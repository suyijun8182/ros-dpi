# ROS-DPI

RouterOS 终端流量、应用统计与上网审计面板。按 今日 / 昨日 / 本周 / 本月 统计每台终端、每个人的流量和应用使用情况（类似 Panabit / 维盟），记录访问日志并按规则告警（参照深信服 AC）；分家庭和企业两种场景。

Per-device and per-person traffic, per-application (DPI-style) statistics and access auditing for MikroTik RouterOS, built on IPFIX + DNS / SNI sniffing.

Source & docs: https://github.com/suyijun8182/ros-dpi

## 两种部署方式 / Two ways to deploy

**Linux 一键安装（无需 Docker，SQLite 零配置起步，网页一键升级）**：

```bash
curl -fsSL https://raw.githubusercontent.com/suyijun8182/ros-dpi/main/install.sh | sudo bash
```

**Docker Compose（自带 MySQL 的模板见仓库）**：

```yaml
services:
  ros-dpi:
    image: suyijun8182/ros-dpi:latest
    restart: unless-stopped
    ports:
      - "8080:8080/tcp"
      - "2055:2055/udp"
      - "37008:37008/udp"
    environment:
      TZ: Asia/Shanghai
      LAN_CIDRS: 192.168.88.0/24
    volumes:
      - ./data:/app/data
```

前提：已有 MySQL 5.7+（建库语句见仓库 README）；还没有 MySQL 用仓库里的 `docker-compose.with-mysql.yml`。镜像同时发布在 GHCR，支持 amd64 / arm64，每次发版带版本标签。

## What's new

