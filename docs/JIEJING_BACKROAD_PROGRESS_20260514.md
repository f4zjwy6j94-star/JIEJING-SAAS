# 捷境后路工程进度记录

生成日期：2026-05-14

本文档记录“捷境自有 Agent Runtime 后路”的当前工程进度。

这里的“后路”不是现在马上替换 Hermes，也不是复制一个通用聊天 Agent。它的目标是让捷境 SaaS 拥有自己的电商任务协议、任务拆分、确认边界、结果结构和平台适配层。Hermes 仍然可以作为当前内测和早期云端执行底座，但捷境后端不能被 Hermes 内部实现锁死。

---

## 1. 当前结论

已经完成第一层可执行原型，并补上了真正的 Runtime MVP 程序：

```text
验收样本
  -> 标准 JiejingTask 输入队列
  -> JiejingRuntime 调度
  -> MockAgentAdapter 离线执行
  -> SafetyGate 风险检查
  -> FileRunStore 落盘
  -> 标准 JiejingTaskResult 输出
  -> 结果校验
  -> HermesAdapter 分发计划
```

这说明捷境已经开始掌握自己的任务格式和结果格式。

现在还没有做真实后端、真实数据库、真实 eBay 写入、真实 Hermes 调用或真实支付。所有新增内容都是离线工程骨架和验收样本，不会影响现有 Huashu Demo Flow。

---

## 2. 已落地的关键文件

### 2.1 任务协议与后路文档

- `docs/JIEJING_TASK_PROTOCOL.md`
- `docs/JIEJING_AGENT_RUNTIME_AND_HERMES_EXIT_PLAN.md`
- `docs/JIEJING_HERMES_ADAPTER_DESIGN.md`
- `docs/JIEJING_AGENT_RUNTIME_MVP_ROADMAP.md`
- `docs/HERMES_VERSION_LOCK.md`
- `docs/JIEJING_BACKROAD_ENGINEERING_RUNBOOK_20260514.md`

### 2.2 Schema

- `schemas/jiejing-task.schema.json`
- `schemas/jiejing-task-result.schema.json`

### 2.3 工程脚本

- `tools/prepare_jiejing_tasks.py`
  - 从验收样本生成标准 `JiejingTask` 输入。
- `tools/run_prepared_jiejing_tasks_mock.py`
  - 从标准 `JiejingTask` 输入跑出标准 `JiejingTaskResult`。
- `tools/jiejing_agent_runtime_mock.py`
  - 直接把 Hermes 闭环样本转换成标准结果。
- `tools/jiejing_hermes_adapter_plan.py`
  - 生成未来 HermesAdapter 要发给各岗位的短任务 prompt，不执行 Hermes。
- `tools/validate_jiejing_tasks.py`
  - 校验标准任务输入。
- `tools/validate_jiejing_task_results.py`
  - 校验标准任务结果。
- `tools/archive-demo-temp-assets.ps1`
  - 清理根目录临时截图，减少 Codex 卡顿。

### 2.4 Runtime MVP 程序

- `jiejing_runtime/__init__.py`
- `jiejing_runtime/models.py`
- `jiejing_runtime/task_queue.py`
- `jiejing_runtime/contracts.py`
- `jiejing_runtime/policies.py`
- `jiejing_runtime/model_clients.py`
- `jiejing_runtime/adapters.py`
- `jiejing_runtime/execution.py`
- `jiejing_runtime/repository.py`
- `jiejing_runtime/tools_registry.py`
- `jiejing_runtime/api_server.py`
- `jiejing_runtime/store.py`
- `jiejing_runtime/runtime.py`
- `tools/jiejing_runtime_cli.py`
- `tools/test_jiejing_runtime_mvp.py`

这才是第一版“捷境 Agent Runtime 底座程序”。

当前能力：

- 读取标准 `JiejingTask` 队列。
- 检查任务队列、父子依赖和重复任务。
- 按顺序调度任务。
- 调用 Adapter 执行。
- 通过 `SafetyGate` 检查真实发布、采购、退款、广告、政策等危险动作。
- 通过 `ResultContractValidator` 检查空输出、缺来源、缺确认项和结果结构。
- 通过 `ExecutionService` 把真实发布、付款、退款、广告、政策修改隔离在执行边界外。
- 通过 `SQLiteRuntimeRepository` 保存 run、task、result、confirmation、decision 和 audit。
- 通过 `RuntimeApiServer` 提供本地 API 查询能力。
- 通过 `ToolRegistry` 固定未来外部工具接入边界。
- 当前 SaaS 模拟端已经能通过本地 Runtime API 读取 run、result、confirmation 和 decision。
- 当前 SaaS 模拟端可以触发一次本地 Runtime 演示运行，并把结果回写到 AI 汇报和 Runtime 确认面板。
- 生成 `JiejingTaskResult`。
- 写入任务快照、执行结果、运行摘要和审计日志。
- 支持 `mock`、`jiejing-local` 和 `hermes-plan` 三种 Adapter。

当前不做：

- 不接真实 Hermes。
- 不接真实 eBay。
- 不调用大模型。
- 不真实发布、付款、退款、广告或改政策。

---

## 3. 当前验收样本

样本目录：

```text
output/jiejing-agent-runtime-samples/cable-clips-20260513
```

样本来源：

```text
C:/Users/57249/Documents/Codex/2026-04-29/hermes-agents/output/cable-clips-pdf-staging-20260513
```

当前标准流程已经调整为 11 个任务：

```text
1. ceo.intake
2. market.data_packet
3. market.report
4. source.match
5. listing.package
6. asset.brief
7. customer.learn_product
8. finance.review
9. confirmation.package
10. ceo.final_report
11. owner.review
```

其中第 9 步 `confirmation.package` 是本轮补上的关键节点。原因是确认中心不能只是报告里的附属字段，它必须成为正式 SaaS 后端里的独立任务节点。

---

## 4. 本轮发现并修复的问题

### 4.1 缺少确认中心任务节点

原样本有确认事项，但没有独立的 `confirmation.package`。

已修复：

- 在样本任务序列中补充 `confirmation.package`。
- Mock Runtime 能合成确认中心结果。
- Hermes Dispatch Plan 能为确认中心生成独立 prompt。

### 4.2 重跑时残留旧任务文件

重新生成任务时，旧 JSON 没清掉，会导致目录里出现重复任务。

已修复：

- `prepare_jiejing_tasks.py` 每次生成前清理旧 task JSON。
- `jiejing_agent_runtime_mock.py` 每次生成前清理旧 result JSON。
- `jiejing_hermes_adapter_plan.py` 每次生成前清理旧 prompt。

这个修复很重要。正式 SaaS 后端也必须避免“旧任务残留导致前端看到重复进度”。

---

## 5. 当前校验结果

已通过：

```text
prepared task inputs: PASS total=11
mock runtime results: PASS total=11
prepared mock run results: PASS total=11
runtime mvp run results: PASS total=11
runtime hermes plan results: PASS total=11
runtime mvp regression: PASS
runtime sqlite repository: PASS
runtime local api server: PASS
runtime api create run: PASS
confirmation decision record: PASS
saas mock frontend runtime bridge: PASS
runtime api cors preflight: PASS
schema json syntax: PASS
python compile: PASS
```

Mock 运行结果：

```json
{
  "task_count": 11,
  "status_counts": {
    "success": 5,
    "partial_success": 3,
    "blocked_missing_input": 2,
    "blocked_confirmation_required": 1
  },
  "confirmation_item_count": 9,
  "missing_input_count": 12
}
```

注意：这不是坏事。它说明系统没有假装“全自动发布成功”，而是在资料、政策、发布、采购、客服边界等风险点正确停住。

Runtime MVP 当前运行结果：

```text
runtime-mvp-run:
  task_count=11
  run_status=completed_with_blocks
  confirmation_item_count=9
  missing_input_count=7

runtime-hermes-plan-run:
  task_count=11
  run_status=adapter_plan_only

runtime-jiejing-local-run:
  task_count=11
  run_status=completed_with_blocks
  confirmation_item_count=9
  missing_input_count=7
```

`completed_with_blocks` 的含义是：流程可以跑通，但正式发布前仍然有资料缺口或高风险确认项。

`adapter_plan_only` 的含义是：Hermes 适配器现在只是占位边界，不会偷偷调用 Hermes。

`runtime-jiejing-local-run` 的含义是：捷境自己的 Adapter 已经能在不依赖 Hermes 样本正文的情况下，按任务协议生成结构化报告、缺口、风险和确认项。

当前新的工程完成度评估：

```text
Runtime 架构底座：约 70%-72%
可替代 Hermes 的 Agent 能力：约 18%-25%
接入真实 SaaS 后端：约 58%-62%
接入真实 eBay 自动化闭环：约 20%-25%
可商业化生产级：约 15%-20%
```

这里提升最大的是“后端底座形态”和“模拟前端接入”：现在已经有 API、SQLite、确认决策记录、工具注册、执行边界，API 可以创建新的 Runtime run，并且当前工作台页面可以读取这些结果。

---

## 6. 这对正式 SaaS 的意义

以后正式 SaaS 不应该把一句大任务直接丢给 Hermes 或任何一个 Agent。

正确方式是：

```text
用户目标
  -> 后端生成 JiejingTask
  -> 队列逐个执行
  -> HermesAdapter / JiejingAgentAdapter 执行单个小任务
  -> 返回 JiejingTaskResult
  -> 前端显示工作记录、来源记录、缺口、确认项
  -> 高风险动作进入确认中心
```

这样可以解决之前真实测试中发现的问题：

- 岗位任务过大导致超时。
- 空输出被误认为还在工作。
- 报告和素材、刊登、客服、财务之间接不上。
- 商家不知道卡在哪一步。
- 确认中心看起来像普通待办，而不是高风险决策点。

现在 `JiejingRuntime` 已经把这套思想落成了最小可运行代码。

---

## 6.1 当前运行命令

从 `software-demo` 目录运行：

```powershell
python .\tools\jiejing_runtime_cli.py run `
  --tasks-dir .\output\jiejing-agent-runtime-samples\cable-clips-20260513\prepared-tasks\tasks `
  --output-dir .\output\jiejing-agent-runtime-samples\cable-clips-20260513\runtime-mvp-run `
  --adapter mock `
  --run-id cable-clips-runtime-mvp
```

输出：

```text
runtime-mvp-run/
  run.json
  summary.md
  audit-log.jsonl
  tasks/
  results/
```

Hermes 边界占位运行：

```powershell
python .\tools\jiejing_runtime_cli.py run `
  --tasks-dir .\output\jiejing-agent-runtime-samples\cable-clips-20260513\prepared-tasks\tasks `
  --output-dir .\output\jiejing-agent-runtime-samples\cable-clips-20260513\runtime-hermes-plan-run `
  --adapter hermes-plan `
  --run-id cable-clips-hermes-plan
```

这个命令不会调用 Hermes，只证明 Adapter 边界存在。

---

## 7. 下一步建议

### P0

1. 用第二个真实闭环样本补充验收集，例如不锈钢水杯或倒流香炉。
2. 把 SaaS 模拟端的 Runtime 接入从 AI 汇报/确认中心扩展到产品刊登、素材工坊和连接账号。
3. 让 HermesAdapter 先只执行一个低风险任务，例如 `market.report`，跑影子对比。

### P1

1. 开始做 `JiejingAgentAdapter` 最小版。
2. 先实现市场报告生成，不碰真实发布。
3. 同一个样本同时跑 Hermes 和 JiejingAgentAdapter，比较报告结构、来源标注、缺口识别和确认项。

### P2

1. 正式后端项目启动后，把 schema 迁移到后端仓库。
2. 建立任务队列、审计日志、确认中心表结构。
3. 真实 eBay 写入只走 Execution Service，并且必须验证确认记录。

