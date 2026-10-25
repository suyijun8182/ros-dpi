"""把 v2fly/domain-list-community（MIT 许可）转换成 ROS-DPI 的应用规则（apps_v2fly.yaml）。

两种用法：
- 发版前：python scripts/import_v2fly.py [--src <data目录>]，更新打包进镜像的 backend/app/classify/apps_v2fly.yaml；
- 运行时：app.classify.updater 每天检查 v2fly 的最新提交，有更新就下载、转换、自检后写到数据目录并热加载。

转换规则：
- v2fly 的每个非 category 列表 = 一个应用；列表里直接写的域名归这个应用（include 的子列表各自是独立应用）。
- 应用的小类由 "哪个 category-* 列表 include 了它" 决定（include 层级越浅越优先，再按 CAT_MAP 的先后），
  category 列表里直接写的域名，按前面的注释分组成应用（注释通常是公司或产品名）。
- 与手工维护的 apps.yaml 里某个应用重合度高的列表，域名合并进那个应用（不另建应用）。
- 带 @ads / @telemetry 属性的域名归到"广告与统计"。
- domain / 无前缀 = 后缀匹配；full: = 精确匹配；keyword: / regexp: 不导入（逐条正则太慢，也容易误判）。
- 手工规则优先：同一个域名两边都有时以 apps.yaml 为准。
"""
import argparse
import io
import os
import re
import sys
import tarfile
from collections import defaultdict

import httpx
import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
CURATED = os.path.join(HERE, "apps.yaml")
BUNDLED = os.path.join(HERE, "apps_v2fly.yaml")
REPO = "v2fly/domain-list-community"
TARBALL = "https://codeload.github.com/" + REPO + "/tar.gz/{ref}"
COMMITS = "https://api.github.com/repos/" + REPO + "/commits/master"

# v2fly 分类 → ROS-DPI 小类。顺序即优先级：一个列表同时属于多个分类时，取层级最浅、排在前面的。
CAT_MAP = [
    ("category-ads", "ads"), ("category-ads-all", "ads"), ("category-ads-and-telemetry", "ads"), ("category-telemetry", "ads"),
    ("category-game-accelerator-cn", "game_tool"), ("category-enhance-gaming", "game_tool"),
    ("category-game-platforms-download", "game"), ("category-games-cn", "game"), ("category-games-!cn", "game"), ("category-games", "game"),
    ("category-bank-*", "bank"), ("category-securities-cn", "stock"), ("category-bourse-ir", "stock"),
    ("category-payment-ir", "finance"), ("category-cryptocurrency", "finance"), ("category-finance", "finance"),
    ("category-netdisk-*", "cloud"), ("category-pt", "download"), ("category-public-tracker", "download"),
    ("category-android-app-download", "app_store"), ("category-browser-!cn", "update"),
    ("category-ai-*", "ai"), ("category-remote-control", "remote"),
    ("category-dev", "dev"), ("category-dev-cn", "dev"), ("category-container", "dev"),
    ("category-collaborate-cn", "work"), ("category-documents-cn", "work"), ("category-password-management", "security"),
    ("category-antivirus", "security"), ("category-network-security-cn", "security"),
    ("category-proxy-tunnels", "proxy"), ("category-vpnservices", "proxy"), ("category-anticensorship", "proxy"),
    ("category-voip", "voip"), ("category-stun", "voip"), ("category-communication", "im"),
    ("category-social-media-*", "social"), ("category-forums*", "social"), ("category-blog-cn", "social"),
    ("category-novel", "reading"), ("category-acg", "reading"),
    ("category-mooc-cn", "education"), ("category-education-*", "education"), ("category-scholar-*", "education"),
    ("category-olympiad-in-informatics", "education"), ("category-cas", "education"),
    ("category-ecommerce*", "shopping"), ("category-retail-ru", "shopping"), ("category-shopping-ir", "shopping"),
    ("category-food-cn", "life"), ("category-logistics-cn", "life"), ("category-hospital-cn", "life"),
    ("category-medicine-ru", "life"), ("category-automobile-cn", "life"),
    ("category-travel-*", "travel"),
    ("category-emby", "video"), ("category-porn", "adult"),
    ("category-media", "news"), ("category-media-*", "news"), ("category-tech-media*", "news"), ("category-news-ir", "news"),
    ("category-wiki-cn", "news"),
    ("category-doh", "network"), ("category-httpdns-cn", "network"), ("category-ntp*", "network"),
    ("category-speedtest", "network"), ("category-ip-geo-detect", "network"), ("category-ddns", "network"),
    ("category-cdn-*", "cdn"),
    # 范围很宽的放最后：影音娱乐里混着游戏、音乐、视频，只在没有更具体分类时使用
    ("category-entertainment-cn", "video"), ("category-entertainment", "video"), ("category-entertainment-ru", "video"),
]
# 没有被任何分类收录的列表（多是公司总表，如 tencent、alibaba）归到"网站服务"
FALLBACK_CAT = "site"
# 名称里含这些词的列表，按名称补一个更准确的小类
NAME_HINTS = [
    (r"music|spotify|tidal|deezer|podcast|radio", "music"), (r"(^|-)live($|-)|twitch|huya|douyu", "live"),
    (r"(^|-)(video|tv|movie|film|anime)($|-)|netflix|hulu|disney|hbo|primevideo|youku|iqiyi|mgtv", "video"),
    (r"(^|-)(mail|email)($|-)|protonmail", "mail"), (r"(^|-)bank($|-)", "bank"),
]
# 分类文件里按注释分组的应用：注释（多为中文名）里含这些词时，改用更准确的小类
LABEL_HINTS = [
    (r"小说|阅读|书城|漫画|文学", "reading"), (r"音乐|电台|播客|FM\b", "music"), (r"直播", "live"),
    (r"游戏|手游|电竞", "game"), (r"银行|Bank", "bank"), (r"证券|基金|期货|股票", "stock"),
    (r"医院|医疗|医学|健康", "life"), (r"大学|学院|中学|教育|学习|题库|考试|University", "education"),
    (r"视频|影视|电影|动漫|番剧", "video"),
]


