import ipaddress
import re
import time

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import __version__, stats, timeutil
from app.classify import GENERIC_APPS
from app.config import get_settings
from app import database
from app.database import get_db
from app.engine import engine, parse_cidrs
from app.models import CustomRule, Setting
from app.ros_poller import poller
from app.security import current_user

router = APIRouter(prefix="/api", tags=["admin"], dependencies=[Depends(current_user)])

_PORT_RE = re.compile(r"^(tcp|udp)/\d{1,5}(-\d{1,5})?$", re.I)
_DOMAIN_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$", re.I)
_APPID_RE = re.compile(r"^[a-z0-9_]{1,48}$")


@router.get("/meta")
def meta():
    c = engine.classifier
    return {
        "groups": [{"id": k, **v} for k, v in c.groups.items()],
        "categories": [{"id": k, **v} for k, v in c.categories.items()],
        "apps": sorted(({"id": a.id, "name": a.name, "name_en": a.name_en, "category": a.category,
                         "custom": a.custom} for a in c.apps.values()), key=lambda a: a["id"]),
    }


# ---------- 自定义识别规则 ----------
class RuleIn(BaseModel):
    kind: str = Field(pattern="^(domain|cidr|port)$")
    pattern: str = Field(min_length=1, max_length=255)
    app_id: str = Field(min_length=1, max_length=48)
    app_name: str | None = Field(None, max_length=64)
    category: str | None = Field(None, max_length=32)


def _rule_dict(r: CustomRule):
    return {"id": r.id, "kind": r.kind, "pattern": r.pattern, "app_id": r.app_id, "app_name": r.app_name,
            "category": r.category, "created": r.created}


@router.get("/rules")
def list_rules(db: Session = Depends(get_db)):
    return [_rule_dict(r) for r in db.query(CustomRule).order_by(CustomRule.id.desc())]


@router.post("/rules")
def add_rule(req: RuleIn, db: Session = Depends(get_db)):
    p = req.pattern.strip().lower()
    if req.kind == "domain":
        p = p.strip(".")
        if not _DOMAIN_RE.match(p):
            raise HTTPException(400, "域名格式不正确")
    elif req.kind == "cidr":
        try:
            p = str(ipaddress.ip_network(p, strict=False))
        except ValueError:
            raise HTTPException(400, "IP 段格式不正确，例如 1.2.3.0/24")
    elif not _PORT_RE.match(p):
        raise HTTPException(400, "端口格式不正确，例如 tcp/8080 或 udp/3000-3010")
    known = req.app_id in engine.classifier.apps
    if not known:
        if not _APPID_RE.match(req.app_id):
            raise HTTPException(400, "新应用 ID 只能包含小写字母、数字和下划线")
        if not req.app_name:
            raise HTTPException(400, "新应用需要填写名称")
        if req.category not in engine.classifier.categories:
            raise HTTPException(400, "请选择分类")
    r = CustomRule(kind=req.kind, pattern=p, app_id=req.app_id, app_name=req.app_name,
                   category=req.category, created=int(time.time()))
    db.add(r)
    db.commit()
    engine.reload_rules()
    return _rule_dict(r)


@router.delete("/rules/{rule_id}")
def delete_rule(rule_id: int, db: Session = Depends(get_db)):
    r = db.get(CustomRule, rule_id)
    if r is None:
        raise HTTPException(404, "规则不存在")
    db.delete(r)
    db.commit()
    engine.reload_rules()
    return {"ok": True}


@router.get("/rules/unknown-domains")
def unknown_domains(range: str = Query("week", pattern="^(today|week|month|last7|last30)$"),
                    db: Session = Depends(get_db)):
    """按流量排序的未识别域名，方便一键归类。"""
    return stats.unknown_domains(db, *timeutil.range_bounds(range))


@router.get("/rules/test")
def test_rule(domain: str):
    """查看一个域名当前会被识别成什么。"""
    app = engine.classifier.match_domain(domain.strip().lower())
    return {"domain": domain, "app": stats.app_meta(app) if app else None}


