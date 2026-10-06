#!/usr/bin/env python3
"""Regression tests for the first real eBay publish adapter boundary."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from jiejing_runtime.execution import ExecutionRequest, ExecutionService
from jiejing_saas.api_server import _apply_publish_recovery_execution_context
from jiejing_saas.config import SaaSSettings
from jiejing_saas.ebay_write_adapter import EbayWriteHttpAdapter, build_ebay_write_adapter_contract, build_publish_readiness
from jiejing_saas.repository import SaaSRepository


OUT = ROOT / "output" / "jiejing-saas-backend" / "write-adapter-test"


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def attach_publish_evidence(
    payload: dict[str, object],
    *,
    company_id: str = "company_test",
    store_id: str = "store_test",
    project_key: str = "listing-project-write-adapter-test",
) -> None:
    report_id = "report_write_adapter_test"
    payload["listing_project_identity"] = {
        "key": project_key,
        "source_report_id": report_id,
        "candidate_id": "candidate_write_adapter_test",
    }
    manifest = payload.get("asset_manifest") if isinstance(payload.get("asset_manifest"), dict) else {}
    raw_assets = manifest.get("assets") if isinstance(manifest.get("assets"), list) else []
    covered_assets = []
    for item in raw_assets:
        asset = item if isinstance(item, dict) else {}
        url = str(asset.get("url") or asset.get("url_or_file_path") or "")
        covered_assets.append(
            {
                "asset_id": str(asset.get("asset_id") or ""),
                "url_sha256": hashlib.sha256(url.encode("utf-8")).hexdigest(),
                "evidence_type": "merchant_product_fact_report",
                "evidence_id": report_id,
            }
        )
    evidence = {
        "contract_version": "2026-08-31-publish-source-rights-evidence-v1",
        "status": "ready",
        "server_resolved": True,
        "scope": {"company_id": company_id, "store_id": store_id, "listing_project_key": project_key},
        "refs": {"product_fact_report_id": report_id, "media_job_id": ""},
        "product_source": {
            "status": "verified",
            "source_mode": "merchant_owned_product",
            "evidence_type": "merchant_product_fact_report",
            "evidence_id": report_id,
        },
        "image_rights": {
            "status": "verified",
            "required_asset_count": len(covered_assets),
            "covered_asset_count": len(covered_assets),
            "coverage_complete": True,
            "assets": covered_assets,
        },
        "secret_exposed": False,
    }
    evidence["fingerprint"] = hashlib.sha256(
        json.dumps(evidence, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    evidence["resolved_at"] = "2026-08-31T00:00:00Z"
    payload["publish_evidence"] = evidence


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    os.environ.update(
        {
            "JIEJING_SAAS_ENV": "staging",
            "JIEJING_ENABLE_REAL_PLATFORM_WRITES": "true",
            "JIEJING_EBAY_WRITE_LIVE": "true",
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
    contract = build_ebay_write_adapter_contract(settings)
    if contract.get("enabled") is not True or contract.get("writes_supported") is not True:
        return fail(f"write adapter should be enabled with explicit staging write flags: {contract}")

    request = ExecutionRequest(
        action_type="publish_listing",
        task_id="task_publish_test",
        user_id="user_test",
        company_id="company_test",
        store_id="store_test",
        platform="ebay",
        confirmation_id="confirm_publish_test",
        confirmed_by="user_test",
        confirmed_at="2026-05-22T00:00:00+00:00",
        idempotency_key="publish-test-001",
        payload={
            "account_health": {
                "status": "clear",
                "selling_status": "active",
                "payout_status": "available",
                "restrictions": [],
            },
            "listing": {
                "sku": "JJ-PUBLISH-TEST-001",
                "title": "Backflow Incense Burner Test Listing",
                "description_html": "<p>Backflow incense burner test listing.</p>",
                "category_id": "159895",
                "condition": "NEW",
                "price": {"value": "22.99", "currency": "USD"},
                "quantity": 1,
                "item_specifics": {"Brand": "Unbranded", "Type": "Incense Burner"},
                "merchant_location_key": "default",
            },
            "business_policies": {
                "fulfillment_policy_id": "fulfillment-policy",
                "payment_policy_id": "payment-policy",
                "return_policy_id": "return-policy",
            },
            "supplier_facts": {
                "package_weight_g": 650,
                "package_dimensions_cm": {"length": 20, "width": 15, "height": 12},
                "material": "Ceramic",
                "item_location": "US",
            },
            "asset_manifest": {"assets": [{"url": "https://example.com/image.jpg"}]},
            "finance_review": {"net_profit_money": {"value": "6.50", "currency": "USD"}},
        },
    )
    attach_publish_evidence(request.payload)
    preflight = ExecutionService(demo_mode=False).preflight(request)
    if preflight.get("status") != "ready_for_platform_adapter":
        return fail(f"publish preflight should be ready: {preflight}")
    readiness = build_publish_readiness(request.payload, preflight=preflight)
    if readiness.get("status") != "ready_for_execution" or readiness.get("blocking_check_count") != 0:
        return fail(f"complete publish payload should be ready: {readiness}")
    traffic = readiness.get("traffic_light_report", {})
    if traffic.get("decision") != "yellow_review_required" or traffic.get("red_count") != 0 or traffic.get("yellow_count", 0) < 1:
        return fail(f"publish payload with missing profit inputs should produce a yellow traffic-light report: {traffic}")
    if traffic.get("can_enter_confirmation_center") is not True:
        return fail(f"yellow publish-health report should still be allowed into confirmation center: {traffic}")
    if traffic.get("requires_confirmation_center") is not True or traffic.get("real_write_allowed_without_confirmation") is not False:
        return fail(f"traffic-light report must preserve confirmation center boundary: {traffic}")
    exposure_check = next((item for item in readiness.get("checks", []) if item.get("key") == "price_quantity_exposure"), {})
    if exposure_check.get("details", {}).get("estimated_listing_amount") != 22.99:
        return fail(f"readiness should expose price x quantity amount: {readiness}")
    readiness_keys = {item.get("key") for item in readiness.get("checks", [])}
    for required_check in {
        "item_specifics_quality",
        "buyer_copy_fact_boundary",
        "ip_vero_and_claims",
        "gpsr_regulatory_fields",
        "profit_and_fee_sanity",
        "inventory_api_lifecycle",
        "new_product_duplicate_guard",
        "account_health_gate",
    }:
        if required_check not in readiness_keys:
            return fail(f"publish readiness missing operating safety check {required_check}: {readiness}")
    for required_section in {
        "post_publish_cockpit_plan",
        "failure_knowledge_base",
        "merchant_rule_memory_policy",
        "trusted_source_policy",
    }:
        if not isinstance(readiness.get(required_section), dict):
            return fail(f"publish readiness missing {required_section}: {readiness}")
    profit_check = next((item for item in readiness.get("checks", []) if item.get("key") == "profit_and_fee_sanity"), {})
    profit_details = profit_check.get("details", {}) if isinstance(profit_check.get("details"), dict) else {}
    for required_profit_field in {"ebay_fee", "ad_budget", "shipping_cost", "return_risk_reserve", "exchange_rate", "effective_profit"}:
        if required_profit_field not in profit_details:
            return fail(f"profit brain should expose {required_profit_field}: {readiness}")
    duplicate_readiness = build_publish_readiness(
        request.payload,
        preflight=preflight,
        recent_confirmations=[{"confirmation_id": "old_confirm", "item": {"publish_payload": deepcopy(request.payload)}}],
    )
    duplicate_blocked = {item.get("key") for item in duplicate_readiness.get("checks", []) if item.get("blocking")}
    if duplicate_readiness.get("status") != "blocked_missing_facts" or "new_product_duplicate_guard" not in duplicate_blocked:
        return fail(f"duplicate SKU/image should block repeat product tests: {duplicate_readiness}")
    if duplicate_readiness.get("traffic_light_report", {}).get("decision") != "red_blocked":
        return fail(f"duplicate SKU/image should produce a red traffic-light report: {duplicate_readiness}")

    missing_account_health_payload = deepcopy(request.payload)
    missing_account_health_payload.pop("account_health")
    missing_account_health_preflight = ExecutionService(demo_mode=False).preflight(
        ExecutionRequest(
            action_type="publish_listing",
            task_id="task_publish_test",
            user_id="user_test",
            company_id="company_test",
            store_id="store_test",
            platform="ebay",
            confirmation_id="confirm_publish_test",
            confirmed_by="user_test",
            confirmed_at="2026-05-22T00:00:00+00:00",
            idempotency_key="publish-test-001-missing-account-health",
            payload=missing_account_health_payload,
        )
    )
    missing_account_health_readiness = build_publish_readiness(missing_account_health_payload, preflight=missing_account_health_preflight)
    missing_account_health_blocked = {item.get("key") for item in missing_account_health_readiness.get("checks", []) if item.get("blocking")}
    if "account_health_gate" not in missing_account_health_blocked:
        return fail(f"missing account health should block readiness visibly: {missing_account_health_readiness}")
    if missing_account_health_readiness.get("traffic_light_report", {}).get("red_count", 0) < 1:
        return fail(f"missing account health should count as a red publish-health item: {missing_account_health_readiness}")

    frozen_account_payload = deepcopy(request.payload)
    frozen_account_payload["account_health"] = {
        "status": "frozen",
        "selling_status": "restricted",
        "payout_status": "hold",
        "restrictions": ["payout hold", "seller account frozen"],
    }
    frozen_account_preflight = ExecutionService(demo_mode=False).preflight(
        ExecutionRequest(
            action_type="publish_listing",
            task_id="task_publish_test",
            user_id="user_test",
            company_id="company_test",
            store_id="store_test",
            platform="ebay",
            confirmation_id="confirm_publish_test",
            confirmed_by="user_test",
            confirmed_at="2026-05-22T00:00:00+00:00",
            idempotency_key="publish-test-001-frozen-account",
            payload=frozen_account_payload,
        )
    )
    frozen_account_readiness = build_publish_readiness(frozen_account_payload, preflight=frozen_account_preflight)
    account_health_check = next((item for item in frozen_account_readiness.get("checks", []) if item.get("key") == "account_health_gate"), {})
    if not account_health_check.get("blocking") or account_health_check.get("details", {}).get("incident_mode") is not True:
        return fail(f"frozen account should trigger incident-mode readiness block: {frozen_account_readiness}")
    if frozen_account_readiness.get("traffic_light_report", {}).get("decision") != "red_blocked":
        return fail(f"frozen account should produce a red traffic-light report: {frozen_account_readiness}")

    incomplete_payload = deepcopy(request.payload)
    incomplete_payload["listing"].pop("merchant_location_key")
    incomplete_payload["business_policies"].pop("return_policy_id")
    incomplete_payload["asset_manifest"]["assets"] = []
    incomplete_preflight_request = ExecutionRequest(
        action_type="publish_listing",
        task_id="task_publish_test",
        user_id="user_test",
        company_id="company_test",
        store_id="store_test",
        platform="ebay",
        confirmation_id="confirm_publish_test",
        confirmed_by="user_test",
        confirmed_at="2026-05-22T00:00:00+00:00",
        idempotency_key="publish-test-001-incomplete",
        payload=incomplete_payload,
    )
    incomplete_preflight = ExecutionService(demo_mode=False).preflight(incomplete_preflight_request)
    incomplete_readiness = build_publish_readiness(incomplete_payload, preflight=incomplete_preflight)
    blocked_keys = {item.get("key") for item in incomplete_readiness.get("checks", []) if item.get("blocking")}
    if not {"field_completeness", "business_policies", "inventory_location", "asset_reachability"} <= blocked_keys:
        return fail(f"incomplete payload should expose merchant-visible blockers: {incomplete_readiness}")
    incomplete_traffic = incomplete_readiness.get("traffic_light_report", {})
    if incomplete_traffic.get("decision") != "red_blocked" or incomplete_traffic.get("red_count", 0) < 4:
        return fail(f"incomplete payload should produce a red traffic-light report with blocker count: {incomplete_readiness}")

    unsafe_payload = deepcopy(request.payload)
    unsafe_payload["listing"]["item_specifics"] = {"Brand": "Unbranded"}
    unsafe_payload["listing"]["title"] = "Apple compatible replica bumper"
    unsafe_payload["finance_review"] = {}
    unsafe_readiness = build_publish_readiness(unsafe_payload, preflight=preflight)
    unsafe_blocked = {item.get("key") for item in unsafe_readiness.get("checks", []) if item.get("blocking")}
    if not {"item_specifics_quality", "ip_vero_and_claims", "profit_and_fee_sanity"} <= unsafe_blocked:
        return fail(f"unsafe payload should block IP/item specifics/profit gaps: {unsafe_readiness}")

    recovery_payload = _apply_publish_recovery_execution_context(
        payload={"listing": {"sku": "STALE-REPORT-SKU"}},
        confirmation_id="confirm_publish_test",
        execution_results=[
            {
                "execution_id": "exec_published",
                "confirmation_id": "confirm_publish_test",
                "result": {"platform_result": {"sku": "REAL-PUBLISHED-SKU", "listing_id": "listing_123", "offer_id": "offer_123"}},
            }
        ],
    )
    if recovery_payload.get("listing", {}).get("sku") != "REAL-PUBLISHED-SKU":
        return fail(f"publish recovery must prefer persisted platform_result SKU over stale reports: {recovery_payload}")

    mismatched_category_payload = deepcopy(request.payload)
    mismatched_category_payload["listing"]["category_leaf"] = "Bass Guitars"
    mismatched_category_request = ExecutionRequest(
        action_type="publish_listing",
        task_id="task_publish_test",
        user_id="user_test",
        company_id="company_test",
        store_id="store_test",
        platform="ebay",
        confirmation_id="confirm_publish_test",
        confirmed_by="user_test",
        confirmed_at="2026-05-22T00:00:00+00:00",
        idempotency_key="publish-test-001-category-mismatch",
        payload=mismatched_category_payload,
    )
    mismatched_preflight = ExecutionService(demo_mode=False).preflight(mismatched_category_request)
    if mismatched_preflight.get("status") != "blocked_missing_execution_facts":
        return fail(f"mismatched eBay category should block publish preflight: {mismatched_preflight}")
    mismatch_issue_keys = {item.get("key") for item in mismatched_preflight.get("issues", []) if isinstance(item, dict)}
    if "listing.category_id" not in mismatch_issue_keys:
        return fail(f"mismatched category should report listing.category_id: {mismatched_preflight}")

    calls: list[tuple[str, str, dict]] = []

    def transport(http_request: Request, timeout: float) -> tuple[int, dict[str, str], bytes]:
        body = {}
        if getattr(http_request, "data", None):
            try:
                body = json.loads((http_request.data or b"{}").decode("utf-8"))
            except json.JSONDecodeError:
                body = {}
        calls.append((http_request.get_method(), http_request.full_url, body))
        if http_request.full_url.startswith("https://vault.test/"):
            return 200, {"content-type": "application/json"}, json.dumps({"data": {"data": {"refresh_token": "TEST_REFRESH_TOKEN"}}}).encode("utf-8")
        if http_request.full_url.endswith("/identity/v1/oauth2/token"):
            return 200, {"content-type": "application/json"}, json.dumps({"access_token": "TEST_ACCESS_TOKEN", "expires_in": 7200}).encode("utf-8")
        if "/inventory_item/" in http_request.full_url:
            return 204, {"content-type": "application/json"}, b""
        if http_request.full_url.endswith("/offer"):
            return 201, {"content-type": "application/json"}, json.dumps({"offerId": "offer_123"}).encode("utf-8")
        if http_request.full_url.endswith("/publish"):
            return 200, {"content-type": "application/json"}, json.dumps({"listingId": "listing_123"}).encode("utf-8")
        return 500, {"content-type": "application/json"}, b"{}"

    unsafe_direct_payload = deepcopy(request.payload)
    unsafe_direct_payload["listing"]["title"] = "Foldable iPad Stand"
    unsafe_direct_request = ExecutionRequest(
        action_type="publish_listing",
        task_id="task_publish_unsafe_compatibility",
        user_id="user_test",
        company_id="company_test",
        store_id="store_test",
        platform="ebay",
        confirmation_id="confirm_publish_unsafe_compatibility",
        confirmed_by="user_test",
        confirmed_at="2026-05-22T00:00:00+00:00",
        idempotency_key="publish-test-unsafe-compatibility",
        payload=unsafe_direct_payload,
    )
    unsafe_direct_result = EbayWriteHttpAdapter(settings, transport=transport).publish_listing(
        request=unsafe_direct_request,
        preflight=preflight,
        connections=[
            {
                "platform": "ebay",
                "connection_type": "oauth",
                "status": "publish_authorized",
                "scopes": ["https://api.ebay.com/oauth/api_scope/sell.inventory"],
                "secret_ref": "secret_ref_publish",
            }
        ],
        secret_refs=[{"provider": "ebay", "purpose": "ebay_refresh_token", "secret_ref": "secret_ref_publish"}],
        marketplace_id="EBAY_US",
    )
    if unsafe_direct_result.get("status") != "buyer_copy_fact_boundary_blocked" or calls:
        return fail(f"publish adapter must block unverified compatibility before token or eBay HTTP: {unsafe_direct_result}, calls={calls}")

    unsafe_draft_request = ExecutionRequest(
        action_type="save_ebay_listing_draft",
        task_id="task_draft_unsafe_compatibility",
        user_id="user_test",
        company_id="company_test",
        store_id="store_test",
        platform="ebay",
        confirmation_id="confirm_draft_unsafe_compatibility",
        confirmed_by="user_test",
        confirmed_at="2026-05-22T00:00:00+00:00",
        idempotency_key="draft-test-unsafe-compatibility",
        payload=unsafe_direct_payload,
    )
    unsafe_draft_result = EbayWriteHttpAdapter(settings, transport=transport).prepare_listing_draft(
        request=unsafe_draft_request,
        preflight=preflight,
        credential_boundary={},
        marketplace_id="EBAY_US",
    )
    if unsafe_draft_result.get("status") != "buyer_copy_fact_boundary_blocked" or calls:
        return fail(f"draft adapter must block unverified compatibility before credential or eBay HTTP: {unsafe_draft_result}, calls={calls}")

    result = EbayWriteHttpAdapter(settings, transport=transport).publish_listing(
        request=request,
        preflight=preflight,
        connections=[
            {
                "platform": "ebay",
                "connection_type": "oauth",
                "status": "publish_authorized",
                "scopes": ["https://api.ebay.com/oauth/api_scope/sell.inventory"],
                "secret_ref": "secret_ref_publish",
            }
        ],
        secret_refs=[{"provider": "ebay", "purpose": "ebay_refresh_token", "secret_ref": "secret_ref_publish"}],
        marketplace_id="EBAY_US",
    )
    if result.get("status") != "published_to_ebay":
        return fail(f"publish adapter should return published_to_ebay: {result}")
    if result.get("platform_result", {}).get("listing_id") != "listing_123":
        return fail("publish adapter should expose sanitized listing_id")
    ebay_calls = [item for item in calls if item[1].startswith("https://api.ebay.com/sell/inventory/")]
    if len(ebay_calls) != 3:
        return fail(f"publish adapter should call inventory item, offer, publish exactly once: {calls}")
    inventory_description = ebay_calls[0][2].get("product", {}).get("description")
    if "<p>" in str(inventory_description) or "</p>" in str(inventory_description):
        return fail(f"inventory item product description should be plain text: {inventory_description}")
    if ebay_calls[1][2].get("listingDescription") != request.payload["listing"]["description_html"]:
        return fail("offer listingDescription should keep the merchant-facing HTML")

    error_calls: list[tuple[str, str, dict]] = []

    def publish_limit_transport(http_request: Request, timeout: float) -> tuple[int, dict[str, str], bytes]:
        body = {}
        if getattr(http_request, "data", None):
            try:
                body = json.loads((http_request.data or b"{}").decode("utf-8") or "{}")
            except json.JSONDecodeError:
                body = {}
        error_calls.append((http_request.get_method(), http_request.full_url, body))
        if http_request.full_url.startswith("https://vault.test/"):
            return 200, {"content-type": "application/json"}, json.dumps({"data": {"data": {"refresh_token": "TEST_REFRESH_TOKEN"}}}).encode("utf-8")
        if http_request.full_url.endswith("/identity/v1/oauth2/token"):
            return 200, {"content-type": "application/json"}, json.dumps({"access_token": "TEST_ACCESS_TOKEN", "expires_in": 7200}).encode("utf-8")
        if "/inventory_item/" in http_request.full_url:
            return 204, {"content-type": "application/json"}, b""
        if http_request.full_url.endswith("/offer"):
            return 201, {"content-type": "application/json"}, json.dumps({"offerId": "offer_limit"}).encode("utf-8")
        if http_request.full_url.endswith("/publish"):
            return (
                400,
                {"content-type": "application/json"},
                json.dumps(
                    {
                        "errors": [
                            {
                                "errorId": 25002,
                                "domain": "API_INVENTORY",
                                "category": "Request",
                                "message": "This listing would cause you to exceed the amount you can list.",
                                "parameters": [{"name": "RemainingAmount", "value": "<b>HKD 1741.33</b>"}],
                            }
                        ]
                    }
                ).encode("utf-8"),
            )
        return 500, {"content-type": "application/json"}, b"{}"

    limit_result = EbayWriteHttpAdapter(settings, transport=publish_limit_transport).publish_listing(
        request=request,
        preflight=preflight,
        connections=[
            {
                "platform": "ebay",
                "connection_type": "oauth",
                "status": "publish_authorized",
                "scopes": ["https://api.ebay.com/oauth/api_scope/sell.inventory"],
                "secret_ref": "secret_ref_publish",
            }
        ],
        secret_refs=[{"provider": "ebay", "purpose": "ebay_refresh_token", "secret_ref": "secret_ref_publish"}],
        marketplace_id="EBAY_US",
    )
    last_step = limit_result.get("steps", [{}])[-1]
    if limit_result.get("status") != "blocked_platform_error" or last_step.get("platform_error", {}).get("error_id") != 25002:
        return fail(f"publish adapter should retain sanitized platform error summaries: {limit_result}")
    if last_step.get("platform_error", {}).get("code") != "seller_listing_limit":
        return fail(f"seller listing limit should be classified: {limit_result}")
    if "<b>" in json.dumps(last_step.get("platform_error", {}), ensure_ascii=False):
        return fail(f"platform error parameters should be sanitized: {limit_result}")
    limit_readiness = build_publish_readiness(
        request.payload,
        preflight=preflight,
        latest_execution_results=[
            {
                "result": {
                    "platform_result": {"sku": request.payload["listing"]["sku"]},
                    "steps": limit_result.get("steps", []),
                }
            }
        ],
    )
    if limit_readiness.get("status") != "blocked_missing_facts":
        return fail(f"recent seller limit error should block readiness until merchant adjusts price or quantity: {limit_readiness}")
    knowledge = limit_readiness.get("failure_knowledge_base", {})
    if knowledge.get("status") != "rule_candidate_from_latest_platform_error":
        return fail(f"seller limit error should become failure knowledge candidate: {limit_readiness}")
    rule_keys = {item.get("rule_key") for item in knowledge.get("rule_candidates", []) if isinstance(item, dict)}
    if "ebay_seller_listing_limit" not in rule_keys:
        return fail(f"seller limit should be persisted as next preflight rule candidate: {limit_readiness}")

    missing_specific_readiness = build_publish_readiness(
        request.payload,
        preflight=preflight,
        latest_execution_results=[
            {
                "result": {
                    "steps": [
                        {
                            "step": "publish_offer",
                            "path": "/sell/inventory/v1/offer/OLD-OFFER/publish",
                            "platform_error": {
                                "error_id": 25002,
                                "code": "missing_item_specific",
                                "message": "The item specific Item Height is missing.",
                            },
                        }
                    ],
                }
            }
        ],
    )
    if missing_specific_readiness.get("status") != "ready_for_execution":
        return fail(f"missing item-specific errors from another SKU must not block this SKU as a seller limit: {missing_specific_readiness}")

    same_sku_missing_specific_readiness = build_publish_readiness(
        request.payload,
        preflight=preflight,
        latest_execution_results=[
            {
                "result": {
                    "steps": [
                        {
                            "step": "publish_offer",
                            "path": f"/sell/inventory/v1/inventory_item/{request.payload['listing']['sku']}",
                            "platform_error": {
                                "error_id": 25002,
                                "code": "missing_item_specific",
                                "message": "The item specific Item Height is missing.",
                            },
                        }
                    ],
                }
            }
        ],
    )
    if same_sku_missing_specific_readiness.get("status") != "ready_for_execution":
        return fail(f"missing item-specific errors should not be classified as seller listing limits: {same_sku_missing_specific_readiness}")

    repo = SaaSRepository(OUT / "execution-datetime.sqlite", database_engine="sqlite")
    account = repo.create_user_with_company(email=f"datetime-{int(time.time())}@example.com", password="Password123!", company_name="Datetime Test")
    user = account["user"]
    store = repo.create_store(
        company_id=user["default_company_id"],
        user_id=user["user_id"],
        payload={"platform": "ebay", "store_name": "datetime store", "marketplace": "EBAY_US"},
    )
    task = repo.create_task(
        company_id=user["default_company_id"],
        store_id=store["store_id"],
        user_id=user["user_id"],
        task_type="product.workflow",
        title="Datetime execution result",
        input_data={"product": "Backflow incense burner"},
    )
    repo.save_runtime_outputs(
        task=task,
        runtime_result={
            "run": {"run_id": "run_datetime"},
            "confirmations": [
                {
                    "confirmation_id": "confirm_datetime_publish",
                    "action_type": "publish_listing",
                    "title": "Confirm publish",
                    "default_action": "hold",
                }
            ],
        },
    )
    confirmations = repo.list_confirmations(company_id=user["default_company_id"], limit=1)
    confirmation_id = confirmations[0]["confirmation_id"]
    confirmation = repo.decide_confirmation(
        company_id=user["default_company_id"],
        confirmation_id=confirmation_id,
        decision="approve",
        decided_by=user["user_id"],
        note="unit datetime",
    )
    stored_execution = repo.save_execution_result(
        confirmation=confirmation,
        result={
            "status": "published_to_ebay",
            "created_at": datetime.now(timezone.utc),
            "audit": {
                "confirmed_at": datetime.now(timezone.utc),
                "real_execution": {"published_to_ebay": True},
            },
        },
    )
    if stored_execution.get("status") != "published_to_ebay":
        return fail(f"execution result with datetime should be persisted: {stored_execution}")

    recovery_calls: list[tuple[str, str, dict]] = []

    def recovery_transport(http_request: Request, timeout: float) -> tuple[int, dict[str, str], bytes]:
        body = {}
        if getattr(http_request, "data", None):
            try:
                body = json.loads((http_request.data or b"{}").decode("utf-8") or "{}")
            except json.JSONDecodeError:
                body = {}
        recovery_calls.append((http_request.get_method(), http_request.full_url, body))
        if http_request.full_url.startswith("https://vault.test/"):
            return 200, {"content-type": "application/json"}, json.dumps({"data": {"data": {"refresh_token": "TEST_REFRESH_TOKEN"}}}).encode("utf-8")
        if http_request.full_url.endswith("/identity/v1/oauth2/token"):
            return 200, {"content-type": "application/json"}, json.dumps({"access_token": "TEST_ACCESS_TOKEN", "expires_in": 7200}).encode("utf-8")
        if "/inventory_item/" in http_request.full_url:
            return 200, {"content-type": "application/json"}, json.dumps({"sku": request.payload["listing"]["sku"]}).encode("utf-8")
        if "/offer?sku=" in http_request.full_url:
            return (
                200,
                {"content-type": "application/json"},
                json.dumps({"offers": [{"offerId": "offer_123", "listingId": "listing_123", "listingStatus": "PUBLISHED"}]}).encode("utf-8"),
            )
        return 500, {"content-type": "application/json"}, b"{}"

    recovery = EbayWriteHttpAdapter(settings, transport=recovery_transport).inspect_publish_state(
        request=request,
        connections=[
            {
                "platform": "ebay",
                "connection_type": "oauth",
                "status": "publish_authorized",
                "scopes": ["https://api.ebay.com/oauth/api_scope/sell.inventory"],
                "secret_ref": "secret_ref_publish",
            }
        ],
        secret_refs=[{"provider": "ebay", "purpose": "ebay_refresh_token", "secret_ref": "secret_ref_publish"}],
        marketplace_id="EBAY_US",
    )
    if recovery.get("status") != "publish_state_checked" or recovery.get("safe_to_retry_publish") is not False:
        return fail(f"publish recovery should block blind retries when eBay already has state: {recovery}")
    if recovery.get("recommended_action") != "backfill_execution_record":
        return fail(f"published offer recovery should recommend SaaS backfill: {recovery}")
    if recovery.get("cleanup_plan", {}).get("confirmation_required") is not True:
        return fail(f"cleanup plan must require merchant confirmation: {recovery}")
    if any(call[0] != "GET" for call in recovery_calls if call[1].startswith("https://api.ebay.com/sell/inventory/")):
        return fail(f"publish recovery must be read-only: {recovery_calls}")

    blocked = EbayWriteHttpAdapter(settings, transport=transport).publish_listing(
        request=request,
        preflight=preflight,
        connections=[{"platform": "ebay", "connection_type": "oauth", "status": "read_only_authorized", "scopes": []}],
        secret_refs=[],
        marketplace_id="EBAY_US",
    )
    if blocked.get("status") != "ebay_publish_scope_missing":
        return fail(f"missing write scope must block before HTTP write: {blocked}")
    print("PASS jiejing_ebay_write_adapter")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
