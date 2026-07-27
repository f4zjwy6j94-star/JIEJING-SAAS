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
                "provider": "wechat_pay_native",
                "provider_configured": True,
                "payment_path_status": "controlled_acceptance_proven_public_charging_closed",
                "external_paid_provider_configured": False,
                "billing_ready_for_paid_launch": False,
                "public_charging_allowed": False,
                "next_paid_launch_blocker": "test_billing_provider_not_allowed_for_paid_launch",
                "frontend_gets_payment_secret": False,
                "frontend_can_grant_quota": False,
                "triggers_real_charge": False,
                "domestic_payment": {
                    "provider": "wechat_pay_native",
                    "status": "controlled_acceptance_proven",
                    "configured_component_count": 9,
                    "required_component_count": 9,
                    "real_checkout_ready": False,
                    "charge_now_allowed": False,
                    "frontend_gets_payment_secret": False,
                },
            }
        },
    }
    deep = {
        "operational_health": {
            "status": "ready",
            "database": {"status": "ready"},
            "queue": {"status": "ready"},
            "worker": {"status": "ready"},
            "secret_exposed": False,
        }
    }
    gate = build_gate({"status": "ok"}, deep, readiness)
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
    if billing.get("provider") != "wechat_pay_native":
        return fail("gate should report the accepted mainland provider instead of the legacy test provider")
    if billing.get("status") != "controlled_acceptance_proven_public_charging_closed":
        return fail("gate should distinguish accepted WeChat Pay from an unconfigured formal provider")
    if billing.get("controlled_acceptance_proven") is not True or billing.get("public_charging_allowed") is not False:
        return fail("controlled payment proof must stay separate from public charging approval")
    if billing.get("provider_configured") is not True:
        return fail("gate should recognize the configured active domestic provider")
    if "select_and_verify_a_formal_hosted_payment_provider_before_public_charging" in gate.get("next_actions", []):
        return fail("gate must not ask the owner to select another provider after WeChat Pay acceptance")
    if "finish_internal_product_acceptance_without_real_ebay_or_payment_actions" in gate.get("next_actions", []):
        return fail("gate must not repeat internal product acceptance after preparation already passed")
    if billing.get("frontend_gets_payment_secret") is not False or billing.get("frontend_can_grant_quota") is not False:
        return fail("frontend must not receive secrets or grant quota")
    for key in ["no_oauth_started", "no_real_platform_write_performed", "no_real_charge_performed"]:
        if gate.get(key) is not True:
            return fail(f"missing safe boundary {key}")
    if gate.get("secret_exposed") is not False:
        return fail("gate must not expose secrets")

    degraded = {
        "operational_health": {
            "status": "degraded",
            "database": {"status": "ready"},
            "queue": {"status": "ready"},
            "worker": {"status": "not_ready"},
            "secret_exposed": False,
        }
    }
    degraded_gate = build_gate({"status": "ok"}, degraded, readiness)
    if degraded_gate.get("preparation_gate_passed") is not False:
        return fail("deep-health degradation must block preparation even when the shallow health endpoint is ok")

    probe_failed_gate = build_gate(
        {"status": "ok"},
        deep,
        {"request_failed": True, "error_type": "TimeoutError", "secret_exposed": False},
    )
    if probe_failed_gate.get("status") != "probe_failed":
        return fail("a readiness timeout must be reported as probe_failed, never ready")
    if probe_failed_gate.get("preparation_gate_passed") is not False:
        return fail("a readiness timeout cannot pass preparation")
    if probe_failed_gate.get("probe_errors") != ["readiness"]:
        return fail("the gate must identify the failed readiness probe")
    failed_billing = probe_failed_gate.get("formal_merchant_payment") or {}
    failed_ebay = probe_failed_gate.get("clean_ebay_account_validation") or {}
    if failed_billing.get("status") != "readiness_probe_failed" or failed_ebay.get("status") != "readiness_probe_failed":
        return fail("probe failure must not be reinterpreted as missing provider or seller configuration")
    if probe_failed_gate.get("next_actions") != ["retry_public_readiness_probe_before_changing_configuration"]:
        return fail("probe failure should request a retry instead of configuration changes")
    print("PASS jiejing_external_launch_blocker_gate")
    return 0


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
