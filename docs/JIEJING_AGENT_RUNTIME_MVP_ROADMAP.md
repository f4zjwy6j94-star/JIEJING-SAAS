# Jiejing Agent Runtime MVP 路线

生成日期：2026-05-14

本文档定义捷境自有 Agent Runtime 的第一版路线。

目标不是复刻 Hermes，而是开发一个适合捷境电商流程的最小可用 Agent 底座。

---

## 1. 核心定位

Jiejing Agent Runtime 是捷境自己的电商流程执行引擎。

它要解决的问题：

- 商家说目标后，系统能拆成电商任务。
- 每个任务能调用大模型和工具。
- 每个结果能回写 SaaS 工作台。
- 每个风险能进入确认中心。
- eBay 是第一平台，未来可适配其他平台。

它不是：

- 不是通用聊天机器人。
- 不是完整复刻 Hermes。
- 不是替代后端权限系统。
- 不是直接操作 eBay 的执行服务。
- 不是绕过确认中心的自动发布工具。

---

## 2. 第一版只做什么

MVP 只做单品闭环。

```text
AI CEO 接目标
  ↓
市场报告
  ↓
货源事实整理
  ↓
产品刊登报告
  ↓
素材任务包
  ↓
客服学习包
  ↓
财务复核
  ↓
确认中心事项
  ↓
CEO 汇总
```

第一版必须支持：

- 标准任务输入。
- 大模型调用。
- 结构化报告输出。
- 来源标注。
- 缺资料识别。
- 风险标记。
- 确认事项生成。
- 任务状态。
- 超时和失败反馈。
- 保存任务记录。

第一版暂不做：

- 完整多租户正式后端。
- 真实 eBay 发布。
- 真实支付。
- 真实采购付款。
- 全自动客服发信。
- 大规模批量铺货并发。
- 完整飞书/Telegram/Slack 多端网关。
- Hermes 那种完整技能自进化系统。

理由：

捷境第一阶段要证明的是电商流程闭环，而不是做一个通用 Agent 平台。

---

## 3. MVP 技术模块

### 3.1 Task Runner

负责：

- 接收 `JiejingTask`。
- 根据 `task_type` 选择 handler。
- 设置超时。
- 写任务状态。
- 返回 `JiejingTaskResult`。

### 3.2 Model Client

负责：

- 接大模型。
- 支持 OpenAI / OpenRouter / 其他模型供应商。
- 隐藏模型差异。
- 控制 prompt、输出格式和重试。

### 3.3 Tool Layer

第一版只需要少量工具：

- 网页搜索或公开数据入口。
- eBay mock / 只读数据入口。
- 1688 手动资料入口。
- 文件读写。
- PDF / Markdown 报告输出。

后续再加：

- eBay Taxonomy。
- eBay Browse / Trading / Finances。
- 1688 API。
- 图片和视频生成。
- 物流费用估算。

### 3.4 Report Renderer

负责：

- 把结构化结果渲染成商家能读的报告。
- 同时保存 JSON 和 Markdown。
- 后续可导出 PDF。

### 3.5 Confirmation Builder

负责：

- 把高风险动作转成确认中心事项。
- 不执行动作。
- 给后端 Execution Service 使用。

### 3.6 Audit Log

负责：

- 保存任务输入。
- 保存模型输出。
- 保存来源记录。
- 保存失败原因。
- 保存确认项。

---

## 4. MVP 文件结构建议

未来后端项目里建议这样放：

```text
jiejing-agent-runtime/
  src/
    index.ts
    task-runner/
      runTask.ts
      taskTypes.ts
      status.ts
    model/
      modelClient.ts
      providers/
    handlers/
      ceoIntake.ts
      marketReport.ts
      sourceMatch.ts
      listingPackage.ts
      assetBrief.ts
      customerLearnProduct.ts
      financeReview.ts
      confirmationPackage.ts
      ceoFinalReport.ts
    platform-adapters/
      ebay/
      source1688/
      manualImport/
    renderers/
      markdownReport.ts
      pdfReport.ts
    audit/
      saveRun.ts
  schemas/
    jiejing-task.schema.json
    jiejing-result.schema.json
  examples/
    backflow-incense/
    stainless-cup/
```

