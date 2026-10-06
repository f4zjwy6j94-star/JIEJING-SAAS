# Merchant content closure — approved scope

User approved continuing confirmation, service/orders and Settings content/function refinement, with visual theme deferred. This is a bounded continuation, not a new product structure or sourcing service.

## Findings and decisions

- Live service page reported 1 confirmation while the current confirmation center reported 0. Its text regex scanned all historical cards regardless of status or display scope. Use the confirmation center's display scope plus pending status and explicit customer-service action types; never infer actions from prose.
- Confirmation center repeats explanations and sends users to Settings for work records. Keep one primary heading, existing approval controls and records; explain that approval is not execution. Offer a return to the product when empty. Do not imply all AI tasks run automatically.
- Service page calls historical order snapshots current pending work and exposes test/engineering language. Show snapshot date and buyer-message availability, keep draft/sent/simulation states distinct, and provide an honest AI CEO draft entry. No message sending or integration added.
- Settings already has five categories and a compact account/AI layout; preserve it. Put current subscription/payment and media balance before optional detailed billing rules. Translate resource status labels without altering data; explicitly handle missing subscription expiry instead of a circular fallback.

## Implementation / acceptance

1. Add offline renderer regression tests before fixing counters; all fixtures synthetic, network forbidden.
2. Update scoped renderers, copy contracts and content-hashed frontend cache references. No backend business logic or existing dirty-file inclusion.
3. Verify empty/current/history states, pending action scope, HTML escaping, billing action preservation and missing-data wording; inspect actual rendered desktop/tablet layouts and interactions.
4. Scoped commit. Production deployment requires same-source gate, bundle and dry-run, with scoped deployment approval. Do not repeat previous release's gates or claim new code is already deployed.

No OAuth, sync, model/image generation, payment/refund, eBay write, account clearing, old-host migration or theme changes.

## Local result

- Fixed pending service count using current confirmation display scope/status/action types; added the sensitive-customer-reply alias to history. Ordinary listing text mentioning shipping/returns no longer becomes a service task.
- Removed duplicate confirmation guidance; folded secondary explanations, retained all approval/revise/reconciliation handlers. Customer confirmation shows saved reply text/order target and does not inherit an unrelated active product. Approved history has no pending decision or approval button.
- Made order snapshot age and buyer-message limitation explicit; reply-state legend is optional, not a numbered workflow. No new messaging adapter or automatic sending claim.
- Preserved five Settings categories, account/AI forms and all billing actions. Current subscription and media balance come first; explanations are collapsed. Missing expiry is explicit; backend source/status codes are not presented as merchant copy.
- Offline renderer regressions reproduce old counter error (red before change); new tests cover scope, aliases, records, missing data, escaping and action preservation. Added to deployment gate as `merchant_content_workspace` (catalog now 242; no full gate run for this candidate yet).
- Local real render inspection at 1440 and 820: empty/pending/approved confirmation, service history and count, Settings tabs and disclosure; no horizontal document overflow. Approval buttons absent for approved history; replies visible before confirmation; expansion controls work. Local page console error/warn empty. These are synthetic fixtures, not new merchant or eBay execution evidence.
- Visual theme/CSS unchanged. Production remains the preceding release until separately approved deployment.

## Deployment preflight correction (09-25)

- First clean 19303b4 gate passed 241/242; `merchant_project_status_browser` timed out at 180 seconds. The smoke test still waited for retired service empty-state copy, and its browser only closed on the success path, masking the actual 20-second assertion timeout.
- Added `withOwnedBrowser` with unconditional finally cleanup and injected-launch unit coverage (red, then green for success/failure). With only cleanup changed, the original browser test reproduced the old-copy timeout and exited normally with failure instead of hanging.
- Updated the smoke expectation to the approved empty state, including both buyer-message unavailability and no automatic draft sending. The complete isolated browser flow then passed desktop/tablet/mobile and project reload checks with no page errors or bad responses. No product/runtime change or timeout increase was needed.
- Content tests now include 11 cases; gate catalog remains 242. The final committed candidate still needs its own complete gate, bundle, dry-run, apply and live acceptance. Never merge the earlier failed report into a claimed pass.
