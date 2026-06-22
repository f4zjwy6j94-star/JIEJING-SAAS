#!/usr/bin/env python3
"""No-write DNS/HTTPS status check for a newly registered Jiejing domain."""

from __future__ import annotations

import argparse
import ipaddress
import json
import socket
import ssl
import sys
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener, urlopen


READY_STATUSES = {"registered", "purchased", "active", "normal", "ok", "approved", "owner_verified"}
PLACEHOLDER_NETWORKS = (ipaddress.ip_network("198.18.0.0/15"),)


def main() -> int:
    parser = argparse.ArgumentParser(description="Check Jiejing registered-domain DNS/WAF cutover status without writes.")
    parser.add_argument("--domain", default="jiejing.shop")
    parser.add_argument("--app-host", default="")
    parser.add_argument("--registration-status", default="registered")
    parser.add_argument("--provider", default="cloudflare", choices=["cloudflare", "tencent_waf", "tencent_edgeone"])
    parser.add_argument("--origin-ip", default="43.129.205.244")
    parser.add_argument("--timeout", type=float, default=8.0)
    parser.add_argument("--skip-https-probe", action="store_true")
    parser.add_argument("--skip-robots-probe", action="store_true")
    parser.add_argument("--skip-scanner-block-probe", action="store_true")
    parser.add_argument("--skip-scripted-challenge-probe", action="store_true")
    parser.add_argument("--skip-backend-rate-limit-probe", action="store_true")
    parser.add_argument("--skip-root-redirect-probe", action="store_true")
    parser.add_argument("--skip-origin-direct-probe", action="store_true")
    parser.add_argument("--skip-cors-probe", action="store_true")
    parser.add_argument(
        "--auth-rate-limit-console-evidence",
        action="store_true",
        help="Non-secret operator evidence that the edge auth/login rate-limit rule is active in the provider console.",
    )
    parser.add_argument(
        "--expensive-api-rate-limit-console-evidence",
        action="store_true",
        help="Non-secret operator evidence that expensive API rate limits are active in the provider console.",
    )
    parser.add_argument(
        "--bot-protection-console-evidence",
        action="store_true",
        help="Non-secret operator evidence that bot/challenge protection is active in the provider console.",
    )
    parser.add_argument(
        "--managed-waf-console-evidence",
        action="store_true",
        help="Non-secret operator evidence that provider managed WAF rules are active in the provider console.",
    )
    parser.add_argument("--root-ip-fixture", action="append", default=[], help="Test-only A record fixture for the root domain.")
    parser.add_argument("--app-ip-fixture", action="append", default=[], help="Test-only A record fixture for the app host.")
    args = parser.parse_args()

    domain = _normalize_host(args.domain)
    app_host = _normalize_host(args.app_host) or (f"app.{domain}" if domain else "")
    origin_ip = args.origin_ip.strip()

    root_records = _resolve_ips(domain, fixtures=args.root_ip_fixture, timeout=args.timeout)
    app_records = _resolve_ips(app_host, fixtures=args.app_ip_fixture, timeout=args.timeout)
    app_health = _probe_https_health(app_host, timeout=args.timeout) if app_host and not args.skip_https_probe else _skipped_https_probe(app_host)
    robots_txt = _probe_robots_txt(app_host, timeout=args.timeout) if app_host and not args.skip_robots_probe else _skipped_probe(f"https://{app_host}/robots.txt")
    scanner_block = (
        _probe_scanner_block_rule(app_host, timeout=args.timeout)
        if app_host and not args.skip_scanner_block_probe
        else _skipped_probe(f"https://{app_host}/.env")
    )
    scripted_challenge = (
        _probe_scripted_expensive_api_challenge(app_host, timeout=args.timeout)
        if app_host and not args.skip_scripted_challenge_probe
        else _skipped_probe(f"https://{app_host}/reports")
    )
    backend_rate_limit = (
        _probe_backend_expensive_api_rate_limit(app_host, timeout=args.timeout)
        if app_host and not args.skip_backend_rate_limit_probe
        else _skipped_probe(f"https://{app_host}/security/rate-limit/status")
    )
    root_redirect = (
        _probe_root_redirect(domain=domain, app_host=app_host, timeout=args.timeout)
        if domain and app_host and not args.skip_root_redirect_probe
        else _skipped_probe(f"https://{domain}/")
    )
    origin_direct = (
        _probe_direct_origin(app_host=app_host, origin_ip=origin_ip, timeout=args.timeout)
        if app_host and origin_ip and not args.skip_origin_direct_probe
        else _skipped_probe(f"https://{origin_ip}/health")
    )
    cors = (
        _probe_cors(app_host=app_host, origin=f"https://{app_host}", timeout=args.timeout)
        if app_host and not args.skip_cors_probe
        else _skipped_probe(f"https://{app_host}/health")
    )

    packet = _build_packet(
        domain=domain,
        app_host=app_host,
        registration_status=args.registration_status,
        provider=args.provider,
        origin_ip=origin_ip,
        root_records=root_records,
        app_records=app_records,
        app_health=app_health,
        robots_txt=robots_txt,
        scanner_block=scanner_block,
        scripted_challenge=scripted_challenge,
        backend_rate_limit=backend_rate_limit,
        root_redirect=root_redirect,
        origin_direct=origin_direct,
        cors=cors,
        auth_rate_limit_console_evidence=args.auth_rate_limit_console_evidence,
        expensive_api_rate_limit_console_evidence=args.expensive_api_rate_limit_console_evidence,
        bot_protection_console_evidence=args.bot_protection_console_evidence,
        managed_waf_console_evidence=args.managed_waf_console_evidence,
    )
    print(json.dumps({"registered_domain_cutover_status": packet}, ensure_ascii=False, indent=2))
    return 0


