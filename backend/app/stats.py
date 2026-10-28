"""统计查询。今日/本周/本月 都从天表汇总（流量落库时同时写分钟/小时/天三张表，不需要 rollup）。"""
import ipaddress
import time
from collections import defaultdict

from sqlalchemy import distinct, func, or_, select

from app import hostnames, timeutil
from app.classify import GENERIC_APPS, UNIDENTIFIED_CATEGORIES
from app.engine import ONLINE_SECONDS, engine
from app.models import Host, HostDomainDay, TrafficDay, TrafficHour, TrafficMinute, UnmatchedDay



def _sum_cols(t):
    return func.coalesce(func.sum(t.up), 0), func.coalesce(func.sum(t.down), 0), func.coalesce(func.sum(t.flows), 0)


def _where(q, t, start, end, host=None, app=None):
    q = q.where(t.ts >= start, t.ts < end)
    if isinstance(host, (list, tuple, set)):  # 一组终端（按人员 / 部门汇总）
        q = q.where(t.host.in_(list(host) or ["-"]))
    elif host:
        q = q.where(t.host == host)
    if app:
        q = q.where(t.app == app)
    return q


def total(db, start, end, host=None, app=None) -> dict:
    up, down, flows = db.execute(_where(select(*_sum_cols(TrafficDay)), TrafficDay, start, end, host, app)).one()
    return {"up": int(up), "down": int(down), "total": int(up) + int(down), "flows": int(flows)}


def totals3(db, host=None, app=None) -> dict:
    return {r: total(db, *timeutil.range_bounds(r), host=host, app=app) for r in ("today", "week", "month")}


def app_meta(app_id: str) -> dict:
    cl = engine.classifier
    a = cl.app_info(app_id)
    c = cl.category_info(a.category)
    g = cl.group_info(c["group"])
    return {"id": a.id, "name": a.name, "name_en": a.name_en, "category": a.category,
            "category_name": c["name"], "category_name_en": c["name_en"],
            "group": c["group"], "group_name": g["name"], "group_name_en": g["name_en"]}


def top_apps(db, start, end, host=None, limit=None) -> list[dict]:
    t = TrafficDay
    q = _where(select(t.app, *_sum_cols(t), func.count(distinct(t.host))), t, start, end, host)
    q = q.group_by(t.app).order_by((func.sum(t.up) + func.sum(t.down)).desc())
    if limit:
        q = q.limit(limit)
    out = []
    for app, up, down, flows, hosts in db.execute(q):
        rate = engine.app_rate.get(app, (0, 0)) if not host else (0, 0)
        out.append({**app_meta(app), "up": int(up), "down": int(down), "total": int(up) + int(down),
                    "flows": int(flows), "hosts": int(hosts), "rate_up": rate[0], "rate_down": rate[1]})
    return out


def top_categories(apps: list[dict]) -> list[dict]:
    agg: dict[str, dict] = {}
    for a in apps:
        c = agg.setdefault(a["category"], {"id": a["category"], "name": a["category_name"],
                                           "name_en": a["category_name_en"], "group": a["group"],
                                           "up": 0, "down": 0, "total": 0, "apps": 0})
        c["up"] += a["up"]
        c["down"] += a["down"]
        c["total"] += a["total"]
        c["apps"] += 1
    return sorted(agg.values(), key=lambda c: c["total"], reverse=True)


def top_groups(cats: list[dict]) -> list[dict]:
    """应用大类汇总，children 是该大类下的小类（已按流量排序）。"""
    agg: dict[str, dict] = {}
    for c in cats:
        gi = engine.classifier.group_info(c["group"])
        g = agg.setdefault(c["group"], {"id": c["group"], "name": gi["name"], "name_en": gi["name_en"],
                                        "up": 0, "down": 0, "total": 0, "apps": 0, "children": []})
        for k in ("up", "down", "total", "apps"):
            g[k] += c[k]
        g["children"].append(c)
    return sorted(agg.values(), key=lambda g: g["total"], reverse=True)


def identified_ratio(apps: list[dict]) -> float:
    known = sum(a["total"] for a in apps if a["category"] not in UNIDENTIFIED_CATEGORIES)
    return known / (sum(a["total"] for a in apps) or 1)


