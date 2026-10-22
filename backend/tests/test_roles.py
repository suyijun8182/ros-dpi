from fastapi.testclient import TestClient

from app import security
from app.main import app


def _login(c, user, pw):
    r = c.post("/api/auth/login", json={"username": user, "password": pw})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}, r.json()["role"]


def test_admin_and_readonly_user():
    """debug9：系统有管理员和普通用户；普通用户只读，用户管理只有管理员能做"""
    with TestClient(app) as c:
        if not c.get("/api/auth/status").json()["initialized"]:
            c.post("/api/auth/setup", json={"username": "admin", "password": "secret1"})
        ha, role = _login(c, "admin", "secret1")
        assert role == "admin" and c.get("/api/auth/me", headers=ha).json()["role"] == "admin"

        r = c.post("/api/auth/users", json={"username": "viewer", "password": "viewer1", "role": "user"}, headers=ha)
        assert r.status_code == 200 and r.json()["role"] == "user"
        uid = r.json()["id"]
        assert c.post("/api/auth/users", json={"username": "viewer", "password": "viewer1"}, headers=ha).status_code == 400

        hu, role = _login(c, "viewer", "viewer1")
        assert role == "user"
        # 看监控数据可以
        assert c.get("/api/overview?range=today", headers=hu).status_code == 200
        assert c.get("/api/audit/logs?range=today", headers=hu).status_code == 200
        # 改东西、看敏感配置不行
        assert c.put("/api/settings", json={"lan_cidrs": "10.0.0.0/8"}, headers=hu).status_code == 403
        assert c.post("/api/rules", json={"kind": "domain", "pattern": "x.com", "app_id": "x"}, headers=hu).status_code == 403
        assert c.post("/api/audit/rules", json={"name": "x", "kind": "new_host"}, headers=hu).status_code == 403
        for path in ("/api/settings", "/api/audit/oplog", "/api/audit/notify", "/api/auth/users"):
            assert c.get(path, headers=hu).status_code == 403, path
        # 自己的密码可以改
        assert c.post("/api/auth/password", json={"old_password": "viewer1", "new_password": "viewer2"}, headers=hu).status_code == 200

        # 至少保留一个管理员；不能删自己
        me = next(u for u in c.get("/api/auth/users", headers=ha).json() if u["username"] == "admin")
        assert c.put(f"/api/auth/users/{me['id']}", json={"role": "user"}, headers=ha).status_code == 400
        assert c.delete(f"/api/auth/users/{me['id']}", headers=ha).status_code == 400

        # 升为管理员后立即生效；管理员重置密码
        assert c.put(f"/api/auth/users/{uid}", json={"role": "admin", "password": "viewer3"}, headers=ha).status_code == 200
        hu, role = _login(c, "viewer", "viewer3")
        assert role == "admin" and c.get("/api/settings", headers=hu).status_code == 200

        # 删除后旧 token 立即失效
        assert c.delete(f"/api/auth/users/{uid}", headers=ha).status_code == 200
        assert c.get("/api/overview?range=today", headers=hu).status_code == 401
        acts = [o["action"] for o in c.get("/api/audit/oplog", headers=ha).json()["rows"]]
        assert {"user_add", "user_edit", "user_delete"} <= set(acts)
    security.forget_roles()
