import ssl
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from app import database
from app.main import _apply_saved, app
from app.models import DEFAULT_SITE, OpLog, Setting, Site

from app.config import get_settings
from app.ros_poller import ROS_KEYS, RosPoller, _explain, effective, poller


@pytest.mark.parametrize(("env", "saved", "url", "source", "tls"), [
    ("https://env", {}, "https://env", "env", True),
    ("https://env", {"ros_url": "http://web", "ros_verify_tls": "0"}, "http://web", "web", False),
    ("https://env", {"ros_url": "", "ros_verify_tls": "1"}, "", "web", True),
    ("", {}, "", "none", True),
])
def test_effective(monkeypatch, env, saved, url, source, tls):
    monkeypatch.setattr(get_settings(), "ros_url", env)
    monkeypatch.setattr(get_settings(), "ros_verify_tls", True)
    cfg = effective(saved)
    assert (cfg["ros_url"], cfg["source"], cfg["ros_verify_tls"]) == (url, source, tls)


def test_reconfigure():
    p = RosPoller(SimpleNamespace(ros_managed=False))
    assert p.configure("https://first", "u", "p", False)
    p.identity, p.wan_override = "first", "wan"
    p.leases["mac"] = {}
    p.samples.append((1, 2, 3))
    assert not p.configure("https://first", "u", "p", False)
    assert p.identity and p.samples and p.leases and p.engine.ros_managed
    assert p.configure("https://second", "u", "p", False)
    assert not (p.identity or p.samples or p.leases)
    assert p.wan_override == "wan"
    assert p.configure("", "", "", False) and not p.engine.ros_managed


def test_disabled_skips_requests(monkeypatch):
    calls = []
    p = RosPoller(SimpleNamespace())
    monkeypatch.setattr(p, "_client", lambda *args: httpx.Client(transport=httpx.MockTransport(calls.append)))
    p.poll()
    p.sample()
    assert not calls


@pytest.mark.parametrize("outcome", ["success", "401", "offline"])
def test_probe_is_read_only(monkeypatch, outcome):
    p = RosPoller(SimpleNamespace())
    p.identity = "live"
    calls = []

    def handler(request):
        calls.append((request.method, request.url.path))
        if outcome == "offline":
            raise httpx.ConnectError("sensitive detail")
        if outcome == "401":
            return httpx.Response(401, text="sensitive detail")
        return httpx.Response(200, json={"name": "trial", "version": "7", "board-name": "RB"})

    def client(url, user, password, verify_tls, *, timeout):
        assert timeout == 8
        return httpx.Client(base_url=url + "/rest", transport=httpx.MockTransport(handler))

    monkeypatch.setattr(p, "_client", client)
    result = p.probe("https://trial", "user", "pwd", False)
    if outcome == "success":
        assert result == {"ok": True, "identity": "trial", "version": "7", "board": "RB"}
        assert calls == [("GET", "/rest/system/identity"), ("GET", "/rest/system/resource")]
    else:
        assert not result["ok"] and "sensitive detail" not in result["error"]
        assert ("401" if outcome == "401" else "连不上") in result["error"]
    assert p.identity == "live" and not p.enabled and p.last_poll == 0


def test_stale_poll_failure_after_switch(monkeypatch):
    p = RosPoller(SimpleNamespace())
    p.configure("https://first", "u", "p", False)

    def handler(request):
        p.configure("https://second", "u", "p", False)
        return httpx.Response(401)

    monkeypatch.setattr(p, "_client", lambda url, *args: httpx.Client(base_url=url, transport=httpx.MockTransport(handler)))
    p.poll()
    assert p.url == "https://second" and not p.error and not p.last_poll


@pytest.mark.parametrize("wrapped", [True, False])
def test_certificate_failure_gives_tls_hint(wrapped):
    if wrapped:
        error = httpx.ConnectError("connection failed")
        error.__cause__ = OSError("TLS handshake")
        error.__cause__.__context__ = ssl.SSLCertVerificationError("private certificate details")
    else:
        error = httpx.ConnectError("[SSL: CERTIFICATE_VERIFY_FAILED] private certificate details")
    assert _explain(error) == "RouterOS 的 HTTPS 证书校验失败：路由器用自签证书时，请取消勾选「校验 HTTPS 证书」"


