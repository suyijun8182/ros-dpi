"""全站审计：安全类修复（首次设置安装码、通知密钥遮挡与报错脱敏、删号重建后旧 token 失效、跨午夜时段累计）"""
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app import notify, security


def _req(peer, xff=None, code=None):
    h = {}
    if xff:
        h["x-forwarded-for"] = xff
    if code:
        h["x-setup-code"] = code
    return SimpleNamespace(client=SimpleNamespace(host=peer), headers=h)


def test_setup_code_only_for_public_visitors():
    security.check_setup_code(_req("192.168.88.20"))                     # 内网：不需要
    with pytest.raises(HTTPException):
        security.check_setup_code(_req("192.168.88.1", xff="8.8.8.8"))     # 经反代来自公网：要安装码
    security.check_setup_code(_req("192.168.88.1", xff="8.8.8.8", code=security.setup_code()))
    with pytest.raises(HTTPException):
        security.check_setup_code(_req("8.8.4.4", xff="192.168.1.5"))     # 直连公网伪造 XFF 没用


def test_notify_mask_and_scrub():
    cfg = {"telegram": {"bot_token": "123456789:ABCDEFGHIJKLMN", "api_base": "", "proxy": "http://u:pw@p:1080"},
           "webhook": {"headers": [{"key": "Authorization", "value": "Bearer abcdefghijklmnop"}]}}
    m = notify.mask(cfg)
    assert m["telegram"]["bot_token"].endswith("…") and m["telegram"]["proxy"].endswith("…")
    assert m["webhook"]["headers"][0]["value"].endswith("…")
    with pytest.raises(ValueError):    # 改了发送地址却沿用遮住的令牌：拒绝
        notify.unmask({**m["telegram"], "api_base": "https://evil.example"}, cfg["telegram"])
    assert notify.unmask(m["webhook"], cfg["webhook"])["headers"][0]["value"] == "Bearer abcdefghijklmnop"
    s = notify.scrub_error("ConnectError https://api.telegram.org/bot123:ABC/sendMessage?token=xyz")
    assert "123:ABC" not in s and "xyz" not in s


def test_new_user_token_version_random():
    from app.models import User
    col = User.__table__.c.token_version
    vals = {col.default.arg(None) for _ in range(5)}
    assert all(v and v > 0 for v in vals) and len(vals) > 1


def test_audit_window_across_midnight():
    from datetime import datetime

    from app import audit, timeutil
    rule = SimpleNamespace(time_from="22:00", time_to="06:00", days="1234567")
    tz = timeutil.tz()
    late = datetime(2026, 10, 25, 23, 30, tzinfo=tz).timestamp()
    early = datetime(2026, 10, 26, 1, 30, tzinfo=tz).timestamp()
    assert audit.window_start(rule, late) == audit.window_start(rule, early)   # 同一段生效时段
