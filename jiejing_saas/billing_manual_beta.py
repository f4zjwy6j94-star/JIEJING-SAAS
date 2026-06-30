"""Private-beta manual payment orders for Jiejing.

This module is intentionally not a payment provider integration. It creates a
merchant-visible payment note and lets an internal admin confirm external
receipt. No QR image, payment API credential, or raw payment proof is stored.
"""

from __future__ import annotations

import hashlib
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from jiejing_runtime.models import now_iso

from .repository import SaaSRepository


MANUAL_BETA_PROVIDER = "manual_beta"
MANUAL_BETA_PLAN_KEY = "starter"
MANUAL_BETA_AMOUNT_CNY = 99
MANUAL_BETA_DURATION_DAYS = 30
MANUAL_BETA_PROVIDER_PLAN_ID = "manual_beta_99_cny_30d"
ORDER_TARGET_TYPE = "manual_beta_payment_order"
ORDER_CREATED_ACTION = "billing.manual_beta_order.created"
ORDER_CONFIRMED_ACTION = "billing.manual_beta_payment.confirmed"


def create_manual_beta_payment_order(
    repository: SaaSRepository,
    *,
    company_id: str,
    user_id: str,
    plan_key: str = MANUAL_BETA_PLAN_KEY,
) -> dict[str, Any]:
    normalized_plan = _normalize_plan(plan_key)
    if normalized_plan != MANUAL_BETA_PLAN_KEY:
        return _blocked("manual_beta_only_supports_starter_plan", http_status=400)
    if not repository.get_company(company_id):
        return _blocked("company_not_found", http_status=404)

    created_at = now_iso()
    order_id = f"manual_beta_order_{secrets.token_hex(8)}"
    order = {
        "ok": True,
        "order_id": order_id,
        "status": "pending_manual_payment_confirmation",
        "provider": MANUAL_BETA_PROVIDER,
        "plan_key": MANUAL_BETA_PLAN_KEY,
        "amount_cny": MANUAL_BETA_AMOUNT_CNY,
        "currency": "CNY",
        "duration_days": MANUAL_BETA_DURATION_DAYS,
        "payment_note": _payment_note(),
        "created_at": created_at,
        "payment_instruction": "Use the private-beta Alipay personal collection code and include the payment note.",
        "manual_reconciliation_required": True,
        "private_beta_only": True,
        "can_be_paid_public_launch_provider": False,
        "qr_code_in_repository": False,
        "creates_real_checkout_session": False,
        "calls_external_payment_api": False,
        "triggers_real_charge": False,
        "charge_now_allowed": False,
        "frontend_gets_payment_secret": False,
        "secret_exposed": False,
    }
    repository.write_audit(
        company_id=company_id,
        user_id=user_id,
        actor_type="user",
        action_type=ORDER_CREATED_ACTION,
        target_type=ORDER_TARGET_TYPE,
        target_id=order_id,
        summary="Private-beta manual payment order created for Jiejing starter access.",
        details=order,
    )
    return order


def list_manual_beta_payment_orders(
    repository: SaaSRepository,
    *,
    company_id: str,
    limit: int = 20,
) -> list[dict[str, Any]]:
    logs = repository.list_audit_logs(company_id=company_id, limit=max(100, min(500, int(limit or 20) * 10)))
    orders: dict[str, dict[str, Any]] = {}
    for audit in reversed(logs):
        if audit.get("target_type") != ORDER_TARGET_TYPE:
            continue
        action = str(audit.get("action_type") or "")
        details = audit.get("details") if isinstance(audit.get("details"), dict) else {}
        order_id = str(audit.get("target_id") or details.get("order_id") or "")
        if not order_id:
            continue
        current = orders.setdefault(order_id, {})
        if action == ORDER_CREATED_ACTION:
            current.update(_public_order(details))
            current.setdefault("created_at", audit.get("created_at") or "")
        elif action == ORDER_CONFIRMED_ACTION:
            current.update(
                {
                    "order_id": order_id,
                    "status": "confirmed_manual_receipt",
                    "confirmed_at": details.get("confirmed_at") or audit.get("created_at") or "",
                    "confirmed_by_user_id_present": bool(details.get("confirmed_by_user_id")),
                    "received_amount_cny": details.get("received_amount_cny"),
                    "active_until": details.get("active_until") or "",
                    "subscription_provider": MANUAL_BETA_PROVIDER,
                    "manual_reconciliation_required": True,
                    "private_beta_only": True,
                    "triggers_real_charge": False,
                    "frontend_gets_payment_secret": False,
                    "secret_exposed": False,
                }
            )
    ordered = sorted(
        (_public_order(order) for order in orders.values()),
        key=lambda item: str(item.get("confirmed_at") or item.get("created_at") or ""),
        reverse=True,
    )
    return ordered[: max(1, min(100, int(limit or 20)))]


