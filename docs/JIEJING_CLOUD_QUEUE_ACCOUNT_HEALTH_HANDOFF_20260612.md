# Jiejing Cloud, Queue, Account Health Handoff - 2026-06-12

## Current Verified State

- Public staging health is OK.
- `database_startup_status=ready`.
- Backend is pointed at the new TencentDB PostgreSQL instance.
- A fresh sanitized Postgres backup was created after restore/cutover.
- `real_platform_writes_enabled=true`, but high-risk writes still require confirmation center approval.
- No eBay OAuth was repeated.
- No model key, eBay refresh token, database password, Tencent credential, or Redis URL was printed into this document.

## Cloud Recovery

- TencentDB PostgreSQL old endpoint was unavailable after billing downtime.
- A new Hong Kong TencentDB PostgreSQL instance was created and connected to staging.
- Backend and worker were restarted against Postgres.
- `/health` became healthy again.
- A fresh dump backup was created on the staging host after the new database came up.

## Queue Work Completed

Code now supports:

- queue job heartbeat
- stale running job recovery
- dead-letter transition after max attempts
- queue health summary endpoint: `/queue/health`
- worker loop watchdog recovery before claiming new work
- frontend settings/onboarding visibility for queue health

Important honesty note:

- Superseded by the 2026-06-12 12:55 update below.
- Redis Streams remained unreachable from staging/container, so the project did not keep trying to depend on Redis.
- The chosen fix is now the Postgres durable queue adapter.

## 2026-06-12 12:55 Update - Postgres Durable Queue Cutover

Implemented and deployed option 2: `postgres_durable`.

What changed:

- `jiejing_saas/queue_adapter.py` recognizes `postgres_durable` as a production-allowed adapter.
- `jiejing_saas/queue_plan.py` treats Postgres durable queue as a distributed queue shape without requiring Redis URL.
- `jiejing_saas/readiness.py` marks queue, queue adapter, worker plan, and infrastructure drivers ready when `postgres_durable` is selected with managed Postgres.
- `jiejing_saas/infrastructure_drivers.py` treats Redis as replaced/not required when `postgres_durable` is selected.
- `jiejing_saas/repository.py` uses a Postgres claim path with `FOR UPDATE SKIP LOCKED` so multiple workers can claim queued jobs safely.
- `tools/jiejing_worker_cli.py` reports `worker_runtime=postgres_durable_queue`.
- Regression test added: `tools/test_jiejing_postgres_durable_queue_adapter.py`.

Staging deployment:

- Deploy channel used: `ubuntu@43.129.205.244` with the Route-A SSH key.
- `agentuser@42.194.158.47` currently rejects the known keys; public staging is still reachable.
- Backend/worker were rebuilt and restarted.
- Private env was backed up, then switched to `JIEJING_QUEUE_PROVIDER=postgres_durable`.
- No DB URL, DB password, eBay token, model key, Tencent credential, or Redis URL was printed.

Fresh backup:

- A fresh Postgres custom-format dump was created after the cutover:
  `/opt/jiejing-staging/app/output/private-backups/postgres/jiejing-postgres-after-postgres-durable-20260612-124905.dump`
- The backup was created using a one-shot official `postgres:18` container because the SaaS container does not include `pg_dump`.

Verified staging state after cutover:

- Public `/health`: OK.
- `database_startup_status=ready`.
- Container env summary:
  - `queue_provider=postgres_durable`
  - `queue_url_configured=False`
  - `database_engine=postgres`
  - `database_url_configured=True`
- Worker status:
  - `worker_runtime=postgres_durable_queue`
  - `database_engine=postgres`
  - `database_url_configured=true`
- Queue health summary for a real company:
  - `status=ready`
  - `queue_provider=postgres_durable`
  - `stale_running_count=0`
  - `worker_heartbeat_required=true`
  - `dead_letter_visible=true`

Historical readiness after the 2026-06-12 12:55 cutover:

