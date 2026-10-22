import json
import time
from datetime import datetime
from types import SimpleNamespace

import httpx
from fastapi.testclient import TestClient

from app import audit, database, timeutil
from app.engine import engine
from app.main import app
from app.models import AccessLog, AuditEvent


def _h(c):
    if not c.get("/api/auth/status").json()["initialized"]:
        c.post("/api/auth/setup", json={"username": "admin", "password": "secret1"})
    return {"Authorization": "Bearer " + c.post("/api/auth/login", json={"username": "admin", "password": "secret1"}).json()["token"]}


def flow(src_ip, dst, sport, nbytes, mac, now, down=False):
    with engine.lock:
        if down:
            return engine.add_flow(dict(src=dst, dst=src_ip, sport=443, dport=sport, proto=6, bytes=nbytes), now)
        return engine.add_flow(dict(src=src_ip, dst=dst, sport=sport, dport=443, proto=6, bytes=nbytes, src_mac=mac), now)


def test_visits_merge_and_access_log():
    t0 = time.time() - 2000
    mac = "AA:00:00:00:0A:01"
    engine.dns.add("www.bilibili.com", [("203.0.113.71", 600)], [])
    flow("192.168.88.71", "203.0.113.71", 5001, 100, mac, t0)
    flow("192.168.88.71", "203.0.113.71", 5001, 9000, mac, t0 + 30, down=True)
    engine.flush(t0 + 60)  # 进行中的访问也先写一行
    with database.session() as db:
        live = db.query(AccessLog).filter(AccessLog.host == mac).all()
    assert len(live) == 1 and (live[0].up, live[0].down) == (100, 9000)
    flow("192.168.88.71", "203.0.113.71", 5002, 50, mac, t0 + 200)  # 5 分钟内的新连接：合并成同一次访问
    engine.flush(t0 + 260)  # 有变化：按行 ID 更新同一行
    engine.flush(t0 + 1000)  # 已经 5 分钟没有新流量：访问结束，移出内存（没有新变化，不再写）
    with database.session() as db:
        rows = db.query(AccessLog).filter(AccessLog.host == mac).all()
    assert len(rows) == 1 and rows[0].id == live[0].id
    r = rows[0]
    assert (r.dest, r.app, r.conns, r.up, r.down) == ("www.bilibili.com", "bilibili", 2, 150, 9000)
    assert r.ts_end - r.ts_start == 200
    with TestClient(app) as c:
        h = _h(c)
        res = c.get(f"/api/audit/logs?start={int(t0) - 10}&end={int(t0) + 3000}&host={mac}", headers=h).json()
        assert res["total"] == 1 and res["rows"][0]["app"]["id"] == "bilibili"
        day = datetime.fromtimestamp(t0, timeutil.tz()).strftime("%Y-%m-%d")
        tl = c.get(f"/api/audit/timeline?host={mac}&day={day}", headers=h).json()
        assert tl["apps"][0]["app"]["id"] == "bilibili" and tl["online"] and tl["apps"][0]["dests"] == ["www.bilibili.com"]
        csv = c.get(f"/api/audit/logs.csv?start={int(t0) - 10}&end={int(t0) + 3000}&host={mac}", headers=h)
        assert csv.status_code == 200 and "www.bilibili.com" in csv.text and csv.text.startswith("﻿")


def test_rule_window_across_midnight():
    r = SimpleNamespace(days="1234567", time_from="22:00", time_to="06:00")
    z = timeutil.tz()
    assert audit.in_window(r, datetime(2026, 10, 21, 23, 0, tzinfo=z).timestamp())
    assert audit.in_window(r, datetime(2026, 10, 22, 5, 0, tzinfo=z).timestamp())
    assert not audit.in_window(r, datetime(2026, 10, 22, 12, 0, tzinfo=z).timestamp())
    # 只在周三晚上生效：周四凌晨 2 点算周三晚上
    r.days = "3"
    assert audit.in_window(r, datetime(2026, 10, 22, 2, 0, tzinfo=z).timestamp())       # 2026-10-22 是周四
    assert not audit.in_window(r, datetime(2026, 10, 22, 23, 0, tzinfo=z).timestamp())


