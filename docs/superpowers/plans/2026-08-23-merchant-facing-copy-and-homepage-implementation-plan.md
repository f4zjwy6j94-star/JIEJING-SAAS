# 捷境全站商家化文案与首页收敛实施计划

日期：2026-08-23  
对应规格：`docs/superpowers/specs/2026-08-23-merchant-facing-copy-and-homepage-design.md`  
当前工作树：已有多项未提交改动；实施必须基于当前工作树做定点补丁，禁止 reset、checkout 或整文件覆盖。

## Phase 0：文档发现、当前基线与允许复用模式

### 已读取的产品和工程合同

- 产品边界与验证要求：`AGENTS.md:5-20, 30-97`。
- 已确认首页、空状态与文案设计：`docs/superpowers/specs/2026-08-23-merchant-facing-copy-and-homepage-design.md:6-187`。
- UI 审查链：`docs/JIEJING_PROFESSIONAL_PROMPT_PLAYBOOK_20260628.md:50-140, 283-304, 349-356`。
- 首页现状：`index.html:3949-4661, 4788-4903, 5527-5805, 6614-6657`。
- 登录前和工作台静态骨架：`app.html:283-839, 942-1960, 3111-3125`。
- 真实 SaaS 空状态与数据恢复：`app.js:12826-12970, 16774-16997, 27567-28045, 37709-37903`。
- 设置与 owner 权限边界：`app.js:41858-42050, 43002-43360, 44943-45148`。
- 后端套餐权威目录：`jiejing_saas/billing_plan.py:16-85`。

### 当前基线证据

- `python tools/test_jiejing_merchant_surface_guard.py`：通过。
- `python tools/test_jiejing_trial_pricing_entry.py`：通过。
- `python tools/test_jiejing_merchant_onboarding_frontend.py`：通过。
- `python tools/test_jiejing_session_restore_and_ebay_ops_ui.py`：通过。
- `python tools/test_jiejing_public_staging_proxy_contract.py`：通过。
- `node --check app.js`：通过。
- `python tools/test_jiejing_saas_clean_settings_and_listing_ui.py`：当前基线失败；失败原因是测试第 71 行仍硬编码已被现有工作树删除的旧页脚句子，不是本次实施造成的新回归。

实施前先把该旧断言更新为已确认的新商家信任合同，再加入本功能 RED 断言，确保后续失败只指向新合同。

### Allowed APIs / patterns

- 复用 `visible_text()` 检查真正可见的公开页面文本：`tools/test_jiejing_merchant_surface_guard.py:126-132`。
- 复用 `function_scope()` 对客户渲染函数做作用域检查，允许 owner-only 源码保留工程词：同文件 `134-146`。
- 首页六板块使用稳定属性 `data-home-section`；唯一主行动使用 `data-home-primary-cta="merchant_first_draft_v1"`。
- 首页 CTA 复用 `setPath("trial")`、`setPlan("free")` 和 `openRealSaasEntry()`，不新造第二套注册或付款流程：`index.html:5755-5805, 6267-6657`。
- 三个公开开始方式继续使用 `opened / multi / trial`，三个公开套餐继续使用 `free / single / multi`：`tools/test_jiejing_trial_pricing_entry.py:25-31`。
- 新用户空白复用 `renderSaasAiCeoFirstRunHandoff()` 与 `renderSaasProductListingCenter()`，不另建并行工作台：`app.js:12886-12949, 37832-37903`。
- 账号数据恢复继续复用账号级快照和后端 `/stores`、`/tasks`、`/reports`、`/confirmations`、`/ai-ceo/chat-history`：`app.js:16774-16997, 27572-28045`。
- 内部权限继续只认 `platform_internal_admin === true`、`audience === "platform_internal_admin"` 且 `customer_visible === false`：`app.js:27567-27569, 43002-43015`。
- 首页样式继续放在 `index.html` 内联样式；工作台样式继续放在 `styles.css`，避免误以为修改 `styles.css` 会影响公开首页。

### Anti-pattern guards

- 不用全局 `MutationObserver` 或正则替换掩盖旧文案。
- 不清空 `saasReports`、`saasTasks`、`saasAiCeoThread`、店铺或账号级快照来制造“默认空白”。
- 不把本地演示 fixture 机械删除；只保证其在 public/merchant render path 不可达。
- 不从 owner/settings 内部证据中全局删除 Runtime、worker、provider、packet、preflight 或 Vault。
- 不在首页另造第四个套餐或第二套套餐数字。
- 不在浏览器测试中触发真实 OAuth、支付、退款、eBay 保存或发布。
- 不把本地通过、代码已部署或开关仍关闭表述成正式收费上线。

