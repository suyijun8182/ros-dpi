# ROS-DPI

**RouterOS 终端流量与应用统计面板**：像 Panabit / 碧海威那样，按 今日 / 本周 / 本月 统计 RouterOS 下每台终端用了多少流量、用在了哪些应用上。

[中文](#中文) · [English](#english)

![全网概览](docs/images/overview-light.png)

---

## 中文

### 能做什么

- **全网概览**：一屏看全的仪表盘：路由器状态、**网络健康指数**（逐项扣分和改进建议）、在线终端、**DHCP 地址池**、每条 **WAN 线路**的状态和速率；流量构成环图（应用大类 → 小类）；实时流量、流量趋势、历史在线终端数；Top 应用与 Top 终端排行。
- **主机监控**：在线终端 / 全部终端 / DHCP 租约 / 命名管理四个标签。每台终端的 IP、MAC、主机名、在线时长、连接数、当前速率、今日 / 本周 / 本月流量，可导出 CSV；可以按 MAC 或按 IP 给设备命名（也能提前给还没上线的设备命名）；详情页可看该终端的应用排行、应用构成、按大类的趋势和访问过的域名。
- **应用统计**：参照 Panabit / 维盟分三级（应用大类 → 小类 → 应用，逐级「查看详情」下钻，每级显示上传 / 下载速度和数据及占比）：10 个大类、43 个小类、2800 多个内置应用（抖音、B 站、微信视频号、Steam、银行、券商、ToDesk、DeepSeek……，其中约 2500 个来自 v2fly 开源域名库）。识别不出具体应用的流量，会按 CDN 的 CNAME 归到阿里云 / 腾讯云 / Akamai 等厂商。可以查看每个应用被哪些终端使用。
- **流量流向**：**实时连接**（此刻哪台终端连到哪个域名 / IP、什么应用、多快；走 sing-box 的连接显示策略组和出口节点）、**访问目标排行**（流量最大的远端域名和 IP，显示国家 / 地区及分布，可按主域名合并，看是哪些终端在访问）和**代理分流**（sing-box 各策略组、各节点的流量与主要应用）。
- **识别规则**：按域名后缀、IP 段、端口自定义识别规则；列出“未识别域名 Top”，一键归类。
- **审计日志**：访问日志（每台终端什么时候访问了什么、多久、多少流量，可筛选、导出 CSV，默认保留 30 天）；终端的上网时间线；审计规则（按应用、域名、时段、流量、新设备）命中时推送到企业微信 / 钉钉 / 飞书 / Bark / Telegram / Webhook；日报和周报；操作日志。
- **管理员与普通用户**：普通用户只能查看，不能修改设置和规则；在 系统设置 → 用户管理 添加。
- **人员与使用场景**：把一个人的多台设备归到一起，按人看流量、在线时长和行为标签。**家用**场景关注孩子的上网健康（屏幕时间、游戏和短视频上限、熬夜、不良内容）；**企业**场景关注效率与合规（工作时间娱乐占比、求职倾向、上班炒股、大流量外发、私接路由）。终端类型（手机、电脑、电视、摄像头……）自动识别。
- **合规与管控**：Syslog 外发访问日志和审计事件；留存天数可在网页设置；按人员 / 设备生成 RouterOS 管控命令（封禁应用、定时断网、限速，附撤销命令，ROS-DPI 不直接改路由器）。通知支持企业微信、钉钉、飞书、Bark、Telegram、邮件、PushPlus、Server酱、ntfy、Gotify、Discord、Slack、Webhook，可设免打扰。
- 顶栏功能搜索（终端、IP、MAC、应用、页面），按 / 键聚焦。
- 中英双语，深浅色主题，手机可用。

![应用统计](docs/images/apps-light.png)

![流量流向](docs/images/flow-light.png)

### 工作原理

RouterOS 本身没有 DPI，ROS-DPI 用两路数据拼出应用级统计：

```
RouterOS ──IPFIX  udp/2055 ──▶ 流量采集：每条连接的终端、远端 IP、端口、字节数
RouterOS ──TZSP   udp/37008──▶ DNS 嗅探：远端 IP 是哪个域名解析出来的
                             ▶ SNI：每条 HTTPS / QUIC 连接握手里的目标域名
RouterOS ◀─REST 只读（可选）── 主机名、IP↔MAC、WAN 口速率、LAN 前缀
                    ↓
         域名 → 应用规则库 → 按 分钟 / 小时 / 天 汇总写入 MySQL
```

- 流量来自 `/ip traffic-flow`（IPFIX），统计的是真实字节数。
- 应用识别靠域名，有两个来源：
  - **SNI**（推荐开启）：每条 HTTPS 连接开头的 TLS 握手里有明文的目标域名；HTTP/3（QUIC）的握手包也能解开。按连接识别，最准，终端用加密 DNS 也有效。
  - **DNS 嗅探**：终端访问 `v26.douyinvod.com` 时，路由器把 DNS 应答镜像一份过来，之后发往该 IP 的流量就归到“抖音”。
  - 查找顺序由准到粗：这条连接的 SNI → 这台终端对该 IP 的 DNS / SNI → 全网的 IP→域名 表。都查不到时，依次按 IP 段、端口兜底（HTTPS / QUIC 等）。**系统设置 → 运行状态 → 域名来源** 会显示各来源的占比。
- 域名 → 应用：手工维护的规则库（约 280 个常用应用，带中文名和细分类），加上从 [v2fly/domain-list-community](https://github.com/v2fly/domain-list-community) 转换来的约 2500 个应用、3.6 万条域名。
- 终端用 MAC 区分（来自 ROS 的 ARP / DHCP，或流记录中的源 MAC），IP 变化不影响统计。

**已知局限**：只开 DNS 嗅探时，终端使用 DoH / DoT 加密 DNS 的流量只能识别为 HTTPS / QUIC，开启 SNI 识别可以补上。启用了 ECH（加密 ClientHello）的少数网站，SNI 只能看到外层的公共名字。

**内网有自己的 DNS 服务器（AdGuard Home / Pi-hole 等）时**：DNS 嗅探照样能用。终端查询内网 DNS 走的是交换机，路由器看不到；但内网 DNS 向上游（如 223.5.5.5）查询时，应答要经过路由器，会被 `forward` 那条规则嗅探到，同样能得到“IP → 域名”的对应关系。前提是内网 DNS 的上游用普通 DNS（udp/53）；上游设成 DoH / DoT 时路由器看不到域名，可以把上游改成普通 DNS，或者改成路由器地址。**系统设置 → DNS 嗅探** 里的“应答来源”会显示应答来自哪台 DNS 服务器。

### 部署

ROS-DPI 把统计数据存在 **MySQL**（5.7 / 8.x 均可）。默认你已经有一个 MySQL，比如 NAS 自带的、单独跑的容器，或者其他服务器上的。只需要给 ROS-DPI 建一个库和账号，连接信息在**第一次打开网页时填写**，和 EasySub 的流程一样。还没有 MySQL 的话，见[自带 MySQL 的部署方式](#还没有-mysql)。

#### 1. 准备数据库

用 root 或其他管理员账号登录 MySQL，执行以下语句（把 `your-password` 换成你自己的密码）：

```sql
CREATE DATABASE rosdpi CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'rosdpi'@'%' IDENTIFIED BY 'your-password';
GRANT ALL PRIVILEGES ON rosdpi.* TO 'rosdpi'@'%';
FLUSH PRIVILEGES;
```

- 命令行：`mysql -h <MySQL地址> -u root -p`，输入 root 密码后粘贴上面的语句。MySQL 跑在容器里时，可以用 `docker exec -it <mysql容器名> mysql -u root -p`。
- 图形界面（phpMyAdmin、群晖 / 飞牛的 MariaDB 管理页、Navicat、DBeaver 等）：打开 SQL 窗口粘贴执行；或者按界面新建数据库 `rosdpi`（字符集选 `utf8mb4`），再新建用户 `rosdpi`，主机填 `%`，授予该库的全部权限。
- 表不用手动建，ROS-DPI 会自动创建。如果直接用 root 账号，连库都可以不建，安装向导会自动创建。
- 如果 MySQL 只允许本机连接，需要把 `bind-address` 改为 `0.0.0.0`，并确认运行 ROS-DPI 的主机能访问 3306 端口。

#### 2. 编写 `docker-compose.yml` 并启动

新建一个目录，保存下面的内容（也可以直接下载：`curl -O https://raw.githubusercontent.com/suyijun8182/ros-dpi/main/docker-compose.yml`），把 `LAN_CIDRS` 改成你的内网网段：

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

```bash
docker compose up -d
```

镜像同时发布在 Docker Hub（`suyijun8182/ros-dpi`）和 GHCR（`ghcr.io/suyijun8182/ros-dpi`），支持 amd64 / arm64。群晖、飞牛、威联通等 NAS 可以在 Docker / Container Manager 里新建“项目”，把 compose 内容粘贴进去即可。

#### 还没有 MySQL？

用 [`docker-compose.with-mysql.yml`](docker-compose.with-mysql.yml)：它会同时启动一个 MySQL 8.4 容器，自动建好库和账号，并且已经把连接信息写进了配置，**不需要第 1 步，网页上也不会出现数据库设置**。下载后改名为 `docker-compose.yml`，改掉其中三处「必改」（两处数据库密码要一致，以及 `LAN_CIDRS`），然后 `docker compose up -d`。MySQL 第一次初始化需要 20～60 秒。

```bash
curl -o docker-compose.yml https://raw.githubusercontent.com/suyijun8182/ros-dpi/main/docker-compose.with-mysql.yml
```

### 首次使用

浏览器打开 `http://<主机IP>:8080`，按两步完成设置：

1. **连接数据库**：填写 MySQL 地址、端口、账号、密码、数据库名。可以先点“测试连接”，没问题再点“保存并继续”。ROS-DPI 会自动建表，并把连接信息保存在 `./data/db_config.json`，之后重启不用再填。
   - MySQL 和 ROS-DPI 在同一台机器上时，地址填这台机器的局域网 IP，**不能填 `127.0.0.1` 或 `localhost`**（在容器里它指向容器自己）。
   - 连接失败时，页面会直接说明原因（地址不通、账号或密码错误、没有权限等）。
2. **设置管理员**：设置 admin 的密码后自动登录。如果在 compose 里填了 `ADMIN_PASSWORD`，这一步会跳过，直接用 `admin` 和该密码登录。

![安装向导](docs/images/setup-wizard.png)

完成后，到 **系统设置 → 接入向导** 复制 RouterOS 命令，在路由器终端执行（见下一节）。大约 1 分钟后，概览页开始有数据。

**常见问题**

| 现象 | 原因与处理 |
|---|---|
| 提示“连不上 MySQL” | 地址或端口不通，或者填了 `127.0.0.1`；MySQL 需要允许远程连接（`bind-address`），防火墙要放行 3306 |
| 提示“账号或密码错误” | 检查密码；账号的主机要是 `%`，只允许 `localhost` 的账号无法从容器连接 |
| 提示“没有该数据库的权限” | 执行第 1 步的 `GRANT` 语句 |
| 重启后网页显示“正在连接数据库” | MySQL 还没启动完成，页面会每 5 秒自动重试，不需要重新填写 |
| 需要更换数据库 | 删除 `./data/db_config.json`，然后重启容器，会重新出现安装向导 |
| 忘记管理员密码 | 在 MySQL 中执行 `DELETE FROM rosdpi.users;`，然后刷新网页重新设置，统计数据不受影响 |

### RouterOS 配置

把 `192.168.88.10` 换成运行容器的主机 IP（**系统设置 → 接入向导**里可以直接复制填好 IP 的命令）：

```routeros
# 1. 流量采集（IPFIX）
/ip traffic-flow set enabled=yes interfaces=all active-flow-timeout=1m inactive-flow-timeout=15s
/ip traffic-flow target add dst-address=192.168.88.10 port=2055 version=ipfix

# 2. DNS 嗅探（应用识别）
/ip firewall mangle add chain=output protocol=udp src-port=53 action=sniff-tzsp sniff-target=192.168.88.10 sniff-target-port=37008 comment=ROSDPI-DNS
/ip firewall mangle add chain=forward protocol=udp src-port=53 action=sniff-tzsp sniff-target=192.168.88.10 sniff-target-port=37008 comment=ROSDPI-DNS

# 3. SNI 识别（推荐：按连接识别，终端用加密 DNS 也有效）
/ip firewall mangle add chain=forward protocol=tcp dst-port=443 connection-bytes=0-4000 action=sniff-tzsp sniff-target=192.168.88.10 sniff-target-port=37008 comment=ROSDPI-SNI
/ip firewall mangle add chain=forward protocol=udp dst-port=443 connection-bytes=0-4000 action=sniff-tzsp sniff-target=192.168.88.10 sniff-target-port=37008 comment=ROSDPI-SNI

# 4. 只读 API 账号（可选：主机名、WAN 速率）
/user group add name=rosdpi policy=read,rest-api,api,!write,!policy,!sensitive
/user add name=rosdpi group=rosdpi password=<强密码> address=192.168.88.10
```

更多说明（SNI 的开销、FastTrack、双 NAT、IPv6、排错）见 [docs/RouterOS配置.md](docs/RouterOS配置.md)。

### 旁路代理与内网 DNS（可选）

家里用旁路代理（sing-box 做旁路由）或内网 DNS（MosDNS）时，路由器看到的多是代理的加密隧道，识别率会很低。在 **系统设置 → 外部数据源** 填写：

- **sing-box Clash API**（`experimental.clash_api.external_controller` 和 `secret`）：按“哪台终端、哪个域名、多少字节”统计走代理的流量，代理自身的隧道流量不再重复计算；域名认不出具体应用时按命中的规则集 / 策略组名识别；流量流向 → 代理分流 按策略组和出口节点统计。
- **MosDNS 审计 API**：知道每台终端查了哪个域名、解析出哪些 IP。

地址每个人都不一样，都不填就不启用。

### 识别库与自动更新

识别靠三份库：内置规则库（手工维护，随版本更新）、[v2fly/domain-list-community](https://github.com/v2fly/domain-list-community)（每天自动检查更新，自检通过后热加载）、[iptoasn.com](https://iptoasn.com) 的 IP 归属库（每天自动下载）。三者的版本和状态在 **识别规则 → 识别库** 查看，也可以关闭自动更新。自动更新需要容器能访问外网；文件保存在 `./data` 卷里。

### 环境变量

| 变量 | 默认值 | 说明 |
|---|---|---|
| `DATABASE_URL` | 空 | 留空则用网页安装向导；设置后跳过向导，格式 `mysql+pymysql://user:pass@host:3306/rosdpi?charset=utf8mb4` |
| `LAN_CIDRS` | 私网三段 + `fd00::/8` | 内网网段，逗号分隔，界面里也能改 |
| `ADMIN_PASSWORD` | 空 | 首次启动创建 `admin` 用的密码；留空则在登录页设置 |
| `ROS_URL` / `ROS_USER` / `ROS_PASSWORD` | 空 | RouterOS REST 地址与只读账号，如 `https://192.168.88.1` |
| `ROS_VERIFY_TLS` | `false` | 是否校验 ROS 证书 |
| `ROS_POLL_SECONDS` / `ROS_RATE_SECONDS` | 30 / 5 | RouterOS 完整轮询间隔 / WAN 口速率采样间隔（实时流量图） |
| `SINGBOX_URL` / `SINGBOX_SECRET` / `PROXY_IPS` | 空 | 旁路代理 sing-box 的 Clash API（也可在网页填写，网页优先） |
| `MOSDNS_URL` | 空 | MosDNS 审计 API 地址（也可在网页填写） |
| `FAKEIP_CIDRS` | `198.18.0.0/15,fc00::/18` | FakeIP 地址段 |
| `ASN_DB` | `true` | 自动下载 IP→ASN 库；没有外网时设为 `false` |
| `OUI_DB` | `true` | 自动下载 IEEE MAC 厂商库（识别终端类型，每 30 天更新）；没有外网时设为 `false` |
| `WAN_INTERFACE` | 自动 | WAN 接口名，默认按默认路由识别 |
| `TZ` | `Asia/Shanghai` | 统计用时区，每周从周一开始 |
| `HTTP_PORT` / `IPFIX_PORT` / `TZSP_PORT` | 8080 / 2055 / 37008 | 端口 |
| `RETENTION_*_DAYS` | 2 / 45 / 730 / 31 | 分钟 / 小时 / 每日 / 域名明细的保留天数 |
| `RETENTION_LOG_DAYS` / `RETENTION_EVENT_DAYS` | 30 / 180 | 访问日志 / 审计事件和操作日志的保留天数 |
| `SECRET_KEY` | 自动生成 | 登录令牌签名密钥 |

### 开发

```bash
# 后端
cd backend && python -m venv .venv && .venv/bin/pip install -r requirements.txt pytest
DATABASE_URL=sqlite:///./dev.db .venv/bin/uvicorn app.main:app --port 8080
.venv/bin/python -m pytest

# 前端
cd frontend && npm install && npm run dev   # http://localhost:5173，/api 代理到 8080

# 灌入模拟数据
backend/.venv/bin/python scripts/simulate.py --minutes 5
```

应用规则库：

- [backend/app/classify/apps.yaml](backend/app/classify/apps.yaml)：手工维护，优先级高，欢迎 PR 补充。
- [backend/app/classify/apps_v2fly.yaml](backend/app/classify/apps_v2fly.yaml)：由 `python scripts/import_v2fly.py` 从 v2fly/domain-list-community 生成，不要手工修改；更新时重新运行脚本即可。

---

## English

**ROS-DPI** shows per-device traffic and per-application usage (today / this week / this month) for networks behind a MikroTik RouterOS router, in the spirit of Panabit-style DPI dashboards.

- **Overview**: a dashboard with router status, a network health score with fixes, DHCP pool usage, WAN line status, online-host history, live rate, and a two-ring traffic-mix donut (app group → category), trends stacked by app group, ranked top apps and hosts.
- **Hosts**: every device with IP, MAC, hostname, online state, live rate and daily / weekly / monthly totals; name devices by MAC or by IP (even before they appear); per-host app breakdown and visited domains.
- **Applications**: a Panabit-style three-level library: 10 app groups, 43 categories, 2800+ built-in apps (about 2500 converted from v2fly/domain-list-community). Traffic that can't be tied to an app is attributed to its CDN (Alibaba Cloud, Tencent Cloud, Akamai, Cloudflare…) via CNAME.
- **Flows**: live connections (which host talks to which domain or IP, which app, how fast; sing-box connections show their policy group and outbound node), top destinations (remote domains and IPs by traffic with country, mergeable by base domain, with the hosts behind each) and proxy routing (traffic and top apps per sing-box policy group and node).
- **Rules**: custom domain / CIDR / port rules, and a list of top unidentified domains to classify.
- **Audit**: an access log of every visit (who reached what, when, for how long and how much; filterable, CSV export, kept 30 days), a per-host daily timeline, audit rules (by app, domain, time window, traffic or new device) that push alerts to WeCom / DingTalk / Feishu / Bark / Telegram / webhooks, daily and weekly reports, and an operation log.
- **Admins and users**: regular users are read-only; add them under Settings → Users.
- **People and scenarios**: group a person's devices and see their traffic, online time and behaviour tags. The **home** scenario focuses on children's online health (screen time, gaming and short-video limits, late nights, adult content); the **business** scenario on productivity and compliance (leisure at work, job hunting, trading at work, large uploads, rogue routers). Device types are detected automatically.
- **Compliance and control**: Syslog forwarding of the access log and audit events, retention set in the web UI, and generated RouterOS control commands (block apps, scheduled blocks, rate limits, with undo; ROS-DPI never writes to the router). Notifications via WeCom, DingTalk, Feishu, Bark, Telegram, email, PushPlus, ServerChan, ntfy, Gotify, Discord, Slack and webhooks, with quiet hours.
- Chinese and English UI, light and dark themes, works on phones.

**How it works.** RouterOS exports IPFIX (`/ip traffic-flow`) for byte counts, and mirrors DNS answers plus the first packets of each HTTPS/QUIC connection via `sniff-tzsp`. The TLS / QUIC handshake carries the target domain (SNI) per connection; DNS answers map remote IPs back to the domain the client looked up. A rule library maps domains to apps. An optional read-only REST user provides hostnames, IP-to-MAC, WAN rate and LAN prefixes. Data is aggregated per minute, hour and day into MySQL.

**Side-router proxy and LAN DNS (optional).** If you run sing-box as a side router or MosDNS as LAN DNS, fill in their Clash API / audit API under Settings → External sources: proxied traffic is then counted per device and domain, and per-device DNS answers are used for identification. **Library updates.** v2fly rules are checked daily and hot-reloaded after a self-test; an IP→ASN database from iptoasn.com (public domain) identifies domain-less traffic by owner.

**Limitations.** With DNS sniffing alone, clients using DoH/DoT show up as generic HTTPS/QUIC; SNI covers them. Sites using ECH only expose their outer public name. A LAN DNS server (AdGuard Home, Pi-hole…) works fine as long as its upstream is plain DNS on udp/53: its upstream answers pass through the router and are sniffed by the `forward` rule.

**Deploy.** ROS-DPI stores data in **MySQL** (5.7 / 8.x) and assumes you already have one. Create a database and user for it:

```sql
CREATE DATABASE rosdpi CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'rosdpi'@'%' IDENTIFIED BY 'your-password';
GRANT ALL PRIVILEGES ON rosdpi.* TO 'rosdpi'@'%';
FLUSH PRIVILEGES;
```

Save the `docker-compose.yml` shown above (or `curl -O https://raw.githubusercontent.com/suyijun8182/ros-dpi/main/docker-compose.yml`), set `LAN_CIDRS`, and run `docker compose up -d`. Images: `suyijun8182/ros-dpi` on Docker Hub and `ghcr.io/suyijun8182/ros-dpi`, amd64/arm64.

No MySQL yet? Use [`docker-compose.with-mysql.yml`](docker-compose.with-mysql.yml): it starts MySQL 8.4 alongside and is pre-configured, so the database step is skipped.

**First run.** Open `http://<host>:8080`. A two-step setup wizard asks for (1) the MySQL host, port, user, password and database, with a connection test, and (2) the admin password. Tables are created automatically and the connection is saved to `./data/db_config.json`. If MySQL runs on the same machine, use its LAN IP, not `127.0.0.1`. To change databases later, delete that file and restart. Setting `DATABASE_URL` skips the wizard. RouterOS commands are listed above and in **Settings → Setup guide**.

## License

[MIT](LICENSE)

`backend/app/classify/apps_v2fly.yaml` is generated from [v2fly/domain-list-community](https://github.com/v2fly/domain-list-community) (MIT License, Copyright (c) 2019-present V2Fly Community).
