#!/usr/bin/env python3
"""Regression checks for the confirmation-gated eBay draft-save adapter."""

from __future__ import annotations

import json
import hashlib
import os
import pickle
import sys
from pathlib import Path
from urllib.request import Request


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_runtime import ExecutionRequest, ExecutionService  # noqa: E402
from jiejing_saas.config import SaaSSettings  # noqa: E402
from jiejing_saas.ebay_oauth import UNPUBLISHED_DRAFT_SCOPES  # noqa: E402
from jiejing_saas.ebay_write_adapter import EbayWriteHttpAdapter  # noqa: E402
from jiejing_saas.repository import (  # noqa: E402
    UnpublishedDraftClaimCapability,
    _UNPUBLISHED_DRAFT_CLAIM_MINT_TOKEN,
)


OUT = ROOT / "output" / "test-jiejing-ebay-draft-save-adapter"


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def _settings() -> SaaSSettings:
    old = dict(os.environ)
    try:
        os.environ.update(
            {
                "JIEJING_SAAS_ENV": "staging",
                "JIEJING_ENABLE_REAL_PLATFORM_WRITES": "false",
                "JIEJING_EBAY_WRITE_LIVE": "false",
                "JIEJING_EBAY_DRAFT_SAVE_LIVE": "true",
                "JIEJING_EBAY_TOKEN_REFRESH_LIVE": "true",
                "JIEJING_EBAY_READ_ONLY_LIVE": "true",
                "JIEJING_VAULT_ENABLED": "true",
            }
        )
        return SaaSSettings.from_env(
            db_path=OUT / "draft-save.sqlite",
            runtime_db_path=OUT / "runtime.sqlite",
            output_root=OUT,
            host="127.0.0.1",
            port=8788,
        )
    finally:
        os.environ.clear()
        os.environ.update(old)


def _request() -> ExecutionRequest:
    return ExecutionRequest(
        action_type="save_ebay_listing_draft",
        task_id="task_ebay_draft_save",
        user_id="user_ebay_draft_save",
        company_id="company_ebay_draft_save",
        store_id="store_ebay_draft_save",
        platform="ebay",
        confirmation_id="confirm_ebay_draft_save",
        confirmed_by="user_ebay_draft_save",
        confirmed_at="2026-07-14T20:00:00+08:00",
        idempotency_key="ebay-draft-save-001",
        payload={
            "account_health": {"status": "ready"},
            "listing": {
                "sku": "JJ-DRAFT-SAVE-001",
                "title": "Compact non-electric travel organizer",
                "description_html": "<p>Draft facts reviewed by the merchant.</p>",
                "category_id": "163222",
                "category_leaf": "Travel Organizers",
                "category_validation": {"product_match": True},
                "condition": "NEW",
                "price": {"value": "12.99", "currency": "USD"},
                "quantity": 1,
                "item_specifics": {"Brand": "Unbranded", "Material": "Polyester"},
                "merchant_location_key": "jj-main-location",
            },
            "business_policies": {
                "fulfillment_policy_id": "fulfillment-policy",
                "payment_policy_id": "payment-policy",
                "return_policy_id": "return-policy",
            },
            "asset_manifest": {
                "assets": [{"url": "https://cdn.example.test/jj-draft-save-001.jpg"}],
            },
        },
    )


def _draft_connection(**overrides: object) -> dict[str, object]:
    connection: dict[str, object] = {
        "connection_id": "conn_unpublished_draft_exact",
        "company_id": "company_ebay_draft_save",
        "store_id": "store_ebay_draft_save",
        "platform": "ebay",
        "connection_type": "oauth",
        "status": "draft_save_authorized",
        "scopes": list(UNPUBLISHED_DRAFT_SCOPES),
        "secret_ref": "vault://ebay/draft-exact",
        "metadata": {
            "oauth_request_id": "oauth_unpublished_draft_exact",
            "confirmation_id": "confirm_oauth_unpublished_draft_exact",
            "scope_profile": "seller_unpublished_draft",
            "authorization_kind": "unpublished_draft",
            "draft_save_scope_authorized": True,
            "publish_scope_authorized": False,
            "public_publish_enabled": False,
            "real_platform_writes_enabled": False,
            "credential_source": "jiejing_vault_secret_ref",
            "account_deletion_identity_mapping_status": "identity_mapping_ready",
            "ebay_user_id_hash": "seller-identity-hash",
            "secret_exposed": False,
        },
    }
    connection.update(overrides)
    return connection


