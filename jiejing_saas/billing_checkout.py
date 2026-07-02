"""Stripe Checkout and Customer Portal boundary for paid Jiejing SaaS.

This module intentionally starts with Stripe because Jiejing needs recurring
SaaS subscriptions, price IDs, signed webhooks, and a self-service portal. API
keys are read only inside the backend process and are never returned.
"""

from __future__ import annotations

import json
import os
import hashlib
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlparse, urlencode, urlunparse
from urllib.request import Request, urlopen

from .billing_webhook import TEST_BILLING_PROVIDERS, billing_plan_ids, build_billing_provider_contract
from .repository import SaaSRepository


STRIPE_API_VERSION = "2026-06-24.dahlia"
PLAN_KEYS = {"starter", "operator", "team"}
LOCAL_RETURN_HOSTS = {"localhost", "127.0.0.1", "::1"}


def build_billing_checkout_contract() -> dict[str, Any]:
    provider_contract = build_billing_provider_contract()
    provider = str(provider_contract.get("provider") or "").strip().lower()
    success_raw = _first_env("JIEJING_BILLING_SUCCESS_URL", "JIEJING_STRIPE_SUCCESS_URL")
    cancel_raw = _first_env("JIEJING_BILLING_CANCEL_URL", "JIEJING_STRIPE_CANCEL_URL")
    portal_raw = _first_env("JIEJING_BILLING_PORTAL_RETURN_URL", "JIEJING_STRIPE_PORTAL_RETURN_URL")
    success_url = _safe_billing_return_url(success_raw)
    cancel_url = _safe_billing_return_url(cancel_raw)
    portal_return_url = _safe_billing_return_url(portal_raw)
    supported_provider = provider == "stripe"
    test_provider = provider in TEST_BILLING_PROVIDERS
    checkout_supported_provider = supported_provider or test_provider
    api_key_configured = bool(_stripe_api_key())
    missing_plan_ids = list(provider_contract.get("missing_plan_ids") or [])
    blockers: list[str] = []
    if not checkout_supported_provider:
        blockers.append("stripe_billing_provider_not_selected")
    if supported_provider and not api_key_configured:
        blockers.append("stripe_api_key_not_configured")
    if supported_provider and missing_plan_ids:
        blockers.append("stripe_price_ids_missing")
    if test_provider and missing_plan_ids:
        blockers.append("billing_test_price_ids_missing")
    if checkout_supported_provider and not success_url:
        blockers.append("billing_success_url_not_configured")
    if checkout_supported_provider and success_raw and not success_url:
        blockers.append("billing_success_url_not_https_or_local")
    if checkout_supported_provider and not cancel_url:
        blockers.append("billing_cancel_url_not_configured")
    if checkout_supported_provider and cancel_raw and not cancel_url:
        blockers.append("billing_cancel_url_not_https_or_local")
    if checkout_supported_provider and not portal_return_url:
        blockers.append("billing_portal_return_url_not_configured")
    if checkout_supported_provider and portal_raw and not portal_return_url:
        blockers.append("billing_portal_return_url_not_https_or_local")
    checkout_ready = checkout_supported_provider and (api_key_configured or test_provider) and not missing_plan_ids and bool(success_url and cancel_url)
    portal_ready = checkout_supported_provider and (api_key_configured or test_provider) and bool(portal_return_url)
    return {
        "contract_version": "2026-06-18-stripe-checkout-portal-test-mode",
        "provider": provider or "not_selected",
        "provider_mode": "external_paid" if supported_provider else "test_mock" if test_provider else "not_selected",
        "stripe_api_version": STRIPE_API_VERSION,
        "checkout_sessions": {
            "implemented": True,
            "ready": checkout_ready,
            "mode": "subscription",
            "uses_price_ids": True,
            "metadata_company_id": True,
            "frontend_gets_api_key": False,
            "test_provider": test_provider,
            "creates_real_checkout_session": supported_provider,
            "calls_stripe_api": supported_provider,
            "triggers_real_charge": False,
            "can_run_without_stripe_account": test_provider,
        },
        "customer_portal": {
            "implemented": True,
            "ready": portal_ready,
            "frontend_gets_api_key": False,
            "test_provider": test_provider,
            "creates_real_customer_portal_session": supported_provider,
            "calls_stripe_api": supported_provider,
            "can_run_without_stripe_account": test_provider,
        },
        "urls": {
            "success_url_configured": bool(success_url),
            "cancel_url_configured": bool(cancel_url),
            "portal_return_url_configured": bool(portal_return_url),
            "success_url_https_or_local": bool(success_url),
            "cancel_url_https_or_local": bool(cancel_url),
            "portal_return_url_https_or_local": bool(portal_return_url),
            "request_override_must_match_configured_url": True,
        },
        "blockers": blockers,
        "ready_for_test_billing_rehearsal": test_provider and checkout_ready and portal_ready,
        "ready_for_paid_launch": supported_provider and checkout_ready and portal_ready,
        "charge_now_allowed": False,
        "secret_exposed": False,
    }


