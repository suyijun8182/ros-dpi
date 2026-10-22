"""从镜像过来的连接首包里取 SNI（TLS ClientHello 里明文的目标域名）。

- TCP：TLS 记录层 → ClientHello。ClientHello 常被拆成 2 个 TCP 段（Chrome 带后量子密钥交换时约 1.8KB），按序号重组。
- QUIC（HTTP/3，udp/443）：Initial 包用公开算法（RFC 9001 / 9369）加密，密钥由包头里的连接 ID 推导，
  任何人都能解开；ClientHello 在 CRYPTO 帧里，Chrome 会把它打散到多个帧甚至多个包，按偏移量重组。

终端用 DoH 加密 DNS 时 DNS 嗅探失效，但 SNI 仍是明文，靠它补上。启用了 ECH 的连接只能看到外层的公共名字。
"""
import ipaddress
import struct
import time
from collections import OrderedDict

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.hmac import HMAC

# ---------------------------------------------------------------- 以太网 / IP

def ethernet_ip(frame: bytes) -> tuple[str, str, int, bytes] | None:
    """以太网帧 → (src_ip, dst_ip, ip_proto, l4_bytes)。不处理分片和 IPv6 扩展头。"""
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
        total = struct.unpack_from("!H", frame, off + 2)[0]
        if struct.unpack_from("!H", frame, off + 6)[0] & 0x1FFF:  # 非首个分片
            return None
        proto = frame[off + 9]
        src = str(ipaddress.IPv4Address(frame[off + 12: off + 16]))
        dst = str(ipaddress.IPv4Address(frame[off + 16: off + 20]))
        end = off + total if total >= ihl else len(frame)  # 去掉以太网填充
        return src, dst, proto, frame[off + ihl: end]
    if etype == 0x86DD:
        if len(frame) < off + 40:
            return None
        plen = struct.unpack_from("!H", frame, off + 4)[0]
        proto = frame[off + 6]
        src = str(ipaddress.IPv6Address(frame[off + 8: off + 24]))
        dst = str(ipaddress.IPv6Address(frame[off + 24: off + 40]))
        return src, dst, proto, frame[off + 40: off + 40 + plen]
    return None


# ---------------------------------------------------------------- TLS ClientHello

class Truncated(Exception):
    """数据还不完整（等后续 TCP 段 / CRYPTO 帧）"""


def _need(buf: bytes, end: int):
    if end > len(buf):
        raise Truncated


def client_hello_sni(hs: bytes) -> str | None:
    """hs：握手消息（从 ClientHello 的类型字节开始）。返回 SNI；不是 ClientHello 返回 None；不完整抛 Truncated。

    只要读到 SNI 扩展就返回，不要求整个 ClientHello 都到齐。
    """
    _need(hs, 4)
    if hs[0] != 1:
        return None
    off = 4 + 2 + 32                                     # 类型+长度、版本、随机数
    _need(hs, off + 1)
    off += 1 + hs[off]                                   # session id
    _need(hs, off + 2)
    off += 2 + struct.unpack_from("!H", hs, off)[0]      # cipher suites
    _need(hs, off + 1)
    off += 1 + hs[off]                                   # compression
    _need(hs, off + 2)
    ext_end = off + 2 + struct.unpack_from("!H", hs, off)[0]
    off += 2
    while off + 4 <= ext_end:
        _need(hs, off + 4)
        etype, elen = struct.unpack_from("!HH", hs, off)
        off += 4
        if etype == 0:  # server_name
            _need(hs, off + elen)
            p = off + 2
            while p + 3 <= off + elen:
                ntype, nlen = hs[p], struct.unpack_from("!H", hs, p + 1)[0]
                if ntype == 0:
                    name = hs[p + 3: p + 3 + nlen].decode("ascii", "replace").lower().rstrip(".")
                    return name if _valid_host(name) else None
                p += 3 + nlen
            return None
        off += elen
    if ext_end > len(hs):
        raise Truncated
    return None


def _valid_host(name: str) -> bool:
    if not name or len(name) > 253 or "." not in name:
        return False
    try:
        ipaddress.ip_address(name)  # SNI 不应是 IP
        return False
    except ValueError:
        return all(c.isalnum() or c in "-._" for c in name)


