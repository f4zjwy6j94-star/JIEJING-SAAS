#!/usr/bin/env python3
"""Regression for the private-beta manual payment order flow.

This test deliberately does not touch Stripe, Alipay APIs, eBay OAuth, or any
real payment rail. It proves that a personal-code beta payment can only become
entitlement after an internal admin confirms external receipt.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "jiejing-manual-beta-payment-test"
SAAS_DB = OUT / "saas.sqlite"
RUNTIME_DB = OUT / "runtime.sqlite"


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True, exist_ok=True)

    previous = {key: os.environ.get(key) for key in _env_keys()}
    os.environ.update(
        {
            "JIEJING_SAAS_ENV": "test",
            "JIEJING_BILLING_PROVIDER": "manual_beta",
            "JIEJING_BILLING_PLANS_PUBLISHED": "1",
            "JIEJING_QUOTA_ENFORCEMENT_ENABLED": "1",
            "JIEJING_INTERNAL_ADMIN_EMAILS": "manual-beta-admin@example.test",
            "JIEJING_EXPENSIVE_API_RATE_LIMIT_ENABLED": "0",
        }
    )
    port = 8798
    process = subprocess.Popen(
        [
            sys.executable,
            str(ROOT / "tools" / "jiejing_saas_backend_cli.py"),
            "serve",
            "--db",
            str(SAAS_DB),
            "--runtime-db",
            str(RUNTIME_DB),
            "--output-root",
            str(OUT),
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=str(ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        base_url = f"http://127.0.0.1:{port}"
        if _wait_for_health(base_url):
            return fail("backend did not become healthy")

        admin = _post_json(
            f"{base_url}/auth/register",
            {
                "email": "manual-beta-admin@example.test",
                "password": "Manual-beta-admin-2026",
                "company_name": "Manual Beta Admin Test",
            },
        )
        admin_token = str(admin.get("token") or "")
        if not admin_token:
            return fail(f"admin registration should return a token: {admin}")

        ordinary = _post_json(
            f"{base_url}/auth/register",
            {
                "email": "manual-beta-user@example.test",
                "password": "Manual-beta-user-2026",
                "company_name": "Manual Beta User Test",
            },
        )
        ordinary_token = str(ordinary.get("token") or "")
        if not ordinary_token:
            return fail(f"ordinary registration should return a token: {ordinary}")

        ordinary_order = _post_json(f"{base_url}/billing/manual-beta/orders", {"plan_key": "starter"}, token=ordinary_token)
        order = ordinary_order.get("manual_beta_payment_order") if isinstance(ordinary_order, dict) else {}
        if order.get("amount_cny") != 99 or order.get("duration_days") != 30 or order.get("plan_key") != "starter":
            return fail(f"manual beta order should be 99 CNY / 30 days / starter: {order}")
        if order.get("status") != "pending_manual_payment_confirmation":
            return fail(f"new manual beta order should wait for owner confirmation: {order}")
        if not str(order.get("payment_note") or "").startswith("JJ-BETA-"):
            return fail(f"manual beta order should generate a payment note: {order}")
        if order.get("qr_code_in_repository") is not False or order.get("frontend_gets_payment_secret") is not False:
            return fail(f"manual beta order must not expose QR/secrets: {order}")
        _assert_no_secret_material(order)

        status, body = _post_json_expect_error(
            f"{base_url}/billing/manual-beta/orders/{order['order_id']}/confirm",
            {"received_amount_cny": 99},
            token=ordinary_token,
        )
        if status != 403:
            return fail(f"ordinary merchant must not confirm manual beta receipt: {status}, {body}")

        admin_order_payload = _post_json(f"{base_url}/billing/manual-beta/orders", {"plan_key": "starter"}, token=admin_token)
        admin_order = admin_order_payload.get("manual_beta_payment_order") if isinstance(admin_order_payload, dict) else {}
        confirm = _post_json(
            f"{base_url}/billing/manual-beta/orders/{admin_order['order_id']}/confirm",
            {"received_amount_cny": 99, "payment_reference": "offline-receipt-1"},
            token=admin_token,
        ).get("manual_beta_payment_confirmation")
        if confirm.get("ok") is not True or confirm.get("status") != "manual_beta_payment_confirmed":
            return fail(f"internal admin confirmation should succeed: {confirm}")
        if confirm.get("triggers_real_charge") is not False or confirm.get("manual_reconciliation_required") is not True:
            return fail(f"manual beta confirmation must remain no-real-charge/manual: {confirm}")
        _assert_no_secret_material(confirm)

        usage = _fetch_json(f"{base_url}/billing/usage", token=admin_token).get("billing_usage", {})
        subscription = usage.get("subscription") if isinstance(usage, dict) else {}
        if subscription.get("provider") != "manual_beta" or subscription.get("plan_key") != "starter":
            return fail(f"manual beta confirmation should create a starter manual_beta subscription: {subscription}")
        if subscription.get("entitlement_active") is not True or subscription.get("payment_attention_required") is not False:
            return fail(f"manual beta confirmation should activate entitlement: {subscription}")
        if subscription.get("manual_reconciliation_required") is not True:
            return fail(f"manual beta subscription should stay visibly manual: {subscription}")

        orders = _fetch_json(f"{base_url}/billing/manual-beta/orders", token=admin_token).get("manual_beta_payment_orders", [])
        latest = next((item for item in orders if item.get("order_id") == admin_order["order_id"]), {})
        if latest.get("status") != "confirmed_manual_receipt":
            return fail(f"confirmed order should be visible in order list: {orders}")

        audit = _fetch_json(f"{base_url}/audit-logs?limit=80", token=admin_token).get("audit_logs", [])
        actions = {item.get("action_type") for item in audit if isinstance(item, dict)}
        if "billing.manual_beta_order.created" not in actions or "billing.manual_beta_payment.confirmed" not in actions:
            return fail(f"manual beta order and confirmation should be audited: {actions}")

        print("PASS jiejing_manual_beta_payment_flow")
        return 0
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
        _restore_env(previous)


def _env_keys() -> list[str]:
    return [
        "JIEJING_SAAS_ENV",
        "JIEJING_BILLING_PROVIDER",
        "JIEJING_BILLING_PLANS_PUBLISHED",
        "JIEJING_QUOTA_ENFORCEMENT_ENABLED",
        "JIEJING_INTERNAL_ADMIN_EMAILS",
        "JIEJING_EXPENSIVE_API_RATE_LIMIT_ENABLED",
    ]


def _restore_env(previous: dict[str, str | None]) -> None:
    for key, value in previous.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def _wait_for_health(base_url: str) -> int:
    for _ in range(80):
        try:
            health = _fetch_json(f"{base_url}/health")
            if health.get("status") == "ok":
                return 0
        except Exception:
            time.sleep(0.1)
    return 1


def _fetch_json(url: str, *, token: str = "", ip: str = "203.0.113.31") -> dict[str, Any]:
    request = urllib.request.Request(url, headers=_headers(token=token, ip=ip), method="GET")
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def _post_json(url: str, body: dict[str, Any], *, token: str = "", ip: str = "203.0.113.31") -> dict[str, Any]:
    headers = _headers(token=token, ip=ip)
    headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def _post_json_expect_error(url: str, body: dict[str, Any], *, token: str = "") -> tuple[int, dict[str, Any]]:
    try:
        return 200, _post_json(url, body, token=token)
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode("utf-8")
        return exc.code, json.loads(body_text) if body_text else {}


def _headers(*, token: str = "", ip: str = "203.0.113.31") -> dict[str, str]:
    headers = {"X-Forwarded-For": ip, "User-Agent": "JiejingManualBetaPaymentTest/1.0"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _assert_no_secret_material(payload: object) -> None:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True).lower()
    forbidden = ["sk_live", "rk_live", "whsec_", "client_secret", "refresh_token", "access_token_value", "qr_code_image"]
    leaked = [item for item in forbidden if item in text]
    if leaked:
        raise AssertionError(f"secret-like material leaked in manual beta payment payload: {leaked}")


if __name__ == "__main__":
    raise SystemExit(main())
