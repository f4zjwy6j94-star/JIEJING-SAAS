#!/usr/bin/env python3
"""Regression test for provider-neutral media point purchases."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.billing_domestic import (  # noqa: E402
    apply_verified_domestic_refund,
    create_domestic_billing_order,
    execute_approved_domestic_billing_refund,
    merchant_domestic_billing_order,
    request_domestic_billing_refund_review,
)
from jiejing_saas.billing_wechat_pay import (  # noqa: E402
    reconcile_wechat_pay_order_query,
    recover_paid_wechat_pay_entitlement,
)
from jiejing_saas.repository import SaaSRepository  # noqa: E402


OUT = ROOT / "output" / "jiejing-media-credit-purchase-test"
APP_ID = "wx-media-points-test"
MCH_ID = "1900000109"


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True, exist_ok=True)
    repository = SaaSRepository(OUT / "saas.sqlite")
    account = repository.create_user_with_company(
        email="media-points@example.test",
        password="Media-points-test-2026",
        company_name="Media Points Test",
    )
    company_id = str(account["company"]["company_id"])
    user_id = str(account["user"]["user_id"])

    with patch.dict("os.environ", {"JIEJING_MEDIA_CREDIT_PURCHASE_ENABLED": "false"}, clear=False):
        blocked = create_domestic_billing_order(
            repository,
            company_id=company_id,
            user_id=user_id,
            provider="wechat_pay_native",
            plan_key="media_points_1000",
            idempotency_key="media-points-disabled-1",
            rehearsal=False,
        )
    if blocked.get("reason") != "media_credit_purchase_not_enabled":
        return fail(f"disabled media purchases must fail closed: {blocked}")

    with patch.dict("os.environ", {"JIEJING_MEDIA_CREDIT_PURCHASE_ENABLED": "true"}, clear=False):
        created = create_domestic_billing_order(
            repository,
            company_id=company_id,
            user_id=user_id,
            provider="wechat_pay_native",
            plan_key="media_points_1000",
            idempotency_key="media-points-purchase-1",
            rehearsal=False,
        )
    if created.get("ok") is not True or created.get("purchase_type") != "media_points":
        return fail(f"media point order should use its own purchase contract: {created}")
    if created.get("media_points") != 1000 or created.get("amount_minor") != 1000 or created.get("duration_days") != 0:
        return fail(f"media point order terms are incorrect: {created}")
    stored = repository.get_domestic_billing_order(company_id=company_id, order_id=str(created["order_id"]))
    merchant = merchant_domestic_billing_order(stored or {})
    if merchant.get("purchase_type") != "media_points" or merchant.get("media_points") != 1000:
        return fail(f"merchant order must identify a media point purchase without provider details: {merchant}")

    provider_response = {
        "appid": APP_ID,
        "mchid": MCH_ID,
        "out_trade_no": str(created["order_id"]),
        "transaction_id": "wx-media-points-transaction-1",
        "trade_type": "NATIVE",
        "trade_state": "SUCCESS",
        "success_time": "2026-07-14T12:15:00+08:00",
        "amount": {"total": 1000, "payer_total": 1000, "currency": "CNY"},
    }
    first = reconcile_wechat_pay_order_query(
        repository,
        company_id=company_id,
        order_id=str(created["order_id"]),
        provider_response=provider_response,
        query_authenticated=True,
        expected_appid=APP_ID,
        expected_mchid=MCH_ID,
    )
    second = reconcile_wechat_pay_order_query(
        repository,
        company_id=company_id,
        order_id=str(created["order_id"]),
        provider_response=provider_response,
        query_authenticated=True,
        expected_appid=APP_ID,
        expected_mchid=MCH_ID,
    )
    if first.get("status") != "payment_confirmed" or first.get("media_points_granted") != 1000:
        return fail(f"verified media payment should grant points: {first}")
    if second.get("duplicate_notification") is not True or second.get("media_points_granted") != 1000:
        return fail(f"duplicate media payment must be idempotent: {second}")
    credit_account = repository.get_media_credit_account(company_id=company_id)
    if credit_account.get("available_points") != 1000:
        return fail(f"duplicate payment must grant exactly once: {credit_account}")
    if repository.get_billing_subscription(company_id=company_id):
        return fail("buying media points must never activate a software subscription")

    recovered = recover_paid_wechat_pay_entitlement(
        repository,
        company_id=company_id,
        order_id=str(created["order_id"]),
        expected_mchid=MCH_ID,
    )
    if recovered.get("ok") is not True or recovered.get("media_points_recovered") is not False:
        return fail(f"media point recovery should be idempotent: {recovered}")
    if repository.get_media_credit_account(company_id=company_id).get("available_points") != 1000:
        return fail("recovery must not duplicate media points")

    refunded = apply_verified_domestic_refund(
        repository,
        company_id=company_id,
        order_id=str(created["order_id"]),
        provider_refund_id="wx-media-points-refund-1",
        amount_minor=1000,
        currency="CNY",
        provider_verified=True,
    )
    if refunded.get("ok") is not True or refunded.get("media_points_revoked") != 1000:
        return fail(f"verified media refund should revoke the purchased points: {refunded}")
    if repository.get_media_credit_account(company_id=company_id).get("available_points") != 0:
        return fail("refunded media points must no longer be spendable")

    with patch.dict("os.environ", {"JIEJING_MEDIA_CREDIT_PURCHASE_ENABLED": "true"}, clear=False):
        spent_order = create_domestic_billing_order(
            repository,
            company_id=company_id,
            user_id=user_id,
            provider="wechat_pay_native",
            plan_key="media_points_5000",
            idempotency_key="media-points-purchase-spent",
            rehearsal=False,
        )
    spent_provider_response = {
        **provider_response,
        "out_trade_no": str(spent_order["order_id"]),
        "transaction_id": "wx-media-points-transaction-spent",
        "amount": {"total": 5000, "payer_total": 5000, "currency": "CNY"},
    }
    spent_paid = reconcile_wechat_pay_order_query(
        repository,
        company_id=company_id,
        order_id=str(spent_order["order_id"]),
        provider_response=spent_provider_response,
        query_authenticated=True,
        expected_appid=APP_ID,
        expected_mchid=MCH_ID,
    )
    if spent_paid.get("media_points_granted") != 5000:
        return fail(f"second media pack should be granted: {spent_paid}")
    reservation = repository.apply_media_credit_operation(
        company_id=company_id,
        user_id=user_id,
        operation_type="reserve",
        points=100,
        idempotency_key="spent-pack-job-reserve",
        reference_type="media_job",
        reference_id="spent-pack-job",
    )
    repository.apply_media_credit_operation(
        company_id=company_id,
        user_id=user_id,
        operation_type="settle",
        points=100,
        idempotency_key="spent-pack-job-settle",
        reference_type="media_job",
        reference_id="spent-pack-job",
        reservation_id=str(reservation["ledger_entry"]["ledger_id"]),
    )
    review = request_domestic_billing_refund_review(
        repository,
        company_id=company_id,
        user_id=user_id,
        order_id=str(spent_order["order_id"]),
        reason="测试已使用素材点时的退款门禁",
    )
    repository.decide_confirmation(
        company_id=company_id,
        confirmation_id=str(review.get("confirmation_id") or ""),
        decision="approve",
        decided_by=user_id,
        note="Approved test fixture.",
    )
    provider_calls: list[str] = []

    def forbidden_refund(**_: object) -> dict[str, object]:
        provider_calls.append("called")
        return {"ok": True}

    blocked_refund = execute_approved_domestic_billing_refund(
        repository,
        company_id=company_id,
        user_id=user_id,
        order_id=str(spent_order["order_id"]),
        provider_refund=forbidden_refund,
    )
    if blocked_refund.get("reason") != "media_points_refund_requires_unused_balance" or provider_calls:
        return fail(f"spent media points must block cash refund before Provider execution: {blocked_refund}, {provider_calls}")

    print("PASS media point purchase, idempotent grant, subscription isolation, recovery, refund revoke, and spent-point guard")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
