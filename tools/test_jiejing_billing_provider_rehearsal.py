#!/usr/bin/env python3
"""Regression for no-charge provider payment rehearsal."""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.billing_plan import build_billing_plan  # noqa: E402
from jiejing_saas.billing_provider_rehearsal import run_billing_provider_rehearsal  # noqa: E402
from jiejing_saas.config import SaaSSettings  # noqa: E402
from jiejing_saas.repository import SaaSRepository  # noqa: E402


OUT = ROOT / "output" / "jiejing-billing-provider-rehearsal-test"


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True, exist_ok=True)
    previous = _set_env()
    try:
        settings = SaaSSettings.from_env(
            db_path=OUT / "saas.sqlite",
            runtime_db_path=OUT / "runtime.sqlite",
            output_root=OUT,
            host="127.0.0.1",
            port=8788,
        )
        repo = SaaSRepository(OUT / "saas.sqlite")
        fixture = repo.create_user_with_company(
            email="billing-provider-rehearsal@example.com",
            password="local-test-password",
            company_name="Billing Provider Rehearsal Merchant",
        )
        company_id = fixture["company"]["company_id"]
        user_id = fixture["user"]["user_id"]

        plan = build_billing_plan(settings, repo)
        rehearsal_summary = plan.get("billing_test_rehearsal_summary") if isinstance(plan.get("billing_test_rehearsal_summary"), dict) else {}
        steps = {item.get("key"): item for item in rehearsal_summary.get("steps", []) if isinstance(item, dict)}
        if rehearsal_summary.get("ready") is not True:
            return fail(f"test billing rehearsal summary should be ready: {rehearsal_summary}")
        if "test_provider_order_query_or_signed_webhook" not in steps:
            return fail(f"rehearsal summary should include backend proof step: {sorted(steps)}")
        if steps["test_provider_order_query_or_signed_webhook"].get("status") != "ready":
            return fail(f"backend proof step should be ready: {steps['test_provider_order_query_or_signed_webhook']}")

        expected_quota = {
            "activate": False,
            "invoice_paid": False,
            "payment_failed": True,
            "cancel": True,
        }
        results = {}
        for action, expected_blocked in expected_quota.items():
            result = run_billing_provider_rehearsal(
                settings,
                repo,
                company_id=company_id,
                user_id=user_id,
                plan_key="starter",
                action=action,
            )
            results[action] = result
            if result.get("ok") is not True or result.get("status") != "billing_provider_rehearsal_completed":
                return fail(f"{action} rehearsal should complete: {result}")
            if result.get("ready_for_paid_launch") is not False or result.get("public_charging_allowed") is not False:
                return fail(f"{action} rehearsal must not mark paid launch ready: {result}")
            for flag in ("creates_real_checkout_session", "calls_external_payment_api", "triggers_real_charge", "charge_now_allowed", "frontend_gets_payment_secret", "secret_exposed"):
                if result.get(flag) is not False:
                    return fail(f"{action} rehearsal should keep {flag}=false: {result.get(flag)}")
            checkout = result.get("checkout") if isinstance(result.get("checkout"), dict) else {}
            if checkout.get("session_id_present") is not True or checkout.get("session_url_returned") is not False:
                return fail(f"{action} checkout proof should be sanitized: {checkout}")
            proof = result.get("provider_proof") if isinstance(result.get("provider_proof"), dict) else {}
            if proof.get("signed_webhook_or_order_query_verified") is not True or proof.get("frontend_submitted_entitlement") is not False:
                return fail(f"{action} provider proof should be backend-owned: {proof}")
            quota = result.get("quota_guardrail") if isinstance(result.get("quota_guardrail"), dict) else {}
            if quota.get("blocked") is not expected_blocked or quota.get("ok") is not True:
                return fail(f"{action} quota expectation failed: {quota}")

        api_server = (ROOT / "jiejing_saas" / "api_server.py").read_text(encoding="utf-8")
        if "billing/provider-rehearsal" not in api_server or "run_billing_provider_rehearsal" not in api_server:
            return fail("api server should expose the billing provider rehearsal endpoint")
        serialized = json.dumps(results, ensure_ascii=False)
        for forbidden in ("sk_test", "whsec", "access_token", "refresh_token", "payment_method", "card", "authorization: bearer"):
            if forbidden in serialized.lower():
                return fail(f"billing provider rehearsal output leaked forbidden marker: {forbidden}")
        if not any(item.get("action_type") == "billing.provider_rehearsal.completed" for item in repo.list_audit_logs(company_id=company_id, limit=20)):
            return fail("billing provider rehearsal should write an audit record")
        print("PASS jiejing_billing_provider_rehearsal")
        return 0
    finally:
        _restore_env(previous)


def _set_env() -> dict[str, str | None]:
    keys = [
        "JIEJING_SAAS_ENV",
        "JIEJING_BILLING_PROVIDER",
        "JIEJING_BILLING_PLANS_PUBLISHED",
        "JIEJING_QUOTA_ENFORCEMENT_ENABLED",
        "JIEJING_BILLING_SUCCESS_URL",
        "JIEJING_BILLING_CANCEL_URL",
        "JIEJING_BILLING_PORTAL_RETURN_URL",
        "JIEJING_DEFAULT_PLAN_KEY",
    ]
    previous = {key: os.environ.get(key) for key in keys}
    os.environ.update(
        {
            "JIEJING_SAAS_ENV": "staging",
            "JIEJING_BILLING_PROVIDER": "stripe_test_mock",
            "JIEJING_BILLING_PLANS_PUBLISHED": "1",
            "JIEJING_QUOTA_ENFORCEMENT_ENABLED": "1",
            "JIEJING_BILLING_SUCCESS_URL": "https://app.example.test/billing/success",
            "JIEJING_BILLING_CANCEL_URL": "https://app.example.test/billing/cancel",
            "JIEJING_BILLING_PORTAL_RETURN_URL": "https://app.example.test/settings/billing",
            "JIEJING_DEFAULT_PLAN_KEY": "starter",
        }
    )
    return previous


def _restore_env(previous: dict[str, str | None]) -> None:
    for key, value in previous.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


if __name__ == "__main__":
    raise SystemExit(main())
