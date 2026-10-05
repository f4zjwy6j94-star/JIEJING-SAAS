# 捷境 → 拼嘚项目：完整项目与共享基础设施交接

日期：2026-10-06（北京时间）。用途：由项目所有者转交另一项目负责人/AI，用于相互知情、资源对齐和防止误操作。

**这是内部交接资料，不是公开宣传材料，也不是新的部署、付款、数据库迁移或资源清理授权。** 包含非秘密的服务器地址、资源标识及路径；不含密码、私钥正文、连接凭据、Cookie、模型密钥、支付密钥或 Vault 恢复材料。

本份文件是跨项目快照；捷境持续更新的唯一执行索引仍是第 3 节的 `JIEJING_CURRENT_EXECUTION_STATE.md`，不要另建一个互相矛盾的“最新状态”。

> **后续补充（10-06，已收到用户手动回传）**：先读 `D:/Codex-Verification/handoff-15dfg7.md` 和拼嘚完整原文 `D:/Codex-Verification/pindd-cross-project-handoff-20261006/PINDD_RETURN_HANDOFF_20261006.txt`。对方03:09配置摘要澄清：当前私人API用自己的本机PG `127.0.0.1:55432/pindd_private_staging`，未配置捷境托管PG；`pindd-api.jiejing.shop:8443`为内部TLS身份，暂无业务DNS/公网入口，没有拼嘚已交付的Caddy/隧道依赖。private-118在本文件原盘点之后启用。实际`/opt/jiejing-production`未被拼嘚InaccessiblePaths显式覆盖、主机安全风险详情、联合维护锁/容量和捷境PG新账期仍待核查。下文原时点记录与待回传模板保留为历史，不再据此重复询问已澄清事项；本补充不是线上复验或修复授权。

## 0. 接收方先读这八条

1. 捷境是已经部署的跨境电商 AI CEO SaaS，第一支持平台是 eBay，不是拼多多平台项目；另一“拼多/拼嘚”是独立项目。
2. 捷境正式源码已有长期仓库，不得在 Codex 任务目录重新初始化或另建平行实现。
3. 最新首版交付清单 8/8 已完成，源版本为 `1e94f2b798b158c8d34f224185151fcb95aaf912`。不要为了接手重跑三商品、OAuth、支付、完整门禁或部署。
4. **已实查两项目共用主机 `43.129.169.223`。** 捷境的 Caddy 当前占用宿主机公网 TCP 80/443；拼嘚有独立 systemd 服务和本地 PostgreSQL 测试服务。不能抢占端口、覆盖 Caddy 或重启整台机器来解决单项目问题。
5. 用户说两项目也共用数据库资源，但此次实查只能证明捷境使用托管 PostgreSQL、拼嘚有本地 PostgreSQL 服务；是否还共用托管实例/逻辑库，须由拼嘚回传配置归属确认，不能推定。
6. 用户说已经从捷境网址体系分配一个地址给拼嘚；**本轮没有核实那个准确地址及完整流量路径**。不要自行选用或改写 `app`、`ops`、根域、`pilot`，不要猜域名。
7. 捷境服务器的历史 release/private 目录、Docker 卷、证书及 Vault 材料不是垃圾。当前仍有服务引用 8 月的路径，禁止按目录日期清理。
8. 请阅读后回传第 14 节的对等资料。接收文档本身不授权修改捷境，不要求把任何密钥或数据库密码发到聊天里。

## 1. 项目目标、产品范围与不可偏移的决定

### 1.1 目标与业务主线

目标是可公开推广、收费并持续运营的 AI CEO SaaS，服务跨境电商经营。eBay 是第一接入平台，不代表所有其他平台已经支持。

主线为：

```text
商家登录与套餐 → 连接 eBay / 配置模型
  → AI CEO 对话与市场研究 → 商品事实与来源资料
  → Listing 文案、素材生成与审核 → 发布前检查
  → 确认中心 → 通过捷境的 eBay API 受控发布
  → 客服/订单辅助、复盘、后续任务与经营记录
```

- AI CEO 对话是主要工作区；商品进度是辅助，不把产品变成通用 ERP、普通聊天框或 Agent 商城。
- 对话意图及经营规划走大模型语义计划，DeepSeek/OpenAI-compatible 为现有实现方向；服务器仍负责权限、事实来源、结构校验、幂等、账单与风险确认。不能把“模型主导理解”误写成取消所有确定性安全检查，也不能让模型失败回退成关键词驱动的真实写入。
- 普通商品刊登留在捷境 → eBay API 的流程内，不改成指导商家手工填写 eBay 表单。
- 无货源商家可以研究方向，再自行找到真实货源；有货源商家提供真实资料。测试时的模拟数据不得自动变成可公开刊登的事实。
- 商品资料、图片权利、材质和尺寸冲突必须保留来源和待核状态。例如此前地漏产品资料里“硅胶”标题与 PVC 参数、详情尺寸与包装/重量字段存在区别，不能把宣传词直接提升为已验证属性。
- 真实发布、改价、库存、退款、采购、广告和敏感客服承诺保留动作时确认。某个 eBay 账号受限，不等于捷境整个平台禁止发布；发布能力开启也不等于所有账号/商品具备发布资格。

### 1.2 当前套餐与支持渠道

依据当前 `jiejing_saas/billing_plan.py`，公开入口只保留三档：

