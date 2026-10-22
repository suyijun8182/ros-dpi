import json
import time

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import devtype, insight, oplog, people, stats, timeutil
from app.database import get_db
from app.models import Department, Host, Person, PersonDevice, Setting, TrafficDay
from app.security import current_user

router = APIRouter(prefix="/api", tags=["people"], dependencies=[Depends(current_user)])
RANGES = "^(today|yesterday|week|month|last7|last30)$"


class DeptIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)


class PersonIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    dept_id: int                             # 成员必须属于一个分组 / 部门（debug11）
    note: str | None = Field(None, max_length=255)
    hosts: list[str] | None = None          # 给了就整体替换这个人的设备


class BindIn(BaseModel):
    host: str = Field(min_length=1, max_length=64)
    person_id: int | None = None            # 空 = 解除归属


class DtypeIn(BaseModel):
    dtype: str | None = Field(None, pattern="^(" + "|".join(devtype.TYPES) + ")$")


class AnalysisIn(BaseModel):
    scenario: str | None = Field(None, pattern="^(home|enterprise)$")
    work_days: str | None = Field(None, max_length=7)
    work: list[list[str]] | None = None
    leisure: list[str] | None = None
    night: list[str] | None = None
    limits: dict[str, int] | None = None


def _bounds(rng):
    return timeutil.range_bounds(rng)


def _set_devices(db, pid: int, hosts: list[str]):
    for d in db.scalars(select(PersonDevice).where(PersonDevice.person_id == pid)):
        db.delete(d)
    db.flush()
    for h in dict.fromkeys(hosts):
        old = db.get(PersonDevice, h)
        if old:
            old.person_id = pid
        else:
            db.add(PersonDevice(host=h, person_id=pid))


def _check_person(db, req: PersonIn, pid: int | None = None):
    """分组 / 部门必须存在；同一分组里不能重名"""
    if not db.get(Department, req.dept_id):
        raise HTTPException(400, "请选择分组 / 部门")
    name = req.name.strip()
    if not name:
        raise HTTPException(400, "请填写名称")
    dup = db.scalar(select(Person).where(Person.dept_id == req.dept_id, Person.name == name, Person.id != (pid or 0)))
    if dup:
        raise HTTPException(400, f"这个分组 / 部门里已经有“{name}”了")


def _person_dict(p: Person, c: dict) -> dict:
    return {"id": p.id, "name": p.name, "dept_id": p.dept_id, "dept": c["depts"].get(p.dept_id), "note": p.note,
            "created": p.created}


# ---------------- 人员 / 部门 ----------------

@router.get("/people/meta")
def people_meta(db: Session = Depends(get_db)):
    """选择器用：部门、人员、场景"""
    c = people.load(db, force=True)
    cfg = insight.get_config(db)
    return {"scenario": cfg["scenario"],
            "departments": [{"id": k, "name": v} for k, v in sorted(c["depts"].items(), key=lambda x: x[1])],
            "people": sorted(({**p, "dept": c["depts"].get(p["dept_id"]),
                               "devices": sum(1 for x in c["dev"].values() if x == p["id"])} for p in c["people"].values()),
                             key=lambda p: p["name"])}


@router.get("/people")
def people_list(range: str = Query("today", pattern=RANGES), db: Session = Depends(get_db)):
    """人员列表：设备、本期流量、在线时长、工作 / 学习时间娱乐占比、最近 7 天的行为标签"""
    c = people.load(db, force=True)
    start, end = _bounds(range)
    groups = {p: people.hosts_of_person(p, db) for p in c["people"]}
    all_hosts = sorted({h for hs in groups.values() for h in hs})
    meta = stats.host_meta(db, all_hosts)
    t = TrafficDay
    by_host = {h: (int(u), int(d)) for h, u, d in db.execute(
        select(t.host, func.sum(t.up), func.sum(t.down)).where(t.ts >= start, t.ts < end, t.host.in_(all_hosts or ["-"]))
        .group_by(t.host))}
    cfg = insight.get_config(db)
    use = insight.analyze_many(db, groups, start, end, cfg)
    w0, w1 = timeutil.range_bounds("last7")
    week = insight.analyze_many(db, groups, w0, w1, cfg)
    rows = []
    for pid, p in c["people"].items():
        hs = groups[pid]
        up = sum(by_host.get(h, (0, 0))[0] for h in hs)
        down = sum(by_host.get(h, (0, 0))[1] for h in hs)
        u = use[pid]
        rows.append({**p, "dept": c["depts"].get(p["dept_id"]), "devices": [meta[h] for h in hs],
                     "online": any(meta[h]["online"] for h in hs), "up": up, "down": down, "total": up + down,
                     "online_seconds": u["online"], "work_online": u["work_online"], "leisure_work": u["leisure_work"],
                     "efficiency": u["efficiency"], "apps": [{k: a[k] for k in ("id", "name", "name_en", "category", "seconds")}
                                                             for a in u["apps"][:3]],
                     "tags": week[pid]["tags"]})
    rows.sort(key=lambda r: (-r["online"], -r["total"], r["name"]))
    bound = set(c["dev"])
    unassigned = [h for h in stats.all_hosts(db) if h["key"] not in bound]
    return {"scenario": cfg["scenario"], "departments": [{"id": k, "name": v} for k, v in c["depts"].items()],
            "people": rows, "unassigned": unassigned[:300]}