def _build_packet(
    *,
    domain: str,
    app_host: str,
    registration_status: str,
    provider: str,
    origin_ip: str,
    root_records: list[str],
    app_records: list[str],
    app_health: dict[str, object],
    robots_txt: dict[str, object],
    scanner_block: dict[str, object],
    scripted_challenge: dict[str, object],
    backend_rate_limit: dict[str, object],
    root_redirect: dict[str, object],
    origin_direct: dict[str, object],
    cors: dict[str, object],
    auth_rate_limit_console_evidence: bool,
    expensive_api_rate_limit_console_evidence: bool,
    bot_protection_console_evidence: bool,
    managed_waf_console_evidence: bool,
) -> dict[str, object]:
    root_dns = _dns_status(root_records, origin_ip=origin_ip)
    app_dns = _dns_status(app_records, origin_ip=origin_ip)
    domain_registered = _status_ready(registration_status)
    app_health_ready = app_health.get("ready") is True
    app_dns_placeholder = app_dns.get("status") == "placeholder_dns"
    app_dns_missing = app_dns.get("status") == "missing_dns"
    app_points_direct_origin = app_dns.get("status") == "direct_origin_dns"
    app_dns_public_or_edge = app_dns.get("status") in {"public_edge_or_unknown_dns", "direct_origin_dns"}
    edge_dns_ready = app_dns_public_or_edge and not app_points_direct_origin and not app_dns_placeholder
    root_dns_placeholder = root_dns.get("status") == "placeholder_dns"
    root_dns_missing = root_dns.get("status") == "missing_dns"
    root_points_direct_origin = root_dns.get("status") == "direct_origin_dns"
    root_dns_public_or_edge = root_dns.get("status") in {"public_edge_or_unknown_dns", "direct_origin_dns"}
    root_dns_ready = root_dns_public_or_edge and not root_points_direct_origin and not root_dns_placeholder
    root_redirect_ready = root_redirect.get("ready") is True
    managed_robots_ready = robots_txt.get("ready") is True
    scanner_block_ready = scanner_block.get("ready") is True
    scripted_challenge_ready = scripted_challenge.get("ready") is True
    backend_rate_limit_ready = backend_rate_limit.get("ready") is True
    bot_protection_ready = bool(bot_protection_console_evidence or scripted_challenge_ready)
    expensive_api_rate_limit_ready = bool(expensive_api_rate_limit_console_evidence or backend_rate_limit_ready)
    origin_locked = origin_direct.get("direct_origin_blocked") is True
    cors_ready = cors.get("ready") is True
    free_waf_baseline_ready = bool(managed_robots_ready and scanner_block_ready and auth_rate_limit_console_evidence and bot_protection_ready)

    blocked_reasons: list[str] = []
    if not domain_registered:
        blocked_reasons.append("domain_registration_not_active")
    if root_dns_missing:
        blocked_reasons.append("root_dns_missing")
    if root_dns_placeholder:
        blocked_reasons.append("root_dns_placeholder_or_benchmark_range")
    if root_points_direct_origin:
        blocked_reasons.append("root_dns_points_to_origin_without_confirmed_proxy")
    if not root_redirect_ready:
        blocked_reasons.append("root_https_redirect_not_ready")
    if app_dns_missing:
        blocked_reasons.append("app_dns_missing")
    if app_dns_placeholder:
        blocked_reasons.append("app_dns_placeholder_or_benchmark_range")
    if app_points_direct_origin:
        blocked_reasons.append("app_dns_points_to_origin_without_confirmed_proxy")
    if not app_health_ready:
        blocked_reasons.append("stable_https_health_not_ready")
    if not (edge_dns_ready and app_health_ready):
        blocked_reasons.append("waf_edge_dns_or_https_not_verified")
    if not managed_robots_ready:
        blocked_reasons.append("managed_robots_ai_crawler_control_not_verified")
    if not scanner_block_ready:
        blocked_reasons.append("scanner_path_block_rule_not_verified")
    if not auth_rate_limit_console_evidence:
        blocked_reasons.append("auth_rate_limit_rule_not_verified")
    if not expensive_api_rate_limit_ready:
        blocked_reasons.append("expensive_api_rate_limit_rule_not_verified")
    if not bot_protection_ready:
        blocked_reasons.append("bot_protection_or_challenge_not_verified")
    if not origin_locked:
        blocked_reasons.append("origin_direct_lock_not_verified")
    if not cors_ready:
        blocked_reasons.append("stable_cors_origin_not_verified")
    blocked_reasons.append("ebay_stripe_callback_evidence_not_recorded")

    return {
        "contract_version": "2026-06-18-registered-domain-cutover-status",
        "mode": "no_write_dns_https_probe",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "domain": domain,
        "app_host": app_host,
        "registration_status": _normalize_status(registration_status),
        "domain_registered": domain_registered,
        "selected_provider": provider,
        "origin_ip": origin_ip,
        "root_dns": root_dns,
        "app_dns": app_dns,
        "root_https_redirect": root_redirect,
        "app_https_health": app_health,
        "robots_txt": robots_txt,
        "scanner_path_block_rule": scanner_block,
        "scripted_expensive_api_challenge": scripted_challenge,
        "backend_expensive_api_rate_limit": backend_rate_limit,
        "edge_waf_console_evidence": {
            "managed_waf_rules_enabled": managed_waf_console_evidence,
            "bot_protection_enabled": bot_protection_ready,
            "auth_rate_limit_rule_enabled": auth_rate_limit_console_evidence,
            "expensive_api_rate_limit_rule_enabled": expensive_api_rate_limit_ready,
            "cloudflare_free_baseline_ready": free_waf_baseline_ready,
            "managed_waf_rules_paid_upgrade_not_required_for_private_beta": provider == "cloudflare" and free_waf_baseline_ready and not managed_waf_console_evidence,
            "secret_exposed": False,
        },
        "origin_direct_probe": origin_direct,
        "cors_stable_origin_probe": cors,
        "edge_dns_https_ready": edge_dns_ready and app_health_ready,
        "root_bare_domain_redirect_ready": root_dns_ready and root_redirect_ready,
        "managed_robots_ai_crawler_control_ready": managed_robots_ready,
        "scanner_path_block_rule_ready": scanner_block_ready,
        "scripted_expensive_api_challenge_ready": scripted_challenge_ready,
        "backend_expensive_api_rate_limit_ready": backend_rate_limit_ready,
        "cloudflare_free_waf_baseline_ready": free_waf_baseline_ready,
        "origin_direct_lock_ready": origin_locked,
        "cors_stable_origin_ready": cors_ready,
        "status": "blocked",
        "production_cutover_ready": False,
        "safe_to_lock_origin_now": bool(edge_dns_ready and app_health_ready and not origin_locked),
        "safe_to_update_ebay_callback_now": False,
        "safe_to_update_stripe_live_urls_now": False,
        "triggers_ebay_oauth": False,
        "calls_stripe_api": False,
        "creates_checkout_session": False,
        "triggers_real_charge": False,
        "triggers_real_platform_write": False,
        "frontend_gets_secret": False,
        "blocked_reasons": blocked_reasons,
        "next_operator_steps": _next_operator_steps(
            provider=provider,
            domain=domain,
            app_host=app_host,
            root_dns_ready=root_dns_ready,
            root_dns_placeholder=root_dns_placeholder,
            root_dns_missing=root_dns_missing,
            root_points_direct_origin=root_points_direct_origin,
            root_redirect_ready=root_redirect_ready,
            app_dns_public_or_edge=app_dns_public_or_edge,
            app_dns_placeholder=app_dns_placeholder,
            app_dns_missing=app_dns_missing,
            app_points_direct_origin=app_points_direct_origin,
            app_health_ready=app_health_ready,
            managed_robots_ready=managed_robots_ready,
            scanner_block_ready=scanner_block_ready,
            auth_rate_limit_ready=auth_rate_limit_console_evidence,
            expensive_api_rate_limit_ready=expensive_api_rate_limit_ready,
            bot_protection_ready=bot_protection_ready,
            managed_waf_ready=managed_waf_console_evidence,
            origin_locked=origin_locked,
            cors_ready=cors_ready,
        ),
        "required_urls_after_stable_https": {
            "ebay_oauth_callback": f"https://{app_host}/oauth/ebay/callback" if app_host else "",
            "stripe_checkout_success": f"https://{app_host}/billing/success" if app_host else "",
            "stripe_checkout_cancel": f"https://{app_host}/billing/cancel" if app_host else "",
            "stripe_portal_return": f"https://{app_host}/settings/billing" if app_host else "",
            "stripe_webhook": f"https://{app_host}/billing/webhook" if app_host else "",
            "secret_exposed": False,
        },
        "secret_exposed": False,
    }


