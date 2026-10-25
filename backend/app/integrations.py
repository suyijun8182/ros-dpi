"""外部数据源（可选）：旁路代理 sing-box 的 Clash API、内网 DNS MosDNS 的审计日志、自有 DNS 服务器 AdGuard Home 的查询日志。

为什么需要：
- 终端走旁路代理时，代理回给终端的下载流量常常走二层直达、不经过路由器；路由器只看到代理自己连服务器的加密隧道，
  认不出任何应用。Clash API 的 /connections 直接给出每条连接的来源终端、域名和上下行字节，最准。
- 终端向内网 DNS（同一网段）查询不经过路由器，DNS 嗅探看不到；MosDNS 审计日志给出“哪台终端查了哪个域名、解析出哪些 IP”。
- 双层 NAT（如爱快在路由器下面又挂一层内网）时，下级客户端的 DNS 被爱快代理，路由器侧更看不到；
  它们真正的 DNS 服务器（如爱快下游的 AdGuard Home）的查询日志就是域名的来源。

地址、密钥每个人都不一样：在网页 系统设置 → 外部数据源 里填写（存在数据库 settings 表），环境变量作为默认值。都不填就不启用。
"""
import ipaddress
import re
import time
from urllib.parse import urlparse

import httpx

from app.config import get_settings

KEYS = ("singbox_url", "singbox_secret", "proxy_ips", "mosdns_url", "adguard_url", "adguard_username",
        "adguard_password")


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