def cat_matches(pattern: str, name: str) -> bool:
    return re.fullmatch(re.escape(pattern).replace(r"\*", ".*"), name) is not None


def strip_comment(line: str) -> tuple[str, str]:
    body, _, comment = line.partition("#")
    return body.strip(), comment.strip().lstrip("#").strip()


def parse_list(text: str):
    """返回 (entries, includes)。entries: [(kind, value, attrs, comment)]，kind = suffix | full。"""
    entries, includes = [], []
    last_comment = ""
    for raw in text.splitlines():
        body, comment = strip_comment(raw)
        if not body:
            if comment:
                last_comment = comment
            elif not raw.strip():
                last_comment = ""  # 空行结束一个注释分组
            continue
        parts = body.split()
        rule, attrs = parts[0], [p[1:] for p in parts[1:] if p.startswith("@")]
        if rule.startswith("include:"):
            includes.append(rule[8:])
            continue
        kind, _, value = rule.rpartition(":")
        if kind in ("keyword", "regexp"):
            continue
        kind = "full" if kind == "full" else "suffix"
        value = value.lower().strip(".")
        if "." not in value or value.startswith("xn--") and value.count(".") == 0:
            continue
        entries.append((kind, value, attrs, comment or last_comment))
    return entries, includes


def clean_label(c: str) -> str:
    """注释 → 应用名：去掉 ICP 备案号、网址等杂项。"""
    c = re.sub(r"[一-龥]{1,2}(ICP|B2|公网安备)[^\s]*", "", c)
    c = re.sub(r"(ICP|B2)[\w-]*", "", c)
    c = re.sub(r"https?://\S+", "", c)
    c = re.sub(r"\s*#\S*", "", c)
    c = re.sub(r"\s+", " ", c).strip(" -:：,，#()（）《》")
    if c.count("(") != c.count(")"):
        c = c.split("(")[0].strip()
    return c[:40]


def hinted(label: str, cat: str) -> str:
    """宽泛分类（影音娱乐、网站服务、新闻）下，按名称关键词细分"""
    if cat not in ("video", "site", "news", "social"):
        return cat
    for pat, c in LABEL_HINTS:
        if re.search(pat, label, re.I):
            return c
    return cat


def latest_commit() -> dict:
    """v2fly master 的最新提交：{sha, date}"""
    r = httpx.get(COMMITS, timeout=20, headers={"Accept": "application/vnd.github+json"})
    r.raise_for_status()
    d = r.json()
    return {"sha": d["sha"], "date": d["commit"]["committer"]["date"]}


def fetch(ref: str = "master") -> dict[str, str]:
    """下载某个提交的源码包，返回 data/ 下的 {列表名: 内容}"""
    files = {}
    with httpx.Client(timeout=120, follow_redirects=True) as c:
        data = c.get(TARBALL.format(ref=ref)).raise_for_status().content
    with tarfile.open(fileobj=io.BytesIO(data)) as tf:
        for m in tf.getmembers():
            parts = m.name.split("/")
            if len(parts) == 3 and parts[1] == "data" and m.isfile():
                files[parts[2]] = tf.extractfile(m).read().decode("utf-8")
    return files


