# 捷境自有 Agent Runtime、Hermes 固定版本与退出计划

生成日期：2026-05-14

本文档是捷境 Jiejing 的内部架构记录，用于回答一个核心问题：

如果当前内测依赖 Hermes，未来正式 SaaS 如何避免法律、技术和商业层面的锁死风险？

结论先行：

- Hermes 可以继续作为当前内测和云端早期执行底座。
- 捷境不能把自己的核心命门绑定在 Hermes 内部实现上。
- 捷境必须沉淀自己的任务协议、岗位规则、报告模板、确认中心和平台适配层。
- 中长期要逐步形成 Jiejing Agent Runtime，使 Hermes 变成可替换执行器之一，而不是唯一核心。

---

## 1. 当前判断

当前本地 Hermes 运行环境显示：

- 真实运行目录：`/home/hermes/.hermes/hermes-agent`
- 代码来源：`https://github.com/NousResearch/hermes-agent.git`
- 本地许可证：MIT License
- 作者/版权方：Nous Research
- 当前定位：内测执行底座、Agent 编排工具、飞书 CEO 与多岗位协作基础设施

MIT License 通常允许使用、复制、修改、分发、再授权和销售，但必须保留版权声明和许可证文本。

因此，当前最大风险不是“用了 Hermes 一定违法”，而是：

- 没有把 Hermes 版本锁住。
- 没有把捷境核心逻辑从 Hermes 内部抽出来。
- 没有自己的 Agent 执行协议。
- 未来如果 Hermes 上游变更、停更、改协议、出 bug 或不适合电商场景，捷境可能被动。

---

## 2. 三步策略的白话解释

### 2.1 fork 一份固定版本

含义：

把当前可用的 Hermes 代码固定到我们自己可控的仓库或镜像里。

目的：

- 防止上游更新导致当前能力损坏。
- 防止未来新版本改协议或删除功能影响当前项目。
- 保留当前能跑通 eBay 闭环的稳定基线。
- 方便后续安全审计和云端部署。

不是：

- 不是把 Hermes 说成捷境原创。
- 不是永远依赖 Hermes。
- 不是直接把 Hermes 暴露给客户。

最低要求：

- 保存当前 commit hash。
- 保存 MIT License。
- 保存 Nous Research 版权声明。
- 记录本地修改点。
- 禁止生产环境自动拉取上游 main 分支。

---

### 2.2 做捷境 Agent Adapter

含义：

捷境 SaaS 后端不直接依赖 Hermes 内部命令、profile、team_bus、飞书消息格式或文件结构。

捷境后端只认自己的任务协议，例如：

| 捷境任务类型 | 说明 | 当前可由谁执行 |
| --- | --- | --- |
| `ceo.intake` | 接收商家目标，判断路径和边界 | Hermes CEO / Jiejing Agent |
| `market.data_packet` | 采集市场数据包，标注来源可信度 | Hermes 市场经理 / Jiejing Market Agent |
| `market.report` | 输出市场经理报告 | Hermes 市场经理 / Jiejing Market Agent |
| `source.match` | 货源匹配、采购价、发货地、规格整理 | Hermes 财务供应链 / Jiejing Source Agent |
| `listing.package` | 生成 eBay 刊登资料包 | Hermes 产品经理 / Jiejing Listing Agent |
| `asset.brief` | 生成图片、详情页、视频任务包 | Hermes 产品经理 / Jiejing Asset Agent |
| `customer.learn_product` | 客服学习商品档案和售后话术 | Hermes 客服 / Jiejing Service Agent |
| `finance.review` | 利润、运费、退货预留、履约风险复核 | Hermes 财务供应链 / Jiejing Finance Agent |
| `confirmation.package` | 生成确认中心事项 | Hermes CEO / Jiejing Confirmation Agent |
| `execution.request` | 用户确认后请求真实执行 | Jiejing Backend Execution Service |

这样做以后：

