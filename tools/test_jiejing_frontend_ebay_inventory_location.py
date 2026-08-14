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
