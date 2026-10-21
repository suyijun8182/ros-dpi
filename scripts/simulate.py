"""向本机 ROS-DPI 发送模拟的 DNS 应答（TZSP）和 IPFIX 流量，用于开发调试和演示。

用法：python scripts/simulate.py [--host 127.0.0.1] [--minutes 5] [--hosts 14]
需在 backend/.venv 环境下运行（借用 tests/packets.py 的构包函数）。
"""
import argparse
import os
import random
import socket
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "tests"))
from packets import ipfix, tzsp_dns  # noqa: E402

# (域名, 典型下行 MB/分钟, 上行比例)
SITES = [
    ("v26.douyinvod.com", 60, .03), ("upos-sz-mirrorcos.bilivideo.com", 80, .02), ("api.bilibili.com", 2, .2),
    ("szshort.weixin.qq.com", 3, .4), ("mmbiz.qpic.cn", 6, .05), ("rr3---sn.googlevideo.com", 90, .02),
    ("steamcdn-a.akamaihd.net.steamcontent.com", 120, .01), ("music.163.com", 4, .05),
    ("chatgpt.com", 1.5, .3), ("claude.ai", 1.2, .35), ("github.com", 3, .1), ("swcdn.apple.com", 70, .01),
    ("dl.delivery.mp.microsoft.com", 50, .01), ("pan.baidu.com", 30, .3), ("www.taobao.com", 5, .08),
    ("img.alicdn.com", 8, .03), ("www.zhihu.com", 3, .08), ("xiaohongshu.com", 9, .05),
    ("cdn.example-unknown.net", 6, .1), ("static.some-cdn.io", 4, .1), ("io.mi.com", .2, .5),
    ("tuyacn.com", .1, .5), ("www.netflix.com", 2, .05), ("ipv4-c001.nflxvideo.net", 70, .01),
]
DEVICES = ["iPhone", "MacBook", "iPad", "小米电视", "Win 台式机", "Switch", "安卓手机", "NAS", "摄像头", "扫地机"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--ipfix-port", type=int, default=2055)
    ap.add_argument("--tzsp-port", type=int, default=37008)
    ap.add_argument("--minutes", type=float, default=3)
    ap.add_argument("--hosts", type=int, default=14)
    ap.add_argument("--fast", action="store_true", help="不等待，一次性发完")
    a = ap.parse_args()

    rnd = random.Random(42)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    ips = {d: f"203.0.113.{i + 10}" for i, (d, *_x) in enumerate(SITES)}
    hosts = [(f"192.168.88.{100 + i}", f"AA:BB:CC:00:00:{i:02X}") for i in range(a.hosts)]
    # 每台终端偏好几个站点
    prefs = {ip: rnd.sample(SITES, k=rnd.randint(3, 8)) for ip, _ in hosts}

    for d, ip in ips.items():
        sock.sendto(tzsp_dns(hosts[0][0], d, [ip]), (a.host, a.tzsp_port))
    print(f"已发送 {len(ips)} 条 DNS 应答")

    end = time.time() + a.minutes * 60
    rounds = 0
    while True:
        flows = []
        for ip, mac in hosts:
            for d, mb, up_ratio in prefs[ip]:
                down = int(mb * 1024 * 1024 / 6 * rnd.uniform(.3, 1.6))  # 10 秒一轮
                up = int(down * up_ratio)
                port = 443
                flows.append(dict(src=ip, dst=ips[d], sport=rnd.randint(30000, 60000), dport=port, proto=6,
                                  nbytes=up, mac=mac))
                flows.append(dict(src=ips[d], dst=ip, sport=port, dport=rnd.randint(30000, 60000), proto=6,
                                  nbytes=down))
        for i in range(0, len(flows), 20):
            sock.sendto(ipfix(flows[i:i + 20], seq=rounds), (a.host, a.ipfix_port))
        rounds += 1
        if a.fast and rounds >= a.minutes * 6 or not a.fast and time.time() > end:
            break
        if not a.fast:
            time.sleep(10)
    print(f"已发送 {rounds} 轮流量，共 {len(hosts)} 台终端")
    print("终端建议备注名：", ", ".join(DEVICES))


if __name__ == "__main__":
    main()
