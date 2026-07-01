#!/usr/bin/env python3
"""Regression for signed billing webhook entitlement persistence."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import shutil
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.billing_plan import build_billing_usage, evaluate_quota_action  # noqa: E402
from jiejing_saas.billing_webhook import handle_billing_webhook  # noqa: E402
from jiejing_saas.config import SaaSSettings  # noqa: E402
from jiejing_saas.repository import SaaSRepository  # noqa: E402


OUT = ROOT / "output" / "jiejing-billing-webhook-subscription-state-test"


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
            email="billing-webhook-state@example.com",
            password="local-test-password",
            company_name="Billing Webhook State Merchant",
        )
        company_id = fixture["company"]["company_id"]

        active_event = _stripe_subscription_event(
            event_id="evt_subscription_active",
            event_type="customer.subscription.updated",
            company_id=company_id,
            subscription_id="sub_state_unit",
            customer_id="cus_state_unit",
            status="active",
            price_id="price_operator_unit",
        )
        accepted = handle_billing_webhook(raw_body=active_event, headers=_stripe_headers(active_event))
        if accepted.get("ok") is not True:
            return fail(f"signed active webhook should verify: {accepted}")
        applied = repo.apply_billing_webhook_event(event=accepted["event"])
        if applied.get("status") != "applied":
            return fail(f"active webhook should apply to company subscription: {applied}")
        duplicate = repo.apply_billing_webhook_event(event=accepted["event"])
        if duplicate.get("status") != "applied_duplicate_ignored" or duplicate.get("duplicate_event") is not True:
            return fail(f"duplicate webhook should be idempotently ignored: {duplicate}")
        applied_audits = [
            item
            for item in repo.list_audit_logs(company_id=company_id, limit=20)
            if item.get("action_type") == "billing.webhook.applied"
        ]
        if len(applied_audits) != 1:
            return fail(f"duplicate webhook must not write a second entitlement audit: {applied_audits}")
        subscription = repo.get_billing_subscription(company_id=company_id)
        if not subscription or subscription.get("plan_key") != "operator" or subscription.get("entitlement_active") is not True:
            return fail(f"operator subscription should be active: {subscription}")
        usage = build_billing_usage(settings, repo, company_id=company_id)
        if usage.get("plan", {}).get("key") != "operator" or usage.get("subscription", {}).get("entitlement_active") is not True:
            return fail(f"billing usage should follow provider subscription: {usage}")

        failed_event = json.dumps(
            {
                "id": "evt_invoice_failed",
                "type": "invoice.payment_failed",
                "data": {"object": {"subscription": "sub_state_unit", "customer": "cus_state_unit"}},
            },
            separators=(",", ":"),
        ).encode("utf-8")
        failed = handle_billing_webhook(raw_body=failed_event, headers=_stripe_headers(failed_event))
        if failed.get("ok") is not True:
            return fail(f"signed failed-payment webhook should verify: {failed}")
        failed_applied = repo.apply_billing_webhook_event(event=failed["event"])
        if failed_applied.get("status") != "applied":
            return fail(f"failed-payment webhook should apply through existing provider ids: {failed_applied}")
        after_failure = repo.get_billing_subscription(company_id=company_id)
        if not after_failure or after_failure.get("plan_key") != "operator" or after_failure.get("entitlement_active") is not False:
            return fail(f"payment failure should keep plan but disable entitlement: {after_failure}")
        quota = evaluate_quota_action(settings, repo, company_id=company_id, action_unit="ai_ceo_task")
        if quota.get("allowed") is not False or quota.get("reason") != "billing_subscription_not_active":
            return fail(f"quota should hard-stop inactive paid subscription: {quota}")

        unsupported_fixture = repo.create_user_with_company(
            email="billing-webhook-unsupported@example.com",
            password="local-test-password",
            company_name="Billing Webhook Unsupported Merchant",
        )
        unsupported_company_id = unsupported_fixture["company"]["company_id"]
        unsupported_event = _stripe_subscription_event(
            event_id="evt_unsupported_customer_source",
            event_type="customer.source.updated",
            company_id=unsupported_company_id,
            subscription_id="sub_unsupported_unit",
            customer_id="cus_unsupported_unit",
            status="active",
            price_id="price_starter_unit",
        )
        unsupported = handle_billing_webhook(raw_body=unsupported_event, headers=_stripe_headers(unsupported_event))
        if unsupported.get("ok") is not True or unsupported.get("event", {}).get("supported_event") is not False:
            return fail(f"unsupported signed event should normalize without entitlement support: {unsupported}")
        unsupported_applied = repo.apply_billing_webhook_event(event=unsupported["event"])
        if unsupported_applied.get("status") != "accepted_unmapped_unsupported_billing_event":
            return fail(f"unsupported event must not grant entitlement: {unsupported_applied}")
        if repo.get_billing_subscription(company_id=unsupported_company_id):
            return fail("unsupported signed event should not create a subscription")

        missing_id_fixture = repo.create_user_with_company(
            email="billing-webhook-missing-id@example.com",
            password="local-test-password",
            company_name="Billing Webhook Missing Id Merchant",
        )
        missing_id_company_id = missing_id_fixture["company"]["company_id"]
        missing_id_event = _stripe_subscription_event(
            event_id="",
            event_type="customer.subscription.updated",
            company_id=missing_id_company_id,
            subscription_id="sub_missing_id_unit",
            customer_id="cus_missing_id_unit",
            status="active",
            price_id="price_starter_unit",
        )
        missing_id = handle_billing_webhook(raw_body=missing_id_event, headers=_stripe_headers(missing_id_event))
        if missing_id.get("ok") is not True or missing_id.get("event", {}).get("event_id_present") is not False:
            return fail(f"missing-id signed event should stay sanitized: {missing_id}")
        missing_id_applied = repo.apply_billing_webhook_event(event=missing_id["event"])
        if missing_id_applied.get("status") != "accepted_unmapped_billing_event_id_missing":
            return fail(f"missing event_id must not grant entitlement: {missing_id_applied}")
        if repo.get_billing_subscription(company_id=missing_id_company_id):
            return fail("event without provider event_id should not create a subscription")

        serialized = json.dumps(
            {
                "accepted": accepted,
                "applied": applied,
                "duplicate": duplicate,
                "unsupported": unsupported_applied,
                "missing_id": missing_id_applied,
                "usage": usage,
                "failed": failed,
                "quota": quota,
                "audits": repo.list_audit_logs(company_id=company_id, limit=10),
            },
            ensure_ascii=False,
        )
        for forbidden in ("sk_test_state", "whsec_state", "raw_body", "payment_method", "card", "access_token", "refresh_token"):
            if forbidden in serialized:
                return fail(f"billing state output leaked forbidden value: {forbidden}")
        print("PASS jiejing_billing_webhook_subscription_state")
        return 0
    finally:
        _restore_env(previous)


def _set_env() -> dict[str, str | None]:
    keys = [
        "JIEJING_SAAS_ENV",
        "JIEJING_BILLING_PROVIDER",
        "JIEJING_STRIPE_SECRET_KEY",
        "JIEJING_STRIPE_WEBHOOK_SECRET",
        "JIEJING_BILLING_WEBHOOK_URL",
        "JIEJING_BILLING_PLANS_PUBLISHED",
        "JIEJING_QUOTA_ENFORCEMENT_ENABLED",
        "JIEJING_STRIPE_PRICE_STARTER_ID",
        "JIEJING_STRIPE_PRICE_OPERATOR_ID",
        "JIEJING_STRIPE_PRICE_TEAM_ID",
    ]
    previous = {key: os.environ.get(key) for key in keys}
    os.environ.update(
        {
            "JIEJING_SAAS_ENV": "staging",
            "JIEJING_BILLING_PROVIDER": "stripe",
            "JIEJING_STRIPE_SECRET_KEY": "sk_test_state",
            "JIEJING_STRIPE_WEBHOOK_SECRET": "whsec_state",
            "JIEJING_BILLING_WEBHOOK_URL": "https://app.example.test/billing/webhook",
            "JIEJING_BILLING_PLANS_PUBLISHED": "1",
            "JIEJING_QUOTA_ENFORCEMENT_ENABLED": "1",
            "JIEJING_STRIPE_PRICE_STARTER_ID": "price_starter_unit",
            "JIEJING_STRIPE_PRICE_OPERATOR_ID": "price_operator_unit",
            "JIEJING_STRIPE_PRICE_TEAM_ID": "price_team_unit",
        }
    )
    return previous


def _stripe_subscription_event(
    *,
    event_id: str,
    event_type: str,
    company_id: str,
    subscription_id: str,
    customer_id: str,
    status: str,
    price_id: str,
) -> bytes:
    return json.dumps(
        {
            "id": event_id,
            "type": event_type,
            "data": {
                "object": {
                    "id": subscription_id,
                    "customer": customer_id,
                    "status": status,
                    "metadata": {"company_id": company_id},
                    "items": {"data": [{"price": {"id": price_id}}]},
                }
            },
        },
        separators=(",", ":"),
    ).encode("utf-8")


def _stripe_headers(body: bytes) -> dict[str, str]:
    timestamp = str(int(time.time()))
    sig = hmac.new(b"whsec_state", timestamp.encode("utf-8") + b"." + body, hashlib.sha256).hexdigest()
    return {"Stripe-Signature": f"t={timestamp},v1={sig}"}


def _restore_env(previous: dict[str, str | None]) -> None:
    for key, value in previous.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


if __name__ == "__main__":
    raise SystemExit(main())
