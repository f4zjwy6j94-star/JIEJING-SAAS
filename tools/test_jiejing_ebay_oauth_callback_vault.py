#!/usr/bin/env python3
"""Regression for eBay OAuth callback exchange -> Vault secret_ref -> connection."""

from __future__ import annotations

import json
import hashlib
import os
import sqlite3
import sys
import threading
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.config import SaaSSettings  # noqa: E402
from jiejing_saas.commercial_launch_gate import build_commercial_launch_gate  # noqa: E402
from jiejing_saas.api_server import SaaSBackendHandler  # noqa: E402
from jiejing_saas.ebay_oauth import EbayOAuthPlanner, UNPUBLISHED_DRAFT_SCOPES  # noqa: E402
from jiejing_saas.ebay_oauth_callback import process_ebay_oauth_callback  # noqa: E402
from jiejing_saas.repository import SaaSRepository  # noqa: E402
from jiejing_saas.secret_store import SecretStoreBoundary  # noqa: E402
from jiejing_saas.vault_secret_resolver import VaultSecretResolver  # noqa: E402


OUT = ROOT / "output" / "test-ebay-oauth-callback-vault"
ENV_KEYS = (
    "JIEJING_SAAS_ENV",
    "JIEJING_EBAY_CLIENT_ID",
    "JIEJING_EBAY_CLIENT_SECRET",
    "JIEJING_EBAY_RU_NAME",
    "JIEJING_EBAY_OAUTH_EXCHANGE_LIVE",
    "JIEJING_VAULT_LOCAL_SECRET_RESOLVER_ENABLED",
    "JIEJING_VAULT_LOCAL_SECRET_STORE_PATH",
    "JIEJING_VAULT_ENABLED",
    "JIEJING_VAULT_PROVIDER",
    "JIEJING_VAULT_LIVE_RESOLVE_ENABLED",
    "JIEJING_VAULT_ADDR",
    "JIEJING_VAULT_TOKEN",
    "JIEJING_VAULT_MOUNT",
    "JIEJING_VAULT_KEYSPACE",
    "JIEJING_VAULT_KV_VERSION",
    "JIEJING_NEW_EBAY_OAUTH_OPERATOR_APPROVED",
    "JIEJING_NEW_EBAY_ACCOUNT_OAUTH_COMPLETED",
)
FORBIDDEN = (
    "CALLBACK-ACCESS-TOKEN-MUST-NOT-LEAK",
    "CALLBACK-REFRESH-TOKEN-MUST-NOT-LEAK",
    "CALLBACK-CLIENT-SECRET-MUST-NOT-LEAK",
    "CALLBACK-MANAGED-ACCESS-MUST-NOT-LEAK",
    "CALLBACK-MANAGED-REFRESH-MUST-NOT-LEAK",
    "CALLBACK-MANAGED-SECRET-MUST-NOT-LEAK",
    "VAULT-CALLBACK-TOKEN-MUST-NOT-LEAK",
    "CALLBACK-IMMUTABLE-USER-MUST-NOT-LEAK",
    "CALLBACK-USERNAME-MUST-NOT-LEAK",
    "Bearer ",
    "Basic ",
)


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    previous = {key: os.environ.get(key) for key in ENV_KEYS}
    local_secret_path = OUT / "local-secret-resolver.json"
    try:
        _clear_env()
        OUT.mkdir(parents=True, exist_ok=True)

        local_result = _run_local_secret_resolver_callback(local_secret_path=local_secret_path)
        if local_result != "ok":
            return fail(local_result)

        draft_scope_result = _run_unpublished_draft_actual_scope_boundary()
        if draft_scope_result != "ok":
            return fail(draft_scope_result)

        draft_upgrade_result = _run_unpublished_draft_same_seller_upgrade()
        if draft_upgrade_result != "ok":
            return fail(draft_upgrade_result)

        retired_publish_result = _run_retired_publish_profile_callback_blocked()
        if retired_publish_result != "ok":
            return fail(retired_publish_result)

        concurrent_result = _run_same_state_callback_exactly_once(
            local_secret_path=OUT / "concurrent-local-secret-resolver.json"
        )
        if concurrent_result != "ok":
            return fail(concurrent_result)

        crash_result = _run_exchange_crash_requires_manual_reconcile()
        if crash_result != "ok":
            return fail(crash_result)

        expired_result = _run_expired_state_blocked(local_secret_path=local_secret_path)
        if expired_result != "ok":
            return fail(expired_result)

        identity_failure_result = _run_identity_mapping_failure_no_secret(local_secret_path=local_secret_path)
        if identity_failure_result != "ok":
            return fail(identity_failure_result)

        managed_result = _run_managed_vault_callback()
        if managed_result != "ok":
            return fail(managed_result)

        blocked_result = _run_production_local_resolver_blocked()
        if blocked_result != "ok":
            return fail(blocked_result)

        print("PASS jiejing_ebay_oauth_callback_vault")
        return 0
    finally:
        try:
            local_secret_path.unlink(missing_ok=True)
        except OSError:
            pass
        _restore_env(previous)