def _next_operator_steps(
    *,
    provider: str,
    domain: str,
    app_host: str,
    root_dns_ready: bool,
    root_dns_placeholder: bool,
    root_dns_missing: bool,
    root_points_direct_origin: bool,
    root_redirect_ready: bool,
    app_dns_public_or_edge: bool,
    app_dns_placeholder: bool,
    app_dns_missing: bool,
    app_points_direct_origin: bool,
    app_health_ready: bool,
    managed_robots_ready: bool,
    scanner_block_ready: bool,
    auth_rate_limit_ready: bool,
    expensive_api_rate_limit_ready: bool,
    bot_protection_ready: bool,
    managed_waf_ready: bool,
    origin_locked: bool,
    cors_ready: bool,
) -> list[dict[str, object]]:
    steps: list[dict[str, object]] = []
    if root_dns_missing or root_dns_placeholder:
        steps.append(
            _step(
                "cloudflare_root_dns_record",
                f"Add a proxied Cloudflare DNS record for {domain}: A @ -> origin IP or CNAME @ -> {app_host}; keep proxy enabled.",
                "operator_console",
                ready=False,
            )
        )
    if root_points_direct_origin:
        steps.append(
            _step(
                "proxy_root_dns_before_public_entry",
                f"{domain} must be orange-cloud proxied before the bare domain is treated as a public entry.",
                "operator_console",
                ready=False,
            )
        )
    if root_dns_ready and root_redirect_ready:
        steps.append(_step("root_bare_domain_redirect_verified", f"https://{domain}/ redirects to https://{app_host}/.", "agent_verification", ready=True))
    elif root_dns_ready:
        steps.append(_step("verify_root_bare_domain_redirect", f"Make https://{domain}/ redirect to https://{app_host}/.", "agent_verification", ready=False))
    if app_dns_missing or app_dns_placeholder:
        if provider == "cloudflare":
            steps.append(
                _step(
                    "cloudflare_add_site_and_dns",
                    f"Add {domain} to Cloudflare, switch Tencent nameservers to Cloudflare, then create proxied DNS for {app_host}.",
                    "operator_console",
                    ready=False,
                )
            )
        else:
            steps.append(
                _step(
                    "tencent_waf_add_domain_and_cname",
                    f"Add {app_host} to Tencent WAF/EdgeOne, then point DNSPod app record to the WAF CNAME.",
                    "operator_console",
                    ready=False,
                )
            )
    if app_points_direct_origin:
        steps.append(
            _step(
                "proxy_dns_before_origin_lock",
                f"{app_host} currently resolves to the origin IP; put it behind {provider} before locking the origin.",
                "operator_console",
                ready=False,
            )
        )
    if app_dns_public_or_edge and not app_health_ready:
        steps.append(_step("fix_stable_https_health", f"Make https://{app_host}/health return the Jiejing health response.", "operator_console", ready=False))
    if managed_robots_ready:
        steps.append(_step("managed_robots_active", f"https://{app_host}/robots.txt returns Cloudflare/Jiejing AI crawler restrictions.", "agent_verification", ready=True))
    else:
        steps.append(_step("enable_managed_robots", f"Enable managed robots.txt or serve the Jiejing robots.txt policy at https://{app_host}/robots.txt.", "operator_console", ready=False))
    if scanner_block_ready:
        steps.append(_step("scanner_path_block_verified", f"https://{app_host}/.env is blocked at the edge.", "agent_verification", ready=True))
    else:
        steps.append(_step("enable_scanner_path_block", "Block common scanner paths such as /.env, /.git, /wp-, /phpmyadmin, /adminer and /xmlrpc.php.", "operator_console", ready=False))
    steps.append(
        _step(
            "auth_rate_limit_verified",
            "Cloudflare auth endpoint rate limit is active for /auth/login, /auth/register and /auth/demo-session.",
            "operator_console",
            ready=auth_rate_limit_ready,
        )
    )
    steps.append(
        _step(
            "expensive_api_rate_limit_verified",
            "Add or verify rate limits for expensive API paths such as /tasks, /reports, /model, /commercial and eBay workflow APIs.",
            "operator_console",
            ready=expensive_api_rate_limit_ready,
        )
    )
    steps.append(
        _step(
            "bot_protection_verified",
            "Enable and verify Bot Fight Mode, challenge rules or an equivalent bot protection control without breaking Stripe/eBay callbacks.",
            "operator_console",
            ready=bot_protection_ready,
        )
    )
    steps.append(
        _step(
            "managed_waf_rules_verified",
            "Enable managed WAF rules only if the selected provider plan supports them without unexpected charges.",
            "operator_console",
            ready=managed_waf_ready,
        )
    )
    if origin_locked:
        steps.append(_step("origin_direct_lock_verified", "Direct public HTTPS access to the origin IP is blocked or times out.", "agent_verification", ready=True))
    if cors_ready:
        steps.append(_step("stable_domain_cors_verified", f"{app_host} accepts the stable HTTPS Origin header.", "agent_verification", ready=True))
    steps.extend(
        [
            _step("lock_origin_after_edge_health", "Only after stable-domain health passes, restrict Tencent CVM 80/443 to edge-provider traffic and keep SSH operator-only.", "operator_console", ready=origin_locked),
            _step("register_callbacks_after_https", "Only after stable HTTPS passes, register eBay callback and Stripe Checkout/Portal/webhook URLs.", "operator_console", ready=False),
            _step("rerun_no_charge_rehearsal", "Rerun readiness, no-real-charge billing rehearsal, secret scan and browser smoke.", "agent_verification", ready=False),
        ]
    )
    return steps


