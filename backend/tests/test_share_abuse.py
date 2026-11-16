import asyncio
import gzip
import zlib

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app import share
from app.routers import share as share_router
from test_debug16 import hub  # reuse the isolated hub fixture


def _auth(c):
    r = c.post(share.API + "/register", json={"version": "0.6.28"})
    assert r.status_code == 200
    data = r.json()
    return {"Authorization": f"Bearer {data['instance']}:{data['token']}"}


def test_spoofed_forwarded_for():
    assert share.client_ip("127.0.0.1", "1.1.1.1, 9.9.9.9", None) == "9.9.9.9"


def test_gzip_bomb_stops_inflate(hub, monkeypatch):
    c, _ = hub
    headers = {**_auth(c), "Content-Encoding": "gzip"}
    raw_size = 50 * 1024 * 1024
    compressed = gzip.compress(b" " * raw_size)
    assert 40000 < len(compressed) < 60000
    original = zlib.decompressobj
    produced = []

    class LimitedInflater:
        def __init__(self, *args):
            self.inner = original(*args)

        def decompress(self, data, max_length):
            assert max_length == share.MAX_INFLATED
            out = self.inner.decompress(data, max_length)
            produced.append(len(out))
            return out

        def __getattr__(self, name):
            return getattr(self.inner, name)

    monkeypatch.setattr(zlib, "decompressobj", LimitedInflater)
    r = c.post(share.API + "/report", headers=headers, content=compressed)
    assert r.status_code in (400, 413)
    assert produced and sum(produced) <= share.MAX_INFLATED < raw_size


@pytest.mark.parametrize("chunked", [False, True])
def test_oversized_report_body(hub, monkeypatch, chunked):
    c, _ = hub
    headers = _auth(c)
    monkeypatch.setattr(share, "MAX_BODY", 1024)
    def inflate(*args):
        pytest.fail("oversized body reached decompression")
    monkeypatch.setattr(share, "inflate", inflate)
    content = iter([b"x" * 600] * 3) if chunked else b"x" * 1800
    if chunked:
        headers["Transfer-Encoding"] = "chunked"
    r = c.post(share.API + "/report", headers=headers, content=content)
    assert r.status_code == 413


def test_chunked_read_stops_before_last_chunk():
    reads = []
    async def receive():
        reads.append(1)
        assert len(reads) <= 2
        return {"type": "http.request", "body": b"x" * 600, "more_body": True}
    req = Request({"type": "http", "method": "POST", "path": "/report",
                   "headers": [(b"transfer-encoding", b"chunked")]}, receive)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(share_router._read_body(req, 1024))
    assert exc.value.status_code == 413 and len(reads) == 2


@pytest.mark.parametrize("credentials", [None, "Bearer unregistered:invalid", "wrong-token"])
def test_report_authenticates_before_inflate(hub, monkeypatch, credentials):
    c, _ = hub
    valid = _auth(c)["Authorization"]
    if credentials == "wrong-token":
        credentials = valid.rsplit(":", 1)[0] + ":wrong-token"
    def fail(*args):
        pytest.fail("unauthorized request reached body reading or decompression")
    monkeypatch.setattr(share, "inflate", fail)
    monkeypatch.setattr(share_router, "_read_body", fail)
    headers = {"Content-Encoding": "gzip"}
    if credentials is not None:
        headers["Authorization"] = credentials
    assert c.post(share.API + "/report", headers=headers, content=b"invalid gzip").status_code == 401
