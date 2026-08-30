# 捷境自适应 AI CEO、商品工作区与官网流程实施计划

日期：2026-08-30
关联规格：`docs/superpowers/specs/2026-08-30-jiejing-workbench-contract-freeze-and-premium-ui-design.md`
批准方向：A 方案
实施原则：测试先行、小步提交、保留业务合同、部署另行确认

## 0. 文档发现与允许边界

### 已确认的事实

- `renderSaasCockpitRealWorkbench()` 当前已经输出单列聊天；真实账号看到旧三栏，是因为历史报告恢复为当前商品项目后，`mountSaasMerchantProjectStatusStrip()` 又把三栏项目状态条挂到 `#view-cockpit` 顶部。
- 普通咨询只会清除路由任务卡，不会清除这个顶层项目状态条，因此历史商品会持续挤压聊天。
- 批量能力没有删除：`#view-bulk`、`view=bulk`、`batch → bulk`、候选生成、部分成功恢复、Listing/素材交接和相关 smoke 均仍存在，只是一级导航被移除。
- 首页 `#workflow` 当前固定为素材工坊演示，而不是批准的六步商家闭环；素材演示可以保留为第 5 步的展开内容。
- 当前工作树另有三项 readiness 修改：`jiejing_saas/readiness.py`、`tools/test_jiejing_phase2_response_boundary_hardening.py`、`tools/test_jiejing_platform_trial_activation_guard.py`。本计划不得覆盖、回退或顺带提交这些修改。

### 允许复用的现有接口与模式

- AI CEO 意图与路由：`saasCeoCommandIntent()`、`primarySaasCeoRoute()`、`isSaasAiCeoPlainConsultationTurn()`，位置见 `app.js:21395-22038`。
- 当前任务数据：`state.saasMerchantProjectStatus`、`saasLatestProductWorkflowTask()`、`saasAiCeoStageCoverage()` 和 Listing draft 的 `unknown_facts/fact_conflicts/blocked_by`。
- 展开/收起无障碍模式：`renderWorkflowFeedbackWidget()` 使用的 state、`.is-open`、`aria-expanded` 与 `hidden` 合同，位置见 `app.js:21043` 及事件代理 `app.js:41541`。
- 商品任务数据：前端已加载的 `state.saasTasks`、`saasTaskById()`、`saasLatestProductWorkflowTask()`、`saasListingDraftFromReport()`；后端继续使用现有 `GET /tasks?limit=20`，不新增接口。
- 首页交互：`setupHomepageAiCeoMap()` 的键盘/焦点模式，以及 `setupHomepageMediaStudio()` 的 `aria-pressed`、`aria-live`、自动轮播停止和 reduced-motion 处理。
- 浏览器验证：现有本地静态资源拦截、`cache-control:no-store`、三视口、pageerror、console error 与横向溢出检查。

### 禁止事项

- 不重写 AI CEO 聊天、Listing、批量、素材、确认、支付退款或 eBay 适配业务逻辑。
- 不恢复 `bulk` 或 `activity` 为一级导航，不重建独立“工作记录”商家页面。
- 不把“存在历史 project/draft/report”直接等同于“AI CEO 任务侧栏必须展开”。
- 不新增 undocumented API，不为 recent 模式伪造任务、报告、商品或执行结果。
- 不重复 OAuth，不触发真实收费、退款、eBay publish、广告或其他真实平台写入。
- 不读取或输出 Secret；不把 HTTP 200、precloud 通过或部署成功表述为公开收费/真实写入证明。
- 不使用顺序复制四个前端文件宣称原子发布；生产 `apply` 必须等待新的明确部署确认。

## 1. 先建立会失败的 UI 合同

### 1.1 AI CEO 自适应布局合同

修改：

- `tools/test_jiejing_workbench_contract_freeze.py`
- `tools/test_jiejing_saas_ai_ceo_latest_reply_ui.py`
- `tools/test_jiejing_ai_ceo_operating_launch_ui.py`
- `tools/codex_jiejing_merchant_project_status_browser_smoke.js`

