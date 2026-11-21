"""多站点（0.7.0）：请求的当前站点。

- ?site=<slug> 选站点；不传时用第一个能看的站点（单站点部署、以及升级前就在用的 API 令牌，不传也照常工作）；
- 管理员和 API 令牌能看全部站点，普通用户只能看被授权的（user_sites）；
- 选定后写进 db.info["site"]，这个请求里的 ORM 查询自动按站点过滤（见 scoping.py）。
"""
import time
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import database
from app.database import get_db
from app.models import DEFAULT_SITE, User, UserSite
from app.scoping import set_site
from app.security import current_user

_cache: dict[str, tuple[frozenset | None, float]] = {}   # username -> (能看的站点，None = 全部; 缓存时间)


def forget():
    _cache.clear()


def allowed_sites(username: str, role: str | None) -> frozenset | None:
    """None 表示全部站点"""
    if role == "admin" or username.startswith("api:"):
        return None
    hit = _cache.get(username)
    if hit and time.time() - hit[1] < 30:
        return hit[0]
    with database.session() as db:
        uid = db.scalar(select(User.id).where(User.username == username))
        slugs = frozenset(db.scalars(select(UserSite.site).where(UserSite.user_id == uid)).all()) if uid else frozenset()
    _cache[username] = (slugs, time.time())
    return slugs


def visible_sites(request: Request, username: str) -> list[str]:
    """按排序列出这个用户能看的站点（含停用的：停用站点的历史数据仍可查）"""
    from app.sites import registry
    if len(registry.info) <= 1:
        # 只有一个站点（单站点部署）：没有站点授权这回事，普通用户照 0.6.x 一样能看（授权界面也不显示）
        return list(registry.info)
    allowed = allowed_sites(username, getattr(request.state, "role", None))
    return [s for s in registry.info if allowed is None or s in allowed]


@dataclass
class SiteCtx:
    slug: str
    name: str

    @property
    def engine(self):
        from app.sites import registry
        return registry.get(self.slug) or registry.get(DEFAULT_SITE)

    @property
    def poller(self):
        from app.sites import registry
        return registry.poller(self.slug) or registry.poller(DEFAULT_SITE)


def site_ctx(request: Request, site: str | None = Query(None, max_length=32),
             user: str = Depends(current_user), db: Session = Depends(get_db)) -> SiteCtx:
    from app.sites import registry
    vis = visible_sites(request, user)
    if site:
        if site not in registry.info:
            raise HTTPException(404, "站点不存在")
        if site not in vis:
            raise HTTPException(403, "没有这个站点的权限")
        slug = site
    elif vis:
        slug = vis[0]
    else:
        raise HTTPException(403, "账号还没有被授权任何站点，请联系管理员")
    set_site(db, slug)
    request.state.site = slug
    return SiteCtx(slug, registry.name(slug))


def site_engine(db):
    """当前请求站点的 Engine（实时速率、会话、DNS 映射等内存状态）"""
    from app.scoping import site_of
    from app.sites import registry
    return registry.get(site_of(db)) or registry.get(DEFAULT_SITE)


def site_poller(db):
    from app.scoping import site_of
    from app.sites import registry
    return registry.poller(site_of(db)) or registry.poller(DEFAULT_SITE)
