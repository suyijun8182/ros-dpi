import os

from fastapi.testclient import TestClient

from app import bootstrap, database
from app.config import get_settings
from app.engine import engine
from app.main import app


def test_build_url_escapes_and_ipv6():
    u = bootstrap.build_url({"host": "fd00::5", "port": 3307, "user": "ro@s", "password": "p@ss:/#", "database": "rosdpi"})
    assert u == "mysql+pymysql://ro%40s:p%40ss%3A%2F%23@[fd00::5]:3307/rosdpi?charset=utf8mb4"


def test_explain_common_errors():
    assert "账号或密码错误" in bootstrap.explain(Exception("(1045, \"Access denied for user 'x'\")"))
    assert "127.0.0.1" in bootstrap.explain(Exception("(2003, \"Can't connect to MySQL server\")"))


def test_configured_via_env_blocks_wizard():
    with TestClient(app) as c:
        st = c.get("/api/setup/status").json()
        assert st == {"configured": True, "source": "env", "config_present": True}
        r = c.post("/api/setup/save", json={"host": "x", "user": "u", "password": "p", "database": "rosdpi"})
        assert r.status_code == 400


def test_wizard_mode_without_database(monkeypatch):
    url = os.environ["DATABASE_URL"]
    monkeypatch.setattr(get_settings(), "database_url", "")
    database.reset_engine()
    try:
        c = TestClient(app)  # 不触发 lifespan，只测接口
        assert c.get("/api/setup/status").json() == {"configured": False, "source": None, "config_present": False}
        assert c.get("/api/auth/status").status_code == 503
        r = c.post("/api/setup/save", json={"host": "x", "user": "u", "database": "bad name"})
        assert r.status_code == 422
        engine.flush()  # 未配置时不报错、也不丢弃内存数据
    finally:
        database.connect(url)
    assert database.is_configured()
