"""0.7.0 多站点 API：?site= 选站点，同一个终端 key 在两个站点各查各的；普通用户只能看授权的站点；审计规则可限定站点"""
import time

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy import delete

from app import database, timeutil
from app.audit import Auditor
from app.engine import engine
from app.main import app
from app.models import (AuditEvent, AuditRule, Host, Person, Department, Site, TrafficDay, User, UserSite)
from app.security import forget_roles
from app.sites import registry

KEY = "AA:00:00:00:70:01"


def _login(c, u, p):
    return {"Authorization": "Bearer " + c.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]}


@pytest.fixture
def two_sites():
    day = timeutil.day_bucket(time.time())
    with database.session() as db:
        db.add(Site(slug="office", name="公司", sources="10.8.0.2", enabled=1, sort=1, created=int(time.time())))
        db.get(Site, "default").sources = "192.168.88.1"
        for site, up, name in (("default", 1000, "家里电脑"), ("office", 7000, "公司电脑")):
            db.merge(TrafficDay(site=site, ts=day, host=KEY, app="wechat", up=up, down=0, flows=1))
            db.merge(Host(site=site, key=KEY, mac=KEY, ip="192.168.88.50", hostname=name,
                          first_seen=int(time.time()), last_seen=int(time.time())))
        db.commit()
    registry.load()
    with TestClient(app) as c:
        if not c.get("/api/auth/status").json()["initialized"]:
            c.post("/api/auth/setup", json={"username": "admin", "password": "secret1"})
        yield c, _login(c, "admin", "secret1")
    with database.session() as db:
        for m in (TrafficDay, Host):
            db.execute(delete(m).where(m.host == KEY) if m is TrafficDay else delete(m).where(m.key == KEY))
        db.execute(delete(AuditEvent).where(AuditEvent.host == KEY))
        db.execute(delete(AuditRule).where(AuditRule.name.like("v070%")))
        db.execute(delete(Person).where(Person.name == "公司的人"))
        db.execute(delete(Department).where(Department.name == "公司部门"))
        db.execute(delete(UserSite).where(UserSite.site == "office"))
        db.execute(delete(Site).where(Site.slug == "office"))
        db.get(Site, "default").sources = ""
        db.commit()
    registry.load()
    forget_roles()


def test_same_host_key_per_site(two_sites):
    c, h = two_sites
    home = {r["key"]: r for r in c.get("/api/hosts?site=default", headers=h).json()}
    office = {r["key"]: r for r in c.get("/api/hosts?site=office", headers=h).json()}
    assert home[KEY]["hostname"] == "家里电脑" and home[KEY]["today"]["up"] >= 1000
    assert office[KEY]["hostname"] == "公司电脑" and office[KEY]["today"]["up"] == 7000
    d = c.get(f"/api/hosts/{KEY}/detail?site=office", headers=h).json()
    assert d["hostname"] == "公司电脑" and d["totals"]["today"]["up"] == 7000
    assert c.get("/api/overview?site=office", headers=h).json()["totals"]["today"]["up"] == 7000
    # 改名只改这个站点
    assert c.patch(f"/api/hosts/{KEY}?site=office", json={"alias": "前台"}, headers=h).json()["name"] == "前台"
    assert c.get(f"/api/hosts/{KEY}/detail?site=default", headers=h).json()["name"] != "前台"
    c.patch(f"/api/hosts/{KEY}?site=office", json={"alias": ""}, headers=h)
    assert c.get("/api/overview?site=nope", headers=h).status_code == 404
    # 不传 site：第一个站点（默认站点），升级前的 API 令牌照常能用
    assert c.get(f"/api/hosts/{KEY}/detail", headers=h).json()["hostname"] == "家里电脑"


