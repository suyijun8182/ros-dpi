"""debug12：落库失败不丢数据、分批清理、登录限速、token 版本吊销、访问目标 SQL 聚合。"""
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import insert

from app import database, security, stats, timeutil
from app.database import upsert_add
from app.engine import Engine
from app.main import app
from app.models import AccessLog, HostDomainDay, TrafficMinute

from packets import ipfix, tzsp_dns


@pytest.fixture
def login_fails_cleared():
    """限速状态是进程级内存，进出测试都要清干净，避免影响其它测试的登录。"""
    security._login_fails.clear()
    yield
    security._login_fails.clear()


def _engine():
    e = Engine()
    e.set_lan("192.168.88.0/24,2408:8000:1:2::/64")
    return e


def test_flush_failure_keeps_data_for_retry(monkeypatch):
    """数据库抖动时这一分钟的数据不能丢：失败留在内存，下次 flush 一起写入。"""
    e = _engine()
    e.on_tzsp(tzsp_dns("192.168.88.10", "www.bilibili.com", ["5.5.5.5"]))
    e.on_ipfix(ipfix([dict(src="192.168.88.10", dst="5.5.5.5", sport=1, dport=443, proto=6, nbytes=1000,
                           mac="AA:00:00:00:00:10")]), "10.0.0.1")
    now = time.time()

    def boom():
        raise RuntimeError("db down")
    monkeypatch.setattr(database, "session", boom)
    e.flush(now)
    assert e._pending is not None and ("AA:00:00:00:00:10", "bilibili") in e._pending["buf"]
    monkeypatch.undo()

    e.flush(now + 60)
    assert e._pending is None
    with database.session() as db:
        t = stats.total(db, *timeutil.range_bounds("today"), host="AA:00:00:00:00:10")
        assert t["total"] == 1000
        n = db.query(AccessLog).filter(AccessLog.host == "AA:00:00:00:00:10").count()
        assert n >= 1  # 访问日志也要补写上


def test_cleanup_batched():
    """按保留期清理：旧的分批删掉，新的留下（TrafficMinute 走复合主键的批量删除路径）。"""
    now = int(time.time())
    old_min, new_min = now - 3 * 86400, now - 60
    with database.session() as db:
        db.execute(insert(TrafficMinute.__table__), [
            {"ts": old_min + i, "host": f"OLD:{i}", "app": "web", "up": 1, "down": 1, "flows": 1} for i in range(8)
        ] + [{"ts": new_min, "host": "NEW", "app": "web", "up": 1, "down": 1, "flows": 1}])
        db.execute(insert(AccessLog.__table__), [
            {"id": 9_000_000_000 + i, "ts_start": now - 40 * 86400, "ts_end": now - 40 * 86400 + 10,
             "host": f"OLD:{i}", "host_ip": "192.168.88.1", "dest": "x.com", "app": "web", "conns": 1, "up": 1, "down": 1}
            for i in range(6)
        ] + [{"id": 9_000_000_100, "ts_start": now - 10, "ts_end": now, "host": "NEW", "host_ip": "192.168.88.2",
              "dest": "y.com", "app": "web", "conns": 1, "up": 1, "down": 1}])
        db.commit()
    _engine().cleanup()
    with database.session() as db:
        assert db.query(TrafficMinute).filter(TrafficMinute.host.like("OLD:%")).count() == 0
        assert db.query(TrafficMinute).filter(TrafficMinute.host == "NEW").count() == 1
        assert db.query(AccessLog).filter(AccessLog.host.like("OLD:%")).count() == 0
        assert db.query(AccessLog).filter(AccessLog.host == "NEW").count() == 1


def test_destinations_sql_aggregation():
    """访问目标排行：聚合在 SQL 侧完成，合并 / 域名 IP 筛选 / 搜索行为与原实现一致。
    用例里用独立的域名，避免其它测试往同一张表写的数据影响断言。"""
    day = timeutil.day_bucket(time.time())
    rows = [
        {"ts": day, "host": "H1", "domain": "a.d12test.example", "app": "bilibili", "bytes": 100,
         "base": "d12test.example"},
        {"ts": day, "host": "H1", "domain": "www.d12test.example", "app": "bilibili", "bytes": 300,
         "base": "d12test.example"},
        {"ts": day, "host": "H2", "domain": "www.d12test.example", "app": "bilibili", "bytes": 50,
         "base": "d12test.example"},
        {"ts": day, "host": "H1", "domain": "203.0.113.9", "app": "https", "bytes": 700, "base": "203.0.113.9"},
    ]
    with database.session() as db:
        upsert_add(db, HostDomainDay.__table__, rows, ["ts", "host", "domain"], ["bytes"], ["app", "base"])
        db.commit()
        s, t = timeutil.range_bounds("today")

        merged = {r["dest"]: r for r in stats.destinations(db, s, t, merge=True)}
        assert merged["d12test.example"]["bytes"] == 450
        assert merged["d12test.example"]["hosts"] == 2
        assert merged["d12test.example"]["names"] == 2  # 两个子域名
        assert merged["d12test.example"]["app"]["id"] == "bilibili"
        assert merged["203.0.113.9"]["ip"] is True

        # 不合并：每个子域名 / IP 各自一行
        plain = {r["dest"]: r for r in stats.destinations(db, s, t)}
        assert plain["a.d12test.example"]["bytes"] == 100 and plain["203.0.113.9"]["bytes"] == 700

        assert [r["dest"] for r in stats.destinations(db, s, t, merge=True, kind="ip")
                if r["dest"] == "203.0.113.9"] == ["203.0.113.9"]
        doms = stats.destinations(db, s, t, kind="domain")
        assert doms and all(not r["ip"] for r in doms)
        assert "203.0.113.9" not in {r["dest"] for r in doms}

        assert [r["dest"] for r in stats.destinations(db, s, t, q="d12test", merge=True)] == ["d12test.example"]
        assert stats.destinations(db, s, t, q="no-such-thing-d12") == []


