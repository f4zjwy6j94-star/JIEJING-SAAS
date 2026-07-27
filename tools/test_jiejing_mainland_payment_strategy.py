#!/usr/bin/env python3
"""Regression for mainland-first billing strategy.

This deliberately does not test QR login. Jiejing is keeping email login as the
current account path and solving collection through domestic payment rails first.
"""

from __future__ import annotations

import gc
import json
import os
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas import billing_payment_options as payment_options  # noqa: E402
from jiejing_saas import billing_domestic as domestic_billing  # noqa: E402
from jiejing_saas.billing_payment_options import (  # noqa: E402
    build_mainland_payment_launch_status,
    build_mainland_payment_strategy,
)
from jiejing_saas.config import SaaSSettings  # noqa: E402
from jiejing_saas.repository import SaaSRepository  # noqa: E402


ACCEPTANCE_CONTRACT_VERSION = "2026-07-27-domestic-payment-acceptance-evidence-v2"
ACCEPTANCE_KIND = "owner_approved_one_cny_live_acceptance"
WECHAT_CONFIGURATION_KEYS = (
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


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    temp_context = tempfile.TemporaryDirectory()
    temp_root = Path(temp_context.name)
    previous = _set_env()
    try:
        settings = SaaSSettings.from_env(
            db_path=temp_root / "saas.sqlite",
            runtime_db_path=temp_root / "runtime.sqlite",
            output_root=temp_root,
            host="127.0.0.1",
            port=8788,
        )

        strategy = build_mainland_payment_strategy(settings)
        if strategy.get("contract_version") != "2026-06-29-mainland-payment-strategy":
            return fail(f"payment strategy contract mismatch: {strategy}")
        if strategy.get("recommended_primary_route") != "domestic_wallets_or_aggregate_acquirer":
            return fail(f"mainland users should default to domestic wallets/acquirer: {strategy}")
        if "manual_qr_cannot_auto_stop_quota_after_payment_failure_or_cancel" not in strategy.get("why_not_static_qr_for_paid_saas", []):
            return fail("manual QR collection must document why it is not a paid SaaS subscription rail")
        if strategy.get("paid_launch_ready") is not False or strategy.get("triggers_real_charge") is not False:
            return fail(f"unconfigured mainland strategy must not be paid-launch ready or charge-capable: {strategy}")
        if strategy.get("manual_qr_collection", {}).get("private_beta_only") is not True:
            return fail("manual collection code must stay private-beta-only")
        if strategy.get("manual_qr_collection", {}).get("auto_entitlement_update") is not False:
            return fail("manual QR collection must not auto-activate subscription/quota")
        formal = strategy.get("formal_collection_architecture") or {}
        if formal.get("contract_version") != "2026-06-29-formal-payment-collection-architecture":
            return fail(f"formal collection architecture missing: {formal}")
        if formal.get("manual_qr_boundary", {}).get("can_be_paid_public_launch_provider") is not False:
            return fail("personal QR must never become the formal paid launch provider")
        formal_steps = {step.get("key") for step in formal.get("steps", []) if isinstance(step, dict)}
        for key in {
            "merchant_entity",
            "domain_icp_subject_alignment",
            "create_order",
            "provider_checkout",
            "signed_webhook_and_order_query",
            "subscription_quota_audit",
            "owner_live_cutover",
        }:
            if key not in formal_steps:
                return fail(f"formal payment spine missing step: {key}")
        domain_plan = strategy.get("domain_and_icp_plan") or {}
        if domain_plan.get("future_mainland_company_conflict") is not False:
            return fail(f"mainland company path should not conflict with the current HK route when planned: {domain_plan}")
        if domain_plan.get("current_hk_route_icp_required") is not False:
            return fail("current HK/overseas route should not claim a mainland ICP filing is already required")
        entity = strategy.get("merchant_entity_readiness") or {}
        if entity.get("contract_version") != "2026-06-30-merchant-entity-payment-readiness":
            return fail(f"merchant entity readiness contract missing: {entity}")
        if entity.get("recommended_entity_path") != "individual_business_first_then_company_if_scale_requires":
            return fail(f"merchant entity path should prefer individual business first: {entity}")
        if entity.get("merchant_entity_ready") is not False:
            return fail(f"merchant entity should start as not ready: {entity}")
        checklist = {item.get("key"): item for item in entity.get("checklist", []) if isinstance(item, dict)}
        for key in {
            "business_license",
            "operator_identity_and_bank",
            "service_docs_and_contact",
            "domain_subject_alignment",
            "signed_callback_and_order_query",
        }:
            if key not in checklist:
                return fail(f"merchant entity checklist missing: {key}")
        if entity.get("can_auto_grant_paid_entitlement") is not False:
            return fail("formal entitlement automation must require provider + signed callback evidence")
        application_packet = strategy.get("merchant_application_packet") or {}
        if application_packet.get("contract_version") != "2026-07-01-merchant-payment-application-packet":
            return fail(f"merchant payment application packet missing: {application_packet}")
        if application_packet.get("does_not_collect_identity_files_in_frontend") is not True:
            return fail("merchant application packet must not collect identity files in the frontend")
        if application_packet.get("can_auto_grant_paid_entitlement") is not False:
            return fail("merchant application packet must not auto-grant entitlement before signed provider evidence")
        review_brief = application_packet.get("customer_review_brief") or {}
        if review_brief.get("contract_version") != "2026-07-01-payment-review-customer-brief":
            return fail(f"payment review customer brief missing: {review_brief}")
        if review_brief.get("review_ready") is not False:
            return fail("payment review should stay not ready until public support contact is configured")
        if "public_support_contact" not in review_brief.get("missing_for_review", []):
            return fail(f"payment review should surface missing support contact: {review_brief}")
        support = review_brief.get("refund_and_support") or {}
        if support.get("support_contact_status") != "pending_public_support_contact":
            return fail(f"support contact should be visibly pending before owner config: {support}")
        for required_scope in {"eBay-first AI CEO workbench", "confirmation_center_for_high_risk_actions"}:
            if required_scope not in set(review_brief.get("service_scope", [])):
                return fail(f"payment review brief missing service scope: {required_scope}")
        for required_term in {
            "base_subscription_is_software_feature_fee",
            "ai_model_media_and_search_usage_can_be_separate",
            "ebay_fees_ads_shipping_refunds_are_settled_by_merchant_platform_accounts",
        }:
            if required_term not in set(review_brief.get("billing_terms", [])):
                return fail(f"payment review brief missing billing boundary: {required_term}")
        packet_checklist = {item.get("key"): item for item in application_packet.get("checklist", []) if isinstance(item, dict)}
        for key in {
            "merchant_subject",
            "operator_and_settlement",
            "service_privacy_refund_pages",
            "pricing_and_subscription_terms",
            "support_contact",
            "reviewed_domain_and_callbacks",
            "signed_callback_and_order_query",
        }:
            if key not in packet_checklist:
                return fail(f"merchant application packet missing checklist item: {key}")
        if packet_checklist["merchant_subject"].get("label") != "合规商户主体":
            return fail(f"merchant subject label should stay customer-safe: {packet_checklist['merchant_subject']}")
        callback_urls = application_packet.get("provider_callback_urls") or {}
        if callback_urls.get("webhook_url") != "https://app.jiejing.shop/billing/webhook":
            return fail(f"merchant application packet should expose reviewed callback URL without secrets: {callback_urls}")
        review_urls = application_packet.get("review_urls") or {}
        for key, url in {
            "refund_policy": "https://app.jiejing.shop/refund-policy.html",
            "support": "https://app.jiejing.shop/support.html",
        }.items():
            if review_urls.get(key) != url:
                return fail(f"merchant application packet missing public payment review URL {key}: {review_urls}")
        if application_packet.get("charge_now_allowed") is not False or application_packet.get("triggers_real_charge") is not False:
            return fail("merchant application packet must not be charge-capable")
        _assert_no_identity_or_bank_material(application_packet)
        if "payment_merchant_entity_not_ready" not in strategy.get("paid_launch_blockers", []):
            return fail("formal paid launch should be blocked until merchant entity is ready")
        if "mainland_payment_icp_subject_not_ready" not in strategy.get("paid_launch_blockers", []):
            return fail("formal paid launch should be blocked until mainland ICP/payment subject alignment is ready")
        settlement = {lane["key"]: lane for lane in strategy.get("settlement_lanes", [])}
        for key in ["worldfirst", "payoneer"]:
            if settlement.get(key, {}).get("use_as_checkout_provider") is not False:
                return fail(f"{key} should remain settlement/receivables, not primary SaaS checkout: {settlement.get(key)}")
        _assert_no_secret_material(strategy)
        _assert_no_internal_payment_copy(strategy)

        os.environ["JIEJING_DOMESTIC_PAYMENT_PROVIDER"] = "alipay"
        os.environ["JIEJING_ALIPAY_APP_ID"] = "configured"
        os.environ["JIEJING_ALIPAY_PRIVATE_KEY_REF"] = "vault://alipay/private-key"
        os.environ["JIEJING_ALIPAY_PUBLIC_CERT_REF"] = "vault://alipay/public-cert"
        rehearsal_strategy = build_mainland_payment_strategy(settings)
        if rehearsal_strategy.get("selected_domestic_provider_ready_for_rehearsal") is not True:
            return fail(f"alipay lane should be rehearsal-ready when refs are configured: {rehearsal_strategy}")
        if rehearsal_strategy.get("paid_launch_ready") is not False:
            return fail("provider refs alone must not make paid launch ready")
        os.environ["JIEJING_DOMESTIC_PAYMENT_ADAPTER_ENABLED"] = "1"
        os.environ["JIEJING_DOMESTIC_PAYMENT_WEBHOOK_CONFIGURED"] = "1"
        os.environ["JIEJING_DOMESTIC_PAYMENT_LIVE_CUTOVER_APPROVED"] = "1"
        provider_without_entity = build_mainland_payment_strategy(settings)
        if provider_without_entity.get("paid_launch_ready") is not False:
            return fail("domestic provider + webhook + cutover cannot be paid-launch ready without merchant entity")
        if "payment_merchant_entity_not_ready" not in provider_without_entity.get("paid_launch_blockers", []):
            return fail(f"provider-ready fixture should still block on merchant entity: {provider_without_entity}")

        os.environ["JIEJING_PAYMENT_MERCHANT_ENTITY_READY"] = "1"
        os.environ["JIEJING_MAINLAND_PAYMENT_ICP_READY"] = "1"
        full_formal_strategy = build_mainland_payment_strategy(settings)
        if full_formal_strategy.get("paid_launch_ready") is not True:
            return fail(f"full formal fixture should satisfy paid launch strategy: {full_formal_strategy.get('paid_launch_blockers')}")
        if full_formal_strategy.get("charge_now_allowed") is not False or full_formal_strategy.get("triggers_real_charge") is not False:
            return fail("strategy readiness is not permission to charge during the test")
        full_entity = full_formal_strategy.get("merchant_entity_readiness") or {}
        if full_entity.get("merchant_entity_ready") is not True or full_entity.get("mainland_icp_or_subject_alignment_ready") is not True:
            return fail(f"full formal fixture should surface entity readiness: {full_entity}")

        with _strict_temporary_directory() as temp_dir:
            repository = SaaSRepository(Path(temp_dir) / "launch-status.sqlite")
            repository.initialize()
            launch_status = build_mainland_payment_launch_status(settings, repository)
            if launch_status.get("contract_version") != "2026-07-27-mainland-payment-launch-v1":
                return fail(f"mainland payment launch contract mismatch: {launch_status}")
            if launch_status.get("market") != "mainland_china" or launch_status.get("primary_provider") != "wechat_pay_native":
                return fail(f"mainland launch must have one WeChat Pay Native primary route: {launch_status}")
            future_payment = launch_status.get("future_international_payment") or {}
            if future_payment.get("provider") != "stripe" or future_payment.get("blocks_mainland_launch") is not False:
                return fail(f"Stripe must remain future international information only: {future_payment}")
            if any("stripe" in str(item).lower() for item in launch_status.get("paid_launch_blockers", [])):
                return fail(f"Stripe absence must not block mainland launch: {launch_status.get('paid_launch_blockers')}")
            configuration = launch_status.get("configuration") or {}
            if configuration.get("required_count") != 9 or configuration.get("completed_count") != 0 or configuration.get("complete") is not False:
                return fail(f"empty WeChat configuration must remain precisely blocked: {configuration}")
            if "wechat_pay_appid_not_configured" not in launch_status.get("paid_launch_blockers", []):
                return fail(f"missing WeChat configuration must be explicit: {launch_status.get('paid_launch_blockers')}")
            capabilities = launch_status.get("code_capabilities") or {}
            for key in {
                "signed_payment_callback_implemented",
                "signed_refund_callback_implemented",
                "real_order_creation_implemented",
                "authenticated_order_query_implemented",
                "quota_entitlement_persistence_implemented",
                "high_risk_confirmation_boundary_implemented",
            }:
                if capabilities.get(key) is not True:
                    return fail(f"mainland payment launch capability missing: {key}: {capabilities}")
            if launch_status.get("provider_checkout_ready") is not False:
                return fail("unconfigured provider must not be checkout-ready")
            if launch_status.get("controlled_acceptance_proven") is not False:
                return fail("empty repository must not claim controlled payment acceptance")
            _assert_launch_status_safety(launch_status)

            original_contract_builder = payment_options.wechat_pay.build_wechat_pay_native_contract
            try:
                payment_options.wechat_pay.build_wechat_pay_native_contract = lambda: {
                    "configured": {},
                    "signed_callback_implemented": True,
                    "signed_refund_callback_implemented": True,
                    "real_order_creation_implemented": True,
                    "refund_execution_confirmation_required": True,
                    "provider_connection_ready": False,
                    "production_environment": False,
                    "owner_approval_recorded": False,
                    "refund_now_allowed": False,
                }
                malformed_contract_status = build_mainland_payment_launch_status(settings, repository)
            finally:
                payment_options.wechat_pay.build_wechat_pay_native_contract = original_contract_builder
            if "wechat_pay_configuration_contract_missing" not in malformed_contract_status.get("paid_launch_blockers", []):
                return fail(f"missing configuration contract must have an exact blocker: {malformed_contract_status}")
            malformed_configuration = malformed_contract_status.get("configuration") or {}
            if malformed_configuration.get("required_count") != 9 or malformed_configuration.get("completed_count") != 0:
                return fail(f"missing configuration contract must retain the fixed nine-item denominator: {malformed_configuration}")

            partial_contract = {
                "configured": {"appid": True},
                "signed_callback_implemented": True,
                "signed_refund_callback_implemented": True,
                "real_order_creation_implemented": True,
                "refund_execution_confirmation_required": True,
                "provider_connection_ready": True,
                "production_environment": True,
                "owner_approval_recorded": True,
                "refund_now_allowed": True,
            }
            original_contract_builder = payment_options.wechat_pay.build_wechat_pay_native_contract
            try:
                payment_options.wechat_pay.build_wechat_pay_native_contract = lambda: dict(partial_contract)
                partial_status = build_mainland_payment_launch_status(settings, repository)
            finally:
                payment_options.wechat_pay.build_wechat_pay_native_contract = original_contract_builder
            partial_configuration = partial_status.get("configuration") or {}
            if partial_configuration.get("required_count") != 9 or partial_configuration.get("completed_count") != 1:
                return fail(f"partial configuration must use the fixed denominator: {partial_configuration}")
            if partial_configuration.get("complete") is not False or partial_status.get("provider_checkout_ready") is not False:
                return fail(f"nonempty partial configuration must remain blocked: {partial_status}")
            expected_missing = [f"wechat_pay_{key}_not_configured" for key in WECHAT_CONFIGURATION_KEYS[1:]]
            actual_missing = [item for item in partial_status.get("paid_launch_blockers", []) if item.endswith("_not_configured")]
            if actual_missing != expected_missing:
                return fail(f"configuration blockers must be fixed-order and exact: {actual_missing}")
            if len(partial_status.get("paid_launch_blockers", [])) != len(set(partial_status.get("paid_launch_blockers", []))):
                return fail(f"launch blockers must be de-duplicated: {partial_status.get('paid_launch_blockers')}")

            original_strategy_builder = payment_options.build_mainland_payment_strategy
            original_contract_builder = payment_options.wechat_pay.build_wechat_pay_native_contract
            try:
                payment_options.build_mainland_payment_strategy = _raise_status_exception
                _assert_unavailable_fallback(build_mainland_payment_launch_status(settings, repository))
                payment_options.build_mainland_payment_strategy = original_strategy_builder
                payment_options.wechat_pay.build_wechat_pay_native_contract = _raise_status_exception
                _assert_unavailable_fallback(build_mainland_payment_launch_status(settings, repository))
            finally:
                payment_options.build_mainland_payment_strategy = original_strategy_builder
                payment_options.wechat_pay.build_wechat_pay_native_contract = original_contract_builder
            _assert_unavailable_fallback(build_mainland_payment_launch_status(settings, _ExplodingEvidenceRepository()))
            invalid_count_status = build_mainland_payment_launch_status(settings, _InvalidCountRepository())
            if invalid_count_status.get("acceptance_evidence", {}).get("verified_paid_order_count") != 0:
                return fail(f"invalid verified count must safely normalize to zero: {invalid_count_status}")
            if "mainland_payment_status_unavailable" in invalid_count_status.get("paid_launch_blockers", []):
                return fail(f"invalid aggregate count must not crash the whole payment status: {invalid_count_status}")
            _assert_inconsistent_acceptance_fails_closed(invalid_count_status)
            _assert_inconsistent_acceptance_fails_closed(
                build_mainland_payment_launch_status(settings, _ZeroCountRepository())
            )
            for invalid_count in (True, 1.9, "1", -1):
                strict_invalid_status = build_mainland_payment_launch_status(
                    settings,
                    _AcceptanceEvidenceRepository(source_flag=True, verified_count=invalid_count),
                )
                if strict_invalid_status.get("acceptance_evidence", {}).get("verified_paid_order_count") != 0:
                    return fail(f"non-native or negative verified count must normalize to zero: {invalid_count!r}: {strict_invalid_status}")
                _assert_inconsistent_acceptance_fails_closed(strict_invalid_status)
            reverse_inconsistent_status = build_mainland_payment_launch_status(
                settings,
                _AcceptanceEvidenceRepository(source_flag=False, verified_count=1),
            )
            _assert_inconsistent_acceptance_fails_closed(reverse_inconsistent_status)
            valid_integer_status = build_mainland_payment_launch_status(
                settings,
                _AcceptanceEvidenceRepository(source_flag=True, verified_count=1),
            )
            if valid_integer_status.get("controlled_acceptance_proven") is not True:
                return fail(f"native positive integer evidence must remain valid: {valid_integer_status}")
            if "controlled_wechat_pay_acceptance_evidence_inconsistent" in valid_integer_status.get("paid_launch_blockers", []):
                return fail(f"consistent positive evidence must not be marked inconsistent: {valid_integer_status}")

            os.environ["JIEJING_PAID_LAUNCH_OWNER_APPROVAL_PACKET_ID"] = "test-owner-approval-record"
            owner_approved_status = build_mainland_payment_launch_status(settings, repository)
            if owner_approved_status.get("owner_approval_recorded") is not True:
                return fail(f"owner approval record must be surfaced separately: {owner_approved_status}")
            if "public_charging_owner_approval_required" in owner_approved_status.get("paid_launch_blockers", []):
                return fail(f"recorded owner approval must not retain a contradictory owner blocker: {owner_approved_status}")
            _assert_launch_status_safety(owner_approved_status)

            test_email = "mainland-launch@example.test"
            test_password = "Mainland-launch-test-2026"
            test_company_name = "Mainland Launch Contract Test"
            identity = repository.create_user_with_company(
                email=test_email,
                password=test_password,
                company_name=test_company_name,
            )
            _persist_acceptance_record(
                repository,
                identity=identity,
                variant_index=99,
                variant_name="direct-sql-self-reported",
            )
            _persist_self_reported_acceptance_without_entitlement(
                repository,
                identity=identity,
            )
            self_reported_evidence = repository.domestic_payment_acceptance_evidence()
            if self_reported_evidence.get("verified_paid_order_count") != 0:
                return fail(
                    "direct SQL/repository payment marks with self-reported verification but no "
                    f"persisted entitlement must fail closed: {self_reported_evidence}"
                )
            _create_reconciled_acceptance(
                repository,
                identity=identity,
                idempotency_key="phase1-legitimate-acceptance",
                transaction_suffix="legitimate",
            )
            repository_evidence = repository.domestic_payment_acceptance_evidence()
            if repository_evidence.get("verified_paid_order_count") != 1:
                return fail(f"the complete controlled payment domain path must count once: {repository_evidence}")

            with _strict_temporary_directory() as refund_temp_dir:
                refund_repository = SaaSRepository(Path(refund_temp_dir) / "phase1-refund-history.sqlite")
                refund_repository.initialize()
                refund_identity = refund_repository.create_user_with_company(
                    email="mainland-phase1-refund-history@example.test",
                    password="Mainland-phase1-refund-history-2026",
                    company_name="Mainland Phase1 Refund History",
                )
                refund_company = refund_identity.get("company") if isinstance(refund_identity.get("company"), dict) else {}
                refund_company_id = str(refund_company.get("company_id") or "")
                refund_order_id = _create_reconciled_acceptance(
                    refund_repository,
                    identity=refund_identity,
                    idempotency_key="phase1-refund-history",
                    transaction_suffix="refund-history",
                )
                before_refund_evidence = refund_repository.domestic_payment_acceptance_evidence()
                if before_refund_evidence.get("verified_paid_order_count") != 1:
                    return fail(f"controlled acceptance must establish one historical proof before refund: {before_refund_evidence}")
                refunded = domestic_billing.apply_verified_domestic_refund(
                    refund_repository,
                    company_id=refund_company_id,
                    order_id=refund_order_id,
                    provider_refund_id="wx-phase1-fake-refund-history",
                    amount_minor=100,
                    currency="CNY",
                    provider_verified=True,
                )
                refunded_order = refund_repository.get_domestic_billing_order(
                    company_id=refund_company_id,
                    order_id=refund_order_id,
                ) or {}
                if refunded.get("ok") is not True or refunded.get("status") != "refunded" or refunded_order.get("status") != "refunded":
                    return fail(f"provider-verified local refund must close the controlled order: {refunded}, {refunded_order}")
                if refunded.get("calls_external_payment_api") is not False or refunded.get("triggers_real_refund") is not False:
                    return fail(f"local verified-refund application must retain strict no-external-side-effect flags: {refunded}")
                after_refund_evidence = refund_repository.domestic_payment_acceptance_evidence()
                if after_refund_evidence.get("verified_paid_order_count") != 1:
                    return fail(f"a later refund must not erase historical controlled acceptance proof: {after_refund_evidence}")
                for key in (
                    "public_charging_allowed",
                    "charge_now_allowed",
                    "triggers_real_charge",
                    "calls_external_payment_api",
                    "secret_exposed",
                ):
                    if after_refund_evidence.get(key) is not False:
                        return fail(f"historical acceptance proof must keep dangerous capability false after refund: {key}: {after_refund_evidence}")
                after_refund_status = build_mainland_payment_launch_status(settings, refund_repository)
                if after_refund_status.get("controlled_acceptance_proven") is not True:
                    return fail(f"launch status must retain historical controlled acceptance after refund: {after_refund_status}")
                _assert_launch_status_safety(after_refund_status)
            acceptance_variants = (
                "wrong-amount",
                "wrong-plan",
                "wrong-contract",
                "wrong-provider-mode",
                "wrong-order-id",
                "missing-qr",
                "invalid-payment-metadata",
                "wrong-verification-source",
                "query-signature-claimed",
                "wrong-trade-type",
                "missing-entitlement-window",
                "unsafe-frontend-secret-flag",
                "appid-not-verified",
            )
            for variant_index, variant_name in enumerate(acceptance_variants, start=1):
                variant_identity = repository.create_user_with_company(
                    email=f"mainland-phase1-invalid-{variant_index}@example.test",
                    password=f"Mainland-phase1-invalid-{variant_index}-2026",
                    company_name=f"Mainland Phase1 Invalid {variant_index}",
                )
                invalid_order_id = _create_reconciled_acceptance(
                    repository,
                    identity=variant_identity,
                    idempotency_key=f"phase1-invalid-{variant_index}",
                    transaction_suffix=f"invalid-{variant_index}",
                )
                _invalidate_reconciled_acceptance(
                    repository,
                    order_id=invalid_order_id,
                    variant_name=variant_name,
                )
                invalid_evidence = repository.domestic_payment_acceptance_evidence()
                if invalid_evidence.get("verified_paid_order_count") != 1:
                    return fail(f"invalid acceptance variant must contribute zero ({variant_name}): {invalid_evidence}")
            repository_evidence = repository.domestic_payment_acceptance_evidence()
            for key, expected in {
                "contract_version": ACCEPTANCE_CONTRACT_VERSION,
                "provider": "wechat_pay_native",
                "acceptance_kind": ACCEPTANCE_KIND,
                "triggers_real_charge": False,
                "calls_external_payment_api": False,
                "public_charging_allowed": False,
                "charge_now_allowed": False,
                "secret_exposed": False,
            }.items():
                if repository_evidence.get(key) != expected or type(repository_evidence.get(key)) is not type(expected):
                    return fail(f"acceptance aggregate contract mismatch: {key}: {repository_evidence}")
            os.environ["JIEJING_WECHAT_PAY_API_V3_KEY"] = "fake-api-v3-value-must-not-leak!"
            os.environ["JIEJING_WECHAT_PAY_MERCHANT_SERIAL_NO"] = "fake-merchant-serial-must-not-leak"
            accepted_status = build_mainland_payment_launch_status(settings, repository)
            if accepted_status.get("controlled_acceptance_proven") is not True:
                return fail(f"verified controlled payment evidence must be surfaced: {accepted_status}")
            evidence = accepted_status.get("acceptance_evidence") or {}
            if evidence.get("verified_paid_order_count") != 1:
                return fail(f"controlled payment evidence count mismatch: {evidence}")
            _assert_launch_status_safety(
                accepted_status,
                forbidden_markers={
                    identity["company"]["company_id"],
                    identity["user"]["user_id"],
                    test_email,
                    test_password,
                    test_company_name,
                },
            )

            payment_module = payment_options.wechat_pay
            callable_names = {
                "create_wechat_pay_native_order_from_env",
                "query_wechat_pay_order_from_env",
                "request_wechat_pay_refund_from_env",
                "process_wechat_pay_notification_from_env",
                "process_wechat_pay_refund_notification_from_env",
                "reconcile_wechat_pay_order_query",
                "recover_paid_wechat_pay_entitlement",
            }
            original_callables = {name: getattr(payment_module, name) for name in callable_names}
            confirmation_callable_names = {
                "request_domestic_billing_refund_review",
                "execute_approved_domestic_billing_refund",
            }
            original_confirmation_callables = {
                name: getattr(domestic_billing, name) for name in confirmation_callable_names
            }
            original_contract_builder = payment_module.build_wechat_pay_native_contract
            sentinel = _CallSentinel()
            confirmation_sentinel = _CallSentinel()
            ready_contract = {
                "contract_version": "2026-07-14-wechat-pay-native-v3",
                "provider": "wechat_pay_native",
                "checkout_mode": "native_qr",
                "billing_mode": "one_time_30_day_plan",
                "merchant_credentials_backend_only": True,
                "frontend_gets_payment_secret": False,
                "secret_exposed": False,
                "configured": {key: True for key in WECHAT_CONFIGURATION_KEYS},
                "signed_callback_implemented": True,
                "signed_refund_callback_implemented": True,
                "real_order_creation_implemented": True,
                "refund_execution_confirmation_required": True,
                "provider_connection_ready": True,
                "production_environment": True,
                "owner_approval_recorded": True,
                "refund_now_allowed": True,
            }
            try:
                for name in callable_names:
                    setattr(payment_module, name, sentinel)
                for name in confirmation_callable_names:
                    setattr(domestic_billing, name, confirmation_sentinel)
                payment_module.build_wechat_pay_native_contract = lambda: dict(ready_contract)
                capability_ready = build_mainland_payment_launch_status(settings, repository)
                if capability_ready.get("mainland_payment_ready_for_owner_approval") is not True:
                    return fail(f"all code capabilities should satisfy the owner-approval readiness slice: {capability_ready}")
                if sentinel.call_count != 0 or confirmation_sentinel.call_count != 0:
                    return fail("launch status builder must not invoke create/query/refund/recovery functions")

                original_strategy_builder = payment_options.build_mainland_payment_strategy
                valid_strategy_contract = build_mainland_payment_strategy(settings)
                try:
                    invalid_strategy_fields = {
                        "contract_version": ("invalid-mainland-payment-contract", _MissingContractField),
                        "charge_now_allowed": (True, _MissingContractField),
                        "triggers_real_charge": (True, _MissingContractField),
                        "frontend_gets_payment_secret": (True, _MissingContractField),
                        "secret_exposed": (True, _MissingContractField),
                    }
                    for field, invalid_values in invalid_strategy_fields.items():
                        for invalid_value in invalid_values:
                            invalid_strategy = dict(valid_strategy_contract)
                            if invalid_value is _MissingContractField:
                                invalid_strategy.pop(field, None)
                            else:
                                invalid_strategy[field] = invalid_value
                            payment_options.build_mainland_payment_strategy = (
                                lambda _settings, contract=invalid_strategy: dict(contract)
                            )
                            invalid_strategy_status = build_mainland_payment_launch_status(settings, repository)
                            blockers = invalid_strategy_status.get("paid_launch_blockers", [])
                            if "mainland_payment_strategy_contract_invalid" not in blockers:
                                return fail(
                                    f"invalid strategy field must add the exact blocker: "
                                    f"{field}={invalid_value!r}: {invalid_strategy_status}"
                                )
                            if invalid_strategy_status.get("provider_checkout_ready") is not False:
                                return fail(f"invalid strategy must block provider readiness: {field}: {invalid_strategy_status}")
                            if invalid_strategy_status.get("mainland_payment_ready_for_owner_approval") is not False:
                                return fail(f"invalid strategy must block owner readiness: {field}: {invalid_strategy_status}")
                finally:
                    payment_options.build_mainland_payment_strategy = original_strategy_builder

                invalid_contract_fields = {
                    "contract_version": "2026-07-13-wechat-pay-native-v2",
                    "provider": "stripe",
                    "checkout_mode": "hosted_checkout",
                    "billing_mode": "recurring_subscription",
                    "merchant_credentials_backend_only": False,
                    "frontend_gets_payment_secret": True,
                    "secret_exposed": True,
                }
                for field, invalid_value in invalid_contract_fields.items():
                    invalid_contract = dict(ready_contract)
                    invalid_contract[field] = invalid_value
                    payment_module.build_wechat_pay_native_contract = lambda contract=invalid_contract: dict(contract)
                    invalid_contract_status = build_mainland_payment_launch_status(settings, repository)
                    blockers = invalid_contract_status.get("paid_launch_blockers", [])
                    if "wechat_pay_native_contract_invalid" not in blockers:
                        return fail(f"invalid WeChat contract field must add the exact blocker: {field}: {invalid_contract_status}")
                    if invalid_contract_status.get("provider_checkout_ready") is not False:
                        return fail(f"invalid WeChat contract field must block provider checkout: {field}: {invalid_contract_status}")
                    if invalid_contract_status.get("mainland_payment_ready_for_owner_approval") is not False:
                        return fail(f"invalid WeChat contract field must block owner readiness: {field}: {invalid_contract_status}")
                payment_module.build_wechat_pay_native_contract = lambda: dict(ready_contract)

                for identity_field in ("contract_version", "provider", "acceptance_kind"):
                    for invalid_value in (_MissingContractField, "invalid-identity"):
                        invalid_identity_status = build_mainland_payment_launch_status(
                            settings,
                            _AcceptanceIdentityRepository(field=identity_field, value=invalid_value),
                        )
                        blockers = invalid_identity_status.get("paid_launch_blockers", [])
                        if "controlled_wechat_pay_acceptance_identity_contract_invalid" not in blockers:
                            return fail(
                                f"invalid acceptance identity must add the exact blocker: "
                                f"{identity_field}={invalid_value!r}: {invalid_identity_status}"
                            )
                        if invalid_identity_status.get("controlled_acceptance_proven") is not False:
                            return fail(f"invalid acceptance identity must invalidate proof: {invalid_identity_status}")
                        if invalid_identity_status.get("mainland_payment_ready_for_owner_approval") is not False:
                            return fail(f"invalid acceptance identity must block owner readiness: {invalid_identity_status}")
                        if invalid_identity_status.get("provider_checkout_ready") is not True:
                            return fail(f"acceptance identity failure must not erase provider capability: {invalid_identity_status}")

                for safety_field in (
                    "public_charging_allowed",
                    "charge_now_allowed",
                    "triggers_real_charge",
                    "calls_external_payment_api",
                    "secret_exposed",
                ):
                    for unsafe_value in (_MissingContractField, True):
                        unsafe_acceptance_status = build_mainland_payment_launch_status(
                            settings,
                            _AcceptanceSafetyRepository(field=safety_field, value=unsafe_value),
                        )
                        blockers = unsafe_acceptance_status.get("paid_launch_blockers", [])
                        if "controlled_wechat_pay_acceptance_safety_contract_invalid" not in blockers:
                            return fail(
                                f"unsafe acceptance field must add the exact blocker: "
                                f"{safety_field}={unsafe_value!r}: {unsafe_acceptance_status}"
                            )
                        if unsafe_acceptance_status.get("controlled_acceptance_proven") is not False:
                            return fail(
                                f"unsafe acceptance field must invalidate controlled proof: "
                                f"{safety_field}={unsafe_value!r}: {unsafe_acceptance_status}"
                            )
                        if unsafe_acceptance_status.get("mainland_payment_ready_for_owner_approval") is not False:
                            return fail(
                                f"unsafe acceptance field must block owner readiness: "
                                f"{safety_field}={unsafe_value!r}: {unsafe_acceptance_status}"
                            )
                        if unsafe_acceptance_status.get("provider_checkout_ready") is not True:
                            return fail(
                                f"acceptance safety failure must not erase provider capability: "
                                f"{safety_field}={unsafe_value!r}: {unsafe_acceptance_status}"
                            )

                invalid_ready_slice = build_mainland_payment_launch_status(settings, _InvalidCountRepository())
                _assert_inconsistent_acceptance_fails_closed(invalid_ready_slice)
                if invalid_ready_slice.get("provider_checkout_ready") is not True:
                    return fail(f"invalid acceptance evidence test must keep all other ready conditions complete: {invalid_ready_slice}")
                zero_ready_slice = build_mainland_payment_launch_status(settings, _ZeroCountRepository())
                _assert_inconsistent_acceptance_fails_closed(zero_ready_slice)
                reverse_inconsistent_ready_slice = build_mainland_payment_launch_status(
                    settings,
                    _AcceptanceEvidenceRepository(source_flag=False, verified_count=1),
                )
                _assert_inconsistent_acceptance_fails_closed(reverse_inconsistent_ready_slice)
                if reverse_inconsistent_ready_slice.get("provider_checkout_ready") is not True:
                    return fail(f"reverse inconsistency test must keep all provider conditions ready: {reverse_inconsistent_ready_slice}")

                payment_module.create_wechat_pay_native_order_from_env = None
                order_create_missing = build_mainland_payment_launch_status(settings, repository)
                if order_create_missing.get("code_capabilities", {}).get("real_order_creation_implemented") is not False:
                    return fail(f"real-order capability must require a callable create boundary: {order_create_missing}")
                if order_create_missing.get("mainland_payment_ready_for_owner_approval") is not False:
                    return fail("owner-approval readiness must require the real-order creation boundary")
                payment_module.create_wechat_pay_native_order_from_env = sentinel

                payment_module.request_wechat_pay_refund_from_env = None
                low_level_refund_transport_missing = build_mainland_payment_launch_status(settings, repository)
                if low_level_refund_transport_missing.get("code_capabilities", {}).get("high_risk_confirmation_boundary_implemented") is not True:
                    return fail(
                        "high-risk confirmation capability must not be derived from the low-level refund transport: "
                        f"{low_level_refund_transport_missing}"
                    )
                if low_level_refund_transport_missing.get("mainland_payment_ready_for_owner_approval") is not True:
                    return fail("owner-approval readiness must remain true when only the low-level refund transport is absent")
                payment_module.request_wechat_pay_refund_from_env = sentinel

                for missing_confirmation_name in confirmation_callable_names:
                    setattr(domestic_billing, missing_confirmation_name, None)
                    refund_confirmation_missing = build_mainland_payment_launch_status(settings, repository)
                    if refund_confirmation_missing.get("code_capabilities", {}).get("high_risk_confirmation_boundary_implemented") is not False:
                        return fail(
                            "refund confirmation capability must require both callable domestic wrappers: "
                            f"{missing_confirmation_name}: {refund_confirmation_missing}"
                        )
                    if refund_confirmation_missing.get("mainland_payment_ready_for_owner_approval") is not False:
                        return fail(
                            "owner-approval readiness must require both high-risk refund confirmation wrappers: "
                            f"{missing_confirmation_name}"
                        )
                    setattr(domestic_billing, missing_confirmation_name, confirmation_sentinel)

                payment_module.reconcile_wechat_pay_order_query = None
                query_missing = build_mainland_payment_launch_status(settings, repository)
                if query_missing.get("code_capabilities", {}).get("authenticated_order_query_implemented") is not False:
                    return fail(f"query capability must be derived from callable presence: {query_missing}")
                if query_missing.get("mainland_payment_ready_for_owner_approval") is not False:
                    return fail("owner-approval readiness must require authenticated order query capability")

                payment_module.reconcile_wechat_pay_order_query = sentinel
                payment_module.recover_paid_wechat_pay_entitlement = None
                persistence_missing = build_mainland_payment_launch_status(settings, repository)
                if persistence_missing.get("code_capabilities", {}).get("quota_entitlement_persistence_implemented") is not False:
                    return fail(f"entitlement capability must be derived from callable presence: {persistence_missing}")
                if persistence_missing.get("mainland_payment_ready_for_owner_approval") is not False:
                    return fail("owner-approval readiness must require entitlement persistence capability")

                payment_module.recover_paid_wechat_pay_entitlement = sentinel
                payment_module.process_wechat_pay_notification_from_env = None
                payment_callback_missing = build_mainland_payment_launch_status(settings, repository)
                if payment_callback_missing.get("code_capabilities", {}).get("signed_payment_callback_implemented") is not False:
                    return fail(f"signed payment callback capability must require a callable boundary: {payment_callback_missing}")
                if payment_callback_missing.get("mainland_payment_ready_for_owner_approval") is not False:
                    return fail("owner-approval readiness must require the signed payment callback boundary")

                payment_module.process_wechat_pay_notification_from_env = sentinel
                payment_module.process_wechat_pay_refund_notification_from_env = None
                refund_callback_missing = build_mainland_payment_launch_status(settings, repository)
                if refund_callback_missing.get("code_capabilities", {}).get("signed_refund_callback_implemented") is not False:
                    return fail(f"signed refund callback capability must require a callable boundary: {refund_callback_missing}")
                if refund_callback_missing.get("mainland_payment_ready_for_owner_approval") is not False:
                    return fail("owner-approval readiness must require the signed refund callback boundary")
            finally:
                payment_module.build_wechat_pay_native_contract = original_contract_builder
                for name, value in original_callables.items():
                    setattr(payment_module, name, value)
                for name, value in original_confirmation_callables.items():
                    setattr(domestic_billing, name, value)

        print("PASS jiejing_mainland_payment_strategy")
        return 0
    finally:
        try:
            _restore_env(previous)
        finally:
            gc.collect()
            temp_context.cleanup()


def _assert_no_secret_material(payload: object) -> None:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    forbidden = ["sk_live", "rk_live", "whsec_", "client_secret", "refresh_token", "access_token_value"]
    leaked = [item for item in forbidden if item in text]
    if leaked:
        raise AssertionError(f"secret-like material leaked in public payment payload: {leaked}")


def _assert_no_identity_or_bank_material(payload: object) -> None:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True).lower()
    forbidden = [
        "id_card_number",
        "identity_number",
        "bank_account_number",
        "settlement_card_number",
        "身份证号码",
        "银行卡号",
    ]
    leaked = [item for item in forbidden if item in text]
    if leaked:
        raise AssertionError(f"identity or bank material leaked in public application packet: {leaked}")


