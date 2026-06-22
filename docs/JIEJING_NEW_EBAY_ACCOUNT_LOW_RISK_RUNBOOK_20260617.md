# New eBay Account Low-Risk Test Runbook - 2026-06-17

This runbook is for the next clean eBay account test. It must not reuse the frozen account, old listing, old SKU, old image set, old report, or old OAuth attempt.

## Hard Rules

- Do not repeat OAuth for the old frozen account.
- Do not use old demo products, old test images, or old SKUs.
- Do not publish when account health is `unknown`, `restricted`, `suspended`, `payout_hold`, or `quota_limited`.
- Do not execute real publish, price change, inventory change, refund, ad spend, policy edit, or sensitive buyer promise outside confirmation center.
- Do not write passwords, eBay refresh tokens, model keys, Stripe keys, or provider tokens into files.

## Low-Risk Sequence

1. Public health: `/health` must be `ok`, database startup must be `ready`.
2. Product readiness: `/readiness/product-saas` must show no database, queue, account-health, token-refresh, or model-value blocker that affects the test.
3. New account login: create or select the new merchant account in Jiejing.
4. eBay authorization: connect only the new eBay account through the normal SaaS backend OAuth path.
5. Store sync: run official read-only sync and generate a sanitized eBay data packet.
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
- account health snapshot
- publish health report
- confirmation ID and decision
- eBay platform result
- audit timeline
- cleanup confirmation and result

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
