#!/usr/bin/env python3
"""Adversarial contract for the one-shot unpublished-draft claim capability."""

from __future__ import annotations

import hashlib
import json
import os
import pickle
import sys
import tempfile
import copy
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.config import SaaSSettings  # noqa: E402
from jiejing_saas.ebay_oauth import EbayOAuthPlanner, UNPUBLISHED_DRAFT_SCOPES  # noqa: E402
from jiejing_saas.ebay_oauth_callback import process_ebay_oauth_callback  # noqa: E402
from jiejing_saas.repository import (  # noqa: E402
    ConfirmationDecisionConflict,
    SaaSRepository,
    UnpublishedDraftClaimCapability,
)
from jiejing_saas.secret_store import SecretStoreBoundary  # noqa: E402
from jiejing_saas.ebay_write_adapter import build_ebay_execution_plan


HASH_KEYS = (
    "connection_id_sha256",
    "credential_ref_sha256",
    "oauth_request_id_sha256",
    "seller_identity_sha256",
)


def _canonical_sha256(value: dict[str, Any]) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _oauth_transport(request: Any, timeout: float) -> tuple[int, dict[str, str], bytes]:
    del timeout
    if request.get_method() == "GET" and request.full_url.endswith("/commerce/identity/v1/user/"):
        return (
            200,
            {"content-type": "application/json"},
            json.dumps(
                {
                    "userId": "CLAIM-CAPABILITY-SELLER-DO-NOT-LEAK",
                    "username": "claim-capability-seller-do-not-leak",
                    "registrationMarketplaceId": "EBAY_US",
                    "accountType": "BUSINESS",
                    "status": "CONFIRMED",
                }
            ).encode("utf-8"),
        )
    if request.get_method() == "POST" and "/identity/v1/oauth2/token" in request.full_url:
        return (
            200,
            {"content-type": "application/json"},
            json.dumps(
                {
                    "access_token": "CLAIM-CAPABILITY-ACCESS-TOKEN-DO-NOT-LEAK",
                    "refresh_token": "CLAIM-CAPABILITY-REFRESH-TOKEN-DO-NOT-LEAK",
                    "expires_in": 7200,
                    "refresh_token_expires_in": 47304000,
                    "scope": " ".join(UNPUBLISHED_DRAFT_SCOPES),
                }
            ).encode("utf-8"),
        )
    return 404, {"content-type": "application/json"}, b'{"error":"missing"}'


def _vault_transport(request: Any, timeout: float) -> tuple[int, dict[str, str], bytes]:
    del timeout
    if request.get_method() != "POST":
        return 405, {"content-type": "application/json"}, b'{"errors":["method"]}'
    return 204, {"content-type": "application/json"}, b""