- Hermes 只是任务执行器。
- 捷境后端掌握任务格式。
- 捷境前端掌握商家体验。
- 未来可以替换执行器，不重写 SaaS。

---

### 2.3 沉淀捷境自己的核心资产

真正属于捷境的不是 Hermes 本体，而是电商自动化方法论和产品体系。

必须沉淀为捷境资产的内容：

- eBay 经营流程拆分。
- 四类商家身份向导。
- AI CEO 接目标方式。
- 市场经理报告结构。
- 产品经理刊登报告结构。
- eBay 类目、Item Specifics、政策、价格、库存、描述、图片和发布前校验规则。
- 素材工坊任务结构。
- 批量铺货流程：机会发现、货源匹配、商家确认、刊登草稿、素材生成、发布前确认。
- 客服学习包：商品档案、风险问题、售后边界、自动回复等级。
- 财务复核模板：采购价、平台费、运费、退货预留、广告预算、利润区间。
- 确认中心规则：钱、发布、退款、广告、采购付款、授权、政策修改、敏感客服承诺必须确认。
- 工作记录、来源记录、失败重试、超时拆分和审计日志。

这些内容要以文档、模板、配置、测试样本和代码形式沉淀，不能只存在 Hermes 的记忆里。

---

## 3. 目标架构

正式 SaaS 架构应当是：

```text
捷境前端
  ↓
捷境后端 API
  ↓
登录、团队、店铺、权限检查
  ↓
捷境任务协议 Jiejing Task Protocol
  ↓
任务队列 Queue
  ↓
AgentExecutionAdapter
  ├─ Hermes Worker
  ├─ Jiejing Agent Runtime
  └─ Future Agent Worker
  ↓
报告、草稿、素材任务、确认事项
  ↓
确认中心
  ↓
Execution Service
  ↓
eBay / 1688 / 物流 / 支付 / 其他平台 API
```

关键原则：

- 前端不直接调用 Hermes。
- 前端不直接调用 eBay。
- 前端不保存密钥。
- Hermes 不直接掌握全部客户 token。
- 真实执行必须经过捷境后端和确认中心。
- Agent 输出必须回到捷境任务记录和审计日志。

---

## 4. Jiejing Task Protocol

捷境任务协议是未来避免锁死的核心。

每个任务都应有统一结构：

```json
{
  "task_id": "task_20260514_001",
  "task_type": "market.report",
  "user_id": "user_xxx",
  "company_id": "company_xxx",
  "store_id": "store_xxx",
  "platform": "ebay",
  "stage": "store_opened",
  "input": {},
  "required_output_schema": {},
  "source_policy": {
    "must_label_source_type": true,
    "allowed_source_types": [
      "official_api",
      "public_page",
      "merchant_provided",
      "manual_input",
      "ai_inference",
      "restricted_unavailable"
    ]
  },
  "risk_policy": {
    "requires_confirmation_for": [
      "publish_listing",
      "change_price",
      "change_inventory",
      "refund",
      "ad_budget",
      "procurement_payment",
      "policy_edit",
      "sensitive_buyer_commitment"
    ]
  }
}
```

所有 Agent，无论是 Hermes 还是未来 Jiejing Agent Runtime，都必须按这个协议收任务、回结果。

---

## 5. Jiejing Agent Runtime 最小版

自有 Agent Runtime 不需要一开始复制 Hermes 全部能力。

第一版只做 eBay 闭环的最小链路：

```text
AI CEO 接目标
  ↓
市场数据包
  ↓
市场经理报告
  ↓
货源事实整理
  ↓
产品刊登资料包
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

第一版必须具备：

- 接收标准任务。
- 调用大模型。
- 读取平台适配器返回的数据。
- 输出结构化报告。
- 标注数据来源。
- 标注缺口。
- 标注风险。
- 支持失败、超时、重试和拆小。
- 输出给确认中心。

第一版不必具备：

- 完整飞书网关。
- 完整多平台消息系统。
- 自动技能自进化。
- 复杂个人记忆系统。
- 所有 Hermes 工具。

原因：

捷境的第一目标不是复刻通用 Agent 工具，而是跑通电商经营自动化。

---

## 6. 平台适配层

未来捷境不能只为 eBay 写死。

正确结构是：

```text
Jiejing Task Protocol
  ↓
