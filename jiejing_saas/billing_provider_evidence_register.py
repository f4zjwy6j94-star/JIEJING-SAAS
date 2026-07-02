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

REQUIRED_STATE_MACHINE_STEPS = {
    "subscription_activation_grants_entitlement",
    "invoice_paid_keeps_quota_open",
    "payment_failed_disables_entitlement",
    "subscription_cancel_disables_entitlement",
    "quota_guardrail_blocks_metered_work",
    "customer_portal_changes_audited",
    "provider_cutover_no_real_charge_safety",
}

REQUIRED_INCIDENT_CARDS = {
    "customer_portal_change",
    "payment_failed",
    "subscription_cancelled",
    "refund_or_dispute",
    "quota_hard_stop",
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
    shutdown_closure = (
        billing.get("subscription_quota_shutdown_closure")
        if isinstance(billing.get("subscription_quota_shutdown_closure"), dict)
        else {}
    )
    incident_runbook = billing.get("billing_incident_runbook") if isinstance(billing.get("billing_incident_runbook"), dict) else {}
    trust_packet = billing.get("customer_billing_trust_packet") if isinstance(billing.get("customer_billing_trust_packet"), dict) else {}
    shutdown_steps = _by_key(shutdown_closure.get("steps"))
    incident_cards = _by_key(incident_runbook.get("cards"))
    state_machine_ready = (
        bool(shutdown_closure.get("ready_for_live_cutover"))
        and all((shutdown_steps.get(key) or {}).get("status") == "ready" for key in REQUIRED_STATE_MACHINE_STEPS)
        and all((incident_cards.get(key) or {}).get("status") == "ready" for key in REQUIRED_INCIDENT_CARDS)
        and bool(incident_runbook.get("customer_portal_changes_require_signed_webhook"))
        and bool(incident_runbook.get("refund_or_dispute_cannot_be_frontend_executed"))
        and bool(incident_runbook.get("payment_failed_cancel_blocks_metered_work"))
        and bool(trust_packet.get("entitlement_recovery_does_not_repeat_ebay_oauth"))
        and _env_present("JIEJING_STRIPE_WEBHOOK_FAILURE_PATH_EVIDENCE_ID")
        and _env_present("JIEJING_STRIPE_CUSTOMER_PORTAL_FAILURE_PATH_EVIDENCE_ID")
        and trust_packet.get("charge_now_allowed") is False
        and trust_packet.get("frontend_gets_payment_secret") is False
        and shutdown_closure.get("charge_now_allowed") is False
        and shutdown_closure.get("frontend_gets_payment_secret") is False
    )

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
        _row(
            "stripe_account_activation_go_live_evidence",
            "Stripe account activation and go-live checklist evidence",
            _env_bool("JIEJING_STRIPE_ACCOUNT_ACTIVATED")
            and _env_bool("JIEJING_STRIPE_LIVE_MODE_DASHBOARD_REVIEWED")
            and _env_present("JIEJING_STRIPE_GO_LIVE_CHECKLIST_EVIDENCE_ID"),
            category="provider",
            owner="platform_ops",
            evidence_summary=_evidence(
                account_activated=_env_bool("JIEJING_STRIPE_ACCOUNT_ACTIVATED"),
                live_mode_dashboard_reviewed=_env_bool("JIEJING_STRIPE_LIVE_MODE_DASHBOARD_REVIEWED"),
                checklist_evidence_id_present=_env_present("JIEJING_STRIPE_GO_LIVE_CHECKLIST_EVIDENCE_ID"),
                frontend_gets_payment_secret=False,
            ),
            environment_keys=[
                "JIEJING_STRIPE_ACCOUNT_ACTIVATED",
                "JIEJING_STRIPE_LIVE_MODE_DASHBOARD_REVIEWED",
                "JIEJING_STRIPE_GO_LIVE_CHECKLIST_EVIDENCE_ID",
            ],
            verification=["Stripe Dashboard live-mode account checklist", "tools/jiejing_billing_provider_evidence_register.py"],
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
        _row(
            "stripe_live_mode_test_object_isolation",
            "Stripe live-mode and test-object isolation",
            _env_bool("JIEJING_STRIPE_NO_TEST_OBJECTS_IN_LIVE_CONFIG")
            and _env_bool("JIEJING_STRIPE_TEST_MODE_OBJECTS_EXCLUDED")
            and provider.get("selected") == "stripe"
            and provider.get("test_billing_provider_configured") is False,
            category="provider",
            owner="platform_ops",
            evidence_summary=_evidence(
                no_test_objects_in_live_config=_env_bool("JIEJING_STRIPE_NO_TEST_OBJECTS_IN_LIVE_CONFIG"),
                test_mode_objects_excluded=_env_bool("JIEJING_STRIPE_TEST_MODE_OBJECTS_EXCLUDED"),
                provider=provider.get("selected") or "not_selected",
                test_provider_configured=bool(provider.get("test_billing_provider_configured")),
            ),
            environment_keys=[
                "JIEJING_STRIPE_NO_TEST_OBJECTS_IN_LIVE_CONFIG",
                "JIEJING_STRIPE_TEST_MODE_OBJECTS_EXCLUDED",
                "JIEJING_BILLING_PROVIDER",
            ],
            verification=["/billing/plans", "Stripe Dashboard live-mode object review"],
            docs=["https://docs.stripe.com/payments/checkout/build-subscriptions"],
            external_resource_required=True,
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
            "merchant_billing_state_machine_proof",
            "Merchant billing state machine and recovery proof",
            state_machine_ready,
            category="entitlement",
            owner="platform_ops",
            evidence_summary=_evidence(
                shutdown_ready=bool(shutdown_closure.get("ready_for_live_cutover")),
                shutdown_ready_count=int(shutdown_closure.get("ready_count") or 0),
                shutdown_total_count=int(shutdown_closure.get("total_count") or 0),
                incident_ready_count=int(incident_runbook.get("ready_count") or 0),
                incident_total_count=int(incident_runbook.get("total_count") or 0),
                portal_change_requires_signed_webhook=bool(incident_runbook.get("customer_portal_changes_require_signed_webhook")),
                refund_dispute_frontend_disabled=bool(incident_runbook.get("refund_or_dispute_cannot_be_frontend_executed")),
                recovery_avoids_ebay_oauth=bool(trust_packet.get("entitlement_recovery_does_not_repeat_ebay_oauth")),
                webhook_failure_evidence_id_present=_env_present("JIEJING_STRIPE_WEBHOOK_FAILURE_PATH_EVIDENCE_ID"),
                portal_failure_evidence_id_present=_env_present("JIEJING_STRIPE_CUSTOMER_PORTAL_FAILURE_PATH_EVIDENCE_ID"),
            ),
            environment_keys=[
                "JIEJING_STRIPE_WEBHOOK_FAILURE_PATH_EVIDENCE_ID",
                "JIEJING_STRIPE_CUSTOMER_PORTAL_FAILURE_PATH_EVIDENCE_ID",
                "JIEJING_STRIPE_CUSTOMER_PORTAL_TESTED",
                "JIEJING_STRIPE_SUBSCRIPTION_CANCEL_TESTED",
                "JIEJING_STRIPE_INVOICE_PAID_TESTED",
                "JIEJING_STRIPE_PAYMENT_FAILURE_TESTED",
            ],
            verification=[
                "tools/test_jiejing_billing_webhook_subscription_state.py",
                "tools/test_jiejing_stripe_checkout_portal.py",
                "/billing/usage",
                "/billing/plans",
            ],
            docs=[
                "https://docs.stripe.com/billing/subscriptions/overview",
                "https://docs.stripe.com/billing/testing",
                "https://docs.stripe.com/customer-management/integrate-customer-portal",
                "https://docs.stripe.com/webhooks",
            ],
            external_resource_required=True,
            next_action="Keep signed webhook, portal change, failed-payment, cancellation, refund/dispute and quota hard-stop evidence green before owner approval.",
        ),
        _row(
            "stripe_tax_invoice_receipt_branding_evidence",
            "Tax, invoice, receipt, support and branding evidence",
            _env_bool("JIEJING_STRIPE_TAX_INVOICE_RECEIPT_REVIEWED")
            and _env_bool("JIEJING_STRIPE_SUPPORT_CONTACT_BRANDING_REVIEWED")
            and _env_present("JIEJING_STRIPE_TAX_INVOICE_RECEIPT_EVIDENCE_ID"),
            category="billing_ops",
            owner="platform_ops",
            evidence_summary=_evidence(
                tax_invoice_receipt_reviewed=_env_bool("JIEJING_STRIPE_TAX_INVOICE_RECEIPT_REVIEWED"),
                support_contact_branding_reviewed=_env_bool("JIEJING_STRIPE_SUPPORT_CONTACT_BRANDING_REVIEWED"),
                evidence_id_present=_env_present("JIEJING_STRIPE_TAX_INVOICE_RECEIPT_EVIDENCE_ID"),
                frontend_gets_payment_secret=False,
            ),
            environment_keys=[
                "JIEJING_STRIPE_TAX_INVOICE_RECEIPT_REVIEWED",
                "JIEJING_STRIPE_SUPPORT_CONTACT_BRANDING_REVIEWED",
                "JIEJING_STRIPE_TAX_INVOICE_RECEIPT_EVIDENCE_ID",
            ],
            verification=["Stripe Dashboard customer emails/receipts/branding/tax settings review"],
            docs=[
                "https://docs.stripe.com/customer-management/integrate-customer-portal",
                "https://docs.stripe.com/billing/subscriptions/overview",
            ],
            external_resource_required=True,
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
            "no_charge_live_domain_rehearsal_packet",
            "No-charge live-domain billing rehearsal packet",
            all(
                (stages.get(key) or {}).get("status") == "ready"
                for key in (
                    "stripe_checkout_return_urls_on_stable_domain",
                    "stripe_customer_portal_return_url_on_stable_domain",
                    "stripe_signed_webhook_on_stable_domain",
                )
            )
            and _env_bool("JIEJING_NO_CHARGE_CHECKOUT_RETURN_URL_SMOKE_PASSED")
            and _env_bool("JIEJING_NO_CHARGE_PORTAL_RETURN_URL_SMOKE_PASSED")
            and _env_bool("JIEJING_NO_CHARGE_SIGNED_WEBHOOK_SMOKE_PASSED")
            and _env_bool("JIEJING_NO_CHARGE_READINESS_SMOKE_PASSED")
            and _env_present("JIEJING_NO_CHARGE_LIVE_DOMAIN_REHEARSAL_EVIDENCE_ID"),
            category="release",
            owner="release_manager",
            evidence_summary=_evidence(
                checkout_return=_env_bool("JIEJING_NO_CHARGE_CHECKOUT_RETURN_URL_SMOKE_PASSED"),
                portal_return=_env_bool("JIEJING_NO_CHARGE_PORTAL_RETURN_URL_SMOKE_PASSED"),
                signed_webhook=_env_bool("JIEJING_NO_CHARGE_SIGNED_WEBHOOK_SMOKE_PASSED"),
                readiness=_env_bool("JIEJING_NO_CHARGE_READINESS_SMOKE_PASSED"),
                evidence_id_present=_env_present("JIEJING_NO_CHARGE_LIVE_DOMAIN_REHEARSAL_EVIDENCE_ID"),
                creates_checkout_session=False,
                triggers_real_charge=False,
            ),
            environment_keys=[
                "JIEJING_NO_CHARGE_CHECKOUT_RETURN_URL_SMOKE_PASSED",
                "JIEJING_NO_CHARGE_PORTAL_RETURN_URL_SMOKE_PASSED",
                "JIEJING_NO_CHARGE_SIGNED_WEBHOOK_SMOKE_PASSED",
                "JIEJING_NO_CHARGE_READINESS_SMOKE_PASSED",
                "JIEJING_NO_CHARGE_LIVE_DOMAIN_REHEARSAL_EVIDENCE_ID",
            ],
            verification=[
                "/commercial/billing-domain-cutover-rehearsal",
                "/billing/checkout-contract",
                "/health",
                "/health/deep",
                "/readiness/product-saas",
            ],
            docs=[
                "https://docs.stripe.com/payments/checkout/build-subscriptions",
                "https://docs.stripe.com/customer-management/integrate-customer-portal",
                "https://docs.stripe.com/webhooks",
            ],
            external_resource_required=False,
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
    provider_cutover_dossier = _provider_cutover_dossier(
        settings=settings,
        rows=rows,
        owner_packet_id=owner_packet_id,
        billing=billing,
        rehearsal=rehearsal,
        approval_packet=approval_packet,
        selected_provider=provider.get("selected") or "not_selected",
    )
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
        "provider_cutover_dossier": provider_cutover_dossier,
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


def _provider_cutover_dossier(
    *,
    settings: SaaSSettings,
    rows: list[dict[str, Any]],
    owner_packet_id: str,
    billing: dict[str, Any],
    rehearsal: dict[str, Any],
    approval_packet: dict[str, Any],
    selected_provider: str,
) -> dict[str, Any]:
    rows_by_key = _by_key(rows)
    sections = [
        _dossier_section(
            "provider_account_and_live_mode",
            "Provider account and live-mode boundary",
            rows_by_key,
            [
                "live_provider_account",
                "stripe_account_activation_go_live_evidence",
                "stripe_live_mode_test_object_isolation",
            ],
        ),
        _dossier_section(
            "product_price_catalog",
            "Products, Prices and plan catalog",
            rows_by_key,
            ["stripe_live_price_catalog"],
        ),
        _dossier_section(
            "checkout_portal_contracts",
            "Subscription Checkout, Portal and stable callback URLs",
            rows_by_key,
            [
                "stripe_subscription_checkout_contract",
                "stripe_customer_portal_contract",
                "stable_domain_billing_callbacks",
            ],
        ),
        _dossier_section(
            "signed_webhook_version_and_failures",
            "Signed webhook, API version and failure paths",
            rows_by_key,
            [
                "stripe_signed_webhook_contract",
                "stripe_api_webhook_version_alignment",
                "stripe_webhook_failure_paths",
            ],
        ),
        _dossier_section(
            "entitlement_quota_and_portal_lifecycle",
            "Entitlement, quota, portal and failed-payment lifecycle",
            rows_by_key,
            [
                "stripe_entitlement_quota_lifecycle",
                "merchant_billing_state_machine_proof",
            ],
        ),
        _dossier_section(
            "billing_ops_customer_trust",
            "Tax, receipt, support and customer communication evidence",
            rows_by_key,
            ["stripe_tax_invoice_receipt_branding_evidence"],
        ),
        _dossier_section(
            "no_charge_rehearsal_and_rollback",
            "No-charge rehearsal, secret scan, smoke and rollback evidence",
            rows_by_key,
            [
                "no_charge_live_domain_rehearsal_packet",
                "cutover_rollback_audit_packet",
            ],
        ),
    ]
    blocked_sections = [section for section in sections if section.get("status") != "ready"]
    blocked_rows = [row for row in rows if row.get("status") != "ready"]
    owner_approval_ready = not blocked_rows and bool(owner_packet_id)
    owner_section = {
        "key": "owner_approval_hold",
        "title": "Owner approval hold",
        "status": "ready" if owner_approval_ready else "blocked",
        "severity": "info" if owner_approval_ready else "blocker",
        "ready_count": 1 if owner_approval_ready else 0,
        "total_count": 1,
        "blocked_keys": [] if owner_approval_ready else ["JIEJING_PAID_LAUNCH_OWNER_APPROVAL_PACKET_ID"],
        "next_action": (
            "Owner approval evidence is recorded; keep launch disabled until the separate deploy-time flag is approved."
            if owner_approval_ready
            else "Attach this provider dossier to a final owner approval record before enabling any public charging."
        ),
        "environment_keys": ["JIEJING_PAID_LAUNCH_OWNER_APPROVAL_PACKET_ID"],
        "source_row_keys": [],
        "external_resource_required": False,
        "customer_visible": False,
        "ordinary_merchant_visible": False,
        "secret_exposed": False,
    }
    sections.append(owner_section)
    if owner_section.get("status") != "ready":
        blocked_sections.append(owner_section)
    ready_count = len(rows) - len(blocked_rows)
    decision = "ready_for_owner_review_not_auto_launch" if owner_approval_ready else "keep_public_paid_launch_blocked"
    next_step = (
        str((blocked_sections[0] if blocked_sections else {}).get("key") or "")
        or "owner_approval_and_deploy_flag_review"
    )
    return {
        "contract_version": "2026-07-02-live-billing-provider-cutover-dossier-v1",
        "mode": "internal_admin_read_only_no_charge_no_checkout",
        "audience": "platform_internal_admin",
        "environment": settings.environment,
        "customer_visible": False,
        "ordinary_merchant_visible": False,
        "merchant_surface_safe": True,
        "status": "ready_for_owner_review" if owner_approval_ready else "blocked",
        "ready_for_owner_review": owner_approval_ready,
        "summary": {
            "decision": decision,
            "selected_provider": selected_provider,
            "ready_count": ready_count,
            "total_count": len(rows),
            "blocked_count": len(blocked_rows),
            "section_count": len(sections),
            "blocked_section_count": len(blocked_sections),
            "blocked_keys": [str(row.get("key") or "") for row in blocked_rows],
            "next_step": next_step,
            "billing_plan_ready_for_paid_launch": bool(billing.get("billing_ready_for_paid_launch")),
            "billing_domain_rehearsal_status": rehearsal.get("status") or "unknown",
            "paid_launch_approval_packet_status": approval_packet.get("status") or "unknown",
            "owner_approval_evidence_recorded": bool(owner_packet_id),
            "public_paid_launch_allowed": False,
            "charge_now_allowed": False,
            "creates_checkout_session": False,
            "calls_stripe_api": False,
            "triggers_real_charge": False,
            "triggers_ebay_oauth": False,
            "triggers_real_platform_write": False,
            "frontend_gets_payment_secret": False,
            "secret_exposed": False,
        },
        "sections": sections,
        "activation_sequence": _provider_activation_sequence(sections),
        "operator_handoff": _provider_operator_handoff(blocked_rows=blocked_rows, owner_approval_ready=owner_approval_ready),
        "forbidden_actions": [
            "Do not create live Checkout Sessions from this dossier.",
            "Do not enable public paid launch from this dossier alone.",
            "Do not call Stripe APIs while building this evidence packet.",
            "Do not expose Stripe secret keys, webhook secrets, customer IDs, payment method IDs or raw tokens to the frontend.",
            "Do not run or repeat eBay OAuth as part of billing cutover.",
            "Do not grant quota until signed webhook events are proven and owner approval is recorded.",
        ],
        "safety": _provider_cutover_dossier_safety_flags(),
        "download_allowed_for_internal_admin": True,
        "public_paid_launch_allowed": False,
        "charge_now_allowed": False,
        "creates_checkout_session": False,
        "calls_stripe_api": False,
        "triggers_real_charge": False,
        "triggers_ebay_oauth": False,
        "repeat_ebay_oauth_allowed": False,
        "triggers_real_platform_write": False,
        "platform_write_now_allowed": False,
        "frontend_gets_payment_secret": False,
        "frontend_gets_provider_secret": False,
        "exports_raw_secret": False,
        "includes_raw_tokens": False,
        "secret_exposed": False,
    }


def _dossier_section(
    key: str,
    title: str,
    rows_by_key: dict[str, dict[str, Any]],
    source_keys: list[str],
) -> dict[str, Any]:
    rows = [rows_by_key.get(source_key) or {} for source_key in source_keys]
    ready_rows = [row for row in rows if row.get("status") == "ready"]
    blocked_rows = [row for row in rows if row.get("status") != "ready"]
    environment_keys = sorted(
        {
            str(value)
            for row in rows
            for value in (row.get("environment_keys") if isinstance(row.get("environment_keys"), list) else [])
            if value
        }
    )
    docs = sorted(
        {
            str(value)
            for row in rows
            for value in (row.get("docs") if isinstance(row.get("docs"), list) else [])
            if value
        }
    )
    return {
        "key": key,
        "title": title,
        "status": "ready" if not blocked_rows else "blocked",
        "severity": "info" if not blocked_rows else "blocker",
        "ready_count": len(ready_rows),
        "total_count": len(rows),
        "blocked_keys": [str(row.get("key") or "") for row in blocked_rows],
        "source_row_keys": source_keys,
        "next_action": (
            str(blocked_rows[0].get("next_action") or "Record the required backend-only evidence before owner review.")
            if blocked_rows
            else "Evidence section is ready; keep the no-charge boundary until owner approval."
        ),
        "evidence_summary": "; ".join(
            f"{row.get('key') or 'unknown'}={row.get('status') or 'unknown'}" for row in rows
        )[:900],
        "environment_keys": environment_keys,
        "docs": docs,
        "external_resource_required": any(bool(row.get("external_resource_required")) for row in rows),
        "customer_visible": False,
        "ordinary_merchant_visible": False,
        "exports_raw_secret": False,
        "includes_raw_tokens": False,
        "creates_checkout_session": False,
        "calls_stripe_api": False,
        "triggers_real_charge": False,
        "charge_now_allowed": False,
        "triggers_ebay_oauth": False,
        "repeat_ebay_oauth_allowed": False,
        "triggers_real_platform_write": False,
        "frontend_gets_payment_secret": False,
        "secret_exposed": False,
    }


def _provider_activation_sequence(sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_key = {str(section.get("key") or ""): section for section in sections}
    sequence = [
        ("freeze_current_private_beta_boundary", "Freeze current private-beta billing and no-write boundary", ["provider_account_and_live_mode"]),
        ("verify_live_catalog_and_callbacks", "Verify live plan catalog, Checkout, Portal and stable callbacks", ["product_price_catalog", "checkout_portal_contracts"]),
        ("prove_signed_webhook_lifecycle", "Prove signed webhook version, duplicate, delayed and out-of-order lifecycle", ["signed_webhook_version_and_failures", "entitlement_quota_and_portal_lifecycle"]),
        ("review_customer_billing_trust", "Review receipts, support contact, tax and customer billing communication", ["billing_ops_customer_trust"]),
        ("run_no_charge_rehearsal_and_rollback", "Run no-charge live-domain rehearsal and rollback packet", ["no_charge_rehearsal_and_rollback"]),
        ("record_owner_approval_hold", "Record owner approval and keep deploy-time charge flag separate", ["owner_approval_hold"]),
    ]
    output: list[dict[str, Any]] = []
    for key, title, required_sections in sequence:
        missing = [section_key for section_key in required_sections if (by_key.get(section_key) or {}).get("status") != "ready"]
        output.append(
            {
                "key": key,
                "title": title,
                "status": "ready" if not missing else "blocked",
                "blocked_sections": missing,
                "required_sections": required_sections,
                "creates_checkout_session": False,
                "calls_stripe_api": False,
                "triggers_real_charge": False,
                "charge_now_allowed": False,
                "triggers_ebay_oauth": False,
                "triggers_real_platform_write": False,
                "frontend_gets_payment_secret": False,
                "secret_exposed": False,
            }
        )
    return output


def _provider_operator_handoff(*, blocked_rows: list[dict[str, Any]], owner_approval_ready: bool) -> dict[str, Any]:
    external_rows = [row for row in blocked_rows if row.get("external_resource_required")]
    internal_rows = [row for row in blocked_rows if not row.get("external_resource_required")]
    return {
        "status": "ready_for_owner_review" if owner_approval_ready else "blocked",
        "external_console_actions": [_handoff_action(row, "external_console") for row in external_rows[:10]],
        "internal_evidence_actions": [_handoff_action(row, "internal_evidence") for row in internal_rows[:10]],
        "next_action": (
            "Owner approval is recorded; review deploy-time feature flags separately before charging."
            if owner_approval_ready
            else (str(blocked_rows[0].get("next_action") or "Finish provider evidence before owner approval.") if blocked_rows else "Record owner approval evidence.")
        ),
        "customer_visible": False,
        "ordinary_merchant_visible": False,
        "secret_exposed": False,
    }


def _handoff_action(row: dict[str, Any], source: str) -> dict[str, Any]:
    return {
        "key": str(row.get("key") or source)[:140],
        "title": str(row.get("title") or row.get("key") or source)[:220],
        "status": str(row.get("status") or "blocked")[:80],
        "source": source,
        "next_action": str(row.get("next_action") or "Record required evidence.")[:720],
        "environment_keys": [str(value)[:160] for value in (row.get("environment_keys") if isinstance(row.get("environment_keys"), list) else [])],
        "verification": [str(value)[:220] for value in (row.get("verification") if isinstance(row.get("verification"), list) else [])],
        "customer_visible": False,
        "ordinary_merchant_visible": False,
        "secret_exposed": False,
    }


def _provider_cutover_dossier_safety_flags() -> dict[str, bool]:
    return {
        "read_only": True,
        "platform_internal_admin_only": True,
        "customer_visible": False,
        "ordinary_merchant_visible": False,
        "merchant_surface_safe": True,
        "download_allowed_for_internal_admin": True,
        "exports_database": False,
        "exports_raw_secret": False,
        "includes_raw_tokens": False,
        "includes_payment_secret": False,
        "reads_env_secret_values": False,
        "calls_stripe_api": False,
        "creates_checkout_session": False,
        "triggers_real_charge": False,
        "charge_now_allowed": False,
        "triggers_ebay_oauth": False,
        "repeat_ebay_oauth_allowed": False,
        "triggers_real_platform_write": False,
        "platform_write_now_allowed": False,
        "frontend_gets_payment_secret": False,
        "frontend_gets_provider_secret": False,
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
