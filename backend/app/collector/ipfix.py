"""IPFIX (v10) 与 NetFlow v9 解码。

RouterOS 的 /ip traffic-flow 两种都支持，模板会周期性重发（默认 20 个包或 30 分钟），
收到模板之前的数据集无法解码，会被计数后丢弃。
"""
import ipaddress
import struct
from dataclasses import dataclass

# IANA IPFIX 信息元素编号（NetFlow v9 的字段类型编号在这个范围内一致）
F_OCTETS = 1
F_PACKETS = 2
F_PROTO = 4
F_SRC_PORT = 7
F_SRC_V4 = 8
F_DST_PORT = 11
F_DST_V4 = 12
F_IN_IF = 10
F_OUT_IF = 14
F_SRC_V6 = 27
F_DST_V6 = 28
F_SRC_MAC = 56
F_DST_MAC = 80
F_POST_SRC_V4 = 225
F_POST_DST_V4 = 226
F_POST_SRC_PORT = 227
F_POST_DST_PORT = 228

_NAMES = {
    F_OCTETS: "bytes",
    F_PACKETS: "packets",
    F_PROTO: "proto",
    F_SRC_PORT: "sport",
    F_DST_PORT: "dport",
    F_SRC_V4: "src",
    F_DST_V4: "dst",
    F_SRC_V6: "src",
    F_DST_V6: "dst",
    F_IN_IF: "in_if",
    F_OUT_IF: "out_if",
    F_SRC_MAC: "src_mac",
    F_DST_MAC: "dst_mac",
    F_POST_SRC_V4: "post_src",
    F_POST_DST_V4: "post_dst",
    F_POST_SRC_PORT: "post_sport",
    F_POST_DST_PORT: "post_dport",
}
_IP_FIELDS = {F_SRC_V4, F_DST_V4, F_SRC_V6, F_DST_V6, F_POST_SRC_V4, F_POST_DST_V4}
_MAC_FIELDS = {F_SRC_MAC, F_DST_MAC}


@dataclass
class Field:
    fid: int
    length: int  # 65535 = 变长
    enterprise: int = 0


class DecodeError(Exception):
    pass


def _fmt_mac(b: bytes) -> str:
    return ":".join(f"{x:02X}" for x in b)