| 套餐 | 价格/周期 | 店铺 / 团队席位 | 任务 / provider job 配额 | 批量行 / 包含素材点 |
| --- | --- | --- | --- | --- |
| 免费体验 free | 0 元 / 7 天 | 1 / 1 | 20 / 30 | 0 / 0 |
| 有店铺 starter | 99 元 / 30 天 | 1 / 2 | 100 / 300 | 20 / 1000 |
| 多店铺 operator | 199 元 / 30 天 | 3 / 5 | 500 / 1500 | 200 / 3000 |

表内为代码目录值，运行时还要应用有效权益、周期和权限检查；套餐不自动授予所有真实平台写入。历史 team 方案仅兼容已有记录，不重新作为第四档售卖。

- 国内微信支付是当前国内收费主线；Stripe 国际支付逻辑保留为其他证据轨道，不把“有 Stripe 代码”当已完成国际收费。
- 本次运行时的旧 `JIEJING_BILLING_PROVIDER` 字段为 `manual_seed`，不能单看此字段判定国内微信收费关闭；公开收费就绪结果来自合成后的国内支付/权益合同，见第 2 节。
- 客服邮箱：`zongshuding4@gmail.com`，已放在公开支持/退款页面。
- “意见箱”走 `POST /product-feedback`，记录到捷境后端、在运营后台查看处理；**不会自动转发到邮箱**。公开 mailto 与内部意见箱是两条渠道。
- 不恢复独立“工作记录/运行记录”导航；历史对话、报告、Listing、素材及支持记录保留在各业务页面。

## 2. 当前进度：什么已完成，什么不能由此推断

### 2.1 已完成的首版软件交付

固定清单为 R1 运行证据可靠性、J1 登录/恢复/隔离、J2 对话/报告/商品/Listing 持久化、J3 素材审核回写与点数、J4 发布预检/确认/幂等、B1 试用/收费权益/退款保护、C1 对外文案、D1 同源部署及独立线上后验。

**8/8 = 100% 指以上首版交付，不是已实现盈利，也不是证明所有未来场景零缺陷。** 跨项目共用资源的完整隔离验收不在原八项的证明范围内。

| 证据 | 结果 |
| --- | --- |
| 干净候选完整发布门禁 | 274/274，通过；未在本交接轮重跑 |
| 最新生产 apply | 已成功，2026-10-06 本机 01:29:29 安全回执完成 |
| 源 commit | `1e94f2b798b158c8d34f224185151fcb95aaf912` |
| Git tree | `724d445bb62fe2446e00d420e909d909ad32c59b` |
| 正式发布包 | 556 文件；包名 `jiejing-public-staging-20261005-171449.zip` |
| 包 SHA-256 | `c64464afdb69970d0a2628d0e4c35de2dd39a3c5b29a3d73a15807612fe19f81` |
| 线上后验 | active/API/Worker 关键代码同源、10 个公开文件合同、后台隔离通过 |
| 上线浏览器验收 | 桌面 1440×1000、手机 390×844；套餐切换、登录入口、支持链接、匿名返回流程通过；观察到的 console/page 错误与横溢为 0 |

### 2.2 本轮新鲜只读核对

2026-10-06 本机约 02:03 的只读检查：

- `/health`：200，`ok`；`/health/deep`：200，`ready`。
- `production_ready=true`、`can_accept_real_customers=true`、`public_charging_allowed=true`、`billing_ready_for_paid_launch=true`，阻断与警告为 0。
- 广泛 `real_platform_writes_enabled=false`；受控 eBay 草稿保存/既有草稿发布配置为 true，不能把前者误解为整个发布功能关闭。
- 主站、运营站可访问；`app.jiejing.shop/ops.html` 返回 404，符合隔离要求。
- 生产仍是上述版本，7 个捷境容器运行；本轮未部署、重启、登录业务账号、操作真实付款/退款或调用 eBay 业务写入。

完整报告：`D:/Codex-Verification/jiejing-unified-closeout-20261005/UNIFIED-CLOSEOUT.md`。这些证据不等于本轮又做过真实扣款、商家成交、买家客服发送或自动经营收益验证。

## 3. 代码、工作区、版本与文档入口

以下路径在项目所有者的同一台 Windows 电脑上。外部机器不会自动拥有它们，应先确认访问环境。

| 位置 | 用途 |
| --- | --- |
| `C:/Users/57249/Documents/Codex/2026-08-24/jiejing-ebay-first-ai-ceo-saas` | 当前 Codex 任务工作区；不是产品源码仓库 |
| `C:/Users/57249/Documents/Codex/2026-04-29/hermes-agents/software-demo` | 实际源码仓库，以下简称 R |
| `C:/Users/57249/Documents/Codex/2026-04-29/hermes-agents/software-demo-release-20260924-result-first` | 已有干净发布 checkout，以下称 C；不要另建平行发布实现 |
| `R/AGENTS.md` | 全仓工作及安全约束；实际使用时展开 R |
| `R/docs/JIEJING_CURRENT_EXECUTION_STATE.md` | 唯一当前执行索引，先读顶部最新结论 |
| `R/docs/JIEJING_PRODUCTION_DEPLOY_RUNBOOK_20260823.md` | 正式部署机制；其中旧 ops 主机段落是历史说明，需结合当前索引和现场 |
| `R/docs/JIEJING_PROFESSIONAL_PROMPT_PLAYBOOK_20260628.md` | 内部产品/安全/可靠性审查规范，不是扩大操作授权 |
| `D:/Codex-Verification` | 新测试报告、截图、隔离辅助材料的首选位置 |

