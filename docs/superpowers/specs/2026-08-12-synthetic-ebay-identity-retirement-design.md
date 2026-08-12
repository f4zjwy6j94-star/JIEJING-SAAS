# Synthetic eBay Identity Retirement Design

## Context

The public readiness packet currently reports `duplicate_identity_review_required` because one immutable eBay seller identity is present on two active Jiejing connections. Read-only production inspection proved that the two owners are different companies: one is the current `merchant` workspace and the older one is a `synthetic_test` account whose store stage is `oauth_staging_validation`.

The duplicate is real data, so merely hiding synthetic rows from readiness would leave two safety defects:

1. a synthetic credential reference would remain active after the test finished; and
2. an official account-deletion notification could select one of two tenant owners by row order.

No raw identity selector, token, secret reference value, company ID, store ID, or user email may be printed by the remediation path.

## Decision

Add a narrow repository operation and local operator CLI that retire only synthetic eBay identity conflicts. The operation is dry-run by default and requires the exact phrase `RETIRE_SYNTHETIC_EBAY_IDENTITY_CONFLICTS` in apply mode.

A connection is eligible only when all of these statements are true:

- it is an active eBay connection;
- its company has at least one `synthetic_test` default account and no `merchant` default account;
- its creator is a `synthetic_test` account;
- its store stage is exactly `oauth_staging_validation`;
- it has an immutable backend eBay user selector;
- the same selector is owned by exactly one active merchant company/store; and
- that selector is not shared by two or more merchant owners.

Apply mode performs one transaction. It changes the eligible connection to `retired_synthetic_test`, clears its scopes and immutable identity selectors, revokes the associated secret reference as `revoked_synthetic_test`, and writes a fixed value-free audit event. It does not delete the company, user, store, task, report, audit history, Vault data, or merchant connection.

The official eBay account-deletion intake must also fail closed when an immutable identity resolves to more than one distinct company/store. It records a sanitized `ambiguous_identity_review_required` receipt and creates no deletion job. Multiple connection rows for one company/store remain one logical owner and keep the existing scoped-deletion behavior.

## Data flow

1. Read active eBay connection rows and load identity metadata only inside the repository boundary.
2. Classify owners with the persisted `users.account_classification` field and the store stage.
3. Return only counts, status codes, booleans, and `secret_exposed=false` to the CLI.
4. In apply mode, recompute eligibility inside the write transaction before updating anything.
5. Re-run product readiness. The merchant connection remains active and mapped; the synthetic connection no longer contributes an active duplicate.

## Error handling

- Missing or wrong confirmation phrase: fail closed with no mutation.
- Two merchant owners for one identity: no synthetic retirement for that identity; readiness remains blocked for owner review.
- Synthetic company mixed with a merchant default account: ineligible and unchanged.
- Wrong store stage, missing selector, missing secret reference, or malformed metadata: ineligible and unchanged.
- Second apply: idempotent, reports zero new retirements.
- Audit or update failure: the transaction rolls back.

## Verification

The focused public-interface test must prove:

- dry-run reports one eligible synthetic connection and mutates nothing;
- wrong confirmation mutates nothing;
- apply retires only the synthetic connection and secret reference;
- the merchant connection and its refresh secret remain active;
- readiness changes from one duplicate to zero without deleting history;
- a real merchant-versus-merchant collision remains blocked;
- account-deletion intake quarantines distinct-owner ambiguity but still accepts duplicate rows belonging to one store; and
- no returned or logged structure contains identity selectors or credential material.

The final release still requires the focused account-deletion, readiness, Postgres, security, secret-scan, and full precloud gates.
