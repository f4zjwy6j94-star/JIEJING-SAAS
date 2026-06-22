# Jiejing External Review Prompt - 2026-06-13

Use this prompt for ClaudeCode or ChatGPT.

```text
Continue and review the Jiejing project in:
C:\Users\57249\Documents\Codex\2026-04-29\hermes-agents\software-demo

Product direction:
Jiejing is an eBay-first AI CEO SaaS for cross-border sellers. It is not a generic ERP, not a generic agent marketplace, and not a normal chatbot. The AI CEO can answer normal consulting questions, but eBay business work must route into the operating workflow: market research, bulk product selection, IP/VeRO screening, Listing, media assets, customer service learning, finance/fulfillment, decision center confirmation, execution, reports, source records, memory and audit.

Hard safety:
Do not print, write, or request secrets, passwords, eBay refresh tokens, model keys, Tencent credentials, Redis URLs, or database passwords. Do not repeat eBay OAuth. Do not ask the merchant to re-enter model keys unless provider authentication is proven invalid. BYOK and eBay tokens must stay inside backend secret boundaries. Real publish, price, inventory, refund, ads, policy edits, procurement payment and sensitive buyer promises must go through the confirmation center.

Current verified public staging:
https://individually-buffalo-prescribed-blocking.trycloudflare.com

Current public readiness truth:
- /health OK.
- database_startup_status=ready.
- real_platform_writes_enabled=true and requested_real_platform_writes=true.
- beta_ready=true.
- blocker_count=0.
- warning_count=2.
- model_value_proof=ready.
- latest official sanitized eBay packet: packet_f5cbba8068e6542d.
- model_secret_refs=1.
- execution_service=confirmation_gated_real_write_ready with severity info.
- production_ready=false and can_accept_real_customers=false.
- Do not overclaim formal paid launch. Paid billing provider, stable domain/OAuth callback, production hardening, monitoring/runbook, backup restore drill evidence and final commercial smoke are still required.
- Remaining warnings are paid billing provider not live and real Vault-backed eBay token refresh adapter pending.

Recent completed architecture:
- TencentDB PostgreSQL staging was recovered after billing downtime and fresh backups were created.
- Postgres durable queue adapter replaced unreachable Redis Streams for now.
- Queue supports claim, heartbeat, retry visibility, stale running recovery, dead-letter visibility and worker health.
- Formal bridges are RuntimeBridge, ProviderAdapter, QueueWorkerBridge, ConfirmationExecutionBridge and AuditMemoryBridge.
- HermesLegacyBridge is transitional only and cannot be a production dependency.
- DeepSeek BYOK model secret metadata was recovered through backend secret boundary.
- Real DeepSeek Market Report and Listing Package proof is green against official sanitized eBay packet source-chain.
- Account health / incident mode blocks real writes when account status is missing, restricted, frozen, suspended, limited, payout-hold, unverified or below standard.

2026-06-13 changes deployed to staging:
- Readiness severity cleanup: confirmation-gated real writes are info, not a warning.
- eBay SSM metadata recovery tool: tools/jiejing_recover_ebay_secret_refs_from_ssm.py.
- Lemon Squeezy billing provider support alongside Stripe/Paddle, including server-side signed webhook verification and paid-readiness tests.
- Updated handoff: docs/JIEJING_CLOUD_QUEUE_ACCOUNT_HEALTH_HANDOFF_20260612.md.
- Fixed Windows subprocess output decoding in tools/test_jiejing_staging_ebay_oauth_flow_tool.py so precloud deployment gate is stable on Chinese Windows terminals.
- Prepared staging bundle: output\jiejing-public-staging-bundle\jiejing-public-staging-20260613-022652.zip.
- Bundle SHA256: e991c132ee70c42f10839c91a0b8d46ca2a0441592aa4b2df7f90935f4bf5669.
- Manifest: output\jiejing-public-staging-bundle\jiejing-public-staging-20260613-022652.manifest.json.
- Incremental patch deployed through Google Chrome OrcaTerm/TAT: output\jiejing-20260613-incremental-patch.zip.
- Readiness-only correction patch deployed through Google Chrome OrcaTerm/TAT: output\jiejing-20260613-readiness-only-patch.zip.
- `jiejing-saas` and `jiejing-worker` were rebuilt and restarted.
- Public readiness now shows `execution_service=confirmation_gated_real_write_ready` with severity `info`.

Deploy channel truth:
- Public staging is reachable.
- agentuser@42.194.158.47 reaches SSH but rejects the known key.
- ubuntu@43.129.205.244 port 22 still times out during SSH banner exchange.
- ubuntu@43.129.205.244 port 2222 is the working SSH deploy channel from this machine using `%USERPROFILE%\.ssh\jiejing_43_ubuntu_ed25519`.
- Google Chrome OrcaTerm/TAT is the current working emergency deployment path when browser login is active.
- 2026-06-13 staging patches were deployed through OrcaTerm; backend/worker were rebuilt and restarted.
- Do not rely on older chat context saying this bundle is not deployed.

Exact next infrastructure steps:
1. Use `ssh -i %USERPROFILE%\.ssh\jiejing_43_ubuntu_ed25519 -p 2222 ubuntu@43.129.205.244` for SSH deploy access; keep repairing or replacing the broken port-22 path separately.
2. Configure a real paid billing provider before public paid launch.
3. Finish the real Vault-backed eBay token refresh adapter.
4. Run final commercial smoke before any paid public launch claim.

Useful tests to rerun:
python -m py_compile jiejing_saas\readiness.py jiejing_saas\billing_webhook.py jiejing_saas\billing_plan.py tools\jiejing_recover_ebay_secret_refs_from_ssm.py tools\test_jiejing_recover_ebay_secret_refs_from_ssm.py tools\test_jiejing_billing_provider_webhook.py tools\test_jiejing_billing_lemon_squeezy_readiness.py
python tools\test_jiejing_managed_infra_readiness_cutover.py
python tools\test_jiejing_recover_ebay_secret_refs_from_ssm.py
python tools\test_jiejing_ebay_refresh_secret_readiness.py
python tools\test_jiejing_billing_provider_webhook.py
python tools\test_jiejing_billing_quota_guardrail.py
python tools\test_jiejing_billing_lemon_squeezy_readiness.py
python tools\test_jiejing_staging_ebay_oauth_flow_tool.py
python tools\test_jiejing_saas_backend_mvp.py
python tools\jiejing_precloud_deployment_gate.py
python tools\jiejing_b_class_production_gate.py
python tools\jiejing_c_class_production_gate.py

Review focus:
1. Verify that the 2026-06-13 local changes do not leak secrets and do not weaken confirmation center boundaries.
2. Check whether the eBay metadata recovery tool safely restores only secret_ref/platform_connection metadata without raw token exposure.
3. Check billing provider normalization and Lemon Squeezy webhook signature verification.
4. Check readiness semantics: private beta can be green while paid production remains false.
5. Check deploy channel recovery options without repeating eBay OAuth or asking for model key re-entry.

2026-06-13 deployment correction:
- The earlier "local changes not yet deployed" section is now stale.
- Google Chrome OrcaTerm/TAT was restored and used to deploy incremental staging patches without printing secrets.
- Remote app path was confirmed as `/opt/jiejing-staging/app`.
- `jiejing-saas` and `jiejing-worker` were rebuilt and restarted.
- Public `/health` after restart is OK: `database_startup_status=ready`, `real_platform_writes_enabled=true`, `requested_real_platform_writes=true`, `secret_exposed=false`.
- Public `/readiness/product-saas` after restart: `beta_ready=true`, `blocker_count=0`, `warning_count=2`, `model_value_proof=ready`, `model_secret_refs=1`, latest packet `packet_f5cbba8068e6542d`.
- `execution_service=confirmation_gated_real_write_ready` now has severity `info`.
- Remaining warnings: paid billing provider is still private-beta/manual, and real Vault-backed eBay token refresh adapter is still pending.
- Do not overclaim formal public paid launch.
```
