"""社区共享库（debug16 → 0.6.21 重做）：项目自带社区主站——注册 / 令牌、心跳 + 投票、按来源网络聚合防刷票、
ETag 304、部署量；普通实例的完整同步流程走真实的主站端点（TestClient），不打桩协议本身。"""
import gzip
import json

import pytest
from fastapi.testclient import TestClient

from app import database, share
from app.classify.local import local
from app.config import get_settings
from app.engine import engine
from app.main import app
from app.models import HostDomainDay, Setting, ShareDeployment, ShareDomain, ShareEntry
from app.routers import share as share_router

DAY = 1792900000
HOST = "IP:192.168.88.41"
HUB = "http://testserver"


def _clean(db):
    for m in (ShareEntry, ShareDomain, ShareDeployment):
        db.query(m).delete(synchronize_session=False)
    db.query(HostDomainDay).filter(HostDomainDay.host == HOST).delete(synchronize_session=False)
    for k in ("share_client_instance", "share_client_token", "share_client_hub", "share_hub_instance"):
        row = db.get(Setting, k)
        if row is not None:
            db.delete(row)
    db.commit()


@pytest.fixture()
def hub(monkeypatch, tmp_path):
    """本进程同时当社区主站和普通实例：主站端点由 TestClient 提供；X-Test-IP 头模拟不同实例的来源地址"""
    s = get_settings()
    monkeypatch.setattr(s, "share_hub", True)
    monkeypatch.setattr(s, "share_hub_url", HUB)
    monkeypatch.setattr(share, "LIB_REBUILD_GAP", 0)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setattr(share_router, "_source", lambda req: req.headers.get("x-test-ip") or "203.0.113.9")
    database.connect_from_saved(force=True)
    with database.session() as db:
        _clean(db)
    share.reset_library_cache()
    local.reset()
    c = TestClient(app)
    state = {"ip": "198.51.100.1"}

    class _Client:
        """client_cycle 用的 httpx.Client 替身：请求转给 TestClient，并带上当前模拟的来源地址"""
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, **kw):
            kw["headers"] = {**(kw.get("headers") or {}), "X-Test-IP": state["ip"]}
            return c.post(url, **kw)

        def get(self, url, **kw):
            kw["headers"] = {**(kw.get("headers") or {}), "X-Test-IP": state["ip"]}
            return c.get(url, **kw)

    monkeypatch.setattr(share, "_http", lambda: _Client())
    yield c, state
    with database.session() as db:
        _clean(db)
    share.reset_library_cache()
    local.reset()


def _as_new_instance(state, ip):
    """换成另一台实例：清掉本机保存的注册信息，换来源地址"""
    with database.session() as db:
        for k in ("share_client_instance", "share_client_token", "share_client_hub"):
            row = db.get(Setting, k)
            if row is not None:
                db.delete(row)
        db.commit()
    share._client.update(votes_ts=0, etag="")
    state["ip"] = ip


def _seed(db, rows):
    for dom, app, b in rows:
        db.add(HostDomainDay(ts=DAY, host=HOST, domain=dom, app=app, base=None, bytes=b))
    db.commit()


def _client_cycle():
    with database.session() as db:
        res = share.client_cycle(engine, db)
        db.commit()
    return res


def test_export_filters_private():
    database.connect_from_saved(force=True)
    with database.session() as db:
        _clean(db)
        _seed(db, [("93.184.216.34", "douyin", 800), ("192.168.8.5", "douyin", 999),
                   ("239.255.255.250", "douyin", 999), ("v.douyin.com", "douyin", 50)])
        entries, domains = share.export_entries(engine, db)
        _clean(db)
    ips = {e["ip"] for e in entries}
    assert "93.184.216.34" in ips and not ips & {"192.168.8.5", "239.255.255.250"}   # 私网 / 组播不出门
    assert "v.douyin.com" in {d["domain"] for d in domains}


def test_client_ip_behind_proxy():
    # 直连公网：用 TCP 对端，伪造的 X-Forwarded-For 无效
    assert share.client_ip("8.8.8.8", "1.1.1.1", None) == "8.8.8.8"
    # 反向代理在内网：取代理追加在最右边的公网地址
    assert share.client_ip("192.168.8.1", "1.1.1.1, 9.9.9.9", None) == "9.9.9.9"
    assert share.client_ip("127.0.0.1", "10.0.0.5", "9.9.9.9") == "9.9.9.9"


