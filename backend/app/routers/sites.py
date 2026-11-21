"""多站点（0.7.0）：站点管理。

- GET /api/sites/mine：当前用户能看的站点（顶部站点切换器用），所有登录用户可用；
- 其余接口只给管理员：站点的增删改、未登记来源。
  站点的 RouterOS 账号 / LAN 网段 / WAN 口仍走 PUT /api/settings?site=<slug>，试连走 POST /api/ros/test?site=<slug>。
"""
import re
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app import database, integrations, oplog
from app.database import get_db
from app.models import (DEFAULT_SITE, AuditRule, CustomRule, Setting, Site, UnknownSource, UserSite)
from app.scoping import SITE_MODELS
from app.security import current_user, require_admin
from app.sites import norm_ip, registry, split_sources
from app.sitectx import visible_sites

router = APIRouter(prefix="/api/sites", tags=["sites"], dependencies=[Depends(current_user)])
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")
MAX_SITES = 20


class SiteIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    sources: list[str] = []
    platform_addr: str = Field("", max_length=255)
    enabled: bool = True


class OtherSources(BaseModel):
    slug: str = Field(min_length=1, max_length=32)
    sources: list[str]


class SiteNew(SiteIn):
    slug: str = Field(min_length=1, max_length=32)
    # 添加第二个站点时，已有站点要同时补上源 IP：和新站点一起校验、一起保存（任何一项不通过都不改）
    others: list[OtherSources] = []


class SiteDelete(BaseModel):
    confirm: str = Field(min_length=1, max_length=32)   # 要删的站点标识，防误删


def _status(slug: str) -> dict:
    p = registry.poller(slug)
    e = registry.get(slug)
    st = p.status() if p else {"enabled": False, "ok": False, "error": "", "last_poll": 0}
    last_flow = (e.stats.get("last_flow") or 0) if e else 0
    return {"ros_enabled": st["enabled"], "ros_ok": st["ok"], "ros_error": st.get("error") or "",
            "ros_last_poll": st.get("last_poll") or 0, "identity": st.get("identity") or "",
            "last_flow": last_flow, "receiving": bool(last_flow and time.time() - last_flow < 180)}


def _dict(r: Site, full: bool = False) -> dict:
    out = {"slug": r.slug, "name": r.name, "enabled": bool(r.enabled), "sort": r.sort or 0, **_status(r.slug)}
    if full:
        out.update(sources=split_sources(r.sources), platform_addr=r.platform_addr or "",
                   ros_url=r.ros_url or "", lan_cidrs=r.lan_cidrs or "", wan_interface=r.wan_interface or "",
                   created=r.created)
    return out


def _rows(db) -> list[Site]:
    return db.scalars(select(Site).order_by(Site.sort, Site.created, Site.slug)).all()


@router.get("/mine")
def mine(request: Request, user: str = Depends(current_user), db: Session = Depends(get_db)):
    """顶部站点切换器：能看的站点、各自状态；multi=False（只有一个站点）时前端不显示任何多站点界面"""
    vis = set(visible_sites(request, user))
    rows = [_dict(r) for r in _rows(db) if r.slug in vis]
    # 站点 ≥2 个（含停用的：停用站点的历史数据还能查）才显示多站点界面
    return {"multi": len(registry.info) > 1, "sites": rows}


@router.get("")
def list_sites(_: str = Depends(require_admin), db: Session = Depends(get_db)):
    return {"sites": [_dict(r, full=True) for r in _rows(db)], "integrations_site": _integrations_site(db)}


def _integrations_site(db) -> str:
    row = db.get(Setting, integrations.SITE_KEY)
    return (row.value if row and row.value else "") or DEFAULT_SITE


def _clean_sources(items: list[str]) -> str:
    out = []
    for x in items:
        x = (x or "").strip()
        if not x:
            continue
        ip = norm_ip(x)
        if ip is None:
            raise HTTPException(400, f"源 IP 格式不正确：{x[:45]}")
        if ip not in out:
            out.append(ip)
    return ",".join(out)


def _validate_all(db):
    """D5：启用站点 ≥2 个时每个都必须登记源 IP；同一个源 IP 不能登记到两个站点"""
    rows = [r for r in _rows(db) if r.enabled]
    owner: dict[str, str] = {}
    for r in rows:
        for ip in split_sources(r.sources):
            if ip in owner and owner[ip] != r.slug:
                raise HTTPException(400, f"源 IP {ip} 已经登记在站点「{registry.name(owner[ip]) or owner[ip]}」")
            owner[ip] = r.slug
    if len(rows) >= 2:
        missing = [r.name for r in rows if not split_sources(r.sources)]
        if missing:
            raise HTTPException(400, "有多个站点时，每个站点都要登记源 IP（路由器发 IPFIX / TZSP 用的地址），"
                                     f"还没填的：{'、'.join(missing)}")


def _apply(db):
    db.flush()
    _validate_all(db)
    db.commit()
    registry.load(db)


@router.post("")
def add_site(req: SiteNew, request: Request, user: str = Depends(require_admin), db: Session = Depends(get_db)):
    slug = req.slug.strip().lower()
    if not SLUG_RE.match(slug) or slug == "all":
        raise HTTPException(400, "站点标识只能用小写字母、数字和 -，以字母或数字开头，最长 32 位（例如 office）")
    if db.get(Site, slug) is not None:
        raise HTTPException(400, "站点标识已存在")
    if len(_rows(db)) >= MAX_SITES:
        raise HTTPException(400, f"最多 {MAX_SITES} 个站点")
    for o in req.others:
        row = db.get(Site, o.slug)
        if row is None:
            raise HTTPException(400, "站点不存在")
        row.sources = _clean_sources(o.sources)
    sort = max((r.sort or 0 for r in _rows(db)), default=0) + 1
    db.add(Site(slug=slug, name=req.name.strip(), sources=_clean_sources(req.sources),
                platform_addr=req.platform_addr.strip() or None, enabled=int(req.enabled), sort=sort,
                ros_verify_tls=0, created=int(time.time())))
    _apply(db)
    oplog.log(db, request, user, "site_add", {"slug": slug, **req.model_dump()})
    return _dict(db.get(Site, slug), full=True)


