#!/usr/bin/env python3
"""P0 security regression checks for Jiejing SaaS backend boundaries."""

from __future__ import annotations

import io
import json
import os
import sys
from contextlib import redirect_stderr
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.api_server import SaaSBackendHandler  # noqa: E402
from jiejing_saas.config import SaaSSettings  # noqa: E402
from jiejing_saas.ebay_credential_preflight import build_ebay_credential_preflight  # noqa: E402
from jiejing_saas.ebay_http_client import EbayReadOnlyHttpClient, build_ebay_http_client_contract  # noqa: E402
from jiejing_saas.readiness import build_product_readiness  # noqa: E402
from jiejing_saas.repository import SaaSRepository  # noqa: E402
from jiejing_runtime.api_server import RuntimeApiHandler  # noqa: E402


OUT = ROOT / "output" / "test-p0-security-guardrails"
ENV_KEYS = (
    "JIEJING_SAAS_ENV",
    "JIEJING_RUNTIME_ENV",
    "JIEJING_SAAS_SESSION_SECRET",
    "JIEJING_CORS_ORIGIN",
    "JIEJING_EBAY_READ_ONLY_LIVE",
    "JIEJING_EBAY_ACCESS_TOKEN",
    "EBAY_ACCESS_TOKEN",
    "JIEJING_EBAY_TOKEN_REFRESH_LIVE",
    "JIEJING_EBAY_CLIENT_ID",
    "JIEJING_EBAY_CLIENT_SECRET",
    "JIEJING_EBAY_REFRESH_TOKEN",
    "JIEJING_ENABLE_HERMES_EBAY_BRIDGE",
    "JIEJING_ENABLE_HERMES_WSL_SECRET_LOOKUP",
    "JIEJING_EBAY_LOCAL_TOKEN_STORE_ENABLED",
    "JIEJING_VAULT_LOCAL_SECRET_RESOLVER_ENABLED",
    "JIEJING_VAULT_ENABLED",
    "JIEJING_VAULT_PROVIDER",
    "JIEJING_VAULT_LIVE_RESOLVE_ENABLED",
    "JIEJING_ENABLE_DEMO_SESSION_BOOTSTRAP",
    "JIEJING_OPERATOR_BOOTSTRAP_SECRET",
)


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    previous = {key: os.environ.get(key) for key in ENV_KEYS}
    try:
        OUT.mkdir(parents=True, exist_ok=True)
        for check in (
            _check_cors_readiness_guardrail,
            _check_cors_origin_resolution,
            _check_runtime_cors_origin_resolution,
            _check_staging_env_access_token_blocked,
            _check_staging_env_refresh_token_blocked,
            _check_preflight_env_access_token_blocked,
            _check_demo_session_staging_guard,
            _check_safe_access_log,
            _check_oauth_callback_html_surface,
            _check_public_diagnostics_are_summarized,
        ):
            result = check()
            if result != "ok":
                return fail(result)
        print("PASS jiejing_saas_p0_security_guardrails")
        return 0
    finally:
        _restore_env(previous)


def _check_cors_readiness_guardrail() -> str:
    _clear_env()
    os.environ["JIEJING_SAAS_ENV"] = "production"
    os.environ["JIEJING_SAAS_SESSION_SECRET"] = "production-like-test-secret-that-is-long-enough"
    settings = _settings("cors-wildcard", port=8840)
    repo = SaaSRepository(settings.db_path)
    repo.initialize()
    readiness = build_product_readiness(settings, repo)
    cors_item = _readiness_item(readiness, "cors_origin")
    if cors_item.get("status") != "blocked_wildcard_in_production" or cors_item.get("severity") != "blocker":
        return "production wildcard CORS should be a readiness blocker"

    _clear_env()
    os.environ["JIEJING_SAAS_ENV"] = "production"
    os.environ["JIEJING_SAAS_SESSION_SECRET"] = "production-like-test-secret-that-is-long-enough"
    os.environ["JIEJING_CORS_ORIGIN"] = "https://app.jiejing.example"
    settings = _settings("cors-exact", port=8841)
    repo = SaaSRepository(settings.db_path)
    repo.initialize()
    readiness = build_product_readiness(settings, repo)
    cors_item = _readiness_item(readiness, "cors_origin")
    if cors_item.get("status") != "ready":
        return "exact production CORS origin should pass the CORS readiness item"
    return "ok"


