"""Vault/KMS adapter contract for Jiejing SaaS.

This file defines the production secret-management boundary. It intentionally
does not read, write, print, or test real secret values. Local development keeps
using secret_ref records only; production can later bind this contract to
Tencent Cloud KMS, Alibaba Cloud KMS, or HashiCorp Vault.
"""

from __future__ import annotations

from typing import Any

from .config import SaaSSettings


VAULT_ADAPTERS = [
    {
        "key": "secret_ref_only",
        "display_name": "Local secret reference only",
        "deployment_fit": "local_development_only",
        "production_ready": False,
        "stores_raw_secret_in_database": False,
        "live_secret_read_supported": False,
        "live_secret_write_supported": False,
        "rotation_supported": False,
        "revocation_supported": False,
        "audit_supported": True,
        "required_config": [],
        "notes": [
            "Use this only for local MVP and contract tests.",
            "The database stores a secret_ref placeholder and redacted metadata only.",
        ],
    },
    {
        "key": "tencent_kms",
        "display_name": "Tencent Cloud KMS / Secrets Manager",
        "deployment_fit": "recommended_for_tencent_cloud",
        "production_ready": False,
        "stores_raw_secret_in_database": False,
        "live_secret_read_supported": False,
        "live_secret_write_supported": False,
        "rotation_supported": True,
        "revocation_supported": True,
        "audit_supported": True,
        "required_config": [
            "JIEJING_TENCENT_SECRET_ID_REF",
            "JIEJING_TENCENT_SECRET_KEY_REF",
            "JIEJING_TENCENT_REGION",
            "JIEJING_VAULT_KEYSPACE",
        ],
        "notes": [
            "Best fit when the formal SaaS is deployed on Tencent Cloud.",
            "Live client implementation must run only in the backend worker network.",
        ],
    },
    {
        "key": "aliyun_kms",
        "display_name": "Alibaba Cloud KMS / Secrets Manager",
        "deployment_fit": "recommended_for_aliyun",
        "production_ready": False,
        "stores_raw_secret_in_database": False,
        "live_secret_read_supported": False,
        "live_secret_write_supported": False,
        "rotation_supported": True,
        "revocation_supported": True,
        "audit_supported": True,
        "required_config": [
            "JIEJING_ALIYUN_ACCESS_KEY_ID_REF",
            "JIEJING_ALIYUN_ACCESS_KEY_SECRET_REF",
            "JIEJING_ALIYUN_REGION",
            "JIEJING_VAULT_KEYSPACE",
        ],
        "notes": [
            "Alternative managed KMS if the SaaS is deployed on Alibaba Cloud.",
            "The adapter contract remains the same as Tencent KMS.",
        ],
    },
    {
        "key": "vault",
        "display_name": "HashiCorp Vault",
        "deployment_fit": "self_managed_or_multi_cloud",
        "production_ready": False,
        "stores_raw_secret_in_database": False,
        "live_secret_read_supported": False,
        "live_secret_write_supported": False,
        "rotation_supported": True,
        "revocation_supported": True,
        "audit_supported": True,
        "required_config": [
            "JIEJING_VAULT_ADDR",
            "JIEJING_VAULT_TOKEN_REF",
            "JIEJING_VAULT_MOUNT",
            "JIEJING_VAULT_KEYSPACE",
        ],
        "notes": [
            "Useful if Jiejing needs cloud portability or self-managed secret engines.",
            "Production deployment must enable Vault audit devices and short-lived backend credentials.",
        ],
    },
]


VAULT_OPERATIONS = [
    {
        "key": "create_secret_ref",
        "label": "Create secret reference",
        "available_in_local_mvp": True,
        "returns_raw_secret": False,
        "stores_raw_secret_in_database": False,
        "audit_required": True,
    },
    {
        "key": "write_secret",
        "label": "Write real secret into Vault/KMS",
        "available_in_local_mvp": False,
        "returns_raw_secret": False,
        "stores_raw_secret_in_database": False,
        "audit_required": True,
        "blocked_until": ["managed_vault_adapter", "backend_only_write_client", "operator_audit"],
    },
    {
        "key": "resolve_task_secret",
        "label": "Resolve task-scoped secret for backend adapter",
        "available_in_local_mvp": False,
        "returns_raw_secret_to_frontend": False,
        "returns_raw_secret_to_runtime": False,
        "audit_required": True,
        "blocked_until": ["managed_vault_adapter", "backend_secret_resolver", "short_lived_access_cache"],
    },
    {
        "key": "rotate_secret",
        "label": "Rotate secret",
        "available_in_local_mvp": False,
        "returns_raw_secret": False,
        "audit_required": True,
        "blocked_until": ["managed_vault_adapter", "replacement_secret_confirmed", "old_secret_revoke_window"],
    },
    {
        "key": "revoke_secret",
        "label": "Revoke secret",
        "available_in_local_mvp": False,
        "returns_raw_secret": False,
        "audit_required": True,
        "blocked_until": ["managed_vault_adapter", "dependent_tasks_stopped", "audit_snapshot"],
    },
]


