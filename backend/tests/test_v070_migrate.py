"""0.7.0 多站点迁移：0.6.30 结构的库升级后数据都在、site=default、主键带上 site；重复运行不做任何事"""
import os
import tempfile

from sqlalchemy import create_engine, inspect, text

from app import migrate_sites
from app.database import Base

OLD_DDL = [
    """CREATE TABLE traffic_day (ts BIGINT NOT NULL, host VARCHAR(64) NOT NULL, app VARCHAR(48) NOT NULL,
       up BIGINT NOT NULL, down BIGINT NOT NULL, flows INTEGER NOT NULL, PRIMARY KEY (ts, host, app))""",
    "CREATE INDEX ix_tday_host_ts ON traffic_day (host, ts)",
    "CREATE INDEX ix_tday_app_ts ON traffic_day (app, ts)",
    """CREATE TABLE hosts (key VARCHAR(64) NOT NULL PRIMARY KEY, mac VARCHAR(17), ip VARCHAR(45), ipv6 TEXT,
       hostname VARCHAR(128), alias VARCHAR(128), first_seen BIGINT, last_seen BIGINT, online_since BIGINT,
       dtype VARCHAR(16), dtype_auto VARCHAR(16), vendor VARCHAR(64))""",
    """CREATE TABLE host_names (kind VARCHAR(8) NOT NULL, value VARCHAR(45) NOT NULL, name VARCHAR(128) NOT NULL,
       updated BIGINT, PRIMARY KEY (kind, value))""",
    """CREATE TABLE departments (id INTEGER NOT NULL PRIMARY KEY, name VARCHAR(64) NOT NULL UNIQUE)""",
    """CREATE TABLE person_devices (host VARCHAR(64) NOT NULL PRIMARY KEY, person_id INTEGER NOT NULL)""",
    """CREATE TABLE access_log (id INTEGER NOT NULL PRIMARY KEY, ts_start BIGINT NOT NULL, ts_end BIGINT NOT NULL,
       host VARCHAR(64) NOT NULL, host_ip VARCHAR(45), dest VARCHAR(255) NOT NULL, remote VARCHAR(255),
       app VARCHAR(48) NOT NULL, port INTEGER, proto INTEGER, conns INTEGER NOT NULL, up BIGINT NOT NULL,
       down BIGINT NOT NULL, source VARCHAR(8))""",
    """CREATE TABLE users (id INTEGER NOT NULL PRIMARY KEY, username VARCHAR(64) NOT NULL UNIQUE,
       password_hash VARCHAR(128) NOT NULL, role VARCHAR(16), token_version INTEGER, created INTEGER,
       last_login INTEGER)""",
    "CREATE TABLE settings (key VARCHAR(64) NOT NULL PRIMARY KEY, value TEXT)",
]
OLD_ROWS = [
    "INSERT INTO traffic_day VALUES (100, 'AA:BB:CC:00:00:01', 'wechat', 10, 20, 3)",
    "INSERT INTO traffic_day VALUES (100, 'IP:192.168.88.9', 'https', 5, 6, 1)",
    "INSERT INTO hosts (key, mac, ip, hostname) VALUES ('AA:BB:CC:00:00:01', 'AA:BB:CC:00:00:01', '192.168.88.2', 'pc')",
    "INSERT INTO host_names VALUES ('mac', 'AA:BB:CC:00:00:01', '书房电脑', 1)",
    "INSERT INTO departments VALUES (1, '家长')",
    "INSERT INTO person_devices VALUES ('AA:BB:CC:00:00:01', 1)",
    "INSERT INTO access_log (id, ts_start, ts_end, host, dest, app, conns, up, down) "
    "VALUES (1, 100, 160, 'AA:BB:CC:00:00:01', 'qq.com', 'wechat', 2, 1, 2)",
    "INSERT INTO users (id, username, password_hash, role) VALUES (1, 'admin', 'x', 'admin')",
    "INSERT INTO users (id, username, password_hash, role) VALUES (2, 'kid', 'x', 'user')",
    "INSERT INTO settings VALUES ('ros_url', 'https://192.168.88.1')",
    "INSERT INTO settings VALUES ('ros_user', 'rosdpi')",
    "INSERT INTO settings VALUES ('ros_password', 'S3cret!')",
    "INSERT INTO settings VALUES ('ros_verify_tls', '1')",
    "INSERT INTO settings VALUES ('lan_cidrs', '192.168.88.0/24')",
]


def _old_db():
    path = os.path.join(tempfile.mkdtemp(prefix="rosdpi-mig-"), "old.db")
    eng = create_engine(f"sqlite:///{path}")
    with eng.begin() as conn:
        for sql in OLD_DDL + OLD_ROWS:
            conn.exec_driver_sql(sql)
    return eng


def test_migrate_old_db(capsys):
    eng = _old_db()
    Base.metadata.create_all(eng)          # 和 init_db 一样：先建新表（sites 等），旧表不动
    assert migrate_sites.migrate(eng, Base.metadata) is True
    insp = inspect(eng)
    assert insp.get_pk_constraint("traffic_day")["constrained_columns"] == ["site", "ts", "host", "app"]
    assert insp.get_pk_constraint("hosts")["constrained_columns"] == ["site", "key"]
    assert insp.get_pk_constraint("host_names")["constrained_columns"] == ["site", "kind", "value"]
    assert insp.get_pk_constraint("person_devices")["constrained_columns"] == ["site", "host"]
    assert any(u["column_names"] == ["site", "name"] for u in insp.get_unique_constraints("departments"))
    with eng.connect() as conn:
        assert conn.execute(text("SELECT site, host, up, down FROM traffic_day ORDER BY host")).all() == [
            ("default", "AA:BB:CC:00:00:01", 10, 20), ("default", "IP:192.168.88.9", 5, 6)]
        assert conn.execute(text("SELECT site, hostname FROM hosts")).all() == [("default", "pc")]
        assert conn.execute(text("SELECT site, name FROM host_names")).all() == [("default", "书房电脑")]
        assert conn.execute(text("SELECT site, name FROM departments")).all() == [("default", "家长")]
        assert conn.execute(text("SELECT site, person_id FROM person_devices")).all() == [("default", 1)]
        assert conn.execute(text("SELECT site, dest FROM access_log")).all() == [("default", "qq.com")]
        site = conn.execute(text("SELECT slug, ros_url, ros_user, ros_password, ros_verify_tls, lan_cidrs, sources "
                                 "FROM sites")).all()
        assert site == [("default", "https://192.168.88.1", "rosdpi", "S3cret!", 1, "192.168.88.0/24", "")]
        # 普通用户自动授权默认站点，管理员不需要
        assert conn.execute(text("SELECT user_id, site FROM user_sites")).all() == [(2, "default")]
    out = capsys.readouterr().out
    assert "请确认已备份数据库" in out and "traffic_day" in out
    # 迁移后同一个部门名可以在不同站点各有一个
    with eng.begin() as conn:
        conn.exec_driver_sql("INSERT INTO departments (site, name) VALUES ('office', '家长')")
    # 再跑一次：什么都不做
    assert migrate_sites.migrate(eng, Base.metadata) is False


def test_migrate_fresh_db():
    path = os.path.join(tempfile.mkdtemp(prefix="rosdpi-mig-"), "new.db")
    eng = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(eng)
    assert migrate_sites.migrate(eng, Base.metadata) is True      # 只建默认站点
    with eng.connect() as conn:
        assert conn.execute(text("SELECT slug, name, enabled, ros_url FROM sites")).all() == [
            ("default", "默认站点", 1, None)]
    assert migrate_sites.migrate(eng, Base.metadata) is False
