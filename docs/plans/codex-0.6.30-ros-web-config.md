# Codex 任务单：ROS-DPI 0.6.30 在网页上配置 RouterOS API

> 基线：`main` @ 025b8f5（v0.6.29 已发布 + CI action 升级），后端测试全绿。
> 来源：2026-11-19 用户在新装的二进制部署（192.168.88.240）上看到「没有配置 RouterOS API，看不到路由器状态。打开接入向导」，但接入向导只给 RouterOS 命令，地址 / 账号 / 密码只能改 `/etc/ros-dpi.env` 再重启服务。要改成在网页上填写、测试、保存，立即生效，不用重启。
> 范围只包括下面 5 个任务。**不要改**：识别库、分类逻辑、RouterOS 轮询读取的路径和解析（`poll` / `_apply` / `_apply_status` / `sample` / `check` 的业务逻辑）、采集端口、`collector_allowed`、轮询间隔（`ROS_POLL_SECONDS` / `ROS_RATE_SECONDS` 仍只走环境变量）。

## 通用约定

- 版本号：`backend/app/__init__.py` 改成 `0.6.30`。
- 每个任务一个 commit，消息用中文，格式同 git log（`feat: ...` / `fix: ...` / `docs: ...`）。**只在本地提交，不 push、不打 tag**。
- 发版文档：`CHANGELOG.md` 加 `## [0.6.30] - <日期>` 小节；README、DOCKERHUB.md、`docs/RouterOS配置.md`、`.env.example`、`install.sh` 里生成的 `/etc/ros-dpi.env` 注释同步（任务 5）。
- 验证命令（每个任务完成后都跑）：
  ```bash
  cd backend && ROSDPI_NO_JOBS=1 ASN_DB=false .venv/Scripts/python.exe -m pytest -q tests
  cd frontend && npm run build      # 含 i18n 中英键一致检查
  ```
- 中英文 i18n 键必须成对添加（`frontend/src/i18n/zh.js`、`en.js`）。
- 用 Python 改含中文标点或转义的代码时，先把脚本写成文件再执行，不要用 shell heredoc。改完扫一遍：`grep -nP '[\x00-\x08\x0b\x0c\x0e-\x1f]' -r backend/app frontend/src` 应无输出。
- **安全底线**（审查时逐条核对）：
  1. 任何 GET 接口、`/api/system`、操作日志、启动日志都**不能**出现 RouterOS 密码原文；只给 `has_ros_password: bool`。
  2. 写接口（保存 / 测试）只有管理员能调用。现有 `security.py` 已经拦截普通用户的非 GET 请求，不要绕开它，新接口也不要加进 `USER_WRITABLE`。
  3. RouterOS 仍然只发 GET 请求，ROS-DPI 不向路由器写任何东西。

## 现状（实现前先读一遍）

- `app/config.py`：`ros_url` / `ros_user` / `ros_password` / `ros_verify_tls` 只来自环境变量。
- `app/ros_poller.py`：`RosPoller.enabled` 和 `_client()` 每次都读 `get_settings()`；`_explain()` 的错误提示写着 “检查 ROS_USER / ROS_PASSWORD”。
- `app/engine.py:70`：`self.ros_managed = bool(s.ros_url)` 只在构造时算一次。
- `app/main.py:187`：`if poller.enabled:` 才注册 `ros-rate` / `ros-poll` 两个定时任务。启动时没配，之后再配也不会轮询。
- `app/routers/admin.py`：`GET /api/settings` 返回 `ros_url` / `ros_user`；`POST /api/ros/test` 没配时报 “请在环境变量中设置”。
- 外部数据源（sing-box / MosDNS / AdGuard）已经是“网页填写优先、环境变量作默认、存 settings 表、`has_*_password` 掩码”的模式，见 `app/integrations.py` 的 `KEYS` / `effective()` / `apply()`，以及 `admin.py` 的 `_integrations()` / `put_settings()`。**照这个模式做，不要另起一套。**
- `app/oplog.py:9`：`SECRET_KEYS` 决定操作日志里哪些字段打码。
- 前端：`frontend/src/views/Settings.vue:39-48` 是 RouterOS 状态卡（没配时只显示 `settings.rosHint`）；第 478 行附近是接入向导第 4 步的 RouterOS 命令；`Overview.vue` 没配时显示 `overview.rosOff` 和 `overview.openGuide` 按钮。
- 测试：`backend/tests/test_ros_poller.py` 用 `monkeypatch.setattr(get_settings(), "ros_url", ...)` 和替换 `poller._client` 来模拟 RouterOS。

