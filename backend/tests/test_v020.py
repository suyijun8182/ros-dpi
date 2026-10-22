import time

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app import database, stats, timeutil
from app.engine import engine
from app.main import app


def _token(c):
    if not c.get("/api/auth/status").json()["initialized"]:
        c.post("/api/auth/setup", json={"username": "admin", "password": "secret1"})
    return {"Authorization": "Bearer " + c.post("/api/auth/login", json={"username": "admin", "password": "secret1"}).json()["token"]}


def test_online_session_and_conns_and_search():
    now = time.time()
    with engine.lock:
        for i in range(3):
            engine.add_flow(dict(src="192.168.88.70", dst="8.8.8.8", sport=1000 + i, dport=443, proto=6, bytes=100,
                                 src_mac="AA:00:00:00:00:70"), now)
    engine.flush(now)
    with TestClient(app) as c:
        h = _token(c)
        host = next(x for x in c.get("/api/hosts", headers=h).json() if x["key"] == "AA:00:00:00:00:70")
        assert host["online"] and host["online_since"] and host["conns"] == 3
        r = c.get("/api/search?q=88.70", headers=h).json()
        assert r["hosts"][0]["key"] == "AA:00:00:00:00:70"
        assert c.get("/api/search?q=bilibili", headers=h).json()["apps"][0]["id"] == "bilibili"
        ov = c.get("/api/overview", headers=h).json()
        assert ov["new_today"] >= 1 and len(ov["online_realtime"]) >= 60
        assert max(p["n"] for p in ov["online_trend"]) >= 1
        assert ov["health"]["level"] in ("excellent", "good", "fair", "poor")
    with database.session() as db:
        pts = stats.online_trend(db, "hour", *timeutil.range_bounds("today"))
        assert sum(p["n"] for p in pts) >= 1


def test_add_missing_columns_on_old_table(tmp_path):
    """旧版本的 hosts 表没有 online_since 列，启动时自动补上"""
    url = f"sqlite:///{tmp_path}/old.db"
    eng = create_engine(url)
    with eng.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE hosts (key VARCHAR(64) PRIMARY KEY, mac VARCHAR(17), ip VARCHAR(45), "
                             "ipv6 TEXT, hostname VARCHAR(128), alias VARCHAR(128), first_seen BIGINT, last_seen BIGINT)")
        conn.exec_driver_sql("INSERT INTO hosts (key, ip) VALUES ('IP:1.2.3.4', '1.2.3.4')")
    eng.dispose()
    saved = (database.engine, database.SessionLocal)
    try:
        database.init_engine(url)
        database.init_db(retries=1)
        with database.engine.connect() as conn:
            assert conn.execute(text("SELECT online_since FROM hosts")).fetchall() == [(None,)]
    finally:
        database.engine.dispose()
        database.engine, database.SessionLocal = saved
