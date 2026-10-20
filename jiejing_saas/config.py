"""Configuration and product-grade guardrails for Jiejing SaaS backend."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_SESSION_SECRET = "local-dev-session-secret-change-me"


@dataclass(slots=True)
class SaaSSettings:
    environment: str
    session_secret_configured: bool
    session_secret_is_default: bool
    requested_real_platform_writes: bool
    database_engine: str
    database_url_configured: bool
    database_adapter: str
    queue_provider: str
    queue_url_configured: bool
    vault_provider: str
    vault_enabled: bool
    execution_adapter: str
    ebay_oauth_environment: str
    ebay_client_id: str
    ebay_ru_name: str
    ebay_client_secret_configured: bool
    ebay_account_deletion_endpoint_url: str
    ebay_account_deletion_verification_token_configured: bool
    ebay_access_token_configured: bool
    ebay_refresh_token_configured: bool
    ebay_oauth_live_exchange_enabled: bool
    ebay_token_refresh_live_enabled: bool
    ebay_read_only_live_enabled: bool
    ebay_write_live_enabled: bool
    ebay_draft_save_live_enabled: bool
    ebay_controlled_publish_live_enabled: bool
    allow_hermes_adapters: bool
    cors_origin: str
    internal_admin_emails: tuple[str, ...]
    host: str
    port: int
    db_path: Path
    runtime_db_path: Path
    output_root: Path
    support_cache_workspace_enabled: bool = False
    support_message_read_enabled: bool = False

    @classmethod
    def from_env(
        cls,
        *,
        db_path: Path,
        runtime_db_path: Path,
        output_root: Path,
        host: str,
        port: int,
    ) -> "SaaSSettings":
        session_secret = os.environ.get("JIEJING_SAAS_SESSION_SECRET") or ""
        return cls(
            environment=os.environ.get("JIEJING_SAAS_ENV", "local_dev").strip().lower() or "local_dev",
            session_secret_configured=bool(session_secret),
            session_secret_is_default=(not session_secret) or session_secret == DEFAULT_SESSION_SECRET,
            requested_real_platform_writes=_env_bool("JIEJING_ENABLE_REAL_PLATFORM_WRITES", default=False),
            database_engine=os.environ.get("JIEJING_DATABASE_ENGINE", "sqlite").strip().lower() or "sqlite",
            database_url_configured=bool(os.environ.get("JIEJING_DATABASE_URL")),
            database_adapter=os.environ.get("JIEJING_DATABASE_ADAPTER", "sqlite-local").strip().lower() or "sqlite-local",
            queue_provider=os.environ.get("JIEJING_QUEUE_PROVIDER", "local_worker").strip().lower() or "local_worker",
            queue_url_configured=bool(os.environ.get("JIEJING_QUEUE_URL")),
            vault_provider=os.environ.get("JIEJING_VAULT_PROVIDER", "secret_ref_only").strip().lower() or "secret_ref_only",
            vault_enabled=_env_bool("JIEJING_VAULT_ENABLED", default=False),
            execution_adapter=os.environ.get("JIEJING_EXECUTION_ADAPTER", "demo_no_platform_write").strip().lower()
            or "demo_no_platform_write",
            ebay_oauth_environment=os.environ.get("JIEJING_EBAY_OAUTH_ENV", "production").strip().lower() or "production",
            ebay_client_id=os.environ.get("JIEJING_EBAY_CLIENT_ID") or os.environ.get("EBAY_CLIENT_ID") or "",
            ebay_ru_name=os.environ.get("JIEJING_EBAY_RU_NAME") or os.environ.get("EBAY_RU_NAME") or "",
            ebay_client_secret_configured=bool(os.environ.get("JIEJING_EBAY_CLIENT_SECRET") or os.environ.get("EBAY_CLIENT_SECRET")),
            ebay_account_deletion_endpoint_url=(
                os.environ.get("JIEJING_EBAY_ACCOUNT_DELETION_ENDPOINT_URL")
                or "https://app.jiejing.shop/webhooks/ebay/marketplace-account-deletion"
            ).strip(),
            ebay_account_deletion_verification_token_configured=bool(
                os.environ.get("JIEJING_EBAY_ACCOUNT_DELETION_VERIFICATION_TOKEN")
            ),
            ebay_access_token_configured=bool(os.environ.get("JIEJING_EBAY_ACCESS_TOKEN") or os.environ.get("EBAY_ACCESS_TOKEN")),
            ebay_refresh_token_configured=bool(os.environ.get("JIEJING_EBAY_REFRESH_TOKEN") or os.environ.get("EBAY_REFRESH_TOKEN")),
            ebay_oauth_live_exchange_enabled=_env_bool("JIEJING_EBAY_OAUTH_EXCHANGE_LIVE", default=False),
            ebay_token_refresh_live_enabled=_env_bool("JIEJING_EBAY_TOKEN_REFRESH_LIVE", default=False),
            ebay_read_only_live_enabled=_env_bool("JIEJING_EBAY_READ_ONLY_LIVE", default=False),
            ebay_write_live_enabled=_env_bool("JIEJING_EBAY_WRITE_LIVE", default=False),
            ebay_draft_save_live_enabled=_env_bool("JIEJING_EBAY_DRAFT_SAVE_LIVE", default=False),
            ebay_controlled_publish_live_enabled=_env_bool(
                "JIEJING_EBAY_CONTROLLED_PUBLISH_LIVE", default=False
            ),
            allow_hermes_adapters=_env_bool("JIEJING_ALLOW_HERMES_ADAPTERS", default=False),
            cors_origin=os.environ.get("JIEJING_CORS_ORIGIN", "*"),
            internal_admin_emails=_env_csv_lower("JIEJING_INTERNAL_ADMIN_EMAILS"),
            host=host,
            port=port,
            db_path=db_path,
            runtime_db_path=runtime_db_path,
            output_root=output_root,
            support_cache_workspace_enabled=_env_bool("JIEJING_SUPPORT_CACHE_WORKSPACE_ENABLED", default=False),
            support_message_read_enabled=_env_bool("JIEJING_SUPPORT_MESSAGE_READ_ENABLED", default=False),
        )

    @property
    def is_production_like(self) -> bool:
        return self.environment in {"staging", "production"}

    @property
    def ebay_env_access_token_allowed(self) -> bool:
        return self.ebay_access_token_configured and not self.is_production_like

    @property
    def ebay_env_access_token_blocked(self) -> bool:
        return self.ebay_access_token_configured and self.is_production_like

    @property
    def ebay_env_refresh_token_allowed(self) -> bool:
        return self.ebay_refresh_token_configured and not self.is_production_like

    @property
    def ebay_env_refresh_token_blocked(self) -> bool:
        return self.ebay_refresh_token_configured and self.is_production_like

    @property
    def cors_allows_wildcard(self) -> bool:
        return "*" in {item.strip() for item in self.cors_origin.split(",") if item.strip()}

    @property
    def effective_real_platform_writes_enabled(self) -> bool:
        return bool(
            self.requested_real_platform_writes
            and self.ebay_write_live_enabled
            and self.ebay_token_refresh_live_enabled
            and self.is_production_like
        )

    @property
    def effective_ebay_draft_save_enabled(self) -> bool:
        return bool(
            self.ebay_draft_save_live_enabled
            and self.ebay_token_refresh_live_enabled
            and self.ebay_read_only_live_enabled
            and self.is_production_like
        )

    @property
    def effective_ebay_controlled_publish_enabled(self) -> bool:
        """Allow confirmation-gated publishOffer only for a proven existing draft.

        This deliberately stays separate from the broad real-write switch.  It
        cannot create inventory items or offers and is valid only while the
        read-only, token-refresh and unpublished-draft boundaries are live.
        """

        return bool(
            self.ebay_controlled_publish_live_enabled
            and self.ebay_draft_save_live_enabled
            and self.ebay_token_refresh_live_enabled
            and self.ebay_read_only_live_enabled
            and self.is_production_like
            and not self.requested_real_platform_writes
            and not self.ebay_write_live_enabled
        )

    def public_dict(self) -> dict[str, Any]:
        return {
            "environment": self.environment,
            "host": self.host,
            "port": self.port,
            "database_engine": self.database_engine,
            "database_adapter": self.database_adapter,
            "database_url_configured": self.database_url_configured,
            "queue_provider": self.queue_provider,
            "queue_url_configured": self.queue_url_configured,
            "vault_provider": self.vault_provider,
            "vault_enabled": self.vault_enabled,
            "execution_adapter": self.execution_adapter,
            "ebay_oauth_environment": self.ebay_oauth_environment,
            "ebay_client_id_configured": bool(self.ebay_client_id),
            "ebay_ru_name_configured": bool(self.ebay_ru_name),
            "ebay_client_secret_configured": self.ebay_client_secret_configured,
            "ebay_account_deletion_endpoint_url_configured": bool(self.ebay_account_deletion_endpoint_url),
            "ebay_account_deletion_verification_token_configured": self.ebay_account_deletion_verification_token_configured,
            "ebay_access_token_configured": self.ebay_access_token_configured,
            "ebay_env_access_token_allowed": self.ebay_env_access_token_allowed,
            "ebay_env_access_token_blocked": self.ebay_env_access_token_blocked,
            "ebay_refresh_token_configured": self.ebay_refresh_token_configured,
            "ebay_env_refresh_token_allowed": self.ebay_env_refresh_token_allowed,
            "ebay_env_refresh_token_blocked": self.ebay_env_refresh_token_blocked,
            "ebay_oauth_live_exchange_enabled": self.ebay_oauth_live_exchange_enabled,
            "ebay_token_refresh_live_enabled": self.ebay_token_refresh_live_enabled,
            "ebay_read_only_live_enabled": self.ebay_read_only_live_enabled,
            "ebay_write_live_enabled": self.ebay_write_live_enabled,
            "ebay_draft_save_live_enabled": self.ebay_draft_save_live_enabled,
            "ebay_controlled_publish_live_enabled": self.ebay_controlled_publish_live_enabled,
            "allow_hermes_adapters": self.allow_hermes_adapters,
            # Cache/draft access is not live message-read or send permission.
            "support_cache_workspace_enabled": self.support_cache_workspace_enabled,
            "support_message_read_enabled": self.support_message_read_enabled,
            "internal_admin_allowlist_configured": bool(self.internal_admin_emails),
            "cors_origin_configured": bool(self.cors_origin),
            "cors_allows_wildcard": self.cors_allows_wildcard,
            "runtime_independent_from_hermes": not self.allow_hermes_adapters,
            "requested_real_platform_writes": self.requested_real_platform_writes,
            "effective_real_platform_writes_enabled": self.effective_real_platform_writes_enabled,
            "effective_ebay_draft_save_enabled": self.effective_ebay_draft_save_enabled,
            "effective_ebay_controlled_publish_enabled": self.effective_ebay_controlled_publish_enabled,
            "session_secret_configured": self.session_secret_configured,
            "session_secret_is_default": self.session_secret_is_default,
            "secret_exposed": False,
        }


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_csv_lower(name: str) -> tuple[str, ...]:
    raw = os.environ.get(name, "")
    values: list[str] = []
    for item in raw.replace(";", ",").split(","):
        value = item.strip().lower()
        if value and value not in values:
            values.append(value)
    return tuple(values)
