# 捷境商家产品成熟化与运营面隔离实施计划

日期：2026-08-27  
对应规格：`docs/superpowers/specs/2026-08-27-merchant-surface-maturity-and-ops-isolation-design.md`  
实施目标：让 `app.jiejing.shop` 成为纯商家产品，让 `ops.jiejing.shop` 成为唯一内部运营入口，并以一个后端权威商品项目状态快照贯通 AI CEO、商品项目、素材、确认和工作记录。

## Phase 0：文档发现、现状基线与允许复用模式

### 已读取的产品和工程合同

- 仓库级产品、安全、验证和部署边界：`AGENTS.md:1-97`。
- 本次已确认设计：`docs/superpowers/specs/2026-08-27-merchant-surface-maturity-and-ops-isolation-design.md`。
- 商家首页和空状态基线：`docs/superpowers/specs/2026-08-23-merchant-facing-copy-and-homepage-design.md:6-145`。
- AI CEO 到真实 Listing 的工件边界：`docs/superpowers/specs/2026-08-23-ai-ceo-real-merchant-loop-design.md:40-67,115-126,171-186`。
- 正式发布通道、dry-run、双锁和回滚合同：`docs/JIEJING_PRODUCTION_DEPLOY_RUNBOOK_20260823.md:1-70`。
- 当前商家设置与 owner 动态分支：`app.js:47432-47575`。
- 当前商家端内部数据抓取：`app.js:29431-30027`。
- 当前商家设置懒加载包：`assets/jiejing-settings-panels.js:1-1300`。
- 当前 ops 页面、加载器和最小数据接口：`ops.html:13-65`、`ops.js:615-713`、`jiejing_saas/api_server.py:2452-2668`。
- 当前 Nginx 双域名和 app 端 ops 静态 404：`deploy/nginx.public-staging.conf:1-147,246-266`；正式 app 主机的宽代理还存在于 `deploy/Caddyfile.production:34-45`。
- 当前 Listing 项目标识与后端规范化：`app.js:6923-6979,11937-12104`、`jiejing_saas/repository.py:17244+`。
- 当前 AI CEO 活跃 Listing 上下文白名单：`jiejing_saas/ai_ceo_chat.py:373-469,1496,1551-1552`。
- 当前报告、任务、确认、执行和素材读取接口：`jiejing_saas/repository.py:3477-3524,5445-5499,7624-7642`。
- 当前套餐和素材点投影：`jiejing_saas/api_server.py:2621-2633,2741+`、`jiejing_saas/media_credits.py:531-569`。

### 现状的直接原因

1. `app.js` 仅凭 `platform_internal_admin` 决定是否抓取和展示上线、Vault、数据库、备份、队列、安全和支付演练数据，没有把 `app`/`ops` 访问面纳入判定。
2. `/billing/plans` 对内部管理员返回未经商家化的原始套餐对象；同一个人在商家域名会得到更多内部字段。
3. 微信零扣费演练只要求 `manage_billing`，并被商家账单页直接渲染。
4. 商家设置懒加载包物理包含内部上线和运行组件；即使 CSS 隐藏，源码与请求仍在商家面。
5. 当前各页面分别读取报告、确认、执行、素材和 Listing 数据并各自推导进度，导致同一项目出现多个完成度、多个阻断和历史项目污染。
6. `app.html`、`app.js` 与 `index.html` 仍含固定店铺、固定商品、假 KPI、预置对话和隐藏退休页面，脚本失败时也可能显示不真实状态。

### Allowed APIs / patterns