def tls_records_sni(stream: bytes) -> str | None:
    """TCP 字节流开头的 TLS 记录 → SNI。不是 TLS 握手返回 None；不完整抛 Truncated。"""
    _need(stream, 5)
    if stream[0] != 0x16 or stream[1] != 0x03:
        return None
    hs = b""
    off = 0
    # ClientHello 一般在一条记录里，偶尔跨多条，拼起来
    while off + 5 <= len(stream) and stream[off] == 0x16:
        rlen = struct.unpack_from("!H", stream, off + 3)[0]
        hs += stream[off + 5: off + 5 + rlen]
        if off + 5 + rlen > len(stream):
            break
        off += 5 + rlen
        try:
            return client_hello_sni(hs)
        except Truncated:
            continue
    return client_hello_sni(hs)


# ---------------------------------------------------------------- QUIC Initial

_QUIC = {
    0x00000001: (bytes.fromhex("38762cf7f55934b34d179ae6a4c80cadccbb7f0a"), "quic", 0),      # v1 (RFC 9001)
    0x6B3343CF: (bytes.fromhex("0dede3def700a6db819381be6e269dcbf9bd2ed9"), "quicv2", 1),    # v2 (RFC 9369)
    0xFF00001D: (bytes.fromhex("afbfec289993d24c9e9786f19c6111e04390a899"), "quic", 0),      # draft-29
}


def _hmac(key: bytes, data: bytes) -> bytes:
    h = HMAC(key, hashes.SHA256())
    h.update(data)
    return h.finalize()


def hkdf_expand_label(secret: bytes, label: str, length: int) -> bytes:
    full = b"tls13 " + label.encode()
    info = struct.pack("!HB", length, len(full)) + full + b"\x00"
    out, t, i = b"", b"", 1
    while len(out) < length:
        t = _hmac(secret, t + info + bytes([i]))
        out += t
        i += 1
    return out[:length]


def initial_keys(dcid: bytes, version: int = 1) -> tuple[bytes, bytes, bytes]:
    """客户端 Initial 的 (key, iv, hp)"""
    salt, lbl, _ = _QUIC[version]
    initial_secret = _hmac(salt, dcid)  # HKDF-Extract
    client = hkdf_expand_label(initial_secret, "client in", 32)
    return (hkdf_expand_label(client, f"{lbl} key", 16), hkdf_expand_label(client, f"{lbl} iv", 12),
            hkdf_expand_label(client, f"{lbl} hp", 16))


def _varint(b: bytes, off: int) -> tuple[int, int]:
    _need(b, off + 1)
    n = 1 << (b[off] >> 6)
    _need(b, off + n)
    v = b[off] & 0x3F
    for i in range(1, n):
        v = (v << 8) | b[off + i]
    return v, off + n


def quic_initial_crypto(dgram: bytes) -> tuple[bytes, list[tuple[int, bytes]]] | None:
    """解开 UDP 报文里客户端的 QUIC Initial 包。返回 (dcid, [(offset, CRYPTO 数据)])；不是 Initial 返回 None。"""
    frames: list[tuple[int, bytes]] = []
    dcid0 = None
    pos = 0
    while pos < len(dgram):  # 一个 UDP 报文里可能合并了多个 QUIC 包
        b0 = dgram[pos]
        if not b0 & 0x80 or pos + 7 > len(dgram):
            break
        version = struct.unpack_from("!I", dgram, pos + 1)[0]
        if version not in _QUIC:
            break
        ptype = (b0 & 0x30) >> 4
        if ptype != _QUIC[version][2]:  # 只要 Initial
            break
        off = pos + 5
        dlen = dgram[off]
        if dlen > 20:
            return None
        dcid = dgram[off + 1: off + 1 + dlen]
        off += 1 + dlen
        _need(dgram, off + 1)
        off += 1 + dgram[off]                       # scid
        tlen, off = _varint(dgram, off)
        off += tlen                                 # token
        plen, off = _varint(dgram, off)
        pn_off, end = off, off + plen
        if end > len(dgram) or plen < 20:
            break
        key, iv, hp = initial_keys(dcid, version)
        sample = dgram[pn_off + 4: pn_off + 20]
        mask = Cipher(algorithms.AES(hp), modes.ECB()).encryptor().update(sample)
        first = b0 ^ (mask[0] & 0x0F)
        pn_len = (first & 0x03) + 1
        pn_bytes = bytes(x ^ y for x, y in zip(dgram[pn_off: pn_off + pn_len], mask[1: 1 + pn_len]))
        header = bytes([first]) + dgram[pos + 1: pn_off] + pn_bytes
        nonce = iv[:-pn_len] + bytes(x ^ y for x, y in zip(iv[-pn_len:], pn_bytes))
        try:
            plain = AESGCM(key).decrypt(nonce, dgram[pn_off + pn_len: end], header)
        except Exception:  # noqa: BLE001  不是客户端 Initial（例如服务器发的），或数据损坏
            return None
        dcid0 = dcid0 if dcid0 is not None else dcid
        frames += _crypto_frames(plain)
        pos = end
    return (dcid0, frames) if dcid0 is not None else None


