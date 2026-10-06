# 捷境验收留痕与 Listing AI 实施计划

日期：2026-08-28  
基线提交：`c787c47`  
对应设计：`docs/superpowers/specs/2026-08-28-owner-acceptance-trace-and-listing-assist-design.md`

## 实施目标

本轮只完成三个直接影响 eBay-first MVP 的闭环：

1. 商家在没有既有 Listing 草稿时保存商品资料，也必须写入后端并在刷新后恢复。
2. Listing 页面能够独立调用后端模型生成结构化草稿，并自动回填现有编辑器；不依赖 Codex、AI CEO 聊天正文复制、本地正则或完整 11 步演练工作流。
3. 现有业务记录继续留在各自页面，“工作记录”按同一商品项目建立商家安全索引；普通商家不接收 `owner.review` 等内部记录，平台内部管理员只看到脱敏验收痕迹。

客服没有真实买家消息时继续保持空状态。本轮只索引已经存在的客服 task/report/confirmation/execution 证据，不制造虚假消息，也不顺手实现真实 eBay 消息发送适配器。

## Phase 0：文档与现有接口发现

### 已确认事实

- `POST /stores/{store_id}/product-facts` 已能按租户持久化 `merchant_product_fact_packet` 和 `listing_project_identity`：`jiejing_saas/api_server.py:9171-9233`。
- `listing_project_identity.{key,source_report_id,candidate_id}` 已有前后端正规化和项目聚合：`jiejing_saas/repository.py:17244-17263`、`app.js:3754-3808`、`jiejing_saas/merchant_project_status.py:31-432`。
- `GET /ai-ceo/chat-history`、`GET /reports`、`GET /confirmations`、`GET /execution-results`、`GET /audit-logs` 和 store-scoped media jobs 已存在，不新建第二套工作记录表。
- Listing “先看草稿”当前只执行 `saasListingComposerDraftFromText()` 本地启发式：`app.js:7783-7851,29426-29442`。
- Listing “生成经营链路”当前固定 `adapter="jiejing-local"`，进入完整 11 步 rule-based runtime；`listing_intake` 在 `RuntimeBridge` 中没有进入任务模型输入：`app.js:30225-30289`、`jiejing_saas/runtime_bridge.py:28-100`。
- `POST /stores/{store_id}/model/value-rehearsal` 能调用真实模型，但语义和产物是受控证明，不应冒充正式 Listing 生成接口。
- 模型选择已有 account BYOK → store BYOK → company default → platform default 路由，密钥仅在后端解析：`jiejing_saas/api_server.py:11709-12058`。
- eBay 脱敏 packet、账号政策和 taxonomy metadata 已有 handoff；商品图片理解已有独立视觉事实包，文本模型不能被描述为会看图。

### Allowed APIs 与复制来源

继续使用：

- `POST /stores/{store_id}/product-facts`
- `GET /stores/{store_id}/merchant-project-status?project_id=...`
- `GET /ai-ceo/chat-history`
- `GET /reports`
- `GET /confirmations`
- `GET /execution-results`
- `GET /audit-logs`
- `GET /stores/{store_id}/media-asset-jobs`
- `_resolve_model_client_for_store(...)`
- `build_runtime_handoff_from_platform_packet(...)`
- `normalize_merchant_product_fact_packet(...)`
- `normalize_listing_project_identity(...)`
- `saasListingDraftFromReport(...)` 已支持的 `listing_handoff.listing_fields` 合同
- eBay 只读 taxonomy/account policy 适配器；不得在本轮重复 OAuth 或无意义同步

新增一个窄接口：

`POST /stores/{store_id}/listing-drafts/generate`

请求只允许：

```json
{
  "listing_project_identity": {},
  "merchant_product_fact_packet": {},
  "current_draft_fields": {},
  "source_report_id": ""
}
```

响应复用现有唯一 Listing 真相：

```json
{
  "listing_draft_generation": {
    "status": "completed|blocked",
    "report_id": "",
    "listing_project_identity": {},
    "listing_handoff": {
      "listing_fields": {},
      "merchant_product_fact_packet": {},
      "listing_readiness": {}
    },
    "missing_fields": []
  },
  "real_platform_writes_enabled": false,
  "secret_exposed": false
}
```

### Anti-pattern guards

