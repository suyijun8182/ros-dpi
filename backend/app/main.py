import asyncio
import os
from contextlib import asynccontextmanager

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app import __version__, database
from app.collector import start_listeners
from app.config import get_settings
from app.engine import engine
from app.models import Setting
from app.ros_poller import poller
from app.routers import admin, auth, setup, stats
from app.security import ensure_admin

FRONTEND_DIR = os.environ.get("FRONTEND_DIR", os.path.join(os.path.dirname(__file__), "..", "frontend_dist"))


def _safe(fn, name):
    def run():
        try:
            fn()
        except Exception as e:  # noqa: BLE001
            print(f"[job] {name} 失败：{type(e).__name__}: {e}")
    return run


def _on_db_ready():
    """数据库连接成功后（启动时或安装向导保存后）执行。"""
    ensure_admin()
    engine.load_state()
    with database.session() as db:
        wan = db.get(Setting, "wan_interface")
        poller.wan_override = wan.value if wan and wan.value else ""
    print("[startup] 数据库已连接", flush=True)


def _reconnect():
    # 有配置但连接断开 / 启动时没连上：后台定期重试，不需要用户重走安装向导
    if not database.is_configured() and database.configured_url():
        database.connect_from_saved(force=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    database.add_ready_hook(_on_db_ready)
    if database.configured_url():
        # 放到后台连接，网页可以立刻打开（MySQL 未就绪时会重试约 1 分钟，之后由 _reconnect 接手）
        asyncio.get_running_loop().run_in_executor(None, lambda: database.connect_from_saved(force=True, retries=20))
    else:
        print("[startup] 未配置数据库，请在网页安装向导中填写 MySQL 信息", flush=True)

    transports = await start_listeners(engine, s.ipfix_port, s.tzsp_port)
    sched = BackgroundScheduler(timezone=s.tz)
    sched.add_job(_safe(engine.flush, "flush"), "cron", second=0, max_instances=1, coalesce=True)
    sched.add_job(_safe(engine.cleanup, "cleanup"), "cron", minute=17, max_instances=1)
    sched.add_job(_safe(_reconnect, "db-reconnect"), "interval", seconds=30, max_instances=1, coalesce=True)
    if poller.enabled:
        sched.add_job(_safe(poller.poll, "ros-poll"), "interval", seconds=s.ros_poll_seconds,
                      max_instances=1, coalesce=True)
        asyncio.get_running_loop().run_in_executor(None, poller.poll)
    sched.start()
    print(f"[startup] ROS-DPI {__version__} 已启动，Web 端口 {s.http_port}", flush=True)
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


for r in (setup.router, auth.router, stats.router, admin.router):
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
