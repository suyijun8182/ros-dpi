"""第三方规则库（运行时下载到数据目录，不进镜像和仓库）：

- blackmatrix7/ios_rule_script（GPL-2.0）：按应用整理的规则。目录名到 ROS-DPI 应用的对应关系在 bm7_map.yaml，
  只用其中列出的目录；给已有应用补内置库和 v2fly 里没有的域名、IP 段，另新增约 100 个应用。每周更新。
- Hagezi DNS blocklists（GPL-3.0）：成人、博彩、VPN/代理、社交、广告、各厂商设备遥测等专项分类列表。每天更新。
- UT1（Université Toulouse Capitole，CC BY-SA 4.0）：游戏、购物、新闻、求职、银行等分类列表。每天更新。

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
    ("publicite", "ads"),
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

    @property
    def map(self) -> dict:
        if self._map is None:
            self._map = load_map()
        return self._map

    def _dir(self, sid: str) -> str:
        return os.path.join(os.environ.get("DATA_DIR", "data"), "lists", sid)

    def _files(self, sid: str) -> list[tuple[str, str]]:
        """(本地文件名, 下载地址)"""
        if sid == "bm7":
            return [(f"{n}.list", BM7_URL.format(urllib.parse.quote(n))) for n in sorted(self.map["owner"])]
        spec, url = (HAGEZI, HAGEZI_URL) if sid == "hagezi" else (UT1, UT1_URL)
        return [(f"{n}.txt", url.format(n)) for n, _app in spec]

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
        spec = HAGEZI if sid == "hagezi" else UT1
        out = []
        for name, app in spec:
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
