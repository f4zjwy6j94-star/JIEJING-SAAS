"""Stable domain, DNS, TLS, callback, and CORS readiness for public launch."""

from __future__ import annotations

import os
import re
from typing import Any
from urllib.parse import urlparse

from .config import SaaSSettings


TEMP_HOST_PATTERNS = (
    r"\.trycloudflare\.com$",
    r"\.nip\.io$",
    r"\.sslip\.io$",
    r"^localhost$",
    r"^127\.",
    r"^\d+\.\d+\.\d+\.\d+$",
)

DOMAIN_REGISTRATION_READY_STATUSES = {
    "registered",
    "purchased",
    "active",
    "normal",
    "ok",
    "approved",
    "owner_verified",
    "dns_ready",
}

DOMAIN_PAYMENT_CONFIRMED_STATUSES = DOMAIN_REGISTRATION_READY_STATUSES | {
    "paid",
    "payment_success",
    "order_paid",
    "paid_registry_name_review",
    "registry_name_review_pending",
    "name_review_pending",
    "domain_name_review_pending",
    "naming_review_pending",
}

DOMAIN_REVIEW_PENDING_STATUSES = {
    "realname_template_review",
    "registry_name_review_pending",
    "name_review_pending",
    "domain_name_review_pending",
    "naming_review_pending",
    "paid_registry_name_review",
}


def build_domain_readiness(settings: SaaSSettings) -> dict[str, Any]:
    public_base_url = _first_env("JIEJING_PUBLIC_BASE_URL", "JIEJING_CANONICAL_URL", "PUBLIC_BASE_URL")
    stable_domain = _first_env("JIEJING_STABLE_DOMAIN", "JIEJING_EDGE_DOMAIN", "JIEJING_PUBLIC_DOMAIN")
    selected_domain = _normalize_domain(_first_env("JIEJING_SELECTED_DOMAIN", "JIEJING_ROOT_DOMAIN", "JIEJING_PENDING_DOMAIN"))
    registration_status = _registration_status()
    parsed = urlparse(public_base_url if "://" in public_base_url else f"https://{public_base_url}" if public_base_url else "")
    host = parsed.hostname or stable_domain
    scheme = parsed.scheme or ("https" if host else "")
    dns_verified = _env_bool("JIEJING_DOMAIN_DNS_VERIFIED")
    tls_verified = _env_bool("JIEJING_TLS_VERIFIED")
    callback_verified = _env_bool("JIEJING_EBAY_CALLBACK_VERIFIED")
    deployment_hardened = _env_bool("JIEJING_DEPLOYMENT_HARDENED")
    security_headers_verified = _env_bool("JIEJING_SECURITY_HEADERS_VERIFIED")
    cors_aligned = _cors_contains_host(settings.cors_origin, host)
    stable_host = bool(host and not _is_temp_host(host))
    https_only = scheme == "https"
    domain_registered = _domain_registered(registration_status=registration_status, dns_verified=dns_verified, tls_verified=tls_verified)
    domain_payment_confirmed = _domain_payment_confirmed(registration_status=registration_status)
    registration_review_pending = _registration_review_pending(registration_status=registration_status)
    target_app_host = _target_app_host(selected_domain=selected_domain, current_host=host, stable_host=stable_host)
    callback_host = host if stable_host else target_app_host
    blockers: list[str] = []
    if not host:
        blockers.append("stable_domain_not_selected")
    elif not stable_host:
        blockers.append("stable_domain_uses_temporary_or_ip_host")
    if registration_review_pending:
        blockers.append("domain_registry_name_review_pending")
    if selected_domain and not domain_registered:
        blockers.append("domain_registration_not_confirmed")
    if not dns_verified:
        blockers.append("domain_dns_not_verified")
    if not https_only or not tls_verified:
        blockers.append("domain_tls_not_verified")
    if not callback_verified:
        blockers.append("ebay_callback_domain_not_verified")
    if not cors_aligned:
        blockers.append("cors_origin_not_aligned_with_stable_domain")
    if not deployment_hardened:
        blockers.append("deployment_hardening_not_verified")
    if not security_headers_verified:
        blockers.append("security_headers_not_verified")
    return {
        "contract_version": "2026-05-26-stable-domain-launch-gate",
        "environment": settings.environment,
        "public_base_url_configured": bool(public_base_url),
        "selected_root_domain": selected_domain,
        "domain_registration_status": registration_status,
        "domain_payment_confirmed": domain_payment_confirmed,
        "domain_registration_review_pending": registration_review_pending,
        "domain_registered": domain_registered,
        "stable_domain": _public_host(host),
        "target_app_host": target_app_host,
        "target_marketing_host": selected_domain,
        "target_api_host": f"api.{selected_domain}" if selected_domain else "",
        "stable_host": stable_host,
        "https_only": https_only,
        "dns_verified": dns_verified,
        "tls_verified": tls_verified,
        "ebay_callback_verified": callback_verified,
        "cors_origin_aligned": cors_aligned,
        "deployment_hardened": deployment_hardened,
        "security_headers_verified": security_headers_verified,
        "production_domain_ready": settings.is_production_like and not blockers,
        "required_callback_url": f"https://{callback_host}/oauth/ebay/callback" if callback_host else "",
        "recommended_urls": _recommended_urls(selected_domain=selected_domain, app_host=target_app_host),
        "recommended_dns_records": _recommended_dns_records(selected_domain=selected_domain),
        "external_console_steps": _external_console_steps(
            selected_domain=selected_domain,
            registration_status=registration_status,
            domain_payment_confirmed=domain_payment_confirmed,
            registration_review_pending=registration_review_pending,
        ),
        "blockers": blockers,
        "next_actions": _next_actions(blockers),
        "raw_dns_provider_secret_exposed": False,
        "secret_exposed": False,
    }