Git remote（已去除任何认证信息）：`https://github.com/f4zjwy6j94-star/JIEJING-SAAS.git`。

R 分支为 `codex/ai-ceo-real-merchant-loop`；R 与 C 当前 commit 均为 `1e94f2b…`，C 为 detached HEAD 且干净。R 本来就存在以下未提交内容，属于已有工作，不得 reset、clean、整批提交或强行覆盖：

```text
 M AGENTS.md
 M docs/JIEJING_CURRENT_EXECUTION_STATE.md
 M docs/superpowers/plans/2026-09-12-old-host-consolidation-implementation-plan.md
 M docs/superpowers/specs/2026-09-12-old-host-consolidation-design.md
 M docs/superpowers/specs/2026-09-24-production-vault-restore-renewal-design.md
?? docs/JIEJING_GLOBAL_REVIEW_20260916.md
?? docs/superpowers/specs/2026-09-26-homepage-classic-interaction-restoration-design.md
```

本轮交接只更新执行索引及 D 盘文档/只读证据；没有新产品代码提交或 push。不要假设远端 GitHub 已拥有最新本地提交。任务目录中的 `references/awesome-design-md` 只是外部设计参考，不是生产代码或套餐/品牌规则。

### 3.1 代码地图

| 路径（均相对 R） | 职责 |
| --- | --- |
| `index.html`、`app.html`、`app.js`、`styles.css`、`assets/` | 官网、商家工作台、业务交互和延迟加载模块；现有 HTML/CSS/JS，不是需要重建的 React 新站 |
| `ops.html`、`ops.js`、`ops.css`、`assets/jiejing-ops-panels.js` | 隔离的内部运营界面 |
| `jiejing_saas/api_server.py`、`repository.py` | SaaS HTTP、身份/租户/店铺边界、存储与业务 API |
| `jiejing_saas/ai_ceo_semantic_plan.py` | 大模型语义计划及安全合同 |
| `jiejing_saas/listing_draft_checkpoint.py`、`listing_draft_generation.py`、`listing_generation_legacy_recovery.py` | Listing 保存、版本/并发保护、生成结果和旧记录恢复 |
| `jiejing_saas/ebay_write_adapter.py`、`ebay_oauth*.py` | eBay 后端凭据边界与受控执行；不是普通前端直连 |
| `jiejing_runtime/` | 研究、标准数据包、模型、媒体、预检和任务执行；不会把商家平台 token 交给通用 agent |
| `jiejing_saas/billing_*.py` | 套餐、微信支付、权益、点数、退款与历史兼容 |
| `jiejing_saas/postgres_repository_runtime.py`、`migrations/` | psycopg/连接池、PostgreSQL 适配和显式迁移 |
| `Dockerfile.saas`、`requirements.saas.lock.txt` | 固定 Python 3.12.13 基础镜像及锁定依赖构建 |
| `deploy/`、`tools/jiejing_production_deploy.py` | 正式 Compose、Caddy/Nginx、部署与维护合同 |

## 4. 正在使用什么浏览器、怎么操作和验收

### 4.1 当前浏览器库存（本轮实际读取）

- **Codex 内置浏览器**：本会话 browser ID `2`。现有捷境标签页 ID `2`、`22`；另有腾讯云登录、旧订单和购买确认页。没有因交接而刷新、提交或关闭这些页面。
- **Chrome**：通过浏览器扩展连接，本轮 browser ID `3`，Profile `ZONGSHU`。有标签组“🔐 拼嘚证书”，其中是 `jiejing.shop` 的 Cloudflare DNS 管理页；**这是另一项目正在使用的页面，不要擅自导航、刷新、点确认或关闭**。
- **Codex MCP Apps**：本轮 browser ID `1`，无标签页。
- 浏览器及 tab ID 会变化，不是永久资源标识；有页面也不等于能证明账号仍登录。腾讯云当前已有登录页，不能假设控制台会话有效。

### 4.2 正常控制方式

目前使用 Codex 的 `mcp__cua_repl.js` / `cua` 浏览器接口。接手先 `await cua.getState()` 只读查看库存，再按实际返回的 URL/ID 选择标签页；遵守工具返回的 API 文档。不要假设名为 Chrome 的浏览器未连接，也不要从旧记录直接使用旧 tab 对象。

本会话原生桌面操作 API 不开放；有浏览器控制能力不等于可随意操作整台 Windows。需要用户本人登录、扫码、验证码、付款确认或纸质恢复材料输入时，保留相应边界。

### 4.3 自动化测试与日常页面不是同一个会话

- 最近公开上线验收使用既有 `R/output/codex-playwright-deps/node_modules/playwright-core` 配合系统 Chrome，独立无头浏览器上下文；没有复制用户 Cookie 或共用 Chrome 的登录 Profile。
- 浏览器脚本：`D:/Codex-Verification/jiejing-unified-closeout-20261005/settings-contract-fix/public-browser-smoke.cjs`。
- 仅为测试拦截两个遥测端点，业务 GET 来自真实线上；没有模拟业务响应、提交注册/支付/发布。桌面与手机截图在同目录 `verified-public-*-entry.png`。
- 专门测试窗口已关闭；用户原有内置浏览器和 Chrome 页面仍保留。这份交接不要求重复跑 UI 测试。

