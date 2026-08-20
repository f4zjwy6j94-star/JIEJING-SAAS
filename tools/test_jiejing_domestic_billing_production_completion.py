#!/usr/bin/env python3
"""Production-completion regression for merchant-facing domestic billing."""

from __future__ import annotations

import gc
import copy
import os
import sys
import tempfile
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator
from unittest.mock import patch

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.billing_domestic import (  # noqa: E402
    CONTROLLED_WECHAT_PAY_ACCEPTANCE_APPROVAL,
    close_domestic_billing_order,
    create_controlled_wechat_pay_acceptance_order,
    create_domestic_billing_order,
    merchant_domestic_billing_order,
    open_domestic_billing_checkout,
)
from jiejing_saas.billing_wechat_pay import reconcile_wechat_pay_order_query  # noqa: E402
from jiejing_saas.billing_plan import build_billing_plan  # noqa: E402
from jiejing_saas.billing_payment_options import build_mainland_payment_strategy  # noqa: E402
from jiejing_saas.config import SaaSSettings  # noqa: E402
from jiejing_saas.repository import SaaSRepository  # noqa: E402
from jiejing_saas.readiness import _billing_item, _public_billing_status  # noqa: E402


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    with tempfile.TemporaryDirectory() as temp_dir:
        try:
            return _run_production_completion(Path(temp_dir))
        finally:
            gc.collect()


