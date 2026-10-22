"""外部数据源（可选）：旁路代理 sing-box 的 Clash API、内网 DNS MosDNS 的审计日志。

为什么需要：
- 终端走旁路代理时，代理回给终端的下载流量常常走二层直达、不经过路由器；路由器只看到代理自己连服务器的加密隧道，
  认不出任何应用。Clash API 的 /connections 直接给出每条连接的来源终端、域名和上下行字节，最准。
- 终端向内网 DNS（同一网段）查询不经过路由器，DNS 嗅探看不到；MosDNS 审计日志给出“哪台终端查了哪个域名、解析出哪些 IP”。

地址、密钥每个人都不一样：在网页 系统设置 → 外部数据源 里填写（存在数据库 settings 表），环境变量作为默认值。都不填就不启用。
"""
import ipaddress
import re
import time
from urllib.parse import urlparse

import httpx

from app.config import get_settings

KEYS = ("singbox_url", "singbox_secret", "proxy_ips", "mosdns_url")


def effective(db_values: dict) -> dict:
    """网页填写的值优先，其次环境变量"""
    s = get_settings()
    return {k: (db_values.get(k) if db_values.get(k) is not None else getattr(s, k)) or "" for k in KEYS}


def _err(e: Exception) -> str:
    if isinstance(e, httpx.HTTPStatusError):
        code = e.response.status_code
        if code == 401:
            return "认证失败（401）：检查密钥（Clash API 的 secret）"
        return f"HTTP {code}：{e.request.url.path}"
    if isinstance(e, httpx.ConnectError):
        return "连不上：检查地址和端口，以及对方是否允许本机访问"
    if isinstance(e, httpx.TimeoutException):
        return "连接超时"
    return f"{type(e).__name__}: {str(e)[:160]}"


class SingboxPoller:
    """每隔几秒读一次 /connections，按连接 id 计算新增字节，交给引擎按“终端 + 域名”记账"""

    def __init__(self, engine):
        self.engine = engine
        self.url = ""
        self.secret = ""
        self.ok = False
        self.error = ""
        self.last = 0
        self.conns = 0
        self.bytes = 0
        self.version = ""
        self._prev: dict[str, tuple[int, int]] = {}

    @property
    def enabled(self) -> bool:
        return bool(self.url)

    @staticmethod
    def route_info(c: dict) -> tuple[str, str, str, list[str]]:
        """(出口节点, 策略组, 规则, 可用来认应用的名字)。chains 是 [节点, …, 策略组]；
        rule 形如 "rule_set=Telegram0 => route(✈️ Telegram)"、"rule_set=[A0 B0] => route(X)"、final"""
        chains = [x for x in (c.get("chains") or []) if x]
        node, group = (chains[0], chains[-1]) if chains else ("", "")
        rule = (c.get("rule") or "").strip()
        names = []
        m = re.match(r"^\s*rule_set=\[?([^\]=]*?)\]?\s*=>", rule)
        if m:
            names += m.group(1).split()
        names += chains[1:]
        return node, group, rule[:120], names

    def configure(self, url: str, secret: str):
        url = (url or "").strip().rstrip("/")
        if url != self.url or secret != self.secret:
            self._prev = {}
            self.ok, self.error, self.version = False, "", ""
        self.url, self.secret = url, secret or ""

    def host_ip(self) -> str | None:
        try:
            h = urlparse(self.url).hostname
            ipaddress.ip_address(h)
            return h
        except (ValueError, TypeError):
            return None

    def _get(self, path: str):
        headers = {"Authorization": f"Bearer {self.secret}"} if self.secret else {}
        r = httpx.get(self.url + path, headers=headers, timeout=8.0)
        r.raise_for_status()
        return r.json()

    def poll(self):
        if not self.enabled:
            return
        try:
            data = self._get("/connections")
            if not self.version:
                try:
                    self.version = (self._get("/version") or {}).get("version", "")
                except Exception:  # noqa: BLE001
                    pass
        except Exception as e:  # noqa: BLE001
            self.ok, self.error = False, _err(e)
            self.last = int(time.time())
            return
        now = time.time()
        seen = {}
        for c in data.get("connections") or []:
            cid = c.get("id")
            up, down = int(c.get("upload") or 0), int(c.get("download") or 0)
            seen[cid] = (up, down)
            pu, pd = self._prev.get(cid, (0, 0))
            du, dd = max(up - pu, 0), max(down - pd, 0)
            if du or dd:
                m = c.get("metadata") or {}
                self.engine.add_proxy_conn(
                    src=m.get("sourceIP") or "", sport=int(m.get("sourcePort") or 0),
                    host=(m.get("host") or m.get("sniffHost") or "").strip().lower().rstrip("."),
                    dst=m.get("destinationIP") or "", dport=int(m.get("destinationPort") or 0),
                    network=m.get("network") or "tcp", up=du, down=dd, route=self.route_info(c), new=cid not in self._prev,
                    now=now)
                self.bytes += du + dd
        self._prev = seen
        self.conns = len(seen)
        self.ok, self.error, self.last = True, "", int(now)

    def status(self) -> dict:
        return {"enabled": self.enabled, "url": self.url, "has_secret": bool(self.secret), "ok": self.ok,
                "error": self.error, "last": self.last, "conns": self.conns, "bytes": self.bytes,
                "version": self.version, "proxy_ip": self.host_ip()}


