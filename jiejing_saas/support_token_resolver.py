"""Offline-first backend credential boundary; no default network/secret adapters.

Dependencies must be trusted server adapters, never request JSON or browser data.
No token store, environment fallback, OAuth, schema initialization or adapter
factory is provided. A successful credential check does not enable message I/O.
"""
from __future__ import annotations

import time
import re
import math

from .ebay_message_adapter import MessageScope, MESSAGE_SCOPE

_BOUNDARY_VERSION = "2026-10-12-support-connection-boundary-v1"
_MODE = "sha256_casefold_ebay_username"
_SELECTOR_KEYS = ("company_id", "store_id", "connection_id", "oauth_request_id", "secret_ref",
                  "seller_identity_hash", "owner_username_hash", "owner_binding_kind", "environment")


def _text(value, limit=200):
    return type(value) is str and bool(value) and value == value.strip() and len(value) <= limit and not any(ord(c) < 32 for c in value)


def _instant(clock):
    value = clock()
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError("invalid_clock")
    return value


class SupportCredentialResolution:
    """Backend result. Only public_result() is suitable for an HTTP response."""

    __slots__ = ("_scope", "_code", "_access_token", "_scopes", "_clock", "_expires_at", "_not_before", "_binding_check")

    def __init__(self, code, *, scope=None, access_token="", scopes=(), expires_at=0, not_before=0, clock=time.time, binding_check=None):
        self._scope = scope
        self._code = code
        self._access_token = access_token
        self._scopes = tuple(scopes)
        self._clock = clock
        self._expires_at = expires_at
        self._not_before = not_before
        self._binding_check = binding_check

    @property
    def scope(self):
        return self._scope

    def __repr__(self):
        return "<SupportCredentialResolution backend-only redacted>"

    def public_result(self):
        self._expire()
        ok = self._code is None
        return {"status": "credentials_verified" if ok else "blocked", "credentials_verified": ok,
                "blocked_by": [] if ok else [self._code],
                "read_enabled": False, "send_enabled": False, "live_end_to_end_verified": False,
                "owner_identity_verified": ok, "granted_message_scope_verified": ok,
                "secret_exposed": False}

    def _expire(self):
        if self._code is None:
            try:
                now = _instant(self._clock)
                if now >= self._expires_at:
                    self._code = "support_verified_token_expired"
                elif now < self._not_before:
                    self._code = "support_token_clock_unavailable"
            except Exception:
                self._code = "support_token_clock_unavailable"
            if self._code:
                self._access_token = ""

    def token_provider(self, scope: MessageScope):
        """Private backend use by an explicitly enabled adapter; never serialize."""
        self._expire()
        if self._code is not None or not isinstance(scope, MessageScope) or scope != self._scope:
            return {"ok": False, "status": "blocked_token_binding"}
        try:
            if not self._binding_check():
                self._code = "support_connection_changed"
        except Exception:
            self._code = "support_connection_recheck_failed"
        self._expire()  # A slow metadata read must not release an expired token.
        if self._code:
            self._access_token = ""
            return {"ok": False, "status": self._code}
        return {"ok": True, "binding": self._scope.as_dict(), "scopes": list(self._scopes),
                "access_token": self._access_token}


