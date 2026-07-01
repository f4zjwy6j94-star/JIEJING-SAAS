"""No-charge provider payment rehearsal for subscription entitlement.

This module proves the future paid-provider path without creating a real
Checkout Session, calling Stripe, collecting card data, or accepting public
test webhooks. Entitlement is granted only after backend-owned proof is present
and a sanitized subscription event is applied.
"""

from __future__ import annotations

import hashlib
import time
from typing import Any

from .billing_checkout import create_stripe_checkout_session
from .billing_plan import build_billing_usage, evaluate_quota_action
from .billing_test_provider import TEST_EVENT_ACTIONS, apply_test_billing_event
from .billing_webhook import TEST_BILLING_PROVIDERS, selected_billing_provider
from .config import SaaSSettings
from .repository import SaaSRepository


PLAN_KEYS = {"starter", "operator", "team"}
METERED_ACTION_UNIT = "ai_ceo_task"


def run_billing_provider_rehearsal(
    settings: SaaSSettings,
    repository: SaaSRepository,
    *,
    company_id: str,
    user_id: str,
    plan_key: str,
    action: str,
) -> dict[str, Any]:
    """Run the checkout/proof/event/quota rehearsal through backend code only."""

    provider = selected_billing_provider()
    if provider not in TEST_BILLING_PROVIDERS:
        return _blocked("billing_rehearsal_requires_test_provider", http_status=409, provider=provider)
    normalized_plan = str(plan_key or "").strip().lower() or "starter"
    if normalized_plan not in PLAN_KEYS:
        return _blocked("billing_plan_key_not_supported", http_status=400, provider=provider)
    normalized_action = str(action or "").strip().lower() or "activate"
    if normalized_action not in TEST_EVENT_ACTIONS:
        return _blocked("billing_rehearsal_action_not_supported", http_status=400, provider=provider)

    checkout = create_stripe_checkout_session(
        repository,
        company_id=company_id,
        user_id=user_id,
        plan_key=normalized_plan,
    )
    if not checkout.get("ok"):
        return {
            **_blocked("billing_test_checkout_not_ready", http_status=int(checkout.get("http_status") or 503), provider=provider),
            "checkout": _public_checkout_presence(checkout),
            "blocked_by": list(checkout.get("blocked_by") or ["billing_test_checkout_not_ready"]),
        }

    checkout_session = checkout.get("checkout_session") if isinstance(checkout.get("checkout_session"), dict) else {}
    provider_proof = _mock_order_query_proof(
        provider=provider,
        company_id=company_id,
        plan_key=normalized_plan,
        action=normalized_action,
        checkout_session_id=str(checkout_session.get("id") or ""),
    )
    billing_event = apply_test_billing_event(
        repository,
        company_id=company_id,
        user_id=user_id,
        plan_key=normalized_plan,
        action=normalized_action,
    )
    if not billing_event.get("ok"):
        return {
            **_blocked("billing_test_event_not_applied", http_status=int(billing_event.get("http_status") or 503), provider=provider),
            "checkout": _public_checkout_presence(checkout),
            "provider_proof": provider_proof,
            "billing_test_event": billing_event,
        }

    usage = build_billing_usage(settings, repository, company_id=company_id)
    quota = evaluate_quota_action(settings, repository, company_id=company_id, action_unit=METERED_ACTION_UNIT)
    should_block_metered_work = normalized_action in {"payment_failed", "cancel"}
    metered_work_guard_ok = quota.get("blocked") is should_block_metered_work
    event = billing_event.get("event") if isinstance(billing_event.get("event"), dict) else {}
    subscription = usage.get("subscription") if isinstance(usage.get("subscription"), dict) else {}
    steps = [
        _step(
            "test_checkout_session",
            bool(checkout.get("ok")),
            evidence={
                "provider_mode": "test_mock",
                "mode": "subscription",
                "session_id_present": bool(checkout_session.get("id")),
                "session_url_returned": False,
            },
        ),
        _step(
            "backend_order_query_or_signed_webhook_proof",
            bool(provider_proof.get("verified")),
            evidence={
                "proof_source": provider_proof["proof_source"],
                "signed_webhook_or_order_query_verified": provider_proof["signed_webhook_or_order_query_verified"],
                "frontend_submitted_entitlement": False,
            },
        ),
        _step(
            "subscription_event_applied",
            billing_event.get("status") == "billing_test_event_applied",
            evidence={
                "event_type": event.get("event_type") or "",
                "subscription_status": event.get("subscription_status") or "",
                "provider_subscription_id_present": bool(event.get("provider_subscription_id_present")),
            },
        ),
        _step(
            "quota_guardrail_evaluated",
            metered_work_guard_ok,
            evidence={
                "action_unit": quota.get("action_unit") or METERED_ACTION_UNIT,
                "allowed": bool(quota.get("allowed")),
                "blocked": bool(quota.get("blocked")),
                "reason": quota.get("reason") or "",
            },
        ),
    ]
    ready = all(item["status"] == "ready" for item in steps)
    repository.write_audit(
        company_id=company_id,
        user_id=user_id,
        actor_type="user",
        action_type="billing.provider_rehearsal.completed",
        target_type="billing_subscription",
        target_id=str(event.get("event_type") or normalized_action),
        summary="No-charge billing provider rehearsal completed through checkout, backend proof, subscription event and quota guard.",
        details={
            "provider": provider,
            "plan_key": normalized_plan,
            "action": normalized_action,
            "ready": ready,
            "provider_proof_id_present": bool(provider_proof.get("proof_id")),
            "quota_guardrail_ok": metered_work_guard_ok,
            "creates_real_checkout_session": False,
            "calls_external_payment_api": False,
            "triggers_real_charge": False,
            "charge_now_allowed": False,
            "frontend_gets_payment_secret": False,
            "secret_exposed": False,
        },
    )
    return {
        "ok": ready,
        "status": "billing_provider_rehearsal_completed" if ready else "billing_provider_rehearsal_attention_required",
        "contract_version": "2026-07-01-no-charge-provider-rehearsal",
        "provider": provider,
        "provider_mode": "test_mock",
        "plan_key": normalized_plan,
        "action": normalized_action,
        "checkout": _public_checkout_presence(checkout),
        "provider_proof": provider_proof,
        "billing_event": {
            "status": billing_event.get("status") or "",
            "event_type": event.get("event_type") or "",
            "subscription_status": event.get("subscription_status") or "",
            "provider_customer_id_present": bool(event.get("provider_customer_id_present")),
            "provider_subscription_id_present": bool(event.get("provider_subscription_id_present")),
            "provider_plan_id_present": bool(event.get("provider_plan_id_present")),
        },
        "subscription": {
            "provider": subscription.get("provider") or provider,
            "status": subscription.get("status") or "",
            "plan_key": subscription.get("plan_key") or normalized_plan,
            "entitlement_active": bool(subscription.get("entitlement_active")),
            "payment_attention_required": bool(subscription.get("payment_attention_required")),
            "block_reason": subscription.get("block_reason") or "",
        },
        "quota_guardrail": {
            "action_unit": quota.get("action_unit") or METERED_ACTION_UNIT,
            "allowed": bool(quota.get("allowed")),
            "blocked": bool(quota.get("blocked")),
            "reason": quota.get("reason") or "",
            "expected_blocked": should_block_metered_work,
            "ok": metered_work_guard_ok,
        },
        "steps": steps,
        "ready_for_test_rehearsal": ready,
        "ready_for_paid_launch": False,
        "public_charging_allowed": False,
        "creates_real_checkout_session": False,
        "calls_external_payment_api": False,
        "triggers_real_charge": False,
        "charge_now_allowed": False,
        "frontend_gets_payment_secret": False,
        "raw_provider_response_stored": False,
        "secret_exposed": False,
    }


