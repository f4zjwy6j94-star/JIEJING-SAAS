#!/usr/bin/env python3
"""Generate a project-scoped Listing draft without allowing model-owned facts."""

from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.listing_draft_generation import ListingDraftGenerationError, generate_listing_draft
from jiejing_saas.repository import SaaSRepository


class FakeLiveModelClient:
    name = "fake-live-listing-model"
    version = "1.0"
    model = "fake-listing-pro"

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def generate_text(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return {
            "text": json.dumps(
                {
                    "title": "AI Generated Zen Lotus Hand Incense Burner Home Decor",
                    "selling_points": [
                        "Decorative lotus and hand silhouette",
                        "Backflow smoke display for a calm room setting",
                        "Resin construction",
                        "Measures 16.2 x 7.7 x 17.9 cm",
                        "Designed for indoor display",
                    ],
                    "description": "A decorative backflow incense burner for indoor display.",
                    "category_id": "999999",
                    "category_suggestion": "Incense Holders",
                    "condition": "USED",
                    "quantity": "999",
                    "item_specifics": {
                        "Material": "Plastic",
                        "Brand": "ImaginaryBrand",
                        "Type": "Backflow Incense Burner",
                    },
                    "fulfillment_policy_id": "wrong-fulfillment",
                    "payment_policy_id": "wrong-payment",
                    "return_policy_id": "wrong-return",
                },
                ensure_ascii=False,
            ),
            "model_mode": "fake_live_model_text",
            "model_client": self.name,
            "model_configured": True,
            "model": self.model,
            "_usage": {"input_tokens": 240, "output_tokens": 160, "total_tokens": 400},
        }


def complete_packet() -> dict[str, Any]:
    return {
        "contract_version": "merchant_product_fact_packet_v1",
        "merchant_confirmed_facts": {
            "product_name": "Zen Lotus Hand Backflow Incense Burner",
            "source_url": "https://supplier.example.invalid/products/zen-lotus-burner",
            "sku": "JJ-ZEN-LOTUS-001",
            "condition": "NEW",
            "material": "Resin",
            "product_dimensions_cm": "16.2 x 7.7 x 17.9",
            "product_origin": "Dehua, Fujian, China",
            "package_weight_g": "451",
            "package_length_cm": "18",
            "package_width_cm": "10",
            "package_height_cm": "21",
            "unit_cost": "36",
            "currency": "CNY",
            "quantity": "3",
            "item_location": "Quanzhou, Fujian, China",
            "handling_time_days": "3",
            "image_urls": "https://assets.example.invalid/zen-lotus-main.jpg",
            "image_rights_confirmed": True,
        },
    }


def official_packet() -> dict[str, Any]:
    return {
        "platform": "ebay",
        "packet_type": "ebay_read_only_data_packet",
        "source_mode": "official_api",
        "source_label": "official_api",
        "status": "ready",
        "marketplace": "EBAY_US",
        "ready_for_runtime": True,
        "present_resource_keys": ["account_business_policies", "taxonomy_listing_metadata"],
        "missing_resource_keys": [],
        "sections": [
            {
                "key": "account_business_policies",
                "data": {
                    "fulfillment_policy_id": "fulfillment-official-1",
                    "payment_policy_id": "payment-official-1",
                    "return_policy_id": "return-official-1",
                    "policy_marketplace": "EBAY_US",
                },
            },
            {
                "key": "taxonomy_listing_metadata",
                "data": {
                    "marketplace_id": "EBAY_US",
                    "category_id": "20682",
                    "category_tree_id": "0",
                    "required_aspects": ["Brand", "Type", "Material"],
                },
            },
        ],
        "lineage": {"probe_live_read_performed": True},
        "secret_exposed": False,
    }


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="jiejing-listing-generation-", ignore_cleanup_errors=True) as temp_dir:
        db = Path(temp_dir) / "saas.sqlite"
        repository = SaaSRepository(db)
        account = repository.create_user_with_company(
            email="listing-generation@local.invalid",
            password="listing-generation-password",
            company_name="Listing Generation",
        )
        user = account["user"]
        company = account["company"]
        store = repository.create_store(
            company_id=company["company_id"],
            user_id=user["user_id"],
            payload={"platform": "ebay", "store_name": "Listing Store", "marketplace": "EBAY_US"},
        )
        fake = FakeLiveModelClient()

        blocked = generate_listing_draft(
            repository=repository,
            company_id=company["company_id"],
            store_id=store["store_id"],
            user_id=user["user_id"],
            listing_project_identity={"key": "listing-project-blocked"},
            merchant_product_fact_packet={
                "contract_version": "merchant_product_fact_packet_v1",
                "merchant_confirmed_facts": {"product_name": "Unverified Product"},
            },
            current_draft_fields={},
            model_client=fake,
            model_resolution={"provider_key": "fake", "model": fake.model, "merchant_pays_provider_directly": True},
        )
        if blocked.get("status") != "blocked":
            raise AssertionError(f"incomplete facts should block before model: {blocked}")
        if not {"condition", "material"}.issubset(set(blocked.get("missing_fields") or [])):
            raise AssertionError(f"blocked response missing concrete field gaps: {blocked}")
        if fake.calls:
            raise AssertionError("model was called for incomplete source facts")
        if repository.list_tasks(company_id=company["company_id"]):
            raise AssertionError("blocked preflight created a task")
        if repository.list_reports(company_id=company["company_id"]):
            raise AssertionError("blocked preflight created a report")

        packet_record = repository.create_platform_data_packet(
            company_id=company["company_id"],
            store_id=store["store_id"],
            user_id=user["user_id"],
            packet=official_packet(),
        )
        secret_sample = "frontend-credential-must-never-enter-listing-prompt"
        generated = generate_listing_draft(
            repository=repository,
            company_id=company["company_id"],
            store_id=store["store_id"],
            user_id=user["user_id"],
            listing_project_identity={"key": "listing-project-zen-lotus", "source_report_id": "report-source-1"},
            merchant_product_fact_packet=complete_packet(),
            current_draft_fields={
                "title": "Merchant Edited Lotus Backflow Incense Burner",
                "description": "Merchant-confirmed copy stays unchanged.",
                "merchant_edited_fields": ["title", "description"],
                "api_key": secret_sample,
            },
            model_client=fake,
            model_resolution={
                "provider_key": "fake",
                "model": fake.model,
                "mode": "merchant_byok",
                "merchant_pays_provider_directly": True,
                "secret_ref": "vault://must-not-enter-report",
            },
            packet_record=packet_record,
        )
        if generated.get("status") != "completed":
            raise AssertionError(f"complete facts did not generate Listing: {generated}")
        if len(fake.calls) != 1:
            raise AssertionError(f"expected one model call, got {len(fake.calls)}")
        prompt = json.dumps(fake.calls[0], ensure_ascii=False)
        if secret_sample in prompt or "vault://must-not-enter-report" in prompt:
            raise AssertionError("Listing model prompt included frontend or Vault secret material")
        for expected in ("Zen Lotus Hand Backflow Incense Burner", "Resin", "EBAY_US", "fulfillment-official-1"):
            if expected not in prompt:
                raise AssertionError(f"Listing prompt missed sanitized source context: {expected}")

        report = generated.get("report") or {}
        body = report.get("report") or {}
        fields = ((body.get("listing_handoff") or {}).get("listing_fields") or {})
        if report.get("report_type") != "listing.package" or body.get("version") != 1:
            raise AssertionError(f"Listing report/version was not persisted: {report}")
        if fields.get("title") != "Merchant Edited Lotus Backflow Incense Burner":
            raise AssertionError("merchant-edited title was silently overwritten")
        if fields.get("description_seed") != "Merchant-confirmed copy stays unchanged.":
            raise AssertionError("merchant-edited description was silently overwritten")
        inventory = fields.get("ebay_inventory_item_draft") or {}
        offer = fields.get("ebay_offer_draft") or {}
        policies = offer.get("listingPolicies") or {}
        if inventory.get("condition") != "NEW" or inventory.get("availability", {}).get("shipToLocationAvailability", {}).get("quantity") != 3:
            raise AssertionError(f"model overrode merchant condition or quantity: {inventory}")
        if inventory.get("product", {}).get("aspects", {}).get("Material") != ["Resin"]:
            raise AssertionError(f"model overrode merchant material: {inventory}")
        if offer.get("categoryId") != "20682":
            raise AssertionError(f"official taxonomy did not override model category: {offer}")
        if policies != {
            "fulfillmentPolicyId": "fulfillment-official-1",
            "paymentPolicyId": "payment-official-1",
            "returnPolicyId": "return-official-1",
        }:
            raise AssertionError(f"official business policies did not override model: {policies}")
        if generated.get("real_platform_writes_enabled") is not False or generated.get("model_usage", {}).get("total_tokens") != 400:
            raise AssertionError(f"Listing result lost safety or usage evidence: {generated}")

        stored = repository.list_reports(company_id=company["company_id"], limit=20)
        if len([item for item in stored if item.get("report_type") == "listing.package"]) != 1:
            raise AssertionError("Listing report was not saved exactly once")
        conn = sqlite3.connect(db)
        try:
            usage_count, total_tokens = conn.execute(
                "select count(*), coalesce(sum(total_tokens), 0) from model_usage_ledger"
            ).fetchone()
            execution_count = conn.execute("select count(*) from execution_results").fetchone()[0]
        finally:
            conn.close()
        if usage_count != 1 or total_tokens != 400:
            raise AssertionError(f"provider-reported usage was not persisted: {(usage_count, total_tokens)}")
        if execution_count != 0:
            raise AssertionError("Listing generation triggered a platform execution")

        # A failure while persisting failure audit must not erase a provider
        # request that already happened. The HTTP quota settlement uses this
        # structured error to decide whether to consume or release its slot.
        audit_failure_model = FakeLiveModelClient()
        with patch.object(repository, "update_task_status", side_effect=RuntimeError("audit store unavailable")):
            try:
                generate_listing_draft(
                    repository=repository,
                    company_id=company["company_id"],
                    store_id=store["store_id"],
                    user_id=user["user_id"],
                    listing_project_identity={"key": "listing-audit-failure-after-provider"},
                    merchant_product_fact_packet=complete_packet(),
                    current_draft_fields={},
                    model_client=audit_failure_model,
                    model_resolution={"provider_key": "fake", "model": fake.model, "mode": "platform_managed_default"},
                    packet_record=packet_record,
                )
            except ListingDraftGenerationError as exc:
                if not exc.model_called or not exc.usage_consumed or exc.model_usage.get("request_count") != 1:
                    raise AssertionError(f"audit failure lost the real provider request: {exc.model_usage}")
                if exc.model_usage.get("total_tokens") != 400 or not exc.task_id:
                    raise AssertionError("audit failure lost provider usage or the original task identity")
            else:
                raise AssertionError("an audit persistence failure must return a structured generation error")
        if len(audit_failure_model.calls) != 1:
            raise AssertionError("audit persistence failure caused duplicate provider requests")

    print("PASS jiejing_listing_draft_generation")


if __name__ == "__main__":
    main()
