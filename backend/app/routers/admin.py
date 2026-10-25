import ipaddress
import re
import time

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import __version__, integrations, oplog, stats, timeutil
from app.asn import asndb
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
def add_rule(req: RuleIn, request: Request, user: str = Depends(current_user), db: Session = Depends(get_db)):
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
    oplog.log(db, request, user, "rule_add", req.model_dump())
    engine.reload_rules()
    return _rule_dict(r)


@router.delete("/rules/{rule_id}")
def delete_rule(rule_id: int, request: Request, user: str = Depends(current_user), db: Session = Depends(get_db)):
    r = db.get(CustomRule, rule_id)
    if r is None:
        raise HTTPException(404, "规则不存在")
    detail = {"id": rule_id, "kind": r.kind, "pattern": r.pattern, "app_id": r.app_id}
    db.delete(r)
    oplog.log(db, request, user, "rule_delete", detail)
    engine.reload_rules()
    return {"ok": True}


@router.get("/rules/unknown-domains")
def unknown_domains(range: str = Query("week", pattern="^(today|week|month|last7|last30)$"),
                    db: Session = Depends(get_db)):
    """按流量排序的未识别域名，方便一键归类。"""
    return stats.unknown_domains(db, *timeutil.range_bounds(range))


@router.post("/rules/reclassify")
def rules_reclassify(request: Request, user: str = Depends(current_user), db: Session = Depends(get_db)):
    """按当前规则重算历史分类：规则或识别库升级后，把历史流量搬到新归属（host_domain_day 覆盖的天数）。"""
    from app.reclass import reclassify
    res = reclassify(engine, db)
    db.commit()
    oplog.log(db, request, user, "reclassify", res)
    return res


@router.get("/rules/test")
def test_rule(domain: str):
    """查看一个域名当前会被识别成什么。"""
    app = engine.classifier.match_domain(domain.strip().lower())
    return {"domain": domain, "app": stats.app_meta(app) if app else None}


# ---------- 设置 ----------
class SettingsIn(BaseModel):
    lan_cidrs: str | None = Field(None, max_length=2000)
    wan_interface: str | None = Field(None, max_length=64)
    # 外部数据源（可选），每个人的地址不同，由用户填写；空字符串表示清除
    singbox_url: str | None = Field(None, max_length=255)
    singbox_secret: str | None = Field(None, max_length=255)
    proxy_ips: str | None = Field(None, max_length=500)
    mosdns_url: str | None = Field(None, max_length=255)
    adguard_url: str | None = Field(None, max_length=255)
    adguard_username: str | None = Field(None, max_length=255)
    adguard_password: str | None = Field(None, max_length=255)
    rules_auto_update: bool | None = None
    share_enabled: bool | None = None


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
        "share_enabled": _get(db, "share_enabled", "1" if s.share_enabled else "0") == "1",
        "tz": s.tz,
        "database": _db_info(),
        "integrations": _integrations(db),
    }


def _integrations(db):
    saved = {k: _get(db, k, None) for k in integrations.KEYS}
    cfg = integrations.effective(saved)
    return {"singbox_url": cfg["singbox_url"], "has_secret": bool(cfg["singbox_secret"]), "proxy_ips": cfg["proxy_ips"],
            "mosdns_url": cfg["mosdns_url"],
            "adguard_url": cfg["adguard_url"], "adguard_username": cfg["adguard_username"],
            "has_adguard_password": bool(cfg["adguard_password"]),
            "proxy_auto": integrations.singbox.host_ip()}


def local_status():
    """本地自学习库（debug15）：本网络实测的 IP→应用 记忆规模"""
    from app.classify.local import local
    return {"ips": len(local.ips), "domains": len(local.domains), "updated": local.version}






def _db_info():
    eng = database.engine
    if eng is None:
        return None
    u = eng.url
    return {"source": "env" if get_settings().database_url else "wizard", "dialect": u.get_backend_name(),
            "host": u.host, "port": u.port, "database": u.database, "user": u.username}


@router.put("/settings")
def put_settings(req: SettingsIn, request: Request, user: str = Depends(current_user), db: Session = Depends(get_db)):
    if req.lan_cidrs is not None:
        text = ",".join(x.strip() for x in req.lan_cidrs.replace("\n", ",").split(",") if x.strip())
        bad = [x for x in text.split(",") if x and not parse_cidrs(x)]
        if bad:
            raise HTTPException(400, f"无效网段：{', '.join(bad)}")
        _put(db, "lan_cidrs", text)
        engine.set_lan(text)
    changed = False
    for k in integrations.KEYS:
        v = getattr(req, k)
        if v is None:
            continue
        v = v.strip()
        if k.endswith("_url") and v and not v.startswith(("http://", "https://")):
            raise HTTPException(400, "地址要以 http:// 或 https:// 开头，例如 http://192.168.1.2:9090")
        _put(db, k, v)
        changed = True
    if changed:
        db.flush()
        integrations.apply({k: _get(db, k, None) for k in integrations.KEYS})
    if req.rules_auto_update is not None:
        _put(db, "rules_auto_update", "1" if req.rules_auto_update else "0")
    if req.share_enabled is not None:
        _put(db, "share_enabled", "1" if req.share_enabled else "0")
        db.commit()
        from app import share
        share.kick(share.run_once)
    if req.wan_interface is not None:
        _put(db, "wan_interface", req.wan_interface.strip())
        poller.wan_override = req.wan_interface.strip()
        poller._wan_prev = None
    oplog.log(db, request, user, "settings", req.model_dump(exclude_none=True))
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
        "ros_check": poller.check(),
        "singbox": integrations.singbox.status(),
        "mosdns": integrations.mosdns.status(),
        "adguard": integrations.adguard.status(),
        "local": local_status(),
        "asn": asndb.status(),
        "proxied_skipped": st["proxied_skipped"], "dns_mosdns": st["dns_mosdns"],
        "generic_apps": sorted(GENERIC_APPS),
    }