def _new_case(root: Path, case_key: str) -> tuple[SaaSRepository, dict[str, str], dict[str, Any], dict[str, str]]:
    settings = SaaSSettings.from_env(
        db_path=root / f"{case_key}.sqlite",
        runtime_db_path=root / f"{case_key}-runtime.sqlite",
        output_root=root / case_key,
        host="127.0.0.1",
        port=8788,
    )
    repo = SaaSRepository(settings.db_path, database_engine="sqlite")
    account = repo.create_user_with_company(
        email=f"{case_key}@example.test",
        password="Password123!",
        company_name=f"{case_key} company",
    )
    user = account["user"]
    context = {
        "company_id": str(user["default_company_id"]),
        "user_id": str(user["user_id"]),
    }
    store = repo.create_store(
        company_id=context["company_id"],
        user_id=context["user_id"],
        payload={"platform": "ebay", "store_name": f"{case_key} store", "marketplace": "EBAY_US"},
    )
    context["store_id"] = str(store["store_id"])

    planner = EbayOAuthPlanner(settings)
    oauth_confirmation = repo.create_unpublished_draft_oauth_confirmation(
        company_id=context["company_id"],
        store_id=context["store_id"],
        user_id=context["user_id"],
    )
    oauth_confirmation = repo.decide_confirmation(
        company_id=context["company_id"],
        confirmation_id=oauth_confirmation["confirmation_id"],
        decision="approve",
        decided_by=context["user_id"],
        note="Approve exact draft claim capability fixture.",
        expected_access_epochs=repo.access_session_epochs(user_id=context["user_id"],company_id=context["company_id"]),
    )
    oauth_plan = planner.unpublished_draft_authorization_plan(
        company_id=context["company_id"],
        store_id=context["store_id"],
        user_id=context["user_id"],
        marketplace_id="EBAY_US",
        requested_scopes=UNPUBLISHED_DRAFT_SCOPES,
    )
    oauth_plan["confirmation_id"] = oauth_confirmation["confirmation_id"]
    oauth_request = repo.create_approved_unpublished_draft_oauth_authorization_request(
        company_id=context["company_id"],
        store_id=context["store_id"],
        user_id=context["user_id"],
        confirmation_id=oauth_confirmation["confirmation_id"],
        plan=oauth_plan,
    )
    callback = process_ebay_oauth_callback(
        repository=repo,
        settings=settings,
        secret_store_boundary=SecretStoreBoundary(settings),
        ebay_oauth_planner=planner,
        state=oauth_request["state_nonce"],
        code="CLAIM_CAPABILITY_EXACT_CODE",
        error="",
        oauth_transport=_oauth_transport,
        vault_transport=_vault_transport,
    )
    if callback.get("status") != "callback_exchange_completed":
        raise AssertionError(f"exact draft OAuth callback fixture failed: {callback.get('status')}")
    credential = repo.unpublished_draft_execution_credential_boundary(
        company_id=context["company_id"],
        store_id=context["store_id"],
    )
    if credential.get("ready") is not True or not all(credential.get(key) for key in HASH_KEYS):
        raise AssertionError(f"exact draft credential fixture failed: {credential.get('code')}")

    payload = {
        "listing": {
            "sku": f"CLAIM-{case_key.upper()}-001",
            "title": "Exact unpublished draft claim fixture",
            "price": 19.95,
            "quantity": 1,
        },
        "marketplace_id": "EBAY_US",
    }
    task = repo.create_task(
        company_id=context["company_id"],
        store_id=context["store_id"],
        user_id=context["user_id"],
        task_type="ebay_draft_save_intake",
        title="Exact unpublished draft claim fixture",
        input_data={"secret_exposed": False},
    )
    confirmation = repo.create_confirmation(
        company_id=context["company_id"],
        store_id=context["store_id"],
        task_id=task["task_id"],
        runtime_run_id="merchant_ebay_draft_save_intake",
        action_type="save_ebay_listing_draft",
        title="Exact unpublished draft claim fixture",
        item={
            "source": "merchant_ebay_draft_save_intake",
            "company_id": context["company_id"],
            "store_id": context["store_id"],
            "draft_save_capability_requested": True,
            "writes_to_ebay_after_approval": True,
            "public_publish_enabled": False,
            "real_platform_writes_enabled": False,
            "publish_payload": payload,
            "publish_payload_sha256": _canonical_sha256(payload),
            "secret_exposed": False,
        },
        created_by=context["user_id"],
    )
    confirmation = repo.decide_confirmation(
        company_id=context["company_id"],
        confirmation_id=confirmation["confirmation_id"],
        decision="approve",
        decided_by=context["user_id"],
        note="Approve one exact unpublished draft claim.",
        expected_access_epochs=repo.access_session_epochs(user_id=context["user_id"],company_id=context["company_id"]),
    )
    binding = {
        "confirmation_id": str(confirmation["confirmation_id"]),
        "company_id": context["company_id"],
        "store_id": context["store_id"],
        "action_type": "save_ebay_listing_draft",
        "task_id": str(task["task_id"]),
        "idempotency_key": f"claim-capability-{case_key}",
        "marketplace_id": "EBAY_US",
        "payload_sha256": _canonical_sha256(payload),
        "preparation_sha256": hashlib.sha256(f"prepare:{case_key}".encode("utf-8")).hexdigest(),
        "contract_version": "2026-08-13-unpublished-draft-credential-v1",
        **{key: str(credential[key]) for key in HASH_KEYS},
    }
    return repo, context, confirmation, binding


def _claim_count(repo: SaaSRepository) -> int:
    with repo._connect() as conn:
        return int(conn.execute("select count(*) as count from external_execution_claims").fetchone()["count"])


def _assert_approved(repo: SaaSRepository, company_id: str, confirmation_id: str) -> None:
    confirmation = repo.get_confirmation(company_id=company_id, confirmation_id=confirmation_id) or {}
    if confirmation.get("status") != "approved":
        raise AssertionError(f"rejected claim must preserve approved confirmation; status={confirmation.get('status')}")