当前 demo 阶段先不需要真的建这个工程目录，先把协议、样本和适配层设计定稳。

---

## 5. 与 Hermes 的关系

第一阶段：

- Hermes 是主执行器。
- Jiejing Agent Runtime 只做影子运行。
- 不影响真实流程。

第二阶段：

- 低风险任务双跑。
- 对比 Hermes 和 Jiejing Runtime 的报告。
- 如果自研结果更稳定，就替换对应任务。

第三阶段：

- Jiejing Runtime 承担主链路。
- Hermes 降级为备用 worker 或内部研发工具。

---

## 6. 影子对比规则

同一个任务同时跑：

```text
JiejingTask
  ├─ HermesAdapter
  └─ JiejingAgentAdapter
```

对比指标：

| 指标 | 说明 |
| --- | --- |
| 完整度 | 是否覆盖必须字段 |
| 准确性 | eBay 字段、政策、风险是否合理 |
| 来源标注 | 是否区分官方、公开、商家提供、AI 推断 |
| 缺口识别 | 是否能停在缺资料处 |
| 可读性 | 商家是否看得懂 |
| 风险边界 | 是否把高风险动作送确认 |
| 稳定性 | 是否超时、空输出、跑偏 |
| 成本 | token、工具、时间成本 |

替换标准：

- 连续 5 次同类任务不低于 Hermes 输出质量。
- 不丢确认中心。
- 不把推断当事实。
- 不出现真实高风险执行。

---

## 7. 第一批样本任务

建议用已经跑过的商品做样本：

- 倒流香炉。
- 不锈钢水杯。
- 桌面理线夹。
- 旅行压缩收纳袋。

每个样本保存：

- `input.json`
- `market_report.md`
- `listing_package.md`
- `asset_brief.md`
- `customer_learning.md`
- `finance_review.md`
- `confirmation_package.md`
- `ceo_final_report.md`
- `expected_result.json`

这些样本以后就是验收集。

---

## 8. 平台扩展原则

eBay 是第一平台。

未来扩展平台时，不重写 Agent Runtime，只新增：

- 平台字段映射。
- 平台 API Adapter。
- 平台政策规则。
- 平台确认边界。
- 平台报告模板差异。

例如：

| 平台 | 新增内容 |
| --- | --- |
| eBay | Category ID、Item Specifics、Business Policies |
| 1688 | 货源、规格、价格、发货地、采购付款 |
| Shopify | Product、Variant、Collection、Shipping Profile |
| Amazon | ASIN、类目合规、品牌、FBA/FBM |
| Manual Import | 图片、链接、表格、手动资料 |

---

## 9. 开发节奏

### 第 1 周：协议和样本

- 完成任务协议。
- 完成 HermesAdapter 设计。
- 整理 2-3 套 Hermes 真实输出样本。

### 第 2 周：Mock Runtime

- 开发 `MockAgentAdapter`。
- 用固定样本跑通 SaaS 前端展示。
- 不接真实模型。

### 第 3 周：Runtime MVP

- 开发 `Task Runner`。
- 接一个大模型。
- 实现 `market.report` 和 `listing.package`。

### 第 4 周：影子运行

- 同任务 Hermes 和自研 Runtime 双跑。
- 对比报告质量。
- 修正 prompt、schema 和失败处理。

### 第 5 周：低风险替换

- 先替换报告生成。
- 仍由 Hermes 或后端处理复杂工具链。
- 真实执行继续走确认中心。

---

## 10. 当前立即动作

P0：

- 把最近 Hermes 测试报告整理成标准样本。
- 设计 `HermesAdapter` 的 `result.json` 示例。
- 设计 `MockAgentAdapter` 返回格式。

P1：

- 给 SaaS 前端的 AI 汇报、产品刊登、素材工坊、确认中心补统一任务状态。
- 把“卡住、缺资料、已完成、需确认”用同一套状态语言展示。

P2：

- 开始最小工程实现。
- 不急着云端部署。
- 不急着接真实 eBay 写入。

---

## 11. 一句话

Jiejing Agent Runtime MVP 的目标不是做第二个 Hermes，而是把捷境电商闭环中最核心、最可控、最能形成壁垒的任务执行能力做成我们自己的底座。