## 5. 腾讯云、Cloudflare 与基础设施总图

```text
Cloudflare / jiejing.shop 域名区
  ├─ jiejing.shop、pilot.jiejing.shop → app.jiejing.shop
  ├─ app.jiejing.shop → 生产机的 Caddy :80/:443
  │                      ├─ 商家 Nginx :80
  │                      └─ SaaS API :8788 ← Worker
  ├─ ops.jiejing.shop → 生产机的独立 ops Nginx → 同一 SaaS API
  └─ 分给拼嘚的具体地址与路径：等待拼嘚回传，禁止猜测

腾讯云香港生产机 43.129.169.223
  ├─ 捷境 Docker / Vault / 证据刷新
  ├─ CCN 私网 → 香港托管 PostgreSQL（捷境数据库/持久队列）
  ├─ 拼嘚 systemd 应用 127.0.0.1:8443
  └─ 拼嘚 systemd PostgreSQL 测试服务 127.0.0.1:55432

旁路：广州 COS 备份/证据、CLS 日志/监控；eBay、模型/搜索/FAL、微信支付
```

图中拼嘚两个监听点通过 unit 的 MainPID 与 `ss` 只读结果匹配；**未核实它们之间的应用连接、TLS方式、域名入口或是否同时使用托管 PostgreSQL**。

### 5.1 云资源清单及证据等级

| 资源 | 非秘密标识/信息 | 核实范围 |
| --- | --- | --- |
| 当前生产 Lighthouse | 香港；公网 `43.129.169.223`；实例 `lhins-gcoi2yb3` | IP/运行环境本轮 SSH 核实；实例 ID 来自 10-01 控制台记录 |
| 生产套餐 | 2 核 4 GB、70 GB 系统盘、30 Mbps | 规格来自既有云审计；本轮确认 2 CPU、Ubuntu 24.04.4 LTS、内存及磁盘容量；带宽/账期未重开控制台确认 |
| 托管 PostgreSQL | 香港；实例 `postgres-p2r6dxhh`；历史规格 30 GB、PG 14.23 | 当前应用 `postgres-managed` 且健康；实例/规格/版本来自既有审计，未读取 DB 连接串或查询业务行 |
| CCN | `ccn-l49vdvsd`，连接轻量供应商 VPC 与香港 `vpc-bkg6pc8k` | 09-22 控制台记录；本轮未修改或重新核查云连接列表 |
| COS | 广州 `ap-guangzhou`，桶 `jiejing-staging-backup-1423900563` | 本轮运行时明确非秘密字段确认仍引用此桶；名字含 staging 不代表可删 |
| CLS | 广州 `ap-guangzhou` | 本轮运行时非秘密配置确认 |
| CLS logset | `edee5162-3b8f-49f2-a02a-ab2eaa09a207` | 资源 ID，不是凭据 |
| CLS topic | `8bbb90fc-4492-40e3-b6f8-93504b85190c` | 资源 ID，不是凭据 |
| 旧 40 GB Lighthouse | `lhins-lxff3wj3`，旧 IP `43.129.205.244` | 10-01 已普通退订退款、当时状态待回收；不是当前生产部署目标 |
| 历史广州 SSM | 09-22 仍有 14 项历史凭据元数据 | 本轮未访问值；不能因为现在使用 Vault 就清空历史恢复相关资源 |

不要把历史计划中的 Redis/KMS 当必需采购项：当前队列为 **PostgreSQL durable queue**，生产密钥服务为 Vault Community；不为交接安装 Redis 或购买付费 KMS。

本轮容量快照：主机约 **2.11 GiB 可用内存、23.12 GiB 可用根盘空间**。它是双项目当前负载下的单次快照，不是并发容量/峰值压测结论，也不是自动扩容或清理许可。

### 5.2 账期与旧机的特别说明

- 旧 40 GB 机于 10-01 已完成普通退订、退款 21.53 元，当时可回收窗口有限；本轮没有恢复、续费或彻底销毁它。旧数据的最终全量保全/停旧完整观察并没有因此自动补为通过。
- 生产机最近记录账期为 2026-10-22 11:21:49，但来自较早控制台快照，不当当前承诺。
- 托管数据库最近能读到的旧到期时间为 2026-10-03 10:38:13，之后控制台会话需要登录；**当前应用能用不等于已核实续费成功或新到期日**。数据库续费由所有者处理，待其/拼嘚交接提供最新订单或控制台非秘密信息；不要擅自付款、重复续费或宣布已经停服。
- CCN 历史免费窗口曾显示到 2027-04-01；这只是旧快照，不是永久免费承诺。账单、优惠、现行费率另按当前官方控制台核实。

## 6. 主机上的服务、端口、网络、数据卷

### 6.1 捷境当前运行服务

生产 Compose 文件是 **`deploy/docker-compose.production-pilot.yml`**，虽然文件名有 pilot，当前正式生产也用它；不存在应改用的 `docker-compose.production.yml`。

当前实际 Compose project 名为 **`deploy`**。另一个项目必须使用自己的明确命名，不要在错误工作目录使用默认 `deploy`，也不要手工改捷境现有项目名。

