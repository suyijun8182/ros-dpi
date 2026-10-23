import asyncio
import os
from contextlib import asynccontextmanager

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app import __version__, database, integrations
from app.asn import asndb
from app.collector import start_listeners
from app.config import get_settings
from app.engine import engine
from app.models import Setting
from app.ros_poller import poller
from app import audit  # noqa: F401  挂上审计（engine.audit）
from app.routers import admin, auth, setup, stats
from app.routers import audit as audit_router
from app.routers import compliance as compliance_router
from app.routers import people as people_router
from app import devtype
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
        saved = {k: (db.get(Setting, k).value if db.get(Setting, k) else None) for k in integrations.KEYS}
    integrations.apply(saved)
    print("[startup] 数据库已连接", flush=True)


def _auto_update_rules():
    """识别库自动更新（默认开启，可在识别规则页关闭）；更新器内部保证一天最多检查一次"""
    if not database.is_configured():
        return
    from app.classify.updater import updater
    with database.session() as db:
        row = db.get(Setting, "rules_auto_update")
    if row is None or row.value != "0":
        updater.check(reload=engine.reload_classifier)


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
    sched.add_job(_safe(audit.auditor.flush_deferred, "notify-deferred"), "cron", second=30, max_instances=1, coalesce=True)
    sched.add_job(_safe(engine.cleanup, "cleanup"), "cron", minute=17, max_instances=1)
    sched.add_job(_safe(_reconnect, "db-reconnect"), "interval", seconds=30, max_instances=1, coalesce=True)
    # 外部数据源：没配置时 poll() 直接返回
    sched.add_job(_safe(integrations.singbox.poll, "singbox"), "interval", seconds=5, max_instances=1, coalesce=True)
    sched.add_job(_safe(integrations.mosdns.poll, "mosdns"), "interval", seconds=5, max_instances=1, coalesce=True)
    sched.add_job(_safe(_auto_update_rules, "rules-update"), "interval", hours=6, max_instances=1, coalesce=True)
    # 审计报表：日报每天 08:00 推送昨天的，周报每周一 08:30 推送近 7 天的（在审计 → 报表里开启）
    sched.add_job(_safe(lambda: audit.push_report("daily"), "report-daily"), "cron", hour=8, minute=0)
    # 终端类型：每小时按主机名、MAC 厂商、最近用过的应用重新识别；MAC 厂商库每 30 天更新
    sched.add_job(_safe(devtype.refresh_all, "devtype"), "cron", minute=7, max_instances=1, coalesce=True)
    sched.add_job(_safe(devtype.oui.update if s.oui_db else devtype.oui.load, "oui-db"), "interval", hours=24,
                  max_instances=1, coalesce=True)
    asyncio.get_running_loop().run_in_executor(None, _safe(devtype.startup, "devtype-startup"))
    sched.add_job(_safe(lambda: audit.push_report("weekly"), "report-weekly"), "cron", day_of_week="mon", hour=8, minute=30)
    asyncio.get_running_loop().call_later(120, lambda: asyncio.get_running_loop().run_in_executor(
        None, _safe(_auto_update_rules, "rules-update")))
    if s.asn_db:
        sched.add_job(_safe(asndb.update, "asn-db"), "interval", hours=6, max_instances=1, coalesce=True)
        asyncio.get_running_loop().run_in_executor(None, _safe(asndb.update, "asn-db"))
    if poller.enabled:
        sched.add_job(_safe(poller.sample, "ros-rate"), "interval", seconds=max(s.ros_rate_seconds, 2),
                      max_instances=1, coalesce=True)
        sched.add_job(_safe(poller.poll, "ros-poll"), "interval", seconds=s.ros_poll_seconds,
                      max_instances=1, coalesce=True)
        asyncio.get_running_loop().run_in_executor(None, poller.poll)
    if not os.environ.get("ROSDPI_NO_JOBS"):  # 测试里不跑后台任务，避免整点落库打乱测试数据
        sched.start()
    print(f"[startup] ROS-DPI {__version__} 已启动，Web 端口 {s.http_port}", flush=True)
    yield
    if sched.running:
        sched.shutdown(wait=False)
    for t in transports:
        t.close()
    _safe(lambda: engine.flush(final=True), "flush")()  # 关闭前把还没结束的访问也写进访问日志


app = FastAPI(title="ROS-DPI", version=__version__, lifespan=lifespan)


@app.exception_handler(Exception)
async def _unhandled(request: Request, exc: Exception):
    # 详情只进日志；返回给客户端的只有异常类型，避免带出内部路径 / SQL 等信息
    print(f"[error] {request.method} {request.url.path}: {exc!r}")
    return JSONResponse(status_code=500, content={"detail": f"服务器内部错误：{type(exc).__name__}"})


for r in (setup.router, auth.router, stats.router, admin.router, audit_router.router, people_router.router,
          compliance_router.router):
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
