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
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import database  # noqa: E402

database.connect(os.environ["DATABASE_URL"])
