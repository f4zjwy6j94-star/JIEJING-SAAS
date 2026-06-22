# Jiejing Security / UI / MVP Audit - 2026-05-21

## Product Direction

Jiejing remains an eBay-first AI CEO SaaS for cross-border sellers.

The minimum commercial MVP must stay on this path:

1. Merchant registers and logs in once.
2. Merchant connects official eBay read-only authorization.
3. Jiejing builds an official sanitized eBay data packet.
4. Merchant saves a BYOK model key through the backend secret boundary.
5. Jiejing runs a live model-backed Market Report and Listing Package.
6. High-risk actions stop in the confirmation center.
7. Work records, source records, reports, and merchant memory remain tenant-scoped.

Jiejing should not drift into a generic ERP, generic chatbot, generic Shopify/TikTok clone, or demo-product showcase.

## Current Controlled Staging State

- Public route checked: `https://individually-buffalo-prescribed-blocking.trycloudflare.com`
- Environment: staging
- Demo session bootstrap: disabled
- Real platform writes: disabled
- Hermes model fallback: disabled
- Hermes adapters: disabled
- Database engine: SQLite in cost-saver mode after managed PostgreSQL was isolated for cost control
- Queue provider: local worker in cost-saver mode after managed Redis was destroyed for cost control
- Vault provider: Tencent SSM configured
- eBay live read-only OAuth exchange: enabled
- eBay refresh token in raw app env: not configured
- Model API key in raw app env: not configured

This is a controlled staging environment suitable for low-cost route, auth, UI, and read-only packet checks. It is not currently beta-ready because cost-saver mode intentionally disables production-grade database and queue readiness.

## 2026-05-21 Late Pass

Changes applied and deployed to Hong Kong staging:

1. Removed the public `app.html` direct-start fallback that accepted legacy `localStorage` bearer tokens. The page now only checks `sessionStorage` and deletes the legacy token key.
2. Removed default frontend demo credentials from `app.js`. Public pages do not contain `demo@jiejing.local` or `jiejing-demo-password`.
3. Tightened `/auth/demo-session`: non-local environments require explicit operator credentials even when an operator bootstrap secret is enabled.
4. Updated `deploy/apply-staging-patch.sh` so staging patches automatically include `/opt/jiejing-staging/private/docker-compose.cost-saver-local.yml` when present. This prevents patch deploys from accidentally restoring managed PostgreSQL/Redis while they are stopped for cost.
5. Added `privacy.html` to the public staging bundle and patch whitelist.
6. Removed unused `assets/demo-*` files from the local repo and made the staging patch delete those old public static assets on the server.
7. Fixed the browser route-health smoke so it opens `app.html`, uses local-only test hooks, and verifies the current eBay data sync UI (`saas-merchant-data-panel`) instead of obsolete route-strip selectors.

Deployment evidence:

- Bundle: `output/jiejing-public-staging-bundle/jiejing-public-staging-20260521-154338.zip`
- SHA256: `43841e270a0c09197a735766d2a91daf1db8520a09d1499d83c07a98c390b90b`
- Remote backup: `/opt/jiejing-staging/app/output/staging-patch-backups/20260521-234625`
- Compose files used: `deploy/docker-compose.public-https-staging.yml` plus `/opt/jiejing-staging/private/docker-compose.cost-saver-local.yml`

Post-deploy verification:

- `/health`: 200, `real_platform_writes_enabled=false`
- `/app.html?start=app`: 200 with CSP, XFO, XCTO, Referrer-Policy, Permissions-Policy, `Cache-Control: no-store`
- `/auth/demo-session`: 403
- `/assets/demo-cable-organizer.svg`: 404
- Public browser runtime: `window.JIEJING_TEST_HOOKS=false`
- Remote container env: `JIEJING_DATABASE_ENGINE=sqlite`, `JIEJING_QUEUE_PROVIDER=local_worker`, `JIEJING_ENABLE_REAL_PLATFORM_WRITES=false`, live Postgres/Redis driver probes disabled
- Readiness: `production_ready=false`, `beta_ready=false`, `blocker_count=7`, `model_value_proof=blocked_live_model_value_not_proven`, latest official packet `packet_5c69bcc5bf0e79ae`