def _expect_claim_rejected(
    repo: SaaSRepository,
    context: dict[str, str],
    confirmation: dict[str, Any],
    operation: Callable[[], Any],
) -> None:
    before = _claim_count(repo)
    try:
        operation()
    except ConfirmationDecisionConflict:
        pass
    else:
        raise AssertionError("invalid draft claim unexpectedly succeeded")
    if _claim_count(repo) != before:
        raise AssertionError("invalid draft claim must not insert a claim row")
    _assert_approved(repo, context["company_id"], str(confirmation["confirmation_id"]))


def _claim(
    repo: SaaSRepository,
    context: dict[str, str],
    confirmation: dict[str, Any],
    binding: dict[str, str],
) -> tuple[dict[str, Any], UnpublishedDraftClaimCapability]:
    return repo.claim_unpublished_draft_execution(
        company_id=context["company_id"],
        confirmation_id=str(confirmation["confirmation_id"]),
        user_id=context["user_id"],
        expected_binding=binding,
        **_plan_args(repo, context, confirmation),
    )


def _plan_args(repo, context, confirmation):
    request=SimpleNamespace(**context,confirmation_id=confirmation['confirmation_id'],task_id=confirmation['task_id'],
        action_type='save_ebay_listing_draft',payload=confirmation['item']['publish_payload'])
    boundary=repo.unpublished_draft_execution_credential_boundary(company_id=context['company_id'],store_id=context['store_id'])
    return dict(expected_access_epochs=repo.access_session_epochs(user_id=context['user_id'],company_id=context['company_id']),
        operation_plan=build_ebay_execution_plan(request=request,marketplace_id='EBAY_US',credential_boundary=boundary,draft_offer_id=''))


def _new_approved_replacement(repo,context,confirmation,binding):
    old=repo.get_confirmation(company_id=context['company_id'],confirmation_id=confirmation['confirmation_id'])
    replacement=repo.create_confirmation(company_id=context['company_id'],store_id=context['store_id'],task_id=old['task_id'],
        runtime_run_id=old['runtime_run_id'],action_type=old['action_type'],title=old['title'],item=copy.deepcopy(old['item']),
        created_by=context['user_id'],replaces_confirmation_id=old['confirmation_id'])
    assert replacement['status']=='pending' and not replacement['decided_by'] and not replacement['decided_at']
    for key in ('item','decided_by','decided_at','decision_note'):
        assert repo.get_confirmation(company_id=context['company_id'],confirmation_id=old['confirmation_id'])[key]==old[key]
    new_binding={**binding,'confirmation_id':replacement['confirmation_id'],'idempotency_key':binding['idempotency_key']+'-replacement'}
    try: _claim(repo,context,replacement,new_binding)
    except ConfirmationDecisionConflict: pass
    else: raise AssertionError('A new pending must not execute before its own approval')
    replacement=repo.decide_confirmation(company_id=context['company_id'],confirmation_id=replacement['confirmation_id'],
        decision='approve',decided_by=context['user_id'],note='Independent new approval after exact zero-write retirement.',
        expected_access_epochs=repo.access_session_epochs(user_id=context['user_id'],company_id=context['company_id']))
    return _claim(repo,context,replacement,new_binding)


def _case_legacy_claim_rejected(root: Path) -> None:
    repo, context, confirmation, _binding = _new_case(root, "legacy-claim")
    _expect_claim_rejected(
        repo,
        context,
        confirmation,
        lambda: repo.claim_external_execution(
            company_id=context["company_id"],
            confirmation_id=str(confirmation["confirmation_id"]),
            user_id=context["user_id"],
        ),
    )


def _case_wrong_claim_bindings(root: Path) -> None:
    mutations: list[tuple[str, Callable[[dict[str, str], dict[str, str]], tuple[str, dict[str, str]]]]] = [
        ("payload", lambda context, binding: (context["company_id"], {**binding, "payload_sha256": "0" * 64})),
        ("store", lambda context, binding: (context["company_id"], {**binding, "store_id": "wrong-store"})),
        ("company", lambda context, binding: ("wrong-company", {**binding, "company_id": "wrong-company"})),
    ]
    mutations.extend(
        (
            key,
            lambda context, binding, key=key: (context["company_id"], {**binding, key: "0" * 64}),
        )
        for key in HASH_KEYS
    )
    for label, mutate in mutations:
        repo, context, confirmation, binding = _new_case(root, f"wrong-{label}")
        company_id, invalid_binding = mutate(context, binding)
        _expect_claim_rejected(
            repo,
            context,
            confirmation,
            lambda repo=repo, context=context, confirmation=confirmation, company_id=company_id, invalid_binding=invalid_binding: repo.claim_unpublished_draft_execution(
                company_id=company_id,
                confirmation_id=str(confirmation["confirmation_id"]),
                user_id=context["user_id"],
                expected_binding=invalid_binding,
                **_plan_args(repo,context,confirmation),
            ),
        )


