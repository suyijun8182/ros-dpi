# ROS-DPI

**RouterOS 终端流量、应用统计与上网审计面板**：像 Panabit / 维盟那样，按 今日 / 昨日 / 本周 / 本月 统计 RouterOS 下每台终端、每个人用了多少流量、用在了哪些应用上；像深信服 AC 那样记录访问日志、按规则告警。支持家庭（孩子上网健康）和企业（效率与合规）两种场景。

[中文](#中文) · [English](#english)

![全网概览](docs/images/overview-light.png)

---

## 中文

### 能做什么

- **全网概览**：路由器状态、**网络健康指数**（逐项扣分和改进建议）、在线终端、**DHCP 地址池**、每条 **WAN 线路**的状态和速率；流量构成饼图（应用大类 → 小类）；实时流量、历史流量、历史在线终端数；Top 应用与 Top 终端排行。
- **主机监控**：在线终端 / 全部终端 / DHCP 租约 / 命名管理四个标签。每台终端的类型（手机、电脑、电视、摄像头……自动识别）、IP、MAC、主机名、归属人、在线时长、连接数、当前速率、今日 / 本周 / 本月流量，可导出 CSV；可以按 MAC 或按 IP 给设备命名。详情页有应用排行与构成、按大类的趋势、访问过的域名、访问日志和上网时间线。
- **应用统计**：参照维盟分三级（应用大类 → 小类 → 应用，逐级“查看详情”下钻）。大类照维盟的 17 类，固定列出，每级显示上传 / 下载速度和数据及占比；应用构成用矩形树图一眼看两层。17 个大类、50 个小类、2900 多个应用（抖音、B 站、微信视频号、Steam、银行、券商、ToDesk、DeepSeek……），识别不出具体应用的流量按 CDN 归到云厂商。
- **流量流向**：实时连接、访问目标排行（可按主域名合并）、流向世界地图、代理分流（sing-box 各策略组 / 节点）。
- **家庭成员 / 员工**：把一个人的设备归到一起按人统计；**家庭**场景关注孩子上网健康（屏幕时间、游戏和短视频上限、熬夜、不良内容），**企业**场景关注效率与合规。场景在 系统设置 全局切换。
- **审计日志**：访问日志（可筛选、导出 CSV）；审计规则（应用、域名、时段、流量、大流量外发、私接路由、新设备）；**通知渠道 14 种**（Telegram、飞书、企业微信、钉钉、Bark、Email、Server酱、Pushplus、Discord、Slack、ntfy、Gotify、QQ Bot、Webhook）；日报 / 周报；操作日志。
- **管控命令**：按应用、时段生成 RouterOS 命令（封禁应用、定时断网、限速），附撤销命令。只生成命令，不修改路由器。
- **识别规则**：按域名 / IP 段 / 端口自定义；未识别域名 Top 一键归类；识别库版本与更新状态（含本地自学习库）。
- **系统设置**：接入与自检、外部数据源（sing-box / MosDNS / AdGuard Home / 社区共享库）、日志与留存、用户管理。中英双语，深浅色主题，手机可用。

![应用统计](docs/images/apps-light.png)

![流量流向](docs/images/flow-light.png)

### 工作原理

```
RouterOS ──IPFIX  udp/2055 ──▶ 流量采集：每条连接的终端、远端 IP、端口、字节数
RouterOS ──TZSP   udp/37008──▶ DNS 嗅探：远端 IP 是哪个域名解析出来的
                             ▶ SNI：每条 HTTPS / QUIC 连接握手里的目标域名
RouterOS ◀─REST 只读（可选）── 主机名、IP↔MAC、WAN 口速率、LAN 前缀
                    ↓
         域名 → 应用规则库 → 按 分钟 / 小时 / 天 汇总写入数据库
```

- 流量来自 `/ip traffic-flow`（IPFIX），统计的是真实字节数。
- 域名来源由准到粗：这条连接的 **SNI**（推荐，终端用加密 DNS 也有效）→ **DNS 嗅探** → 这台终端的 DNS/SNI 记录 → 全网 IP→域名 表；都查不到时依次按 IP 段（ASN）、端口兜底。
- **域名 → 应用规则库，四层叠加**：
  1. 公开库：内置手工规则库 + [v2fly](https://github.com/v2fly/domain-list-community)（约 2500 应用）+ [blackmatrix7](https://github.com/blackmatrix7/ios_rule_script)（自动登记上游新目录）+ Hagezi / UT1 分类列表 + 国内域名列表 / 官方 IP 段 / 国内 IP 段兜底；
  2. **本地自学习库**：本网络实测的「IP → 应用」与「域名 → 应用」长期记忆——DNS 缓存过期、DoH、裸 IP 流量都能按记忆归类，每小时自动重建；
  3. **社区共享库**：各部署实例把实测结论匿名汇总到项目自带的社区主站（至少 2 个不同网络的实例一致才发布），本地没有结论时兜底；
  4. 以上都没有时，才归到 HTTPS / 国内网络这类笼统分类。
- 终端用 MAC 区分，IP 变化不影响统计。

**已知局限**：只开 DNS 嗅探时，终端使用 DoH / DoT 的流量只能识别为 HTTPS / QUIC，开启 SNI 识别可以补上；启用了 ECH 的少数网站只能看到外层公共名字。

## 部署

两种方式任选。**方式一**最快：一条命令装好，用 SQLite 零配置起步，之后可以在网页里一键升级；**方式二**是传统 Docker Compose，适合已有 MySQL / NAS 的环境。

### 方式一：Linux 一键安装（二进制，无需 Docker）

```bash
curl -fsSL https://raw.githubusercontent.com/suyijun8182/ros-dpi/main/install.sh | sudo bash
```

脚本自动完成：下载最新版单文件二进制（含前端）→ 安装到 `/usr/local/bin/ros-dpi` → 创建 `/opt/ros-dpi` 数据目录（默认 SQLite，无需 MySQL）→ 注册并启动 systemd 服务。完成后浏览器打开 `http://<本机IP>:8080`。

- **升级不用登录服务器**：有新版本时 系统设置 → 版本更新 会出现提示，点「一键更新」自动下载、替换二进制并重启服务。
- 支持 x86_64 与 aarch64。想用 MySQL：设 `DATABASE_URL` 环境变量后 `systemctl restart ros-dpi`。
- 服务以 root 运行（一键自更新需要写 `/usr/local/bin` 与 systemctl 权限）。
- 常用变量（`/etc/systemd/system/ros-dpi.service`）：`HTTP_PORT`、`DATA_DIR`、`DATABASE_URL`。

### 方式二：Docker Compose

ROS-DPI 把统计数据存在 **MySQL**（5.7 / 8.x）。默认你已经有一个 MySQL；还没有的话见[自带 MySQL 的部署方式](#还没有-mysql)。

#### 1. 准备数据库

用 root 或其他管理员账号登录 MySQL，执行以下语句（把 `your-password` 换成你自己的密码）：

```sql
CREATE DATABASE rosdpi CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'rosdpi'@'%' IDENTIFIED BY 'your-password';
GRANT ALL PRIVILEGES ON rosdpi.* TO 'rosdpi'@'%';
FLUSH PRIVILEGES;
```

- 命令行：`mysql -h <MySQL地址> -u root -p`，输入 root 密码后粘贴上面的语句。MySQL 跑在容器里时，可以用 `docker exec -it <mysql容器名> mysql -u root -p`。
- 图形界面（phpMyAdmin、NAS 的 MariaDB 管理页、Navicat、DBeaver 等）：新建数据库 `rosdpi`（字符集 `utf8mb4`），再新建用户 `rosdpi`（主机 `%`），授予该库全部权限。
- 表不用手动建，ROS-DPI 会自动创建。

#### 2. 编写 `docker-compose.yml` 并启动

新建目录保存下面的内容（也可 `curl -O https://raw.githubusercontent.com/suyijun8182/ros-dpi/main/docker-compose.yml`），把 `LAN_CIDRS` 改成你的内网网段：

```yaml
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
      LAN_CIDRS: 192.168.88.0/24     # 「必改」内网网段，逗号分隔
      ADMIN_PASSWORD: ""             # 留空则首次打开网页时设置
      ROS_URL: ""                    # 可选：RouterOS 只读 API，如 http://192.168.88.1
      ROS_USER: ""
      ROS_PASSWORD: ""
      ROS_VERIFY_TLS: "false"
    volumes:
      - ./data:/app/data             # 保存数据库连接配置，务必保留这个卷
```

```bash
docker compose up -d
```

镜像同时发布在 Docker Hub（`suyijun8182/ros-dpi`）和 GHCR（`ghcr.io/suyijun8182/ros-dpi`），支持 amd64 / arm64，每次发版带版本标签。NAS（群晖 / 飞牛 / 威联通）在 Container Manager 里新建“项目”粘贴 compose 即可。

#### 还没有 MySQL？

用 [`docker-compose.with-mysql.yml`](docker-compose.with-mysql.yml)：同时启动一个 MySQL 8.4 容器，自动建好库和账号并写好连接配置，**不需要第 1 步，网页上也不会出现数据库设置**：

```bash
curl -o docker-compose.yml https://raw.githubusercontent.com/suyijun8182/ros-dpi/main/docker-compose.with-mysql.yml
cat > .env <<'EOF'
MYSQL_PASSWORD=改成强密码
MYSQL_ROOT_PASSWORD=改成另一个强密码
EOF
# 再把 compose 里的 LAN_CIDRS 改成你的内网网段，然后 docker compose up -d
```

### 首次使用

浏览器打开 `http://<主机IP>:8080`：

1. **连接数据库**（Docker 且未用内置 MySQL 时）：填写 MySQL 信息，可先“测试连接”；自动建表并把连接信息存到 `./data/db_config.json`。MySQL 在同机时填局域网 IP，**不能填 127.0.0.1**。
2. **设置管理员**密码后自动登录。

完成后到 **系统设置 → 接入与自检** 复制 RouterOS 命令并在路由器执行（见下节），约 1 分钟后概览页开始有数据。接着：选择场景（家庭 / 企业）、添加成员并把设备分给他们、配置通知渠道和审计规则；需要只读账号时在 用户管理 添加。

**常见问题**

| 现象 | 原因与处理 |
|---|---|
| 提示“连不上 MySQL” | 地址或端口不通，或填了 `127.0.0.1`；MySQL 需要允许远程连接（`bind-address`），防火墙放行 3306 |
| 提示“账号或密码错误” | 检查密码；账号主机要是 `%` |
| 重启后显示“正在连接数据库” | MySQL 未就绪，每 5 秒自动重试，无需重新填写 |
| 需要更换数据库 | 删除 `./data/db_config.json` 重启，重新出现向导 |
| 忘记管理员密码 | 其他管理员可在 用户管理 重置；都忘了时执行 `DELETE FROM rosdpi.users;` 后重新设置（统计数据不受影响） |

### RouterOS 配置

把 `192.168.88.10` 换成运行 ROS-DPI 的主机 IP（**系统设置 → 接入与自检** 里可直接复制）：

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

更多说明（SNI 开销、FastTrack、双 NAT、IPv6、排错）见 [docs/RouterOS配置.md](docs/RouterOS配置.md)。

### 旁路代理与内网 DNS（可选）

- **sing-box Clash API**：走代理的流量按“哪台终端、哪个域名、多少字节”直接记账；按规则集 / 策略组名识别；代理分流按策略组和节点统计。
- **MosDNS 审计 API**：知道每台终端查了哪个域名、解析出哪些 IP。
- **AdGuard Home（自有 DNS 服务器）**：双层 NAT（路由器下挂爱快等二级路由）时，下级客户端的 DNS 查询被上游代理，路由器侧看不到——填入下级网络真正使用的 AdGuard Home 地址和密码，从查询日志补全域名，下级终端的流量同样按域名识别。

地址每个人都不一样，都不填就不启用。

### 识别库、自学习与社区共享

识别规则**四层叠加**，识别规则 → 识别库 可看每层的规模和状态：

1. **公开库**（自动更新）：内置手工库 + v2fly（每天自检更新）+ blackmatrix7（每周，上游新目录自动登记：先下载、再由现有识别库投票定归属）+ Hagezi / UT1 分类列表 + ASN（iptoasn）+ 国内域名列表 / 官方 IP 段 / 国内 IP 段兜底。
2. **本地自学习库**：本网络实测的「IP → 应用」（IPv6 按 /64 前缀聚合）与「域名 → 应用」长期记忆，每小时从数据库重建；DNS 缓存过期、DoH、裸 IP 流量都能按记忆归类。每次历史重算自动纠正它。
3. **社区共享库**：项目自带社区主站，不依赖任何第三方存储。各实例每 30 分钟向主站心跳、每 6 小时上报一次匿名投票——只含远端 IP / 域名、应用 ID 和字节票数，不含本机终端、访问记录与自定义应用，私网地址剔除；主站按**来源网络**计票（IPv4 /24、IPv6 /56，只存加盐哈希），**至少 2 个不同网络的实例投给同一应用且票数领先**才发布，一个人伪造多个实例也只算一票；每个实例有主站发的令牌，别人无法冒充。社区库缓存在本地，主站暂时不可达时继续可用。各实例**不需要公网 IP**（都是主动连主站），但要能访问主站：主站目前只有 IPv6 地址，Linux 一键安装直接用主机网络即可；Docker 默认网桥没有 IPv6 出口，需按 `docker-compose.yml` 末尾的说明开启（Docker 27+）。系统设置 → 外部数据源 可看连接状态、社区库规模与全球已部署 / 在线 / 离线数量；开关默认打开，关闭后不再上报也不再使用社区库。自建私有社区：一台实例设 `SHARE_HUB=true`，其它实例把 `SHARE_HUB_URL` 指向它（主站要能被各实例访问，建议 HTTPS）。
4. 以上都没有时，才归到 HTTPS / 国内网络这类笼统分类。

识别库有变化或过了零点，自动把今天以前的历史流量按新规则重算（只升级不降级）；识别规则页也可手动执行。世界地图使用 [Natural Earth](https://www.naturalearthdata.com/)（公有领域）简化数据。

### 环境变量

| 变量 | 默认值 | 说明 |
|---|---|---|
| `DATABASE_URL` | 空 | 留空则用网页安装向导（二进制部署默认 SQLite）；格式 `mysql+pymysql://user:pass@host:3306/rosdpi?charset=utf8mb4` |
| `LAN_CIDRS` | 私网三段 + `fd00::/8` | 内网网段，逗号分隔，界面里也能改 |
| `ADMIN_PASSWORD` | 空 | 首次启动创建 `admin` 用的密码；留空则在登录页设置 |
| `ROS_URL` / `ROS_USER` / `ROS_PASSWORD` | 空 | RouterOS REST 地址与只读账号 |
| `ROS_VERIFY_TLS` | `false` | 是否校验 ROS 证书 |
| `ROS_POLL_SECONDS` / `ROS_RATE_SECONDS` | 30 / 5 | RouterOS 完整轮询间隔 / WAN 口速率采样间隔 |
| `SINGBOX_URL` / `SINGBOX_SECRET` / `PROXY_IPS` | 空 | 旁路代理 sing-box 的 Clash API（也可在网页填写，网页优先） |
| `MOSDNS_URL` | 空 | MosDNS 审计 API 地址 |
| `ADGUARD_URL` / `ADGUARD_USERNAME` / `ADGUARD_PASSWORD` | 空 | 自有 DNS 服务器 AdGuard Home 的查询日志（双层 NAT 场景） |
| `SHARE_HUB_URL` | `https://rosdpi.suyijun.top:8443` | 社区主站地址（内置，一般不用改）；自建私有社区时改成自己的主站 |
| `SHARE_HUB` | `false` | 本实例作为社区主站（只有主站部署设为 `true`） |
| `SHARE_VERIFY_TLS` | `true` | 校验主站证书；私有社区用自签证书时才设 `false` |
| `FAKEIP_CIDRS` | `198.18.0.0/15,fc00::/18` | FakeIP 地址段 |
| `ASN_DB` / `CHINA_DB` / `IPLIST_DB` / `BM7_DB` / `HAGEZI_DB` / `UT1_DB` / `OUI_DB` | `true` | 各识别库自动下载开关；没有外网时设 `false` |
| `WAN_INTERFACE` | 自动 | WAN 接口名，默认按默认路由识别 |
| `TZ` | `Asia/Shanghai` | 统计用时区，每周从周一开始 |
| `HTTP_PORT` / `IPFIX_PORT` / `TZSP_PORT` | 8080 / 2055 / 37008 | 端口 |
| `RETENTION_*_DAYS` | 2 / 45 / 730 / 31 / 30 / 180 | 分钟 / 小时 / 每日 / 域名明细 / 访问日志 / 审计事件的保留天数（界面可改，网页优先） |
| `SECRET_KEY` | 自动生成 | 登录令牌签名密钥 |
| `DATA_DIR` | `./data` | 数据目录（数据库连接配置、识别库文件）；Docker 里对应 `/app/data` |

### 开发

```bash
# 后端
cd backend && python -m venv .venv && .venv/bin/pip install -r requirements.txt pytest
DATABASE_URL=sqlite:///./dev.db .venv/bin/uvicorn app.main:app --port 8080
.venv/bin/python -m pytest

# 前端
cd frontend && npm install && npm run dev   # http://localhost:5173，/api 代理到 8080

# Linux 单文件二进制（debug18）
cd frontend && npm run build
pip install -r backend/requirements.txt pyinstaller
pyinstaller ros-dpi.spec                    # 产物 dist/ros-dpi

# 灌入模拟数据
backend/.venv/bin/python scripts/simulate.py --minutes 5
```

应用规则库：

- [backend/app/classify/apps.yaml](backend/app/classify/apps.yaml)：手工维护，优先级高，欢迎 PR 补充。
- [backend/app/classify/apps_v2fly.yaml](backend/app/classify/apps_v2fly.yaml)：由 `python scripts/import_v2fly.py` 从 v2fly/domain-list-community 生成，不要手工修改；更新时重新运行脚本即可。

---

## English

**ROS-DPI** shows per-device and per-person traffic and per-application usage (today / yesterday / this week / this month) for networks behind a MikroTik RouterOS router, in the spirit of Panabit-style DPI dashboards, plus Sangfor-AC-style access logging and alerting. It has a home scenario (children's online health) and a business scenario (productivity and compliance).

- **Overview**: router status, a network health score with fixes, DHCP pool usage, WAN line status, online-host history, live rate, a traffic-mix pie (app group → category), and top apps and hosts.
- **Hosts**: every device with its detected type (phone, computer, TV, camera…), IP, MAC, hostname, owner, online state, live rate and daily / weekly / monthly totals. Name devices by MAC or by IP. Each device has an app breakdown, visited domains, an access log and a daily timeline.
- **Applications**: a three-level drill-down (app group → category → app) with fixed groups and categories, upload/download rates and totals with shares at each level, and a treemap of the mix. Groups follow WayOS's 17 DPI classes. It covers 17 groups, 50 categories and 2900+ apps, with a CDN fallback for unidentified traffic.
- **Flows**: live connections (sing-box connections show their policy group and outbound node), top destinations with a flow map from your location to each country, and proxy routing per sing-box policy group and node.
- **Family members / Employees**: pick the Home or Business scenario under **Settings → Scenario & network**; group each person's devices and see their traffic, online time, top apps and behaviour tags for the last 7 days.
- **Audit**: access log (CSV export), audit rules (app, domain, time window, traffic, large upload, rogue router, new device) with 14 push-notification channels, daily / weekly reports, operation log, TTL-based shared-access check, and a RouterOS control-command generator.
- **Self-learning & community library**: mappings observed on YOUR network (IP → app, domain → app) are kept as long-term memory and classify traffic even after DNS caches expire, with DoH clients, or for bare-IP flows; deployments share anonymous votes through the built-in community hub (no third-party storage); a mapping is published only when instances on at least two different networks agree, and the hub shows global deployed / online / offline counts. Instances need no public IP — they only connect out to the hub.
- **Self-update** (Linux binary install): a one-line installer sets up a systemd service with SQLite out of the box; new versions are detected automatically and applied with one click from the UI — no SSH needed.
- Chinese and English UI, light and dark themes, works on phones.

**How it works.** RouterOS exports IPFIX (`/ip traffic-flow`) for byte counts, and mirrors DNS answers plus the first packets of each HTTPS/QUIC connection via `sniff-tzsp`. The TLS / QUIC handshake carries the target domain (SNI) per connection; DNS answers map remote IPs back to the domain the client looked up. A four-layer rule library maps domains and IPs to apps (public libraries, self-learned local memory, community-shared votes, then generic fallbacks). An optional read-only REST user provides hostnames, IP-to-MAC, WAN rate and LAN prefixes. Data is aggregated per minute, hour and day.

**Deploy (Linux one-line, no Docker).**

```bash
curl -fsSL https://raw.githubusercontent.com/suyijun8182/ros-dpi/main/install.sh | sudo bash
```

Downloads the latest single-file binary, installs a systemd service on port 8080 with SQLite out of the box, and starts it. Upgrades are one click under **Settings → Version update**.

**Deploy (Docker).** Create a MySQL database and user:

```sql
CREATE DATABASE rosdpi CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'rosdpi'@'%' IDENTIFIED BY 'your-password';
GRANT ALL PRIVILEGES ON rosdpi.* TO 'rosdpi'@'%';
FLUSH PRIVILEGES;
```

Save the `docker-compose.yml` shown above (or `curl -O https://raw.githubusercontent.com/suyijun8182/ros-dpi/main/docker-compose.yml`), set `LAN_CIDRS`, and run `docker compose up -d`. Images: `suyijun8182/ros-dpi` on Docker Hub and `ghcr.io/suyijun8182/ros-dpi`, amd64/arm64, tagged per release.

No MySQL yet? Use [`docker-compose.with-mysql.yml`](docker-compose.with-mysql.yml): it starts MySQL 8.4 alongside and is pre-configured, so the database step is skipped. Rename it to `docker-compose.yml`, create a `.env` next to it with `MYSQL_PASSWORD` and `MYSQL_ROOT_PASSWORD`, set `LAN_CIDRS`, and run `docker compose up -d`.

**First run.** Open `http://<host>:8080`. A two-step setup wizard asks for (1) the MySQL host, port, user, password and database, with a connection test, and (2) the admin password. Tables are created automatically and the connection is saved to `./data/db_config.json`. If MySQL runs on the same machine, use its LAN IP, not `127.0.0.1`. To change databases later, delete that file and restart. RouterOS commands are listed above and in **Settings → Setup & check**. Then choose the scenario (Home / Business) under **Settings → Scenario & network**, add people and assign their devices, and set up notification channels under **Audit → Notifications**.

**Limitations.** With DNS sniffing alone, clients using DoH/DoT show up as generic HTTPS/QUIC; SNI covers them. Sites using ECH only expose their outer public name. A LAN DNS server (AdGuard Home, Pi-hole…) works fine as long as its upstream is plain DNS on udp/53: its upstream answers pass through the router and are sniffed by the `forward` rule.

## License

[MIT](LICENSE)

`backend/app/classify/apps_v2fly.yaml` is generated from [v2fly/domain-list-community](https://github.com/v2fly/domain-list-community) (MIT License, Copyright (c) 2019-present V2Fly Community).

These data sources are **not** included in this repository or the Docker image; the container downloads them at runtime into its data directory, and each keeps its own license / 以下数据不在仓库和镜像里，由容器运行时下载，各自沿用原许可证：

- [blackmatrix7/ios_rule_script](https://github.com/blackmatrix7/ios_rule_script) — GPL-2.0 (`BM7_DB`). `backend/app/classify/bm7_map.yaml` only maps its directory names to ROS-DPI apps.
- [Hagezi DNS blocklists](https://github.com/hagezi/dns-blocklists) — GPL-3.0 (`HAGEZI_DB`).
- [UT1 blacklists](https://dsi.ut-capitole.fr/blacklists/), Université Toulouse Capitole, via the [olbat/ut1-blacklists](https://github.com/olbat/ut1-blacklists) mirror — CC BY-SA 4.0 (`UT1_DB`).
- [dnsmasq-china-list](https://github.com/felixonmars/dnsmasq-china-list) — WTFPL; [chnroutes2](https://github.com/misakaio/chnroutes2) — CC BY-SA 4.0; [iptoasn](https://iptoasn.com) — PDDL; IEEE OUI; official Google / Cloudflare / AWS / GitHub IP range feeds.
