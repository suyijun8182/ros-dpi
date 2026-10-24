"""历史分类重算：规则 / 识别库升级后，把历史流量搬到新归属。

以 host_domain_day（每天每终端每域名，31 天）为源：对每一行用现在的规则重新分类，分类结果变化的行，
把 traffic_day 里对应 (天, 终端, 旧应用) 的上下行与连接数按字节占比搬到新应用，并把 host_domain_day 的
app 标记同步改掉（保证重复执行幂等）。host_domain_day 只覆盖有域名、或进了当分钟 Top30 IP 的流量，
其余流量保持原分类；traffic_minute / traffic_hour 不动，随保留期自然滚动。

只重算今天以前的数据：今天的行每分钟落库都会把 app 改回实时分类、字节继续累加，重算今天会把同一批字节
反复搬走，还会和落库争写同一行。今天的流量本来就按最新规则实时统计，过了零点由自动重算补上。

历史行只存了域名（或 IP），没有端口、目标 IP、sing-box 规则这些实时信号，所以只“升级”不“降级”：
- 新结果是笼统分类（HTTPS / 国内网站 / 未识别…）的不搬，免得把实时认出的应用改回笼统分类；
- 原来就是笼统分类的，认出具体应用就搬；
- 原来已是具体应用的，只有域名规则直接命中另一个应用时才改（例如识别库把某域名改归了别的应用）。
纯 IP 的历史行用 dns_cache 反查域名（嗅探 / MosDNS / AdGuard Home 积累的映射）再按上面的规则判断。

自动重算（auto_reclassify）：fingerprint() 覆盖各层库的版本 / 规模和日期，识别库变了或过了零点才执行；
识别规则页的手动「重算历史分类」直接调 reclassify()。
"""
import ipaddress
import time
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from app import timeutil
from app.classify import GENERIC_APPS, UNIDENTIFIED_CATEGORIES, WEAK_PREFIXES
from app.models import DnsCache, HostDomainDay, Setting, TrafficDay

FP_KEY = "reclass_fp"
# 只说明协议、地区或“是个网站”的笼统分类：可以被升级成具体应用，但重算不会把行改成它们
VAGUE_APPS = GENERIC_APPS | {"cn_net", "cn_web", "unknown"}


def _vague(classifier, app: str | None) -> bool:
    if not app or app in VAGUE_APPS or app.startswith(WEAK_PREFIXES):
        return True
    return classifier.app_info(app).category in UNIDENTIFIED_CATEGORIES


def _is_ip(s: str) -> bool:
    try:
        ipaddress.ip_address(s)
        return True
    except ValueError:
        return False


def _deadlock(e: Exception) -> bool:
    """MySQL 死锁（1213）或锁等待超时（1205）：落库任务每分钟在写同一批表，撞上重试即可"""
    s = str(e)
    return "(1213" in s or "(1205" in s


def reclassify(engine, db, before: int | None = None, attempts: int = 3) -> dict:
    """重算 before（默认今天零点）以前的历史分类"""
    for i in range(attempts):
        try:
            return _reclassify_once(engine, db, before)
        except OperationalError as e:
            db.rollback()
            if i == attempts - 1 or not _deadlock(e):
                raise
            time.sleep(2 + i * 2)


def _dns_domain_map(db) -> dict[str, str]:
    """未过期的 IP→域名映射（嗅探 / MosDNS / AdGuard Home 积累的），给纯 IP 的历史行反查域名"""
    now = int(time.time())
    rows = db.execute(select(DnsCache.ip, DnsCache.name).where(DnsCache.expires > now)).all()
    return dict(rows)


def _new_app(classifier, dom: str, old_app: str, cache: dict) -> str | None:
    """按现在的规则给一行历史重新归类；不该改时返回 None（规则见模块说明）"""
    if _is_ip(dom):
        qname = cache.get(dom)
        new_app = classifier.classify(dom, 6, 0, qname, None)
    else:
        qname = dom
        new_app = classifier.classify("0.0.0.0", 6, 443, dom, None)
    if not new_app or new_app == old_app or _vague(classifier, new_app):
        return None
    if _vague(classifier, old_app):
        return new_app
    # 原来已是具体应用：只认域名规则的直接证据（IP 段 / ASN / 端口当时按真实目标判断，历史行里没有这些信息）
    return new_app if qname and classifier.match_domain(qname) == new_app else None


def _reclassify_once(engine, db, before: int | None) -> dict:
    t0 = time.time()
    classifier = engine.classifier
    before = timeutil.day_bucket(time.time()) if before is None else before
    cache = _dns_domain_map(db)
    moves: dict = defaultdict(lambda: defaultdict(int))  # (ts, host, 旧应用) -> {新应用: 字节}
    marks: list[dict] = []
    rows = db.execute(
        select(HostDomainDay.ts, HostDomainDay.host, HostDomainDay.domain, HostDomainDay.app, HostDomainDay.bytes)
        .where(HostDomainDay.ts < before)
    ).all()
    for ts, host, dom, old_app, b in rows:
        if not b:
            continue
        new_app = _new_app(classifier, dom, old_app, cache)
        if new_app:
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
    """识别规则的有效指纹：任何一层库变了（v2fly 提交、第三方库规模、ASN 行数）或过了零点（昨天成了可重算的历史，
    期间积累的 DNS 映射也一并用上）都不一样。不再用 DNS 缓存行数：它几乎时刻在变，等于每次都全量重算"""
    from app.asn import asndb
    from app.classify.lists import lists as extra_lists
    from app.classify.updater import updater
    libs = "|".join(f"{r['id']}:{r.get('domains', r.get('rules', 0))}" for r in extra_lists.rows())
    return "|".join([f"day{timeutil.day_bucket(time.time())}", f"asn{asndb.rows}",
                     f"v2{updater.state.get('latest') or ''}", f"apps{len(engine.classifier.apps)}", libs])


def auto_reclassify(engine, db) -> dict | None:
    """识别库更新或过了零点后自动重算（debug14）：指纹没变就什么都不做，变了才重算并记住新指纹"""
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
