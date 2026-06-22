# 捷境任务协议 Jiejing Task Protocol

生成日期：2026-05-14

本文档定义捷境 SaaS 的标准任务协议。

目的：

- 让捷境后端掌握任务格式，而不是绑定 Hermes 内部结构。
- 让 Hermes、Jiejing Agent Runtime、MockAgent 和未来其他执行器都能按同一套协议执行。
- 让 eBay、1688、Shopify、Amazon 等平台未来通过适配层接入。
- 让每个任务都有来源、缺口、风险、确认边界和审计记录。

---

## 1. 总原则

捷境不是普通聊天工具，也不是普通 ERP。

捷境的任务系统要把商家的自然语言目标转成可执行、可追踪、可确认的电商任务。

核心原则：

- 商家面对 AI CEO，不直接管理内部岗位。
- 后端负责身份、权限、数据隔离和任务状态。
- Agent 只处理本次任务所需的最小数据包。
- 高风险动作必须进入确认中心。
- 所有结果必须标注来源和可信度。
- 任务必须支持超时、失败、重试和拆小。
- 不同执行器必须返回同一种结果结构。

---

## 2. 标准任务结构

每个任务必须包含：

```json
{
  "task_id": "task_20260514_0001",
  "task_type": "market.report",
  "task_version": "2026-05-14",
  "user_id": "user_demo",
  "company_id": "company_demo",
  "store_id": "store_demo",
  "platform": "ebay",
  "stage": "store_opened",
  "project_id": "project_backflow_incense",
  "parent_task_id": "task_20260514_0000",
  "input": {},
  "context": {},
  "source_policy": {},
  "risk_policy": {},
  "output_contract": {},
  "timeout_seconds": 180,
  "retry_policy": {
    "max_retries": 2,
    "split_on_timeout": true
  }
}
```

字段说明：

| 字段 | 说明 |
| --- | --- |
| `task_id` | 全局唯一任务 ID |
| `task_type` | 任务类型，例如 `market.report` |
| `task_version` | 协议版本，方便以后升级 |
| `user_id` | 用户 ID |
| `company_id` | 公司或团队 ID |
| `store_id` | 店铺 ID |
| `platform` | 平台，例如 `ebay` |
| `stage` | 商家阶段，例如小白、已有店铺、有订单、多店铺 |
| `project_id` | 商品或项目 ID |
| `parent_task_id` | 上游任务 ID |
| `input` | 本次任务输入 |
| `context` | 必要上下文，不放无关历史 |
| `source_policy` | 来源标注规则 |
| `risk_policy` | 风险确认规则 |
| `output_contract` | 必须返回的结构 |
| `timeout_seconds` | 超时时间 |
| `retry_policy` | 重试和拆分策略 |

---

## 3. 标准结果结构

每个执行器必须返回：

```json
{
  "task_id": "task_20260514_0001",
  "status": "success",
  "executor": "hermes",
  "executor_version": "0.13.0",
  "started_at": "2026-05-14T15:00:00+08:00",
  "finished_at": "2026-05-14T15:02:00+08:00",
  "summary": "市场报告已完成，建议进入小批量测试。",
  "report": {},
  "source_records": [],
  "missing_inputs": [],
  "risk_flags": [],
  "confirmation_items": [],
  "next_tasks": [],
  "artifacts": [],
  "audit": {}
}
```

状态枚举：

| 状态 | 含义 |
| --- | --- |
| `queued` | 已进入队列 |
| `running` | 正在执行 |
| `success` | 成功完成 |
| `partial_success` | 部分完成，有缺口 |
| `blocked_missing_input` | 缺资料，等待商家补充 |
| `blocked_permission` | 缺授权或权限 |
| `failed_timeout` | 超时 |
| `failed_tool` | 工具或外部接口失败 |
| `failed_policy` | 风险或合规规则阻断 |
| `cancelled` | 已取消 |

---

## 4. 来源记录 Source Records

所有关键结论必须标注来源类型。

