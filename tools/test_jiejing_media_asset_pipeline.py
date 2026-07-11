#!/usr/bin/env python3
"""Regression for the SaaS media asset generation pipeline packet."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.media_asset_pipeline import MEDIA_ASSET_PIPELINE_VERSION, build_media_asset_generation_packet  # noqa: E402


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    base = {
        "packet_type": "asset_manifest",
        "provider_family": "media",
        "source_record_type": "media_provider",
        "status": "dry_run_ready",
        "missing_inputs": [],
        "live_provider_called": False,
        "secret_exposed": False,
    }
    packet = build_media_asset_generation_packet(
        base=base,
        contract_key="media.asset_generation",
        captured_at="2026-07-01T00:00:00Z",
        inputs={
            "model_provider": "deepseek",
            "media_provider": "fal",
            "creative_job_spec": {
                "job_type": "eBay_listing_asset_package",
                "product_facts_required": [
                    "product_identity",
                    "confirmed_dimensions_or_pending_label",
                    "confirmed_material_or_pending_label",
                    "allowed_claims",
                    "forbidden_claims",
                    "reference_images_or_source_notes",
                    "target_marketplace_rules",
                ],
                "review_gates": [
                    "fact_consistency_review",
                    "commercial_use_rights_review",
                    "platform_image_video_policy_review",
                    "listing_use_approval",
                ],
                "blocked_claims": ["unverified_certification"],
            },
            "product_facts": {
                "product": "Stainless steel tumbler",
                "supplier_facts": {
                    "material": "stainless steel",
                    "package_dimensions_cm": {"length": 10, "width": 10, "height": 18},
                },
                "allowed_claims": ["keeps drinks cold"],
                "forbidden_claims": ["medical"],
                "reference_images": ["merchant_upload://reference-1"],
                "target_marketplace_rules": {"platform": "ebay"},
            },
            "image_count": 3,
            "image_sizes": ["1600x1600", "1200x1600"],
            "scene_types": ["white_background", "lifestyle_scene", "detail_page"],
            "video_script": "15 second product demo script",
            "cost_limit_cents": 100,
        },
    )
    if packet.get("pipeline_version") != MEDIA_ASSET_PIPELINE_VERSION:
        return fail("media asset pipeline version missing")
    validation = packet.get("asset_manifest_validation") if isinstance(packet.get("asset_manifest_validation"), dict) else {}
    if validation.get("status") != "manifest_ready":
        return fail(f"pipeline should produce validator-ready manifest placeholders: {validation}")
    if packet.get("asset_review", {}).get("listing_use_status") != "not_ready_for_listing_until_review":
        return fail("asset manifest must not become listing-ready before review")
    if packet.get("asset_review", {}).get("status") != "waiting_for_human_asset_review":
        return fail("complete product facts should move to human asset review")
    if packet.get("production_gate", {}).get("live_media_provider_call_allowed") is not False:
        return fail("pipeline must not allow live media provider calls")
    if packet.get("cost_guard", {}).get("spend_now_allowed") is not False:
        return fail("pipeline must block media spend until quota/limit approval")
    if packet.get("cost_guard", {}).get("within_requested_limit") is not False:
        return fail("test packet should show estimated media spend above the requested limit")
    if packet.get("media_router", {}).get("brain_provider") != "deepseek":
        return fail("merchant model should remain the brain provider")
    if packet.get("media_router", {}).get("merchant_visible_provider_name") is not False:
        return fail("merchant-facing flow should not expose internal media driver names")
    if packet.get("product_fact_gate", {}).get("status") != "facts_ready_for_asset_review":
        return fail("complete facts should pass the product fact gate")

    missing = build_media_asset_generation_packet(
        base=base,
        contract_key="media.asset_generation",
        captured_at="2026-07-01T00:00:00Z",
        inputs={
            "creative_job_spec": {"product_facts_required": ["product_identity", "confirmed_material_or_pending_label"]},
            "product_facts": {"product": "Unknown product"},
            "image_count": 1,
            "image_sizes": ["1:1"],
            "scene_types": ["white_background"],
        },
    )
    if missing.get("product_fact_gate", {}).get("status") != "needs_fact_review":
        return fail("missing supplier facts should block fact review")
    gates = missing.get("asset_review", {}).get("review_gates", [])
    if not any(item.get("status") == "blocked_missing_product_facts" for item in gates):
        return fail("review gates should expose missing product facts")

    concept = build_media_asset_generation_packet(
        base=base,
        contract_key="media.asset_generation",
        captured_at="2026-07-01T00:00:00Z",
        inputs={
            "creative_job_spec": {
                "output_safety_mode": "concept_reference_only",
                "product_facts_required": ["product_identity", "reference_images_or_source_notes"],
            },
            "product_facts": {"product": "Silicone cup covers", "reference_images": []},
            "image_count": 1,
        },
        live_media_snapshot={
            "provider": "fake",
            "assets": [{"asset_id": "concept-1", "asset_type": "product_image", "url": "https://example.test/concept.jpg"}],
        },
    )
    concept_asset = concept.get("asset_manifest", [{}])[0]
    if concept_asset.get("asset_type") != "concept_reference_image":
        return fail(f"ungrounded live output must be labelled concept reference: {concept_asset}")
    if concept_asset.get("listing_use_status") != "concept_only_not_eligible_for_listing":
        return fail("concept reference must not become Listing eligible")

    for checked in (packet, missing):
        if checked.get("secret_exposed") is not False:
            return fail("pipeline packet must not expose secrets")
        safety = checked.get("safety") if isinstance(checked.get("safety"), dict) else {}
        for marker in (
            "live_provider_called",
            "calls_image_provider",
            "calls_video_provider",
            "raw_secret_read",
            "raw_provider_response_stored",
            "real_platform_writes_enabled",
            "frontend_gets_media_api_key",
            "runtime_gets_raw_secret",
            "secret_exposed",
        ):
            if safety.get(marker) is not False:
                return fail(f"pipeline unsafe flag should be false: {marker}")

    print("PASS jiejing_media_asset_pipeline")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
