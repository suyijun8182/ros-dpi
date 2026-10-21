# ROS-DPI

RouterOS 终端流量与应用统计面板。按 今日 / 本周 / 本月 统计每台终端的流量和应用使用情况，类似 Panabit / 碧海威。

Per-device traffic and per-application (DPI-style) statistics for MikroTik RouterOS, built on IPFIX + DNS sniffing.

Source & docs: https://github.com/suyijun8182/ros-dpi

## What's new

- **0.1.3**: fix the 500 error on the overview page when the RouterOS API (`ROS_URL`) is configured; clearer RouterOS connection errors.
- **0.1.2**: first-run setup wizard: enter your MySQL connection in the browser, like EasySub. The compose file no longer needs database settings. A README guide covers creating the database.
- **0.1.1**: full `docker-compose.yml` on this page (no `.env` needed), first-run notes, database auto-created on external MySQL.
- **0.1.0**: first release. Overview, hosts, applications, flow Sankey, custom rules, setup guide. zh/en, light/dark.

## Features

- IPFIX / NetFlow v9 collector (udp/2055), TZSP DNS sniffer (udp/37008), optional read-only RouterOS REST polling
- 100+ built-in apps in 20+ categories; custom domain / CIDR / port rules
- Per-minute / hour / day aggregation in MySQL

## Quick start

ROS-DPI stores data in **MySQL 5.7 / 8.x** and assumes you already have one. 默认使用你已有的 MySQL。

**1. Create the database and user / 准备数据库**（在你的 MySQL 里执行）

```sql
CREATE DATABASE rosdpi CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'rosdpi'@'%' IDENTIFIED BY 'your-password';
GRANT ALL PRIVILEGES ON rosdpi.* TO 'rosdpi'@'%';
FLUSH PRIVILEGES;
```

**2. `docker-compose.yml`**: set `LAN_CIDRS`, then `docker compose up -d`. 把 `LAN_CIDRS` 改成你的内网网段后启动。

```yaml
# ROS-DPI：RouterOS 终端流量与应用统计
# 前提：已有 MySQL 5.7+ / 8.x，并已按 README「准备数据库」建好库和账号
# 用法：保存为 docker-compose.yml，把 LAN_CIDRS 改成你的内网网段，然后 docker compose up -d
# 浏览器打开 http://<本机IP>:8080，按安装向导填写 MySQL 信息、设置管理员密码
services:
  ros-dpi:
    image: suyijun8182/ros-dpi:latest        # 也可用 ghcr.io/suyijun8182/ros-dpi:latest
    container_name: ros-dpi
    restart: unless-stopped
    ports:
      - "8080:8080/tcp"     # Web 界面
      - "2055:2055/udp"     # IPFIX / NetFlow：RouterOS Traffic Flow 发到这里
      - "37008:37008/udp"   # TZSP：RouterOS 镜像的 DNS 应答发到这里
    environment:
      TZ: Asia/Shanghai
      # MySQL 连接信息在首次打开网页时填写（保存在 ./data/db_config.json）
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
      - ./data:/app/data      # 保存数据库连接配置，务必保留这个卷
```

**No MySQL yet? / 还没有 MySQL？** Use [docker-compose.with-mysql.yml](https://github.com/suyijun8182/ros-dpi/blob/main/docker-compose.with-mysql.yml). It starts MySQL 8.4 too and is pre-configured, so the database step is skipped. 这个文件会同时启动 MySQL 并且已配置好连接，不需要建库，也不需要在网页上填写。

## First run / 首次使用

Open `http://<host>:8080`. The setup wizard has two steps. 打开网页后按两步完成：

1. **Connect MySQL / 连接数据库**: host, port, user, password, database, with a connection test. Tables are created automatically, and the connection is saved to `./data/db_config.json`. If MySQL runs on the same machine, use its LAN IP, not `127.0.0.1`. 填写 MySQL 信息，可先测试连接；MySQL 在本机时填局域网 IP，不要填 127.0.0.1。
2. **Create admin / 设置管理员密码**.

- Change database later: delete `./data/db_config.json` and restart. 更换数据库：删除该文件后重启容器。
- Setting `DATABASE_URL` skips the wizard. 设置环境变量 `DATABASE_URL` 可跳过向导。
- RouterOS commands: **Settings → Setup guide**. Full guide: https://github.com/suyijun8182/ros-dpi

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