class MosdnsPoller:
    """读 MosDNS 审计日志（最新的在前），把新出现的应答交给引擎：终端 + IP → 域名"""

    PAGE = 500

    def __init__(self, engine):
        self.engine = engine
        self.url = ""
        self.ok = False
        self.error = ""
        self.last = 0
        self.answers = 0
        self._mark: tuple[str, str] | None = None  # 上次处理到的 (query_time, trace_id)

    @property
    def enabled(self) -> bool:
        return bool(self.url)

    def configure(self, url: str):
        url = (url or "").strip().rstrip("/")
        if url != self.url:
            self._mark = None
            self.ok, self.error = False, ""
        self.url = url

    def poll(self):
        if not self.enabled:
            return
        try:
            r = httpx.get(f"{self.url}/api/v2/audit/logs", params={"limit": self.PAGE, "page": 1}, timeout=8.0)
            r.raise_for_status()
            logs = (r.json() or {}).get("logs") or []
        except Exception as e:  # noqa: BLE001
            self.ok, self.error = False, _err(e)
            self.last = int(time.time())
            return
        new = []
        for x in logs:  # 最新的在前，遇到上次处理过的就停
            mark = (x.get("query_time") or "", str(x.get("trace_id") or ""))
            if self._mark and mark <= self._mark:
                break
            new.append(x)
        if logs:
            self._mark = max((x.get("query_time") or "", str(x.get("trace_id") or "")) for x in logs)
        for x in reversed(new):
            ips, cnames = [], []
            for a in x.get("answers") or []:
                t, d = a.get("type"), (a.get("data") or "").strip()
                if t in ("A", "AAAA") and d:
                    ips.append((d, int(a.get("ttl") or 0)))
                elif t == "CNAME" and d:
                    cnames.append(d.lower().rstrip("."))
            name = (x.get("query_name") or "").lower().rstrip(".")
            if ips and name:
                self.engine.add_dns_answer(x.get("client_ip") or "", name, ips, cnames, source="mosdns")
                self.answers += 1
        self.ok, self.error, self.last = True, "", int(time.time())

    def status(self) -> dict:
        return {"enabled": self.enabled, "url": self.url, "ok": self.ok, "error": self.error,
                "last": self.last, "answers": self.answers}


def _make():
    from app.engine import engine
    return SingboxPoller(engine), MosdnsPoller(engine)


singbox, mosdns = _make()


def apply(db_values: dict):
    """按网页 / 环境变量的配置更新两个轮询器和引擎里的旁路代理地址"""
    cfg = effective(db_values)
    singbox.configure(cfg["singbox_url"], cfg["singbox_secret"])
    mosdns.configure(cfg["mosdns_url"])
    ips = {x.strip() for x in cfg["proxy_ips"].replace("\n", ",").split(",") if x.strip()}
    if not ips and singbox.host_ip():
        ips.add(singbox.host_ip())
    singbox.engine.set_proxy(ips, singbox.enabled)
    return cfg