def confirm_manual_beta_payment_order(
    repository: SaaSRepository,
    *,
    company_id: str,
    user_id: str,
    order_id: str,
    internal_admin: bool,
    received_amount_cny: int = MANUAL_BETA_AMOUNT_CNY,
    payment_reference: str = "",
) -> dict[str, Any]:
    if not internal_admin:
        return _blocked("manual_beta_confirmation_requires_internal_admin", http_status=403)
    clean_order_id = _safe_order_id(order_id)
    if not clean_order_id:
        return _blocked("manual_beta_order_id_required", http_status=400)
    received_amount = _safe_amount(received_amount_cny)
    if received_amount != MANUAL_BETA_AMOUNT_CNY:
        return _blocked("manual_beta_received_amount_mismatch", http_status=400)

    order = next((item for item in list_manual_beta_payment_orders(repository, company_id=company_id, limit=100) if item.get("order_id") == clean_order_id), None)
    if not order:
        return _blocked("manual_beta_order_not_found", http_status=404)
    if order.get("status") == "confirmed_manual_receipt":
        return {
            "ok": True,
            "status": "manual_beta_payment_already_confirmed",
            "order": order,
            "manual_reconciliation_required": True,
            "private_beta_only": True,
            "triggers_real_charge": False,
            "frontend_gets_payment_secret": False,
            "secret_exposed": False,
        }

    confirmed_at = now_iso()
    active_until = _plus_days(confirmed_at, MANUAL_BETA_DURATION_DAYS)
    provider_customer_id = _stable_provider_id("manual_beta_cus", company_id)
    provider_subscription_id = _stable_provider_id("manual_beta_sub", clean_order_id)
    event = {
        "provider": MANUAL_BETA_PROVIDER,
        "event_id": f"{MANUAL_BETA_PROVIDER}:{clean_order_id}:confirmed",
        "event_type": "manual_beta.payment_confirmed",
        "company_id": company_id,
        "provider_customer_id": provider_customer_id,
        "provider_subscription_id": provider_subscription_id,
        "provider_plan_id": MANUAL_BETA_PROVIDER_PLAN_ID,
        "plan_key": MANUAL_BETA_PLAN_KEY,
        "subscription_status": "active",
        "quota_recalculation_required": True,
        "payment_attention_required": False,
        "manual_payment_order_id": clean_order_id,
        "amount_cny": MANUAL_BETA_AMOUNT_CNY,
        "duration_days": MANUAL_BETA_DURATION_DAYS,
        "active_until": active_until,
        "manual_reconciliation_required": True,
        "private_beta_only": True,
        "raw_payload_persisted": False,
        "frontend_gets_payment_secret": False,
        "secret_exposed": False,
    }
    persistence = repository.apply_billing_webhook_event(event=event)
    confirmation = {
        "ok": True,
        "status": "manual_beta_payment_confirmed",
        "order_id": clean_order_id,
        "provider": MANUAL_BETA_PROVIDER,
        "plan_key": MANUAL_BETA_PLAN_KEY,
        "received_amount_cny": received_amount,
        "currency": "CNY",
        "duration_days": MANUAL_BETA_DURATION_DAYS,
        "confirmed_at": confirmed_at,
        "active_until": active_until,
        "confirmed_by_user_id": user_id,
        "payment_reference_present": bool(_safe_text(payment_reference)),
        "persistence": persistence,
        "manual_reconciliation_required": True,
        "private_beta_only": True,
        "creates_real_checkout_session": False,
        "calls_external_payment_api": False,
        "triggers_real_charge": False,
        "charge_now_allowed": False,
        "frontend_gets_payment_secret": False,
        "secret_exposed": False,
    }
    repository.write_audit(
        company_id=company_id,
        user_id=user_id,
        actor_type="internal_admin",
        action_type=ORDER_CONFIRMED_ACTION,
        target_type=ORDER_TARGET_TYPE,
        target_id=clean_order_id,
        summary="Internal admin confirmed external receipt for a private-beta manual payment order.",
        details={
            **confirmation,
            "payment_reference": _safe_text(payment_reference),
        },
    )
    return confirmation


