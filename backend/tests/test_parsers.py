from packets import dns_response, ipfix, netflow9, tzsp_dns

from app.collector.ipfix import FlowDecoder
from app.collector.tzsp import parse_dns_response, parse_tzsp_dns

F1 = dict(src="192.168.88.10", dst="1.2.3.4", sport=50000, dport=443, proto=6, nbytes=1500,
          mac="AA:BB:CC:00:00:01")


def test_ipfix_template_and_data():
    d = FlowDecoder()
    recs = d.decode(ipfix([F1]), "10.0.0.1")
    assert len(recs) == 1
    r = recs[0]
    assert (r["src"], r["dst"], r["sport"], r["dport"], r["proto"], r["bytes"]) == \
        ("192.168.88.10", "1.2.3.4", 50000, 443, 6, 1500)
    assert r["src_mac"] == "AA:BB:CC:00:00:01"
    assert r["post_dst"] == "0.0.0.0"


def test_ipfix_data_before_template_is_dropped_then_decoded():
    d = FlowDecoder()
    assert d.decode(ipfix([F1], with_template=False), "x") == []
    assert d.stats["no_template"] == 1
    d.decode(ipfix(with_template=True), "x")
    assert len(d.decode(ipfix([F1, F1], with_template=False), "x")) == 2


def test_templates_are_per_exporter():
    d = FlowDecoder()
    d.decode(ipfix(), "a")
    assert d.decode(ipfix([F1], with_template=False), "b") == []


def test_ipfix_ipv6():
    d = FlowDecoder()
    recs = d.decode(ipfix(flows_v6=[dict(src="2408:8000:1:2::10", dst="2400:3200::1", sport=1, dport=443,
                                         proto=17, nbytes=99)]), "x")
    assert recs[0]["src"] == "2408:8000:1:2::10" and recs[0]["bytes"] == 99


def test_netflow_v9():
    d = FlowDecoder()
    recs = d.decode(netflow9([F1]), "x")
    assert len(recs) == 1 and recs[0]["dst"] == "1.2.3.4"


def test_garbage_does_not_raise():
    d = FlowDecoder()
    for junk in (b"", b"\x00\x0a", b"\x00\x0a\x00\x20" + b"\xff" * 40, b"\x00\x05" + b"\x00" * 30):
        assert d.decode(junk, "x") == []


def test_dns_response_with_cname():
    msg = dns_response("www.douyin.com", ["1.1.1.1", "2400::1"], cnames=["www.douyin.com.w.cdngslb.com"])
    qname, ips, cnames = parse_dns_response(msg)
    assert qname == "www.douyin.com"
    assert [ip for ip, _ in ips] == ["1.1.1.1", "2400::1"]
    assert cnames == ["www.douyin.com.w.cdngslb.com"]


def test_tzsp_dns_and_vlan():
    for vlan in (None, 20):
        ans = parse_tzsp_dns(tzsp_dns("192.168.88.10", "api.bilibili.com", ["5.5.5.5"], vlan=vlan))
        assert ans.client == "192.168.88.10"
        assert ans.qname == "api.bilibili.com"
        assert ans.ips[0][0] == "5.5.5.5"


def test_tzsp_ignores_non_dns():
    assert parse_tzsp_dns(b"\x01\x00\x00\x01\x01" + b"\x00" * 10) is None
    assert parse_tzsp_dns(b"garbage") is None