def _run_production_completion(temp_root: Path) -> int:
    settings = SaaSSettings.from_env(
        db_path=temp_root / "saas.sqlite",
        runtime_db_path=temp_root / "runtime.sqlite",
        output_root=temp_root,
        host="127.0.0.1",
        port=8788,
    )
    repository = SaaSRepository(settings.db_path)
    account_email = "billing-completion@example.test"
    account = repository.create_user_with_company(
        email=account_email,
        password="Billing-completion-2026",
        company_name="Billing Completion",
    )
    company_id = str(account["company"]["company_id"])
    user_id = str(account["user"]["user_id"])

    created = create_domestic_billing_order(
        repository,
        company_id=company_id,
        user_id=user_id,
        provider="wechat_pay_native",
        plan_key="starter",
        idempotency_key="merchant-production-checkout-1",
        rehearsal=False,
    )
    if created.get("ok") is not True or not created.get("expires_at"):
        return fail(f"live local order must have a bounded checkout lifetime: {created}")

    create_calls: list[str] = []

    def fake_create(*, order: dict[str, Any]) -> dict[str, Any]:
        create_calls.append(str(order["order_id"]))
        return {
            "ok": True,
            "status": "payable_order_created",
            "order_id": order["order_id"],
            "code_url": "weixin://wxpay/bizpayurl?pr=production-completion-token",
            "amount_minor": order["amount_minor"],
            "currency": order["currency"],
            "calls_external_payment_api": True,
            "triggers_real_charge": False,
            "secret_exposed": False,
        }

    opened = open_domestic_billing_checkout(
        repository,
        company_id=company_id,
        order_id=str(created["order_id"]),
        provider_create=fake_create,
    )
    safe_checkout = merchant_domestic_billing_order(opened, include_checkout=True)
    if not str(safe_checkout.get("qr_image_data_url") or "").startswith("data:image/png;base64,"):
        return fail(f"merchant checkout must receive an in-product QR image: {safe_checkout}")
    if "code_url" in safe_checkout or "weixin://" in str(safe_checkout):
        return fail(f"merchant checkout must not expose the raw provider payment URI: {safe_checkout}")
    if safe_checkout.get("can_close") is not True or safe_checkout.get("can_continue_payment") is not True:
        return fail(f"pending checkout must be recoverable and cancellable: {safe_checkout}")
    if safe_checkout.get("renewal_mode") != "merchant_confirmed_one_time_30_day":
        return fail(f"merchant checkout must declare one-time 30-day renewal: {safe_checkout}")

    stored = repository.get_domestic_billing_order(company_id=company_id, order_id=str(created["order_id"]))
    safe_list_item = merchant_domestic_billing_order(stored or {}, include_checkout=False)
    if "qr_image_data_url" in safe_list_item or "code_url" in safe_list_item or "company_id" in safe_list_item or "user_id" in safe_list_item:
        return fail(f"order history must only contain merchant-safe fields: {safe_list_item}")

    close_calls: list[str] = []

    def fake_close(*, order_id: str) -> dict[str, Any]:
        close_calls.append(order_id)
        return {
            "ok": True,
            "status": "provider_order_closed",
            "order_id": order_id,
            "calls_external_payment_api": True,
            "triggers_real_charge": False,
            "secret_exposed": False,
        }

    closed = close_domestic_billing_order(
        repository,
        company_id=company_id,
        user_id=user_id,
        order_id=str(created["order_id"]),
        provider_close=fake_close,
    )
    replayed_close = close_domestic_billing_order(
        repository,
        company_id=company_id,
        user_id=user_id,
        order_id=str(created["order_id"]),
        provider_close=fake_close,
    )
    if closed.get("status") != "closed" or replayed_close.get("duplicate_request") is not True:
        return fail(f"merchant cancellation must be durable and idempotent: {closed}, {replayed_close}")
    if close_calls != [str(created["order_id"])]:
        return fail(f"provider close must execute once: {close_calls}")
    if repository.get_domestic_billing_order(company_id=company_id, order_id=str(created["order_id"])).get("status") != "closed":
        return fail("closed state must be persisted")

    local_only = create_domestic_billing_order(
        repository,
        company_id=company_id,
        user_id=user_id,
        provider="wechat_pay_native",
        plan_key="starter",
        idempotency_key="merchant-local-cancel-1",
        rehearsal=False,
    )
    local_closed = close_domestic_billing_order(
        repository,
        company_id=company_id,
        user_id=user_id,
        order_id=str(local_only["order_id"]),
        provider_close=lambda **_: (_ for _ in ()).throw(AssertionError("local-only close must not call provider")),
    )
    if local_closed.get("status") != "closed" or local_closed.get("calls_external_payment_api") is not False:
        return fail(f"an order with no provider QR must cancel locally: {local_closed}")

    lock_account = repository.create_user_with_company(
        email="billing-close-lock@example.test",
        password="Billing-close-lock-2026",
        company_name="Billing Close Lock",
    )
    lock_company_id = str(lock_account["company"]["company_id"])
    lock_user_id = str(lock_account["user"]["user_id"])
    lock_order = create_domestic_billing_order(
        repository,
        company_id=lock_company_id,
        user_id=lock_user_id,
        provider="wechat_pay_native",
        plan_key="starter",
        idempotency_key="merchant-close-database-lock-1",
        rehearsal=False,
    )
    close_lock_repository = _CloseLockContractRepository(repository)
    lock_closed = close_domestic_billing_order(
        close_lock_repository,
        company_id=lock_company_id,
        user_id=lock_user_id,
        order_id=str(lock_order["order_id"]),
        provider_close=lambda **_: (_ for _ in ()).throw(AssertionError("local-only close must not call provider")),
    )
    if lock_closed.get("status") != "closed" or close_lock_repository.lock_entries != 1:
        return fail(f"unpaid order close must use the cross-instance company lock: {lock_closed}")

    expired_order_id = "domestic_expired_checkout_01"
    repository.create_domestic_billing_order_record(
        order_id=expired_order_id,
        company_id=company_id,
        user_id=user_id,
        provider="wechat_pay_native",
        plan_key="starter",
        amount_minor=9900,
        currency="CNY",
        duration_days=30,
        status="pending_payment",
        idempotency_key_hash="e" * 64,
        expires_at=(datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
        order={"display_name": "捷境基础版 30 天"},
    )
    expired = open_domestic_billing_checkout(
        repository,
        company_id=company_id,
        order_id=expired_order_id,
        provider_create=lambda **_: (_ for _ in ()).throw(AssertionError("expired checkout must not call provider")),
    )
    expired_safe = merchant_domestic_billing_order(
        repository.get_domestic_billing_order(company_id=company_id, order_id=expired_order_id) or {},
        include_checkout=True,
    )
    if expired.get("reason") != "domestic_billing_order_expired":
        return fail(f"expired checkout must fail before provider access: {expired}")
    if expired_safe.get("can_continue_payment") is not False or expired_safe.get("checkout_expired") is not True:
        return fail(f"expired checkout must be explicit and non-payable to the merchant: {expired_safe}")

    acceptance_create_calls: list[str] = []

    def fake_acceptance_create(*, order: dict[str, Any]) -> dict[str, Any]:
        acceptance_create_calls.append(str(order["order_id"]))
        return {
            "ok": True,
            "status": "payable_order_created",
            "order_id": order["order_id"],
            "code_url": "weixin://wxpay/bizpayurl?pr=controlled-production-completion",
            "amount_minor": order["amount_minor"],
            "currency": order["currency"],
            "calls_external_payment_api": False,
            "triggers_real_charge": False,
            "secret_exposed": False,
        }

    acceptance = create_controlled_wechat_pay_acceptance_order(
        repository,
        account_email=account_email,
        approval_phrase=CONTROLLED_WECHAT_PAY_ACCEPTANCE_APPROVAL,
        idempotency_key="production-completion-acceptance",
        provider_create=fake_acceptance_create,
    )
    acceptance_order_id = str(acceptance.get("order_id") or "")
    if acceptance.get("ok") is not True or acceptance.get("status") != "payable_order_created":
        return fail(f"controlled acceptance must create a local fake-provider QR: {acceptance}")
    if acceptance_create_calls != [acceptance_order_id]:
        return fail(f"controlled acceptance fake provider must execute once: {acceptance_create_calls}")
    reconciled = reconcile_wechat_pay_order_query(
        repository,
        company_id=company_id,
        order_id=acceptance_order_id,
        provider_response={
            "appid": "wx-production-completion-app",
            "mchid": "1900000109",
            "out_trade_no": acceptance_order_id,
            "transaction_id": "wx-verified-production-proof",
            "trade_type": "NATIVE",
            "trade_state": "SUCCESS",
            "success_time": "2026-07-13T16:00:00+08:00",
            "amount": {"total": 100, "currency": "CNY"},
        },
        query_authenticated=True,
        expected_appid="wx-production-completion-app",
        expected_mchid="1900000109",
    )
    if reconciled.get("ok") is not True or reconciled.get("entitlement_active") is not True:
        return fail(f"authenticated provider query must persist payment and entitlement: {reconciled}")
    stored_acceptance = repository.get_domestic_billing_order(company_id=company_id, order_id=acceptance_order_id) or {}
    stored_payload = stored_acceptance.get("order") if isinstance(stored_acceptance.get("order"), dict) else {}
    stored_checkout = stored_payload.get("checkout") if isinstance(stored_payload.get("checkout"), dict) else {}
    if stored_payload.get("payable_qr_created") is not False or stored_checkout.get("payable_uri_removed") is not True:
        return fail(f"paid acceptance must remove the payable QR URI: {stored_payload}")
    if stored_payload.get("frontend_gets_payment_secret") is not False:
        return fail(f"payment secret boundary must persist as strict false: {stored_payload}")
    paid_safe = merchant_domestic_billing_order(
        repository.get_domestic_billing_order(company_id=company_id, order_id=acceptance_order_id) or {},
        include_checkout=False,
    )
    if paid_safe.get("payment_record_available") is not True or paid_safe.get("payment_record_reference") != acceptance_order_id:
        return fail(f"paid order must expose a safe payment record reference: {paid_safe}")
    if paid_safe.get("invoice_request_available") is not True or paid_safe.get("invoice_request_route") != "service":
        return fail(f"paid order must expose the reviewed invoice request path: {paid_safe}")
    evidence = repository.domestic_payment_acceptance_evidence()
    if evidence.get("verified_paid_order_count") != 1 or evidence.get("controlled_acceptance_proven") is not True:
        return fail(f"readiness must recognize only verified controlled acceptance: {evidence}")
    if evidence.get("public_charging_allowed") is not False or evidence.get("charge_now_allowed") is not False:
        return fail(f"acceptance evidence must not open public charging: {evidence}")
    for key, expected in {
        "contract_version": "2026-07-27-domestic-payment-acceptance-evidence-v2",
        "provider": "wechat_pay_native",
        "acceptance_kind": "owner_approved_one_cny_live_acceptance",
        "triggers_real_charge": False,
        "calls_external_payment_api": False,
        "secret_exposed": False,
    }.items():
        if evidence.get(key) != expected or type(evidence.get(key)) is not type(expected):
            return fail(f"acceptance evidence contract mismatch: {key}: {evidence}")
    with _mainland_payment_owner_ready_env():
        legacy_strategy = build_mainland_payment_strategy(settings)
        plan = build_billing_plan(settings, repository)
        readiness_item = _billing_item(settings, repository)
        public_status = _public_billing_status(settings, repository)
    mainland_launch = plan.get("mainland_payment_launch") if isinstance(plan.get("mainland_payment_launch"), dict) else {}
    if mainland_launch.get("contract_version") != "2026-07-27-mainland-payment-launch-v1":
        return fail(f"billing plan must embed the canonical mainland launch contract: {mainland_launch}")
    if plan.get("mainland_payment_ready_for_owner_approval") is not True:
        return fail(f"billing plan must expose canonical owner-approval readiness: {plan}")
    future_payment = mainland_launch.get("future_international_payment") if isinstance(mainland_launch.get("future_international_payment"), dict) else {}
    if future_payment.get("provider") != "stripe" or future_payment.get("blocks_mainland_launch") is not False:
        return fail(f"Stripe must remain future international compatibility only: {future_payment}")
    future_compatibility = plan.get("future_international_payment") if isinstance(plan.get("future_international_payment"), dict) else {}
    if (
        future_compatibility.get("provider") != "stripe"
        or future_compatibility.get("role") != "future_international_payment_only"
        or future_compatibility.get("subscription_provider_contract_version") != "2026-05-26-signed-billing-provider"
        or future_compatibility.get("checkout_portal_contract_version") != "2026-06-18-stripe-checkout-portal-test-mode"
        or future_compatibility.get("blocks_mainland_launch") is not False
    ):
        return fail(f"billing plan must retain Stripe contracts as future-international compatibility only: {future_compatibility}")
    if plan.get("billing_ready_for_paid_launch") is not False:
        return fail("canonical owner readiness must not open the legacy paid-launch compatibility field")
    if legacy_strategy.get("selected_domestic_provider_ready_for_rehearsal") is not True:
        return fail(f"legacy strategy lane must honor native-contract raw PEM configuration: {legacy_strategy}")
    with _mainland_payment_owner_ready_env(), _platform_certificate_verification_env():
        certificate_fallback_strategy = build_mainland_payment_strategy(settings)
    if certificate_fallback_strategy.get("selected_domestic_provider_ready_for_rehearsal") is not True:
        return fail(
            "legacy strategy lane must honor the native-contract platform certificate fallback: "
            f"{certificate_fallback_strategy}"
        )
    if plan.get("billing_ready_for_private_beta") is not False:
        return fail("owner-ready payment evidence must not synthesize a missing private-beta billing contract")
    if (
        readiness_item.status != "blocked_private_beta_billing_not_ready"
        or readiness_item.severity != "blocker"
    ):
        return fail(
            "owner-ready payment evidence must remain blocked when the strict private-beta billing contract is absent: "
            f"{readiness_item}"
        )
    readiness_copy = f"{readiness_item.detail} {readiness_item.next_action}".lower()
    if "stripe" in readiness_copy or "external paid subscription provider" in readiness_copy:
        return fail(f"mainland billing readiness must not instruct merchants to configure Stripe: {readiness_item}")
    domestic_status = public_status.get("domestic_payment", {})
    if domestic_status.get("status") != "controlled_acceptance_proven":
        return fail(f"public readiness must report the controlled acceptance proof: {domestic_status}")
    if public_status.get("provider") != "wechat_pay_native":
        return fail(f"public readiness must identify the active domestic payment provider: {public_status}")
    if public_status.get("payment_path_status") != "controlled_acceptance_proven_public_charging_closed":
        return fail(f"public readiness must expose one coherent payment path status: {public_status}")
    if public_status.get("next_paid_launch_blocker") != "merchant_payment_public_cutover_not_approved":
        return fail(f"public readiness must not report the legacy test provider as the next blocker: {public_status}")
    if public_status.get("mainland_payment_ready_for_owner_approval") is not True:
        return fail(f"public readiness must preserve canonical owner-approval readiness: {public_status}")
    if domestic_status.get("checkout_mode") != "native_qr" or domestic_status.get("billing_mode") != "one_time_30_day_plan":
        return fail(f"public readiness must describe the mainland Native QR path: {domestic_status}")
    if public_status.get("merchant_launch_path", {}).get("hosted_payment_page_required_for_formal_payment") is not False:
        return fail(f"WeChat Native checkout must not require a Stripe-style hosted payment page: {public_status}")
    if domestic_status.get("configured_component_count") != 9 or domestic_status.get("required_component_count") != 9:
        return fail(f"public readiness must expose only safe aggregate configuration counts: {domestic_status}")
    if domestic_status.get("verified_paid_order_count") != 1:
        return fail(f"public readiness must expose only the aggregate verified-payment count: {domestic_status}")
    for internal_capability in (
        "signed_callback_implemented",
        "signed_payment_callback_implemented",
        "signed_refund_callback_implemented",
        "real_order_creation_implemented",
        "authenticated_order_query_implemented",
        "quota_entitlement_persistence_implemented",
        "high_risk_confirmation_boundary_implemented",
    ):
        if internal_capability in domestic_status:
            return fail(f"public readiness must not expose code-capability diagnostics: {domestic_status}")
    if public_status.get("provider_configured") is not True:
        return fail(f"public readiness must recognize the fully configured domestic provider: {public_status}")
    if public_status.get("charge_now_allowed") is not False or domestic_status.get("charge_now_allowed") is not False:
        return fail(f"controlled acceptance must never silently open public charging: {public_status}")
    serialized_status = str(public_status).lower()
    if any(value in serialized_status for value in (company_id.lower(), user_id.lower(), "wx-verified-production-proof")):
        return fail(f"public readiness must not leak order, tenant or provider references: {public_status}")
    for internal_marker in (
        "component_presence",
        "acceptance_kind",
        "owner_approval_recorded",
        "production_environment",
        "external_paid_subscription_provider_not_configured",
        "test_billing_provider_not_allowed_for_paid_launch",
        "jiejing_wechat_pay_",
    ):
        if internal_marker in serialized_status:
            return fail(f"public readiness must not expose internal payment diagnostics: {internal_marker}: {public_status}")

    canonical_launch = copy.deepcopy(mainland_launch)
    malformed_variants: list[tuple[str, dict[str, Any]]] = []
    for field, invalid_value in (
        ("contract_version", "wrong-contract"),
        ("market", "international"),
        ("primary_provider", "stripe"),
        ("checkout_mode", "hosted"),
        ("billing_mode", "subscription"),
    ):
        candidate = copy.deepcopy(canonical_launch)
        candidate[field] = invalid_value
        malformed_variants.append((field, candidate))
    for safety_field in (
        "public_charging_allowed",
        "charge_now_allowed",
        "triggers_real_charge",
        "triggers_real_refund",
        "calls_external_payment_api",
        "calls_stripe_api",
        "real_platform_writes_enabled",
        "frontend_gets_payment_secret",
        "secret_exposed",
    ):
        candidate = copy.deepcopy(canonical_launch)
        candidate[safety_field] = True
        malformed_variants.append((safety_field, candidate))
    invalid_verified_count = copy.deepcopy(canonical_launch)
    invalid_verified_count["acceptance_evidence"]["verified_paid_order_count"] = "1"
    malformed_variants.append(("verified_paid_order_count", invalid_verified_count))
    invalid_float_verified_count = copy.deepcopy(canonical_launch)
    invalid_float_verified_count["acceptance_evidence"]["verified_paid_order_count"] = 1.0
    malformed_variants.append(("float_verified_paid_order_count", invalid_float_verified_count))
    invalid_acceptance_provider = copy.deepcopy(canonical_launch)
    invalid_acceptance_provider["acceptance_evidence"]["provider"] = "stripe"
    malformed_variants.append(("acceptance_provider", invalid_acceptance_provider))
    invalid_acceptance_kind = copy.deepcopy(canonical_launch)
    invalid_acceptance_kind["acceptance_evidence"]["acceptance_kind"] = "uncontrolled_payment"
    malformed_variants.append(("acceptance_kind", invalid_acceptance_kind))
    invalid_acceptance_safety = copy.deepcopy(canonical_launch)
    invalid_acceptance_safety["acceptance_evidence"]["calls_external_payment_api"] = "false"
    malformed_variants.append(("acceptance_safety_type", invalid_acceptance_safety))
    invalid_refund_type = copy.deepcopy(canonical_launch)
    invalid_refund_type["refund_now_allowed"] = "true"
    malformed_variants.append(("refund_now_allowed_type", invalid_refund_type))
    invalid_owner_marker = copy.deepcopy(canonical_launch)
    invalid_owner_marker["mainland_payment_ready_for_owner_approval"] = "true"
    malformed_variants.append(("owner_ready_type", invalid_owner_marker))
    invalid_configured_count = copy.deepcopy(canonical_launch)
    invalid_configured_count["configuration"]["completed_count"] = True
    malformed_variants.append(("completed_count", invalid_configured_count))
    for label, candidate in malformed_variants:
        malformed_public = _public_status_for_launch(settings, repository, plan, candidate)
        malformed_domestic = malformed_public.get("domestic_payment", {})
        if (
            malformed_public.get("mainland_payment_ready_for_owner_approval") is not False
            or malformed_public.get("provider_configured") is not False
            or malformed_domestic.get("controlled_acceptance_proven") is not False
            or malformed_domestic.get("verified_paid_order_count") != 0
            or malformed_public.get("next_paid_launch_blocker") != "merchant_payment_status_unavailable"
        ):
            return fail(f"malformed canonical launch must fail closed ({label}): {malformed_public}")

    precedence_cases: list[tuple[str, dict[str, Any], str]] = []
    configuration_incomplete = copy.deepcopy(canonical_launch)
    configuration_incomplete["configuration"] = {
        **configuration_incomplete["configuration"],
        "complete": False,
        "completed_count": 8,
    }
    configuration_incomplete["provider_checkout_ready"] = False
    precedence_cases.append(
        ("configuration", configuration_incomplete, "merchant_payment_provider_configuration_incomplete")
    )
    capability_incomplete = copy.deepcopy(canonical_launch)
    capability_incomplete["code_capabilities"]["signed_payment_callback_implemented"] = False
    precedence_cases.append(
        ("capability", capability_incomplete, "merchant_payment_backend_safety_controls_incomplete")
    )
    provider_disconnected = copy.deepcopy(canonical_launch)
    provider_disconnected["provider_checkout_ready"] = False
    provider_disconnected["provider_runtime_activation_enabled"] = False
    provider_disconnected["provider_connection_evidence"] = {
        **provider_disconnected["provider_connection_evidence"],
        "provider_connection_proof_ready": False,
        "verified_proof_count": 0,
        "latest_verified_at": "",
        "proof_query_called_external_api": False,
    }
    precedence_cases.append(
        ("provider", provider_disconnected, "merchant_payment_provider_runtime_activation_pending")
    )
    nonproduction = copy.deepcopy(canonical_launch)
    nonproduction["production_environment"] = False
    precedence_cases.append(
        ("production", nonproduction, "merchant_payment_production_environment_required")
    )
    refund_not_ready = copy.deepcopy(canonical_launch)
    refund_not_ready["refund_now_allowed"] = False
    precedence_cases.append(
        ("refund", refund_not_ready, "merchant_payment_refund_not_ready")
    )
    acceptance_missing = copy.deepcopy(canonical_launch)
    acceptance_missing["controlled_acceptance_proven"] = False
    acceptance_missing["acceptance_evidence"]["controlled_acceptance_proven"] = False
    acceptance_missing["acceptance_evidence"]["verified_paid_order_count"] = 0
    precedence_cases.append(
        ("acceptance", acceptance_missing, "merchant_payment_controlled_acceptance_not_proven")
    )
    for label, candidate, expected_blocker in precedence_cases:
        candidate["mainland_payment_ready_for_owner_approval"] = True
        candidate_public = _public_status_for_launch(settings, repository, plan, candidate)
        if candidate_public.get("next_paid_launch_blocker") != expected_blocker:
            return fail(f"public mainland blocker precedence mismatch ({label}): {candidate_public}")
        if candidate_public.get("mainland_payment_ready_for_owner_approval") is not False:
            return fail(f"historical/raw owner-ready must not bypass current {label} readiness: {candidate_public}")
    configuration_public = _public_status_for_launch(settings, repository, plan, configuration_incomplete)
    if configuration_public.get("payment_path_status") != "configuration_in_progress":
        return fail(f"historical proof must not hide current provider configuration loss: {configuration_public}")

    provider_activation_public = _public_status_for_launch(settings, repository, plan, provider_disconnected)
    if (
        provider_activation_public.get("payment_path_status") != "provider_activation_pending"
        or provider_activation_public.get("next_paid_launch_blocker")
        != "merchant_payment_provider_runtime_activation_pending"
        or provider_activation_public.get("provider_configured") is not True
        or provider_activation_public.get("mainland_payment_ready_for_owner_approval") is not False
        or provider_activation_public.get("charge_now_allowed") is not False
    ):
        return fail(
            "a fully configured provider with controlled acceptance must report runtime activation pending, "
            f"not a broken merchant connection: {provider_activation_public}"
        )

    unverified_provider = copy.deepcopy(provider_disconnected)
    unverified_provider["controlled_acceptance_proven"] = False
    unverified_provider["acceptance_evidence"]["controlled_acceptance_proven"] = False
    unverified_provider["acceptance_evidence"]["verified_paid_order_count"] = 0
    unverified_provider_public = _public_status_for_launch(settings, repository, plan, unverified_provider)
    if (
        unverified_provider_public.get("payment_path_status") != "provider_connection_in_progress"
        or unverified_provider_public.get("next_paid_launch_blocker")
        != "merchant_payment_provider_connection_not_ready"
        or unverified_provider_public.get("provider_configured") is not False
        or unverified_provider_public.get("mainland_payment_ready_for_owner_approval") is not False
        or unverified_provider_public.get("charge_now_allowed") is not False
    ):
        return fail(
            "configuration without controlled acceptance must remain an unverified provider connection: "
            f"{unverified_provider_public}"
        )

    ready_public = _public_status_for_launch(settings, repository, plan, canonical_launch)
    if ready_public.get("next_paid_launch_blocker") != "merchant_payment_public_cutover_not_approved":
        return fail(f"only a currently complete canonical launch may reach public cutover review: {ready_public}")

    repository_source = (ROOT / "jiejing_saas" / "repository.py").read_text(encoding="utf-8")
    if "where company_id = ? and order_id = ? and status = ?" not in repository_source:
        return fail("domestic billing state transitions must use database compare-and-swap")
    if "if updated != 1:" not in repository_source:
        return fail("checkout attachment must not audit a lost pending-payment compare-and-swap")

    print("PASS jiejing_domestic_billing_production_completion")
    return 0


def _public_status_for_launch(
    settings: SaaSSettings,
    repository: SaaSRepository,
    source_plan: dict[str, Any],
    launch: dict[str, Any],
) -> dict[str, Any]:
    candidate_plan = copy.deepcopy(source_plan)
    candidate_plan["mainland_payment_launch"] = launch
    candidate_plan["mainland_payment_ready_for_owner_approval"] = True
    with patch("jiejing_saas.readiness.build_billing_plan", return_value=candidate_plan):
        return _public_billing_status(settings, repository)


class _CloseLockContractRepository:
    """Require close-state reads and writes to occur inside the company lock."""

    def __init__(self, delegate: SaaSRepository) -> None:
        self._delegate = delegate
        self._lock_depth = 0
        self.lock_entries = 0

    @contextmanager
    def domestic_billing_company_lock(self, *, company_id: str) -> Iterator[None]:
        self.lock_entries += 1
        with self._delegate.domestic_billing_company_lock(company_id=company_id):
            self._lock_depth += 1
            try:
                yield
            finally:
                self._lock_depth -= 1

    def get_domestic_billing_order(self, **kwargs: object) -> dict[str, Any] | None:
        self._require_lock()
        return self._delegate.get_domestic_billing_order(**kwargs)

    def update_domestic_billing_order_state(self, **kwargs: object) -> dict[str, Any] | None:
        self._require_lock()
        return self._delegate.update_domestic_billing_order_state(**kwargs)

    def _require_lock(self) -> None:
        if self._lock_depth <= 0:
            raise AssertionError("domestic billing close occurred outside the company lock")

    def __getattr__(self, name: str) -> object:
        return getattr(self._delegate, name)


@contextmanager
def _mainland_payment_owner_ready_env() -> Iterator[None]:
    merchant_private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    merchant_private_key_pem = merchant_private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("ascii")
    verification_private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    verification_public_key_pem = verification_private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("ascii")
    values = {
        "JIEJING_SAAS_ENV": "production",
        "JIEJING_WECHAT_PAY_APP_ID": "wx-mainland-phase2-fixture",
        "JIEJING_WECHAT_PAY_MCH_ID": "1900000109",
        "JIEJING_WECHAT_PAY_MERCHANT_SERIAL_NO": "MAINLANDPHASE2SERIAL",
        "JIEJING_WECHAT_PAY_MERCHANT_PRIVATE_KEY_PEM": merchant_private_key_pem,
        "JIEJING_WECHAT_PAY_MERCHANT_PRIVATE_KEY_PEM_B64": "",
        "JIEJING_WECHAT_PAY_API_V3_KEY": "a" * 32,
        "JIEJING_WECHAT_PAY_PUBLIC_KEY_ID": "PUB_KEY_ID_MAINLAND_PHASE2",
        "JIEJING_WECHAT_PAY_PUBLIC_KEY_PEM": verification_public_key_pem,
        "JIEJING_WECHAT_PAY_PUBLIC_KEY_PEM_B64": "",
        "JIEJING_WECHAT_PAY_NOTIFY_URL": "https://app.example.test/billing/wechat-pay/notify",
        "JIEJING_WECHAT_PAY_REFUND_NOTIFY_URL": "https://app.example.test/billing/wechat-pay/refund-notify",
        "JIEJING_WECHAT_PAY_LIVE_API_ENABLED": "true",
        "JIEJING_WECHAT_PAY_REFUND_ALLOWED": "true",
        "JIEJING_PAID_LAUNCH_OWNER_APPROVAL_PACKET_ID": "phase2-fixture-owner-packet",
        "JIEJING_BILLING_PROVIDER": "",
        "JIEJING_DOMESTIC_PAYMENT_PROVIDER": "wechat_pay_native",
    }
    previous = {key: os.environ.get(key) for key in values}
    try:
        os.environ.update(values)
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


@contextmanager
def _platform_certificate_verification_env() -> Iterator[None]:
    keys = (
        "JIEJING_WECHAT_PAY_PUBLIC_KEY_ID",
        "JIEJING_WECHAT_PAY_PUBLIC_KEY_PEM",
        "JIEJING_WECHAT_PAY_PUBLIC_KEY_PEM_B64",
        "JIEJING_WECHAT_PAY_PLATFORM_SERIAL_NO",
        "JIEJING_WECHAT_PAY_PLATFORM_CERTIFICATE_PEM",
        "JIEJING_WECHAT_PAY_PLATFORM_CERTIFICATE_PEM_B64",
    )
    previous = {key: os.environ.get(key) for key in keys}
    platform_private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Jiejing platform test")])
    platform_certificate_pem = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(platform_private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(timezone.utc) - timedelta(minutes=1))
        .not_valid_after(datetime.now(timezone.utc) + timedelta(days=1))
        .sign(platform_private_key, hashes.SHA256())
        .public_bytes(serialization.Encoding.PEM)
        .decode("ascii")
    )
    try:
        os.environ.pop("JIEJING_WECHAT_PAY_PUBLIC_KEY_ID", None)
        os.environ.pop("JIEJING_WECHAT_PAY_PUBLIC_KEY_PEM", None)
        os.environ.pop("JIEJING_WECHAT_PAY_PUBLIC_KEY_PEM_B64", None)
        os.environ["JIEJING_WECHAT_PAY_PLATFORM_SERIAL_NO"] = "PLATFORMPHASE2SERIAL"
        os.environ["JIEJING_WECHAT_PAY_PLATFORM_CERTIFICATE_PEM"] = platform_certificate_pem
        os.environ.pop("JIEJING_WECHAT_PAY_PLATFORM_CERTIFICATE_PEM_B64", None)
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


if __name__ == "__main__":
    raise SystemExit(main())