def test_people_are_per_site(two_sites):
    c, h = two_sites
    dept = c.post("/api/departments?site=office", json={"name": "公司部门"}, headers=h).json()
    p = c.post("/api/people?site=office", json={"name": "公司的人", "dept_id": dept["id"], "hosts": [KEY]}, headers=h)
    assert p.status_code == 200, p.text
    names = lambda site: {x["name"] for x in c.get(f"/api/people?site={site}", headers=h).json()["people"]}  # noqa: E731
    assert "公司的人" in names("office") and "公司的人" not in names("default")
    # 默认站点里同一个终端没有归属
    assert c.get(f"/api/hosts/{KEY}/detail?site=default", headers=h).json()["person"] is None
    assert c.get(f"/api/hosts/{KEY}/detail?site=office", headers=h).json()["person"]["name"] == "公司的人"


def test_user_only_sees_granted_sites(two_sites):
    c, h = two_sites
    r = c.post("/api/auth/users", json={"username": "v070user", "password": "viewer1", "role": "user",
                                        "sites": ["office"]}, headers=h)
    uid = r.json()["id"]
    try:
        hu = _login(c, "v070user", "viewer1")
        assert c.get("/api/overview?site=default", headers=hu).status_code == 403
        assert c.get("/api/overview?site=office", headers=hu).status_code == 200
        # 不传 site：用他能看的第一个站点
        assert c.get(f"/api/hosts/{KEY}/detail", headers=hu).json()["hostname"] == "公司电脑"
    finally:
        with database.session() as db:
            db.execute(delete(UserSite).where(UserSite.user_id == uid))
            db.execute(delete(User).where(User.id == uid))
            db.commit()


def test_audit_rule_site_scope(two_sites):
    c, h = two_sites
    body = {"name": "v070 新终端", "kind": "new_host", "all_sites": False}
    r = c.post("/api/audit/rules?site=office", json=body, headers=h).json()
    assert r["site"] == "office"
    assert r["id"] in {x["id"] for x in c.get("/api/audit/rules?site=office", headers=h).json()}
    assert r["id"] not in {x["id"] for x in c.get("/api/audit/rules?site=default", headers=h).json()}
    assert c.delete(f"/api/audit/rules/{r['id']}?site=default", headers=h).status_code == 404
    # 限定了终端的规则只能是当前站点
    scoped = c.post("/api/audit/rules?site=default", json={"name": "v070 限定", "kind": "new_host", "hosts": [KEY]},
                    headers=h).json()
    assert scoped["site"] == "default"
    a = Auditor(engine)
    now = time.time()
    a.evaluate({}, {}, [(KEY, "192.168.88.50", KEY)], now, site="default")
    with database.session() as db:
        fired = {(e.site, e.rule_name) for e in db.query(AuditEvent).filter(AuditEvent.host == KEY)}
    assert ("default", "v070 限定") in fired and not any(n == "v070 新终端" for _s, n in fired)
    a.evaluate({}, {}, [(KEY, "192.168.88.50", KEY)], now, site="office")
    with database.session() as db:
        fired = {(e.site, e.rule_name) for e in db.query(AuditEvent).filter(AuditEvent.host == KEY)}
    assert ("office", "v070 新终端") in fired and ("office", "v070 限定") not in fired
    # 事件按站点列出
    ev = c.get("/api/audit/events?site=office", headers=h).json()
    assert {e["rule"] for e in ev["rows"] if e["host"] == KEY and e["rule"].startswith("v070")} == {"v070 新终端"}


def test_get_routes_no_500_on_second_site(two_sites):
    c, h = two_sites
    bad = []
    for r in app.routes:
        if not isinstance(r, APIRoute) or "GET" not in r.methods or "{" in r.path:
            continue
        if not r.path.startswith("/api/") or r.path in {"/api/system/update"}:
            continue
        resp = c.get(r.path + "?site=office", headers=h)
        if resp.status_code >= 500:
            bad.append((r.path, resp.status_code, resp.text[:120]))
    assert not bad, bad


