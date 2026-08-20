# 捷境短期会话与设备撤销实施计划

## 目标

按 `docs/superpowers/specs/2026-08-20-session-rotation-and-device-control-design.md`
关闭 2026-08-10 安全审计中的会话 P1，同时保持登录可用、租户隔离、后端 secret 边界、
公开收费关闭和 eBay 真实写入门禁不变。

## Phase 0：文档与现有 API 发现

### 已核对来源

- `jiejing_saas/security.py:38-114`：现有 `SessionPayload`、`SessionManager.create_token()`、
  `SessionManager.verify_token()` 与环境 TTL seam。
- `jiejing_saas/repository.py:250-258,961-1008`：现有 `user_sessions`、
  `ensure_user_session()`、`revoke_user_session()`。
- `jiejing_saas/api_server.py:2527-2589,7214-7301`：登录、退出、公司切换、认证、访问 cookie
  与 production-like 浏览器响应。
- `app.js:16402-16443`：所有 JSON 请求的统一 `saasFetch()` seam 和 cookie credentials。
- `app.js:19699-19806`：设置页账号入口和退出行为。
- `jiejing_saas/migrations/001_initial_schema_postgres.sql:48-55,577`：Postgres session 表与索引。
- `tools/test_jiejing_session_revocation.py:24-82`：真实 HTTP 登录/退出/撤销回归模板。
- `docs/JIEJING_SECURITY_BEST_PRACTICES_AUDIT_20260810.md:56-61`：待关闭 P1 的验收方向。
- `C:/Users/57249/.codex/skills/security-best-practices/references/javascript-general-web-frontend-security.md`
  的 JS-STORAGE-001：认证标识不进入 local/session storage，优先 `HttpOnly` cookie。

### 允许复用的 API

- Python 标准库：`secrets.token_urlsafe`、`hashlib.sha256`、`hmac.compare_digest`、
  `http.cookies.SimpleCookie`。
- Repository 事务：现有 `_connect()`、SQLite/Postgres 参数适配、`write_audit()`；Postgres 行锁
  沿用仓库已有 `for_update_clause()`/事务模式，不发明新 driver API。
- HTTP：现有 `_send_json()` 多 `Set-Cookie` header seam、`_require_auth()`、
  production-like Origin 检查。
- 前端：现有 `fetch(... credentials:"include")`、页面级 Promise 去重和 `WeakMap` DOM 绑定模式。

### 禁止模式

- 不把 refresh token 设计成前端可读 JWT。
- 不把 token、cookie、hash、原始 UA、IP 或 session ref 写入日志/analytics/storage/DOM 属性。
- 不只用内存锁实现轮换；多进程/多副本必须依赖数据库事务。
- 不在 401 后无限刷新或重放非幂等请求两次。
- 不删除现有 Bearer 测试兼容 seam，也不把 production token 返回给前端。

## Phase 1：Repository 会话族与轮换事务

### What to implement

1. 复制现有 `user_sessions` 建表/索引模式，新增 `user_refresh_sessions` 和
   `user_refresh_token_history` 到 SQLite 初始化及 Postgres 初始迁移。
2. 给 `user_sessions` 增加可空 `refresh_session_id`，SQLite 用 `_ensure_columns` 兼容旧库，
   Postgres 用幂等 `alter table ... add column if not exists`。
3. 新增小接口：
   - `create_browser_refresh_session(...) -> (public_summary, raw_refresh_token)`；raw 只返回调用栈。
   - `rotate_browser_refresh_session(raw_token) -> (identity, public_summary, next_raw_token)`。
   - `list_browser_sessions(user_id, current_session_id)`。
   - `revoke_browser_session(...)`、`revoke_other_browser_sessions(...)`、
     `revoke_current_browser_session(...)`。
4. 所有 token 比对使用 SHA-256 lookup + `hmac.compare_digest`；轮换/重放/撤销在同一事务完成。
5. 签发前验证精确 user/company 成员关系，并为 `user_sessions.refresh_session_id` 建立撤销索引。
6. 合法新签发时有界清理已到期 access、token history 和无引用 refresh family；access 持久化失败
   则 best-effort 撤销刚创建的 family，禁止留下可用孤儿会话。

### Tracer RED→GREEN

新增 `tools/test_jiejing_rotating_browser_sessions.py`，第一条只验证：创建后数据库无 raw token，
第一次 rotate 成功，旧 token 再用触发整个 session 撤销。

### Verification

- raw sentinel 在 SQLite/Postgres-shaped rows、audit、异常文本和公开 summary 中零命中。
- 四并发 rotate 只有一个成功；最终 active generation 恰好 1。
- wrong user/company、expired、malformed、duplicate rows 全 fail closed。
- `python -m py_compile` 与 Postgres cutover focused 通过。

## Phase 2：短期 access token 与 HTTP cookie 合同

### What to implement

