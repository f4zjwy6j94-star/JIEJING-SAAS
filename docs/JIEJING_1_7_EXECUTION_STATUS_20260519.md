# 捷境 1-7 执行状态 - 2026-05-19

本记录只覆盖本轮 1-7 任务。未重复 eBay OAuth，未重新跑官方同步，未开启真实平台写入。

## 1. CVM 与 staging 清理

- 当前 staging 入口仍是 Lighthouse `42.194.158.47`，SSH 通道 `agentuser` 可用。
- 已清理 Lighthouse Docker build cache：build cache 从 `17.25GB` 降到 `0B`，根分区从 `76%` 使用率降到 `40%`。
- 未删除 Docker volumes。`deploy_jiejing_public_staging_data`、Vault/Caddy volumes 均保留。
- CVM `ins-01hsr6ti / 159.75.102.10`：22 端口开放，80/443 未开放；当前已知 staging key 对 `agentuser/root/ubuntu` 均被拒绝。下一步仍应在腾讯云控制台先快照，再检查目录、容器、端口、定时任务，确认无依赖后停机观察。

## 2. 模型密钥边界

- `DeepSeekModelClient` 默认不再读取 `JIEJING_HERMES_AUTH_JSON`、`/home/hermes/.hermes/auth.json` 或 WSL Hermes auth。
- 只有显式设置 `JIEJING_ALLOW_HERMES_MODEL_FALLBACK=true` 时，旧 Hermes 模型凭证路径才可用于本地 legacy 回归。
- staging/production env 模板和 public staging compose 明确设置 `JIEJING_ALLOW_HERMES_MODEL_FALLBACK=false`。

## 3-4. Market Report / Listing Package live proof

- 已在 staging 容器内对官方数据包 `packet_5c69bcc5bf0e79ae` 发起受控 model value rehearsal。
- 结果为 `blocked_before_model_rehearsal`，阻断项：`model_provider_not_configured`。
- 因 staging 未配置模型 provider key，本轮没有伪造 live Market Report 或 live Listing Package 证据。
- 安全边界保持：Runtime 只拿 sanitized packet，不拿 eBay token；前端不拿模型 key；真实写入仍关闭。

## 5. 工作台证据面板

- 工作台新增真实证据面板，展示 `source_mode`、`packet_id`、六类 eBay 资源、Market Report / Listing Package 模型证明状态、真实写入关闭、备份恢复与 paid launch gate 状态。
- 登录态刷新会读取 `/backup/plan`、`/model/value-gate`、`/commercial/launch-gate`，把阻断原因展示给商家/运营，而不是只展示样例页面。

## 6. Demo/mock 隔离

- 公共 HTML 的 `内测试用`、`workflow-demo-grid`、`mockPreview`、`bulk-demo-note`、`media*Demo` DOM 标记已移除或重命名。
- 公网页面仍保留内部教程/受控草稿能力，但真实 SaaS 商家模式不会把它当成真实数据。
- 前端 bearer token 从 `localStorage` 改为 `sessionStorage`，并清理旧 localStorage token。

## 7. Beta hardening

- `/auth/demo-session` 在 `staging/production` 默认关闭；只允许 `local_dev/test`，或显式 `JIEJING_ENABLE_DEMO_SESSION_BOOTSTRAP=true`，或带 `x-jiejing-operator-secret` 且匹配 `JIEJING_OPERATOR_BOOTSTRAP_SECRET`。
- public staging compose 强制 `JIEJING_ENABLE_DEMO_SESSION_BOOTSTRAP=false`。
- 生产域名/TLS/eBay callback/CORS 仍是 paid launch 准备项，不应通过 trycloudflare 作为正式商业入口。
- 备份恢复仍需正式演练证据：`backup_policy`、`restore_drill`、`backup_alerts`、COS probe/Vault backup policy 需要在真实云环境补齐。