class SupportTokenResolver:
    def __init__(self, repository, *, refresh, introspect, get_identity,
                 expected_client_id: str, verification_enabled: bool = False, clock=time.time):
        self.repository = repository
        self.refresh = refresh
        self.introspect = introspect
        self.get_identity = get_identity
        self.expected_client_id = expected_client_id
        self.verification_enabled = verification_enabled
        self.clock = clock

    def resolve(self, *, company_id: str, store_id: str):
        if self.verification_enabled is not True:
            return SupportCredentialResolution("support_verification_disabled")
        if not all(_text(x) for x in (company_id, store_id, self.expected_client_id)):
            return SupportCredentialResolution("support_invalid_resolver_scope")
        binding, code = self._read_binding(company_id, store_id)
        if code:
            return SupportCredentialResolution(code)
        try:
            refreshed = self.refresh(binding=dict(binding), task_scope="support.message.verify")
        except Exception:
            return SupportCredentialResolution("support_refresh_failed")
        if (not isinstance(refreshed, dict) or refreshed.get("ok") is not True
                or type(refreshed.get("http_status")) is not int or refreshed.get("http_status") != 200
                or refreshed.get("source") != "backend_vault_secret_ref_refresh"
                or refreshed.get("binding") != binding or refreshed.get("token_type") != "Bearer"
                or refreshed.get("secret_exposed") is not False
                or not _text(refreshed.get("access_token"), 65536)):
            return SupportCredentialResolution("support_refresh_binding_invalid")
        access_token = refreshed["access_token"]
        try:
            now = _instant(self.clock)
            timestamp, lifetime = refreshed.get("refreshed_at"), refreshed.get("expires_in")
            if (type(timestamp) is not int or type(lifetime) is not int or not 35 <= lifetime <= 86400
                    or not now - 30 <= timestamp <= now + 5):
                raise ValueError("invalid_expiry")
            expires_at = min(timestamp + lifetime - 30, now + 60)
            if expires_at <= now:
                raise ValueError("expired_token")
        except Exception:
            return SupportCredentialResolution("support_token_expiry_invalid")
        try:
            inspection = self.introspect(access_token=access_token, environment="production",
                                         expected_client_id=self.expected_client_id)
        except Exception:
            return SupportCredentialResolution("support_introspection_failed")
        if (not isinstance(inspection, dict) or inspection.get("ok") is not True
                or type(inspection.get("http_status")) is not int or inspection.get("http_status") != 200
                or inspection.get("active") is not True
                or inspection.get("client_id") != self.expected_client_id
                or inspection.get("secret_exposed") is not False):
            return SupportCredentialResolution("support_token_identity_unverified")
        scopes = inspection.get("scopes")
        if (not isinstance(scopes, list) or not 1 <= len(scopes) <= 50 or MESSAGE_SCOPE not in scopes
                or not all(_text(scope, 512) for scope in scopes) or len(set(scopes)) != len(scopes)):
            return SupportCredentialResolution("support_message_scope_not_granted")
        try:
            identity = self.get_identity(access_token=access_token, environment="production")
        except Exception:
            return SupportCredentialResolution("support_owner_identity_check_failed")
        if (not isinstance(identity, dict) or identity.get("status") != "identity_mapping_ready"
                or identity.get("secret_exposed") is not False
                or identity.get("ebay_user_id_hash") != binding["seller_identity_hash"]
                or identity.get("ebay_username_hash") != binding["owner_username_hash"]):
            return SupportCredentialResolution("support_owner_identity_mismatch")
        current, code = self._read_binding(company_id, store_id)
        if code or current != binding:
            return SupportCredentialResolution("support_connection_changed")
        try:
            if _instant(self.clock) >= expires_at:
                return SupportCredentialResolution("support_verified_token_expired")
        except Exception:
            return SupportCredentialResolution("support_token_clock_unavailable")
        scope = MessageScope(company_id, store_id, binding["owner_username_hash"], owner_binding_kind=_MODE)
        return SupportCredentialResolution(None, scope=scope, access_token=access_token, scopes=scopes,
            expires_at=expires_at, not_before=now - 5, clock=self.clock,
            binding_check=lambda: self._read_binding(company_id, store_id) == (binding, None))

    def _read_binding(self, company_id, store_id):
        try:
            boundary = self.repository.get_support_connection_boundary(company_id=company_id, store_id=store_id)
        except Exception:
            return None, "support_connection_metadata_unavailable"
        if not isinstance(boundary, dict) or boundary.get("contract_version") != _BOUNDARY_VERSION:
            return None, "support_connection_boundary_invalid"
        if boundary.get("connection_bound") is not True:
            return None, "support_connection_not_bound"
        blockers = boundary.get("blocked_by")
        if (not isinstance(blockers, list)
                or any(type(code) is not str or code not in {
                    "support_message_scope_unverified", "support_message_scope_missing"} for code in blockers)
                or boundary.get("status") != ("blocked" if blockers else "metadata_ready")):
            return None, "support_connection_boundary_blocked"
        internal = boundary.get("internal")
        if (not isinstance(internal, dict) or not all(_text(internal.get(key)) for key in _SELECTOR_KEYS)
                or internal.get("company_id") != company_id or internal.get("store_id") != store_id
                or internal.get("environment") != "production" or internal.get("owner_binding_kind") != _MODE
                or not all(re.fullmatch(r"[0-9a-f]{64}", internal.get(key, ""))
                           for key in ("seller_identity_hash", "owner_username_hash"))):
            return None, "support_connection_binding_invalid"
        return {key: internal[key] for key in _SELECTOR_KEYS}, None
