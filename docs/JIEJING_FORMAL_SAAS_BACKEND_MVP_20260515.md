# 捷境正式 SaaS 后端 MVP 搭建记录

日期：2026-05-15

## 这次新增了什么

新增 `jiejing_saas/`，作为官网和工作流前端之上的正式 SaaS 后端最小骨架。

当前链路是：

商家前端
-> 捷境 SaaS Backend
-> 登录与权限
-> SaaS 数据库
-> Secret Reference / Vault 边界
-> 本地任务队列边界
-> Jiejing Runtime Bridge
-> 报告与确认中心
-> ExecutionService
-> 审计日志

## 当前已经跑通

- 注册 / 登录，本地密码使用 PBKDF2 哈希，不保存明文密码。
- 用户 / 公司 / 店铺隔离，用户不能拿别的公司店铺跑任务。
- eBay / 货源等平台连接只保存连接元数据和 `secret_ref`，不保存真实 token。
- 前端活动页已经接入本地 SaaS 后端状态面板，可以从页面触发后端产品工作流。
- 产品工作流任务先进入 SaaS 任务和队列表，再由后端调用 Jiejing Runtime。
- Runtime 返回的市场、刊登、素材、客服、财务、确认等报告会写入 SaaS 报告表。
- Runtime 返回的确认项会写入 SaaS 确认中心表。
- 商家确认后，才会进入 ExecutionService。
- 当前 ExecutionService 仍是演示安全模式，只返回 `simulated_no_platform_write`，不执行真实 eBay 发布、付款、退款或广告。
- 审计日志记录注册、登录、建店、连接、任务、Runtime 完成、报告保存、确认、执行服务结果。

## 当前没有做什么

- 没有接真实 eBay 写入。
- 没有接真实支付。
- 没有接真实采购下单。
- 没有把真实密钥写进数据库。
- 没有把前端全部改成动态读后端。
- 没有把 SQLite 当成生产数据库。
- 没有把本地队列当成生产队列。

## 为什么这样做

现在前端已经能表达产品体验，但真正 SaaS 需要先有一条后端安全链路。否则以后网页按钮直接调用 Runtime、eBay、支付或采购，会产生数据隔离、权限、密钥、审计和高风险执行问题。

这一版先把边界立住：

- 前端只调用 SaaS Backend。
- SaaS Backend 负责身份、权限、任务、报告、确认和审计。
- Runtime 只负责低风险分析、草稿、报告和确认项生成。
- 真实平台执行只允许从 ExecutionService 出口走。
- 所有高风险动作必须先有确认记录。

## 下一步

1. 把活动页以外的模块继续改成读 `jiejing_saas` API：产品刊登、素材工坊、确认中心、连接账号。
2. 把 SQLite 替换成 Postgres / MySQL 的生产方案。
3. 把本地队列表替换成 Redis / 云队列。
4. 把 `secret_ref` 接入腾讯云或其他 Vault/KMS。
5. 做 eBay OAuth 只读接入，不先做发布、改价、退款。
6. 做真正的执行服务适配器，但仍然必须确认后才能执行。

## 前端接入状态

当前 `app.js` 已新增：

- `saasApiBase = http://127.0.0.1:8788`
- 本地 SaaS demo session 自动注册 / 登录
- 本地 eBay 店铺工作区自动创建
- 平台连接元数据和 `secret_ref` 自动创建
- `通过 SaaS 后端跑一单` 按钮
- SaaS 后端报告写入 AI 汇报活动流
- `确认第一条并交给执行服务` 按钮

这一步的意义是：前端已经开始从“纯静态模拟”进入“本地 SaaS 后端驱动的模拟闭环”。

## 产品级 SaaS 新增红线

2026-05-15 追加：

新增 `readiness/product-saas` 检查，不再只看功能能不能跑，而是检查能不能进入真实 SaaS 阶段。

当前 readiness 会检查：

