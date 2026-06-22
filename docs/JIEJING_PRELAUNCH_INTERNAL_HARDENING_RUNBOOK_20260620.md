# Jiejing Prelaunch Internal Hardening Runbook

Date: 2026-06-20
Scope: app.jiejing.shop private beta and prelaunch hardening.

This runbook covers internal work that can continue while formal payment cutover
and clean new eBay account validation are intentionally deferred.

## Safety Contract

- Do not create live Stripe Checkout sessions.
- Do not call Stripe live APIs from this runbook.
- Do not start or repeat eBay OAuth.
- Do not execute real eBay platform writes.
- Do not delete smoke data automatically.
- Do not expose raw tokens, passwords, client secrets, payment secrets, or model
  provider keys in frontend, reports, logs, docs, or audit memory.

## Monitoring And Incident Runbooks

Required published runbooks:

- eBay OAuth callback or token resolution failure.
- Vault/KMS secret resolution failure.
- eBay read-only packet or queue sync failure.
- Queue backlog or stuck job.
- Confirmation center backlog.
- Platform write failure or ambiguous marketplace result.
- Billing webhook failure, payment failure, or dispute.
- Backup restore drill overdue or backup provider failure.

Safe logging rules:

- Access logs must not record request bodies.
- Access logs must not record Authorization headers.
- Access logs must not record raw access tokens, refresh tokens, client secrets,
  passwords, webhook secrets, or payment identifiers.

Alert route:

- During private beta, the alert route can be an owner-operated channel.
- Before public paid launch, connect Tencent CLS, Grafana/Prometheus, Sentry, or
  an equivalent provider and record live probe evidence.

## Public Security Evidence

Minimum free-layer evidence to keep recorded:

- Stable HTTPS origin: `https://app.jiejing.shop`.
- DNS and TLS verified.
- Security headers verified: CSP, X-Frame-Options or frame-ancestors,
  X-Content-Type-Options, Referrer-Policy, Permissions-Policy, noindex headers.
- `robots.txt` blocks broad crawling and AI training crawlers.
- Source maps and source/internal paths are blocked from public serving.
- Auth endpoints are rate-limited.
- High-cost API groups are rate-limited.
- Cloudflare or Tencent edge bot/AI crawler controls are enabled where available
  without enabling surprise paid WAF products.

This does not make copying impossible. It raises cost, protects data boundaries,
and reduces casual scraping. Real customer data protection still depends on
authentication, authorization, tenant scoping, secret boundaries, audit logs, and
confirmation-gated high-risk writes.

## Test Data Governance

Policy:

- Smoke data is marked and reported before cleanup.
- Cleanup is not automatic.
- Review is scoped to the current company/tenant only.
- Cross-tenant test data enumeration must not be exposed.
- Deletion tools require owner approval and a retention policy.
- Existing smoke data may remain as evidence for readiness, billing rehearsal,
  browser smoke, and regression history.

Allowed now:

- Count marked smoke users, stores, audit events, billing test events, and pending
  confirmations.
- Display current-company candidates to owner/admin only.
- Record that smoke data is isolated and intentionally retained.

Not allowed now:

- Global tenant scans visible in product UI.
- Automatic deletion of users, stores, reports, tasks, audit logs, or
  confirmations.
- Cleanup of live eBay state without confirmation center approval.

## Current Decision

Formal payment provider cutover and clean eBay account real validation are
deferred. Internal prelaunch hardening remains active. Public paid launch remains
blocked until the external payment, eBay refresh proof, callback, monitoring
provider, restore drill, final no-charge rehearsal, and owner approval evidence
are all green.
