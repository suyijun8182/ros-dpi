"""数据库连接在运行时初始化（与 EasySub 相同的做法）。

来源优先级：环境变量 DATABASE_URL > 网页安装向导保存的 data/db_config.json。
都没有时进入安装向导模式：流量照常采集到内存，数据库配置好后才落库。
"""
import threading
import time

from fastapi import HTTPException
from sqlalchemy import create_engine, event
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import DeclarativeBase, sessionmaker


class Base(DeclarativeBase):
    pass


# 由 init_engine() 赋值；未配置前为 None
engine = None
SessionLocal = None

_ready_hooks: list = []
_connect_lock = threading.Lock()
_last_reconnect_attempt = 0.0
_RECONNECT_INTERVAL = 15.0


class NotConfigured(RuntimeError):
    pass


def _make_engine(url: str):
    if url.startswith("sqlite"):
        import os
        path = url.split("///", 1)[-1]
        if path and path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        eng = create_engine(url, connect_args={"check_same_thread": False})

        @event.listens_for(eng, "connect")
        def _pragma(conn, _):
            cur = conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA synchronous=NORMAL")
            cur.close()

        return eng
    return create_engine(url, pool_pre_ping=True, pool_recycle=1800, pool_size=10, max_overflow=10,
                         connect_args={"connect_timeout": 10} if url.startswith("mysql") else {})


def init_engine(url: str):
    global engine, SessionLocal
    reset_engine()
    engine = _make_engine(url)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    return engine


def reset_engine():
    global engine, SessionLocal
    if engine is not None:
        engine.dispose()
    engine = None
    SessionLocal = None


def is_configured() -> bool:
    return SessionLocal is not None


def session():
    """后台任务用：未配置数据库时抛 NotConfigured。"""
    if SessionLocal is None:
        raise NotConfigured("数据库尚未配置")
    return SessionLocal()


def is_mysql() -> bool:
    return engine is not None and engine.dialect.name == "mysql"


def upsert_add(session, table, rows: list[dict], keys: list[str], add_cols: list[str], set_cols: list[str] = ()):
    """批量 upsert：主键冲突时 add_cols 累加、set_cols 覆盖。MySQL / SQLite 通用。"""
    if not rows:
        return
    if is_mysql():
        stmt = mysql_insert(table).values(rows)
        upd = {c: table.c[c] + stmt.inserted[c] for c in add_cols}
        upd.update({c: stmt.inserted[c] for c in set_cols})
        stmt = stmt.on_duplicate_key_update(**upd)
    else:
        stmt = sqlite_insert(table).values(rows)
        upd = {c: table.c[c] + stmt.excluded[c] for c in add_cols}
        upd.update({c: stmt.excluded[c] for c in set_cols})
        stmt = stmt.on_conflict_do_update(index_elements=keys, set_=upd)
    session.execute(stmt)


def _create_database_if_missing(err: Exception) -> bool:
    """MySQL 报 1049（库不存在）时，用同一账号连到服务器建库。成功返回 True。"""
    if not is_mysql() or "1049" not in str(err):
        return False
    url = engine.url
    name = url.database
    # 注意：url.set(database=None) 在 SQLAlchemy 2.0 里表示"不修改"，必须用 _replace 真正去掉库名
    server = create_engine(url._replace(database=None), pool_pre_ping=True)
    try:
        with server.connect() as conn:
            conn.exec_driver_sql(
                f"CREATE DATABASE IF NOT EXISTS `{name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
        print(f"[db] 已自动创建数据库 {name}", flush=True)
        return True
    finally:
        server.dispose()


def init_db(retries: int = 20, delay: float = 3.0):
    """建库建表。容器启动时 MySQL 往往还没就绪，这里重试。"""
    from app import models  # noqa: F401  注册模型

    for i in range(1, retries + 1):
        try:
            Base.metadata.create_all(engine)
            return
        except Exception as e:  # noqa: BLE001
            try:
                if _create_database_if_missing(e):
                    Base.metadata.create_all(engine)
                    return
            except Exception as ce:  # noqa: BLE001
                print(f"[db] 数据库不存在，且自动创建失败（账号可能没有建库权限）：{ce}", flush=True)
            print(f"[db] 数据库未就绪（{i}/{retries}）：{type(e).__name__}: {str(e)[:160]}", flush=True)
            if i == retries:
                raise
            time.sleep(delay)


def add_ready_hook(fn):
    """数据库连接成功后要执行的初始化（创建管理员、恢复状态等）。"""
    if fn not in _ready_hooks:
        _ready_hooks.append(fn)


def connect(url: str, retries: int = 1, delay: float = 3.0):
    """连接并建表，成功后执行 ready hooks；失败时恢复为未配置状态并抛出异常。"""
    init_engine(url)
    try:
        init_db(retries=retries, delay=delay)
    except Exception:
        reset_engine()
        raise
    for fn in _ready_hooks:
        fn()


def configured_url() -> str | None:
    from app import bootstrap
    from app.config import get_settings

    if get_settings().database_url:
        return get_settings().database_url
    if bootstrap.config_exists():
        return bootstrap.build_url(bootstrap.load_config())
    return None


def connect_from_saved(force: bool = False, retries: int = 1) -> bool:
    """用环境变量或已保存的配置连接（幂等）。非 force 调用有节流，避免数据库故障时每个请求都阻塞。"""
    global _last_reconnect_attempt
    if SessionLocal is not None:
        return True
    now = time.monotonic()
    if not force and now - _last_reconnect_attempt < _RECONNECT_INTERVAL:
        return False
    _last_reconnect_attempt = now
    url = configured_url()
    if not url:
        return False
    # 启动时的后台连接和定时重连可能同时触发，只让一个去连
    if not _connect_lock.acquire(blocking=False):
        return False
    try:
        if SessionLocal is not None:
            return True
        connect(url, retries=retries)
        return True
    except Exception as e:  # noqa: BLE001
        print(f"[db] 连接失败：{type(e).__name__}: {str(e)[:200]}", flush=True)
        return False
    finally:
        _connect_lock.release()


def get_db():
    if SessionLocal is None and not connect_from_saved():
        raise HTTPException(503, "数据库尚未配置或暂时不可用；首次使用请在安装向导中填写 MySQL 信息")
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
