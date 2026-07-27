# Jiejing Operations Metering Design

## Goal

Give the internal operator console enough first-party evidence to calculate acquisition, paid revenue, model usage, media supplier cost coverage, and contribution margin without exposing provider identities or collecting merchant content.

## Trust boundaries

- The merchant UI never receives model keys, payment credentials, provider secrets, raw provider responses, or internal supplier names.
- The public analytics endpoint accepts only allowlisted event and page keys. It never stores IP addresses, user-agent strings, raw URLs, query strings, or referrers.
- Browser visitor and session identifiers are random opaque values. The backend stores only a keyed hash.
- Model usage records contain token counts and billing ownership, not prompts, replies, or credentials.
- Media cost records are provider-neutral. Actual/reconciled costs and configured estimates remain separate.
- The operations overview remains restricted to platform internal administrators.

## Data contracts

### Platform analytics event

- event: `page_view`, `pricing_view`, `signup_started`, `signup_completed`, or `login_started`
- page: `landing`, `pricing`, `login`, `register`, or `workbench`
- visitor/session: keyed hashes only
- optional authenticated company/user identifiers
- bounded, sanitized metadata with no free-form URL or browser fields

### Model usage ledger

- provider-neutral model family and model label
- request count and provider-reported input/output/total tokens
- usage owner: merchant BYOK or Jiejing platform trial
- cost in CNY minor units only when an operator-configured rate is available
- cost status: `configured_estimate` or `unavailable`

### Provider cost ledger

- category: media generation
- resource type: image, video, or mixed
- unit count and media points
- CNY minor-unit cost
- cost status: `actual`, `reconciled`, `configured_estimate`, or `unavailable`
- no public supplier identity

## Operator metrics

The 30-day overview reports unique visitors, sessions, page views, signup completion, paid order revenue, model tokens split by billing owner, media cost coverage, and contribution margin status. Margin is `ready` only when every included supplier cost is actual/reconciled or a deliberately configured estimate; otherwise it is `partial` and no false profit number is shown.

## Failure behavior

- Analytics failures never block page use, registration, or login.
- Metering failures never discard a model answer or generated asset; they produce an internal audit warning and leave cost coverage partial.
- Duplicate events and retries are idempotent.
- Real charges, refunds, eBay writes, ads, procurement, inventory, price, and policy changes remain outside this work.