@router.post("/people")
def add_person(req: PersonIn, request: Request, user: str = Depends(current_user), db: Session = Depends(get_db)):
    _check_person(db, req)
    p = Person(name=req.name.strip(), dept_id=req.dept_id, note=req.note, created=int(time.time()))
    db.add(p)
    db.flush()
    if req.hosts is not None:
        _set_devices(db, p.id, req.hosts)
    oplog.log(db, request, user, "person_add", {"name": p.name, "hosts": req.hosts})
    people.forget()
    return _person_dict(p, people.load(db, force=True))


@router.put("/people/{pid}")
def edit_person(pid: int, req: PersonIn, request: Request, user: str = Depends(current_user), db: Session = Depends(get_db)):
    p = db.get(Person, pid)
    if p is None:
        raise HTTPException(404, "人员不存在")
    _check_person(db, req, pid)
    p.name, p.dept_id, p.note = req.name.strip(), req.dept_id, req.note
    if req.hosts is not None:
        _set_devices(db, pid, req.hosts)
    oplog.log(db, request, user, "person_edit", {"id": pid, "name": p.name, "hosts": req.hosts})
    people.forget()
    return _person_dict(p, people.load(db, force=True))


@router.delete("/people/{pid}")
def delete_person(pid: int, request: Request, user: str = Depends(current_user), db: Session = Depends(get_db)):
    p = db.get(Person, pid)
    if p is None:
        raise HTTPException(404, "人员不存在")
    for d in db.scalars(select(PersonDevice).where(PersonDevice.person_id == pid)):
        db.delete(d)
    name = p.name
    db.delete(p)
    oplog.log(db, request, user, "person_delete", {"id": pid, "name": name})
    people.forget()
    return {"ok": True}


@router.put("/devices/bind")
def bind(req: BindIn, request: Request, user: str = Depends(current_user), db: Session = Depends(get_db)):
    """设置一台设备属于谁（主机详情、未分配设备列表里用）"""
    old = db.get(PersonDevice, req.host)
    if req.person_id is None:
        if old:
            db.delete(old)
    else:
        if not db.get(Person, req.person_id):
            raise HTTPException(404, "人员不存在")
        if old:
            old.person_id = req.person_id
        else:
            db.add(PersonDevice(host=req.host, person_id=req.person_id))
    oplog.log(db, request, user, "person_bind", {"host": req.host, "person_id": req.person_id})
    people.forget()
    return {"ok": True, "person": people.person_of(req.host) if req.person_id else None}


@router.post("/departments")
def add_dept(req: DeptIn, request: Request, user: str = Depends(current_user), db: Session = Depends(get_db)):
    if db.scalar(select(Department).where(Department.name == req.name.strip())):
        raise HTTPException(400, "名称已存在")
    if not req.name.strip():
        raise HTTPException(400, "请填写名称")
    d = Department(name=req.name.strip())
    db.add(d)
    oplog.log(db, request, user, "dept_add", {"name": d.name})
    people.forget()
    return {"id": d.id, "name": d.name}


@router.put("/departments/{did}")
def edit_dept(did: int, req: DeptIn, request: Request, user: str = Depends(current_user), db: Session = Depends(get_db)):
    d = db.get(Department, did)
    if d is None:
        raise HTTPException(404, "部门不存在")
    if db.scalar(select(Department).where(Department.name == req.name.strip(), Department.id != did)):
        raise HTTPException(400, "名称已存在")
    d.name = req.name.strip()
    oplog.log(db, request, user, "dept_edit", {"id": did, "name": d.name})
    people.forget()
    return {"id": d.id, "name": d.name}


@router.delete("/departments/{did}")
def delete_dept(did: int, request: Request, user: str = Depends(current_user), db: Session = Depends(get_db)):
    d = db.get(Department, did)
    if d is None:
        raise HTTPException(404, "部门不存在")
    n = db.scalar(select(func.count()).select_from(Person).where(Person.dept_id == did)) or 0
    if n:
        raise HTTPException(400, f"“{d.name}”下还有 {n} 个成员，先把他们移到别的分组或删除")
    name = d.name
    db.delete(d)
    oplog.log(db, request, user, "dept_delete", {"id": did, "name": name})
    people.forget()
    return {"ok": True}


# ---------------- 人员详情 ----------------

