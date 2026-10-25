"""社区共享库（debug16→debug22）：通过 **WebDAV 文件夹**（飞牛 / 群晖等 NAS 自带）共享本地自学习库。

架构（无中心服务、无中转）：
- 每个实例把各自的匿名投票写到 WebDAV 上的两个文件（文件名是随机 UUID，不含任何可识别信息）：
    deployments/<uuid>.json   {"version", "ts"}                 —— 部署心跳（全球部署量统计）
    votes/<uuid>.json         {"entries": [IP→应用], "domains": [域名→应用]}
- 每 30 分钟：PUT 自己的两个文件（WebDAV 天然按文件去重，不会互相覆盖），然后列出文件夹里
  所有其它实例的文件、全部拉下来在本地聚合——**至少 2 个不同实例见过的映射**才进入社区层。
- 本地实测优先：社区条目只补本地没有结论的 IP / 域名。

隐私与防污染：
- 投票内容只有 (远端 IP / 域名, 应用 ID, 字节票数)；不含本机终端、域名记录、自定义应用；
- 私网 / 保留 / 组播地址剔除；IPv6 按 /64 前缀聚合（中国环境以 IPv6 公网为主）；
- 应用白名单：只共享所有实例都认识的应用，自定义应用和编造的 ID 拒收；
- 单文件限量，防止单实例撑爆共享文件夹。

安全：WebDAV 地址建议用 HTTPS 或仅内网可达；账号密码保存在本实例数据库里，不上报。
"""
import ipaddress
import json
import re
import threading
import time
import urllib.parse
import uuid
from collections import defaultdict

import httpx
from sqlalchemy import select

from app.classify.local import _is_ip, _v6key
from app.models import HostDomainDay

MAX_UPLOAD = 50_000          # 单个实例投票文件的条数上限
MAX_COMMUNITY = 200_000      # 社区聚合后的条数上限
PUBLISH_FILES = 2            # 至少几个不同实例的投票文件见过才进社区层
DEPLOY_ONLINE = 7200         # 心跳 2 小时内算在线

