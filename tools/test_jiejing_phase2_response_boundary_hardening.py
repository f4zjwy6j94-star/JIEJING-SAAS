#!/usr/bin/env python3
"""Focused fail-closed checks for the Phase 2 merchant/public response boundary."""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def canonical_launch() -> dict[str, Any]:
    return {
        "contract_version": "2026-07-27-mainland-payment-launch-v1",
        "market": "mainland_china",
        "primary_provider": "wechat_pay_native",
        "checkout_mode": "native_qr",
        "billing_mode": "one_time_30_day_plan",
        "configuration": {"required_count": 9, "completed_count": 9, "complete": True},
        "code_capabilities": {
            "signed_payment_callback_implemented": True,
            "signed_refund_callback_implemented": True,
            "real_order_creation_implemented": True,
            "authenticated_order_query_implemented": True,
            "quota_entitlement_persistence_implemented": True,
            "high_risk_confirmation_boundary_implemented": True,
        },
        "acceptance_evidence": {
            "contract_version": "2026-07-27-domestic-payment-acceptance-evidence-v2",
            "provider": "wechat_pay_native",
            "acceptance_kind": "owner_approved_one_cny_live_acceptance",
            "controlled_acceptance_proven": True,
            "verified_paid_order_count": 1,
            "public_charging_allowed": False,
            "charge_now_allowed": False,
            "triggers_real_charge": False,
            "calls_external_payment_api": False,
            "secret_exposed": False,
        },
        "controlled_acceptance_proven": True,
        "provider_checkout_ready": True,
        "production_environment": True,
        "refund_now_allowed": True,
        "mainland_payment_ready_for_owner_approval": True,
        "public_charging_allowed": False,
        "charge_now_allowed": False,
        "triggers_real_charge": False,
        "triggers_real_refund": False,
        "calls_external_payment_api": False,
        "calls_stripe_api": False,
        "real_platform_writes_enabled": False,
        "frontend_gets_payment_secret": False,
        "secret_exposed": False,
    }


def public_billing() -> dict[str, Any]:
    return {
        "provider": "wechat_pay_native",
        "checkout_mode": "native_qr",
        "billing_mode": "one_time_30_day_plan",
        "provider_configured": True,
        "payment_path_status": "controlled_acceptance_proven_public_charging_closed",
        "mainland_payment_ready_for_owner_approval": True,
        "billing_ready_for_private_beta": False,
        "billing_ready_for_paid_launch": False,
        "configured_component_count": 9,
        "required_component_count": 9,
        "verified_paid_order_count": 1,
        "quota_enforcement_enabled": True,
        "next_paid_launch_blocker": "merchant_payment_public_cutover_not_approved",
        "merchant_launch_path": {
            "contract_version": "2026-07-27-merchant-mainland-payment-path-v1",
            "current_stage": "controlled_acceptance_proven_public_charging_closed",
            "public_paid_launch_allowed": False,
            "charge_now_allowed": False,
            "triggers_real_charge": False,
            "backend_confirmation_required_before_entitlement": True,
            "frontend_can_grant_entitlement": False,
            "frontend_can_grant_quota": False,
            "secret_exposed": False,
        },
        "domestic_payment": {
            "provider": "wechat_pay_native",
            "checkout_mode": "native_qr",
            "billing_mode": "one_time_30_day_plan",
            "status": "controlled_acceptance_proven",
            "configured_component_count": 9,
            "required_component_count": 9,
            "controlled_acceptance_proven": True,
            "verified_paid_order_count": 1,
            "public_charging_allowed": False,
            "charge_now_allowed": False,
            "triggers_real_charge": False,
            "triggers_real_refund": False,
            "calls_external_payment_api": False,
            "frontend_gets_payment_secret": False,
            "secret_exposed": False,
        },
        "public_charging_allowed": False,
        "charge_now_allowed": False,
        "triggers_real_charge": False,
        "triggers_real_refund": False,
        "calls_external_payment_api": False,
        "real_platform_writes_enabled": False,
        "frontend_gets_payment_secret": False,
        "frontend_can_grant_quota": False,
        "secret_exposed": False,
    }