def _crypto_frames(p: bytes) -> list[tuple[int, bytes]]:
    out, off = [], 0
    try:
        while off < len(p):
            ft = p[off]
            off += 1
            if ft in (0x00, 0x01):                  # PADDING / PING
                continue
            if ft == 0x06:                          # CRYPTO
                o, off = _varint(p, off)
                n, off = _varint(p, off)
                out.append((o, p[off: off + n]))
                off += n
            elif ft in (0x02, 0x03):                # ACK
                _largest, off = _varint(p, off)
                _delay, off = _varint(p, off)
                cnt, off = _varint(p, off)
                _first, off = _varint(p, off)
                for _ in range(cnt * 2):
                    _x, off = _varint(p, off)
                if ft == 0x03:
                    for _ in range(3):
                        _x, off = _varint(p, off)
            else:                                   # Initial 里不会有别的帧，遇到就停
                break
    except Truncated:
        pass
    return out


# ---------------------------------------------------------------- 重组

class SniExtractor:
    """处理镜像过来的包，凑齐 ClientHello 后返回 (client_ip, client_port, server_ip, server_port, sni, 'tls'|'quic')。"""

    TTL = 10            # 未完成的重组最多等 10 秒
    MAX_PENDING = 20000

    def __init__(self):
        self._tcp: OrderedDict[tuple, tuple[int, dict[int, bytes], float]] = OrderedDict()
        self._quic: OrderedDict[tuple, tuple[dict[int, bytes], float]] = OrderedDict()
        self.stats = {"tls": 0, "quic": 0, "no_sni": 0}

    def feed(self, src: str, dst: str, proto: int, l4: bytes, now: float | None = None):
        now = now or time.time()
        if proto == 6:
            return self._feed_tcp(src, dst, l4, now)
        if proto == 17 and len(l4) >= 8:
            sport, dport = struct.unpack_from("!HH", l4, 0)
            payload = l4[8:]
            if payload and payload[0] & 0xC0 == 0xC0:  # QUIC 长包头
                return self._feed_quic(src, dst, sport, dport, payload, now)
        return None

    def _feed_tcp(self, src, dst, seg, now):
        if len(seg) < 20:
            return None
        sport, dport, seq = struct.unpack_from("!HHI", seg, 0)
        data = seg[(seg[12] >> 4) * 4:]
        if not data:
            return None
        key = (src, sport, dst, dport)
        st = self._tcp.get(key)
        if st is None:
            if data[0] != 0x16 or len(data) < 2 or data[1] != 0x03:
                return None  # 不是 TLS 握手的开头（可能是之后的数据包，忽略）
            st = (seq, {}, now)
            self._tcp[key] = st
            self._gc(self._tcp, now)
        seq0, parts, _t = st
        parts[(seq - seq0) & 0xFFFFFFFF] = data
        stream = b""
        for off in sorted(parts):
            if off > len(stream):
                break
            stream += parts[off][len(stream) - off:]
        try:
            sni = tls_records_sni(stream)
        except Truncated:
            if len(stream) > 16384:
                self._tcp.pop(key, None)
            return None
        except (struct.error, IndexError):
            sni = None
        self._tcp.pop(key, None)
        if not sni:
            self.stats["no_sni"] += 1
            return None
        self.stats["tls"] += 1
        return src, sport, dst, dport, sni, "tls"

    def _feed_quic(self, src, dst, sport, dport, payload, now):
        try:
            got = quic_initial_crypto(payload)
        except (Truncated, struct.error, IndexError, ValueError):
            return None
        if not got:
            return None
        dcid, frames = got
        key = (src, sport, dst, dport, dcid)
        st = self._quic.get(key)
        if st is None:
            st = ({}, now)
            self._quic[key] = st
            self._gc(self._quic, now)
        parts = st[0]
        for o, d in frames:
            parts[o] = d
        stream = b""
        for off in sorted(parts):
            if off > len(stream):
                break
            stream += parts[off][len(stream) - off:]
        try:
            sni = client_hello_sni(stream)
        except Truncated:
            return None
        except (struct.error, IndexError):
            sni = None
        self._quic.pop(key, None)
        if not sni:
            self.stats["no_sni"] += 1
            return None
        self.stats["quic"] += 1
        return src, sport, dst, dport, sni, "quic"

    def _gc(self, d: OrderedDict, now: float):
        while d and (len(d) > self.MAX_PENDING or now - next(iter(d.values()))[-1] > self.TTL):
            d.popitem(last=False)