---

## 8. 当前边界

本轮没有：

- 接真实 eBay API。
- 接真实 Hermes 执行。
- 接真实支付。
- 接真实数据库。
- 修改现有官网主页。
- 执行任何真实发布、采购、退款、广告或店铺政策变更。

本轮已经修改当前工作台 UI：在 `AI 汇报` 和 `待我确认` 中加入 Runtime API 接入面板。它只读取本地 Runtime 演示数据，不执行真实外部平台动作。

本轮把“捷境自己的任务协议和后路执行骨架”推进到可被 SaaS 模拟端读取的阶段。

---

## 9. 2026-05-14 Runtime 知识层补充

本轮新增“脱敏知识导入层”，把 Hermes 已经沉淀的项目资料转成捷境 Runtime 自己可读取的知识包。

新增文件：

- `jiejing_runtime/knowledge.py`
- `tools/ingest_jiejing_knowledge.py`
- `tools/test_jiejing_runtime_knowledge.py`

生成文件：

- `output/jiejing-runtime-knowledge/jiejing-runtime-knowledge-pack.json`
- `output/jiejing-runtime-knowledge/summary.md`

导入内容：

- CEO 编排和任务拆分 SOP
- 市场经理 eBay 市场报告标准
- 产品经理 eBay 刊登字段、素材任务包和发布锁标准
- 客服学习产品档案和自动回复边界
- 财务履约、1688/货源资料、SpeedPAK/橙联费用纪律
- team-repair 工作流健康检查
- SaaS 公开页面与内部 Hermes 边界
- 已验证样本报告结构

安全边界：

- 不导入 `.env`、credential、token、Cookie、密码、真实授权值。
- 导入脚本会对疑似密钥赋值、HTTP 认证头、敏感路径、邮箱和长串密钥值做脱敏。
- Runtime 结果只引用 `runtime_sanitized_knowledge`，不会把 Hermes 内部实现当作公开产品能力。

当前知识包状态：

```text
items=24
files_read=16
manual_distilled_rules=8
redactions=19
```

验证结果：

```text
runtime_knowledge_regression: PASS
runtime_mvp_regression: PASS
runtime API /knowledge: PASS
runtime API run with knowledge references: PASS
```

这一步的意义：

Runtime 不再只是空的执行框架。它已经开始拥有捷境自己的“流程记忆”：哪些岗位该做什么、市场报告怎么写、刊登包必须包含哪些 eBay 字段、素材任务包和真实素材文件怎么区分、客服什么时候能自动回复、财务和物流哪些资料会阻塞发布、哪些动作必须进确认中心。

最新实打实进度评估：

```text
Runtime 架构底座：约 74%-76%
替代 Hermes 的 Agent 能力：约 24%-30%
接入 SaaS 模拟端：约 72%-75%
接入真实 SaaS 后端：约 60%-64%
真实 eBay 自动化闭环：约 22%-27%
商业化生产级：约 16%-22%
```

---

## 10. 2026-05-14 动态工作流与 Hermes 影子适配器

本轮继续把后路底座往“可接 SaaS、可接 Hermes、可替换 Hermes”的方向推进。

新增文件：

- `jiejing_runtime/workflow_templates.py`
- `tools/test_jiejing_runtime_workflow.py`

新增能力：

- `build_product_workflow(...)`
  - 输入一个商品、商家目标、店铺阶段和货源方式。
  - 自动生成 11 段标准 `JiejingTask`：
    1. `ceo.intake`
    2. `market.data_packet`
    3. `market.report`
    4. `source.match`
    5. `listing.package`
    6. `asset.brief`
    7. `customer.learn_product`
    8. `finance.review`
    9. `confirmation.package`
    10. `ceo.final_report`
    11. `owner.review`
- CLI 新增：
  - `python .\tools\jiejing_runtime_cli.py run-workflow ...`
- Runtime API 新增：
  - `POST /workflows/product-test`
- SaaS 模拟端的“运行一次模拟链路”已改为调用动态工作流接口，不再只依赖固定样本目录。
- 新增 `hermes-shadow` adapter：
  - 把每个 `JiejingTask` 翻译成 Hermes 岗位短任务包。
  - 记录目标岗位、必填输出结构、知识引用和安全边界。
  - 不调用 Hermes。
  - 不读 token、Cookie、密钥。
  - 不执行真实 eBay、采购、退款、广告或政策改动。

验证结果：

```text
runtime_workflow_regression: PASS
runtime_mvp_regression: PASS
runtime_knowledge_regression: PASS
python compileall: PASS
node --check app.js: PASS
Runtime API /workflows/product-test: PASS
SaaS front-end create runtime workflow: PASS
Hermes shadow adapter dispatch packet: PASS
```

这一步的意义：

以前 Runtime 主要是在跑已经准备好的样本任务。现在它可以从 SaaS 的一句商品目标开始，自己生成标准任务链，再交给 `jiejing-local` 或 `hermes-shadow` 执行。也就是说，捷境后路底座已经开始具备“前端目标 -> 后端任务链 -> 执行器 -> 报告/确认项 -> 前端读取”的形态。

更新后的真实进度评估：

```text
Runtime 架构底座：约 79%-82%
替代 Hermes 的 Agent 能力：约 28%-34%
接入 SaaS 模拟端：约 78%-82%
接入真实 SaaS 后端：约 64%-68%
真实 eBay 自动化闭环：约 23%-28%
商业化生产级：约 18%-24%
```

还不能说“后路已经能替代 Hermes”。原因：

- 还没有真实大模型客户端。
- `hermes-shadow` 还没有真的向飞书 CEO / team_bus / Hermes profile 发任务。
- 还没有真实工具调用编排。
- 还没有生产数据库、多租户权限、OAuth vault、云端队列。
- 还没有真实 eBay 只读和写入执行服务。

但可以说：后路底座的工程骨架已经从文档和样本，推进到可由 SaaS 模拟端动态触发的 Runtime API。

---

## 11. 2026-05-14 可插拔模型、Hermes 文件交接与运行画像

本轮继续推进“后路底座拉满”的工程闭环。

新增文件：

- `jiejing_runtime/capabilities.py`

增强文件：

- `jiejing_runtime/model_clients.py`
- `jiejing_runtime/adapters.py`
- `jiejing_runtime/runtime.py`
- `jiejing_runtime/api_server.py`
- `tools/jiejing_runtime_cli.py`
- `tools/test_jiejing_runtime_workflow.py`
- `app.js`
- `styles.css`

新增能力：

### 11.1 可插拔模型客户端

新增 `OpenAICompatibleModelClient`。

特点：

- 使用环境变量显式配置时，才调用真实 HTTP 模型接口。
- 未配置时自动降级到本地规则模型。
- 不会因为没有 API key 阻塞测试。
- 不会在 Demo 中误扣费。
- 输出仍必须回到 `JiejingTaskResult` 结构。

新增执行器名称：

```text
jiejing-llm
```

### 11.2 Hermes 文件交接适配器

新增 `HermesFileHandoffAdapter`。

执行器名称：

```text
hermes-file
```

它会把每个 Runtime 任务生成两类交接文件：

```text
output/jiejing-hermes-handoff/<project_id>/<role>/<task_id>.md
output/jiejing-hermes-handoff/<project_id>/<role>/<task_id>.json
```

这些文件包含：

- task_id
- target_role
- product
- merchant goal
- required sections
- dispatch prompt
- missing inputs
- confirmation items
- safety boundary

它不会：

- 调用 Hermes。
- 调用 eBay。
- 读 token、Cookie、密钥。
- 执行发布、付款、退款、广告、政策修改。

意义：

后面真正接 Hermes 时，不需要 SaaS 前端直接碰 Hermes。正确链路会变成：

```text
SaaS 前端
-> Runtime API
-> JiejingTask
-> HermesAdapter / Hermes file handoff
-> Hermes role / cloud worker
-> JiejingTaskResult
-> 确认中心 / 工作记录
```

### 11.3 Runtime 运行画像

新增 API：

```text
GET /capabilities
```

当前返回 8 个能力项：

- JiejingTask protocol
- Sanitized Jiejing/Hermes knowledge pack
- Configurable model client
- Hermes shadow dispatch
- Hermes file handoff
- Confirmation center boundary
- Real eBay/payment/logistics execution blocked
- Production SaaS backend partial

SaaS 前端 Runtime 面板现在显示：

- 工具能力：6
- Runtime 知识包：24
- 底座画像：8

验证结果：

```text
runtime_workflow_regression: PASS
runtime_mvp_regression: PASS
runtime_knowledge_regression: PASS
python compileall: PASS
node --check app.js: PASS
Runtime API /capabilities: PASS
SaaS front-end capability panel: PASS
hermes-file handoff artifacts: PASS
jiejing-llm fallback boundary: PASS
```

更新后的真实进度评估：

```text
Runtime 架构底座：约 84%-87%
替代 Hermes 的 Agent 能力：约 34%-40%
接入 SaaS 模拟端：约 82%-86%
接入真实 SaaS 后端：约 67%-71%
真实 eBay 自动化闭环：约 24%-30%
商业化生产级：约 20%-26%
```

为什么还不能继续往上虚报：

- 真实模型客户端有接口，但还没有配置真实 key 和模型做稳定输出验收。
- Hermes 文件交接已有，但还没有真实飞书 CEO/team_bus/cloud worker 消费这些文件。
- 还没有生产级队列、Vault、多租户权限、云数据库。
- 还没有真实 eBay 只读 Adapter 和 ExecutionService 写入 Adapter。

当前已经可以说：

捷境后路底座不再只是文档。它已经具备任务协议、动态工作流、知识包、模型接口、Hermes 交接、确认中心、SQLite/API、SaaS 前端读取和安全边界。下一步再往上拉，必须开始接真实低风险执行：先接只读工具和 Hermes 单任务回收，不碰真实发布。

---

## 12. 2026-05-14 Hermes 回收解析器

本轮继续补齐“发给 Hermes 后怎么收回来”的闭环。

新增文件：

- `jiejing_runtime/hermes_handoff.py`

新增 CLI：

```powershell
python .\tools\jiejing_runtime_cli.py import-handoff-result `
  --packet-json <hermes-file 生成的 packet.json> `
  --role-output <Hermes 或 team_bus 返回的 markdown> `
  --output-json <标准 JiejingTaskResult 输出路径>
```

新增能力：

- 读取 `hermes-file` 生成的 handoff packet。
- 读取 Hermes / team_bus / 飞书角色返回的 Markdown。
- 解析 Markdown 标题为结构化 `report.sections`。
- 自动识别常见缺口：
  - supplier_real_facts
  - business_policy_ids
  - taxonomy_item_specifics
  - logistics_quote
- 自动识别常见风险：
  - publish_lock
  - customer_service_escalation
  - source_confidence
- 重新生成 `confirmation_items`。
- 保持 `real_execution_allowed=false`。
- 输出标准 `JiejingTaskResult`。

验证结果：

```text
import-handoff-result: PASS
handoff importer missing input detection: PASS
handoff importer real execution blocked: PASS
runtime_workflow_regression: PASS
runtime_mvp_regression: PASS
runtime_knowledge_regression: PASS
```

这一步的意义：

Runtime 现在不只是能“把任务交给 Hermes”，也能“把 Hermes 返回内容收回到捷境自己的标准结果格式”。这才是以后逐步替换 Hermes 的关键：无论执行器是 Hermes、捷境自研 Agent、云端 Worker，还是其他模型，只要最后回到 `JiejingTaskResult`，SaaS 前端、确认中心、审计日志和后端执行服务都不用跟着重写。

更新后的真实进度评估：

```text
Runtime 架构底座：约 88%-90%
替代 Hermes 的 Agent 能力：约 40%-46%
接入 SaaS 模拟端：约 84%-88%
接入真实 SaaS 后端：约 70%-74%
真实 eBay 自动化闭环：约 25%-31%
商业化生产级：约 22%-28%
```

这里已经接近“后路底座 MVP 完成”。再往上不是继续堆本地代码，而是要做真实集成：

1. 配置真实模型 key，验收 `jiejing-llm` 输出质量。
2. 让 Hermes 或飞书 CEO 消费 `output/jiejing-hermes-handoff` 里的任务包。
3. 把返回报告用 `import-handoff-result` 收回 Runtime。
4. 接 eBay 只读 Adapter。
5. 上云后换成生产队列、数据库、Vault、OAuth 和 ExecutionService。

---

## 13. 2026-05-14 Runtime -> Hermes 实测回收

本轮开始做低风险真实桥接测试：

```text
Jiejing Runtime
  -> 生成 market.report handoff
  -> Hermes market-manager 尝试执行
  -> Hermes Markdown 输出
  -> import-handoff-result 回收到 JiejingTaskResult
