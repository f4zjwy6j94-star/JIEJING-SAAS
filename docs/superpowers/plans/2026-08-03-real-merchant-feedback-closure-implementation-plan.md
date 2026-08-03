# 捷境真实商家反馈闭环实施计划

日期：2026-08-03

批准设计：`docs/superpowers/specs/2026-08-03-real-merchant-feedback-closure-design.md`

## 目标与边界

本计划把现有只写浏览器 `localStorage` 的 `product_improvement` 产品/流程意见升级为后端权威、租户隔离、可重试、可审计并能在独立运营后台处理的真实反馈闭环。

本次只处理明确的产品改进意见，不迁移“有用、没用、记住规则”等经营记忆，不扩展为通用客服工单或 CRM，不接入第三方通知，不触发 eBay OAuth、eBay 读写、付款、退款、广告、采购、改价、库存或政策修改。固定商业化进度不增加，`production_ready`、`can_accept_real_customers`、`public_charging_allowed` 和真实平台写入继续由既有门禁控制。

## 不可违反的约束

- 保留当前工作区，不 reset、clean、checkout、stash、批量格式化或触碰 `.superpowers/`。
- 商家成功提示只能来自服务器回执；本机保存、超时、401、429、503 或网络失败均不能显示“已送达”。
- 所有商家读写由认证身份派生 `company_id` 和 `user_id`；不接受客户端提供的租户、操作者、状态或内部权限字段。
- 新待发队列使用独立 storage key，不混入同时承载经营记忆的 `jiejing_saas_merchant_feedback`。
- 后端再次执行严格白名单、限长、控制字符处理和 secret-like 文本脱敏；前端清洗不是安全边界。
- 原始幂等键、反馈正文、上下文编号、密码、Token、Secret、API Key、Cookie、Authorization header 和原始 IP 不进入访问日志或审计正文。
- 状态推进只能是 `open -> reviewing -> resolved`；不能由浏览器选择任意目标状态、倒退或跳级。
- `ops.jiejing.shop` 只精确开放所需反馈路由；禁止开放整个 `/owner` 或广泛后端前缀。
- additive migration 和真实反馈记录在代码回滚后保留；禁止用清理数据作为回滚方式。

## Phase 0：文档发现、允许 API 与复制来源

### 允许复用的后端模式

- `jiejing_saas/repository.py:151-795`：SQLite 初始化、additive 表、索引和 migration 记录模式。
- `jiejing_saas/repository.py:4300-4434`：条件更新、并发冲突和同事务审计模式。
- `jiejing_saas/repository.py:4566-4747`：公司作用域哈希幂等模式；只复用哈希思想，不复制原始幂等键持久化。
- `jiejing_saas/repository.py:4776-4855`：同一事务中写主记录、读回和记录审计。
- `jiejing_saas/repository.py:6658-7406`：内部运营聚合合同。
- `jiejing_saas/repository.py:7409-7706`：内部 detail section、筛选、游标、上限和安全短引用模式。
- `jiejing_saas/repository.py:8351-8407`：共享数据库 rate-limit bucket；数据库不可用时本功能必须 fail closed，不用进程内 fallback 假装共享限流成功。
- `jiejing_saas/repository.py:8864-8897`：`_insert_audit(...)`；反馈创建和状态推进必须在同一事务中写审计。
- `jiejing_saas/repository.py:9389-9430`：`_redact_secret_like()` 与 `_redact_secret_text()`；在严格字段白名单后复用。
- `jiejing_saas/api_server.py:1323-1328`、`:2550-2588`：认证后商家 GET/POST、400/409 映射模式。
- `jiejing_saas/api_server.py:1519-1553`、`:2590-2643`：platform internal admin detail 和固定状态动作模式。
- `jiejing_saas/api_server.py:5900-5909`：`_require_auth()`。
- `jiejing_saas/api_server.py:6670-6674`：`_require_platform_internal_admin(identity, label)`。
- `jiejing_saas/api_server.py:6136-6180`：共享限流消费边界。
- `jiejing_saas/postgres_repository_runtime.py:20-50`：PostgreSQL JSONB 列白名单。
- `jiejing_saas/migrations/001_initial_schema_postgres.sql:390-434,544-612,614-708`：PostgreSQL 公司级幂等表、索引和 migration marker 风格。

### 允许复用的浏览器和运营后台模式

