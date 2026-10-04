#!/usr/bin/env python3
"""Regression checks for server-resolved publish source and rights evidence."""

from __future__ import annotations

import hashlib
import json
import sys
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_runtime import ExecutionRequest, ExecutionService  # noqa: E402
from jiejing_saas.ebay_write_adapter import EbayWriteHttpAdapter, build_publish_readiness  # noqa: E402


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def _request(*, action_type: str, payload: dict) -> ExecutionRequest:
    return ExecutionRequest(
        action_type=action_type,
        task_id="task_publish_evidence",
        user_id="user_publish_evidence",
        company_id="company_publish_evidence",
        store_id="store_publish_evidence",
        platform="ebay",
        confirmation_id="confirm_publish_evidence",
        confirmed_by="user_publish_evidence",
        confirmed_at="2026-08-31T00:00:00+00:00",
        idempotency_key=f"{action_type}-publish-evidence-1",
        payload=payload,
    )


def _complete_payload() -> dict:
    return {
        "listing_project_identity": {
            "key": "listing-project-publish-evidence",
            "source_report_id": "report_publish_evidence",
            "candidate_id": "candidate_publish_evidence",
        },
        "account_health": {"status": "clear"},
        "listing": {
            "sku": "JJ-EVIDENCE-001",
            "title": "Stainless Steel Coffee Scoop",
            "description_html": "<p>Merchant-verified coffee scoop.</p>",
            "category_id": "20637",
            "condition": "NEW",
            "price": {"value": "14.99", "currency": "USD"},
            "quantity": 1,
            "item_specifics": {"Brand": "Unbranded", "Type": "Coffee Scoop"},
            "merchant_location_key": "merchant-location",
        },
        "business_policies": {
            "fulfillment_policy_id": "fulfillment-policy",
            "payment_policy_id": "payment-policy",
            "return_policy_id": "return-policy",
        },
        "supplier_facts": {
            "package_weight_g": 120,
            "package_dimensions_cm": {"length": 18, "width": 5, "height": 3},
            "material": "Stainless steel",
            "item_location": "Shenzhen, China",
        },
        "asset_manifest": {
            "assets": [
                {"asset_id": "asset_1", "url": "https://example.test/coffee-scoop-1.jpg"},
                {"asset_id": "asset_2", "url": "https://example.test/coffee-scoop-2.jpg"},
            ]
        },
        "finance_review": {"net_profit_money": {"value": "3.50", "currency": "USD"}},
    }


