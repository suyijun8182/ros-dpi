"""上网时长、工作时间效率、行为标签（参照深信服 AC 的“效率分析 / 风险洞察”，只用访问日志能看到的信息）。

时长按访问日志的时段计算：同一应用的重叠时段先合并，再和“工作时间”“深夜”窗口求交集；单次访问不足 1 分钟按 1 分钟算。
"""
import json
import time
from bisect import bisect_left
from collections import defaultdict
from datetime import datetime, timedelta

from sqlalchemy import select

from app import timeutil
from app.engine import engine
from app.models import AccessLog, Setting

# 使用场景：家用侧重孩子的上网健康（屏幕时间、游戏、短视频、熬夜、不良内容），企业侧重效率与合规
SCENARIOS = {
    "enterprise": {
        "work_days": "12345",                                  # 周一 = 1
        "work": [["09:00", "12:00"], ["13:30", "18:00"]],      # 工作时间段
        "leisure": ["media", "game", "shopping"],              # 算“娱乐”的应用大类或分类
        "night": ["00:00", "05:00"],                           # 深夜
        "limits": {"screen": 0, "game": 0, "short_video": 0},  # 每日时长上限（秒），企业场景不用
    },
    "home": {
        "work_days": "12345",
        "work": [["19:00", "21:00"]],                          # 学习（写作业）时间
        "leisure": ["media", "game", "shopping", "social"],
        "night": ["22:00", "06:00"],                           # 该睡觉了
        "limits": {"screen": 3 * 3600, "game": 3600, "short_video": 3600},
    },
}
DEFAULTS = {"scenario": "home", **SCENARIOS["home"]}
JOB_APPS = {"jobs", "linkedin", "maimai"}
# 行为标签：(id, 依据, 中档阈值, 高档阈值)
#   work:<大类或分类>  工作 / 学习时间内的时长（秒）；work:leisure 为所有娱乐应用
#   days:<指标>        超过当日上限的天数（screen 屏幕时间、game 游戏、short_video 短视频）
#   job / night / adult 为访问招聘网站 / 深夜上网超过 15 分钟 / 访问成人内容的天数
TAG_RULES = {
    "enterprise": [
        ("job", "job", 2, 3),
        ("stock_work", "work:stock", 1800, 7200),
        ("game_work", "work:game", 1800, 7200),
        ("video_work", "work:media", 3600, 4 * 3600),
        ("shop_work", "work:shopping", 1800, 7200),
        ("late_night", "night", 3, 5),
    ],
    "home": [
        ("adult", "adult", 1, 1),
        ("screen_over", "days:screen", 2, 4),
        ("game_over", "days:game", 2, 4),
        ("short_video_over", "days:short_video", 2, 4),
        ("late_night", "night", 1, 3),
        ("study_leisure", "work:leisure", 1800, 7200),
    ],
}
_cache: dict[tuple, tuple[float, dict]] = {}
CACHE_SECONDS = 120


def get_config(db) -> dict:
    row = db.get(Setting, "analysis")
    cfg = dict(DEFAULTS)
    if row and row.value:
        try:
            saved = json.loads(row.value)
            scn = saved.get("scenario") if saved.get("scenario") in SCENARIOS else "home"
            cfg = {"scenario": scn, **SCENARIOS[scn]}
            cfg.update({k: v for k, v in saved.items() if k in DEFAULTS})
            cfg["limits"] = {**SCENARIOS[scn]["limits"], **(saved.get("limits") or {})}
        except ValueError:
            pass
    return cfg


def _hm(s: str) -> int:
    h, m = s.split(":")
    return int(h) * 3600 + int(m) * 60


def check_config(cfg: dict) -> dict:
    """校验并规范化分析设置，出错抛 ValueError。只给了场景时，其余用该场景的默认值"""
    scn = cfg.get("scenario") if cfg.get("scenario") in SCENARIOS else "home"
    base = SCENARIOS[scn]
    cfg = {**base, **{k: v for k, v in cfg.items() if v is not None}}
    out = {"scenario": scn, **base}
    lim = cfg.get("limits") or {}
    out["limits"] = {k: max(0, int(lim.get(k, base["limits"][k]) or 0)) for k in base["limits"]}
    days = "".join(sorted(set(str(cfg.get("work_days", "")) ) & set("1234567")))
    out["work_days"] = days
    ranges = []
    for a, b in cfg.get("work") or []:
        if _hm(a) >= _hm(b) and b != "24:00":
            raise ValueError(f"工作时间段 {a}–{b} 无效")
        ranges.append([a, b])
    out["work"] = ranges
    cl = engine.classifier
    ok = set(cl.groups) | set(cl.categories)
    out["leisure"] = [x for x in cfg.get("leisure") or [] if x in ok]
    n = cfg.get("night") or DEFAULTS["night"]
    _hm(n[0]), _hm(n[1])
    out["night"] = [n[0], n[1]]
    return out


