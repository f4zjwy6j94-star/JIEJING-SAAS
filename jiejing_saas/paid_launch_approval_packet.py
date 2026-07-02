"""Owner approval packet for paid public launch readiness."""

from __future__ import annotations

from typing import Any

from .billing_domain_cutover_rehearsal import build_billing_domain_cutover_rehearsal
from .commercial_launch_gate import build_commercial_launch_gate
from .config import SaaSSettings
from .domain_readiness import build_domain_readiness
from .readiness import build_product_readiness_or_degraded
from .repository import SaaSRepository


PRIMARY_SEQUENCE = [
    "stable_domain_hardening",
    "stripe_live_cutover",
    "no_charge_launch_rehearsal",
    "new_ebay_account_low_risk_smoke",
]


def build_paid_launch_approval_packet(settings: SaaSSettings, repository: SaaSRepository) -> dict[str, Any]:
    """Build a read-only packet that shows exactly what blocks public charging."""

    readiness = build_product_readiness_or_degraded(settings, repository)
    domain = build_domain_readiness(settings)
    launch_gate = build_commercial_launch_gate(settings, repository)
    rehearsal = build_billing_domain_cutover_rehearsal(settings, repository)
    action_plan = launch_gate.get("launch_action_plan") if isinstance(launch_gate.get("launch_action_plan"), dict) else {}
    decision = action_plan.get("paid_launch_cutover_decision") if isinstance(action_plan.get("paid_launch_cutover_decision"), dict) else {}
    cutover = action_plan.get("paid_launch_cutover_checklist") if isinstance(action_plan.get("paid_launch_cutover_checklist"), list) else []
    new_account = action_plan.get("new_ebay_account_smoke_runbook") if isinstance(action_plan.get("new_ebay_account_smoke_runbook"), list) else []
    drills = action_plan.get("commercial_hardening_drills") if isinstance(action_plan.get("commercial_hardening_drills"), list) else []
    steps = _build_steps(
        readiness=readiness,
        domain=domain,
        rehearsal=rehearsal,
        decision=decision,
        cutover=cutover,
        new_account=new_account,
        drills=drills,
    )
    blocked = [step for step in steps if step.get("status") != "ready"]
    user_items = _external_configuration_items(steps=steps, domain=domain, rehearsal=rehearsal, new_account=new_account)
    return {
        "contract_version": "2026-06-18-paid-launch-approval-packet",
        "mode": "owner_approval_packet_no_charge_no_write",
        "environment": settings.environment,
        "status": "ready_for_owner_approval" if not blocked else "blocked",
        "ready_for_owner_approval": not blocked,
        "public_paid_launch_allowed": False,
        "charge_now_allowed": False,
        "creates_checkout_session": False,
        "calls_stripe_api": False,
        "triggers_real_charge": False,
        "triggers_ebay_oauth": False,
        "repeat_ebay_oauth_allowed": False,
        "triggers_real_platform_write": False,
        "frontend_gets_payment_secret": False,
        "frontend_gets_ebay_token": False,
        "old_frozen_ebay_account_reuse_allowed": False,
        "old_demo_product_or_sku_allowed": False,
        "summary": {
            "ready_count": len(steps) - len(blocked),
            "total_count": len(steps),
            "blocked_count": len(blocked),
            "blocked_keys": [str(step.get("key") or "") for step in blocked],
            "next_step": str((blocked[0] if blocked else {}).get("key") or ""),
            "production_ready": bool(readiness.get("production_ready")),
            "beta_ready": bool(readiness.get("beta_ready")),
            "can_accept_real_customers": bool(readiness.get("can_accept_real_customers")),
            "stable_domain_ready": bool(domain.get("production_domain_ready")),
            "stripe_rehearsal_status": rehearsal.get("status") or "unknown",
            "new_account_smoke_ready": _all_ready(new_account),
            "external_configuration_needed_count": len([item for item in user_items if item.get("status") != "ready"]),
        },
        "steps": steps,
        "external_configuration_needed": user_items,
        "agent_completed_before_user_intervention": [
            "read_only_paid_launch_approval_packet_contract",
            "stable_domain_dns_tls_callback_evidence_slots",
            "stripe_live_price_checkout_portal_webhook_rehearsal_contract",
            "subscription_state_quota_lifecycle_regressions",
            "new_ebay_account_low_risk_smoke_runbook",
            "settings_launch_gate_visibility",
        ],
        "final_rehearsal_commands": [
            "python tools/test_jiejing_paid_launch_approval_packet.py",
            "python tools/test_jiejing_domain_launch_gate.py",
            "python tools/test_jiejing_billing_domain_cutover_rehearsal.py",
            "python tools/test_jiejing_new_ebay_account_low_risk_runbook.py",
            "python tools/jiejing_secret_scan.py",
            "node tools/codex_jiejing_paid_cutover_decision_smoke.js",
        ],
        "evidence_register": [
            "/health",
            "/health/deep",
            "/readiness/product-saas",
            "/domain/status",
            "/billing/plans",
            "/billing/checkout-contract",
            "/commercial/billing-domain-cutover-rehearsal",
            "/commercial/billing-provider-evidence-register",
            "/commercial/launch-gate",
            "/commercial/paid-launch-approval-packet",
            "tools/jiejing_billing_provider_evidence_register.py --output output/billing-provider-evidence-register/latest.json",
            "tools/jiejing_new_ebay_account_low_risk_check.py --checklist-only",
        ],
        "docs": [
            "https://docs.stripe.com/api/versioning",
            "https://docs.stripe.com/billing/quickstart",
            "https://docs.stripe.com/webhooks/signature",
            "https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/routing-to-tunnel/dns/",
            "https://developer.ebay.com/develop/guides-v2/authorization",
        ],
        "rollback_controls": [
            "keep_trycloudflare_staging_available_until_stable_domain_smoke_passes",
            "do_not_enable_public_checkout_until_owner_approval",
            "disable_JIEJING_BILLING_PROVIDER_or_quota_flags_if_webhook_smoke_fails",
            "keep_real_ebay_writes_confirmation_gated_after_billing_cutover",
            "never_retry_platform_write_after_timeout_without_platform_state_check",
        ],
        "secret_exposed": False,
    }


