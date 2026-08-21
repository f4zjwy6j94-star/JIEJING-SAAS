# 捷境 CLS 探针自动刷新实施计划

## Phase 0：文档发现与允许使用的现有模式

### 已确认的实现来源

- 已批准规格：`docs/superpowers/specs/2026-08-21-cls-probe-auto-refresh-design.md`。
- CLS 探针公开入口和失败分流：`tools/jiejing_configure_tencent_runtime_env.py:1382-1521`。
- 私有环境 0600 备份、同目录临时文件和原子替换：`tools/jiejing_configure_tencent_runtime_env.py:554-599`。
- Self-hosted workflow 的最小权限、并发和 checkout 模式：`.github/workflows/jiejing-staging-runner-doctor.yml:1-23`。
- 受信绝对路径、root ownership、symlink、候选 SHA、release manifest 和 runtime guard 模式：`deploy/github-actions/jiejing-runner-doctor.sh:10-259`。
- API/worker 分服务重建模式：`deploy/github-actions/jiejing-staging-rollback.sh:95-97`。
- GitHub runner 静态负面合同：`tools/test_jiejing_github_runner_doctor_guardrails.py:14-174`。
- precloud 注册表：`tools/jiejing_precloud_deployment_gate.py:29-192`。

### 允许 API

- GitHub Actions：`schedule`、`workflow_dispatch`、`permissions.contents: read`、`concurrency.cancel-in-progress: false`、`runs-on: [self-hosted, jiejing-staging]`、`actions/checkout@v6`。
- Bash：`set -euo pipefail`、`readlink -f`、`stat`、`cmp`、`git rev-parse`、`docker ps/inspect/run/compose`、`curl` 和固定次数健康轮询。
- Python 标准库仅用于解析已捕获的 JSON 安全字段；不读取或打印私有环境值。
- 现有 `jiejing_configure_tencent_runtime_env.py --verify-provider-cls-probe --apply` 是唯一允许写三项 CLS 证明的接口。
- 现有 root-controlled `jiejing_runtime_env_overlap_guard.py` 是唯一允许的环境重叠校验器。

### 禁止模式

- 不在宿主机安装 Tencent SDK；不调用宿主机探针入口。
- 不 `source`、`cat`、`printenv`、`env |`、`set -x` 或回显私有环境。
- 不接受 workflow path/command/resource-id 输入。
- 不使用候选 checkout 的 Compose 或 Python 工具操作生产私有环境；探针必须来自精确 live image。
- 不重启 Vault、frontend 或 Cloudflare，不执行 `docker compose down`。
- 不调用 eBay、微信支付、模型、搜索、媒体或其他业务 provider。
- 不提高 24 小时 freshness 阈值，不把失败 run 自动改成成功。

## Phase 1：建立 workflow 和入口合同

### RED → GREEN 1

1. 新增 `tools/test_jiejing_cls_probe_auto_refresh_guardrails.py`，首先要求以下文件存在：
   - `.github/workflows/jiejing-cls-probe-auto-refresh.yml`
   - `deploy/github-actions/jiejing-cls-probe-auto-refresh.sh`
2. 测试 workflow 必须精确包含：
   - `17 */12 * * *`
   - `workflow_dispatch`
   - `contents: read`
   - non-cancelling concurrency
   - self-hosted staging runner
   - 十分钟 timeout
   - full-history checkout
   - 唯一脚本入口
3. 测试拒绝 workflow inputs、write permissions、cloud-hosted runner、`pull_request_target`、secret env 和任何 eBay/payment/provider-business marker。
4. 运行测试取得文件缺失 RED。
5. 新增最小 workflow 和脚本骨架，使第一条合同 GREEN；脚本骨架在任何 Docker/探针操作前固定失败。

### 验证

- `python tools/test_jiejing_cls_probe_auto_refresh_guardrails.py`
- `git diff --check`

## Phase 2：受信 live-release 和私有文件边界

### RED → GREEN 2

逐条增加合同并最小实现：

1. 固定 `/opt/jiejing-staging`、live app、private env、release 和 Compose 路径；拒绝 symlink、路径逃逸和缺失文件。
2. 要求 private env 是 root-owned、0600 regular file。
3. 要求 `GITHUB_SHA`、checkout HEAD 和最新 applied manifest SHA 完全一致。
4. 要求 runtime Compose 与最新 applied release Compose 字节一致。
5. 通过 Compose label 精确找到唯一 `deploy/jiejing-saas` 容器；验证 config file、working directory、service、image 和 `/app`。
6. 调用 root-controlled runtime overlap guard；任何失败在 `docker run` 前结束。
7. 测试用顺序断言保证所有 guard marker 先于 probe marker。

