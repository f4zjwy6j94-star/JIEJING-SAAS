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

_IMAGE_ASSET_TYPES = frozenset(
    {
        *AssetManifestValidator.IMAGE_TYPES,
        "image",
        "photo",
        "product_image",
        "concept_reference_image",
    }
)
_VIDEO_SUFFIXES = (".mp4", ".webm", ".mov")
_IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".avif")


def is_concept_only_media_spec(creative_job_spec: dict[str, Any] | None) -> bool:
    """Keep source-free concept policy identical before and after provider execution."""

    return bool(
        isinstance(creative_job_spec, dict)
        and creative_job_spec.get("output_safety_mode") == "concept_reference_only"
    )


def normalized_media_mime_type(asset: dict[str, Any]) -> str:
    """Return a value-free canonical MIME type supplied by the provider."""

    if not isinstance(asset, dict):
        return ""
    value = str(
        asset.get("mime_type")
        or asset.get("content_type")
        or asset.get("content-type")
        or ""
    ).strip().lower()
    return value.split(";", 1)[0].strip()


def media_asset_resource_type(asset: dict[str, Any]) -> str:
    """Classify one asset from type, MIME, and URL; conflicting signals fail closed."""

    if not isinstance(asset, dict):
        return "unknown"
    signals: set[str] = set()
    asset_type = str(
        asset.get("asset_type") or asset.get("media_type") or asset.get("type") or ""
    ).strip().lower()
    if "video" in asset_type:
        signals.add("video")
    elif asset_type in _IMAGE_ASSET_TYPES or "image" in asset_type or "photo" in asset_type:
        signals.add("image")
    mime_type = normalized_media_mime_type(asset)
    if mime_type.startswith("video/"):
        signals.add("video")
    elif mime_type.startswith("image/"):
        signals.add("image")
    reference = str(
        asset.get("url") or asset.get("url_or_file_path") or asset.get("path") or asset.get("file_path") or ""
    ).strip().lower().split("?", 1)[0]
    if reference.endswith(_VIDEO_SUFFIXES):
        signals.add("video")
    elif reference.endswith(_IMAGE_SUFFIXES):
        signals.add("image")
    if len(signals) > 1:
        return "conflict"
    return next(iter(signals), "unknown")


def media_asset_is_settlement_eligible(asset: dict[str, Any], *, require_https: bool = True) -> bool:
    """Reject failed, blocked, placeholder, or non-deliverable provider assets."""

    if not isinstance(asset, dict):
        return False
    reference = str(
        asset.get("url") or asset.get("url_or_file_path") or asset.get("path") or asset.get("file_path") or ""
    ).strip()
    if require_https and not reference.startswith("https://"):
        return False
    if media_asset_resource_type(asset) not in {"image", "video"}:
        return False
    allowed_states = {
        "status": {"generated", "ready", "returned", "completed", "success", "succeeded", "available", "ok"},
        "commercial_use_status": {"needs_review", "needs_rights_review"},
        "fact_review_status": {"needs_review"},
        "listing_use_status": {
            "not_ready_for_listing_until_review",
            "concept_only_not_eligible_for_listing",
        },
    }
    defaults = {
        "status": "generated",
        "commercial_use_status": "needs_rights_review",
        "fact_review_status": "needs_review",
        "listing_use_status": "not_ready_for_listing_until_review",
    }
    return all(
        str(asset.get(key) or defaults[key]).strip().lower() in allowed
        for key, allowed in allowed_states.items()
    )


def media_asset_is_video(asset: dict[str, Any]) -> bool:
    """Return true only when all available type signals agree that this is video."""

    return media_asset_resource_type(asset) == "video"


def media_asset_is_image(asset: dict[str, Any]) -> bool:
    """Return true only when all available type signals agree that this is an image."""

    return media_asset_resource_type(asset) == "image"


def media_manifest_matches_approved_quote(quote: dict[str, Any], manifest: list[dict[str, Any]]) -> bool:
    """Fail closed when a provider returns video that the merchant quote did not approve."""

    resource_types = {
        media_asset_resource_type(asset)
        for asset in manifest
        if isinstance(asset, dict)
    }
    if resource_types.intersection({"conflict", "unknown"}):
        return False
    video_present = "video" in resource_types
    if not video_present:
        return True
    return bool(
        isinstance(quote, dict)
        and quote.get("video_requested") is True
        and quote.get("chargeable") is True
    )


