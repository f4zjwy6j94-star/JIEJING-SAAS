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
- `dry_run` 不获取任何锁，不调用 `systemctl`，也不运行 COS/CLS 探针；它在创建 `/tmp/jiejing-production-dry-run-*.d` 之前安装清理 trap，完成 wrapper `bash -n`、固定 unit 合同和安装意图校验后自动删除；`HUP`、`INT`、`TERM` 和正常/异常退出均进入不可被二次可捕获信号打断的清理。成功输出 `CANDIDATE_RELEASE_PERSISTED=0`，不会在 production release root 留下目录。
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

## 证据刷新 unit 独立事务

应用健康并切换 active link 后，部署才原子安装证据刷新 wrapper（`0755 root:root`）和两个 unit（`0644 root:root`）。安装过程执行 `systemd-analyze verify`、`daemon-reload` 和 timer enable，但不会在维护锁释放前启动探针。

维护锁释放后，部署手工启动一次 oneshot，并以本次 `InvocationID` 对应 journal 中的 `JIEJING_PRODUCTION_EVIDENCE_REFRESH_STATUS=success`、service `Result=success`、`ExecMainStatus=0` 为真实成功条件。随后才启动 timer，并确认 enabled、active 且 `NextElapseUSecRealtime` 有值。

安装后必须确认 service 与 timer 的实际属性都严格返回单行 `DropInPaths=`；缺少该属性或返回任何路径都会 fail-closed，拒绝来自 `/etc`、`/run` 或 `/usr/lib` 的旧 drop-in 覆盖固定 `ExecStart` 与沙箱合同。生产 apply 的 SSH 客户端超时预算固定为 `3600` 秒，以覆盖最长 20 分钟 oneshot、应用健康等待与镜像构建余量。

若 wrapper/unit 安装、首次 oneshot 或 timer 验收失败，只回滚这三个 root 文件以及部署前的 timer enabled/active 状态，不回滚已经健康的应用版本。失败输出必须同时包含 `TIMER_INSTALL_ROLLED_BACK=1` 和 `APPLICATION_RELEASE_RETAINED=1`，便于运营明确区分“应用在线”与“定时证据刷新未安装成功”。

unit 事务期间的 `HUP`、`INT`、`TERM` 和异常 `EXIT` 会进入同一独立回滚；回滚时忽略二次可捕获信号，避免递归。`SIGKILL` 和整机断电无法被 shell 捕获，因此部署后仍必须按本节 markers、root 文件和 timer 状态完成验收。