- 不新建 `work_records`、`project_progress`、`owner_acceptance` 或第二套 Listing 表。
- 不让前端计算权威阶段、blocker 或完成度。
- 不让 Listing 页面调用 AI CEO chat 再复制回答正文。
- 不继续把本地正则、`value-rehearsal` 或 rule-based 11 步工作流称为正式 Listing AI。
- 不让模型猜材质、尺寸、重量、成本、库存、产地、发货地、图片权利、policy ID 或正式类目 ID。
- 不校验 demo Listing 文本；校验对象必须是本次实际生成内容。
- 生成草稿接口不得保存 Offer、发布 Listing 或触发真实 eBay 写入。
- 不按全局最新记录、同名商品、SKU 或 Offer 单独猜项目归属。
- 不在普通商家响应中返回内部 `owner.review` 或原始调试详情。

## Phase 1：商品资料真实持久化（RED → GREEN）

### 行为 1：无草稿时保存商品资料不会丢失

RED：新增公共界面行为测试，模拟登录商家在空 Listing 状态填写商品资料并点击保存，断言：

- 创建稳定 `listing_project_identity`；
- 调用现有 `/stores/{store_id}/product-facts`；
- 成功后显示“已保存”，刷新后从后端 report 恢复；
- 失败时保留输入并显示“未保存”，不得继续提示“已暂存”。

GREEN：复用 `saasListingComposerDraftFromText()` 只创建可编辑起点，随后统一进入已有 `persistSaasListingProductFacts(...)` 后端路径。移除无 active draft 时只写 `state.manualSourceFacts` 的假成功分支。

参考：`app.js:29263-29385,37753-37790`。

验证：专项测试、跨设备恢复、生产空状态测试、`node --check app.js`。

## Phase 2：商家安全记录投影（RED → GREEN）

### 行为 2：普通商家不会收到内部报告

RED：通过认证 HTTP 接口创建普通报告与 `owner.review`，断言普通商家 `GET /reports` 只收到商家报告；租户 A 永远拿不到租户 B 记录。

GREEN：在 API merchant projection 层过滤内部 report type；repository 保留完整历史，ops/owner 继续走受 Host + platform internal admin 保护的内部接口。

### 行为 3：验收痕迹只返回脱敏业务事件

RED：普通商家 `GET /audit-logs` 只能收到商家安全字段；平台内部管理员在 app 身份下可收到 `internal_actor=true` 的脱敏验收事件，但不能收到 user id、Secret、Token、原始请求或内部提示词。

GREEN：增加统一 merchant audit projection，按 role 扩展可见事件范围；不增加可编辑验收表，不把 ops 控制台搬回 app。

验证：HTTP 行为测试、tenant isolation、secret scan、现有 product feedback internal-actor 测试。

## Phase 3：Listing 独立真实 AI 接口（逐条 RED → GREEN）

### 行为 4：事实不足时不调用模型编造

RED：调用新接口并提交缺少来源/核心事实的 packet，断言返回 `blocked`、明确 `missing_fields`、没有模型请求、没有扣除次数、没有报告和平台写入。

GREEN：复用商品事实正规化和 `listing_readiness`，在模型前执行事实门禁。

### 行为 5：事实充分时调用账号模型并保存结构化草稿

RED：注入 `FakeLiveModelClient` 与脱敏 eBay packet，断言：

- 使用现有模型 resolver，不接收前端 key；
- 模型输入包含已确认事实、当前草稿、站点和脱敏政策/taxonomy，不含原始 token；
- 返回 strict `listing_handoff.listing_fields`；
- 保存为当前项目的 `listing.package` report/version；
- 记录 provider-reported usage；
- `real_platform_writes_enabled=false`。

GREEN：实现窄的 listing draft generation service，并把 `_resolve_model_client_for_store()` 的 Vault task scope 参数化；复用已有 provider client、metering、report persistence 和 audit。

### 行为 6：规则字段不由模型拍板

RED：模型返回错误 policy、重量、库存或类目时，断言后端以已确认事实和 eBay 脱敏数据覆盖或阻断；未知字段继续进入 `missing_fields`。

GREEN：增加严格结构解析与字段来源合并：

- 模型：标题、卖点、描述和候选建议；
- 商品事实：材质、尺寸、重量、产地、库存、成本；
- eBay 数据：policy IDs、正式 category/aspects；
- 商家当前编辑值：保留并产生新版本，不被静默覆盖。

验证：模型 service 测试、事实冲突测试、ListingPackageValidator 对实际输出测试、无真实 eBay 写入断言。

## Phase 4：Listing 页面自动回填（逐条 RED → GREEN）

### 行为 7：商家在 Listing 页面直接生成 AI 草稿

RED：浏览器行为测试点击“AI 生成 Listing 草稿”，断言只调用新 endpoint，成功后标题、描述、类目建议、item specifics 和缺失项进入现有编辑器；刷新后从后端 report 恢复。

GREEN：

