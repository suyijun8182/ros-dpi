"""时间分桶与统计区间（今日 / 本周 / 本月）。周从周一开始，按配置时区计算。"""
import time
from datetime import datetime, timedelta

from app.config import get_settings


def minute_bucket(ts: float) -> int:
    return int(ts) // 60 * 60


def hour_bucket(ts: float) -> int:
    # 小时按 UTC 对齐；整小时偏移的时区（如 Asia/Shanghai）与本地整点一致
    return int(ts) // 3600 * 3600


def day_bucket(ts: float) -> int:
    z = get_settings().zone
    d = datetime.fromtimestamp(ts, z)
    return int(d.replace(hour=0, minute=0, second=0, microsecond=0).timestamp())


def range_bounds(rng: str, now: float | None = None) -> tuple[int, int]:
    """返回 [start, end) 的 epoch 秒。rng: today | yesterday | week | month | last7 | last30。"""
    now = now or time.time()
    z = get_settings().zone
    d = datetime.fromtimestamp(now, z).replace(hour=0, minute=0, second=0, microsecond=0)
    end = int(now) + 1
    if rng == "today":
        start = d
    elif rng == "yesterday":
        start = d - timedelta(days=1)
        end = int(d.timestamp())
    elif rng == "week":
        start = d - timedelta(days=d.weekday())
    elif rng == "month":
        start = d.replace(day=1)
    elif rng == "last7":
        start = d - timedelta(days=6)
    elif rng == "last30":
        start = d - timedelta(days=29)
    else:
        raise ValueError(f"unknown range {rng}")
    return int(start.timestamp()), end
