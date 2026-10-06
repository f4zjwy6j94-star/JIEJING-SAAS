#!/usr/bin/env python3
"""Regression for merchant model save/verification truthfulness."""

from __future__ import annotations

import json
import os
import runpy
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
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


def serve_fixture() -> None:
    """Run the real server with external secret/provider boundaries fail-closed."""
    import jiejing_saas.api_server as api_server

    def blocked_resolver(self: Any, *, secret_ref: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        if secret_ref.get("status") not in {"stored_unverified", "ready"}:
            raise AssertionError("blocked historical storage must not invoke the resolver")
        return {"ok": False, "blocked_by": ["fixture_vault_temporarily_unavailable"]}

    def forbidden_provider(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("this contract must not invoke a model provider")

    api_server.VaultSecretResolver.resolve_secret = blocked_resolver
    api_server.build_model_client_from_byok_secret = forbidden_provider
    cli_path = ROOT / "tools" / "jiejing_saas_backend_cli.py"
    sys.argv = [str(cli_path), *sys.argv[2:]]
    runpy.run_path(str(cli_path), run_name="__main__")


def assert_historical_storage_recovery(base_url: str, cookie: str, store_id: str) -> None:
    """A saved connection becoming unreadable is not an unsuccessful first save."""
    from jiejing_saas.repository import SaaSRepository

    status, identity = request_json(f"{base_url}/me", cookie=cookie)
    assert status == 200, "existing merchant identity must remain readable"
    company_id = str(identity["company"]["company_id"])
    user_id = str(identity["user"]["user_id"])
    repository = SaaSRepository(SAAS_DB, database_engine="sqlite")
    reference = repository.create_secret_reference(
        company_id=company_id,
        store_id=None,
        user_id=user_id,
        provider="model.deepseek",
        purpose="model_api_key",
        status="ready",
        metadata={
            "provider_key": "deepseek",
            "model": "deepseek-v4-pro",
            "model_connection_scope": "account",
            "managed_vault_write_performed": True,
        },
    )
    settings_url = f"{base_url}/stores/{store_id}/model/settings"
    status, response = request_json(settings_url, cookie=cookie)
    settings = response.get("model_settings", {})
    assert status == 200 and settings.get("configured") is True, "saved history starts ready"
    repository.update_secret_reference_status(
        company_id=company_id,
        store_id=None,
        secret_ref=reference["secret_ref"],
        status="store_blocked",
        user_id=user_id,
        metadata_patch={
            "legacy_storage_unavailable": True,
            "secret_resolution_blocked": True,
            "blocked_by": ["legacy_tencent_ssm_kms_unavailable"],
            "verification_status": "failed",
            "verification_error_code": "model_secret_resolve_blocked",
        },
    )
    status, response = request_json(settings_url, cookie=cookie)
    settings = response.get("model_settings", {})
    assert status == 200, "historical recovery state must remain readable"
    assert settings.get("connection_state") == "storage_recovery_required", "historical success must not become first-save failure"
    assert settings.get("configured") is False and not settings.get("active_secret_ref"), "unreadable history is not an active credential"
    assert settings.get("requires_api_key_reentry") is False, "do not demand re-entry before recovery is investigated"
    assert settings.get("can_retry_verification") is False, "known unavailable storage is not a provider retry"
    assert settings.get("latest_attempt", {}).get("storage_recovery_required") is True
    status, verification = request_json(
        f"{base_url}/stores/{store_id}/model/verify",
        method="POST",
        cookie=cookie,
        payload={"model_secret_ref": reference["secret_ref"]},
    )
    assert status == 422 and verification.get("verified") is False
    assert verification.get("blocked_by") == ["model_secret_storage_recovery_required"], "verification must explain saved-storage recovery, not a new write failure"
    assert verification.get("requires_api_key_reentry") is False
    assert verification.get("can_retry_verification") is False
    assert verification.get("model_settings", {}).get("connection_state") == "storage_recovery_required"

    for history in (None, False, 1, "true"):
        repository.update_secret_reference_status(
            company_id=company_id, store_id=None, secret_ref=reference["secret_ref"],
            status="store_blocked", user_id=user_id,
            metadata_patch={"managed_vault_write_performed": history},
        )
        status, response = request_json(settings_url, cookie=cookie)
        settings = response.get("model_settings", {})
        assert status == 200 and settings.get("connection_state") == "save_failed", "missing or truthy non-boolean write evidence is not historical success"
        assert settings.get("requires_api_key_reentry") is True
        assert settings.get("latest_attempt", {}).get("storage_recovery_required") is False

    repository.update_secret_reference_status(
        company_id=company_id, store_id=None, secret_ref=reference["secret_ref"],
        status="store_blocked", user_id=user_id,
        metadata_patch={
            "managed_vault_write_performed": True,
            "legacy_storage_unavailable": "true", "secret_resolution_blocked": "true",
            "blocked_by": [], "verification_error_code": "",
        },
    )
    status, response = request_json(settings_url, cookie=cookie)
    assert status == 200 and response["model_settings"]["connection_state"] == "save_failed", "write evidence alone or truthy storage flags cannot invent a recovery diagnosis"

    repository.update_secret_reference_status(
        company_id=company_id, store_id=None, secret_ref=reference["secret_ref"],
        status="stored_unverified", user_id=user_id,
        metadata_patch={"legacy_storage_unavailable": False, "secret_resolution_blocked": False},
    )
    status, response = request_json(settings_url, cookie=cookie)
    settings = response.get("model_settings", {})
    assert status == 200 and settings.get("connection_state") == "saved_needs_verification"
    assert settings.get("can_retry_verification") is True and settings.get("requires_api_key_reentry") is False
    status, verification = request_json(
        f"{base_url}/stores/{store_id}/model/verify", method="POST", cookie=cookie,
        payload={"model_secret_ref": reference["secret_ref"]},
    )
    assert status == 422 and verification.get("blocked_by") == ["fixture_vault_temporarily_unavailable"]
    assert verification.get("can_retry_verification") is True and verification.get("requires_api_key_reentry") is False, "ordinary saved-storage outages retain their existing retry"

    repository.update_secret_reference_status(
        company_id=company_id, store_id=None, secret_ref=reference["secret_ref"],
        status="store_blocked", user_id=user_id,
        metadata_patch={"legacy_storage_unavailable": True, "secret_resolution_blocked": True},
    )
    active = repository.create_secret_reference(
        company_id=company_id, store_id=store_id, user_id=user_id,
        provider="model.deepseek", purpose="model_api_key", status="ready",
        metadata={"provider_key": "deepseek", "model_connection_scope": "store"},
    )
    status, response = request_json(settings_url, cookie=cookie)
    settings = response.get("model_settings", {})
    assert status == 200 and settings.get("configured") is True
    assert settings.get("active_secret_ref") == active["secret_ref"] and settings.get("active_scope") == "store"
    assert settings.get("connection_state") == "ready_with_failed_update", "an old blocked account reference must not hide another usable connection"
    status, verification = request_json(
        f"{base_url}/stores/{store_id}/model/verify", method="POST", cookie=cookie, payload={},
    )
    assert status == 422 and verification.get("blocked_by") == ["fixture_vault_temporarily_unavailable"], "default verification still selects the existing active connection"
    assert verification.get("can_retry_verification") is True and verification.get("requires_api_key_reentry") is False

    hidden = repository.create_secret_reference(
        company_id=company_id, store_id=None, user_id="other-synthetic-account",
        provider="model.deepseek", purpose="model_api_key", status="store_blocked",
        metadata={
            "provider_key": "deepseek", "model_connection_scope": "account",
            "managed_vault_write_performed": True, "legacy_storage_unavailable": True,
            "api_key": "SYNTHETIC-HIDDEN-KEY-MUST-NOT-LEAK",
        },
    )
    status, response = request_json(settings_url, cookie=cookie)
    serialized = json.dumps(response)
    assert status == 200 and hidden["secret_ref"] not in serialized, "other account references remain private"
    assert "SYNTHETIC-HIDDEN-KEY-MUST-NOT-LEAK" not in serialized
    status, verification = request_json(
        f"{base_url}/stores/{store_id}/model/verify", method="POST", cookie=cookie,
        payload={"model_secret_ref": hidden["secret_ref"]},
    )
    assert status == 422 and verification.get("blocked_by") == ["current_account_model_connection_missing"]
    assert hidden["secret_ref"] not in json.dumps(verification)
    status, _, other_cookie = register_session(
        f"{base_url}/auth/register",
        {"email": "other-model-owner@example.test", "password": "password123", "company_name": "Other Company"},
    )
    assert status == 201
    status, response = request_json(settings_url, cookie=other_cookie)
    assert status == 404 and reference["secret_ref"] not in json.dumps(response), "another tenant cannot inspect recovery metadata"
    print("PASS model_storage_recovery_http: lifecycle, strict evidence, retry, active fallback, account and tenant isolation")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for path in (SAAS_DB, RUNTIME_DB):
        if path.exists():
            path.unlink()
    port = free_port()
    env = os.environ.copy()
    for key in tuple(env):
        if key.startswith(("JIEJING_", "TENCENTCLOUD", "VAULT_", "OPENAI_", "DEEPSEEK_", "FAL_", "ANTHROPIC_")) or key == "DATABASE_URL":
            env.pop(key, None)
    env["JIEJING_SAAS_ENV"] = "staging"
    env["JIEJING_DATABASE_ENGINE"] = "sqlite"
    env["JIEJING_ENABLE_HERMES_WSL_SECRET_LOOKUP"] = "0"
    process = subprocess.Popen(
        [
            sys.executable,
            str(Path(__file__).resolve()),
            "--serve-fixture",
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
        assert_historical_storage_recovery(base_url, session_cookie, store_id)
        print("PASS jiejing_model_connection_save_contract")
        return 0
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--serve-fixture":
        serve_fixture()
    else:
        raise SystemExit(main())
