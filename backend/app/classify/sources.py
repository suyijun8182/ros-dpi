"""补充识别库：国内域名列表与官方发布的 IP 段，只做兜底——
域名规则 / 自定义规则 / ASN 能认出来的流量不走这里，因此永远不会让已有识别变差。

- 国内域名：felixonmars/dnsmasq-china-list 的 accelerated-domains.china.conf（约 8 万条，WTFPL）。
  知道域名但规则库没有的流量，域名在列表里就归「国内网站」。
- 官方 IP 段：Google（goog.json）、Cloudflare（ips-v4/v6）、AWS（ip-ranges.json）、
  GitHub（api.github.com/meta）官方发布的数据，加上 IANA 注册给 Apple 的 17.0.0.0/8。
  完全没有域名的流量（加密 DNS、ECH、直连 IP）按 IP 段认出归属。
- 国内 IP 段：misakaio/chnroutes2（CC-BY-SA 4.0，来自 APNIC），归「国内网络」。

都是运行时下载到数据目录（不进镜像）、每天检查一次更新；单个来源失败不影响其它来源。
环境变量 CHINA_DB / IPLIST_DB 可分别关闭（默认开）。
"""
import heapq
import ipaddress
import json
import os
import threading
import time
from array import array
from bisect import bisect_right

import httpx

MAX_AGE = 24 * 3600
CN_WEB = "cn_web"   # 国内网站（域名在国内域名列表里）
CN_NET = "cn_net"   # 国内网络（IP 在国内段里，但没有域名）


def _parse_china(text: str) -> set[str]:
    """dnsmasq 格式：server=/domain/114.114.114.114"""
    out = set()
    for line in text.splitlines():
        if line.startswith("server=/"):
            parts = line.split("/")
            if len(parts) >= 3 and parts[1]:
                out.add(parts[1].lower().strip("."))
    return out


def _parse_cidrs(text: str) -> list[str]:
    out = []
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            out.append(line)
    return out


def _parse_goog(text: str) -> list[str]:
    return [p[k] for p in json.loads(text).get("prefixes", []) for k in ("ipv4Prefix", "ipv6Prefix") if k in p]


def _parse_aws(text: str) -> list[str]:
    d = json.loads(text)
    return ([p["ip_prefix"] for p in d.get("prefixes", [])]
            + [p["ipv6_prefix"] for p in d.get("ipv6_prefixes", [])])


def _parse_github(text: str) -> list[str]:
    d = json.loads(text)
    return [c for k in ("git", "hooks", "pages", "web", "importers", "actions") for c in d.get(k, [])]


class _Ranges:
    """CIDR → 不重叠的排序区间数组（bisect 查找）。

    段之间会重叠（AWS 中国区的段落在 chnroutes 的大段里、GitHub 的段落在 AWS 段里），
    和路由表一样按最长前缀匹配：更小（更具体）的段赢，一样大时先加入的赢。
    """

    def __init__(self):
        self._v4 = (array("Q"), array("Q"), [])
        self._v6 = ([], [], [])
        self._raw = {4: [], 6: []}
        self.count = 0

    def add(self, cidr: str, app: str):
        try:
            net = ipaddress.ip_network(cidr, strict=False)
        except ValueError:
            return False
        raw = self._raw[net.version]
        raw.append((int(net.network_address), int(net.broadcast_address), net.num_addresses, len(raw), app))
        self.count += 1
        return True

    @staticmethod
    def _flatten(raw: list) -> list[tuple[int, int, str]]:
        """扫描线：在每个边界点之间取覆盖它的优先级最高的段，再合并相邻同归属的区间。"""
        cuts = sorted({x for lo, hi, *_ in raw for x in (lo, hi + 1)})
        by_lo = sorted(raw)
        heap, out, j = [], [], 0
        for a, b in zip(cuts, cuts[1:]):
            while j < len(by_lo) and by_lo[j][0] <= a:
                lo, hi, size, idx, app = by_lo[j]
                heapq.heappush(heap, (size, idx, hi, app))
                j += 1
            while heap and heap[0][2] < a:
                heapq.heappop(heap)
            if not heap:
                continue
            app = heap[0][3]
            if out and out[-1][2] == app and out[-1][1] == a - 1:
                out[-1] = (out[-1][0], b - 1, app)
            else:
                out.append((a, b - 1, app))
        return out

    def build(self):
        for ver, t in ((4, self._v4), (6, self._v6)):
            segs = self._flatten(self._raw[ver])
            if ver == 4:  # v4 用 array("Q") 省内存
                t[0][:], t[1][:] = array("Q", [s[0] for s in segs]), array("Q", [s[1] for s in segs])
            else:
                t[0][:], t[1][:] = [s[0] for s in segs], [s[1] for s in segs]
            t[2][:] = [s[2] for s in segs]
        self._raw = {4: [], 6: []}

    def lookup(self, ip: str) -> str | None:
        try:
            a = ipaddress.ip_address(ip)
        except ValueError:
            return None
        t = self._v4 if a.version == 4 else self._v6
        if not t[0]:
            return None
        x = int(a)
        i = bisect_right(t[0], x) - 1
        return t[2][i] if i >= 0 and x <= t[1][i] else None