- **0.6.22**: 社区主站地址可在网页填写，新增 VPS 主站部署模板（`deploy/hub/`，Docker + Caddy 自动 HTTPS）；接入向导与文档补上 IPv6 嗅探（`/ipv6 firewall mangle` 4 条）和 FastTrack（IPv4 / IPv6）命令；自检检查 IPv6 的 FastTrack。Setup guide and docs now include IPv6 sniff rules and FastTrack commands for both families; the self-check also flags IPv6 FastTrack without a connection-bytes limit.
- **0.6.21**: 社区共享库重做——项目自带社区主站，不再需要 WebDAV / 第三方存储：令牌注册、按来源网络计票（≥2 个不同网络一致才发布，防伪造实例刷票）、ETag 增量拉取、本地缓存；修复 0.6.20 部署量接口 500、共享任务从未运行、开关保存不上。接入自检新增 IPv6 嗅探规则检查，FastTrack 已限定 connection-bytes 时不再误报，并直接给出修改命令。Community library rebuilt around a built-in hub (no WebDAV/third-party storage): per-instance tokens, votes counted per source network, ETag pulls, local cache; fixes the 0.6.20 deployments 500 and the never-running share job. Self-check now flags missing IPv6 sniff rules.
- **0.6.12 / 0.6.11 / 0.6.10 / 0.6.9 / 0.6.8**: 自学习与共享系列。**本地自学习库**：本网络实测的「IP → 应用」（IPv6 按 /64 前缀聚合）与「域名 → 应用」长期记忆，每小时重建，DNS 缓存过期、DoH、裸 IP 流量都能按记忆归类；**社区共享库**：各部署实例把实测结论匿名共享（中转聚合、至少 2 个实例见过才发布），本地实测优先、社区只补空白；**全球部署量**：实例心跳上报，中转公开已部署 / 在线 / 离线数量；共享总开关默认打开；**一键自更新**：Linux 二进制部署在网页上检测并一键升级（自动下载、替换、重启服务）；**Linux 单文件二进制部署**：`install.sh` 一键安装 systemd 服务（SQLite 零配置起步）；修复落库卡死（代理长域名撑爆 access_log.remote 列导致每分钟落库失败、在线终端归零）；组播 / 广播流量不再计入统计；17 个 DPI 大类配色互异。
- **0.6.7**: fixes for the 0.6.5 / 0.6.6 history reclassification and rule auto-registration. Reclassification now only touches days before today and only upgrades vague rows (HTTPS / Chinese websites / unknown / CDN) to a specific app — it no longer downgrades apps identified live by IP range, port or ASN. New upstream blackmatrix7 directories are downloaded first and then assigned by a vote of the existing libraries. The manual dark theme now uses the 17 distinct group colors, and the AdGuard Home password is masked in the operation log.
- **0.6.6**: AdGuard Home's newer query-log format (`{"data": [...]}`) is now read (0.6.5 always got 0 answers); new upstream rule directories / lists are registered automatically; history reclassification looks up the DNS cache for IP-only rows and runs automatically after library updates.
- **0.6.5**: AdGuard Home as an external DNS source (for double-NAT setups where the router can't see downstream DNS); ASN ranges for Chinese first-party content providers (ByteDance, Bilibili, iQIYI, miHoYo, JD, Taobao, NetEase…); "Reclassify history" on the Rules page re-assigns the last 31 days with current rules; 17 distinct DPI group colors.
- **0.6.4**: app-group colors now match WayOS's DPI pie, and the traffic-mix pie is drawn in the fixed group order like WayOS; the rule-library panel is grouped by tier with a one-line explanation per tier; the four official IP-range feeds are merged into one row.
- **0.6.3**: app groups now follow WayOS's 17 DPI classes, always listed in that order; new categories HTTPS/QUIC, databases (by port), mining pools and PCDN. Category ids are unchanged, so history is kept; saved analysis settings and group-based audit rules are migrated automatically. "Details" now opens a WayOS-style "DPI protocol details" dialog.
- **0.6.2**: fixes external sources (sing-box / MosDNS) showing "not enabled" after 0.6.0; three more rule sources downloaded at runtime: **blackmatrix7** per-app rules (GPL-2.0, weekly), **Hagezi** (GPL-3.0) and **UT1** (CC BY-SA 4.0) category lists; notification channels now match EasySub exactly — 14 channels; the scenario (Home / Business) is a global setting.
- **0.6.1**: much higher identification rate: dnsmasq-china-list (~110k Chinese domains), official Google / Cloudflare / AWS / GitHub IP ranges plus Apple's 17.0.0.0/8, and China IP ranges (chnroutes2) as fallbacks. Purely additive — existing rules always take priority.
- **0.6.0**: reliability & hardening: a failed database write no longer loses that minute's data (kept in memory and retried for up to 2 hours); login rate limiting; immediate token revocation on password change; batched retention cleanup; destination ranking aggregated in SQL.
- **0.6.0 之前 / earlier**: 0.5.x added people & scenarios (home / business), audit system with 13 notification channels, per-visit access log and reports; 0.4.x added the WayOS-style DPI drill-down, sing-box integration, IP→ASN identification; 0.2.x–0.3.x added the WayOS 4.0-style UI, 2800+ apps from v2fly, per-connection SNI from TLS and QUIC handshakes.

## Features

- IPFIX / NetFlow v9 collector (udp/2055), TZSP sniffer for DNS answers and TLS/QUIC handshakes (udp/37008), optional read-only RouterOS REST polling
- 2900+ apps in 50 categories under 17 app groups (WayOS-style DPI classes), plus Hagezi / UT1 category lists, China lists and IP-range fallbacks; custom domain / CIDR / port rules
- **Self-learning library**: your network's observed IP→app and domain→app mappings as long-term memory (hourly rebuild, IPv6 aggregated by /64)
- **Community sharing**: pool anonymous IP→app and domain→app votes across deployments through a relay; mappings seen by 2+ instances are published; global deployment counter (total / online / offline)
- **Self-update**: Linux binary deployments detect new releases and update with one click from the UI
- Per-connection SNI from TLS and QUIC handshakes mirrored via TZSP
- Audit: access log, per-host timeline, alert rules with push notifications (14 channels), daily / weekly reports, operation log
- People and departments (home / business scenarios), behaviour tags, device-type detection
- Admin and read-only user accounts; zh/en UI, light/dark themes

## Quick start

**Linux one-line install / 一键安装（无需 Docker）**

```bash
curl -fsSL https://raw.githubusercontent.com/suyijun8182/ros-dpi/main/install.sh | sudo bash
```

SQLite out of the box; upgrades are one click in the UI. 想用 MySQL：设 `DATABASE_URL` 后重启服务。

**Docker Compose（已有 MySQL / with your MySQL）**

前提：已有 MySQL 5.7+（建库语句见仓库 README）。Set `LAN_CIDRS`, then `docker compose up -d`.

```yaml
services:
  ros-dpi:
    image: suyijun8182/ros-dpi:latest
    restart: unless-stopped
    ports:
      - "8080:8080/tcp"
      - "2055:2055/udp"
      - "37008:37008/udp"
    environment:
      TZ: Asia/Shanghai
      LAN_CIDRS: 192.168.88.0/24
    volumes:
      - ./data:/app/data
```

**No MySQL yet? / 还没有 MySQL？** Use `docker-compose.with-mysql.yml` from the repo. 这个文件会同时启动 MySQL 并且已配置好连接，不需要建库，也不需要在网页上填写。

## First run / 首次使用

Open `http://<host>:8080`. The setup wizard has two steps. 打开网页后按两步完成：

1. **Connect MySQL / 连接数据库**: host, port, user, password, database, with a connection test. Tables are created automatically. MySQL 在本机时填局域网 IP，不要填 127.0.0.1。
2. **Create admin / 设置管理员密码**.

- Change database later: delete `./data/db_config.json` and restart. 更换数据库：删除该文件后重启容器。
- RouterOS commands: **Settings → Setup & check / 系统设置 → 接入与自检**. Full guide: https://github.com/suyijun8182/ros-dpi
- Then choose the scenario under **Settings → Scenario & network**, assign devices to people, and set up notifications under **Audit → Notifications**.

## Ports

| Port | Use |
|---|---|
| 8080/tcp | Web UI |
| 2055/udp | IPFIX / NetFlow v9 |
| 37008/udp | TZSP (DNS answers + TLS/QUIC handshakes) |

## Environment

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | set in compose | `mysql+pymysql://user:pass@host:3306/rosdpi?charset=utf8mb4`；二进制部署留空则用 SQLite |
| `LAN_CIDRS` | private ranges | LAN ranges, comma separated |
| `ADMIN_PASSWORD` | empty | initial password for `admin` |
| `ROS_URL` / `ROS_USER` / `ROS_PASSWORD` | empty | RouterOS REST + read-only user |
| `SINGBOX_URL` / `MOSDNS_URL` / `ADGUARD_URL` | empty | external sources (Clash API, MosDNS audit, AdGuard Home query log) |
| `SHARE_HUB_URL` | `https://rosdpi.suyijun.top:8443` | community hub (built in); point it at your own hub for a private community |
| `SHARE_HUB` | `false` | run this instance as the community hub (only the hub sets `true`) |
| `SHARE_VERIFY_TLS` | `true` | verify the hub certificate; set `false` only for a private hub with a self-signed cert |
| `TZ` | `Asia/Shanghai` | statistics time zone (weeks start Monday) |

Full list: https://github.com/suyijun8182/ros-dpi#环境变量
