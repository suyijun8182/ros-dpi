# Codex 任务单：ROS-DPI 0.6.28 加固

> 基线：`main` @ 5f7fdc9（v0.6.27），后端 151 个测试全绿。
> 来源：2026-11-16 审查（覆盖 0.6.25–0.6.27 新增代码 + 2026-10-25 审计遗留的 P2/P3）。
> 范围只包括下面 6 个任务。**不要改**：识别库、分类顺序、ECharts 配色（维盟 9 色是用户指定的）、社区主站的发布门槛与默认开关（这两项要用户拍板，不在本单）。

## 通用约定

- 版本号：`backend/app/__init__.py` 改成 `0.6.28`（小版本只 +0.0.1）。
- 每个任务一个 commit，消息用中文，格式同 git log（`fix: ...` / `feat: ...` / `chore: ...`）。**只在本地提交，不 push、不打 tag**。
- 发版文档：`CHANGELOG.md` 加 0.6.28 小节；README / DOCKERHUB.md 只在用户可见行为变化时同步（任务 1 和任务 3 需要）。
- 验证命令（每个任务完成后都跑）：
  ```bash
  cd backend && ROSDPI_NO_JOBS=1 ASN_DB=false .venv/Scripts/python.exe -m pytest -q tests
  cd frontend && npm run build      # 含 i18n 中英键一致检查
  ```
- 中英文 i18n 键必须成对添加（`frontend/src/i18n/zh.js`、`en.js`），否则 build 失败。
- 用 Python 改含中文标点或转义的代码时，先把脚本写成文件再执行，不要用 shell heredoc（会写进控制字符）。改完扫一遍：`grep -nP '[\x00-\x08\x0b\x0c\x0e-\x1f]' -r backend/app frontend/src` 应无输出。

---

## 任务 1（P1）规则改算移出 HTTP 请求，批量归类合并成一次扫描

**问题**
- `routers/admin.py` 的 `add_rule` / `classify_domains` / `edit_rule` / `delete_rule` 在请求里同步调用 `reclass.reclassify_rule`，它要拿 `reclass._reclass_lock`。每小时的自动全量重算也拿这把锁，曾实测耗时 80 秒以上。撞上时，保存规则的请求会卡住几分钟，超过前端 120 秒超时就报错。实际上规则已经提交（`oplog.log` 先 commit 了），用户却看到失败。
- `classify_domains` 对每个 pattern 各调一次 `_reclass_rule`。最多 50 个域名就是 50 次全表扫描 `host_domain_day`（`LIKE '%.x'` 用不上索引），每次各 commit 一次，中途失败只改了一部分。

**改法**
1. `backend/app/reclass.py`
   - 新增 `rules_scope(items: list[tuple[str, str, str | None]]) -> list[tuple[where, pred, force]]`：把多条 `(kind, pattern, from_app)` 按 `from_app` 分组，同组的 domain 条件用 `or_()` 合成一个 where，cidr 条件合成一个 pred（任一网段命中即真）；port 规则忽略。
   - 新增 `reclassify_rules(engine, db, items) -> dict`：对每组调用一次现有的 `reclassify(..., where=, pred=, force=)`，合计 `bytes_moved`、`rows` 后返回。保留 `reclassify_rule` 作为单条的薄封装（现有测试在用）。
2. 新增 `backend/app/rulejobs.py`（或放进 reclass.py）：
   - 模块级 `ThreadPoolExecutor(max_workers=1, thread_name_prefix="rule-reclass")`。
   - `queue(items, user: str) -> Future`：在 worker 里用 `database.session()` 开新会话，调用 `reclassify_rules`，commit，再写一条 oplog：`action="rule_reclass"`，detail 为 `{"rules": n, "bytes_moved": x}`，失败时 `ok=False` 并带上错误摘要（≤200 字）。worker 里的异常必须捕获，不能让线程池吞掉后无声无息。
   - 记录最近一次任务状态（`running` / `done` / `error`、完成时间、bytes_moved），供下面的 GET 接口读取。
3. `backend/app/routers/admin.py`
   - 四个接口改成 commit 之后调用 `rulejobs.queue(...)`，立即返回。响应里去掉 `bytes_moved`，改为 `"reclass": "queued"`（port 规则返回 `"none"`）。
   - `classify_domains` 把 `changed` 列表一次性交给 `queue`。
   - 新增 `GET /api/rules/reclass-status`，返回第 2 步记录的最近状态。
