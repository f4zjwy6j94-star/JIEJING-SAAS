# Jiejing Global Audit - 2026-06-17

本文件记录 2026-06-17 对捷境 SaaS 的本地代码、公开 staging、腾讯云部署通道和上线硬缺口复检。所有密钥、token、refresh token、模型 key、密码均未写入本文件。

## 结论摘要

- 公开 staging 可访问，`/health` 正常，`secret_exposed=false`。
- `/readiness/product-saas` 当前显示 `beta_ready=true`、`production_ready=false`、`can_accept_real_customers=false`。
- 当前不是正式收费公开上线状态。主要差口是正式 paid billing provider、eBay token refresh 的真实 Vault-backed 续期证明、新 eBay 账号的完整真实链路、稳定域名/OAuth callback、商业 smoke。
- 本地 py_compile、`node --check app.js`、关键 Python 回归、全模块 browser smoke 均通过。
- 腾讯云 43.129.205.244 的 SSH 备用端口 2222 可用；public staging 可达；容器运行中。
- TencentDB PostgreSQL 实际端口为 24998，宿主机、SaaS 容器、worker 容器到该端口 TCP 均可达。
- worker 历史重启次数过高，曾因 Postgres DNS 解析失败反复退出；现在进程存活，但必须接入告警和重启原因可见化。
- 本地项目目录不是 Git repo，正式协作/CI/回滚前这是工程化硬风险。
- 前端仍会把 SaaS token 写入 `localStorage`，上线前应改成 HttpOnly cookie + session/in-memory 回退。
- `app.js`、`styles.css`、`api_server.py`、`repository.py` 等文件过大，维护和回归风险明显。
- 代码中存在乱码中文字符串残留，会影响商家可见体验和信任感，需要系统清理。

## 公开 staging 状态

检查时间：2026-06-17 20:20-20:35 Asia/Shanghai。

- URL: `https://individually-buffalo-prescribed-blocking.trycloudflare.com`
- `/health`
  - `status=ok`
  - `environment=staging`
  - `database_startup_status=ready`
  - `real_platform_writes_enabled=true`
  - `requested_real_platform_writes=true`
  - `secret_exposed=false`
- `/readiness/product-saas`
  - `beta_ready=true`
  - `production_ready=false`
  - `can_accept_real_customers=false`
  - `blocker_count=0`
  - `warning_count=2`
  - latest packet: `packet_f5cbba8068e6542d`
  - packet source: `official_api`
  - packet resources: `6/6`
  - `model_secret_refs=1`
  - `ebay_secret_refs=0`
  - billing provider: `manual_seed`
  - model value: `ready`
  - public search provider credential: not configured; built-in public fallback enabled

当前 warning：

1. `billing_quota`: private beta quota ready, but external paid subscription provider required before charging merchants.
2. `ebay_token_refresh`: refresh blocked until real Vault-backed eBay refresh proof is completed.

## 腾讯云部署体检

服务器：

- Host: `43.129.205.244`
- User: `ubuntu`
- SSH port: `2222`
- App path: `/opt/jiejing-staging/app`

部署通道：

- `tools/jiejing_deploy_channel_doctor.py` 结果：`deploy_channel_ready=true`
- public staging reachable: true
- SSH status: usable
- 备注：doctor 里 plain `docker` 因 ubuntu 非 docker group 显示 permission denied；`sudo docker` 可用。

系统资源：

- uptime: 29 days
- disk `/`: 40G total, 30G used, 8.1G available, 79%
- memory: 1.9Gi total, about 1.1Gi available
- Docker images: 5.112GB, reclaimable 3.956GB
- Build cache: 3.82GB, reclaimable 3.776GB
- staging patch backups: 467M

容器：

- `deploy-jiejing-frontend-1`: up 4 days
- `deploy-jiejing-saas-1`: up 4 days, restart count 0
- `deploy-jiejing-worker-1`: up about 1 hour, restart count 4151
- `deploy-jiejing-vault-1`: up 2 weeks
- `jiejing-cloudflared-hk`: up 4 weeks

Postgres 连接：

- 当前 DB URL host: `hk-postgres-p2r6dxhh.sql.tencentcdb.com`
- 当前 DB URL port: `24998`
- 宿主机到 `host:24998`: OK
- SaaS container 到 `host:24998`: OK
- worker container 到 `host:24998`: OK

重要发现：

- worker 日志中存在大量历史错误：Postgres host 解析失败导致 worker 退出并重启。
- 当前连接已恢复，但 4151 次重启说明欠费/网络/DNS 问题曾造成后台任务不稳定。
- 必须把 worker restart count、DB DNS/TCP probe、dead-letter、stale jobs 接入告警和 readiness。

## 本地验证

通过：

- `python -m py_compile jiejing_saas\ai_ceo_chat.py jiejing_saas\api_server.py jiejing_saas\readiness.py jiejing_saas\billing_webhook.py jiejing_saas\ebay_write_adapter.py jiejing_saas\ebay_token_refresh_adapter.py jiejing_saas\worker.py jiejing_saas\postgres_repository_runtime.py jiejing_runtime\execution_preflight.py`
- `node --check app.js`
- `python tools\test_jiejing_account_health_incident_mode.py`
- `python tools\test_jiejing_account_health_preflight.py`
- `python tools\test_jiejing_postgres_durable_queue_adapter.py`
- `python tools\test_jiejing_queue_recovery_heartbeat.py`
- `python tools\test_jiejing_billing_provider_webhook.py`
- `python tools\test_jiejing_billing_webhook_subscription_state.py`
- `python tools\test_jiejing_billing_quota_guardrail.py`
- `python tools\test_jiejing_ebay_vault_token_refresh_adapter.py`
- `node tools\codex_jiejing_all_modules_clean_smoke.js`