def _step(key: str, title: str, owner: str, *, ready: bool) -> dict[str, object]:
    return {"key": key, "title": title, "owner": owner, "ready": ready, "secret_exposed": False}


def _dns_status(records: list[str], *, origin_ip: str) -> dict[str, object]:
    if not records:
        return {"status": "missing_dns", "records": [], "secret_exposed": False}
    classified = [{"ip": ip, "class": _classify_ip(ip, origin_ip=origin_ip)} for ip in sorted(set(records))]
    classes = {str(item["class"]) for item in classified}
    if "placeholder_or_benchmark_range" in classes:
        status = "placeholder_dns"
    elif classes == {"origin_direct_ip"}:
        status = "direct_origin_dns"
    elif "public_edge_or_unknown" in classes:
        status = "public_edge_or_unknown_dns"
    else:
        status = "non_public_dns"
    return {"status": status, "records": classified, "secret_exposed": False}


def _classify_ip(ip: str, *, origin_ip: str) -> str:
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return "invalid_ip"
    if any(address in network for network in PLACEHOLDER_NETWORKS):
        return "placeholder_or_benchmark_range"
    if ip == origin_ip:
        return "origin_direct_ip"
    if address.is_private or address.is_loopback or address.is_link_local or address.is_multicast or address.is_reserved:
        return "non_public_ip"
    return "public_edge_or_unknown"


