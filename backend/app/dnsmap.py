"""IP → 域名 映射表（从嗅探到的 DNS 响应建立）。

DNS TTL 往往只有几十秒，但连接会持续很久，所以保留时间取 max(TTL, MIN_KEEP)。
同一个 CDN IP 可能对应多个域名，这里保留最近一次的结果。
"""
import time
from collections import OrderedDict

MIN_KEEP = 6 * 3600
MAX_KEEP = 48 * 3600
MAX_ENTRIES = 300_000


class DnsMap:
    def __init__(self, max_entries: int = MAX_ENTRIES):
        self._d: OrderedDict[str, tuple[str, str | None, int]] = OrderedDict()
        self.max_entries = max_entries
        self.answers = 0
        self.dirty: dict[str, tuple[str, str | None, int]] = {}

    def add(self, qname: str, ips: list[tuple[str, int]], cnames: list[str], now: float | None = None):
        now = int(now or time.time())
        cname = cnames[-1] if cnames else None
        self.answers += 1
        for ip, ttl in ips:
            exp = now + min(max(ttl, MIN_KEEP), MAX_KEEP)
            val = (qname, cname, exp)
            self._d[ip] = val
            self._d.move_to_end(ip)
            self.dirty[ip] = val
        while len(self._d) > self.max_entries:
            self._d.popitem(last=False)

    def lookup(self, ip: str) -> tuple[str, str | None] | None:
        # 过期条目也照常返回（比没有强），由 purge 定期清理
        v = self._d.get(ip)
        return (v[0], v[1]) if v else None

    def load(self, rows):
        for ip, name, cname, exp in rows:
            self._d[ip] = (name, cname, exp)

    def purge(self, now: float | None = None) -> int:
        now = now or time.time()
        dead = [ip for ip, v in self._d.items() if v[2] < now]
        for ip in dead:
            del self._d[ip]
        return len(dead)

    def take_dirty(self) -> dict:
        d, self.dirty = self.dirty, {}
        return d

    def __len__(self):
        return len(self._d)
