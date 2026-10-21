# ROS-DPI

**RouterOS 终端流量与应用统计面板**：像 Panabit / 碧海威那样，按 今日 / 本周 / 本月 统计 RouterOS 下每台终端用了多少流量、用在了哪些应用上。

[中文](#中文) · [English](#english)

![全网概览](docs/images/overview-light.png)

---

## 中文

### 能做什么

- **全网概览**：今日 / 本周 / 本月流量，此刻的上下行速率，流量构成（按应用分类），Top 应用与 Top 终端，24 小时与 30 天趋势。
- **主机监控**：所有终端的 IP、MAC、主机名、在线状态、当前速率、今日 / 本周 / 本月流量，可以给设备起备注名；详情页可看该终端的应用排行、分类占比和访问过的域名。
- **应用统计**：100 多个内置应用（抖音、B 站、微信、Steam、Apple 更新、ChatGPT……）分 20 多个类别，可以查看每个应用被哪些终端使用。
- **流量流向**：桑基图展示 终端 → 应用分类 → 应用 的流向。
- **识别规则**：按域名后缀、IP 段、端口自定义识别规则；列出“未识别域名 Top”，一键归类。
- 中英双语，深浅色主题，手机可用。

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

**已知局限**：终端使用 DoH / DoT 加密 DNS，或者在路由器之外解析 DNS 时，这部分流量只能识别为 HTTPS / QUIC。可以在终端或路由器上禁用加密 DNS 来提高识别率。

### 部署

ROS-DPI 把统计数据存在 **MySQL**（5.7 / 8.x 均可）。默认你已经有一个 MySQL（NAS 自带的、单独跑的容器、其他服务器上的都可以），只需要给 ROS-DPI 建一个库和账号。还没有 MySQL 的话，见下面的[自带 MySQL 的部署方式](#还没有-mysql)。

#### 1. 准备数据库

用 root 或其他管理员账号登录 MySQL，执行以下语句（把 `your-password` 换成你自己的密码）：

```sql
CREATE DATABASE rosdpi CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'rosdpi'@'%' IDENTIFIED BY 'your-password';
GRANT ALL PRIVILEGES ON rosdpi.* TO 'rosdpi'@'%';
FLUSH PRIVILEGES;
```

- 命令行：`mysql -h <MySQL地址> -u root -p`，输入 root 密码后粘贴上面的语句；MySQL 跑在容器里时可以用 `docker exec -it <mysql容器名> mysql -u root -p`。
- 图形界面（phpMyAdmin、群晖 / 飞牛的 MariaDB 管理页、Navicat、DBeaver 等）：打开 SQL 窗口粘贴执行，或者按界面新建数据库 `rosdpi`（字符集选 `utf8mb4`），再新建用户 `rosdpi`、主机填 `%`，授予该库的全部权限。
- 表不用手动建，ROS-DPI 第一次启动时会自动创建。
- 如果 MySQL 只允许本机连接，需要把 `bind-address` 改为 `0.0.0.0`（或者 ROS-DPI 主机的 IP），并确认 3306 端口能从运行 ROS-DPI 的主机访问。

#### 2. 编写 `docker-compose.yml`

新建一个目录，保存下面的内容（也可以直接下载：`curl -O https://raw.githubusercontent.com/suyijun8182/ros-dpi/main/docker-compose.yml`）：

```yaml
# ROS-DPI：RouterOS 终端流量与应用统计
# 前提：已有 MySQL 5.7+ / 8.x，并已按 README「准备数据库」建好 rosdpi 库和账号
# 用法：保存为 docker-compose.yml，改掉标了「必改」的两处，然后 docker compose up -d
# 浏览器打开 http://<本机IP>:8080，首次打开设置管理员密码
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
      # 「必改」你的 MySQL：mysql+pymysql://账号:密码@MySQL地址:端口/库名?charset=utf8mb4
      # MySQL 在本机时地址填本机局域网 IP，不要填 127.0.0.1（那是容器自己）
      DATABASE_URL: mysql+pymysql://rosdpi:your-password@192.168.1.10:3306/rosdpi?charset=utf8mb4
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
```

需要改两处「必改」：

- `DATABASE_URL`：填上一步创建的账号、密码和 MySQL 地址。MySQL 和 ROS-DPI 在同一台机器上时，地址填这台机器的局域网 IP，**不能填 `127.0.0.1` 或 `localhost`**（在容器里它指向容器自己）。密码里有 `@ : / ? #` 等特殊字符时，需要做 URL 编码，例如 `@` 写成 `%40`。
- `LAN_CIDRS`：你的内网网段。

#### 3. 启动

```bash
docker compose up -d
docker logs -f ros-dpi     # 看到 “ROS-DPI 0.x 已启动” 就说明数据库连接成功
```

镜像同时发布在 Docker Hub（`suyijun8182/ros-dpi`）和 GHCR（`ghcr.io/suyijun8182/ros-dpi`），支持 amd64 / arm64。群晖、飞牛、威联通等 NAS 可以在 Docker / Container Manager 里新建“项目”，把 compose 内容粘贴进去即可。

#### 还没有 MySQL？

可以用 [`docker-compose.with-mysql.yml`](docker-compose.with-mysql.yml)，它会同时启动一个 MySQL 8.4 容器，并且自动建好 `rosdpi` 库和账号，**不需要执行第 1 步的 SQL**。下载后改名为 `docker-compose.yml`，改掉其中三处「必改」（两处数据库密码要一致，以及 `LAN_CIDRS`），然后 `docker compose up -d`。MySQL 第一次初始化需要 20～60 秒，ROS-DPI 会等它就绪再启动。

```bash
curl -o docker-compose.yml https://raw.githubusercontent.com/suyijun8182/ros-dpi/main/docker-compose.with-mysql.yml
```

### 首次使用

1. 浏览器打开 `http://<主机IP>:8080`。
2. 第一次打开会显示 **“首次使用：设置管理员”**，设置 admin 的密码后自动登录。如果在 compose 里填了 `ADMIN_PASSWORD`，就直接用 `admin` + 该密码登录。网页里没有数据库设置步骤，数据库只需要按上文准备好。
3. 到 **系统设置 → 接入向导** 复制 RouterOS 命令，在路由器终端执行（见下一节）。大约 1 分钟后概览页开始有数据。

**常见问题**

| 现象 | 原因与处理 |
|---|---|
| 日志反复出现 “数据库未就绪” | MySQL 地址、端口不通，或者填了 `127.0.0.1`；在 ROS-DPI 主机上执行 `nc -zv <MySQL地址> 3306` 测试 |
| `Access denied for user 'rosdpi'` | 账号或密码不对，或者账号的主机不是 `%`（只允许 localhost 登录） |
| `Unknown database 'rosdpi'` | 没建库；如果账号有建库权限，ROS-DPI 会自动创建，否则请执行第 1 步的 SQL |
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
| `DATABASE_URL` | 必填 | `mysql+pymysql://user:pass@host:3306/rosdpi?charset=utf8mb4` |
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

- **Overview**: totals, live rate, traffic mix by category, top apps and hosts, trends.
- **Hosts**: every device with IP, MAC, hostname, online state, live rate and daily / weekly / monthly totals; per-host app breakdown and visited domains.
- **Applications**: 100+ built-in apps in 20+ categories.
- **Flows**: a Sankey diagram from hosts through categories to apps.
- **Rules**: custom domain / CIDR / port rules, and a list of top unidentified domains to classify.
- Chinese and English UI, light and dark themes, works on phones.

**How it works.** RouterOS exports IPFIX (`/ip traffic-flow`) for byte counts, and mirrors DNS answers via `sniff-tzsp` so each remote IP can be mapped back to the domain the client looked up. A rule library maps domains to apps. An optional read-only REST user provides hostnames, IP-to-MAC, WAN rate and LAN prefixes. Data is aggregated per minute, hour and day into MySQL.

**Limitations.** Clients using DoH/DoT (or resolving DNS elsewhere) show up as generic HTTPS/QUIC.

**Deploy.** ROS-DPI stores data in **MySQL** (5.7 / 8.x) and assumes you already have one. Create a database and user for it:

```sql
CREATE DATABASE rosdpi CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'rosdpi'@'%' IDENTIFIED BY 'your-password';
GRANT ALL PRIVILEGES ON rosdpi.* TO 'rosdpi'@'%';
FLUSH PRIVILEGES;
```

Then save the `docker-compose.yml` shown above (or `curl -O https://raw.githubusercontent.com/suyijun8182/ros-dpi/main/docker-compose.yml`), set `DATABASE_URL` (use the host's LAN IP, not `127.0.0.1`) and `LAN_CIDRS`, and run `docker compose up -d`. Tables are created automatically. Images: `suyijun8182/ros-dpi` on Docker Hub and `ghcr.io/suyijun8182/ros-dpi`, amd64/arm64.

No MySQL yet? Use [`docker-compose.with-mysql.yml`](docker-compose.with-mysql.yml): it starts MySQL 8.4 alongside and creates the database and user for you.

**First run.** Open `http://<host>:8080` and set the admin password (or log in as `admin` with `ADMIN_PASSWORD`). There is no database step in the web UI. RouterOS commands are listed above and in **Settings → Setup guide**.

## License

[MIT](LICENSE)
