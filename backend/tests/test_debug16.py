"""debug16：社区共享库——本地库导出/上报过滤、中转聚合（≥2 实例才发布）、部署心跳、总开关。"""
import time

from app import share
from app.classify.local import local
from app.engine import Engine
from app.models import HostDomainDay, ShareDeployment, ShareEntry

DAY = 1792900000
HOST = "IP:192.168.8.40"
HUB = "11111111-1111-1111-1111-111111111111"
CLIENT_A = "22222222-2222-2222-2222-222222222222"
CLIENT_B = "33333333-3333-3333-3333-333333333333"


def _engine():
    e = Engine()
    e.set_lan("192.168.8.0/24")
    return e


def test_export_filters_private_and_custom():
    import app.database as database
    database.connect_from_saved(force=True)
    s = database.SessionLocal()
    try:
        s.query(HostDomainDay).filter(HostDomainDay.host == HOST).delete(synchronize_session=False)
        s.commit()
        s.add(HostDomainDay(ts=DAY, host=HOST, domain="93.184.216.34", app="douyin", base=None, bytes=800))
        s.add(HostDomainDay(ts=DAY, host=HOST, domain="192.168.8.5", app="douyin", base=None, bytes=999))     # 私网：不共享
        s.add(HostDomainDay(ts=DAY, host=HOST, domain="239.255.255.250", app="douyin", base=None, bytes=999))  # 组播：不共享
        s.add(HostDomainDay(ts=DAY, host=HOST, domain="45.57.10.1", app="my_custom_app", base=None, bytes=999))  # 自定义应用：不共享
        s.commit()
        entries = share.export_entries(_engine(), s)
        mine = {e["ip"]: e["app"] for e in entries if e["ip"] == "93.184.216.34"}
        assert mine == {"93.184.216.34": "douyin"}
        assert "192.168.8.5" not in {e["ip"] for e in entries}            # 私网
        assert "239.255.255.250" not in {e["ip"] for e in entries}        # 组播
        assert "45.57.10.1" not in {e["ip"] for e in entries}             # 自定义应用（45.57.10.1 那行是自定义应用）
        assert all(not e["ip"].endswith("/64") or ":" in e["ip"] for e in entries)  # IPv4 永远精确
    finally:
        s.query(HostDomainDay).filter(HostDomainDay.host == HOST).delete(synchronize_session=False)
        s.commit()
        s.close()


def test_hub_collect_publishes_only_two_reporters():
    import app.database as database
    database.connect_from_saved(force=True)
    s = database.SessionLocal()
    try:
        s.query(HostDomainDay).filter(HostDomainDay.host == HOST).delete(synchronize_session=False)
        s.commit()
        s.query(ShareEntry).filter(ShareEntry.ip.in_(["45.57.10.1", "8.8.8.8"])).delete(synchronize_session=False)
        s.commit()
        # 单个实例上报：不发布
        share.collect(s, CLIENT_A, [{"ip": "45.57.10.1", "app": "douyin", "bytes": 500},
                                    {"ip": "8.8.8.8", "app": "bilibili", "bytes": 300}])
        s.commit()
        lib = share.published_library(s)
        assert lib["entries"] == []
        # 第二个实例也见过 198.51.100.1 → 发布；198.51.100.2 仍只有一个实例 → 不发布
        share.collect(s, CLIENT_B, [{"ip": "45.57.10.1", "app": "douyin", "bytes": 700}])
        s.commit()
        lib = share.published_library(s)
        assert {"ip": "45.57.10.1", "app": "douyin"} in lib["entries"]
        assert all(e["ip"] != "8.8.8.8" for e in lib["entries"])
    finally:
        s.query(ShareEntry).filter(ShareEntry.ip.in_(["45.57.10.1", "8.8.8.8"])).delete(synchronize_session=False)
        s.commit()
        s.close()