def media_asset_is_listing_review_eligible(asset: dict[str, Any]) -> bool:
    """Require the exact pre-approval states produced by the authoritative manifest pipeline."""

    if not media_asset_is_settlement_eligible(asset, require_https=True):
        return False
    return bool(
        str(asset.get("commercial_use_status") or "").strip().lower()
        in {"needs_review", "needs_rights_review"}
        and str(asset.get("fact_review_status") or "").strip().lower() == "needs_review"
        and str(asset.get("listing_use_status") or "").strip().lower()
        == "not_ready_for_listing_until_review"
    )


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
    version_context = _asset_version_context(inputs)
    assets = _placeholder_assets(
        image_count=image_count,
        image_sizes=image_sizes,
        scene_types=scene_types,
        video_script=video_script,
        version_context=version_context,
    )
    live_provider_called = False
    live_snapshot_has_assets = bool(
        isinstance(live_media_snapshot, dict) and live_media_snapshot.get("assets")
    )
    if live_snapshot_has_assets:
        concept_only = is_concept_only_media_spec(creative_job_spec)
        live_assets = _live_provider_assets(live_media_snapshot, version_context=version_context, concept_only=concept_only)
        if live_assets:
            assets = live_assets
            live_provider_called = True
    manifest_packet = {
        "assets": assets,
        "manifest_status": "generated_by_live_provider_for_review" if live_provider_called else "placeholder_not_reviewable",
        "single_output_contract": "AssetManifest",
        "live_provider_called": live_provider_called,
        "secret_exposed": False,
    }
    validation = _validate_manifest(manifest_packet)
    if live_snapshot_has_assets and not live_provider_called:
        validation = {
            **validation,
            "status": "blocked_incomplete_manifest",
            "blocked_by": ["unsupported_live_asset_reference"],
            "secret_exposed": False,
        }
    missing_fact_keys = missing_media_product_fact_keys(inputs)
    review_gates = _review_gates(
        validation=validation,
        missing_fact_keys=missing_fact_keys,
        creative_job_spec=creative_job_spec,
        live_provider_called=live_provider_called,
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
        "asset_version": version_context,
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
            "status": _asset_review_status(
                validation=validation,
                missing_fact_keys=missing_fact_keys,
                live_provider_called=live_provider_called,
            ),
            "review_gates": review_gates,
            "listing_use_status": (
                "concept_only_not_eligible_for_listing"
                if is_concept_only_media_spec(creative_job_spec)
                else "not_ready_for_listing_until_review"
                if live_provider_called
                else "blocked_missing_live_provider"
            ),
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
            "calls_image_provider": bool(
                live_provider_called
                and any(media_asset_is_image(item) for item in assets if isinstance(item, dict))
            ),
            "calls_video_provider": bool(
                live_provider_called
                and any(media_asset_is_video(item) for item in assets if isinstance(item, dict))
            ),
            "raw_secret_read": False,
            "raw_provider_response_stored": False,
            "real_platform_writes_enabled": False,
            "frontend_gets_media_api_key": False,
            "runtime_gets_raw_secret": False,
            "secret_exposed": False,
        },
}


def _live_provider_assets(
    snapshot: dict[str, Any],
    *,
    version_context: dict[str, Any],
    concept_only: bool = False,
) -> list[dict[str, Any]]:
    raw_assets = snapshot.get("assets") if isinstance(snapshot.get("assets"), list) else []
    provider = str(snapshot.get("provider") or "configured_media_provider")
    assets: list[dict[str, Any]] = []
    for index, item in enumerate(raw_assets, start=1):
        if not isinstance(item, dict):
            continue
        url_or_path = str(item.get("url") or item.get("url_or_file_path") or item.get("path") or "").strip()
        if not media_asset_is_settlement_eligible(item, require_https=True):
            continue
        resource_type = media_asset_resource_type(item)
        raw_asset_type = str(item.get("asset_type") or item.get("type") or "").strip()
        if concept_only and resource_type == "image":
            asset_type = "concept_reference_image"
        elif raw_asset_type:
            asset_type = raw_asset_type
        else:
            asset_type = "product_video" if resource_type == "video" else "product_image"
        mime_type = normalized_media_mime_type(item)
        duration = item.get("duration_seconds") or item.get("duration")
        dimensions = item.get("dimensions") or item.get("dimensions_or_duration") or (f"{duration}s" if duration else "provider_returned")
        assets.append(
            {
                "asset_id": item.get("asset_id") or item.get("id") or f"live_provider_asset_{index:02d}",
                "asset_version": version_context["version"],
                "parent_media_job_id": version_context["parent_media_job_id"],
                "generation_reason": version_context["generation_reason"],
                "asset_type": asset_type,
                "mime_type": mime_type,
                "url": url_or_path,
                "url_or_file_path": url_or_path,
                "dimensions": dimensions,
                "dimensions_or_duration": dimensions,
                "duration_seconds": duration,
                "source": "media_generation_provider",
                "source_provider_or_upload": provider,
                "prompt_version": version_context["prompt_version"],
                "cost_estimate": "see_cost_guard",
                "commercial_use_status": item.get("commercial_use_status") or "needs_rights_review",
                "fact_review_status": "needs_review",
                "listing_use_status": "concept_only_not_eligible_for_listing" if concept_only else "not_ready_for_listing_until_review",
                "status": item.get("status") or "generated",
                "review_status": "concept_reference_requires_real_product_source" if concept_only else "needs_human_review_before_listing",
            }
        )
    return assets


