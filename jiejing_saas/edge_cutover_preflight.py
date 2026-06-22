"""Edge WAF, origin lock, and callback cutover preflight for Jiejing."""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlparse

from .config import SaaSSettings
from .domain_readiness import build_domain_readiness


EDGE_PROVIDERS = {"cloudflare", "tencent_edgeone", "tencent_waf"}


def build_edge_cutover_preflight(settings: SaaSSettings) -> dict[str, Any]:
    """Build a no-write packet for domain step 2/3/4 preparation."""

    domain = build_domain_readiness(settings)
    selected_root = str(domain.get("selected_root_domain") or "").strip().lower()
    app_host = str(domain.get("target_app_host") or domain.get("stable_domain") or "").strip().lower()
    provider = _edge_provider()
    waf = _waf_evidence(provider=provider)
    origin = _origin_lock_evidence(provider=provider)
    callbacks = _callback_evidence(app_host=app_host, domain=domain)
    stages = _stages(domain=domain, waf=waf, origin=origin, callbacks=callbacks)
    blocked = [item for item in stages if item.get("status") != "ready"]
    next_stage = blocked[0] if blocked else {}
    return {
        "contract_version": "2026-06-18-edge-waf-origin-callback-preflight",
        "mode": "owner_console_preflight_no_write_no_charge",
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
        "selected_root_domain": selected_root,
        "target_app_host": app_host,
        "recommended_provider": "cloudflare",
        "selected_edge_provider": provider,
        "domain": domain,
        "waf_edge": waf,
        "origin_lock": origin,
        "callback_cutover": callbacks,
        "summary": {
            "ready_count": len(stages) - len(blocked),
            "total_count": len(stages),
            "blocked_count": len(blocked),
            "blocked_keys": [str(item.get("key") or "") for item in blocked],
            "next_step": str(next_stage.get("key") or ""),
            "next_action": str(next_stage.get("next_action") or ""),
            "domain_payment_confirmed": bool(domain.get("domain_payment_confirmed")),
            "domain_registration_review_pending": bool(domain.get("domain_registration_review_pending")),
            "domain_registered": bool(domain.get("domain_registered")),
            "waf_ready": bool(waf.get("ready")),
            "origin_locked": bool(origin.get("ready")),
            "callbacks_ready": bool(callbacks.get("ready")),
        },
        "stages": stages,
        "operator_sequence": _operator_sequence(selected_root=selected_root, app_host=app_host, provider=provider),
        "cloudflare_minimum_rules": _cloudflare_minimum_rules(),
        "tencent_edgeone_minimum_rules": _tencent_edgeone_minimum_rules(),
        "origin_security_group_plan": _origin_security_group_plan(provider=provider),
        "required_callback_urls": _required_callback_urls(app_host),
        "docs": [
            "https://developers.cloudflare.com/waf/rate-limiting-rules/",
            "https://developers.cloudflare.com/fundamentals/concepts/cloudflare-ip-addresses/",
            "https://www.cloudflare.com/ips/",
            "https://www.tencentcloud.com/document/product/213/12452",
            "https://www.tencentcloud.com/document/product/213/34272",
            "https://www.tencentcloud.com/document/product/1145/55936",
            "https://www.tencentcloud.com/document/product/1145/55943",
            "https://docs.stripe.com/webhooks",
            "https://developer.ebay.com/develop/guides-v2/authorization",
        ],
        "evidence_to_record": [
            "edge_provider_selected",
            "domain_added_to_edge_provider",
            "edge_dns_proxied_or_cname_verified",
            "waf_managed_rules_enabled",
            "bot_protection_enabled",
            "login_and_api_rate_limits_enabled",
            "origin_http_https_edge_only_security_group_screenshot_or_audit_note",
            "direct_origin_ip_blocked_probe",
            "ebay_callback_registered_on_stable_domain",
            "stripe_checkout_portal_webhook_urls_registered_on_stable_domain",
        ],
        "secret_exposed": False,
    }


