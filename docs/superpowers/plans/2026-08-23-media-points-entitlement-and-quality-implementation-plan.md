# 捷境套餐素材点与图片质量实施计划

日期：2026-08-23
对应规格：`docs/superpowers/specs/2026-08-22-media-points-entitlement-and-quality-design.md`

## Phase 0：现有文档与允许复用的接口

本计划只复用仓库中已经存在并有测试基础的接口，不新造第二套支付或任务系统。

### 允许复用

- 套餐目录：`jiejing_saas/billing_plan.py:16-85` 的 `PLAN_CATALOG`；套餐商家投影复用 `build_billing_usage`。
- 素材报价与商家摘要：`jiejing_saas/media_credits.py:35-98` 的 `estimate_media_points`、`build_media_credit_summary`。
- 租户级素材点并发边界：`jiejing_saas/repository.py:6382-6401` 的 `media_credit_company_lock`。
- 素材点幂等账本：`jiejing_saas/repository.py:8589-8770` 的 `apply_media_credit_operation`。
- 微信支付成功与崩溃恢复：`jiejing_saas/billing_wechat_pay.py:1383-1484`、`1487-1552`。
- 生成前预占：`jiejing_saas/api_server.py:5681-5717` 与 `6573-6615`。
- 生成后结算/失败释放：`jiejing_saas/worker.py:663-710`、`753-781`。
- 素材工坊质量参数：`app.html:2305-2312`、`app.js:14854-14920`；后端实际映射复用 `jiejing_saas/provider_job_runner.py:206-210`。
- 素材点商家面板：`app.js:35378-35510`。

### 禁止做法

- 不让浏览器发放点数、决定最终扣点或直接操作数据库。
- 不从 GET 投影触发微信、FAL 或其他外部调用。
- 不把供应商密钥、支付密钥、原始回调或商家隐私写入账本。
- 不新增“超清”供应商质量参数；继续使用真实存在的 `low / medium / high`。
- 不在本次启用视频素材点收费；视频报价未重新核定时保持显式阻断。
- 不在代码通过前启用 `JIEJING_MEDIA_CREDIT_ENFORCEMENT_ENABLED` 或 `JIEJING_MEDIA_CREDIT_PURCHASE_ENABLED`。

## Phase 1：RED 测试与数据契约

### 实现内容

1. 扩展 `tools/test_jiejing_commercial_entitlements.py`：断言 free/starter/operator 为 0/1,000/3,000 点，三档为 20/80/250 点，并证明 `generation_tier` 是权威输入。
2. 新增聚焦测试覆盖素材点批次：套餐批次有到期时间、购买批次无到期时间、先扣最早到期套餐点、套餐到期不清除购买点。
3. 扩展微信支付测试：同一套餐订单重复通知/恢复只发放一次套餐点；素材包重复通知仍只发放一次。
4. 扩展 worker 测试：部分成功只结算实际成功图片点数，余下预占释放；全失败完整释放。
5. 扩展前端静态/浏览器契约：三档名称、单张点数、本次预计扣点与余额明细存在。

### 文档参考

- 复制现有素材点 reserve/settle/release 测试模式：`tools/test_jiejing_commercial_entitlements.py:67-134`。
- 复制现有素材包支付与退款测试模式：`tools/test_jiejing_media_credit_purchase.py`。
- 复制现有商家设置面板断言模式：`tools/test_jiejing_domestic_billing_merchant_ui.py`。

### 验证

- 新增测试在实现前按预期失败，且失败原因只指向新合同。
- 旧素材包幂等、退款和租户隔离测试仍可执行。

## Phase 2：批次账本与兼容迁移

### 实现内容

1. 在 repository 初始化迁移中新增 `media_credit_buckets` 表，字段至少包含租户、来源类型、来源引用、发放点数、剩余点数、预占点数、到期时间、状态和安全 JSON。
2. 为现有聚合余额建立兼容批次：首次需要分账时，将尚未映射的正余额归入不过期的 `legacy` 批次；不删除或覆盖旧账本。
3. `grant` 按 `details.credit_source` 创建或幂等复用套餐/购买批次。
4. `reserve` 按“即将到期套餐点 -> 其他套餐点 -> 用户购买点 -> legacy”顺序分配，并把分配明细安全写入预占账本 JSON。
5. `settle` 按实际点数减少对应批次余额并释放未结算预占；`release` 仅释放预占。
6. 读取余额或新操作前，在租户锁内惰性关闭已到期套餐批次，只减少对应套餐剩余点，不碰购买点。
7. 商家摘要新增 `included_points`、`purchased_points`、`included_expires_at`，聚合 `available_points` 保持向后兼容。

### 文档参考