def _public_order(value: dict[str, Any]) -> dict[str, Any]:
    allowed_keys = {
        "ok",
        "order_id",
        "status",
        "provider",
        "plan_key",
        "amount_cny",
        "currency",
        "duration_days",
        "payment_note",
        "created_at",
        "confirmed_at",
        "active_until",
        "payment_instruction",
        "manual_reconciliation_required",
        "private_beta_only",
        "can_be_paid_public_launch_provider",
        "qr_code_in_repository",
        "received_amount_cny",
        "subscription_provider",
        "confirmed_by_user_id_present",
        "creates_real_checkout_session",
        "calls_external_payment_api",
        "triggers_real_charge",
        "charge_now_allowed",
        "frontend_gets_payment_secret",
        "secret_exposed",
    }
    order = {key: value.get(key) for key in allowed_keys if key in value}
    order.setdefault("ok", True)
    order.setdefault("provider", MANUAL_BETA_PROVIDER)
    order.setdefault("plan_key", MANUAL_BETA_PLAN_KEY)
    order.setdefault("amount_cny", MANUAL_BETA_AMOUNT_CNY)
    order.setdefault("currency", "CNY")
    order.setdefault("duration_days", MANUAL_BETA_DURATION_DAYS)
    order.setdefault("manual_reconciliation_required", True)
    order.setdefault("private_beta_only", True)
    order.setdefault("qr_code_in_repository", False)
    order.setdefault("creates_real_checkout_session", False)
    order.setdefault("calls_external_payment_api", False)
    order.setdefault("triggers_real_charge", False)
    order.setdefault("charge_now_allowed", False)
    order.setdefault("frontend_gets_payment_secret", False)
    order.setdefault("secret_exposed", False)
    return order


def _normalize_plan(value: str) -> str:
    return str(value or "").strip().lower().replace("-", "_") or MANUAL_BETA_PLAN_KEY


def _payment_note() -> str:
    return f"JJ-BETA-{secrets.token_hex(3).upper()}"


def _safe_order_id(value: str) -> str:
    text = str(value or "").strip()
    if not re.fullmatch(r"manual_beta_order_[a-f0-9]{16}", text):
        return ""
    return text


def _safe_amount(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _safe_text(value: str, *, limit: int = 120) -> str:
    return re.sub(r"[^a-zA-Z0-9 ._:@#-]+", " ", str(value or "")).strip()[:limit]


def _plus_days(iso_value: str, days: int) -> str:
    try:
        base = datetime.fromisoformat(iso_value.replace("Z", "+00:00"))
    except ValueError:
        base = datetime.now(timezone.utc)
    return (base + timedelta(days=days)).astimezone(timezone.utc).isoformat()


def _stable_provider_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256(":".join(parts).encode("utf-8")).hexdigest()[:24]
    return f"{prefix}_{digest}"


def _blocked(reason: str, *, http_status: int) -> dict[str, Any]:
    return {
        "ok": False,
        "status": "blocked",
        "http_status": http_status,
        "blocked_by": [reason],
        "manual_reconciliation_required": True,
        "private_beta_only": True,
        "creates_real_checkout_session": False,
        "calls_external_payment_api": False,
        "triggers_real_charge": False,
        "charge_now_allowed": False,
        "frontend_gets_payment_secret": False,
        "secret_exposed": False,
    }
