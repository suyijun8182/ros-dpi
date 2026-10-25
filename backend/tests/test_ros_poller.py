import httpx
from fastapi.testclient import TestClient

from app.config import get_settings
from app.engine import engine
from app.main import app
from app.ros_poller import poller

# 模拟 RouterOS 7 REST 接口的返回（字段值都是字符串，与真实设备一致）
ROS = {
    "/rest/system/identity": {"name": "MikroTik-Home"},
    "/rest/system/resource": {"version": "7.23beta", "board-name": "RB5009", "uptime": "3d2h", "cpu-load": "7",
                              "total-memory": "1073741824", "free-memory": "805306368"},
    "/rest/interface": [{"name": "ether1", "type": "ether", "running": "true", "rx-byte": "1000", "tx-byte": "500"},
                        {"name": "bridge", "type": "bridge", "running": "true", "rx-byte": "10", "tx-byte": "20"}],
    "/rest/ip/arp": [{"address": "192.168.88.30", "mac-address": "aa:bb:cc:dd:ee:30"}],
    "/rest/ip/dhcp-server/lease": [{"address": "192.168.88.31", "mac-address": "AA:BB:CC:DD:EE:31",
                                    "host-name": "iPhone", "comment": "小明的手机"}],
    "/rest/ip/address": [{"address": "192.168.88.1/24", "interface": "bridge"},
                         {"address": "100.64.1.2/24", "interface": "ether1"}],
    "/rest/ip/route": [{"dst-address": "0.0.0.0/0", "gateway": "100.64.1.1", "immediate-gw": "100.64.1.1%ether1",
                        "active": "true"},
                       # 策略路由：把部分流量导给旁路由 sing-box，出口是 LAN 网桥，不能算 WAN（debug9）
                       {"dst-address": "0.0.0.0/0", "gateway": "192.168.88.249", "immediate-gw": "192.168.88.249%bridge",
                        "routing-table": "sing-box-v4", "active": "true"}],
    "/rest/ipv6/neighbor": [{"address": "2408:8000:aa:bb::30", "mac-address": "AA:BB:CC:DD:EE:30"}],
    "/rest/ipv6/address": [{"address": "2408:8000:aa:bb::1/64", "interface": "bridge"},
                           {"address": "fe80::1/64", "interface": "bridge"}],
    "/rest/ip/pool": [{"name": "dhcp_pool0", "ranges": "192.168.88.10-192.168.88.19,192.168.88.100/30"}],
    "/rest/ip/dhcp-server": [{"name": "defconf", "interface": "bridge", "address-pool": "dhcp_pool0"}],
    "/rest/ip/dhcp-client": [{"interface": "ether1", "status": "bound"}],
    # 接入自检：DNS 规则正常；SNI 规则端口填错（真实遇到过：37880）
    "/rest/ip/firewall/mangle": [
        {".id": "*7", "action": "sniff-tzsp", "chain": "forward", "protocol": "udp", "src-port": "53",
         "sniff-target": "192.168.88.10", "sniff-target-port": "37008", "packets": "100", "disabled": "false", "comment": "ROSDPI-DNS"},
        {".id": "*9", "action": "sniff-tzsp", "chain": "forward", "protocol": "tcp", "dst-port": "443",
         "sniff-target": "192.168.88.10", "sniff-target-port": "37880", "packets": "1964", "disabled": "false", "comment": "ROSDPI-SNI"}],
    "/rest/ip/settings": {"ipv4-fasttrack-active": "false"},
}


def _use_mock(monkeypatch, status=200):
    def handler(req: httpx.Request):
        if status != 200:
            return httpx.Response(status, json={"error": status})
        body = ROS.get(req.url.path)
        return httpx.Response(200, json=body) if body is not None else httpx.Response(404, json={})

    monkeypatch.setattr(get_settings(), "ros_url", "https://192.168.88.1")
    monkeypatch.setattr(poller, "_client",
                        lambda: httpx.Client(base_url="https://192.168.88.1/rest", transport=httpx.MockTransport(handler)))


