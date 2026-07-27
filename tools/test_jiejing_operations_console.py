#!/usr/bin/env python3
"""Functional security and data-contract test for the independent operations console."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "jiejing-operations-console-test"
PORT = 8867
ADMIN_EMAIL = "ops-owner@jiejing-shop.cn"
MERCHANT_EMAIL = "ordinary-merchant@jiejing-shop.cn"
PASSWORD = "operations-console-test-password"


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True, exist_ok=True)
    db = OUT / "saas.sqlite"
    runtime_db = OUT / "runtime.sqlite"
    env = os.environ.copy()
    env["JIEJING_INTERNAL_ADMIN_EMAILS"] = ADMIN_EMAIL
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
            str(PORT),
        ],
        cwd=str(ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    try:
        base = f"http://127.0.0.1:{PORT}"
        _wait_for_health(base)
        merchant = _post_json(
            f"{base}/auth/register",
            {"email": MERCHANT_EMAIL, "password": PASSWORD, "company_name": "Ordinary Merchant"},
        )
        admin = _post_json(
            f"{base}/auth/register",
            {"email": ADMIN_EMAIL, "password": PASSWORD, "company_name": "Jiejing Operations"},
        )
        merchant_token = str(merchant["body"].get("token") or "")
        admin_token = str(admin["body"].get("token") or "")
        if not merchant_token or not admin_token:
            return fail("registration did not create test sessions")

        unauthenticated = _get_json(f"{base}/owner/operations-overview")
        if unauthenticated["status"] != 401:
            return fail(f"unauthenticated overview should be 401: {unauthenticated}")

        merchant_overview = _get_json(f"{base}/owner/operations-overview", token=merchant_token)
        merchant_details = [
            _get_json(f"{base}/owner/operations/{section}", token=merchant_token)
            for section in ("traffic", "merchants", "transactions", "costs", "workflows", "audit")
        ]
        if merchant_overview["status"] != 403 or any(item["status"] != 403 for item in merchant_details):
            return fail("ordinary merchant accessed internal operations data")

        merchant_ops_login = _post_json(
            f"{base}/owner/auth/login",
            {"email": MERCHANT_EMAIL, "password": PASSWORD},
            host="ops.jiejing.shop",
        )
        if merchant_ops_login["status"] != 403 or merchant_ops_login["headers"].get("set-cookie"):
            return fail(f"ordinary merchant received an operations session: {merchant_ops_login}")

        admin_ops_login = _post_json(
            f"{base}/owner/auth/login",
            {"email": ADMIN_EMAIL, "password": PASSWORD},
            host="ops.jiejing.shop",
        )
        admin_login_body = admin_ops_login["body"]
        admin_cookie = str(admin_ops_login["headers"].get("set-cookie") or "")
        if admin_ops_login["status"] != 200:
            return fail(f"internal admin login failed: {admin_ops_login}")
        if "token" in admin_login_body or admin_login_body.get("token_returned_to_frontend") is not False:
            return fail(f"operations login exposed bearer token: {admin_login_body}")
        if "HttpOnly" not in admin_cookie or "SameSite=Strict" not in admin_cookie:
            return fail(f"operations session cookie is not strict and HttpOnly: {admin_cookie}")

        overview_response = _get_json(f"{base}/owner/operations-overview?period_days=7", token=admin_token)
        if overview_response["status"] != 200:
            return fail(f"internal overview failed: {overview_response}")
        overview = overview_response["body"].get("operations_overview") or {}
        if overview.get("period", {}).get("days") != 7 or overview.get("audience") != "platform_internal_admin":
            return fail(f"overview period or audience is wrong: {overview}")
        if overview.get("merchant_navigation_visible") is not False or overview.get("secret_exposed") is not False:
            return fail("overview crossed merchant or secret boundary")
        clamped_overview = _get_json(f"{base}/owner/operations-overview?period_days=999999", token=admin_token)
        if clamped_overview["body"].get("operations_overview", {}).get("period", {}).get("days") != 366:
            return fail(f"overview period upper bound failed: {clamped_overview}")

        with ThreadPoolExecutor(max_workers=8) as executor:
            concurrent_results = list(
                executor.map(
                    lambda _: _get_json(f"{base}/owner/operations-overview?period_days=30", token=admin_token),
                    range(16),
                )
            )
        if any(response["status"] != 200 for response in concurrent_results):
            return fail(f"concurrent read-only overview requests were unstable: {concurrent_results}")

        all_detail_payloads = {}
        for section in ("traffic", "merchants", "transactions", "costs", "workflows", "audit"):
            response = _get_json(
                f"{base}/owner/operations/{section}?period_days=7&limit=1&cursor=not-a-valid-cursor",
                token=admin_token,
            )
            if response["status"] != 200:
                return fail(f"{section} detail failed: {response}")
            detail = response["body"].get("operations_detail") or {}
            if detail.get("section") != section or detail.get("secret_exposed") is not False:
                return fail(f"{section} detail contract is wrong: {detail}")
            if detail.get("merchant_content_exposed") is True:
                return fail(f"{section} detail exposed merchant content")
            all_detail_payloads[section] = detail

        serialized_details = json.dumps(all_detail_payloads, ensure_ascii=False).lower()
        if ADMIN_EMAIL in serialized_details or MERCHANT_EMAIL in serialized_details:
            return fail("operations detail exposed a raw account email")
        for forbidden in ("password", "refresh_token", "client_secret", "api_key"):
            if forbidden in serialized_details:
                return fail(f"operations detail exposed forbidden field: {forbidden}")

        invalid = _get_json(f"{base}/owner/operations/not-a-section", token=admin_token)
        if invalid["status"] != 400:
            return fail(f"invalid detail section should be 400: {invalid}")
        extreme = _get_json(
            f"{base}/owner/operations/merchants?period_days=-999&limit=9999&cursor=djE6OTk5OTk5",
            token=admin_token,
        )
        extreme_detail = extreme["body"].get("operations_detail") or {}
        if extreme["status"] != 200 or extreme_detail.get("period", {}).get("days") != 1 or len(extreme_detail.get("items") or []) > 100:
            return fail(f"detail bounds failed: {extreme}")
        malicious_query = urllib.parse.urlencode(
            {"status": "' OR 1=1 --", "plan": "<script>alert(1)</script>", "limit": "100"}
        )
        malicious = _get_json(f"{base}/owner/operations/merchants?{malicious_query}", token=admin_token)
        if malicious["status"] != 200 or malicious["body"].get("operations_detail", {}).get("secret_exposed") is not False:
            return fail(f"malicious filter input crossed the operations boundary: {malicious}")

        throttled = None
        for _ in range(21):
            throttled = _post_json(
                f"{base}/owner/auth/login",
                {"email": "rate-limit-attacker@example.invalid", "password": "wrong-password"},
                host="ops.jiejing.shop",
            )
        if not throttled or throttled["status"] != 429:
            return fail(f"operations login did not enforce the shared authentication rate limit: {throttled}")

        ops_html = (ROOT / "ops.html").read_text(encoding="utf-8")
        ops_js = (ROOT / "ops.js").read_text(encoding="utf-8")
        nginx = (ROOT / "deploy" / "nginx.public-staging.conf").read_text(encoding="utf-8")
        caddy_systemd = (ROOT / "deploy" / "Caddyfile.public-staging.systemd").read_text(encoding="utf-8")
        if "noindex,nofollow" not in ops_html or "/owner/auth/login" not in ops_js:
            return fail("operations frontend security markers are missing")
        if "localStorage" in ops_js or "sessionStorage" in ops_js:
            return fail("operations frontend persists a session token in browser storage")
        if "server_name ops.jiejing.shop" not in nginx or "location = /ops.html { return 404; }" not in nginx:
            return fail("operations hostname isolation is missing")
        if "listen 80 default_server;" not in nginx or "server_name app.jiejing.shop jiejing.shop" not in nginx:
            return fail("merchant application is not the explicit default virtual host")
        if "location ~ ^/(auth|permissions|owner)(/|$)" in nginx:
            return fail("operations hostname exposes broad backend route prefixes")
        for allowed_route in ("auth/logout", "permissions/me", "owner/auth/login", "owner/operations-overview"):
            if allowed_route not in nginx:
                return fail(f"operations hostname is missing required route: {allowed_route}")
        if "ops.jiejing.shop" not in caddy_systemd or 'Referrer-Policy "no-referrer"' not in caddy_systemd:
            return fail("systemd edge is missing the isolated operations hostname")
        if any(name in ops_js.lower() for name in ("fal.ai", "fal_api", "runway")):
            return fail("operations frontend exposed a media supplier brand")

        print("PASS jiejing_operations_console")
        return 0
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def _wait_for_health(base: str) -> None:
    deadline = time.time() + 25
    while time.time() < deadline:
        try:
            if _get_json(f"{base}/health")["status"] == 200:
                return
        except Exception:
            pass
        time.sleep(0.2)
    raise RuntimeError("backend did not become healthy")


def _post_json(url: str, body: dict[str, Any], *, token: str = "", host: str = "") -> dict[str, Any]:
    headers = {"content-type": "application/json", "accept": "application/json"}
    if token:
        headers["authorization"] = f"Bearer {token}"
    if host:
        headers["host"] = host
        headers["x-forwarded-proto"] = "https"
    request = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST")
    return _open_json(request)


def _get_json(url: str, *, token: str = "") -> dict[str, Any]:
    headers = {"accept": "application/json"}
    if token:
        headers["authorization"] = f"Bearer {token}"
    return _open_json(urllib.request.Request(url, headers=headers, method="GET"))


def _open_json(request: urllib.request.Request) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return {
                "status": response.status,
                "body": json.loads(response.read().decode("utf-8")),
                "headers": {key.lower(): value for key, value in response.headers.items()},
            }
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            body = json.loads(raw)
        except json.JSONDecodeError:
            body = {"raw": raw[:200]}
        return {
            "status": exc.code,
            "body": body,
            "headers": {key.lower(): value for key, value in exc.headers.items()},
        }


if __name__ == "__main__":
    raise SystemExit(main())