def _run_local_secret_resolver_callback(*, local_secret_path: Path) -> str:
    _clear_env()
    _base_oauth_env(environment="local_dev")
    os.environ["JIEJING_EBAY_CLIENT_SECRET"] = "CALLBACK-CLIENT-SECRET-MUST-NOT-LEAK"
    os.environ["JIEJING_VAULT_LOCAL_SECRET_RESOLVER_ENABLED"] = "true"
    os.environ["JIEJING_VAULT_LOCAL_SECRET_STORE_PATH"] = str(local_secret_path)
    local_secret_path.unlink(missing_ok=True)
    settings, repo, store, request = _seed_oauth_request(case_key="local-callback", port=8820)
    oauth_transport = _fake_oauth_transport(
        access_token="CALLBACK-ACCESS-TOKEN-MUST-NOT-LEAK",
        refresh_token="CALLBACK-REFRESH-TOKEN-MUST-NOT-LEAK",
    )
    result = process_ebay_oauth_callback(
        repository=repo,
        settings=settings,
        secret_store_boundary=SecretStoreBoundary(settings),
        ebay_oauth_planner=EbayOAuthPlanner(settings),
        state=request["state_nonce"],
        code="UNIT_AUTH_CODE",
        error="",
        oauth_transport=oauth_transport,
    )
    if result.get("status") != "callback_exchange_completed":
        return "local callback should complete exchange and Vault write"
    if result.get("secret_storage", {}).get("storage_adapter") != "local_secret_resolver":
        return "local callback should store through local secret resolver"
    if result.get("secret_ref", {}).get("status") != "local_secret_resolver_stored":
        return "local callback should update secret_ref status"
    if result.get("connection", {}).get("status") != "read_only_authorized":
        return "local callback should create read-only platform connection"
    if result.get("account_deletion_identity_mapping", {}).get("immutable_selector_ready") is not True:
        return "local callback should map the immutable eBay user selector"
    if result.get("access_token_returned_to_frontend") is not False or result.get("refresh_token_returned_to_frontend") is not False:
        return "local callback must not return tokens to frontend"
    public_serialized = json.dumps(result, ensure_ascii=False)
    if any(value in public_serialized for value in FORBIDDEN):
        return "local callback public response leaked a token or secret"

    secret_ref = result.get("secret_ref", {})
    resolved = VaultSecretResolver(settings).resolve_secret(
        secret_ref=secret_ref,
        requested_by="oauth_refresh_service",
        task_scope="unit_callback_verify",
        allowed_purposes=["ebay_refresh_token"],
    )
    if resolved.get("secret_value") != "CALLBACK-REFRESH-TOKEN-MUST-NOT-LEAK":
        return "local secret resolver did not receive the refresh token internally"
    connections = repo.list_connections(company_id=store["company_id"], store_id=store["store_id"])
    if not connections or connections[0].get("secret_ref") != secret_ref.get("secret_ref"):
        return "platform connection should reference the stored secret_ref"
    oauth_boundary = repo.ebay_read_only_oauth_boundary(
        company_id=store["company_id"],
        store_id=store["store_id"],
    )
    if oauth_boundary.get("authorized") is not True:
        return "completed backend OAuth callback should satisfy the strong current-store authorization boundary"
    if oauth_boundary.get("strong_identity_ready") is not True or oauth_boundary.get("backend_provenance_ready") is not True:
        return "strong OAuth boundary must bind immutable identity and backend callback provenance"
    for index in range(501):
        repo.write_audit(
            company_id=store["company_id"],
            store_id=store["store_id"],
            user_id=request["created_by"],
            actor_type="system",
            action_type="unit.unrelated.audit",
            target_type="unit_noise",
            target_id=f"noise-{index}",
            summary="Unrelated audit volume must not hide the OAuth callback proof.",
            details={"secret_exposed": False},
        )
    boundary_after_unrelated_audits = repo.ebay_read_only_oauth_boundary(
        company_id=store["company_id"],
        store_id=store["store_id"],
    )
    if boundary_after_unrelated_audits.get("authorized") is not True:
        return "OAuth boundary must use targeted callback audit evidence beyond the newest 500 unrelated audits"
    os.environ.pop("JIEJING_NEW_EBAY_OAUTH_OPERATOR_APPROVED", None)
    os.environ.pop("JIEJING_NEW_EBAY_ACCOUNT_OAUTH_COMPLETED", None)
    gate = build_commercial_launch_gate(
        settings,
        repo,
        company_id=store["company_id"],
        store_id=store["store_id"],
    )
    oauth_step = _oauth_launch_step(gate)
    if oauth_step.get("status") != "ready":
        return "current-store backend strong proof should satisfy the commercial OAuth gate without env flags"
    other_store = repo.create_store(
        company_id=store["company_id"],
        user_id=request["created_by"],
        payload={"platform": "ebay", "store_name": "unproved-current-store", "marketplace": "EBAY_US"},
    )
    repo.create_platform_data_packet(
        company_id=store["company_id"],
        store_id=other_store["store_id"],
        user_id=request["created_by"],
        packet={
            "platform": "ebay",
            "packet_type": "ebay_read_only_snapshot",
            "source_mode": "official_api",
            "source_label": "official_api",
            "status": "created",
            "company_id": store["company_id"],
            "store_id": other_store["store_id"],
            "present_resource_keys": [
                "store_profile",
                "account_business_policies",
                "inventory_and_offers",
                "orders_and_fulfillment",
                "finances",
                "taxonomy_listing_metadata",
            ],
            "missing_resource_keys": [],
            "sections": [
                {"key": "store_profile", "data": {"seller_account_status": "active"}},
                {
                    "key": "account_business_policies",
                    "data": {
                        "payment_policy_id": "other-payment",
                        "fulfillment_policy_id": "other-fulfillment",
                        "return_policy_id": "other-return",
                    },
                },
            ],
            "freshness": {
                "official_request_count": 5,
                "route_success_count": 5,
                "route_failure_count": 0,
            },
            "lineage": {
                "probe_live_read_performed": True,
                "access_token_used": True,
                "access_token_returned_to_frontend": False,
                "raw_ebay_response_stored": False,
            },
            "safe_for_real_platform_write": False,
            "secret_exposed": False,
        },
    )
    repo.write_audit(
        company_id=store["company_id"],
        store_id=other_store["store_id"],
        user_id=request["created_by"],
        actor_type="system",
        action_type="oauth.token_refresh.executed",
        target_type="store",
        target_id=other_store["store_id"],
        summary="Other-store refresh proof must not satisfy the selected store.",
        details={
            "ok": True,
            "status": "refreshed",
            "source": "backend_vault_secret_ref_refresh",
            "secret_ref_present": True,
            "secret_exposed": False,
        },
    )
    cross_store_gate = build_commercial_launch_gate(
        settings,
        repo,
        company_id=store["company_id"],
        store_id=store["store_id"],
    )
    cross_store_steps = {
        item.get("key"): item
        for item in cross_store_gate.get("new_ebay_account_smoke_runbook") or []
        if isinstance(item, dict)
    }
    if (cross_store_steps.get("official_packet_account_health_snapshot") or {}).get("status") != "blocked":
        return "another store's packet/account-health proof must not satisfy the current-store launch gate"
    current_store_evidence = cross_store_gate.get("current_store_ebay_evidence") or {}
    if current_store_evidence.get("official_packet_ready") is not False:
        return "commercial launch evidence must explicitly fail closed on a cross-store official packet"
    if current_store_evidence.get("refresh_success_ready") is not False:
        return "commercial launch evidence must explicitly fail closed on a cross-store refresh audit"
    other_gate = build_commercial_launch_gate(
        settings,
        repo,
        company_id=store["company_id"],
        store_id=other_store["store_id"],
    )
    if _oauth_launch_step(other_gate).get("status") != "blocked":
        return "a strong OAuth proof from another store must not satisfy the selected current-store gate"
    real_connection_id = str(result.get("connection", {}).get("connection_id") or "")
    now = datetime.now(timezone.utc).isoformat()
    current_packet = repo.create_platform_data_packet(
        company_id=store["company_id"],
        store_id=store["store_id"],
        user_id=request["created_by"],
        packet={
            "platform": "ebay",
            "packet_type": "ebay_read_only_snapshot",
            "source_mode": "official_api",
            "source_label": "official_api",
            "status": "created",
            "company_id": store["company_id"],
            "store_id": store["store_id"],
            "created_at": now,
            "present_resource_keys": [
                "store_profile",
                "account_business_policies",
                "inventory_and_offers",
                "orders_and_fulfillment",
                "finances",
                "taxonomy_listing_metadata",
            ],
            "missing_resource_keys": [],
            "sections": [
                {"key": "store_profile", "data": {"seller_account_status": "active"}},
                {
                    "key": "account_business_policies",
                    "data": {
                        "payment_policy_id": "current-payment",
                        "fulfillment_policy_id": "current-fulfillment",
                        "return_policy_id": "current-return",
                    },
                },
            ],
            "freshness": {
                "official_request_count": 5,
                "route_success_count": 5,
                "route_failure_count": 0,
            },
            "lineage": {
                "probe_live_read_performed": True,
                "access_token_used": True,
                "access_token_returned_to_frontend": False,
                "raw_ebay_response_stored": False,
            },
            "safe_for_real_platform_write": False,
            "secret_exposed": False,
        },
    )
    current_task = repo.create_task(
        company_id=store["company_id"],
        store_id=store["store_id"],
        user_id=request["created_by"],
        task_type="ebay_read_only_live_plan",
        title="Current-store official evidence",
        input_data={},
    )
    current_job = repo.create_queue_job(
        company_id=store["company_id"],
        task_id=current_task["task_id"],
        job_data={
            "kind": "ebay_read_only_live_plan",
            "store_id": store["store_id"],
            "live_read_plan": {
                "store_id": store["store_id"],
                "token_boundary": {"connection_id": real_connection_id},
            },
        },
    )
    repo.update_queue_job(
        job_id=current_job["job_id"],
        company_id=store["company_id"],
        status="completed",
        details={
            "live_read_performed": True,
            "request_count": 5,
            "data_packet_id": current_packet["packet_id"],
            "secret_exposed": False,
        },
    )
    repo.write_audit(
        company_id=store["company_id"],
        store_id=store["store_id"],
        user_id=request["created_by"],
        actor_type="system",
        action_type="ebay.read_only.live.completed",
        target_type="queue_job",
        target_id=current_job["job_id"],
        summary="Current-store packet completed through backend worker.",
        details={
            "request_count": 5,
            "data_packet_id": current_packet["packet_id"],
            "raw_response_stored": False,
            "secret_exposed": False,
        },
    )
    repo.write_audit(
        company_id=store["company_id"],
        store_id=store["store_id"],
        user_id=request["created_by"],
        actor_type="system",
        action_type="oauth.token_refresh.executed",
        target_type="store",
        target_id=store["store_id"],
        summary="Current-store refresh proof bound to the callback-owned connection.",
        details={
            "ok": True,
            "status": "refreshed",
            "source": "backend_vault_secret_ref_refresh",
            "secret_ref_present": True,
            "connection_id_sha256": hashlib.sha256(real_connection_id.encode("utf-8")).hexdigest(),
            "credential_ref_sha256": hashlib.sha256(str(secret_ref["secret_ref"]).encode("utf-8")).hexdigest(),
            "secret_exposed": False,
        },
    )
    bound_gate = build_commercial_launch_gate(
        settings,
        repo,
        company_id=store["company_id"],
        store_id=store["store_id"],
    )
    bound_evidence = bound_gate.get("current_store_ebay_evidence") or {}
    if bound_evidence.get("official_packet_ready") is not True:
        return f"current-store packet must become ready only with exact worker/audit/OAuth connection binding: {bound_evidence.get('blockers')}"
    if bound_evidence.get("account_health_ready") is not True:
        return "current-store safe account health must bind to the same official packet"
    if bound_evidence.get("refresh_success_ready") is not True:
        return "current-store refresh proof must bind to the callback-owned OAuth connection"
    bound_steps = {
        item.get("key"): item
        for item in bound_gate.get("new_ebay_account_smoke_runbook") or []
        if isinstance(item, dict)
    }
    if (bound_steps.get("official_packet_account_health_snapshot") or {}).get("status") != "ready":
        return "fully bound current-store packet/account-health evidence should satisfy the smoke phase"
    duplicate_confirmation = repo.create_confirmation(
        company_id=store["company_id"],
        store_id=store["store_id"],
        task_id=None,
        runtime_run_id="new_ebay_account_oauth_authorization_gate",
        action_type="ebay_oauth_scope_change",
        title="Strong callback must block another OAuth plan",
        item={
            "source": "new_ebay_account_low_risk_smoke",
            "requested_step": "new_account_oauth_authorization_gate",
            "scope_profile": "seller_read_only",
            "secret_exposed": False,
        },
        created_by=request["created_by"],
        default_action="hold",
    )
    duplicate_confirmation = repo.decide_confirmation(
        company_id=store["company_id"],
        confirmation_id=duplicate_confirmation["confirmation_id"],
        decision="approve",
        decided_by=request["created_by"],
        note="Regression only: a real strong boundary must win before approval consumption.",
    )
    oauth_request_count_before_duplicate = len(
        repo.list_oauth_authorization_requests(company_id=store["company_id"], store_id=store["store_id"])
    )
    duplicate_plan = EbayOAuthPlanner(settings).read_only_authorization_plan(
        company_id=store["company_id"],
        store_id=store["store_id"],
        user_id=request["created_by"],
        marketplace_id="EBAY_US",
    )
    try:
        repo.create_approved_read_only_oauth_authorization_request(
            company_id=store["company_id"],
            store_id=store["store_id"],
            user_id=request["created_by"],
            confirmation_id=duplicate_confirmation["confirmation_id"],
            plan=duplicate_plan,
        )
    except ValueError as exc:
        if str(exc) != "oauth_plan_already_authorized":
            return "strong callback duplicate plan must fail with the authorized boundary"
    else:
        return "strong callback evidence must block a duplicate OAuth plan"
    if len(repo.list_oauth_authorization_requests(company_id=store["company_id"], store_id=store["store_id"])) != oauth_request_count_before_duplicate:
        return "strong callback duplicate plan rejection must not persist another request/state"
    forged_connection = repo.create_platform_connection(
        company_id=store["company_id"],
        store_id=store["store_id"],
        user_id=request["created_by"],
        payload={
            "platform": "ebay",
            "connection_type": "oauth",
            "status": "read_only_authorized",
            "secret_ref": secret_ref["secret_ref"],
            "metadata": {
                "oauth_request_id": request["oauth_request_id"],
                "scope_profile": "seller_read_only",
                "credential_source": "jiejing_vault_secret_ref",
                "account_deletion_identity_mapping_status": "identity_mapping_ready",
                "ebay_user_id_hash": "x",
                "token_values_returned_to_public_response": False,
                "secret_exposed": False,
            },
        },
    )
    forged_conn = sqlite3.connect(settings.db_path)
    try:
        with forged_conn:
            forged_conn.execute(
                "delete from platform_connections where connection_id = ?",
                (real_connection_id,),
            )
    finally:
        forged_conn.close()
    forged_boundary = repo.ebay_read_only_oauth_boundary(
        company_id=store["company_id"],
        store_id=store["store_id"],
    )
    if forged_boundary.get("authorized") is not False:
        return "a forged connection borrowing real request/secret/audit evidence must remain blocked"
    if forged_boundary.get("connection_id_sha256") == hashlib.sha256(
        str(forged_connection.get("connection_id") or "").encode("utf-8")
    ).hexdigest():
        return "strong boundary must not identify a merchant-created forged connection as callback-owned"
    db_text = _sqlite_public_dump(settings.db_path)
    if any(value in db_text for value in FORBIDDEN):
        return "SaaS database leaked a raw OAuth token or client secret"

    replay_seen = {"oauth_post": False}

    def replay_transport(request_obj: Any, timeout: float) -> tuple[int, dict[str, str], bytes]:
        replay_seen["oauth_post"] = True
        return _oauth_response(
            access_token="CALLBACK-ACCESS-TOKEN-MUST-NOT-LEAK",
            refresh_token="CALLBACK-REFRESH-TOKEN-MUST-NOT-LEAK",
        )

    replay = process_ebay_oauth_callback(
        repository=repo,
        settings=settings,
        secret_store_boundary=SecretStoreBoundary(settings),
        ebay_oauth_planner=EbayOAuthPlanner(settings),
        state=request["state_nonce"],
        code="UNIT_AUTH_CODE_REPLAY",
        error="",
        oauth_transport=replay_transport,
    )
    if replay.get("status") != "blocked_replayed_state":
        return "second callback with same state should be blocked as replay"
    if replay_seen["oauth_post"]:
        return "replayed callback must not call the eBay token endpoint"
    refetched = repo.get_oauth_authorization_request_by_state(state_nonce=request["state_nonce"])
    if not refetched or refetched.get("status") != "callback_exchange_completed":
        return "replayed callback must not overwrite the original completed OAuth request"
    return "ok"


