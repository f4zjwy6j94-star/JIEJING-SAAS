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
