"""debug14：上游规则库自动发现、自动登记成应用、识别库更新后自动重算历史分类。"""
import os
import time

import pytest

from app.classify import lists as L
from app.classify.lists import guess_category, lists
from app.engine import Engine
from app.models import DnsCache, HostDomainDay, Setting, TrafficDay
from app.reclass import auto_reclassify, reclassify

DAY = 1792900000
HOST = "IP:192.168.8.31"


class _Resp:
    def __init__(self, payload):
        self._p = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._p


def test_guess_category():
    assert guess_category("MangoTV")[0] == "video"
    assert guess_category("ICBCBank")[0] == "bank"
    assert guess_category("OpenAI")[0] == "ai"
    assert guess_category("IPTVMainland2")[0] == "video"
    # 猜不出：bm7 用「常用网站」兜底登记；Hagezi / UT1 分类列表直接跳过
    assert guess_category("RandomCorp") == ("site", False)


def test_discover_registers_new_dirs(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    fake = [{"name": n, "type": "dir"} for n in ["BiliBili", "MangoTV", "RandomCorp", "Global", "HotMovies"]]
    called = []
    monkeypatch.setattr(L.httpx, "get",
                        lambda url, **kw: called.append(url) or (_Resp(fake) if "ios_rule_script" in url else _Resp([])))
    try:
        lists.reset()
        lists._map = None
        lists._auto = {}
        lists._load_auto()
        added = lists.discover()
        assert added == 3                       # BiliBili 已映射、Global 在跳过名单；其余 3 个自动登记
        m = lists.map
        assert m["apps"]["bm7_mangotv"]["category"] == "video"
        assert m["apps"]["bm7_randomcorp"]["category"] == "site"
        assert m["owner"]["MangoTV"] == "bm7_mangotv" and m["owner"]["HotMovies"] == "bm7_hotmovies"
        assert os.path.exists(lists._auto_file())
        assert called and "rule/Clash" in called[0]
        assert lists.discover() == 0            # 再发现一次：没有新增
        # 自动登记的应用分类器认得出（和手工映射同一条管线）
        from app.classify import Classifier
        c = Classifier()
        assert "bm7_mangotv" in c.apps and c.apps["bm7_mangotv"].category == "video"
    finally:
        lists.reset()
        lists._map = None
        lists._auto = {}


def test_reclass_uses_dns_cache_for_ip_rows():
    import app.database as database
    database.connect_from_saved(force=True)
    s = database.SessionLocal()
    try:
        now = int(time.time())
        s.add(DnsCache(ip="203.0.113.9", name="v.douyin.com", expires=now + 3600))
        s.add(HostDomainDay(ts=DAY, host=HOST, domain="203.0.113.9", app="cn_net", base=None, bytes=500))
        s.add(TrafficDay(ts=DAY, host=HOST, app="cn_net", up=100, down=900, flows=10))
        s.commit()

        class _C:
            @staticmethod
            def classify(ip, proto, port, qname, cname):
                return "douyin" if qname == "v.douyin.com" else "cn_net"

        eng = Engine()
        eng.classifier = _C()
        res = reclassify(eng, s)
        s.commit()
        assert res["bytes_moved"] >= 500
        marks = {d.domain: d.app for d in s.query(HostDomainDay).filter(HostDomainDay.host == HOST).all()}
        assert marks["203.0.113.9"] == "douyin"

        # 防倒退：DNS 缓存过期后，已归到具体应用的行不再被搬回笼统分类
        s.query(DnsCache).filter(DnsCache.ip == "203.0.113.9").delete()
        s.commit()
        res2 = reclassify(eng, s)
        s.commit()
        assert res2["bytes_moved"] == 0
        marks = {d.domain: d.app for d in s.query(HostDomainDay).filter(HostDomainDay.host == HOST).all()}
        assert marks["203.0.113.9"] == "douyin"
    finally:
        s.query(TrafficDay).filter(TrafficDay.host == HOST).delete()
        s.query(HostDomainDay).filter(HostDomainDay.host == HOST).delete()
        s.query(DnsCache).filter(DnsCache.ip == "203.0.113.9").delete()
        s.commit()
        s.close()


def test_auto_reclassify_runs_on_fingerprint_change():
    import app.database as database
    database.connect_from_saved(force=True)
    s = database.SessionLocal()
    try:
        s.query(Setting).filter(Setting.key == "reclass_fp").delete()
        s.commit()
        eng = Engine()
        r1 = auto_reclassify(eng, s)
        s.commit()
        assert r1 is not None and "scanned" in r1
        assert auto_reclassify(eng, s) is None          # 指纹没变：什么都不做
        s.add(DnsCache(ip="198.51.100.1", name="x.example.com", expires=int(time.time()) + 600))
        s.commit()
        assert auto_reclassify(eng, s) is not None      # DNS 映射变多：指纹变化 → 重算
    finally:
        s.query(Setting).filter(Setting.key == "reclass_fp").delete()
        s.query(DnsCache).filter(DnsCache.ip == "198.51.100.1").delete()
        s.commit()
        s.close()
