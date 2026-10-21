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

```bash
mkdir ros-dpi && cd ros-dpi
curl -O https://raw.githubusercontent.com/suyijun8182/ros-dpi/main/docker-compose.yml
curl -o .env https://raw.githubusercontent.com/suyijun8182/ros-dpi/main/.env.example
# 编辑 .env：修改 MYSQL_PASSWORD / MYSQL_ROOT_PASSWORD，填写 LAN_CIDRS
docker compose up -d
```

打开 `http://<主机IP>:8080`，第一次访问时设置管理员密码。

镜像：`ghcr.io/suyijun8182/ros-dpi`（amd64 / arm64）。已有 MySQL 时，删掉 compose 里的 `mysql` 服务，把 `DATABASE_URL` 指向你的数据库即可。

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
| `DATABASE_URL` | compose 中已设置 | `mysql+pymysql://user:pass@host:3306/rosdpi?charset=utf8mb4` |
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

**Deploy.** Copy `docker-compose.yml` and `.env.example` (as `.env`), set the MySQL passwords and `LAN_CIDRS`, run `docker compose up -d`, then open `http://<host>:8080`. RouterOS commands are listed above and in **Settings → Setup guide** inside the app.

## License

[MIT](LICENSE)