def _check_cors_origin_resolution() -> str:
    _clear_env()
    os.environ["JIEJING_SAAS_ENV"] = "production"
    os.environ["JIEJING_CORS_ORIGIN"] = "https://app.jiejing.example,https://admin.jiejing.example"
    settings = _settings("cors-resolution", port=8842)
    allowed = _fake_handler(settings=settings, origin="https://admin.jiejing.example")
    if SaaSBackendHandler._resolved_cors_origin(allowed) != "https://admin.jiejing.example":
        return "CORS should echo only a configured production origin"
    denied = _fake_handler(settings=settings, origin="https://evil.example")
    if SaaSBackendHandler._resolved_cors_origin(denied) is not None:
        return "CORS should not echo an unconfigured production origin"
    return "ok"


def _check_runtime_cors_origin_resolution() -> str:
    _clear_env()
    os.environ["JIEJING_RUNTIME_ENV"] = "production"
    wildcard = _fake_handler(settings=None, origin="https://evil.example")
    if RuntimeApiHandler._resolved_cors_origin(wildcard) is not None:
        return "Runtime API should not echo wildcard CORS in production-like mode"
    os.environ["JIEJING_CORS_ORIGIN"] = "https://runtime.jiejing.example"
    allowed = _fake_handler(settings=None, origin="https://runtime.jiejing.example")
    if RuntimeApiHandler._resolved_cors_origin(allowed) != "https://runtime.jiejing.example":
        return "Runtime API should echo only a configured production origin"
    _clear_env()
    local = _fake_handler(settings=None, origin="https://local.example")
    if RuntimeApiHandler._resolved_cors_origin(local) != "*":
        return "Runtime API should preserve local development wildcard compatibility"
    return "ok"


def _check_staging_env_access_token_blocked() -> str:
    _clear_env()
    os.environ["JIEJING_SAAS_ENV"] = "staging"
    os.environ["JIEJING_EBAY_READ_ONLY_LIVE"] = "true"
    os.environ["JIEJING_EBAY_ACCESS_TOKEN"] = "P0-ENV-ACCESS-TOKEN-MUST-NOT-LEAK"
    os.environ["JIEJING_ENABLE_HERMES_EBAY_BRIDGE"] = "false"
    os.environ["JIEJING_EBAY_LOCAL_TOKEN_STORE_ENABLED"] = "false"
    os.environ["JIEJING_VAULT_LOCAL_SECRET_RESOLVER_ENABLED"] = "false"
    settings = _settings("staging-env-token", port=8843)
    contract = build_ebay_http_client_contract(settings)
    blockers = set(contract.get("blocked_by") or [])
    token_sources = contract.get("token_sources") if isinstance(contract.get("token_sources"), dict) else {}
    if contract.get("status") == "live_ready":
        return "staging env access token must not make HTTP client live-ready"
    if "JIEJING_EBAY_ENV_ACCESS_TOKEN_DISABLED_IN_PRODUCTION" not in blockers:
        return "staging env access token blocker should be explicit"
    if token_sources.get("env_access_token_allowed") is not False or token_sources.get("env_access_token_blocked") is not True:
        return "HTTP contract should expose sanitized env-token allowed/blocked flags"
    resolved = EbayReadOnlyHttpClient(settings)._resolve_access_token()
    if resolved.get("ok") is not False:
        return "staging env access token must not resolve into a usable eBay token"
    if "JIEJING_EBAY_ENV_ACCESS_TOKEN_DISABLED_IN_PRODUCTION" not in set(resolved.get("blocked_by") or []):
        return "staging token resolution should return the production env-token blocker"
    serialized = json.dumps({"contract": contract, "resolved": resolved}, ensure_ascii=False)
    if "P0-ENV-ACCESS-TOKEN-MUST-NOT-LEAK" in serialized:
        return "staging env access token leaked into public contract output"
    return "ok"


