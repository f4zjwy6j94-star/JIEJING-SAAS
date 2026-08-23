# AI CEO 真实商家闭环生产修复设计

日期：2026-08-23
状态：方案 A 已由项目负责人确认
范围：`app.jiejing.shop` 生产 AI CEO、市场调研工件、Listing 交接、素材点、真实生图与 eBay 写入门禁

## 1. 背景与已确认故障

本次从生产 AI CEO 以真实商家身份提交全新选品请求，明确禁止复用历史手机壳、旧 SKU、旧图片和旧草稿。线上请求未进入模型调用，返回 HTTP 503。生产日志记录 PostgreSQL `42P01`，只读模式对照当前仓库所需表后确认生产缺少 `media_credit_buckets`。

同时确认三类产品合同错误：

1. 前端在模型结果返回前无条件把用户指令同步到 Listing，后端失败也会出现错误的后续入口。
2. 后端及前端分别用自然语言关键词推断“市场调研”，普通公司、云服务价格或费用分析也可能生成 eBay 调研记录。
3. 素材供应商返回资产但事实/清单校验失败时，任务会标为 `validation_failed`，现有结算条件仍可能扣除素材点。

Chrome 扩展可以正常控制浏览器；此前 `setFiles: Not allowed` 发生在浏览器把本地文件交给页面之前，不是捷境上传 API 的错误。产品上传链路仍须通过真实 HTTP 回归验证。

## 2. 目标

建立一条诚实、可恢复、可审计的真实商家闭环：

1. 商家在 AI CEO 明确提出 eBay 选品目标。
2. AI CEO 返回三个全新候选品及真实来源、证据缺口和风险，不编造供应商、库存、尺寸、重量、材质或成本。
3. 商家选择候选品并补齐实物与供应商事实。
4. 后端生成结构化市场调研工件；只有满足 Listing 导入合同才允许交接。
5. 素材工坊基于已核验事实与有权使用的来源图真实生图，失败或校验不通过不扣点。
6. 生成全新 Listing 包并保存 eBay 未发布草稿。
7. 仅在当前店铺账号健康、商品事实、政策、图片权利和发布体检全部通过后，才允许单次确认后公开发布。

## 3. 非目标

- 不复用手机壳、旧商品、旧 SKU、旧标题、旧图片哈希、旧报告或旧确认单。
- 不重复 eBay OAuth，不新建第三个卖家账号，除非当前替代账号的实时证据明确失效。
- 不把普通搜索、股票研究、云服务成本分析保存为 eBay 市场调研。
- 不在前端保存或展示模型密钥、eBay token、支付密钥或 Vault 凭证。
- 不用直接改生产余额、伪造支付回调、关闭扣点规则等方式冒充验收通过。
- 本修复不自动打开广义 eBay 真实写入开关。

## 4. 后端权威工件合同

前端不再从自然语言自行推断权威市场报告。后端返回的结构化工件是唯一事实来源。

市场调研工件至少包含：

- `artifact_type = ai_ceo.market_research`
- `artifact_version`
- `merchant_intent = ebay_product_research`
- `candidate_products`，每项包含候选名称、eBay US 类目、检索词、来源、价格证据或明确缺口、需求与竞争信号、履约/IP/售后风险、待核实事实
- `candidate_count`
- `selected_candidate_id`
- `evidence_status`
- `supplier_fact_status`
- `listing_import_ready`
- `blocked_by`
- `source_records`
- `secret_exposed = false`

只有下列条件同时成立才允许 `listing_import_ready=true`：

1. 用户意图明确属于 eBay 选品或 Listing 工作流。
2. 至少有一个具体候选品。
3. 已选择唯一候选品。
4. 没有编造或缺失会改变刊登真实性的事实。
5. 工件由后端保存并带稳定 ID。

“报告已保存”与“可导入 Listing”是两个独立状态。

## 5. AI CEO 请求状态机

每一次模型请求先创建一个轻量、不可执行外部写入的尝试记录：

`accepted -> resolving_dependencies -> quota_checked -> model_running -> artifact_validating -> completed`

允许的失败状态：

- `blocked_database_schema`
- `blocked_model_connection`
- `blocked_quota`
- `failed_model_provider`
- `failed_artifact_validation`

失败请求必须：

- 在后台任务和审计中可见；
- 返回准确中文原因；
- 不消耗 AI 试用次数；
- 不生成市场报告或 Listing 入口；
- 不把用户输入同步成 Listing 草稿。

## 6. PostgreSQL 迁移与健康合同