def _mock_order_query_proof(
    *,
    provider: str,
    company_id: str,
    plan_key: str,
    action: str,
    checkout_session_id: str,
) -> dict[str, Any]:
    paid_like = action in {"activate", "invoice_paid"}
    proof_id = _stable_proof_id(provider, company_id, plan_key, action, checkout_session_id)
    return {
        "proof_id": proof_id,
        "proof_id_present": bool(proof_id),
        "proof_source": "backend_test_provider_order_query",
        "provider_order_id_present": bool(checkout_session_id),
        "provider_subscription_status": "paid" if paid_like else "attention_required",
        "signed_webhook_or_order_query_verified": True,
        "verified": True,
        "frontend_submitted_entitlement": False,
        "browser_can_grant_quota": False,
        "raw_provider_response_stored": False,
        "creates_real_checkout_session": False,
        "calls_external_payment_api": False,
        "triggers_real_charge": False,
        "charge_now_allowed": False,
        "frontend_gets_payment_secret": False,
        "secret_exposed": False,
    }


def _public_checkout_presence(checkout: dict[str, Any]) -> dict[str, Any]:
    session = checkout.get("checkout_session") if isinstance(checkout.get("checkout_session"), dict) else {}
    return {
        "status": checkout.get("status") or "",
        "provider": checkout.get("provider") or selected_billing_provider(),
        "provider_mode": checkout.get("provider_mode") or "test_mock",
        "plan_key": checkout.get("plan_key") or "",
        "session_id_present": bool(session.get("id")),
        "session_url_present": bool(session.get("url")),
        "session_url_returned": False,
        "creates_real_checkout_session": False,
        "calls_external_payment_api": False,
        "triggers_real_charge": False,
        "charge_now_allowed": False,
        "frontend_gets_payment_secret": False,
        "secret_exposed": False,
    }


def _step(key: str, ready: bool, *, evidence: dict[str, Any]) -> dict[str, Any]:
    return {
        "key": key,
        "status": "ready" if ready else "blocked",
        "evidence": evidence,
        "creates_real_checkout_session": False,
        "calls_external_payment_api": False,
        "triggers_real_charge": False,
        "charge_now_allowed": False,
        "frontend_gets_payment_secret": False,
        "secret_exposed": False,
    }


def _stable_proof_id(*parts: str) -> str:
    seed = ":".join([*parts, str(int(time.time() // 60))])
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24]
    return f"proof_mock_{digest}"


def _blocked(reason: str, *, http_status: int, provider: str) -> dict[str, Any]:
    return {
        "ok": False,
        "status": "blocked",
        "http_status": http_status,
        "blocked_by": [reason],
        "provider": provider or "not_selected",
        "ready_for_paid_launch": False,
        "public_charging_allowed": False,
        "creates_real_checkout_session": False,
        "calls_external_payment_api": False,
        "triggers_real_charge": False,
        "charge_now_allowed": False,
        "frontend_gets_payment_secret": False,
        "secret_exposed": False,
    }