def create_stripe_checkout_session(
    repository: SaaSRepository,
    *,
    company_id: str,
    user_id: str,
    plan_key: str,
    success_url: str | None = None,
    cancel_url: str | None = None,
) -> dict[str, Any]:
    normalized_plan = str(plan_key or "").strip().lower()
    if normalized_plan not in PLAN_KEYS:
        return _blocked("billing_plan_key_not_supported", http_status=400)
    contract = build_billing_checkout_contract()
    if contract.get("provider") in TEST_BILLING_PROVIDERS:
        return _create_test_checkout_session(
            repository,
            company_id=company_id,
            user_id=user_id,
            plan_key=normalized_plan,
            success_url=success_url,
            cancel_url=cancel_url,
            contract=contract,
        )
    if contract.get("provider") != "stripe":
        return _blocked("stripe_billing_provider_not_selected", http_status=409, contract=contract)
    if not contract.get("checkout_sessions", {}).get("ready"):
        return _blocked_list(contract.get("blockers") or ["stripe_checkout_not_ready"], http_status=503, contract=contract)
    price_id = billing_plan_ids().get(normalized_plan) or ""
    if not price_id:
        return _blocked("stripe_price_id_missing", http_status=503, contract=contract)
    company = repository.get_company(company_id)
    if not company:
        return _blocked("company_not_found", http_status=404, contract=contract)
    subscription = repository.get_billing_subscription(company_id=company_id)
    customer_id = str(subscription.get("provider_customer_id") or "") if subscription else ""
    resolved_success = _resolve_configured_return_url(
        requested=success_url,
        configured=_success_url(),
        invalid_reason="billing_success_url_not_allowed",
    )
    if not resolved_success.get("ok"):
        return _blocked(str(resolved_success.get("reason") or "billing_success_url_not_allowed"), http_status=400, contract=contract)
    resolved_cancel = _resolve_configured_return_url(
        requested=cancel_url,
        configured=_cancel_url(),
        invalid_reason="billing_cancel_url_not_allowed",
    )
    if not resolved_cancel.get("ok"):
        return _blocked(str(resolved_cancel.get("reason") or "billing_cancel_url_not_allowed"), http_status=400, contract=contract)
    payload = {
        "mode": "subscription",
        "success_url": str(resolved_success.get("url") or ""),
        "cancel_url": str(resolved_cancel.get("url") or ""),
        "client_reference_id": company_id,
        "line_items[0][price]": price_id,
        "line_items[0][quantity]": "1",
        "metadata[company_id]": company_id,
        "metadata[jiejing_company_id]": company_id,
        "metadata[plan_key]": normalized_plan,
        "subscription_data[metadata][company_id]": company_id,
        "subscription_data[metadata][jiejing_company_id]": company_id,
        "subscription_data[metadata][plan_key]": normalized_plan,
    }
    if customer_id:
        payload["customer"] = customer_id
    else:
        payload["customer_creation"] = "always"
    response = _stripe_api_post("/v1/checkout/sessions", payload)
    if not response.get("ok"):
        return {**response, "contract": contract}
    session = response.get("response") if isinstance(response.get("response"), dict) else {}
    repository.write_audit(
        company_id=company_id,
        user_id=user_id,
        action_type="billing.checkout_session.created",
        target_type="billing_checkout_session",
        target_id=str(session.get("id") or ""),
        summary="Stripe Checkout session created for Jiejing subscription.",
        details={
            "provider": "stripe",
            "plan_key": normalized_plan,
            "session_id_present": bool(session.get("id")),
            "session_url_present": bool(session.get("url")),
            "frontend_gets_api_key": False,
            "secret_exposed": False,
        },
        actor_type="user",
    )
    return {
        "ok": True,
        "status": "checkout_session_created",
        "provider": "stripe",
        "plan_key": normalized_plan,
        "checkout_session": {
            "id": session.get("id") or "",
            "url": session.get("url") or "",
            "expires_at": session.get("expires_at") or None,
        },
        "frontend_gets_api_key": False,
        "secret_exposed": False,
    }


