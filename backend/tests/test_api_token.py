"""0.6.25：只读 API 令牌（给 Home Assistant 用）与 /api/ha/summary。"""
import time

from fastapi.testclient import TestClient

from app.engine import engine
from app.main import app


def _admin(c):
    if not c.get("/api/auth/status").json()["initialized"]:
        c.post("/api/auth/setup", json={"username": "admin", "password": "secret1"})
    tok = c.post("/api/auth/login", json={"username": "admin", "password": "secret1"}).json()["token"]
    return {"Authorization": "Bearer " + tok}


def test_api_token_read_only_and_revoke():
    with TestClient(app) as c:
        h = _admin(c)
        r = c.post("/api/auth/tokens", json={"name": "Home Assistant"}, headers=h).json()
        raw, tid = r["token"], r["id"]
        assert raw.startswith("rdp_") and r["prefix"] == raw[:10]
        # 列表里不再有原文
        lst = c.get("/api/auth/tokens", headers=h).json()
        assert any(t["id"] == tid for t in lst) and all("token" not in t for t in lst)

        t = {"Authorization": "Bearer " + raw}
        assert c.get("/api/overview", headers=t).status_code == 200
        me = c.get("/api/auth/me", headers=t).json()
        assert me == {"username": "api:Home Assistant", "role": "user"}
        # 只读：写操作、管理员页面、管理令牌都不行
        assert c.post("/api/auth/password", json={"old_password": "x", "new_password": "yyyyyy"}, headers=t).status_code == 403
        assert c.get("/api/settings", headers=t).status_code == 403
        assert c.get("/api/auth/tokens", headers=t).status_code == 403
        assert c.put("/api/settings", json={}, headers=t).status_code == 403
        assert c.get("/api/overview", headers={"Authorization": "Bearer rdp_wrong"}).status_code == 401
        # 删除后立即失效（不等 30 秒缓存）
        assert c.delete(f"/api/auth/tokens/{tid}", headers=h).json()["ok"]
        assert c.get("/api/overview", headers=t).status_code == 401
        acts = [o["action"] for o in c.get("/api/audit/oplog", headers=h).json()["rows"]]
        assert "api_token_add" in acts and "api_token_delete" in acts


def test_ha_summary():
    with TestClient(app) as c:
        h = _admin(c)
        now = time.time()
        with engine.lock:
            engine.add_flow(dict(src="192.168.88.91", dst="203.0.113.91", sport=5001, dport=443, proto=6, bytes=4000,
                                 src_mac="AA:00:00:00:91:01"), now)
        engine.flush(now)
        raw = c.post("/api/auth/tokens", json={"name": "ha"}, headers=h).json()["token"]
        s = c.get("/api/ha/summary?limit=5", headers={"Authorization": "Bearer " + raw}).json()
        for k in ("version", "rate", "totals", "online", "identified", "health", "groups", "top_apps", "hosts"):
            assert k in s
        assert len(s["hosts"]) <= 5 and set(s["totals"]) == {"today", "week", "month"}
        hs = s["hosts"][0]
        for k in ("key", "name", "ip", "mac", "type", "online", "rate", "today", "week", "month", "apps"):
            assert k in hs
        assert len(hs["today"]) == 2 and isinstance(hs["apps"], list)
        assert c.get("/api/ha/summary?limit=0", headers=h).status_code == 422
