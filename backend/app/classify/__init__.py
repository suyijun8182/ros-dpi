"""把一条流（远端 IP + 端口 + 域名）识别为应用。

分三级：应用大类（group）→ 应用小类（category）→ 应用（app），与 Panabit 的应用分类方式一致。

识别顺序（前面的认出来就不再往下查）：
1. 自定义规则（域名）
2. 应用级域名库：内置 apps.yaml、v2fly（apps_v2fly.yaml）、blackmatrix7（lists.py，运行时下载）。
   先查询名再 CNAME；三者一起按“命中的后缀越长越准”比较，一样长时 内置 > v2fly > blackmatrix7，
   因此 blackmatrix7 只补前两者没有的、或比它们更具体的域名
3. 应用级 IP：自定义 / 内置 CIDR > blackmatrix7 的 IP 段 > 专用端口 > IP 所属 ASN
4. 分类级域名列表（lists.py）：Hagezi > UT1。只知道是哪类网站（博彩、成人、游戏、购物……），
   所以排在所有应用级信号之后；命中 v2fly 的“geolocation”这类只说明是网站的兜底条目时，也由它们细化
5. 国内域名列表 > 域名像视频站（m3u8 / vod / play……）> 官方 IP 段（最长前缀优先）/ 国内 IP 段（sources.py）
   完全没有域名、落到国内网络的：按远端 ASN 名称推断家宽（P2P/PCDN）或 IDC（apps.yaml 的 asn_kinds）
6. 通用端口（HTTPS 等）> IP 协议号 > other
"""
import ipaddress
import os
import re
from dataclasses import dataclass

import yaml

_Loader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)  # 有 libyaml 时快 10 倍（v2fly 规则有几万条）

RULES_FILE = os.path.join(os.path.dirname(__file__), "apps.yaml")
# 由 scripts/import_v2fly.py 从 v2fly/domain-list-community 生成；优先级低于手工维护的 apps.yaml
V2FLY_FILE = os.path.join(os.path.dirname(__file__), "apps_v2fly.yaml")


def active_v2fly_file() -> str:
    """数据目录里自动更新的 v2fly 规则比镜像自带的新时用它，否则用镜像自带的"""
    from app.classify.v2fly import read_source
    data = os.path.join(os.environ.get("DATA_DIR", "data"), "apps_v2fly.yaml")
    if not os.path.exists(data):
        return V2FLY_FILE
    a, b = read_source(data) or {}, read_source(V2FLY_FILE) or {}
    return data if a.get("date", "") > b.get("date", "") else V2FLY_FILE
UNKNOWN_APP = "other"
WEAK_PREFIXES = ("v2_geolocation",)  # v2fly 的地区兜底条目：只说明是个网站，分类列表认得出类别时以分类列表为准


def _norm_label(s: str) -> str:
    s = re.sub(r"^(geosite|geoip|rule[-_]?set|category)[-_:]", "", str(s or "").strip().lower())
    s = re.sub(r"[\W_]+", "", s)          # 表情符号、空格、标点
    return re.sub(r"\d+$", "", s)          # sing-box 给规则集名加的序号：Telegram0
CN_NET, PCDN_APP, IDC_APP, VIDEO_APP = "cn_net", "pcdn_p2p", "idc_cloud", "gen_video"
# 主机名里带这些片段、又没有任何规则认得的域名，多半是视频站的播放 / 切片 CDN（debug25：盗版影视站的 m3u8 节点）
_VIDEO_RE = re.compile(r"m3u8|^vod|vod\d|(?<!dis)play|video|movie")
GENERIC_APPS = {"https", "quic", "http", UNKNOWN_APP}  # 这些应用下的域名算"未识别"
# 只能说明协议或 CDN 厂商、说明不了具体应用的分类，不计入"应用识别率"
UNIDENTIFIED_CATEGORIES = {"unknown", "web", "tls", "network", "cdn"}


@dataclass
class App:
    id: str
    name: str
    name_en: str
    category: str
    custom: bool = False