def build_vault_adapter_contract(settings: SaaSSettings) -> dict[str, Any]:
    provider = _normalize_provider(settings.vault_provider)
    base_selected = next((item for item in VAULT_ADAPTERS if item["key"] == provider), VAULT_ADAPTERS[0])
    selected = dict(base_selected)
    live_enabled = settings.vault_enabled and selected["key"] != "secret_ref_only"
    resolver_status: dict[str, Any] = {}
    if selected["key"] in {"vault", "tencent_kms"}:
        from .vault_secret_resolver import build_vault_secret_resolver_status

        resolver_status = build_vault_secret_resolver_status(settings)
    live_adapter_implemented = bool(
        selected["key"] in {"vault", "tencent_kms"}
        and resolver_status.get("managed_client_implemented")
        and resolver_status.get("managed_live_resolution_ready")
    )
    if live_adapter_implemented:
        selected.update(
            {
                "production_ready": True,
                "live_secret_read_supported": True,
                "live_secret_write_supported": True,
                "status": "implemented_for_staging",
            }
        )
    blockers = []
    if selected["key"] == "secret_ref_only":
        blockers.append("managed_vault_provider_not_selected")
    if not settings.vault_enabled:
        blockers.append("JIEJING_VAULT_ENABLED")
    if selected["key"] == "vault":
        for item in resolver_status.get("hashicorp_vault", {}).get("blocked_by") or []:
            if item not in blockers:
                blockers.append(item)
        if live_enabled and not live_adapter_implemented and "live_vault_client_not_ready" not in blockers:
            blockers.append("live_vault_client_not_ready")
    elif selected["key"] == "tencent_kms":
        for item in resolver_status.get("tencent_ssm", {}).get("blocked_by") or []:
            if item not in blockers:
                blockers.append(item)
        if live_enabled and not live_adapter_implemented and "live_tencent_ssm_client_not_ready" not in blockers:
            blockers.append("live_tencent_ssm_client_not_ready")
    elif live_enabled and not live_adapter_implemented:
        blockers.append("live_vault_client_not_implemented")
    if settings.environment == "production" and live_adapter_implemented:
        blockers.append("secret_rotation_revoke_live_client_pending")
    return {
        "selected_adapter": selected,
        "available_adapters": VAULT_ADAPTERS,
        "operations": VAULT_OPERATIONS,
        "live_enabled": live_enabled,
        "live_adapter_implemented": live_adapter_implemented,
        "contract_ready": bool(live_enabled and live_adapter_implemented and not blockers),
        "managed_live_resolution_ready": bool(resolver_status.get("managed_live_resolution_ready")),
        "resolver_status": {
            "provider": resolver_status.get("provider"),
            "status": resolver_status.get("status"),
            "managed_client_implemented": resolver_status.get("managed_client_implemented"),
            "managed_live_resolution_ready": resolver_status.get("managed_live_resolution_ready"),
            "live_secret_resolution_available": resolver_status.get("live_secret_resolution_available"),
            "secret_exposed": False,
            "tencent_ssm": {
                "provider_selected": resolver_status.get("tencent_ssm", {}).get("provider_selected"),
                "region": resolver_status.get("tencent_ssm", {}).get("region"),
                "credentials_configured": resolver_status.get("tencent_ssm", {}).get("credentials_configured"),
                "keyspace_configured": resolver_status.get("tencent_ssm", {}).get("keyspace_configured"),
                "sdk_available": resolver_status.get("tencent_ssm", {}).get("sdk_available"),
                "secret_exposed": False,
            },
        }
        if resolver_status
        else {},
        "can_store_raw_secret": bool(live_enabled and live_adapter_implemented),
        "production_blockers": blockers,
        "rules": {
            "frontend_gets_raw_secret": False,
            "database_stores_raw_secret": False,
            "runtime_gets_raw_secret": False,
            "backend_resolves_task_scoped_secret_only": True,
            "secret_access_must_write_audit_log": True,
            "rotation_and_revoke_are_backend_operations": True,
        },
        "secret_exposed": False,
    }


