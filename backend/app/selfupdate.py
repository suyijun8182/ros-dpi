"""Linux 二进制部署的自更新（debug18）：检测新版本、下载、原子替换二进制、自动重启服务。

- 只对 PyInstaller 打包的二进制部署生效（sys.frozen）；Docker 部署请用 docker compose pull。
- 替换用 os.replace（rename 是原子元数据操作，正在运行的二进制可以被 rename 覆盖，不会 ETXTBSY），
  然后重启服务换上新版本，全程不需要登录 Linux：
  0.6.24 起 install.sh 以专用用户 ros-dpi 运行服务，二进制放在 <安装目录>/bin（该用户可写），
  重启靠进程自己退出、由 systemd 的 Restart=always 拉起；旧版装出来的 root 服务仍用 systemctl restart。
- 完整性：先下载 Release 里的 SHA256SUMS，tar 包哈希对不上（或 Release 没有 SHA256SUMS）一律拒绝更新。
- 替换前把旧二进制留成 <binary>.bak，新版本起不来时可以手工 mv 回去。
"""
import hashlib
import os
import platform
import shutil
import signal
import subprocess
import sys
import tarfile
import tempfile
import threading
import time

import httpx

REPO = "suyijun8182/ros-dpi"
_state = {"checked": 0, "latest": "", "error": ""}
_lock = threading.Lock()   # 同一时间只允许一次更新（非阻塞获取，第二个请求直接返回“正在更新”）
_MIN_SIZE = 10 * 1024 * 1024


class Busy(RuntimeError):
    """已有一次更新在进行中（路由层转成 HTTP 409）"""


def _frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def latest_release() -> tuple[str, str]:
    """(最新版本号, 错误)；缓存 1 小时，避免每次打开设置页都打 GitHub API"""
    if time.time() - _state["checked"] < 3600 and (_state["latest"] or _state["error"]):
        return _state["latest"], _state["error"]
    tag, err = "", ""
    try:
        r = httpx.get(f"https://api.github.com/repos/{REPO}/releases/latest", timeout=10.0,
                      headers={"User-Agent": "ros-dpi"})
        r.raise_for_status()
        tag = str(r.json().get("tag_name") or "").lstrip("v")
    except Exception as e:  # noqa: BLE001
        err = f"{type(e).__name__}: {str(e)[:120]}"
    _state.update(checked=int(time.time()), latest=tag, error=err)
    return tag, err


def _ver_tuple(v: str) -> tuple:
    parts = []
    for x in v.split("."):
        parts.append(int("".join(ch for ch in x if ch.isdigit()) or 0))
    return tuple(parts + [0] * (3 - len(parts)))


def status(current: str) -> dict:
    latest, err = latest_release()
    available = bool(latest and err == "" and _ver_tuple(latest) > _ver_tuple(current))
    return {"current": current, "latest": latest, "available": available,
            "supported": _frozen(), "error": err}


def _exe() -> str:
    return os.path.realpath(sys.executable)


def _arch() -> str:
    m = platform.machine().lower()
    arch = {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64"}.get(m)
    if not arch:
        raise RuntimeError(f"不支持的架构：{m}")
    return arch


def _get_text(url: str) -> str | None:
    """下载小文本文件；404 返回 None（用来判断 Release 里有没有 SHA256SUMS）"""
    r = httpx.get(url, timeout=30.0, follow_redirects=True, headers={"User-Agent": "ros-dpi"})
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.text


def _download(url: str, f) -> str:
    """流式下载到已打开的文件对象，返回 sha256 十六进制"""
    h = hashlib.sha256()
    with httpx.stream("GET", url, timeout=300.0, follow_redirects=True, headers={"User-Agent": "ros-dpi"}) as r:
        r.raise_for_status()
        for chunk in r.iter_bytes(1 << 16):
            h.update(chunk)
            f.write(chunk)
    return h.hexdigest()


def _parse_sums(text: str) -> dict[str, str]:
    """sha256sum 输出格式：<hash>  <文件名>（二进制模式文件名前带 *）"""
    out = {}
    for line in text.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) == 2 and len(parts[0]) == 64:
            out[parts[1].strip().lstrip("*")] = parts[0].lower()
    return out


def _restart():
    if os.geteuid() == 0:
        subprocess.Popen(["sh", "-c", "sleep 2; systemctl restart ros-dpi"], start_new_session=True)
        return
    # 非 root 没有 systemctl 权限：2 秒后（先让这次请求的响应发出去）给自己发 SIGTERM，
    # 正常走关闭流程（落库），退出后 systemd 按 Restart=always 用新二进制拉起
    threading.Timer(2.0, os.kill, (os.getpid(), signal.SIGTERM)).start()