def _case_invalid_approval_time(root: Path) -> None:
    invalid_times = {
        "expired": datetime.now(timezone.utc) - timedelta(minutes=16),
        "future": datetime.now(timezone.utc) + timedelta(minutes=5),
    }
    for label, decided_at in invalid_times.items():
        repo, context, confirmation, binding = _new_case(root, f"claim-{label}")
        with repo._connect() as conn:
            conn.execute(
                "update confirmations set decided_at = ? where company_id = ? and confirmation_id = ?",
                (decided_at.isoformat(), context["company_id"], confirmation["confirmation_id"]),
            )
        _expect_claim_rejected(
            repo,
            context,
            confirmation,
            lambda repo=repo, context=context, confirmation=confirmation, binding=binding: _claim(
                repo, context, confirmation, binding
            ),
        )


def _case_fake_replay_and_concurrent_consume(root: Path) -> None:
    repo, context, confirmation, binding = _new_case(root, "fake-nonce")
    claimed, capability = _claim(repo, context, confirmation, binding)
    forged = UnpublishedDraftClaimCapability(
        claim_id=capability._claim_id,
        nonce=b"forged-capability-nonce" * 2,
        binding=claimed["external_execution_claim_binding"],
    )
    try:
        repo.consume_unpublished_draft_execution_claim(capability=forged)
    except ConfirmationDecisionConflict:
        pass
    else:
        raise AssertionError("forged capability nonce must not consume a draft claim")
    consumed = repo.consume_unpublished_draft_execution_claim(capability=capability)
    if consumed.get("external_execution_claimed") is not True:
        raise AssertionError("the real one-shot capability must remain usable after a forged nonce attempt")
    try:
        repo.consume_unpublished_draft_execution_claim(capability=capability)
    except ConfirmationDecisionConflict:
        pass
    else:
        raise AssertionError("a consumed draft claim capability must not be replayed")

    repo, context, confirmation, binding = _new_case(root, "concurrent-consume")
    _claimed, capability = _claim(repo, context, confirmation, binding)

    def consume(_index: int) -> str:
        try:
            repo.consume_unpublished_draft_execution_claim(capability=capability)
            return "consumed"
        except ConfirmationDecisionConflict:
            return "blocked"

    with ThreadPoolExecutor(max_workers=4) as executor:
        outcomes = list(executor.map(consume, range(4)))
    if outcomes.count("consumed") != 1 or outcomes.count("blocked") != 3:
        raise AssertionError(f"concurrent capability consume must succeed exactly once: {outcomes}")


def _case_post_claim_payload_drift(root: Path) -> None:
    repo, context, confirmation, binding = _new_case(root, "payload-drift")
    _claimed, capability = _claim(repo, context, confirmation, binding)
    with repo._connect() as conn:
        row = conn.execute(
            "select item_json from confirmations where company_id = ? and confirmation_id = ?",
            (context["company_id"], confirmation["confirmation_id"]),
        ).fetchone()
        item = json.loads(row["item_json"])
        item["publish_payload"]["listing"]["title"] = "Changed after claim and must never execute"
        item["publish_payload_sha256"] = _canonical_sha256(item["publish_payload"])
        conn.execute(
            "update confirmations set item_json = ? where company_id = ? and confirmation_id = ?",
            (json.dumps(item, ensure_ascii=False), context["company_id"], confirmation["confirmation_id"]),
        )
    try:
        repo.consume_unpublished_draft_execution_claim(capability=capability)
    except ConfirmationDecisionConflict:
        return
    raise AssertionError("confirmation payload drift after claim must block capability consume")


def _case_post_claim_credential_drift(root: Path) -> None:
    repo, context, confirmation, binding = _new_case(root, "credential-drift")
    _claimed, capability = _claim(repo, context, confirmation, binding)
    boundary = repo.unpublished_draft_execution_credential_boundary(
        company_id=context["company_id"],
        store_id=context["store_id"],
    )
    with repo._connect() as conn:
        conn.execute(
            "update secret_refs set status = 'oauth_scope_superseded' where company_id = ? and store_id = ? and secret_ref = ?",
            (context["company_id"], context["store_id"], boundary["secret_ref"]),
        )
    try:
        repo.consume_unpublished_draft_execution_claim(capability=capability)
    except ConfirmationDecisionConflict:
        return
    raise AssertionError("credential drift after claim must block capability consume")


