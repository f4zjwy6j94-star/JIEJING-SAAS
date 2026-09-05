# 捷境正式生产部署手册（2026-08-23）

## 目标

本通道只面向捷境正式生产主机。它把“上传文件后临时手工操作”收口为：候选包校验、`dry_run`、原子切换、健康检查和失败自动回滚。

候选包只包含代码和公开资源，**不复制任何密钥**。生产环境变量、微信支付配置、eBay 凭据引用和 Vault token 继续留在服务器私有目录；日志和输出也不得打印这些值。

## 固定边界

- 默认动作是 `dry_run`，只验证候选发布，不切换线上服务。
- 正式应用必须输入完整确认语：`deploy app.jiejing.shop production`。
- 发布前 Git 工作区必须干净，候选包 SHA-256 必须与清单一致。
- 发布不会主动发起真实扣款、退款或 eBay 写入。
- 当前部署只重建 SaaS、Worker，并重建前端与边缘代理；不会删除数据库、Docker volume 或 Vault 数据。
- `dry_run` 不获取任何锁，不调用 `systemctl`，也不运行 COS/CLS 探针；它在创建 `/tmp/jiejing-production-dry-run-*.d` 之前安装清理 trap，完成 wrapper `bash -n`、固定 unit 合同和安装意图校验后自动删除；`HUP`、`INT`、`TERM` 和正常/异常退出均进入不可被二次可捕获信号打断的清理。成功必须精确输出 `CANDIDATE_RELEASE_PERSISTED=0`、`ACTIVE_SWITCHED=0` 以及不含值的 private env 权限规范化布尔，不会在 production release root 留下目录。
- 正式 apply 先持有 deploy-only `/run/lock/jiejing-production-deploy.lock`，再持有与证据刷新共享的 `/run/lock/jiejing-production-maintenance.lock`，避免两个部署互相穿插或刷新任务撞上容器切换。
- 正式 apply 必须先取得上述双锁，才允许读取 active release、容器环境文件标签和 private-dir 等 live snapshot，更不能提前在 production release root 创建永久候选目录。

## 标准顺序

```powershell
python tools/jiejing_secret_scan.py
python tools/test_jiejing_production_deploy_channel.py
python tools/jiejing_prepare_public_staging_bundle.py

python tools/jiejing_production_deploy.py `
  --bundle output/jiejing-public-staging-bundle/<bundle>.zip `
  --manifest output/jiejing-public-staging-bundle/<bundle>.manifest.json `
  --mode dry_run
```

只有 dry-run、CI 和生产前验证全部通过后，才允许执行：

```powershell
python tools/jiejing_production_deploy.py `
  --bundle output/jiejing-public-staging-bundle/<bundle>.zip `
  --manifest output/jiejing-public-staging-bundle/<bundle>.manifest.json `
  --mode apply `
  --confirm "deploy app.jiejing.shop production"
