#!/usr/bin/env python3
"""Read-only gate for clean-account eBay validation and formal billing launch.

The gate never starts OAuth, calls an eBay write API, or creates a payment.
It converts public health/readiness evidence into an operator-safe next step.
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


CONTRACT_VERSION = "2026-07-15-external-launch-blocker-gate-v4"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="https://app.jiejing.shop")
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--attempts", type=int, default=2)
    args = parser.parse_args()
    base_url = args.base_url.rstrip("/")
    health = _get_json(f"{base_url}/health", timeout=args.timeout, attempts=args.attempts)
    deep = _get_json(f"{base_url}/health/deep", timeout=args.timeout, attempts=args.attempts)
    readiness_payload = _get_json(f"{base_url}/readiness/product-saas", timeout=args.timeout, attempts=args.attempts)
    readiness = readiness_payload.get("readiness") if isinstance(readiness_payload.get("readiness"), dict) else readiness_payload
    report = build_gate(health, deep, readiness)
    report["base_url"] = base_url.split("?", 1)[0]
    report["checked_at"] = datetime.now(timezone.utc).isoformat()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["preparation_gate_passed"] else 1


def build_gate(health: dict[str, Any], deep: dict[str, Any], readiness: dict[str, Any]) -> dict[str, Any]:
    probe_errors = [
        key
        for key, payload in (("health", health), ("deep", deep), ("readiness", readiness))
        if payload.get("request_failed") is True
    ]
    readiness_probe_failed = "readiness" in probe_errors
    evidence = readiness.get("product_evidence") if isinstance(readiness.get("product_evidence"), dict) else {}
    provider_status = readiness.get("provider_status") if isinstance(readiness.get("provider_status"), dict) else {}
    billing = provider_status.get("billing") if isinstance(provider_status.get("billing"), dict) else {}
    domestic_payment = billing.get("domestic_payment") if isinstance(billing.get("domestic_payment"), dict) else {}
    items = {item.get("key"): item for item in readiness.get("items") or [] if isinstance(item, dict)}
    refresh_count = int(evidence.get("ebay_token_refresh_success_count") or 0)
    operational_health = deep.get("operational_health") if isinstance(deep.get("operational_health"), dict) else deep
    database = operational_health.get("database") if isinstance(operational_health.get("database"), dict) else {}
    queue = operational_health.get("queue") if isinstance(operational_health.get("queue"), dict) else {}
    worker = operational_health.get("worker") if isinstance(operational_health.get("worker"), dict) else {}
    deep_ready = (
        operational_health.get("status") == "ready"
        and database.get("status") == "ready"
        and queue.get("status") == "ready"
        and worker.get("status") == "ready"
        and operational_health.get("secret_exposed") is False
    )
    public_healthy = health.get("status") == "ok" and deep_ready
    beta_ready = readiness.get("beta_ready") is True
    production_ready = readiness.get("production_ready") is True
    real_customers_allowed = readiness.get("can_accept_real_customers") is True
    real_writes_enabled = readiness.get("real_platform_writes_enabled") is True

    ebay_ready = refresh_count > 0 and real_writes_enabled and production_ready
    legacy_formal_billing_ready = (
        billing.get("external_paid_provider_configured") is True
        and billing.get("billing_ready_for_paid_launch") is True
        and billing.get("public_charging_allowed") is True
        and production_ready
    )
    domestic_acceptance_proven = (
        domestic_payment.get("controlled_acceptance_proven") is True
        or domestic_payment.get("status") == "controlled_acceptance_proven"
    )
    domestic_formal_billing_ready = (
        domestic_payment.get("real_checkout_ready") is True
        and domestic_acceptance_proven
        and billing.get("public_charging_allowed") is True
        and production_ready
    )
    formal_billing_ready = legacy_formal_billing_ready or domestic_formal_billing_ready
    boundary_safe = (
        billing.get("frontend_gets_payment_secret") is False
        and billing.get("frontend_can_grant_quota") is False
        and billing.get("triggers_real_charge") is False
        and readiness.get("secret_exposed") is False
    )
    preparation_gate_passed = not probe_errors and public_healthy and beta_ready and boundary_safe and not real_customers_allowed

    payment_status = (
        "readiness_probe_failed"
        if readiness_probe_failed
        else "ready"
        if formal_billing_ready
        else "controlled_acceptance_proven_public_charging_closed"
        if domestic_acceptance_proven
        else "formal_provider_still_blocked"
    )
    payment_provider = (
        "probe_unavailable"
        if readiness_probe_failed
        else
        domestic_payment.get("provider")
        if domestic_acceptance_proven or domestic_payment.get("real_checkout_ready") is True
        else billing.get("provider")
    ) or "not_configured"
    payment_next_blocker = (
        "retry_public_readiness_probe"
        if readiness_probe_failed
        else ""
        if formal_billing_ready
        else "merchant_payment_public_cutover_not_approved"
        if domestic_acceptance_proven
        else billing.get("next_paid_launch_blocker") or "formal_provider_evidence_missing"
    )
    next_actions = []
    if probe_errors:
        next_actions.append("retry_public_readiness_probe_before_changing_configuration")
    elif not ebay_ready:
        next_actions.extend(
            [
                "wait_for_operator_confirmation_of_a_clean_new_ebay_account_before_oauth",
                "run_read_only_account_health_and_token_refresh_proof_before_any_draft_write",
            ]
        )
    if not probe_errors and not formal_billing_ready:
        next_actions.append(
            "complete_wechat_pay_merchant_checkout_refund_and_operations_acceptance_before_public_cutover"
            if domestic_acceptance_proven
            else "select_and_verify_a_formal_hosted_payment_provider_before_public_charging"
        )

    if probe_errors:
        gate_status = "probe_failed"
    elif not public_healthy:
        gate_status = "public_staging_unhealthy"
    elif preparation_gate_passed and not (ebay_ready and formal_billing_ready):
        gate_status = "prepared_but_externally_blocked"
    elif ebay_ready and formal_billing_ready and real_customers_allowed:
        gate_status = "ready"
    else:
        gate_status = "internal_preparation_incomplete"

    return {
        "contract_version": CONTRACT_VERSION,
        "status": gate_status,
        "probe_errors": probe_errors,
        "preparation_gate_passed": preparation_gate_passed,
        "formal_public_launch_ready": bool(ebay_ready and formal_billing_ready and real_customers_allowed),
        "public_staging": {
            "healthy": public_healthy,
            "deep_ready": deep_ready,
            "beta_ready": beta_ready,
            "production_ready": production_ready,
            "can_accept_real_customers": real_customers_allowed,
        },
        "clean_ebay_account_validation": {
            "status": "readiness_probe_failed"
            if readiness_probe_failed
            else "ready"
            if ebay_ready
            else "waiting_for_clean_new_account_and_refresh_proof",
            "ready": ebay_ready,
            "refresh_success_count": refresh_count,
            "existing_ebay_secret_ref_count": int(evidence.get("ebay_secret_refs") or 0),
            "readiness_status": (items.get("ebay_token_refresh") or {}).get("status") or "missing",
            "low_risk_draft_adapter_ready": (items.get("execution_service") or {}).get("status")
            == "ebay_draft_save_adapter_ready_disabled",
            "controlled_draft_proof_is_next_step": (items.get("execution_service") or {}).get("status")
            in {"safe_demo_boundary", "ebay_draft_save_adapter_ready_disabled"},
            "old_frozen_account_allowed": False,
            "old_demo_product_allowed": False,
            "operator_approval_required_before_new_oauth": True,
            "oauth_started_by_this_gate": False,
            "real_platform_write_performed": False,
        },
        "formal_merchant_payment": {
            "status": payment_status,
            "ready": formal_billing_ready,
            "provider": payment_provider,
            "provider_configured": bool(
                billing.get("provider_configured") is True
                or (
                    domestic_acceptance_proven
                    and int(domestic_payment.get("configured_component_count") or 0) > 0
                    and int(domestic_payment.get("configured_component_count") or 0)
                    == int(domestic_payment.get("required_component_count") or 0)
                )
            ),
            "external_paid_provider_configured": billing.get("external_paid_provider_configured") is True,
            "controlled_acceptance_proven": domestic_acceptance_proven,
            "real_checkout_ready": domestic_payment.get("real_checkout_ready") is True,
            "configured_component_count": int(domestic_payment.get("configured_component_count") or 0),
            "required_component_count": int(domestic_payment.get("required_component_count") or 0),
            "public_charging_allowed": billing.get("public_charging_allowed") is True,
            "next_blocker": payment_next_blocker,
            "frontend_gets_payment_secret": billing.get("frontend_gets_payment_secret") is True,
            "frontend_can_grant_quota": billing.get("frontend_can_grant_quota") is True,
            "real_charge_performed": False,
        },
        "next_actions": next_actions,
        "completed_internal_actions": ["internal_product_acceptance"],
        "no_oauth_started": True,
        "no_real_platform_write_performed": True,
        "no_real_charge_performed": True,
        "secret_exposed": False,
    }


def _get_json(url: str, *, timeout: int = 30, attempts: int = 2) -> dict[str, Any]:
    request = Request(
        url,
        headers={"accept": "application/json", "cache-control": "no-store", "user-agent": "Mozilla/5.0 JiejingLaunchGate/1.0"},
    )
    bounded_timeout = max(1, min(int(timeout), 60))
    bounded_attempts = max(1, min(int(attempts), 3))
    last_error_type = "unknown"
    for attempt in range(1, bounded_attempts + 1):
        try:
            with urlopen(request, timeout=bounded_timeout) as response:  # nosec B310 - operator-selected HTTPS base URL.
                payload = json.loads(response.read(1_000_000).decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_error_type = type(exc).__name__
            if attempt < bounded_attempts:
                time.sleep(1)
            continue
        if isinstance(payload, dict):
            return payload
        last_error_type = "non_object_json"
        if attempt < bounded_attempts:
            time.sleep(1)
    return {
        "request_failed": True,
        "error_type": last_error_type,
        "attempts": bounded_attempts,
        "secret_exposed": False,
    }


if __name__ == "__main__":
    raise SystemExit(main())