def test_custom_rule_for_one_site(two_sites):
    """只对公司生效的规则：公司的流量按它认，家里照旧；重算历史也只改公司的行"""
    from app.models import CustomRule, HostDomainDay
    from app.reclass import reclassify_rules
    c, h = two_sites
    office = registry.get("office")
    assert office.classifier.classify("203.0.113.9", 6, 443, "erp.v070corp.example", None) != "v070_erp"
    r = c.post("/api/rules", json={"kind": "domain", "pattern": "v070corp.example", "app_id": "v070_erp",
                                   "app_name": "公司 ERP", "category": "work", "site": "office"}, headers=h)
    assert r.status_code == 200, r.text
    rid = r.json()["id"]
    try:
        assert r.json()["site"] == "office"
        assert office.classifier.classify("203.0.113.9", 6, 443, "erp.v070corp.example", None) == "v070_erp"
        assert engine.classifier.classify("203.0.113.9", 6, 443, "erp.v070corp.example", None) != "v070_erp"
        assert engine.classifier.app_info("v070_erp").name == "公司 ERP"      # 应用全局都认得（名称、统计）
        # 历史：两个站点昨天都访问过这个域名，重算后只有公司的改过去
        day = timeutil.day_bucket(time.time()) - 86400
        with database.session() as db:
            for site in ("default", "office"):
                db.merge(HostDomainDay(site=site, ts=day, host=KEY, domain="erp.v070corp.example", app="https",
                                       base="v070corp.example", bytes=500))
                db.merge(TrafficDay(site=site, ts=day, host=KEY, app="https", up=200, down=300, flows=2))
            db.commit()
            reclassify_rules(engine, db, [("domain", "v070corp.example", None)])
            db.commit()
            got = {(x.site, x.app) for x in db.query(TrafficDay).filter(TrafficDay.ts == day, TrafficDay.host == KEY,
                                                                           TrafficDay.up > 0)}
        assert got == {("default", "https"), ("office", "v070_erp")}
    finally:
        c.delete(f"/api/rules/{rid}", headers=h)
        with database.session() as db:
            db.execute(delete(HostDomainDay).where(HostDomainDay.host == KEY))
            db.execute(delete(TrafficDay).where(TrafficDay.host == KEY))
            db.commit()
    assert office.classifier.classify("203.0.113.9", 6, 443, "erp.v070corp.example", None) != "v070_erp"


def test_user_site_grants_api(two_sites):
    c, h = two_sites
    # 多站点时新建普通用户必须选站点
    assert c.post("/api/auth/users", json={"username": "v070g", "password": "viewer1", "role": "user"},
                  headers=h).status_code == 400
    assert c.post("/api/auth/users", json={"username": "v070g", "password": "viewer1", "role": "user", "sites": ["nope"]},
                  headers=h).status_code == 400
    r = c.post("/api/auth/users", json={"username": "v070g", "password": "viewer1", "role": "user", "sites": ["office"]},
               headers=h)
    assert r.status_code == 200 and r.json()["sites"] == ["office"]
    uid = r.json()["id"]
    try:
        hu = _login(c, "v070g", "viewer1")
        assert [s["slug"] for s in c.get("/api/sites/mine", headers=hu).json()["sites"]] == ["office"]
        assert c.get("/api/overview?site=default", headers=hu).status_code == 403
        # 改授权：同一个登录立即生效
        assert c.put(f"/api/auth/users/{uid}", json={"sites": ["default"]}, headers=h).json()["sites"] == ["default"]
        assert c.get("/api/overview?site=default", headers=hu).status_code == 200
        assert c.get("/api/overview?site=office", headers=hu).status_code == 403
        assert c.put(f"/api/auth/users/{uid}", json={"sites": []}, headers=h).status_code == 400
        assert {u["username"]: u["sites"] for u in c.get("/api/auth/users", headers=h).json()}["v070g"] == ["default"]
    finally:
        c.delete(f"/api/auth/users/{uid}", headers=h)
    with database.session() as db:
        assert db.query(UserSite).filter(UserSite.user_id == uid).count() == 0