Local verification:

- `python -m compileall jiejing_saas jiejing_runtime tools`
- `node --check app.js`
- `node --check tools/jiejing_frontend_route_health_browser_smoke.js`
- `node tools/jiejing_frontend_route_health_browser_smoke.js`
- `python tools/test_jiejing_frontend_staging_config.py`
- `python tools/test_jiejing_staging_patch_apply_contract.py`
- `python tools/test_jiejing_saas_p0_security_guardrails.py`
- `python tools/test_jiejing_saas_backend_mvp.py`
- `python tools/test_jiejing_saas_production_guardrails.py`
- `python tools/test_jiejing_merchant_surface_guard.py`
- `python tools/test_jiejing_public_staging_proxy_contract.py`
- `python tools/test_jiejing_controlled_staging_security_gate.py`
- `python tools/test_jiejing_merchant_byok_model_and_memory.py`
- `python tools/test_jiejing_model_value_rehearsal.py`
- `python tools/test_jiejing_ebay_refresh_secret_readiness.py`

## Issues Fixed In This Pass

### 1. Static assets missed security headers

Problem:
Static HTML/JS routes inherited weaker protection than API routes because location-level cache headers prevented the common nginx security headers from being emitted.

Fix:
Security headers are now explicitly emitted for root, HTML, static assets, health, and API proxy paths:

- `Content-Security-Policy`
- `X-Frame-Options: DENY`
- `X-Content-Type-Options: nosniff`
- `Referrer-Policy: strict-origin-when-cross-origin`
- `Permissions-Policy: geolocation=(), microphone=(), camera=(), payment=()`

Verification:

- `/app.html`: 200 with CSP, XFO, XCTO
- `/app.js`: 200 with CSP, XFO, XCTO
- `/stores` unauthenticated route: protected and still emits security headers

### 2. Direct-IP access still reached edge infrastructure

Problem:
The public IP path was accessible enough to show edge behavior. For staging this is tolerable, but the SaaS should not depend on merchants using direct IP, and production should not expose the origin broadly.

Fix:
The frontend nginx now rejects unexpected Host headers and only allows the known Cloudflare staging hosts plus localhost for internal checks.

Verification:

- Cloudflare route serves the app normally.
- Direct IP path no longer serves the SaaS app; it returns edge failure/security headers instead of the product UI.

Remaining production action:
Firewall the origin so only Cloudflare tunnel/edge and operator SSH can reach it. Host filtering is a useful guard, not a full origin firewall.

### 3. Auth endpoints had no rate limit

Problem:
Register/login/demo-session endpoints had password hashing and session boundaries, but no request throttling.

Fix:
Added in-process staging auth rate limit by email and client IP.

Verification:

- Wrong-password attempts return `429` after the threshold.
- Demo session remains disabled and returns `403`.
- Merchant surface guard still passes.

## Checks Passed

- `python -m py_compile jiejing_saas\api_server.py`
- `python tools\test_jiejing_saas_backend_mvp.py`
- `python tools\test_jiejing_controlled_staging_security_gate.py`
- `python tools\test_jiejing_frontend_staging_config.py`
- `python tools\test_jiejing_staging_patch_apply_contract.py`
- `python tools\test_jiejing_merchant_surface_guard.py`
- Browser smoke: SaaS foundation desktop/mobile
- Browser smoke: account menu, switch account, logout, settings
- Browser smoke: workflow restoration and product navigation
- CORS check: only configured staging origins are allowed
- Protected endpoint check: unauthenticated protected APIs return 401
- Demo-session check: returns 403
- Secret scan: no real token/key leak found in source scan; one contract-version false positive only

## Current Security Assessment

The current architecture has the right SaaS security direction:

- Tenant state is account-scoped.
- Raw eBay refresh token is not exposed to frontend.
- Raw model key is not exposed to frontend.
- BYOK key boundary is represented by `secret_ref`.
- Real platform writes are off.
- High-risk writes are routed to confirmation center.
- CORS is allow-listed.
- Public routes now have security headers.
- Login/register now have basic throttling.

The current environment should be called:

> Controlled staging for real read-only value proof.

It should not be called:

