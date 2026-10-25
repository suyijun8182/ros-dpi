"""审计：规则判定、审计事件、通知推送、日报 / 周报。

规则在每分钟落库时检查（engine.flush → evaluate），看这一分钟里每台终端的流量：
- group / category / app：终端用了某个应用大类 / 小类 / 应用；
- domain：终端访问了某个域名（后缀匹配）；
- traffic：终端的流量（不分应用）；
- new_host：出现了新终端。
min_bytes > 0 时，在生效时段内按天累计，超过阈值才命中；同一条规则对同一台终端，一天最多记一次（min_bytes = 0 时一小时一次）。
"""
import json
import threading
import time
from collections import defaultdict
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import select, update

from app import database, notify, people, sharing
from app.config import get_settings
from app.models import AuditEvent, AuditRule, Setting



def _tz():
    return ZoneInfo(get_settings().tz)


def in_window(rule, ts: float) -> bool:
    """规则是否在生效的星期和时段内（时段可以跨午夜，例如 22:00-06:00）"""
    d = datetime.fromtimestamp(ts, _tz())
    hm = d.strftime("%H:%M")
    a, b = rule.time_from or "00:00", rule.time_to or "24:00"
    day = d.isoweekday()
    if a <= b:
        ok_time, ok_day = a <= hm < b, str(day) in (rule.days or "1234567")
    else:  # 跨午夜：凌晨那一段算前一天的
        ok_time = hm >= a or hm < b
        ok_day = str(day if hm >= a else (day - 2) % 7 + 1) in (rule.days or "1234567")
    return ok_time and ok_day


