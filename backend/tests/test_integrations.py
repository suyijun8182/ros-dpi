import gzip
import time

import httpx
from fastapi.testclient import TestClient

from app import integrations
from app.asn import asndb
from app.classify import Classifier
from app.engine import Engine
from app.main import app


def _engine():
    e = Engine()
    e.set_lan("192.168.8.0/24")
    return e


def _fake_get(responses):
    """把 httpx.get 换成按 URL 路径返回固定 JSON 的假实现（每次调用取列表里的下一个）"""
    def get(url, params=None, headers=None, timeout=None):
        path = httpx.URL(url).path
        body = responses[path].pop(0) if isinstance(responses[path], list) else responses[path]
        return httpx.Response(200, json=body, request=httpx.Request("GET", url))
    return get


def conn(cid, src, host, up, down, dst=""):
    return {"id": cid, "upload": up, "download": down, "chains": ["HK"],
            "metadata": {"sourceIP": src, "sourcePort": "50000", "host": host, "destinationIP": dst,
                         "destinationPort": "443", "network": "tcp"}}


def test_singbox_attributes_proxied_traffic_to_clients(monkeypatch):
    e = _engine()
    sb = integrations.SingboxPoller(e)
    sb.configure("http://192.168.8.249:9090", "s3cret")
    e.set_proxy({"192.168.8.249"}, True)
    monkeypatch.setattr(integrations.httpx, "get", _fake_get({
        "/version": {"version": "sing-box 1.13"},
        "/connections": [{"connections": [conn("a", "192.168.8.20", "www.youtube.com", 100, 1000)]},
                         {"connections": [conn("a", "192.168.8.20", "www.youtube.com", 150, 5000)]}],
    }))
    sb.poll()
    sb.poll()
    assert sb.ok and sb.conns == 1 and sb.bytes == 5150
    key = "IP:192.168.8.20"
    assert e._buf[(key, "youtube")][:2] == [150, 5000]
    # 路由器看到的代理出口隧道、终端发往 FakeIP 的流量不再重复计
    with e.lock:
        assert e.add_flow(dict(src="192.168.8.249", dst="104.1.2.3", sport=1, dport=443, proto=6, bytes=9000), time.time()) is None
        assert e.add_flow(dict(src="192.168.8.20", dst="198.18.0.7", sport=1, dport=443, proto=6, bytes=50), time.time()) is None
    assert e.stats["proxied_skipped"] == 9050 and e.stats["match"]["proxy"] == 5150


def test_without_clash_api_proxy_traffic_is_labeled_tunnel():
    e = _engine()
    e.set_proxy({"192.168.8.249"}, False)
    with e.lock:
        r = e.add_flow(dict(src="192.168.8.249", dst="104.1.2.3", sport=1, dport=443, proto=6, bytes=9000), time.time())
    assert r[1] == "proxy_tunnel"


def test_mosdns_logs_give_per_client_domains(monkeypatch):
    e = _engine()
    md = integrations.MosdnsPoller(e)
    md.configure("http://192.168.8.248:9099/")
    log = lambda t, tid, name, ip: {"client_ip": "192.168.8.30", "query_name": name, "query_time": t, "trace_id": tid,
                                    "answers": [{"type": "A", "ttl": 60, "data": ip}]}
    monkeypatch.setattr(integrations.httpx, "get", _fake_get({"/api/v2/audit/logs": [
        {"logs": [log("2026-10-23T00:00:02+08:00", "2", "www.bilibili.com", "203.0.113.5")]},
        {"logs": [log("2026-10-23T00:00:03+08:00", "3", "music.163.com", "203.0.113.6"),
                  log("2026-10-23T00:00:02+08:00", "2", "www.bilibili.com", "203.0.113.5")]},
    ]}))
    md.poll()
    md.poll()
    assert md.answers == 2  # 第二次只处理新的一条
    with e.lock:
        r = e.add_flow(dict(src="192.168.8.30", dst="203.0.113.6", sport=1, dport=443, proto=6, bytes=10), time.time())
    assert r[1] == "netease_music" and e.stats["dns_mosdns"] == 2


def test_asn_identifies_domainless_traffic(tmp_path):
    p = tmp_path / "ip2asn.tsv.gz"
    with gzip.open(p, "wt") as f:
        f.write("45.57.0.0\t45.57.127.255\t2906\tUS\tAS-SSI\n")
        f.write("142.250.0.0\t142.251.255.255\t15169\tUS\tGOOGLE\n")
        f.write("2a00:1450::\t2a00:1450:ffff:ffff:ffff:ffff:ffff:ffff\t15169\tUS\tGOOGLE\n")
    saved = (asndb._v4, asndb._v6, asndb.names, asndb.rows)
    try:
        assert asndb.load(str(p)) and asndb.rows == 3
        assert asndb.lookup("45.57.10.1") == (2906, "US", "AS-SSI")
        c = Classifier()
        assert c.classify("45.57.10.1", 6, 443, None, None) == "netflix"
        assert c.classify("142.250.1.1", 17, 443, None, None) == "google"      # ASN 比通用的 QUIC 端口优先
        assert c.classify("2a00:1450::1", 6, 443, None, None) == "google"
        assert c.classify("142.250.1.1", 17, 53, None, None) == "dns"          # 专用端口仍优先
        assert c.classify("9.9.9.9", 6, 443, None, None) == "https"
    finally:
        asndb._v4, asndb._v6, asndb.names, asndb.rows = saved
        asndb._cache = {}


def test_settings_api_configures_integrations():
    with TestClient(app) as c:
        if not c.get("/api/auth/status").json()["initialized"]:
            c.post("/api/auth/setup", json={"username": "admin", "password": "secret1"})
        h = {"Authorization": "Bearer " + c.post("/api/auth/login", json={"username": "admin", "password": "secret1"}).json()["token"]}
        assert c.put("/api/settings", json={"singbox_url": "192.168.8.249:9090"}, headers=h).status_code == 400
        s = c.put("/api/settings", json={"singbox_url": "http://192.168.8.249:9090", "singbox_secret": "x",
                                         "mosdns_url": "http://192.168.8.248:9099"}, headers=h).json()
        assert s["integrations"]["has_secret"] and s["integrations"]["proxy_auto"] == "192.168.8.249"
        assert integrations.singbox.enabled and integrations.mosdns.enabled
        sysinfo = c.get("/api/system", headers=h).json()
        assert sysinfo["singbox"]["url"] == "http://192.168.8.249:9090" and "secret" not in str(sysinfo["singbox"]).lower().replace("has_secret", "")
        # 清空后停用
        c.put("/api/settings", json={"singbox_url": "", "singbox_secret": "", "mosdns_url": ""}, headers=h)
        assert not integrations.singbox.enabled and not integrations.mosdns.enabled