def test_backfill_base_domain():
    """升级回填：旧版本写入的 host_domain_day 行（base 为空）补上主域名。"""
    day = timeutil.day_bucket(time.time())
    with database.session() as db:
        db.execute(insert(HostDomainDay.__table__),
                   [{"ts": day, "host": "H9", "domain": "cdn.example.com.cn", "app": "web", "bytes": 5}])
        db.commit()
        Engine._backfill_base(db)
        row = db.get(HostDomainDay, (day, "H9", "cdn.example.com.cn"))
        assert row.base == "example.com.cn"
        merged = stats.destinations(db, *timeutil.range_bounds("today"), merge=True)
        assert any(r["dest"] == "example.com.cn" for r in merged)


def test_login_rate_limit(login_fails_cleared):
    """同一 IP + 用户名连续失败 5 次后锁定 15 分钟，密码正确也进不来；其它账号不受影响。"""
    with TestClient(app) as c:
        if not c.get("/api/auth/status").json()["initialized"]:
            c.post("/api/auth/setup", json={"username": "admin", "password": "secret1"})
        ha = {"Authorization": "Bearer " + c.post("/api/auth/login", json={"username": "admin", "password": "secret1"}).json()["token"]}
        assert c.post("/api/auth/users", json={"username": "lockme", "password": "lockpass1", "role": "user"},
                      headers=ha).status_code == 200
        for _ in range(5):
            assert c.post("/api/auth/login", json={"username": "lockme", "password": "wrong"}).status_code == 401
        # 第 6 次即使密码正确也被锁定
        assert c.post("/api/auth/login", json={"username": "lockme", "password": "lockpass1"}).status_code == 429
        # 其它用户名不受影响
        assert c.post("/api/auth/login", json={"username": "admin", "password": "secret1"}).status_code == 200
        security._login_fails.clear()
        assert c.post("/api/auth/login", json={"username": "lockme", "password": "lockpass1"}).status_code == 200


def test_token_invalidated_on_password_or_role_change(login_fails_cleared):
    """改密码 / 管理员改权限后，已签发的旧 token 立即失效。"""
    with TestClient(app) as c:
        if not c.get("/api/auth/status").json()["initialized"]:
            c.post("/api/auth/setup", json={"username": "admin", "password": "secret1"})
        ha = {"Authorization": "Bearer " + c.post("/api/auth/login", json={"username": "admin", "password": "secret1"}).json()["token"]}
        r = c.post("/api/auth/users", json={"username": "bob", "password": "bobpass1", "role": "user"}, headers=ha)
        assert r.status_code == 200, r.text
        uid = r.json()["id"]
        hb = {"Authorization": "Bearer " + c.post("/api/auth/login", json={"username": "bob", "password": "bobpass1"}).json()["token"]}
        assert c.get("/api/auth/me", headers=hb).status_code == 200

        # bob 自己改密码 → 旧 token 失效（角色缓存清掉，立即生效）
        assert c.post("/api/auth/password", json={"old_password": "bobpass1", "new_password": "bobpass2"},
                      headers=hb).status_code == 200
        assert c.get("/api/auth/me", headers=hb).status_code == 401
        hb = {"Authorization": "Bearer " + c.post("/api/auth/login", json={"username": "bob", "password": "bobpass2"}).json()["token"]}

        # 管理员提权 → bob 的旧 token 失效
        assert c.put(f"/api/auth/users/{uid}", json={"role": "admin"}, headers=ha).status_code == 200
        assert c.get("/api/auth/me", headers=hb).status_code == 401
        assert c.delete(f"/api/auth/users/{uid}", headers=ha).status_code == 200
    security.forget_roles()
