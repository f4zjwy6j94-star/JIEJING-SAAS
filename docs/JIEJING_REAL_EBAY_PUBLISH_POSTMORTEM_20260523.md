# Jiejing Real eBay Publish Postmortem - 2026-05-23

## Result

Jiejing completed the first controlled real eBay publish through the SaaS confirmation boundary.

```text
Product: Backflow Incense Burner
SKU: JJ-BACKFLOW-20260523-003
eBay listingId: 127879396514
eBay offerId: 172743146011
eBay status at verification time: ACTIVE
Listing URL: https://www.ebay.com/itm/127879396514
Marketplace: EBAY_US
Shipping origin: Shenzhen, China
Package weight: 200 g
Inventory quantity: 5
Test price used: US $9.99
SaaS executionId: exec_7a1e76616a64ec1d
```

No raw eBay access token, refresh token, model key, or authorization code was returned to the frontend or Runtime.

## What Happened

The test started from a real merchant account, a real eBay OAuth publish connection, and a confirmed high-risk publish action in the Jiejing confirmation center.

Initial release candidates were not safe to publish because the available official packet and generated listing context still had gaps:

- The original packet taxonomy could point to the wrong category. One observed bad state was `Bass Guitars` for an incense burner.
- The publish package required real execution fields: `description_html`, condition, price, quantity, `merchant_location_key`, package weight, package dimensions, material, shipping origin, image assets, net profit, and business policies.
- The eBay account had no inventory location yet.
- The SaaS UI and execution record did not expose enough detail when eBay returned a platform-side failure.

The category was corrected using eBay taxonomy suggestions. `Home Fragrance` / category `20552` was used for the low-volume test. The Shenzhen eBay inventory location was created as `shenzhen-warehouse`. The user supplied the real origin/weight/inventory values: Shenzhen, 200 g, quantity 5.

## Issues Found And Fixed

1. Wrong-category risk

The official packet could leave the listing package with a mismatched category. That is dangerous because a real publish can place a product in the wrong eBay category.

Fix applied:

- Added a category relevance guard in execution preflight.
- If the listing category leaf obviously conflicts with the title/product, the preflight blocks real publish before the platform adapter.

2. eBay platform limit

The first complete publish attempt used `US $99.99` with quantity `5`. eBay rejected `publishOffer` with an official seller-limit error:

```text
The listing would exceed the seller account's monthly listing amount limit.
Remaining monthly amount was about HK$1,741.33 at the time.
```

Fix applied:

- Treated this as a platform/business limit, not a broken API connection.
- Re-ran the publish with a lower test price: `US $9.99`.
- Added safe platform-error summaries so future execution results can show the eBay error id/message instead of a generic failure.

3. eBay inventory description format

The Inventory API accepted the product record more reliably when `product.description` was plain text, while the offer still needs the merchant-facing HTML listing description.

Fix applied:

- Inventory item `product.description` now strips HTML into plain text.
- Offer `listingDescription` keeps the HTML.
- Regression test covers both behaviors.

4. Result persistence crash after live platform action

After the successful platform-side action, the SaaS request returned `502`. Logs showed the backend crashed while saving `execution_results` because Postgres returned a `datetime` value that `json.dumps` could not serialize.

Fix applied:

- `save_execution_result` now uses the shared safe JSON serializer.
- The successful eBay publish result was backfilled into SaaS execution records.
- Regression test covers saving an execution result containing `datetime`.

5. Duplicate-publish risk during debugging

After the `502`, it was unsafe to blindly retry because the eBay platform action might already have succeeded.

Fix applied:

- Checked eBay directly by SKU before retrying.
- Verified that `JJ-BACKFLOW-20260523-003` already had a published offer and active listing.
- Did not call publish again for the same SKU.

## What This Proves

This test proves the first real write loop can work:

```text
Merchant account
-> eBay publish OAuth
-> official eBay data and policies
-> Jiejing AI CEO workflow
-> confirmation center approval
-> backend-only token resolution
-> eBay Inventory API item + offer + publish
-> execution result and audit record
```

It does not yet prove production readiness. It proves the narrow MVP publish path can create a real eBay listing when the packet is corrected and all required facts are supplied.

## Product Lessons

- Real publish must not depend on model guesses. Required fields need a visible completeness checklist.
- Category and taxonomy checks are not optional. Wrong category is a real business accident.
- Seller account limits are normal operating constraints. The product should show quota/limit blockers before the merchant reaches final publish.
- Platform errors must be shown as readable execution facts, not vague failure toasts.
- A live platform action can succeed even if the SaaS response fails. Execution recovery must verify external state by idempotency key/SKU before retrying.
- Confirmation center is the correct high-risk boundary, but it needs clearer "what will happen after approval" language for real publish.

## Engineering Follow-Ups

High priority:

- Add a publish readiness panel to Listing Factory and Confirmation Center:
  - category match
  - seller listing limits
  - required item specifics
  - inventory location
  - business policies
  - package dimensions/weight
  - image URL reachability
  - price x quantity quota impact
- Store sanitized eBay platform error summaries for every write step.
- Add recovery logic for ambiguous network/502 outcomes:
  - check SKU inventory item
  - check offers by SKU
  - check listing status
  - only retry if no published offer exists
- Make idempotency keys visible in execution records.
- Add cleanup tooling for test inventory items/offers/listings, with merchant confirmation.

Implemented productization pass on 2026-05-23:

- Added a backend publish-readiness checklist that surfaces field completeness, category match, business policies, inventory location, package facts, image assets, and price x quantity exposure before execution.
- Added merchant-readable eBay platform error summaries. Seller monthly listing amount failures are classified as `seller_listing_limit` and sanitized parameters are preserved without raw tokens.
- Added a read-only publish recovery check by SKU. It inspects inventory item and offers after ambiguous browser/HTTP failures and tells the product whether to backfill, manually review, or retry after preflight.
- Added a plan-only cleanup tool for test inventory/offers/listings. Cleanup is intentionally not automatic because ending or deleting a real eBay listing is a real platform write and must go through confirmation.
- Updated the confirmation center UI so the merchant can see the latest real publish result, preflight readiness, platform error, recovery status, and cleanup plan instead of only a toast.
- Added a frontend freshness fix after staging verification showed the API had confirmations/executions but the page still rendered the old empty state. Confirmation-center core data now loads and renders before slower optional security/model/commercial panels, and optional endpoint reads are bounded by a short timeout so they cannot hide real publish records.

Medium priority:

- Improve the UI wording around store name versus account email/internal store id.
- Replace any leftover generated/test product copy in real-mode workbench states.
- Add a first-class "live publish proof" report in AI CEO Reports.
- Add seller-limit monitoring to the eBay connection/settings page.
- Add a post-publish review step: title, category, price, quantity, policies, images, and deletion/end listing instructions.

## Current Known Cleanup Items

The active test listing was intentionally left live for merchant verification:

```text
https://www.ebay.com/itm/127879396514
```

Earlier debug SKUs may exist as unpublished inventory items because they were used to validate direct Inventory API behavior:

```text
JJ-BACKFLOW-INCENSE-DEBUG-FULL
JJ-BACKFLOW-INCENSE-DEBUG-MIN
```

They are not public listings unless an offer was published, but they should be cleaned up with an explicit merchant-approved cleanup action later.

## Rule For Future Agents

For real eBay writes, never retry blindly after a timeout, 502, or broken browser response. First verify platform state by SKU/offer/listing id, then decide whether to backfill the SaaS record, resume, or retry.
