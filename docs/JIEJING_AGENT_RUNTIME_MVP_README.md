# 捷境 Agent Runtime MVP 说明

生成日期：2026-05-14

这份文档说明当前已经写出来的“捷境自己的 Agent Runtime 底座程序”。

它不是网页 Demo，也不是 Hermes 本体，也不是普通脚本集合。它的定位是：未来捷境 SaaS 后端里的任务执行底座。

---

## 1. 它负责什么

`jiejing_runtime` 负责：

- 接收标准任务 `JiejingTask`。
- 管理任务队列和父子依赖。
- 调度 Adapter 执行任务。
- 检查高风险动作和确认中心边界。
- 检查每个岗位输出是否符合结果契约。
- 生成标准结果 `JiejingTaskResult`。
- 写任务快照、结果文件、运行摘要和审计日志。

一句话：它把“商家一句话”后面的 AI CEO 工作流，变成后端能执行、能审计、能替换底层引擎的任务系统。

---

## 2. 当前目录

```text
jiejing_runtime/
  __init__.py
  models.py
  task_queue.py
  contracts.py
  policies.py
  model_clients.py
  adapters.py
  execution.py
  repository.py
  tools_registry.py
  api_server.py
  store.py
  runtime.py

tools/
  jiejing_runtime_cli.py
  test_jiejing_runtime_mvp.py
```

---

## 3. 模块职责

### `models.py`

定义任务和基础校验：

- `JiejingTask`
- `RuntimeIssue`
- `RuntimeAuditEvent`
- `validate_task_core`

### `task_queue.py`

定义任务队列：

- 检查重复任务 ID。
- 检查父任务是否存在。
- 检查父任务是否排在子任务前面。
- 输出队列快照给 `run.json`。

当前是内存队列。正式后端可以换成 Redis、Postgres 或云队列。

### `contracts.py`

定义结果契约检查：

- 结果必须有核心字段。
- 结果必须有摘要。
- 结果必须有来源记录。
- 高风险任务必须生成确认项。
- Adapter 必须承认任务要求的报告结构。

这一步是为了防止岗位空转、无正文、无来源、无确认项。

### `policies.py`

定义安全边界：

- 哪些动作必须确认。
- 哪些真实执行标记绝对不能在演示模式出现。
- 哪些任务会生成确认项。

核心类：

- `SafetyGate`
- `ConfirmationCenter`

### `model_clients.py`

定义模型调用边界。

当前只有：

- `RuleBasedModelClient`

它是本地确定性模型替身，不调用外部大模型。未来可以在这里接真实模型，而不改 Runtime 调度器。

### `adapters.py`

定义执行器边界。

当前有三个 Adapter：

- `MockAgentAdapter`
  - 离线跑 Hermes/Jiejing 验收样本。
  - 不调用 Hermes。
  - 不调用 eBay。
  - 不调用大模型。
- `JiejingAgentAdapter`
  - 捷境自有 Agent Adapter 第一版。
  - 当前使用 `RuleBasedModelClient`。
  - 不依赖 Hermes 样本正文。
  - 会生成结构化报告、缺口、风险和确认项。
- `HermesAdapterPlanOnly`
  - Hermes 边界占位。
  - 当前不执行 Hermes。
  - 证明以后可以把 Hermes 放在 Adapter 后面，而不是让 SaaS 直接绑定 Hermes 内部实现。

### `store.py`

负责落盘：

- 任务快照
- 执行结果
- `run.json`
- `summary.md`
- `audit-log.jsonl`

### `execution.py`

定义真实动作执行边界。

当前有：

- `ExecutionRequest`
- `ExecutionResult`
- `ExecutionService`

规则：

- Adapter 不能直接发布、退款、付款、改价、改广告、改政策。
- 高风险动作没有确认记录时，返回 `blocked_confirmation_required`。
- 演示模式下，即使有确认记录，也返回 `blocked_demo_mode`，不会执行真实平台动作。
- 未来真实 eBay / 支付 / 物流 API 只能接在这里后面。

### `repository.py`

定义本地 SQLite 持久化层。

当前保存：

- runs
- tasks
- results
- confirmations
- confirmation decisions
- audit events

这一步让 Runtime 不再只能写文件，而是有了未来 SaaS 后端可以查询的数据库雏形。

### `tools_registry.py`

定义工具能力注册表。

当前只登记能力，不真实执行：

- `web.public_search`
- `ebay.read_only`
- `ebay.execution`
- `sourcing.1688_read`
- `logistics.orange_connex_estimate`
- `asset.image_video_generation`

所有工具默认关闭。真实执行能力必须以后通过权限、授权和确认中心打开。

### `api_server.py`

定义本地 HTTP API。

当前支持：

- `GET /health`
- `GET /tools`
- `GET /runs`
- `GET /runs/{run_id}`
- `GET /runs/{run_id}/tasks`
- `GET /runs/{run_id}/results`
- `GET /runs/{run_id}/confirmations`
- `GET /runs/{run_id}/confirmation-decisions`
- `GET /runs/{run_id}/audit`
- `POST /runs`
- `POST /runs/{run_id}/confirmations/{confirmation_id}/decision`

这不是最终生产后端，但它证明 SaaS 前端以后可以通过 API 读取 Runtime 结果，而不是直接读静态演示文件。

### `runtime.py`

核心调度器：

- 读取任务。
- 过队列检查。
- 过安全闸。
- 调 Adapter。
- 过结果契约检查。
- 写结果。
- 汇总运行状态。

核心类：

- `JiejingRuntime`
- `RuntimeConfig`
- `RuntimeRunSummary`

---

## 4. 当前已经能跑什么

