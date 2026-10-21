"""网页安装向导填写的 MySQL 连接信息：保存在 data/db_config.json（通过 Docker 卷持久化）。

连接信息本身就是要配置的对象，没法存进数据库，所以和 EasySub 一样放在磁盘文件里。
"""
import json
import os
from urllib.parse import quote_plus

from sqlalchemy import create_engine, text

FIELDS = ("host", "port", "user", "password", "database")


def config_path() -> str:
    return os.path.join(os.environ.get("DATA_DIR", "data"), "db_config.json")


def config_exists() -> bool:
    return os.path.isfile(config_path())


def load_config() -> dict:
    with open(config_path(), encoding="utf-8") as f:
        return json.load(f)


def save_config(cfg: dict) -> None:
    p = config_path()
    os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump({k: cfg[k] for k in FIELDS if k in cfg}, f, ensure_ascii=False, indent=2)
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass


def delete_config() -> None:
    if config_exists():
        os.remove(config_path())


def build_url(cfg: dict, with_db: bool = True) -> str:
    user = quote_plus(str(cfg["user"]))
    pw = quote_plus(str(cfg.get("password", "")))
    host = cfg["host"].strip()
    if ":" in host and not host.startswith("["):  # IPv6 地址
        host = f"[{host}]"
    port = int(cfg.get("port") or 3306)
    db = cfg["database"] if with_db else ""
    return f"mysql+pymysql://{user}:{pw}@{host}:{port}/{db}?charset=utf8mb4"


def test_connection(cfg: dict) -> tuple[bool, str]:
    """测试连接。库不存在但账号能连上服务器时也算通过（保存时会尝试自动建库）。"""
    eng = create_engine(build_url(cfg, with_db=False), connect_args={"connect_timeout": 8})
    try:
        with eng.connect() as conn:
            version = conn.execute(text("SELECT VERSION()")).scalar()
            exists = conn.execute(text("SELECT COUNT(*) FROM information_schema.SCHEMATA WHERE SCHEMA_NAME = :d"),
                                  {"d": cfg["database"]}).scalar()
        if exists:
            return True, f"连接成功，MySQL {version}，数据库 {cfg['database']} 已存在"
        return True, f"连接成功，MySQL {version}；数据库 {cfg['database']} 不存在，保存时将自动创建（需要建库权限）"
    except Exception as e:  # noqa: BLE001
        return False, explain(e)
    finally:
        eng.dispose()


def explain(e: Exception) -> str:
    """把常见的 MySQL 错误翻译成能照着改的提示。"""
    msg = str(e)
    if "1045" in msg:
        hint = "账号或密码错误，或者该账号不允许从本机连接（建账号时主机请用 %）"
    elif "2003" in msg or "timed out" in msg or "Can't connect" in msg:
        hint = "连不上 MySQL：检查地址和端口；MySQL 在同一台机器时请填局域网 IP，不要填 127.0.0.1；确认 MySQL 允许远程连接"
    elif "1044" in msg or "1142" in msg:
        hint = "账号没有该数据库的权限：请执行 GRANT ALL PRIVILEGES ON 库名.* TO '账号'@'%'"
    elif "1049" in msg:
        hint = "数据库不存在，且账号没有建库权限：请先执行 CREATE DATABASE"
    else:
        hint = "连接失败"
    return f"{hint}（{type(e).__name__}: {msg.splitlines()[0][:200]}）"
