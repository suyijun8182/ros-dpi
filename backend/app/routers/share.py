"""社区共享库的中转端点（debug16）：中转实例接收各部署的上报并对外发布聚合库。

- POST /api/share/collect   上报本实例的自学习库（匿名投票：远端 IP → 应用）
- GET  /api/share/library.json   聚合后的社区库（至少 2 个实例见过的映射才发布）
两个端点只在 系统设置里开启「共享中转」时可用；SHARE_TOKEN 环境变量可加一层令牌校验。
"""
from fastapi import APIRouter, HTTPException, Request

from app import database, share
from app.config import get_settings

router = APIRouter(prefix="/share", tags=["share"])


def _hub_on(db) -> bool:
    from app.models import Setting
    row = db.get(Setting, "share_hub")
    return (row.value == "1") if row is not None else get_settings().share_hub


@router.post("/collect")
def collect(req: Request, body: dict):
    s = get_settings()
    with database.session() as db:
        if not _hub_on(db):
            raise HTTPException(404, "本实例未开启共享中转")
        if s.share_token and req.headers.get("x-share-token") != s.share_token:
            raise HTTPException(403, "共享令牌不对")
    reporter = str((body or {}).get("instance") or "")[:36]
    entries = (body or {}).get("entries")
    if not reporter or not isinstance(entries, list):
        raise HTTPException(400, "格式不对：需要 instance 和 entries")
    from app.engine import engine
    with database.session() as db:
        accepted = share.collect(db, reporter, entries, domains, engine.classifier)
        db.commit()
    return {"ok": True, "accepted": accepted}


@router.get("/library.json")
def library_json():
    with database.session() as db:
        if not _hub_on(db):
            raise HTTPException(404, "本实例未开启共享中转")
        return share.published_library(db)


@router.post("/heartbeat")
def heartbeat(req: Request, body: dict):
    """部署心跳（debug16 第 2 条）：只有匿名实例 ID 和版本号，用于全球部署量统计"""
    s = get_settings()
    with database.session() as db:
        if not _hub_on(db):
            raise HTTPException(404, "本实例未开启共享中转")
        if s.share_token and req.headers.get("x-share-token") != s.share_token:
            raise HTTPException(403, "共享令牌不对")
        reporter = str((body or {}).get("instance") or "")[:36]
        if not reporter:
            raise HTTPException(400, "格式不对：需要 instance")
        share.heartbeat(db, reporter, str((body or {}).get("version") or ""),
                        str((body or {}).get("public_url") or ""))
        db.commit()
    return {"ok": True}


@router.get("/deployments")
def deployments():
    """全球部署概况（公开）：已部署总数 / 在线 / 离线"""
    with database.session() as db:
        if not _hub_on(db):
            raise HTTPException(404, "本实例未开启共享中转")
        return share.deployments(db)