Browser smoke 结果：

- `ok=true`
- 首页未自动弹登录。
- AI CEO、Listing、批量铺货、素材工坊、决策中心、客服与订单、设置均可见。
- 设置 7 个 tab 存在。
- 决策中心明确真实写入已开但必须先确认。
- Listing 当前显示等待 eBay 授权/未读取到商品，原因是当前 public DB `ebay_secret_refs=0`，且旧 eBay 账号已冻结；不能用旧数据冒充。

## 安全与漏洞风险

### P0/P1

1. 前端 token 存储风险
   - 位置：`app.js:10822-10868`、`index.html:5371-5378`
   - 现状：登录 token 会写入 `sessionStorage`，并且 `app.js` 还会写入/读取 `localStorage`。
   - 风险：XSS 一旦发生，localStorage token 可被读取；正式 SaaS 不应把会话 token 长期放在 localStorage。
   - 建议：以后端 `HttpOnly; SameSite=Lax; Secure` cookie 为主；前端只保存非敏感 session hint/store id；移除 localStorage token。

2. worker 真实稳定性不足
   - 位置：腾讯云容器 `deploy-jiejing-worker-1`
   - 现状：restart count 4151，历史日志显示 Postgres DNS 解析失败。
   - 风险：后台任务、发布后复盘、队列恢复、素材任务可能中断。
   - 建议：worker restart 告警、DB TCP probe、DNS probe、dead-letter alert、stale job alert、restart reason dashboard。

3. 当前 eBay 账号冻结，新账号未完成真实链路
   - 现状：旧账号不可用于真实发布测试；public readiness 中 `ebay_secret_refs=0`。
   - 风险：不能证明新商家从授权、同步、体检、确认、发布、审计回流完整可用。
   - 建议：新账号只做低量真实测试，先跑只读同步和账号健康，再跑发布体检和确认中心，最后发布/清理。

4. 正式收费系统未上线
   - 现状：billing provider 为 `manual_seed`。
   - 风险：不能公开收费；无法处理订阅、webhook、欠费停用、发票、用量账单。
   - 建议：先接 Stripe 或 Lemon Squeezy，真实 plan ID、signed webhook、quota hard stop、账单 UI。

5. 本地/远端都不是 Git repo
   - 现状：`git rev-parse --show-toplevel` 返回 `NO_GIT_REPO`。
   - 风险：无法可靠 code review、CI、回滚、分支管理和安全扫描。
   - 建议：先做 secret scan 和清理，再初始化 private GitHub，接 GitHub Actions。

### P2

6. 代码文件过大
   - `app.js` 约 1.3MB，超过 26k 行。
   - `styles.css` 超过 26k 行。
   - `api_server.py`、`repository.py` 过大。
   - 风险：修改任何 UI/路由都容易引入回归，测试定位困难。
   - 建议：按模块拆分：AI CEO、settings、listing、media、confirmation、service、billing、queue。

7. 中文乱码残留
   - 位置：`app.js`、`index.html`、`account_health.py` 等处存在 mojibake 字符串。
   - 风险：商家界面或错误 toast 暴露乱码，降低产品可信度。
   - 建议：统一 UTF-8 检查脚本，禁止乱码进入 CI。

8. CSP 仍依赖 `unsafe-inline`
   - 位置：`deploy/nginx.public-staging.conf`
   - 现状：`script-src 'self' 'unsafe-inline'`。
   - 风险：XSS 防御深度不足。
   - 建议：短期保留 staging 可用性；上线前逐步把 inline script 移入外部 JS，添加 nonce/hash 或 Trusted Types。

9. readiness 实时 DB 探针需要加强
   - 现状：`/health` 只反映启动时 repository 初始化状态。
   - 风险：数据库后续中断时，health 可能继续显示 ready。
   - 建议：增加 `/health/deep` 或 readiness item：current Postgres DNS/TCP/select 1、worker heartbeat、queue stale/dead-letter。

## 产品进度估算

- 私测可用度：85%
- 当前 beta 能力：78%
- 正式收费公开上线：65%
- 工程化/CI/回滚能力：50%
- 运维稳定性：70%
- 安全边界：72%
- eBay 真实闭环：旧账号冻结后暂时 60%，新账号接入后需重跑到 85%+
- 商业化收费：45%

这些百分比不是宣传口径，是按“能否真实接商家、收费、出问题可恢复”的上线标准估算。

## 下一步建议顺序

1. 修 session token 存储：移除 localStorage token，前端只保留 session hint；以后端 HttpOnly cookie 为主。
2. 补 worker/DB 深度健康：DB DNS/TCP/select 1、worker heartbeat、restart count、stale jobs、dead letters 进入 readiness 和设置页。
3. 接正式 billing provider：Stripe 或 Lemon Squeezy 选一个先跑通真实 plan、webhook、quota、欠费停用。
4. 初始化 private GitHub + CI：先 secret scan，再接 py_compile、node check、Python 回归、browser smoke。
5. 清理乱码和大文件拆分：先拆 `app.js` 的设置、AI CEO、Listing、素材、决策中心模块。
6. 新 eBay 账号低风险重跑：只读同步 -> account health -> publish health -> confirmation -> real publish -> post-publish cockpit -> cleanup plan。
7. 稳定域名/OAuth callback：替换 trycloudflare，固化 DNS/TLS/CORS/eBay callback。
