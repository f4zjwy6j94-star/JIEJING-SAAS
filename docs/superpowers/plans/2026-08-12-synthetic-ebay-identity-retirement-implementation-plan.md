# Synthetic eBay Identity Retirement Implementation Plan

## Phase 0: Existing contracts

- Reuse account classification from `jiejing_saas/repository.py::_account_classification_for_email` and `users.account_classification`.
- Reuse the active eBay statuses and immutable identity metadata already consumed by `SaaSRepository.product_readiness_evidence`.
- Reuse value-free audit insertion through `SaaSRepository._insert_audit`.
- Preserve the account-deletion transaction and same-store multi-row behavior in `SaaSRepository.accept_ebay_account_deletion_event`.
- Do not invent a public merchant delete/disconnect route; remediation remains an operator-only CLI.

## Phase 1: RED - retirement and ambiguity contracts

Create `tools/test_jiejing_synthetic_ebay_identity_retirement.py` through repository public methods and a temporary SQLite database.

Verify the current code fails to provide:

- a dry-run synthetic conflict plan;
- exact-phrase apply retirement;
- merchant preservation and readiness warning closure; and
- fail-closed cross-owner deletion intake.

Run only this test until the first observable failure is captured.

## Phase 2: GREEN - repository boundary

Implement a small public interface on `SaaSRepository`:

- `synthetic_ebay_identity_retirement_plan()` for a value-free dry-run; and
- `retire_synthetic_ebay_identity_conflicts(...)` for exact-confirmed transactional apply.

Add an internal candidate collector that classifies active owners without returning selectors. Update account-deletion matching to quarantine distinct-owner ambiguity. Do not change merchant-facing APIs or readiness thresholds.

Verification:

- the new focused test passes;
- existing account-deletion and readiness tests pass; and
- SQLite and Postgres-compatible SQL uses only supported repository adapter syntax.

## Phase 3: Operator CLI

Add `tools/jiejing_retire_synthetic_ebay_identity_conflicts.py`.

- Default invocation is dry-run.
- Apply requires `--apply --confirm RETIRE_SYNTHETIC_EBAY_IDENTITY_CONFLICTS`.
- Output contains only counts/status/booleans.
- The CLI never resolves or prints Vault material.

Add the focused test to `tools/jiejing_precloud_deployment_gate.py`.

## Phase 4: Full verification and staging

Run focused account-deletion, backend, readiness, Postgres cutover, P0 security, syntax, secret, and diff checks. Run the complete precloud gate. After review, commit and push, run Doctor, deployment dry-run, apply, and post-Doctor.

On staging, run the new CLI dry-run first. Apply only if it reports exactly one eligible synthetic connection, exactly one merchant owner, and zero merchant conflicts. Re-run dry-run and public readiness afterward. Merchant eBay OAuth, sync, token refresh, payment, and Listing writes are forbidden during this remediation.
