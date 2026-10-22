"""合规（Syslog 外发、留存天数、数据库占用）和管控命令生成"""
import json

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import compliance, control, oplog, people, sharing, stats
from app.database import get_db
from app.engine import engine
from app.models import Setting
from app.security import current_user

router = APIRouter(prefix="/api", tags=["compliance"], dependencies=[Depends(current_user)])


class SyslogIn(BaseModel):
    enabled: bool = False
    host: str = Field("", max_length=255)
    port: int = Field(514, ge=1, le=65535)
    proto: str = Field("udp", pattern="^(udp|tcp)$")
    facility: int = Field(16, ge=0, le=23)
    access: bool = True
    events: bool = True


class RetentionIn(BaseModel):
    minute: int | None = Field(None, ge=1, le=30)
    hour: int | None = Field(None, ge=1, le=400)
    day: int | None = Field(None, ge=30, le=3650)
    domain: int | None = Field(None, ge=1, le=400)
    log: int | None = Field(None, ge=1, le=400)
    event: int | None = Field(None, ge=1, le=3650)


class ComplianceIn(BaseModel):
    syslog: SyslogIn | None = None
    retention: RetentionIn | None = None


def _save(db, key: str, val: dict):
    row = db.get(Setting, key)
    v = json.dumps(val, ensure_ascii=False)
    if row is None:
        db.add(Setting(key=key, value=v))
    else:
        row.value = v


@router.get("/compliance")
def get_compliance():
    return {"syslog": compliance.syslog_config(), "retention": compliance.retention(), "usage": compliance.db_usage()}


@router.put("/compliance")
def put_compliance(req: ComplianceIn, request: Request, user: str = Depends(current_user), db: Session = Depends(get_db)):
    if req.syslog:
        if req.syslog.enabled and not req.syslog.host.strip():
            raise HTTPException(400, "请填写 Syslog 服务器地址")
        _save(db, "syslog", req.syslog.model_dump())
    if req.retention:
        _save(db, "retention", req.retention.model_dump(exclude_none=True))
    oplog.log(db, request, user, "compliance", req.model_dump(exclude_none=True))
    compliance.forget()
    return get_compliance()


@router.post("/compliance/syslog-test")
def syslog_test(req: SyslogIn):
    if not req.host.strip():
        raise HTTPException(400, "请填写 Syslog 服务器地址")
    try:
        compliance.test_syslog(req.model_dump())
    except OSError as e:
        raise HTTPException(400, f"发送失败：{e}")
    return {"ok": True}


@router.get("/sharing")
def sharing_list(db: Session = Depends(get_db)):
    """私接路由 / 共享上网嫌疑（今天的数据）"""
    base, rows = sharing.suspects(engine.ttl_snapshot())
    meta = stats.host_meta(db, [r["host"] for r in rows])
    return {"base_hops": base, "hosts": len(engine.ttl), "rows": [{**r, "meta": meta[r["host"]]} for r in rows]}


class ControlIn(BaseModel):
    target: str = Field(pattern="^(person|dept|host)$")
    target_id: str = Field(min_length=1, max_length=64)
    action: str = Field(pattern="^(block_app|block_all|limit)$")
    apps: list[str] = []
    groups: list[str] = []
    days: str = Field("1234567", pattern="^[1-7]{1,7}$")
    time_from: str = Field("00:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    time_to: str = Field("24:00", pattern=r"^(([01]\d|2[0-3]):[0-5]\d|24:00)$")
    block_quic: bool = True
    up_mbps: float = Field(0, ge=0, le=100000)
    down_mbps: float = Field(0, ge=0, le=100000)


@router.post("/control/script")
def control_script(req: ControlIn, request: Request, user: str = Depends(current_user), db: Session = Depends(get_db)):
    """生成 RouterOS 管控命令（只生成，不下发）"""
    if req.target == "host":
        hosts, label = [req.target_id], ""
    elif req.target == "person":
        hosts = people.hosts_of_person(int(req.target_id), db)
        label = (people.load(db)["people"].get(int(req.target_id)) or {}).get("name", "")
    else:
        hosts = people.hosts_of_dept(int(req.target_id), db)
        label = people.load(db)["depts"].get(int(req.target_id), "")
    if not hosts:
        raise HTTPException(400, "还没有给这个人员 / 部门分配设备")
    meta = stats.host_meta(db, hosts)
    if req.target == "host":
        label = meta[req.target_id]["name"]
    try:
        res = control.build(db, list(meta.values()), req.action, req.apps, req.groups, req.days, req.time_from,
                            req.time_to, req.block_quic, req.up_mbps, req.down_mbps, label)
    except ValueError as e:
        raise HTTPException(400, str(e))
    oplog.log(db, request, user, "control_script", {"target": f"{req.target}:{req.target_id}", "action": req.action,
                                                     "tag": res["tag"]})
    return res
