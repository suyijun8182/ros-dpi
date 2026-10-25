#!/bin/bash
# ROS-DPI Linux 一键部署（debug18）：下载二进制 → 安装 systemd 服务 → 自动启动
# 用法：curl -fsSL https://raw.githubusercontent.com/suyijun8182/ros-dpi/main/install.sh | bash
# 可用环境变量：ROS_DPI_PORT（默认 8080）、ROS_DPI_DIR（默认 /opt/ros-dpi）
# 自定义配置（DATABASE_URL、ADMIN_PASSWORD 等）写在 /etc/ros-dpi.env，重装 / 升级都不会覆盖
set -euo pipefail

REPO="suyijun8182/ros-dpi"
PORT="${ROS_DPI_PORT:-8080}"
DIR="${ROS_DPI_DIR:-/opt/ros-dpi}"
BIN="$DIR/bin/ros-dpi"          # 放在安装目录下，服务账号可写：一键自更新要原地替换它
LINK="/usr/local/bin/ros-dpi"
ENV_FILE="/etc/ros-dpi.env"
SVC_USER="ros-dpi"

[ "$(id -u)" = 0 ] || { echo "请用 root 运行（sudo curl ... | sudo bash）"; exit 1; }

ARCH="$(uname -m)"
case "$ARCH" in
  x86_64) ASSET="ros-dpi-linux-amd64.tar.gz" ;;
  aarch64 | arm64) ASSET="ros-dpi-linux-arm64.tar.gz" ;;
  *) echo "不支持的架构：$ARCH"; exit 1 ;;
esac

