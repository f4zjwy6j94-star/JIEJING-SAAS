# 捷境后路工程运行说明

生成日期：2026-05-14

本文档记录当前已经落地的“捷境后路”工程原型：清理脚本、MockAgentAdapter、HermesAdapter 规划器、任务结果验证器和 schema。

---

## 1. 当前已完成

### 1.1 临时图归档

已归档根目录临时截图：

- 匹配范围：`software-demo/tmp*.png`、`software-demo/.tmp*.png`
- 归档数量：206 张
- 归档体量：约 97.93 MB
- 归档位置：`software-demo/artifacts/archive/tmp-screenshots-20260514-160121`

没有移动：

- `assets`
- `docs`
- `output` 报告
- `app.js`
- `styles.css`
- `index.html`
- `design-huashu.html`

手动 dry-run：

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\archive-demo-temp-assets.ps1
```

真正归档：

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\archive-demo-temp-assets.ps1 -Apply
```

---

## 2. MockAgentAdapter 原型

文件：

`software-demo/tools/jiejing_agent_runtime_mock.py`

作用：

- 不调用大模型。
- 不调用 Hermes。
- 不调用 eBay。
- 不调用支付、物流、1688。
- 只读取验收样本，把 Hermes 闭环文件转换成标准 `JiejingTaskResult`。

运行：

```powershell
python .\tools\jiejing_agent_runtime_mock.py .\output\jiejing-agent-runtime-samples\cable-clips-20260513
```

输出：

```text
output/jiejing-agent-runtime-samples/cable-clips-20260513/mock-runtime-run/
  result.json
  summary.md
  tasks/
    01_ceo_intake.json
    02_market_data_packet.json
    ...
```

当前结果：

- 任务数：10
- 成功：5
- 部分成功：3
- 缺资料阻断：2
- 确认项：4
- 缺口：12

---

## 3. HermesAdapter 规划器

文件：

`software-demo/tools/jiejing_hermes_adapter_plan.py`

作用：

- 不执行 Hermes。
- 只生成未来 HermesAdapter 要发给各岗位的短任务 prompt。
- 把 `Jiejing Task` 映射到 Hermes 角色。
- 所有生成计划都标记 `execute_now=false`。

运行：

```powershell
python .\tools\jiejing_hermes_adapter_plan.py .\output\jiejing-agent-runtime-samples\cable-clips-20260513
```

输出：

```text
output/jiejing-agent-runtime-samples/cable-clips-20260513/hermes-dispatch-plan/
  dispatch-plan.json
  summary.md
  prompts/
    01_ceo_intake_default.md
    02_market_data_packet_market-manager.md
    ...
```

当前映射：

| 任务 | Hermes 角色 |
| --- | --- |
| `ceo.intake` | `default` |
| `market.data_packet` | `market-manager` |
| `market.report` | `market-manager` |
| `source.match` | `finance-supply` |
| `listing.package` | `product-manager` |
| `asset.brief` | `product-manager` |
| `customer.learn_product` | `customer-service` |
| `finance.review` | `finance-supply` |
| `ceo.final_report` | `default` |
| `owner.review` | `default` |

---

## 4. 任务结果验证器

文件：

`software-demo/tools/validate_jiejing_task_results.py`

作用：

- 检查每个 `JiejingTaskResult` 是否有核心字段。
- 检查状态是否合法。
- 检查是否有来源记录。
- 检查是否误标真实发布、付款、退款、广告、政策修改。

运行：

```powershell
python .\tools\validate_jiejing_task_results.py .\output\jiejing-agent-runtime-samples\cable-clips-20260513\mock-runtime-run\tasks
```

当前结果：

```text
result=PASS total=10
```

---

## 5. Schema

新增：

- `software-demo/schemas/jiejing-task.schema.json`
- `software-demo/schemas/jiejing-task-result.schema.json`

用途：

- 约束后端任务输入。
- 约束 Agent 输出。
- 后续 TypeScript / 后端 / Jiejing Runtime 都可以按 schema 实现。

当前校验：

```powershell
python -m json.tool .\schemas\jiejing-task.schema.json
python -m json.tool .\schemas\jiejing-task-result.schema.json
```

结果：

```text
schemas=PASS
```

---

## 6. 验收样本

样本目录：

`software-demo/output/jiejing-agent-runtime-samples/`

当前主样本：

`cable-clips-20260513`

包含：

- `task-sequence.json`
- `expected-result-summary.json`
- `mock-runtime-run/`
- `hermes-dispatch-plan/`

样本来源：

`C:/Users/57249/Documents/Codex/2026-04-29/hermes-agents/output/cable-clips-pdf-staging-20260513`

这个样本是目前最重要的后路验收基准。

---

## 7. 下一步

P0：

- 把 `MockAgentAdapter` 的结果接入 SaaS 前端的 AI 汇报模块，用来展示真实任务状态。
- 生成第二套样本，比如不锈钢水杯或倒流香炉。
- 给 `HermesAdapter` 增加“可执行但默认关闭”的命令层。

P1：

- 开始 `JiejingAgentAdapter` 第一版，只实现 `market.report`。
- 同一个样本同时跑 Hermes 和自研 Runtime。
- 输出影子对比报告。

P2：

- 做真正后端项目时，把 schema 迁移到后端仓库。
- 把 `Execution Service` 和 `Confirmation Center` 做成独立模块。

---

## 8. 一句话

当前后路工程已经从文档进入可执行原型：它能读取 Hermes 闭环样本，生成标准任务结果，生成 Hermes 分发计划，并验证输出是否符合捷境任务协议。
