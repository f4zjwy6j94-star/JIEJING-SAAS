# 捷境外部复检提示词 2026-05-31

用途：把下面提示词分别发给 Claude Code 和 ChatGPT，让它们从代码、产品、商业上线、安全边界角度复检捷境。不要在提示词里填任何密码、token、eBay refresh token、模型 key 或腾讯云密钥。

## 给 Claude Code 的提示词

你是资深 SaaS / 跨境电商平台 / 安全工程审查员。请在本地代码仓库中复检捷境 Jiejing 项目，先只输出审查报告，不要直接修改代码。

项目目录：

```text
C:\Users\57249\Documents\Codex\2026-04-29\hermes-agents\software-demo
```

产品定位：

捷境是 eBay-first AI CEO SaaS，不是通用 ERP，不是通用 Agent 市场，也不是普通聊天机器人。核心闭环是：

```text
商家给 AI CEO 下文字指令
-> 后端 agents 分配任务
-> 市场调研 / 批量选品 / IP 防侵权筛查
-> Listing 资料
-> 素材工坊
-> 客服学习
-> 财务履约与费用统计
-> 决策中心确认
-> 执行
-> 报告 / 来源 / 记忆 / 审计回流 AI CEO
```

硬边界：

- 禁止输出、读取、转储、写入任何密码、token、eBay refresh token、模型 key。
- 不要重复 eBay OAuth。
- 不要要求用户重新配置模型 key，除非后端明确证明 provider 返回认证失败或 key 已失效。
- BYOK 和 eBay token 只能在后端密钥边界内处理。
- 真实发布、采购付款、改价、库存、退款、广告、政策、敏感客服承诺必须进决策中心。

当前 staging：

```text
https://individually-buffalo-prescribed-blocking.trycloudflare.com
```

当前已复核事实：

- `/health` 正常。
- `database_startup_status=ready`。
- `real_platform_writes_enabled=true`，但真实写入必须走决策中心确认。
- `secret_exposed=false`。
- `/readiness/product-saas`：`production_ready=false`，`beta_ready=false`，`can_accept_real_customers=false`。
- blocker_count=3，warning_count=2。
- 主要 blocker 是生产级队列 / queue adapter / infrastructure cutover。
- billing 当前是 `manual_seed`，正式 paid billing provider 还没接。
- eBay official packet 已存在：`packet_2fc16b08e7bb4955`。
- reports=152，confirmations=117。
- BYOK 文本模型和 model value proof 已接通。
- 腾讯云付费 Redis 实例 `crs-jd4il28o` 已调用官方销毁接口，任务成功，实例进入待删除状态；当前 SaaS 使用 `JIEJING_QUEUE_PROVIDER=local_worker`。
- Postgres 是当前系统记录库，不能停。

请重点审查：

1. AI CEO 是否保持连续聊天体验、自动路由、普通知识直答、eBay 任务闭环、实时数据诚实处理、高风险动作进确认中心。
2. Listing / Market Report / 商家可见报告是否从源头中文化，不展示大段英文给中文商家。
3. 素材工坊是否只展示资产清单、主图、详情图、视频封面、脚本、可否发布，不向商家解释内部模型 provider。
4. Listing、批量铺货、素材、客服与订单、设置、决策中心是否各司其职，不堆旧状态和配置状态。
5. eBay 店铺同步是否清晰显示店铺名、商品 / offer / 订单 / policy / packet / 最后同步时间，不能让用户感觉没接上。
6. 发布体检报告是否覆盖类目、item specifics、图片、VeRO/IP、禁售词、GPSR、库存位置、business policy、卖家额度、预计费用、利润。
7. 发布后驾驶舱是否有 1 小时、24 小时、7 天复盘方向；真实改价、库存、下架仍进决策中心。
8. 利润大脑是否覆盖售价、eBay fee、广告、物流、采购、退货、汇率。
9. 失败知识库和商家规则记忆是否符合：用户明确说“记住这个规则”才写长期偏好；真实执行 / 确认 / 报告永久进审计和经营记忆。
10. 是否还有旧模拟商品、旧英文文案、旧 Hermes 暴露、旧登录自动弹窗、旧 OAuth 引导、密钥泄露风险。
11. 当前未正式上线的真实原因是否被 UI 和 readiness 诚实表达：正式 billing provider、稳定域名 DNS/TLS、生产队列、商业 smoke。

输出格式：

- 先列 P0 / P1 / P2 问题，带文件和行号。
- 再列“上线前必须修”和“可后续优化”。
- 最后给一个诚实进度百分比，区分“私测可跑”“beta 可邀请”“正式可收费公开上线”。

## 给 ChatGPT 的提示词

你是 SaaS 产品负责人 + 跨境电商 eBay 运营专家 + 安全审计顾问。请基于下面信息对捷境 Jiejing 做产品级复盘和上线前风险审查，不要假设它已经正式上线。

捷境定位：

eBay-first AI CEO SaaS。商家用一个 AI CEO 对话框下指令，系统把市场调研、批量选品、IP 防侵权、Listing、素材工坊、客服、财务、决策中心、执行、报告、来源、记忆和审计串成经营闭环。它不是通用 ERP，不是 Agent 市场，不是普通聊天机器人。

当前真实状态：

- public staging 可访问：`https://individually-buffalo-prescribed-blocking.trycloudflare.com`
- `/health` 正常，Postgres ready，`secret_exposed=false`
- 真实 eBay 写入开关开启，但必须通过决策中心确认
- `production_ready=false`
- `beta_ready=false`
- `can_accept_real_customers=false`
- 主要 blocker：生产级队列 / queue adapter / infrastructure cutover、正式 billing provider、稳定域名 DNS/TLS、最终商业 smoke
- eBay official packet 已存在：`packet_2fc16b08e7bb4955`
- reports=152，confirmations=117
- BYOK 文本模型已接通并有 model value proof
- Tavily 等正式外部搜索 provider 尚未配置；已有内置公开搜索 / 股票 fallback 方向
- 腾讯云付费 Redis 已释放到待删除状态；当前 SaaS 使用 local worker，Postgres 必须保留

请审查：

1. 明天真实商家自己跑“输入商品 -> 市场报告 -> Listing -> 素材 -> 发布体检 -> 决策中心 -> 真实发布 -> 审计回流”最可能卡在哪里。
2. AI CEO 应该怎样兼顾普通 DeepSeek 式咨询能力和 eBay 经营操作系统能力。
3. 7 个模块是否足够清晰：AI CEO、Listing、批量铺货、素材工坊、决策中心、客服与订单、设置。
4. 哪些地方必须吸收 Amazon 工具经验：新手 7 步发布引导、输入区 / 生成按钮 / 结果区、广告优化建议、ACOS / 预算模拟、未来 Amazon 平台抽象。
5. 经营安全系统还缺什么：发布体检报告、利润大脑、IP/VeRO、GPSR、失败知识库、商家规则记忆、可信来源 UI。
6. 商业上线前还缺什么：billing、quota、webhook、欠费停用、发票、域名、监控、告警、备份恢复演练、事故 runbook。
7. 给出诚实上线进度百分比，区分“私测可跑”“beta 可邀请”“正式可收费公开上线”。

输出要求：

- 不要输出任何密钥、token 或凭证。
- 不要建议重复 eBay OAuth，除非明确发现授权失效。
- 不要建议绕过决策中心执行真实发布、付款、退款、广告、改价、库存、政策、敏感客服承诺。
- 给出优先级路线图：明天测试前、私测后、beta 前、正式收费前。
