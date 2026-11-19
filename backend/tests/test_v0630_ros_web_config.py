from types import SimpleNamespace

import httpx
import pytest

from app.config import get_settings
from app.ros_poller import RosPoller, effective


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
