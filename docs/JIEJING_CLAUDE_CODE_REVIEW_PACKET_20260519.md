# Jiejing SaaS Full Review Packet for Claude Code - 2026-05-19

This packet is for an external code and architecture review. The reviewer should not modify files unless explicitly asked later. The immediate task is read-only review and judgment.

## 1. Project Identity

Project name: Jiejing / 捷境

Product direction:

- Jiejing is an independent product-grade SaaS for cross-border e-commerce sellers.
- The current wedge is eBay-first.
- The product promise is an AI CEO workbench: merchant connects official read-only eBay data, Jiejing converts it into standard data packets, self-owned Jiejing Runtime / Agents generate reports and work records, and high-risk actions remain behind confirmation.
- Hermes is historical/internal reference only. It must not be exposed as the merchant-facing product architecture.
- Public copy should center on Jiejing, AI CEO, work records, source records, standard data packets, and confirmation center.

Critical boundaries:

- Frontend must never receive eBay access tokens, refresh tokens, Tencent credentials, model keys, or raw provider secrets.
- Database should store `secret_ref`, not raw secrets.
- Runtime / Agents must not touch raw tokens. They consume sanitized standard data packets only.
- Real platform writes remain disabled. Publishing, price changes, refunds, ad budgets, procurement payments, business policy changes, and sensitive customer commitments must stop at confirmation.
- Do not repeat eBay OAuth or run another live eBay sync just to check status. Current state already has completed callback and official read-only packet evidence.

## 2. Workspace

Primary repo path:

```text
C:\Users\57249\Documents\Codex\2026-04-29\hermes-agents\software-demo
```

Public staging:

```text
https://mentioned-shake-inter-critical.trycloudflare.com
```

Tencent staging host:

```text
42.194.158.47
```

Known SSH route for deployment/status checks:

```text
ssh -i C:\Users\57249\Documents\Codex\2026-05-15\saas-c-users-57249-documents-codex\ssh\jiejing_staging_ed25519 agentuser@42.194.158.47
```

Remote app path:

```text
/opt/jiejing-staging/app
```

Use the SSH route first. Do not start with Tencent browser login or root SSH unless this known route fails.

## 3. Latest Verified Product State

As of 2026-05-19:

- Public staging is reachable.
- Health endpoint reports staging and real platform writes disabled.
- eBay read-only OAuth callback is complete.
- Official eBay read-only sync is complete.
- Current official packet is `packet_5c69bcc5bf0e79ae`.
- The packet has all six required eBay resource sections:
  - `store_profile`
  - `account_business_policies`
  - `inventory_and_offers`
  - `orders_and_fulfillment`
  - `finances`
  - `taxonomy_listing_metadata`
- Latest product evidence says there are reports and confirmation records derived from official data.
- `production_ready=false`.
- `can_accept_real_customers=false`.
- Main blocker: live model-backed Agent value proof is not complete.
- Paid launch blockers: external billing provider, stable domain/TLS/eBay callback/CORS, merchant beta proof, longer operational validation.

## 4. Current Progress Estimates

These are working estimates, not marketing claims:

| Module | Current estimate | Notes |
|---|---:|---|
| SaaS homepage | 88% | White trustworthy style and public positioning are present; still needs final product-copy polish and stable domain. |
| Onboarding / identity guide | 78% | Has entry path and seller flow, but needs more mature merchant registration -> connect -> sync -> first report guidance. |
| Logged-in workbench | 88% | Reads backend endpoints; still has demo/mock residue and unauthenticated request noise to clean. |
| SaaS backend skeleton | 95% | Users, companies, stores, tasks, queue, reports, confirmations, audit, permission boundary, adapters. |
| eBay read-only real loop | 98-99% | OAuth, secret_ref, official sync, and standard packet proof are complete. |
| Standard data packet | 96% | Six resources present, source gaps zero; freshness/versioning/retry observability can improve. |
| Jiejing Runtime / Agents | 83% | Seven commerce roles and contracts exist, but live model value still needs proof. |
| Provider jobs | 70% | Contracts and boundaries exist; model/media/sourcing/logistics need production adapters. |
| Tencent Cloud staging | 86% | Postgres, Redis, SSM/KMS, CLS, COS are connected; some cleanup remains. |
| Production infrastructure | 78% | Managed resource integration is now real for staging; paid-grade domain/billing/model/ops remain. |
| Paid commercial SaaS readiness | 64-66% | Real staging proof exists, but not yet public paid launch. |

