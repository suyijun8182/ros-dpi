import time

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import oplog
from app.database import get_db
from app.models import User
from app.security import current_user, forget_roles, make_token, pwd, require_admin, role_of

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
    db.add(User(username=req.username, password_hash=pwd.hash(req.password), role="admin", created=int(time.time())))
    oplog.log(db, request, req.username, "setup_admin")
    forget_roles()
    return {"token": make_token(req.username), "username": req.username, "role": "admin"}


@router.post("/login")
def login(req: Creds, request: Request, db: Session = Depends(get_db)):
    u = db.query(User).filter(User.username == req.username).first()
    if not u or not pwd.verify(req.password, u.password_hash):
        oplog.log(db, request, req.username, "login", ok=False)
        raise HTTPException(401, "用户名或密码错误")
    u.last_login = int(time.time())
    oplog.log(db, request, u.username, "login")
    return {"token": make_token(u.username), "username": u.username, "role": u.role or "admin"}


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
    oplog.log(db, request, user, "change_password")
    return {"ok": True}


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
