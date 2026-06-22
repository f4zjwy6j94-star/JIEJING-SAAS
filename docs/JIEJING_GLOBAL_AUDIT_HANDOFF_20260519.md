# Jiejing Global Audit and Handoff - 2026-05-19

This document is the current handoff anchor for continuing Jiejing in a new window.
It is intentionally explicit to avoid repeated OAuth, repeated eBay sync, repeated Tencent Cloud setup, and false launch claims.

## 1. Product Direction

- Product: Jiejing, an eBay-first AI CEO SaaS for cross-border e-commerce merchants.
- Public positioning: merchant-facing AI CEO workbench, source records, work records, reports, and confirmation center.
- Runtime direction: self-owned Jiejing Runtime / Agent team.
- Hermes position: historical/internal reference and replaceable worker only. Hermes must not be exposed as the merchant-facing product.
- Token rule: Runtime and Agents must receive sanitized standard data packets only. They must never receive raw eBay tokens, refresh tokens, cloud keys, or provider API keys.
- Write rule: real eBay/platform writes remain disabled. Publishing, price changes, refunds, policy edits, ad budgets, procurement payments, and sensitive customer commitments must stay behind confirmation.

## 2. Canonical Paths and Access

- Local repo: `C:\Users\57249\Documents\Codex\2026-04-29\hermes-agents\software-demo`
- Current Codex workspace used for SSH key: `C:\Users\57249\Documents\Codex\2026-05-15\saas-c-users-57249-documents-codex`
- Public staging: `https://mentioned-shake-inter-critical.trycloudflare.com`
- Tencent server: `42.194.158.47`
- Staging SSH user: `agentuser`
- SSH key: `C:\Users\57249\Documents\Codex\2026-05-15\saas-c-users-57249-documents-codex\ssh\jiejing_staging_ed25519`
- Remote app path: `/opt/jiejing-staging/app`
- Compose file: `/opt/jiejing-staging/app/deploy/docker-compose.public-https-staging.yml`

Do not start with Tencent browser login or root SSH. Use the `agentuser` SSH path first.

## 3. Current Verified Staging State

- `/health` is reachable and returns staging.
- `real_platform_writes_enabled=false`.
- `/readiness/product-saas` returns `production_ready=false`, `can_accept_real_customers=false`, `blocker_count=1`, `warning_count=4`.
- Current hard blocker: `model_value_proof`.
- Current official eBay packet: `packet_5c69bcc5bf0e79ae`.
- Packet source mode: `official_api`.
- Packet resource coverage:
  - `store_profile`
  - `account_business_policies`
  - `inventory_and_offers`
  - `orders_and_fulfillment`
  - `finances`
  - `taxonomy_listing_metadata`
- Missing packet resources: none.
- Reports exist in staging: 44.
- Confirmation records exist in staging: 36.
- Audit logs exist in staging: over 300.
- Secret exposure flags checked by readiness and gates: false.

Important: eBay OAuth callback and official read-only sync are already complete. Do not repeat authorization or sync just to check progress.

## 4. What Was Done In The Latest Pass

- Rechecked current memory/status to avoid repeating OAuth and eBay sync.
- Rechecked public staging `/health` and `/readiness/product-saas`.
- Ran local gates:
  - `node --check app.js`
  - `python tools\jiejing_productization_stage_gate.py`
  - `python tools\jiejing_precloud_deployment_gate.py`
  - `python tools\test_jiejing_tencent_cloud_integrations.py`
  - `python tools\test_jiejing_billing_quota_guardrail.py`
  - `python tools\test_jiejing_managed_infra_readiness_cutover.py`
  - `python tools\test_jiejing_public_staging_proxy_contract.py`
- Audited public homepage and workbench with Playwright:
  - Homepage status 200.
  - Workbench status 200.
  - Homepage console/page errors: 0.
  - Workbench page errors: 0.
  - Workbench console shows expected unauthenticated 401 before login and one transient HTTP2 resource error.
  - Public visible Hermes text: false.
  - Homepage demo/mock visible text count: 0.
  - Workbench demo/mock visible text count: 1.
