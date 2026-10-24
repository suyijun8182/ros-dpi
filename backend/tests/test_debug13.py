"""debug13：自有 DNS 服务器（AdGuard Home）接入、中国自营内容商 ASN、历史重算。"""
import gzip

import pytest

from app import integrations
from app.asn import asndb
from app.classify import Classifier
from app.engine import Engine
from app.reclass import reclassify

DAY = 1792900000  # 2026-10-25 附近
HOST = "IP:192.168.8.20"


def _engine():
    e = Engine()
    e.set_lan("192.168.8.0/24")
    return e


# ---------- A2：中国自营内容商的 ASN 识别（无域名流量） ----------

def test_asn_chinese_providers(tmp_path):
    p = tmp_path / "ip2asn.tsv.gz"
    with gzip.open(p, "wt") as f:
        # 注意：asndb.load 不排序（真实 iptoasn 文件本身有序），测试数据也要按起始 IP 排好
        f.write("10.11.0.0\t10.11.255.255\t140633\tHK\tBILIBILI HK LIMITED\n")
        f.write("10.12.0.0\t10.12.255.255\t215543\tSG\tHOYOVERSE\n")
        f.write("10.13.0.0\t10.13.255.255\t133478\tCN\tTENCENT-AS-AP Tencent Cloud Computing Beijing\n")
        f.write("10.14.0.0\t10.14.255.255\t137753\tCN\tJD Beijing Jingdong Shangke\n")
        f.write("10.15.0.0\t10.15.255.255\t24429\tCN\tTAOBAO Zhejiang Taobao Network\n")
        f.write("42.186.0.0\t42.186.186.255\t45062\tCN\tNETEASE-NETWORK NetEase Building No.16\n")
        f.write("71.18.1.0\t71.18.5.255\t396986\tUS\tBYTEDANCE\n")
    saved = (asndb._v4, asndb._v6, asndb.names, asndb.rows)
    try:
        assert asndb.load(str(p)) and asndb.rows == 7
        c = Classifier()
        assert c.classify("71.18.2.1", 6, 443, None, None) == "douyin"          # 字节跳动 → 抖音
        assert c.classify("10.11.1.1", 6, 443, None, None) == "bilibili"
        assert c.classify("10.12.1.1", 17, 443, None, None) == "mihoyo"
        assert c.classify("10.13.1.1", 6, 443, None, None) == "tencent_cloud"
        assert c.classify("10.14.1.1", 6, 443, None, None) == "jd"
        assert c.classify("10.15.1.1", 6, 443, None, None) == "taobao"
        assert c.classify("42.186.1.1", 6, 443, None, None) == "netease"
        assert c.classify("9.9.9.9", 6, 443, None, None) == "https"             # 没命中的仍是通用
    finally:
        asndb._v4, asndb._v6, asndb.names, asndb.rows = saved
        asndb._cache = {}


# ---------- A1：AdGuard Home 查询日志 ----------

def test_adguard_parse_entry():
    p = integrations.AdguardPoller(_engine())
    row = {"time": "2026-10-25T10:00:00.123+08:00", "domain": "www.iqiyi.com.", "client": "192.168.9.6",
           "answer": "www.iqiyi.com. 180 IN CNAME iqiyi.com.\niqiyi.com. 180 IN A 133.86.5.1", "status": "NOERROR"}
    assert p._parse_entry(row) == ("www.iqiyi.com", [("133.86.5.1", 180)], ["iqiyi.com"], "192.168.9.6")
    # 列表格式的 answer（部分版本）
    row2 = {"domain": "a.bilibili.com", "client": "192.168.9.7",
            "answer": [{"type": "A", "value": "10.11.0.9", "ttl": 120}]}
    assert p._parse_entry(row2) == ("a.bilibili.com", [("10.11.0.9", 120)], [], "192.168.9.7")
    # 被拦截 / NXDOMAIN：没有 A/AAAA 应答
    assert p._parse_entry({"domain": "ads.example.com", "client": "192.168.9.6", "answer": ""}) is None
    assert p._parse_entry({"domain": "nx.example.com", "client": "192.168.9.6"}) is None


def test_adguard_entries_shapes():
    """新版 AdGuard 返回 {"data": [...]}（线上实测），旧版 {"entries": [...]}，更老的直接数组"""
    p = integrations.AdguardPoller(_engine())
    assert p._entries({"data": [1, 2], "oldest": "x"}) == [1, 2]
    assert p._entries({"entries": [3]}) == [3]
    assert p._entries([4]) == [4]
    assert p._entries({}) == []
    assert p._entries({"data": None}) == []


class _FakeEngine:
    def __init__(self):
        self.calls = []

    def add_dns_answer(self, client, qname, ips, cnames, source="sniff"):
        self.calls.append((client, qname, [ip for ip, _ in ips], list(cnames), source))