def create_stripe_customer_portal_session(
    repository: SaaSRepository,
    *,
    company_id: str,
    user_id: str,
    return_url: str | None = None,
) -> dict[str, Any]:
    contract = build_billing_checkout_contract()
    if contract.get("provider") in TEST_BILLING_PROVIDERS:
        return _create_test_customer_portal_session(
            repository,
            company_id=company_id,
            user_id=user_id,
            return_url=return_url,
            contract=contract,
        )
    if contract.get("provider") != "stripe":
        return _blocked("stripe_billing_provider_not_selected", http_status=409, contract=contract)
    if not contract.get("customer_portal", {}).get("ready"):
        return _blocked_list(contract.get("blockers") or ["stripe_customer_portal_not_ready"], http_status=503, contract=contract)
    subscription = repository.get_billing_subscription(company_id=company_id)
    customer_id = str(subscription.get("provider_customer_id") or "") if subscription else ""
    if not customer_id:
        return _blocked("stripe_customer_id_missing_for_portal", http_status=409, contract=contract)
    resolved_return = _resolve_configured_return_url(
        requested=return_url,
        configured=_portal_return_url(),
        invalid_reason="billing_portal_return_url_not_allowed",
    )
    if not resolved_return.get("ok"):
        return _blocked(str(resolved_return.get("reason") or "billing_portal_return_url_not_allowed"), http_status=400, contract=contract)
    payload = {
        "customer": customer_id,
        "return_url": str(resolved_return.get("url") or ""),
    }
    response = _stripe_api_post("/v1/billing_portal/sessions", payload)
    if not response.get("ok"):
        return {**response, "contract": contract}
    session = response.get("response") if isinstance(response.get("response"), dict) else {}
    repository.write_audit(
        company_id=company_id,
        user_id=user_id,
        action_type="billing.customer_portal.created",
        target_type="billing_customer_portal",
        target_id=str(session.get("id") or customer_id),
        summary="Stripe customer portal session created for Jiejing subscription management.",
        details={
            "provider": "stripe",
            "customer_id_present": True,
            "portal_url_present": bool(session.get("url")),
            "frontend_gets_api_key": False,
            "secret_exposed": False,
        },
        actor_type="user",
    )
    return {
        "ok": True,
        "status": "customer_portal_session_created",
        "provider": "stripe",
        "customer_portal": {
            "id": session.get("id") or "",
            "url": session.get("url") or "",
        },
        "frontend_gets_api_key": False,
        "secret_exposed": False,
    }


def _create_test_checkout_session(
    repository: SaaSRepository,
    *,
    company_id: str,
    user_id: str,
    plan_key: str,
    success_url: str | None,
    cancel_url: str | None,
    contract: dict[str, Any],
) -> dict[str, Any]:
    if not contract.get("checkout_sessions", {}).get("ready"):
        return _blocked_list(contract.get("blockers") or ["billing_test_checkout_not_ready"], http_status=503, contract=contract)
    price_id = billing_plan_ids().get(plan_key) or ""
    if not price_id:
        return _blocked("billing_test_price_id_missing", http_status=503, contract=contract)
    company = repository.get_company(company_id)
    if not company:
        return _blocked("company_not_found", http_status=404, contract=contract)
    resolved_success = _resolve_configured_return_url(
        requested=success_url,
        configured=_success_url(),
        invalid_reason="billing_success_url_not_allowed",
    )
    if not resolved_success.get("ok"):
        return _blocked(str(resolved_success.get("reason") or "billing_success_url_not_allowed"), http_status=400, contract=contract)
    resolved_cancel = _resolve_configured_return_url(
        requested=cancel_url,
        configured=_cancel_url(),
        invalid_reason="billing_cancel_url_not_allowed",
    )
    if not resolved_cancel.get("ok"):
        return _blocked(str(resolved_cancel.get("reason") or "billing_cancel_url_not_allowed"), http_status=400, contract=contract)
    session_id = _stable_mock_id("cs_mock", company_id, plan_key)
    checkout_url = _append_query(
        str(resolved_success.get("url") or ""),
        {
            "billing_test_session": session_id,
            "billing_test_plan": plan_key,
            "billing_test_mode": "1",
        },
    )
    repository.write_audit(
        company_id=company_id,
        user_id=user_id,
        action_type="billing.test_checkout_session.created",
        target_type="billing_checkout_session",
        target_id=session_id,
        summary="No-charge billing test Checkout session created for Jiejing subscription rehearsal.",
        details={
            "provider": str(contract.get("provider") or "stripe_test_mock"),
            "plan_key": plan_key,
            "provider_plan_id_present": bool(price_id),
            "session_url_present": bool(checkout_url),
            "creates_real_checkout_session": False,
            "calls_stripe_api": False,
            "triggers_real_charge": False,
            "charge_now_allowed": False,
            "frontend_gets_api_key": False,
            "secret_exposed": False,
        },
        actor_type="user",
    )
    return {
        "ok": True,
        "status": "test_checkout_session_created",
        "provider": str(contract.get("provider") or "stripe_test_mock"),
        "provider_mode": "test_mock",
        "plan_key": plan_key,
        "checkout_session": {
            "id": session_id,
            "url": checkout_url,
            "expires_at": None,
            "test_mode": True,
        },
        "next_test_events": ["activate", "invoice_paid", "payment_failed", "cancel"],
        "creates_real_checkout_session": False,
        "calls_stripe_api": False,
        "triggers_real_charge": False,
        "charge_now_allowed": False,
        "frontend_gets_api_key": False,
        "secret_exposed": False,
    }