@pytest.fixture
def api():
    with TestClient(app) as client:
        if not client.get("/api/auth/status").json()["initialized"]:
            client.post("/api/auth/setup", json={"username": "admin", "password": "secret1"})
        token = client.post("/api/auth/login", json={"username": "admin", "password": "secret1"}).json()["token"]
        client.headers["Authorization"] = f"Bearer {token}"
        yield client
    with database.session() as db:
        db.query(Setting).filter(Setting.key.in_(ROS_KEYS)).delete()
        row = db.get(Site, DEFAULT_SITE)      # 0.7.0：RouterOS 配置存在默认站点行里
        row.ros_url = row.ros_user = row.ros_password = row.ros_verify_tls = None
        db.commit()
    poller.configure("", "", "", False)


def test_settings_save_reload_and_disable(api, monkeypatch):
    calls = []
    monkeypatch.setattr(poller, "poll", lambda: calls.append(poller.url))
    monkeypatch.setattr(get_settings(), "ros_url", "https://env")
    secret = "private-router-password"
    body = {"ros_url": "https://192.168.88.1/rest/", "ros_user": "u", "ros_password": secret, "ros_verify_tls": True}
    response = api.put("/api/settings", json=body)
    assert response.status_code == 200 and secret not in response.text
    cfg = api.get("/api/settings").json()["ros"]
    assert cfg == {"url": "https://192.168.88.1", "user": "u", "has_password": True, "verify_tls": True, "source": "web"}
    assert calls == [cfg["url"]]
    assert api.put("/api/settings", json={"ros_user": "new"}).is_success
    assert poller.user == "new" and poller.password == secret
    assert api.put("/api/settings", json={"ros_user": "new"}).is_success
    assert len(calls) == 2
    poller.configure("", "", "", False)
    _apply_saved()
    assert poller.enabled and poller.verify_tls and poller.password == secret
    for path in ("/api/settings", "/api/system", "/api/audit/oplog"):
        result = api.get(path)
        assert result.is_success and secret not in result.text
    assert api.get("/api/system").json()["router"]["source"] == "web"
    with database.session() as db:
        logs = [row.detail for row in db.query(OpLog).filter_by(action="settings")]
        assert all(secret not in detail for detail in logs)
        assert any('"ros_password": "***"' in detail for detail in logs)
    assert api.post("/api/ros/test").json()["enabled"] and len(calls) == 3
    assert api.put("/api/settings", json={"ros_url": ""}).is_success
    cfg = api.get("/api/settings").json()["ros"]
    assert not poller.enabled and cfg["source"] == "web"
    assert cfg["url"] == cfg["user"] == "" and not cfg["has_password"]
    assert api.post("/api/ros/test").status_code == 400


@pytest.mark.parametrize("url", ["ftp://x", "https://u:p@1.2.3.4", "https://1.2.3.4/?a=1",
                                 "https://router/#part", "http://", "https://host:wrong"])
def test_reject_router_url(api, url):
    assert api.put("/api/settings", json={"ros_url": url}).status_code == 400
    assert api.post("/api/ros/test", json={"url": url}).status_code == 400
    assert not poller.enabled


@pytest.mark.parametrize("status", [200, 401])
def test_trial_uses_saved_password_without_saving(api, monkeypatch, status):
    monkeypatch.setattr(poller, "poll", lambda: None)
    secret = "saved-probe-password"
    assert api.put("/api/settings", json={"ros_url": "https://live", "ros_user": "u", "ros_password": secret}).is_success
    before = poller.status()
    settings = api.get("/api/settings").json()["ros"]

    def handler(request):
        assert request.method == "GET" and request.url.host == "live"
        return httpx.Response(status, json={"name": "trial-router", "version": "7"})

    def client(url, user, password, verify_tls, **kwargs):
        assert (url, user, password, verify_tls) == ("https://LIVE:443", "trial-user", secret, True)
        return httpx.Client(base_url=url + "/rest", transport=httpx.MockTransport(handler))

    monkeypatch.setattr(poller, "_client", client)
    result = api.post("/api/ros/test", json={"url": "https://LIVE:443/rest/", "user": "trial-user", "verify_tls": True}).json()
    if status == 200:
        assert result["ok"] and result["identity"] == "trial-router"
    else:
        assert not result["ok"] and "拒绝登录（401）" in result["error"]
    assert poller.status() == before and api.get("/api/settings").json()["ros"] == settings