def _resolve_ips(host: str, *, fixtures: list[str], timeout: float) -> list[str]:
    if fixtures:
        return [item.strip() for item in fixtures if item.strip()]
    if not host:
        return []
    doh_records = _resolve_ips_doh(host, timeout=timeout)
    if doh_records:
        return doh_records
    previous_timeout = socket.getdefaulttimeout()
    socket.setdefaulttimeout(timeout)
    try:
        infos = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except (OSError, socket.gaierror):
        return []
    finally:
        socket.setdefaulttimeout(previous_timeout)
    return sorted({info[4][0] for info in infos if info and info[4]})


def _resolve_ips_doh(host: str, *, timeout: float) -> list[str]:
    records: set[str] = set()
    encoded_host = quote(host, safe="")
    urls = [
        f"https://cloudflare-dns.com/dns-query?name={encoded_host}&type=A",
        f"https://dns.google/resolve?name={encoded_host}&type=A",
    ]
    for url in urls:
        request = Request(
            url,
            method="GET",
            headers={
                "Accept": "application/dns-json",
                "User-Agent": "jiejing-domain-cutover-status/2026-06-18",
            },
        )
        try:
            with urlopen(request, timeout=timeout, context=ssl.create_default_context()) as response:
                packet = json.loads(response.read(8192).decode("utf-8", errors="replace"))
        except (HTTPError, URLError, OSError, TimeoutError, ssl.SSLError, json.JSONDecodeError):
            continue
        for answer in packet.get("Answer") or []:
            if int(answer.get("type") or 0) != 1:
                continue
            value = str(answer.get("data") or "").strip()
            try:
                ipaddress.ip_address(value)
            except ValueError:
                continue
            records.add(value)
    return sorted(records)