新增断言：

1. 普通问答的 `#view-cockpit` 不再挂载 `.saas-merchant-project-status-strip`。
2. 商品任务才输出 `data-ai-ceo-task-context`，并带有可收起按钮、`aria-expanded` 和唯一下一步。
3. 历史 draft/report 本身不能令侧栏自动展开。
4. 桌面为默认单列或任务态 68/32；平板为抽屉；手机为底部摘要与全屏详情。
5. `product/media/confirm` 继续保留原项目状态条，避免误删业务上下文。

复制模式：静态导航/函数存在检查沿用 `test_jiejing_workbench_contract_freeze.py:18-64`；真实项目 fixture、三视口和溢出检查沿用 `codex_jiejing_merchant_project_status_browser_smoke.js:341-530`。

### 1.2 商品工作区入口合同

修改：

- `tools/test_jiejing_workbench_contract_freeze.py`
- `tools/test_jiejing_media_nav_and_state_restore.py`
- `tools/test_jiejing_workflow_closure_ui.py`
- `tools/test_jiejing_bulk_partial_success_contract.py`
- `tools/codex_jiejing_bulk_media_handoff_smoke.js`

新增断言：

1. “选品与上架”内可发现“单个商品 / 批量选品与草稿 / 最近任务”。
2. `view=bulk` 与 `batch → bulk` 仍可用，但一级导航高亮 `product`。
3. recent 只显示真实 `product_workflow` 任务；打开任务恢复已有状态，不创建新任务、不重跑调研。
4. `activity/report/reports` 继续归一到 AI CEO，不能重新暴露记录中心。
5. 批量候选、部分成功、单项恢复和 Listing/素材交接合同不变。

复制模式：批量真实来源与空批次保护沿用 `test_jiejing_workflow_closure_ui.py:32-36`；暂停/恢复与无真实写入沿用 `test_jiejing_bulk_partial_success_contract.py:14-30`。

### 1.3 官网六步演示合同

修改：

- `tools/test_jiejing_homepage_maturity.py`
- `tools/codex_jiejing_homepage_maturity_browser_smoke.js`

把旧的“workflow 必须只是素材工坊”断言改为：

1. `#workflow` 依次包含 `goal/research/facts/listing/media/confirm` 六步。
2. 键盘、点击和触控可切换步骤，当前步骤同步 `aria-pressed` 与 `aria-live`。
3. 第 5 步保留当前素材画布与五个素材选项，不丢弃已批准公开素材。
4. 第 6 步明确“商家确认后经 eBay 官方连接执行”，并可返回注册/工作台入口。
5. 禁止真实账号、订单、聊天、Token、内部运行记录、项目完成度和未上线平台可用性暗示。

复制模式：键盘、reduced-motion、无 JS fallback、图片加载和三视口检查沿用 `codex_jiejing_homepage_maturity_browser_smoke.js:177-190,554-625`。

### 阶段验证

先运行上述测试并确认只因新 A 方案标记、布局行为、商品入口和六步流程尚未实现而失败。不得用删除断言或恢复旧导航让测试变绿。

## 2. 实现 AI CEO 普通全宽与条件任务侧栏

### 2.1 状态与判定

修改 `app.js`：

- 增加纯前端 helper，区分 `plain_consultation`、`active_product_task`、`explicit_project_entry` 和 `collapsed` UI 状态。
- 经营指令提交时由 `handleSaasCeoCommandSubmit()` 激活上下文；普通咨询完成时由 `updateSaasAiCeoLatestReply()` 自动收起。
- 用户手动收起只能改变 UI state，不能删除 draft、URL project、报告或后端 snapshot。
- 仅恢复历史账号时默认普通全宽；只有当前经营指令或从具体商品业务对象显式返回 AI CEO 时才展开任务侧栏。

