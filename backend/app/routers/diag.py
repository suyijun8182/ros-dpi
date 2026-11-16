"""识别校验与抓包采样（0.6.29）。"""
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import accuracy, oplog, stats
from app.capture import MAX_MINUTES, capture
from app.capture import delete as delete_capture
from app.capture import files as capture_files
from app.capture import path_of
from app.database import get_db
from app.engine import engine
from app.models import AccuracyProbe, Host
from app.security import current_user, require_admin

router = APIRouter(prefix="/api", tags=["diag"], dependencies=[Depends(current_user)])
MAX_RUNNING = 5
MAX_PROBES = 200


# ---------- 识别校验 ----------
class ProbeIn(BaseModel):
    host: str = Field(min_length=1, max_length=64)
    expected: str = Field(min_length=1, max_length=48)
    back: int | None = Field(None, ge=1, le=360)   # 不填：从现在开始；填了：校验刚过去的 N 分钟
    note: str | None = Field(None, max_length=128)


def _probe_out(db, p: AccuracyProbe, now: float) -> dict:
    if not p.end and now - p.start > accuracy.MAX_SPAN:
        p.end = p.start + accuracy.MAX_SPAN   # 忘了点结束：最长 6 小时
    v = accuracy.view(db, engine.classifier, p, now)
    v["expected"] = stats.app_meta(p.expected)
    v["apps"] = [{**a, "app": stats.app_meta(a["app"])} for a in v["apps"]]
    return v


@router.get("/accuracy/probes")
def list_probes(db: Session = Depends(get_db)):
    now = time.time()
    rows = db.query(AccuracyProbe).order_by(AccuracyProbe.id.desc()).limit(MAX_PROBES).all()
    items = [_probe_out(db, p, now) for p in rows]
    meta = stats.host_meta(db, {p.host for p in rows})
    for it in items:
        it["host"] = meta.get(it["host"]) or {"key": it["host"], "name": it["host"]}
    db.commit()   # 冻结了结果的要存下来
    return {"items": items, "summary": accuracy.summary(items)}


@router.post("/accuracy/probes")
def add_probe(req: ProbeIn, request: Request, user: str = Depends(require_admin), db: Session = Depends(get_db)):
    if db.get(Host, req.host) is None:
        raise HTTPException(400, "终端不存在")
    if req.expected not in engine.classifier.apps:
        raise HTTPException(400, "应用不存在")
    now = int(time.time())
    if req.back is None and db.query(AccuracyProbe).filter(AccuracyProbe.end.is_(None)).count() >= MAX_RUNNING:
        raise HTTPException(400, f"同时进行的校验最多 {MAX_RUNNING} 个，请先结束一些")
    p = AccuracyProbe(host=req.host, expected=req.expected, note=(req.note or "").strip() or None, created_by=user,
                      start=now - req.back * 60 if req.back else now, end=now if req.back else None)
    db.add(p)
    oplog.log(db, request, user, "accuracy_add", {"host": req.host, "expected": req.expected, "back": req.back})
    return _probe_out(db, p, now)


@router.post("/accuracy/probes/{pid}/stop")
def stop_probe(pid: int, request: Request, user: str = Depends(require_admin), db: Session = Depends(get_db)):
    p = db.get(AccuracyProbe, pid)
    if p is None:
        raise HTTPException(404, "校验不存在")
    if not p.end:
        p.end = int(time.time())
        oplog.log(db, request, user, "accuracy_stop", {"id": pid})
    return _probe_out(db, p, time.time())


@router.delete("/accuracy/probes/{pid}")
def delete_probe(pid: int, request: Request, user: str = Depends(require_admin), db: Session = Depends(get_db)):
    p = db.get(AccuracyProbe, pid)
    if p is None:
        raise HTTPException(404, "校验不存在")
    db.delete(p)
    oplog.log(db, request, user, "accuracy_delete", {"id": pid})
    return {"ok": True}


# ---------- 抓包采样（只给管理员；GET 在 security.ADMIN_ONLY_GET 里） ----------
class CaptureIn(BaseModel):
    minutes: int = Field(10, ge=1, le=MAX_MINUTES)


@router.get("/diag/capture")
def capture_status(_: str = Depends(require_admin)):
    from app.config import get_settings
    from app.ros_poller import poller
    chk = poller.check()   # 用 RouterOS 上已经在工作的 DNS 镜像规则的目标地址 / 端口，生成临时嗅探规则
    return {**capture.status(), "files": capture_files(),
            "target": chk.get("target"), "target_port": chk.get("port") or get_settings().tzsp_port}


@router.post("/diag/capture/start")
def capture_start(req: CaptureIn, request: Request, user: str = Depends(require_admin), db: Session = Depends(get_db)):
    try:
        st = capture.start(engine, req.minutes, user)
    except RuntimeError as e:
        raise HTTPException(409, str(e))
    oplog.log(db, request, user, "capture_start", {"minutes": req.minutes})
    return st


@router.post("/diag/capture/stop")
def capture_stop(request: Request, user: str = Depends(require_admin), db: Session = Depends(get_db)):
    st = capture.stop()
    oplog.log(db, request, user, "capture_stop", {"name": (st.get("last") or {}).get("name")})
    return st


@router.get("/diag/capture/{name}/{kind}")
def capture_download(name: str, kind: str, _: str = Depends(require_admin)):
    p = path_of(name, kind)
    if p is None:
        raise HTTPException(404, "文件不存在")
    media = "application/vnd.tcpdump.pcap" if kind == "pcap" else "text/csv" if kind.endswith("csv") else "application/json"
    return FileResponse(p, media_type=media, filename=f"{name}.{kind}")


@router.delete("/diag/capture/{name}")
def capture_delete(name: str, request: Request, user: str = Depends(require_admin), db: Session = Depends(get_db)):
    if not delete_capture(name):
        raise HTTPException(404, "文件不存在或正在采样")
    oplog.log(db, request, user, "capture_delete", {"name": name})
    return {"ok": True}
