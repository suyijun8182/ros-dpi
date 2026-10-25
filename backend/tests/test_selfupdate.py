"""一键自更新加固 + 改密码不掉线：并发锁、SHA256 校验、缺 SHA256SUMS 拒绝、坏包可读报错、临时文件清理、.bak 备份。"""
import hashlib
import io
import os
import tarfile
import threading

import pytest
from fastapi.testclient import TestClient

from app import security, selfupdate
from app.main import app


def _tar(name="ros-dpi", size=selfupdate._MIN_SIZE + 10) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        data = b"\x7fELF" + b"\0" * (size - 4)
        ti = tarfile.TarInfo(name)
        ti.size = len(data)
        tf.addfile(ti, io.BytesIO(data))
    return buf.getvalue()


@pytest.fixture
def fake(tmp_path, monkeypatch):
    """模拟冻结环境：二进制在 tmp_path 里，GitHub 下载由 state 决定"""
    exe = tmp_path / "ros-dpi"
    exe.write_bytes(b"old-binary")
    state = {"tar": _tar(), "sums": None, "restarted": 0}
    state["sums"] = f"{hashlib.sha256(state['tar']).hexdigest()}  ros-dpi-linux-amd64.tar.gz\n"

    def get_text(url):
        assert url.endswith("/SHA256SUMS")
        return state["sums"]

    def download(url, f):
        f.write(state["tar"])
        return hashlib.sha256(state["tar"]).hexdigest()

    monkeypatch.setattr(selfupdate, "_frozen", lambda: True)
    monkeypatch.setattr(selfupdate, "latest_release", lambda: ("9.9.9", ""))
    monkeypatch.setattr(selfupdate, "_arch", lambda: "amd64")
    monkeypatch.setattr(selfupdate, "_exe", lambda: str(exe))
    monkeypatch.setattr(selfupdate, "_get_text", get_text)
    monkeypatch.setattr(selfupdate, "_download", download)
    monkeypatch.setattr(selfupdate, "_restart", lambda: state.__setitem__("restarted", state["restarted"] + 1))
    state["exe"] = exe
    state["dir"] = tmp_path
    return state


def _leftovers(d):
    return [p for p in os.listdir(d) if p.startswith(".ros-dpi-update-")]


def test_update_ok_with_backup(fake):
    res = selfupdate.perform("0.6.0")
    assert res["ok"] and ".bak" in res["message"]
    assert fake["exe"].stat().st_size > selfupdate._MIN_SIZE
    assert (fake["dir"] / "ros-dpi.bak").read_bytes() == b"old-binary"
    assert fake["restarted"] == 1 and _leftovers(fake["dir"]) == []


def test_update_refuses_without_sha256sums(fake):
    fake["sums"] = None
    with pytest.raises(RuntimeError, match="SHA256SUMS"):
        selfupdate.perform("0.6.0")
    assert fake["exe"].read_bytes() == b"old-binary" and fake["restarted"] == 0


def test_update_hash_mismatch(fake):
    fake["sums"] = "0" * 64 + "  ros-dpi-linux-amd64.tar.gz\n"
    with pytest.raises(RuntimeError, match="校验失败"):
        selfupdate.perform("0.6.0")
    assert fake["exe"].read_bytes() == b"old-binary" and _leftovers(fake["dir"]) == []


def test_update_tar_without_binary(fake):
    fake["tar"] = _tar(name="README")
    fake["sums"] = f"{hashlib.sha256(fake['tar']).hexdigest()}  ros-dpi-linux-amd64.tar.gz\n"
    with pytest.raises(RuntimeError, match="找不到"):
        selfupdate.perform("0.6.0")
    assert fake["exe"].read_bytes() == b"old-binary" and _leftovers(fake["dir"]) == []


def test_update_network_error_readable(fake, monkeypatch):
    import httpx

    def boom(url, f):
        raise httpx.ConnectError("no route")
    monkeypatch.setattr(selfupdate, "_download", boom)
    with pytest.raises(RuntimeError, match="连接 GitHub 失败"):
        selfupdate.perform("0.6.0")
    assert _leftovers(fake["dir"]) == []


def test_update_concurrent_busy(fake, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    orig = fake["tar"]

    def slow(url, f):
        entered.set()
        release.wait(5)
        f.write(orig)
        return hashlib.sha256(orig).hexdigest()
    monkeypatch.setattr(selfupdate, "_download", slow)
    t = threading.Thread(target=selfupdate.perform, args=("0.6.0",))
    t.start()
    try:
        assert entered.wait(5)
        with pytest.raises(selfupdate.Busy):
            selfupdate.perform("0.6.0")
    finally:
        release.set()
        t.join(5)
    assert not selfupdate._lock.locked()


def _admin(c):
    security._login_fails.clear()
    if not c.get("/api/auth/status").json()["initialized"]:
        c.post("/api/auth/setup", json={"username": "admin", "password": "secret1"})
    return {"Authorization": "Bearer " + c.post("/api/auth/login", json={"username": "admin", "password": "secret1"}).json()["token"]}


def test_update_route_409_and_400(monkeypatch):
    with TestClient(app) as c:
        h = _admin(c)

        def busy(cur):
            raise selfupdate.Busy("已有一次更新正在进行，请稍候")
        monkeypatch.setattr(selfupdate, "perform", busy)
        assert c.post("/api/system/update", headers=h).status_code == 409

        def bad(cur):
            raise StopIteration
        monkeypatch.setattr(selfupdate, "perform", bad)
        r = c.post("/api/system/update", headers=h)
        assert r.status_code == 400 and "StopIteration" in r.json()["detail"]


def test_change_password_returns_fresh_token():
    with TestClient(app) as c:
        ha = _admin(c)
        assert c.post("/api/auth/users", json={"username": "pwfresh", "password": "fresh111", "role": "user"},
                      headers=ha).status_code == 200
        security._login_fails.clear()
        h = {"Authorization": "Bearer " + c.post("/api/auth/login", json={"username": "pwfresh", "password": "fresh111"}).json()["token"]}
        r = c.post("/api/auth/password", json={"old_password": "fresh111", "new_password": "fresh222"}, headers=h)
        assert r.status_code == 200 and r.json()["token"]
        assert c.get("/api/auth/me", headers=h).status_code == 401            # 旧 token 失效
        h2 = {"Authorization": "Bearer " + r.json()["token"]}
        assert c.get("/api/auth/me", headers=h2).json()["username"] == "pwfresh"   # 新 token 直接可用