def host_meta(db, keys) -> dict[str, dict]:
    keys = list(keys)
    if not keys:
        return {}
    now = time.time()
    rows = db.scalars(select(Host).where(Host.key.in_(keys))).all()
    names = hostnames.load(db)
    from app import people
    people.load(db)
    out = {}
    for h in rows:
        alias, by = hostnames.resolve(names, h.mac, h.ip)
        alias = alias or h.alias  # 旧版备注名（迁移前）
        out[h.key] = {"key": h.key, "mac": h.mac, "ip": h.ip, "hostname": h.hostname, "alias": alias,
                      "alias_by": by, "name": alias or h.hostname or h.ip or h.key, "first_seen": h.first_seen,
                      "last_seen": h.last_seen, "online": bool(h.last_seen and now - h.last_seen < ONLINE_SECONDS)}
        out[h.key]["online_since"] = h.online_since if out[h.key]["online"] else None
        out[h.key].update(dtype=h.dtype or h.dtype_auto or "unknown", dtype_manual=h.dtype, dtype_auto=h.dtype_auto, vendor=h.vendor)
    for k in keys:
        if k not in out:
            ip = k.removeprefix("IP:")
            alias, by = hostnames.resolve(names, None, ip)
            out[k] = {"key": k, "mac": None, "ip": ip, "hostname": None, "alias": alias, "alias_by": by,
                      "name": alias or ip, "first_seen": None, "last_seen": None, "online": False, "online_since": None,
                      "dtype": "unknown", "dtype_manual": None, "dtype_auto": None, "vendor": None}
        rate = engine.host_rate.get(k, (0, 0))
        out[k]["rate_up"], out[k]["rate_down"] = rate
        out[k]["conns"] = engine.host_conns.get(k, 0)
        out[k]["person"] = people.person_of(k)
    return out


def top_hosts(db, start, end, app=None, limit=None) -> list[dict]:
    t = TrafficDay
    q = _where(select(t.host, *_sum_cols(t)), t, start, end, app=app)
    q = q.group_by(t.host).order_by((func.sum(t.up) + func.sum(t.down)).desc())
    if limit:
        q = q.limit(limit)
    rows = db.execute(q).all()
    meta = host_meta(db, [r[0] for r in rows])
    return [{**meta[h], "up": int(u), "down": int(d), "total": int(u) + int(d), "flows": int(f)}
            for h, u, d, f in rows]


_GRAN = {"minute": (TrafficMinute, 60), "hour": (TrafficHour, 3600), "day": (TrafficDay, 86400)}


def _buckets(gran: str, start, end) -> list[int]:
    out = []
    if gran == "day":
        cur = timeutil.day_bucket(start)
        while cur < end:
            out.append(cur)
            cur = timeutil.day_bucket(cur + 86400 + 3600)  # +1h 兼容夏令时
    else:
        step = _GRAN[gran][1]
        cur = start // step * step
        while cur < end:
            out.append(cur)
            cur += step
    return out


def trend(db, gran: str, start, end, host=None, app=None) -> list[dict]:
    """gran: minute | hour | day。返回补齐空桶后的序列。"""
    t = _GRAN[gran][0]
    q = _where(select(t.ts, *_sum_cols(t)), t, start, end, host, app).group_by(t.ts).order_by(t.ts)
    data = {int(ts): (int(u), int(d)) for ts, u, d, _f in db.execute(q)}
    return [{"ts": ts, "up": data.get(ts, (0, 0))[0], "down": data.get(ts, (0, 0))[1]}
            for ts in _buckets(gran, start, end)]


def trend_groups(db, gran: str, start, end, host=None, app=None, max_series=7) -> dict:
    """按应用大类拆分的趋势（堆叠面积图）。流量最大的 max_series 个大类单独成线，其余合并为 other。"""
    t, step = _GRAN[gran]
    q = _where(select(t.ts, t.app, func.sum(t.up) + func.sum(t.down)), t, start, end, host, app)         .group_by(t.ts, t.app)
    per: dict[str, dict[int, int]] = defaultdict(lambda: defaultdict(int))
    tot: dict[str, int] = defaultdict(int)
    for ts, a, b in db.execute(q):
        g = app_meta(a)["group"]
        per[g][int(ts)] += int(b)
        tot[g] += int(b)
    buckets = _buckets(gran, start, end)
    order = sorted(tot, key=tot.get, reverse=True)
    keep, rest = order[:max_series], order[max_series:]
    series = []
    for g in keep:
        gi = engine.classifier.group_info(g)
        series.append({"id": g, "name": gi["name"], "name_en": gi["name_en"], "total": tot[g],
                       "values": [per[g].get(ts, 0) for ts in buckets]})
    if rest:
        series.append({"id": "__other", "name": None, "name_en": None, "total": sum(tot[g] for g in rest),
                       "values": [sum(per[g].get(ts, 0) for g in rest) for ts in buckets]})
    return {"gran": gran, "step": step, "ts": buckets, "series": series}


def online_trend(db, gran: str, start, end) -> list[dict]:
    """每个时间桶里有流量的终端数（历史在线数）。"""
    t = _GRAN[gran][0]
    q = select(t.ts, func.count(distinct(t.host))).where(t.ts >= start, t.ts < end).group_by(t.ts)
    data = {int(ts): int(n) for ts, n in db.execute(q)}
    return [{"ts": ts, "n": data.get(ts, 0)} for ts in _buckets(gran, start, end)]


