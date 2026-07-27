#!/usr/bin/env python3
"""Failure-recovery and concurrency tests for domestic WeChat Pay entitlement."""

from __future__ import annotations

import shutil
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.billing_domestic import query_and_reconcile_domestic_billing_order  # noqa: E402
from jiejing_saas.billing_wechat_pay import reconcile_wechat_pay_order_query  # noqa: E402
from jiejing_saas.repository import SaaSRepository  # noqa: E402


OUT = ROOT / "output" / "jiejing-wechat-pay-recovery-test"
APP_ID = "wx-recovery-test-app"
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
        email="wechat-recovery@example.test",
        password="Wechat-recovery-test-2026",
        company_name="WeChat Recovery Test",
    )
    company_id = str(account["company"]["company_id"])
    user_id = str(account["user"]["user_id"])

    recovery_order_id = "domestic_paid_without_entitlement"
    now = datetime.now(timezone.utc).replace(microsecond=0)
    active_from = now.isoformat()
    active_until = (now + timedelta(days=30)).isoformat()
    repository.create_domestic_billing_order_record(
        order_id=recovery_order_id,
        company_id=company_id,
        user_id=user_id,
        provider="wechat_pay_native",
        plan_key="starter",
        amount_minor=9900,
        currency="CNY",
        duration_days=30,
        status="pending_payment",
        idempotency_key_hash="d" * 64,
        order={"provider_mode": "crash_recovery_test", "provider_order_created": True},
    )
    repository.mark_domestic_billing_order_paid(
        company_id=company_id,
        order_id=recovery_order_id,
        provider_order_id="wx-recovery-transaction-1",
        paid_at=now.isoformat(),
        payment={
            "provider_transaction_present": True,
            "amount_minor": 9900,
            "currency": "CNY",
            "signature_verified": True,
            "verification_source": "signed_callback",
            "appid_verified": True,
            "mchid_verified": True,
            "amount_verified": True,
            "entitlement_active_from": active_from,
            "entitlement_active_until": active_until,
        },
    )
    if repository.get_billing_subscription(company_id=company_id):
        return fail("the crash fixture must start with a paid order and no entitlement")

    provider_called = False

    def forbidden_provider_query(**_: object) -> dict[str, object]:
        nonlocal provider_called
        provider_called = True
        raise AssertionError("paid-order recovery must not call the external provider")

    recovered = query_and_reconcile_domestic_billing_order(
        repository,
        company_id=company_id,
        order_id=recovery_order_id,
        provider_query=forbidden_provider_query,
        expected_appid=APP_ID,
        expected_mchid=MCH_ID,
    )
    if provider_called:
        return fail("paid-order recovery called the external provider")
    if recovered.get("ok") is not True or recovered.get("entitlement_recovered") is not True:
        return fail(f"paid order should self-heal its missing entitlement: {recovered}")
    recovered_subscription = repository.get_billing_subscription(company_id=company_id)
    if (
        not recovered_subscription
        or recovered_subscription.get("entitlement_active") is not True
        or recovered_subscription.get("provider_subscription_id") != recovery_order_id
        or recovered_subscription.get("subscription", {}).get("active_until") != active_until
    ):
        return fail(f"recovered entitlement is incomplete: {recovered_subscription}")

    repeated = query_and_reconcile_domestic_billing_order(
        repository,
        company_id=company_id,
        order_id=recovery_order_id,
        provider_query=forbidden_provider_query,
        expected_appid=APP_ID,
        expected_mchid=MCH_ID,
    )
    if repeated.get("ok") is not True or repeated.get("entitlement_recovered") is not False:
        return fail(f"recovery must be idempotent: {repeated}")

    legacy_account = repository.create_user_with_company(
        email="wechat-legacy-recovery@example.test",
        password="Wechat-legacy-recovery-2026",
        company_name="WeChat Legacy Recovery Test",
    )
    legacy_company_id = str(legacy_account["company"]["company_id"])
    legacy_user_id = str(legacy_account["user"]["user_id"])
    legacy_order_id = "domestic_legacy_paid_without_window"
    legacy_active_until = (now + timedelta(days=30)).isoformat()
    repository.create_domestic_billing_order_record(
        order_id=legacy_order_id,
        company_id=legacy_company_id,
        user_id=legacy_user_id,
        provider="wechat_pay_native",
        plan_key="starter",
        amount_minor=9900,
        currency="CNY",
        duration_days=30,
        status="pending_payment",
        idempotency_key_hash="a" * 64,
        order={"provider_mode": "legacy_recovery_test", "provider_order_created": True},
    )
    repository.mark_domestic_billing_order_paid(
        company_id=legacy_company_id,
        order_id=legacy_order_id,
        provider_order_id="wx-legacy-recovery-transaction-1",
        paid_at=now.isoformat(),
        payment={
            "provider_transaction_present": True,
            "amount_minor": 9900,
            "currency": "CNY",
            "signature_verified": True,
            "verification_source": "signed_callback",
            "appid_verified": True,
            "mchid_verified": True,
            "amount_verified": True,
        },
    )
    legacy_recovered = query_and_reconcile_domestic_billing_order(
        repository,
        company_id=legacy_company_id,
        order_id=legacy_order_id,
        provider_query=forbidden_provider_query,
        expected_appid=APP_ID,
        expected_mchid=MCH_ID,
    )
    if legacy_recovered.get("ok") is not True or legacy_recovered.get("entitlement_recovered") is not True:
        return fail(f"verified legacy paid order should recover from paid_at and duration: {legacy_recovered}")
    legacy_subscription = repository.get_billing_subscription(company_id=legacy_company_id)
    if (
        not legacy_subscription
        or legacy_subscription.get("entitlement_active") is not True
        or legacy_subscription.get("subscription", {}).get("active_until") != legacy_active_until
    ):
        return fail(f"legacy fallback entitlement window is incorrect: {legacy_subscription}")

    tampered_order_id = "domestic_legacy_paid_tampered_amount"
    repository.create_domestic_billing_order_record(
        order_id=tampered_order_id,
        company_id=legacy_company_id,
        user_id=legacy_user_id,
        provider="wechat_pay_native",
        plan_key="starter",
        amount_minor=9900,
        currency="CNY",
        duration_days=30,
        status="pending_payment",
        idempotency_key_hash="b" * 64,
        order={"provider_mode": "legacy_tamper_test", "provider_order_created": True},
    )
    repository.mark_domestic_billing_order_paid(
        company_id=legacy_company_id,
        order_id=tampered_order_id,
        provider_order_id="wx-legacy-recovery-transaction-2",
        paid_at=now.isoformat(),
        payment={
            "provider_transaction_present": True,
            "amount_minor": 1,
            "currency": "CNY",
            "signature_verified": True,
            "verification_source": "signed_callback",
            "appid_verified": True,
            "mchid_verified": True,
            "amount_verified": True,
        },
    )
    tampered = query_and_reconcile_domestic_billing_order(
        repository,
        company_id=legacy_company_id,
        order_id=tampered_order_id,
        provider_query=forbidden_provider_query,
        expected_appid=APP_ID,
        expected_mchid=MCH_ID,
    )
    if tampered.get("reason") != "paid_order_entitlement_evidence_incomplete":
        return fail(f"tampered legacy payment evidence must fail closed: {tampered}")

    conflicting_order_id = "domestic_provider_transaction_conflict"
    repository.create_domestic_billing_order_record(
        order_id=conflicting_order_id,
        company_id=company_id,
        user_id=user_id,
        provider="wechat_pay_native",
        plan_key="starter",
        amount_minor=9900,
        currency="CNY",
        duration_days=30,
        status="pending_payment",
        idempotency_key_hash="c" * 64,
        order={"provider_mode": "transaction_conflict_test", "provider_order_created": True},
    )
    try:
        repository.mark_domestic_billing_order_paid(
            company_id=company_id,
            order_id=conflicting_order_id,
            provider_order_id="wx-recovery-transaction-1",
            paid_at=now.isoformat(),
            payment={"provider_transaction_present": True},
        )
    except ValueError:
        pass
    else:
        return fail("one provider transaction must not activate two Jiejing orders")

    lock_entered = threading.Event()
    lock_released = threading.Event()
    contender_entered = threading.Event()

    def lock_holder() -> None:
        with repository.domestic_billing_company_lock(company_id=company_id):
            lock_entered.set()
            lock_released.wait(timeout=2)

    def lock_contender() -> None:
        lock_entered.wait(timeout=2)
        with repository.domestic_billing_company_lock(company_id=company_id):
            contender_entered.set()

    holder = threading.Thread(target=lock_holder, daemon=True)
    contender = threading.Thread(target=lock_contender, daemon=True)
    holder.start()
    contender.start()
    if not lock_entered.wait(timeout=2):
        return fail("company entitlement lock was not acquired")
    time.sleep(0.1)
    if contender_entered.is_set():
        return fail("same-company entitlement operations were not serialized")
    lock_released.set()
    holder.join(timeout=2)
    contender.join(timeout=2)
    if not contender_entered.is_set():
        return fail("same-company entitlement lock did not release")

    concurrent_account = repository.create_user_with_company(
        email="wechat-concurrent-renewal@example.test",
        password="Wechat-concurrent-renewal-2026",
        company_name="WeChat Concurrent Renewal Test",
    )
    concurrent_company_id = str(concurrent_account["company"]["company_id"])
    concurrent_user_id = str(concurrent_account["user"]["user_id"])
    order_ids = ["domestic_concurrent_renewal_a", "domestic_concurrent_renewal_b"]
    for index, order_id in enumerate(order_ids):
        repository.create_domestic_billing_order_record(
            order_id=order_id,
            company_id=concurrent_company_id,
            user_id=concurrent_user_id,
            provider="wechat_pay_native",
            plan_key="starter",
            amount_minor=9900,
            currency="CNY",
            duration_days=30,
            status="pending_payment",
            idempotency_key_hash=("e" if index == 0 else "f") * 64,
            order={"provider_mode": "concurrent_renewal_test", "provider_order_created": True},
        )

    start = threading.Barrier(2)
    results: list[dict[str, object]] = []
    results_lock = threading.Lock()

    def reconcile(order_id: str, transaction_id: str) -> None:
        start.wait(timeout=2)
        result = reconcile_wechat_pay_order_query(
            repository,
            company_id=concurrent_company_id,
            order_id=order_id,
            provider_response={
                "appid": APP_ID,
                "mchid": MCH_ID,
                "out_trade_no": order_id,
                "transaction_id": transaction_id,
                "trade_type": "NATIVE",
                "trade_state": "SUCCESS",
                "success_time": now.isoformat(),
                "amount": {"total": 9900, "currency": "CNY"},
            },
            query_authenticated=True,
            expected_appid=APP_ID,
            expected_mchid=MCH_ID,
        )
        with results_lock:
            results.append(result)

    threads = [
        threading.Thread(target=reconcile, args=(order_ids[0], "wx-concurrent-transaction-a"), daemon=True),
        threading.Thread(target=reconcile, args=(order_ids[1], "wx-concurrent-transaction-b"), daemon=True),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)
    if len(results) != 2 or any(item.get("ok") is not True for item in results):
        return fail(f"both concurrent renewals must succeed once: {results}")
    subscription = repository.get_billing_subscription(company_id=concurrent_company_id)
    active_until_text = str(subscription.get("subscription", {}).get("active_until") or "") if subscription else ""
    try:
        concurrent_active_until = datetime.fromisoformat(active_until_text.replace("Z", "+00:00"))
    except ValueError:
        return fail(f"concurrent renewal active_until is invalid: {subscription}")
    if concurrent_active_until < datetime.now(timezone.utc) + timedelta(days=59):
        return fail(f"concurrent renewals lost paid entitlement time: {subscription}")

    print("PASS jiejing_wechat_pay_recovery")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
