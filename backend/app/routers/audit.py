"""审计：访问日志、终端时间线、审计规则与事件、通知通道、报表、操作日志。"""
import csv
import io
import json
import time
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app import oplog, people, stats, timeutil
from app import notify
from app.audit import auditor, report, report_text
from app.config import get_settings
from app.database import get_db
from app.engine import engine
from app.models import AccessLog, AuditEvent, AuditRule, OpLog, Setting
from app.security import current_user

router = APIRouter(prefix="/api/audit", tags=["audit"], dependencies=[Depends(current_user)])

RANGES = "^(today|yesterday|week|month|last7|last30)$"


# ---------------- 访问日志 ----------------

def _log_query(start, end, host, q, app, group, person=None, dept=None):
    t = AccessLog
    from app.engine import VISIT_MAX_SPAN
    stmt = select(t).where(t.ts_start < end, t.ts_start >= start - VISIT_MAX_SPAN, t.ts_end >= start)
    hosts = people.scope_hosts(person, dept, host)
    if hosts is not None:
        stmt = stmt.where(t.host.in_(hosts))
    if app:
        stmt = stmt.where(t.app == app)
    if group:
        ids = [a.id for a in engine.classifier.apps.values()
               if engine.classifier.category_info(a.category)["group"] == group]
        stmt = stmt.where(t.app.in_(ids or ["-"]))
    if q:
        like = f"%{q.strip().lower()}%"
        stmt = stmt.where(or_(t.dest.like(like), t.remote.like(like), t.host_ip.like(like)))
    return stmt


def _bounds(rng, start, end):
    if start is not None and end is not None:
        return start, end
    return timeutil.range_bounds(rng)


def _row(r, meta):
    m = meta.get(r.host) or {}
    return {"id": r.id, "ts_start": r.ts_start, "ts_end": r.ts_end, "host": r.host, "host_name": m.get("name") or r.host,
            "host_ip": r.host_ip, "dest": r.dest, "remote": r.remote, "port": r.port, "proto": r.proto,
            "conns": r.conns, "up": r.up, "down": r.down, "source": r.source, "app": stats.app_meta(r.app)}


@router.get("/logs")
def logs(range: str = Query("today", pattern=RANGES), start: int | None = None, end: int | None = None,
         host: str | None = None, q: str = "", app: str | None = None, group: str | None = None,
         person: int | None = None, dept: int | None = None,
         page: int = Query(1, ge=1), size: int = Query(50, ge=10, le=500), db: Session = Depends(get_db)):
    """访问日志（按开始时间倒序，分页）"""
    s, e = _bounds(range, start, end)
    stmt = _log_query(s, e, host, q, app, group, person, dept)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(AccessLog.ts_start.desc()).offset((page - 1) * size).limit(size)).all()
    meta = stats.host_meta(db, {r.host for r in rows})
    return {"total": total, "page": page, "size": size, "rows": [_row(r, meta) for r in rows]}


