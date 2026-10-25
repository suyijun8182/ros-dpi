"""首次使用的安装向导：在网页上填写 MySQL 连接信息（与 EasySub 相同的流程）。

这些接口不需要登录，但只在数据库尚未配置时可用。
"""
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app import bootstrap, database
from app.config import get_settings
from app.security import check_setup_code

router = APIRouter(prefix="/api/setup", tags=["setup"])


class DBConfig(BaseModel):
    host: str = Field(min_length=1, max_length=255)
    port: int = Field(3306, ge=1, le=65535)
    user: str = Field(min_length=1, max_length=128)
    password: str = Field("", max_length=256)
    database: str = Field("rosdpi", pattern=r"^[A-Za-z0-9_$-]{1,64}$")


def _source() -> str | None:
    if get_settings().database_url:
        return "env"
    if bootstrap.config_exists():
        return "file"
    return None


@router.get("/status")
def status():
    src = _source()
    # 有配置但还没连上（例如 MySQL 比本服务晚启动）：顺带尝试重连，刷新页面即可恢复
    if src and not database.is_configured():
        database.connect_from_saved()
    return {"configured": database.is_configured(), "source": src, "config_present": src is not None}


def _guard():
    if _source() is not None:
        raise HTTPException(400, "数据库已配置；如需更换，请删除 data/db_config.json 后重启容器")


@router.post("/test")
def test(cfg: DBConfig, request: Request):
    _guard()
    check_setup_code(request)
    ok, msg = bootstrap.test_connection(cfg.model_dump())
    if not ok:
        raise HTTPException(400, msg)
    return {"ok": True, "message": msg}


@router.post("/save")
def save(cfg: DBConfig, request: Request):
    _guard()
    check_setup_code(request)
    data = cfg.model_dump()
    ok, msg = bootstrap.test_connection(data)
    if not ok:
        raise HTTPException(400, msg)
    try:
        database.connect(bootstrap.build_url(data), retries=1)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"初始化数据库失败：{bootstrap.explain(e)}")
    bootstrap.save_config(data)
    return {"ok": True, "message": "数据库已配置，接下来设置管理员密码"}
