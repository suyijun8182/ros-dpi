"""合规：日志外发（Syslog，RFC 5424）、留存天数（网页设置优先于环境变量）、数据库占用。"""
import json
import socket
import threading
import time
from datetime import datetime, timezone

from sqlalchemy import inspect, text

from app import database
from app.config import get_settings
from app.models import Setting

RETENTION_KEYS = ("minute", "hour", "day", "domain", "log", "event")
SYSLOG_DEFAULT = {"enabled": False, "host": "", "port": 514, "proto": "udp", "facility": 16, "access": True, "events": True}
_cfg = {"t": 0, "syslog": dict(SYSLOG_DEFAULT), "retention": {}}
_lock = threading.Lock()


def _load(force=False):
    if not force and time.time() - _cfg["t"] < 30:
        return _cfg
    if not database.is_configured():
        return _cfg
    with database.session() as db:
        for key in ("syslog", "retention"):
            row = db.get(Setting, key)
            try:
                val = json.loads(row.value) if row and row.value else {}
            except ValueError:
                val = {}
            _cfg[key] = {**SYSLOG_DEFAULT, **val} if key == "syslog" else val
    _cfg["t"] = time.time()
    return _cfg


def forget():
    _cfg["t"] = 0


def retention() -> dict[str, int]:
    """各类数据的保留天数：网页里设置过的优先，否则用环境变量 RETENTION_*_DAYS"""
    s = get_settings()
    env = {"minute": s.retention_minute_days, "hour": s.retention_hour_days, "day": s.retention_day_days,
           "domain": s.retention_domain_days, "log": s.retention_log_days, "event": s.retention_event_days}
    ov = _load()["retention"]
    return {k: int(ov.get(k) or env[k]) for k in RETENTION_KEYS}


def syslog_config() -> dict:
    return dict(_load()["syslog"])


# ---------------- Syslog ----------------
_sock = {"udp": None}


def _send(lines: list[str], cfg: dict):
    if not lines:
        return
    addr = (cfg["host"], int(cfg["port"]))
    if cfg.get("proto") == "tcp":
        def run():
            try:
                with socket.create_connection(addr, timeout=5) as s:
                    # RFC 6587 octet-counting
                    s.sendall(b"".join(f"{len(x.encode())} ".encode() + x.encode() for x in lines))
            except OSError:
                pass
        threading.Thread(target=run, daemon=True).start()
        return
    with _lock:
        if _sock["udp"] is None:
            _sock["udp"] = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        for x in lines:
            try:
                _sock["udp"].sendto(x.encode()[:8000], addr)
            except OSError:
                break


def _fmt(cfg: dict, msgid: str, fields: dict, severity: int = 6) -> str:
    pri = int(cfg.get("facility", 16)) * 8 + severity
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    msg = " ".join(f'{k}="{str(v).replace(chr(34), chr(39))}"' if isinstance(v, str) and (" " in v or not v) else f"{k}={v}"
                   for k, v in fields.items() if v is not None)
    return f"<{pri}>1 {ts} {socket.gethostname()[:48]} ros-dpi - {msgid} - {msg}"


def send_visits(rows: list[dict], names: dict | None = None):
    """访问日志：一次访问结束（或满一小时封口）时外发一条"""
    cfg = syslog_config()
    if not (cfg.get("enabled") and cfg.get("host") and cfg.get("access")) or not rows:
        return
    from app import people
    out = []
    for r in rows:
        p = people.person_of(r["host"])
        out.append(_fmt(cfg, "ACCESS", {
            "start": datetime.fromtimestamp(r["ts_start"], timezone.utc).isoformat(timespec="seconds"),
            "end": datetime.fromtimestamp(r["ts_end"], timezone.utc).isoformat(timespec="seconds"),
            "device": r["host"], "ip": r["host_ip"], "user": p["name"] if p else None,
            "dest": r["dest"], "remote": r["remote"], "port": r["port"], "proto": r["proto"], "app": r["app"],
            "conns": r["conns"], "up": r["up"], "down": r["down"]}))
    _send(out, cfg)


def send_event(rule: str, host: str, detail: dict):
    cfg = syslog_config()
    if not (cfg.get("enabled") and cfg.get("host") and cfg.get("events")):
        return
    from app import people
    p = people.person_of(host)
    _send([_fmt(cfg, "AUDIT", {"rule": rule, "device": host, "user": p["name"] if p else None,
                               "bytes": detail.get("total") or detail.get("bytes", 0),
                               "items": ",".join(str(k) for k, _v in detail.get("items", [])[:5])}, severity=4)], cfg)


def test_syslog(cfg: dict) -> None:
    _send([_fmt({**SYSLOG_DEFAULT, **cfg}, "TEST", {"msg": "ROS-DPI syslog test"})], {**SYSLOG_DEFAULT, **cfg})


# ---------------- 数据库占用 ----------------

def db_usage() -> dict:
    """各表的行数估计和占用空间（MySQL 读 information_schema；SQLite 只给整个文件大小）"""
    if not database.is_configured():
        return {"tables": [], "total": 0}
    eng = database.engine
    out = []
    with eng.connect() as c:
        if eng.dialect.name == "mysql":
            for name, rows, data, idx in c.execute(text(
                    "SELECT table_name, table_rows, data_length, index_length FROM information_schema.tables "
                    "WHERE table_schema = DATABASE()")):
                out.append({"table": name, "rows": int(rows or 0), "bytes": int(data or 0) + int(idx or 0)})
        else:
            for name in inspect(eng).get_table_names():
                n = c.execute(text(f'SELECT COUNT(*) FROM "{name}"')).scalar() or 0
                out.append({"table": name, "rows": int(n), "bytes": None})
            pc = c.execute(text("PRAGMA page_count")).scalar() or 0
            ps = c.execute(text("PRAGMA page_size")).scalar() or 0
            return {"tables": sorted(out, key=lambda x: -x["rows"]), "total": int(pc) * int(ps), "dialect": "sqlite"}
    return {"tables": sorted(out, key=lambda x: -(x["bytes"] or 0)), "total": sum(x["bytes"] or 0 for x in out),
            "dialect": eng.dialect.name}
