"""Fixtures generated with passlib 1.7.4 / python-jose 3.3.0 before migration."""
import pytest
import jwt
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from starlette.requests import Request

from app import security

KEY = "legacy-test-secret-key-32-characters"
TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJsZWdhY3ktdXNlciIsInZlciI6NywiZXhwIjo0MTAyNDQ0ODAwfQ.yKWRip8V_nl7qHinNiDIpJOi4u_t6nnfvgI8ynLUSDg"
HASH = "$2b$12$23X.k2ZjH6zCjDogN0Mjxu.nqlBgfemQQmkYKi2BfLGUNz/yNsnjy"


def test_legacy_password():
    assert security.pwd.verify("test-password-123", HASH)
    assert not security.pwd.verify("wrong-password", HASH)
    assert not security.pwd.verify("password", "malformed")


def test_password_byte_truncation():
    password = "中" * 25
    hashed = security.pwd.hash(password)
    assert security.pwd.verify(password, hashed)
    assert security.pwd.verify("中" * 24 + "different suffix", hashed)


def test_legacy_token(monkeypatch):
    monkeypatch.setattr(security, "secret_key", lambda: KEY)
    monkeypatch.setattr(security, "user_info", lambda name: ("admin", 7) if name == "legacy-user" else None)
    req = Request({"type": "http", "method": "GET", "path": "/api/rules", "headers": []})
    assert security.current_user(req, HTTPAuthorizationCredentials(scheme="Bearer", credentials=TOKEN)) == "legacy-user"


@pytest.mark.parametrize("payload,algorithm", [({"sub": "legacy-user", "exp": 1, "ver": 7}, "HS256"),
    ({"sub": "legacy-user", "exp": 4102444800, "ver": 7}, "HS384"),
    ({"sub": "legacy-user", "exp": 4102444800, "ver": 6}, "HS256")])
def test_invalid_token(monkeypatch, payload, algorithm):
    monkeypatch.setattr(security, "secret_key", lambda: KEY)
    monkeypatch.setattr(security, "user_info", lambda name: ("admin", 7))
    req = Request({"type": "http", "method": "GET", "path": "/api/rules", "headers": []})
    cred = HTTPAuthorizationCredentials(scheme="Bearer", credentials=jwt.encode(payload, KEY, algorithm=algorithm))
    with pytest.raises(HTTPException) as exc:
        security.current_user(req, cred)
    assert exc.value.status_code == 401