def _assert_no_internal_payment_copy(payload: object) -> None:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    forbidden = [
        "大陆收款方式",
        "大陆用户优先",
        "个体工商户",
        "个体户",
        "主体资料",
        "聚合收单",
        "个人码",
        "个人收款码",
        "原散户",
        "散户",
    ]
    leaked = [item for item in forbidden if item in text]
    if leaked:
        raise AssertionError(f"internal payment route copy leaked in payment strategy payload: {leaked}")


class _CallSentinel:
    def __init__(self) -> None:
        self.call_count = 0

    def __call__(self, *args: object, **kwargs: object) -> object:
        self.call_count += 1
        raise AssertionError("payment transport/capability function was invoked while building launch status")


class _ExplodingEvidenceRepository:
    def domestic_payment_acceptance_evidence(self) -> dict[str, object]:
        raise RuntimeError("sk_live_exception-must-not-leak")


class _InvalidCountRepository:
    def domestic_payment_acceptance_evidence(self) -> dict[str, object]:
        return _acceptance_evidence(verified_paid_order_count="not-a-number")


class _ZeroCountRepository:
    def domestic_payment_acceptance_evidence(self) -> dict[str, object]:
        return _acceptance_evidence(verified_paid_order_count=0)


class _AcceptanceEvidenceRepository:
    def __init__(self, *, source_flag: bool, verified_count: object) -> None:
        self.source_flag = source_flag
        self.verified_count = verified_count

    def domestic_payment_acceptance_evidence(self) -> dict[str, object]:
        return _acceptance_evidence(
            controlled_acceptance_proven=self.source_flag,
            verified_paid_order_count=self.verified_count,
        )


