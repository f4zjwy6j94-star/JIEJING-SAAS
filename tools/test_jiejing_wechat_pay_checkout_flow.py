#!/usr/bin/env python3
"""Checkout orchestration tests with a fully injected no-network provider."""

from __future__ import annotations

import shutil
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.billing_domestic import (  # noqa: E402
    create_domestic_billing_order,
    open_domestic_billing_checkout,
    query_and_reconcile_domestic_billing_order,
)
from jiejing_saas.config import SaaSSettings  # noqa: E402
from jiejing_saas.repository import SaaSRepository  # noqa: E402


OUT = ROOT / "output" / "jiejing-wechat-pay-checkout-flow-test"


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
    owner = repository.create_user_with_company(
        email="wechat-flow-owner@jiejing-shop.cn",
        password="WeChat-flow-owner-2026",
        company_name="WeChat Flow Owner",
    )
    other = repository.create_user_with_company(
        email="wechat-flow-other@example.test",
        password="WeChat-flow-other-2026",
        company_name="WeChat Flow Other",
    )
    concurrent_owner = repository.create_user_with_company(
        email="wechat-flow-concurrent@example.test",
        password="WeChat-flow-concurrent-2026",
        company_name="WeChat Flow Concurrent",
    )
    company_id = str(owner["company"]["company_id"])
    user_id = str(owner["user"]["user_id"])
    other_company_id = str(other["company"]["company_id"])
    concurrent_company_id = str(concurrent_owner["company"]["company_id"])
    concurrent_user_id = str(concurrent_owner["user"]["user_id"])

    rehearsal = create_domestic_billing_order(
        repository,
        company_id=company_id,
        user_id=user_id,
        provider="wechat_pay_native",
        plan_key="starter",
        idempotency_key="wechat-flow-rehearsal-1",
        rehearsal=True,
    )
    provider_calls: list[dict[str, Any]] = []

    def fake_create(*, order: dict[str, Any]) -> dict[str, Any]:
        provider_calls.append(order)
        return {
            "ok": True,
            "status": "payable_order_created",
            "order_id": order["order_id"],
            "code_url": "weixin://wxpay/bizpayurl?pr=flow-test-token",
            "amount_minor": order["amount_minor"],
            "currency": order["currency"],
            "calls_external_payment_api": True,
            "triggers_real_charge": False,
            "frontend_gets_payment_secret": False,
            "secret_exposed": False,
        }

    blocked_rehearsal = open_domestic_billing_checkout(
        repository,
        company_id=company_id,
        order_id=str(rehearsal["order_id"]),
        provider_create=fake_create,
    )
    if blocked_rehearsal.get("reason") != "domestic_real_checkout_not_enabled" or provider_calls:
        return fail(f"rehearsal orders must never reach the provider: {blocked_rehearsal}, calls={provider_calls}")

    live = create_domestic_billing_order(
        repository,
        company_id=company_id,
        user_id=user_id,
        provider="wechat_pay_native",
        plan_key="starter",
        idempotency_key="wechat-flow-live-1",
        rehearsal=False,
    )
    if live.get("ok") is not True or live.get("status") != "pending_payment":
        return fail(f"approved live flow should create a local pending order first: {live}")
    if live.get("calls_external_payment_api") is not False or provider_calls:
        return fail(f"local order persistence must happen before the provider call: {live}, calls={provider_calls}")

    other_tenant = open_domestic_billing_checkout(
        repository,
        company_id=other_company_id,
        order_id=str(live["order_id"]),
        provider_create=fake_create,
    )
    if other_tenant.get("reason") != "domestic_billing_order_not_found" or provider_calls:
        return fail(f"another tenant must not discover or activate the order: {other_tenant}")

    opened = open_domestic_billing_checkout(
        repository,
        company_id=company_id,
        order_id=str(live["order_id"]),
        provider_create=fake_create,
    )
    replayed = open_domestic_billing_checkout(
        repository,
        company_id=company_id,
        order_id=str(live["order_id"]),
        provider_create=fake_create,
    )
    if opened.get("ok") is not True or opened.get("code_url") != "weixin://wxpay/bizpayurl?pr=flow-test-token":
        return fail(f"provider-created QR should be returned to the owning merchant: {opened}")
    if replayed.get("duplicate_request") is not True or replayed.get("code_url") != opened.get("code_url"):
        return fail(f"duplicate checkout clicks should reuse the stored QR without another provider call: {replayed}")
    if len(provider_calls) != 1:
        return fail(f"idempotent checkout must call the provider once: calls={len(provider_calls)}")
    checkout_reliability = repository.platform_operations_overview().get("provider_reliability_analytics", {})
    payment_reliability = checkout_reliability.get("payment", {})
    if payment_reliability.get("request_count") != 1 or payment_reliability.get("success_count") != 1:
        return fail(f"external checkout call must be metered once without counting its replay: {payment_reliability}")

    failure_owner = repository.create_user_with_company(
        email="wechat-flow-failure@jiejing-shop.cn",
        password="WeChat-flow-failure-2026",
        company_name="WeChat Flow Failure",
    )
    failure_company_id = str(failure_owner["company"]["company_id"])
    failure_order = create_domestic_billing_order(
        repository,
        company_id=failure_company_id,
        user_id=str(failure_owner["user"]["user_id"]),
        provider="wechat_pay_native",
        plan_key="starter",
        idempotency_key="wechat-flow-provider-failure-1",
        rehearsal=False,
    )

    def fake_provider_failure(*, order: dict[str, Any]) -> dict[str, Any]:
        return {
            "ok": False,
            "status": "blocked",
            "reason": "payment_provider_request_failed",
            "http_status": 502,
            "calls_external_payment_api": True,
            "secret_exposed": False,
        }

    failed_checkout = open_domestic_billing_checkout(
        repository,
        company_id=failure_company_id,
        order_id=str(failure_order["order_id"]),
        provider_create=fake_provider_failure,
    )
    if failed_checkout.get("reason") != "payment_provider_request_failed":
        return fail(f"provider failure must preserve the merchant-safe failure contract: {failed_checkout}")
    failed_reliability = repository.platform_operations_overview().get("provider_reliability_analytics", {}).get("payment", {})
    if failed_reliability.get("request_count") != 2 or failed_reliability.get("failure_count") != 1:
        return fail(f"external payment failure must be metered without fabricating extra calls: {failed_reliability}")

    concurrent = create_domestic_billing_order(
        repository,
        company_id=concurrent_company_id,
        user_id=concurrent_user_id,
        provider="wechat_pay_native",
        plan_key="starter",
        idempotency_key="wechat-flow-concurrent-1",
        rehearsal=False,
    )
    concurrent_provider_calls: list[str] = []
    concurrent_results: list[dict[str, Any]] = []

    def slow_create(*, order: dict[str, Any]) -> dict[str, Any]:
        concurrent_provider_calls.append(str(order["order_id"]))
        time.sleep(0.15)
        return {
            "ok": True,
            "status": "payable_order_created",
            "order_id": order["order_id"],
            "code_url": "weixin://wxpay/bizpayurl?pr=concurrent-token",
            "amount_minor": order["amount_minor"],
            "currency": order["currency"],
            "calls_external_payment_api": True,
            "triggers_real_charge": False,
            "frontend_gets_payment_secret": False,
            "secret_exposed": False,
        }

    def open_concurrently() -> None:
        concurrent_results.append(
            open_domestic_billing_checkout(
                repository,
                company_id=concurrent_company_id,
                order_id=str(concurrent["order_id"]),
                provider_create=slow_create,
            )
        )

    threads = [threading.Thread(target=open_concurrently), threading.Thread(target=open_concurrently)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)
    if len(concurrent_provider_calls) != 1 or len(concurrent_results) != 2 or not all(item.get("ok") is True for item in concurrent_results):
        return fail(
            "concurrent checkout clicks must serialize around one provider call: "
            f"provider_calls={concurrent_provider_calls}, results={concurrent_results}"
        )

    lock_account = repository.create_user_with_company(
        email="wechat-flow-lock@example.test",
        password="WeChat-flow-lock-2026",
        company_name="WeChat Flow Lock",
    )
    lock_company_id = str(lock_account["company"]["company_id"])
    lock_user_id = str(lock_account["user"]["user_id"])
    lock_order = create_domestic_billing_order(
        repository,
        company_id=lock_company_id,
        user_id=lock_user_id,
        provider="wechat_pay_native",
        plan_key="starter",
        idempotency_key="wechat-flow-database-lock-1",
        rehearsal=False,
    )
    lock_contract_repository = _CheckoutLockContractRepository(repository)
    lock_opened = open_domestic_billing_checkout(
        lock_contract_repository,
        company_id=lock_company_id,
        order_id=str(lock_order["order_id"]),
        provider_create=fake_create,
    )
    if lock_opened.get("ok") is not True or lock_contract_repository.lock_entries != 1:
        return fail(f"payable QR creation must use the cross-instance company lock: {lock_opened}")

    stored = repository.get_domestic_billing_order(company_id=company_id, order_id=str(live["order_id"]))
    checkout = stored.get("order", {}).get("checkout", {}) if stored else {}
    if stored is None or stored.get("status") != "pending_payment" or checkout.get("code_url") != opened.get("code_url"):
        return fail(f"sanitized QR state should be tenant-scoped and recoverable: {stored}")
    if checkout.get("raw_provider_response_persisted") is not False or checkout.get("payment_secret_persisted") is not False:
        return fail(f"checkout persistence must not store raw provider material: {checkout}")

    query_calls: list[str] = []

    def fake_query(*, order_id: str) -> dict[str, Any]:
        query_calls.append(order_id)
        return {
            "ok": True,
            "status": "provider_response_verified",
            "provider_response": {
                "appid": "wx-test-app",
                "mchid": "1900000109",
                "out_trade_no": order_id,
                "trade_state": "NOTPAY",
            },
            "query_authenticated": True,
            "calls_external_payment_api": True,
            "frontend_gets_payment_secret": False,
            "secret_exposed": False,
        }

    queried = query_and_reconcile_domestic_billing_order(
        repository,
        company_id=company_id,
        order_id=str(live["order_id"]),
        provider_query=fake_query,
        expected_appid="wx-test-app",
        expected_mchid="1900000109",
    )
    if queried.get("ok") is not True or queried.get("status") != "pending_payment" or queried.get("provider_state") != "NOTPAY":
        return fail(f"NOTPAY query should stay pending without exposing raw provider data: {queried}")
    if "provider_response" in queried or query_calls != [str(live["order_id"])]:
        return fail(f"merchant query response must be sanitized and tenant scoped: {queried}, calls={query_calls}")

    def fake_closed_query(*, order_id: str) -> dict[str, Any]:
        return {
            "ok": True,
            "status": "provider_response_verified",
            "provider_response": {
                "appid": "wx-test-app",
                "mchid": "1900000109",
                "out_trade_no": order_id,
                "trade_state": "CLOSED",
            },
            "query_authenticated": True,
            "calls_external_payment_api": True,
            "secret_exposed": False,
        }

    closed_query = query_and_reconcile_domestic_billing_order(
        repository,
        company_id=company_id,
        order_id=str(live["order_id"]),
        provider_query=fake_closed_query,
        expected_appid="wx-test-app",
        expected_mchid="1900000109",
    )
    closed_order = repository.get_domestic_billing_order(company_id=company_id, order_id=str(live["order_id"]))
    closed_checkout = closed_order.get("order", {}).get("checkout", {}) if closed_order else {}
    if closed_query.get("status") != "closed" or closed_order.get("status") != "closed":
        return fail(f"authenticated CLOSED state must be persisted: {closed_query}, {closed_order}")
    if closed_checkout.get("code_url"):
        return fail(f"closed orders must not retain a payable QR URI: {closed_checkout}")

    terminal_replay = query_and_reconcile_domestic_billing_order(
        repository,
        company_id=company_id,
        order_id=str(live["order_id"]),
        provider_query=lambda **_: (_ for _ in ()).throw(AssertionError("terminal state must not query provider")),
    )
    if terminal_replay.get("status") != "closed" or terminal_replay.get("calls_external_payment_api") is not False:
        return fail(f"terminal order status must be replayed without another provider query: {terminal_replay}")

    print("PASS jiejing_wechat_pay_checkout_flow")
    return 0


class _CheckoutLockContractRepository:
    """Require checkout state reads and writes to occur inside the company lock."""

    def __init__(self, delegate: SaaSRepository) -> None:
        self._delegate = delegate
        self._lock_depth = 0
        self.lock_entries = 0

    @contextmanager
    def domestic_billing_company_lock(self, *, company_id: str) -> Iterator[None]:
        self.lock_entries += 1
        with self._delegate.domestic_billing_company_lock(company_id=company_id):
            self._lock_depth += 1
            try:
                yield
            finally:
                self._lock_depth -= 1

    def get_domestic_billing_order(self, **kwargs: object) -> dict[str, Any] | None:
        self._require_lock()
        return self._delegate.get_domestic_billing_order(**kwargs)

    def attach_domestic_billing_checkout(self, **kwargs: object) -> dict[str, Any] | None:
        self._require_lock()
        return self._delegate.attach_domestic_billing_checkout(**kwargs)

    def _require_lock(self) -> None:
        if self._lock_depth <= 0:
            raise AssertionError("domestic billing checkout access occurred outside the company lock")

    def __getattr__(self, name: str) -> object:
        return getattr(self._delegate, name)


if __name__ == "__main__":
    raise SystemExit(main())
