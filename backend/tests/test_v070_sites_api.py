"""0.7.0 站点管理接口：增删改、源 IP 校验（D5）、删除清数据、未登记来源"""
import time

from fastapi.testclient import TestClient
from sqlalchemy import select

from app import database
from app.main import app
from app.models import Host, Site, TrafficDay
from app.sites import registry


def _h(c):
    if not c.get("/api/auth/status").json()["initialized"]:
        c.post("/api/auth/setup", json={"username": "admin", "password": "secret1"})
    return {"Authorization": "Bearer " + c.post("/api/auth/login", json={"username": "admin", "password": "secret1"}).json()["token"]}


def test_site_lifecycle():
    with TestClient(app) as c:
        h = _h(c)
        mine = c.get("/api/sites/mine", headers=h).json()
        assert mine["multi"] is False and [s["slug"] for s in mine["sites"]] == ["default"]
        # 第二个站点：两个站点都要有源 IP
        r = c.post("/api/sites", json={"slug": "branch", "name": "分店", "sources": ["10.9.0.2"]}, headers=h)
        assert r.status_code == 400 and "默认站点" in r.json()["detail"]
        assert c.get("/api/sites/mine", headers=h).json()["multi"] is False      # 没保存
        assert c.post("/api/sites", json={"slug": "Bad Slug", "name": "x"}, headers=h).status_code == 400
        assert c.put("/api/sites/default", json={"name": "家里", "sources": ["192.168.88.1"]}, headers=h).status_code == 200
        r = c.post("/api/sites", json={"slug": "branch", "name": "分店", "sources": ["10.9.0.2", "bad"]}, headers=h)
        assert r.status_code == 400
        r = c.post("/api/sites", json={"slug": "branch", "name": "分店", "sources": ["192.168.88.1"]}, headers=h)
        assert r.status_code == 400 and "已经登记" in r.json()["detail"]
        r = c.post("/api/sites", json={"slug": "branch", "name": "分店", "sources": ["10.9.0.2"],
                                       "platform_addr": "10.9.0.1"}, headers=h)
        assert r.status_code == 200, r.text
        assert registry.multi() and registry.resolve("10.9.0.2") is registry.get("branch")
        mine = c.get("/api/sites/mine", headers=h).json()
        assert mine["multi"] and [s["name"] for s in mine["sites"]] == ["家里", "分店"]
        # 分店的 RouterOS 走 /api/settings?site=branch，不用环境变量
        assert c.put("/api/settings?site=branch", json={"lan_cidrs": "10.20.0.0/16"}, headers=h).status_code == 200
        assert registry.get("branch").is_lan("10.20.1.1")
        assert c.get("/api/settings?site=branch", headers=h).json()["ros"]["source"] == "none"
        # 停用分店后只剩一个启用站点，但都登记过源 IP：仍按源 IP 收
        assert c.put("/api/sites/branch", json={"name": "分店", "sources": ["10.9.0.2"], "enabled": False},
                     headers=h).status_code == 200
        assert not registry.multi() and registry.resolve("10.9.0.2") is None
        assert c.put("/api/sites/default", json={"name": "家里", "sources": ["192.168.88.1"], "enabled": False},
                     headers=h).status_code == 400          # 至少一个启用
        # 未登记来源
        registry.on_ipfix(b"\x00\x0a\x00\x10" + b"\x00" * 12, "198.51.100.77")
        u = c.get("/api/sites/unknown-sources", headers=h).json()
        assert any(x["ip"] == "198.51.100.77" for x in u["unknown"])
        # 删除：清掉分店的数据
        with database.session() as db:
            db.add(TrafficDay(site="branch", ts=5, host="H", app="a", up=1, down=1, flows=1))
            db.add(Host(site="branch", key="H", ip="10.20.0.5"))
            db.commit()
        assert c.request("DELETE", "/api/sites/branch", json={"confirm": "x"}, headers=h).status_code == 400
        assert c.request("DELETE", "/api/sites/default", json={"confirm": "default"}, headers=h).status_code == 400
        r = c.request("DELETE", "/api/sites/branch", json={"confirm": "branch"}, headers=h)
        assert r.status_code == 200 and r.json()["rows"]["traffic_day"] == 1 and r.json()["rows"]["hosts"] == 1
        with database.session() as db:
            assert db.scalar(select(TrafficDay).where(TrafficDay.site == "branch")) is None
            assert db.get(Site, "branch") is None
        assert "branch" not in registry.engines
        # 还原
        c.put("/api/sites/default", json={"name": "默认站点", "sources": []}, headers=h)
        assert registry.accept_all == "default"


def test_sites_admin_only():
    with TestClient(app) as c:
        h = _h(c)
        c.post("/api/auth/users", json={"username": "v070ro", "password": "viewer1", "role": "user"}, headers=h)
        hu = {"Authorization": "Bearer " + c.post("/api/auth/login", json={"username": "v070ro", "password": "viewer1"}).json()["token"]}
        assert c.get("/api/sites/mine", headers=hu).status_code == 200
        assert c.get("/api/sites", headers=hu).status_code == 403
        assert c.get("/api/sites/unknown-sources", headers=hu).status_code == 403
        assert c.post("/api/sites", json={"slug": "x", "name": "x"}, headers=hu).status_code == 403
