import asyncio
import os
from contextlib import asynccontextmanager

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.collector import start_listeners
from app.config import get_settings
from app.database import SessionLocal, init_db
from app.engine import engine
from app.models import Setting
from app.ros_poller import poller
from app.routers import admin, auth, stats
from app.security import ensure_admin

FRONTEND_DIR = os.environ.get("FRONTEND_DIR", os.path.join(os.path.dirname(__file__), "..", "frontend_dist"))


def _safe(fn, name):
    def run():
        try:
            fn()
        except Exception as e:  # noqa: BLE001
            print(f"[job] {name} 失败：{type(e).__name__}: {e}")
    return run


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    await asyncio.to_thread(init_db)
    ensure_admin()
    engine.load_state()
    with SessionLocal() as db:
        wan = db.get(Setting, "wan_interface")
        poller.wan_override = wan.value if wan and wan.value else ""

    transports = await start_listeners(engine, s.ipfix_port, s.tzsp_port)
    sched = BackgroundScheduler(timezone=s.tz)
    sched.add_job(_safe(engine.flush, "flush"), "cron", second=0, max_instances=1, coalesce=True)
    sched.add_job(_safe(engine.cleanup, "cleanup"), "cron", minute=17, max_instances=1)
    if poller.enabled:
        sched.add_job(_safe(poller.poll, "ros-poll"), "interval", seconds=s.ros_poll_seconds,
                      max_instances=1, coalesce=True)
        await asyncio.to_thread(poller.poll)
    sched.start()
    print(f"[startup] ROS-DPI {__version__} 已启动，Web 端口 {s.http_port}")
    yield
    sched.shutdown(wait=False)
    for t in transports:
        t.close()
    _safe(engine.flush, "flush")()


app = FastAPI(title="ROS-DPI", version=__version__, lifespan=lifespan)


@app.exception_handler(Exception)
async def _unhandled(request: Request, exc: Exception):
    print(f"[error] {request.method} {request.url.path}: {exc!r}")
    msg = (str(exc).splitlines() or [""])[0][:300]
    return JSONResponse(status_code=500, content={"detail": f"服务器内部错误：{type(exc).__name__}: {msg}"})


for r in (auth.router, stats.router, admin.router):
    app.include_router(r)


@app.get("/api/health")
def health():
    return {"ok": True, "version": __version__}


if os.path.isdir(FRONTEND_DIR):
    app.mount("/assets", StaticFiles(directory=os.path.join(FRONTEND_DIR, "assets")), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        root = os.path.realpath(FRONTEND_DIR)
        f = os.path.realpath(os.path.join(root, path))
        if path and f.startswith(root + os.sep) and os.path.isfile(f):
            return FileResponse(f)
        if path.startswith("api/"):
            return JSONResponse(status_code=404, content={"detail": "Not Found"})
        return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))