在 PostgreSQL 迁移中新增 `media_credit_buckets` 及 `idx_media_credit_buckets_company_status (company_id, status, expires_at)`。字段合同固定为 `bucket_id`、`company_id`、`source_type`、`source_reference_id`、`granted_points`、`remaining_points`、`reserved_points`、`expires_at`、`status`、`created_at`、`updated_at`、`bucket_json`；时间/JSON 使用 PostgreSQL `timestamptz/jsonb`，`company_id` 外键指向 `companies(company_id)`。bucket 的业务唯一键固定为 `(company_id, source_type, source_reference_id)`，同一公司同一来源引用不得重复建 bucket。迁移必须幂等、事务化，并以 migration id `20260823_002_media_credit_buckets_postgres`、checksum `jiejing-media-credit-buckets-postgres-v20260823` 记录新的 `schema_migrations` 条目；已经上线的 `001_initial_schema_postgres.sql` 全文件内容保持不变。

迁移互斥固定使用 PostgreSQL session advisory lock：lock key 为有符号 int64 `-1280677561506917264`，它由 `SHA-256('jiejing-postgres-schema-migration-v1')` 的前 8 字节按有符号 64 位整数解释得到。API 与 Worker 启动的 migration runner 必须使用同一 key，并在结束路径上执行与之匹配的显式 `pg_advisory_unlock`；事务级 `pg_advisory_xact_lock` 不能代替该跨 runner 合同。

现有 `media_credit_accounts` 余额通过后端现有 legacy bucket 映射规则惰性映射；迁移本身不改变总余额、已预留点数、累计赠送或累计消耗。

部署前后必须验证：

- 所有仓库要求的生产表均存在；
- 素材点余额读取、reserve、release、settle 的零外部调用探针通过；
- AI CEO 额度读取不会再触发 `42P01`；
- `/health/deep` 或产品 readiness 暴露数据库 schema contract，不再只证明“数据库能连接”。

迁移前保存数据库结构与受影响表的恢复证据；失败时事务回滚，应用保持旧版本。

## 7. 路由与前端交接

- eBay 工作流必须出现明确 eBay、Listing、刊登、选品或当前结构化工件上下文，通用“费用”“市场”“产品”不再单独触发。
- 普通实时研究可以保存普通工作记录，但不能生成 `ai_ceo.market_research`。
- 删除发送消息时的无条件 Listing 同步。
- Listing CTA 仅在后端 delivery 明确 `listing_import_ready=true` 且带有效 artifact ID 时渲染。
- 后端无工件时，前端不得根据回答文本自行创建权威市场报告。
- HTTP 503 等依赖失败显示“本次未调用模型、未消耗次数、未生成草稿”，并保留可重试入口。

## 8. 素材点与真实生图

素材结算分成两个阶段，不把“已生成”与“可上架”混为一个状态。

阶段 A 是 provider 调用前的不计费门禁：

- 必须具有会影响图片真实性的已确认商品事实；缺失时返回精确事实缺口，例如 `confirmed_material_or_pending_label`。
- 必须有 `reference_images`、`source_asset_id` 或可审计的 `source_notes`；缺失时阻断码为 `reference_images_or_source_notes`。
- 商家必须显式声明 `commercial_rights_confirmed=true`；未确认时阻断码为 `commercial_use_rights_authorization`。
- 任一项不满足，worker 不得调用真实素材 provider；已创建的 reservation 必须 release，不得消耗素材点。

阶段 B 是 provider 返回后的结算与 Listing 使用门禁：

- 真实生产器 `build_media_asset_generation_packet(...)` 返回非空 manifest，且 `asset_manifest_validation.status=manifest_ready` 时，当前正常成功态仍是 `asset_review.status=waiting_for_human_asset_review`、review gate `status=needs_review`。这表示有效生图交付立即按实际返回资产 settle，但 `listing_use_status=not_ready_for_listing_until_review`，未经商家复核绝不得进入 Listing。
- 商家只能通过现有 `/media-asset-jobs/{id}/review` 复核转换为 `approved_for_listing_draft` 或 `needs_rework`。生成后的商家 `needs_rework` 决定只阻断 Listing，绝不得逆转、release 或重写已 settle 的终态账本；善意补点或免费重试属于未来的独立政策，不在本合同中暗示实现。
- provider 未调用或调用失败，以及 provider 刚返回时 manifest/fact/right 校验为真实 `blocked_*` 或 `failed*` 状态时，全额 release。
- 部分资产正常返回时只按实际资产数 settle，释放其余预留。
- 重试、超时、重复或矛盾回调必须保持幂等，每个 reservation 只能有一个终态 settle/release 结果；终态后的商家复核不属于账本回调。

为本次生产闭环新增非公开 `controlled_acceptance` 验收点来源：