def test_rules_events_notify_and_oplog(monkeypatch):
    sent = []

    class FakeClient:
        """只替换通知用的 httpx.Client（TestClient 本身也是 httpx.Client 的子类，不能动它）"""
        def __init__(self, *a, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, json=None, **kw):
            sent.append((url, json))
            return httpx.Response(200, json={"errcode": 0}, request=httpx.Request("POST", url))
    monkeypatch.setattr(audit.httpx, "Client", FakeClient)

    with TestClient(app) as c:
        h = _h(c)
        assert c.post("/api/audit/rules", json={"name": "x", "kind": "group", "value": "nope"}, headers=h).status_code == 400
        assert c.post("/api/audit/rules", json={"name": "x", "kind": "traffic"}, headers=h).status_code == 400
        c.post("/api/audit/rules", json={"name": "玩游戏", "kind": "group", "value": "game"}, headers=h)
        c.post("/api/audit/rules", json={"name": "大流量", "kind": "traffic", "min_bytes": 5000}, headers=h)
        c.post("/api/audit/rules", json={"name": "访问 B 站", "kind": "domain", "value": "bilibili.com", "notify": False}, headers=h)
        c.post("/api/audit/rules", json={"name": "新设备", "kind": "new_host"}, headers=h)
        r = c.put("/api/audit/notify", json={"channels": [{"type": "wecom", "name": "家庭群", "url": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=SECRET-KEY-123456789"}]}, headers=h).json()
        assert r["channels"][0]["url"].endswith("…") and "SECRET-KEY-123456789" not in json.dumps(r)
        # 保存时 url 以 … 结尾表示不修改
        c.put("/api/audit/notify", json={"channels": r["channels"]}, headers=h)
        assert audit.Notifier.channels()[0]["url"].endswith("123456789")

        audit.auditor.reload()
        now = time.time()
        mac = "AA:00:00:00:0A:02"
        engine.dns.add("store.steampowered.com", [("203.0.113.72", 600)], [])
        engine.dns.add("www.bilibili.com", [("203.0.113.73", 600)], [])
        flow("192.168.88.72", "203.0.113.72", 6001, 3000, mac, now)
        flow("192.168.88.72", "203.0.113.73", 6002, 3000, mac, now)
        engine.flush(now)
        ev = c.get("/api/audit/events?range=today", headers=h).json()
        names = {e["rule"] for e in ev["rows"] if e["host"] == mac}
        assert names == {"玩游戏", "大流量", "访问 B 站", "新设备"}
        # 冷却：同一分钟再来一次不重复记
        flow("192.168.88.72", "203.0.113.72", 6003, 3000, mac, now + 1)
        engine.flush(now + 1)
        assert c.get("/api/audit/events?range=today", headers=h).json()["total"] == ev["total"]
        # 推送在后台线程里发，发成功后才标成已推送；不推送的规则保持未推送
        for _ in range(40):
            rows = [e for e in c.get("/api/audit/events?range=today", headers=h).json()["rows"] if e["host"] == mac]
            if any(e["notified"] for e in rows):
                break
            time.sleep(0.05)
        st = {e["rule"]: e["notified"] for e in rows}
        assert st["玩游戏"] and st["新设备"] and not st["访问 B 站"]
        texts = [j["text"]["content"] for _u, j in sent]
        assert any("玩游戏" in t and "Steam" in t for t in texts) and not any("访问 B 站" in t for t in texts)

        rep = c.get("/api/audit/report?range=today", headers=h).json()
        assert rep["events_total"] >= 4 and "ROS-DPI" in rep["title"] and "总流量" in rep["text"]
        assert c.post("/api/audit/report/push?range=today", headers=h).json()["results"][0]["ok"]

        c.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
        ops = c.get("/api/audit/oplog", headers=h).json()["rows"]
        acts = [o["action"] for o in ops]
        assert "audit_rule_add" in acts and "notify_channels" in acts
        assert any(o["action"] == "login" and not o["ok"] for o in ops)
        assert all("SECRET-KEY" not in (o["detail"] or "") for o in ops)
        s = c.get("/api/audit/summary", headers=h).json()
        assert s["rules"] >= 4 and s["channels"] == 1