- `app.js:16311-16424`：`saasFetch()` 和可真正 abort 的 `saasFetchWithTimeout()`；写请求不得使用超时后仍继续的 `optionalSaasFetchFast()`。
- `app.js:20911-21205`：现有反馈作用域、清洗、抽屉、原因按钮和提交入口。
- `app.js:26091-26528`：认证身份和店铺已经应用后的安全初始化位置。
- `ops.js:4-24,125-155,303-453,489-538`：独立 ops view、cookie transport、detail renderer、筛选、分页和动作绑定。
- `ops.html:42-92`、`ops.css:136-238`：现有 ops 导航、内容区、表格、按钮、空态和响应式模式。
- `tools/test_jiejing_merchant_onboarding_state.py:316-425`：真实本地 HTTP 服务、401、租户和 409 测试模式。
- `tools/test_jiejing_operations_console.py:79-204`：ops 401/403、Strict HttpOnly cookie、精确代理白名单、恶意筛选和无 Secret 测试。
- `tools/codex_jiejing_operations_console_smoke.js:96-221`：ops 桌面、平板、移动端、XSS 和 detail fixture 模式。

### 禁止模式

- 禁止先 SELECT 后 INSERT 的非原子幂等实现。
- 禁止 `insert or replace` 处理复合幂等键或覆盖反馈。
- 禁止相同幂等键配合不同载荷时静默返回成功。
- 禁止把 task/report/confirmation/packet ID 当作授权或跨租户查询依据。
- 禁止把反馈正文复制进审计、访问日志、错误日志或公开 readiness。
- 禁止在身份尚未确定时读取 `anonymous`、公司名或旧账号 fallback scope 的待发记录。
- 禁止使用普通 expensive-IP limiter 代替公司/用户/IP 三层共享反馈限流。
- 禁止在 ops.js 使用 localStorage/sessionStorage 保存内部登录状态。
- 禁止把内部反馈队列、处理状态、供应商名称或诊断数据放进商家主站。

## Phase 1：RED——规范化、幂等和持久化合同

### 文件

- 新增 `jiejing_saas/product_feedback.py`。
- 新增 `tools/test_jiejing_product_feedback_closure.py`。
- 修改 `jiejing_saas/repository.py`。
- 修改 `jiejing_saas/migrations/001_initial_schema_postgres.sql`。
- 修改 `jiejing_saas/postgres_repository_runtime.py`。
- 扩展 `tools/test_jiejing_postgres_repository_cutover.py`。

### 先写失败测试

1. 只接受 `feedback_type=product_improvement`、现有工作舱模块枚举和 `unclear|wrong_result|missing_action`。
2. detail 上限 420、stage title 上限 160；控制字符、HTML 和 secret-like 文本被清洗或脱敏。
3. 客户端提供 `company_id/user_id/store_id/status/internal_note` 时拒绝，不静默保存。
4. 新公司没有反馈；创建后只能由同一 `company_id` 读回安全回执。
5. 同一公司、同一幂等键、同一规范载荷只创建一次，并返回 `duplicate_request=true`。
6. 同一幂等键配合不同规范载荷抛 `ProductFeedbackIdempotencyConflict`，原记录不变。
7. 原始幂等键不出现在数据库 JSON、响应、审计或序列化结果中。
8. 创建反馈审计只包含模块、原因、正文是否存在和长度等摘要，不复制正文或上下文编号。
9. `open -> reviewing -> resolved` 通过条件更新和同事务审计成功；跳级、倒退、重复处理或未知 ID fail closed。
10. SQLite 重复 initialize 不丢数据；PostgreSQL SQL 含表、复合唯一约束、两个索引、JSONB 和 migration marker。
11. `feedback_json` 被加入 PostgreSQL runtime JSONB 适配白名单。

先运行并确认因模块、表和方法尚不存在而失败：

```powershell
python tools/test_jiejing_product_feedback_closure.py
python tools/test_jiejing_postgres_repository_cutover.py
```

测试使用 `tempfile.TemporaryDirectory()`，不得删除或清理仓库现有 `output/`。

### 最小实现

`jiejing_saas/product_feedback.py` 只定义常量、异常和纯规范化函数：

- `ProductFeedbackValidationError`
- `ProductFeedbackIdempotencyConflict`
- `ProductFeedbackStatusConflict`
- `normalize_product_feedback_payload(payload)`
- `product_feedback_payload_hash(payload)`