def test_heartbeat_and_deployments():
    import app.database as database
    database.connect_from_saved(force=True)
    s = database.SessionLocal()
    try:
        s.query(ShareDeployment).filter(ShareDeployment.instance.in_([HUB, CLIENT_A])).delete(synchronize_session=False)
        s.commit()
        share.heartbeat(s, HUB, "0.6.10")
        share.heartbeat(s, CLIENT_A, "0.6.10")
        s.commit()
        d = share.deployments(s)
        assert d["total"] >= 2 and d["online"] >= 2
    finally:
        s.query(ShareDeployment).filter(ShareDeployment.instance.in_([HUB, CLIENT_A])).delete(synchronize_session=False)
        s.commit()
        s.close()


def test_client_merges_community_only_into_gaps():
    import app.database as database
    database.connect_from_saved(force=True)
    s = database.SessionLocal()
    try:
        local.reset()
        # 其它测试可能留过同域名的行：先清掉（8.8.4.4 在共享测试里是社区条目）
        s.query(HostDomainDay).filter(HostDomainDay.domain.in_(["45.57.10.1", "8.8.4.4"])).delete(synchronize_session=False)
        s.commit()
        # 本地实测：45.57.10.1 → bilibili；社区对同一 IP 说什么都不覆盖
        local.load_community({"45.57.10.1": "bilibili", "8.8.4.4": "douyin"})
        s.add(HostDomainDay(ts=DAY, host=HOST, domain="45.57.10.1", app="bilibili", base=None, bytes=100))
        s.commit()
        local.load(s)
        s.commit()
        assert local.ip_app("45.57.10.1") == "bilibili"   # 本地实测优先
        assert local.ip_app("8.8.4.4") == "douyin"     # 本地没有的用社区
    finally:
        s.query(HostDomainDay).filter(HostDomainDay.host == HOST).delete(synchronize_session=False)
        s.query(HostDomainDay).filter(HostDomainDay.domain.in_(["45.57.10.1", "8.8.4.4"])).delete(synchronize_session=False)
        s.commit()
        s.close()
        local.reset()


def test_ipv6_prefix_shared_and_matched():
    """中国环境以 IPv6 公网为主：精确地址在不同实例间几乎不重复，共享与匹配都按 /64 前缀"""
    import app.database as database
    database.connect_from_saved(force=True)
    s = database.SessionLocal()
    try:
        s.query(HostDomainDay).filter(HostDomainDay.host == HOST).delete(synchronize_session=False)
        s.query(ShareEntry).filter(ShareEntry.ip.like("%/64")).delete(synchronize_session=False)
        s.commit()
        # 两个不同实例、同一 /64 里的不同精确地址：聚合后应发布为同一条 /64 记忆
        s.add(HostDomainDay(ts=DAY, host=HOST, domain="2408:8556:1234:5678::1", app="douyin", base=None, bytes=600))
        s.add(HostDomainDay(ts=DAY, host=HOST, domain="fd00::5", app="douyin", base=None, bytes=999))   # ULA：不共享
        s.commit()
        entries = share.export_entries(_engine(), s)
        v6 = {e["ip"]: e["app"] for e in entries if e["ip"].endswith("/64")}
        assert v6 == {"2408:8556:1234:5678::/64": "douyin"}
        assert "fd00::/64" not in v6
        share.collect(s, CLIENT_A, [{"ip": "2408:8556:1234:5678::5", "app": "douyin", "bytes": 100}])   # 别的实例、同一 /64
        share.collect(s, CLIENT_B, [{"ip": "2408:8556:1234:5678::9", "app": "douyin", "bytes": 100}])
        s.commit()
        lib = share.published_library(s)
        assert {"ip": "2408:8556:1234:5678::/64", "app": "douyin"} in lib["entries"]
        # 本地匹配：同一 /64 里的另一个精确地址也能命中
        local.reset()
        local.load_community({"2408:8556:1234:5678::/64": "douyin"})
        assert local.ip_app("2408:8556:1234:5678::abc") == "douyin"
        assert local.ip_app("2408:8556:9999::abc") is None
    finally:
        s.query(HostDomainDay).filter(HostDomainDay.host == HOST).delete(synchronize_session=False)
        s.query(ShareEntry).filter(ShareEntry.ip.like("%/64")).delete(synchronize_session=False)
        s.commit()
        s.close()
        local.reset()
