"""终端命名：用户按 MAC 或 IP 给终端起名。

- 按 MAC：设备换了 IP 名字也跟着走，适合大多数设备。
- 按 IP：适合固定 IP、但 MAC 会变的设备（手机的随机 MAC），或拿不到 MAC 的终端。
"""
import ipaddress
import re
import time

from sqlalchemy import select

from app.models import Host, HostName

_MAC_RE = re.compile(r"^[0-9A-F]{12}$")


def norm_mac(s: str) -> str | None:
    """AA-BB-CC-DD-EE-FF / aabb.ccdd.eeff / aabbccddeeff → AA:BB:CC:DD:EE:FF"""
    h = re.sub(r"[:\-.\s]", "", s or "").upper()
    if not _MAC_RE.match(h):
        return None
    return ":".join(h[i:i + 2] for i in range(0, 12, 2))


def norm_ip(s: str) -> str | None:
    try:
        return str(ipaddress.ip_address((s or "").strip()))
    except ValueError:
        return None


def normalize(kind: str, value: str) -> str | None:
    return norm_mac(value) if kind == "mac" else norm_ip(value) if kind == "ip" else None


def load(db) -> dict[tuple[str, str], str]:
    return {(n.kind, n.value): n.name for n in db.scalars(select(HostName))}


def resolve(names: dict, mac: str | None, ip: str | None) -> tuple[str | None, str | None]:
    """返回 (名字, 命中方式 mac|ip)。"""
    if mac and (n := names.get(("mac", mac))):
        return n, "mac"
    if ip and (n := names.get(("ip", ip))):
        return n, "ip"
    return None, None


def put(db, kind: str, value: str, name: str | None):
    """name 为空表示删除这条命名。value 需已规范化。"""
    row = db.get(HostName, (kind, value))
    name = (name or "").strip()
    if not name:
        if row is not None:
            db.delete(row)
        return
    if row is None:
        db.add(HostName(kind=kind, value=value, name=name, updated=int(time.time())))
    else:
        row.name, row.updated = name, int(time.time())


def migrate_aliases(db):
    """把旧版 hosts.alias 搬到 host_names（有 MAC 按 MAC，否则按 IP），只做一次。"""
    hosts = db.scalars(select(Host).where(Host.alias.is_not(None))).all()
    if not hosts:
        return
    names = load(db)
    for h in hosts:
        kind, value = ("mac", h.mac) if h.mac else ("ip", h.ip)
        if value and (kind, value) not in names and h.alias.strip():
            put(db, kind, value, h.alias)
            names[(kind, value)] = h.alias
        h.alias = None
    db.commit()
