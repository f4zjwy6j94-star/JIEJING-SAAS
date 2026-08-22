# 捷境公开收费上线交接（2026-08-22）

## 当前权威状态

- 正式域名：`https://app.jiejing.shop`；`pilot.jiejing.shop` 仅保留为回滚域名。
- `/health`：`environment=production`、`status=ok`。
- `/readiness/product-saas`：`production_ready=true`、`can_accept_real_customers=true`、`blocker_count=0`、`warning_count=0`。
- 已启用：微信 Native 主动扫码购买 30 天、人工确认退款执行、eBay 未发布草稿保存。
- 仍关闭：eBay 公开发布、广泛平台真实写入、自动续费、自动扣款。
- 正式切换没有创建付款订单，也没有触发客户扣款；只有商家在登录后主动创建订单并扫码才会产生付款。
- 正式域名已返回 CSP 与 `Strict-Transport-Security: max-age=31536000`。

## 安全合同

权威运行合同是 `2026-08-22-public-commercial-release-v1`。以下条件必须同时成立，否则真实结账自动关闭：

- 主理人付费上线批准包和生产发布批准包均已记录；
- 收费、受限写入范围、退款政策和商家页面文案均已复核；
- 生产候选启动例外已关闭；
- 微信收费与退款开关已打开；
- 广泛平台写入和 eBay 公开发布显式关闭。

`commercial_launch_gate` 与旧 `production_release_gate` 仍描述“全自动公开发布/上线前无收费审核”范围，不是本次“付费 SaaS + eBay 未发布草稿”上线范围的权威判断；不要因为它们的旧范围阻断而重复 OAuth、重复真实发布或重新执行退款证明。

## 生产证据

- 发布证明：`/opt/jiejing-production/releases/20260822-034237/private/jiejing-public-commercial-release-proof-20260822.json`
- 1 元退款证明：`/opt/jiejing-production/releases/20260822-034237/private/jiejing-one-cny-refund-proof-20260822.json`
- eBay 未发布草稿证明：`/opt/jiejing-production/releases/20260822-034237/private/jiejing-existing-ebay-unpublished-draft-live-verification-20260822.json`
- 部署镜像：`sha256:19d7c73c5d93a366c81cc843879a2a133f3a5ed265c3f9614c0bd52fea09408c`
- 源码发布提交：`914627e`
- 回滚镜像标签：`deploy-jiejing-saas:before-commercial-20260822T095219Z`
- 原子回滚备份：`/opt/jiejing-production/releases/20260822-034237/private/commercial-release-backup-20260822T095219Z`

所有证明均为后端私有文件，不得复制到前端、日志、普通商家接口或长期记忆中。Vault、eBay token 和微信支付密钥继续只留在后端密钥边界。

## 下一步

邀请少量真实商家，重点监控第一批订单创建、签名回调、查单补偿、权益发放、退款申请与 eBay 草稿保存成功率。任何异常先关闭对应单项开关；不要打开 eBay 公开发布或广泛平台写入。
