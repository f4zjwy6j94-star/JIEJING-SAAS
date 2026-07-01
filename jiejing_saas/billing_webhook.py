"""Signed billing webhook boundary for Jiejing paid SaaS launch.

The module validates provider signatures and returns a sanitized event shape.
It never logs raw webhook bodies, API keys, endpoint secrets, customer emails,
or payment details.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from typing import Any, Mapping


SUPPORTED_BILLING_PROVIDERS = {"stripe", "paddle", "lemon_squeezy"}
TEST_BILLING_PROVIDERS = {"stripe_test_mock"}
PRIVATE_BETA_BILLING_PROVIDERS = {"manual_beta"}


def build_billing_provider_contract() -> dict[str, Any]:
    provider = _provider()
    external_provider = provider in SUPPORTED_BILLING_PROVIDERS
    test_provider = provider in TEST_BILLING_PROVIDERS
    private_beta_provider = provider in PRIVATE_BETA_BILLING_PROVIDERS
    plan_ids = billing_plan_ids()
    webhook_secret_configured = bool(_webhook_secret(provider)) if external_provider else False
    api_key_configured = bool(_api_key(provider)) if external_provider else False
    webhook_endpoint_configured = bool(os.environ.get("JIEJING_BILLING_WEBHOOK_URL", "").strip())
    webhook_configured = webhook_secret_configured and webhook_endpoint_configured if external_provider else test_provider or private_beta_provider
    missing_plan_ids = [key for key, value in plan_ids.items() if not value]
    blockers: list[str] = []
    if not external_provider and not test_provider and not private_beta_provider:
        blockers.append("external_paid_subscription_provider_not_configured")
    if external_provider and not api_key_configured:
        blockers.append(f"{provider}_api_key_not_configured")
    if external_provider and not webhook_secret_configured:
        blockers.append(f"{provider}_webhook_secret_not_configured")
    if external_provider and not webhook_endpoint_configured:
        blockers.append("billing_webhook_url_not_configured")
    if missing_plan_ids:
        blockers.append("billing_plan_ids_missing")
    return {
        "contract_version": "2026-05-26-signed-billing-provider",
        "provider": provider or "not_selected",
        "provider_mode": "external_paid" if external_provider else "test_mock" if test_provider else "private_beta_manual" if private_beta_provider else "not_selected",
        "supported_external_providers": sorted(SUPPORTED_BILLING_PROVIDERS),
        "supported_test_providers": sorted(TEST_BILLING_PROVIDERS),
        "supported_private_beta_providers": sorted(PRIVATE_BETA_BILLING_PROVIDERS),
        "external_provider_configured": external_provider,
        "test_provider_configured": test_provider,
        "private_beta_provider_configured": private_beta_provider,
        "test_provider_ready": test_provider and not missing_plan_ids,
        "api_key_configured": api_key_configured,
        "api_key_required": external_provider,
        "webhook_secret_configured": webhook_secret_configured,
        "webhook_secret_required": external_provider,
        "webhook_endpoint_configured": webhook_endpoint_configured,
        "webhook_configured": webhook_configured,
        "plan_ids": {key: bool(value) for key, value in plan_ids.items()},
        "missing_plan_ids": missing_plan_ids,
        "paid_provider_ready": external_provider and api_key_configured and webhook_configured and not missing_plan_ids,
        "calls_external_payment_api": external_provider,
        "can_run_without_payment_provider_account": test_provider or private_beta_provider,
        "triggers_real_charge": False,
        "charge_now_allowed": False,
        "webhook_event_types": webhook_event_types(provider),
        "frontend_gets_payment_secret": False,
        "raw_payment_secret_exposed": False,
        "blockers": blockers,
        "secret_exposed": False,
    }


def billing_plan_ids() -> dict[str, str]:
    provider = _provider()
    if provider in PRIVATE_BETA_BILLING_PROVIDERS:
        return {
            "starter": "manual_beta_99_cny_30d",
            "operator": "manual_beta_operator_not_available",
            "team": "manual_beta_team_not_available",
        }
    if provider in TEST_BILLING_PROVIDERS:
        return {
            "starter": _first_env("JIEJING_STRIPE_TEST_MOCK_PRICE_STARTER_ID", "JIEJING_BILLING_PLAN_STARTER_ID") or "mock_price_starter",
            "operator": _first_env("JIEJING_STRIPE_TEST_MOCK_PRICE_OPERATOR_ID", "JIEJING_BILLING_PLAN_OPERATOR_ID") or "mock_price_operator",
            "team": _first_env("JIEJING_STRIPE_TEST_MOCK_PRICE_TEAM_ID", "JIEJING_BILLING_PLAN_TEAM_ID") or "mock_price_team",
        }
    if provider == "lemon_squeezy":
        return {
            "starter": _first_env(
                "JIEJING_LEMON_SQUEEZY_VARIANT_STARTER_ID",
                "LEMON_SQUEEZY_VARIANT_STARTER_ID",
                "JIEJING_BILLING_PLAN_STARTER_ID",
            ),
            "operator": _first_env(
                "JIEJING_LEMON_SQUEEZY_VARIANT_OPERATOR_ID",
                "LEMON_SQUEEZY_VARIANT_OPERATOR_ID",
                "JIEJING_BILLING_PLAN_OPERATOR_ID",
            ),
            "team": _first_env(
                "JIEJING_LEMON_SQUEEZY_VARIANT_TEAM_ID",
                "LEMON_SQUEEZY_VARIANT_TEAM_ID",
                "JIEJING_BILLING_PLAN_TEAM_ID",
            ),
        }
    provider_prefix = f"JIEJING_{provider.upper()}_PRICE_" if provider else ""
    return {
        "starter": _first_env(provider_prefix + "STARTER_ID" if provider_prefix else "", "JIEJING_BILLING_PLAN_STARTER_ID"),
        "operator": _first_env(provider_prefix + "OPERATOR_ID" if provider_prefix else "", "JIEJING_BILLING_PLAN_OPERATOR_ID"),
        "team": _first_env(provider_prefix + "TEAM_ID" if provider_prefix else "", "JIEJING_BILLING_PLAN_TEAM_ID"),
    }


def webhook_event_types(provider: str | None = None) -> list[str]:
    selected = (provider or _provider()).strip().lower()
    if selected == "stripe":
        return [
            "checkout.session.completed",
            "customer.subscription.created",
            "customer.subscription.updated",
            "customer.subscription.deleted",
            "invoice.paid",
            "invoice.payment_succeeded",
            "invoice.payment_failed",
            "charge.refunded",
            "charge.dispute.created",
            "charge.dispute.closed",
        ]
    if selected == "paddle":
        return [
            "subscription.created",
            "subscription.updated",
            "subscription.canceled",
            "transaction.completed",
            "transaction.payment_failed",
        ]
    if selected == "lemon_squeezy":
        return [
            "order_created",
            "subscription_created",
            "subscription_updated",
            "subscription_cancelled",
            "subscription_resumed",
            "subscription_expired",
            "subscription_payment_success",
            "subscription_payment_failed",
        ]
    if selected in TEST_BILLING_PROVIDERS:
        return [
            "test.checkout.session.completed",
            "test.customer.subscription.updated",
            "test.invoice.paid",
            "test.invoice.payment_failed",
            "test.customer.subscription.deleted",
        ]
    if selected in PRIVATE_BETA_BILLING_PROVIDERS:
        return ["manual_beta.payment_confirmed"]
    return []


def handle_billing_webhook(*, raw_body: bytes, headers: Mapping[str, str]) -> dict[str, Any]:
    provider = _provider()
    if provider in TEST_BILLING_PROVIDERS:
        return _blocked("billing_test_provider_public_webhook_disabled", http_status=400)
    if provider in PRIVATE_BETA_BILLING_PROVIDERS:
        return _blocked("manual_beta_public_webhook_disabled", http_status=400)
    if provider not in SUPPORTED_BILLING_PROVIDERS:
        return _blocked("billing_provider_not_selected", http_status=400)
    secret = _webhook_secret(provider)
    if not secret:
        return _blocked(f"{provider}_webhook_secret_not_configured", http_status=503)
    if provider == "stripe":
        verified = _verify_stripe_signature(raw_body=raw_body, signature=_header(headers, "stripe-signature"), secret=secret)
    elif provider == "paddle":
        verified = _verify_paddle_signature(raw_body=raw_body, signature=_header(headers, "paddle-signature"), secret=secret)
    else:
        verified = _verify_lemon_squeezy_signature(raw_body=raw_body, signature=_header(headers, "x-signature"), secret=secret)
    if not verified.get("ok"):
        return {
            "ok": False,
            "status": "invalid_signature",
            "provider": provider,
            "blocked_by": verified.get("blocked_by") or ["invalid_signature"],
            "http_status": int(verified.get("http_status") or 400),
            "frontend_gets_payment_secret": False,
            "secret_exposed": False,
        }
    event = _parse_event(raw_body)
    normalized = normalize_billing_event(provider=provider, event=event)
    return {
        "ok": True,
        "status": "accepted",
        "provider": provider,
        "event": normalized,
        "signature_verified": True,
        "payload_persisted": False,
        "frontend_gets_payment_secret": False,
        "secret_exposed": False,
    }


def normalize_billing_event(*, provider: str, event: dict[str, Any]) -> dict[str, Any]:
    meta = event.get("meta") if isinstance(event.get("meta"), dict) else {}
    event_type = str(meta.get("event_name") or event.get("type") or event.get("event_type") or event.get("event_name") or "").strip()
    event_id = str(event.get("id") or event.get("event_id") or "").strip()
    data = event.get("data") if isinstance(event.get("data"), dict) else {}
    obj = data.get("object") if isinstance(data.get("object"), dict) else data
    if provider == "lemon_squeezy" and isinstance(data.get("attributes"), dict):
        obj = {**data.get("attributes", {}), "id": data.get("id") or event.get("id")}
    subscription_id = _extract_subscription_id(provider=provider, event_type=event_type, obj=obj)
    customer_id = str(obj.get("customer") or obj.get("customer_id") or "").strip()
    status = str(obj.get("status") or "").strip()
    plan_id = _extract_plan_id(provider=provider, obj=obj)
    company_id = _extract_company_id(provider=provider, event=event, obj=obj)
    plan_key = _plan_key_for_provider_plan_id(plan_id)
    return {
        "provider": provider,
        "event_id": event_id,
        "event_id_present": bool(event_id),
        "event_type": event_type,
        "supported_event": event_type in webhook_event_types(provider),
        "company_id": company_id,
        "company_id_present": bool(company_id),
        "provider_subscription_id": subscription_id,
        "subscription_id_present": bool(subscription_id),
        "provider_customer_id": customer_id,
        "customer_id_present": bool(customer_id),
        "provider_plan_id": plan_id,
        "provider_plan_id_present": bool(plan_id),
        "plan_key": plan_key,
        "plan_key_resolved": bool(plan_key),
        "subscription_status": status,
        "quota_recalculation_required": event_type in _quota_recalculation_events(provider),
        "payment_attention_required": event_type in _payment_attention_events(provider),
        "raw_customer_email_returned": False,
        "payment_details_returned": False,
        "raw_payload_persisted": False,
        "secret_exposed": False,
    }


def _verify_stripe_signature(*, raw_body: bytes, signature: str, secret: str) -> dict[str, Any]:
    parts = _parse_signature_parts(signature, separator=",")
    timestamp = (parts.get("t") or [""])[0]
    signatures = parts.get("v1") or []
    if not timestamp or not signatures:
        return {"ok": False, "blocked_by": ["stripe_signature_header_invalid"], "http_status": 400}
    if _timestamp_expired(timestamp, tolerance_seconds=300):
        return {"ok": False, "blocked_by": ["stripe_signature_timestamp_expired"], "http_status": 400}
    signed_payload = timestamp.encode("utf-8") + b"." + raw_body
    expected = hmac.new(secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
    if not any(hmac.compare_digest(expected, item) for item in signatures):
        return {"ok": False, "blocked_by": ["stripe_signature_mismatch"], "http_status": 400}
    return {"ok": True, "secret_exposed": False}


def _verify_paddle_signature(*, raw_body: bytes, signature: str, secret: str) -> dict[str, Any]:
    parts = _parse_signature_parts(signature, separator=";")
    timestamp = (parts.get("ts") or [""])[0]
    signatures = parts.get("h1") or []
    if not timestamp or not signatures:
        return {"ok": False, "blocked_by": ["paddle_signature_header_invalid"], "http_status": 400}
    if _timestamp_expired(timestamp, tolerance_seconds=300):
        return {"ok": False, "blocked_by": ["paddle_signature_timestamp_expired"], "http_status": 400}
    signed_payload = timestamp.encode("utf-8") + b":" + raw_body
    expected = hmac.new(secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
    if not any(hmac.compare_digest(expected, item) for item in signatures):
        return {"ok": False, "blocked_by": ["paddle_signature_mismatch"], "http_status": 400}
    return {"ok": True, "secret_exposed": False}


def _verify_lemon_squeezy_signature(*, raw_body: bytes, signature: str, secret: str) -> dict[str, Any]:
    if not signature:
        return {"ok": False, "blocked_by": ["lemon_squeezy_signature_header_missing"], "http_status": 400}
    expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        return {"ok": False, "blocked_by": ["lemon_squeezy_signature_mismatch"], "http_status": 400}
    return {"ok": True, "secret_exposed": False}


def _parse_signature_parts(value: str, *, separator: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for part in str(value or "").split(separator):
        if "=" not in part:
            continue
        key, raw = part.strip().split("=", 1)
        key = key.strip()
        raw = raw.strip()
        if key and raw:
            out.setdefault(key, []).append(raw)
    return out


def _timestamp_expired(value: str, *, tolerance_seconds: int) -> bool:
    try:
        timestamp = int(value)
    except ValueError:
        return True
    return abs(int(time.time()) - timestamp) > tolerance_seconds


def _parse_event(raw_body: bytes) -> dict[str, Any]:
    try:
        parsed = json.loads(raw_body.decode("utf-8"))
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _extract_plan_id(*, provider: str, obj: dict[str, Any]) -> str:
    if provider == "stripe":
        items = ((obj.get("items") or {}).get("data") if isinstance(obj.get("items"), dict) else []) or []
        first = items[0] if items and isinstance(items[0], dict) else {}
        price = first.get("price") if isinstance(first.get("price"), dict) else {}
        return str(price.get("id") or obj.get("price") or "").strip()
    if provider == "paddle":
        items = obj.get("items") if isinstance(obj.get("items"), list) else []
        first = items[0] if items and isinstance(items[0], dict) else {}
        price = first.get("price") if isinstance(first.get("price"), dict) else {}
        return str(price.get("id") or first.get("price_id") or "").strip()
    if provider == "lemon_squeezy":
        first_order_item = obj.get("first_order_item") if isinstance(obj.get("first_order_item"), dict) else {}
        return str(obj.get("variant_id") or first_order_item.get("variant_id") or obj.get("product_id") or "").strip()
    if provider in TEST_BILLING_PROVIDERS:
        return str(obj.get("price") or obj.get("price_id") or "").strip()
    return ""


def _extract_subscription_id(*, provider: str, event_type: str, obj: dict[str, Any]) -> str:
    event = str(event_type or "").strip().lower()
    if provider == "stripe" and (event.startswith("charge.") or "dispute" in event):
        return str(obj.get("subscription") or obj.get("subscription_id") or "").strip()
    return str(obj.get("subscription") or obj.get("subscription_id") or obj.get("id") or "").strip()


def _extract_company_id(*, provider: str, event: dict[str, Any], obj: dict[str, Any]) -> str:
    metadata = obj.get("metadata") if isinstance(obj.get("metadata"), dict) else {}
    custom_data = obj.get("custom_data") if isinstance(obj.get("custom_data"), dict) else {}
    meta = event.get("meta") if isinstance(event.get("meta"), dict) else {}
    meta_custom = meta.get("custom_data") if isinstance(meta.get("custom_data"), dict) else {}
    candidates = [
        metadata.get("company_id"),
        metadata.get("jiejing_company_id"),
        custom_data.get("company_id"),
        custom_data.get("jiejing_company_id"),
        meta_custom.get("company_id"),
        meta_custom.get("jiejing_company_id"),
    ]
    if provider == "stripe":
        candidates.append(obj.get("client_reference_id"))
    for value in candidates:
        text = str(value or "").strip()
        if text and len(text) <= 120:
            return text
    return ""


def _plan_key_for_provider_plan_id(provider_plan_id: str) -> str:
    if not provider_plan_id:
        return ""
    plan_ids = billing_plan_ids()
    for key, value in plan_ids.items():
        if value and str(value) == str(provider_plan_id):
            return key
    return ""


def _quota_recalculation_events(provider: str) -> set[str]:
    if provider in TEST_BILLING_PROVIDERS:
        return {
            "test.checkout.session.completed",
            "test.customer.subscription.updated",
            "test.invoice.paid",
            "test.invoice.payment_failed",
            "test.customer.subscription.deleted",
        }
    if provider == "stripe":
        return {
            "checkout.session.completed",
            "customer.subscription.created",
            "customer.subscription.updated",
            "customer.subscription.deleted",
            "invoice.paid",
            "invoice.payment_failed",
            "charge.refunded",
            "charge.dispute.created",
            "charge.dispute.closed",
        }
    if provider == "paddle":
        return {"subscription.created", "subscription.updated", "subscription.canceled", "transaction.completed"}
    if provider == "lemon_squeezy":
        return {
            "order_created",
            "subscription_created",
            "subscription_updated",
            "subscription_cancelled",
            "subscription_resumed",
            "subscription_expired",
            "subscription_payment_success",
            "subscription_payment_failed",
        }
    return set()


def _payment_attention_events(provider: str) -> set[str]:
    if provider in TEST_BILLING_PROVIDERS:
        return {"test.invoice.payment_failed", "test.customer.subscription.deleted"}
    if provider == "stripe":
        return {"invoice.payment_failed", "customer.subscription.deleted", "charge.refunded", "charge.dispute.created", "charge.dispute.closed"}
    if provider == "paddle":
        return {"transaction.payment_failed", "subscription.canceled"}
    if provider == "lemon_squeezy":
        return {"subscription_cancelled", "subscription_expired", "subscription_payment_failed"}
    return set()


def _provider() -> str:
    raw = os.environ.get("JIEJING_BILLING_PROVIDER", "").strip().lower().replace("-", "_")
    aliases = {
        "lemonsqueezy": "lemon_squeezy",
        "lemon_squeezy": "lemon_squeezy",
        "stripe_mock": "stripe_test_mock",
        "stripe_test": "stripe_test_mock",
        "test_stripe": "stripe_test_mock",
        "mock_stripe": "stripe_test_mock",
        "mock_billing": "stripe_test_mock",
        "manual": "manual_beta",
        "manual_qr": "manual_beta",
        "manual_beta": "manual_beta",
    }
    return aliases.get(raw, raw)


def selected_billing_provider() -> str:
    return _provider()


def _webhook_secret(provider: str) -> str:
    if provider == "stripe":
        return _first_env("JIEJING_STRIPE_WEBHOOK_SECRET", "STRIPE_WEBHOOK_SECRET")
    if provider == "paddle":
        return _first_env("JIEJING_PADDLE_WEBHOOK_SECRET", "PADDLE_WEBHOOK_SECRET", "PADDLE_WEBHOOK_SECRET_KEY")
    if provider == "lemon_squeezy":
        return _first_env("JIEJING_LEMON_SQUEEZY_WEBHOOK_SECRET", "LEMON_SQUEEZY_WEBHOOK_SECRET")
    return ""


def _api_key(provider: str) -> str:
    if provider == "stripe":
        return _first_env("JIEJING_STRIPE_SECRET_KEY", "STRIPE_SECRET_KEY")
    if provider == "paddle":
        return _first_env("JIEJING_PADDLE_API_KEY", "PADDLE_API_KEY")
    if provider == "lemon_squeezy":
        return _first_env("JIEJING_LEMON_SQUEEZY_API_KEY", "LEMON_SQUEEZY_API_KEY")
    return ""


def _first_env(*names: str) -> str:
    for name in names:
        if name and os.environ.get(name, "").strip():
            return os.environ.get(name, "").strip()
    return ""


def _header(headers: Mapping[str, str], name: str) -> str:
    lower = name.lower()
    for key, value in headers.items():
        if key.lower() == lower:
            return str(value or "")
    return ""


def _blocked(reason: str, *, http_status: int) -> dict[str, Any]:
    return {
        "ok": False,
        "status": "blocked",
        "blocked_by": [reason],
        "http_status": http_status,
        "frontend_gets_payment_secret": False,
        "secret_exposed": False,
    }