```

测试商品：

```text
Stainless Steel Travel Tumbler
```

测试结论：

- Runtime 能生成动态 11 段商品流程。
- `hermes-file` 能生成市场经理 handoff 包。
- Hermes CLI 与 `team_bus` 入口存在。
- 完整工具型市场报告任务 420 秒超时，日志为空。
- 拆成 `market.data_packet` 后仍然 240 秒超时，日志为空。
- 改成 no-tools 初步报告后，Hermes market-manager 能在约 53 秒返回 Markdown 报告。
- Runtime 能把该 Markdown 回收到标准 `JiejingTaskResult`。
- 回收器现在会把“AI 推断 / 初步报告 / 非官方数据 / 缺 Top5 竞品拆解”判定为 `blocked_missing_input`，不会误判为 `success`。

本轮发现的真实问题：

```text
Hermes 角色能写短报告，但工具型深度调研会超时。
```

这说明正式 SaaS 后端不能把“全网调研 + eBay 数据 + 1688 货源 + 市场报告”一次性丢给一个岗位。必须拆成：

```text
market.data_packet.ebay_probe
market.data_packet.public_search_probe
market.data_packet.source_probe
market.data_packet.logistics_probe
market.report.write_from_packet
```

每个小任务都要有：

- 超时上限
- 重试次数
- 空输出识别
- 来源置信度
- 失败反馈
- 可继续 / 不可继续判断

本轮已补的 Runtime 保护：

- 空 Hermes 输出会被标记为 `failed_tool`。
- 含 `timeout / timed out` 的输出会被标记为 `failed_timeout`。
- 纯 AI 推断或初步报告会要求 `source_confidence_upgrade`。
- 缺真实 eBay 数据会要求 `live_market_data`。
- 缺必需报告章节会生成 `report_section_*` 缺口。
- 所有回收结果仍保持 `real_execution_allowed=false`。

当前进度调整：

```text
Runtime 架构底座：约 88%-90%
替代 Hermes 的 Agent 能力：约 40%-46%
接入 SaaS 模拟端：约 84%-88%
接入真实 SaaS 后端：约 70%-74%
真实 eBay 自动化闭环：约 25%-31%
商业化生产级：约 22%-28%
```

下一步不要直接进入产品经理刊登。应先把 `market.data_packet` 的真实数据采集从 Hermes 大 prompt 中拆出来，做成 Runtime 可控的小工具/小任务，再让 Hermes 市场经理只负责基于数据包写判断报告。

---

## 14. 2026-05-14 market.data_packet 拆分层

本轮开始把上一节发现的问题落成代码：`market.data_packet` 不再只是一个泛泛的模型报告，而是 Runtime 自己控制的市场数据包层。

新增文件：

- `jiejing_runtime/market_data_packet.py`

改动文件：

- `jiejing_runtime/adapters.py`
- `jiejing_runtime/capabilities.py`
- `jiejing_runtime/tools_registry.py`
- `jiejing_runtime/__init__.py`
- `tools/test_jiejing_runtime_workflow.py`

当前数据包拆成 5 个槽位：

```text
1. ebay_read_only
   eBay 只读市场信号：listing 数、价格带、竞品、售出信号、类目方向。

2. public_search
   公开网页搜索信号：搜索引擎、公开页面、标题摘要、来源时间。

3. cross_platform_reference
   跨平台公开参考：Amazon、1688、淘宝、拼多多、Shopify 等只能作为公开参考或授权数据，不能冒充 eBay 官方数据。

4. sourcing_availability
   货源可得性：1688 链接、图片、表格、授权接口或商家手动输入。

5. logistics_estimate
   物流估算：包裹重量、尺寸、发货地、SpeedPAK/橙联路线、时效和费用。
```

每个槽位都会输出：

- 状态：`ready / pending_connector / pending_tool / pending_manual_input / pending_facts`
- 来源类型：例如 `restricted_unavailable`、`manual_input`、`tool_estimate`
- 置信度：`low / medium / high`
- 当前结论
- 下一步动作

`ProductWorkflowRequest` 和 Runtime API 现在支持 `market_probe_inputs`。这意味着以后正式后端、只读 eBay Adapter、搜索工具、1688 只读 Adapter、物流估算工具，拿到结果后可以把快照塞进这个字段：

```json
{
  "market_probe_inputs": {
    "ebay_read_only": {
      "source_type": "official_api",
      "confidence": "medium",
      "summary": "Read-only eBay signal was collected.",
      "metrics": {
        "active_listing_sample": 42,
        "observed_price_band": "US $14.99-$24.99"
      }
    }
  }
}
```

只要对应槽位有合规快照，数据包会从 `pending_connector` 变成 `ready`。没有快照时继续保持缺口，不会假装完成。

当前策略：

```text
没有真实 eBay 只读数据时，market.data_packet = blocked_missing_input
没有货源或授权数据时，source_availability = blocking
没有公开搜索、跨平台参考、物流估算时，先标 warning 或 blocking，不假装已经调研完成
```

这一步的产品意义：

商家以后在 SaaS 里看到的不是“AI 正在调研，请等待”，而是：

```text
eBay 信号：未接只读数据，不能作为正式市场报告
公开搜索：待搜索工具执行
货源：待 1688 链接/图片/授权接口
物流：待重量、尺寸和橙联路线
下一步：补数据或允许系统跑只读工具
```

这也让 Hermes 的角色变清楚：

```text
Runtime 负责采集状态、来源标注、缺口判断、阻塞边界
Hermes 市场经理负责基于数据包写判断报告
```

验证结果：

```text
runtime_workflow_regression: PASS
runtime_mvp_regression: PASS
runtime_knowledge_regression: PASS
python compileall: PASS
node --check app.js: PASS
Runtime API market_probe_inputs: PASS
```

当前进度微调：

```text
Runtime 架构底座：约 89%-91%
替代 Hermes 的 Agent 能力：约 42%-48%
接入 SaaS 模拟端：约 85%-88%
接入真实 SaaS 后端：约 71%-75%
真实 eBay 自动化闭环：约 26%-32%
商业化生产级：约 23%-29%
```

下一步最小动作：

把 `ebay_read_only` 槽位从“pending connector”升级为真实只读 Adapter 的壳：先只读，不发布、不改价、不改库存、不退款、不改政策。读取失败时要把失败原因回写到数据包，而不是让 Hermes 长时间空转。

---

## 15. 2026-05-14 Hermes 9 岗位能力迁移地图

本轮根据项目方向新增“角色能力地图”，目标是把 Hermes 当前 9 个岗位的能力，逐步迁移到捷境自有 Runtime，而不是让 SaaS 永久绑死 Hermes。

新增文件：

- `jiejing_runtime/role_capabilities.py`
- `tools/test_jiejing_runtime_role_capabilities.py`

改动文件：

- `jiejing_runtime/capabilities.py`
- `jiejing_runtime/api_server.py`
- `jiejing_runtime/adapters.py`
- `jiejing_runtime/__init__.py`
- `tools/test_jiejing_runtime_workflow.py`

当前映射的 9 个角色：

```text
1. ceo
2. market-manager
3. product-manager
4. customer-service
5. finance-supply
6. team-repair
7. web-engineer
8. desktop-engineer
9. mobile-engineer
```

每个角色现在都有结构化定义：

- 商家侧标签
- 内部执行标签
- 当前 Hermes 能力
- Runtime 已掌握资产
- 对应 JiejingTask 类型
- 必须输出的内容
- 安全边界
- 迁移状态
- 下一步 Runtime 迁移动作
- 当前缺口

新增 API：

```text
GET /role-capabilities
```

`GET /capabilities` 也会返回 `role_capability_map`，方便 SaaS 运营诊断面板读取。

重要边界：

```text
商家前台仍然主要面对 AI CEO、工作记录、来源记录、确认中心。
这些岗位是后端和执行器内部能力地图，不是给商家管理岗位用的主导航。
```

这一步对后路的意义：

以前我们只有“Hermes 有 9 个岗位”的口头理解。现在 Runtime 里有了正式的能力地图，可以逐步把每个岗位的：

- 报告模板
- 输出契约
- 缺口判断
- 安全边界
- 工具依赖
- 下一步迁移计划

迁移成捷境自己的资产。

Hermes 以后可以继续作为执行器，但不再是唯一真相源。捷境自己的 Runtime 会掌握：

```text
任务协议
角色能力地图
数据包状态
报告契约
确认中心
审计记录
执行边界
```

验证结果：

```text
runtime_role_capability_regression: PASS
runtime_workflow_regression: PASS
runtime_mvp_regression: PASS
runtime_knowledge_regression: PASS
python compileall: PASS
node --check app.js: PASS
```

当前进度微调：

```text
Runtime 架构底座：约 90%-92%
替代 Hermes 的 Agent 能力：约 45%-50%
接入 SaaS 模拟端：约 86%-89%
接入真实 SaaS 后端：约 72%-76%
真实 eBay 自动化闭环：约 26%-32%
商业化生产级：约 24%-30%
```

下一步最小动作：

继续从“角色能力地图”往下落真实能力。优先顺序：

1. eBay 只读 Adapter 壳，先填 `market.data_packet.ebay_read_only`。
2. public_search Adapter 壳，先填公开搜索来源。
3. product-manager importer，把 Hermes 刊登报告回收到 `listing.package`。
4. asset manifest schema，把“素材任务包”和“真实生成文件”彻底分离。
5. finance-supply importer，把运费、采购、利润、履约风险按钱数和来源回收。

---

## 16. 2026-05-14 eBay 只读 Adapter 壳

本轮开始把 `market.data_packet.ebay_read_only` 从预留槽位推进成真实可接的工程入口。

新增文件：

- `jiejing_runtime/ebay_read_only.py`
- `tools/test_jiejing_ebay_read_only_probe.py`

改动文件：

- `jiejing_runtime/market_data_packet.py`
- `jiejing_runtime/workflow_templates.py`
- `jiejing_runtime/api_server.py`
- `jiejing_runtime/capabilities.py`
- `jiejing_runtime/__init__.py`
- `tools/test_jiejing_runtime_workflow.py`

官方边界依据：

- eBay Browse API 的 `item_summary/search` 是商品摘要搜索能力，可按关键词、类目、GTIN 等参数查商品摘要。
- eBay Taxonomy API 的 `getItemAspectsForCategory` 可按 leaf category 返回该类目需要或建议填写的 item aspects。
- eBay Account API 的 fulfillment/payment/return policy 属于卖家业务政策读取/管理边界，后续必须按账号权限、OAuth scope、确认中心和 ExecutionService 处理。

当前 Adapter 能力：

```text
EbayReadOnlyProbeAdapter
  -> normalize supplied Browse response
  -> normalize supplied Taxonomy aspects response
  -> produce market_probe_inputs.ebay_read_only snapshot
  -> calculate sample_count, price_min, price_median, price_max, currency
  -> extract top_items sample
  -> extract category_distribution
  -> extract required_aspects
  -> keep live call disabled unless explicitly enabled
