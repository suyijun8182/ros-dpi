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


class ConnNames:
    """更精确的 域名 对应关系（只在内存里，重启后由新的握手 / DNS 查询重新建立）：

    - conn：(终端 IP, 终端端口, 远端 IP) → SNI，就是这条连接本身访问的域名，最准；
    - pair：(终端 IP, 远端 IP) → 这台终端最近一次对该 IP 解析 / 握手用的域名。

    同一个 CDN IP 往往同时服务很多网站，全网共用的 IP→域名 表只能记住最后一个；
    按连接 / 按终端记录可以避免张冠李戴。
    """

    CONN_KEEP = 6 * 3600
    PAIR_KEEP = 12 * 3600

    def __init__(self, max_conn: int = 200_000, max_pair: int = 300_000):
        self.conn: OrderedDict[tuple, tuple[str, str | None, int]] = OrderedDict()
        self.pair: OrderedDict[tuple, tuple[str, str | None, int]] = OrderedDict()
        self.max_conn, self.max_pair = max_conn, max_pair

    @staticmethod
    def _put(d: OrderedDict, key, val, cap: int):
        d[key] = val
        d.move_to_end(key)
        while len(d) > cap:
            d.popitem(last=False)

    def add_conn(self, client: str, cport: int, server: str, name: str, now: float | None = None):
        now = int(now or time.time())
        self._put(self.conn, (client, cport, server), (name, None, now), self.max_conn)
        self._put(self.pair, (client, server), (name, None, now), self.max_pair)

    def add_pair(self, client: str, server: str, name: str, cname: str | None, now: float | None = None):
        now = int(now or time.time())
        self._put(self.pair, (client, server), (name, cname, now), self.max_pair)

    def lookup(self, client: str, cport: int, server: str) -> tuple[str, str | None, str] | None:
        """返回 (域名, CNAME, 来源 conn|pair)"""
        v = self.conn.get((client, cport, server))
        if v:
            return v[0], v[1], "conn"
        v = self.pair.get((client, server))
        if v:
            return v[0], v[1], "pair"
        return None

    def purge(self, now: float | None = None):
        now = now or time.time()
        for d, keep in ((self.conn, self.CONN_KEEP), (self.pair, self.PAIR_KEEP)):
            # 按插入/更新顺序排列，从最旧的开始删
            while d and now - next(iter(d.values()))[2] > keep:
                d.popitem(last=False)