文档依据：规格 `4.2`；现有意图分类 `app.js:21395-22038`；提交/回复入口 `app.js:22749-23007,40949-41089`。

### 2.2 DOM 投影

修改 `app.js`：

- 在 `renderSaasCockpitRealWorkbench()` 的现有聊天旁渲染 `renderSaasAiCeoTaskContextMarkup()`。
- 侧栏仅投影当前商品、当前阶段、已完成事项、缺失事实和唯一下一步；详细编辑按钮进入 `product`。
- 路由交接条继续使用 `renderSaasCeoRoutingTaskCard()`，不扩成第二个 Listing 编辑器。
- 从 `mountSaasMerchantProjectStatusStrip()` 的允许视图移除 `cockpit`，保留 `product/media/confirm`。
- 让 `syncSaasAiCeoFixedChatViewportState()` 同步 `has-task-context` 与 `is-task-context-collapsed`，避免重复绑定事件。

### 2.3 响应式与启动保护

修改 `styles.css` 与 `app.html` 的启动内联 guard：

- 大于 1100px：普通 `1fr`；任务态约 `minmax(0, 68fr) minmax(280px, 32fr)`；收起后恢复 `1fr auto`。
- 701–1100px：任务侧栏为不挤压聊天的抽屉。
- 小于等于 700px：底部任务摘要；展开后全屏详情；触控目标至少 44px。
- 清除 `.saas-merchant-project-status-strip` 在 cockpit 的旧三栏样式影响，保留其他业务页的三栏投影。
- 保持输入区、历史消息、滚动和 streaming 节点不重建。

### 阶段验证

```powershell
python tools/test_jiejing_workbench_contract_freeze.py
python tools/test_jiejing_saas_ai_ceo_latest_reply_ui.py
python tools/test_jiejing_ai_ceo_operating_launch_ui.py
python tools/test_jiejing_ai_ceo_project_trace.py
python tools/test_jiejing_current_project_archive_ui.py
node tools/codex_jiejing_merchant_project_status_browser_smoke.js
```

反模式守卫：不得修改 `general_chat` 的项目身份边界；不得清空历史项目来制造“全宽”；不得只修 CSS 而保留顶层旧状态条。

## 3. 在“选品与上架”恢复单品、批量与最近任务

### 3.1 共用内部导航

修改 `app.js` 和必要的 `app.html` fallback：

- 新建共用 `renderSaasListingModeNav(activeMode)`，固定输出“单个商品 / 批量选品与草稿 / 最近任务”。
- 在 `renderSaasListingComposerWorkspace()` 与 `renderBulkFactory()` 顶部复用同一组件。
- 保留 `view=bulk` 及 `batch → bulk` 深链；`setView()` 进入 bulk 时把一级导航高亮映射到 `product`。
- 将商家可见“批量铺货”主标题改为“批量选品与草稿”，不机械重命名稳定函数、DOM id 或兼容路由。

### 3.2 单品来源路径

- 在单品模式首屏保留 `renderSaasListingSourceIntake()`，清楚呈现“我已有货源 / 我还没有货源”。
- 已有货源继续接收链接、图片和真实规格；无货源只承接 AI CEO 选品建议，商家确认真实货源后再进入 Listing。
- 不新增“捷境提供货源”“已核验供应商”或自动编造规格的表达。

### 3.3 最近任务

修改 `app.js`：

- 新增 recent 视图投影，只筛选 `state.saasTasks` 中 `task_type === "product_workflow"` 的真实任务。
- 显示商品名、状态、更新时间、当前阶段和真实阻断；没有数据时使用商家空状态，不放示例商品。
- 打开任务时优先使用 task identity 关联已有报告，并通过 `saasListingDraftFromReport()` 恢复草稿；缺少可关联报告时只展示可证事实和下一步，不生成新任务或重跑 AI。
- 批量页旧“查看汇报”动作改为进入 product/recent 对应任务，不再跳到已归一的 activity。
- recent 使用 `?view=product&mode=recent`，不增加新的一级 view。