def _next_actions(blockers: list[str]) -> list[str]:
    actions = []
    if "domain_registry_name_review_pending" in blockers:
        actions.append("wait_for_registry_name_review_then_verify_domain_active")
    elif "domain_registration_not_confirmed" in blockers:
        actions.append("complete_domain_realname_review_purchase_order_and_record_domain_registered")
    if "stable_domain_not_selected" in blockers or "stable_domain_uses_temporary_or_ip_host" in blockers:
        actions.append("choose_app_domain_and_set_JIEJING_PUBLIC_BASE_URL")
    if "domain_dns_not_verified" in blockers:
        actions.append("point_domain_dns_to_edge_or_load_balancer_and_record_JIEJING_DOMAIN_DNS_VERIFIED")
    if "domain_tls_not_verified" in blockers:
        actions.append("verify_https_certificate_and_record_JIEJING_TLS_VERIFIED")
    if "ebay_callback_domain_not_verified" in blockers:
        actions.append("update_ebay_RuName_callback_to_stable_domain_and_record_JIEJING_EBAY_CALLBACK_VERIFIED")
    if "cors_origin_not_aligned_with_stable_domain" in blockers:
        actions.append("set_JIEJING_CORS_ORIGIN_to_the_stable_https_origin")
    if "deployment_hardening_not_verified" in blockers:
        actions.append("verify_host_allowlist_container_restart_policy_and_no_demo_bootstrap")
    if "security_headers_not_verified" in blockers:
        actions.append("verify_CSP_HSTS_frame_options_referrer_policy_and_permissions_policy")
    return actions or ["keep_domain_tls_callback_and_security_headers_monitored"]


def _cors_contains_host(cors_origin: str, host: str) -> bool:
    if not host:
        return False
    allowed = [item.strip() for item in str(cors_origin or "").split(",") if item.strip()]
    if "*" in allowed:
        return False
    expected = f"https://{host}"
    return expected in allowed


def _is_temp_host(host: str) -> bool:
    value = str(host or "").strip().lower()
    return any(re.search(pattern, value) for pattern in TEMP_HOST_PATTERNS)


def _public_host(host: str) -> str:
    return str(host or "").strip().lower()


def _normalize_domain(value: str) -> str:
    text = _public_host(value).strip("/")
    if not text:
        return ""
    if "://" in text:
        return _public_host(urlparse(text).hostname or "")
    return text.split("/", 1)[0]


def _registration_status() -> str:
    status = _public_host(_first_env("JIEJING_DOMAIN_REGISTRATION_STATUS", "JIEJING_DOMAIN_PURCHASE_STATUS"))
    if status:
        return status
    if _env_bool("JIEJING_DOMAIN_REGISTERED") or _env_bool("JIEJING_DOMAIN_PURCHASED"):
        return "registered"
    return "not_recorded"


def _domain_registered(*, registration_status: str, dns_verified: bool, tls_verified: bool) -> bool:
    if registration_status in DOMAIN_REVIEW_PENDING_STATUSES:
        return False
    return (
        registration_status in DOMAIN_REGISTRATION_READY_STATUSES
        or _env_bool("JIEJING_DOMAIN_REGISTERED")
        or dns_verified
        or tls_verified
    )


