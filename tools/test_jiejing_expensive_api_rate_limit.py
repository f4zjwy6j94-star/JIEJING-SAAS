#!/usr/bin/env python3
"""Regression for high-cost API rate limiting at the SaaS backend edge."""

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
OUT = ROOT / "output" / "jiejing-expensive-api-rate-limit-test"
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
            "JIEJING_INTERNAL_ADMIN_EMAILS": "rate-limit-admin@example.test",
            "JIEJING_EXPENSIVE_API_RATE_LIMIT_ENABLED": "1",
            "JIEJING_EXPENSIVE_API_RATE_LIMIT_WINDOW_SECONDS": "60",
            "JIEJING_EXPENSIVE_API_RATE_LIMIT_MAX_PER_IP": "2",
        }
    )
    port = 8797
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

        unauth_status, unauth_body = _fetch_json_expect_error(f"{base_url}/security/rate-limit/status", ip="203.0.113.10")
        if unauth_status != 401:
            return fail(f"rate-limit status should require authentication: {unauth_status}, {unauth_body}")

        admin = _post_json(
            f"{base_url}/auth/register",
            {
                "email": "rate-limit-admin@example.test",
                "password": "Rate-limit-admin-2026",
                "company_name": "Rate Limit Admin Test",
            },
        )
        admin_token = str(admin.get("token") or "")
        if not admin_token:
            return fail(f"admin registration should return a token: {admin}")

        ordinary = _post_json(
            f"{base_url}/auth/register",
            {
                "email": "rate-limit-ordinary@example.test",
                "password": "Rate-limit-ordinary-2026",
                "company_name": "Rate Limit Ordinary Test",
            },
        )
        ordinary_status, ordinary_body = _fetch_json_expect_error(
            f"{base_url}/security/rate-limit/status",
            ip="203.0.113.11",
            token=str(ordinary.get("token") or ""),
        )
        if ordinary_status != 403:
            return fail(f"rate-limit status should require internal admin allowlist: {ordinary_status}, {ordinary_body}")

        status = _fetch_json(f"{base_url}/security/rate-limit/status", token=admin_token)
        expensive = status.get("rate_limit_status", {}).get("expensive_api_rate_limit", {})
        if expensive.get("enabled") is not True or expensive.get("max_per_ip_per_route_group") != 2:
            return fail(f"rate-limit status should expose enabled fixture: {expensive}")
        if (
            expensive.get("platform_internal_admin_only") is not True
            or expensive.get("backend_status_requires_internal_admin") is not True
            or expensive.get("protects_get_and_post") is not True
        ):
            return fail(f"rate-limit status should be internal-admin-only with GET/POST protection evidence: {expensive}")
        route_groups = {item.get("route_group") for item in expensive.get("route_group_evidence", []) if isinstance(item, dict)}
        for required_group in {"reports", "model", "confirmations", "ebay-write", "post-publish", "billing"}:
            if required_group not in route_groups:
                return fail(f"rate-limit status should expose high-cost route evidence for {required_group}: {expensive}")
        stores_evidence = next((item for item in expensive.get("route_group_evidence", []) if item.get("route_group") == "stores"), {})
        if "POST /stores/{store_id}/merchant-ceo/chat" not in stores_evidence.get("example_paths", []):
            return fail(f"stores route evidence should include AI CEO chat protection: {stores_evidence}")
        if expensive.get("customer_visible") is not False or expensive.get("prevents_complete_copy") is not False:
            return fail(f"rate-limit status should stay owner-only and honest about anti-copy limits: {expensive}")
        for forbidden in ("refresh_token=", "client_secret=", "api_key=", "sk_live_", "whsec_"):
            if forbidden in json.dumps(status, ensure_ascii=False).lower():
                return fail(f"rate-limit status leaked forbidden marker: {forbidden}")

        first_status, _first_body = _fetch_json_expect_error(f"{base_url}/reports", ip="203.0.113.77")
        second_status, _second_body = _fetch_json_expect_error(f"{base_url}/reports", ip="203.0.113.77")
        third_status, third_body = _fetch_json_expect_error(f"{base_url}/reports", ip="203.0.113.77")
        if first_status != 401 or second_status != 401:
            return fail(f"first two unauthenticated expensive requests should reach auth boundary: {first_status}, {second_status}")
        if third_status != 429:
            return fail(f"third expensive request should be rate limited: {third_status}, {third_body}")
        rate_limit = third_body.get("rate_limit", {}) if isinstance(third_body, dict) else {}
        if rate_limit.get("route_group") != "reports" or third_body.get("secret_exposed") is not False:
            return fail(f"429 response should expose safe route-group evidence only: {third_body}")
        if rate_limit.get("protected_high_cost_api") is not True or rate_limit.get("frontend_gets_secret") is not False:
            return fail(f"429 response should expose safe operator evidence: {third_body}")

        saturated_status = _fetch_json(f"{base_url}/security/rate-limit/status", token=admin_token)
        saturated = saturated_status.get("rate_limit_status", {}).get("expensive_api_rate_limit", {}).get("active_bucket_summary", [])
        report_bucket = next((item for item in saturated if item.get("route_group") == "reports"), None)
        if not report_bucket or report_bucket.get("active_request_count") != 2 or report_bucket.get("client_ip_visible") is not False:
            return fail(f"active bucket summary should aggregate reports without exposing IP: {saturated}")

        health = _fetch_json(f"{base_url}/health", ip="203.0.113.77")
        if health.get("status") != "ok":
            return fail("health must not be expensive-API rate limited")

        print("PASS jiejing_expensive_api_rate_limit")
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
        "JIEJING_INTERNAL_ADMIN_EMAILS",
        "JIEJING_EXPENSIVE_API_RATE_LIMIT_ENABLED",
        "JIEJING_EXPENSIVE_API_RATE_LIMIT_WINDOW_SECONDS",
        "JIEJING_EXPENSIVE_API_RATE_LIMIT_MAX_PER_IP",
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


def _fetch_json(url: str, *, ip: str = "203.0.113.10", token: str = "") -> dict[str, Any]:
    headers = {"X-Forwarded-For": ip, "User-Agent": "JiejingRateLimitTest/1.0"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def _post_json(url: str, body: dict[str, Any], *, ip: str = "203.0.113.10", token: str = "") -> dict[str, Any]:
    headers = {"Content-Type": "application/json", "X-Forwarded-For": ip, "User-Agent": "JiejingRateLimitTest/1.0"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def _fetch_json_expect_error(url: str, *, ip: str, token: str = "") -> tuple[int, dict[str, Any]]:
    try:
        return 200, _fetch_json(url, ip=ip, token=token)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        return exc.code, json.loads(body) if body else {}


if __name__ == "__main__":
    raise SystemExit(main())
