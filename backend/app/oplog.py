"""操作日志：谁、什么时候、从哪里、做了什么。密钥类字段只记“已修改”，不记内容。"""
import json
import time

from fastapi import Request

from app.models import OpLog

SECRET_KEYS = {"singbox_secret", "adguard_password", "password", "old_password", "new_password", "token", "secret"}


def client_ip(request: Request | None) -> str:
    """来访地址。只有 TCP 对端是内网 / 回环地址（前面是自己的反向代理，如 Lucky）时才看 X-Forwarded-For，
    而且只取代理追加在最右边的那一跳——最左边的值客户端可以随便写（以前取最左边，换个头就能绕过登录锁定）"""
    import ipaddress
    if request is None:
        return ""
    peer = request.client.host if request.client else ""
    try:
        p = ipaddress.ip_address(peer)
        behind_proxy = p.is_private or p.is_loopback
    except ValueError:
        behind_proxy = False
    fwd = request.headers.get("x-forwarded-for")
    if behind_proxy and fwd:
        last = fwd.split(",")[-1].strip()
        try:
            ipaddress.ip_address(last)
            return last[:45]
        except ValueError:
            pass
    return peer[:45]


def scrub(d: dict) -> dict:
    return {k: ("***" if k in SECRET_KEYS and v else v) for k, v in d.items() if v is not None}


def log(db, request: Request | None, user: str | None, action: str, detail=None, ok: bool = True, commit: bool = True):
    if isinstance(detail, dict):
        detail = json.dumps(scrub(detail), ensure_ascii=False)
    db.add(OpLog(ts=int(time.time()), user=(user or "")[:64], ip=client_ip(request), action=action[:32],
                 detail=(detail or "")[:2000], ok=1 if ok else 0))
    if commit:
        db.commit()
