"""第三方规则库（运行时下载到数据目录，不进镜像和仓库）：

- blackmatrix7/ios_rule_script（GPL-2.0）：按应用整理的规则。目录名到 ROS-DPI 应用的对应关系在 bm7_map.yaml，
  只用其中列出的目录；给已有应用补内置库和 v2fly 里没有的域名、IP 段，另新增约 100 个应用。每周更新。
- Hagezi DNS blocklists（GPL-3.0）：成人、博彩、VPN/代理、社交、广告、各厂商设备遥测等专项分类列表。每天更新。
- UT1（Université Toulouse Capitole，CC BY-SA 4.0）：游戏、购物、新闻、求职、银行等分类列表。每天更新。

上游出现新的目录 / 列表时自动登记成新应用（debug14）：类别按目录名猜测，登记结果存在
data/lists/rules_auto.yaml，下次更新自动带上；手工映射仍在 bm7_map.yaml，优先级更高。

识别顺序和权重（详见 app/classify/__init__.py）：
- blackmatrix7 是应用级：和内置库 / v2fly 一起按域名匹配，匹配到的后缀更长者赢，一样长时内置库和 v2fly 优先。
- Hagezi / UT1 是分类级：只知道是哪类网站，排在所有应用级信号（域名、IP 段、端口、ASN）之后、国内域名列表之前；
  两者之间 Hagezi 优先（专项列表、维护更勤），同一列表里后缀更长者赢。

分类列表加起来约 65 万个域名，存成排序的 64 位哈希数组（约 5MB），不存字符串。
环境变量 BM7_DB / HAGEZI_DB / UT1_DB 可分别关闭（默认开）。
"""
import hashlib
import ipaddress
import os
import re
import threading
import time
import urllib.parse
from array import array
from bisect import bisect_left
from concurrent.futures import ThreadPoolExecutor

import httpx
import yaml

from app.classify.sources import _Ranges

