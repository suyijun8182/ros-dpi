import time

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import health, hostnames, stats, timeutil
from app.database import get_db
from app.engine import engine
from app.models import Host, HostName
from app.ros_poller import poller
from app.security import current_user

router = APIRouter(prefix="/api", tags=["stats"], dependencies=[Depends(current_user)])

RANGES = "^(today|yesterday|week|month|last7|last30)$"


def _bounds(rng: str):
    return timeutil.range_bounds(rng)


def _trend_gran(rng: str) -> str:
    return "hour" if rng in ("today", "yesterday") else "day"


@router.get("/overview")
def overview(range: str = Query("today", pattern=RANGES), db: Session = Depends(get_db)):
    start, end = _bounds(range)
    apps = stats.top_apps(db, start, end)
    cats = stats.top_categories(apps)
    now = int(time.time())
    return {
        "totals": stats.totals3(db),
        "range_total": stats.total(db, start, end),
        "rate": {"flow_up": engine.total_rate[0], "flow_down": engine.total_rate[1],
                 "wan_up": poller.wan_rate[0], "wan_down": poller.wan_rate[1]},
        "online": stats.online_count(db),
        "hosts_total": db.query(Host).count(),
        "identified_ratio": stats.identified_ratio(apps),
        "apps_count": len(apps),
        "top_apps": apps[:10],
        "categories": cats,
        "groups": stats.top_groups(cats),
        "top_hosts": stats.top_hosts(db, start, end, limit=10),
        "trend": stats.trend(db, _trend_gran(range), start, end),
        "trend_groups": stats.trend_groups(db, _trend_gran(range), start, end),
        "realtime": stats.trend(db, "minute", now - 3600, now + 1),
        "online_realtime": stats.online_trend(db, "minute", now - 3600, now + 1),
        "online_trend": stats.online_trend(db, _trend_gran(range), start, end),
        "new_today": stats.new_hosts(db, timeutil.range_bounds("today")[0]),
        "router": poller.status(),
        "wans": poller.wans,
        "pools": poller.pools,
        "health": health.compute(db),
    }


@router.get("/trend")
def trend(range: str = Query("today", pattern=RANGES), gran: str = Query(None, pattern="^(minute|hour|day)$"),
          host: str | None = None, app: str | None = None, db: Session = Depends(get_db)):
    start, end = _bounds(range)
    return stats.trend(db, gran or _trend_gran(range), start, end, host, app)


@router.get("/hosts")
def hosts(db: Session = Depends(get_db)):
    rows = stats.all_hosts(db)
    top = stats.top_app_per_host(db, *_bounds("today"))
    for r in rows:
        r["top_app"] = top.get(r["key"])
    return rows


@router.get("/hosts/{key:path}/detail")
def host_detail(key: str, range: str = Query("today", pattern=RANGES), db: Session = Depends(get_db)):
    start, end = _bounds(range)
    meta = stats.host_meta(db, [key])[key]
    if meta["first_seen"] is None and stats.total(db, *_bounds("month"), host=key)["total"] == 0:
        raise HTTPException(404, "终端不存在")
    apps = stats.top_apps(db, start, end, host=key)
    cats = stats.top_categories(apps)
    lease = poller.leases.get(meta["mac"] or "") or {}
    return {
        **meta,
        "totals": stats.totals3(db, host=key),
        "range_total": stats.total(db, start, end, host=key),
        "apps": apps,
        "categories": cats,
        "groups": stats.top_groups(cats),
        "trend": stats.trend(db, _trend_gran(range), start, end, host=key),
        "trend_groups": stats.trend_groups(db, _trend_gran(range), start, end, host=key),
        "domains": stats.host_domains(db, key, start, end),
        "dhcp": {"server": lease.get("server"), "status": lease.get("status"),
                 "expires_after": lease.get("expires-after")} if lease else None,
    }


class HostPatch(BaseModel):
    alias: str | None = Field(None, max_length=128)
    by: str | None = Field(None, pattern="^(mac|ip)$")  # 留空：有 MAC 按 MAC，否则按 IP


@router.patch("/hosts/{key:path}")
def host_patch(key: str, req: HostPatch, db: Session = Depends(get_db)):
    """给终端改名。按 MAC 命名跟着设备走；按 IP 命名跟着地址走。"""
    h = db.get(Host, key)
    if h is None:
        raise HTTPException(404, "终端不存在")
    by = req.by or ("mac" if h.mac else "ip")
    value = h.mac if by == "mac" else h.ip
    if not value:
        raise HTTPException(400, "这台终端没有 MAC 地址，只能按 IP 命名" if by == "mac" else "这台终端没有 IP 地址")
    # 换了命名方式时，删掉另一种方式下这台终端的旧名字，避免两处都有
    other = ("ip", h.ip) if by == "mac" else ("mac", h.mac)
    if other[1]:
        hostnames.put(db, other[0], other[1], None)
    hostnames.put(db, by, value, req.alias)
    h.alias = None
    db.commit()
    return {"ok": True, **stats.host_meta(db, [key])[key]}