- Found and fixed one public proxy issue:
  - `/infrastructure/drivers` was falling through to frontend HTML.
  - Added `infrastructure` to `deploy/nginx.public-staging.conf` API proxy regex.
  - Added regression coverage to `tools/test_jiejing_public_staging_proxy_contract.py`.
  - Deployed the nginx config to staging and restarted the frontend nginx container.
  - Verified `/infrastructure/drivers` now returns 401 without token and returns backend driver status with token.

## 5. Tencent Cloud Architecture Review

Current selected cloud products fit the current SaaS stage:

- TencentDB for PostgreSQL: correct primary database choice for SaaS tenant data, stores, tasks, reports, confirmations, audit logs, and standard packets.
- TencentDB for Redis: correct queue/runtime delivery choice for async eBay sync, provider jobs, model jobs, retries, and dead-letter flow.
- Tencent SSM/KMS: correct secret boundary for eBay refresh tokens, model keys, search keys, media keys, sourcing/logistics credentials.
- Tencent CLS: correct log and alerting target, provided request bodies, Authorization headers, and raw tokens remain excluded.
- Tencent COS: correct low-cost backup/drill storage target.

Runtime evidence from staging:

- `/database/inventory` reports `engine=postgres`, `db_path=[managed-postgres]`, 17 tables.
- `/queue/plan` reports selected adapter `redis_streams`.
- `/vault/secret-resolver/status` reports provider `tencent_ssm`, status `ready`, managed live resolution ready.
- `/monitoring/status` reports provider `tencent_cls`, safe access logs enabled, no request body/header/raw token logging.
- `/backup/plan` reports Postgres managed database selected, COS target ready, backup ready for paid-launch gate.
- `/infrastructure/drivers` now routes correctly and reports Postgres/Redis dependency available and `ready_for_runtime_cutover=true` on staging.

The architecture is not wasteful for the intended SaaS direction. It is the smallest credible managed-cloud stack for merchant data and credential-bearing automation.

## 6. Waste / Redundancy / Cleanup Findings

These are real findings, not blockers:

1. HashiCorp Vault container still runs in the public staging compose file while Tencent SSM is now selected.
   - Current judgment: acceptable as transitional fallback/history, but it adds complexity and resource usage.
   - Next cleanup: remove or pause it only after confirming all existing eBay refresh-token secret refs are migrated and resolvable in SSM.

2. `docker-compose.public-https-staging.yml` still passes `/data/saas.sqlite` and `/data/runtime.sqlite` CLI arguments.
   - Current judgment: confusing but not currently fatal because runtime environment selects managed Postgres.
   - Next cleanup: simplify the CLI/startup path so staging cannot look like SQLite is still primary.

3. Public workbench still contains historical demo/mock/sample state inside `app.js`.
   - Current judgment: public visible copy is mostly protected by replacement and product mode, but technical debt remains.
   - Next cleanup: split product data from fallback/tutorial data and keep demo-only data behind explicit local/operator mode.

4. Public homepage does not yet strongly show backend readiness/live infrastructure evidence.
   - Current judgment: good for merchant-first copy, but it undersells “what is real now”.
   - Next cleanup: add a small trust/status section showing official read-only packet, source records, AI CEO outputs, and confirmation boundary without exposing internals.

5. Temporary trycloudflare URL is not production-grade.
   - Current judgment: fine for staging, not for paid SaaS.
   - Next cleanup: stable domain, TLS, DNS, callback URL, CORS origin alignment, and ICP/domain decision.

6. Demo-session audit creates/uses a separate empty company.
   - Current judgment: okay for endpoint auth checks, but not good for showing real staging data.
   - Next cleanup: create a controlled staging merchant account/session that can view the real packet/report/confirmation evidence without using “demo” semantics.

7. Local precloud gate still reports local Windows Docker/dependency blockers while staging itself has the runtime dependencies.
   - Current judgment: not a staging blocker.
   - Next cleanup: make local gate distinguish local workstation blockers from deployed staging blockers more clearly.