def _check_preflight_env_access_token_blocked() -> str:
    _clear_env()
    os.environ["JIEJING_SAAS_ENV"] = "staging"
    os.environ["JIEJING_EBAY_READ_ONLY_LIVE"] = "true"
    os.environ["JIEJING_EBAY_ACCESS_TOKEN"] = "P0-PREFLIGHT-TOKEN-MUST-NOT-LEAK"
    os.environ["JIEJING_ENABLE_HERMES_EBAY_BRIDGE"] = "false"
    os.environ["JIEJING_EBAY_LOCAL_TOKEN_STORE_ENABLED"] = "false"
    settings = _settings("preflight-env-token", port=8844)
    preflight = build_ebay_credential_preflight(
        settings=settings,
        store={"store_id": "store_p0", "platform": "ebay", "store_name": "P0 Store", "marketplace": "EBAY_US"},
        secret_refs=[],
        connections=[],
    )
    if preflight.get("token_mode") == "backend_env_access_token":
        return "preflight must not report staging env access token as usable"
    if "JIEJING_EBAY_ENV_ACCESS_TOKEN_DISABLED_IN_PRODUCTION" not in set(preflight.get("blocked_by") or []):
        return "preflight should surface the staging env-token blocker"
    if "P0-PREFLIGHT-TOKEN-MUST-NOT-LEAK" in json.dumps(preflight, ensure_ascii=False):
        return "preflight leaked an env access token"
    return "ok"


def _check_staging_env_refresh_token_blocked() -> str:
    _clear_env()
    os.environ["JIEJING_SAAS_ENV"] = "staging"
    os.environ["JIEJING_EBAY_READ_ONLY_LIVE"] = "true"
    os.environ["JIEJING_EBAY_TOKEN_REFRESH_LIVE"] = "true"
    os.environ["JIEJING_EBAY_CLIENT_ID"] = "P0-CLIENT-ID"
    os.environ["JIEJING_EBAY_CLIENT_SECRET"] = "P0-CLIENT-SECRET-MUST-NOT-LEAK"
    os.environ["JIEJING_EBAY_REFRESH_TOKEN"] = "P0-REFRESH-TOKEN-MUST-NOT-LEAK"
    os.environ["JIEJING_ENABLE_HERMES_EBAY_BRIDGE"] = "false"
    os.environ["JIEJING_EBAY_LOCAL_TOKEN_STORE_ENABLED"] = "false"
    settings = _settings("staging-env-refresh-token", port=8846)
    contract = build_ebay_http_client_contract(settings)
    blockers = set(contract.get("blocked_by") or [])
    if contract.get("status") == "live_ready":
        return "staging env refresh token must not make HTTP client live-ready"
    if "JIEJING_EBAY_ENV_REFRESH_TOKEN_DISABLED_IN_PRODUCTION" not in blockers:
        return "staging env refresh token blocker should be explicit"
    serialized = json.dumps(contract, ensure_ascii=False)
    if "P0-REFRESH-TOKEN-MUST-NOT-LEAK" in serialized or "P0-CLIENT-SECRET-MUST-NOT-LEAK" in serialized:
        return "staging env refresh token or client secret leaked into public contract output"
    return "ok"