当前可以跑 11 步闭环：

```text
ceo.intake
market.data_packet
market.report
source.match
listing.package
asset.brief
customer.learn_product
finance.review
confirmation.package
ceo.final_report
owner.review
```

对应捷境 SaaS 的真实方向：

```text
AI CEO 接目标
-> 市场数据包
-> 市场经理报告
-> 货源/财务预检
-> 产品经理刊登资料
-> 素材任务包
-> 客服学习产品
-> 财务复核
-> 确认中心
-> CEO 汇总
-> 主理人复盘
```

---

## 5. 当前运行命令

从 `software-demo` 目录运行 Mock Adapter：

```powershell
python .\tools\jiejing_runtime_cli.py run `
  --tasks-dir .\output\jiejing-agent-runtime-samples\cable-clips-20260513\prepared-tasks\tasks `
  --output-dir .\output\jiejing-agent-runtime-samples\cable-clips-20260513\runtime-mvp-run `
  --adapter mock `
  --run-id cable-clips-runtime-mvp
```

当前结果：

```text
tasks=11
status=completed_with_blocks
```

运行捷境自有 Adapter：

```powershell
python .\tools\jiejing_runtime_cli.py run `
  --tasks-dir .\output\jiejing-agent-runtime-samples\cable-clips-20260513\prepared-tasks\tasks `
  --output-dir .\output\jiejing-agent-runtime-samples\cable-clips-20260513\runtime-jiejing-local-run `
  --adapter jiejing-local `
  --run-id cable-clips-jiejing-local
```

当前结果：

```text
tasks=11
status=completed_with_blocks
```

运行 Hermes 占位 Adapter：

```powershell
python .\tools\jiejing_runtime_cli.py run `
  --tasks-dir .\output\jiejing-agent-runtime-samples\cable-clips-20260513\prepared-tasks\tasks `
  --output-dir .\output\jiejing-agent-runtime-samples\cable-clips-20260513\runtime-hermes-plan-run `
  --adapter hermes-plan `
  --run-id cable-clips-hermes-plan
```

当前结果：

```text
tasks=11
status=adapter_plan_only
```

`completed_with_blocks` 的意思是：流程能跑通，但正式发布前仍然有缺资料和确认中心阻断。

`adapter_plan_only` 的意思是：Hermes 只是占位边界，没有被真实调用。

---

## 6. 输出文件

每次运行会生成：

```text
runtime-mvp-run/
  run.json
  summary.md
  audit-log.jsonl
  tasks/
    01_ceo_intake.json
    ...
  results/
    01_ceo_intake.json
    ...
```

其中：

- `run.json` 给后端/前端读取。
- `summary.md` 给人看。
- `audit-log.jsonl` 给审计和排错。
- `tasks/` 是本次执行的任务快照。
- `results/` 是本次执行的标准结果。

---

## 7. 回归测试

运行：

```powershell
python .\tools\test_jiejing_runtime_mvp.py
```

当前结果：

```text
PASS runtime_mvp_regression
```

测试覆盖：

- Mock Adapter 跑完整 11 步。
- JiejingAgentAdapter 跑完整 11 步。
- `run_status` 必须是 `completed_with_blocks`。
- 结果必须有 11 个。
- 队列快照必须有 11 个。
- 确认中心必须有确认项。
- 真实发布、采购、退款、广告、政策修改标记必须全是 `false`。
- 审计日志的 `created_at` 必须是时间字符串。
- ExecutionService 必须拦住没有确认的真实发布请求。
- 演示模式下，即使有确认记录，也不能真实发布。
- SQLite 必须能保存 run、结果、确认项、审计日志。
- API 必须能返回 run、确认项、工具注册表。
- API 必须能创建新的 Runtime run，并自动保存到 SQLite。
- API 必须能记录确认中心决策，但不能真实执行。

---

## 8. 和 Hermes 的关系

当前设计不是马上替换 Hermes。

正确关系是：

```text
捷境后端
  -> JiejingTask
  -> JiejingRuntime
  -> AgentAdapter
      -> MockAgentAdapter
      -> JiejingAgentAdapter
      -> HermesAdapter
      -> Future Platform/Model Adapter
```

Hermes 以后只是 Adapter 后面的一个执行器。

捷境掌握：

- 任务协议
- 任务队列
- 任务拆分
- 报告结构
- 来源记录
- 确认中心
- 风险边界
- 平台适配
- 执行动作边界
- 审计日志

这样 Hermes 能用就用；如果以后不可用，捷境可以逐步替换 Adapter，而不是整个 SaaS 瘫痪。

---

## 9. 当前边界

本 Runtime MVP 当前没有：

- 真实大模型调用。
- 真实 Hermes 调用。
- 真实 eBay API 调用。
- 真实数据库。
- 真实支付。
- 真实物流。
- 真实发布。
- 真实退款。

它先把“捷境应该怎么跑任务”写成程序。

---

## 10. 下一步开发顺序

### 第一步

把 `HermesAdapterPlanOnly` 升级为真正的 `HermesAdapter`，但先只允许低风险任务：

- `market.report`
- `listing.package`
- `asset.brief`

禁止真实发布和付款。

### 第二步

把 `JiejingAgentAdapter` 从本地规则模型升级为真实模型客户端：

- 先只跑 `market.report`。
- 和 Hermes 输出做影子对比。
- 保持来源记录、确认中心和审计日志不变。

### 第三步

把 Runtime 输出接到 SaaS 工作台：

- AI 汇报
- 工作记录
- 确认中心
- 连接账号

### 第四步

后端项目启动后，把 Runtime 从 `software-demo` 迁移到正式后端仓库。