# ---------- 设置 ----------
class SettingsIn(BaseModel):
    lan_cidrs: str | None = Field(None, max_length=2000)
    wan_interface: str | None = Field(None, max_length=64)


def _get(db, key, default=""):
    row = db.get(Setting, key)
    return row.value if row and row.value is not None else default


def _put(db, key, value):
    row = db.get(Setting, key)
    if row is None:
        db.add(Setting(key=key, value=value))
    else:
        row.value = value


@router.get("/settings")
def get_settings_api(db: Session = Depends(get_db)):
    s = get_settings()
    return {
        "lan_cidrs": engine.lan_cidrs_text,
        "lan_auto": [str(n) for n in engine.auto_nets],
        "wan_interface": _get(db, "wan_interface", s.wan_interface),
        "wan_detected": poller.wan_name,
        "interfaces": [i["name"] for i in poller.interfaces],
        "retention": {"minute": s.retention_minute_days, "hour": s.retention_hour_days,
                      "day": s.retention_day_days, "domain": s.retention_domain_days},
        "ros_url": s.ros_url, "ros_user": s.ros_user,
        "ports": {"http": s.http_port, "ipfix": s.ipfix_port, "tzsp": s.tzsp_port},
        "tz": s.tz,
        "database": _db_info(),
    }


def _db_info():
    eng = database.engine
    if eng is None:
        return None
    u = eng.url
    return {"source": "env" if get_settings().database_url else "wizard", "dialect": u.get_backend_name(),
            "host": u.host, "port": u.port, "database": u.database, "user": u.username}


@router.put("/settings")
def put_settings(req: SettingsIn, db: Session = Depends(get_db)):
    if req.lan_cidrs is not None:
        text = ",".join(x.strip() for x in req.lan_cidrs.replace("\n", ",").split(",") if x.strip())
        bad = [x for x in text.split(",") if x and not parse_cidrs(x)]
        if bad:
            raise HTTPException(400, f"无效网段：{', '.join(bad)}")
        _put(db, "lan_cidrs", text)
        engine.set_lan(text)
    if req.wan_interface is not None:
        _put(db, "wan_interface", req.wan_interface.strip())
        poller.wan_override = req.wan_interface.strip()
        poller._wan_prev = None
    db.commit()
    return get_settings_api(db)


# ---------- 系统状态 ----------
@router.get("/system")
def system():
    st = engine.stats
    now = int(time.time())
    return {
        "version": __version__,
        "collector": {
            "flows": st["flows"], "flows_dropped": st["flows_dropped"], "bytes": st["bytes_seen"],
            "last_flow": st["last_flow"], "exporters": st["exporters"],
            "decoder": engine.decoder.stats, "templates": len(engine.decoder.templates),
            "flow_ok": bool(st["last_flow"] and now - st["last_flow"] < 180),
        },
        "dns": {"packets": st["dns_packets"], "answers": st["dns_answers"], "last": st["last_dns"],
                "entries": len(engine.dns), "ok": bool(st["last_dns"] and now - st["last_dns"] < 600),
                "servers": sorted(({"ip": ip, "answers": n, "last": ts, "lan": engine.is_lan(ip)}
                                   for ip, (n, ts) in list(engine.dns_servers.items())),
                                  key=lambda x: x["answers"], reverse=True)[:8]},
        "sni": {"tls": st["sni_tls"], "quic": st["sni_quic"], "last": st["last_sni"],
                "ok": bool(st["last_sni"] and now - st["last_sni"] < 600)},
        # 流量靠什么认出域名（按字节）：conn 本连接 SNI、pair 本终端 DNS/SNI、ip 全网 IP 表、none 没有域名
        "match": dict(st["match"]),
        "router": poller.status(),
        "generic_apps": sorted(GENERIC_APPS),
    }


@router.post("/ros/test")
def ros_test():
    if not poller.enabled:
        raise HTTPException(400, "未配置 ROS_URL，请在环境变量中设置 RouterOS REST 地址和只读账号")
    poller.poll()
    return poller.status()
