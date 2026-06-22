# 捷境 Codex 插件与 Skill 自主触发协议 2026-06-17

本协议用于约束 Codex 在捷境项目中的自主判断：以后用户不需要点名插件或 skill，Codex 应根据任务类型主动触发合适能力，并保持捷境的 eBay-first、后端密钥边界、确认中心和审计边界。

## 总原则

1. 先判断任务类型，再选择插件和 skill。
2. 插件服务于捷境产品目标，不为了使用插件而使用插件。
3. 外部项目只吸收模式、测试、协议和工程经验，不直接替代捷境核心闭环。
4. 涉及 eBay、支付、密钥、真实写入、账号健康时，默认按高风险处理。
5. 任何真实平台写入必须经过决策中心、执行预检、审计和事故模式门禁。

## 自动触发矩阵

| 任务/信号 | 自动触发 |
|---|---|
| UI、首页、AI CEO、设置、决策中心、客服与订单 | `jiejing-design-system`、Build Web Apps、Browser/Chrome |
| UI 需要设计稿、视觉系统、页面重构前评审 | Figma、`jiejing-design-system` |
| 前端报错、布局错、按钮不动、smoke 失败 | `frontend-testing-debugging`、Browser/Chrome、Playwright/Node |
| 正式收费、套餐、quota、webhook、欠费停用 | `stripe-best-practices`、Stripe sample、Lago 参考 |
| Postgres、索引、慢查询、备份恢复、队列数据 | `supabase-postgres-best-practices`、本地 DB 检查 |
| AI CEO 慢、模型失败、接口超时、队列卡死 | `diagnose`、日志、复现脚本、回归测试 |
| eBay OAuth、token refresh、publishOffer、Inventory API | eBay 官方文档、eBay OAuth reference、后端 secret boundary |
| eBay 选品、SEO、广告、定价、Listing、转化 | Nexscope eBay/ecommerce skills + 捷境 official packet |
| IP/VeRO/品牌保护、侵权词、图片来源 | `nexscope-brand-protection-ebay`、发布体检、账号健康 |
| 封号、账号冻结、payout hold、额度不足 | 账号健康中心、事故模式、`security-threat-model` |
| 可信来源、packet、来源标签、减少幻觉 | CommerceTXT 参考、Jiejing Commerce Packet |
| feature flag、真实写入开关、灰度、kill switch | Flagsmith 参考、捷境内部 flags |
| 上线前全盘检查 | `review`、`security-threat-model`、readiness、browser smoke、核心测试 |
| GitHub repo、CI、PR、issue、review | GitHub 插件、GitHub Actions |
| 商业材料、路演、介绍 PPT | Presentations、Canva |
| 官网素材、社媒图、品牌图 | Canva |
| 产品演示视频、流程动画 | Remotion、HyperFrames |
| 服务条款、隐私政策、事故 runbook | Documents/PDF |
| 费用模型、利润模型、用量计费表 | Spreadsheets |

## Nexscope skills 触发规则

| Skill | 触发信号 | 捷境使用方式 |
|---|---|---|
| `nexscope-ebay-product-research` | 选品、市场机会、竞品、sell-through | 作为调研方法论，真实数据来自 eBay packet/公开搜索 |
| `nexscope-ebay-seo` | 标题、item specifics、搜索曝光 | 映射到 Listing Package 和发布体检 |
| `nexscope-ebay-advertising` | 广告建议、预算、ROAS/ACOS | 只做建议和模拟，真实广告必须进决策中心 |
| `nexscope-brand-protection-ebay` | VeRO/IP、品牌词、兼容性表述 | 映射到 IP 防侵权和发布体检红黄绿 |
| `nexscope-competitive-pricing-strategy` | 定价、改价、竞争价 | 真实改价必须进决策中心 |
| `nexscope-ecommerce-shipping-rates` | 物流、运费、履约成本 | 进入利润大脑和发布体检 |
| `nexscope-ecommerce-returns-management` | 退货风险、客服承诺、政策 | 敏感承诺和退款必须进决策中心 |
| `nexscope-conversion-rate-optimization` | 转化率、主图、详情页、页面优化 | 进入发布后驾驶舱和素材工坊 |
| `nexscope-market-gap-analysis` | 市场缺口、机会判断 | 进入 AI CEO 市场调研报告 |
| `nexscope-product-description-generator` | 标题、描述、卖点 | 输出必须中文商家可见，eBay listing 字段按平台规则 |
| `nexscope-ecommerce-growth-strategy` | 店铺增长、90 天计划 | 进入 AI CEO 经营复盘和路线图 |
| `nexscope-supply-chain-optimization-amazon` | Amazon 扩展、供应链策略 | 未来 Amazon 方向参考，不改变当前 eBay-first |

## 禁止事项

- 不把第三方仓库整包提交到捷境主仓库。
- 不把外部 sample 的 `.env`、key、token、webhook secret 写入项目。
- 不用 eBay scraper 替代官方 API。
- 不把 Nexscope skill 的方法论当作实时数据。
- 不让 Runtime/agents 直接读取 eBay token、模型 key、Stripe secret。
- 不让 feature flag 绕过确认中心。
- 不为了引入 LangGraph、Next.js 或外部 starter 而重写当前可运行系统。

## 执行习惯

每次处理捷境任务时，Codex 应在内部做以下检查：

1. 当前任务是否涉及真实写入、支付、账号健康或密钥。
2. 当前任务是否需要官方文档或最新 GitHub 参考。
3. 当前任务是否适合触发已安装 Nexscope skill。
4. 当前任务是否会影响多个模块，需要同步 UI、后端、readiness、测试。
5. 完成后是否需要更新测试、bundle、staging 或文档。

如果触发了外部参考，Codex 应说明使用的是“参考/方法论/官方接口依据”，不能暗示第三方代码已经成为捷境生产依赖。