def _merge(iv: list) -> list:
    out = []
    for s, e in sorted(iv):
        if out and s <= out[-1][1]:
            if e > out[-1][1]:
                out[-1][1] = e
        else:
            out.append([s, e])
    return out


def _overlap(merged: list, windows: list) -> int:
    """两组各自不重叠、已排序的时段的交集长度"""
    if not merged or not windows:
        return 0
    n, j = 0, 0
    for s, e in merged:
        while j < len(windows) and windows[j][1] <= s:
            j += 1
        k = j
        while k < len(windows) and windows[k][0] < e:
            n += min(e, windows[k][1]) - max(s, windows[k][0])
            k += 1
    return n


def _days(start: int, end: int):
    """[start, end) 里每一天的 (零点, 次日零点, 星期 1-7)"""
    tz = timeutil.tz()
    d = datetime.fromtimestamp(start, tz).replace(hour=0, minute=0, second=0, microsecond=0)
    while int(d.timestamp()) < end:
        nxt = (d + timedelta(days=1, hours=2)).replace(hour=0)
        yield int(d.timestamp()), int(nxt.timestamp()), d.isoweekday()
        d = nxt


def windows(start: int, end: int, cfg: dict) -> tuple[list, list, list]:
    """(每天的时段, 工作时间时段, 深夜时段)，都裁剪到 [start, end)"""
    days, work, night = [], [], []
    ns, ne = _hm(cfg["night"][0]), _hm(cfg["night"][1])
    for d0, d1, wd in _days(start, end):
        days.append([max(d0, start), min(d1, end)])
        if str(wd) in cfg["work_days"]:
            for a, b in cfg["work"]:
                work.append([d0 + _hm(a), d0 + _hm(b)])
        if ns < ne:
            night.append([d0 + ns, d0 + ne])
        else:  # 跨午夜，例如 23:00–05:00
            night += [[d0, d0 + ne], [d0 + ns, d1]]
    clip = lambda w: [[max(s, start), min(e, end)] for s, e in w if e > start and s < end]  # noqa: E731
    return days, _merge(clip(work)), _merge(clip(night))


def load_rows(db, hosts: list[str] | None, start: int, end: int) -> list[tuple]:
    t = AccessLog
    q = select(t.host, t.app, t.ts_start, t.ts_end, t.dest).where(t.ts_start < end, t.ts_end >= start)
    if hosts is not None:
        if not hosts:
            return []
        q = q.where(t.host.in_(hosts))
    return db.execute(q).all()


def _is_leisure(app: str, cfg: dict) -> bool:
    cl = engine.classifier
    c = cl.app_info(app).category
    return c in cfg["leisure"] or cl.category_info(c)["group"] in cfg["leisure"]


