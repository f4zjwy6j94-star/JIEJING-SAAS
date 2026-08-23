# AI CEO 真实商家闭环实施计划

日期：2026-08-23
设计依据：`docs/superpowers/specs/2026-08-23-ai-ceo-real-merchant-loop-design.md`
工作分支：`codex/ai-ceo-real-merchant-loop`

## Phase 0：文档与现有模式发现

### 已确认的允许接口与复制来源

1. PostgreSQL 迁移
   - `jiejing_saas.infrastructure_drivers.run_postgres_migration(...)` 从固定可信 manifest 按 `001 -> 002 -> 003` 顺序读取并在 psycopg 事务中执行。
   - `SaaSRepository._initialize_postgres()` 是应用启动迁移入口。
   - `jiejing_saas.operational_health._database_live_probe(...)` 调用 `run_postgres_live_probe(...)`，是 `/health/deep` 的数据库证明来源。
   - 复制 `tools/test_jiejing_postgres_repository_cutover.py` 的迁移合同和假 psycopg 模式，不另造数据库驱动 API。
2. AI CEO 工件与任务
   - `SaaSRepository.create_task(...)` 与 `update_task_status(...)` 是唯一任务持久化接口。
   - `SaaSRepository.save_ai_ceo_market_research_report(...)` 是权威市场报告入口。
   - `build_ai_ceo_market_report_delivery(...)` 已把 `listing_handoff.ready_for_listing_draft` 映射为 `listing_import_ready`。
   - 复制 `tools/test_jiejing_saas_ai_ceo_chat_model_boundary.py` 的正负 HTTP 回归结构。
3. 前端 Listing 门禁
   - 复制 `saasListingDraftFromReport(...)` 在 `app.js:11229` 的严格 `ready_for_listing_draft` 早退模式。
   - 复制 `saasAiCeoMarketResearchEligibility(...)` 和具体商品门禁，不再创建第二份前端权威报告。
4. 素材点
   - `SaaSRepository.apply_media_credit_operation(...)` 是唯一 grant/reserve/settle/release/revoke 入口。
   - 复制现有公司级锁、幂等键、bucket 分配与账本模式。
   - `Worker._settle_media_credit_reservation(...)` 必须以最终 manifest validation 为结算事实。
5. 受控验收运维
   - 复制 `create_controlled_wechat_pay_acceptance_order(...)` 与 `tools/jiejing_wechat_pay_live_acceptance.py` 的非公开 CLI、目标账号、一次性进程开关和确定性幂等模式。owner 确认必须通过字符串参数精确匹配 `I_APPROVE_CONTROLLED_MEDIA_ACCEPTANCE_POINTS`，不得简化为布尔 flag。
   - 验收 CLI 通过目标账号反查唯一 company，额度和到期时间由服务端常量固定，一次性幂等键/source reference 也由服务端确定性派生；不接受任意 company/points/expiry/source reference 或 `--idempotency-key` 参数。显式 enable env 缺失时默认关闭。
6. eBay
   - 未发布草稿继续走现有 `draft_save_authorized` 窄门。
   - 公开发布继续服从 `effective_real_platform_writes_enabled`、`JIEJING_EBAY_WRITE_LIVE`、账号健康、类目和商品事实门禁。

### Anti-pattern guards

- 不直接执行生产 SQL 修表来代替仓库迁移。
- 不直接更新生产素材点余额。
- 不伪造微信支付回调或关闭 enforcement。
- 不让前端从自然语言创建 `ai_ceo.market_research`。
- 不把 `task.status=completed` 当作 Listing 工件已可导入。
- 不在日志、测试输出或文档中打印数据库 URL、模型密钥、Vault token 或 eBay token。
- 不重复 OAuth 或重新同步 eBay，只用当前登录态状态接口核验。

## Phase 1：先写红灯回归

### What to implement

1. 新增 PostgreSQL schema 合同测试：要求独立、不可变的增量迁移创建 `media_credit_buckets` 表、索引和新的 migration record；验证 checksum drift 与 live probe 缺表均失败。
2. 扩展 AI CEO HTTP/纯函数测试：
   - 模型前依赖失败生成 `merchant_ceo_chat_attempt` 阻断任务；
   - 不生成 report/delivery/CTA；
   - 不计入平台试用次数；
   - ticker、腾讯云价格和腾讯云费用不得生成 eBay 工件。
3. 扩展前端测试：
   - `listing_import_ready=false` 时无 CTA；
   - 后端无 report 时不创建前端权威 report；
   - 发送消息前不写 Listing。