MAP_FILE = os.path.join(os.path.dirname(__file__), "bm7_map.yaml")
BM7_URL = "https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/master/rule/Clash/{0}/{0}.list"
HAGEZI_URL = "https://raw.githubusercontent.com/hagezi/dns-blocklists/main/wildcard/{0}-onlydomains.txt"
UT1_URL = "https://raw.githubusercontent.com/olbat/ut1-blacklists/master/blacklists/{0}/domains"
# 上游目录清单（自动发现用，每次更新最多查一次）
BM7_LIST_API = "https://api.github.com/repos/blackmatrix7/ios_rule_script/contents/rule/Clash"
HAGEZI_LIST_API = "https://api.github.com/repos/hagezi/dns-blocklists/contents/wildcard"
UT1_LIST_API = "https://api.github.com/repos/olbat/ut1-blacklists/contents/blacklists"
LIST_API = {"bm7": BM7_LIST_API, "hagezi": HAGEZI_LIST_API, "ut1": UT1_LIST_API}
# bm7 的汇总 / 区域 / 安全类目录：不是单个应用，不自动登记
BM7_SKIP = {
    "Global", "Proxy", "Direct", "Lan", "Reject", "AdBlock", "Advertising", "AdvertisingLite", "AntiAd",
    "China", "ChinaMedia", "ChinaTest", "ChinaMax", "ChinaMaxNoIP", "ChinaMaxNoMedia", "ChinaNoMedia",
    "ChinaIPs", "ChinaIPsBGP", "ChinaDNS", "DomesticIPs", "PublicDNS", "LocalDNS", "PrivateDNS", "DNS",
    "GoogleDNS", "ProxyGFW", "GFW", "GreatFire", "AntiPolicy", "Hijacking", "PotentialMalware", "Safety",
    "Spam", "TrackersList", "ZoneTelekom", "Classic", "3Type", "Cloud", "GlobalMedia", "IPTVOther",
    "Speedtest", "MicrosoftEdge", "AllAI", "Download", "Crypto", "Cryptocurrency", "Developer", "Anime",
    "AsianMedia", "Game", "Mail", "GoogleSearch", "Antutu", "Region", "TldCheap", "TldFake",
}
# 目录名 / 列表名 → 类别的猜测规则（debug14：上游新增内容自动归类；猜不出 bm7 归「常用网站」、分类列表跳过）
GUESS = [
    (r"adult|porn|nsfw|xxx", "adult"), (r"gambl|bet|casino|lotter", "gambling"),
    (r"spotify|music|radio|podcast|tidal|deezer|netease_music|kugou|kuwo", "music"),
    (r"(^|[-_])(live|stream)([-_]|$)|twitch|douyu|huya|yy", "live"),
    (r"video|tv|movie|film|cinema|anime|manga|mgtv|youku|iqiyi|bilibili|netflix|hbo|disney|emby|iptv|cctv", "video"),
    (r"game|steam|epic|blizzard|riot|xbox|playstation|nintendo|4399|9game|taptap|mihoyo", "game"),
    (r"shop|taobao|tmall|jd|jingdong|pinduoduo|suning|vipshop|aliexpress|amazon|ebay|shopee|gome", "shopping"),
    (r"bank|icbc|ccb|cmb|abc|psbc|boc|bocom|citic|spdb|cib|ceb|cgb|spdb|unionpay|alipay|tenpay|paypal|pay", "bank"),
    (r"mail|smtp|imap|webmail", "mail"),
    (r"news|media|press|bbc|cnn|reuters|nytimes", "news"),
    (r"social|weibo|twitter|facebook|instagram|tiktok|douyin|reddit|forum|snapchat|linkedin|pin", "social"),
    (r"wechat|weixin|whatsapp|telegram|line|slack|dingtalk|feishu|skype|zoom|meeting", "im"),
    (r"openai|claude|gemini|copilot|chatgpt|anthropic|perplexity|midjourney|hf|\bai\b", "ai"),
    (r"cloud|drive|pan|onedrive|dropbox|aliyundrive|quark|s3|oss", "cloud"),
    (r"github|gitlab|gitcode|gitee|docker|npm|python|jetbrains|dev", "dev"),
    (r"proxy|vpn|tor|gfw|warp|outline|shadowsocks|v2ray|trojan|clash", "proxy"),
    (r"travel|trip|hotel|flight|airline|booking|ctrip|qunar|fliggy|12306|ticket", "travel"),
    (r"edu|mooc|university|course|learn|school|xueersi|yuanfudao|zuoyebang", "education"),
    (r"health|hospital|medic|pharma|doctor|clinic", "life"),
    (r"food|takeaway|waimai|meituan|eleme|restaurant|recipe", "life"),
    (r"cdn|static|cache|cloudfront|akamai|cloudflare|fastly|edge", "cdn"),
    (r"tracker|warez|pt|download|thunder|xunlei", "download"),
    (r"mine|mining|pool|nicehash", "mining"),
    (r"remote|ssh|rdp|vnc|teamviewer|todesk|rustdesk|anydesk", "remote"),
]