- 运行环境是否仍是 local/test
- 登录 session secret 是否还是默认值
- 数据库是否仍是 SQLite
- 队列是否仍是本地同步执行
- Vault/KMS 是否只停留在 `secret_ref`
- Runtime 是否仍在本地
- 大模型 provider 是否配置
- eBay 只读凭据是否可用
- eBay 物流 / 支付 / 退货政策快照是否可用
- ExecutionService 是否仍是演示安全模式
- 租户隔离和审计是否被测试过

产品级判断：

- `production_ready = false`：不能开放真实商家。
- `can_accept_real_customers = false`：不能当作正式生产 SaaS。
- `real_platform_writes_enabled = false`：不能真实发布、改价、退款、广告、采购付款或修改政策。

后端现在会拒绝两类危险启动：

1. `JIEJING_SAAS_ENV=production` 但 readiness 仍有阻断项。
2. `JIEJING_ENABLE_REAL_PLATFORM_WRITES=true`。

这保证我们不会因为页面和本地链路看起来能跑，就误把系统当成可上线产品。

## 任务拆分状态

2026-05-15 追加：

产品工作流不再只是一条黑箱任务。SaaS 后端新增 `task_steps`，每次创建产品工作流时会先拆成 11 个可追踪步骤：

1. AI CEO 接目标
2. 市场数据包
3. 市场经理报告
4. 货源事实核对
5. 产品经理刊登包
6. 素材任务包
7. 客服学习商品
8. 财务与履约复核
9. 确认中心打包
10. AI CEO 汇总
11. 主理人复盘

新增接口：

- `GET /tasks/{task_id}/steps`

当前已经从“创建任务时同步执行”推进到“先入队、再由本地 worker 认领执行”。readiness 仍然把队列标成阻断项，因为本地 worker 不是生产级 Redis / 云队列；但接口形态已经更接近正式 SaaS。

## 本地 worker 队列形态

2026-05-15 追加：

新增 `jiejing_saas/worker.py`，产品工作流变成两段：

1. `POST /tasks/product-workflow`：只创建任务、拆分 11 个步骤、写入 `queue_jobs`，返回 `202 Accepted`。
2. `POST /workers/run-next`：本地 worker 认领排队任务，调用 Jiejing Runtime，保存报告、确认项、步骤状态和审计。

新增接口：

- `GET /queue-jobs`
- `POST /workers/run-next`
- `GET /tasks/{task_id}/timeline`
- `POST /queue-jobs/{job_id}/cancel`
- `POST /queue-jobs/{job_id}/retry`

前端活动页现在会先提交任务入队，再触发本地 worker 跑一次，方便演示完整闭环。正式 SaaS 上线时，前端不应该直接触发 worker；应由 Redis / 云队列和后台 worker 服务自动消费任务。

这一步解决的是昨天 Hermes 测试里暴露的核心问题：不能把完整跨境电商链路塞进一个同步请求或一个岗位长任务里。正式链路必须能看到“已入队、执行中、完成、失败、等待资料”的状态，并且失败要写回页面和审计。

2026-05-15 继续追加：

队列生命周期补齐了三个产品级动作：

- 排队任务可以取消，取消后任务和 11 个步骤都会显示 `cancelled`。
- 失败或取消的任务可以重新入队，生成新的 queue job，保留 `retry_of` 关系。
- 单个任务可以查看 timeline，把 task、queue job、步骤、报告、确认项和审计事件放到一条时间线上。

这不是为了让商家管理技术细节，而是为了正式 SaaS 出现超时、空报告、工具失败、资料缺口时，后台和前台都能明确知道：卡在哪、能不能重试、有没有误执行高风险动作。

## Secret / OAuth 边界

2026-05-15 继续追加：

新增 `jiejing_saas/secret_store.py` 和 `jiejing_saas/ebay_oauth.py`。

新增接口：

- `GET /vault/status`
- `GET /oauth/requests`
- `POST /stores/{store_id}/ebay-oauth/read-only-plan`
- `GET /oauth/ebay/callback`
- `POST /oauth/ebay/callback`

当前实现的是安全边界，不是真实 token 接入：