class _MissingContractField:
    pass


class _AcceptanceSafetyRepository:
    def __init__(self, *, field: str, value: object) -> None:
        self.field = field
        self.value = value

    def domestic_payment_acceptance_evidence(self) -> dict[str, object]:
        evidence = _acceptance_evidence()
        if self.value is _MissingContractField:
            evidence.pop(self.field)
        else:
            evidence[self.field] = self.value
        return evidence


class _AcceptanceIdentityRepository:
    def __init__(self, *, field: str, value: object) -> None:
        self.field = field
        self.value = value

    def domestic_payment_acceptance_evidence(self) -> dict[str, object]:
        evidence = _acceptance_evidence()
        if self.value is _MissingContractField:
            evidence.pop(self.field)
        else:
            evidence[self.field] = self.value
        return evidence


def _acceptance_evidence(
    *,
    controlled_acceptance_proven: bool = True,
    verified_paid_order_count: object = 1,
) -> dict[str, object]:
    return {
        "contract_version": ACCEPTANCE_CONTRACT_VERSION,
        "provider": "wechat_pay_native",
        "acceptance_kind": ACCEPTANCE_KIND,
        "controlled_acceptance_proven": controlled_acceptance_proven,
        "verified_paid_order_count": verified_paid_order_count,
        "public_charging_allowed": False,
        "charge_now_allowed": False,
        "triggers_real_charge": False,
        "calls_external_payment_api": False,
        "secret_exposed": False,
    }


