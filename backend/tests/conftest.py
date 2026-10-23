import os
import sys
import tempfile

_tmp = tempfile.mkdtemp(prefix="rosdpi-test-")
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ["DATA_DIR"] = _tmp
os.environ["LAN_CIDRS"] = "192.168.88.0/24,2408:8000:1:2::/64"
os.environ["ROS_URL"] = ""
os.environ["ADMIN_PASSWORD"] = ""
os.environ["TZ"] = "Asia/Shanghai"
os.environ["IPFIX_PORT"] = "0"
os.environ["TZSP_PORT"] = "0"
os.environ["ASN_DB"] = "false"
os.environ["OUI_DB"] = "false"  # 测试不下载 MAC 厂商库  # 测试不下载 ASN 库
os.environ["CHINA_DB"] = "false"   # 测试不下载国内域名 / IP 段库
os.environ["IPLIST_DB"] = "false"  # 测试不下载官方 IP 段库
os.environ["ROSDPI_NO_JOBS"] = "1"  # 不启动后台定时任务（每分钟落库会打乱测试里的计数）
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import database  # noqa: E402

database.connect(os.environ["DATABASE_URL"])
