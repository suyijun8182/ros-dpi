"""debug16/22：WebDAV 社区共享——本地库导出过滤、≥2 实例聚合、部署量、自学习接入。"""
import json
import time

import pytest

from app.classify.local import local
from app.engine import Engine
from app.models import HostDomainDay
from app.share import webdav_cycle

DAY = 1792900000
HOST = "IP:192.168.8.40"
BASE = "http://nas.local:5005/ros-dpi"


def _engine():
    e = Engine()
    e.set_lan("192.168.8.0/24")
    return e


class _FakeDav:
    """最小 WebDAV 仿真：按文件夹分桶的内存键值 + PROPFIND 列表；记录所有 PUT。
    files 的键是 "<folder>/<name>.json"（和真实 WebDAV 的路径一致）"""

    def __init__(self):
        self.files = {}
        self.puts = []

    def handle(self, method, url, content=None):
        from httpx import Response
        path = str(url).split("/ros-dpi/")[-1].rstrip("/")      # deployments/xxx.json 或 votes/ 或 votes/xxx.json
        if method == "PROPFIND":
            folder = path.rstrip("/")
            names = [k for k in self.files if k.startswith(folder + "/")]
            body = "".join(f"<d:response><d:href>/{n}</d:href></d:response>" for n in names)
            return Response(207, text=f"<d:multistatus>{body}</d:multistatus>")
        if method == "PUT":
            self.puts.append(path)
            self.files[path] = content or b""
            return Response(201)
        if method == "GET":
            if path in self.files:
                return Response(200, content=self.files[path])
            return Response(404)
        if method == "MKCOL":
            return Response(201)
        return Response(200)


def _install(monkeypatch, dav):
    """把 share.py 里的 httpx 模块函数换成 WebDAV 仿真"""
    import httpx

    from app import share as share_mod

    monkeypatch.setattr(share_mod.httpx, "put", lambda url, content=None, **kw: dav.handle("PUT", url, content))
    monkeypatch.setattr(share_mod.httpx, "get", lambda url, **kw: dav.handle("GET", url))
    monkeypatch.setattr(share_mod.httpx, "request", lambda method, url, **kw: dav.handle(method, url))
    del httpx


def test_export_filters_private():
    import app.database as database
    database.connect_from_saved(force=True)
    s = database.SessionLocal()
    try:
        s.query(HostDomainDay).filter(HostDomainDay.host == HOST).delete(synchronize_session=False)
        s.add(HostDomainDay(ts=DAY, host=HOST, domain="93.184.216.34", app="douyin", base=None, bytes=800))
        s.add(HostDomainDay(ts=DAY, host=HOST, domain="192.168.8.5", app="douyin", base=None, bytes=999))      # 私网
        s.add(HostDomainDay(ts=DAY, host=HOST, domain="239.255.255.250", app="douyin", base=None, bytes=999))  # 组播
        s.commit()
        eng = _engine()
        from app import share as share_mod
        entries, _domains = share_mod.export_entries(eng, s)
        ips = {e["ip"] for e in entries}
        assert "93.184.216.34" in ips
        assert "192.168.8.5" not in ips and "239.255.255.250" not in ips
    finally:
        s.query(HostDomainDay).filter(HostDomainDay.host == HOST).delete(synchronize_session=False)
        s.commit()
        s.close()


def test_webdav_aggregates_two_instances(monkeypatch):
    """两个实例各写各的投票文件：≥2 个实例见过的映射进社区层；单实例见过的进不来"""
    import app.database as database
    database.connect_from_saved(force=True)
    dav = _FakeDav()
    _install(monkeypatch, dav)
    s = database.SessionLocal()
    try:
        s.query(HostDomainDay).filter(HostDomainDay.host == HOST).delete(synchronize_session=False)
        s.commit()
        eng = _engine()
        # A 的本机实测：1.2.3.4 → douyin（进入自己的投票文件）
        s.add(HostDomainDay(ts=DAY, host=HOST, domain="1.2.3.4", app="douyin", base=None, bytes=500))
        s.commit()
        # 第一轮：A 写入自己的投票文件；此时没有其它文件，社区层为空
        with database.session() as db:
            res1 = webdav_cycle(eng, db, BASE, "", "")
            db.commit()
        assert res1["deployed"] == 1 and res1["online"] == 1
        assert res1["community_ips"] == 0
        # B 的文件出现在 NAS 上：1.2.3.4 → douyin（与 A 相同）+ 5.6.7.8 → bilibili（只有 B 见过）
        dav.files["votes/IID_B.json"] = json.dumps({
            "version": "0.6.20", "ts": int(time.time()),
            "entries": [{"ip": "1.2.3.4", "app": "douyin", "bytes": 100},
                        {"ip": "5.6.7.8", "app": "bilibili", "bytes": 200}],
            "domains": []}).encode()
        dav.files["deployments/IID_B.json"] = json.dumps(
            {"version": "0.6.20", "ts": int(time.time())}).encode()

        # 第二轮：A 读 B 的文件并聚合
        with database.session() as db:
            res2 = webdav_cycle(eng, db, BASE, "", "")
            db.commit()
        assert res2["deployed"] == 2 and res2["online"] == 2
        assert res2["community_ips"] == 1          # 1.2.3.4 两家都见过
        assert local.ip_app("1.2.3.4") == "douyin"
        assert local.ip_app("5.6.7.8") is None     # 单实例见过的进不了社区层
        assert len(dav.puts) == 4                  # 2 轮 × (deployments + votes)
    finally:
        s.query(HostDomainDay).filter(HostDomainDay.host == HOST).delete(synchronize_session=False)
        s.commit()
        s.close()
        local.reset()
        dav.files.clear()
        dav.puts.clear()


def test_webdav_single_instance_no_community(monkeypatch):
    import httpx

    dav = _FakeDav()
    _install(monkeypatch, dav)
    eng = _engine()
    try:
        local.reset()
        import app.database as database
        database.connect_from_saved(force=True)
        s = database.SessionLocal()
        with database.session() as db:
            res = webdav_cycle(eng, db, BASE, "", "")
            db.commit()
        assert res["deployed"] == 1 and res["online"] == 1
        assert res["community_ips"] == 0           # 没有其它实例 → 社区层空（本地实测本来就优先）
    finally:
        s.close()
        local.reset()
        dav.files.clear()
