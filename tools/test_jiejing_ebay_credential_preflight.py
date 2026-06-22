#!/usr/bin/env python3
"""Regression for sanitized eBay credential preflight."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.config import SaaSSettings  # noqa: E402
from jiejing_saas.ebay_credential_preflight import build_ebay_credential_preflight  # noqa: E402
from jiejing_saas.vault_secret_resolver import VaultSecretResolver  # noqa: E402


ENV_KEYS = (
    "JIEJING_SAAS_ENV",
    "JIEJING_EBAY_READ_ONLY_LIVE",
    "JIEJING_EBAY_ACCESS_TOKEN",
    "EBAY_ACCESS_TOKEN",
    "JIEJING_EBAY_TOKEN_REFRESH_LIVE",
    "JIEJING_EBAY_CLIENT_ID",
    "EBAY_CLIENT_ID",
    "JIEJING_EBAY_CLIENT_SECRET",
    "EBAY_CLIENT_SECRET",
    "JIEJING_EBAY_REFRESH_TOKEN",
    "EBAY_REFRESH_TOKEN",
    "JIEJING_ENABLE_HERMES_EBAY_BRIDGE",
    "JIEJING_ENABLE_HERMES_WSL_SECRET_LOOKUP",
    "JIEJING_EBAY_AUTO_REFRESH",
    "JIEJING_VAULT_ENABLED",
    "JIEJING_VAULT_PROVIDER",
    "JIEJING_VAULT_LOCAL_SECRET_RESOLVER_ENABLED",
    "JIEJING_VAULT_LOCAL_SECRET_STORE_PATH",
    "JIEJING_VAULT_LIVE_RESOLVE_ENABLED",
    "JIEJING_VAULT_ADDR",
    "JIEJING_VAULT_TOKEN",
    "JIEJING_VAULT_MOUNT",
    "JIEJING_VAULT_KEYSPACE",
    "JIEJING_VAULT_KV_VERSION",
)


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    previous = {key: os.environ.get(key) for key in ENV_KEYS}
    try:
        _clear_env()
        os.environ["JIEJING_SAAS_ENV"] = "local_dev"
        os.environ["JIEJING_ENABLE_HERMES_EBAY_BRIDGE"] = "false"
        default = _build()
        if default.get("status") != "blocked":
            return fail("default preflight should block without live flag and token")
        default_blockers = set(default.get("blocked_by") or [])
        if "live_read_switch" not in default_blockers or "token_source" not in default_blockers:
            return fail("default preflight should expose live switch and token blockers")
        if default.get("secret_exposed") is not False or default.get("frontend_gets_access_token") is not False:
            return fail("default preflight must keep secrets out of public response")

        _clear_env()
        os.environ["JIEJING_SAAS_ENV"] = "local_dev"
        os.environ["JIEJING_ENABLE_HERMES_EBAY_BRIDGE"] = "false"
        os.environ["JIEJING_EBAY_READ_ONLY_LIVE"] = "true"
        os.environ["JIEJING_EBAY_ACCESS_TOKEN"] = "FAKE-ACCESS-TOKEN-MUST-NOT-LEAK"
        direct = _build()
        if direct.get("status") != "ready_for_official_read" or direct.get("token_mode") != "backend_env_access_token":
            return fail("direct backend access token should make local preflight ready")
        direct_serialized = json.dumps(direct, ensure_ascii=False)
        if "FAKE-ACCESS-TOKEN-MUST-NOT-LEAK" in direct_serialized:
            return fail("direct token preflight leaked token value")

        _clear_env()
        os.environ["JIEJING_SAAS_ENV"] = "local_dev"
        os.environ["JIEJING_ENABLE_HERMES_EBAY_BRIDGE"] = "false"
        os.environ["JIEJING_EBAY_READ_ONLY_LIVE"] = "true"
        os.environ["JIEJING_EBAY_TOKEN_REFRESH_LIVE"] = "true"
        os.environ["JIEJING_EBAY_CLIENT_ID"] = "FAKE-CLIENT-ID"
        os.environ["JIEJING_EBAY_CLIENT_SECRET"] = "FAKE-CLIENT-SECRET-MUST-NOT-LEAK"
        os.environ["JIEJING_EBAY_REFRESH_TOKEN"] = "FAKE-REFRESH-TOKEN-MUST-NOT-LEAK"
        refresh = _build(
            secret_refs=[
                {
                    "secret_ref": "secret_refresh",
                    "provider": "ebay",
                    "purpose": "ebay_refresh_token",
                    "status": "external_vault_required",
                }
            ],
            connections=[
                {
                    "connection_id": "conn_refresh",
                    "platform": "ebay",
                    "connection_type": "oauth",
                    "status": "read_only_authorized",
                    "scopes": ["sell.account.readonly", "sell.inventory.readonly"],
                    "secret_ref": "secret_refresh",
                }
            ],
        )
        if refresh.get("status") != "ready_for_official_read" or refresh.get("token_mode") != "backend_refresh_token":
            return fail("refresh token flow should make local preflight ready")
        refresh_serialized = json.dumps(refresh, ensure_ascii=False)
        forbidden = (
            "FAKE-CLIENT-SECRET-MUST-NOT-LEAK",
            "FAKE-REFRESH-TOKEN-MUST-NOT-LEAK",
            "Authorization",
        )
        if any(value in refresh_serialized for value in forbidden):
            return fail("refresh token preflight leaked a secret or authorization header")

        _clear_env()
        os.environ["JIEJING_SAAS_ENV"] = "local_dev"
        os.environ["JIEJING_ENABLE_HERMES_EBAY_BRIDGE"] = "false"
        os.environ["JIEJING_EBAY_READ_ONLY_LIVE"] = "true"
        os.environ["JIEJING_EBAY_TOKEN_REFRESH_LIVE"] = "true"
        os.environ["JIEJING_EBAY_CLIENT_ID"] = "FAKE-CLIENT-ID"
        os.environ["JIEJING_EBAY_CLIENT_SECRET"] = "FAKE-CLIENT-SECRET-MUST-NOT-LEAK"
        os.environ["JIEJING_VAULT_LOCAL_SECRET_RESOLVER_ENABLED"] = "true"
        resolver_path = ROOT / "output" / "test-ebay-preflight-local-secret-resolver.json"
        if resolver_path.exists():
            resolver_path.unlink()
        os.environ["JIEJING_VAULT_LOCAL_SECRET_STORE_PATH"] = str(resolver_path)
        resolver_settings = _settings()
        resolver_secret_ref = {
            "secret_ref": "secret_ref_resolver_refresh",
            "company_id": "company_preflight",
            "store_id": "store_preflight",
            "provider": "ebay",
            "purpose": "ebay_refresh_token",
            "status": "external_vault_required",
        }
        VaultSecretResolver(resolver_settings).store_local_secret(
            secret_ref=resolver_secret_ref,
            secret_value="LOCAL-RESOLVER-REFRESH-TOKEN-MUST-NOT-LEAK",
            created_by="user_preflight",
        )
        resolver_preflight = build_ebay_credential_preflight(
            settings=resolver_settings,
            store={"store_id": "store_preflight", "store_name": "preflight store", "platform": "ebay", "marketplace": "EBAY_US"},
            secret_refs=[resolver_secret_ref],
            connections=[
                {
                    "connection_id": "conn_resolver",
                    "platform": "ebay",
                    "connection_type": "oauth",
                    "status": "read_only_authorized",
                    "scopes": ["sell.inventory.readonly"],
                    "secret_ref": "secret_ref_resolver_refresh",
                }
            ],
            requested_resources=["inventory_and_offers"],
        )
        if resolver_preflight.get("status") != "ready_for_official_read" or resolver_preflight.get("token_mode") != "backend_jiejing_secret_ref_resolver":
            return fail("secret_ref resolver flow should make local preflight ready")
        resolver_serialized = json.dumps(resolver_preflight, ensure_ascii=False)
        if "LOCAL-RESOLVER-REFRESH-TOKEN-MUST-NOT-LEAK" in resolver_serialized or "FAKE-CLIENT-SECRET-MUST-NOT-LEAK" in resolver_serialized:
            return fail("secret_ref resolver preflight leaked a secret")
        if resolver_path.exists():
            resolver_path.unlink()

        _clear_env()
        os.environ["JIEJING_SAAS_ENV"] = "staging"
        os.environ["JIEJING_ENABLE_HERMES_EBAY_BRIDGE"] = "false"
        os.environ["JIEJING_EBAY_READ_ONLY_LIVE"] = "true"
        os.environ["JIEJING_EBAY_TOKEN_REFRESH_LIVE"] = "true"
        os.environ["JIEJING_EBAY_CLIENT_ID"] = "FAKE-CLIENT-ID"
        os.environ["JIEJING_EBAY_CLIENT_SECRET"] = "FAKE-CLIENT-SECRET-MUST-NOT-LEAK"
        os.environ["JIEJING_VAULT_ENABLED"] = "true"
        os.environ["JIEJING_VAULT_PROVIDER"] = "vault"
        os.environ["JIEJING_VAULT_LIVE_RESOLVE_ENABLED"] = "true"
        os.environ["JIEJING_VAULT_ADDR"] = "https://vault.example.test"
        os.environ["JIEJING_VAULT_TOKEN"] = "VAULT-PREFLIGHT-TOKEN-MUST-NOT-LEAK"
        os.environ["JIEJING_VAULT_MOUNT"] = "secret"
        os.environ["JIEJING_VAULT_KEYSPACE"] = "jiejing-preflight"
        managed_seen = {"vault_get": False}

        def managed_transport(request: Any, timeout: float) -> tuple[int, dict[str, str], bytes]:
            managed_seen["vault_get"] = True
            token = request.headers.get("X-vault-token") or request.headers.get("X-Vault-Token")
            if token != "VAULT-PREFLIGHT-TOKEN-MUST-NOT-LEAK":
                return 403, {"content-type": "application/json"}, b'{"errors":["forbidden"]}'
            if "/v1/secret/data/jiejing-preflight/company/store/secret_managed_refresh" not in request.full_url:
                return 404, {"content-type": "application/json"}, b'{"errors":["missing"]}'
            return (
                200,
                {"content-type": "application/json"},
                b'{"data":{"data":{"refresh_token":"MANAGED-PREFLIGHT-REFRESH-TOKEN-MUST-NOT-LEAK"}}}',
            )

        managed = _build(
            secret_refs=[
                {
                    "secret_ref": "secret_managed_refresh",
                    "provider": "ebay",
                    "purpose": "ebay_refresh_token",
                    "status": "external_vault_required",
                }
            ],
            connections=[
                {
                    "connection_id": "conn_managed",
                    "platform": "ebay",
                    "connection_type": "oauth",
                    "status": "read_only_authorized",
                    "scopes": ["sell.inventory.readonly"],
                    "secret_ref": "secret_managed_refresh",
                }
            ],
            secret_transport=managed_transport,
        )
        if managed.get("status") != "ready_for_official_read" or managed.get("token_mode") != "backend_jiejing_secret_ref_resolver":
            return fail("managed Vault secret_ref resolver should make staging preflight ready")
        if managed.get("backend_secret_ref_resolver", {}).get("secret_ref_verified") is not True:
            return fail("managed Vault preflight should verify the secret_ref can actually be resolved")
        if managed_seen != {"vault_get": True}:
            return fail("managed Vault preflight should perform a backend-only Vault read")
        managed_serialized = json.dumps(managed, ensure_ascii=False)
        if (
            "VAULT-PREFLIGHT-TOKEN-MUST-NOT-LEAK" in managed_serialized
            or "MANAGED-PREFLIGHT-REFRESH-TOKEN-MUST-NOT-LEAK" in managed_serialized
            or "FAKE-CLIENT-SECRET-MUST-NOT-LEAK" in managed_serialized
        ):
            return fail("managed Vault preflight leaked a secret")

        missing = _build(
            secret_refs=[
                {
                    "secret_ref": "secret_missing_managed_refresh",
                    "provider": "ebay",
                    "purpose": "ebay_refresh_token",
                    "status": "external_vault_required",
                }
            ],
            connections=[
                {
                    "connection_id": "conn_missing_managed",
                    "platform": "ebay",
                    "connection_type": "oauth",
                    "status": "read_only_authorized",
                    "scopes": ["sell.inventory.readonly"],
                    "secret_ref": "secret_missing_managed_refresh",
                }
            ],
            secret_transport=lambda request, timeout: (404, {"content-type": "application/json"}, b'{"errors":["missing"]}'),
        )
        if missing.get("status") != "blocked" or missing.get("can_queue_sync") is not False:
            return fail("managed Vault preflight must block when the secret_ref record exists but the Vault value is missing")
        if missing.get("token_mode") != "not_ready":
            return fail("managed Vault missing secret_ref should not be reported as ready token mode")
        if missing.get("backend_secret_ref_resolver", {}).get("secret_ref_verified") is not False:
            return fail("managed Vault missing secret_ref should expose only a false verification flag")

        print("PASS jiejing_ebay_credential_preflight")
        return 0
    finally:
        _restore_env(previous)


def _clear_env() -> None:
    for key in ENV_KEYS:
        os.environ.pop(key, None)


def _restore_env(previous: dict[str, str | None]) -> None:
    for key, value in previous.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def _settings() -> SaaSSettings:
    return SaaSSettings.from_env(
        db_path=ROOT / "output" / "test-ebay-credential-preflight.sqlite",
        runtime_db_path=ROOT / "output" / "test-ebay-credential-preflight-runtime.sqlite",
        output_root=ROOT / "output" / "test-ebay-credential-preflight",
        host="127.0.0.1",
        port=8801,
    )


def _build(
    *,
    secret_refs: list[dict[str, object]] | None = None,
    connections: list[dict[str, object]] | None = None,
    secret_transport: Any | None = None,
) -> dict[str, object]:
    settings = _settings()
    return build_ebay_credential_preflight(
        settings=settings,
        store={"store_id": "store_preflight", "store_name": "preflight store", "platform": "ebay", "marketplace": "EBAY_US"},
        secret_refs=secret_refs or [],
        connections=connections or [],
        requested_resources=["store_profile", "account_business_policies", "inventory_and_offers"],
        secret_transport=secret_transport,
    )


if __name__ == "__main__":
    raise SystemExit(main())