## Phase 1：修复旧测试基线并建立 RED 合同

### What to implement

1. 更新 `tools/test_jiejing_saas_clean_settings_and_listing_ui.py` 的旧页脚字面量断言，改为验证新信任边界：侵权只做初筛、高风险动作需确认、设置承载复杂配置。
2. 扩展 `tools/test_jiejing_merchant_surface_guard.py`：
   - 首页恰好 6 个 `data-home-section`。
   - 恰好 1 个 `data-home-primary-cta="merchant_first_draft_v1"`，文案为“免费生成第一条草稿”。
   - 首页不存在固定商品、`IP 初筛通过`、`侵权检测通过`、Runtime/Vault/provider 等内部词。
   - 首页包含“侵权风险初筛，仍需商家核对”。
   - `renderSaasAiCeoFirstRunHandoff` 与 public Listing scope 不含固定 SKU。
   - public Activity 不注入后台/设置控制台；普通设置不显示 owner-only 工程词。
3. 扩展 `tools/test_jiejing_merchant_onboarding_frontend.py`，要求 `merchant_blank_workbench_v1` 和“上传第一份商品资料”空状态标记。
4. 更新 `tools/codex_jiejing_public_pricing_responsive_smoke.py`：价格只统计三个 `.price-card .price`，并增加六板块、单 CTA、横向溢出、console/pageerror 和移动端可见性检查。
5. 在 `tools/codex_jiejing_first_user_browser_smoke.js` 增加四个结果合同：
   - `new_account_shows_blank_merchant_workbench`
   - `new_account_has_no_seeded_product`
   - `existing_account_restores_own_data`
   - `free_entry_created_no_payment_order`

### Documentation references

- 复制静态可见文本和函数 scope 模式：`tools/test_jiejing_merchant_surface_guard.py:126-154, 190-288`。
- 复制首次用户和既有账号恢复场景：`tools/codex_jiejing_first_user_browser_smoke.js:320-442, 518-553`。
- 复制三视口 Playwright、console/pageerror 和截图模式：`tools/codex_jiejing_public_pricing_responsive_smoke.py:11-15, 38-114`。
- 保留账号隔离合同：`tools/test_jiejing_frontend_tenant_cache_scope.py:189-227`。

### Verification checklist

- 先让新增合同按预期失败；失败项只对应六板块、单 CTA、风险措辞、固定商品或默认空状态。
- 旧基线页脚断言不再造成无关失败。
- 三路径、三套餐、会话恢复和路由保护测试保持通过。

### Anti-pattern guards

- 不因 owner 源码含工程词而让全文件扫描误报；客户渲染函数必须精确作用域检查。
- 不把隐藏 `<section>` 计入六个公开核心板块；以 `data-home-section` 为合同。
- 不运行默认指向线上环境并会创建测试账号的数据型 smoke；先使用隔离本地后端或静态路由 fixture。

## Phase 2：公开首页收敛为六板块和单主行动

### What to implement

在 `index.html` 基于已确认规格和视觉稿重组，不整文件重写：

1. 首屏：标题“把商品资料，变成商家可以核对的 eBay 草稿”；唯一填充式主按钮“免费生成第一条草稿”。顶部登录改为普通文字链接。
2. 商家得到什么：把现有固定商品工作台改成无具体商品事实的 Listing 草稿骨架，展示标题建议、属性缺口、利润参考、来源与待确认项。
3. 三步开始：提交资料、核对结果、保存未发布草稿。
4. 信任与安全边界：统一使用“侵权风险初筛，仍需商家核对”，明确真实平台写入和高风险操作需确认。
5. 经营阶段与套餐：保留 `opened / multi / trial` 与 `free / single / multi`，显示后端合同一致的套餐素材点；套餐详情直接从对应卡片 `data-*` 读取，删除公开页未使用的 `pro/team` 和第二份 `planData` 数字源。
6. 常见问题与支持：解释自动发布、自动扣费、风险初筛、店铺连接与设置入口；不增加第二个填充式 CTA。

删除公开 DOM 中仅用于旧营销展示的隐藏技术区、固定商品演示和重复流程板块。保留登录/注册 modal、身份向导及其安全行为，但不让它们成为首页核心板块。