@router.get("/logs.csv")
def logs_csv(request: Request, range: str = Query("today", pattern=RANGES), start: int | None = None,
             end: int | None = None, host: str | None = None, q: str = "", app: str | None = None,
             group: str | None = None, person: int | None = None, dept: int | None = None,
             user: str = Depends(current_user), db: Session = Depends(get_db)):
    """导出访问日志 CSV（最多 10 万行，UTF-8 带 BOM，Excel 直接打开）"""
    s, e = _bounds(range, start, end)
    rows = db.scalars(_log_query(s, e, host, q, app, group, person, dept).order_by(AccessLog.ts_start.desc()).limit(100_000)).all()
    meta = stats.host_meta(db, {r.host for r in rows})
    oplog.log(db, request, user, "export_logs", {"range": range, "host": host, "q": q, "rows": len(rows)})
    tz = timeutil.tz()
    buf = io.StringIO()
    buf.write("﻿")
    w = csv.writer(buf)
    w.writerow(["开始", "结束", "终端", "终端 IP", "访问目标", "远端 IP", "端口", "应用", "大类", "连接数", "上行字节", "下行字节", "识别依据"])
    for r in rows:
        x = _row(r, meta)
        w.writerow([datetime.fromtimestamp(r.ts_start, tz).strftime("%Y-%m-%d %H:%M:%S"),
                    datetime.fromtimestamp(r.ts_end, tz).strftime("%Y-%m-%d %H:%M:%S"), x["host_name"], r.host_ip,
                    r.dest, r.remote, r.port, x["app"]["name"], x["app"]["group_name"], r.conns, r.up, r.down, r.source])
    name = f"rosdpi-access-{datetime.now(tz).strftime('%Y%m%d-%H%M')}.csv"
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.get("/timeline")
def timeline(host: str | None = None, person: int | None = None, day: str | None = None, db: Session = Depends(get_db)):
    """终端（或一个人的所有设备）某一天的上网时间线：每个应用的访问时段，以及合并后的在线时段"""
    hosts = people.scope_hosts(person, None, host) or ["-"]
    tz = timeutil.tz()
    d = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=tz) if day else datetime.now(tz)
    d0 = int(d.replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
    d1 = timeutil.day_bucket(d0 + 86400 + 3600)
    from app.engine import VISIT_MAX_SPAN
    rows = db.scalars(select(AccessLog).where(AccessLog.host.in_(hosts), AccessLog.ts_start < d1,
                                              AccessLog.ts_start >= d0 - VISIT_MAX_SPAN, AccessLog.ts_end >= d0)
                      .order_by(AccessLog.ts_start)).all()
    per: dict[str, dict] = {}
    spans = []
    for r in rows:
        s, e = max(r.ts_start, d0), min(max(r.ts_end, r.ts_start + 60), d1)
        p = per.setdefault(r.app, {"app": stats.app_meta(r.app), "bytes": 0, "segments": [], "dests": {}})
        p["bytes"] += r.up + r.down
        p["dests"][r.dest] = p["dests"].get(r.dest, 0) + r.up + r.down
        if p["segments"] and s - p["segments"][-1][1] <= 120:
            p["segments"][-1][1] = max(p["segments"][-1][1], e)
            p["segments"][-1][2] += r.up + r.down
        else:
            p["segments"].append([s, e, r.up + r.down])
        spans.append([s, e])
    online = []
    for s, e in sorted(spans):  # 合并成在线时段（间隔 5 分钟以内算连续）
        if online and s - online[-1][1] <= 300:
            online[-1][1] = max(online[-1][1], e)
        else:
            online.append([s, e])
    apps = sorted(per.values(), key=lambda x: -x["bytes"])
    for a in apps:
        a["dests"] = [k for k, _v in sorted(a["dests"].items(), key=lambda x: -x[1])[:5]]
    return {"host": stats.host_meta(db, [host])[host] if host else None, "day": d.strftime("%Y-%m-%d"), "start": d0, "end": d1,
            "online": online, "apps": apps, "first": online[0][0] if online else None,
            "last": online[-1][1] if online else None, "active_seconds": sum(e - s for s, e in online)}


# ---------------- 审计规则与事件 ----------------

class RuleIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    enabled: bool = True
    kind: str = Field(pattern="^(group|category|app|domain|traffic|new_host|upload|sharing)$")
    value: str | None = Field(None, max_length=255)
    hosts: list[str] = []
    days: str = Field("1234567", pattern="^[1-7]{1,7}$")
    time_from: str = Field("00:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    time_to: str = Field("24:00", pattern=r"^(([01]\d|2[0-3]):[0-5]\d|24:00)$")
    min_bytes: int = Field(0, ge=0)
    notify: bool = True
    channels: list[str] = []          # 推送到哪些渠道；空 = 所有已启用的渠道


def _rule_dict(r: AuditRule):
    return {"id": r.id, "name": r.name, "enabled": bool(r.enabled), "kind": r.kind, "value": r.value,
            "hosts": [x for x in (r.hosts or "").split(",") if x], "days": r.days, "time_from": r.time_from,
            "time_to": r.time_to, "min_bytes": r.min_bytes or 0, "notify": bool(r.notify), "created": r.created,
            "channels": [x for x in (r.channels or "").split(",") if x]}


def _check_rule(req: RuleIn):
    c = engine.classifier
    if req.kind == "group" and req.value not in c.groups:
        raise HTTPException(400, "请选择应用大类")
    if req.kind == "category" and req.value not in c.categories:
        raise HTTPException(400, "请选择应用小类")
    if req.kind == "app" and req.value not in c.apps:
        raise HTTPException(400, "应用不存在")
    if req.kind == "domain" and not (req.value or "").strip(". "):
        raise HTTPException(400, "请填写域名，例如 example.com")
    if req.kind in ("traffic", "upload") and not req.min_bytes:
        raise HTTPException(400, "流量规则需要填写阈值")
    if req.kind == "upload" and req.value and req.value not in c.groups and req.value not in c.categories:
        raise HTTPException(400, "外发规则只能限定应用大类或分类")
    if any(x not in notify.CHANNEL_TYPES for x in req.channels):
        raise HTTPException(400, "未知的通知渠道")
    for h in req.hosts:
        if h.startswith("person:") and not h[7:].isdigit() or h.startswith("dept:") and not h[5:].isdigit():
            raise HTTPException(400, "适用范围无效")


@router.get("/rules")
def list_rules(db: Session = Depends(get_db)):
    return [_rule_dict(r) for r in db.scalars(select(AuditRule).order_by(AuditRule.id))]


@router.post("/rules")
def add_rule(req: RuleIn, request: Request, user: str = Depends(current_user), db: Session = Depends(get_db)):
    _check_rule(req)
    r = AuditRule(**{**req.model_dump(exclude={"hosts", "channels"}), "enabled": int(req.enabled), "notify": int(req.notify),
                     "hosts": ",".join(req.hosts), "channels": ",".join(req.channels), "created": int(time.time())})
    db.add(r)
    db.flush()
    oplog.log(db, request, user, "audit_rule_add", req.model_dump())
    auditor.reload()
    return _rule_dict(r)


@router.put("/rules/{rule_id}")
def update_rule(rule_id: int, req: RuleIn, request: Request, user: str = Depends(current_user),
                db: Session = Depends(get_db)):
    r = db.get(AuditRule, rule_id)
    if r is None:
        raise HTTPException(404, "规则不存在")
    _check_rule(req)
    for k, v in req.model_dump(exclude={"hosts", "channels"}).items():
        setattr(r, k, int(v) if isinstance(v, bool) else v)
    r.hosts = ",".join(req.hosts)
    r.channels = ",".join(req.channels)
    oplog.log(db, request, user, "audit_rule_edit", {"id": rule_id, **req.model_dump()})
    auditor.reload()
    return _rule_dict(r)


@router.delete("/rules/{rule_id}")
def delete_rule(rule_id: int, request: Request, user: str = Depends(current_user), db: Session = Depends(get_db)):
    r = db.get(AuditRule, rule_id)
    if r is None:
        raise HTTPException(404, "规则不存在")
    name = r.name
    db.delete(r)
    oplog.log(db, request, user, "audit_rule_delete", {"id": rule_id, "name": name})
    auditor.reload()
    return {"ok": True}


@router.get("/events")
def events(range: str = Query("week", pattern=RANGES), host: str | None = None, rule_id: int | None = None,
           page: int = Query(1, ge=1), size: int = Query(50, ge=10, le=500), db: Session = Depends(get_db)):
    s, e = timeutil.range_bounds(range)
    stmt = select(AuditEvent).where(AuditEvent.ts >= s, AuditEvent.ts < e)
    if host:
        stmt = stmt.where(AuditEvent.host == host)
    if rule_id:
        stmt = stmt.where(AuditEvent.rule_id == rule_id)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(AuditEvent.ts.desc()).offset((page - 1) * size).limit(size)).all()
    meta = stats.host_meta(db, {r.host for r in rows if r.host})
    out = []
    for r in rows:
        d = json.loads(r.detail or "{}")
        items = [{"key": k, "bytes": b, "app": stats.app_meta(k) if k in engine.classifier.apps else None}
                 for k, b in d.get("items", [])]
        out.append({"id": r.id, "ts": r.ts, "rule_id": r.rule_id, "rule": r.rule_name, "host": r.host,
                    "host_name": (meta.get(r.host) or {}).get("name", r.host), "host_ip": (meta.get(r.host) or {}).get("ip"),
                    "bytes": d.get("total") or d.get("bytes", 0), "items": items, "notified": int(r.notified or 0)})
    return {"total": total, "rows": out}


# ---------------- 通知通道 ----------------

class NotifyIn(BaseModel):
    config: dict[str, dict] = {}                 # {渠道: {enabled, ...}}
    quiet_from: str | None = Field(None, pattern=r"^(([01]\d|2[0-3]):[0-5]\d)?$")
    quiet_to: str | None = Field(None, pattern=r"^(([01]\d|2[0-3]):[0-5]\d)?$")


class NotifyTest(BaseModel):
    channel: str
    config: dict | None = None                   # 未保存的配置也能测试


def _clean(t: str, c: dict, old: dict) -> dict:
    """只保留该渠道认识的字段，类型按默认值转换；以“…”结尾的密钥沿用原值"""
    base = notify.DEFAULTS[t]
    c = notify.unmask(c, old)
    out = {"enabled": bool(c.get("enabled"))}
    for k, dv in base.items():
        v = c.get(k, dv)
        if isinstance(dv, bool):
            v = bool(v)
        elif isinstance(dv, list):
            v = [x for x in (v or []) if (x.get("key") if isinstance(x, dict) else str(x).strip())]
            if k != "headers":
                v = [str(x).strip() for x in v]
        elif isinstance(dv, int):
            try:
                v = int(v)
            except (TypeError, ValueError):
                v = dv
        else:
            v = str(v or "").strip()
        out[k] = v
    if t == "wecom" and out["mode"] not in ("webhook", "app"):
        out["mode"] = "webhook"
    for k in ("url", "server", "card_url", "icon"):
        if out.get(k) and not str(out[k]).startswith(("http://", "https://")):
            raise HTTPException(400, f"{notify_name(t)}：地址要以 http:// 或 https:// 开头")
    for u in out.get("urls") or []:
        if not u.startswith(("http://", "https://")):
            raise HTTPException(400, f"{notify_name(t)}：地址要以 http:// 或 https:// 开头")
    if out["enabled"] and notify.missing(t, out):
        raise HTTPException(400, f"{notify_name(t)}：请先填写 {', '.join(notify.missing(t, out))}")
    return out


def notify_name(t: str) -> str:
    return {"wecom": "企业微信", "dingtalk": "钉钉", "feishu": "飞书", "qq": "QQ", "bark": "Bark", "telegram": "Telegram",
            "email": "Email", "pushplus": "Pushplus", "serverchan": "Server酱", "ntfy": "ntfy", "gotify": "Gotify",
            "discord": "Discord", "slack": "Slack", "webhook": "Webhook"}.get(t, t)


@router.get("/notify")
def get_notify():
    return {"config": notify.mask(notify.load_config()), "types": list(notify.CHANNEL_TYPES), **notify.prefs(),
            "last": notify.last_results(), "enabled": notify.enabled_types()}


@router.put("/notify")
def put_notify(req: NotifyIn, request: Request, user: str = Depends(current_user), db: Session = Depends(get_db)):
    """保存所有渠道（一次性保存，和 EasySub 一样）和免打扰时段"""
    old = notify.load_config()
    cfg = {t: _clean(t, req.config.get(t) or old[t], old[t]) for t in notify.CHANNEL_TYPES}
    for key, val in (("notify_config", cfg), ("notify_prefs", {"quiet_from": req.quiet_from or "", "quiet_to": req.quiet_to or ""})):
        row = db.get(Setting, key)
        v = json.dumps(val, ensure_ascii=False)
        if row is None:
            db.add(Setting(key=key, value=v))
        else:
            row.value = v
    oplog.log(db, request, user, "notify_channels", {"enabled": [t for t, c in cfg.items() if c["enabled"]],
                                                      "quiet": f"{req.quiet_from or ''}-{req.quiet_to or ''}"})
    return get_notify()


@router.post("/notify/test")
def test_notify(req: NotifyTest):
    """测试一个渠道；带了 config 就用这份（可以是还没保存的），密钥以“…”结尾时沿用已保存的值"""
    if req.channel not in notify.DEFAULTS:
        raise HTTPException(400, "未知的渠道")
    old = notify.load_config()[req.channel]
    c = _clean(req.channel, {**(req.config or old), "enabled": True}, old)
    res = notify.send("ROS-DPI 测试消息", "收到这条消息，说明通知渠道配置正确。", types=[req.channel], wait=True,
                      config={req.channel: c})
    if not res[0]["ok"]:
        raise HTTPException(502, res[0]["error"])
    return {"ok": True}


def _draft(channel: str, config: dict | None) -> dict:
    """前端还没保存的配置：只保留认识的字段，密钥以“…”结尾时沿用已保存的值（不校验必填）"""
    old = notify.load_config()[channel]
    return _clean(channel, {**(config or old), "enabled": False}, old)


@router.post("/notify/telegram/{action}")
def telegram_helper(action: str, req: NotifyTest):
    """同 EasySub：「验证机器人」= getMe，「获取 Chat ID」= getUpdates（用户先给机器人发一条消息）"""
    method = {"me": "getMe", "updates": "getUpdates"}.get(action)
    if not method:
        raise HTTPException(404, "未知操作")
    try:
        return notify.telegram_call(_draft("telegram", req.config), method)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"Telegram {method} 失败：{e}")


