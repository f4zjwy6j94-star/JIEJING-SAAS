#!/usr/bin/env python3
"""Behavior test for the sanitized WeChat Pay acceptance verifier."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.repository import SaaSRepository


def main() -> int:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        db_path = Path(temp_dir) / "saas.sqlite"
        repository = SaaSRepository(db_path)
        repository.initialize()
        identity = repository.create_user_with_company(
            email="owner@example.test",
            password="Acceptance-test-2026",
            company_name="Acceptance Test Merchant",
        )
        company_id = identity["company"]["company_id"]
        user_id = identity["user"]["user_id"]
        order_id = "JJLIVE-VERIFY-TEST"
        repository.create_domestic_billing_order_record(
            order_id=order_id,
            company_id=company_id,
            user_id=user_id,
            provider="wechat_pay_native",
            plan_key="starter",
            amount_minor=100,
            currency="CNY",
            duration_days=30,
            status="pending_payment",
            idempotency_key_hash="a" * 64,
            order={"display_name": "Acceptance test", "live_acceptance_test": True},
        )
        repository.mark_domestic_billing_order_paid(
            company_id=company_id,
            order_id=order_id,
            provider_order_id="wx-transaction-test",
            paid_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            payment={
                "provider_transaction_present": True,
                "amount_minor": 100,
                "currency": "CNY",
                "signature_verified": True,
                "verification_source": "signed_callback",
                "appid_verified": True,
                "mchid_verified": True,
                "amount_verified": True,
            },
        )
        repository.apply_billing_webhook_event(
            event={
                "provider": "wechat_pay_native",
                "event_id": "wx-transaction-test",
                "event_type": "payment_succeeded",
                "supported_event": True,
                "company_id": company_id,
                "provider_customer_id": "merchant-test",
                "provider_subscription_id": order_id,
                "provider_plan_id": "wechat_native_starter_100_30d",
                "plan_key": "starter",
                "subscription_status": "active",
                "duration_days": 30,
                "active_until": (datetime.now(timezone.utc) + timedelta(days=30)).replace(microsecond=0).isoformat(),
                "quota_recalculation_required": True,
                "raw_payload_persisted": False,
                "raw_signature_persisted": False,
                "secret_exposed": False,
            }
        )
        env = dict(os.environ)
        env.update(
            {
                "JIEJING_SAAS_DB_PATH": str(db_path),
                "JIEJING_RUNTIME_DB_PATH": str(Path(temp_dir) / "runtime.sqlite"),
                "JIEJING_OUTPUT_ROOT": str(Path(temp_dir) / "output"),
                "JIEJING_DATABASE_URL": "",
                "JIEJING_BILLING_PROVIDER": "stripe_test_mock",
                "JIEJING_QUOTA_ENFORCEMENT_ENABLED": "true",
            }
        )
        completed = subprocess.run(
            [
                sys.executable,
                "tools/jiejing_wechat_pay_acceptance_verify.py",
                "--account-email",
                "owner@example.test",
                "--order-id",
                order_id,
            ],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            return fail(f"verifier failed: {completed.stdout} {completed.stderr}")
        result = json.loads(completed.stdout)
        if result.get("ok") is not True or result.get("order", {}).get("status") != "paid":
            return fail(f"paid order was not verified: {result}")
        if result.get("payment_verification", {}).get("signature_verified") is not True:
            return fail(f"signed callback proof missing: {result}")
        if result.get("subscription", {}).get("entitlement_active") is not True:
            return fail(f"entitlement was not verified: {result}")
        if result.get("secret_exposed") is not False or "wx-transaction-test" in completed.stdout:
            return fail("verifier exposed a provider transaction identifier")

    print("PASS jiejing_wechat_pay_acceptance_verify")
    return 0


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
