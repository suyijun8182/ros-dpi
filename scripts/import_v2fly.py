"""发版前更新打包进镜像的 v2fly 规则：python scripts/import_v2fly.py [--src <v2fly 仓库的 data 目录>]

转换逻辑在 backend/app/classify/v2fly.py（容器运行时也用它每天自动更新）。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend"))
from app.classify.v2fly import main  # noqa: E402

if __name__ == "__main__":
    main()
