# Prompt to Send to Claude Code

Please perform a read-only full review of this project. Do not modify files.

Repo path:

```text
C:\Users\57249\Documents\Codex\2026-04-29\hermes-agents\software-demo
```

Start by reading:

```text
docs/JIEJING_CLAUDE_CODE_REVIEW_PACKET_20260519.md
docs/JIEJING_TENCENT_CLOUD_RESOURCE_AUDIT_20260519.md
docs/JIEJING_GLOBAL_AUDIT_HANDOFF_20260519.md
docs/JIEJING_STAGING_STATUS_20260519.md
```

Project direction:

Jiejing / 捷境 is an independent product-grade SaaS for eBay-first cross-border sellers. It should become a merchant-facing AI CEO workbench. The core loop is:

```text
merchant login -> connect official eBay read-only account -> sync six eBay resource groups -> create standard data packet -> Jiejing Runtime / Agents create reports and work records -> confirmation center gates high-risk actions
```

Important guardrails:

- Hermes is historical/internal only, not public product architecture.
- Frontend must never see raw eBay tokens, Tencent credentials, model keys, or provider secrets.
- Database stores `secret_ref`, not raw secrets.
- Runtime/Agents consume sanitized standard packets only.
- Real platform writes remain disabled.
- Do not repeat eBay OAuth or run a fresh eBay official sync just to check status. Current packet is `packet_5c69bcc5bf0e79ae`.

Please review:

```text
jiejing_saas/
jiejing_runtime/
tools/
deploy/
schemas/
app.js
app.html
design-huashu.html
styles.css
docs/
```

Please run these checks if available:

```powershell
node --check app.js
python tools\jiejing_productization_stage_gate.py
python tools\jiejing_precloud_deployment_gate.py
python tools\test_jiejing_tencent_cloud_integrations.py
python tools\test_jiejing_managed_infra_readiness_cutover.py
python tools\test_jiejing_billing_quota_guardrail.py
python tools\test_jiejing_public_staging_proxy_contract.py
python tools\test_jiejing_model_value_rehearsal.py
```

Main questions:

1. Is the architecture reasonable for an eBay-first merchant SaaS?
2. Does the frontend still look like a demo anywhere, or does it communicate a real SaaS product?
3. Are Postgres, Redis, Tencent SSM/KMS, CLS, and COS properly integrated, or only superficially represented?
4. Which Tencent Cloud resources are actually needed, and which look wasteful?
5. Is CVM `ins-01hsr6ti` likely unused by current staging?
6. Are there secret/token leakage risks?
7. Are Jiejing Runtime and Agents becoming a real owned capability, or still mostly rule/template/demo?
8. What is the true current progress percentage by module?
9. What blocks private beta with one real merchant?
10. What blocks paid commercial launch?

Expected output:

- Executive verdict.
- Architecture map.
- Module progress percentages.
- P0/P1/P2/P3 findings.
- Tencent Cloud resource cleanup recommendations.
- Security/secret boundary findings.
- Frontend productization findings.
- Runtime/Agents value findings.
- Next 10 tasks in recommended order.

Again: read-only review only. Do not edit files.

