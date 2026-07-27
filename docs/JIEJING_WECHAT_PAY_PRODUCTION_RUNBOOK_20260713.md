# JIEJING WeChat Pay Production Runbook

Date: 2026-07-13

## Purpose

This runbook controls the first mainland merchant-payment launch for JIEJING.
It covers one-time 30-day WeChat Pay Native plan orders. It does not authorize
automatic renewal, automatic refunds, public eBay writes, or any other money
movement.

## Deployment Modes

1. **Rehearsal**: no provider order, no payable QR, no charge.
2. **Controlled acceptance**: one owner-approved acceptance order through the
   backend-only tool. This proves the real provider lifecycle but does not open
   public checkout.
3. **Public charging**: production-only merchant checkout after every launch
   gate and the owner approval packet are complete.

The public charge gate requires all of these conditions at the same time:

- all required WeChat merchant credentials and verification material are
  present in backend Vault/env;
- live provider API access is enabled;
- the signed refund callback and approved-refund execution path are configured;
- `JIEJING_WECHAT_PAY_REFUND_ALLOWED=true` only after a controlled refund proof;
- the deployment environment is `production`;
- the public charge switch is enabled;
- a recorded owner approval packet ID is present.

No single switch is sufficient by itself.

## Preflight

Before public charging is considered:

- run the full payment regression suite and precloud deployment gate;
- run the repository secret scan and confirm no raw payment credential appears
  in source, bundle, logs, browser storage, API responses, or audit details;
- verify `/health`, `/health/deep`, and `/readiness/product-saas` on the exact
  deployment that will receive traffic;
- verify unauthenticated merchant order creation returns `401`;
- verify support, refund policy, privacy, terms, and risk disclosure pages;
- confirm signed callback, authenticated order query, amount mismatch,
  duplicate callback, delayed callback, close-order, refund-state, and
  entitlement tests pass;
- confirm the controlled real-payment evidence is present and sanitized;
- confirm alerting, backup, rollback, and operator ownership are recorded.

## Secret Boundary

Private keys, API v3 keys, merchant certificates, response verification keys,
and other credentials are written only through the backend secret-management
path. Never paste them into frontend settings, source files, deployment bundles,
chat, tickets, screenshots, or audit notes. Public readiness exposes only
presence and verification booleans.

## Cutover

1. Deploy the reviewed build with public charging still disabled.
2. Verify health, readiness, callback reachability, and the non-charge smoke.
3. Record the exact build, database backup, secret scan, rollback packet, and
   controlled acceptance evidence in the owner approval packet.
4. Deploy a dedicated production environment. Do not turn staging into
   production in place.
5. Enable provider live access while keeping the public charge switch disabled;
   verify signed query and callback configuration.
6. After explicit owner approval, enable the public charge switch and attach the
   approval packet ID.
7. Create no operator test charge during cutover. Observe the first real
   customer checkout through normal product telemetry and reconciliation.

## Normal Order Lifecycle

- Create one tenant-scoped order with an idempotency key.
- Create one short-lived Native QR and show only its rendered image.
- Treat browser state as untrusted. Activate quota only after verified callback
  or authenticated provider query.
- Reuse the existing QR for duplicate checkout clicks.
- Close expired or merchant-cancelled unpaid orders.
- Route refund requests to human review. Provider-confirmed full refunds update
  entitlement only after verification.

## Refund Lifecycle

1. A merchant requests a refund review. This creates an account-scoped item in
   the confirmation center and does not call WeChat Pay.
2. An authorized human reviews ownership, policy, amount, entitlement impact,
   and the full-refund boundary.
3. Approval records intent only. A separate protected execution endpoint sends
   the idempotent full-refund request.
4. Signed refund callback or authenticated refund query moves the order through
   `refund_processing`, `refunded`, or `refund_failed`.
5. Entitlement changes only after the verified Provider state is `SUCCESS`.