4. 扩展 worker 素材测试：用 `build_media_asset_generation_packet(...)` 构建真实当前输出，不伪造 `passed/blocked` provider packet。覆盖 provider 前商品事实/来源/商用权利缺失时不调 provider 且 release；provider 返回当下 manifest/fact/right 的真实 `blocked_*`/`failed*` 状态 release；正常 `manifest_ready + needs_review` 立即按实际返回资产 settle，但商家复核前仍禁止 Listing；后续商家 `needs_rework` 不逆转终态账本；重复和矛盾回调每个 reservation 只产生一个终态。
5. 新增 controlled acceptance CLI 测试：缺少或错误的精确确认短语 `I_APPROVE_CONTROLLED_MEDIA_ACCEPTANCE_POINTS`、enable env 缺失/关闭、公司未白名单、目标账号/租户不匹配时阻断；固定 320 点与 24 小时 TTL；过期不可消耗；服务端派生的同一次性来源重复请求只发一次，CLI 无 idempotency/source 覆盖；结构检查和本地 HTTP 探针都证明无公共 grant 路由。
6. 新增本地 HTTP 入队集成测试：在套餐、购买、验收三类 bucket 并存时，认证商家向 `POST /stores/{store_id}/provider-jobs/queue` 提交受控验收素材任务，必须只预留服务端绑定的 `controlled_acceptance` bucket；套餐/购买 bucket 不变，验收 bucket 无效则阻断且不回退，队列模式不触发 provider。

### Documentation references

- `tools/test_jiejing_postgres_repository_cutover.py:198-289`
- `tools/test_jiejing_saas_ai_ceo_chat_model_boundary.py:445-523,895-970,1008-1104`
- `tools/test_jiejing_ai_ceo_market_report_recovery.py:122-139`
- `tools/test_jiejing_ai_ceo_listing_import_target.py:35-91`
- `tools/test_jiejing_media_asset_jobs.py:120-250,420-445`
- `tools/test_jiejing_commercial_entitlements.py:49-207`

### Verification

- 新增/扩展测试必须在实现前以预期原因失败。
- 保存红灯输出摘要，不接受语法错误或夹具错误作为红灯。

## Phase 2：修复 PostgreSQL 迁移与深度健康

### What to implement

1. 保持已经上线的 `001_initial_schema_postgres.sql` 全文件内容不变，新增独立、不可变的 `002_media_credit_buckets_postgres.sql`；表字段合同固定为 `bucket_id`、`company_id`、`source_type`、`source_reference_id`、`granted_points`、`remaining_points`、`reserved_points`、`expires_at`、`status`、`created_at`、`updated_at`、`bucket_json`，其中时间/JSON 使用 PostgreSQL `timestamptz/jsonb`，`company_id` 外键指向 `companies(company_id)`。
2. 新增 `idx_media_credit_buckets_company_status (company_id, status, expires_at)` 和 `(company_id, source_type, source_reference_id)` 唯一约束；migration id 固定为 `20260823_002_media_credit_buckets_postgres`，checksum 固定为 `jiejing-media-credit-buckets-postgres-v20260823`；已存在同 ID 但 checksum 不同必须 fail closed。
3. 修复历史 001 曾被发布后原地扩展造成的遗留库漂移：新增独立、不可变的 `003_runtime_schema_reconciliation_postgres.sql`，幂等补齐 `external_execution_claims`、`user_refresh_sessions`、`user_refresh_token_history`、`user_sessions.refresh_session_id`、三个刷新会话索引及命名外键 `user_sessions_refresh_session_id_fkey`。003 migration id 固定为 `20260823_003_runtime_schema_reconciliation_postgres`，checksum 固定为 `jiejing-runtime-schema-reconciliation-postgres-v20260823`。
4. `run_postgres_migration(...)` 按固定 `001 -> 002 -> 003` manifest 顺序执行增量迁移，并使用 PostgreSQL session advisory lock 防止 API/Worker 跨进程并发迁移。lock key 固定为有符号 int64 `-1280677561506917264`，即 `SHA-256('jiejing-postgres-schema-migration-v1')` 前 8 字节的有符号 64 位整数。API 与 Worker runner 必须使用同一 key，且在结束路径上使用同 key 显式调用 `pg_advisory_unlock`；不接受 `pg_advisory_xact_lock` 代替。显式参数传入单文件的测试兼容路径保留。
5. 001、002、003 均以固定 canonical SHA-256 和 migration record 进入可信 manifest；已发布文件永久只读。未来结构变化只能新增更高编号迁移，禁止修改旧文件、复用旧 id 或用冲突忽略掩盖 drift。
6. 扩展 Postgres live probe：在 `select 1` 后，以固定静态 allowlist 批量查询 required relations、migration id/checksum、关键 columns/indexes/constraints；四个索引必须匹配所属表和列顺序，外键必须匹配源表/源列和目标表/目标列，bucket company 外键与三列 UNIQUE 也必须验证。总 execute 不超过 6，不得对每个 relation 单独执行 `to_regclass`。缺失或同名错误 postcondition 返回 `postgres_schema_missing_postconditions` 及安全 identifier 列表，不返回实际 definition、连接信息、checksum 或 SQL。
7. 002/003 在写入各自 migration marker 前，以事务内 `DO` postcondition 验证关键 index/constraint 的真实 catalog 定义；同名错误对象必须 raise 并回滚，不得静默跳过后落 marker。
8. `/health/deep` 在缺表、migration drift 或关键 postcondition 缺失时返回 blocked，产品 readiness 同步阻断 database schema contract。

