"""Payment route strategy for Jiejing mainland-first billing.

This module is intentionally provider-neutral. It reports which collection
route should be pursued next without exposing API keys, payment secrets, or
creating a charge.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

from . import billing_domestic, billing_wechat_pay as wechat_pay
from .config import SaaSSettings

if TYPE_CHECKING:
    from .repository import SaaSRepository


MAINLAND_PAYMENT_CONTRACT_VERSION = "2026-06-29-mainland-payment-strategy"
FORMAL_PAYMENT_ARCHITECTURE_VERSION = "2026-06-29-formal-payment-collection-architecture"
MERCHANT_APPLICATION_PACKET_VERSION = "2026-07-01-merchant-payment-application-packet"
MAINLAND_PAYMENT_LAUNCH_CONTRACT_VERSION = "2026-07-27-mainland-payment-launch-v1"
MAINLAND_WECHAT_CONFIGURATION_KEYS = (
    "appid",
    "mchid",
    "merchant_serial",
    "merchant_private_key",
    "api_v3_key",
    "response_verification_key",
    "response_verification_key_id",
    "notify_url",
    "refund_notify_url",
)
MAINLAND_PAYMENT_REQUIRED_CAPABILITY_KEYS = (
    "signed_payment_callback_implemented",
    "signed_refund_callback_implemented",
    "real_order_creation_implemented",
    "authenticated_order_query_implemented",
    "quota_entitlement_persistence_implemented",
    "high_risk_confirmation_boundary_implemented",
)


def build_mainland_payment_strategy(settings: SaaSSettings) -> dict[str, Any]:
    """Return a sanitized payment strategy for the current launch stage."""

    target_region = _env("JIEJING_PRIMARY_CUSTOMER_REGION", "mainland_china")
    domestic_provider = _canonical_provider(_env("JIEJING_DOMESTIC_PAYMENT_PROVIDER", "not_selected"))
    manual_qr_enabled = _env_bool("JIEJING_MANUAL_QR_COLLECTION_ENABLED")
    domestic_adapter_enabled = _env_bool("JIEJING_DOMESTIC_PAYMENT_ADAPTER_ENABLED")
    domestic_webhook_configured = _env_bool("JIEJING_DOMESTIC_PAYMENT_WEBHOOK_CONFIGURED")
    domestic_live_cutover_approved = _env_bool("JIEJING_DOMESTIC_PAYMENT_LIVE_CUTOVER_APPROVED")
    merchant_entity_ready = _env_bool("JIEJING_PAYMENT_MERCHANT_ENTITY_READY")
    mainland_icp_ready = _env_bool("JIEJING_MAINLAND_PAYMENT_ICP_READY")
    domestic_lanes = _domestic_lanes(domestic_provider)
    selected_lane = next((lane for lane in domestic_lanes if lane["selected"]), None)
    mainland_first = target_region in {"mainland_china", "china_mainland", "cn"}
    ready_lane = next((lane for lane in domestic_lanes if lane["status"] == "ready"), None)
    domestic_provider_ready = ready_lane is not None
    subject_alignment_ready = mainland_icp_ready if mainland_first else True
    paid_launch_ready = (
        merchant_entity_ready
        and subject_alignment_ready
        and domestic_provider_ready
        and domestic_adapter_enabled
        and domestic_webhook_configured
        and domestic_live_cutover_approved
    )

    return {
        "contract_version": MAINLAND_PAYMENT_CONTRACT_VERSION,
        "target_customer_region": target_region,
        "recommended_primary_route": "domestic_wallets_or_aggregate_acquirer" if mainland_first else "stripe_or_global_checkout",
        "recommended_provider_order": [
            "wechat_pay_alipay_unionpay_via_licensed_acquirer",
            "lianlian_or_airwallex_as_aggregate_acquirer_if_merchant_kyc_passes",
            "stripe_or_paypal_for_international_bank_payments_and_non_mainland_customers",
            "manual_static_qr_only_for_private_beta_reconciliation",
        ],
        "why_not_static_qr_for_paid_saas": [
            "manual_qr_cannot_reliably_map_payment_to_plan_and_company",
            "manual_qr_has_no_signed_webhook_for_subscription_lifecycle",
            "manual_qr_cannot_auto_stop_quota_after_payment_failure_or_cancel",
            "manual_qr_makes_refund_dispute_invoice_and_audit_reconciliation_manual",
        ],
        "domestic_payment_lanes": domestic_lanes,
        "selected_domestic_provider": domestic_provider,
        "selected_domestic_provider_ready_for_rehearsal": domestic_provider_ready,
        "selected_domestic_provider_status": (selected_lane or {}).get("status") or "not_selected",
        "domestic_adapter_enabled": domestic_adapter_enabled,
        "domestic_signed_webhook_configured": domestic_webhook_configured,
        "domestic_live_cutover_approved": domestic_live_cutover_approved,
        "cross_border_lanes": _cross_border_lanes(),
        "settlement_lanes": _settlement_lanes(),
        "manual_qr_collection": {
            "enabled": manual_qr_enabled,
            "private_beta_only": True,
            "paid_launch_ready": False,
            "requires_manual_reconciliation": True,
            "auto_entitlement_update": False,
            "requires_owner_confirmation_to_activate_quota": True,
            "recommended_scope": "small_private_beta_only_before_merchant_provider_approval",
            "triggers_real_charge": False,
            "frontend_gets_payment_secret": False,
            "secret_exposed": False,
        },
        "formal_collection_architecture": _formal_collection_architecture(
            merchant_entity_ready=merchant_entity_ready,
            mainland_icp_ready=mainland_icp_ready,
            domestic_provider_ready=domestic_provider_ready,
            domestic_adapter_enabled=domestic_adapter_enabled,
            domestic_webhook_configured=domestic_webhook_configured,
            domestic_live_cutover_approved=domestic_live_cutover_approved,
            manual_qr_enabled=manual_qr_enabled,
        ),
        "merchant_entity_guidance": {
            "mainland_individual_without_business_license": "not_ready_for_automated_saas_collection",
            "recommended_next_step": "prepare_compliant_merchant_entity_and_payment_provider_review_packet",
            "reason": "regulated payment channels normally require merchant onboarding, settlement identity, product risk review, and webhook/order-query credentials",
            "current_hk_hosting_note": "hong_kong_or_overseas_hosting_is_fine_for_private_beta_but_mainland_web_payment_review_may_require_icp_and_subject_consistency",
        },
        "merchant_entity_readiness": _merchant_entity_readiness(
            merchant_entity_ready=merchant_entity_ready,
            mainland_icp_ready=mainland_icp_ready,
            domestic_provider_ready=domestic_provider_ready,
            domestic_webhook_configured=domestic_webhook_configured,
            manual_qr_enabled=manual_qr_enabled,
        ),
        "merchant_application_packet": _merchant_application_packet(
            settings=settings,
            merchant_entity_ready=merchant_entity_ready,
            mainland_icp_ready=mainland_icp_ready,
            domestic_provider_ready=domestic_provider_ready,
            domestic_webhook_configured=domestic_webhook_configured,
        ),
        "domain_and_icp_plan": _domain_and_icp_plan(
            merchant_entity_ready=merchant_entity_ready,
            mainland_icp_ready=mainland_icp_ready,
        ),
        "paid_launch_ready": paid_launch_ready,
        "paid_launch_blockers": []
        if paid_launch_ready
        else _payment_strategy_blockers(
            domestic_provider,
            manual_qr_enabled,
            domestic_provider_ready=domestic_provider_ready,
            domestic_adapter_enabled=domestic_adapter_enabled,
            domestic_webhook_configured=domestic_webhook_configured,
            domestic_live_cutover_approved=domestic_live_cutover_approved,
            merchant_entity_ready=merchant_entity_ready,
            mainland_icp_ready=mainland_icp_ready,
        ),
        "charge_now_allowed": False,
        "triggers_real_charge": False,
        "frontend_gets_payment_secret": False,
        "secret_exposed": False,
    }


def build_mainland_payment_launch_status(
    settings: SaaSSettings,
    repository: SaaSRepository,
) -> dict[str, Any]:
    """Return the canonical, sanitized mainland payment launch state.

    Building this status is deliberately read-only: it checks configuration
    presence and aggregate acceptance evidence, but never creates, queries, or
    refunds a provider order.
    """

    try:
        strategy = build_mainland_payment_strategy(settings)
        wechat = wechat_pay.build_wechat_pay_native_contract()
        acceptance = repository.domestic_payment_acceptance_evidence()
        if not isinstance(strategy, dict) or not isinstance(wechat, dict) or not isinstance(acceptance, dict):
            raise TypeError("payment launch dependency returned an invalid contract")
        return _build_mainland_payment_launch_status(
            strategy=strategy,
            wechat=wechat,
            acceptance=acceptance,
        )
    except Exception:
        return _unavailable_mainland_payment_launch_status()


def validate_mainland_payment_launch_for_public(value: Any) -> dict[str, Any]:
    """Validate and reduce the canonical launch contract for response boundaries.

    Both the merchant billing response and the unauthenticated readiness response
    consume this exact result.  Keeping the fail-closed decision here prevents
    either boundary from accepting a contradictory count, marker, or safety flag.
    """

    mainland = value if isinstance(value, dict) else {}
    unavailable = {
        "mainland_payment_ready_for_owner_approval": False,
        "provider_configured": False,
        "payment_path_status": "payment_status_unavailable",
        "merchant_status": "unavailable",
        "domestic_payment_status": "unavailable",
        "configured_component_count": 0,
        "required_component_count": 0,
        "controlled_acceptance_proven": False,
        "verified_paid_order_count": 0,
        "next_paid_launch_blocker": "merchant_payment_status_unavailable",
    }
    safety_fields = (
        "public_charging_allowed",
        "charge_now_allowed",
        "triggers_real_charge",
        "triggers_real_refund",
        "calls_external_payment_api",
        "calls_stripe_api",
        "real_platform_writes_enabled",
        "frontend_gets_payment_secret",
        "secret_exposed",
    )
    identity_valid = all(
        (
            mainland.get("contract_version") == MAINLAND_PAYMENT_LAUNCH_CONTRACT_VERSION,
            mainland.get("market") == "mainland_china",
            mainland.get("primary_provider") == "wechat_pay_native",
            mainland.get("checkout_mode") == "native_qr",
            mainland.get("billing_mode") == "one_time_30_day_plan",
            all(mainland.get(key) is False for key in safety_fields),
        )
    )
    configuration = mainland.get("configuration") if isinstance(mainland.get("configuration"), dict) else {}
    required_count = configuration.get("required_count")
    configured_count = configuration.get("completed_count")
    configuration_shape_valid = all(
        (
            type(required_count) is int,
            required_count == len(MAINLAND_WECHAT_CONFIGURATION_KEYS),
            type(configured_count) is int,
            type(configured_count) is int
            and type(required_count) is int
            and 0 <= configured_count <= required_count,
            type(configuration.get("complete")) is bool,
            type(configured_count) is int
            and configuration.get("complete") is (configured_count == len(MAINLAND_WECHAT_CONFIGURATION_KEYS)),
        )
    )
    configuration_complete = configuration_shape_valid and configured_count == required_count

    capabilities = mainland.get("code_capabilities") if isinstance(mainland.get("code_capabilities"), dict) else {}
    capability_shape_valid = all(type(capabilities.get(key)) is bool for key in MAINLAND_PAYMENT_REQUIRED_CAPABILITY_KEYS)
    capability_ready = capability_shape_valid and all(
        capabilities.get(key) is True for key in MAINLAND_PAYMENT_REQUIRED_CAPABILITY_KEYS
    )

    acceptance = mainland.get("acceptance_evidence") if isinstance(mainland.get("acceptance_evidence"), dict) else {}
    verified_count = acceptance.get("verified_paid_order_count")
    acceptance_marker = acceptance.get("controlled_acceptance_proven")
    verified_count_valid = type(verified_count) is int and verified_count >= 0
    acceptance_shape_valid = all(
        (
            acceptance.get("contract_version") == "2026-07-27-domestic-payment-acceptance-evidence-v2",
            acceptance.get("provider") == "wechat_pay_native",
            acceptance.get("acceptance_kind") == "owner_approved_one_cny_live_acceptance",
            verified_count_valid,
            type(acceptance_marker) is bool,
            verified_count_valid and acceptance_marker is (verified_count > 0),
            all(
                acceptance.get(key) is False
                for key in (
                    "public_charging_allowed",
                    "charge_now_allowed",
                    "triggers_real_charge",
                    "calls_external_payment_api",
                    "secret_exposed",
                )
            ),
        )
    )
    outer_acceptance_marker = mainland.get("controlled_acceptance_proven")
    provider_checkout_marker = mainland.get("provider_checkout_ready")
    production_environment_marker = mainland.get("production_environment")
    refund_ready_marker = mainland.get("refund_now_allowed")
    canonical_owner_marker = mainland.get("mainland_payment_ready_for_owner_approval")
    dynamic_shape_valid = all(
        (
            type(outer_acceptance_marker) is bool,
            outer_acceptance_marker is acceptance_marker,
            type(provider_checkout_marker) is bool,
            type(production_environment_marker) is bool,
            type(refund_ready_marker) is bool,
            type(canonical_owner_marker) is bool,
        )
    )
    controlled_acceptance_proven = bool(
        acceptance_shape_valid
        and outer_acceptance_marker is True
        and acceptance_marker is True
        and verified_count > 0
    )
    computed_owner_ready = all(
        (
            configuration_complete,
            capability_ready,
            provider_checkout_marker is True,
            production_environment_marker is True,
            refund_ready_marker is True,
            controlled_acceptance_proven,
        )
    )
    owner_shape_valid = type(canonical_owner_marker) is bool
    canonical_valid = all(
        (
            identity_valid,
            configuration_shape_valid,
            capability_shape_valid,
            acceptance_shape_valid,
            dynamic_shape_valid,
            owner_shape_valid,
        )
    )
    if not canonical_valid:
        return unavailable

    provider_configured = configuration_complete and (
        provider_checkout_marker is True or controlled_acceptance_proven
    )
    if not configuration_complete:
        blocker = "merchant_payment_provider_configuration_incomplete"
        payment_status = "configuration_in_progress"
        domestic_status = "configuration_in_progress"
        merchant_status = "configuration_in_progress"
    elif not capability_ready:
        blocker = "merchant_payment_backend_safety_controls_incomplete"
        payment_status = "backend_safety_controls_in_progress"
        domestic_status = "backend_safety_controls_in_progress"
        merchant_status = "backend_safety_controls_in_progress"
    elif provider_checkout_marker is not True and controlled_acceptance_proven:
        blocker = "merchant_payment_provider_runtime_activation_pending"
        payment_status = "provider_activation_pending"
        domestic_status = "provider_activation_pending"
        merchant_status = "provider_activation_pending"
    elif provider_checkout_marker is not True:
        blocker = "merchant_payment_provider_connection_not_ready"
        payment_status = "provider_connection_in_progress"
        domestic_status = "provider_connection_in_progress"
        merchant_status = "provider_connection_in_progress"
    elif production_environment_marker is not True:
        blocker = "merchant_payment_production_environment_required"
        payment_status = "production_environment_pending"
        domestic_status = "production_environment_pending"
        merchant_status = "production_environment_pending"
    elif refund_ready_marker is not True:
        blocker = "merchant_payment_refund_not_ready"
        payment_status = "refund_controls_pending"
        domestic_status = "refund_controls_pending"
        merchant_status = "refund_controls_pending"
    elif not controlled_acceptance_proven:
        blocker = "merchant_payment_controlled_acceptance_not_proven"
        payment_status = "controlled_acceptance_pending"
        domestic_status = "controlled_acceptance_pending"
        merchant_status = "controlled_acceptance_pending"
    elif canonical_owner_marker is not True:
        return unavailable
    else:
        blocker = "merchant_payment_public_cutover_not_approved"
        payment_status = "controlled_acceptance_proven_public_charging_closed"
        domestic_status = "controlled_acceptance_proven"
        merchant_status = "awaiting_public_cutover"
    return {
        "mainland_payment_ready_for_owner_approval": computed_owner_ready and canonical_owner_marker is True,
        "provider_configured": provider_configured,
        "payment_path_status": payment_status,
        "merchant_status": merchant_status,
        "domestic_payment_status": domestic_status,
        "configured_component_count": configured_count,
        "required_component_count": required_count,
        "controlled_acceptance_proven": controlled_acceptance_proven,
        "verified_paid_order_count": verified_count,
        "next_paid_launch_blocker": blocker,
    }


def _build_mainland_payment_launch_status(
    *,
    strategy: dict[str, Any],
    wechat: dict[str, Any],
    acceptance: dict[str, Any],
) -> dict[str, Any]:
    mainland_payment_strategy_contract_valid = all(
        (
            strategy.get("contract_version") == MAINLAND_PAYMENT_CONTRACT_VERSION,
            strategy.get("charge_now_allowed") is False,
            strategy.get("triggers_real_charge") is False,
            strategy.get("frontend_gets_payment_secret") is False,
            strategy.get("secret_exposed") is False,
        )
    )
    configured_source = wechat.get("configured") if isinstance(wechat.get("configured"), dict) else {}
    configured = {key: configured_source.get(key) is True for key in MAINLAND_WECHAT_CONFIGURATION_KEYS}
    completed_count = sum(1 for ready in configured.values() if ready)
    configuration_complete = completed_count == len(MAINLAND_WECHAT_CONFIGURATION_KEYS)
    wechat_native_contract_valid = all(
        (
            wechat.get("contract_version") == "2026-07-14-wechat-pay-native-v3",
            wechat.get("provider") == "wechat_pay_native",
            wechat.get("checkout_mode") == "native_qr",
            wechat.get("billing_mode") == "one_time_30_day_plan",
            wechat.get("merchant_credentials_backend_only") is True,
            wechat.get("frontend_gets_payment_secret") is False,
            wechat.get("secret_exposed") is False,
        )
    )
    provider_checkout_ready = (
        mainland_payment_strategy_contract_valid
        and wechat_native_contract_valid
        and configuration_complete
        and wechat.get("provider_connection_ready") is True
    )
    verified_paid_order_count = _safe_verified_payment_count(acceptance.get("verified_paid_order_count"))
    acceptance_source_flag = acceptance.get("controlled_acceptance_proven") is True
    acceptance_count_proves_payment = verified_paid_order_count > 0
    acceptance_evidence_inconsistent = acceptance_source_flag != acceptance_count_proves_payment
    acceptance_identity_contract_valid = all(
        (
            acceptance.get("contract_version") == "2026-07-27-domestic-payment-acceptance-evidence-v2",
            acceptance.get("provider") == "wechat_pay_native",
            acceptance.get("acceptance_kind") == "owner_approved_one_cny_live_acceptance",
        )
    )
    acceptance_safety_contract_valid = all(
        acceptance.get(key) is False
        for key in (
            "public_charging_allowed",
            "charge_now_allowed",
            "triggers_real_charge",
            "calls_external_payment_api",
            "secret_exposed",
        )
    )
    controlled_acceptance_proven = (
        acceptance_source_flag
        and acceptance_count_proves_payment
        and acceptance_identity_contract_valid
        and acceptance_safety_contract_valid
    )
    production_environment = wechat.get("production_environment") is True
    owner_approval_recorded = wechat.get("owner_approval_recorded") is True

    code_capabilities = {
        "signed_payment_callback_implemented": (
            wechat.get("signed_callback_implemented") is True
            and callable(getattr(wechat_pay, "process_wechat_pay_notification_from_env", None))
        ),
        "signed_refund_callback_implemented": (
            wechat.get("signed_refund_callback_implemented") is True
            and callable(getattr(wechat_pay, "process_wechat_pay_refund_notification_from_env", None))
        ),
        "real_order_creation_implemented": (
            wechat.get("real_order_creation_implemented") is True
            and callable(getattr(wechat_pay, "create_wechat_pay_native_order_from_env", None))
        ),
        "authenticated_order_query_implemented": (
            callable(getattr(wechat_pay, "query_wechat_pay_order_from_env", None))
            and callable(getattr(wechat_pay, "reconcile_wechat_pay_order_query", None))
        ),
        "quota_entitlement_persistence_implemented": callable(
            getattr(wechat_pay, "recover_paid_wechat_pay_entitlement", None)
        ),
        "refund_execution_confirmation_required": wechat.get("refund_execution_confirmation_required") is True,
        "high_risk_confirmation_boundary_implemented": (
            wechat.get("refund_execution_confirmation_required") is True
            and callable(getattr(billing_domestic, "request_domestic_billing_refund_review", None))
            and callable(getattr(billing_domestic, "execute_approved_domestic_billing_refund", None))
        ),
    }
    blockers: list[str] = []
    if not mainland_payment_strategy_contract_valid:
        blockers.append("mainland_payment_strategy_contract_invalid")
    if not wechat_native_contract_valid:
        blockers.append("wechat_pay_native_contract_invalid")
    if not configured_source:
        blockers.append("wechat_pay_configuration_contract_missing")
    blockers.extend(f"wechat_pay_{key}_not_configured" for key in MAINLAND_WECHAT_CONFIGURATION_KEYS if not configured[key])
    blockers.extend(
        f"wechat_pay_{key}_missing"
        for key in (*MAINLAND_PAYMENT_REQUIRED_CAPABILITY_KEYS, "refund_execution_confirmation_required")
        if code_capabilities.get(key) is not True
    )
    if configuration_complete and not provider_checkout_ready:
        blockers.append("wechat_pay_live_api_disabled")
    if not acceptance_identity_contract_valid:
        blockers.append("controlled_wechat_pay_acceptance_identity_contract_invalid")
    if not acceptance_safety_contract_valid:
        blockers.append("controlled_wechat_pay_acceptance_safety_contract_invalid")
    if acceptance_evidence_inconsistent:
        blockers.append("controlled_wechat_pay_acceptance_evidence_inconsistent")
    elif not (acceptance_source_flag and acceptance_count_proves_payment):
        blockers.append("controlled_wechat_pay_acceptance_not_proven")
    if not production_environment:
        blockers.append("public_checkout_requires_production_environment")
    if wechat.get("refund_now_allowed") is not True:
        blockers.append("wechat_pay_refund_not_approved_or_ready")
    if not owner_approval_recorded:
        blockers.append("paid_launch_owner_approval_packet_missing")
    blockers.append("public_charging_requires_higher_commercial_release_gate")
    blockers = list(dict.fromkeys(blockers))

    stripe_lane = next(
        (
            lane
            for lane in strategy.get("cross_border_lanes", [])
            if isinstance(lane, dict) and lane.get("key") == "stripe"
        ),
        {},
    )
    acceptance_evidence = {
        "contract_version": "2026-07-27-domestic-payment-acceptance-evidence-v2",
        "provider": "wechat_pay_native",
        "acceptance_kind": "owner_approved_one_cny_live_acceptance",
        "controlled_acceptance_proven": controlled_acceptance_proven,
        "verified_paid_order_count": verified_paid_order_count,
        "public_charging_allowed": False,
        "charge_now_allowed": False,
        "triggers_real_charge": False,
        "calls_external_payment_api": False,
        "secret_exposed": False,
    }
    ready_for_owner_approval = all(
        (
            provider_checkout_ready,
            controlled_acceptance_proven,
            production_environment,
            wechat.get("refund_now_allowed") is True,
            all(code_capabilities.get(key) is True for key in MAINLAND_PAYMENT_REQUIRED_CAPABILITY_KEYS),
        )
    )

    return {
        "contract_version": MAINLAND_PAYMENT_LAUNCH_CONTRACT_VERSION,
        "status": "blocked" if blockers else "ready",
        "market": "mainland_china",
        "primary_provider": "wechat_pay_native",
        "checkout_mode": "native_qr",
        "billing_mode": "one_time_30_day_plan",
        "future_international_payment": {
            "provider": "stripe",
            "role": "future_international_payment_only",
            "selected": stripe_lane.get("selected") is True,
            "blocks_mainland_launch": False,
            "calls_stripe_api": False,
            "triggers_real_charge": False,
            "secret_exposed": False,
        },
        "code_capabilities": code_capabilities,
        "configuration": {
            "required_count": len(MAINLAND_WECHAT_CONFIGURATION_KEYS),
            "completed_count": completed_count,
            "complete": configuration_complete,
            "component_presence": configured,
            "secret_values_included": False,
        },
        "acceptance_evidence": acceptance_evidence,
        "controlled_acceptance_proven": controlled_acceptance_proven,
        "provider_checkout_ready": provider_checkout_ready,
        "production_environment": production_environment,
        "refund_now_allowed": wechat.get("refund_now_allowed") is True,
        "owner_approval_recorded": owner_approval_recorded,
        "mainland_payment_ready_for_owner_approval": ready_for_owner_approval,
        "paid_launch_ready": False,
        "paid_launch_blockers": blockers,
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


def _safe_verified_payment_count(value: Any) -> int:
    if type(value) is not int or value < 0:
        return 0
    return min(value, 100)


def _unavailable_mainland_payment_launch_status() -> dict[str, Any]:
    return {
        "contract_version": MAINLAND_PAYMENT_LAUNCH_CONTRACT_VERSION,
        "status": "blocked",
        "market": "mainland_china",
        "primary_provider": "wechat_pay_native",
        "checkout_mode": "native_qr",
        "billing_mode": "one_time_30_day_plan",
        "future_international_payment": {
            "provider": "stripe",
            "role": "future_international_payment_only",
            "selected": False,
            "blocks_mainland_launch": False,
            "calls_stripe_api": False,
            "triggers_real_charge": False,
            "secret_exposed": False,
        },
        "code_capabilities": {
            "signed_payment_callback_implemented": False,
            "signed_refund_callback_implemented": False,
            "real_order_creation_implemented": False,
            "authenticated_order_query_implemented": False,
            "quota_entitlement_persistence_implemented": False,
            "refund_execution_confirmation_required": False,
            "high_risk_confirmation_boundary_implemented": False,
        },
        "configuration": {
            "required_count": len(MAINLAND_WECHAT_CONFIGURATION_KEYS),
            "completed_count": 0,
            "complete": False,
            "component_presence": {key: False for key in MAINLAND_WECHAT_CONFIGURATION_KEYS},
            "secret_values_included": False,
        },
        "acceptance_evidence": {
            "contract_version": "2026-07-27-domestic-payment-acceptance-evidence-v2",
            "provider": "wechat_pay_native",
            "acceptance_kind": "owner_approved_one_cny_live_acceptance",
            "controlled_acceptance_proven": False,
            "verified_paid_order_count": 0,
            "public_charging_allowed": False,
            "charge_now_allowed": False,
            "triggers_real_charge": False,
            "calls_external_payment_api": False,
            "secret_exposed": False,
        },
        "controlled_acceptance_proven": False,
        "provider_checkout_ready": False,
        "production_environment": False,
        "refund_now_allowed": False,
        "owner_approval_recorded": False,
        "mainland_payment_ready_for_owner_approval": False,
        "paid_launch_ready": False,
        "paid_launch_blockers": ["mainland_payment_status_unavailable"],
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


def _merchant_application_packet(
    *,
    settings: SaaSSettings,
    merchant_entity_ready: bool,
    mainland_icp_ready: bool,
    domestic_provider_ready: bool,
    domestic_webhook_configured: bool,
) -> dict[str, Any]:
    """Return a public-safe checklist for formal merchant payment review."""

    public_app_url = _env("JIEJING_PUBLIC_APP_URL", "https://app.jiejing.shop").rstrip("/")
    public_support_contact = _env("JIEJING_PUBLIC_SUPPORT_CONTACT", "")
    service_docs_ready = _env_bool("JIEJING_PAYMENT_REVIEW_SERVICE_DOCS_READY", True)
    pricing_terms_ready = _env_bool("JIEJING_PAYMENT_REVIEW_PRICING_TERMS_READY", True)
    support_contact_ready = _env_bool("JIEJING_PAYMENT_REVIEW_SUPPORT_CONTACT_READY", bool(public_support_contact))
    refund_policy_ready = _env_bool("JIEJING_PAYMENT_REVIEW_REFUND_POLICY_READY", True)
    callback_url_ready = _env_bool("JIEJING_PAYMENT_REVIEW_CALLBACK_URL_READY", bool(public_app_url))
    checklist = [
        {
            "key": "merchant_subject",
            "label": "合规商户主体",
            "status": "ready" if merchant_entity_ready else "blocked",
            "review_use": "用于支付通道审核商户实名、结算主体和服务场景",
        },
        {
            "key": "operator_and_settlement",
            "label": "经营者实名和结算账户",
            "status": "ready" if merchant_entity_ready else "blocked",
            "review_use": "用于 KYC、打款、退款、争议和对账，不在捷境前端保存证件或银行卡明文",
        },
        {
            "key": "service_privacy_refund_pages",
            "label": "服务协议、隐私和退款说明",
            "status": "ready" if service_docs_ready and refund_policy_ready else "in_progress",
            "review_use": "支付机构审核会看产品卖什么、怎么退款、用户数据如何处理",
        },
        {
            "key": "pricing_and_subscription_terms",
            "label": "价格、订阅和额度规则",
            "status": "ready" if pricing_terms_ready else "in_progress",
            "review_use": "说明基础订阅、大模型用量、素材生成费用和欠费停用边界",
        },
        {
            "key": "support_contact",
            "label": "客服和投诉入口",
            "status": "ready" if support_contact_ready else "in_progress",
            "review_use": "支付审核和真实用户都需要找到售后、退款和争议处理入口",
        },
        {
            "key": "reviewed_domain_and_callbacks",
            "label": "正式域名和回调地址",
            "status": "ready" if callback_url_ready and mainland_icp_ready else "designed",
            "review_use": "商户平台需要填写支付成功、取消、异步通知和查单相关地址",
        },
        {
            "key": "signed_callback_and_order_query",
            "label": "签名回调和主动查单",
            "status": "ready" if domestic_provider_ready and domestic_webhook_configured else "blocked",
            "review_use": "只有后端验证过的支付证据才能自动发放套餐和额度",
        },
    ]
    return {
        "contract_version": MERCHANT_APPLICATION_PACKET_VERSION,
        "current_stage": "merchant_entity_and_provider_review_preparation",
        "public_app_url": public_app_url,
        "recommended_packet_use": "use_after_compliant_merchant_entity_is_ready_before_formal_payment_provider_application",
        "review_urls": {
            "terms": f"{public_app_url}/terms.html",
            "privacy": f"{public_app_url}/privacy.html",
            "refund_policy": f"{public_app_url}/refund-policy.html",
            "support": f"{public_app_url}/support.html",
            "risk_disclosure": f"{public_app_url}/risk-disclosure.html",
            "pricing": public_app_url,
        },
        "provider_callback_urls": {
            "success_url": f"{public_app_url}/billing/success",
            "cancel_url": f"{public_app_url}/billing/cancel",
            "webhook_url": f"{public_app_url}/billing/webhook",
        },
        "customer_review_brief": _customer_review_brief(
            support_contact_ready=support_contact_ready,
            public_support_contact=public_support_contact,
            refund_policy_ready=refund_policy_ready,
            pricing_terms_ready=pricing_terms_ready,
            service_docs_ready=service_docs_ready,
        ),
        "checklist": checklist,
        "must_stay_backend_only": [
            "merchant_private_keys",
            "api_v3_keys",
            "webhook_secrets",
            "provider_cert_private_material",
            "operator_identity_files",
            "settlement_bank_account_details",
        ],
        "does_not_collect_identity_files_in_frontend": True,
        "requires_owner_supplied_real_docs": True,
        "can_submit_provider_application": merchant_entity_ready and service_docs_ready and pricing_terms_ready and refund_policy_ready,
        "can_auto_grant_paid_entitlement": domestic_provider_ready and domestic_webhook_configured,
        "settings_storage_db_path_configured": bool(settings.db_path),
        "charge_now_allowed": False,
        "triggers_real_charge": False,
        "frontend_gets_payment_secret": False,
        "secret_exposed": False,
    }


def _customer_review_brief(
    *,
    support_contact_ready: bool,
    public_support_contact: str,
    refund_policy_ready: bool,
    pricing_terms_ready: bool,
    service_docs_ready: bool,
) -> dict[str, Any]:
    """Summarize the customer-facing policy story needed for payment review."""

    missing = []
    if not support_contact_ready:
        missing.append("public_support_contact")
    if not refund_policy_ready:
        missing.append("refund_policy")
    if not pricing_terms_ready:
        missing.append("pricing_and_subscription_terms")
    if not service_docs_ready:
        missing.append("service_privacy_terms")
    return {
        "contract_version": "2026-07-01-payment-review-customer-brief",
        "service_name": "JIEJING AI CEO eBay SaaS",
        "service_scope": [
            "eBay-first AI CEO workbench",
            "listing_draft_and_market_report",
            "media_brief_and_customer_service_draft",
            "confirmation_center_for_high_risk_actions",
        ],
        "billing_terms": [
            "base_subscription_is_software_feature_fee",
            "ai_model_media_and_search_usage_can_be_separate",
            "ebay_fees_ads_shipping_refunds_are_settled_by_merchant_platform_accounts",
        ],
        "refund_and_support": {
            "support_contact_status": "ready" if support_contact_ready else "pending_public_support_contact",
            "support_contact_public": public_support_contact if support_contact_ready else "",
            "refund_policy_status": "ready" if refund_policy_ready else "in_progress",
            "dispute_path": "owner_review_with_order_subscription_and_audit_evidence",
        },
        "data_and_action_boundary": [
            "payment_identity_files_and_provider_secrets_do_not_enter_frontend",
            "real_publish_refund_ad_payment_policy_and_sensitive_customer_promises_require_confirmation",
            "verified_provider_callback_or_order_query_required_before_auto_entitlement",
        ],
        "missing_for_review": missing,
        "review_ready": not missing,
        "charge_now_allowed": False,
        "triggers_real_charge": False,
        "frontend_gets_payment_secret": False,
        "secret_exposed": False,
    }


def _domestic_lanes(selected_provider: str) -> list[dict[str, Any]]:
    wechat_contract = wechat_pay.build_wechat_pay_native_contract()
    wechat_configured = (
        wechat_contract.get("configured") if isinstance(wechat_contract.get("configured"), dict) else {}
    )
    return [
        _domestic_lane(
            key="wechat_pay_native",
            label="微信支付商户通道",
            selected_provider=selected_provider,
            aliases={"wechat_pay", "wechat_pay_native", "weixin_pay"},
            required_env=[
                "JIEJING_WECHAT_PAY_MCH_ID",
                "JIEJING_WECHAT_PAY_APP_ID",
                "JIEJING_WECHAT_PAY_MERCHANT_SERIAL_NO",
                "JIEJING_WECHAT_PAY_MERCHANT_PRIVATE_KEY_PEM_B64",
                "JIEJING_WECHAT_PAY_API_V3_KEY",
                "JIEJING_WECHAT_PAY_PUBLIC_KEY_ID",
                "JIEJING_WECHAT_PAY_PUBLIC_KEY_PEM_B64",
                "JIEJING_WECHAT_PAY_NOTIFY_URL",
                "JIEJING_WECHAT_PAY_REFUND_NOTIFY_URL",
            ],
            configured_override={
                "JIEJING_WECHAT_PAY_MCH_ID": wechat_configured.get("mchid") is True,
                "JIEJING_WECHAT_PAY_APP_ID": wechat_configured.get("appid") is True,
                "JIEJING_WECHAT_PAY_MERCHANT_SERIAL_NO": wechat_configured.get("merchant_serial") is True,
                "JIEJING_WECHAT_PAY_MERCHANT_PRIVATE_KEY_PEM_B64": wechat_configured.get("merchant_private_key") is True,
                "JIEJING_WECHAT_PAY_API_V3_KEY": wechat_configured.get("api_v3_key") is True,
                "JIEJING_WECHAT_PAY_PUBLIC_KEY_ID": wechat_configured.get("response_verification_key_id") is True,
                "JIEJING_WECHAT_PAY_PUBLIC_KEY_PEM_B64": wechat_configured.get("response_verification_key") is True,
                "JIEJING_WECHAT_PAY_NOTIFY_URL": wechat_configured.get("notify_url") is True,
                "JIEJING_WECHAT_PAY_REFUND_NOTIFY_URL": wechat_configured.get("refund_notify_url") is True,
            },
            fit="best_for_mainland_wechat_users_and_qr_checkout",
        ),
        _domestic_lane(
            key="alipay_web",
            label="支付宝商户通道",
            selected_provider=selected_provider,
            aliases={"alipay", "alipay_web", "alipay_f2f"},
            required_env=[
                "JIEJING_ALIPAY_APP_ID",
                "JIEJING_ALIPAY_PRIVATE_KEY_REF",
                "JIEJING_ALIPAY_PUBLIC_CERT_REF",
            ],
            fit="best_for_mainland_alipay_checkout_and_qr_checkout",
        ),
        _domestic_lane(
            key="unionpay_cloud_quickpass",
            label="银联商户通道",
            selected_provider=selected_provider,
            aliases={"unionpay", "cloud_quickpass", "yunshanfu"},
            required_env=[
                "JIEJING_UNIONPAY_MERCHANT_ID",
                "JIEJING_UNIONPAY_APP_ID",
                "JIEJING_UNIONPAY_CERT_REF",
            ],
            fit="best_for_unionpay_accounts_and_cloud_quickpass_users",
        ),
        _domestic_lane(
            key="lianlian_aggregate",
            label="连连支付商户通道",
            selected_provider=selected_provider,
            aliases={"lianlian", "lianlian_pay", "lianlian_aggregate"},
            required_env=[
                "JIEJING_LIANLIAN_MERCHANT_ID",
                "JIEJING_LIANLIAN_APP_ID",
                "JIEJING_LIANLIAN_PRIVATE_KEY_REF",
            ],
            fit="possible_cn_acquirer_path_if_merchant_kyc_and_product_approval_pass",
        ),
        _domestic_lane(
            key="airwallex_cn_aggregate",
            label="空中云汇商户通道",
            selected_provider=selected_provider,
            aliases={"airwallex", "airwallex_cn", "airwallex_cn_aggregate"},
            required_env=[
                "JIEJING_AIRWALLEX_CLIENT_ID",
                "JIEJING_AIRWALLEX_API_KEY_REF",
                "JIEJING_AIRWALLEX_WEBHOOK_SECRET_REF",
            ],
            fit="possible_cross_border_and_wallet_route_if_account_kyc_passes",
        ),
    ]


def _domestic_lane(
    *,
    key: str,
    label: str,
    selected_provider: str,
    aliases: set[str],
    required_env: list[str],
    configured_override: dict[str, bool] | None = None,
    fit: str,
) -> dict[str, Any]:
    configured = (
        {name: configured_override.get(name) is True for name in required_env}
        if configured_override is not None
        else {name: bool(os.environ.get(name, "").strip()) for name in required_env}
    )
    missing = [name for name, ready in configured.items() if not ready]
    selected = selected_provider in aliases
    return {
        "key": key,
        "label": label,
        "selected": selected,
        "status": "ready" if selected and not missing else "missing_credentials" if selected else "available_candidate",
        "fit": fit,
        "required_env_configured": configured,
        "missing_env": missing if selected else [],
        "requires_merchant_kyc": True,
        "requires_signed_callback_or_order_query": True,
        "can_drive_subscription_quota": selected and not missing,
        "triggers_real_charge": False,
        "frontend_gets_payment_secret": False,
        "secret_exposed": False,
    }


def _cross_border_lanes() -> list[dict[str, Any]]:
    stripe_selected = _env("JIEJING_BILLING_PROVIDER", "").strip().lower() == "stripe"
    return [
        {
            "key": "stripe",
            "fit": "best_for_international_bank_payments_overseas_customers_and_global_saas_billing",
            "mainland_first_note": "not_the_default_choice_when_all_customers_are_mainland_china",
            "selected": stripe_selected,
            "requires_supported_stripe_account_country": True,
            "requires_live_price_ids_and_signed_webhook": True,
            "triggers_real_charge": False,
            "frontend_gets_payment_secret": False,
            "secret_exposed": False,
        },
        {
            "key": "paypal",
            "fit": "useful_for_cross_border_paypal_buyers_not_mainland_domestic_qr_first",
            "selected": False,
            "requires_business_account_and_webhook": True,
            "triggers_real_charge": False,
            "frontend_gets_payment_secret": False,
            "secret_exposed": False,
        },
    ]


def _settlement_lanes() -> list[dict[str, Any]]:
    return [
        {
            "key": "worldfirst",
            "fit": "marketplace_and_cross_border_settlement_account_not_primary_saas_checkout",
            "use_as_checkout_provider": False,
        },
        {
            "key": "payoneer",
            "fit": "marketplace_or_b2b_receivables_and_settlement_not_mainland_wallet_checkout",
            "use_as_checkout_provider": False,
        },
    ]


def _merchant_entity_readiness(
    *,
    merchant_entity_ready: bool,
    mainland_icp_ready: bool,
    domestic_provider_ready: bool,
    domestic_webhook_configured: bool,
    manual_qr_enabled: bool,
) -> dict[str, Any]:
    """Return public-safe readiness for the user's entity/payment onboarding path."""

    checklist = [
        {
            "key": "business_license",
            "label": "商户主体资质",
            "status": "ready" if merchant_entity_ready else "in_progress",
            "why": "正式支付通道审核需要可结算、可核验的商户主体",
        },
        {
            "key": "operator_identity_and_bank",
            "label": "经营者实名与结算账户",
            "status": "ready" if merchant_entity_ready else "blocked",
            "why": "商户审核、打款、退款和争议处理要能对应同一经营主体",
        },
        {
            "key": "service_docs_and_contact",
            "label": "服务协议、隐私政策和客服入口",
            "status": "designed",
            "why": "支付审核需要看清服务内容、退款路径和售后联系方式",
        },
        {
            "key": "domain_subject_alignment",
            "label": "域名、备案要求和商户主体一致",
            "status": "ready" if mainland_icp_ready else "blocked",
            "why": "支付审核可能核对官网、回调域名和商户主体是否一致",
        },
        {
            "key": "signed_callback_and_order_query",
            "label": "签名回调和主动查单能力",
            "status": "ready" if domestic_webhook_configured and domestic_provider_ready else "blocked",
            "why": "捷境只能依据后端验证过的支付证据自动发放或停止额度",
        },
    ]
    return {
        "contract_version": "2026-06-30-merchant-entity-payment-readiness",
        "current_stage": "private_beta_manual_reconciliation" if manual_qr_enabled else "entity_and_provider_preparation",
        "recommended_entity_path": "individual_business_first_then_company_if_scale_requires",
        "merchant_entity_ready": merchant_entity_ready,
        "mainland_icp_or_subject_alignment_ready": mainland_icp_ready,
        "domestic_provider_ready_for_rehearsal": domestic_provider_ready,
        "signed_webhook_configured": domestic_webhook_configured,
        "personal_qr_scope": "private_beta_manual_reconciliation_only",
        "can_auto_grant_paid_entitlement": domestic_provider_ready and domestic_webhook_configured,
        "checklist": checklist,
        "next_external_steps": [
            "prepare_compliant_merchant_entity_materials",
            "apply_formal_payment_provider_merchant_account",
            "prepare_reviewed_domain_service_pages_and_callback_urls",
            "store_provider_credentials_only_in_backend_vault_or_env",
            "run_no_real_charge_rehearsal_before_owner_live_cutover",
        ],
        "triggers_real_charge": False,
        "frontend_gets_payment_secret": False,
        "secret_exposed": False,
    }