- 将主按钮从 `run-model-value-rehearsal`/rule-based workflow 切到新动作；
- 保留“先看草稿”作为不计费的本地整理预览，但明确标注“资料预览”，不得称为 AI 已生成；
- 复用 `saasListingDraftFromReport(...)`，不建立第二个 draft shape；
- 每次生成形成新 report/version，不覆盖商家未保存编辑。

验证：Listing UI 专项、移动/平板/桌面 smoke、跨设备恢复、无 OAuth/写入/收费触发。

## Phase 5：项目关联与工作记录索引（逐条 RED → GREEN）

### 行为 8：AI CEO 对话可按商品项目追溯

RED：chat history sync/get 对新记录保留完整 `listing_project_identity`；切换项目时不会串入同名商品聊天。历史记录仅在 exact `market_report_id` 可验证时桥接。

GREEN：扩展 chat turn 安全白名单和当前 Listing context 持久化，不新增 chat 表。

### 行为 9：工作记录索引现有业务工件

RED：同一项目下的 chat、reports、product facts、media jobs、confirmations、executions 和已有 customer task/report 摘要可见并跳回原页面；历史项目折叠；无记录保持空状态。

GREEN：扩展现有 `merchant-project-status` 商家安全派生投影和 `renderSaasActivityCenter()`；详情仍由各业务页面读取原对象。

### 行为 10：新项目不接受模糊 identity

RED：新工件只有 key、同名商品、SKU 或 Offer 时不能自动归入当前项目；legacy 工件仅在明确兼容标记和无冲突时展示在历史归档。

GREEN：收紧 `_identity_matches()` 的新旧合同，不删除历史数据。

验证：项目聚合单测、当前/历史归档测试、浏览器跨页 snapshot、tenant cache scope。

## Phase 6：客服记录边界

### 行为 11：客服状态不冒充发送

RED：已有客服 task/report/confirmation/execution fixture 必须区分 `buyer_message`、`ai_suggested`、`merchant_edited`、`sent`、`simulated`；没有官方消息时保持空状态。

GREEN：只增加商家安全 read model 和页面状态映射。真实发送继续走确认和 execution；仓库内不存在的 eBay 消息发送适配器不在本轮发明。

验证：客服状态行为测试、敏感承诺确认门禁、空状态回归。

## Phase 7：全局商家体验审查

依次执行：

1. Listing Expert Review：标题、描述、类目、属性、成本、合规和发布缺口。
2. Beginner UX Walkthrough：新手是否知道给资料、生成、补充、审核和确认。
3. Tenant Isolation Audit：chat/report/facts/media/confirm/execution/cache 全部按 company/store/project 隔离。
4. Security Threat Model：浏览器、后端、DB、Vault、模型、eBay 与确认中心边界。
5. Reality Checker：不把本地预览、mock model、草稿或失败平台写入说成真实发布。

低风险且同范围的问题在同一轮修复；需要新 eBay 账号、真实支付或外部基础设施的项目只记录 blocker。

## Phase 8：完整验证、提交与部署

### 专项验证

- 新增的 product facts persistence HTTP/browser test。
- 新增的 merchant-safe report/audit projection test。
- 新增的 listing draft generation service/HTTP/UI test。
- 新增的 chat project identity 和 work-record index test。
- 新增的 customer state test。
- 现有 AI CEO history、current project archive、listing fact boundary、media writeback、confirmation/execution、tenant cache tests。

### 基础门禁

```powershell
node --check app.js
python tools/jiejing_secret_scan.py
python tools/jiejing_precloud_deployment_gate.py
git diff --check
```

### 部署与生产回归

1. 生成 production dry-run 与 release manifest，不打印 private env。
2. 原子部署当前提交，不修改真实 eBay/收费/退款/库存/政策。
3. 使用浏览器式 User-Agent 复核 `/health`、`/health/deep`、`/readiness/product-saas`。
4. 复核 `ops.jiejing.shop` 可用、`app.jiejing.shop/ops.html` 继续 404。
5. 用项目所有者账号做无真实平台写入的浏览器验收：商品资料保存 → Listing AI 草稿 → 页面回填 → 刷新恢复 → 工作记录跳转。
6. eBay 账号限制保持外部 blocker，不重复 OAuth、不重复正式发布。

## 完成定义

- 商家只使用捷境网站即可保存商品事实、调用 AI 生成结构化 Listing、修改并恢复草稿。
- 每个业务页面显示自己的真实记录，工作记录只做当前项目索引。
- 项目所有者看到脱敏代操作痕迹，普通商家不接收内部报告或跨租户数据。
- 本轮不产生真实 eBay 写入、真实收费、退款、广告、采购或敏感客服发送。
- 专项测试、完整门禁和生产回归均有当前提交证据；否则不得声明完成。
