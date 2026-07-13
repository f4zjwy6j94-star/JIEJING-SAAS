"""eBay OAuth planning boundary for Jiejing SaaS.

This module only builds a read-only authorization plan. It does not exchange
codes for tokens, does not persist tokens, and does not enable eBay writes.
"""

from __future__ import annotations

import secrets
import urllib.parse
from typing import Any

from .config import SaaSSettings
from .hermes_ebay_bridge import inspect_hermes_ebay_bridge
from .ebay_oauth_token_store import EbayLocalOAuthTokenStore, build_local_oauth_token_store_status
from .vault_secret_resolver import VaultSecretResolver, build_vault_secret_resolver_status


READ_ONLY_SCOPES = [
    "https://api.ebay.com/oauth/api_scope",
    "https://api.ebay.com/oauth/api_scope/commerce.identity.readonly",
    "https://api.ebay.com/oauth/api_scope/sell.account.readonly",
    "https://api.ebay.com/oauth/api_scope/sell.inventory.readonly",
    "https://api.ebay.com/oauth/api_scope/sell.fulfillment.readonly",
    "https://api.ebay.com/oauth/api_scope/sell.finances",
]

PUBLISH_SCOPES = [
    "https://api.ebay.com/oauth/api_scope",
    "https://api.ebay.com/oauth/api_scope/commerce.identity.readonly",
    "https://api.ebay.com/oauth/api_scope/sell.account.readonly",
    "https://api.ebay.com/oauth/api_scope/sell.inventory",
    "https://api.ebay.com/oauth/api_scope/sell.inventory.readonly",
    "https://api.ebay.com/oauth/api_scope/sell.fulfillment.readonly",
    "https://api.ebay.com/oauth/api_scope/sell.finances",
]

HIGH_RISK_WRITE_SCOPE_MARKERS = (
    "/sell.inventory",
    "/sell.account",
    "/sell.fulfillment",
    "/sell.marketing",
    "/sell.payment.dispute",
)


