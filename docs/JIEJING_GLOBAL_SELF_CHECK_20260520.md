# Jiejing Global Self Check - 2026-05-20

## Scope

- Reviewed the current eBay-first AI CEO SaaS direction without repeating eBay OAuth.
- Did not rerun official eBay sync.
- Kept Runtime/Agents behind the sanitized packet boundary.
- Kept real platform writes disabled.

## Fixes Applied

1. Removed frontend `document.write` from report export and switched to a Blob URL print flow.
2. Escaped report export titles before inserting them into generated HTML.
3. Added backend API security headers:
   - `X-Content-Type-Options: nosniff`
   - `X-Frame-Options: DENY`
   - `Referrer-Policy: strict-origin-when-cross-origin`
   - `Permissions-Policy: geolocation=(), microphone=(), camera=(), payment=()`
4. Added the same `Permissions-Policy` header to nginx/Caddy staging configs.
5. Hid duplicate upstream security headers in nginx proxy responses.
6. Updated active deploy defaults from retired Guangzhou staging to Hong Kong:
   - host `43.129.205.244`
   - user `ubuntu`
   - public URL `https://individually-buffalo-prescribed-blocking.trycloudflare.com`
7. Updated Route A/staging env examples away from the retired Guangzhou tunnel.
8. Made production startup refusal explicit when repository readiness blocks startup.
9. Made Runtime mock adapter support generated Jiejing task queues without requiring legacy sample source files.
10. Made Runtime MVP/knowledge tests generate a local self-check task queue when output samples are absent.

## Local Verification

All local Jiejing regression scripts passed:

```text
ALL_TESTS_PASSED count=54
```

Also passed:

```text
node --check app.js
python -m compileall jiejing_saas jiejing_runtime tools
```

## Cloud Deployment

Deployed to Hong Kong staging:

```text
host: 43.129.205.244
app_path: /opt/jiejing-staging/app
latest_backup: /opt/jiejing-staging/app/output/staging-patch-backups/20260520-030423
```

No Docker volumes, database data, Vault data, eBay credentials, or model keys were overwritten.

## Cloud Verification

Passed on the active Cloudflare staging route:

```text
https://individually-buffalo-prescribed-blocking.trycloudflare.com/health -> 200
environment=staging
real_platform_writes_enabled=false
```

Readiness remains intentionally blocked for paid/beta launch:

```text
blocker_count=1
warning_count=4
remaining_blocker=model_value_proof
```

Public demo bootstrap remains blocked:

```text
POST /auth/demo-session -> 403
```

Merchant-facing page checks:

```text
public forbidden demo/mock/sample/simulated/Hermes markers = 0
```

Security headers on the HTTPS route:

```text
X-Frame-Options: DENY
X-Content-Type-Options: nosniff
Referrer-Policy: strict-origin-when-cross-origin
Permissions-Policy: geolocation=(), microphone=(), camera=(), payment=()
```

Remote regression checks passed:

```text
python3 tools/test_jiejing_frontend_staging_config.py
python3 tools/test_jiejing_saas_p0_security_guardrails.py
python3 tools/test_jiejing_saas_production_guardrails.py
python3 tools/test_jiejing_runtime_mvp.py
```

## Continued Optimization: Request Body Guard

The backend POST entrypoint now rejects malformed or unsafe JSON request bodies before they reach auth, store, model, report, confirmation, or queue logic.

Added protection:

```text
invalid JSON -> 400 invalid json body
non-object JSON -> 400 json body must be an object
oversized JSON body -> 413 json body too large
```

Verification:

```text
local compileall jiejing_saas tools -> pass
local tools/test_jiejing_saas_backend_mvp.py -> pass
local tools/test_jiejing_saas_p0_security_guardrails.py -> pass
local tools/test_jiejing_*.py -> pass all 54
cloud tools/test_jiejing_saas_backend_mvp.py -> pass
cloud tools/test_jiejing_saas_p0_security_guardrails.py -> pass
cloud tools/test_jiejing_saas_production_guardrails.py -> pass
cloud POST /auth/login with invalid JSON -> 400 invalid json body
cloud POST /auth/demo-session -> 403
cloud /health real_platform_writes_enabled=false
cloud readiness blocker_count=1
```

Cloud deployment backup:

```text
/opt/jiejing-staging/app/output/staging-patch-backups/20260520-031823
```

## Current Architecture Judgment

The architecture is still directionally correct:

```text
merchant browser
-> Jiejing SaaS backend
-> auth/company/store boundary
-> Postgres/Redis/Vault/KMS boundaries
-> sanitized eBay standard packet
-> Jiejing Runtime/Agents
-> reports/work records/source records
-> confirmation center
-> no real platform write unless future backend confirmation contract allows it
```

The current system is suitable for controlled staging flow testing. It is not ready for paid launch because live model-backed Market Report and Listing Package value proof is still the remaining blocker.

## Next Best Task

Run the real flow test with a merchant BYOK model key:

1. Log in as a real SaaS merchant account.
2. Confirm the existing official eBay packet is visible.
3. Save a model provider API key through the BYOK model panel.
4. Generate live model-backed Market Report and Listing Package.
5. Review output quality, source labels, confidence, and confirmation center items.