### Verification

- Phase 1 数据库测试转绿。
- 旧 marker 库仅执行 003 一次，第二次幂等跳过；随后 live probe 转绿。
- 现有 `test_jiejing_postgres_repository_cutover.py`、`test_jiejing_operational_health_readiness.py` 转绿。
- `rg` 确认 SQLite/002 两份 bucket 字段一致。
- 两个并发 migration runner 使用固定 key `-1280677561506917264`，只能有一个持锁执行，另一方等待后验证同一结果；两方都必须留下匹配的显式 unlock 证据。

### Anti-pattern guards

- 不继续修改已发布的 001 来伪装版本化迁移。
- 不修改已经进入可信 manifest 的 002/003；任何后续变化新增迁移。
- 不把 required table 名称取自用户输入。
- 不对 required relations 执行逐表 catalog 往返。
- 不在 public summary 暴露数据库 URL、schema owner 或 SQL 原文。

## Phase 3：建立 AI CEO 尝试任务和准确失败状态

### What to implement

1. 在聊天入口保存命令后创建 `merchant_ceo_chat_attempt` 任务，输入只含脱敏 route、command id 和安全状态。
2. 连接、schema、quota、provider 和 artifact 失败分别更新 attempt task；不创建实际模型使用任务。
3. 实际模型成功后仍使用现有 `merchant_ceo_chat` 任务作为计量事实，并在 attempt output 记录 artifact outcome 和实际 task id。
4. 统一 artifact outcome：`not_requested`、`not_eligible`、`saved_not_importable`、`saved_import_ready`、`artifact_save_failed`。
5. 错误响应增加准确中文说明及 `usage_consumed=false`、`listing_created=false`。

### Documentation references

- `jiejing_saas/repository.py:2711-2750,3867-3903`
- `jiejing_saas/api_server.py:5884-6315`
- `jiejing_saas/api_server.py:226-251`

### Verification

- 模型前阻断在任务列表可见。
- 平台 trial `used` 不因 attempt 增加。
- 后端日志不包含用户完整 prompt 或 secret。

## Phase 4：收紧路由并确立后端唯一工件

### What to implement

1. 把 route 与 artifact intent 拆开；只有用户明确 eBay/Listing/刊登/选品意图或已有后端工件上下文时，才具备 eBay market artifact eligibility。
2. 从通用 workflow marker 中移除单独的“费用”等非电商触发词。
3. `_looks_like_ai_ceo_market_research_turn(...)` 不再跨问题+回答凭“市场+产品”判权威工件，也不把所有 `external_realtime` 当选品。
4. 报告 `listing_import_ready` 至少要求明确意图、具体候选、已选择候选、权威后端 report id；事实缺口继续显示但保持不可导入。
5. 修复审计中硬编码 `ready_for_listing_draft=True`，改为实际值。

### Verification

- 股票、ticker、云服务与 eBay 正负矩阵通过。
- 保存不可导入报告时审计、handoff、delivery 三者一致。
- 报告列表无新增误分类记录。

## Phase 5：删除前端假进度与错误 CTA

### What to implement

1. 删除消息发送阶段的无条件 `syncSaasCeoCommandToListing(command)`。
2. 聊天响应不再调用前端自然语言报告构建函数来创建权威报告；本地函数仅允许渲染兼容旧历史记录，且不能产生 CTA。
3. `renderSaasAiCeoMarketReportDeliveryMarkup(...)` 必须同时检查：后端 report id、`listing_import_ready=true`、具体商品。
4. delivery 缺少 `report_type` 时不默认成市场调研。
5. 503/blocked UI 明确显示本次未调用模型、未扣次数、未生成草稿。

### Documentation references