def _run_same_state_callback_exactly_once(*, local_secret_path: Path) -> str:
    _clear_env()
    _base_oauth_env(environment="local_dev")
    os.environ["JIEJING_EBAY_CLIENT_SECRET"] = "CALLBACK-CLIENT-SECRET-MUST-NOT-LEAK"
    os.environ["JIEJING_VAULT_LOCAL_SECRET_RESOLVER_ENABLED"] = "true"
    os.environ["JIEJING_VAULT_LOCAL_SECRET_STORE_PATH"] = str(local_secret_path)
    local_secret_path.unlink(missing_ok=True)
    settings, repo, store, request = _seed_oauth_request(case_key="concurrent-callback", port=8826)
    initial_get = repo.get_oauth_authorization_request_by_state
    initial_read_barrier = threading.Barrier(2)
    initial_read_count = 0
    initial_read_lock = threading.Lock()

    def synchronized_initial_get(*, state_nonce: str):
        nonlocal initial_read_count
        value = initial_get(state_nonce=state_nonce)
        with initial_read_lock:
            initial_read_count += 1
            should_wait = initial_read_count <= 2
        if should_wait:
            initial_read_barrier.wait(timeout=5)
        return value

    repo.get_oauth_authorization_request_by_state = synchronized_initial_get  # type: ignore[method-assign]
    base_transport = _fake_oauth_transport(
        access_token="CALLBACK-ACCESS-TOKEN-MUST-NOT-LEAK",
        refresh_token="CALLBACK-REFRESH-TOKEN-MUST-NOT-LEAK",
    )
    exchange_entry_count = 0
    exchange_entry_lock = threading.Lock()

    def counted_transport(request_obj: Any, timeout: float) -> tuple[int, dict[str, str], bytes]:
        nonlocal exchange_entry_count
        if request_obj.get_method() == "POST" and "/identity/v1/oauth2/token" in request_obj.full_url:
            with exchange_entry_lock:
                exchange_entry_count += 1
        return base_transport(request_obj, timeout)

    def invoke_callback(_index: int) -> dict[str, Any]:
        return process_ebay_oauth_callback(
            repository=repo,
            settings=settings,
            secret_store_boundary=SecretStoreBoundary(settings),
            ebay_oauth_planner=EbayOAuthPlanner(settings),
            state=request["state_nonce"],
            code="UNIT_AUTH_CODE_CONCURRENT",
            error="",
            oauth_transport=counted_transport,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(invoke_callback, range(2)))
    if exchange_entry_count != 1:
        return "same-state concurrent callbacks must enter token exchange exactly once"
    statuses = [str(item.get("status") or "") for item in results]
    if statuses.count("callback_exchange_completed") != 1:
        return "same-state concurrent callbacks must produce exactly one completed exchange"
    if not any(status in {"blocked_callback_exchange_in_progress", "blocked_replayed_state"} for status in statuses):
        return "the losing same-state callback must fail closed before token exchange"
    refetched = initial_get(state_nonce=request["state_nonce"])
    if not refetched or refetched.get("status") != "callback_exchange_completed":
        return "the winning same-state callback must persist the completed terminal state"
    if len(repo.list_connections(company_id=store["company_id"], store_id=store["store_id"])) != 1:
        return "same-state concurrent callbacks must create exactly one platform connection"
    return "ok"