def _domain_payment_confirmed(*, registration_status: str) -> bool:
    return registration_status in DOMAIN_PAYMENT_CONFIRMED_STATUSES or _env_bool("JIEJING_DOMAIN_PAYMENT_CONFIRMED") or _env_bool("JIEJING_DOMAIN_PURCHASED")


def _registration_review_pending(*, registration_status: str) -> bool:
    return registration_status in DOMAIN_REVIEW_PENDING_STATUSES


def _target_app_host(*, selected_domain: str, current_host: str, stable_host: bool) -> str:
    explicit = _normalize_domain(_first_env("JIEJING_TARGET_APP_HOST", "JIEJING_APP_HOST"))
    if explicit:
        return explicit
    if selected_domain:
        return f"app.{selected_domain}"
    if stable_host:
        return _public_host(current_host)
    return ""


def _recommended_urls(*, selected_domain: str, app_host: str) -> dict[str, str | bool]:
    return {
        "marketing_home": f"https://{selected_domain}" if selected_domain else "",
        "app_home": f"https://{app_host}" if app_host else "",
        "api_base_reserved": f"https://api.{selected_domain}" if selected_domain else "",
        "ebay_oauth_callback": f"https://{app_host}/oauth/ebay/callback" if app_host else "",
        "stripe_checkout_success": f"https://{app_host}/billing/success" if app_host else "",
        "stripe_checkout_cancel": f"https://{app_host}/billing/cancel" if app_host else "",
        "stripe_portal_return": f"https://{app_host}/settings/billing" if app_host else "",
        "stripe_webhook": f"https://{app_host}/billing/webhook" if app_host else "",
        "secret_exposed": False,
    }


def _recommended_dns_records(*, selected_domain: str) -> list[dict[str, str | bool]]:
    if not selected_domain:
        return []
    return [
        {
            "name": "@",
            "type": "proxied_A_or_CNAME",
            "target": "cloudflare_proxied_A_to_43.129.205.244_or_CNAME_to_app_host",
            "purpose": "marketing_or_redirect_entry",
            "configure_now": False,
            "secret_exposed": False,
        },
        {
            "name": "app",
            "type": "CNAME",
            "target": "cloudflare_tunnel_or_tencent_edge_cname_after_domain_purchase",
            "purpose": "merchant_workbench_primary_origin",
            "configure_now": False,
            "secret_exposed": False,
        },
        {
            "name": "api",
            "type": "CNAME",
            "target": "reserved_for_future_api_edge_if_split_from_app",
            "purpose": "future_backend_api_boundary",
            "configure_now": False,
            "secret_exposed": False,
        },
    ]


def _external_console_steps(
    *,
    selected_domain: str,
    registration_status: str,
    domain_payment_confirmed: bool,
    registration_review_pending: bool,
) -> list[dict[str, str | bool]]:
    domain_label = selected_domain or "selected domain"
    return [
        {
            "key": "finish_realname_template_review",
            "title": f"Finish real-name template review for {domain_label}",
            "status": "done_or_not_applicable" if domain_payment_confirmed else "operator_required",
            "can_do_before_purchase": True,
            "secret_exposed": False,
        },
        {
            "key": "purchase_domain_and_enable_auto_renew",
            "title": f"Purchase {domain_label} and enable auto-renew",
            "status": "payment_confirmed" if domain_payment_confirmed else "operator_required",
            "can_do_before_purchase": False,
            "secret_exposed": False,
        },
        {
            "key": "wait_registry_name_review",
            "title": f"Wait for registry name review to activate {domain_label}",
            "status": "waiting_registry" if registration_review_pending else registration_status or "not_recorded",
            "can_do_before_purchase": False,
            "secret_exposed": False,
        },
        {
            "key": "choose_edge_provider",
            "title": "Choose Cloudflare or Tencent EdgeOne/WAF before final DNS cutover",
            "status": "operator_required",
            "can_do_before_purchase": True,
            "secret_exposed": False,
        },
        {
            "key": "prepare_callback_urls",
            "title": "Prepare eBay and Stripe callback URLs; do not activate them until DNS/TLS pass",
            "status": "agent_preparable_operator_confirms_later",
            "can_do_before_purchase": True,
            "secret_exposed": False,
        },
    ]


def _first_env(*names: str) -> str:
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return ""


def _env_bool(name: str) -> bool:
    return str(os.environ.get(name) or "").strip().lower() in {"1", "true", "yes", "on"}
