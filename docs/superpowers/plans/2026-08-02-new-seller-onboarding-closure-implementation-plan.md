# New Seller Onboarding Closure Implementation Plan

## Status and objective

Approved design: `docs/superpowers/specs/2026-08-02-new-seller-onboarding-closure-design.md`.

This plan completes the existing Jiejing `newbie` / “新店起步” route as one durable, evidence-led onboarding flow. It adds company-scoped progress persistence, derives one safe next action from current eBay connection/account-health evidence, and keeps draft work available while all real eBay writes and public charging stay blocked.

Current live calibration on 2026-08-02 already shows an authorized current eBay connection and one refresh proof. Implementation and tests must reuse that truth and must not start OAuth, read live secrets, call eBay, deploy, charge, refund or perform a real platform write.

## Non-negotiable constraints

- Preserve the current worktree; do not reset, clean, checkout, stash, broad-format or touch `.superpowers/`.
- Extend the existing homepage guide and workbench onboarding surfaces. Do not add a second onboarding product.
- Treat merchant answers as intent only. Backend evidence exclusively derives `effective_stage`.
- Store no eBay password, OAuth code/token, identity document, address detail, bank/payment data, Cookie, raw URL or third-party page content.
- Scope every read/write by authenticated `company_id`; require `manage_connections` for progress mutation.
- An authorized current connection must never route to repeat OAuth. Missing/invalid connection is the only authorization state.
- `draft_only` must not change publish, billing, quota, OAuth or execution gates.
- Business policy readiness requires all three IDs: fulfillment, payment and return.
- Keep `ready_for_paid_commercial_launch=false`, `public_charging_allowed=false`, and real platform writes disabled unless external evidence changes through separate approved work.

## Phase 0: allowed APIs and copy sources

Use these existing repository and API patterns:

- `jiejing_saas/repository.py:161-179` — SQLite table declaration style.
- `jiejing_saas/repository.py:652-769` — schema migration recording during initialization.
- `jiejing_saas/repository.py:4247-4338` — sanitized tenant upsert/get plus audit pattern.
- `jiejing_saas/migrations/001_initial_schema_postgres.sql:39-48` — PostgreSQL JSONB/timestamp table style.
- `jiejing_saas/migrations/001_initial_schema_postgres.sql:527-593` — production index declarations.
- `jiejing_saas/api_server.py:1176-1265` — public GET routing followed by authentication boundary.
- `jiejing_saas/api_server.py:1819-1836` — tenant-scoped `account-health` composition.
- `jiejing_saas/api_server.py:2520-2600` — authenticated POST routing and explicit HTTP conflict response.
- `jiejing_saas/api_server.py:6535-6540` — role/permission enforcement.
- `jiejing_saas/permissions.py:8-55` — existing `manage_connections` permission contract.
- `jiejing_saas/account_health.py:95-159` and `:480-487` — account health evidence and onboarding stage mapping.
- `app.js:17470-17617` — current authorized-connection status and preferred-store helpers.
- `app.js:17426-17450` — strict eBay authorization URL allowlist.
- `index.html:5818-5825` and `:6163-6169` — legacy local completion marker and current finish behavior to replace safely.
- `tools/test_jiejing_platform_trial_activation_guard.py` — real HTTP server behavior-test harness.
- `tools/test_jiejing_postgres_repository_cutover.py:136-143` — PostgreSQL migration contract checks.

Allowed frontend transport:

- Homepage authenticated requests use same-origin `fetch(..., {credentials: "include"})` as `index.html:5950-5958`.
- Workbench requests use `saasFetch()` / `saasFetchWithTimeout()` at `app.js:16310-16420`.
- Official seller registration URL is a fixed constant: `https://www.ebay.com/sl/sell`, opened with `noopener,noreferrer`.

Prohibited patterns:

- No client-supplied `company_id`, `effective_stage`, `verified`, `connection_current` or arbitrary external URL.
- No free-form answers, HTML persistence, `eval`, string event handlers, unvalidated navigation or secrets in web storage.
- No hidden OAuth/sync inside progress persistence.
- No “onboarding complete” inference from localStorage, focus events, store subscription or a returned browser tab.
- No direct SQL from frontend tests and no test that requires a real eBay/Cloudflare/payment account.

## Phase 1: state machine tracer bullet

### Files

- Add `jiejing_saas/merchant_onboarding.py`.
- Add `tools/test_jiejing_merchant_onboarding_state.py`.

### RED → GREEN slices

1. Default no-record/no-connection state returns `seller_registration_required`, no verified claim and no real action.
2. `seller_returned=true` with no current connection returns `authorization_required`.
3. Any current authorized connection suppresses authorization and routes to read-only/account-health evidence.
4. `registration_incomplete` overrides saved intent and routes back to registration with `oauth_required=false`.
5. Restricted/unknown health routes to `account_review_required`.
6. Normal health with one or more policy IDs missing routes to `business_policies_required`.
7. Normal health plus all three policies routes to `ready_for_publish_preflight`, never direct publish.
8. Input normalization rejects unknown path/step/answer/value, overly long input and secret-like keys.

### Verification

```powershell
python tools/test_jiejing_merchant_onboarding_state.py
```

## Phase 2: tenant persistence and authenticated API

### Files

