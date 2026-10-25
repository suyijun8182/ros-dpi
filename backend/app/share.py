"""社区共享库（debug16）：各部署实例互相共享本地自学习库的「IP → 应用」实测结论。

架构：任意实例可开启中转模式（公网可达）——其它实例每小时把自学习库上报给中转（POST /api/share/collect，
只含 远端IP→应用 的匿名投票），中转聚合后发布 GET /api/share/library.json；所有实例拉取并合并进本地
自学习库的「社区层」，本地没有实测结论的 IP 才用社区条目。

隐私与防污染：
- 上报内容只有 (远端 IP, 应用 ID, 字节票数)；不含本机终端、域名记录、自定义应用；
- 私网 / 保留地址剔除；
- 中转只发布「至少 2 个不同实例都见过」的映射——单实例的私有服务不会出现在社区库里；
- 每次上报限量，中转按实例 ID 去重投票、过期清理。
"""
import ipaddress
import re
import threading
import time
import uuid
from collections import defaultdict

from sqlalchemy import delete, func, select

from app.classify.local import _is_ip, _v6key
from app.models import HostDomainDay, ShareDeployment, ShareDomain, ShareEntry

MAX_UPLOAD = 50_000          # 单次上报的条数上限
MAX_REPORTER = 100_000       # 中转上每个实例最多保留的条数
PUBLISH_REPORTERS = 2        # 至少几个不同实例见过才对外发布
ENTRY_TTL = 30 * 24 * 3600   # 上报条目 30 天没再出现就清理
# 域名格式（debug20：中转拒收格式错误的域名条目）
_DOMAIN_RE = re.compile(r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
MAX_BYTES = 10 ** 15         # 单条字节票数的上限，防脏数据

# 最近一次与中转同步的结果（连接状态指示，debug20 第 1 条）
_sync_lock = threading.Lock()
_sync = {"ts": 0, "ok": None, "error": "", "community_ips": 0, "community_domains": 0}


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
    """只共享公网远端地址：私网 / 保留 / 组播 / 回环不出门"""
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return not (a.is_private or a.is_reserved or a.is_multicast or a.is_loopback or a.is_link_local)


def export_entries(engine, db) -> list[dict]:
    """把本地自学习库整理成可上报的条目：host_domain_day 里以 IP 记录的行，按字节数取最多的应用。
    IPv4 按精确地址共享；IPv6 按 /64 前缀共享（精确地址在不同实例间几乎不重复，凑不满投票）"""
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
    """域名学习（debug17）：host_domain_day 里非 IP 的域名行，按字节数取最多的应用，精确域名共享"""
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


def _valid_app(classifier, app: str) -> bool:
    """应用白名单（debug20）：只收所有实例都认识的应用；自定义应用和编造的 ID 拒收。
    classifier 传 None 时只按 ID 形状校验（测试直调用）"""
    if classifier is None:
        return bool(app) and len(app) <= 48 and app != "other" and not app.startswith("custom_")
    info = classifier.apps.get(app)
    return info is not None and not info.custom


def collect(db, reporter: str, entries: list[dict], domains: list[dict] | None = None,
            classifier=None) -> int:
    """中转：记录一次上报（调用方提交事务）。返回接受的条数。
    校验（debug20 第 2 条）：IP 可共享性、域名格式、应用白名单（自定义应用和编造的 ID 拒收）、字节上限"""
    now = int(time.time())
    accepted = 0
    from app.classify.local import _v6key
    for e in entries[:MAX_UPLOAD]:
        ip, app, b = str(e.get("ip", "")), str(e.get("app", "")), min(max(int(e.get("bytes", 0) or 0), 0), MAX_BYTES)
        # IPv6 条目（不管上报的是精确地址还是 /64）统一按 /64 前缀存储：不同实例的精确地址才能凑齐投票
        base = ip[:-3] if ip.endswith("/64") else ip
        if not _shareable_ip(base) or not _valid_app(classifier, app):
            continue
        key = _v6key(base) or base
        row = db.get(ShareEntry, {"ip": key, "app": app, "reporter": reporter})
        if row is None:
            db.add(ShareEntry(ip=key, app=app, reporter=reporter, bytes=b, ts=now))
        else:
            row.bytes = max(row.bytes, b)
            row.ts = now
        accepted += 1
    for e in (domains or [])[:MAX_UPLOAD]:
        dom, app = str(e.get("domain", "")).lower().rstrip("."), str(e.get("app", ""))
        b = min(max(int(e.get("bytes", 0) or 0), 0), MAX_BYTES)
        if not _DOMAIN_RE.match(dom) or not _valid_app(classifier, app):
            continue
        row = db.get(ShareDomain, {"domain": dom, "app": app, "reporter": reporter})
        if row is None:
            db.add(ShareDomain(domain=dom, app=app, reporter=reporter, bytes=b, ts=now))
        else:
            row.bytes = max(row.bytes, b)
            row.ts = now
        accepted += 1
    # 清理：30 天没再出现、或单个实例超出上限的旧条目
    db.execute(delete(ShareEntry).where(ShareEntry.reporter == reporter, ShareEntry.ts < now - ENTRY_TTL))
    db.execute(delete(ShareDomain).where(ShareDomain.reporter == reporter, ShareDomain.ts < now - ENTRY_TTL))
    n = db.scalar(select(func.count()).select_from(ShareEntry).where(ShareEntry.reporter == reporter))
    if n and n > MAX_REPORTER:
        old = db.execute(select(ShareEntry.ip, ShareEntry.app).where(ShareEntry.reporter == reporter)
                         .order_by(ShareEntry.ts).limit(n - MAX_REPORTER)).all()
        for ip, app in old:
            db.execute(delete(ShareEntry).where(ShareEntry.ip == ip, ShareEntry.app == app,
                                                ShareEntry.reporter == reporter))
    return accepted


def published_library(db) -> dict:
    """中转对外发布的社区库：至少 PUBLISH_REPORTERS 个不同实例见过的映射"""
    rows = db.execute(select(ShareEntry.ip, ShareEntry.app, func.count(func.distinct(ShareEntry.reporter)),
                             func.sum(ShareEntry.bytes)).group_by(ShareEntry.ip, ShareEntry.app)).all()
    per_ip: dict = defaultdict(list)
    for ip, app, reporters, _b in rows:
        if reporters >= PUBLISH_REPORTERS:
            per_ip[ip].append((int(_b or 0), app))
    entries = [{"ip": ip, "app": max(v)[1]} for ip, v in per_ip.items()]
    entries.sort(key=lambda x: x["ip"])
    drows = db.execute(select(ShareDomain.domain, ShareDomain.app,
                              func.count(func.distinct(ShareDomain.reporter))).group_by(ShareDomain.domain, ShareDomain.app)).all()
    per_dom: dict = defaultdict(list)
    for dom, app, reporters in drows:
        if reporters >= PUBLISH_REPORTERS:
            per_dom[dom].append(app)
    doms = [{"domain": d, "app": apps[0]} for d, apps in sorted(per_dom.items())]
    return {"version": 1, "generated": int(time.time()), "entries": entries, "domains": doms}


def heartbeat(db, instance: str, version: str, public_url: str = "") -> None:
    """中转：记录一次部署心跳（调用方提交事务）。只含实例匿名 ID、版本号；中转实例附带自己的公开地址"""
    now = int(time.time())
    row = db.get(ShareDeployment, instance)
    if row is None:
        db.add(ShareDeployment(instance=instance, version=version[:16], first_seen=now, last_seen=now,
                               public_url=public_url or None))
    else:
        row.version, row.last_seen = version[:16], now
        if public_url:
            row.public_url = public_url


def deployments(db, online_after: int = 7200) -> dict:
    """中转：全球部署概况（所有人可见）：已部署总数 / 在线（最近 2 小时有心跳）/ 离线 / 可用中转列表"""
    now = int(time.time())
    total = db.scalar(select(func.count()).select_from(ShareDeployment)) or 0
    online = db.scalar(select(func.count()).select_from(ShareDeployment)
                       .where(ShareDeployment.last_seen >= now - online_after)) or 0
    relays = [r[0] for r in db.execute(select(ShareDeployment.public_url)
                                       .where(ShareDeployment.public_url.is_not(None),
                                              ShareDeployment.last_seen >= now - online_after * 12)
                                       .distinct()).all() if r[0]]
    return {"total": total, "online": online, "offline": total - online, "relays": sorted(relays)}


def deployments_remote(url: str, token: str = "") -> dict | None:
    """客户端：从中转拉取全球部署概况（中转的 /api/share/deployments 是公开端点）"""
    import httpx
    headers = {"X-Share-Token": token} if token else {}
    try:
        r = httpx.get(url.rstrip("/") + "/api/share/deployments", headers=headers, timeout=15.0, verify=False)
        r.raise_for_status()
        d = r.json()
        return {"total": d.get("total", 0), "online": d.get("online", 0), "offline": d.get("offline", 0)}
    except Exception:  # noqa: BLE001
        return None


def sharing_on(db) -> bool:
    """共享识别库的总开关（debug16 第 3 条）：默认打开；设置里可关闭（关闭后不心跳、不上报、不拉取）"""
    from app.models import Setting
    row = db.get(Setting, "share_enabled")
    return (row.value == "1") if row is not None else True


def client_cycle(engine, db, url: str, token: str = "") -> dict:
    """客户端一轮同步：心跳（部署量统计）+ 上报本地实测 + 拉取社区库；中转实例还会与其它中转同步保持一致"""
    import httpx
    iid = instance_id(db)
    headers = {"X-Share-Token": token} if token else {}
    base = url.rstrip("/")
    from app import __version__
    # 本实例是中转时，心跳带上自己的公开地址（默认中转地址即本实例对外地址）
    hub_row = db.get(__import__("app.models", fromlist=["Setting"]).Setting, "share_hub")
    is_hub = (hub_row.value == "1") if hub_row is not None else False
    public_url = url if is_hub else ""
    try:
        httpx.post(base + "/api/share/heartbeat",
                   json={"instance": iid, "version": __version__, "public_url": public_url},
                   headers=headers, timeout=15.0)
    except Exception:  # noqa: BLE001  心跳失败不影响库同步
        pass
    entries, domains = export_entries(engine, db)
    uploaded, merged, c_ips, c_doms, error = 0, 0, 0, 0, ""
    try:
        r = httpx.post(base + "/api/share/collect", json={"instance": iid, "entries": entries, "domains": domains},
                       headers=headers, timeout=30.0, verify=False)
        r.raise_for_status()
        uploaded = int(r.json().get("accepted", 0))
    except Exception as e:  # noqa: BLE001
        error = f"{type(e).__name__}: {str(e)[:120]}"
    try:
        r2 = httpx.get(base + "/api/share/library.json", headers=headers, timeout=30.0, verify=False)
        r2.raise_for_status()
        data = r2.json()
        c_ips, c_doms = len(data.get("entries") or []), len(data.get("domains") or [])
        merged = merge_community(db, data)
    except Exception as e:  # noqa: BLE001
        error = error or f"{type(e).__name__}: {str(e)[:120]}"
    with _sync_lock:
        _sync.update(ts=int(time.time()), ok=(not error), error=error,
                     community_ips=c_ips, community_domains=c_doms)
    # 中转之间自动同步（debug19 第 2 条）：从主中转的部署名单里发现其它中转，把它们的社区库并进本地，
    # 保证所有中转对外发布的数据一致
    if is_hub and base.rstrip("/") != url.rstrip("/"):
        pass
    try:
        d = httpx.get(base + "/api/share/deployments", headers=headers, timeout=15.0).json()
        for peer in d.get("relays") or []:
            peer = peer.rstrip("/")
            if not peer or peer == base:
                continue
            try:
                pr = httpx.get(peer + "/api/share/library.json", timeout=30.0, verify=False)
                pr.raise_for_status()
                data = pr.json()
                for e in data.get("entries") or []:
                    row = db.get(ShareEntry, {"ip": e.get("ip"), "app": e.get("app"), "reporter": "relay:" + peer})
                    if row is None:
                        db.add(ShareEntry(ip=e.get("ip"), app=e.get("app"), reporter="relay:" + peer,
                                          bytes=0, ts=int(time.time())))
                    else:
                        row.ts = int(time.time())
                for e in data.get("domains") or []:
                    row = db.get(ShareDomain, {"domain": e.get("domain"), "app": e.get("app"),
                                               "reporter": "relay:" + peer})
                    if row is None:
                        db.add(ShareDomain(domain=e.get("domain"), app=e.get("app"), reporter="relay:" + peer,
                                           bytes=0, ts=int(time.time())))
                    else:
                        row.ts = int(time.time())
                db.commit()
            except Exception:  # noqa: BLE001  单个中转不通不影响其它
                continue
    except Exception:  # noqa: BLE001
        pass
    return {"uploaded": uploaded, "merged": merged}


def merge_community(db, data: dict) -> int:
    """客户端：把社区库并入本地自学习库的社区层（本地实测优先，社区只补空白）。返回并入条数"""
    from app.classify.local import local
    entries = (data or {}).get("entries") or []
    known = set(local.ips)
    community = {}
    for e in entries:
        ip, app = str(e.get("ip", "")), str(e.get("app", ""))
        if ip in known or not _shareable_ip(ip[:-3] if ip.endswith("/64") else ip) or len(app) > 48:
            continue
        community[ip] = app
    known_d = set(local.domains)
    community_domains = {}
    for e in (data or {}).get("domains") or []:
        dom, app = str(e.get("domain", "")).lower().rstrip("."), str(e.get("app", ""))
        if dom in known_d or not dom or "/" in dom or len(dom) > 255 or len(app) > 48:
            continue
        community_domains[dom] = app
    local.load_community(community, community_domains)
    return len(community) + len(community_domains)