- `queue`: `postgres_durable_queue_ready`, info.
- `queue_adapter_contract`: `managed_queue_live`, info.
- `queue_worker_plan`: `ready`, info.
- `infrastructure_drivers`: `ready`, info.
- Historical remaining blocker count: 1.
- Historical remaining blocker: `model_value_proof` / `blocked_live_model_value_not_proven`.
- This blocker was later cleared in the 2026-06-12 late recovery update.

## 2026-06-12 15:35 Update - Controlled Bridge Contract

Implemented and deployed the formal bridge contract requested after the Postgres durable queue cutover.

Formal bridges:

- `RuntimeBridge`: SaaS backend to Jiejing Runtime tasks/results.
- `ProviderAdapter`: backend secret boundary to provider adapters and normalized source/output packets.
- `QueueWorkerBridge`: durable queue jobs to worker claim/heartbeat/retry/dead-letter/recovery.
- `ConfirmationExecutionBridge`: confirmation center to ExecutionService and provider write adapters.
- `AuditMemoryBridge`: reports/confirmations/executions to audit logs and merchant memory writeback.

Legacy bridge:

- `HermesLegacyBridge` is now explicitly `disabled_transitional_only` by default.
- It is not a formal production dependency.
- If `JIEJING_ALLOW_HERMES_ADAPTERS=true`, readiness marks the bridge contract as blocked for formal launch.

Code added or changed:

- Added `jiejing_saas/controlled_bridges.py`.
- Added API endpoint `/controlled-bridges`.
- Added readiness item `controlled_bridges`.
- Added `provider_status.controlled_bridges`.
- Updated chain schema so the formal route names are visible.
- Added regression test `tools/test_jiejing_controlled_bridges.py`.
- Updated productization gate and backend MVP test to enforce the bridge contract.

Verified staging state after bridge deploy:

- Public `/health`: OK.
- Remote `tools/test_jiejing_controlled_bridges.py`: PASS.
- Remote `tools/test_jiejing_postgres_durable_queue_adapter.py`: PASS.
- Remote worker status:
  - `queue_provider=postgres_durable`
  - `database_engine=postgres`
  - `database_url_configured=true`
  - `worker_runtime=postgres_durable_queue`
- Public readiness:
  - `controlled_bridges`: `ready`, info.
  - `formal_bridge_count=5`.
  - `legacy_bridge_count=1`.
  - `production_blockers=[]`.
  - `hermes_legacy_bridge_can_be_production_dependency=false`.
  - Remaining blocker count still 1: `model_value_proof`.

## Account Health / Store Suspension Risk

Backend publish preflight and publish readiness now block real publish when account health is missing or indicates:

- frozen
- restricted
- suspended
- limited
- payout hold / payment hold
- unverified / below standard

When blocked, the readiness check enters incident mode:

- allowed: diagnostics, evidence package, read-only sync
- blocked: publish, price revision, inventory changes, refunds, ads, policy changes

## Tests Passed Locally

- `python -m py_compile jiejing_saas\api_server.py jiejing_saas\repository.py jiejing_saas\worker.py jiejing_saas\ebay_write_adapter.py tools\jiejing_worker_cli.py`
- `node --check app.js`
- `python tools\test_jiejing_queue_recovery_heartbeat.py`
- `python tools\test_jiejing_worker_cli_contract.py`
- `python tools\test_jiejing_account_health_preflight.py`
- `python tools\test_jiejing_ebay_write_adapter.py`
- `python tools\test_jiejing_saas_clean_settings_and_listing_ui.py`
- `python tools\test_jiejing_saas_readable_decision_service_settings_ui.py`
- `python tools\test_jiejing_staging_patch_apply_contract.py`

Remote container tests:

- `python tools/test_jiejing_ebay_write_adapter.py` passed.
- `python tools/test_jiejing_account_health_preflight.py` passed.
- `python tools/test_jiejing_queue_recovery_heartbeat.py` initially exposed that the test was inheriting staging Postgres env; the test has been fixed locally to force SQLite for white-box queue state.

## Historical Remaining Blocker At 2026-06-12 15:35 - Superseded

At this point in the 2026-06-12 run, readiness still reported one blocker. This is historical context only and is superseded by the late recovery update below.