- ops 继续使用 `GET /owner/operations-overview` 与 `GET /owner/operations/{view}` 的内部管理员鉴权、`secret_exposed === false` 和白名单返回模式：`ops.js:654-673`。
- 后端请求面判断从 `_operations_console_cookie_context()` 的 Host 识别模式提取为统一 helper；生产式环境的内部接口同时要求 ops Host 和内部管理员，本地测试使用显式 fixture host，不做隐式放行。
- 后端内部接口继续复用 `platform_internal_admin` 守卫；域名/访问面隔离由 Nginx 精确路由作为第二道边界，不用前端隐藏代替。
- 商家套餐和素材点使用正向白名单投影；不根据登录者是否内部管理员改变商家响应结构。
- 新建 `jiejing_saas/merchant_project_status.py` 作为纯组合服务，不新建并行数据库真相；它在同一 evidence cutoff 内组合现有 repository 读取结果。
- 项目标识继续复用 `listing_project_identity` 正规化；新项目按完整 identity 匹配，历史兼容才允许 SKU/Offer fallback，发生冲突必须阻断。
- 当前项目状态 URL 使用 `?view=<merchant-view>&project=<opaque-id>`，只保存非敏感、不含商家事实的 opaque id。
- 浏览器 smoke 复用现有登录 fixture、console/pageerror 捕获、桌面和移动视口模式，不触发 OAuth、支付退款或 eBay 写入。
- 部署严格复用 `tools/jiejing_prepare_public_staging_bundle.py` 与 `tools/jiejing_production_deploy.py`，先 dry-run，再 apply；不手工复制 secret 或绕开 manifest。

### Anti-pattern guards

- 不用 CSS、`hidden`、运行时正则替换或角色分支假装隔离；商家 bundle、网络请求、后端投影和 app 主机路由都必须不含内部面。
- 不删除现有商家真实数据；只删除生产默认 seed，测试数据迁入 fixture。
- 不为统一状态建立第二份可编辑业务真相，不把前端本地缓存当权威。
- 不用 readiness 变绿作为盲开公开收费或真实写入的理由。
- 不重复 OAuth、真实支付、退款、只读全量同步或旧手机壳证明。
- 不在本次部署中触发 Offer 发布；现有 Offer 的最终公开发布仍需要动作时确认。

## Phase 1：建立商家面与 ops 面隔离的 RED 合同

### What to implement

1. 新增 `tools/test_jiejing_merchant_surface_isolation.py`，静态验证：
   - `app.jiejing.shop` 的 Settings 恰好五类，内部管理员也不追加 owner tab。
   - `app.js` 不抓取 `/owner/*`、Vault、数据库、备份、队列、安全和支付演练接口。
   - 商家设置 bundle 不导出上线、WAF、队列、备份或演练组件。
   - `/billing/plans` 对普通商家与内部管理员使用同一个 merchant-safe projection。
   - 商家素材点响应不含 `owner_testing_points`、内部发放来源或 ledger 细节。
2. 将以下旧测试反向改成方案 B 合同：
   - `tools/test_jiejing_saas_clean_settings_and_listing_ui.py` 不再要求商家 app 含 owner_ops。
   - `tools/test_jiejing_owner_launch_control_ui.py` 改为要求 owner launch 只在 ops。
   - `tools/test_jiejing_frontend_wechat_zero_charge_rehearsal.py` 改为商家面禁止、ops 内部管理员允许。
   - `tools/test_jiejing_frontend_settings_module_split.py` 改为商家模块禁止 paid-launch/queue/WAF/internal markers。
3. 新增 `tools/codex_jiejing_merchant_ops_surface_isolation_smoke.js`，覆盖：
   - app × 普通商家；app × 内部管理员；ops × 内部管理员；ops × 普通商家。
   - 捕获网络请求，证明 app 身份即使是内部管理员也不请求内部路由。
   - 证明 app 主机内部路径拒绝、ops 主机只允许精确白名单。

### Documentation references

- 静态客户面 scope/visible text 模式：`tools/test_jiejing_merchant_surface_guard.py:126-171,195-293`。
- ops 登录与权限 smoke 模式：`tools/test_jiejing_operations_console.py:209-250,435-513`。
- 当前 owner smoke 的不足：`tools/codex_jiejing_owner_launch_control_smoke.js:104+`。
- 当前需要反转的设置模块测试：`tools/test_jiejing_frontend_settings_module_split.py:84-134`。

### Verification checklist

- 新增隔离测试先 RED，且失败只对应当前已知泄漏。
- 原有认证、租户隔离、商家套餐测试保持通过。
- RED 阶段不访问生产、不创建账号、不触发任何平台写入。

### Anti-pattern guards

