"""No-charge Stripe billing and stable-domain cutover rehearsal contract."""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlparse

from .billing_checkout import STRIPE_API_VERSION, build_billing_checkout_contract
from .billing_plan import STRIPE_CURRENT_API_VERSION, build_billing_plan, stripe_webhook_api_version, stripe_webhook_api_version_aligned
from .billing_webhook import build_billing_provider_contract
from .config import SaaSSettings
from .domain_readiness import build_domain_readiness
from .repository import SaaSRepository


REQUIRED_STRIPE_EVENTS = {
    "checkout.session.completed",
    "customer.subscription.created",
    "customer.subscription.updated",
    "customer.subscription.deleted",
    "invoice.paid",
    "invoice.payment_failed",
}


def build_billing_domain_cutover_rehearsal(settings: SaaSSettings, repository: SaaSRepository) -> dict[str, Any]:
    """Build a public-launch rehearsal packet without creating payment sessions."""

    billing = build_billing_plan(settings, repository)
    domain = build_domain_readiness(settings)
    checkout = build_billing_checkout_contract()
    provider_contract = build_billing_provider_contract()
    counts = repository.system_counts()
    stable_host = str(domain.get("stable_domain") or "").strip().lower()
    stages = _rehearsal_stages(
        billing=billing,
        domain=domain,
        checkout=checkout,
        provider_contract=provider_contract,
        counts=counts,
        stable_host=stable_host,
    )
    blocked = [stage for stage in stages if stage.get("status") != "ready"]
    next_stage = blocked[0] if blocked else {}
    return {
        "contract_version": "2026-06-18-stripe-domain-cutover-rehearsal",
        "mode": "dry_run_no_charge",
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
        "payment_provider_secret_boundary": "backend_env_or_vault_only",
        "stable_domain": stable_host,
        "required_urls": _required_urls(stable_host),
        "summary": {
            "ready_count": len(stages) - len(blocked),
            "total_count": len(stages),
            "blocked_count": len(blocked),
            "blocked_keys": [str(stage.get("key") or "") for stage in blocked],
            "next_step": str(next_stage.get("key") or ""),
            "next_action": str(next_stage.get("next_action") or ""),
            "billing_provider": ((billing.get("provider") or {}).get("selected") if isinstance(billing.get("provider"), dict) else "") or "not_selected",
            "domain_ready": bool(domain.get("production_domain_ready")),
            "stripe_api_version": STRIPE_API_VERSION,
            "subscription_records": int(counts.get("billing_subscriptions") or 0),
            "webhook_event_records": int(counts.get("billing_webhook_events") or 0),
        },
        "stages": stages,
        "rollback_controls": [
            "keep_manual_seed_private_beta_until_owner_approval",
            "do_not_enable_public_checkout_until_stable_domain_and_webhook_smoke_pass",
            "disable_JIEJING_BILLING_PROVIDER_or_quota_flags_if_webhook_or_checkout_smoke_fails",
            "keep_real_ebay_writes_confirmation_gated_after_billing_cutover",
        ],
        "evidence_to_record": [
            "billing_domain_cutover_rehearsal_json",
            "billing_checkout_contract_json",
            "billing_provider_contract_json",
            "domain_status_json",
            "stripe_webhook_endpoint_api_version",
            "signed_webhook_test_output",
            "quota_hard_stop_test_output",
            "browser_smoke_output",
            "secret_scan_output",
        ],
        "docs": [
            "https://docs.stripe.com/api/versioning",
            "https://docs.stripe.com/billing/quickstart",
            "https://docs.stripe.com/webhooks",
            "https://docs.stripe.com/customer-management/integrate-customer-portal",
            "https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/routing-to-tunnel/dns/",
            "https://developer.ebay.com/develop/guides-v2/authorization",
        ],
        "secret_exposed": False,
    }