| 容器 | 职责 | 暴露范围 |
| --- | --- | --- |
| `deploy-jiejing-edge-1` | Caddy 2.11.4，HTTPS/路由 | 宿主公网 TCP 80/443；容器 2019 未公开映射 |
| `deploy-jiejing-frontend-1` | Nginx 1.30.4，商家公开/私有入口 | Docker 内部 80，不占第二个宿主 80 |
| `deploy-jiejing-ops-frontend-1` | Nginx 1.30.4，独立内部运营站 | Docker 内部 80，独立网络、无宿主映射 |
| `deploy-jiejing-saas-1` | Python HTTP API | Docker 内部 8788 |
| `deploy-jiejing-worker-1` | 持久队列执行 | 无独立公网端口 |
| `deploy-jiejing-vault-1` | Vault Community 1.21.4 | 内部 8200，不公开 |
| `deploy-jiejing-vault-token-renewer-1` | 后端周期 token 续租 | 内部网络，无公网入口 |

实际网络：`deploy_jiejing_app`、`deploy_jiejing_ops`、`deploy_jiejing_secrets`。后两者在 Compose 中为 internal；不要把拼嘚容器任意加入 secrets/ops 网络。`jiejing-vault-paper-controller` 是 operator-only 工具，不是应例行启动的第八个常驻服务。

必须保护的命名卷：

- `deploy_jiejing_production_data`：`/data`，运行数据/输出；不能因主业务使用 PostgreSQL 就认作无用。
- `deploy_jiejing_production_media`：`/var/lib/jiejing/media-assets`，商品素材。
- `deploy_jiejing_production_vault_data`：Vault file backend 加密数据。
- `deploy_jiejing_caddy_data`、`deploy_jiejing_caddy_config`：HTTPS/ACME与边缘持久状态。
- 本轮还看到 Vault 及 renewer 正在引用匿名卷；匿名或长 hash 名称不表示孤立，不得全局 prune。

### 6.2 拼嘚的已观察资源（仅元数据，不替代对方交接）

| 项目 | 本轮实际读取 |
| --- | --- |
| 程序目录存在 | `/opt/pindd`（未进入读取其代码/秘密） |
| 应用 unit | `pindd-staging.service`，active/running |
| 应用 unit 路径 | `/etc/systemd/system/pindd-staging.service` |
| 应用运行用户/组 | `pindd-staging` |
| 应用工作目录 | `/var/lib/pindd/staging` |
| 应用监听 | `127.0.0.1:8443`，与 unit MainPID 对应 |
| 测试库 unit | `pindd-postgres-staging.service`，active/running |
| 测试库 unit 路径 | `/etc/systemd/system/pindd-postgres-staging.service` |
| 测试库运行用户/组 | `pindd-postgres` |
| 测试库工作目录 | `/var/lib/pindd/postgres-staging` |
| 测试库监听 | `127.0.0.1:55432`，进程 postgres，与 unit MainPID 对应 |
| 日志 namespace unit | `systemd-journald@pindd-staging.service`，active/running |

没有读取拼嘚配置文件、环境变量、数据库连接、表或业务数据。服务名中的 staging 不能被我们擅自改成 production，也不能据此判断其商业上线状态。

### 6.3 关键共享边界

- 公网 80/443 已由捷境 edge 占用。拼嘚当前是 loopback 8443，不能直接改成抢占 443。
- 捷境当前持久 `Caddyfile.production` 与 Git HEAD 内容 SHA 完全相同：`b7e651757500c8d41142ba4a2b65dbb20388a0376fdedc1dbabead480665f983`；其中未发现拼嘚域名/反代声明。
- **这不证明拼嘚没有入口**：可能另有代理、隧道、动态路由或待完成配置。若对方依赖临时修改 Caddy 的运行配置，捷境未来重建 edge 有覆盖风险；必须回传实际路由及其持久化位置后协调。
- 全局 `docker restart`、Docker daemon 重启、整机重启、UFW/安全组改变、端口释放、根域路由覆盖、实例级数据库恢复，都可能影响两个项目，不属于单项目随手修复范围。

## 7. 域名、TLS、公开页面与回调

| 地址 | 用途/本轮结果 |
| --- | --- |
| `https://jiejing.shop/` | 品牌/推广入口，当前最终跳转 `https://app.jiejing.shop/`，200 |
| `https://app.jiejing.shop/` | 官网与用户入口，200 |
| `https://app.jiejing.shop/app.html?start=app` | 商家工作台；未登录按现有逻辑返回首页登录，不是故障 |
| `https://ops.jiejing.shop/` | 独立运营入口，200；不能给普通商家开放管理权限 |
| `https://pilot.jiejing.shop/` | 兼容入口，当前最终跳转 app，200；不要分给另项目 |
| `https://app.jiejing.shop/support.html#email` | 未登录也能找到客服邮箱 |
| `/terms.html`、`/privacy.html`、`/refund-policy.html`、`/risk-disclosure.html` | app 域下公开信任与政策页 |
| `/health`、`/health/deep`、`/readiness/product-saas` | app 域只读健康/就绪接口，分别看待健康、收费与发布能力 |
| `https://app.jiejing.shop/ops.html` | 预期 404；不能为了“修链接”去开放 |