def _stages(
    *,
    domain: dict[str, Any],
    waf: dict[str, Any],
    origin: dict[str, Any],
    callbacks: dict[str, Any],
) -> list[dict[str, Any]]:
    domain_registered = bool(domain.get("domain_registered"))
    return [
        _stage(
            "stable_domain_purchase_confirmed",
            "Stable domain payment and registry review are confirmed",
            domain_registered,
            next_action=_domain_next_action(domain),
            evidence_summary=(
                f"domain={domain.get('selected_root_domain') or 'not_selected'}; "
                f"registration_status={domain.get('domain_registration_status')}; "
                f"payment_confirmed={bool(domain.get('domain_payment_confirmed'))}; "
                f"review_pending={bool(domain.get('domain_registration_review_pending'))}"
            ),
            external_console_required=True,
            can_prepare_now=True,
        ),
        _stage(
            "waf_edge_onboarded",
            "Cloudflare or Tencent EdgeOne/WAF is onboarded",
            domain_registered and bool(waf.get("ready")),
            next_action="After the domain is purchased, add it to the chosen edge provider, proxy app.jiejing.shop, enable managed WAF, bot controls and rate limits.",
            evidence_summary=str(waf.get("evidence_summary") or ""),
            external_console_required=True,
            can_prepare_now=True,
        ),
        _stage(
            "origin_direct_access_locked",
            "Origin direct HTTP/HTTPS access is locked",
            bool(waf.get("ready")) and bool(origin.get("ready")),
            next_action="Only after WAF traffic is verified, change the Tencent Cloud security group so website ports accept only edge-provider traffic; keep SSH operator-only.",
            evidence_summary=str(origin.get("evidence_summary") or ""),
            external_console_required=True,
            can_prepare_now=False,
        ),
        _stage(
            "ebay_stripe_callbacks_on_stable_domain",
            "eBay and Stripe URLs are aligned to the stable domain",
            bool(callbacks.get("ready")),
            next_action="After HTTPS is verified, register the stable eBay callback and Stripe Checkout, Portal and webhook URLs; do not start OAuth or create Checkout sessions from this preflight.",
            evidence_summary=str(callbacks.get("evidence_summary") or ""),
            external_console_required=True,
            can_prepare_now=True,
        ),
    ]


def _stage(
    key: str,
    title: str,
    ready: bool,
    *,
    next_action: str,
    evidence_summary: str,
    external_console_required: bool,
    can_prepare_now: bool,
) -> dict[str, Any]:
    return {
        "key": key,
        "title": title,
        "status": "ready" if ready else "blocked",
        "severity": "info" if ready else "blocker",
        "next_action": next_action,
        "evidence_summary": evidence_summary,
        "external_console_required": external_console_required,
        "can_prepare_now": can_prepare_now,
        "creates_checkout_session": False,
        "calls_stripe_api": False,
        "triggers_real_charge": False,
        "triggers_ebay_oauth": False,
        "repeat_ebay_oauth_allowed": False,
        "triggers_real_platform_write": False,
        "frontend_gets_payment_secret": False,
        "frontend_gets_ebay_token": False,
        "secret_exposed": False,
    }


def _waf_evidence(*, provider: str) -> dict[str, Any]:
    domain_added = _env_bool("JIEJING_EDGE_DOMAIN_ADDED")
    dns_proxied = _env_bool("JIEJING_EDGE_DNS_PROXIED")
    managed_rules = _env_bool("JIEJING_WAF_MANAGED_RULES_ENABLED")
    bot = _env_bool("JIEJING_BOT_PROTECTION_ENABLED")
    rate_limits = _env_bool("JIEJING_WAF_RATE_LIMITS_ENABLED")
    ai_crawler = _env_bool("JIEJING_AI_CRAWLER_CONTROL_ENABLED")
    challenge = _env_bool("JIEJING_TURNSTILE_OR_CHALLENGE_ENABLED")
    free_baseline_ready = provider in EDGE_PROVIDERS and domain_added and dns_proxied and bot and rate_limits and ai_crawler and challenge
    ready = free_baseline_ready
    return {
        "provider": provider,
        "provider_selected": provider in EDGE_PROVIDERS,
        "domain_added": domain_added,
        "dns_proxied": dns_proxied,
        "managed_waf_rules_enabled": managed_rules,
        "managed_waf_rules_required_for_private_beta": False,
        "managed_waf_rules_paid_upgrade_not_required_for_private_beta": provider == "cloudflare" and free_baseline_ready and not managed_rules,
        "cloudflare_free_baseline_ready": free_baseline_ready,
        "bot_protection_enabled": bot,
        "rate_limits_enabled": rate_limits,
        "ai_crawler_control_enabled": ai_crawler,
        "turnstile_or_managed_challenge_enabled": challenge,
        "ready": ready,
        "evidence_summary": (
            f"provider={provider}; domain_added={domain_added}; dns_proxied={dns_proxied}; "
            f"managed_rules={managed_rules}; free_baseline={free_baseline_ready}; "
            f"bot={bot}; rate_limits={rate_limits}; ai_crawler={ai_crawler}; challenge={challenge}"
        ),
        "secret_exposed": False,
    }


