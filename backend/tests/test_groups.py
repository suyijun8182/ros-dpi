"""debug12 第 8 条：应用大类改成维盟的 17 类；旧大类 ID 的迁移，以及指标口径不变。"""
import json

from sqlalchemy import delete

from app import database
from app.classify import migrate
from app.engine import engine
from app.models import AuditRule, Setting

WAYOS = ["http", "game", "tv", "p2p", "common", "im", "music", "stock", "phone", "proxy", "database", "mobile",
         "special", "mining", "pcdn", "other", "unknown"]


def test_groups_are_wayos_17():
    c = engine.classifier
    assert list(c.groups) == WAYOS
    assert c.group_info("tv")["name"] == "网络电视" and c.group_info("pcdn")["name"] == "PCDN"
    cat = lambda a: c.app_info(a).category
    assert c.category_info(cat("https"))["group"] == "common"      # 维盟：HTTPS 在常用协议
    assert c.category_info(cat("http"))["group"] == "http"
    assert c.category_info(cat("douyin"))["group"] == "mobile"     # 短视频在移动应用
    assert c.category_info(cat("wework"))["group"] == "common" and c.category_info(cat("tencent_meeting"))["group"] == "im"
    assert c.classify("203.0.113.5", 6, 3306, None, None) == "mysql"
    assert c.category_info("database")["group"] == "database"
    assert c.classify("203.0.113.5", 6, 443, "eu1.f2pool.com", None) == "mining_pool"
    assert c.classify("203.0.113.5", 6, 443, "x.onethingpcs.com", None) == "onethingcloud"


def test_migrate_old_group_ids():
    with database.session() as db:
        for k in ("group_schema",):
            row = db.get(Setting, k)
            if row:
                db.delete(row)
        row = db.get(Setting, "analysis") or Setting(key="analysis")
        old_cfg = row.value
        row.value = json.dumps({"scenario": "home", "leisure": ["media", "game", "shopping"]})
        db.merge(row)
        db.add(AuditRule(name="t-grp", kind="group", value="media", enabled=1, notify=0, created=0))
        db.add(AuditRule(name="t-up", kind="upload", value="transfer", min_bytes=1, enabled=1, notify=0, created=0))
        db.add(AuditRule(name="t-app", kind="app", value="steam", enabled=1, notify=0, created=0))
        db.commit()
    try:
        with database.session() as db:
            migrate.run(db)
            migrate.run(db)   # 幂等
        with database.session() as db:
            cfg = json.loads(db.get(Setting, "analysis").value)
            assert cfg["leisure"] == ["video", "short_video", "live", "music", "game", "mobile_game", "console_game",
                                      "game_tool", "shopping"]
            rules = {r.name: r.value for r in db.query(AuditRule).filter(AuditRule.name.like("t-%"))}
            assert rules == {"t-grp": "tv", "t-up": "p2p", "t-app": "steam"}
            assert db.get(Setting, "group_schema").value == "2"
    finally:
        with database.session() as db:
            db.execute(delete(AuditRule).where(AuditRule.name.like("t-%")))
            row = db.get(Setting, "analysis")
            if old_cfg is None:
                db.delete(row)
            else:
                row.value = old_cfg
            db.commit()


def test_game_metric_still_covers_mobile_games():
    """“游戏时长”跨了维盟的大类：网络游戏 + 手机游戏（移动应用下）+ 游戏加速器（常用协议下）"""
    from app import insight
    rows = [("h", "mihoyo", 1_000_000, 1_000_000 + 1800, ""), ("h", "steam", 1_000_000 + 3600, 1_000_000 + 5400, ""),
            ("h", "game_booster", 1_000_000 + 7200, 1_000_000 + 7800, "")]
    cfg = {**insight.DEFAULTS}
    out = insight.analyze(rows, 1_000_000 - 3600, 1_000_000 + 86400, cfg)
    assert out["game"] == 1800 + 1800 + 600