def build_secret_resolution_plan(
    *,
    settings: SaaSSettings,
    secret_ref: dict[str, Any] | None,
    requested_by: str,
    task_scope: str,
) -> dict[str, Any]:
    contract = build_vault_adapter_contract(settings)
    blockers = list(contract.get("production_blockers", []))
    if not secret_ref:
        blockers.append("secret_ref_not_found")
    if requested_by not in {"backend_adapter", "execution_service", "oauth_refresh_service", "queued_worker"}:
        blockers.append("requester_not_allowed")
    if not task_scope:
        blockers.append("missing_task_scope")
    return {
        "status": "resolve_ready" if not blockers else "resolve_blocked",
        "operation": "resolve_task_secret",
        "requested_by": requested_by,
        "task_scope": task_scope,
        "secret_ref": secret_ref.get("secret_ref") if secret_ref else None,
        "provider": secret_ref.get("provider") if secret_ref else None,
        "purpose": secret_ref.get("purpose") if secret_ref else None,
        "blocked_by": blockers,
        "raw_secret_returned": False,
        "frontend_gets_raw_secret": False,
        "runtime_gets_raw_secret": False,
        "database_stores_raw_secret": False,
        "audit_required": True,
        "next_step": "run_backend_secret_resolver" if not blockers else "configure_managed_vault_and_backend_resolver",
        "secret_exposed": False,
    }


def build_secret_rotation_plan(
    *,
    settings: SaaSSettings,
    secret_ref: dict[str, Any] | None,
    requested_by: str,
    reason: str,
) -> dict[str, Any]:
    contract = build_vault_adapter_contract(settings)
    blockers = list(contract.get("production_blockers", []))
    if not secret_ref:
        blockers.append("secret_ref_not_found")
    if requested_by not in {"owner", "admin", "backend_security_job"}:
        blockers.append("requester_not_allowed")
    return {
        "status": "rotation_ready" if not blockers else "rotation_blocked",
        "operation": "rotate_secret",
        "secret_ref": secret_ref.get("secret_ref") if secret_ref else None,
        "provider": secret_ref.get("provider") if secret_ref else None,
        "purpose": secret_ref.get("purpose") if secret_ref else None,
        "requested_by": requested_by,
        "reason": reason or "routine_rotation",
        "blocked_by": blockers,
        "steps": [
            "create replacement secret in managed Vault/KMS",
            "validate replacement with a read-only backend probe",
            "switch secret_ref metadata to replacement version",
            "revoke old secret after the grace window",
            "write audit log for every step",
        ],
        "raw_secret_returned": False,
        "frontend_gets_raw_secret": False,
        "runtime_gets_raw_secret": False,
        "database_stores_raw_secret": False,
        "audit_required": True,
        "secret_exposed": False,
    }


def build_secret_revoke_plan(
    *,
    settings: SaaSSettings,
    secret_ref: dict[str, Any] | None,
    requested_by: str,
    reason: str,
) -> dict[str, Any]:
    contract = build_vault_adapter_contract(settings)
    blockers = list(contract.get("production_blockers", []))
    if not secret_ref:
        blockers.append("secret_ref_not_found")
    if requested_by not in {"owner", "admin", "backend_security_job"}:
        blockers.append("requester_not_allowed")
    return {
        "status": "revoke_ready" if not blockers else "revoke_blocked",
        "operation": "revoke_secret",
        "secret_ref": secret_ref.get("secret_ref") if secret_ref else None,
        "provider": secret_ref.get("provider") if secret_ref else None,
        "purpose": secret_ref.get("purpose") if secret_ref else None,
        "requested_by": requested_by,
        "reason": reason or "security_or_disconnect",
        "blocked_by": blockers,
        "steps": [
            "stop queued jobs that depend on this secret_ref",
            "write a final redacted dependency snapshot",
            "revoke the secret in managed Vault/KMS",
            "mark the secret_ref as revoked",
            "write audit log and require re-authorization before future use",
        ],
        "raw_secret_returned": False,
        "frontend_gets_raw_secret": False,
        "runtime_gets_raw_secret": False,
        "database_stores_raw_secret": False,
        "audit_required": True,
        "secret_exposed": False,
    }


def _normalize_provider(provider: str) -> str:
    text = (provider or "").strip().lower()
    aliases = {
        "tencent": "tencent_kms",
        "tencent_cloud": "tencent_kms",
        "tencent_cloud_kms": "tencent_kms",
        "tencent_ssm": "tencent_kms",
        "ssm": "tencent_kms",
        "aliyun": "aliyun_kms",
        "alibaba_cloud": "aliyun_kms",
        "hashicorp": "vault",
        "hashicorp_vault": "vault",
        "local": "secret_ref_only",
    }
    return aliases.get(text, text or "secret_ref_only")