---

## 任务 1 后端：RouterOS 配置改成运行时可变

**改法**

1. `app/ros_poller.py`
   - 模块级常量 `ROS_KEYS = ("ros_url", "ros_user", "ros_password", "ros_verify_tls")`。
   - `effective(db_values: dict) -> dict`：与 `integrations.effective` 同语义。数据库里的值不是 `None` 就用数据库的（空字符串表示“网页上清除了”，此时**不**回落到环境变量），否则用环境变量。`ros_verify_tls` 在数据库里存 `"1"` / `"0"`，返回 bool。另返回 `source`：`"web"`（数据库里有 ros_url 这一行，哪怕是空串）/ `"env"` / `"none"`（最终 url 为空）。
   - `RosPoller` 增加实例属性 `url / user / password / verify_tls`，新增 `configure(url, user, password, verify_tls)`：
     - 与当前值完全相同时什么都不做（返回 False）。
     - 有变化时：更新属性，**清空上一个路由器的运行态**（`ok=False`、`error=""`、`last_poll=0`、`identity`、`resource`、`interfaces`、`wan_name`、`wan_rate`、`_wan_prev`、`leases`、`lease_list`、`if_rate`、`_if_prev`、`wans`、`pools`、`samples`、`mangle`、`ip_settings`、`filter_rules`、`filter6_rules`、`has_ipv6`、`_sample_prev`），并设 `self.engine.ros_managed = bool(url)`，返回 True。`wan_override` 不动。
     - 整个替换要在一把 `threading.Lock` 下做，`poll()` / `sample()` 开头先在锁内取一份 `(url, user, password, verify_tls)` 快照再发请求，避免轮询线程拿到一半新一半旧的配置。
   - `enabled` 改为 `bool(self.url)`；`_client()` 改用实例属性；不再读 `get_settings()` 的 ros_* 字段。
   - `poll()` / `sample()` 开头：`if not self.enabled: return`（没配时定时任务空转）。
   - `_client()` 加 `follow_redirects=False`（默认就是 False，显式写出来，防止以后被改）。
   - `_explain()` 的提示把 “ROS_USER / ROS_PASSWORD”“ROS_URL” 改成 “用户名 / 密码”“RouterOS 地址”（网页和环境变量两种配法都适用）。
   - 新增 `probe(url, user, password, verify_tls) -> dict`：**不改动 poller 状态**，用临时 client 只读 `GET /rest/system/identity` 和 `GET /rest/system/resource`，返回 `{"ok": True, "identity", "version", "board"}` 或 `{"ok": False, "error": _explain(e)}`。超时 8 秒。错误信息里不能拼进响应体，`_explain` 现有分支已满足，确认一遍。
2. `app/engine.py:70`：保持初值 `False`，由 `poller.configure()` 设置（启动时任务 1 第 3 步会调用）。
3. `app/main.py`
   - `_apply_saved()` 里一并读 `ROS_KEYS`，调用 `poller.configure(**{k: cfg[k] for k in ROS_KEYS})`（cfg 来自 `ros_poller.effective`）。
   - 定时任务**无条件**注册 `ros-rate` / `ros-poll`（`poll` / `sample` 内部已在没配时直接返回）。启动时的那次立即 `poll` 也保留，没配时会直接返回。
   - 注意 `_apply_saved()` 在 `_on_db_ready` 里执行，装机向导保存数据库后也会走一遍。环境变量配了 ROS 而数据库还没就绪时，要在数据库就绪前也能轮询：`lifespan` 开头先用 `effective({})`（纯环境变量）调一次 `configure`，数据库就绪后 `_apply_saved()` 再覆盖。
4. `app/oplog.py`：`SECRET_KEYS` 加 `ros_password`。

**测试**（新建 `backend/tests/test_v0630_ros_web_config.py`，并改造 `test_ros_poller.py`）
- `test_ros_poller.py` 里 `monkeypatch.setattr(get_settings(), "ros_url", ...)` 改成 `poller.configure("https://192.168.88.1", "u", "p", False)`，测试结束用 fixture 还原 `poller.configure("", "", "", False)`。原有断言全部保留且通过。
- `effective()`：数据库空 → 用环境变量，source=env；数据库有 url → 用数据库，source=web；数据库 url 为空串 → 不启用，source=web（确认不会回落到环境变量）；两边都空 → source=none。
- `configure()` 换地址后旧的 `identity` / `samples` / `leases` 被清空，`engine.ros_managed` 跟着变；相同参数再调一次返回 False 且状态不清空。
- 没配时 `poll()` / `sample()` 不发任何请求（MockTransport handler 里计数为 0）。
- `probe()` 成功 / 401 / 连接失败三种情况，且 poller 原有状态不变。