def _run_unpublished_draft_actual_scope_boundary() -> str:
    _clear_env()
    _base_oauth_env(environment="local_dev")
    os.environ["JIEJING_EBAY_CLIENT_SECRET"] = "CALLBACK-CLIENT-SECRET-MUST-NOT-LEAK"
    os.environ["JIEJING_VAULT_LOCAL_SECRET_RESOLVER_ENABLED"] = "true"
    missing_secret_path = OUT / "draft-missing-scope-secrets.json"
    os.environ["JIEJING_VAULT_LOCAL_SECRET_STORE_PATH"] = str(missing_secret_path)
    missing_secret_path.unlink(missing_ok=True)
    settings, repo, store, request = _seed_unpublished_draft_oauth_request(
        case_key="draft-missing-granted-scope",
        port=8831,
    )
    missing = process_ebay_oauth_callback(
        repository=repo,
        settings=settings,
        secret_store_boundary=SecretStoreBoundary(settings),
        ebay_oauth_planner=EbayOAuthPlanner(settings),
        state=request["state_nonce"],
        code="UNIT_DRAFT_AUTH_CODE_MISSING_SCOPE",
        error="",
        oauth_transport=_fake_oauth_transport(
            access_token="CALLBACK-ACCESS-TOKEN-MUST-NOT-LEAK",
            refresh_token="CALLBACK-REFRESH-TOKEN-MUST-NOT-LEAK",
        ),
    )
    if missing.get("status") != "callback_exchange_granted_scope_blocked":
        return "draft OAuth callback must fail closed when token response omits actual granted scope"
    if repo.list_secret_refs(company_id=store["company_id"], store_id=store["store_id"]):
        return "missing draft granted scope must block before secret_ref/Vault persistence"
    if repo.list_connections(company_id=store["company_id"], store_id=store["store_id"]):
        return "missing draft granted scope must block before connection creation"

    granted_secret_path = OUT / "draft-granted-scope-secrets.json"
    os.environ["JIEJING_VAULT_LOCAL_SECRET_STORE_PATH"] = str(granted_secret_path)
    granted_secret_path.unlink(missing_ok=True)
    settings, repo, store, request = _seed_unpublished_draft_oauth_request(
        case_key="draft-exact-granted-scope",
        port=8832,
    )
    granted = process_ebay_oauth_callback(
        repository=repo,
        settings=settings,
        secret_store_boundary=SecretStoreBoundary(settings),
        ebay_oauth_planner=EbayOAuthPlanner(settings),
        state=request["state_nonce"],
        code="UNIT_DRAFT_AUTH_CODE_EXACT_SCOPE",
        error="",
        oauth_transport=_fake_oauth_transport(
            access_token="CALLBACK-ACCESS-TOKEN-MUST-NOT-LEAK",
            refresh_token="CALLBACK-REFRESH-TOKEN-MUST-NOT-LEAK",
            granted_scopes=UNPUBLISHED_DRAFT_SCOPES,
        ),
    )
    if granted.get("status") != "callback_exchange_completed":
        return "exact actual draft scope must complete callback"
    connection = granted.get("connection") if isinstance(granted.get("connection"), dict) else {}
    metadata = connection.get("metadata") if isinstance(connection.get("metadata"), dict) else {}
    public_result = SaaSBackendHandler._oauth_callback_public_result(object(), granted)
    persisted_request = repo.get_oauth_authorization_request_by_state(state_nonce=request["state_nonce"]) or {}
    internal_boundary = repo.unpublished_draft_execution_credential_boundary(
        company_id=store["company_id"],
        store_id=store["store_id"],
    )
    if connection.get("status") != "draft_save_authorized":
        return "draft OAuth callback must create draft_save_authorized, never publish_authorized"
    if not (
        granted.get("draft_save_scope_authorized") is True
        and granted.get("publish_scope_authorized") is False
        and metadata.get("authorization_kind") == "unpublished_draft"
        and metadata.get("scope_profile") == "seller_unpublished_draft"
        and "confirmation_id" not in metadata
        and "oauth_request_id" not in metadata
        and metadata.get("confirmation_bound") is True
        and metadata.get("oauth_request_bound") is True
        and connection.get("secret_ref")
        and persisted_request.get("status") == "callback_exchange_completed"
        and (persisted_request.get("request") or {}).get("confirmation_id")
        and (persisted_request.get("request") or {}).get("scope_profile") == "seller_unpublished_draft"
        and internal_boundary.get("ready") is True
        and internal_boundary.get("connection_status") == "draft_save_authorized"
        and internal_boundary.get("authorization_kind") == "unpublished_draft"
        and internal_boundary.get("connection_id") == connection.get("connection_id")
        and internal_boundary.get("secret_ref") == connection.get("secret_ref")
        and internal_boundary.get("oauth_request_id") == request.get("oauth_request_id")
        and internal_boundary.get("confirmation_id") == (request.get("request") or {}).get("confirmation_id")
        and internal_boundary.get("seller_identity_hash")
        and internal_boundary.get("state_nonce") == request.get("state_nonce")
        and internal_boundary.get("oauth_request_status") == "callback_exchange_completed"
        and public_result.get("authorization_kind") == "unpublished_draft"
        and metadata.get("public_publish_enabled") is False
        and metadata.get("real_platform_writes_enabled") is False
    ):
        return (
            "draft callback result/connection metadata must preserve draft-only authorization semantics; "
            f"public_kind={public_result.get('authorization_kind')}; "
            f"boundary_ready={internal_boundary.get('ready')}; "
            f"boundary_code={internal_boundary.get('code')}; "
            f"request_status={persisted_request.get('status')}; "
            f"public_request_hidden={'oauth_request_id' not in metadata}; "
            f"public_confirmation_hidden={'confirmation_id' not in metadata}"
        )
    return "ok"


