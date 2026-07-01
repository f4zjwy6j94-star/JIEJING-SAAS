"""Provider-neutral media capability routing for Jiejing Runtime.

Jiejing should not let a merchant-selected model decide the whole asset
workflow. This module describes the stable Jiejing layer: models and media
tools are capability providers, while generated images/videos must always
return through the AssetManifest contract before they can affect a Listing.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


MEDIA_ROUTER_VERSION = "2026-07-01-media-capability-router-v1"


CAPABILITIES = [
    "text",
    "structured_json",
    "tool_calls",
    "vision_input",
    "image_generation",
    "image_edit",
    "video_generation",
    "voice",
    "async_webhook",
    "commercial_rights_metadata",
    "cost_estimate",
    "region_available",
]


@dataclass(frozen=True, slots=True)
class ModelCapabilityProfile:
    provider: str
    label: str
    capabilities: list[str]
    recommended_role: str
    missing_capabilities: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class CreativeJobSpec:
    job_type: str
    product_facts_required: list[str]
    output_assets: list[str]
    review_gates: list[str]
    blocked_claims: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_media_capability_router(
    *,
    preferred_model_provider: str = "",
    media_provider: str = "",
    image_provider_configured: bool = False,
    video_provider_configured: bool = False,
    voice_provider_configured: bool = False,
) -> dict[str, Any]:
    provider = _normalize_provider(preferred_model_provider)
    profiles = _profiles()
    selected = profiles.get(provider) or profiles["generic_text_model"]
    configured_media = {
        "image": bool(image_provider_configured),
        "video": bool(video_provider_configured),
        "voice": bool(voice_provider_configured),
    }
    routing = _routing_decision(selected, media_provider=media_provider, configured_media=configured_media)
    return {
        "router_version": MEDIA_ROUTER_VERSION,
        "mode": "capability_router_no_generation_no_provider_call",
        "selected_model_provider": selected.provider,
        "selected_model_role": selected.recommended_role,
        "capability_axis": list(CAPABILITIES),
        "model_profile": selected.to_dict(),
        "known_profiles": [profile.to_dict() for profile in profiles.values()],
        "creative_job_spec": _creative_job_spec().to_dict(),
        "routing_decision": routing,
        "asset_contract": {
            "single_output_contract": "AssetManifest",
            "all_generated_or_uploaded_assets_must_return_manifest": True,
            "manifest_required_fields": [
                "asset_type",
                "url_or_file_path",
                "dimensions_or_duration",
                "source_provider_or_upload",
                "commercial_use_status",
                "fact_review_status",
                "listing_use_status",
            ],
            "brief_is_not_generated_media": True,
            "cannot_claim_generated_without_manifest": True,
        },
        "merchant_visible_states": [
            "waiting_for_product_facts",
            "ready_to_generate",
            "generating",
            "waiting_for_review",
            "usable_for_listing",
            "needs_rework",
            "blocked_missing_provider",
        ],
        "safety": {
            "calls_model_api": False,
            "calls_image_provider": False,
            "calls_video_provider": False,
            "triggers_real_platform_write": False,
            "creates_checkout_session": False,
            "frontend_gets_model_api_key": False,
            "frontend_gets_media_api_key": False,
            "runtime_gets_raw_secret": False,
            "secret_exposed": False,
        },
        "secret_exposed": False,
    }


def _profiles() -> dict[str, ModelCapabilityProfile]:
    return {
        "deepseek": ModelCapabilityProfile(
            provider="deepseek",
            label="DeepSeek text/reasoning model",
            capabilities=["text", "structured_json", "tool_calls"],
            recommended_role="brain_planner_prompt_writer_review_rules",
            missing_capabilities=["image_generation", "image_edit", "video_generation", "voice"],
            notes=[
                "Use for asset brief, prompts, shot list, banned claims, and review checklist.",
                "Do not assume direct image or video generation.",
            ],
        ),
        "openai": ModelCapabilityProfile(
            provider="openai",
            label="OpenAI multimodal-capable provider",
            capabilities=["text", "structured_json", "tool_calls", "vision_input", "image_generation"],
            recommended_role="brain_plus_optional_image_driver",
            missing_capabilities=["video_generation_may_require_separate_video_api_or_driver"],
            notes=[
                "May be used as the image driver when image generation is configured.",
                "Still must return assets through AssetManifest.",
            ],
        ),
        "fal": ModelCapabilityProfile(
            provider="fal",
            label="FAL media driver",
            capabilities=["image_generation", "image_edit", "video_generation", "async_webhook", "cost_estimate"],
            recommended_role="media_driver_not_ai_ceo_brain",
            missing_capabilities=["commerce_reasoning", "listing_policy_judgment"],
            notes=[
                "Use as a replaceable media execution driver.",
                "Do not expose FAL as the Jiejing product identity.",
            ],
        ),
        "runway": ModelCapabilityProfile(
            provider="runway",
            label="Runway-style video driver",
            capabilities=["video_generation", "image_edit", "async_webhook", "cost_estimate"],
            recommended_role="video_driver_not_workflow_owner",
            missing_capabilities=["commerce_reasoning", "platform_listing_validation"],
            notes=["Useful for video generation after the asset brief and product facts are ready."],
        ),
        "merchant_upload": ModelCapabilityProfile(
            provider="merchant_upload",
            label="Merchant uploaded assets",
            capabilities=["vision_input", "commercial_rights_metadata"],
            recommended_role="source_material",
            missing_capabilities=["text", "image_generation", "video_generation"],
            notes=["Uploaded assets still need manifest, rights, and fact consistency review."],
        ),
        "generic_text_model": ModelCapabilityProfile(
            provider="generic_text_model",
            label="Generic text model",
            capabilities=["text", "structured_json"],
            recommended_role="brain_planner_only",
            missing_capabilities=["vision_input", "image_generation", "image_edit", "video_generation", "voice", "tool_calls"],
            notes=["Use for planning and review; route media generation to configured media drivers."],
        ),
    }


def _creative_job_spec() -> CreativeJobSpec:
    return CreativeJobSpec(
        job_type="eBay_listing_asset_package",
        product_facts_required=[
            "product_identity",
            "confirmed_dimensions_or_pending_label",
            "confirmed_material_or_pending_label",
            "allowed_claims",
            "forbidden_claims",
            "reference_images_or_source_notes",
            "target_marketplace_rules",
        ],
        output_assets=[
            "main_white_background_image",
            "lifestyle_scene_image",
            "detail_page_or_infographic",
            "dimension_image",
            "video_cover",
            "short_product_video_or_script",
        ],
        review_gates=[
            "fact_consistency_review",
            "commercial_use_rights_review",
            "platform_image_video_policy_review",
            "no_unverified_claims_review",
            "listing_use_approval",
        ],
        blocked_claims=[
            "unverified_material",
            "unverified_certification",
            "medical_or_performance_claim_without_source",
            "fake_testimonial",
            "brand_or_person_likeness_without_rights",
        ],
    )


def _routing_decision(
    profile: ModelCapabilityProfile,
    *,
    media_provider: str,
    configured_media: dict[str, bool],
) -> dict[str, Any]:
    can_image = "image_generation" in profile.capabilities and configured_media.get("image")
    can_video = "video_generation" in profile.capabilities and configured_media.get("video")
    image_driver = profile.provider if can_image else _configured_driver(media_provider, configured_media, "image")
    video_driver = profile.provider if can_video else _configured_driver(media_provider, configured_media, "video")
    return {
        "brain_provider": profile.provider,
        "brain_handles": ["merchant_intent", "asset_brief", "prompt_pack", "shot_list", "claim_review"],
        "image_driver": image_driver or "blocked_missing_image_provider",
        "video_driver": video_driver or "brief_or_cover_only_until_video_provider_ready",
        "voice_driver": _configured_driver(media_provider, configured_media, "voice") or "script_only_until_voice_provider_ready",
        "uses_single_asset_manifest": True,
        "merchant_should_not_choose_internal_tool": True,
        "fallback_when_text_only_model": [
            "generate_asset_brief",
            "generate_prompts_and_shot_list",
            "queue_media_asset_generation_with_configured_driver",
            "return_manifest_for_review",
        ],
    }


def _configured_driver(media_provider: str, configured_media: dict[str, bool], kind: str) -> str:
    if not configured_media.get(kind):
        return ""
    provider = _normalize_provider(media_provider)
    if provider:
        return provider
    return "configured_media_provider"


def _normalize_provider(provider: str) -> str:
    normalized = str(provider or "").strip().lower().replace("-", "_")
    aliases = {
        "deepseek_v4": "deepseek",
        "deepseek_v4_pro": "deepseek",
        "gpt": "openai",
        "gpt_image": "openai",
        "openai_responses": "openai",
        "fal_ai": "fal",
        "fal_run": "fal",
        "uploaded": "merchant_upload",
        "upload": "merchant_upload",
    }
    return aliases.get(normalized, normalized)