def _create_test_customer_portal_session(
    repository: SaaSRepository,
    *,
    company_id: str,
    user_id: str,
    return_url: str | None,
    contract: dict[str, Any],
) -> dict[str, Any]:
    if not contract.get("customer_portal", {}).get("ready"):
        return _blocked_list(contract.get("blockers") or ["billing_test_customer_portal_not_ready"], http_status=503, contract=contract)
    subscription = repository.get_billing_subscription(company_id=company_id)
    customer_id = str(subscription.get("provider_customer_id") or "") if subscription else ""
    if not customer_id:
        return _blocked("billing_test_customer_id_missing_for_portal", http_status=409, contract=contract)
    resolved_return = _resolve_configured_return_url(
        requested=return_url,
        configured=_portal_return_url(),
        invalid_reason="billing_portal_return_url_not_allowed",
    )
    if not resolved_return.get("ok"):
        return _blocked(str(resolved_return.get("reason") or "billing_portal_return_url_not_allowed"), http_status=400, contract=contract)
    portal_id = _stable_mock_id("bps_mock", company_id, customer_id)
    portal_url = _append_query(
        str(resolved_return.get("url") or ""),
        {
            "billing_test_portal": portal_id,
            "billing_test_mode": "1",
        },
    )
    repository.write_audit(
        company_id=company_id,
        user_id=user_id,
        action_type="billing.test_customer_portal.created",
        target_type="billing_customer_portal",
        target_id=portal_id,
        summary="No-charge billing test Customer Portal session created for subscription rehearsal.",
        details={
            "provider": str(contract.get("provider") or "stripe_test_mock"),
            "customer_id_present": True,
            "portal_url_present": bool(portal_url),
            "creates_real_customer_portal_session": False,
            "calls_stripe_api": False,
            "triggers_real_charge": False,
            "charge_now_allowed": False,
            "frontend_gets_api_key": False,
            "secret_exposed": False,
        },
        actor_type="user",
    )
    return {
        "ok": True,
        "status": "test_customer_portal_session_created",
        "provider": str(contract.get("provider") or "stripe_test_mock"),
        "provider_mode": "test_mock",
        "customer_portal": {
            "id": portal_id,
            "url": portal_url,
            "test_mode": True,
        },
        "creates_real_customer_portal_session": False,
        "calls_stripe_api": False,
        "triggers_real_charge": False,
        "charge_now_allowed": False,
        "frontend_gets_api_key": False,
        "secret_exposed": False,
    }