def _run_unpublished_draft_same_seller_upgrade() -> str:
    _clear_env()
    _base_oauth_env(environment="local_dev")
    os.environ["JIEJING_EBAY_CLIENT_SECRET"] = "CALLBACK-CLIENT-SECRET-MUST-NOT-LEAK"
    secret_path = OUT / "draft-same-seller-upgrade-secrets.json"
    os.environ["JIEJING_VAULT_LOCAL_SECRET_RESOLVER_ENABLED"] = "true"
    os.environ["JIEJING_VAULT_LOCAL_SECRET_STORE_PATH"] = str(secret_path)
    secret_path.unlink(missing_ok=True)
    settings, repo, store, read_request = _seed_oauth_request(case_key="draft-same-seller-upgrade", port=8834)
    read_result = process_ebay_oauth_callback(
        repository=repo,
        settings=settings,
        secret_store_boundary=SecretStoreBoundary(settings),
        ebay_oauth_planner=EbayOAuthPlanner(settings),
        state=read_request["state_nonce"],
        code="UNIT_READ_AUTH_CODE_BEFORE_DRAFT",
        error="",
        oauth_transport=_fake_oauth_transport(
            access_token="CALLBACK-ACCESS-TOKEN-MUST-NOT-LEAK",
            refresh_token="CALLBACK-REFRESH-TOKEN-MUST-NOT-LEAK",
        ),
    )
    if read_result.get("status") != "callback_exchange_completed":
        return "read-only callback fixture must complete before draft upgrade"
    old_connection_id = str((read_result.get("connection") or {}).get("connection_id") or "")
    old_secret_ref = str((read_result.get("secret_ref") or {}).get("secret_ref") or "")

    draft_plan = EbayOAuthPlanner(settings).unpublished_draft_authorization_plan(
        company_id=store["company_id"],
        store_id=store["store_id"],
        user_id=store["user_id"],
        marketplace_id="EBAY_US",
        requested_scopes=UNPUBLISHED_DRAFT_SCOPES,
    )
    draft_request = repo.create_oauth_authorization_request(
        company_id=store["company_id"],
        store_id=store["store_id"],
        user_id=store["user_id"],
        plan=draft_plan,
    )
    upgraded = process_ebay_oauth_callback(
        repository=repo,
        settings=settings,
        secret_store_boundary=SecretStoreBoundary(settings),
        ebay_oauth_planner=EbayOAuthPlanner(settings),
        state=draft_request["state_nonce"],
        code="UNIT_DRAFT_AUTH_CODE_SAME_SELLER",
        error="",
        oauth_transport=_fake_oauth_transport(
            access_token="CALLBACK-ACCESS-TOKEN-MUST-NOT-LEAK",
            refresh_token="CALLBACK-REFRESH-TOKEN-MUST-NOT-LEAK",
            granted_scopes=UNPUBLISHED_DRAFT_SCOPES,
        ),
    )
    if upgraded.get("status") != "callback_exchange_completed":
        return "same-store same-seller draft upgrade must complete"
    connections = repo.list_connections(company_id=store["company_id"], store_id=store["store_id"])
    active = [
        item
        for item in connections
        if item.get("status") in {"read_only_authorized", "draft_save_authorized", "publish_authorized"}
    ]
    if len(active) != 1 or active[0].get("status") != "draft_save_authorized":
        return "same-seller scope upgrade must leave exactly one active draft connection"
    retired = next((item for item in connections if item.get("connection_id") == old_connection_id), {})
    if retired.get("status") != "oauth_scope_superseded":
        return "same-seller scope upgrade must atomically retire the old read-only connection"
    old_ref = repo.get_secret_ref(
        company_id=store["company_id"],
        store_id=store["store_id"],
        secret_ref=old_secret_ref,
    ) or {}
    if old_ref.get("status") != "oauth_scope_superseded":
        return "same-seller scope upgrade must atomically retire the old refresh secret reference"

    second_plan = EbayOAuthPlanner(settings).unpublished_draft_authorization_plan(
        company_id=store["company_id"],
        store_id=store["store_id"],
        user_id=store["user_id"],
        marketplace_id="EBAY_US",
        requested_scopes=UNPUBLISHED_DRAFT_SCOPES,
    )
    second_request = repo.create_oauth_authorization_request(
        company_id=store["company_id"],
        store_id=store["store_id"],
        user_id=store["user_id"],
        plan=second_plan,
    )
    ref_count_before = len(repo.list_secret_refs(company_id=store["company_id"], store_id=store["store_id"]))
    wrong_seller = process_ebay_oauth_callback(
        repository=repo,
        settings=settings,
        secret_store_boundary=SecretStoreBoundary(settings),
        ebay_oauth_planner=EbayOAuthPlanner(settings),
        state=second_request["state_nonce"],
        code="UNIT_DRAFT_AUTH_CODE_WRONG_SELLER",
        error="",
        oauth_transport=_fake_oauth_transport(
            access_token="CALLBACK-ACCESS-TOKEN-MUST-NOT-LEAK",
            refresh_token="CALLBACK-REFRESH-TOKEN-MUST-NOT-LEAK",
            granted_scopes=UNPUBLISHED_DRAFT_SCOPES,
            ebay_user_id="DIFFERENT-CALLBACK-USER-MUST-NOT-LEAK",
        ),
    )
    if wrong_seller.get("status") != "callback_exchange_seller_identity_blocked":
        return "draft upgrade must fail closed when the seller identity differs from the current store connection"
    if len(repo.list_secret_refs(company_id=store["company_id"], store_id=store["store_id"])) != ref_count_before:
        return "wrong-seller draft upgrade must block before new secret_ref/Vault persistence"
    return "ok"


