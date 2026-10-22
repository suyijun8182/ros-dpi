"""终端类型识别：手机 / 平板 / 电脑 / 电视 / 游戏机 / 摄像头 / 智能设备 / NAS / 网络设备。

依据（越靠前越可信）：主机名 → MAC 厂商（IEEE OUI 公开数据）→ 最近用过的应用 → 随机 MAC（手机、平板的隐私地址）。
结果写进 hosts 表（dtype_auto / vendor），每小时刷新一次；用户手动指定的 dtype 优先。
"""
import csv
import os
import re
import threading
import time

import httpx

from app.config import get_settings

URL = "https://standards-oui.ieee.org/oui/oui.csv"
MAX_AGE = 30 * 86400
TYPES = ("phone", "tablet", "computer", "tv", "console", "camera", "iot", "nas", "network", "unknown")

# 主机名规则：(正则, 类型)，按顺序取第一条命中的
HOSTNAME_RULES = [
    (r"ipad", "tablet"), (r"iphone", "phone"), (r"apple-?tv|appletv", "tv"),
    (r"macbook|imac|mac-?mini|mac-?pro|mac-?studio", "computer"),
    (r"\b(tab|pad)\b|matepad|galaxy-?tab|xiaomi-?pad|mipad", "tablet"),
    (r"nintendo|switch|ps[345]\b|playstation|xbox|steam-?deck", "console"),
    (r"mitv|mi-?box|\btv\b|-tv\b|tv-|android-?tv|chromecast|hisense|skyworth|letv|sony-?bravia|roku|fire-?tv", "tv"),
    (r"camera|\bipc\b|ipcam|hikvision|dahua|ezviz|imou|xiaomi-?cam|chuangmi|isa-camera|c[0-9]{2,3}[a-z]?-", "camera"),
    (r"synology|diskstation|\bds[0-9]{3,4}|qnap|truenas|unraid|\bnas\b|-nas\b|nas-|omv|proxmox|\bpve\b", "nas"),
    (r"openwrt|lede|mikrotik|routeros|\bap\b|-ap\b|ap-|router|unifi|tplink|tp-link|ruijie|h3c|wifi-?ext|mesh", "network"),
    (r"^esp[_-]|esp32|esp8266|tuya|yeelink|lumi-|mijia|miot|zhimi|roborock|dreame|deerma|xiaomi-.*-(plug|light|fan|heater)|shelly|sonoff|"
     r"midea|gree|haier|aqara|broadlink|wemo|hue|smartthings|ewelink", "iot"),
    (r"android|redmi|xiaomi|^mi-|oneplus|huawei|honor|oppo|vivo|realme|iqoo|galaxy|samsung-sm|sm-[a-z][0-9]|meizu|pixel|nokia", "phone"),
    (r"desktop-|laptop-|^win-|windows|-pc\b|\bpc-|thinkpad|surface|ubuntu|debian|fedora|archlinux|manjaro|deepin|uos", "computer"),
]
_HOST_RE = [(re.compile(p, re.I), t) for p, t in HOSTNAME_RULES]

# 厂商关键字 → 类型（厂商只生产这一类设备时才放进来）
VENDOR_TYPES = [
    (r"hikvision|dahua|ezviz|zhejiang uniview|imou|reolink|axis comm", "camera"),
    (r"espressif|tuya|shelly|sonoff|itead|broadlink|lumi united|aqara|yeelight|roborock|dreame|ecovacs|midea|gree electric|haier|"
     r"philips lighting|signify|tp-link.*(tapo|kasa)", "iot"),
    (r"nintendo|sony interactive|microsoft.*xbox", "console"),
    (r"synology|qnap|western digital|seagate", "nas"),
    (r"mikrotik|routerboard|ubiquiti|tp-link|ruijie|h3c|new h3c|cisco|juniper|netgear|aruba|tenda|mercury|fiberhome|zte|"
     r"shenzhen gongjin|openwrt", "network"),
    (r"hisense|tcl|skyworth|konka|changhong|roku|sharp", "tv"),
]
_VENDOR_RE = [(re.compile(p, re.I), t) for p, t in VENDOR_TYPES]

# 用过的应用 → 类型线索：只放“这类设备才会用”的；智能设备另按“只用智能家居 / 摄像头类应用”判断（手机上的米家 App 也会访问同样的域名）
APP_HINTS = {"windows_update": "computer", "xbox": "console", "playstation": "console", "nintendo": "console"}
NEUTRAL_GROUPS = {"base", "unknown"}  # 系统、DNS、未识别：判断时不计


# 厂商全名缩短：去掉公司后缀，常见的直接给短名
SHORT = [(r"apple", "Apple"), (r"xiaomi|beijing xiaomi", "Xiaomi"), (r"huawei", "Huawei"), (r"honor device", "Honor"),
         (r"guangdong oppo|oppo", "OPPO"), (r"vivo mobile", "vivo"), (r"samsung", "Samsung"), (r"oneplus", "OnePlus"),
         (r"realme", "realme"), (r"lenovo", "Lenovo"), (r"dell", "Dell"), (r"hewlett|hp inc", "HP"), (r"intel", "Intel"),
         (r"microsoft", "Microsoft"), (r"google", "Google"), (r"amazon", "Amazon"), (r"sony", "Sony"),
         (r"nintendo", "Nintendo"), (r"espressif", "Espressif"), (r"tuya", "Tuya"), (r"hikvision", "Hikvision"),
         (r"dahua", "Dahua"), (r"tp-link", "TP-Link"), (r"mikrotik|routerboard", "MikroTik"), (r"synology", "Synology"),
         (r"qnap", "QNAP"), (r"ubiquiti", "Ubiquiti"), (r"realtek", "Realtek"), (r"azurewave", "AzureWave"),
         (r"liteon|lite-on", "Lite-On"), (r"murata", "Murata"), (r"hon hai|foxconn", "Foxconn")]