> Production-grade paid SaaS security.

## Remaining Risks

### P0 before any paid merchant

- Prove the live value loop with real merchant login, official eBay packet, BYOK key, live Market Report, live Listing Package, and confirmation center output.
- Keep `real_platform_writes_enabled=false` until the confirmation/write execution service is audited separately.
- Add restore-proof for backups, not just backup-plan metadata.
- Add production monitoring and alerting for auth failures, model failures, report generation, worker backlog, and eBay sync health.
- Finalize production domain/TLS/origin firewall policy.

### P1 before broader beta

- Move browser session token storage from `sessionStorage/localStorage` toward HttpOnly secure cookies or an equivalent hardened session design.
- Tighten CSP by removing `'unsafe-inline'` after inline scripts/styles are refactored.
- Replace in-memory auth rate limit with Redis-backed distributed rate limiting.
- Define log retention and PII minimization rules for account, IP, User-Agent, report, and source-record logs.
- Add tenant-isolation regression tests for every account-scoped API.

### UI / Product Debt

- Authenticated SaaS core is aligned with the eBay-first MVP direction.
- Public/legacy pages still contain old sample/demo traces such as the incense-burner walkthrough and simulated listing language.
- Shopify/TikTok references must remain clearly marked as borrowed UX patterns only, not Jiejing product scope.
- The merchant-facing MVP should default to real status, missing evidence, next action, and confirmation boundaries; it should not show old sample products in the live testing path.

## Next MVP Iteration

1. Clean public landing/onboarding copy so it sells Jiejing's real eBay-first value loop instead of showing legacy demo product flows.
2. Run the real merchant test loop:
   `login -> official eBay read-only packet -> save BYOK key -> live model-backed Market Report + Listing Package -> confirmation center`.
3. Review the generated report quality against model_value_proof:
   source grounding, missing fields, risk notes, listing usability, confirmation items, and merchant memory writeback.
4. Promote only the proven path into the minimum commercial MVP. Everything else stays behind settings, internal tools, or backlog.

## 2026-05-21 Cost-Saver Snapshot Guard

Problem found after the cost-saver switch:

- The runtime is intentionally back on SQLite/local worker to stop paid Postgres/Redis cost.
- Current SQLite does not contain the latest BYOK model value proof or merchant memory rows.
- The observed `output/cost-saver-backups/...` directory was empty, so it could not be used as recovery evidence.

Fix added:

- `tools/jiejing_cost_saver_snapshot.py`
  - exports the active SQLite SaaS DB into `manifest.json`, `schema.sql`, and `tables/*.jsonl`;
  - verifies every table file count and sha256;
  - rejects empty business snapshots, so a schema-only DB cannot be treated as recoverable data;
  - rejects raw provider secret markers such as `api_key`, `access_token`, `refresh_token`, and `client_secret` inside JSON payloads;
  - keeps `real_platform_writes_enabled=false` and `secret_exposed=false`.
- `tools/test_jiejing_cost_saver_snapshot.py`
  - proves non-empty business snapshot export and verification;
  - proves an empty snapshot directory fails;
  - proves a schema-only SQLite DB fails;
  - proves a raw provider key marker is rejected.
- `deploy/apply-staging-patch.sh`
  - now whitelists and compiles the snapshot tool and test so the staging host receives the guard.

Verification:

- `python -m py_compile tools\jiejing_cost_saver_snapshot.py tools\test_jiejing_cost_saver_snapshot.py tools\test_jiejing_staging_patch_apply_contract.py`
- `python tools\test_jiejing_cost_saver_snapshot.py`
- `python tools\test_jiejing_staging_patch_apply_contract.py`
- `python -m compileall jiejing_saas jiejing_runtime tools`
- `python tools\test_jiejing_infra_cutover_rehearsal.py`
- `python tools\test_jiejing_saas_p0_security_guardrails.py`
- `python tools\test_jiejing_frontend_staging_config.py`

Operational rule:

Before stopping, destroying, or switching away from a paid database/queue runtime again, create and verify a cost-saver snapshot. A backup directory without `manifest.json` plus non-empty business table exports is not valid recovery evidence.

Deployment and staging verification:

