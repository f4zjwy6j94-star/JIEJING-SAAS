"""Backend-only Vault/KMS client contract for Jiejing SaaS.

The local MVP does not read or write real secrets. This module defines the
production client boundary so future Tencent KMS, Aliyun KMS, or Vault clients
can be swapped in without changing frontend, Runtime, or Agent code.
"""

from __future__ import annotations

from typing import Any

from .config import SaaSSettings
from .vault_secret_resolver import build_vault_secret_resolver_status


def build_vault_client_contract(settings: SaaSSettings) -> dict[str, Any]:
    provider = (settings.vault_provider or "secret_ref_only").strip().lower()
    managed_provider_selected = provider not in {"", "secret_ref_only", "local"}
    resolver = build_vault_secret_resolver_status(settings)
    live_client_implemented = False
    blocked_by: list[str] = []
    if not settings.vault_enabled:
        blocked_by.append("JIEJING_VAULT_ENABLED")
    if not managed_provider_selected:
        blocked_by.append("managed_vault_provider_not_selected")
    if managed_provider_selected and not live_client_implemented:
        blocked_by.append("live_vault_client_not_implemented")
    return {
        "contract_version": "2026-05-15-vault-client-contract",
        "provider": provider,
        "contract_ready": True,
        "live_enabled": bool(settings.vault_enabled and managed_provider_selected),
        "live_client_implemented": live_client_implemented,
        "secret_resolver": {
            "status": resolver.get("status"),
            "local_development_enabled": resolver.get("local_development_enabled"),
            "live_secret_resolution_available": resolver.get("live_secret_resolution_available"),
            "returns_raw_secret_to_frontend": False,
            "returns_raw_secret_to_runtime": False,
            "secret_exposed": False,
        },
        "status": "ready_for_live_client_implementation" if not blocked_by else "contract_only_blocked",
        "blocked_by": blocked_by,
        "supported_providers": ["tencent_kms", "aliyun_kms", "vault"],
        "operations": [
            _operation_contract("resolve_secret", "Resolve task-scoped secret for backend adapter"),
            _operation_contract("write_secret", "Write initial secret value to managed Vault/KMS"),
            _operation_contract("rotate_secret", "Rotate a stored secret with audit trail"),
            _operation_contract("revoke_secret", "Revoke a secret and stop dependent jobs"),
        ],
        "request_contract": {
            "input": {
                "secret_ref": "opaque reference stored in database metadata",
                "purpose": "ebay_refresh_token | ebay_client_secret | model_api_key | sourcing_api_secret | logistics_api_secret",
                "requested_by": "backend_adapter | oauth_refresh_service | execution_service | queued_worker",
                "task_scope": "short task reason, never a broad all-customer scope",
                "company_id": "required",
                "store_id": "required when platform scoped",
            },
            "forbidden_input": [
                "raw token from frontend",
                "customer password",
                "whole customer database",
                "unscoped secret lookup",
            ],
        },
        "response_contract": {
            "returns_raw_secret_to_frontend": False,
            "returns_raw_secret_to_runtime": False,
            "returns_raw_secret_to_reports": False,
            "returns_secret_value_to_backend_adapter": "only inside live backend process, never persisted",
            "public_response_shape": {
                "status": "resolved | blocked | revoked | missing",
                "secret_ref": "same opaque reference",
                "lease_seconds": 300,
                "audit_id": "audit log id",
                "secret_value": "[NEVER_RETURNED_IN_PUBLIC_RESPONSE]",
            },
        },
        "lease_policy": {
            "default_lease_seconds": 300,
            "max_lease_seconds": 900,
            "cache_scope": "backend_task_only",
            "cache_in_database": False,
            "cache_in_frontend": False,
            "cache_in_runtime": False,
        },
        "audit_policy": {
            "audit_required": True,
            "record_secret_value": False,
            "record_secret_ref": True,
            "record_requester": True,
            "record_task_scope": True,
            "record_provider_status": True,
        },
        "secret_exposed": False,
    }


def build_task_secret_resolution_contract(
    *,
    settings: SaaSSettings,
    secret_ref: dict[str, Any] | None,
    requested_by: str,
    task_scope: str,
) -> dict[str, Any]:
    contract = build_vault_client_contract(settings)
    blocked_by = list(contract.get("blocked_by") or [])
    if not secret_ref:
        blocked_by.append("secret_ref_not_found")
    if requested_by not in {"backend_adapter", "oauth_refresh_service", "execution_service", "queued_worker"}:
        blocked_by.append("requester_not_allowed")
    if not task_scope:
        blocked_by.append("missing_task_scope")
    return {
        "contract_version": "2026-05-15-task-secret-resolution-contract",
        "status": "resolve_ready_for_live_client" if not blocked_by else "resolve_blocked",
        "operation": "resolve_secret",
        "provider": secret_ref.get("provider") if secret_ref else None,
        "purpose": secret_ref.get("purpose") if secret_ref else None,
        "secret_ref": secret_ref.get("secret_ref") if secret_ref else None,
        "requested_by": requested_by,
        "task_scope": task_scope,
        "blocked_by": blocked_by,
        "backend_only": True,
        "lease_seconds": contract.get("lease_policy", {}).get("default_lease_seconds"),
        "raw_secret_read": False,
        "raw_secret_returned": False,
        "frontend_gets_raw_secret": False,
        "runtime_gets_raw_secret": False,
        "reports_get_raw_secret": False,
        "database_stores_raw_secret": False,
        "audit_required": True,
        "secret_exposed": False,
    }


def _operation_contract(key: str, label: str) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "backend_only": True,
        "returns_raw_secret_to_public_response": False,
        "audit_required": True,
        "live_implemented": False,
    }
