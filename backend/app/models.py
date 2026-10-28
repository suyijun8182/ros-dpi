"""数据表。时间一律存 epoch 秒（BigInteger），分桶起点：分钟/小时按 UTC 对齐，天按配置时区的 0 点。"""
import secrets

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
    base = Column(String(255))   # 主域名（访问目标排行按主域名合并在 SQL 侧做）；升级前的旧行启动时回填
    bytes = Column(BigInteger, nullable=False, default=0)
    __table_args__ = (Index("ix_hdd_host_ts", "host", "ts"), Index("ix_hdd_app_ts", "app", "ts"))


class UnmatchedDay(Base):
    """没有任何域名信号的流量（未匹配诊断，debug25）：每天按 终端 / 协议 / 端口 / 远端 ASN 类型 / 最终归类 汇总，留 30 天。
    port 为 65536 表示 1024 以上的非常用端口（P2P 端口五花八门，逐个记没有意义）"""
    __tablename__ = "unmatched_day"
    ts = Column(BigInteger, primary_key=True, autoincrement=False)
    host = Column(String(64), primary_key=True)
    proto = Column(Integer, primary_key=True, autoincrement=False)
    port = Column(Integer, primary_key=True, autoincrement=False)
    kind = Column(String(16), primary_key=True)   # broadband / idc / other（国内其它）/ foreign / nodb（没有 ASN 库）
    app = Column(String(48), primary_key=True)
    up = Column(BigInteger, nullable=False, default=0)
    down = Column(BigInteger, nullable=False, default=0)
    flows = Column(Integer, nullable=False, default=0)
    __table_args__ = (Index("ix_unm_ts", "ts"),)


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
    expires = Column(BigInteger, nullable=False, index=True)   # 清理过期条目按它删


class DomainGeo(Base):
    """域名的地理位置：记录流量时它连到的 IP 和国家（访问目标的国家 / 地区分布用，不随 DNS 缓存过期而丢失）"""
    __tablename__ = "domain_geo"
    domain = Column(String(255), primary_key=True)
    ip = Column(String(45))
    cc = Column(String(2))
    updated = Column(BigInteger, index=True)   # 按保留期清理时按它删


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


class ApiToken(Base):
    """只读 API 令牌（0.6.25）：给 Home Assistant 等外部程序长期读取数据用，不过期、可随时删除。
    只存 SHA-256，令牌原文只在创建时显示一次"""
    __tablename__ = "api_tokens"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(64), nullable=False)
    token_hash = Column(String(64), unique=True, nullable=False)
    prefix = Column(String(12))                       # 令牌前几位，列表里用来辨认
    created = Column(Integer)
    created_by = Column(String(64))
    last_used = Column(Integer)


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(64), unique=True, nullable=False)
    password_hash = Column(String(128), nullable=False)
    role = Column(String(16), nullable=True)          # admin | user；空 = admin（升级前建的账号都是管理员）
    # 改密码 / 改权限时 +1，旧 token 立即失效。新建账号从随机值开始：删掉 alice 再建一个同名账号时，
    # 被删账号手里 ver=0 的旧 token 不能对上新账号
    token_version = Column(Integer, nullable=True, default=lambda: secrets.randbelow(1 << 30) + 1)
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
    remote = Column(String(255))                 # 最近一次的远端 IP；0.6.8 从 45 加宽：代理连接曾把域名写进来导致落库卡死
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


class ShareEntry(Base):
    """社区共享库（debug16）：各部署实例上报的「远端 IP → 应用」匿名投票。
    中转实例聚合：至少 2 个不同实例都见过的映射才对外发布。不含本机终端、域名记录与自定义应用。"""
    __tablename__ = "share_entries"
    ip = Column(String(45), primary_key=True)
    app = Column(String(48), primary_key=True)
    reporter = Column(String(36), primary_key=True)   # 上报实例的匿名 ID（随机 UUID）
    bytes = Column(BigInteger, nullable=False, default=0)
    ts = Column(BigInteger, nullable=False)           # 最近一次上报时间（过期清理用）


class ShareDeployment(Base):
    """社区主站上的实例登记（debug16 / 0.6.21 重做）：注册时发令牌，每次上报更新心跳。
    全球 已部署 / 在线 / 离线 从这里统计；只含版本号和来源网络的哈希，不存来源 IP"""
    __tablename__ = "share_deployments"
    instance = Column(String(36), primary_key=True)
    version = Column(String(16))
    first_seen = Column(BigInteger, nullable=False)
    last_seen = Column(BigInteger, nullable=False)
    public_url = Column(String(255))                 # 0.6.15~0.6.19 的中转地址，已停用
    token_hash = Column(String(64))                  # 实例令牌的 SHA-256（令牌本身只在实例那边）
    net = Column(String(16))                         # 来源网络（IPv4 /24、IPv6 /56）的加盐哈希：防一人伪造多个实例刷票
    last_votes = Column(BigInteger)                  # 最近一次带投票的上报时间
    block = Column(String(16))                       # 来源 /48（IPv6）或 /24（IPv4）的加盐哈希：注册限额用


class ShareDomain(Base):
    """社区共享库的域名学习（debug17）：各实例实测的「域名 → 应用」匿名投票，聚合规则同 ShareEntry"""
    __tablename__ = "share_domains"
    domain = Column(String(255), primary_key=True)
    app = Column(String(48), primary_key=True)
    reporter = Column(String(36), primary_key=True)
    bytes = Column(BigInteger, nullable=False, default=0)
    ts = Column(BigInteger, nullable=False)