模块枚举固定为现有商家工作舱：`cockpit`、`workflow`、`product`、`bulk`、`media`、`confirm`、`service`、`connect`、`activity`。后续新增模块另行更新枚举和测试，不接受任意字符串。

新增 `merchant_product_feedback` 表，字段和约束遵循批准规格。幂等哈希使用 `sha256(company_id + raw_idempotency_key)`；规范载荷哈希存入安全 JSON。插入使用原子 conflict-do-nothing/returning 语义，重复后读回并比较载荷哈希。

Repository 新增：

- `create_product_feedback(...)`
- `list_product_feedback(company_id, limit=20)`
- `transition_product_feedback_status(feedback_id, actor_user_id, target_status)`

状态动作不接受客户端公司、任意前置状态或处理备注。owner 路由决定合法目标和前置状态。

## Phase 2：RED→GREEN——认证 API、共享限流与日志隐私

### 文件

- 修改 `jiejing_saas/api_server.py`。
- 扩展 `tools/test_jiejing_product_feedback_closure.py`。
- 修改 `tools/test_jiejing_saas_p0_security_guardrails.py` 的现有安全访问日志合同测试。

### API 行为测试

1. 未认证 `POST/GET /product-feedback` 返回 401。
2. 认证提交返回 201、`delivered=true`、安全回执和 `duplicate_request=false`。
3. 同载荷重放返回 200、原 feedback ID 和 `duplicate_request=true`；同键异载荷返回 409。
4. 验证失败返回 400，数据库没有半条记录。
5. merchant GET 只列本公司、最多 50 条安全回执，不返回正文、内部状态说明或租户 ID。
6. 普通商家访问 feedback operations/detail/review/resolve 返回 403；未认证返回 401。
7. internal admin 可以按固定路由推进状态；未知 ID 返回 404，非法状态返回 409。
8. rate limit 同时使用用户、公司和可信代理 IP 的共享数据库 bucket；任一失败返回 429。
9. 共享 bucket 数据库不可用返回 503，由浏览器排队；不能 fallback 为单进程限流后声称已送达。
10. 响应、错误、审计和生产访问日志不包含正文、原始幂等键、Authorization、Cookie、Secret 或原始 IP。

### 实现

新增：

- `POST /product-feedback`
- `GET /product-feedback?limit=20`
- `POST /owner/product-feedback/review`
- `POST /owner/product-feedback/resolve`

商家提交使用专用 `_check_product_feedback_rate_limit(identity)`。默认 60 秒窗口，12/用户、30/公司、60/IP，并通过有上下界的环境变量可调。bucket 表只保存 subject 哈希；真实值不进入响应或日志。

生产访问日志当前包含原始 `client_ip`，与批准规格冲突。本阶段把访问事件改为不保存原始 IP；若现有监控需要请求关联，使用与反馈内容、账号和凭证无关的已有 request/event ID，不引入可逆 IP 标识。对应回归必须覆盖所有请求，不只特殊处理 feedback 路由。

## Phase 3：RED→GREEN——运营聚合、feedback detail 与独立后台

### 文件

- 修改 `jiejing_saas/repository.py`。
- 修改 `jiejing_saas/api_server.py`。
- 修改 `ops.html`、`ops.js`，仅在现有样式不足时最小修改 `ops.css`。
- 修改 `deploy/nginx.public-staging.conf`。
- 扩展 `tools/test_jiejing_operations_console.py`。
- 扩展 `tools/codex_jiejing_operations_console_smoke.js`。

### 后端聚合与权限

1. `platform_operations_overview()` 增加内部 `product_feedback` 聚合：total/open/reviewing/resolved、按模块和原因、最旧 open 年龄。
2. synthetic-test 账号反馈不计入真实经营聚合；数据质量字段明确排除数量。
3. `platform_operations_detail()` section 白名单加入 `feedback`，复用 period/cursor/limit/status/module。
4. feedback detail 返回清洗后的短文本和状态，设置 `raw_merchant_content_exposed=false`、`sanitized_feedback_text_internal_only=true`；不返回 company/user/store ID、上下文原始编号或幂等哈希。
5. 普通商家仍不能访问任何 operations detail。

### 独立 ops UI

