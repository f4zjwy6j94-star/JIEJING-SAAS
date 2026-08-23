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
