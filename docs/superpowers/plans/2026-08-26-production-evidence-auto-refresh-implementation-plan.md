# 捷境生产证据自动刷新与商家闭环一致性实施计划

## Phase 0：文档发现与允许使用的现有模式

### 已确认来源

- 已批准规格：`docs/superpowers/specs/2026-08-26-production-evidence-auto-refresh-design.md`。
- 生产 active release、private directory、Compose 和原子回滚：`deploy/jiejing-production-release-apply.sh:55-76,128-160,225-276`。
- 生产客户端 bundle 验证：`tools/jiejing_production_deploy.py:30-185`。
- Bundle 单一文件来源：`tools/jiejing_prepare_public_staging_bundle.py:94-122` 和 `deploy/apply-staging-patch.sh` 的 `FILES`。
- 预发布探针的路径、容器、精确镜像和失败短路模式：`deploy/github-actions/jiejing-cls-probe-auto-refresh.sh:22-265`。
- CLS 验证并原子写回：`tools/jiejing_configure_tencent_runtime_env.py:1382-1516`。
- 私有环境 0600 备份与 `os.replace`：`tools/jiejing_configure_tencent_runtime_env.py:554-605`。
- COS 上传、读回哈希和删除合同：`jiejing_saas/cos_backup_probe.py:18-141`。
- COS/CLS freshness：`jiejing_saas/backup_plan.py:277-319`、`jiejing_saas/monitoring.py:635-713`。
- 生产部署静态合同：`tools/test_jiejing_production_deploy_channel.py:40-160`。
- 自动刷新负面合同模板：`tools/test_jiejing_cls_probe_auto_refresh_guardrails.py:98-321`。
- 商家闭环 P0 证据：`app.js:6876-6913,22359-22384,12677-12902`。
- 商品事实项目隔离证据：`app.js:6918-6951,17353-17543,32718-32723`、`jiejing_saas/api_server.py:8980-9033`、`jiejing_saas/repository.py:5320-5420`。

### 允许 API 和命令

- Bash：`set -euo pipefail`、`readlink -f`、`stat`、`flock`、`cmp`、`install`、`docker ps/inspect/run/compose`、`curl`、固定次数健康轮询。
- systemd：`systemd-analyze verify`、`systemctl daemon-reload`、`enable`、`start`、`is-enabled`、`is-active`、`show`；只允许固定 unit 名。
- COS：现有 `execute_cos_backup_probe(env=...)`，成功必须包含上传、读回 SHA-256 一致和对象删除。
- CLS：现有 `--verify-provider-cls-probe --apply`，只接受完整 verified 字段合同。
- 私有环境写回：只复用 `_write_env_file()`；不得自行拼接或覆写整个 Secret 文件。
- Python 标准库只解析捕获的 JSON 和计算非证据字段摘要，不输出原始环境值。

### 禁止模式

- 不 `source`、`cat`、`printenv`、`env`、`set -x` 私有环境。
- 不在宿主机安装腾讯 SDK；探针只能使用精确 live SaaS 镜像。
- 不直接使用 `--record-cos-probe-now` 冒充已验证探针。
- 不调用 eBay、微信支付、退款、模型、搜索或素材 provider。
- 不重启 Vault、Frontend、Edge 或数据库，不执行 `docker compose down`。
- 不提高 freshness 阈值，不把 HTTP 200 当作收费或发布就绪。
- 不把 systemd unit 回滚混入应用版本回滚。

## Phase 1：COS“验证成功才记账”原子入口

### RED

1. 扩展 `tools/test_jiejing_configure_tencent_runtime_env.py`，要求新 CLI `--verify-cos-backup-probe --apply`。
2. 用 fake COS client 覆盖成功、哈希错误、删除失败和 provider 异常。
3. 断言失败不修改 env；成功只更新 `JIEJING_COS_BACKUP_LAST_SUCCESS_AT`，文件仍为 root/operator 预期权限且输出无 bucket、object key、凭据。

### GREEN

1. 在 `tools/jiejing_configure_tencent_runtime_env.py` 增加唯一 COS provider-control mode。
2. 调用 `execute_cos_backup_probe(env=existing)` 并严格验证完整结果。
3. 只取探针返回的已验证 `success_at`，通过 `_write_env_file()` 原子写回单一时间字段。
4. 返回 value-free JSON：verified/blocked、evidence recorded、Secret false；不返回资源标识。

### 验证与反模式检查

- `python tools/test_jiejing_configure_tencent_runtime_env.py`
- `python tools/test_jiejing_cos_backup_probe.py`
- 搜索新入口，确认没有独立调用 `--record-cos-probe-now`。

## Phase 2：生产 wrapper 与 systemd 合同

### RED

新增 `tools/test_jiejing_production_evidence_auto_refresh_guardrails.py`，先要求以下文件存在：

- `deploy/jiejing-production-evidence-auto-refresh.sh`
- `deploy/systemd/jiejing-production-evidence-refresh.service`
- `deploy/systemd/jiejing-production-evidence-refresh.timer`

测试必须覆盖：

- `OnCalendar=*-*-* 00,12:17:00`、`Persistent=true`、随机延迟、固定 unit；
- root/0600 私有文件、active release symlink、唯一 SaaS 容器、Compose labels 和精确镜像 guard；
- 非阻塞 `flock`；
- COS 原子入口与 CLS verified 入口；
- 任一 probe 失败均在容器重载前退出；
- API 健康后才允许 Worker 重载；
- 最终 readiness 不含 backup blocker/monitoring warning，且收费、广义写入、Secret 仍为 false；
- 禁止业务 provider、环境输出、动态命令输入、危险 Docker/文件操作。

### GREEN