Platform Adapter
  ├─ eBay Adapter
  ├─ 1688 Adapter
  ├─ Shopify Adapter
  ├─ Amazon Adapter
  ├─ AliExpress Adapter
  └─ Manual Import Adapter
```

### 6.1 eBay Adapter

当前优先级最高。

负责：

- OAuth 授权状态。
- 店铺信息读取。
- Listing 读取。
- 订单读取。
- 费用读取。
- 店铺政策读取。
- Taxonomy 类目与 Item Specifics 校验。
- Trading API / REST API 能力差异处理。
- 发布前校验。
- 用户确认后执行发布、改价、库存、退款等动作。

### 6.2 1688 Adapter

第二优先级。

负责：

- 商品链接解析。
- 价格、规格、库存、起订量、发货地读取。
- 供应商评分和发货能力整理。
- 采购价、重量、尺寸、包装、材质缺口标记。
- 根据 eBay 机会反向匹配货源。

高风险边界：

- 真实下单、付款、地址写入必须确认。
- 不能让 AI 静默采购。

### 6.3 Manual Import Adapter

必须保留。

原因：

很多小白或早期商家不会接 API，也不信任授权。

负责：

- 上传图片。
- 填写采购价。
- 填写重量尺寸。
- 粘贴货源链接。
- 导入表格。
- 上传聊天记录或供应商截图。

### 6.4 Amazon / Shopify / AliExpress Adapter

未来扩展。

当前只预留，不作为第一阶段承诺。

---

## 7. Hermes 继续使用边界

当前阶段可以继续使用 Hermes：

- 真实 eBay 闭环内测。
- 飞书 CEO 调度。
- 多岗位报告生成。
- 市场经理、产品经理、客服、财务供应链协作。
- 任务拆分、失败经验沉淀。
- 技能和报告模板验证。

但必须遵守：

- 不把 Hermes 写进官网主页。
- 不让客户直接接触 Hermes。
- 不让前端直接调用 Hermes。
- 不把客户密钥交给 Hermes 长期持有。
- 不把 Hermes 的记忆当唯一事实源。
- 不把 Hermes 输出直接发布到 eBay。
- 不自动跟随上游升级。

---

## 8. 退出 Hermes 的触发条件

如果出现以下任一情况，必须启动替换或降级计划：

- 上游许可证从 MIT 改为限制商用的新许可证。
- 上游删除关键功能或改变接口，影响捷境闭环。
- 上游长期停更，安全漏洞无法修复。
- Hermes 云端部署成本或维护复杂度过高。
- Hermes 内部结构不适合多租户 SaaS。
- Hermes 不能稳定处理队列、权限隔离、失败重试。
- Hermes 的记忆或工具体系对客户数据安全造成不可控风险。

退出不是立刻停用，而是：

```text
锁定当前 Hermes 版本
  ↓
停止上游自动升级
  ↓
通过 Adapter 降低耦合
  ↓
用 Jiejing Agent Runtime 替换单个任务类型
  ↓
逐步替换市场、刊登、素材、客服、财务任务
  ↓