def _persist_acceptance_record(
    repository: SaaSRepository,
    *,
    identity: dict[str, object],
    variant_index: int,
    variant_name: str,
    amount_minor: int = 100,
    plan_key: str = "starter",
    contract_version: str = "2026-07-13-wechat-pay-live-acceptance-v1",
    provider_mode: str = "owner_approved_single_live_acceptance",
    order_id: str = "",
    attach_checkout: bool = True,
    payment_overrides: dict[str, object] | None = None,
) -> None:
    company = identity.get("company") if isinstance(identity.get("company"), dict) else {}
    user = identity.get("user") if isinstance(identity.get("user"), dict) else {}
    controlled_order_id = order_id or f"JJLIVE{variant_index:026x}"
    repository.create_domestic_billing_order_record(
        order_id=controlled_order_id,
        company_id=str(company.get("company_id") or ""),
        user_id=str(user.get("user_id") or ""),
        provider="wechat_pay_native",
        plan_key=plan_key,
        amount_minor=amount_minor,
        currency="CNY",
        duration_days=30,
        status="pending_payment",
        idempotency_key_hash=f"{variant_index:064x}",
        order={
            "contract_version": contract_version,
            "live_acceptance_test": True,
            "provider_mode": provider_mode,
            "provider_order_created": False,
            "payable_qr_created": False,
            "calls_external_payment_api": False,
            "triggers_real_charge": False,
            "bank_details_persisted": False,
            "payment_secret_persisted": False,
            "frontend_gets_payment_secret": False,
            "secret_exposed": False,
        },
    )
    if attach_checkout:
        repository.attach_domestic_billing_checkout(
            company_id=str(company.get("company_id") or ""),
            order_id=controlled_order_id,
            code_url=f"weixin://wxpay/bizpayurl?pr={variant_name}",
        )
    payment: dict[str, object] = {
        "provider_transaction_present": True,
        "amount_minor": 100,
        "currency": "CNY",
        "purchase_type": "subscription",
        "signature_verified": True,
        "appid_verified": True,
        "mchid_verified": True,
        "amount_verified": True,
    }
    payment.update(payment_overrides or {})
    _write_strict_acceptance_payment_fixture(
        repository,
        order_id=controlled_order_id,
        provider_order_id=f"wx-{variant_index:026x}",
        paid_at="2026-07-13T00:00:00+00:00",
        payment=payment,
        payable_qr_created=attach_checkout,
    )


