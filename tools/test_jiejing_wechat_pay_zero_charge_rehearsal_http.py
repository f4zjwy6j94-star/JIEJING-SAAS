#!/usr/bin/env python3
"""HTTP auth, tenant, phrase, and value-free checks for WeChat rehearsal."""

from __future__ import annotations

import json
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.billing_wechat_pay_rehearsal import (  # noqa: E402
    WECHAT_PAY_ZERO_CHARGE_REHEARSAL_CONFIRMATION,
)
from jiejing_saas.api_server import SaaSBackendHandler  # noqa: E402


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    with tempfile.TemporaryDirectory(
        prefix="jiejing-wechat-rehearsal-http-",
        ignore_cleanup_errors=True,
    ) as temp_dir:
        root = Path(temp_dir)
        port = _free_port()
        process = subprocess.Popen(
            [
                sys.executable,
                str(ROOT / "tools" / "jiejing_saas_backend_cli.py"),
                "serve",
                "--db",
                str(root / "saas.sqlite"),
                "--runtime-db",
                str(root / "runtime.sqlite"),
                "--output-root",
                str(root / "output"),
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
            if not _wait_for_health(base_url):
                return fail("backend did not become healthy")
            route = f"{base_url}/billing/wechat-pay/zero-charge-rehearsal"
            if not SaaSBackendHandler._is_expensive_api_rate_limited_path(
                "billing/wechat-pay/zero-charge-rehearsal"
            ):
                return fail("WeChat rehearsal must use the existing global/IP high-cost limiter")
            unauth_status, unauth = _post_expect_error(
                route,
                {"exact_confirmation": WECHAT_PAY_ZERO_CHARGE_REHEARSAL_CONFIRMATION},
            )
            if unauth_status != 401:
                return fail(f"unauthenticated rehearsal must return 401: {unauth_status}, {unauth}")

            owner_a = _post(
                f"{base_url}/auth/register",
                {
                    "email": "wechat-rehearsal-a@example.test",
                    "password": "WeChat-rehearsal-owner-a-2026",
                    "company_name": "WeChat Rehearsal A",
                },
            )
            owner_b = _post(
                f"{base_url}/auth/register",
                {
                    "email": "wechat-rehearsal-b@example.test",
                    "password": "WeChat-rehearsal-owner-b-2026",
                    "company_name": "WeChat Rehearsal B",
                },
            )
            token_a = str(owner_a.get("token") or "")
            token_b = str(owner_b.get("token") or "")
            if not token_a or not token_b:
                return fail("tenant fixtures did not receive bearer tokens")

            wrong_status, wrong = _post_expect_error(
                route,
                {"exact_confirmation": "RUN SOMETHING ELSE"},
                token=token_b,
            )
            wrong_report = (
                wrong.get("wechat_pay_zero_charge_rehearsal")
                if isinstance(wrong.get("wechat_pay_zero_charge_rehearsal"), dict)
                else {}
            )
            if wrong_status != 409 or wrong_report.get("reason") != "exact_rehearsal_confirmation_required":
                return fail(f"wrong rehearsal phrase must fail closed: {wrong_status}, {wrong_report}")
            if wrong_report.get("transport_invoked") is not False or wrong_report.get("evidence_recorded") is not False:
                return fail(f"wrong phrase touched transport or audit evidence: {wrong_report}")

            sentinel = "must-not-reflect-merchant-order-transaction-secret-cert-path"
            ready = _post(
                route,
                {
                    "exact_confirmation": WECHAT_PAY_ZERO_CHARGE_REHEARSAL_CONFIRMATION,
                    "merchant": sentinel,
                    "order": sentinel,
                    "transaction": sentinel,
                    "secret": sentinel,
                    "certificate_path": sentinel,
                },
                token=token_a,
            ).get("wechat_pay_zero_charge_rehearsal", {})
            if not isinstance(ready, dict) or ready.get("status") != "ready" or ready.get("evidence_recorded") is not True:
                return fail(f"authenticated exact-phrase rehearsal did not complete: {ready}")
            if sentinel in json.dumps(ready, ensure_ascii=False):
                return fail("request sentinel leaked into the value-free rehearsal report")

            second = _post(
                route,
                {"exact_confirmation": WECHAT_PAY_ZERO_CHARGE_REHEARSAL_CONFIRMATION},
                token=token_a,
            ).get("wechat_pay_zero_charge_rehearsal", {})
            if not isinstance(second, dict) or second.get("status") != "ready":
                return fail(f"second company-scoped rehearsal should remain within the hourly limit: {second}")
            before_third = _get(f"{base_url}/audit-logs?limit=20", token=token_a).get("audit_logs", [])
            third_status, third = _post_expect_error(
                route,
                {"exact_confirmation": WECHAT_PAY_ZERO_CHARGE_REHEARSAL_CONFIRMATION},
                token=token_a,
            )
            if third_status != 429:
                return fail(f"third company rehearsal in one hour must return 429: {third_status}, {third}")
            rate_limit = third.get("rate_limit") if isinstance(third.get("rate_limit"), dict) else {}
            if (
                rate_limit.get("scope") != "wechat_zero_charge_rehearsal_per_company"
                or rate_limit.get("max_requests") != 2
                or third.get("transport_invoked") is not False
                or third.get("evidence_recorded") is not False
                or third.get("fake_transport_call_count") != 0
            ):
                return fail(f"company 429 must prove zero transport and zero audit: {third}")
            after_third = _get(f"{base_url}/audit-logs?limit=20", token=token_a).get("audit_logs", [])
            if len(after_third) != len(before_third):
                return fail("rate-limited third rehearsal wrote an audit record")

            audit_a = _get(f"{base_url}/audit-logs?limit=20", token=token_a).get("audit_logs", [])
            audit_b = _get(f"{base_url}/audit-logs?limit=20", token=token_b).get("audit_logs", [])
            action = "billing.wechat_pay.zero_charge_rehearsal.completed"
            if sum(isinstance(item, dict) and item.get("action_type") == action for item in audit_a) != 2:
                return fail("caller tenant should have exactly two allowed WeChat rehearsal audits")
            if any(isinstance(item, dict) and item.get("action_type") == action for item in audit_b):
                return fail("WeChat rehearsal audit crossed the tenant boundary")
            serialized_audit = json.dumps(audit_a, ensure_ascii=False).lower()
            if sentinel in serialized_audit:
                return fail("request sentinel leaked into the backend audit")
            for forbidden in ("merchant_private_key", "api_v3_key", "platform_certificate", "transaction_id", "order_id", "pem"):
                if forbidden in json.dumps(ready, ensure_ascii=False).lower():
                    return fail(f"public rehearsal report contains forbidden field: {forbidden}")

            print("PASS jiejing_wechat_pay_zero_charge_rehearsal_http")
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


def _wait_for_health(base_url: str) -> bool:
    for _ in range(80):
        try:
            if _get(f"{base_url}/health").get("status") == "ok":
                return True
        except Exception:
            time.sleep(0.1)
    return False


def _post(url: str, payload: dict[str, Any], *, token: str = "") -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=_headers(token),
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def _post_expect_error(
    url: str,
    payload: dict[str, Any],
    *,
    token: str = "",
) -> tuple[int, dict[str, Any]]:
    try:
        return 200, _post(url, payload, token=token)
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def _get(url: str, *, token: str = "") -> dict[str, Any]:
    request = urllib.request.Request(url, headers=_headers(token), method="GET")
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _headers(token: str) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


if __name__ == "__main__":
    raise SystemExit(main())
