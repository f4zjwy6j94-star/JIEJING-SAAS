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