- 本地 MVP 仍然只保存 `secret_ref`，不保存 access token / refresh token / client secret。
- eBay 只读 OAuth 只生成授权计划，记录 company、store、user、state、scope 和授权 URL。
- 如果没有配置 `JIEJING_EBAY_CLIENT_ID` 和 `JIEJING_EBAY_RU_NAME`，后端会返回 `blocked_missing_oauth_config`，不会假装已经能跳转授权。
- 前端可以检查 eBay 只读授权状态，但不会拿到 token。
- 请求里如果混入写入 scope，后端会从只读授权计划中过滤掉。

当前 callback 已先实现“接住并审计”的骨架：

- 能用 `state` 找回原来的授权请求。
- 无效 `state` 会被拒绝。
- 收到 `code` 后不会保存 code。
- 没有 eBay App ID / RuName / Client Secret / Vault/KMS / live exchange 开关时，不会换 token。
- 会把 callback 状态写回 `oauth_authorization_requests`，方便后续继续处理。

正式版下一步要把 callback 从“骨架”升级成真实 token exchange：

1. eBay 回调到捷境后端。
2. 后端校验 `state_nonce` 是否匹配 `oauth_authorization_requests`。
3. 后端用 code 换 token。
4. refresh token 写入 Vault/KMS。
5. 数据库只保存 `secret_ref`、scope、授权状态和过期时间。
6. Runtime 只拿到本次任务需要的只读数据，不拿全量客户密钥。

## 多平台接口预留

2026-05-15 继续追加：
新增 `jiejing_saas/platform_registry.py`，把“以后要接其他境内外平台”从页面口号变成后端合同。

新增接口：

- `GET /platforms`
- `GET /platforms/{platform_key}`
- `POST /stores/{store_id}/platforms/{platform_key}/connection-plan`

当前注册的平台：

- `ebay`：当前主平台，优先只读 OAuth，后续写入必须走确认中心。
- `1688`：近期待预留货源平台，用于读取商品、价格、规格、库存、供应商和发货地；采购、付款、地址写入必须确认。
- `amazon`：未来销售平台预留，不抢当前 eBay 主线。
- `shopify`：未来独立站工作台预留。
- `taobao_tmall`：境内货源或公开参考预留，不把公开页面当成真实库存和成本。
- `pinduoduo`：境内货源或公开参考预留，后续需要合规评估。
- `alibaba`：B2B 货源和询价流程预留。
- `aliexpress`：全球参考或货源通道预留。

这个注册表只做合同，不做真实 API 调用：

- 不保存任何真实 token。
- 不让前端接触密钥。
- 不绕过 Vault/KMS。
- 不自动采购、付款、发布、改价、退款、开广告或改政策。
- 所有写入动作默认进入确认中心。

这样做的意义是：捷境仍然是 eBay-first AI CEO 工作台，但代码结构不再写死在 eBay 上。以后接 Amazon、Shopify、1688、淘宝/天猫、拼多多、Alibaba、AliExpress 或其他平台时，都按同一套“平台定义 -> 连接计划 -> secret_ref -> Runtime 数据包 -> 确认中心 -> ExecutionService”的路径扩展。

## Vault / KMS 密钥层预留

2026-05-15 继续追加：
新增正式密钥层合同，不把密钥逻辑散落在 eBay、1688、模型、搜索或图片视频接口里。

新增接口：

- `GET /vault/targets`
- `GET /secret-refs`
- `POST /stores/{store_id}/vault/secret-ref-plan`

当前预留的生产密钥目标：

- `tencent_kms`：腾讯云 KMS / Secrets Manager，适合未来腾讯云部署。
- `aliyun_kms`：阿里云 KMS / Secrets Manager，适合未来阿里云部署。
- `vault`：HashiCorp Vault，适合自管或多云部署。

当前预留的密钥用途：

- `ebay_client_secret`
- `ebay_refresh_token`
- `model_api_key`
- `public_search_api_key`
- `media_generation_api_key`
- `sourcing_api_secret`
- `logistics_api_secret`
- `storefront_api_secret`