def _run_retired_publish_profile_callback_blocked() -> str:
    _clear_env()
    _base_oauth_env(environment="local_dev")
    settings, repo, store, _request = _seed_oauth_request(case_key="retired-publish-profile", port=8828)
    with sqlite3.connect(settings.db_path) as conn:
        conn.execute("delete from audit_logs")
        conn.execute("delete from oauth_authorization_requests")
    plan = EbayOAuthPlanner(settings).publish_authorization_plan(
        company_id=store["company_id"],
        store_id=store["store_id"],
        user_id=store["user_id"],
        marketplace_id="EBAY_US",
    )
    request = repo.create_oauth_authorization_request(
        company_id=store["company_id"],
        store_id=store["store_id"],
        user_id=store["user_id"],
        plan=plan,
    )
    exchange_seen = {"value": False}

    def forbidden_transport(request_obj: Any, timeout: float) -> tuple[int, dict[str, str], bytes]:
        del request_obj, timeout
        exchange_seen["value"] = True
        return 500, {}, b""

    result = process_ebay_oauth_callback(
        repository=repo,
        settings=settings,
        secret_store_boundary=SecretStoreBoundary(settings),
        ebay_oauth_planner=EbayOAuthPlanner(settings),
        state=request["state_nonce"],
        code="RETIRED_PUBLISH_CODE_MUST_NOT_EXCHANGE",
        error="",
        oauth_transport=forbidden_transport,
    )
    if (
        result.get("status") != "blocked_retired_oauth_profile"
        or exchange_seen["value"]
        or result.get("token_exchange_performed") is not False
        or result.get("vault_write_performed") is not False
    ):
        return "a historical seller_publish_listing callback must be retired before token/Vault work"
    if repo.list_connections(company_id=store["company_id"], store_id=store["store_id"]):
        return "a retired publish callback must never create a platform connection"
    return "ok"


def _run_exchange_crash_requires_manual_reconcile() -> str:
    _clear_env()
    _base_oauth_env(environment="local_dev")
    os.environ["JIEJING_EBAY_CLIENT_SECRET"] = "CALLBACK-CLIENT-SECRET-MUST-NOT-LEAK"
    os.environ["JIEJING_VAULT_LOCAL_SECRET_RESOLVER_ENABLED"] = "true"
    os.environ["JIEJING_VAULT_LOCAL_SECRET_STORE_PATH"] = str(OUT / "crashed-callback-secrets.json")
    settings, repo, _store, request = _seed_oauth_request(case_key="crashed-callback", port=8827)
    exchange_entry_count = 0

    def crashing_transport(request_obj: Any, timeout: float) -> tuple[int, dict[str, str], bytes]:
        nonlocal exchange_entry_count
        if request_obj.get_method() == "POST" and "/identity/v1/oauth2/token" in request_obj.full_url:
            exchange_entry_count += 1
            raise RuntimeError("simulated transport crash")
        return 404, {"content-type": "application/json"}, b'{}'

    first = process_ebay_oauth_callback(
        repository=repo,
        settings=settings,
        secret_store_boundary=SecretStoreBoundary(settings),
        ebay_oauth_planner=EbayOAuthPlanner(settings),
        state=request["state_nonce"],
        code="UNIT_AUTH_CODE_CRASH",
        error="",
        oauth_transport=crashing_transport,
    )
    if first.get("status") != "callback_received_exchange_failed":
        return "a transport crash after claim must terminate fail-closed"

    claimed = repo.get_oauth_authorization_request_by_state(state_nonce=request["state_nonce"])
    if not claimed or claimed.get("status") != "callback_received_exchange_failed":
        return "a callback crash after claim must persist a terminal failure for manual reconcile"

    retry = process_ebay_oauth_callback(
        repository=repo,
        settings=settings,
        secret_store_boundary=SecretStoreBoundary(settings),
        ebay_oauth_planner=EbayOAuthPlanner(settings),
        state=request["state_nonce"],
        code="UNIT_AUTH_CODE_CRASH",
        error="",
        oauth_transport=crashing_transport,
    )
    if exchange_entry_count != 1:
        return "a claimed callback crash must never automatically repeat token exchange"
    if retry.get("status") != "blocked_replayed_state":
        return "a retry after callback crash must remain blocked for manual reconcile"
    if retry.get("record_callback_event") is not False:
        return "a callback crash retry must not overwrite the terminal failure"
    return "ok"


def _oauth_launch_step(gate: dict[str, Any]) -> dict[str, Any]:
    action_plan = gate.get("launch_action_plan") if isinstance(gate.get("launch_action_plan"), dict) else {}
    for item in action_plan.get("new_ebay_account_smoke_runbook") or []:
        if isinstance(item, dict) and item.get("key") == "new_account_oauth_authorization_gate":
            return item
    return {}


def _run_expired_state_blocked(*, local_secret_path: Path) -> str:
    _clear_env()
    _base_oauth_env(environment="local_dev")
    os.environ["JIEJING_EBAY_CLIENT_SECRET"] = "CALLBACK-CLIENT-SECRET-MUST-NOT-LEAK"
    os.environ["JIEJING_VAULT_LOCAL_SECRET_RESOLVER_ENABLED"] = "true"
    os.environ["JIEJING_VAULT_LOCAL_SECRET_STORE_PATH"] = str(local_secret_path)
    settings, repo, _store, request = _seed_oauth_request(case_key="expired-state", port=8824)
    with sqlite3.connect(settings.db_path) as conn:
        conn.execute(
            """
            update oauth_authorization_requests
            set created_at = ?, updated_at = ?
            where oauth_request_id = ?
            """,
            ("2000-01-01T00:00:00+00:00", "2000-01-01T00:00:00+00:00", request["oauth_request_id"]),
        )
    seen = {"oauth_post": False}

    def oauth_transport(request_obj: Any, timeout: float) -> tuple[int, dict[str, str], bytes]:
        seen["oauth_post"] = True
        return _oauth_response(
            access_token="CALLBACK-ACCESS-TOKEN-MUST-NOT-LEAK",
            refresh_token="CALLBACK-REFRESH-TOKEN-MUST-NOT-LEAK",
        )

    result = process_ebay_oauth_callback(
        repository=repo,
        settings=settings,
        secret_store_boundary=SecretStoreBoundary(settings),
        ebay_oauth_planner=EbayOAuthPlanner(settings),
        state=request["state_nonce"],
        code="UNIT_AUTH_CODE_EXPIRED",
        error="",
        oauth_transport=oauth_transport,
    )
    if result.get("status") != "blocked_invalid_expired_state":
        return "expired callback state should be blocked before token exchange"
    if seen["oauth_post"]:
        return "expired callback state must not call the eBay token endpoint"
    refetched = repo.get_oauth_authorization_request_by_state(state_nonce=request["state_nonce"])
    if not refetched or refetched.get("status") != "blocked_invalid_expired_state":
        return "expired callback state should be recorded as expired"

    invalid_times = {
        "naive": datetime.now().replace(microsecond=0).isoformat(),
        "future": (datetime.now(timezone.utc) + timedelta(minutes=5)).replace(microsecond=0).isoformat(),
    }
    for label, created_at in invalid_times.items():
        settings, repo, _store, request = _seed_oauth_request(case_key=f"{label}-state", port=8833)
        with sqlite3.connect(settings.db_path) as conn:
            conn.execute(
                "update oauth_authorization_requests set created_at = ?, updated_at = ? where oauth_request_id = ?",
                (created_at, created_at, request["oauth_request_id"]),
            )
        exchange_seen = {"value": False}

        def invalid_state_transport(request_obj: Any, timeout: float) -> tuple[int, dict[str, str], bytes]:
            exchange_seen["value"] = True
            return _oauth_response(
                access_token="CALLBACK-ACCESS-TOKEN-MUST-NOT-LEAK",
                refresh_token="CALLBACK-REFRESH-TOKEN-MUST-NOT-LEAK",
            )

        invalid = process_ebay_oauth_callback(
            repository=repo,
            settings=settings,
            secret_store_boundary=SecretStoreBoundary(settings),
            ebay_oauth_planner=EbayOAuthPlanner(settings),
            state=request["state_nonce"],
            code=f"UNIT_AUTH_CODE_{label.upper()}",
            error="",
            oauth_transport=invalid_state_transport,
        )
        if invalid.get("status") != "blocked_invalid_expired_state" or exchange_seen["value"]:
            return f"{label} callback state must fail closed before token exchange"
    return "ok"