def main() -> int:
    from jiejing_saas.api_server import SaaSBackendHandler, _public_safe_billing_summary
    from jiejing_saas.billing_payment_options import validate_mainland_payment_launch_for_public
    from jiejing_saas.readiness import _validated_public_mainland_payment

    ready = canonical_launch()
    shared = validate_mainland_payment_launch_for_public(ready)
    readiness = _validated_public_mainland_payment(ready)
    merchant = SaaSBackendHandler._merchant_safe_billing_plan({"mainland_payment_launch": ready})["mainland_payment"]
    if not shared.get("mainland_payment_ready_for_owner_approval"):
        return fail("valid canonical mainland launch must remain owner-ready at the sanitized boundary")
    if readiness.get("configured_component_count") != merchant.get("configured_component_count"):
        return fail("merchant and readiness boundaries must share canonical counts")

    contradictory_launch = copy.deepcopy(ready)
    contradictory_launch["configuration"] = {"required_count": 9, "completed_count": 9, "complete": False}
    readiness_bad = _validated_public_mainland_payment(contradictory_launch)
    merchant_bad = SaaSBackendHandler._merchant_safe_billing_plan(
        {"mainland_payment_launch": contradictory_launch}
    )["mainland_payment"]
    for label, value in (("readiness", readiness_bad), ("merchant", merchant_bad)):
        if value.get("mainland_payment_ready_for_owner_approval") is not False:
            return fail(f"{label} boundary accepted contradictory configuration completion")
        if value.get("configured_component_count") != 0 or value.get("required_component_count") != 0:
            return fail(f"{label} boundary did not fail closed with identical zero counts")

    for configured, required, verified in ((0, 0, 0), (8, 9, 1), (9, 9, 0)):
        candidate = public_billing()
        candidate["configured_component_count"] = configured
        candidate["required_component_count"] = required
        candidate["verified_paid_order_count"] = verified
        candidate["domestic_payment"]["configured_component_count"] = configured
        candidate["domestic_payment"]["required_component_count"] = required
        candidate["domestic_payment"]["verified_paid_order_count"] = verified
        candidate["domestic_payment"]["controlled_acceptance_proven"] = verified > 0
        safe = _public_safe_billing_summary(candidate)
        if safe.get("mainland_payment_ready_for_owner_approval") is not False:
            return fail(f"public billing accepted contradictory owner-ready counts {(configured, required, verified)}")
        if safe.get("provider_configured") is not False:
            return fail(f"public billing exposed provider-configured success for {(configured, required, verified)}")

    readiness_source = {
        "service": "jiejing-saas-backend",
        "environment": "staging",
        "items": [
            {
                "key": "payment_status",
                "label": "Safe payment status",
                "status": "blocked",
                "severity": "blocker",
                "detail": "Bearer must-not-cross-boundary",
                "next_action": "secret_ref=must-not-cross-boundary",
                "arbitrary": {"credential": "must-not-cross-boundary"},
            }
        ],
        "product_evidence": {
            "latest_ebay_packet_status": "created",
            "latest_ebay_packet_source_mode": "official_api",
            "latest_ebay_packet_present_resource_keys": ["store_profile", "Bearer must-not-cross-boundary"],
            "latest_ebay_packet_missing_resource_keys": ["account_business_policies"],
            "internal": {"secret_ref": "must-not-cross-boundary"},
        },
        "provider_status": {
            "billing": public_billing(),
            "ai_ceo_platform_model": {
                "provider": "Bearer must-not-cross-boundary",
                "model": "secret_ref=must-not-cross-boundary",
                "status": "blocked",
            },
            "public_search": {
                "provider": "tavily",
                "endpoint_host": "Bearer must-not-cross-boundary",
            },
            "media_generation": {
                "status": "dry_run_review_chain_ready_missing_media_driver",
                "customer_visible_summary": "Safe summary",
                "next_action": "Bearer must-not-cross-boundary",
            },
        },
    }
    original = copy.deepcopy(readiness_source)
    safe_readiness = SaaSBackendHandler._public_readiness_summary(readiness_source, authenticated=False)
    if readiness_source != original:
        return fail("public readiness sanitizer mutated its source")
    serialized = json.dumps(safe_readiness, ensure_ascii=False).lower()
    if "must-not-cross-boundary" in serialized or "secret_ref" in serialized or "bearer " in serialized:
        return fail("public readiness leaked raw nested secret-like diagnostic text")
    safe_readiness["items"][0]["label"] = "mutated"
    safe_readiness["product_evidence"]["latest_ebay_packet_present_resource_keys"].append("mutated")
    if readiness_source != original:
        return fail("public readiness response shares nested source containers")

    summary_source = {
        "mainland_payment_launch": ready,
        "provider": {
            "external_paid_provider_configured": True,
            "test_billing_provider_configured": True,
            "manual_beta_private_provider_configured": True,
            "payment_flow_test_mode": True,
        },
        "paid_launch_blockers": ["raw_secret_ref=must-not-cross-boundary"],
        "billing_test_rehearsal_summary": {
            "contract_version": "2026-06-18-no-charge-billing-rehearsal",
            "ready": True,
            "ready_count": 1,
            "total_count": 1,
            "blocked_count": 0,
            "next_step": "",
            "steps": [{"key": "test_provider_selected", "status": "ready", "severity": "info"}],
            "evidence_id": "must-not-cross-boundary",
        },
        "subscription_quota_shutdown_closure": {
            "contract_version": "2026-06-20-subscription-quota-shutdown-closure",
            "ready": True,
            "ready_count": 1,
            "total_count": 1,
            "blocked_count": 0,
            "steps": [{"key": "quota_guardrail_blocks_metered_work", "status": "ready"}],
        },
        "billing_incident_runbook": {
            "contract_version": "2026-07-01-billing-incident-runbook-v1",
            "ready_count": 1,
            "total_count": 1,
            "blocked_count": 0,
            "cards": [{"key": "payment_failed", "status": "ready", "title": "Payment failed"}],
        },
        "customer_billing_trust_packet": {
            "contract_version": "2026-07-01-customer-billing-trust-packet-v1",
            "ready_count": 1,
            "total_count": 1,
            "blocked_count": 0,
            "cards": [{"key": "entitlement_recovery_boundary", "status": "ready", "title": "Recovery"}],
            "provider_reference": "must-not-cross-boundary",
        },
    }
    safe_plan = SaaSBackendHandler._merchant_safe_billing_plan(summary_source)
    for key in (
        "paid_launch_blockers",
        "billing_test_rehearsal_summary",
        "subscription_quota_shutdown_closure",
        "billing_incident_runbook",
        "customer_billing_trust_packet",
    ):
        if key not in safe_plan:
            return fail(f"merchant Settings summary missing: {key}")
    for legacy_key in (
        "external_paid_provider_configured",
        "test_billing_provider_configured",
        "manual_beta_private_provider_configured",
        "payment_flow_test_mode",
    ):
        if legacy_key in safe_plan.get("provider", {}):
            return fail(f"merchant response retained legacy provider diagnostic {legacy_key}")
    if "must-not-cross-boundary" in json.dumps(safe_plan, ensure_ascii=False).lower():
        return fail("merchant summary allowlists leaked internal evidence")

    print("PASS phase2 response boundary hardening")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
