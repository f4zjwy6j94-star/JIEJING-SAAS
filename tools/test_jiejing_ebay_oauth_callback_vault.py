#!/usr/bin/env python3
"""Regression for eBay OAuth callback exchange -> Vault secret_ref -> connection."""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.config import SaaSSettings  # noqa: E402
from jiejing_saas.ebay_oauth import EbayOAuthPlanner  # noqa: E402
from jiejing_saas.ebay_oauth_callback import process_ebay_oauth_callback  # noqa: E402
from jiejing_saas.repository import SaaSRepository  # noqa: E402
from jiejing_saas.secret_store import SecretStoreBoundary  # noqa: E402
from jiejing_saas.vault_secret_resolver import VaultSecretResolver  # noqa: E402


OUT = ROOT / "output" / "test-ebay-oauth-callback-vault"
ENV_KEYS = (
    "JIEJING_SAAS_ENV",
    "JIEJING_EBAY_CLIENT_ID",
    "JIEJING_EBAY_CLIENT_SECRET",
    "JIEJING_EBAY_RU_NAME",
    "JIEJING_EBAY_OAUTH_EXCHANGE_LIVE",
    "JIEJING_VAULT_LOCAL_SECRET_RESOLVER_ENABLED",
    "JIEJING_VAULT_LOCAL_SECRET_STORE_PATH",
    "JIEJING_VAULT_ENABLED",
    "JIEJING_VAULT_PROVIDER",
    "JIEJING_VAULT_LIVE_RESOLVE_ENABLED",
    "JIEJING_VAULT_ADDR",
    "JIEJING_VAULT_TOKEN",
    "JIEJING_VAULT_MOUNT",
    "JIEJING_VAULT_KEYSPACE",
    "JIEJING_VAULT_KV_VERSION",
)
FORBIDDEN = (
    "CALLBACK-ACCESS-TOKEN-MUST-NOT-LEAK",
    "CALLBACK-REFRESH-TOKEN-MUST-NOT-LEAK",
    "CALLBACK-CLIENT-SECRET-MUST-NOT-LEAK",
    "CALLBACK-MANAGED-ACCESS-MUST-NOT-LEAK",
    "CALLBACK-MANAGED-REFRESH-MUST-NOT-LEAK",
    "CALLBACK-MANAGED-SECRET-MUST-NOT-LEAK",
    "VAULT-CALLBACK-TOKEN-MUST-NOT-LEAK",
    "Bearer ",
    "Basic ",
)


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    previous = {key: os.environ.get(key) for key in ENV_KEYS}
    local_secret_path = OUT / "local-secret-resolver.json"
    try:
        _clear_env()
        OUT.mkdir(parents=True, exist_ok=True)

        local_result = _run_local_secret_resolver_callback(local_secret_path=local_secret_path)
        if local_result != "ok":
            return fail(local_result)

        expired_result = _run_expired_state_blocked(local_secret_path=local_secret_path)
        if expired_result != "ok":
            return fail(expired_result)

        managed_result = _run_managed_vault_callback()
        if managed_result != "ok":
            return fail(managed_result)

        blocked_result = _run_production_local_resolver_blocked()
        if blocked_result != "ok":
            return fail(blocked_result)

        print("PASS jiejing_ebay_oauth_callback_vault")
        return 0
    finally:
        try:
            local_secret_path.unlink(missing_ok=True)
        except OSError:
            pass
        _restore_env(previous)


