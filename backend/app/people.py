"""人员与部门：设备归属、按人汇总的辅助函数（审计规则、访问日志、报表都会用到）"""
import time

from sqlalchemy import select

from app import database
from app.models import Department, Person, PersonDevice

_cache: dict = {"t": 0, "dev": {}, "people": {}, "depts": {}}


def load(db=None, force: bool = False) -> dict:
    """{dev: host -> person_id, people: id -> {id,name,dept_id}, depts: id -> name}，缓存 30 秒"""
    if not force and time.time() - _cache["t"] < 30:
        return _cache
    own = db is None
    if own:
        if not database.is_configured():
            return _cache
        db = database.SessionLocal()
    try:
        _cache["dev"] = {d.host: d.person_id for d in db.scalars(select(PersonDevice))}
        _cache["people"] = {p.id: {"id": p.id, "name": p.name, "dept_id": p.dept_id} for p in db.scalars(select(Person))}
        _cache["depts"] = {d.id: d.name for d in db.scalars(select(Department))}
        _cache["t"] = time.time()
    finally:
        if own:
            db.close()
    return _cache


def forget():
    _cache["t"] = 0


def hosts_of_person(pid: int, db=None) -> list[str]:
    return sorted(h for h, p in load(db)["dev"].items() if p == pid)


def hosts_of_dept(did: int, db=None) -> list[str]:
    c = load(db)
    pids = {p["id"] for p in c["people"].values() if p["dept_id"] == did}
    return sorted(h for h, p in c["dev"].items() if p in pids)


def person_of(host: str) -> dict | None:
    c = load()
    pid = c["dev"].get(host)
    p = c["people"].get(pid) if pid else None
    if not p:
        return None
    return {"id": p["id"], "name": p["name"], "dept_id": p["dept_id"], "dept": c["depts"].get(p["dept_id"])}


def expand_scope(tokens) -> set[str]:
    """审计规则的适用范围：终端 key、person:<id>、dept:<id> 混合，展开成终端 key 集合；空 = 全部"""
    out: set[str] = set()
    for t in tokens or []:
        if t.startswith("person:"):
            out.update(hosts_of_person(int(t[7:])))
        elif t.startswith("dept:"):
            out.update(hosts_of_dept(int(t[5:])))
        elif t:
            out.add(t)
    if tokens and not out:
        out.add("-")  # 选了人员 / 部门但还没有设备：什么都不匹配，而不是变成“全部终端”
    return out


def scope_hosts(person: int | None, dept: int | None, host: str | None = None) -> list[str] | None:
    """接口筛选参数 → 终端列表；都没给返回 None（不限）"""
    if host:
        return [host]
    if person:
        return hosts_of_person(person) or ["-"]
    if dept:
        return hosts_of_dept(dept) or ["-"]
    return None
