# 捷境短期访问会话与设备撤销设计

## 1. 背景

捷境当前浏览器认证已经具备 `HttpOnly`、`Secure`、`SameSite`、服务端 `jti`
撤销和退出即失效，但访问会话默认仍可持续七天。2026-08-10 安全审计因此保留一项
paid-launch P1：设备丢失或 cookie 被复制后，缺少短期访问凭证、轮换刷新凭证和商家可见的
设备会话管理。

本设计关闭这一项，不改变 eBay OAuth、支付、退款、配额、真实平台写入或正式上线判定。

## 2. 目标

- production-like 环境新签发的访问会话最多 30 分钟。
- 浏览器通过独立 `HttpOnly` 刷新 cookie 在后端轮换续期，默认最长 30 天。
- 刷新 token 原值只存在浏览器 cookie 和当前请求内存中；数据库只保存 SHA-256。
- 每次刷新原子作废上一代并生成下一代；已轮换 token 被重放时整组会话失效。
- 设置页展示当前账号的安全设备摘要，并允许精确退出一个设备或退出其他全部设备。
- access/refresh token、cookie、token hash、原始 User-Agent 和 IP 不进入 API JSON、DOM、
  localStorage、sessionStorage、日志、审计 details 或分析事件。
- 现有 Bearer 工具调用保持兼容，但不会得到浏览器刷新 cookie。

## 3. 非目标

- 不实现第三方身份提供商、MFA 或 passkey。
- 不把刷新 token 改成可被 JavaScript 读取的 JWT。
- 不允许前端直接创建、延长或恢复会话。
- 不通过本次改动开放公开收费、微信支付 Live API、eBay 写入或 paid launch。
- 不把设备摘要当作风控、地理位置或用户画像。

## 4. 方案选择

### 方案 A：后端不透明刷新会话 + 短期签名访问 cookie（采用）

访问 cookie 保留现有签名格式并增加 `sid`/`token_type=access`；刷新 token 使用随机不透明值，
数据库只保存哈希和会话族状态。优点是浏览器无 secret 可读、服务端可以撤销和检测重放，
并能渐进兼容现有 Bearer 工具。缺点是增加一张表和一次刷新事务。

### 方案 B：把长期 JWT 放进刷新 cookie（拒绝）

服务端撤销与轮换重放检测较弱，而且会继续扩大长期签名凭证的风险窗口。

### 方案 C：只把现有七天 TTL 改为 30 分钟（拒绝）

实现简单，但会频繁中断商家工作，无法达到“安全且可用”的产品标准。

## 5. 数据模型

新增 `user_refresh_sessions`（一个设备登录对应一个会话族）：

- `session_id`：随机不可猜测的公开会话引用，不具备认证能力；主键。
- `current_token_hash`：当前代刷新 token 的 SHA-256；唯一且不得返回。
- `user_id`、`company_id`：租户和用户边界。
- `device_class`：服务端 allowlist 分类，如 `chrome_windows`、`edge_windows`、`mobile_safari`、
  `unknown_browser`；不保存原始 User-Agent。
- `status`：严格枚举 `active`、`rotated`、`revoked`、`expired`、`replay_revoked`。
- `created_at`、`last_seen_at`、`expires_epoch`、`revoked_at`。

新增 `user_refresh_token_history`（保留到会话族过期）：

- `token_hash`：每一代刷新 token 的 SHA-256；主键。
- `session_id`、`generation`：精确关联会话族且代际唯一。
- `status`：严格枚举 `active`、`rotated`、`replay_revoked`、`expired`。
- `issued_at`、`rotated_at`、`replayed_at`、`expires_epoch`。

轮换时同一事务更新 `current_token_hash`、把旧 generation 标为 `rotated` 并插入下一代。
任意历史 generation 再出现都能命中历史表并撤销整个 `session_id`，不是只识别上一代。

访问会话的 `user_sessions` 增加可空 `refresh_session_id`，使 access `jti` 可关联到设备会话。
外键不是授权来源；每次读取仍精确校验 `user_id`、`company_id` 和状态。

SQLite 使用 `BEGIN IMMEDIATE`，Postgres 使用事务和行锁。轮换/撤销必须单赢家，不能先返回
新 cookie 再落库。

## 6. Cookie 与 token 合同

### 6.1 访问 cookie

- 名称沿用 `jiejing_saas_session`。
- `HttpOnly; Secure`（staging/production）；`SameSite=Lax`，运营控制台仍为 `Strict`。
- production-like `Max-Age <= 1800`。
- 签名 payload 包含 `token_type=access`、唯一 `jti`、设备 `sid`、`iat`、`exp`、
  `user_id`、`company_id`、`email`。

