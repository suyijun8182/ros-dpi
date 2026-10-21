# ROS-DPI

RouterOS 终端流量与应用统计面板。按 今日 / 本周 / 本月 统计每台终端的流量和应用使用情况，类似 Panabit / 碧海威。

Per-device traffic and per-application (DPI-style) statistics for MikroTik RouterOS, built on IPFIX + DNS sniffing.

Source & docs: https://github.com/suyijun8182/ros-dpi

## What's new

- **0.1.1**: full `docker-compose.yml` on this page (no `.env` needed), first-run notes, database auto-created on external MySQL.
- **0.1.0**: first release. Overview, hosts, applications, flow Sankey, custom rules, setup guide. zh/en, light/dark.

## Features

- IPFIX / NetFlow v9 collector (udp/2055), TZSP DNS sniffer (udp/37008), optional read-only RouterOS REST polling
- 100+ built-in apps in 20+ categories; custom domain / CIDR / port rules
- Per-minute / hour / day aggregation in MySQL

## Quick start

Save as `docker-compose.yml`, change the two database passwords (they must match) and `LAN_CIDRS`, then `docker compose up -d`:

```yaml
# ROS-DPI：RouterOS 终端流量与应用统计
# 用法：保存为 docker-compose.yml，改掉标了「必改」的三处，然后 docker compose up -d
# 浏览器打开 http://<本机IP>:8080，首次打开设置管理员密码即可，数据库无需手动配置
services:
  ros-dpi:
    image: suyijun8182/ros-dpi:latest        # 也可用 ghcr.io/suyijun8182/ros-dpi:latest
    container_name: ros-dpi
    restart: unless-stopped
    depends_on:
      mysql:
        condition: service_healthy
    ports:
      - "8080:8080/tcp"     # Web 界面
      - "2055:2055/udp"     # IPFIX / NetFlow：RouterOS Traffic Flow 发到这里
      - "37008:37008/udp"   # TZSP：RouterOS 镜像的 DNS 应答发到这里
    environment:
      TZ: Asia/Shanghai
      # 「必改」密码与下方 MYSQL_PASSWORD 保持一致
      DATABASE_URL: mysql+pymysql://rosdpi:rosdpi-change-me@mysql:3306/rosdpi?charset=utf8mb4
      # 「必改」内网网段，逗号分隔（之后也可在 系统设置 → 网络 里改）
      LAN_CIDRS: 192.168.88.0/24
      # 管理员 admin 的初始密码；留空则首次打开网页时设置
      ADMIN_PASSWORD: ""
      # RouterOS 只读 API（可选：显示主机名、WAN 速率）
      ROS_URL: ""                 # 例如 https://192.168.88.1
      ROS_USER: ""
      ROS_PASSWORD: ""
      ROS_VERIFY_TLS: "false"
    volumes:
      - ./data:/app/data

  mysql:
    image: mysql:8.4
    container_name: ros-dpi-mysql
    restart: unless-stopped
    environment:
      TZ: Asia/Shanghai
      MYSQL_DATABASE: rosdpi                    # 首次启动自动创建库和账号，表由 ROS-DPI 自动建立
      MYSQL_USER: rosdpi
      MYSQL_PASSWORD: rosdpi-change-me          # 「必改」与上方 DATABASE_URL 中的密码一致
      MYSQL_ROOT_PASSWORD: root-change-me       # 「必改」
    command: ["--character-set-server=utf8mb4", "--collation-server=utf8mb4_unicode_ci", "--innodb-buffer-pool-size=256M"]
    volumes:
      - ./mysql:/var/lib/mysql
    healthcheck:
      test: ["CMD-SHELL", "mysqladmin ping -h 127.0.0.1 -uroot -p$$MYSQL_ROOT_PASSWORD"]
      interval: 10s
      timeout: 5s
      retries: 20
```

## First run / 首次使用

- Open `http://<host>:8080` and set the admin password. 首次打开网页设置管理员密码即可。
- **No MySQL setup needed.** The MySQL container creates the database and user on first start; ROS-DPI creates its tables (and the database, on an external MySQL). 无需手动配置数据库或导入 SQL。
- First MySQL initialization takes 20–60 s. 首次初始化需要 20～60 秒。
- RouterOS commands: **Settings → Setup guide** in the app. RouterOS 配置命令见 系统设置 → 接入向导。

## Ports

| Port | Use |
|---|---|
| 8080/tcp | Web UI |
| 2055/udp | IPFIX / NetFlow v9 |
| 37008/udp | TZSP (DNS mirror) |

## Environment

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | set in compose | `mysql+pymysql://user:pass@host:3306/rosdpi?charset=utf8mb4` |
| `LAN_CIDRS` | private ranges | LAN ranges, comma separated |
| `ADMIN_PASSWORD` | empty | initial password for `admin` |
| `ROS_URL` / `ROS_USER` / `ROS_PASSWORD` | empty | RouterOS REST + read-only user |
| `TZ` | `Asia/Shanghai` | statistics time zone (weeks start Monday) |