class EbayOAuthPlanner:
    def __init__(self, settings: SaaSSettings) -> None:
        self.settings = settings

    def read_only_authorization_plan(
        self,
        *,
        company_id: str,
        store_id: str,
        user_id: str,
        marketplace_id: str = "EBAY_US",
        requested_scopes: list[str] | None = None,
    ) -> dict[str, Any]:
        scopes = self._normalize_scopes(requested_scopes)
        missing_config = []
        if not self.settings.ebay_client_id:
            missing_config.append("JIEJING_EBAY_CLIENT_ID")
        if not self.settings.ebay_ru_name:
            missing_config.append("JIEJING_EBAY_RU_NAME")

        state_nonce = secrets.token_urlsafe(24)
        configured = not missing_config
        authorization_url = self._authorization_url(scopes, state_nonce) if configured else None
        return {
            "status": "ready_to_redirect" if configured else "blocked_missing_oauth_config",
            "platform": "ebay",
            "environment": self.settings.ebay_oauth_environment,
            "company_id": company_id,
            "store_id": store_id,
            "user_id": user_id,
            "marketplace_id": marketplace_id,
            "scopes": scopes,
            "scope_profile": "seller_read_only",
            "state_nonce": state_nonce,
            "authorization_url": authorization_url,
            "missing_config": missing_config,
            "human_login_required": True,
            "callback_next_step": "backend_exchange_code_for_token_then_store_refresh_token_in_vault",
            "will_store_raw_token_in_frontend": False,
            "will_store_raw_token_in_database": False,
            "real_platform_writes_enabled": False,
            "confirmation_required_for_scope_upgrade": True,
            "notes": [
                "The seller must complete eBay login and consent in the browser.",
                "The browser should only receive an authorization URL and state, never access_token or refresh_token.",
                "Code exchange and refresh token storage belong to the SaaS backend and Vault/KMS.",
                "Publishing, refunds, ads, procurement payment, and policy edits remain confirmation-gated.",
            ],
            "secret_exposed": False,
        }

    def publish_authorization_plan(
        self,
        *,
        company_id: str,
        store_id: str,
        user_id: str,
        marketplace_id: str = "EBAY_US",
        requested_scopes: list[str] | None = None,
    ) -> dict[str, Any]:
        """Build a seller-consent URL for the first supported write: publish listing."""

        scopes = self._normalize_publish_scopes(requested_scopes)
        missing_config = []
        if not self.settings.ebay_client_id:
            missing_config.append("JIEJING_EBAY_CLIENT_ID")
        if not self.settings.ebay_ru_name:
            missing_config.append("JIEJING_EBAY_RU_NAME")

        state_nonce = secrets.token_urlsafe(24)
        configured = not missing_config
        authorization_url = self._authorization_url(scopes, state_nonce) if configured else None
        return {
            "status": "ready_to_redirect" if configured else "blocked_missing_oauth_config",
            "platform": "ebay",
            "environment": self.settings.ebay_oauth_environment,
            "company_id": company_id,
            "store_id": store_id,
            "user_id": user_id,
            "marketplace_id": marketplace_id,
            "scopes": scopes,
            "scope_profile": "seller_publish_listing",
            "state_nonce": state_nonce,
            "authorization_url": authorization_url,
            "missing_config": missing_config,
            "human_login_required": True,
            "callback_next_step": "backend_exchange_code_for_token_then_store_refresh_token_in_vault",
            "will_store_raw_token_in_frontend": False,
            "will_store_raw_token_in_database": False,
            "real_platform_writes_enabled": self.settings.effective_real_platform_writes_enabled,
            "confirmation_required_for_scope_upgrade": True,
            "write_actions_requested": ["publish_listing"],
            "write_actions_not_requested": [
                "change_price",
                "change_inventory",
                "refund",
                "ad_budget",
                "procurement_payment",
                "policy_edit",
                "tracking_write",
            ],
            "notes": [
                "This authorization adds the eBay sell.inventory write scope needed for Inventory API publishOffer.",
                "The browser still receives only an authorization URL and state, never access_token or refresh_token.",
                "The first live write supported by Jiejing is single publish_listing after confirmation, not bulk publish or account mutation.",
                "Publishing remains blocked unless listing facts, business policies, item specifics, assets, finance review, and confirmation preflight pass.",
            ],
            "secret_exposed": False,
        }

    def callback_result(
        self,
        *,
        request_record: dict[str, Any] | None,
        code: str | None,
        error: str | None,
        secret_store_status: dict[str, Any],
    ) -> dict[str, Any]:
        if not request_record:
            return {
                "status": "blocked_invalid_state",
                "summary": "OAuth callback state does not match any pending Jiejing authorization request.",
                "real_platform_writes_enabled": False,
                "secret_exposed": False,
            }
        if error:
            return {
                "status": "seller_declined_or_ebay_error",
                "oauth_request_id": request_record["oauth_request_id"],
                "company_id": request_record["company_id"],
                "store_id": request_record["store_id"],
                "summary": f"eBay returned an OAuth error: {str(error)[:160]}",
                "real_platform_writes_enabled": False,
                "secret_exposed": False,
            }
        if not code:
            return {
                "status": "blocked_missing_code",
                "oauth_request_id": request_record["oauth_request_id"],
                "company_id": request_record["company_id"],
                "store_id": request_record["store_id"],
                "summary": "OAuth callback arrived without an authorization code.",
                "real_platform_writes_enabled": False,
                "secret_exposed": False,
            }

        blockers = []
        if not self.settings.ebay_client_id:
            blockers.append("JIEJING_EBAY_CLIENT_ID")
        if not self.settings.ebay_ru_name:
            blockers.append("JIEJING_EBAY_RU_NAME")
        if not self.settings.ebay_client_secret_configured:
            blockers.append("JIEJING_EBAY_CLIENT_SECRET")
        local_token_store = build_local_oauth_token_store_status(self.settings)
        secret_resolver_status = build_vault_secret_resolver_status(self.settings)
        if not secret_resolver_status.get("live_secret_resolution_available"):
            blockers.append("Vault/KMS")
        if not self.settings.ebay_oauth_live_exchange_enabled:
            blockers.append("JIEJING_EBAY_OAUTH_EXCHANGE_LIVE")

        status = "callback_received_exchange_ready" if not blockers else "callback_received_exchange_blocked"
        return {
            "status": status,
            "oauth_request_id": request_record["oauth_request_id"],
            "company_id": request_record["company_id"],
            "store_id": request_record["store_id"],
            "platform": request_record.get("platform") or "ebay",
            "scopes": request_record.get("scopes") or [],
            "code_received": True,
            "code_stored": False,
            "token_exchange_performed": False,
            "token_endpoint": self._token_endpoint(),
            "backend_local_oauth_store": {
                "enabled": bool(local_token_store.get("enabled")),
                "status": local_token_store.get("status"),
                "used_for_callback_storage": False,
                "deprecated_for_oauth_callback": True,
                "secret_exposed": False,
            },
            "backend_secret_ref_resolver": {
                "status": secret_resolver_status.get("status"),
                "local_development_enabled": bool(secret_resolver_status.get("local_development_enabled")),
                "managed_live_resolution_ready": bool(secret_resolver_status.get("managed_live_resolution_ready")),
                "live_secret_resolution_available": bool(secret_resolver_status.get("live_secret_resolution_available")),
                "will_store_refresh_token_by_secret_ref": not blockers,
                "secret_exposed": False,
            },
            "blocked_by": blockers,
            "next_step": "exchange_code_and_store_refresh_token_in_vault" if not blockers else "configure_backend_oauth_and_vault_before_token_exchange",
            "real_platform_writes_enabled": False,
            "notes": [
                "Authorization codes are runtime-only values and should not be stored.",
                "When live exchange is enabled, the backend exchanges the code and stores only the seller refresh token in the configured secret resolver.",
                "The SaaS database stores only secret_ref and connection metadata, never access_token or refresh_token values.",
            ],
            "secret_exposed": False,
        }

    def token_refresh_plan(
        self,
        *,
        company_id: str,
        store_id: str,
        user_id: str,
        secret_refs: list[dict[str, Any]],
        connections: list[dict[str, Any]],
        secret_store_status: dict[str, Any],
    ) -> dict[str, Any]:
        """Build a safe refresh-token plan without reading or minting tokens."""

        refresh_refs = [
            item
            for item in secret_refs
            if str(item.get("provider") or "").lower() == "ebay"
            and str(item.get("purpose") or "").lower() == "ebay_refresh_token"
        ]
        ebay_connections = [
            item
            for item in connections
            if str(item.get("platform") or "").lower() == "ebay"
            and str(item.get("connection_type") or "").lower() == "oauth"
        ]
        hermes_bridge = inspect_hermes_ebay_bridge(self.settings)
        local_token_store = EbayLocalOAuthTokenStore(self.settings)
        local_store_status = local_token_store.status()
        secret_resolver = VaultSecretResolver(self.settings)
        secret_resolver_status = build_vault_secret_resolver_status(self.settings)
        secret_resolver_record_ready = bool(
            refresh_refs and secret_resolver.has_resolvable_secret(secret_ref=refresh_refs[0])
        )
        local_store_ready = bool(
            local_store_status.get("enabled")
            and refresh_refs
            and local_token_store.has_usable_token()
            and self.settings.ebay_token_refresh_live_enabled
        )
        env_refresh_ready = bool(
            self.settings.ebay_env_refresh_token_allowed
            and self.settings.ebay_client_id
            and self.settings.ebay_client_secret_configured
            and self.settings.ebay_token_refresh_live_enabled
        )
        secret_ref_refresh_ready = bool(
            refresh_refs
            and self.settings.ebay_client_id
            and self.settings.ebay_client_secret_configured
            and self.settings.ebay_token_refresh_live_enabled
            and secret_resolver.can_resolve_secret_values()
            and secret_resolver_record_ready
        )
        hermes_refresh_ready = bool(hermes_bridge.get("can_resolve_access_token") and self.settings.ebay_token_refresh_live_enabled)
        backend_access_token_available = bool(self.settings.ebay_env_access_token_allowed or hermes_bridge.get("credential_present"))
        blockers = []
        if self.settings.ebay_env_access_token_blocked:
            blockers.append("JIEJING_EBAY_ENV_ACCESS_TOKEN_DISABLED_IN_PRODUCTION")
        if self.settings.ebay_env_refresh_token_blocked:
            blockers.append("JIEJING_EBAY_ENV_REFRESH_TOKEN_DISABLED_IN_PRODUCTION")
        if not (refresh_refs or self.settings.ebay_refresh_token_configured or hermes_bridge.get("refresh_ready") or backend_access_token_available):
            blockers.append("ebay_refresh_token_secret_ref")
        if not self.settings.ebay_client_id and not hermes_bridge.get("client_id_present") and not backend_access_token_available:
            blockers.append("JIEJING_EBAY_CLIENT_ID")
        if not self.settings.ebay_client_secret_configured and not hermes_bridge.get("client_secret_present") and not backend_access_token_available:
            blockers.append("JIEJING_EBAY_CLIENT_SECRET")
        if self.settings.is_production_like and not secret_store_status.get("can_store_raw_secret"):
            blockers.append("Vault/KMS")
        if not self.settings.ebay_token_refresh_live_enabled and not backend_access_token_available:
            blockers.append("JIEJING_EBAY_TOKEN_REFRESH_LIVE")
        if hermes_bridge.get("refresh_ready") and not hermes_bridge.get("can_resolve_access_token"):
            blockers.extend(item for item in hermes_bridge.get("blocked_by", []) if item not in blockers)

        refresh_ready = bool(backend_access_token_available or env_refresh_ready or secret_ref_refresh_ready or hermes_refresh_ready or local_store_ready)
        if not refresh_ready and not blockers:
            blockers.append("token_refresh_source_not_ready")

        status = "refresh_blocked" if blockers else "refresh_ready"
        token_source = (
            "backend_env_access_token"
            if self.settings.ebay_env_access_token_allowed
            else "backend_legacy_credential_bridge"
            if hermes_bridge.get("can_resolve_access_token")
            else "backend_env_refresh_token"
            if env_refresh_ready
            else "backend_jiejing_local_oauth_store"
            if local_store_ready
            else "backend_jiejing_secret_ref_resolver"
            if secret_ref_refresh_ready
            else "not_ready"
        )
        return {
            "status": status,
            "platform": "ebay",
            "environment": self.settings.ebay_oauth_environment,
            "company_id": company_id,
            "store_id": store_id,
            "user_id": user_id,
            "token_endpoint": self._token_endpoint(),
            "grant_type": "refresh_token",
            "secret_refs_found": len(refresh_refs),
            "connection_records_found": len(ebay_connections),
            "secret_ref_ids": [item.get("secret_ref") for item in refresh_refs],
            "token_source": token_source,
            "backend_access_token_available": backend_access_token_available,
            "backend_legacy_bridge": {
                "enabled": bool(hermes_bridge.get("bridge_enabled")),
                "status": hermes_bridge.get("status"),
                "can_resolve_access_token": bool(hermes_bridge.get("can_resolve_access_token")),
                "can_refresh_access_token": bool(hermes_bridge.get("can_refresh_access_token")),
                "credential_source": hermes_bridge.get("credential_source"),
                "policy_snapshot_present": bool(hermes_bridge.get("policy_snapshot_present")),
                "listing_rules_snapshot_present": bool(hermes_bridge.get("listing_rules_snapshot_present")),
                "secret_exposed": False,
            },
            "backend_local_oauth_store": {
                "enabled": bool(local_store_status.get("enabled")),
                "status": local_store_status.get("status"),
                "record_count": local_store_status.get("record_count"),
                "latest_secret_ref": local_store_status.get("latest_secret_ref"),
                "secret_exposed": False,
            },
            "backend_secret_ref_resolver": {
                "status": secret_resolver_status.get("status"),
                "local_development_enabled": bool(secret_resolver_status.get("local_development_enabled")),
                "live_secret_resolution_available": bool(secret_resolver_status.get("live_secret_resolution_available")),
                "returns_raw_secret_to_frontend": False,
                "returns_raw_secret_to_runtime": False,
                "secret_exposed": False,
            },
            "blocked_by": blockers,
            "refresh_token_read_from_vault": False,
            "access_token_returned_to_frontend": False,
            "access_token_stored_in_database": False,
            "token_refresh_performed": False,
            "real_platform_writes_enabled": False,
            "next_step": "complete_backend_credential_bridge_or_vault_refresh" if blockers else "run_backend_refresh_and_store_access_token_cache",
            "notes": [
                "Refresh tokens must live in Vault/KMS, not in browser, SQLite, Runtime, or reports.",
                "The backend may mint short-lived access tokens for task-scoped use after Vault and live adapter are ready.",
                "Refreshing an access token is not a platform write, but it still touches account credentials and must be audited.",
                "Scope upgrades require a separate seller consent flow and confirmation record.",
            ],
            "secret_exposed": False,
        }

    def token_refresh_execution_plan(
        self,
        *,
        company_id: str,
        store_id: str,
        user_id: str,
        secret_refs: list[dict[str, Any]],
        connections: list[dict[str, Any]],
        secret_store_status: dict[str, Any],
    ) -> dict[str, Any]:
        """Build the backend-only HTTP contract for future token refresh.

        The local MVP does not read the refresh token, does not call eBay, and
        does not return an access token. This plan exists so the production
        backend can implement the boundary without letting token handling leak
        into the browser, Runtime, reports, or logs.
        """

        plan = self.token_refresh_plan(
            company_id=company_id,
            store_id=store_id,
            user_id=user_id,
            secret_refs=secret_refs,
            connections=connections,
            secret_store_status=secret_store_status,
        )
        blocked_by = list(plan.get("blocked_by") or [])
        status = "ready_for_backend_refresh_adapter" if not blocked_by else "blocked_contract_only"
        return {
            "plan_version": "2026-05-15-ebay-token-refresh-execution-plan",
            "platform": "ebay",
            "status": status,
            "company_id": company_id,
            "store_id": store_id,
            "user_id": user_id,
            "environment": self.settings.ebay_oauth_environment,
            "token_endpoint": self._token_endpoint(),
            "grant_type": "refresh_token",
            "backend_steps": [
                {
                    "step_order": 1,
                    "key": "check_tenant_store_scope",
                    "label": "Check user/company/store permission before touching credentials",
                    "status": "planned",
                    "backend_only": True,
                },
                {
                    "step_order": 2,
                    "key": "resolve_ebay_client_secret",
                    "label": "Resolve eBay client secret from backend secret config or Vault/KMS",
                    "status": "planned" if self.settings.ebay_client_secret_configured else "blocked",
                    "backend_only": True,
                    "returns_secret": False,
                },
                {
                    "step_order": 3,
                    "key": "resolve_refresh_token",
                    "label": "Resolve seller refresh token from Vault/KMS by secret_ref",
                    "status": "planned" if plan.get("secret_refs_found") else "blocked",
                    "backend_only": True,
                    "returns_secret": False,
                },
                {
                    "step_order": 4,
                    "key": "post_token_endpoint",
                    "label": "POST to eBay OAuth token endpoint from backend only",
                    "status": "planned" if status == "ready_for_backend_refresh_adapter" else "blocked",
                    "backend_only": True,
                    "http_call_performed": False,
                },
                {
                    "step_order": 5,
                    "key": "cache_short_lived_access_token",
                    "label": "Cache short-lived access token in backend runtime cache",
                    "status": "planned" if status == "ready_for_backend_refresh_adapter" else "blocked",
                    "backend_only": True,
                    "stores_token_in_database": False,
                },
            ],
            "http_request_contract": {
                "method": "POST",
                "url": self._token_endpoint(),
                "headers": [
                    {"name": "Authorization", "value": "Basic <base64(client_id:client_secret)>", "redacted": True},
                    {"name": "Content-Type", "value": "application/x-www-form-urlencoded", "redacted": False},
                ],
                "body": {
                    "grant_type": "refresh_token",
                    "refresh_token": "<refresh_token_from_vault>",
                    "scope": "<task_scoped_readonly_scopes_when_needed>",
                },
                "body_redacted": True,
                "timeout_seconds": 20,
                "retry_policy": {"max_attempts": 2, "retry_on": ["timeout", "5xx"], "do_not_retry_on": ["invalid_grant", "invalid_client"]},
            },
            "token_boundary": {
                "refresh_token_read_from_vault": False,
                "token_refresh_performed": False,
                "access_token_returned_to_frontend": False,
                "access_token_returned_to_runtime": False,
                "access_token_stored_in_database": False,
                "access_token_cache": "backend_memory_or_redis_cache_only",
            },
            "audit_policy": {
                "audit_required": True,
                "record_token_endpoint": True,
                "record_http_status_only": True,
                "record_token_values": False,
                "record_secret_ref_ids": True,
            },
            "blocked_by": blocked_by,
            "live_refresh_performed": False,
            "secret_exposed": False,
            "real_platform_writes_enabled": False,
            "next_step": "implement_backend_vault_read_and_oauth_http_client" if blocked_by else "run_backend_refresh_and_cache_access_token",
        }

    def _authorization_url(self, scopes: list[str], state_nonce: str) -> str:
        base = "https://auth.sandbox.ebay.com/oauth2/authorize" if self.settings.ebay_oauth_environment == "sandbox" else "https://auth.ebay.com/oauth2/authorize"
        params = {
            "client_id": self.settings.ebay_client_id,
            "redirect_uri": self.settings.ebay_ru_name,
            "response_type": "code",
            "scope": " ".join(scopes),
            "state": state_nonce,
            "prompt": "login",
        }
        return f"{base}?{urllib.parse.urlencode(params)}"

    def _token_endpoint(self) -> str:
        if self.settings.ebay_oauth_environment == "sandbox":
            return "https://api.sandbox.ebay.com/identity/v1/oauth2/token"
        return "https://api.ebay.com/identity/v1/oauth2/token"

    def _normalize_scopes(self, requested_scopes: list[str] | None) -> list[str]:
        if not requested_scopes:
            return list(READ_ONLY_SCOPES)
        scopes = []
        for scope in requested_scopes:
            text = str(scope).strip()
            if not text:
                continue
            if self._looks_high_risk_write_scope(text):
                continue
            scopes.append(text)
        if "https://api.ebay.com/oauth/api_scope" not in scopes:
            scopes.insert(0, "https://api.ebay.com/oauth/api_scope")
        identity_scope = "https://api.ebay.com/oauth/api_scope/commerce.identity.readonly"
        if identity_scope not in scopes:
            scopes.append(identity_scope)
        return scopes or list(READ_ONLY_SCOPES)

    def _normalize_publish_scopes(self, requested_scopes: list[str] | None) -> list[str]:
        allowed = set(PUBLISH_SCOPES)
        if not requested_scopes:
            return list(PUBLISH_SCOPES)
        scopes = []
        for scope in requested_scopes:
            text = str(scope).strip()
            if text and text in allowed:
                scopes.append(text)
        for scope in PUBLISH_SCOPES:
            if scope not in scopes:
                scopes.append(scope)
        return scopes

    def _looks_high_risk_write_scope(self, scope: str) -> bool:
        normalized = scope.lower()
        if normalized.endswith(".readonly") or ".readonly" in normalized:
            return False
        return any(marker in normalized for marker in HIGH_RISK_WRITE_SCOPE_MARKERS)
