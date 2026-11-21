"""多站点（0.7.0）：会话级的站点过滤。

请求进来时 site_ctx 把站点写进 db.info["site"]，之后这个会话里：
- 所有 ORM 查询（select / update / delete，包括 select(Model.col) 这种）自动加上 Model.site == 站点，
  不用在每个查询里手写（漏写一个就会把别的站点的数据带出来）；
- 新建的按站点隔离的对象（db.add）自动填上站点。

没有设置站点的会话（后台任务、全站重算、清理）不过滤；要跨站点查询时用
db.execute(stmt, execution_options={"all_sites": True})。
Core 语句（Model.__table__ 上的 insert / upsert）不受影响，由调用方显式写 site。
"""
from sqlalchemy import event
from sqlalchemy.orm import Session, with_loader_criteria

from app.models import (DEFAULT_SITE, AccessLog, AccuracyProbe, AuditEvent, Department, Host, HostDomainDay, HostName,
                        Person, PersonDevice, TrafficDay, TrafficHour, TrafficMinute, UnmatchedDay)

SITE_MODELS = (TrafficMinute, TrafficHour, TrafficDay, HostDomainDay, UnmatchedDay, Host, HostName, PersonDevice,
               AccessLog, AuditEvent, Person, Department, AccuracyProbe)


def site_of(db) -> str:
    return db.info.get("site") or DEFAULT_SITE


def set_site(db, slug: str | None):
    if slug:
        db.info["site"] = slug
    else:
        db.info.pop("site", None)
    return db


@event.listens_for(Session, "do_orm_execute")
def _filter_by_site(state):
    site = state.session.info.get("site")
    if not site or state.execution_options.get("all_sites"):
        return
    if not (state.is_select or state.is_update or state.is_delete):
        return
    state.statement = state.statement.options(
        *(with_loader_criteria(m, lambda cls: cls.site == site, include_aliases=True) for m in SITE_MODELS))


@event.listens_for(Session, "before_flush")
def _stamp_site(session, _ctx, _instances):
    site = session.info.get("site")
    if not site:
        return
    for obj in session.new:
        if isinstance(obj, SITE_MODELS) and not obj.site:
            obj.site = site
