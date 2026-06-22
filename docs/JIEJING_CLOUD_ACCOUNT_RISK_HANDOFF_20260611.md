# Jiejing Cloud Recovery and Account-Risk Handoff - 2026-06-11

This handoff is sanitized. It must not contain passwords, tokens, eBay refresh tokens, model keys, Tencent secrets, database passwords, or OAuth secrets.

## Current Verified State

- Public staging: `https://individually-buffalo-prescribed-blocking.trycloudflare.com`
- `/health` is reachable and reports:
  - `status=ok`
  - `environment=staging`
  - `database_startup_status=ready`
  - `real_platform_writes_enabled=true`
  - `requested_real_platform_writes=true`
  - `secret_exposed=false`
- `/readiness/product-saas` is degraded:
  - `readiness_version=2026-05-24-product-saas-degraded`
  - `status=degraded`
  - `degraded_reason=database_unavailable`
  - `database_error_type=OperationalError`
  - `production_ready=false`
  - `beta_ready=false`
  - `can_accept_real_customers=false`
  - blocker: `database_reachability`
- Remote app host is reachable through SSH using the current route-A channel:
  - host: `43.129.205.244`
  - user: `ubuntu`
  - app path: `/opt/jiejing-staging/app`
- Remote containers:
  - frontend: running
  - saas backend: running
  - vault: running
  - worker: restarting
- Worker restart root cause:
  - Postgres repository initialization fails because `hk-postgres-b6chkvaj.sql.tencentcdb.com` does not resolve.
  - Host DNS works for other domains, so this points to the old TencentDB PostgreSQL instance being offline, released, or not restored, not a general server DNS outage.
- Queue env has cleanup debt:
  - Private env contains both old `JIEJING_QUEUE_PROVIDER=redis_streams` and later `JIEJING_QUEUE_PROVIDER=local_worker`.
  - Container resolves to `local_worker`, but the stale Redis line should be cleaned after database recovery.
- Backup created on server:
  - `/opt/jiejing-staging/backups/cloud-recovery-20260611T145739Z`
  - Contains `app-and-private-config.tar.gz`, `SHA256SUMS`, and `recovery-diagnostics-sanitized.txt`.
  - This is a server-side config/code backup, not a fresh database dump.
- Fresh Postgres backup could not be created because the managed Postgres endpoint is unreachable.
- Older visible backup:
  - `/opt/jiejing-staging/app/output/restore-drills/20260519-144746/staging-postgres.dump`
  - This may be stale and must not be treated as the current production dataset without checking recovery requirements.

## Code Change Completed In This Recovery Pass

- Added account-health gating to `jiejing_runtime/execution_preflight.py`.
- `publish_listing` now requires `account_health.status`.
- If account health shows frozen, restricted, suspended, limited, held, payout hold, or unverified states, preflight blocks real publish before the platform adapter.
- Added regression test:
  - `tools/test_jiejing_account_health_preflight.py`
- Updated existing publish-boundary regression data to include a healthy account snapshot.

Validated locally:

```text
python -m py_compile jiejing_runtime\execution_preflight.py tools\test_jiejing_account_health_preflight.py
python tools\test_jiejing_account_health_preflight.py
python tools\test_jiejing_ebay_write_adapter.py
python tools\jiejing_productization_stage_gate.py
```

All commands above passed.

## eBay Account Freeze Risk

The merchant account screenshot shows eBay payout/account freeze symptoms. Do not assume Jiejing caused it without timeline evidence.

Product implication: Jiejing must treat account-health risk as a P0 safety boundary before paid beta.

Add an `Account Health / Seller Risk Center` capability:

- Read-only account status monitor:
  - restrictions
  - payout holds
  - selling limits
  - seller level
  - unresolved cases
  - policy warnings
  - verification status
  - business policy availability
- Pre-publish account health gate:
  - if account is restricted, frozen, payment-held, or limit-blocked, block publish, ads, inventory writes, price changes, policy edits, and sensitive customer promises.
  - allow read-only diagnosis and appeal/evidence packet generation.
- Incident mode:
  - stop all real platform writes for that store.
  - snapshot recent Jiejing actions, confirmations, execution results, reports, and source records.
  - separate Jiejing-initiated actions from seller/manual actions.
  - generate appeal/remediation packet, but do not promise outcome.
- Liability and trust boundary:
  - Jiejing must not guarantee that eBay will not restrict a seller.
  - Jiejing must show source, risk, confirmation, and audit trail before high-risk actions.
  - Merchant remains responsible for product truth, supplier legitimacy, IP rights, fulfillment accuracy, and policy compliance.

## Current Honest Progress

Because the database is currently degraded, live readiness is lower than the last good staging state:

- Private/internal test readiness: about 70%
- Beta invite readiness: about 58-62%
- Public paid launch readiness: about 48-52%