@router.get("/people/{pid}/detail")
def person_detail(pid: int, range: str = Query("today", pattern=RANGES), db: Session = Depends(get_db)):
    p = db.get(Person, pid)
    if p is None:
        raise HTTPException(404, "人员不存在")
    c = people.load(db, force=True)
    hs = people.hosts_of_person(pid, db)
    start, end = _bounds(range)
    cfg = insight.get_config(db)
    key = hs or ["-"]
    apps = stats.top_apps(db, start, end, host=key)
    cats = stats.top_categories(apps)
    gran = "hour" if range in ("today", "yesterday") else "day"
    w0, w1 = timeutil.range_bounds("last7")
    return {
        **_person_dict(p, c), "scenario": cfg["scenario"], "config": cfg,
        "devices": list(stats.host_meta(db, hs).values()),
        "totals": stats.totals3(db, host=key), "range_total": stats.total(db, start, end, host=key),
        "apps": apps[:50], "groups": stats.top_groups(cats),
        "trend": stats.trend(db, gran, start, end, host=key),
        "trend_groups": stats.trend_groups(db, gran, start, end, host=key),
        "usage": insight.analyze_hosts(db, hs, start, end, cfg),
        "week": insight.analyze_hosts(db, hs, w0, w1, cfg),
    }


@router.get("/hosts/{key}/insight")
def host_insight(key: str, range: str = Query("today", pattern=RANGES), db: Session = Depends(get_db)):
    """单台终端的上网时长和行为标签（终端详情用）"""
    start, end = _bounds(range)
    cfg = insight.get_config(db)
    w0, w1 = timeutil.range_bounds("last7")
    return {"scenario": cfg["scenario"], "usage": insight.analyze_hosts(db, [key], start, end, cfg),
            "week": insight.analyze_hosts(db, [key], w0, w1, cfg), "person": people.person_of(key)}


@router.put("/hosts/{key}/dtype")
def set_dtype(key: str, req: DtypeIn, request: Request, user: str = Depends(current_user), db: Session = Depends(get_db)):
    h = db.get(Host, key)
    if h is None:
        raise HTTPException(404, "终端不存在")
    h.dtype = req.dtype
    oplog.log(db, request, user, "host_dtype", {"host": key, "dtype": req.dtype})
    return {"dtype": h.dtype or h.dtype_auto or "unknown", "dtype_manual": h.dtype}


# ---------------- 行为洞察 ----------------

@router.get("/insights")
def insights(db: Session = Depends(get_db)):
    """最近 7 天：每个人的标签、效率排行；也给出没有归属的设备的标签（家里可能还没把设备分给人）"""
    c = people.load(db, force=True)
    cfg = insight.get_config(db)
    w0, w1 = timeutil.range_bounds("last7")
    groups = {f"p{p}": people.hosts_of_person(p, db) for p in c["people"]}
    res = insight.analyze_many(db, groups, w0, w1, cfg)
    subjects = []
    for pid, p in c["people"].items():
        r = res[f"p{pid}"]
        subjects.append({"kind": "person", "id": pid, "name": p["name"], "dept": c["depts"].get(p["dept_id"]),
                         "online": r["online"], "work_online": r["work_online"], "leisure_work": r["leisure_work"],
                         "efficiency": r["efficiency"], "night": r["night"], "game": r["game"],
                         "short_video": r["short_video"], "tags": r["tags"], "days": r["days"]})
    return {"scenario": cfg["scenario"], "config": cfg, "start": w0, "end": w1, "subjects": subjects}


# ---------------- 分析设置（场景、工作 / 学习时间、上限） ----------------

@router.get("/analysis/settings")
def get_analysis(db: Session = Depends(get_db)):
    from app.engine import engine
    cl = engine.classifier
    return {"config": insight.get_config(db), "scenarios": insight.SCENARIOS,
            "choices": [{"id": k, "name": v["name"], "name_en": v["name_en"], "kind": "group"} for k, v in cl.groups.items()]
            + [{"id": k, "name": v["name"], "name_en": v["name_en"], "kind": "category"} for k, v in cl.categories.items()]}


@router.put("/analysis/settings")
def put_analysis(req: AnalysisIn, request: Request, user: str = Depends(current_user), db: Session = Depends(get_db)):
    cur = insight.get_config(db)
    body = req.model_dump(exclude_none=True)
    if body.get("scenario") and body["scenario"] != cur["scenario"] and set(body) == {"scenario"}:
        merged = {"scenario": body["scenario"]}          # 只换场景：其余用新场景的默认值
    else:
        merged = {**cur, **body}
    try:
        cfg = insight.check_config(merged)
    except (ValueError, KeyError, TypeError) as e:
        raise HTTPException(400, str(e) or "设置无效")
    row = db.get(Setting, "analysis")
    if row is None:
        db.add(Setting(key="analysis", value=json.dumps(cfg, ensure_ascii=False)))
    else:
        row.value = json.dumps(cfg, ensure_ascii=False)
    oplog.log(db, request, user, "analysis_settings", cfg)
    insight.clear_cache()
    return {"config": cfg}


@router.post("/devtype/refresh")
def devtype_refresh(request: Request, user: str = Depends(current_user), db: Session = Depends(get_db)):
    n = devtype.refresh_all()
    return {"changed": n, "oui": devtype.oui.status()}
