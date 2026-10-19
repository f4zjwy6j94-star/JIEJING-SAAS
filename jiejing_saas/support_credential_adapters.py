"""Explicit backend-only bridges for SupportTokenResolver, disabled by default.

The default-off server factory pins one verified store binding and one managed
Vault destination. Construction performs no network or secret read. Dependencies
are never deserialized request data. Only public_result is HTTP-safe.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import sqlite3
from dataclasses import replace
from urllib.parse import quote

from .config import SaaSSettings
from .ebay_token_refresh_adapter import EbayVaultTokenRefreshAdapter
from .ebay_oauth_token_store import EbayLocalOAuthTokenStore
from .ebay_account_deletion import fetch_ebay_identity_hashes
from .support_transport import SupportTransport
from .support_token_resolver import SupportTokenResolver
from .vault_secret_resolver import _hashicorp_secret_path

_SELECTORS = ("company_id", "store_id", "connection_id", "oauth_request_id", "secret_ref",
              "seller_identity_hash", "owner_username_hash", "owner_binding_kind", "environment")


def _text(value, limit=200):
    return type(value) is str and bool(value) and value == value.strip() and len(value) <= limit and not any(ord(c) < 32 for c in value)


def _blocked(code):
    return {"ok": False, "status": "blocked", "blocked_by": [code], "secret_exposed": False}


def _support_vault_url(binding):
    addr = os.environ.get("JIEJING_VAULT_ADDR") or os.environ.get("VAULT_ADDR") or ""
    mount = os.environ.get("JIEJING_VAULT_MOUNT") or "secret"
    keyspace = os.environ.get("JIEJING_VAULT_KEYSPACE") or ""
    kv_version = os.environ.get("JIEJING_VAULT_KV_VERSION", "v2").strip().lower()
    if not addr or not keyspace or kv_version not in {"v1", "v2"}:
        return ""
    config = {"keyspace": keyspace, "path_template": os.environ.get("JIEJING_VAULT_PATH_TEMPLATE")
              or "{keyspace}/{company_id}/{store_id}/{secret_ref}"}
    path = _hashicorp_secret_path(config=config, secret_ref=binding)
    return (addr.rstrip("/") + "/v1/" + quote(mount.strip("/"), safe="") + "/"
            + ("data/" if kv_version == "v2" else "") + path)


def build_support_resolver(repository, settings, *, company_id, store_id, enabled=False):
    """Trusted server entry only. Never enable from a request's fields/headers.

    One construction per authenticated operation; no global token cache. The
    immutable transport rejects a changed Vault URL and managed-only resolution
    prevents local-provider fallback. Actual grant/owner checks still happen in
    SupportTokenResolver before any buyer-message operation can use the token.
    """
    if enabled is not True or type(settings) is not SaaSSettings:
        return None
    try:
        boundary = repository.get_support_connection_boundary(company_id=company_id, store_id=store_id)
        binding = boundary.get("internal") or {}
        if binding.get("company_id") != company_id or binding.get("store_id") != store_id:
            return None
        pinned_settings = replace(settings)
        credential_http = SupportTransport(role="credential", enabled=True,
            vault_url=_support_vault_url(binding), vault_binding=tuple(sorted(binding.items())))
        identity_http = SupportTransport(role="identity", enabled=True)
        adapters = SupportCredentialAdapters(repository,
            refresh_adapter=EbayVaultTokenRefreshAdapter(pinned_settings, transport=credential_http, managed_provider_only="vault"),
            introspection_adapter=EbayLocalOAuthTokenStore(pinned_settings, transport=credential_http),
            identity_helper=fetch_ebay_identity_hashes,
            credential_transport=credential_http, identity_transport=identity_http,
            expected_client_id=pinned_settings.ebay_client_id, enabled=True)
        if not (adapters._binding_valid(binding) and adapters._configuration_valid() and adapters._vault_target_valid(binding)):
            return None
        return SupportTokenResolver(repository, refresh=adapters.refresh, introspect=adapters.introspect,
            get_identity=adapters.get_identity, expected_client_id=pinned_settings.ebay_client_id,
            verification_enabled=True)
    except Exception:
        return None


class SupportCredentialAdapters:
    def __init__(self, repository, *, refresh_adapter, introspection_adapter,
                 identity_helper, credential_transport, identity_transport,
                 expected_client_id, enabled=False):
        self._repository = repository
        self._refresh_adapter = refresh_adapter
        self._introspection_adapter = introspection_adapter
        self._identity_helper = identity_helper
        self._credential_transport = credential_transport
        self._identity_transport = identity_transport
        self._expected_client_id = expected_client_id
        self._enabled = enabled

    def __repr__(self):
        return "<SupportCredentialAdapters backend-only redacted>"

    def refresh(self, *, binding, task_scope):
        if self._enabled is not True:
            return _blocked("support_credential_adapters_disabled")
        try:
            if not self._configuration_valid():
                return _blocked("support_credential_configuration_invalid")
            if task_scope != "support.message.verify" or not self._binding_valid(binding):
                return _blocked("support_credential_binding_invalid")
            binding = dict(binding)
            if not self._vault_target_valid(binding):
                return _blocked("support_credential_secret_provider_unreviewed")
            record = self._read_exact_record(binding)
            record_snapshot = json.dumps(record, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
            if (not self._binding_valid(binding) or not self._configuration_valid() or not self._vault_target_valid(binding)
                    or json.dumps(self._read_exact_record(binding), sort_keys=True, ensure_ascii=True,
                                  separators=(",", ":")) != record_snapshot):
                return _blocked("support_credential_binding_changed")
            result = self._refresh_adapter.refresh_access_token_from_secret_ref(secret_ref=record,
                company_id=binding["company_id"], store_id=binding["store_id"], task_scope=task_scope)
            if (not self._binding_valid(binding) or not self._configuration_valid() or not self._vault_target_valid(binding)
                    or json.dumps(self._read_exact_record(binding), sort_keys=True, ensure_ascii=True,
                                  separators=(",", ":")) != record_snapshot):
                return _blocked("support_credential_binding_changed")
            if (not isinstance(result, dict) or result.get("ok") is not True
                    or type(result.get("http_status")) is not int or result["http_status"] != 200
                    or result.get("source") != "backend_vault_secret_ref_refresh"
                    or any(result.get(key) != binding[key] for key in ("company_id", "store_id", "secret_ref"))
                    or result.get("secret_exposed") is not False or result.get("token_type") != "Bearer"
                    or not _text(result.get("access_token"), 65536)):
                return _blocked("support_credential_refresh_unverified")
            return {"ok": True, "binding": binding, "http_status": 200,
                    "source": "backend_vault_secret_ref_refresh", "token_type": "Bearer",
                    "access_token": result["access_token"], "expires_in": result.get("expires_in"),
                    "refreshed_at": result.get("refreshed_at"), "secret_exposed": False}
        except Exception:
            return _blocked("support_credential_refresh_unavailable")

    def _configuration_valid(self):
        # Only the reviewed implementation, never arbitrary callables, wrappers,
        # subclasses or caller-supplied safety markers.
        return (type(self._refresh_adapter) is EbayVaultTokenRefreshAdapter
            and type(self._introspection_adapter) is EbayLocalOAuthTokenStore
            and self._identity_helper is fetch_ebay_identity_hashes
            and _text(self._expected_client_id)
            and type(self._credential_transport) is SupportTransport
            and self._credential_transport.role == "credential" and self._credential_transport.enabled is True
            and type(self._identity_transport) is SupportTransport
            and self._identity_transport.role == "identity" and self._identity_transport.enabled is True
            and all(adapter.transport is self._credential_transport
                    and adapter.settings.ebay_client_id == self._expected_client_id
                    and adapter.settings.ebay_oauth_environment == "production"
                    for adapter in (self._refresh_adapter, self._introspection_adapter)))

    def _vault_target_valid(self, binding):
        """Pure nonsecret precheck, not generic provider status or token reading.

        Only Hashicorp is supported here. The server factory additionally forces
        managed-only resolution and pins the exact URL in SupportTransport.
        """
        settings = self._refresh_adapter.settings
        if (settings.vault_provider != "vault" or settings.vault_enabled is not True
                or settings.ebay_token_refresh_live_enabled is not True
                or os.environ.get("JIEJING_VAULT_LOCAL_SECRET_RESOLVER_ENABLED", "").strip().lower()
                    not in {"", "0", "false", "no", "off"}
                or os.environ.get("JIEJING_VAULT_LIVE_RESOLVE_ENABLED", "").strip().lower()
                    not in {"1", "true", "yes", "on"}):
            return False
        return self._credential_transport.matches_vault(binding, _support_vault_url(binding))

    def _binding_valid(self, binding):
        if (not isinstance(binding, dict) or set(binding) != set(_SELECTORS)
                or not all(_text(binding.get(key)) for key in _SELECTORS)
                or binding["environment"] != "production"
                or binding["owner_binding_kind"] != "sha256_casefold_ebay_username"
                or not all(re.fullmatch(r"[0-9a-f]{64}", binding[key])
                           for key in ("seller_identity_hash", "owner_username_hash"))):
            return False
        boundary = self._repository.get_support_connection_boundary(
            company_id=binding["company_id"], store_id=binding["store_id"])
        if not isinstance(boundary, dict):
            return False
        blockers = boundary.get("blocked_by")
        return (boundary.get("contract_version") == "2026-10-12-support-connection-boundary-v1"
            and boundary.get("connection_bound") is True
            and isinstance(blockers, list)
            and all(type(code) is str and code in {"support_message_scope_unverified", "support_message_scope_missing"}
                    for code in blockers)
            and boundary.get("status") == ("blocked" if blockers else "metadata_ready")
            and boundary.get("internal") == binding)

    def _read_exact_record(self, binding):
        """SELECT only, without repository.initialize or public get_secret_ref.

        SQLite uses mode=ro (not an existence-check followed by create-on-open).
        PG keeps the repository driver/placeholder adapter; no schema migration.
        This private record is passed only to the injected backend refresher.
        """
        engine = self._repository.database_engine
        if engine == "sqlite":
            conn = sqlite3.connect(Path(self._repository.db_path).resolve().as_uri() + "?mode=ro", uri=True)
            conn.row_factory = sqlite3.Row
        elif engine == "postgres":
            conn = self._repository._connect()
        else:
            raise ValueError("unsupported_repository")
        try:
            with conn:
                rows = conn.execute("""select secret_ref, company_id, store_id, provider, purpose, status,
                    created_by, created_at, metadata_json from secret_refs
                    where company_id=? and store_id=? and secret_ref=? limit 2""",
                    (binding["company_id"], binding["store_id"], binding["secret_ref"])).fetchall()
                if len(rows) != 1:
                    raise ValueError("exact_record_unavailable")
                row = dict(rows[0])
                raw = row.pop("metadata_json")
                metadata = json.loads(raw) if isinstance(raw, str) else raw
                if (not isinstance(metadata, dict)
                        or any(row.get(key) != binding[key] for key in ("company_id", "store_id", "secret_ref"))
                        or row.get("provider") != "ebay" or row.get("purpose") != "ebay_refresh_token"
                        or row.get("status") not in {"managed_vault_stored", "local_secret_resolver_stored"}
                        or metadata.get("oauth_request_id") != binding["oauth_request_id"]
                        or metadata.get("credential_owner") != "jiejing_saas_backend"):
                    raise ValueError("exact_record_invalid")
                row.update(metadata=metadata, secret_exposed=False)
            # Do not return from inside the context: exit/finalization failures
            # must discard the record rather than claim a successful read.
        finally:
            if engine == "sqlite":
                conn.close()
        return row

    def introspect(self, *, access_token, environment, expected_client_id):
        if self._enabled is not True:
            return _blocked("support_credential_adapters_disabled")
        try:
            if (not self._configuration_valid() or environment != "production"
                    or expected_client_id != self._expected_client_id or not _text(access_token, 65536)):
                return _blocked("support_credential_configuration_invalid")
            result = self._introspection_adapter.introspect_access_token(access_token=access_token)
            if not self._configuration_valid():
                return _blocked("support_credential_configuration_changed")
            if (not isinstance(result, dict) or result.get("ok") is not True
                    or result.get("active") is not True or result.get("client_id_matched") is not True
                    or type(result.get("http_status")) is not int or result["http_status"] != 200
                    or result.get("secret_exposed") is not False):
                return _blocked("support_credential_introspection_unverified")
            scopes = result.get("scopes")
            if (not isinstance(scopes, list) or not 1 <= len(scopes) <= 50
                    or not all(_text(scope, 512) for scope in scopes) or len(set(scopes)) != len(scopes)):
                return _blocked("support_credential_scopes_invalid")
            # Existing helper independently compared the actual provider client
            # to its config. Only after pinning that config before AND after the
            # call may the verified ID be projected; never echo request input.
            return {"ok": True, "active": True, "http_status": 200,
                    "client_id": self._expected_client_id, "scopes": list(scopes), "secret_exposed": False}
        except Exception:
            return _blocked("support_credential_introspection_unavailable")

    def get_identity(self, *, access_token, environment):
        if self._enabled is not True:
            return _blocked("support_credential_adapters_disabled")
        try:
            if not self._configuration_valid() or environment != "production" or not _text(access_token, 65536):
                return _blocked("support_credential_configuration_invalid")
            result = self._identity_helper(access_token=access_token, environment="production",
                                           transport=self._identity_transport)
            if not self._configuration_valid():
                return _blocked("support_credential_configuration_changed")
            if (not isinstance(result, dict) or result.get("status") != "identity_mapping_ready"
                    or result.get("secret_exposed") is not False or result.get("raw_identity_returned") is not False
                    or not all(type(result.get(key)) is str and re.fullmatch(r"[0-9a-f]{64}", result[key])
                               for key in ("ebay_user_id_hash", "ebay_username_hash"))):
                return _blocked("support_credential_identity_unverified")
            return {"status": "identity_mapping_ready", "ebay_user_id_hash": result["ebay_user_id_hash"],
                    "ebay_username_hash": result["ebay_username_hash"], "secret_exposed": False}
        except Exception:
            return _blocked("support_credential_identity_unavailable")
