# WeChat Production Cutover Truth Implementation Plan

## Phase 0 — Authoritative patterns

Use these existing interfaces; do not invent provider calls:

- `jiejing_saas.paid_launch_approval_packet.build_paid_launch_approval_packet`: canonical WeChat Native payment and zero-charge launch evidence.
- `jiejing_saas.billing_payment_options.validate_mainland_payment_launch_for_public`: fail-closed public payment projection.
- `jiejing_saas.owner_launch_control._owner_mainland_cutover_view`: current compatibility projection to deepen and expose.
- `jiejing_saas.billing_wechat_pay_rehearsal.run_wechat_pay_zero_charge_rehearsal`: isolated fake-transport proof; never call this from a GET projection.
- `jiejing_saas.api_server.SaaSBackendHandler`: owner-admin permission checks and fixed JSON error responses.
- `app.js` Settings control-room rendering and `tools/codex_jiejing_paid_cutover_decision_smoke.js`: existing browser surface and contract fixture.

Avoid the deprecated patterns in `billing_domain_cutover_rehearsal.py` and `billing_provider_evidence_register.py`: Stripe Checkout, Portal, Price IDs, subscription webhooks and Stripe live-mode evidence cannot satisfy mainland launch.

## Phase 1 — Canonical owner packet

1. Add one public-interface regression to `tools/test_jiejing_owner_launch_control.py` proving `mainland_payment_cutover` exists, has exactly the payment and zero-charge sections, and stays blocked when either section is blocked.
2. Update `_owner_mainland_cutover_view` and `build_owner_launch_control` minimally to satisfy the test.
3. Require exact false values for charge, refund, external provider call, eBay OAuth, platform write and secret exposure.

Verification: owner launch control test, paid launch approval packet test, production release gate test.

Anti-pattern guard: do not execute the zero-charge rehearsal while building GET packets; only read its existing audit evidence through the paid-launch packet.

## Phase 2 — Retire false HTTP truth

1. Add HTTP regressions to `tools/test_jiejing_owner_launch_control_access.py`: anonymous legacy routes return 401; authenticated platform admin receives 410 with exact fixed codes and no legacy provider body.
2. Replace the four legacy GET route bodies in `api_server.py` with protected fixed retirement responses.
3. Keep canonical `/owner/launch-control` and `/owner/paid-launch-approval-packet` unchanged.

Verification: access test, backend MVP, P0 security guardrails.

Anti-pattern guard: do not remove the permission check, redirect to a provider, or return Stripe configuration in the retirement body.

## Phase 3 — Settings control room

1. Add static RED assertions that `app.js` no longer fetches legacy endpoints and contains the canonical `mainland_payment_cutover` key without current-launch Stripe copy.
2. Update state hydration to obtain the cutover from `/owner/launch-control` only.
3. Rewrite the card as two WeChat sections: production prerequisites and zero-charge/rollback evidence. Unknown blocker values receive generic allowlisted copy.
4. Update the existing paid-cutover browser fixture to assert provider `wechat_pay_native`, two sections, safe false flags, malformed fail-closed behavior and no secret/ID leakage.

Verification: frontend static, Settings layout, paid-cutover browser smoke, secret scan.

Anti-pattern guard: no Checkout, Portal, Price, Stripe subscription, provider secret, merchant ID, order ID or raw blocker string in the current mainland card.

## Phase 4 — Compatibility and release

Run focused WeChat payment, owner control, production release, frontend, browser and security tests. Run `tools/jiejing_precloud_deployment_gate.py`. Freeze hashes, commit, push, then use pre-Doctor → dry-run → apply → post-Doctor. Verify public health and the authenticated Settings card. Keep all payment/refund/real-write switches false.

Do not mark paid launch ready: the independent Vault custody blocker remains external until three real custody units and a witnessed restore are proven.
