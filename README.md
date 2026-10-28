# ROS-DPI

**给 MikroTik RouterOS 用的终端流量、应用识别与上网审计面板。**

不换路由器、不做旁路串接：RouterOS 把流量统计（IPFIX）和握手包镜像（TZSP）发给 ROS-DPI，它算出**每台设备、每个人用了多少流量、用在了哪些应用上**，并按规则记录访问、推送告警。界面参照维盟 / Panabit，审计参照深信服 AC。

[中文](#中文) · [English](#english) · [更新日志](CHANGELOG.md) · [RouterOS 配置详解](docs/RouterOS配置.md)

![全网概览](docs/images/overview-light.png)

---

## 中文

### 功能

| 页面 | 能看到 / 能做什么 |
|---|---|
| **全网概览** | 路由器状态、网络健康指数（逐项扣分和改进建议）、在线终端、DHCP 地址池、每条 WAN 线路的状态和速率；流量构成饼图；实时 / 历史流量；Top 应用与 Top 终端 |
| **主机监控** | 每台设备的类型（手机、电脑、电视、摄像头……自动识别）、IP、MAC、主机名、归属人、在线时长、实时速率、今日 / 本周 / 本月流量；按 MAC 或 IP 命名；单台设备的应用构成、访问过的域名、访问日志、上网时间线；导出 CSV |
| **应用统计** | 三级下钻：应用大类 → 小类 → 应用。大类照维盟的 17 类，共 50 个小类、约 2970 个应用（抖音、B 站、微信、Steam、银行、券商、ToDesk、DeepSeek……） |
| **流量流向** | 实时连接、访问目标排行、流向世界地图、代理分流（sing-box 的策略组 / 出口节点） |
| **家庭成员 / 员工** | 把一个人的设备归到一起按人统计。**家庭**场景看孩子上网健康（屏幕时间、游戏和短视频、熬夜），**企业**场景看效率与合规 |
| **审计日志** | 访问日志；审计规则（应用、域名、时段、流量阈值、大流量外发、私接路由、新设备）；14 种通知渠道（Telegram、飞书、企业微信、钉钉、Bark、邮件、Server酱、Pushplus、Discord、Slack、ntfy、Gotify、QQ、Webhook）；日报 / 周报；操作日志 |
| **管控命令** | 按应用、时段生成 RouterOS 命令（封禁应用、定时断网、限速）并附撤销命令。**只生成，不会改路由器** |
| **识别规则** | 按域名 / IP 段 / 端口自定义规则；未识别域名 Top 一键归类；各识别库的规模与更新状态 |

中英双语，浅色 / 深色主题，手机上也能用。

![应用统计](docs/images/apps-light.png)

![流量流向](docs/images/flow-light.png)

![家庭成员](docs/images/people-light.png)

### 三步上手

1. **部署 ROS-DPI**：Linux 一条命令，或 Docker Compose（见[部署](#部署)）。
2. **配置 RouterOS**：在 **系统设置 → 接入与自检** 复制命令到路由器执行（见[RouterOS 配置](#routeros-配置)）。
3. **打开网页**：约 1 分钟后概览页开始有数据。再选场景（家庭 / 企业）、把设备分给成员、配好通知渠道和审计规则。

### 部署

| | 方式一：Linux 一键安装 | 方式二：Docker Compose |
|---|---|---|
| 适合 | 一台 Linux 小主机 / 虚拟机 | 已有 Docker、NAS 或 MySQL |
| 数据库 | 默认 SQLite，零配置；可改 MySQL | MySQL 5.7 / 8.x（可一起启动） |
| 升级 | 网页上点「一键更新」 | `docker compose pull && docker compose up -d` |
| 架构 | x86_64、aarch64 | amd64、arm64 |

#### 方式一：Linux 一键安装

```bash
curl -fsSL https://raw.githubusercontent.com/suyijun8182/ros-dpi/main/install.sh | sudo bash
```

脚本会下载最新版单文件二进制（含前端）并校验 SHA256，创建专用账号 `ros-dpi`，注册并启动 systemd 服务。装完浏览器打开 `http://<本机IP>:8080`。

| 位置 | 用途 |
|---|---|
| `/opt/ros-dpi/bin/ros-dpi` | 程序（`/usr/local/bin/ros-dpi` 是指向它的软链接） |
| `/opt/ros-dpi/data/` | 数据：SQLite 库、识别库文件 |
| `/etc/ros-dpi.env` | 你的配置（`DATABASE_URL`、`ADMIN_PASSWORD`、`LAN_CIDRS`……），重装 / 升级都不会覆盖 |

- 改配置后执行 `sudo systemctl restart ros-dpi`；看日志用 `journalctl -u ros-dpi -f`。
- 安装时可以用 `ROS_DPI_PORT`（默认 8080）和 `ROS_DPI_DIR`（默认 `/opt/ros-dpi`）指定端口和目录，例如 `curl … | sudo ROS_DPI_PORT=9000 bash`。
- 服务以 `ros-dpi` 账号运行，不是 root，只能写 `bin/` 和 `data/`。**0.6.23 及以前装的是 root 服务**，重新执行一次安装命令即可迁移，数据和配置原样保留。

#### 方式二：Docker Compose

**还没有 MySQL**：用 [`docker-compose.with-mysql.yml`](docker-compose.with-mysql.yml)，会一起启动 MySQL 8.4 并自动建库、写好连接，网页上不会出现数据库设置。

```bash
mkdir ros-dpi && cd ros-dpi
curl -o docker-compose.yml https://raw.githubusercontent.com/suyijun8182/ros-dpi/main/docker-compose.with-mysql.yml
cat > .env <<'EOF'
MYSQL_PASSWORD=改成强密码
MYSQL_ROOT_PASSWORD=改成另一个强密码
EOF
# 把 docker-compose.yml 里的 LAN_CIDRS 改成你的内网网段
docker compose up -d
```

**已有 MySQL**：先建库和账号（命令行用 `mysql -u root -p`，也可以在 phpMyAdmin、Navicat、NAS 的数据库管理页里操作；表会自动创建）：

```sql
CREATE DATABASE rosdpi CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'rosdpi'@'%' IDENTIFIED BY 'your-password';
GRANT ALL PRIVILEGES ON rosdpi.* TO 'rosdpi'@'%';
FLUSH PRIVILEGES;
```

再保存下面的 `docker-compose.yml`（或 `curl -O https://raw.githubusercontent.com/suyijun8182/ros-dpi/main/docker-compose.yml`），改好 `LAN_CIDRS` 后 `docker compose up -d`。首次打开网页时在安装向导里填 MySQL 信息。

```yaml
services:
  ros-dpi:
    image: suyijun8182/ros-dpi:latest        # 也可用 ghcr.io/suyijun8182/ros-dpi:latest
    container_name: ros-dpi
    restart: unless-stopped
    ports:
      - "8080:8080/tcp"     # Web 界面
      - "2055:2055/udp"     # IPFIX：RouterOS Traffic Flow 发到这里
      - "37008:37008/udp"   # TZSP：RouterOS 镜像的 DNS 应答和 HTTPS / QUIC 握手包发到这里
    environment:
      TZ: Asia/Shanghai
      LAN_CIDRS: 192.168.88.0/24     # 必改：内网网段，逗号分隔
      ADMIN_PASSWORD: ""             # 留空则首次打开网页时设置
    volumes:
      - ./data:/app/data             # 保存数据库连接配置和识别库，务必保留
```

镜像发布在 Docker Hub（`suyijun8182/ros-dpi`）和 GHCR（`ghcr.io/suyijun8182/ros-dpi`），每次发版都有版本号标签。群晖 / 飞牛 / 威联通在 Container Manager 里新建“项目”，粘贴 compose 即可。

### 首次使用

打开 `http://<主机IP>:8080`：

1. **连接数据库**（只有 Docker 且没用自带 MySQL 时才有这一步）：填 MySQL 信息，可以先测试连接。MySQL 和 ROS-DPI 在同一台机器上时填局域网 IP，**不能填 127.0.0.1**。
2. **设置管理员密码**，设置后自动登录。
3. 到 **系统设置 → 接入与自检** 复制 RouterOS 命令去路由器执行。自检会检查规则是否齐全、端口是否写错、FastTrack 是否挡住了握手包。

只读账号（只能看、不能改）在 **系统设置 → 用户管理** 添加。

| 现象 | 处理 |
|---|---|
| 连不上 MySQL | 地址 / 端口不通，或填了 `127.0.0.1`；MySQL 要允许远程连接（`bind-address`），防火墙放行 3306 |
| 账号或密码错误 | 检查密码；账号的主机要是 `%` |
| 重启后显示“正在连接数据库” | MySQL 还没就绪，会自动重试，不用重填 |
| 要换数据库 | 删掉 `data/db_config.json` 后重启，重新出现向导 |
| 忘记管理员密码 | 让其他管理员在 用户管理 里重置；都忘了就执行 `DELETE FROM rosdpi.users;` 后重新设置（统计数据不受影响） |
| 概览一直没数据 | 看 接入与自检 的结果；确认路由器能访问本机的 udp/2055、udp/37008 |

### RouterOS 配置

把 `192.168.88.10` 换成 ROS-DPI 主机的 IP。**系统设置 → 接入与自检** 里有替换好地址的版本，可以直接复制。

```routeros
# 1. 流量统计（IPFIX）
/ip traffic-flow set enabled=yes interfaces=all active-flow-timeout=1m inactive-flow-timeout=15s
/ip traffic-flow target add dst-address=192.168.88.10 port=2055 version=ipfix

# 2. DNS 嗅探：远端 IP 是哪个域名解析出来的
/ip firewall mangle add chain=output protocol=udp src-port=53 action=sniff-tzsp sniff-target=192.168.88.10 sniff-target-port=37008 comment=ROSDPI-DNS
/ip firewall mangle add chain=forward protocol=udp src-port=53 action=sniff-tzsp sniff-target=192.168.88.10 sniff-target-port=37008 comment=ROSDPI-DNS

# 3. SNI 识别（推荐）：只镜像每条 HTTPS / QUIC 连接开头的握手，终端用加密 DNS 也能识别
/ip firewall mangle add chain=forward protocol=tcp dst-port=443 connection-bytes=0-4000 action=sniff-tzsp sniff-target=192.168.88.10 sniff-target-port=37008 comment=ROSDPI-SNI
/ip firewall mangle add chain=forward protocol=udp dst-port=443 connection-bytes=0-4000 action=sniff-tzsp sniff-target=192.168.88.10 sniff-target-port=37008 comment=ROSDPI-SNI

# 4. 开了 IPv6 时再加一份（国内宽带大多有 IPv6，视频、下载优先走 IPv6）
/ipv6 firewall mangle add chain=output protocol=udp src-port=53 action=sniff-tzsp sniff-target=192.168.88.10 sniff-target-port=37008 comment=ROSDPI-DNS
/ipv6 firewall mangle add chain=forward protocol=udp src-port=53 action=sniff-tzsp sniff-target=192.168.88.10 sniff-target-port=37008 comment=ROSDPI-DNS
/ipv6 firewall mangle add chain=forward protocol=tcp dst-port=443 connection-bytes=0-4000 action=sniff-tzsp sniff-target=192.168.88.10 sniff-target-port=37008 comment=ROSDPI-SNI
/ipv6 firewall mangle add chain=forward protocol=udp dst-port=443 connection-bytes=0-4000 action=sniff-tzsp sniff-target=192.168.88.10 sniff-target-port=37008 comment=ROSDPI-SNI

# 5. 开了 FastTrack 时：每条连接的前 10KB 不走 FastTrack，否则握手包镜像不到
/ip firewall filter set [find action=fasttrack-connection] connection-bytes=10000-0
/ipv6 firewall filter set [find action=fasttrack-connection] connection-bytes=10000-0

# 6. 只读 API 账号（可选）：主机名、IP↔MAC、WAN 口速率、DHCP 地址池
/user group add name=rosdpi policy=read,rest-api,api,!write,!policy,!sensitive
/user add name=rosdpi group=rosdpi password=<强密码> address=192.168.88.10
```

第 6 步的地址和账号填在 **系统设置 → 接入与自检**，或者用环境变量 `ROS_URL` / `ROS_USER` / `ROS_PASSWORD`。SNI 的开销、双层 NAT、排错等见 [docs/RouterOS配置.md](docs/RouterOS配置.md)。

### 应用是怎么识别出来的

```
RouterOS ──IPFIX udp/2055 ──▶ 每条连接：哪台终端、远端 IP、端口、字节数
RouterOS ──TZSP  udp/37008──▶ DNS 应答：远端 IP ← 哪个域名
                             HTTPS / QUIC 握手：这条连接的目标域名（SNI）
RouterOS ◀── REST 只读（可选）── 主机名、IP↔MAC、WAN 速率
                       ↓
           域名 / IP → 应用 → 按分钟、小时、天汇总入库
```

**先确定域名**，由准到粗：这条连接的 SNI → DNS 嗅探 → 这台终端最近的 DNS / SNI 记录 → 全网 IP→域名 表。终端按 MAC 区分，IP 变了不影响统计。

**再把域名 / IP 对应到应用**，四层依次查：

1. **公开识别库**（自动更新）：内置手工库、[v2fly](https://github.com/v2fly/domain-list-community)、[blackmatrix7](https://github.com/blackmatrix7/ios_rule_script)、Hagezi / UT1 分类列表、ASN、国内域名列表、云厂商官方 IP 段。上游有新目录时，先下载再用现有识别库投票决定它属于哪个应用，不用人工整理。
2. **本地自学习库**：你的网络里实测到的「IP → 应用」「域名 → 应用」会长期记住，DNS 缓存过期、用 DoH 的终端、直接连 IP 的流量都能按记忆归类，每小时重建一次。
3. **社区共享库**：各个部署实例匿名汇总的识别结论，本地查不到时兜底（见下节）。
4. 都查不到时：域名像视频站（`m3u8 / vod / play`……）的归「其他视频网站」；**完全没有域名**的国内流量按远端 ASN 推断，家宽 / 骨干网归「P2P/PCDN 加速」，IDC / 云厂商归「国内云/IDC」（推断，不对应具体 App）；再不行才是「HTTPS」「国内网络」这类笼统分类。

「其他」占比偏高时，看 **识别规则 → 未匹配流量诊断**：没有域名的流量按远端类型、端口、终端拆开显示。一台终端占了大部分流量多半是下挂了路由器（双重 NAT），它后面的设备 ROS 看不到，接入自检会提示。自己的 NAS、VPS 域名可以在识别规则里归到「常用协议 → 自建服务」。

识别库更新后，或者每天过了零点，会自动把以前的历史流量按新规则重算一遍（只会从笼统改成具体，不会反过来）；**识别规则** 页也可以手动重算。

**局限**：没开 SNI、只开 DNS 嗅探时，用 DoH / DoT 的终端只能识别成 HTTPS / QUIC；启用了 ECH 的少数网站只能看到外层的公共域名。

### 社区共享库

每个部署实例学到的东西不一样，汇总起来识别会更准。项目自带一个社区主站，不依赖第三方存储。

- **上报什么**：远端 IP / 域名、应用 ID、票数。**不含**本机终端、访问记录、自定义应用；私网地址会被剔除。
- **怎么防作假**：主站按**来源网络**计票（IPv4 /24、IPv6 /56，只存加盐哈希），至少 2 个不同网络的实例投给同一个应用、而且票数领先才会发布；一个人开再多实例也只算一票。每个实例有主站发的令牌，别人冒充不了。
- **不需要公网 IP**：各实例都是主动连主站，能上外网就行。社区库缓存在本地，主站暂时连不上也照常用。
- **在哪里看、怎么关**：**系统设置 → 外部数据源 → 社区共享库**，能看到连接状态、社区库规模、全球已部署 / 在线 / 离线数量。默认打开，关掉后不再上报，也不再使用社区库。
- **自建私有社区**：[`deploy/hub/`](deploy/hub/) 有 VPS 部署模板（Docker + Caddy 自动 HTTPS；或已有 Lucky + MySQL 的版本），步骤见 [docs/社区主站部署.md](docs/社区主站部署.md)。各实例在上面的页面填写“社区主站地址”即可。

### 外部数据源（可选）

用了旁路代理或自建 DNS 时，可以把它们接进来补全识别。都在 **系统设置 → 外部数据源** 填写，不填就不启用。

| 来源 | 补上什么 |
|---|---|
| **sing-box**（Clash API） | 走代理的流量：哪台终端、哪个域名、多少字节，以及策略组和出口节点 |
| **MosDNS**（审计 API） | 每台终端查了哪个域名、解析出哪些 IP |
| **AdGuard Home** | 双层 NAT（RouterOS 下面还挂了一台路由器）时，下级终端的 DNS 查询路由器看不到，从 AdGuard Home 的查询日志补上 |

### 升级

- **Linux 一键安装**：**系统设置 → 版本更新** 出现新版本时点「一键更新」，程序会下载新版、校验 SHA256、替换后自动重启，旧版本留一份 `ros-dpi.bak`。也可以重新执行安装命令。
- **Docker**：`docker compose pull && docker compose up -d`。想固定版本，就把镜像标签从 `latest` 改成具体版本号（如 `0.6.24`）。

每个版本改了什么见 [CHANGELOG.md](CHANGELOG.md)。

### 接入 Home Assistant 等外部程序

在 **系统设置 → 用户管理 → API 令牌** 新建一个令牌（只读、不过期，删除后立即失效；原文只在创建时显示一次），请求时放在请求头里：

```
Authorization: Bearer rdp_xxxxxxxx
GET http://<ROS-DPI 地址>:8080/api/ha/summary?limit=30
```

`/api/ha/summary` 一次返回首页常用的数：今日 / 本周 / 本月流量、实时速率、在线终端数、识别率、健康指数、应用大类构成、Top 应用，以及按今日流量排序的前 `limit` 台终端（名称、IP、MAC、类型、实时速率、今日 / 本周 / 本月流量、今日前 3 个应用）。字节数单位是 bytes，速率是 bytes/s。令牌也能读其它只读接口（等同普通用户），但不能修改任何设置。

Home Assistant 里用 RESTful 传感器读取即可，例如：

```yaml
rest:
  - resource: http://192.168.88.10:8080/api/ha/summary
    headers:
      Authorization: !secret rosdpi_token     # secrets.yaml 里写 "Bearer rdp_..."
    scan_interval: 60
    sensor:
      - name: rosdpi_summary
        value_template: "{{ value_json.online }}"
        json_attributes: [totals, rate, hosts, groups, top_apps, identified, health]
```

### 安全建议

- 内网有不可信设备时，设 `COLLECTOR_ALLOWED=<路由器IP>`，采集端口只接收路由器发来的包，防止别人伪造流量或 DNS 记录。
- 不要把 8080 端口直接暴露到公网；需要外网访问时放在反向代理后面并启用 HTTPS。从公网打开安装向导时，需要填写启动日志里打印的安装码。
- RouterOS 账号只给只读权限（上面第 6 步的用户组）；管控页生成的命令要你自己检查后再执行。

### 环境变量

Linux 一键安装写在 `/etc/ros-dpi.env`，Docker 写在 compose 的 `environment`。标了“网页可改”的，网页上的设置优先。

**基础**

| 变量 | 默认值 | 说明 |
|---|---|---|
| `DATABASE_URL` | 空 | 留空则用网页安装向导（Linux 一键安装默认 SQLite）。MySQL 格式：`mysql+pymysql://user:pass@host:3306/rosdpi?charset=utf8mb4` |
| `LAN_CIDRS` | 私网三段 + `fd00::/8` | 内网网段，逗号分隔（网页可改） |
| `ADMIN_PASSWORD` | 空 | 首次启动时创建 `admin` 的密码；留空则在网页上设置 |
| `TZ` | `Asia/Shanghai` | 统计用的时区；每周从周一开始 |
| `HTTP_PORT` / `IPFIX_PORT` / `TZSP_PORT` | 8080 / 2055 / 37008 | 端口 |
| `DATA_DIR` | `./data` | 数据目录；Docker 里是 `/app/data` |
| `SECRET_KEY` | 自动生成 | 登录令牌的签名密钥 |

**RouterOS 与采集**

| 变量 | 默认值 | 说明 |
|---|---|---|
| `ROS_URL` / `ROS_USER` / `ROS_PASSWORD` | 空 | RouterOS REST 地址和只读账号（网页可改） |
| `ROS_VERIFY_TLS` | `false` | 是否校验 RouterOS 的证书 |
| `ROS_POLL_SECONDS` / `ROS_RATE_SECONDS` | 30 / 5 | 完整轮询间隔 / WAN 口速率采样间隔（秒） |
| `WAN_INTERFACE` | 自动 | WAN 接口名，默认按默认路由判断 |
| `COLLECTOR_ALLOWED` | 空 | 采集端口只收这些地址的包（一般填路由器 IP）；留空不限制 |

**外部数据源**（都可在网页填写）

| 变量 | 默认值 | 说明 |
|---|---|---|
| `SINGBOX_URL` / `SINGBOX_SECRET` | 空 | sing-box 的 Clash API 地址和密钥 |
| `PROXY_IPS` | 空 | 旁路代理自己的 IP；留空时取 `SINGBOX_URL` 里的地址 |
| `FAKEIP_CIDRS` | `198.18.0.0/15,fc00::/18` | FakeIP 地址段 |
| `MOSDNS_URL` | 空 | MosDNS 审计 API 地址 |
| `ADGUARD_URL` / `ADGUARD_USERNAME` / `ADGUARD_PASSWORD` | 空 | AdGuard Home 地址和账号 |

**识别库与社区**

| 变量 | 默认值 | 说明 |
|---|---|---|
| `ASN_DB` / `CHINA_DB` / `IPLIST_DB` / `BM7_DB` / `HAGEZI_DB` / `UT1_DB` / `OUI_DB` | `true` | 各识别库是否自动下载；机器上不了外网时设 `false` |
| `SHARE_ENABLED` | `true` | 社区共享库总开关（网页可改） |
| `SHARE_HUB_URL` | `https://rosdpi.vviip.dpdns.org:8443` | 社区主站地址，一般不用改（网页可改） |
| `SHARE_VERIFY_TLS` | `true` | 校验主站证书；私有社区用自签证书时才设 `false` |
| `SHARE_HUB` | `false` | 把本实例当作社区主站（只有主站部署才设 `true`） |
| `SHARE_TRUSTED_PROXIES` | 空 | 主站用：只信任这些反向代理传来的 `X-Forwarded-For`；留空 = 内网和本机地址 |

**数据保留**（网页可改）

| 变量 | 默认值（天） |
|---|---|
| `RETENTION_MINUTE_DAYS` / `RETENTION_HOUR_DAYS` / `RETENTION_DAY_DAYS` | 2 / 45 / 730（分钟、小时、每日汇总） |
| `RETENTION_DOMAIN_DAYS` / `RETENTION_LOG_DAYS` / `RETENTION_EVENT_DAYS` | 31 / 30 / 180（域名明细、访问日志、审计事件） |

### 开发

技术栈：后端 FastAPI + SQLAlchemy（MySQL / SQLite），前端 Vue 3 + Vite + ECharts。

```bash
# 后端
cd backend && python -m venv .venv && .venv/bin/pip install -r requirements.txt pytest
DATABASE_URL=sqlite:///./dev.db .venv/bin/uvicorn app.main:app --port 8080
.venv/bin/python -m pytest

# 前端：http://localhost:5173，/api 代理到 8080
cd frontend && npm install && npm run dev

# 灌一些模拟流量
backend/.venv/bin/python scripts/simulate.py --minutes 5

# 打包 Linux 单文件二进制（产物 dist/ros-dpi）
cd frontend && npm run build && cd ..
pip install -r backend/requirements.txt pyinstaller && pyinstaller ros-dpi.spec
```

补充应用规则：改 [backend/app/classify/apps.yaml](backend/app/classify/apps.yaml)（手工维护，优先级最高，欢迎 PR）。`apps_v2fly.yaml` 由 `scripts/import_v2fly.py` 生成，不要手改。

---

## English

**ROS-DPI** is a traffic, application and access-audit dashboard for networks behind a MikroTik RouterOS router. RouterOS exports flow records (IPFIX) and mirrors DNS answers and TLS/QUIC handshakes (TZSP); ROS-DPI turns them into per-device and per-person traffic by application, with access logs and alert rules. No inline box, no router replacement.

### Features

- **Overview**: router status, network health score with fixes, online hosts, DHCP pool, per-WAN status and rate, traffic mix, live and historical traffic, top apps and hosts.
- **Hosts**: device type detection (phone, PC, TV, camera…), IP / MAC / hostname / owner, online time, live rate, daily / weekly / monthly totals, per-device app mix, domains, access log and timeline; CSV export.
- **Applications**: three-level drill-down (group → category → app) — 17 groups, 50 categories, ~2,970 apps.
- **Flows**: live connections, top destinations, world flow map, proxy routing per sing-box policy group and outbound.
- **People**: group devices per person. *Home* scenario focuses on children's screen time and habits; *Business* on productivity and compliance.
- **Audit**: access log, rules (app, domain, time window, traffic threshold, large upload, rogue router, new device), 14 notification channels, daily / weekly reports, operation log.
- **Control commands**: generates RouterOS commands (block an app, scheduled cut-off, rate limit) with undo commands. It never changes the router by itself.
- Chinese and English UI, light and dark themes, mobile friendly.

### Quick start

**Linux (single binary, SQLite by default, one-click updates from the UI):**

```bash
curl -fsSL https://raw.githubusercontent.com/suyijun8182/ros-dpi/main/install.sh | sudo bash
```

It verifies the download's SHA256, creates a dedicated `ros-dpi` user and starts a systemd service on port 8080. The binary lives in `/opt/ros-dpi/bin`, data in `/opt/ros-dpi/data`, and your settings in `/etc/ros-dpi.env` (kept across reinstalls). Installs from 0.6.23 or earlier ran as root — re-run the command to migrate; data and settings are kept.

**Docker, with a bundled MySQL:**

```bash
curl -o docker-compose.yml https://raw.githubusercontent.com/suyijun8182/ros-dpi/main/docker-compose.with-mysql.yml
printf 'MYSQL_PASSWORD=change-me\nMYSQL_ROOT_PASSWORD=change-me-too\n' > .env
# set LAN_CIDRS in docker-compose.yml, then:
docker compose up -d
```

**Docker, with your own MySQL:** create the database and user with the SQL in the Chinese section, use [`docker-compose.yml`](docker-compose.yml), and enter the MySQL details in the setup wizard on first launch (use the host's LAN IP, not `127.0.0.1`). Images: `suyijun8182/ros-dpi` on Docker Hub and `ghcr.io/suyijun8182/ros-dpi`, amd64 / arm64, tagged per release.

Then open `http://<host>:8080`, set the admin password, and copy the RouterOS commands from **Settings → Setup & check** (also listed in the [RouterOS section](#routeros-配置) above and in [docs/RouterOS配置.md](docs/RouterOS配置.md)). The self-check there flags missing rules, wrong ports and FastTrack bypassing the sniffer.

### How apps are identified

The domain of each connection comes from its TLS/QUIC SNI, then sniffed DNS answers, then the host's recent lookups, then a network-wide IP→domain table. Domains and IPs map to apps through four layers: (1) public libraries, updated automatically — built-in rules, v2fly, blackmatrix7, Hagezi / UT1 categories, ASN, China domain lists and official cloud IP ranges; (2) a **local self-learning library** of mappings observed on your own network; (3) the **community library**; (4) fallbacks — video-like hostnames go to "Other video sites", traffic with no domain at all is inferred from the remote ASN (Chinese broadband → "P2P/PCDN", IDC/cloud → "China cloud/IDC"), and the rest is generic ("HTTPS", "China networks"). When the libraries change, past traffic is reclassified automatically. **Rules → Unmatched traffic** breaks down traffic with no domain by remote type, port and device, and the self-check warns when one device carries most of the traffic (a router behind RouterOS, i.e. double NAT).

With DNS sniffing alone, DoH/DoT clients show up as generic HTTPS/QUIC — enable the SNI rules to cover them. Sites using ECH only expose their outer public name.

### Community library

Instances share anonymous votes (remote IP / domain → app) through the built-in community hub — no hosts, no access logs and no private addresses are sent. A mapping is published only when instances on at least two different networks (IPv4 /24, IPv6 /56, stored as salted hashes) agree, so one person running many instances still counts once. Instances need no public IP. Toggle it and see its status under **Settings → External sources**; to run a private hub, see [`deploy/hub/`](deploy/hub/) and [docs/社区主站部署.md](docs/社区主站部署.md).

### Optional sources

sing-box (Clash API) adds per-host, per-domain byte counts for proxied traffic; MosDNS adds per-host DNS lookups; AdGuard Home fills in domains behind a second NAT. Configure them under **Settings → External sources**.

### Home Assistant and other programs

Create a read-only API token under **Settings → Users → API tokens** (it never expires and stops working when deleted; the token is shown only once). Send it as `Authorization: Bearer rdp_…`. `GET /api/ha/summary?limit=30` returns today / week / month totals, live rate, online hosts, identification rate, health score, app groups, top apps and the top hosts by today's traffic with their top three apps (bytes and bytes/s). See the Chinese section for a Home Assistant RESTful sensor example.

### Security notes

Set `COLLECTOR_ALLOWED=<router IP>` if untrusted devices share the LAN. Don't expose port 8080 to the internet directly — put it behind an HTTPS reverse proxy. Give RouterOS a read-only user only.

All environment variables are listed in the [Chinese section](#环境变量).

## License

[MIT](LICENSE)

`backend/app/classify/apps_v2fly.yaml` is generated from [v2fly/domain-list-community](https://github.com/v2fly/domain-list-community) (MIT License, Copyright (c) 2019-present V2Fly Community). World map data from [Natural Earth](https://www.naturalearthdata.com/) (public domain).

These data sources are **not** included in this repository or the Docker image; ROS-DPI downloads them at runtime into its data directory, and each keeps its own license / 以下数据不在仓库和镜像里，运行时下载，各自沿用原许可证：

- [blackmatrix7/ios_rule_script](https://github.com/blackmatrix7/ios_rule_script) — GPL-2.0 (`BM7_DB`). `backend/app/classify/bm7_map.yaml` only maps its directory names to ROS-DPI apps.
- [Hagezi DNS blocklists](https://github.com/hagezi/dns-blocklists) — GPL-3.0 (`HAGEZI_DB`).
- [UT1 blacklists](https://dsi.ut-capitole.fr/blacklists/), Université Toulouse Capitole, via the [olbat/ut1-blacklists](https://github.com/olbat/ut1-blacklists) mirror — CC BY-SA 4.0 (`UT1_DB`).
- [dnsmasq-china-list](https://github.com/felixonmars/dnsmasq-china-list) — WTFPL; [chnroutes2](https://github.com/misakaio/chnroutes2) — CC BY-SA 4.0; [iptoasn](https://iptoasn.com) — PDDL; IEEE OUI; official Google / Cloudflare / AWS / GitHub IP range feeds.
