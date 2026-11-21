import time

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import oplog
from app.database import get_db
from app.models import ApiToken, Setting, Site, User, UserSite
from app.security import (check_login_lock, check_setup_code, current_user, forget_api_tokens, forget_roles, make_token, new_api_token,
                          note_login_fail, note_login_ok, pwd, require_admin, role_of)

router = APIRouter(prefix="/api/auth", tags=["auth"])


class Creds(BaseModel):
    username: str = "admin"
    password: str = Field(min_length=1)


class SetupReq(BaseModel):
    username: str = Field("admin", min_length=1, max_length=64)
    password: str = Field(min_length=6)


class PwChange(BaseModel):
    old_password: str
    new_password: str = Field(min_length=6)


@router.get("/status")
def status(db: Session = Depends(get_db)):
    return {"initialized": db.query(User).count() > 0}


@router.post("/setup")
def setup(req: SetupReq, request: Request, db: Session = Depends(get_db)):
    if db.query(User).count() > 0:
        raise HTTPException(400, "管理员已存在")
    check_setup_code(request)
    u = User(username=req.username, password_hash=pwd.hash(req.password), role="admin", created=int(time.time()))
    db.add(u)
    # settings 主键唯一：两个请求同时走到这里时，只有一个能提交成功（防安装窗口期被并发接管）
    db.add(Setting(key="setup_done", value=str(int(time.time()))))
    try:
        oplog.log(db, request, req.username, "setup_admin")
    except IntegrityError:
        db.rollback()
        raise HTTPException(400, "管理员已存在")
    forget_roles()
    db.flush()
    return {"token": make_token(req.username, u.token_version), "username": req.username, "role": "admin"}


@router.post("/login")
def login(req: Creds, request: Request, db: Session = Depends(get_db)):
    check_login_lock(request, req.username)
    u = db.query(User).filter(User.username == req.username).first()
    if not u or not pwd.verify(req.password, u.password_hash):
        note_login_fail(request, req.username)
        oplog.log(db, request, req.username, "login", ok=False)
        raise HTTPException(401, "用户名或密码错误")
    note_login_ok(request, req.username)
    u.last_login = int(time.time())
    oplog.log(db, request, u.username, "login")
    return {"token": make_token(u.username, u.token_version), "username": u.username, "role": u.role or "admin"}


@router.get("/me")
def me(request: Request, user: str = Depends(current_user)):
    return {"username": user, "role": getattr(request.state, "role", None) or role_of(user)}


@router.post("/password")
def change_password(req: PwChange, request: Request, user: str = Depends(current_user), db: Session = Depends(get_db)):
    u = db.query(User).filter(User.username == user).first()
    if not u or not pwd.verify(req.old_password, u.password_hash):
        oplog.log(db, request, user, "change_password", ok=False)
        raise HTTPException(400, "原密码错误")
    u.password_hash = pwd.hash(req.new_password)
    u.token_version = (u.token_version or 0) + 1  # 其它设备上的旧 token 立即失效
    forget_roles()  # 角色缓存里存了旧的 token 版本，必须清掉才立即生效
    oplog.log(db, request, user, "change_password")
    # 返回新版本的 token：当前会话无缝续用，其它设备上的旧 token 照样失效
    return {"ok": True, "token": make_token(user, u.token_version), "username": user, "role": u.role or "admin"}


# ---------------- 用户管理（仅管理员） ----------------
ROLE = "^(admin|user)$"


class UserIn(BaseModel):
    username: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.@-]+$")
    password: str = Field(min_length=6, max_length=128)
    role: str = Field("user", pattern=ROLE)
    sites: list[str] | None = None   # 多站点：普通用户能看哪些站点（管理员不用填，看全部）


class UserPatch(BaseModel):
    role: str | None = Field(None, pattern=ROLE)
    password: str | None = Field(None, min_length=6, max_length=128)
    sites: list[str] | None = None


def _user_dict(u: User, db=None) -> dict:
    out = {"id": u.id, "username": u.username, "role": u.role or "admin", "created": u.created, "last_login": u.last_login}
    if db is not None:
        out["sites"] = sorted(db.scalars(select(UserSite.site).where(UserSite.user_id == u.id)).all())
    return out


def _set_sites(db, u: User, sites: list[str] | None, role: str):
    """普通用户的站点授权。没给时：只有一个站点就授权它（以后加了站点，原来的用户照旧只看这个）；
    多个站点时必须至少选一个"""
    all_sites = set(db.scalars(select(Site.slug)).all())
    if sites is None:
        if len(all_sites) > 1:
            if role == "user" and u.id is None:
                raise HTTPException(400, "请选择这个账号能看的站点")
            return
        sites = sorted(all_sites)
    sites = list(dict.fromkeys(x for x in sites if x))
    bad = [x for x in sites if x not in all_sites]
    if bad:
        raise HTTPException(400, f"站点不存在：{', '.join(bad)}")
    if role == "user" and not sites:
        raise HTTPException(400, "请至少选择一个站点")
    db.flush()
    db.execute(delete(UserSite).where(UserSite.user_id == u.id))
    for x in sites:
        db.add(UserSite(user_id=u.id, site=x))