def _run_local_secret_resolver_callback(*, local_secret_path: Path) -> str:
    _clear_env()
    _base_oauth_env(environment="local_dev")
    os.environ["JIEJING_EBAY_CLIENT_SECRET"] = "CALLBACK-CLIENT-SECRET-MUST-NOT-LEAK"
    os.environ["JIEJING_VAULT_LOCAL_SECRET_RESOLVER_ENABLED"] = "true"
    os.environ["JIEJING_VAULT_LOCAL_SECRET_STORE_PATH"] = str(local_secret_path)
    local_secret_path.unlink(missing_ok=True)
    settings, repo, store, request = _seed_oauth_request(case_key="local-callback", port=8820)
    oauth_transport = _fake_oauth_transport(
        access_token="CALLBACK-ACCESS-TOKEN-MUST-NOT-LEAK",
        refresh_token="CALLBACK-REFRESH-TOKEN-MUST-NOT-LEAK",
    )
    result = process_ebay_oauth_callback(
        repository=repo,
        settings=settings,
        secret_store_boundary=SecretStoreBoundary(settings),
        ebay_oauth_planner=EbayOAuthPlanner(settings),
        state=request["state_nonce"],
        code="UNIT_AUTH_CODE",
        error="",
        oauth_transport=oauth_transport,
    )
    if result.get("status") != "callback_exchange_completed":
        return "local callback should complete exchange and Vault write"
    if result.get("secret_storage", {}).get("storage_adapter") != "local_secret_resolver":
        return "local callback should store through local secret resolver"
    if result.get("secret_ref", {}).get("status") != "local_secret_resolver_stored":
        return "local callback should update secret_ref status"
    if result.get("connection", {}).get("status") != "read_only_authorized":
        return "local callback should create read-only platform connection"
    if result.get("access_token_returned_to_frontend") is not False or result.get("refresh_token_returned_to_frontend") is not False:
        return "local callback must not return tokens to frontend"
    public_serialized = json.dumps(result, ensure_ascii=False)
    if any(value in public_serialized for value in FORBIDDEN):
        return "local callback public response leaked a token or secret"

    secret_ref = result.get("secret_ref", {})
    resolved = VaultSecretResolver(settings).resolve_secret(
        secret_ref=secret_ref,
        requested_by="oauth_refresh_service",
        task_scope="unit_callback_verify",
        allowed_purposes=["ebay_refresh_token"],
    )
    if resolved.get("secret_value") != "CALLBACK-REFRESH-TOKEN-MUST-NOT-LEAK":
        return "local secret resolver did not receive the refresh token internally"
    connections = repo.list_connections(company_id=store["company_id"], store_id=store["store_id"])
    if not connections or connections[0].get("secret_ref") != secret_ref.get("secret_ref"):
        return "platform connection should reference the stored secret_ref"
    db_text = _sqlite_public_dump(settings.db_path)
    if any(value in db_text for value in FORBIDDEN):
        return "SaaS database leaked a raw OAuth token or client secret"

    replay_seen = {"oauth_post": False}

    def replay_transport(request_obj: Any, timeout: float) -> tuple[int, dict[str, str], bytes]:
        replay_seen["oauth_post"] = True
        return _oauth_response(
            access_token="CALLBACK-ACCESS-TOKEN-MUST-NOT-LEAK",
            refresh_token="CALLBACK-REFRESH-TOKEN-MUST-NOT-LEAK",
        )

    replay = process_ebay_oauth_callback(
        repository=repo,
        settings=settings,
        secret_store_boundary=SecretStoreBoundary(settings),
        ebay_oauth_planner=EbayOAuthPlanner(settings),
        state=request["state_nonce"],
        code="UNIT_AUTH_CODE_REPLAY",
        error="",
        oauth_transport=replay_transport,
    )
    if replay.get("status") != "blocked_replayed_state":
        return "second callback with same state should be blocked as replay"
    if replay_seen["oauth_post"]:
        return "replayed callback must not call the eBay token endpoint"
    refetched = repo.get_oauth_authorization_request_by_state(state_nonce=request["state_nonce"])
    if not refetched or refetched.get("status") != "callback_exchange_completed":
        return "replayed callback must not overwrite the original completed OAuth request"
    return "ok"


def _run_expired_state_blocked(*, local_secret_path: Path) -> str:
    _clear_env()
    _base_oauth_env(environment="local_dev")
    os.environ["JIEJING_EBAY_CLIENT_SECRET"] = "CALLBACK-CLIENT-SECRET-MUST-NOT-LEAK"
    os.environ["JIEJING_VAULT_LOCAL_SECRET_RESOLVER_ENABLED"] = "true"
    os.environ["JIEJING_VAULT_LOCAL_SECRET_STORE_PATH"] = str(local_secret_path)
    settings, repo, _store, request = _seed_oauth_request(case_key="expired-state", port=8824)
    with sqlite3.connect(settings.db_path) as conn:
        conn.execute(
            """
            update oauth_authorization_requests
            set created_at = ?, updated_at = ?
            where oauth_request_id = ?
            """,
            ("2000-01-01T00:00:00+00:00", "2000-01-01T00:00:00+00:00", request["oauth_request_id"]),
        )
    seen = {"oauth_post": False}

    def oauth_transport(request_obj: Any, timeout: float) -> tuple[int, dict[str, str], bytes]:
        seen["oauth_post"] = True
        return _oauth_response(
            access_token="CALLBACK-ACCESS-TOKEN-MUST-NOT-LEAK",
            refresh_token="CALLBACK-REFRESH-TOKEN-MUST-NOT-LEAK",
        )

    result = process_ebay_oauth_callback(
        repository=repo,
        settings=settings,
        secret_store_boundary=SecretStoreBoundary(settings),
        ebay_oauth_planner=EbayOAuthPlanner(settings),
        state=request["state_nonce"],
        code="UNIT_AUTH_CODE_EXPIRED",
        error="",
        oauth_transport=oauth_transport,
    )
    if result.get("status") != "blocked_invalid_expired_state":
        return "expired callback state should be blocked before token exchange"
    if seen["oauth_post"]:
        return "expired callback state must not call the eBay token endpoint"
    refetched = repo.get_oauth_authorization_request_by_state(state_nonce=request["state_nonce"])
    if not refetched or refetched.get("status") != "blocked_invalid_expired_state":
        return "expired callback state should be recorded as expired"
    return "ok"


