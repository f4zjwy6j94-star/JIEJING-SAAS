# Jiejing Latest New Window Prompt - 2026-05-19

Use this when moving to a fresh Codex/Claude Code window. The goal is to continue the Jiejing SaaS project without losing current state and without repeating completed work.

## Copy This First

```text
继续捷境 Jiejing SaaS 项目。先读取以下文件，不要从旧印象重新开始：

C:\Users\57249\Documents\Codex\2026-04-29\hermes-agents\software-demo\docs\JIEJING_GLOBAL_AUDIT_HANDOFF_20260519.md
C:\Users\57249\Documents\Codex\2026-04-29\hermes-agents\software-demo\docs\JIEJING_STAGING_STATUS_20260519.md
C:\Users\57249\Documents\Codex\2026-04-29\hermes-agents\software-demo\docs\JIEJING_TENCENT_CLOUD_RESOURCE_AUDIT_20260519.md
C:\Users\57249\Documents\Codex\2026-04-29\hermes-agents\software-demo\docs\JIEJING_CLAUDE_CODE_REVIEW_PACKET_20260519.md

项目方向：
捷境是独立产品级 SaaS，eBay-first AI CEO 商家工作台。自研 Jiejing Runtime / Agents 是目标；Hermes 只是历史参考和可替换内部工人，不能作为商家可见架构。

严禁重复：
- 不要重新做 eBay OAuth。
- 不要为了查进度重新跑官方 eBay 同步。
- 不要从 Tencent 浏览器登录/二维码开始；部署和状态检查先用 agentuser SSH。
- 不要声称已经可以收费上线。

当前事实：
- staging: https://mentioned-shake-inter-critical.trycloudflare.com
- server: 42.194.158.47
- SSH: agentuser + key C:\Users\57249\Documents\Codex\2026-05-15\saas-c-users-57249-documents-codex\ssh\jiejing_staging_ed25519
- remote app: /opt/jiejing-staging/app
- eBay OAuth callback 已完成。
- 官方 eBay 只读同步已完成。
- 当前官方 packet: packet_5c69bcc5bf0e79ae
- real platform writes: false
- Tencent Cloud: Postgres / Redis / SSM-KMS / CLS / COS 已接入 staging。
- 可能多余资源：CVM ins-01hsr6ti，公网 159.75.102.10；当前 SaaS 不跑在这台上，需先快照和审查再停机。

当前主要进度：
- SaaS 官网首页约 88%
- onboarding 约 78%
- 登录后工作台约 88%
- SaaS 后端约 95%
- eBay 只读真实链路约 98-99%
- 标准数据包约 96%
- Jiejing Runtime / Agents 约 83%
- Provider Jobs 约 70%
- 腾讯云 staging 约 86%
- 生产基础设施约 78%
- 真正可收费 SaaS 约 64-66%

下一步优先顺序：
1. 审查 CVM ins-01hsr6ti 是否旧资源：先快照和读取目录/容器，确认无用后停机观察，不要直接删除。
2. 清理 staging Docker build cache，只清 build cache，不碰 volumes。
3. 前端继续产品化：去 demo/mock 残留，官网 -> 向导 -> 工作台闭环要清楚展示真实 eBay 数据、标准包、AI CEO 报告、确认中心。
4. 做 live model-backed Market Report / Listing Package 价值证明，但模型 key 必须走 secret boundary。
5. 准备外部计费 provider、稳定域名/TLS/eBay callback/CORS。
```

## Most Important Files

- `docs/JIEJING_GLOBAL_AUDIT_HANDOFF_20260519.md`
- `docs/JIEJING_STAGING_STATUS_20260519.md`
- `docs/JIEJING_TENCENT_CLOUD_RESOURCE_AUDIT_20260519.md`
- `docs/JIEJING_CLAUDE_CODE_REVIEW_PACKET_20260519.md`
- `output/jiejing-new-window-handoff-latest-20260519.zip`

