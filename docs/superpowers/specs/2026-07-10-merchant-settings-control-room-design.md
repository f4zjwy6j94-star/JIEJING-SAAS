# Jiejing Merchant Settings Control Room

## Goal

Make Settings a merchant-facing control room for account access, the eBay connection, AI and media availability, store data, team approval boundaries, subscription, and security. Daily product work remains in AI CEO, Listing, bulk merchandising, media, customer service, and the decision center.

## Information Architecture

The merchant sees six entries:

1. Overview: current status and links to the five setting categories.
2. Account and store: Jiejing account, eBay connection, and account health.
3. AI and media: account-scoped text AI, trial quota, web search, and media availability.
4. Store data: official read-only data, source records, and missing information.
5. Team permissions: the current role and confirmation boundaries; the full role matrix is optional detail.
6. Subscription and security: current plan, current charge state, and the activation action; pricing, continuity, and security explanations are optional detail.

Internal launch, payment-provider, WAF, queue, OAuth diagnostics, and production-readiness controls remain available only in the owner-operations tab.

## Merchant Display Rules

- Show the current state and one next action before explanatory material.
- Do not list unopened marketplaces as if merchants can configure them.
- Distinguish "supported connection" from "currently connected" for AI providers.
- Do not repeat the same subscription explanation across several default-visible cards.
- Show the current team role by default; place the complete role catalogue behind an explicit details control.
- Keep raw provider names, internal status keys, rehearsal controls, secrets, and deployment language out of ordinary merchant settings.
- Never move market reports, Listing drafts, media assets, or work records into Settings.

## Behavior Boundaries

- Existing backend contracts and account isolation remain unchanged.
- No eBay OAuth, platform write, payment, refund, advertising, procurement, pricing, inventory, or policy action is triggered by this UI change.
- Formal-payment opening checks move to owner operations; merchant-safe plan and activation state remain under Subscription and Security.
- Provider credentials continue to be accepted only by the backend secret boundary and are cleared from the form after save.

## Acceptance Criteria

- All six merchant setting entries render and switch without console errors.
- Subscription and Security shows no more than two primary cards before optional details.
- Team Permissions initially shows the current role and approval boundary, not seven simultaneous role cards.
- AI provider cards say whether a provider is supported, not that the merchant is already connected.
- Account and Store presents eBay as the active platform without a catalogue of unavailable marketplaces.
- Settings module split, merchant copy guard, account isolation, secret scan, deployment gate, desktop/mobile smoke, and public readiness checks pass.
