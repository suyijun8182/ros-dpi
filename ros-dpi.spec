# PyInstaller 打包配置（debug18）：把后端 + 前端 dist + 运行时打成单文件 Linux 二进制
# 用法（在仓库根目录）：pyinstaller ros-dpi.spec
import os
from PyInstaller.utils.hooks import collect_all, collect_data_files

block_cipher = None

datas = [("frontend/dist", "frontend_dist")]
hidden = ["uvicorn.logging", "uvicorn.loops", "uvicorn.loops.auto", "uvicorn.protocols",
          "uvicorn.protocols.http", "uvicorn.protocols.http.auto", "uvicorn.protocols.websockets",
          "uvicorn.protocols.websockets.auto", "uvicorn.lifespan", "uvicorn.lifespan.on",
          "app.main", "app.routers", "app.collector"]
for pkg in ("uvicorn", "pymysql", "cryptography", "passlib", "anyio"):
    attrs = collect_all(pkg)
    datas += attrs[0]
    hidden += attrs[1]

a = Analysis(
    ["backend/ros_dpi_launcher.py"],
    pathex=["backend"],
    binaries=[],
    datas=datas,
    hiddenimports=hidden,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    name="ros-dpi",
    upx=False,
    console=True,
)
