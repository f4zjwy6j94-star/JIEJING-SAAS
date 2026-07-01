"""Sanitized expert feasibility review for Jiejing.

The packet is deliberately read-only. It summarizes whether the SaaS is viable
for private beta and what blocks public paid launch; it never starts OAuth,
Checkout, provider calls, platform writes, or secret export.
"""

from __future__ import annotations

from typing import Any

from jiejing_runtime.media_capability_router import build_media_capability_router

from .platform_authorization_strategy import build_platform_authorization_strategy


FEASIBILITY_REVIEW_VERSION = "2026-07-01-expert-feasibility-review-v1"


def build_feasibility_review(
    *,
    readiness: dict[str, Any],
    launch_gate: dict[str, Any],
    billing: dict[str, Any],
    billing_cutover: dict[str, Any],
    backup: dict[str, Any],
    operational: dict[str, Any],
    edge: dict[str, Any],
    monitoring: dict[str, Any],
    evidence: dict[str, Any],
    post_publish: dict[str, Any],
    test_data_governance: dict[str, Any],
) -> dict[str, Any]:
    """Return a cross-functional feasibility packet without sensitive values."""

    groups = _by_key(launch_gate.get("groups"))
    provider = billing.get("provider") if isinstance(billing.get("provider"), dict) else {}
    trust_packet = (
        billing.get("customer_billing_trust_packet")
        if isinstance(billing.get("customer_billing_trust_packet"), dict)
        else {}
    )
    edge_summary = edge.get("summary") if isinstance(edge.get("summary"), dict) else {}
    operational_ready = operational.get("status") == "ready"
    beta_ready = bool(readiness.get("beta_ready"))
    production_ready = bool(readiness.get("production_ready"))
    can_accept_real_customers = bool(readiness.get("can_accept_real_customers"))
    paid_launch_ready = bool(launch_gate.get("paid_commercial_launch_ready"))
    refresh_success_count = _as_int(evidence.get("ebay_token_refresh_success_count"))
    official_packet_ready = _official_packet_ready(evidence)
    authorization_strategy = build_platform_authorization_strategy()
    media_router = build_media_capability_router(preferred_model_provider="deepseek")
    expert_reviews = [
        _expert_review(
            "product_market_fit",
            "eBay-first product and market",
            "attention_required" if beta_ready and official_packet_ready else "blocked",
            "Private beta is feasible for controlled merchant workflow learning; public growth claims still need clean eBay account proof and real willingness-to-pay evidence.",
            evidence={
                "beta_ready": beta_ready,
                "official_packet_ready": official_packet_ready,
                "latest_ebay_packet_status": evidence.get("latest_ebay_packet_status") or "",
                "present_resource_key_count": len(evidence.get("latest_ebay_packet_present_resource_keys") or []),
                "post_publish_status": post_publish.get("status") or "unknown",
            },
            blockers=[
                *([] if _group_ready(groups, "new_ebay_account_low_risk_smoke") else ["clean_new_ebay_account_low_risk_smoke_missing"]),
                *([] if refresh_success_count > 0 else ["backend_refresh_success_proof_missing"]),
                "merchant_willingness_to_pay_and_unit_economics_unproven",
            ],
            next_actions=[
                "Keep product direction eBay-first AI CEO SaaS, not generic ERP or agent marketplace.",
                "Run clean-new-account low-risk smoke only after the owner provides a new eBay account.",
                "Collect merchant pricing, time-saved and conversion evidence before any paid growth claim.",
            ],
        ),
        _expert_review(
            "billing_subscription_revenue",
            "Billing, subscription and revenue",
            "ready" if bool(billing.get("billing_ready_for_paid_launch")) and billing_cutover.get("status") == "ready_for_owner_approval" else "blocked",
            "The architecture matches SaaS billing best practice, but current staging is not commercially chargeable until live merchant provider, Prices, Checkout, Portal and signed webhooks are proven.",
            evidence={
                "provider": provider.get("selected") or "not_selected",
                "billing_ready_for_paid_launch": bool(billing.get("billing_ready_for_paid_launch")),
                "billing_cutover_status": billing_cutover.get("status") or "unknown",
                "customer_trust_packet_ready": bool(trust_packet.get("ready_for_paid_customer_display")),
                "quota_enforcement_enabled": bool((billing.get("quota_contract") or {}).get("enabled")) if isinstance(billing.get("quota_contract"), dict) else False,
            },
            blockers=list(billing.get("paid_launch_blockers") or billing.get("blockers") or ["billing_live_provider_evidence_missing"]),
            next_actions=[
                "Use live Products/Prices, subscription Checkout, Customer Portal and signed webhook before paid launch.",
                "Keep personal QR/manual beta payment as manual activation only.",
                "Keep quota entitlement backend-driven; browser cannot grant paid access.",
            ],
        ),
        _expert_review(
            "architecture_operations",
            "Architecture and operations",
            "attention_required" if operational_ready else "blocked",
            "The public staging runtime is operational, but paid SaaS scale still needs managed Postgres/Redis probes, restore drill evidence and production runbooks.",
            evidence={
                "operational_status": operational.get("status") or "unknown",
                "worker_ready": bool(((operational.get("worker_runtime") or {}) if isinstance(operational.get("worker_runtime"), dict) else {}).get("ready")),
                "backup_ready_for_paid_launch": bool(backup.get("backup_ready_for_paid_launch")),
                "monitoring_status": monitoring.get("status") or "unknown",
                "test_data_governance_status": test_data_governance.get("status") or "unknown",
            },
            blockers=[
                *list(backup.get("blockers") or []),
                *([] if _group_ready(groups, "managed_database_queue") else ["managed_postgres_redis_cutover_missing"]),
                *([] if _group_ready(groups, "monitoring_alerting") else ["production_monitoring_alerts_incomplete"]),
            ],
            next_actions=[
                "Run managed Postgres and Redis live probes before production runtime cutover.",
                "Record restore drill and backup alert evidence before real customer data.",
                "Keep staging smoke data marked and isolated; automatic deletion stays disabled.",
            ],
        ),
        _expert_review(
            "security_compliance",
            "Security, compliance and platform risk",
            "attention_required" if not _any_secret_exposed(readiness, launch_gate, billing, operational, edge, monitoring) else "blocked",
            "Secret boundaries and security headers are represented, but paid launch still needs stable-domain callback alignment, origin lock, WAF evidence and backend-only eBay refresh proof.",
            evidence={
                "secret_exposed": False,
                "edge_status": edge.get("status") or "unknown",
                "edge_ready_count": _as_int(edge_summary.get("ready_count")),
                "edge_total_count": _as_int(edge_summary.get("total_count")),
                "legal_boundary_ready": _group_ready(groups, "legal_risk_boundary"),
                "refresh_success_count": refresh_success_count,
            },
            blockers=[
                *([] if edge.get("status") == "ready_for_owner_approval" else ["stable_domain_waf_origin_callback_evidence_missing"]),
                *([] if refresh_success_count > 0 else ["vault_backed_ebay_refresh_success_missing"]),
                *([] if _group_ready(groups, "legal_risk_boundary") else ["commercial_legal_risk_boundary_not_verified"]),
            ],
            next_actions=[
                "Verify app domain security headers, WAF/bot controls, origin lock and callback URLs before paid launch.",
                "Keep BYOK, eBay tokens and payment provider secrets backend/Vault/env only.",
                "Do not use the frozen eBay account or old demo products for real proof.",
            ],
        ),
        _expert_review(
            "ai_value_delivery",
            "AI CEO value delivery",
            "ready" if _group_ready(groups, "model_agent_value") else "blocked",
            "The AI CEO workflow shell is credible for controlled beta, but paid value claims need live model output over sanitized official packets and measured merchant outcomes.",
            evidence={
                "model_value_gate_ready": _group_ready(groups, "model_agent_value"),
                "provider_status_model_ready": bool(((readiness.get("provider_status") or {}).get("model_value") or {}).get("ready"))
                if isinstance(readiness.get("provider_status"), dict)
                else False,
                "ordinary_chat_allowed": True,
                "eBay_workflows_confirmation_gated": True,
            },
            blockers=[] if _group_ready(groups, "model_agent_value") else ["live_model_value_over_sanitized_packets_missing"],
            next_actions=[
                "Prove Market Report and Listing Package with live model output over sanitized eBay packets.",
                "Keep ordinary consulting chat separate from persistent merchant rules unless the merchant explicitly says to remember.",
                "Route eBay operating tasks into workflow and confirmation center, not free-form hidden actions.",
            ],
        ),
    ]
    ready_count = sum(1 for item in expert_reviews if item.get("status") == "ready")
    blocked_count = sum(1 for item in expert_reviews if item.get("status") == "blocked")
    attention_count = sum(1 for item in expert_reviews if item.get("status") == "attention_required")
    feasible_for_private_beta = beta_ready and official_packet_ready and not _any_secret_exposed(readiness, launch_gate, billing, operational, edge, monitoring)
    feasible_for_paid_public_launch = production_ready and can_accept_real_customers and paid_launch_ready and blocked_count == 0
    status = (
        "paid_public_launch_feasible"
        if feasible_for_paid_public_launch
        else "private_beta_feasible_paid_launch_blocked"
        if feasible_for_private_beta
        else "feasibility_blocked"
    )
    top_risks = _dedupe(
        risk
        for review in expert_reviews
        for risk in (review.get("blockers") or [])
        if risk
    )[:8]
    return {
        "contract_version": FEASIBILITY_REVIEW_VERSION,
        "mode": "platform_internal_admin_read_only",
        "audience": "platform_internal_admin",
        "customer_visible": False,
        "status": status,
        "summary": {
            "feasible_for_private_beta": feasible_for_private_beta,
            "feasible_for_paid_public_launch": feasible_for_paid_public_launch,
            "ready_count": ready_count,
            "blocked_count": blocked_count,
            "attention_count": attention_count,
            "expert_count": len(expert_reviews),
            "recommended_decision": "continue_private_beta_do_not_charge_publicly"
            if not feasible_for_paid_public_launch
            else "prepare_owner_final_approval",
            "next_step": top_risks[0] if top_risks else "owner_final_approval",
        },
        "expert_reviews": expert_reviews,
        "operating_model_review": _operating_model_review(
            authorization_strategy=authorization_strategy,
            media_router=media_router,
        ),
        "top_risks": top_risks,
        "next_7_day_actions": [
            "Keep public staging smoke, secret scan and readiness evidence current after every change.",
            "Close live merchant payment evidence before any public charging copy or switch.",
            "Wait for a clean new eBay account before any new OAuth or real listing smoke.",
            "Use live model value rehearsal on sanitized official packets to justify paid plan positioning.",
            "Route all image and video work through media.asset_generation, then AssetManifest review.",
        ],
        "safety": _safety_flags(),
        **_safety_flags(),
    }


