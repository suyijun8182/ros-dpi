"""ROS-DPI 单文件二进制的入口（debug18）：PyInstaller 打包用，也可直接 python 运行做本地冒烟。

零配置起步：没有 DATABASE_URL / db_config.json 时默认用 SQLite（数据目录下 rosdpi.db），
想用 MySQL 的用户通过环境变量 DATABASE_URL 或网页安装向导切换。
"""
import os
import sys


def main():
    # 冻结后的数据文件在 sys._MEIPASS；前端 dist 由 spec 打包到 _MEIPASS/frontend_dist，
    # main.py 的默认 FRONTEND_DIR（__file__/../frontend_dist）恰好解析到这里，不需要额外处理
    data_dir = os.path.abspath(os.environ.get("DATA_DIR") or os.path.join(os.getcwd(), "data"))
    os.environ["DATA_DIR"] = data_dir
    os.makedirs(data_dir, exist_ok=True)
    if not os.environ.get("DATABASE_URL"):
        saved = os.path.join(data_dir, "db_config.json")
        if not os.path.exists(saved):
            # 零配置起步：默认 SQLite；想用 MySQL 设 DATABASE_URL 或删掉这个默认走安装向导
            os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(data_dir, 'rosdpi.db')}"
    port = int(os.environ.get("HTTP_PORT") or 8080)
    import uvicorn
    uvicorn.run("app.main:app", host=os.environ.get("HOST", "0.0.0.0"), port=port,
                access_log=False, log_level=os.environ.get("LOG_LEVEL", "info"))


if __name__ == "__main__":
    main()