本地 MVP 的原则不变：

- 数据库只保存 `secret_ref`、用途、provider、状态和脱敏元数据。
- 即使请求里传入 `refresh_token`、`client_secret`、`api_key`，返回结果和数据库记录也只能保存脱敏信息。
- 前端永远不能拿到真实密钥。
- Runtime 不能拿全量客户密钥，只能由后端在具体任务里解析最小必要数据。
- 真实 token 写入、读取、轮换和吊销，要等云端 KMS/Vault 接入后再开启。

这一步让捷境以后接 eBay、1688、Amazon、Shopify、搜索、图片视频、物流接口时，都走同一条密钥边界，避免每个接口各自保存一套敏感信息。

## eBay Token 自动续期边界

2026-05-15 继续追加：
新增 eBay token refresh 的后端安全骨架。

新增接口：

- `POST /stores/{store_id}/ebay-oauth/refresh-plan`

这个接口解决的是正式 SaaS 的日常运行问题：eBay access token 通常是短期凭证，过期后不能让商家反复登录，也不能让前端、Runtime 或 Hermes 直接拿 refresh token。正确做法是：

1. 商家完成 eBay 官方授权。
2. 后端在 callback 阶段把 refresh token 写入 Vault/KMS。
3. 数据库只保存 `secret_ref`、scope、授权状态和过期时间。
4. access token 过期时，由后端读取 Vault/KMS 中的 refresh token。
5. 后端调用 eBay token endpoint 换新的短期 access token。
6. access token 只给本次任务的后端 adapter 使用，不返回给前端。
7. 每次刷新都写入审计日志。

当前本地 MVP 只做 refresh plan，不做真实刷新：

- 不读取 refresh token。
- 不调用 eBay token endpoint。
- 不返回 access token。
- 不把 access token 写入数据库。
- 不让 Runtime 拿全量客户密钥。

当前会阻断的条件：

- 缺少 `ebay_refresh_token` 的 `secret_ref`。
- 缺少 eBay Client ID。
- 缺少 eBay Client Secret。
- 尚未接 Vault/KMS。
- 未开启 `JIEJING_EBAY_TOKEN_REFRESH_LIVE`。
- 真实 refresh HTTP adapter 尚未实现。

这一步把“以后 token 过期怎么办”从临时人工处理，推进为正式 SaaS 后端的一条可审计链路。

## eBay 只读 Adapter 边界

2026-05-15 继续追加：
新增 eBay 只读 Adapter 壳，先把正式 SaaS 需要读取的资源分成清晰的数据包。

新增接口：

- `GET /ebay-read-only/catalog`
- `POST /stores/{store_id}/ebay-read-only/probe-plan`

当前只读资源包：

- `account_business_policies`：读取物流、支付、退货政策 ID，服务于产品刊登和确认中心。
- `inventory_and_offers`：读取 SKU、库存、offer、刊登状态和 item location。
- `orders_and_fulfillment`：读取订单、履约状态、tracking 缺口和发货时效风险。
- `finances`：读取费用、payout、transaction、billing activity，用于利润和复盘。
- `taxonomy_listing_metadata`：读取类目树、类目建议和 item specifics，用于真实 eBay 刊登字段校验。
- `marketing_readonly`：读取广告表现信号，不修改广告预算。

当前本地 MVP 只生成 probe plan，不做真实读取：

- 不调用 eBay API。
- 不读取 Vault 里的 refresh token。
- 不向前端返回 access token。
- 不保存原始 eBay response。
- 不执行任何发布、改价、改库存、退款、广告或政策修改。

正式版读取链路应该是：

前端请求
-> SaaS Backend
-> Auth/Permission 检查
-> eBay token refresh service
-> Vault/KMS 取密钥
-> eBay Read-only Adapter
-> 数据脱敏 / 缓存 / 来源标注
-> Runtime 市场、刊登、客服、财务数据包
-> 前端报告和确认中心

