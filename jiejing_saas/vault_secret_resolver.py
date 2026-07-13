"""Backend-only secret resolver boundary for Jiejing SaaS.

The production target is a managed KMS/Vault client. This module also provides
an explicitly enabled local-development resolver so Jiejing can validate the
secret_ref path without falling back to Hermes or putting raw secrets in SQLite,
frontend state, Runtime packets, reports, or audit logs.
"""

from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable

from .config import SaaSSettings


ALLOWED_REQUESTERS = {"backend_adapter", "oauth_refresh_service", "execution_service", "queued_worker", "model_provider_client"}
DEFAULT_LEASE_SECONDS = 300
TENCENT_SSM_PROVIDERS = {"tencent_kms", "tencent_ssm"}
SecretTransport = Callable[[urllib.request.Request, float], tuple[int, dict[str, str], bytes]]


def build_vault_secret_resolver_status(settings: SaaSSettings) -> dict[str, Any]:
    local_requested = _env_bool("JIEJING_VAULT_LOCAL_SECRET_RESOLVER_ENABLED", default=False)
    local_enabled = _local_resolver_enabled(settings)
    provider = _normalize_provider(settings.vault_provider)
    vault_config = _hashicorp_vault_config(settings)
    tencent_config = _tencent_ssm_config(settings)
    managed_provider_selected = provider not in {"", "secret_ref_only", "local"}
    managed_client_implemented = provider == "vault" or provider in TENCENT_SSM_PROVIDERS
    managed_live_ready = _managed_secret_resolver_live_ready(settings)
    blockers: list[str] = []
    if settings.is_production_like and local_requested:
        blockers.append("production_requires_managed_vault")
    if not local_enabled and not managed_provider_selected:
        blockers.append("managed_vault_provider_not_selected")
    if not local_enabled and managed_provider_selected and provider == "vault":
        blockers.extend(item for item in vault_config["blocked_by"] if item not in blockers)
    elif not local_enabled and managed_provider_selected and provider in TENCENT_SSM_PROVIDERS:
        blockers.extend(item for item in tencent_config["blocked_by"] if item not in blockers)
    elif not local_enabled and managed_provider_selected and (not settings.vault_enabled):
        blockers.append("JIEJING_VAULT_ENABLED")
    if not local_enabled and managed_provider_selected and not managed_client_implemented:
        blockers.append("managed_vault_client_not_implemented")
    live_resolution_available = bool(local_enabled or managed_live_ready)
    return {
        "resolver_version": "2026-05-15-vault-secret-resolver",
        "provider": provider,
        "status": "ready" if live_resolution_available else "contract_only_blocked",
        "local_development_requested": local_requested,
        "local_development_enabled": local_enabled,
        "managed_provider_selected": managed_provider_selected,
        "managed_client_implemented": managed_client_implemented,
        "managed_live_resolution_ready": managed_live_ready,
        "live_secret_resolution_available": live_resolution_available,
        "local_store_path_configured": bool(os.environ.get("JIEJING_VAULT_LOCAL_SECRET_STORE_PATH")),
        "local_store_path": str(_local_store_path(settings)),
        "hashicorp_vault": {
            "provider_selected": provider == "vault",
            "live_resolve_enabled": vault_config["live_resolve_enabled"],
            "addr_configured": vault_config["addr_configured"],
            "token_configured": vault_config["token_configured"],
            "mount_configured": vault_config["mount_configured"],
            "keyspace_configured": vault_config["keyspace_configured"],
            "kv_version": vault_config["kv_version"],
            "path_template_configured": vault_config["path_template_configured"],
            "blocked_by": vault_config["blocked_by"],
            "secret_exposed": False,
        },
        "tencent_ssm": {
            "provider_selected": provider in TENCENT_SSM_PROVIDERS,
            "live_resolve_enabled": tencent_config["live_resolve_enabled"],
            "live_write_enabled": tencent_config["live_write_enabled"],
            "region": tencent_config["region"],
            "region_configured": tencent_config["region_configured"],
            "credentials_configured": tencent_config["credentials_configured"],
            "temporary_token_configured": tencent_config["temporary_token_configured"],
            "keyspace_configured": tencent_config["keyspace_configured"],
            "secret_name_template_configured": tencent_config["secret_name_template_configured"],
            "kms_key_id_configured": tencent_config["kms_key_id_configured"],
            "sdk_available": tencent_config["sdk_available"],
            "blocked_by": tencent_config["blocked_by"],
            "secret_exposed": False,
        },
        "blocked_by": blockers,
        "backend_only": True,
        "returns_raw_secret_to_frontend": False,
        "returns_raw_secret_to_runtime": False,
        "returns_raw_secret_to_reports": False,
        "stores_raw_secret_in_database": False,
        "production_replacement": "Jiejing-managed Tencent KMS, Aliyun KMS, or HashiCorp Vault client",
        "secret_exposed": False,
    }


