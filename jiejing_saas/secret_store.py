"""Secret-store boundary for the formal Jiejing SaaS backend.

The local MVP must never persist raw platform tokens. It only records
secret_ref metadata so the front end can see that a credential exists elsewhere.
Production should replace this with Tencent Cloud KMS, Alibaba Cloud KMS, Vault,
or another managed secret store.
"""

from __future__ import annotations

from typing import Any

from .config import SaaSSettings
from .vault_adapter import (
    build_secret_resolution_plan,
    build_secret_revoke_plan,
    build_secret_rotation_plan,
    build_vault_adapter_contract,
)
from .vault_secret_resolver import build_vault_secret_resolver_status


SECRET_MARKERS = ("secret", "token", "password", "api_key", "apikey", "refresh")

VAULT_TARGETS = [
    {
        "key": "tencent_kms",
        "display_name": "Tencent Cloud KMS / Secrets Manager",
        "deployment_fit": "recommended_for_tencent_cloud",
        "stores_raw_secret_in_database": False,
        "production_use": "Store eBay, model, sourcing, logistics, and media provider secrets outside the SaaS database.",
    },
    {
        "key": "aliyun_kms",
        "display_name": "Alibaba Cloud KMS / Secrets Manager",
        "deployment_fit": "recommended_for_aliyun",
        "stores_raw_secret_in_database": False,
        "production_use": "Alternative managed cloud KMS for China-region deployment.",
    },
    {
        "key": "vault",
        "display_name": "HashiCorp Vault",
        "deployment_fit": "cloud_or_self_managed",
        "stores_raw_secret_in_database": False,
        "production_use": "Central secret engine with audit, leases, rotation, and policy control.",
    },
]

SECRET_PURPOSES = {
    "ebay_client_secret": {
        "label": "eBay app client secret",
        "provider_family": "sales_channel",
        "rotation_days": 180,
        "live_use": "OAuth code exchange and refresh-token renewal.",
    },
    "ebay_refresh_token": {
        "label": "eBay seller refresh token",
        "provider_family": "sales_channel",
        "rotation_days": 365,
        "live_use": "Renew short-lived eBay access tokens for read-only and confirmed execution tasks.",
    },
    "model_api_key": {
        "label": "Model provider API key",
        "provider_family": "ai_model",
        "rotation_days": 90,
        "live_use": "Run Jiejing-owned agents and fallback model calls.",
    },
    "public_search_api_key": {
        "label": "Public search provider API key",
        "provider_family": "research_tool",
        "rotation_days": 90,
        "live_use": "Power market data packet and public-web evidence search.",
    },
    "media_generation_api_key": {
        "label": "Image/video generation API key",
        "provider_family": "creative_tool",
        "rotation_days": 90,
        "live_use": "Generate product images, detail images, scene images, and video assets.",
    },
    "sourcing_api_secret": {
        "label": "Sourcing platform API secret",
        "provider_family": "sourcing_channel",
        "rotation_days": 180,
        "live_use": "Read product, price, stock, supplier, and logistics facts from 1688 or other sourcing platforms.",
    },
    "logistics_api_secret": {
        "label": "Logistics provider API secret",
        "provider_family": "fulfillment_channel",
        "rotation_days": 180,
        "live_use": "Read shipping quotes, labels, tracking, and fulfillment status.",
    },
    "storefront_api_secret": {
        "label": "Future storefront/sales-channel secret",
        "provider_family": "future_sales_channel",
        "rotation_days": 180,
        "live_use": "Reserved for Amazon, Shopify, Alibaba, AliExpress, or other future adapters.",
    },
}


