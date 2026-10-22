"""数据表。时间一律存 epoch 秒（BigInteger），分桶起点：分钟/小时按 UTC 对齐，天按配置时区的 0 点。"""
from sqlalchemy import BigInteger, Column, Index, Integer, String, Text

from app.database import Base


def _traffic_cols():
    return [
        # 复合主键里唯一的整数列，MySQL 上会被默认加 AUTO_INCREMENT，显式关掉
        Column("ts", BigInteger, primary_key=True, autoincrement=False),
        Column("host", String(64), primary_key=True),
        Column("app", String(48), primary_key=True),
        Column("up", BigInteger, nullable=False, default=0),
        Column("down", BigInteger, nullable=False, default=0),
        Column("flows", Integer, nullable=False, default=0),
    ]


class TrafficMinute(Base):
    __tablename__ = "traffic_minute"
    ts, host, app, up, down, flows = _traffic_cols()
    __table_args__ = (Index("ix_tmin_host_ts", "host", "ts"),)


class TrafficHour(Base):
    __tablename__ = "traffic_hour"
    ts, host, app, up, down, flows = _traffic_cols()
    __table_args__ = (Index("ix_thour_host_ts", "host", "ts"), Index("ix_thour_app_ts", "app", "ts"))


class TrafficDay(Base):
    __tablename__ = "traffic_day"
    ts, host, app, up, down, flows = _traffic_cols()
    __table_args__ = (Index("ix_tday_host_ts", "host", "ts"), Index("ix_tday_app_ts", "app", "ts"))


class HostDomainDay(Base):
    """每台终端每天访问的域名及字节数（主机详情 "最近访问域名"、未识别域名 Top）。"""
    __tablename__ = "host_domain_day"
    ts = Column(BigInteger, primary_key=True, autoincrement=False)
    host = Column(String(64), primary_key=True)
    domain = Column(String(255), primary_key=True)
    app = Column(String(48), nullable=False)
    bytes = Column(BigInteger, nullable=False, default=0)
    __table_args__ = (Index("ix_hdd_host_ts", "host", "ts"), Index("ix_hdd_app_ts", "app", "ts"))


class Host(Base):
    """终端。key 优先用 MAC（大写冒号格式），拿不到 MAC 时用 "IP:x.x.x.x"。"""
    __tablename__ = "hosts"
    key = Column(String(64), primary_key=True)
    mac = Column(String(17))
    ip = Column(String(45))
    ipv6 = Column(Text)
    hostname = Column(String(128))
    alias = Column(String(128))
    first_seen = Column(BigInteger)
    last_seen = Column(BigInteger)
    online_since = Column(BigInteger)  # 本次上线时间（离线超过 5 分钟后再出现算新的一次）
    dtype = Column(String(16))         # 手动指定的终端类型（优先）
    dtype_auto = Column(String(16))    # 自动识别的终端类型（devtype.py，每小时刷新）
    vendor = Column(String(64))        # MAC 厂商（IEEE OUI）


class HostName(Base):
    """终端命名：按 MAC（跟着设备走）或按 IP（跟着地址走）。同时命中时 MAC 优先。

    旧版本把备注名存在 hosts.alias（按终端 key），启动时会迁移到这里。
    """
    __tablename__ = "host_names"
    kind = Column(String(8), primary_key=True)    # mac | ip
    value = Column(String(45), primary_key=True)  # 大写冒号格式的 MAC，或规范化后的 IP
    name = Column(String(128), nullable=False)
    updated = Column(BigInteger)


class DnsCache(Base):
    __tablename__ = "dns_cache"
    ip = Column(String(45), primary_key=True)
    name = Column(String(255), nullable=False)
    cname = Column(String(255))
    expires = Column(BigInteger, nullable=False)


class CustomRule(Base):
    __tablename__ = "custom_rules"
    id = Column(Integer, primary_key=True, autoincrement=True)
    kind = Column(String(16), nullable=False)  # domain | cidr | port
    pattern = Column(String(255), nullable=False)
    app_id = Column(String(48), nullable=False)
    app_name = Column(String(64))
    category = Column(String(32))
    created = Column(BigInteger)


