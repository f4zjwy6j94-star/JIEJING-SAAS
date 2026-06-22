# 捷境 GitHub 吸收台账 2026-06-17

本台账记录已经拉取到本机的外部 GitHub 参考源、可吸收方向和禁止事项。外部仓库只放在 `external_references/github/` 作为参考，不进入 SaaS 运行时，不直接打包部署，不绕过捷境自己的密钥边界、确认中心、审计和 eBay official packet。

## 安装与隔离状态

- 本机参考目录：`external_references/github/`
- 已加入 `.gitignore`：`external_references/`
- 原因：这些仓库用于学习和对照，不能整包提交进捷境私有仓库，也不能把第三方代码未经审查混入生产链路。
- PowerShell 阻止了 `npx.ps1`，因此 Nexscope skills 采用从已克隆仓库复制 `SKILL.md` 目录的方式安装，没有修改系统执行策略。

## 已拉取参考仓库

| 参考源 | 本地目录 | HEAD | 主要用途 | 吸收策略 |
|---|---|---:|---|---|
| `stripe-samples/subscription-use-cases` | `external_references/github/stripe-subscription-use-cases` | `fb6e9d4` | Stripe subscription、webhook、usage billing | P0，参考实现正式 billing，不直接照搬 demo env/key 处理 |
| `eBay/ebay-oauth-python-client` | `external_references/github/ebay-oauth-python-client` | `009f099` | eBay OAuth/refresh token 参考 | P0，只参考 OAuth 思路；生产仍走后端 Vault/secret_ref |
| `nexscope-ai/eCommerce-Skills` | `external_references/github/nexscope-ecommerce-skills` | `3ff915d` | 电商经营技能库 | P1，抽取 eBay-first 和跨境经营 skill 作为 Codex 触发能力 |
| `commercetxt/commercetxt` | `external_references/github/commercetxt` | `913e0d2` | 可信 commerce context / seller packet | P1，吸收为 Jiejing Commerce Packet 设计参考 |
| `getlago/lago` | `external_references/github/lago` | `a4708fa` | 混合计费、用量计费、metering | P1，研究计量模型；短期仍优先 Stripe |
| `flagsmith/flagsmith` | `external_references/github/flagsmith` | `e85f77b` | feature flag、kill switch、灰度 | P1，吸收开关模型；短期先做轻量内部 flags |
| `fastapi/full-stack-fastapi-template` | `external_references/github/full-stack-fastapi-template` | `cd83fc1` | CI、Docker、Postgres、GitHub Actions | P2，参考工程化，不迁移架构 |
| `wassim249/fastapi-langgraph-agent-production-ready-template` | `external_references/github/fastapi-langgraph-agent-template` | `36e9c33` | agent observability、rate limit、memory | P2，只参考，不把 AI CEO 重写为 LangGraph |
| `trevor-nichols/agents-saas-starter` | `external_references/github/agents-saas-starter` | `50548aa` | AI SaaS operator console、env/secrets、Stripe infra | P2，参考 operator console，不改变 DeepSeek BYOK/eBay-first 主线 |

## 已安装 Codex 电商 skills

已从 `nexscope-ai/eCommerce-Skills` 安装到 `C:\Users\57249\.codex\skills` 的 skill：

- `nexscope-ebay-product-research`
- `nexscope-ebay-seller-guide`
- `nexscope-ebay-seller-tools`
- `nexscope-ebay-seo`
- `nexscope-ebay-advertising`
- `nexscope-brand-protection-ebay`
- `nexscope-brand-monitoring`
- `nexscope-cross-border-ecommerce`
- `nexscope-product-description-generator`
- `nexscope-product-title-optimization`
- `nexscope-competitive-pricing-strategy`
- `nexscope-conversion-rate-optimization`
- `nexscope-customer-feedback-analysis`
- `nexscope-ecommerce-growth-strategy`
- `nexscope-ecommerce-ppc-strategy-planner`
- `nexscope-ecommerce-returns-management`
- `nexscope-ecommerce-shipping-rates`
- `nexscope-inventory-tracking-software`
- `nexscope-market-gap-analysis`
- `nexscope-product-launch-strategy`
- `nexscope-supply-chain-optimization-amazon`

