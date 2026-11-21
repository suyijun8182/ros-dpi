# Codex 任务单：0.7.0 多站点（一个平台管多台 RouterOS）

> 基线：`main` @ 0c1f364（0.6.30，206 个测试全绿）。
> 来源：2026-11-21 与用户的需求讨论（grill 记录见本文“已定决策”）。
> 约定：每个任务一个本地 commit，中文消息，不 push、不打 tag；每个任务后跑全量 pytest 和 `npm run build`。任务按顺序做，后面的依赖前面的。
> 版本号在任务 I 改成 0.7.0。

---

## 已定决策（不要擅自改）

| # | 决策 |
|---|---|
| D1 | 一个平台、一个库，相关表加 `site` 列。目标规模 ≤10 台，不做多租户 |
| D2 | 站点间用 WireGuard 互通；文档按此写，REST API 不建议暴露公网 |
| D3 | 按 UDP 源 IP 识别站点，所有站点共用 2055 / 37008 端口；生成的 ROS 命令带 `src-address` |
| D4 | 未登记来源的数据丢弃，并记到“未登记来源”列表（IP、端口类型、最近时间、包数），管理员可一键登记到站点 |
| D5 | **单站点兼容**：只有 1 个站点且它没登记源 IP 时，接收所有来源（= 0.6.x 行为）。保存第 2 个站点时，要求**所有**启用站点都有源 IP，否则 400 |
| D6 | 按站点隔离：终端 / 命名 / 人员与部门 / 访问日志 / 审计事件 / 实时流量与 WAN 速率 / 未识别流量 / 域名统计 |
| D7 | 全局共享：应用识别库、ASN/GeoIP、DNS 缓存、域名地理、系统设置、账号、通知渠道、社区共享（整个平台一个实例） |
| D8 | 自定义规则、审计规则：默认全部站点，可选限定一个站点（`site` 为空 = 全部） |
| D9 | LAN 网段按站点（每站点一份 `lan_cidrs`）；sing-box / mosdns / AdGuard 集成各绑一个站点，默认绑默认站点（讨论后由 Claude 按 D6 推定，用户可改） |
| D10 | 每站点独立的 ROS 轮询和状态；一台连不上不影响别的 |
| D11 | 站点在网页里管理（仅管理员）：标识 slug（创建后不可改）、名称、源 IP（多个）、REST 地址 / 账号 / 密码 / 校验 TLS、平台地址（从该站点看）、LAN 网段、启用。环境变量 `ROS_*` 只用于首次生成默认站点 |
| D12 | 停用（保留数据）和删除（二次确认，清掉该站点全部数据）都提供 |
| D13 | 管控命令只能选当前站点的人员 / 设备 |
| D14 | 通知共用渠道，消息前加 `[站点名]`（只有 1 个站点时不加） |
| D15 | **只有 1 个站点时，所有多站点 UI 都不出现**，界面与 0.6.x 一致 |
| D16 | ≥2 站点时顶部有站点切换器，选项：各站点 + “全部”。“全部”只是总览页：每站点一张卡片（实时速率、今日流量、在线终端、Top 5 应用、连接状态），**数据不相加**，点卡片进入该站点。其他页面必须选具体站点 |
| D17 | 当前站点放在 URL `?site=<slug>`，没有时用 localStorage 里上次选的，再没有用第一个有权限的站点 |
| D18 | 管理员看全部站点；普通用户只能看被授权的站点。升级时已有普通用户自动授权默认站点；新站点默认只有管理员可见 |
| D19 | API 令牌可访问全部站点，接口一律用 `site` 参数选站点 |
| D20 | 升级在启动阶段迁移表结构（会停机），日志打印进度；迁移前日志和 README 提醒先备份 |
| D21 | 不做：Prometheus `/metrics`、按站点分通知渠道、跨站点批量管控 |

默认站点：slug `default`，名称“默认站点”（可改名）。

---

## 任务 A　数据模型与迁移

**新表**

- `sites`：`slug` String(32) PK（`^[a-z0-9][a-z0-9-]{0,31}$`）、`name` String(64)、`sources` Text（逗号分隔的 IP）、`ros_url` / `ros_user` / `ros_password` / `ros_verify_tls`、`platform_addr` String(255)、`lan_cidrs` Text、`enabled` Integer、`sort` Integer、`created` BigInteger。
- `user_sites`：`user_id` + `site` 复合主键。
- `unknown_sources`：`ip` + `kind`（ipfix / tzsp）主键、`last_seen`、`packets`。内存计数，flush 时落库，保留 7 天。

**加 `site` 列（String(32)，NOT NULL，默认 `'default'`）并进主键 / 索引**

