#!/usr/bin/env python3
"""Regression tests for eBay account-health gating before real publish."""

from __future__ import annotations

import sys
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_runtime.execution import ExecutionRequest, ExecutionService  # noqa: E402


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def _base_payload() -> dict:
    return {
        "account_health": {
            "status": "clear",
            "selling_status": "active",
            "payout_status": "available",
            "restrictions": [],
        },
        "listing": {
            "sku": "JJ-ACCOUNT-HEALTH-001",
            "title": "Account Health Gate Test Product",
            "description_html": "<p>Account health gate test product.</p>",
            "category_id": "20687",
            "condition": "NEW",
            "price": {"value": "12.99", "currency": "USD"},
            "quantity": 1,
            "item_specifics": {"Brand": "Unbranded", "Type": "Test Product"},
            "merchant_location_key": "default",
        },
        "business_policies": {
            "fulfillment_policy_id": "fulfillment-policy",
            "payment_policy_id": "payment-policy",
            "return_policy_id": "return-policy",
        },
        "supplier_facts": {
            "package_weight_g": 180,
            "package_dimensions_cm": {"length": 10, "width": 8, "height": 4},
            "material": "Plastic",
            "item_location": "US",
        },
        "asset_manifest": {"assets": [{"url": "https://example.com/image.jpg"}]},
        "finance_review": {"net_profit_money": {"value": "3.20", "currency": "USD"}},
    }


def _request(payload: dict) -> ExecutionRequest:
    return ExecutionRequest(
        action_type="publish_listing",
        task_id="task_account_health",
        user_id="user_account_health",
        company_id="company_account_health",
        store_id="store_account_health",
        platform="ebay",
        confirmation_id="confirm_account_health",
        confirmed_by="user_account_health",
        confirmed_at="2026-06-11T00:00:00+00:00",
        idempotency_key="account-health-publish-001",
        payload=payload,
    )


def main() -> int:
    service = ExecutionService(demo_mode=False)

    healthy = service.preflight(_request(_base_payload()))
    if healthy.get("status") != "ready_for_platform_adapter":
        return fail(f"healthy account should pass publish preflight: {healthy}")

    missing = deepcopy(_base_payload())
    missing.pop("account_health")
    missing_preflight = service.preflight(_request(missing))
    if missing_preflight.get("status") != "blocked_missing_execution_facts":
        return fail(f"missing account health should block publish: {missing_preflight}")
    if "account_health.status" not in missing_preflight.get("missing_fields", []):
        return fail(f"missing account-health snapshot should be visible: {missing_preflight}")

    frozen = deepcopy(_base_payload())
    frozen["account_health"] = {
        "status": "frozen",
        "selling_status": "restricted",
        "payout_status": "hold",
        "restrictions": ["account restriction", "payout frozen"],
    }
    frozen_preflight = service.preflight(_request(frozen))
    issue_keys = {issue.get("key") for issue in frozen_preflight.get("issues", [])}
    if frozen_preflight.get("status") != "blocked_missing_execution_facts" or "account_health.status" not in issue_keys:
        return fail(f"frozen or restricted account should block real publish: {frozen_preflight}")

    print("PASS account_health_preflight_gate")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