def _case_abort_restores_once_without_write_audit(root: Path) -> None:
    repo, context, confirmation, binding = _new_case(root, "abort-prewrite")
    _claimed, capability = _claim(repo, context, confirmation, binding)
    if not callable(getattr(capability, "abort", None)):
        raise AssertionError("repository must expose one-shot abort_unpublished_draft_execution_claim")
    aborted = capability.abort()
    if aborted.get("status") != "needs_revision" or aborted.get("writes_to_ebay") is not False:
        raise AssertionError(f"prewrite abort must retire old authority without a write: {aborted}")
    stored=repo.get_confirmation(company_id=context['company_id'],confirmation_id=confirmation['confirmation_id'])
    assert stored['status']=='needs_revision'
    for key in ('item','decided_by','decided_at','decision_note'): assert stored[key]==confirmation[key]
    try:
        capability.abort()
    except ConfirmationDecisionConflict:
        pass
    else:
        raise AssertionError("prewrite abort capability must be one-shot")
    try:
        capability.consume()
    except ConfirmationDecisionConflict:
        pass
    else:
        raise AssertionError("an aborted capability must never be consumable")
    audits = repo.list_audit_logs(company_id=context["company_id"], limit=200)
    if any(
        isinstance(item.get("details"), dict) and item["details"].get("writes_to_ebay") is True
        for item in audits
    ):
        raise AssertionError("prewrite abort must leave zero audit evidence of an eBay write")
    with repo._connect() as conn:
        row = conn.execute(
            "select status, consumed_at from external_execution_claims where confirmation_id = ?",
            (confirmation["confirmation_id"],),
        ).fetchone()
    if not row or row["status"] != "aborted" or row["consumed_at"]:
        raise AssertionError("prewrite abort must terminate the claim without recording consumption")
    try: _claim(repo,context,confirmation,binding)
    except ConfirmationDecisionConflict: pass
    else: raise AssertionError('The retired old confirmation cannot be reclaimed')
    _renewed, renewed_capability = _new_approved_replacement(repo, context, confirmation, binding)
    renewed = renewed_capability.consume()
    if renewed.get("external_execution_claimed") is not True or not renewed_capability.was_consumed():
        raise AssertionError("a safe abort must allow one separately approved linked new claim")


def _case_expired_prewrite_claim_recovers_safely(root: Path) -> None:
    repo, context, confirmation, binding = _new_case(root, "expired-prewrite-recovery")
    _claimed, expired_capability = _claim(repo, context, confirmation, binding)
    with repo._connect() as conn:
        conn.execute(
            "update external_execution_claims set expires_at = ? where confirmation_id = ?",
            ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(), confirmation["confirmation_id"]),
        )
    recovered = repo.recover_expired_unpublished_draft_execution_claim(
        company_id=context["company_id"],
        confirmation_id=str(confirmation["confirmation_id"]),
        user_id=context["user_id"],
    )
    if recovered.get("status") != "needs_revision" or recovered.get("writes_to_ebay") is not False:
        raise AssertionError(f"an expired unchanged prewrite claim must retire old approval: {recovered}")
    try:
        expired_capability.consume()
    except ConfirmationDecisionConflict:
        pass
    else:
        raise AssertionError("the capability from an expired recovered claim must stay permanently invalid")
    _renewed, renewed_capability = _new_approved_replacement(repo, context, confirmation, binding)
    if renewed_capability.consume().get("external_execution_claimed") is not True:
        raise AssertionError("expired safe recovery must permit one fresh independently minted claim")

    repo, context, confirmation, binding = _new_case(root, "expired-prewrite-reapproval")
    _claimed, _capability = _claim(repo, context, confirmation, binding)
    with repo._connect() as conn:
        conn.execute(
            "update external_execution_claims set expires_at = ? where confirmation_id = ?",
            ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(), confirmation["confirmation_id"]),
        )
        conn.execute(
            "update confirmations set decided_at = ? where company_id = ? and confirmation_id = ?",
            (
                (datetime.now(timezone.utc) - timedelta(minutes=16)).isoformat(),
                context["company_id"],
                confirmation["confirmation_id"],
            ),
        )
    reapproval = repo.recover_expired_unpublished_draft_execution_claim(
        company_id=context["company_id"],
        confirmation_id=str(confirmation["confirmation_id"]),
        user_id=context["user_id"],
    )
    stored = repo.get_confirmation(
        company_id=context["company_id"], confirmation_id=str(confirmation["confirmation_id"])
    ) or {}
    if (
        reapproval.get("status") != "needs_revision"
        or stored.get("status") != "needs_revision"
        or not stored.get("decided_by")
        or not stored.get("decided_at")
    ):
        raise AssertionError(f"an expired stale approval must preserve history and require a new confirmation: {reapproval}")


