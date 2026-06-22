# 捷境上线前经营安全系统补强规格 - 2026-05-26

本文把“AI CEO 聊天入口”升级为“eBay-first 经营操作系统”的上线前补强规格。目标不是多加页面，而是让每次选品、刊登、发布、改价、库存、客服、复盘都有来源、风控、确认、执行和审计回流。

## 0. 总原则

- 捷境仍是 eBay-first AI CEO SaaS，不做通用 ERP、通用 Agent 市场或普通聊天机器人。
- AI 可以调研、起草、预填、比价、生成素材任务、学习客服、计算利润、生成确认包和复盘报告。
- 真实发布、改价、库存、下架、退款、广告、政策、采购付款、敏感客服承诺必须进入决策中心。
- 每个商家可见建议必须标注来源：eBay 官方 packet、历史订单、财务记录、公开搜索、模型推理、人工输入。
- 没有来源就写缺口和下一步，不能用旧演示商品或模型猜测填空。

## 1. 经营安全系统

### 1.1 发布体检报告

发布前必须生成独立的“发布体检报告”，不能只写在日志里。报告必须在 Listing 页面和决策中心都可见。

必查项目：

- 类目：categoryId 是否来自 eBay Taxonomy/Metadata 或人工确认；类目与商品是否相关。
- Item specifics：必填字段、推荐字段、变体字段、兼容性字段是否齐全。
- 图片：至少 1 张主图；图片来源、授权、尺寸、白底、变体图、实物一致性。
- 文案：标题、描述、禁售词、夸大宣传、医疗/安全/认证承诺、兼容性表述。
- IP / VeRO：品牌词、Logo、第三方图片、复制文案、compatible/fits 表述、疑似仿品。
- GPSR / 法规：EU/北爱销售时检查制造商、安全负责人、产品安全、合规政策字段。
- 库存位置：merchantLocationKey、地址字段、实际发货城市、tracking 起点一致性。
- Business policies：paymentPolicyId、fulfillmentPolicyId、returnPolicyId 是否可用且适合商品。
- 卖家额度：刊登额度、金额额度、类目限制、账号状态、out-of-stock control 建议。
- 预计费用：insertion fee、final value fee、international fee、广告预算、可能订阅分摊。
- 利润：售价、采购、物流、退货预留、汇率、平台费、广告费后的贡献毛利。

输出结构：

- 体检总分：`pass / warning / blocked`
- 发布阻断项：必须先修复，不能进真实发布
- 风险提示项：允许进确认中心，但商家必须看见
- 来源记录：每一项来自哪里
- 决策中心动作：发布、改价、补图、改 policy、调整库存等

### 1.2 eBay Inventory API 发布约束

捷境必须把 eBay Inventory API 的真实发布约束产品化：

- offer 要关联 marketplace、SKU、location、category、quantity、price、business policies。
- Inventory item 在 publish 前必须有 SKU、condition、product.title、description、aspects、imageUrls 等。
- payment、fulfillment、return 三类 business policy 是发布 active listing 前的硬要求。
- 有些字段 createOffer 时可选，但 publishOffer 时变成必需；发布体检必须按 publish 标准检查。

### 1.3 Inventory API 生命周期责任

Inventory API 创建的 listing 后续不能随意让用户去 Seller Hub 改。捷境一旦发布，就必须负责完整生命周期：

- 改价：进入决策中心，执行后写 execution_result。
- 改库存：进入决策中心，检查 out-of-stock 规则。
- 下架/withdraw：进入决策中心，保留原因和审计。
- 补图/改描述：进入决策中心，重新跑 IP/VeRO/法规/费用影响检查。
- 失败恢复：超时、502、连接中断后，先按 SKU/offerId/listingId 查平台状态，再决定补记或重试。

## 2. 发布后驾驶舱

真实发布不是结束，而是进入“发布后驾驶舱”。

### 2.1 自动复盘窗口

- 1 小时：发布是否成功、是否可搜索、费用是否异常、图片/类目/政策是否有平台警告。
- 24 小时：曝光、点击、收藏、加购/询盘、售出、客服消息、费用、初步利润。
- 7 天：销售转化、退货风险、广告消耗、库存健康、是否调价、补图、暂停或扩量。

### 2.2 复盘输出

每次复盘生成工作记录：

- 指标：impressions、clicks、watchers、sold、fees、profit、messages、returns。
- 结论：继续、改价、补图、改标题、改库存、暂停、下架。
- 来源：eBay official packet / orders / finances / traffic reports / model analysis。
- 需确认动作：真实改价、库存、下架、广告、政策、客服敏感承诺仍进决策中心。
- 记忆回流：成功/失败原因进入商家级经营记忆和平台规则记忆。