1. `model_value_proof`: live model-backed Market Report and Listing Package evidence still needs to be proven against sanitized official eBay packets.

## 2026-06-12 17:35 Update - Model Value Proof Recheck

Safe checks performed:

- Public `/health` remains OK.
- Current Postgres has no `secret_refs` and no `platform_data_packets` after the new database recovery.
- Container/private env does not contain DeepSeek/OpenAI/FAL model provider keys.
- Tencent SSM credentials and SDK are present, but SSM metadata listing did not show model/deepseek/openai/byok markers.
- Old env backups checked for model provider key names; none were present.
- No raw model key, eBay token, DB password, Tencent secret, or Redis URL was printed.

Fix deployed to staging:

- `managed_vault_stored` is now treated as a ready model-secret status for merchant BYOK model settings, model value gate evidence, and model client resolution.
- This prevents a valid Tencent SSM/Vault-stored model key from being misreported as missing.

Verified:

- Local `python -m py_compile jiejing_saas\api_server.py jiejing_saas\model_provider_catalog.py jiejing_saas\model_value_gate.py jiejing_saas\model_value_rehearsal.py` passed.
- Local `python tools\test_jiejing_merchant_byok_model_and_memory.py` passed.
- Local `python tools\test_jiejing_model_value_rehearsal.py` passed.
- Remote deploy rebuilt and restarted `jiejing-saas` and `jiejing-worker`.
- Public readiness after deploy still has one blocker. The public model value blocker is now narrowed to `model_provider_not_configured`.

Important truth:

- Historical at 2026-06-12 17:35: `model_value_proof` was not clear yet because the current backend secret boundary had no resolvable model provider credential metadata.
- This was later superseded by the 2026-06-12 late recovery update: model secret metadata was recovered through the backend boundary and public readiness now reports `model_value_proof=ready`.
- Do not claim formal launch readiness.
- Do not repeat eBay OAuth.
- Do not ask the user to reconfigure a model key unless current backend/Vault metadata recovery is exhausted and the missing model secret is explicitly confirmed.

Local-only patch not yet deployed due SSH timeout:

- `model_value_gate` has been tightened locally so Market Report and Listing Package value proof requires both live model evidence and a link back to a sanitized official eBay packet.
- This is needed because current DB has no `platform_data_packets`, and a report-only live flag is not enough to satisfy the desired source-chain proof.
- Local tests passed after this tightening.
- Route-A SSH started timing out during banner exchange; `agentuser@42.194.158.47` still rejects the known key.

2026-06-12 continuation check:

- Public readiness now shows `platform_data_packets=1`.
- Latest packet is `official_api`, has 6/6 resource keys, and has no missing resource keys.
- `secret_refs=0` and `model_secret_refs=0` remain true.
- Therefore the packet source-chain prerequisite is partly restored, but the model provider credential metadata is still missing.
- Route-A SSH still fails with `ssh_network_timeout` / banner exchange timeout while TCP 22 is open.
- Chrome extension control failed locally under the current sandbox, so Tencent Cloud console inspection was not completed in this turn.

## Recommended Next Steps

1. Restore or rehydrate sanitized official eBay packet metadata into Postgres without repeating OAuth, then deploy the source-chain gate tightening.
2. Recover the missing merchant model `secret_ref` metadata if it exists in backup/SSM, or create it only through the backend BYOK secret boundary.
3. Run model value rehearsal against the restored store/packet state; fix BYOK mapping if `model_value_proof` stays blocked.
4. Restore or rehydrate merchant records if old DB data is required. Do not repeat eBay OAuth unless current secret refs are proven unrecoverable.
5. Add account health center UI backed by real eBay account/seller status when available, not only publish payload readiness.
6. Add incident mode automation: when account health is restricted/frozen, automatically pause all real writes and surface evidence package actions.
7. Keep staging as not production-ready until billing, stable domain/OAuth callback, monitoring, backup restore drill evidence, model value proof, and commercial smoke are green.

## Migration Prompt

Use this prompt for ClaudeCode or ChatGPT:

