"""0.6.29：识别校验（已知答案核对命中率）、抓包采样（pcap + 识别结果，给 nDPI 离线对照）、nDPI 对照脚本。"""
import csv
import importlib.util
import os
import struct
import time

from fastapi.testclient import TestClient

from app import accuracy, capture as capmod, database, timeutil
from app.capture import capture
from app.engine import engine
from app.main import app
from app.models import AccuracyProbe, Host, TrafficMinute
from packets import tcp_segment, tzsp

H = "AA:00:00:00:29:01"


def _admin(c):
    if not c.get("/api/auth/status").json()["initialized"]:
        c.post("/api/auth/setup", json={"username": "admin", "password": "secret1"})
    tok = c.post("/api/auth/login", json={"username": "admin", "password": "secret1"}).json()["token"]
    return {"Authorization": "Bearer " + tok}


def _viewer(c, ha):
    c.post("/api/auth/users", json={"username": "viewer29", "password": "viewer1", "role": "user"}, headers=ha)
    tok = c.post("/api/auth/login", json={"username": "viewer29", "password": "viewer1"}).json()["token"]
    return {"Authorization": "Bearer " + tok}


def _seed_minutes(now):
    m = timeutil.minute_bucket(now)
    with database.session() as db:
        db.query(TrafficMinute).filter(TrafficMinute.host == H).delete(synchronize_session=False)
        db.query(AccuracyProbe).filter(AccuracyProbe.host == H).delete(synchronize_session=False)
        if db.get(Host, ("default", H)) is None:
            db.add(Host(key=H, mac=H, ip="192.168.88.29"))
        rows = [("douyin", 700), ("https", 200), ("wechat", 100)]   # 预期抖音：命中 70%，笼统 20%，认错 10%
        for i in range(3):
            for app_id, b in rows:
                db.add(TrafficMinute(ts=m - i * 60, host=H, app=app_id, up=b // 10, down=b - b // 10, flows=1))
        db.add(TrafficMinute(ts=m - 3600, host=H, app="wechat", up=0, down=10_000, flows=1))   # 窗口外，不算
        db.commit()


def test_measure_kinds():
    now = time.time()
    _seed_minutes(now)
    with database.session() as db:
        r = accuracy.measure(db, engine.classifier, H, "douyin", int(now) - 300, int(now))
    assert r["total"] == 3000
    assert (r["hit"], r["vague"], r["wrong"]) == (2100, 600, 300)
    assert r["apps"][0]["app"] == "douyin" and r["apps"][0]["kind"] == "hit"


def test_probe_api_flow():
    now = time.time()
    _seed_minutes(now)
    with TestClient(app) as c:
        ha = _admin(c)
        # 回看刚过去的 10 分钟：立即结束；结束不到 2 分钟时还不冻结
        r = c.post("/api/accuracy/probes", json={"host": H, "expected": "douyin", "back": 10}, headers=ha)
        assert r.status_code == 200, r.text
        p = r.json()
        assert p["state"] == "settling" and p["hit"] == 2100 and p["expected"]["id"] == "douyin"
        # 开始 / 结束
        r = c.post("/api/accuracy/probes", json={"host": H, "expected": "douyin"}, headers=ha).json()
        assert r["state"] == "running" and r["end"] is None
        assert c.post(f"/api/accuracy/probes/{r['id']}/stop", headers=ha).json()["end"]
        # 列表 + 合计；只读用户能看、不能建
        hu = _viewer(c, ha)
        lst = c.get("/api/accuracy/probes", headers=hu).json()
        assert lst["summary"]["probes"] >= 1 and lst["items"][0]["host"]["key"] == H
        assert c.post("/api/accuracy/probes", json={"host": H, "expected": "douyin"}, headers=hu).status_code == 403
        # 校验：终端、应用必须存在
        assert c.post("/api/accuracy/probes", json={"host": "nope", "expected": "douyin"}, headers=ha).status_code == 400
        assert c.post("/api/accuracy/probes", json={"host": H, "expected": "nope"}, headers=ha).status_code == 400
        assert c.delete(f"/api/accuracy/probes/{p['id']}", headers=ha).json()["ok"]


def test_probe_freezes_result():
    now = time.time()
    _seed_minutes(now)
    with database.session() as db:
        p = AccuracyProbe(host=H, expected="douyin", start=int(now) - 600, end=int(now) - 300)
        db.add(p)
        db.commit()
        v = accuracy.view(db, engine.classifier, p, now)
        assert v["state"] == "done" and p.result
        # 明细被清理以后结果仍在
        db.query(TrafficMinute).filter(TrafficMinute.host == H).delete(synchronize_session=False)
        assert accuracy.view(db, engine.classifier, p, now)["hit"] == v["hit"]


def _read_pcap(path):
    with open(path, "rb") as f:
        data = f.read()
    magic, _maj, _min, _tz, _sig, snap, link = struct.unpack_from("<IHHiIII", data, 0)
    assert magic == 0xA1B2C3D4 and link == 1 and snap == 65535
    off, frames = 24, []
    while off < len(data):
        _s, _us, incl, orig = struct.unpack_from("<IIII", data, off)
        frames.append(data[off + 16: off + 16 + incl])
        off += 16 + incl
    return frames


def test_capture_writes_pcap_and_labels():
    capture.stop()
    with TestClient(app) as c:
        ha = _admin(c)
        st = c.post("/api/diag/capture/start", json={"minutes": 1}, headers=ha).json()
        assert st["active"]
        assert c.post("/api/diag/capture/start", json={"minutes": 1}, headers=ha).status_code == 409
        # 实时连接表里放一条连接，再进两个镜像包
        with engine.lock:
            engine.sessions[(H, "1.2.3.4", 6881, 6, 51413)] = ["192.168.88.29", "https", "", "", 100, 900, 0, 0, 0, 0, 0.0, 0.0, None]
        seg = tcp_segment("192.168.88.29", "1.2.3.4", 51413, 6881, 1, b"\x13BitTorrent protocol" + b"\x00" * 48)
        engine.on_tzsp(tzsp(seg))
        engine.on_tzsp(tzsp(seg))
        name = st["name"]
        last = c.post("/api/diag/capture/stop", headers=ha).json()["last"]
        assert last["name"] == name and last["packets"] == 2 and last["connections"] >= 1
        with engine.lock:
            engine.sessions.pop((H, "1.2.3.4", 6881, 6, 51413), None)
        files = c.get("/api/diag/capture", headers=ha).json()["files"]
        assert any(f["name"] == name for f in files)
        frames = _read_pcap(os.path.join(capmod.capture_dir(), name + ".pcap"))
        assert len(frames) == 2 and frames[0] == seg
        r = c.get(f"/api/diag/capture/{name}/labels.csv", headers=ha)
        assert r.status_code == 200
        rows = list(csv.DictReader(r.text.splitlines()))
        hit = [x for x in rows if x["remote_port"] == "6881"]
        assert hit and hit[0]["app"] == "https" and hit[0]["vague"] == "1" and hit[0]["client_ip"] == "192.168.88.29"
        # 只读用户：看不到、下载不了
        hu = _viewer(c, ha)
        assert c.get("/api/diag/capture", headers=hu).status_code == 403
        assert c.get(f"/api/diag/capture/{name}/pcap", headers=hu).status_code == 403
        # 名字校验防路径穿越
        assert c.get("/api/diag/capture/..%2f..%2ftest/pcap", headers=ha).status_code == 404
        assert capmod.path_of("../x", "pcap") is None and capmod.path_of(name, "py") is None
        assert c.delete(f"/api/diag/capture/{name}", headers=ha).json()["ok"]
        assert capmod.path_of(name, "pcap") is None


def test_capture_limits_and_cleanup(monkeypatch, tmp_path):
    capture.stop()
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setattr(capmod, "MAX_BYTES", 24 + 16 + 10)
    capture.start(engine, 5)
    capture.write(b"x" * 10)
    capture.write(b"y" * 10)          # 超过上限：自动停止
    assert not capture.active and capture.last["packets"] == 1
    old = os.path.join(capmod.capture_dir(), capture.last["name"] + ".pcap")
    os.utime(old, (time.time() - capmod.KEEP_SECONDS - 10,) * 2)
    capmod.cleanup()
    assert not os.path.exists(old)


def _eval_module():
    path = os.path.join(os.path.dirname(__file__), "..", "..", "scripts", "ndpi_eval.py")
    spec = importlib.util.spec_from_file_location("ndpi_eval", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_ndpi_eval_join_and_report(tmp_path):
    ev = _eval_module()
    assert ev.ndpi_specific("TLS.YouTube") and ev.ndpi_specific("BitTorrent")
    assert not ev.ndpi_specific("TLS") and not ev.ndpi_specific("Unknown") and not ev.ndpi_specific("QUIC")
    lab = tmp_path / "x.labels.csv"
    with open(lab, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(capmod.LABEL_FIELDS)
        w.writerow(("192.168.88.29", 51413, "1.2.3.4", 6881, 6, "pcdn_p2p", "", "", 100, 9900, "p2p", 1))
        w.writerow(("192.168.88.29", 50000, "5.6.7.8", 443, 6, "douyin", "douyin.com", "sni", 10, 990, "video", 0))
        w.writerow(("192.168.88.29", 50001, "9.9.9.9", 3478, 17, "cn_net", "", "", 10, 990, "network", 1))
    flows = [
        # 回包方向先看到：要能按反方向对上
        {"src_ip": "1.2.3.4", "src_port": 6881, "dst_ip": "192.168.88.29", "dst_port": 51413, "proto": 6, "bytes": 500,
         "app": "BitTorrent", "category": "Download", "sni": ""},
        {"src_ip": "192.168.88.29", "src_port": 50000, "dst_ip": "5.6.7.8", "dst_port": 443, "proto": 6, "bytes": 500,
         "app": "TLS.TikTok", "category": "SocialNetwork", "sni": "douyin.com"},
        {"src_ip": "192.168.88.29", "src_port": 50001, "dst_ip": "9.9.9.9", "dst_port": 3478, "proto": 17, "bytes": 500,
         "app": "Unknown", "category": "", "sni": ""},
        {"src_ip": "192.168.88.29", "src_port": 1, "dst_ip": "8.8.8.8", "dst_port": 53, "proto": 17, "bytes": 80,
         "app": "DNS", "category": "Network", "sni": ""},
    ]
    rows = ev.join(flows, ev.load_labels(str(lab)), [])
    assert [r["ros_app"] for r in rows] == ["pcdn_p2p", "douyin", "cn_net", None]
    assert rows[0]["client_ip"] == "192.168.88.29" and rows[0]["weight"] == 10_000
    md = ev.report(rows, {"name": "x", "packets": 4, "connections": 3})
    # 笼统流量 11000 里 nDPI 认出了 BitTorrent 的 10000
    assert "其中 nDPI 能说出具体应用的：90.9%" in md
    assert "| BitTorrent | Download |" in md and "| douyin | TLS.TikTok |" in md and "udp/3478" in md