4. 前端 `frontend/src/components/ClassifyModal.vue`、`frontend/src/views/Rules.vue`
   - 去掉这几个请求的 `timeout: 120000`，用默认值。
   - 成功提示改成「已保存，历史数据正在后台改算」。之后每 3 秒轮询一次 `reclass-status`，最多 2 分钟；状态变为 done 时刷新未识别列表，并提示改算了多少流量（沿用现有的字节格式化函数）；变为 error 时提示失败。
   - 新增 i18n 键，中英成对。
5. 测试 `backend/tests/test_debug26.py`
   - 现有断言 `bytes_moved` 的用例改成拿到 Future 后 `.result(timeout=30)` 再断言。可以让 `queue` 返回 Future，或在测试里 monkeypatch 成同步执行。
   - 新增：批量归类 3 个域名，只触发 1 次 `reclassify` 调用（monkeypatch 计数）。
   - 新增：在 `_reclass_lock` 已被占用时调用 `POST /api/rules/classify`，接口在 1 秒内返回。

**验收**：pytest 全绿；`npm run build` 通过；手测时在锁被占用的情况下保存规则，界面立即提示已保存。

---

## 任务 2（P1）`host_domain_day` 按主域名加索引，规则改算和推荐不再全表扫

**问题**
- `ruleassist.suggest` 按 `HostDomainDay.base == base` 查询，没有索引，每打开一次归类弹窗就全表扫一次。
- `reclass.rule_scope` 新增规则时（没有 `from_app`）的条件是 `domain == p OR domain LIKE '%.p'`，也是全表扫。

**改法**
1. `backend/app/models.py`：`HostDomainDay.__table_args__` 增加 `Index("ix_hdd_base_ts", "base", "ts")`。`database.add_missing_columns()` 会给已有库补建缺失的索引（第 164 行起，按 `table.indexes` 比对），请确认 MySQL 和 SQLite 都能走到这段代码，并在 tests_mysql 里断言索引存在（如果那边已有检查索引的辅助函数就复用）。
2. `backend/app/reclass.py` 的 `rule_scope`：kind 为 domain 时，算出 `b = stats.base_domain(p)`。如果 `p == b` 或 `p` 以 `"." + b` 结尾，说明 p 本身在可注册域名或更深的层级，所有命中的行主域名都是 b，此时在 where 里再加 `t.base == b` 作为预过滤。否则（p 是 `com.cn` 这类公共后缀）保持原样。
3. 测试：给 `rule_scope` 加单测，覆盖 `example.com`、`a.example.com`、`com.cn` 三种 pattern，断言生成的 SQL 里有没有 base 条件，并断言命中的行集合与改动前一致（造 5～6 行数据比对）。

**验收**：pytest 全绿；在 MySQL 上对 `SELECT ... WHERE base=? AND ...` 执行 EXPLAIN，能看到用了 `ix_hdd_base_ts`（写进 commit 说明，不强制自动化）。

---

## 任务 3（P2）换掉两个不再维护的认证库

**问题**
- `python-jose 3.3.0` 已停止维护，有公开 CVE（CVE-2024-33663 / 33664）。本项目只用 HS256 且固定了 algorithms，实际风险低，但审计工具会一直报。
- `passlib 1.7.4` 配 `bcrypt 4.2.1`，每次认证都打 `bcrypt.__about__` 告警，线上日志被刷屏。

**改法**
1. `backend/requirements.txt`：删掉 `python-jose[cryptography]`、`passlib[bcrypt]`；加 `PyJWT==2.10.1`（或当前最新 2.x）；`bcrypt` 保留。`cryptography` 如果别处还在用就保留（先 grep 确认）。
2. `backend/app/security.py`
   - `jwt.encode` / `jwt.decode` 换成 PyJWT。`decode` 必须带 `algorithms=["HS256"]`，异常改捕获 `jwt.PyJWTError`。注意 PyJWT 的 `encode` 返回 str。
   - `pwd = CryptContext(...)` 换成一个同接口的小对象，保留 `pwd.hash(pw)` 和 `pwd.verify(pw, hashed)` 两个方法，内部用 `bcrypt.hashpw` / `bcrypt.checkpw`，这样调用方不用改。bcrypt 只看前 72 字节：hash 和 verify 前统一把 utf-8 字节截到 72，与 passlib 旧行为一致。
   - 兼容性：passlib 生成的是标准 `$2b$` 哈希，`bcrypt.checkpw` 可以直接校验。**新增测试**：用 passlib 格式的固定哈希（在测试里硬编码一条 `$2b$12$...`，对应明文 `test-password-123`）验证新实现能通过。可以先在旧环境用 passlib 生成一条再贴进测试。
