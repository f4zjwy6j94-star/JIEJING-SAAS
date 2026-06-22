# Jiejing first-order operating loop design

## Product Goal

Make the logged-in AI CEO cockpit explain one clear merchant path: from the first eBay product idea to publish preflight, decision center review, and post-publish follow-up. This is a product surface change, not a new execution shortcut.

## User Experience

The AI CEO cockpit now shows a "首单经营闭环" panel directly below the chat surface. The panel has six operating steps:

1. Official eBay read-only packet.
2. Market Report and Listing Package.
3. Fresh product intake with new SKU/assets only.
4. Publish-health red/yellow/green report.
5. Decision center gate.
6. Post-publish cockpit.

Each step exposes a status, a metric, a plain-language blocker, and one safe next action. Buttons reuse existing protected actions such as `sync-ebay-readonly`, `run-model-value-rehearsal`, `focus-publish-intake`, `create-publish-confirmation`, and `open-confirm`.

## Safety Boundaries

- No OAuth is started from this panel.
- No billing Checkout is started from this panel.
- No eBay write is allowed from this panel.
- Old demo products, old images, and old SKUs are explicitly rejected as real smoke inputs.
- eBay token refresh proof remains visible as a blocker when the proof count is `0`.
- Real publish, procurement payment, price, inventory, refund, ads, policy, and sensitive customer promises still route to the decision center.

## Verification

Static guard: `tools/test_jiejing_first_order_launch_loop_ui.py`.

The guard checks that the cockpit contains the first-order loop, publish-health and confirmation links, cache busting, and no unsafe secret/write markers.