@router.post("/notify/wecom/check")
def wecom_check(req: NotifyTest):
    """校验企业微信自建应用：拉取 access_token 并读取应用名与可见范围"""
    conf = _draft("wecom", req.config)
    if conf.get("mode") != "app":
        raise HTTPException(400, "该校验仅适用于「自建应用」模式")
    try:
        return {"ok": True, "agent": notify.wecom_agent_info(conf)}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, str(e))


# ---------------- 报表 ----------------

class ReportSettings(BaseModel):
    daily: bool | None = None
    weekly: bool | None = None


def _report_settings(db):
    def g(k):
        r = db.get(Setting, k)
        return bool(r and r.value == "1")
    return {"daily": g("report_daily"), "weekly": g("report_weekly")}


@router.get("/report")
def get_report(range: str = Query("yesterday", pattern=RANGES), db: Session = Depends(get_db)):
    r = report(db, range)
    title, text = report_text(r)
    return {**r, "title": title, "text": text, "settings": _report_settings(db)}


@router.put("/report/settings")
def put_report_settings(req: ReportSettings, request: Request, user: str = Depends(current_user),
                        db: Session = Depends(get_db)):
    for k, v in (("report_daily", req.daily), ("report_weekly", req.weekly)):
        if v is None:
            continue
        row = db.get(Setting, k)
        if row is None:
            db.add(Setting(key=k, value="1" if v else "0"))
        else:
            row.value = "1" if v else "0"
    oplog.log(db, request, user, "report_settings", req.model_dump())
    return _report_settings(db)