Cloudflare DNS 区为 `jiejing.shop`。本轮 DoH 查询四个已知域名均返回 Cloudflare 边缘 IP `104.21.88.176` / `172.67.151.142`；**它们不是腾讯云源站 IP，不要写回服务器配置当源站**。控制台源站记录、代理开关、TTL、WAF/Turnstile规则没有在本轮改变或完整导出。

本机系统 DNS 曾返回 `198.18.0.7` 这类代理映射，已改用 DoH交叉核实；不能把本机代理答案当真实公网源站。

Caddy 持续管理 ACME/TLS，证书数据在自己的持久卷；不要改为随意手工覆盖证书、关闭 TLS 校验、把 Cloudflare 切为 DNS-only，或为修另项目直接改全局防火墙。现有 `jiejing-production-origin-lock.service` 为 active/exited；其作用是源站访问限制，未做本轮规则重写。

当前生产 Compose 固定涉及的回调包括：

- eBay 账号删除：`https://app.jiejing.shop/webhooks/ebay/marketplace-account-deletion`
- 微信支付通知：`https://app.jiejing.shop/billing/domestic/wechat-pay/notify`
- 微信退款通知：`https://app.jiejing.shop/billing/domestic/wechat-pay/refund-notify`
- 其他 OAuth、CLS、付款和平台路径按现有 Caddy/API 精确匹配，不移动到拼嘚域名；本轮未重复 OAuth 或向任何回调发送请求。

## 8. 数据库、账号与密钥隔离

捷境实查：`JIEJING_DATABASE_ENGINE=postgres`、`JIEJING_DATABASE_ADAPTER=postgres-managed`、`JIEJING_QUEUE_PROVIDER=postgres_durable`；单进程连接池 min=1、max=8。API 与 Worker 共用后台数据体系，实例总连接数还包括其他进程/项目，不等于只有 8 个连接。

数据库连接串留在服务器后端私有环境文件中，本文不提供。逻辑数据库名、schema、账号角色、网络地址与拼嘚是否共用，待对方用**不含密码**的元数据对齐；本轮没有为了盘点而打开连接串或查询生产业务数据。

合作边界：

- 共用云账号/主机，不代表可以共用商家表、会话签名密钥或管理员账号。双方数据库/schema/角色/迁移历史要明确归属，禁止用另项目迁移器扫描或修改捷境表。
- 捷境业务侧按用户/company/store等上下文隔离；这不自动替代两套应用之间的数据库权限隔离。
- 当前源码会话 Cookie 为 `jiejing_saas_session`，设置 HttpOnly；生产 HTTPS 使用 Secure，商家 SameSite=Lax，ops Strict；刷新 Cookie 为 Strict。当前生成逻辑没有 Domain 属性，即 host-only。不要为了共域名把它改为父域 Cookie或复用签名密钥。
- eBay token、BYOK、模型/媒体/支付凭据只能在后端 Vault/env 的 `secret_ref` 边界使用。不要从浏览器导出 Cookie、把 `.env` 发到另一聊天或把密钥写入文档/Git。
- Vault 为 file backend、现有 A/B/C 纸质材料 2-of-3 恢复安排。不要重新初始化、索要材料进聊天、迁移成 Raft、把两项目 Vault 数据互相覆盖或以交接为由购买 KMS。

## 9. 捷境具体怎么部署、怎么回滚

### 9.1 已在使用的生产通道

不是浏览器上传网站，也不是直接把 R 整个目录复制到服务器。固定顺序是：

1. 保留 R 原有未提交改动，限定修改并冻结候选；使用已有干净 C checkout。
2. 同一 clean commit/tree 完整门禁，报告绑定检查有序清单、结果及源状态；专项通过不能替代完整候选证明。
3. `tools/jiejing_prepare_public_staging_bundle.py` 生成仅含代码/公开资源的白名单包与 manifest，不包含私有环境或用户数据。
4. `tools/jiejing_production_deploy.py --bundle <准确包> --manifest <准确清单> --mode dry_run` 先验证；原包/hash/同源报告必须一致。
5. 获得该批正式部署批准后，才使用同工具的 `--mode apply --confirm "deploy app.jiejing.shop production"`。
6. SSH 上传受校验包，远端 `deploy/jiejing-production-release-apply.sh` 构建候选、切换 active、验健康/维护任务，失败按原合同回滚。
7. 独立核对 active/API/Worker 与源版本、公开资产、健康/收费、ops隔离，必要时真实浏览器验收；部署成功不能代替真实业务执行。

本交接文档中的命令仅解释既有流程，**不能据此再次执行已经完成的部署**。后续共有资源变更前先完成跨项目影响核对。

### 9.2 SSH 和路径

- 已验证通道：`ubuntu@43.129.169.223:22`，本地既有 SSH key 文件 `C:/Users/57249/.ssh/jiejing_production_hk_ed25519`。
- 只记录 key 路径，绝不打开/复制/打印私钥。使用既有 known_hosts、严格校验和 BatchMode，不接受未知指纹，不关闭 host key checking。
- 本轮只读元数据通过此 SSH 通道及限定 `sudo -n` 查询取得，不需要重新登录腾讯云网页。
- active 链接：`/opt/jiejing-production/app`。
- 当前实际目录：`/opt/jiejing-production/releases/20261005T173039Z-1e94f2b798b1/app`。
- 发布清单：该 app 父目录的 `JIEJING_PRODUCTION_RELEASE_MANIFEST.txt`。本轮该清单确认 SOURCE_COMMIT；Git tree由本地候选/报告证明，不把清单缺失的 tree 字段填造。
- 当前 API/Worker/前端/edge 使用私有目录：`/opt/jiejing-production/releases/20260822-170619/private`。
- Vault/renewer 仍引用 `releases/20260822-034237` 下的配置/私有文件元数据；这是实际存活引用，**不是版本过旧就应删掉的目录**。

