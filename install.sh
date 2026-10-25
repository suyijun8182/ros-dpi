#!/bin/bash
# ROS-DPI Linux 一键部署（debug18）：下载二进制 → 安装 systemd 服务 → 自动启动
# 用法：curl -fsSL https://raw.githubusercontent.com/suyijun8182/ros-dpi/main/install.sh | bash
# 可用环境变量：ROS_DPI_PORT（默认 8080）、ROS_DPI_DIR（默认 /opt/ros-dpi）
set -euo pipefail

REPO="suyijun8182/ros-dpi"
PORT="${ROS_DPI_PORT:-8080}"
DIR="${ROS_DPI_DIR:-/opt/ros-dpi}"
BIN="/usr/local/bin/ros-dpi"

[ "$(id -u)" = 0 ] || { echo "请用 root 运行（sudo curl ... | sudo bash）"; exit 1; }

ARCH="$(uname -m)"
case "$ARCH" in
  x86_64) ASSET="ros-dpi-linux-amd64.tar.gz" ;;
  aarch64 | arm64) ASSET="ros-dpi-linux-arm64.tar.gz" ;;
  *) echo "不支持的架构：$ARCH"; exit 1 ;;
esac

echo "==> 获取最新版本号"
URL="https://api.github.com/repos/${REPO}/releases/latest"
TAG=$(curl -fsSL "$URL" | grep -oP '"tag_name":\s*"\K[^"]+' || true)
[ -n "$TAG" ] || { echo "取不到最新版本（网络问题？）"; exit 1; }
echo "    最新版本 $TAG"

echo "==> 下载 $ASSET ($TAG)"
TMP=$(mktemp -d)
curl -fsSL "https://github.com/${REPO}/releases/download/${TAG}/${ASSET}" -o "$TMP/pkg.tar.gz"
tar -xzf "$TMP/pkg.tar.gz" -C "$TMP"

echo "==> 安装"
install -m 755 "$TMP/ros-dpi" "$BIN"
mkdir -p "$DIR/data"

# 以 root 运行：一键自更新（前端按钮）需要写 /usr/local/bin 与 systemctl restart 权限
cat > /etc/systemd/system/ros-dpi.service <<UNIT
[Unit]
Description=ROS-DPI 终端流量与应用统计
After=network-online.target
Wants=network-online.target

[Service]
WorkingDirectory=$DIR
Environment=HTTP_PORT=$PORT
Environment=DATA_DIR=$DIR/data
ExecStart=$BIN
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable --now ros-dpi
sleep 2
systemctl is-active ros-dpi >/dev/null && STATE="运行中" || STATE="启动失败（journalctl -u ros-dpi 查看）"
rm -rf "$TMP"

IP=$(hostname -I 2>/dev/null | awk '{print $1}')
echo
echo "==> 完成：$STATE"
echo "    浏览器打开 http://${IP:-本机IP}:$PORT"
echo "    数据目录 $DIR/data（默认 SQLite，想用 MySQL 设 DATABASE_URL 后 systemctl restart ros-dpi）"
echo "    流量采集：RouterOS 的 Traffic-Flow(udp/2055) 与 TZSP(udp/37008) 指到本机地址"