- 不做全文件关键词一刀切；ops 包内允许精确内部词，app 包和商家响应禁止。
- 不只测普通商家，必须覆盖“内部管理员登录 app 域名”。
- 不把 HTTP 403 当唯一成功：app 主机不应把内部路由暴露成可发现的正常 API。

## Phase 2：物理拆分商家与 ops 代码、数据和路由

### What to implement

1. 从 `app.js` 删除 `saasCanViewPlatformInternalFromPermissions()` 驱动的内部抓取链、owner launch/operations 渲染和相关交互。
2. 将 `assets/jiejing-settings-panels.js` 收窄为纯商家设置组件；内部组件迁入新的 `assets/jiejing-ops-panels.js`，只由 `ops.html/ops.js` 加载。
3. 在 ops 增加“上线与发布”“支付验收”“备份与恢复”“运行与安全”视图，复用现有 owner API 与 internal-admin guard。
4. 将零扣费演练迁移到 `/owner/...` 精确路由并要求 internal admin；移除/拒绝原商家路由。
5. 修改 `/billing/plans`：无论登录角色都只返回 merchant projection；内部原始套餐证据只由 ops endpoint 返回。
6. 新增素材点 merchant projection；商家只得到可用总点数、套餐/购买/赠送等可理解分类，内部测试来源和账本证据只留 ops。
7. 修改 `deploy/nginx.public-staging.conf`：
   - app host 在通用代理前精确拒绝 `/owner/`、`/vault/`、`/database/`、`/backup/`、`/queue/` 和内部安全/发布路由。
   - ops host 只扩展本次明确需要的内部 endpoint allowlist，禁止通配整个后端。
8. 同步修改 `deploy/Caddyfile.production`，从正式 app host 的宽 matcher 中移除内部前缀并显式拒绝；不得只修旧 ops/预发布主机而让正式 app 主机继续直代内部接口。
9. 为内部 owner/rehearsal 路由增加后端 ops-surface + internal-admin 双守卫；`owner/auth/login` 也只能从 ops surface 使用。

### Documentation references

- 当前内部抓取落点：`app.js:29601-30027`。
- 当前商家设置模块 exports：`assets/jiejing-settings-panels.js:1293-1299`。
- ops renderer/loadDetail 模式：`ops.js:615-673`。
- 套餐和支付演练路由：`jiejing_saas/api_server.py:2621-2633,4343-4363`。
- Nginx 双 host 基线：`deploy/nginx.public-staging.conf:1-147,246-266`；正式 Caddy app 代理：`deploy/Caddyfile.production:34-45`；已有 Host 识别：`jiejing_saas/api_server.py:10268-10270`。

### Verification checklist

- Phase 1 所有 RED 合同转绿。
- `node --check app.js`、`node --check ops.js`、新 ops module 语法检查通过。
- 普通商家和内部管理员在 app 得到相同五类 Settings、相同商家套餐 schema。
- ops 普通商家 403；内部管理员能读取迁移后的只读证据，不显示 secret 值。

### Anti-pattern guards

- 不复制业务组件形成两套真相；商家账单组件留 merchant module，内部证据组件归 ops module。
- 不通过 query parameter 或前端变量伪造 surface；公网域名和 Nginx server block 是外层边界，后端角色是内层边界。
- ops 不返回 env 原值、token、secret、私有路径内容或支付密钥。

## Phase 3：五类 Settings、生产空状态和成熟商家文案

### What to implement

1. Settings 固定为：账号与店铺、AI 与素材、店铺数据、团队权限、套餐与付款；总览变为设置页顶部摘要，不再是 tab。
2. 删除 `app.js:621-760,4284+` 的生产默认店铺、任务、商品、客服与 KPI seed；需要的样例迁到测试 fixture。
3. 将 `app.html:946-1140,2703-2717` 的预置对话、固定商品、假客服/订单/KPI 改为中性加载骨架和真实空状态。
4. 删除 `app.html:282-780` 重复营销首页；保留登录、注册、向导所需 DOM hooks。
5. 删除/改写 `app.html:2800-3058` 的“AI 找货源、1688 匹配、采购路径”过度承诺，明确：
   - 有货源商家上传链接/图片/规格，捷境整理 Listing。
   - 无货源商家得到选品建议，找到货源后再导入事实。
