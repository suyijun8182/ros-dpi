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
from sqlalchemy import select

from app import database
from app.config import get_settings
from app.models import AuditEvent, AuditRule, Setting

CHANNEL_TYPES = ("wecom", "dingtalk", "feishu", "bark", "telegram", "webhook")


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


def domain_match(domain: str, suffix: str) -> bool:
    suffix = suffix.lower().strip(".")
    return domain == suffix or domain.endswith("." + suffix)


class Notifier:
    """把文字消息推送到用户配置的各个通道（企业微信 / 钉钉 / 飞书群机器人、Bark、Telegram、通用 Webhook）"""

    def __init__(self):
        self.last: dict[int, dict] = {}  # 通道序号 -> {ok, error, ts}

    @staticmethod
    def channels() -> list[dict]:
        if not database.is_configured():
            return []
        with database.session() as db:
            row = db.get(Setting, "notify_channels")
        try:
            return [c for c in json.loads(row.value) if isinstance(c, dict)] if row and row.value else []
        except ValueError:
            return []

    def send(self, title: str, text: str, channels: list[dict] | None = None, wait: bool = False) -> list[dict]:
        chans = [c for c in (channels if channels is not None else self.channels()) if c.get("enabled", True)]
        results = []

        def run():
            for i, c in enumerate(chans):
                try:
                    self._send_one(c, title, text)
                    r = {"ok": True, "error": "", "ts": int(time.time())}
                except Exception as e:  # noqa: BLE001
                    r = {"ok": False, "error": f"{type(e).__name__}: {str(e)[:160]}", "ts": int(time.time())}
                self.last[i] = r
                results.append({"name": c.get("name") or c.get("type"), **r})

        if wait:
            run()
        else:
            threading.Thread(target=run, daemon=True).start()
        return results

    @staticmethod
    def _send_one(c: dict, title: str, text: str):
        t, url = c.get("type"), (c.get("url") or "").strip()
        body = f"{title}\n{text}"
        with httpx.Client(timeout=10) as h:
            if t == "wecom":
                r = h.post(url, json={"msgtype": "text", "text": {"content": body}})
            elif t == "dingtalk":
                r = h.post(url, json={"msgtype": "text", "text": {"content": body}})
            elif t == "feishu":
                r = h.post(url, json={"msg_type": "text", "content": {"text": body}})
            elif t == "bark":
                r = h.post(url.rstrip("/"), json={"title": title, "body": text, "group": "ROS-DPI"})
            elif t == "telegram":
                r = h.post(f"https://api.telegram.org/bot{c.get('token', '')}/sendMessage",
                           json={"chat_id": c.get("chat_id"), "text": body})
            else:
                r = h.post(url, json={"title": title, "text": text, "source": "ros-dpi"})
            r.raise_for_status()
            # 群机器人接口出错时 HTTP 也是 200，看返回码
            try:
                j = r.json()
            except ValueError:
                return
            code = j.get("errcode", j.get("code", 0)) if isinstance(j, dict) else 0
            if code not in (0, None, 200):
                raise RuntimeError(j.get("errmsg") or j.get("msg") or str(j)[:120])


class Auditor:
    def __init__(self, engine):
        self.engine = engine
        self.notifier = Notifier()
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
        day = datetime.fromtimestamp(now, _tz()).strftime("%Y%m%d")
        events = []
        for rule in rules:
            if not in_window(rule, now):
                continue
            only = {x for x in (rule.hosts or "").split(",") if x}
            hits: dict[str, dict] = defaultdict(lambda: {"bytes": 0, "items": defaultdict(int)})
            if rule.kind == "new_host":
                for key, ip, mac in new_hosts:
                    if not only or key in only:
                        hits[key]["items"][ip or key] += 0
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
                    else:
                        a = cl.app_info(app)
                        grp = cl.category_info(a.category)["group"]
                        ok = {"group": grp, "category": a.category, "app": app}.get(rule.kind) == rule.value
                    if ok:
                        hits[host]["bytes"] += up + down
                        hits[host]["items"][app] += up + down
            for host, h in hits.items():
                if rule.kind != "new_host" and h["bytes"] <= 0:
                    continue
                key = (rule.id, host)
                if rule.min_bytes:
                    self._acc[(rule.id, host, day)] += h["bytes"]
                    if self._acc[(rule.id, host, day)] < rule.min_bytes:
                        continue
                    if self._fired.get(key, 0) >= _day_start(now):  # 一天一次
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
            push_ids = [row.id for row, (rule, _h, _d) in zip(rows, events) if rule.notify]
        self.events += len(events)
        lines = []
        for rule, host, detail in events:
            if not rule.notify:
                continue
            m = meta[host]
            what = "、".join(self._label(x) for x, _b in detail["items"][:3])
            size = _fmt_bytes(detail.get("total") or detail["bytes"])
            lines.append(f"· {m['name']}（{m['ip']}）{what} {size if rule.kind != 'new_host' else ''}".rstrip()
                         + f"  [{rule.name}]")
        if lines and any(c.get("enabled", True) for c in self.notifier.channels()):
            t = datetime.fromtimestamp(now, _tz()).strftime("%m-%d %H:%M")
            threading.Thread(target=self._push, args=(f"ROS-DPI 审计提醒 {t}", "\n".join(lines), push_ids),
                             daemon=True).start()

    def _push(self, title: str, text: str, ids: list[int]):
        """至少一个通道发送成功才把事件标成已推送；没配通道或全部失败时保持未推送"""
        res = self.notifier.send(title, text, wait=True)
        if ids and any(r["ok"] for r in res):
            with database.session() as db:
                for ev in db.scalars(select(AuditEvent).where(AuditEvent.id.in_(ids))):
                    ev.notified = 1
                db.commit()

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
        "top_apps": apps[:10],
        "groups": stats.top_groups(cats),
        "new_hosts": [meta[h.key] for h in new][:50],
        "events": [{"rule": r or "-", "count": int(n)} for r, n in ev],
        "events_total": sum(int(n) for _r, n in ev),
    }


def report_text(r: dict) -> tuple[str, str]:
    from app.stats import app_meta  # noqa: F401
    title = {"yesterday": "ROS-DPI 日报", "last7": "ROS-DPI 周报"}.get(r["range"], "ROS-DPI 报表")
    d0 = datetime.fromtimestamp(r["start"], _tz()).strftime("%m-%d")
    d1 = datetime.fromtimestamp(r["end"] - 1, _tz()).strftime("%m-%d")
    lines = [f"{d0}{'' if d0 == d1 else ' ~ ' + d1}  总流量 {_fmt_bytes(r['total']['total'])}"
             f"（↓{_fmt_bytes(r['total']['down'])} ↑{_fmt_bytes(r['total']['up'])}），识别率 {r['identified_ratio'] * 100:.0f}%"]
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
    Notifier().send(title, text)


def _make():
    from app.engine import engine
    a = Auditor(engine)
    engine.audit = a
    return a


auditor = _make()
