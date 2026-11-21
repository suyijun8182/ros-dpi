"""多站点（0.7.0）：站点注册表。

- 一个站点一个 Engine（实时状态、内网网段、IP→MAC、会话、访问都各自独立），识别器共用；
- 按 UDP 源 IP 认出数据包属于哪个站点。只有一个启用站点、且它没登记源 IP 时接收所有来源（与 0.6.x 相同）；
- 没对上任何站点的包丢弃，按 (IP, 类型) 计数，每分钟落库到 unknown_sources，设置页里可以一键登记。
"""
import ipaddress
import threading
import time

from sqlalchemy import delete, select

from app import database, ros_poller, scoping  # noqa: F401  scoping：注册会话级站点过滤
from app.config import get_settings
from app.engine import Engine, engine as default_engine
from app.ros_poller import RosPoller, poller as default_poller
from app.models import DEFAULT_SITE, Site, UnknownSource

UNKNOWN_DAYS = 7
MAX_UNKNOWN = 256


def norm_ip(text: str) -> str | None:
    try:
        return str(ipaddress.ip_address(text.strip()))
    except ValueError:
        return None


def ros_values(row) -> dict:
    """站点行里的 RouterOS 配置，换成 ros_poller.effective 认的格式（没保存过的为 None）"""
    if row is None:
        return {}
    return {"ros_url": row.ros_url, "ros_user": row.ros_user, "ros_password": row.ros_password,
            "ros_verify_tls": None if row.ros_verify_tls is None else ("1" if row.ros_verify_tls else "0")}


def split_sources(text: str | None) -> list[str]:
    out = []
    for part in (text or "").replace("\n", ",").split(","):
        ip = norm_ip(part) if part.strip() else None
        if ip and ip not in out:
            out.append(ip)
    return out


