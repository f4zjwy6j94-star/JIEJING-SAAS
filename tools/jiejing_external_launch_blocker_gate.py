#!/usr/bin/env python3
"""Read-only gate for clean-account eBay validation and formal billing launch.

The gate never starts OAuth, calls an eBay write API, or creates a payment.
It converts public health/readiness evidence into an operator-safe next step.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


CONTRACT_VERSION = "2026-07-11-external-launch-blocker-gate-v1"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="https://app.jiejing.shop")
    args = parser.parse_args()
    base_url = args.base_url.rstrip("/")
    health = _get_json(f"{base_url}/health")
    deep = _get_json(f"{base_url}/health/deep")
    readiness_payload = _get_json(f"{base_url}/readiness/product-saas")
    report = build_gate(health, deep, readiness_payload.get("readiness") or {})
    report["base_url"] = base_url.split("?", 1)[0]
    report["checked_at"] = datetime.now(timezone.utc).isoformat()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["preparation_gate_passed"] else 1


def build_gate(health: dict[str, Any], deep: dict[str, Any], readiness: dict[str, Any]) -> dict[str, Any]:
    evidence = readiness.get("product_evidence") if isinstance(readiness.get("product_evidence"), dict) else {}
    provider_status = readiness.get("provider_status") if isinstance(readiness.get("provider_status"), dict) else {}
    billing = provider_status.get("billing") if isinstance(provider_status.get("billing"), dict) else {}
    items = {item.get("key"): item for item in readiness.get("items") or [] if isinstance(item, dict)}
    refresh_count = int(evidence.get("ebay_token_refresh_success_count") or 0)
    public_healthy = health.get("status") == "ok" and not deep.get("request_failed")
    beta_ready = readiness.get("beta_ready") is True
    production_ready = readiness.get("production_ready") is True
    real_customers_allowed = readiness.get("can_accept_real_customers") is True
    real_writes_enabled = readiness.get("real_platform_writes_enabled") is True

    ebay_ready = refresh_count > 0 and real_writes_enabled and production_ready
    formal_billing_ready = (
        billing.get("external_paid_provider_configured") is True
        and billing.get("billing_ready_for_paid_launch") is True
        and billing.get("public_charging_allowed") is True
        and production_ready
    )
    boundary_safe = (
        billing.get("frontend_gets_payment_secret") is False
        and billing.get("frontend_can_grant_quota") is False
        and billing.get("triggers_real_charge") is False
        and readiness.get("secret_exposed") is False
    )
    preparation_gate_passed = public_healthy and beta_ready and boundary_safe and not real_customers_allowed

    return {
        "contract_version": CONTRACT_VERSION,
        "status": "prepared_but_externally_blocked" if preparation_gate_passed and not (ebay_ready and formal_billing_ready) else "ready",
        "preparation_gate_passed": preparation_gate_passed,
        "formal_public_launch_ready": bool(ebay_ready and formal_billing_ready and real_customers_allowed),
        "public_staging": {
            "healthy": public_healthy,
            "beta_ready": beta_ready,
            "production_ready": production_ready,
            "can_accept_real_customers": real_customers_allowed,
        },
        "clean_ebay_account_validation": {
            "status": "ready" if ebay_ready else "waiting_for_clean_new_account_and_refresh_proof",
            "ready": ebay_ready,
            "refresh_success_count": refresh_count,
            "existing_ebay_secret_ref_count": int(evidence.get("ebay_secret_refs") or 0),
            "readiness_status": (items.get("ebay_token_refresh") or {}).get("status") or "missing",
            "low_risk_draft_adapter_is_next_step": (items.get("execution_service") or {}).get("status") == "safe_demo_boundary",
            "old_frozen_account_allowed": False,
            "old_demo_product_allowed": False,
            "operator_approval_required_before_new_oauth": True,
            "oauth_started_by_this_gate": False,
            "real_platform_write_performed": False,
        },
        "formal_merchant_payment": {
            "status": "ready" if formal_billing_ready else "formal_provider_still_blocked",
            "ready": formal_billing_ready,
            "provider": billing.get("provider") or "not_configured",
            "external_paid_provider_configured": billing.get("external_paid_provider_configured") is True,
            "public_charging_allowed": billing.get("public_charging_allowed") is True,
            "next_blocker": billing.get("next_paid_launch_blocker") or "formal_provider_evidence_missing",
            "frontend_gets_payment_secret": billing.get("frontend_gets_payment_secret") is True,
            "frontend_can_grant_quota": billing.get("frontend_can_grant_quota") is True,
            "real_charge_performed": False,
        },
        "next_actions": [
            "finish_internal_product_acceptance_without_real_ebay_or_payment_actions",
            "wait_for_operator_confirmation_of_a_clean_new_ebay_account_before_oauth",
            "run_read_only_account_health_and_token_refresh_proof_before_any_draft_write",
            "select_and verify_a_formal_hosted_payment_provider_before_public_charging",
        ],
        "no_oauth_started": True,
        "no_real_platform_write_performed": True,
        "no_real_charge_performed": True,
        "secret_exposed": False,
    }


def _get_json(url: str) -> dict[str, Any]:
    request = Request(
        url,
        headers={"accept": "application/json", "cache-control": "no-store", "user-agent": "Mozilla/5.0 JiejingLaunchGate/1.0"},
    )
    try:
        with urlopen(request, timeout=20) as response:  # nosec B310 - operator-selected HTTPS base URL.
            payload = json.loads(response.read(1_000_000).decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        return {"request_failed": True, "error_type": type(exc).__name__, "secret_exposed": False}
    return payload if isinstance(payload, dict) else {"request_failed": True, "error_type": "non_object_json", "secret_exposed": False}


if __name__ == "__main__":
    raise SystemExit(main())