1. 扩展 `SessionPayload` 为 `token_type=access` 和可选 `sid`；新登录传入 refresh session id。
2. production-like access TTL 硬上限 1800 秒；local/test 保持可覆盖。
3. 登录、注册、owner 登录签发 access + refresh 两枚 cookie；生产响应仍不返回 token。
4. 新增 `POST /auth/refresh`，只从 refresh cookie 取值，原子轮换后设置两枚新 cookie。
5. logout、公司切换和认证校验精确关联 session id；logout 清除两枚 cookie。

### Tracer RED→GREEN

扩展真实 HTTP 测试：登录响应包含两条安全 cookie；将 access TTL 调短后 `/auth/refresh`
恢复 `/me`，旧 refresh cookie 重放返回固定 401，且无 token 进入 JSON。

### Verification

- production cookie 属性精确：access `HttpOnly/Secure/Lax`，refresh
  `HttpOnly/Secure/Strict/Path=/auth`，并与公网 Caddy/Nginx 路由一致。
- refresh body/query/Authorization 注入均被忽略或拒绝。
- Origin mismatch 在读取/轮换 token 前阻断。
- refresh 失败不返回新 cookie，不把数据库异常替换成包含值的错误。

## Phase 3：设备清单与精确撤销 HTTP

### What to implement

1. `GET /auth/sessions` 返回当前用户 value-free 设备摘要。
2. `POST /auth/sessions/{session_ref}/revoke` 与
   `POST /auth/sessions/revoke-others` 使用当前访问身份，精确 user/company 边界。
3. 当前设备撤销时清除两枚 cookie；其他设备撤销不影响当前会话。
4. 写固定、无 ref/token/UA/IP 的审计事件。

### Tracer RED→GREEN

真实 HTTP 创建两个 cookie jar：清单为 2，设备 A 撤销 B 后 B 的 access/refresh 均 401，A 仍可
访问；跨账号使用同一 ref 固定 404/403 且不泄露存在性。

### Verification

- malformed/empty/duplicate session ref fail closed。
- 清单不包含 `token/hash/cookie/ip/user_agent/company_id/user_id`。
- 权限与租户攻击矩阵通过。

## Phase 4：前端自动刷新与设置页设备控制

### What to implement

1. 在 `saasFetch()` 内增加单一共享 refresh Promise 和同源 Web Locks 跨标签页锁；只对非 auth
   请求的一次 401 生效，成功后原请求最多重放一次。锁内先探测 `/me`，避免其它标签完成轮换
   后再次使用旧代 cookie。
2. NDJSON 流式请求不自动重放已发送 body；到期时显示重新连接提示，避免模型请求重复计费。
3. 设置 -> 账号与店铺读取 `/auth/sessions`，显示设备类别、创建/最近活动和当前设备。
4. 撤销按钮通过 `WeakMap<HTMLButtonElement, session_ref>` 绑定；DOM/storage/log 无 ref。
5. `ops.js` 复用同一跨标签 refresh 锁；运营只读 GET/HEAD 最多恢复并重放一次，任何运营 POST
   不触发 refresh、不自动重放。

### Tracer RED→GREEN

新增 127 浏览器 fixture：两个标签同时恢复只触发一次 refresh；两个调用均成功；POST/NDJSON
不被隐式重复；撤销按钮发送一次精确请求；sentinel 在 DOM、URL、storage、console 为 0。

### Verification

- 登录、退出、账号切换、公开首页、设置 clean layout、AI CEO 流式请求回归通过。
- 设备清单加载失败只显示安全提示，不退出当前有效会话。

## Phase 5：迁移、兼容和安全回归

### What to implement

1. 更新 SQLite 导出/导入表清单、Postgres migration 合同和 schema migration 记录。
2. production env example 增加 access/refresh TTL，guard 拒绝 production access TTL > 1800 或
   refresh TTL > 30 天。
3. 更新安全审计文档，将该 P1 标记为闭合并记录 legacy token 最长七天自然淘汰窗口。

### Verification

- session revocation、session cookie、global security、P0 guard、Postgres cutover、Origin/CSRF、
  Settings/UI focused 全绿。
- secret scan、Node/Python syntax、`git diff --check` 全绿。
- 完整 precloud 全绿，`ready_for_paid_commercial_launch` 仍为 false，writes/charge/secret false。

## Phase 6：冻结复核与部署

1. 冻结 HEAD/diff/file hashes，做独立安全复核和重复/重放攻击复签。
2. 只提交本功能文件，不触碰 `.superpowers/` 和本地 output。
3. push 后依次运行 Doctor、staging dry-run、apply、post-Doctor；SHA 必须一致。
4. 公网只读验证 health/deep/readiness、登录 cookie 属性和设备清单；不执行支付、eBay OAuth、
   同步或写操作。
5. 若刷新异常，停止公开验证并回滚代码；不放宽 cookie/Origin/撤销边界。
