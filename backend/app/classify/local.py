"""本地自学习库（debug15 / debug17）：把本网络实测的「IP → 应用」与「域名 → 应用」长期记忆接入分类管线。

host_domain_day（31 天）里的行，当初是靠 DNS / SNI / ASN / 端口认出来的——这些证据过后会消失
（DNS 缓存过期、终端改用 DoH、SNI 只在连接开头出现），但结论是实测来的，比任何公开库都准，
因为它只属于你自己的网络。本模块把结论沉淀成两类映射，每小时从数据库重建一次、热加载：

- IP → 应用（debug15）：IPv4 精确、IPv6 按 /64 前缀聚合（中国环境以 IPv6 公网为主，精确地址不稳定）；
- 域名 → 应用（debug17）：精确域名匹配，配合社区共享（其它部署实例的实测结论，本地没有结论时兜底）。

它随每一次历史重算自动纠正，与识别库升级、社区共享形成闭环。
"""
import ipaddress
import threading
import time
from collections import defaultdict

from sqlalchemy import func, select

from app.models import HostDomainDay

MAX_IPS = 200_000
MAX_DOMAINS = 200_000
# IPv6 精确地址在不同网络里几乎不重复（中国环境以 IPv6 公网为主）：按 /64 前缀聚合记忆与共享


def _is_ip(s: str) -> bool:
    try:
        ipaddress.ip_address(s)
        return True
    except ValueError:
        return False


def _v6key(ip: str) -> str | None:
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return None
    if a.version != 6:
        return None
    return str(ipaddress.ip_network(f"{a}/64", strict=False).network_address) + "/64"


class LocalDB:
    def __init__(self):
        self.lock = threading.Lock()
        self.version = 0
        self.updated = 0                 # 上次重建的时间（识别库面板显示用）
        self.ips: dict[str, str] = {}        # 本地实测：IPv4 精确 / IPv6 /64 前缀 -> 应用 ID（按历史字节数取最多的应用）
        self.domains: dict[str, str] = {}    # 本地实测（debug17）：精确域名 -> 应用 ID
        self.community: dict[str, str] = {}  # 社区共享（debug16）：其它实例的 IP 结论，只补本地空白
        self.community_domains: dict[str, str] = {}  # 社区共享（debug17）：其它实例的域名结论，只补本地空白

    def load(self, db, classifier=None):
        """从 host_domain_day 聚合：IP（IPv6 聚到 /64）与域名分别取历史字节数最多的应用；调用方提交事务。
        聚合在数据库里做（GROUP BY），不把几百万行逐行读进 Python——那会抢住 GIL，UDP 收包跟着丢。
        笼统结论（HTTPS / QUIC / 国内网络 / 未识别……）不进记忆：它们会挡住后面更准的识别，还会自我强化"""
        from app.reclass import _vague
        ip_votes: dict = defaultdict(dict)
        dom_votes: dict = defaultdict(dict)
        rows = db.execute(
            select(HostDomainDay.domain, HostDomainDay.app, func.sum(HostDomainDay.bytes))
            .group_by(HostDomainDay.domain, HostDomainDay.app)
        ).all()
        for dom, app, b in rows:
            if classifier is not None and _vague(classifier, app):
                continue
            if _is_ip(dom):
                key = _v6key(dom) or dom
                votes = ip_votes
            else:
                key, votes = dom, dom_votes
            per = votes[key]
            per[app] = per.get(app, 0) + int(b or 0)
        # 只留最大的 MAX_IPS / MAX_DOMAINS 个键（按总字节），避免极端环境下无限膨胀
        ips = {k: max(p, key=p.get) for k, p in
               sorted(ip_votes.items(), key=lambda kv: -sum(kv[1].values()))[:MAX_IPS]}
        domains = {k: max(p, key=p.get) for k, p in
                   sorted(dom_votes.items(), key=lambda kv: -sum(kv[1].values()))[:MAX_DOMAINS]}
        with self.lock:
            self.ips = ips
            self.domains = domains
            self.updated = int(time.time())
            self.version += 1

    def ip_app(self, ip: str) -> str | None:
        with self.lock:
            # 本地实测优先；本地没有结论的 IP 用社区共享层（debug16）
            hit = self.ips.get(ip)
            if hit:
                return hit
            p = _v6key(ip)
            if p:
                hit = self.ips.get(p)
                if hit:
                    return hit
                return self.community.get(p)
            return self.community.get(ip)

    def domain_app(self, qname: str | None) -> str | None:
        """域名学习（debug17）：精确匹配，本地实测优先、社区共享兜底；没有 qname 或没学过返回 None"""
        if not qname:
            return None
        name = qname.lower().rstrip(".")
        with self.lock:
            return self.domains.get(name) or self.community_domains.get(name)

    def load_community(self, community: dict[str, str], community_domains: dict[str, str] | None = None):
        """社区共享库（debug16/17）：其它部署实例的实测结论，只补本地没有的条目。调用方提交事务"""
        with self.lock:
            self.community = dict(community)
            self.community_domains = dict(community_domains or {})
            self.version += 1

    def reset(self):
        """测试用：清空内存记忆"""
        with self.lock:
            self.ips = {}
            self.domains = {}
            self.community = {}
            self.community_domains = {}
            self.version += 1


local = LocalDB()