没有安装全量 157 个 skill。原因：捷境当前是 eBay-first AI CEO SaaS，不能让 TikTok、Shopify、Walmart 等大量平台技能冲淡主线；未来做 Amazon 扩展时再按平台逐批启用。

## 吸收为捷境产品能力

### P0 正式收费系统

参考：Stripe subscription sample、`stripe-best-practices` skill、Lago 计量模型。

落地目标：

- plan：基础版、成长版、托管风控版。
- quota：AI CEO 指令、报告、素材、发布体检、真实发布次数。
- webhook：订阅创建、续费成功、付款失败、取消、欠费停用。
- usage ledger：记录每一次调研、素材、模型调用、发布体检和真实执行。
- billing gate：欠费、超额度、套餐不支持的高阶功能必须阻断。

禁止：

- 不把 Stripe secret key 写入前端、报告、日志或文档。
- 不在未验证 webhook 签名时修改订阅状态。

### P0 eBay OAuth / token refresh

参考：eBay OAuth client 和官方 API 文档。

落地目标：

- 继续使用后端 secret_ref 和 Vault-backed adapter。
- 不重复旧账号 OAuth。
- 新 eBay 账号接入后跑 token refresh live proof。
- refresh 失败要进入账号健康和事故模式，不允许继续真实写入。

禁止：

- Runtime/agents 直接拿 eBay token。
- 前端接触 access token 或 refresh token。
- 用旧被冻结账号继续真实发布测试。

### P1 Jiejing Commerce Packet

参考：CommerceTXT。

落地目标：

- 将 eBay official packet、店铺画像、business policy、inventory/offers、orders、finances、taxonomy、AI CEO 报告来源统一成可信来源协议。
- 每条建议显示来源：官方 packet、订单、财务、公开搜索、模型推理、人工输入。
- AI CEO 回答经营任务时引用 packet，不靠模型猜测价格、库存、费用和政策。

禁止：

- 用网页爬虫替代 eBay official API。
- 用旧 demo 商品补空白数据。

### P1 Feature Flag / Kill Switch

参考：Flagsmith。

落地目标：

- `real_platform_writes_enabled`
- `incident_mode`
- `billing_enforced`
- `new_merchant_beta_enabled`
- `ai_ceo_realtime_search_enabled`
- `ebay_publish_enabled`
- `ads_write_enabled`
- `refund_write_enabled`

禁止：

- 任何 flag 不能绕过确认中心。
- 任何事故模式下不能继续真实发布、改价、库存、退款、广告、政策写入。

### P1 电商经营技能库

参考：Nexscope eCommerce Skills。

落地目标：

- eBay 选品、SEO、广告、定价、利润、退货、物流、品牌/IP、市场缺口进入 AI CEO 工作流能力。
- Skills 只提供方法论；实时数据仍来自 eBay packet、公开搜索 provider 或商家输入。
- Amazon 相关 skill 暂作为未来扩展参考，不影响当前 eBay-first 产品定位。

### P2 工程化和 Agent 参考

参考：FastAPI template、LangGraph template、OpenAI Agents SaaS Starter。

落地目标：

- private GitHub repo。
- GitHub Actions 自动跑 py_compile、node check、核心 regression、bundle contract、readiness contract。
- Operator console 思路吸收到设置/上线页：env、secrets、billing、worker、queue、readiness 一屏可见。
- Agent observability 思路吸收到 AI CEO：任务状态、工具调用、失败原因、来源、审计。

禁止：

- 不大迁移现有后端框架。
- 不把 AI CEO 重写成通用 LangGraph agent 市场。

## 下一步任务

1. 建立 private GitHub repo 前，先做 secret scan 和 `.gitignore` 清理。
2. 增加 GitHub Actions 测试矩阵。
3. 基于 Stripe sample 和 `stripe-best-practices` 设计正式 billing provider adapter。
4. 设计 `Jiejing Commerce Packet` schema 和来源 UI。
5. 设计轻量 feature flag / kill switch，先覆盖真实写入和事故模式。
6. 将 eBay skills 的方法论映射到 AI CEO 工作流和发布体检，而不是直接展示给商家。