- `app.js:8802-8808,11229-11235,19185-19203`
- `app.js:23376-23416,23949-24068,31082-31259,45470-45490`

### Verification

- `node --check app.js`
- AI CEO Listing import/具体商品/前端安全 smoke 全绿。
- 静态 grep 不再出现发送前无条件 Listing 同步。

## Phase 6：修复素材结算并增加受控验收点

### What to implement

1. 在 `ProviderJobRunner` 调真实 provider 之前执行不计费预检：必须有已确认商品事实、`reference_images`/`source_asset_id`/`source_notes` 之一和 `commercial_rights_confirmed=true`。缺失时返回精确 blocker（如 `confirmed_material_or_pending_label`、`reference_images_or_source_notes`、`commercial_use_rights_authorization`），不调 provider，reservation release。
2. `Worker._settle_media_credit_reservation(...)` 以真实 `build_media_asset_generation_packet(...)` 产物为依据：live provider 已调用、manifest 非空、`asset_manifest_validation.status=manifest_ready` 时，当前标准成功态 `asset_review.status=waiting_for_human_asset_review` 和 review gate `needs_review` 立即按实际返回资产数结算；其 `listing_use_status=not_ready_for_listing_until_review`，只有商家在 `/media-asset-jobs/{id}/review` 批准后才可用于 Listing。后续 `needs_rework` 只改变 Listing 可用性，绝不逆转已 settle 的终态账本；善意/重试补点保留为未来独立政策。
3. provider 失败、provider 刚返回时 manifest/fact/right 的真实 `blocked_*`/`failed*` 状态释放全额；部分成功使用现有 `actual_media_points_from_output(...)` 和返回资产数结算，剩余预留通过同一原子结果释放；重复或矛盾回调不得创建第二个终态。
4. 增加一次性、非公开 controlled acceptance CLI，复制微信支付 acceptance 工具的目标账号和一次性进程开关模式；CLI 只接受并精确校验 owner 短语 `I_APPROVE_CONTROLLED_MEDIA_ACCEPTANCE_POINTS`，不接受布尔批准 flag、`--idempotency-key` 或 source reference 覆盖；固定 320 点、24 小时 TTL和目标账号所属 company，一次性幂等键/source reference 由服务端确定性派生，enable env 缺失时默认关闭。审计字段固定覆盖 action type、company、bucket target/source reference、points、TTL、无外部 provider 动作和 `secret_exposed=false`。
5. 将 `controlled_acceptance` 加入明确的 bucket source allowlist、到期、撤销和余额投影；保证 `(company_id, source_type, source_reference_id)` 唯一，绝不静默降级成 `legacy`。商家余额摘要可单列或省略验收点，但绝不得归入 `plan_included` 或 `purchased`；精确来源、预留和到期以 bucket/ledger 为权威证据。
6. 受控验收任务必须经认证商家实际调用 `POST /stores/{store_id}/provider-jobs/queue`，入队时使用 `reserve_media_credit_source(...)` 精确预留服务端绑定的 acceptance bucket；在 plan/purchased/controlled 并存时只改变 controlled bucket，验收额度不足、过期或缺失即阻断，绝不回退消耗套餐点或购买点；queued 验收不触发 provider。
7. public/free plan 保持 0 素材点；仓库的公共路由表与 `do_POST`/路由分派器都不得注册 controlled acceptance grant 端点，常见伪路径本地 HTTP 探针必须 404 且账本/审计无变化。

### Documentation references

- `jiejing_saas/worker.py:481-549,664-782,841-900`
- `jiejing_saas/repository.py:8907-9465`
- `jiejing_saas/api_server.py:8680-8750`
- `jiejing_saas/media_credits.py:105-222`

### Verification

- 素材账本、worker、购买点、套餐点测试全绿。
- 缺少或错误的确认短语、公司未白名单、目标账号/租户不匹配、enable env 缺失/关闭和重复 grant 回归通过；尝试提供不同 operator idempotency key 不得发放第二份。
- 失败任务余额不减少、reservation 状态为 released。
- 商家余额摘要把验收点单列或排除，不归类为 purchased。
- 实际 provider-job queue 只预留 controlled bucket，plan/purchased 证据不变；无效 controlled bucket 时不入队、不调 provider。
- 有效产物 settle 后的商家 `needs_rework` 只阻断 Listing，账本终态和余额不变。

### Anti-pattern guards

- 不提供浏览器调用入口；CLI 不接受布尔批准 flag、`--idempotency-key`、source reference、自定义 points、expiry 或任意 company id。
- 不允许 production 默认开启 controlled acceptance。
- 不用 legacy bucket 冒充验收点。
- 不使用通用 reserve 侵占商家套餐点或购买点。