def _probe_https_health(app_host: str, *, timeout: float) -> dict[str, object]:
    url = f"https://{app_host}/health"
    request = Request(url, method="GET", headers={"User-Agent": "jiejing-domain-cutover-status/2026-06-18"})
    try:
        with urlopen(request, timeout=timeout, context=ssl.create_default_context()) as response:
            body = response.read(4096).decode("utf-8", errors="replace")
            status = getattr(response, "status", 0)
    except HTTPError as exc:
        return {"url": url, "ready": False, "http_status": exc.code, "error_type": "http_error", "secret_exposed": False}
    except URLError as exc:
        return {"url": url, "ready": False, "http_status": 0, "error_type": type(exc.reason).__name__, "secret_exposed": False}
    except (OSError, TimeoutError, ssl.SSLError) as exc:
        return {"url": url, "ready": False, "http_status": 0, "error_type": type(exc).__name__, "secret_exposed": False}

    return {
        "url": url,
        "ready": status == 200 and '"status"' in body and "secret" not in body.lower().replace("secret_exposed", ""),
        "http_status": status,
        "body_has_jiejing_health_shape": '"status"' in body,
        "secret_exposed": False,
    }


def _skipped_https_probe(app_host: str) -> dict[str, object]:
    return {"url": f"https://{app_host}/health" if app_host else "", "ready": False, "skipped": True, "secret_exposed": False}


def _skipped_probe(url: str) -> dict[str, object]:
    return {"url": url, "ready": False, "skipped": True, "secret_exposed": False}


def _probe_robots_txt(app_host: str, *, timeout: float) -> dict[str, object]:
    url = f"https://{app_host}/robots.txt"
    request = Request(url, method="GET", headers={"User-Agent": "jiejing-domain-cutover-status/2026-06-18"})
    try:
        with urlopen(request, timeout=timeout, context=ssl.create_default_context()) as response:
            body = response.read(8192).decode("utf-8", errors="replace")
            status = getattr(response, "status", 0)
    except HTTPError as exc:
        return {"url": url, "ready": False, "http_status": exc.code, "error_type": "http_error", "secret_exposed": False}
    except URLError as exc:
        return {"url": url, "ready": False, "http_status": 0, "error_type": type(exc.reason).__name__, "secret_exposed": False}
    except (OSError, TimeoutError, ssl.SSLError) as exc:
        return {"url": url, "ready": False, "http_status": 0, "error_type": type(exc).__name__, "secret_exposed": False}

    lowered = body.lower()
    cloudflare_managed = "cloudflare managed" in lowered
    disallows_all = "user-agent: *" in lowered and "disallow: /" in lowered
    ai_training_denied = "ai-train=no" in lowered or all(marker.lower() in lowered for marker in ("GPTBot", "ClaudeBot", "Google-Extended"))
    return {
        "url": url,
        "ready": status == 200 and disallows_all and ai_training_denied,
        "http_status": status,
        "cloudflare_managed_content": cloudflare_managed,
        "disallows_all_crawlers": disallows_all,
        "ai_training_denied": ai_training_denied,
        "secret_exposed": False,
    }


def _probe_scanner_block_rule(app_host: str, *, timeout: float) -> dict[str, object]:
    url = f"https://{app_host}/.env"
    request = Request(url, method="GET", headers={"User-Agent": "jiejing-domain-cutover-status/2026-06-18"})
    try:
        with urlopen(request, timeout=timeout, context=ssl.create_default_context()) as response:
            body = response.read(1024).decode("utf-8", errors="replace")
            status = getattr(response, "status", 0)
            server = response.headers.get("server", "")
    except HTTPError as exc:
        _ = exc.read(1024)
        server = exc.headers.get("server", "")
        edge_blocked = exc.code in {401, 403, 429} and "cloudflare" in server.lower()
        return {
            "url": url,
            "ready": edge_blocked,
            "http_status": exc.code,
            "edge_blocked": edge_blocked,
            "server": server,
            "secret_exposed": False,
        }
    except URLError as exc:
        return {"url": url, "ready": False, "http_status": 0, "error_type": type(exc.reason).__name__, "secret_exposed": False}
    except (OSError, TimeoutError, ssl.SSLError) as exc:
        return {"url": url, "ready": False, "http_status": 0, "error_type": type(exc).__name__, "secret_exposed": False}

    body_lower = body.lower()
    return {
        "url": url,
        "ready": False,
        "http_status": status,
        "edge_blocked": False,
        "server": server,
        "body_looks_like_secret_file": "password" in body_lower or "api_key" in body_lower,
        "secret_exposed": False,
    }


