# Jiejing eBay account freeze hold - 2026-06-18

## Current decision

eBay live-account work is paused.

The previously used seller account showed an account-frozen notice during the eBay sign-in / consent path. Do not use that account for:

- OAuth authorization
- token refresh proof
- read-only packet refresh
- low-risk live publish smoke
- callback verification by signing in
- cleanup or post-publish checks

## Safety boundary

Do not save or claim readiness from partially prepared console fields. The current production status remains:

- eBay OAuth not re-run
- eBay callback not verified by a new account
- eBay token refresh success proof remains unavailable
- no new eBay refresh token should be written to Vault from the frozen account
- no old demo SKU, image, or listing should be reused as a real smoke proof

## Resume conditions

Resume eBay work only after the owner has a clean new eBay account and fresh product materials.

Required inputs before the next eBay smoke:

- new eBay seller account that can sign in and is not frozen or restricted
- fresh real product title, photos, SKU, condition, price, inventory, shipping policy, return policy, payment policy, and category intent
- owner approval to start a new OAuth authorization with that new account
- confirmation-center approval before any real publish, inventory, price, refund, ad, policy, or sensitive customer-service action

## Next safe work

Until the new eBay account is ready, continue:

- Stripe live account onboarding and provider cutover preparation
- stable domain, WAF, SSH, origin-lock and callback evidence hardening
- no-real-charge Stripe rehearsal
- UI/report improvements that keep real eBay writes blocked