- Full public bundle created locally: `output/jiejing-public-staging-bundle/jiejing-public-staging-20260521-163155.zip`
  - SHA256: `655f507d169777414484ec06e46c396c2a4af9357fb44e5e5f28259a33af0dd0`
- SSH route was unstable for the 90 MB full bundle, so a minimal deploy patch was generated from the `deploy/apply-staging-patch.sh` whitelist:
  - `output/jiejing-public-staging-bundle/jiejing-staging-minimal-patch-20260521-163953.zip`
  - SHA256: `c0fe17974aba592768fb64c1e080695aaa125f4b57403b45e5e4dd64bd3b6e5d`
- Staging patch applied on the HK host.
  - Remote backup: `/opt/jiejing-staging/app/output/staging-patch-backups/20260522-004715`
  - Compose files used: `deploy/docker-compose.public-https-staging.yml` plus `/opt/jiejing-staging/private/docker-compose.cost-saver-local.yml`
- Remote current SQLite cost-saver snapshot created and verified:
  - `/data/output/cost-saver-snapshots/20260522-005000-after-patch`
  - `table_count=18`
  - `total_rows=508`
  - `business_rows=507`
  - `merchant_memory=0`
  - `secret_exposed=false`
- Public checks after deployment:
  - `/health`: 200, `real_platform_writes_enabled=false`
  - `POST /auth/demo-session`: 403
  - `/assets/demo-cable-organizer.svg`: 404
  - `/readiness`: still `production_ready=false`, `beta_ready=false`, with current blockers around SQLite/local worker/model value proof/backup restore.

## 2026-05-22 Workbench Focus Pass

Problem:

- The authenticated workbench was still too broad for real merchant testing.
- Provider Hub, permissions, IP risk, merchant memory, and model configuration are useful, but they made the daily workbench feel like an internal settings console.
- The public onboarding copy still mentioned running the beginner flow through a fixed incense-burner sample.

Fix:

- The daily merchant workbench now keeps the MVP path focused on:
  - truth/status panel;
  - setup guide;
  - official eBay packet and readiness evidence;
  - merchant operating path;
  - data coverage;
  - AI CEO value output and confirmation center.
- Advanced/configuration panels stay under Settings:
  - Provider Hub;
  - eBay skill packs;
  - source records and credibility;
  - BYOK model provider form;
  - cost/run ledger;
  - permissions;
  - IP risk;
  - merchant memory.
- Homepage/onboarding copy now says real testing uses the merchant's eBay read-only data and merchant materials, not a fixed sample product.
- `tools/test_jiejing_frontend_staging_config.py` now blocks advanced/settings panels from returning to the daily workbench and verifies the homepage copy does not route real testing through a fixed sample product.

Verification:

- `node --check app.js`
- `python tools\test_jiejing_frontend_staging_config.py`
- `python tools\test_jiejing_merchant_surface_guard.py`
- `python tools\test_jiejing_staging_patch_apply_contract.py`
- `node tools\jiejing_frontend_route_health_browser_smoke.js`

Deployment and public verification:

- Minimal staging patch: `output/jiejing-public-staging-bundle/jiejing-staging-minimal-patch-20260521-170216.zip`
  - SHA256: `32315ff7e46ca788afbabbf097d27e220a819da5af74cfe736e1ad7dc866f09b`
- Remote backup: `/opt/jiejing-staging/app/output/staging-patch-backups/20260522-010413`
- Compose files used: `deploy/docker-compose.public-https-staging.yml` plus `/opt/jiejing-staging/private/docker-compose.cost-saver-local.yml`
- Public `/health`: 200, `real_platform_writes_enabled=false`
- Public `POST /auth/demo-session`: 403
- Public homepage contains the new merchant-data wording and no longer contains the old fixed-sample onboarding sentence.
- Public `app.js` check:
  - daily workbench does not call Provider Hub, IP risk, or merchant memory panels;
  - Settings still contains Provider Hub, BYOK model provider, and merchant memory panels.
- Public `/readiness`: `production_ready=false`, `beta_ready=false`, `blocker_count=7`, `model_secret_refs=0`, `merchant_memory=0`, latest official packet `packet_5c69bcc5bf0e79ae`.