6. 商家角色映射为负责人、管理员、运营、素材、客服、财务、只读；不显示内部 role code。
7. AI 与素材页拆成文字分析、图片识别、联网搜索、图片生成四张能力卡；明确不支持图片的模型不会被要求猜图。
8. 统一套餐名称与解释：免费体验、有店铺、多店铺；套餐包含素材点，用完后才加购。
9. 统一风险措辞为“侵权风险初筛，仍需商家核对”。

### Documentation references

- 已确认商家文案和空状态：`docs/superpowers/specs/2026-08-23-merchant-facing-copy-and-homepage-design.md:34-145`。
- Settings 动态 tabs：`app.js:47432-47575`。
- 默认 seeds：`app.js:621-760,4284+`、`app.html:916,1104-1125,2703-2717`。
- 角色 code 映射：`app.js:26874-26887`。
- 素材点商家渲染：`app.js:37690-37763`。

### Verification checklist

- 无脚本、延迟脚本、空账号和已有账号四种状态都不出现假商品、假订单、假 KPI 或内部完成度。
- 新账号严格空白；已有账号从后端恢复自己的数据，不被清空。
- Settings 只显示五类，移动端可完整进入且焦点可见。
- 商家 DOM 不含内部测试额度、provider 美元成本、contract/version/raw boolean。

### Anti-pattern guards

- 不清空后端报告、店铺、聊天或历史工件来制造空白。
- 不删除登录、注册、onboarding 所需 id/data 属性。
- 不把“已识别图片”表述成 DeepSeek 文本模型自身能力；图片事实必须来自独立视觉能力证据。

## Phase 4：实现唯一的 merchantProjectStatus 后端快照

### What to implement

1. 先新增 `tools/test_jiejing_listing_single_progress.py`，定义一个项目只能有一个总体阶段、一个 blocker、一个 next action。
2. 新增 `tools/test_jiejing_current_project_archive_ui.py`，定义当前香炉项目与旧手机壳/历史验收记录严格隔离。
3. 新建 `jiejing_saas/merchant_project_status.py`：
   - 接收 company/store/project identity。
   - 在一个 `evidence_cutoff` 内读取现有任务、报告、素材、确认和执行结果。
   - 以完整 `listing_project_identity` 过滤，冲突时返回 blocked，不能猜测归属。
   - 输出版本化 `merchant_project_status_v1` 白名单结构，固定 `secret_exposed=false`。
4. 增加商家安全只读 endpoint，例如 `GET /stores/{store_id}/merchant-project-status?project_id=<opaque>`；沿用 store/company 租户鉴权，不接收任意 company id。
5. 八阶段固定为：资料、调研、事实、素材、Listing、未发布草稿、正式发布、记录；每阶段只有业务状态和可执行说明，不返回内部 evidence path。
6. 为当前香炉项目锁定权威 identity：SKU `JJ-INCENSE-JC2023041300002-01`、Offer `245675556011`；任何引用不一致都阻断，不自动重绑。
7. `app.js` 的 AI CEO、商品项目、素材、确认中心和工作记录全部消费同一个 snapshot；移除各页竞争性的总体进度算法。
8. `setView` 同步 `view` 和 opaque `project` 到 URL；刷新和跨页返回仍指向同一项目。

### Documentation references

- `listing_project_identity` 前后端规范化：`app.js:6942-6979`、`jiejing_saas/repository.py:17244+`。
- 后端安全白名单示例：`jiejing_saas/ai_ceo_chat.py:373-469`。
- 可复用 repository list API：`jiejing_saas/repository.py:3477-3524,5445-5499,7624-7642`。
- 当前分散前端读取：`app.js:25543,27572-28045`。
- 当前竞争性进度：`app.js:10836-10859,12070-12104,12485-12595,20274-20359,36688-36777`。
- 当前 URL 仅改 DOM：`app.js:37162-37204`。

### Verification checklist