```text
Continue the Jiejing project in:
C:\Users\57249\Documents\Codex\2026-04-29\hermes-agents\software-demo

Product direction:
Jiejing is an eBay-first AI CEO SaaS for cross-border sellers. It is not a generic ERP, not a generic agent marketplace, and not a normal chatbot. AI CEO should support normal consulting conversation, but eBay business actions must route into the operating workflow. High-risk real actions including publish, price, inventory, refund, ads, policy changes, procurement payment, and sensitive buyer promises must go through the confirmation center.

Strict safety:
Do not print or write secrets, passwords, eBay refresh tokens, model keys, Tencent credentials, Redis URLs, or DB passwords. Do not repeat eBay OAuth. Do not ask the user to reconfigure model keys unless provider authentication is proven invalid. BYOK and eBay tokens must stay inside backend secret boundaries.

Current public staging:
https://individually-buffalo-prescribed-blocking.trycloudflare.com

Current verified public readiness:
- /health OK, database_startup_status=ready.
- real_platform_writes_enabled=true and requested_real_platform_writes=true, but confirmation center boundaries still apply.
- beta_ready=true.
- blocker_count=0.
- model_value_proof=ready.
- model_secret_refs=1.
- latest official sanitized eBay packet: packet_f5cbba8068e6542d.
- production_ready=false and can_accept_real_customers=false remain correct because paid billing provider, stable domain/OAuth callback, production hardening, monitoring/runbook, backup restore drill evidence and final commercial smoke are not all live.

Recent completed work:
1. Restored TencentDB PostgreSQL-backed staging after billing downtime and created fresh Postgres backups.
2. Added queue heartbeat, stale running job recovery, dead-letter handling, queue health summary, and worker watchdog recovery.
3. Chose and deployed Postgres durable queue adapter instead of continuing to depend on unreachable Redis Streams.
4. Added /queue/health API and settings UI queue health visibility.
5. Added account health gate to publish preflight/readiness. Missing or frozen/restricted/suspended/limited/payout-hold/unverified account health blocks real publish and enters incident mode.
6. Added formal bridge contract: RuntimeBridge, ProviderAdapter, QueueWorkerBridge, ConfirmationExecutionBridge and AuditMemoryBridge.
7. HermesLegacyBridge is transitional only and cannot be a production dependency.
8. Recovered DeepSeek BYOK model secret metadata through backend secret boundary and proved Market Report + Listing Package with live DeepSeek evidence and official sanitized eBay packet source-chain.
9. Locally added eBay secret metadata recovery from Tencent SSM after Postgres restore without printing or storing raw secret values.
10. Locally added Lemon Squeezy billing provider support alongside Stripe and Paddle, including server-side webhook HMAC verification and readiness tests.

Important current truth:
Redis Streams private env existed, but Redis host was not reachable from staging/container. The project chose option 2 and deployed a Postgres durable queue adapter. Current effective queue provider is postgres_durable. Queue, queue adapter, worker plan and infrastructure drivers are no longer readiness blockers. model_value_proof is now ready. Do not use older docs that still say model_value_proof is blocked without re-verifying public readiness.

Controlled bridge state:
- RuntimeBridge, ProviderAdapter, QueueWorkerBridge, ConfirmationExecutionBridge and AuditMemoryBridge are the formal SaaS bridges.
- HermesLegacyBridge is transitional only and cannot be a production dependency.
- /controlled-bridges and readiness.provider_status.controlled_bridges expose this contract.

Next work:
1. Deploy the 2026-06-13 local changes once SSH/Tencent TAT access is available again.
2. Expand account health center UI with real eBay account/seller status when available.
3. Keep all real writes behind confirmation center.
4. Configure a real paid billing provider plan/quota/webhook before public paid launch.
5. Continue hardening stable domain/OAuth callback, monitoring, backup restore drills, incident runbooks and final commercial smoke before public paid launch.

Current deploy channel truth:
- Public staging is reachable.
- Normal SSH is not reliable from this machine: agentuser@42.194.158.47 rejects the known key; ubuntu@43.129.205.244 still times out during banner exchange.
- Prior emergency deployment used Tencent TAT/OrcaTerm, but that browser session needs valid login again before it can be reused.

Useful tests:
python -m py_compile jiejing_saas\api_server.py jiejing_saas\repository.py jiejing_saas\worker.py jiejing_saas\ebay_write_adapter.py jiejing_saas\billing_webhook.py jiejing_saas\billing_plan.py jiejing_saas\readiness.py tools\jiejing_worker_cli.py
node --check app.js
python tools\test_jiejing_queue_recovery_heartbeat.py
python tools\test_jiejing_worker_cli_contract.py
python tools\test_jiejing_postgres_durable_queue_adapter.py
python tools\test_jiejing_account_health_preflight.py
python tools\test_jiejing_ebay_write_adapter.py
python tools\test_jiejing_recover_ebay_secret_refs_from_ssm.py
python tools\test_jiejing_billing_provider_webhook.py
python tools\test_jiejing_billing_lemon_squeezy_readiness.py
python tools\test_jiejing_saas_clean_settings_and_listing_ui.py
python tools\test_jiejing_saas_readable_decision_service_settings_ui.py
python tools\jiejing_b_class_production_gate.py
python tools\jiejing_c_class_production_gate.py
```

