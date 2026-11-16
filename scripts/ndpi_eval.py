"""用 nDPI 对照 ROS-DPI 的识别结果（0.6.29 技术验证）。

输入：ROS-DPI 识别规则页「抓包采样」下载的同名三个文件（.pcap / .labels.csv / .json）。
输出：Markdown 报告——ROS-DPI 认成笼统分类（HTTPS / 国内网络 / 未识别 …）的流量，nDPI 能认出多少、认成什么；
      两边都认出来的，结论对照表（供人工判断谁对）。

依赖：nfstream（内含 nDPI，LGPL-3.0）。不进 ROS-DPI 的 requirements，只在跑这个脚本的环境里装：
    python -m venv ndpi-venv && ndpi-venv/bin/pip install nfstream
Windows 需要先装 Npcap（https://npcap.com/）。Linux x86_64 / arm64 直接可用。

用法：
    python ndpi_eval.py data/captures/capture-20261116-101500        # 不带扩展名
    python ndpi_eval.py <前缀> --csv detail.csv                       # 另存逐条连接明细
"""
import argparse
import csv
import ipaddress
import json
import os
import sys
from collections import defaultdict

# nDPI 的这些结论只说明了协议，没说出具体应用：和 ROS-DPI 的“笼统”是一个意思
NDPI_GENERIC = {"unknown", "tls", "quic", "http", "dns", "icmp", "icmpv6", "ntp", "dtls", "http_proxy", "ipv6", "ip"}
TOP = 25


def ndpi_specific(name: str) -> bool:
    """nDPI 的应用名形如 TLS.YouTube、QUIC、BitTorrent；最后一段不是纯协议名才算认出了具体应用"""
    if not name:
        return False
    return any(p.lower() not in NDPI_GENERIC for p in name.split("."))