def _expert_review(
    key: str,
    label: str,
    status: str,
    verdict: str,
    *,
    evidence: dict[str, Any],
    blockers: list[str],
    next_actions: list[str],
) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "status": status,
        "tone": "green" if status == "ready" else "amber" if status == "attention_required" else "red",
        "verdict": verdict,
        "evidence": evidence,
        "blockers": _dedupe(blockers),
        "next_actions": _dedupe(next_actions),
        "owner_approval_required": status != "ready",
        "customer_visible": False,
        "creates_checkout_session": False,
        "calls_stripe_api": False,
        "triggers_real_charge": False,
        "charge_now_allowed": False,
        "triggers_ebay_oauth": False,
        "repeat_ebay_oauth_allowed": False,
        "triggers_real_platform_write": False,
        "platform_write_now_allowed": False,
        "frontend_gets_payment_secret": False,
        "frontend_gets_ebay_token": False,
        "secret_exposed": False,
    }


def _safety_flags() -> dict[str, bool]:
    return {
        "public_charging_allowed": False,
        "creates_checkout_session": False,
        "calls_stripe_api": False,
        "triggers_real_charge": False,
        "charge_now_allowed": False,
        "triggers_ebay_oauth": False,
        "repeat_ebay_oauth_allowed": False,
        "triggers_real_platform_write": False,
        "platform_write_now_allowed": False,
        "frontend_gets_payment_secret": False,
        "frontend_gets_ebay_token": False,
        "exports_raw_secret": False,
        "exports_database": False,
        "secret_exposed": False,
    }


