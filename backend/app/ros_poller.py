"""通过 RouterOS REST API（只读，仅 GET）获取终端名称、IP↔MAC、LAN 前缀、接口速率、WAN 线路、DHCP 地址池和系统状态。"""
import ipaddress
import time
from collections import deque

import httpx

from app.config import get_settings


class RosPoller:
    def __init__(self, engine):
        self.engine = engine
        self.ok = False
        self.error = ""
        self.last_poll = 0
        self.identity = ""
        self.resource: dict = {}
        self.interfaces: list[dict] = []
        self.wan_name = ""
        self.wan_rate = (0.0, 0.0)  # (上行 tx, 下行 rx) 字节/秒
        self._wan_prev: tuple[float, int, int] | None = None
        self.wan_override = ""
        self.leases: dict[str, dict] = {}  # mac -> lease
        self.lease_list: list[dict] = []
        self.if_rate: dict[str, tuple[float, float]] = {}  # 接口 -> (tx, rx) 字节/秒
        self._if_prev: dict[str, tuple[float, int, int]] = {}
        self.wans: list[dict] = []
        self.pools: list[dict] = []
        # 实时流量：WAN 口计数器采样（ts, 上行 B/s, 下行 B/s），保留最近 1 小时
        self.samples: deque = deque(maxlen=1440)
        self.mangle: list[dict] = []        # 接入自检用：RouterOS 的 mangle 规则（只读）
        self.ip_settings: dict = {}
        self._sample_prev: dict[str, tuple[float, int, int]] = {}

    @property
    def enabled(self) -> bool:
        return bool(get_settings().ros_url)

    def _client(self) -> httpx.Client:
        s = get_settings()
        return httpx.Client(base_url=s.ros_url.rstrip("/") + "/rest", auth=(s.ros_user, s.ros_password),
                            verify=s.ros_verify_tls, timeout=10.0)

    @classmethod
    def _opt(cls, c: httpx.Client, path: str):
        """可选数据：对应功能包没装（404）或权限不够时返回空列表，不影响其他数据"""
        try:
            return cls._get(c, path)
        except httpx.HTTPStatusError as e:
            if e.response.status_code in (400, 403, 404, 500):
                return []
            raise

    @staticmethod
    def _get(c: httpx.Client, path: str):
        # 注意：httpx 的 raise_for_status() 成功时返回响应对象本身，不能写成 `raise_for_status() or r.json()`
        r = c.get(path)
        r.raise_for_status()
        return r.json()

    def poll(self):
        if not self.enabled:
            return
        try:
            with self._client() as c:
                ident = self._get(c, "/system/identity")
                resource = self._get(c, "/system/resource")
                ifaces = self._get(c, "/interface")
                arp = self._get(c, "/ip/arp")
                leases = self._get(c, "/ip/dhcp-server/lease")
                addrs = self._get(c, "/ip/address")
                routes = self._get(c, "/ip/route?dst-address=0.0.0.0/0")
                try:
                    nb6 = self._get(c, "/ipv6/neighbor")
                    addrs6 = self._get(c, "/ipv6/address")
                except httpx.HTTPError:
                    nb6, addrs6 = [], []  # IPv6 包未启用
                extra = {k: self._opt(c, path) for k, path in (
                    ("pools", "/ip/pool"), ("servers", "/ip/dhcp-server"), ("dhcpc", "/ip/dhcp-client"),
                    ("pppoe", "/interface/pppoe-client"), ("mangle", "/ip/firewall/mangle"),
                    ("mangle6", "/ipv6/firewall/mangle"), ("ipset", "/ip/settings"))}
            self._apply(ifaces, arp, leases, addrs, routes, nb6, addrs6)
            self._apply_status(ifaces, addrs, leases, routes, extra)
            self.mangle = [{**r, "_family": "ipv4"} for r in extra["mangle"] or []] + \
                [{**r, "_family": "ipv6"} for r in extra["mangle6"] or []]
            self.ip_settings = extra["ipset"] if isinstance(extra["ipset"], dict) else {}
            # 全部成功后再更新展示用的状态，失败时保留上一次的结果
            self.identity = ident.get("name", "") if isinstance(ident, dict) else ""
            self.resource = resource if isinstance(resource, dict) else {}
            self.ok, self.error = True, ""
        except Exception as e:  # noqa: BLE001
            self.ok, self.error = False, _explain(e)
            print(f"[ros] 轮询失败：{self.error}", flush=True)
        self.last_poll = int(time.time())

    def _apply(self, ifaces, arp, leases, addrs, routes, nb6, addrs6):
        now = time.time()
        self.interfaces = [
            {"name": i.get("name"), "type": i.get("type"), "running": i.get("running") == "true",
             "rx": int(i.get("rx-byte", 0) or 0), "tx": int(i.get("tx-byte", 0) or 0)}
            for i in ifaces
        ]
        self.wan_name = self.wan_override or get_settings().wan_interface or _default_route_iface(routes)
        wan = next((i for i in self.interfaces if i["name"] == self.wan_name), None)
        if wan:
            if self._wan_prev and self._wan_prev[0] < now:
                dt = now - self._wan_prev[0]
                self.wan_rate = (max(wan["tx"] - self._wan_prev[2], 0) / dt,
                                 max(wan["rx"] - self._wan_prev[1], 0) / dt)
            self._wan_prev = (now, wan["rx"], wan["tx"])

        ip2mac: dict[str, str] = {}
        for a in arp:
            if a.get("mac-address") and a.get("address"):
                ip2mac[a["address"]] = a["mac-address"].upper()
        for n in nb6:
            if n.get("mac-address") and n.get("address"):
                ip2mac[n["address"]] = n["mac-address"].upper()
        names: dict[str, str] = {}
        self.leases = {}
        for le in leases:
            mac = (le.get("mac-address") or le.get("active-mac-address") or "").upper()
            if not mac:
                continue
            ip = le.get("active-address") or le.get("address")
            if ip and "/" not in ip:
                ip2mac.setdefault(ip, mac)
            name = le.get("comment") or le.get("host-name") or le.get("active-host-name")
            if name:
                names[mac] = name
            self.leases[mac] = le
        self.engine.ip2mac.update(ip2mac)
        self.engine.mac2name.update(names)

        # 非 WAN 接口上的地址段视为 LAN（自动补充 IPv6 公网前缀等）
        # 认不出 WAN 口时不自动发现，免得把 WAN 地址段当成 LAN
        nets = []
        for a in (list(addrs) + list(addrs6)) if self.wan_name else []:
            if a.get("interface") == self.wan_name or a.get("disabled") == "true":
                continue
            try:
                net = ipaddress.ip_interface(a.get("address", "")).network
            except ValueError:
                continue
            if net.is_link_local or net.is_loopback or net.prefixlen == net.max_prefixlen:
                continue
            nets.append(net)
        self.engine.set_auto_nets(nets)

    def _apply_status(self, ifaces, addrs, leases, routes, extra):
        """接口速率、WAN 线路、DHCP 地址池（概览页的全网状态、DHCP 分配、健康指数用）"""
        now = time.time()
        for i in ifaces:
            name = i.get("name")
            rx, tx = int(i.get("rx-byte", 0) or 0), int(i.get("tx-byte", 0) or 0)
            prev = self._if_prev.get(name)
            if prev and prev[0] < now:
                dt = now - prev[0]
                self.if_rate[name] = (max(tx - prev[2], 0) / dt, max(rx - prev[1], 0) / dt)
            self._if_prev[name] = (now, rx, tx)

        # WAN 线路：所有默认路由的出接口（多 WAN 时有多条），没有时用识别到的 WAN 口
        names = []
        for r in routes or []:
            n = _default_route_iface([r])
            if n and n not in names:
                names.append(n)
        if self.wan_name and self.wan_name not in names:
            names.insert(0, self.wan_name)
        by_name = {i.get("name"): i for i in ifaces}
        pppoe = {p.get("name"): p for p in extra["pppoe"] or []}
        dhcpc = {d.get("interface"): d for d in extra["dhcpc"] or []}
        wans = []
        for n in names:
            i = by_name.get(n, {})
            kind = "pppoe" if n in pppoe or i.get("type") == "pppoe-out" else "dhcp" if n in dhcpc else "static"
            ip = next((a.get("address", "").split("/")[0] for a in addrs if a.get("interface") == n
                       and a.get("disabled") != "true"), "")
            rate = self.if_rate.get(n, (0.0, 0.0))
            wans.append({"name": n, "type": kind, "running": i.get("running") == "true", "ip": ip,
                         "since": i.get("last-link-up-time") or "", "comment": i.get("comment") or "",
                         "rate_up": rate[0], "rate_down": rate[1],
                         "dhcp_status": (dhcpc.get(n) or {}).get("status")})
        self.wans = wans

        # DHCP 地址池：容量来自 /ip/pool 的地址范围，已用 = 该 DHCP 服务器的租约数
        pool_size = {p.get("name"): _pool_size(p.get("ranges", "")) for p in extra["pools"] or []}
        used: dict[str, int] = {}
        for le in leases:
            if le.get("disabled") == "true":
                continue
            used[le.get("server") or ""] = used.get(le.get("server") or "", 0) + 1
        servers = [sv for sv in extra["servers"] or [] if sv.get("disabled") != "true"]
        if len(servers) == 1 and "" in used:  # 租约没带 server 字段时，只有一个 DHCP 服务器就算它的
            used[servers[0].get("name")] = used.get(servers[0].get("name"), 0) + used.pop("")
        self.pools = [{"server": sv.get("name"), "interface": sv.get("interface"), "pool": sv.get("address-pool"),
                       "size": pool_size.get(sv.get("address-pool"), 0), "used": used.get(sv.get("name"), 0)}
                      for sv in servers]
        self.lease_list = [{
            "address": le.get("active-address") or le.get("address"), "mac": (le.get("mac-address") or "").upper(),
            "host_name": le.get("host-name") or le.get("active-host-name") or "", "comment": le.get("comment") or "",
            "server": le.get("server") or "", "status": le.get("status") or "",
            "dynamic": le.get("dynamic") == "true", "expires_after": le.get("expires-after") or "",
            "last_seen": le.get("last-seen") or "",
        } for le in leases]

    def sample(self):
        """只读一次接口计数，算出所有 WAN 线路的合计速率（比 poll 轻得多，可以几秒一次）"""
        names = [w["name"] for w in self.wans] or ([self.wan_name] if self.wan_name else [])
        if not self.enabled or not names:
            return
        try:
            with self._client() as c:
                ifaces = self._get(c, "/interface?.proplist=name,rx-byte,tx-byte")
        except Exception:  # noqa: BLE001  采样失败不影响主轮询，下次再试
            return
        now = time.time()
        up = down = 0.0
        got = False
        for i in ifaces:
            n = i.get("name")
            if n not in names:
                continue
            rx, tx = int(i.get("rx-byte", 0) or 0), int(i.get("tx-byte", 0) or 0)
            prev = self._sample_prev.get(n)
            self._sample_prev[n] = (now, rx, tx)
            if prev and now > prev[0]:
                dt = now - prev[0]
                up += max(tx - prev[2], 0) / dt
                down += max(rx - prev[1], 0) / dt
                got = True
        if got:
            self.samples.append((int(now), up, down))
            self.wan_rate = (up, down)

    def check(self) -> dict:
        """接入自检：检查 RouterOS 上镜像到 ROS-DPI 的 sniff-tzsp 规则（目标端口、是否停用、有没有命中）。

        返回 {checked, rules: [...], issues: [code...]}。没配 ROS API 时 checked=False。
        """
        if not self.enabled or not self.ok:
            return {"checked": False, "rules": [], "issues": []}
        sniff = [r for r in self.mangle if r.get("action") == "sniff-tzsp"]
        kind_of = lambda r: "dns" if r.get("src-port") == "53" else "sni" if "443" in (r.get("dst-port") or "") else "other"
        # 参照：ROS-DPI 已经收到 DNS 应答时，DNS 规则的目标地址和端口就是对的（端口映射可能不是 37008:37008）；
        # 否则退回和本机监听端口比较
        dns_ok = self.engine.stats.get("dns_answers", 0) > 0
        ref = next(((r.get("sniff-target"), int(r.get("sniff-target-port") or 37008)) for r in sniff
                    if kind_of(r) == "dns" and r.get("disabled") != "true"), None) if dns_ok else None
        port = ref[1] if ref else get_settings().tzsp_port
        rules, issues = [], []
        for r in sniff:
            kind = kind_of(r)
            probs = []
            if r.get("disabled") == "true":
                probs.append("disabled")
            tport = int(r.get("sniff-target-port") or 37008)
            if tport != port:
                probs.append("port")
            if ref and r.get("sniff-target") and r.get("sniff-target") != ref[0] and r["_family"] == "ipv4":
                probs.append("target")
            rules.append({"id": r.get(".id"), "family": r["_family"], "chain": r.get("chain"), "kind": kind,
                          "protocol": r.get("protocol") or "", "comment": r.get("comment") or "",
                          "target": r.get("sniff-target") or "", "target_port": tport,
                          "packets": int(r.get("packets") or 0), "disabled": r.get("disabled") == "true", "problems": probs})
        # 规则存在但有问题（端口 / 地址 / 停用）时，按规则逐条给修改命令；只有完全没有某类规则时才建议新增
        if any(x["problems"] for x in rules):
            issues.append("rule_problem")
        if not any(x["kind"] == "dns" for x in rules):
            issues.append("no_dns")
        if not any(x["kind"] == "sni" for x in rules):
            issues.append("no_sni")
        elif not any(x["kind"] == "sni" and x["protocol"] == "udp" for x in rules):
            issues.append("no_quic")
        if self.ip_settings.get("ipv4-fasttrack-active") == "true":
            issues.append("fasttrack")
        return {"checked": True, "port": port, "target": ref[0] if ref else None, "rules": rules, "issues": issues,
                "fasttrack": self.ip_settings.get("ipv4-fasttrack-active") == "true"}

    def status(self) -> dict:
        r = self.resource if isinstance(self.resource, dict) else {}
        return {
            "enabled": self.enabled, "ok": self.ok, "error": self.error, "last_poll": self.last_poll,
            "identity": self.identity, "version": r.get("version"), "board": r.get("board-name"),
            "uptime": r.get("uptime"), "cpu_load": _int(r.get("cpu-load")),
            "mem_total": _int(r.get("total-memory")), "mem_free": _int(r.get("free-memory")),
            "wan_interface": self.wan_name,
        }