- 仅后端/ops 可发放，公共 API 不可调用；
- 公司白名单；
- 一次性幂等键和 `source_reference_id` 由服务端根据固定验收活动与目标 company/account 确定性派生，CLI 不得接受 `--idempotency-key` 或 source reference 覆盖；
- 低额度，只够一轮标准图片验收；
- 固定 24 小时到期，过期后不可消耗；
- 显式启用环境变量缺失或非真时默认关闭，生产不得默认启用；
- CLI 只接受且必须精确匹配 owner 确认短语 `I_APPROVE_CONTROLLED_MEDIA_ACCEPTANCE_POINTS`，不接受布尔批准开关；
- 完整审计：`action_type=media_credit.controlled_acceptance.granted`，记录 company、bucket target/source reference、320 点、24 小时 TTL、`external_provider_action_triggered=false`与 `secret_exposed=false`；不可退款、转让或兑现；
- 余额摘要可以单列或不展示验收点，但绝不得将其计入 `plan_included` 或 `purchased`；精确来源、预留和到期以 bucket/ledger 为权威证据；
- 不改变公开免费版“0 素材点”政策。

受控验收生图必须走商家真实入口 `POST /stores/{store_id}/provider-jobs/queue`。该任务上下文由服务端绑定上述 `controlled_acceptance` source reference，入队时必须通过精确来源 reserve 只预留该 bucket；即使同一公司同时存在套餐点和购买点，也不得动用它们。受控 bucket 不存在、已过期或额度不足时直接阻断入队，绝不回退到通用 reserve。此入队证明不允许立即调 provider，真实外部调用仍需后续独立动作确认。

公共 HTTP 路由表和 `do_POST`/路由分派器中都不得注册任何 controlled acceptance grant 入口；常见的伪造路径必须稳定返回 404 且不产生账本或审计变化。

真实 FAL 调用仍属于消费动作。创建任务前展示预计图片数、清晰度、预计点数及来源事实，并在行动时确认。

## 9. eBay 写入边界

第一阶段只使用现有窄门保存 Inventory Item 与 unpublished Offer，不调用 `publishOffer`。

公开发布前必须用登录态、当前 store scope 只读核验：

- 唯一且匹配当前店铺的连接；
- 当前 OAuth callback、Vault secret ref 与账号身份；
- `account-health.status=normal`、`incident_mode=false`、`can_execute_real_writes=true`；
- 无 frozen、restricted、suspended、limited、payout hold、unverified 或 below-standard；
- 当前 6/6 官方数据包及三项 Business Policies；
- 新 SKU、标题和图片未命中历史重复记录。

商品包必须包含真实库存、售价、类目、item specifics、发货地、重量、尺寸、材质、成本与利润、图片商业使用权及合规复核。缺一项就停在未发布草稿。

广义真实写入开关保持关闭，直到上述证据齐全并获得行动时确认。确认公开发布后只开放一次受控执行；超时或 502 先按 SKU 查询远端状态，禁止盲目重试。

## 10. 测试矩阵

实现遵循测试先行，至少覆盖：

1. PostgreSQL 迁移创建 bucket 表、索引和 migration record，重复执行无副作用。
2. 生产 schema contract 缺表时 readiness 失败并指出表名，不再假绿。
3. AI CEO 依赖失败创建阻断任务、不扣次数、无报告、无 Listing CTA。
4. 股票、ticker、腾讯云价格、腾讯云费用均不生成 eBay 工件。
5. 明确 eBay 选品请求可生成三个候选，但未选择或事实不足时不可导入。
6. 后端 `listing_import_ready=false` 时前端无导入按钮。
7. 后端无工件而回答含“推荐产品”时前端不自行生成报告。
8. manifest、事实或权利校验失败释放素材点；部分成功按实际结算；重试幂等。
9. `controlled_acceptance` 只能由 ops、白名单、一次性、限额、限时发放。
10. 上传成功、无登录 401、错误类型、超限、签名读取与租户隔离。
11. eBay 未发布草稿合同通过，公开 publish 在开关关闭时继续阻断。

## 11. 发布与回滚

发布顺序：

1. 本地红灯测试。
2. 实现迁移和后端合同。
3. 实现前端交接与素材结算。
4. 全量门禁、秘密扫描和 JavaScript 语法检查。
5. 生产数据库备份与迁移 dry-run。
6. 原子部署并验证 health、deep health、readiness、匿名权限边界。
7. 登录态 AI CEO 真实回归。
8. 经确认后执行一次真实生图。
9. 保存未发布 eBay 草稿并核验远端状态。
10. 单独决定是否开放一次公开发布。

应用失败回滚到上一 release；数据库 DDL 为向后兼容新增表，无需破坏性回滚。若需要停用新逻辑，旧应用可忽略新增表，数据保留用于审计。

## 12. 验收标准

本轮只有在以下证据齐全时才算完成：

- AI CEO 在生产站真实返回三个全新候选品；
- 没有手机壳及历史商品污染；
- 候选与来源、风险、数据缺口可审计；
- 选择商品后生成可恢复的结构化工件；
- 素材工坊产生本轮真实新图片，结算准确；
- Listing 包字段来自真实商品事实；
- eBay 未发布草稿远端存在且与本地审计一致；
- 当前账号健康与发布体检结果明确；
- 若获最终确认，公开 Listing 远端存在且可通过 listing ID 只读核验；否则明确停在未发布草稿，不冒充已上线。
