import socket
import time
from collections import Counter

from fastapi.testclient import TestClient

from app import audit, devtype, insight, people, sharing
from app.engine import engine
from app.main import app
from tests.test_audit import _h, flow


def test_people_usage_scenarios_and_scope(monkeypatch):
    """debug10：人员 / 部门、设备归属、按人统计和筛选、场景不同标签不同、审计规则按人生效"""
    now = time.time()
    mac1, mac2 = "AA:00:00:00:0B:01", "AA:00:00:00:0B:02"
    engine.dns.add("store.steampowered.com", [("203.0.113.81", 600)], [])
    engine.dns.add("www.zhipin.com", [("203.0.113.82", 600)], [])
    with TestClient(app) as c:
        h = _h(c)
        d = c.post("/api/departments", json={"name": "孩子"}, headers=h).json()
        assert c.post("/api/departments", json={"name": "孩子"}, headers=h).status_code == 400
        p = c.post("/api/people", json={"name": "小明", "dept_id": d["id"], "hosts": [mac1]}, headers=h).json()
        # debug11：成员必须属于分组；同一分组不重名；分组下有成员时不能删
        assert c.post("/api/people", json={"name": "唐女士"}, headers=h).status_code == 422
        assert c.post("/api/people", json={"name": "唐女士", "dept_id": 99999}, headers=h).status_code == 400
        assert c.post("/api/people", json={"name": " 小明 ", "dept_id": d["id"]}, headers=h).status_code == 400
        assert c.delete(f"/api/departments/{d['id']}", headers=h).status_code == 400
        assert p["dept"] == "孩子"
        assert c.put("/api/devices/bind", json={"host": mac2, "person_id": p["id"]}, headers=h).json()["person"]["name"] == "小明"
        assert people.hosts_of_person(p["id"]) == [mac1, mac2]
        assert people.expand_scope([f"dept:{d['id']}"]) == {mac1, mac2}

        # 两台设备各玩一会儿游戏；审计规则只对“小明”生效
        c.post("/api/audit/rules", json={"name": "小明玩游戏", "kind": "group", "value": "game", "hosts": [f"person:{p['id']}"]}, headers=h)
        audit.auditor.reload()
        flow("192.168.88.81", "203.0.113.81", 7001, 5000, mac1, now - 120)
        flow("192.168.88.82", "203.0.113.81", 7002, 5000, mac2, now - 60)
        flow("192.168.88.83", "203.0.113.81", 7003, 5000, "AA:00:00:00:0B:03", now - 60)  # 别人
        engine.flush(now)
        ev = c.get("/api/audit/events?range=today", headers=h).json()["rows"]
        hit = {e["host"] for e in ev if e["rule"] == "小明玩游戏"}
        assert hit == {mac1, mac2}

        # 访问日志、时间线按人
        logs = c.get(f"/api/audit/logs?range=today&person={p['id']}", headers=h).json()
        assert logs["total"] == 2 and {r["host"] for r in logs["rows"]} == {mac1, mac2}
        tl = c.get(f"/api/audit/timeline?person={p['id']}", headers=h).json()
        assert tl["apps"][0]["app"]["id"] == "steam" and tl["host"] is None

        lst = c.get("/api/people?range=today", headers=h).json()
        me = next(x for x in lst["people"] if x["id"] == p["id"])
        assert me["total"] == 10000 and len(me["devices"]) == 2 and me["devices"][0]["person"]["name"] == "小明"
        assert all(x["key"] not in (mac1, mac2) for x in lst["unassigned"])
        det = c.get(f"/api/people/{p['id']}/detail?range=today", headers=h).json()
        assert det["range_total"]["total"] == 10000 and det["usage"]["online"] > 0 and det["apps"][0]["id"] == "steam"

        # 场景：家用 / 企业，只换场景时其余用该场景的默认值
        r = c.put("/api/analysis/settings", json={"scenario": "enterprise"}, headers=h).json()["config"]
        assert r["work"] == [["09:00", "12:00"], ["13:30", "18:00"]] and r["limits"]["screen"] == 0
        r = c.put("/api/analysis/settings", json={"scenario": "home"}, headers=h).json()["config"]
        assert r["night"] == ["22:00", "06:00"] and r["limits"]["game"] == 3600
        assert c.put("/api/analysis/settings", json={"work": [["18:00", "09:00"]]}, headers=h).status_code == 400

        # 报表里有人员排行
        rep = c.get("/api/audit/report?range=today", headers=h).json()
        assert rep["top_people"][0]["name"] == "小明" and "Top 人员" in rep["text"]

        # 管控命令：按人生成，带撤销
        sc = c.post("/api/control/script", json={"target": "person", "target_id": str(p["id"]), "action": "block_app",
                                                  "groups": ["game"], "days": "12345", "time_from": "19:00", "time_to": "21:00"},
                    headers=h).json()
        assert f"src-mac-address={mac1}" in sc["script"] and "tls-host=*steampowered.com" in sc["script"]
        assert "time=19h00m-21h00m,mon,tue,wed,thu,fri" in sc["script"] and sc["undo"].startswith("/ip firewall filter remove")
        sc = c.post("/api/control/script", json={"target": "person", "target_id": str(p["id"]), "action": "block_all",
                                                  "time_from": "22:00", "time_to": "06:00"}, headers=h).json()
        assert "time=22h00m-1d" in sc["script"] and "time=0s-6h00m" in sc["script"]  # 跨午夜拆成两段

        # 删除人员：设备解除归属
        assert c.delete(f"/api/people/{p['id']}", headers=h).status_code == 200
        assert people.hosts_of_person(p["id"]) == []