The refund callback is
`https://app.jiejing.shop/billing/domestic/wechat-pay/refund-notify`. Keep it
reachable after checkout is disabled so in-flight refunds can settle. Never
place the API v3 key, merchant private key, certificate content, or raw callback
payload in browser storage, source, logs, or support messages.

## Incident Actions

### Invalid or repeated callback

- Return a non-success response for invalid signatures or mismatched order data.
- Keep the order and entitlement unchanged.
- Duplicate valid callbacks remain idempotent and must not extend quota twice.

### Merchant paid but entitlement is missing

- Do not ask the merchant to pay again.
- Query the provider order from the authenticated backend path.
- Reconcile only when merchant ID, app ID, order number, amount, currency, and
  success state all match.
- Legacy paid orders that predate the persisted entitlement-window fields may
  derive one bounded window from verified `paid_at + duration_days` evidence.
  This fallback requires the stored provider transaction, verification source,
  merchant/app/amount checks, amount, and currency to remain exact; it never
  extends a newer explicit window and fails closed on any mismatch.

### Payment operations reconciliation

- Use the authenticated company-scoped operations snapshot to identify expired
  unpaid checkouts, verified paid orders that need entitlement recovery, refund
  reviews, and failed refunds.
- Reconcile no more than 10 explicitly selected order IDs in one request.
- Limit payment reconciliation to six authenticated requests per company per
  minute in addition to the shared IP and global high-cost API limits.
- A reconciliation request may perform authenticated order queries, but it must
  never create a charge, initiate a refund, accept a browser payment claim, or
  expose a raw provider response.
- Treat partial success as an expected operator state. Retry only the affected
  order after checking its current state; do not replay the whole batch blindly.
- Keep these diagnostics out of the normal merchant workflow. Merchant-facing
  pages show the current status and one next action; finance and owner roles use
  the protected operations route.

### Scheduled maintenance

- `jiejing-worker` runs a bounded maintenance pass every five minutes when
  `JIEJING_DOMESTIC_BILLING_MAINTENANCE_ENABLED=true`.
- Automatic reconciliation remains query-only. It can recover a missed payment
  callback, restore verified paid entitlement, or query a refund already in
  `refund_processing`.
- Every pass has per-company limits plus a global Provider-query budget
  (`JIEJING_DOMESTIC_BILLING_MAINTENANCE_MAX_QUERIES`, default `50`). Budget
  exhaustion is logged for alerting instead of continuing an unbounded sweep.
- A refund still waiting for human review is never executed by maintenance.
- One tenant or Provider failure is isolated; the worker continues other
  tenants and queue work.
- Logs contain hashed company/order references and event codes only. Critical
  incidents and failed queries set `alert_required=true` for the existing CLS
  alert route.

### Provider unavailable or slow

- Keep the internal order pending and show a retryable merchant-safe state.
- Do not infer payment success from a screenshot, QR scan, redirect, or browser
  timeout.

### Suspected credential exposure

- Disable public charging first.
- Rotate the affected credential in WeChat Pay and backend Vault.
- Invalidate affected provider material, redeploy, rerun callback/query proofs,
  and preserve only sanitized incident evidence.

### Refund dispute

- Keep automatic money movement disabled.
- Verify order ownership, provider transaction, amount, entitlement impact, and
  refund-policy eligibility before a human-approved provider refund.

## Rollback

1. Disable the public charge switch immediately; keep callback and query paths
   available so already-paid orders can finish reconciliation.
2. Close outstanding unpaid provider orders when appropriate.
3. Do not delete paid order, audit, entitlement, or reconciliation records.
4. Roll back application code only after preserving the database and evidence
   packet.
5. Re-run health, readiness, unauthorized access, callback, query, and secret
   checks before reopening checkout.

## Launch Truth

A healthy staging deployment and one successful controlled payment prove the
provider path, not general production readiness. Public charging remains closed
while `/readiness/product-saas` reports `production_ready=false` or
`can_accept_real_customers=false`.
