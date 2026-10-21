"""构造 IPFIX / NetFlow v9 / TZSP-DNS 测试包（测试和 scripts/simulate.py 共用）。"""
import ipaddress
import struct
import time

# (field_id, length) — 模仿 RouterOS IPFIX 模板的主要字段
V4_FIELDS = [(8, 4), (12, 4), (7, 2), (11, 2), (4, 1), (1, 8), (2, 8), (56, 6), (225, 4), (226, 4)]
V6_FIELDS = [(27, 16), (28, 16), (7, 2), (11, 2), (4, 1), (1, 8), (2, 8)]


def _rec_v4(src, dst, sport, dport, proto, nbytes, pkts=1, mac="00:00:00:00:00:00", post_src="0.0.0.0",
            post_dst="0.0.0.0"):
    return (ipaddress.IPv4Address(src).packed + ipaddress.IPv4Address(dst).packed
            + struct.pack("!HHBQQ", sport, dport, proto, nbytes, pkts)
            + bytes.fromhex(mac.replace(":", ""))
            + ipaddress.IPv4Address(post_src).packed + ipaddress.IPv4Address(post_dst).packed)


def _rec_v6(src, dst, sport, dport, proto, nbytes, pkts=1):
    return (ipaddress.IPv6Address(src).packed + ipaddress.IPv6Address(dst).packed
            + struct.pack("!HHBQQ", sport, dport, proto, nbytes, pkts))


def _tmpl(tid, fields):
    body = struct.pack("!HH", tid, len(fields)) + b"".join(struct.pack("!HH", f, n) for f, n in fields)
    return body


def _set(set_id, body):
    pad = (-len(body)) % 4
    body += b"\0" * pad
    return struct.pack("!HH", set_id, len(body) + 4) + body


def ipfix(flows_v4=(), flows_v6=(), with_template=True, domain=0, seq=1):
    """flows_v4: [dict(src,dst,sport,dport,proto,nbytes,mac?,post_dst?...)]"""
    sets = b""
    if with_template:
        sets += _set(2, _tmpl(256, V4_FIELDS) + _tmpl(257, V6_FIELDS))
    if flows_v4:
        sets += _set(256, b"".join(_rec_v4(**f) for f in flows_v4))
    if flows_v6:
        sets += _set(257, b"".join(_rec_v6(**f) for f in flows_v6))
    hdr = struct.pack("!HHIII", 10, 16 + len(sets), int(time.time()), seq, domain)
    return hdr + sets


def netflow9(flows_v4=(), with_template=True, source_id=0):
    sets = b""
    count = 0
    if with_template:
        sets += _set(0, _tmpl(300, V4_FIELDS))
        count += 1
    if flows_v4:
        sets += _set(300, b"".join(_rec_v4(**f) for f in flows_v4))
        count += len(flows_v4)
    hdr = struct.pack("!HHIIII", 9, count, 1000, int(time.time()), 1, source_id)
    return hdr + sets


def _name(n):
    return b"".join(bytes([len(p)]) + p.encode() for p in n.split(".")) + b"\0"


def dns_response(qname, ips, cnames=(), ttl=60):
    an = []
    owner = b"\xc0\x0c"
    for c in cnames:
        rd = _name(c)
        an.append(owner + struct.pack("!HHIH", 5, 1, ttl, len(rd)) + rd)
    for ip in ips:
        a = ipaddress.ip_address(ip)
        an.append(owner + struct.pack("!HHIH", 1 if a.version == 4 else 28, 1, ttl, len(a.packed)) + a.packed)
    hdr = struct.pack("!HHHHHH", 0x1234, 0x8180, 1, len(an), 0, 0)
    return hdr + _name(qname) + struct.pack("!HH", 1, 1) + b"".join(an)


def tzsp_dns(client, qname, ips, cnames=(), server="192.168.88.1", vlan=None):
    payload = dns_response(qname, ips, cnames)
    udp = struct.pack("!HHHH", 53, 40000, 8 + len(payload), 0) + payload
    iph = struct.pack("!BBHHHBBH4s4s", 0x45, 0, 20 + len(udp), 0, 0, 64, 17, 0,
                      ipaddress.IPv4Address(server).packed, ipaddress.IPv4Address(client).packed)
    eth = b"\x11" * 6 + b"\x22" * 6
    if vlan is not None:
        eth += struct.pack("!HH", 0x8100, vlan)
    eth += b"\x08\x00"
    # TZSP v1, type 0 (received), encap 1 (Ethernet)，带一个填充和结束标记
    return b"\x01\x00\x00\x01" + b"\x00" + b"\x01" + eth + iph + udp
