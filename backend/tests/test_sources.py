"""debug12：补充识别库（国内域名列表 + 官方 IP 段）——只做兜底，不让任何已有识别变差。"""
import json

import pytest

from app.classify import Classifier
from app.classify.sources import sources as src


@pytest.fixture
def loaded_sources(tmp_path, monkeypatch):
    """用小份样本数据驱动 sources（不访问网络）：国内域名 + Google/GitHub/国内 IP 段。"""
    (tmp_path / "china-domains.conf").write_text(
        "# 样本\nserver=/example-test.cn/114.114.114.114\nserver=/gov-example.gov.cn/114\nbad line\n", encoding="utf-8")
    (tmp_path / "ip-google.json").write_text(json.dumps(
        {"prefixes": [{"ipv4Prefix": "192.0.2.0/24"}, {"ipv6Prefix": "2001:db8::/32"}]}), encoding="utf-8")
    (tmp_path / "ip-github.json").write_text(json.dumps(
        {"git": ["203.0.113.0/25"], "web": ["203.0.113.128/25"]}), encoding="utf-8")
    (tmp_path / "ip-cn.txt").write_text("198.51.100.0/24\n# comment\n", encoding="utf-8")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setattr("app.classify.sources._enabled", lambda sid: True)
    src.reset()
    src.load()
    yield src
    src.reset()


def test_china_list_fallback(loaded_sources):
    """域名规则没认出、但在国内域名列表里 → 国内网站；子域名同样命中；列表外仍是通用 HTTPS。"""
    c = Classifier()
    assert c.classify("93.184.216.34", 6, 443, "www.example-test.cn", None) == "cn_web"
    assert c.classify("93.184.216.34", 6, 443, "deep.sub.example-test.cn", None) == "cn_web"
    assert c.classify("93.184.216.34", 6, 443, "not-in-list.example.org", None) == "https"
    # 已有规则的应用不被兜底覆盖
    assert c.classify("93.184.216.34", 6, 443, "www.bilibili.com", None) == "bilibili"


def test_official_ip_fallback(loaded_sources):
    """没有域名的流量按官方 IP 段认出归属（测试里 ASN 库是关的，正好只验证这一层）。"""
    c = Classifier()
    assert c.classify("192.0.2.1", 6, 443, None, None) == "google"
    assert c.classify("203.0.113.10", 6, 443, None, None) == "github"
    assert c.classify("198.51.100.7", 6, 443, None, None) == "cn_net"
    assert c.classify("198.51.100.7", 17, 443, None, None) == "cn_net"
    # 官方 IP 段认出的也在库外：测试段外的 IP 仍走通用端口
    assert c.classify("45.155.99.10", 6, 443, None, None) == "https"
    # 域名优先于 IP：IP 在 Google 段里但域名是别的应用
    assert c.classify("192.0.2.1", 6, 443, "store.steampowered.com", None) == "steam"
    # Apple 静态段（IANA 注册）
    assert c.classify("17.0.0.1", 6, 443, None, None) == "apple"


def test_sources_counted_as_identified(loaded_sources):
    """国内网站 / 国内网络不计入「未识别」，识别率计算把它们算已识别。"""
    from app.classify import UNIDENTIFIED_CATEGORIES
    from app import stats
    c = Classifier()
    for app_id, ip, qname in (("cn_web", "93.184.216.34", "www.example-test.cn"), ("cn_net", "198.51.100.7", None)):
        hit = c.classify(ip, 6, 443, qname, None)
        assert c.app_info(hit).category not in UNIDENTIFIED_CATEGORIES
        assert c.app_info(hit).name_en
    apps = [{**stats.app_meta(a), "total": 1} for a in ("cn_web", "cn_net")]
    assert stats.identified_ratio(apps) == 1.0


def test_sources_rows_for_library_panel(loaded_sources):
    rows = {r["id"]: r for r in src.rows()}
    assert rows["cnlist"]["domains"] == 2
    assert rows["google"]["ranges"] == 2
    assert rows["github"]["ranges"] == 2
    assert rows["cn"]["ranges"] == 1
    assert all(r["license"] and r["url"] for r in rows.values())


def test_domain_fallback_before_ip_fallback(loaded_sources):
    """有域名时先按域名兜底：国内网站托管在 Google/国内段的 IP 上，仍归「国内网站」而不是 IP 所属的 CDN。"""
    c = Classifier()
    assert c.classify("192.0.2.1", 6, 443, "www.example-test.cn", None) == "cn_web"
    assert c.classify("198.51.100.7", 6, 443, "www.example-test.cn", None) == "cn_web"
    # 域名不在任何库里时才按 IP
    assert c.classify("192.0.2.1", 6, 443, "not-in-list.example.org", None) == "google"


def test_overlapping_ranges_longest_prefix():
    """IP 段重叠时按最长前缀：小段赢；小段之外仍落在大段里（旧实现在这里会漏查返回 None）。"""
    from app.classify.sources import _Ranges
    r = _Ranges()
    r.add("10.0.0.0/8", "cn_net")       # 先加入的大段
    r.add("10.1.0.0/16", "aws")         # 后加入、更具体
    r.add("10.1.2.0/24", "github")      # 再嵌套一层
    r.add("10.200.0.0/16", "cn_net")    # 同归属的嵌套，合并后不影响
    r.add("2001:db8::/32", "google")
    r.add("2001:db8:1::/48", "cloudflare")
    r.build()
    assert r.lookup("10.1.2.3") == "github"
    assert r.lookup("10.1.3.1") == "aws"
    assert r.lookup("10.2.0.1") == "cn_net"      # 在小段后面、仍属于大段
    assert r.lookup("10.255.255.255") == "cn_net"
    assert r.lookup("10.0.0.0") == "cn_net"
    assert r.lookup("11.0.0.1") is None
    assert r.lookup("2001:db8:1::5") == "cloudflare"
    assert r.lookup("2001:db8:2::5") == "google"
    # 一样大时先加入的赢
    r2 = _Ranges()
    r2.add("192.0.2.0/24", "google")
    r2.add("192.0.2.0/24", "aws")
    r2.build()
    assert r2.lookup("192.0.2.9") == "google"
