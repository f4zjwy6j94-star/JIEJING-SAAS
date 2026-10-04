#!/usr/bin/env python3
"""Buyer-facing Listing copy must match the target marketplace and fact boundary."""

from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.listing_draft_generation import (
    ListingDraftGenerationError,
    _contains_unverified_compatibility,
    _safe_merchant_item_specifics,
    _validate_buyer_copy,
    generate_listing_draft,
)
from jiejing_saas.ebay_write_adapter import build_publish_readiness
from jiejing_saas.repository import SaaSRepository
from tools.listing_claim_review_fixture import review_response
from jiejing_saas.sensitive_text import contains_secret_like_text


class FakeListingModel:
    name = "fake-listing-quality-model"
    version = "1.0"
    model = "fake-listing-quality-pro"

    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.call_count = 0

    def generate_text(self, **kwargs: Any) -> dict[str, Any]:
        self.call_count += 1
        review = review_response(kwargs, usage={"input_tokens": 100, "output_tokens": 100, "total_tokens": 200})
        if review is not None:
            return review
        return {
            "text": json.dumps(self.payload, ensure_ascii=False),
            "model_mode": "fake_live_model_text",
            "model_client": self.name,
            "model_configured": True,
            "model": self.model,
            "_usage": {"input_tokens": 100, "output_tokens": 100, "total_tokens": 200},
        }


def tablet_packet() -> dict[str, Any]:
    return {
        "contract_version": "merchant_product_fact_packet_v1",
        "merchant_confirmed_facts": {
            "product_name": "平板电脑支架（折叠便携款）",
            "condition": "NEW",
            "material": "Aluminum alloy with silicone pads",
            "product_dimensions_cm": "15 x 12 x 8",
            "net_weight_g": "220",
            "package_weight_g": "280",
            "package_length_cm": "18",
            "package_width_cm": "14",
            "package_height_cm": "5",
            "selling_price": "16.99",
            "currency": "USD",
            "quantity": "30",
        },
    }


def check_grounded_measuring_set_capacities() -> None:
    """Exercise the same buyer-copy boundary used by model parsing and final merge."""
    def validate(description: str, source: str = "", **packet_extra: Any) -> None:
        packet = {
            "merchant_confirmed_facts": {
                "product_name": "Gold measuring cups and spoons, 8-piece set",
                "condition": "NEW", "material": "Metal with wooden handles",
                "included_items": source,
            },
            **packet_extra,
        }
        _validate_buyer_copy(
            title="Gold Measuring Cups and Spoons Set with Wooden Handles, 8 Piece",
            description=description,
            selling_points=["Four cups and four spoons", "Gold finish", "Wooden handles"],
            marketplace="EBAY_US", failure_prefix="listing_model_output",
            merchant_product_fact_packet=packet,
        )

    source = "4只量杯（250、125、80、60 mL）和4只量勺（15、5、2.5、1.25 mL）。不含展示架。"
    for description in (
        "Cups: 250, 125, 80 and 60 mL. Spoons: 15, 5, 2.5 and 1.25 mL.",
        "Four measuring cups: 250ml, 125ml, 80ml, 60ml.",
        "Includes a 0.25 litre cup and a 1.25 milliliter spoon.",
    ):
        validate(description, source)
    validate("Includes a 250 mL cup.", "量杯250毫升；量勺15毫升")
    validate("Includes a 0.25 L cup.", "Cup: 250 millilitres")

    blocked = [
        ("A 300 mL cup.", source, {}),
        ("Cups: 300, 125 and 60 mL.", source, {}),
        ("Cups: 300 / 125 / 60 mL.", source, {}),
        ("A 250 L cup.", source, {}),
        ("A -250 mL cup.", source, {}),
        ("A 1e250 mL cup.", source, {}),
        ("A 0 mL cup.", source, {}),
        ("A 1.3 mL spoon.", source, {}),
        ("A 250 mL cup.", "", {}),
        ("A 250 mL cup.", "8-piece set, SKU 250", {}),
        ("A 250 mL cup.", "杯子250ml，容量待确认", {}),
        ("A 250 mL cup.", "No 250 mL cup included", {}),
        ("A 250 mL cup.", "Cup capacity maybe 250 mL", {}),
        ("A 250 mL cup.", "不含250毫升杯", {}),
        ("A 250 mL cup.", "不是250毫升", {}),
        ("A 250 mL cup.", "可能250毫升", {}),
        ("A 250 mL cup.", "250 mL?", {}),
        ("A 250 mL cup.", "250毫升？", {}),
        ("A 1 mL spoon.", "Capacity: 1,250 mL", {}),
        ("A 250 mL cup.", "Cup 250 mL not confirmed", {}),
        ("A 250 mL cup.", "", {"derived_listing_suggestions": {"included_items": source}}),
        ("A 5 V powered cup.", source, {}),
        ("A 250 mAh cup.", source, {}),
        ("A 2 fl oz spoon.", source, {}),
    ]
    for description, facts, extra in blocked:
        try:
            validate(description, facts, **extra)
        except ValueError as exc:
            if str(exc) != "listing_model_output_ungrounded_numeric_spec":
                raise
        else:
            raise AssertionError(f"ungrounded capacity/other numeric spec escaped: {description!r}, {facts!r}")


