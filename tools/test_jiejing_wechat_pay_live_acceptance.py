#!/usr/bin/env python3
"""Behavior test for the one-CNY owner-approved WeChat Pay acceptance order."""

from __future__ import annotations

import tempfile
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.billing_domestic import create_controlled_wechat_pay_acceptance_order
from jiejing_saas.repository import SaaSRepository


APPROVAL = "I_APPROVE_ONE_CNY_REAL_WECHAT_PAY_ORDER"


def main() -> int:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        repository = SaaSRepository(Path(temp_dir) / "saas.sqlite")
        repository.initialize()
        identity = repository.create_user_with_company(
            email="owner@example.test",
            password="Acceptance-test-2026",
            company_name="Acceptance Test Merchant",
        )
        provider_calls: list[dict] = []

        def fake_provider_create(*, order: dict) -> dict:
            provider_calls.append(order)
            return {
                "ok": True,
                "status": "payable_order_created",
                "code_url": "weixin://wxpay/bizpayurl?pr=acceptance-test",
                "calls_external_payment_api": True,
                "creates_payable_order": True,
                "triggers_real_charge": False,
                "secret_exposed": False,
            }

        blocked = create_controlled_wechat_pay_acceptance_order(
            repository,
            account_email="owner@example.test",
            approval_phrase="not-approved",
            idempotency_key="acceptance-20260713",
            provider_create=fake_provider_create,
        )
        if blocked.get("reason") != "real_payment_owner_approval_required" or provider_calls:
            return fail(f"missing approval must not create a provider order: {blocked}")

        first = create_controlled_wechat_pay_acceptance_order(
            repository,
            account_email="owner@example.test",
            approval_phrase=APPROVAL,
            idempotency_key="acceptance-20260713",
            provider_create=fake_provider_create,
        )
        second = create_controlled_wechat_pay_acceptance_order(
            repository,
            account_email="owner@example.test",
            approval_phrase=APPROVAL,
            idempotency_key="acceptance-20260713",
            provider_create=fake_provider_create,
        )
        if first.get("ok") is not True or first.get("amount_minor") != 100 or first.get("currency") != "CNY":
            return fail(f"approved acceptance order must be exactly one CNY: {first}")
        if first.get("order_id") != second.get("order_id") or len(provider_calls) != 1:
            return fail("duplicate acceptance execution must reuse the same payable order")

        stored = repository.get_domestic_billing_order(
            company_id=identity["company"]["company_id"],
            order_id=str(first["order_id"]),
        )
        order_payload = stored.get("order") if isinstance(stored, dict) and isinstance(stored.get("order"), dict) else {}
        if not stored or stored.get("amount_minor") != 100 or stored.get("status") != "pending_payment":
            return fail(f"acceptance order must be persisted before provider checkout: {stored}")
        if order_payload.get("display_name") != "捷境支付验收测试（1 元）":
            return fail(f"customer-facing acceptance description is incorrect: {order_payload}")
        if order_payload.get("live_acceptance_test") is not True:
            return fail("acceptance order must remain distinguishable from the public 99 CNY plan")
        if any(key in str(first).lower() for key in ("private_key", "api_v3", "certificate_pem")):
            return fail("acceptance response must not expose payment credentials")

    print("PASS jiejing_wechat_pay_live_acceptance")
    return 0


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