## 7. Current Website State

### Homepage

- Current state: product-style homepage is live.
- Direction: white, trustworthy, merchant-facing SaaS style.
- Public visible Hermes: none found.
- Public visible demo/mock words: none found in first public audit.
- Strong points:
  - eBay-first positioning is clear.
  - AI/human confirmation boundary is visible.
  - Homepage has interactive onboarding path and workbench preview entry.
- Weak points:
  - Homepage does not yet clearly show “current staging is backed by real official read-only packet / reports / confirmations”.
  - It still feels partly like product introduction, not yet a final commercial landing page with proof/status, plan limits, and onboarding-to-activation metrics.

### Onboarding

- Current state: present and interactive.
- Strong points:
  - Seller paths exist: beginner, opened store, orders, multi-store.
  - It explains that risky actions need human confirmation.
- Weak points:
  - Not yet a complete production onboarding flow from merchant registration to eBay authorization to first sync to first AI CEO task.
  - Needs clearer error handling when authorization/sync/data packet is missing or stale.

### Logged-in Workbench

- Current state: product workbench exists and public route loads.
- Strong points:
  - Reads backend endpoints when authenticated.
  - Shows AI CEO, source/data packet concepts, reports, confirmation center, disabled write boundary.
  - No visible Hermes found in browser audit.
- Weak points:
  - Unauthenticated public workbench still triggers expected 401 console errors. This is not a backend bug, but should be made quieter in UI by not firing authenticated calls before login.
  - A small demo word residue remains visible.
  - Demo-session points to a separate empty company, so direct authenticated endpoint checks show no stores/data packets/reports for that demo company while readiness proves the real official packet exists elsewhere.

## 8. Backend and Runtime State

### SaaS Backend

- User/team/store/task/report/confirmation/audit/queue boundaries exist.
- P0 security guardrails pass.
- CORS is guarded.
- OAuth state/callback and token handling boundaries exist.
- Access logs are safe and avoid bodies/tokens.
- Database adapter and queue adapter contracts exist.
- Managed Postgres and Redis runtime status are now visible on staging.

### eBay Read-Only

- OAuth callback already completed.
- Official read-only sync already completed.
- Six-resource official packet exists.
- Standard data packet is sanitized and safe for Runtime/report use.
- Real writes remain false.

### Standard Data Packet

- Current packet includes all six target resources.
- No missing resource keys.
- Packet metadata includes source mode and safety information.
- Still should improve route freshness, retry visibility, packet versioning, and merchant-facing “stale data” warnings.

### Jiejing Runtime / Agents

- Seven commerce roles exist and report contracts pass gates.
- Runtime is independent from Hermes as the default product path.
- Provider jobs and execution boundaries exist.
- Current limitation: output quality is still not fully proven with a live model provider over real sanitized packets.
- Current hard blocker: `model_value_proof`.

## 9. Current Progress Percentages

These are product-readiness estimates, not just code-completion estimates.

| Module | Current % | Judgment |
|---|---:|---|
| SaaS homepage | 88% | Public product direction is good; needs stronger real-proof/status section and final commercial polish. |
| Onboarding | 78% | Interactive path exists; needs full merchant registration -> eBay authorize -> first sync -> first task activation flow. |
| Logged-in workbench | 88% | Reads real backend routes; still needs quieter unauthenticated behavior and removal of remaining demo residue. |
| SaaS backend skeleton | 95% | Core tenancy, auth, stores, reports, confirmations, audits, queue, readiness are strong. |
| eBay read-only real chain | 98%-99% | OAuth, secret_ref boundary, official packet, six resources are complete; do not repeat. |
| Standard data packet | 96% | Six-resource packet exists; needs freshness/retry/version UX. |
| Jiejing Runtime / Agents | 83% | Owned roles and contracts exist; live model value not yet proven. |
| Provider jobs | 70% | Contracts and eBay/public-search boundaries are good; sourcing/logistics/media/model still need production adapters. |
| Tencent cloud staging | 86% | Postgres/Redis/SSM/KMS/CLS/COS are connected; cleanup/fallback simplification remains. |
| Production infrastructure | 78% | Managed infra is mostly in place; stable domain, production deploy discipline, billing provider, long-run monitoring still remain. |
| Paid commercial SaaS readiness | 64%-66% | Real staging proof exists, but paid launch still blocked by model value proof, external billing, domain, and merchant beta validation. |