class Setting(Base):
    __tablename__ = "settings"
    key = Column(String(64), primary_key=True)
    value = Column(Text)


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(64), unique=True, nullable=False)
    password_hash = Column(String(128), nullable=False)
    role = Column(String(16), nullable=True)          # admin | user；空 = admin（升级前建的账号都是管理员）
    created = Column(Integer, nullable=True)
    last_login = Column(Integer, nullable=True)


# ---------------- 审计 ----------------

class AccessLog(Base):
    """访问日志：同一终端、同一目标（域名或 IP）、同一应用，间隔不超过 5 分钟的连接合成一条“访问”。

    持续超过 1 小时的访问分段写入（每段一行）。保留天数见 RETENTION_LOG_DAYS。
    """
    __tablename__ = "access_log"
    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    ts_start = Column(BigInteger, nullable=False)
    ts_end = Column(BigInteger, nullable=False)
    host = Column(String(64), nullable=False)
    host_ip = Column(String(45))
    dest = Column(String(255), nullable=False)   # 域名；没有域名时是远端 IP
    remote = Column(String(45))                  # 最近一次的远端 IP
    app = Column(String(48), nullable=False)
    port = Column(Integer)
    proto = Column(Integer)
    conns = Column(Integer, nullable=False, default=0)
    up = Column(BigInteger, nullable=False, default=0)
    down = Column(BigInteger, nullable=False, default=0)
    source = Column(String(8))                   # 域名来源：proxy / conn / pair / ip / none
    __table_args__ = (Index("ix_alog_host_ts", "host", "ts_start"), Index("ix_alog_ts", "ts_start"),
                      Index("ix_alog_app_ts", "app", "ts_start"), Index("ix_alog_dest", "dest"))


class AuditRule(Base):
    """审计规则：命中（终端访问了某类应用 / 域名，或流量超过阈值）时记一条审计事件，可推送通知"""
    __tablename__ = "audit_rules"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(64), nullable=False)
    enabled = Column(Integer, nullable=False, default=1)
    kind = Column(String(16), nullable=False)        # group | category | app | domain | traffic | new_host
    value = Column(String(255))                      # 大类 / 小类 / 应用 ID / 域名后缀；traffic 时为空
    hosts = Column(Text)                             # 只针对这些终端（逗号分隔的 key）；空 = 全部
    days = Column(String(16), default="1234567")     # 生效的星期（1=周一）
    time_from = Column(String(5), default="00:00")   # 生效时段（可跨午夜，如 22:00-06:00）
    time_to = Column(String(5), default="24:00")
    min_bytes = Column(BigInteger, default=0)        # 时段内累计超过这么多字节才算命中
    notify = Column(Integer, nullable=False, default=1)
    channels = Column(String(255))                   # 推送到哪些渠道（逗号分隔）；空 = 所有已启用的渠道
    created = Column(BigInteger)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    ts = Column(BigInteger, nullable=False)
    rule_id = Column(Integer)
    rule_name = Column(String(64))
    host = Column(String(64))
    detail = Column(Text)                            # JSON：命中的应用 / 域名 / 字节数
    notified = Column(Integer, default=0)
    __table_args__ = (Index("ix_aevent_ts", "ts"), Index("ix_aevent_host_ts", "host", "ts"))


class OpLog(Base):
    """操作日志：登录、修改设置 / 规则 / 命名等（审计系统本身也要可追溯）"""
    __tablename__ = "op_log"
    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    ts = Column(BigInteger, nullable=False)
    user = Column(String(64))
    ip = Column(String(45))
    action = Column(String(32), nullable=False)
    detail = Column(Text)
    ok = Column(Integer, default=1)
    __table_args__ = (Index("ix_oplog_ts", "ts"),)


# ---------------- 人员 ----------------

class Department(Base):
    """部门 / 分组（家里可以是“家长”“孩子”）"""
    __tablename__ = "departments"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(64), unique=True, nullable=False)


class Person(Base):
    """人员：一个人可以有多台设备，统计、报表、审计规则都能按人"""
    __tablename__ = "people"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(64), nullable=False)
    dept_id = Column(Integer, index=True)
    note = Column(String(255))
    created = Column(Integer)


class PersonDevice(Base):
    """设备归属：终端 key（MAC 或 IP:x）→ 人员"""
    __tablename__ = "person_devices"
    host = Column(String(64), primary_key=True)
    person_id = Column(Integer, nullable=False, index=True)
