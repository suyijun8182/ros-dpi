import time

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import health, hostnames, oplog, stats, timeutil
from app.asn import asndb
from app.database import get_db
from app.engine import engine
from app.models import DomainGeo, Host, HostName
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
        "apps_library": len(engine.classifier.apps),
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
        # range=today 时健康指数要的今日应用排行已经查过，直接复用
        "health": health.compute(db, apps if range == "today" else None),
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
def host_patch(key: str, req: HostPatch, request: Request, user: str = Depends(current_user),
               db: Session = Depends(get_db)):
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
    oplog.log(db, request, user, "rename_host", {"host": key, "by": by, "name": req.alias})
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
def put_name(req: NameIn, request: Request, user: str = Depends(current_user), db: Session = Depends(get_db)):
    """新增或修改一条命名；name 为空表示删除。可以给还没出现过的设备提前命名。"""
    value = hostnames.normalize(req.kind, req.value)
    if value is None:
        raise HTTPException(400, "MAC 地址格式不正确，例如 AA:BB:CC:DD:EE:FF" if req.kind == "mac"
                            else "IP 地址格式不正确，例如 192.168.88.20")
    hostnames.put(db, req.kind, value, req.name)
    oplog.log(db, request, user, "name_set", {"kind": req.kind, "value": value, "name": req.name})
    return _name_rows(db)


@router.delete("/names/{kind}/{value:path}")
def delete_name(kind: str, value: str, request: Request, user: str = Depends(current_user),
                db: Session = Depends(get_db)):
    v = hostnames.normalize(kind, value)
    if v is None:
        raise HTTPException(400, "格式不正确")
    hostnames.put(db, kind, v, None)
    oplog.log(db, request, user, "name_delete", {"kind": kind, "value": v})
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


@router.get("/realtime")
def realtime(db: Session = Depends(get_db)):
    """实时流量曲线（最近 1 小时，速率 B/s）。有 RouterOS API 时用 WAN 口计数器的秒级采样，否则用每分钟的流量记录。"""
    now = int(time.time())
    if poller.enabled and poller.ok and len(poller.samples) >= 2:
        pts = [{"ts": ts, "up": u, "down": d} for ts, u, d in poller.samples if ts >= now - 3600]
        return {"source": "wan", "interface": poller.wan_name, "points": pts}
    pts = [{"ts": p["ts"], "up": p["up"] / 60, "down": p["down"] / 60}
           for p in stats.trend(db, "minute", now - 3600, now + 1)]
    return {"source": "flow", "interface": None, "points": pts}


@router.get("/sessions")
def sessions(q: str = "", host: str | None = None, limit: int = Query(300, ge=10, le=2000), db: Session = Depends(get_db)):
    """实时连接：此刻还在传数据的连接，按实时速率、再按累计流量排序。"""
    rows = engine.session_list()
    if host:
        rows = [r for r in rows if r["host"] == host]
    meta = stats.host_meta(db, {r["host"] for r in rows})
    s = q.strip().lower()
    out = []
    for r in rows:
        m = meta[r["host"]]
        app = stats.app_meta(r["app"])
        if s and not any(s in str(v).lower() for v in (m["name"], r["host_ip"], r["remote"], r["domain"], app["name"],
                                                         app["name_en"], r["port"], *(r["route"] or {}).values()) if v):
            continue
        out.append({**r, "host_name": m["name"], "online": m["online"], "app": app, "asn": _asn(r["remote"])})
    out.sort(key=lambda r: (r["rate_up"] + r["rate_down"], r["up"] + r["down"]), reverse=True)
    return {"count": len(out), "rate_up": sum(r["rate_up"] for r in out), "rate_down": sum(r["rate_down"] for r in out),
            "sessions": out[:limit]}


@router.get("/destinations")
def destinations(range: str = Query("today", pattern=RANGES), q: str = "", merge: bool = False,
                 kind: str = Query("all", pattern="^(all|domain|ip)$"), db: Session = Depends(get_db)):
    """访问目标排行（远端域名 / IP）"""
    start, end = _bounds(range)
    rows = stats.destinations(db, start, end, q, merge, kind)
    idx = engine.dns.name_index()
    names = {n for r in rows if not r["ip"] for n in [r["dest"], *r["name_list"]]}
    geo = {}
    for chunk in _chunks500(sorted(names)):  # 参数名 range 遮住了内置 range，分块放到模块级
        geo.update(dict(db.execute(select(DomainGeo.domain, DomainGeo.cc).where(DomainGeo.domain.in_(chunk))).all()))
    countries: dict[str, int] = {}
    for r in rows:
        r["asn"] = _asn(r["dest"]) if r["ip"] else None
        if not r["ip"]:
            # 域名：记录流量时存下的国家（DomainGeo）；没有时再用 DNS 缓存里最近解析到的 IP 查
            cc = geo.get(r["dest"]) or next((geo[n] for n in r["name_list"] if n in geo), None)
            if not cc:
                ip = idx.get(r["dest"]) or next((idx[n] for n in r["name_list"] if n in idx), None)
                hit = asndb.lookup(ip) if ip else None
                cc = hit[1] if hit else None
            r["country"] = cc
        else:
            r["country"] = r["asn"]["country"] if r["asn"] else None
        r.pop("name_list", None)
        cc = r["country"] or "-"
        countries[cc] = countries.get(cc, 0) + r["bytes"]
    return {"range_total": stats.total(db, start, end), "rows": rows,
            "countries": [{"cc": k, "bytes": v} for k, v in sorted(countries.items(), key=lambda x: x[1], reverse=True)],
            "home": _home_country()}


def _chunks500(xs: list) -> list[list]:
    return [xs[i:i + 500] for i in range(0, len(xs), 500)]


def _home_country() -> str:
    """本地所在国家（流向图的起点）：WAN 口公网 IP 的归属；拿不到时按中国"""
    for w in poller.wans:
        hit = asndb.lookup(w.get("ip") or "") if w.get("ip") else None
        if hit and hit[1]:
            return hit[1]
    return "CN"


@router.get("/proxy/routes")
def proxy_routes():
    """代理分流（sing-box）：今天按 策略组 / 出口节点 的流量、连接数和主要应用"""
    from app.integrations import singbox
    rows = engine.proxy_route_list()
    for r in rows:
        r["apps"] = [{**stats.app_meta(a["id"]), "bytes": a["bytes"]} for a in r["apps"]]
    return {"enabled": singbox.enabled, "ok": singbox.ok, "error": singbox.error, "rows": rows,
            "up": sum(r["up"] for r in rows), "down": sum(r["down"] for r in rows)}


def _asn(ip: str):
    """远端 IP 的归属（ASN、国家、名称），没有 ASN 库或查不到时为 None"""
    hit = asndb.lookup(ip) if ip else None
    return {"asn": hit[0], "country": hit[1], "name": hit[2]} if hit else None


@router.get("/destinations/hosts")
def destination_hosts(dest: str, range: str = Query("today", pattern=RANGES), merge: bool = False,
                      db: Session = Depends(get_db)):
    """某个访问目标被哪些终端访问"""
    return stats.destination_hosts(db, dest, *_bounds(range), merge=merge)
