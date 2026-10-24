"""历史分类重算：规则 / 识别库升级后，把历史流量搬到新归属。

以 host_domain_day（每天每终端每域名，31 天）为源：对每一行用现在的规则重新分类，分类结果变化的行，
把 traffic_day 里对应 (天, 终端, 旧应用) 的上下行与连接数按字节占比搬到新应用，并把 host_domain_day 的
app 标记同步改掉（保证重复执行幂等）。host_domain_day 只覆盖有域名、或进了当分钟 Top30 IP 的流量，
其余流量保持原分类；traffic_minute / traffic_hour 不动，随保留期自然滚动。

纯 IP 的历史行会用 dns_cache 反查域名再分类（嗅探 / MosDNS / AdGuard Home 积累的映射）——DNS 缓存
会过期，所以已经归到具体应用、又拿不到新域名证据的行保持不动，避免缓存过期让历史分类倒退。

识别库更新 / DNS 映射积累后自动重算：fingerprint() 覆盖各层库的规模和 DNS 缓存行数，指纹变了才执行
（auto_reclassify），识别规则页的手动「重算历史分类」直接调 reclassify()。
"""
import ipaddress
import time
from collections import defaultdict

from sqlalchemy import func, select

from app.models import DnsCache, HostDomainDay, Setting, TrafficDay

FP_KEY = "reclass_fp"
# 纯 IP 行没有域名证据时，只有原本就归在这些笼统应用里的才重算（ASN / IP 段升级的直接受益者）
GENERIC_OLD = {"cn_net", "cn_web", "other", "unknown", "https", "quic", "http", "web", "site"}


def _is_ip(s: str) -> bool:
    try:
        ipaddress.ip_address(s)
        return True
    except ValueError:
        return False


def _dns_domain_map(db) -> dict[str, str]:
    """未过期的 IP→域名映射（嗅探 / MosDNS / AdGuard Home 积累的），给纯 IP 的历史行反查域名"""
    now = int(time.time())
    rows = db.execute(select(DnsCache.ip, DnsCache.name).where(DnsCache.expires > now)).all()
    return dict(rows)


def reclassify(engine, db) -> dict:
    t0 = time.time()
    classifier = engine.classifier
    cache = _dns_domain_map(db)
    moves: dict = defaultdict(lambda: defaultdict(int))  # (ts, host, 旧应用) -> {新应用: 字节}
    marks: list[dict] = []
    rows = db.execute(
        select(HostDomainDay.ts, HostDomainDay.host, HostDomainDay.domain, HostDomainDay.app, HostDomainDay.bytes)
    ).all()
    for ts, host, dom, old_app, b in rows:
        if not b:
            continue
        if _is_ip(dom):
            qname = cache.get(dom)
            if qname:
                new_app = classifier.classify(dom, 6, 0, qname, None)
            elif old_app in GENERIC_OLD:
                new_app = classifier.classify(dom, 6, 0, None, None)
            else:
                continue   # 已归到具体应用、又没有新的域名证据：保持不动（DNS 缓存过期不应让历史倒退）
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


def fingerprint(engine, db) -> str:
    """识别规则的有效指纹：任何一层库变了（v2fly 提交、第三方库规模、ASN 行数）或 DNS 映射积累变多都不一样"""
    from app.asn import asndb
    from app.classify.lists import lists as extra_lists
    from app.classify.updater import updater
    now = int(time.time())
    dns_n = db.scalar(select(func.count()).select_from(DnsCache).where(DnsCache.expires > now)) or 0
    libs = "|".join(f"{r['id']}:{r.get('domains', r.get('rules', 0))}" for r in extra_lists.rows())
    return "|".join([f"dns{dns_n}", f"asn{asndb.rows}", f"v2{updater.state.get('latest') or ''}",
                     f"apps{len(engine.classifier.apps)}", libs])


def auto_reclassify(engine, db) -> dict | None:
    """识别库更新 / DNS 映射积累后自动重算（debug14）：指纹没变就什么都不做，变了才重算并记住新指纹"""
    fp = fingerprint(engine, db)
    row = db.get(Setting, FP_KEY)
    if row is not None and row.value == fp:
        return None
    res = reclassify(engine, db)
    row = db.get(Setting, FP_KEY)
    if row is None:
        db.add(Setting(key=FP_KEY, value=fp))
    else:
        row.value = fp
    return res