# 分类列表：(列表名, 归到的应用)。顺序就是同一域名在多个列表里时的优先级
HAGEZI = [(f"native.{v}", "gen_telemetry") for v in
          ("xiaomi", "huawei", "oppo-realme", "vivo", "samsung", "apple", "amazon", "tiktok", "lgwebos", "roku", "winoffice")] + [
    ("nsfw", "gen_adult"), ("gambling.medium", "gen_gambling"), ("doh-vpn-proxy-bypass", "vpn"),
    ("social", "gen_social"), ("light", "ads"),
]
UT1 = [
    ("jobsearch", "jobs"), ("gambling", "gen_gambling"), ("mixed_adult", "gen_adult"), ("lingerie", "gen_adult"),
    ("bank", "gen_bank"), ("financial", "gen_finance"), ("bitcoin", "gen_finance"), ("webmail", "gen_mail"), ("chat", "gen_im"),
    ("remote-control", "gen_remote"), ("ai", "gen_ai"), ("doh", "doh"), ("vpn", "vpn"), ("update", "gen_update"),
    ("filehosting", "gen_cloud"), ("download", "gen_download"), ("warez", "gen_download"), ("audio-video", "gen_video"),
    ("radio", "gen_music"), ("manga", "comics"), ("games", "gen_game"), ("educational_games", "gen_education"),
    ("social_networks", "gen_social"), ("forums", "gen_social"), ("dating", "gen_social"), ("blog", "gen_reading"),
    ("press", "gen_news"), ("sports", "gen_news"), ("celebrity", "gen_news"), ("shopping", "gen_shopping"),
    ("publicite", "ads"), ("cryptojacking", "gen_mining"),
]
MAX_AGE = {"bm7": 7 * 24 * 3600, "hagezi": 24 * 3600, "ut1": 24 * 3600}
META = {
    "bm7": ("GPL-2.0", "https://github.com/blackmatrix7/ios_rule_script"),
    "hagezi": ("GPL-3.0", "https://github.com/hagezi/dns-blocklists"),
    "ut1": ("CC BY-SA 4.0", "https://dsi.ut-capitole.fr/blacklists/"),
}


def _h(name: str) -> int:
    return int.from_bytes(hashlib.blake2b(name.encode(), digest_size=8).digest(), "little")


def _suffixes(name: str | None) -> list[str]:
    """完整域名在前，逐级去掉左边一段；单段名不参与匹配"""
    if not name:
        return []
    parts = name.lower().strip(".").split(".")
    return [".".join(parts[i:]) for i in range(len(parts) - 1)]


def _is_domain(s: str) -> bool:
    if not s or "." not in s or "/" in s or ":" in s:
        return False
    try:
        ipaddress.ip_address(s)
        return False
    except ValueError:
        return True


class _HashTable:
    """域名 → 应用：排序的 64 位哈希数组 + 应用下标（碰撞概率可忽略：65 万条 / 2^64）"""

    def __init__(self):
        self.keys, self.vals, self.apps = array("Q"), array("H"), []

    @classmethod
    def build(cls, lists: list[tuple[str, list[str]]]) -> "_HashTable":
        """lists 按优先级排列：[(应用, [域名…])]；同一域名取最靠前的"""
        t = cls()
        idx = {}
        packed = []
        for prio, (app, domains) in enumerate(lists):
            ai = idx.setdefault(app, len(idx))
            for d in domains:
                packed.append((_h(d) << 32) | (prio << 16) | ai)   # 先按哈希、再按优先级排序
        packed.sort()
        last = None
        for x in packed:
            k = x >> 32
            if k != last:
                t.keys.append(k)
                t.vals.append(x & 0xFFFF)
                last = k
        t.apps = list(idx)
        return t

    def __len__(self):
        return len(self.keys)

    def get(self, name: str) -> str | None:
        k = _h(name)
        i = bisect_left(self.keys, k)
        return self.apps[self.vals[i]] if i < len(self.keys) and self.keys[i] == k else None

    def lookup(self, name: str | None) -> tuple[str, int] | None:
        """最长后缀匹配，返回 (应用, 命中的后缀段数)"""
        for s in _suffixes(name):
            hit = self.get(s)
            if hit:
                return hit, s.count(".") + 1
        return None


def _enabled(sid: str) -> bool:
    from app.config import get_settings
    return bool(getattr(get_settings(), f"{sid}_db", True))


def load_map() -> dict:
    with open(MAP_FILE, encoding="utf-8") as f:
        m = yaml.safe_load(f) or {}
    owner = dict(m.get("extend") or {})
    for aid, a in (m.get("apps") or {}).items():
        for n in a.get("lists", []):
            owner[n] = aid
    return {"owner": owner, "apps": m.get("apps") or {}}