### 6.2 刷新 cookie

- 名称 `jiejing_saas_refresh`。
- `HttpOnly; Secure; SameSite=Strict; Path=/auth`。
- 默认 `Max-Age=2592000`，production-like 最大 30 天。
- value 为高熵随机不透明 token；不编码用户、租户或时间。

### 6.3 兼容期

部署前已存在且没有 `sid` 的访问 token 继续按原 `exp` 验证，但不能调用刷新接口；到期后重新
登录。新登录、注册、owner 登录和公司切换全部签发新合同。这样不需要读取或迁移现有 cookie，
且最长七天后自然消除旧会话。

## 7. HTTP 接口

### `POST /auth/refresh`

- 只从刷新 cookie 读取 token，拒绝 JSON、query、Authorization 传入的刷新 token。
- production-like 必须通过现有 HTTPS Origin 边界。
- 原子验证 active、未过期、精确 user/company、当前哈希唯一后轮换。
- 返回 value-free `{ok, session_refreshed, secret_exposed:false}`，并设置新的 access/refresh cookie。
- 任意 rotated token 重放：撤销同 `session_id` 的 refresh 会话和关联 access `jti`，返回固定 401。

### `GET /auth/sessions`

- 需要有效访问会话。
- 仅返回 `session_ref`、`device_label`、`created_at`、`last_seen_at`、`current`、`status=active`。
- 只返回当前 `user_id` 的会话；company 切换不改变账号设备边界。

### `POST /auth/sessions/{session_ref}/revoke`

- 需要有效访问会话和同一用户精确绑定。
- 原子撤销目标 refresh session 及其所有 access `jti`。
- 目标是当前设备时同时清除两枚 cookie。
- 错用户、错租户、畸形/重复 ref 固定 fail closed，不暴露会话是否存在。

### `POST /auth/sessions/revoke-others`

- 保留当前 `sid`，撤销同一用户的其他 active family。
- 返回仅包含撤销数量和安全布尔值。

现有 `POST /auth/logout` 同时撤销当前 access `jti` 和 refresh family，并清除两枚 cookie。

## 8. 前端行为

- `saasFetch` 遇到一次 401 时，可对非 auth 请求执行一次 `POST /auth/refresh`，成功后只重放
  原请求一次；刷新失败立即进入登录页，禁止递归重试。
- 同一页面并发 401 共享一个 refresh Promise，避免刷新 token 并发轮换导致误判重放。
- 设置 -> 账号与店铺增加“登录设备”区；只显示设备类别和时间。
- 撤销按钮通过页面内 `WeakMap` 绑定 `session_ref`，不得把 ref 写入 DOM 属性或浏览器存储。
- UI 不显示 IP、城市、原始 User-Agent、cookie、token 或哈希。

## 9. 错误与审计

- 公共错误固定为 `session_refresh_required`、`session_refresh_invalid`、
  `session_refresh_replay_blocked`、`session_revoke_not_allowed`。
- 审计只记录固定 action、设备类别、是否当前设备、撤销数量和 `secret_exposed=false`；目标使用
  code-owned 类型，不写 token/ref/hash/UA/IP。
- 数据库/日志异常不得让 refresh token 回到响应，也不得在轮换事务失败后发新 cookie。

## 10. TDD 验收矩阵

按垂直切片逐条 RED→GREEN：

1. 登录签发短 access + refresh cookie；JSON/DOM/storage/log 无 token。
2. access 过期后 refresh 成功并轮换；旧 refresh 再用触发 family 撤销。
3. 两个并发 refresh 只有一个成功，另一个固定阻断且不会产生第二个 active generation。
4. logout 同时使 access 和 refresh 失效。
5. 两设备登录后清单为 2；撤销另一设备后其 access/refresh 均 401，当前设备仍有效。
6. 错用户、错 company、畸形 ref、过期/未来/重复行全部 fail closed。
7. 原始 token、cookie、哈希、UA、IP 在响应、异常、审计、DOM、local/session storage 中零命中。
8. Postgres migration、SQLite migration、session revocation、Origin/CSRF、登录恢复和设置页回归通过。

## 11. 发布与回滚

- 先在本地/127 fixture 完成攻击矩阵，再运行安全 focused 和完整 precloud。
- staging dry-run 成功后才 apply；部署后只读验证 health/deep/readiness 和 cookie 属性。
- 不使用真实支付、eBay OAuth、同步或写操作验证本功能。
- 回滚代码时保留新增表；旧服务忽略该表。若刷新链异常，用户最多需要重新登录，不放宽
  Origin、cookie 或服务端撤销边界。