def _formal_collection_architecture(
    *,
    merchant_entity_ready: bool,
    mainland_icp_ready: bool,
    domestic_provider_ready: bool,
    domestic_adapter_enabled: bool,
    domestic_webhook_configured: bool,
    domestic_live_cutover_approved: bool,
    manual_qr_enabled: bool,
) -> dict[str, Any]:
    """Describe the formal payment spine without exposing provider secrets."""

    steps = [
        {
            "key": "merchant_entity",
            "label": "商户主体和产品审核",
            "status": "ready" if merchant_entity_ready else "blocked",
            "owner": "operator",
            "reason": "正式支付通道需要可核验的结算主体和产品审核",
        },
        {
            "key": "domain_icp_subject_alignment",
            "label": "域名、备案要求和商户主体一致",
            "status": "ready" if mainland_icp_ready else "blocked",
            "owner": "operator",
            "reason": "支付审核可能核对官网、回调域名和商户主体一致性",
        },
        {
            "key": "create_order",
            "label": "后端创建订阅订单",
            "status": "ready" if domestic_adapter_enabled else "blocked",
            "owner": "backend",
            "reason": "Jiejing must create an internal order before sending a user to payment",
        },
        {
            "key": "provider_checkout",
            "label": "支付通道订单页",
            "status": "ready" if domestic_provider_ready and domestic_adapter_enabled else "blocked",
            "owner": "backend",
            "reason": "公开订阅付款必须来自正式商户支付通道，不能靠人工核对",
        },
        {
            "key": "signed_webhook_and_order_query",
            "label": "签名回调和主动查单",
            "status": "ready" if domestic_webhook_configured else "blocked",
            "owner": "backend",
            "reason": "subscription and quota changes must be driven by verifiable provider evidence",
        },
        {
            "key": "subscription_quota_audit",
            "label": "订阅、额度、票据和审计更新",
            "status": "blocked" if manual_qr_enabled else "designed",
            "owner": "backend",
            "reason": "人工核对只能用于小范围内测，不能自动续费、停用额度或完成审计闭环",
        },
        {
            "key": "owner_live_cutover",
            "label": "负责人批准正式切换",
            "status": "ready" if domestic_live_cutover_approved else "blocked",
            "owner": "owner",
            "reason": "real-money collection must not be enabled by code deployment alone",
        },
    ]
    return {
        "contract_version": FORMAL_PAYMENT_ARCHITECTURE_VERSION,
        "current_stage": "private_beta_manual_collection" if manual_qr_enabled else "formal_provider_not_connected",
        "recommended_now": "use_invited_beta_manual_reconciliation_only_until_provider_cutover",
        "formal_target": "licensed_payment_provider_with_signed_callbacks_and_order_query",
        "steps": steps,
        "manual_qr_boundary": {
            "can_collect_private_beta_money": True,
            "can_auto_activate_subscription": False,
            "can_prove_payment_by_signed_provider_webhook": False,
            "can_be_paid_public_launch_provider": False,
            "requires_owner_manual_reconciliation": True,
        },
        "charge_now_allowed": False,
        "triggers_real_charge": False,
        "frontend_gets_payment_secret": False,
        "secret_exposed": False,
    }


