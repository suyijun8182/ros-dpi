"""0.7.0 多站点：按 UDP 源 IP 分到各站点的 Engine，同一个内网 IP 在两个站点各记各的；未登记来源丢弃并计数"""
import time

from packets import ipfix, tzsp_dns
from sqlalchemy import select

from app import database
from app.models import DEFAULT_SITE, Host, TrafficDay, UnknownSource
from app.sites import SiteRegistry, split_sources

HOME, OFFICE = "192.168.88.1", "10.8.0.2"


def _flow(nbytes, sport=50000):
    return ipfix([dict(src="192.168.88.10", dst="6.6.6.6", sport=sport, dport=443, proto=6, nbytes=nbytes,
                       mac="AA:00:00:00:07:01")])


def _two_sites():
    reg = SiteRegistry()
    reg.apply([{"slug": DEFAULT_SITE, "name": "家里", "enabled": True, "sources": [HOME]},
               {"slug": "office", "name": "公司", "enabled": True, "sources": [OFFICE]}])
    return reg


def test_split_sources():
    assert split_sources(" 10.8.0.2,\n10.8.0.2, bad, fd00::0001 ") == ["10.8.0.2", "fd00::1"]


def test_single_site_accepts_everything():
    reg = SiteRegistry()
    reg.apply([{"slug": DEFAULT_SITE, "name": "家里", "enabled": True, "sources": []}])
    assert reg.accept_all == DEFAULT_SITE and not reg.multi()
    assert reg.resolve("203.0.113.77") is reg.engines[DEFAULT_SITE]
    # 单站点但登记了源 IP：只收登记的
    reg.apply([{"slug": DEFAULT_SITE, "name": "家里", "enabled": True, "sources": [HOME]}])
    assert reg.resolve("203.0.113.77") is None and reg.resolve(HOME) is reg.engines[DEFAULT_SITE]


def test_two_sites_same_lan_ip_kept_apart():
    reg = _two_sites()
    assert reg.multi() and reg.accept_all is None
    home, office = reg.engines[DEFAULT_SITE], reg.engines["office"]
    assert home is not office and home.classifier is office.classifier   # 识别器共用
    b0, o0 = home.stats["bytes_seen"], office.stats["bytes_seen"]
    with database.session() as db:     # 默认站点的 Engine 是全局的，前面的测试可能留下同一终端的数据
        before = {r.site: r.up for r in db.scalars(select(TrafficDay).where(TrafficDay.host == "AA:00:00:00:07:01"))}
    reg.on_ipfix(_flow(1000), HOME)
    reg.on_ipfix(_flow(5000, sport=50001), OFFICE)
    reg.on_ipfix(_flow(9999, sport=50002), "198.51.100.9")          # 未登记
    reg.on_tzsp(tzsp_dns("192.168.88.10", "x.example", ["6.6.6.6"]), "198.51.100.9")
    assert home.stats["bytes_seen"] - b0 == 1000 and office.stats["bytes_seen"] - o0 == 5000
    unknown = {(u["ip"], u["kind"]): u["packets"] for u in reg.unknown_snapshot()}
    assert unknown == {("198.51.100.9", "ipfix"): 1, ("198.51.100.9", "tzsp"): 1}

    reg.flush()
    with database.session() as db:
        day = {r.site: r.up for r in db.scalars(select(TrafficDay).where(TrafficDay.host == "AA:00:00:00:07:01"))}
        assert {k: v - before.get(k, 0) for k, v in day.items()} == {DEFAULT_SITE: 1000, "office": 5000}
        hosts = {h.site for h in db.scalars(select(Host).where(Host.key == "AA:00:00:00:07:01"))}
        assert hosts == {DEFAULT_SITE, "office"}
        u = db.scalars(select(UnknownSource).where(UnknownSource.ip == "198.51.100.9")).all()
        assert {(r.kind, r.packets) for r in u} == {("ipfix", 1), ("tzsp", 1)}
        assert all(r.last_seen >= time.time() - 60 for r in u)


def test_disabled_site_gets_nothing_and_ids_do_not_collide():
    reg = _two_sites()
    reg.apply([{"slug": DEFAULT_SITE, "name": "家里", "enabled": True, "sources": [HOME]},
               {"slug": "office", "name": "公司", "enabled": False, "sources": [OFFICE]}])
    # 只剩一个启用站点，但它登记了源 IP：仍然按源 IP 收，公司的包不会落进家里
    assert reg.resolve(OFFICE) is None and not reg.multi()
    a, b = reg.engines[DEFAULT_SITE]._next_vid(), reg.engines["office"]._next_vid()
    assert a != b