class VaultSecretResolver:
    def __init__(self, settings: SaaSSettings, *, transport: SecretTransport | None = None) -> None:
        self.settings = settings
        self.transport = transport or _urlopen_transport
        self.path = _local_store_path(settings)

    def status(self) -> dict[str, Any]:
        status = build_vault_secret_resolver_status(self.settings)
        status["local_record_count"] = len(self._read_records())
        return status

    def can_resolve_secret_values(self) -> bool:
        return bool(build_vault_secret_resolver_status(self.settings).get("live_secret_resolution_available"))

    def has_resolvable_secret(self, *, secret_ref: dict[str, Any] | None, verify_secret_value: bool = False) -> bool:
        if not secret_ref or not secret_ref.get("secret_ref"):
            return False
        if _local_resolver_enabled(self.settings):
            return self.public_record_status(secret_ref=secret_ref).get("status") == "ready"
        if not _managed_secret_resolver_live_ready(self.settings):
            return False
        if not verify_secret_value:
            return True
        resolved = self.resolve_secret(
            secret_ref=secret_ref,
            requested_by="backend_adapter",
            task_scope="secret_ref_preflight",
            allowed_purposes=[str(secret_ref.get("purpose") or "")],
        )
        return bool(resolved.get("ok"))

    def store_local_secret(
        self,
        *,
        secret_ref: dict[str, Any],
        secret_value: str,
        created_by: str,
    ) -> dict[str, Any]:
        if not _local_resolver_enabled(self.settings):
            return {"status": "blocked", "blocked_by": ["JIEJING_VAULT_LOCAL_SECRET_RESOLVER_ENABLED"], "secret_exposed": False}
        ref_id = str(secret_ref.get("secret_ref") or "").strip()
        if not ref_id:
            return {"status": "blocked_missing_secret_ref", "blocked_by": ["secret_ref_not_found"], "secret_exposed": False}
        if not secret_value:
            return {"status": "blocked_missing_secret_value", "blocked_by": ["missing_secret_value"], "secret_exposed": False}
        records = self._read_records()
        now = int(time.time())
        records[ref_id] = {
            "secret_ref": ref_id,
            "company_id": secret_ref.get("company_id"),
            "store_id": secret_ref.get("store_id"),
            "provider": secret_ref.get("provider"),
            "purpose": secret_ref.get("purpose"),
            "status": "local_development_secret_stored",
            "created_by": created_by,
            "updated_at": now,
            "secret_value": secret_value,
        }
        self._write_records(records)
        return self.public_record_status(secret_ref=secret_ref)

    def store_secret(
        self,
        *,
        secret_ref: dict[str, Any],
        secret_value: str,
        created_by: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Store a backend-only secret value in the configured resolver.

        Local development can use the explicitly enabled local resolver. In
        production-like environments, this must go through a managed Vault
        provider. The public return value never includes the raw secret.
        """

        if _local_resolver_enabled(self.settings):
            stored = self.store_local_secret(
                secret_ref=secret_ref,
                secret_value=secret_value,
                created_by=created_by,
            )
            return {
                **stored,
                "source": "backend_local_secret_resolver",
                "storage_adapter": "local_secret_resolver",
                "managed_vault_write_performed": False,
                "local_development_write_performed": stored.get("status") == "ready",
                "secret_value_returned": False,
                "secret_exposed": False,
            }
        if _hashicorp_vault_live_ready(self.settings):
            return self._write_hashicorp_vault_secret(
                secret_ref=secret_ref,
                secret_value=secret_value,
                created_by=created_by,
                metadata=metadata or {},
            )
        if _tencent_ssm_live_ready(self.settings):
            return self._write_tencent_ssm_secret(
                secret_ref=secret_ref,
                secret_value=secret_value,
                created_by=created_by,
                metadata=metadata or {},
            )
        status = build_vault_secret_resolver_status(self.settings)
        blockers = list(status.get("blocked_by") or [])
        if self.settings.is_production_like and not blockers:
            blockers.append("managed_vault_write_not_ready")
        if not blockers:
            blockers.append("secret_resolver_not_enabled")
        return {
            "status": "store_blocked",
            "secret_ref": secret_ref.get("secret_ref") if isinstance(secret_ref, dict) else None,
            "provider": secret_ref.get("provider") if isinstance(secret_ref, dict) else None,
            "purpose": secret_ref.get("purpose") if isinstance(secret_ref, dict) else None,
            "blocked_by": blockers,
            "source": "not_ready",
            "managed_vault_write_performed": False,
            "local_development_write_performed": False,
            "secret_value_returned": False,
            "secret_exposed": False,
        }

    def public_record_status(self, *, secret_ref: dict[str, Any] | None) -> dict[str, Any]:
        ref_id = str((secret_ref or {}).get("secret_ref") or "").strip()
        record = self._read_records().get(ref_id) if ref_id else None
        managed_available = bool(ref_id and _managed_secret_resolver_live_ready(self.settings))
        status = "ready" if isinstance(record, dict) and bool(record.get("secret_value")) else "ready_for_managed_resolution" if managed_available else "missing"
        return {
            "status": status,
            "secret_ref": ref_id or None,
            "provider": (secret_ref or {}).get("provider"),
            "purpose": (secret_ref or {}).get("purpose"),
            "secret_value_present": bool(isinstance(record, dict) and record.get("secret_value")),
            "managed_resolution_available": managed_available,
            "secret_value_returned": False,
            "secret_exposed": False,
        }

    def resolve_secret(
        self,
        *,
        secret_ref: dict[str, Any] | None,
        requested_by: str,
        task_scope: str,
        allowed_purposes: list[str] | None = None,
    ) -> dict[str, Any]:
        blockers = self._resolution_blockers(
            secret_ref=secret_ref,
            requested_by=requested_by,
            task_scope=task_scope,
            allowed_purposes=allowed_purposes,
        )
        if blockers:
            return {
                "ok": False,
                "status": "resolve_blocked",
                "secret_ref": (secret_ref or {}).get("secret_ref"),
                "blocked_by": blockers,
                "raw_secret_returned_to_public_response": False,
                "secret_exposed": False,
            }
        if _hashicorp_vault_live_ready(self.settings) and not _local_resolver_enabled(self.settings):
            return self._resolve_hashicorp_vault_secret(secret_ref=secret_ref)
        if _tencent_ssm_live_ready(self.settings) and not _local_resolver_enabled(self.settings):
            return self._resolve_tencent_ssm_secret(secret_ref=secret_ref)
        return self._resolve_local_secret(secret_ref=secret_ref)

    def revoke_secret(self, *, secret_ref: dict[str, Any] | None, requested_by: str, task_scope: str) -> dict[str, Any]:
        """Permanently remove a backend secret value without returning it."""

        if not secret_ref or not secret_ref.get("secret_ref"):
            return {"status": "revoke_blocked", "blocked_by": ["secret_ref_not_found"], "secret_exposed": False}
        if requested_by not in ALLOWED_REQUESTERS or not task_scope:
            return {"status": "revoke_blocked", "blocked_by": ["requester_or_scope_invalid"], "secret_exposed": False}
        if _local_resolver_enabled(self.settings):
            records = self._read_records()
            existed = records.pop(str(secret_ref["secret_ref"]), None) is not None
            self._write_records(records)
            return {
                "status": "revoked",
                "storage_adapter": "local_secret_resolver",
                "secret_ref": secret_ref.get("secret_ref"),
                "secret_value_existed": existed,
                "secret_value_returned": False,
                "secret_exposed": False,
            }
        if _hashicorp_vault_live_ready(self.settings):
            return self._revoke_hashicorp_vault_secret(secret_ref=secret_ref)
        if _tencent_ssm_live_ready(self.settings):
            return self._revoke_tencent_ssm_secret(secret_ref=secret_ref)
        return {
            "status": "revoke_blocked",
            "secret_ref": secret_ref.get("secret_ref"),
            "blocked_by": ["managed_vault_revoke_not_ready"],
            "secret_value_returned": False,
            "secret_exposed": False,
        }

    def _revoke_hashicorp_vault_secret(self, *, secret_ref: dict[str, Any]) -> dict[str, Any]:
        config = _hashicorp_vault_config(self.settings)
        mount = urllib.parse.quote(str(config["mount"]).strip("/"), safe="")
        path = _hashicorp_secret_path(config=config, secret_ref=secret_ref)
        prefix = "metadata/" if config["kv_version"] == "v2" else ""
        request = urllib.request.Request(
            f"{str(config['addr']).rstrip('/')}/v1/{mount}/{prefix}{path}",
            headers={"X-Vault-Token": _hashicorp_vault_token(), "Accept": "application/json"},
            method="DELETE",
        )
        try:
            status, _headers, _raw = self.transport(request, 20)
        except Exception as exc:  # pragma: no cover - live provider dependent
            return {
                "status": "revoke_blocked", "blocked_by": ["managed_vault_http_error"],
                "error_type": type(exc).__name__, "secret_value_returned": False, "secret_exposed": False,
            }
        return {
            "status": "revoked" if status < 400 or status == 404 else "revoke_blocked",
            "storage_adapter": "managed_hashicorp_vault",
            "secret_ref": secret_ref.get("secret_ref"),
            "http_status": status,
            "secret_value_returned": False,
            "secret_exposed": False,
        }

    def _revoke_tencent_ssm_secret(self, *, secret_ref: dict[str, Any]) -> dict[str, Any]:
        config = _tencent_ssm_config(self.settings)
        try:
            client = _build_tencent_ssm_client(config)
            request = _new_tencent_ssm_request("DeleteSecretRequest")
            setattr(request, "SecretName", _tencent_secret_name(config=config, secret_ref=secret_ref))
            setattr(request, "ForceDelete", True)
            client.DeleteSecret(request)
        except Exception as exc:  # pragma: no cover - live provider dependent
            if not _looks_like_tencent_secret_missing(exc):
                return {
                    "status": "revoke_blocked", "blocked_by": ["tencent_ssm_revoke_failed"],
                    "error_type": type(exc).__name__, "secret_value_returned": False, "secret_exposed": False,
                }
        return {
            "status": "revoked",
            "storage_adapter": "managed_tencent_ssm",
            "secret_ref": secret_ref.get("secret_ref"),
            "secret_value_returned": False,
            "secret_exposed": False,
        }

    def _resolve_local_secret(self, *, secret_ref: dict[str, Any]) -> dict[str, Any]:
        record = self._read_records().get(str(secret_ref["secret_ref"]))
        if not isinstance(record, dict) or not record.get("secret_value"):
            return {
                "ok": False,
                "status": "resolve_blocked",
                "secret_ref": secret_ref.get("secret_ref"),
                "blocked_by": ["local_secret_record_missing"],
                "raw_secret_returned_to_public_response": False,
                "secret_exposed": False,
            }
        return {
            "ok": True,
            "status": "resolved",
            "source": "backend_local_secret_resolver",
            "secret_ref": secret_ref.get("secret_ref"),
            "provider": secret_ref.get("provider"),
            "purpose": secret_ref.get("purpose"),
            "secret_value": str(record["secret_value"]),
            "lease_seconds": DEFAULT_LEASE_SECONDS,
            "backend_only": True,
            "raw_secret_returned_to_public_response": False,
            "frontend_gets_raw_secret": False,
            "runtime_gets_raw_secret": False,
            "reports_get_raw_secret": False,
            "database_stores_raw_secret": False,
            "secret_exposed": False,
        }

    def _resolve_hashicorp_vault_secret(self, *, secret_ref: dict[str, Any]) -> dict[str, Any]:
        config = _hashicorp_vault_config(self.settings)
        vault_token = _hashicorp_vault_token()
        path = _hashicorp_secret_path(config=config, secret_ref=secret_ref)
        mount = urllib.parse.quote(str(config["mount"]).strip("/"), safe="")
        prefix = "data/" if config["kv_version"] == "v2" else ""
        url = f"{str(config['addr']).rstrip('/')}/v1/{mount}/{prefix}{path}"
        request = urllib.request.Request(
            url,
            headers={
                "X-Vault-Token": vault_token,
                "Accept": "application/json",
            },
            method="GET",
        )
        try:
            status, _headers, raw = self.transport(request, 20)
            data = json.loads(raw.decode("utf-8")) if raw else {}
        except Exception as exc:  # pragma: no cover - live provider dependent
            return {
                "ok": False,
                "status": "resolve_blocked",
                "secret_ref": secret_ref.get("secret_ref"),
                "blocked_by": ["managed_vault_http_error"],
                "error_type": type(exc).__name__,
                "raw_secret_returned_to_public_response": False,
                "secret_exposed": False,
            }
        if status >= 400 or not isinstance(data, dict):
            return {
                "ok": False,
                "status": "resolve_blocked",
                "secret_ref": secret_ref.get("secret_ref"),
                "blocked_by": ["managed_vault_resolve_failed"],
                "http_status": status,
                "raw_secret_returned_to_public_response": False,
                "secret_exposed": False,
            }
        payload = data.get("data") if isinstance(data.get("data"), dict) else {}
        if config["kv_version"] == "v2":
            payload = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        secret_value = _extract_secret_value(payload=payload, purpose=str(secret_ref.get("purpose") or ""), configured_field=str(config["secret_field"] or ""))
        if not secret_value:
            return {
                "ok": False,
                "status": "resolve_blocked",
                "secret_ref": secret_ref.get("secret_ref"),
                "blocked_by": ["managed_vault_secret_value_missing"],
                "http_status": status,
                "raw_secret_returned_to_public_response": False,
                "secret_exposed": False,
            }
        return {
            "ok": True,
            "status": "resolved",
            "source": "backend_hashicorp_vault_secret_resolver",
            "secret_ref": secret_ref.get("secret_ref"),
            "provider": secret_ref.get("provider"),
            "purpose": secret_ref.get("purpose"),
            "secret_value": secret_value,
            "lease_seconds": DEFAULT_LEASE_SECONDS,
            "backend_only": True,
            "raw_secret_returned_to_public_response": False,
            "frontend_gets_raw_secret": False,
            "runtime_gets_raw_secret": False,
            "reports_get_raw_secret": False,
            "database_stores_raw_secret": False,
            "secret_exposed": False,
        }

    def _write_hashicorp_vault_secret(
        self,
        *,
        secret_ref: dict[str, Any],
        secret_value: str,
        created_by: str,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        config = _hashicorp_vault_config(self.settings)
        vault_token = _hashicorp_vault_token()
        path = _hashicorp_secret_path(config=config, secret_ref=secret_ref)
        mount = urllib.parse.quote(str(config["mount"]).strip("/"), safe="")
        prefix = "data/" if config["kv_version"] == "v2" else ""
        url = f"{str(config['addr']).rstrip('/')}/v1/{mount}/{prefix}{path}"
        field = _secret_field_for_purpose(
            purpose=str(secret_ref.get("purpose") or ""),
            configured_field=str(config["secret_field"] or ""),
        )
        payload = {
            field: secret_value,
            "purpose": secret_ref.get("purpose"),
            "provider": secret_ref.get("provider"),
            "updated_at": int(time.time()),
            "created_by": created_by,
            "metadata": _public_metadata(metadata),
        }
        body = {"data": payload} if config["kv_version"] == "v2" else payload
        request = urllib.request.Request(
            url,
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={
                "X-Vault-Token": vault_token,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            status, _headers, _raw = self.transport(request, 20)
        except Exception as exc:  # pragma: no cover - live provider dependent
            return {
                "status": "store_blocked",
                "secret_ref": secret_ref.get("secret_ref"),
                "provider": secret_ref.get("provider"),
                "purpose": secret_ref.get("purpose"),
                "blocked_by": ["managed_vault_http_error"],
                "error_type": type(exc).__name__,
                "managed_vault_write_performed": False,
                "secret_value_returned": False,
                "secret_exposed": False,
            }
        if status >= 400:
            return {
                "status": "store_blocked",
                "secret_ref": secret_ref.get("secret_ref"),
                "provider": secret_ref.get("provider"),
                "purpose": secret_ref.get("purpose"),
                "blocked_by": ["managed_vault_write_failed"],
                "http_status": status,
                "managed_vault_write_performed": False,
                "secret_value_returned": False,
                "secret_exposed": False,
            }
        return {
            "status": "stored",
            "secret_ref": secret_ref.get("secret_ref"),
            "provider": secret_ref.get("provider"),
            "purpose": secret_ref.get("purpose"),
            "source": "backend_hashicorp_vault_secret_resolver",
            "storage_adapter": "managed_hashicorp_vault",
            "managed_vault_write_performed": True,
            "local_development_write_performed": False,
            "http_status": status,
            "secret_value_returned": False,
            "frontend_gets_raw_secret": False,
            "runtime_gets_raw_secret": False,
            "reports_get_raw_secret": False,
            "database_stores_raw_secret": False,
            "secret_exposed": False,
        }

    def _resolve_tencent_ssm_secret(self, *, secret_ref: dict[str, Any]) -> dict[str, Any]:
        config = _tencent_ssm_config(self.settings)
        secret_name = _tencent_secret_name(config=config, secret_ref=secret_ref)
        try:
            client = _build_tencent_ssm_client(config)
            version_id = _tencent_latest_secret_version_id(client=client, secret_name=secret_name)
            request = _new_tencent_ssm_request("GetSecretValueRequest")
            setattr(request, "SecretName", secret_name)
            if version_id:
                setattr(request, "VersionId", version_id)
            response = client.GetSecretValue(request)
            secret_string = _tencent_response_value(response, "SecretString")
            payload = _decode_secret_payload(secret_string)
        except Exception as exc:  # pragma: no cover - live provider dependent
            return {
                "ok": False,
                "status": "resolve_blocked",
                "secret_ref": secret_ref.get("secret_ref"),
                "blocked_by": ["tencent_ssm_resolve_failed"],
                "error_type": type(exc).__name__,
                "raw_secret_returned_to_public_response": False,
                "secret_exposed": False,
            }
        secret_value = _extract_secret_value(
            payload=payload,
            purpose=str(secret_ref.get("purpose") or ""),
            configured_field=str(config["secret_field"] or ""),
        )
        if not secret_value:
            return {
                "ok": False,
                "status": "resolve_blocked",
                "secret_ref": secret_ref.get("secret_ref"),
                "blocked_by": ["tencent_ssm_secret_value_missing"],
                "raw_secret_returned_to_public_response": False,
                "secret_exposed": False,
            }
        return {
            "ok": True,
            "status": "resolved",
            "source": "backend_tencent_ssm_secret_resolver",
            "secret_ref": secret_ref.get("secret_ref"),
            "provider": secret_ref.get("provider"),
            "purpose": secret_ref.get("purpose"),
            "secret_value": secret_value,
            "lease_seconds": DEFAULT_LEASE_SECONDS,
            "backend_only": True,
            "raw_secret_returned_to_public_response": False,
            "frontend_gets_raw_secret": False,
            "runtime_gets_raw_secret": False,
            "reports_get_raw_secret": False,
            "database_stores_raw_secret": False,
            "secret_exposed": False,
        }

    def _write_tencent_ssm_secret(
        self,
        *,
        secret_ref: dict[str, Any],
        secret_value: str,
        created_by: str,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        config = _tencent_ssm_config(self.settings)
        if not config["live_write_enabled"]:
            return {
                "status": "store_blocked",
                "secret_ref": secret_ref.get("secret_ref"),
                "provider": secret_ref.get("provider"),
                "purpose": secret_ref.get("purpose"),
                "blocked_by": ["JIEJING_TENCENT_SSM_LIVE_WRITE_ENABLED"],
                "managed_vault_write_performed": False,
                "secret_value_returned": False,
                "secret_exposed": False,
            }
        secret_name = _tencent_secret_name(config=config, secret_ref=secret_ref)
        field = _secret_field_for_purpose(
            purpose=str(secret_ref.get("purpose") or ""),
            configured_field=str(config["secret_field"] or ""),
        )
        payload = {
            field: secret_value,
            "purpose": secret_ref.get("purpose"),
            "provider": secret_ref.get("provider"),
            "updated_at": int(time.time()),
            "created_by": created_by,
            "metadata": _public_metadata(metadata),
        }
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        version_id = "v" + str(int(time.time()))
        try:
            client = _build_tencent_ssm_client(config)
            put_request = _new_tencent_ssm_request("PutSecretValueRequest")
            setattr(put_request, "SecretName", secret_name)
            setattr(put_request, "VersionId", version_id)
            setattr(put_request, "SecretString", body)
            try:
                client.PutSecretValue(put_request)
                operation = "put_secret_value"
            except Exception as exc:
                if not _looks_like_tencent_secret_missing(exc):
                    raise
                create_request = _new_tencent_ssm_request("CreateSecretRequest")
                setattr(create_request, "SecretName", secret_name)
                setattr(create_request, "VersionId", version_id)
                setattr(create_request, "SecretString", body)
                setattr(create_request, "Description", "Jiejing backend-only secret_ref; raw value never stored in SaaS database")
                if config.get("kms_key_id"):
                    setattr(create_request, "KmsKeyId", str(config["kms_key_id"]))
                client.CreateSecret(create_request)
                operation = "create_secret"
        except Exception as exc:  # pragma: no cover - live provider dependent
            return {
                "status": "store_blocked",
                "secret_ref": secret_ref.get("secret_ref"),
                "provider": secret_ref.get("provider"),
                "purpose": secret_ref.get("purpose"),
                "blocked_by": ["tencent_ssm_write_failed"],
                "error_type": type(exc).__name__,
                "managed_vault_write_performed": False,
                "secret_value_returned": False,
                "secret_exposed": False,
            }
        return {
            "status": "stored",
            "secret_ref": secret_ref.get("secret_ref"),
            "provider": secret_ref.get("provider"),
            "purpose": secret_ref.get("purpose"),
            "source": "backend_tencent_ssm_secret_resolver",
            "storage_adapter": "managed_tencent_ssm",
            "operation": operation,
            "managed_vault_write_performed": True,
            "local_development_write_performed": False,
            "secret_value_returned": False,
            "frontend_gets_raw_secret": False,
            "runtime_gets_raw_secret": False,
            "reports_get_raw_secret": False,
            "database_stores_raw_secret": False,
            "secret_exposed": False,
        }

    def _resolution_blockers(
        self,
        *,
        secret_ref: dict[str, Any] | None,
        requested_by: str,
        task_scope: str,
        allowed_purposes: list[str] | None,
    ) -> list[str]:
        blockers: list[str] = []
        if not secret_ref or not secret_ref.get("secret_ref"):
            blockers.append("secret_ref_not_found")
        if requested_by not in ALLOWED_REQUESTERS:
            blockers.append("requester_not_allowed")
        if not task_scope:
            blockers.append("missing_task_scope")
        purpose = str((secret_ref or {}).get("purpose") or "").strip()
        if allowed_purposes and purpose not in set(allowed_purposes):
            blockers.append("purpose_not_allowed_for_task")
        status = build_vault_secret_resolver_status(self.settings)
        if not status.get("live_secret_resolution_available"):
            blockers.extend(item for item in status.get("blocked_by", []) if item not in blockers)
            if not status.get("blocked_by"):
                blockers.append("secret_resolver_not_enabled")
        return blockers

    def _read_records(self) -> dict[str, dict[str, Any]]:
        try:
            if not self.path.exists():
                return {}
            data = json.loads(self.path.read_text(encoding="utf-8"))
            records = data.get("secrets") if isinstance(data, dict) else {}
            return records if isinstance(records, dict) else {}
        except Exception:
            return {}

    def _write_records(self, records: dict[str, dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "store_version": "2026-05-15-local-vault-secret-resolver",
            "warning": "Local development only. Do not commit or use in production.",
            "secrets": records,
        }
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        tmp.replace(self.path)


def _local_resolver_enabled(settings: SaaSSettings) -> bool:
    return (not settings.is_production_like) and _env_bool("JIEJING_VAULT_LOCAL_SECRET_RESOLVER_ENABLED", default=False)


def _normalize_provider(provider: str) -> str:
    text = (provider or "").strip().lower()
    aliases = {
        "tencent": "tencent_kms",
        "tencent_cloud": "tencent_kms",
        "tencent_cloud_kms": "tencent_kms",
        "tencent_secrets_manager": "tencent_kms",
        "ssm": "tencent_ssm",
        "tencent_ssm": "tencent_ssm",
        "hashicorp": "vault",
        "hashicorp_vault": "vault",
        "local": "secret_ref_only",
    }
    return aliases.get(text, text or "secret_ref_only")


def _local_store_path(settings: SaaSSettings) -> Path:
    configured = os.environ.get("JIEJING_VAULT_LOCAL_SECRET_STORE_PATH")
    if configured:
        return Path(configured)
    return settings.output_root / "secrets" / "local_secret_values.json"


def _hashicorp_vault_config(settings: SaaSSettings) -> dict[str, Any]:
    provider = (settings.vault_provider or "secret_ref_only").strip().lower()
    addr = os.environ.get("JIEJING_VAULT_ADDR") or os.environ.get("VAULT_ADDR") or ""
    token_configured = bool(_hashicorp_vault_token())
    mount = os.environ.get("JIEJING_VAULT_MOUNT") or "secret"
    keyspace = os.environ.get("JIEJING_VAULT_KEYSPACE") or ""
    live_resolve_enabled = _env_bool("JIEJING_VAULT_LIVE_RESOLVE_ENABLED", default=False)
    kv_version = (os.environ.get("JIEJING_VAULT_KV_VERSION") or "v2").strip().lower()
    blocked_by: list[str] = []
    if provider == "vault":
        if not settings.vault_enabled:
            blocked_by.append("JIEJING_VAULT_ENABLED")
        if not live_resolve_enabled:
            blocked_by.append("JIEJING_VAULT_LIVE_RESOLVE_ENABLED")
        if not addr:
            blocked_by.append("JIEJING_VAULT_ADDR")
        if not token_configured:
            blocked_by.append("JIEJING_VAULT_TOKEN")
        if not mount:
            blocked_by.append("JIEJING_VAULT_MOUNT")
        if not keyspace:
            blocked_by.append("JIEJING_VAULT_KEYSPACE")
        if kv_version not in {"v1", "v2"}:
            blocked_by.append("JIEJING_VAULT_KV_VERSION")
    return {
        "provider": provider,
        "addr": addr,
        "mount": mount,
        "keyspace": keyspace,
        "secret_field": os.environ.get("JIEJING_VAULT_SECRET_FIELD") or "",
        "path_template": os.environ.get("JIEJING_VAULT_PATH_TEMPLATE") or "{keyspace}/{company_id}/{store_id}/{secret_ref}",
        "path_template_configured": bool(os.environ.get("JIEJING_VAULT_PATH_TEMPLATE")),
        "live_resolve_enabled": live_resolve_enabled,
        "kv_version": kv_version,
        "addr_configured": bool(addr),
        "token_configured": token_configured,
        "mount_configured": bool(mount),
        "keyspace_configured": bool(keyspace),
        "blocked_by": blocked_by,
    }


def _hashicorp_vault_token() -> str:
    return os.environ.get("JIEJING_VAULT_TOKEN") or os.environ.get("VAULT_TOKEN") or ""


def _hashicorp_vault_live_ready(settings: SaaSSettings) -> bool:
    config = _hashicorp_vault_config(settings)
    return config["provider"] == "vault" and not config["blocked_by"]


def _tencent_ssm_config(settings: SaaSSettings) -> dict[str, Any]:
    provider = _normalize_provider(settings.vault_provider)
    region = os.environ.get("JIEJING_TENCENT_REGION") or os.environ.get("TENCENTCLOUD_REGION") or "ap-guangzhou"
    keyspace = os.environ.get("JIEJING_TENCENT_SSM_KEYSPACE") or os.environ.get("JIEJING_VAULT_KEYSPACE") or ""
    live_resolve_enabled = _env_bool("JIEJING_TENCENT_SSM_LIVE_RESOLVE_ENABLED", default=False) or _env_bool(
        "JIEJING_VAULT_LIVE_RESOLVE_ENABLED",
        default=False,
    )
    live_write_enabled = _env_bool("JIEJING_TENCENT_SSM_LIVE_WRITE_ENABLED", default=live_resolve_enabled)
    secret_id_configured = bool(_tencent_secret_id())
    secret_key_configured = bool(_tencent_secret_key())
    token_configured = bool(_tencent_token())
    credentials_configured = secret_id_configured and secret_key_configured
    sdk_available = _tencent_ssm_sdk_available()
    blocked_by: list[str] = []
    if provider in TENCENT_SSM_PROVIDERS:
        if not settings.vault_enabled:
            blocked_by.append("JIEJING_VAULT_ENABLED")
        if not live_resolve_enabled:
            blocked_by.append("JIEJING_TENCENT_SSM_LIVE_RESOLVE_ENABLED")
        if not region:
            blocked_by.append("JIEJING_TENCENT_REGION")
        if not keyspace:
            blocked_by.append("JIEJING_TENCENT_SSM_KEYSPACE")
        if not credentials_configured:
            blocked_by.append("TENCENTCLOUD_SECRET_ID_AND_KEY")
        if not sdk_available:
            blocked_by.append("tencentcloud-sdk-python-ssm")
    return {
        "provider": provider,
        "region": region,
        "keyspace": keyspace,
        "secret_field": os.environ.get("JIEJING_TENCENT_SSM_SECRET_FIELD") or os.environ.get("JIEJING_VAULT_SECRET_FIELD") or "",
        "secret_name_template": os.environ.get("JIEJING_TENCENT_SSM_SECRET_NAME_TEMPLATE")
        or "{keyspace}-{company_id}-{store_id}-{purpose}-{secret_ref}",
        "secret_name_template_configured": bool(os.environ.get("JIEJING_TENCENT_SSM_SECRET_NAME_TEMPLATE")),
        "kms_key_id": os.environ.get("JIEJING_TENCENT_KMS_KEY_ID") or "",
        "kms_key_id_configured": bool(os.environ.get("JIEJING_TENCENT_KMS_KEY_ID")),
        "live_resolve_enabled": live_resolve_enabled,
        "live_write_enabled": live_write_enabled,
        "region_configured": bool(region),
        "secret_id_configured": secret_id_configured,
        "secret_key_configured": secret_key_configured,
        "temporary_token_configured": token_configured,
        "credentials_configured": credentials_configured,
        "keyspace_configured": bool(keyspace),
        "sdk_available": sdk_available,
        "blocked_by": blocked_by,
    }


def _tencent_ssm_live_ready(settings: SaaSSettings) -> bool:
    config = _tencent_ssm_config(settings)
    return config["provider"] in TENCENT_SSM_PROVIDERS and not config["blocked_by"]


def _managed_secret_resolver_live_ready(settings: SaaSSettings) -> bool:
    return _hashicorp_vault_live_ready(settings) or _tencent_ssm_live_ready(settings)


def _hashicorp_secret_path(*, config: dict[str, Any], secret_ref: dict[str, Any]) -> str:
    context = {
        "keyspace": str(config.get("keyspace") or ""),
        "company_id": str(secret_ref.get("company_id") or "company"),
        "store_id": str(secret_ref.get("store_id") or "store"),
        "provider": str(secret_ref.get("provider") or "provider"),
        "purpose": str(secret_ref.get("purpose") or "purpose"),
        "secret_ref": str(secret_ref.get("secret_ref") or ""),
    }
    template = str(config.get("path_template") or "{keyspace}/{company_id}/{store_id}/{secret_ref}")
    try:
        raw_path = template.format(**context)
    except KeyError:
        raw_path = "{keyspace}/{company_id}/{store_id}/{secret_ref}".format(**context)
    return "/".join(urllib.parse.quote(part, safe="") for part in raw_path.strip("/").split("/") if part)


def _tencent_secret_name(*, config: dict[str, Any], secret_ref: dict[str, Any]) -> str:
    context = {
        "keyspace": str(config.get("keyspace") or "jiejing"),
        "company_id": str(secret_ref.get("company_id") or "company"),
        "store_id": str(secret_ref.get("store_id") or "store"),
        "provider": str(secret_ref.get("provider") or "provider"),
        "purpose": str(secret_ref.get("purpose") or "purpose"),
        "secret_ref": str(secret_ref.get("secret_ref") or ""),
    }
    template = str(config.get("secret_name_template") or "{keyspace}-{company_id}-{store_id}-{purpose}-{secret_ref}")
    try:
        raw_name = template.format(**context)
    except KeyError:
        raw_name = "{keyspace}-{company_id}-{store_id}-{purpose}-{secret_ref}".format(**context)
    return _sanitize_tencent_secret_name(raw_name)


def _sanitize_tencent_secret_name(value: str) -> str:
    cleaned = []
    for char in value.strip():
        if char.isalnum() or char in {"_", "-", "."}:
            cleaned.append(char)
        else:
            cleaned.append("-")
    name = "".join(cleaned).strip("-._")
    while "--" in name:
        name = name.replace("--", "-")
    return (name or "jiejing-secret")[:128]


def _decode_secret_payload(secret_string: str) -> dict[str, Any]:
    if not secret_string:
        return {}
    try:
        payload = json.loads(secret_string)
    except json.JSONDecodeError:
        return {"secret_value": secret_string}
    return payload if isinstance(payload, dict) else {"secret_value": str(payload)}


def _tencent_response_value(response: Any, key: str) -> str:
    value = getattr(response, key, "")
    if isinstance(value, str):
        return value
    to_json = getattr(response, "to_json_string", None)
    if callable(to_json):
        try:
            data = json.loads(to_json())
            maybe = data.get(key)
            return maybe if isinstance(maybe, str) else ""
        except Exception:
            return ""
    return ""


def _new_tencent_ssm_request(model_name: str) -> Any:
    try:
        from tencentcloud.ssm.v20190923 import models  # type: ignore

        return getattr(models, model_name)()
    except Exception:
        class _Request:
            pass

        return _Request()


def _tencent_latest_secret_version_id(*, client: Any, secret_name: str) -> str:
    request = _new_tencent_ssm_request("ListSecretVersionIdsRequest")
    setattr(request, "SecretName", secret_name)
    try:
        response = client.ListSecretVersionIds(request)
    except Exception:
        return ""
    to_json = getattr(response, "to_json_string", None)
    if not callable(to_json):
        return ""
    try:
        data = json.loads(to_json())
    except Exception:
        return ""
    versions = data.get("Versions")
    if not isinstance(versions, list) or not versions:
        return ""
    candidates: list[dict[str, Any]] = [
        item for item in versions if isinstance(item, dict) and item.get("VersionId")
    ]
    if not candidates:
        return ""
    candidates.sort(key=lambda item: int(item.get("CreateTime") or 0), reverse=True)
    return str(candidates[0].get("VersionId") or "")


def _build_tencent_ssm_client(config: dict[str, Any]) -> Any:
    from tencentcloud.common import credential  # type: ignore
    from tencentcloud.common.profile.client_profile import ClientProfile  # type: ignore
    from tencentcloud.common.profile.http_profile import HttpProfile  # type: ignore
    from tencentcloud.ssm.v20190923 import ssm_client  # type: ignore

    cred = credential.Credential(_tencent_secret_id(), _tencent_secret_key(), _tencent_token() or None)
    http_profile = HttpProfile()
    http_profile.endpoint = "ssm.tencentcloudapi.com"
    client_profile = ClientProfile()
    client_profile.httpProfile = http_profile
    return ssm_client.SsmClient(cred, str(config["region"]), client_profile)


def _tencent_ssm_sdk_available() -> bool:
    try:
        from tencentcloud.ssm.v20190923 import ssm_client  # noqa: F401

        return True
    except Exception:
        return False


def _looks_like_tencent_secret_missing(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(marker in text for marker in ("resourcenotfound", "resource not found", "notfound", "secretnotexist", "not exist"))


def _tencent_secret_id() -> str:
    return os.environ.get("JIEJING_TENCENT_SECRET_ID") or os.environ.get("TENCENTCLOUD_SECRET_ID") or ""


def _tencent_secret_key() -> str:
    return os.environ.get("JIEJING_TENCENT_SECRET_KEY") or os.environ.get("TENCENTCLOUD_SECRET_KEY") or ""


def _tencent_token() -> str:
    return os.environ.get("JIEJING_TENCENT_TOKEN") or os.environ.get("TENCENTCLOUD_TOKEN") or ""


def _extract_secret_value(*, payload: dict[str, Any], purpose: str, configured_field: str) -> str:
    fields = []
    if configured_field:
        fields.append(configured_field)
    if purpose == "ebay_refresh_token":
        fields.append("refresh_token")
    fields.extend(["secret_value", "value", "token", "api_key"])
    for field in fields:
        value = payload.get(field)
        if isinstance(value, str) and value:
            return value
    return ""


def _secret_field_for_purpose(*, purpose: str, configured_field: str) -> str:
    if configured_field:
        return configured_field
    if purpose == "ebay_refresh_token":
        return "refresh_token"
    if purpose == "ebay_client_secret":
        return "client_secret"
    return "secret_value"


def _public_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in metadata.items():
        lower = str(key).lower()
        if any(marker in lower for marker in ("secret", "token", "password", "api_key", "apikey", "authorization", "cookie")):
            out[key] = "[REDACTED]"
        elif isinstance(value, dict):
            out[key] = _public_metadata(value)
        elif isinstance(value, list):
            out[key] = [
                _public_metadata(item) if isinstance(item, dict) else item
                for item in value
            ]
        else:
            out[key] = value
    return out


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _urlopen_transport(request: urllib.request.Request, timeout: float) -> tuple[int, dict[str, str], bytes]:
    with urllib.request.urlopen(request, timeout=timeout) as response:
        headers = {key: value for key, value in response.headers.items()}
        return int(response.status), headers, response.read()
