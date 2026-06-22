"""Backend-only bridge from the legacy Hermes eBay credential store.

This is an interim migration bridge for local development. It lets Jiejing
SaaS read eBay through the existing Hermes credential files while Jiejing's own
Vault/KMS path is still being productized. It never returns token values to API
responses, the frontend, Runtime, reports, or audit payloads.
"""

from __future__ import annotations

import os
from typing import Any

from .config import SaaSSettings


def inspect_hermes_ebay_bridge(settings: SaaSSettings) -> dict[str, Any]:
    """Return sanitized readiness for the local Hermes eBay bridge."""

    enabled = _bridge_enabled(settings)
    if not enabled:
        return {
            "bridge_enabled": False,
            "status": "disabled",
            "can_resolve_access_token": False,
            "can_refresh_access_token": False,
            "credential_present": False,
            "credential_source": "disabled",
            "token_mode": "not_ready",
            "blocked_by": ["JIEJING_ENABLE_HERMES_EBAY_BRIDGE"],
            "secret_exposed": False,
        }

    resolver = _resolver()
    if resolver is None:
        return {
            "bridge_enabled": True,
            "status": "unavailable",
            "can_resolve_access_token": False,
            "can_refresh_access_token": False,
            "credential_present": False,
            "credential_source": "resolver_unavailable",
            "token_mode": "not_ready",
            "blocked_by": ["hermes_ebay_resolver_unavailable"],
            "secret_exposed": False,
        }

    presence = resolver.credential_presence()
    oauth_refresh = resolver.oauth_refresh_status()
    credential_source = str(presence.get("credential_source") or "missing")
    access_token_expired = "token_expired" in credential_source
    credential_present = bool(presence.get("credential_present"))
    refresh_ready = bool(oauth_refresh.get("refresh_ready"))
    auto_refresh_enabled = _env_bool("JIEJING_EBAY_AUTO_REFRESH", default=False)
    can_refresh = bool(refresh_ready and auto_refresh_enabled)
    can_resolve = credential_present or can_refresh
    if credential_present:
        status = "access_token_ready"
        token_mode = "backend_legacy_access_token"
    elif can_refresh:
        status = "refresh_ready_auto_enabled"
        token_mode = "backend_legacy_refresh_token"
    elif refresh_ready and access_token_expired:
        status = "access_token_expired_refresh_ready"
        token_mode = "not_ready"
    elif refresh_ready:
        status = "refresh_ready_auto_disabled"
        token_mode = "not_ready"
    else:
        status = "blocked"
        token_mode = "not_ready"

    blockers: list[str] = []
    if not can_resolve:
        if refresh_ready and not auto_refresh_enabled:
            blockers.append("JIEJING_EBAY_AUTO_REFRESH")
        elif access_token_expired:
            blockers.append("hermes_access_token_expired")
        else:
            blockers.append("hermes_ebay_credential_missing")

    return {
        "bridge_enabled": True,
        "status": status,
        "can_resolve_access_token": can_resolve,
        "can_refresh_access_token": can_refresh,
        "credential_present": credential_present,
        "credential_source": credential_source,
        "access_token_expired": access_token_expired,
        "refresh_token_present": bool(oauth_refresh.get("refresh_token_present")),
        "client_id_present": bool(oauth_refresh.get("client_id_present")),
        "client_secret_present": bool(oauth_refresh.get("client_secret_present")),
        "refresh_ready": refresh_ready,
        "auto_refresh_enabled": auto_refresh_enabled,
        "policy_snapshot_present": bool(resolver.policy_snapshot_present()),
        "listing_rules_snapshot_present": bool(resolver.listing_rules_snapshot_present()),
        "hermes_refresh_adapter_available": bool((oauth_refresh.get("hermes_refresh_adapter") or {}).get("available")),
        "token_mode": token_mode,
        "blocked_by": blockers,
        "secret_exposed": False,
    }


def resolve_hermes_ebay_access_token(settings: SaaSSettings) -> dict[str, Any]:
    """Resolve an access token internally from Hermes without exposing it."""

    status = inspect_hermes_ebay_bridge(settings)
    if not status.get("can_resolve_access_token"):
        return {
            "ok": False,
            "source": status.get("credential_source") or "missing",
            "blocked_by": status.get("blocked_by") or ["hermes_ebay_credential_unavailable"],
            "secret_exposed": False,
        }
    resolver = _resolver()
    if resolver is None:
        return {
            "ok": False,
            "source": "resolver_unavailable",
            "blocked_by": ["hermes_ebay_resolver_unavailable"],
            "secret_exposed": False,
        }
    token, source = resolver.resolve_access_token()
    if not token:
        return {
            "ok": False,
            "source": source,
            "blocked_by": ["hermes_ebay_access_token_unavailable"],
            "secret_exposed": False,
        }
    return {
        "ok": True,
        "source": "backend_legacy_hermes_bridge",
        "source_detail": source,
        "access_token": token,
        "secret_exposed": False,
    }


def _bridge_enabled(settings: SaaSSettings) -> bool:
    # Production SaaS should use Jiejing-owned Vault/KMS, not local Hermes files.
    if not _env_bool("JIEJING_ENABLE_HERMES_WSL_SECRET_LOOKUP", default=True):
        return False
    return _env_bool("JIEJING_ENABLE_HERMES_EBAY_BRIDGE", default=False)


def _resolver() -> Any | None:
    try:
        from jiejing_runtime.ebay_credentials import EbayCredentialResolver
    except Exception:
        return None
    return EbayCredentialResolver()


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}
