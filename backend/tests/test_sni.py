import json
import os
import time

from packets import client_hello, quic_initial, tcp_segment, tls_record, tzsp_dns, udp_datagram

from app.collector.tls import SniExtractor, ethernet_ip, tls_records_sni
from app.collector.tzsp import tzsp_payload
from app.engine import Engine

C, S = "192.168.88.20", "203.0.113.5"


def feed(x: SniExtractor, pkt: bytes):
    return x.feed(*ethernet_ip(tzsp_payload(pkt)))


def test_tls_clienthello_split_and_out_of_order():
    rec = tls_record(client_hello("api.bilibili.com", pad_before_sni=1400))
    a, b = rec[:1000], rec[1000:]
    x = SniExtractor()
    # 第二段先到，单独看不出是 TLS，忽略；第一段到了以后开始重组，再来第二段时得到结果
    assert feed(x, tcp_segment(C, S, 50001, 443, 1000 + len(a), b)) is None
    assert feed(x, tcp_segment(C, S, 50001, 443, 1000, a)) is None
    assert feed(x, tcp_segment(C, S, 50001, 443, 1000 + len(a), b)) == (C, 50001, S, 443, "api.bilibili.com", "tls")


def test_tls_real_python_clienthello():
    d = json.load(open(os.path.join(os.path.dirname(__file__), "fixtures", "handshakes.json")))
    assert tls_records_sni(bytes.fromhex(d["tls"])) == "www.bilibili.com"


def test_quic_real_aioquic_v1_v2():
    """aioquic（独立的 QUIC 实现）生成的真实 Initial 报文，v1 和 v2"""
    d = json.load(open(os.path.join(os.path.dirname(__file__), "fixtures", "handshakes.json")))
    for k in ("quic_00000001", "quic_6b3343cf"):
        x = SniExtractor()
        got = [feed(x, udp_datagram(C, S, 50002, 443, bytes.fromhex(h))) for h in d[k]]
        assert got[-1] == (C, 50002, S, 443, "rr3---sn-abc.googlevideo.com", "quic")


def test_quic_scattered_crypto_over_two_packets():
    """像 Chrome 一样：ClientHello 拆成乱序的 CRYPTO 帧，分在两个 Initial 包里"""
    ch = client_hello("v26.douyinvod.com", pad_before_sni=1500)
    dcid = bytes.fromhex("0011223344556677")
    p1 = quic_initial(dcid, [(900, ch[900:1300]), (0, ch[:900])], pn=0)
    p2 = quic_initial(dcid, [(1300, ch[1300:])], pn=1, version=1)
    x = SniExtractor()
    assert feed(x, udp_datagram(C, S, 50003, 443, p1)) is None
    assert feed(x, udp_datagram(C, S, 50003, 443, p2))[4] == "v26.douyinvod.com"


def test_garbage_is_ignored():
    x = SniExtractor()
    for p in (udp_datagram(C, S, 1, 443, b"\xc0" + b"\x00" * 50), udp_datagram(C, S, 1, 443, b"\xcf\x00\x00\x00\x01\x15" + b"x" * 30),
              tcp_segment(C, S, 1, 443, 0, b"\x16\x03\x01\x00\x05\x02\x00\x00\x01\x00"), tcp_segment(C, S, 1, 443, 0, b"GET / HTTP/1.1")):
        assert feed(x, p) is None


def _engine():
    e = Engine()
    e.set_lan("192.168.88.0/24")
    return e


def test_engine_sni_beats_shared_cdn_ip():
    """同一个 CDN IP 先后解析出两个网站：全网 IP 表只记得最后一个，有 SNI 的连接仍然认得准"""
    e = _engine()
    cdn = "198.51.100.7"
    e.on_tzsp(tzsp_dns("192.168.88.248", "www.bilibili.com", [cdn], server="223.5.5.5"))
    e.on_tzsp(tcp_segment("192.168.88.21", cdn, 40001, 443, 7, tls_record(client_hello("www.bilibili.com"))))
    e.on_tzsp(tzsp_dns("192.168.88.248", "www.douyin.com", [cdn], server="223.5.5.5"))
    now = time.time()
    with e.lock:
        a = e.add_flow(dict(src="192.168.88.21", dst=cdn, sport=40001, dport=443, proto=6, bytes=10), now)
        b = e.add_flow(dict(src=cdn, dst="192.168.88.21", sport=443, dport=40001, proto=6, bytes=10), now)
        other = e.add_flow(dict(src="192.168.88.22", dst=cdn, sport=40002, dport=443, proto=6, bytes=10), now)
    assert a[1] == b[1] == "bilibili" and other[1] == "douyin"
    assert e.stats["sni_tls"] == 1 and e.stats["match"]["conn"] == 20 and e.stats["match"]["ip"] == 10


def test_engine_dns_answer_per_client():
    """终端直接查询（应答发给 LAN 地址）时按 (终端, IP) 记录"""
    e = _engine()
    ip = "198.51.100.8"
    e.on_tzsp(tzsp_dns("192.168.88.30", "music.163.com", [ip]))
    e.on_tzsp(tzsp_dns("192.168.88.31", "www.163.com", [ip]))
    with e.lock:
        r30 = e.add_flow(dict(src="192.168.88.30", dst=ip, sport=1, dport=443, proto=6, bytes=5), time.time())
        r31 = e.add_flow(dict(src="192.168.88.31", dst=ip, sport=2, dport=443, proto=6, bytes=5), time.time())
    assert r30[1] == "netease_music" and r31[1] == "netease"