def _explain(e: Exception) -> str:
    """常见错误翻译成可操作的提示。"""
    if isinstance(e, httpx.HTTPStatusError):
        code = e.response.status_code
        if code == 401:
            return "RouterOS 拒绝登录（401）：检查 ROS_USER / ROS_PASSWORD，以及该用户的 address 是否允许本机 IP"
        if code == 403:
            return "RouterOS 权限不足（403）：用户组需要 read、rest-api 权限"
        return f"RouterOS 返回 HTTP {code}：{e.request.url.path}"
    if isinstance(e, httpx.ConnectError):
        return f"连不上 RouterOS：检查 ROS_URL，并确认 /ip service 中 www-ssl（或 www）已启用（{e}）"
    if isinstance(e, httpx.TimeoutException):
        return "连接 RouterOS 超时：检查 ROS_URL 与防火墙"
    return f"{type(e).__name__}: {str(e)[:200]}"


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _pool_size(ranges: str) -> int:
    """"192.168.88.10-192.168.88.254,10.0.0.0/24" → 地址数"""
    n = 0
    for part in (ranges or "").split(","):
        part = part.strip()
        try:
            if "-" in part:
                a, b = (ipaddress.ip_address(x.strip()) for x in part.split("-", 1))
                n += int(b) - int(a) + 1
            elif "/" in part:
                n += ipaddress.ip_network(part, strict=False).num_addresses
            elif part:
                ipaddress.ip_address(part)
                n += 1
        except ValueError:
            continue
    return n


def _default_route_iface(routes) -> str:
    """默认路由的出接口：immediate-gw 形如 "10.0.0.1%ether1"，PPPoE 时 gateway 直接是接口名。"""
    for r in routes or []:
        if r.get("active") not in ("true", True) and len(routes) > 1:
            continue
        gw = r.get("immediate-gw") or r.get("gateway") or ""
        if "%" in gw:
            return gw.split("%", 1)[1]
        if gw and not gw[0].isdigit():
            return gw
    return ""


def _make():
    from app.engine import engine
    return RosPoller(engine)


poller = _make()
