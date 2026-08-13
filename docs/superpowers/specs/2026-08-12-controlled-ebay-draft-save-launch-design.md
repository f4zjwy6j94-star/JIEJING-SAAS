# Controlled eBay Draft Save Launch Design

## Goal

Close the last eBay execution-readiness warning with one real merchant proof that saves an Inventory API item and an unpublished offer, while keeping every public-listing, payment, refund, ad, procurement and policy-write path disabled.

## Product boundary

- `JIEJING_EBAY_DRAFT_SAVE_LIVE=true` is a narrow capability. It never implies `JIEJING_ENABLE_REAL_PLATFORM_WRITES=true` or `JIEJING_EBAY_WRITE_LIVE=true`.
- The narrow capability supports only `save_ebay_listing_draft` after an exact approved confirmation, complete execution preflight, an idempotency key, a backend-only Vault token and an atomic external-execution claim.
- `publish_listing`, `cleanup_test_listing`, revise, price, inventory, ads, refund, procurement, policy and tracking actions remain blocked while the broad write flags are false.
- The adapter must inspect offers by SKU before writing, must stop when a published offer exists, and must never call `publishOffer`.
- An uncertain adapter outcome leaves the confirmation in manual-reconcile state and cannot be retried automatically.

## Authorization upgrade

The current seller connection is read-only. The write scope used by eBay Inventory API must therefore be requested through a dedicated confirmation-center card whose merchant-facing purpose is "save unpublished eBay draft". The resulting connection may hold the technical `sell.inventory` scope, but Jiejing's server capability remains draft-only until the broad publish flags are separately approved in a future release.

The browser receives only an eBay authorization URL and state. Tokens remain in the backend Vault boundary. URL, state, scopes, company, store and confirmation bindings must be validated exactly before redirect.

## Readiness evidence

The execution-service item becomes ready only when all of these are true:

1. The narrow draft-save capability is enabled.
2. A stored execution has status `saved_to_ebay_draft` for an executed `save_ebay_listing_draft` confirmation.
3. The result proves `offer_status=UNPUBLISHED`, `writes_to_ebay=true`, `published_to_ebay=false`, `public_listing_created=false` and `secret_exposed=false`.
4. The company/store still owns one active eBay connection and active backend refresh-token reference.

Turning on the switch without this proof remains a warning. Historical simulated results, retired synthetic stores, malformed JSON and published results never satisfy readiness.

## Deployment and rollback

Deploy code and keep the narrow switch false first. After pre-Doctor/dry-run/apply/post-Doctor pass, enable only `JIEJING_EBAY_DRAFT_SAVE_LIVE=true` through the authoritative compose declaration, deploy again, then run one merchant-confirmed proof. A failure stops with the broad publish flags still false. Rollback disables the narrow switch and restores the previous release; it never deletes the merchant's eBay draft automatically.
