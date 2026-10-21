import os
import time

from fastapi.testclient import TestClient

from app import bootstrap, database, stats, timeutil
from app.engine import engine
from app.main import app

CFG = {"host": os.environ.get("MYSQL_HOST", "127.0.0.1"), "port": int(os.environ.get("MYSQL_PORT", 3306)),
       "user": "root", "password": os.environ.get("MYSQL_ROOT_PASSWORD", ""), "database": "rosdpi_wizard"}


def test_full_wizard_flow_on_mysql():
    with TestClient(app) as c:
        assert c.get("/api/setup/status").json()["configured"] is False
        assert c.get("/api/auth/status").status_code == 503

        bad = c.post("/api/setup/test", json={**CFG, "password": "wrong"})
        assert bad.status_code == 400 and "账号或密码错误" in bad.json()["detail"]

        ok = c.post("/api/setup/test", json=CFG).json()
        assert "自动创建" in ok["message"]          # 库还不存在

        assert c.post("/api/setup/save", json=CFG).status_code == 200
        assert database.is_mysql()
        assert bootstrap.load_config()["database"] == "rosdpi_wizard"
        assert c.get("/api/setup/status").json() == {"configured": True, "source": "file", "config_present": True}
        # 配置完成后向导接口关闭
        assert c.post("/api/setup/save", json=CFG).status_code == 400

        tok = c.post("/api/auth/setup", json={"username": "admin", "password": "secret1"}).json()["token"]
        h = {"Authorization": f"Bearer {tok}"}

        # MySQL 的 ON DUPLICATE KEY UPDATE 累加
        now = time.time()
        for _ in range(2):
            with engine.lock:
                engine.add_flow(dict(src="192.168.88.9", dst="8.8.8.8", sport=1, dport=443, proto=6, bytes=100,
                                     src_mac="AA:00:00:00:00:09"), now)
            engine.flush(now)
        with database.session() as db:
            t = stats.total(db, *timeutil.range_bounds("today"), host="AA:00:00:00:00:09")
        assert t["up"] == 200 and t["flows"] == 2

        s = c.get("/api/settings", headers=h).json()
        assert s["database"]["source"] == "wizard" and s["database"]["database"] == "rosdpi_wizard"
        assert c.get("/api/overview", headers=h).status_code == 200