3. 全局 grep `jose`、`passlib`、`CryptContext`，确认没有遗漏（包括 `ros-dpi.spec` 里 PyInstaller 的 hiddenimports）。
4. CI `.github/workflows/docker-publish.yml` 的 Backend tests 步骤后加一步 `pip install pip-audit && pip-audit -r backend/requirements.txt`，失败即阻断。frontend 步骤加 `npm audit --omit=dev --audit-level=high`。
5. CHANGELOG 写明：升级后旧的登录状态会失效吗？**不应失效**（JWT 格式、HS256 和密钥都不变），请用测试证明：用旧库签出的 token 能被新代码校验。测试里直接硬编码一个用当前密钥签的 token 即可，密钥用测试夹具的固定值。

**验收**：pytest 全绿，日志里不再出现 bcrypt `__about__` 告警；`pyinstaller ros-dpi.spec` 本机能打包（可选，Windows 上打不了就在 commit 说明里注明）。

---

## 任务 4（P3）`ConnNames` 自带锁

**问题**：`backend/app/dnsmap.py` 的 `DnsMap` 已经自带锁，`ConnNames` 却没有，全靠调用方持有 `engine.lock`。目前所有调用点都核实过，但以后新增调用点很容易踩坑（0.6.2x 出现过的 `OrderedDict mutated during iteration` 就是这类问题）。

**改法**：仿照 `DnsMap`，在 `ConnNames.__init__` 里建一个 `threading.RLock()`（用 RLock，因为调用方可能已经持有 engine.lock，而 ConnNames 内部方法之间也可能互相调用），所有读写方法和 purge 用 `with self._lock`。不要改调用方。

**测试**：新增并发冒烟测试。4 个线程各执行 5000 次 put/lookup，另起一个线程循环 purge，2 秒内无异常即通过。

---

## 任务 5（P3）补社区主站异常路径的测试

现有 `test_debug16` 覆盖了正常路径。在 `backend/tests/test_share_abuse.py` 新增以下用例，只加测试；如果测出 bug，就在同一个 commit 里修掉并在说明里写清楚：
1. 伪造 `X-Forwarded-For`：最左边放一个公网地址、最右边是真实地址时，`client_ip` 取最右边的公网地址。
2. gzip 炸弹：发送一个约 50KB、解压后大于上限的 gzip body，应返回 413 或 400，且进程内存不暴涨（只断言状态码和"没有解压到底"即可，例如 monkeypatch 解压函数统计读取的字节数）。
3. 超过长度上限的 body，以及 chunked 传输：都被拒绝。
4. 未注册或令牌错误时调用 `/report`：返回 401，并且**发生在解压之前**（同样用 monkeypatch 断言解压函数没被调用）。

另外在 `docs/社区主站部署.md` 加一段「不要轮换 share_salt」：轮换后所有实例的来源网络标签作废，票数要重新攒。

---

## 任务 6（P3）仓库卫生：防止内部文件再次进公开仓库

**问题**：`审计报告-2026-10-25.md` 和 `.zcode/` 曾被提交进公开仓库，里面有内网地址和私人域名。

**现状**：git 历史已在 2026-11-16 清理（审计报告和 `.zcode/` 都已从全部提交中移除），本地这些文件仍在磁盘上、处于未跟踪状态。

**改法**
1. `.gitignore` 增加以下内容，防止再次误提交：
   ```
   /审计报告-*.md
   /wayos审计/
   .zcode/
   ```
2. **不要**删这些本地文件，不要改写 git 历史，不要 force push。

**验收**：`git status` 里看不到这几个文件；本地文件仍在。

---

## 完成后