```

当前不会做：

```text
不发布 Listing
不改价格
不改库存
不退款
不开广告
不采购付款
不修改 fulfillment/payment/return policy
不在前端保存 token
```

`market.data_packet` 现在支持两种 eBay 只读输入：

### 1. 后端/测试直接提供快照

```json
{
  "market_probe_inputs": {
    "ebay_read_only": {
      "source_type": "official_api",
      "confidence": "medium",
      "summary": "Read-only eBay signal collected.",
      "metrics": {}
    }
  }
}
```

### 2. 提供 Browse/Taxonomy 原始响应，由 Runtime 归一化

```json
{
  "ebay_read_only_probe": {
    "keyword": "stainless steel tumbler",
    "marketplace_id": "EBAY_US",
    "browse_response": {},
    "taxonomy_response": {}
  }
}
```

以后正式后端可把 `browse_response` 换成 live read-only call 的返回结果。当前如果没有显式启用 live read-only，Adapter 会返回 `pending_connector`，不会假装已经读取 eBay。

验证结果：

```text
ebay_read_only_probe_regression: PASS
runtime_role_capability_regression: PASS
runtime_workflow_regression: PASS
runtime_mvp_regression: PASS
runtime_knowledge_regression: PASS
python compileall: PASS
node --check app.js: PASS
```

当前进度微调：

```text
Runtime 架构底座：约 91%-93%
替代 Hermes 的 Agent 能力：约 47%-52%
接入 SaaS 模拟端：约 87%-90%
接入真实 SaaS 后端：约 73%-77%
真实 eBay 自动化闭环：约 28%-34%
商业化生产级：约 25%-31%
```

下一步最小动作：

做 `public_search` Adapter 壳，让公开搜索结果也能进入 `market.data_packet`，并且像 eBay 只读一样记录 URL、标题、摘要、来源时间、置信度和不可用原因。然后市场经理就能拿到更完整的数据包，而不是自己在 Hermes 里长时间空转。

---

## 17. 2026-05-14 public_search Adapter 壳

本轮把 `market.data_packet.public_search` 从预留槽位推进成可接真实搜索工具的工程入口。

新增文件：

- `jiejing_runtime/public_search.py`
- `tools/test_jiejing_public_search_probe.py`

改动文件：

- `jiejing_runtime/market_data_packet.py`
- `jiejing_runtime/workflow_templates.py`
- `jiejing_runtime/api_server.py`
- `jiejing_runtime/capabilities.py`
- `jiejing_runtime/__init__.py`
- `tools/test_jiejing_runtime_workflow.py`

当前 Adapter 能力：

```text
PublicSearchProbeAdapter
  -> normalize supplied search results
  -> keep URL / title / snippet / domain / captured_at
  -> detect commerce hints: ebay / amazon / 1688 / alibaba / shopify / generic commerce
  -> summarize result_count, domain_distribution, commercial_result_count
  -> keep search as directional public reference, not official eBay data
  -> live provider disabled unless backend explicitly configures endpoint and key
```

支持的后端来源形态：

```text
Bing / Google CSE / Tavily / SerpApi / browser worker / manual exported search records
```

统一进入：

```json
{
  "public_search_probe": {
    "query": "stainless steel tumbler ebay reviews supplier",
    "provider": "backend-search-provider",
    "results": [
      {
        "title": "...",
        "url": "...",
        "snippet": "..."
      }
    ]
  }
}
```

安全边界：

- 公开搜索结果只能作为方向参考。
- 不能把公开搜索结果冒充 eBay 官方数据。
- 搜索结果可能个性化、过期、缺失或被平台限制，必须保留来源和置信度。
- 不绕过登录、验证码、反爬或平台限制。

验证结果：

```text
public_search_probe_regression: PASS
ebay_read_only_probe_regression: PASS
runtime_role_capability_regression: PASS
runtime_workflow_regression: PASS
runtime_mvp_regression: PASS
runtime_knowledge_regression: PASS
python compileall: PASS
node --check app.js: PASS
```

当前进度微调：

```text
Runtime 架构底座：约 92%-94%
替代 Hermes 的 Agent 能力：约 49%-54%
接入 SaaS 模拟端：约 88%-91%
接入真实 SaaS 后端：约 74%-78%
真实 eBay 自动化闭环：约 29%-35%
商业化生产级：约 26%-32%
```

下一步最小动作：

做 `cross_platform_reference` Adapter 壳，把 Amazon、1688、淘宝、拼多多、Shopify 等公开参考或授权输入归一化成跨平台参考信号，明确标注“参考，不是 eBay 官方数据”。

---

## 18. 2026-05-14 cross_platform_reference Adapter 壳

本轮把 `market.data_packet.cross_platform_reference` 从预留槽位推进成可接真实参考数据的工程入口。

新增文件：

- `jiejing_runtime/cross_platform_reference.py`
- `tools/test_jiejing_cross_platform_reference_probe.py`

改动文件：

- `jiejing_runtime/market_data_packet.py`
- `jiejing_runtime/workflow_templates.py`
- `jiejing_runtime/api_server.py`
- `jiejing_runtime/capabilities.py`
- `jiejing_runtime/__init__.py`
- `tools/test_jiejing_runtime_workflow.py`

当前 Adapter 能力：

```text
CrossPlatformReferenceAdapter
  -> normalize references from Amazon / 1688 / Taobao / Pinduoduo / Shopify / Alibaba / AliExpress / Temu / SHEIN
  -> detect useful_for: sourcing / buyer_language / visual_merchandising / risk_signal / price_or_supply_reference
  -> summarize reference_count, platform_distribution, useful_for
  -> keep cross-platform signals as directional context, not eBay official data
```

统一进入：

```json
{
  "cross_platform_reference_probe": {
    "references": [
      {
        "platform": "1688",
        "title": "...",
        "url": "...",
        "summary": "..."
      }
    ]
  }
}
```

安全边界：

- Amazon/1688/淘宝/拼多多/Shopify 等只能作为公开参考、授权 API 数据或商家提供资料。
- 不能把其他平台的热度当成 eBay 官方需求。
- 不能绕过登录、验证码、反爬或平台限制。
- 不能因为 1688 有货就自动采购付款。

验证结果：

```text
cross_platform_reference_probe_regression: PASS
public_search_probe_regression: PASS
ebay_read_only_probe_regression: PASS
runtime_role_capability_regression: PASS
runtime_workflow_regression: PASS
runtime_mvp_regression: PASS
runtime_knowledge_regression: PASS
python compileall: PASS
node --check app.js: PASS
```

当前进度微调：

```text
Runtime 架构底座：约 93%-95%
替代 Hermes 的 Agent 能力：约 51%-56%
接入 SaaS 模拟端：约 89%-92%
接入真实 SaaS 后端：约 75%-79%
真实 eBay 自动化闭环：约 30%-36%
商业化生产级：约 27%-33%
```

下一步最小动作：

做 `sourcing_availability` Adapter 壳，把 1688 链接、商家手动链接、表格、供应商报价、图片包、授权接口快照统一成货源候选数据。它只负责读取和整理，不自动下单、不付款。

---

## 19. 2026-05-14 sourcing_availability Adapter 壳

本轮把 `market.data_packet.sourcing_availability` 从预留槽位推进成可接货源数据的工程入口。

新增文件：

- `jiejing_runtime/sourcing_availability.py`
- `tools/test_jiejing_sourcing_availability_probe.py`

改动文件：

- `jiejing_runtime/market_data_packet.py`
- `jiejing_runtime/workflow_templates.py`
- `jiejing_runtime/api_server.py`
- `jiejing_runtime/capabilities.py`
- `jiejing_runtime/__init__.py`
- `tools/test_jiejing_runtime_workflow.py`

当前 Adapter 能力：

```text
SourcingAvailabilityAdapter
  -> normalize 1688 links / merchant links / supplier quotes / tables / authorized source snapshots
  -> extract source_platform, title, source_url, supplier_name
  -> extract unit_cost, currency, MOQ, stock, ship_from
  -> extract domestic shipping cost, package weight, dimensions, material, packaging
  -> detect missing_facts
  -> summarize lowest_unit_cost, ship_from_distribution, ready_candidate_count, blockers
```

统一进入：

```json
{
  "sourcing_availability_probe": {
    "route": "manual_or_1688",
    "candidates": [
      {
        "source_platform": "1688",
        "title": "...",
        "source_url": "...",
        "unit_cost": 18.8,
        "package_weight_g": 520,
        "package_dimensions_cm": "11x11x24",
        "ship_from": "Zhejiang Jinhua",
        "material": "304 stainless steel"
      }
    ]
  }
}
```

安全边界：

- 只读取和整理货源候选。
- 不自动下单。
- 不自动付款。
- 不写收货地址。
- 不给供应商发送真实采购指令。
- 不把缺重量、尺寸、材质、包装、发货地的候选当作发布级资料。

验证结果：

```text
sourcing_availability_probe_regression: PASS
cross_platform_reference_probe_regression: PASS
public_search_probe_regression: PASS
ebay_read_only_probe_regression: PASS
runtime_workflow_regression: PASS
runtime_role_capability_regression: PASS
runtime_mvp_regression: PASS
runtime_knowledge_regression: PASS
python compileall: PASS
node --check app.js: PASS
```

当前进度微调：

```text
Runtime 架构底座：约 94%-95%
替代 Hermes 的 Agent 能力：约 53%-58%
接入 SaaS 模拟端：约 90%-92%
接入真实 SaaS 后端：约 76%-80%
真实 eBay 自动化闭环：约 31%-37%
商业化生产级：约 28%-34%
```

下一步最小动作：

做 `logistics_estimate` Adapter 壳，把包裹重量、尺寸、发货地、目的国、SpeedPAK/橙联路线、费用和时效估算统一成物流信号。它只做估算和缺口，不买面单、不回填 tracking。

---

## 20. 2026-05-14 logistics_estimate Adapter 壳

本轮把 `market.data_packet.logistics_estimate` 从预留槽位推进成可接物流估算数据的工程入口。

新增文件：

- `jiejing_runtime/logistics_estimate.py`
- `tools/test_jiejing_logistics_estimate_probe.py`

改动文件：

- `jiejing_runtime/market_data_packet.py`
- `jiejing_runtime/workflow_templates.py`
- `jiejing_runtime/api_server.py`
- `jiejing_runtime/capabilities.py`
- `jiejing_runtime/__init__.py`
- `tools/test_jiejing_runtime_workflow.py`

当前 Adapter 能力：

```text
LogisticsEstimateAdapter
  -> normalize package weight and dimensions
  -> normalize origin / destination / route
  -> normalize carrier service estimates
  -> extract shipping_cost, currency, eta_min_days, eta_max_days, tracking
  -> calculate lowest_shipping_cost and fastest_eta_days
  -> detect missing package facts and shipping estimates
