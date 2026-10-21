import time

from fastapi.testclient import TestClient

from app.engine import engine
from app.main import app


def test_api_flow():
    with TestClient(app) as c:
        assert c.get("/api/overview").status_code == 401
        assert c.get("/api/auth/status").json() == {"initialized": False}
        tok = c.post("/api/auth/setup", json={"username": "admin", "password": "secret1"}).json()["token"]
        assert c.post("/api/auth/setup", json={"password": "secret2"}).status_code == 400
        assert c.post("/api/auth/login", json={"username": "admin", "password": "bad"}).status_code == 401
        h = {"Authorization": f"Bearer {tok}"}

        with engine.lock:
            engine.add_flow(dict(src="192.168.88.50", dst="8.8.4.4", sport=1, dport=443, proto=6, bytes=777,
                                 src_mac="AA:00:00:00:00:50"), time.time())
        engine.flush()

        ov = c.get("/api/overview?range=week", headers=h).json()
        assert ov["totals"]["today"]["total"] >= 777
        assert any(x["key"] == "AA:00:00:00:00:50" for x in ov["top_hosts"])
        assert len(ov["realtime"]) >= 60

        hosts = c.get("/api/hosts", headers=h).json()
        assert any(x["key"] == "AA:00:00:00:00:50" for x in hosts)
        assert c.patch("/api/hosts/AA:00:00:00:00:50", json={"alias": "书房电脑"}, headers=h).json()["ok"]
        d = c.get("/api/hosts/AA:00:00:00:00:50/detail?range=month", headers=h).json()
        assert d["name"] == "书房电脑" and d["apps"][0]["id"] == "https"
        assert c.get("/api/hosts/IP:1.1.1.1/detail", headers=h).status_code == 404

        assert c.get("/api/apps/https/detail", headers=h).json()["hosts"][0]["key"] == "AA:00:00:00:00:50"

        bad = c.post("/api/rules", json={"kind": "domain", "pattern": "x", "app_id": "douyin"}, headers=h)
        assert bad.status_code == 400
        r = c.post("/api/rules", json={"kind": "cidr", "pattern": "8.8.4.0/24", "app_id": "google"}, headers=h)
        assert r.status_code == 200
        assert engine.classifier.classify("8.8.4.4", 6, 443, None, None) == "google"
        assert c.delete(f"/api/rules/{r.json()['id']}", headers=h).json()["ok"]

        s = c.put("/api/settings", json={"lan_cidrs": "192.168.88.0/24\n10.0.0.0/8"}, headers=h).json()
        assert s["lan_cidrs"] == "192.168.88.0/24,10.0.0.0/8"
        assert c.put("/api/settings", json={"lan_cidrs": "nope"}, headers=h).status_code == 400
        assert c.get("/api/system", headers=h).json()["collector"]["flows"] >= 1
        assert len(c.get("/api/meta", headers=h).json()["apps"]) > 50


def test_flow_graph():
    from app import stats, timeutil
    from app import database
    with engine.lock:
        engine.add_flow(dict(src="192.168.88.60", dst="91.108.4.1", sport=1, dport=443, proto=6, bytes=300,
                             src_mac="AA:00:00:00:00:60"), time.time())
    engine.flush()
    with database.session() as db:
        g = stats.flow_graph(db, *timeutil.range_bounds("today"), max_hosts=1, max_apps=1)
    ids = {n["id"] for n in g["nodes"]}
    assert all(l["source"] in ids and l["target"] in ids for l in g["links"])
    assert "h:__other_hosts" in ids or len([n for n in g["nodes"] if n["kind"] == "host"]) == 1
    # 守恒：终端→分类 的总量 == 分类→应用 的总量 == total
    hc = sum(l["value"] for l in g["links"] if l["source"].startswith("h:"))
    ca = sum(l["value"] for l in g["links"] if l["source"].startswith("c:"))
    assert hc == ca == g["total"]