def _domain_and_icp_plan(*, merchant_entity_ready: bool, mainland_icp_ready: bool) -> dict[str, Any]:
    return {
        "contract_version": "2026-06-29-mainland-domain-icp-payment-plan",
        "current_domain": _env("JIEJING_PUBLIC_APP_URL", "https://app.jiejing.shop"),
        "current_hosting_region": _env("JIEJING_PUBLIC_HOSTING_REGION", "hong_kong_or_overseas"),
        "current_hk_route_icp_required": False,
        "current_hk_route_note": "Hong Kong or overseas hosting does not create a mainland ICP filing by itself.",
        "future_mainland_company_conflict": False,
        "future_mainland_company_complexity": "manageable_if_domain_payment_and_icp_subject_are_planned_together",
        "recommended_formal_path": [
            "keep_app_jiejing_shop_as_private_beta_or_global_app_entry",
            "after_compliant_merchant_entity_is_ready_prepare_reviewed_payment_domain_or_subdomain",
            "file_mainland_icp_only_if_using_mainland_server_or_if_payment_provider_product_review_requires_icp_site",
            "keep payment callback urls on the reviewed domain and map secrets only in backend vault env",
        ],
        "subject_status": {
            "merchant_entity_ready": merchant_entity_ready,
            "mainland_icp_ready": mainland_icp_ready,
            "subject_consistency_required_before_formal_web_payment": True,
        },
        "triggers_real_charge": False,
        "frontend_gets_payment_secret": False,
        "secret_exposed": False,
    }


