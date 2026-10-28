"""未识别域名的归类助手（debug26）：匹配范围、应用推荐、忽略列表。

匹配范围：默认按主域名（含所有子域名）建规则；公共 CDN、云托管、动态域名这类大家共用的后缀，
按主域名会把整个 CDN 都归给一个应用，所以主域名往下多取一段、默认改用完整域名。
推荐：同主域名下已经认出来的其他子域名 > 本地 / 社区学习库 > 分类列表（Hagezi / UT1）> 域名里的应用关键词。
忽略：不想管的域名（测速、探活、乱码域名）不再列在 Top 里，流量照旧算未识别；存在设置表 unknown_ignore。
"""
import json
import time

from sqlalchemy import func, select

from app import stats
from app.models import HostDomainDay, Setting
from app.reclass import _vague

IGNORE_KEY = "unknown_ignore"
# 多家共用的后缀：主域名说明不了是哪个应用
SHARED_SUFFIXES = (
    "cloudfront.net", "akamaized.net", "akamaihd.net", "akamai.net", "edgekey.net", "edgesuite.net",
    "fastly.net", "fastlylb.net", "azureedge.net", "azurefd.net", "azurewebsites.net", "trafficmanager.net",
    "cloudflare.net", "workers.dev", "pages.dev", "r2.dev", "b-cdn.net", "cdn77.org", "llnwd.net",
    "amazonaws.com", "elb.amazonaws.com", "appspot.com", "googleusercontent.com", "web.app", "firebaseapp.com",
    "github.io", "vercel.app", "netlify.app", "herokuapp.com", "onrender.com", "fly.dev",
    "myqcloud.com", "tencent-cloud.net", "dnsv1.com", "cdntip.com", "aliyuncs.com", "alikunlun.com",
    "kunlunca.com", "kunlunsl.com", "alicdn.com", "ksyuncdn.com", "qiniucdn.com", "qiniudns.com",
    "bdydns.com", "bcebos.com", "wscdns.com", "chinacache.net", "cdn20.com", "ourwebcdn.com",
    "cdnhwc1.com", "cdnhwc2.com", "hwcdn.net", "volcfcdn.com", "bytecdn.cn", "jomodns.com",
    "dpdns.org", "duckdns.org", "ddns.net", "no-ip.org", "noip.me", "synology.me", "myds.me",
    "quickconnect.to", "dynv6.net", "dyndns.org", "3322.org", "oray.net", "vicp.net", "f3322.net",
)
SHARED_SUFFIXES = tuple(sorted(SHARED_SUFFIXES, key=len, reverse=True))   # 长的先比：elb.amazonaws.com 先于 amazonaws.com
SUGGEST_MAX = 3


def shared_suffix(domain: str) -> str | None:
    d = domain.lower().strip(".")
    return next((s for s in SHARED_SUFFIXES if d == s or d.endswith("." + s)), None)


def scope(domain: str) -> dict:
    """匹配范围：base = 主域名（共用后缀往下多取一段），default = 默认选哪个"""
    d = domain.lower().strip(".")
    sfx = shared_suffix(d)
    if sfx:
        extra = d[: -len(sfx) - 1].split(".")[-1] if d != sfx else ""
        base = f"{extra}.{sfx}" if extra else d
    else:
        base = stats.base_domain(d)
    return {"domain": d, "base": base, "default": "full" if sfx else "base", "shared": sfx}


def suggest(classifier, db, domain: str) -> list[dict]:
    """给一个未识别域名推荐最多 3 个应用，每个带来源说明（sibling / learn / list / keyword）"""
    from app.classify.lists import lists as extra_lists
    from app.classify.local import local
    d = domain.lower().strip(".")
    out: list[dict] = []

    def add(app, source):
        if app and app in classifier.apps and not _vague(classifier, app) and all(x["app"] != app for x in out):
            out.append({"app": app, "source": source})

    base = scope(d)["base"]
    t = HostDomainDay
    rows = db.execute(select(t.app, func.sum(t.bytes)).where(t.base == base, t.domain != d)
                      .group_by(t.app).order_by(func.sum(t.bytes).desc()).limit(10)).all()
    for app, _ in rows:
        add(app, "sibling")
    add(local.domain_app(d), "learn")
    add(extra_lists.category(d), "list")
    labels = [x for x in d.split(".")[:-1] if len(x) >= 4]
    if labels and len(out) < SUGGEST_MAX:
        hits = []
        for a in classifier.apps.values():
            k = a.id.lower()
            if len(k) >= 4 and k.isalnum() and any(k in x for x in labels):
                hits.append((-len(k), a.id))
        for _, aid in sorted(hits)[:SUGGEST_MAX]:
            add(aid, "keyword")
    return out[:SUGGEST_MAX]


# ---------- 忽略列表 ----------
def ignored(db) -> list[dict]:
    row = db.get(Setting, IGNORE_KEY)
    try:
        items = json.loads(row.value) if row and row.value else []
    except ValueError:
        items = []
    return [x for x in items if isinstance(x, dict) and x.get("pattern")]


def _save(db, items):
    value = json.dumps(items, ensure_ascii=False)
    row = db.get(Setting, IGNORE_KEY)
    if row is None:
        db.add(Setting(key=IGNORE_KEY, value=value))
    else:
        row.value = value


def ignore(db, patterns: list[str]):
    items = ignored(db)
    have = {x["pattern"] for x in items}
    now = int(time.time())
    for p in patterns:
        if p not in have:
            items.append({"pattern": p, "created": now})
            have.add(p)
    _save(db, items)


def unignore(db, pattern: str) -> bool:
    items = ignored(db)
    left = [x for x in items if x["pattern"] != pattern]
    _save(db, left)
    return len(left) != len(items)


def matches(pattern: str, domain: str) -> bool:
    return domain == pattern or domain.endswith("." + pattern)
