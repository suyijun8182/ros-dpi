# ROS-DPI

RouterOS 终端流量、应用统计与上网审计面板。按 今日 / 昨日 / 本周 / 本月 统计每台终端、每个人的流量和应用使用情况（类似 Panabit / 维盟），记录访问日志并按规则告警（参照深信服 AC）；分家庭和企业两种场景。

Per-device and per-person traffic, per-application (DPI-style) statistics and access auditing for MikroTik RouterOS, built on IPFIX + DNS / SNI sniffing.

Source & docs: https://github.com/suyijun8182/ros-dpi

## What's new

- **0.6.4**: app-group colors now match WayOS's DPI pie (ECharts' 9 default colors cycled over the 17 groups), and the traffic-mix pie is drawn in the fixed group order like WayOS; the rule-library panel is grouped by tier (apps by domain, apps by IP, categories by domain, fallbacks) with a one-line explanation per tier; the four official IP-range feeds are merged into one row.
- **0.6.3**: app groups now follow WayOS's 17 DPI classes (HTTP, online games, video/TV, P2P, common protocols, messaging, music, stock trading, VoIP, proxies, databases, mobile apps, special protocols, mining pools, PCDN, other, unknown), always listed in that order; new categories HTTPS/QUIC, databases (by port), mining pools and PCDN. Category ids are unchanged, so history is kept; saved analysis settings and group-based audit rules are migrated automatically. On the Applications page, "Details" now opens a WayOS-style "DPI protocol details" dialog that drills down group → category → app.
- **0.6.2**: fixes external sources (sing-box / MosDNS) showing "not enabled" after 0.6.0 — a broken upgrade backfill aborted startup initialisation, so saved sing-box / MosDNS settings, LAN ranges and custom rules were not loaded after a restart; no need to re-enter anything. Three more rule sources, downloaded at runtime (not in the image): **blackmatrix7** per-app rules (GPL-2.0, weekly) add domains / IP ranges to ~460 existing apps and ~100 new apps; **Hagezi** (GPL-3.0) and **UT1** (CC BY-SA 4.0) category lists (adult, gambling, VPN/proxy, device telemetry, games, shopping, news, job search, banks…). Order and weights: app-level domain sources (built-in, v2fly, blackmatrix7) are compared by longest matching suffix, ties go to built-in > v2fly > blackmatrix7; then app-level IP (CIDR, ports, ASN); then category lists (Hagezi > UT1); then the China domain list and IP-range fallbacks. On the Tranco top-10k, the share mapped to a specific category went from 19.6% to 35.7%. New category: Gambling. Disable with `BM7_DB` / `HAGEZI_DB` / `UT1_DB=false`. Also: notification channels now match EasySub exactly — 14 channels with the same fields: Telegram (API proxy, HTTP proxy, check bot / get Chat ID), Feishu app bot, new QQ bot, Bark icon, email SSL switch, Pushplus channel, WeCom group robot **or self-built app** (CorpID / AgentId / Secret, API proxy, user / department / tag, text card, "check app"), webhook timeout and retries. The scenario (Home / Business) is now a global setting under **Settings → Scenario & network**; in Business mode the menu says "Employees" instead of "Family members", and the last scenario is cached so the menu no longer flashes the wrong label. Identification order: domain fallbacks (China domain list) are tried before IP-range fallbacks, and overlapping IP ranges use longest-prefix match (before, a small range inside a big one could hide the big one). The "Auto update" switch now also controls the ASN and fallback list downloads. Note: Feishu now uses an app bot (App ID / Secret / Chat IDs) like EasySub; an old Feishu group-webhook config has to be re-entered.
- **0.6.1**: much higher identification rate. New fallback sources, all downloaded at runtime and auto-updated daily: the dnsmasq-china-list Chinese domain list (~110k domains, WTFPL) catches long-tail .cn domains as "Chinese websites" (sampling showed v2fly + built-in rules only matched 5.6% of them); official Google / Cloudflare / AWS / GitHub IP ranges plus Apple's 17.0.0.0/8 attribute domain-less traffic (DoH, ECH, raw IPs) to the owning company; China IP ranges (chnroutes2, CC-BY-SA 4.0) group domain-less domestic traffic as "China networks". Purely additive — existing rules always take priority. Disable with `CHINA_DB=false` / `IPLIST_DB=false`.
- **0.6.0**: reliability & hardening. A failed database write no longer loses that minute's traffic and access log (kept in memory and retried, giving up only after 2 hours); retention cleanup deletes in batches of 5000 rows instead of one long transaction, and `domain_geo` is now covered. Security: login rate limiting (5 failures locks the IP+username for 15 min), tokens are revoked immediately when a password or role changes, setup race protected, 500 errors no longer echo exception details. Performance: destination ranking aggregated in SQL (new `base` column for merging by registered domain, auto-backfilled), the people page scans the access log once instead of twice, the overview reuses today's app ranking. Frontend: polling race fixed (stale responses can no longer overwrite fresh data) and a dozen loads that could spin forever on error now show the error. CI builds the image on PRs; the container process runs as a non-root user; the bundled-MySQL compose now requires real passwords.
- **0.5.1**: people must belong to a group / department (no duplicates within a group; groups with members can't be deleted), and existing people can be edited and deleted again. Countries are shown on a flow map from your location with a ranked list; a domain's country is now stored when traffic is recorded, so it no longer turns "unlocated" after a restart. README brought up to date.
- **0.5.0**: people and scenarios: group devices per person (home: family members; business: people and departments), per-person traffic, online time and behaviour tags over the last 7 days (home: screen time, gaming and short-video limits, late nights, adult content; business: leisure at work, job hunting, trading at work), automatic device-type detection (IEEE OUI). Audit: rules scoped to people or departments, new large-upload and rogue-router (TTL-based) rules, Syslog forwarding, retention set in the UI, generated RouterOS control commands. Notifications rebuilt after EasySub with 13 channels, per-rule channel choice and quiet hours. Applications page with fixed categories and a treemap; destinations on a world map; date ranges trimmed to today / yesterday / this week / this month; consistent up/down colours.
- **0.4.0**: audit system: per-visit access log (CSV export, 30-day retention), per-host daily timeline, audit rules with alerts to WeCom / DingTalk / Feishu / Bark / Telegram / webhooks, daily and weekly reports, operation log. Admin and read-only user accounts. Applications page reworked as WayOS-style DPI drill-down (group → category → app). sing-box connections identified by rule-set / policy-group name, with a new proxy-routing view per policy group and node. Destinations show the country. Fixes: live up/down rates were almost identical when a policy-routing table pointed at a side router; the network status row no longer wraps with several WAN lines.
- **0.3.0**: optional sing-box Clash API and MosDNS integration (per-device proxied traffic and DNS), IP→ASN identification (iptoasn.com, public domain), daily self-tested auto-update of the v2fly rules, RouterOS rule self-check, page-by-page layout fixes for desktop / tablet / phone. Also includes 0.2.1: charts restyled after WayOS 4.0 (solid pie with paged legend, traffic card with live / history / online tabs, upright up/down lines); WAN rate sampled every 5 seconds for the live chart; the Flows page is now live connections plus top destinations (the Sankey diagram is gone).
- **0.2.0**: redesigned UI after WayOS 4.0 (sidebar layout, new "seven layers" logo, new login page); dashboard with network health score, DHCP pools, WAN line status and online-host history; session time and connection count per host; DHCP lease list; live per-app rates; top-bar search; CSV export. Also includes: 2800+ apps / ~38k domains (adds v2fly/domain-list-community, MIT); per-connection SNI identification from TLS ClientHello and decrypted QUIC Initial packets (v1/v2), so apps are identified even with DoH and on shared CDN IPs; domain-source breakdown in Settings.
- **0.1.4**: Panabit-style three-level app library (10 groups, 41 categories, 277 apps; CDN attribution via CNAME); redesigned charts (traffic-mix donut, trend stacked by app group, ranked lists, Sankey by group); name hosts by MAC or IP; DNS sniffer card shows which DNS servers answers come from.
- **0.1.3**: fix the 500 error on the overview page when the RouterOS API (`ROS_URL`) is configured; clearer RouterOS connection errors.
- **0.1.2**: first-run setup wizard: enter your MySQL connection in the browser, like EasySub. The compose file no longer needs database settings. A README guide covers creating the database.
- **0.1.1**: full `docker-compose.yml` on this page (no `.env` needed), first-run notes, database auto-created on external MySQL.
- **0.1.0**: first release. Overview, hosts, applications, flow Sankey, custom rules, setup guide. zh/en, light/dark.

## Features

- IPFIX / NetFlow v9 collector (udp/2055), TZSP sniffer for DNS answers and TLS/QUIC handshakes (udp/37008), optional read-only RouterOS REST polling
- 2900+ apps in 50 categories under 17 app groups (WayOS-style DPI classes; ~2500 from v2fly/domain-list-community, MIT; ~100 more from blackmatrix7 rules downloaded at runtime), plus Hagezi / UT1 category lists as a fallback; custom domain / CIDR / port rules
- Per-connection SNI from TLS and QUIC handshakes mirrored via TZSP
- Name hosts by MAC or by IP
- Audit: access log, per-host timeline, alert rules with push notifications, daily / weekly reports, operation log
- Admin and read-only user accounts
- People and departments (home / business scenarios), behaviour tags, device-type detection
- Syslog forwarding, configurable retention, RouterOS control-command generator, 13 notification channels
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
      - "37008:37008/udp"   # TZSP：RouterOS 镜像的 DNS 应答和 HTTPS/QUIC 握手包发到这里
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
- RouterOS commands: **Settings → Setup & check / 系统设置 → 接入与自检**. Full guide: https://github.com/suyijun8182/ros-dpi
- Then choose the scenario under **Settings → Scenario & network**, assign devices to people, and set up notifications under **Audit → Notifications**. 之后在 系统设置 → 场景与网络 选择场景（家庭 / 企业），把设备分给成员或员工，在 审计日志 → 通知渠道 配置推送。

## Ports

| Port | Use |
|---|---|
| 8080/tcp | Web UI |
| 2055/udp | IPFIX / NetFlow v9 |
| 37008/udp | TZSP (DNS answers + TLS/QUIC handshakes) |

## Environment

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | set in compose | `mysql+pymysql://user:pass@host:3306/rosdpi?charset=utf8mb4` |
| `LAN_CIDRS` | private ranges | LAN ranges, comma separated |
| `ADMIN_PASSWORD` | empty | initial password for `admin` |
| `ROS_URL` / `ROS_USER` / `ROS_PASSWORD` | empty | RouterOS REST + read-only user |
| `TZ` | `Asia/Shanghai` | statistics time zone (weeks start Monday) |