---

## 任务 2 后端：设置接口与测试接口

**改法**（`app/routers/admin.py`）

1. `SettingsIn` 增加：
   ```python
   ros_url: str | None = Field(None, max_length=255)
   ros_user: str | None = Field(None, max_length=64)
   ros_password: str | None = Field(None, max_length=255)
   ros_verify_tls: bool | None = None
   ```
   语义：`None` = 不修改；`ros_url=""` = 清除（停用 RouterOS API，同时把 user / password 也存成空串）；`ros_password` 前端只在用户输入了新密码时才发送。
2. `put_settings()` 校验：
   - `ros_url` 非空时必须是 `http://` 或 `https://` 开头，**不能**带 `user:pass@`（用 `urllib.parse.urlsplit`，有 `username` / `password` 就 400：“账号密码请填在下面的用户名 / 密码栏，不要写进地址”），不能带 query / fragment；去掉末尾 `/`；如果用户填了 `/rest` 结尾也去掉（`_client` 会自己加）。
   - 保存后 `db.flush()`，从数据库重新读 `ROS_KEYS` 走 `ros_poller.effective()` → `poller.configure(...)`；返回 True（配置变了）且启用时，用 `run_in_threadpool` 或后台线程**立即触发一次 `poller.poll()`**，不要阻塞响应超过必要时间（直接在线程池里同步调一次也可以，`poll` 有 10 秒超时；二选一，写清楚理由）。
   - `oplog` 记录本次修改时，确认 `ros_password` 被打码（任务 1 第 4 步）。
3. `GET /api/settings`：把现有的 `"ros_url": s.ros_url, "ros_user": s.ros_user` 换成
   ```python
   "ros": {"url": cfg["ros_url"], "user": cfg["ros_user"], "has_password": bool(cfg["ros_password"]),
           "verify_tls": cfg["ros_verify_tls"], "source": cfg["source"]},
   ```
   同时把前端所有读 `s.ros_url` / `s.ros_user` 的地方改过来（`grep -rn "ros_url\|ros_user" frontend/src`）。
4. `POST /api/ros/test` 改成可带请求体：
   ```python
   class RosTestIn(BaseModel):
       url: str | None = Field(None, max_length=255)
       user: str | None = Field(None, max_length=64)
       password: str | None = Field(None, max_length=255)   # 留空 = 用已保存的密码
       verify_tls: bool | None = None
   ```
   - 不带请求体（或 `url` 为 None）：保持现在的行为，对当前配置 `poller.poll()` 后返回 `poller.status()`；没配时 400，提示文案改成 “还没有配置 RouterOS API，请在 系统设置 → RouterOS API 填写”。
   - 带 `url`：先做第 2 步同样的地址校验，`password` 为 None 或空时用当前生效的密码，然后调用 `poller.probe(...)`，**不保存、不改 poller 状态**，返回 probe 结果。
   - 只有管理员能调（非 GET，`security.py` 已拦截；在测试里断言普通用户 403）。
5. `/api/system` 的 `router` 字段（`poller.status()`）里加 `source`，供状态卡显示“来自网页 / 来自环境变量”。

**测试**
- PUT 保存地址、用户名、密码 → GET 只返回 `has_password: true`，响应 JSON 全文里搜不到密码原文；`/api/system`、操作日志表里也搜不到。
- 不传 `ros_password` 再 PUT 一次（只改用户名）→ 密码保留。
- `ros_url=""` → 停用，`poller.enabled` 为 False，GET 的 `source` 为 `web`，环境变量里的 `ROS_URL` 不再生效。
- 地址校验：`ftp://x`、`https://u:p@1.2.3.4`、`https://1.2.3.4/?a=1` 都返回 400；`https://192.168.88.1/rest/` 存成 `https://192.168.88.1`。
- `/api/ros/test` 带请求体：MockTransport 成功返回 identity，失败（401）返回 `ok: false` 和中文提示；两种情况下 poller 原状态不变、数据库没写入。
- 普通用户调用 PUT `/api/settings` 和 POST `/api/ros/test` 都是 403。