### 阶段验证

```powershell
python tools/test_jiejing_workbench_contract_freeze.py
python tools/test_jiejing_media_nav_and_state_restore.py
python tools/test_jiejing_workflow_closure_ui.py
python tools/test_jiejing_bulk_partial_success_contract.py
python tools/test_jiejing_current_project_archive_ui.py
node tools/codex_jiejing_bulk_media_handoff_smoke.js
```

反模式守卫：不恢复 activity 导航；不复制一套新的批量业务逻辑；不把普通任务、客服任务或内部执行记录混入最近商品任务。

## 4. 把官网 `#workflow` 改成六步公开演示

### 4.1 标记与内容

修改 `index.html`：

- 保留现有 CTA `href="#workflow"`、六个首页 section 和唯一主 CTA。
- 把 workflow 外层改为六个可选择步骤：提交目标或商品、AI CEO 调研与识别、核对商品事实、生成 Listing、生成并审核素材、商家确认执行。
- 使用统一的旅行收纳袋公开示例贯穿六步；只作为脱敏流程案例，不宣称真实销量、来源核验或执行证明。
- 把现有 `.home-material-studio` 完整嵌入第 5 步，不丢弃五个已批准素材资源。
- 第 6 步提供“免费生成第一条草稿”或进入工作台的明确返回路径。

### 4.2 交互与可访问性

- 从 `setupHomepageAiCeoMap()` 复制按钮激活和键盘模式；从 `setupHomepageMediaStudio()` 复制 `aria-pressed`、`aria-live`、用户操作停止轮播与 reduced-motion 逻辑。
- 用户主动切换步骤后停止自动切换；无 JavaScript 时六步正文仍按顺序可读。
- 保持锚点 `scroll-margin-top`，桌面、平板、手机不横向溢出。

### 4.3 商家文案

- 全部使用商家语言，不出现 readiness、provider、packet、worker、Vault、内部完成度或“工作记录”。
- 事实、营销文案与 AI 素材明确分开；图片相关统一表述为“侵权风险初筛，仍需商家核对”。
- TikTok、Amazon 等只允许使用“后续开放”，不能表现为当前可用。

### 阶段验证

```powershell
python tools/test_jiejing_homepage_maturity.py
python tools/test_jiejing_merchant_surface_guard.py
python tools/test_jiejing_merchant_copy_maturity.py
node tools/codex_jiejing_homepage_maturity_browser_smoke.js
```

反模式守卫：不嵌入真实登录工作台；不读取真实账户；不移除素材演示后留下空洞流程图；不新增第二个主要 CTA。

## 5. 视觉、可访问性和跨页面回归

### 实现

- 只在现有 premium token 上增量扩展：暖白、深墨绿、克制青绿，琥珀只用于风险和待确认。
- 普通卡片圆角不超过 8px，弹层不超过 12px；不加入暗色科技渐变、光球、伪 3D 或大面积无意义空白。
- 保证表单有 label/name/autocomplete，图标按钮有 `aria-label`，异步状态有 `aria-live`，焦点可见，动效支持 reduced-motion。
- 按 Product Owner、Beginner UX、UI Design Polish、Listing Expert、Security/Reality Checker 审视范围内页面；只修与本轮直接相关且可证的问题。

### 验证

```powershell
python tools/test_jiejing_saas_clean_settings_and_listing_ui.py
python tools/test_jiejing_listing_progressive_disclosure.py
python tools/test_jiejing_listing_single_progress.py
python tools/test_jiejing_merchant_copy_maturity.py
node tools/codex_jiejing_all_modules_clean_smoke.js
node tools/codex_jiejing_homepage_maturity_browser_smoke.js
node tools/codex_jiejing_merchant_project_status_browser_smoke.js
```

浏览器结果必须证明：无 pageerror、无 console error、三视口无横向溢出、聊天不被压窄、批量可返回、recent 不触发重跑、官网六步可用键盘和触控操作。

