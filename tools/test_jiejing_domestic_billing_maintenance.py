#!/usr/bin/env python3
"""Adversarial checks for bounded, query-only domestic billing maintenance."""

from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "jiejing-domestic-billing-maintenance-test"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.billing_operations_maintenance import run_domestic_billing_maintenance  # noqa: E402
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
        email="billing-maintenance-owner@example.test",
        password="Billing-maintenance-owner-2026",
        company_name="Billing Maintenance Owner",
    )
    other = repository.create_user_with_company(
        email="billing-maintenance-other@example.test",
        password="Billing-maintenance-other-2026",
        company_name="Billing Maintenance Other",
    )
    now = datetime(2026, 7, 14, 5, 0, tzinfo=timezone.utc)
    company_id = str(owner["company"]["company_id"])
    user_id = str(owner["user"]["user_id"])
    other_company_id = str(other["company"]["company_id"])
    other_user_id = str(other["user"]["user_id"])

    expired = _create_order(repository, "domestic_maint_expired_1", company_id, user_id, now - timedelta(minutes=1))
    paid = _create_paid_order(repository, "domestic_maint_paid_1", company_id, user_id, now + timedelta(days=30))
    review = _create_paid_order(repository, "domestic_maint_review_1", company_id, user_id, now + timedelta(days=30))
    _transition(repository, company_id, user_id, review["order_id"], "refund_review_requested", {"paid"})
    processing = _create_paid_order(repository, "domestic_maint_processing_1", company_id, user_id, now + timedelta(days=30))
    _transition(repository, company_id, user_id, processing["order_id"], "refund_review_requested", {"paid"})
    _transition(repository, company_id, user_id, processing["order_id"], "refund_processing", {"refund_review_requested"})
    foreign = _create_order(repository, "domestic_maint_foreign_1", other_company_id, other_user_id, now - timedelta(minutes=1))

    payment_calls: list[tuple[str, str]] = []
    refund_calls: list[tuple[str, str]] = []

    def fake_payment_query(_repository: SaaSRepository, scoped_company: str, order_id: str) -> dict[str, Any]:
        payment_calls.append((scoped_company, order_id))
        if order_id == paid["order_id"]:
            raise TimeoutError("provider details must not leak")
        return {
            "ok": True,
            "status": "pending_payment",
            "calls_external_payment_api": True,
            "provider_response": {"payer_account": "must-not-leak"},
        }

    def fake_refund_query(_repository: SaaSRepository, scoped_company: str, order_id: str) -> dict[str, Any]:
        refund_calls.append((scoped_company, order_id))
        return {
            "ok": True,
            "status": "refund_processing",
            "calls_external_payment_api": True,
            "provider_response": {"user_received_account": "must-not-leak"},
        }

    passive = run_domestic_billing_maintenance(
        repository,
        now=now,
        auto_reconcile=False,
        query_payment=fake_payment_query,
        query_refund=fake_refund_query,
    )
    if payment_calls or refund_calls:
        return fail("passive maintenance must not call a Provider")
    if passive.get("action_required_count", 0) < 5 or passive.get("calls_external_payment_api") is not False:
        return fail(f"passive maintenance did not expose the bounded incident summary: {passive}")

    active = run_domestic_billing_maintenance(
        repository,
        now=now,
        auto_reconcile=True,
        max_companies=10,
        max_orders_per_company=10,
        query_payment=fake_payment_query,
        query_refund=fake_refund_query,
    )
    owner_payment_ids = {order_id for scoped, order_id in payment_calls if scoped == company_id}
    if owner_payment_ids != {expired["order_id"], paid["order_id"]}:
        return fail(f"maintenance queried the wrong owner payment orders: {payment_calls}")
    if (company_id, review["order_id"]) in payment_calls or (company_id, review["order_id"]) in refund_calls:
        return fail("a refund awaiting human approval must never be executed or queried as approved")
    if (company_id, processing["order_id"]) not in refund_calls:
        return fail(f"refund processing recovery was not queried: {refund_calls}")
    if (other_company_id, foreign["order_id"]) not in payment_calls:
        return fail("maintenance did not process the second tenant independently")
    serialized = json.dumps(active, ensure_ascii=False).lower()
    for forbidden in (company_id.lower(), other_company_id.lower(), expired["order_id"].lower(), "must-not-leak", "provider details"):
        if forbidden in serialized:
            return fail(f"maintenance output leaked an internal or Provider value: {forbidden}")
    if active.get("failed_query_count") != 1 or active.get("alert_required") is not True:
        return fail(f"partial Provider failure must be isolated and alerted: {active}")
    if active.get("triggers_real_charge") is not False or active.get("triggers_real_refund") is not False:
        return fail(f"maintenance must never move money: {active}")

    bounded = run_domestic_billing_maintenance(
        repository,
        now=now,
        auto_reconcile=True,
        max_companies=10,
        max_orders_per_company=10,
        max_queries_per_run=2,
        query_payment=fake_payment_query,
        query_refund=fake_refund_query,
    )
    if bounded.get("company_count") != 2 or bounded.get("query_attempt_count", 0) > 2:
        return fail(f"maintenance limits were not enforced: {bounded}")
    if bounded.get("max_queries_per_run") != 2 or bounded.get("query_budget_exhausted") is not True:
        return fail(f"maintenance must expose its global Provider query budget: {bounded}")

    print("PASS jiejing_domestic_billing_maintenance")
    return 0


def _create_order(repository: SaaSRepository, order_id: str, company_id: str, user_id: str, expires_at: datetime) -> dict[str, Any]:
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


def _create_paid_order(repository: SaaSRepository, order_id: str, company_id: str, user_id: str, active_until: datetime) -> dict[str, Any]:
    created = _create_order(repository, order_id, company_id, user_id, active_until)
    active_from = active_until - timedelta(days=30)
    paid = repository.mark_domestic_billing_order_paid(
        company_id=company_id,
        order_id=created["order_id"],
        provider_order_id=f"4200000000{order_id[-8:]}",
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
            "secret_exposed": False,
        },
    )
    if not paid:
        raise AssertionError("paid order fixture failed")
    return paid


def _transition(repository: SaaSRepository, company_id: str, user_id: str, order_id: str, status: str, allowed: set[str]) -> None:
    repository.update_domestic_billing_order_state(
        company_id=company_id,
        user_id=user_id,
        order_id=order_id,
        status=status,
        allowed_current_statuses=allowed,
        state_details={"test_transition": True},
        audit_action=f"billing.test.{status}",
        audit_summary="Billing maintenance test transition.",
    )


if __name__ == "__main__":
    raise SystemExit(main())