- snapshot unit tests 覆盖无项目、进行中、事实阻断、素材待审、草稿已保存、账号限制、已发布、identity 冲突、历史污染和跨租户拒绝。
- 同一响应中 `snapshot_version`、`evidence_cutoff` 一致；各页面显示同一阶段、blocker 和 next action。
- 当前香炉项目不被旧手机壳、旧概念图或其他 Offer 的工件推进。
- AI CEO 上下文只包含 snapshot 白名单字段，不把浏览器拼装数据当后端权威。

### Anti-pattern guards

- 不新建可编辑 project-status 表，不让前端回写阶段。
- 不用“最新一条全局报告/执行结果”推断当前项目。
- 不因 Offer 存在就声称已发布；必须有对应成功执行证据。
- 不把 eBay 账号限制误报成捷境代码失败，也不隐藏它作为当前 blocker。

## Phase 5：首页、核心工作流与视觉成熟度收敛

### What to implement

1. `index.html` 保持约六板块和唯一填充主 CTA“免费生成第一条草稿”；登录为低强调文字入口。
2. 将复杂放射式 hero 改为真实、商品无关的草稿摘要：已整理、待补、下一步。
3. 套餐按免费体验 → 有店铺 → 多店铺排列，不新增第四档。
4. 从生产 DOM 物理删除隐藏退休页面、内部 Hermes/Agent/开发完成度文案和固定商品案例。
5. 商品项目页只显示一个总体阶段和一个阻断；局部字段只显示已填写/待补。
6. 素材页默认只显示当前项目当前版本；历史概念图和旧版本归档，不参与当前可发布判断。
7. 确认中心统一 action_type 白名单，按钮文案与实际动作一致；没有持久化“稍后处理”时不得伪装为该动作。
8. 工作记录默认当前项目，历史项目独立归档；不显示未经校准的置信度。

### Documentation references

- 首页既有主体：`index.html:3994-4213,4220-4528`。
- Listing 页头和多个完成度：`app.js:10836-10859,12070-12104,12485-12611,13259-13316`。
- 未发布草稿回执：`app.js:22561-22586`。
- 素材清单/成本/版本：`app.js:7642-7892,16046`。
- 确认中心：`app.js:23426-23519,42426-42430`。
- 工作记录：`app.js:42308-42408`。

### Verification checklist

- 桌面 1440、平板 1024、手机 390 视口无横向滚动、遮挡、不可达操作或 console/pageerror。
- 键盘可以到达主要导航、表单、确认按钮，焦点清楚；状态不只依赖颜色。
- 首页只有一个 filled primary CTA；app 内每页只有一个明确下一步。
- 页面所有状态均来自真实 API/空状态，不来自生产 seed。

### Anti-pattern guards

- 不追求炫技动画或大面积渐变，不降低性能和信任感。
- 不用固定香炉案例作为公开营销主视觉。
- 不把技术字段平铺给初学商家；平台 ID 和原始状态进入可展开“平台详情”。

## Phase 6：完整本地验证与主理人审计

### What to implement

1. 运行所有本次专项测试、相关历史合同、JS 语法、Secret 扫描和完整 precloud gate。
2. 使用隔离 fixture 运行浏览器 smoke，覆盖未登录、新商家、已有商家、内部管理员四类状态与桌面/移动视口。
3. 按 Product Owner、Beginner UX、Billing、Tenant Isolation、Security、Listing Expert、Reliability 和 Reality Checker 八个视角主动复核。
4. 发现低风险、范围内问题直接修复并重跑相应测试；外部账号/审核/付费条件只报告，不伪造通过。

### Verification commands

```powershell
python tools/test_jiejing_merchant_surface_isolation.py
python tools/test_jiejing_operations_console.py
python tools/test_jiejing_saas_clean_settings_and_listing_ui.py
python tools/test_jiejing_frontend_settings_module_split.py
python tools/test_jiejing_frontend_wechat_zero_charge_rehearsal.py
python tools/test_jiejing_listing_single_progress.py
python tools/test_jiejing_current_project_archive_ui.py
python tools/test_jiejing_controlled_existing_draft_publish.py
python tools/test_jiejing_controlled_existing_draft_publish_http.py
python tools/jiejing_secret_scan.py
node --check app.js
node --check ops.js
node tools/codex_jiejing_merchant_ops_surface_isolation_smoke.js
python tools/jiejing_precloud_deployment_gate.py
```