## 6. 前端版本与四文件原子证据

### 测试先行

扩展：

- `tools/test_jiejing_frontend_staging_config.py`
- `tools/test_jiejing_production_deploy_channel.py`
- `tools/jiejing_prepare_public_staging_bundle.py`
- `tools/jiejing_production_deploy.py`

要求：

1. `app.js` 与 `styles.css` 版本继续以规范化 UTF-8 内容 SHA-256 前 12 位结尾并共享 release family。
2. `index.html`、`app.html` 引用同一 JS/CSS 版本。
3. bundle manifest 增加 `index.html`、`app.html`、`app.js`、`styles.css` 四个独立 SHA-256；dry-run 验证四项存在且与 bundle 内容一致。
4. 回滚继续以完整不可变 release 和原子 active-link 切换为单位。

实施完成后统一计算版本并一次更新四文件引用；不得手改 `deploy/release-evidence.json` 伪造通过结果。

### 阶段验证

```powershell
python tools/test_jiejing_frontend_staging_config.py
python tools/test_jiejing_production_deploy_channel.py
python tools/test_jiejing_staging_patch_apply_contract.py
python tools/jiejing_prepare_public_staging_bundle.py
```

## 7. 完整门禁、提交与部署边界

### 本地门禁

```powershell
python tools/jiejing_secret_scan.py
node --check app.js
python tools/jiejing_precloud_deployment_gate.py
```

若 precloud 失败，先区分本轮回归、已有 readiness 工作树修改、外部证据过期和真实环境阻断；不得为了变绿打开公开收费或真实平台写入。

### 提交边界

- 每个阶段单独提交：测试合同、AI CEO、商品入口、官网演示、质量收敛、版本/manifest。
- 仅提交本计划涉及文件；三个既有 readiness 修改继续留在用户工作树，除非它们的原任务明确要求合并。
- 不提交 `output/`、日志、截图、临时浏览器依赖、`.superpowers/brainstorm/` 或任何凭证材料。

### 生产准备与部署

完成本地门禁后只运行：

```powershell
python tools/jiejing_secret_scan.py
python tools/test_jiejing_production_deploy_channel.py
python tools/jiejing_prepare_public_staging_bundle.py
python tools/jiejing_production_deploy.py --bundle $jiejingBundlePath --manifest $jiejingManifestPath --mode dry_run
```

其中两个路径变量必须直接采用上一条 bundle 生成命令输出的精确文件路径，不自行猜测。dry-run 成功后向用户单独报告代码验证、四文件 manifest、已知外部 readiness 和风险。只有获得新的明确部署确认，才允许 production `apply`。

部署后使用浏览器式 User-Agent 和 cache-busting 只读核验：

- `/health`
- `/health/deep`
- `/readiness/product-saas`
- `ops.jiejing.shop`
- `app.jiejing.shop/ops.html` 必须为 404
- `index.html`、`app.html`、`app.js`、`styles.css` 版本与 manifest 一致

状态汇报必须分别说明：网站在线、私测可用、公开收费可用、真实平台写入可用。

## 8. 完成定义

- 普通咨询打开 AI CEO 时对话占满主工作区；历史商品不会自动出现大三栏。
- 当前经营任务可展开 68/32 侧栏，侧栏可收起，平板和手机不压缩对话。
- “选品与上架”首屏可找到单个商品、批量选品与草稿、最近任务；批量业务合同不变。
- 最近任务从真实保存状态继续，不重跑调研、不伪造记录。
- 官网访客无需登录即可看懂六步闭环，第 5 步保留真实素材工坊演示，第 6 步保持商家确认边界。
- 现有 Listing、素材、支付退款、确认和 eBay 受控写入专项测试不回退。
- Secret scan、语法检查、浏览器三视口和 precloud 门禁完成，并对失败项诚实分类。
- 生产发布保持四文件版本一致与原子 release；没有新的部署确认则停在 dry-run。
