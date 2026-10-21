# ROS-DPI

RouterOS 终端流量与应用统计面板。按 今日 / 本周 / 本月 统计每台终端的流量和应用使用情况，类似 Panabit / 碧海威。

Per-device traffic and per-application (DPI-style) statistics for MikroTik RouterOS, built on IPFIX + DNS sniffing.

Source & docs: https://github.com/suyijun8182/ros-dpi

## What's new

- **0.1.0**: first release. Overview, hosts, applications, flow Sankey, custom rules, setup guide. zh/en, light/dark.

## Features

- IPFIX / NetFlow v9 collector (udp/2055), TZSP DNS sniffer (udp/37008), optional read-only RouterOS REST polling
- 100+ built-in apps in 20+ categories; custom domain / CIDR / port rules
- Per-minute / hour / day aggregation in MySQL

## Quick start

```bash
curl -O https://raw.githubusercontent.com/suyijun8182/ros-dpi/main/docker-compose.yml
curl -o .env https://raw.githubusercontent.com/suyijun8182/ros-dpi/main/.env.example
# edit .env (MySQL passwords, LAN_CIDRS)
docker compose up -d
```

Open `http://<host>:8080`. RouterOS commands are shown in **Settings → Setup guide**.

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
