"""通过 RouterOS REST API（只读，仅 GET）获取终端名称、IP↔MAC、LAN 前缀、WAN 口速率和系统状态。"""
import ipaddress
import time

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

    @property
    def enabled(self) -> bool:
        return bool(get_settings().ros_url)

    def _client(self) -> httpx.Client:
        s = get_settings()
        return httpx.Client(base_url=s.ros_url.rstrip("/") + "/rest", auth=(s.ros_user, s.ros_password),
                            verify=s.ros_verify_tls, timeout=10.0)

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
            self._apply(ifaces, arp, leases, addrs, routes, nb6, addrs6)
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