def _write_strict_acceptance_payment_fixture(
    repository: SaaSRepository,
    *,
    order_id: str,
    provider_order_id: str,
    paid_at: str,
    payment: dict[str, object],
    payable_qr_created: bool,
) -> None:
    with repository._connect() as conn:
        row = conn.execute("select order_json from billing_orders where order_id = ?", (order_id,)).fetchone()
        if not row:
            raise AssertionError(f"acceptance fixture order missing: {order_id}")
        payload = json.loads(row["order_json"])
        checkout = payload.get("checkout") if isinstance(payload.get("checkout"), dict) else {}
        checkout.pop("code_url", None)
        if checkout:
            checkout["payable_uri_removed"] = True
            payload["checkout"] = checkout
        payload.update(
            {
                "provider_order_created": payable_qr_created,
                "payable_qr_created": payable_qr_created,
                "calls_external_payment_api": False,
                "triggers_real_charge": False,
                "bank_details_persisted": False,
                "payment_secret_persisted": False,
                "frontend_gets_payment_secret": False,
                "secret_exposed": False,
                "raw_callback_persisted": False,
                "raw_signature_persisted": False,
                "payment": payment,
            }
        )
        updated = conn.execute(
            """
            update billing_orders
            set provider_order_id = ?, status = 'paid', paid_at = ?, order_json = ?
            where order_id = ? and status = 'pending_payment'
            """,
            (provider_order_id, paid_at, json.dumps(payload, ensure_ascii=False), order_id),
        ).rowcount
        if updated != 1:
            raise AssertionError(f"acceptance fixture payment update failed: {order_id}")