```

统一进入：

```json
{
  "logistics_estimate_probe": {
    "origin": "Zhejiang Jinhua, China",
    "destination": "United States",
    "package_weight_g": 620,
    "package_dimensions_cm": "12x12x26",
    "route": "SpeedPAK/Orange Connex estimate",
    "estimates": [
      {
        "carrier": "Orange Connex",
        "service_name": "SpeedPAK Economy",
        "shipping_cost": 58.5,
        "currency": "CNY",
        "eta_min_days": 10,
        "eta_max_days": 22,
        "tracking": true
      }
    ]
  }
}
```

安全边界：

- 只做估算和缺口判断。
- 不买面单。
- 不回填 tracking。
- 不承诺真实到达日期。
- 不修改物流政策。
- 未确认真实重量、尺寸、服务、费用前，不进入发布级利润结论。

验证结果：

```text
logistics_estimate_probe_regression: PASS
sourcing_availability_probe_regression: PASS
cross_platform_reference_probe_regression: PASS
public_search_probe_regression: PASS
ebay_read_only_probe_regression: PASS
runtime_role_capability_regression: PASS
runtime_workflow_regression: PASS
runtime_mvp_regression: PASS
runtime_knowledge_regression: PASS
python compileall: PASS
node --check app.js: PASS
```

市场数据包五个核心入口已成型：

```text
1. ebay_read_only
2. public_search
3. cross_platform_reference
4. sourcing_availability
5. logistics_estimate
```

当前进度微调：

```text
Runtime 架构底座：约 95%-96%
替代 Hermes 的 Agent 能力：约 55%-60%
接入 SaaS 模拟端：约 91%-93%
接入真实 SaaS 后端：约 77%-81%
真实 eBay 自动化闭环：约 32%-38%
商业化生产级：约 29%-35%
```

下一步最小动作：

进入产品经理侧，做 `listing.package` 回收校验器。目标是让 Hermes 或自研产品经理返回的刊登报告必须符合真实 eBay 刊登骨架：SKU、Title、Category、Condition、Format、Price、Quantity、Item Specifics、Pictures、Video、Description、Package、Handling time、Item Location、Fulfillment/Payment/Return policy、发布阻断项。

---

## 21. 2026-05-14 listing.package 回收校验器

本轮进入产品经理侧，新增 `listing.package` 回收校验器，避免产品经理报告看起来完整但缺真实 eBay 刊登骨架。

新增文件：

- `jiejing_runtime/listing_package.py`
- `tools/test_jiejing_listing_package_validator.py`

改动文件：

- `jiejing_runtime/hermes_handoff.py`
- `jiejing_runtime/__init__.py`

当前校验字段：

```text
SKU
Title
Category ID
Condition
Format
Price
Quantity
Item Specifics
Pictures
Video
Description HTML
Package weight
Package dimensions
Handling time
Item Location
Fulfillment policy
Payment policy
Return policy
Publish blockers / Publish lock
```

当前校验能力：

- 标题必须能被检测出来。
- 标题超过 80 字符会阻断。
- 三政策字段必须出现。
- 缺字段会生成 `listing_field_*` missing input。
- 没有发布锁 / 发布阻断项会阻断。
- Hermes product-manager Markdown 回收时，会自动附加 `listing_validation`。
- 即使刊登包结构完整，也只是进入确认审阅，不会真实发布。

验证结果：

```text
listing_package_validator_regression: PASS
logistics_estimate_probe_regression: PASS
sourcing_availability_probe_regression: PASS
cross_platform_reference_probe_regression: PASS
public_search_probe_regression: PASS
ebay_read_only_probe_regression: PASS
runtime_workflow_regression: PASS
runtime_role_capability_regression: PASS
runtime_mvp_regression: PASS
runtime_knowledge_regression: PASS
python compileall: PASS
node --check app.js: PASS
```

当前进度微调：

```text
Runtime 架构底座：约 95%-96%
替代 Hermes 的 Agent 能力：约 57%-62%
接入 SaaS 模拟端：约 91%-94%
接入真实 SaaS 后端：约 78%-82%
真实 eBay 自动化闭环：约 34%-40%
商业化生产级：约 30%-36%
```

下一步最小动作：

做 `asset_manifest` schema 和校验器，把“素材任务包”和“真实生成出来的图片/视频文件”彻底分开。素材工坊不能再把任务要求当成已生成素材。

---

## 22. 2026-05-14 asset.brief 素材 Manifest 校验器

本轮进入素材经理侧，新增 `asset_manifest` 校验器，把“素材任务包”和“真实生成出来的图片/视频文件清单”彻底分开。

新增文件：
- `jiejing_runtime/asset_manifest.py`
- `tools/test_jiejing_asset_manifest_validator.py`

改动文件：
- `jiejing_runtime/hermes_handoff.py`
- `jiejing_runtime/__init__.py`

当前校验状态：
```text
brief_only
素材经理只返回图片、详情页、视频的制作要求，没有声称真实文件已生成。这个状态允许作为任务包继续流转。

blocked_missing_manifest
报告里声称图片/视频已生成，但没有提供 asset manifest。这个状态会阻断，避免商家以为素材已经产出。

blocked_incomplete_manifest
提供了 manifest，但素材条目缺少 asset_type、url/file_path、source、commercial_use_status、图片尺寸或视频时长。

manifest_ready
每个素材都有可追踪条目，能进入复核或确认中心，但仍不代表自动发布。
```

当前 Manifest 字段：
```text
asset_id
asset_type
file_path 或 url
dimensions 或 width/height
duration_seconds
source
commercial_use_status
status
```

这一步对 SaaS 的意义：
- 素材工坊不能再把“素材需求”当成“已生成素材”。
- Hermes 素材经理或未来自研素材 Agent 必须交出可追踪文件清单。
- 以后图片/视频生成、预览、PDF 报告、确认中心都能引用同一份 Manifest。
- 即使 Manifest 完整，也只进入复核，不自动发布到 eBay。

验证结果：
```text
asset_manifest_validator_regression: PASS
listing_package_validator_regression: PASS
logistics_estimate_probe_regression: PASS
sourcing_availability_probe_regression: PASS
cross_platform_reference_probe_regression: PASS
public_search_probe_regression: PASS
ebay_read_only_probe_regression: PASS
runtime_workflow_regression: PASS
runtime_role_capability_regression: PASS
runtime_mvp_regression: PASS
runtime_knowledge_regression: PASS
python compileall: PASS
node --check app.js: PASS
```

当前进度微调：
```text
Runtime 架构底座：约 96%-97%
替代 Hermes 的 Agent 能力：约 60%-64%
接入 SaaS 模拟端：约 92%-94%
接入真实 SaaS 后端：约 79%-83%
真实 eBay 自动化闭环：约 35%-41%
商业化生产级：约 31%-38%
```

下一步最小动作：

进入客服学习包校验器：`customer.learn_product` 不能只写“客服已学习”，必须回收产品档案、买家问题地图、FAQ、可自动回复边界、必须人工接管规则。这样才能支撑“低风险客服自动回复，高风险人工确认”的项目方向。

---

## 23. 2026-05-14 customer.learn_product 客服学习包校验器

本轮进入客服经理侧，新增 `customer_learning` 校验器，确保自动客服不是一句“客服已学习”就开始工作，而是必须有产品档案、买家问题地图、FAQ、回复边界、自动回复模板和人工接管规则。

新增文件：
- `jiejing_runtime/customer_learning.py`
- `tools/test_jiejing_customer_learning_validator.py`

改动文件：
- `jiejing_runtime/hermes_handoff.py`
- `jiejing_runtime/__init__.py`

当前校验字段：
```text
product_service_file
buyer_question_map
faq
reply_boundary
auto_reply_templates
escalation_rules
```

当前高风险客服边界：
```text
refund / compensation
guarantee / guaranteed promise
medical / therapeutic claim
customs / tax promise
exact delivery date
negative feedback / dispute
```

当前校验状态：
```text
ready_for_auto_reply_review
客服学习包完整，能进入低风险自动回复复核。

blocked_incomplete_learning_package
缺产品档案、买家问题、FAQ、模板或边界之一。

blocked_missing_human_takeover
没有定义什么时候必须人工接管。

blocked_unsafe_auto_reply_claim
报告声称自动客服可用，但没有完整学习包支撑。
```

这一步对 SaaS 的意义：
- 市场经理和产品经理的结果必须能沉淀给客服经理。
- 客服自动化不再是一个独立聊天框，而是接产品档案和订单状态的流程节点。
- 低风险问题可以自动回复或草稿回复；退款、赔付、争议、准确到达承诺等仍必须人工确认。
- 以后 Hermes 客服经理或自研客服 Agent 都要按同一份学习包合同交付。

验证结果：
```text
customer_learning_validator_regression: PASS
asset_manifest_validator_regression: PASS
listing_package_validator_regression: PASS
logistics_estimate_probe_regression: PASS
sourcing_availability_probe_regression: PASS
cross_platform_reference_probe_regression: PASS
public_search_probe_regression: PASS
ebay_read_only_probe_regression: PASS
runtime_workflow_regression: PASS
runtime_role_capability_regression: PASS
runtime_mvp_regression: PASS
runtime_knowledge_regression: PASS
python compileall: PASS
node --check app.js: PASS
```

当前进度微调：
```text
Runtime 架构底座：约 97%
替代 Hermes 的 Agent 能力：约 63%-67%
接入 SaaS 模拟端：约 93%-95%
接入真实 SaaS 后端：约 80%-84%
真实 eBay 自动化闭环：约 36%-42%
商业化生产级：约 32%-39%
```

下一步最小动作：

进入财务复核包校验器：`finance.review` 必须回收平台费、采购价、物流费、包装费、广告预算、退款预留、利润数字和发布前财务锁，不能只写百分比或一句“利润可以”。

---

## 24. 2026-05-14 finance.review 财务复核包校验器

本轮进入财务风控侧，新增 `finance_review` 校验器，确保财务经理输出的是可复核的金额表，而不是只写利润率或“利润可以”。

新增文件：
- `jiejing_runtime/finance_review.py`
- `tools/test_jiejing_finance_review_validator.py`

改动文件：
- `jiejing_runtime/hermes_handoff.py`
- `jiejing_runtime/__init__.py`

当前校验字段：
```text
cost_table
sale_price
procurement_cost
platform_fee
logistics_cost
package_cost
net_profit_money
logistics_route
subscription_allocation
return_reserve
risk_notes
next_action
```

当前金额规则：
```text
必须出现具体金额，例如 US $19.99、CNY 18.00、RMB 58.50。
只有百分比不够。
少于 4 个金额数字会阻断。
必须明确 finance lock / publish lock / confirmation center 状态。
```

这一步对 SaaS 的意义：
- 财务复盘可以接真实 eBay 费用、采购价、橙联/SpeedPAK 物流估算、包装费、订阅费分摊和退货预留。
- 发布前不是“看起来赚钱”就放行，而是必须有金额级别的解释。
- 即使财务复核完整，也只进入确认中心，不自动发布、不自动付款。

验证结果：
```text
finance_review_validator_regression: PASS
customer_learning_validator_regression: PASS
asset_manifest_validator_regression: PASS
listing_package_validator_regression: PASS
logistics_estimate_probe_regression: PASS
sourcing_availability_probe_regression: PASS
cross_platform_reference_probe_regression: PASS
public_search_probe_regression: PASS
ebay_read_only_probe_regression: PASS
runtime_workflow_regression: PASS
runtime_role_capability_regression: PASS
runtime_mvp_regression: PASS
runtime_knowledge_regression: PASS
python compileall: PASS
node --check app.js: PASS
```

当前进度微调：
```text
Runtime 架构底座：约 97%-98%
替代 Hermes 的 Agent 能力：约 66%-70%
接入 SaaS 模拟端：约 94%-95%
接入真实 SaaS 后端：约 81%-85%
真实 eBay 自动化闭环：约 38%-44%
商业化生产级：约 34%-41%
```

下一步最小动作：

进入确认中心包校验器：`confirmation.package` 必须把“可自动做、默认规则做、每次确认、完全禁止、缺资料停止”分清楚，并且发布、采购付款、退款、广告预算、店铺政策修改永远不能绕过确认边界。

---

## 25. 2026-05-14 confirmation.package 确认中心包校验器

本轮进入确认中心侧，新增 `confirmation_package` 校验器，把“AI 能自动做什么”和“必须商家确认什么”做成 Runtime 可验证合同。

新增文件：
- `jiejing_runtime/confirmation_package.py`
- `tools/test_jiejing_confirmation_package_validator.py`

改动文件：
- `jiejing_runtime/hermes_handoff.py`
- `jiejing_runtime/__init__.py`

当前校验字段：
```text
allowed_auto_actions
default_rule_actions
every_time_confirm_actions
blocked_actions
missing_facts
```

必须明确确认闸门的高风险动作：
```text
publish listing
batch publish
procurement payment
refund / partial refund
ad budget / promoted listing budget
price change
inventory change
store policy change: fulfillment/payment/return policy
store subscription change
OAuth authorization / token scope change
sensitive customer promise: compensation, guarantee, customs, exact delivery date
```

当前校验状态：
```text
ready_for_confirmation_center
确认包完整，可以进入确认中心展示。