主 CTA 点击时先调用现有 `setPath("trial")` 与 `setPlan("free")`，再进入 `openRealSaasEntry()`；登录后继续由工作台和后端合同判断免费试用，不在首页创建支付订单。

### Documentation references

- 直接复制文案和六板块顺序：设计规格 `:34-71`。
- 复制现有三路径 DOM/事件模式：`index.html:4236-4280, 5755-5805, 6618-6624`。
- 复制登录 modal 和 cookie session 边界：`index.html:4663-4723` 与 `tools/test_jiejing_saas_clean_settings_and_listing_ui.py` 的 HttpOnly session contract。
- 套餐数值以 `jiejing_saas/billing_plan.py:16-85` 为权威，并由 `tools/test_jiejing_trial_pricing_entry.py:55-77` 做前后端一致性保护。

### Verification checklist

- Phase 1 首页静态合同全部转绿。
- 主 CTA 能保留 `trial/free` 意图并打开现有注册登录流程。
- 首页没有固定商品、模型 API 配置卡、内部架构图或重复填充式按钮。
- `index.html` 桌面、平板、手机三个宽度无横向滚动、遮挡或控制台错误。

### Anti-pattern guards

- 不通过 CSS `display:none` 假装删除技术板块；客户不需要的内容从公开 DOM 移除。
- 不把“IP 防侵权”写成完成性承诺；只描述风险初筛和商家核对。
- 不复制新的套餐价格表到 JS；套餐详情读取同一页面卡片数据，并由测试对齐后端目录。

## Phase 3：登录前入口与静态工作台骨架去个人化

### What to implement

1. 将 `app.html:461-805` 的第二套长营销页收敛为紧凑访问页：品牌、价值句、登录/注册和三种开始方式；公开产品介绍以 `index.html` 为唯一营销首页。
2. 保留现有 `#entryShell`、`[data-entry-panel]`、登录 modal 和向导所需 id/data 属性，避免破坏注册、身份选择和 onboarding 持久化。
3. 把 `app.html #view-cockpit` 的固定聊天、倒流香炉附件和市场报告替换为带 `merchant_blank_workbench_v1` 的中性 mount/空状态骨架。
4. 把 `app.html #view-product` 的固定商品队列和 Listing 报告替换为无商品的中性容器；真实内容继续由 `renderSaasProductListingCenter()` 注入。
5. 将普通空状态统一为“上传第一份商品资料”“支持商品图片、货源链接或文字说明”“先生成草稿，商家核对后再决定下一步”。

### Documentation references

- 复制规格空状态三句：设计规格 `:73-90`。
- 复用现有安全空 Listing 模式：`app.js:12886-12949`。
- 保留入口路由和 `/app.html?start=app` 防护：`tools/test_jiejing_public_staging_proxy_contract.py`。
- 保留 onboarding 持久化：`tools/test_jiejing_merchant_onboarding_frontend.py:18-66`。

### Verification checklist

- 脚本未运行、延迟运行或失败时，静态 DOM 也不会露出固定商品或旧店铺数据。
- 注册、登录、跳过介绍、身份选择和向导持久化仍可用。
- `app.html` 客户可见文本不含“倒流香炉”“Backflow Incense”或个人主理人汇报。

### Anti-pattern guards

- 不删除登录和 onboarding 所需 DOM 钩子。
- 不把 `app.html` 再做成第二个完整官网。
- 不以全局字符串替换作为静态骨架去个人化手段。

## Phase 4：public 工作台默认空白并保护已有商家数据

### What to implement

1. 在 public SaaS 模式下显式清除固定演示默认选择：`activeProject`、`activeListingDraft`、`activeCockpitMarketDraft`、`publishFlow.draftId`；非 public 的本地开发 fixture 继续保留。
2. 修改 `activeListingDraft()`、`cockpitMarketProfile()`、`listingCategoryProfile()` 和 `getActiveProject()`：public 模式找不到当前账号具体数据时返回空值，不回退 `listingDraftCatalog[0]` 或 incense；非 public 模式保持既有 fixture。
3. 从 `renderSaasAiCeoFirstRunHandoff()` 源头写入已确认空状态，并把 `heroCommands`、普通政策说明和客户可见任务卡中的固定 SKU 改成商品无关表达。
4. 只有当前账号没有具体草稿、真实报告、账号级对话或任务时才显示空状态；已有账号仍先恢复账号级快照，再由后端状态覆盖。
5. public 深链接在后端状态刷新后，只解析当前账号有权限的 task/report/listing 标识；找不到或无权限时回安全空状态，不回退演示商品。

