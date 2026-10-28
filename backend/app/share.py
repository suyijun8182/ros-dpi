"""社区共享库（debug16 → 0.6.21 重做）：各部署实例互相共享本地自学习库的实测结论，项目自带社区主站，不依赖第三方存储。

架构：
- 社区主站：和普通实例是同一套程序，部署时设 SHARE_HUB=true（只有主站这样设）。它接收各实例的上报，
  聚合后发布社区库与全球部署量（/api/share/v1/*，见 routers/share.py）。主站自己的投票在进程内直接计入，
  不经过网络（之前的中转要通过公网地址访问自己，NAT 回环不通时永远同步不上）。
- 普通实例：默认参与共享，主站地址内置（SHARE_HUB_URL 可改成自建的私有社区）。每 30 分钟一轮：
  首次注册领取令牌 → 上报心跳（每 6 小时附带一次投票）→ 拉取社区库（没变化时主站回 304）→ 拉取部署量。
  社区库缓存在 DATA_DIR/share_community.json，主站暂时不可达时继续用上次的版本。

隐私：
- 投票只有 (远端 IP / 域名, 应用 ID, 字节票数)；不含本机终端、访问记录、自定义应用；
- 私网 / 保留 / 组播地址剔除；IPv6 按 /64 前缀聚合；
- 主站不保存来源 IP，只保存来源网络（IPv4 /24、IPv6 /56）的加盐哈希。

防污染：
- 每个实例有主站发的令牌，别人不能冒充或覆盖它的投票；同一来源网络每天限注册次数；投票每小时最多收一次；
- 一条映射要有 ≥2 个**不同来源网络**的实例投给同一个应用，并且票数多于其它应用，才进社区库——
  一个人伪造再多实例 ID，来自同一个网络也只算一票；
- 应用白名单（自定义应用、编造的 ID 拒收）、域名格式校验、单实例条数上限、字节票数上限。
"""
import gzip
import hashlib
import hmac
import ipaddress
import json
import os
import re
import secrets
import threading
import time
import uuid
from collections import defaultdict

import httpx
from sqlalchemy import delete, func, select

from app.classify.local import _is_ip, _v6key
from app.config import get_settings
from app.models import CustomRule, HostDomainDay, Setting, ShareDeployment, ShareDomain, ShareEntry

API = "/api/share/v1"
MAX_UPLOAD = 50_000          # 单次上报 IP / 域名各自的条数上限
MAX_COMMUNITY = 200_000      # 社区库 IP / 域名各自的条数上限
PUBLISH_NETS = 2             # 至少几个不同来源网络投给同一应用才发布
DEPLOY_ONLINE = 7200         # 2 小时内有心跳算在线
DEPLOY_KEEP = 90 * 86400     # 90 天没心跳的实例不再计入部署量
ENTRY_TTL = 30 * 86400       # 30 天没再上报投票的实例，投票作废
VOTES_EVERY = 6 * 3600       # 客户端每 6 小时附带一次投票（心跳每轮都发）
VOTES_MIN_GAP = 3600         # 主站对同一实例的投票每小时最多收一次
REGISTER_PER_NET = 5         # 同一来源网络每天最多注册几个实例
REGISTER_PER_BLOCK = 20      # 同一 IPv6 /48（隧道商一次给一整段）每天最多注册几个实例
VOTERS_PER_NET = 2           # 同一来源网络最多几个实例的投票被收下（一户人家通常只有一台）
MAX_VOTE_ROWS = 5_000_000    # 主站投票总行数上限：超过后只接受已有投票的实例更新，不再收新实例
VOTE_MIN_AGE = 86400         # 实例注册满 1 天，它的投票才参与计票（刚注册的一批伪造实例不能立刻投毒）
MAX_BODY = 8 * 1024 * 1024   # 上报请求体上限（压缩后）
MAX_INFLATED = 16 * 1024 * 1024  # 解压后上限，防压缩炸弹（5 万 IP + 5 万域名约 6MB）
MAX_REGISTER_BODY = 4096     # 注册请求只有版本号
LIB_REBUILD_GAP = 60         # 社区库最快每分钟重建一次
MAX_BYTES = 10 ** 15         # 单条字节票数上限
HUB_NET = "hub"              # 主站自己的投票的来源网络标记