def analyze(rows: list, start: int, end: int, cfg: dict) -> dict:
    """rows: [(host, app, ts_start, ts_end, dest)]，一个人（或一台终端）的访问日志"""
    cl = engine.classifier
    per_app: dict[str, list] = defaultdict(list)
    job_days: set[int] = set()
    for _h, app, s, e, _d in rows:
        s, e = max(s, start), min(max(e, s + 60), end)
        if e > s:
            per_app[app].append([s, e])
    days, work, night = windows(start, end, cfg)
    day_starts = [d[0] for d in days]
    merged = {a: _merge(iv) for a, iv in per_app.items()}
    allm = _merge([x for m in merged.values() for x in m])
    leisure = _merge([x for a, m in merged.items() if _is_leisure(a, cfg) for x in m])

    def union_of(pred):
        return _merge([x for a, m in merged.items() if pred(a) for x in m])

    for a in JOB_APPS & set(merged):
        for s, _e in merged[a]:
            job_days.add(bisect_left(day_starts, s + 1) - 1)
    def in_key(a, key):
        c = cl.app_info(a).category
        return c == key or cl.category_info(c)["group"] == key

    game_u = union_of(lambda a: in_key(a, "game"))
    sv_u = union_of(lambda a: in_key(a, "short_video"))
    adult_u = union_of(lambda a: in_key(a, "adult"))
    out_days = []
    late_days = adult_days = 0
    lim = cfg.get("limits") or {}
    over = {"screen": 0, "game": 0, "short_video": 0}
    for d0, d1 in days:
        w = [[max(s, d0), min(e, d1)] for s, e in work if s < d1 and e > d0]
        n = [[max(s, d0), min(e, d1)] for s, e in night if s < d1 and e > d0]
        nsec = _overlap(allm, n)
        late_days += nsec >= 900
        day = {"ts": d0, "online": _overlap(allm, [[d0, d1]]), "work": _overlap(allm, w),
               "leisure_work": _overlap(leisure, w), "night": nsec, "game": _overlap(game_u, [[d0, d1]]),
               "short_video": _overlap(sv_u, [[d0, d1]])}
        adult_days += _overlap(adult_u, [[d0, d1]]) > 0
        for k, field in (("screen", "online"), ("game", "game"), ("short_video", "short_video")):
            if lim.get(k) and day[field] > lim[k]:
                over[k] += 1
        out_days.append(day)
    apps = []
    for a, m in merged.items():
        apps.append({**_app(a), "seconds": sum(e - s for s, e in m), "work_seconds": _overlap(m, work),
                     "leisure": _is_leisure(a, cfg)})
    apps.sort(key=lambda x: -x["seconds"])
    work_online, leisure_work = _overlap(allm, work), _overlap(leisure, work)

    # 行为标签
    def work_secs(key):
        if key == "leisure":
            return leisure_work
        return _overlap(union_of(lambda a: in_key(a, key)), work)

    def top_apps(key, n=3, field="work_seconds"):
        hit = [x for x in apps if (x["leisure"] if key == "leisure" else (x["category"] == key or x["group"] == key))]
        return sorted(hit, key=lambda x: -x[field])[:n]

    tags = []
    for tid, basis, mid, high in TAG_RULES.get(cfg.get("scenario"), TAG_RULES["home"]):
        if basis == "job":
            v, unit, ev = len(job_days), "days", [x for x in apps if x["id"] in JOB_APPS][:3]
        elif basis == "night":
            v, unit, ev = late_days, "days", []
        elif basis == "adult":
            v, unit, ev = adult_days, "days", top_apps("adult", field="seconds")
        elif basis.startswith("days:"):
            k = basis[5:]
            if not lim.get(k):
                continue
            v, unit = over[k], "days"
            ev = top_apps({"screen": "leisure", "game": "game", "short_video": "short_video"}[k], field="seconds")
        else:
            key = basis.split(":", 1)[1]
            v, unit, ev = work_secs(key), "seconds", top_apps(key)
        if v >= mid:
            tags.append({"id": tid, "level": "high" if v >= high else "mid", "value": v, "unit": unit,
                         "apps": [{"id": x["id"], "name": x["name"], "name_en": x["name_en"], "category": x["category"],
                                   "seconds": x["work_seconds"] if unit == "seconds" else x["seconds"]} for x in ev],
                         "limit": lim.get(basis[5:]) if basis.startswith("days:") else None})
    return {
        "start": start, "end": end, "online": sum(e - s for s, e in allm), "work_online": work_online,
        "leisure_work": leisure_work, "night": _overlap(allm, night),
        "efficiency": (1 - leisure_work / work_online) if work_online else None,
        "game": sum(d["game"] for d in out_days), "short_video": sum(d["short_video"] for d in out_days),
        "days": out_days, "apps": apps[:40], "tags": tags,
    }


def _app(a: str) -> dict:
    from app import stats
    return stats.app_meta(a)


def analyze_hosts(db, hosts: list[str], start: int, end: int, cfg: dict | None = None) -> dict:
    """带缓存（2 分钟）的 analyze"""
    cfg = cfg or get_config(db)
    key = (tuple(sorted(hosts)), start // 60, end // 60, json.dumps(cfg, sort_keys=True))
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < CACHE_SECONDS:
        return hit[1]
    res = analyze(load_rows(db, hosts, start, end), start, end, cfg)
    if len(_cache) > 500:
        _cache.clear()
    _cache[key] = (time.time(), res)
    return res


def analyze_many(db, groups: dict, start: int, end: int, cfg: dict | None = None) -> dict:
    """groups: {主体 id: [host_key...]}，一次查出所有访问日志再分组计算（人员列表用）"""
    cfg = cfg or get_config(db)
    hosts = sorted({h for hs in groups.values() for h in hs})
    key = ("many", tuple((k, tuple(sorted(v))) for k, v in sorted(groups.items())), start // 60, end // 60,
           json.dumps(cfg, sort_keys=True))
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < CACHE_SECONDS:
        return hit[1]
    by_host = defaultdict(list)
    for r in load_rows(db, hosts, start, end):
        by_host[r[0]].append(r)
    res = {k: analyze([r for h in hs for r in by_host.get(h, [])], start, end, cfg) for k, hs in groups.items()}
    _cache[key] = (time.time(), res)
    return res


def clear_cache():
    _cache.clear()
