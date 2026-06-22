# 捷境 HermesAdapter 设计

生成日期：2026-05-14

本文档定义捷境后端如何把标准任务协议交给当前 Hermes 执行，并把 Hermes 输出转换回捷境 SaaS 可展示、可追踪、可确认的结果。

目标：

- 当前继续使用 Hermes 跑真实 eBay 内测。
- 捷境后端不直接绑定 Hermes 内部结构。
- 让后续 `Jiejing Agent Runtime` 可以逐步替换 Hermes 的部分任务。
- 让 SaaS 工作台看到统一的任务状态、报告、来源记录、缺口和确认项。

---

## 1. 适配器定位

`HermesAdapter` 是捷境后端和 Hermes 之间的翻译层。

它不属于前端。

它不属于 Hermes 本体。

它属于捷境后端。

职责：

- 接收 `JiejingTask`。
- 判断任务类型。
- 选择 Hermes CEO 或具体岗位。
- 生成短任务指令。
- 设置超时和重试。
- 收集 Hermes 输出文件、飞书回报或 team_bus 结果。
- 转换成 `JiejingTaskResult`。
- 标注成功、部分成功、失败、缺资料或需要确认。

---

## 2. 总体链路

```text
捷境 SaaS 前端
  ↓
捷境后端 API
  ↓
Jiejing Task Protocol
  ↓
任务队列
  ↓
HermesAdapter
  ↓
Hermes CEO / team_bus / profile
  ↓
岗位输出
  ↓
HermesAdapter 解析
  ↓
JiejingTaskResult
  ↓
SaaS 工作记录 / AI 汇报 / 确认中心
```

---

## 3. 输入：JiejingTask

适配器只接收标准任务。

示例：

```json
{
  "task_id": "task_20260514_0101",
  "task_type": "market.report",
  "platform": "ebay",
  "project_id": "project_stainless_cup",
  "input": {
    "product_keyword": "stainless steel tumbler",
    "merchant_constraints": ["lightweight", "non-electric", "1688_available"],
    "target_market": "US"
  },
  "timeout_seconds": 180
}
```

适配器禁止接收：

- 无 `task_type` 的自由聊天。
- 无 `task_id` 的长任务。
- 要求真实发布、付款、退款、广告扣费但没有确认项的任务。
- 把完整历史文件全塞进 prompt 的任务。

---

## 4. 任务到 Hermes 岗位映射

| Jiejing Task | Hermes 执行入口 | 说明 |
| --- | --- | --- |
| `ceo.intake` | CEO/default | 接目标、拆任务、判断缺口 |
| `market.data_packet` | market-manager | 先采集数据包，不写长报告 |
| `market.report` | market-manager | 写报告级市场经理报告 |
| `source.match` | finance-supply | 货源、采购、物流、成本事实整理 |
| `listing.package` | product-manager | 生成真实 eBay 刊登资料包 |
| `asset.brief` | product-manager / 素材链路 | 生成图片视频任务包 |
| `customer.learn_product` | customer-service | 客服学习商品档案 |
| `finance.review` | finance-supply | 利润、运费、退货、履约复核 |
| `confirmation.package` | CEO/default | 汇总确认中心事项 |
| `ceo.final_report` | CEO/default | 汇总闭环结果 |

规则：

- 商家不直接看到这些岗位。
- 岗位只接短任务。
- CEO 负责串联和验收。
- 任务过大时必须拆分。

---

## 5. Hermes 指令模板

HermesAdapter 给岗位的指令必须短、清楚、带边界。

### 5.1 市场报告任务

```text
你是捷境 eBay 流程中的市场经理。

任务类型：market.report
商品：{product_keyword}
目标市场：{target_market}
商家约束：{merchant_constraints}

请输出报告级市场判断，必须包含：
1. 品类概述
2. 用户画像
3. eBay 价格带
4. 竞品 Top 5 拆解
5. 差评与风险
6. 关键词方向
7. 货源可行性
8. 物流和包装风险
9. 建议做/谨慎做/暂不做
10. 下一步

每个关键结论必须标注来源类型：
official_api / public_page / merchant_provided / ai_inference / restricted_unavailable。

不要执行真实发布、退款、广告、采购付款。
```

### 5.2 产品刊登任务

```text
你是捷境 eBay 流程中的产品经理。

任务类型：listing.package
上游输入：市场报告、货源事实、店铺政策

请按真实 eBay 发布骨架生成刊登资料包：
SKU、Marketplace、Category ID、Title、Subtitle、Condition、Format、Price、
Quantity、Item Specifics、Picture 1-12 需求、Video 需求、Description HTML、
Package weight、Package dimensions、Handling time、Item Location、
Fulfillment policy、Payment policy、Return policy。

缺真实数据必须列入 missing_inputs。
类目字段必须标注是否已 Taxonomy 校验。
不要编造已确认的 policyId。
不要执行真实发布。
```

### 5.3 财务复核任务