def window_start(rule, ts: float) -> float:
    """这一段生效时段从哪天 0 点算起：跨午夜的时段（22:00-06:00）凌晨那一段属于前一天，
    累计流量和“一天一次”都按它算，不能到 0 点就清零重报"""
    d = datetime.fromtimestamp(ts, _tz())
    a, b = rule.time_from or "00:00", rule.time_to or "24:00"
    start = d.replace(hour=0, minute=0, second=0, microsecond=0)
    if a > b and d.strftime("%H:%M") < b:
        from datetime import timedelta
        start = (start - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return start.timestamp()


def domain_match(domain: str, suffix: str) -> bool:
    suffix = suffix.lower().strip(".")
    return domain == suffix or domain.endswith("." + suffix)


class Auditor:
    def __init__(self, engine):
        self.engine = engine
        self._rules: list = []
        self._loaded = 0
        self._acc: dict[tuple, int] = defaultdict(int)     # (rule, host, 日期) -> 生效时段内累计字节
        self._fired: dict[tuple, float] = {}               # (rule, host) -> 上次命中时间
        self.events = 0

    def reload(self):
        self._loaded = 0

    def _rules_now(self):
        if time.time() - self._loaded > 60:
            with database.session() as db:
                self._rules = [r for r in db.scalars(select(AuditRule).where(AuditRule.enabled == 1))]
                for r in self._rules:
                    db.expunge(r)
            self._loaded = time.time()
        return self._rules

    def evaluate(self, buf: dict, dom: dict, new_hosts: list, now: float):
        """buf: {(host, app): [up, down, flows]}；dom: {(host, domain, app): bytes}；new_hosts: [(key, ip, mac)]"""
        try:
            rules = self._rules_now()
        except Exception:  # noqa: BLE001  数据库暂时不可用
            return
        if not rules:
            return
        cl = self.engine.classifier
        events = []
        # 只保留近两天的累计（以前按天累积的键永远不删）
        if len(self._acc) > 1000:
            keep = _day_start(now) - 86400
            self._acc = defaultdict(int, {k: v for k, v in self._acc.items() if k[2] >= keep})
        sharing_hits = None
        for rule in rules:
            if not in_window(rule, now):
                continue
            day = window_start(rule, now)
            only = people.expand_scope([x for x in (rule.hosts or "").split(",") if x])
            hits: dict[str, dict] = defaultdict(lambda: {"bytes": 0, "items": defaultdict(int)})
            if rule.kind == "new_host":
                for key, ip, mac in new_hosts:
                    if not only or key in only:
                        hits[key]["items"][ip or key] += 0
            elif rule.kind == "sharing":
                if sharing_hits is None:
                    sharing_hits = sharing.suspects(self.engine.ttl_snapshot())[1]
                for s in sharing_hits:
                    if not only or s["host"] in only:
                        for ttl, n in s["ttls"].items():
                            hits[s["host"]]["items"][f"TTL {ttl}"] += 0
                        hits[s["host"]]["items"]["|".join(s["reasons"])] += 0
            elif rule.kind == "domain":
                for (host, domain, _app), b in dom.items():
                    if (not only or host in only) and domain_match(domain, rule.value or ""):
                        hits[host]["bytes"] += b
                        hits[host]["items"][domain] += b
            else:
                for (host, app), (up, down, _f) in buf.items():
                    if only and host not in only:
                        continue
                    if rule.kind == "traffic":
                        ok = True
                    elif rule.kind == "upload":
                        # 大流量外发：只算上行；value 可选，限定应用大类或分类（例如网盘）
                        a = cl.app_info(app)
                        ok = not rule.value or rule.value in (a.category, cl.category_info(a.category)["group"])
                        if ok and up:
                            hits[host]["bytes"] += up
                            hits[host]["items"][app] += up
                        continue
                    else:
                        a = cl.app_info(app)
                        grp = cl.category_info(a.category)["group"]
                        ok = {"group": grp, "category": a.category, "app": app}.get(rule.kind) == rule.value
                    if ok:
                        hits[host]["bytes"] += up + down
                        hits[host]["items"][app] += up + down
            for host, h in hits.items():
                if rule.kind not in ("new_host", "sharing") and h["bytes"] <= 0:
                    continue
                key = (rule.id, host)
                if rule.kind == "sharing":
                    if self._fired.get(key, 0) >= _day_start(now):  # 私接路由：每台一天提醒一次
                        continue
                    self._fired[key] = now
                    events.append((rule, host, {"bytes": 0, "total": 0, "items": list(h["items"].items())[:6]}))
                    continue
                if rule.min_bytes:
                    self._acc[(rule.id, host, day)] += h["bytes"]
                    if self._acc[(rule.id, host, day)] < rule.min_bytes:
                        continue
                    if self._fired.get(key, 0) >= day:  # 每个生效时段一次
                        continue
                elif now - self._fired.get(key, 0) < 3600:          # 一小时一次
                    continue
                self._fired[key] = now
                total = self._acc.get((rule.id, host, day), h["bytes"])
                top = sorted(h["items"].items(), key=lambda x: -x[1])[:5]
                events.append((rule, host, {"bytes": h["bytes"], "total": total, "items": top}))
        if len(self._acc) > 50_000:
            self._acc = defaultdict(int, {k: v for k, v in self._acc.items() if k[2] == day})
        if events:
            self._record(events, now)

    def _record(self, events, now):
        from app import stats
        with database.session() as db:
            meta = stats.host_meta(db, {h for _r, h, _d in events})
            rows = []
            for rule, host, detail in events:
                rows.append(AuditEvent(ts=int(now), rule_id=rule.id, rule_name=rule.name, host=host,
                                       detail=json.dumps(detail, ensure_ascii=False), notified=0))
            db.add_all(rows)
            db.commit()
            from app import compliance
            for rule, host, detail in events:
                compliance.send_event(rule.name, host, detail)
            push = [(row.id, rule, host, detail) for row, (rule, host, detail) in zip(rows, events) if rule.notify]
        self.events += len(events)
        if not push:
            return
        if notify.in_quiet(now):
            # 免打扰：先标成“待推送”，结束后由 flush_deferred 汇总发出
            with database.session() as db:
                for ev in db.scalars(select(AuditEvent).where(AuditEvent.id.in_([p[0] for p in push]))):
                    ev.notified = 2
                db.commit()
            return
        self._dispatch([(i, rule, host, detail, meta[host]) for i, rule, host, detail in push], now)

    def line(self, rule_name: str, kind: str, m: dict, detail: dict) -> str:
        what = "、".join(self._label(x) for x, _b in detail.get("items", [])[:3])
        size = _fmt_bytes(detail.get("total") or detail.get("bytes") or 0)
        who = m["name"] + (f"（{m['person']['name']}）" if m.get("person") else "")
        return f"· {who} {m.get('ip') or ''} {what} {size if kind not in ('new_host', 'sharing') else ''}".rstrip() + f"  [{rule_name}]"

    def _dispatch(self, items: list, now: float, title: str | None = None):
        """items: [(事件 id, 规则, 终端, detail, 终端信息)]。按规则选的渠道分组发送，成功后标成已推送"""
        by_types: dict[tuple, list] = defaultdict(list)
        for i, rule, host, detail, m in items:
            types = tuple(sorted(x for x in (rule.channels or "").split(",") if x)) or ()
            by_types[types].append((i, self.line(rule.name, rule.kind, m, detail)))
        t = datetime.fromtimestamp(now, _tz()).strftime("%m-%d %H:%M")
        for types, rows in by_types.items():
            threading.Thread(target=self._push, args=(title or f"ROS-DPI 审计提醒 {t}", "\n".join(r[1] for r in rows),
                                                      [r[0] for r in rows], list(types) or None), daemon=True).start()

    def _push(self, title: str, text: str, ids: list[int], types: list[str] | None = None):
        """至少一个渠道发送成功才把事件标成已推送；没配渠道或全部失败时保持未推送"""
        res = notify.send(title, text, types=types, wait=True)
        with database.session() as db:
            for ev in db.scalars(select(AuditEvent).where(AuditEvent.id.in_(ids))):
                ev.notified = 1 if any(r["ok"] for r in res) else 0
            db.commit()

    def flush_deferred(self):
        """免打扰结束后：把期间记下的事件汇总推送一次（每分钟检查）"""
        if not database.is_configured() or notify.in_quiet():
            return
        from app import stats
        with database.session() as db:
            if not getattr(self, "_sending_reset", False):
                # 上次进程在发送途中退出：“发送中”的事件放回待发
                db.execute(update(AuditEvent).where(AuditEvent.notified == 3).values(notified=2))
                self._sending_reset = True
            evs = db.scalars(select(AuditEvent).where(AuditEvent.notified == 2).order_by(AuditEvent.ts).limit(500)).all()
            if not evs:
                db.commit()
                return
            rules = {r.id: r for r in db.scalars(select(AuditRule))}
            meta = stats.host_meta(db, {e.host for e in evs})
            items = []
            for e in evs:
                r = rules.get(e.rule_id)
                # 先标成“发送中”（3）再推送：推送比一分钟长时，下一轮不会把同一批再查出来重复发送；
                # 规则已删除的直接作废，不能一直占着前 500 条让新积压的永远排不上
                e.notified = 3 if r is not None else 0
                if r is not None:
                    items.append((e.id, r, e.host, json.loads(e.detail or "{}"), meta[e.host]))
            db.commit()
        self._dispatch(items, time.time(), title=f"ROS-DPI 免打扰期间的审计提醒（{len(items)} 条）")

    def _label(self, x: str) -> str:
        a = self.engine.classifier.apps.get(x)
        return str(a.name) if a else x


def _day_start(ts: float) -> float:
    d = datetime.fromtimestamp(ts, _tz())
    return d.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()


def _fmt_bytes(n: float) -> str:
    for u in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or u == "TB":
            return f"{n:.0f} {u}" if u == "B" else f"{n:.1f} {u}"
        n /= 1024
    return f"{n} B"


# ---------------- 报表 ----------------

def report(db, rng: str) -> dict:
    """审计报表的数据：总量、Top 终端 / 应用 / 大类、新终端、审计事件"""
    from sqlalchemy import func

    from app import stats, timeutil
    from app.models import Host
    start, end = timeutil.range_bounds(rng)
    apps = stats.top_apps(db, start, end)
    cats = stats.top_categories(apps)
    ev = db.execute(select(AuditEvent.rule_name, func.count()).where(AuditEvent.ts >= start, AuditEvent.ts < end)
                    .group_by(AuditEvent.rule_name).order_by(func.count().desc())).all()
    new = db.scalars(select(Host).where(Host.first_seen >= start, Host.first_seen < end)).all()
    meta = stats.host_meta(db, [h.key for h in new])
    return {
        "range": rng, "start": start, "end": end,
        "total": stats.total(db, start, end),
        "identified_ratio": stats.identified_ratio(apps),
        "top_hosts": stats.top_hosts(db, start, end, limit=10),
        "top_people": top_people(db, start, end),
        "top_apps": apps[:10],
        "groups": stats.top_groups(cats),
        "new_hosts": [meta[h.key] for h in new][:50],
        "events": [{"rule": r or "-", "count": int(n)} for r, n in ev],
        "events_total": sum(int(n) for _r, n in ev),
    }


def top_people(db, start, end, limit=10) -> list[dict]:
    """按人员汇总的流量排行（只算已经分给人的设备）"""
    from sqlalchemy import func

    from app.models import TrafficDay
    c = people.load(db)
    if not c["dev"]:
        return []
    t = TrafficDay
    per: dict[int, list] = {}
    for h, u, d in db.execute(select(t.host, func.sum(t.up), func.sum(t.down)).where(
            t.ts >= start, t.ts < end, t.host.in_(list(c["dev"]))).group_by(t.host)):
        pid = c["dev"].get(h)
        x = per.setdefault(pid, [0, 0])
        x[0] += int(u)
        x[1] += int(d)
    rows = [{"id": pid, "name": c["people"][pid]["name"], "dept": c["depts"].get(c["people"][pid]["dept_id"]),
             "up": u, "down": d, "total": u + d} for pid, (u, d) in per.items() if pid in c["people"]]
    return sorted(rows, key=lambda r: -r["total"])[:limit]


def report_text(r: dict) -> tuple[str, str]:
    from app.stats import app_meta  # noqa: F401
    title = {"yesterday": "ROS-DPI 日报", "last7": "ROS-DPI 周报"}.get(r["range"], "ROS-DPI 报表")
    d0 = datetime.fromtimestamp(r["start"], _tz()).strftime("%m-%d")
    d1 = datetime.fromtimestamp(r["end"] - 1, _tz()).strftime("%m-%d")
    lines = [f"{d0}{'' if d0 == d1 else ' ~ ' + d1}  总流量 {_fmt_bytes(r['total']['total'])}"
             f"（↓{_fmt_bytes(r['total']['down'])} ↑{_fmt_bytes(r['total']['up'])}），识别率 {r['identified_ratio'] * 100:.0f}%"]
    if r.get("top_people"):
        lines.append("Top 人员：" + "，".join(f"{p['name']} {_fmt_bytes(p['total'])}" for p in r["top_people"][:5]))
    if r["top_hosts"]:
        lines.append("Top 终端：" + "，".join(f"{h['name']} {_fmt_bytes(h['total'])}" for h in r["top_hosts"][:5]))
    if r["top_apps"]:
        lines.append("Top 应用：" + "，".join(f"{a['name']} {_fmt_bytes(a['total'])}" for a in r["top_apps"][:5]))
    if r["new_hosts"]:
        lines.append(f"新终端 {len(r['new_hosts'])} 台：" + "，".join(f"{h['name']}" for h in r["new_hosts"][:8]))
    if r["events_total"]:
        lines.append(f"审计事件 {r['events_total']} 次：" + "，".join(f"{e['rule']} {e['count']}" for e in r["events"][:5]))
    return title, "\n".join(lines)


def push_report(kind: str):
    """kind: daily（昨天）| weekly（近 7 天）。在设置里开启后由定时任务调用"""
    if not database.is_configured():
        return
    key = {"daily": "report_daily", "weekly": "report_weekly"}[kind]
    with database.session() as db:
        row = db.get(Setting, key)
        if not row or row.value != "1":
            return
        r = report(db, "yesterday" if kind == "daily" else "last7")
    title, text = report_text(r)
    notify.send(title, text)


def _make():
    from app.engine import engine
    a = Auditor(engine)
    engine.audit = a
    return a


auditor = _make()
