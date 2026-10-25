import time

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import oplog
from app.database import get_db
from app.models import Setting, User
from app.security import (check_login_lock, check_setup_code, current_user, forget_roles, make_token, note_login_fail, note_login_ok,
                          pwd, require_admin, role_of)

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
def me(user: str = Depends(current_user)):
    return {"username": user, "role": role_of(user)}


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


class UserPatch(BaseModel):
    role: str | None = Field(None, pattern=ROLE)
    password: str | None = Field(None, min_length=6, max_length=128)


def _user_dict(u: User) -> dict:
    return {"id": u.id, "username": u.username, "role": u.role or "admin", "created": u.created, "last_login": u.last_login}


def _admins(db) -> int:
    return sum(1 for u in db.query(User) if (u.role or "admin") == "admin")


@router.get("/users")
def users(_: str = Depends(require_admin), db: Session = Depends(get_db)):
    return [_user_dict(u) for u in db.query(User).order_by(User.id)]


@router.post("/users")
def add_user(req: UserIn, request: Request, user: str = Depends(require_admin), db: Session = Depends(get_db)):
    if db.query(User).filter(User.username == req.username).first():
        raise HTTPException(400, "用户名已存在")
    u = User(username=req.username, password_hash=pwd.hash(req.password), role=req.role, created=int(time.time()))
    db.add(u)
    oplog.log(db, request, user, "user_add", {"username": req.username, "role": req.role})
    forget_roles()
    return _user_dict(u)


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
    oplog.log(db, request, user, "user_edit", {"username": u.username, "role": req.role, "password": bool(req.password)})
    forget_roles()
    return _user_dict(u)


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
    db.delete(u)
    oplog.log(db, request, user, "user_delete", {"username": name})
    forget_roles()
    return {"ok": True}