私有文件例：`production-compose.env`、`jiejing-saas.production.env`、`jiejing-vault-token.d/`。本文只交代位置与归属，不导出内容。

### 9.3 部署锁、回滚和共享影响

- 捷境 apply 使用 `/run/lock/jiejing-production-deploy.lock`，再取 `/run/lock/jiejing-production-maintenance.lock`。这只协调捷境自身工具，**不会自动阻止拼嘚部署同时改共享入口**；双方仍须协商同一维护窗口。
- 标准发布涉及 SaaS、Worker、商家前端、ops 前端和 edge；不是只更新静态页面。可能短暂影响共享 CPU/内存或公网连接，不承诺零停机。
- API 与 Worker 有分别固定的 rollback image hold refs；回滚按原通道恢复代码/路由/镜像，**不拿旧数据库快照覆盖新交易或另一项目数据**。
- 不运行全局 image/volume prune，不调用 `docker compose down -v`，不根据“原三品已测完”删除素材/数据库。
- GitHub staging 是另一个历史通道，按仓库要求走手动 workflow dry-run/apply；不要把旧 SSH staging 覆盖脚本用于这台当前生产机。

## 10. 备份、监控、恢复证据与需要持续维护的事项

- 维护 unit：`jiejing-production-evidence-refresh.service` / `.timer`。
- 源码调度：每天 00:17、12:17，最多 9 分钟随机抖动，Persistent=true。当前 timer enabled/active；服务器本轮显示最近 oneshot success/exit0，下一次约 10-06 12:20。
- `/opt/jiejing-production/runtime-evidence/current.json` 是脱敏运行证据快照；API/Worker把整个目录只读挂到 `/run/jiejing-production-evidence`，不要改为单文件挂载或删除。
- 维护自动更新 COS/CLS等有限证据，不等于自动做了一次数据库/Vault真实恢复演练，更不等于自动获得营收。
- 既有托管 PG 恢复演练记录：2026-09-09；Vault实际隔离恢复记录：2026-09-24。恢复新鲜度代码默认为 30 天。后续应核对是否已有更新证明并安排到期维护，不能只改时间戳或延长 TTL 让状态变绿。
- PG 控制台 09-22 历史记录：每日物理备份与日志备份存在，数据/日志保留 7 天。它不是本轮重新检查的 PITR/续费证明，恢复生产数据库需要另外确认，尤其先厘清拼嘚是否共用实例。
- Vault离机受限副本路径记录为 `C:/Users/57249/.codex/private-backups/jiejing-vault/20260924-r2`；禁止当普通附件发出，禁止打开恢复材料。目录存在/旧回执不能代替后续新鲜恢复证明。
- 旧机保全归档在 `D:/Jiejing-Host-Migration-20260912` 及新机特定备份目录；保留历史失败和成功证据，不因旧机已退款而删归档。
- 本轮观察服务器时钟比本机快约 3 分半；时间以各回执时区分别记录，不把跨主机时间差当操作耗时，不擅自调整共享主机 NTP。

本机磁盘本轮约 C: 1.66 GiB 空闲，D: 214.45 GiB、E: 260.47 GiB、F: 314.66 GiB。新报告/截图/测试产物优先 D；不要挪动整个捷境或拼嘚仓库。此前完整本地检查采用 C盘剩余1GiB停测保护，避免重复启动大任务。

## 11. 已知风险与尚未核实项：明确交接，不替别人猜

| 项目 | 已知事实 | 还需对齐 |
| --- | --- | --- |
| 同机 | 两项目服务都在当前生产机 | 并发资源预算、各自峰值、维护窗口 |
| 数据库 | 捷境托管PG；拼嘚本地PG测试服务存在 | 拼嘚是否还接托管实例、数据库/schema/role、备份责任 |
| 公网入口 | 捷境 Caddy 占80/443；拼嘚应用在8443 loopback | 拼嘚实际URL、代理/隧道路径、TLS续期、路由持久化 |
| 域名控制 | Chrome已有拼嘚证书/DNS管理页；四个捷境域名正常 | 新分配记录的准确名称/记录类型/代理状态/是否已正式切换 |
| 账期 | 服务当前健康；存在旧账期记录 | 最新PG/生产机到期日、余额与续费回执 |
| 旧机 | 10-01已普通退订 | 当前回收状态及历史未完成保全项，不重复退订 |
| 软件100% | 固定捷境首版8项交付已完成 | 不涵盖另一项目质量、跨项目全量安全审计或实际盈利 |

这份交接不把新披露的共享资源关系隐瞒在“所有一切永远没问题”里，也不擅自重开旧产品开发计划。先把资源归属对齐，有具体差异再限定修复。

## 12. 双项目共同遵守的操作规则