def _run_managed_vault_callback() -> str:
    _clear_env()
    _base_oauth_env(environment="staging")
    os.environ["JIEJING_EBAY_CLIENT_SECRET"] = "CALLBACK-MANAGED-SECRET-MUST-NOT-LEAK"
    os.environ["JIEJING_VAULT_ENABLED"] = "true"
    os.environ["JIEJING_VAULT_PROVIDER"] = "vault"
    os.environ["JIEJING_VAULT_LIVE_RESOLVE_ENABLED"] = "true"
    os.environ["JIEJING_VAULT_ADDR"] = "https://vault.example.test"
    os.environ["JIEJING_VAULT_TOKEN"] = "VAULT-CALLBACK-TOKEN-MUST-NOT-LEAK"
    os.environ["JIEJING_VAULT_MOUNT"] = "secret"
    os.environ["JIEJING_VAULT_KEYSPACE"] = "jiejing-callback"
    os.environ["JIEJING_VAULT_KV_VERSION"] = "v2"
    settings, repo, store, request = _seed_oauth_request(case_key="managed-callback", port=8821)
    oauth_seen = {"post": False}
    vault_seen = {"post": False, "body_had_refresh_token": False}

    def oauth_transport(request_obj: Any, timeout: float) -> tuple[int, dict[str, str], bytes]:
        oauth_seen["post"] = True
        return _oauth_response(
            access_token="CALLBACK-MANAGED-ACCESS-MUST-NOT-LEAK",
            refresh_token="CALLBACK-MANAGED-REFRESH-MUST-NOT-LEAK",
        )

    def vault_transport(request_obj: Any, timeout: float) -> tuple[int, dict[str, str], bytes]:
        vault_seen["post"] = request_obj.get_method() == "POST"
        token = request_obj.headers.get("X-vault-token") or request_obj.headers.get("X-Vault-Token")
        if token != "VAULT-CALLBACK-TOKEN-MUST-NOT-LEAK":
            return 403, {"content-type": "application/json"}, b'{"errors":["forbidden"]}'
        body = request_obj.data.decode("utf-8") if request_obj.data else ""
        vault_seen["body_had_refresh_token"] = "CALLBACK-MANAGED-REFRESH-MUST-NOT-LEAK" in body
        if "/v1/secret/data/jiejing-callback/" not in request_obj.full_url:
            return 404, {"content-type": "application/json"}, b'{"errors":["missing"]}'
        return 204, {"content-type": "application/json"}, b""

    result = process_ebay_oauth_callback(
        repository=repo,
        settings=settings,
        secret_store_boundary=SecretStoreBoundary(settings),
        ebay_oauth_planner=EbayOAuthPlanner(settings),
        state=request["state_nonce"],
        code="UNIT_AUTH_CODE",
        error="",
        oauth_transport=oauth_transport,
        vault_transport=vault_transport,
    )
    if result.get("status") != "callback_exchange_completed":
        return "managed callback should complete exchange and Vault write"
    if result.get("secret_storage", {}).get("storage_adapter") != "managed_hashicorp_vault":
        return "managed callback should store through HashiCorp Vault adapter"
    if result.get("secret_ref", {}).get("status") != "managed_vault_stored":
        return "managed callback should update secret_ref to managed_vault_stored"
    if oauth_seen != {"post": True} or vault_seen != {"post": True, "body_had_refresh_token": True}:
        return "managed callback should POST to eBay token endpoint and managed Vault"
    public_serialized = json.dumps(result, ensure_ascii=False)
    if any(value in public_serialized for value in FORBIDDEN):
        return "managed callback public response leaked a token or secret"
    db_text = _sqlite_public_dump(settings.db_path)
    if any(value in db_text for value in FORBIDDEN):
        return "managed callback database leaked a token or secret"
    connections = repo.list_connections(company_id=store["company_id"], store_id=store["store_id"])
    if not connections or connections[0].get("metadata", {}).get("credential_source") != "jiejing_vault_secret_ref":
        return "managed callback should create a Jiejing Vault-backed platform connection"
    return "ok"