def _check_demo_session_staging_guard() -> str:
    _clear_env()
    os.environ["JIEJING_SAAS_ENV"] = "staging"
    settings = _settings("demo-session-staging", port=8848)
    blocked = _fake_handler(settings=settings, origin="")
    if SaaSBackendHandler._demo_session_bootstrap_allowed(blocked) is not False:
        return "staging demo-session bootstrap should be disabled by default"
    os.environ["JIEJING_OPERATOR_BOOTSTRAP_SECRET"] = "operator-secret-unit-test"
    allowed = _fake_handler(settings=settings, origin="")
    allowed.headers = {"x-jiejing-operator-secret": "operator-secret-unit-test"}
    if SaaSBackendHandler._demo_session_bootstrap_allowed(allowed) is not True:
        return "staging demo-session bootstrap should allow an explicit operator secret"
    wrong = _fake_handler(settings=settings, origin="")
    wrong.headers = {"x-jiejing-operator-secret": "wrong-secret"}
    if SaaSBackendHandler._demo_session_bootstrap_allowed(wrong) is not False:
        return "staging demo-session bootstrap should reject an invalid operator secret"
    _clear_env()
    os.environ["JIEJING_SAAS_ENV"] = "local_dev"
    local_settings = _settings("demo-session-local", port=8849)
    local = _fake_handler(settings=local_settings, origin="")
    if SaaSBackendHandler._demo_session_bootstrap_allowed(local) is not True:
        return "local_dev demo-session bootstrap should remain available for regression tests"
    return "ok"


def _check_safe_access_log() -> str:
    _clear_env()
    os.environ["JIEJING_SAAS_ENV"] = "production"
    settings = _settings("safe-access-log", port=8845)
    fake = _fake_handler(settings=settings, origin="")
    fake._safe_access_log_enabled = lambda: True
    fake.path = "/oauth/ebay/callback?state=STATE-MUST-NOT-LOG&code=CODE-MUST-NOT-LOG"
    fake.command = "GET"
    fake.client_address = ("203.0.113.10", 55123)
    buffer = io.StringIO()
    with redirect_stderr(buffer):
        SaaSBackendHandler.log_message(fake, '"%s" %s %s', fake.path, 200, 123)
    log_line = buffer.getvalue().strip()
    event = json.loads(log_line)
    if event.get("event") != "http_access" or event.get("path") != "/oauth/ebay/callback":
        return "access log should record a safe path-only HTTP event"
    if "STATE-MUST-NOT-LOG" in log_line or "CODE-MUST-NOT-LOG" in log_line:
        return "access log leaked OAuth query parameters"
    if "203.0.113.10" in log_line or "client_ip" in event:
        return "production access log must omit the raw client IP for every route"
    if any(key.lower() in {"authorization", "body", "headers", "query"} for key in event):
        return "access log must not include headers, query, body, or authorization fields"
    if event.get("secret_exposed") is not False:
        return "access log event should mark secret_exposed false"
    return "ok"


