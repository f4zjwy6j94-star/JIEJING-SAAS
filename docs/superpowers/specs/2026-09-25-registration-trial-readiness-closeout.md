# Registration trial readiness closeout

Scope: the approved single-domain Turnstile setup and the already implemented
20-call registration flow. No new plans, DNS/WAF change, login requirement,
eBay action, payment, refund, or free media grant.

## Observed defect

The deployed registration endpoint required server verification but its
site/verification pair was absent and its switch was off. Existing login and
BYOK remained usable; new platform-funded trial activation was unavailable.
Product readiness did not include this condition and therefore overstated
new-customer readiness. A previous uncommitted readiness addition was reviewed
and completed rather than replaced with another implementation.

Rendered inspection then found that the homepage's separate registration form
did not submit a challenge at all, unlike the workbench form. This is the same
activation defect, not a visual redesign. Add bounded explicit verification to
that entry, pass the result in the existing API contract, request a fresh token
for retries, and disclose withheld trial activation without blocking BYOK/login.
The client controller has 10 isolated behavior checks; the server verifies
action, hostname, replay and activation budgets independently.

## Change

- Add one readiness item, derived from the existing public registration
  configuration. Required but incomplete verification is a production blocker;
  configured verification is informational. Secrets never enter the item.
- Preserve anonymous readiness filtering: only warnings and blockers are
  returned, so a ready registration verifier is absent from the public list.
- Cover every missing configuration component and the working case, then
  exercise the existing HTTP flow with an isolated verifier: missing, invalid,
  wrong-action, wrong-host, replay, per-IP and global budget, and BYOK isolation.
- Configure one Managed widget for app.jiejing.shop with pre-clearance off.
  Transfer generated configuration through a one-shot loopback private input
  and SSH stdin to the existing backend private env; no credential in source,
  chat, raw logs, command arguments, or merchant responses. Preserve unrelated
  bytes and permissions, validate exact release/compose references, hold the
  deployment and maintenance locks, and restore original config on failure.

## Verification and honest claims

Configuration presence is not proof of a completed real challenge. Check both
API and worker projections, public challenge config, official script/widget
loading, and the actual registration outcome where owner interaction permits.
Do not use Cloudflare test keys in production or disable activation protection.
The final code change requires its own same-source gate and controlled release;
the previous 245-check release is not evidence for this addition.

## Actual new-merchant entry follow-up (2026-09-26 Beijing)

The owner completed the real registration challenge. The backend recorded one
ordinary-merchant registration and one verified activation. Selecting the live
free-trial card then failed with `unsupported current_step_key`: the homepage
submitted `trialStart`, absent from the backend's bounded step allowlist. The
old tests checked the UI and backend independently, missing this contract gap.

Permit only this existing free-entry step; retain all other input validation
and external-action gates. Restore `trialStart` as the trial path, not the paid
single-store guide sharing the same `store_opened` backend path. This does not
grant a subscription, connect eBay, invoke AI, or change pricing/permissions.

Regression evidence executes the real homepage catalog and serializer for all
three public paths and every step, validates their payloads, and restores the
same path/step. The actual trial payload also traverses the isolated HTTP API,
persists once, reloads unchanged, keeps external writes false and leaves the
other tenant unchanged. Both defects were observed RED before their minimal
fixes. Real acceptance must resume the same registered account after release;
do not register again or replace browser evidence with a direct database write.