def _build_steps(
    *,
    readiness: dict[str, Any],
    domain: dict[str, Any],
    rehearsal: dict[str, Any],
    decision: dict[str, Any],
    cutover: list[dict[str, Any]],
    new_account: list[dict[str, Any]],
    drills: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    cutover_by_key = _by_key(cutover)
    drill_by_key = _by_key(drills)
    rehearsal_summary = rehearsal.get("summary") if isinstance(rehearsal.get("summary"), dict) else {}
    return [
        _step(
            "stable_domain_hardening",
            "Stable domain, DNS, TLS, CORS and callback hardening",
            bool(domain.get("production_domain_ready")),
            category="domain",
            owner="platform_ops",
            evidence_summary=_evidence(
                domain=domain.get("stable_domain") or "not_selected",
                dns=bool(domain.get("dns_verified")),
                tls=bool(domain.get("tls_verified")),
                callback=bool(domain.get("ebay_callback_verified")),
                cors=bool(domain.get("cors_origin_aligned")),
                headers=bool(domain.get("security_headers_verified")),
            ),
            next_action="Bind a stable HTTPS domain, verify DNS/TLS/security headers, align CORS and update the eBay callback URL.",
            verification=["/domain/status", "/health/deep", "tools/test_jiejing_domain_launch_gate.py"],
            external_resource_required=True,
            blocked_by=domain.get("blockers") if isinstance(domain.get("blockers"), list) else [],
        ),
        _step(
            "stripe_live_cutover",
            "Stripe live Price IDs, Checkout, Portal and signed webhook cutover",
            rehearsal.get("status") == "ready_for_owner_approval",
            category="billing",
            owner="platform_ops",
            evidence_summary=_evidence(
                rehearsal_status=rehearsal.get("status") or "unknown",
                ready=f"{rehearsal_summary.get('ready_count', 0)}/{rehearsal_summary.get('total_count', 0)}",
                next=rehearsal_summary.get("next_step") or "stripe_live_provider_selected",
            ),
            next_action=rehearsal_summary.get("next_action") or "Configure Stripe live provider, Price IDs, stable-domain URLs and signed webhook evidence.",
            verification=["/commercial/billing-domain-cutover-rehearsal", "/billing/plans", "/billing/checkout-contract"],
            external_resource_required=True,
            blocked_by=rehearsal_summary.get("blocked_keys") if isinstance(rehearsal_summary.get("blocked_keys"), list) else [],
        ),
        _step(
            "no_charge_launch_rehearsal",
            "No-charge full launch rehearsal and rollback packet",
            decision.get("status") == "ready_for_owner_approval"
            and (cutover_by_key.get("final_paid_launch_smoke_evidence") or {}).get("status") == "ready",
            category="release",
            owner="release_manager",
            evidence_summary=_evidence(
                decision=decision.get("status") or "blocked",
                public_paid_launch_allowed=bool(decision.get("public_paid_launch_allowed")),
                final_smoke=(cutover_by_key.get("final_paid_launch_smoke_evidence") or {}).get("status") or "missing",
                drill=(drill_by_key.get("final_commercial_smoke") or {}).get("status") or "missing",
            ),
            next_action="Run final no-charge register/login/domain/billing/webhook/readiness/secret-scan/browser smoke and record rollback evidence.",
            verification=["/commercial/launch-gate", "tools/jiejing_secret_scan.py", "output/browser-smoke"],
            external_resource_required=False,
            blocked_by=[str(item.get("key") or "") for item in cutover if isinstance(item, dict) and item.get("status") != "ready"],
        ),
        _step(
            "new_ebay_account_low_risk_smoke",
            "Clean new eBay account low-risk smoke runbook",
            _all_ready(new_account),
            category="ebay",
            owner="founder_operator",
            evidence_summary=_evidence(
                ready=f"{sum(1 for item in new_account if isinstance(item, dict) and item.get('status') == 'ready')}/{len(new_account)}",
                old_frozen_account_reuse_allowed=False,
                old_demo_product_or_sku_allowed=False,
            ),
            next_action="Wait for the owner to provide a clean new eBay account, then run OAuth, packet, health, fresh product, confirmation, publish probe and cleanup in order.",
            verification=["tools/jiejing_new_ebay_account_low_risk_check.py --checklist-only", "/commercial/launch-gate"],
            external_resource_required=True,
            blocked_by=[str(item.get("key") or "") for item in new_account if isinstance(item, dict) and item.get("status") != "ready"],
        ),
    ]


def _external_configuration_items(
    *,
    steps: list[dict[str, Any]],
    domain: dict[str, Any],
    rehearsal: dict[str, Any],
    new_account: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    step_by_key = _by_key(steps)
    rehearsal_summary = rehearsal.get("summary") if isinstance(rehearsal.get("summary"), dict) else {}
    return [
        _external_item(
            "stable_domain_dns_tls_callback",
            "Stable domain DNS/TLS/CORS/eBay callback",
            (step_by_key.get("stable_domain_hardening") or {}).get("status") == "ready",
            env_keys=[
                "JIEJING_PUBLIC_BASE_URL",
                "JIEJING_STABLE_DOMAIN",
                "JIEJING_CORS_ORIGIN",
                "JIEJING_DOMAIN_DNS_VERIFIED",
                "JIEJING_TLS_VERIFIED",
                "JIEJING_EBAY_CALLBACK_VERIFIED",
                "JIEJING_DEPLOYMENT_HARDENED",
                "JIEJING_SECURITY_HEADERS_VERIFIED",
            ],
            evidence=_evidence(domain=domain.get("stable_domain") or "not_selected", blockers=",".join(domain.get("blockers") or [])),
        ),
        _external_item(
            "stripe_live_products_prices_webhook",
            "Stripe live Products, Price IDs, Checkout/Portal URLs and signed webhook",
            (step_by_key.get("stripe_live_cutover") or {}).get("status") == "ready",
            env_keys=[
                "JIEJING_BILLING_PROVIDER",
                "JIEJING_STRIPE_SECRET_KEY",
                "JIEJING_STRIPE_WEBHOOK_SECRET",
                "JIEJING_STRIPE_PRICE_STARTER_ID",
                "JIEJING_STRIPE_PRICE_OPERATOR_ID",
                "JIEJING_STRIPE_PRICE_TEAM_ID",
                "JIEJING_BILLING_SUCCESS_URL",
                "JIEJING_BILLING_CANCEL_URL",
                "JIEJING_BILLING_PORTAL_RETURN_URL",
                "JIEJING_BILLING_WEBHOOK_URL",
                "JIEJING_STRIPE_ACCOUNT_ACTIVATED",
                "JIEJING_STRIPE_LIVE_MODE_DASHBOARD_REVIEWED",
                "JIEJING_STRIPE_GO_LIVE_CHECKLIST_EVIDENCE_ID",
                "JIEJING_STRIPE_TEST_MODE_OBJECTS_EXCLUDED",
                "JIEJING_STRIPE_TAX_INVOICE_RECEIPT_REVIEWED",
                "JIEJING_STRIPE_SUPPORT_CONTACT_BRANDING_REVIEWED",
                "JIEJING_STRIPE_TAX_INVOICE_RECEIPT_EVIDENCE_ID",
                "JIEJING_STRIPE_WEBHOOK_FAILURE_PATH_EVIDENCE_ID",
                "JIEJING_STRIPE_CUSTOMER_PORTAL_FAILURE_PATH_EVIDENCE_ID",
            ],
            evidence=_evidence(next=rehearsal_summary.get("next_step") or "stripe_live_provider_selected"),
        ),
        _external_item(
            "no_charge_rehearsal_evidence_flags",
            "No-charge rehearsal evidence flags",
            (step_by_key.get("no_charge_launch_rehearsal") or {}).get("status") == "ready",
            env_keys=[
                "JIEJING_CUTOVER_ROLLBACK_VERIFIED",
                "JIEJING_SECRET_SCAN_PASSED",
                "JIEJING_READINESS_SNAPSHOT_RECORDED",
                "JIEJING_BROWSER_SMOKE_PASSED",
                "JIEJING_CUTOVER_ROLLBACK_AUDIT_PACKET_ID",
                "JIEJING_FINAL_COMMERCIAL_SMOKE_PASSED",
                "JIEJING_FINAL_COMMERCIAL_SMOKE_EVIDENCE_ID",
            ],
            evidence="local tests and browser smoke must be recorded before owner approval",
            external_resource_required=False,
        ),
        _external_item(
            "clean_new_ebay_account_and_fresh_product",
            "Clean new eBay account plus fresh product/SKU/assets",
            _all_ready(new_account),
            env_keys=[
                "JIEJING_NEW_EBAY_ACCOUNT_CONFIRMED_CLEAN",
                "JIEJING_NEW_EBAY_OLD_FROZEN_ACCOUNT_REJECTED",
                "JIEJING_NEW_EBAY_OAUTH_OPERATOR_APPROVED",
                "JIEJING_NEW_EBAY_ACCOUNT_OAUTH_COMPLETED",
                "JIEJING_NEW_EBAY_FRESH_PRODUCT_DECLARED",
                "JIEJING_NEW_EBAY_FRESH_SKU_DECLARED",
                "JIEJING_NEW_EBAY_FRESH_ASSETS_DECLARED",
                "JIEJING_NEW_EBAY_NO_OLD_LISTING_OR_REPORT_REUSE",
                "JIEJING_NEW_EBAY_PRODUCT_DUPLICATE_GUARD_PASSED",
                "JIEJING_NEW_EBAY_PUBLISH_HEALTH_CONFIRMATION_READY",
                "JIEJING_NEW_EBAY_PUBLISH_CONFIRMATION_APPROVED",
                "JIEJING_NEW_EBAY_ACCOUNT_REAL_PUBLISH_PASSED",
                "JIEJING_NEW_EBAY_CLEANUP_CONFIRMATION_APPROVED",
                "JIEJING_NEW_EBAY_TEST_CLEANUP_CONFIRMED",
            ],
            evidence="old frozen account and old demo product/SKU/assets remain forbidden",
        ),
    ]


def _step(
    key: str,
    title: str,
    ready: bool,
    *,
    category: str,
    owner: str,
    evidence_summary: str,
    next_action: str,
    verification: list[str],
    external_resource_required: bool,
    blocked_by: list[str],
) -> dict[str, Any]:
    return {
        "key": key,
        "title": title,
        "status": "ready" if ready else "blocked",
        "severity": "info" if ready else "blocker",
        "category": category,
        "owner": owner,
        "evidence_summary": evidence_summary,
        "next_action": next_action,
        "verification": verification,
        "blocked_by": [str(item) for item in blocked_by if str(item)],
        "external_resource_required": external_resource_required,
        "creates_checkout_session": False,
        "calls_stripe_api": False,
        "triggers_real_charge": False,
        "charge_now_allowed": False,
        "triggers_ebay_oauth": False,
        "repeat_ebay_oauth_allowed": False,
        "triggers_real_platform_write": False,
        "frontend_gets_payment_secret": False,
        "frontend_gets_ebay_token": False,
        "secret_exposed": False,
    }


def _external_item(
    key: str,
    title: str,
    ready: bool,
    *,
    env_keys: list[str],
    evidence: str,
    external_resource_required: bool = True,
) -> dict[str, Any]:
    return {
        "key": key,
        "title": title,
        "status": "ready" if ready else "blocked",
        "severity": "info" if ready else "blocker",
        "environment_keys": env_keys,
        "evidence_summary": evidence,
        "external_resource_required": external_resource_required,
        "secret_values_required_in_backend_only": True,
        "secret_value_returned": False,
        "frontend_gets_secret": False,
        "secret_exposed": False,
    }


def _by_key(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(item.get("key") or ""): item for item in items if isinstance(item, dict)}


def _all_ready(items: list[dict[str, Any]]) -> bool:
    return bool(items) and all(isinstance(item, dict) and item.get("status") == "ready" for item in items)


def _evidence(**values: Any) -> str:
    return "; ".join(f"{key}={value}" for key, value in values.items())
