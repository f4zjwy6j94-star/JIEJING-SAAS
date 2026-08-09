#!/usr/bin/env python3
"""Focused regressions for production-adjacent authentication and BYOK boundaries."""

from __future__ import annotations

import http.cookiejar
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas import api_server
from jiejing_saas.api_server import SaaSBackendHandler
from jiejing_saas.config import SaaSSettings


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _request_json(
    opener: urllib.request.OpenerDirector,
    url: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    origin: str = "",
    cookie: str = "",
) -> tuple[int, dict[str, Any], dict[str, str]]:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"accept": "application/json", "content-type": "application/json"}
    if origin:
        headers["origin"] = origin
    if cookie:
        headers["cookie"] = cookie
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with opener.open(request, timeout=20) as response:
            raw = response.read().decode("utf-8")
            return int(response.status), json.loads(raw) if raw else {}, dict(response.headers.items())
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        return int(exc.code), json.loads(raw) if raw else {}, dict(exc.headers.items())


def _wait_for_health(opener: urllib.request.OpenerDirector, base_url: str) -> bool:
    deadline = time.time() + 20
    while time.time() < deadline:
        try:
            status, body, _headers = _request_json(opener, f"{base_url}/health")
            if status == 200 and body.get("status") == "ok":
                return True
        except Exception:
            pass
        time.sleep(0.2)
    return False


def _test_production_like_cookie_and_token_boundary() -> None:
    with tempfile.TemporaryDirectory(prefix="jiejing-global-security-") as temp_dir:
        root = Path(temp_dir)
        port = _free_port()
        env = os.environ.copy()
        env.update(
            {
                "JIEJING_SAAS_ENV": "staging",
                "JIEJING_SAAS_SESSION_SECRET": "global-security-test-session-secret-long-enough",
                "JIEJING_CORS_ORIGIN": "https://app.jiejing.shop",
                "JIEJING_ENABLE_REAL_PLATFORM_WRITES": "false",
                "JIEJING_EBAY_WRITE_LIVE": "false",
                "JIEJING_PUBLIC_CHARGING_ALLOWED": "false",
                "JIEJING_BILLING_PROVIDER": "stripe_test_mock",
                "JIEJING_ENABLE_HERMES_WSL_SECRET_LOOKUP": "0",
            }
        )
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
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        jar = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        base_url = f"http://127.0.0.1:{port}"
        try:
            failures: list[str] = []
            if not _wait_for_health(opener, base_url):
                stderr = process.stderr.read() if process.stderr else ""
                raise AssertionError(f"backend did not become healthy: {stderr[-500:]}")
            register_status, registered, register_headers = _request_json(
                opener,
                f"{base_url}/auth/register",
                method="POST",
                origin="https://app.jiejing.shop",
                payload={
                    "email": "global-security@example.test",
                    "password": "password123",
                    "company_name": "Global Security Test",
                },
            )
            assert register_status == 201, registered
            if "token" in registered:
                failures.append("production-like registration returned a browser-readable bearer token")
            register_cookie_header = str(register_headers.get("Set-Cookie") or register_headers.get("set-cookie") or "")
            assert "httponly" in register_cookie_header.lower()
            assert "secure" in register_cookie_header.lower(), "production-like session cookie was not pinned to HTTPS"
            session_cookie = str(register_headers.get("Set-Cookie") or register_headers.get("set-cookie") or "").split(";", 1)[0]
            assert session_cookie
            company_id = str((registered.get("company") or {}).get("company_id") or "")
            assert company_id

            login_status, login, login_headers = _request_json(
                opener,
                f"{base_url}/auth/login",
                method="POST",
                payload={"email": "global-security@example.test", "password": "password123"},
            )
            assert login_status == 200, login
            if "token" in login:
                failures.append("production-like login returned a browser-readable bearer token")
            login_cookie_header = str(login_headers.get("Set-Cookie") or login_headers.get("set-cookie") or "")
            assert "secure" in login_cookie_header.lower(), "production-like session cookie depended on a forwarded HTTPS hint"
            session_cookie = login_cookie_header.split(";", 1)[0]
            assert session_cookie

            blocked_status, blocked, _headers = _request_json(
                opener,
                f"{base_url}/auth/switch-company",
                method="POST",
                origin="https://attacker.jiejing.shop",
                cookie=session_cookie,
                payload={"company_id": company_id},
            )
            if blocked_status != 403 or blocked.get("error") != "cross-origin mutation is not allowed":
                failures.append("production-like cookie-authenticated cross-origin mutation was accepted")
            serialized = json.dumps(blocked, ensure_ascii=False).lower()
            for forbidden in ("token", "cookie", "attacker.jiejing.shop", "global-security@example.test"):
                assert forbidden not in serialized, f"blocked Origin response leaked {forbidden}"

            allowed_status, allowed, _headers = _request_json(
                opener,
                f"{base_url}/auth/switch-company",
                method="POST",
                origin="https://app.jiejing.shop",
                cookie=session_cookie,
                payload={"company_id": company_id},
            )
            assert allowed_status == 200, allowed
            if "token" in allowed:
                failures.append("production-like company switch returned a browser-readable bearer token")
            assert not failures, "; ".join(failures)
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()


