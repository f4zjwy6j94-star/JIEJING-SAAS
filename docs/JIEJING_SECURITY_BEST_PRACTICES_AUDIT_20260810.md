# JIEJING security best-practices audit — 2026-08-10

## Outcome

No Critical issue was confirmed. Four production-adjacent weaknesses were reproduced with test-only fixtures and fixed in this change set:

1. High — account BYOK request-time model endpoint override could bypass the reviewed provider-host boundary.
2. Medium — staging/production auth responses exposed a browser-readable bearer token in addition to the `HttpOnly` cookie.
3. Medium — cookie-authenticated POST requests did not enforce a production-like Origin boundary.
4. Low — the `Secure` cookie attribute depended on proxy/browser HTTPS hints instead of the environment contract.

The fixes do not enable eBay writes, external payment calls, public charging, refunds, advertising, procurement or paid launch.

## Scope and assumptions

- Internet-facing edge and vanilla JavaScript merchant UI.
- Python standard-library HTTP API, PostgreSQL/Redis production adapters, background worker and root-pinned deployment guard.
- Multi-tenant merchant data keyed by `company_id`; merchant BYOK and platform/eBay/payment credentials remain backend-only.
- Anonymous attacker, ordinary tenant, malicious tenant, stolen browser session and malicious public web content are in scope.
- Host/cloud administrator compromise and dependency-registry compromise are outside the code review scope.

## Evidence reviewed

- Authentication, session revocation, account enumeration, rate limiting and operations-console isolation.
- Tenant-scoped model settings, merchant cache isolation and repository query construction.
- Billing checkout/portal URL pinning, signed webhooks, idempotency, subscriptions, quota and domestic payment/refund gates.
- eBay OAuth state/token vault, read adapter, write adapter, draft-save gate and marketplace deletion callback.
- Public CSP/security headers, trusted HTML rendering, AI-answer escaping and clean Settings/Listing UI contracts.
- Runtime environment ownership guard, deployment Doctor/dry-run/apply boundaries and secret scan.

## Fixed controls

### BYOK outbound request boundary

`jiejing_saas/api_server.py` now validates the stored model URL against the selected provider's reviewed HTTPS host and requires any request-body override to be exactly identical. Validation happens before secret resolution and before client construction. Rejections expose neither endpoint, secret reference nor secret value.

### Browser session boundary

Production-like auth responses use a shared response helper that omits the bearer token. Cookies are `HttpOnly`, `SameSite`, and unconditionally `Secure` in staging/production. Local/test compatibility remains available without changing the public contract.

The paid-launch session P1 is now closed in the 2026-08-20 follow-up. Production-like access cookies are capped at 30 minutes and bind to a backend refresh-session family. The refresh cookie is `HttpOnly`, `Secure`, `SameSite=Strict`, scoped to the actual public `/auth` route, rotated atomically, stored only as SHA-256, and revokes the full family on replay. Issuance requires an exact user-company membership; settings exposes only value-free device summaries with exact single-device and revoke-others controls. A same-origin Web Locks guard serializes refresh across browser tabs in both the merchant workbench and isolated operations console, so legitimate concurrent expiry does not look like token theft; only safe reads are replayed. Failed access persistence revokes the newly-created refresh family, and expired family history is lifecycle-bounded. Legacy access cookies without a refresh family cannot refresh and age out within their existing maximum seven-day window.

### Cross-origin mutation boundary

Production-like POST requests with an `Origin` must use HTTPS and match the configured or same-origin host. The check runs before body handling. Non-browser callbacks without an `Origin` remain accepted only subject to their existing route-specific signature or authentication controls.

## Controls that passed

- SQL values use bound parameters; reviewed dynamic identifiers/clauses come from fixed code-owned sets or boolean branches.
- No confirmed cross-tenant IDOR in the reviewed merchant, model, billing, eBay or operations paths.
- Public model/search text is escaped before HTML insertion; AI markdown rendering escapes first and adds only bounded formatting tags.
- Billing return URLs must match configured safe URLs; public charging and real payment/refund calls remain disabled.
- Real eBay writes remain confirmation-gated and disabled in public staging.
- Exact hash-locked runtime/build dependencies, `pip check`, Python/Node syntax, focused security contracts and repository secret scan pass.

## Open hardening work

| Priority | Item | Current risk and next acceptance gate |
| --- | --- | --- |
| P1 before paid launch | Production application server | `ThreadingHTTPServer` remains a bounded beta implementation. Move to a hardened multi-process server and rerun slow-body/concurrency tests. |
| P2 | Remove public CSP `unsafe-inline` | Existing escaping and CSP still reduce risk, but hashes/nonces or externalized code improve browser defense in depth. |
| P2 | Automated dependency advisory enforcement | Exact hashed runtime/build locks are enforced in CI and deploy. Add an advisory scanner that fails on unresolved High/Critical findings. |
| Operational | Refresh monitoring and backup/restore evidence | Current public readiness warns that evidence is incomplete/stale. Refresh evidence without changing payment/eBay write gates. |

## Release recommendation

The current staging environment can continue controlled beta testing. Keep `production_ready=false`, `can_accept_real_customers=false`, public charging disabled and real platform writes disabled. Do not change the fixed commercial score until the fixed gate has new real-merchant/payment evidence.
