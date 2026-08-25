"""Regression for publishing one exact existing eBay draft without creating a second offer."""

from __future__ import annotations

import json
import hashlib
import os
import sys
from pathlib import Path
from urllib.request import Request


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_runtime.execution import ExecutionRequest, ExecutionService  # noqa: E402
from jiejing_saas.api_server import (  # noqa: E402
    _controlled_existing_draft_publish_context,
    _controlled_existing_draft_publish_preflight,
)
from jiejing_saas.config import SaaSSettings  # noqa: E402
from jiejing_saas.ebay_write_adapter import EbayWriteHttpAdapter, build_publish_readiness  # noqa: E402
from jiejing_saas.ebay_oauth import UNPUBLISHED_DRAFT_SCOPES  # noqa: E402


OUT = ROOT / "output" / "test-jiejing-controlled-existing-draft-publish"
OFFER_ID = "245675556011"
SKU = "JJ-INCENSE-JC2023041300002-01"


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def credential_boundary() -> dict[str, object]:
    connection_id = "conn_controlled_publish"
    secret_ref_id = "secret_ref_publish"
    oauth_request_id = "oauth_controlled_publish"
    seller_identity = "seller-controlled-publish"
    connection = {
        "connection_id": connection_id,
        "company_id": "company_test",
        "store_id": "store_test",
        "platform": "ebay",
        "connection_type": "oauth",
        "status": "draft_save_authorized",
        "scopes": list(UNPUBLISHED_DRAFT_SCOPES),
        "secret_ref": secret_ref_id,
        "metadata": {
            "oauth_request_id": oauth_request_id,
            "confirmation_id": "confirm_oauth_controlled_publish",
            "scope_profile": "seller_unpublished_draft",
            "authorization_kind": "unpublished_draft",
            "draft_save_scope_authorized": True,
            "publish_scope_authorized": False,
            "public_publish_enabled": False,
            "real_platform_writes_enabled": False,
            "credential_source": "jiejing_vault_secret_ref",
            "account_deletion_identity_mapping_status": "identity_mapping_ready",
            "ebay_user_id_hash": seller_identity,
            "secret_exposed": False,
        },
    }
    secret = {
        "secret_ref": secret_ref_id,
        "company_id": "company_test",
        "store_id": "store_test",
        "provider": "ebay",
        "purpose": "ebay_refresh_token",
        "status": "managed_vault_stored",
        "metadata": {
            "oauth_request_id": oauth_request_id,
            "credential_owner": "jiejing_saas_backend",
            "secret_exposed": False,
        },
    }
    digest = lambda value: hashlib.sha256(value.encode("utf-8")).hexdigest()
    return {
        "ready": True,
        "contract_version": "2026-08-13-unpublished-draft-credential-v1",
        "company_id": "company_test",
        "store_id": "store_test",
        "connection_id_sha256": digest(connection_id),
        "credential_ref_sha256": digest(secret_ref_id),
        "oauth_request_id_sha256": digest(oauth_request_id),
        "seller_identity_sha256": digest(seller_identity),
        "connection": connection,
        "secret_reference": secret,
        "secret_exposed": False,
    }


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    os.environ.update(
        {
            "JIEJING_SAAS_ENV": "production",
            "JIEJING_ENABLE_REAL_PLATFORM_WRITES": "false",
            "JIEJING_EBAY_WRITE_LIVE": "false",
            "JIEJING_EBAY_CONTROLLED_PUBLISH_LIVE": "true",
            "JIEJING_EBAY_DRAFT_SAVE_LIVE": "true",
            "JIEJING_EBAY_READ_ONLY_LIVE": "true",
            "JIEJING_EBAY_TOKEN_REFRESH_LIVE": "true",
            "JIEJING_EBAY_CLIENT_ID": "test-client-id",
            "JIEJING_EBAY_CLIENT_SECRET": "test-client-secret",
            "JIEJING_EBAY_RU_NAME": "test-ru-name",
            "JIEJING_VAULT_ENABLED": "true",
            "JIEJING_VAULT_PROVIDER": "vault",
            "JIEJING_VAULT_LIVE_RESOLVE_ENABLED": "true",
            "JIEJING_VAULT_ADDR": "https://vault.test",
            "JIEJING_VAULT_TOKEN": "vault-token",
            "JIEJING_VAULT_KEYSPACE": "jiejing-test",
        }
    )
    settings = SaaSSettings.from_env(
        db_path=OUT / "db.sqlite",
        runtime_db_path=OUT / "runtime.sqlite",
        output_root=OUT,
        host="127.0.0.1",
        port=8797,
    )
    if settings.effective_real_platform_writes_enabled is not False:
        return fail("controlled publish must not turn on broad platform writes")
    if settings.effective_ebay_controlled_publish_enabled is not True:
        return fail("exact existing-draft publish lane should be enabled")

    publish_payload = {
        "account_health": {"status": "clear", "selling_status": "active", "payout_status": "available", "restrictions": []},
        "listing": {
            "sku": SKU,
            "title": "Backflow Incense Burner with Lotus Flower and Hand Design",
            "description_html": "<p>Backflow incense burner.</p>",
            "category_id": "20552",
            "condition": "NEW",
            "price": {"value": "29.99", "currency": "USD"},
            "quantity": 1,
            "item_specifics": {"Brand": "Unbranded", "Type": "Backflow Incense Burner"},
            "merchant_location_key": "shenzhen-warehouse",
        },
        "business_policies": {
            "fulfillment_policy_id": "252706512026",
            "payment_policy_id": "252706224026",
            "return_policy_id": "252706513026",
        },
        "supplier_facts": {
            "package_weight_g": 451,
            "package_dimensions_cm": {"length": 16.2, "width": 7.7, "height": 17.9},
            "material": "supplier-confirmed-material",
            "item_location": "shenzhen-warehouse",
        },
        "asset_manifest": {"assets": [{"url": "https://example.test/generated-approved.jpg"}]},
        "finance_review": {"net_profit_money": {"value": "5.00", "currency": "USD"}},
        "existing_ebay_draft": {
            "offer_id": OFFER_ID,
            "sku": SKU,
            "source_execution_id": "exec_draft_1",
            "source_confirmation_id": "confirm_draft_1",
            "offer_status": "UNPUBLISHED",
            "public_listing_created": False,
        },
        "secret_exposed": False,
    }
    executions = [
        {
            "execution_id": "exec_draft_1",
            "confirmation_id": "confirm_draft_1",
            "action_type": "save_ebay_listing_draft",
            "status": "saved_to_ebay_draft",
            "result": {
                "status": "saved_to_ebay_draft",
                "secret_exposed": False,
                "platform_result": {
                    "offer_id": OFFER_ID,
                    "offer_status": "UNPUBLISHED",
                    "sku": SKU,
                    "writes_to_ebay": True,
                    "published_to_ebay": False,
                    "public_listing_created": False,
                },
            },
        }
    ]
    confirmations = [
        {
            "confirmation_id": "confirm_draft_1",
            "company_id": "company_test",
            "store_id": "store_test",
            "action_type": "save_ebay_listing_draft",
            "status": "executed",
            "item": {"publish_payload": publish_payload, "secret_exposed": False},
        }
    ]
    context = _controlled_existing_draft_publish_context(
        execution_results=executions,
        confirmations=confirmations,
        company_id="company_test",
        store_id="store_test",
        offer_id=OFFER_ID,
        sku=SKU,
        execution_id="exec_draft_1",
    )
    if context.get("status") != "ready" or context.get("publish_payload", {}).get("listing", {}).get("sku") != SKU:
        return fail(f"exact draft evidence should produce a controlled publish context: {context}")
    if context.get("source_confirmation_id") != "confirm_draft_1" or context.get("source_execution_id") != "exec_draft_1":
        return fail(f"controlled publish context lost its source binding: {context}")

    readiness = build_publish_readiness(
        context["publish_payload"],
        preflight={"status": "ready_for_platform_adapter", "missing_fields": []},
        latest_execution_results=executions,
        recent_confirmations=confirmations,
    )
    duplicate_check = next(
        (item for item in readiness.get("checks", []) if item.get("key") == "new_product_duplicate_guard"),
        {},
    )
    if duplicate_check.get("blocking") is not False:
        return fail(f"the source draft must not be mistaken for a duplicate product: {duplicate_check}")

    request = ExecutionRequest(
        action_type="publish_listing",
        task_id="task_publish_existing",
        user_id="user_test",
        company_id="company_test",
        store_id="store_test",
        platform="ebay",
        confirmation_id="confirm_publish_existing",
        confirmed_by="user_test",
        confirmed_at="2026-08-26T00:00:00+00:00",
        idempotency_key="publish-existing-offer-1",
        payload=context["publish_payload"],
    )
    preflight = ExecutionService(demo_mode=False).preflight(request)
    if preflight.get("status") != "ready_for_platform_adapter":
        return fail(f"controlled publish payload should pass execution preflight: {preflight}")

    disclosed_gap_payload = json.loads(json.dumps(context["publish_payload"]))
    disclosed_gap_payload["supplier_facts"] = {"item_location": "shenzhen-warehouse"}
    disclosed_gap_payload["finance_review"] = {}
    disclosed_gap_request = ExecutionRequest(
        action_type="publish_listing",
        task_id="task_publish_existing_disclosed_gaps",
        user_id="user_test",
        company_id="company_test",
        store_id="store_test",
        platform="ebay",
        confirmation_id="confirm_publish_existing_disclosed_gaps",
        confirmed_by="user_test",
        confirmed_at="2026-08-26T00:00:00+00:00",
        idempotency_key="publish-existing-offer-disclosed-gaps-1",
        payload=disclosed_gap_payload,
    )
    controlled_preflight = _controlled_existing_draft_publish_preflight(
        disclosed_gap_request,
        require_confirmation=True,
    )
    if controlled_preflight.get("status") != "ready_for_platform_adapter":
        return fail(f"non-buyer-facing supplier/profit gaps should be disclosed warnings: {controlled_preflight}")
    expected_warnings = {
        "supplier_facts.package_weight_g",
        "supplier_facts.package_dimensions_cm",
        "supplier_facts.material",
        "finance_review.net_profit_money",
    }
    if not expected_warnings.issubset(set(controlled_preflight.get("disclosed_missing_facts") or [])):
        return fail(f"controlled publish did not disclose every retained fact gap: {controlled_preflight}")
    blocked_payload = json.loads(json.dumps(disclosed_gap_payload))
    blocked_payload["listing"]["title"] = ""
    blocked_request = ExecutionRequest(
        action_type="publish_listing",
        task_id="task_publish_existing_missing_title",
        user_id="user_test",
        company_id="company_test",
        store_id="store_test",
        platform="ebay",
        confirmation_id="confirm_publish_existing_missing_title",
        confirmed_by="user_test",
        confirmed_at="2026-08-26T00:00:00+00:00",
        idempotency_key="publish-existing-offer-missing-title-1",
        payload=blocked_payload,
    )
    blocked_preflight = _controlled_existing_draft_publish_preflight(blocked_request, require_confirmation=True)
    if blocked_preflight.get("status") == "ready_for_platform_adapter" or "listing.title" not in (
        blocked_preflight.get("missing_fields") or []
    ):
        return fail(f"buyer-facing listing facts must remain hard blockers: {blocked_preflight}")

    calls: list[tuple[str, str, dict]] = []

    def transport(http_request: Request, timeout: float) -> tuple[int, dict[str, str], bytes]:
        del timeout
        body = {}
        if getattr(http_request, "data", None):
            try:
                body = json.loads((http_request.data or b"{}").decode("utf-8") or "{}")
            except json.JSONDecodeError:
                body = {}
        calls.append((http_request.get_method(), http_request.full_url, body))
        if http_request.full_url.startswith("https://vault.test/"):
            return 200, {"content-type": "application/json"}, json.dumps({"data": {"data": {"refresh_token": "TEST_REFRESH_TOKEN"}}}).encode()
        if http_request.full_url.endswith("/identity/v1/oauth2/token"):
            return 200, {"content-type": "application/json"}, json.dumps({"access_token": "TEST_ACCESS_TOKEN", "expires_in": 7200}).encode()
        if "/offer?sku=" in http_request.full_url:
            return 200, {"content-type": "application/json"}, json.dumps(
                {"offers": [{"offerId": OFFER_ID, "marketplaceId": "EBAY_US", "status": "UNPUBLISHED"}]}
            ).encode()
        if http_request.full_url.endswith(f"/offer/{OFFER_ID}/publish"):
            return 200, {"content-type": "application/json"}, json.dumps({"listingId": "listing_987"}).encode()
        return 500, {"content-type": "application/json"}, b"{}"

    result = EbayWriteHttpAdapter(settings, transport=transport).publish_existing_listing_draft(
        request=request,
        preflight=preflight,
        credential_boundary=credential_boundary(),
        marketplace_id="EBAY_US",
        expected_offer_id=OFFER_ID,
    )
    if result.get("status") != "published_to_ebay" or result.get("platform_result", {}).get("offer_id") != OFFER_ID:
        return fail(f"exact existing offer should publish successfully: {result}; calls={calls}")
    ebay_calls = [item for item in calls if item[1].startswith("https://api.ebay.com/sell/inventory/")]
    if [item[0] for item in ebay_calls] != ["GET", "POST"]:
        return fail(f"controlled publish must only inspect then publish: {ebay_calls}")
    if any(item[1].endswith("/offer") or "/inventory_item/" in item[1] for item in ebay_calls):
        return fail(f"controlled publish must never create another offer or replace inventory: {ebay_calls}")

    mismatch_calls: list[tuple[str, str]] = []

    def mismatch_transport(http_request: Request, timeout: float) -> tuple[int, dict[str, str], bytes]:
        del timeout
        mismatch_calls.append((http_request.get_method(), http_request.full_url))
        if http_request.full_url.startswith("https://vault.test/"):
            return 200, {"content-type": "application/json"}, json.dumps({"data": {"data": {"refresh_token": "TEST_REFRESH_TOKEN"}}}).encode()
        if http_request.full_url.endswith("/identity/v1/oauth2/token"):
            return 200, {"content-type": "application/json"}, json.dumps({"access_token": "TEST_ACCESS_TOKEN", "expires_in": 7200}).encode()
        if "/offer?sku=" in http_request.full_url:
            return 200, {"content-type": "application/json"}, json.dumps(
                {"offers": [{"offerId": "different-offer", "marketplaceId": "EBAY_US", "status": "UNPUBLISHED"}]}
            ).encode()
        return 500, {"content-type": "application/json"}, b"{}"

    blocked = EbayWriteHttpAdapter(settings, transport=mismatch_transport).publish_existing_listing_draft(
        request=request,
        preflight=preflight,
        credential_boundary=credential_boundary(),
        marketplace_id="EBAY_US",
        expected_offer_id=OFFER_ID,
    )
    if blocked.get("status") != "controlled_publish_offer_mismatch":
        return fail(f"offer mismatch must fail closed: {blocked}")
    if any(method == "POST" and url.endswith("/publish") for method, url in mismatch_calls):
        return fail(f"offer mismatch must not call publishOffer: {mismatch_calls}")

    print("PASS jiejing_controlled_existing_draft_publish")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
