#!/usr/bin/env python3
"""Functional access and mutation contract for the internal reliability duty loop."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "jiejing-reliability-alert-api-test"


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    startup_retry_result = _test_health_wait_retries_connection_refusal()
    if startup_retry_result:
        return fail(startup_retry_result)
    OUT.mkdir(parents=True, exist_ok=True)
    db = OUT / "reliability-alert-api.sqlite"
    runtime_db = OUT / "runtime.sqlite"
    for path in (db, runtime_db):
        if path.exists():
            path.unlink()

    port = 8844
    env = os.environ.copy()
    env["JIEJING_INTERNAL_ADMIN_EMAILS"] = "platform-reliability@example.test"
    process = subprocess.Popen(
        [
            sys.executable,
            str(ROOT / "tools" / "jiejing_saas_backend_cli.py"),
            "serve",
            "--db",
            str(db),
            "--runtime-db",
            str(runtime_db),
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
        env=env,
    )
    try:
        base = f"http://127.0.0.1:{port}"
        _wait_for_health(base)
        unauthenticated = _request_json(
            f"{base}/owner/operations-reliability-alerts/reconcile",
            method="POST",
            body={},
        )
        if unauthenticated["status"] != 401:
            return fail(f"unauthenticated reconcile should receive 401: {unauthenticated}")

        merchant_token = _register(base, "merchant-reliability@example.test")
        merchant_reconcile = _request_json(
            f"{base}/owner/operations-reliability-alerts/reconcile",
            method="POST",
            body={},
            token=merchant_token,
        )
        if merchant_reconcile["status"] != 403:
            return fail(f"merchant reconcile should receive 403: {merchant_reconcile}")

        admin_token = _register(base, "platform-reliability@example.test")
        first = _request_json(
            f"{base}/owner/operations-reliability-alerts/reconcile",
            method="POST",
            body={},
            token=admin_token,
        )
        second = _request_json(
            f"{base}/owner/operations-reliability-alerts/reconcile",
            method="POST",
            body={},
            token=admin_token,
        )
        for label, result in (("first", first), ("second", second)):
            if result["status"] != 200:
                return fail(f"internal admin {label} reconcile failed: {result}")
            body = result["body"]
            if body.get("real_platform_writes_enabled") is not False or body.get("external_provider_action_triggered") is not False:
                return fail(f"reconcile safety boundary is missing: {body}")
            if body.get("reliability_evaluation_window_minutes") != 30:
                return fail(f"manual reconcile must use the same focused scheduler window: {body}")
            lifecycle = body.get("reliability_alert_lifecycle") or {}
            if lifecycle.get("merchant_navigation_visible") is not False or lifecycle.get("secret_exposed") is not False:
                return fail(f"reliability lifecycle escaped the internal boundary: {lifecycle}")

        invalid_acknowledgement = _request_json(
            f"{base}/owner/operations-reliability-alerts/acknowledge",
            method="POST",
            body={"scope": "model", "action_key": "restart_provider"},
            token=admin_token,
        )
        if invalid_acknowledgement["status"] != 400:
            return fail(f"unknown acknowledgement action should receive 400: {invalid_acknowledgement}")

        no_open_alert = _request_json(
            f"{base}/owner/operations-reliability-alerts/acknowledge",
            method="POST",
            body={"scope": "model", "action_key": "investigating"},
            token=admin_token,
        )
        if no_open_alert["status"] != 409:
            return fail(f"acknowledging a non-open alert should receive 409: {no_open_alert}")

        before_get = _request_json(f"{base}/owner/operations-overview", token=admin_token)
        after_get = _request_json(f"{base}/owner/operations-overview", token=admin_token)
        before_lifecycle = ((before_get["body"].get("operations_overview") or {}).get("provider_reliability_analytics") or {}).get("lifecycle")
        after_lifecycle = ((after_get["body"].get("operations_overview") or {}).get("provider_reliability_analytics") or {}).get("lifecycle")
        if before_get["status"] != 200 or after_get["status"] != 200 or before_lifecycle != after_lifecycle:
            return fail("GET operations overview must not advance the reliability lifecycle")

        serialized = json.dumps(second["body"], ensure_ascii=False).lower()
        for forbidden in ("api_key", "client_secret", "refresh_token", "private_key", "raw provider"):
            if forbidden in serialized:
                return fail(f"reliability API leaked forbidden detail: {forbidden}")
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)

    print("PASS jiejing_reliability_alert_api")
    return 0


def _register(base: str, email: str) -> str:
    result = _request_json(
        f"{base}/auth/register",
        method="POST",
        body={"email": email, "password": "local-test-password", "company_name": "Reliability API Test"},
    )
    token = str(result["body"].get("token") or "")
    if result["status"] != 201 or not token:
        raise RuntimeError(f"registration failed: {result}")
    return token


def _wait_for_health(
    base: str,
    *,
    timeout_seconds: float = 20,
    retry_interval_seconds: float = 0.2,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            result = _request_json(f"{base}/health")
        except (urllib.error.URLError, ConnectionError, OSError, json.JSONDecodeError):
            result = {"status": 0}
        if result["status"] == 200:
            return
        time.sleep(retry_interval_seconds)
    raise RuntimeError("backend did not become healthy")


def _test_health_wait_retries_connection_refusal() -> str:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        unavailable_port = int(probe.getsockname()[1])
    try:
        _wait_for_health(
            f"http://127.0.0.1:{unavailable_port}",
            timeout_seconds=0.05,
            retry_interval_seconds=0.01,
        )
    except RuntimeError as exc:
        if str(exc) == "backend did not become healthy":
            return ""
        return f"unexpected startup retry error: {exc}"
    except urllib.error.URLError as exc:
        return f"health wait leaked transient connection refusal: {exc.reason.__class__.__name__}"
    return "health wait unexpectedly accepted an unavailable local port"


def _request_json(
    url: str,
    *,
    method: str = "GET",
    body: dict[str, Any] | None = None,
    token: str = "",
) -> dict[str, Any]:
    headers = {"accept": "application/json"}
    data = None
    if body is not None:
        headers["content-type"] = "application/json"
        data = json.dumps(body).encode("utf-8")
    if token:
        headers["authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return {"status": response.status, "body": json.loads(response.read().decode("utf-8"))}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            response_body = json.loads(raw)
        except json.JSONDecodeError:
            response_body = {"raw": raw[:300]}
        return {"status": exc.code, "body": response_body}


if __name__ == "__main__":
    raise SystemExit(main())
