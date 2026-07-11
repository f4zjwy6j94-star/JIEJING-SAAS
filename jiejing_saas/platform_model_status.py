"""Backend-only status for the platform-managed AI CEO model."""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlparse

from .model_provider_catalog import get_model_provider, normalize_model_api_base_url


def build_platform_default_model_status() -> dict[str, Any]:
    explicit_api_key = (os.environ.get("JIEJING_AI_CEO_PLATFORM_MODEL_API_KEY") or "").strip()
    enabled = _env_enabled("JIEJING_AI_CEO_PLATFORM_MODEL_ENABLED", default=bool(explicit_api_key))
    provider = (
        os.environ.get("JIEJING_AI_CEO_PLATFORM_MODEL_PROVIDER")
        or os.environ.get("JIEJING_MODEL_PROVIDER")
        or ("deepseek" if os.environ.get("DEEPSEEK_API_KEY") else "openai")
    ).strip()
    definition = get_model_provider(provider)
    provider_supported = bool(definition and definition.supported_live_adapter)
    credential_source = "missing"
    credential_present = bool(explicit_api_key)
    if credential_present:
        credential_source = "platform_model_env"
    elif provider == "deepseek" and os.environ.get("DEEPSEEK_API_KEY"):
        credential_present = True
        credential_source = "deepseek_env"
    elif os.environ.get("JIEJING_MODEL_API_KEY"):
        credential_present = True
        credential_source = "generic_model_env"

    configured_model = (
        os.environ.get("JIEJING_AI_CEO_PLATFORM_MODEL")
        or os.environ.get("JIEJING_MODEL")
        or (definition.default_model if definition else "")
    ).strip()
    model = platform_default_serving_model(provider=provider, configured_model=configured_model)
    raw_base_url = (
        os.environ.get("JIEJING_AI_CEO_PLATFORM_MODEL_BASE_URL")
        or os.environ.get("JIEJING_MODEL_BASE_URL")
        or (definition.default_base_url if definition else "")
    )
    base_url = normalize_model_api_base_url(provider_key=provider, base_url=raw_base_url) if definition else ""
    live_disabled = _env_enabled("JIEJING_MODEL_DISABLE_LIVE", default=False)
    configured = bool(enabled and credential_present and provider_supported and model and base_url and not live_disabled)
    if configured:
        status = "ready"
    elif not enabled:
        status = "not_enabled"
    elif not provider_supported:
        status = "unsupported_provider"
    elif not credential_present:
        status = "missing_key"
    elif live_disabled:
        status = "live_disabled"
    else:
        status = "incomplete_configuration"

    return {
        "contract_version": "2026-07-11-platform-default-model-serving-policy",
        "enabled": enabled,
        "configured": configured,
        "status": status,
        "provider": provider,
        "model": model,
        "configured_model": configured_model,
        "serving_policy": "fast_trial_model_with_configured_fallback" if model != configured_model else "configured_model",
        "fallback_model": configured_model if model != configured_model else "",
        "endpoint_host": urlparse(base_url).netloc if base_url else "",
        "provider_supported": provider_supported,
        "credential_present": credential_present,
        "credential_source": credential_source,
        "live_disabled": live_disabled,
        "frontend_gets_model_api_key": False,
        "runtime_gets_model_api_key": False,
        "reports_get_model_api_key": False,
        "secret_exposed": False,
    }


def platform_default_serving_model(*, provider: str, configured_model: str) -> str:
    explicit = (os.environ.get("JIEJING_AI_CEO_PLATFORM_SERVING_MODEL") or "").strip()
    if explicit:
        return explicit
    if provider.strip().lower() == "deepseek":
        return "deepseek-v4-flash"
    return configured_model


def _env_enabled(name: str, *, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}