## 2026-06-12 Late Recovery Update

Completed after the previous handoff:

- The source-chain gate tightening patch was deployed to staging through the Tencent TAT/OrcaTerm path because normal SSH still timed out during banner exchange.
- SSH service on the Tencent instance was restarted and hardened, but local OpenSSH still cannot complete banner exchange. Treat TAT/OrcaTerm as the working emergency channel until SSH is fully diagnosed.
- SSM/Vault metadata was inspected inside the backend boundary without printing or writing raw secret values.
- Existing DeepSeek BYOK secret metadata was recovered into Postgres as one `secret_refs` row. No model key was written to a file or response.
- Real DeepSeek-backed model value rehearsal was run against the restored official eBay packet.
- Market Report and Listing Package both have live-model evidence and official sanitized eBay packet source-chain proof.
- Public readiness now reports `blocker_count=0`, `beta_ready=true`, `model_value_proof=ready`, and `provider_status.model_value.ready_for_paid_value_claim=true`.

Current public readiness truth:

- `/health`: database is ready, real platform writes are enabled/requested, and `secret_exposed=false`.
- `/readiness/product-saas`: private beta gate is green, but paid public production is still not green.
- `production_ready=false` and `can_accept_real_customers=false` remain correct because paid billing provider, stable domain/OAuth callback, production hardening, monitoring/runbook, and final commercial smoke still need completion.
- The earlier cosmetic/aggregation inconsistency has been fixed and deployed: `product_evidence.model_secret_refs=1` now matches `provider_status.model_value.merchant_byok_secret_ref_count=1`.

Do not repeat eBay OAuth. Do not ask the merchant to re-enter the model key based on the old missing-secret state; the model proof has been recovered through the backend secret boundary.

## 2026-06-13 Continuation Update - Billing, eBay Secret Metadata Recovery, Gate Recheck

Completed locally after the 2026-06-12 late recovery update:

- Rechecked public staging `/health` and `/readiness/product-saas`.
- Current public readiness is private-beta green: `beta_ready=true`, `blocker_count=0`, `model_value_proof=ready`, `model_secret_refs=1`, latest packet `packet_f5cbba8068e6542d`.
- Current public paid launch state is still not green: `production_ready=false`, `can_accept_real_customers=false`, billing is still `manual_seed` and paid billing provider is not live.
- Fixed readiness wording/severity so `confirmation_gated_real_write_ready` is treated as an `info` readiness item, not a permanent warning. Confirmation-gated writes are the required safety boundary, not a defect.
- Added a backend-boundary recovery tool for eBay secret metadata after Postgres restore: `tools/jiejing_recover_ebay_secret_refs_from_ssm.py`.
- The recovery tool reads Tencent SSM only through the backend secret boundary, never prints secret values, and writes only `secret_refs` / `platform_connections` metadata when run with `--apply`.
- Added regression coverage to prove the recovery path does not leak a fake secret marker.
- Added Lemon Squeezy billing provider support next to Stripe and Paddle:
  - provider normalization: `lemon_squeezy`, `lemonsqueezy`, `lemon-squeezy`
  - server-side API key and webhook secret env names
  - plan/variant IDs for starter/operator/team
  - HMAC SHA256 webhook verification through the `X-Signature` header
  - subscription lifecycle/payment success/payment failure event normalization
  - readiness coverage for paid billing provider configuration