在本文件末尾追加「执行记录」：每个任务对应的 commit SHA、测试数量、有无偏离本单之处。然后停下来等审查，不要 push。

## 执行记录（2026-11-16）

已完成 6 个任务，版本为 0.6.28。全部仅本地提交，没有 push、打 tag 或改写历史。

| 任务 | 本地 commit | 该阶段后端测试 | 验证与偏离 |
| --- | --- | --- | --- |
| 1 后台规则改算、批量扫描、页面轮询 | b809e7c | 153 通过 | 单 worker 独立会话；同组域名一次扫描；锁占用时接口仍返回；浏览器实测保存提示与完成轮询。另有下述两条补充修正。 |
| 2 主域名索引和预过滤 | b126423 | 157 通过 | SQLite 验证已有库补建索引；MySQL 测试增加索引断言。使用探针域名辨别 com.cn 等公共后缀，避免原方案 p == b 的判断误加过滤。 |
| 3 认证依赖替换与 CI 扫描 | ebba944 | 163 通过 | 固定旧 passlib 哈希和 jose token 均通过新认证；保留 cryptography 供 TLS 采集器使用。为使扫描门禁通过，另升级 FastAPI/Starlette、cryptography 和 follow-redirects。 |
| 4 ConnNames 锁 | 2b67f9f | 164 通过 | 4 个线程各 5000 次写入/查询，另有清理线程；单独测得并发用例约 0.51 秒。调用方未改。 |
| 5 社区主站异常测试 | 821071e | 172 通过 | 8 个新增用例，确认解压和流式读取均提前截止，未授权请求在读包/解压前拒绝；无需改生产代码。部署文档补充 share_salt 说明。 |
| 6 审计报告仓库卫生 | 74e0f86 | 172 通过 | 当前基线已不再跟踪报告，无需重复 rm --cached；补充根目录忽略规则。两个报告和 wayos 审计目录均被忽略，本地报告哈希未变。 |

任务 1 的额外修正分别提交，方便独立审查：

- `f65d03c`：内置 YAML 复用现有安全 C 加载器。完整回归中原有纯 Python 解析使接口 1 秒断言压线；两种解析结果完全一致，本机从约 0.324 秒降至 0.042 秒。未更改识别库数据或分类顺序。该阶段 164 项测试通过。
- `3c38145`：批量改算中后一组的可重试错误会回滚整个会话，因此改为重试整个批次。新增回归测试先失败、修正后通过；最终全部 173 项测试通过，避免前组改动在回滚后漏算。

最终验证：

- `cd backend; $env:ROSDPI_NO_JOBS='1'; $env:ASN_DB='false'; .venv/Scripts/python.exe -m pytest -q tests`：173 通过。仍有 Starlette/httpx 弃用提示及拒绝 HS384 的测试夹具密钥长度提示；没有 bcrypt __about__ 告警。
- 每个任务均执行 `cd frontend; npm run build`，最后一次构建通过，i18n 中英 1186 个键一致。
- `pip-audit -r backend/requirements.txt`：无已知漏洞。
- `npm audit --omit=dev --audit-level=high`：退出码 0，仍报告 3 项 moderate（vue-i18n 相关及 ECharts）；本轮未升级 ECharts。
- 浏览器使用隔离测试数据库和 headless Edge，持有改算锁时点击保存立即显示后台改算提示，释放锁后显示完成，无页面运行错误。
- 人工注入后台任务异常，确认状态为 error 且操作日志 ok=False。
- 控制字符检查和 `git diff --check` 均通过；审计报告 SHA256 前后一致，报告与审计目录不出现在 git status 中。

未执行的验证：本机未发现可用 MySQL 服务，因此未运行真实 MySQL tests/EXPLAIN；索引断言已留给 CI。可选的 PyInstaller 打包未执行。

环境说明：执行期间外部将分支从原基线重置到 `66836ea`（origin/main），该基线已经移除审计报告跟踪；本轮保留新基线并重新建立任务 1 提交，没有恢复旧历史。人员统计既有测试曾在测试时区跨午夜时漏查 now-120 秒的记录，未修改无关测试，窗口后完整回归通过。

认证接口核对资料：[PyJWT HS256](https://pyjwt.readthedocs.io/en/stable/usage.html)、[bcrypt 官方用法](https://github.com/pyca/bcrypt)。