def new_hosts(db, since) -> int:
    return db.scalar(select(func.count()).select_from(Host).where(Host.first_seen >= since)) or 0


def all_hosts(db) -> list[dict]:
    """主机监控列表：每台终端的 今日/本周/本月 流量。"""
    per: dict[str, dict] = defaultdict(dict)
    for r in ("today", "week", "month"):
        start, end = timeutil.range_bounds(r)
        q = select(TrafficDay.host, *_sum_cols(TrafficDay)).where(TrafficDay.ts >= start, TrafficDay.ts < end) \
            .group_by(TrafficDay.host)
        for h, u, d, _f in db.execute(q):
            per[h][r] = {"up": int(u), "down": int(d), "total": int(u) + int(d)}
    keys = set(per) | set(db.scalars(select(Host.key)).all())
    meta = host_meta(db, keys)
    zero = {"up": 0, "down": 0, "total": 0}
    rows = [{**meta[k], **{r: per[k].get(r, zero) for r in ("today", "week", "month")}} for k in keys]
    rows.sort(key=lambda x: (x["today"]["total"], x["month"]["total"]), reverse=True)
    return rows


def top_app_per_host(db, start, end) -> dict[str, dict]:
    t = TrafficDay
    q = _where(select(t.host, t.app, (func.sum(t.up) + func.sum(t.down)).label("b")), t, start, end) \
        .group_by(t.host, t.app)
    best: dict[str, tuple[str, int]] = {}
    for h, a, b in db.execute(q):
        if a in GENERIC_APPS:
            continue
        if h not in best or b > best[h][1]:
            best[h] = (a, int(b))
    return {h: app_meta(a) for h, (a, _b) in best.items()}


def app_bytes_per_host(db, start, end, hosts) -> list[tuple]:
    """[(终端, 应用 ID, 应用名, 字节)]，只含具体应用（不含笼统分类）；hosts 为空时返回空"""
    if not hosts:
        return []
    t = TrafficDay
    q = select(t.host, t.app, func.sum(t.up) + func.sum(t.down)).where(t.ts >= start, t.ts < end, t.host.in_(list(hosts)))         .group_by(t.host, t.app)
    return [(h, a, app_meta(a)["name"], int(b)) for h, a, b in db.execute(q) if a not in GENERIC_APPS]


def host_domains(db, host, start, end, limit=100) -> list[dict]:
    t = HostDomainDay
    q = select(t.domain, t.app, func.sum(t.bytes), func.max(t.ts)).where(t.host == host, t.ts >= start, t.ts < end) \
        .group_by(t.domain, t.app).order_by(func.sum(t.bytes).desc()).limit(limit)
    return [{"domain": d, "app": app_meta(a), "bytes": int(b), "last_day": int(ts)} for d, a, b, ts in db.execute(q)]


def unknown_domains(db, start, end, limit=100) -> list[dict]:
    t = HostDomainDay
    q = select(t.domain, func.sum(t.bytes), func.count(distinct(t.host))) \
        .where(t.ts >= start, t.ts < end, t.app.in_(list(GENERIC_APPS))) \
        .group_by(t.domain).order_by(func.sum(t.bytes).desc()).limit(limit * 3)
    # 只有 IP 的访问目标没法按域名建规则，不列在这里
    return [{"domain": d, "bytes": int(b), "hosts": int(h)} for d, b, h in db.execute(q) if not is_ip(d)][:limit]


NAT_SHARE = 0.6   # 一台终端占全网流量六成以上：多半是下挂的路由器（双重 NAT），后面的设备 ROS 看不到


def nat_suspect(db, start, end) -> dict | None:
    """疑似下挂路由器的终端（debug25：爱快接在 ROS 下面，全家流量合成了一台）"""
    tot = total(db, start, end)["total"]
    if tot <= 0:
        return None
    top = top_hosts(db, start, end, limit=1)
    if not top or top[0]["total"] / tot < NAT_SHARE:
        return None
    h = top[0]
    return {"key": h["key"], "name": h["name"], "ip": h["ip"], "share": h["total"] / tot}