def _persist_self_reported_acceptance_without_entitlement(
    repository: SaaSRepository,
    *,
    identity: dict[str, object],
) -> None:
    company = identity.get("company") if isinstance(identity.get("company"), dict) else {}
    user = identity.get("user") if isinstance(identity.get("user"), dict) else {}
    company_id = str(company.get("company_id") or "")
    order_id = f"JJLIVE{'f' * 26}"
    repository.create_domestic_billing_order_record(
        order_id=order_id,
        company_id=company_id,
        user_id=str(user.get("user_id") or ""),
        provider="wechat_pay_native",
        plan_key="starter",
        amount_minor=100,
        currency="CNY",
        duration_days=30,
        status="pending_payment",
        idempotency_key_hash="f" * 64,
        order={
            "contract_version": "2026-07-13-wechat-pay-live-acceptance-v1",
            "live_acceptance_test": True,
            "provider_mode": "owner_approved_single_live_acceptance",
            "provider_order_created": False,
            "payable_qr_created": False,
            "calls_external_payment_api": False,
            "triggers_real_charge": False,
            "bank_details_persisted": False,
            "payment_secret_persisted": False,
            "frontend_gets_payment_secret": False,
            "secret_exposed": False,
        },
    )
    repository.attach_domestic_billing_checkout(
        company_id=company_id,
        order_id=order_id,
        code_url="weixin://wxpay/bizpayurl?pr=self-reported-without-entitlement",
    )
    marked = repository.mark_domestic_billing_order_paid(
        company_id=company_id,
        order_id=order_id,
        provider_order_id="wx-self-reported-without-entitlement",
        paid_at="2026-07-13T00:00:00+00:00",
        payment={
            "provider_transaction_present": True,
            "trade_type": "NATIVE",
            "amount_minor": 100,
            "currency": "CNY",
            "purchase_type": "subscription",
            "signature_verified": True,
            "verification_source": "signed_callback",
            "appid_verified": True,
            "mchid_verified": True,
            "amount_verified": True,
            "entitlement_active_from": "2026-07-13T00:00:00+00:00",
            "entitlement_active_until": "2026-08-12T00:00:00+00:00",
        },
    )
    if not marked or marked.get("status") != "paid":
        raise AssertionError(f"self-reported acceptance fixture payment mark failed: {marked}")