def test_two_networks_publish_end_to_end(hub):
    c, state = hub
    with database.session() as db:
        _seed(db, [("1.2.3.4", "douyin", 500), ("v.douyin.com", "douyin", 300)])

    # 第一台：注册 + 上报；只有一个网络见过，社区库为空
    res = _client_cycle()
    assert res["total"] == 1 and res["online"] == 1 and res["community_ips"] == 0
    assert share.sync_state()["ok"] is True and local.ip_app("1.2.3.4") is None

    # 第二台（另一个网络）投了同样的结论：两网一致 → 进社区库，本机自学习的社区层生效
    _as_new_instance(state, "203.0.113.50")
    res = _client_cycle()
    assert res["total"] == 2 and res["community_ips"] >= 1 and res["community_domains"] >= 1
    assert local.ip_app("1.2.3.4") == "douyin"
    assert local.domain_app("v.douyin.com") == "douyin"

    # 社区库没变化：带 ETag 再拉是 304，结果沿用；缓存文件已写，重启后可直接加载
    etag = share._client["etag"]
    assert etag and c.get(HUB + share.API + "/library", headers={"If-None-Match": etag}).status_code == 304
    local.reset()
    share.load_cached_library()
    assert local.ip_app("1.2.3.4") == "douyin"

    # 公开的部署量
    assert c.get(HUB + share.API + "/stats").json() == {"total": 2, "online": 2, "offline": 0}


def test_same_network_counts_once(hub):
    """一个人在同一网络里伪造多个实例：只算一票，进不了社区库"""
    c, state = hub
    with database.session() as db:
        _seed(db, [("5.6.7.8", "bilibili", 100)])
    _client_cycle()
    _as_new_instance(state, "198.51.100.77")     # 同一个 /24
    res = _client_cycle()
    assert res["total"] == 2 and res["community_ips"] == 0 and local.ip_app("5.6.7.8") is None


def test_majority_and_whitelist(hub):
    c, _state = hub
    with database.session() as db:
        rows = []
        for i, ip in enumerate(("1.0.0.1", "2.0.0.1", "3.0.0.1")):
            iid, _t = share.register(db, share.net_of(db, ip), "t")
            db.flush()
            rows.append(db.get(ShareDeployment, iid))
        cls = engine.classifier
        share.report(db, rows[0], rows[0].net, {"entries": [{"ip": "8.8.8.8", "app": "douyin", "bytes": 1}]}, cls)
        share.report(db, rows[1], rows[1].net, {"entries": [{"ip": "8.8.8.8", "app": "douyin", "bytes": 1}]}, cls)
        share.report(db, rows[2], rows[2].net, {"entries": [{"ip": "8.8.8.8", "app": "bilibili", "bytes": 10 ** 9},
                                                            {"ip": "9.9.9.9", "app": "made_up_app", "bytes": 1},
                                                            {"ip": "10.0.0.1", "app": "douyin", "bytes": 1}]}, cls)
        db.commit()
        lib = share.build_library(db)
        n = db.query(ShareEntry).filter(ShareEntry.reporter == rows[2].instance).count()
    assert lib["entries"] == [{"ip": "8.8.8.8", "app": "douyin"}]   # 两个网络对一个网络：按网络数，不按字节
    assert n == 1                                                    # 编造的应用、私网地址被拒收


