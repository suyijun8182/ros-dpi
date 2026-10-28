"""debug25：「其他 / 未识别」占比——无域名流量按 ASN 类型推断、视频站域名兜底、CDN/广告移出其他、未匹配诊断。"""
import gzip
import time

import pytest

from app import database, stats, timeutil
from app.asn import asndb
from app.classify import Classifier
from app.engine import Engine
from app.models import HostDomainDay, TrafficDay, UnmatchedDay
from app.reclass import reclassify

DAY = 1792900000 - 7 * 86400


@pytest.fixture
def asn(tmp_path):
    p = tmp_path / "ip2asn.tsv.gz"
    with gzip.open(p, "wt") as f:
        f.write("10.21.0.0\t10.21.255.255\t134419\tCN\tCHINATELECOM-GUANGXI-BEIHAI-MAN Beihai\n")
        f.write("10.22.0.0\t10.22.255.255\t4134\tCN\tCHINANET-BACKBONE No.31,Jin-rong Street\n")
        f.write("10.23.0.0\t10.23.255.255\t138169\tCN\tASEAN-INTERNATIONAL-INFORMATION-GARDEN-IDC China Telecom\n")
        f.write("10.24.0.0\t10.24.255.255\t131516\tCN\tJHWA Jinhua Weian InfoTech Co., Ltd\n")
        f.write("10.25.0.0\t10.25.255.255\t3320\tDE\tDTAG Deutsche Telekom AG\n")
    saved = (asndb._v4, asndb._v6, asndb.names, asndb.rows)
    assert asndb.load(str(p))
    yield
    asndb._v4, asndb._v6, asndb.names, asndb.rows = saved
    asndb._cache = {}


def test_asn_kind_guess(asn):
    c = Classifier()
    assert c.classify("10.21.1.1", 17, 31000, None, None) == "pcdn_p2p"     # 城域网（家宽）
    assert c.classify("10.22.1.1", 6, 8899, None, None) == "pcdn_p2p"       # 骨干网
    assert c.classify("10.23.1.1", 6, 443, None, None) == "idc_cloud"       # 名字带 IDC 优先于 TELECOM
    assert c.classify("10.24.1.1", 6, 443, None, None) == "https"           # 认不出类型：照旧
    assert c.classify("10.25.1.1", 17, 31000, None, None) != "pcdn_p2p"     # 不是国内
    # 有域名时不按 ASN 猜（域名没认出也一样）
    assert c.classify("10.21.1.1", 6, 443, "foo.example", None) != "pcdn_p2p"
    assert c.app_info("pcdn_p2p").category == "pcdn" and c.category_info("pcdn")["group"] == "pcdn"


def test_video_domain_guess():
    c = Classifier()
    for d in ("m3u8.44cdn.com", "cdn.yzzy31-play.com", "player.yzzyvip-35.com", "vodcnd02.ky32e.com",
              "s1.52videoplay.com", "voddadaizi2.com"):
        assert c.classify("0.0.0.0", 6, 443, d, None) == "gen_video", d
    for d in ("display.example.com", "foo.example.com"):
        assert c.classify("0.0.0.0", 6, 443, d, None) == "https", d


def test_cdn_ads_moved_to_common():
    c = Classifier()
    for cat in ("cdn", "ads", "selfhost"):
        assert c.category_info(cat)["group"] == "common"
    assert c.category_info("cn_net")["group"] == "other"


def test_reclass_upgrades_cn_net(asn):
    e = Engine()
    host = "IP:192.168.88.30"
    with database.session() as db:
        for ip, n in (("10.21.5.5", 7000), ("10.23.5.5", 3000)):
            db.add(HostDomainDay(ts=DAY, host=host, domain=ip, app="cn_net", base=ip, bytes=n))
        db.add(TrafficDay(ts=DAY, host=host, app="cn_net", up=1000, down=9000, flows=10))
        db.commit()
        res = reclassify(e, db, before=DAY + 86400, since=DAY)
        db.commit()
        assert res["bytes_moved"] == 10000
        rows = {r.app: r.up + r.down for r in db.query(TrafficDay).filter(TrafficDay.ts == DAY, TrafficDay.host == host)}
        assert rows["pcdn_p2p"] == 7000 and rows["idc_cloud"] == 3000 and rows.get("cn_net", 0) == 0


def test_unmatched_diag(asn):
    e = Engine()
    e.set_lan("192.168.88.0/24")
    now = time.time()
    with e.lock:
        e.add_flow(dict(src="192.168.88.88", dst="10.21.1.1", sport=5000, dport=31000, proto=17, bytes=500,
                        src_mac="AA:00:00:00:25:01"), now)
        e.add_flow(dict(src="10.21.1.1", dst="192.168.88.88", sport=31000, dport=5000, proto=17, bytes=9500), now)
        e.add_flow(dict(src="192.168.88.88", dst="10.23.1.1", sport=5001, dport=443, proto=6, bytes=100,
                        src_mac="AA:00:00:00:25:01"), now)
    e.flush(now)
    with database.session() as db:
        d = stats.unmatched(db, *timeutil.range_bounds("today"))
        assert d["total"] >= 10100
        kinds = {k["kind"]: k["total"] for k in d["kinds"]}
        assert kinds["broadband"] >= 10000 and kinds["idc"] >= 100
        ports = {(p["proto"], p["port"]): p["total"] for p in d["ports"]}
        assert ports[(17, 65536)] >= 10000 and ports[(6, 443)] >= 100
        assert any(a["app"]["id"] == "pcdn_p2p" for a in d["apps"])
        assert db.query(UnmatchedDay).count() >= 2


def test_nat_suspect():
    with database.session() as db:
        db.add(TrafficDay(ts=timeutil.day_bucket(time.time()), host="AA:00:00:00:25:99", app="https",
                          up=0, down=10 ** 15, flows=1))
        db.commit()
        n = stats.nat_suspect(db, *timeutil.range_bounds("today"))
        assert n and n["key"] == "AA:00:00:00:25:99" and n["share"] > 0.6
        db.query(TrafficDay).filter(TrafficDay.host == "AA:00:00:00:25:99").delete()
        db.commit()


def test_selfhost_rule_via_singbox():
    from types import SimpleNamespace
    e = Engine()
    e.set_lan("192.168.88.0/24")
    e.classifier.load_custom([SimpleNamespace(kind="domain", pattern="myvps.example", app_id="my_vps",
                                              app_name="VPS", category="selfhost")])
    now = time.time()
    e.add_proxy_conn("192.168.88.40", 5555, "panel.myvps.example", "198.51.100.7", 443, "tcp", 100, 900, now)
    assert e._buf[("IP:192.168.88.40", "my_vps")][:2] == [100, 900]
    assert e.classifier.category_info(e.classifier.app_info("my_vps").category)["group"] == "common"
