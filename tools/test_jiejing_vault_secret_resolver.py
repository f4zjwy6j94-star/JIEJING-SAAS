#!/usr/bin/env python3
"""Regression for Jiejing's backend-only Vault secret resolver boundary."""

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
import jiejing_saas.vault_secret_resolver as vault_resolver_module  # noqa: E402
from jiejing_saas.vault_secret_resolver import VaultSecretResolver, _hashicorp_vault_config, build_vault_secret_resolver_status  # noqa: E402


ENV_KEYS = (
    "JIEJING_SAAS_ENV",
    "JIEJING_VAULT_ENABLED",
    "JIEJING_VAULT_PROVIDER",
    "JIEJING_VAULT_LOCAL_SECRET_RESOLVER_ENABLED",
    "JIEJING_VAULT_LOCAL_SECRET_STORE_PATH",
    "JIEJING_VAULT_LIVE_RESOLVE_ENABLED",
    "JIEJING_VAULT_ADDR",
    "VAULT_ADDR",
    "JIEJING_VAULT_TOKEN",
    "VAULT_TOKEN",
    "JIEJING_VAULT_MOUNT",
    "JIEJING_VAULT_KEYSPACE",
    "JIEJING_VAULT_KV_VERSION",
    "JIEJING_VAULT_PATH_TEMPLATE",
    "JIEJING_VAULT_SECRET_FIELD",
    "JIEJING_TENCENT_REGION",
    "JIEJING_TENCENT_SECRET_ID",
    "JIEJING_TENCENT_SECRET_KEY",
    "JIEJING_TENCENT_TOKEN",
    "JIEJING_TENCENT_SSM_LIVE_RESOLVE_ENABLED",
    "JIEJING_TENCENT_SSM_LIVE_WRITE_ENABLED",
    "JIEJING_TENCENT_SSM_KEYSPACE",
    "JIEJING_TENCENT_SSM_SECRET_NAME_TEMPLATE",
    "JIEJING_TENCENT_SSM_SECRET_FIELD",
)


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    previous = {key: os.environ.get(key) for key in ENV_KEYS}
    local_path = ROOT / "output" / "test-vault-secret-resolver.json"
    try:
        _clear_env()
        os.environ["JIEJING_SAAS_ENV"] = "local_dev"
        default_settings = _settings()
        default_status = build_vault_secret_resolver_status(default_settings)
        if default_status.get("live_secret_resolution_available") is not False:
            return fail("secret resolver should be disabled by default")
        if default_status.get("returns_raw_secret_to_frontend") is not False or default_status.get("returns_raw_secret_to_runtime") is not False:
            return fail("default resolver status must not return raw secrets")

        _clear_env()
        if local_path.exists():
            local_path.unlink()
        os.environ["JIEJING_SAAS_ENV"] = "local_dev"
        os.environ["JIEJING_VAULT_LOCAL_SECRET_RESOLVER_ENABLED"] = "true"
        os.environ["JIEJING_VAULT_LOCAL_SECRET_STORE_PATH"] = str(local_path)
        local_settings = _settings()
        secret_ref = {
            "secret_ref": "secret_unit_resolver",
            "company_id": "company_unit",
            "store_id": "store_unit",
            "provider": "ebay",
            "purpose": "ebay_refresh_token",
            "status": "external_vault_required",
        }
        resolver = VaultSecretResolver(local_settings)
        public_store = resolver.store_local_secret(
            secret_ref=secret_ref,
            secret_value="UNIT-RESOLVER-SECRET-MUST-NOT-LEAK",
            created_by="user_unit",
        )
        if public_store.get("status") != "ready" or public_store.get("secret_value_returned") is not False:
            return fail("local resolver should store secret but return only public status")
        public_serialized = json.dumps({"status": resolver.status(), "store": public_store}, ensure_ascii=False)
        if "UNIT-RESOLVER-SECRET-MUST-NOT-LEAK" in public_serialized:
            return fail("public resolver responses leaked a local secret")

        resolved = resolver.resolve_secret(
            secret_ref=secret_ref,
            requested_by="oauth_refresh_service",
            task_scope="unit_ebay_read_only",
            allowed_purposes=["ebay_refresh_token"],
        )
        if resolved.get("ok") is not True or resolved.get("secret_value") != "UNIT-RESOLVER-SECRET-MUST-NOT-LEAK":
            return fail("backend resolver should return raw secret only to internal caller")
        if resolved.get("frontend_gets_raw_secret") is not False or resolved.get("runtime_gets_raw_secret") is not False:
            return fail("internal resolver result must still mark public boundaries as false")

        _clear_env()
        os.environ["JIEJING_SAAS_ENV"] = "staging"
        os.environ["JIEJING_VAULT_ENABLED"] = "true"
        os.environ["JIEJING_VAULT_PROVIDER"] = "vault"
        os.environ["JIEJING_VAULT_LIVE_RESOLVE_ENABLED"] = "true"
        os.environ["JIEJING_VAULT_ADDR"] = "https://vault.example.test"
        os.environ["JIEJING_VAULT_TOKEN"] = "VAULT-TOKEN-MUST-NOT-LEAK"
        os.environ["JIEJING_VAULT_MOUNT"] = "secret"
        os.environ["JIEJING_VAULT_KEYSPACE"] = "jiejing-unit"
        managed_settings = _settings()
        managed_status = build_vault_secret_resolver_status(managed_settings)
        if managed_status.get("live_secret_resolution_available") is not True:
            return fail("HashiCorp Vault resolver should be live-ready when managed config is complete")
        if managed_status.get("hashicorp_vault", {}).get("token_configured") is not True:
            return fail("HashiCorp Vault status should expose only token presence")
        managed_config = _hashicorp_vault_config(managed_settings)
        if "token" in managed_config or "VAULT-TOKEN-MUST-NOT-LEAK" in json.dumps(managed_config, ensure_ascii=False):
            return fail("HashiCorp Vault config object should not carry the raw Vault token")
        managed_seen = {"vault_get": False}

        def fake_vault_transport(request: Any, timeout: float) -> tuple[int, dict[str, str], bytes]:
            managed_seen["vault_get"] = True
            token = request.headers.get("X-vault-token") or request.headers.get("X-Vault-Token")
            if token != "VAULT-TOKEN-MUST-NOT-LEAK":
                return 403, {"content-type": "application/json"}, b'{"errors":["forbidden"]}'
            if request.get_method() != "GET" or "/v1/secret/data/jiejing-unit/company_unit/store_unit/secret_unit_resolver" not in request.full_url:
                return 404, {"content-type": "application/json"}, b'{"errors":["missing"]}'
            return (
                200,
                {"content-type": "application/json"},
                b'{"data":{"data":{"refresh_token":"MANAGED-VAULT-SECRET-MUST-NOT-LEAK"}}}',
            )

        managed_resolver = VaultSecretResolver(managed_settings, transport=fake_vault_transport)
        managed_public = managed_resolver.public_record_status(secret_ref=secret_ref)
        if managed_public.get("status") != "ready_for_managed_resolution" or managed_public.get("secret_value_returned") is not False:
            return fail("managed resolver public status should be ready without returning the secret")
        managed_resolved = managed_resolver.resolve_secret(
            secret_ref=secret_ref,
            requested_by="oauth_refresh_service",
            task_scope="unit_managed_vault",
            allowed_purposes=["ebay_refresh_token"],
        )
        if managed_resolved.get("ok") is not True or managed_resolved.get("source") != "backend_hashicorp_vault_secret_resolver":
            return fail("managed Vault resolver should resolve through the HashiCorp HTTP client")
        if managed_resolved.get("secret_value") != "MANAGED-VAULT-SECRET-MUST-NOT-LEAK":
            return fail("managed Vault resolver did not return the expected internal secret value")
        managed_public_serialized = json.dumps({"status": managed_status, "public": managed_public}, ensure_ascii=False)
        if "VAULT-TOKEN-MUST-NOT-LEAK" in managed_public_serialized or "MANAGED-VAULT-SECRET-MUST-NOT-LEAK" in managed_public_serialized:
            return fail("managed Vault public responses leaked token or secret value")
        if managed_seen != {"vault_get": True}:
            return fail("managed Vault resolver should perform exactly one backend Vault read")

        _clear_env()
        os.environ["JIEJING_SAAS_ENV"] = "staging"
        os.environ["JIEJING_VAULT_ENABLED"] = "true"
        os.environ["JIEJING_VAULT_PROVIDER"] = "tencent_ssm"
        os.environ["JIEJING_TENCENT_SSM_LIVE_RESOLVE_ENABLED"] = "true"
        os.environ["JIEJING_TENCENT_SSM_LIVE_WRITE_ENABLED"] = "true"
        os.environ["JIEJING_TENCENT_REGION"] = "ap-guangzhou"
        os.environ["JIEJING_TENCENT_SECRET_ID"] = "TENCENT-SECRET-ID-MUST-NOT-LEAK"
        os.environ["JIEJING_TENCENT_SECRET_KEY"] = "TENCENT-SECRET-KEY-MUST-NOT-LEAK"
        os.environ["JIEJING_TENCENT_SSM_KEYSPACE"] = "jiejing-unit"
        original_sdk_available = vault_resolver_module._tencent_ssm_sdk_available
        original_build_client = vault_resolver_module._build_tencent_ssm_client
        fake_client = _FakeTencentSSMClient()
        try:
            vault_resolver_module._tencent_ssm_sdk_available = lambda: True
            vault_resolver_module._build_tencent_ssm_client = lambda config: fake_client
            tencent_settings = _settings()
            tencent_status = build_vault_secret_resolver_status(tencent_settings)
            if tencent_status.get("live_secret_resolution_available") is not True:
                return fail("Tencent SSM resolver should be live-ready when managed config is complete")
            if tencent_status.get("tencent_ssm", {}).get("credentials_configured") is not True:
                return fail("Tencent SSM public status should expose only credential presence")
            tencent_resolver = VaultSecretResolver(tencent_settings)
            tencent_store = tencent_resolver.store_secret(
                secret_ref=secret_ref,
                secret_value="TENCENT-SSM-SECRET-MUST-NOT-LEAK",
                created_by="user_unit",
                metadata={"scope": "unit", "refresh_token_preview": "must-redact"},
            )
            if tencent_store.get("status") != "stored" or tencent_store.get("storage_adapter") != "managed_tencent_ssm":
                return fail("Tencent SSM resolver should write through the managed backend adapter")
            tencent_resolved = tencent_resolver.resolve_secret(
                secret_ref=secret_ref,
                requested_by="oauth_refresh_service",
                task_scope="unit_tencent_ssm",
                allowed_purposes=["ebay_refresh_token"],
            )
            if tencent_resolved.get("ok") is not True or tencent_resolved.get("source") != "backend_tencent_ssm_secret_resolver":
                return fail("Tencent SSM resolver should resolve through the backend-only client")
            if tencent_resolved.get("secret_value") != "TENCENT-SSM-SECRET-MUST-NOT-LEAK":
                return fail("Tencent SSM resolver did not return the expected internal secret value")
            tencent_revoked = tencent_resolver.revoke_secret(
                secret_ref=secret_ref,
                requested_by="queued_worker",
                task_scope="ebay_marketplace_account_deletion",
            )
            if tencent_revoked.get("status") != "revoked" or tencent_revoked.get("storage_adapter") != "managed_tencent_ssm":
                return fail("Tencent SSM resolver should permanently revoke through the managed backend adapter")
            if fake_client.force_delete_seen is not True:
                return fail("Tencent SSM revocation should request immediate permanent deletion")
            tencent_public_serialized = json.dumps({"status": tencent_status, "store": tencent_store}, ensure_ascii=False)
            for forbidden in ("TENCENT-SECRET-ID-MUST-NOT-LEAK", "TENCENT-SECRET-KEY-MUST-NOT-LEAK", "TENCENT-SSM-SECRET-MUST-NOT-LEAK"):
                if forbidden in tencent_public_serialized:
                    return fail(f"Tencent SSM public responses leaked secret marker {forbidden}")
            if fake_client.operations != ["put", "get", "delete"]:
                return fail(f"Tencent SSM fake client saw unexpected operations: {fake_client.operations}")
        finally:
            vault_resolver_module._tencent_ssm_sdk_available = original_sdk_available
            vault_resolver_module._build_tencent_ssm_client = original_build_client

        _clear_env()
        os.environ["JIEJING_SAAS_ENV"] = "production"
        os.environ["JIEJING_VAULT_LOCAL_SECRET_RESOLVER_ENABLED"] = "true"
        os.environ["JIEJING_VAULT_LOCAL_SECRET_STORE_PATH"] = str(local_path)
        production_status = build_vault_secret_resolver_status(_settings())
        if production_status.get("live_secret_resolution_available") is not False:
            return fail("local resolver must be disabled in production-like environments")
        if "production_requires_managed_vault" not in production_status.get("blocked_by", []):
            return fail("production resolver status should require managed Vault/KMS")

        if local_path.exists():
            local_path.unlink()
        print("PASS jiejing_vault_secret_resolver")
        return 0
    finally:
        if local_path.exists():
            local_path.unlink()
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
        db_path=ROOT / "output" / "test-vault-secret-resolver.sqlite",
        runtime_db_path=ROOT / "output" / "test-vault-secret-resolver-runtime.sqlite",
        output_root=ROOT / "output" / "test-vault-secret-resolver",
        host="127.0.0.1",
        port=8803,
    )


class _FakeTencentSSMResponse:
    def __init__(self, secret_string: str) -> None:
        self.SecretString = secret_string


class _FakeTencentSSMClient:
    def __init__(self) -> None:
        self.secret_string = ""
        self.operations: list[str] = []
        self.force_delete_seen = False

    def PutSecretValue(self, request: Any) -> object:
        self.operations.append("put")
        self.secret_string = request.SecretString
        return object()

    def CreateSecret(self, request: Any) -> object:
        self.operations.append("create")
        self.secret_string = request.SecretString
        return object()

    def GetSecretValue(self, request: Any) -> _FakeTencentSSMResponse:
        self.operations.append("get")
        return _FakeTencentSSMResponse(self.secret_string)

    def DeleteSecret(self, request: Any) -> object:
        self.operations.append("delete")
        self.force_delete_seen = bool(request.ForceDelete)
        self.secret_string = ""
        return object()


if __name__ == "__main__":
    raise SystemExit(main())
