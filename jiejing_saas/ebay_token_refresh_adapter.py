"""Backend-only eBay OAuth token refresh adapter.

This is the production-shaped boundary between Jiejing's secret_ref records,
Vault/KMS resolution, and eBay's OAuth token endpoint. The public result is
sanitized; the short-lived access token is only returned to backend callers.
"""

from __future__ import annotations

import base64
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable

from .config import SaaSSettings
from .vault_secret_resolver import VaultSecretResolver, build_vault_secret_resolver_status


TokenRefreshTransport = Callable[[urllib.request.Request, float], tuple[int, dict[str, str], bytes]]


def build_ebay_token_refresh_adapter_status(settings: SaaSSettings) -> dict[str, Any]:
    resolver_status = build_vault_secret_resolver_status(settings)
    blockers: list[str] = []
    if not settings.ebay_client_id:
        blockers.append("JIEJING_EBAY_CLIENT_ID")
    if not settings.ebay_client_secret_configured:
        blockers.append("JIEJING_EBAY_CLIENT_SECRET")
    if not settings.ebay_token_refresh_live_enabled:
        blockers.append("JIEJING_EBAY_TOKEN_REFRESH_LIVE")
    if not resolver_status.get("live_secret_resolution_available"):
        blockers.append("Vault/KMS")
        blockers.extend(str(item) for item in resolver_status.get("blocked_by") or [] if item not in blockers)
    return {
        "adapter_version": "2026-06-13-ebay-vault-token-refresh-adapter",
        "platform": "ebay",
        "environment": settings.ebay_oauth_environment,
        "live_adapter_implemented": True,
        "status": "ready" if not blockers else "blocked",
        "blocked_by": _unique(blockers),
        "token_endpoint": _token_endpoint(settings),
        "vault_secret_resolver": {
            "status": resolver_status.get("status"),
            "live_secret_resolution_available": bool(resolver_status.get("live_secret_resolution_available")),
            "managed_live_resolution_ready": bool(resolver_status.get("managed_live_resolution_ready")),
            "returns_raw_secret_to_frontend": False,
            "returns_raw_secret_to_runtime": False,
            "secret_exposed": False,
        },
        "token_boundary": {
            "refresh_token_source": "backend_vault_secret_ref",
            "access_token_cache": "backend_memory_or_worker_process_only",
            "frontend_gets_access_token": False,
            "runtime_gets_access_token": False,
            "database_stores_access_token": False,
            "audit_records_token_value": False,
        },
        "secret_exposed": False,
    }


