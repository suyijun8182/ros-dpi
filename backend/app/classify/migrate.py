"""0.6.3 起应用大类改成维盟的 17 类（debug12），小类 ID 不变。这里把旧的 10 个大类 ID 换成新的：

- 分析设置里“算娱乐”的列表：旧大类展开成它原来包含的小类，含义不变
- 审计规则：按大类的规则换成最接近的新大类；大流量外发限定的大类同样处理
"""
import json

from sqlalchemy import select

# 旧大类原来包含的小类（0.6.2 及以前）
OLD_GROUPS = {
    "media": ["video", "short_video", "live", "music"],
    "social": ["im", "social", "voip", "mail"],
    "transfer": ["download", "cloud", "update", "app_store"],
    "work": ["work", "meeting", "dev", "remote", "ai", "education"],
    "life": ["shopping", "life", "travel", "finance", "bank", "stock"],
    "info": ["news", "search", "reading", "site", "adult", "gambling", "cn_web"],
    "iot": ["iot", "camera"],
    "base": ["network", "system", "cdn", "proxy", "security", "ads", "web", "cn_net"],
    "game": ["game", "mobile_game", "console_game", "game_tool"],
}
# 按大类的审计规则：换成最接近的新大类
GROUP_MAP = {"media": "tv", "social": "im", "transfer": "p2p", "work": "common", "life": "mobile", "info": "http",
             "iot": "special", "base": "common"}
SCHEMA = 2


def expand_leisure(items: list[str]) -> list[str]:
    out = []
    for x in items:
        for c in OLD_GROUPS.get(x, [x]):
            if c not in out:
                out.append(c)
    return out


def run(db):
    """启动时执行一次（幂等）：迁移后在 settings 里记 group_schema=2"""
    from app.models import AuditRule, Setting
    mark = db.get(Setting, "group_schema")
    if mark and mark.value == str(SCHEMA):
        return
    row = db.get(Setting, "analysis")
    if row and row.value:
        try:
            cfg = json.loads(row.value)
            if cfg.get("leisure"):
                cfg["leisure"] = expand_leisure(cfg["leisure"])
                row.value = json.dumps(cfg, ensure_ascii=False)
        except ValueError:
            pass
    n = 0
    for r in db.execute(select(AuditRule).where(AuditRule.kind.in_(("group", "upload")))).scalars():
        if r.value in GROUP_MAP:
            r.value = GROUP_MAP[r.value]
            n += 1
    if mark is None:
        db.add(Setting(key="group_schema", value=str(SCHEMA)))
    else:
        mark.value = str(SCHEMA)
    db.commit()
    if n:
        print(f"[db] 应用大类改为 17 类：已迁移 {n} 条审计规则", flush=True)
