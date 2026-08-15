#!/usr/bin/env python3
"""Adversarial checks for tenant-safe payment operations and bounded reconciliation."""

from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "jiejing-domestic-billing-operations-test"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.billing_domestic import (  # noqa: E402
    DOMESTIC_RECONCILIATION_BATCH_LIMIT,
    build_domestic_billing_operations_snapshot,
    reconcile_domestic_billing_orders,
)
from jiejing_saas.billing_wechat_pay import recover_paid_wechat_pay_entitlement  # noqa: E402
from jiejing_saas.repository import SaaSRepository  # noqa: E402


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True, exist_ok=True)
    repository = SaaSRepository(OUT / "saas.sqlite")
    owner = repository.create_user_with_company(
        email="billing-operations-owner@example.test",
        password="Billing-operations-owner-2026",
        company_name="Billing Operations Owner",
    )
    other = repository.create_user_with_company(
        email="billing-operations-other@example.test",
        password="Billing-operations-other-2026",
        company_name="Billing Operations Other",
    )
    company_id = str(owner["company"]["company_id"])
    user_id = str(owner["user"]["user_id"])
    other_company_id = str(other["company"]["company_id"])
    other_user_id = str(other["user"]["user_id"])
    now = datetime(2026, 7, 14, 4, 0, tzinfo=timezone.utc)

    historical = repository.create_user_with_company(
        email="billing-operations-historical@example.test",
        password="Billing-operations-historical-2026",
        company_name="Billing Operations Historical",
    )
    historical_company_id = str(historical["company"]["company_id"])
    historical_user_id = str(historical["user"]["user_id"])
    historical_active_until = datetime.now(timezone.utc) + timedelta(days=1)
    _create_paid_order(
        repository,
        order_id="domestic_historical_fulfilled_1",
        company_id=historical_company_id,
        user_id=historical_user_id,
        active_until=historical_active_until,
        verified_payment=True,
    )
    historical_applied = repository.apply_billing_webhook_event(
        event={
            "provider": "wechat_pay_native",
            "event_id": "domestic-historical-fulfilled-event-1",
            "event_type": "payment_succeeded",
            "supported_event": True,
            "company_id": historical_company_id,
            "provider_customer_id": "historical-merchant-fixture",
            "provider_subscription_id": "domestic_historical_fulfilled_1",
            "provider_plan_id": "wechat_native_starter_9900_30d",
            "plan_key": "starter",
            "subscription_status": "active",
            "duration_days": 30,
            "active_until": historical_active_until.isoformat(),
            "quota_recalculation_required": True,
            "raw_payload_persisted": False,
            "raw_signature_persisted": False,
            "secret_exposed": False,
        }
    )
    if historical_applied.get("status") != "applied":
        return fail(f"historical paid entitlement fixture was not applied: {historical_applied}")
    historical_expired = repository.apply_billing_webhook_event(
        event={
            "provider": "wechat_pay_native",
            "event_id": "domestic-historical-expired-event-1",
            "event_type": "subscription_expired",
            "supported_event": True,
            "company_id": historical_company_id,
            "provider_customer_id": "historical-merchant-fixture",
            "provider_subscription_id": "domestic_historical_fulfilled_1",
            "provider_plan_id": "wechat_native_starter_9900_30d",
            "plan_key": "starter",
            "subscription_status": "expired",
            "duration_days": 30,
            "active_until": historical_active_until.isoformat(),
            "quota_recalculation_required": True,
            "raw_payload_persisted": False,
            "raw_signature_persisted": False,
            "secret_exposed": False,
        }
    )
    if historical_expired.get("status") != "applied":
        return fail(f"historical entitlement expiry fixture was not applied: {historical_expired}")
    historical_snapshot = build_domestic_billing_operations_snapshot(
        repository,
        company_id=historical_company_id,
        now=historical_active_until + timedelta(days=1),
    )
    if (
        historical_snapshot.get("status") != "healthy"
        or historical_snapshot.get("action_required_count") != 0
        or historical_snapshot.get("incidents")
    ):
        return fail(
            "a paid order whose full entitlement window elapsed must remain fulfilled without a recovery incident: "
            f"{historical_snapshot}"
        )

    expired_order = _create_order(
        repository,
        order_id="domestic_expired_ops_1",
        company_id=company_id,
        user_id=user_id,
        expires_at=now - timedelta(minutes=1),
    )
    paid_order = _create_paid_order(
        repository,
        order_id="domestic_paid_ops_1",
        company_id=company_id,
        user_id=user_id,
        active_until=now + timedelta(days=60),
    )
    refund_order = _create_paid_order(
        repository,
        order_id="domestic_refund_ops_1",
        company_id=company_id,
        user_id=user_id,
        active_until=now + timedelta(days=30),
    )
    repository.update_domestic_billing_order_state(
        company_id=company_id,
        user_id=user_id,
        order_id=refund_order["order_id"],
        status="refund_review_requested",
        allowed_current_statuses={"paid"},
        state_details={"provider_refund_called": False},
        audit_action="billing.domestic_refund.review_requested",
        audit_summary="Refund review test request.",
    )
    foreign_order = _create_order(
        repository,
        order_id="domestic_foreign_ops_1",
        company_id=other_company_id,
        user_id=other_user_id,
        expires_at=now - timedelta(minutes=1),
    )
    legacy_order = _create_legacy_paid_order(
        repository,
        order_id="domestic_legacy_paid_ops_1",
        company_id=company_id,
        user_id=user_id,
        paid_at=now,
    )
    legacy_recovery = recover_paid_wechat_pay_entitlement(
        repository,
        company_id=company_id,
        order_id=legacy_order["order_id"],
        expected_mchid="1900000109",
    )
    if legacy_recovery.get("ok") is not True or legacy_recovery.get("entitlement_recovered") is not True:
        return fail(f"verified legacy paid order should be recoverable without an incident: {legacy_recovery}")

    snapshot = build_domestic_billing_operations_snapshot(repository, company_id=company_id, now=now)
    if snapshot.get("order_count") != 4 or snapshot.get("action_required_count") != 3:
        return fail(f"snapshot should ignore the recovered legacy order and classify three actionable owner orders: {snapshot}")
    codes = {str(item.get("code") or "") for item in snapshot.get("incidents", [])}
    expected_codes = {"checkout_expired", "paid_entitlement_recovery_required", "refund_review_pending"}
    if codes != expected_codes:
        return fail(f"snapshot incident classification drifted: {codes}")
    serialized = json.dumps(snapshot, ensure_ascii=False).lower()
    if foreign_order["order_id"].lower() in serialized or other_company_id.lower() in serialized:
        return fail("operations snapshot crossed the tenant boundary")
    if any(secret_word in serialized for secret_word in ("private_key", "api_v3", "authorization:")):
        return fail(f"operations snapshot exposed credential-shaped data: {serialized}")
    if snapshot.get("calls_external_payment_api") is not False or snapshot.get("triggers_real_refund") is not False:
        return fail(f"snapshot must remain read-only: {snapshot}")

    calls: list[str] = []

    def fake_query(_repository: SaaSRepository, scoped_company_id: str, order_id: str) -> dict[str, Any]:
        if scoped_company_id != company_id:
            raise AssertionError("reconciliation query escaped the company scope")
        calls.append(order_id)
        return {
            "ok": True,
            "status": "checked",
            "order_id": order_id,
            "calls_external_payment_api": order_id == expired_order["order_id"],
            "provider_response": {"must_not_be_exposed": True},
            "secret_exposed": False,
        }

    batch = reconcile_domestic_billing_orders(
        repository,
        company_id=company_id,
        order_ids=[expired_order["order_id"], paid_order["order_id"], expired_order["order_id"], foreign_order["order_id"]],
        query_order=fake_query,
    )
    if calls != [expired_order["order_id"], paid_order["order_id"]]:
        return fail(f"batch should deduplicate and avoid querying a foreign order: {calls}")
    if batch.get("requested_count") != 3 or batch.get("succeeded_count") != 2 or batch.get("attention_count") != 1:
        return fail(f"batch partial-success accounting is incorrect: {batch}")
    if "must_not_be_exposed" in json.dumps(batch, ensure_ascii=False):
        return fail(f"batch leaked a raw provider response: {batch}")
    if batch.get("triggers_real_charge") is not False or batch.get("triggers_real_refund") is not False:
        return fail(f"batch must never move money: {batch}")

    too_many = reconcile_domestic_billing_orders(
        repository,
        company_id=company_id,
        order_ids=[f"domestic_batch_{index:02d}" for index in range(DOMESTIC_RECONCILIATION_BATCH_LIMIT + 1)],
        query_order=fake_query,
    )
    if too_many.get("reason") != "domestic_reconciliation_batch_too_large" or too_many.get("http_status") != 400:
        return fail(f"oversized reconciliation batch must fail closed: {too_many}")

    print("PASS jiejing_domestic_billing_operations")
    return 0


