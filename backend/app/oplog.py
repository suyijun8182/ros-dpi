"""操作日志：谁、什么时候、从哪里、做了什么。密钥类字段只记“已修改”，不记内容。"""
import json
import time

from fastapi import Request

from app.models import OpLog

SECRET_KEYS = {"singbox_secret", "password", "old_password", "new_password", "token", "secret"}


def client_ip(request: Request | None) -> str:
    if request is None:
        return ""
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()[:45]
    return (request.client.host if request.client else "")[:45]


def scrub(d: dict) -> dict:
    return {k: ("***" if k in SECRET_KEYS and v else v) for k, v in d.items() if v is not None}


def log(db, request: Request | None, user: str | None, action: str, detail=None, ok: bool = True, commit: bool = True):
    if isinstance(detail, dict):
        detail = json.dumps(scrub(detail), ensure_ascii=False)
    db.add(OpLog(ts=int(time.time()), user=(user or "")[:64], ip=client_ip(request), action=action[:32],
                 detail=(detail or "")[:2000], ok=1 if ok else 0))
    if commit:
        db.commit()