def _origin_lock_evidence(*, provider: str) -> dict[str, Any]:
    http_https_edge_only = _env_bool("JIEJING_ORIGIN_HTTP_HTTPS_EDGE_ONLY")
    direct_ip_blocked = _env_bool("JIEJING_ORIGIN_DIRECT_IP_BLOCKED")
    ssh_operator_only = _env_bool("JIEJING_ORIGIN_SSH_OPERATOR_ONLY")
    allowlist_source = _first_env("JIEJING_ORIGIN_EDGE_IP_ALLOWLIST_SOURCE")
    ready = http_https_edge_only and direct_ip_blocked and ssh_operator_only and bool(allowlist_source)
    return {
        "provider": provider,
        "http_https_edge_only": http_https_edge_only,
        "direct_origin_ip_blocked": direct_ip_blocked,
        "ssh_operator_only": ssh_operator_only,
        "edge_ip_allowlist_source": allowlist_source,
        "ready": ready,
        "do_not_apply_before_edge_dns_is_verified": True,
        "evidence_summary": (
            f"http_https_edge_only={http_https_edge_only}; direct_ip_blocked={direct_ip_blocked}; "
            f"ssh_operator_only={ssh_operator_only}; allowlist_source={allowlist_source or 'missing'}"
        ),
        "secret_exposed": False,
    }


def _callback_evidence(*, app_host: str, domain: dict[str, Any]) -> dict[str, Any]:
    urls = _required_callback_urls(app_host)
    stable_https_ready = bool(domain.get("production_domain_ready"))
    ebay_callback_verified = bool(domain.get("ebay_callback_verified"))
    stripe_urls_aligned = all(
        _url_on_host(_first_env(env_name), app_host)
        for env_name in (
            "JIEJING_BILLING_SUCCESS_URL",
            "JIEJING_BILLING_CANCEL_URL",
            "JIEJING_BILLING_PORTAL_RETURN_URL",
            "JIEJING_BILLING_WEBHOOK_URL",
        )
    )
    stripe_urls_verified = _env_bool("JIEJING_STRIPE_CALLBACK_URLS_VERIFIED")
    ready = stable_https_ready and ebay_callback_verified and stripe_urls_aligned and stripe_urls_verified
    return {
        "stable_https_domain_ready": stable_https_ready,
        "ebay_callback_verified": ebay_callback_verified,
        "stripe_urls_on_stable_domain": stripe_urls_aligned,
        "stripe_urls_verified_in_dashboard": stripe_urls_verified,
        "ready": ready,
        "required_urls": urls,
        "evidence_summary": (
            f"stable_https={stable_https_ready}; ebay_callback={ebay_callback_verified}; "
            f"stripe_urls_aligned={stripe_urls_aligned}; stripe_dashboard_verified={stripe_urls_verified}"
        ),
        "secret_exposed": False,
    }


def _operator_sequence(*, selected_root: str, app_host: str, provider: str) -> list[dict[str, Any]]:
    return [
        _operator_step("finish_domain_purchase", f"Wait for registry review and activation of {selected_root or 'the selected domain'}", "domain", can_do_now=True),
        _operator_step("add_domain_to_edge", f"Add {selected_root or 'the selected domain'} to {provider if provider != 'not_selected' else 'Cloudflare or Tencent EdgeOne'}", "waf", can_do_now=False),
        _operator_step("proxy_app_hostname", f"Proxy {app_host or 'app.<domain>'} through the edge provider", "waf", can_do_now=False),
        _operator_step("proxy_root_hostname", f"Proxy {selected_root or 'the root domain'} through the edge provider and redirect it to {app_host or 'app.<domain>'}", "waf", can_do_now=False),
        _operator_step("enable_waf_bot_rate_limits", "Enable managed WAF rules, bot protection, AI crawler controls, login/API rate limits and challenge rules", "waf", can_do_now=False),
        _operator_step("lock_origin_security_group", "Lock Tencent Cloud security group: HTTP/HTTPS only from edge provider, SSH only from trusted operator access", "origin", can_do_now=False),
        _operator_step("register_callbacks", "Register eBay callback and Stripe Checkout/Portal/webhook URLs on the stable HTTPS app host", "callbacks", can_do_now=False),
    ]