### Documentation references

- 复制 public/non-public 分支模式：`isSaasPublicMvpMode()` 与 `renderCockpitExperience()` 的现有门禁，`app.js:521-529, 37962-37966`。
- 复制真实具体商品判断：`saasListingDraftHasConcreteProduct()` 与 `renderSaasProductListingCenter()`，`app.js:19235+`、`12886-12949`。
- 复制账号级恢复：`buildSaasProtectedStateSnapshot()` / `hydrateSaasProtectedStateFromCache()`，`app.js:16774-16997`。
- 复制跨账号隔离断言：`tools/test_jiejing_frontend_tenant_cache_scope.py:189-227`。

### Verification checklist

- 新账号：空工作台、无固定商品、无支付订单。
- 已有账号：恢复自己的聊天、报告、草稿和店铺状态，不被空状态覆盖。
- 账号 A 的快照和深链接不会出现在账号 B。
- public 模式没有具体商品时，Listing、素材、报告和确认流程不生成虚假当前商品。

### Anti-pattern guards

- 不调用 `resetSaasProtectedWorkbenchState()` 制造空白。
- 不清空账号级缓存或服务器数据。
- 不让 public 空值继续落到本地 fixture 的第一个元素。
- 不为深链接猜测或新造后端 API；只使用已加载且已做租户权限过滤的状态。

## Phase 5：经营页、设置页与 owner-only 边界收敛

### What to implement

1. public 模式下停止 `renderSaasBackendPanel()` 向 `#view-activity` 注入 `renderSaasMerchantWorkbenchPanel()`；经营汇报页只保留商家报告、待处理事项和下一步。
2. 普通商家设置中的 `packet / smoke / provider / Runtime / Vault / preflight` 可见文案从对应 render function 源头改成“店铺资料 / 状态检查 / AI 服务 / 服务状态 / 密钥安全设置 / 发布前检查”。
3. 保留 owner-only `renderSaasOwnerOperationsOverviewPanel()`、`renderSaasOwnerLaunchControlPanel()` 和 `owner_ops` 标签中的原始工程证据，不把它们移到普通商家页面。
4. 停止在 public 页面启动 `applyJiejingProductModeCopy(document)` 和全 DOM `MutationObserver`。显式 `publicRuntimeText()` 只作为历史记录展示映射，不作为完成本次文案改造的证据。
5. 法律、支持、退款和风险页只做术语一致性扫描；不改变现有政策实质。

### Documentation references

- 复制术语映射：设计规格 `:92-105`。
- 复制页面权限分界：设计规格 `:115-136`。
- 保留 owner 权限模式：`app.js:27567-27569, 43002-43015, 45030-45085`。
- 经营页注入问题落点：`app.js:26925-27151, 48323-48325`。

### Verification checklist

- 普通商家经营页不出现后台状态控制台或原始工程词。
- 普通设置仍能管理账号、店铺、AI、数据、权限和账单，但不回显内部证据标识。
- owner 内部账号仍能查看完整运营证据；普通商家和未登录用户仍被拒绝。
- 全局 DOM observer 不再承担客户文案修复。

### Anti-pattern guards

- 不删除内部证据、部署门禁或 owner 运维能力。
- 不把错误原因过度简化成无法排障的“失败”；普通商家看到可行动解释，owner 区保留精确证据。
- 不把设置中心复杂配置重新搬回首页或经营工作流。

## Phase 6：响应式、可访问性与聚焦浏览器回归

### What to implement

1. 在 `index.html` 的现有 1120/680/420 断点上收敛单 CTA、六板块、三套餐和 FAQ；删除只服务旧多 CTA/固定演示的规则。
2. 在 `styles.css` 现有 1100/760/640 断点上保证紧凑登录页和空工作台不溢出；避免同时在旧黑色 hero、白色覆盖和后置覆盖三层重复修改同一组件。
3. 所有主交互保留键盘焦点、语义按钮/链接、aria-live 风险与状态提示；装饰骨架不进入可访问名称。
4. 运行本地静态 Playwright 三视口截图；首次用户行为 smoke 只指向隔离本地后端或 route fixture。

### Documentation references

