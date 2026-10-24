"""按当前规则重算历史分类。

以 host_domain_day（每天每终端每域名，31 天）为源：对每一行用现在的规则重新分类，分类结果变化的行，
把 traffic_day 里对应 (天, 终端, 旧应用) 的上下行与连接数按字节占比搬到新应用，并把 host_domain_day 的
app 标记同步改掉（保证重复执行幂等）。host_domain_day 只覆盖有域名、或进了当分钟 Top30 IP 的流量，
其余流量保持原分类；traffic_minute / traffic_hour 不动，随保留期自然滚动。
"""
import ipaddress
import time
from collections import defaultdict

from sqlalchemy import select

from app.models import HostDomainDay, TrafficDay


def _is_ip(s: str) -> bool:
    try:
        ipaddress.ip_address(s)
        return True
    except ValueError:
        return False


def reclassify(engine, db) -> dict:
    t0 = time.time()
    classifier = engine.classifier
    moves: dict = defaultdict(lambda: defaultdict(int))  # (ts, host, 旧应用) -> {新应用: 字节}
    marks: list[dict] = []
    rows = db.execute(
        select(HostDomainDay.ts, HostDomainDay.host, HostDomainDay.domain, HostDomainDay.app, HostDomainDay.bytes)
    ).all()
    for ts, host, dom, old_app, b in rows:
        if not b:
            continue
        if _is_ip(dom):
            new_app = classifier.classify(dom, 6, 0, None, None)
        else:
            new_app = classifier.classify("0.0.0.0", 6, 443, dom, None)
        new_app = new_app or "other"
        if new_app != old_app:
            moves[(int(ts), host, old_app)][new_app] += int(b)
            marks.append({"ts": int(ts), "host": host, "domain": dom, "app": new_app})
    if marks:
        db.bulk_update_mappings(HostDomainDay, marks)

    # 先在内存里把搬移汇总（同一个目标行可能来自多个源、同一个源可能拆给多个目标），再统一落库
    srcs: dict = defaultdict(lambda: [0, 0, 0])  # (ts, host, 旧应用) -> 要减掉的 [up, down, flows]
    dsts: dict = defaultdict(lambda: [0, 0, 0])  # (ts, host, 新应用) -> 要加上的 [up, down, flows]
    for (ts, host, old_app), tgts in moves.items():
        src = db.get(TrafficDay, {"ts": ts, "host": host, "app": old_app})
        if src is None:
            continue
        total_old = src.up + src.down
        if total_old <= 0:
            continue
        ratio_up = src.up / total_old
        flows_per_byte = (src.flows or 0) / total_old
        remain = total_old
        for new_app, b in tgts.items():
            mv = min(b, remain)
            if mv <= 0:
                break
            remain -= mv
            up = round(mv * ratio_up)
            down = mv - up
            flows = min(round(mv * flows_per_byte), src.flows)
            d = dsts[(ts, host, new_app)]
            d[0] += up
            d[1] += down
            d[2] += flows
            s_ = srcs[(ts, host, old_app)]
            s_[0] += up
            s_[1] += down
            s_[2] += flows
    for key, (up, down, flows) in srcs.items():
        src = db.get(TrafficDay, {"ts": key[0], "host": key[1], "app": key[2]})
        if src is None:
            continue
        src.up = max(src.up - up, 0)
        src.down = max(src.down - down, 0)
        src.flows = max(src.flows - flows, 0)
    for key, (up, down, flows) in dsts.items():
        dst = db.get(TrafficDay, {"ts": key[0], "host": key[1], "app": key[2]})
        if dst is None:
            db.add(TrafficDay(ts=key[0], host=key[1], app=key[2], up=up, down=down, flows=flows))
        else:
            dst.up += up
            dst.down += down
            dst.flows += flows
    return {"scanned": len(rows), "rows_moved": len(dsts), "bytes_moved": sum(v[0] + v[1] for v in dsts.values()),
            "flows_moved": sum(v[2] for v in dsts.values()), "seconds": round(time.time() - t0, 1)}