def _rehearsal_stages(
    *,
    billing: dict[str, Any],
    domain: dict[str, Any],
    checkout: dict[str, Any],
    provider_contract: dict[str, Any],
    counts: dict[str, int],
    stable_host: str,
) -> list[dict[str, Any]]:
    provider = billing.get("provider") if isinstance(billing.get("provider"), dict) else {}
    quota = billing.get("quota_contract") if isinstance(billing.get("quota_contract"), dict) else {}
    checkout_sessions = checkout.get("checkout_sessions") if isinstance(checkout.get("checkout_sessions"), dict) else {}
    customer_portal = checkout.get("customer_portal") if isinstance(checkout.get("customer_portal"), dict) else {}
    plan_ids = provider_contract.get("plan_ids") if isinstance(provider_contract.get("plan_ids"), dict) else {}
    event_types = set(provider_contract.get("webhook_event_types") or [])
    billing_ready = bool(billing.get("billing_ready_for_paid_launch"))
    lifecycle_flags = [
        "JIEJING_STRIPE_CUSTOMER_PORTAL_TESTED",
        "JIEJING_STRIPE_SUBSCRIPTION_CANCEL_TESTED",
        "JIEJING_STRIPE_INVOICE_PAID_TESTED",
        "JIEJING_STRIPE_PAYMENT_FAILURE_TESTED",
    ]
    webhook_resilience_flags = [
        "JIEJING_STRIPE_WEBHOOK_DUPLICATE_TESTED",
        "JIEJING_STRIPE_WEBHOOK_DELAYED_TESTED",
        "JIEJING_STRIPE_WEBHOOK_OUT_OF_ORDER_TESTED",
    ]
    rollback_flags = [
        "JIEJING_CUTOVER_ROLLBACK_VERIFIED",
        "JIEJING_SECRET_SCAN_PASSED",
        "JIEJING_READINESS_SNAPSHOT_RECORDED",
        "JIEJING_BROWSER_SMOKE_PASSED",
    ]
    return [
        _stage(
            "stripe_live_provider_selected",
            "Stripe live provider is selected",
            provider.get("selected") == "stripe" and bool(provider.get("external_paid_provider_configured")) and bool(provider_contract.get("api_key_configured")),
            category="billing",
            owner="platform_ops",
            evidence_summary=_evidence(provider=provider.get("selected") or "not_selected", api_key_configured=bool(provider_contract.get("api_key_configured"))),
            next_action="Set JIEJING_BILLING_PROVIDER=stripe and keep the Stripe secret key backend-only.",
            environment_keys=["JIEJING_BILLING_PROVIDER", "JIEJING_STRIPE_SECRET_KEY"],
            docs=["https://docs.stripe.com/billing/quickstart"],
        ),
        _stage(
            "stripe_live_price_ids_verified",
            "Live product and Price IDs are verified",
            bool(_env_bool("JIEJING_BILLING_PLANS_PUBLISHED"))
            and all(bool(plan_ids.get(key)) for key in ("starter", "operator", "team"))
            and all(_env_bool(name) for name in ("JIEJING_STRIPE_LIVE_PRODUCTS_VERIFIED", "JIEJING_STRIPE_LIVE_PRICES_VERIFIED", "JIEJING_STRIPE_NO_TEST_OBJECTS_IN_LIVE_CONFIG")),
            category="billing",
            owner="commercial_ops",
            evidence_summary=_evidence(plans_published=_env_bool("JIEJING_BILLING_PLANS_PUBLISHED"), starter=bool(plan_ids.get("starter")), operator=bool(plan_ids.get("operator")), team=bool(plan_ids.get("team"))),
            next_action="Publish live Starter, Operator and Team Price IDs and verify no sandbox/test objects remain in live config.",
            environment_keys=[
                "JIEJING_BILLING_PLANS_PUBLISHED",
                "JIEJING_STRIPE_PRICE_STARTER_ID",
                "JIEJING_STRIPE_PRICE_OPERATOR_ID",
                "JIEJING_STRIPE_PRICE_TEAM_ID",
                "JIEJING_STRIPE_LIVE_PRODUCTS_VERIFIED",
                "JIEJING_STRIPE_LIVE_PRICES_VERIFIED",
                "JIEJING_STRIPE_NO_TEST_OBJECTS_IN_LIVE_CONFIG",
            ],
            docs=["https://docs.stripe.com/billing/quickstart"],
        ),
        _stage(
            "stable_domain_dns_tls_headers",
            "Stable domain, DNS, TLS and security headers are verified",
            bool(domain.get("production_domain_ready")),
            category="domain",
            owner="platform_ops",
            evidence_summary=_evidence(domain=stable_host or "not_selected", dns=bool(domain.get("dns_verified")), tls=bool(domain.get("tls_verified")), headers=bool(domain.get("security_headers_verified"))),
            next_action="Point the stable hostname at the tunnel/edge, verify TLS, deployment hardening and security headers.",
            environment_keys=[
                "JIEJING_PUBLIC_BASE_URL",
                "JIEJING_STABLE_DOMAIN",
                "JIEJING_DOMAIN_DNS_VERIFIED",
                "JIEJING_TLS_VERIFIED",
                "JIEJING_DEPLOYMENT_HARDENED",
                "JIEJING_SECURITY_HEADERS_VERIFIED",
            ],
            docs=["https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/routing-to-tunnel/dns/"],
        ),
        _stage(
            "stripe_checkout_return_urls_on_stable_domain",
            "Checkout success and cancel URLs use the stable domain",
            bool(checkout_sessions.get("ready")) and _url_on_stable_domain(_success_url(), stable_host) and _url_on_stable_domain(_cancel_url(), stable_host),
            category="billing_domain",
            owner="platform_ops",
            evidence_summary=_evidence(success=_url_status(_success_url(), stable_host), cancel=_url_status(_cancel_url(), stable_host), checkout_ready=bool(checkout_sessions.get("ready"))),
            next_action="Set Checkout success/cancel URLs to the stable HTTPS origin before public checkout is enabled.",
            environment_keys=["JIEJING_BILLING_SUCCESS_URL", "JIEJING_BILLING_CANCEL_URL"],
            docs=["https://docs.stripe.com/api/checkout/sessions/create"],
        ),
        _stage(
            "stripe_customer_portal_return_url_on_stable_domain",
            "Customer Portal return URL uses the stable domain",
            bool(customer_portal.get("ready")) and _url_on_stable_domain(_portal_return_url(), stable_host),
            category="billing_domain",
            owner="platform_ops",
            evidence_summary=_evidence(portal=_url_status(_portal_return_url(), stable_host), portal_ready=bool(customer_portal.get("ready"))),
            next_action="Set Customer Portal return URL to the stable HTTPS settings/billing route.",
            environment_keys=["JIEJING_BILLING_PORTAL_RETURN_URL"],
            docs=["https://docs.stripe.com/customer-management/integrate-customer-portal"],
        ),
        _stage(
            "stripe_signed_webhook_on_stable_domain",
            "Signed Stripe webhook uses the stable domain and required events",
            bool(provider_contract.get("webhook_configured"))
            and _url_on_stable_domain(_webhook_url(), stable_host)
            and REQUIRED_STRIPE_EVENTS.issubset(event_types),
            category="billing_domain",
            owner="platform_ops",
            evidence_summary=_evidence(webhook=_url_status(_webhook_url(), stable_host), signed=bool(provider_contract.get("webhook_configured")), required_events=REQUIRED_STRIPE_EVENTS.issubset(event_types)),
            next_action="Register the live Stripe webhook endpoint on the stable HTTPS domain with subscription and invoice events.",
            environment_keys=["JIEJING_BILLING_WEBHOOK_URL", "JIEJING_STRIPE_WEBHOOK_SECRET"],
            docs=["https://docs.stripe.com/webhooks", "https://docs.stripe.com/webhooks/signature"],
        ),
        _stage(
            "stripe_api_webhook_version_pinned",
            "Stripe API and webhook endpoint versions are pinned",
            STRIPE_API_VERSION == STRIPE_CURRENT_API_VERSION and checkout.get("stripe_api_version") == STRIPE_CURRENT_API_VERSION and stripe_webhook_api_version_aligned(),
            category="billing",
            owner="platform_ops",
            evidence_summary=_evidence(
                request_api_version=checkout.get("stripe_api_version") or "missing",
                expected=STRIPE_CURRENT_API_VERSION,
                recorded_webhook_api_version=stripe_webhook_api_version() or "missing",
                webhook_version_verified=_env_bool("JIEJING_STRIPE_WEBHOOK_API_VERSION_VERIFIED"),
                webhook_version_aligned=stripe_webhook_api_version() == STRIPE_CURRENT_API_VERSION,
            ),
            next_action="Pin backend Stripe-Version and record the live webhook endpoint API version metadata.",
            environment_keys=["JIEJING_STRIPE_WEBHOOK_API_VERSION", "JIEJING_STRIPE_WEBHOOK_API_VERSION_VERIFIED"],
            docs=["https://docs.stripe.com/api/versioning"],
        ),
        _stage(
            "stripe_webhook_resilience_rehearsed",
            "Webhook duplicate, delayed and out-of-order handling is rehearsed",
            bool(provider_contract.get("webhook_configured")) and all(_env_bool(name) for name in webhook_resilience_flags),
            category="billing",
            owner="platform_ops",
            evidence_summary=_evidence(duplicate=_env_bool(webhook_resilience_flags[0]), delayed=_env_bool(webhook_resilience_flags[1]), out_of_order=_env_bool(webhook_resilience_flags[2])),
            next_action="Run signed webhook tests for duplicate, delayed and out-of-order events before charging merchants.",
            environment_keys=webhook_resilience_flags,
            docs=["https://docs.stripe.com/webhooks"],
        ),
        _stage(
            "subscription_state_and_quota_lifecycle_rehearsed",
            "Subscription state, failed payment and quota hard-stop are rehearsed",
            billing_ready
            and bool(quota.get("enabled"))
            and all(_env_bool(name) for name in lifecycle_flags)
            and (int(counts.get("billing_subscriptions") or 0) > 0 or _env_bool("JIEJING_STRIPE_SUBSCRIPTION_STATE_PERSISTENCE_TESTED"))
            and (int(counts.get("billing_webhook_events") or 0) > 0 or _env_bool("JIEJING_STRIPE_SUBSCRIPTION_STATE_PERSISTENCE_TESTED")),
            category="entitlement",
            owner="platform_ops",
            evidence_summary=_evidence(subscriptions=int(counts.get("billing_subscriptions") or 0), webhook_events=int(counts.get("billing_webhook_events") or 0), quota=bool(quota.get("enabled")), payment_failure=_env_bool("JIEJING_STRIPE_PAYMENT_FAILURE_TESTED")),
            next_action="Verify active subscription provisioning, cancellation, invoice.paid, payment failure, and quota hard-stop behavior.",
            environment_keys=["JIEJING_QUOTA_ENFORCEMENT_ENABLED", "JIEJING_STRIPE_SUBSCRIPTION_STATE_PERSISTENCE_TESTED", *lifecycle_flags],
            docs=["https://docs.stripe.com/customer-management/integrate-customer-portal"],
        ),
        _stage(
            "cutover_rollback_audit_packet_recorded",
            "Rollback, readiness, smoke and secret-scan evidence is recorded",
            all(_env_bool(name) for name in rollback_flags),
            category="release",
            owner="release_manager",
            evidence_summary=_evidence(rollback=_env_bool(rollback_flags[0]), secret_scan=_env_bool(rollback_flags[1]), readiness=_env_bool(rollback_flags[2]), browser_smoke=_env_bool(rollback_flags[3])),
            next_action="Record rollback plan, secret scan, readiness snapshots and browser smoke before owner approval.",
            environment_keys=rollback_flags,
            docs=["https://docs.stripe.com/get-started/checklist/go-live"],
            external_resource_required=False,
        ),
    ]