1. 现有导航增加“产品反馈”，不创建第二套后台。
2. overview 增加待处理反馈指标；detail 支持状态和模块筛选。
3. 每条反馈只对合法状态显示固定“开始处理”或“标记解决”按钮。
4. 动作成功后强制刷新 feedback detail 和 overview；失败显示真实错误，不乐观伪造状态。
5. 所有动态文本继续经过 `escapeHtml()`；恶意 HTML 不执行。
6. ops 设置文案从“完全只读”更正为“经营数据只读，反馈处理只更新内部状态”，避免新的文案失真。
7. `ops.js` 继续只使用 HttpOnly Strict cookie，不使用 browser storage。

Nginx 精确加入：

- `GET /owner/operations/feedback`
- `POST /owner/product-feedback/review`
- `POST /owner/product-feedback/resolve`

不得开放 broad `/owner`。Caddy 继续只反代本机 Nginx，无需增加第二套路由。

修改 ops 静态文件后，把 `ops.html` 的 CSS/JS cache version 统一升级为 `20260803-product-feedback-v1`，并增加版本回归断言。

## Phase 4：RED→GREEN——商家端真实送达与离线 outbox

### 文件

- 修改 `app.js`。
- 仅在现有 `.workflow-feedback-status` 无法表达状态时最小修改 `styles.css`。
- 修改 `app.html`、`index.html` 的 app.js cache version。
- 新增 `tools/codex_jiejing_product_feedback_smoke.js`。
- 扩展 `tools/test_jiejing_media_nav_and_state_restore.py` 和 `tools/test_jiejing_saas_clean_settings_and_listing_ui.py`。
- 修改 `tools/test_jiejing_frontend_staging_config.py`。

### 独立 storage 与无损迁移

新增独立 storage keys：

- `jiejing_saas_product_feedback_outbox_v1`，每个真实 identity/store scope 最多 20 条；
- `jiejing_saas_product_feedback_receipts_v1`，每个 scope 最多 40 条；
- `jiejing_saas_product_feedback_migration_v1`，记录当前作用域旧反馈迁移完成状态。

待发 scope 必须使用已认证 `company_id + user_id + store_id/account-wide`，禁止使用 anonymous、邮箱别名、公司名或旧账号 fallback。

首次升级后，在真实身份和店铺确定时，将当前作用域旧 `jiejing_saas_merchant_feedback` 中 `product_improvement` 记录映射到新 outbox。只复制批准白名单字段，保留稳定幂等键，交给服务端再次脱敏；成功回执前不删除旧本机记录。`useful/not_useful/remember_rule` 留在原经营记忆路径。

### 浏览器状态机

1. 提交前先把安全记录写入 outbox，再设置 `submitting`。
2. 使用 `saasFetchWithTimeout('/product-feedback', {method:'POST', body: ...})`，同一 outbox 项每次重试复用相同幂等键。
3. 只有 201/200 服务器回执进入 `delivered`，移动到 receipts，清除 outbox 项和表单草稿。
4. 网络、超时、401、429、503 或 5xx 保留 outbox，显示“本机待重试”；401 明确要求登录。
5. 400 验证错误保持抽屉和用户草稿，移除不可自动重试的错误请求并显示可修正原因。
6. 409 幂等冲突 fail closed，不自动生成新键覆盖原意；保留安全记录并提示人工重试。
7. 登录状态应用完成、`window online` 和用户手动重试时 flush；初始化身份之前绝不发送。
8. 自动 flush 串行、有界，不并发重复发送，不阻塞工作舱主数据加载。

### 浏览器验证

新 smoke 覆盖：

- 后端 201 才显示“已送达”；
- 离线/超时显示本机待重试且队列存在；
- 恢复 online 后使用同一幂等键并清队列；
- 401 不跨账号发送；切换账号不能读取另一作用域 outbox；
- 400 保持草稿；409 不静默覆盖；
- 产品反馈不进入 AI CEO chat/memory；
- 桌面和手机抽屉不遮挡发送按钮、底部导航或核心操作。

app.js 修改后，把 `app.html` 与 `index.html` 的 app.js cache version 统一升级为 `20260803-product-feedback-v1`，并更新缓存合同测试。若未修改 styles.css，不改其版本；若确实修改则同步升级并测试。

## Phase 5：部署白名单、完整门禁与主理人审计

### 文件

- 修改 `tools/jiejing_precloud_deployment_gate.py`。
- 修改 `deploy/apply-staging-patch.sh`。
- 修改 `tools/test_jiejing_staging_patch_apply_contract.py`。
- 必要时修改 `tools/jiejing_prepare_public_staging_bundle.py` 的合同测试，不复制第二份文件清单。

### Gate 与 bundle

