import secrets
import time

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext

from app.config import get_settings
from app.database import SessionLocal
from app.models import Setting, User

pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
_bearer = HTTPBearer(auto_error=False)
_secret: str | None = None
TOKEN_DAYS = 30


def secret_key() -> str:
    global _secret
    if _secret:
        return _secret
    if get_settings().secret_key:
        _secret = get_settings().secret_key
        return _secret
    with SessionLocal() as db:
        row = db.get(Setting, "secret_key")
        if row is None:
            row = Setting(key="secret_key", value=secrets.token_urlsafe(48))
            db.add(row)
            db.commit()
        _secret = row.value
    return _secret


def ensure_admin():
    """设置了 ADMIN_PASSWORD 且还没有账号时，创建 admin。"""
    pw = get_settings().admin_password
    with SessionLocal() as db:
        if pw and db.query(User).count() == 0:
            db.add(User(username="admin", password_hash=pwd.hash(pw)))
            db.commit()
            print("[auth] 已按 ADMIN_PASSWORD 创建管理员 admin")


def make_token(username: str) -> str:
    return jwt.encode({"sub": username, "exp": int(time.time()) + TOKEN_DAYS * 86400}, secret_key(), "HS256")


def current_user(cred: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> str:
    if cred is None:
        raise HTTPException(401, "未登录")
    try:
        data = jwt.decode(cred.credentials, secret_key(), algorithms=["HS256"])
    except JWTError:
        raise HTTPException(401, "登录已过期，请重新登录")
    return data["sub"]