## Phase 7：完整本地门禁

### Commands

```powershell
python tools/test_jiejing_postgres_repository_cutover.py
python tools/test_jiejing_operational_health_readiness.py
python tools/test_jiejing_saas_ai_ceo_chat_model_boundary.py
python tools/test_jiejing_ai_ceo_market_report_recovery.py
python tools/test_jiejing_ai_ceo_listing_import_target.py
python tools/test_jiejing_listing_concrete_product_gate.py
python tools/test_jiejing_media_source_upload_http.py
python tools/test_jiejing_media_asset_jobs.py
python tools/test_jiejing_commercial_entitlements.py
python tools/test_jiejing_media_credit_purchase.py
python tools/jiejing_secret_scan.py
node --check app.js
python tools/jiejing_precloud_deployment_gate.py
```

若新增专用测试文件，加入 gate 并单独运行。任何失败先修复，不绕过。

## Phase 8：提交、备份、原子部署与生产回归

### What to implement/do

1. 检查 dirty worktree，只提交本方案相关文件。
2. 构建白名单 bundle 和 manifest，先执行 deploy dry-run；把 002/003 migrations、受控验收 CLI 和新增测试加入发布白名单。
3. 生产变更前从 owner-only `/backup/plan` 核验最新 managed backup/PITR 与恢复演练；保存 schema/受影响表恢复证据，禁止输出数据库 URL。若恢复证据过期则先阻断部署，不把旧容器回滚冒充数据库回滚。
4. 为生产 deploy apply 增加独占锁，避免两个发布同时替换同一 Compose project。
5. 使用现有确认门执行原子部署；让应用启动迁移在事务和 advisory lock 内补表。
6. 加强发布脚本 readiness 断言：`production_ready=true`、`can_accept_real_customers=true`、blocker/warning 为 0、secret false，而不是只检查字段存在。
7. 验证 `/health`、`/health/deep`、`/readiness/product-saas`、匿名私有接口 401/403、生产 source commit。
8. 查询生产日志，确认无 `42P01`、migration drift 和 secret exposure。

### Documentation references

- `tools/jiejing_production_deploy.py`
- `deploy/jiejing-production-release-apply.sh`
- `docs/JIEJING_PRODUCTION_DEPLOY_RUNBOOK_20260823.md`

### Verification

- 生产 required relations 全部存在。
- AI CEO 额度/素材点读取不再 503。
- 回滚 release 与恢复证据已记录。

## Phase 9：生产 AI CEO 真实商家回归

1. 使用已登录 Chrome 和当前店铺，从 AI CEO 提交禁止历史污染的全新选品指令。
2. 要求三个候选品、真实来源、价格证据或缺口、竞争/需求信号、合规/IP/售后/履约风险。
3. 验证模型真实调用任务、耗时、source records 和 artifact outcome。
4. 普通非 eBay 查询做负向回归，确认无 Listing CTA。
5. 选择候选前保持 `listing_import_ready=false`；选择后仍需供应商事实核验。

## Phase 10：真实素材与未发布草稿

1. 核验真实供应商/实物事实和图片商业使用权；不能证明则停在事实补充。
2. 经行动时确认后，发放一次 controlled acceptance 点并调用一次真实 FAL 生图。
3. 核验新图片文件、hash、manifest、事实/权利复核、实际素材点结算。
4. 生成 Listing 包，核对类目、item specifics、库存、价格、发货地、重量、尺寸、材质、成本利润与政策。
5. 经行动时确认后保存全新 eBay 未发布草稿，并用远端 offer/inventory item 只读核验。

## Phase 11：账号健康与公开发布决策

1. 登录态只读核验当前替代账号 store-scoped connection、OAuth/Vault identity、account health、6/6 packet 和 Business Policies。
2. 原冻结账号继续禁止复用，不重复 OAuth。
3. 若任何商品事实或账号健康证据不足，明确停在未发布草稿。
4. 只有全部通过时，展示最终发布摘要并获得一次行动时确认；再临时开放受控 publish 执行。
5. 公开发布后按 SKU/listing id 只读核验；超时或 502 禁止盲目重试。

## Final verification

- 对照设计文档逐项核验验收标准。
- grep 已知 anti-pattern：前端权威 report、发送前 Listing 同步、硬编码 ready、生产公开 grant、secret-like 输出。
- 保存测试、部署、health、AI task、FAL asset、素材点账本、eBay draft/publish 的 value-free 证据。
- 只有远端 listing id 可查且状态正确时才能报告“已公开上线”。
