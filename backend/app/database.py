import os
import time

from sqlalchemy import create_engine, event
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


def _make_engine(url: str):
    if url.startswith("sqlite"):
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
    return create_engine(url, pool_pre_ping=True, pool_recycle=1800, pool_size=10, max_overflow=10)


engine = _make_engine(get_settings().database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def is_mysql() -> bool:
    return engine.dialect.name == "mysql"


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


def init_db(retries: int = 20, delay: float = 3.0):
    """建表。容器启动时 MySQL 往往还没就绪，这里重试。"""
    from app import models  # noqa: F401  注册模型

    for i in range(1, retries + 1):
        try:
            Base.metadata.create_all(engine)
            return
        except Exception as e:  # noqa: BLE001
            print(f"[db] 数据库未就绪（{i}/{retries}）：{type(e).__name__}: {str(e)[:120]}")
            if i == retries:
                raise
            time.sleep(delay)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
