# Platform-funded trial activation guard

## Goal

Keep account registration and merchant BYOK available while preventing automated
account farms from consuming Jiejing-funded AI and media generation credits.

## Decision

Registration and platform-funded trial activation are separate outcomes.

- Registration can succeed without a platform-funded trial.
- Merchant-owned DeepSeek/OpenAI connections remain available regardless of the
  Jiejing trial decision.
- A Jiejing-funded trial requires an attested edge challenge when the production
  guard is enabled.
- Trial activations use shared database rate-limit buckets with daily per-IP and
  global budgets. Raw IP values are never persisted.
- The activation decision is stored as tenant-scoped backend state. Existing
  accounts without an activation record are grandfathered to avoid regressions.
- Welcome media points are granted only after activation succeeds.

## Public behavior

The registration response includes a sanitized `platform_trial_activation`
summary. A withheld trial explains that account registration succeeded and that
the merchant can still connect their own AI. It never exposes challenge secrets,
raw client IPs, provider responses, or internal identifiers.

## Verification

One API-level regression covers challenge absence, successful activation, daily
budget exhaustion, safe response fields, and platform-model quota blocking. The
existing BYOK fallback regression continues to prove that merchant-paid model
usage bypasses Jiejing trial limits.