### Verification checklist

- 所有专项及完整门禁通过；任何 skipped 项必须说明原因和覆盖缺口。
- Git diff 只含方案 B 及其测试/文档，不含 output、secret、截图缓存或无关用户改动。
- 当前四种状态分别表述：网站在线、私测可用、公开收费可用、真实平台写入可用。

### Anti-pattern guards

- 不以 `HTTP 200`、代码部署或门禁数量替代公开收费/真实写入证据。
- 不为了测试全绿修改测试去接受错误产品行为。
- 不运行指向生产且会创建账号、支付单、草稿或平台写入的 smoke。

## Phase 7：生产 dry-run、apply 与发布后复核

### What to implement

1. 在干净提交上生成 bundle/manifest，记录 source commit 与 SHA-256，不包含 private env。
2. 先运行生产 `dry_run`，确认 `CANDIDATE_RELEASE_PERSISTED=0`、`ACTIVE_SWITCHED=0`、私有文件权限布尔正常。
3. dry-run 和本地门禁通过后，使用已确认的生产部署通道执行 apply；不触发真实支付、退款或 eBay 写入。
   - 新生产主机更新 app/Caddy/SaaS/Worker。
   - 旧运营主机更新 ops 静态包与精确 Nginx allowlist；先核对其 active release 和回滚路径，不能假设两台主机共用同一发布目录。
4. 部署后用浏览器式 User-Agent 检查：
   - `/health`
   - `/health/deep`
   - `/readiness/product-saas`
   - `ops.jiejing.shop`
   - `app.jiejing.shop/ops.html` 必须 404
   - app host 内部路由拒绝、ops host 精确 allowlist。
5. 只读核对 active release、容器 source labels、compose 路径和 manifest 一致；不得打印 env 内容。

### Documentation references

- 完整命令和回滚合同：`docs/JIEJING_PRODUCTION_DEPLOY_RUNBOOK_20260823.md:10-70`。
- 最低验证：`AGENTS.md:46-66`。

### Verification checklist

- health/deep 健康且 release/labels/manifest 一致。
- 商家域名无内部页面、内部请求和内部响应字段；ops 仍受内部管理员鉴权。
- readiness 如仍因外部备份/退款/eBay 审核证据为 false，原样报告，不盲开布尔。
- 部署日志和交接不含 Secret。

### Anti-pattern guards

- 不在工作树脏、dry-run 失败或 manifest 不一致时 apply。
- 不手工编辑生产 private env 让 readiness 变绿。
- 不绕过部署锁、健康检查或失败回滚。

## Phase 8：香炉项目与 eBay 边界只读复核

### What to implement

1. 从统一 project snapshot 只读确认香炉项目 identity、素材审核、Listing 事实、未发布草稿和 Offer 状态。
2. 只读读取 eBay 官方账号/Offer 结果，判断地址审核是否真正通过；不因用户已上传材料就猜测通过。
3. 若账号仍受限，项目 next action 显示等待 eBay 审核，其他 SaaS 页面保持一致。
4. 若账号已解除限制且所有商品事实/素材权利/预检通过，生成唯一最终发布确认单并停下，等待新的动作时确认。
5. 只有用户对该确认单和 Offer 再次明确确认后，才调用 exact-offer single publish adapter，并记录 item ID、offer ID、execution record 和审计证据。

### Verification checklist

- 不重跑 OAuth、支付、退款或旧手机壳流程。
- 不创建第二个香炉 Offer，不改价格/库存/政策，不做 bulk write。
- 用户登录捷境后能看到当前项目会话、调用、生成、草稿和执行记录；eBay 端状态与捷境记录一致。

### Anti-pattern guards

- 规格确认和部署确认都不等于 eBay 最终公开发布确认。
- 不把 `UNPUBLISHED` 草稿、Offer ID 或发布请求受理当成成功 Listing。
- 不在外部账号限制期间用重复 publish 重试制造噪声或重复记录。