def _probe_scripted_expensive_api_challenge(app_host: str, *, timeout: float) -> dict[str, object]:
    url = f"https://{app_host}/reports"
    request = Request(
        url,
        method="GET",
        headers={"User-Agent": "curl/8.0 jiejing-domain-cutover-status/2026-06-18"},
    )
    try:
        with urlopen(request, timeout=timeout, context=ssl.create_default_context()) as response:
            _ = response.read(1024)
            status = getattr(response, "status", 0)
            server = response.headers.get("server", "")
            cf_mitigated = response.headers.get("cf-mitigated", "")
    except HTTPError as exc:
        _ = exc.read(1024)
        server = exc.headers.get("server", "")
        cf_mitigated = exc.headers.get("cf-mitigated", "")
        edge_challenged = exc.code in {403, 429} and cf_mitigated.lower() == "challenge" and "cloudflare" in server.lower()
        return {
            "url": url,
            "ready": edge_challenged,
            "http_status": exc.code,
            "edge_challenged": edge_challenged,
            "cf_mitigated": cf_mitigated,
            "server": server,
            "secret_exposed": False,
        }
    except URLError as exc:
        return {"url": url, "ready": False, "http_status": 0, "error_type": type(exc.reason).__name__, "secret_exposed": False}
    except (OSError, TimeoutError, ssl.SSLError) as exc:
        return {"url": url, "ready": False, "http_status": 0, "error_type": type(exc).__name__, "secret_exposed": False}

    return {
        "url": url,
        "ready": False,
        "http_status": status,
        "edge_challenged": False,
        "cf_mitigated": cf_mitigated,
        "server": server,
        "secret_exposed": False,
    }


def _probe_backend_expensive_api_rate_limit(app_host: str, *, timeout: float) -> dict[str, object]:
    url = f"https://{app_host}/security/rate-limit/status"
    request = Request(
        url,
        method="GET",
        headers={"User-Agent": "Mozilla/5.0 JiejingDomainCutoverStatus/2026-06-18"},
    )
    try:
        with urlopen(request, timeout=timeout, context=ssl.create_default_context()) as response:
            status = getattr(response, "status", 0)
            payload = json.loads(response.read(16384).decode("utf-8", errors="replace"))
    except HTTPError as exc:
        _ = exc.read(1024)
        return {"url": url, "ready": False, "http_status": exc.code, "error_type": "http_error", "secret_exposed": False}
    except URLError as exc:
        return {"url": url, "ready": False, "http_status": 0, "error_type": type(exc.reason).__name__, "secret_exposed": False}
    except (OSError, TimeoutError, ssl.SSLError, json.JSONDecodeError) as exc:
        return {"url": url, "ready": False, "http_status": 0, "error_type": type(exc).__name__, "secret_exposed": False}

    status_packet = payload.get("rate_limit_status") if isinstance(payload, dict) else {}
    expensive = status_packet.get("expensive_api_rate_limit") if isinstance(status_packet, dict) else {}
    protected_prefixes = expensive.get("protected_prefixes") if isinstance(expensive, dict) else []
    protected_exact_paths = expensive.get("protected_exact_paths") if isinstance(expensive, dict) else []
    protected_text = " ".join(str(item) for item in [*list(protected_prefixes or []), *list(protected_exact_paths or [])])
    required_paths_ready = all(marker in protected_text for marker in ("tasks", "reports", "model/", "commercial/"))
    enabled = isinstance(expensive, dict) and expensive.get("enabled") is True
    max_per_ip = int(expensive.get("max_per_ip_per_route_group") or 0) if isinstance(expensive, dict) else 0
    return {
        "url": url,
        "ready": status == 200 and enabled and required_paths_ready and max_per_ip > 0,
        "http_status": status,
        "enabled": enabled,
        "window_seconds": int(expensive.get("window_seconds") or 0) if isinstance(expensive, dict) else 0,
        "max_per_ip_per_route_group": max_per_ip,
        "protects_core_expensive_paths": required_paths_ready,
        "frontend_gets_secret": False,
        "calls_stripe_api": False,
        "triggers_ebay_oauth": False,
        "triggers_real_charge": False,
        "triggers_real_platform_write": False,
        "secret_exposed": False,
    }


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        return None


