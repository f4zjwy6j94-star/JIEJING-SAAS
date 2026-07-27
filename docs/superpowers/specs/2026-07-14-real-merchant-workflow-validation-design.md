# Real Merchant Workflow Validation Evidence

## Goal

Replace the manually editable release boolean for real merchant validation with
backend-derived, privacy-safe evidence. The result feeds the fixed public-launch
score but remains invisible to ordinary merchant accounts.

## Evidence Contract

A validated merchant path must contain all of the following for the same
`product_workflow` task:

1. The task completed successfully.
2. At least one runtime report was persisted.
3. At least one confirmation item was persisted.
4. The merchant made a decision in the confirmation center: approve, reject, or
   request revision.

Only companies owned by users classified as `merchant` count. Accounts classified
as `synthetic_test` never count, even when they contain complete workflow records.

The launch evidence passes only when both thresholds are met:

- at least 3 independent merchant companies have a validated path;
- at least 20 validated paths exist in total.

## Data Boundary

The snapshot returns aggregate counts, thresholds, status, and next action only.
It must not return email addresses, company names, user IDs, company IDs, store
IDs, raw prompts, report contents, confirmation contents, credentials, or provider
secrets.

The calculation is read-only. It does not trigger eBay OAuth, eBay reads or
writes, payments, refunds, advertising, inventory changes, or policy changes.

## Integration

`SaaSRepository.merchant_workflow_validation_snapshot()` is the source of truth.
The owner launch-control packet includes the sanitized snapshot and passes its
`passed` value into the fixed 100-point launch score. The static release evidence
file can no longer award the five real-merchant-validation points.

The internal owner panel shows progress as independent merchants and completed
paths. Ordinary merchant accounts continue to receive HTTP 403 for owner launch
control and never see this operational evidence.

## Failure Handling

Database/query failures degrade the owner packet to pending through the existing
safe-call boundary. Missing evidence never defaults to pass. Production readiness
and public charging remain false until the evidence and separate owner approvals
are complete.

## Verification

- synthetic accounts with complete records do not count;
- incomplete merchant paths do not count;
- decided complete paths count once per task;
- thresholds must both be satisfied;
- no identifiers or secret-like fields appear in the snapshot;
- SQLite and PostgreSQL use parameterized, compatible SQL;
- owner-only UI and endpoint access controls remain intact.