def _run_identity_mapping_failure_no_secret(*, local_secret_path: Path) -> str:
    _clear_env()
    _base_oauth_env(environment="local_dev")
    os.environ["JIEJING_EBAY_CLIENT_SECRET"] = "CALLBACK-CLIENT-SECRET-MUST-NOT-LEAK"
    os.environ["JIEJING_VAULT_LOCAL_SECRET_RESOLVER_ENABLED"] = "true"
    os.environ["JIEJING_VAULT_LOCAL_SECRET_STORE_PATH"] = str(local_secret_path)
    local_secret_path.unlink(missing_ok=True)
    settings, repo, store, request = _seed_oauth_request(case_key="identity-failure", port=8824)

    def transport(request_obj: Any, timeout: float) -> tuple[int, dict[str, str], bytes]:
        if request_obj.get_method() == "POST" and "/identity/v1/oauth2/token" in request_obj.full_url:
            return _oauth_response(
                access_token="CALLBACK-ACCESS-TOKEN-MUST-NOT-LEAK",
                refresh_token="CALLBACK-REFRESH-TOKEN-MUST-NOT-LEAK",
            )
        return 503, {"content-type": "application/json"}, b'{"error":"temporary"}'

    result = process_ebay_oauth_callback(
        repository=repo,
        settings=settings,
        secret_store_boundary=SecretStoreBoundary(settings),
        ebay_oauth_planner=EbayOAuthPlanner(settings),
        state=request["state_nonce"],
        code="UNIT_AUTH_CODE",
        error="",
        oauth_transport=transport,
    )
    if result.get("status") != "callback_exchange_identity_mapping_failed":
        return "identity API failure should stop OAuth before credential persistence"
    if repo.list_connections(company_id=store["company_id"], store_id=store["store_id"]):
        return "identity mapping failure must not create an unmapped active eBay connection"
    if repo.list_secret_refs(company_id=store["company_id"], store_id=store["store_id"]):
        return "identity mapping failure must not create an orphaned refresh-token reference"
    if local_secret_path.exists():
        return "identity mapping failure must not write the refresh token to local secret storage"
    return "ok"


def _run_managed_vault_callback() -> str:
    _clear_env()
    _base_oauth_env(environment="staging")
    os.environ["JIEJING_EBAY_CLIENT_SECRET"] = "CALLBACK-MANAGED-SECRET-MUST-NOT-LEAK"
    os.environ["JIEJING_VAULT_ENABLED"] = "true"
    os.environ["JIEJING_VAULT_PROVIDER"] = "vault"
    os.environ["JIEJING_VAULT_LIVE_RESOLVE_ENABLED"] = "true"
    os.environ["JIEJING_VAULT_ADDR"] = "https://vault.example.test"
    os.environ["JIEJING_VAULT_TOKEN"] = "VAULT-CALLBACK-TOKEN-MUST-NOT-LEAK"
    os.environ["JIEJING_VAULT_MOUNT"] = "secret"
    os.environ["JIEJING_VAULT_KEYSPACE"] = "jiejing-callback"
    os.environ["JIEJING_VAULT_KV_VERSION"] = "v2"
    settings, repo, store, request = _seed_oauth_request(case_key="managed-callback", port=8821)
    oauth_seen = {"post": False}
    vault_seen = {"post": False, "body_had_refresh_token": False}

    def oauth_transport(request_obj: Any, timeout: float) -> tuple[int, dict[str, str], bytes]:
        if request_obj.get_method() == "GET" and request_obj.full_url.endswith("/commerce/identity/v1/user/"):
            return (
                200,
                {"content-type": "application/json"},
                json.dumps(
                    {
                        "userId": "CALLBACK-IMMUTABLE-USER-MUST-NOT-LEAK",
                        "username": "CALLBACK-USERNAME-MUST-NOT-LEAK",
                        "registrationMarketplaceId": "EBAY_US",
                        "accountType": "BUSINESS",
                        "status": "CONFIRMED",
                    }
                ).encode("utf-8"),
            )
        oauth_seen["post"] = True
        return _oauth_response(
            access_token="CALLBACK-MANAGED-ACCESS-MUST-NOT-LEAK",
            refresh_token="CALLBACK-MANAGED-REFRESH-MUST-NOT-LEAK",
        )

    def vault_transport(request_obj: Any, timeout: float) -> tuple[int, dict[str, str], bytes]:
        vault_seen["post"] = request_obj.get_method() == "POST"
        token = request_obj.headers.get("X-vault-token") or request_obj.headers.get("X-Vault-Token")
        if token != "VAULT-CALLBACK-TOKEN-MUST-NOT-LEAK":
            return 403, {"content-type": "application/json"}, b'{"errors":["forbidden"]}'
        body = request_obj.data.decode("utf-8") if request_obj.data else ""
        vault_seen["body_had_refresh_token"] = "CALLBACK-MANAGED-REFRESH-MUST-NOT-LEAK" in body
        if "/v1/secret/data/jiejing-callback/" not in request_obj.full_url:
            return 404, {"content-type": "application/json"}, b'{"errors":["missing"]}'
        return 204, {"content-type": "application/json"}, b""

    result = process_ebay_oauth_callback(
        repository=repo,
        settings=settings,
        secret_store_boundary=SecretStoreBoundary(settings),
        ebay_oauth_planner=EbayOAuthPlanner(settings),
        state=request["state_nonce"],
        code="UNIT_AUTH_CODE",
        error="",
        oauth_transport=oauth_transport,
        vault_transport=vault_transport,
    )
    if result.get("status") != "callback_exchange_completed":
        return "managed callback should complete exchange and Vault write"
    if result.get("secret_storage", {}).get("storage_adapter") != "managed_hashicorp_vault":
        return "managed callback should store through HashiCorp Vault adapter"
    if result.get("secret_ref", {}).get("status") != "managed_vault_stored":
        return "managed callback should update secret_ref to managed_vault_stored"
    if oauth_seen != {"post": True} or vault_seen != {"post": True, "body_had_refresh_token": True}:
        return "managed callback should POST to eBay token endpoint and managed Vault"
    public_serialized = json.dumps(result, ensure_ascii=False)
    if any(value in public_serialized for value in FORBIDDEN):
        return "managed callback public response leaked a token or secret"
    db_text = _sqlite_public_dump(settings.db_path)
    if any(value in db_text for value in FORBIDDEN):
        return "managed callback database leaked a token or secret"
    connections = repo.list_connections(company_id=store["company_id"], store_id=store["store_id"])
    if not connections or connections[0].get("metadata", {}).get("credential_source") != "jiejing_vault_secret_ref":
        return "managed callback should create a Jiejing Vault-backed platform connection"
    return "ok"