def _stripe_api_post(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    api_key = _stripe_api_key()
    if not api_key:
        return _blocked("stripe_api_key_not_configured", http_status=503)
    base = os.environ.get("JIEJING_STRIPE_API_BASE", "https://api.stripe.com").rstrip("/")
    encoded = urlencode({key: value for key, value in payload.items() if value is not None}).encode("utf-8")
    request = Request(
        f"{base}{path}",
        data=encoded,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/x-www-form-urlencoded",
            "Stripe-Version": STRIPE_API_VERSION,
            "User-Agent": "Jiejing-SaaS-Billing/2026-06-17",
        },
    )
    try:
        with urlopen(request, timeout=_stripe_timeout_seconds()) as response:  # nosec B310 - controlled Stripe API base for tests/prod env.
            raw = response.read(256_000)
    except HTTPError as exc:
        return {
            "ok": False,
            "status": "stripe_api_error",
            "http_status": int(exc.code or 502),
            "blocked_by": ["stripe_api_error"],
            "message": "Stripe API returned an error. Check provider configuration and dashboard logs.",
            "frontend_gets_api_key": False,
            "secret_exposed": False,
        }
    except (TimeoutError, URLError) as exc:
        return {
            "ok": False,
            "status": "stripe_network_error",
            "http_status": 504,
            "blocked_by": ["stripe_network_error"],
            "error_type": type(exc).__name__,
            "frontend_gets_api_key": False,
            "secret_exposed": False,
        }
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except Exception:
        parsed = {}
    return {
        "ok": True,
        "status": "stripe_api_ok",
        "response": parsed if isinstance(parsed, dict) else {},
        "frontend_gets_api_key": False,
        "secret_exposed": False,
    }


def _stripe_api_key() -> str:
    return (os.environ.get("JIEJING_STRIPE_SECRET_KEY") or os.environ.get("STRIPE_SECRET_KEY") or "").strip()


def _success_url() -> str:
    return _safe_billing_return_url(_first_env("JIEJING_BILLING_SUCCESS_URL", "JIEJING_STRIPE_SUCCESS_URL"))


def _cancel_url() -> str:
    return _safe_billing_return_url(_first_env("JIEJING_BILLING_CANCEL_URL", "JIEJING_STRIPE_CANCEL_URL"))


def _portal_return_url() -> str:
    return _safe_billing_return_url(_first_env("JIEJING_BILLING_PORTAL_RETURN_URL", "JIEJING_STRIPE_PORTAL_RETURN_URL"))


def _safe_billing_return_url(value: str | None) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    parsed = urlparse(text)
    host = (parsed.hostname or "").lower()
    if parsed.scheme == "https" and host:
        return text
    if parsed.scheme == "http" and host in LOCAL_RETURN_HOSTS:
        return text
    return ""


def _resolve_configured_return_url(*, requested: str | None, configured: str, invalid_reason: str) -> dict[str, Any]:
    configured_safe = _safe_billing_return_url(configured)
    if not configured_safe:
        return {"ok": False, "reason": f"{invalid_reason}_configured_url_missing"}
    requested_text = str(requested or "").strip()
    if not requested_text:
        return {"ok": True, "url": configured_safe}
    requested_safe = _safe_billing_return_url(requested_text)
    if not requested_safe:
        return {"ok": False, "reason": invalid_reason}
    if _return_target(requested_safe) != _return_target(configured_safe):
        return {"ok": False, "reason": invalid_reason}
    return {"ok": True, "url": requested_safe}


def _return_target(value: str) -> tuple[str, str, str, str]:
    parsed = urlparse(value)
    return (
        parsed.scheme.lower(),
        (parsed.hostname or "").lower(),
        parsed.path or "/",
        parsed.query or "",
    )


def _first_env(*names: str) -> str:
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return ""


def _stripe_timeout_seconds() -> int:
    raw = os.environ.get("JIEJING_STRIPE_TIMEOUT_SECONDS", "").strip()
    try:
        return min(max(int(raw), 2), 30) if raw else 10
    except ValueError:
        return 10


def _stable_mock_id(prefix: str, *parts: str) -> str:
    seed = ":".join(str(part or "") for part in (*parts, str(int(time.time() // 60))))
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24]
    safe_prefix = "".join(char for char in prefix if char.isalnum() or char == "_") or "mock"
    return f"{safe_prefix}_{digest}"


def _append_query(url: str, params: dict[str, str]) -> str:
    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    for key, value in params.items():
        if value:
            query[key] = value
    return urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            urlencode(query),
            parsed.fragment,
        )
    )


def _blocked(reason: str, *, http_status: int, contract: dict[str, Any] | None = None) -> dict[str, Any]:
    return _blocked_list([reason], http_status=http_status, contract=contract)


def _blocked_list(reasons: list[str], *, http_status: int, contract: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "ok": False,
        "status": "blocked",
        "http_status": http_status,
        "blocked_by": reasons,
        "contract": contract or {},
        "frontend_gets_api_key": False,
        "secret_exposed": False,
    }
