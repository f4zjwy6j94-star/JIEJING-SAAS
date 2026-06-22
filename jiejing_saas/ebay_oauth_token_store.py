"""Jiejing-owned backend OAuth token adapter for eBay.

This is the local-development implementation of the Jiejing-owned credential
boundary. It stores token values only in a backend-local output file when
explicitly enabled. Public API responses only return secret_ref/status
metadata. Staging and production should replace this adapter with Vault/KMS.
"""

from __future__ import annotations

import base64
import json
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable

from .config import SaaSSettings


OAuthTransport = Callable[[urllib.request.Request, float], tuple[int, dict[str, str], bytes]]


def build_local_oauth_token_store_status(settings: SaaSSettings) -> dict[str, Any]:
    enabled = _local_store_enabled(settings)
    path = _store_path(settings)
    blocked_by: list[str] = []
    if not enabled:
        blocked_by.append("JIEJING_EBAY_LOCAL_TOKEN_STORE_ENABLED")
    if settings.is_production_like:
        blocked_by.append("production_requires_managed_vault")
    return {
        "adapter_version": "2026-05-15-ebay-local-oauth-token-store",
        "status": "enabled" if enabled and not settings.is_production_like else "disabled_or_blocked",
        "enabled": bool(enabled and not settings.is_production_like),
        "path_configured": bool(os.environ.get("JIEJING_EBAY_LOCAL_TOKEN_STORE_PATH")),
        "path": str(path),
        "blocked_by": blocked_by,
        "stores_raw_secret_in_database": False,
        "returns_raw_secret_to_frontend": False,
        "returns_raw_secret_to_runtime": False,
        "production_replacement": "Jiejing-managed Vault/KMS secret resolver",
        "secret_exposed": False,
    }


