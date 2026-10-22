"""流量处理核心：流记录 → 判断终端与方向 → 查域名 → 识别应用 → 内存累加 → 定时落库。"""
import ipaddress
import threading
import time
from collections import defaultdict

from sqlalchemy import delete, select

from app import timeutil
from app.classify import GENERIC_APPS, Classifier
from app.collector.ipfix import FlowDecoder
from app.collector.tzsp import parse_tzsp_dns
from app.config import get_settings
from app import database, hostnames
from app.database import upsert_add
from app.dnsmap import DnsMap
from app.models import (CustomRule, DnsCache, Host, HostDomainDay, Setting, TrafficDay, TrafficHour,
                        TrafficMinute)

_ZERO = {"0.0.0.0", "::"}


def parse_cidrs(text: str) -> list:
    nets = []
    for part in (text or "").replace("\n", ",").split(","):
        part = part.strip()
        if part:
            try:
                nets.append(ipaddress.ip_network(part, strict=False))
            except ValueError:
                pass
    return nets


class Engine:
    def __init__(self):
        s = get_settings()
        self.decoder = FlowDecoder()
        self.dns = DnsMap()
        self.classifier = Classifier()
        self.lock = threading.Lock()
        self.lan_cidrs_text = s.lan_cidrs
        self.lan_nets = parse_cidrs(s.lan_cidrs)
        self.auto_nets: list = []        # ros_poller 自动发现的 LAN 前缀（主要是 IPv6 公网前缀）
        self.ip2mac: dict[str, str] = {}  # ARP / IPv6 邻居 / DHCP
        self.mac2name: dict[str, str] = {}
        self._lan_cache: dict[str, bool] = {}

        self._buf: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0, 0])
        self._dom: dict[tuple[str, str, str], int] = defaultdict(int)
        self._seen: dict[str, tuple[str, str | None, int]] = {}  # host_key -> (ip, mac, ts)

        # 最近一个分钟窗口的统计，用于实时速率
        self.last_flush = time.time()
        self.host_rate: dict[str, tuple[float, float]] = {}
        self.app_rate: dict[str, tuple[float, float]] = {}
        self.total_rate = (0.0, 0.0)
        self.stats = {"flows": 0, "flows_dropped": 0, "dns_packets": 0, "dns_answers": 0,
                      "bytes_seen": 0, "last_flow": 0, "last_dns": 0, "exporters": {}}
        self.dns_servers: dict[str, list[int]] = {}  # 应答来源 DNS 服务器 -> [应答数, 最近时间]

    # ---------- 配置 ----------
    def set_lan(self, text: str):
        self.lan_cidrs_text = text
        self.lan_nets = parse_cidrs(text)
        self._lan_cache.clear()

    def set_auto_nets(self, nets: list):
        if set(map(str, nets)) != set(map(str, self.auto_nets)):
            self.auto_nets = nets
            self._lan_cache.clear()

    def reload_rules(self):
        with database.session() as db:
            rules = db.scalars(select(CustomRule)).all()
        self.classifier.load_custom(rules)

    def is_lan(self, ip: str | None) -> bool:
        if not ip or ip in _ZERO:
            return False
        hit = self._lan_cache.get(ip)
        if hit is not None:
            return hit
        try:
            a = ipaddress.ip_address(ip)
        except ValueError:
            return False
        if a.version == 6 and a.is_link_local:
            hit = True
        else:
            hit = any(a.version == n.version and a in n for n in self.lan_nets + self.auto_nets)
        if len(self._lan_cache) > 100_000:
            self._lan_cache.clear()
        self._lan_cache[ip] = hit
        return hit

    # ---------- 输入 ----------
    def on_ipfix(self, data: bytes, exporter: str):
        recs = self.decoder.decode(data, exporter)
        now = time.time()
        ex = self.stats["exporters"]
        ex[exporter] = int(now)
        with self.lock:
            for r in recs:
                self.add_flow(r, now)

    def on_tzsp(self, data: bytes):
        self.stats["dns_packets"] += 1
        ans = parse_tzsp_dns(data)
        if ans is None:
            return
        now = int(time.time())
        self.stats["dns_answers"] += 1
        self.stats["last_dns"] = now
        self.dns.add(ans.qname, ans.ips, ans.cnames)
        # 记录应答来自哪台 DNS 服务器，方便在系统设置里确认嗅探到的是哪一段（终端↔DNS 还是 DNS↔上游）
        srv = self.dns_servers.get(ans.server)
        if srv is None:
            if len(self.dns_servers) >= 64:
                del self.dns_servers[min(self.dns_servers, key=lambda k: self.dns_servers[k][1])]
            srv = self.dns_servers[ans.server] = [0, 0]
        srv[0] += 1
        srv[1] = now

    def host_key(self, ip: str, mac: str | None) -> tuple[str, str | None]:
        m = self.ip2mac.get(ip)
        if not m and mac:
            # 没配 ROS 轮询时，靠上行流里的源 MAC 学习 IP→MAC
            self.ip2mac[ip] = m = mac
        if m:
            return m, m
        return f"IP:{ip}", None

    def add_flow(self, r: dict, now: float):
        """调用方持有 self.lock。返回 (host_key, app, direction) 便于测试。"""
        src, dst = r.get("src"), r.get("dst")
        post_src, post_dst = r.get("post_src"), r.get("post_dst")
        proto = r.get("proto", 0)
        nbytes = r.get("bytes", 0)
        if not src or not dst or nbytes <= 0:
            self.stats["flows_dropped"] += 1
            return None
        src_lan, dst_lan = self.is_lan(src), self.is_lan(dst)
        mac = None
        if src_lan and not dst_lan:
            direction, host_ip, remote, rport = "up", src, dst, r.get("dport", 0)
            mac = r.get("src_mac")
        elif dst_lan and not src_lan:
            # 下行包在 WAN 口入方向采集，记录里的 MAC 是路由器自己的，不能用
            direction, host_ip, remote, rport = "down", dst, src, r.get("sport", 0)
        elif not src_lan and not dst_lan and self.is_lan(post_dst):
            # WAN 入方向、记录的是 DNAT 前地址：用 post-NAT 目的地址找终端
            direction, host_ip, remote, rport = "down", post_dst, src, r.get("sport", 0)
        else:
            # 内网互访，或路由器自身的流量
            self.stats["flows_dropped"] += 1
            return None

        names = self.dns.lookup(remote)
        qname, cname = names if names else (None, None)
        app = self.classifier.classify(remote, proto, rport, qname, cname)
        key, mac = self.host_key(host_ip, mac)

        b = self._buf[(key, app)]
        if direction == "up":
            b[0] += nbytes
        else:
            b[1] += nbytes
        b[2] += 1
        if qname:
            self._dom[(key, qname, app)] += nbytes
        self._seen[key] = (host_ip, mac, int(now))
        self.stats["flows"] += 1
        self.stats["bytes_seen"] += nbytes
        self.stats["last_flow"] = int(now)
        return key, app, direction

    # ---------- 落库 ----------
    def flush(self, now: float | None = None):
        if not database.is_configured():
            return  # 安装向导完成前先留在内存里，配置好后的第一次落库一起写入
        now = now or time.time()
        with self.lock:
            buf, self._buf = self._buf, defaultdict(lambda: [0, 0, 0])
            dom, self._dom = self._dom, defaultdict(int)
            seen, self._seen = self._seen, {}
        elapsed = max(now - self.last_flush, 1.0)
        self.last_flush = now

        hr, ar = defaultdict(lambda: [0, 0]), defaultdict(lambda: [0, 0])
        for (host, app), (up, down, _f) in buf.items():
            hr[host][0] += up
            hr[host][1] += down
            ar[app][0] += up
            ar[app][1] += down
        self.host_rate = {h: (u / elapsed, d / elapsed) for h, (u, d) in hr.items()}
        self.app_rate = {a: (u / elapsed, d / elapsed) for a, (u, d) in ar.items()}
        self.total_rate = (sum(v[0] for v in hr.values()) / elapsed, sum(v[1] for v in hr.values()) / elapsed)

        m, h, d = timeutil.minute_bucket(now), timeutil.hour_bucket(now), timeutil.day_bucket(now)
        rows = [{"host": host, "app": app, "up": up, "down": down, "flows": f}
                for (host, app), (up, down, f) in buf.items()]
        dirty_dns = self.dns.take_dirty()
        with database.session() as db:
            for table, ts in ((TrafficMinute.__table__, m), (TrafficHour.__table__, h), (TrafficDay.__table__, d)):
                for chunk in _chunks([{**r, "ts": ts} for r in rows], 500):
                    upsert_add(db, table, chunk, ["ts", "host", "app"], ["up", "down", "flows"])
            drows = [{"ts": d, "host": host, "domain": name[:255], "app": app, "bytes": n}
                     for (host, name, app), n in dom.items()]
            for chunk in _chunks(drows, 500):
                upsert_add(db, HostDomainDay.__table__, chunk, ["ts", "host", "domain"], ["bytes"], ["app"])
            self._save_hosts(db, seen)
            if dirty_dns:
                drs = [{"ip": ip, "name": v[0][:255], "cname": (v[1] or "")[:255] or None, "expires": v[2]}
                       for ip, v in dirty_dns.items()]
                for chunk in _chunks(drs, 500):
                    upsert_add(db, DnsCache.__table__, chunk, ["ip"], [], ["name", "cname", "expires"])
            db.commit()

    def _save_hosts(self, db, seen: dict):
        if not seen:
            return
        rows = []
        for key, (ip, mac, ts) in seen.items():
            rows.append({"key": key, "mac": mac, "ip": ip, "hostname": self.mac2name.get(mac) if mac else None,
                         "first_seen": ts, "last_seen": ts})
        # 已存在的终端只更新 ip / last_seen，first_seen 与备注名保持不变
        existing = {h.key: h for h in db.scalars(select(Host).where(Host.key.in_(list(seen))))}
        for r in rows:
            h = existing.get(r["key"])
            if h is None:
                db.add(Host(**r))
                continue
            h.ip, h.last_seen = r["ip"], r["last_seen"]
            h.first_seen = h.first_seen or r["first_seen"]
            h.mac = h.mac or r["mac"]
            if r["hostname"]:
                h.hostname = r["hostname"]

    def load_state(self):
        """启动时恢复 DNS 映射、自定义规则和界面设置。"""
        now = int(time.time())
        with database.session() as db:
            rows = db.execute(select(DnsCache.ip, DnsCache.name, DnsCache.cname, DnsCache.expires)
                              .where(DnsCache.expires > now)).all()
            lan = db.get(Setting, "lan_cidrs")
            hostnames.migrate_aliases(db)
        self.dns.load(rows)
        if lan and lan.value:
            self.set_lan(lan.value)
        self.reload_rules()

    def cleanup(self):
        if not database.is_configured():
            return
        s = get_settings()
        now = int(time.time())
        with database.session() as db:
            db.execute(delete(TrafficMinute).where(TrafficMinute.ts < now - s.retention_minute_days * 86400))
            db.execute(delete(TrafficHour).where(TrafficHour.ts < now - s.retention_hour_days * 86400))
            db.execute(delete(TrafficDay).where(TrafficDay.ts < now - s.retention_day_days * 86400))
            db.execute(delete(HostDomainDay).where(HostDomainDay.ts < now - s.retention_domain_days * 86400))
            db.execute(delete(DnsCache).where(DnsCache.expires < now))
            db.commit()
        self.dns.purge()

    def is_generic(self, app: str) -> bool:
        return app in GENERIC_APPS


def _chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i: i + n]


engine = Engine()
