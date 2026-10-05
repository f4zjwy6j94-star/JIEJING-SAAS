# Public paid SaaS closeout

The owner approved the corrected scope and supplied the public support address
zongshuding4@gmail.com. This revision replaces the earlier, incorrect
draft-only publication claim; do not retain that claim in code or tests.

## Approved direction

The owner approved the previously proposed release-scope closeout, then
explicitly rejected another merchant/product workflow replay. The outcome is
a public-facing paid SaaS release, not an invitation-only beta. Existing
registration, billing, ordinary-account and product-flow evidence is retained.
External merchant recruitment and another three-product run are not gates.

## Scope

Preserve the AI CEO direction, eBay-first delivery, all existing modules and
the three approved plans. Prices, quotas, billing logic and platform permissions
are unchanged. Align public and purchase-facing statements with the deployed
controlled eBay publication capability: authorized merchants prepare a draft,
pass the required product/account/plan checks, confirm, and publish through the
eBay API. Success is determined by the eBay result, not by payment or approval
alone. The broad write switch remains closed and is not publication status.

Fix only concrete public-delivery gaps found in this pass:

1. Correct publication statements on the homepage, before checkout, in the
   service-scope explanation and confirmation status. Read the independent
   controlled publish capability for status, rather than the broad switch.
   Do not imply subscription removes account restrictions or sends buyer messages.
2. Route Jiejing subscription/invoice help to the existing Jiejing feedback
   entry, not the merchant's eBay customer/order workspace.
3. Add the owner-supplied email to support and refund-help pages, plus a help
   link in the existing login dialog. Show the full address for manual copying
   and provide a mailto link. Explain that it opens the user's mail app and
   nothing is sent until the user sends it. Logged-in users retain the feedback
   entry. Email requests do not bypass account or payment verification.
4. State clearly that feedback is handled in the internal feedback dashboard;
   it is not automatically forwarded to the support email. Do not add a mail
   provider, collect email credentials, or promise an unstaffed response SLA.

## Non-goals

No new architecture, visual redesign, fourth plan, pricing change, repeated
registration/OAuth/payment/refund proof, product rerun, paid model/media call,
platform write, or invented business evidence. Do not open publication flags.
No price, refund-eligibility, term-of-service legal obligation, or SLA changes.
New defects unrelated to the public delivery surface are not silently added.

## Verification and release

Add focused regressions for the changed public statements and the support
route. Cover controlled-enabled/broad-disabled, broad-enabled, disabled, and
unknown capability projections without changing execution permissions. Inspect
these surfaces in the built-in browser at desktop and narrow widths; purchase
controls must remain unchanged, no order/email/feedback/listing is submitted.
Use D: for new verification artifacts. Existing completed evidence remains
valid for unchanged behavior; a new deployment must still follow the existing
same-source release procedure and its approval boundary. A local fix is not
reported as deployed.

## Evidence reused

- Current execution index, 2026-10-05 17:28 quality release and 18:48 billing
  correction; production source 48054ba.
- Current execution index, 2026-09-26 ordinary registration/trial and fixed
  R1/J1-J4/B1/C1/D1 closeout; do not redo those completed checks.
- Production API and worker read-only evidence at 19:43 on 2026-10-05:
  draft_save_live_enabled and controlled_existing_draft_publish_enabled true,
  live_actions_supported includes publish_listing. The old 8/22 blanket copy
  must not override this. A current product's real publish result remains separate.

## Implementation order

1. Correct one public-copy regression, verify RED, then correct the source.
2. Add public support/link/privacy regressions, verify RED, then wire the existing pages.
3. Correct confirmation capability projection with focused cases and no permission changes.
4. Run focused source checks and browser click/layout checks. Freeze the scoped
   candidate only after these pass; preserve all unrelated dirty documents.
5. Follow the existing same-source release gate, dry-run and deployment approval
   boundary. Do not use the old 48054ba proof for a changed candidate.

## Self-review

The changes clarify existing capabilities, do not remove modules, and do not
grant new authority. The required support address is supplied and approved for
public display. Acceptance concerns this patch, not another full product journey.
