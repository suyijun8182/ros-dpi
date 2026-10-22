"""统计查询。今日/本周/本月 都从天表汇总（流量落库时同时写分钟/小时/天三张表，不需要 rollup）。"""
import time
from collections import defaultdict

from sqlalchemy import distinct, func, select

from app import hostnames, timeutil
from app.classify import GENERIC_APPS, UNIDENTIFIED_CATEGORIES
from app.engine import engine
from app.models import Host, HostDomainDay, TrafficDay, TrafficHour, TrafficMinute

ONLINE_SECONDS = 300


def _sum_cols(t):
    return func.coalesce(func.sum(t.up), 0), func.coalesce(func.sum(t.down), 0), func.coalesce(func.sum(t.flows), 0)


def _where(q, t, start, end, host=None, app=None):
    q = q.where(t.ts >= start, t.ts < end)
    if host:
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
    out = {}
    for h in rows:
        alias, by = hostnames.resolve(names, h.mac, h.ip)
        alias = alias or h.alias  # 旧版备注名（迁移前）
        out[h.key] = {"key": h.key, "mac": h.mac, "ip": h.ip, "hostname": h.hostname, "alias": alias,
                      "alias_by": by, "name": alias or h.hostname or h.ip or h.key, "first_seen": h.first_seen,
                      "last_seen": h.last_seen, "online": bool(h.last_seen and now - h.last_seen < ONLINE_SECONDS)}
    for k in keys:
        if k in out:
            continue
        ip = k.removeprefix("IP:")
        alias, by = hostnames.resolve(names, None, ip)
        out[k] = {"key": k, "mac": None, "ip": ip, "hostname": None, "alias": alias, "alias_by": by,
                  "name": alias or ip, "first_seen": None, "last_seen": None, "online": False}
        rate = engine.host_rate.get(k, (0, 0))
        out[k]["rate_up"], out[k]["rate_down"] = rate
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


def host_domains(db, host, start, end, limit=100) -> list[dict]:
    t = HostDomainDay
    q = select(t.domain, t.app, func.sum(t.bytes), func.max(t.ts)).where(t.host == host, t.ts >= start, t.ts < end) \
        .group_by(t.domain, t.app).order_by(func.sum(t.bytes).desc()).limit(limit)
    return [{"domain": d, "app": app_meta(a), "bytes": int(b), "last_day": int(ts)} for d, a, b, ts in db.execute(q)]


def unknown_domains(db, start, end, limit=100) -> list[dict]:
    t = HostDomainDay
    q = select(t.domain, func.sum(t.bytes), func.count(distinct(t.host))) \
        .where(t.ts >= start, t.ts < end, t.app.in_(list(GENERIC_APPS))) \
        .group_by(t.domain).order_by(func.sum(t.bytes).desc()).limit(limit)
    return [{"domain": d, "bytes": int(b), "hosts": int(h)} for d, b, h in db.execute(q)]


def online_count(db) -> int:
    return db.scalar(select(func.count()).select_from(Host).where(Host.last_seen > time.time() - ONLINE_SECONDS)) or 0


def flow_graph(db, start, end, max_hosts=12, max_apps=16, host=None) -> dict:
    """流向图（桑基图）数据：终端 → 应用大类 → 应用。超出上限的终端/应用合并为"其他"。"""
    t = TrafficDay
    q = _where(select(t.host, t.app, *_sum_cols(t)), t, start, end, host).group_by(t.host, t.app)
    rows = [(h, a, int(u), int(d)) for h, a, u, d, _f in db.execute(q)]
    host_tot: dict[str, int] = defaultdict(int)
    app_tot: dict[str, int] = defaultdict(int)
    for h, a, u, d in rows:
        host_tot[h] += u + d
        app_tot[a] += u + d
    top_h = set(sorted(host_tot, key=host_tot.get, reverse=True)[:max_hosts])
    top_a = set(sorted(app_tot, key=app_tot.get, reverse=True)[:max_apps])
    meta = host_meta(db, top_h)

    hg: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0])
    ga: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0])
    for h, a, u, d in rows:
        hk = h if h in top_h else "__other_hosts"
        grp = app_meta(a)["group"]
        ak = a if a in top_a else f"__other_apps:{grp}"
        for acc, key in ((hg, (hk, grp)), (ga, (grp, ak))):
            acc[key][0] += u
            acc[key][1] += d

    nodes: dict[str, dict] = {}

    def node(nid, kind, **kw):
        nodes.setdefault(nid, {"id": nid, "kind": kind, **kw})
        return nid

    links = []
    for (hk, grp), (u, d) in hg.items():
        hm = meta.get(hk)
        src = node(f"h:{hk}", "host", key=None if hk == "__other_hosts" else hk,
                   name=hm["name"] if hm else None, online=hm["online"] if hm else False)
        gi = engine.classifier.group_info(grp)
        dst = node(f"g:{grp}", "group", group=grp, name=gi["name"], name_en=gi["name_en"])
        links.append({"source": src, "target": dst, "up": u, "down": d, "value": u + d})
    for (grp, ak), (u, d) in ga.items():
        if ak.startswith("__other_apps:"):
            dst = node(f"a:{ak}", "app", app=None, group=grp, category=None)
        else:
            am = app_meta(ak)
            dst = node(f"a:{ak}", "app", app=ak, group=grp, category=am["category"], name=am["name"],
                       name_en=am["name_en"])
        links.append({"source": f"g:{grp}", "target": dst, "up": u, "down": d, "value": u + d})
    links = [x for x in links if x["value"] > 0]
    return {"nodes": list(nodes.values()), "links": links, "total": sum(host_tot.values())}
