"""eBay OAuth callback execution boundary for Jiejing SaaS."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any

from .config import SaaSSettings
from .ebay_account_deletion import fetch_ebay_identity_hashes
from .ebay_oauth import EbayOAuthPlanner, UNPUBLISHED_DRAFT_SCOPES
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
        claim = repository.claim_oauth_callback_exchange(state_nonce=state) if request_record else {}
        claimed_request = claim.get("oauth_request") if isinstance(claim.get("oauth_request"), dict) else None
        if request_record and not claim.get("claimed"):
            request_record = claimed_request or request_record
            result = _oauth_claim_blocker(request_record=request_record, code=code)
            should_record_callback = False
        else:
            request_record = claimed_request or request_record
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


def _oauth_claim_blocker(*, request_record: dict[str, Any], code: str) -> dict[str, Any]:
    status = str(request_record.get("status") or "")
    if status.startswith(OAUTH_CALLBACK_TERMINAL_PREFIXES):
        blocked_status = "blocked_replayed_state"
        blocked_by = ["oauth_state_already_consumed"]
        summary = "OAuth callback state was already consumed."
    else:
        blocked_status = "blocked_callback_exchange_in_progress"
        blocked_by = ["oauth_callback_exchange_already_claimed"]
        summary = "OAuth callback exchange is already claimed and requires terminal-state review."
    return {
        "oauth_request_id": request_record.get("oauth_request_id"),
        "company_id": request_record.get("company_id"),
        "store_id": request_record.get("store_id"),
        "platform": request_record.get("platform") or "ebay",
        "status": blocked_status,
        "summary": summary,
        "blocked_by": blocked_by,
        "code_received": bool(code),
        "code_stored": False,
        "token_exchange_performed": False,
        "vault_write_performed": False,
        "automatic_retry_allowed": False,
        "manual_reconcile_required": blocked_status == "blocked_callback_exchange_in_progress",
        "record_callback_event": False,
        "access_token_returned_to_frontend": False,
        "refresh_token_returned_to_frontend": False,
        "access_token_returned_to_runtime": False,
        "refresh_token_returned_to_runtime": False,
        "access_token_stored_in_database": False,
        "refresh_token_stored_in_database": False,
        "real_platform_writes_enabled": False,
        "secret_exposed": False,
    }


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
    request_payload = request_record.get("request") if isinstance(request_record.get("request"), dict) else {}
    scope_profile = str(request_payload.get("scope_profile") or "")
    if scope_profile not in {"seller_read_only", "seller_unpublished_draft"}:
        return {
            **base,
            "status": "blocked_retired_oauth_profile",
            "summary": "This legacy OAuth authorization profile is retired and cannot exchange credentials.",
            "blocked_by": ["oauth_legacy_publish_profile_retired"],
            "record_callback_event": True,
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
            "status": "blocked_replayed_state",
            "summary": "OAuth callback state was already consumed.",
            "blocked_by": ["oauth_state_already_consumed"],
            "state_replay_blocked": True,
            "record_callback_event": False,
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
    if not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})",
        created_at,
    ):
        return None
    try:
        created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    if created.tzinfo is None or created.utcoffset() is None:
        return None
    age_seconds = (datetime.now(timezone.utc) - created.astimezone(timezone.utc)).total_seconds()
    if age_seconds < 0:
        return None
    return int(age_seconds)


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
            "next_step": "manual_reconcile_then_start_a_new_authorization_only_if_explicitly_approved",
            "secret_exposed": False,
        }

    token_response = exchange.get("token_response") if isinstance(exchange.get("token_response"), dict) else {}
    request_payload = request_record.get("request") if isinstance(request_record.get("request"), dict) else {}
    scope_profile = str(request_payload.get("scope_profile") or "seller_read_only")
    draft_scope_upgrade = scope_profile == "seller_unpublished_draft"
    actual_granted_scopes = _actual_granted_scopes(token_response)
    if draft_scope_upgrade and actual_granted_scopes != UNPUBLISHED_DRAFT_SCOPES:
        return {
            **callback_result,
            "status": "callback_exchange_granted_scope_blocked",
            "token_exchange_performed": True,
            "vault_write_performed": False,
            "blocked_by": ["oauth_actual_granted_scope_not_exact"],
            "token_response_summary": _token_response_summary(token_response),
            "draft_save_scope_authorized": False,
            "publish_scope_authorized": False,
            "manual_reconcile_required": True,
            "automatic_retry_allowed": False,
            "next_step": "manual_reconcile_granted_scope_before_new_authorization",
            "access_token_returned_to_frontend": False,
            "refresh_token_returned_to_frontend": False,
            "secret_exposed": False,
        }
    refresh_token = str(token_response.get("refresh_token") or "")
    if not refresh_token:
        return {
            **callback_result,
            "status": "callback_exchange_missing_refresh_token",
            "token_exchange_performed": True,
            "vault_write_performed": False,
            "blocked_by": ["oauth_refresh_token_missing"],
            "token_response_summary": _token_response_summary(token_response),
            "next_step": "manual_reconcile_then_start_a_new_authorization_with_offline_scope_only_if_explicitly_approved",
            "secret_exposed": False,
        }

    identity_mapping = fetch_ebay_identity_hashes(
        access_token=str(token_response.get("access_token") or ""),
        environment=settings.ebay_oauth_environment,
        transport=oauth_transport,
    )
    if identity_mapping.get("status") != "identity_mapping_ready" or not identity_mapping.get("ebay_user_id_hash"):
        return {
            **callback_result,
            "status": "callback_exchange_identity_mapping_failed",
            "token_exchange_performed": True,
            "vault_write_performed": False,
            "blocked_by": identity_mapping.get("blocked_by") or ["ebay_identity_mapping_failed"],
            "token_response_summary": _token_response_summary(token_response),
            "next_step": "manual_reconcile_then_start_a_new_authorization_after_identity_api_recovers_only_if_explicitly_approved",
            "access_token_returned_to_frontend": False,
            "refresh_token_returned_to_frontend": False,
            "secret_exposed": False,
        }

    draft_upgrade_boundary: dict[str, Any] = {}
    if draft_scope_upgrade:
        draft_upgrade_boundary = repository.ebay_oauth_scope_upgrade_identity_boundary(
            company_id=request_record["company_id"],
            store_id=request_record["store_id"],
            ebay_user_id_hash=str(identity_mapping.get("ebay_user_id_hash") or ""),
        )
        if draft_upgrade_boundary.get("allowed") is not True:
            return {
                **callback_result,
                "status": "callback_exchange_seller_identity_blocked",
                "token_exchange_performed": True,
                "vault_write_performed": False,
                "blocked_by": draft_upgrade_boundary.get("blocked_by")
                or ["oauth_seller_identity_or_provenance_mismatch"],
                "token_response_summary": _token_response_summary(token_response),
                "draft_save_scope_authorized": False,
                "publish_scope_authorized": False,
                "manual_reconcile_required": True,
                "automatic_retry_allowed": False,
                "next_step": "manual_reconcile_seller_identity_before_new_authorization",
                "access_token_returned_to_frontend": False,
                "refresh_token_returned_to_frontend": False,
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

    terminal_stored_status = "local_secret_resolver_stored" if storage.get("local_development_write_performed") else "managed_vault_stored"
    stored_status = "oauth_scope_upgrade_vault_stored_pending_connection" if draft_scope_upgrade else terminal_stored_status
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
    connection_scopes = actual_granted_scopes if draft_scope_upgrade else request_scopes
    draft_save_scope_authorized = bool(draft_scope_upgrade and actual_granted_scopes == UNPUBLISHED_DRAFT_SCOPES)
    publish_scope_authorized = bool(not draft_scope_upgrade and _has_ebay_publish_scope(connection_scopes))
    connection_status = (
        "draft_save_authorized"
        if draft_save_scope_authorized
        else "publish_authorized"
        if publish_scope_authorized
        else "read_only_authorized"
    )
    connection_metadata = {
        "oauth_request_id": request_record["oauth_request_id"],
        "confirmation_id": str(request_payload.get("confirmation_id") or ""),
        "scope_profile": scope_profile or ("seller_publish_listing" if publish_scope_authorized else "seller_read_only"),
        "authorization_kind": "unpublished_draft" if draft_save_scope_authorized else "publish" if publish_scope_authorized else "read_only",
        "draft_save_scope_authorized": draft_save_scope_authorized,
        "publish_scope_authorized": publish_scope_authorized,
        "public_publish_enabled": False if draft_save_scope_authorized else publish_scope_authorized,
        "credential_source": "jiejing_vault_secret_ref",
        "storage_adapter": storage.get("storage_adapter"),
        "marketplace": request_payload.get("marketplace_id") or "EBAY_US",
        "environment": settings.ebay_oauth_environment,
        "token_endpoint": callback_result.get("token_endpoint"),
        "token_exchange_http_status": exchange.get("http_status"),
        "access_token_ttl_seconds": _safe_int(token_response.get("expires_in")),
        "seller_refresh_credential_ttl_seconds": _safe_int(token_response.get("refresh_token_expires_in")),
        "account_deletion_identity_mapping_status": identity_mapping.get("status"),
        "ebay_user_id_hash": identity_mapping.get("ebay_user_id_hash") or "",
        "ebay_username_hash": identity_mapping.get("ebay_username_hash") or "",
        "registration_marketplace_id": identity_mapping.get("registration_marketplace_id") or "",
        "ebay_account_type": identity_mapping.get("account_type") or "",
        "ebay_account_status": identity_mapping.get("account_status") or "",
        "token_values_returned_to_public_response": False,
        "access_token_stored_in_database": False,
        "refresh_token_stored_in_database": False,
        "real_platform_writes_enabled": False,
        "secret_exposed": False,
    }
    if draft_save_scope_authorized:
        connection = repository.finalize_unpublished_draft_oauth_connection(
            company_id=request_record["company_id"],
            store_id=request_record["store_id"],
            user_id=request_record["created_by"],
            oauth_request_id=request_record["oauth_request_id"],
            secret_ref=str(updated_ref["secret_ref"]),
            scopes=connection_scopes,
            metadata=connection_metadata,
            previous_connection_id=str(draft_upgrade_boundary.get("previous_connection_id") or ""),
            previous_secret_ref=str(draft_upgrade_boundary.get("previous_secret_ref") or ""),
            final_secret_status=terminal_stored_status,
        )
    else:
        connection = repository.create_platform_connection(
            company_id=request_record["company_id"],
            store_id=request_record["store_id"],
            user_id=request_record["created_by"],
            payload={
                "platform": "ebay",
                "connection_type": "oauth",
                "status": connection_status,
                "purpose": "ebay_refresh_token",
                "scopes": connection_scopes,
                "secret_ref": updated_ref["secret_ref"],
                "metadata": connection_metadata,
            },
        )
    backend_connection_binding = {
        "contract_version": "2026-08-10-oauth-callback-connection-binding-v1",
        "oauth_request_id": request_record["oauth_request_id"],
        "connection_id": connection["connection_id"],
        "connection_id_sha256": hashlib.sha256(str(connection["connection_id"]).encode("utf-8")).hexdigest(),
        "credential_ref_sha256": hashlib.sha256(str(updated_ref["secret_ref"]).encode("utf-8")).hexdigest(),
        "seller_identity_sha256": hashlib.sha256(
            str(identity_mapping.get("ebay_user_id_hash") or "").encode("utf-8")
        ).hexdigest(),
        "created_by_backend_callback": True,
        "secret_exposed": False,
    }
    return {
        **callback_result,
        "status": "callback_exchange_completed",
        "connection_status": connection_status,
        "draft_save_scope_authorized": draft_save_scope_authorized,
        "publish_scope_authorized": publish_scope_authorized,
        "token_exchange_performed": True,
        "vault_write_performed": True,
        "token_response_summary": _token_response_summary(token_response),
        "secret_storage": _public_storage(storage),
        "secret_ref": updated_ref,
        "connection": connection,
        "backend_connection_binding": backend_connection_binding,
        "account_deletion_identity_mapping": {
            "status": identity_mapping.get("status"),
            "immutable_selector_ready": bool(identity_mapping.get("ebay_user_id_hash")),
            "raw_identity_returned": False,
            "secret_exposed": False,
        },
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


def _actual_granted_scopes(token_response: dict[str, Any]) -> list[str]:
    raw_scope = token_response.get("scope")
    if type(raw_scope) is not str or not raw_scope.strip():
        return []
    scopes = raw_scope.split()
    if not scopes or len(scopes) != len(set(scopes)):
        return []
    if set(scopes) != set(UNPUBLISHED_DRAFT_SCOPES):
        return []
    return list(UNPUBLISHED_DRAFT_SCOPES)


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