来源类型：

| 类型 | 说明 |
| --- | --- |
| `official_api` | 官方 API，例如 eBay API |
| `official_page` | 官方公开页面 |
| `public_page` | 公开网页 |
| `merchant_provided` | 商家上传或手动填写 |
| `manual_input` | 人工输入 |
| `screenshot_or_video` | 截图、视频、图片 |
| `tool_estimate` | 工具估算 |
| `ai_inference` | AI 推断 |
| `restricted_unavailable` | 受限不可访问 |

来源记录结构：

```json
{
  "source_id": "src_001",
  "source_type": "merchant_provided",
  "title": "供应商提供的包装重量",
  "url": null,
  "captured_at": "2026-05-14T15:00:00+08:00",
  "confidence": "medium",
  "used_for": ["package_weight", "shipping_estimate"],
  "note": "商家手动填写，发布前建议实测。"
}
```

可信度：

- `high`
- `medium`
- `low`
- `unknown`

规则：

- 官方 API 优先。
- 商家提供资料必须标注。
- AI 推断不能当作官方事实。
- 受限不可访问要明确写出，不允许假装查到了。

---

## 5. 风险确认规则

以下动作必须生成 `confirmation_items`，不能自动执行：

| 风险动作 | 说明 |
| --- | --- |
| `publish_listing` | 真实发布 Listing |
| `bulk_publish_listing` | 批量发布 |
| `change_price` | 改价 |
| `change_inventory` | 改库存 |
| `refund` | 退款 |
| `partial_refund` | 部分退款 |
| `ad_budget` | 广告预算 |
| `procurement_payment` | 采购付款 |
| `address_write` | 写入收货地址 |
| `policy_edit` | 修改物流、支付、退货政策 |
| `oauth_scope_change` | 授权范围变化 |
| `store_subscription` | 店铺订阅开通、升级或取消 |
| `sensitive_buyer_commitment` | 敏感客服承诺 |

确认项结构：

```json
{
  "confirmation_id": "confirm_001",
  "action_type": "publish_listing",
  "title": "发布倒流香炉 Listing",
  "reason": "资料已齐，可进入真实发布前确认。",
  "impact": "将在 eBay 店铺创建新商品。",
  "required_by": "execution_service",
  "default_action": "hold",
  "options": ["approve", "edit", "reject"],
  "source_task_ids": ["task_001", "task_002"]
}
```

默认规则：

- 钱、发布、退款、广告、采购、授权、店铺政策、敏感买家承诺，都默认停住。
- 用户可设置默认规则，但高风险首次配置必须确认。
- 自动客服可以更自动，但退款、赔偿、负面承诺和平台纠纷必须停住。

---

## 6. 核心任务类型

### 6.1 `ceo.intake`

目的：

接收商家目标，判断任务是否清楚，拆分后续任务。

输入：

- 商家原话。
- 当前店铺阶段。
- 已连接账号状态。
- 已有货源或无货源。
- 自动化边界设置。

输出：

- 商家目标复述。
- 风险边界。
- 任务拆分。
- 需要补问的问题。
- 下一批任务。

---

### 6.2 `market.data_packet`

目的：

先整理市场数据包，不直接写长报告。

输入：

- 商品关键词。
- 平台。
- 目标市场。
- 货源约束。
- 商家偏好：轻小、不带电、不易碎、客单价、售后难度等。

输出：

- 关键词方向。
- eBay 可观察数据。
- 竞品样本。
- 价格带。
- 用户画像。
- 风险信号。
- 来源记录。
- 哪些数据是推断。

---

### 6.3 `market.report`

目的：

生成报告级市场经理输出。

必须包含：

- 品类概述。
- 用户画像。
- eBay 价格带。
- 竞品 Top 5 拆解。
- 标题和卖点模式。
- 差评与风险。
- 搜索词方向。
- 货源可行性。
- 物流和包装风险。
- 利润初判。
- 建议：做 / 谨慎做 / 暂不做。
- 下一步。