@router.post("/report/push")
def push_report_now(range: str = Query("yesterday", pattern=RANGES), db: Session = Depends(get_db)):
    title, text = report_text(report(db, range))
    res = notify.send(title, text, wait=True)
    if not res:
        raise HTTPException(400, "还没有配置通知通道")
    return {"results": res}


# ---------------- 操作日志 ----------------

@router.get("/oplog")
def op_log(page: int = Query(1, ge=1), size: int = Query(50, ge=10, le=500), db: Session = Depends(get_db)):
    total = db.scalar(select(func.count()).select_from(OpLog)) or 0
    rows = db.scalars(select(OpLog).order_by(OpLog.ts.desc()).offset((page - 1) * size).limit(size)).all()
    return {"total": total, "rows": [{"id": r.id, "ts": r.ts, "user": r.user, "ip": r.ip, "action": r.action,
                                      "detail": r.detail, "ok": bool(r.ok)} for r in rows]}


@router.get("/summary")
def summary(db: Session = Depends(get_db)):
    """审计页顶部的概况：今日访问记录数、今日审计事件、启用的规则数、通知通道数、保留天数"""
    s, e = timeutil.range_bounds("today")
    st = get_settings()
    return {
        "logs_today": db.scalar(select(func.count()).select_from(AccessLog).where(AccessLog.ts_start >= s)) or 0,
        "events_today": db.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.ts >= s)) or 0,
        "rules": db.scalar(select(func.count()).select_from(AuditRule).where(AuditRule.enabled == 1)) or 0,
        "channels": len(notify.enabled_types()),
        "retention_log_days": st.retention_log_days, "retention_event_days": st.retention_event_days,
        "open_visits": len(engine.visits),
    }