def _payment_strategy_blockers(
    selected_provider: str,
    manual_qr_enabled: bool,
    *,
    domestic_provider_ready: bool,
    domestic_adapter_enabled: bool,
    domestic_webhook_configured: bool,
    domestic_live_cutover_approved: bool,
    merchant_entity_ready: bool,
    mainland_icp_ready: bool,
) -> list[str]:
    blockers = []
    if not merchant_entity_ready:
        blockers.append("payment_merchant_entity_not_ready")
    if not mainland_icp_ready:
        blockers.append("mainland_payment_icp_subject_not_ready")
    if not domestic_provider_ready:
        blockers.append("domestic_payment_provider_not_ready")
    if selected_provider in {"not_selected", ""}:
        blockers.append("domestic_payment_provider_not_selected")
    if not domestic_adapter_enabled:
        blockers.append("domestic_payment_adapter_not_enabled")
    if not domestic_webhook_configured:
        blockers.append("domestic_signed_webhook_not_configured")
    if not domestic_live_cutover_approved:
        blockers.append("domestic_live_cutover_not_approved")
    if manual_qr_enabled:
        blockers.append("manual_qr_collection_not_paid_launch_ready")
    return blockers


def _canonical_provider(value: str) -> str:
    return (value or "not_selected").strip().lower().replace("-", "_") or "not_selected"


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip() or default


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}