class FlowDecoder:
    def __init__(self):
        # (exporter, version, domain/source_id, template_id) -> [Field]
        self.templates: dict[tuple, list[Field]] = {}
        self.stats = {"packets": 0, "records": 0, "no_template": 0, "errors": 0}

    def decode(self, data: bytes, exporter: str) -> list[dict]:
        self.stats["packets"] += 1
        try:
            if len(data) < 4:
                raise DecodeError("too short")
            version = struct.unpack_from("!H", data, 0)[0]
            if version == 10:
                return self._ipfix(data, exporter)
            if version == 9:
                return self._v9(data, exporter)
            raise DecodeError(f"unsupported version {version}")
        except (DecodeError, struct.error, ValueError, IndexError):
            self.stats["errors"] += 1
            return []

    # ---------- IPFIX ----------
    def _ipfix(self, data: bytes, exporter: str) -> list[dict]:
        if len(data) < 16:
            raise DecodeError("short ipfix header")
        _, length, _export_time, _seq, domain = struct.unpack_from("!HHIII", data, 0)
        end = min(length, len(data))
        off = 16
        out: list[dict] = []
        while off + 4 <= end:
            set_id, set_len = struct.unpack_from("!HH", data, off)
            if set_len < 4:
                raise DecodeError("bad set length")
            body = data[off + 4: off + set_len]
            if set_id == 2:
                self._ipfix_templates(body, (exporter, 10, domain), options=False)
            elif set_id == 3:
                self._ipfix_templates(body, (exporter, 10, domain), options=True)
            elif set_id >= 256:
                out.extend(self._records(body, (exporter, 10, domain, set_id), ipfix=True))
            off += set_len
        return out

    def _ipfix_templates(self, body: bytes, key: tuple, options: bool):
        off = 0
        while off + 4 <= len(body):
            tid, count = struct.unpack_from("!HH", body, off)
            off += 4
            if tid < 256:  # 填充
                break
            if options:
                off += 2  # scope field count，作用域字段也在下面的列表里
            fields = []
            for _ in range(count):
                fid, flen = struct.unpack_from("!HH", body, off)
                off += 4
                ent = 0
                if fid & 0x8000:
                    fid &= 0x7FFF
                    ent = struct.unpack_from("!I", body, off)[0]
                    off += 4
                fields.append(Field(fid, flen, ent))
            # 选项模板（采样率、接口名等）只记下长度用于跳过，不解码
            self.templates[key + (tid,)] = fields if not options else [Field(-1, f.length, f.enterprise) for f in fields]

    # ---------- NetFlow v9 ----------
    def _v9(self, data: bytes, exporter: str) -> list[dict]:
        if len(data) < 20:
            raise DecodeError("short v9 header")
        _, _count, _uptime, _secs, _seq, source_id = struct.unpack_from("!HHIIII", data, 0)
        off = 20
        out: list[dict] = []
        while off + 4 <= len(data):
            set_id, set_len = struct.unpack_from("!HH", data, off)
            if set_len < 4:
                raise DecodeError("bad flowset length")
            body = data[off + 4: off + set_len]
            key = (exporter, 9, source_id)
            if set_id == 0:
                self._v9_templates(body, key)
            elif set_id == 1:
                self._v9_options(body, key)
            elif set_id >= 256:
                out.extend(self._records(body, key + (set_id,), ipfix=False))
            off += set_len
        return out

    def _v9_templates(self, body: bytes, key: tuple):
        off = 0
        while off + 4 <= len(body):
            tid, count = struct.unpack_from("!HH", body, off)
            off += 4
            if tid < 256:
                break
            fields = []
            for _ in range(count):
                fid, flen = struct.unpack_from("!HH", body, off)
                off += 4
                fields.append(Field(fid, flen))
            self.templates[key + (tid,)] = fields

    def _v9_options(self, body: bytes, key: tuple):
        off = 0
        while off + 6 <= len(body):
            tid, scope_len, opt_len = struct.unpack_from("!HHH", body, off)
            off += 6
            if tid < 256:
                break
            fields = []
            for _ in range((scope_len + opt_len) // 4):
                _fid, flen = struct.unpack_from("!HH", body, off)
                off += 4
                fields.append(Field(-1, flen))
            self.templates[key + (tid,)] = fields

    # ---------- 数据记录 ----------
    def _records(self, body: bytes, tkey: tuple, ipfix: bool) -> list[dict]:
        fields = self.templates.get(tkey)
        if fields is None:
            self.stats["no_template"] += 1
            return []
        if not fields:
            return []
        min_len = sum(f.length if f.length != 65535 else 1 for f in fields)
        out = []
        off = 0
        while len(body) - off >= min_len:
            rec: dict = {}
            for f in fields:
                flen = f.length
                if flen == 65535:
                    flen = body[off]
                    off += 1
                    if flen == 255:
                        flen = struct.unpack_from("!H", body, off)[0]
                        off += 2
                raw = body[off: off + flen]
                off += flen
                if len(raw) < flen:
                    raise DecodeError("truncated record")
                if f.enterprise or f.fid < 0:
                    continue
                name = _NAMES.get(f.fid)
                if name is None:
                    continue
                if f.fid in _IP_FIELDS:
                    if flen in (4, 16):
                        rec[name] = str(ipaddress.ip_address(raw))
                elif f.fid in _MAC_FIELDS:
                    if flen == 6:
                        rec[name] = _fmt_mac(raw)
                else:
                    rec[name] = int.from_bytes(raw, "big")
            if "bytes" in rec:
                out.append(rec)
        self.stats["records"] += len(out)
        return out
