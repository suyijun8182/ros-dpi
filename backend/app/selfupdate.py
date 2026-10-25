"""Linux 二进制部署的自更新（debug18）：检测新版本、下载、原子替换二进制、自动重启服务。

- 只对 PyInstaller 打包的二进制部署生效（sys.frozen）；Docker 部署请用 docker compose pull。
- 替换用 os.replace（rename 是原子元数据操作，正在运行的二进制可以被 rename 覆盖，不会 ETXTBSY），
  然后 spawn 一个脱离会话的 shell 延迟 systemctl restart——服务重启即换新版本，全程不需要登录 Linux。
"""
import os
import sys
import time

import httpx

REPO = "suyijun8182/ros-dpi"
_state = {"checked": 0, "latest": "", "error": ""}


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


def perform(current: str) -> dict:
    """下载新版本二进制 → 原子替换 → 延迟重启服务。返回给前端的说明"""
    if not _frozen():
        raise RuntimeError("仅二进制部署支持一键更新；Docker 部署请在服务器上执行 docker compose pull && docker compose up -d")
    latest, err = latest_release()
    if err or not latest:
        raise RuntimeError(f"取不到最新版本：{err or '未知'}")
    if _ver_tuple(latest) <= _ver_tuple(current):
        return {"ok": True, "message": f"已经是最新版本 {current}"}
    arch = {"x86_64": "amd64", "aarch64": "arm64"}.get(os.uname().machine)
    if not arch:
        raise RuntimeError(f"不支持的架构：{os.uname().machine}")
    url = f"https://github.com/{REPO}/releases/download/v{latest}/ros-dpi-linux-{arch}.tar.gz"
    exe = os.path.realpath(sys.executable)
    tmp_tar = exe + ".update.tar.gz"
    tmp_bin = exe + ".update"
    with httpx.stream("GET", url, timeout=300.0, follow_redirects=True) as r:
        r.raise_for_status()
        with open(tmp_tar, "wb") as f:
            for chunk in r.iter_bytes(1 << 16):
                f.write(chunk)
    import tarfile
    with tarfile.open(tmp_tar) as tf:
        member = next(m for m in tf.getmembers() if m.name.endswith("ros-dpi") or m.name == "ros-dpi")
        extracted = tf.extractfile(member)
        with open(tmp_bin, "wb") as f:
            f.write(extracted.read())
    os.remove(tmp_tar)
    if os.path.getsize(tmp_bin) < 10 * 1024 * 1024:
        os.remove(tmp_bin)
        raise RuntimeError("下载的二进制不完整，已取消")
    os.chmod(tmp_bin, 0o755)
    # rename 是原子操作：正在运行的二进制可以被 rename 覆盖（inode 仍由进程持有）
    os.replace(tmp_bin, exe)
    import subprocess
    subprocess.Popen(["sh", "-c", "sleep 2; systemctl restart ros-dpi"],
                     start_new_session=True)
    return {"ok": True, "message": f"已更新到 {latest}，服务正在自动重启（约 5 秒）"}