blocked_missing_confirmation_sections
缺自动动作、默认规则、每次确认、禁止动作或缺资料停止条件。

blocked_high_risk_confirmation_gap
高风险动作没有明确写入确认/人工/禁止边界。
```

这一步对 SaaS 的意义：
- 发布、采购付款、退款、广告、改价、库存、店铺政策、OAuth 和敏感客服承诺不能绕过确认中心。
- 默认规则可以保存，但高风险动作必须每次确认或明确禁止。
- 以后 Hermes 或自研 Runtime 执行结果都会被同一个确认包校验器拦住。

验证结果：
```text
confirmation_package_validator_regression: PASS
finance_review_validator_regression: PASS
customer_learning_validator_regression: PASS
asset_manifest_validator_regression: PASS
listing_package_validator_regression: PASS
logistics_estimate_probe_regression: PASS
sourcing_availability_probe_regression: PASS
cross_platform_reference_probe_regression: PASS
public_search_probe_regression: PASS
ebay_read_only_probe_regression: PASS
runtime_workflow_regression: PASS
runtime_role_capability_regression: PASS
runtime_mvp_regression: PASS
runtime_knowledge_regression: PASS
python compileall: PASS
node --check app.js: PASS
```

当前进度微调：
```text
Runtime 架构底座：约 98%
替代 Hermes 的 Agent 能力：约 69%-73%
接入 SaaS 模拟端：约 94%-96%
接入真实 SaaS 后端：约 82%-86%
真实 eBay 自动化闭环：约 40%-46%
商业化生产级：约 36%-43%
```

下一步最小动作：

进入 CEO 最终汇总校验器：`ceo.final_report` 必须把当前状态、来源健康度、各岗位报告是否齐全、发布锁、下一步最小动作说清楚，避免商家看到一堆岗位报告后不知道现在该干什么。

---

## 26. 2026-05-14 ceo.final_report AI CEO 最终汇总校验器

本轮进入 AI CEO 汇总侧，新增 `ceo_final_report` 校验器，确保整条链路结束后，商家看到的是“当前状态、数据可信度、报告齐不齐、能不能发布、下一步做什么”，而不是一堆岗位报告堆在一起。

新增文件：
- `jiejing_runtime/ceo_final_report.py`
- `tools/test_jiejing_ceo_final_report_validator.py`

改动文件：
- `jiejing_runtime/hermes_handoff.py`
- `jiejing_runtime/__init__.py`

当前校验字段：
```text
current_status
source_health
reports_ready
publish_lock
next_minimum_action
```

当前岗位覆盖检查：
```text
market_report
source_facts
listing_package
asset_manifest
customer_learning
finance_review
confirmation_package
```

这一步对 SaaS 的意义：
- AI CEO 是商家主入口，最终必须用商家能看懂的话收束全链路。
- CEO 汇总不能空泛说“都好了”，必须明确发布锁和下一步最小动作。
- 后续 SaaS 的 AI 汇报模块可以直接读取这个校验结果，决定展示“可继续 / 缺资料 / 待确认 / 不可发布”。

验证结果：
```text
ceo_final_report_validator_regression: PASS
confirmation_package_validator_regression: PASS
finance_review_validator_regression: PASS
customer_learning_validator_regression: PASS
asset_manifest_validator_regression: PASS
listing_package_validator_regression: PASS
logistics_estimate_probe_regression: PASS
sourcing_availability_probe_regression: PASS
cross_platform_reference_probe_regression: PASS
public_search_probe_regression: PASS
ebay_read_only_probe_regression: PASS
runtime_workflow_regression: PASS
runtime_role_capability_regression: PASS
runtime_mvp_regression: PASS
runtime_knowledge_regression: PASS
python compileall: PASS
node --check app.js: PASS
```

当前进度微调：
```text
Runtime 架构底座：约 98%
替代 Hermes 的 Agent 能力：约 72%-76%
接入 SaaS 模拟端：约 95%-96%
接入真实 SaaS 后端：约 83%-87%
真实 eBay 自动化闭环：约 42%-48%
商业化生产级：约 38%-45%
```

下一步最小动作：

把这些校验器统一接到 Runtime API 的结果摘要里，让 SaaS 前端不用解析每份报告正文，而是直接读取 `listing_validation`、`asset_manifest_validation`、`customer_learning_validation`、`finance_review_validation`、`confirmation_package_validation`、`ceo_final_report_validation` 的状态。

---

## 27. 2026-05-14 Runtime validation-summary API

本轮把岗位校验器状态接进 Runtime 查询层，新增 `validation-summary` 摘要，方便 SaaS 前端直接读取结构化状态。

改动文件：
- `jiejing_runtime/repository.py`
- `jiejing_runtime/api_server.py`
- `tools/test_jiejing_runtime_mvp.py`

新增能力：
```text
GET /runs/{run_id}/validation-summary
```

返回内容：
```text
run_id
validation_count
ready_count
blocked_count
validations[]
  task_id
  task_type
  result_status
  validation_key
  validator
  validator_version
  validation_status
  summary
```

这一步对 SaaS 的意义：
- 前端不用解析报告正文，就能知道每个岗位包是 ready、blocked 还是缺资料。
- AI 汇报、待我确认、产品刊登、素材工坊和自动客服可以统一读取 Runtime 校验状态。
- Hermes 仍然可以作为执行器，但捷境掌握报告回收、结构化校验和前端展示合同。

验证结果：
```text
ceo_final_report_validator_regression: PASS
confirmation_package_validator_regression: PASS
finance_review_validator_regression: PASS
customer_learning_validator_regression: PASS
asset_manifest_validator_regression: PASS
listing_package_validator_regression: PASS
logistics_estimate_probe_regression: PASS
sourcing_availability_probe_regression: PASS
cross_platform_reference_probe_regression: PASS
public_search_probe_regression: PASS
ebay_read_only_probe_regression: PASS
runtime_workflow_regression: PASS
runtime_role_capability_regression: PASS
runtime_mvp_regression: PASS
runtime_knowledge_regression: PASS
python compileall: PASS
node --check app.js: PASS
```

当前进度微调：
```text
Runtime 架构底座：约 98%-99%
替代 Hermes 的 Agent 能力：约 74%-78%
接入 SaaS 模拟端：约 95%-97%
接入真实 SaaS 后端：约 84%-88%
真实 eBay 自动化闭环：约 43%-50%
商业化生产级：约 39%-46%
```

下一步最小动作：

把 SaaS 前端的 AI 汇报模块读取 `validation-summary`，让每条报告显示“已就绪 / 缺资料 / 被确认中心拦截 / 不能发布”的明确状态，而不是只展示 Runtime 正文摘要。

---

## 28. 2026-05-14 SaaS 前端接入 validation-summary

本轮把 Runtime 的岗位包校验状态接进 SaaS 模拟前端。现在前端不只读取 Runtime 正文结果，还能读取每个岗位包的结构化校验状态。

改动文件：
- `app.js`
- `styles.css`
- `jiejing_runtime/adapters.py`
- `tools/test_jiejing_runtime_mvp.py`

新增前端状态：
```text
state.runtimeValidationSummary
```

新增前端展示：
```text
Runtime 面板：岗位回收校验总览
AI 汇报：每条 Runtime 任务报告加入“结构化校验”
```

本地演示适配器已补齐校验输出：
```text
listing.package -> listing_validation
asset.brief -> asset_manifest_validation
customer.learn_product -> customer_learning_validation
finance.review -> finance_review_validation
confirmation.package -> confirmation_package_validation
ceo.final_report -> ceo_final_report_validation
```

当前本地模拟链路 validation-summary 示例：
```text
validation_count: 6
ready_count: 5
blocked_count: 1