def _check_oauth_callback_html_surface() -> str:
    _clear_env()
    settings = _settings("oauth-callback-html", port=8847)
    fake = _fake_handler(settings=settings, origin="")
    fake.headers = {"accept": "text/html,application/xhtml+xml"}
    if SaaSBackendHandler._wants_html_response(fake) is not True:
        return "browser OAuth callback should prefer a product HTML response"
    fake.headers = {"accept": "application/json, text/html"}
    if SaaSBackendHandler._wants_html_response(fake) is not False:
        return "API clients should keep the JSON OAuth callback response"
    result = {
        "status": "callback_exchange_completed",
        "summary": "SUMMARY-INTERNAL-MUST-NOT-LEAK",
        "company_id": "COMPANY-ID-MUST-NOT-LEAK",
        "store_id": "STORE-ID-MUST-NOT-LEAK",
        "oauth_request_id": "OAUTH-REQUEST-ID-MUST-NOT-LEAK",
        "connection_id": "CONNECTION-ID-MUST-NOT-LEAK",
        "secret_ref": {"secret_ref": "SECRET-REF-MUST-NOT-LEAK"},
        "backend_connection_binding": {
            "connection_id": "BINDING-CONNECTION-ID-MUST-NOT-LEAK",
            "connection_id_sha256": "BINDING-HASH-MUST-NOT-LEAK",
        },
        "token_exchange_performed": True,
        "vault_write_performed": True,
        "real_platform_writes_enabled": False,
        "state": "STATE-MUST-NOT-LEAK",
        "code": "CODE-MUST-NOT-LEAK",
        "access_token": "ACCESS-TOKEN-MUST-NOT-LEAK",
        "refresh_token": "REFRESH-TOKEN-MUST-NOT-LEAK",
        "client_secret": "CLIENT-SECRET-MUST-NOT-LEAK",
    }
    html = SaaSBackendHandler._oauth_callback_public_html(fake, result)
    for forbidden in (
        "STATE-MUST-NOT-LEAK",
        "CODE-MUST-NOT-LEAK",
        "ACCESS-TOKEN-MUST-NOT-LEAK",
        "REFRESH-TOKEN-MUST-NOT-LEAK",
        "CLIENT-SECRET-MUST-NOT-LEAK",
        "SUMMARY-INTERNAL-MUST-NOT-LEAK",
        "COMPANY-ID-MUST-NOT-LEAK",
        "STORE-ID-MUST-NOT-LEAK",
        "OAUTH-REQUEST-ID-MUST-NOT-LEAK",
        "CONNECTION-ID-MUST-NOT-LEAK",
        "SECRET-REF-MUST-NOT-LEAK",
        "BINDING-CONNECTION-ID-MUST-NOT-LEAK",
        "BINDING-HASH-MUST-NOT-LEAK",
    ):
        if forbidden in html:
            return f"OAuth callback HTML leaked sensitive value: {forbidden}"
    if "eBay 只读授权已完成" not in html or "返回捷境工作台" not in html:
        return "OAuth callback HTML should be a merchant-facing completion page"
    if "access token、refresh token、授权码或 state" not in html:
        return "OAuth callback HTML should explain the no-token browser boundary"
    public_result_builder = getattr(SaaSBackendHandler, "_oauth_callback_public_result", None)
    if not callable(public_result_builder):
        return "OAuth callback JSON must pass through a fixed public allowlist"
    public_result = public_result_builder(fake, result)
    public_json = json.dumps(public_result, ensure_ascii=False)
    for forbidden in (
        "SUMMARY-INTERNAL-MUST-NOT-LEAK",
        "COMPANY-ID-MUST-NOT-LEAK",
        "STORE-ID-MUST-NOT-LEAK",
        "OAUTH-REQUEST-ID-MUST-NOT-LEAK",
        "CONNECTION-ID-MUST-NOT-LEAK",
        "SECRET-REF-MUST-NOT-LEAK",
        "BINDING-CONNECTION-ID-MUST-NOT-LEAK",
        "BINDING-HASH-MUST-NOT-LEAK",
    ):
        if forbidden in public_json:
            return f"OAuth callback JSON leaked internal identifier: {forbidden}"
    if set(public_result) - {
        "status",
        "authorization_kind",
        "completed",
        "token_exchange_performed",
        "vault_write_performed",
        "real_platform_writes_enabled",
        "next_step",
        "secret_exposed",
    }:
        return "OAuth callback JSON must expose only the fixed public allowlist"
    return "ok"