def test_poll_success_populates_router_state(monkeypatch):
    _use_mock(monkeypatch)
    monkeypatch.setitem(engine.stats, "dns_answers", 5)  # DNS 规则在正常工作，自检以它的端口为准
    poller.poll()
    st = poller.status()
    assert st["ok"] and st["error"] == ""
    assert st["identity"] == "MikroTik-Home" and st["version"] == "7.23beta" and st["cpu_load"] == 7
    assert st["wan_interface"] == "ether1"
    assert engine.ip2mac["192.168.88.30"] == "AA:BB:CC:DD:EE:30"
    assert engine.mac2name["AA:BB:CC:DD:EE:31"] == "小明的手机"
    nets = {str(n) for n in engine.auto_nets}
    assert "2408:8000:aa:bb::/64" in nets and "100.64.1.0/24" not in nets  # WAN 口的地址段不算 LAN
    assert engine.is_lan("2408:8000:aa:bb::30")
    # 全网状态：WAN 线路；DHCP 地址池容量 = 10 + 4，已用 = 1 条租约
    assert [w["name"] for w in poller.wans] == ["ether1"]
    assert poller.wans[0]["name"] == "ether1" and poller.wans[0]["type"] == "dhcp" and poller.wans[0]["ip"] == "100.64.1.2"
    assert poller.pools == [{"server": "defconf", "interface": "bridge", "pool": "dhcp_pool0", "size": 14, "used": 1}]
    # 实时流量采样：两次采样之间 WAN 口计数增加，得到速率点
    poller.samples.clear(); poller._sample_prev.clear()
    poller.sample()
    ROS["/rest/interface"][0]["rx-byte"] = "1001000"
    poller._sample_prev["ether1"] = (poller._sample_prev["ether1"][0] - 2, 1000, 500)
    poller.sample()
    assert len(poller.samples) == 1 and poller.samples[0][2] > 0

    # 配置了 ROS 后，概览页能正常返回路由器信息（此前这里会 500）
    with TestClient(app) as c:
        if not c.get("/api/auth/status").json()["initialized"]:
            c.post("/api/auth/setup", json={"username": "admin", "password": "secret1"})
        tok = c.post("/api/auth/login", json={"username": "admin", "password": "secret1"}).json()["token"]
        r = c.get("/api/overview", headers={"Authorization": f"Bearer {tok}"})
        assert r.status_code == 200 and r.json()["router"]["identity"] == "MikroTik-Home"
        ov = r.json()
        assert ov["wans"][0]["running"] and ov["pools"][0]["size"] == 14
        codes = {i["code"]: i for i in ov["health"]["items"]}
        assert codes["wan"]["ok"] and codes["cpu"]["ok"] and 0 <= ov["health"]["score"] <= 100
        chk = c.get("/api/system", headers={"Authorization": f"Bearer {tok}"}).json()["ros_check"]
        sni = next(x for x in chk["rules"] if x["kind"] == "sni")
        assert chk["checked"] and sni["problems"] == ["port"] and sni["target_port"] == 37880
        # SNI 规则存在、只是端口错：建议改端口，不建议重复新增；但缺 UDP（QUIC）规则
        assert "rule_problem" in chk["issues"] and "no_sni" not in chk["issues"] and "no_quic" in chk["issues"]
        # 路由器有 IPv6 公网地址，嗅探规则却只有 IPv4 的一份
        assert "no_ipv6" in chk["issues"] and "fasttrack" not in chk["issues"]
        assert not codes["rules"]["ok"] and codes["rules"]["params"]["wrong"] == [37880]
        leases = c.get("/api/dhcp/leases", headers={"Authorization": f"Bearer {tok}"}).json()
        assert leases["leases"][0]["mac"] == "AA:BB:CC:DD:EE:31" and leases["leases"][0]["host_name"] == "iPhone"

def test_fasttrack_check_respects_connection_bytes(monkeypatch):
    """FastTrack 开着：规则没限定 connection-bytes 要提示；已经限定（连接开头不走 FastTrack）就不再提示"""
    _use_mock(monkeypatch)
    monkeypatch.setitem(engine.stats, "dns_answers", 5)
    monkeypatch.setitem(ROS, "/rest/ip/settings", {"ipv4-fasttrack-active": "true"})
    rule = {".id": "*2", "action": "fasttrack-connection", "chain": "forward",
            "connection-state": "established,related", "disabled": "false"}
    monkeypatch.setitem(ROS, "/rest/ip/firewall/filter", [rule])
    poller.poll()
    assert "fasttrack" in poller.check()["issues"]
    monkeypatch.setitem(ROS, "/rest/ip/firewall/filter", [{**rule, "connection-bytes": "10000-0"}])
    poller.poll()
    chk = poller.check()
    assert "fasttrack" not in chk["issues"] and chk["fasttrack_limited"]
    # IPv6 的 FastTrack 规则同样要限定 connection-bytes
    rule6 = {".id": "*3", "action": "fasttrack-connection", "chain": "forward", "disabled": "false"}
    monkeypatch.setitem(ROS, "/rest/ipv6/firewall/filter", [rule6])
    poller.poll()
    assert "fasttrack6" in poller.check()["issues"]
    monkeypatch.setitem(ROS, "/rest/ipv6/firewall/filter", [{**rule6, "connection-bytes": "10000-0"}])
    poller.poll()
    assert "fasttrack6" not in poller.check()["issues"]
    # 读不到 filter 表（只读账号没权限）：按旧办法提示
    monkeypatch.delitem(ROS, "/rest/ip/firewall/filter")
    poller.poll()
    assert "fasttrack" in poller.check()["issues"]


def test_poll_401_gives_actionable_error_and_keeps_status_usable(monkeypatch):
    _use_mock(monkeypatch, status=401)
    poller.poll()
    st = poller.status()
    assert not st["ok"] and "401" in st["error"] and "ROS_USER" in st["error"]