def _draft_secret_ref(**overrides: object) -> dict[str, object]:
    secret: dict[str, object] = {
        "secret_ref": "vault://ebay/draft-exact",
        "company_id": "company_ebay_draft_save",
        "store_id": "store_ebay_draft_save",
        "provider": "ebay",
        "purpose": "ebay_refresh_token",
        "status": "managed_vault_stored",
        "metadata": {
            "oauth_request_id": "oauth_unpublished_draft_exact",
            "credential_owner": "jiejing_saas_backend",
            "secret_exposed": False,
        },
    }
    secret.update(overrides)
    return secret


def _credential_boundary() -> dict[str, object]:
    connection = _draft_connection()
    secret = _draft_secret_ref()
    connection_id = str(connection["connection_id"])
    secret_ref = str(connection["secret_ref"])
    metadata = connection["metadata"] if isinstance(connection.get("metadata"), dict) else {}
    oauth_request_id = str(metadata.get("oauth_request_id") or "")
    seller_identity_hash = "seller-identity-hash"
    return {
        "ready": True,
        "contract_version": "2026-08-13-unpublished-draft-credential-v1",
        "company_id": "company_ebay_draft_save",
        "store_id": "store_ebay_draft_save",
        "connection_id_sha256": hashlib.sha256(connection_id.encode("utf-8")).hexdigest(),
        "credential_ref_sha256": hashlib.sha256(secret_ref.encode("utf-8")).hexdigest(),
        "oauth_request_id_sha256": hashlib.sha256(oauth_request_id.encode("utf-8")).hexdigest(),
        "seller_identity_sha256": hashlib.sha256(seller_identity_hash.encode("utf-8")).hexdigest(),
        "connection": connection,
        "secret_reference": secret,
        "secret_exposed": False,
    }


class _TestClaimRepository:
    def __init__(self, binding: dict[str, str]) -> None:
        self.binding = dict(binding)
        self.consumed = False
        self.aborted = False

    def consume_unpublished_draft_execution_claim(self, *, capability: object) -> dict[str, object]:
        del capability
        if self.consumed or self.aborted:
            raise RuntimeError("test claim already terminal")
        self.consumed = True
        return {
            "status": "external_execution_processing_manual_reconcile",
            "external_execution_claimed": True,
            "external_execution_claim_binding": dict(self.binding),
            "secret_exposed": False,
        }

    def abort_unpublished_draft_execution_claim(self, *, capability: object, reason_code: str) -> dict[str, object]:
        del capability, reason_code
        if self.consumed or self.aborted:
            raise RuntimeError("test claim already terminal")
        self.aborted = True
        return {"status": "approved", "writes_to_ebay": False, "secret_exposed": False}


