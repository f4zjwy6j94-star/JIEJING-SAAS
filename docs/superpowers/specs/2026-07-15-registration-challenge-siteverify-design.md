# Registration challenge server verification

## Goal

Protect Jiejing-funded AI and media trial credits from direct API abuse without
blocking account registration, merchant BYOK, or ordinary login.

## Options considered

1. Trust the edge-enabled environment flag. This is insufficient because a
   caller can submit directly to `POST /auth/register` without proving that the
   current request completed a challenge.
2. Trust a browser or proxy header. This is easy to forge unless the entire
   origin trust chain is cryptographically bound to the request.
3. Send a short-lived browser challenge token and validate it from the backend.
   This is the selected approach because it gives every registration attempt an
   independently verifiable, single-use proof.

## Public contract

- `GET /auth/challenge-config` returns only public configuration: whether the
  check is required, whether the widget can run, the public site key, and the
  expected action. It never returns the verification secret.
- The registration client may send `trial_activation_challenge` containing the
  provider, token, and action.
- Registration still succeeds when verification is missing, unavailable, or
  rejected. Only Jiejing-funded trial activation and welcome media points are
  withheld. Merchant-owned model connections remain available.
- Customer-facing responses use stable, sanitized reasons. They never include
  the token, raw provider response, secret, or client IP.

## Backend validation

- The backend is the only caller of the fixed Siteverify endpoint.
- The secret is read only from `JIEJING_TURNSTILE_SECRET_KEY` in the backend
  private environment/Vault boundary.
- Validation uses a bounded timeout and checks `success`, `action`, and the
  configured hostname allowlist.
- Tokens are never stored. The existing tenant activation record stores only
  the sanitized decision.
- Daily per-IP and global activation budgets are consumed only after successful
  server verification.
- Tests may override the Siteverify URL only when `JIEJING_SAAS_ENV=test`; this
  keeps production immune to environment-driven SSRF.

## Frontend behavior

- The SPA loads the challenge script only when registration requires it.
- The challenge uses explicit rendering and interaction-only appearance so the
  normal path remains quiet while still allowing an interactive fallback.
- Expired or failed tokens are discarded. Every retry requests a fresh token.
- If the challenge service is unavailable, the merchant can still create the
  account and is told that Jiejing's赠送额度 is pending while BYOK remains usable.

## Security and deployment

- CSP permits only the official challenge script and frame origin.
- Production and staging fail closed for Jiejing-funded credits when either the
  public site key or backend secret is absent.
- Secret scanning, API regression, frontend contract, deployment contract, and
  the full precloud gate must pass before public staging deployment.
- This change cannot trigger eBay writes, charges, refunds, ads, procurement,
  repricing, inventory changes, or policy edits.
