"""RouterOS connections must not leak into an unrelated system proxy."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import httpx
import pytest

from app.ros_poller import RosPoller, _explain


def test_router_bypasses_environment_proxy(monkeypatch):
    paths = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            paths.append(self.path)
            # A proxy receives an absolute URL; the router receives a path.
            proxy = self.path.startswith('http://')
            self.send_response(400 if proxy else 200)
            self.end_headers()
            self.wfile.write(json.dumps({'name': 'router', 'version': '7.24.2'}).encode())

        def log_message(self, *args):
            pass

    with ThreadingHTTPServer(('127.0.0.1', 0), Handler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        url = f'http://127.0.0.1:{server.server_port}'
        for key in ('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY'):
            monkeypatch.setenv(key, url)
        monkeypatch.setenv('NO_PROXY', '')
        try:
            result = RosPoller(SimpleNamespace()).probe(url, 'u', 'p', False)
            assert result['ok'], result
            assert paths == ['/rest/system/identity', '/rest/system/resource']
        finally:
            server.shutdown()
            thread.join(timeout=2)


@pytest.mark.parametrize('code', [400, 401, 403, 500])
def test_error_identifies_failed_path_without_url_credentials(code):
    req = httpx.Request('GET', 'http://user:secret@router/rest/ip/route?token=secret')
    resp = httpx.Response(code, json={'detail': 'not enough permissions (9)'}, request=req)
    msg = _explain(httpx.HTTPStatusError('error', request=req, response=resp))
    assert '/rest/ip/route' in msg
    assert 'secret' not in msg
    assert str(code) in msg