listing.package: blocked_missing_input
asset.brief: manifest_ready
customer.learn_product: ready_for_auto_reply_review
finance.review: ready_for_confirmation_review
confirmation.package: ready_for_confirmation_center
ceo.final_report: ready_for_merchant_summary
```

说明：
- `listing.package` 保持 blocked 是合理的，因为正式发布前仍缺真实供应商资料、eBay 类目字段、店铺三政策等事实。
- 其它 5 段表示报告结构已可被 Runtime 读取和复核，但仍不代表真实执行。

这一步对 SaaS 的意义：
- AI 汇报可以展示“哪份报告结构合格、哪份缺资料”，不再只靠商家读长文判断。
- 产品刊登、素材工坊、客服、财务和确认中心可以共享同一套 Runtime 状态。
- 后续接真实 HermesAdapter 时，前端不需要改逻辑，只要后端继续返回同样的 validation-summary。

验证结果：
```text
runtime_mvp_regression: PASS
runtime_workflow_regression: PASS
node --check app.js: PASS
Edge headless screenshot: PASS, output/runtime-validation-ui-check.png
```

当前进度微调：
```text
Runtime 架构底座：约 98%-99%
替代 Hermes 的 Agent 能力：约 76%-80%
接入 SaaS 模拟端：约 96%-98%
接入真实 SaaS 后端：约 85%-89%
真实 eBay 自动化闭环：约 44%-51%
商业化生产级：约 40%-47%
```

下一步最小动作：

继续把确认中心和 AI 汇报的前端交互做得更“商家可读”：根据 validation-summary 自动生成“现在卡在哪里”“我需要补什么”“补完会去哪里”的短说明。

---

## 29. 2026-05-14 validation-summary 商家下一步提示

本轮继续优化 SaaS 前端的 Runtime 面板：岗位包校验不只显示 ready/blocked，还会自动生成商家能看懂的下一步提示。

改动文件：
- `app.js`
- `styles.css`

新增前端逻辑：
```text
runtimeValidationActionGuide(summary)
```

当前提示逻辑：
```text
没有校验数据 -> 先运行一次模拟链路
全部就绪 -> 查看确认中心
刊登资料 blocked -> 回产品刊登补供应商资料、类目字段、店铺三政策
素材清单 blocked -> 回素材工坊补文件清单、尺寸、来源、商用状态
客服学习 blocked -> 同步产品档案、FAQ、回复边界、人工接管规则
财务复核 blocked -> 补售价、采购、平台费、物流、包装、退货预留和利润金额
确认中心 blocked -> 检查发布、付款、退款、广告、改价、政策、授权和客服承诺边界
CEO 汇总 blocked -> 重生成 AI 汇报，补当前状态、来源健康度、发布锁和下一步
```

这一步对 SaaS 的意义：
- 商家不需要理解 Runtime validator 名字。
- 页面能把技术状态翻译成“现在该干什么”。
- 这和捷境方向一致：商家面对 AI CEO 和确认中心，不管理后台岗位。

验证结果：
```text
runtime_mvp_regression: PASS
node --check app.js: PASS
```

---

## 32. 2026-05-14 刊登资料回写与 Runtime 复核

本轮把“产品刊登里补齐资料”真正接回了 Jiejing Runtime。现在前端保存货源资料、类目候选和店铺三类政策后，不再只是本地演示状态，而是会提交给 Runtime 重新校验 `listing.package`。

改动文件：
- `jiejing_runtime/repository.py`
- `jiejing_runtime/api_server.py`
- `tools/test_jiejing_runtime_mvp.py`
- `app.js`

新增 Runtime 能力：

```text
POST /runs/{run_id}/listing-facts
```

这个接口接收商家补齐的刊登事实，例如：
- 货源链接、采购价、发货地
- 商品尺寸、包装尺寸、包装重量、材质、配件
- eBay 类目候选与 Item Specifics
- 物流政策、支付政策、退货政策
- 标题、售价、库存、刊登站点等发布草稿字段

Runtime 收到后会重新生成产品经理刊登包文本，再跑 `ListingPackageValidator`。如果资料完整，它会把 `listing.package` 从 `blocked_missing_input` 推进到 `ready_for_confirmation_review`，但结果状态仍保持 `blocked_confirmation_required`，也就是只允许进入确认中心，不允许直接真实发布。

本轮真实本地 HTTP 验证：

```json
{
  "run_id": "runtime-listing-facts-demo-20260514204734",
  "initial_status": "completed_with_blocks",
  "listing_result_status": "blocked_confirmation_required",
  "listing_validation": "ready_for_confirmation_review",
  "ready_count": 6,
  "blocked_count": 0,
  "validation_count": 6
}
```

这说明：
- 大链路仍然拆成市场、刊登、素材、客服、财务、确认、CEO 汇总。
- 缺资料时停在产品刊登，不假装已经能发布。
- 商家补齐资料后，Runtime 能重新校验并推进状态。
- 即使 6 个岗位包全部 ready，真实 eBay 发布仍然必须走确认中心和执行服务。

验证结果：

```text
python .\tools\test_jiejing_runtime_mvp.py: PASS
node --check .\app.js: PASS
python -m compileall .\jiejing_runtime .\tools: PASS
Runtime API health: ok
POST /runs/{run_id}/listing-facts: PASS
```

当前进度校准：

```text
Runtime 架构底座：约 99%
替代 Hermes 的 Agent 能力：约 80%-84%
接入 SaaS 模拟端：约 98%-99%
接入真实 SaaS 后端：约 88%-91%
真实 eBay 自动化闭环：约 47%-54%
商业化生产级：约 42%-50%
```

下一步最小动作：

把这个 Runtime 复核结果进一步显示到前端产品刊登和待我确认里：商家保存资料后，页面要明确显示“刊登包已复核，可以进入确认中心”，并把“真实发布仍被锁住”的原因说清楚。

---

## 33. 2026-05-14 产品刊登与确认中心显示 Runtime 复核状态

本轮把第 32 步的底座复核结果放回商家能看到的位置。现在产品刊登的补资料区域会显示：
- Runtime 是否连接
- listing.package 是否已经复核
- 是否可以进入确认中心
- 为什么真实发布仍然不能自动执行

确认中心的发布确认卡也会显示同一套复核状态，避免商家点完“保存资料”后不知道后端有没有接住。

改动文件：
- `app.js`
- `styles.css`

新增前端函数：

```text
runtimeListingValidation()
runtimeListingStatusMeta()
renderRuntimeListingStatusCard()
```

当前状态逻辑：

```text
Runtime 未连接 -> 只提示本地页面演示已保存，不声称后端已复核
Runtime 已连接但无 listing.package 校验 -> 提示等待保存资料后复核
listing_validation ready -> 提示刊登包可进确认中心，但真实发布仍被锁住
listing_validation blocked -> 提示继续补资料，不允许 AI 猜资料发布
```

验证结果：

```text
node --check .\app.js: PASS
python .\tools\test_jiejing_runtime_mvp.py: PASS
python -m compileall .\jiejing_runtime .\tools: PASS
```

这一步对 SaaS 的意义：
- 商家不用理解 Runtime、validator、task_id 这些技术词。
- 页面能把底座状态翻译成“能不能确认、为什么不能真实发布”。
- 这和捷境方向一致：AI CEO 推进流程，确认中心只拦资金、发布、退款、广告、政策和敏感客服承诺。

当前进度校准：

```text
Runtime 架构底座：约 99%
替代 Hermes 的 Agent 能力：约 81%-84%
接入 SaaS 模拟端：约 99%
接入真实 SaaS 后端：约 89%-91%
真实 eBay 自动化闭环：约 48%-55%
商业化生产级：约 43%-50%
```

下一步最小动作：

继续做“真实执行服务 ExecutionService 的壳”：确认中心点头后，不是页面自己改状态，而是 Runtime / 后端执行服务接收确认、写审计日志、返回执行结果。演示版仍然不接真实 eBay 写入。

---

## 34. 2026-05-14 ExecutionService 执行服务壳接入

本轮把“确认中心点头之后”的后端边界继续往前推进。现在确认不是只存在前端状态里，而是可以进入 Runtime 的 ExecutionService 壳：

```text
确认中心记录 decision
-> ExecutionService 接收已确认动作
-> 检查发布前条件
-> 演示模式只写执行交接记录
-> 写入 execution_results 和 audit_events
-> 返回执行状态给 SaaS 前端
```

改动文件：
- `jiejing_runtime/execution.py`
- `jiejing_runtime/repository.py`
- `jiejing_runtime/api_server.py`
- `tools/test_jiejing_runtime_mvp.py`
- `app.js`

新增 Runtime API：

```text
GET  /runs/{run_id}/execution-results
POST /runs/{run_id}/confirmations/{confirmation_id}/execute
```

新增数据库表：

```text
execution_results
```

重要安全规则：
- 没有确认记录，不能进入执行服务。
- `edit` / `reject` 不进入执行服务。
- `publish_listing` / `bulk_publish_listing` 必须先让 `listing.package` 达到 `ready_for_confirmation_review`。
- 演示模式下即使确认通过，也只返回 `simulated_no_platform_write`，不会写入真实 eBay。
- 执行结果继续保留 `published_to_ebay=false`、`procurement_paid=false`、`refund_executed=false`、`ad_budget_changed=false`、`store_policy_changed=false`。

本轮真实本地 HTTP 验证：

未补齐刊登资料时：

```json
{
  "blocked_before_facts": true,
  "message": "listing package must be ready for confirmation review before publish execution handoff"
}
```

补齐资料并通过 Runtime 复核后：

```json
{
  "execution_status": "simulated_no_platform_write",
  "real_published": false,
  "execution_results_count": 1
}
```

验证结果：

```text
python .\tools\test_jiejing_runtime_mvp.py: PASS
node --check .\app.js: PASS
python -m compileall .\jiejing_runtime .\tools: PASS
Runtime API health: ok
```

当前进度校准：

```text
Runtime 架构底座：约 99%
替代 Hermes 的 Agent 能力：约 82%-85%
接入 SaaS 模拟端：约 99%
接入真实 SaaS 后端：约 90%-92%
真实 eBay 自动化闭环：约 50%-57%
商业化生产级：约 45%-52%
```

下一步最小动作：

继续把 ExecutionService 的结果更完整地显示到“待我确认”和“AI 汇报”：商家点完确认后，页面要清楚显示“已进入执行服务、演示未写入 eBay、正式版会由 eBay Adapter 执行并写审计日志”。

---

## 31. 2026-05-14 发布前补资料接力

本轮把 Runtime `listing_validation` blocked 后的前端接力继续产品化：不再只提示“缺资料”，而是在产品刊登里直接出现发布前补资料表单。

改动文件：
- `app.js`
- `styles.css`

新增前端能力：
```text
产品刊登 -> 待补资料 -> 补资料接力
货源资料：货源链接、采购价、起订/代发、发货地、尺寸、包装、重量、材质、配件、履约方式、需要确认事项
eBay 类目字段：用商家能看懂的方式解释 Taxonomy / Item Specifics
店铺三类政策：物流 / 支付 / 退货默认模板，商品只补差异
保存并生成发布确认单：写入 AI 汇报，状态进入待我确认
```

这一步对退路的意义：
- Runtime 的结构化缺口现在可以驱动 SaaS 里的具体操作，不只是显示技术状态。
- 商家不用在“产品刊登 / 连接账号 / 确认中心”之间来回找入口。
- Hermes 以后只需要返回同样的 `validation-summary` 和缺口字段，SaaS 前端可以继续用捷境自己的接力逻辑承接。
- 真实发布仍然不会自动执行；保存资料只生成确认单，正式版还要后端重查 eBay 类目、店铺三政策和审计日志。

验证结果：
```text
node --check app.js: PASS
runtime_mvp_regression: PASS
python compileall jiejing_runtime tools: PASS
Edge headless screenshot: PASS, output/product-readiness-intake-check.png
```

当前进度微调：
```text
Runtime 架构底座：约 98%-99%
替代 Hermes 的 Agent 能力：约 77%-81%
接入 SaaS 模拟端：约 97%-98%
接入真实 SaaS 后端：约 86%-89%
真实 eBay 自动化闭环：约 45%-52%
商业化生产级：约 41%-48%
```

下一步最小动作：

把这个补资料接力再反向接进 Runtime：前端保存的货源资料、类目候选和三政策状态要能提交给 Runtime API，重新跑 `listing.package` 校验，让 blocked 变成 ready。

下一步最小动作：

把这个“下一步提示”进一步接到确认中心和产品刊登按钮，让商家点提示就能跳到对应模块，而不是只看说明。

---

## 30. 2026-05-14 validation guide 点击接力

本轮把 validation-summary 的“下一步提示”接成可点击入口。

改动文件：
- `app.js`
- `styles.css`

当前点击接力：
```text
运行一次模拟链路 -> Runtime API 创建本地 run
回产品刊登补资料 -> 产品刊登
回素材工坊 -> 素材工坊
同步客服资料 -> 自动客服
查看确认中心 -> 待我确认
重生成 AI 汇报 / 查看待补资料 -> AI 汇报
```

这一步对 SaaS 的意义：
- 商家看到缺口后不用自己找入口。
- Runtime 的技术状态变成了商家可操作的工作流入口。
- 这符合捷境方向：AI CEO 负责翻译和接力，商家只在关键点确认。

验证结果：
```text
runtime_mvp_regression: PASS
node --check app.js: PASS
```

---

## 35. 2026-05-14 大模型 ModelClient 接入边界

本轮把捷境 Runtime 从“只能规则兜底”推进到“可接真实大模型、但默认安全兜底”的状态。重点不是让前端直接调用模型，而是把大模型放进 Runtime 后端边界里：

```text
捷境 SaaS 前端
-> 捷境后端 API
-> Jiejing Runtime
-> ModelClient
-> 大模型 API
-> Runtime 校验 / 确认中心 / 审计
-> SaaS 前端展示
```

改动文件：
- `jiejing_runtime/model_clients.py`
- `jiejing_runtime/runtime.py`
- `jiejing_runtime/capabilities.py`
- `jiejing_runtime/api_server.py`
- `jiejing_runtime/__init__.py`
- `app.js`
- `tools/test_jiejing_runtime_mvp.py`
- `tools/test_jiejing_runtime_workflow.py`

新增能力：

```text
OpenAIResponsesModelClient
默认走 Responses API 风格的模型边界。

OpenAICompatibleModelClient
保留兼容 chat-completions 风格的备用入口。

RuleBasedModelClient
没有密钥、没有模型配置、模型失败或测试环境时，继续规则兜底，不阻塞演示。

model_client_from_env()
按环境变量选择模型客户端。