---

## 任务 3 前端：系统设置里的 RouterOS API 卡片

**改法**（`frontend/src/views/Settings.vue` + i18n）

1. 现有 RouterOS 状态卡（第 39–48 行）改成“状态 + 表单”：
   - 顶部状态行保持：状态点（未配置灰 / 正常绿 / 出错红）、Identity · 版本、最近轮询时间、错误信息（`sys.router.error`），再加一个来源标签：`来自网页` / `来自环境变量` / `未配置`。
   - 表单字段：
     - **RouterOS 地址**：placeholder `https://192.168.88.1`；下方小字说明 “RouterOS 7 的 REST API，需要在 /ip service 启用 www-ssl（HTTPS）或 www（HTTP）”。
     - **用户名**：placeholder `rosdpi`。
     - **密码**：`type="password"`、`autocomplete="new-password"`；已保存过密码时 placeholder 显示 “已保存，留空则不修改”；不回显原文。
     - **校验 HTTPS 证书**：复选框，默认不勾，旁边小字 “路由器用自签证书时不要勾选”。
   - 按钮：
     - **测试连接**：用表单当前值调 `POST /api/ros/test`（密码框空时不传 password，由后端用已保存的），结果显示在按钮旁：成功 “已连上 <identity>（RouterOS <version>）”，失败显示后端返回的中文提示。测试中按钮禁用并显示加载状态。
     - **保存**：调 `PUT /api/settings`，只发送有变化的字段，密码框为空就不发 `ros_password`；成功后清空密码框、刷新 `/api/settings` 和 `/api/system`；2 秒后再刷新一次 `/api/system`，拿到首次轮询结果。
     - **停用**：仅在 `source === 'web'` 且已配置时显示；确认后发 `ros_url: ""`。确认对话框**不要用** `window.confirm`，沿用项目里已有的确认组件或二次点击确认的写法（先 grep 现有删除操作怎么做的）。
   - `source === 'env'` 时表单预填环境变量的地址和用户名，并提示 “当前使用环境变量 /etc/ros-dpi.env（或 .env）中的配置；在这里保存后以网页填写的为准”。
   - 非管理员：表单只读（字段 disabled，不显示测试 / 保存 / 停用按钮），只看状态。用现有判断管理员的方式（grep `isAdmin` 或 `role`）。
   - 给这张卡加 `id="ros-api"`，供下面跳转定位。
2. 接入向导第 4 步（第 478 行附近的 RouterOS 命令）：
   - `/user add ... address=` 填 ROS-DPI 主机 IP（向导里已经算出的 `{ip}`，不要写死），并在命令下方加一句 “执行后，在上方 RouterOS API 卡片填写地址、用户名和密码，点测试连接再保存”，带一个跳到 `#ros-api` 的链接。
   - 命令里的 `/ip service set www-ssl disabled=no` 后面补一行注释说明没有证书时可改用 `www`（HTTP）。
3. i18n：`settings.rosHint` 改成 “未配置。在下面填写 RouterOS 地址和只读账号后，可显示主机名、WAN 口速率和路由器状态。”（中英文都改），去掉 “设置环境变量” 的说法。新文案全部成对加到 `zh.js` / `en.js`。

---

## 任务 4 前端：概览页的入口

**改法**（`frontend/src/views/Overview.vue` + i18n）

- 没配 RouterOS API 时（`!d.router.enabled`），`overview.rosOff` 提示旁的按钮：管理员显示 “去配置”，跳转到 系统设置 并滚动到 `#ros-api`（用项目现有的路由方式，带 hash 或 query 均可，Settings 页挂载后 `scrollIntoView`）；普通用户不显示按钮，提示改成 “请联系管理员配置 RouterOS API”。
- 原来的 “打开接入向导” 如果其他地方还在用（`grep -rn openGuide frontend/src`），保留键名不删，只改这里的用法。
- 配了但连不上（`d.router.enabled && !d.router.ok`）时，同位置显示 “RouterOS API 连接失败” + 错误摘要 + 同一个 “去配置” 按钮（管理员）。

---

## 任务 5 文档与发版