def _parse_port(spec: str) -> tuple[int, int, int]:
    proto, rng = spec.lower().split("/")
    pnum = {"tcp": 6, "udp": 17}[proto]
    lo, _, hi = rng.partition("-")
    return pnum, int(lo), int(hi or lo)


class Classifier:
    def __init__(self, rules_file: str = RULES_FILE, extra_file: str | None = ""):
        if extra_file == "":
            extra_file = active_v2fly_file()
        with open(rules_file, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        self.groups: dict[str, dict] = data["groups"]
        self.categories: dict[str, dict] = data["categories"]
        self._base_apps = data["apps"]
        kinds = data.get("asn_kinds") or {}
        self.asn_kinds = {k: {str(w).upper() for w in kinds.get(k, [])} for k in ("idc", "broadband")}
        self._extra = {"extend": [], "apps": []}
        if extra_file and os.path.exists(extra_file):
            with open(extra_file, encoding="utf-8") as f:
                self._extra = yaml.load(f, Loader=_Loader) or self._extra
        self.load_custom([])

    def load_custom(self, custom_rules: list):
        """custom_rules: CustomRule 行（或同字段的对象）。每次规则变更后整体重建。"""
        self.apps: dict[str, App] = {}
        self.domains: dict[str, str] = {}       # 后缀匹配
        self.full: dict[str, str] = {}          # 精确匹配
        self.custom_domains: dict[str, str] = {}
        self.nets: list[tuple[ipaddress._BaseNetwork, str]] = []
        self.ports: list[tuple[int, int, int, str]] = []
        self.protos: dict[int, str] = {}
        self.asn_apps: dict[int, str] = {}   # ASN -> 应用（IP 段归属某家公司时）
        for a in self._base_apps:
            for n in a.get("asns", []):
                self.asn_apps.setdefault(int(n), a["id"])
            self.apps[a["id"]] = App(a["id"], a["name"], a.get("name_en", a["name"]), a["category"])
            self._add(a["id"], a.get("domains", []), a.get("cidrs", []), a.get("ports", []), first_wins=True)
            for p in a.get("protos", []):
                self.protos.setdefault(int(p), a["id"])
        for e in self._extra.get("extend", []):
            if e["extend"] in self.apps:
                self._add(e["extend"], e.get("domains", []), [], [], first_wins=True)
                for d in e.get("full", []):
                    self.full.setdefault(d, e["extend"])
        for a in self._extra.get("apps", []):
            if a["id"] in self.apps or a["category"] not in self.categories:
                continue
            self.apps[a["id"]] = App(a["id"], str(a["name"]), str(a.get("name_en", a["name"])), a["category"])
            self._add(a["id"], a.get("domains", []), [], [], first_wins=True)
            for d in a.get("full", []):
                self.full.setdefault(d, a["id"])
        self._sync_list_apps()
        self.apps[UNKNOWN_APP] = App(UNKNOWN_APP, "其他", "Other", "unknown")

        custom_nets, custom_ports = [], []
        for r in custom_rules:
            if r.app_id not in self.apps:
                self.apps[r.app_id] = App(r.app_id, r.app_name or r.app_id, r.app_name or r.app_id,
                                          r.category or "web", custom=True)
            try:
                if r.kind == "domain":
                    self.custom_domains[r.pattern.lower().strip(".")] = r.app_id
                elif r.kind == "cidr":
                    custom_nets.append((ipaddress.ip_network(r.pattern, strict=False), r.app_id))
                elif r.kind == "port":
                    p, lo, hi = _parse_port(r.pattern)
                    custom_ports.append((p, lo, hi, r.app_id))
            except (ValueError, KeyError):
                continue
        # 自定义的放前面，优先匹配
        self.nets = custom_nets + self.nets
        self.ports = custom_ports + self.ports
        self._cache: dict[tuple, str] = {}
        self._ver = None

    def _sync_list_apps(self):
        """blackmatrix7 新增的应用（规则运行时下载，见 lists.py；对应关系在 bm7_map.yaml，另有上游新目录自动登记的）。
        识别库重新加载后也调一次：自动登记的新应用不用重启就生效"""
        from app.classify.lists import lists as bm7
        for aid, a in bm7.map["apps"].items():
            if aid not in self.apps and a.get("category") in self.categories:
                self.apps[aid] = App(aid, str(a["name"]), str(a.get("name_en", a["name"])), a["category"])

    def _add(self, app_id, domains, cidrs, ports, first_wins):
        for d in domains:
            d = d.lower().strip(".")
            if first_wins and d in self.domains:
                continue
            self.domains[d] = app_id
        for c in cidrs:
            self.nets.append((ipaddress.ip_network(c, strict=False), app_id))
        for p in ports:
            proto, lo, hi = _parse_port(p)
            self.ports.append((proto, lo, hi, app_id))

    def match_domain(self, name: str | None) -> str | None:
        if not name:
            return None
        name = name.lower().strip(".")
        parts = name.split(".")
        # 从完整域名开始逐级去掉左边一段；单段名（如 dns.google 的 google）不参与匹配
        suffixes = [".".join(parts[i:]) for i in range(len(parts) - 1)]
        if self.custom_domains:
            for sfx in suffixes:
                if sfx in self.custom_domains:
                    return self.custom_domains[sfx]
        # 内置 + v2fly：精确匹配算比任何后缀都长
        hit, depth = self.full.get(name), len(parts) + 1
        if not hit:
            for i, sfx in enumerate(suffixes):
                hit = self.domains.get(sfx)
                if hit:
                    depth = len(parts) - i
                    break
        # blackmatrix7：命中的后缀严格更长才用它（一样长时内置库和 v2fly 优先）
        from app.classify.lists import lists as bm7
        alt = bm7.app_domain(name)
        if alt and alt[0] in self.apps and (not hit or alt[1] > depth):
            return alt[0]
        return hit

    @staticmethod
    def video_guess(name: str | None) -> str | None:
        if not name:
            return None
        labels = name.lower().strip(".").split(".")[:-1]   # 顶级域名不看
        return VIDEO_APP if any(_VIDEO_RE.search(x) for x in labels) else None

    def asn_kind(self, remote_ip: str) -> tuple[str | None, str | None]:
        """远端 IP 所属 ASN 的类型：("idc" | "broadband" | None, 国家)；没有 ASN 库或查不到时 (None, None)"""
        from app.asn import asndb
        hit = asndb.lookup(remote_ip)
        if not hit:
            return None, None
        cache = self.__dict__.setdefault("_kind_cache", {})   # 按 ASN 缓存：每条无域名的流都要查
        kind = cache.get(hit[0], False)
        if kind is False:
            words = set(re.split(r"[^A-Z0-9]+", (hit[2] or "").upper()))
            kind = next((k for k in ("idc", "broadband") if words & self.asn_kinds.get(k, set())), None)
            if len(cache) > 100_000:
                cache.clear()
            cache[hit[0]] = kind
        return kind, hit[1]

    def asn_guess(self, remote_ip: str) -> str | None:
        """没有域名的国内流量：家宽 / 骨干网 → P2P/PCDN，IDC / 云 → 国内云/IDC；不是国内或认不出类型时 None"""
        kind, cc = self.asn_kind(remote_ip)
        if cc != "CN" or not kind:
            return None
        return PCDN_APP if kind == "broadband" else IDC_APP

    def classify(self, remote_ip: str, proto: int, port: int, qname: str | None, cname: str | None) -> str:
        from app.classify.lists import lists as extra_lists
        from app.classify.local import local
        from app.classify.sources import sources as extra
        from app.asn import asndb
        ver = (extra_lists.version, extra.version, local.version, getattr(asndb, "version", 0))
        if ver != self._ver:   # 第三方库 / 本地自学习库重新加载过：之前的结果作废
            self._cache.clear()
            self._ver = ver
            self._sync_list_apps()
        key = (remote_ip, proto, port, qname, cname)
        hit = self._cache.get(key)
        if hit:
            return hit
        app = self.match_domain(qname) or self.match_domain(cname)
        if app is None:
            # 域名自学习（debug17）：本网络实测 + 社区共享的「域名 → 应用」，精确匹配
            from app.classify.local import local as local_db
            app = local_db.domain_app(qname) or local_db.domain_app(cname)
        if app is None:
            try:
                addr = ipaddress.ip_address(remote_ip)
                for net, aid in self.nets:
                    if addr.version == net.version and addr in net:
                        app = aid
                        break
                if app is None:
                    app = extra_lists.app_ip(remote_ip)
                    app = app if app in self.apps else None
            except ValueError:
                pass
        generic = None
        if app is None:
            for p, lo, hi, aid in self.ports:
                if p == proto and lo <= port <= hi:
                    if aid in GENERIC_APPS:   # HTTPS / QUIC / HTTP 这类通用端口留到 ASN 之后
                        generic = aid
                    else:
                        app = aid
                    break
        if app is None and self.asn_apps:
            from app.asn import asndb
            hit = asndb.lookup(remote_ip)
            if hit:
                app = self.asn_apps.get(hit[0])
        if app is None:
            # 本地自学习库（debug15）：本网络实测过的 IP→应用 长期记忆，DNS 缓存过期 / DoH / 裸 IP 都能归类
            app = local.ip_app(remote_ip)
        if app is None or app.startswith(WEAK_PREFIXES):
            # 分类级列表（Hagezi > UT1）：只认得出类别；也用来细化 v2fly 的地区兜底条目
            cat = extra_lists.category(qname) or extra_lists.category(cname)
            if cat in self.apps:
                app = cat
        if app is None:
            # 先按域名兜底、再按 IP：有域名时域名更准（国内网站托管在 Cloudflare/AWS 上时，IP 只能说明是哪家 CDN）
            # 国内域名列表：域名规则没认出、但在列表里 → 国内网站
            app = extra.fallback_domain(qname) or extra.fallback_domain(cname)
            app = app or self.video_guess(qname) or self.video_guess(cname)
            # 官方 IP 段：完全没有域名的流量（加密 DNS、ECH、直连 IP）按 Google/Cloudflare/AWS/Apple/国内段 认归属
            app = app or extra.ip_app(remote_ip)
            if app in (None, CN_NET) and not qname and not cname:
                # 国内段兜底只说明“在国内”：再按 ASN 类型分出家宽 P2P/PCDN 和 IDC（debug25）
                app = self.asn_guess(remote_ip) or app
        if app is None:
            app = generic or self.protos.get(proto)
        app = app or UNKNOWN_APP
        if len(self._cache) > 200_000:
            self._cache.clear()
        self._cache[key] = app
        return app

    def app_by_label(self, label: str) -> str | None:
        """按名字找应用：sing-box 的规则集名（Telegram0、geosite-netflix）或策略组名（✈️ Telegram）。
        去掉表情符号、前缀和末尾序号后，与应用的 id / 中英文名精确比较"""
        idx = getattr(self, "_label_idx", None)
        if idx is None or idx[0] is not self.apps or idx[2] != len(self.apps):   # 自动登记的新应用是原地加进来的
            m = {}
            for a in self.apps.values():
                if a.id in GENERIC_APPS or a.category == "unknown":
                    continue
                for v in (a.id, a.name, a.name_en):
                    k = _norm_label(v)
                    if len(k) >= 2:
                        m.setdefault(k, a.id)
            idx = self._label_idx = (self.apps, m, len(self.apps))
        return idx[1].get(_norm_label(label))

    def app_info(self, app_id: str) -> App:
        return self.apps.get(app_id) or App(app_id, app_id, app_id, "unknown")

    def category_info(self, cat: str) -> dict:
        return self.categories.get(cat) or {"group": "unknown", "name": cat, "name_en": cat}

    def group_info(self, group: str) -> dict:
        return self.groups.get(group) or {"name": group, "name_en": group}