def test_adguard_poll_delta(monkeypatch):
    e = _FakeEngine()
    p = integrations.AdguardPoller(e)
    p.configure("http://192.168.9.2:3000", "admin", "pw")
    assert p.enabled
    pages = [
        # 第一页：最新的在前
        [{"time": "T2", "domain": "b.example.com", "client": "192.168.9.6",
          "answer": "b.example.com. 60 IN A 10.0.0.2"},
         {"time": "T1", "domain": "a.example.com", "client": "192.168.9.6",
          "answer": "a.example.com. 60 IN A 10.0.0.1"}],
        # 第二页：一条新的（T3）+ 两条旧的（应被 mark 挡住）
        [{"time": "T3", "domain": "c.example.com", "client": "192.168.9.6",
          "answer": "c.example.com. 60 IN A 10.0.0.3"},
         {"time": "T2", "domain": "b.example.com", "client": "192.168.9.6",
          "answer": "b.example.com. 60 IN A 10.0.0.2"}],
    ]
    monkeypatch.setattr(p, "_fetch", lambda: pages.pop(0))
    p.poll()
    assert [(c, n) for c, n, *_ in e.calls] == [("192.168.9.6", "a.example.com"), ("192.168.9.6", "b.example.com")]
    assert e.calls[0][4] == "adguard"
    p.poll()
    assert [(c, n) for c, n, *_ in e.calls] == [("192.168.9.6", "a.example.com"), ("192.168.9.6", "b.example.com"),
                                                ("192.168.9.6", "c.example.com")]
    assert p.ok and p.answers == 3 and not p.error


def test_adguard_configure_reset_and_off():
    e = _FakeEngine()
    p = integrations.AdguardPoller(e)
    p.poll()  # 未配置：直接返回
    assert not p.enabled and not p.ok
    p.configure("http://192.168.9.2:3000", "", "")
    p._mark = ("T1", "d", "c")
    p.configure("http://192.168.9.2:3000", "", "")  # 相同配置：不重置
    assert p._mark == ("T1", "d", "c")
    p.configure("http://192.168.9.3:3000", "", "")  # 换地址：重置断点和会话
    assert p._mark is None and p._client is None


# ---------- A4：历史重算 ----------

def test_reclass_moves_history():
    from app.database import SessionLocal
    from app.models import HostDomainDay, TrafficDay
    s = SessionLocal()
    try:
        s.add(TrafficDay(ts=DAY, host=HOST, app="cn_net", up=100, down=900, flows=10))
        s.add(HostDomainDay(ts=DAY, host=HOST, domain="v.douyin.com", app="cn_net", base=None, bytes=300))
        s.add(HostDomainDay(ts=DAY, host=HOST, domain="portal.example.cn", app="cn_net", base=None, bytes=100))
        s.commit()

        class _C:
            @staticmethod
            def classify(ip, proto, port, qname, cname):
                if qname == "v.douyin.com":
                    return "douyin"
                return "cn_net"

        eng = _engine()
        eng.classifier = _C()
        res = reclassify(eng, s)
        s.commit()
        assert res["bytes_moved"] >= 300  # 全套件里还有其它测试遗留的行也会被重算，这里只下限
        rows = {(r.app): r for r in s.query(TrafficDay).filter(TrafficDay.ts == DAY, TrafficDay.host == HOST).all()}
        assert set(rows) == {"cn_net", "douyin"}
        assert (rows["cn_net"].up, rows["cn_net"].down, rows["cn_net"].flows) == (70, 630, 7)
        assert (rows["douyin"].up, rows["douyin"].down, rows["douyin"].flows) == (30, 270, 3)
        marks = {d.domain: d.app for d in s.query(HostDomainDay).filter(HostDomainDay.host == HOST).all()}
        assert marks["v.douyin.com"] == "douyin" and marks["portal.example.cn"] == "cn_net"
        # 幂等：再跑一次没有变化
        res2 = reclassify(eng, s)
        s.commit()
        assert res2["bytes_moved"] == 0
    finally:
        s.query(TrafficDay).filter(TrafficDay.host == HOST).delete()
        s.query(HostDomainDay).filter(HostDomainDay.host == HOST).delete()
        s.commit()
        s.close()


# ---------- 设置 API ----------

def test_settings_api_adguard_fields():
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as c:
        if not c.get("/api/auth/status").json()["initialized"]:
            c.post("/api/auth/setup", json={"username": "admin", "password": "secret1"})
        h = {"Authorization": "Bearer " + c.post("/api/auth/login", json={"username": "admin", "password": "secret1"}).json()["token"]}
        try:
            s = c.put("/api/settings", json={"adguard_url": "http://192.168.9.2:3000",
                                             "adguard_username": "admin", "adguard_password": "pw1"}, headers=h).json()
            assert s["integrations"]["adguard_url"] == "http://192.168.9.2:3000"
            assert s["integrations"]["adguard_username"] == "admin"
            assert s["integrations"]["has_adguard_password"] is True
            assert "pw1" not in str(s)
            assert integrations.adguard.enabled
            sysinfo = c.get("/api/system", headers=h).json()
            assert sysinfo["adguard"]["enabled"] is True
        finally:
            c.put("/api/settings", json={"adguard_url": "", "adguard_username": "", "adguard_password": ""}, headers=h)