Hermes 降级为备用 worker 或内部研发工具
```

---

## 9. 开发路线

### 阶段 0：当前状态

目标：

- 继续用 Hermes 跑真实 eBay 内测。
- 继续打磨 SaaS Demo。
- 记录任务拆分、报告模板、失败案例。

完成标准：

- 每次 Hermes 测试都能映射到 SaaS 流程。
- 每个岗位输出都有报告。
- 失败、超时、缺资料都能被记录。

### 阶段 1：固定 Hermes 版本

目标：

- 记录当前 Hermes commit hash。
- 保存 MIT License。
- 记录本地修改。
- 禁止生产环境直接跟随 upstream main。

交付物：

- `HERMES_VERSION_LOCK.md`
- 内部 fork 或镜像仓库。
- 依赖许可证清单。

### 阶段 2：定义捷境任务协议

目标：

- 把 market、listing、asset、customer、finance、confirmation 全部定义成结构化任务。
- 每个任务都有输入、输出、超时、重试、来源标注、确认边界。

交付物：

- `JIEJING_TASK_PROTOCOL.md`
- JSON Schema 或 TypeScript types。
- 示例任务包。

### 阶段 3：AgentExecutionAdapter

目标：

- 后端通过统一接口调用执行器。
- Hermes 只是第一个执行器。

接口示例：

```ts
interface AgentExecutionAdapter {
  runTask(task: JiejingTask): Promise<JiejingTaskResult>;
  getTaskStatus(taskId: string): Promise<JiejingTaskStatus>;
  cancelTask(taskId: string): Promise<void>;
}
```

交付物：

- `HermesAdapter`
- `MockAgentAdapter`
- 任务状态表
- 失败重试机制

### 阶段 4：Jiejing Agent Runtime MVP

目标：

- 不依赖 Hermes，独立跑通一个单品闭环。

范围：

- AI CEO 接目标。
- 市场报告。
- 产品刊登报告。
- 财务复核。
- 确认中心事项。

暂不做：

- 完整素材生成。
- 多平台。
- 自动客服全链路。
- 批量铺货大规模并发。

### 阶段 5：多平台扩展

目标：

- eBay 继续作为第一平台。
- 新增 1688 / Manual Import 货源适配。
- 再考虑 Shopify / Amazon。

原则：

- 不重写 Agent。
- 新平台只新增 Adapter、字段映射、政策规则和执行服务。

---

## 10. 捷境与 Hermes 的长期关系

短期：

Hermes 是内测执行底座。

中期：

Hermes 是捷境后端的一个 Agent Worker。

长期：

Hermes 是可替换组件，捷境自有 Agent Runtime 承担核心电商链路。

最终目标：

客户买的是捷境，不是 Hermes。

捷境的价值来自：

- 懂 eBay 经营流程。
- 能把复杂流程自动化。
- 能把风险停在确认中心。
- 能把报告、来源、草稿、素材、客服、财务串成闭环。
- 能逐步适配更多平台。

---

## 11. 当前立即行动清单

P0：

- 记录 Hermes 当前版本和许可证。
- 保留 MIT License 和 Nous Research 版权声明。
- 明确生产环境不得自动更新 Hermes。
- 后续所有真实任务都按捷境任务类型记录。

P1：

- 新增 `JIEJING_TASK_PROTOCOL.md`。
- 新增 `HERMES_VERSION_LOCK.md`。
- 在 SaaS 后端设计里加入 `AgentExecutionAdapter`。
- 把当前 Hermes 测试报告逐步转成标准任务样本。

P2：

- 开始 Jiejing Agent Runtime MVP。
- 先实现单品闭环，不做大而全。
- 用 Hermes 输出作为训练样本和验收样本。

---

## 12. 红线

- 不在官网公开宣传 Hermes。
- 不把 Hermes 说成捷境原创。
- 不删除 MIT License 和版权声明。
- 不让客户直接访问 Hermes。
- 不让前端直连 Hermes。
- 不让 Hermes 直接执行真实高风险动作。
- 不让生产环境自动拉取上游 main。
- 不把客户 token、订单、买家信息长期散落在 Hermes 记忆或文件里。
- 不把 AI 推断当官方数据。

---

## 13. 一句话路线

现在用 Hermes 跑通真实闭环，边跑边把任务协议、报告模板、确认规则和平台适配沉淀成捷境自己的资产；等自有 Jiejing Agent Runtime 能独立跑通单品闭环后，Hermes 从核心底座降级为可替换 worker。
