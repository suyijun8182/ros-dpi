"""管控命令生成（参照深信服 AC 的应用控制 / 时间控制 / 流量控制，但 ROS-DPI 不写路由器）。

根据人员 / 设备、应用、时段生成 RouterOS 7 命令，用户复制到终端执行；每次生成一个标签，附带撤销命令。
- block_app：按 TLS 域名（tls-host）拒绝 HTTPS；QUIC（udp/443）看不到域名，可选整体禁止该设备的 QUIC 让应用回落到 TCP。
- block_all：断网（定时断网就是加上时段）。
- limit：简单队列限速（需要设备的 IPv4 地址；开了 FastTrack 的连接不经过简单队列）。
"""
import re
import time
from collections import defaultdict

from sqlalchemy import func, select

DAYS = {"1": "mon", "2": "tue", "3": "wed", "4": "thu", "5": "fri", "6": "sat", "7": "sun"}
MAX_DOMAINS = 40


_CTRL = re.compile(r"[\x00-\x1f\x7f]")
_DOMAIN = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$")
_MAC = re.compile(r"^[0-9A-F]{2}(:[0-9A-F]{2}){5}$")


def _q(s: str) -> str:
    """RouterOS 双引号字符串：设备名（DHCP 主机名，任何设备都能随便设）会进到这里，管理员粘贴执行时
    "$[...]" 会被 RouterOS 当命令执行、换行会另起一条命令——所以去掉控制字符，并转义反斜杠、双引号和 $"""
    s = _CTRL.sub("", str(s))
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$") + '"'


def _time_parts(days: str, t_from: str, t_to: str) -> list[str]:
    """RouterOS 防火墙 time= 参数；跨午夜拆成两段"""
    if (t_from, t_to) in (("00:00", "24:00"), ("00:00", "00:00")) and len(days) == 7:
        return [""]
    d = ",".join(DAYS[x] for x in sorted(set(days)) if x in DAYS)

    def hm(x):
        return "1d" if x == "24:00" else f"{int(x[:2])}h{int(x[3:]):02d}m"
    if t_to == "00:00":
        t_to = "24:00"
    if t_from < t_to:
        return [f"{hm(t_from)}-{hm(t_to)},{d}"]
    return [f"{hm(t_from)}-1d,{d}", f"0s-{hm(t_to)},{d}"]


def app_domains(db, apps: list[str], groups: list[str]) -> list[str]:
    """要封禁的域名：识别库里这些应用的域名，加上你的网络里最近 30 天实际出现过的（按流量排前面）"""
    from app import stats, timeutil
    from app.engine import engine
    from app.models import HostDomainDay
    cl = engine.classifier
    want = set(apps)
    for a in cl.apps.values():
        c = cl.category_info(a.category)
        if a.category in groups or c["group"] in groups:
            want.add(a.id)
    seen: dict[str, int] = defaultdict(int)
    start = timeutil.range_bounds("last30")[0]
    t = HostDomainDay
    for dom, b in db.execute(select(t.domain, func.sum(t.bytes)).where(t.ts >= start, t.app.in_(list(want) or ["-"]))
                             .group_by(t.domain)):
        if not stats.is_ip(dom):
            seen[stats.base_domain(dom)] += int(b)
    lib = [d for d, a in list(cl.domains.items()) + list(cl.full.items()) if a in want]
    # 域名来自 DNS 嗅探（内网设备可以伪造应答），不加引号拼进 tls-host=，只收规范的主机名
    seen = {d: b for d, b in seen.items() if len(d) <= 253 and _DOMAIN.match(d)}
    out = sorted(seen, key=lambda d: -seen[d])
    for d in sorted(lib, key=len):
        if len(out) >= MAX_DOMAINS:
            break
        if d not in out and not any(d.endswith("." + x) for x in out):
            out.append(d)
    return out[:MAX_DOMAINS]


def build(db, targets: list[dict], action: str, apps: list[str], groups: list[str], days: str, t_from: str, t_to: str,
          block_quic: bool = True, up_mbps: float = 0, down_mbps: float = 0, label: str = "") -> dict:
    tag = "ROSDPI-CTRL " + time.strftime("%m%d%H%M%S")
    note = f"{tag} {label}".strip()
    lines, undo, notes = [], [], []
    match = []
    for h in targets:
        mac, ip = (h.get("mac") or "").upper(), h.get("ip") or ""
        if mac and _MAC.match(mac):
            match.append((f"src-mac-address={mac}", h))
        elif ip and _is_ip(ip):
            match.append((f"src-address={ip}", h))
    if not match:
        raise ValueError("所选设备都没有 MAC 或 IP，无法生成规则")
    times = _time_parts(days, t_from, t_to)
    tparam = lambda tp: f" time={tp}" if tp else ""  # noqa: E731
    if action in ("block_app", "block_all"):
        lines.append("/ip firewall filter")
        if action == "block_app":
            doms = app_domains(db, apps, groups)
            if not doms:
                raise ValueError("没有找到这些应用的域名")
            for m, h in match:
                for tp in times:
                    for d in doms:
                        lines.append(f"add chain=forward {m} protocol=tcp dst-port=443 tls-host=*{d}{tparam(tp)} "
                                     f"action=reject reject-with=tcp-reset place-before=0 comment={_q(note)}")
                    if block_quic:
                        lines.append(f"add chain=forward {m} protocol=udp dst-port=443{tparam(tp)} action=drop "
                                     f"place-before=0 comment={_q(note)}")
            notes.append(f"按 TLS 域名封禁 {len(doms)} 个域名：{', '.join(doms[:12])}{' …' if len(doms) > 12 else ''}")
            if block_quic:
                notes.append("同时在该时段禁止这些设备的 QUIC（udp/443），应用会改用 TCP，从而能按域名拦截。")
            notes.append("tls-host 只认 HTTPS 握手里的域名；应用改用 IP 直连或私有协议时拦不住。")
        else:
            for m, h in match:
                for tp in times:
                    lines.append(f"add chain=forward {m}{tparam(tp)} action=drop place-before=0 comment={_q(note)}")
        undo.append(f"/ip firewall filter remove [find comment={_q(note)}]")
        notes.append("规则放在最前面（place-before=0），在 FastTrack 之前生效；已经建立的连接不受影响，可在 IP → Firewall → Connections 里清掉。")
    elif action == "limit":
        if not (up_mbps or down_mbps):
            raise ValueError("请填写限速值")
        lines.append("/queue simple")
        for _m, h in match:
            ip = h.get("ip") or ""
            if not re.match(r"^\d+\.\d+\.\d+\.\d+$", ip):
                notes.append(f"{h.get('name')} 没有 IPv4 地址，跳过")
                continue
            lines.append(f"add name={_q(note + ' ' + (h.get('name') or ip))} target={ip}/32 "
                         f"max-limit={_rate(up_mbps)}/{_rate(down_mbps)} comment={_q(note)}")
        undo.append(f"/queue simple remove [find comment={_q(note)}]")
        notes.append("简单队列按 IP 限速：设备换了 IP 要重新生成；开了 FastTrack 时被加速的连接不受队列限制。")
    else:
        raise ValueError("未知的动作")
    return {"tag": tag, "script": "\n".join(lines), "undo": "\n".join(undo), "notes": notes,
            "targets": [h.get("name") for _m, h in match]}


def _is_ip(s: str) -> bool:
    import ipaddress
    try:
        ipaddress.ip_address(s)
        return True
    except ValueError:
        return False


def _rate(mbps: float) -> str:
    return "0" if not mbps else f"{int(mbps * 1000)}k"