If TencentDB Postgres is restored, staging readiness can recover toward the previous range, but it is still not public paid-launch ready until billing, production queue, stable domain, monitoring, backup drills, and commercial smoke are complete.

## Immediate Next Steps

1. Restore TencentDB PostgreSQL or create a replacement managed Postgres instance.
2. Confirm the new endpoint resolves from `43.129.205.244`.
3. Update backend private env to the restored/replacement database endpoint inside the secret boundary.
4. Restart backend and worker.
5. Recheck `/health` and `/readiness/product-saas`.
6. Run a fresh database backup after connectivity is restored.
7. Clean stale Redis queue env lines and keep queue provider explicit.
8. Resume production queue hardening:
   - retry
   - dead letter
   - timeout recovery
   - worker heartbeat
   - stuck job recovery
   - visible failed-job panel
9. Add account-health gate and seller-risk center before more real publish testing.
10. Only after database and worker are healthy, run full end-to-end smoke.

Current blocker for step 1:

- No local `tccli` / Tencent Cloud CLI credentials were found.
- No remote Tencent CLI credentials were found under the SSH user.
- Chrome control could not attach to the already-open Tencent console because the local Chrome plugin runtime failed with a missing asset-path error.
- Therefore, this pass could not safely perform console-level paid restore/new-instance operations.

## Migration Prompt for Claude Code

You are reviewing the Jiejing project as a senior SaaS/backend/e-commerce safety auditor. Do not edit code first; produce findings, then propose changes.

Project path:

```text
C:\Users\57249\Documents\Codex\2026-04-29\hermes-agents\software-demo
```

Product direction:

Jiejing is an eBay-first AI CEO SaaS for cross-border sellers. It is not a generic ERP, not a generic agent marketplace, and not a normal chatbot. The core loop is:

```text
merchant text command -> backend agents -> market research / batch sourcing / IP risk screening
-> Listing package -> asset workshop -> customer-service learning
-> finance/fulfillment/fees -> confirmation center -> execution
-> report / source / memory / audit back to AI CEO
```

Hard safety rules:

- Do not print, read aloud, copy, or persist secrets, passwords, tokens, eBay refresh tokens, model keys, database passwords, or Tencent secrets.
- Do not repeat eBay OAuth unless a current authenticated check proves authorization is invalid.
- Do not ask the user to reconfigure model keys unless provider authentication failure is proven.
- BYOK and eBay tokens must remain inside backend secret boundaries.
- Real publish, procurement payment, price change, inventory change, refund, ad budget, policy change, and sensitive customer-service promise must go through the confirmation center.
- Do not use old mock products as real store data.
- Merchant-visible reports must be Chinese except proper nouns like eBay, SKU, Listing, Market Report.

Current verified status on 2026-06-11:

- Public staging `/health` is reachable and reports `status=ok`, `database_startup_status=ready`, `real_platform_writes_enabled=true`, `secret_exposed=false`.
- `/readiness/product-saas` is degraded with `degraded_reason=database_unavailable`, `database_error_type=OperationalError`, `production_ready=false`, `beta_ready=false`, `can_accept_real_customers=false`.
- Remote app host: `43.129.205.244`, user `ubuntu`, app path `/opt/jiejing-staging/app`.
- Remote worker is restarting because Postgres host `hk-postgres-b6chkvaj.sql.tencentcdb.com` no longer resolves.
- This likely means the old TencentDB PostgreSQL instance is offline/released/not restored.
- A server-side backup was created at `/opt/jiejing-staging/backups/cloud-recovery-20260611T145739Z`.
- Fresh DB backup was impossible because DB endpoint is unreachable.
- Queue env has stale duplicate provider lines; container resolves `local_worker`, but old Redis env should be cleaned after DB recovery.

Audit priorities:

1. Restore or replace managed Postgres, then backup.
2. Verify backend/worker/readiness after DB recovery.
3. Add account-health/seller-risk gate so Jiejing blocks writes when eBay account is restricted/frozen/held/limit-blocked.
4. Finish production queue: retry, dead letter, timeout recovery, worker heartbeat, stuck-job recovery, failed-job visibility.
5. Add explicit pre-publish safety report: category, item specifics, images, VeRO/IP, prohibited terms, GPSR, inventory location, business policies, seller limits, expected fees, profit.
6. Ensure decision center is the only path for high-risk actions.
7. Ensure AI CEO routes normal chat, eBay workflow, realtime search, and high-risk actions clearly.
8. Ensure eBay sync visibility shows store name, product/offer/order/policy counts, packet ID, and last sync time.
9. Ensure commercial launch blockers stay honest: billing provider, stable domain/DNS/TLS, monitoring/alerts, backups, incident runbook, final commercial smoke.

Return:

- P0/P1/P2 findings with file paths and line references.
- What must be fixed before private test, beta invite, and public paid launch.
- A realistic progress percentage.
- Do not include any secret values.