def _operating_model_review(
    *,
    authorization_strategy: dict[str, Any],
    media_router: dict[str, Any],
) -> dict[str, Any]:
    media_asset_contract = media_router.get("asset_contract") if isinstance(media_router.get("asset_contract"), dict) else {}
    authorization_rules = (
        authorization_strategy.get("operating_rules") if isinstance(authorization_strategy.get("operating_rules"), dict) else {}
    )
    return {
        "key": "jiejing_operating_model",
        "status": "private_beta_operating_model_ready_paid_launch_still_blocked",
        "plain_language": {
            "secret_boundary": "Browser, Agent, and Runtime receive work packets and secret_refs; raw eBay, model, media, and payment secrets stay behind backend Vault/env/provider adapters.",
            "platform_api_strategy": "Future marketplace API approval delays do not collapse Jiejing. eBay stays first; other platforms start with manual import/export or read-only lanes, then graduate one adapter at a time.",
            "media_strategy": "Merchant models act as the brain. Image, video, voice, upload, and external providers are drivers. Every output must become an AssetManifest before Listing use.",
        },
        "evidence": {
            "authorization_strategy_version": authorization_strategy.get("strategy_version"),
            "manual_import_is_valid_beta_lane": authorization_rules.get("manual_import_is_a_valid_beta_lane") is True,
            "read_only_before_write": authorization_rules.get("read_only_before_write") is True,
            "writes_require_confirmation_center": authorization_rules.get("writes_require_confirmation_center") is True,
            "media_router_version": media_router.get("router_version"),
            "deepseek_text_only_fallback_encoded": media_router.get("selected_model_provider") == "deepseek",
            "asset_manifest_required": media_asset_contract.get("all_generated_or_uploaded_assets_must_return_manifest") is True,
            "brief_is_not_generated_media": media_asset_contract.get("brief_is_not_generated_media") is True,
        },
        "must_not_do": _dedupe(
            list(authorization_strategy.get("blocked_actions") or [])
            + [
                "let_merchant_model_choice_bypass_asset_manifest",
                "treat_fal_or_any_media_driver_as_product_identity",
                "claim_image_or_video_generated_without_manifest",
            ]
        ),
        "secret_exposed": False,
        **_safety_flags(),
    }


def _by_key(items: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(items, list):
        return {}
    return {str(item.get("key") or ""): item for item in items if isinstance(item, dict) and item.get("key")}


def _group_ready(groups: dict[str, dict[str, Any]], key: str) -> bool:
    return (groups.get(key) or {}).get("status") == "ready"


def _official_packet_ready(evidence: dict[str, Any]) -> bool:
    required = {
        "store_profile",
        "account_business_policies",
        "inventory_and_offers",
        "orders_and_fulfillment",
        "finances",
        "taxonomy_listing_metadata",
    }
    present = set(evidence.get("latest_ebay_packet_present_resource_keys") or [])
    return evidence.get("latest_ebay_packet_status") == "created" and required.issubset(present)


def _any_secret_exposed(*packets: dict[str, Any]) -> bool:
    return any(bool(packet.get("secret_exposed")) for packet in packets if isinstance(packet, dict))


def _as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _dedupe(items: Any) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result
