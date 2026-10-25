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
import time
import uuid
from collections import defaultdict

from sqlalchemy import delete, func, select

from app.models import HostDomainDay, ShareDeployment, ShareEntry

MAX_UPLOAD = 50_000          # 单次上报的条数上限
MAX_REPORTER = 100_000       # 中转上每个实例最多保留的条数
PUBLISH_REPORTERS = 2        # 至少几个不同实例见过才对外发布
ENTRY_TTL = 30 * 24 * 3600   # 上报条目 30 天没再出现就清理


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
    from app.classify.local import _v6key
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
    return out[:MAX_UPLOAD]


def collect(db, reporter: str, entries: list[dict]) -> int:
    """中转：记录一次上报（调用方提交事务）。返回接受的条数"""
    now = int(time.time())
    accepted = 0
    from app.classify.local import _v6key
    for e in entries[:MAX_UPLOAD]:
        ip, app, b = str(e.get("ip", "")), str(e.get("app", "")), max(int(e.get("bytes", 0) or 0), 0)
        # IPv6 条目（不管上报的是精确地址还是 /64）统一按 /64 前缀存储：不同实例的精确地址才能凑齐投票
        base = ip[:-3] if ip.endswith("/64") else ip
        if not _shareable_ip(base) or len(app) > 48 or app == "other":
            continue
        key = _v6key(base) or base
        row = db.get(ShareEntry, {"ip": key, "app": app, "reporter": reporter})
        if row is None:
            db.add(ShareEntry(ip=key, app=app, reporter=reporter, bytes=b, ts=now))
        else:
            row.bytes = max(row.bytes, b)
            row.ts = now
        accepted += 1
    # 清理：30 天没再出现、或单个实例超出上限的旧条目
    db.execute(delete(ShareEntry).where(ShareEntry.reporter == reporter, ShareEntry.ts < now - ENTRY_TTL))
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
    return {"version": 1, "generated": int(time.time()), "entries": entries}


def heartbeat(db, instance: str, version: str) -> None:
    """中转：记录一次部署心跳（调用方提交事务）。只含实例匿名 ID 和版本号"""
    now = int(time.time())
    row = db.get(ShareDeployment, instance)
    if row is None:
        db.add(ShareDeployment(instance=instance, version=version[:16], first_seen=now, last_seen=now))
    else:
        row.version, row.last_seen = version[:16], now


def deployments(db, online_after: int = 7200) -> dict:
    """中转：全球部署概况（所有人可见）：已部署总数 / 在线（最近 2 小时有心跳）/ 离线"""
    now = int(time.time())
    total = db.scalar(select(func.count()).select_from(ShareDeployment)) or 0
    online = db.scalar(select(func.count()).select_from(ShareDeployment)
                       .where(ShareDeployment.last_seen >= now - online_after)) or 0
    return {"total": total, "online": online, "offline": total - online}


def sharing_on(db) -> bool:
    """共享识别库的总开关（debug16 第 3 条）：默认打开；设置里可关闭（关闭后不心跳、不上报、不拉取）"""
    from app.models import Setting
    row = db.get(Setting, "share_enabled")
    return (row.value == "1") if row is not None else True


def client_cycle(engine, db, url: str, token: str = "") -> dict:
    """客户端一轮同步：心跳（部署量统计）+ 上报本地实测 + 拉取社区库"""
    import httpx
    iid = instance_id(db)
    headers = {"X-Share-Token": token} if token else {}
    base = url.rstrip("/")
    from app import __version__
    try:
        httpx.post(base + "/api/share/heartbeat", json={"instance": iid, "version": __version__},
                   headers=headers, timeout=15.0)
    except Exception:  # noqa: BLE001  心跳失败不影响库同步
        pass
    entries = export_entries(engine, db)
    uploaded = 0
    try:
        r = httpx.post(base + "/api/share/collect", json={"instance": iid, "entries": entries},
                       headers=headers, timeout=30.0)
        r.raise_for_status()
        uploaded = int(r.json().get("accepted", 0))
    except Exception:  # noqa: BLE001
        pass
    merged = 0
    try:
        r2 = httpx.get(base + "/api/share/library.json", headers=headers, timeout=30.0)
        r2.raise_for_status()
        merged = merge_community(db, r2.json())
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
    local.load_community(community)
    return len(community)