- 首页现有响应式锚点：`index.html:3230-3390, 3826-3893`。
- 工作台响应式锚点：`styles.css:5315-5690, 9378-9515`。
- 复制三视口 smoke：`tools/codex_jiejing_public_pricing_responsive_smoke.py:11-15, 38-114`。
- 视觉原则：Jiejing design system 的白色、克制、证据优先和核心页面简单。

### Verification checklist

- 1266×720、820×1180、390×844 三个视口无横向滚动、文字截断或 CTA 遮挡。
- 页面无 console error、pageerror。
- Tab 顺序先到唯一主 CTA，再到登录和内容链接；焦点清晰可见。
- 空状态在手机上无需横向滚动即可上传或输入第一份资料。

### Anti-pattern guards

- 不依赖屏幕宽度隐藏第二个主 CTA；DOM 本身只能有一个主 CTA。
- 不用黑色炫技、重渐变或复杂后台视觉替代商家工作台。
- 不因截图通过而跳过交互与控制台检查。

## Phase 7：聚焦验证、专业复盘与全量门禁

### Verification commands

先运行不会触发真实支付或 eBay 写入的聚焦检查：

```powershell
node --check app.js
python tools/test_jiejing_merchant_surface_guard.py
python tools/test_jiejing_trial_pricing_entry.py
python tools/test_jiejing_merchant_onboarding_frontend.py
python tools/test_jiejing_session_restore_and_ebay_ops_ui.py
python tools/test_jiejing_frontend_settings_module_split.py
python tools/test_jiejing_saas_clean_settings_and_listing_ui.py
python tools/test_jiejing_frontend_tenant_cache_scope.py
python tools/test_jiejing_operations_console.py
python tools/test_jiejing_public_staging_proxy_contract.py
python tools/jiejing_secret_scan.py
```

本地静态页面启动后运行首页三视口 smoke。首次账号行为测试只有在隔离本地后端或明确 route fixture 下运行；不能使用默认线上地址创建测试账号。

聚焦检查通过后，再在隔离环境运行 `python tools/jiejing_precloud_deployment_gate.py`。该门禁会写 `output/.../latest.json`，不能把它当作纯只读检查，也不能把 `ready_for_paid_commercial_launch=false` 的结果描述为正式收费上线。

### Review chain

- Beginner UX Walkthrough：首屏能否在 10 秒内回答“是什么、点哪里、会不会自动发布或扣费”。
- UI Design Polish：六板块、单主行动、移动端、状态层级是否克制一致。
- Product Owner Review：是否解决商家首次理解和开始体验的问题，没有扩大支付或模型采购范围。
- Reality Checker：是否仍有固定商品、旧账号数据串入、mock/测试能力被说成正式能力。
- Proactive Principal Audit：检查 SaaS 产品适配、商家 UX、计费清晰度、租户隔离、安全信任、eBay 边界和可靠性。

### Completion criteria

- 静态、行为、浏览器和安全边界测试全部通过。
- `git diff --check` 通过，变更只包含本功能预期文件且不覆盖工作树已有改动。
- 本地完成只能表述为“代码与本地验证完成”；未部署前不能说“已上线”。

## Phase 8：受控部署与线上核验

### What to implement

1. 按仓库约束先执行 `Jiejing Staging Manual Deploy` 的 `dry_run`。
2. dry-run 通过后形成部署清单和变更摘要；在正式 `apply` 前再次取得针对该部署的明确批准。
3. 部署后只读验证：
   - `https://app.jiejing.shop/health`
   - `https://app.jiejing.shop/health/deep`
   - `https://app.jiejing.shop/readiness/product-saas`
4. 使用浏览器 User-Agent 核验公开首页、登录前入口、默认空工作台、已有账号恢复、设置和法律支持页；不点击支付、OAuth、保存草稿或发布。

### Verification checklist

- 首页线上可见 6 个核心板块和唯一主 CTA。
- 新用户路径保留免费体验意图且不创建支付订单。
- 现有账号数据恢复正常，没有固定演示商品或跨账号数据。
- health/readiness 的真实状态如实报告；若 `production_ready` 或 `can_accept_real_customers` 不是 true，不声称正式收费上线。

### Stop conditions

- dry-run、聚焦测试、健康检查或浏览器回归任一失败即停止 apply 或回滚讨论。
- 本轮不触发真实 eBay OAuth、草稿保存、发布、退款、广告、采购付款或真实支付验证。
- 部署代码不等于改变收费、素材点或真实平台写入开关。