_SHORT_RE = [(re.compile(p, re.I), n) for p, n in SHORT]


def short_vendor(name: str) -> str:
    for r, n in _SHORT_RE:
        if r.search(name):
            return n
    s = re.sub(r"[,.]?\s*(co\.?,?\s*ltd\.?|ltd\.?|inc\.?|corp(oration)?\.?|limited|gmbh|s\.?a\.?|llc|company|technolog(y|ies)|"
               r"electronics?|communications?|international)\b", "", name, flags=re.I)
    return re.sub(r"\s+", " ", s).strip(" ,.") or name


def is_random_mac(mac: str | None) -> bool:
    """本地管理地址（第二个十六进制位是 2/6/A/E）：手机、平板的隐私 MAC 基本都是这种"""
    return bool(mac) and len(mac) >= 2 and mac[1].upper() in "26AE"


class OuiDb:
    def __init__(self):
        self.vendors: dict[str, str] = {}
        self.updated = 0
        self.error = ""
        self.lock = threading.Lock()

    @staticmethod
    def path() -> str:
        return os.path.join(os.environ.get("DATA_DIR", "data"), "oui.csv")

    def load(self, path: str | None = None) -> bool:
        path = path or self.path()
        if not os.path.exists(path):
            return False
        m = {}
        with open(path, encoding="utf-8", errors="replace") as f:
            for row in csv.reader(f):
                if len(row) >= 3 and len(row[1]) == 6 and row[0] == "MA-L":
                    m[row[1].upper()] = row[2].strip()
        with self.lock:
            self.vendors = m
            self.updated = int(os.path.getmtime(path))
        return bool(m)

    def update(self, force: bool = False) -> bool:
        path = self.path()
        if not force and os.path.exists(path) and time.time() - os.path.getmtime(path) < MAX_AGE:
            if not self.vendors:
                self.load(path)
            return False
        tmp = path + ".part"
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            r = httpx.get(URL, timeout=120, follow_redirects=True, headers={"User-Agent": "ros-dpi"})
            r.raise_for_status()
            if b"Registry,Assignment" not in r.content[:200]:
                raise ValueError("不是 IEEE OUI CSV")
            with open(tmp, "wb") as f:
                f.write(r.content)
            os.replace(tmp, path)
            self.error = ""
        except Exception as e:  # noqa: BLE001  没有外网时保留旧数据
            self.error = f"{type(e).__name__}: {str(e)[:160]}"
            if os.path.exists(tmp):
                os.remove(tmp)
            if not self.vendors:
                self.load(path)
            return False
        return self.load(path)

    def lookup(self, mac: str | None) -> str:
        if not mac or is_random_mac(mac):
            return ""
        return self.vendors.get(mac.replace(":", "").replace("-", "").upper()[:6], "")

    def status(self) -> dict:
        return {"rows": len(self.vendors), "updated": self.updated, "error": self.error}


oui = OuiDb()


def _by_apps(apps: set[str]) -> str | None:
    from app.engine import engine
    cl = engine.classifier
    hints = {APP_HINTS[a] for a in apps if a in APP_HINTS}
    if len(hints) == 1:
        return hints.pop()
    cats = {cl.app_info(a).category for a in apps}
    groups = {cl.category_info(c)["group"] for c in cats} - NEUTRAL_GROUPS
    if groups == {"iot"}:
        return "camera" if "camera" in cats else "iot"
    return None


def classify(mac: str | None, hostname: str | None, apps: set[str] | None = None, vendor_full: str | None = None) -> tuple[str, str, str]:
    """返回 (类型, 厂商短名, 依据：hostname / vendor / apps / random / "")"""
    vendor_full = vendor_full if vendor_full is not None else oui.lookup(mac)
    vendor = short_vendor(vendor_full) if vendor_full else ""
    name = (hostname or "").strip()
    if name:
        for r, t in _HOST_RE:
            if r.search(name):
                return t, vendor, "hostname"
    if vendor_full:
        for r, t in _VENDOR_RE:
            if r.search(vendor_full):
                return t, vendor, "vendor"
    if apps:
        t = _by_apps(apps)
        if t:
            return t, vendor, "apps"
    if vendor in ("Apple", "Xiaomi", "Huawei", "Honor", "OPPO", "vivo", "Samsung", "OnePlus", "realme"):
        return "phone", vendor, "vendor"
    if is_random_mac(mac):
        return "phone", vendor, "random"
    return "unknown", vendor, ""


def refresh_all():
    """按最近 7 天用过的应用重新识别所有终端，结果写回 hosts 表"""
    from sqlalchemy import select

    from app import database, timeutil
    from app.models import Host, TrafficDay
    if not database.is_configured():
        return 0
    since = timeutil.range_bounds("last7")[0]
    n = 0
    with database.session() as db:
        apps: dict[str, set] = {}
        for host, app in db.execute(select(TrafficDay.host, TrafficDay.app).where(TrafficDay.ts >= since)
                                    .group_by(TrafficDay.host, TrafficDay.app)):
            apps.setdefault(host, set()).add(app)
        for h in db.query(Host):
            t, v, _by = classify(h.mac, h.hostname, apps.get(h.key))
            if (h.dtype_auto, h.vendor) != (t, v or None):
                h.dtype_auto, h.vendor = t, v or None
                n += 1
        db.commit()
    return n


def startup():
    if get_settings().oui_db:
        oui.update()
    else:
        oui.load()
    refresh_all()

