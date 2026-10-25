# debug13 实施方案（修订版：接入自有 AdGuard Home）

## 调研结论（根因）

线上实测：其它+未识别 ≈ 57%（国内网络 47.9% + 未识别 9.4%），其中 2.16GB/3.91GB 流量**完全没有域名**；「未识别域名」列表总共才 6.5MB。问题不在规则库不够大，而在**拿不到域名**：

1. 88.6% 流量来自 iKuai-wan5（192.168.88.88）——爱快下游还有一层内网二次 NAT，爱快给下级客户端做 DNS 代理/缓存，RouterOS 侧看不到这些 DNS 查询；
2. 无域名目标大多是运营商 CDN 边缘（电信骨干/省 IDC/移动/联通），ASN 归属是运营商而非内容商，规则库无从判断；
3. `engine.add_dns_answer` 会把每条 DNS 应答**无条件写入全网 IP→域名表**（`engine.py:233`），与客户端在哪层 NAT 无关——所以只要拿到爱快下游 AdGuard Home 的查询日志，下游流量的 CDN 边缘 IP 就能全部按域名归类。

关于「dnsmasq-china-list 拆类别」：该列表没有类别元数据，拆不了；且 bm7/v2fly/Hagezi/UT1 都排在它之前，能被类别库认出的域名不会落到「国内网站」。有效做法是扩充前面类别库对中国域名的覆盖（A2/A3）。

## A. 分类精准度（debug13 第 1 条）

**A1. 外部数据源新增「AdGuard Home」DNS 审计源（核心改动）**

- `backend/app/integrations.py`：新增 `AdguardPoller`，复用 MosdnsPoller 的增量拉取模式（mark/断点）：
  - 登录 `POST /control/login`（用户名可空 + 密码）拿会话，403 时自动重登
  - 轮询 `GET /control/querylog?limit=500&response_status=all`（最新在前）
  - 解析每条 `answer` 字符串（`域名. TTL IN A/AAAA/CNAME 值`）→ 交给 `engine.add_dns_answer()`，与 MosDNS 源走同一条管线
- 配置与 UI：
  - 设置项新增 `adguard_url`、`adguard_password`（GET 返回时脱敏，与 ros_password 一致），两个 DNS 源可同时启用
  - `Settings.vue` 外部数据源区块增加「AdGuard Home（自有 DNS 服务器）」地址/密码输入框（中英文 i18n）
- 文档：`docs/RouterOS配置.md` + README 增补「双层 NAT（爱快）场景」——爱快下游 DHCP 的 DNS 指到 AdGuard Home、AdGuard 保持查询日志开启、ROS-DPI 填地址密码

**A2. ASN 自营内容商映射（数据活，走现有管线）**

- 从 iptoasn TSV 按 org 名生成中国自营内容商 ASN（字节/快手/网易/B站/米哈游/爱奇艺/优酷/芒果/京东/拼多多/美团等），写入 `apps.yaml` 对应应用的 `asns:`；无域名但命中自营 AS 的流量直接归入正确大类

**A3. 类别库扩充（数据+小改动）**

- `bm7_map.yaml`：盘点 blackmatrix7 尚未映射的中文应用目录补进 17 大类
- `v2fly.py CAT_MAP`：补充尚未纳入的 category-*（娱乐/新闻/电商变体等）
- `apps.yaml` 精选库：手工补高频中文应用（咪咕系、芒果TV、央视频、12306、主流银行/支付等）
- 回归样本：用线上拉的「未识别域名」+「cn_net Top IP」名单做测试逐条验证

**A4. 历史重算（新功能，让改进立刻见效）**

- 新增 `POST /api/rules/reclassify`：以 `host_domain_day`（31 天）为源，对每行 (domain, dest-ip) 用当前规则重跑分类，重写 traffic_minute/hour/day 聚合表
- 识别规则页加「重算历史分类」按钮（确认弹窗 + 进度提示）

## B. DPI 配色去重（debug13 第 2 条）

- `style.css` 三处主题块的 17 个 `--g-*` 换成互异颜色（等距色相 ≈21° 步进 + 语义微调，other/unknown 中性灰；深浅主题同值，与现状一致），并更新 `Composition.vue` 过时注释
- 饼图/矩形树图/趋势线/图例/详情弹窗读同一组变量，改一处全局生效

## 验证与发布

- 后端 pytest（含 AdGuard 日志解析的单测 + 分类回归样本），前端构建通过
- 版本 0.6.5（小版本 +0.0.1），更新 CHANGELOG，提交 push，CI 出镜像
- 192.168.88.240 `docker compose pull && up -d`，线上实例升级
- 实施时需要你提供：AdGuard Home 的地址和密码（ ROS-DPI 机器要能访问它，不通的话做个端口转发）
- 验收：配置 AdGuard 源 + 重算历史后，对比其它+未识别占比

## 预期说明（诚实边界）

DNS 链路修通后大头（CDN 边缘）会归位；但**浏览器 DoH、客户端绕过 AdGuard 直连加密 DNS** 的流量仍拿不到域名，只能靠 ASN/端口兜底。「≤3%」能否达成取决于爱快下游是否统一走 AdGuard 明文 DNS——文档里给完整配置清单。