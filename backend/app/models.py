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
