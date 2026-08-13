# Controlled eBay Draft Save Launch Plan

1. Add the narrow configuration property and keep broad real-write/public-publish properties false.
2. Route only `save_ebay_listing_draft` through the live boundary when the narrow property is true.
3. Claim draft execution atomically and persist terminal success or manual-reconcile state exactly once.
4. Add strict current-store execution evidence to product readiness.
5. Add a confirmation-gated draft-save OAuth scope upgrade; retire the ungated publish-plan entry.
6. Add frontend confirmation/redirect validation and merchant-language status.
7. Run focused adapter, HTTP concurrency, OAuth, readiness, Postgres, security and browser tests, then the full precloud gate.
8. Commit, push, deploy through Doctor -> dry-run -> apply -> Doctor.
9. Ask the merchant for only the final eBay consent/confirmation clicks, save one unpublished draft, verify no public listing, and re-read readiness.
