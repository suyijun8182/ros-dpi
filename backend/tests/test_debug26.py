"""debug26：未识别域名 Top 的归类——弹窗推荐与匹配范围、保存后只重算这条规则的历史、修改 / 删除回退、忽略、社区贡献。"""
import time

from fastapi.testclient import TestClient

from app import database, ruleassist, share, timeutil
from app.engine import engine
from app.main import app
from app.models import CustomRule, HostDomainDay, Setting, TrafficDay

DAY = timeutil.day_bucket(time.time()) - 2 * 86400
H, H2 = "AA:00:00:00:26:01", "AA:00:00:00:26:02"
DOM = "foo-unknown26.com"


def _admin(c):
    if not c.get("/api/auth/status").json()["initialized"]:
        c.post("/api/auth/setup", json={"username": "admin", "password": "secret1"})
    tok = c.post("/api/auth/login", json={"username": "admin", "password": "secret1"}).json()["token"]
    return {"Authorization": "Bearer " + tok}


def _clean(db):
    db.query(HostDomainDay).filter(HostDomainDay.host.in_([H, H2])).delete(synchronize_session=False)
    db.query(TrafficDay).filter(TrafficDay.host.in_([H, H2])).delete(synchronize_session=False)
    db.query(CustomRule).filter(CustomRule.pattern.like("%unknown26%")).delete(synchronize_session=False)
    row = db.get(Setting, ruleassist.IGNORE_KEY)
    if row is not None:
        db.delete(row)
    db.commit()


def _seed():
    with database.session() as db:
        _clean(db)
        for host, d, a, b in ((H, "cdn." + DOM, "https", 5000), (H, "img." + DOM, "https", 3000),
                              (H2, "www." + DOM, "bilibili", 100)):
            db.add(HostDomainDay(ts=DAY, host=host, domain=d, app=a, base=DOM, bytes=b))
        db.add(TrafficDay(ts=DAY, host=H, app="https", up=1000, down=9000, flows=10))
        db.commit()
    engine.reload_rules()


def _day():
    with database.session() as db:
        return {r.app: r.up + r.down for r in db.query(TrafficDay).filter(TrafficDay.ts == DAY, TrafficDay.host == H)}


def test_scope_shared_suffix():
    assert ruleassist.scope("cdn.foo.example.com") == {"domain": "cdn.foo.example.com", "base": "example.com",
                                                       "default": "base", "shared": None}
    s = ruleassist.scope("a.d111.cloudfront.net")
    assert s["base"] == "d111.cloudfront.net" and s["default"] == "full" and s["shared"] == "cloudfront.net"
    s = ruleassist.scope("x.us-east-1.elb.amazonaws.com")
    assert s["shared"] == "elb.amazonaws.com" and s["base"] == "us-east-1.elb.amazonaws.com"
    assert ruleassist.scope("nas.suyijun.dpdns.org")["base"] == "suyijun.dpdns.org"


def test_classify_flow():
    _seed()
    try:
        with TestClient(app) as c:
            h = _admin(c)
            sg = c.get("/api/rules/suggest", params={"domain": "cdn." + DOM}, headers=h).json()
            assert sg["base"] == DOM and sg["default"] == "base"
            assert sg["candidates"][0]["app"]["id"] == "bilibili" and sg["candidates"][0]["source"] == "sibling"

            unk = {u["domain"] for u in c.get("/api/rules/unknown-domains?range=last30", headers=h).json()}
            assert {"cdn." + DOM, "img." + DOM} <= unk

            # 归类：历史立即改算，列表里不再出现
            r = c.post("/api/rules/classify", json={"patterns": [DOM, DOM.upper()], "app_id": "bilibili"}, headers=h).json()
            assert r["patterns"] == [DOM] and r["bytes_moved"] == 8000 and r["app"]["id"] == "bilibili"
            assert _day() == {"https": 2000, "bilibili": 8000}
            unk = {u["domain"] for u in c.get("/api/rules/unknown-domains?range=last30", headers=h).json()}
            assert not unk & {"cdn." + DOM, "img." + DOM}

            # 修改：按这条规则归过去的历史改到新应用
            rule = next(x for x in c.get("/api/rules", headers=h).json() if x["pattern"] == DOM)
            r = c.put(f"/api/rules/{rule['id']}", json={"app_id": "douyin"}, headers=h).json()
            assert r["app_id"] == "douyin" and r["bytes_moved"] == 8000
            assert _day() == {"https": 2000, "bilibili": 0, "douyin": 8000}

            # 删除：退回识别库现在的结果（这里是 HTTPS）
            r = c.delete(f"/api/rules/{rule['id']}", headers=h).json()
            assert r["bytes_moved"] == 8000 and _day()["https"] == 10000
    finally:
        with database.session() as db:
            _clean(db)
        engine.reload_rules()


def test_ignore():
    _seed()
    try:
        with TestClient(app) as c:
            h = _admin(c)
            assert c.post("/api/rules/ignore", json={"patterns": [DOM]}, headers=h).json()["ok"]
            assert [x["pattern"] for x in c.get("/api/rules/ignored", headers=h).json()] == [DOM]
            unk = {u["domain"] for u in c.get("/api/rules/unknown-domains?range=last30", headers=h).json()}
            assert not unk & {"cdn." + DOM, "img." + DOM}
            assert _day() == {"https": 10000}    # 流量照旧算未识别
            assert c.post("/api/rules/unignore", json={"patterns": [DOM]}, headers=h).json()["ok"]
            assert c.post("/api/rules/unignore", json={"patterns": [DOM]}, headers=h).status_code == 404
            unk = {u["domain"] for u in c.get("/api/rules/unknown-domains?range=last30", headers=h).json()}
            assert "cdn." + DOM in unk
    finally:
        with database.session() as db:
            _clean(db)


def test_share_opt_in():
    _seed()
    try:
        with TestClient(app) as c:
            h = _admin(c)
            c.post("/api/rules/classify", json={"patterns": [DOM], "app_id": "bilibili"}, headers=h)
            with database.session() as db:
                doms = {d["domain"] for d in share.export_entries(engine, db)[1]}
            assert not any(d.endswith(DOM) for d in doms)    # 默认不贡献

            r = c.post("/api/rules/classify", json={"patterns": [DOM], "app_id": "bilibili", "share": True}, headers=h)
            assert r.status_code == 200
            with database.session() as db:
                doms = {d["domain"] for d in share.export_entries(engine, db)[1]}
            assert {"cdn." + DOM, "img." + DOM} <= doms

            # 自建服务：勾了也不贡献
            r = c.post("/api/rules", json={"kind": "domain", "pattern": "nas.unknown26.top", "app_id": "my_nas26",
                                           "app_name": "我的 NAS", "category": "selfhost", "share": True}, headers=h).json()
            assert r["share"] is False
            # 已有的自定义应用：名称和分类沿用
            r = c.post("/api/rules/classify", json={"patterns": ["nas2.unknown26.top"], "app_id": "my_nas26"},
                       headers=h).json()
            rule = next(x for x in c.get("/api/rules", headers=h).json() if x["pattern"] == "nas2.unknown26.top")
            assert rule["app_name"] == "我的 NAS" and rule["category"] == "selfhost"
    finally:
        with database.session() as db:
            _clean(db)
        engine.reload_rules()
