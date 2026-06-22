# Jiejing Staging Status - 2026-05-19

This file records the current verified staging state so future work does not repeat OAuth, sync, cloud setup, or deployment actions that are already complete.

## Product Direction

- Jiejing remains an eBay-first AI CEO SaaS for merchants.
- Hermes is historical/internal reference only and must not be exposed as the merchant-facing product.
- Runtime and Agents must consume sanitized standard data packets, never raw eBay tokens.
- Real platform writes remain disabled.

## Verified Staging URL

- Public staging: `https://mentioned-shake-inter-critical.trycloudflare.com`
- Server path: `/opt/jiejing-staging/app`
- SSH path: `agentuser@42.194.158.47`

## Current Verified State

- Public `/health` is reachable.
- eBay OAuth callback and official read-only sync are already complete. Do not repeat authorization unless the current-state guard says the artifact is missing or stale.
- Latest official packet: `packet_5c69bcc5bf0e79ae`
- Latest packet source: `official_api`
- Packet resource coverage: `store_profile`, `account_business_policies`, `inventory_and_offers`, `orders_and_fulfillment`, `finances`, `taxonomy_listing_metadata`
- Missing packet resources: none
- Reports and confirmation records exist in staging.
- Real platform writes: `false`
- Secret exposure checks: `false`

## Tencent Cloud Runtime

- Managed Postgres and Redis are provisioned and the staging runtime reports database/queue readiness.
- Tencent SSM/KMS resolver is deployed and active for runtime secret resolution.
- Tencent CLS is configured for safe access logs and alert callback wiring. Request bodies, Authorization headers, and raw tokens are not logged.
- Tencent COS backup/restore drill has run with sanitized table inventory and COS round-trip verification.

## Billing and Quota

- Staging now has manual-seed billing enabled for private beta control.
- Merchant-visible `/billing/usage` is deployed.
- Quota enforcement is enabled for:
  - connected store creation
  - AI CEO product workflow creation
  - eBay official read sync jobs
  - provider jobs
  - model value rehearsal jobs
- This is not paid public billing. Paid launch still needs Stripe, Paddle, or Lemon Squeezy plan IDs and signed webhooks.

## Remaining Launch Blockers

- `model_value_proof`: no live model provider key is configured, so Market Report and Listing Package cannot truthfully be marked as live-model-proven.
- `billing_quota` remains a paid commercial launch blocker in the commercial launch gate because manual seed is private beta only.

## Anti-Repeat Rules

- Do not open a new eBay authorization URL just to check state.
- Do not run a new eBay official sync just to check progress.
- Do not claim paid commercial launch readiness while model value proof and external billing provider are missing.
- Do not turn on real platform writes.
- Use `agentuser` SSH before any Tencent browser-login fallback.