### 验证

- 聚焦 guardrail 测试 GREEN。
- 现有 `python tools/test_jiejing_github_runner_doctor_guardrails.py` GREEN。
- 禁止 marker mutation 测试 GREEN。

## Phase 3：精确容器探针和失败不重启

### RED → GREEN 3

1. 测试要求临时容器使用运行 API 的 exact image、`--rm`、固定工作目录和 private directory mount。
2. 测试要求唯一命令为现有 `--verify-provider-cls-probe --apply`。
3. 捕获但不回显探针 JSON；只接受：
   - `status=verified`
   - upload/searchable/alarm exclusion/allowlist exact 全 true
   - notification/resource-id/secret exposure 全 false
   - evidence recorded true
4. blocked、exception、malformed、额外输出或字段不符时输出 value-free blocker 并在任何 Compose 重建前退出。
5. 测试拒绝宿主机 `python3 tools/jiejing_configure...`、SDK 安装、环境输出和 raw probe JSON 输出。

### 验证

- 聚焦测试覆盖成功、blocked、malformed 三条合同。
- `python tools/jiejing_secret_scan.py`。

## Phase 4：API → worker 顺序重载与公开健康门禁

### RED → GREEN 4

1. 成功探针后只允许：
   - `docker compose ... up -d --no-deps --force-recreate jiejing-saas`
   - API container health ready
   - localhost/public `/health` 和 `/health/deep` value-free 检查
   - `docker compose ... up -d --no-deps --force-recreate jiejing-worker`
   - worker heartbeat/deep health ready
   - CLS 探针独立证明监控就绪；公网 `/readiness/product-saas` 按脱敏合同不返回 info 级就绪项，因此必须不存在 `monitoring_alerting` warning/blocker
2. 检查 health/readiness 的 database、queue、worker、real/requested writes、public charging 和 secret 字段。
3. API recreate 或 health 失败时 worker 命令不得可达。
4. worker 或 final readiness 失败时 run 非零，不重放探针。
5. 脚本只打印固定 marker：guard/probe/API/worker/readiness/blockers/secret。

### 验证

- 静态调用顺序和失败短路 mutation 测试 GREEN。
- `bash -n deploy/github-actions/jiejing-cls-probe-auto-refresh.sh`（Git Bash/CI）。
- 现有 staging deploy、doctor 和 runtime-env overlap guard 测试 GREEN。

## Phase 5：precloud、runbook 和发布边界

### RED → GREEN 5

1. 将新 guardrail 测试注册到 `tools/jiejing_precloud_deployment_gate.py`。
2. 将 workflow、脚本、测试、规格和计划加入 staging patch/public release 白名单与合同。
3. 在 self-hosted runner runbook 增加：12 小时 cadence、value-free markers、失败语义、manual dispatch、禁止业务调用和取消方式。
4. 更新相关 release/patch guard 测试，确保新文件真正进入 bundle，不能仅在 Git 中存在。

### 验证

- 新 focused test。
- `python tools/test_jiejing_staging_patch_apply_contract.py`
- `python tools/test_jiejing_github_actions_deploy_guardrails.py`
- `python tools/test_jiejing_local_first_cloud_fallback_guardrails.py`
- `python tools/jiejing_secret_scan.py`
- `git diff --check`

## Phase 6：完整冻结、复签、部署和首次运行

1. 运行 complete precloud gate，要求全部 checks=pass，paid/writes/secret=false。
2. 冻结 HEAD、diff 和文件 SHA；做独立只读复签。
3. 精确提交和 push 批准文件。
4. 串行执行 exact SHA 的 pre-Doctor、dry-run、apply、post-Doctor。
5. 手工 dispatch 新 workflow 一次，验证：
   - trusted/live SHA guard ready
   - probe verified
   - API and worker ready
   - readiness monitoring item ready
   - blockers none inside this workflow
   - secret=false
6. 公网和认证复验 `/health`、`/health/deep`、`/monitoring/status`、`/readiness/product-saas`；确认总 readiness 只剩外部 Vault custody blocker 和支付 warning。
7. 保留计划任务，观察第一轮 cron Success 后才把“自动刷新已建立”写入无损交接。

## 完成判定

- 不再需要人工腾讯云 MFA 刷新 CLS 证明。
- 12 小时任务在 24 小时 fail-closed 门槛内留下成功 evidence。
- 失败绝不刷新时间、重启服务或触发业务调用。
- 成功只重载 API/worker，Vault/frontend/Cloudflare 不动。
- 实际 GitHub run、服务器健康和公开/认证 readiness 全部提供一致证据。
- 真实写入、收费、退款、eBay publish 和 secret 暴露仍为 false。