def unmatched(db, start, end) -> dict:
    """没有任何域名信号的流量拆解（未匹配诊断）：按 协议/端口、远端 ASN 类型、终端、最终归类"""
    t = UnmatchedDay
    vol = func.sum(t.up) + func.sum(t.down)
    rng = (t.ts >= start, t.ts < end)

    def by(*cols, limit=None):
        q = select(*cols, func.sum(t.up), func.sum(t.down), func.sum(t.flows)).where(*rng)             .group_by(*cols).order_by(vol.desc())
        if limit:
            q = q.limit(limit)
        return [(*r[:-3], int(r[-3]), int(r[-2]), int(r[-1])) for r in db.execute(q).all()]

    def row(up, down, flows, **kw):
        return {**kw, "up": up, "down": down, "total": up + down, "flows": flows}

    ports = [row(u, d, f, proto=p, port=pt) for p, pt, u, d, f in by(t.proto, t.port, limit=20)]
    kinds = [row(u, d, f, kind=k) for k, u, d, f in by(t.kind)]
    apps = [row(u, d, f, app=app_meta(a)) for a, u, d, f in by(t.app, limit=15)]
    hrows = by(t.host, limit=10)
    meta = host_meta(db, [r[0] for r in hrows])
    hosts = [row(u, d, f, host=meta[h]) for h, u, d, f in hrows]
    return {"total": sum(k["total"] for k in kinds), "range_total": total(db, start, end)["total"],
            "ports": ports, "kinds": kinds, "apps": apps, "hosts": hosts, "nat": nat_suspect(db, start, end)}


def online_count(db) -> int:
    return db.scalar(select(func.count()).select_from(Host).where(Host.last_seen > time.time() - ONLINE_SECONDS)) or 0


_CC_SLD = {"com", "net", "org", "gov", "edu", "co", "ac"}


def is_ip(x: str) -> bool:
    try:
        ipaddress.ip_address(x)
        return True
    except ValueError:
        return False


def base_domain(name: str) -> str:
    """主域名：www.bilibili.com → bilibili.com，a.b.example.com.cn → example.com.cn；IP 原样返回"""
    if is_ip(name):
        return name
    p = name.split(".")
    n = 3 if len(p) >= 3 and p[-2] in _CC_SLD and len(p[-1]) == 2 else 2
    return ".".join(p[-n:])


def destinations(db, start, end, q: str = "", merge: bool = False, kind: str = "all", limit: int = 300) -> list[dict]:
    """访问目标排行：按流量排序的远端域名 / IP，附带主要应用和访问的终端数。merge=True 时按主域名合并。
    聚合在 SQL 侧完成，只把排到前面的目标拿回内存；目标是域名还是 IP 在内存里判断，多取 5 倍候选保证够筛。"""
    t = HostDomainDay
    col = func.coalesce(t.base, t.domain) if merge else t.domain
    total = func.sum(t.bytes)
    sel = select(col.label("dest"), total.label("b"), func.count(distinct(t.host)).label("h")) \
        .where(t.ts >= start, t.ts < end)
    s = q.strip().lower()
    if s:
        like = f"%{s}%"
        sel = sel.where(or_(t.domain.like(like), t.base.like(like)))
    sel = sel.group_by(col).order_by(total.desc()).limit(limit * 5)
    rows = [r for r in db.execute(sel).all()
            if kind == "all" or (is_ip(r.dest) if kind == "ip" else not is_ip(r.dest))][:limit]
    if not rows:
        return []
    dests = [r.dest for r in rows]
    where = (col.in_(dests), t.ts >= start, t.ts < end)
    apps: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    names: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for dest, app, b in db.execute(select(col, t.app, total).where(*where).group_by(col, t.app)):
        apps[dest][app] = int(b)
    for dest, dom, b in db.execute(select(col, t.domain, total).where(*where).group_by(col, t.domain)):
        names[dest][dom] = int(b)
    out = []
    for r in rows:
        a = apps[r.dest]
        top_app = max(a, key=a.get) if a else ""
        subs = sorted(names[r.dest].items(), key=lambda x: x[1], reverse=True)
        out.append({"dest": r.dest, "ip": is_ip(r.dest), "bytes": int(r.b), "hosts": int(r.h),
                    "names": len(subs), "app": app_meta(top_app) if top_app else None,
                    "name_list": [d for d, _b in subs[:20]]})
    return out


def destination_hosts(db, dest: str, start, end, merge: bool = False) -> list[dict]:
    """某个访问目标被哪些终端访问、各用了多少"""
    t = HostDomainDay
    q = select(t.host, t.domain, func.sum(t.bytes)).where(t.ts >= start, t.ts < end)
    q = q.where((t.domain == dest) | t.domain.like(f"%.{dest}")) if merge else q.where(t.domain == dest)
    per: dict[str, list] = defaultdict(lambda: [0, set()])
    for host, dom, b in db.execute(q.group_by(t.host, t.domain)):
        per[host][0] += int(b)
        per[host][1].add(dom)
    meta = host_meta(db, per)
    return sorted(({**meta[h], "bytes": v[0], "names": sorted(v[1])[:5]} for h, v in per.items()),
                  key=lambda x: x["bytes"], reverse=True)
