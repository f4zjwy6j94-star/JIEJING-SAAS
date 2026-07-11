#!/usr/bin/env python3
"""Regression for the side-effect-free external launch blocker gate."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.jiejing_external_launch_blocker_gate import build_gate  # noqa: E402


def main() -> int:
    readiness = {
        "beta_ready": True,
        "production_ready": False,
        "can_accept_real_customers": False,
        "real_platform_writes_enabled": False,
        "secret_exposed": False,
        "items": [
            {"key": "ebay_token_refresh", "status": "refresh_blocked"},
            {"key": "execution_service", "status": "safe_demo_boundary"},
        ],
        "product_evidence": {"ebay_token_refresh_success_count": 0, "ebay_secret_refs": 0},
        "provider_status": {
            "billing": {
                "provider": "stripe_test_mock",
                "external_paid_provider_configured": False,
                "billing_ready_for_paid_launch": False,
                "public_charging_allowed": False,
                "next_paid_launch_blocker": "test_billing_provider_not_allowed_for_paid_launch",
                "frontend_gets_payment_secret": False,
                "frontend_can_grant_quota": False,
                "triggers_real_charge": False,
            }
        },
    }
    gate = build_gate({"status": "ok"}, {"status": "ok"}, readiness)
    if gate.get("preparation_gate_passed") is not True:
        return fail("private-beta preparation should pass while external gates remain blocked")
    if gate.get("formal_public_launch_ready") is not False:
        return fail("gate must not claim formal public launch readiness")
    ebay = gate.get("clean_ebay_account_validation") or {}
    billing = gate.get("formal_merchant_payment") or {}
    if ebay.get("ready") is not False or ebay.get("oauth_started_by_this_gate") is not False:
        return fail("clean-account validation must stay blocked without starting OAuth")
    if ebay.get("old_frozen_account_allowed") is not False or ebay.get("real_platform_write_performed") is not False:
        return fail("eBay gate must preserve frozen-account and write boundaries")
    if billing.get("ready") is not False or billing.get("real_charge_performed") is not False:
        return fail("formal billing must stay blocked without charging")
    if billing.get("frontend_gets_payment_secret") is not False or billing.get("frontend_can_grant_quota") is not False:
        return fail("frontend must not receive secrets or grant quota")
    for key in ["no_oauth_started", "no_real_platform_write_performed", "no_real_charge_performed"]:
        if gate.get(key) is not True:
            return fail(f"missing safe boundary {key}")
    if gate.get("secret_exposed") is not False:
        return fail("gate must not expose secrets")
    print("PASS jiejing_external_launch_blocker_gate")
    return 0


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