class EbayLocalOAuthTokenStore:
    def __init__(self, settings: SaaSSettings, *, transport: OAuthTransport | None = None) -> None:
        self.settings = settings
        self.transport = transport or _urlopen_transport
        self.path = _store_path(settings)

    def status(self) -> dict[str, Any]:
        status = build_local_oauth_token_store_status(self.settings)
        status["record_count"] = len(self._read_records())
        status["latest_secret_ref"] = self._latest_secret_ref()
        return status

    def has_usable_token(self, secret_ref: str | None = None) -> bool:
        if not _local_store_enabled(self.settings):
            return False
        record = self._get_record(secret_ref)
        if not record:
            return False
        if record.get("access_token") and not _is_expired(record):
            return True
        return bool(record.get("refresh_token") and self.settings.ebay_token_refresh_live_enabled)

    def public_record_status(self, secret_ref: str | None = None) -> dict[str, Any]:
        record = self._get_record(secret_ref)
        if not record:
            return {
                "status": "missing",
                "secret_ref": secret_ref,
                "access_token_present": False,
                "refresh_token_present": False,
                "secret_exposed": False,
            }
        return {
            "status": "ready" if self.has_usable_token(secret_ref) else "blocked_or_expired",
            "secret_ref": record.get("secret_ref"),
            "company_id": record.get("company_id"),
            "store_id": record.get("store_id"),
            "scopes": record.get("scopes") if isinstance(record.get("scopes"), list) else [],
            "access_token_present": bool(record.get("access_token")),
            "refresh_token_present": bool(record.get("refresh_token")),
            "expires_at": record.get("expires_at"),
            "updated_at": record.get("updated_at"),
            "token_values_returned": False,
            "secret_exposed": False,
        }

    def store_exchange_result(
        self,
        *,
        secret_ref: str,
        company_id: str,
        store_id: str,
        user_id: str,
        token_response: dict[str, Any],
        scopes: list[str],
    ) -> dict[str, Any]:
        if not _local_store_enabled(self.settings):
            return {
                "status": "blocked",
                "blocked_by": ["JIEJING_EBAY_LOCAL_TOKEN_STORE_ENABLED"],
                "secret_exposed": False,
            }
        access_token = str(token_response.get("access_token") or "")
        refresh_token = str(token_response.get("refresh_token") or "")
        if not access_token and not refresh_token:
            return {
                "status": "blocked_missing_token_response",
                "blocked_by": ["missing_access_or_refresh_token"],
                "secret_exposed": False,
            }
        now = int(time.time())
        expires_in = _safe_int(token_response.get("expires_in"), default=7200)
        records = self._read_records()
        records[secret_ref] = {
            "secret_ref": secret_ref,
            "company_id": company_id,
            "store_id": store_id,
            "created_by": user_id,
            "platform": "ebay",
            "purpose": "ebay_refresh_token",
            "environment": self.settings.ebay_oauth_environment,
            "scopes": scopes,
            "token_type": token_response.get("token_type") or "User Access Token",
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_at": now + expires_in,
            "refresh_token_expires_in": token_response.get("refresh_token_expires_in"),
            "updated_at": now,
        }
        self._write_records(records)
        return self.public_record_status(secret_ref)

    def resolve_access_token(self, *, secret_ref: str | None = None) -> dict[str, Any]:
        if not _local_store_enabled(self.settings):
            return {"ok": False, "blocked_by": ["JIEJING_EBAY_LOCAL_TOKEN_STORE_ENABLED"], "secret_exposed": False}
        record = self._get_record(secret_ref)
        if not record:
            return {"ok": False, "blocked_by": ["local_oauth_token_record_missing"], "secret_exposed": False}
        if record.get("access_token") and not _is_expired(record):
            return {
                "ok": True,
                "source": "backend_jiejing_local_oauth_store",
                "access_token": str(record["access_token"]),
                "expires_at": record.get("expires_at"),
                "secret_exposed": False,
            }
        if not record.get("refresh_token"):
            return {"ok": False, "blocked_by": ["local_refresh_token_missing"], "secret_exposed": False}
        if not self.settings.ebay_token_refresh_live_enabled:
            return {"ok": False, "blocked_by": ["JIEJING_EBAY_TOKEN_REFRESH_LIVE"], "secret_exposed": False}
        return self._refresh_record(record)

    def exchange_authorization_code(self, *, code: str) -> dict[str, Any]:
        blockers = []
        if not self.settings.ebay_oauth_live_exchange_enabled:
            blockers.append("JIEJING_EBAY_OAUTH_EXCHANGE_LIVE")
        if not self.settings.ebay_client_id:
            blockers.append("JIEJING_EBAY_CLIENT_ID")
        if not self.settings.ebay_client_secret_configured:
            blockers.append("JIEJING_EBAY_CLIENT_SECRET")
        if not self.settings.ebay_ru_name:
            blockers.append("JIEJING_EBAY_RU_NAME")
        if blockers:
            return {"ok": False, "blocked_by": blockers, "secret_exposed": False}
        body = urllib.parse.urlencode(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.settings.ebay_ru_name,
            }
        ).encode("utf-8")
        result = self._post_token_endpoint(body)
        if not result.get("ok"):
            return result
        return {
            "ok": True,
            "token_response": result["token_response"],
            "http_status": result.get("http_status"),
            "secret_exposed": False,
        }

    def _refresh_record(self, record: dict[str, Any]) -> dict[str, Any]:
        body = urllib.parse.urlencode(
            {
                "grant_type": "refresh_token",
                "refresh_token": record.get("refresh_token") or "",
            }
        ).encode("utf-8")
        result = self._post_token_endpoint(body)
        if not result.get("ok"):
            return result
        token_response = result["token_response"]
        records = self._read_records()
        updated = dict(record)
        now = int(time.time())
        updated["access_token"] = token_response.get("access_token") or updated.get("access_token")
        if token_response.get("refresh_token"):
            updated["refresh_token"] = token_response.get("refresh_token")
        updated["expires_at"] = now + _safe_int(token_response.get("expires_in"), default=7200)
        updated["updated_at"] = now
        records[str(updated["secret_ref"])] = updated
        self._write_records(records)
        return {
            "ok": True,
            "source": "backend_jiejing_local_oauth_store_refresh",
            "access_token": str(updated["access_token"]),
            "expires_at": updated.get("expires_at"),
            "secret_exposed": False,
        }

    def _post_token_endpoint(self, body: bytes) -> dict[str, Any]:
        client_secret = os.environ.get("JIEJING_EBAY_CLIENT_SECRET") or os.environ.get("EBAY_CLIENT_SECRET") or ""
        basic = base64.b64encode(f"{self.settings.ebay_client_id}:{client_secret}".encode("utf-8")).decode("ascii")
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
            status, _headers, raw = self.transport(request, 20)
            data = json.loads(raw.decode("utf-8")) if raw else {}
        except Exception as exc:  # pragma: no cover - live provider dependent
            return {"ok": False, "blocked_by": ["oauth_token_http_error"], "error_type": type(exc).__name__, "secret_exposed": False}
        if status >= 400 or not isinstance(data, dict) or not data.get("access_token"):
            return {"ok": False, "blocked_by": ["oauth_token_exchange_failed"], "http_status": status, "secret_exposed": False}
        return {"ok": True, "http_status": status, "token_response": data, "secret_exposed": False}

    def _get_record(self, secret_ref: str | None) -> dict[str, Any] | None:
        records = self._read_records()
        if secret_ref and isinstance(records.get(secret_ref), dict):
            return records[secret_ref]
        latest_ref = self._latest_secret_ref()
        if latest_ref and isinstance(records.get(latest_ref), dict):
            return records[latest_ref]
        return None

    def _latest_secret_ref(self) -> str | None:
        records = self._read_records()
        latest: tuple[int, str] | None = None
        for secret_ref, record in records.items():
            if not isinstance(record, dict):
                continue
            updated_at = _safe_int(record.get("updated_at"), default=0)
            if latest is None or updated_at > latest[0]:
                latest = (updated_at, secret_ref)
        return latest[1] if latest else None

    def _read_records(self) -> dict[str, dict[str, Any]]:
        try:
            if not self.path.exists():
                return {}
            data = json.loads(self.path.read_text(encoding="utf-8"))
            records = data.get("records") if isinstance(data, dict) else {}
            return records if isinstance(records, dict) else {}
        except Exception:
            return {}

    def _write_records(self, records: dict[str, dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "store_version": "2026-05-15-local-ebay-oauth-token-store",
            "warning": "Local development only. Do not commit or use in production.",
            "records": records,
        }
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        tmp.replace(self.path)


def _local_store_enabled(settings: SaaSSettings) -> bool:
    return (not settings.is_production_like) and _env_bool("JIEJING_EBAY_LOCAL_TOKEN_STORE_ENABLED", default=False)


def _store_path(settings: SaaSSettings) -> Path:
    configured = os.environ.get("JIEJING_EBAY_LOCAL_TOKEN_STORE_PATH")
    if configured:
        return Path(configured)
    return settings.output_root / "secrets" / "ebay_oauth_tokens.local.json"


def _token_endpoint(settings: SaaSSettings) -> str:
    if settings.ebay_oauth_environment == "sandbox":
        return "https://api.sandbox.ebay.com/identity/v1/oauth2/token"
    return "https://api.ebay.com/identity/v1/oauth2/token"


def _is_expired(record: dict[str, Any]) -> bool:
    return _safe_int(record.get("expires_at"), default=0) <= int(time.time()) + 60


def _safe_int(value: Any, *, default: int) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _urlopen_transport(request: urllib.request.Request, timeout: float) -> tuple[int, dict[str, str], bytes]:
    with urllib.request.urlopen(request, timeout=timeout) as response:
        headers = {key: value for key, value in response.headers.items()}
        return int(response.status), headers, response.read()
