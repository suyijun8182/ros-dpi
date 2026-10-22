# ROS-DPI

**RouterOS 终端流量与应用统计面板**：像 Panabit / 碧海威那样，按 今日 / 本周 / 本月 统计 RouterOS 下每台终端用了多少流量、用在了哪些应用上。

[中文](#中文) · [English](#english)

![全网概览](docs/images/overview-light.png)

---

## 中文

### 能做什么

- **全网概览**：今日 / 本周 / 本月流量，此刻的上下行速率，流量构成环图（应用大类 → 小类），按应用大类堆叠的流量趋势，Top 应用与 Top 终端排行。
- **主机监控**：所有终端的 IP、MAC、主机名、在线状态、当前速率、今日 / 本周 / 本月流量，可以按 MAC 或按 IP 给设备命名（也能提前给还没上线的设备命名）；详情页可看该终端的应用排行、应用构成、按大类的趋势和访问过的域名。
- **应用统计**：参照 Panabit 分三级（应用大类 → 小类 → 应用）：10 个大类、41 个小类、270 多个内置应用（抖音、B 站、微信视频号、Steam、银行、券商、ToDesk、DeepSeek……）。识别不出具体应用的流量，会按 CDN 的 CNAME 归到阿里云 / 腾讯云 / Akamai 等厂商。可以查看每个应用被哪些终端使用。
- **流量流向**：桑基图展示 终端 → 应用大类 → 应用 的流向。
- **识别规则**：按域名后缀、IP 段、端口自定义识别规则；列出“未识别域名 Top”，一键归类。
- 中英双语，深浅色主题，手机可用。

![应用统计](docs/images/apps-light.png)

![流量流向](docs/images/flow-light.png)

### 工作原理

RouterOS 本身没有 DPI，ROS-DPI 用两路数据拼出应用级统计：

```
RouterOS ──IPFIX  udp/2055 ──▶ 流量采集：每条连接的终端、远端 IP、端口、字节数
RouterOS ──TZSP   udp/37008──▶ DNS 嗅探：远端 IP 是哪个域名解析出来的
RouterOS ◀─REST 只读（可选）── 主机名、IP↔MAC、WAN 口速率、LAN 前缀
                    ↓
         域名 → 应用规则库 → 按 分钟 / 小时 / 天 汇总写入 MySQL
```

- 流量来自 `/ip traffic-flow`（IPFIX），统计的是真实字节数。
- 应用识别靠 DNS：终端访问 `v26.douyinvod.com` 时，路由器把 DNS 应答镜像一份过来，之后发往该 IP 的流量就归到“抖音”。查不到域名时，依次按 IP 段、端口兜底（HTTPS / QUIC 等）。
- 终端用 MAC 区分（来自 ROS 的 ARP / DHCP，或流记录中的源 MAC），IP 变化不影响统计。

**已知局限**：终端使用 DoH / DoT 加密 DNS 时，这部分流量只能识别为 HTTPS / QUIC。可以在终端或路由器上禁用加密 DNS 来提高识别率。

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

# 3. 只读 API 账号（可选：主机名、WAN 速率）
/user group add name=rosdpi policy=read,rest-api,api,!write,!policy,!sensitive
/user add name=rosdpi group=rosdpi password=<强密码> address=192.168.88.10
```

更多说明（FastTrack、双 NAT、IPv6、排错）见 [docs/RouterOS配置.md](docs/RouterOS配置.md)。

### 环境变量

| 变量 | 默认值 | 说明 |
|---|---|---|
| `DATABASE_URL` | 空 | 留空则用网页安装向导；设置后跳过向导，格式 `mysql+pymysql://user:pass@host:3306/rosdpi?charset=utf8mb4` |
| `LAN_CIDRS` | 私网三段 + `fd00::/8` | 内网网段，逗号分隔，界面里也能改 |
| `ADMIN_PASSWORD` | 空 | 首次启动创建 `admin` 用的密码；留空则在登录页设置 |
| `ROS_URL` / `ROS_USER` / `ROS_PASSWORD` | 空 | RouterOS REST 地址与只读账号，如 `https://192.168.88.1` |
| `ROS_VERIFY_TLS` | `false` | 是否校验 ROS 证书 |
| `WAN_INTERFACE` | 自动 | WAN 接口名，默认按默认路由识别 |
| `TZ` | `Asia/Shanghai` | 统计用时区，每周从周一开始 |
| `HTTP_PORT` / `IPFIX_PORT` / `TZSP_PORT` | 8080 / 2055 / 37008 | 端口 |
| `RETENTION_*_DAYS` | 2 / 45 / 730 / 31 | 分钟 / 小时 / 每日 / 域名明细的保留天数 |
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

应用规则库在 [backend/app/classify/apps.yaml](backend/app/classify/apps.yaml)，欢迎 PR 补充。

---

## English

**ROS-DPI** shows per-device traffic and per-application usage (today / this week / this month) for networks behind a MikroTik RouterOS router, in the spirit of Panabit-style DPI dashboards.

- **Overview**: totals, live rate, a two-ring traffic-mix donut (app group → category), trends stacked by app group, ranked top apps and hosts.
- **Hosts**: every device with IP, MAC, hostname, online state, live rate and daily / weekly / monthly totals; name devices by MAC or by IP (even before they appear); per-host app breakdown and visited domains.
- **Applications**: a Panabit-style three-level library: 10 app groups, 41 categories, 270+ built-in apps. Traffic that can't be tied to an app is attributed to its CDN (Alibaba Cloud, Tencent Cloud, Akamai, Cloudflare…) via CNAME.
- **Flows**: a Sankey diagram from hosts through app groups to apps.
- **Rules**: custom domain / CIDR / port rules, and a list of top unidentified domains to classify.
- Chinese and English UI, light and dark themes, works on phones.

**How it works.** RouterOS exports IPFIX (`/ip traffic-flow`) for byte counts, and mirrors DNS answers via `sniff-tzsp` so each remote IP can be mapped back to the domain the client looked up. A rule library maps domains to apps. An optional read-only REST user provides hostnames, IP-to-MAC, WAN rate and LAN prefixes. Data is aggregated per minute, hour and day into MySQL.

**Limitations.** Clients using DoH/DoT show up as generic HTTPS/QUIC. A LAN DNS server (AdGuard Home, Pi-hole…) works fine as long as its upstream is plain DNS on udp/53: its upstream answers pass through the router and are sniffed by the `forward` rule.

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