def load_labels(path: str) -> dict[tuple, dict]:
    out = {}
    with open(path, encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            k = (r["client_ip"], int(r["client_port"]), r["remote_ip"], int(r["remote_port"]), int(r["proto"]))
            r["bytes"] = int(r["up"] or 0) + int(r["down"] or 0)
            r["vague"] = r.get("vague") == "1"
            out[k] = r
    return out


def nfstream_flows(pcap: str):
    from nfstream import NFStreamer   # 延迟导入：没装 nfstream 时 --help 和单元测试照样能用
    for fl in NFStreamer(source=pcap, statistical_analysis=False, n_dissections=20):
        yield {"src_ip": fl.src_ip, "src_port": fl.src_port, "dst_ip": fl.dst_ip, "dst_port": fl.dst_port,
               "proto": fl.protocol, "bytes": fl.bidirectional_bytes, "app": fl.application_name or "Unknown",
               "category": fl.application_category_name or "", "sni": fl.requested_server_name or ""}


def join(flows, labels: dict[tuple, dict], lan) -> list[dict]:
    """每条 nDPI 流找对应的 ROS-DPI 连接：先按发起方，再按反方向（镜像可能先看到回包）"""
    rows = []
    for fl in flows:
        a = (fl["src_ip"], fl["src_port"], fl["dst_ip"], fl["dst_port"], fl["proto"])
        b = (fl["dst_ip"], fl["dst_port"], fl["src_ip"], fl["src_port"], fl["proto"])
        lab = labels.get(a)
        if lab is None and b in labels:
            lab, a = labels[b], b      # 按反方向对上：以 ROS-DPI 记的终端一侧为准
        if lab is None and lan:
            # 没有对上：用内网网段判断哪边是终端，方便看是哪台机器
            try:
                src_lan = any(ipaddress.ip_address(fl["src_ip"]) in n for n in lan)
            except ValueError:
                src_lan = True
            if not src_lan:
                a = b
        rows.append({"client_ip": a[0], "client_port": a[1], "remote_ip": a[2], "remote_port": a[3], "proto": a[4],
                     "ndpi_app": fl["app"], "ndpi_category": fl["category"], "ndpi_sni": fl["sni"],
                     "ndpi_specific": ndpi_specific(fl["app"]),
                     "ros_app": lab["app"] if lab else None, "ros_domain": lab["domain"] if lab else "",
                     "ros_vague": lab["vague"] if lab else None,
                     # 权重：pcap 里只有每条连接开头几 KB，ROS-DPI 记下的整条连接字节数更能代表分量
                     "weight": lab["bytes"] if lab and lab["bytes"] else fl["bytes"]})
    return rows


def report(rows: list[dict], meta: dict | None = None) -> str:
    out = []
    w = out.append
    matched = [r for r in rows if r["ros_app"] is not None]
    vague = [r for r in matched if r["ros_vague"]]
    specific = [r for r in matched if not r["ros_vague"]]
    tot = sum(r["weight"] for r in matched) or 1
    vtot = sum(r["weight"] for r in vague)
    vhit = sum(r["weight"] for r in vague if r["ndpi_specific"])

    w("# nDPI 对照报告")
    if meta:
        w(f"\n采样：{meta.get('name')}，{meta.get('packets', 0):,} 个包，ROS-DPI 实时表连接 {meta.get('connections', 0):,} 条")
    w(f"\n- nDPI 看到的流：{len(rows):,}；对上 ROS-DPI 连接的：{len(matched):,}（没对上的多半是只有 DNS、或连接没经过流量统计）")
    w(f"- 对上的流量里，ROS-DPI 只认到笼统分类的：{vtot / tot:.1%}")
    w(f"- **其中 nDPI 能说出具体应用的：{vhit / max(vtot, 1):.1%}**（按 ROS-DPI 记的整条连接字节数加权）")

    def table(title, items, cols):
        w(f"\n## {title}\n")
        w("| " + " | ".join(c[0] for c in cols) + " |")
        w("|" + "---|" * len(cols))
        for it in items:
            w("| " + " | ".join(str(c[1](it)) for c in cols) + " |")

    agg = defaultdict(lambda: [0, 0, set()])
    for r in vague:
        x = agg[(r["ndpi_app"], r["ndpi_category"])]
        x[0] += r["weight"]
        x[1] += 1
        x[2].add(r["ros_app"])
    top = sorted(agg.items(), key=lambda kv: -kv[1][0])[:TOP]
    table("ROS-DPI 认成笼统分类的流量，nDPI 认成了什么", top,
          [("nDPI 应用", lambda kv: kv[0][0]), ("nDPI 类别", lambda kv: kv[0][1]),
           ("占这部分流量", lambda kv: f"{kv[1][0] / max(vtot, 1):.1%}"), ("连接数", lambda kv: kv[1][1]),
           ("ROS-DPI 原结论", lambda kv: "、".join(sorted(kv[1][2]))[:60])])

    pairs = defaultdict(lambda: [0, 0])
    for r in specific:
        if r["ndpi_specific"]:
            p = pairs[(r["ros_app"], r["ndpi_app"])]
            p[0] += r["weight"]
            p[1] += 1
    stot = sum(v[0] for v in pairs.values()) or 1
    table("两边都认出具体应用的：结论对照（人工判断名字是否指同一个应用）",
          sorted(pairs.items(), key=lambda kv: -kv[1][0])[:TOP],
          [("ROS-DPI", lambda kv: kv[0][0]), ("nDPI", lambda kv: kv[0][1]),
           ("占比", lambda kv: f"{kv[1][0] / stot:.1%}"), ("连接数", lambda kv: kv[1][1])])

    ports = defaultdict(int)
    for r in vague:
        if not r["ndpi_specific"]:
            ports[(r["proto"], r["remote_port"])] += r["weight"]
    table("两边都没认出来的：按远端端口", sorted(ports.items(), key=lambda kv: -kv[1])[:15],
          [("协议/端口", lambda kv: f"{'tcp' if kv[0][0] == 6 else 'udp' if kv[0][0] == 17 else kv[0][0]}/{kv[0][1]}"),
           ("占笼统流量", lambda kv: f"{kv[1] / max(vtot, 1):.1%}")])
    return "\n".join(out) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("prefix", help="采样文件路径前缀（不带 .pcap）")
    ap.add_argument("--csv", help="另存逐条连接明细")
    args = ap.parse_args(argv)
    meta = None
    if os.path.isfile(args.prefix + ".json"):
        with open(args.prefix + ".json", encoding="utf-8") as f:
            meta = json.load(f)
    lan = [ipaddress.ip_network(n) for n in (meta or {}).get("lan", [])]
    rows = join(nfstream_flows(args.prefix + ".pcap"), load_labels(args.prefix + ".labels.csv"), lan)
    if args.csv:
        with open(args.csv, "w", newline="", encoding="utf-8-sig") as f:
            wr = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ["empty"])
            wr.writeheader()
            wr.writerows(rows)
    sys.stdout.write(report(rows, meta))


if __name__ == "__main__":
    main()