def main() -> None:
    check_grounded_measuring_set_capacities()
    credential_shapes = (
        "ghp_" + "A" * 30,
        "AKIA" + "B" * 16,
        "AIza" + "C" * 35,
        "-----BEGIN " + "PRIVATE KEY-----",
        "v^1.1#i^1#" + "D" * 40,
    )
    if not all(contains_secret_like_text(value) for value in credential_shapes):
        raise AssertionError("shared Listing sensitive-text boundary missed a credential shape")
    for unsafe_claim in (
        "Universal tablet stand",
        "Fits your iPad",
        "Works seamlessly with iPad",
        "Holds phones and tablets from 4 to 13 inches",
        "Use with iPad Pro",
        "Made to hold iPad Pro",
        "13-inch tablet stand",
        "Supports screens up to 13 inches",
        "Holds tablets up to 13 inches",
        "Works perfectly and securely with iPad",
        "Fits perfectly on iPad Pro",
        "Universal stand for a tablet",
        "Compatible: iPad Pro",
        "Compatibility: iPad Pro",
        "iPad Pro ready design",
        "iPad-friendly design",
        "Pairs with iPad Pro",
        "Works on iPad Pro",
        "Accepts tablets up to 13 inches",
        "Cradles tablets securely",
        "Secures your phone",
        "Tailored to iPad Pro",
        "Built around iPad Pro",
        "Tablet compatibility",
        "Universal compatibility",
        "Wide compatibility",
        "Adjustable across screen sizes from 4 to 13 inches",
    ):
        if not _contains_unverified_compatibility(unsafe_claim):
            raise AssertionError(f"unverified compatibility wording escaped the buyer-copy boundary: {unsafe_claim}")
    for grounded_phrase in (
        "Works well with your decor",
        "Apple green finish",
        "An apple corer accessory",
        "For Apple green kitchens",
        "Works beautifully with Apple green decor",
        "Fits in a 10-inch drawer",
        "Works with a 12-inch shelf",
        "Supports a 12-inch shelf",
    ):
        if _contains_unverified_compatibility(grounded_phrase):
            raise AssertionError(f"compatibility boundary falsely blocked ordinary copy: {grounded_phrase}")
    safe_specifics = _safe_merchant_item_specifics(
        {
            "To Fit": "Tablet",
            "Supported Product": "Tablet",
            "Supported Device": "eReader",
            "Type": "Apple Corer",
            "Color": "Apple Green",
            "Style": "iPad Stand",
            "Size Type": "13-inch tablet stand",
            "Tablet Size": "13 inches",
            "Maximum Tablet Size": "13 inches",
            "Phone Size": "6 inches",
            "Fits": "iPad Pro",
            "Model Year": "2026",
            "Model Number": "TS-2026",
        }
    )
    if set(safe_specifics) != {"Type", "Color", "Model Year", "Model Number"}:
        raise AssertionError(f"unverified compatibility aspects escaped the item-specific boundary: {safe_specifics}")
    for non_english in (
        ("Base ajustable para escritorio", "A compact folding metal stand.", ["Folds for storage", "Stable desk base", "Lightweight design"]),
        ("Opvouwbare standaard voor tablet", "A compact folding metal stand.", ["Folds for storage", "Stable desk base", "Lightweight design"]),
        ("Regulowany stojak na tablet", "A compact folding metal stand.", ["Folds for storage", "Stable desk base", "Lightweight design"]),
        ("Soporte plegable de aluminio para tableta", "Soporte de escritorio con silicona.", ["Diseño plegable", "Construcción de aluminio", "Almacenamiento compacto"]),
        ("Складная подставка для планшета", "Алюминиевая настольная подставка.", ["Складная", "Компактная", "Силиконовые накладки"]),
        ("접이식 태블릿 스탠드", "알루미늄 데스크 스탠드입니다.", ["접이식", "알루미늄", "컴팩트 보관"]),
        ("Support pliable pour tablette", "Support léger pour bureau.", ["Pliable", "Rangement compact", "Conçu pour bureau"]),
        ("Faltbarer Tablet Halter", "Verstellbarer Halter für den Schreibtisch.", ["Faltbar", "Kompakt", "Silikonauflagen"]),
        ("Suporte dobrável para tablet", "Suporte de alumínio para mesa.", ["Dobrável", "Compacto", "Almofadas de silicone"]),
        ("Supporto pieghevole per tablet", "Supporto in alluminio da scrivania.", ["Pieghevole", "Compatto", "Base in silicone"]),
    ):
        try:
            _validate_buyer_copy(
                title=non_english[0],
                description=non_english[1],
                selling_points=non_english[2],
                marketplace="EBAY_US",
                failure_prefix="listing_model_output",
            )
        except ValueError as exc:
            if str(exc) != "listing_model_output_marketplace_language":
                raise
        else:
            raise AssertionError(f"non-English EBAY_US copy escaped the language boundary: {non_english}")
    _validate_buyer_copy(
        title="Adjustable Folding Base for Desk Use",
        description="A compact aluminum alloy stand with silicone pads for a stable desktop setup.",
        selling_points=["Folds for storage", "Stable desk base", "Lightweight design"],
        marketplace="EBAY_US",
        failure_prefix="listing_model_output",
    )

    direct_ipad_readiness = build_publish_readiness(
        {
            "listing": {
                "title": "Foldable iPad Stand",
                "description_html": "A compact desktop stand.",
                "item_specifics": {"Brand": "Unbranded", "Type": "Tablet Stand"},
            }
        },
        preflight={"status": "ready_for_platform_adapter"},
    )
    direct_ipad_boundary = next(
        (item for item in direct_ipad_readiness.get("checks", []) if item.get("key") == "buyer_copy_fact_boundary"),
        {},
    )
    if direct_ipad_boundary.get("blocking") is not True:
        raise AssertionError(f"direct publish intake escaped the iPad compatibility boundary: {direct_ipad_readiness}")
    direct_ipad_sources = {
        str(item.get("source_type") or "") for item in direct_ipad_boundary.get("source_records", [])
    }
    if not {"policy_screening", "merchant_input"} <= direct_ipad_sources:
        raise AssertionError(f"buyer-copy blocker lacks explainable source records: {direct_ipad_boundary}")
    if direct_ipad_boundary.get("fix_action", {}).get("target") != "product.listing_copy":
        raise AssertionError(f"buyer-copy blocker lacks a precise merchant fix target: {direct_ipad_boundary}")

    direct_size_readiness = build_publish_readiness(
        {
            "listing": {
                "title": "Adjustable 4-13 Inch Tablet Stand",
                "description_html": "A compact desktop stand.",
                "item_specifics": {"Brand": "Unbranded", "Type": "Tablet Stand"},
            }
        },
        preflight={"status": "ready_for_platform_adapter"},
    )
    direct_size_boundary = next(
        (item for item in direct_size_readiness.get("checks", []) if item.get("key") == "buyer_copy_fact_boundary"),
        {},
    )
    if direct_size_boundary.get("blocking") is not True:
        raise AssertionError(f"direct publish intake escaped the device-size compatibility boundary: {direct_size_readiness}")

    direct_size_aspect_readiness = build_publish_readiness(
        {
            "listing": {
                "title": "Foldable Tablet Stand",
                "description_html": "A compact desktop stand.",
                "item_specifics": {
                    "Brand": "Unbranded",
                    "Type": "Tablet Stand",
                    "Tablet Size": "4-13 in",
                },
            }
        },
        preflight={"status": "ready_for_platform_adapter"},
    )
    direct_size_aspect_boundary = next(
        (item for item in direct_size_aspect_readiness.get("checks", []) if item.get("key") == "buyer_copy_fact_boundary"),
        {},
    )
    if direct_size_aspect_boundary.get("blocking") is not True:
        raise AssertionError(f"direct publish intake escaped the compatibility aspect boundary: {direct_size_aspect_readiness}")

    direct_fits_aspect_readiness = build_publish_readiness(
        {
            "listing": {
                "title": "Foldable Tablet Stand",
                "description_html": "A compact desktop stand.",
                "item_specifics": {
                    "Brand": "Unbranded",
                    "Type": "Tablet Stand",
                    "Fits": "iPad Pro",
                },
            }
        },
        preflight={"status": "ready_for_platform_adapter"},
    )
    direct_fits_aspect_boundary = next(
        (item for item in direct_fits_aspect_readiness.get("checks", []) if item.get("key") == "buyer_copy_fact_boundary"),
        {},
    )
    if direct_fits_aspect_boundary.get("blocking") is not True:
        raise AssertionError(f"direct publish intake escaped the Fits compatibility aspect boundary: {direct_fits_aspect_readiness}")

    for ordinary_apple_title, ordinary_type in (
        ("Apple Green Folding Desk Stand", "Desk Stand"),
        ("Apple Corer Holder for Kitchen Counter", "Apple Corer Holder"),
        ("Apple-Shaped Fruit Corer Stand", "Fruit Corer Stand"),
    ):
        ordinary_readiness = build_publish_readiness(
            {
                "listing": {
                    "title": ordinary_apple_title,
                    "description_html": "A compact household organizer with a stable base.",
                    "item_specifics": {"Brand": "Unbranded", "Type": ordinary_type},
                }
            },
            preflight={"status": "ready_for_platform_adapter"},
        )
        ordinary_checks = {item.get("key"): item for item in ordinary_readiness.get("checks", [])}
        if ordinary_checks.get("buyer_copy_fact_boundary", {}).get("blocking") is True:
            raise AssertionError(f"ordinary Apple wording was misclassified as compatibility: {ordinary_readiness}")
        if ordinary_checks.get("ip_vero_and_claims", {}).get("blocking") is True:
            raise AssertionError(f"ordinary Apple fruit/color wording was misclassified as Apple IP: {ordinary_readiness}")

    apple_brand_readiness = build_publish_readiness(
        {
            "listing": {
                "title": "Apple Watch Band Organizer",
                "description_html": "A compact organizer for a desk.",
                "item_specifics": {"Brand": "Unbranded", "Type": "Band Organizer"},
            }
        },
        preflight={"status": "ready_for_platform_adapter"},
    )
    apple_brand_check = next(
        (item for item in apple_brand_readiness.get("checks", []) if item.get("key") == "ip_vero_and_claims"),
        {},
    )
    if apple_brand_check.get("blocking") is not True:
        raise AssertionError(f"real Apple brand wording escaped the IP boundary: {apple_brand_readiness}")

    with tempfile.TemporaryDirectory(prefix="jiejing-listing-copy-quality-", ignore_cleanup_errors=True) as temp_dir:
        db = Path(temp_dir) / "saas.sqlite"
        repository = SaaSRepository(db)
        account = repository.create_user_with_company(
            email="listing-copy-quality@local.invalid",
            password="listing-copy-quality-password",
            company_name="Listing Copy Quality",
        )
        store = repository.create_store(
            company_id=account["company"]["company_id"],
            user_id=account["user"]["user_id"],
            payload={"platform": "ebay", "store_name": "Listing Copy Store", "marketplace": "EBAY_US"},
        )
        simulation_model = FakeListingModel(
            {
                "title": "Foldable Aluminum Tablet Stand for Desk Use",
                "selling_points": [
                    "Foldable profile for compact storage",
                    "Aluminum alloy construction",
                    "Silicone contact pads",
                ],
                "description": "A foldable aluminum alloy tablet stand with silicone contact pads.",
                "category_suggestion": "Tablet & eBook Reader Stands",
                "keywords": ["tablet stand"],
                "item_specifics": {"Type": "Tablet Stand"},
            }
        )
        simulation = generate_listing_draft(
            repository=repository,
            company_id=account["company"]["company_id"],
            store_id=store["store_id"],
            user_id=account["user"]["user_id"],
            listing_project_identity={"key": "listing-project-tablet-simulation"},
            merchant_product_fact_packet={
                "simulation_only": True,
                "merchant_confirmed_facts": {},
                "derived_listing_suggestions": {
                    "product_name": "平板电脑支架（折叠便携款）",
                    "condition": "NEW",
                    "material": "Aluminum alloy with silicone pads",
                    "product_dimensions_cm": "15 x 12 x 8",
                    "net_weight_g": "220",
                    "quantity": "30",
                },
            },
            current_draft_fields={},
            model_client=simulation_model,
            model_resolution={"provider_key": "fake", "model": simulation_model.model},
        )
        simulation_fields = (
            (((simulation.get("report") or {}).get("report") or {}).get("listing_handoff") or {}).get("listing_fields")
            or {}
        )
        persisted_simulation_packet = simulation_fields.get("merchant_product_fact_packet") or {}
        if simulation_fields.get("simulation_only") is not True or simulation_fields.get("safe_local_only") is not True:
            raise AssertionError(f"simulation Listing lost its non-publish boundary: {simulation_fields}")
        if persisted_simulation_packet.get("merchant_confirmed_facts"):
            raise AssertionError(f"simulation suggestions were promoted to merchant facts: {persisted_simulation_packet}")
        if simulation_fields.get("listing_readiness", {}).get("ready_for_real_publish") is not False:
            raise AssertionError(f"simulation Listing claimed real publish readiness: {simulation_fields}")

        model = FakeListingModel(
            {
                "title": "Foldable Aluminum Tablet Stand Adjustable Desk Holder",
                "selling_points": [
                    "Foldable profile for compact storage",
                    "Aluminum alloy construction",
                    "Silicone pads help protect contact surfaces",
                    "Measures 15 x 12 x 8 cm",
                    "Net weight is approximately 220 g",
                ],
                "description": (
                    "A foldable tablet stand made from aluminum alloy with silicone pads. "
                    "The stand measures 15 x 12 x 8 cm and has a net weight of approximately 220 g."
                ),
                "category_suggestion": "Tablet & eBook Reader Stands",
                "keywords": ["tablet stand", "foldable stand", "desk holder"],
                "item_specifics": {
                    "Type": "Tablet Stand",
                    "Material": "Imaginary material",
                    "Compatible Brand": "Apple",
                    "Compatible Screen Size": "13 in",
                },
            }
        )
        secret_sample = "api_key=listing-secret-value-must-not-persist"
        generated = generate_listing_draft(
            repository=repository,
            company_id=account["company"]["company_id"],
            store_id=store["store_id"],
            user_id=account["user"]["user_id"],
            listing_project_identity={"key": "listing-project-tablet-quality"},
            merchant_product_fact_packet=tablet_packet(),
            current_draft_fields={
                "title": "平板电脑支架（折叠便携款）",
                "selling_points": ["Foldable design", "Aluminum construction", "Compact storage"],
                "description": "A stand compatible with most tablets and e-readers.",
                "keywords": secret_sample,
                "merchant_edited_fields": ["keywords"],
            },
            model_client=model,
            model_resolution={"provider_key": "fake", "model": model.model},
        )
        fields = (((generated.get("report") or {}).get("report") or {}).get("listing_handoff") or {}).get(
            "listing_fields"
        ) or {}
        if fields.get("title") != "Foldable Aluminum Tablet Stand Adjustable Desk Holder":
            raise AssertionError(f"imported product label suppressed marketplace-ready model title: {fields}")
        if len(fields.get("selling_points") or []) != 5:
            raise AssertionError(f"incomplete prior AI selling points suppressed corrected model output: {fields}")
        if "compatible with" in str(fields.get("description_seed") or "").lower():
            raise AssertionError(f"unverified prior AI claim suppressed corrected model output: {fields}")
        unsafe_aspects = {
            key
            for key in (fields.get("item_specifics") or {})
            if "compatible" in str(key).lower() or "screen size" in str(key).lower()
        }
        if unsafe_aspects:
            raise AssertionError(f"unverified compatibility aspects were persisted: {fields}")
        if secret_sample in json.dumps(
            repository.list_tasks(company_id=account["company"]["company_id"]),
            ensure_ascii=False,
        ):
            raise AssertionError("credential-shaped text in a legal Listing field was persisted in a task")

        short_points_model = FakeListingModel(
            {
                "title": "Foldable Aluminum Tablet Stand Adjustable Desk Holder",
                "selling_points": [
                    "Foldable profile for compact storage",
                    "Aluminum alloy construction",
                ],
                "description": "A foldable aluminum alloy tablet stand measuring 15 x 12 x 8 cm.",
                "category_suggestion": "Tablet & eBook Reader Stands",
                "keywords": ["tablet stand"],
                "item_specifics": {"Type": "Tablet Stand"},
            }
        )
        try:
            generate_listing_draft(
                repository=repository,
                company_id=account["company"]["company_id"],
                store_id=store["store_id"],
                user_id=account["user"]["user_id"],
                listing_project_identity={"key": "listing-project-tablet-short-points"},
                merchant_product_fact_packet=tablet_packet(),
                current_draft_fields={},
                model_client=short_points_model,
                model_resolution={"provider_key": "fake", "model": short_points_model.model},
            )
        except ListingDraftGenerationError as exc:
            if exc.failure_code != "listing_model_output_selling_points_count":
                raise
            if exc.model_usage.get("request_count") != 2 or exc.usage_consumed is not True:
                raise AssertionError(f"quality repair usage was not reported honestly: {exc.model_usage}")
        else:
            raise AssertionError("Listing model output with fewer than three selling points was persisted")

        excess_points_model = FakeListingModel(
            {
                "title": "Foldable Aluminum Tablet Stand Adjustable Desk Holder",
                "selling_points": [
                    "Foldable profile for compact storage",
                    "Aluminum alloy construction",
                    "Silicone contact pads",
                    "Measures 15 x 12 x 8 cm",
                    "Net weight is approximately 220 g",
                    "Designed for indoor desk use",
                ],
                "description": "A foldable aluminum alloy tablet stand measuring 15 x 12 x 8 cm.",
                "category_suggestion": "Tablet & eBook Reader Stands",
                "keywords": ["tablet stand"],
                "item_specifics": {"Type": "Tablet Stand"},
            }
        )
        try:
            generate_listing_draft(
                repository=repository,
                company_id=account["company"]["company_id"],
                store_id=store["store_id"],
                user_id=account["user"]["user_id"],
                listing_project_identity={"key": "listing-project-tablet-excess-points"},
                merchant_product_fact_packet=tablet_packet(),
                current_draft_fields={},
                model_client=excess_points_model,
                model_resolution={"provider_key": "fake", "model": excess_points_model.model},
            )
        except ListingDraftGenerationError as exc:
            if exc.failure_code != "listing_model_output_selling_points_count":
                raise
        else:
            raise AssertionError("Listing model output with more than five selling points was silently truncated")

        non_english_model = FakeListingModel(
            {
                "title": "折叠便携铝合金平板电脑支架",
                "selling_points": ["折叠便携", "铝合金材质", "硅胶防滑", "桌面使用", "轻巧收纳"],
                "description": "这是一款折叠便携的铝合金平板电脑支架。",
                "category_suggestion": "Tablet & eBook Reader Stands",
                "keywords": ["tablet stand"],
                "item_specifics": {"Type": "Tablet Stand"},
            }
        )
        try:
            generate_listing_draft(
                repository=repository,
                company_id=account["company"]["company_id"],
                store_id=store["store_id"],
                user_id=account["user"]["user_id"],
                listing_project_identity={"key": "listing-project-tablet-non-english"},
                merchant_product_fact_packet=tablet_packet(),
                current_draft_fields={},
                model_client=non_english_model,
                model_resolution={"provider_key": "fake", "model": non_english_model.model},
            )
        except ListingDraftGenerationError as exc:
            if exc.failure_code != "listing_model_output_marketplace_language":
                raise
        else:
            raise AssertionError("non-English buyer copy was persisted for EBAY_US")

        compatibility_model = FakeListingModel(
            {
                "title": "Foldable Aluminum Tablet Stand Adjustable Desk Holder",
                "selling_points": [
                    "Foldable profile for compact storage",
                    "Aluminum alloy construction",
                    "Silicone pads help protect contact surfaces",
                    "Measures 15 x 12 x 8 cm",
                    "Supports 4-13 inch tablets",
                ],
                "description": "Works with iPad Pro and fits most e-readers. Designed for Apple iPad devices.",
                "category_suggestion": "Tablet & eBook Reader Stands",
                "keywords": ["tablet stand"],
                "item_specifics": {"Type": "Tablet Stand"},
            }
        )
        try:
            generate_listing_draft(
                repository=repository,
                company_id=account["company"]["company_id"],
                store_id=store["store_id"],
                user_id=account["user"]["user_id"],
                listing_project_identity={"key": "listing-project-tablet-unverified-compatibility"},
                merchant_product_fact_packet=tablet_packet(),
                current_draft_fields={},
                model_client=compatibility_model,
                model_resolution={"provider_key": "fake", "model": compatibility_model.model},
            )
        except ListingDraftGenerationError as exc:
            if exc.failure_code != "listing_model_output_unverified_compatibility":
                raise
        else:
            raise AssertionError("unverified compatibility claim was persisted in buyer-facing copy")

        merchant_copy_model = FakeListingModel(
            {
                "title": "Model Draft Tablet Stand",
                "selling_points": [
                    "Foldable profile for storage",
                    "Aluminum alloy construction",
                    "Silicone contact pads",
                ],
                "description": "A foldable aluminum alloy tablet stand with silicone contact pads.",
                "category_suggestion": "Tablet & eBook Reader Stands",
                "keywords": ["tablet stand"],
                "item_specifics": {"Type": "Tablet Stand"},
            }
        )
        merchant_copy = generate_listing_draft(
            repository=repository,
            company_id=account["company"]["company_id"],
            store_id=store["store_id"],
            user_id=account["user"]["user_id"],
            listing_project_identity={"key": "listing-project-tablet-merchant-copy"},
            merchant_product_fact_packet=tablet_packet(),
            current_draft_fields={
                "title": "Merchant Edited Foldable Aluminum Tablet Stand",
                "selling_points": (
                    "Folds flat, for compact storage\n"
                    "Aluminum alloy body, with silicone contact pads\n"
                    "Measures 15 x 12 x 8 cm, net weight about 220 g"
                ),
                "description": "Merchant-confirmed tablet stand description.",
                "merchant_edited_fields": ["title", "selling_points", "description"],
            },
            model_client=merchant_copy_model,
            model_resolution={"provider_key": "fake", "model": merchant_copy_model.model},
        )
        merchant_fields = (
            (((merchant_copy.get("report") or {}).get("report") or {}).get("listing_handoff") or {}).get("listing_fields")
            or {}
        )
        if merchant_fields.get("title") != "Merchant Edited Foldable Aluminum Tablet Stand":
            raise AssertionError(f"explicit merchant edit was overwritten: {merchant_fields}")
        if len(merchant_fields.get("selling_points") or []) != 3:
            raise AssertionError(f"commas split one textarea line into extra selling points: {merchant_fields}")

        before_merchant_block_calls = merchant_copy_model.call_count
        merchant_block = generate_listing_draft(
            repository=repository,
            company_id=account["company"]["company_id"],
            store_id=store["store_id"],
            user_id=account["user"]["user_id"],
            listing_project_identity={"key": "listing-project-tablet-merchant-six-points"},
            merchant_product_fact_packet=tablet_packet(),
            current_draft_fields={
                "title": "Merchant Edited Foldable Aluminum Tablet Stand",
                "selling_points": "\n".join(f"Grounded merchant point {index}" for index in range(1, 7)),
                "description": "Merchant-confirmed tablet stand description.",
                "merchant_edited_fields": ["title", "selling_points", "description"],
            },
            model_client=merchant_copy_model,
            model_resolution={"provider_key": "fake", "model": merchant_copy_model.model},
        )
        if merchant_block.get("failure_code") != "listing_merchant_copy_selling_points_count":
            raise AssertionError(f"six merchant-edited selling points were not blocked precisely: {merchant_block}")
        if merchant_block.get("model_called") is not False or merchant_block.get("usage_consumed") is not False:
            raise AssertionError(f"merchant copy preflight consumed model usage: {merchant_block}")
        if merchant_copy_model.call_count != before_merchant_block_calls:
            raise AssertionError("merchant copy preflight called the model before blocking")

        reports_before_ledger_failure = len(repository.list_reports(company_id=account["company"]["company_id"]))
        original_record_model_usage = repository.record_model_usage

        def fail_model_usage_ledger(**_: Any) -> dict[str, Any]:
            raise RuntimeError("injected model usage ledger failure")

        repository.record_model_usage = fail_model_usage_ledger  # type: ignore[method-assign]
        try:
            generate_listing_draft(
                repository=repository,
                company_id=account["company"]["company_id"],
                store_id=store["store_id"],
                user_id=account["user"]["user_id"],
                listing_project_identity={"key": "listing-project-tablet-ledger-failure"},
                merchant_product_fact_packet=tablet_packet(),
                current_draft_fields={},
                model_client=merchant_copy_model,
                model_resolution={"provider_key": "fake", "model": merchant_copy_model.model},
            )
        except ListingDraftGenerationError as exc:
            if exc.failure_code != "listing_model_usage_ledger_failed":
                raise
            if exc.model_usage.get("request_count") != 2 or exc.usage_consumed is not True:
                raise AssertionError(f"ledger failure hid actual provider usage: {exc.model_usage}")
        else:
            raise AssertionError("Listing persisted despite a model usage ledger failure")
        finally:
            repository.record_model_usage = original_record_model_usage  # type: ignore[method-assign]
        if len(repository.list_reports(company_id=account["company"]["company_id"])) != reports_before_ledger_failure:
            raise AssertionError("model usage ledger failure left a persisted Listing report")

        failed_tasks = [
            task
            for task in repository.list_tasks(company_id=account["company"]["company_id"])
            if task.get("status") == "failed"
        ]
        if len(failed_tasks) != 5:
            raise AssertionError(f"quality failures were not retained as failed tasks: {failed_tasks}")
        for failed_task in failed_tasks:
            output = failed_task.get("output") if isinstance(failed_task.get("output"), dict) else {}
            failure_code = str(output.get("failure_code") or "")
            expected_requests = 1 if failure_code.startswith("listing_final_copy_") else 2
            if output.get("usage_consumed") is not True or output.get("model_request_count") != expected_requests:
                raise AssertionError(f"failed Listing task hid consumed model usage: {failed_task}")
            if not failure_code.startswith(("listing_model_output_", "listing_final_copy_")) and failure_code != "listing_model_usage_ledger_failed":
                raise AssertionError(f"failed Listing task lost the precise quality code: {failed_task}")
        listing_reports = [
            report
            for report in repository.list_reports(company_id=account["company"]["company_id"])
            if report.get("report_type") == "listing.package"
        ]
        if len(listing_reports) != 3:
            raise AssertionError(f"quality-blocked model output created a Listing report: {listing_reports}")
        with sqlite3.connect(db) as connection:
            usage_rows = connection.execute(
                "select request_count, usage_json from model_usage_ledger order by created_at asc"
            ).fetchall()
            execution_count = connection.execute("select count(*) from execution_results").fetchone()[0]
        if len(usage_rows) != 7 or sum(int(row[0] or 0) for row in usage_rows) != 14:
            raise AssertionError(f"success/failure model usage ledger is incomplete: {usage_rows}")
        if execution_count != 0:
            raise AssertionError("Listing copy generation or quality repair triggered a platform execution")

    print("PASS jiejing_listing_draft_buyer_copy_quality")


if __name__ == "__main__":
    main()