def _publish_evidence(payload: dict, *, server_resolved: bool = True) -> dict:
    asset_rows = []
    for asset in payload["asset_manifest"]["assets"]:
        asset_rows.append(
            {
                "asset_id": asset["asset_id"],
                "url_sha256": hashlib.sha256(asset["url"].encode("utf-8")).hexdigest(),
                "evidence_type": "approved_media_asset_job",
                "evidence_id": "media_job_publish_evidence",
            }
        )
    evidence = {
        "contract_version": "2026-08-31-publish-source-rights-evidence-v1",
        "status": "ready",
        "server_resolved": server_resolved,
        "scope": {
            "company_id": "company_publish_evidence",
            "store_id": "store_publish_evidence",
            "listing_project_key": "listing-project-publish-evidence",
        },
        "refs": {
            "product_fact_report_id": "report_publish_evidence",
            "media_job_id": "media_job_publish_evidence",
        },
        "product_source": {
            "status": "verified",
            "source_mode": "merchant_source_supplied",
            "evidence_type": "merchant_product_fact_report",
            "evidence_id": "report_publish_evidence",
        },
        "image_rights": {
            "status": "verified",
            "required_asset_count": len(asset_rows),
            "covered_asset_count": len(asset_rows),
            "coverage_complete": True,
            "assets": asset_rows,
        },
        "resolved_at": "2026-08-31T00:00:00+00:00",
        "secret_exposed": False,
    }
    fingerprint_payload = {key: value for key, value in evidence.items() if key not in {"resolved_at", "fingerprint"}}
    evidence["fingerprint"] = hashlib.sha256(
        json.dumps(
            fingerprint_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return evidence


def _refingerprint(evidence: dict) -> None:
    fingerprint_payload = {key: value for key, value in evidence.items() if key not in {"resolved_at", "fingerprint"}}
    evidence["fingerprint"] = hashlib.sha256(
        json.dumps(
            fingerprint_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _set_path(mapping: dict, path: str, value: object) -> None:
    current = mapping
    parts = path.split(".")
    for part in parts[:-1]:
        current = current[part]
    current[parts[-1]] = value


def main() -> int:
    payload = _complete_payload()
    draft_preflight = ExecutionService(demo_mode=False).preflight(
        _request(action_type="save_ebay_listing_draft", payload=payload)
    )
    if draft_preflight.get("status") != "blocked_missing_execution_facts":
        return fail(f"draft save without server publish evidence must be blocked: {draft_preflight}")
    if "publish_evidence" not in set(draft_preflight.get("missing_fields") or []):
        return fail(f"draft save should name the missing publish evidence: {draft_preflight}")

    wrong_shape_payload = deepcopy(payload)
    wrong_shape_payload["publish_evidence"] = "browser-says-ready"
    wrong_shape_preflight = ExecutionService(demo_mode=False).preflight(
        _request(action_type="publish_listing", payload=wrong_shape_payload)
    )
    wrong_shape_issue_keys = {
        item.get("key") for item in wrong_shape_preflight.get("issues", []) if isinstance(item, dict)
    }
    if (
        wrong_shape_preflight.get("status") != "blocked_missing_execution_facts"
        or "publish_evidence" not in wrong_shape_issue_keys
    ):
        return fail(f"non-object publish evidence must fail strict validation: {wrong_shape_preflight}")

    browser_asserted_payload = deepcopy(payload)
    browser_asserted_payload["publish_evidence"] = _publish_evidence(browser_asserted_payload, server_resolved=False)
    browser_asserted_preflight = ExecutionService(demo_mode=False).preflight(
        _request(action_type="publish_listing", payload=browser_asserted_payload)
    )
    if browser_asserted_preflight.get("status") != "blocked_missing_execution_facts":
        return fail(f"browser-asserted publish evidence must be blocked: {browser_asserted_preflight}")
    browser_issue_keys = {
        item.get("key") for item in browser_asserted_preflight.get("issues", []) if isinstance(item, dict)
    }
    if "publish_evidence.server_resolved" not in browser_issue_keys:
        return fail(f"publish evidence should expose the server-resolution blocker: {browser_asserted_preflight}")

    cross_tenant_payload = deepcopy(payload)
    cross_tenant_payload["publish_evidence"] = _publish_evidence(cross_tenant_payload)
    cross_tenant_payload["publish_evidence"]["scope"]["company_id"] = "company_other"
    _refingerprint(cross_tenant_payload["publish_evidence"])
    cross_tenant_preflight = ExecutionService(demo_mode=False).preflight(
        _request(action_type="save_ebay_listing_draft", payload=cross_tenant_payload)
    )
    if cross_tenant_preflight.get("status") != "blocked_missing_execution_facts":
        return fail(f"cross-tenant publish evidence must be blocked: {cross_tenant_preflight}")
    cross_tenant_issue_keys = {
        item.get("key") for item in cross_tenant_preflight.get("issues", []) if isinstance(item, dict)
    }
    if "publish_evidence.scope.company_id" not in cross_tenant_issue_keys:
        return fail(f"cross-tenant evidence should expose company scope mismatch: {cross_tenant_preflight}")

    partial_coverage_payload = deepcopy(payload)
    partial_coverage_payload["publish_evidence"] = _publish_evidence(partial_coverage_payload)
    partial_coverage_payload["publish_evidence"]["image_rights"]["covered_asset_count"] = 1
    partial_coverage_payload["publish_evidence"]["image_rights"]["assets"] = partial_coverage_payload[
        "publish_evidence"
    ]["image_rights"]["assets"][:1]
    _refingerprint(partial_coverage_payload["publish_evidence"])
    partial_coverage_preflight = ExecutionService(demo_mode=False).preflight(
        _request(action_type="publish_listing", payload=partial_coverage_payload)
    )
    if partial_coverage_preflight.get("status") != "blocked_missing_execution_facts":
        return fail(f"partial image-rights coverage must be blocked: {partial_coverage_preflight}")
    partial_coverage_issue_keys = {
        item.get("key") for item in partial_coverage_preflight.get("issues", []) if isinstance(item, dict)
    }
    if "publish_evidence.image_rights.coverage" not in partial_coverage_issue_keys:
        return fail(f"partial rights evidence should expose coverage mismatch: {partial_coverage_preflight}")

    valid_payload = deepcopy(payload)
    valid_payload["publish_evidence"] = _publish_evidence(valid_payload)
    for action_type in ("save_ebay_listing_draft", "publish_listing"):
        valid_preflight = ExecutionService(demo_mode=False).preflight(
            _request(action_type=action_type, payload=valid_payload)
        )
        if valid_preflight.get("status") != "ready_for_platform_adapter":
            return fail(f"valid server evidence should pass {action_type}: {valid_preflight}")

    legacy_price_payload = deepcopy(valid_payload)
    legacy_price_payload["listing"]["price"] = 14.99
    legacy_preflight = ExecutionService(demo_mode=False).preflight(
        _request(action_type="save_ebay_listing_draft", payload=legacy_price_payload)
    )
    if legacy_preflight.get("status") != "ready_for_platform_adapter":
        return fail("valid legacy scalar draft prices must remain supported")
    # The UI projection must support the same legacy values as execution,
    # rather than raising while reading a currency from a scalar.
    for legacy_price in (14.99, "14.99"):
        legacy_price_payload["listing"]["price"] = legacy_price
        legacy_readiness = build_publish_readiness(legacy_price_payload, preflight=legacy_preflight)
        legacy_finance = next(row for row in legacy_readiness["checks"] if row["key"] == "profit_and_fee_sanity")
        if legacy_finance["details"]["calculation_currency"] != "USD" or legacy_finance["details"]["unit_price"] != 14.99:
            return fail("legacy price readiness must use the normalized amount and currency")

    # A complete object is not necessarily a valid sale. Validate the same
    # values at the execution boundary, even when source/rights are verified.
    zero_price_payload = deepcopy(valid_payload)
    zero_price_payload["listing"]["price"]["value"] = "0"
    for action_type in ("save_ebay_listing_draft", "publish_listing"):
        reviewed = ExecutionService(demo_mode=False).preflight(
            _request(action_type=action_type, payload=zero_price_payload)
        )
        if reviewed.get("status") != "blocked_missing_execution_facts":
            return fail(f"zero selling price must block {action_type} before platform handoff")
        if "listing.price.value" not in {issue.get("key") for issue in reviewed.get("issues", [])}:
            return fail("invalid selling price must identify the actionable field")

    numeric_cases = [
        ("listing.price.value", "NaN"),
        ("listing.price.value", "Infinity"),
        ("listing.price.value", "-1"),
        ("listing.quantity", 1.5),
        ("listing.quantity", -1),
        ("listing.quantity", "Infinity"),
        ("supplier_facts.package_weight_g", 0),
        ("supplier_facts.package_weight_g", -10),
        ("supplier_facts.package_dimensions_cm.width", 0),
        ("supplier_facts.package_dimensions_cm.length", "NaN"),
    ]
    for path, value in numeric_cases:
        invalid_payload = deepcopy(valid_payload)
        _set_path(invalid_payload, path, value)
        for action_type in ("save_ebay_listing_draft", "publish_listing"):
            reviewed = ExecutionService(demo_mode=False).preflight(
                _request(action_type=action_type, payload=invalid_payload)
            )
            if reviewed.get("status") != "blocked_missing_execution_facts" or path not in {
                issue.get("key") for issue in reviewed.get("issues", [])
            }:
                return fail(f"invalid {path} must block {action_type} with a field-specific error")
        review = build_publish_readiness(invalid_payload, preflight=reviewed)
        group = "package_facts" if path.startswith("supplier_facts.") else "price_quantity_exposure"
        if not next(row for row in review["checks"] if row["key"] == group)["blocking"]:
            return fail(f"readiness must not display an invalid {path} as passed")
        if review["ready_for_platform_adapter"]:
            return fail("invalid numerical input must not be ready for a platform adapter")

    losing_payload = deepcopy(valid_payload)
    losing_payload["finance_review"] = {
        "procurement_cost_money": {"value": "2.50", "currency": "USD"},
        "shipping_cost_money": {"value": "25", "currency": "USD"},
        "ebay_fee_money": {"value": "2.07", "currency": "USD"},
        "ad_budget_money": {"value": "0", "currency": "USD"},
        "return_risk_reserve_money": {"value": "0.65", "currency": "USD"},
        "exchange_rate": "1",
        "net_profit_money": {"value": "5.57", "currency": "USD"},
    }
    reviewed = ExecutionService(demo_mode=False).preflight(
        _request(action_type="publish_listing", payload=losing_payload)
    )
    if reviewed.get("status") != "blocked_missing_execution_facts":
        return fail("a declared positive profit must not override a loss calculated from complete costs")
    review = build_publish_readiness(losing_payload, preflight=reviewed)
    finance_check = next(row for row in review["checks"] if row["key"] == "profit_and_fee_sanity")
    if not finance_check["blocking"] or finance_check["details"]["effective_profit"] >= 0:
        return fail("merchant readiness must display and block the calculated loss")

    # Missing optional estimates can require review, but a provided invalid
    # estimate must never be silently treated as a valid zero or a missing one.
    for key, value in (
        ("shipping_cost_money", {"value": "NaN", "currency": "USD"}),
        ("procurement_cost_money", {"value": "-1", "currency": "USD"}),
        ("ad_budget_money", {"value": "Infinity", "currency": "USD"}),
        ("ebay_fee_money", {"value": True, "currency": "USD"}),
        ("return_risk_reserve_money", {"value": "0.5", "currency": "CNY"}),
        ("exchange_rate", "0"),
        ("exchange_rate", "NaN"),
        ("net_profit_money", {"value": "NaN", "currency": "USD"}),
    ):
        invalid_payload = deepcopy(valid_payload)
        invalid_payload["finance_review"][key] = value
        reviewed = ExecutionService(demo_mode=False).preflight(
            _request(action_type="publish_listing", payload=invalid_payload)
        )
        if not any(issue.get("key", "").startswith(f"finance_review.{key}") for issue in reviewed["issues"]):
            return fail(f"invalid provided {key} must return a blocking finance issue")
        review = build_publish_readiness(invalid_payload, preflight=reviewed)
        if not next(row for row in review["checks"] if row["key"] == "profit_and_fee_sanity")["blocking"]:
            return fail(f"invalid provided {key} must also block merchant readiness")

    overflow_payload = deepcopy(valid_payload)
    overflow_payload["listing"]["price"]["value"] = "1e308"
    overflow_payload["listing"]["quantity"] = 10
    overflow_preflight = ExecutionService(demo_mode=False).preflight(
        _request(action_type="publish_listing", payload=overflow_payload)
    )
    if not any(issue.get("key") == "listing.price.exposure" for issue in overflow_preflight["issues"]):
        return fail("overflowing listing exposure must block before JSON or provider serialization")
    json.dumps(build_publish_readiness(overflow_payload, preflight=overflow_preflight), allow_nan=False)

    invalid_cases = [
        ("contract_version", "old-contract", "publish_evidence.contract_version", True),
        ("status", "pending", "publish_evidence.status", True),
        ("product_source.status", "merchant_asserted", "publish_evidence.product_source", True),
        ("product_source.source_mode", "model_inferred", "publish_evidence.product_source", True),
        ("image_rights.status", "merchant_asserted", "publish_evidence.image_rights.status", True),
        ("scope.store_id", "store_other", "publish_evidence.scope.store_id", True),
        ("scope.listing_project_key", "listing-project-other", "publish_evidence.scope.listing_project_key", True),
        ("secret_exposed", True, "publish_evidence.secret_exposed", True),
        ("image_rights.assets", [], "publish_evidence.image_rights.coverage", True),
        ("fingerprint", "0" * 64, "publish_evidence.fingerprint", False),
    ]
    for path, value, expected_issue, refresh_fingerprint in invalid_cases:
        invalid_payload = deepcopy(payload)
        invalid_payload["publish_evidence"] = _publish_evidence(invalid_payload)
        _set_path(invalid_payload["publish_evidence"], path, value)
        if refresh_fingerprint:
            _refingerprint(invalid_payload["publish_evidence"])
        invalid_preflight = ExecutionService(demo_mode=False).preflight(
            _request(action_type="publish_listing", payload=invalid_payload)
        )
        invalid_issue_keys = {
            item.get("key") for item in invalid_preflight.get("issues", []) if isinstance(item, dict)
        }
        if invalid_preflight.get("status") != "blocked_missing_execution_facts" or expected_issue not in invalid_issue_keys:
            return fail(f"invalid publish evidence {path} must block as {expected_issue}: {invalid_preflight}")

    readiness = build_publish_readiness(
        valid_payload,
        preflight=ExecutionService(demo_mode=False).preflight(
            _request(action_type="publish_listing", payload=valid_payload)
        ),
        expected_company_id="company_publish_evidence",
        expected_store_id="store_publish_evidence",
        expected_listing_project_key="listing-project-publish-evidence",
    )
    evidence_check = next(
        (item for item in readiness.get("checks", []) if item.get("key") == "publish_source_rights_evidence"),
        {},
    )
    if evidence_check.get("status") != "passed" or evidence_check.get("blocking") is not False:
        return fail(f"readiness should show valid source and rights evidence as passed: {readiness}")

    forged_readiness_payload = deepcopy(payload)
    forged_readiness_payload["publish_evidence"] = _publish_evidence(forged_readiness_payload, server_resolved=False)
    forged_readiness = build_publish_readiness(
        forged_readiness_payload,
        preflight={"status": "ready_for_platform_adapter", "missing_fields": [], "issues": []},
        expected_company_id="company_publish_evidence",
        expected_store_id="store_publish_evidence",
        expected_listing_project_key="listing-project-publish-evidence",
    )
    forged_check = next(
        (item for item in forged_readiness.get("checks", []) if item.get("key") == "publish_source_rights_evidence"),
        {},
    )
    if forged_readiness.get("status") != "blocked_missing_facts" or forged_check.get("blocking") is not True:
        return fail(f"readiness must independently block browser-asserted evidence: {forged_readiness}")
    forged_issue_keys = {
        item.get("key") for item in forged_check.get("details", {}).get("issues", []) if isinstance(item, dict)
    }
    if "publish_evidence.server_resolved" not in forged_issue_keys:
        return fail(f"readiness should expose the server-resolution evidence blocker: {forged_readiness}")

    adapter_calls: list[str] = []

    def forbidden_transport(*_args: object, **_kwargs: object) -> tuple[int, dict[str, str], bytes]:
        adapter_calls.append("called")
        return 500, {}, b"{}"

    adapter = EbayWriteHttpAdapter(
        SimpleNamespace(
            effective_real_platform_writes_enabled=True,
            effective_ebay_draft_save_enabled=True,
            effective_ebay_controlled_publish_enabled=True,
        ),
        transport=forbidden_transport,
    )
    forged_request = _request(action_type="publish_listing", payload=forged_readiness_payload)
    direct_publish = adapter.publish_listing(
        request=forged_request,
        preflight={"status": "ready_for_platform_adapter", "missing_fields": [], "issues": []},
        connections=[],
        secret_refs=[],
        marketplace_id="EBAY_US",
    )
    if direct_publish.get("status") != "publish_evidence_not_ready":
        return fail(f"adapter must not trust a forged ready preflight: {direct_publish}")
    draft_request = _request(action_type="save_ebay_listing_draft", payload=forged_readiness_payload)
    direct_draft = adapter.prepare_listing_draft(
        request=draft_request,
        preflight={"status": "ready_for_platform_adapter", "missing_fields": [], "issues": []},
        credential_boundary={},
        marketplace_id="EBAY_US",
    )
    if direct_draft.get("status") != "draft_publish_evidence_not_ready":
        return fail(f"draft adapter must not trust a forged ready preflight: {direct_draft}")
    if adapter_calls:
        return fail(f"invalid publish evidence must block before any provider HTTP call: {adapter_calls}")

    print("PASS jiejing_publish_evidence_preflight")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
