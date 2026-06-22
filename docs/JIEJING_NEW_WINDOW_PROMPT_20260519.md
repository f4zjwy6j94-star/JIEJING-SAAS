# Copy This Into A New Window

继续捷境 Jiejing SaaS 项目。先读取并遵守：

`C:\Users\57249\Documents\Codex\2026-04-29\hermes-agents\software-demo\docs\JIEJING_GLOBAL_AUDIT_HANDOFF_20260519.md`

当前方向不能偏：

- 捷境是 eBay-first AI CEO SaaS，面向跨境电商商家。
- Jiejing Runtime / Agent 团队是自研底座。
- Hermes 只作为历史参考和可替换内部工人，不能作为商家前台产品语言。
- Runtime / Agents 只能吃 sanitized standard data packet，不能碰 eBay token 或云密钥。
- 真实平台写入仍然关闭；发布、改价、退款、广告预算、采购付款、政策修改、敏感客服承诺都必须进确认中心。

当前 staging：

- Public staging: `https://mentioned-shake-inter-critical.trycloudflare.com`
- SSH: `agentuser@42.194.158.47`
- SSH key: `C:\Users\57249\Documents\Codex\2026-05-15\saas-c-users-57249-documents-codex\ssh\jiejing_staging_ed25519`
- Remote app: `/opt/jiejing-staging/app`
- Local repo: `C:\Users\57249\Documents\Codex\2026-04-29\hermes-agents\software-demo`

不要重复做：

- 不要重新开 eBay OAuth 授权。
- 不要为了检查进度重新跑 eBay 官方同步。
- 不要重复腾讯云开通流程。
- 不要把 trycloudflare staging 说成正式生产域名。
- 不要把手动 seed billing 说成真正可收费订阅系统。

当前真实状态：

- eBay OAuth callback 已完成。
- 官方 eBay 只读同步已完成。
- 最新官方 packet：`packet_5c69bcc5bf0e79ae`
- 六类资源齐：store profile、business policies、inventory/offers、orders/fulfillment、finances、taxonomy/listing metadata。
- Postgres/Redis/SSM/KMS/CLS/COS 已接入 staging readiness。
- `/infrastructure/drivers` 反代缺口已修复。
- 当前硬阻塞只剩 `model_value_proof`。
- 付费上线还缺：真实模型价值证明、外部订阅计费 provider、稳定域名/TLS/eBay callback/CORS、长期监控告警和备份恢复演练。

下一步请直接做，不要问我：

1. 配置/接入真实模型 provider 的安全边界和模型价值证明流程。
2. 用 `packet_5c69bcc5bf0e79ae` 跑 Market Report 和 Listing Package 的 live-model evidence。
3. 修工作台剩余产品化问题：未登录前不要打认证接口、清掉 demo 残留、把真实 packet/reports/confirmations/freshness 显示清楚。
4. 做云端清理：确认 SSM 可完整替代 Vault 后，再移除 HashiCorp Vault 过渡容器；简化 staging compose 里看起来像 SQLite 主库的参数。

最后必须诚实汇报进度，不允许把 code-contract 进度当成 paid commercial SaaS ready。