def guess_category(name: str) -> tuple[str, bool]:
    """按目录名 / 列表名猜类别（debug14 自动登记用）。返回 (类别, 是否有把握)；猜不出归「常用网站」"""
    low = name.lower()
    for pat, cat in GUESS:
        if re.search(pat, low):
            return cat, True
    return "site", False


class Lists:
    def __init__(self):
        self.lock = threading.Lock()
        self.version = 0
        self.bm7_suffix: dict[str, str] = {}
        self.bm7_full: dict[str, str] = {}
        self.bm7_ips = _Ranges()
        self.cat = _HashTable()
        self.state: dict[str, dict] = {}   # 来源 id -> {count, apps, updated, error}
        self._map = None
        self._auto: dict = {}              # 自动登记的应用（debug14），存 data/lists/rules_auto.yaml
        self._load_auto()

    @property
    def map(self) -> dict:
        if self._map is None:
            base = load_map()
            for aid, a in self._auto.items():
                base["apps"].setdefault(aid, {"category": a["category"], "name": a["name"], "name_en": a["name_en"]})
                if a.get("source") == "bm7" and a.get("dir"):
                    base["owner"].setdefault(a["dir"], aid)
            self._map = base
        return self._map

    def _dir(self, sid: str) -> str:
        return os.path.join(os.environ.get("DATA_DIR", "data"), "lists", sid)

    def _auto_file(self) -> str:
        return os.path.join(self._dir("bm7"), "rules_auto.yaml")

    def _load_auto(self):
        try:
            with open(self._auto_file(), encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            self._auto = data.get("apps") or {}
        except (OSError, yaml.YAMLError):
            self._auto = {}

    def _save_auto(self):
        path = self._auto_file()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write("# 自动发现并登记的第三方规则（debug14）：上游出现新目录 / 新列表时自动生成。\n"
                    "# 手工映射在镜像内的 bm7_map.yaml，优先级更高；删除本文件后，下次更新按当时的上游重新生成。\n")
            yaml.safe_dump({"apps": self._auto}, f, allow_unicode=True, sort_keys=True)

    def _spec(self, sid: str) -> list[tuple[str, str]]:
        """分类列表的 (列表名, 应用)：手工映射在前，自动登记的追加在后面"""
        base = HAGEZI if sid == "hagezi" else UT1
        extra = [(a["list"], aid) for aid, a in self._auto.items() if a.get("source") == sid]
        return list(base) + extra

    def _files(self, sid: str) -> list[tuple[str, str]]:
        """(本地文件名, 下载地址)"""
        if sid == "bm7":
            return [(f"{n}.list", BM7_URL.format(urllib.parse.quote(n))) for n in sorted(self.map["owner"])]
        return [(f"{n}.txt", (HAGEZI_URL if sid == "hagezi" else UT1_URL).format(n)) for n, _app in self._spec(sid)]

    # ---------- 加载 ----------
    @staticmethod
    def _read(path: str) -> list[str]:
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                return f.read().splitlines()
        except OSError:
            return []

    def _load_bm7(self):
        suffix, full, ips = {}, {}, _Ranges()
        apps, n = set(), 0
        d = self._dir("bm7")
        for name, app in self.map["owner"].items():
            got = False
            for line in self._read(os.path.join(d, f"{name}.list")):
                p = [x.strip() for x in line.split(",")]
                if len(p) < 2 or line.startswith("#"):
                    continue
                kind, val = p[0].upper(), p[1].lower().strip(".")
                if kind == "DOMAIN-SUFFIX" and _is_domain(val):
                    suffix.setdefault(val, app)
                elif kind == "DOMAIN" and _is_domain(val):
                    full.setdefault(val, app)
                elif kind in ("IP-CIDR", "IP-CIDR6"):
                    ips.add(val, app)
                else:
                    continue
                n += 1
                got = True
            if got:
                apps.add(app)
        ips.build()
        return suffix, full, ips, n, len(apps)

    def _load_cat(self, sid: str) -> list[tuple[str, list[str]]]:
        out = []
        for name, app in self._spec(sid):
            doms = []
            for line in self._read(os.path.join(self._dir(sid), f"{name}.txt")):
                s = line.strip().lower().lstrip("*.").strip(".")
                if s and not s.startswith("#") and _is_domain(s):
                    doms.append(s)
            out.append((app, doms))
        return out

    def _stamp(self, sid: str) -> int:
        try:
            return int(os.path.getmtime(os.path.join(self._dir(sid), ".stamp")))
        except OSError:
            return 0

    def load(self):
        state = {}
        suffix, full, ips = {}, {}, _Ranges()
        if _enabled("bm7"):
            suffix, full, ips, n, apps = self._load_bm7()
            if n:
                state["bm7"] = {"count": n, "apps": apps, "updated": self._stamp("bm7")}
        else:
            ips.build()
        cat_lists = []
        for sid in ("hagezi", "ut1"):   # 先 Hagezi 后 UT1：同一域名 Hagezi 优先
            if not _enabled(sid):
                continue
            lists = self._load_cat(sid)
            n = sum(len(d) for _a, d in lists)
            if n:
                cat_lists += lists
                state[sid] = {"count": n, "updated": self._stamp(sid)}
        cat = _HashTable.build(cat_lists)
        with self.lock:
            for sid, st in state.items():
                st["error"] = self.state.get(sid, {}).get("error", "")
            for sid, st in self.state.items():
                if sid not in state and st.get("error"):
                    state[sid] = {"count": 0, "updated": 0, "error": st["error"]}
            self.bm7_suffix, self.bm7_full, self.bm7_ips, self.cat, self.state = suffix, full, ips, cat, state
            self.version += 1

    # ---------- 更新 ----------
    def update(self, force: bool = False) -> bool:
        """各来源满了更新周期（bm7 一周、其余一天）就重新下载；单个文件失败保留旧文件"""
        changed = False
        if _enabled("bm7") and (force or time.time() - self._stamp("bm7") >= MAX_AGE["bm7"]):
            try:
                self.discover()   # debug14：上游新增的目录 / 列表先登记，同一轮就会下载
            except Exception:  # noqa: BLE001  发现不了（没外网 / API 限流）不影响本轮更新
                pass
        for sid in ("bm7", "hagezi", "ut1"):
            if not _enabled(sid):
                continue
            if not force and time.time() - self._stamp(sid) < MAX_AGE[sid]:
                continue
            ok, failed = self._fetch_all(sid)
            changed = changed or ok > 0
            err = f"{failed} 个文件下载失败，继续用旧数据" if failed else ""
            self.state[sid] = {**self.state.get(sid, {}), "error": err}
        if changed or not self.state:
            self.load()
        return changed

    def discover(self) -> int:
        """上游仓库出现新的规则目录 / 分类列表时自动登记成应用（debug14）。返回新登记个数。"""
        added = self._discover_bm7() + self._discover_spec("hagezi") + self._discover_spec("ut1")
        if added:
            self._save_auto()
            self._map = None   # 让 map 重新合并，新应用 / 新目录立即生效
        return added

    @staticmethod
    def _list_names(url: str, kind: str) -> set[str]:
        """GitHub 目录清单：kind=dir 取目录名；kind=file 取去掉 onlydomains.txt 后缀的文件名"""
        r = httpx.get(url, timeout=30.0, headers={"User-Agent": "ros-dpi", "Accept": "application/vnd.github+json"})
        r.raise_for_status()
        out = set()
        for x in r.json():
            name = x.get("name", "")
            if x.get("type") == kind and not name.startswith("."):
                if kind == "file" and name.endswith("-onlydomains.txt"):
                    name = name[:-len("-onlydomains.txt")]
                out.add(name)
        return out

    def _register(self, source: str, names: set[str], strict: bool) -> int:
        added = 0
        known = set(self.map["owner"])
        for n in sorted(names):
            if n in known or n in BM7_SKIP:
                continue
            cat, confident = guess_category(n)
            if strict and not confident:
                continue   # 分类列表猜不出类别就跳过：宁缺毋滥，等手工映射
            aid = "gen_" + re.sub(r"[^a-z0-9]+", "_", n.lower()).strip("_") if source != "bm7" \
                else "bm7_" + re.sub(r"[^a-z0-9]+", "_", n.lower()).strip("_")
            if aid in self._auto or aid in self.map["apps"] or aid in self.map["owner"].values():
                continue
            entry = {"category": cat, "name": n, "name_en": n, "source": source}
            if source == "bm7":
                entry["dir"] = n
            else:
                entry["list"] = n
            self._auto[aid] = entry
            known.add(n)
            added += 1
        return added

    def _discover_bm7(self) -> int:
        return self._register("bm7", self._list_names(LIST_API["bm7"], "dir"), strict=False)

    def _discover_spec(self, sid: str) -> int:
        if sid == "hagezi":
            return self._register("hagezi", self._list_names(LIST_API[sid], "file"), strict=True)
        return self._register("ut1", self._list_names(LIST_API[sid], "dir"), strict=True)

    def _fetch_all(self, sid: str) -> tuple[int, int]:
        d = self._dir(sid)
        os.makedirs(d, exist_ok=True)

        def one(item):
            fname, url = item
            path = os.path.join(d, fname)
            tmp = path + ".part"
            try:
                with httpx.stream("GET", url, timeout=120, follow_redirects=True) as r:
                    if r.status_code == 404:
                        return None            # 上游删了这个目录：不算失败
                    r.raise_for_status()
                    with open(tmp, "wb") as f:
                        for chunk in r.iter_bytes(1 << 16):
                            f.write(chunk)
                os.replace(tmp, path)
                return True
            except Exception:  # noqa: BLE001  没有外网时保留旧文件
                if os.path.exists(tmp):
                    os.remove(tmp)
                return False

        with ThreadPoolExecutor(8) as ex:
            res = list(ex.map(one, self._files(sid)))
        ok, failed = res.count(True), res.count(False)
        if ok and failed <= len(res) // 10:   # 大部分成功才算这一轮更新完成
            with open(os.path.join(d, ".stamp"), "w") as f:
                f.write(str(int(time.time())))
        return ok, failed

    # ---------- 查询 ----------
    def app_domain(self, name: str | None) -> tuple[str, int] | None:
        """blackmatrix7：(应用, 命中的后缀段数)；精确匹配算比任何后缀都长"""
        if not name or not (self.bm7_suffix or self.bm7_full):
            return None
        name = name.lower().strip(".")
        hit = self.bm7_full.get(name)
        if hit:
            return hit, name.count(".") + 2
        for s in _suffixes(name):
            hit = self.bm7_suffix.get(s)
            if hit:
                return hit, s.count(".") + 1
        return None

    def app_ip(self, ip: str) -> str | None:
        with self.lock:
            return self.bm7_ips.lookup(ip)

    def category(self, name: str | None) -> str | None:
        hit = self.cat.lookup(name) if len(self.cat) else None
        return hit[0] if hit else None

    # ---------- 状态（识别库面板） ----------
    def rows(self) -> list[dict]:
        out = []
        for sid, (license_, url) in META.items():
            if not _enabled(sid):
                continue
            st = self.state.get(sid) or {}
            row = {"id": sid, "license": license_, "url": url, "domains": st.get("count", 0),
                   "updated": st.get("updated", 0), "error": st.get("error", "")}
            if sid == "bm7":
                row["apps"] = st.get("apps", 0)
                row["rules"] = row.pop("domains")
            out.append(row)
        return out

    def reset(self):
        """测试用：清空内存数据"""
        with self.lock:
            self.bm7_suffix, self.bm7_full, self.bm7_ips, self.cat, self.state = {}, {}, _Ranges(), _HashTable(), {}
            self.bm7_ips.build()
            self.version += 1


lists = Lists()