```

## 验收标准

部署脚本必须验证：

- `/health` 为 `status=ok`；
- `/health/deep` 为 `status=ready`；
- `/readiness/product-saas` 不暴露密钥；
- 正式收口时进一步要求 `production_ready=true`、`can_accept_real_customers=true`、`warning_count=0`；
- 失败自动回滚到上一个发布目录；
- 当前符号链接、容器 Compose 标签和发布清单指向同一版本。

真实扣款、退款或 eBay 写入不属于部署验收。即使部署通过，这些动作仍必须进入确认中心并在动作前获得单独确认。

## 独立运营后台不是本通道的自动发布目标

`ops.jiejing.shop` 当前由旧运营主机提供；本通道更新 `app.jiejing.shop` 的生产发布目录，不会自动更新旧主机的静态文件、API或代理规则。主站成功不能直接表述为“全站前后端已同步”。

当修改 `ops.html`、`ops.js`、`ops.css`、`assets/jiejing-ops-panels.js`、运营代理规则或运营专用API时，整体功能验收还必须核对：

- 实际运营页面引用的版本和返回资产哈希与候选一致；不能只检查HTTP 200或页面标题。
- 运营端实际反代的API包含本次处理器；静态文件更新不能替代后端更新。
- 所需路径和HTTP方法在ops域精确开放，未登录/非运营身份仍被拒绝，商家域内部路径仍404。
- 退款provider能力布尔与“运营界面能完整申请/审核/执行/查询”分开记录；禁止为验证部署而实际退款。

独立运营端按既有GitHub手动发布规范处理；不要发现版本不一致后盲目运行旧SSH staging全量覆盖脚本。若需使用规范外的专门SSH发布，先获得明确例外授权并准备前后端同版校验和可恢复方案。只读确认是同一数据库时，不因连接地址文字不同就迁移数据库或修改DNS。

## 证据刷新 unit 独立事务

应用健康并切换 active link 后，部署才原子安装证据刷新 wrapper（`0755 root:root`）和两个 unit（`0644 root:root`）。安装过程执行 `systemd-analyze verify`、`daemon-reload` 和 timer enable，但不会在维护锁释放前启动探针。

维护锁释放后，部署手工启动一次 oneshot，并以本次 `InvocationID` 对应 journal 中的 `JIEJING_PRODUCTION_EVIDENCE_REFRESH_STATUS=success`、service `Result=success`、`ExecMainStatus=0` 为真实成功条件。随后才启动 timer，并确认 enabled、active 且 `NextElapseUSecRealtime` 有值。

oneshot 会分别捕获当前 SaaS API 与 Worker 的实际 image ID；两个 ID 可以不同，但必须各自为可检查的 `sha256`，且各自的 image reference、Compose project/service/config/workdir/environment-file label 和运行状态都与 active release 精确一致。COS、CLS 和探针工具存在性检查明确只运行在已验证的 API 镜像中；后续强制重建 API 只能恢复原 API ID，重建 Worker 只能恢复原 Worker ID，任一缺失、漂移或交叉交换都会 fail-closed。

安装后必须确认 service 与 timer 的实际属性都严格返回单行 `DropInPaths=`；缺少该属性或返回任何路径都会 fail-closed，拒绝来自 `/etc`、`/run` 或 `/usr/lib` 的旧 drop-in 覆盖固定 `ExecStart` 与沙箱合同。生产 apply 的 SSH 客户端超时预算固定为 `3600` 秒，以覆盖最长 20 分钟 oneshot、应用健康等待与镜像构建余量。

apply 会在构建前从当前 release manifest 唯一解析 `PRIVATE_DIR`，与运行容器的 environment-file label 交叉验证，并只通过 `O_NOFOLLOW` 文件描述符把该目录规范为 `root:root 0700`、两个 env 文件规范为 `root:root 0600`；不会读取或输出文件内容。SaaS 与 Worker 会分别保存构建后实际 image ID；两个 ID 可以不同，但候选启动和最终收口都必须逐服务匹配各自已保存的 ID、Compose labels、workdir、environment-file 和健康状态。

构建前，当前 SaaS 与 Worker image ID 会分别固定到 root 控制的 `jiejing-production-rollback-api:previous` 和 `jiejing-production-rollback-worker:previous`；固定、回读或半创建恢复失败都会在 build、容器、active link 和 unit 变更前停止。这两个 hold refs 至少保留到完整成功或完整回滚，并作为最近一版人工回滚证据；部署路径禁止 image prune。若 wrapper/unit 安装、首次 oneshot 或 timer 验收失败，部署会从 hold refs 恢复 live image refs，同时恢复三个 root 文件、原 timer 状态和旧 active release。失败输出包含 `TIMER_INSTALL_ROLLED_BACK=1`、`APPLICATION_RELEASE_RETAINED=0` 和 `JIEJING_PRODUCTION_ROLLBACK_APPLIED=1`；只有完整验证旧双 image ID、容器 labels 与健康状态后才允许报告回滚成功。

unit 事务期间的 `HUP`、`INT`、`TERM` 和异常 `EXIT` 会进入同一独立回滚；回滚时忽略二次可捕获信号，避免递归。`SIGKILL` 和整机断电无法被 shell 捕获，因此部署后仍必须按本节 markers、root 文件和 timer 状态完成验收。
