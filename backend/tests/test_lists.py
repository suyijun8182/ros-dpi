"""debug12：第三方规则库 blackmatrix7（应用级）、Hagezi / UT1（分类级）的识别顺序与权重。"""
import pytest

from app.classify import Classifier
from app.classify import lists as L
from app.classify.lists import _HashTable, lists
from app.classify.sources import sources as src


@pytest.fixture
def loaded(tmp_path, monkeypatch):
    """小份样本：bm7 三个目录、Hagezi 两个列表、UT1 两个列表、国内域名列表"""
    bm7 = tmp_path / "lists" / "bm7"
    bm7.mkdir(parents=True)
    (bm7 / "BiliBili.list").write_text("# NAME: BiliBili\nDOMAIN-SUFFIX,zz-bili-extra.example\nDOMAIN,cdn.zz-bili-full.example\n"
                                       "DOMAIN-KEYWORD,bili\nPROCESS-NAME,tv.danmaku.bili\n", encoding="utf-8")
    # 同样长的后缀：内置库（bilibili.com → bilibili）优先；更长的后缀：bm7 赢
    (bm7 / "TencentVideo.list").write_text("DOMAIN-SUFFIX,bilibili.com\nDOMAIN-SUFFIX,vtest.qq.com\n", encoding="utf-8")
    (bm7 / "Zalo.list").write_text("DOMAIN-SUFFIX,zalo-test.example\nIP-CIDR,198.18.77.0/24,no-resolve\n"
                                   "IP-CIDR,91.108.4.0/22,no-resolve\n", encoding="utf-8")
    hg = tmp_path / "lists" / "hagezi"
    hg.mkdir(parents=True)
    (hg / "nsfw.txt").write_text("# Hagezi\nadult-test.example\nbilibili.com\n", encoding="utf-8")
    (hg / "gambling.medium.txt").write_text("both-lists.example\n*.wild-test.example\n", encoding="utf-8")
    (hg / "social.txt").write_text("example.org\n", encoding="utf-8")
    ut = tmp_path / "lists" / "ut1"
    ut.mkdir(parents=True)
    (ut / "games.txt").write_text("game-test.example\nboth-lists.example\ncn-game.example-test.cn\n0123456789.com\n1.2.3.4\n",
                                  encoding="utf-8")
    (ut / "shopping.txt").write_text("shop.example.org\n", encoding="utf-8")
    (tmp_path / "china-domains.conf").write_text("server=/example-test.cn/114.114.114.114\n", encoding="utf-8")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setattr(L, "_enabled", lambda sid: True)
    monkeypatch.setattr("app.classify.sources._enabled", lambda sid: True)
    src.reset()
    src.load()
    lists.reset()
    lists.load()
    yield lists
    lists.reset()
    src.reset()


def test_bm7_app_level(loaded):
    c = Classifier()
    # 补内置库 / v2fly 没有的域名
    assert c.classify("203.0.113.9", 6, 443, "a.zz-bili-extra.example", None) == "bilibili"
    assert c.classify("203.0.113.9", 6, 443, "cdn.zz-bili-full.example", None) == "bilibili"
    assert c.classify("203.0.113.9", 6, 443, "x.cdn.zz-bili-full.example", None) == "https"   # DOMAIN 是精确匹配
    # 后缀一样长：内置库优先；bm7 的后缀更长：bm7 赢
    assert c.classify("203.0.113.9", 6, 443, "www.bilibili.com", None) == "bilibili"
    assert c.classify("203.0.113.9", 6, 443, "x.vtest.qq.com", None) == "tencent_video"
    assert c.classify("203.0.113.9", 6, 443, "x.qq.com", None) == "qq"
    # bm7 新增的应用带分类
    assert c.classify("203.0.113.9", 6, 443, "chat.zalo-test.example", None) == "bm7_zalo"
    assert c.app_info("bm7_zalo").category == "im"
    # bm7 的 IP 段：在内置 CIDR 之后（91.108.4.0/22 内置属于 Telegram）
    assert c.classify("198.18.77.5", 6, 443, None, None) == "bm7_zalo"
    assert c.classify("91.108.4.10", 6, 443, None, None) == "telegram"


def test_category_lists_order(loaded):
    c = Classifier()
    assert c.classify("203.0.113.9", 6, 443, "adult-test.example", None) == "gen_adult"
    assert c.app_info("gen_adult").category == "adult"
    assert c.classify("203.0.113.9", 6, 443, "www.game-test.example", None) == "gen_game"
    assert c.classify("203.0.113.9", 6, 443, "a.wild-test.example", None) == "gen_gambling"   # *. 前缀
    # 两个列表都有：Hagezi 优先
    assert c.classify("203.0.113.9", 6, 443, "both-lists.example", None) == "gen_gambling"
    assert c.app_info("gen_gambling").category == "gambling"
    # 命中的后缀更长者赢（不论来自哪个列表）
    assert c.classify("203.0.113.9", 6, 443, "a.shop.example.org", None) == "gen_shopping"
    assert c.classify("203.0.113.9", 6, 443, "a.example.org", None) == "gen_social"
    # 应用级永远优先：bilibili.com 在成人列表里也不影响
    assert c.classify("203.0.113.9", 6, 443, "www.bilibili.com", None) == "bilibili"
    # 分类级排在国内域名列表之前
    assert c.classify("203.0.113.9", 6, 443, "cn-game.example-test.cn", None) == "gen_game"
    assert c.classify("203.0.113.9", 6, 443, "other.example-test.cn", None) == "cn_web"
    # v2fly 的地区兜底条目由分类列表细化
    assert c.classify("203.0.113.9", 6, 443, "www.0123456789.com", None) == "gen_game"
    # IP 写在列表里会被忽略；列表外的域名仍走通用端口
    assert c.classify("1.2.3.4", 6, 443, None, None) == "https"
    assert c.classify("203.0.113.9", 6, 443, "nothing.example", None) == "https"


def test_cache_cleared_on_reload(loaded):
    c = Classifier()
    assert c.classify("203.0.113.9", 6, 443, "adult-test.example", None) == "gen_adult"
    lists.reset()
    assert c.classify("203.0.113.9", 6, 443, "adult-test.example", None) == "https"


def test_rows_and_hash_table(loaded):
    rows = {r["id"]: r for r in lists.rows()}
    assert rows["bm7"]["rules"] == 7 and rows["bm7"]["apps"] == 3
    assert rows["hagezi"]["domains"] == 5 and rows["ut1"]["domains"] == 5
    t = _HashTable.build([("a", ["x.example", "y.example"]), ("b", ["y.example", "z.example"])])
    assert len(t) == 3 and t.get("y.example") == "a" and t.get("z.example") == "b" and t.get("q.example") is None
    assert t.lookup("deep.sub.x.example") == ("a", 2)


def test_map_targets_exist():
    """bm7_map.yaml 里并入的应用都存在（v2fly 换代删了某个应用时这里会报出来），新应用的分类都存在"""
    c = Classifier(extra_file=None)
    full = Classifier()
    m = L.load_map()
    missing = sorted({a for a in m["owner"].values() if a not in full.apps})
    assert missing == []
    assert all(a["category"] in c.categories for a in m["apps"].values())