def _run_production_local_resolver_blocked() -> str:
    _clear_env()
    _base_oauth_env(environment="production")
    os.environ["JIEJING_EBAY_CLIENT_SECRET"] = "CALLBACK-CLIENT-SECRET-MUST-NOT-LEAK"
    os.environ["JIEJING_VAULT_LOCAL_SECRET_RESOLVER_ENABLED"] = "true"
    settings, repo, _store, request = _seed_oauth_request(case_key="production-blocked", port=8822)
    seen = {"oauth_post": False}

    def oauth_transport(request_obj: Any, timeout: float) -> tuple[int, dict[str, str], bytes]:
        seen["oauth_post"] = True
        return _oauth_response(
            access_token="CALLBACK-ACCESS-TOKEN-MUST-NOT-LEAK",
            refresh_token="CALLBACK-REFRESH-TOKEN-MUST-NOT-LEAK",
        )

    result = process_ebay_oauth_callback(
        repository=repo,
        settings=settings,
        secret_store_boundary=SecretStoreBoundary(settings),
        ebay_oauth_planner=EbayOAuthPlanner(settings),
        state=request["state_nonce"],
        code="UNIT_AUTH_CODE",
        error="",
        oauth_transport=oauth_transport,
    )
    if result.get("status") != "callback_received_exchange_blocked":
        return "production callback should block without managed Vault"
    if seen["oauth_post"]:
        return "production callback must not exchange code before managed Vault is ready"
    if "Vault/KMS" not in result.get("blocked_by", []):
        return "production callback should surface Vault/KMS blocker"
    return "ok"


def _seed_oauth_request(*, case_key: str, port: int) -> tuple[SaaSSettings, SaaSRepository, dict[str, Any], dict[str, Any]]:
    db_path = OUT / f"{case_key}.sqlite"
    runtime_db_path = OUT / f"{case_key}-runtime.sqlite"
    db_path.unlink(missing_ok=True)
    runtime_db_path.unlink(missing_ok=True)
    settings = SaaSSettings.from_env(
        db_path=db_path,
        runtime_db_path=runtime_db_path,
        output_root=OUT / case_key,
        host="127.0.0.1",
        port=port,
    )
    repo = SaaSRepository(db_path)
    repo.initialize()
    user_company = repo.create_user_with_company(
        email=f"{case_key}@example.com",
        password="unit-password",
        company_name=f"{case_key} company",
    )
    company_id = user_company["company"]["company_id"]
    user_id = user_company["user"]["user_id"]
    store = repo.create_store(
        company_id=company_id,
        user_id=user_id,
        payload={"platform": "ebay", "store_name": f"{case_key} store", "marketplace": "EBAY_US"},
    )
    plan = EbayOAuthPlanner(settings).read_only_authorization_plan(
        company_id=company_id,
        store_id=store["store_id"],
        user_id=user_id,
        marketplace_id="EBAY_US",
    )
    oauth_query = urllib.parse.parse_qs(urllib.parse.urlparse(plan["authorization_url"]).query)
    if oauth_query.get("prompt") != ["login"]:
        raise AssertionError("seller OAuth should force an explicit eBay login before consent")
    request = repo.create_oauth_authorization_request(
        company_id=company_id,
        store_id=store["store_id"],
        user_id=user_id,
        plan=plan,
    )
    return settings, repo, {**store, "company_id": company_id, "user_id": user_id}, request


def _seed_unpublished_draft_oauth_request(
    *,
    case_key: str,
    port: int,
) -> tuple[SaaSSettings, SaaSRepository, dict[str, Any], dict[str, Any]]:
    settings, repo, store, _request = _seed_oauth_request(case_key=case_key, port=port)
    with sqlite3.connect(settings.db_path) as conn:
        conn.execute("delete from audit_logs")
        conn.execute("delete from oauth_authorization_requests")
    plan = EbayOAuthPlanner(settings).unpublished_draft_authorization_plan(
        company_id=store["company_id"],
        store_id=store["store_id"],
        user_id=store["user_id"],
        marketplace_id="EBAY_US",
        requested_scopes=UNPUBLISHED_DRAFT_SCOPES,
    )
    confirmation = repo.create_unpublished_draft_oauth_confirmation(
        company_id=store["company_id"],
        store_id=store["store_id"],
        user_id=store["user_id"],
    )
    confirmation = repo.decide_confirmation(
        company_id=store["company_id"],
        confirmation_id=confirmation["confirmation_id"],
        decided_by=store["user_id"],
        decision="approve",
        note="Focused exact draft OAuth callback fixture.",
    )
    plan["confirmation_id"] = confirmation["confirmation_id"]
    request = repo.create_approved_unpublished_draft_oauth_authorization_request(
        company_id=store["company_id"],
        store_id=store["store_id"],
        user_id=store["user_id"],
        confirmation_id=confirmation["confirmation_id"],
        plan=plan,
    )
    return settings, repo, store, request


def _base_oauth_env(*, environment: str) -> None:
    os.environ["JIEJING_SAAS_ENV"] = environment
    os.environ["JIEJING_EBAY_CLIENT_ID"] = "CALLBACK-CLIENT-ID"
    os.environ["JIEJING_EBAY_RU_NAME"] = "Jiejing_Auth_RuName"
    os.environ["JIEJING_EBAY_OAUTH_EXCHANGE_LIVE"] = "true"


def _fake_oauth_transport(
    *,
    access_token: str,
    refresh_token: str,
    granted_scopes: list[str] | None = None,
    ebay_user_id: str = "CALLBACK-IMMUTABLE-USER-MUST-NOT-LEAK",
) -> Any:
    def transport(request_obj: Any, timeout: float) -> tuple[int, dict[str, str], bytes]:
        if request_obj.get_method() == "GET" and request_obj.full_url.endswith("/commerce/identity/v1/user/"):
            if request_obj.get_header("Authorization") != f"Bearer {access_token}":
                raise AssertionError("identity request should use the transient access token")
            return (
                200,
                {"content-type": "application/json"},
                json.dumps(
                    {
                        "userId": ebay_user_id,
                        "username": "CALLBACK-USERNAME-MUST-NOT-LEAK",
                        "registrationMarketplaceId": "EBAY_US",
                        "accountType": "INDIVIDUAL",
                        "status": "CONFIRMED",
                    }
                ).encode("utf-8"),
            )
        if request_obj.get_method() != "POST" or "/identity/v1/oauth2/token" not in request_obj.full_url:
            return 404, {"content-type": "application/json"}, b'{"error":"missing"}'
        return _oauth_response(
            access_token=access_token,
            refresh_token=refresh_token,
            granted_scopes=granted_scopes,
        )

    return transport


def _oauth_response(
    *,
    access_token: str,
    refresh_token: str,
    granted_scopes: list[str] | None = None,
) -> tuple[int, dict[str, str], bytes]:
    payload = {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_in": 7200,
        "refresh_token_expires_in": 47304000,
    }
    if granted_scopes is not None:
        payload["scope"] = " ".join(granted_scopes)
    return (
        200,
        {"content-type": "application/json"},
        json.dumps(payload).encode("utf-8"),
    )


def _sqlite_public_dump(path: Path) -> str:
    with sqlite3.connect(path) as conn:
        tables = [
            row[0]
            for row in conn.execute(
                "select name from sqlite_master where type = 'table' and name not like 'sqlite_%' order by name"
            ).fetchall()
        ]
        rows: list[Any] = []
        for table in tables:
            rows.extend(conn.execute(f"select * from {table}").fetchall())
    return json.dumps(rows, ensure_ascii=False, default=str)


def _clear_env() -> None:
    for key in ENV_KEYS:
        os.environ.pop(key, None)


def _restore_env(previous: dict[str, str | None]) -> None:
    for key, value in previous.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


if __name__ == "__main__":
    raise SystemExit(main())