```text
你是捷境 eBay 流程中的财务供应链岗位。

任务类型：finance.review
请复核采购价、平台费、运费、退货预留、广告预算、利润区间和履约风险。

要求：
- 费用来源必须标注。
- 没有真实物流价格时写成估算。
- 真实发布前必须列出需要商家确认的费用项。
- 不执行采购付款。
```

---

## 6. 输出转换规则

Hermes 输出必须转换成 `JiejingTaskResult`。

转换字段：

| Hermes 输出 | 捷境结果字段 |
| --- | --- |
| 报告正文 | `report` |
| 来源说明 | `source_records` |
| 待补资料 | `missing_inputs` |
| 风险提示 | `risk_flags` |
| 需要确认 | `confirmation_items` |
| 下游任务 | `next_tasks` |
| PDF、图片、视频、Markdown | `artifacts` |
| 超时、空输出、工具失败 | `status` + `audit` |

适配器不能做：

- 把空输出标记为成功。
- 把 AI 推断改成官方数据。
- 把素材任务包标成素材已生成。
- 把确认项直接执行。

---

## 7. 状态映射

| Hermes 状态 | 捷境状态 |
| --- | --- |
| 正常输出完整报告 | `success` |
| 输出报告但缺关键资料 | `partial_success` |
| 明确缺资料 | `blocked_missing_input` |
| eBay / 1688 / 工具无权限 | `blocked_permission` |
| 超时 | `failed_timeout` |
| 输出为空 | `failed_tool` |
| 触发高风险动作 | `blocked_confirmation_required` |

SaaS 前台展示规则：

- 成功：展示报告。
- 部分成功：展示报告 + 待补资料。
- 缺资料：跳到资料补充界面。
- 缺权限：跳到连接账号或手动导入。
- 超时：提示已拆分重试，不让商家以为系统还在假工作。
- 需要确认：进入确认中心。

---

## 8. 超时和拆分

HermesAdapter 必须内置超时控制。

默认策略：

| 任务 | 超时 | 失败后动作 |
| --- | --- | --- |
| `ceo.intake` | 60s | 重新组织目标 |
| `market.data_packet` | 180s | 缩小关键词或只取数据包 |
| `market.report` | 180s | 拆成价格带、竞品、风险三段 |
| `listing.package` | 180s | 先输出固定骨架，再补动态字段 |
| `asset.brief` | 180s | 先输出素材清单，再生成素材 |
| `finance.review` | 120s | 先算基础利润，再补运费细节 |
| `confirmation.package` | 60s | 只生成确认项 |

重试规则：

- 第一次失败：自动拆小。
- 第二次失败：返回 `failed_timeout`。
- 不能无限重试。
- 失败也要进入 AI 工作记录。

---

## 9. 文件与报告约定

HermesAdapter 应保存每次任务结果：

```text
output/jiejing-task-runs/
  task_20260514_0101/
    input.json
    hermes_prompt.md
    hermes_raw_output.md
    result.json
    report.md
    artifacts/
```

目的：

- 以后可以复盘。
- 可以训练 Jiejing Agent Runtime。
- 可以对比 Hermes 与自研 Runtime 输出质量。
- 可以排查失败原因。

---

## 10. 影子运行

当 `Jiejing Agent Runtime MVP` 出现后，同一个任务可以双跑：

```text
JiejingTask
  ├─ HermesAdapter -> Hermes result
  └─ JiejingAgentAdapter -> Jiejing result
```

对比维度：

- 报告完整度。
- eBay 字段正确率。
- 缺资料识别。
- 来源标注。
- 风险判断。
- 确认中心生成质量。
- 商家可读性。
- 耗时和稳定性。

替换原则：

- 先替换低风险报告任务。
- 后替换涉及平台数据的任务。
- 最后才替换确认中心和真实执行前流程。
- 真实执行服务不由 Agent 直接掌控，永远在捷境后端。

---

## 11. 安全边界

HermesAdapter 必须拦截：

- 无确认的真实发布。
- 无确认的退款。
- 无确认的改价。
- 无确认的改库存。
- 无确认的广告预算。
- 无确认的采购付款。
- 无确认的店铺政策修改。
- 无确认的 OAuth scope 变更。
- 向前端或报告暴露 token、secret、cookie。

HermesAdapter 必须最小化给 Hermes 的数据：

- 只给本次任务需要的商品、店铺和报告数据。
- 不给全部客户数据库。
- 不给其他用户数据。
- 不给无关订单。
- 不给明文密钥。

---

## 12. 当前实施顺序

P0：

- 使用本设计约束后续 Hermes 测试。
- 每次测试都保存 `input -> prompt -> raw_output -> result`。
- 失败和超时必须写入 SaaS 工作记录。

P1：

- 设计 `HermesAdapter` 伪代码。
- 设计 `result.json` 示例。
- 从最近一次 Hermes 闭环测试中抽取一套样本。

P2：

- 开发 `MockAgentAdapter`。
- 开发 `HermesAdapter` 最小命令行版。
- 开始 `JiejingAgentAdapter` 影子运行。

---

## 13. 一句话

HermesAdapter 的作用不是让捷境更依赖 Hermes，而是把 Hermes 纳入捷境自己的任务协议里，保证以后能替换、能复盘、能扩展。