Local verification completed:

- `python -m py_compile jiejing_saas\readiness.py jiejing_saas\billing_webhook.py jiejing_saas\billing_plan.py tools\test_jiejing_managed_infra_readiness_cutover.py tools\jiejing_recover_ebay_secret_refs_from_ssm.py tools\test_jiejing_recover_ebay_secret_refs_from_ssm.py tools\test_jiejing_billing_provider_webhook.py tools\test_jiejing_billing_lemon_squeezy_readiness.py`
- `python tools\test_jiejing_managed_infra_readiness_cutover.py`
- `python tools\test_jiejing_recover_ebay_secret_refs_from_ssm.py`
- `python tools\test_jiejing_ebay_refresh_secret_readiness.py`
- `python tools\test_jiejing_billing_provider_webhook.py`
- `python tools\test_jiejing_billing_quota_guardrail.py`
- `python tools\test_jiejing_billing_lemon_squeezy_readiness.py`
- `python tools\test_jiejing_saas_backend_mvp.py`
- `python tools\jiejing_b_class_production_gate.py`: PASS, 4/4 groups, 100%.
- `python tools\jiejing_c_class_production_gate.py`: PASS, 5/5 groups, 100%.
- `python tools\test_jiejing_staging_ebay_oauth_flow_tool.py`: PASS after fixing Windows subprocess output decoding.
- `python tools\jiejing_precloud_deployment_gate.py`: PASS, `ready_for_public_staging_code_handoff=true`.
- Final re-run after the test fix:
  - `python tools\jiejing_b_class_production_gate.py`: PASS, 4/4 groups, 100%.
  - `python tools\jiejing_c_class_production_gate.py`: PASS, 5/5 groups, 100%.
  - Sensitive-pattern scan over the changed code/docs: no matches.

Important correction:

- A temporary B/C gate failure was caused by the backend MVP test SQLite file being locked by a previous run. No Python backend test process remained; after the lock cleared, the backend contract, B-class gate, and C-class gate all passed.
- A later precloud gate failure was caused by Windows GBK decoding in the OAuth flow regression test. The test now pins subprocess output to UTF-8 with replacement and guards against `None` stdout/stderr.

Prepared deployment artifact:

- Bundle: `output\jiejing-public-staging-bundle\jiejing-public-staging-20260613-022652.zip`
- Manifest: `output\jiejing-public-staging-bundle\jiejing-public-staging-20260613-022652.manifest.json`
- SHA256: `e991c132ee70c42f10839c91a0b8d46ca2a0441592aa4b2df7f90935f4bf5669`
- File count: 413

Deployment status:

- The 2026-06-13 staging patch has been deployed through Google Chrome OrcaTerm/TAT.
- Remote app path confirmed: `/opt/jiejing-staging/app`.
- Remote backups were written under `/home/ubuntu/jiejing-patch-backups/`.
- `jiejing-saas` and `jiejing-worker` were rebuilt and restarted with Docker Compose.
- Public `/health`: OK, `database_startup_status=ready`, `real_platform_writes_enabled=true`, `requested_real_platform_writes=true`, `secret_exposed=false`.
- Public `/readiness/product-saas`: `beta_ready=true`, `blocker_count=0`, `warning_count=2`, `model_value_proof=ready`, `model_secret_refs=1`, latest packet `packet_f5cbba8068e6542d`.
- `execution_service` now returns `confirmation_gated_real_write_ready` with severity `info`.
- Normal SSH is still not reliable from this machine:
  - `agentuser@42.194.158.47` reaches SSH but rejects the known key.
  - `ubuntu@43.129.205.244` times out during SSH banner exchange.
