"""Read-only live billing provider evidence register.

This packet is an operator-facing checklist for paid subscription cutover. It
records which backend-only Stripe Billing, Checkout, Portal, webhook, failure
path and rollback proofs exist. It never creates Checkout sessions, calls
Stripe, grants quota, or exposes provider secrets.
"""

from __future__ import annotations

import os
from typing import Any

from .billing_domain_cutover_rehearsal import build_billing_domain_cutover_rehearsal
from .billing_plan import STRIPE_CURRENT_API_VERSION, build_billing_plan, stripe_webhook_api_version
from .config import SaaSSettings
from .paid_launch_approval_packet import build_paid_launch_approval_packet
from .repository import SaaSRepository


REQUIRED_STRIPE_EVENTS = {
    "checkout.session.completed",
    "customer.subscription.created",
    "customer.subscription.updated",
    "customer.subscription.deleted",
    "invoice.paid",
    "invoice.payment_failed",
}


def build_billing_provider_evidence_register(settings: SaaSSettings, repository: SaaSRepository) -> dict[str, Any]:
    """Build the live billing provider evidence register without side effects."""

    billing = build_billing_plan(settings, repository)
    rehearsal = build_billing_domain_cutover_rehearsal(settings, repository)
    approval_packet = build_paid_launch_approval_packet(settings, repository)
    provider = billing.get("provider") if isinstance(billing.get("provider"), dict) else {}
    provider_contract = provider.get("signed_webhook_contract") if isinstance(provider.get("signed_webhook_contract"), dict) else {}
    checkout_contract = provider.get("checkout_portal_contract") if isinstance(provider.get("checkout_portal_contract"), dict) else {}
    checkout = checkout_contract.get("checkout_sessions") if isinstance(checkout_contract.get("checkout_sessions"), dict) else {}
    portal = checkout_contract.get("customer_portal") if isinstance(checkout_contract.get("customer_portal"), dict) else {}
    urls = checkout_contract.get("urls") if isinstance(checkout_contract.get("urls"), dict) else {}
    plan_ids = provider_contract.get("plan_ids") if isinstance(provider_contract.get("plan_ids"), dict) else {}
    event_types = set(provider_contract.get("webhook_event_types") or [])
    matrix = _by_key(billing.get("billing_live_cutover_matrix"))
    stages = _by_key(rehearsal.get("stages"))
    approval_summary = approval_packet.get("summary") if isinstance(approval_packet.get("summary"), dict) else {}

    rows = [
        _row(
            "live_provider_account",
            "Live Stripe provider account",
            provider.get("selected") == "stripe"
            and provider.get("external_paid_provider_configured") is True
            and provider_contract.get("api_key_configured") is True
            and provider.get("test_billing_provider_configured") is False
            and provider.get("manual_beta_private_provider_configured") is False,
            category="provider",
            owner="platform_ops",
            evidence_summary=_evidence(
                selected=provider.get("selected") or "not_selected",
                mode=provider_contract.get("provider_mode") or "unknown",
                api_key_configured=bool(provider_contract.get("api_key_configured")),
                frontend_gets_payment_secret=False,
            ),
            environment_keys=["JIEJING_BILLING_PROVIDER", "JIEJING_STRIPE_SECRET_KEY"],
            verification=["/billing/plans"],
            docs=["https://docs.stripe.com/get-started/checklist/go-live"],
            external_resource_required=True,
        ),
        _matrix_row(
            matrix,
            "stripe_live_price_catalog",
            "Live Products and Price IDs",
            evidence_summary=_evidence(
                plans_published=_env_bool("JIEJING_BILLING_PLANS_PUBLISHED"),
                starter=bool(plan_ids.get("starter")),
                operator=bool(plan_ids.get("operator")),
                team=bool(plan_ids.get("team")),
                no_test_objects=_env_bool("JIEJING_STRIPE_NO_TEST_OBJECTS_IN_LIVE_CONFIG"),
            ),
        ),
        _matrix_row(
            matrix,
            "stripe_subscription_checkout_contract",
            "Subscription Checkout contract",
            evidence_summary=_evidence(
                ready=bool(checkout.get("ready")),
                mode=checkout.get("mode") or "missing",
                uses_price_ids=checkout.get("uses_price_ids") is True,
                success_url=urls.get("success_url_configured") is True,
                cancel_url=urls.get("cancel_url_configured") is True,
            ),
        ),
        _matrix_row(
            matrix,
            "stripe_customer_portal_contract",
            "Customer Portal contract",
            evidence_summary=_evidence(
                ready=bool(portal.get("ready")),
                portal_return_url=urls.get("portal_return_url_configured") is True,
                override_locked=urls.get("request_override_must_match_configured_url") is True,
            ),
        ),
        _matrix_row(
            matrix,
            "stripe_signed_webhook_contract",
            "Signed webhook endpoint contract",
            evidence_summary=_evidence(
                webhook_configured=bool(provider_contract.get("webhook_configured")),
                required_events_present=REQUIRED_STRIPE_EVENTS.issubset(event_types),
                endpoint_configured=bool(provider_contract.get("webhook_endpoint_configured")),
            ),
        ),
        _matrix_row(
            matrix,
            "stripe_api_webhook_version_alignment",
            "Stripe request and webhook endpoint API version",
            evidence_summary=_evidence(
                expected=STRIPE_CURRENT_API_VERSION,
                request_api_version=checkout_contract.get("stripe_api_version") or "missing",
                recorded_webhook_api_version=stripe_webhook_api_version() or "missing",
                endpoint_version_verified=_env_bool("JIEJING_STRIPE_WEBHOOK_API_VERSION_VERIFIED"),
            ),
        ),
        _matrix_row(
            matrix,
            "stripe_webhook_failure_paths",
            "Webhook duplicate, delayed and out-of-order evidence",
            evidence_summary=_evidence(
                duplicate=_env_bool("JIEJING_STRIPE_WEBHOOK_DUPLICATE_TESTED"),
                delayed=_env_bool("JIEJING_STRIPE_WEBHOOK_DELAYED_TESTED"),
                out_of_order=_env_bool("JIEJING_STRIPE_WEBHOOK_OUT_OF_ORDER_TESTED"),
                evidence_id_present=_env_present("JIEJING_STRIPE_WEBHOOK_FAILURE_PATH_EVIDENCE_ID"),
            ),
        ),
        _matrix_row(
            matrix,
            "stripe_entitlement_quota_lifecycle",
            "Portal, entitlement and quota failure-path evidence",
            evidence_summary=_evidence(
                portal=_env_bool("JIEJING_STRIPE_CUSTOMER_PORTAL_TESTED"),
                cancel=_env_bool("JIEJING_STRIPE_SUBSCRIPTION_CANCEL_TESTED"),
                invoice_paid=_env_bool("JIEJING_STRIPE_INVOICE_PAID_TESTED"),
                payment_failure=_env_bool("JIEJING_STRIPE_PAYMENT_FAILURE_TESTED"),
                evidence_id_present=_env_present("JIEJING_STRIPE_CUSTOMER_PORTAL_FAILURE_PATH_EVIDENCE_ID"),
            ),
        ),
        _row(
            "stable_domain_billing_callbacks",
            "Stable-domain Checkout, Portal and webhook URLs",
            all(
                (stages.get(key) or {}).get("status") == "ready"
                for key in (
                    "stripe_checkout_return_urls_on_stable_domain",
                    "stripe_customer_portal_return_url_on_stable_domain",
                    "stripe_signed_webhook_on_stable_domain",
                )
            ),
            category="domain",
            owner="platform_ops",
            evidence_summary=_evidence(
                checkout=(stages.get("stripe_checkout_return_urls_on_stable_domain") or {}).get("status") or "missing",
                portal=(stages.get("stripe_customer_portal_return_url_on_stable_domain") or {}).get("status") or "missing",
                webhook=(stages.get("stripe_signed_webhook_on_stable_domain") or {}).get("status") or "missing",
            ),
            environment_keys=[
                "JIEJING_BILLING_SUCCESS_URL",
                "JIEJING_BILLING_CANCEL_URL",
                "JIEJING_BILLING_PORTAL_RETURN_URL",
                "JIEJING_BILLING_WEBHOOK_URL",
            ],
            verification=["/commercial/billing-domain-cutover-rehearsal", "/domain/status"],
            docs=["https://docs.stripe.com/customer-management/integrate-customer-portal", "https://docs.stripe.com/webhooks"],
            external_resource_required=True,
        ),
        _row(
            "cutover_rollback_audit_packet",
            "Rollback audit packet",
            (stages.get("cutover_rollback_audit_packet_recorded") or {}).get("status") == "ready",
            category="release",
            owner="release_manager",
            evidence_summary=_evidence(
                rollback=_env_bool("JIEJING_CUTOVER_ROLLBACK_VERIFIED"),
                secret_scan=_env_bool("JIEJING_SECRET_SCAN_PASSED"),
                readiness=_env_bool("JIEJING_READINESS_SNAPSHOT_RECORDED"),
                browser_smoke=_env_bool("JIEJING_BROWSER_SMOKE_PASSED"),
                audit_packet_id_present=_env_present("JIEJING_CUTOVER_ROLLBACK_AUDIT_PACKET_ID"),
            ),
            environment_keys=[
                "JIEJING_CUTOVER_ROLLBACK_VERIFIED",
                "JIEJING_SECRET_SCAN_PASSED",
                "JIEJING_READINESS_SNAPSHOT_RECORDED",
                "JIEJING_BROWSER_SMOKE_PASSED",
                "JIEJING_CUTOVER_ROLLBACK_AUDIT_PACKET_ID",
            ],
            verification=["tools/jiejing_secret_scan.py", "/health", "/health/deep", "/readiness/product-saas", "output/browser-smoke"],
            docs=["https://docs.stripe.com/get-started/checklist/go-live"],
            external_resource_required=False,
        ),
    ]
    blocked = [row for row in rows if row.get("status") != "ready"]
    owner_packet_id = _env_text("JIEJING_PAID_LAUNCH_OWNER_APPROVAL_PACKET_ID")
    return {
        "contract_version": "2026-07-02-live-billing-provider-evidence-register",
        "mode": "read_only_no_charge_no_checkout",
        "environment": settings.environment,
        "status": "ready_for_owner_review" if not blocked else "blocked",
        "ready_for_owner_review": not blocked,
        "public_paid_launch_allowed": False,
        "charge_now_allowed": False,
        "creates_checkout_session": False,
        "calls_stripe_api": False,
        "triggers_real_charge": False,
        "triggers_ebay_oauth": False,
        "repeat_ebay_oauth_allowed": False,
        "triggers_real_platform_write": False,
        "frontend_gets_payment_secret": False,
        "frontend_gets_provider_secret": False,
        "selected_provider": provider.get("selected") or "not_selected",
        "summary": {
            "ready_count": len(rows) - len(blocked),
            "total_count": len(rows),
            "blocked_count": len(blocked),
            "blocked_keys": [str(row.get("key") or "") for row in blocked],
            "next_step": str((blocked[0] if blocked else {}).get("key") or "owner_approval"),
            "billing_plan_ready_for_paid_launch": bool(billing.get("billing_ready_for_paid_launch")),
            "billing_domain_rehearsal_status": rehearsal.get("status") or "unknown",
            "paid_launch_approval_packet_status": approval_packet.get("status") or "unknown",
            "paid_launch_approval_blocked_count": int(approval_summary.get("blocked_count") or 0),
        },
        "evidence_rows": rows,
        "owner_approval": {
            "status": "recorded" if owner_packet_id else "required",
            "owner_approval_required": True,
            "evidence_id_present": bool(owner_packet_id),
            "environment_keys": ["JIEJING_PAID_LAUNCH_OWNER_APPROVAL_PACKET_ID"],
            "next_action": "Attach this register to the final owner approval packet before enabling any public charging.",
            "public_paid_launch_allowed": False,
            "charge_now_allowed": False,
            "secret_exposed": False,
        },
        "source_packets": [
            "/billing/plans",
            "/billing/checkout-contract",
            "/commercial/billing-domain-cutover-rehearsal",
            "/commercial/paid-launch-approval-packet",
        ],
        "docs": [
            "https://docs.stripe.com/billing/subscriptions/build-subscriptions",
            "https://docs.stripe.com/customer-management/integrate-customer-portal",
            "https://docs.stripe.com/webhooks",
            "https://docs.stripe.com/webhooks/versioning",
        ],
        "secret_exposed": False,
    }