## 3. AI CEO 经营操作系统

每条 AI CEO 指令必须输出统一“经营指令包”，而不是只返回聊天文本。

字段：

- 目标：用户要达成的经营结果。
- 计划：拆成市场、货源、Listing、素材、客服、财务、确认、执行、复盘。
- 来源：用到的 packet、订单、财务、公开搜索、人工输入、模型推理。
- 风险：平台规则、IP、利润、履约、客服、账号额度。
- 需确认动作：所有真实写入和高风险承诺。
- 执行结果：任务、报告、确认项、execution_result、失败原因。
- 复盘：1h/24h/7d 的后续动作和经营记忆。

UI 表达：

- AI CEO 顶部仍保持像对话一样直接输入指令。
- 回复区展示“经营指令包时间线”，不是一堆机器人段落。
- 每条建议旁边显示来源标签和风险标签。
- 高风险动作显示为决策中心按钮，不在 AI CEO 回复里直接执行。

## 4. 费用与利润大脑

没有利润模型，AI CEO 只是“发品”；捷境必须做经营利润判断。

### 4.1 Listing 级贡献毛利

每个 Listing 建立 `listing_profit_snapshot`：

- 售价
- eBay insertion/final value/international fee
- 广告预算或 promoted listing 费
- 采购成本
- 国内段物流
- 国际物流
- 包材成本
- 汇率
- 退货/破损/退款预留
- 店铺订阅/工具成本分摊
- 净利润金额
- 净利率
- 保本价
- 建议价格带

### 4.2 决策规则

- 低于商家利润底线：不能直接发布，只能进入确认中心。
- 毛利为负：默认阻断。
- 费用缺失：显示“利润不可确认”，不能写成可盈利。
- 汇率敏感：跨币种采购必须记录汇率时间戳。

## 5. IP / VeRO / 内容合规

捷境要把 IP 风控变成卖点。

检查维度：

- 品牌词：是否真实品牌商品；是否误用品牌吸流。
- 兼容性：只允许 `fits/for/compatible with` 类清晰表达，不能暗示授权或原厂。
- 图片来源：自拍、商家上传、eBay catalog、授权图库、生成图；第三方来源必须有授权。
- 文案来源：不能复制竞品、官网、目录文案；模型输出也要原创改写。
- Logo：图片和详情页不能加入未授权 Logo。
- 禁售词/夸大词：医疗、安全、认证、万能、保证效果、绝对化承诺。
- VeRO 记忆：每次平台拒绝、删除、警告都沉淀到平台规则记忆。

输出：

- `ip_risk_score`
- `brand_terms_detected`
- `image_source_status`
- `compatibility_claim_review`
- `blocked_terms`
- `safe_rewrite_suggestions`
- `needs_manual_legal_review`

## 6. GPSR / 法规字段

当销售或发货覆盖 EU/北爱时，发布体检要启用 GPSR/法规检查：

- manufacturer name/address/contact
- responsible person / EU representative
- product safety documents
- warning labels
- product compliance custom policies
- take-back policies
- 类目是否要求 Hazmat、EPR、product compliance 字段

缺少条件必需字段时，状态为 blocked，不进入真实发布。

## 7. 测试发布清理计划

真实测试品必须有产品化清理流程：

- 清理动作：end/withdraw listing、删除或停用 offer、必要时库存归零。
- 边界：清理也是真实写入，必须进决策中心。
- 证据：保留 listingId、offerId、SKU、执行结果、平台响应摘要。
- 审计：不能删除历史记录；只能标记 cleaned / withdrawn / archived。
- 复盘：记录测试品为什么发布、为什么清理、学到的平台限制。

## 8. 失败知识库

每次平台拒绝都必须沉淀为可复用规则：

- seller quota / monthly listing amount limit
- category restriction
- missing item specifics
- policy mismatch
- location mismatch
- GPSR required
- IP/VeRO complaint
- fee too high / profit below floor
- duplicate SKU / offer exists
- ambiguous 502 with platform-side success

知识库用途：

- 下次发布体检提前命中。
- AI CEO 解释失败原因。
- 对商家形成“这个店铺/类目踩过什么坑”的记忆。
- 形成捷境护城河，而不是一次性错误日志。

## 9. 商家级经营记忆

不是聊天历史，而是经营偏好和约束：

- 利润底线
- 可接受价格带
- 常用供应商与可靠度
- 常踩坑类目
- 常批准/拒绝动作
- 发货地与物流偏好
- 退货策略
- IP 风险偏好
- 模型输出风格反馈
- 真实发布、改价、库存、客服承诺的历史结果

