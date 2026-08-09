#!/usr/bin/env python3
"""Regression for merchant model save/verification truthfulness."""

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
OUT = ROOT / "output" / "jiejing-model-connection-save-contract" / "test"
SAAS_DB = OUT / "saas.sqlite"
RUNTIME_DB = OUT / "runtime.sqlite"


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def request_json(
    url: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    token: str = "",
    cookie: str = "",
) -> tuple[int, dict[str, Any]]:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"accept": "application/json", "content-type": "application/json"}
    if token:
        headers["authorization"] = f"Bearer {token}"
    if cookie:
        headers["cookie"] = cookie
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return int(response.status), json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        return int(exc.code), json.loads(raw) if raw else {}


def register_session(url: str, payload: dict[str, Any]) -> tuple[int, dict[str, Any], str]:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"accept": "application/json", "content-type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        record = json.loads(response.read().decode("utf-8"))
        cookie = str(response.headers.get("set-cookie") or "").split(";", 1)[0]
        return int(response.status), record, cookie


def wait_for_health(base_url: str) -> bool:
    deadline = time.time() + 20
    while time.time() < deadline:
        try:
            status, _ = request_json(f"{base_url}/health")
            if status == 200:
                return True
        except Exception:
            pass
        time.sleep(0.2)
    return False


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for path in (SAAS_DB, RUNTIME_DB):
        if path.exists():
            path.unlink()
    port = free_port()
    env = os.environ.copy()
    for key in tuple(env):
        if key.startswith("JIEJING_VAULT") or key.startswith("JIEJING_TENCENT") or key.startswith("TENCENTCLOUD"):
            env.pop(key, None)
    env["JIEJING_SAAS_ENV"] = "staging"
    env["JIEJING_ENABLE_HERMES_WSL_SECRET_LOOKUP"] = "0"
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
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        base_url = f"http://127.0.0.1:{port}"
        if not wait_for_health(base_url):
            return fail("backend did not become healthy")
        register_status, auth, session_cookie = register_session(
            f"{base_url}/auth/register",
            {"email": "model-save-contract@example.test", "password": "password123", "company_name": "Model Save Contract"},
        )
        if register_status != 201 or not session_cookie or "token" in auth:
            return fail("staging registration must use an HttpOnly session cookie without a browser-readable token")
        _, created = request_json(
            f"{base_url}/stores",
            method="POST",
            cookie=session_cookie,
            payload={"platform": "ebay", "store_name": "Model Save Store", "marketplace": "EBAY_US", "stage": "store_opened"},
        )
        store_id = str((created.get("store") or {}).get("store_id") or "")
        secret_marker = "MODEL-KEY-MUST-NOT-LEAK"
        unsafe_status, unsafe_response = request_json(
            f"{base_url}/stores/{store_id}/model/api-key",
            method="POST",
            cookie=session_cookie,
            payload={
                "provider_key": "deepseek",
                "model": "deepseek-v4-pro",
                "base_url": "http://127.0.0.1:9999",
                "connection_scope": "account",
                "api_key": secret_marker,
            },
        )
        if unsafe_status != 400 or "unapproved_model_base_url" not in set(unsafe_response.get("blocked_by") or []):
            return fail(f"staging must reject non-official model endpoints before storing a secret: {unsafe_response}")
        if secret_marker in json.dumps(unsafe_response, ensure_ascii=False):
            return fail("unsafe endpoint rejection leaked the submitted key")
        status, response = request_json(
            f"{base_url}/stores/{store_id}/model/api-key",
            method="POST",
            cookie=session_cookie,
            payload={
                "provider_key": "deepseek",
                "model": "deepseek-v4-pro",
                "base_url": "https://api.deepseek.com",
                "connection_scope": "account",
                "api_key": secret_marker,
            },
        )
        serialized = json.dumps(response, ensure_ascii=False)
        if status != 503:
            return fail(f"blocked safe storage must return HTTP 503, got {status}: {response}")
        if secret_marker in serialized:
            return fail("model save failure response leaked the submitted key")
        connection = response.get("model_connection", {})
        settings = response.get("model_settings", {})
        if connection.get("status") != "storage_failed" or connection.get("requires_api_key_reentry") is not True:
            return fail(f"storage failure must explicitly require one re-entry: {connection}")
        if settings.get("configured") is not False or settings.get("connection_state") != "save_failed":
            return fail(f"blocked storage must never be shown as configured: {settings}")
        if settings.get("active_secret_ref"):
            return fail("blocked storage must not become the active model secret ref")
        latest = settings.get("latest_attempt", {})
        if latest.get("requires_api_key_reentry") is not True or latest.get("can_retry_verification") is not False:
            return fail(f"latest attempt should explain that no retriable secret was saved: {latest}")
        print("PASS jiejing_model_connection_save_contract")
        return 0
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()


if __name__ == "__main__":
    raise SystemExit(main())
