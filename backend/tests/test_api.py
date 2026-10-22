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
        assert ov["groups"][0]["children"][0]["id"] == "web"
        tg = ov["trend_groups"]
        assert len(tg["ts"]) == len(ov["trend"]) and all(len(x["values"]) == len(tg["ts"]) for x in tg["series"])

        hosts = c.get("/api/hosts", headers=h).json()
        assert any(x["key"] == "AA:00:00:00:00:50" for x in hosts)
        assert c.patch("/api/hosts/AA:00:00:00:00:50", json={"alias": "书房电脑"}, headers=h).json()["ok"]
        d = c.get("/api/hosts/AA:00:00:00:00:50/detail?range=month", headers=h).json()
        assert d["name"] == "书房电脑" and d["alias_by"] == "mac" and d["apps"][0]["id"] == "https"
        assert d["groups"][0]["id"] == "base" and d["trend_groups"]["series"][0]["id"] == "base"
        # 改成按 IP 命名：MAC 下的旧名字被删掉
        r = c.patch("/api/hosts/AA:00:00:00:00:50", json={"alias": "固定IP", "by": "ip"}, headers=h).json()
        assert r["name"] == "固定IP" and r["alias_by"] == "ip"
        names = c.get("/api/names", headers=h).json()
        assert [(n["kind"], n["value"]) for n in names] == [("ip", "192.168.88.50")]
        assert names[0]["host"]["key"] == "AA:00:00:00:00:50"
        # 命名表：MAC 优先于 IP；格式自动规范化；可以给没出现过的设备提前命名
        c.put("/api/names", json={"kind": "mac", "value": "aa-00-00-00-00-50", "name": "按MAC"}, headers=h)
        c.put("/api/names", json={"kind": "mac", "value": "aabb.ccdd.eeff", "name": "未来设备"}, headers=h)
        assert c.put("/api/names", json={"kind": "ip", "value": "300.1.1.1", "name": "x"}, headers=h).status_code == 400
        assert c.get("/api/hosts/AA:00:00:00:00:50/detail", headers=h).json()["name"] == "按MAC"
        names = c.delete("/api/names/mac/AA:00:00:00:00:50", headers=h).json()
        assert {n["value"] for n in names} == {"192.168.88.50", "AA:BB:CC:DD:EE:FF"}
        assert next(x for x in c.get("/api/hosts", headers=h).json() if x["key"] == "AA:00:00:00:00:50")["name"] == "固定IP"
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
        meta = c.get("/api/meta", headers=h).json()
        assert len(meta["apps"]) > 250 and {g["id"] for g in meta["groups"]} >= {"media", "game", "unknown"}


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
    ca = sum(l["value"] for l in g["links"] if l["source"].startswith("g:"))
    assert hc == ca == g["total"]
