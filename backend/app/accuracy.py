"""识别校验（0.6.29）：用"已知答案"的流量核对识别得对不对。

做法：在手机上只开一个应用用几分钟，同时在 识别规则 → 识别校验 选这台终端和这个应用，点开始 / 结束。
这段时间里这台终端的流量（每分钟明细 traffic_minute）按识别结果拆开：
- 命中：识别成了预期的应用；
- 同类：识别成同一小类的其它应用（比如预期抖音、认成了抖音火山版）；
- 笼统：HTTPS / 国内网络 / 未识别这类没说出具体应用的；
- 认错：识别成了别的具体应用。
手机后台本来就有推送、系统更新等流量，所以命中率不会是 100%，看"认错"里排前面的是什么更有用。
"""
import json
import time

from sqlalchemy import func, select

from app import timeutil
from app.models import AccuracyProbe, TrafficMinute

FREEZE_AFTER = 120      # 结束 2 分钟后最后一分钟的数据已经落库，结果冻结
MAX_SPAN = 6 * 3600     # 一次校验最长 6 小时（每分钟明细只留 2 天，也没必要更长）
TOP = 8


def measure(db, classifier, host: str, expected: str, start: int, end: int) -> dict:
    from app.reclass import _vague
    t = TrafficMinute
    rows = db.execute(select(t.app, func.sum(t.up), func.sum(t.down))
                      .where(t.host == host, t.ts >= timeutil.minute_bucket(start), t.ts <= timeutil.minute_bucket(end))
                      .group_by(t.app)).all()
    exp_cat = classifier.app_info(expected).category
    out = {"total": 0, "hit": 0, "same_cat": 0, "vague": 0, "wrong": 0, "apps": []}
    for app, up, down in rows:
        b = int(up or 0) + int(down or 0)
        if not b:
            continue
        if app == expected:
            kind = "hit"
        elif _vague(classifier, app):
            kind = "vague"
        elif classifier.app_info(app).category == exp_cat:
            kind = "same_cat"
        else:
            kind = "wrong"
        out[kind] += b
        out["total"] += b
        out["apps"].append({"app": app, "bytes": b, "kind": kind})
    out["apps"].sort(key=lambda x: -x["bytes"])
    out["apps"] = out["apps"][:TOP]
    return out


def view(db, classifier, p: AccuracyProbe, now: float | None = None) -> dict:
    """一条校验的展示数据；已结束且过了冻结时间的，结果算一次存起来"""
    now = time.time() if now is None else now
    res = None
    if p.result:
        try:
            res = json.loads(p.result)
        except ValueError:
            res = None
    if res is None:
        res = measure(db, classifier, p.host, p.expected, p.start, int(p.end or now))
        if p.end and now - p.end >= FREEZE_AFTER:
            p.result = json.dumps(res)
    state = "running" if not p.end else ("done" if p.result else "settling")
    return {"id": p.id, "host": p.host, "expected": p.expected, "start": p.start, "end": p.end, "note": p.note,
            "state": state, **res}


def summary(items: list[dict]) -> dict:
    """已结束的校验合计：按字节加权的命中率"""
    done = [x for x in items if x["state"] != "running" and x["total"]]
    total = sum(x["total"] for x in done)
    agg = {k: sum(x[k] for x in done) for k in ("hit", "same_cat", "vague", "wrong")}
    return {"probes": len(done), "total": total, **agg}