echo "==> 获取最新版本号"
URL="https://api.github.com/repos/${REPO}/releases/latest"
# 不用 grep -P（BusyBox / 部分发行版的 grep 不支持），sed 取 "tag_name": "vX.Y.Z"
TAG=$(curl -fsSL "$URL" | sed -n 's/.*"tag_name"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -n 1 || true)
[ -n "$TAG" ] || { echo "取不到最新版本（网络问题？）"; exit 1; }
echo "    最新版本 $TAG"

echo "==> 下载 $ASSET ($TAG)"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
BASE="https://github.com/${REPO}/releases/download/${TAG}"
curl -fsSL "$BASE/${ASSET}" -o "$TMP/${ASSET}"

echo "==> 校验 SHA256"
curl -fsSL "$BASE/SHA256SUMS" -o "$TMP/SHA256SUMS" || { echo "该版本没有 SHA256SUMS 校验文件，为安全起见停止安装"; exit 1; }
grep -q " [*]\{0,1\}${ASSET}\$" "$TMP/SHA256SUMS" || { echo "SHA256SUMS 里没有 ${ASSET}，停止安装"; exit 1; }
(cd "$TMP" && grep " [*]\{0,1\}${ASSET}\$" SHA256SUMS | sha256sum -c -) || { echo "校验失败：下载的文件已损坏或被篡改"; exit 1; }
tar -xzf "$TMP/${ASSET}" -C "$TMP"

echo "==> 安装"
REINSTALL=0
[ -f /etc/systemd/system/ros-dpi.service ] && REINSTALL=1
# 专用系统账号运行服务（0.6.22 及以前是 root）：不能登录、没有家目录
if ! id "$SVC_USER" >/dev/null 2>&1; then
  NOLOGIN=$(command -v nologin || echo /bin/false)
  if command -v useradd >/dev/null 2>&1; then
    useradd --system --user-group --no-create-home --home-dir "$DIR" --shell "$NOLOGIN" "$SVC_USER"
  else   # BusyBox / Alpine
    addgroup -S "$SVC_USER" 2>/dev/null || true
    adduser -S -D -H -h "$DIR" -s "$NOLOGIN" -G "$SVC_USER" "$SVC_USER"
  fi
fi
mkdir -p "$DIR/bin" "$DIR/data"
install -m 755 "$TMP/ros-dpi" "$BIN"
# 旧版把二进制装在 /usr/local/bin（只有 root 可写）：换成指向安装目录的软链接，命令行照常可用
rm -f "$LINK.bak"
ln -sfn "$BIN" "$LINK"
# 数据目录里的 SQLite 库存着 JWT 签名密钥和各类密码：只给服务账号读写（旧版装出来的是 root 的 644 文件）
chown -R "$SVC_USER:$SVC_USER" "$DIR/bin" "$DIR/data"
chmod 700 "$DIR/data"
chmod -R go-rwx "$DIR/data"

# 用户配置单独放在 EnvironmentFile：只在不存在时创建（全是注释示例），重装 / 升级都不覆盖
NEW_ENV=0
if [ ! -f "$ENV_FILE" ]; then
  NEW_ENV=1
  cat > "$ENV_FILE" <<'ENVF'
# ROS-DPI 自定义配置：取消注释并修改后执行 systemctl restart ros-dpi
# 本文件不会被 install.sh 覆盖；端口和数据目录由服务文件给出，这里设置会覆盖它们
#
# 用 MySQL 代替默认 SQLite：
# DATABASE_URL=mysql+pymysql://rosdpi:密码@127.0.0.1:3306/rosdpi?charset=utf8mb4
# 管理员 admin 的初始密码（强烈建议设置；留空则首次打开网页时设置）：
# ADMIN_PASSWORD=
# 内网网段（之后也可在 系统设置 → 网络 里改）：
# LAN_CIDRS=192.168.88.0/24
# RouterOS 只读 API（可选）：
# ROS_URL=https://192.168.88.1
# ROS_USER=
# ROS_PASSWORD=
ENVF
  # 0.6.21 及以前的配置写在服务文件里（Environment=DATABASE_URL=…）：搬进来，否则重装后会退回 SQLite，看起来像数据全丢了
  if [ "$REINSTALL" = 1 ]; then
    grep '^Environment=' /etc/systemd/system/ros-dpi.service \
      | grep -v -e '^Environment="\{0,1\}HTTP_PORT=' -e '^Environment="\{0,1\}DATA_DIR=' \
      | sed -e 's/^Environment=//' -e 's/^"\(.*\)"$/\1/' >> "$ENV_FILE" || true
  fi
fi
chmod 600 "$ENV_FILE"

# 以专用账号运行。一键自更新只需要写 $DIR/bin，重启靠进程退出后 Restart=always 拉起，不需要 systemctl 权限；
# 环境文件由 systemd 以 root 读取，服务账号本身读不到（chmod 600 root）
cat > /etc/systemd/system/ros-dpi.service <<UNIT
[Unit]
Description=ROS-DPI 终端流量与应用统计
After=network-online.target
Wants=network-online.target

[Service]
User=$SVC_USER
Group=$SVC_USER
WorkingDirectory=$DIR
Environment=HTTP_PORT=$PORT
Environment=DATA_DIR=$DIR/data
EnvironmentFile=-$ENV_FILE
ExecStart=$BIN
Restart=always
RestartSec=3
UMask=0077
# Web 端口改成 1024 以下（如 80）时需要绑定特权端口的能力；除此之外不给任何能力
AmbientCapabilities=CAP_NET_BIND_SERVICE
CapabilityBoundingSet=CAP_NET_BIND_SERVICE
NoNewPrivileges=yes
PrivateTmp=yes
PrivateDevices=yes
ProtectHome=yes
ProtectSystem=strict
ReadWritePaths=$DIR/bin $DIR/data
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectControlGroups=yes
RestrictSUIDSGID=yes
LockPersonality=yes

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable ros-dpi >/dev/null 2>&1
# 重装 / 升级：restart 让新二进制和新服务文件立即生效（enable --now 对已运行的服务不会重启）
if [ "$REINSTALL" = 1 ]; then systemctl restart ros-dpi; else systemctl start ros-dpi; fi
sleep 2
systemctl is-active ros-dpi >/dev/null && STATE="运行中" || STATE="启动失败（journalctl -u ros-dpi 查看）"

IP=$(hostname -I 2>/dev/null | awk '{print $1}')
echo
echo "==> 完成：$STATE"
echo "    浏览器打开 http://${IP:-本机IP}:$PORT"
echo "    数据目录 $DIR/data（默认 SQLite，想用 MySQL 在 $ENV_FILE 里设 DATABASE_URL 后 systemctl restart ros-dpi）"
echo "    建议在 $ENV_FILE 里设置 ADMIN_PASSWORD，或立即打开网页设置管理员密码"
echo "    流量采集：RouterOS 的 Traffic-Flow(udp/2055) 与 TZSP(udp/37008) 指到本机地址"
