"""Merchant BYOK model provider catalog and client factory."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from jiejing_runtime.model_clients import OpenAICompatibleModelClient, OpenAIResponsesModelClient, ModelClient


MODEL_SECRET_PURPOSE = "model_api_key"
MODEL_PROVIDER_PREFIX = "model."
READY_MODEL_SECRET_STATUSES = {
    "ready",
    "stored",
    "active",
    "managed_vault_stored",
    "local_development_secret_stored",
}


@dataclass(frozen=True)
class ModelProviderDefinition:
    provider_key: str
    label: str
    api_style: str
    key_url: str
    docs_url: str
    default_base_url: str
    default_model: str
    supported_live_adapter: bool
    cost_owner: str = "merchant_provider_account"
    notes: str = ""

    def public_dict(self) -> dict[str, Any]:
        parsed = urlparse(self.default_base_url)
        return {
            "provider_key": self.provider_key,
            "label": self.label,
            "api_style": self.api_style,
            "key_url": self.key_url,
            "docs_url": self.docs_url,
            "default_base_url": self.default_base_url,
            "default_model": self.default_model,
            "supported_live_adapter": self.supported_live_adapter,
            "cost_owner": self.cost_owner,
            "endpoint_host": parsed.netloc,
            "merchant_brings_own_key": True,
            "jiejing_bills_model_usage": False,
            "stores_raw_key_in_database": False,
            "frontend_gets_raw_key_after_save": False,
            "runtime_gets_raw_key": False,
            "reports_get_raw_key": False,
            "notes": self.notes,
            "secret_exposed": False,
        }


PROVIDER_CATALOG: dict[str, ModelProviderDefinition] = {
    "openai": ModelProviderDefinition(
        provider_key="openai",
        label="OpenAI",
        api_style="responses",
        key_url="https://platform.openai.com/api-keys",
        docs_url="https://platform.openai.com/docs",
        default_base_url="https://api.openai.com/v1",
        default_model="gpt-4.1-mini",
        supported_live_adapter=True,
        notes="Preferred for OpenAI accounts; uses the Responses API.",
    ),
    "deepseek": ModelProviderDefinition(
        provider_key="deepseek",
        label="DeepSeek",
        api_style="openai_compatible",
        key_url="https://platform.deepseek.com/api_keys",
        docs_url="https://api-docs.deepseek.com/",
        default_base_url="https://api.deepseek.com",
        default_model="deepseek-v4-pro",
        supported_live_adapter=True,
        notes="OpenAI-compatible chat completions endpoint. DeepSeek documents the root base_url, not /v1.",
    ),
    "openrouter": ModelProviderDefinition(
        provider_key="openrouter",
        label="OpenRouter",
        api_style="openai_compatible",
        key_url="https://openrouter.ai/settings/keys",
        docs_url="https://openrouter.ai/docs",
        default_base_url="https://openrouter.ai/api/v1",
        default_model="openai/gpt-4o-mini",
        supported_live_adapter=True,
        notes="Useful when merchants want to route through OpenRouter with their own billing account.",
    ),
    "qwen_dashscope": ModelProviderDefinition(
        provider_key="qwen_dashscope",
        label="Alibaba Qwen / DashScope",
        api_style="openai_compatible",
        key_url="https://bailian.console.aliyun.com/?tab=model#/api-key",
        docs_url="https://help.aliyun.com/zh/model-studio/get-api-key",
        default_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        default_model="qwen-plus",
        supported_live_adapter=True,
        notes="Uses Alibaba Model Studio compatible mode.",
    ),
    "moonshot": ModelProviderDefinition(
        provider_key="moonshot",
        label="Moonshot AI",
        api_style="openai_compatible",
        key_url="https://platform.moonshot.cn/console/api-keys",
        docs_url="https://platform.moonshot.cn/docs",
        default_base_url="https://api.moonshot.cn/v1",
        default_model="moonshot-v1-8k",
        supported_live_adapter=True,
        notes="OpenAI-compatible endpoint for Moonshot merchant accounts.",
    ),
    "anthropic": ModelProviderDefinition(
        provider_key="anthropic",
        label="Anthropic Claude",
        api_style="native_pending",
        key_url="https://console.anthropic.com/settings/keys",
        docs_url="https://docs.anthropic.com/",
        default_base_url="https://api.anthropic.com",
        default_model="claude-3-5-sonnet-latest",
        supported_live_adapter=False,
        notes="Catalog entry is ready; native Anthropic adapter is not enabled in this runtime yet.",
    ),
    "google_gemini": ModelProviderDefinition(
        provider_key="google_gemini",
        label="Google Gemini",
        api_style="native_pending",
        key_url="https://aistudio.google.com/app/apikey",
        docs_url="https://ai.google.dev/gemini-api/docs/api-key",
        default_base_url="https://generativelanguage.googleapis.com",
        default_model="gemini-1.5-flash",
        supported_live_adapter=False,
        notes="Catalog entry is ready; native Gemini adapter is not enabled in this runtime yet.",
    ),
    "tencent_hunyuan": ModelProviderDefinition(
        provider_key="tencent_hunyuan",
        label="Tencent Hunyuan",
        api_style="native_pending",
        key_url="https://console.cloud.tencent.com/cam/capi",
        docs_url="https://cloud.tencent.com/document/product/1729",
        default_base_url="https://hunyuan.tencentcloudapi.com",
        default_model="hunyuan-lite",
        supported_live_adapter=False,
        notes="Catalog entry is ready; native Tencent Hunyuan adapter is not enabled in this runtime yet.",
    ),
}


def build_model_provider_catalog() -> dict[str, Any]:
    return {
        "contract_version": "2026-05-20-merchant-byok-model-provider-catalog",
        "billing_model": "merchant_brings_own_key",
        "merchant_pays_provider_directly": True,
        "credential_scope": "account_default_with_store_context",
        "jiejing_account_scoped_model_secret_ref": True,
        "jiejing_stores_only_secret_ref": False,
        "frontend_gets_raw_key_after_save": False,
        "runtime_gets_raw_key": False,
        "reports_get_raw_key": False,
        "providers": [definition.public_dict() for definition in PROVIDER_CATALOG.values()],
        "secret_exposed": False,
    }


def get_model_provider(provider_key: str) -> ModelProviderDefinition | None:
    normalized = normalize_model_provider_key(provider_key)
    return PROVIDER_CATALOG.get(normalized)


def normalize_model_provider_key(provider_key: str) -> str:
    return provider_key.strip().lower().replace("-", "_").replace(" ", "_")


def model_secret_provider(provider_key: str) -> str:
    return f"{MODEL_PROVIDER_PREFIX}{normalize_model_provider_key(provider_key)}"


def public_model_settings_from_secret_refs(secret_refs: list[dict[str, Any]]) -> dict[str, Any]:
    model_refs = [item for item in secret_refs if str(item.get("purpose") or "") == MODEL_SECRET_PURPOSE]
    active_refs = [item for item in model_refs if str(item.get("status") or "") in READY_MODEL_SECRET_STATUSES]
    latest = model_refs[0] if model_refs else None
    active = active_refs[0] if active_refs else None
    latest_public = _public_secret_ref(latest) if latest else None
    latest_status = str((latest or {}).get("status") or "")
    if active:
        connection_state = "ready"
        if latest and latest.get("secret_ref") != active.get("secret_ref"):
            connection_state = "ready_with_failed_update"
    elif latest_status == "stored_unverified":
        connection_state = "saved_needs_verification"
    elif latest:
        connection_state = "save_failed"
    else:
        connection_state = "not_configured"
    scope_counts: dict[str, int] = {}
    for item in model_refs:
        scope = _public_model_ref_scope(item)
        scope_counts[scope] = scope_counts.get(scope, 0) + 1
    return {
        "contract_version": "2026-07-03-account-model-settings",
        "mode": "merchant_byok_account_default",
        "configured": bool(active_refs),
        "active_secret_ref": active.get("secret_ref") if active else None,
        "active_provider": provider_key_from_secret_ref(active) if active else "",
        "active_model": _public_secret_ref(active).get("model") if active else "",
        "active_scope": _public_model_ref_scope(active) if active else "",
        "scope_counts": scope_counts,
        "secret_refs": [_public_secret_ref(item) for item in model_refs],
        "connection_state": connection_state,
        "latest_attempt": latest_public,
        "requires_api_key_reentry": bool(latest_public and latest_public.get("requires_api_key_reentry")),
        "can_retry_verification": bool(latest_public and latest_public.get("can_retry_verification")),
        "merchant_pays_provider_directly": True,
        "merchant_model_follows_account": True,
        "store_context_optional": True,
        "jiejing_account_scoped_model_secret_ref": True,
        "jiejing_stores_only_secret_ref": False,
        "frontend_gets_raw_key_after_save": False,
        "runtime_gets_raw_key": False,
        "reports_get_raw_key": False,
        "secret_exposed": False,
    }


def provider_key_from_secret_ref(secret_ref: dict[str, Any] | None) -> str:
    if not secret_ref:
        return ""
    metadata = secret_ref.get("metadata") if isinstance(secret_ref.get("metadata"), dict) else {}
    provider_key = str(metadata.get("provider_key") or "")
    if provider_key:
        return normalize_model_provider_key(provider_key)
    provider = str(secret_ref.get("provider") or "")
    if provider.startswith(MODEL_PROVIDER_PREFIX):
        return normalize_model_provider_key(provider[len(MODEL_PROVIDER_PREFIX) :])
    return normalize_model_provider_key(provider)


def _public_model_ref_scope(secret_ref: dict[str, Any] | None) -> str:
    if not secret_ref:
        return ""
    metadata = secret_ref.get("metadata") if isinstance(secret_ref.get("metadata"), dict) else {}
    raw_scope = str(
        metadata.get("model_connection_scope")
        or metadata.get("scope")
        or metadata.get("connection_scope")
        or ""
    ).strip().lower()
    if raw_scope in {"account", "store", "company", "platform"}:
        return raw_scope
    return "store" if secret_ref.get("store_id") else "account"


def _model_client_timeout_seconds(timeout_seconds: int | None = None) -> int:
    if timeout_seconds is not None:
        try:
            return max(5, min(180, int(timeout_seconds)))
        except (TypeError, ValueError):
            pass
    raw = os.environ.get("JIEJING_MODEL_CLIENT_TIMEOUT_SECONDS")
    try:
        return max(5, min(180, int(str(raw).strip()))) if raw else 90
    except (TypeError, ValueError):
        return 90


def build_model_client_from_byok_secret(
    *,
    provider_key: str,
    api_key: str,
    model: str,
    base_url: str | None = None,
    timeout_seconds: int | None = None,
) -> ModelClient:
    definition = get_model_provider(provider_key)
    if not definition:
        raise ValueError("unsupported_model_provider")
    if not definition.supported_live_adapter:
        raise ValueError("model_provider_adapter_not_implemented")
    selected_base_url = normalize_model_api_base_url(provider_key=provider_key, base_url=base_url)
    selected_model = model or definition.default_model
    selected_timeout = _model_client_timeout_seconds(timeout_seconds)
    if definition.api_style == "responses":
        return OpenAIResponsesModelClient(
            endpoint=f"{selected_base_url}/responses",
            api_key=api_key,
            model=selected_model,
            timeout_seconds=selected_timeout,
        )
    if definition.api_style == "openai_compatible":
        return OpenAICompatibleModelClient(
            endpoint=f"{selected_base_url}/chat/completions",
            api_key=api_key,
            model=selected_model,
            timeout_seconds=selected_timeout,
        )
    raise ValueError("model_provider_adapter_not_implemented")


def normalize_model_api_base_url(*, provider_key: str, base_url: str | None = None) -> str:
    definition = get_model_provider(provider_key)
    if not definition:
        raise ValueError("unsupported_model_provider")
    raw = str(base_url or "").strip().rstrip("/")
    if not raw:
        return definition.default_base_url
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return definition.default_base_url
    docs_url = definition.docs_url.rstrip("/")
    key_url = definition.key_url.rstrip("/")
    if raw.startswith(docs_url) or raw.startswith(key_url):
        return definition.default_base_url
    host = parsed.netloc.lower()
    path = parsed.path.lower()
    if "docs" in host or "doc" in path or "/zh-cn" in path:
        return definition.default_base_url
    if definition.provider_key == "deepseek" and host == "api.deepseek.com" and path in {"", "/", "/v1"}:
        return definition.default_base_url
    return raw


def _public_secret_ref(secret_ref: dict[str, Any]) -> dict[str, Any]:
    metadata = secret_ref.get("metadata") if isinstance(secret_ref.get("metadata"), dict) else {}
    provider_key = provider_key_from_secret_ref(secret_ref)
    definition = get_model_provider(provider_key)
    scope = _public_model_ref_scope(secret_ref)
    status = str(secret_ref.get("status") or "")
    blocked_by = metadata.get("blocked_by") if isinstance(metadata.get("blocked_by"), list) else []
    storage_succeeded = status in READY_MODEL_SECRET_STATUSES or status == "stored_unverified"
    return {
        "secret_ref": secret_ref.get("secret_ref"),
        "store_id": secret_ref.get("store_id"),
        "scope": scope,
        "model_connection_scope": scope,
        "provider": secret_ref.get("provider"),
        "provider_key": provider_key,
        "provider_label": definition.label if definition else provider_key,
        "purpose": secret_ref.get("purpose"),
        "status": secret_ref.get("status"),
        "created_at": secret_ref.get("created_at"),
        "model": metadata.get("model") or (definition.default_model if definition else ""),
        "base_url": metadata.get("base_url") or (definition.default_base_url if definition else ""),
        "api_style": metadata.get("api_style") or (definition.api_style if definition else ""),
        "key_url": definition.key_url if definition else metadata.get("key_url"),
        "docs_url": definition.docs_url if definition else metadata.get("docs_url"),
        "supported_live_adapter": bool(definition and definition.supported_live_adapter),
        "storage_status": metadata.get("storage_status") or status,
        "verification_status": metadata.get("verification_status") or ("verified" if status == "ready" else "not_verified"),
        "verified_at": metadata.get("verified_at") or "",
        "verification_error_code": metadata.get("verification_error_code") or "",
        "blocked_by": blocked_by,
        "requires_api_key_reentry": not storage_succeeded,
        "can_retry_verification": status == "stored_unverified",
        "merchant_pays_provider_directly": True,
        "secret_exposed": False,
    }
