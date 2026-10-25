"""所有无路径参数的 GET 接口都不能返回 500（0.6.20 的部署量接口调用了已删除的函数，上线后才发现）"""
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app.main import app

SKIP = {"/api/system/update"}   # 会访问 GitHub


def _h(c):
    if not c.get("/api/auth/status").json()["initialized"]:
        c.post("/api/auth/setup", json={"username": "admin", "password": "secret1"})
    return {"Authorization": "Bearer " + c.post("/api/auth/login", json={"username": "admin", "password": "secret1"}).json()["token"]}


def test_get_routes_no_500():
    with TestClient(app) as c:
        h = _h(c)
        bad = []
        for r in app.routes:
            if not isinstance(r, APIRoute) or "GET" not in r.methods or "{" in r.path:
                continue
            if not r.path.startswith("/api/") or r.path in SKIP:
                continue
            resp = c.get(r.path, headers=h)
            if resp.status_code >= 500:
                bad.append((r.path, resp.status_code, resp.text[:120]))
        assert not bad, bad