class EbayVaultTokenRefreshAdapter:
    def __init__(self, settings: SaaSSettings, *, transport: TokenRefreshTransport | None = None) -> None:
        self.settings = settings
        self.transport = transport or _urlopen_transport

    def refresh_access_token_from_secret_ref(
        self,
        *,
        secret_ref: dict[str, Any] | None,
        company_id: str,
        store_id: str,
        task_scope: str,
    ) -> dict[str, Any]:
        status = build_ebay_token_refresh_adapter_status(self.settings)
        blockers = list(status.get("blocked_by") or [])
        if not secret_ref or not secret_ref.get("secret_ref"):
            blockers.append("ebay_refresh_token_secret_ref")
        elif str(secret_ref.get("provider") or "").lower() != "ebay":
            blockers.append("secret_ref_provider_not_ebay")
        elif str(secret_ref.get("purpose") or "").lower() != "ebay_refresh_token":
            blockers.append("secret_ref_purpose_not_ebay_refresh_token")
        if blockers:
            return _blocked(blockers)

        resolved = VaultSecretResolver(self.settings, transport=self.transport).resolve_secret(
            secret_ref=secret_ref,
            requested_by="oauth_refresh_service",
            task_scope=task_scope,
            allowed_purposes=["ebay_refresh_token"],
        )
        if not resolved.get("ok"):
            return _blocked(resolved.get("blocked_by") or ["secret_ref_resolution_failed"])
        refresh_token = str(resolved.get("secret_value") or "")
        if not refresh_token:
            return _blocked(["resolved_refresh_token_empty"])
        return self._refresh_access_token(
            refresh_token=refresh_token,
            company_id=company_id,
            store_id=store_id,
            secret_ref_id=str(secret_ref.get("secret_ref") or ""),
            source=str(resolved.get("source") or "backend_vault_secret_ref"),
        )

    def _refresh_access_token(
        self,
        *,
        refresh_token: str,
        company_id: str,
        store_id: str,
        secret_ref_id: str,
        source: str,
    ) -> dict[str, Any]:
        client_secret = os.environ.get("JIEJING_EBAY_CLIENT_SECRET") or os.environ.get("EBAY_CLIENT_SECRET") or ""
        basic = base64.b64encode(f"{self.settings.ebay_client_id}:{client_secret}".encode("utf-8")).decode("ascii")
        body = urllib.parse.urlencode({"grant_type": "refresh_token", "refresh_token": refresh_token}).encode("utf-8")
        request = urllib.request.Request(
            _token_endpoint(self.settings),
            data=body,
            headers={
                "Authorization": f"Basic {basic}",
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            http_status, _headers, raw = self.transport(request, 20)
            data = json.loads(raw.decode("utf-8")) if raw else {}
        except urllib.error.HTTPError as exc:  # pragma: no cover - live provider dependent
            return _blocked(["token_refresh_http_error"], http_status=int(exc.code), error_type="HTTPError")
        except Exception as exc:  # pragma: no cover - live provider dependent
            return _blocked(["token_refresh_http_error"], error_type=type(exc).__name__)
        access_token = data.get("access_token") if isinstance(data, dict) else None
        if http_status >= 400 or not access_token:
            provider_error = _safe_provider_error(data if isinstance(data, dict) else {})
            return _blocked(
                ["token_refresh_failed"],
                http_status=http_status,
                provider_error=provider_error,
            )
        expires_in = _int(data.get("expires_in")) if isinstance(data, dict) else None
        return {
            "ok": True,
            "status": "refreshed",
            "source": "backend_vault_secret_ref_refresh",
            "resolver_source": source,
            "company_id": company_id,
            "store_id": store_id,
            "secret_ref": secret_ref_id,
            "http_status": http_status,
            "token_type": str(data.get("token_type") or "Bearer") if isinstance(data, dict) else "Bearer",
            "expires_in": expires_in,
            "refreshed_at": int(time.time()),
            "access_token": str(access_token),
            "access_token_returned_to_frontend": False,
            "access_token_returned_to_runtime": False,
            "access_token_stored_in_database": False,
            "refresh_token_returned_to_frontend": False,
            "secret_exposed": False,
        }


def public_token_refresh_result(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": bool(result.get("ok")),
        "status": result.get("status") or ("blocked" if result.get("blocked_by") else "unknown"),
        "source": result.get("source") or "",
        "resolver_source": result.get("resolver_source") or "",
        "company_id": result.get("company_id") or "",
        "store_id": result.get("store_id") or "",
        "secret_ref_present": bool(result.get("secret_ref")),
        "http_status": result.get("http_status"),
        "token_type": result.get("token_type") or "",
        "expires_in": result.get("expires_in"),
        "refreshed_at": result.get("refreshed_at"),
        "blocked_by": result.get("blocked_by") or [],
        "provider_error": result.get("provider_error") or {},
        "access_token_returned_to_frontend": False,
        "access_token_returned_to_runtime": False,
        "access_token_stored_in_database": False,
        "refresh_token_returned_to_frontend": False,
        "secret_exposed": False,
    }


def _token_endpoint(settings: SaaSSettings) -> str:
    if settings.ebay_oauth_environment == "sandbox":
        return "https://api.sandbox.ebay.com/identity/v1/oauth2/token"
    return "https://api.ebay.com/identity/v1/oauth2/token"


def _blocked(
    blockers: list[Any],
    *,
    http_status: int | None = None,
    error_type: str | None = None,
    provider_error: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "ok": False,
        "status": "blocked",
        "blocked_by": _unique([str(item) for item in blockers if item]),
        "access_token_returned_to_frontend": False,
        "access_token_returned_to_runtime": False,
        "access_token_stored_in_database": False,
        "refresh_token_returned_to_frontend": False,
        "secret_exposed": False,
    }
    if http_status is not None:
        result["http_status"] = http_status
    if error_type:
        result["error_type"] = error_type
    if provider_error:
        result["provider_error"] = provider_error
    return result


def _safe_provider_error(data: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in ("error", "error_description", "errorId", "message"):
        value = data.get(key)
        if isinstance(value, str) and value:
            out[key] = value[:300]
    return out


def _int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _urlopen_transport(request: urllib.request.Request, timeout: float) -> tuple[int, dict[str, str], bytes]:
    with urllib.request.urlopen(request, timeout=timeout) as response:
        headers = {key: value for key, value in response.headers.items()}
        return int(response.status), headers, response.read()
