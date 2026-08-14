#!/usr/bin/env python3
"""Static fail-closed contract for confirmation-gated eBay inventory locations."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "app.js"


def require(source: str, marker: str, message: str) -> None:
    if marker not in source:
        raise AssertionError(message)


def main() -> None:
    app = APP_JS.read_text(encoding="utf-8")

    for marker, message in [
        (
            'data-saas-action="create-ebay-inventory-location-confirmation"',
            "Listing must expose a dedicated confirmation-only inventory-location action",
        ),
        (
            'data-saas-action="execute-ebay-inventory-location"',
            "Listing must expose a separate approved execution action",
        ),
        (
            'data-saas-action="reconcile-ebay-inventory-location"',
            "Listing must expose a read-only reconciliation action after an uncertain write",
        ),
        (
            'async function createSaasInventoryLocationConfirmation()',
            "the frontend must implement the dedicated confirmation intake",
        ),
        (
            '/ebay-inventory-location/confirmation',
            "the first action must call the confirmation-only route",
        ),
        (
            'async function executeSaasApprovedInventoryLocation()',
            "the frontend must implement the separate approved execution step",
        ),
        (
            '/ebay-inventory-location/execute',
            "the second action must call the one-shot execution route",
        ),
        (
            'async function reconcileSaasInventoryLocation()',
            "the frontend must implement the read-only reconciliation step",
        ),
        (
            '/ebay-inventory-location/reconcile',
            "the reconciliation action must call the dedicated backend route",
        ),
        (
            'isSaasExactInventoryLocationConfirmation',
            "inventory-location cards must have an exact tenant/store/payload contract",
        ),
        (
            'verifySaasInventoryLocationConfirmations',
            "the displayed card must verify the canonical location payload digest",
        ),
        (
            'saasVerifiedInventoryLocationConfirmations',
            "digest verification must be held only in page-local memory",
        ),
        (
            'isSaasInventoryLocationSensitiveConfirmation',
            "malformed inventory-location cards must not fall through as ordinary approvals",
        ),
        (
            'isSaasUniqueCurrentInventoryLocationConfirmation',
            "duplicate or wrong-store inventory-location cards must fail closed",
        ),
        (
            'ebay-inventory-location-current-store',
            "the confirmation ID must use an opaque DOM binding",
        ),
        (
            'saasInventoryLocationExecutionAttemptKeys',
            "one page may attempt an exact approved location only once",
        ),
        (
            'saasInventoryLocationReconciliationAttemptKeys',
            "one page may reconcile an exact uncertain location only once",
        ),
        (
            'activeSaasStore()',
            "the inventory-location flow must bind the active store",
        ),
    ]:
        require(app, marker, message)

    create_start = app.index("async function createSaasInventoryLocationConfirmation()")
    execute_start = app.index("async function executeSaasApprovedInventoryLocation()")
    create_flow = app[create_start:execute_start]
    execute_end = app.index("async function", execute_start + 20)
    execute_flow = app[execute_start:execute_end]
    if "/ebay-inventory-location/execute" in create_flow:
        raise AssertionError("creating a location confirmation must never execute the provider write")
    if "state.saasStores[0]" in create_flow or "state.saasStores[0]" in execute_flow:
        raise AssertionError("inventory-location actions must never fall back to the first tenant store")
    if execute_flow.index("saasInventoryLocationExecutionAttemptKeys.add(attemptKey)") >= execute_flow.index(
        "/ebay-inventory-location/execute"
    ):
        raise AssertionError("the page-local one-shot claim must happen before the execution POST")

    reconcile_start = app.index("async function reconcileSaasInventoryLocation()")
    reconcile_end = app.index("async function", reconcile_start + 20)
    reconcile_flow = app[reconcile_start:reconcile_end]
    if "/ebay-inventory-location/execute" in reconcile_flow:
        raise AssertionError("read-only reconciliation must never call the provider execution route")
    if reconcile_flow.index("saasInventoryLocationReconciliationAttemptKeys.add(attemptKey)") >= reconcile_flow.index(
        "/ebay-inventory-location/reconcile"
    ):
        raise AssertionError("the page-local reconciliation claim must happen before the read-only request")
    for marker in [
        'reconciliation.reconciled_from_provider_read !== true',
        'reconciliation.writes_to_ebay !== false',
        'reconciliation.public_listing_created !== false',
        'reconciliation.secret_exposed !== false',
    ]:
        require(reconcile_flow, marker, "read-only reconciliation must validate every no-write response flag")

    approve_start = app.index("async function approveFirstSaasConfirmation")
    approve_end = app.index("async function loginSaasBackendSession", approve_start)
    approve = app[approve_start:approve_end]
    require(approve, "isExactInventoryLocation", "inventory-location approval needs a decision-only branch")
    branch_start = approve.index("if (isExactInventoryLocation")
    branch_end = approve.index("const preflight", branch_start)
    if "/preflight" in approve[branch_start:branch_end] or "/execute" in approve[branch_start:branch_end]:
        raise AssertionError("approving an inventory location must not execute it automatically")

    print("PASS test_jiejing_frontend_ebay_inventory_location")


if __name__ == "__main__":
    main()