- 主键要加 `site`：`traffic_minute` / `traffic_hour` / `traffic_day`、`host_domain_day`、`unmatched_day`、`hosts`、`host_names`、`person_devices`。
- 普通列 + 索引前缀加 `site`：`access_log`、`audit_events`、`people`、`departments`（部门名唯一约束改成 `(site, name)`）。
- 可空列（空 = 全部站点）：`custom_rules.site`、`audit_rules.site`。
- 不动：`dns_cache`、`domain_geo`、`settings`、`users`、`api_tokens`、`op_log`、`share_*`、`accuracy_probes`。

**迁移**（新文件 `backend/app/migrate_sites.py`，在 `init_db` 之后、`add_missing_columns` 之前执行）

1. 用 `settings` 里的 `schema_sites=1` 标记幂等，已迁移则跳过。
2. 打印 `[migrate] 0.7.0 多站点迁移开始，请确认已备份数据库`，以及每张表的进度（表名、行数、耗时）。
3. 需要改主键的表：MySQL 用 `ALTER TABLE … ADD COLUMN site … DEFAULT 'default', DROP PRIMARY KEY, ADD PRIMARY KEY (site, …)`，一条语句完成；SQLite 用“建新表 → `INSERT … SELECT` → 删旧表 → 改名”。
4. 建默认站点：`ros_*` 取 `settings` 表里的值，没有就取环境变量；`lan_cidrs` 取 `settings` 表或环境变量；`sources` 留空（对应 D5）。迁移后把 `settings` 里的 `ros_*` / `lan_cidrs` 删掉。
5. 已有 role=user 的用户都插一行 `user_sites(default)`。
6. 新装（空库）直接按新结构建表，建默认站点，同样打标记。

**测试**：用 0.6.30 结构的 SQLite 库（造几行数据）跑迁移，断言数据都在、`site='default'`、主键正确，第二次运行不做任何事；新装路径测一次。MySQL 用 docker-compose.with-mysql 手工验证，结果写进执行记录。

## 任务 B　站点注册表与按站点的 Engine

- 新增 `backend/app/sites.py`：`SiteRegistry` 从 `sites` 表加载；`resolve(src_ip) -> slug | None` 按 D3 / D5 判断；`reload()` 在站点增删改后调用。
- `Engine` 一个站点一个实例（`registry.engines[slug]`）。分类器、ASN、全局设置共享引用（`reload_classifier` 对所有实例生效）；DnsMap、ConnNames、SNI、会话、速率、`lan_nets`、代理状态都各站点独立。
- `collector.start_listeners` 的 handler 先 `resolve`；结果为 None 时只更新未登记来源计数，然后返回。
- 落库：`_write_flush` 每一行都带上 `self.site`；`load_state`、`cleanup` 按站点过滤（cleanup 可以只由一个实例跑全表）。
- `collector_allowed`（全局 ACL）保持现状，先于站点判断。
- 现有大量代码 `from app.engine import engine`：保留一个 `engine` 名字指向默认站点的实例作过渡，任务 D 结束前要全部改成按站点取，最后删掉（`grep -rn "import engine"` 结果为 0）。

**测试**：两个站点、相同内网 IP `192.168.88.10`，从两个源 IP 各发 IPFIX，落库后两个 `site` 下各有一份数据，互不串；未登记的源被丢弃并计数；单站点无源 IP 时任何来源都收。

## 任务 C　按站点的 ROS 轮询与集成

- `ros_poller.poller` 改成 `pollers: dict[slug, RosPoller]`，跟随 `SiteRegistry.reload()` 增删。调度器对每个启用站点跑 `poll` / `sample`，每个站点用自己的 job id，单个站点抛异常不影响其他。
- ROS 自动发现的网段（`set_auto_nets`）写进该站点的 Engine。
- 集成（sing-box / mosdns / AdGuard）在 settings 里新增 `integrations_site`（默认 `default`），喂给对应站点的 Engine。
- 0.6.30 的同源密码保护（任务 A，`_same_origin`）照搬到站点编辑接口：改了地址就必须重新输入密码。

## 任务 D　API 按站点隔离与权限

- `security.py` 新增依赖 `site_ctx(site: str | None = Query(None))`：
  - 没传 `site` 时，用户只有一个有权限的站点就用它，否则 400“请选择站点”；
  - 站点不存在返回 404；没有权限返回 403。管理员和 API 令牌有全部权限；
  - 返回站点对象（含 engine、poller）。