def _probe_root_redirect(*, domain: str, app_host: str, timeout: float) -> dict[str, object]:
    url = f"https://{domain}/"
    expected_prefix = f"https://{app_host}"
    request = Request(url, method="GET", headers={"User-Agent": "jiejing-domain-cutover-status/2026-06-18"})
    opener = build_opener(_NoRedirect, HTTPSHandler(context=ssl.create_default_context()))
    try:
        with opener.open(request, timeout=timeout) as response:
            status = getattr(response, "status", 0)
            location = response.headers.get("location", "")
    except HTTPError as exc:
        status = exc.code
        location = exc.headers.get("location", "")
        return {
            "url": url,
            "ready": status in {301, 302, 307, 308} and location.startswith(expected_prefix),
            "http_status": status,
            "location": location,
            "expected_location_prefix": expected_prefix,
            "secret_exposed": False,
        }
    except URLError as exc:
        return {"url": url, "ready": False, "http_status": 0, "error_type": type(exc.reason).__name__, "secret_exposed": False}
    except (OSError, TimeoutError, ssl.SSLError) as exc:
        return {"url": url, "ready": False, "http_status": 0, "error_type": type(exc).__name__, "secret_exposed": False}

    return {
        "url": url,
        "ready": status in {301, 302, 307, 308} and location.startswith(expected_prefix),
        "http_status": status,
        "location": location,
        "expected_location_prefix": expected_prefix,
        "secret_exposed": False,
    }


def _probe_cors(*, app_host: str, origin: str, timeout: float) -> dict[str, object]:
    url = f"https://{app_host}/health"
    request = Request(url, method="GET", headers={"Origin": origin, "User-Agent": "jiejing-domain-cutover-status/2026-06-18"})
    try:
        with urlopen(request, timeout=timeout, context=ssl.create_default_context()) as response:
            status = getattr(response, "status", 0)
            allow_origin = response.headers.get("access-control-allow-origin", "")
            vary = response.headers.get("vary", "")
    except HTTPError as exc:
        return {"url": url, "origin": origin, "ready": False, "http_status": exc.code, "error_type": "http_error", "secret_exposed": False}
    except URLError as exc:
        return {"url": url, "origin": origin, "ready": False, "http_status": 0, "error_type": type(exc.reason).__name__, "secret_exposed": False}
    except (OSError, TimeoutError, ssl.SSLError) as exc:
        return {"url": url, "origin": origin, "ready": False, "http_status": 0, "error_type": type(exc).__name__, "secret_exposed": False}
    return {
        "url": url,
        "origin": origin,
        "ready": status == 200 and allow_origin == origin,
        "http_status": status,
        "access_control_allow_origin": allow_origin,
        "vary_origin": "origin" in vary.lower(),
        "secret_exposed": False,
    }


def _probe_direct_origin(*, app_host: str, origin_ip: str, timeout: float) -> dict[str, object]:
    if not app_host or not origin_ip:
        return {"ready": False, "direct_origin_blocked": False, "error_type": "missing_app_host_or_origin_ip", "secret_exposed": False}
    try:
        context = ssl.create_default_context()
        with socket.create_connection((origin_ip, 443), timeout=timeout) as raw:
            raw.settimeout(timeout)
            with context.wrap_socket(raw, server_hostname=app_host) as tls:
                tls.settimeout(timeout)
                tls.sendall(
                    (
                        f"GET /health HTTP/1.1\r\nHost: {app_host}\r\n"
                        "User-Agent: jiejing-domain-cutover-status/2026-06-18\r\nConnection: close\r\n\r\n"
                    ).encode("ascii")
                )
                data = tls.recv(512)
    except (socket.timeout, TimeoutError):
        return {"target": f"{origin_ip}:443", "host_header": app_host, "ready": True, "direct_origin_blocked": True, "error_type": "timeout", "secret_exposed": False}
    except ssl.SSLError as exc:
        return {"target": f"{origin_ip}:443", "host_header": app_host, "ready": False, "direct_origin_blocked": False, "error_type": type(exc).__name__, "secret_exposed": False}
    except (ConnectionRefusedError, OSError) as exc:
        return {"target": f"{origin_ip}:443", "host_header": app_host, "ready": True, "direct_origin_blocked": True, "error_type": type(exc).__name__, "secret_exposed": False}

    first_line = data.decode("utf-8", errors="replace").splitlines()[0] if data else ""
    return {
        "target": f"{origin_ip}:443",
        "host_header": app_host,
        "ready": False,
        "direct_origin_blocked": False,
        "http_reachable": bool(data),
        "first_line": first_line,
        "secret_exposed": False,
    }


def _normalize_host(value: str) -> str:
    text = str(value or "").strip().lower().strip("/")
    if "://" in text:
        text = text.split("://", 1)[1]
    return text.split("/", 1)[0]


def _normalize_status(value: str) -> str:
    return str(value or "").strip().lower()


def _status_ready(value: str) -> bool:
    return _normalize_status(value) in READY_STATUSES


if __name__ == "__main__":
    raise SystemExit(main())