# ---------- 终端命名表（按 MAC / IP） ----------
class NameIn(BaseModel):
    kind: str = Field(pattern="^(mac|ip)$")
    value: str = Field(min_length=1, max_length=45)
    name: str = Field("", max_length=128)


def _name_rows(db):
    hosts = db.query(Host).all()
    by_mac = {h.mac: h for h in hosts if h.mac}
    by_ip: dict[str, Host] = {}
    for h in sorted(hosts, key=lambda x: x.last_seen or 0):
        if h.ip:
            by_ip[h.ip] = h  # 同一 IP 用过多台设备时取最近的
    out = []
    for n in db.query(HostName).order_by(HostName.kind, HostName.value):
        h = by_mac.get(n.value) if n.kind == "mac" else by_ip.get(n.value)
        out.append({"kind": n.kind, "value": n.value, "name": n.name, "updated": n.updated,
                    "host": {"key": h.key, "ip": h.ip, "mac": h.mac, "hostname": h.hostname} if h else None})
    return out


@router.get("/names")
def list_names(db: Session = Depends(get_db)):
    return _name_rows(db)


@router.put("/names")
def put_name(req: NameIn, db: Session = Depends(get_db)):
    """新增或修改一条命名；name 为空表示删除。可以给还没出现过的设备提前命名。"""
    value = hostnames.normalize(req.kind, req.value)
    if value is None:
        raise HTTPException(400, "MAC 地址格式不正确，例如 AA:BB:CC:DD:EE:FF" if req.kind == "mac"
                            else "IP 地址格式不正确，例如 192.168.88.20")
    hostnames.put(db, req.kind, value, req.name)
    db.commit()
    return _name_rows(db)


@router.delete("/names/{kind}/{value:path}")
def delete_name(kind: str, value: str, db: Session = Depends(get_db)):
    v = hostnames.normalize(kind, value)
    if v is None:
        raise HTTPException(400, "格式不正确")
    hostnames.put(db, kind, v, None)
    db.commit()
    return _name_rows(db)


@router.get("/search")
def search(q: str = Query(..., min_length=1, max_length=64), db: Session = Depends(get_db)):
    """顶栏功能搜索：终端（名称 / IP / MAC / 主机名）和应用。页面名由前端自己匹配。"""
    s = q.strip().lower()
    names = hostnames.load(db)
    hosts = []
    for h in db.query(Host).order_by(Host.last_seen.desc()).limit(5000):
        alias, _by = hostnames.resolve(names, h.mac, h.ip)
        fields = [alias, h.hostname, h.ip, h.mac, h.key]
        if any(f and s in f.lower() for f in fields):
            hosts.append({"key": h.key, "name": alias or h.hostname or h.ip or h.key, "ip": h.ip, "mac": h.mac})
            if len(hosts) >= 8:
                break
    apps = [stats.app_meta(a.id) for a in engine.classifier.apps.values()
            if s in a.id.lower() or s in str(a.name).lower() or s in str(a.name_en).lower()]
    # ID 完全相同的最前；手工规则库的应用排在 v2fly 导入的前面；再按名称开头匹配、名称长短
    apps.sort(key=lambda a: (a["id"] != s, a["id"].startswith("v2_"),
                             not any(str(a[k]).lower().startswith(s) for k in ("name", "name_en")), len(str(a["name"]))))
    return {"hosts": hosts, "apps": apps[:8]}


@router.get("/dhcp/leases")
def dhcp_leases(db: Session = Depends(get_db)):
    """RouterOS 的 DHCP 租约（需要配置 ROS API），附带 ROS-DPI 里的命名和终端链接。"""
    names = hostnames.load(db)
    keys = {h.mac: h.key for h in db.query(Host).filter(Host.mac.isnot(None))}
    out = []
    for le in poller.lease_list:
        alias, _by = hostnames.resolve(names, le["mac"] or None, le["address"])
        out.append({**le, "alias": alias, "host_key": keys.get(le["mac"])})
    return {"enabled": poller.enabled, "pools": poller.pools, "leases": out}


@router.get("/apps")
def apps(range: str = Query("today", pattern=RANGES), db: Session = Depends(get_db)):
    start, end = _bounds(range)
    rows = stats.top_apps(db, start, end)
    cats = stats.top_categories(rows)
    return {"apps": rows, "categories": cats, "groups": stats.top_groups(cats),
            "range_total": stats.total(db, start, end)}


@router.get("/apps/{app_id}/detail")
def app_detail(app_id: str, range: str = Query("today", pattern=RANGES), db: Session = Depends(get_db)):
    start, end = _bounds(range)
    return {
        **stats.app_meta(app_id),
        "totals": stats.totals3(db, app=app_id),
        "range_total": stats.total(db, start, end, app=app_id),
        "hosts": stats.top_hosts(db, start, end, app=app_id),
        "trend": stats.trend(db, _trend_gran(range), start, end, app=app_id),
    }


@router.get("/flow")
def flow(range: str = Query("today", pattern=RANGES), host: str | None = None,
         hosts: int = Query(12, ge=3, le=40), apps: int = Query(16, ge=3, le=60), db: Session = Depends(get_db)):
    return stats.flow_graph(db, *_bounds(range), max_hosts=hosts, max_apps=apps, host=host)