class SecretStoreBoundary:
    def __init__(self, settings: SaaSSettings) -> None:
        self.settings = settings

    def status(self) -> dict[str, Any]:
        can_store_raw_secret = self.settings.vault_enabled and self.settings.vault_provider != "secret_ref_only"
        resolver = build_vault_secret_resolver_status(self.settings)
        return {
            "provider": self.settings.vault_provider,
            "enabled": self.settings.vault_enabled,
            "can_store_raw_secret": can_store_raw_secret,
            "can_resolve_task_secret": bool(resolver.get("live_secret_resolution_available")),
            "mode": "external_vault_required" if not can_store_raw_secret else "managed_vault_configured",
            "secret_ref_only": not can_store_raw_secret,
            "production_ready": can_store_raw_secret,
            "secret_resolver": {
                "status": resolver.get("status"),
                "local_development_enabled": resolver.get("local_development_enabled"),
                "managed_client_implemented": resolver.get("managed_client_implemented"),
                "live_secret_resolution_available": resolver.get("live_secret_resolution_available"),
                "secret_exposed": False,
            },
            "supported_production_targets": [target["key"] for target in VAULT_TARGETS],
            "target_count": len(VAULT_TARGETS),
            "purpose_count": len(SECRET_PURPOSES),
            "rules": [
                "front end never receives raw tokens",
                "database stores secret_ref and metadata only",
                "runtime receives only the minimum task-scoped data",
                "real token refresh and rotation belongs in backend/Vault, not in the browser",
            ],
            "secret_exposed": False,
        }

    def targets(self) -> dict[str, Any]:
        return {
            "targets": VAULT_TARGETS,
            "purposes": [
                {"key": key, **value}
                for key, value in sorted(SECRET_PURPOSES.items())
            ],
            "default_provider": self.settings.vault_provider,
            "enabled": self.settings.vault_enabled,
            "can_store_raw_secret": self.status()["can_store_raw_secret"],
            "secret_exposed": False,
        }

    def adapter_contract(self) -> dict[str, Any]:
        return build_vault_adapter_contract(self.settings)

    def classify_input(self, payload: dict[str, Any]) -> dict[str, Any]:
        raw_secret_keys = [key for key in payload if _looks_secret_key(key)]
        return {
            "raw_secret_input_seen": bool(raw_secret_keys),
            "raw_secret_key_count": len(raw_secret_keys),
            "secret_value_stored": False,
            "storage_mode": "secret_ref_only",
            "requires_vault_before_production": True,
            "secret_exposed": False,
        }

    def build_secret_resolution_plan(
        self,
        *,
        secret_ref: dict[str, Any] | None,
        requested_by: str,
        task_scope: str,
    ) -> dict[str, Any]:
        return build_secret_resolution_plan(
            settings=self.settings,
            secret_ref=secret_ref,
            requested_by=requested_by,
            task_scope=task_scope,
        )

    def build_secret_rotation_plan(
        self,
        *,
        secret_ref: dict[str, Any] | None,
        requested_by: str,
        reason: str,
    ) -> dict[str, Any]:
        return build_secret_rotation_plan(
            settings=self.settings,
            secret_ref=secret_ref,
            requested_by=requested_by,
            reason=reason,
        )

    def build_secret_revoke_plan(
        self,
        *,
        secret_ref: dict[str, Any] | None,
        requested_by: str,
        reason: str,
    ) -> dict[str, Any]:
        return build_secret_revoke_plan(
            settings=self.settings,
            secret_ref=secret_ref,
            requested_by=requested_by,
            reason=reason,
        )

    def build_secret_reference_plan(
        self,
        *,
        payload: dict[str, Any],
        store: dict[str, Any],
        user_id: str,
    ) -> dict[str, Any]:
        purpose = str(payload.get("purpose") or "platform_connection").strip().lower()
        purpose_info = SECRET_PURPOSES.get(purpose, {
            "label": purpose,
            "provider_family": "custom",
            "rotation_days": int(payload.get("rotation_days") or 90),
            "live_use": "Custom secret reference reserved by the backend.",
        })
        requested_provider = str(payload.get("provider") or store.get("platform") or "platform").strip().lower()
        vault_target = str(payload.get("vault_target") or self.settings.vault_provider or "secret_ref_only").strip().lower()
        classification = self.classify_input(payload)
        can_store_raw_secret = self.status()["can_store_raw_secret"]
        status = "ready_for_external_vault_write" if can_store_raw_secret else "external_vault_required"
        return {
            "provider": requested_provider,
            "purpose": purpose,
            "purpose_label": purpose_info.get("label"),
            "provider_family": purpose_info.get("provider_family"),
            "store_id": store.get("store_id"),
            "store_platform": store.get("platform"),
            "created_by": user_id,
            "status": status,
            "vault_target": vault_target,
            "rotation_days": int(payload.get("rotation_days") or purpose_info.get("rotation_days") or 90),
            "live_use": purpose_info.get("live_use"),
            "raw_secret_input_seen": classification["raw_secret_input_seen"],
            "raw_secret_key_count": classification["raw_secret_key_count"],
            "secret_value_stored": False,
            "secret_ref_only": not can_store_raw_secret,
            "manual_entry_allowed": bool(payload.get("manual_entry_allowed", True)),
            "allowed_next_actions": [
                "create_secret_ref",
                "write_real_secret_to_external_vault_when_configured",
                "use_secret_ref_from_backend_adapter_only",
                "rotate_and_audit_before_production",
            ],
            "blocked_actions": [
                "return_raw_secret_to_frontend",
                "store_raw_secret_in_sqlite",
                "pass_all_customer_secrets_to_runtime",
                "run_live_adapter_without_vault",
            ],
            "redacted_metadata": redact_secret_like(payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}),
            "secret_exposed": False,
        }


def redact_secret_like(value: Any) -> Any:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            out[key] = "[REDACTED]" if _looks_secret_key(str(key)) else redact_secret_like(item)
        return out
    if isinstance(value, list):
        return [redact_secret_like(item) for item in value]
    return value


def _looks_secret_key(key: str) -> bool:
    lower = key.lower()
    return any(marker in lower for marker in SECRET_MARKERS)