## 5. Tencent Cloud Resource Review

Current architecture is directionally correct:

```text
Lighthouse + Docker + Cloudflare tunnel
  -> Jiejing frontend/backend/worker
  -> TencentDB PostgreSQL
  -> TencentDB Redis
  -> Tencent SSM/KMS
  -> Tencent CLS
  -> Tencent COS
```

Verified resources:

- Lighthouse `lhins-bulffuz3`, public IP `42.194.158.47`, running: current staging host.
- CVM `ins-01hsr6ti`, public IP `159.75.102.10`, running: no evidence current SaaS uses it. Candidate old/extra resource.
- PostgreSQL `postgres-8yuuxdqb`, running: managed SaaS database.
- Redis `crs-bueo6vz7`, running: Redis Streams queue.
- COS bucket `jiejing-staging-backup-1423900563`: backup/restore target.
- CLS logsets/topics include `jiejing-staging` and `jiejing-saas-runtime`: monitoring/log target.
- SSM has four credentials: three `jiejing-staging-secret_*` plus `jiejing-staging-runtime-probe`.
- KMS key exists and backs SSM.
- VPC and CCN are present for private networking.

Potential redundancy / cost issues:

- CVM `ins-01hsr6ti` should be audited before deletion. Snapshot and inspect first; current staging is not using it.
- HashiCorp Vault container still runs in Docker although runtime is selected to Tencent SSM/KMS. Keep as short-term fallback only; later remove after secret_ref resolution stays stable.
- Docker build cache on staging host is large; safe cleanup is build-cache-only, not volume pruning.
- `qcloud_track` CLS/COS resources appear service-generated. Do not delete blindly.
- Host Security and Smart Advisor entries are Tencent safety/advisory surfaces, not Jiejing runtime dependencies.
- Hunyuan image resources appear unused at the moment.

See:

```text
docs/JIEJING_TENCENT_CLOUD_RESOURCE_AUDIT_20260519.md
docs/JIEJING_STAGING_STATUS_20260519.md
docs/JIEJING_GLOBAL_AUDIT_HANDOFF_20260519.md
```

## 6. Core Backend Areas to Review

Review these paths for SaaS correctness, tenant isolation, security, and production readiness:

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

Backend features to inspect:

- Auth/session handling.
- Company/team/store tenant boundaries.
- eBay OAuth callback and read-only connection handling.
- `secret_ref` storage and Tencent SSM/KMS resolver.
- Standard data packet schema and source labeling.
- Report generation and confirmation center contracts.
- Queue adapters and Redis Streams worker.
- Postgres repository cutover and migration contract.
- Backup/restore plan and COS probe.
- CLS safe logging and alert callback.
- Billing/quota contracts and current manual private-beta status.
- Commercial launch gate and model value gate.

## 7. Frontend Areas to Review

Product flow:

```text
homepage -> onboarding/identity guide -> logged-in workbench -> eBay sync/status -> standard packet -> AI CEO report details -> confirmation center
```

Review goals:

- Does the homepage look like a real merchant-facing SaaS, not a demo?
- Is there any visible Hermes/OpenClaw/old internal wording?
- Does onboarding clearly move a seller from identity selection to connect eBay to sync to first work result?
- Does the workbench show real backend state instead of misleading demo data?
- Are source labels clear: official API, source gap, manual sample, stale data?
- Does the sync status explain resource-level success/failure for the six eBay resources?
- Can a merchant understand what the AI CEO produced and why it needs confirmation?
- Are high-risk actions visibly paused behind human confirmation?
- Does unauthenticated state avoid noisy protected endpoint calls?
- Are API bases environment-configurable, not hardcoded for production?

Known frontend issues:

- Some demo/mock residue remains.
- Demo session can point to an empty demo company, while real official packet evidence exists elsewhere in staging DB.
- Unauthenticated workbench may still generate protected endpoint 401 console noise before login.
- Stable domain/CORS/TLS is not final.

## 8. Runtime / Agents to Review

Current Jiejing Agent direction:

- CEO
- Market Manager
- Product Manager
- Asset Manager
- Finance Supply
- Customer Service
- Confirmation Center

Review goals:

- Are the roles appropriate for eBay-first seller operations?
- Are outputs tied to standard packets rather than raw provider calls?
- Do reports cite source records and confidence/missing fields?
- Is the confirmation boundary strict enough?
- Is Hermes truly replaceable/internal, not core public architecture?
- Is live model integration designed safely with cost/timeouts/quota?
- Is the product value claim honest, given live model proof is still blocked?

Known issue:

- Rule-based/template output and dry-run contracts exist, but Market Report and Listing Package still need controlled live model proof over sanitized official packets.

## 9. Suggested Commands for Reviewer

From repo root:

```powershell
cd C:\Users\57249\Documents\Codex\2026-04-29\hermes-agents\software-demo

node --check app.js
python tools\jiejing_productization_stage_gate.py
python tools\jiejing_precloud_deployment_gate.py
python tools\test_jiejing_tencent_cloud_integrations.py
python tools\test_jiejing_managed_infra_readiness_cutover.py
python tools\test_jiejing_billing_quota_guardrail.py
python tools\test_jiejing_public_staging_proxy_contract.py
python tools\test_jiejing_model_value_rehearsal.py
```

Public staging checks:

```powershell
$base='https://mentioned-shake-inter-critical.trycloudflare.com'
Invoke-RestMethod "$base/health"
Invoke-RestMethod "$base/readiness/product-saas"
```

Authenticated checks can use the local demo session endpoint only for contract inspection:

```powershell
$base='https://mentioned-shake-inter-critical.trycloudflare.com'
$session=Invoke-RestMethod -Method Post -Uri "$base/auth/demo-session" -Body '{}' -ContentType 'application/json'
$headers=@{Authorization="Bearer $($session.token)"}
Invoke-RestMethod "$base/infrastructure/drivers" -Headers $headers
Invoke-RestMethod "$base/vault/secret-resolver/status" -Headers $headers
Invoke-RestMethod "$base/backup/plan" -Headers $headers
Invoke-RestMethod "$base/monitoring/status" -Headers $headers
Invoke-RestMethod "$base/commercial/launch-gate" -Headers $headers
Invoke-RestMethod "$base/model/value-gate" -Headers $headers
Invoke-RestMethod "$base/billing/plans" -Headers $headers
```

Do not run:

- New eBay OAuth authorization.
- Fresh eBay official sync just to check status.
- Real platform write tests.
- Destructive Tencent Cloud cleanup.
- Secret dumping commands.

## 10. Specific Review Questions

Please answer these directly:

1. Is the overall architecture appropriate for an eBay-first AI CEO SaaS for merchants?
2. Are the current Tencent Cloud resources enough for staging/private beta, and which resources are likely waste?
3. Is CVM `ins-01hsr6ti` likely unused by Jiejing staging, based on evidence?
4. Is it safe to keep Lighthouse as the staging host for now, or should the app move to CVM/container service?
5. Is Postgres/Redis/SSM/KMS/CLS/COS integration properly represented in code and readiness gates?
6. Are there any places where raw secrets could leak to frontend, database, logs, Runtime, reports, or Claude/agent prompts?
7. Does the frontend still mislead merchants with demo data?
8. Does the product flow clearly show real merchant value: official eBay data -> standard packet -> AI CEO report -> confirmation?
9. Are Jiejing Runtime and Agents designed as an owned product capability rather than a wrapper around Hermes?
10. What is the true paid commercial readiness percentage, and what are the top five blockers?
11. What should be fixed before inviting one real beta merchant?
12. What should be fixed before charging merchants?
13. What should not be built yet because it would be premature or distract from eBay-first value proof?

## 11. Expected Reviewer Output

Please produce:

- Executive verdict.
- Architecture map.
- Current progress percentages by module.
- Findings ranked P0/P1/P2/P3.
- Waste/resource cleanup recommendations.
- Security and secret-boundary review.
- Frontend productization review.
- Runtime/Agents value review.
- Staging/private-beta readiness.
- Paid launch readiness.
- Concrete next 10 tasks in recommended order.

Do not make code changes unless explicitly asked in a separate instruction.