def load_dir(src: str) -> dict[str, str]:
    files = {}
    for n in os.listdir(src):
        with open(os.path.join(src, n), encoding="utf-8") as f:
            files[n] = f.read()
    return files


def read_source(path: str) -> dict | None:
    """读生成文件头里记录的来源提交：{sha, date}；没有记录返回 None"""
    try:
        with open(path, encoding="utf-8") as f:
            for _ in range(6):
                m = re.match(r"# source-commit: (\w+) (\S+)", f.readline())
                if m:
                    return {"sha": m.group(1), "date": m.group(2)}
    except OSError:
        pass
    return None


def convert(files: dict[str, str]) -> tuple[dict, dict]:
    """v2fly 的列表 → {"extend": [...], "apps": [...]}，以及统计 {apps, extend, domains, cats}"""
    lists = {n: parse_list(t) for n, t in files.items()}
    with open(CURATED, encoding="utf-8") as f:
        curated = yaml.safe_load(f)
    cur_domains: dict[str, str] = {}
    for app in curated["apps"]:
        for d in app.get("domains", []):
            cur_domains.setdefault(d.lower(), app["id"])
    cur_apps = {app["id"]: app for app in curated["apps"]}

    # 1. 每个列表属于哪个小类：从各个 category-* 出发做 BFS，记录层级
    best: dict[str, tuple[int, int, str]] = {}  # list -> (depth, cat_rank, our_cat)
    for rank, (pat, our) in enumerate(CAT_MAP):
        for cname in (n for n in lists if n.startswith("category-") and cat_matches(pat, n)):
            seen, frontier, depth = {cname}, [cname], 0
            while frontier:
                depth += 1
                nxt = []
                for n in frontier:
                    for inc in lists.get(n, ([], []))[1]:
                        if inc in seen or inc not in lists:
                            continue
                        seen.add(inc)
                        nxt.append(inc)
                        if not inc.startswith("category-"):
                            key = (depth, rank, our)
                            if inc not in best or key < best[inc]:
                                best[inc] = key
                frontier = nxt

    apps: list[dict] = []
    extend: dict[str, dict[str, set]] = defaultdict(lambda: {"domains": set(), "full": set()})
    ads = {"domains": set(), "full": set()}
    used_ids = set(cur_apps)

    def cover_app(value: str) -> str | None:
        """手工规则里按后缀覆盖了这个域名（含它本身）的应用"""
        parts = value.split(".")
        return next((cur_domains[x] for x in (".".join(parts[i:]) for i in range(len(parts) - 1)) if x in cur_domains), None)


    def add_domains(target: dict, entries, target_id: str | None = None):
        for kind, value, attrs, _c in entries:
            # 手工规则里已有同一个域名，或者已被同一应用的后缀覆盖：重复，跳过。
            # 被其他应用的后缀覆盖时保留（更具体，例如 qq.com 下的 lol.qq.com 属于腾讯游戏）
            if value in cur_domains or (target_id and cover_app(value) == target_id):
                continue
            if "ads" in attrs or "telemetry" in attrs:
                ads["full" if kind == "full" else "domains"].add(value)
            else:
                target["full" if kind == "full" else "domains"].add(value)

    def new_id(base: str) -> str:
        i = "v2_" + re.sub(r"[^a-z0-9]+", "_", base.lower()).strip("_")
        i = i[:44]
        n, k = i, 2
        while n in used_ids:
            n, k = f"{i}_{k}", k + 1
        used_ids.add(n)
        return n

    for name, (entries, _inc) in sorted(lists.items()):
        if not entries:
            continue
        if name.startswith("category-"):
            # 分类列表里直接写的域名：按注释分组成应用
            our = next((c for p, c in CAT_MAP if cat_matches(p, name)), None)
            if our is None or our == "ads":
                if our == "ads":
                    add_domains(ads, entries)
                continue
            groups: dict[str, list] = defaultdict(list)
            for e in entries:
                groups[clean_label(e[3]) or ""].append(e)
            for label, es in groups.items():
                # "Steam - 游戏下载[Akamai]" 这种注释，前半段就是已有应用的名字：并进去
                head = re.split(r"\s+-\s+|\[|（|\(", label)[0].strip().lower()
                same = next((i for i, x in cur_apps.items()
                             if head and head in (str(x["name"]).lower(), str(x.get("name_en", "")).lower())), None)
                if same:
                    add_domains(extend[same], es, same)
                    continue
                if not label:
                    label = "其他" + curated["categories"][our]["name"]
                rec = {"domains": set(), "full": set()}
                add_domains(rec, es)
                if rec["domains"] or rec["full"]:
                    apps.append({"id": new_id(f"{name.removeprefix('category-')}_{label}" if not re.search(r"[a-z]", label, re.I) else label),
                                 "name": label, "name_en": label, "category": hinted(label, our), **rec})
            continue

        # 普通列表 = 一个应用。和某个手工应用的域名重合较多时，合并进去
        own = [e for e in entries]
        hits = defaultdict(int)
        for _k, v, _a, _c in own:
            if (hit := cover_app(v)):
                hits[hit] += 1
        target_id = None
        if name.replace("-", "_") in cur_apps:
            target_id = name.replace("-", "_")
        elif hits and name in best:
            top, n = max(hits.items(), key=lambda x: x[1])
            if n >= 2 or n >= len(cur_apps[top].get("domains", [])) * 0.5:
                target_id = top
        if target_id:
            add_domains(extend[target_id], own, target_id)
            continue
        cat = best.get(name, (99, 99, FALLBACK_CAT))[2]
        if cat in ("video", FALLBACK_CAT):
            for pat, c in NAME_HINTS:
                if re.search(pat, name):
                    cat = c
                    break
        rec = {"domains": set(), "full": set()}
        add_domains(rec, own)
        if not rec["domains"] and not rec["full"]:
            continue
        # 只用第一条域名前的注释当中文名（后面的注释多是子产品说明）
        label = clean_label(own[0][3]) if re.search(r"[一-龥]", own[0][3]) else ""
        pretty = name.replace("-", " ").replace("!cn", "intl").title()
        apps.append({"id": new_id(name), "name": label or pretty, "name_en": pretty, "category": hinted(label or pretty, cat), **rec})

    # 同一域名只保留一个应用（前面的优先）
    taken: set[str] = set()

    def dedup(rec):
        for k in ("domains", "full"):
            vals = sorted(v for v in rec[k] if (k, v) not in taken)
            taken.update((k, v) for v in vals)
            rec[k] = vals

    out_ext = []
    for aid in sorted(extend):
        dedup(extend[aid])
        if extend[aid]["domains"] or extend[aid]["full"]:
            out_ext.append({"extend": aid, **{k: v for k, v in extend[aid].items() if v}})
    dedup(ads)
    out_ext.append({"extend": "ads", **{k: v for k, v in ads.items() if v}})
    out_apps = []
    for app in apps:
        dedup(app)
        if app["domains"] or app["full"]:
            out_apps.append({k: v for k, v in app.items() if v != []})

    n_dom = sum(len(x.get("domains", [])) + len(x.get("full", [])) for x in out_apps + out_ext)
    cats = defaultdict(int)
    for x in out_apps:
        cats[x["category"]] += 1
    return {"extend": out_ext, "apps": out_apps}, {"apps": len(out_apps), "extend": len(out_ext), "domains": n_dom,
                                                    "cats": dict(cats)}


