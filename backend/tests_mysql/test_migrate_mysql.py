"""0.7.0 多站点迁移在真实 MySQL 上：改主键（DROP/ADD PRIMARY KEY）、部门唯一索引换成 (site, name)"""
import os

from sqlalchemy import create_engine, inspect, text

from app import migrate_sites
from app.database import Base

HOST = os.environ.get("MYSQL_HOST", "127.0.0.1")
PORT = int(os.environ.get("MYSQL_PORT", 3306))
PW = os.environ.get("MYSQL_ROOT_PASSWORD", "")
DB = "rosdpi_mig070"

OLD_DDL = [
    """CREATE TABLE traffic_day (ts BIGINT NOT NULL, host VARCHAR(64) NOT NULL, app VARCHAR(48) NOT NULL,
       up BIGINT NOT NULL, down BIGINT NOT NULL, flows INT NOT NULL, PRIMARY KEY (ts, host, app),
       INDEX ix_tday_host_ts (host, ts), INDEX ix_tday_app_ts (app, ts))""",
    """CREATE TABLE hosts (`key` VARCHAR(64) NOT NULL PRIMARY KEY, mac VARCHAR(17), ip VARCHAR(45), ipv6 TEXT,
       hostname VARCHAR(128), alias VARCHAR(128), first_seen BIGINT, last_seen BIGINT, online_since BIGINT,
       dtype VARCHAR(16), dtype_auto VARCHAR(16), vendor VARCHAR(64))""",
    """CREATE TABLE departments (id INT NOT NULL AUTO_INCREMENT PRIMARY KEY, name VARCHAR(64) NOT NULL UNIQUE)""",
    """CREATE TABLE access_log (id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY, ts_start BIGINT NOT NULL,
       ts_end BIGINT NOT NULL, host VARCHAR(64) NOT NULL, host_ip VARCHAR(45), dest VARCHAR(255) NOT NULL,
       remote VARCHAR(255), app VARCHAR(48) NOT NULL, port INT, proto INT, conns INT NOT NULL, up BIGINT NOT NULL,
       down BIGINT NOT NULL, source VARCHAR(8))""",
    "INSERT INTO traffic_day VALUES (100, 'H1', 'wechat', 10, 20, 3)",
    "INSERT INTO hosts (`key`, ip) VALUES ('H1', '192.168.88.2')",
    "INSERT INTO departments (name) VALUES ('家长')",
    "INSERT INTO access_log (ts_start, ts_end, host, dest, app, conns, up, down) VALUES (1, 2, 'H1', 'qq.com', 'x', 1, 1, 1)",
]


def test_migrate_on_mysql():
    server = create_engine(f"mysql+pymysql://root:{PW}@{HOST}:{PORT}/?charset=utf8mb4")
    with server.begin() as conn:
        conn.exec_driver_sql(f"DROP DATABASE IF EXISTS {DB}")
        conn.exec_driver_sql(f"CREATE DATABASE {DB} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
    server.dispose()
    eng = create_engine(f"mysql+pymysql://root:{PW}@{HOST}:{PORT}/{DB}?charset=utf8mb4")
    with eng.begin() as conn:
        for sql in OLD_DDL:
            conn.exec_driver_sql(sql)
    Base.metadata.create_all(eng)
    assert migrate_sites.migrate(eng, Base.metadata) is True
    insp = inspect(eng)
    assert insp.get_pk_constraint("traffic_day")["constrained_columns"] == ["site", "ts", "host", "app"]
    assert insp.get_pk_constraint("hosts")["constrained_columns"] == ["site", "key"]
    uniq = [i["column_names"] for i in insp.get_indexes("departments") if i.get("unique")]
    assert ["site", "name"] in uniq and ["name"] not in uniq
    with eng.begin() as conn:
        assert conn.execute(text("SELECT site, up FROM traffic_day")).all() == [("default", 10)]
        assert conn.execute(text("SELECT site FROM access_log")).all() == [("default",)]
        conn.exec_driver_sql("INSERT INTO departments (site, name) VALUES ('office', '家长')")
    assert migrate_sites.migrate(eng, Base.metadata) is False
    eng.dispose()