1. 各自只改自己的代码、进程、路径、数据库迁移和业务数据。拼嘚 unit/路径不得由捷境顺手清理，反之亦然。
2. 操作前确定真实主机、服务、端口、域名、库/schema、备份对象和恢复范围；名字含 test/staging/old 不代表无用。
3. DNS、Caddy、TLS、防火墙、整机/Docker重启、共享数据库恢复及云资源退订，须说明双项目影响与回滚安排，再取得针对动作的确认。
4. 不使用 `docker system prune`、卷删除、全库drop/truncate、整目录递归删除作为“释放空间”手段。先可恢复、限定对象，不能误删两项目。
5. 新模型生成、支付、退款、商品发布、广告或客户消息不作为交接核验动作；也不要重做 eBay OAuth。
6. 共享域名不共享 Cookie、会话密钥、数据库超级用户、支付回调、监控身份和商家权限。
7. 变更后两边分别验证自己的健康与关键链路；只有捷境页面200不能证明拼嘚正常，反之亦然。
8. 未经所有者明确要求，不给另一 Codex 聊天发送任务或控制对方浏览器。本轮由所有者转交文件，双方按回传信息协调。

## 13. 本轮证据和后续查证入口

| 证据 | 位置 |
| --- | --- |
| 本轮只读主机、容器/挂载/非秘密配置、公开GET摘要 | `D:/Codex-Verification/jiejing-cross-project-handoff-20261006/readonly-inventory.safe.json` |
| 上述安全采集器源码 | 同目录 `collect-safe-inventory.py`；仅元数据/GET，不执行部署或DB连接；证据文件以独占创建避免覆盖 |
| 拼嘚unit/端口、DoH与浏览器库存补充摘要 | 同目录 `supplement.safe.json` |
| 最新完整上线报告 | `D:/Codex-Verification/jiejing-unified-closeout-20261005/UNIFIED-CLOSEOUT.md` |
| 最新 apply/独立后验/浏览器证据 | 上述报告目录下 `settings-contract-fix/`，其中 `apply.safe.json`、`public-release-verified.safe.json`、`public-browser-corrected.safe.json`、`controlled-publish-lane.safe.json` |
| 274同源报告与标准包 | `settings-contract-fix/run-20261006-002741/`，只读复用，不覆盖旧失败报告 |
| 云资源/迁移历史 | R 当前索引中的09-22资源盘点、09-24恢复、10-01旧机退订、10-03续费页记录；历史方案不覆盖较新事实 |

`readonly-inventory.safe.json` SHA-256：`da78d105d4ccdfb53c4222b725bc10c0ebad586a231382025eb467c3a9b4bc6e`。

未完整刷新腾讯云全账号收费资源、Cloudflare全区记录、拼嘚私有配置或当前eBay账号资格。本文覆盖捷境交接所需的已识别信息，不声称已经读取“整个账号所有秘密与业务数据”。

## 14. 请拼嘚负责人按这个模板回传（不含密码/密钥）

```text
项目正式名称 / 当前阶段：
项目目标、主要功能、已完成和正在做的事情：
实际源码目录 / Git仓库 / 分支 / 当前commit / 未提交改动：
本地开发、测试、部署、回滚的标准入口：
正在使用的浏览器 / profile / 标签页占用情况：
腾讯云主机实例ID、公网/私网地址及地域：
服务名、运行用户、工作目录、监听端口、启动方式：
分配的网址（完整URL）、DNS记录、Cloudflare代理状态：
公网到应用的完整路径、Caddy/隧道等配置位置与持久化方式：
TLS证书由谁管理、如何续期、是否依赖捷境Caddy：
数据库：本地还是托管；实例ID/host/port（不含密码）：
数据库名/schema/角色名、迁移工具；是否读写捷境表：
本地55432测试库的用途、持久目录、是否还连接托管PG：
使用的Docker项目/网络/卷，或systemd unit/定时任务：
上传文件、日志、缓存、备份目录及留存/恢复方式：
CPU/内存/磁盘/DB连接预算及服务高峰：
与捷境共用的确切资源、不能动的资源和已知冲突：
近期准备做的部署/DNS/证书/数据库动作、是否需要共享入口窗口：
当前健康、验收证据、风险与待确认问题：
云服务最新到期日/续费状态（仅非秘密回执，不含支付凭据）：
```

收到对方资料后的第一步是把两份清单对齐，明确共享与独占边界。**不要在资料未对齐时自动实施迁移、换域名、重启或统一两套数据库。** 如需调整共享入口，先提出最小改动与双项目回滚/验收方案。

## 15. 给接收方AI的可直接复制启动说明

> 这是同一所有者的捷境项目交接，目的是与拼嘚协调共用服务器、数据库和域名，不是让你接管或重建捷境。请先完整阅读本文；如果需要操作捷境，再先读实际仓库AGENTS.md及当前执行索引，并只读核对变化。先回传第14节的拼嘚资源清单，尤其说明完整URL、8443应用与55432测试库的关系、是否使用托管PostgreSQL、以及公网80/443到拼嘚的流量路径。不得读取或发送密钥，不得改捷境Caddy/数据库/卷，不得根据旧文档重做已完成部署或退订。共享变更先说明双项目影响、取得动作确认，再执行。

建议使用交接与完成前验证规范；若进入实际诊断、浏览器或代码工作，再按当前可用技能和仓库规则选择。旧技能/旧设计参考不得覆盖用户最新决定。本文不是后台持续监控，也没有创建定时任务。