class AdguardPoller:
    """读 AdGuard Home 的查询日志（最新的在前），把新出现的应答交给引擎：终端 + IP → 域名。

    用于双层 NAT（如爱快下游）：路由器看不到下级客户端的 DNS 查询，但它们的查询都记录在
    下游自己的 DNS 服务器上。应答会进引擎的全网 IP→域名表（add_dns_answer），与客户端在哪层 NAT 无关。
    """

    PAGE = 500
    # 查询日志 answer 字段的资源记录行：「域名. TTL IN A|AAAA|CNAME 值」
    _RR = re.compile(r"(\S+)\s+(\d+)\s+IN\s+(A|AAAA|CNAME)\s+(\S+)", re.IGNORECASE)

    def __init__(self, engine):
        self.engine = engine
        self.url = ""
        self.username = ""
        self.password = ""
        self.ok = False
        self.error = ""
        self.last = 0
        self.answers = 0
        self._mark: tuple[str, str, str] | None = None  # 上次处理到的 (time, domain, client)
        self._client: httpx.Client | None = None

    @property
    def enabled(self) -> bool:
        return bool(self.url)

    def configure(self, url: str, username: str, password: str):
        url = (url or "").strip().rstrip("/")
        username, password = (username or "").strip(), password or ""
        if (url, username, password) != (self.url, self.username, self.password):
            self._mark = None
            self._close_client()
            self.ok, self.error = False, ""
        self.url, self.username, self.password = url, username, password

    def _close_client(self):
        if self._client is not None:
            try:
                self._client.close()
            except Exception:  # noqa: BLE001
                pass
        self._client = None

    def _connect(self):
        """登录拿会话；没配账号密码时跳过登录（AdGuard 只在内网监听时可以免认证）"""
        self._close_client()
        c = httpx.Client(base_url=self.url, timeout=10.0)
        if self.username or self.password:
            r = c.post("/control/login", json={"name": self.username, "password": self.password})
            r.raise_for_status()
        self._client = c

    def _fetch(self) -> list:
        if self._client is None:
            self._connect()
        r = self._client.get("/control/querylog", params={"limit": self.PAGE, "response_status": "all"})
        if r.status_code in (401, 403):  # 会话过期：重登一次再取
            self._connect()
            r = self._client.get("/control/querylog", params={"limit": self.PAGE, "response_status": "all"})
        r.raise_for_status()
        return self._entries(r.json())

    @staticmethod
    def _entries(data) -> list:
        # 新版本返回 {"data": [...]}，旧版本 {"entries": [...]} 或直接数组
        if isinstance(data, dict):
            return data.get("data") or data.get("entries") or []
        return data or []

    def poll(self):
        if not self.enabled:
            return
        try:
            entries = self._fetch()
        except Exception as e:  # noqa: BLE001
            self._close_client()
            self.ok, self.error, self.last = False, _err(e), int(time.time())
            return
        new = []
        for x in entries:  # 最新的在前，遇到上次处理过的就停
            mark = (str(x.get("time") or ""), str(x.get("domain") or ""), str(x.get("client") or ""))
            if self._mark and mark <= self._mark:
                break
            new.append(x)
        if entries:
            self._mark = max((str(x.get("time") or ""), str(x.get("domain") or ""), str(x.get("client") or ""))
                             for x in entries)
        for x in reversed(new):
            parsed = self._parse_entry(x)
            if parsed:
                name, ips, cnames, client = parsed
                self.engine.add_dns_answer(client, name, ips, cnames, source="adguard")
                self.answers += 1
        self.ok, self.error, self.last = True, "", int(time.time())

    @classmethod
    def _parse_entry(cls, x: dict):
        """返回 (域名, [(IP, TTL)...], [CNAME...], 客户端IP)；没有 A/AAAA 应答（被拦截、NXDOMAIN）时返回 None"""
        name = (x.get("domain") or (x.get("question") or {}).get("name") or "").strip().lower().rstrip(".")
        client = (x.get("client_ip") or x.get("client") or "").strip()
        answer = x.get("answer")
        ips, cnames = [], []
        if isinstance(answer, (list, tuple)):
            for v in answer:
                if isinstance(v, dict):
                    typ = str(v.get("type") or "").upper()
                    val = str(v.get("value") or "").strip().rstrip(".")
                    ttl = int(v.get("ttl") or 0)
                    if typ == "CNAME" and val:
                        cnames.append(val.lower())
                    elif typ in ("A", "AAAA") and val:
                        try:
                            ipaddress.ip_address(val)
                        except ValueError:
                            continue
                        ips.append((val, ttl))
                else:
                    cls._parse_rr(str(v), ips, cnames)
        else:
            if isinstance(answer, dict):
                answer = "\n".join(str(v) for v in answer.values())
            cls._parse_rr(str(answer or ""), ips, cnames)
        if not ips or not name or not client:
            return None
        return name, ips, cnames, client

    @classmethod
    def _parse_rr(cls, text: str, ips: list, cnames: list):
        for line in text.splitlines():
            m = cls._RR.search(line)
            if not m:
                continue
            typ, val = m.group(3).upper(), m.group(4).rstrip(".")
            ttl = int(m.group(2) or 0)
            if typ == "CNAME":
                cnames.append(val.lower())
            elif typ in ("A", "AAAA"):
                try:
                    ipaddress.ip_address(val)
                except ValueError:
                    continue
                ips.append((val, ttl))

    def status(self) -> dict:
        return {"enabled": self.enabled, "url": self.url, "ok": self.ok, "error": self.error,
                "last": self.last, "answers": self.answers}


def _make():
    from app.engine import engine
    return SingboxPoller(engine), MosdnsPoller(engine), AdguardPoller(engine)


singbox, mosdns, adguard = _make()


def apply(db_values: dict):
    """按网页 / 环境变量的配置更新三个轮询器和引擎里的旁路代理地址"""
    cfg = effective(db_values)
    singbox.configure(cfg["singbox_url"], cfg["singbox_secret"])
    mosdns.configure(cfg["mosdns_url"])
    adguard.configure(cfg["adguard_url"], cfg["adguard_username"], cfg["adguard_password"])
    ips = {x.strip() for x in cfg["proxy_ips"].replace("\n", ",").split(",") if x.strip()}
    if not ips and singbox.host_ip():
        ips.add(singbox.host_ip())
    singbox.engine.set_proxy(ips, singbox.enabled)
    return cfg