def _stage(
    key: str,
    title: str,
    ready: bool,
    *,
    category: str,
    owner: str,
    evidence_summary: str,
    next_action: str,
    environment_keys: list[str],
    docs: list[str],
    external_resource_required: bool = True,
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
        "environment_keys": environment_keys,
        "verification": ["/commercial/billing-domain-cutover-rehearsal", "/billing/plans", "/billing/checkout-contract", "/domain/status"],
        "docs": docs,
        "external_resource_required": external_resource_required,
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


def _required_urls(stable_host: str) -> dict[str, Any]:
    return {
        "stable_origin": f"https://{stable_host}" if stable_host else "",
        "stripe_success_url": _public_url_shape(_success_url()),
        "stripe_cancel_url": _public_url_shape(_cancel_url()),
        "stripe_portal_return_url": _public_url_shape(_portal_return_url()),
        "stripe_webhook_url": _public_url_shape(_webhook_url()),
        "ebay_oauth_callback_url": f"https://{stable_host}/oauth/ebay/callback" if stable_host else "",
        "secret_exposed": False,
    }


def _url_on_stable_domain(value: str, stable_host: str) -> bool:
    parsed = urlparse(value or "")
    return bool(stable_host and parsed.scheme == "https" and (parsed.hostname or "").lower() == stable_host)


def _url_status(value: str, stable_host: str) -> str:
    if not value:
        return "missing"
    parsed = urlparse(value)
    if parsed.scheme != "https":
        return "not_https"
    host = (parsed.hostname or "").lower()
    if not host:
        return "host_missing"
    if stable_host and host == stable_host:
        return "stable_domain_aligned"
    return f"host={host or 'missing'}"


def _public_url_shape(value: str) -> dict[str, str | bool]:
    parsed = urlparse(value or "")
    return {
        "configured": bool(value),
        "scheme": parsed.scheme or "",
        "host": (parsed.hostname or "").lower(),
        "path": parsed.path or "",
        "query_returned": False,
        "secret_exposed": False,
    }


def _success_url() -> str:
    return _first_env("JIEJING_BILLING_SUCCESS_URL", "JIEJING_STRIPE_SUCCESS_URL")


def _cancel_url() -> str:
    return _first_env("JIEJING_BILLING_CANCEL_URL", "JIEJING_STRIPE_CANCEL_URL")


def _portal_return_url() -> str:
    return _first_env("JIEJING_BILLING_PORTAL_RETURN_URL", "JIEJING_STRIPE_PORTAL_RETURN_URL")


def _webhook_url() -> str:
    return _first_env("JIEJING_BILLING_WEBHOOK_URL")


def _first_env(*names: str) -> str:
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return ""


def _env_bool(name: str) -> bool:
    return str(os.environ.get(name) or "").strip().lower() in {"1", "true", "yes", "on"}


def _evidence(**values: Any) -> str:
    return "; ".join(f"{key}={value}" for key, value in values.items())