## 10. Current Blockers

### Hard blocker

1. `model_value_proof`
   - No live model provider key is configured.
   - Market Report and Listing Package cannot truthfully be claimed as live-model-proven.
   - Next action: configure model provider, run controlled model-backed reports over sanitized official packet, review quality, persist evidence.

### Paid-launch blockers

1. External billing provider not configured.
   - Current billing is `manual_seed`, good for private beta quota control only.
   - Need Stripe, Paddle, or Lemon Squeezy plan IDs and signed webhooks before charging.

2. Stable production domain missing.
   - Current trycloudflare URL is staging only.
   - Need stable domain/TLS/eBay callback/CORS alignment.

3. Merchant beta proof missing.
   - Need a real merchant-style run: login -> connect/read eBay -> official packet -> AI CEO reports -> confirmation center -> user understands value.

4. Long-run operations proof incomplete.
   - Need scheduled backup/restore drill, CLS alert verification, queue-depth alert, OAuth/token expiry alert, and cost monitoring over time.

## 11. Next Work Order

Do not go back to demo-page stacking. The next work should be:

1. Model value proof
   - Configure model provider key safely through SSM/KMS.
   - Run live Market Report and Listing Package over `packet_5c69bcc5bf0e79ae`.
   - Persist evidence in reports/model-value gate.
   - Add cost/timeouts and no-token leak checks.

2. Product workbench cleanup
   - Suppress authenticated calls before login.
   - Remove visible demo residue.
   - Add real-data status panel: official packet, six resources, reports, confirmations, freshness.
   - Make demo-session no longer the main way to view staging proof.

3. Cloud cleanup
   - Confirm all secrets resolve from Tencent SSM.
   - Remove/pause HashiCorp Vault container if no secret refs depend on it.
   - Simplify SQLite-looking CLI args in staging compose.
   - Keep Postgres/Redis as selected production-shaped runtime.

4. Paid SaaS preparation
   - Choose billing provider.
   - Stable domain/TLS/CORS/eBay callback.
   - Monitoring alert tests.
   - Backup restore drill schedule.
   - Seed merchant beta validation.

## 12. Anti-Repeat Rules For Next Window

- Do not open a new eBay authorization URL unless readiness says the official packet/connection is missing or stale.
- Do not run a new official eBay sync merely to check progress.
- Do not claim paid launch readiness while `model_value_proof` and external billing remain incomplete.
- Do not turn on real platform writes.
- Do not expose Hermes in public product copy.
- Use `agentuser@42.194.158.47` first for staging work.
- Treat Tencent browser login/QR as fallback only.

## 13. Evidence Artifacts

- Current status doc: `docs/JIEJING_STAGING_STATUS_20260519.md`
- This handoff: `docs/JIEJING_GLOBAL_AUDIT_HANDOFF_20260519.md`
- New-window prompt: `docs/JIEJING_NEW_WINDOW_PROMPT_20260519.md`
- Public UI audit output: `output/jiejing-global-audit-20260519/public_staging_ui_audit.json`
- Precloud gate output: `output/jiejing-precloud-deployment-gate/latest.json`
- Infrastructure stage gate output: `output/jiejing-infrastructure-stage-gate/latest.json`

## 14. Tencent Cloud Product Fit References

- TencentDB for PostgreSQL is appropriate for managed relational data, backup, restoration, monitoring, and high availability.
- TencentDB for Redis is appropriate for Redis-compatible queue/cache scenarios.
- Tencent SSM/KMS is appropriate for removing hardcoded secrets and retrieving encrypted credentials through API calls.
- COS is appropriate for low-cost object backup storage.
- CLS is appropriate for log collection, retrieval, monitoring, and alerting.

