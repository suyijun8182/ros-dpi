"""debug14：上游规则库自动发现、自动登记成应用、识别库更新后自动重算历史分类。"""
import os
import time

import pytest

from app.classify import lists as L
from app.classify.lists import guess_category, lists
from app.classify import Classifier
from app.engine import Engine
from app.models import DnsCache, HostDomainDay, Setting, TrafficDay
from app.reclass import auto_reclassify, reclassify

DAY = 1792900000 - 7 * 86400  # 一周前（重算只处理今天以前的数据）
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


def test_guess_category_whole_words():
    # 0.6.6 按子串猜：Facebook 含 ceb → 银行、Minecraft 含 mine → 挖矿、HeroesoftheStorm 含 tor → 代理
    assert guess_category("Facebook")[0] == "social"
    assert guess_category("Minecraft")[0] != "mining"
    assert guess_category("HeroesoftheStorm")[0] != "proxy"
    assert guess_category("Stripe")[0] != "travel"
    assert guess_category("Alphabet")[0] != "gambling"
    assert guess_category("Airline")[0] == "travel"


def _write_bm7(tmp_path, name, domains):
    d = tmp_path / "lists" / "bm7"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.list").write_text("".join(f"DOMAIN-SUFFIX,{x}\n" for x in domains), encoding="utf-8")


