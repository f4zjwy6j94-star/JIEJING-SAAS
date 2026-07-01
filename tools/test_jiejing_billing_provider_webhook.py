#!/usr/bin/env python3
"""Regression for signed Stripe/Paddle billing webhook boundaries."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.billing_webhook import build_billing_provider_contract, handle_billing_webhook  # noqa: E402


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    previous = _set_env()
    try:
        contract = build_billing_provider_contract()
        if contract.get("paid_provider_ready") is not True:
            return fail(f"stripe contract should be ready with API key, webhook URL and plan IDs: {contract.get('blockers')}")
        for expected_event in {
            "checkout.session.completed",
            "customer.subscription.updated",
            "invoice.paid",
            "invoice.payment_failed",
            "charge.refunded",
            "charge.dispute.created",
        }:
            if expected_event not in contract.get("webhook_event_types", []):
                return fail(f"stripe webhook contract missing event: {expected_event}")
        body = json.dumps(
            {
                "id": "evt_unit",
                "type": "customer.subscription.updated",
                "data": {
                    "object": {
                        "id": "sub_unit",
                        "customer": "cus_unit",
                        "status": "active",
                        "items": {"data": [{"price": {"id": "price_starter_unit"}}]},
                    }
                },
            },
            separators=(",", ":"),
        ).encode("utf-8")
        timestamp = str(int(time.time()))
        sig = hmac.new(b"whsec_unit", timestamp.encode("utf-8") + b"." + body, hashlib.sha256).hexdigest()
        result = handle_billing_webhook(raw_body=body, headers={"Stripe-Signature": f"t={timestamp},v1={sig}"})
        event = result.get("event") if isinstance(result.get("event"), dict) else {}
        if result.get("ok") is not True or event.get("quota_recalculation_required") is not True:
            return fail(f"stripe webhook should verify and require quota recalculation: {result}")
        serialized = json.dumps(result, ensure_ascii=False)
        for forbidden in ("sk_test_unit", "whsec_unit", "payment_method", "raw_body"):
            if forbidden in serialized:
                return fail(f"webhook output leaked forbidden value: {forbidden}")
        bad = handle_billing_webhook(raw_body=body, headers={"Stripe-Signature": f"t={timestamp},v1=bad"})
        if bad.get("ok") is not False or bad.get("status") != "invalid_signature":
            return fail("invalid stripe signature should be blocked")
        paid_body = json.dumps(
            {
                "id": "evt_invoice_paid",
                "type": "invoice.paid",
                "data": {
                    "object": {
                        "subscription": "sub_unit",
                        "customer": "cus_unit",
                        "status": "paid",
                        "items": {"data": [{"price": {"id": "price_starter_unit"}}]},
                    }
                },
            },
            separators=(",", ":"),
        ).encode("utf-8")
        paid_timestamp = str(int(time.time()))
        paid_sig = hmac.new(b"whsec_unit", paid_timestamp.encode("utf-8") + b"." + paid_body, hashlib.sha256).hexdigest()
        paid = handle_billing_webhook(raw_body=paid_body, headers={"Stripe-Signature": f"t={paid_timestamp},v1={paid_sig}"})
        if paid.get("ok") is not True or paid.get("event", {}).get("quota_recalculation_required") is not True:
            return fail(f"invoice.paid should verify and trigger quota recalculation: {paid}")

        _restore_env(previous)
        previous = _set_paddle_env()
        paddle_body = json.dumps(
            {
                "event_id": "evt_paddle_unit",
                "event_type": "subscription.updated",
                "data": {"id": "sub_paddle", "customer_id": "ctm_unit", "status": "active", "items": [{"price": {"id": "pri_team_unit"}}]},
            },
            separators=(",", ":"),
        ).encode("utf-8")
        timestamp = str(int(time.time()))
        paddle_sig = hmac.new(b"pdl_whsec_unit", timestamp.encode("utf-8") + b":" + paddle_body, hashlib.sha256).hexdigest()
        paddle = handle_billing_webhook(raw_body=paddle_body, headers={"Paddle-Signature": f"ts={timestamp};h1={paddle_sig}"})
        if paddle.get("ok") is not True or paddle.get("event", {}).get("provider_plan_id_present") is not True:
            return fail(f"paddle webhook should verify and normalize subscription event: {paddle}")

        _restore_env(previous)
        previous = _set_lemon_squeezy_env()
        lemon_body = json.dumps(
            {
                "meta": {"event_name": "subscription_updated"},
                "data": {
                    "id": "sub_lemon",
                    "type": "subscriptions",
                    "attributes": {
                        "status": "active",
                        "customer_id": 123,
                        "variant_id": 456,
                    },
                },
            },
            separators=(",", ":"),
        ).encode("utf-8")
        lemon_sig = hmac.new(b"ls_whsec_unit", lemon_body, hashlib.sha256).hexdigest()
        lemon = handle_billing_webhook(raw_body=lemon_body, headers={"X-Signature": lemon_sig})
        if lemon.get("ok") is not True or lemon.get("event", {}).get("provider_plan_id_present") is not True:
            return fail(f"lemon squeezy webhook should verify and normalize subscription event: {lemon}")
        lemon_serialized = json.dumps(lemon, ensure_ascii=False)
        for forbidden in ("ls_api_unit", "ls_whsec_unit"):
            if forbidden in lemon_serialized:
                return fail(f"lemon squeezy webhook output leaked forbidden value: {forbidden}")
        print("PASS jiejing_billing_provider_webhook")
        return 0
    finally:
        _restore_env(previous)


def _set_env() -> dict[str, str | None]:
    keys = [
        "JIEJING_BILLING_PROVIDER",
        "JIEJING_STRIPE_SECRET_KEY",
        "JIEJING_STRIPE_WEBHOOK_SECRET",
        "JIEJING_BILLING_WEBHOOK_URL",
        "JIEJING_STRIPE_PRICE_STARTER_ID",
        "JIEJING_STRIPE_PRICE_OPERATOR_ID",
        "JIEJING_STRIPE_PRICE_TEAM_ID",
    ]
    previous = {key: os.environ.get(key) for key in keys}
    os.environ.update(
        {
            "JIEJING_BILLING_PROVIDER": "stripe",
            "JIEJING_STRIPE_SECRET_KEY": "sk_test_unit",
            "JIEJING_STRIPE_WEBHOOK_SECRET": "whsec_unit",
            "JIEJING_BILLING_WEBHOOK_URL": "https://app.example.test/billing/webhook",
            "JIEJING_STRIPE_PRICE_STARTER_ID": "price_starter_unit",
            "JIEJING_STRIPE_PRICE_OPERATOR_ID": "price_operator_unit",
            "JIEJING_STRIPE_PRICE_TEAM_ID": "price_team_unit",
        }
    )
    return previous


def _set_paddle_env() -> dict[str, str | None]:
    keys = [
        "JIEJING_BILLING_PROVIDER",
        "JIEJING_PADDLE_API_KEY",
        "JIEJING_PADDLE_WEBHOOK_SECRET",
        "JIEJING_BILLING_WEBHOOK_URL",
        "JIEJING_PADDLE_PRICE_STARTER_ID",
        "JIEJING_PADDLE_PRICE_OPERATOR_ID",
        "JIEJING_PADDLE_PRICE_TEAM_ID",
    ]
    previous = {key: os.environ.get(key) for key in keys}
    os.environ.update(
        {
            "JIEJING_BILLING_PROVIDER": "paddle",
            "JIEJING_PADDLE_API_KEY": "pdl_test_unit",
            "JIEJING_PADDLE_WEBHOOK_SECRET": "pdl_whsec_unit",
            "JIEJING_BILLING_WEBHOOK_URL": "https://app.example.test/billing/webhook",
            "JIEJING_PADDLE_PRICE_STARTER_ID": "pri_starter_unit",
            "JIEJING_PADDLE_PRICE_OPERATOR_ID": "pri_operator_unit",
            "JIEJING_PADDLE_PRICE_TEAM_ID": "pri_team_unit",
        }
    )
    return previous


def _set_lemon_squeezy_env() -> dict[str, str | None]:
    keys = [
        "JIEJING_BILLING_PROVIDER",
        "JIEJING_LEMON_SQUEEZY_API_KEY",
        "JIEJING_LEMON_SQUEEZY_WEBHOOK_SECRET",
        "JIEJING_BILLING_WEBHOOK_URL",
        "JIEJING_LEMON_SQUEEZY_VARIANT_STARTER_ID",
        "JIEJING_LEMON_SQUEEZY_VARIANT_OPERATOR_ID",
        "JIEJING_LEMON_SQUEEZY_VARIANT_TEAM_ID",
    ]
    previous = {key: os.environ.get(key) for key in keys}
    os.environ.update(
        {
            "JIEJING_BILLING_PROVIDER": "lemon_squeezy",
            "JIEJING_LEMON_SQUEEZY_API_KEY": "ls_api_unit",
            "JIEJING_LEMON_SQUEEZY_WEBHOOK_SECRET": "ls_whsec_unit",
            "JIEJING_BILLING_WEBHOOK_URL": "https://app.example.test/billing/webhook",
            "JIEJING_LEMON_SQUEEZY_VARIANT_STARTER_ID": "456",
            "JIEJING_LEMON_SQUEEZY_VARIANT_OPERATOR_ID": "789",
            "JIEJING_LEMON_SQUEEZY_VARIANT_TEAM_ID": "999",
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