def _placeholder_assets(
    *,
    image_count: int,
    image_sizes: list[str],
    scene_types: list[str],
    video_script: str,
    version_context: dict[str, Any],
) -> list[dict[str, Any]]:
    count = max(1, min(image_count, 4))
    assets: list[dict[str, Any]] = []
    for index in range(count):
        scene = scene_types[index % len(scene_types)] if scene_types else "image"
        size = image_sizes[index % len(image_sizes)] if image_sizes else "1:1"
        assets.append(
            {
                "asset_id": f"dry_run_image_{index + 1:02d}",
                "asset_version": version_context["version"],
                "parent_media_job_id": version_context["parent_media_job_id"],
                "generation_reason": version_context["generation_reason"],
                "asset_type": _asset_type_for_scene(scene),
                "url": f"dry-run://media/{scene or 'image'}-{index + 1}",
                "url_or_file_path": f"dry-run://media/{scene or 'image'}-{index + 1}",
                "dimensions": _dimension_label(size),
                "dimensions_or_duration": _dimension_label(size),
                "source": "media_asset_generation_router",
                "source_provider_or_upload": "configured_media_provider",
                "prompt_version": version_context["prompt_version"],
                "cost_estimate": "pending_quota_check",
                "commercial_use_status": "needs_rights_review",
                "fact_review_status": "needs_review",
                "listing_use_status": "blocked_missing_live_provider",
                "status": "generated_placeholder",
                "review_status": "blocked_missing_live_provider",
            }
        )
    if video_script:
        assets.append(
            {
                "asset_id": "dry_run_video_script_01",
                "asset_version": version_context["version"],
                "parent_media_job_id": version_context["parent_media_job_id"],
                "generation_reason": version_context["generation_reason"],
                "asset_type": "product_video",
                "url": "dry-run://media/video-script-placeholder",
                "url_or_file_path": "dry-run://media/video-script-placeholder",
                "duration_seconds": 20,
                "dimensions_or_duration": "20s_script_placeholder",
                "source": "media_asset_generation_router",
                "source_provider_or_upload": "configured_media_provider",
                "prompt_version": version_context["prompt_version"],
                "cost_estimate": "pending_quota_check",
                "commercial_use_status": "needs_rights_review",
                "fact_review_status": "needs_review",
                "listing_use_status": "blocked_missing_live_provider",
                "status": "script_placeholder",
                "review_status": "blocked_missing_live_provider",
            }
        )
    return assets


def _validate_manifest(manifest_packet: dict[str, Any]) -> dict[str, Any]:
    text = "Generated media placeholder assets are ready for review.\n```json\n"
    text += json.dumps(manifest_packet, ensure_ascii=False)
    text += "\n```"
    return AssetManifestValidator().validate_text(text)


