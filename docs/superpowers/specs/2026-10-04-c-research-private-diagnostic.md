# Third-product research: one-request private diagnostic

The user explicitly approved this narrow diagnostic on 2026-10-04 after the
third product's original request failed on deployed 379557e. A/B are preserved.
This is not permission to bypass report validation, rewrite business records,
publish to eBay, enable general logging, or collect another merchant's output.

## Capture boundary

- Default off. No browser/API diagnostic control; only an operator-created
  private control file beside the backend database, outside public assets.
- Exact company, user, store, submitted project, and SHA-256 of the approved
  request. First matching initial answer consumes authorization atomically.
- At most the initial and existing single repair answer from that same call;
  no new model retry, no reasoning, no provider credentials or prompt context.
- Capture only sanitized answer text, separate acceptance/reason codes, public
  product-source fields and bounded public semantic-plan fields.
- Two-hour maximum authorization. 0700 directory and 0600 files on Linux;
  shared controls, mismatched scope, revoked/expired consent and reuse fail off.
- A capture failure cannot change the public chat result. No report/task/audit
  body receives diagnostic answers. Remove the temporary hook in the actual
  fix release and clean up this one sample after a minimized regression exists.

## Evidence and next steps

Actual authenticated HTTP path: RED c1a447 (missing consented diagnostic),
GREEN 4dc2d1; entire semantic HTTP suite 28/28, 403f99. Scope tests: six Windows
passes/one Linux-only skip; Linux synthetic child-process RED c4e3c8 exposed
shared-mode acceptance, fixed GREEN ef78cc with all seven passing. These child
tests use temporary fixtures, not production business state. Bundle whitelist,
secret scan, JavaScript syntax and diff checks passed a5c041/e10225.

Release only through the existing exact-source standard gate, same-bundle dry
run/apply and independent verification. Enable scoped control after deployment,
send the original C request once through the Jiejing browser, then disable and
read its sanitized sample. Replay actual failures locally before any fix.
Do not infer C completion from this diagnostic's green tests.

## Closure and minimal regression

On fdab5fc the one approved request completed and the capture was disabled.
The initial answer and its existing repair were replayed through the real
validator. The extracted unit fixtures contain public-source formats only:
explicit Item price versus Was/savings/bulk amounts, pending availability
labels, negative availability prose, candidate cards followed by product-title
tables and translated headers, and report-only semantic scope. No merchant
identity or stored conversation is committed.

Initial RED: all five focused cases failed before implementation.
Further RED covers seller-navigation prefixes before unit price, and the
negative promise not to generate Listing fields. Focused regression and real
authenticated local HTTP exercise corrected scope, report-only persistence,
two candidates, unchanged existing reports, idempotent replay and bounded
answer repair. These are offline fixtures, not production completion.

The final captured-answer replay removes price/ownership/negative-phrase
false positives but still rejects actual unsupported demand and current-sale
claims. It does not blanket-accept the captured reports.

Remote cleanup verified 2026-10-04T02:49:38Z: disabled=true, enabled=false,
sample_present=false (safe cleanup receipt kept locally). The local full sample
was deleted after minimized tests. Only those tests and non-content status
receipts remain. The temporary capture module, hooks, test and packaging entries
are removed by this fix candidate. No customer report or product was deleted.

This fix still requires its own complete release gate, same-bundle deployment
and actual C browser acceptance. A/B are not to be regenerated.

## Post-release findings: item search scope and diagnostic retirement

2637426 passed its 273-check release gate and was deployed. The original C
request then selected the correct report-only semantic plan but produced zero
eligible sources: two broad eBay queries returned eight filtered results.
One explicit item-page follow-up obtained five sources, but the answer still
failed the current-availability guard. This failure is not a successful C
acceptance and no new answer-body diagnostic was enabled.

The local follow-up fixes are narrow:

- Constrain the evidence adapter's queries to eBay-US item pages, matching its
  existing returned-URL boundary. Preserve model-selected subjects, keywords,
  exclusions, query count and the original semantic plan; no keyword router.
  Preserve already-scoped `/itm` and `/itm/` queries exactly. The full chat
  regression initially found nine failures from unnecessary slash rewriting;
  this compatibility correction restores all 21 chat tests without weakening
  source attribution or changing the tests' assertions.
- A closed list such as `当前在售、销量、利润均未验证` shares one negative
  predicate. Do not split its first noun into a positive current-sale claim.
  Independent affirmative clauses must still fail. RED tests cover the list
  alone and within surrounding prose. This is an independently reproduced
  false positive, not proof that the uncaptured follow-up used that wording.
- The production base-release copy inherited the deleted one-shot diagnostic
  module. Its callsites and control were absent and the sample was already
  cleaned, but physical removal was not complete. Exclude exactly the module
  and its test when assembling the next candidate; preserve the previous
  release, runtime data, private configuration and rollback images. The
  staging patch retires the same two code files explicitly.

Unit tests plus the authenticated local HTTP path check two candidate reports,
unchanged existing facts, report-only scope and rejection of an independent
positive current-sale statement. Deployment contracts check the exclusions.
Only the new release's actual browser result can establish whether C passes.
