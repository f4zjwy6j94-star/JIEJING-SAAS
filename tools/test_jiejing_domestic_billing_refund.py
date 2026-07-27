#!/usr/bin/env python3
"""Regression for review-gated domestic refund state transitions."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.billing_domestic import (  # noqa: E402
    apply_verified_domestic_refund,
    execute_approved_domestic_billing_refund,
    request_domestic_billing_refund_review,
)
from jiejing_saas.config import SaaSSettings  # noqa: E402
from jiejing_saas.repository import SaaSRepository  # noqa: E402


OUT = ROOT / "output" / "jiejing-domestic-billing-refund-test"


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True, exist_ok=True)
    settings = SaaSSettings.from_env(
        db_path=OUT / "saas.sqlite",
        runtime_db_path=OUT / "runtime.sqlite",
        output_root=OUT,
        host="127.0.0.1",
        port=8788,
    )
    repository = SaaSRepository(settings.db_path)
    account = repository.create_user_with_company(
        email="refund-owner@example.test",
        password="Refund-owner-test-2026",
        company_name="Refund Test",
    )
    company_id = str(account["company"]["company_id"])
    user_id = str(account["user"]["user_id"])
    order_id = "domestic_refund_test_order"
    repository.create_domestic_billing_order_record(
        order_id=order_id,
        company_id=company_id,
        user_id=user_id,
        provider="wechat_pay_native",
        plan_key="starter",
        amount_minor=9900,
        currency="CNY",
        duration_days=30,
        status="pending_payment",
        idempotency_key_hash="c" * 64,
        order={"provider_mode": "refund_state_test"},
    )
    repository.mark_domestic_billing_order_paid(
        company_id=company_id,
        order_id=order_id,
        provider_order_id="wx-paid-before-refund",
        paid_at="2026-07-13T04:00:00+00:00",
        payment={"signature_verified": True, "amount_verified": True},
    )
    repository.apply_billing_webhook_event(
        event={
            "provider": "wechat_pay_native",
            "event_id": "wx-paid-before-refund",
            "event_type": "payment_succeeded",
            "supported_event": True,
            "company_id": company_id,
            "provider_customer_id": "merchant-fixture",
            "provider_subscription_id": order_id,
            "provider_plan_id": "wechat_native_starter_9900_30d",
            "plan_key": "starter",
            "subscription_status": "active",
        }
    )

    missing_reason = request_domestic_billing_refund_review(
        repository,
        company_id=company_id,
        user_id=user_id,
        order_id=order_id,
        reason=" ",
    )
    if missing_reason.get("reason") != "domestic_refund_reason_required":
        return fail(f"empty refund reasons must be rejected: {missing_reason}")
    long_reason = request_domestic_billing_refund_review(
        repository,
        company_id=company_id,
        user_id=user_id,
        order_id=order_id,
        reason="x" * 501,
    )
    if long_reason.get("reason") != "domestic_refund_reason_too_long":
        return fail(f"oversized refund reasons must be rejected: {long_reason}")

    requested = request_domestic_billing_refund_review(
        repository,
        company_id=company_id,
        user_id=user_id,
        order_id=order_id,
        reason="Service no longer needed; password=placeholder-value",
    )
    if requested.get("ok") is not True or requested.get("status") != "refund_review_requested":
        return fail(f"merchant should be able to request a review: {requested}")
    if requested.get("calls_external_payment_api") is not False or requested.get("triggers_real_refund") is not False:
        return fail(f"review request must not execute a refund: {requested}")
    confirmation_id = str(requested.get("confirmation_id") or "")
    confirmation = repository.get_confirmation(company_id=company_id, confirmation_id=confirmation_id)
    if not confirmation or confirmation.get("action_type") != "refund" or confirmation.get("store_id") is not None:
        return fail(f"refund review must create an account-scoped confirmation item: {confirmation}")
    if confirmation.get("status") != "pending" or confirmation.get("item", {}).get("order_id") != order_id:
        return fail(f"refund confirmation must hold the exact tenant order pending approval: {confirmation}")
    blocked_execute = execute_approved_domestic_billing_refund(
        repository,
        company_id=company_id,
        user_id=user_id,
        order_id=order_id,
        provider_refund=lambda **_: {"ok": True},
    )
    if blocked_execute.get("reason") != "domestic_refund_confirmation_not_approved":
        return fail(f"provider refund must remain blocked before confirmation approval: {blocked_execute}")
    review_order = repository.get_domestic_billing_order(company_id=company_id, order_id=order_id) or {}
    review_state = review_order.get("order", {}).get("state", {})
    if review_state.get("refund_reason_summary") != "Service no longer needed; password=[redacted]":
        return fail(f"refund reason should be useful but credential-redacted: {review_state}")
    if review_state.get("refund_reason_raw_persisted") is not False:
        return fail(f"raw refund reason persistence must remain disabled: {review_state}")
    active = repository.get_billing_subscription(company_id=company_id)
    if not active or active.get("entitlement_active") is not True:
        return fail(f"requesting review alone must not revoke paid access: {active}")

    tampered_item = dict(confirmation.get("item") or {})
    tampered_item["amount_minor"] = 1
    with repository._connect() as conn:  # noqa: SLF001 - adversarial persistence fixture
        conn.execute(
            "update confirmations set item_json = ? where company_id = ? and confirmation_id = ?",
            (json.dumps(tampered_item, ensure_ascii=False), company_id, confirmation_id),
        )
    repository.decide_confirmation(
        company_id=company_id,
        confirmation_id=confirmation_id,
        decision="approve",
        decided_by=user_id,
        note="Adversarial approval fixture.",
    )
    provider_calls: list[str] = []

    def forbidden_provider_refund(**_: object) -> dict[str, object]:
        provider_calls.append(order_id)
        return {"ok": True, "provider_response": {}}

    tampered_execute = execute_approved_domestic_billing_refund(
        repository,
        company_id=company_id,
        user_id=user_id,
        order_id=order_id,
        provider_refund=forbidden_provider_refund,
    )
    if tampered_execute.get("reason") != "domestic_refund_confirmation_invalid" or provider_calls:
        return fail(f"stale or tampered refund approvals must fail before Provider execution: {tampered_execute}, {provider_calls}")

    unverified = apply_verified_domestic_refund(
        repository,
        company_id=company_id,
        order_id=order_id,
        provider_refund_id="wx-refund-test-1",
        amount_minor=9900,
        currency="CNY",
        provider_verified=False,
    )
    if unverified.get("reason") != "domestic_refund_not_provider_verified":
        return fail(f"browser-supplied refund claims must be blocked: {unverified}")

    first = apply_verified_domestic_refund(
        repository,
        company_id=company_id,
        order_id=order_id,
        provider_refund_id="wx-refund-test-1",
        amount_minor=9900,
        currency="CNY",
        provider_verified=True,
    )
    second = apply_verified_domestic_refund(
        repository,
        company_id=company_id,
        order_id=order_id,
        provider_refund_id="wx-refund-test-1",
        amount_minor=9900,
        currency="CNY",
        provider_verified=True,
    )
    if first.get("status") != "refunded" or second.get("duplicate_refund_result") is not True:
        return fail(f"verified refund result should be durable and idempotent: {first}, {second}")
    stored = repository.get_domestic_billing_order(company_id=company_id, order_id=order_id)
    subscription = repository.get_billing_subscription(company_id=company_id)
    if not stored or stored.get("status") != "refunded":
        return fail(f"order should persist refunded state: {stored}")
    if not subscription or subscription.get("entitlement_active") is not False or subscription.get("status") != "refunded":
        return fail(f"verified refund should close the matching entitlement: {subscription}")

    print("PASS jiejing_domestic_billing_refund")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
