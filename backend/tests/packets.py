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


# ---------- TLS / QUIC 握手（SNI 测试用） ----------

def _eth_ip(src, dst, proto, l4):
    """以太网 + IPv4/IPv6 头"""
    a, b = ipaddress.ip_address(src), ipaddress.ip_address(dst)
    eth = b"\x11" * 6 + b"\x22" * 6
    if a.version == 4:
        iph = struct.pack("!BBHHHBBH4s4s", 0x45, 0, 20 + len(l4), 0, 0, 64, proto, 0, a.packed, b.packed)
        return eth + b"\x08\x00" + iph + l4
    iph = struct.pack("!IHBB16s16s", 6 << 28, len(l4), proto, 64, a.packed, b.packed)
    return eth + b"\x86\xdd" + iph + l4


def tzsp(frame):
    return b"\x01\x00\x00\x01" + b"\x01" + frame


def tcp_segment(src, dst, sport, dport, seq, payload):
    hdr = struct.pack("!HHIIBBHHH", sport, dport, seq, 1, 5 << 4, 0x18, 65535, 0, 0)
    return tzsp(_eth_ip(src, dst, 6, hdr + payload))


def udp_datagram(src, dst, sport, dport, payload):
    return tzsp(_eth_ip(src, dst, 17, struct.pack("!HHHH", sport, dport, 8 + len(payload), 0) + payload))


def client_hello(sni, pad_before_sni=0):
    """最小的 TLS 1.3 ClientHello 握手消息；pad_before_sni 模拟 SNI 前面有很大的扩展（如后量子 key_share）。"""
    exts = b""
    if pad_before_sni:
        exts += struct.pack("!HH", 0x0015, pad_before_sni) + b"\0" * pad_before_sni
    name = sni.encode()
    sn = struct.pack("!HBH", len(name) + 3, 0, len(name)) + name
    exts += struct.pack("!HH", 0, len(sn)) + sn
    body = b"\x03\x03" + b"\x07" * 32 + b"\x00" + struct.pack("!H", 2) + b"\x13\x01" + b"\x01\x00"
    body += struct.pack("!H", len(exts)) + exts
    return b"\x01" + len(body).to_bytes(3, "big") + body


def tls_record(hs):
    return b"\x16\x03\x01" + struct.pack("!H", len(hs)) + hs


def _qvar(n):
    if n < 64:
        return bytes([n])
    if n < 16384:
        return struct.pack("!H", 0x4000 | n)
    return struct.pack("!I", 0x80000000 | n)


def quic_initial(dcid, crypto, pn=0, version=1, extra_frames=b""):
    """加密一个客户端 Initial 包。crypto: [(offset, data)]，会被包成 CRYPTO 帧（中间夹 PING/PADDING）。"""
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    from app.collector.tls import initial_keys
    key, iv, hp = initial_keys(dcid, version)
    frames = extra_frames
    for off, data in crypto:
        frames += b"\x01" + b"\x06" + _qvar(off) + _qvar(len(data)) + data + b"\x00" * 3
    frames += b"\x00" * max(0, 1162 - len(frames))  # 客户端 Initial 至少 1200 字节
    ptype = 0 if version == 1 else 1
    first = 0xC0 | (ptype << 4) | 0x03  # 4 字节包号
    pnb = struct.pack("!I", pn)
    length = len(frames) + 16 + 4
    header = bytes([first]) + struct.pack("!I", version) + bytes([len(dcid)]) + dcid + b"\x00" + b"\x00" + \
        struct.pack("!H", 0x4000 | length) + pnb
    nonce = iv[:-4] + bytes(x ^ y for x, y in zip(iv[-4:], pnb))
    ct = AESGCM(key).encrypt(nonce, frames, header)
    mask = Cipher(algorithms.AES(hp), modes.ECB()).encryptor().update(ct[:16])
    hdr = bytearray(header)
    hdr[0] ^= mask[0] & 0x0F
    for i in range(4):
        hdr[-4 + i] ^= mask[1 + i]
    return bytes(hdr) + ct
