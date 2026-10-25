"""社区主站的公开端点（0.6.21 重做，见 app/share.py）。只有 SHARE_HUB=true 的实例开放，其它实例一律 404。

- POST /api/share/v1/register   首次注册，领取实例 ID 和令牌
- POST /api/share/v1/report     心跳 + 投票（Authorization: Bearer <实例ID>:<令牌>，可 gzip）
- GET  /api/share/v1/library    社区库（ETag / 304，支持 gzip）
- GET  /api/share/v1/stats      全球部署量：已部署 / 在线 / 离线（所有人可见）
"""
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from app import database, share

router = APIRouter(prefix=share.API, tags=["share"])


def _need_hub():
    if not share.is_hub():
        raise HTTPException(404, "本实例不是社区主站")
    if not database.is_configured():
        raise HTTPException(503, "社区主站的数据库还没就绪")


def _source(request: Request) -> str:
    return share.client_ip(request.client.host if request.client else "", request.headers.get("x-forwarded-for"),
                           request.headers.get("x-real-ip"))


def _run(fn):
    try:
        return fn()
    except share.ShareError as e:
        raise HTTPException(e.status, e.detail) from None


@router.post("/register")
async def register(request: Request):
    _need_hub()
    if int(request.headers.get("content-length") or 0) > share.MAX_BODY:
        raise HTTPException(413, "请求内容太大")
    raw = await request.body()
    ip = _source(request)

    def work():
        body = share.inflate(raw, request.headers.get("content-encoding"))
        with database.session() as db:
            iid, token = share.register(db, share.net_of(db, ip), str(body.get("version") or ""))
            db.commit()
        return {"instance": iid, "token": token}
    return await run_in_threadpool(_run, work)


@router.post("/report")
async def report(request: Request):
    _need_hub()
    if int(request.headers.get("content-length") or 0) > share.MAX_BODY:
        raise HTTPException(413, "上报内容太大")
    raw = await request.body()
    ip = _source(request)

    def work():
        from app.engine import engine
        body = share.inflate(raw, request.headers.get("content-encoding"))
        with database.session() as db:
            row = share.authenticate(db, request.headers.get("authorization"))
            res = share.report(db, row, share.net_of(db, ip), body, engine.classifier)
            db.commit()
        return res
    return await run_in_threadpool(_run, work)


@router.get("/library")
def library(request: Request):
    _need_hub()
    with database.session() as db:
        lib = share.library(db)
    headers = {"ETag": lib["etag"], "Cache-Control": "no-cache"}
    if request.headers.get("if-none-match") == lib["etag"]:
        return Response(status_code=304, headers=headers)
    if "gzip" in (request.headers.get("accept-encoding") or "").lower():
        return Response(lib["gzip"], media_type="application/json", headers={**headers, "Content-Encoding": "gzip"})
    return Response(lib["json"], media_type="application/json", headers=headers)


@router.get("/stats")
def stats():
    _need_hub()
    with database.session() as db:
        return JSONResponse(share.stats(db), headers={"Access-Control-Allow-Origin": "*"})