- `routers/stats.py`、`audit.py`、`people.py`、`compliance.py`、`diag.py`、`admin.py` 中读数据的接口，以及 `stats.py`、`insight.py`、`audit.py`、`people.py`、`control.py`、`reclass.py`、`hostnames.py`、`devtype.py` 的查询都加 `site` 过滤。逐个文件 grep 模型名，不能漏。
- 审计规则：按规则的 `site` 只在对应站点评估（为空则每个站点都评估），事件带 `site`。`new_host` 规则按站点判断“新”。
- 自定义规则：`site` 非空时只在那个站点的 Engine 生效。
- `notify.py`：启用站点 ≥2 个时，标题前加 `[站点名]`。
- `control.py`：只接受当前站点的 host / person。
- 社区共享（`share.py`）：投票从所有站点汇总，实例 ID 不变。

**测试**：普通用户访问没授权的站点 → 403；两个站点同 IP 的主机详情各查各的；审计规则限定 A 站点时 B 站点不触发；参数化遍历所有带 `site_ctx` 的路由做一遍冒烟（复用 `test_routes_smoke.py` 的方式）。

## 任务 E　站点管理接口与设置页

- 接口（仅管理员）：`GET/POST /api/sites`、`PUT/DELETE /api/sites/{slug}`、`POST /api/sites/{slug}/disable`、`POST /api/sites/{slug}/test`（试连 ROS）、`GET /api/sites/unknown-sources`。
  - 保存时校验 D5：启用站点 ≥2 个时，每个都必须有源 IP；同一个源 IP 不能登记到两个站点；默认站点不能删除（可以改名、停用）。
  - 删除：请求体带 `confirm: <slug>`，逐表 `DELETE … WHERE site=?`，并记操作日志。
  - 密码只写不读，沿用 0.6.30 的规则。
- 前端 `Settings.vue`：
  - 只有 1 个站点时：RouterOS 卡片照旧（`RouterOsCard.vue` 改成编辑默认站点），底部多一个“添加站点”按钮，其他没有变化。
  - ≥2 个站点时：变成站点列表（名称、状态点、源 IP、启用开关、编辑 / 停用 / 删除），再加一张“未登记来源”卡片（一键登记到某站点）。
  - 添加第二个站点的弹窗里，同时要求补全默认站点的源 IP，旁边列出最近的未登记来源 / 已收到数据的源 IP 供点选。
- “部署与自检”：≥2 个站点时出现站点选择和“平台地址（从该站点看）”；生成命令时，`sniff-target`、traffic-flow target 用这个地址，并加 `src-address=<该站点第一个源 IP>`。只有 1 个站点时和现在完全一样。

## 任务 F　前端站点切换

- `api.js`：新增 `siteState`（`list`、`current`），登录后拉 `/api/sites/mine`（每个站点的 slug、名称、状态）。axios 拦截器给所有请求自动加 `params.site`（站点管理接口、认证接口除外）。
- `router.js`：`beforeEach` 按 D17 补齐 `?site=`，换页时保留这个参数；切换站点时只改 query，页面 watch 到后重新拉数据（`poll.js` 已有的刷新机制）。
- `App.vue` 顶栏：可见站点 ≥2 个时才显示切换器（离线站点打标记）；只有 1 个时不渲染，URL 也不带 `?site`。
- 内部链接（主机详情、人员详情、应用详情、审计跳转）都保留 `site`。
- i18n 中英文成对，用现有的键检查脚本验证。

## 任务 G　“全部”总览页

- 后端 `GET /api/sites/overview`：返回当前用户可见的每个站点的实时上 / 下行、今日上 / 下行、在线终端数、Top 5 应用、ROS 状态。只读内存和 `traffic_day`，不做跨站点加总。
- 前端新路由 `/sites`（`views/Sites.vue`），切换器选“全部”时进入这个页面；每个站点一张卡片，点卡片跳到 `/?site=<slug>`。页面风格和全网概览一致。
- 其他页面没有“全部”选项；用户如果手动在 URL 里写 `?site=all`，跳到 `/sites`。

## 任务 H　用户站点授权

- `UsersPanel.vue`：普通用户的编辑弹窗里加“可访问的站点”多选（≥2 个站点时才显示）；管理员不显示（默认全部）。
- `POST/PUT /api/users` 接收 `sites: list[str]`；普通用户至少要选一个站点。
- 登录响应和 `/api/auth/me` 返回 `sites`。

## 任务 I　文档与版本

- 版本号 0.7.0（`backend/app/__init__.py`、`frontend/package.json` 等现有改版本号的地方都改）。
- `docs/RouterOS配置.md` 新增“多站点”一节：两台 ROS 之间配 WireGuard 的示例（配置命令、allowed-address、路由），traffic-flow / mangle 带 `src-address`，在平台里登记站点的步骤。
- README（中英文两部分）：功能列表加多站点；升级说明写明 **0.7.0 首次启动要迁移表结构，先备份**，迁移耗时与数据量相关。
- CHANGELOG 0.7.0。

---

## 完成后

在本文件末尾追加执行记录：每个任务的 commit 号、新增测试数、全量 pytest 和 `npm run build` 结果、偏离本单的地方和理由。另外：

