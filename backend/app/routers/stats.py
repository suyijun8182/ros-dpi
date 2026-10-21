import time

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import stats, timeutil
from app.database import get_db
from app.engine import engine
from app.models import Host
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
    now = int(time.time())
    known = sum(a["total"] for a in apps if a["category"] not in ("unknown", "web", "network"))
    all_bytes = sum(a["total"] for a in apps) or 1
    return {
        "totals": stats.totals3(db),
        "range_total": stats.total(db, start, end),
        "rate": {"flow_up": engine.total_rate[0], "flow_down": engine.total_rate[1],
                 "wan_up": poller.wan_rate[0], "wan_down": poller.wan_rate[1]},
        "online": stats.online_count(db),
        "hosts_total": db.query(Host).count(),
        "identified_ratio": known / all_bytes,
        "top_apps": apps[:10],
        "categories": stats.top_categories(apps),
        "top_hosts": stats.top_hosts(db, start, end, limit=10),
        "trend": stats.trend(db, _trend_gran(range), start, end),
        "realtime": stats.trend(db, "minute", now - 3600, now + 1),
        "router": poller.status(),
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
    lease = poller.leases.get(meta["mac"] or "") or {}
    return {
        **meta,
        "totals": stats.totals3(db, host=key),
        "range_total": stats.total(db, start, end, host=key),
        "apps": apps,
        "categories": stats.top_categories(apps),
        "trend": stats.trend(db, _trend_gran(range), start, end, host=key),
        "domains": stats.host_domains(db, key, start, end),
        "dhcp": {"server": lease.get("server"), "status": lease.get("status"),
                 "expires_after": lease.get("expires-after")} if lease else None,
    }


class HostPatch(BaseModel):
    alias: str | None = Field(None, max_length=128)


@router.patch("/hosts/{key:path}")
def host_patch(key: str, req: HostPatch, db: Session = Depends(get_db)):
    h = db.get(Host, key)
    if h is None:
        raise HTTPException(404, "终端不存在")
    h.alias = (req.alias or "").strip() or None
    db.commit()
    return {"ok": True}


@router.get("/apps")
def apps(range: str = Query("today", pattern=RANGES), db: Session = Depends(get_db)):
    start, end = _bounds(range)
    rows = stats.top_apps(db, start, end)
    return {"apps": rows, "categories": stats.top_categories(rows), "range_total": stats.total(db, start, end)}


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