1. 从生产 active link 解析物理 release；允许 link 本身存在，但解析结果必须位于 releases 根。
2. 从唯一 SaaS 容器的 `production-compose.env` label 解析 private directory，再固定找到 app env。
3. 验证 root:root、0600、普通文件、非 symlink；探针前后比较“排除三个允许证据字段后的环境摘要”，拒绝其他字段漂移。
4. 在 exact live image 内串行执行 COS、CLS，捕获但不回显原始 JSON。
5. 串行重载 SaaS→健康→Worker→深度健康；最终验证公开 readiness。
6. 日志只输出固定状态、blocker 分类和 `SECRET_EXPOSED=false`。

### 验证

- 新专项 guardrail 测试。
- `bash -n deploy/jiejing-production-evidence-auto-refresh.sh`。
- `systemd-analyze verify` 两个 unit。
- 现有 CLS/COS 测试保持通过。

## Phase 3：生产发布通道的独立 unit 事务

### RED

扩展：

- `tools/test_jiejing_production_deploy_channel.py`
- `tools/jiejing_production_deploy.py::validate_zip()`
- `deploy/apply-staging-patch.sh` 白名单与对应 whitelist 测试
- `tools/jiejing_precloud_deployment_gate.py`
- `.github/workflows/jiejing-ci.yml`
- `docs/JIEJING_PRODUCTION_DEPLOY_RUNBOOK_20260823.md`

要求候选包缺少 wrapper/units/test/规格/计划时本地失败。dry-run 只做 `bash -n`、unit 合同和安装意图验证，不调用 systemctl、不运行探针。

### GREEN

1. 应用版本已健康并切 active link 后，再进入独立 systemd transaction。
2. 备份当前 root wrapper 和 units，支持“首次安装时旧文件不存在”。
3. 原子安装 root wrapper 和 units，daemon-reload，enable timer，手工 start oneshot。
4. 验证 service 成功、timer enabled/active、NextElapse 存在。
5. unit transaction 失败时只恢复/移除 units 与 wrapper，输出：
   - `TIMER_INSTALL_ROLLED_BACK=1`
   - `APPLICATION_RELEASE_RETAINED=1`
6. 不触发应用容器或 active link 回滚；应用版本保持在线。

### 验证

- 生产部署 channel test。
- staging patch whitelist contract。
- Bundle dry-run 中出现所有新文件。
- 模拟首次安装和升级恢复路径的静态/fixture 测试。

## Phase 4：商家闭环 P0 一致性修复

### RED → GREEN A：真实香炉不再被旧样例过滤

1. 在现有前端 Node/静态测试中复现 `禅意佛手托莲花倒流香炉` 被降级为“当前商品”。
2. 删除通用品类词旧样例判断，只允许精确历史 draft/source/report/SKU 标识命中旧样例。
3. 断言真实商品名原样进入素材商品事实和生成上下文，精确旧手机壳等历史标识仍被拦截。

### RED → GREEN B：执行回执必须绑定当前确认单

1. 构造 old/new 两个 confirmation，只有 old 有 blocked/success execution。
2. 指定 new confirmation 查询时必须返回 `null`，不得 fallback 到 latest。
3. 当前 Listing 不得因旧回执跳到“查看发布回执”。

### 验证

- 扩展 `tools/test_jiejing_saas_clean_settings_and_listing_ui.py` 或新增小型 Node 合同测试。
- `node --check app.js`。
- 活动/执行记录 UI 与受控 publish 专项测试。

## Phase 5：商品事实项目隔离 P1

### RED

扩展 `tools/test_jiejing_ai_ceo_routing_supplier_http_red.py`：

- 两个同名商品、不同 `listing_project_identity.key` 不得互串 SKU、规格或图片；
- 后端最新事实已经解决的 unknown field 不得被旧前端集合复活；
- 旧记录无结构 identity 时仅允许保守 fallback。

### GREEN

1. 前端保存事实包时附带 `listing_project_identity.key/source_report_id/candidate_id`。
2. API 和 repository 规范化并持久化该结构，不接受跨公司/空 key 冒充精确匹配。
3. 恢复时先按精确 key，旧记录才走来源 URL/货号/商品名 fallback。
4. 精确项目记录的 `unknown_facts` 以服务器最新事实为准，不与旧前端未知项盲目取并集。

### 验证

- 商品事实 HTTP/frontend 测试。
- 同名项目隔离回归。
- AI CEO→Listing 事实边界和素材来源测试。

## Phase 6：完整门禁、部署与生产验收

1. 运行所有专项测试、`node --check app.js`、Python compile、Secret 扫描和 `git diff --check`。
2. 运行完整 precloud gate，要求全部 checks pass，收费/广义写入/Secret false。
3. 提交干净 HEAD，构建精确 bundle。
4. 生产 deploy dry-run；确认不安装 unit、不运行探针。
5. apply 后首次 oneshot 必须真实刷新合成 COS/CLS 证据。
6. 验证：
   - release/manifest/container labels 一致；
   - service 最近结果 success；
   - timer enabled/active 且 NextElapse 存在；
   - `/health`、`/health/deep` ready；
   - readiness 为 0 blocker，monitoring warning 不存在；
   - 支付 warning 可以保留；
   - eBay 无新执行、无 OAuth、无支付/退款调用；
   - 用户域 `/ops.html` 仍 404，ops 独立域仍 200。

## 完成判定

- COS/CLS 证据不再依赖人工刷新，关机错过周期后会补跑。
- 探针验证与证据记账不可分离，失败不会写成功时间。
- 第二/第三次真实商品演练不会因“香炉”品类词被当旧样例，也不会显示其他确认单的回执。
- 同名商品项目不串事实，已解决缺口不复活。
- 正式发布仍在 eBay 审核解除和新的动作时确认之前保持暂停。
