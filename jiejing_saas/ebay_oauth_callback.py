"""eBay OAuth callback execution boundary for Jiejing SaaS."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .config import SaaSSettings
from .ebay_oauth import EbayOAuthPlanner
from .ebay_oauth_token_store import EbayLocalOAuthTokenStore, OAuthTransport
from .repository import SaaSRepository
from .secret_store import SecretStoreBoundary
from .vault_secret_resolver import SecretTransport, VaultSecretResolver


OAUTH_CALLBACK_STATE_TTL_SECONDS = 15 * 60
OAUTH_CALLBACK_PENDING_STATUSES = {"ready_to_redirect", "blocked_missing_oauth_config"}
OAUTH_CALLBACK_TERMINAL_PREFIXES = (
    "callback_",
    "blocked_replayed",
    "blocked_invalid_expired",
    "seller_declined",
)


def process_ebay_oauth_callback(
    *,
    repository: SaaSRepository,
    settings: SaaSSettings,
    secret_store_boundary: SecretStoreBoundary,
    ebay_oauth_planner: EbayOAuthPlanner,
    state: str,
    code: str,
    error: str,
    oauth_transport: OAuthTransport | None = None,
    vault_transport: SecretTransport | None = None,
) -> dict[str, Any]:
    request_record = repository.get_oauth_authorization_request_by_state(state_nonce=state)
    state_block = _oauth_state_blocker(request_record=request_record, code=code)
    should_record_callback = True
    if state_block:
        result = state_block
        should_record_callback = bool(state_block.get("record_callback_event"))
    else:
        result = ebay_oauth_planner.callback_result(
            request_record=request_record,
            code=code or None,
            error=error or None,
            secret_store_status=secret_store_boundary.status(),
        )
        if request_record and result.get("status") == "callback_received_exchange_ready" and code:
            result = _exchange_and_store_refresh_token(
                repository=repository,
                settings=settings,
                request_record=request_record,
                callback_result=result,
                code=code,
                oauth_transport=oauth_transport,
                vault_transport=vault_transport,
            )
    if request_record and result.get("oauth_request_id") and should_record_callback:
        repository.update_oauth_authorization_request(
            oauth_request_id=str(result["oauth_request_id"]),
            status=str(result.get("status") or "callback_received"),
            details=result,
        )
    return result


def _oauth_state_blocker(*, request_record: dict[str, Any] | None, code: str) -> dict[str, Any] | None:
    if not request_record:
        return None
    status = str(request_record.get("status") or "")
    base = {
        "oauth_request_id": request_record["oauth_request_id"],
        "company_id": request_record["company_id"],
        "store_id": request_record["store_id"],
        "platform": request_record.get("platform") or "ebay",
        "code_received": bool(code),
        "code_stored": False,
        "token_exchange_performed": False,
        "vault_write_performed": False,
        "access_token_returned_to_frontend": False,
        "refresh_token_returned_to_frontend": False,
        "access_token_returned_to_runtime": False,
        "refresh_token_returned_to_runtime": False,
        "access_token_stored_in_database": False,
        "refresh_token_stored_in_database": False,
        "real_platform_writes_enabled": False,
        "secret_exposed": False,
    }
    if status.startswith(OAUTH_CALLBACK_TERMINAL_PREFIXES):
        return {
            **base,
            "status": "blocked_replayed_state",
            "summary": "OAuth callback state was already consumed.",
            "blocked_by": ["oauth_state_already_consumed"],
            "state_replay_blocked": True,
            "record_callback_event": False,
        }
    if status and status not in OAUTH_CALLBACK_PENDING_STATUSES:
        return {
            **base,
            "status": "blocked_invalid_state_status",
            "summary": "OAuth callback state is not in a pending status.",
            "blocked_by": ["oauth_state_not_pending"],
            "record_callback_event": True,
        }
    age_seconds = _oauth_state_age_seconds(request_record)
    if age_seconds is None or age_seconds > OAUTH_CALLBACK_STATE_TTL_SECONDS:
        return {
            **base,
            "status": "blocked_invalid_expired_state",
            "summary": "OAuth callback state expired before token exchange.",
            "blocked_by": ["oauth_state_expired"],
            "state_age_seconds": age_seconds,
            "state_ttl_seconds": OAUTH_CALLBACK_STATE_TTL_SECONDS,
            "record_callback_event": True,
        }
    return None


def _oauth_state_age_seconds(request_record: dict[str, Any]) -> int | None:
    created_at = str(request_record.get("created_at") or "")
    if not created_at:
        return None
    try:
        created = datetime.fromisoformat(created_at)
    except ValueError:
        return None
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return max(0, int((datetime.now(timezone.utc) - created.astimezone(timezone.utc)).total_seconds()))


def _exchange_and_store_refresh_token(
    *,
    repository: SaaSRepository,
    settings: SaaSSettings,
    request_record: dict[str, Any],
    callback_result: dict[str, Any],
    code: str,
    oauth_transport: OAuthTransport | None,
    vault_transport: SecretTransport | None,
) -> dict[str, Any]:
    exchanger = EbayLocalOAuthTokenStore(settings, transport=oauth_transport)
    exchange = exchanger.exchange_authorization_code(code=code)
    if not exchange.get("ok"):
        return {
            **callback_result,
            "status": "callback_received_exchange_failed",
            "token_exchange_performed": False,
            "vault_write_performed": False,
            "blocked_by": exchange.get("blocked_by") or ["oauth_token_exchange_failed"],
            "next_step": "check_jiejing_oauth_config_and_retry_callback",
            "secret_exposed": False,
        }

    token_response = exchange.get("token_response") if isinstance(exchange.get("token_response"), dict) else {}
    refresh_token = str(token_response.get("refresh_token") or "")
    if not refresh_token:
        return {
            **callback_result,
            "status": "callback_exchange_missing_refresh_token",
            "token_exchange_performed": True,
            "vault_write_performed": False,
            "blocked_by": ["oauth_refresh_token_missing"],
            "token_response_summary": _token_response_summary(token_response),
            "next_step": "retry_oauth_authorization_with_offline_refresh_token_scope",
            "secret_exposed": False,
        }

    secret_ref = repository.create_secret_reference(
        company_id=request_record["company_id"],
        store_id=request_record["store_id"],
        user_id=request_record["created_by"],
        provider="ebay",
        purpose="ebay_refresh_token",
        status="oauth_exchange_pending_vault_write",
        metadata={
            "oauth_request_id": request_record["oauth_request_id"],
            "credential_owner": "jiejing_saas_backend",
            "storage_adapter": "pending_vault_secret_resolver",
            "token_values_returned_to_public_response": False,
            "access_token_stored_in_database": False,
            "refresh_token_stored_in_database": False,
            "real_platform_writes_enabled": False,
            "secret_exposed": False,
        },
    )
    storage = VaultSecretResolver(settings, transport=vault_transport).store_secret(
        secret_ref=secret_ref,
        secret_value=refresh_token,
        created_by=request_record["created_by"],
        metadata={
            "oauth_request_id": request_record["oauth_request_id"],
            "token_endpoint": callback_result.get("token_endpoint"),
            "scope_count": len(request_record.get("scopes") if isinstance(request_record.get("scopes"), list) else []),
            "token_exchange_http_status": exchange.get("http_status"),
            "token_values_returned_to_public_response": False,
        },
    )
    if storage.get("status") not in {"ready", "stored"}:
        failed_ref = repository.update_secret_reference_status(
            company_id=request_record["company_id"],
            store_id=request_record["store_id"],
            secret_ref=secret_ref["secret_ref"],
            status="oauth_exchange_vault_write_failed",
            user_id=request_record["created_by"],
            metadata_patch={
                "oauth_request_id": request_record["oauth_request_id"],
                "storage_status": storage.get("status"),
                "blocked_by": storage.get("blocked_by") or [],
                "token_values_returned_to_public_response": False,
                "refresh_token_stored_in_database": False,
                "secret_exposed": False,
            },
        )
        return {
            **callback_result,
            "status": "callback_exchange_vault_write_failed",
            "token_exchange_performed": True,
            "vault_write_performed": False,
            "secret_ref": failed_ref,
            "secret_storage": _public_storage(storage),
            "blocked_by": storage.get("blocked_by") or ["vault_secret_write_failed"],
            "token_response_summary": _token_response_summary(token_response),
            "next_step": "configure_jiejing_vault_or_local_secret_resolver_then_reauthorize",
            "access_token_returned_to_frontend": False,
            "refresh_token_returned_to_frontend": False,
            "access_token_returned_to_runtime": False,
            "refresh_token_returned_to_runtime": False,
            "secret_exposed": False,
        }

    stored_status = "local_secret_resolver_stored" if storage.get("local_development_write_performed") else "managed_vault_stored"
    updated_ref = repository.update_secret_reference_status(
        company_id=request_record["company_id"],
        store_id=request_record["store_id"],
        secret_ref=secret_ref["secret_ref"],
        status=stored_status,
        user_id=request_record["created_by"],
        metadata_patch={
            "oauth_request_id": request_record["oauth_request_id"],
            "credential_owner": "jiejing_saas_backend",
            "storage_adapter": storage.get("storage_adapter"),
            "token_endpoint": callback_result.get("token_endpoint"),
            "token_exchange_http_status": exchange.get("http_status"),
            "access_token_ttl_seconds": _safe_int(token_response.get("expires_in")),
            "seller_refresh_credential_ttl_seconds": _safe_int(token_response.get("refresh_token_expires_in")),
            "token_values_returned_to_public_response": False,
            "access_token_stored_in_database": False,
            "refresh_token_stored_in_database": False,
            "secret_exposed": False,
        },
    )
    request_scopes = request_record.get("scopes") if isinstance(request_record.get("scopes"), list) else []
    publish_scope_authorized = _has_ebay_publish_scope(request_scopes)
    connection_status = "publish_authorized" if publish_scope_authorized else "read_only_authorized"
    request_payload = request_record.get("request") if isinstance(request_record.get("request"), dict) else {}
    connection = repository.create_platform_connection(
        company_id=request_record["company_id"],
        store_id=request_record["store_id"],
        user_id=request_record["created_by"],
        payload={
            "platform": "ebay",
            "connection_type": "oauth",
            "status": connection_status,
            "purpose": "ebay_refresh_token",
            "scopes": request_scopes,
            "secret_ref": updated_ref["secret_ref"],
            "metadata": {
                "oauth_request_id": request_record["oauth_request_id"],
                "scope_profile": request_payload.get("scope_profile") or ("seller_publish_listing" if publish_scope_authorized else "seller_read_only"),
                "publish_scope_authorized": publish_scope_authorized,
                "credential_source": "jiejing_vault_secret_ref",
                "storage_adapter": storage.get("storage_adapter"),
                "marketplace": request_payload.get("marketplace_id") or "EBAY_US",
                "environment": settings.ebay_oauth_environment,
                "token_endpoint": callback_result.get("token_endpoint"),
                "token_exchange_http_status": exchange.get("http_status"),
                "access_token_ttl_seconds": _safe_int(token_response.get("expires_in")),
                "seller_refresh_credential_ttl_seconds": _safe_int(token_response.get("refresh_token_expires_in")),
                "token_values_returned_to_public_response": False,
                "access_token_stored_in_database": False,
                "refresh_token_stored_in_database": False,
                "real_platform_writes_enabled": False,
                "secret_exposed": False,
            },
        },
    )
    return {
        **callback_result,
        "status": "callback_exchange_completed",
        "connection_status": connection_status,
        "publish_scope_authorized": publish_scope_authorized,
        "token_exchange_performed": True,
        "vault_write_performed": True,
        "token_response_summary": _token_response_summary(token_response),
        "secret_storage": _public_storage(storage),
        "secret_ref": updated_ref,
        "connection": connection,
        "next_step": "run_ebay_read_only_credential_preflight",
        "access_token_returned_to_frontend": False,
        "refresh_token_returned_to_frontend": False,
        "access_token_returned_to_runtime": False,
        "refresh_token_returned_to_runtime": False,
        "access_token_stored_in_database": False,
        "refresh_token_stored_in_database": False,
        "real_platform_writes_enabled": False,
        "secret_exposed": False,
    }


def _has_ebay_publish_scope(scopes: list[Any]) -> bool:
    return any(str(scope).strip().lower().endswith("/sell.inventory") for scope in scopes)


def _token_response_summary(token_response: dict[str, Any]) -> dict[str, Any]:
    return {
        "access_token_present": bool(token_response.get("access_token")),
        "refresh_token_present": bool(token_response.get("refresh_token")),
        "access_token_ttl_seconds": _safe_int(token_response.get("expires_in")),
        "seller_refresh_credential_ttl_seconds": _safe_int(token_response.get("refresh_token_expires_in")),
        "token_values_returned_to_public_response": False,
        "secret_exposed": False,
    }


def _public_storage(storage: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": storage.get("status"),
        "secret_ref": storage.get("secret_ref"),
        "provider": storage.get("provider"),
        "purpose": storage.get("purpose"),
        "source": storage.get("source"),
        "storage_adapter": storage.get("storage_adapter"),
        "managed_vault_write_performed": bool(storage.get("managed_vault_write_performed")),
        "local_development_write_performed": bool(storage.get("local_development_write_performed")),
        "secret_value_returned": False,
        "secret_exposed": False,
    }


def _safe_int(value: Any) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None