把以下新文件加入 gate、patch FILES、py_compile/test 段和 whitelist contract：

- `jiejing_saas/product_feedback.py`
- `tools/test_jiejing_product_feedback_closure.py`
- `tools/codex_jiejing_product_feedback_smoke.js`
- 新设计与实施计划文档（用于完整 bundle 交接，不在运行时导入）

完整 gate 从当前 111 项增加两个独立检查后应为 113 项；不得继续报告旧的 107/111。bundle 必须包含 SQLite/PostgreSQL/API、app、ops、Nginx、测试和缓存版本的全部改动。

### 聚焦验证顺序

```powershell
python -m py_compile jiejing_saas/product_feedback.py jiejing_saas/repository.py jiejing_saas/api_server.py tools/test_jiejing_product_feedback_closure.py
python tools/test_jiejing_product_feedback_closure.py
python tools/test_jiejing_postgres_repository_cutover.py
python tools/test_jiejing_saas_p0_security_guardrails.py
python tools/test_jiejing_operations_console.py
node tools/codex_jiejing_product_feedback_smoke.js
node tools/codex_jiejing_operations_console_smoke.js
python tools/test_jiejing_media_nav_and_state_restore.py
python tools/test_jiejing_saas_clean_settings_and_listing_ui.py
python tools/test_jiejing_frontend_staging_config.py
node --check app.js
node --check ops.js
python tools/test_jiejing_staging_patch_apply_contract.py
python tools/jiejing_secret_scan.py
python tools/jiejing_precloud_deployment_gate.py
```

### 主理人级审查

完成代码后主动复核：

- 产品价值：内测意见是否真正到达并可处理，而不是新增一个无人使用的后台模块。
- 新手体验：提交、离线、重新登录和失败提示是否一眼能懂。
- 租户隔离：公司、用户、店铺作用域、登出、切换账号和旧缓存迁移是否会串租户。
- 安全：正文、secret-like 文本、原始 IP、幂等键、Cookie 和内部状态是否泄漏。
- 可靠性：响应丢失、重复、并发、数据库限流失败、ops 处理冲突和回滚是否 fail closed。
- 现实校验：代码完成不等于真实商家 5 分、正式支付、eBay 上线或公开收费 ready。

低风险且直接相关的问题在本轮修复；需要真实账号、支付机构、外部商家或部署 apply 的事项只报告，不编造完成证据。

## Phase 6：提交、dry-run、apply 边界与线上只读验收

1. 实现与测试以 scoped code-only 提交保存，不混入 `.superpowers/` 或无关工作区变化。
2. push 后等待 CI，再运行 GitHub Actions staging dry-run。
3. dry-run 成功后，apply 仍按仓库部署合同取得针对本提交的独立批准；本次书面规格批准不自动等于部署 apply 批准。
4. apply 后使用有效 TLS 和浏览器风格 User-Agent 验证：
   - `https://app.jiejing.shop/health`
   - `https://app.jiejing.shop/health/deep`
   - `https://app.jiejing.shop/readiness/product-saas`
   - `https://ops.jiejing.shop/` 登录权限与反馈视图
   - app 主站对 `ops.html` 和内部反馈运营路由的隔离
5. 线上只用安全模拟反馈完成“提交、幂等重放、内部处理、商家回执”验收；不调用 eBay、支付或外部通知。
6. 任一 TLS、权限、租户、日志、secret scan 或健康检查失败时停止 apply/后续发布，保持公开收费和真实平台写入关闭。

## 完成定义

- 当前虚假成功提示被真实服务器回执取代。
- 离线、超时、会话过期和服务不可用时反馈不丢失、不跨账号、不虚报成功。
- SQLite/PostgreSQL 表、哈希幂等、同事务审计、共享限流和条件状态迁移全部通过测试。
- 商家只能看到本公司的安全回执；普通商家不能访问 ops 反馈数据或处理动作。
- 独立运营后台能安全查看、筛选并处理清洗后的反馈，且主站仍隔离。
- 原始 IP、反馈正文、幂等键、Secret、Token、Cookie 和内部诊断不进入不应出现的响应、日志或审计。
- 聚焦测试、113 项完整 gate、secret scan、bundle/manifest/SHA256 和 staging dry-run 全部通过。
- apply 前保留独立批准；部署后有效 TLS、健康、权限和隔离证据通过。
- 固定商业进度不虚增，未发生真实 eBay 写入、付款、退款或其他高风险外部动作。