# ---------- 识别库：来源、版本、自动更新 ----------
def _library(db):
    from app.classify.lists import lists
    from app.classify.local import local
    from app.classify.sources import sources
    from app.classify.updater import updater
    c = engine.classifier
    base_ids = {a["id"] for a in c._base_apps}
    v2_apps = c._extra.get("apps", [])
    v2_domains = sum(len(x.get("domains", [])) + len(x.get("full", [])) for x in v2_apps + c._extra.get("extend", []))
    base_domains = sum(len(a.get("domains", [])) for a in c._base_apps)
    third = {r["id"]: r for r in lists.rows()}
    return {
        "auto": _get(db, "rules_auto_update", "1") != "0",
        "total_apps": len(c.apps),
        "total_domains": len(c.domains) + len(c.full) + len(lists.bm7_suffix) + len(lists.bm7_full) + len(lists.cat),
        # 按识别顺序排列（前端给每行编号）
        "sources": [
            {"id": "curated", "apps": len(base_ids), "domains": base_domains, "version": __version__,
             "license": "MIT", "url": "https://github.com/suyijun8182/ros-dpi"},
            {"id": "v2fly", "apps": len(v2_apps), "domains": v2_domains, "license": "MIT",
             "url": "https://github.com/v2fly/domain-list-community", **updater.status()},
            *[third[k] for k in ("bm7",) if k in third],
            {"id": "asn", "license": "PDDL v1.0", "url": "https://iptoasn.com", "asns": len(c.asn_apps), **asndb.status()},
            *[third[k] for k in ("hagezi", "ut1") if k in third],
            *sources.rows(),
            # 本地自学习库（debug15）：本网络实测的 IP→应用 记忆，排在所有公开库之后做兜底
            {"id": "local", "license": "本地实测", "url": "https://github.com/suyijun8182/ros-dpi",
             "ips": len(local.ips), "domains": len(local.domains), "updated": local.updated},
        ],
    }


@router.get("/library")
def library(db: Session = Depends(get_db)):
    return _library(db)


@router.get("/system/deployments")
def system_deployments(db: Session = Depends(get_db)):
    """社区共享状态 + 全球部署量（设置页 → 外部数据源 → 社区共享库）"""
    from app import share
    return share.status(db)


@router.get("/system/update")
def system_update_status():
    """Linux 二进制部署的版本检测（debug18）：当前版本 vs GitHub 最新 Release"""
    from app import selfupdate
    return selfupdate.status(__version__)


@router.post("/system/update")
def system_update_run(request: Request, user: str = Depends(current_user), db: Session = Depends(get_db)):
    """一键自更新（仅 Linux 二进制部署）：下载新版本 → 原子替换 → 自动重启服务"""
    from app import selfupdate
    try:
        res = selfupdate.perform(__version__)
    except RuntimeError as e:
        raise HTTPException(400, str(e))
    oplog.log(db, request, user, "self_update", res)
    return res


@router.post("/library/update")
def library_update(request: Request, user: str = Depends(current_user), db: Session = Depends(get_db)):
    """立即检查识别库更新（v2fly 规则 + ASN 库 + 补充库），返回最新状态"""
    from app.classify.sources import sources
    from app.classify.updater import updater
    updater.check(force=True, reload=engine.reload_classifier)
    if get_settings().asn_db:
        asndb.update()
    sources.update(force=True)
    from app.classify.lists import lists
    lists.update(force=True)
    oplog.log(db, request, user, "library_update", {"result": updater.state.get("result")})
    try:
        from app.reclass import auto_reclassify
        res = auto_reclassify(engine, db)
        if res:
            db.commit()
            oplog.log(db, request, user, "reclassify", res)
    except Exception as e:  # noqa: BLE001  重算失败不影响更新结果
        db.rollback()
        print(f"[reclass] 手动更新后自动重算失败：{type(e).__name__}: {e}", flush=True)
    return _library(db)


@router.post("/integrations/test")
def integrations_test():
    """立即读一次 sing-box / MosDNS / AdGuard Home，返回各自状态（用于“测试连接”按钮）"""
    integrations.singbox.poll()
    integrations.mosdns.poll()
    integrations.adguard.poll()
    return {"singbox": integrations.singbox.status(), "mosdns": integrations.mosdns.status(),
            "adguard": integrations.adguard.status()}


@router.post("/ros/test")
def ros_test():
    if not poller.enabled:
        raise HTTPException(400, "未配置 ROS_URL，请在环境变量中设置 RouterOS REST 地址和只读账号")
    poller.poll()
    return poller.status()