def _capability_for(prepared: object) -> UnpublishedDraftClaimCapability:
    safe = prepared.claim_binding()  # type: ignore[attr-defined]
    repository = _TestClaimRepository(safe)
    return UnpublishedDraftClaimCapability(
        claim_id="draftclaim_unit_test",
        nonce=b"unit-test-nonce-is-never-a-production-secret",
        binding=safe,
        repository=repository,  # type: ignore[arg-type]
        mint_token=_UNPUBLISHED_DRAFT_CLAIM_MINT_TOKEN,
    )


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    request = _request()
    settings = _settings()
    if settings.effective_real_platform_writes_enabled:
        return fail("the controlled draft capability must not enable broad eBay writes")
    if settings.effective_ebay_draft_save_enabled is not True:
        return fail("the narrow draft-save capability should be independently enabled")
    preflight = ExecutionService(demo_mode=False).preflight(request)
    if preflight.get("canonical_action_type") != "save_ebay_listing_draft":
        return fail(f"external draft action should keep an explicit canonical type: {preflight}")
    if preflight.get("status") != "ready_for_platform_adapter":
        return fail(f"complete confirmed draft should be ready for the eBay adapter: {preflight}")
    if preflight.get("platform_adapter_required") is not True:
        return fail(f"eBay draft save is an external write and must require an adapter: {preflight}")

    calls: list[dict[str, object]] = []

    def create_transport(http_request: Request, timeout: float) -> tuple[int, dict[str, str], bytes]:
        calls.append(
            {
                "method": http_request.get_method(),
                "url": http_request.full_url,
                "body": json.loads(http_request.data.decode("utf-8")) if http_request.data else {},
            }
        )
        if "/inventory_item/" in http_request.full_url:
            return 204, {"content-type": "application/json"}, b""
        if "/offer?sku=" in http_request.full_url:
            return 200, {"content-type": "application/json"}, json.dumps({"offers": []}).encode("utf-8")
        if http_request.full_url.endswith("/offer"):
            return 201, {"content-type": "application/json"}, json.dumps({"offerId": "offer_draft_001"}).encode("utf-8")
        raise AssertionError(f"unexpected eBay draft-save request: {http_request.get_method()} {http_request.full_url}")

    adapter = EbayWriteHttpAdapter(settings, transport=create_transport)
    adapter._resolve_access_token = lambda **_: {  # type: ignore[attr-defined]
        "ok": True,
        "access_token": "backend-only-test-token",
        "source": "vault",
    }
    prepared = adapter.prepare_listing_draft(
        request=request,
        preflight=preflight,
        credential_boundary=_credential_boundary(),
        marketplace_id="EBAY_US",
    )
    if prepared.__class__.__name__ != "_DraftPreparationHandle":
        return fail(f"valid exact credential and payload should prepare one draft write: {prepared}")
    legacy_calls = len(calls)
    legacy = adapter.save_listing_draft(
        request=request,
        preflight=preflight,
        connections=[_draft_connection()],
        secret_refs=[_draft_secret_ref()],
        marketplace_id="EBAY_US",
    )
    if legacy.get("status") != "draft_prepare_claim_execute_required" or len(calls) != legacy_calls:
        return fail("legacy draft wrapper must be permanently blocked before token or eBay access")
    prepared_text = repr(prepared)
    if any(sentinel in prepared_text for sentinel in ("backend-only-test-token", "vault://", "oauth_unpublished")):
        return fail("opaque preparation handle repr must not expose token or credential identifiers")
    try:
        pickle.dumps(prepared)
    except (TypeError, pickle.PicklingError):
        pass
    else:
        return fail("opaque preparation handle must not be serializable")
    if [call.get("method") for call in calls] != ["GET"]:
        return fail(f"prepare must perform only the deterministic offer inspection GET: {calls}")
    created = adapter.execute_prepared_listing_draft(
        request=request,
        preflight=preflight,
        prepared=prepared,
        claim_capability=_capability_for(prepared),
        marketplace_id="EBAY_US",
    )
    if created.get("status") != "saved_to_ebay_draft":
        return fail(f"new offer should be saved as an unpublished eBay draft: {created}")
    if created.get("platform_result", {}).get("published_to_ebay") is not False:
        return fail(f"draft save must explicitly prove no public listing was created: {created}")
    if any("/publish" in str(call.get("url") or "") for call in calls):
        return fail(f"draft save must never call publishOffer: {calls}")
    if [call.get("method") for call in calls] != ["GET", "GET", "PUT", "POST"]:
        return fail(f"new draft should inspect offers before any write, then stage inventory and create one offer: {calls}")
    if not all(
        created.get("platform_result", {}).get(key)
        for key in ("connection_id_sha256", "credential_ref_sha256", "oauth_request_id_sha256", "seller_identity_sha256")
    ):
        return fail("draft receipt must bind value-free hashes for the exact OAuth connection, secret, request and seller")
    if created.get("platform_result", {}).get("contract_version") != "2026-08-13-unpublished-draft-credential-v1":
        return fail("draft receipt must retain the versioned credential binding contract")
    serialized_created = json.dumps(created, ensure_ascii=False, sort_keys=True)
    for sentinel in ("vault://ebay/draft-exact", "oauth_unpublished_draft_exact", "backend-only-test-token"):
        if sentinel in serialized_created:
            return fail("draft result must contain only value-free credential hashes")
    replay_calls = len(calls)
    replay = adapter.execute_prepared_listing_draft(
        request=request,
        preflight=preflight,
        prepared=prepared,
        claim_capability=_capability_for(prepared),
        marketplace_id="EBAY_US",
    )
    if replay.get("status") != "prepared_draft_binding_invalid" or len(calls) != replay_calls:
        return fail("the same preparation handle must be one-shot and perform zero replay writes")

    attacks = [
        ("legacy publish status", [_draft_connection(status="publish_authorized")], [_draft_secret_ref()]),
        ("read-only status", [_draft_connection(status="read_only_authorized")], [_draft_secret_ref()]),
        (
            "duplicate exact connections",
            [_draft_connection(), _draft_connection(connection_id="conn_duplicate")],
            [_draft_secret_ref()],
        ),
        ("wrong store connection", [_draft_connection(store_id="store_other")], [_draft_secret_ref()]),
        (
            "detached secret reference",
            [_draft_connection()],
            [_draft_secret_ref(secret_ref="vault://ebay/not-the-connection-secret")],
        ),
        (
            "wrong oauth request secret",
            [_draft_connection()],
            [_draft_secret_ref(metadata={"oauth_request_id": "oauth_other", "credential_owner": "jiejing_saas_backend"})],
        ),
    ]
    for label, attack_connections, attack_secrets in attacks:
        attack_calls_before = len(calls)
        attack_boundary = _credential_boundary()
        attack_boundary["connection"] = attack_connections[0] if attack_connections else {}
        attack_boundary["secret_reference"] = attack_secrets[0] if attack_secrets else {}
        if len(attack_connections) != 1:
            attack_boundary["ready"] = False
        attack = adapter.prepare_listing_draft(
            request=request,
            preflight=preflight,
            credential_boundary=attack_boundary,
            marketplace_id="EBAY_US",
        )
        if attack.get("status") != "ebay_draft_connection_boundary_not_ready":
            return fail(f"{label} must fail closed before token resolution or eBay access: {attack}")
        if len(calls) != attack_calls_before:
            return fail(f"{label} must not call eBay: {calls[attack_calls_before:]}")
    broad_publish = adapter.publish_listing(
        request=ExecutionRequest(
            action_type="publish_listing",
            task_id=request.task_id,
            user_id=request.user_id,
            company_id=request.company_id,
            store_id=request.store_id,
            platform="ebay",
            payload=request.payload,
            confirmation_id=request.confirmation_id,
            confirmed_by=request.confirmed_by,
            confirmed_at=request.confirmed_at,
            idempotency_key="broad-publish-must-stay-blocked",
        ),
        preflight=preflight,
        connections=[],
        secret_refs=[],
        marketplace_id="EBAY_US",
    )
    if broad_publish.get("status") != "real_platform_writes_disabled":
        return fail(f"draft-only mode must keep public publish blocked: {broad_publish}")

    update_calls: list[dict[str, object]] = []

    def update_transport(http_request: Request, timeout: float) -> tuple[int, dict[str, str], bytes]:
        update_calls.append({"method": http_request.get_method(), "url": http_request.full_url})
        if "/inventory_item/" in http_request.full_url:
            return 204, {}, b""
        if "/offer?sku=" in http_request.full_url:
            return 200, {}, json.dumps(
                {
                    "offers": [
                        {
                            "offerId": "offer_draft_existing",
                            "marketplaceId": "EBAY_US",
                            "listingStatus": "UNPUBLISHED",
                        }
                    ]
                }
            ).encode("utf-8")
        if http_request.full_url.endswith("/offer/offer_draft_existing"):
            return 204, {}, b""
        raise AssertionError(f"unexpected eBay draft update request: {http_request.get_method()} {http_request.full_url}")

    update_adapter = EbayWriteHttpAdapter(_settings(), transport=update_transport)
    update_adapter._resolve_access_token = adapter._resolve_access_token  # type: ignore[attr-defined]
    update_prepared = update_adapter.prepare_listing_draft(
        request=request,
        preflight=preflight,
        credential_boundary=_credential_boundary(),
        marketplace_id="EBAY_US",
    )
    if update_prepared.__class__.__name__ != "_DraftPreparationHandle":
        return fail(f"existing unpublished offer should prepare for an in-place update: {update_prepared}")
    updated = update_adapter.execute_prepared_listing_draft(
        request=request,
        preflight=preflight,
        prepared=update_prepared,
        claim_capability=_capability_for(update_prepared),
        marketplace_id="EBAY_US",
    )
    if updated.get("status") != "saved_to_ebay_draft":
        return fail(f"existing unpublished offer should be updated in place: {updated}")
    if [call.get("method") for call in update_calls] != ["GET", "GET", "PUT", "PUT"]:
        return fail(f"retry should inspect first and update the existing unpublished offer instead of creating a duplicate: {update_calls}")
    if any("/publish" in str(call.get("url") or "") for call in update_calls):
        return fail(f"draft update must never call publishOffer: {update_calls}")

    published_calls: list[dict[str, object]] = []

    def published_transport(http_request: Request, timeout: float) -> tuple[int, dict[str, str], bytes]:
        published_calls.append({"method": http_request.get_method(), "url": http_request.full_url})
        if "/inventory_item/" in http_request.full_url:
            return 204, {}, b""
        if "/offer?sku=" in http_request.full_url:
            return 200, {}, json.dumps(
                {
                    "offers": [
                        {
                            "offerId": "offer_already_live",
                            "marketplaceId": "EBAY_US",
                            "listingStatus": "PUBLISHED",
                        }
                    ]
                }
            ).encode("utf-8")
        raise AssertionError(f"published offer must block before any offer write: {http_request.get_method()} {http_request.full_url}")

    published_adapter = EbayWriteHttpAdapter(_settings(), transport=published_transport)
    published_adapter._resolve_access_token = adapter._resolve_access_token  # type: ignore[attr-defined]
    blocked = published_adapter.prepare_listing_draft(
        request=request,
        preflight=preflight,
        credential_boundary=_credential_boundary(),
        marketplace_id="EBAY_US",
    )
    if blocked.get("status") != "blocked_existing_published_offer":
        return fail(f"draft save must not revise an already published offer: {blocked}")
    if [call.get("method") for call in published_calls] != ["GET"]:
        return fail(f"published-offer guard should stop before every platform write: {published_calls}")
    if blocked.get("platform_result", {}).get("writes_to_ebay") is not False:
        return fail(f"published-offer guard should prove that no eBay write occurred: {blocked}")
    if blocked.get("platform_result", {}).get("public_listing_created") is not False:
        return fail(f"published-offer guard must never claim a new public listing: {blocked}")

    changed_calls: list[dict[str, object]] = []

    def changed_transport(http_request: Request, timeout: float) -> tuple[int, dict[str, str], bytes]:
        del timeout
        changed_calls.append({"method": http_request.get_method(), "url": http_request.full_url})
        if "/offer?sku=" not in http_request.full_url:
            raise AssertionError("offer-state change must stop before every write")
        offers = [] if len(changed_calls) == 1 else [
            {
                "offerId": "offer_became_live_after_prepare",
                "marketplaceId": "EBAY_US",
                "listingStatus": "PUBLISHED",
            }
        ]
        return 200, {}, json.dumps({"offers": offers}).encode("utf-8")

    changed_adapter = EbayWriteHttpAdapter(_settings(), transport=changed_transport)
    changed_adapter._resolve_access_token = adapter._resolve_access_token  # type: ignore[attr-defined]
    changed_prepared = changed_adapter.prepare_listing_draft(
        request=request,
        preflight=preflight,
        credential_boundary=_credential_boundary(),
        marketplace_id="EBAY_US",
    )
    changed_capability = _capability_for(changed_prepared)
    changed = changed_adapter.execute_prepared_listing_draft(
        request=request,
        preflight=preflight,
        prepared=changed_prepared,
        claim_capability=changed_capability,
        marketplace_id="EBAY_US",
    )
    if changed.get("status") != "blocked_offer_state_changed_before_write":
        return fail(f"offer becoming published after prepare must block the write: {changed}")
    if [call.get("method") for call in changed_calls] != ["GET", "GET"]:
        return fail(f"offer-state change may perform the second GET but no PUT/POST: {changed_calls}")
    if not changed_capability._repository.aborted or changed_capability._repository.consumed:  # type: ignore[attr-defined]
        return fail("offer-state change must abort, not consume, the DB-backed claim")

    print("PASS jiejing_ebay_draft_save_adapter")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