# 来源清单：文件名、下载地址（Cloudflare 两个地址合并成一个文件）、解析器、归类
SPECS = [
    ("cnlist", "china-domains.conf", ["https://raw.githubusercontent.com/felixonmars/dnsmasq-china-list/master/accelerated-domains.china.conf"], _parse_china, CN_WEB),
    ("google", "ip-google.json", ["https://www.gstatic.com/ipranges/goog.json"], _parse_goog, "google"),
    ("cloudflare", "ip-cloudflare.txt", ["https://www.cloudflare.com/ips-v4", "https://www.cloudflare.com/ips-v6"], _parse_cidrs, "cloudflare"),
    ("aws", "ip-aws.json", ["https://ip-ranges.amazonaws.com/ip-ranges.json"], _parse_aws, "aws"),
    ("github", "ip-github.json", ["https://api.github.com/meta"], _parse_github, "github"),
    ("cn", "ip-cn.txt", ["https://raw.githubusercontent.com/misakaio/chnroutes2/master/chnroutes.txt"], _parse_cidrs, CN_NET),
]
APPLE_NETS = ("17.0.0.0/8",)  # IANA 把整个 17/8 注册给了 Apple（官方数据，不用下载）

# 识别库面板里显示的许可证与出处
META = {
    "cnlist": ("WTFPL", "https://github.com/felixonmars/dnsmasq-china-list"),
    "google": ("官方公开数据", "https://www.gstatic.com/ipranges/goog.json"),
    "cloudflare": ("官方公开数据", "https://www.cloudflare.com/ips/"),
    "aws": ("官方公开数据", "https://ip-ranges.amazonaws.com/ip-ranges.json"),
    "github": ("官方公开数据", "https://api.github.com/meta"),
    "cn": ("CC-BY-SA 4.0", "https://github.com/misakaio/chnroutes2"),
}


def _enabled(sid: str) -> bool:
    from app.config import get_settings
    s = get_settings()
    return s.china_db if sid in ("cnlist", "cn") else s.iplist_db


class Sources:
    def __init__(self):
        self.lock = threading.Lock()
        self.china: set[str] = set()
        self.ips = _Ranges()
        self.state: dict[str, dict] = {}   # 来源 id -> {count, updated, error}
        self.version = 0                   # 每次重新加载 +1，分类器据此清掉缓存

    def _data_dir(self) -> str:
        return os.environ.get("DATA_DIR", "data")

    # ---------- 加载 ----------
    def load(self):
        """从数据目录读已下载的文件（没有就空着）；单个文件坏了不影响其它来源。"""
        china: set[str] = set()
        ips = _Ranges()
        state: dict[str, dict] = {}
        for sid, fname, _urls, parse, app in SPECS:
            if not _enabled(sid):
                continue
            path = os.path.join(self._data_dir(), fname)
            try:
                with open(path, encoding="utf-8", errors="replace") as f:
                    text = f.read()
                st = {"count": 0, "updated": int(os.path.getmtime(path)), "error": ""}
            except OSError:
                continue
            try:
                data = parse(text)
            except (ValueError, KeyError, TypeError) as e:
                state[sid] = {**st, "count": self.state.get(sid, {}).get("count", 0),
                              "error": f"解析失败：{type(e).__name__}"}
                continue
            n = 0
            if sid == "cnlist":
                china = set(data)
                n = len(china)
            else:
                for cidr in data:
                    n += 1 if ips.add(cidr, app) else 0
            state[sid] = {**st, "count": n}
        if _enabled("google"):
            for cidr in APPLE_NETS:
                ips.add(cidr, "apple")
        ips.build()
        with self.lock:
            self.china, self.ips, self.state = china, ips, state
            self.version += 1

    # ---------- 更新 ----------
    def update(self, force: bool = False) -> bool:
        """文件缺失或超过一天就重新下载；返回是否下载到了新文件。"""
        changed = False
        for sid, fname, urls, _parse, _app in SPECS:
            if not _enabled(sid):
                continue
            path = os.path.join(self._data_dir(), fname)
            if not force and os.path.exists(path) and time.time() - os.path.getmtime(path) < MAX_AGE:
                continue
            if self._fetch(path, urls, sid):
                changed = True
        if changed or not self.state:
            self.load()
        return changed

    def _fetch(self, path: str, urls: list[str], sid: str) -> bool:
        tmp = path + ".part"
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(tmp, "wb") as f:
                for u in urls:  # Cloudflare 的 v4 / v6 分两个地址，合并写进同一个文件
                    with httpx.stream("GET", u, timeout=120, follow_redirects=True) as r:
                        r.raise_for_status()
                        for chunk in r.iter_bytes(1 << 16):
                            f.write(chunk)
                        f.write(b"\n")
            os.replace(tmp, path)
            self.state[sid] = {**self.state.get(sid, {}), "error": ""}
            return True
        except Exception as e:  # noqa: BLE001  没有外网时保留旧数据
            if os.path.exists(tmp):
                os.remove(tmp)
            self.state[sid] = {**self.state.get(sid, {}), "error": f"{type(e).__name__}: {str(e)[:160]}"}
            return False

    # ---------- 查询 ----------
    def fallback_domain(self, name: str | None) -> str | None:
        """域名不在任何规则里、但在国内域名列表里 → 国内网站。逐级去左边一段的后缀匹配。"""
        if not self.china or not name:
            return None
        name = name.lower().strip(".")
        parts = name.split(".")
        for i in range(len(parts) - 1):
            if ".".join(parts[i:]) in self.china:
                return CN_WEB
        return None

    def ip_app(self, ip: str) -> str | None:
        with self.lock:
            return self.ips.lookup(ip)

    # ---------- 状态（识别库面板） ----------
    def rows(self) -> list[dict]:
        out = []
        for sid, (license_, url) in META.items():
            if not _enabled(sid):
                continue
            st = self.state.get(sid) or {}
            row = {"id": sid, "license": license_, "url": url, "ranges": st.get("count", 0),
                   "updated": st.get("updated", 0), "error": st.get("error", "")}
            if sid == "cnlist":
                row["domains"] = st.get("count", 0)
            out.append(row)
        return out

    def reset(self):
        """测试用：清空内存数据。"""
        with self.lock:
            self.china, self.ips, self.state = set(), _Ranges(), {}
            self.version += 1


sources = Sources()
