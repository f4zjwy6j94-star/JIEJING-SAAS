# 捷境运行环境重叠防护实施计划

## Phase 0：文档发现与允许使用的现有模式

### 已确认的实现来源

- 私有 env 解析入口：`tools/jiejing_configure_tencent_runtime_env.py:275-286`。
- symlink 拒绝、唯一备份名、同目录临时文件、`fsync`、原子 `os.replace` 和 0600：`tools/jiejing_configure_tencent_runtime_env.py:411-469`。
- 默认 dry-run 与 apply 分流：`tools/jiejing_configure_tencent_runtime_env.py:123-178`。
- GitHub deploy 最早无副作用接入点：`deploy/github-actions/jiejing-staging-deploy.sh:31-58`。
- patch apply 首次写入前接入点：`deploy/apply-staging-patch.sh:318-336`。
- Runner Doctor blocker/warning 模式：`deploy/github-actions/jiejing-runner-doctor.sh:20-26,47-76,131-145`。
- precloud 注册表：`tools/jiejing_precloud_deployment_gate.py:29-143`。
- 部署静态契约：
  - `tools/test_jiejing_staging_patch_apply_contract.py:24-346`
  - `tools/test_jiejing_github_actions_deploy_guardrails.py:29-208`
  - `tools/test_jiejing_github_runner_doctor_guardrails.py:20-91`

### 允许 API

- Python 标准库：`argparse`、`dataclasses`、`json`、`os`、`pathlib.Path`、`re`、`stat`、`tempfile`、`time`。
- `Path.read_text(encoding="utf-8")` 只用于内部解析；报告对象不得包含值字段。
- `os.open`、`os.fdopen`、`os.fsync`、`os.replace`、`Path.chmod` 用于安全原子写入。
- Bash 只通过 `sudo -n python3 <guard> ...` 调用检查器，不读取、不 `source`、不 `cat` 私有 env。

### 禁止模式

- 不复用现有 env parser 的重复键 last-wins 行为。
- 不使用现有 `_redact_value` 作为安全保证；新报告从结构上不含值。
- 不使用 `printenv`、`env |`、`set -x` 或 shell `source` 输出私有配置。
- 不在检查成功前创建 release、复制 patch、写 OAuth Secret、备份应用或操作容器。
- 不用宽泛 `JIEJING_*` 所有权规则吞掉未知键。
- 不读取或迁移唯一存在的模型、搜索、媒体、支付、会话秘密。

## Phase 1：建立检查器公开合同

### 目标

新增 `tools/jiejing_runtime_env_overlap_guard.py`，提供：

```text
check --compose PATH --managed-env PATH --secret-env PATH --postgres-env PATH [--json]
migrate --compose PATH --managed-env PATH --secret-env PATH --postgres-env PATH [--apply] [--confirm TEXT] [--json]
```

`migrate` 默认 dry-run；apply 需要固定确认短语。报告只含键名、来源、分类、计数、`equal|conflict` 和 `secret_exposed=false`。

### RED → GREEN 1

1. 新增 `tools/test_jiejing_runtime_env_overlap_guard.py`。
2. 先写合法三文件通过、同文件重复键失败、跨文件重复键失败、输出不含 sentinel value 的测试。
3. 运行测试确认失败。
4. 实现逐行 parser、键声明记录、关键所有权 registry 和 value-free report，做到最小通过。

### 所有权 registry

- `postgres-localqueue.env`：`JIEJING_DATABASE_*`、`JIEJING_POSTGRES_*`、`JIEJING_QUEUE_*`、`JIEJING_REDIS_*`。
- `tencent-managed.env`：`JIEJING_BACKUP_*`、`JIEJING_COS_*`、`JIEJING_CLS_*`、`JIEJING_RESTORE_*`、`JIEJING_TENCENT_*`、`JIEJING_PROVIDER_*`，以及明确登记的 Vault 托管证据。
- `jiejing-saas.staging-oauth.env`：明确的 eBay、微信支付、模型、搜索、媒体、会话和 Vault 后端秘密；历史文件名不改变其秘密边界。
- Compose：真实写入 false 钳位和公共测试环境写入策略等明确 exact keys。
- 未知唯一键：warning；未知重复键：blocker。

### 验证

- `python tools/test_jiejing_runtime_env_overlap_guard.py`
- 测试证明报告 JSON 中不存在任何测试值或 `value` 字段。

## Phase 2：实现 dry-run 迁移与安全 apply

### RED → GREEN 2