输出要求：

- 不能只有聊天摘要。
- 必须标注数据来源。
- 数据不足时必须写明缺口。

---

### 6.4 `source.match`

目的：

根据市场机会匹配货源。

输入：

- 市场报告。
- 商家选择的货源渠道：1688 / 手动链接 / 自有库存 / 供应商表格。
- 约束：轻小、不带电、不易碎、预算、发货地。

输出：

- 候选货源。
- 采购价。
- SKU / 规格。
- 起订量。
- 发货地。
- 库存状态。
- 包装重量和尺寸。
- 供应商要确认的问题。
- 采购风险。

规则：

- 不知道就写缺口。
- 测试模拟可以标注为样例资料。
- 真实发布前必须用真实供应商资料替换。

---

### 6.5 `listing.package`

目的：

生成产品经理刊登资料包。

固定骨架：

- SKU。
- Marketplace。
- Category ID。
- Title，最长 80 字符。
- Subtitle，需提示可能收费。
- Condition。
- Format。
- Price。
- Quantity。
- Item Specifics。
- Picture 1-12 需求。
- Video 需求。
- Description HTML。
- Package weight。
- Package dimensions。
- Handling time。
- Item Location。
- Fulfillment policy。
- Payment policy。
- Return policy。

动态字段：

- 必须由 eBay 类目决定。
- 不同商品不能用同一套 Item Specifics。
- 真实接入时要通过 eBay Taxonomy 校验。

输出要求：

- 让商家能看懂。
- 字段必须接近真实 eBay 发布项。
- 缺口要集中列出。
- 不能把 AI 推断字段伪装成已确认事实。

---

### 6.6 `asset.brief`

目的：

生成素材工坊任务包。

输入：

- 市场报告。
- 刊登资料包。
- 商品图或无图需求。
- 平台要求。
- 图片数量、尺寸、场景、详情页、视频要求。

输出：

- 主图需求。
- 白底图需求。
- 场景图需求。
- 尺寸图需求。
- 细节图需求。
- 详情页长图需求。
- 口播视频脚本。
- 展示视频镜头表。
- 禁止出现的词和画面。
- 发布前需要确认的素材事实。

规则：

- 素材任务包不等于素材已生成。
- 生成图片/视频后必须回写 artifacts。
- 未实测或未授权的卖点不能写进图文。

---

### 6.7 `customer.learn_product`

目的：

让客服在商品发布前学习商品资料。

输入：

- 市场报告。
- 刊登资料。
- 商品参数。
- 物流与退货规则。
- 风险问题。

输出：

- 商品知识卡。
- 常见问题。
- 买家关心点。
- 售前回复模板。
- 售后回复模板。
- 需要人工接管的问题。
- 禁止承诺清单。

规则：

- 客服不能临时瞎答。
- 客服必须先学习商品档案。
- 退款、赔偿、纠纷、负面评价、平台投诉默认停住。

---

### 6.8 `finance.review`

目的：

复核利润和履约风险。

输入：

- 采购价。
- 包装重量和尺寸。
- eBay 价格。
- 平台费。
- 广告预算。
- 物流方式。
- 退货预留。
- 汇率。

输出：

- 成本拆解。
- 运费估算。
- 平台费用。
- 广告预算影响。
- 退货预留。
- 利润区间。
- 不赚钱红线。
- 是否建议发布。

规则：

- 费用估算要标注来源。
- 没有真实物流价格时不能写成确定值。
- 真实发布前必须让商家确认。

---

### 6.9 `confirmation.package`

目的：

把所有需要人确认的事项集中到确认中心。

输入：

- 市场报告。
- 刊登资料。
- 素材状态。
- 财务复核。
- 客服边界。

输出：

- 发布确认。
- 价格确认。
- 库存确认。
- 采购付款确认。
- 物流政策确认。
- 退货政策确认。
- 广告预算确认。
- 客服自动化边界确认。

规则：

