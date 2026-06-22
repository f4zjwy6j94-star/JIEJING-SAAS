#!/usr/bin/env python3
"""Regression for edge WAF, origin lock, and callback cutover preflight."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.config import SaaSSettings  # noqa: E402
from jiejing_saas.edge_cutover_preflight import build_edge_cutover_preflight  # noqa: E402


OUT = ROOT / "output" / "jiejing-edge-cutover-preflight-test"
ENV_KEYS = [
    "JIEJING_SAAS_ENV",
    "JIEJING_SELECTED_DOMAIN",
    "JIEJING_DOMAIN_REGISTRATION_STATUS",
    "JIEJING_PUBLIC_BASE_URL",
    "JIEJING_STABLE_DOMAIN",
    "JIEJING_CORS_ORIGIN",
    "JIEJING_DOMAIN_DNS_VERIFIED",
    "JIEJING_TLS_VERIFIED",
    "JIEJING_EBAY_CALLBACK_VERIFIED",
    "JIEJING_DEPLOYMENT_HARDENED",
    "JIEJING_SECURITY_HEADERS_VERIFIED",
    "JIEJING_EDGE_PROVIDER",
    "JIEJING_EDGE_DOMAIN_ADDED",
    "JIEJING_EDGE_DNS_PROXIED",
    "JIEJING_WAF_MANAGED_RULES_ENABLED",
    "JIEJING_BOT_PROTECTION_ENABLED",
    "JIEJING_WAF_RATE_LIMITS_ENABLED",
    "JIEJING_AI_CRAWLER_CONTROL_ENABLED",
    "JIEJING_TURNSTILE_OR_CHALLENGE_ENABLED",
    "JIEJING_ORIGIN_HTTP_HTTPS_EDGE_ONLY",
    "JIEJING_ORIGIN_DIRECT_IP_BLOCKED",
    "JIEJING_ORIGIN_SSH_OPERATOR_ONLY",
    "JIEJING_ORIGIN_EDGE_IP_ALLOWLIST_SOURCE",
    "JIEJING_BILLING_SUCCESS_URL",
    "JIEJING_BILLING_CANCEL_URL",
    "JIEJING_BILLING_PORTAL_RETURN_URL",
    "JIEJING_BILLING_WEBHOOK_URL",
    "JIEJING_STRIPE_CALLBACK_URLS_VERIFIED",
]


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    previous = _set_pending_env()
    try:
        pending = _build()
        if pending.get("status") != "blocked":
            return fail(f"pending domain should keep edge cutover blocked: {pending.get('summary')}")
        if pending.get("selected_root_domain") != "jiejing.shop":
            return fail("pending edge packet should carry selected domain")
        if pending.get("target_app_host") != "app.jiejing.shop":
            return fail("pending edge packet should prepare app.jiejing.shop")
        summary = pending.get("summary") if isinstance(pending.get("summary"), dict) else {}
        if summary.get("domain_payment_confirmed") is not True or summary.get("domain_registration_review_pending") is not True:
            return fail(f"pending edge packet should show paid registry-review status: {summary}")
        if summary.get("domain_registered") is not False:
            return fail(f"pending edge packet should not treat review as active: {summary}")
        if pending.get("charge_now_allowed") is not False or pending.get("triggers_ebay_oauth") is not False:
            return fail("pending edge packet must not charge or trigger eBay OAuth")
        stages = {item.get("key"): item for item in pending.get("stages", []) if isinstance(item, dict)}
        if set(stages) != {
            "stable_domain_purchase_confirmed",
            "waf_edge_onboarded",
            "origin_direct_access_locked",
            "ebay_stripe_callbacks_on_stable_domain",
        }:
            return fail(f"unexpected stages: {sorted(stages)}")
        if stages["waf_edge_onboarded"].get("status") != "blocked":
            return fail("WAF stage must stay blocked before domain purchase and edge evidence")
        if stages["origin_direct_access_locked"].get("can_prepare_now") is not False:
            return fail("origin lock should not be applied before edge DNS/WAF is verified")
        required_urls = pending.get("required_callback_urls") if isinstance(pending.get("required_callback_urls"), dict) else {}
        if required_urls.get("stripe_webhook") != "https://app.jiejing.shop/billing/webhook":
            return fail(f"Stripe webhook URL should be prepared: {required_urls}")
    finally:
        _restore_env(previous)

    previous = _set_ready_env()
    try:
        ready = _build()
        if ready.get("status") != "ready_for_owner_approval":
            return fail(f"all evidence flags should prepare owner approval: {ready.get('summary')}")
        summary = ready.get("summary") if isinstance(ready.get("summary"), dict) else {}
        if summary.get("ready_count") != summary.get("total_count") or summary.get("blocked_count") != 0:
            return fail(f"all stages should be ready in fixture: {summary}")
        if ready.get("public_paid_launch_allowed") is not False or ready.get("charge_now_allowed") is not False:
            return fail("even ready preflight must not directly allow paid launch or charging")
        origin = ready.get("origin_lock") if isinstance(ready.get("origin_lock"), dict) else {}
        if origin.get("direct_origin_ip_blocked") is not True:
            return fail("origin lock evidence should require direct origin IP block")
        waf = ready.get("waf_edge") if isinstance(ready.get("waf_edge"), dict) else {}
        if waf.get("cloudflare_free_baseline_ready") is not True or waf.get("managed_waf_rules_enabled") is not False:
            return fail(f"Cloudflare free WAF baseline should be ready without paid managed rules: {waf}")
        callbacks = ready.get("callback_cutover") if isinstance(ready.get("callback_cutover"), dict) else {}
        if callbacks.get("stripe_urls_on_stable_domain") is not True or callbacks.get("ebay_callback_verified") is not True:
            return fail(f"callback evidence should be ready: {callbacks}")
        serialized = json.dumps(ready, ensure_ascii=False).lower()
        for forbidden in ("access_token", "refresh_token=", "client_secret=", "api_key=", "password=", "sk_live_", "whsec_"):
            if forbidden in serialized:
                return fail(f"edge preflight leaked forbidden marker: {forbidden}")
    finally:
        _restore_env(previous)

    output = subprocess.check_output(
        [
            sys.executable,
            str(ROOT / "tools" / "jiejing_edge_cutover_preflight.py"),
            "--domain",
            "jiejing.shop",
            "--registration-status",
            "registered",
            "--provider",
            "cloudflare",
        ],
        cwd=ROOT,
        text=True,
    )
    packet = (json.loads(output).get("edge_cutover_preflight") or {})
    if packet.get("selected_edge_provider") != "cloudflare":
        return fail("CLI should preserve selected provider")
    if packet.get("status") != "blocked":
        return fail("CLI active-domain fixture should stay blocked until DNS/WAF/callback evidence")
    cli_summary = packet.get("summary") if isinstance(packet.get("summary"), dict) else {}
    if cli_summary.get("domain_registered") is not True:
        return fail(f"CLI active-domain fixture should mark domain registered: {cli_summary}")

    print("PASS jiejing_edge_cutover_preflight")
    return 0


def _build() -> dict[str, object]:
    settings = SaaSSettings.from_env(db_path=OUT / "saas.sqlite", runtime_db_path=OUT / "runtime.sqlite", output_root=OUT, host="127.0.0.1", port=8788)
    return build_edge_cutover_preflight(settings)


def _set_pending_env() -> dict[str, str | None]:
    previous = {key: os.environ.get(key) for key in ENV_KEYS}
    _clear_env()
    os.environ.update(
        {
            "JIEJING_SAAS_ENV": "staging",
            "JIEJING_SELECTED_DOMAIN": "jiejing.shop",
            "JIEJING_DOMAIN_REGISTRATION_STATUS": "registry_name_review_pending",
            "JIEJING_EDGE_PROVIDER": "cloudflare",
        }
    )
    return previous


def _set_ready_env() -> dict[str, str | None]:
    previous = {key: os.environ.get(key) for key in ENV_KEYS}
    _clear_env()
    stable = "https://app.jiejing.shop"
    os.environ.update(
        {
            "JIEJING_SAAS_ENV": "staging",
            "JIEJING_SELECTED_DOMAIN": "jiejing.shop",
            "JIEJING_DOMAIN_REGISTRATION_STATUS": "registered",
            "JIEJING_PUBLIC_BASE_URL": stable,
            "JIEJING_STABLE_DOMAIN": "app.jiejing.shop",
            "JIEJING_CORS_ORIGIN": stable,
            "JIEJING_DOMAIN_DNS_VERIFIED": "1",
            "JIEJING_TLS_VERIFIED": "1",
            "JIEJING_EBAY_CALLBACK_VERIFIED": "1",
            "JIEJING_DEPLOYMENT_HARDENED": "1",
            "JIEJING_SECURITY_HEADERS_VERIFIED": "1",
            "JIEJING_EDGE_PROVIDER": "cloudflare",
            "JIEJING_EDGE_DOMAIN_ADDED": "1",
            "JIEJING_EDGE_DNS_PROXIED": "1",
            "JIEJING_WAF_MANAGED_RULES_ENABLED": "0",
            "JIEJING_BOT_PROTECTION_ENABLED": "1",
            "JIEJING_WAF_RATE_LIMITS_ENABLED": "1",
            "JIEJING_AI_CRAWLER_CONTROL_ENABLED": "1",
            "JIEJING_TURNSTILE_OR_CHALLENGE_ENABLED": "1",
            "JIEJING_ORIGIN_HTTP_HTTPS_EDGE_ONLY": "1",
            "JIEJING_ORIGIN_DIRECT_IP_BLOCKED": "1",
            "JIEJING_ORIGIN_SSH_OPERATOR_ONLY": "1",
            "JIEJING_ORIGIN_EDGE_IP_ALLOWLIST_SOURCE": "cloudflare_current_ip_ranges",
            "JIEJING_BILLING_SUCCESS_URL": f"{stable}/billing/success",
            "JIEJING_BILLING_CANCEL_URL": f"{stable}/billing/cancel",
            "JIEJING_BILLING_PORTAL_RETURN_URL": f"{stable}/settings/billing",
            "JIEJING_BILLING_WEBHOOK_URL": f"{stable}/billing/webhook",
            "JIEJING_STRIPE_CALLBACK_URLS_VERIFIED": "1",
        }
    )
    return previous


def _clear_env() -> None:
    for key in ENV_KEYS:
        os.environ.pop(key, None)


def _restore_env(previous: dict[str, str | None]) -> None:
    _clear_env()
    for key, value in previous.items():
        if value is not None:
            os.environ[key] = value


if __name__ == "__main__":
    raise SystemExit(main())