def _case_capability_is_opaque(root: Path) -> None:
    repo, context, confirmation, binding = _new_case(root, "opaque-capability")
    _claimed, capability = _claim(repo, context, confirmation, binding)
    boundary = repo.unpublished_draft_execution_credential_boundary(
        company_id=context["company_id"],
        store_id=context["store_id"],
    )
    sentinels = {
        str(boundary.get("connection_id") or ""),
        str(boundary.get("secret_ref") or ""),
        str(boundary.get("oauth_request_id") or ""),
        str(boundary.get("confirmation_id") or ""),
        str(boundary.get("state_nonce") or ""),
        str(boundary.get("seller_identity_hash") or ""),
        str(capability._claim_id),
        capability._nonce.hex(),
    }
    sentinels.discard("")
    rendered = repr(capability)
    if any(value in rendered for value in sentinels):
        raise AssertionError("capability repr leaked a nonce or raw backend reference")
    for serializer in (pickle.dumps, json.dumps):
        try:
            serialized = serializer(capability)
        except (TypeError, pickle.PicklingError) as exc:
            serialized = str(exc)
        else:
            raise AssertionError(f"capability unexpectedly serialized via {serializer.__name__}")
        if any(value in str(serialized) for value in sentinels):
            raise AssertionError(f"{serializer.__name__} failure leaked a nonce or raw backend reference")


def main() -> int:
    old_env = dict(os.environ)
    failures: list[str] = []
    try:
        os.environ.update(
            {
                "JIEJING_SAAS_ENV": "staging",
                "JIEJING_EBAY_CLIENT_ID": "CLAIM-CAPABILITY-CLIENT-ID",
                "JIEJING_EBAY_CLIENT_SECRET": "CLAIM-CAPABILITY-CLIENT-SECRET-DO-NOT-LEAK",
                "JIEJING_EBAY_RU_NAME": "Jiejing_Auth_RuName",
                "JIEJING_EBAY_OAUTH_EXCHANGE_LIVE": "true",
                "JIEJING_VAULT_ENABLED": "true",
                "JIEJING_VAULT_PROVIDER": "vault",
                "JIEJING_VAULT_LIVE_RESOLVE_ENABLED": "true",
                "JIEJING_VAULT_ADDR": "https://vault.example.test",
                "JIEJING_VAULT_TOKEN": "CLAIM-CAPABILITY-VAULT-TOKEN-DO-NOT-LEAK",
                "JIEJING_VAULT_MOUNT": "secret",
                "JIEJING_VAULT_KEYSPACE": "claim-capability",
                "JIEJING_VAULT_KV_VERSION": "v2",
                "JIEJING_ENABLE_REAL_PLATFORM_WRITES": "false",
                "JIEJING_EBAY_WRITE_LIVE": "false",
                "JIEJING_EBAY_DRAFT_SAVE_LIVE": "true",
            }
        )
        with tempfile.TemporaryDirectory(prefix="jiejing-draft-claim-capability-", ignore_cleanup_errors=True) as temp:
            root = Path(temp)
            cases = (
                ("legacy draft claim rejected", _case_legacy_claim_rejected),
                ("wrong claim bindings rejected", _case_wrong_claim_bindings),
                ("expired and future approval rejected", _case_invalid_approval_time),
                ("fake replay and concurrent consume", _case_fake_replay_and_concurrent_consume),
                ("post-claim payload drift rejected", _case_post_claim_payload_drift),
                ("post-claim credential drift rejected", _case_post_claim_credential_drift),
                ("prewrite abort retires old and separately approves linked new", _case_abort_restores_once_without_write_audit),
                ("expired prewrite claim recovers safely", _case_expired_prewrite_claim_recovers_safely),
                ("capability remains opaque", _case_capability_is_opaque),
            )
            for label, case in cases:
                try:
                    case(root)
                except Exception as exc:  # noqa: BLE001 - report the complete adversarial RED matrix
                    failures.append(f"{label}: {type(exc).__name__}: {exc}")
    finally:
        os.environ.clear()
        os.environ.update(old_env)
    if failures:
        print("RED jiejing_unpublished_draft_claim_capability")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print("PASS jiejing_unpublished_draft_claim_capability")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