1. 增加以下逐项测试并每次只实现一个行为：
   - dry-run 不修改文件。
   - 所有权来源存在且值相等时生成 remove-from-wrong-source 计划。
   - 值冲突时拒绝，不显示值。
   - 正确来源缺失时拒绝，不自动搬运秘密。
   - apply 无确认短语时拒绝。
   - apply 拒绝 symlink。
   - apply 先备份、再原子替换，且权限不比原文件更宽。
   - 任一步失败时目标文件保持不变。
2. 复用 `jiejing_configure_tencent_runtime_env.py:411-469` 的备份/原子模式，但记录原 mode，并使用 `原 mode` 与 `0600` 中更严格的权限。
3. migration 内部可以比较值；对外报告只能是 `equal|conflict`。

### 验证

- 聚焦测试全通过。
- `git diff --check`。
- `python tools/jiejing_secret_scan.py`。

## Phase 3：整理公开模板与 Compose 合同

### RED → GREEN 3

1. 测试先要求新增 `deploy/jiejing-saas.postgres-localqueue.env.example`。
2. 模板仅包含数据库、队列、Stream、Consumer Group、dead-letter 和 driver probe 键，不含真实值。
3. 从 Tencent 模板移除数据库/队列、eBay、模型/搜索和写入钳位的越界示例。
4. 保留 OAuth 历史模板中的后端秘密类别，但移除数据库/队列、备份证据、静态域名和写入钳位。
5. `docker-compose.public-https-staging.yml` 与 fallback `docker-compose.public-staging.yml` 的 SaaS/Worker 都按 managed → secret → postgres 顺序加载三个文件。
6. Compose `environment` 只对明确 exact safety keys 形成已登记覆盖；其他现有静态项先作为 warning，不在本次大范围搬迁。

### 验证

- 聚焦 guard 测试读取三个公开模板并通过。
- `python tools/test_jiejing_frontend_staging_config.py`。
- `python tools/test_jiejing_staging_patch_apply_contract.py`。

## Phase 4：部署前 fail-closed 接入

### RED → GREEN 4

1. 先扩充静态守卫测试，要求：
   - GitHub deploy 在 release 目录创建/rsync/secret upsert 之前运行 guard。
   - patch apply 在 backup/copy/install/docker 之前运行候选 patch 中的 guard。
   - Runner Doctor 将 guard 缺失或失败加入 blocker，并始终输出 `SECRET_EXPOSED=false`。
2. 实现脚本接入：
   - GitHub deploy 使用 `$WORKSPACE` candidate tool/compose 与 `$DEPLOY_ROOT/private` live env。
   - patch apply 使用 `$PATCH_DIR` candidate tool/compose 与 `$APP_DIR/../private` live env。
   - Runner Doctor 使用 `$APP_DIR` 已部署 tool/compose，只输出安全摘要。
3. 将新工具、测试、模板、规格和计划加入 patch `FILES` 白名单与 Python 编译/测试清单。
4. 在 `tools/jiejing_precloud_deployment_gate.py` 注册聚焦测试。

### 验证

- `python tools/test_jiejing_github_actions_deploy_guardrails.py`
- `python tools/test_jiejing_github_runner_doctor_guardrails.py`
- `python tools/test_jiejing_staging_patch_apply_contract.py`
- `python tools/test_jiejing_local_first_cloud_fallback_guardrails.py`

## Phase 5：完整本地验证与主理人审视

### 验证命令

```text
python tools/test_jiejing_runtime_env_overlap_guard.py
python tools/jiejing_secret_scan.py
node --check app.js
python tools/jiejing_precloud_deployment_gate.py
```

### 主理人审视

- 产品方向：不增加通用 ERP/Agent 市场能力，不改变 AI CEO → 工作流 → 事实证据 → 确认中心链路。
- 商家体验：变更完全在内部部署层，商家前端不暴露环境文件、供应商或诊断数据。
- 安全：不读取输出 Secret；真实 eBay 写入、收费、退款和公开上线继续关闭。
- 可靠性：任何重叠或冲突在变更服务器之前失败；迁移可 dry-run、可备份、可回滚。
- 诚实进度：实现不会自动增加商业进度，目标是防止 82/100 因配置漂移倒退。

## Phase 6：服务器 dry-run 与后续 apply 边界

代码提交后只执行：

1. GitHub Actions Runner Doctor。
2. GitHub Actions staging deploy `dry_run`。
3. 在服务器私有文件上运行 key-only `check` 和 `migrate` dry-run，记录安全摘要；不显示值。

以下动作必须另行取得部署 apply 批准后才能执行：

- 私有 env migration `--apply`。
- staging deploy `apply`。
- SaaS/Worker 容器重建。

apply 后复验三条公开健康接口、固定进度不低于 82/100，并确认所有真实写入和公开收费字段仍为 false。