def missing_media_product_fact_keys(inputs: dict[str, Any]) -> list[str]:
    """Return the server-authoritative fact blockers shared by preflight and postflight."""

    product_facts = inputs.get("product_facts") if isinstance(inputs.get("product_facts"), dict) else {}
    creative_job_spec = inputs.get("creative_job_spec") if isinstance(inputs.get("creative_job_spec"), dict) else {}
    supplier = product_facts.get("supplier_facts") if isinstance(product_facts.get("supplier_facts"), dict) else {}
    reference_images = (
        product_facts.get("reference_images")
        if isinstance(product_facts.get("reference_images"), list)
        else []
    )
    reference_image_url = str(inputs.get("reference_image_url") or "").strip()
    hydrated_private_source = bool(
        product_facts.get("source_asset_id")
        and (
            (
                inputs.get("private_media_source_hydrated") is True
                and reference_image_url.startswith("data:image/")
            )
            or inputs.get("private_media_source_preflight_validated") is True
        )
    )
    grounded_reference = bool(
        reference_image_url.startswith("https://")
        or any(str(item or "").strip().startswith("https://") for item in reference_images)
        or hydrated_private_source
    )
    checks = {
        "product_identity": _has_confirmed_fact(product_facts.get("product") or product_facts.get("product_identity")),
        "confirmed_dimensions_or_pending_label": _has_confirmed_fact(supplier.get("package_dimensions_cm") or supplier.get("dimensions")) or bool(product_facts.get("dimensions_pending_label")),
        "confirmed_material_or_pending_label": _has_confirmed_fact(supplier.get("material")) or bool(product_facts.get("material_pending_label")),
        "allowed_claims": bool(product_facts.get("allowed_claims") or product_facts.get("listing_context")),
        "forbidden_claims": bool(product_facts.get("forbidden_claims") or creative_job_spec.get("blocked_claims")),
        "reference_images_or_source_notes": grounded_reference,
        "target_marketplace_rules": bool(
            product_facts.get("target_marketplace_rules")
            or product_facts.get("listing_context")
            or creative_job_spec.get("platform")
        ),
    }
    concept_only = is_concept_only_media_spec(creative_job_spec)
    requested = creative_job_spec.get("product_facts_required")
    requested_keys = [str(key) for key in requested] if isinstance(requested, list) else []
    server_required = ["product_identity", "confirmed_material_or_pending_label", "allowed_claims"]
    if concept_only:
        server_required.append("forbidden_claims")
        requested_keys = [key for key in requested_keys if key != "reference_images_or_source_notes"]
    else:
        server_required.extend(["reference_images_or_source_notes", "target_marketplace_rules"])
    scene_types = inputs.get("scene_types") if isinstance(inputs.get("scene_types"), list) else []
    if any("dimension" in str(scene).lower() or "size" in str(scene).lower() for scene in scene_types):
        server_required.append("confirmed_dimensions_or_pending_label")
    required = list(dict.fromkeys([*server_required, *requested_keys]))
    return [key for key in required if checks.get(key) is False]


def _has_confirmed_fact(value: Any) -> bool:
    if isinstance(value, dict):
        return bool(value) and all(_has_confirmed_fact(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return bool(value) and all(_has_confirmed_fact(item) for item in value)
    text = str(value or "").strip().lower()
    return bool(text) and text not in {
        "待补",
        "待补充",
        "待确认",
        "当前商品",
        "未填写",
        "unknown",
        "todo",
        "pending",
        "n/a",
    }


def _review_gates(
    *,
    validation: dict[str, Any],
    missing_fact_keys: list[str],
    creative_job_spec: dict[str, Any],
    live_provider_called: bool,
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
        elif not live_provider_called:
            status = "blocked_missing_live_provider"
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
        "contract_version": "2026-07-11-media-cost-transparency-v1",
        "status": "blocked_until_quota_and_cost_limit",
        "estimated_max_cost_cents": estimated_max_cents,
        "estimate_currency": "USD",
        "estimate_is_ceiling_not_invoice": True,
        "requested_cost_limit_cents": requested_limit,
        "within_requested_limit": bool(requested_limit and estimated_max_cents <= requested_limit),
        "actual_cost_cents": None,
        "actual_cost_status": "unknown_until_provider_usage_record",
        "merchant_charge_created": False,
        "spend_now_allowed": False,
        "requires_paid_entitlement_or_manual_beta_quota": True,
        "requires_owner_or_merchant_confirmation_for_high_cost": True,
        "secret_exposed": False,
    }


def _asset_version_context(inputs: dict[str, Any]) -> dict[str, Any]:
    raw = inputs.get("asset_version") if isinstance(inputs.get("asset_version"), dict) else {}
    version = max(1, _safe_int(raw.get("version"), default=1))
    reason = str(raw.get("generation_reason") or ("initial_generation" if version == 1 else "merchant_requested_rework"))[:200]
    prompt_version = str(raw.get("prompt_version") or f"media_prompt_v{version}")[:80]
    return {
        "contract_version": "2026-07-11-media-asset-version-v1",
        "version": version,
        "root_media_job_id": str(raw.get("root_media_job_id") or "")[:120],
        "parent_media_job_id": str(raw.get("parent_media_job_id") or "")[:120],
        "generation_reason": reason,
        "prompt_version": prompt_version,
        "immutable_prior_versions": True,
        "secret_exposed": False,
    }


def _asset_review_status(*, validation: dict[str, Any], missing_fact_keys: list[str], live_provider_called: bool) -> str:
    if validation.get("status") != "manifest_ready":
        return "blocked_manifest_not_ready"
    if missing_fact_keys:
        return "blocked_missing_product_facts"
    if not live_provider_called:
        return "blocked_missing_live_provider"
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
