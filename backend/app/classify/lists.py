"""第三方规则库（运行时下载到数据目录，不进镜像和仓库）：

- blackmatrix7/ios_rule_script（GPL-2.0）：按应用整理的规则。目录名到 ROS-DPI 应用的对应关系在 bm7_map.yaml，
  只用其中列出的目录；给已有应用补内置库和 v2fly 里没有的域名、IP 段，另新增约 100 个应用。每周更新。
- Hagezi DNS blocklists（GPL-3.0）：成人、博彩、VPN/代理、社交、广告、各厂商设备遥测等专项分类列表。每天更新。
- UT1（Université Toulouse Capitole，CC BY-SA 4.0）：游戏、购物、新闻、求职、银行等分类列表。每天更新。

上游出现新的目录 / 列表时自动登记（debug14），结果存在 data/lists/bm7/rules_auto.yaml，手工映射（bm7_map.yaml）优先：
- blackmatrix7 新目录先下载，再拿它的域名去问现有识别库“投票”：多数域名属于同一个已有应用 → 并入该应用；
  多数属于同一大类 → 新建该类应用；投票不够（多是没人认识的新应用）才按目录名猜类别，猜不出归「常用网站」。
  公司级大杂烩（Tencent、Google…）、广告 / 隐私 / 汇总列表不登记。
- Hagezi / UT1 新列表只有列表名能明确猜出类别时才登记，下载后投票明显不符的作废。

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
from collections import Counter
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
# bm7 的汇总 / 区域 / 安全类目录、公司级大杂烩：不是单个应用，不自动登记（同 bm7_map.yaml 开头的说明）
BM7_SKIP = {
    "Global", "Proxy", "ProxyLite", "Direct", "Lan", "Reject", "AdBlock", "Advertising", "AdvertisingLite", "AntiAd",
    "China", "ChinaMedia", "ChinaTest", "ChinaMax", "ChinaMaxNoIP", "ChinaMaxNoMedia", "ChinaNoMedia",
    "ChinaIPs", "ChinaIPsBGP", "ChinaDNS", "DomesticIPs", "PublicDNS", "LocalDNS", "PrivateDNS", "DNS",
    "GoogleDNS", "ProxyGFW", "GFW", "GreatFire", "AntiPolicy", "Hijacking", "PotentialMalware", "Safety",
    "Spam", "TrackersList", "ZoneTelekom", "Classic", "3Type", "Cloud", "GlobalMedia", "IPTVOther",
    "Speedtest", "MicrosoftEdge", "AllAI", "Download", "Crypto", "Cryptocurrency", "Developer", "Anime",
    "AsianMedia", "Game", "Mail", "GoogleSearch", "Antutu", "Region", "TldCheap", "TldFake",
    "Alibaba", "Baidu", "ByteDance", "Tencent", "Google", "Microsoft", "Apple", "Huawei", "Amazon",
    "BlockHttpDNS", "SystemOTA", "STUN", "Scholar", "GlobalScholar", "UKMedia", "USMedia",
}
# 名字像广告 / 隐私 / 拦截 / 纯 IP 列表的也跳过（AdGuardSDNSFilter、EasyPrivacy、AdvertisingMiTV、AmazonIP…）
BM7_SKIP_RE = re.compile(r"^(Ad[A-Z]|Advertising|AdGuard|Easy)|Privacy|Marketing|Block|Tracker|Filter|IPs?$")
# 投票：至少这么多条被现有库认出才算数（小目录认出一半以上也算）；同一应用占 ≥60% 并入该应用，同一大类占 ≥50% 定为该类
VOTE_MIN, VOTE_APP, VOTE_CAT, VOTE_SAMPLE = 5, 0.6, 0.5, 5000
# 目录名 / 列表名 → 类别（投票不够时才用）。按单词匹配：短词（<5 个字母）必须是完整的单词，
# 免得 Facebook 里的 ceb 认成银行、Minecraft 里的 mine 认成挖矿、HeroesoftheStorm 里的 tor 认成代理
GUESS = [
    (("adult", "porn", "nsfw", "xxx"), "adult"), (("gambl", "bet", "betting", "casino", "lotter"), "gambling"),
    (("spotify", "music", "radio", "podcast", "tidal", "deezer", "kugou", "kuwo"), "music"),
    (("live", "stream", "twitch", "douyu", "huya", "yy"), "live"),
    (("video", "tv", "movie", "film", "cinema", "anime", "manga", "mgtv", "youku", "iqiyi", "bilibili", "netflix",
      "hbo", "disney", "emby", "iptv", "cctv"), "video"),
    (("game", "games", "steam", "epic", "blizzard", "riot", "xbox", "playstation", "nintendo", "4399", "taptap",
      "mihoyo"), "game"),
    (("shop", "shopping", "taobao", "tmall", "jd", "jingdong", "pinduoduo", "suning", "vipshop", "aliexpress",
      "amazon", "ebay", "shopee", "gome"), "shopping"),
    (("bank", "icbc", "ccb", "cmb", "abc", "psbc", "boc", "bocom", "citic", "spdb", "cib", "ceb", "cgb",
      "unionpay", "alipay", "tenpay", "paypal", "pay"), "bank"),
    (("mail", "smtp", "imap", "webmail"), "mail"),
    (("news", "media", "press", "bbc", "cnn", "reuters", "nytimes"), "news"),
    (("social", "weibo", "twitter", "facebook", "instagram", "tiktok", "douyin", "reddit", "forum", "forums",
      "snapchat", "linkedin", "pinterest"), "social"),
    (("wechat", "weixin", "whatsapp", "telegram", "line", "slack", "dingtalk", "feishu", "skype", "zoom",
      "meeting", "chat"), "im"),
    (("openai", "claude", "gemini", "copilot", "chatgpt", "anthropic", "perplexity", "midjourney", "hf", "ai"), "ai"),
    (("cdn", "static", "cache", "cloudfront", "akamai", "cloudflare", "fastly", "edge"), "cdn"),
    (("cloud", "drive", "pan", "onedrive", "dropbox", "aliyundrive", "quark", "s3", "oss"), "cloud"),
    (("github", "gitlab", "gitcode", "gitee", "docker", "npm", "python", "jetbrains", "dev"), "dev"),
    (("proxy", "vpn", "tor", "gfw", "warp", "outline", "shadowsocks", "v2ray", "trojan", "clash"), "proxy"),
    (("travel", "trip", "hotel", "flight", "airline", "booking", "ctrip", "qunar", "fliggy", "12306", "ticket"),
     "travel"),
    (("edu", "mooc", "university", "course", "learn", "school", "xueersi", "yuanfudao", "zuoyebang"), "education"),
    (("health", "hospital", "medic", "pharma", "doctor", "clinic", "food", "takeaway", "waimai", "meituan",
      "eleme", "restaurant", "recipe"), "life"),
    (("tracker", "warez", "pt", "download", "thunder", "xunlei"), "download"),
    (("mining", "mine", "pool", "nicehash"), "mining"),
    (("remote", "ssh", "rdp", "vnc", "teamviewer", "todesk", "rustdesk", "anydesk"), "remote"),
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


def _words(name: str) -> set[str]:
    """MangoTV → {mango, tv}；ICBCBank → {icbc, bank}；native.tiktok → {native, tiktok}"""
    return {w.lower() for w in re.findall(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+", name)}


def guess_category(name: str) -> tuple[str, bool]:
    """按目录名 / 列表名猜类别（debug14 自动登记、投票不够时用）。返回 (类别, 是否有把握)；猜不出归「常用网站」"""
    low, words = name.lower(), _words(name)
    for keys, cat in GUESS:
        for k in keys:
            if (k in low) if len(k) >= 5 else (k in words):
                return cat, True
    return "site", False


def _vote(classifier, cat_of, domains: list[str], ips: list[str] = ()) -> tuple[str | None, float, str | None, float, int]:
    """拿一份新列表的域名（和 IP 段）问现有识别库：返回 (最多的应用, 占比, 最多的大类, 占比, 认出的条数)。
    协议 / CDN / 未识别这类笼统结果不算票。IP 段取网络地址按 IP 段 / ASN 识别（TelegramSG 这类只有 IP 的目录）"""
    from app.classify import GENERIC_APPS, UNIDENTIFIED_CATEGORIES, WEAK_PREFIXES
    apps, cats = Counter(), Counter()
    found = [classifier.match_domain(d) or cat_of(d) for d in domains[:VOTE_SAMPLE]]
    found += [classifier.classify(ip, 6, 0, None, None) for ip in ips[:VOTE_SAMPLE]]
    for aid in found:
        if not aid or aid in GENERIC_APPS or aid.startswith(WEAK_PREFIXES):
            continue
        cat = classifier.app_info(aid).category
        if cat in UNIDENTIFIED_CATEGORIES:
            continue
        apps[aid] += 1
        cats[cat] += 1
    n = sum(apps.values())
    if not n:
        return None, 0.0, None, 0.0, 0
    (app, na), (cat, nc) = apps.most_common(1)[0], cats.most_common(1)[0]
    return app, na / n, cat, nc / n, n


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
                if a.get("pending") or a.get("rejected"):
                    continue   # 还没投票 / 投票作废的不进映射
                if not a.get("extend") and not a.get("app"):
                    base["apps"].setdefault(aid, {"category": a["category"], "name": a["name"], "name_en": a["name_en"]})
                if a.get("source") == "bm7" and a.get("dir"):
                    base["owner"].setdefault(a["dir"], a.get("extend") or aid)
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
        extra = [(a["list"], a.get("app") or aid) for aid, a in self._auto.items()
                 if a.get("source") == sid and not a.get("pending") and not a.get("rejected")]
        return list(base) + extra

    def _pending(self, sid: str) -> list[str]:
        """已发现、等下载后投票的目录 / 列表名"""
        return [a.get("dir") or a.get("list") for a in self._auto.values() if a.get("source") == sid and a.get("pending")]

    def _files(self, sid: str) -> list[tuple[str, str]]:
        """(本地文件名, 下载地址)；待投票的也下载"""
        if sid == "bm7":
            names = set(self.map["owner"]) | set(self._pending("bm7"))
            return [(f"{n}.list", BM7_URL.format(urllib.parse.quote(n))) for n in sorted(names)]
        names = [n for n, _app in self._spec(sid)] + self._pending(sid)
        return [(f"{n}.txt", (HAGEZI_URL if sid == "hagezi" else UT1_URL).format(n)) for n in names]

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
            for kind, val in self._bm7_rules(os.path.join(d, f"{name}.list")):
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

    def _bm7_rules(self, path: str):
        for line in self._read(path):
            p = [x.strip() for x in line.split(",")]
            if len(p) < 2 or line.startswith("#"):
                continue
            yield p[0].upper(), p[1].lower().strip(".")

    def _cat_domains(self, path: str) -> list[str]:
        doms = []
        for line in self._read(path):
            s = line.strip().lower().lstrip("*.").strip(".")
            if s and not s.startswith("#") and _is_domain(s):
                doms.append(s)
        return doms

    def _load_cat(self, sid: str) -> list[tuple[str, list[str]]]:
        return [(app, self._cat_domains(os.path.join(self._dir(sid), f"{name}.txt"))) for name, app in self._spec(sid)]

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
        try:
            if self.resolve():   # 刚下载的新目录 / 列表投票定归属
                changed = True
        except Exception as e:  # noqa: BLE001  投票失败下次再来，不影响本轮更新
            print(f"[lists] 新规则投票失败：{type(e).__name__}: {e}", flush=True)
        if changed or not self.state:
            self.load()
        return changed

    def discover(self) -> int:
        """上游仓库出现新的规则目录 / 分类列表时先登记为待定，下载后由 resolve() 投票定归属（debug14）。返回新登记个数。"""
        added = self._discover_bm7() + self._discover_spec("hagezi") + self._discover_spec("ut1")
        if added:
            self._save_auto()
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

    @staticmethod
    def _aid(source: str, name: str) -> str:
        return ("bm7_" if source == "bm7" else "gen_") + re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")

    def _discover_bm7(self) -> int:
        known = set(self.map["owner"]) | {a.get("dir") for a in self._auto.values() if a.get("source") == "bm7"}
        added = 0
        for n in sorted(self._list_names(LIST_API["bm7"], "dir")):
            if n in known or n in BM7_SKIP or BM7_SKIP_RE.search(n):
                continue
            aid = self._aid("bm7", n)
            if aid in self._auto or aid in self.map["apps"]:
                continue
            self._auto[aid] = {"source": "bm7", "dir": n, "pending": True}
            added += 1
        return added

    def _discover_spec(self, sid: str) -> int:
        kind = "file" if sid == "hagezi" else "dir"
        base = HAGEZI if sid == "hagezi" else UT1
        known = {n for n, _app in base} | {a.get("list") for a in self._auto.values() if a.get("source") == sid}
        added = 0
        for n in sorted(self._list_names(LIST_API[sid], kind)):
            if n in known:
                continue
            cat, confident = guess_category(n)
            if not confident:
                continue   # 分类列表猜不出类别就跳过：宁缺毋滥，等手工映射
            aid = self._aid(sid, n)
            if aid in self._auto or aid in self.map["apps"]:
                continue
            self._auto[aid] = {"source": sid, "list": n, "category": cat, "pending": True}
            added += 1
        return added

    def resolve(self, classifier=None) -> int:
        """给已下载的待定目录 / 列表投票定归属（见模块说明）。返回定下来的个数；没下载到的留到下次"""
        pend = [(aid, a) for aid, a in self._auto.items() if a.get("pending")]
        if not pend:
            return 0
        if classifier is None:
            from app.engine import engine
            classifier = engine.classifier
        done = 0
        for aid, a in pend:
            sid = a["source"]
            if sid == "bm7":
                path = os.path.join(self._dir("bm7"), f"{a['dir']}.list")
                rules = list(self._bm7_rules(path))
                doms = [v for k, v in rules if k in ("DOMAIN", "DOMAIN-SUFFIX") and _is_domain(v)]
                ips = []
                for k, v in rules:
                    if k in ("IP-CIDR", "IP-CIDR6"):
                        try:
                            ips.append(str(ipaddress.ip_network(v, strict=False).network_address))
                        except ValueError:
                            pass
            else:
                path = os.path.join(self._dir(sid), f"{a['list']}.txt")
                doms, ips = self._cat_domains(path), []
            if not os.path.exists(path):
                continue
            app, app_share, cat, cat_share, n = _vote(classifier, self.category, doms, ips)
            # 小目录（只有几条）认出一半以上也算数
            enough = n >= VOTE_MIN or (n >= 2 and n * 2 >= len(doms) + len(ips))
            if sid == "bm7":
                name = a["dir"]
                if enough and app_share >= VOTE_APP and app in classifier.apps:
                    entry = {"extend": app, "by": "vote"}
                elif enough and cat_share >= VOTE_CAT:
                    entry = {"category": cat, "name": name, "name_en": name, "by": "vote"}
                else:
                    entry = {"category": guess_category(name)[0], "name": name, "name_en": name, "by": "name"}
                self._auto[aid] = {"source": "bm7", "dir": name, **entry}
            else:
                name, guess = a["list"], a["category"]
                if enough and cat != guess and cat_share >= VOTE_CAT:
                    self._auto[aid] = {"source": sid, "list": name, "rejected": True, "vote": cat}
                else:
                    entry = {"source": sid, "list": name, "category": guess, "name": name, "name_en": name}
                    gen = classifier.apps.get(f"gen_{guess}")
                    if gen is not None and gen.category == guess:
                        entry["app"] = gen.id   # 并到该类的“其他 xx 网站”，不多建应用
                    self._auto[aid] = entry
            done += 1
        if done:
            self._save_auto()
            self._map = None   # 让 map 重新合并，新应用 / 新目录立即生效
        return done

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