def _run_production_local_resolver_blocked() -> str:
    _clear_env()
    _base_oauth_env(environment="production")
    os.environ["JIEJING_EBAY_CLIENT_SECRET"] = "CALLBACK-CLIENT-SECRET-MUST-NOT-LEAK"
    os.environ["JIEJING_VAULT_LOCAL_SECRET_RESOLVER_ENABLED"] = "true"
    settings, repo, _store, request = _seed_oauth_request(case_key="production-blocked", port=8822)
    seen = {"oauth_post": False}

    def oauth_transport(request_obj: Any, timeout: float) -> tuple[int, dict[str, str], bytes]:
        seen["oauth_post"] = True
        return _oauth_response(
            access_token="CALLBACK-ACCESS-TOKEN-MUST-NOT-LEAK",
            refresh_token="CALLBACK-REFRESH-TOKEN-MUST-NOT-LEAK",
        )

    result = process_ebay_oauth_callback(
        repository=repo,
        settings=settings,
        secret_store_boundary=SecretStoreBoundary(settings),
        ebay_oauth_planner=EbayOAuthPlanner(settings),
        state=request["state_nonce"],
        code="UNIT_AUTH_CODE",
        error="",
        oauth_transport=oauth_transport,
    )
    if result.get("status") != "callback_received_exchange_blocked":
        return "production callback should block without managed Vault"
    if seen["oauth_post"]:
        return "production callback must not exchange code before managed Vault is ready"
    if "Vault/KMS" not in result.get("blocked_by", []):
        return "production callback should surface Vault/KMS blocker"
    return "ok"


def _seed_oauth_request(*, case_key: str, port: int) -> tuple[SaaSSettings, SaaSRepository, dict[str, Any], dict[str, Any]]:
    db_path = OUT / f"{case_key}.sqlite"
    runtime_db_path = OUT / f"{case_key}-runtime.sqlite"
    db_path.unlink(missing_ok=True)
    runtime_db_path.unlink(missing_ok=True)
    settings = SaaSSettings.from_env(
        db_path=db_path,
        runtime_db_path=runtime_db_path,
        output_root=OUT / case_key,
        host="127.0.0.1",
        port=port,
    )
    repo = SaaSRepository(db_path)
    repo.initialize()
    user_company = repo.create_user_with_company(
        email=f"{case_key}@example.com",
        password="unit-password",
        company_name=f"{case_key} company",
    )
    company_id = user_company["company"]["company_id"]
    user_id = user_company["user"]["user_id"]
    store = repo.create_store(
        company_id=company_id,
        user_id=user_id,
        payload={"platform": "ebay", "store_name": f"{case_key} store", "marketplace": "EBAY_US"},
    )
    plan = EbayOAuthPlanner(settings).read_only_authorization_plan(
        company_id=company_id,
        store_id=store["store_id"],
        user_id=user_id,
        marketplace_id="EBAY_US",
    )
    request = repo.create_oauth_authorization_request(
        company_id=company_id,
        store_id=store["store_id"],
        user_id=user_id,
        plan=plan,
    )
    return settings, repo, {**store, "company_id": company_id, "user_id": user_id}, request


def _base_oauth_env(*, environment: str) -> None:
    os.environ["JIEJING_SAAS_ENV"] = environment
    os.environ["JIEJING_EBAY_CLIENT_ID"] = "CALLBACK-CLIENT-ID"
    os.environ["JIEJING_EBAY_RU_NAME"] = "Jiejing_Auth_RuName"
    os.environ["JIEJING_EBAY_OAUTH_EXCHANGE_LIVE"] = "true"


def _fake_oauth_transport(*, access_token: str, refresh_token: str) -> Any:
    def transport(request_obj: Any, timeout: float) -> tuple[int, dict[str, str], bytes]:
        if request_obj.get_method() != "POST" or "/identity/v1/oauth2/token" not in request_obj.full_url:
            return 404, {"content-type": "application/json"}, b'{"error":"missing"}'
        return _oauth_response(access_token=access_token, refresh_token=refresh_token)

    return transport


def _oauth_response(*, access_token: str, refresh_token: str) -> tuple[int, dict[str, str], bytes]:
    return (
        200,
        {"content-type": "application/json"},
        json.dumps(
            {
                "access_token": access_token,
                "refresh_token": refresh_token,
                "expires_in": 7200,
                "refresh_token_expires_in": 47304000,
            }
        ).encode("utf-8"),
    )


def _sqlite_public_dump(path: Path) -> str:
    with sqlite3.connect(path) as conn:
        tables = [
            row[0]
            for row in conn.execute(
                "select name from sqlite_master where type = 'table' and name not like 'sqlite_%' order by name"
            ).fetchall()
        ]
        rows: list[Any] = []
        for table in tables:
            rows.extend(conn.execute(f"select * from {table}").fetchall())
    return json.dumps(rows, ensure_ascii=False, default=str)


def _clear_env() -> None:
    for key in ENV_KEYS:
        os.environ.pop(key, None)


def _restore_env(previous: dict[str, str | None]) -> None:
    for key, value in previous.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


if __name__ == "__main__":
    raise SystemExit(main())