def _create_reconciled_acceptance(
    repository: SaaSRepository,
    *,
    identity: dict[str, object],
    idempotency_key: str,
    transaction_suffix: str,
) -> str:
    company = identity.get("company") if isinstance(identity.get("company"), dict) else {}
    user = identity.get("user") if isinstance(identity.get("user"), dict) else {}
    company_id = str(company.get("company_id") or "")
    account_email = str(user.get("email") or "")
    provider_create_calls: list[str] = []

    def fake_provider_create(*, order: dict[str, object]) -> dict[str, object]:
        provider_create_calls.append(str(order.get("order_id") or ""))
        return {
            "ok": True,
            "status": "payable_order_created",
            "order_id": str(order.get("order_id") or ""),
            "code_url": f"weixin://wxpay/bizpayurl?pr={transaction_suffix}",
            "amount_minor": int(order.get("amount_minor") or 0),
            "currency": str(order.get("currency") or ""),
            "calls_external_payment_api": False,
            "triggers_real_charge": False,
            "secret_exposed": False,
        }

    created = domestic_billing.create_controlled_wechat_pay_acceptance_order(
        repository,
        account_email=account_email,
        approval_phrase=domestic_billing.CONTROLLED_WECHAT_PAY_ACCEPTANCE_APPROVAL,
        idempotency_key=idempotency_key,
        provider_create=fake_provider_create,
    )
    order_id = str(created.get("order_id") or "")
    if created.get("ok") is not True or created.get("status") != "payable_order_created":
        raise AssertionError(f"controlled acceptance checkout creation failed: {created}")
    if provider_create_calls != [order_id]:
        raise AssertionError(f"fake provider create must execute exactly once: {provider_create_calls}")
    reconciled = payment_options.wechat_pay.reconcile_wechat_pay_order_query(
        repository,
        company_id=company_id,
        order_id=order_id,
        provider_response={
            "appid": "wx-phase1-local-app",
            "mchid": "1900000109",
            "out_trade_no": order_id,
            "transaction_id": f"wx-phase1-{transaction_suffix}",
            "trade_type": "NATIVE",
            "trade_state": "SUCCESS",
            "success_time": "2026-07-13T00:00:00+08:00",
            "amount": {"total": 100, "currency": "CNY"},
        },
        query_authenticated=True,
        expected_appid="wx-phase1-local-app",
        expected_mchid="1900000109",
    )
    if reconciled.get("ok") is not True or reconciled.get("entitlement_active") is not True:
        raise AssertionError(f"authenticated acceptance reconciliation failed: {reconciled}")
    stored = repository.get_domestic_billing_order(company_id=company_id, order_id=order_id) or {}
    payload = stored.get("order") if isinstance(stored.get("order"), dict) else {}
    payment = payload.get("payment") if isinstance(payload.get("payment"), dict) else {}
    checkout = payload.get("checkout") if isinstance(payload.get("checkout"), dict) else {}
    if payload.get("frontend_gets_payment_secret") is not False:
        raise AssertionError(f"safe frontend payment-secret flag must persist as strict false: {payload}")
    if payload.get("payable_qr_created") is not False or checkout.get("payable_uri_removed") is not True:
        raise AssertionError(f"paid acceptance must remove the payable QR URI: {payload}")
    if payment.get("verification_source") != "authenticated_order_query" or payment.get("signature_verified") is not False:
        raise AssertionError(f"authenticated query provenance must be persisted exactly: {payment}")
    subscription = repository.get_billing_subscription(company_id=company_id) or {}
    if {
        "provider": subscription.get("provider"),
        "provider_subscription_id": subscription.get("provider_subscription_id"),
        "plan_key": subscription.get("plan_key"),
        "status": subscription.get("status"),
        "entitlement_active": subscription.get("entitlement_active"),
    } != {
        "provider": "wechat_pay_native",
        "provider_subscription_id": order_id,
        "plan_key": "starter",
        "status": "active",
        "entitlement_active": True,
    }:
        raise AssertionError(f"controlled acceptance entitlement was not persisted: {subscription}")
    return order_id


