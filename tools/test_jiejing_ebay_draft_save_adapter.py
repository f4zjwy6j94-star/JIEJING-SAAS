#!/usr/bin/env python3
"""Regression checks for the confirmation-gated eBay draft-save adapter."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from urllib.request import Request


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_runtime import ExecutionRequest, ExecutionService  # noqa: E402
from jiejing_saas.config import SaaSSettings  # noqa: E402
from jiejing_saas.ebay_write_adapter import EbayWriteHttpAdapter  # noqa: E402


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
                "JIEJING_ENABLE_REAL_PLATFORM_WRITES": "true",
                "JIEJING_EBAY_WRITE_LIVE": "true",
                "JIEJING_EBAY_TOKEN_REFRESH_LIVE": "true",
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


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    request = _request()
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

    adapter = EbayWriteHttpAdapter(_settings(), transport=create_transport)
    adapter._resolve_access_token = lambda **_: {  # type: ignore[attr-defined]
        "ok": True,
        "access_token": "backend-only-test-token",
        "source": "vault",
    }
    created = adapter.save_listing_draft(
        request=request,
        preflight=preflight,
        connections=[
            {
                "platform": "ebay",
                "connection_type": "oauth",
                "scopes": ["https://api.ebay.com/oauth/api_scope/sell.inventory"],
                "secret_ref": "vault://ebay/test",
            }
        ],
        secret_refs=[],
        marketplace_id="EBAY_US",
    )
    if created.get("status") != "saved_to_ebay_draft":
        return fail(f"new offer should be saved as an unpublished eBay draft: {created}")
    if created.get("platform_result", {}).get("published_to_ebay") is not False:
        return fail(f"draft save must explicitly prove no public listing was created: {created}")
    if any("/publish" in str(call.get("url") or "") for call in calls):
        return fail(f"draft save must never call publishOffer: {calls}")
    if [call.get("method") for call in calls] != ["GET", "PUT", "POST"]:
        return fail(f"new draft should inspect offers before any write, then stage inventory and create one offer: {calls}")

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
    updated = update_adapter.save_listing_draft(
        request=request,
        preflight=preflight,
        connections=[
            {
                "platform": "ebay",
                "connection_type": "oauth",
                "scopes": ["https://api.ebay.com/oauth/api_scope/sell.inventory"],
                "secret_ref": "vault://ebay/test",
            }
        ],
        secret_refs=[],
        marketplace_id="EBAY_US",
    )
    if updated.get("status") != "saved_to_ebay_draft":
        return fail(f"existing unpublished offer should be updated in place: {updated}")
    if [call.get("method") for call in update_calls] != ["GET", "PUT", "PUT"]:
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
    blocked = published_adapter.save_listing_draft(
        request=request,
        preflight=preflight,
        connections=[
            {
                "platform": "ebay",
                "connection_type": "oauth",
                "scopes": ["https://api.ebay.com/oauth/api_scope/sell.inventory"],
                "secret_ref": "vault://ebay/test",
            }
        ],
        secret_refs=[],
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

    print("PASS jiejing_ebay_draft_save_adapter")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