# 域名格式：格式错误的域名条目直接丢弃
_DOMAIN_RE = re.compile(r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")


class ShareError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status, self.detail = status, detail


# ---------- 共用 ----------

_sync_lock = threading.Lock()
_sync = {"ts": 0, "ok": None, "error": "", "community_ips": 0, "community_domains": 0,
         "total": None, "online": None, "offline": None}
_client = {"votes_ts": 0, "etag": ""}


def sync_state() -> dict:
    with _sync_lock:
        return dict(_sync)


def _set_sync(**kw):
    with _sync_lock:
        _sync.update(kw)


def is_hub() -> bool:
    return bool(get_settings().share_hub)


def hub_url(db=None) -> str:
    """社区主站地址：网页填写的优先（debug23：可以改用自己 VPS 上的主站），其次环境变量 / 内置默认"""
    saved = _setting(db, "share_hub_url") if db is not None else ""
    return (saved or get_settings().share_hub_url or "").strip().rstrip("/")


def default_hub_url() -> str:
    return (get_settings().share_hub_url or "").strip().rstrip("/")


def sharing_on(db) -> bool:
    """共享识别库的总开关（debug16 第 3 条）：默认打开；关闭后不心跳、不上报、不拉取（主站不受影响，照常服务其它实例）"""
    row = db.get(Setting, "share_enabled")
    if row is not None and row.value is not None:
        return row.value == "1"
    return bool(get_settings().share_enabled)


def _setting(db, key: str) -> str:
    row = db.get(Setting, key)
    return row.value if row is not None and row.value else ""


def _put_setting(db, key: str, value: str):
    row = db.get(Setting, key)
    if row is None:
        db.add(Setting(key=key, value=value))
    else:
        row.value = value


def _is_shareable_app(classifier, app: str) -> bool:
    """自定义应用（每家不一样）、未识别和笼统结论（HTTPS / 国内网络……）不共享"""
    from app.reclass import _vague
    info = classifier.apps.get(app)
    return info is not None and not info.custom and app != "other" and not _vague(classifier, app)


def _shareable_ip(ip: str) -> bool:
    """只共享公网远端地址：私网 / 保留 / 组播 / 回环 / 链路本地不出门"""
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return not (a.is_private or a.is_reserved or a.is_multicast or a.is_loopback or a.is_link_local)


def _under(dom: str, patterns: set[str]) -> bool:
    """dom 是不是 patterns 里某个域名本身或它的子域名"""
    parts = dom.split(".")
    return any(".".join(parts[i:]) in patterns for i in range(len(parts)))


def export_entries(engine, db) -> tuple[list[dict], list[dict]]:
    """本地自学习库整理成投票：host_domain_day 里的行按字节数取最多的应用。
    IP 条目 IPv4 按精确地址、IPv6 按 /64 前缀（精确地址在不同网络间几乎不重复，凑不满投票）；域名条目按精确域名"""
    classifier = engine.classifier
    ip_votes: dict = defaultdict(dict)
    dom_votes: dict = defaultdict(dict)
    # 手动归类的域名默认不贡献（debug26）：没勾「贡献给社区」的域名规则命中的域名一律不报
    private = {r.pattern for r in db.scalars(select(CustomRule).where(CustomRule.kind == "domain"))
               if not r.share}
    rows = db.execute(select(HostDomainDay.domain, HostDomainDay.app, func.sum(HostDomainDay.bytes))
                      .group_by(HostDomainDay.domain, HostDomainDay.app)).all()
    for dom, app, b in rows:
        if not dom or not _is_shareable_app(classifier, app):
            continue
        if _is_ip(dom):
            if not _shareable_ip(dom):
                continue
            per = ip_votes[_v6key(dom) or dom]
        else:
            dom = dom.lower().rstrip(".")
            if private and _under(dom, private):
                continue
            per = dom_votes[dom]
        per[app] = per.get(app, 0) + int(b or 0)

    def pack(votes, field):
        out = [{field: k, "app": max(p, key=p.get), "bytes": sum(p.values())} for k, p in votes.items()]
        out.sort(key=lambda x: -x["bytes"])
        return out[:MAX_UPLOAD]
    return pack(ip_votes, "ip"), pack(dom_votes, "domain")


def apply_library(data: dict) -> tuple[int, int]:
    """把社区库并入本地自学习库的社区层（本地实测优先，社区只补空白）。返回 (IP 条数, 域名条数)"""
    from app.classify.local import local
    ips, doms = {}, {}
    for e in (data or {}).get("entries") or []:
        if not isinstance(e, dict):
            continue
        ip, app = str(e.get("ip", "")), str(e.get("app", ""))
        if app and len(app) <= 48 and _shareable_ip(ip[:-3] if ip.endswith("/64") else ip):
            ips[ip] = app
    for e in (data or {}).get("domains") or []:
        if not isinstance(e, dict):
            continue
        dom, app = str(e.get("domain", "")).lower().rstrip("."), str(e.get("app", ""))
        if app and len(app) <= 48 and _DOMAIN_RE.match(dom):
            doms[dom] = app
    local.load_community(ips, doms)
    return len(ips), len(doms)


def _cache_path() -> str:
    return os.path.join(os.environ.get("DATA_DIR", "data"), "share_community.json")


def load_cached_library():
    """启动时先用上次拉到的社区库，不用等第一轮同步；主站暂时不可达时也一直有数据"""
    try:
        with open(_cache_path(), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return
    n_ip, n_dom = apply_library(data)
    _client["etag"] = str(data.get("etag") or "")
    _set_sync(community_ips=n_ip, community_domains=n_dom)


def _save_cache(data: dict, etag: str):
    try:
        os.makedirs(os.path.dirname(_cache_path()) or ".", exist_ok=True)
        tmp = _cache_path() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({**data, "etag": etag}, f, ensure_ascii=False)
        os.replace(tmp, _cache_path())
    except OSError as e:
        print(f"[share] 社区库缓存写入失败：{e}", flush=True)


# ---------- 社区主站 ----------

def _salt(db) -> str:
    salt = _setting(db, "share_salt")
    if not salt:
        salt = secrets.token_hex(16)
        _put_setting(db, "share_salt", salt)
        db.flush()     # 同一个事务里第二次取盐（net_of 之后 block_of）要能读到，不能再插一行
    return salt


def block_of(db, ip: str) -> str:
    """IPv6 来源的 /48 段哈希（注册限额用；IPv4 就是 /24，和 net_of 一样）"""
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return "unknown"
    net = ipaddress.ip_network(f"{a}/{24 if a.version == 4 else 48}", strict=False)
    return hashlib.sha256(f"{_salt(db)}|{net}".encode()).hexdigest()[:16]


def net_of(db, ip: str) -> str:
    """来源网络的加盐哈希（IPv4 /24、IPv6 /56）：同一网络里伪造多个实例也只算一票；主站不保存来源 IP 本身。
    IPv6 按 /56：国内家庭宽带一般分到 /56 或 /60，按 /48 会把几百户人家算成同一个网络"""
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return "unknown"
    net = ipaddress.ip_network(f"{a}/{24 if a.version == 4 else 56}", strict=False)
    return hashlib.sha256(f"{_salt(db)}|{net}".encode()).hexdigest()[:16]


def client_ip(peer: str, forwarded: str | None, real_ip: str | None) -> str:
    """主站看到的来源地址。直接暴露在公网时用 TCP 对端；对端是可信反向代理（默认：内网 / 回环地址，
    或 SHARE_TRUSTED_PROXIES 列出的地址）时，只取代理追加在 X-Forwarded-For **最右边**的那一跳——
    更左边的值是客户端自己写的，可以伪造；最右一跳不是公网地址就退回 TCP 对端，不再往左找"""
    try:
        p = ipaddress.ip_address(peer)
    except ValueError:
        return peer
    trusted = [x.strip() for x in (get_settings().share_trusted_proxies or "").split(",") if x.strip()]
    if trusted:
        behind_proxy = any(p in ipaddress.ip_network(t, strict=False) for t in trusted)
    else:
        behind_proxy = p.is_private or p.is_loopback
    if not behind_proxy:
        return peer
    hops = [x.strip() for x in (forwarded or "").split(",") if x.strip()]
    if hops:
        return hops[-1] if _shareable_ip(hops[-1]) else peer
    if real_ip and _shareable_ip(real_ip.strip()):
        return real_ip.strip()
    return peer


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def register(db, net: str, version: str, block: str | None = None) -> tuple[str, str]:
    """主站：登记一个新实例并发放令牌（调用方提交事务）。同一来源网络每天限 REGISTER_PER_NET 个，
    同一 IPv6 /48 每天限 REGISTER_PER_BLOCK 个"""
    now = int(time.time())
    q = select(func.count()).select_from(ShareDeployment).where(ShareDeployment.first_seen >= now - 86400)
    if net != HUB_NET:
        if (db.scalar(q.where(ShareDeployment.net == net)) or 0) >= REGISTER_PER_NET:
            raise ShareError(429, "注册太频繁，请明天再试")
        if block and (db.scalar(q.where(ShareDeployment.block == block)) or 0) >= REGISTER_PER_BLOCK:
            raise ShareError(429, "注册太频繁，请明天再试")
    iid, token = str(uuid.uuid4()), secrets.token_urlsafe(32)
    db.add(ShareDeployment(instance=iid, version=version[:16], first_seen=now, last_seen=now,
                           token_hash=_hash_token(token), net=net, block=block or net))
    return iid, token


def authenticate(db, auth_header: str | None) -> ShareDeployment:
    """主站：校验 Authorization: Bearer <实例ID>:<令牌>"""
    raw = (auth_header or "").removeprefix("Bearer ").strip()
    iid, _, token = raw.partition(":")
    row = db.get(ShareDeployment, iid[:36]) if iid and token else None
    if row is None or not row.token_hash or not hmac.compare_digest(row.token_hash, _hash_token(token)):
        raise ShareError(401, "实例未注册或令牌无效")
    return row


def _clamp_bytes(v) -> int:
    try:
        return min(max(int(v or 0), 0), MAX_BYTES)
    except (TypeError, ValueError):
        return 0


def report(db, row: ShareDeployment, net: str, body: dict, classifier) -> dict:
    """主站：记录一次上报（调用方提交事务）。心跳每次都记；带了投票时整份替换该实例的旧投票。
    应用白名单：只收主站也认识的内置应用，自定义应用和编造的 ID 拒收"""
    now = int(time.time())
    row.last_seen, row.net = now, net
    row.version = str(body.get("version") or "")[:16]
    entries, domains = body.get("entries"), body.get("domains")
    if not isinstance(entries, list) and not isinstance(domains, list):
        return {"ok": True, "accepted": 0}
    if row.last_votes and now - row.last_votes < VOTES_MIN_GAP:
        return {"ok": True, "accepted": 0, "skipped": "投票每小时最多收一次"}
    if net != HUB_NET and not row.last_votes:
        # 新投票者：同一网络已有 VOTERS_PER_NET 个实例在投票、或主站投票总量已满时，只记心跳
        voters = db.scalar(select(func.count()).select_from(ShareDeployment)
                           .where(ShareDeployment.net == net, ShareDeployment.last_votes.is_not(None),
                                  ShareDeployment.instance != row.instance)) or 0
        if voters >= VOTERS_PER_NET:
            return {"ok": True, "accepted": 0, "skipped": "同一网络的投票实例已满"}
        total = (db.scalar(select(func.count()).select_from(ShareEntry)) or 0) +             (db.scalar(select(func.count()).select_from(ShareDomain)) or 0)
        if total >= MAX_VOTE_ROWS:
            return {"ok": True, "accepted": 0, "skipped": "主站投票总量已满"}
    ips: dict = {}
    for e in (entries or [])[:MAX_UPLOAD]:
        if not isinstance(e, dict):
            continue
        ip, app = str(e.get("ip", "")), str(e.get("app", ""))
        base = ip[:-3] if ip.endswith("/64") else ip
        if not _shareable_ip(base) or not _is_shareable_app(classifier, app):
            continue
        ips[_v6key(base) or base] = (app, _clamp_bytes(e.get("bytes")))
    doms: dict = {}
    for e in (domains or [])[:MAX_UPLOAD]:
        if not isinstance(e, dict):
            continue
        dom, app = str(e.get("domain", "")).lower().rstrip("."), str(e.get("app", ""))
        if not _DOMAIN_RE.match(dom) or not _is_shareable_app(classifier, app):
            continue
        doms[dom] = (app, _clamp_bytes(e.get("bytes")))
    db.execute(delete(ShareEntry).where(ShareEntry.reporter == row.instance))
    db.execute(delete(ShareDomain).where(ShareDomain.reporter == row.instance))
    db.add_all([ShareEntry(ip=k, app=a, reporter=row.instance, bytes=b, ts=now) for k, (a, b) in ips.items()])
    db.add_all([ShareDomain(domain=k, app=a, reporter=row.instance, bytes=b, ts=now) for k, (a, b) in doms.items()])
    row.last_votes = now
    _lib["dirty"] = True
    return {"ok": True, "accepted": len(ips) + len(doms)}


def purge(db):
    """主站：清掉 90 天没心跳的实例、30 天没更新的投票（调用方提交事务）"""
    now = int(time.time())
    db.execute(delete(ShareDeployment).where(ShareDeployment.last_seen < now - DEPLOY_KEEP))
    n = db.execute(delete(ShareEntry).where(ShareEntry.ts < now - ENTRY_TTL)).rowcount or 0
    n += db.execute(delete(ShareDomain).where(ShareDomain.ts < now - ENTRY_TTL)).rowcount or 0
    if n:
        _lib["dirty"] = True


def _aggregate(rows, nets: dict) -> dict:
    """按来源网络计票：每个键选投票网络最多的应用（平票看字节），网络数 ≥ PUBLISH_NETS 且多于第二名才发布"""
    votes: dict = defaultdict(lambda: defaultdict(lambda: [set(), 0]))
    for key, app, reporter, b in rows:
        net = nets.get(reporter)
        if net is None:          # 已被清理的实例、0.6.20 以前的旧中转留下的投票不算
            continue
        v = votes[key][app]
        v[0].add(net)
        v[1] += int(b or 0)
    out = []
    for key, per in votes.items():
        ranked = sorted(per.items(), key=lambda kv: (len(kv[1][0]), kv[1][1]), reverse=True)
        top_app, (top_nets, top_bytes) = ranked[0]
        runner = len(ranked[1][1][0]) if len(ranked) > 1 else 0
        if len(top_nets) >= PUBLISH_NETS and len(top_nets) > runner:
            out.append((top_bytes, key, top_app))
    out.sort(reverse=True)
    return {key: app for _b, key, app in out[:MAX_COMMUNITY]}


def build_library(db) -> dict:
    # 只有注册满 VOTE_MIN_AGE 的实例参与计票（主站自己除外）
    aged = int(time.time()) - VOTE_MIN_AGE
    nets = {i: n for i, n, first in db.execute(select(ShareDeployment.instance, ShareDeployment.net,
                                                      ShareDeployment.first_seen)).all()
            if n and (n == HUB_NET or first <= aged)}
    ips = _aggregate(db.execute(select(ShareEntry.ip, ShareEntry.app, ShareEntry.reporter, ShareEntry.bytes)).all(), nets)
    doms = _aggregate(db.execute(select(ShareDomain.domain, ShareDomain.app, ShareDomain.reporter,
                                        ShareDomain.bytes)).all(), nets)
    return {"version": 1, "generated": int(time.time()),
            "entries": [{"ip": k, "app": v} for k, v in sorted(ips.items())],
            "domains": [{"domain": k, "app": v} for k, v in sorted(doms.items())]}


_lib_lock = threading.Lock()
_lib = {"dirty": True, "ts": 0, "etag": "", "json": b"", "gzip": b"", "data": None}


def library(db) -> dict:
    """主站：当前社区库（有新投票时最快每分钟重建一次），返回 {etag, json, gzip, data}"""
    with _lib_lock:
        if _lib["data"] is None or (_lib["dirty"] and time.time() - _lib["ts"] >= LIB_REBUILD_GAP):
            data = build_library(db)
            raw = json.dumps({k: data[k] for k in ("version", "entries", "domains")}, ensure_ascii=False,
                             separators=(",", ":")).encode()
            body = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode()
            _lib.update(dirty=False, ts=time.time(), etag='"' + hashlib.sha256(raw).hexdigest()[:32] + '"',
                        json=body, gzip=gzip.compress(body, 6), data=data)
        return dict(_lib)


def reset_library_cache():
    """测试用"""
    with _lib_lock:
        _lib.update(dirty=True, ts=0, etag="", json=b"", gzip=b"", data=None)
    _client.update(votes_ts=0, etag="")


def stats(db) -> dict:
    """全球部署量（公开）：已部署 = 90 天内有心跳的实例，在线 = 2 小时内有心跳"""
    now = int(time.time())
    # 只数 0.6.21 起注册过的实例：旧中转（0.6.10~0.6.19）留下的无令牌心跳不计，否则升级后会重复计数
    q = select(func.count()).select_from(ShareDeployment).where(ShareDeployment.token_hash.is_not(None))
    total = db.scalar(q.where(ShareDeployment.last_seen >= now - DEPLOY_KEEP)) or 0
    online = db.scalar(q.where(ShareDeployment.last_seen >= now - DEPLOY_ONLINE)) or 0
    return {"total": total, "online": online, "offline": total - online}


def inflate(body: bytes, encoding: str | None) -> dict:
    """主站：解析上报请求体（可 gzip 压缩），限制解压后大小"""
    if len(body) > MAX_BODY:
        raise ShareError(413, "上报内容太大")
    if (encoding or "").lower() == "gzip":
        import zlib
        d = zlib.decompressobj(16 + zlib.MAX_WBITS)
        try:
            out = d.decompress(body, MAX_INFLATED)
        except zlib.error:
            raise ShareError(400, "上报内容解压失败") from None
        if d.unconsumed_tail:
            raise ShareError(413, "上报内容太大")
        body = out
    # 条目数上限先粗算：JSON 里每个对象一个 "{"，远超上限就不解析（防小包撑出几百万个 dict）
    if body.count(b"{") > 2 * MAX_UPLOAD + 16:
        raise ShareError(413, "上报条目太多")
    try:
        data = json.loads(body or b"{}")
    except ValueError:
        raise ShareError(400, "上报内容不是 JSON") from None
    if not isinstance(data, dict):
        raise ShareError(400, "上报内容格式不对")
    return data


def hub_cycle(engine, db) -> dict:
    """主站自己的一轮：投票在进程内直接计入（不经网络）→ 清理过期 → 重建社区库并用到本机"""
    from app import __version__
    iid = _setting(db, "share_hub_instance")
    row = db.get(ShareDeployment, iid) if iid else None
    if row is None:
        iid, _token = register(db, HUB_NET, __version__)
        _put_setting(db, "share_hub_instance", iid)
        db.flush()
        row = db.get(ShareDeployment, iid)
    body: dict = {"version": __version__}
    on = sharing_on(db)
    if on and (not row.last_votes or time.time() - row.last_votes >= VOTES_EVERY):
        body["entries"], body["domains"] = export_entries(engine, db)
    elif not on:
        # 主站关掉“参与共享”：照常服务其它实例，只是不再贡献自己的投票、本机也不用社区库
        db.execute(delete(ShareEntry).where(ShareEntry.reporter == iid))
        db.execute(delete(ShareDomain).where(ShareDomain.reporter == iid))
        row.last_votes = None
        _lib["dirty"] = True
    report(db, row, HUB_NET, body, engine.classifier)
    purge(db)
    db.flush()
    lib = library(db)
    if on:
        n_ip, n_dom = apply_library(lib["data"])
    else:
        from app.classify.local import local
        local.load_community({}, {})
        n_ip = n_dom = 0
    st = stats(db)
    _set_sync(ts=int(time.time()), ok=True, error="", community_ips=n_ip, community_domains=n_dom, **st)
    return {**st, "community_ips": n_ip, "community_domains": n_dom}


# ---------- 普通实例 ----------

def _http() -> httpx.Client:
    from app import __version__
    return httpx.Client(verify=get_settings().share_verify_tls, timeout=30.0, follow_redirects=False,
                        headers={"User-Agent": f"ros-dpi/{__version__}"})


def _err(e: Exception) -> str:
    if isinstance(e, httpx.HTTPStatusError):
        try:
            detail = e.response.json().get("detail") or ""
        except ValueError:
            detail = ""
        return f"主站返回 {e.response.status_code}" + (f"：{detail}" if detail else "")
    if isinstance(e, httpx.ConnectError) and "CERTIFICATE" in str(e).upper():
        return "主站证书校验失败（私有社区用自签证书时设 SHARE_VERIFY_TLS=false）"
    if isinstance(e, ShareError):
        return e.detail
    msg = str(e).lower()
    if isinstance(e, httpx.ConnectError) and ("errno 101" in msg or "unreachable" in msg
                                              or "cannot assign requested address" in msg):
        # 实例不需要公网 IP（都是主动连主站）；网络不可达多半是自建主站只有 IPv6、而本机 / 容器没有 IPv6 出口
        return ("连不上社区主站：网络不可达。主站只有 IPv6 地址时，Docker 默认没有 IPv6 出口——"
                "按 docker-compose.yml 末尾的说明开启 IPv6，或改用 Linux 一键安装，或把主站放到有公网 IPv4 的服务器上")
    return f"{type(e).__name__}: {str(e)[:120]}"


def _register(c: httpx.Client, base: str, db) -> tuple[str, str]:
    from app import __version__
    r = c.post(base + API + "/register", json={"version": __version__})
    r.raise_for_status()
    d = r.json()
    iid, token = str(d["instance"]), str(d["token"])
    _put_setting(db, "share_client_instance", iid)
    _put_setting(db, "share_client_token", token)
    _put_setting(db, "share_client_hub", base)
    db.commit()
    return iid, token


def client_cycle(engine, db) -> dict:
    """普通实例一轮同步：注册（首次）→ 心跳（每 6 小时带投票）→ 拉社区库 → 拉部署量"""
    from app import __version__
    base = hub_url(db)
    if not base:
        raise ShareError(400, "没有配置社区主站地址（SHARE_HUB_URL）")
    with _http() as c:
        iid, token = _setting(db, "share_client_instance"), _setting(db, "share_client_token")
        if not iid or not token or _setting(db, "share_client_hub") != base:   # 换了主站要重新注册
            iid, token = _register(c, base, db)
            _client["votes_ts"] = 0
        body: dict = {"version": __version__}
        with_votes = time.time() - _client["votes_ts"] >= VOTES_EVERY
        if with_votes:
            body["entries"], body["domains"] = export_entries(engine, db)
        payload = gzip.compress(json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode(), 6)

        def send(i, t):
            return c.post(base + API + "/report", content=payload,
                          headers={"Authorization": f"Bearer {i}:{t}", "Content-Type": "application/json",
                                   "Content-Encoding": "gzip"})
        r = send(iid, token)
        if r.status_code == 401:    # 主站清理过（90 天没心跳）或换过库：重新注册一次
            iid, token = _register(c, base, db)
            r = send(iid, token)
        r.raise_for_status()
        if with_votes:
            _client["votes_ts"] = time.time()

        headers = {"If-None-Match": _client["etag"]} if _client["etag"] else {}
        r = c.get(base + API + "/library", headers=headers)
        if r.status_code == 304:
            st = sync_state()
            n_ip, n_dom = st["community_ips"], st["community_domains"]
        else:
            r.raise_for_status()
            data = r.json()
            n_ip, n_dom = apply_library(data)
            _client["etag"] = r.headers.get("etag", "")
            _save_cache(data, _client["etag"])
        r = c.get(base + API + "/stats")
        r.raise_for_status()
        st = {k: int(r.json().get(k) or 0) for k in ("total", "online", "offline")}
    _set_sync(ts=int(time.time()), ok=True, error="", community_ips=n_ip, community_domains=n_dom, **st)
    return {**st, "community_ips": n_ip, "community_domains": n_dom}


def cycle(engine, db) -> dict | None:
    """定时任务入口（每 30 分钟）：主站走进程内流程；普通实例开关关闭时什么都不发"""
    if is_hub():
        return hub_cycle(engine, db)
    if not sharing_on(db):
        from app.classify.local import local
        local.load_community({}, {})
        _set_sync(ts=0, ok=None, error="", community_ips=0, community_domains=0,
                  total=None, online=None, offline=None)
        return None
    try:
        return client_cycle(engine, db)
    except Exception as e:  # noqa: BLE001  记录原因给设置页显示；社区库继续用上次缓存
        _set_sync(ts=int(time.time()), ok=False, error=_err(e))
        raise


def kick(fn):
    """后台立刻跑一轮（启动后、打开开关后），不等 30 分钟的定时任务；测试环境不跑"""
    if not os.environ.get("ROSDPI_NO_JOBS"):
        threading.Thread(target=fn, daemon=True).start()


def run_once():
    from app import database
    from app.engine import engine
    try:
        with database.session() as db:
            cycle(engine, db)
            db.commit()
    except Exception as e:  # noqa: BLE001
        print(f"[share] 同步失败：{_err(e)}", flush=True)


def status(db) -> dict:
    """设置页的共享状态：角色、主站地址、开关、上次同步结果与全球部署量"""
    st = sync_state()
    if is_hub():   # 主站的部署量直接查库，不用等下一轮
        st.update(stats(db))
        # 不同来源网络数：实例很多却只有 1 个网络，说明反向代理没有传 X-Forwarded-For，社区库永远凑不够票
        st["nets"] = db.scalar(select(func.count(func.distinct(ShareDeployment.net)))
                               .where(ShareDeployment.token_hash.is_not(None),
                                      ShareDeployment.net != HUB_NET)) or 0
    return {"role": "hub" if is_hub() else "client", "hub_url": hub_url(db), "default_hub_url": default_hub_url(),
            "custom_hub": bool(_setting(db, "share_hub_url")), "enabled": sharing_on(db),
            "verify_tls": bool(get_settings().share_verify_tls), "sync": st}
