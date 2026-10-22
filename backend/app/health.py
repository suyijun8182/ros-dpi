"""网络健康指数：100 分起扣，每一项给出扣分原因（code + 参数，由前端翻译成文字和改进建议）。

只用 ROS-DPI 已有的数据：采集状态、RouterOS 只读 API、今日统计。
"""
import time

from sqlalchemy import distinct, func, select

from app import stats, timeutil
from app.engine import engine
from app.models import TrafficDay
from app.ros_poller import poller


def _item(code, deduct, ok, **params):
    return {"code": code, "deduct": deduct if not ok else 0, "ok": ok, "params": params}


def compute(db) -> dict:
    now = time.time()
    st = engine.stats
    items = []

    # 1. 流量采集：一切统计的前提
    last = st["last_flow"]
    items.append(_item("flow", 30, bool(last and now - last < 180), last=last))

    # 2. 应用识别的数据来源
    dns_ok = bool(st["last_dns"] and now - st["last_dns"] < 600)
    sni_ok = bool(st["last_sni"] and now - st["last_sni"] < 600)
    if not dns_ok and not sni_ok:
        items.append(_item("appid", 15, False))
    else:
        items.append(_item("sni", 5, sni_ok, dns=dns_ok))

    # 3. 今日应用识别率
    start, end = timeutil.range_bounds("today")
    apps = stats.top_apps(db, start, end)
    total = sum(a["total"] for a in apps)
    ratio = stats.identified_ratio(apps) if total else 1.0
    items.append(_item("identified", 15 if ratio < .6 else 10, ratio >= .8 or not total, ratio=round(ratio, 3)))

    # 4. RouterOS API 及其提供的状态
    r = poller.status()
    if not r["enabled"]:
        items.append(_item("ros", 5, False, state="off"))
    elif not r["ok"]:
        items.append(_item("ros", 10, False, state="error", error=r["error"]))
    else:
        items.append(_item("ros", 0, True, state="ok"))
        down = [w["name"] for w in poller.wans if not w["running"]]
        items.append(_item("wan", 25, not down, down=down, total=len(poller.wans)))
        cpu = r["cpu_load"] or 0
        items.append(_item("cpu", 10, cpu < 80, cpu=cpu))
        if r["mem_total"]:
            used = 1 - (r["mem_free"] or 0) / r["mem_total"]
            items.append(_item("mem", 10, used < .9, used=round(used, 3)))
        chk = poller.check()
        bad = [x for x in chk["rules"] if x["problems"]]
        items.append(_item("rules", 10, not bad, rules=len(chk["rules"]), bad=len(bad),
                           port=chk.get("port"), wrong=sorted({x["target_port"] for x in bad if "port" in x["problems"]})))
        full = [p for p in poller.pools if p["size"] and p["used"] / p["size"] >= .75]
        worst = max(full, key=lambda p: p["used"] / p["size"]) if full else None
        items.append(_item("pool", 10 if worst and worst["used"] / worst["size"] >= .9 else 5, not worst,
                           server=worst["server"] if worst else None, used=worst["used"] if worst else 0,
                           size=worst["size"] if worst else 0))

    # 5. 终端在用加密 DNS（DoH）：只开 DNS 嗅探时这些终端的应用认不出来
    n_doh = db.scalar(select(func.count(distinct(TrafficDay.host)))
                      .where(TrafficDay.ts >= start, TrafficDay.ts < end, TrafficDay.app == "doh")) or 0
    items.append(_item("doh", 3, n_doh == 0 or sni_ok, hosts=n_doh))

    score = max(0, 100 - sum(i["deduct"] for i in items))
    level = "excellent" if score >= 90 else "good" if score >= 75 else "fair" if score >= 60 else "poor"
    # 先列扣分项（扣得多的在前），再列正常项
    items.sort(key=lambda i: (i["ok"], -i["deduct"]))
    return {"score": score, "level": level, "items": items}
