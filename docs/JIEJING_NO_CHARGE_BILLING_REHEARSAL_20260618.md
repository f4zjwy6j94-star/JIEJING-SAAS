# Jiejing No-Charge Billing Rehearsal - 2026-06-18

Purpose: let staging run the full SaaS billing lifecycle while the owner does
not yet have a usable live Stripe account or Mainland China business setup.

## Provider

- `JIEJING_BILLING_PROVIDER=stripe_test_mock`
- No Stripe account is required.
- No Stripe API key is required.
- No real Checkout Session is created.
- No real charge, refund, card collection, or payment method update is allowed.
- Public `/billing/webhook` rejects this provider; test events must use the
  authenticated backend boundary.

## Flow

1. Create a test checkout session with `POST /billing/checkout-session`.
2. Apply a test lifecycle event with `POST /billing/test-event`.
3. Verify `/billing/usage` shows entitlement and quota state.
4. Apply `payment_failed` or `cancel` and verify quota blocks paid work.
5. Keep `/billing/plans` paid-launch fields blocked until live Stripe is ready.

Supported test actions:

- `activate`
- `invoice_paid`
- `payment_failed`
- `cancel`

## Safety Boundary

- `creates_real_checkout_session=false`
- `calls_stripe_api=false`
- `triggers_real_charge=false`
- `charge_now_allowed=false`
- `frontend_gets_payment_secret=false`
- `secret_exposed=false`

This is only a staging/private-beta rehearsal path. Public paid launch still
requires live Stripe Products/Prices, signed webhook secret, Checkout, Customer
Portal, stable callback URLs, and owner approval.