def _invalidate_reconciled_acceptance(
    repository: SaaSRepository,
    *,
    order_id: str,
    variant_name: str,
) -> None:
    with repository._connect() as conn:
        row = conn.execute("select order_json from billing_orders where order_id = ?", (order_id,)).fetchone()
        if not row:
            raise AssertionError(f"reconciled acceptance fixture missing: {order_id}")
        payload = json.loads(row["order_json"])
        payment = payload.get("payment") if isinstance(payload.get("payment"), dict) else {}
        if variant_name == "wrong-amount":
            conn.execute("update billing_orders set amount_minor = ? where order_id = ?", (101, order_id))
        elif variant_name == "wrong-plan":
            conn.execute("update billing_orders set plan_key = ? where order_id = ?", ("operator", order_id))
        elif variant_name == "wrong-contract":
            payload["contract_version"] = "2026-07-13-wechat-pay-live-acceptance-v0"
        elif variant_name == "wrong-provider-mode":
            payload["provider_mode"] = "public_checkout"
        elif variant_name == "wrong-order-id":
            conn.execute(
                "update billing_orders set order_id = ? where order_id = ?",
                (f"JJLIVE-invalid-{order_id[-8:]}", order_id),
            )
        elif variant_name == "missing-qr":
            payload["provider_order_created"] = False
        elif variant_name == "invalid-payment-metadata":
            payment["provider_transaction_present"] = False
        elif variant_name == "wrong-verification-source":
            payment["verification_source"] = "self_reported"
        elif variant_name == "query-signature-claimed":
            payment["signature_verified"] = True
        elif variant_name == "wrong-trade-type":
            payment["trade_type"] = "JSAPI"
        elif variant_name == "missing-entitlement-window":
            payment["entitlement_active_until"] = ""
        elif variant_name == "unsafe-frontend-secret-flag":
            payload["frontend_gets_payment_secret"] = True
        elif variant_name == "appid-not-verified":
            payment["appid_verified"] = False
        else:
            raise AssertionError(f"unsupported acceptance invalidation: {variant_name}")
        payload["payment"] = payment
        conn.execute(
            "update billing_orders set order_json = ? where order_id = ?",
            (json.dumps(payload, ensure_ascii=False), order_id),
        )


@contextmanager
def _strict_temporary_directory():
    with tempfile.TemporaryDirectory() as temp_dir:
        try:
            yield temp_dir
        finally:
            gc.collect()


def _raise_status_exception(*args: object, **kwargs: object) -> object:
    raise RuntimeError("sk_live_exception-must-not-leak")


def _assert_unavailable_fallback(payload: object) -> None:
    if not isinstance(payload, dict):
        raise AssertionError("unavailable payment status fallback must be a dictionary")
    if payload.get("status") != "blocked":
        raise AssertionError(f"unavailable payment status must be blocked: {payload}")
    if payload.get("paid_launch_blockers") != ["mainland_payment_status_unavailable"]:
        raise AssertionError(f"unavailable payment status blocker must be exact: {payload}")
    configuration = payload.get("configuration") if isinstance(payload.get("configuration"), dict) else {}
    if configuration.get("required_count") != 9 or configuration.get("completed_count") != 0 or configuration.get("complete") is not False:
        raise AssertionError(f"unavailable payment status must retain the fixed configuration denominator: {payload}")
    _assert_launch_status_safety(payload, forbidden_markers={"sk_live_exception-must-not-leak"})


def _assert_inconsistent_acceptance_fails_closed(payload: object) -> None:
    if not isinstance(payload, dict):
        raise AssertionError("inconsistent payment evidence result must be a dictionary")
    if payload.get("controlled_acceptance_proven") is not False:
        raise AssertionError(f"flag-only payment evidence must fail closed: {payload}")
    if payload.get("mainland_payment_ready_for_owner_approval") is not False:
        raise AssertionError(f"flag-only payment evidence must block owner readiness: {payload}")
    blockers = payload.get("paid_launch_blockers") if isinstance(payload.get("paid_launch_blockers"), list) else []
    if "controlled_wechat_pay_acceptance_evidence_inconsistent" not in blockers:
        raise AssertionError(f"inconsistent payment evidence must have an exact blocker: {payload}")
    if "controlled_wechat_pay_acceptance_not_proven" in blockers:
        raise AssertionError(f"inconsistent evidence must not emit a duplicate not-proven blocker: {payload}")
    _assert_launch_status_safety(payload)


def _assert_launch_status_safety(payload: object, *, forbidden_markers: set[str] | None = None) -> None:
    if not isinstance(payload, dict):
        raise AssertionError("mainland payment launch status must be a dictionary")
    for key in {
        "public_charging_allowed",
        "charge_now_allowed",
        "triggers_real_charge",
        "triggers_real_refund",
        "calls_external_payment_api",
        "calls_stripe_api",
        "real_platform_writes_enabled",
        "frontend_gets_payment_secret",
        "secret_exposed",
    }:
        if payload.get(key) is not False:
            raise AssertionError(f"mainland launch safety field must remain false: {key}: {payload.get(key)!r}")
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True).lower()
    forbidden = [
        "sensitive-order-id-must-not-leak",
        "sensitive-provider-id-must-not-leak",
        "mainland launch contract test",
        "raw_callback",
        "must-not-leak",
        "client_secret",
        "refresh_token",
    ]
    forbidden.extend(str(item).strip().lower() for item in (forbidden_markers or set()) if str(item).strip())
    leaked = [item for item in forbidden if item in serialized]
    if leaked:
        raise AssertionError(f"mainland payment launch status leaked private material: {leaked}")


def _set_env() -> dict[str, str | None]:
    keys = [
        "JIEJING_SAAS_ENV",
        "JIEJING_PRIMARY_CUSTOMER_REGION",
        "JIEJING_DOMESTIC_PAYMENT_PROVIDER",
        "JIEJING_DOMESTIC_PAYMENT_ADAPTER_ENABLED",
        "JIEJING_DOMESTIC_PAYMENT_WEBHOOK_CONFIGURED",
        "JIEJING_DOMESTIC_PAYMENT_LIVE_CUTOVER_APPROVED",
        "JIEJING_MANUAL_QR_COLLECTION_ENABLED",
        "JIEJING_PAYMENT_MERCHANT_ENTITY_READY",
        "JIEJING_MAINLAND_PAYMENT_ICP_READY",
        "JIEJING_PUBLIC_APP_URL",
        "JIEJING_PUBLIC_HOSTING_REGION",
        "JIEJING_ALIPAY_APP_ID",
        "JIEJING_ALIPAY_PRIVATE_KEY_REF",
        "JIEJING_ALIPAY_PUBLIC_CERT_REF",
        "JIEJING_BILLING_PROVIDER",
        "JIEJING_WECHAT_PAY_APP_ID",
        "JIEJING_WECHAT_PAY_MCH_ID",
        "JIEJING_WECHAT_PAY_MERCHANT_SERIAL_NO",
        "JIEJING_WECHAT_PAY_MERCHANT_PRIVATE_KEY_PEM",
        "JIEJING_WECHAT_PAY_MERCHANT_PRIVATE_KEY_PEM_B64",
        "JIEJING_WECHAT_PAY_API_V3_KEY",
        "JIEJING_WECHAT_PAY_PUBLIC_KEY_ID",
        "JIEJING_WECHAT_PAY_PUBLIC_KEY_PEM",
        "JIEJING_WECHAT_PAY_PUBLIC_KEY_PEM_B64",
        "JIEJING_WECHAT_PAY_PLATFORM_CERTIFICATE_PEM",
        "JIEJING_WECHAT_PAY_PLATFORM_CERTIFICATE_PEM_B64",
        "JIEJING_WECHAT_PAY_PLATFORM_SERIAL_NO",
        "JIEJING_WECHAT_PAY_NOTIFY_URL",
        "JIEJING_WECHAT_PAY_REFUND_NOTIFY_URL",
        "JIEJING_WECHAT_PAY_LIVE_API_ENABLED",
        "JIEJING_WECHAT_PAY_CHARGE_ALLOWED",
        "JIEJING_WECHAT_PAY_REFUND_ALLOWED",
        "JIEJING_PAID_LAUNCH_OWNER_APPROVAL_PACKET_ID",
    ]
    previous = {key: os.environ.get(key) for key in keys}
    for key in keys:
        os.environ.pop(key, None)
    os.environ["JIEJING_SAAS_ENV"] = "staging"
    os.environ["JIEJING_PRIMARY_CUSTOMER_REGION"] = "mainland_china"
    return previous


def _restore_env(previous: dict[str, str | None]) -> None:
    for key, value in previous.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


if __name__ == "__main__":
    raise SystemExit(main())
