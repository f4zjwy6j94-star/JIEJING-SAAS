#!/usr/bin/env python3
"""Behavior test for tenant-scoped domestic billing orders.

The test creates no payable provider order and makes no network call. It proves
that JIEJING owns an idempotent, sanitized order record before any WeChat Pay
adapter is allowed to run.
"""

from __future__ import annotations

import json
import shutil
import sys
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.billing_domestic import create_domestic_billing_order  # noqa: E402
from jiejing_saas.config import SaaSSettings  # noqa: E402
from jiejing_saas.repository import SaaSRepository  # noqa: E402


OUT = ROOT / "output" / "jiejing-domestic-billing-order-test"


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
        email="domestic-order@example.test",
        password="Domestic-order-test-2026",
        company_name="Domestic Billing Order Test",
    )
    company_id = str(account["company"]["company_id"])
    user_id = str(account["user"]["user_id"])

    first = create_domestic_billing_order(
        repository,
        company_id=company_id,
        user_id=user_id,
        provider="wechat_pay_native",
        plan_key="starter",
        idempotency_key="merchant-checkout-click-1",
        rehearsal=True,
    )
    second = create_domestic_billing_order(
        repository,
        company_id=company_id,
        user_id=user_id,
        provider="wechat_pay_native",
        plan_key="starter",
        idempotency_key="merchant-checkout-click-1",
        rehearsal=True,
    )
    if first.get("ok") is not True or first.get("status") != "rehearsal_order_created":
        return fail(f"rehearsal order should be created without a provider call: {first}")
    if second.get("order_id") != first.get("order_id") or second.get("duplicate_request") is not True:
        return fail(f"same idempotency key should return the same order: {first}, {second}")
    order_id = str(first.get("order_id") or "")
    if not (6 <= len(order_id) <= 32) or any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-|*" for character in order_id):
        return fail(f"merchant order id must satisfy WeChat Pay's 6-32 character contract: {order_id!r}")
    if first.get("amount_minor") != 9900 or first.get("currency") != "CNY" or first.get("duration_days") != 30:
        return fail(f"starter mainland order should use the reviewed 99 CNY / 30 day terms: {first}")
    if first.get("provider_order_id") or first.get("code_url"):
        return fail(f"rehearsal order must not create a payable provider order or QR URL: {first}")
    if first.get("calls_external_payment_api") is not False or first.get("triggers_real_charge") is not False:
        return fail(f"rehearsal order must remain no-charge: {first}")
    if first.get("frontend_gets_payment_secret") is not False or first.get("secret_exposed") is not False:
        return fail(f"billing order must preserve backend-only secret handling: {first}")
    if first.get("idempotency_key") or first.get("idempotency_key_hash"):
        return fail(f"raw or hashed idempotency material must not be returned to the merchant: {first}")
    _assert_no_secret_material(first)

    stored = repository.get_domestic_billing_order(company_id=company_id, order_id=str(first["order_id"]))
    if not stored or stored.get("order_id") != first.get("order_id"):
        return fail(f"order should be retrievable only through its tenant-scoped repository interface: {stored}")
    if repository.get_domestic_billing_order(company_id="company_other", order_id=str(first["order_id"])) is not None:
        return fail("domestic order must not cross tenant boundaries")

    live_account = repository.create_user_with_company(
        email="domestic-live-order@example.test",
        password="Domestic-live-order-test-2026",
        company_name="Domestic Live Billing Order Test",
    )
    live_company_id = str(live_account["company"]["company_id"])
    live_user_id = str(live_account["user"]["user_id"])
    start = threading.Barrier(2)
    concurrent_results: list[dict[str, object]] = []
    results_lock = threading.Lock()

    def create_live_order(idempotency_key: str, plan_key: str) -> None:
        start.wait(timeout=2)
        result = create_domestic_billing_order(
            repository,
            company_id=live_company_id,
            user_id=live_user_id,
            provider="wechat_pay_native",
            plan_key=plan_key,
            idempotency_key=idempotency_key,
            rehearsal=False,
        )
        with results_lock:
            concurrent_results.append(result)

    threads = [
        threading.Thread(target=create_live_order, args=("merchant-tab-checkout-a", "starter"), daemon=True),
        threading.Thread(target=create_live_order, args=("merchant-tab-checkout-b", "operator"), daemon=True),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)
    if len(concurrent_results) != 2 or any(item.get("ok") is not True for item in concurrent_results):
        return fail(f"concurrent live checkout intents must both resolve safely: {concurrent_results}")
    concurrent_order_ids = {str(item.get("order_id") or "") for item in concurrent_results}
    if len(concurrent_order_ids) != 1:
        return fail(f"concurrent tabs must reuse one active pending order: {concurrent_results}")
    if sum(item.get("duplicate_request") is True for item in concurrent_results) != 1:
        return fail(f"one concurrent intent must be marked as a recovered duplicate: {concurrent_results}")
    pending_orders = [
        item
        for item in repository.list_domestic_billing_orders(company_id=live_company_id, limit=10)
        if item.get("status") == "pending_payment"
    ]
    if len(pending_orders) != 1:
        return fail(f"only one active pending subscription order may exist per tenant: {pending_orders}")

    locked_account = repository.create_user_with_company(
        email="domestic-database-lock@example.test",
        password="Domestic-database-lock-test-2026",
        company_name="Domestic Database Lock Test",
    )
    locked_company_id = str(locked_account["company"]["company_id"])
    locked_user_id = str(locked_account["user"]["user_id"])
    lock_contract_repository = _LockContractRepository(repository)
    locked_order = create_domestic_billing_order(
        lock_contract_repository,
        company_id=locked_company_id,
        user_id=locked_user_id,
        provider="wechat_pay_native",
        plan_key="starter",
        idempotency_key="merchant-database-lock-contract",
        rehearsal=False,
    )
    if locked_order.get("ok") is not True or lock_contract_repository.lock_entries != 1:
        return fail(f"live order creation must use the cross-instance company lock: {locked_order}")

    print("PASS jiejing_domestic_billing_orders")
    return 0


def _assert_no_secret_material(payload: object) -> None:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True).lower()
    forbidden = [
        "api_v3_key",
        "private_key",
        "certificate_pem",
        "bank_account",
        "identity_number",
        "client_secret",
        "refresh_token",
    ]
    leaked = [item for item in forbidden if item in text]
    if leaked:
        raise AssertionError(f"secret-like material leaked in domestic billing order: {leaked}")


class _LockContractRepository:
    """Require live order reads and writes to occur inside the repository lock."""

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

    def list_domestic_billing_orders(self, **kwargs: object) -> list[dict[str, object]]:
        self._require_lock()
        return self._delegate.list_domestic_billing_orders(**kwargs)

    def create_domestic_billing_order_record(self, **kwargs: object) -> dict[str, object]:
        self._require_lock()
        return self._delegate.create_domestic_billing_order_record(**kwargs)

    def _require_lock(self) -> None:
        if self._lock_depth <= 0:
            raise AssertionError("domestic billing order access occurred outside the company lock")

    def __getattr__(self, name: str) -> object:
        return getattr(self._delegate, name)


if __name__ == "__main__":
    raise SystemExit(main())