- Modify `jiejing_saas/repository.py`.
- Modify `jiejing_saas/migrations/001_initial_schema_postgres.sql`.
- Modify `jiejing_saas/api_server.py`.
- Extend `tools/test_jiejing_merchant_onboarding_state.py` with repository and HTTP behavior.
- Extend `tools/test_jiejing_postgres_repository_cutover.py`.
- Modify `tools/jiejing_precloud_deployment_gate.py` to include the focused onboarding check.

### RED → GREEN slices

1. Repository returns no record for a new company, then saves and restores an enum-only record without a store.
2. Optimistic `expected_version` mismatch returns a typed conflict without overwriting newer data.
3. Saved progress is isolated by `company_id`; a second company receives its own default state.
4. Audit records only stage/path/mode booleans and safe step keys, never raw answers or identity data.
5. GET `/merchant-onboarding/primary-ebay` requires authentication and derives current state from the company’s preferred eBay store, current connections and account health.
6. POST `/merchant-onboarding/primary-ebay/progress` requires authentication plus `manage_connections`, rejects forged derived fields, handles `400/403/409`, and returns the current safe read model.
7. First matching eBay store may bind an unbound company record; a foreign store can never be bound.
8. PostgreSQL schema contains the table, composite tenant key, JSONB columns, index and migration marker.

### Verification

```powershell
python tools/test_jiejing_merchant_onboarding_state.py
python tools/test_jiejing_postgres_repository_cutover.py
```

## Phase 3: homepage guide continuity

### Files

- Modify `index.html` only; preserve the current visual system and existing guide data.
- Extend `tools/test_jiejing_registration_challenge_ui.py` or add focused static checks to `tools/test_jiejing_merchant_onboarding_state.py`.

### RED → GREEN slices

1. Logged-in guide loads server progress before rendering saved step/path/answers.
2. Selecting “还没注册 eBay 卖家账号” shows the fixed official registration button in that same step.
3. Opening the official page saves progress first and uses a fixed allowlisted URL with `noopener,noreferrer`.
4. Window focus after external navigation displays “欢迎回来” without marking seller verification complete.
5. “我已完成 eBay 页面，继续检查” only persists `seller_returned=true`.
6. Step changes save with a bounded debounce; save failure shows “进度暂未同步” and keeps local choices.
7. “保存并进入工作舱” persists `draft_only` and no longer marks eBay readiness complete.
8. Legacy local `done/path` migrate only when the backend has no record; `done=1` maps to saved preferences, never verified seller status.

### Verification

```powershell
python tools/test_jiejing_merchant_onboarding_state.py
python tools/test_jiejing_registration_challenge_ui.py
```

## Phase 4: workbench single-source rendering

### Files

- Modify `app.js` and minimal supporting styles in `styles.css` only if existing classes cannot express the states.
- Extend `tools/test_jiejing_product_grade_journey_contract.py` and/or the focused onboarding test.

### RED → GREEN slices

1. Protected state refresh loads `/merchant-onboarding/primary-ebay` into one `state.saasMerchantOnboarding` object.
2. The existing “新店起步” panel displays the server-derived stage, one merchant-language next action and draft-only status.
3. Authorized current connection plus registration-incomplete health never renders a repeat OAuth action.
4. Policy step shows payment, fulfillment and return separately and stays blocked when any is missing.
5. Ready state says “进入发布体检”; no copy claims auto-publish or paid-launch readiness.
6. No provider, secret, packet, token, internal console or Hermes detail appears in merchant-facing onboarding.

### Verification

```powershell
node --check app.js
python tools/test_jiejing_merchant_onboarding_state.py
python tools/test_jiejing_product_grade_journey_contract.py
```

## Phase 5: rendered QA and full release gate

The flow under test is: existing Jiejing onboarding → choose “还没注册” → see/open official eBay seller registration → return to the same step → persist “returned” without false verification → enter draft-only workbench with the correct server-derived next action.

Use the available Browser plugin first according to `build-web-apps:frontend-testing-debugging`. Validate desktop and mobile page identity, meaningful content, no framework overlay, console health, screenshot evidence and at least one interaction state change. Use only local/test data and do not navigate into real OAuth.

Then run:

```powershell
python tools/test_jiejing_merchant_onboarding_state.py
python tools/test_jiejing_postgres_repository_cutover.py
python tools/test_jiejing_product_grade_journey_contract.py
python tools/test_jiejing_registration_challenge_ui.py
node --check app.js
python tools/jiejing_secret_scan.py
python tools/jiejing_precloud_deployment_gate.py
```

Final anti-pattern scan:

- No raw secrets or secret-like onboarding fields.
- No arbitrary external URLs, `javascript:` navigation, string event handlers or new unsafe HTML from network/storage values.
- No OAuth, eBay sync, payment or real-write call inside progress GET/POST.
- No cross-company table read/write without `company_id`.
- No changed commercial progress, `production_ready`, `public_charging_allowed` or real-write flags.

## Completion output

- Commit implementation and tests as scoped code-only changes.
- Report local test/gate evidence and rendered QA evidence.
- Do not deploy automatically. Deployment remains a separate approved production-adjacent action.
- Keep external blockers honest: current public readiness and eBay/account-policy evidence are not changed merely by completing code.
