"""私接路由 / 共享上网检测（参照深信服 AC 的“防共享上网”，只用镜像包里的 IP TTL 做被动判断）。

系统发出的包 TTL 初始值一般是 64（Linux、安卓、苹果）、128（Windows）或 255。每经过一个路由器减 1。
ROS-DPI 看到的是路由器镜像过来的包（forward 链，路由器自己已减过 1），所以正常设备一般是 63 / 127。
- 某台“设备”的包比全网常见的跳数还多一跳：它后面很可能接了路由器（私接路由、随身 WiFi、软路由）。
- 同一台“设备”同时出现两种系统的 TTL：后面可能有多台不同系统的设备在共享。
只作为提示：样本是 HTTPS / QUIC 握手和 DNS 之外的首包，数量有限；VPN、虚拟机、容器也可能造成同样的现象。
"""
from collections import Counter

BASES = (64, 128, 255)
MIN_PACKETS = 5


def hops(ttl: int) -> tuple[int, int]:
    """(初始值, 已经过的跳数)"""
    base = next(b for b in BASES if b >= ttl)
    return base, base - ttl


def suspects(ttl_by_host: dict[str, Counter]) -> tuple[int, list[dict]]:
    """返回 (全网常见跳数, 可疑终端列表)"""
    usual = Counter()
    for c in ttl_by_host.values():
        if sum(c.values()) >= MIN_PACKETS:
            usual[hops(c.most_common(1)[0][0])[1]] += 1
    base_hops = usual.most_common(1)[0][0] if usual else 1
    out = []
    for host, c in ttl_by_host.items():
        n = sum(c.values())
        if n < MIN_PACKETS:
            continue
        by_os: Counter = Counter()
        extra = 0
        for ttl, k in c.items():
            b, h = hops(ttl)
            by_os[b] += k
            if h > base_hops:
                extra += k
        reasons = []
        if extra >= max(3, n * 0.3):
            reasons.append("extra_hop")
        if sum(1 for b, k in by_os.items() if k >= 3 and k >= n * 0.1) >= 2:
            reasons.append("multi_os")
        if reasons:
            out.append({"host": host, "packets": n, "ttls": dict(c.most_common(6)), "reasons": reasons,
                        "extra_share": extra / n, "os": sorted(b for b, k in by_os.items() if k >= 3)})
    out.sort(key=lambda x: (-len(x["reasons"]), -x["extra_share"]))
    return base_hops, out