如果接口没权限、403、token 过期、验证码、平台限制或数据不可用，必须在报告里标明为来源缺口，不能让商家误以为已经读到了真实店铺数据。

## eBay 只读数据包缓存

2026-05-15 继续追加：
新增 eBay 只读数据包缓存层。它不是直接保存原始 eBay response，而是把只读资源整理成 Runtime 可以使用的安全数据包。

新增接口：

- `GET /data-packets`
- `GET /data-packets/{packet_id}`
- `POST /stores/{store_id}/ebay-read-only/data-packet`

新增数据库表：

- `platform_data_packets`

数据包覆盖的资源仍然是：

- 店铺三类政策
- Inventory / Listing / Offer
- 订单与履约
- 费用与流水
- 类目与 Item Specifics
- 广告只读信号

数据包规则：

- 每个 section 必须带 `source_type`，例如 `official_api`、`sample_payload`、`source_gap`。
- 没有真实读取时，必须保存为 `source_gap` 或样本来源，不能假装是官方 API。
- PII 类字段、地址、电话、邮箱、买家姓名、token、cookie、api key 必须脱敏。
- 数据包可以给市场经理、产品经理、客服、财务和确认中心使用。
- 数据包不能授权真实发布、改价、退款、广告或政策修改。

这层的意义是：正式 eBay 只读 Adapter 接上以后，读到的数据不直接散落在各个模块里，而是先进入统一数据包，再由 Runtime 和工作台消费。这样以后排查问题时可以知道：数据从哪里来、什么时候读的、是否脱敏、是否有来源缺口、是否被用于某个报告或确认项。

## 数据库迁移与索引边界

2026-05-15 继续追加：

这次新增数据库治理层，不是为了把本地 SQLite 说成生产数据库，而是让正式 SaaS 的数据库替换路径变清楚。

新增：

- `schema_migrations`：记录当前本地 SaaS MVP schema 已经应用的版本。
- 关键索引：覆盖店铺、密钥引用、平台连接、OAuth 请求、只读数据包、任务、队列、步骤、报告、确认项、执行结果和审计日志。
- `jiejing_saas/database_plan.py`：把本地数据库现状、生产数据库阻断项、关键表、关键索引、备份恢复、最小权限账号和租户隔离规则统一输出。

新增接口：

- `GET /database/plan`
- `GET /database/inventory`

当前判断：

- 本地迁移和索引形态已经具备，可以继续做 staging 迁移准备。
- 仍然不能把 SQLite 当成正式 SaaS 数据库。
- 正式上线前必须换成托管 Postgres / MySQL，并完成备份、恢复演练、最小权限账号、监控和迁移脚本。

这一步提高的是“后端能不能承载真实商家数据”的工程确定性。它不会让系统直接具备真实 eBay 发布能力，但会让任务、报告、确认中心和审计日志以后有稳定的数据承载边界。

## 队列与 Worker 上线边界

2026-05-15 继续追加：

这次新增 `jiejing_saas/queue_plan.py`，把“本地 worker 能跑”和“正式 SaaS 云队列可上线”分开判断。

新增接口：

- `GET /queue/plan`

当前本地已经具备的形态：

- 商家请求先进入后端任务，不直接堵住浏览器。
- 一个产品工作流会拆成可追踪步骤。
- 本地 worker 可以认领队列任务。
- 队列任务可以取消、重试。
- timeline 可以看到任务、队列、步骤、报告、确认和审计。
- 高风险动作仍然不能由队列直接执行，必须先进入确认中心，再交给 ExecutionService。

正式 SaaS 还必须补：

- Redis / 云队列。
- 云端 worker 服务。
- worker heartbeat。
- 死信队列。
- 超时回收器。
- 幂等执行，避免重试时重复发布、重复退款、重复采购或重复发客服消息。
- 队列深度、失败率、最老任务等待时间和 worker 健康监控。

这一步解决的是 Hermes 测试里反复暴露的同一个问题：不能让一个岗位或一个请求吃完整条链路。正式产品必须把任务拆开、排队、可重试、可失败反馈、可审计。
