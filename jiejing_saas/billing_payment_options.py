"""Payment route strategy for Jiejing mainland-first billing.

This module is intentionally provider-neutral. It reports which collection
route should be pursued next without exposing API keys, payment secrets, or
creating a charge.
"""

from __future__ import annotations

import os
from typing import Any

from .config import SaaSSettings


MAINLAND_PAYMENT_CONTRACT_VERSION = "2026-06-29-mainland-payment-strategy"
FORMAL_PAYMENT_ARCHITECTURE_VERSION = "2026-06-29-formal-payment-collection-architecture"
MERCHANT_APPLICATION_PACKET_VERSION = "2026-07-01-merchant-payment-application-packet"


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
            "recommended_next_step": "prepare_individual_business_or_company_merchant_kyc_for_alipay_wechat_unionpay_or_acquirer",
            "reason": "regulated payment channels normally require merchant onboarding, settlement identity, risk review, and webhook/order-query credentials",
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
    service_docs_ready = _env_bool("JIEJING_PAYMENT_REVIEW_SERVICE_DOCS_READY", True)
    pricing_terms_ready = _env_bool("JIEJING_PAYMENT_REVIEW_PRICING_TERMS_READY", True)
    support_contact_ready = _env_bool("JIEJING_PAYMENT_REVIEW_SUPPORT_CONTACT_READY", False)
    refund_policy_ready = _env_bool("JIEJING_PAYMENT_REVIEW_REFUND_POLICY_READY", True)
    callback_url_ready = _env_bool("JIEJING_PAYMENT_REVIEW_CALLBACK_URL_READY", bool(public_app_url))
    checklist = [
        {
            "key": "merchant_subject",
            "label": "个体工商户或公司主体",
            "status": "ready" if merchant_entity_ready else "blocked",
            "review_use": "用于微信、支付宝、云闪付或聚合收单的商户实名和结算主体审核",
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
        "recommended_packet_use": "use_after_individual_business_or_company_registration_before_formal_payment_provider_application",
        "review_urls": {
            "terms": f"{public_app_url}/terms.html",
            "privacy": f"{public_app_url}/privacy.html",
            "risk_disclosure": f"{public_app_url}/risk-disclosure.html",
            "pricing": public_app_url,
        },
        "provider_callback_urls": {
            "success_url": f"{public_app_url}/billing/success",
            "cancel_url": f"{public_app_url}/billing/cancel",
            "webhook_url": f"{public_app_url}/billing/webhook",
        },
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


def _domestic_lanes(selected_provider: str) -> list[dict[str, Any]]:
    return [
        _domestic_lane(
            key="wechat_pay_native",
            label="WeChat Pay Native / JSAPI",
            selected_provider=selected_provider,
            aliases={"wechat_pay", "wechat_pay_native", "weixin_pay"},
            required_env=[
                "JIEJING_WECHAT_PAY_MCH_ID",
                "JIEJING_WECHAT_PAY_APP_ID",
                "JIEJING_WECHAT_PAY_API_V3_KEY",
                "JIEJING_WECHAT_PAY_CERT_SERIAL_NO",
            ],
            fit="best_for_mainland_wechat_users_and_qr_checkout",
        ),
        _domestic_lane(
            key="alipay_web",
            label="Alipay web / face-to-face",
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
            label="UnionPay / Cloud QuickPass",
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
            label="LianLian aggregate acquiring",
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
            label="Airwallex China aggregate acquiring",
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
    fit: str,
) -> dict[str, Any]:
    configured = {name: bool(os.environ.get(name, "").strip()) for name in required_env}
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
            "label": "Individual business or company license",
            "status": "ready" if merchant_entity_ready else "in_progress",
            "why": "formal WeChat, Alipay, UnionPay, or acquirer onboarding needs a real settlement subject",
        },
        {
            "key": "operator_identity_and_bank",
            "label": "Operator identity and settlement bank account",
            "status": "ready" if merchant_entity_ready else "blocked",
            "why": "provider KYC, payout, and dispute handling must map to the same operator or entity",
        },
        {
            "key": "service_docs_and_contact",
            "label": "Service agreement, privacy policy, and customer contact",
            "status": "designed",
            "why": "payment product review needs a clear service page, refund path, and support contact",
        },
        {
            "key": "domain_subject_alignment",
            "label": "Domain, ICP if required, and payment subject alignment",
            "status": "ready" if mainland_icp_ready else "blocked",
            "why": "mainland payment review may check that website, callback domain, and merchant subject are consistent",
        },
        {
            "key": "signed_callback_and_order_query",
            "label": "Signed callback and order query credentials",
            "status": "ready" if domestic_webhook_configured and domestic_provider_ready else "blocked",
            "why": "Jiejing can only auto-grant quota from signed provider evidence, not from a static personal QR image",
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
            "finish_individual_business_registration_or_company_setup",
            "apply_wechat_alipay_unionpay_or_acquirer_merchant_account",
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
            "label": "Merchant entity and product review",
            "status": "ready" if merchant_entity_ready else "blocked",
            "owner": "operator",
            "reason": "formal wallet/acquirer onboarding needs a real settlement subject and product review",
        },
        {
            "key": "domain_icp_subject_alignment",
            "label": "Domain, ICP, and merchant subject alignment",
            "status": "ready" if mainland_icp_ready else "blocked",
            "owner": "operator",
            "reason": "mainland web payment review commonly checks ICP and merchant subject consistency or consent proof",
        },
        {
            "key": "create_order",
            "label": "Backend order creation",
            "status": "ready" if domestic_adapter_enabled else "blocked",
            "owner": "backend",
            "reason": "Jiejing must create an internal order before sending a user to payment",
        },
        {
            "key": "provider_checkout",
            "label": "Provider checkout or QR order",
            "status": "ready" if domestic_provider_ready and domestic_adapter_enabled else "blocked",
            "owner": "backend",
            "reason": "checkout must come from a merchant provider account, not a static personal QR code",
        },
        {
            "key": "signed_webhook_and_order_query",
            "label": "Signed callback and order query",
            "status": "ready" if domestic_webhook_configured else "blocked",
            "owner": "backend",
            "reason": "subscription and quota changes must be driven by verifiable provider evidence",
        },
        {
            "key": "subscription_quota_audit",
            "label": "Subscription, quota, invoice, and audit update",
            "status": "blocked" if manual_qr_enabled else "designed",
            "owner": "backend",
            "reason": "manual QR can only be reconciled by the owner and cannot automatically renew or stop quota",
        },
        {
            "key": "owner_live_cutover",
            "label": "Owner-approved live cutover",
            "status": "ready" if domestic_live_cutover_approved else "blocked",
            "owner": "owner",
            "reason": "real-money collection must not be enabled by code deployment alone",
        },
    ]
    return {
        "contract_version": FORMAL_PAYMENT_ARCHITECTURE_VERSION,
        "current_stage": "private_beta_manual_collection" if manual_qr_enabled else "formal_provider_not_connected",
        "recommended_now": "use_personal_alipay_qr_only_for_small_private_beta_manual_reconciliation",
        "formal_target": "licensed_domestic_wallet_or_aggregate_acquirer_with_signed_callbacks",
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
            "after_company_or_individual_business_entity_is_ready_prepare_cn_or_pay_subdomain_for_mainland_payment_review",
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
