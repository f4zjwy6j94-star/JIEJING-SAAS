# JIEJING WeChat Pay Native Collection Design

Date: 2026-07-13

## Decision

JIEJING will use direct WeChat Pay ordinary-merchant Native checkout as the
first formal mainland collection rail. Alipay follows through the same domestic
payment adapter after the WeChat order lifecycle is proven. Stripe remains a
later international route and is not the default for a mainland individual
business.

The first launch uses one-time 30-day plan orders rather than automatic renewal.
This keeps consent, cancellation, refund, failed-payment, and reconciliation
behavior explicit while the product is still in controlled merchant rollout.

## Merchant Experience

1. The merchant selects a JIEJING plan and sees the price, duration, included
   quota, refund link, and support link.
2. JIEJING creates one internal billing order before contacting WeChat Pay.
3. The backend creates a WeChat Native order, keeps the raw `code_url` inside
   the backend boundary, and returns only a short-lived rendered QR image to
   the frontend.
4. The merchant scans the generated QR code in WeChat.
5. The page polls JIEJING order status. It never treats a frontend redirect,
   screenshot, QR image, or client-supplied status as payment proof.
6. JIEJING activates the plan only after a verified WeChat callback or a
   successful backend order query confirms the merchant order number, amount,
   currency, merchant ID, and application ID.
7. The merchant sees only `待支付`, `支付确认中`, `已开通`, `已关闭`, or
   `需联系客服`. Provider diagnostics stay in the internal owner surface.

## Backend Components

### Domestic payment contract

The domestic payment layer is provider-neutral. The first driver is
`wechat_pay_native`; later drivers can implement the same contract for Alipay
or a licensed aggregate acquirer.

Required operations:

- create checkout order;
- get order status;
- query provider order;
- accept and verify payment notification;
- close unpaid order;
- request and query refund;
- normalize verified payment evidence into the existing subscription and quota
  lifecycle.

### Billing order record

Every payment attempt has a durable tenant-scoped record containing:

- JIEJING order ID and unique merchant order number;
- company ID, selected plan, amount in fen, currency, and duration;
- provider and sanitized provider transaction ID presence;
- order status and expiry;
- idempotency key hash;
- created and updated timestamps;
- sanitized order metadata only.

Raw callback bodies, API v3 keys, private keys, certificates, identity files,
bank details, QR images, and provider secrets are never persisted in this table.

### Verified evidence path

The callback boundary must:

1. verify the WeChat response signature using the configured WeChat Pay public
   key for new merchants, with platform-certificate fallback for older setups;
2. reject stale, malformed, unknown-serial, or invalid signatures;
3. decrypt the callback resource with AES-256-GCM inside the backend boundary;
4. compare `mchid`, `appid`, `out_trade_no`, amount, and currency with the
   internal order;
5. apply the resulting event idempotently;
6. activate entitlement only for a `SUCCESS` payment with no mismatches;
7. record a sanitized audit event without storing the raw callback.

When a callback is missing, the worker or authenticated order-status endpoint
may query WeChat. Query evidence must pass the same order, merchant, amount, and
currency checks before it can activate entitlement.

## Security Boundaries

- Merchant API certificate private key, API v3 key, merchant ID, app ID, and
  response-verification public keys or certificates stay in backend Vault/env
  references. Multiline PEM values use backend-only Base64 environment values
  or mounted secret files, never frontend configuration.
- The frontend receives no payment credential, decrypted callback, bank data,
  certificate, or private key.
- Merchant order creation requires `manage_billing` and tenant ownership.
- Public callback handling is unauthenticated only at HTTP identity level; it
  is authorized exclusively by provider signature verification and order
  matching.
- Duplicate callbacks and duplicate order-creation requests cannot double-grant
  quota.
- Amount, plan, duration, company ID, and merchant order number are always read
  from the server-side order record, never trusted from callback metadata or
  browser input.
- Refund money movement remains disabled until an internal owner confirmation
  flow and provider approval evidence exist.
- Real checkout creation remains blocked until merchant onboarding, credentials,
  signed callback rehearsal, active order-query proof, and owner live-cutover
  approval are all present.

## API Surface

Merchant-facing endpoints:

- `POST /billing/domestic/orders`
- `GET /billing/domestic/orders`
- `GET /billing/domestic/orders/{order_id}`
- `POST /billing/domestic/orders/{order_id}/checkout`
- `POST /billing/domestic/orders/{order_id}/close`
- `POST /billing/domestic/orders/{order_id}/query`
- `POST /billing/domestic/orders/{order_id}/refund-request`

Provider endpoint:

- `POST /billing/domestic/wechat-pay/notify`

Owner-only rehearsal endpoint:

- `POST /owner/billing/domestic/rehearsal`

The rehearsal generates and verifies sanitized mock evidence. It never calls
WeChat, creates a payable QR code, charges money, or grants production launch
readiness.

## Rollout Gates

The domestic payment route stays blocked for public paid launch until all of the
following are true:

- individual-business merchant account approved;
- settlement account verified by WeChat Pay;
- Native payment product permission active;
- reviewed domain and callback URL configured;
- backend credential references configured without secret exposure;
- signed callback verification proven;
- duplicate, delayed, and out-of-order callback tests pass;
- active order query and amount-mismatch tests pass;
- entitlement and quota activation tests pass;
- close-order and refund-state tests pass;
- support and refund pages remain publicly reachable;
- owner explicitly approves live cutover.

Public charging also requires the deployment itself to be the production
environment, live provider access to be enabled, the charge switch to be
enabled, and a non-empty owner approval packet ID. Staging must not be converted
into production merely by changing the charge switch.

Until then, `production_ready=false`, `can_accept_real_customers=false`,
`charge_now_allowed=false`, and `triggers_real_charge=false` remain truthful.