def _test_staging_byok_runtime_rejects_request_base_url_override() -> None:
    selected_ref = {
        "secret_ref": "ref_test_model",
        "company_id": "company_test",
        "store_id": None,
        "created_by": "user_test",
        "provider": "model.deepseek",
        "purpose": "model_api_key",
        "status": "ready",
        "metadata": {
            "model_connection_scope": "account",
            "provider_key": "deepseek",
            "model": "deepseek-v4-pro",
            "base_url": "https://api.deepseek.com",
        },
    }

    class Repository:
        @staticmethod
        def list_secret_refs(*, company_id: str) -> list[dict[str, Any]]:
            assert company_id == "company_test"
            return [selected_ref]

    class Resolver:
        def __init__(self, settings: SaaSSettings) -> None:
            self.settings = settings

        @staticmethod
        def resolve_secret(**_kwargs: Any) -> dict[str, Any]:
            return {"ok": True, "secret_value": "test-only-model-secret"}

    captured: list[dict[str, Any]] = []

    def build_client(**kwargs: Any) -> object:
        captured.append(dict(kwargs))
        return type("FakeModelClient", (), {"configured": lambda self: True, "endpoint": kwargs["base_url"]})()

    with tempfile.TemporaryDirectory(prefix="jiejing-byok-ssrf-") as temp_dir, mock.patch.dict(
        os.environ,
        {"JIEJING_SAAS_ENV": "staging"},
        clear=False,
    ), mock.patch.object(api_server, "VaultSecretResolver", Resolver), mock.patch.object(
        api_server,
        "build_model_client_from_byok_secret",
        build_client,
    ):
        root = Path(temp_dir)
        handler = object.__new__(SaaSBackendHandler)
        handler.repository = Repository()
        handler.settings = SaaSSettings.from_env(
            db_path=root / "saas.sqlite",
            runtime_db_path=root / "runtime.sqlite",
            output_root=root / "output",
            host="127.0.0.1",
            port=8788,
        )
        result = handler._resolve_model_client_for_store(
            identity={"company_id": "company_test", "user_id": "user_test", "email": "user@example.test"},
            store_id="store_test",
            body={"base_url": "http://127.0.0.1:9/internal"},
        )
        selected_ref["metadata"]["base_url"] = "http://127.0.0.1:9/stored-internal"
        stored_result = handler._resolve_model_client_for_store(
            identity={"company_id": "company_test", "user_id": "user_test", "email": "user@example.test"},
            store_id="store_test",
            body={},
        )
    assert result.get("status") == "blocked", result
    assert "unapproved_model_base_url_override" in set(result.get("blocked_by") or []), result
    assert stored_result.get("status") == "blocked", stored_result
    assert "unapproved_model_stored_base_url" in set(stored_result.get("blocked_by") or []), stored_result
    assert captured == [], "untrusted request base_url reached the model client factory"
    serialized = json.dumps([result, stored_result], ensure_ascii=False).lower()
    for forbidden in ("127.0.0.1", "test-only-model-secret", "ref_test_model"):
        assert forbidden not in serialized, f"BYOK endpoint rejection leaked {forbidden}"


def main() -> int:
    _test_staging_byok_runtime_rejects_request_base_url_override()
    _test_production_like_cookie_and_token_boundary()
    print("PASS jiejing_global_security_hardening")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