def _matrix_row(matrix: dict[str, dict[str, Any]], key: str, title: str, *, evidence_summary: str) -> dict[str, Any]:
    item = matrix.get(key) or {}
    return _row(
        key,
        title,
        item.get("status") == "ready",
        category=str(item.get("category") or "billing"),
        owner=str(item.get("owner") or "platform_ops"),
        evidence_summary=evidence_summary,
        environment_keys=[str(value) for value in item.get("environment_keys") or []],
        verification=[str(value) for value in item.get("verification") or []],
        docs=[str(value) for value in item.get("docs") or []],
        external_resource_required=bool(item.get("external_resource_required")),
        next_action=str(item.get("next_action") or ""),
    )


def _row(
    key: str,
    title: str,
    ready: bool,
    *,
    category: str,
    owner: str,
    evidence_summary: str,
    environment_keys: list[str],
    verification: list[str],
    docs: list[str],
    external_resource_required: bool,
    next_action: str = "",
) -> dict[str, Any]:
    return {
        "key": key,
        "title": title,
        "status": "ready" if ready else "blocked",
        "severity": "info" if ready else "blocker",
        "category": category,
        "owner": owner,
        "evidence_summary": evidence_summary,
        "environment_keys": environment_keys,
        "verification": verification,
        "docs": docs,
        "external_resource_required": external_resource_required,
        "blocks_paid_launch": not ready,
        "next_action": next_action or "Record the required backend-only evidence before owner review.",
        "creates_checkout_session": False,
        "calls_stripe_api": False,
        "triggers_real_charge": False,
        "charge_now_allowed": False,
        "triggers_ebay_oauth": False,
        "repeat_ebay_oauth_allowed": False,
        "triggers_real_platform_write": False,
        "frontend_gets_payment_secret": False,
        "secret_values_required_in_backend_only": any("SECRET" in key or "API_KEY" in key for key in environment_keys),
        "secret_value_returned": False,
        "secret_exposed": False,
    }


def _by_key(items: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(items, list):
        return {}
    return {str(item.get("key") or ""): item for item in items if isinstance(item, dict)}


def _env_bool(name: str) -> bool:
    return str(os.environ.get(name) or "").strip().lower() in {"1", "true", "yes", "on"}


def _env_text(name: str) -> str:
    return os.environ.get(name, "").strip()


def _env_present(name: str) -> bool:
    return bool(_env_text(name))


def _evidence(**values: Any) -> str:
    return "; ".join(f"{key}={value}" for key, value in values.items())