def test_insight_home_tags():
    now = int(time.time())
    start = now - 7 * 86400
    cfg = insight.check_config({"scenario": "home"})
    day = 86400
    # 连续 3 天每天玩 2 小时游戏（上限 1 小时）
    rows = [("h", "steam", now - k * day - 3 * 3600, now - k * day - 3600, "x") for k in range(1, 4)]
    r = insight.analyze(rows, start, now, cfg)
    tags = {t["id"]: t for t in r["tags"]}
    assert tags["game_over"]["value"] == 3 and tags["game_over"]["level"] == "mid" and tags["game_over"]["limit"] == 3600
    ent = insight.analyze(rows, start, now, insight.check_config({"scenario": "enterprise"}))
    assert "game_over" not in {t["id"] for t in ent["tags"]}


def test_devtype_classify():
    assert devtype.classify("AA:BB:CC:00:00:01", "iPhone-of-Xiaoming")[0] == "phone"
    assert devtype.classify("AA:BB:CC:00:00:02", "DESKTOP-8F3K2L")[0] == "computer"
    assert devtype.classify("AA:BB:CC:00:00:03", "MiTV-AXFR0")[0] == "tv"
    assert devtype.classify("00:11:22:33:44:55", None, vendor_full="Hangzhou Hikvision Digital Technology Co.,Ltd.") == \
        ("camera", "Hikvision", "vendor")
    assert devtype.classify("00:11:22:33:44:56", None, {"ezviz", "dns"}, vendor_full="")[0] == "camera"
    assert devtype.classify("00:11:22:33:44:57", None, {"windows_update", "wechat"}, vendor_full="")[0] == "computer"
    assert devtype.classify("DA:11:22:33:44:58", None, vendor_full="")[0:3:2] == ("phone", "random")
    assert devtype.short_vendor("Shenzhen Foo Electronics Co.,Ltd.") == "Shenzhen Foo"


def test_sharing_suspects():
    ttl = {"a": Counter({63: 40}), "b": Counter({127: 30}), "c": Counter({63: 20}),
           "nat": Counter({62: 30, 126: 10}), "mix": Counter({63: 20, 127: 15})}
    base, rows = sharing.suspects(ttl)
    by = {r["host"]: r for r in rows}
    assert base == 1 and set(by) == {"nat", "mix"}
    assert "extra_hop" in by["nat"]["reasons"] and "multi_os" in by["nat"]["reasons"]
    assert by["mix"]["reasons"] == ["multi_os"]