- 确认中心不是普通待办。
- 只放真正需要人决定的高风险事项。
- 每个确认项都必须说明影响。

---

### 6.10 `ceo.final_report`

目的：

CEO 汇总完整闭环结果。

输出：

- 这次做了什么。
- 哪些岗位完成了什么。
- 关键结论。
- 资料缺口。
- 风险。
- 是否进入确认中心。
- 下一步建议。

---

## 7. 任务拆分顺序

标准单品流程：

```text
ceo.intake
  ↓
market.data_packet
  ↓
market.report
  ↓
source.match
  ↓
listing.package
  ↓
asset.brief
  ↓
customer.learn_product
  ↓
finance.review
  ↓
confirmation.package
  ↓
ceo.final_report
```

批量铺货流程：

```text
ceo.intake
  ↓
market.bulk_opportunity_scan
  ↓
market.bulk_shortlist
  ↓
source.bulk_match
  ↓
merchant.select_candidates
  ↓
逐个进入单品流程
```

---

## 8. 执行器适配

### 8.1 HermesAdapter

当前主执行器。

负责：

- 把 Jiejing Task 转成 Hermes CEO / team_bus / profile 能理解的任务。
- 控制任务颗粒。
- 收集 Hermes 输出。
- 转换成标准结果结构。
- 处理超时、空输出、失败。

### 8.2 JiejingAgentAdapter

未来自有执行器。

负责：

- 直接调用 Jiejing Agent Runtime。
- 按标准任务协议执行。
- 不依赖 Hermes profile 和飞书。

### 8.3 MockAgentAdapter

演示和测试执行器。

负责：

- 返回稳定的演示数据。
- 不调用真实 eBay、Hermes、支付或数据库。
- 用于 SaaS 前端演示和离线测试。

---

## 9. 超时和失败规则

默认原则：

- 任务超时不能假装还在做。
- 空输出不能当成功。
- 报告太大必须拆小。
- 外部数据不可用必须标注。

建议超时：

| 任务 | 建议超时 |
| --- | --- |
| `ceo.intake` | 60s |
| `market.data_packet` | 180s |
| `market.report` | 180s |
| `source.match` | 180s |
| `listing.package` | 180s |
| `asset.brief` | 180s |
| `customer.learn_product` | 120s |
| `finance.review` | 120s |
| `confirmation.package` | 60s |
| `ceo.final_report` | 90s |

超时处理：

1. 标记 `failed_timeout`。
2. 记录已完成部分。
3. 自动拆成更小任务。
4. 重试不超过 2 次。
5. 仍失败则回到 AI CEO 工作记录，告诉商家卡在哪里。

---

## 10. 平台字段适配

任务协议不直接写死平台字段。

例如 `listing.package` 在 eBay 下需要：

- Title。
- Category ID。
- Item Specifics。
- Condition。
- Format。
- Price。
- Quantity。
- Description。
- Package weight。
- Package dimensions。
- Fulfillment policy。
- Payment policy。
- Return policy。

未来 Shopify 可能需要：

- Product title。
- Vendor。
- Product type。
- Variants。
- Collections。
- SEO title。
- SEO description。
- Inventory tracking。
- Shipping profile。

所以正确方式是：

```text
Jiejing Task Protocol
  ↓
Platform Adapter
  ↓
Platform-specific Fields
```

---

## 11. 当前优先级

P0：

- 用这个任务协议约束后续 Hermes 测试。
- Hermes 每次跑闭环后，输出要能映射到这些任务类型。
- SaaS 前端工作流点击和报告也要逐步按这些任务类型组织。

P1：

- 新增示例任务包。
- 新增 `HermesAdapter` 设计文档。
- 新增标准报告模板。

P2：

- 开发 Jiejing Agent Runtime MVP。
- 用 Hermes 输出做影子对比。
- 逐步替换低风险报告生成任务。

---

## 12. 一句话

捷境任务协议是后路的核心：Hermes 可以继续执行，但捷境必须拥有任务格式、报告结构、确认规则和平台适配权。
