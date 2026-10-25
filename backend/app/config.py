"""运行配置：全部来自环境变量（见 .env.example）。

界面里可修改的项（LAN 网段、保留天数、WAN 接口）存到数据库 settings 表，
优先级高于这里的默认值，见 app.runtime。
"""
from functools import lru_cache
from zoneinfo import ZoneInfo

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # 留空（默认）：首次打开网页时在安装向导里填写 MySQL 信息，保存到 data/db_config.json
    # 设置后跳过向导：mysql+pymysql://user:pass@host:3306/rosdpi?charset=utf8mb4；开发/测试可用 sqlite:///./dev.db
    database_url: str = ""

    http_port: int = 8080
    ipfix_port: int = 2055
    tzsp_port: int = 37008

    # 逗号分隔，界面可覆盖
    lan_cidrs: str = "10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,fd00::/8"
    wan_interface: str = ""

    # RouterOS REST（只读用户）。留空则不轮询，终端只显示 IP。
    ros_url: str = ""
    ros_user: str = ""
    ros_password: str = ""
    ros_verify_tls: bool = False
    ros_poll_seconds: int = 30
    ros_rate_seconds: int = 5  # WAN 口速率采样间隔（实时流量图），只读一次接口计数

    # 旁路代理与内网 DNS（可选）。每个人的地址不同，默认都不启用；也可以在网页 系统设置 → 外部数据源 里填写（网页填写的优先）
    singbox_url: str = ""        # sing-box / Clash 兼容的 external_controller，如 http://192.168.1.2:9090
    singbox_secret: str = ""
    proxy_ips: str = ""          # 旁路代理自身的 IP（逗号分隔）；留空时取 singbox_url 里的地址
    fakeip_cidrs: str = "198.18.0.0/15,fc00::/18"
    mosdns_url: str = ""         # MosDNS 审计 API 地址，如 http://192.168.1.3:9099
    adguard_url: str = ""        # 自有 DNS 服务器 AdGuard Home 的地址，如 http://192.168.9.2:3000（双层 NAT 时爱快下游的 DNS）
    adguard_username: str = ""   # AdGuard Home 登录用户名；和密码都留空表示免认证（只在内网监听时）
    adguard_password: str = ""
    share_enabled: bool = True   # 共享识别库总开关（debug16 第 3 条，默认打开）：关掉后不心跳、不上报、不拉取
    webdav_url: str = ""         # 社区共享库的 WebDAV 地址（debug22，NAS 自带）：如 http://192.168.8.10:5005/ros-dpi
    webdav_user: str = ""        # WebDAV 账号；和密码都留空表示免认证
    webdav_password: str = ""
    oui_db: bool = True          # 自动下载 IEEE 的 MAC 厂商库（OUI，识别终端类型用，每 30 天更新）
    asn_db: bool = True          # 自动下载 iptoasn 的 IP→ASN 库（公有领域，每天更新）
    china_db: bool = True        # 自动下载国内域名列表（dnsmasq-china-list）与国内 IP 段（每天更新）
    iplist_db: bool = True       # 自动下载 Google/Cloudflare/AWS/GitHub 官方 IP 段（每天更新）
    bm7_db: bool = True          # 自动下载 blackmatrix7 按应用整理的规则（GPL-2.0，每周更新）：给已有应用补域名、新增应用
    hagezi_db: bool = True       # 自动下载 Hagezi 分类列表（GPL-3.0，每天更新）：成人、博彩、VPN/代理、广告、设备遥测
    ut1_db: bool = True          # 自动下载 UT1 分类列表（CC BY-SA 4.0，每天更新）：游戏、购物、新闻、求职等 20 多类

    tz: str = "Asia/Shanghai"

    retention_minute_days: int = 2
    retention_hour_days: int = 45
    retention_day_days: int = 730
    retention_domain_days: int = 31
    retention_log_days: int = 30      # 访问日志（审计）
    retention_event_days: int = 180   # 审计事件、操作日志

    # JWT 密钥；留空则首次启动随机生成并保存到数据库
    secret_key: str = ""
    # 首次启动的管理员密码；留空则由登录页引导设置
    admin_password: str = ""

    @property
    def zone(self) -> ZoneInfo:
        return ZoneInfo(self.tz)


@lru_cache
def get_settings() -> Settings:
    return Settings()