- Keep Google Chrome OrcaTerm/TAT as emergency deployment path until normal SSH is repaired.

Do not overclaim:

- The project is private-beta ready by current public readiness, not paid public production ready.
- Do not claim formal launch readiness until paid billing provider, stable domain/OAuth callback, production monitoring/backup restore drill/runbook, and final commercial smoke are live and verified.
- Do not repeat eBay OAuth.
- Do not print or store raw eBay/model/Tencent/database secrets while recovering metadata.

## 2026-06-13 OrcaTerm Deployment Verification

Current correction to the deployment status above:

- Google Chrome OrcaTerm/TAT terminal was restored and used to deploy the staging patch without printing secrets.
- Remote app path confirmed: `/opt/jiejing-staging/app`.
- Remote backups were written under `/home/ubuntu/jiejing-patch-backups/`.
- The full bundle remains available at `output\jiejing-public-staging-bundle\jiejing-public-staging-20260613-022652.zip`, SHA256 `e991c132ee70c42f10839c91a0b8d46ca2a0441592aa4b2df7f90935f4bf5669`.
- Browser upload of the full bundle was fragile, so the deployed update used incremental patches:
  - `output\jiejing-20260613-incremental-patch.zip`, SHA256 `EAD3E4A6D75EE8CE628E18ACE45D21631C6694447E13E6F32E836CCBD42FFCBB`.
  - `output\jiejing-20260613-readiness-only-patch.zip`, SHA256 `456CF3D29F438B33C33E2DC123E828B5A505F0CDE9C84BC63E5D995F0270CAA2`.
- `jiejing-saas` and `jiejing-worker` were rebuilt and restarted with Docker Compose.
- Public `/health` after restart: OK, `database_startup_status=ready`, `real_platform_writes_enabled=true`, `requested_real_platform_writes=true`, `secret_exposed=false`.
- Public `/readiness/product-saas` after restart: `beta_ready=true`, `blocker_count=0`, `warning_count=2`, `model_value_proof=ready`, `model_secret_refs=1`, latest packet `packet_f5cbba8068e6542d`.
- `execution_service` now returns `confirmation_gated_real_write_ready` with severity `info`.
- Remaining public readiness warnings:
  - `billing_quota=private_beta_quota_ready`: paid billing provider is still not live.
  - `ebay_token_refresh=refresh_adapter_pending`: final real Vault-backed refresh adapter still needs completion.

## 2026-06-13 SSH Recovery Update

SSH remediation completed through Google Chrome OrcaTerm/TAT:

- Server-side `sshd` was active, but local SSH to `43.129.205.244:22` still timed out during banner exchange.
- Server local banner test succeeded for both `127.0.0.1:22` and `127.0.0.1:2222`, proving OpenSSH itself returns a banner correctly.
- `ssh.socket` socket activation was disabled and persistent `ssh.service` was enabled/restarted.
- `/etc/ssh/sshd_config.d/999-jiejing-ops.conf` was added:
  - `Port 22`
  - `Port 2222`
  - `UseDNS no`
  - `MaxStartups 100:30:200`
  - `PubkeyAuthentication yes`
  - `PasswordAuthentication yes`
  - `PermitRootLogin prohibit-password`
  - `LogLevel VERBOSE`
- Tencent Cloud Lighthouse firewall now has a custom allow rule for TCP `2222`, source `all IPv4`, remark `SSH backup`.
- Current verified deploy access:
  - `ssh -i %USERPROFILE%\.ssh\jiejing_43_ubuntu_ed25519 -p 2222 ubuntu@43.129.205.244` logs in successfully from this machine.
  - Port `22` still reaches TCP but times out before banner; treat it as unreliable.
- Use port `2222` for future emergency SSH/deploy checks, while keeping Google Chrome OrcaTerm/TAT as fallback.
- The 2222 SSH deploy channel was verified against `/opt/jiejing-staging/app`; Docker Compose reported `deploy-jiejing-frontend-1`, `deploy-jiejing-saas-1`, `deploy-jiejing-vault-1`, and `deploy-jiejing-worker-1` running.
