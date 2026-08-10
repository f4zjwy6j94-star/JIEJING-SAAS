# New eBay Account Low-Risk Test Runbook - 2026-06-17

This runbook is for the next clean eBay account test. It must not reuse the frozen account, old listing, old SKU, old image set, old report, or old OAuth attempt.

## Hard Rules

- Do not repeat OAuth for the old frozen account.
- Do not create a new OAuth plan when the current store already has an authorized eBay connection. Inspect authenticated, store-scoped evidence first.
- Do not use old demo products, old test images, or old SKUs.
- Treat account health as safe only when status is exactly `normal`, `incident_mode=false`, and `can_execute_real_writes=true`; missing fields and every other status, including `suspended`, fail closed.
- Do not execute real publish, price change, inventory change, refund, ad spend, policy edit, or sensitive buyer promise outside confirmation center.
- Do not write passwords, eBay refresh tokens, model keys, Stripe keys, or provider tokens into files.
- Do not mark the smoke ready with one broad flag. Each account, OAuth, product, publish and cleanup boundary needs its own audit flag.

## Low-Risk Sequence

1. Public health: `/health` must be `ok` with `database_startup_status=ready`; `/health/deep` must report the database, queue and worker as `ready`.
2. Product readiness: public `/readiness/product-saas` must show no platform blocker, but its global packet or refresh count never proves the selected store is connected.
3. New account login: create or select the new merchant account in Jiejing.
4. eBay authorization: first verify authenticated `/connections?store_id={store_id}` and backend-derived `/stores/{store_id}/ebay-oauth/read-only-status`. Only a completed backend callback, stored secret reference, immutable account identity and matching system audit prove authorization; merchant-written connection status does not. If the current store is already authorized, do not repeat OAuth. If it is not authorized or pending and the owner explicitly approves this external step, use `POST /stores/{store_id}/ebay-oauth/read-only-plan` through the backend secret boundary with the exact approved `confirmation_id`; the backend idempotently rejects an existing authorized or pending plan. The staging operator tool never creates or approves that confirmation and only calls the plan endpoint when the approved ID is passed explicitly in the real CLI order `python tools/jiejing_staging_ebay_oauth_readonly_flow.py prepare --confirmation-id <approved-card-reference>`.
5. Store evidence: verify authenticated `/data-packets?store_id={store_id}&platform=ebay&limit=1`, `/stores/{store_id}/account-health`, `/queue-jobs?status=completed&limit=200`, and `/audit-logs?limit=200`. Official evidence requires a packet no more than six hours old, bound to the current company, store, OAuth connection and account-health packet ID, plus non-empty IDs and a matching backend worker completion and system audit within five minutes. Packet-reported TTL, merchant-supplied metadata, or `source_mode=official_api` alone is not proof. Only when this evidence is missing, run `python tools/jiejing_staging_ebay_oauth_readonly_flow.py request-sync-confirmation` to create a pending decision-center card. After a human decision center approval, pass its reference explicitly with `sync --confirmation-id ...`. The tool never creates or approves its own card and never starts sync from the request command; never sync merely to check progress.
6. Account health: show store name, account status, payout/limit signals, policy count, product/offer/order counts, latest packet ID, and last sync time.
7. New product check: reject if title, SKU, image hash, old listing ID, old report ID, or old asset manifest matches a previous test.
8. Publish health report: category, item specifics, image rules, VeRO/IP, prohibited terms, GPSR/regulatory fields, inventory location, business policies, seller quota, expected fees, contribution margin and account health must be red/yellow/green.
9. Confirmation center: red items block; yellow items require confirmation; real publish waits for an explicit approved confirmation.
10. Real publish: only after confirmation. Persist platform result, listing ID, offer ID, SKU, audit record and source packet.
11. Post-publish cockpit: schedule or record 1h, 24h and 7d review for impressions, clicks, watchers, sales, fees, margin and customer-service risk.
12. Test cleanup: end listing, delete/deactivate offer where applicable, retain audit and evidence. Cleanup also goes through confirmation center.

## Stop Conditions

- eBay account frozen, suspended, payout hold, quota limited, or policy attention signal.
- Missing business policy, inventory location, category, required item specifics, image compliance, GPSR/regulatory field, or seller limit.
- Duplicate title/SKU/image/listing/report from previous test.
- Model/report output is not Chinese for merchant-visible market report or listing package.
- Any real write would bypass confirmation center.

## Evidence To Capture

- health response timestamp
- readiness packet ID and blocker list
- new store display name and marketplace
- packet ID, source mode and resource coverage
- matching backend worker completion and system audit IDs
- account health snapshot
- publish health report
- confirmation ID and decision
- eBay platform result
- audit timeline
- cleanup confirmation and result

## Evidence Flags

The operator may only mark a phase ready when all flags in that phase have audit evidence. These flags are booleans or evidence IDs in backend env/Vault/audit metadata; they are not secrets.

- Account boundary:
  - `JIEJING_NEW_EBAY_ACCOUNT_CONFIRMED_CLEAN`
  - `JIEJING_NEW_EBAY_OLD_FROZEN_ACCOUNT_REJECTED`
- Fresh product boundary:
  - `JIEJING_NEW_EBAY_FRESH_PRODUCT_DECLARED`
  - `JIEJING_NEW_EBAY_FRESH_SKU_DECLARED`
  - `JIEJING_NEW_EBAY_FRESH_ASSETS_DECLARED`
  - `JIEJING_NEW_EBAY_NO_OLD_LISTING_OR_REPORT_REUSE`
  - `JIEJING_NEW_EBAY_PRODUCT_DUPLICATE_GUARD_PASSED`
- Publish confirmation:
  - `JIEJING_NEW_EBAY_PUBLISH_HEALTH_CONFIRMATION_READY`
  - `JIEJING_NEW_EBAY_PUBLISH_CONFIRMATION_APPROVED`
- Controlled real publish:
  - `JIEJING_NEW_EBAY_PUBLISH_CONFIRMATION_APPROVED`
  - `JIEJING_NEW_EBAY_ACCOUNT_REAL_PUBLISH_PASSED`
- Cleanup confirmation:
  - `JIEJING_NEW_EBAY_CLEANUP_CONFIRMATION_APPROVED`
  - `JIEJING_NEW_EBAY_TEST_CLEANUP_CONFIRMED`

## Automation Contract Keys

The backend launch gate, settings UI, and `tools/jiejing_new_ebay_account_low_risk_check.py` must keep these keys in this order:

1. `public_preflight_ready`
2. `clean_new_account_declared`
3. `new_account_oauth_authorization_gate`
4. `official_packet_account_health_snapshot`
5. `new_product_duplicate_guard`
6. `publish_health_confirmation_gate`
7. `controlled_real_publish_probe`
8. `post_publish_cockpit_cleanup_gate`

All contract outputs must set `secret_exposed=false`, `old_frozen_account_reuse_allowed=false`, `old_demo_product_or_sku_allowed=false`, `triggers_real_charge=false`, and `triggers_real_platform_write=false`. Real publish and cleanup are marked as real-write steps for operator planning, but the runbook/checker must not execute them directly.
