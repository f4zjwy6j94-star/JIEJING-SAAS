"""SaaS media asset generation packet builder.

This is the production-shape layer for ``media.asset_generation``. It does not
call image/video providers. It turns a creative job spec into an auditable
AssetManifest packet with validation, review gates, and cost/quota guards.
"""

from __future__ import annotations

import json
from typing import Any

from jiejing_runtime.asset_manifest import AssetManifestValidator
from jiejing_runtime.media_capability_router import build_media_capability_router


MEDIA_ASSET_PIPELINE_VERSION = "2026-07-01-media-asset-pipeline-v1"


def build_media_asset_generation_packet(
    *,
    base: dict[str, Any],
    contract_key: str,
    inputs: dict[str, Any],
    captured_at: str,
    live_media_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a provider-neutral media packet for dry-run or reviewed live media output."""

    product_facts = inputs.get("product_facts") if isinstance(inputs.get("product_facts"), dict) else {}
    creative_job_spec = inputs.get("creative_job_spec") if isinstance(inputs.get("creative_job_spec"), dict) else {}
    image_sizes = _list_or_default(inputs.get("image_sizes"), ["1:1", "4:5", "16:9"])
    scene_types = _list_or_default(inputs.get("scene_types"), ["white_background", "lifestyle_scene", "detail_page", "size_chart"])
    image_count = max(1, min(_safe_int(inputs.get("image_count"), default=1), 12))
    video_script = str(inputs.get("video_script") or "").strip()
    media_provider = str(inputs.get("media_provider") or inputs.get("preferred_media_provider") or "").strip()
    model_provider = str(inputs.get("model_provider") or inputs.get("ai_model_provider") or "").strip()
    router = build_media_capability_router(
        preferred_model_provider=model_provider,
        media_provider=media_provider,
        image_provider_configured=False,
        video_provider_configured=False,
        voice_provider_configured=False,
    )
    assets = _placeholder_assets(
        image_count=image_count,
        image_sizes=image_sizes,
        scene_types=scene_types,
        video_script=video_script,
    )
    live_provider_called = False
    if isinstance(live_media_snapshot, dict) and live_media_snapshot.get("assets"):
        live_assets = _live_provider_assets(live_media_snapshot)
        if live_assets:
            assets = live_assets
            live_provider_called = True
    manifest_packet = {
        "assets": assets,
        "manifest_status": "generated_by_live_provider_for_review" if live_provider_called else "generated_placeholder_for_review",
        "single_output_contract": "AssetManifest",
        "live_provider_called": live_provider_called,
        "secret_exposed": False,
    }
    validation = _validate_manifest(manifest_packet)
    missing_fact_keys = _missing_product_fact_keys(product_facts=product_facts, creative_job_spec=creative_job_spec)
    review_gates = _review_gates(
        validation=validation,
        missing_fact_keys=missing_fact_keys,
        creative_job_spec=creative_job_spec,
    )
    cost_guard = _cost_guard(
        image_count=image_count,
        video_requested=bool(video_script),
        inputs=inputs,
    )
    return {
        **base,
        "pipeline_version": MEDIA_ASSET_PIPELINE_VERSION,
        "media_router": {
            **router.get("routing_decision", {}),
            "contract_key": contract_key,
            "canonical_contract_key": "media.asset_generation",
            "driver": "configured_media_provider",
            "driver_selected_later": not live_provider_called,
            "fal_is_legacy_driver_alias": contract_key == "media.fal_asset_generation",
            "merchant_visible_provider_name": False,
            "live_provider_called": live_provider_called,
        },
        "creative_job_spec": creative_job_spec,
        "product_fact_gate": {
            "status": "needs_fact_review" if missing_fact_keys else "facts_ready_for_asset_review",
            "missing_fact_keys": missing_fact_keys,
            "pending_labels_allowed": True,
            "must_not_invent_missing_facts": True,
            "secret_exposed": False,
        },
        "asset_manifest": assets,
        "asset_manifest_packet": manifest_packet,
        "asset_manifest_validation": validation,
        "asset_review": {
            "status": _asset_review_status(validation=validation, missing_fact_keys=missing_fact_keys),
            "review_gates": review_gates,
            "listing_use_status": "not_ready_for_listing_until_review",
            "confirmation_center_required_before_listing_use": True,
            "secret_exposed": False,
        },
        "cost_guard": cost_guard,
        "production_gate": {
            "status": "live_media_provider_completed_waiting_review" if live_provider_called else "blocked_before_live_media_provider",
            "live_media_provider_call_allowed": live_provider_called,
            "live_media_provider_call_completed": live_provider_called,
            "requires_quota_check": True,
            "requires_asset_manifest_validation": True,
            "requires_asset_review_approval": True,
            "requires_provider_driver_configuration": not live_provider_called,
            "next_safe_step": "review_asset_manifest_before_listing_use" if live_provider_called else "approve_quota_and_provider_driver_then_run_async_media_job",
            "secret_exposed": False,
        },
        "merchant_visible_states": [
            "waiting_for_product_facts" if missing_fact_keys else "ready_to_generate",
            "generating",
            "waiting_for_review",
            "usable_for_listing",
            "needs_rework",
            "blocked_missing_provider",
        ],
        "scene_types": scene_types,
        "video_script_status": "received" if video_script else "missing",
        "safety": {
            "live_provider_called": live_provider_called,
            "calls_image_provider": bool(live_provider_called and any(str(item.get("asset_type", "")).startswith("product_") or "image" in str(item.get("asset_type", "")) for item in assets)),
            "calls_video_provider": bool(live_provider_called and any("video" in str(item.get("asset_type", "")) for item in assets)),
            "raw_secret_read": False,
            "raw_provider_response_stored": False,
            "real_platform_writes_enabled": False,
            "frontend_gets_media_api_key": False,
            "runtime_gets_raw_secret": False,
            "secret_exposed": False,
        },
}


def _live_provider_assets(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    raw_assets = snapshot.get("assets") if isinstance(snapshot.get("assets"), list) else []
    provider = str(snapshot.get("provider") or "configured_media_provider")
    assets: list[dict[str, Any]] = []
    for index, item in enumerate(raw_assets, start=1):
        if not isinstance(item, dict):
            continue
        url_or_path = str(item.get("url") or item.get("url_or_file_path") or item.get("path") or "").strip()
        if not url_or_path:
            continue
        asset_type = str(item.get("asset_type") or item.get("type") or "product_image").strip() or "product_image"
        duration = item.get("duration_seconds") or item.get("duration")
        dimensions = item.get("dimensions") or item.get("dimensions_or_duration") or (f"{duration}s" if duration else "provider_returned")
        assets.append(
            {
                "asset_id": item.get("asset_id") or item.get("id") or f"live_provider_asset_{index:02d}",
                "asset_type": asset_type,
                "url": url_or_path,
                "url_or_file_path": url_or_path,
                "dimensions": dimensions,
                "dimensions_or_duration": dimensions,
                "duration_seconds": duration,
                "source": "media_generation_provider",
                "source_provider_or_upload": provider,
                "prompt_version": "live_media_generation_v1",
                "cost_estimate": "provider_spend_recorded",
                "commercial_use_status": item.get("commercial_use_status") or "needs_rights_review",
                "fact_review_status": "needs_review",
                "listing_use_status": "not_ready_for_listing_until_review",
                "status": item.get("status") or "generated",
                "review_status": "needs_human_review_before_listing",
            }
        )
    return assets


def _placeholder_assets(
    *,
    image_count: int,
    image_sizes: list[str],
    scene_types: list[str],
    video_script: str,
) -> list[dict[str, Any]]:
    count = max(1, min(image_count, 4))
    assets: list[dict[str, Any]] = []
    for index in range(count):
        scene = scene_types[index % len(scene_types)] if scene_types else "image"
        size = image_sizes[index % len(image_sizes)] if image_sizes else "1:1"
        assets.append(
            {
                "asset_id": f"dry_run_image_{index + 1:02d}",
                "asset_type": _asset_type_for_scene(scene),
                "url": f"dry-run://media/{scene or 'image'}-{index + 1}",
                "url_or_file_path": f"dry-run://media/{scene or 'image'}-{index + 1}",
                "dimensions": _dimension_label(size),
                "dimensions_or_duration": _dimension_label(size),
                "source": "media_asset_generation_router",
                "source_provider_or_upload": "configured_media_provider",
                "prompt_version": "pending_live_media_generation",
                "cost_estimate": "pending_quota_check",
                "commercial_use_status": "needs_rights_review",
                "fact_review_status": "needs_review",
                "listing_use_status": "not_ready_for_listing_until_review",
                "status": "generated_placeholder",
                "review_status": "needs_human_review_before_listing",
            }
        )
    if video_script:
        assets.append(
            {
                "asset_id": "dry_run_video_script_01",
                "asset_type": "product_video",
                "url": "dry-run://media/video-script-placeholder",
                "url_or_file_path": "dry-run://media/video-script-placeholder",
                "duration_seconds": 20,
                "dimensions_or_duration": "20s_script_placeholder",
                "source": "media_asset_generation_router",
                "source_provider_or_upload": "configured_media_provider",
                "prompt_version": "pending_live_video_generation",
                "cost_estimate": "pending_quota_check",
                "commercial_use_status": "needs_rights_review",
                "fact_review_status": "needs_review",
                "listing_use_status": "not_ready_for_listing_until_review",
                "status": "script_placeholder",
                "review_status": "needs_human_review_before_listing",
            }
        )
    return assets


def _validate_manifest(manifest_packet: dict[str, Any]) -> dict[str, Any]:
    text = "Generated media placeholder assets are ready for review.\n```json\n"
    text += json.dumps(manifest_packet, ensure_ascii=False)
    text += "\n```"
    return AssetManifestValidator().validate_text(text)


def _missing_product_fact_keys(*, product_facts: dict[str, Any], creative_job_spec: dict[str, Any]) -> list[str]:
    supplier = product_facts.get("supplier_facts") if isinstance(product_facts.get("supplier_facts"), dict) else {}
    checks = {
        "product_identity": bool(product_facts.get("product") or product_facts.get("product_identity")),
        "confirmed_dimensions_or_pending_label": bool(supplier.get("package_dimensions_cm") or supplier.get("dimensions") or product_facts.get("dimensions_pending_label")),
        "confirmed_material_or_pending_label": bool(supplier.get("material") or product_facts.get("material_pending_label")),
        "allowed_claims": bool(product_facts.get("allowed_claims") or product_facts.get("listing_context")),
        "forbidden_claims": bool(product_facts.get("forbidden_claims") or creative_job_spec.get("blocked_claims")),
        "reference_images_or_source_notes": bool(product_facts.get("reference_images") or product_facts.get("source_notes") or product_facts.get("listing_context")),
        "target_marketplace_rules": bool(product_facts.get("target_marketplace_rules") or product_facts.get("listing_context")),
    }
    required = creative_job_spec.get("product_facts_required")
    if not isinstance(required, list) or not required:
        required = list(checks.keys())
    return [key for key in required if checks.get(str(key)) is False]


def _review_gates(
    *,
    validation: dict[str, Any],
    missing_fact_keys: list[str],
    creative_job_spec: dict[str, Any],
) -> list[dict[str, Any]]:
    requested = creative_job_spec.get("review_gates")
    if not isinstance(requested, list) or not requested:
        requested = [
            "fact_consistency_review",
            "commercial_use_rights_review",
            "platform_image_video_policy_review",
            "no_unverified_claims_review",
            "listing_use_approval",
        ]
    manifest_ready = validation.get("status") == "manifest_ready"
    gates: list[dict[str, Any]] = []
    for key in requested:
        key = str(key)
        if key == "fact_consistency_review" and missing_fact_keys:
            status = "blocked_missing_product_facts"
        elif not manifest_ready:
            status = "blocked_manifest_not_ready"
        else:
            status = "needs_review"
        gates.append(
            {
                "key": key,
                "status": status,
                "required_before_listing": True,
                "confirmation_center_required": key == "listing_use_approval",
                "secret_exposed": False,
            }
        )
    return gates


def _cost_guard(*, image_count: int, video_requested: bool, inputs: dict[str, Any]) -> dict[str, Any]:
    image_ceiling = max(1, image_count) * 80
    video_ceiling = 1200 if video_requested else 0
    estimated_max_cents = image_ceiling + video_ceiling
    requested_limit = _safe_int(inputs.get("cost_limit_cents") or inputs.get("media_cost_limit_cents"), default=0)
    return {
        "status": "blocked_until_quota_and_cost_limit",
        "estimated_max_cost_cents": estimated_max_cents,
        "requested_cost_limit_cents": requested_limit,
        "within_requested_limit": bool(requested_limit and estimated_max_cents <= requested_limit),
        "spend_now_allowed": False,
        "requires_paid_entitlement_or_manual_beta_quota": True,
        "requires_owner_or_merchant_confirmation_for_high_cost": True,
        "secret_exposed": False,
    }


def _asset_review_status(*, validation: dict[str, Any], missing_fact_keys: list[str]) -> str:
    if validation.get("status") != "manifest_ready":
        return "blocked_manifest_not_ready"
    if missing_fact_keys:
        return "blocked_missing_product_facts"
    return "waiting_for_human_asset_review"


def _asset_type_for_scene(scene: str) -> str:
    normalized = str(scene or "").strip().lower()
    if "detail" in normalized:
        return "detail_page"
    if "size" in normalized or "dimension" in normalized:
        return "dimension_image"
    if "scene" in normalized or "lifestyle" in normalized:
        return "lifestyle_image"
    return "main_image"


def _dimension_label(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return "pending_size"
    if ":" in text and "x" not in text.lower():
        return f"ratio_{text}"
    return text


def _list_or_default(value: Any, default: list[str]) -> list[str]:
    if isinstance(value, list):
        out = [str(item).strip() for item in value if str(item).strip()]
        return out or list(default)
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return list(default)


def _safe_int(value: Any, *, default: int) -> int:
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return default
