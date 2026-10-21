from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.security import current_user, make_token, pwd

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
def setup(req: SetupReq, db: Session = Depends(get_db)):
    if db.query(User).count() > 0:
        raise HTTPException(400, "管理员已存在")
    db.add(User(username=req.username, password_hash=pwd.hash(req.password)))
    db.commit()
    return {"token": make_token(req.username), "username": req.username}


@router.post("/login")
def login(req: Creds, db: Session = Depends(get_db)):
    u = db.query(User).filter(User.username == req.username).first()
    if not u or not pwd.verify(req.password, u.password_hash):
        raise HTTPException(401, "用户名或密码错误")
    return {"token": make_token(u.username), "username": u.username}


@router.get("/me")
def me(user: str = Depends(current_user)):
    return {"username": user}


@router.post("/password")
def change_password(req: PwChange, user: str = Depends(current_user), db: Session = Depends(get_db)):
    u = db.query(User).filter(User.username == user).first()
    if not u or not pwd.verify(req.old_password, u.password_hash):
        raise HTTPException(400, "原密码错误")
    u.password_hash = pwd.hash(req.new_password)
    db.commit()
    return {"ok": True}