AI CEO 每次计划都要读取这些记忆，但不能绕过确认中心。

## 10. 可信来源 UI

每个建议旁边显示来源标签：

- `eBay 官方 packet`
- `eBay 订单/履约`
- `eBay 财务记录`
- `eBay policy/account`
- `公开搜索`
- `商家输入`
- `供应商资料`
- `模型推理`
- `历史经营记忆`

颜色语义：

- 绿色：官方或商家确认来源。
- 蓝色：公开来源。
- 灰色：模型推理。
- 黄色：缺口或待确认。
- 红色：阻断或高风险。

## 11. 正式商业化计费

正式 SaaS 不能只靠手动套餐。必须接 Stripe/Paddle 之一，支持：

- 真实 plan IDs
- signed webhook
- subscription created/updated/deleted
- invoice paid / payment failed
- past_due / unpaid / canceled 访问控制
- 欠费停用和恢复
- 发票
- 用量计费
- quota 重算

### 11.1 推荐套餐

基础订阅 + 用量包：

- 月费：店铺数、团队席位、AI CEO 额度、标准报告额度。
- 用量：真实发布次数、市场调研次数、素材生成、客服学习、深度财务分析。
- 高阶：托管式发布风控、跨店铺策略、专属模型记忆、专属合规词库。

### 11.2 欠费策略

- `past_due`：允许读取历史和导出，停止新增真实发布/素材生成等成本型动作。
- `unpaid/canceled`：停止新增任务，保留数据只读和恢复入口。
- webhook 失败：不静默升级/降级，进入 billing review 状态并告警。

## 12. 后端模块拆分

建议新增模块：

- `jiejing_saas/publish_safety_report.py`
- `jiejing_saas/post_publish_review.py`
- `jiejing_saas/listing_profit_brain.py`
- `jiejing_saas/ip_compliance_guard.py`
- `jiejing_saas/platform_rule_memory.py`
- `jiejing_saas/merchant_operating_memory.py`
- `jiejing_saas/source_trust_labels.py`

Runtime 对应新增任务类型：

- `publish.safety_report`
- `listing.profit_snapshot`
- `ip.compliance_review`
- `post_publish.review_1h`
- `post_publish.review_24h`
- `post_publish.review_7d`
- `platform_rule.memory_write`
- `test_listing.cleanup_plan`

## 13. 前端入口

保持 7 个左侧模块，不新增第 8 个模块：

- AI CEO：经营指令包、计划、来源、风险、确认动作、复盘。
- Listing：发布体检报告、利润快照、IP/VeRO/GPSR 状态、后续生命周期。
- 批量铺货：批量发布体检，先抽检再分批确认。
- 素材工坊：图片来源、授权、实物一致性、VeRO 风险。
- 决策中心：发布、清理、改价、库存、下架、广告、政策等高风险动作。
- 客服与订单：发布后客服风险、退货风险、订单复盘。
- 设置：商家经营记忆、利润底线、计费、quota、合规词库、上线门禁。

## 14. 验收标准

上线前必须通过：

- 发布体检报告可见，且阻断项能阻止真实发布。
- Inventory API publish 必填字段按官方 publish 标准检查。
- EU/北爱 GPSR 条件触发时能阻断缺字段发布。
- IP/VeRO 检查能识别品牌词、第三方图片、复制文案、compatible 表述风险。
- Listing 利润快照存在，负毛利/缺成本不能显示为可盈利。
- 发布后 1h/24h/7d 复盘任务能生成并写入工作记录。
- 改价、库存、下架、补图、改描述、清理测试品都进决策中心。
- eBay 失败原因写入平台规则记忆。
- 商家偏好写入经营记忆，但不能绕过确认中心。
- 每个建议都有可信来源标签。
- Stripe/Paddle webhook 能驱动 quota、欠费、恢复、发票和用量账本。

## 15. 官方依据

- eBay Inventory API overview: Inventory item、offer、location、business policies、API 生命周期管理。
- eBay required fields for publishing offers: publish 前必需字段与 business policy 要求。
- eBay createOffer docs: payment/fulfillment/return policy、product compliance、GPSR 条件字段。
- eBay Intellectual Property / VeRO policy: 自有文字图片、品牌名、授权、compatible/fits 表述。
- eBay GPSR seller update: 2024-12-13 后 EU/北爱销售触发安全信息要求。
- Stripe subscription webhooks: invoice paid/payment failed、subscription status、past_due/unpaid/canceled 访问控制。
