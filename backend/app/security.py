import secrets
import time

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext

from app import database
from app.config import get_settings
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
    with database.session() as db:
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
    with database.session() as db:
        if pw and db.query(User).count() == 0:
            db.add(User(username="admin", password_hash=pwd.hash(pw), role="admin", created=int(time.time())))
            db.commit()
            print("[auth] 已按 ADMIN_PASSWORD 创建管理员 admin")


def make_token(username: str) -> str:
    return jwt.encode({"sub": username, "exp": int(time.time()) + TOKEN_DAYS * 86400}, secret_key(), "HS256")


# 普通用户（role=user）只读：除了改自己的密码，所有写操作都要管理员；这些读接口也只给管理员
USER_WRITABLE = {"/api/auth/password"}
ADMIN_ONLY_GET = ("/api/settings", "/api/audit/notify", "/api/audit/oplog", "/api/auth/users")
_roles: dict[str, tuple[str | None, float]] = {}   # username -> (role，账号不存在时为 None, 缓存时间)


def role_of(username: str) -> str | None:
    """账号的角色：admin / user；账号不存在返回 None。缓存 30 秒，改账号后调用 forget_roles()"""
    hit = _roles.get(username)
    if hit and time.time() - hit[1] < 30:
        return hit[0]
    with database.session() as db:
        u = db.query(User).filter(User.username == username).first()
    role = (u.role or "admin") if u else None
    _roles[username] = (role, time.time())
    return role


def forget_roles():
    _roles.clear()


def current_user(request: Request, cred: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> str:
    if cred is None:
        raise HTTPException(401, "未登录")
    try:
        data = jwt.decode(cred.credentials, secret_key(), algorithms=["HS256"])
    except JWTError:
        raise HTTPException(401, "登录已过期，请重新登录")
    user = data["sub"]
    role = role_of(user)
    if role is None:
        raise HTTPException(401, "账号不存在或已被删除，请重新登录")
    request.state.role = role
    if role != "admin":
        path = request.url.path
        if request.method not in ("GET", "HEAD") and path not in USER_WRITABLE:
            raise HTTPException(403, "只有管理员可以修改")
        if request.method in ("GET", "HEAD") and path.startswith(ADMIN_ONLY_GET):
            raise HTTPException(403, "只有管理员可以查看")
    return user


def require_admin(request: Request, user: str = Depends(current_user)) -> str:
    if getattr(request.state, "role", None) != "admin":
        raise HTTPException(403, "只有管理员可以操作")
    return user
