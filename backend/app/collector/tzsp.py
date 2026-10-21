"""解 RouterOS sniff-tzsp 镜像过来的包：TZSP → 以太网 → IPv4/IPv6 → UDP → DNS 响应。"""
import ipaddress
import struct
from dataclasses import dataclass, field

QTYPE_A = 1
QTYPE_CNAME = 5
QTYPE_AAAA = 28


@dataclass
class DnsAnswer:
    client: str                    # 收到响应的终端（UDP 目的地址）
    qname: str                     # 终端查询的名字
    ips: list[tuple[str, int]] = field(default_factory=list)  # (ip, ttl)
    cnames: list[str] = field(default_factory=list)


def tzsp_payload(data: bytes) -> bytes | None:
    """返回 TZSP 里封装的以太网帧。"""
    if len(data) < 4 or data[0] != 1:
        return None
    encap = struct.unpack_from("!H", data, 2)[0]
    if encap != 1:  # 只处理 Ethernet
        return None
    off = 4
    while off < len(data):
        tag = data[off]
        if tag == 1:  # TAG_END
            return data[off + 1:]
        if tag == 0:  # TAG_PADDING
            off += 1
            continue
        if off + 1 >= len(data):
            return None
        off += 2 + data[off + 1]
    return None


def ethernet_udp(frame: bytes) -> tuple[str, str, int, int, bytes] | None:
    """以太网帧 → (src_ip, dst_ip, sport, dport, udp_payload)，非 UDP 返回 None。"""
    if len(frame) < 14:
        return None
    off = 12
    etype = struct.unpack_from("!H", frame, off)[0]
    off += 2
    while etype in (0x8100, 0x88A8):  # VLAN / QinQ
        if len(frame) < off + 4:
            return None
        etype = struct.unpack_from("!H", frame, off + 2)[0]
        off += 4
    if etype == 0x0800:
        if len(frame) < off + 20:
            return None
        ihl = (frame[off] & 0x0F) * 4
        if frame[off + 9] != 17:
            return None
        src = str(ipaddress.IPv4Address(frame[off + 12: off + 16]))
        dst = str(ipaddress.IPv4Address(frame[off + 16: off + 20]))
        off += ihl
    elif etype == 0x86DD:
        if len(frame) < off + 40:
            return None
        if frame[off + 6] != 17:  # 不处理扩展头
            return None
        src = str(ipaddress.IPv6Address(frame[off + 8: off + 24]))
        dst = str(ipaddress.IPv6Address(frame[off + 24: off + 40]))
        off += 40
    else:
        return None
    if len(frame) < off + 8:
        return None
    sport, dport, ulen = struct.unpack_from("!HHH", frame, off)
    payload = frame[off + 8: off + max(ulen, 8)]
    return src, dst, sport, dport, payload


def _read_name(msg: bytes, off: int) -> tuple[str, int]:
    labels = []
    jumped = False
    end = off
    hops = 0
    while True:
        if off >= len(msg):
            raise ValueError("name out of range")
        ln = msg[off]
        if ln & 0xC0 == 0xC0:
            if off + 1 >= len(msg):
                raise ValueError("bad pointer")
            ptr = ((ln & 0x3F) << 8) | msg[off + 1]
            if not jumped:
                end = off + 2
            jumped = True
            off = ptr
            hops += 1
            if hops > 20:
                raise ValueError("pointer loop")
            continue
        if ln == 0:
            if not jumped:
                end = off + 1
            break
        labels.append(msg[off + 1: off + 1 + ln].decode("ascii", "replace"))
        off += 1 + ln
    return ".".join(labels).lower(), end


def parse_dns_response(msg: bytes) -> tuple[str, list[tuple[str, int]], list[str]] | None:
    """返回 (qname, [(ip, ttl)], [cname...])；不是响应或没有 A/AAAA 时返回 None。"""
    if len(msg) < 12:
        return None
    _id, flags, qd, an, _ns, _ar = struct.unpack_from("!HHHHHH", msg, 0)
    if not flags & 0x8000 or flags & 0x000F or qd != 1 or an == 0:
        return None
    qname, off = _read_name(msg, 12)
    off += 4
    ips: list[tuple[str, int]] = []
    cnames: list[str] = []
    for _ in range(an):
        _name, off = _read_name(msg, off)
        if off + 10 > len(msg):
            break
        rtype, _cls, ttl, rdlen = struct.unpack_from("!HHIH", msg, off)
        off += 10
        rdata = msg[off: off + rdlen]
        if rtype == QTYPE_A and rdlen == 4:
            ips.append((str(ipaddress.IPv4Address(rdata)), ttl))
        elif rtype == QTYPE_AAAA and rdlen == 16:
            ips.append((str(ipaddress.IPv6Address(rdata)), ttl))
        elif rtype == QTYPE_CNAME:
            cnames.append(_read_name(msg, off)[0])
        off += rdlen
    if not ips or not qname:
        return None
    return qname, ips, cnames


def parse_tzsp_dns(data: bytes) -> DnsAnswer | None:
    frame = tzsp_payload(data)
    if frame is None:
        return None
    udp = ethernet_udp(frame)
    if udp is None:
        return None
    _src, dst, sport, _dport, payload = udp
    if sport != 53:
        return None
    try:
        parsed = parse_dns_response(payload)
    except (ValueError, struct.error, ipaddress.AddressValueError):
        return None
    if parsed is None:
        return None
    qname, ips, cnames = parsed
    return DnsAnswer(client=dst, qname=qname, ips=ips, cnames=cnames)
