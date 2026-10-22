import time
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from packets import ipfix, tzsp_dns

from app import stats, timeutil
from app.classify import Classifier
from app import database
from app.engine import Engine

Z = ZoneInfo("Asia/Shanghai")


def test_classifier_longest_suffix_and_cname():
    c = Classifier()
    assert c.classify("1.1.1.1", 6, 443, "v26-web.douyinvod.com", None) == "douyin"
    assert c.classify("1.1.1.1", 6, 443, "y.qq.com", None) == "qq_music"   # 比 qq.com 更具体
    assert c.classify("1.1.1.1", 6, 443, "www.qq.com", None) == "qq"
    assert c.classify("1.1.1.1", 6, 443, "unknown.example", "x.bilivideo.com") == "bilibili"
    assert c.classify("91.108.4.5", 6, 443, None, None) == "telegram"
    assert c.classify("9.9.9.9", 17, 443, None, None) == "quic"
    assert c.classify("9.9.9.9", 6, 12345, None, None) == "other"
    assert c.classify("9.9.9.9", 1, 0, None, None) == "icmp"
    assert c.classify("9.9.9.9", 50, 0, None, None) == "vpn"
    # 未识别的站点经 CDN 的 CNAME 至少能归到 CDN 厂商
    assert c.classify("1.1.1.1", 6, 443, "img.some-site.cn", "x.kunlunsl.com") == "aliyun"
    assert c.classify("1.1.1.1", 6, 443, "finder.video.qq.com", None) == "wechat_channels"


def test_rules_library_consistent():
    """规则库自洽：分类都有大类、应用都有分类，已发布的应用/分类 ID 没被删掉。"""
    c = Classifier()
    assert all(v["group"] in c.groups for v in c.categories.values())
    assert all(a.category in c.categories for a in c.apps.values())
    released = {"douyin", "bilibili", "wechat", "qq", "steam", "apple_update", "apple", "microsoft", "cn_ai",
                "android_update", "app_market", "cloudflare", "ads", "ezviz", "dns", "vpn", "ssh", "mail", "stun",
                "https", "quic", "http"}
    assert released <= set(c.apps)
    assert {"video", "short_video", "live", "music", "social", "im", "game", "shopping", "news", "search",
            "cloud", "download", "update", "ai", "work", "finance", "life", "ads", "iot", "network", "web",
            "unknown"} <= set(c.categories)


def test_frontend_colors_cover_categories():
    """前端按大类配色（format.js 的 CAT_GROUP），新增分类时要同步。"""
    import os
    import re
    js = open(os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "src", "format.js"), encoding="utf-8").read()
    block = js[js.index("CAT_GROUP"):]
    block = block[:block.index("}")]
    mapping = dict(re.findall(r"(\w+):\s*'(\w+)'", block))
    c = Classifier()
    assert mapping == {k: v["group"] for k, v in c.categories.items()}


def test_custom_rule_overrides():
    c = Classifier()
    c.load_custom([SimpleNamespace(kind="domain", pattern="douyin.com", app_id="myapp", app_name="我的",
                                   category="video")])
    assert c.classify("1.1.1.1", 6, 443, "www.douyin.com", None) == "myapp"
    assert c.apps["myapp"].name == "我的"


def _engine():
    e = Engine()
    e.set_lan("192.168.88.0/24,2408:8000:1:2::/64")
    return e


def test_direction_dns_and_mac_learning():
    e = _engine()
    e.on_tzsp(tzsp_dns("192.168.88.10", "www.bilibili.com", ["5.5.5.5"]))
    assert list(e.dns_servers) and e.dns_servers[next(iter(e.dns_servers))][0] == 1
    now = time.time()
    up = e.add_flow(dict(src="192.168.88.10", dst="5.5.5.5", sport=1, dport=443, proto=6, bytes=100,
                         src_mac="AA:00:00:00:00:01"), now)
    down = e.add_flow(dict(src="5.5.5.5", dst="192.168.88.10", sport=443, dport=1, proto=6, bytes=900), now)
    assert up == ("AA:00:00:00:00:01", "bilibili", "up")
    assert down == ("AA:00:00:00:00:01", "bilibili", "down")
    # 内网互访、路由器自身流量不计
    assert e.add_flow(dict(src="192.168.88.10", dst="192.168.88.20", proto=6, bytes=5), now) is None
    assert e.add_flow(dict(src="100.64.1.2", dst="8.8.8.8", proto=17, bytes=5), now) is None


def test_post_nat_download():
    e = _engine()
    r = e.add_flow(dict(src="5.5.5.5", dst="100.64.1.2", post_dst="192.168.88.30", sport=443, dport=1, proto=6,
                        bytes=10), time.time())
    assert r == ("IP:192.168.88.30", "https", "down")


def test_flush_and_ranges():
    e = _engine()
    e.on_tzsp(tzsp_dns("192.168.88.11", "store.steampowered.com", ["6.6.6.6"]))
    e.on_ipfix(ipfix([dict(src="192.168.88.11", dst="6.6.6.6", sport=1, dport=443, proto=6, nbytes=1000,
                           mac="AA:00:00:00:00:11"),
                      dict(src="192.168.88.11", dst="7.7.7.7", sport=1, dport=443, proto=6, nbytes=50,
                           mac="AA:00:00:00:00:11")]), "10.0.0.1")
    now = time.time()
    e.flush(now)
    e.add_flow(dict(src="6.6.6.6", dst="192.168.88.11", sport=443, dport=1, proto=6, bytes=4000), now)
    e.flush(now)  # 同一分钟再写一次，应累加
    with database.session() as db:
        t = stats.total(db, *timeutil.range_bounds("today"), host="AA:00:00:00:00:11")
        assert t == {"up": 1050, "down": 4000, "total": 5050, "flows": 3}
        apps = {a["id"]: a for a in stats.top_apps(db, *timeutil.range_bounds("month"), host="AA:00:00:00:00:11")}
        assert apps["steam"]["total"] == 5000 and apps["https"]["total"] == 50
        hosts = {h["key"]: h for h in stats.all_hosts(db)}
        assert hosts["AA:00:00:00:00:11"]["today"]["total"] == 5050
        assert hosts["AA:00:00:00:00:11"]["online"]
        doms = stats.host_domains(db, "AA:00:00:00:00:11", *timeutil.range_bounds("today"))
        assert doms[0]["domain"] == "store.steampowered.com" and doms[0]["bytes"] == 5000


def test_range_bounds_week_starts_monday():
    # 2026-10-21 是周三
    now = datetime(2026, 10, 21, 15, 0, tzinfo=Z).timestamp()
    start, _ = timeutil.range_bounds("week", now)
    assert datetime.fromtimestamp(start, Z) == datetime(2026, 10, 19, tzinfo=Z)
    start, _ = timeutil.range_bounds("month", now)
    assert datetime.fromtimestamp(start, Z) == datetime(2026, 10, 1, tzinfo=Z)
    assert timeutil.day_bucket(now) == datetime(2026, 10, 21, tzinfo=Z).timestamp()