class SiteRegistry:
    def __init__(self):
        self.lock = threading.Lock()
        self.engines: dict[str, Engine] = {DEFAULT_SITE: default_engine}
        self.pollers: dict[str, RosPoller] = {DEFAULT_SITE: default_poller}
        self.info: dict[str, dict] = {DEFAULT_SITE: {"slug": DEFAULT_SITE, "name": "默认站点", "enabled": True,
                                                       "sources": [], "sort": 0}}
        self._by_ip: dict[str, str] = {}
        self.accept_all: str | None = DEFAULT_SITE   # 单站点且没登记源 IP 时，所有来源都归它
        self._unknown: dict[tuple[str, str], list[int]] = {}

    # ---------- 加载 ----------
    def load(self, db=None):
        """从 sites 表重新加载（启动、站点增删改后调用）"""
        if db is None:
            with database.session() as s:
                return self.load(s)
        rows = db.scalars(select(Site).order_by(Site.sort, Site.created, Site.slug)).all()
        self.apply([{"slug": r.slug, "name": r.name, "enabled": bool(r.enabled), "sources": split_sources(r.sources),
                     "lan_cidrs": r.lan_cidrs or "", "sort": r.sort or 0, "wan_interface": r.wan_interface or "",
                     "ros": ros_values(r)} for r in rows])

    def apply(self, sites: list[dict]):
        env_lan = get_settings().lan_cidrs
        removed = []
        added = False
        with self.lock:
            info = {s["slug"]: s for s in sites} or dict(self.info)
            for slug in info:
                if slug not in self.engines:
                    e = Engine(site=slug)
                    e.audit = default_engine.audit
                    self.engines[slug] = e
                    added = True
                if slug not in self.pollers:
                    p = RosPoller(self.engines[slug])
                    p.env_wan = ""
                    self.pollers[slug] = p
            for slug in list(self.engines):
                if slug not in info and slug != DEFAULT_SITE:
                    removed.append(self.engines.pop(slug))
                    self.pollers.pop(slug, None)
            for slug, s in info.items():
                lan = s.get("lan_cidrs") or env_lan
                e = self.engines[slug]
                if e.lan_cidrs_text != lan:
                    e.set_lan(lan)
            enabled = [s for s in info.values() if s.get("enabled")]
            by_ip = {}
            for s in enabled:
                for ip in s.get("sources") or []:
                    by_ip.setdefault(ip, s["slug"])
            self.info, self._by_ip = info, by_ip
            self.accept_all = enabled[0]["slug"] if len(enabled) == 1 and not enabled[0].get("sources") else None
        for slug, s in info.items():
            if "ros" not in s:
                continue
            p = self.pollers[slug]
            # 停用的站点不轮询；默认站点没在网页保存过时用环境变量 ROS_*
            ros_poller.apply(s["ros"] if s.get("enabled") else {"ros_url": ""}, target=p, env=slug == DEFAULT_SITE)
            if p.wan_override != (s.get("wan_interface") or ""):
                p.wan_override, p._wan_prev = s.get("wan_interface") or "", None
        if added and database.is_configured():
            # 新站点的 Engine：装上只对它生效的自定义规则
            try:
                default_engine.reload_rules()
            except Exception as ex:  # noqa: BLE001
                print(f"[sites] 加载站点规则失败：{type(ex).__name__}: {ex}", flush=True)
        for e in removed:   # 删掉的站点：把内存里还没写的先写掉
            try:
                e.flush(final=True)
            except Exception as ex:  # noqa: BLE001
                print(f"[sites] 移除站点前落库失败：{type(ex).__name__}: {ex}", flush=True)

    def load_state(self):
        default_engine.load_state()
        for e in self.all():
            if e is not default_engine:
                e.load_state(full=False)

    # ---------- 查询 ----------
    def get(self, slug: str) -> Engine | None:
        return self.engines.get(slug)

    def enabled_slugs(self) -> list[str]:
        return [s for s, i in self.info.items() if i.get("enabled")]

    def multi(self) -> bool:
        """启用站点 ≥2 个（多站点界面、通知前缀按这个判断）"""
        return len(self.enabled_slugs()) >= 2

    def name(self, slug: str) -> str:
        i = self.info.get(slug)
        return (i or {}).get("name") or slug

    def all(self) -> list[Engine]:
        return list(self.engines.values())

    def poller(self, slug: str) -> RosPoller | None:
        return self.pollers.get(slug)

    # ---------- RouterOS 轮询：每个站点各跑各的，一台连不上（超时 10 秒）不拖住别的站点 ----------
    def _each(self, method: str):
        from concurrent.futures import ThreadPoolExecutor
        if not hasattr(self, "_pool"):
            self._pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="ros")
        for slug, p in list(self.pollers.items()):
            if not p.enabled or getattr(p, "_busy_" + method, False):
                continue
            setattr(p, "_busy_" + method, True)

            def run(p=p, slug=slug):
                try:
                    getattr(p, method)()
                except Exception as ex:  # noqa: BLE001
                    print(f"[ros] 站点 {slug} {method} 失败：{type(ex).__name__}: {ex}", flush=True)
                finally:
                    setattr(p, "_busy_" + method, False)
            self._pool.submit(run)

    def poll_all(self):
        self._each("poll")

    def sample_all(self):
        self._each("sample")

    # ---------- 收包 ----------
    def resolve(self, addr: str) -> Engine | None:
        slug = self.accept_all or self._by_ip.get(addr)
        if slug is None and addr and "%" not in addr:
            ip = norm_ip(addr)
            slug = self._by_ip.get(ip) if ip else None
        return self.engines.get(slug) if slug else None

    def on_ipfix(self, data: bytes, addr: str):
        e = self.resolve(addr)
        if e is None:
            return self._note_unknown(addr, "ipfix")
        e.on_ipfix(data, addr)

    def on_tzsp(self, data: bytes, addr: str):
        e = self.resolve(addr)
        if e is None:
            return self._note_unknown(addr, "tzsp")
        e.on_tzsp(data, addr)

    def _note_unknown(self, addr: str, kind: str):
        # 先过全局白名单（COLLECTOR_ALLOWED）：白名单外的包本来就丢，不进未登记列表
        if not default_engine.source_allowed(addr):
            return
        k = (addr, kind)
        with self.lock:
            v = self._unknown.get(k)
            if v is None:
                if len(self._unknown) >= MAX_UNKNOWN:
                    return
                v = self._unknown[k] = [0, 0]
            v[0] = int(time.time())
            v[1] += 1

    def unknown_snapshot(self) -> list[dict]:
        with self.lock:
            return [{"ip": ip, "kind": kind, "last_seen": v[0], "packets": v[1]}
                    for (ip, kind), v in self._unknown.items()]

    # ---------- 定时任务 ----------
    def flush(self, final: bool = False):
        for e in self.all():
            try:
                e.flush(final=final)
            except Exception as ex:  # noqa: BLE001  一个站点出错不影响其它站点
                print(f"[sites] 站点 {e.site} 落库失败：{type(ex).__name__}: {ex}", flush=True)
        self._flush_unknown()

    def _flush_unknown(self):
        with self.lock:
            pending, self._unknown = self._unknown, {}
        if not pending or not database.is_configured():
            if pending:
                with self.lock:
                    for k, v in pending.items():
                        self._unknown.setdefault(k, v)
            return
        from app.database import upsert_add
        rows = [{"ip": ip[:45], "kind": kind, "last_seen": v[0], "packets": v[1]} for (ip, kind), v in pending.items()]
        try:
            with database.session() as db:
                upsert_add(db, UnknownSource.__table__, rows, ["ip", "kind"], ["packets"], ["last_seen"])
                db.commit()
        except Exception as ex:  # noqa: BLE001
            print(f"[sites] 未登记来源落库失败：{type(ex).__name__}: {ex}", flush=True)

    def cleanup(self):
        default_engine.cleanup()            # 内存 + 按保留期清理数据库（全站点共用的表，只做一次）
        for e in self.all():
            if e is not default_engine:
                e.cleanup(db_too=False)
        if database.is_configured():
            with database.session() as db:
                db.execute(delete(UnknownSource).where(UnknownSource.last_seen < time.time() - UNKNOWN_DAYS * 86400))
                db.commit()


registry = SiteRegistry()