def _admins(db) -> int:
    return sum(1 for u in db.query(User) if (u.role or "admin") == "admin")


@router.get("/users")
def users(_: str = Depends(require_admin), db: Session = Depends(get_db)):
    return [_user_dict(u, db) for u in db.query(User).order_by(User.id)]


@router.post("/users")
def add_user(req: UserIn, request: Request, user: str = Depends(require_admin), db: Session = Depends(get_db)):
    if db.query(User).filter(User.username == req.username).first():
        raise HTTPException(400, "用户名已存在")
    u = User(username=req.username, password_hash=pwd.hash(req.password), role=req.role, created=int(time.time()))
    if req.role == "user" and req.sites is None and db.query(Site).count() > 1:
        raise HTTPException(400, "请选择这个账号能看的站点")
    db.add(u)
    db.flush()
    _set_sites(db, u, req.sites, req.role)
    oplog.log(db, request, user, "user_add", {"username": req.username, "role": req.role, "sites": req.sites})
    forget_roles()
    return _user_dict(u, db)


@router.put("/users/{uid}")
def edit_user(uid: int, req: UserPatch, request: Request, user: str = Depends(require_admin), db: Session = Depends(get_db)):
    u = db.get(User, uid)
    if u is None:
        raise HTTPException(404, "用户不存在")
    if req.role and req.role != (u.role or "admin"):
        if req.role == "user" and (u.role or "admin") == "admin" and _admins(db) <= 1:
            raise HTTPException(400, "至少要保留一个管理员")
        u.role = req.role
    if req.password:
        u.password_hash = pwd.hash(req.password)
    if req.password or req.role:
        u.token_version = (u.token_version or 0) + 1  # 改密码 / 降权后旧 token 立即失效
    if req.sites is not None:
        _set_sites(db, u, req.sites, u.role or "admin")   # 授权缓存由 forget_roles 一起清，下一个请求就生效
    oplog.log(db, request, user, "user_edit", {"username": u.username, "role": req.role, "password": bool(req.password),
                                               "sites": req.sites})
    forget_roles()
    return _user_dict(u, db)


@router.delete("/users/{uid}")
def delete_user(uid: int, request: Request, user: str = Depends(require_admin), db: Session = Depends(get_db)):
    u = db.get(User, uid)
    if u is None:
        raise HTTPException(404, "用户不存在")
    if u.username == user:
        raise HTTPException(400, "不能删除当前登录的账号")
    if (u.role or "admin") == "admin" and _admins(db) <= 1:
        raise HTTPException(400, "至少要保留一个管理员")
    name = u.username
    db.execute(delete(UserSite).where(UserSite.user_id == u.id))
    db.delete(u)
    oplog.log(db, request, user, "user_delete", {"username": name})
    forget_roles()
    return {"ok": True}


# ---------- 只读 API 令牌（0.6.25）：给 Home Assistant 等外部程序用，不过期，原文只在创建时显示一次 ----------
class TokenIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)


def _token_dict(t: ApiToken) -> dict:
    return {"id": t.id, "name": t.name, "prefix": t.prefix, "created": t.created, "created_by": t.created_by, "last_used": t.last_used}


@router.get("/tokens")
def tokens(_: str = Depends(require_admin), db: Session = Depends(get_db)):
    return [_token_dict(t) for t in db.query(ApiToken).order_by(ApiToken.id)]


@router.post("/tokens")
def add_token(req: TokenIn, request: Request, user: str = Depends(require_admin), db: Session = Depends(get_db)):
    if db.query(ApiToken).count() >= 50:
        raise HTTPException(400, "令牌最多 50 个，请先删掉不用的")
    raw, h = new_api_token()
    t = ApiToken(name=req.name.strip(), token_hash=h, prefix=raw[:10], created=int(time.time()), created_by=user)
    db.add(t)
    db.flush()
    oplog.log(db, request, user, "api_token_add", {"name": t.name})
    return {**_token_dict(t), "token": raw}


@router.delete("/tokens/{tid}")
def delete_token(tid: int, request: Request, user: str = Depends(require_admin), db: Session = Depends(get_db)):
    t = db.get(ApiToken, tid)
    if t is None:
        raise HTTPException(404, "令牌不存在")
    name = t.name
    db.delete(t)
    oplog.log(db, request, user, "api_token_delete", {"name": name})
    forget_api_tokens()
    return {"ok": True}