def _domain_next_action(domain: dict[str, Any]) -> str:
    if domain.get("domain_registration_review_pending"):
        return "Payment is confirmed; wait for registry name review to pass, then verify the domain is active before DNS, WAF, callbacks or CORS cutover."
    if domain.get("domain_payment_confirmed"):
        return "Payment is recorded; verify registry activation and DNS management availability before WAF or callback cutover."
    return "Finish real-name review, purchase the domain, enable auto-renew, then record the domain as registered."


def _operator_step(key: str, title: str, category: str, *, can_do_now: bool) -> dict[str, Any]:
    return {
        "key": key,
        "title": title,
        "category": category,
        "can_do_now": can_do_now,
        "external_console_required": True,
        "secret_exposed": False,
    }


def _cloudflare_minimum_rules() -> list[dict[str, Any]]:
    return [
        _rule("managed_waf_rules", "Enable Cloudflare managed WAF rules", paths=["all_app_paths"]),
        _rule("login_signup_rate_limit", "Rate limit login, signup and password paths", paths=["/auth/login", "/auth/register", "/auth/password*"]),
        _rule("expensive_api_rate_limit", "Rate limit expensive API paths", paths=["/tasks*", "/reports*", "/model/*", "/commercial/*", "/data-packets/*"]),
        _rule("bot_or_managed_challenge", "Challenge low-confidence bots and abnormal browser fingerprints", paths=["/app.html", "/assets/*", "/commercial/*"]),
        _rule("ai_crawler_control", "Disable AI training crawlers and bulk scraping", paths=["robots.txt", "AI crawler controls"]),
    ]


def _tencent_edgeone_minimum_rules() -> list[dict[str, Any]]:
    return [
        _rule("managed_web_protection", "Enable EdgeOne managed web protection rules", paths=["all_app_paths"]),
        _rule("platform_managed_rate_limiting", "Enable platform-managed rate limiting for CC attack behavior", paths=["all_app_paths"]),
        _rule("custom_rate_limiting", "Add custom login and expensive API rate limits", paths=["/auth/*", "/tasks*", "/reports*", "/model/*"]),
        _rule("bot_behavior_analysis", "Enable bot behavior analysis and custom bot rules", paths=["/app.html", "/assets/*", "/commercial/*"]),
    ]


def _rule(key: str, title: str, *, paths: list[str]) -> dict[str, Any]:
    return {
        "key": key,
        "title": title,
        "paths": paths,
        "action": "managed_challenge_or_block",
        "secret_exposed": False,
    }


def _origin_security_group_plan(*, provider: str) -> dict[str, Any]:
    return {
        "provider": provider,
        "server_ip": "43.129.205.244",
        "apply_after": ["edge_dns_proxied", "waf_managed_rules_enabled", "health_check_through_stable_domain_passed"],
        "allow_inbound": [
            {"ports": "80,443", "source": "current_edge_provider_ip_ranges", "purpose": "web traffic via WAF only"},
            {"ports": "22", "source": "trusted_operator_access_only", "purpose": "SSH administration"},
        ],
        "deny_inbound": [
            {"ports": "80,443", "source": "0.0.0.0/0 after allow rules", "purpose": "block direct origin web access"},
        ],
        "do_not_lock_before_edge_is_verified": True,
        "secret_exposed": False,
    }


def _required_callback_urls(app_host: str) -> dict[str, str | bool]:
    return {
        "ebay_oauth_callback": f"https://{app_host}/oauth/ebay/callback" if app_host else "",
        "stripe_checkout_success": f"https://{app_host}/billing/success" if app_host else "",
        "stripe_checkout_cancel": f"https://{app_host}/billing/cancel" if app_host else "",
        "stripe_portal_return": f"https://{app_host}/settings/billing" if app_host else "",
        "stripe_webhook": f"https://{app_host}/billing/webhook" if app_host else "",
        "secret_exposed": False,
    }


def _edge_provider() -> str:
    provider = _first_env("JIEJING_EDGE_PROVIDER", "JIEJING_WAF_PROVIDER").strip().lower()
    return provider if provider else "not_selected"


def _url_on_host(value: str, host: str) -> bool:
    parsed = urlparse(value or "")
    return bool(host and parsed.scheme == "https" and (parsed.hostname or "").lower() == host)


def _first_env(*names: str) -> str:
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return ""


def _env_bool(name: str) -> bool:
    return str(os.environ.get(name) or "").strip().lower() in {"1", "true", "yes", "on"}
