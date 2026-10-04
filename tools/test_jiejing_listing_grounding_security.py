#!/usr/bin/env python3
"""Listing buyer copy stays grounded in the sanitized merchant fact packet."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.listing_draft_generation import ListingDraftGenerationError, generate_listing_draft
from jiejing_saas.repository import SaaSRepository
from tools.listing_claim_review_fixture import review_response
from jiejing_saas.sensitive_text import contains_secret_like_data


class FixedListingModel:
    name = "fixed-listing-grounding-model"
    version = "1.0"
    model = "fixed-listing-grounding-pro"

    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.call_count = 0
        self.prompts: list[str] = []

    def generate_text(self, **kwargs: Any) -> dict[str, Any]:
        self.call_count += 1
        self.prompts.append(str(kwargs.get("user_prompt") or ""))
        review = review_response(kwargs, usage={"input_tokens": 100, "output_tokens": 80, "total_tokens": 180})
        if review is not None:
            return review
        return {
            "text": json.dumps(self.payload, ensure_ascii=False),
            "model_mode": "fixed_listing_grounding",
            "model_client": self.name,
            "model_configured": True,
            "model": self.model,
            "_usage": {"input_tokens": 100, "output_tokens": 80, "total_tokens": 180},
        }


def tablet_packet() -> dict[str, Any]:
    return {
        "contract_version": "merchant_product_fact_packet_v1",
        "secret_exposed": False,
        "input_tokens": 0,
        "merchant_confirmed_facts": {
            "product_name": "Foldable Tablet Stand",
            "condition": "NEW",
            "material": "Aluminum alloy with silicone pads",
            "product_dimensions_cm": "15 x 12 x 8",
            "net_weight_g": "220",
            "merchant_owned_product_confirmed": True,
        },
    }


def model_payload(*, extra_point: str, description: str) -> dict[str, Any]:
    return {
        "title": "Foldable Aluminum Tablet Stand",
        "selling_points": [
            "Foldable profile for compact storage",
            "Aluminum alloy construction",
            "Silicone contact pads",
            extra_point,
        ],
        "description": description,
        "category_suggestion": "Tablet and eBook Reader Stands",
        "keywords": ["tablet stand", "foldable stand"],
        "item_specifics": {"Type": "Tablet Stand"},
    }


def main() -> None:
    if contains_secret_like_data({"secret_exposed": False, "input_tokens": 0, "token_count": 0}):
        raise AssertionError("safe secret flags or token counters were misclassified as credentials")
    if not contains_secret_like_data({"material": "Aluminum " + "ghp_" + "U" * 30}):
        raise AssertionError("nested credential-shaped product text escaped the shared detector")
    if not contains_secret_like_data({"source_url": "https://supplier.invalid/item?token=" + "V" * 24}):
        raise AssertionError("token-like supplier URL escaped the shared detector")
    with tempfile.TemporaryDirectory(prefix="jiejing-listing-grounding-", ignore_cleanup_errors=True) as temp_dir:
        repository = SaaSRepository(Path(temp_dir) / "saas.sqlite")
        account = repository.create_user_with_company(
            email="listing-grounding@local.invalid",
            password="listing-grounding-password",
            company_name="Listing Grounding",
        )
        store = repository.create_store(
            company_id=account["company"]["company_id"],
            user_id=account["user"]["user_id"],
            payload={"platform": "ebay", "store_name": "Grounding Store", "marketplace": "EBAY_US"},
        )

        secret_shape = "ghp_" + "T" * 30
        sensitive_packet = tablet_packet()
        sensitive_packet["merchant_confirmed_facts"]["material"] = f"Aluminum alloy {secret_shape}"
        never_called_model = FixedListingModel(
            model_payload(
                extra_point="Measures 15 x 12 x 8 cm",
                description="A foldable aluminum alloy tablet stand measuring 15 x 12 x 8 cm.",
            )
        )
        sensitive_result = generate_listing_draft(
            repository=repository,
            company_id=account["company"]["company_id"],
            store_id=store["store_id"],
            user_id=account["user"]["user_id"],
            listing_project_identity={"key": "listing-project-sensitive-direct"},
            merchant_product_fact_packet=sensitive_packet,
            current_draft_fields={},
            model_client=never_called_model,
            model_resolution={"provider_key": "fake", "model": never_called_model.model},
        )
        if sensitive_result.get("failure_code") != "listing_product_fact_sensitive_text":
            raise AssertionError(f"direct Listing call did not fail closed on sensitive facts: {sensitive_result}")
        if never_called_model.call_count != 0 or sensitive_result.get("usage_consumed") is not False:
            raise AssertionError(f"sensitive facts reached the provider: {sensitive_result}")
        if secret_shape.casefold() in json.dumps(sensitive_result, ensure_ascii=False).casefold():
            raise AssertionError("direct sensitive-fact response echoed credential-shaped text")
        if repository.list_tasks(company_id=account["company"]["company_id"]):
            raise AssertionError("direct sensitive-fact preflight created an audit task")

        merchant_grounding_model = FixedListingModel(
            model_payload(
                extra_point="Measures 15 x 12 x 8 cm",
                description="A foldable aluminum alloy tablet stand measuring 15 x 12 x 8 cm.",
            )
        )
        merchant_grounding_result = generate_listing_draft(
            repository=repository,
            company_id=account["company"]["company_id"],
            store_id=store["store_id"],
            user_id=account["user"]["user_id"],
            listing_project_identity={"key": "listing-project-merchant-ungrounded-material"},
            merchant_product_fact_packet=tablet_packet(),
            current_draft_fields={
                "title": "Titanium Foldable Tablet Stand",
                "description": "A compact aluminum alloy tablet stand.",
                "selling_points": ["Foldable profile", "Aluminum alloy body", "Silicone contact pads"],
                "merchant_edited_fields": ["title", "description", "selling_points"],
            },
            model_client=merchant_grounding_model,
            model_resolution={"provider_key": "fake", "model": merchant_grounding_model.model},
        )
        if merchant_grounding_result.get("failure_code") != "listing_merchant_copy_ungrounded_material":
            raise AssertionError(f"merchant-invented material was not blocked precisely: {merchant_grounding_result}")
        if merchant_grounding_model.call_count != 0 or merchant_grounding_result.get("usage_consumed") is not False:
            raise AssertionError(f"merchant grounding preflight called the model: {merchant_grounding_result}")
        if repository.list_tasks(company_id=account["company"]["company_id"]):
            raise AssertionError("merchant grounding preflight created an audit task")

        titanium_model = FixedListingModel(
            model_payload(
                extra_point="Titanium reinforced frame",
                description="A foldable aluminum tablet stand with a titanium reinforced frame.",
            )
        )
        titanium_packet = tablet_packet()
        titanium_packet["merchant_confirmed_facts"]["source_url"] = "https://supplier.invalid/titanium-stand"
        try:
            generate_listing_draft(
                repository=repository,
                company_id=account["company"]["company_id"],
                store_id=store["store_id"],
                user_id=account["user"]["user_id"],
                listing_project_identity={"key": "listing-project-ungrounded-titanium"},
                merchant_product_fact_packet=titanium_packet,
                current_draft_fields={},
                model_client=titanium_model,
                model_resolution={"provider_key": "fake", "model": titanium_model.model},
            )
        except ListingDraftGenerationError as exc:
            if exc.failure_code != "listing_model_output_ungrounded_material":
                raise AssertionError(f"ungrounded material did not produce a precise failure: {exc.failure_code}")
            if exc.model_usage.get("request_count") != 2:
                raise AssertionError(f"grounding repair usage was not reported: {exc.model_usage}")
        else:
            raise AssertionError("model-invented titanium was persisted without a merchant fact")

        waterproof_model = FixedListingModel(
            model_payload(
                extra_point="Waterproof construction for everyday use",
                description="A foldable aluminum tablet stand with waterproof protection.",
            )
        )
        waterproof_packet = tablet_packet()
        waterproof_packet["merchant_confirmed_facts"]["source_url"] = "https://supplier.invalid/waterproof-stand"
        try:
            generate_listing_draft(
                repository=repository,
                company_id=account["company"]["company_id"],
                store_id=store["store_id"],
                user_id=account["user"]["user_id"],
                listing_project_identity={"key": "listing-project-ungrounded-waterproof"},
                merchant_product_fact_packet=waterproof_packet,
                current_draft_fields={},
                model_client=waterproof_model,
                model_resolution={"provider_key": "fake", "model": waterproof_model.model},
            )
        except ListingDraftGenerationError as exc:
            if exc.failure_code != "listing_model_output_ungrounded_performance_claim":
                raise AssertionError(f"ungrounded waterproof claim was not precise: {exc.failure_code}")
        else:
            raise AssertionError("model-invented waterproof claim was persisted without a merchant fact")

        warranty_model = FixedListingModel(
            model_payload(
                extra_point="Backed by a lifetime warranty",
                description="A foldable aluminum tablet stand with a lifetime warranty.",
            )
        )
        try:
            generate_listing_draft(
                repository=repository,
                company_id=account["company"]["company_id"],
                store_id=store["store_id"],
                user_id=account["user"]["user_id"],
                listing_project_identity={"key": "listing-project-ungrounded-warranty"},
                merchant_product_fact_packet=tablet_packet(),
                current_draft_fields={},
                model_client=warranty_model,
                model_resolution={"provider_key": "fake", "model": warranty_model.model},
            )
        except ListingDraftGenerationError as exc:
            if exc.failure_code != "listing_model_output_ungrounded_warranty":
                raise AssertionError(f"ungrounded warranty claim was not precise: {exc.failure_code}")
        else:
            raise AssertionError("model-invented lifetime warranty was persisted without a merchant fact")

        certification_model = FixedListingModel(
            model_payload(
                extra_point="CE certified construction",
                description="A CE certified foldable aluminum tablet stand.",
            )
        )
        try:
            generate_listing_draft(
                repository=repository,
                company_id=account["company"]["company_id"],
                store_id=store["store_id"],
                user_id=account["user"]["user_id"],
                listing_project_identity={"key": "listing-project-ungrounded-certification"},
                merchant_product_fact_packet=tablet_packet(),
                current_draft_fields={},
                model_client=certification_model,
                model_resolution={"provider_key": "fake", "model": certification_model.model},
            )
        except ListingDraftGenerationError as exc:
            if exc.failure_code != "listing_model_output_ungrounded_certification":
                raise AssertionError(f"ungrounded certification claim was not precise: {exc.failure_code}")
        else:
            raise AssertionError("model-invented certification was persisted without a merchant fact")

        numeric_model = FixedListingModel(
            model_payload(
                extra_point="Net weight is 500 g",
                description="A foldable aluminum tablet stand with a net weight of 500 g.",
            )
        )
        try:
            generate_listing_draft(
                repository=repository,
                company_id=account["company"]["company_id"],
                store_id=store["store_id"],
                user_id=account["user"]["user_id"],
                listing_project_identity={"key": "listing-project-ungrounded-weight"},
                merchant_product_fact_packet=tablet_packet(),
                current_draft_fields={},
                model_client=numeric_model,
                model_resolution={"provider_key": "fake", "model": numeric_model.model},
            )
        except ListingDraftGenerationError as exc:
            if exc.failure_code != "listing_model_output_ungrounded_numeric_spec":
                raise AssertionError(f"ungrounded numeric specification was not precise: {exc.failure_code}")
        else:
            raise AssertionError("model-invented 500 g specification was persisted without a merchant fact")

        unsafe_type_payload = model_payload(
            extra_point="Measures 15 x 12 x 8 cm",
            description="A foldable aluminum alloy tablet stand measuring 15 x 12 x 8 cm.",
        )
        unsafe_type_payload["item_specifics"] = {"Type": "Titanium Tablet Stand"}
        unsafe_type_model = FixedListingModel(unsafe_type_payload)
        try:
            generate_listing_draft(
                repository=repository,
                company_id=account["company"]["company_id"],
                store_id=store["store_id"],
                user_id=account["user"]["user_id"],
                listing_project_identity={"key": "listing-project-ungrounded-type-aspect"},
                merchant_product_fact_packet=tablet_packet(),
                current_draft_fields={},
                model_client=unsafe_type_model,
                model_resolution={"provider_key": "fake", "model": unsafe_type_model.model},
            )
        except ListingDraftGenerationError as exc:
            if exc.failure_code != "listing_model_output_ungrounded_material":
                raise AssertionError(f"ungrounded Type aspect was not blocked precisely: {exc.failure_code}")
        else:
            raise AssertionError("model-invented material persisted through the Type aspect")
        if repository.list_reports(company_id=account["company"]["company_id"]):
            raise AssertionError("ungrounded buyer copy created a Listing report")

        formal_packet = tablet_packet()
        formal_packet["derived_listing_suggestions"] = {
            "product_name": "Injected Suggested Product",
            "material": "Titanium",
        }
        prompt_scope_model = FixedListingModel(
            model_payload(
                extra_point="Measures 15 x 12 x 8 cm and weighs 220 g",
                description="A foldable aluminum alloy tablet stand measuring 15 x 12 x 8 cm and weighing 220 g.",
            )
        )
        generate_listing_draft(
            repository=repository,
            company_id=account["company"]["company_id"],
            store_id=store["store_id"],
            user_id=account["user"]["user_id"],
            listing_project_identity={"key": "listing-project-formal-prompt-scope"},
            merchant_product_fact_packet=formal_packet,
            current_draft_fields={},
            model_client=prompt_scope_model,
            model_resolution={"provider_key": "fake", "model": prompt_scope_model.model},
        )
        formal_prompt = " ".join(prompt_scope_model.prompts)
        if "derived_listing_suggestions" in formal_prompt or "Injected Suggested Product" in formal_prompt or "Titanium" in formal_prompt:
            raise AssertionError("formal Listing prompt exposed unconfirmed derived suggestions")

        grounded_model = FixedListingModel(
            model_payload(
                extra_point="Measures 15 x 12 x 8 cm and weighs 220 g",
                description=(
                    "A foldable aluminum alloy tablet stand with silicone pads. "
                    "It measures 15 x 12 x 8 cm and has a net weight of 220 g."
                ),
            )
        )
        grounded = generate_listing_draft(
            repository=repository,
            company_id=account["company"]["company_id"],
            store_id=store["store_id"],
            user_id=account["user"]["user_id"],
            listing_project_identity={"key": "listing-project-grounded-dimensions-weight"},
            merchant_product_fact_packet=tablet_packet(),
            current_draft_fields={},
            model_client=grounded_model,
            model_resolution={"provider_key": "fake", "model": grounded_model.model},
        )
        if grounded.get("status") != "completed" or grounded_model.call_count != 2:
            raise AssertionError(f"grounded dimensions and weight were not accepted: {grounded}")
        if len(repository.list_reports(company_id=account["company"]["company_id"])) != 2:
            raise AssertionError("grounded buyer copy did not create exactly two Listing reports")

    print("PASS jiejing_listing_grounding_security")


if __name__ == "__main__":
    main()