def test_upload_rule_syslog_and_retention(monkeypatch):
    now = time.time()
    mac = "AA:00:00:00:0C:01"
    recv = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    recv.bind(("127.0.0.1", 0))
    recv.settimeout(3)
    port = recv.getsockname()[1]
    engine.dns.add("pan.baidu.com", [("203.0.113.91", 600)], [])
    with TestClient(app) as c:
        h = _h(c)
        r = c.put("/api/compliance", json={"syslog": {"enabled": True, "host": "127.0.0.1", "port": port},
                                           "retention": {"log": 90}}, headers=h).json()
        assert r["syslog"]["enabled"] and r["retention"]["log"] == 90 and r["usage"]["tables"]
        assert c.post("/api/audit/rules", json={"name": "外发", "kind": "upload", "value": "nope", "min_bytes": 10}, headers=h).status_code == 400
        c.post("/api/audit/rules", json={"name": "大流量外发", "kind": "upload", "min_bytes": 4000}, headers=h)
        audit.auditor.reload()
        flow("192.168.88.91", "203.0.113.91", 7101, 5000, mac, now - 1000)          # 上行 5000
        flow("192.168.88.91", "203.0.113.91", 7101, 90000, mac, now - 1000, down=True)  # 下行不算
        engine.flush(now - 900)
        # 事件时间是 now-900：午夜前后 15 分钟内运行时它会落在昨天，用 last7 保证总能查到
        ev = [e for e in c.get("/api/audit/events?range=last7", headers=h).json()["rows"]
              if e["host"] == mac and e["rule"] == "大流量外发"]
        assert len(ev) == 1 and ev[0]["bytes"] == 5000  # 只算上行
        engine.flush(now)  # 5 分钟没有新流量：访问结束，外发一条 Syslog
        got = []
        try:
            while True:
                got.append(recv.recv(9000).decode())
        except socket.timeout:
            pass
        assert any(" ros-dpi - AUDIT - " in x and 'rule=' in x for x in got)
        acc = [x for x in got if " ACCESS " in x and f"device={mac}" in x]
        assert acc and "dest=pan.baidu.com" in acc[0] and "up=5000" in acc[0]
        assert c.put("/api/compliance", json={"syslog": {"enabled": False}}, headers=h).status_code == 200
        assert c.get("/api/sharing", headers=h).status_code == 200
    recv.close()


def test_oui_db_load(tmp_path, monkeypatch):
    """MAC 厂商库：从 DATA_DIR 读 IEEE 的 oui.csv（之前读错配置项，启动时报错）"""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    (tmp_path / "oui.csv").write_text("Registry,Assignment,Organization Name,Organization Address\n"
                                      "MA-L,28EE52,TP-LINK TECHNOLOGIES CO.,LTD.,Shenzhen\n"
                                      'MA-L,BC6AD1,"Xiaomi Communications Co Ltd",Beijing\n', encoding="utf-8")
    db = devtype.OuiDb()
    assert db.path() == str(tmp_path / "oui.csv") and db.load()
    assert db.lookup("28:EE:52:11:22:33") == "TP-LINK TECHNOLOGIES CO." and db.lookup("BC-6A-D1-00-00-01").startswith("Xiaomi")
    assert db.lookup("2A:EE:52:11:22:33") == ""  # 随机 MAC 不查
    assert devtype.classify("BC:6A:D1:00:00:01", None, vendor_full=db.lookup("BC:6A:D1:00:00:01"))[:2] == ("phone", "Xiaomi")


def test_domain_country_survives_dns_expiry(tmp_path):
    """debug11：域名的国家在记录流量时存下（DomainGeo），DNS 缓存过期或重启后仍能定位"""
    import gzip
    from app.asn import asndb
    p = tmp_path / "ip2asn.tsv.gz"
    with gzip.open(p, "wt") as f:
        f.write("45.57.0.0\t45.57.127.255\t64500\tJP\tTEST-JP\n")
    saved = (asndb._v4, asndb._v6, asndb.names, asndb.rows)
    try:
        asndb.load(str(p))
        asndb._cache = {}
        now = time.time()
        engine.dns.add("cdn.geo-test.example", [("45.57.10.120", 600)], [])
        flow("192.168.88.120", "45.57.10.120", 7301, 4000, "AA:00:00:00:0E:01", now)
        engine.flush(now)
        engine.dns._d.pop("45.57.10.120", None)  # 模拟 DNS 缓存过期 / 重启
        with TestClient(app) as c:
            h = _h(c)
            r = c.get("/api/destinations?range=today&q=geo-test", headers=h).json()
            row = next(x for x in r["rows"] if x["dest"] == "cdn.geo-test.example")
            assert row["country"] == "JP" and any(x["cc"] == "JP" for x in r["countries"]) and r["home"]
    finally:
        asndb._v4, asndb._v6, asndb.names, asndb.rows = saved
        asndb._cache = {}
