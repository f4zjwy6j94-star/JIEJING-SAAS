#!/usr/bin/env python3
"""Regression for mainland-first billing strategy.

This deliberately does not test QR login. Jiejing is keeping email login as the
current account path and solving collection through domestic payment rails first.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.billing_payment_options import build_mainland_payment_strategy  # noqa: E402
from jiejing_saas.config import SaaSSettings  # noqa: E402


OUT = ROOT / "output" / "jiejing-mainland-payment-strategy"


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    previous = _set_env()
    try:
        settings = SaaSSettings.from_env(
            db_path=OUT / "saas.sqlite",
            runtime_db_path=OUT / "runtime.sqlite",
            output_root=OUT,
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

        print("PASS jiejing_mainland_payment_strategy")
        return 0
    finally:
        _restore_env(previous)


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
