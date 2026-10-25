"""本地自学习库（debug15）：把本网络实测的「IP → 应用」长期记忆接入分类管线。

host_domain_day（31 天）里以 IP 形式记录的行，当初是靠 DNS / SNI / ASN / 端口认出来的——这些证据
过后会消失（DNS 缓存过期、终端改用 DoH、SNI 只在连接开头出现），但"这个 IP 是什么应用"的结论是
实测来的，比任何公开库都准，因为它只属于你自己的网络。本模块把结论沉淀成 IP → 应用 的映射，
每小时从数据库重建一次、热加载：之后同一个 IP 就算完全拿不到域名，也能按记忆归类。

这是"自建本地库"的第一层（debug15）；它随每一次重算自动纠正，与识别库升级、历史重算形成闭环。
"""
import ipaddress
import threading
from collections import defaultdict

from sqlalchemy import select

from app.models import HostDomainDay

MAX_IPS = 200_000


class LocalDB:
    def __init__(self):
        self.lock = threading.Lock()
        self.version = 0
        self.ips: dict[str, str] = {}   # IP -> 应用 ID（按历史字节数取最多的应用）

    def load(self, db):
        """从 host_domain_day 聚合：每个 IP 取历史字节数最多的应用；调用方提交事务"""
        votes: dict = defaultdict(dict)
        rows = db.execute(
            select(HostDomainDay.domain, HostDomainDay.app, HostDomainDay.bytes)
        ).all()
        for dom, app, b in rows:
            try:
                ipaddress.ip_address(dom)
            except ValueError:
                continue
            per = votes[dom]
            per[app] = per.get(app, 0) + int(b or 0)
        # 只留最大的 MAX_IPS 个 IP（按总字节），避免极端环境下无限膨胀
        top = sorted(votes.items(), key=lambda kv: -sum(kv[1].values()))[:MAX_IPS]
        ips = {}
        for dom, per in top:
            ips[dom] = max(per, key=per.get)
        with self.lock:
            self.ips = ips
            self.version += 1

    def ip_app(self, ip: str) -> str | None:
        with self.lock:
            return self.ips.get(ip)

    def reset(self):
        """测试用：清空内存记忆"""
        with self.lock:
            self.ips = {}
            self.version += 1


local = LocalDB()