@pytest.mark.parametrize(("source", "new_url", "password_fields"), [
    ("web", "https://other", {}),
    ("web", "http://live", {"password": ""}),
    ("env", "https://live:8443", {}),
])
def test_origin_change_rejected_before_network_or_save(api, monkeypatch, source, new_url, password_fields):
    if source == "env":
        monkeypatch.setattr(get_settings(), "ros_url", "https://live")
        monkeypatch.setattr(get_settings(), "ros_password", "saved-password")
        _apply_saved()
    else:
        monkeypatch.setattr(poller, "poll", lambda: None)
        assert api.put("/api/settings", json={"ros_url": "https://live", "ros_password": "saved-password"}).is_success
    before = api.get("/api/settings").json()["ros"]
    with monkeypatch.context() as guard:
        guard.setattr(poller, "_client", lambda *a, **kw: pytest.fail("unexpected RouterOS connection"))
        guard.setattr(poller, "configure", lambda *a, **kw: pytest.fail("unexpected reconfiguration"))
        result = api.post("/api/ros/test", json={"url": new_url, **password_fields})
        assert result.is_success and result.json() == {"ok": False, "error": "地址改了，请重新输入密码再测试"}
        changes = {"ros_" + k: v for k, v in password_fields.items()}
        saved = api.put("/api/settings", json={"ros_url": new_url, **changes})
        assert saved.status_code == 400 and saved.json()["detail"] == "地址改了，请重新输入密码"
    assert before == api.get("/api/settings").json()["ros"] and before["source"] == source
    assert poller.url == "https://live"


def test_same_origin_save_preserves_password(api, monkeypatch):
    monkeypatch.setattr(poller, "poll", lambda: None)
    assert api.put("/api/settings", json={"ros_url": "http://router/", "ros_password": "saved"}).is_success
    assert api.put("/api/settings", json={"ros_url": "http://ROUTER:80/rest"}).is_success
    assert poller.url == "http://ROUTER:80" and poller.password == "saved"


def test_new_origin_uses_explicit_password(api, monkeypatch):
    polls = []
    monkeypatch.setattr(poller, "poll", lambda: polls.append((poller.url, poller.password)))
    assert api.put("/api/settings", json={"ros_url": "https://live", "ros_password": "old"}).is_success
    target = "https://second"

    def client(url, user, password, verify_tls, **kwargs):
        assert (url, password) == (target, "new")
        return httpx.Client(base_url=url, transport=httpx.MockTransport(lambda r: httpx.Response(200, json={})))

    monkeypatch.setattr(poller, "_client", client)
    assert api.post("/api/ros/test", json={"url": target, "password": "new"}).json()["ok"]
    assert poller.url == "https://live" and len(polls) == 1
    assert api.put("/api/settings", json={"ros_url": target, "ros_password": "new"}).is_success
    assert polls[-1] == (target, "new")


def test_viewer_cannot_write_or_probe(api):
    user = {"username": "ros-viewer", "password": "viewer-pass"}
    created = api.post("/api/auth/users", json={**user, "role": "user"})
    assert created.is_success
    try:
        token = api.post("/api/auth/login", json=user).json()["token"]
        headers = {"Authorization": f"Bearer {token}"}
        assert api.put("/api/settings", json={"ros_url": "http://trial"}, headers=headers).status_code == 403
        assert api.post("/api/ros/test", json={"url": "http://trial"}, headers=headers).status_code == 403
    finally:
        api.delete(f"/api/auth/users/{created.json()['id']}")
