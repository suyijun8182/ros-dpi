"""真实 MySQL 上的安装向导测试。需要环境变量 MYSQL_HOST / MYSQL_PORT / MYSQL_ROOT_PASSWORD（CI 中由 mysql 服务提供）。"""
import os
import sys
import tempfile

import pytest

_tmp = tempfile.mkdtemp(prefix="rosdpi-mysql-")
os.environ["DATA_DIR"] = _tmp
os.environ["DATABASE_URL"] = ""          # 走安装向导
os.environ["LAN_CIDRS"] = "192.168.88.0/24"
os.environ["IPFIX_PORT"] = "0"
os.environ["TZSP_PORT"] = "0"
os.environ["ROS_URL"] = ""
os.environ["ADMIN_PASSWORD"] = ""
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if not os.environ.get("MYSQL_HOST"):
    pytest.skip("未设置 MYSQL_HOST，跳过 MySQL 测试", allow_module_level=True)
