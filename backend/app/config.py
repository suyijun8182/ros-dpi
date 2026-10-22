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

    tz: str = "Asia/Shanghai"

    retention_minute_days: int = 2
    retention_hour_days: int = 45
    retention_day_days: int = 730
    retention_domain_days: int = 31

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
