#!/usr/bin/env python3
"""Focused fail-closed checks for the Phase 2 merchant/public response boundary."""

from __future__ import annotations

import copy
import json
import sys
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch


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


def isolated_product_readiness(plan: dict[str, Any]) -> dict[str, Any]:
    """Exercise the public readiness aggregator with unrelated gates held ready."""

    import jiejing_saas.readiness as readiness_module

    class RepositoryStub:
        @staticmethod
        def system_counts() -> dict[str, int]:
            return {"users": 1, "stores": 1}

        @staticmethod
        def product_readiness_evidence() -> dict[str, Any]:
            return {}

    class EbayStatusStub:
        @staticmethod
        def to_dict() -> dict[str, Any]:
            return {}

    def unrelated_ready(*_args: Any, **_kwargs: Any) -> Any:
        return readiness_module.ReadinessItem(
            "unrelated_test_item",
            "Unrelated test item",
            "ready",
            "info",
            "Held ready by the focused readiness aggregation test.",
            "",
        )

    unrelated_item_builders = (
        "_environment_item",
        "_session_secret_item",
        "_cors_item",
        "_team_permission_item",
        "_database_item",
        "_database_adapter_item",
        "_database_migration_item",
        "_queue_item",
        "_queue_adapter_item",
        "_queue_worker_plan_item",
        "_infrastructure_driver_item",
        "_monitoring_item",
        "_backup_item",
        "_provider_job_runner_item",
        "_independent_runtime_item",
        "_controlled_bridge_item",
        "_vault_item",
        "_vault_adapter_item",
        "_runtime_item",
        "_model_item",
        "_model_value_item",
        "_platform_registry_item",
        "_ebay_account_deletion_item",
        "_ebay_oauth_item",
        "_ebay_token_refresh_item",
        "_ebay_read_adapter_item",
        "_ebay_live_read_adapter_item",
        "_data_packet_cache_item",
        "_real_saas_loop_item",
        "_ebay_read_item",
        "_account_health_incident_item",
        "_ebay_policy_item",
        "_execution_item",
        "_tenant_audit_item",
    )
    unrelated_public_statuses = (
        "_public_model_status",
        "_public_ebay_status",
        "_public_platform_registry_status",
        "_public_provider_job_status",
        "_public_controlled_bridge_status",
        "_public_backup_status",
        "_public_model_value_status",
        "_ai_ceo_platform_model_status",
        "_public_search_status",
        "_public_media_generation_status",
        "_public_operational_health_status",
    )
    settings = SimpleNamespace(
        environment="staging",
        is_production_like=True,
        effective_real_platform_writes_enabled=False,
        effective_ebay_draft_save_enabled=False,
        requested_real_platform_writes=False,
    )
    with ExitStack() as stack:
        stack.enter_context(patch.object(readiness_module, "build_billing_plan", return_value=plan))
        stack.enter_context(patch.object(readiness_module, "build_operational_health", return_value={}))
        stack.enter_context(patch.object(readiness_module, "EbayProviderStatus", return_value=EbayStatusStub()))
        stack.enter_context(patch.object(readiness_module, "model_client_status_from_env", return_value={}))
        stack.enter_context(patch.object(readiness_module, "build_platform_default_model_status", return_value={}))
        stack.enter_context(patch.object(readiness_module, "_operational_health_items", return_value=[]))
        for name in unrelated_item_builders:
            stack.enter_context(patch.object(readiness_module, name, side_effect=unrelated_ready))
        for name in unrelated_public_statuses:
            stack.enter_context(patch.object(readiness_module, name, return_value={}))
        return readiness_module.build_product_readiness(settings, RepositoryStub())


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

    private_beta_launch = copy.deepcopy(ready)
    private_beta_launch["provider_checkout_ready"] = False
    private_beta_launch["mainland_payment_ready_for_owner_approval"] = False
    private_beta_readiness = isolated_product_readiness(
        {
            "billing_ready_for_private_beta": True,
            "billing_ready_for_paid_launch": False,
            "mainland_payment_launch": private_beta_launch,
            "quota_contract": {"enabled": True},
            "plan_catalog": [],
        }
    )
    billing_item = next(
        item for item in private_beta_readiness.get("items", []) if item.get("key") == "billing_quota"
    )
    if billing_item.get("severity") != "warning":
        return fail(f"paid-launch-only payment gap should not block free invited beta: {billing_item}")
    if private_beta_readiness.get("beta_ready") is not True:
        return fail(f"valid free invited beta should be ready when unrelated gates are ready: {private_beta_readiness}")
    if (
        private_beta_readiness.get("production_ready") is not False
        or private_beta_readiness.get("can_accept_real_customers") is not False
    ):
        return fail("private beta readiness must not imply paid production or real-customer readiness")
    private_beta_billing = private_beta_readiness.get("provider_status", {}).get("billing", {})
    for safety_key in (
        "billing_ready_for_paid_launch",
        "public_charging_allowed",
        "charge_now_allowed",
        "triggers_real_charge",
        "triggers_real_refund",
        "real_platform_writes_enabled",
        "frontend_can_grant_quota",
    ):
        if private_beta_billing.get(safety_key) is not False:
            return fail(f"private beta readiness opened forbidden billing capability {safety_key}")

    paid_launch_only_candidates: list[tuple[str, dict[str, Any]]] = []
    production_pending = copy.deepcopy(ready)
    production_pending["production_environment"] = False
    production_pending["mainland_payment_ready_for_owner_approval"] = False
    paid_launch_only_candidates.append(("production_environment", production_pending))
    refund_pending = copy.deepcopy(ready)
    refund_pending["refund_now_allowed"] = False
    refund_pending["mainland_payment_ready_for_owner_approval"] = False
    paid_launch_only_candidates.append(("refund", refund_pending))
    acceptance_pending = copy.deepcopy(ready)
    acceptance_pending["acceptance_evidence"]["controlled_acceptance_proven"] = False
    acceptance_pending["acceptance_evidence"]["verified_paid_order_count"] = 0
    acceptance_pending["controlled_acceptance_proven"] = False
    acceptance_pending["mainland_payment_ready_for_owner_approval"] = False
    paid_launch_only_candidates.append(("controlled_acceptance", acceptance_pending))
    paid_launch_only_candidates.append(("public_cutover", copy.deepcopy(ready)))
    for label, launch in paid_launch_only_candidates:
        candidate = isolated_product_readiness(
            {
                "billing_ready_for_private_beta": True,
                "billing_ready_for_paid_launch": False,
                "mainland_payment_launch": launch,
                "quota_contract": {"enabled": True},
                "plan_catalog": [],
            }
        )
        candidate_billing_item = next(
            item for item in candidate.get("items", []) if item.get("key") == "billing_quota"
        )
        if candidate_billing_item.get("severity") != "warning" or candidate.get("beta_ready") is not True:
            return fail(f"valid private beta should tolerate paid-launch-only {label} gap: {candidate_billing_item}")
        if candidate.get("production_ready") is not False or candidate.get("can_accept_real_customers") is not False:
            return fail(f"paid-launch-only {label} gap must keep production and real customers closed")

    malformed_launch = copy.deepcopy(private_beta_launch)
    malformed_launch["public_charging_allowed"] = True
    malformed_readiness = isolated_product_readiness(
        {
            "billing_ready_for_private_beta": True,
            "mainland_payment_launch": malformed_launch,
            "quota_contract": {"enabled": True},
            "plan_catalog": [],
        }
    )
    malformed_item = next(
        item for item in malformed_readiness.get("items", []) if item.get("key") == "billing_quota"
    )
    if malformed_item.get("severity") != "blocker" or malformed_readiness.get("beta_ready") is not False:
        return fail(f"contradictory payment safety state must fail closed: {malformed_item}")

    backend_safety_incomplete = copy.deepcopy(ready)
    backend_safety_incomplete["code_capabilities"]["authenticated_order_query_implemented"] = False
    backend_safety_incomplete["mainland_payment_ready_for_owner_approval"] = False
    configuration_incomplete = copy.deepcopy(ready)
    configuration_incomplete["configuration"] = {"required_count": 9, "completed_count": 8, "complete": False}
    configuration_incomplete["mainland_payment_ready_for_owner_approval"] = False
    for label, launch in (
        ("backend_safety", backend_safety_incomplete),
        ("provider_configuration", configuration_incomplete),
    ):
        candidate = isolated_product_readiness(
            {
                "billing_ready_for_private_beta": True,
                "mainland_payment_launch": launch,
                "quota_contract": {"enabled": True},
                "plan_catalog": [],
            }
        )
        candidate_item = next(item for item in candidate.get("items", []) if item.get("key") == "billing_quota")
        if candidate_item.get("severity") != "blocker" or candidate.get("beta_ready") is not False:
            return fail(f"incomplete {label} contract must keep private beta blocked: {candidate_item}")

    for private_beta_marker in (False, "true", 1, 1.0, None):
        candidate_plan = {
            "billing_ready_for_paid_launch": False,
            "mainland_payment_launch": private_beta_launch,
            "quota_contract": {"enabled": True},
            "plan_catalog": [],
        }
        if private_beta_marker is not None:
            candidate_plan["billing_ready_for_private_beta"] = private_beta_marker
        candidate = isolated_product_readiness(candidate_plan)
        candidate_item = next(item for item in candidate.get("items", []) if item.get("key") == "billing_quota")
        if candidate_item.get("severity") != "blocker" or candidate.get("beta_ready") is not False:
            return fail(f"non-boolean private beta marker must fail closed: {private_beta_marker!r}")

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
