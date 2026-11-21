"""0.7.0 多站点迁移：给按站点隔离的表加 site 列（需要时重建主键），建默认站点，给已有普通用户授权默认站点。

在 create_all 之后、add_missing_columns 之前执行；每张表按“site 列是否已存在”判断，重复运行不做任何事。
数据多时重建主键会比较久（MySQL 要重建整张表），期间平台不可用，日志里有每张表的进度。
"""
import time

from sqlalchemy import inspect, text

from app.models import DEFAULT_SITE

# 表名 -> 新主键（site 在最前）；None 表示只加普通列
PK_TABLES = {
    "traffic_minute": ("site", "ts", "host", "app"),
    "traffic_hour": ("site", "ts", "host", "app"),
    "traffic_day": ("site", "ts", "host", "app"),
    "host_domain_day": ("site", "ts", "host", "domain"),
    "unmatched_day": ("site", "ts", "host", "proto", "port", "kind", "app"),
    "hosts": ("site", "key"),
    "host_names": ("site", "kind", "value"),
    "person_devices": ("site", "host"),
}
COL_TABLES = ("access_log", "audit_events", "people", "departments", "accuracy_probes")
SITE_KEYS = ("ros_url", "ros_user", "ros_password", "ros_verify_tls", "lan_cidrs", "wan_interface")


def _q(name: str) -> str:
    return f"`{name}`" if name else name


def _log(msg: str):
    print(f"[migrate] {msg}", flush=True)


def migrate(engine, metadata) -> bool:
    """返回是否做了迁移"""
    insp = inspect(engine)
    todo = [t for t in (*PK_TABLES, *COL_TABLES)
            if insp.has_table(t) and "site" not in {c["name"] for c in insp.get_columns(t)}]
    did = False
    if todo:
        did = True
        _log("0.7.0 多站点迁移开始：给 %d 张表加站点列。数据多时需要几分钟甚至更久，请勿中断；"
             "升级前请确认已备份数据库" % len(todo))
        mysql = engine.dialect.name == "mysql"
        for name in todo:
            t0 = time.time()
            with engine.begin() as conn:
                rows = conn.execute(text(f"SELECT COUNT(*) FROM {_q(name)}")).scalar() or 0
                _log(f"{name}：{rows} 行 …")
                table = metadata.tables[name]
                if name in PK_TABLES or name == "departments":
                    if mysql:
                        _mysql_rebuild(conn, insp, name, table)
                    else:
                        _sqlite_rebuild(conn, insp, name, table)
                else:
                    conn.exec_driver_sql(f"ALTER TABLE {_q(name)} ADD COLUMN `site` VARCHAR(32) NOT NULL "
                                         f"DEFAULT '{DEFAULT_SITE}'")
            _log(f"{name}：完成（{time.time() - t0:.1f}s）")
    if _ensure_default_site(engine):
        did = True
    if todo:
        _log("0.7.0 多站点迁移完成")
    return did


def _mysql_rebuild(conn, insp, name, table):
    pk = ", ".join(_q(c) for c in PK_TABLES.get(name, ()))
    parts = [f"ADD COLUMN `site` VARCHAR(32) NOT NULL DEFAULT '{DEFAULT_SITE}' FIRST"]
    if name == "departments":
        # 旧的 name 唯一索引换成 (site, name)
        for u in insp.get_unique_constraints(name):
            if u["column_names"] == ["name"]:
                parts.append(f"DROP INDEX {_q(u['name'])}")
        for i in insp.get_indexes(name):
            if i.get("unique") and i["column_names"] == ["name"]:
                if f"DROP INDEX {_q(i['name'])}" not in parts:
                    parts.append(f"DROP INDEX {_q(i['name'])}")
        parts.append("ADD CONSTRAINT `uq_dept_site_name` UNIQUE (`site`, `name`)")
    else:
        parts += ["DROP PRIMARY KEY", f"ADD PRIMARY KEY ({pk})"]
    conn.exec_driver_sql(f"ALTER TABLE {_q(name)} " + ", ".join(parts))


def _sqlite_rebuild(conn, insp, name, table):
    """SQLite 不能改主键：旧表改名 → 按新结构建表 → 复制 → 删旧表。索引名在 SQLite 里全库唯一，先删旧索引"""
    old_cols = [c["name"] for c in insp.get_columns(name)]
    for i in insp.get_indexes(name):
        if i.get("name") and not i["name"].startswith("sqlite_autoindex"):
            conn.exec_driver_sql(f'DROP INDEX IF EXISTS "{i["name"]}"')
    tmp = f"{name}__pre070"
    conn.exec_driver_sql(f'ALTER TABLE "{name}" RENAME TO "{tmp}"')
    table.create(conn)
    cols = [c for c in old_cols if c in table.c and c != "site"]
    col_sql = ", ".join(f'"{c}"' for c in cols)
    conn.exec_driver_sql(f'INSERT INTO "{name}" ("site", {col_sql}) SELECT \'{DEFAULT_SITE}\', {col_sql} FROM "{tmp}"')
    conn.exec_driver_sql(f'DROP TABLE "{tmp}"')


def _ensure_default_site(engine) -> bool:
    """没有任何站点时建默认站点：RouterOS / LAN / WAN 配置从 settings 表搬过来（环境变量不搬，运行时作为默认站点的后备）；
    已有的普通用户授权默认站点"""
    from app.models import Setting, Site, User, UserSite
    from sqlalchemy.orm import Session

    with Session(engine) as db:
        if db.query(Site.slug).first() is not None:
            return False
        saved = dict(db.query(Setting.key, Setting.value).filter(Setting.key.in_(SITE_KEYS)).all())
        db.add(Site(slug=DEFAULT_SITE, name="默认站点", sources="",
                    ros_url=saved.get("ros_url") or None, ros_user=saved.get("ros_user") or None,
                    ros_password=saved.get("ros_password") or None,
                    ros_verify_tls=(1 if saved.get("ros_verify_tls") in ("1", "true", "True") else
                                    0 if "ros_verify_tls" in saved else None),
                    lan_cidrs=saved.get("lan_cidrs") or None, wan_interface=saved.get("wan_interface") or None,
                    enabled=1, sort=0, created=int(time.time())))
        # 这几项改由站点保存，从全局设置里删掉（以后网页改的是站点行）
        db.query(Setting).filter(Setting.key.in_(SITE_KEYS)).delete(synchronize_session=False)
        for (uid,) in db.query(User.id).filter(User.role == "user").all():
            db.add(UserSite(user_id=uid, site=DEFAULT_SITE))
        db.commit()
    _log("已建默认站点")
    return True