def _check_public_diagnostics_are_summarized() -> str:
    _clear_env()
    os.environ["JIEJING_SAAS_ENV"] = "production"
    settings = _settings("public-diagnostics-summary", port=8850)
    readiness = {
        "service": "jiejing-saas-backend",
        "readiness_version": "unit-test",
        "environment": "production",
        "production_ready": False,
        "beta_ready": True,
        "can_accept_real_customers": False,
        "real_platform_writes_enabled": True,
        "requested_real_platform_writes": True,
        "blocker_count": 1,
        "warning_count": 1,
        "items": [
            {"key": "safe_warning", "label": "Safe warning", "status": "warning", "severity": "warning", "detail": "safe public detail"},
            {"key": "internal_ready", "label": "Internal ready", "status": "ready", "severity": "info", "detail": "INTERNAL-READY-DETAIL-MUST-NOT-LEAK"},
        ],
        "product_evidence": {
            "latest_ebay_packet_status": "ready",
            "latest_ebay_packet_source_mode": "official",
            "latest_ebay_packet_present_resource_keys": ["inventory"],
            "latest_ebay_packet_missing_resource_keys": ["token_refresh"],
            "latest_ebay_packet_id": "packet-visible-only-after-login",
            "latest_ebay_packet_created_at": "2026-06-20T00:00:00Z",
            "latest_ebay_packet_internal_path": "C:\\secret\\packet.json",
            "ebay_token_refresh_success_count": 0,
            "model_secret_refs": 1,
            "ebay_secret_refs": 1,
        },
        "provider_status": {
            "billing": {
                "provider": "stripe_live",
                "billing_ready_for_paid_launch": False,
                "quota_enforcement_enabled": True,
                "domestic_payment": {
                    "provider": "wechat_pay_native",
                    "checkout_mode": "native_qr",
                    "status": "configuration_in_progress",
                    "configured_component_count": 7,
                    "required_component_count": 8,
                    "signed_callback_implemented": True,
                    "real_order_creation_implemented": False,
                    "real_checkout_ready": False,
                    "api_v3_key": "WECHAT-API-V3-KEY-MUST-NOT-LEAK",
                },
                "webhook_secret_present": True,
                "webhook_secret": "STRIPE-WEBHOOK-SECRET-MUST-NOT-LEAK",
            },
            "model_value": {
                "ready_for_paid_value_claim": True,
                "live_model_report_types": ["market.report", "listing.package"],
                "blockers": [],
                "model_api_key": "MODEL-KEY-MUST-NOT-LEAK",
            },
            "ai_ceo_platform_model": {
                "enabled": True,
                "configured": True,
                "status": "ready",
                "provider": "deepseek",
                "model": "deepseek-v4-pro",
                "trial_request_limit": 20,
                "trial_duration_days": 7,
                "trial_quota_scope": "account_trial_window",
                "usage_owner": "jiejing_platform_trial",
                "quota_checked_by_backend": True,
                "hard_stop_on_exhaustion": True,
                "byok_bypasses_platform_trial": True,
                "model_api_key": "PLATFORM-MODEL-KEY-MUST-NOT-LEAK",
            },
            "public_search": {
                "provider": "tavily",
                "configured": True,
                "endpoint_host": "api.tavily.com",
                "credential_present": True,
                "credential_source": "TAVILY-SECRET-SOURCE-MUST-NOT-LEAK",
                "search_api_key": "TAVILY-KEY-MUST-NOT-LEAK",
                "ai_ceo_realtime_search_enabled": True,
                "builtin_public_web_fallback_enabled": True,
                "builtin_stock_quote_fallback_enabled": True,
            },
            "media_generation": {
                "contract_version": "unit-media-readiness",
                "configured": True,
                "status": "live_generation_ready_waiting_asset_review",
                "live_generation_enabled": True,
                "live_image_generation_enabled": True,
                "live_video_generation_enabled": True,
                "live_provider_calls_allowed": True,
                "asset_manifest_required": True,
                "asset_review_required": True,
                "fact_review_required": True,
                "human_review_required_before_listing": True,
                "cost_guard_required": True,
                "spend_now_allowed": True,
                "listing_use_requires_review": False,
                "customer_visible_summary": "素材通道可用，仍需审核。",
                "next_action": "审核素材清单后再用于 Listing。",
                "media_api_key": "MEDIA-KEY-MUST-NOT-LEAK",
                "credential_source": "MEDIA-SECRET-SOURCE-MUST-NOT-LEAK",
                "raw_provider_response": "RAW-MEDIA-PROVIDER-RESPONSE-MUST-NOT-LEAK",
            },
        },
        "operational_health": {"status": "ready", "database_url_public": "postgres://secret@db"},
    }
    unauth = SaaSBackendHandler._public_readiness_summary(readiness, authenticated=False)
    auth = SaaSBackendHandler._public_readiness_summary(readiness, authenticated=True)
    unauth_serialized = json.dumps(unauth, ensure_ascii=False)
    auth_serialized = json.dumps(auth, ensure_ascii=False)
    if unauth.get("detail_scope") != "public_summary" or not unauth.get("internal_detail_required"):
        return "public readiness should be marked as a summary with internal details withheld"
    if "packet-visible-only-after-login" in unauth_serialized:
        return "unauthenticated readiness summary leaked packet id"
    if auth.get("product_evidence", {}).get("latest_ebay_packet_id") != "packet-visible-only-after-login":
        return "authenticated readiness summary should keep safe packet identity evidence"
    for serialized in (unauth_serialized, auth_serialized):
        for forbidden in (
            "INTERNAL-READY-DETAIL-MUST-NOT-LEAK",
            "C:\\secret\\packet.json",
            "STRIPE-WEBHOOK-SECRET-MUST-NOT-LEAK",
            "WECHAT-API-V3-KEY-MUST-NOT-LEAK",
            "MODEL-KEY-MUST-NOT-LEAK",
            "PLATFORM-MODEL-KEY-MUST-NOT-LEAK",
            "TAVILY-SECRET-SOURCE-MUST-NOT-LEAK",
            "TAVILY-KEY-MUST-NOT-LEAK",
            "MEDIA-KEY-MUST-NOT-LEAK",
            "MEDIA-SECRET-SOURCE-MUST-NOT-LEAK",
            "RAW-MEDIA-PROVIDER-RESPONSE-MUST-NOT-LEAK",
            "postgres://secret@db",
        ):
            if forbidden in serialized:
                return f"public readiness summary leaked internal diagnostic value: {forbidden}"
    search_summary = unauth.get("provider_status", {}).get("public_search", {})
    if search_summary.get("configured") is not True or search_summary.get("credential_present") is not True:
        return "public readiness summary should expose non-secret public search readiness"
    if "credential_source" in search_summary:
        return "public readiness summary must not expose public search credential source"
    billing_summary = unauth.get("provider_status", {}).get("billing", {})
    if (
        billing_summary.get("billing_ready_for_paid_launch") is not False
        or billing_summary.get("quota_enforcement_enabled") is not True
        or billing_summary.get("public_charging_allowed") is not False
        or billing_summary.get("triggers_real_charge") is not False
        or billing_summary.get("frontend_can_grant_quota") is not False
    ):
        return "public readiness billing summary should expose safe launch truth without enabling charges or frontend quota"
    billing_launch_path = billing_summary.get("merchant_launch_path") if isinstance(billing_summary.get("merchant_launch_path"), dict) else {}
    if (
        billing_launch_path.get("backend_confirmation_required_before_entitlement") is not True
        or billing_launch_path.get("frontend_can_grant_entitlement") is not False
        or billing_launch_path.get("quota_grant_source") != "backend_subscription_state"
    ):
        return "public readiness billing launch path should keep entitlement and quota behind backend billing state"
    domestic_summary = billing_summary.get("domestic_payment") if isinstance(billing_summary.get("domestic_payment"), dict) else {}
    if (
        domestic_summary.get("provider") != "wechat_pay_native"
        or domestic_summary.get("configured_component_count") != 0
        or domestic_summary.get("required_component_count") != 0
        or domestic_summary.get("charge_now_allowed") is not False
        or domestic_summary.get("frontend_gets_payment_secret") is not False
    ):
        return "malformed public readiness payment counts must fail closed without enabling charges or secrets"
    for internal_capability in (
        "signed_callback_implemented",
        "real_order_creation_implemented",
        "real_checkout_ready",
    ):
        if internal_capability in domestic_summary:
            return f"public readiness must not expose payment implementation capability {internal_capability}"
    platform_model_summary = unauth.get("provider_status", {}).get("ai_ceo_platform_model", {})
    if (
        platform_model_summary.get("configured") is not True
        or platform_model_summary.get("trial_request_limit") != 20
        or platform_model_summary.get("trial_duration_days") != 7
        or platform_model_summary.get("trial_quota_scope") != "account_trial_window"
        or platform_model_summary.get("usage_owner") != "jiejing_platform_trial"
        or platform_model_summary.get("quota_checked_by_backend") is not True
        or platform_model_summary.get("hard_stop_on_exhaustion") is not True
        or platform_model_summary.get("byok_bypasses_platform_trial") is not True
        or platform_model_summary.get("frontend_gets_model_api_key") is not False
        or platform_model_summary.get("frontend_can_grant_quota") is not False
    ):
        return "public readiness platform model summary should expose only safe trial status"
    model_value_summary = unauth.get("provider_status", {}).get("model_value", {})
    if (
        model_value_summary.get("status") != "ready"
        or model_value_summary.get("ready") is not True
        or model_value_summary.get("live_model_report_types") != ["market.report", "listing.package"]
        or model_value_summary.get("blocker_count") != 0
    ):
        return "public readiness model value summary should map the current gate contract consistently"
    media_summary = unauth.get("provider_status", {}).get("media_generation", {})
    if (
        media_summary.get("configured") is not True
        or media_summary.get("live_image_generation_enabled") is not True
        or media_summary.get("live_video_generation_enabled") is not True
        or media_summary.get("asset_manifest_required") is not True
        or media_summary.get("asset_review_required") is not True
        or media_summary.get("spend_now_allowed") is not False
        or media_summary.get("listing_use_requires_review") is not True
        or media_summary.get("frontend_gets_media_api_key") is not False
        or media_summary.get("runtime_gets_raw_secret") is not False
        or media_summary.get("reports_get_raw_provider_response") is not False
        or media_summary.get("raw_provider_response_stored") is not False
    ):
        return "public readiness media summary should expose only review-gated media status without provider secrets"
    if "credential_source" in media_summary or "media_api_key" in media_summary or "raw_provider_response" in media_summary:
        return "public readiness media summary leaked internal media provider fields"

    fake = _fake_handler(settings=settings, origin="")
    health = {
        "status": "ready",
        "database_live_probe": {"status": "ready", "database_url": "postgres://secret@db", "engine": "postgresql"},
        "queue_runtime": {"status": "ready", "provider": "postgres_durable", "internal_queue_table": "jobs"},
        "worker_runtime": {"heartbeat_status": "ready", "worker_id": "WORKER-ID-MUST-NOT-LEAK", "last_heartbeat_at": "2026-06-20T00:00:00Z"},
    }
    health_summary = SaaSBackendHandler._public_operational_health_summary(fake, health, authenticated=False)
    health_serialized = json.dumps(health_summary, ensure_ascii=False)
    if health_summary.get("detail_scope") != "public_summary" or not health_summary.get("internal_detail_required"):
        return "public operational health should be marked as a summary with internal details withheld"
    for forbidden in ("postgres://secret@db", "postgresql", "postgres_durable", "WORKER-ID-MUST-NOT-LEAK", "jobs"):
        if forbidden in health_serialized:
            return f"public operational health summary leaked internal diagnostic value: {forbidden}"
    return "ok"


def _settings(case_key: str, *, port: int) -> SaaSSettings:
    return SaaSSettings.from_env(
        db_path=OUT / f"{case_key}.sqlite",
        runtime_db_path=OUT / f"{case_key}-runtime.sqlite",
        output_root=OUT / case_key,
        host="127.0.0.1",
        port=port,
    )


def _readiness_item(readiness: dict[str, Any], key: str) -> dict[str, Any]:
    for item in readiness.get("items") or []:
        if isinstance(item, dict) and item.get("key") == key:
            return item
    return {}


def _fake_handler(*, settings: SaaSSettings | None, origin: str) -> Any:
    class FakeHandler:
        pass

    fake = FakeHandler()
    fake.settings = settings
    fake.headers = {"origin": origin} if origin else {}
    return fake


def _clear_env() -> None:
    for key in ENV_KEYS:
        os.environ.pop(key, None)


def _restore_env(previous: dict[str, str | None]) -> None:
    for key, value in previous.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


if __name__ == "__main__":
    raise SystemExit(main())
