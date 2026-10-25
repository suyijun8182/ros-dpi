"""debug15：本地自学习库（IP→应用 长期记忆）、组播噪音过滤、代理连接 remote 只存 IP。"""
import time

from app.classify import Classifier
from app.classify.local import local
from app.engine import Engine
from app.models import HostDomainDay

DAY = 1792900000
HOST = "IP:192.168.8.40"


def _engine():
    e = Engine()
    e.set_lan("192.168.8.0/24")
    return e


def test_local_library_feeds_classifier():
    import app.database as database
    database.connect_from_saved(force=True)
    s = database.SessionLocal()
    try:
        # 其它测试可能在共享库里留过同域名的行：先清掉，保证聚合结果确定
        s.query(HostDomainDay).filter(HostDomainDay.domain.in_(["203.0.113.9", "www.example.com"])).delete(synchronize_session=False)
        s.query(HostDomainDay).filter(HostDomainDay.host == HOST).delete(synchronize_session=False)
        s.add(HostDomainDay(ts=DAY, host=HOST, domain="203.0.113.9", app="douyin", base=None, bytes=500))
        s.add(HostDomainDay(ts=DAY, host=HOST, domain="www.example.com", app="web", base=None, bytes=900))
        s.commit()
        local.load(s)
        s.commit()
        assert local.ip_app("203.0.113.9") == "douyin"     # IP 行进记忆
        assert local.ip_app("198.51.100.7") is None
        c = Classifier()
        assert c.classify("203.0.113.9", 6, 443, None, None) == "douyin"   # 分类管线用上记忆（无域名 / DoH 场景）
        assert c.classify("198.51.100.7", 6, 443, None, None) == "https"   # 没记忆的照旧走通用
    finally:
        s.query(HostDomainDay).filter(HostDomainDay.host == HOST).delete(synchronize_session=False)
        s.query(HostDomainDay).filter(HostDomainDay.domain.in_(["203.0.113.9", "www.example.com"])).delete(synchronize_session=False)
        s.commit()
        s.close()
        local.reset()   # 单例记忆会污染同进程的其它用例（203.0.113.9 是测试标准地址）


def test_multicast_and_broadcast_dropped():
    e = _engine()
    now = time.time()
    for dst in ("239.255.255.250", "255.255.255.255", "224.0.0.251", "ff02::fb"):
        r = e.add_flow(dict(src="192.168.8.20", dst=dst, sport=5000, dport=1900, proto=17, bytes=1000), now)
        assert r is None, dst
    r = e.add_flow(dict(src="192.168.8.20", dst="93.184.216.34", sport=5000, dport=443, proto=6, bytes=1000), now)
    assert r is not None


def test_proxy_remote_stores_ip_only():
    e = _engine()
    e.set_proxy({"192.168.8.249"}, True)
    now = time.time()
    # 目标是域名（无 IP）：remote 留空，不把长域名写进 access_log.remote
    e.add_proxy_conn("192.168.8.20", 50000, "very-long-domain-name.example-cdn-cluster.some-provider.net",
                     "", 443, "tcp", 100, 1000, now)
    # 目标是 IP：remote 存 IP
    e.add_proxy_conn("192.168.8.20", 50001, "api.example.com", "93.184.216.34", 443, "tcp", 100, 1000, now + 1)
    remotes = {k[1] for k in e.sessions}
    assert "" in remotes and "93.184.216.34" in remotes
    assert not any(r and "example-cdn-cluster" in r for r in remotes)