def test_discover_then_vote(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    names = ["BiliBili", "FbMirror", "VideoBundle", "HotMovies", "RandomCorp", "Missing",
             "Global", "Tencent", "AdGuardSDNSFilter", "EasyPrivacy", "AmazonIP"]
    fake = [{"name": n, "type": "dir"} for n in names]
    called = []
    monkeypatch.setattr(L.httpx, "get",
                        lambda url, **kw: called.append(url) or (_Resp(fake) if "ios_rule_script" in url else _Resp([])))
    try:
        lists.reset()
        lists._map = None
        lists._auto = {}
        lists._load_auto()
        c = Classifier()
        fb = c.match_domain("facebook.com")
        video = ["youtube.com", "netflix.com", "iqiyi.com", "youku.com", "mgtv.com", "hulu.com"]
        assert fb and all(c.app_info(c.match_domain(x)).category == "video" for x in video)

        # BiliBili 已映射；Global / Tencent / 广告隐私 / 纯 IP 列表不登记；其余先登记为待定，不进映射
        assert lists.discover() == 5
        assert called and "rule/Clash" in called[0]
        assert "FbMirror" not in lists.map["owner"]
        assert sorted(lists._pending("bm7")) == ["FbMirror", "HotMovies", "Missing", "RandomCorp", "VideoBundle"]
        assert {f for f, _u in lists._files("bm7")} >= {"FbMirror.list", "Missing.list"}   # 待定的也下载

        _write_bm7(tmp_path, "FbMirror", [f"s{i}.facebook.com" for i in range(8)])
        _write_bm7(tmp_path, "VideoBundle", [f"x.{d}" for d in video])
        _write_bm7(tmp_path, "HotMovies", [f"zz{i}.example-movies.test" for i in range(8)])
        _write_bm7(tmp_path, "RandomCorp", ["random-corp.test"])
        assert lists.resolve(c) == 4                     # Missing 没下载到：留到下次
        m = lists.map
        assert m["owner"]["FbMirror"] == fb               # 多数域名属于已有应用：并入
        assert "bm7_fbmirror" not in m["apps"]
        assert m["apps"]["bm7_videobundle"]["category"] == "video"   # 多数属于同一大类：新建该类应用
        assert m["apps"]["bm7_hotmovies"]["category"] == "video"     # 没人认识：按名字猜
        assert m["apps"]["bm7_randomcorp"]["category"] == "site"     # 名字也猜不出：常用网站
        assert lists._pending("bm7") == ["Missing"]
        assert os.path.exists(lists._auto_file())
        assert lists.discover() == 0                     # 再发现一次：没有新增

        # 自动登记的应用不用重启就生效：识别库重新加载（version 变化）后分类器补上新应用
        assert "bm7_videobundle" not in c.apps
        lists.load()
        c.classify("1.1.1.1", 6, 443, "x.youtube.com", None)
        assert c.apps["bm7_videobundle"].category == "video"
        assert Classifier().apps["bm7_hotmovies"].category == "video"
    finally:
        lists.reset()
        lists._map = None
        lists._auto = {}


def test_discover_category_lists(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    ut1 = [{"name": n, "type": "dir"} for n in ["shopping", "cooking", "games_online", "sports_betting"]]
    monkeypatch.setattr(L.httpx, "get", lambda url, **kw: _Resp(ut1) if "ut1" in url else _Resp([]))
    try:
        lists.reset()
        lists._map = None
        lists._auto = {}
        c = Classifier()
        assert lists.discover() == 2                     # shopping 已映射、cooking 猜不出；其余两个待定
        d = tmp_path / "lists" / "ut1"
        d.mkdir(parents=True)
        (d / "games_online.txt").write_text("\n".join(f"g{i}.unknown-games.test" for i in range(6)), encoding="utf-8")
        # 名字像博彩，内容却全是视频网站：投票不符，作废
        (d / "sports_betting.txt").write_text("\n".join(["youtube.com", "netflix.com", "iqiyi.com", "youku.com",
                                                         "mgtv.com", "hulu.com"]), encoding="utf-8")
        assert lists.resolve(c) == 2
        spec = dict(lists._spec("ut1"))
        assert spec["games_online"] == "gen_game"        # 并到该类的“其他游戏网站”
        assert "sports_betting" not in spec
        assert lists._auto["gen_sports_betting"]["rejected"]
        assert lists.discover() == 0                     # 作废的不再登记
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

        class _C(Classifier):
            def classify(self, ip, proto, port, qname, cname):
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


def test_auto_reclassify_runs_on_fingerprint_change(monkeypatch):
    import app.database as database
    from app import reclass, timeutil
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
        assert auto_reclassify(eng, s) is None          # DNS 映射变多不再触发（0.6.6 每次都全量重算）
        real = timeutil.day_bucket
        monkeypatch.setattr(reclass.timeutil, "day_bucket", lambda ts: real(ts) + 86400)
        assert auto_reclassify(eng, s) is not None      # 过了零点：昨天成了可重算的历史
    finally:
        s.query(Setting).filter(Setting.key == "reclass_fp").delete()
        s.query(DnsCache).filter(DnsCache.ip == "198.51.100.1").delete()
        s.commit()
        s.close()


# ---------- 0.6.7：重算只升级、不碰今天（用真实识别器） ----------

def _rows(s, ts):
    return {r.app: r.up + r.down for r in s.query(TrafficDay).filter(TrafficDay.ts == ts, TrafficDay.host == HOST).all()}


def _cleanup(s):
    s.query(TrafficDay).filter(TrafficDay.host == HOST).delete()
    s.query(HostDomainDay).filter(HostDomainDay.host == HOST).delete()
    s.commit()


def test_reclass_never_downgrades():
    import app.database as database
    database.connect_from_saved(force=True)
    s = database.SessionLocal()
    eng = Engine()
    c = eng.classifier
    # 前提：实时按端口 443 认成 HTTPS 的纯 IP、实时按 Telegram IP 段认出的无名域名，历史行里都没有这些信号
    assert c.classify("203.0.113.7", 6, 443, None, None) == "https"
    assert c.classify("91.108.4.10", 6, 443, "x.unknown-zz.test", None) == "telegram"
    assert c.classify("0.0.0.0", 6, 443, "x.unknown-zz.test", None) != "telegram"
    try:
        s.add(TrafficDay(ts=DAY, host=HOST, app="https", up=0, down=1000, flows=10))
        s.add(TrafficDay(ts=DAY, host=HOST, app="telegram", up=0, down=2000, flows=20))
        s.add(HostDomainDay(ts=DAY, host=HOST, domain="203.0.113.7", app="https", bytes=1000))
        s.add(HostDomainDay(ts=DAY, host=HOST, domain="x.unknown-zz.test", app="telegram", bytes=2000))
        s.commit()
        res = reclassify(eng, s)
        s.commit()
        assert _rows(s, DAY) == {"https": 1000, "telegram": 2000}   # 0.6.6：https → other、telegram → https
        assert res["bytes_moved"] == 0
    finally:
        _cleanup(s)
        s.close()


def test_reclass_skips_today():
    """今天的行每分钟落库都会把 app 改回实时分类、字节累加；0.6.6 重算今天会把同一批字节反复搬走"""
    import app.database as database
    from app import timeutil
    database.connect_from_saved(force=True)
    s = database.SessionLocal()
    today = timeutil.day_bucket(time.time())

    class _C(Classifier):
        def classify(self, ip, proto, port, qname, cname):
            return "douyin" if qname == "v.douyin.com" else "cn_net"

    eng = Engine()
    eng.classifier = _C()
    try:
        s.add(TrafficDay(ts=today, host=HOST, app="cn_net", up=0, down=4000, flows=40))
        s.add(HostDomainDay(ts=today, host=HOST, domain="v.douyin.com", app="cn_net", bytes=2000))
        s.commit()
        for _ in range(3):
            assert reclassify(eng, s)["bytes_moved"] == 0
            s.commit()
        assert _rows(s, today) == {"cn_net": 4000}
        # 显式包含今天（before=明天零点）时才会动
        assert reclassify(eng, s, before=today + 86400)["bytes_moved"] == 2000
        s.commit()
    finally:
        _cleanup(s)
        s.close()


def test_oplog_scrubs_adguard_password():
    from app.oplog import scrub
    assert scrub({"adguard_password": "p@ss", "adguard_url": "http://x"}) == {"adguard_password": "***",
                                                                               "adguard_url": "http://x"}