- `CHANGELOG.md` 0.6.30：RouterOS API 可以在 系统设置 → RouterOS API 填写、测试、保存，立即生效、不用重启；网页填写优先于环境变量；密码只写不读；概览页没配置时可直接跳过去配置。
- `README.md`、`DOCKERHUB.md`：配置 RouterOS API 的说明改成“在网页 系统设置 → RouterOS API 填写（推荐），或用环境变量 ROS_URL / ROS_USER / ROS_PASSWORD”。README 的环境变量表里 `ROS_URL` 那行的“网页可改”现在才名副其实，确认描述准确。DOCKERHUB.md 版本说明加 0.6.30 一行（中英文）。
- `docs/RouterOS配置.md` 第 4 节：RouterOS 命令后面改成“然后在 ROS-DPI 网页 系统设置 → RouterOS API 填写；也可以写在 `.env` / `/etc/ros-dpi.env`”，并说明网页填写的优先。
- `.env.example` 的 ROS_* 注释、`install.sh` 生成的 `/etc/ros-dpi.env` 模板注释：加一句 “也可以在网页 系统设置 → RouterOS API 里填写，网页填写的优先”。**install.sh 只改注释文本，不改逻辑。**
- 版本号 `0.6.30`。

---

## 完成后给我的回报

在本文件末尾追加“执行记录”：每个任务的 commit 号、改了哪些文件、新增测试数和全量测试结果、`npm run build` 结果，以及偏离本单的地方和理由。不要 push。

## 执行记录

2026-11-19，在已有任务单提交 `c47c05f` 上完成五项工作。下表的新增测试数按 pytest 收集的用例计数，包含参数化组合。

| 任务 | 本地提交 | 修改文件 | 新增测试 | 后端全量测试 | 前端构建及中英键检查 |
|---|---|---|---:|---|---|
| 1 · 运行时配置与轮询 | `d8e8c2b` | `backend/app/ros_poller.py`、`engine.py`、`main.py`、`oplog.py`，`backend/tests/test_ros_poller.py`、`test_v0630_ros_web_config.py` | 10 | 189 passed | 通过，1,223 个键 |
| 2 · 设置与试连接口 | `cc2b13e` | `backend/app/routers/admin.py`、`backend/app/main.py`、`backend/app/ros_poller.py`、`backend/tests/test_v0630_ros_web_config.py` | 10 | 199 passed | 通过，1,223 个键 |
| 3 · 设置卡片与向导 | `1242133` | `frontend/src/components/RouterOsCard.vue`、`frontend/src/views/Settings.vue`、`frontend/src/i18n/zh.js`、`en.js` | 0 | 199 passed | 通过，1,239 个键 |
| 4 · 概览入口与定位 | `fdc03c1` | `frontend/src/views/Overview.vue`、`Settings.vue`、`frontend/src/i18n/zh.js`、`en.js` | 0 | 199 passed | 通过，1,241 个键 |
| 5 · 版本与部署文档 | `ebe859c` | `backend/app/__init__.py`、`CHANGELOG.md`、`README.md`、`DOCKERHUB.md`、`docs/RouterOS配置.md`、`.env.example`、`install.sh` | 0 | 199 passed | 通过，1,241 个键 |

每一步均按任务单运行完整 pytest 和 `npm run build`。后端每次有 3 条测试依赖警告，来自 Starlette 测试客户端、AnyIO 和既有 JWT 兼容测试。控制字符扫描无匹配，`git diff --check` 通过。

**补充验收**

- 用隔离的 SQLite 数据库、真实后端和本机模拟的 RouterOS REST 服务，在 Edge 的 390 像素宽视口走通管理员操作。覆盖从概览进入设置、成功试连、保存、留空复用密码、401 错误、回到概览查看失败摘要、取消和确认停用，以及从接入向导跳回卡片。
- 普通用户在概览可见联系管理员的提示，设置卡片字段禁用。接口测试另行验证保存和试连均返回 403。两条浏览器流程均无未捕获的页面异常。本次验收没有连接现场设备。

**实现取舍**

- 用 FastAPI 后台任务在保存响应发出后立即轮询，避免路由器响应时间影响网页保存。轮询与采样核对配置代次，可丢弃切换前已发出请求的迟到结果。
- 设置页沿用原有权限，普通用户从系统状态接口读取状态与来源。表单和确认对话框封装为独立 Vue 组件，设置页负责刷新数据和定位。首次仅修改环境变量配置的账号或 TLS 时，同时记录当前地址，供来源标签和停用操作使用。
- 五项任务各有一个本地提交。为在本文件写入第五项的实际提交号，执行记录单独提交。未推送，未打标签。