def write(doc: dict, path: str, source: dict | None = None):
    header = ("# 由 v2fly/domain-list-community 自动转换（app/classify/v2fly.py），请勿手工修改。\n"
              "# 数据来源：https://github.com/v2fly/domain-list-community （MIT License，"
              "Copyright (c) 2019-present V2Fly Community）\n"
              "# extend: 给 apps.yaml 里已有应用补充域名；apps: 新应用。full = 精确匹配，domains = 后缀匹配。\n")
    if source:
        header += f"# source-commit: {source['sha']} {source['date']}\n"
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(header)
        yaml.safe_dump(doc, f, allow_unicode=True, sort_keys=False, width=200, default_flow_style=None)


def main():
    ap = argparse.ArgumentParser(description="把 v2fly/domain-list-community 转换成 ROS-DPI 应用规则")
    ap.add_argument("--src", help="v2fly 仓库的 data 目录；不填则下载最新提交")
    ap.add_argument("--out", default=BUNDLED)
    a = ap.parse_args()
    source = None
    if a.src:
        files = load_dir(a.src)
    else:
        source = latest_commit()
        print("下载", REPO, source["sha"][:10], source["date"], file=sys.stderr)
        files = fetch(source["sha"])
    doc, st = convert(files)
    write(doc, a.out, source)
    print(f"新应用 {st['apps']} 个，补充已有应用 {st['extend']} 个，域名 {st['domains']} 条 → {a.out}", file=sys.stderr)
    print("按小类：", dict(sorted(st["cats"].items(), key=lambda x: -x[1])), file=sys.stderr)


if __name__ == "__main__":
    main()