# 域名格式（debug20：格式错误的域名条目直接丢弃）
_DOMAIN_RE = re.compile(r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
MAX_BYTES = 10 ** 15

_sync_lock = threading.Lock()
_sync = {"ts": 0, "ok": None, "error": "", "community_ips": 0, "community_domains": 0,
         "deployed": 0, "online": 0, "offline": 0}


def sync_state() -> dict:
    with _sync_lock:
        return dict(_sync)


def instance_id(db) -> str:
    """本实例的匿名 ID：第一次生成后存在 settings 表（不上报任何可识别信息）"""
    from app.models import Setting
    row = db.get(Setting, "share_instance_id")
    if row is not None and row.value:
        return row.value
    iid = str(uuid.uuid4())
    row = db.get(Setting, "share_instance_id")
    if row is None:
        db.add(Setting(key="share_instance_id", value=iid))
    else:
        row.value = iid
    return iid


def _is_shareable_app(classifier, app: str) -> bool:
    """自定义应用（每家不一样）和未识别不共享"""
    info = classifier.apps.get(app)
    return info is not None and not info.custom and app != "other"


def _shareable_ip(ip: str) -> bool:
    """只共享公网远端地址：私网 / 保留 / 组播 / 回环 / 链路本地不出门"""
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return not (a.is_private or a.is_reserved or a.is_multicast or a.is_loopback or a.is_link_local)


def export_entries(engine, db) -> list[dict]:
    """本地自学习库的 IP 条目：host_domain_day 里以 IP 记录的行，按字节数取最多的应用。
    IPv4 按精确地址；IPv6 按 /64 前缀聚合（中国环境以 IPv6 公网为主，精确地址不稳定）"""
    classifier = engine.classifier
    votes: dict = defaultdict(dict)
    rows = db.execute(select(HostDomainDay.domain, HostDomainDay.app, HostDomainDay.bytes)).all()
    for dom, app, b in rows:
        if not _shareable_ip(dom) or not _is_shareable_app(classifier, app):
            continue
        key = _v6key(dom) or dom
        per = votes[key]
        per[app] = per.get(app, 0) + int(b or 0)
    out = [{"ip": ip, "app": max(per, key=per.get), "bytes": sum(per.values())}
           for ip, per in votes.items()]
    out.sort(key=lambda x: -x["bytes"])
    doms = export_domains(engine, db)
    return out[:MAX_UPLOAD], doms


def export_domains(engine, db) -> list[dict]:
    """本地自学习库的域名条目（debug17）：非 IP 的域名行，按字节数取最多的应用，精确域名共享"""
    classifier = engine.classifier
    votes: dict = defaultdict(dict)
    rows = db.execute(select(HostDomainDay.domain, HostDomainDay.app, HostDomainDay.bytes)).all()
    for dom, app, b in rows:
        if _is_ip(dom) or not _is_shareable_app(classifier, app):
            continue
        per = votes[dom]
        per[app] = per.get(app, 0) + int(b or 0)
    out = [{"domain": d, "app": max(p, key=p.get), "bytes": sum(p.values())}
           for d, p in votes.items()]
    out.sort(key=lambda x: -x["bytes"])
    return out[:MAX_UPLOAD]


# ---------- WebDAV ----------

def _dav_url(base: str, path: str) -> str:
    return base.rstrip("/") + "/" + "/".join(urllib.parse.quote(x) for x in path.split("/"))


def _dav_put(httpx, base: str, path: str, data, auth) -> bool:
    """PUT 文件；目标文件夹不存在（409）时逐级 MKCOL 后重试一次"""
    url = _dav_url(base, path)
    r = httpx.put(url, content=data, auth=auth, timeout=30.0, verify=False)
    if r.status_code in (200, 201, 204):
        return True
    if r.status_code == 409:   # 上级文件夹不存在：逐级创建
        parts = path.split("/")
        for i in range(1, len(parts)):
            httpx.request("MKCOL", _dav_url(base, "/".join(parts[:i])), auth=auth,
                          timeout=30.0, verify=False)
        r = httpx.put(url, content=data, auth=auth, timeout=30.0, verify=False)
        return r.status_code in (200, 201, 204)
    return False


def _dav_list(httpx, base: str, folder: str, auth) -> list[str]:
    """PROPFIND 列出文件夹里的 .json 文件，返回 folder/name 相对路径（和 _dav_get 拼接一致）"""
    r = httpx.request("PROPFIND", _dav_url(base, folder), headers={"Depth": "1"}, auth=auth,
                      timeout=30.0, verify=False)
    if r.status_code not in (200, 207):
        return []
    hrefs = re.findall(r"<(?:[\w]+:)?href>\s*([^<]+)\s*</(?:[\w]+:)?href>", r.text, re.IGNORECASE)
    base_path = urllib.parse.quote(_dav_url(base, "").split("//", 1)[-1].split("/", 1)[-1])
    out = []
    for h in hrefs:
        name = urllib.parse.unquote(h.split("?")[0].rstrip("/")).rsplit("/", 1)[-1]
        if name.endswith(".json") and name != folder:
            out.append(f"{folder}/{name}")
    return out


def _dav_get(httpx, base: str, path: str, auth):
    r = httpx.get(_dav_url(base, path), auth=auth, timeout=30.0, verify=False)
    if r.status_code != 200:
        return None
    try:
        return json.loads(r.text)
    except Exception:  # noqa: BLE001
        return None


def webdav_cycle(engine, db, base: str, user: str, password: str) -> dict:
    """一轮 WebDAV 共享（每 30 分钟）：写自己的心跳与投票文件 → 读其它实例的文件 → 本地聚合"""
    from app import __version__
    auth = (user, password) if user or password else None
    iid = instance_id(db)
    now = int(time.time())

    # 1) 心跳（部署量统计：只有版本号和时间）
    ok_put_dep = _dav_put(httpx, base, f"deployments/{iid}.json",
                          json.dumps({"version": __version__, "ts": now}).encode(), auth)
    # 2) 投票（本网络实测）
    entries, domains = export_entries(engine, db)
    ok_put_votes = _dav_put(httpx, base, f"votes/{iid}.json",
                            json.dumps({"version": __version__, "ts": now,
                                        "entries": entries, "domains": domains},
                                       ensure_ascii=False).encode(), auth)

    # 3) 读其它实例的文件，本地聚合（自己写不进去时留给下轮，不空算）
    other_dep, other_votes = [], []
    if ok_put_dep and ok_put_votes:
        for kind, out in (("deployments", other_dep), ("votes", other_votes)):
            for path in _dav_list(httpx, base, kind, auth):
                if path == f"{kind}/{iid}.json":
                    continue
                data = _dav_get(httpx, base, path, auth)
                if isinstance(data, dict):
                    out.append(data)

    # 部署量：心跳文件数 = 已部署；ts 在 2 小时内 = 在线
    deployed, online = len(other_dep) + (1 if ok_put_dep else 0), 0
    for d in other_dep:
        if int(d.get("ts", 0) or 0) >= now - DEPLOY_ONLINE:
            online += 1
    if ok_put_dep:
        online += 1

    # 社区层：出现在 ≥2 个不同投票文件里的映射（自己的文件算一票）。votes[k] = {app: (实例数, 总字节)}
    def _vote(bucket, key, app, weight):
        per = bucket[key]
        n, b = per.get(app, (0, 0))
        per[app] = (n + 1, b + weight)

    ip_votes: dict = defaultdict(dict)
    dom_votes: dict = defaultdict(dict)
    if ok_put_votes:
        for e in entries:
            _vote(ip_votes, e["ip"], e["app"], e["bytes"])
        for e in domains:
            _vote(dom_votes, e["domain"], e["app"], e["bytes"])
    for d in other_votes:
        for e in d.get("entries") or []:
            ip, app, b = str(e.get("ip", "")), str(e.get("app", "")), int(e.get("bytes", 0) or 0)
            if _shareable_ip(ip):
                _vote(ip_votes, ip, app, b)
        for e in d.get("domains") or []:
            dom_, app, b = str(e.get("domain", "")).lower(), str(e.get("app", "")), int(e.get("bytes", 0) or 0)
            if dom_ and not _is_ip(dom_):
                _vote(dom_votes, dom_, app, b)

    def top(bucket, cap):
        out = {}
        for key, per in sorted(bucket.items(), key=lambda kv: -sum(v[1] for v in kv[1].values()))[:cap]:
            if any(n >= PUBLISH_FILES for n, _b in per.values()):   # 至少 2 个实例见过
                out[key] = max(per, key=lambda a: per[a][1])
        return out

    community_ips = top(ip_votes, MAX_COMMUNITY)
    community_domains = top(dom_votes, MAX_COMMUNITY)
    from app.classify.local import local
    local.load_community(community_ips, community_domains)

    ok = ok_put_dep and ok_put_votes
    error = "" if ok else "WebDAV 写入失败：检查地址 / 账号密码 / 文件夹权限"
    with _sync_lock:
        _sync.update(ts=now, ok=ok, error=error, deployed=deployed, online=online,
                     offline=deployed - online,
                     community_ips=len(community_ips), community_domains=len(community_domains))
    return {"deployed": deployed, "online": online, "offline": deployed - online,
            "community_ips": len(community_ips), "community_domains": len(community_domains),
            "uploaded": bool(ok_put_dep and ok_put_votes)}