def perform(current: str) -> dict:
    """下载新版本二进制 → 校验 SHA256 → 备份旧版 → 原子替换 → 延迟重启服务。返回给前端的说明。
    所有失败都转成 RuntimeError（可读的中文说明），并发调用抛 Busy"""
    if not _lock.acquire(blocking=False):
        raise Busy("已有一次更新正在进行，请稍候")
    try:
        return _perform(current)
    except RuntimeError:
        raise
    except httpx.HTTPStatusError as e:
        raise RuntimeError(f"下载失败：HTTP {e.response.status_code} {e.request.url}") from e
    except httpx.HTTPError as e:
        raise RuntimeError(f"连接 GitHub 失败：{type(e).__name__}: {str(e)[:120]}") from e
    except tarfile.TarError as e:
        raise RuntimeError(f"更新包损坏，无法解压：{str(e)[:120]}") from e
    except OSError as e:
        raise RuntimeError(f"写入文件失败：{type(e).__name__}: {str(e)[:120]}") from e
    except Exception as e:  # noqa: BLE001  兜底：任何意外都给出可读原因，而不是 500
        raise RuntimeError(f"更新失败：{type(e).__name__}: {str(e)[:120]}") from e
    finally:
        _lock.release()


def _perform(current: str) -> dict:
    if not _frozen():
        raise RuntimeError("仅二进制部署支持一键更新；Docker 部署请在服务器上执行 docker compose pull && docker compose up -d")
    latest, err = latest_release()
    if err or not latest:
        raise RuntimeError(f"取不到最新版本：{err or '未知'}")
    if _ver_tuple(latest) <= _ver_tuple(current):
        return {"ok": True, "message": f"已经是最新版本 {current}"}
    asset = f"ros-dpi-linux-{_arch()}.tar.gz"
    base = f"https://github.com/{REPO}/releases/download/v{latest}"
    sums = _get_text(f"{base}/SHA256SUMS")
    if sums is None:
        raise RuntimeError(f"v{latest} 的 Release 里没有 SHA256SUMS 校验文件，为安全起见拒绝更新（可稍后再试或手工安装）")
    want = _parse_sums(sums).get(asset)
    if not want:
        raise RuntimeError(f"SHA256SUMS 里没有 {asset} 的校验值，拒绝更新")

    exe = _exe()
    d = os.path.dirname(exe)
    if not os.access(d, os.W_OK):
        raise RuntimeError(f"服务账号没有 {d} 的写权限，无法替换二进制：请重新执行一键安装命令（会把二进制迁到安装目录下）后再更新")
    # 临时文件放在二进制同目录：保证 os.replace 是同一文件系统内的原子 rename；名字唯一，互不覆盖
    tmps = []

    def _mktemp(suffix: str) -> str:
        fd, path = tempfile.mkstemp(dir=d, prefix=".ros-dpi-update-", suffix=suffix)
        os.close(fd)
        tmps.append(path)
        return path

    bak = exe + ".bak"
    try:
        tmp_tar, tmp_bin = _mktemp(".tar.gz"), _mktemp(".bin")
        with open(tmp_tar, "wb") as f:
            got = _download(f"{base}/{asset}", f)
        if got != want:
            raise RuntimeError(f"{asset} 校验失败（SHA256 不匹配），已取消更新")
        with tarfile.open(tmp_tar) as tf, open(tmp_bin, "wb") as f:
            member = next((m for m in tf.getmembers() if m.isfile() and os.path.basename(m.name) == "ros-dpi"), None)
            if member is None:
                raise RuntimeError("更新包里找不到 ros-dpi 二进制，已取消")
            shutil.copyfileobj(tf.extractfile(member), f, 1 << 16)
        if os.path.getsize(tmp_bin) < _MIN_SIZE:
            raise RuntimeError("下载的二进制不完整，已取消")
        os.chmod(tmp_bin, 0o755)
        # 旧二进制留一份 .bak：硬链接零拷贝（同一 inode），不支持硬链接的文件系统退回复制
        if os.path.lexists(bak):
            os.remove(bak)
        try:
            os.link(exe, bak)
        except OSError:
            shutil.copy2(exe, bak)
        # rename 是原子操作：正在运行的二进制可以被 rename 覆盖（inode 仍由进程持有）
        os.replace(tmp_bin, exe)
    finally:
        for p in tmps:   # 成功时 tmp_bin 已被 rename 走，只剩 tar；失败时两个都清掉
            try:
                if os.path.exists(p):
                    os.remove(p)
            except OSError:
                pass
    rollback = f"旧版本已备份为 {bak}，新版本起不来时可手工 mv 回去再 sudo systemctl restart ros-dpi"
    try:
        _restart()
    except OSError as e:   # 二进制已经换好，只是没能自动重启：提示手工重启，不当作失败
        return {"ok": True, "message": f"已更新到 {latest}，但自动重启失败（{e}），请手工 sudo systemctl restart ros-dpi。{rollback}"}
    return {"ok": True, "message": f"已更新到 {latest}，服务正在自动重启（约 5 秒）。{rollback}"}