@router.put("/{slug}")
def edit_site(slug: str, req: SiteIn, request: Request, user: str = Depends(require_admin),
              db: Session = Depends(get_db)):
    r = db.get(Site, slug)
    if r is None:
        raise HTTPException(404, "站点不存在")
    r.name = req.name.strip()
    r.sources = _clean_sources(req.sources)
    r.platform_addr = req.platform_addr.strip() or None
    r.enabled = int(req.enabled)
    if not any(x.enabled for x in _rows(db)):
        raise HTTPException(400, "至少要有一个启用的站点")
    _apply(db)
    oplog.log(db, request, user, "site_edit", {"slug": slug, **req.model_dump()})
    return _dict(r, full=True)


@router.delete("/{slug}")
def delete_site(slug: str, req: SiteDelete, request: Request, user: str = Depends(require_admin),
                db: Session = Depends(get_db)):
    """删除站点和它的全部数据（流量、终端、命名、人员、访问日志、审计事件……）。默认站点不能删，可以停用"""
    r = db.get(Site, slug)
    if r is None:
        raise HTTPException(404, "站点不存在")
    if slug == DEFAULT_SITE:
        raise HTTPException(400, "默认站点不能删除，可以改名或停用")
    if req.confirm != slug:
        raise HTTPException(400, "确认的站点标识不对")
    if not any(x.enabled for x in _rows(db) if x.slug != slug):
        raise HTTPException(400, "至少要保留一个启用的站点")
    counts = {}
    for m in SITE_MODELS:
        res = db.execute(delete(m).where(m.site == slug), execution_options={"all_sites": True})
        counts[m.__tablename__] = res.rowcount or 0
    db.execute(delete(UserSite).where(UserSite.site == slug))
    db.execute(delete(AuditRule).where(AuditRule.site == slug))
    db.execute(delete(CustomRule).where(CustomRule.site == slug))
    row = db.get(Setting, integrations.SITE_KEY)
    if row is not None and row.value == slug:
        row.value = DEFAULT_SITE
    db.delete(r)
    db.commit()
    registry.load(db)
    from app.audit import auditor
    from app.engine import engine
    from app import people
    auditor.reload()
    engine.reload_rules()
    people.forget()
    with database.session() as s:
        integrations.apply(dict(s.query(Setting.key, Setting.value).filter(
            Setting.key.in_((*integrations.KEYS, integrations.SITE_KEY))).all()))
    oplog.log(db, request, user, "site_delete", {"slug": slug, "name": r.name, "rows": counts})
    db.commit()
    return {"ok": True, "rows": counts}


@router.get("/unknown-sources")
def unknown_sources(_: str = Depends(require_admin), db: Session = Depends(get_db)):
    """没对上任何站点、被丢弃的数据来源（最近 7 天），以及各站点最近实际收到数据的来源 IP（登记源 IP 时点选用）"""
    merged: dict[tuple, dict] = {}
    for u in db.scalars(select(UnknownSource)):
        merged[(u.ip, u.kind)] = {"ip": u.ip, "kind": u.kind, "last_seen": u.last_seen, "packets": u.packets}
    for u in registry.unknown_snapshot():   # 还没落库的这一分钟
        m = merged.setdefault((u["ip"], u["kind"]), {**u, "packets": 0})
        m["packets"] += u["packets"]
        m["last_seen"] = max(m["last_seen"], u["last_seen"])
    seen = []
    for slug, e in registry.engines.items():
        for kind, src in (("ipfix", e.stats.get("exporters") or {}), ("tzsp", e.stats.get("tzsp_sources") or {})):
            for ip, ts in src.items():
                seen.append({"site": slug, "ip": ip, "kind": kind, "last_seen": ts})
    return {"unknown": sorted(merged.values(), key=lambda x: -x["last_seen"]),
            "seen": sorted(seen, key=lambda x: -x["last_seen"])}


@router.get("/overview")
def overview(request: Request, user: str = Depends(current_user), db: Session = Depends(get_db)):
    """“全部站点”总览：每个能看的站点一张卡片。各站点的数各算各的，不相加"""
    from app import stats, timeutil
    from app.scoping import set_site
    vis = set(visible_sites(request, user))
    t0, t1 = timeutil.range_bounds("today")
    out = []
    for r in _rows(db):
        if r.slug not in vis:
            continue
        set_site(db, r.slug)
        e, p = registry.get(r.slug), registry.poller(r.slug)
        wan = p is not None and p.enabled and p.ok and len(p.samples) >= 2
        rate = p.wan_rate if wan else (e.total_rate if e else (0.0, 0.0))
        apps = stats.top_apps(db, t0, t1, limit=5)
        out.append({**_dict(r), "rate_up": rate[0], "rate_down": rate[1], "rate_source": "wan" if wan else "flow",
                    "today": stats.total(db, t0, t1), "online": stats.online_count(db),
                    "apps": [{"id": a["id"], "name": a["name"], "name_en": a["name_en"], "group": a["group"],
                              "total": a["total"]} for a in apps]})
    set_site(db, None)
    return {"sites": out}
