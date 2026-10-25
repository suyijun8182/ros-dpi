"""全站审计：采集端口和解析器的防护（来源白名单、模板上限、TLS 重组上限、ECH 外层名、超长域名、IPv6 扩展头）"""
import struct

from packets import ipfix, tzsp_dns

from app.collector.ipfix import MAX_TEMPLATES, FlowDecoder
from app.collector.tls import MAX_PARTS, SniExtractor, skip_v6_ext
from app.engine import Engine


def _engine():
    e = Engine()
    e.set_lan("192.168.88.0/24")
    return e


def test_collector_source_allowlist():
    e = _engine()
    e.allowed_sources = [__import__("ipaddress").ip_network("10.0.0.1/32")]
    pkt = ipfix([dict(src="192.168.88.10", dst="5.5.5.5", sport=1, dport=443, proto=6, nbytes=100,
                      mac="AA:00:00:00:00:10")])
    e.on_ipfix(pkt, "192.168.88.66")                 # 不在白名单：丢弃
    assert not e._buf and e.stats["rejected"] == 1
    e.on_tzsp(tzsp_dns("192.168.88.10", "evil.example", ["1.2.3.4"]), "192.168.88.66")
    assert e.dns.lookup("1.2.3.4") is None
    e.on_ipfix(pkt, "10.0.0.1")
    assert e._buf


def test_template_table_is_bounded():
    d = FlowDecoder()
    for i in range(MAX_TEMPLATES + 50):
        d._store(("x", 10, i, 256), [])
    assert len(d.templates) == MAX_TEMPLATES


def test_tls_reassembly_bounded():
    ex = SniExtractor()
    hdr = lambda seq, data: struct.pack("!HHIIBBHHH", 50000, 443, seq, 0, 5 << 4, 0x18, 0, 0, 0) + data  # noqa: E731
    ex._feed_tcp("192.168.88.10", "1.1.1.1", hdr(1000, b"\x16\x03\x01\x02\x00\x01"), 0)
    key = ("192.168.88.10", 50000, "1.1.1.1", 443)
    for i in range(MAX_PARTS + 5):
        ex._feed_tcp("192.168.88.10", "1.1.1.1", hdr(1000 + 100 * (i + 2), b"x"), 0)
    assert key not in ex._tcp                         # 段太多：放弃这条重组


def test_ech_outer_name_and_long_names_not_recorded():
    e = _engine()
    e.add_dns_answer("192.168.88.10", "a" * 300 + ".com", [("1.2.3.5", 60)], [])
    assert e.dns.lookup("1.2.3.5") is None
    e.add_dns_answer("192.168.88.10", "discord.com", [("1.2.3.6", 60)], [])
    e.names.add_conn_only("192.168.88.10", 5555, "1.2.3.6", "cloudflare-ech.com")
    assert e.names.lookup("192.168.88.10", 1234, "1.2.3.6")[0] == "discord.com"   # 终端自己的 DNS 记录还在


def test_ipv6_extension_headers_skipped():
    hbh = bytes([17, 0]) + b"\x00" * 6                # 逐跳选项头 → UDP
    assert skip_v6_ext(hbh + b"\x00" * 8, 0, 0) == (17, 8)
    frag_later = bytes([17, 0, 0x00, 0x10]) + b"\x00" * 4   # 分片偏移 ≠ 0
    assert skip_v6_ext(frag_later, 0, 44) is None