def test_auth_and_limits(hub):
    c, _state = hub
    url = HUB + share.API
    assert c.post(url + "/report", json={"version": "x"}).status_code == 401
    reg = c.post(url + "/register", json={"version": "x"}, headers={"X-Test-IP": "192.0.2.1"}).json()
    bad = {"Authorization": f"Bearer {reg['instance']}:wrong"}
    assert c.post(url + "/report", json={"version": "x"}, headers=bad).status_code == 401
    ok = {"Authorization": f"Bearer {reg['instance']}:{reg['token']}", "Content-Encoding": "gzip"}
    assert c.post(url + "/report", content=gzip.compress(json.dumps({"version": "x"}).encode()), headers=ok).json()["ok"]
    # 解压后超限：拒收（防压缩炸弹）
    bomb = gzip.compress(b" " * (share.MAX_INFLATED + 10))
    assert c.post(url + "/report", content=bomb, headers=ok).status_code == 413
    # 同一网络一天注册超限
    for i in range(share.REGISTER_PER_NET):
        assert c.post(url + "/register", json={}, headers={"X-Test-IP": f"100.20.30.{i}"}).status_code == 200
    assert c.post(url + "/register", json={}, headers={"X-Test-IP": "100.20.30.200"}).status_code == 429


def test_hub_counts_itself_in_process(hub):
    """主站自己的投票在进程内计入（不经网络）：主站 + 一个普通实例两网一致即发布"""
    c, state = hub
    with database.session() as db:
        _seed(db, [("4.4.4.4", "douyin", 100)])
        res = share.hub_cycle(engine, db)
        db.commit()
    assert res["total"] == 1 and res["community_ips"] == 0
    assert local.ip_app("4.4.4.4") is None
    _client_cycle()
    with database.session() as db:
        share._lib["dirty"] = True
        res = share.hub_cycle(engine, db)
        db.commit()
    assert res["total"] == 2 and res["community_ips"] >= 1 and local.ip_app("4.4.4.4") == "douyin"


def test_non_hub_404(monkeypatch):
    monkeypatch.setattr(get_settings(), "share_hub", False)
    c = TestClient(app)
    for path in ("/stats", "/library"):
        assert c.get(share.API + path).status_code == 404
    assert c.post(share.API + "/register", json={}).status_code == 404


def test_client_error_is_reported(monkeypatch):
    """主站不可达：设置页能看到原因，社区库沿用缓存"""
    import httpx

    database.connect_from_saved(force=True)
    monkeypatch.setattr(get_settings(), "share_hub", False)
    monkeypatch.setattr(get_settings(), "share_hub_url", "http://127.0.0.1:9")

    class _Down:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, **kw):
            raise httpx.ConnectError("connection refused")
        get = post

    monkeypatch.setattr(share, "_http", lambda: _Down())
    with database.session() as db:
        with pytest.raises(httpx.ConnectError):
            share.cycle(engine, db)
    st = share.sync_state()
    assert st["ok"] is False and "ConnectError" in st["error"]


def test_no_ipv6_egress_message():
    """实例不需要公网 IP，但主站只有 IPv6：容器没有 IPv6 出口时给出能照着做的提示"""
    import httpx
    msg = share._err(httpx.ConnectError("[Errno 101] Network is unreachable"))
    assert "IPv6" in msg and "Docker" in msg


def test_hub_url_from_settings(monkeypatch):
    """debug23：社区主站地址可在网页填写（优先于环境变量），空字符串恢复内置默认；地址格式校验"""
    monkeypatch.setattr(get_settings(), "share_hub", False)
    monkeypatch.setattr(get_settings(), "share_hub_url", "https://builtin.example:8443")
    with TestClient(app) as c:
        if not c.get("/api/auth/status").json()["initialized"]:
            c.post("/api/auth/setup", json={"username": "admin", "password": "secret1"})
        h = {"Authorization": "Bearer " + c.post("/api/auth/login", json={"username": "admin", "password": "secret1"}).json()["token"]}
        assert c.put("/api/settings", json={"share_hub_url": "hub.example.com"}, headers=h).status_code == 400
        r = c.put("/api/settings", json={"share_hub_url": "https://hub.example.com/"}, headers=h).json()
        assert r["share_hub_url"] == "https://hub.example.com"
        st = c.get("/api/system/deployments", headers=h).json()
        assert st["hub_url"] == "https://hub.example.com" and st["custom_hub"]
        assert st["default_hub_url"] == "https://builtin.example:8443"
        c.put("/api/settings", json={"share_hub_url": ""}, headers=h)
        st = c.get("/api/system/deployments", headers=h).json()
        assert st["hub_url"] == "https://builtin.example:8443" and not st["custom_hub"]
