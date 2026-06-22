# Jiejing Agent Runtime 验收样本集

生成日期：2026-05-14

本文档把已经跑过的 Hermes 闭环测试整理成捷境自有 Agent Runtime 的验收样本。

目的：

- 不让后路开发从空白开始。
- 用 Hermes 已经跑通的真实链路做基准。
- 以后 Jiejing Agent Runtime 每做一个能力，都要和这些样本对比。

---

## 1. 样本 A：桌面理线夹闭环

样本目录：

`C:\Users\57249\Documents\Codex\2026-04-29\hermes-agents\output\cable-clips-pdf-staging-20260513`

样本定位：

- 当前最重要的 Hermes 闭环验收样本。
- 商品是 `50pcs Self Adhesive Cable Clips Organizer`。
- 覆盖 CEO、市场经理、货源/财务预审、产品经理刊登、素材工坊、客服学习、财务终审、CEO 汇总和主理人复盘。
- 没有执行真实 eBay 发布、采购付款、退款、广告预算或政策修改。

任务映射：

| 源文件 | 捷境任务类型 | 用途 |
| --- | --- | --- |
| `01_ceo_intake.md` | `ceo.intake` | 接目标、定边界、拆任务 |
| `00_source_packet.md` | `market.data_packet` / `source.match` | 初始数据包和约束 |
| `02_market_manager.md` | `market.report` | 市场经理报告 |
| `03_source_finance_precheck.md` | `source.match` | 货源事实、履约预审 |
| `04_product_listing.md` | `listing.package` | 产品经理 eBay 刊登资料包 |
| `05_asset_workshop.md` | `asset.brief` | 素材工坊任务包 |
| `06_customer_service.md` | `customer.learn_product` | 客服学习商品档案和话术 |
| `07_finance_final.md` | `finance.review` | 财务终审和履约复核 |
| `08_ceo_final.md` | `ceo.final_report` | CEO 全链路总结 |
| `10_codex_owner_review.md` | `owner.review` | 主理人验收、SaaS 整改要求 |

关键验收点：

- 每个岗位都有结构化输出。
- 文件名已尽量使用 ASCII，避免跨系统乱码。
- 报告明确区分真实采集、公开样本、测试假设和 AI 推断。
- 产品刊登包接近真实 eBay 上架骨架。
- 素材工坊明确区分任务包与真实素材。
- 客服在发布前学习商品档案。
- 财务终审能反推产品刊登和价格策略。
- 高风险动作停在确认中心。

当前不足：

- 仍缺独立 `confirmation.package` 文件。
- 真实发布前缺 eBay Taxonomy 校验。
- 真实发布前缺真实供应商资料和素材商用确认。
- 当前店铺运费策略会显著影响低客单价商品，需要进入确认中心。

---

## 2. 样本 B：2026-05-12 模拟闭环

样本目录：

`C:\Users\57249\Documents\Codex\2026-04-29\hermes-agents\software-demo\output\full-loop-20260512`

样本定位：

- SaaS 前端闭环和演示流程样本。
- 适合验证页面流转、确认中心、素材展示和模拟执行边界。
- 不作为真实 eBay 发布级样本。

任务映射：

| 源文件 | 捷境任务类型 | 用途 |
| --- | --- | --- |
| `FULL_LOOP_REPORT_20260512.md` | `ceo.final_report` | 模拟闭环总报告 |
| `CEO_CONFIRMATION_PACKAGE_20260512_AFTERNOON.md` | `confirmation.package` | 确认中心样本 |
| `SAAS_TASK_SPLIT_DESIGN_20260512.md` | `task.split.design` | SaaS 任务拆分设计 |
| `simulated_supplier_reusable_cable_ties.json` | `source.match` | 模拟供应商资料 |
| `simulated_product_reusable_cable_ties.json` | `listing.package` | 模拟产品资料 |
| `simulated_margin_reusable_cable_ties.json` | `finance.review` | 模拟利润资料 |
| `simulated_store_policies.json` | `store.policy` | 模拟店铺政策 |

关键验收点：

- 能验证 SaaS 前端是否形成闭环。
- 能验证确认中心是否出现。
- 能验证素材和视频是否能被页面展示。
- 能验证缺资料和高风险动作是否被拦住。

当前不足：

- 部分报告存在编码显示问题。
- 模拟数据不能当真实店铺数据。
- 不适合作为真实发布级样本。

---

## 3. 自研 Runtime 验收标准

以后 `Jiejing Agent Runtime MVP` 对同一商品运行时，至少要达到：

| 标准 | 要求 |
| --- | --- |
| 完整度 | 能输出单品闭环 8 个核心任务 |
| 结构 | 输出符合 `JIEJING_TASK_PROTOCOL.md` |
| 来源 | 每个关键结论标注来源类型 |
| 风险 | 不把 AI 推断当官方事实 |
| eBay | 刊登包字段接近真实 eBay 发布项 |
| 缺口 | 能识别供应商资料、Taxonomy、政策、图片和运费缺口 |
| 客服 | 能生成商品学习包和接管边界 |
| 财务 | 能复核价格、运费、退货和利润区间 |
| 确认 | 钱、发布、退款、广告、采购和政策修改必须停住 |
| 稳定 | 不空输出，不无限重试，不让商家以为还在假工作 |

---

## 4. 影子对比方式

同一任务先跑 Hermes，再跑自研 Runtime。

对比表：

| 维度 | Hermes 输出 | Jiejing Runtime 输出 | 结论 |
| --- | --- | --- | --- |
| 市场报告 | 样本 A `02_market_manager.md` | 待生成 | 是否达到报告级 |
| 刊登资料 | 样本 A `04_product_listing.md` | 待生成 | 是否覆盖真实 eBay 字段 |
| 素材任务 | 样本 A `05_asset_workshop.md` | 待生成 | 是否区分任务包和素材 |
| 客服学习 | 样本 A `06_customer_service.md` | 待生成 | 是否能接住售前售后 |
| 财务复核 | 样本 A `07_finance_final.md` | 待生成 | 是否能反推发布策略 |
| CEO 汇总 | 样本 A `08_ceo_final.md` | 待生成 | 是否能汇总闭环和阻断点 |

替换规则：

- 自研 Runtime 连续多次不低于 Hermes 输出质量，才替换低风险报告任务。
- 真正执行 eBay 写入仍然只走捷境后端 Execution Service。
- Agent 永远不直接越过确认中心。

---

## 5. 下一步

P0：

- 为样本 A 生成 `task-sequence.json`。
- 为样本 A 生成 `expected-result-summary.json`。
- 从样本 A 抽取第一批 prompt / schema 验收点。

P1：

- 做 `MockAgentAdapter`，先用样本输出驱动 SaaS 页面状态。
- 做 `HermesAdapter` 最小命令行版。

P2：

- 自研 Runtime 先实现 `market.report` 和 `listing.package` 两个任务。
- 做 Hermes vs 自研 Runtime 影子对比。

---

## 6. 一句话

后路开发不是凭空重写，而是把 Hermes 已经跑通的闭环沉淀成标准样本，再让捷境自己的 Runtime 一项一项追上并替换。
