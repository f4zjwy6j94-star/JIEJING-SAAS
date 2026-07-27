#!/usr/bin/env python3
"""HTTP regression for merchant-safe domestic billing rehearsal routes."""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "jiejing-domestic-billing-api-test"


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True, exist_ok=True)
    port = _free_port()
    env = dict(os.environ)
    env.update({"JIEJING_SAAS_ENV": "test"})
    for key in (
        "JIEJING_WECHAT_PAY_APP_ID",
        "JIEJING_WECHAT_PAY_MCH_ID",
        "JIEJING_WECHAT_PAY_API_V3_KEY",
        "JIEJING_WECHAT_PAY_PLATFORM_CERTIFICATE_PEM",
        "JIEJING_WECHAT_PAY_PLATFORM_SERIAL_NO",
        "JIEJING_WECHAT_PAY_MERCHANT_SERIAL_NO",
        "JIEJING_WECHAT_PAY_MERCHANT_PRIVATE_KEY_PEM",
        "JIEJING_WECHAT_PAY_NOTIFY_URL",
    ):
        env.pop(key, None)
    process = subprocess.Popen(
        [
            sys.executable,
            str(ROOT / "tools" / "jiejing_saas_backend_cli.py"),
            "serve",
            "--db",
            str(OUT / "saas.sqlite"),
            "--runtime-db",
            str(OUT / "runtime.sqlite"),
            "--output-root",
            str(OUT),
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        base = f"http://127.0.0.1:{port}"
        if not _wait(base):
            return fail("backend did not become healthy")
        owner = _post_json(
            f"{base}/auth/register",
            {"email": "billing-owner@example.test", "password": "Billing-owner-2026", "company_name": "Billing Owner"},
        )
        other = _post_json(
            f"{base}/auth/register",
            {"email": "billing-other@example.test", "password": "Billing-other-2026", "company_name": "Billing Other"},
        )
        token = str(owner.get("token") or "")
        other_token = str(other.get("token") or "")
        if not token or not other_token:
            return fail("test accounts should receive bearer tokens")

        contract = _get_json(f"{base}/billing/domestic/contract", token=token).get("domestic_billing", {})
        if contract.get("status") != "not_open" or contract.get("real_checkout_ready") is not False:
            return fail(f"merchant contract must honestly stay not open: {contract}")
        serialized_contract = json.dumps(contract, ensure_ascii=False).lower()
        if "private_key" in serialized_contract or "api_v3" in serialized_contract or "mchid" in serialized_contract:
            return fail(f"merchant contract leaked internal credential diagnostics: {contract}")

        readiness = _get_json(f"{base}/readiness/product-saas").get("readiness", {})
        domestic_status = readiness.get("provider_status", {}).get("billing", {}).get("domestic_payment", {})
        if (
            domestic_status.get("provider") != "wechat_pay_native"
            or domestic_status.get("checkout_mode") != "native_qr"
            or domestic_status.get("billing_mode") != "one_time_30_day_plan"
            or domestic_status.get("charge_now_allowed") is not False
            or domestic_status.get("frontend_gets_payment_secret") is not False
        ):
            return fail(f"public readiness must expose a safe, honest domestic payment summary: {domestic_status}")
        if "real_checkout_ready" in domestic_status:
            return fail(f"public readiness must not expose implementation capability diagnostics: {domestic_status}")
        if domestic_status.get("required_component_count") != 9:
            return fail(f"public readiness must track all backend payment capability components: {domestic_status}")

        missing_status, missing = _post_json_expect_error(
            f"{base}/billing/domestic/orders",
            {"provider": "wechat_pay_native", "plan_key": "starter"},
            token=token,
        )
        if missing_status != 400 or missing.get("domestic_billing_order", {}).get("reason") != "billing_idempotency_key_invalid":
            return fail(f"order creation should require an idempotency header: {missing_status}, {missing}")

        headers = {"Idempotency-Key": "merchant-checkout-api-test-1"}
        first_status, first = _post_json_status(
            f"{base}/billing/domestic/orders",
            {"provider": "wechat_pay_native", "plan_key": "starter"},
            token=token,
            headers=headers,
        )
        second_status, second = _post_json_status(
            f"{base}/billing/domestic/orders",
            {"provider": "wechat_pay_native", "plan_key": "starter"},
            token=token,
            headers=headers,
        )
        first_order = first.get("domestic_billing_order", {})
        second_order = second.get("domestic_billing_order", {})
        if first_status != 201 or second_status != 200 or first_order.get("order_id") != second_order.get("order_id"):
            return fail(f"repeated merchant clicks must be idempotent: {first_status}, {second_status}, {first}, {second}")
        if first_order.get("triggers_real_charge") is not False or first_order.get("code_url"):
            return fail(f"rehearsal API must not charge or create a payable QR: {first_order}")

        order_id = str(first_order.get("order_id") or "")
        query_status, query_body = _post_json_expect_error(
            f"{base}/billing/domestic/orders/{order_id}/query",
            {},
            token=token,
        )
        query_result = query_body.get("domestic_billing_order_query", {})
        if query_status != 409 or query_result.get("calls_external_payment_api") is not False:
            return fail(f"live provider query must remain fail-closed before credentials: {query_status}, {query_body}")
        stored = _get_json(f"{base}/billing/domestic/orders/{order_id}", token=token).get("domestic_billing_order", {})
        if stored.get("order_id") != order_id:
            return fail(f"owner should retrieve its order: {stored}")
        if any(key in stored for key in ("company_id", "user_id", "order", "code_url", "provider_order_id")):
            return fail(f"merchant order detail must not expose tenant or provider internals: {stored}")
        listed = _get_json(f"{base}/billing/domestic/orders", token=token).get("domestic_billing_orders", [])
        if not listed or any(key in listed[0] for key in ("company_id", "user_id", "order", "code_url", "provider_order_id")):
            return fail(f"merchant order history must stay sanitized: {listed}")
        other_status, _ = _get_json_expect_error(f"{base}/billing/domestic/orders/{order_id}", token=other_token)
        if other_status != 404:
            return fail(f"another merchant must not discover the order: {other_status}")

        operations = _get_json(f"{base}/billing/domestic/operations", token=token).get("domestic_billing_operations", {})
        if operations.get("order_count") != 1 or operations.get("tenant_scoped") is not True:
            return fail(f"billing operations snapshot must stay company scoped: {operations}")
        if operations.get("calls_external_payment_api") is not False or operations.get("triggers_real_refund") is not False:
            return fail(f"billing operations snapshot must not move money: {operations}")
        other_operations = _get_json(f"{base}/billing/domestic/operations", token=other_token).get("domestic_billing_operations", {})
        if other_operations.get("order_count") != 0 or order_id in json.dumps(other_operations, ensure_ascii=False):
            return fail(f"another tenant must receive an empty independent operations snapshot: {other_operations}")
        unauth_operations_status, _ = _get_json_expect_error(f"{base}/billing/domestic/operations")
        if unauth_operations_status != 401:
            return fail(f"billing operations must require authentication: {unauth_operations_status}")

        reconcile_status, reconcile_body = _post_json_status(
            f"{base}/billing/domestic/reconcile",
            {"order_ids": [order_id, order_id]},
            token=token,
        )
        reconciliation = reconcile_body.get("domestic_billing_reconciliation", {})
        if reconcile_status != 200 or reconciliation.get("requested_count") != 1:
            return fail(f"billing reconciliation must be bounded and deduplicated: {reconcile_status}, {reconcile_body}")
        if reconciliation.get("triggers_real_charge") is not False or reconciliation.get("triggers_real_refund") is not False:
            return fail(f"billing reconciliation must never move money: {reconciliation}")
        foreign_reconcile_status, foreign_reconcile_body = _post_json_status(
            f"{base}/billing/domestic/reconcile",
            {"order_ids": [order_id]},
            token=other_token,
        )
        foreign_reconciliation = foreign_reconcile_body.get("domestic_billing_reconciliation", {})
        foreign_results = foreign_reconciliation.get("results") if isinstance(foreign_reconciliation.get("results"), list) else []
        if foreign_reconcile_status != 200 or not foreign_results or foreign_results[0].get("status") != "not_found":
            return fail(f"cross-tenant reconciliation must not discover an order: {foreign_reconcile_body}")
        oversized_status, oversized_body = _post_json_expect_error(
            f"{base}/billing/domestic/reconcile",
            {"order_ids": [f"domestic_batch_{index:02d}" for index in range(11)]},
            token=token,
        )
        if oversized_status != 400 or oversized_body.get("domestic_billing_reconciliation", {}).get("reason") != "domestic_reconciliation_batch_too_large":
            return fail(f"oversized reconciliation batches must fail closed: {oversized_status}, {oversized_body}")
        company_limit_statuses = [
            _post_json_expect_error(
                f"{base}/billing/domestic/reconcile",
                {"order_ids": [order_id]},
                token=token,
            )[0]
            for _ in range(4)
        ]
        if company_limit_statuses != [200, 200, 200, 429]:
            return fail(f"payment reconciliation needs an independent company rate limit: {company_limit_statuses}")

        callback_status, callback = _post_raw_status(
            f"{base}/billing/domestic/wechat-pay/notify",
            b"{}",
            headers={"Content-Type": "application/json"},
        )
        if callback_status != 503 or callback.get("code") != "FAIL":
            return fail(f"unconfigured callback must fail closed: {callback_status}, {callback}")
        if "configured" in json.dumps(callback, ensure_ascii=False).lower():
            return fail(f"public callback failure must not expose setup diagnostics: {callback}")

        refund_callback_status, refund_callback = _post_raw_status(
            f"{base}/billing/domestic/wechat-pay/refund-notify",
            b"{}",
            headers={"Content-Type": "application/json"},
        )
        if refund_callback_status != 503 or refund_callback.get("code") != "FAIL":
            return fail(f"unconfigured refund callback must fail closed: {refund_callback_status}, {refund_callback}")
        unauth_refund_execute, _ = _post_json_expect_error(
            f"{base}/billing/domestic/orders/{order_id}/refund-execute",
            {},
        )
        unauth_refund_query, _ = _post_json_expect_error(
            f"{base}/billing/domestic/orders/{order_id}/refund-query",
            {},
        )
        if unauth_refund_execute != 401 or unauth_refund_query != 401:
            return fail(f"refund execution and query routes must require authentication: {unauth_refund_execute}, {unauth_refund_query}")

        print("PASS jiejing_domestic_billing_api")
        return 0
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _wait(base: str) -> bool:
    for _ in range(100):
        try:
            if _get_json(f"{base}/health").get("status") == "ok":
                return True
        except Exception:
            time.sleep(0.1)
    return False


def _get_json(url: str, *, token: str = "") -> dict[str, Any]:
    request = urllib.request.Request(url, headers=_headers(token=token), method="GET")
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def _get_json_expect_error(url: str, *, token: str = "") -> tuple[int, dict[str, Any]]:
    try:
        return 200, _get_json(url, token=token)
    except urllib.error.HTTPError as exc:
        return int(exc.code), json.loads(exc.read().decode("utf-8"))


def _post_json(url: str, body: dict[str, Any], *, token: str = "", headers: dict[str, str] | None = None) -> dict[str, Any]:
    _status, payload = _post_json_status(url, body, token=token, headers=headers)
    return payload


def _post_json_status(
    url: str,
    body: dict[str, Any],
    *,
    token: str = "",
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, Any]]:
    request_headers = _headers(token=token)
    request_headers["Content-Type"] = "application/json"
    request_headers.update(headers or {})
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers=request_headers,
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return int(response.status), json.loads(response.read().decode("utf-8"))


def _post_json_expect_error(url: str, body: dict[str, Any], *, token: str = "") -> tuple[int, dict[str, Any]]:
    try:
        return _post_json_status(url, body, token=token)
    except urllib.error.HTTPError as exc:
        return int(exc.code), json.loads(exc.read().decode("utf-8"))


def _post_raw_status(url: str, body: bytes, *, headers: dict[str, str]) -> tuple[int, dict[str, Any]]:
    request = urllib.request.Request(url, data=body, headers={**_headers(), **headers}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return int(response.status), json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return int(exc.code), json.loads(exc.read().decode("utf-8"))


def _headers(*, token: str = "") -> dict[str, str]:
    headers = {"User-Agent": "JiejingDomesticBillingApiTest/1.0"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


if __name__ == "__main__":
    raise SystemExit(main())