- 复制现有租户锁和幂等哈希模式：`repository.py:6382-6401`、`8611-8638`。
- 复制现有 JSON 安全清洗：`apply_media_credit_operation` 中的 `_redact_secret_like`。
- 不改变 `media_credit_accounts` 和 `media_credit_ledger` 的既有字段语义。

### 验证

- 同一租户并发/重复操作不重复发放或扣减。
- A 租户不能读取或消费 B 租户批次。
- 旧正余额迁移一次且总余额不变。
- 负余额退款防滥用合同保持有效。

## Phase 3：套餐支付赠点与报价规则

### 实现内容

1. 将 `PLAN_CATALOG` 的 `media_points_included` 更新为 free=0、starter=1000、operator=3000；legacy team 保持 0，避免重新公开已移除档位。
2. `build_billing_usage` 从选中套餐读取真实 `media_points_included`，不再硬编码 0。
3. 删除注册流程中的旧“300欢迎素材点”发放；免费体验继续保留20次托管AI调用，但不赠FAL素材点。
4. 微信套餐支付确认后，使用订单号作为来源引用和幂等键发放套餐点；批次到期时间使用已验证并持久化的套餐权益截止时间。
5. `recover_paid_wechat_pay_entitlement` 使用同一幂等键补齐可能的崩溃窗口。
6. `estimate_media_points` 以 `generation_tier` 为权威字段，兼容旧 `image_quality`：draft/low=20、standard/medium=80、high_quality/high=250。
7. 视频请求返回 `chargeable=false` 与明确阻断码；强制扣点开启时不进入供应商队列。

### 文档参考

- 套餐权益截止时间复用微信已持久化的 `entitlement_active_until`，不得由浏览器提供。
- 赠点沿用素材包支付成功的 `apply_media_credit_operation(... operation_type="grant")` 模式，但 `credit_source=plan_included`。

### 验证

- 付款成功、重复回调、恢复三条路径最终都只有一个套餐批次。
- free 不生成套餐批次；starter/operator 批次分别为1,000/3,000点。
- 套餐到期后购买点仍完整可用。

## Phase 4：商家界面与报价透明度

### 实现内容

1. 素材工坊三档改成：快速样图·20点/张、标准图·80点/张、高清图·250点/张。
2. 根据张数和质量实时显示预计扣点；文字明确“服务端提交时再次校验，失败自动退点”。
3. 素材点面板将总余额拆成“套餐内”和“已购买”，并显示套餐点到期时间。
4. 套餐卡写明单店版含1,000点、多店铺版含3,000点，免费体验不承诺生图。
5. 点数不足时沿用 HTTP 402 后端结果，引导用户到设置与账户的素材点购买区域，不自动创建支付订单。

### 文档参考

- 视觉和文案遵循 `jiejing-design-system`：白色、克制、商家语言、复杂账本留在设置。
- 复用现有 `renderSaasMerchantMediaCreditsPanel`，不新建第二个素材钱包页面。

### 验证

- `node --check app.js`。
- 桌面和移动端素材工坊、套餐卡、设置素材点面板截图检查。
- 页面无控制台错误，档位切换和张数切换可实时更新预计点数。

## Phase 5：聚焦验证与全量门禁

### 验证命令

1. 运行新增/修改的素材点、微信支付、套餐与 worker 聚焦测试。
2. 运行 `python tools/jiejing_secret_scan.py`。
3. 运行 `node --check app.js`。
4. 运行相关浏览器 smoke。
5. 运行 `python tools/jiejing_precloud_deployment_gate.py`。
6. 运行 `git diff --check` 并检查只包含本功能的预期文件。

### 审查链

- Billing And Pricing Review：套餐包含内容、扣点、耗尽后行为清楚。
- Beginner UX Walkthrough：首次使用者知道本次预计扣多少，不担心误扣费。
- Security Threat Model：服务端权威、租户锁、幂等、密钥不落账本。
- Reliability And Launch Readiness：失败退点、重复通知、迁移和回滚有证据。
- Reality Checker：区分本地通过、已部署但开关关闭、真实收费开关已打开三种状态。

## Phase 6：受控部署与开关边界

### 实现内容

1. 先部署代码与数据迁移，保持素材点购买和强制扣点开关为 false。
2. 验证 `/health`、`/health/deep`、`/readiness/product-saas`，再用测试商家检查余额只读投影和报价。
3. 受控验证套餐订单幂等赠点、生成成功结算、失败释放和购买点不受套餐到期影响。
4. 只有上述证据全部通过，才形成单独的生产开关批准包。

### 明确停止点

- 本计划的代码部署不等于公开素材包收费开放。
- 未获得针对生产开关的单独确认，不设置购买或强制扣点为 true，不创建真实素材包订单，不触发真实FAL验证消费。
- 任一关键测试失败即保持开关关闭并回报失败码，不用旧证据代替。