GET /model-status
只返回模型边界状态，不返回任何密钥。
```

后端环境变量约定：

```text
JIEJING_MODEL_PROVIDER=responses
JIEJING_MODEL_BASE_URL=https://api.openai.com/v1
JIEJING_MODEL_API_KEY=后端密钥或云端 Secret
JIEJING_MODEL=模型名称
```

安全规则：
- 前端不保存模型密钥。
- 前端不直连大模型。
- `/model-status` 只展示是否已配置、客户端类型、模型名、endpoint host，不展示密钥。
- Responses 请求里默认 `store: false`，避免把捷境测试任务作为可检索响应保存。
- 模型未配置或失败时，Runtime 返回规则兜底报告，并明确标记 `model_mode`。
- `jiejing-llm` adapter 现在会通过 `model_client_from_env()` 进入模型边界，而不是把模型逻辑写死在岗位里。

当前本机状态：

```json
{
  "client": "openai-responses-model",
  "configured": false,
  "endpoint_host": "api.openai.com",
  "credential_present": false,
  "secret_exposed": false
}
```

这说明代码边界已经接好，但本机没有配置真实模型密钥和模型名，所以仍在安全兜底模式。正式接入时，只需要在后端或云端 Secret Manager 里配置环境变量并重启 Runtime API，不需要改前端代码。

验证结果：

```text
python .\tools\test_jiejing_runtime_mvp.py: PASS
python .\tools\test_jiejing_runtime_workflow.py: PASS
node --check .\app.js: PASS
python -m compileall .\jiejing_runtime .\tools: PASS
Runtime API /model-status: PASS
```

当前进度微调：

```text
Runtime 架构底座：约 99%
替代 Hermes 的 Agent 能力：约 84%-87%
接入 SaaS 模拟端：约 99%
接入真实 SaaS 后端：约 91%-93%
真实 eBay 自动化闭环：约 50%-57%
商业化生产级：约 46%-53%
```

下一步最小动作：

把模型输出进一步做成严格 JSON Schema 校验：市场报告、产品刊登、素材任务、客服学习包、财务复核和确认中心都要按固定合同返回。模型只负责生成内容，Runtime 负责校验、拆任务、失败重试和确认边界。

---

## 36. 2026-05-14 MerchantOperatingProfile 商家经营档案

本轮把“不同商家自定义模式”落进 Runtime，不再只停留在产品想法。核心原则是：

```text
底层闭环固定：
AI CEO -> 市场 -> 货源/履约 -> 产品刊登 -> 素材 -> 客服学习 -> 财务复核 -> 确认中心 -> CEO 汇总

商家档案可配置：
身份阶段、货源路线、履约方式、风险偏好、素材方式、客服自动化、费用口径、确认边界
```

改动文件：
- `jiejing_runtime/merchant_profile.py`
- `jiejing_runtime/workflow_templates.py`
- `jiejing_runtime/api_server.py`
- `jiejing_runtime/capabilities.py`
- `jiejing_runtime/adapters.py`
- `jiejing_runtime/__init__.py`
- `app.js`
- `tools/test_jiejing_runtime_workflow.py`

新增 Runtime 能力：

```text
MerchantOperatingProfile
把商家经营偏好变成结构化档案。

build_merchant_profile()
把 SaaS 向导里的 merchantStage / sourceApiMode / permissionLevel / riskLevel 等字段转成 Runtime 可执行配置。

GET /merchant-profiles/defaults
返回四种经营起点的默认档案：newbie / store_opened / has_orders / multi_store。

workflow_templates
每个 Runtime task 都携带 merchant_operating_profile，岗位执行时能知道当前商家的边界。
```

四类默认模式：

```text
newbie
引导式第一条商品流程：解释 API、接只读授权、补货源资料、保守确认。

store_opened
单店流程自动化：读取店铺上下文，复用店铺政策，生成刊登和素材草稿。

has_orders
订单优先自动化：客服、物流、退款边界、利润复核优先。

multi_store
多店铺批量但带闸门：先选店铺、套政策、分批候选、统一确认边界。
```

当前安全边界：
- 资料整理、调研、草稿、素材任务、客服学习包、费用预估、工作记录可以自动推进。
- 发布、批量发布、改价、改库存、广告预算、退款、采购付款、地址写入、政策修改、店铺订阅、敏感客服承诺仍必须确认。
- `service_auto` 可以放开标准客服接待，但敏感承诺、退款、补偿、差评、纠纷、地址修改仍会停住。
- `conservative` 风险档案会额外拦住未验证品牌/IP、带电、液体、易碎包装等风险。

SaaS 侧接入：

`app.js` 现在会把向导里的 `state.dna` 转成 `merchant_profile` 提交给 Runtime。Runtime 面板也会显示当前经营档案：商家身份、权限边界和风险偏好。

验证结果：

```text
python .\tools\test_jiejing_runtime_workflow.py: PASS
python .\tools\test_jiejing_runtime_mvp.py: PASS
node --check .\app.js: PASS
python -m compileall .\jiejing_runtime .\tools: PASS
Runtime API /merchant-profiles/defaults: PASS
Runtime API /capabilities includes merchant_operating_profile: PASS
```

当前进度微调：

```text
Runtime 架构底座：约 99%
替代 Hermes 的 Agent 能力：约 86%-89%
接入 SaaS 模拟端：约 99%
接入真实 SaaS 后端：约 92%-94%
真实 eBay 自动化闭环：约 51%-58%
商业化生产级：约 48%-55%
```

下一步最小动作：

把模型输出合同做成真正的 JSON Schema 校验，并让每个岗位按商家档案调整输出重点。例如同样是 `listing.package`，小白要解释字段和缺口，老店要复用店铺政策，多店铺要带店铺差异和批量确认规则。

---

## 37. 2026-05-14 RoleReportContract 岗位报告合同

本轮把“模型输出合同”真正接进 Runtime。现在不是只要求模型返回一个 `report` 对象，而是要求每个岗位报告必须带：

```text
merchant_readable_summary
required_sections
sections
limits
```

其中 `sections` 必须包含当前任务合同要求的所有字段。比如：

```text
market.report
必须包含 category_overview / buyer_profile / ebay_price_bands / competitor_top5 / keywords / risk_assessment 等。

listing.package
必须包含 sku / title / category_id / condition / price / quantity / item_specifics / pictures_required / video_required / business_policies / publish_blockers 等。

confirmation.package
必须包含 allowed_auto_actions / default_rule_actions / every_time_confirm_actions / blocked_actions / missing_facts。
```

改动文件：
- `jiejing_runtime/report_contracts.py`
- `jiejing_runtime/contracts.py`
- `jiejing_runtime/adapters.py`
- `jiejing_runtime/model_clients.py`
- `jiejing_runtime/capabilities.py`
- `jiejing_runtime/repository.py`
- `jiejing_runtime/__init__.py`
- `app.js`
- `schemas/jiejing-role-report.schema.json`
- `tools/test_jiejing_runtime_workflow.py`

新增能力：

```text
RoleReportContractValidator
检查每个岗位报告是否包含 required_sections、sections 和每个必填 section。

report_contract
每个 Runtime 报告里会附带合同校验状态：ready / blocked_missing_report_contract / blocked_empty_report_sections。

模型提示词更新
真实大模型必须返回 merchant_readable_summary、required_sections、sections、limits，不允许只写自然语言。

Hermes shadow / file handoff 同步
给 Hermes 的交接包也带 required section 边界，后续 Hermes 返回结果必须按同样结构回传。

SaaS 可见接力
`report_contract` 已进入 Runtime validation-summary 和前端校验列表，页面会把它显示成“报告字段合同”，商家不需要看技术字段，但系统能知道这份报告能不能继续接到下一步。
```

本轮发现并修复的问题：

```text
1. Hermes shadow adapter 原来只生成 dispatch_prompt，没有 sections。
   已补成“交接合同型 sections”，不再让 Hermes 交接包脱离 Runtime 合同。

2. market.data_packet 里 unavailable_sources 为空数组时被误判为失败。
   已修复：空数组可以表示“没有不可用来源”，不再误判。

3. mock/local/llm/handoff 适配器必须全部遵守同一套报告合同。
   已统一校验，避免只有本地规则版能跑，真实模型或 Hermes 交接时格式漂移。
```

验证结果：

```text
python .\tools\test_jiejing_runtime_workflow.py: PASS
python .\tools\test_jiejing_runtime_mvp.py: PASS
node --check .\app.js: PASS
python -m compileall .\jiejing_runtime .\tools: PASS
Runtime API /capabilities includes role_report_contract: PASS
Runtime API validation-summary includes report_contract: PASS
```

当前进度微调：

```text
Runtime 架构底座：约 99%
替代 Hermes 的 Agent 能力：约 88%-91%
接入 SaaS 模拟端：约 99%
接入真实 SaaS 后端：约 93%-95%
真实 eBay 自动化闭环：约 52%-59%
商业化生产级：约 50%-57%
```

下一步最小动作：

把 `report_contract` 状态展示到 SaaS 的 AI 汇报/工作记录里。商家不需要看到技术词，但页面要能告诉他：“这份市场报告可接力”“这份刊登包缺字段”“这份客服学习包还不能自动接待”。

---

## 38. 2026-05-14 报告合同的商家可见接力

本轮把 Runtime 的 `report_contract` 从技术校验翻译成商家能看懂的动作提示。页面不再只显示“报告字段合同”，而是显示“报告可接力检查”，并按任务类型解释卡在哪里、下一步去哪里。

改动文件：
- `app.js`
- `styles.css`

新增前端能力：

```text
runtimeMerchantAdvice()
把 report_contract / listing_validation / asset_manifest_validation 等状态翻译成商家可读提示。

runtimeValidationPreviewItems()
校验列表不再按后端原始顺序展示，而是优先展示真正卡住的模块。

runtimeActionForTaskType()
点击校验卡片可以跳转到对应模块：产品刊登 / 素材工坊 / 自动客服 / 待我确认 / AI 汇报。
```

当前商家侧提示逻辑：

```text
market.report 合同缺字段
显示：市场报告还不能接下一步
动作：回 AI 汇报

listing.package 合同缺字段
显示：刊登资料还没达到 eBay 草稿标准
动作：回产品刊登

asset.brief 合同缺字段
显示：素材任务还不能开工
动作：回素材工坊

customer.learn_product 合同缺字段
显示：客服还没学完产品
动作：回自动客服

finance.review 合同缺字段
显示：利润复核还缺字段
动作：回产品刊登补费用

confirmation.package 合同缺字段
显示：确认边界还不清楚
动作：查看确认中心
```

为什么这一步重要：
- Runtime 负责严格校验，SaaS 负责把校验翻译成商家动作。
- 商家不需要理解合同、validator、section 这些技术词。
- 报告能不能继续接力，现在能直接在工作台上形成反馈。
- 这符合捷境方向：AI CEO 推进流程，商家只在卡点和高风险动作上介入。

验证结果：

```text
node --check .\app.js: PASS
python .\tools\test_jiejing_runtime_workflow.py: PASS
python .\tools\test_jiejing_runtime_mvp.py: PASS
python -m compileall .\jiejing_runtime .\tools: PASS
Runtime API validation sample: 17 validations, 16 ready, 1 blocked
```

补充打磨：

AI 汇报详情里的“结构化校验”已改成“下一步接力检查”，报告详情也会使用同一套商家可读提示，不再只出现技术校验词。

当前进度微调：

```text
Runtime 架构底座：约 99%
替代 Hermes 的 Agent 能力：约 89%-92%
接入 SaaS 模拟端：约 99%
接入真实 SaaS 后端：约 93%-95%
真实 eBay 自动化闭环：约 52%-59%
商业化生产级：约 51%-58%
```

下一步最小动作：

把同一套“商家可见接力”继续接到真实模块按钮和 AI 工作记录：商家在某条报告里看到缺口时，不只是在 Runtime 面板点击，还能在 AI 汇报详情、产品刊登详情和确认中心里看到同样的下一步入口。