def _create_order(
    repository: SaaSRepository,
    *,
    order_id: str,
    company_id: str,
    user_id: str,
    expires_at: datetime,
) -> dict[str, Any]:
    return repository.create_domestic_billing_order_record(
        order_id=order_id,
        company_id=company_id,
        user_id=user_id,
        provider="wechat_pay_native",
        plan_key="starter",
        amount_minor=9900,
        currency="CNY",
        duration_days=30,
        status="pending_payment",
        idempotency_key_hash=f"hash-{order_id}",
        expires_at=expires_at.isoformat(),
        order={"payment_secret_persisted": False, "secret_exposed": False},
    )


def _create_paid_order(
    repository: SaaSRepository,
    *,
    order_id: str,
    company_id: str,
    user_id: str,
    active_until: datetime,
    verified_payment: bool = False,
) -> dict[str, Any]:
    created = _create_order(
        repository,
        order_id=order_id,
        company_id=company_id,
        user_id=user_id,
        expires_at=active_until,
    )
    active_from = active_until - timedelta(days=30)
    paid = repository.mark_domestic_billing_order_paid(
        company_id=company_id,
        order_id=created["order_id"],
        provider_order_id=f"legacy-{order_id}",
        paid_at=active_from.isoformat(),
        payment={
            "provider_transaction_present": True,
            "appid_verified": True,
            "mchid_verified": True,
            "amount_verified": True,
            "amount_minor": 9900,
            "currency": "CNY",
            "entitlement_active_from": active_from.isoformat(),
            "entitlement_active_until": active_until.isoformat(),
            "signature_verified": True if verified_payment else False,
            "verification_source": "signed_callback" if verified_payment else "",
            "secret_exposed": False,
        },
    )
    if not paid:
        raise AssertionError("paid order fixture could not be created")
    return paid


def _create_legacy_paid_order(
    repository: SaaSRepository,
    *,
    order_id: str,
    company_id: str,
    user_id: str,
    paid_at: datetime,
) -> dict[str, Any]:
    created = _create_order(
        repository,
        order_id=order_id,
        company_id=company_id,
        user_id=user_id,
        expires_at=paid_at + timedelta(minutes=15),
    )
    paid = repository.mark_domestic_billing_order_paid(
        company_id=company_id,
        order_id=created["order_id"],
        provider_order_id=f"4200000000{order_id[-8:]}",
        paid_at=paid_at.isoformat(),
        payment={
            "provider_transaction_present": True,
            "appid_verified": True,
            "mchid_verified": True,
            "amount_verified": True,
            "amount_minor": 9900,
            "currency": "CNY",
            "signature_verified": True,
            "verification_source": "signed_callback",
            "secret_exposed": False,
        },
    )
    if not paid:
        raise AssertionError("legacy paid order fixture could not be created")
    return paid


if __name__ == "__main__":
    raise SystemExit(main())