- 单站点回归：0.6.30 的库升级后，界面上不出现任何多站点元素，数据和功能一切照旧（用 Edge 截图对比概览、主机、设置三页）；
- 双站点实测：两个源 IP 用相同内网网段灌数据，确认各个页面、审计、通知都按站点隔离，“全部”页卡片的数值和各站点概览页一致；
- MySQL 迁移实测：耗时和行数。

不要 push。

## 执行记录

2026-11-21 ~ 22，由 Claude 直接实现（未交给 Codex）。基线 `63a7334`（任务单）时后端 206 个测试全绿。

| 任务 | 本地提交 | 后端全量 pytest | 前端构建 / 中英文键 |
|---|---|---|---|
| A · 数据模型与迁移 | `23cbf1d` | 208 passed | 未改前端 |
| B · 站点注册表、按源 IP 分 Engine | `2d2cd5d` | 212 passed | 未改前端 |
| （插入）LocalDNS 外部数据源 | `a9cf0ea` | 213 passed | 通过 |
| C · 按站点的 RouterOS 轮询与集成 | `6ef70cf` | 216 passed | 未改前端 |
| D · API 按站点隔离与权限 | `311fc2d` | 225 passed | 未改前端 |
| E 后端 · 站点管理接口 | `f5c90e6` | 227 passed | 未改前端 |
| E 前端 + F + G + H | `c270edd` | 229 passed | 通过，1,299 个键 |
| I · 文档与版本号 | `7f109bd` | 229 passed | 通过 |

### 偏离本单的地方

- **按站点过滤的做法**：没有在每个查询里手写 `site`，改为会话级过滤（`app/scoping.py`）：请求的 `site_ctx` 把站点写进 `db.info["site"]`，`do_orm_execute` 用 `with_loader_criteria` 给所有按站点隔离的表加条件（select / update / delete / `db.get` 都生效），`before_flush` 给新对象填站点。漏写一个查询就串站的风险没了；后台全站任务不设站点即不过滤。有专门测试（`test_v070_scoping.py`）覆盖交替站点时 lambda 缓存不串。
- **不传 `?site=`**：本单写的是返回 400，实际用第一个能看的站点。这样单站点部署和已有的 API 令牌 / Home Assistant 不用改。
- **`from app.engine import engine` 没有清零**：识别器是全站共用的，大量 `engine.classifier` 引用保留；按站点的状态（速率、会话、DNS、RouterOS）都已改为按请求站点取。
- **只有一个站点时**普通用户不需要站点授权就能看（授权界面也不显示）。
- **站点规则**：只对一个站点生效的自定义规则由 `SiteClassifier` 在共用识别器前先匹配；端口规则只在连接没有域名时生效（近似：有域名但内置库没认出时不会再落到站点端口规则）。
- **访问日志行 ID** 改为全局计数器（多个站点写同一张表不撞号），本单没写到。
- 抓包采样只录选中站点的镜像包；Syslog 在多站点时带 `site` 字段。
- 任务 E 前端、F、G、H 互相依赖（切换器、设置页、授权都用同一份站点状态），合成一个提交。
- 顺手修了 0.6.30 起就有的前端问题：直接打开 `/settings?tab=system` 时版本更新状态未初始化报错。

### 实测

- **MySQL 迁移**：本机没有 Docker，没能实测。加了 `tests_mysql/test_migrate_mysql.py`（改主键、部门唯一索引换成 `(site, name)`、重复运行不做事），由 CI 的 MySQL 8.4 服务跑。迁移耗时未测。
- **单站点回归**：新库启动后，概览、主机、设置页都没有站点切换器，地址里不带 `?site`（Edge 无头截图）。
- **双站点**：本机起一个实例，从 127.0.0.1 和 127.0.0.2 两个地址分别发 IPFIX + DNS，两边都有内网 IP `192.168.88.10`。在设置页添加「公司」站点（同时补默认站点源 IP）后切换器立即出现；公司的主机列表只有公司的两台设备，同一 IP 在两个站点分别识别成企业微信 / 哔哩哔哩；「全部站点」两张卡片各算各的；公司的接入向导用平台地址 10.8.0.1 并带 `src-address`；新建普通用户可勾选站点。全程浏览器控制台无报错。
- 发现并修复：点「添加站点」过快时站点列表还没加载，弹窗里不会要求补已有站点的源 IP（改为等列表加载完再打开）；IP 地址按钮与全局 `.chip` 样式冲突；卡片内容被 `<button>` 默认垂直居中。
- 新库首次启动时 `devtype-startup` 在建表前运行报一次 `no such table`，0.6.30 同样存在，一小时后自动重试，未改。

未推送、未打标签。
