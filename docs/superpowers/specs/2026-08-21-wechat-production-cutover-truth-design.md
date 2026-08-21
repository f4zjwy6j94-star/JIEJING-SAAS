# WeChat Production Cutover Truth Design

## Context

Mainland launch uses WeChat Pay Native. The current owner launch packet and paid-launch approval packet already use that canonical provider, but the separate billing-domain rehearsal endpoint, Settings card, and provider evidence register still expose an older Stripe subscription cutover contract. Those legacy surfaces can misdirect an operator during the final production review even though they do not themselves move money.

## Decision

Use the existing WeChat Pay Native launch status and paid-launch approval packet as the only mainland production-cutover truth. Keep Stripe only as an explicitly future international option. Do not build a generic multi-provider abstraction during this launch pass.

The old Stripe domain rehearsal and Stripe provider evidence endpoints become retired compatibility surfaces. They must return a fixed value-free retirement response and must not be fetched or rendered by the current Settings control room.

## Canonical owner cutover contract

`build_owner_launch_control` exposes one `mainland_payment_cutover` object derived from `build_paid_launch_approval_packet`.

The contract contains exactly two launch sections:

1. `wechat_pay_native_cutover`: backend-only merchant configuration, signed payment and refund callbacks, authenticated order query, controlled acceptance and refund proof.
2. `no_charge_launch_rehearsal`: isolated zero-charge rehearsal, rollback packet, readiness snapshot, browser smoke, final commercial smoke and secret scan.

The overall status is `ready_for_owner_approval` only when both sections are ready. A ready payment configuration cannot hide a missing zero-charge rehearsal. The object never creates an order, calls an external payment API, charges, refunds, exposes a secret, starts eBay OAuth or performs a platform write.

## HTTP and UI migration

- `/owner/launch-control` remains the canonical platform-admin endpoint and includes `mainland_payment_cutover`.
- `/owner/billing-domain-cutover-rehearsal` and `/commercial/billing-domain-cutover-rehearsal` return HTTP 410 with fixed code `legacy_stripe_billing_cutover_retired`.
- `/owner/billing-provider-evidence-register` and its legacy commercial alias return HTTP 410 with fixed code `legacy_stripe_billing_evidence_retired`.
- Settings stops requesting both legacy sources. It renders the canonical object already returned by `/owner/launch-control`.
- The card uses only mainland terms: WeChat Native QR, signed payment/refund callback, authenticated order query, zero-charge rehearsal, rollback and owner approval. It contains no current-launch Stripe Checkout, Portal, Price, subscription or Stripe API wording.

## Failure and security behavior

- Missing or malformed owner cutover data renders a blocked, value-free state.
- Unknown blocker strings are not copied into merchant-visible text; the UI uses an allowlisted label map and generic fallback.
- The two legacy endpoints are still owner-admin protected before returning 410, so their existence does not become an unauthenticated capability oracle.
- All safety flags remain exact false: public charging, charge now, real refund, external payment call, eBay OAuth, platform write and secret exposure.
- Existing WeChat credentials stay backend-only. No credential, merchant identifier, order identifier, evidence identifier or raw provider error is added to DOM, logs, storage or public JSON.

## TDD slices

1. Owner launch control: RED proves canonical object is missing or reports ready when only payment is ready; GREEN exposes two-section exact status and false safety flags.
2. HTTP: RED proves legacy endpoints still return 200 Stripe evidence; GREEN requires authenticated HTTP 410, unauthenticated 401, no provider calls and no secret/value leakage.
3. Frontend static: RED proves Settings still fetches and labels the Stripe contract; GREEN removes the fetch and all current-launch Stripe wording while requiring the new canonical key.
4. Browser: RED proves the rendered card cannot explain the WeChat cutover; GREEN verifies exact two-section output and blocks malformed/unknown evidence without DOM/storage/log leakage.
5. Compatibility: existing canonical WeChat rehearsal, payment status, owner launch access, public readiness and production release tests remain green. Stripe may remain documented only as future international payment and must not satisfy mainland readiness.

## Deployment and acceptance

Run focused owner-control, payment, frontend, security and browser contracts, then the full precloud gate. Commit and push only a frozen tree. Use pre-Doctor, dry-run, apply and post-Doctor. Public health must remain ready; readiness must honestly retain the Vault custody blocker and paid-launch warning until external custody and production cutover evidence are genuinely complete. Public charging, refunds and real platform writes remain disabled throughout.
