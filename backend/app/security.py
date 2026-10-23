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


def make_token(username: str, version: int | None = None) -> str:
    return jwt.encode({"sub": username, "ver": version or 0,
                       "exp": int(time.time()) + TOKEN_DAYS * 86400}, secret_key(), "HS256")


# 普通用户（role=user）只读：除了改自己的密码，所有写操作都要管理员；这些读接口也只给管理员
USER_WRITABLE = {"/api/auth/password"}
ADMIN_ONLY_GET = ("/api/settings", "/api/audit/notify", "/api/audit/oplog", "/api/auth/users", "/api/compliance")
_roles: dict[str, tuple[str | None, int, float]] = {}   # username -> (role，账号不存在时为 None, token_version, 缓存时间)


def user_info(username: str) -> tuple[str, int] | None:
    """账号的 (角色, token 版本)；账号不存在返回 None。缓存 30 秒，改账号后调用 forget_roles()"""
    hit = _roles.get(username)
    if hit and time.time() - hit[2] < 30:
        return (hit[0], hit[1]) if hit[0] is not None else None
    with database.session() as db:
        u = db.query(User).filter(User.username == username).first()
    if u is None:
        _roles[username] = (None, 0, time.time())
        return None
    _roles[username] = ((u.role or "admin"), u.token_version or 0, time.time())
    return _roles[username][0], _roles[username][1]


def role_of(username: str) -> str | None:
    info = user_info(username)
    return info[0] if info else None


def forget_roles():
    _roles.clear()


def current_user(request: Request, cred: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> str:
    if cred is None:
        raise HTTPException(401, "未登录")
    try:
        data = jwt.decode(cred.credentials, secret_key(), algorithms=["HS256"])
    except JWTError:
        raise HTTPException(401, "登录已过期，请重新登录")
    user = data.get("sub")
    if not user:
        raise HTTPException(401, "登录已过期，请重新登录")
    info = user_info(user)
    if info is None:
        raise HTTPException(401, "账号不存在或已被删除，请重新登录")
    role, ver = info
    if data.get("ver", 0) != ver:
        # 改密码 / 管理员改权限后版本号会 +1，旧 token 立即失效
        raise HTTPException(401, "登录状态已失效（密码或权限已变更），请重新登录")
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


# ---------------- 登录限速：同一 IP + 用户名连续失败 5 次后锁定 15 分钟 ----------------
MAX_LOGIN_FAILS = 5
LOGIN_LOCK_SECONDS = 900
_login_fails: dict[tuple[str, str], list] = {}  # (ip, username) -> [连续失败次数, 锁定到]


def _fail_key(request: Request, username: str) -> tuple[str, str]:
    from app.oplog import client_ip
    return client_ip(request), username


def check_login_lock(request: Request, username: str):
    key = _fail_key(request, username)
    e = _login_fails.get(key)
    if not e:
        return
    now = time.time()
    if e[0] >= MAX_LOGIN_FAILS:
        if now < e[1]:
            raise HTTPException(429, f"失败次数过多，请 {max(int((e[1] - now) / 60), 1)} 分钟后再试")
        _login_fails.pop(key, None)  # 锁定期已过，重新计数


def note_login_fail(request: Request, username: str):
    if len(_login_fails) > 10_000:  # 被大 IP 池爆破时兜底，避免字典无限涨
        _login_fails.clear()
    key = _fail_key(request, username)
    e = _login_fails.get(key) or [0, 0.0]
    if e[0] >= MAX_LOGIN_FAILS and time.time() >= e[1]:
        e = [0, 0.0]
    e[0] += 1
    if e[0] >= MAX_LOGIN_FAILS:
        e[1] = time.time() + LOGIN_LOCK_SECONDS
    _login_fails[key] = e


def note_login_ok(request: Request, username: str):
    _login_fails.pop(_fail_key(request, username), None)
