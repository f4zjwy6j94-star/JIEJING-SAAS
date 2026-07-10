"""No-charge billing provider used to rehearse subscription lifecycle.

The test provider intentionally does not call Stripe, create real Checkout
Sessions, collect card data, or accept public payment webhooks.
"""

from __future__ import annotations

import hashlib
import time
from typing import Any

from .billing_webhook import TEST_BILLING_PROVIDERS, billing_plan_ids, selected_billing_provider
from .repository import SaaSRepository


PLAN_KEYS = {"starter", "operator", "team"}
TEST_EVENT_ACTIONS = {
    "activate": {
        "event_type": "test.customer.subscription.updated",
        "subscription_status": "active",
        "payment_attention_required": False,
    },
    "invoice_paid": {
        "event_type": "test.invoice.paid",
        "subscription_status": "active",
        "payment_attention_required": False,
    },
    "payment_failed": {
        "event_type": "test.invoice.payment_failed",
        "subscription_status": "past_due",
        "payment_attention_required": True,
    },
    "cancel": {
        "event_type": "test.customer.subscription.deleted",
        "subscription_status": "canceled",
        "payment_attention_required": True,
    },
}


def apply_test_billing_event(
    repository: SaaSRepository,
    *,
    company_id: str,
    user_id: str,
    plan_key: str,
    action: str,
    event_nonce: str = "",
) -> dict[str, Any]:
    provider = selected_billing_provider()
    if provider not in TEST_BILLING_PROVIDERS:
        return _blocked("billing_test_provider_not_selected", http_status=409)
    normalized_plan = str(plan_key or "").strip().lower() or "starter"
    if normalized_plan not in PLAN_KEYS:
        return _blocked("billing_plan_key_not_supported", http_status=400)
    normalized_action = str(action or "").strip().lower() or "activate"
    if normalized_action not in TEST_EVENT_ACTIONS:
        return _blocked("billing_test_event_action_not_supported", http_status=400)
    company = repository.get_company(company_id)
    if not company:
        return _blocked("company_not_found", http_status=404)

    event_shape = TEST_EVENT_ACTIONS[normalized_action]
    provider_plan_id = billing_plan_ids().get(normalized_plan) or f"mock_price_{normalized_plan}"
    provider_customer_id = _stable_provider_id("cus_mock", company_id)
    provider_subscription_id = _stable_provider_id("sub_mock", company_id)
    event_id = _stable_provider_id("evt_mock", company_id, normalized_action, event_nonce or str(int(time.time() // 60)))
    event = {
        "provider": provider,
        "event_id": event_id,
        "event_type": event_shape["event_type"],
        "company_id": company_id,
        "provider_customer_id": provider_customer_id,
        "provider_subscription_id": provider_subscription_id,
        "provider_plan_id": provider_plan_id,
        "plan_key": normalized_plan,
        "subscription_status": event_shape["subscription_status"],
        "quota_recalculation_required": True,
        "payment_attention_required": bool(event_shape["payment_attention_required"]),
        "raw_payload_persisted": False,
        "frontend_gets_payment_secret": False,
        "secret_exposed": False,
    }
    persistence = repository.apply_billing_webhook_event(event=event)
    repository.write_audit(
        company_id=company_id,
        user_id=user_id,
        actor_type="user",
        action_type="billing.test_event.applied",
        target_type="billing_subscription",
        target_id=provider_subscription_id,
        summary="No-charge billing test event applied through the subscription entitlement pipeline.",
        details={
            "provider": provider,
            "event_type": event["event_type"],
            "action": normalized_action,
            "plan_key": normalized_plan,
            "subscription_status": event["subscription_status"],
            "creates_real_checkout_session": False,
            "calls_stripe_api": False,
            "triggers_real_charge": False,
            "raw_payload_persisted": False,
            "frontend_gets_payment_secret": False,
            "secret_exposed": False,
        },
    )
    return {
        "ok": True,
        "status": "billing_test_event_applied",
        "provider": provider,
        "provider_mode": "test_mock",
        "action": normalized_action,
        "event": {
            "event_id_present": True,
            "event_type": event["event_type"],
            "plan_key": normalized_plan,
            "subscription_status": event["subscription_status"],
            "provider_customer_id_present": True,
            "provider_subscription_id_present": True,
            "provider_plan_id_present": True,
        },
        "persistence": persistence,
        "creates_real_checkout_session": False,
        "calls_stripe_api": False,
        "triggers_real_charge": False,
        "charge_now_allowed": False,
        "frontend_gets_payment_secret": False,
        "secret_exposed": False,
    }


def _stable_provider_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256(":".join(parts).encode("utf-8")).hexdigest()[:24]
    return f"{prefix}_{digest}"


def _blocked(reason: str, *, http_status: int) -> dict[str, Any]:
    return {
        "ok": False,
        "status": "blocked",
        "http_status": http_status,
        "blocked_by": [reason],
        "creates_real_checkout_session": False,
        "calls_stripe_api": False,
        "triggers_real_charge": False,
        "charge_now_allowed": False,
        "frontend_gets_payment_secret": False,
        "secret_exposed": False,
    }
