"""Creative and media capability profile for Jiejing Runtime.

This is not a media generator by itself. It defines the provider-neutral
contract Jiejing needs before connecting image, detail-page, voiceover, and
video tools. The goal is to let Jiejing gain first-class creative ability
without copying or depending on one closed product's UI or internals.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from typing import Any

from .media_generation import MediaGenerationAdapter


CREATIVE_PROFILE_VERSION = "2026-05-15.1"


@dataclass(slots=True)
class CreativeCapability:
    key: str
    label: str
    status: str
    owned_layer: str
    provider_needed: bool
    output_contract: list[str] = field(default_factory=list)
    safety_gate: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class CreativeCapabilityProfile:
    """Summarize design, image, and video capabilities for SaaS visibility."""

    def __init__(self) -> None:
        self.image_provider = os.environ.get("JIEJING_IMAGE_PROVIDER", "").strip()
        self.video_provider = os.environ.get("JIEJING_VIDEO_PROVIDER", "").strip()
        self.voice_provider = os.environ.get("JIEJING_VOICE_PROVIDER", "").strip()
        self.fal_status = MediaGenerationAdapter().provider_status("fal")

    def to_dict(self) -> dict[str, Any]:
        capabilities = [
            CreativeCapability(
                key="open_design_method",
                label="Open Design style exploration",
                status="owned_prompt_workflow_ready",
                owned_layer="Jiejing owns UI/creative direction prompts, variant review rules, and merchant-facing copy standards.",
                provider_needed=False,
                output_contract=["design brief", "layout variants", "critique checklist", "selected direction"],
                safety_gate=["No fake customer proof", "No copied closed-source product UI"],
            ),
            CreativeCapability(
                key="listing_asset_brief",
                label="Listing asset brief",
                status="ready",
                owned_layer="Asset Agent produces image plan, detail page plan, video script, and manifest requirements.",
                provider_needed=False,
                output_contract=["main image plan", "scene images", "detail page", "dimension image", "video script"],
                safety_gate=["Unknown product facts stay Pending", "Generated file claims require manifest"],
            ),
            CreativeCapability(
                key="product_image_generation",
                label="Product image generation",
                status="provider_configured" if self.image_provider or self.fal_status.get("configured") else "adapter_contract_ready",
                owned_layer="Jiejing owns prompts, sizes, claim guardrails, and asset manifest schema.",
                provider_needed=True,
                output_contract=["file path or URL", "asset type", "dimensions", "source prompt", "commercial-use status"],
                safety_gate=["No unsupported claims in images", "Supplier facts required for size/material claims"],
            ),
            CreativeCapability(
                key="detail_page_generation",
                label="Detail page image generation",
                status="provider_configured" if self.image_provider or self.fal_status.get("configured") else "adapter_contract_ready",
                owned_layer="Jiejing owns eBay detail-page structure: use scene, features, size, package, FAQ.",
                provider_needed=True,
                output_contract=["long image", "section map", "text overlay copy", "source facts used"],
                safety_gate=["No medical/performance exaggeration", "No invented certification"],
            ),
            CreativeCapability(
                key="product_video_generation",
                label="Product video generation",
                status="provider_configured" if self.video_provider or self.fal_status.get("configured") else "adapter_contract_ready",
                owned_layer="Jiejing owns shot list, script, subtitle, cover, and manifest schema.",
                provider_needed=True,
                output_contract=["video file", "cover image", "script", "subtitle file", "duration", "asset manifest"],
                safety_gate=["No fake testimonial", "No unsupported demo effect", "No real person likeness without rights"],
            ),
            CreativeCapability(
                key="voiceover_and_script",
                label="Voiceover script and narration",
                status="provider_configured" if self.voice_provider else "script_ready_provider_pending",
                owned_layer="Jiejing can generate product-safe scripts locally; audio rendering requires a voice provider.",
                provider_needed=True,
                output_contract=["hook", "selling script", "caption", "voice file if rendered"],
                safety_gate=["No deceptive claims", "No platform policy violation"],
            ),
        ]
        return {
            "profile_version": CREATIVE_PROFILE_VERSION,
            "configured_providers": {
                "image": bool(self.image_provider or self.fal_status.get("configured")),
                "video": bool(self.video_provider or self.fal_status.get("configured")),
                "voice": bool(self.voice_provider),
            },
            "provider_names": {
                "image": self.image_provider or ("fal" if self.fal_status.get("configured") else None),
                "video": self.video_provider or ("fal" if self.fal_status.get("configured") else None),
                "voice": self.voice_provider or None,
            },
            "provider_status": {
                "fal": self.fal_status,
            },
            "capabilities": [item.to_dict() for item in capabilities],
            "can_match_claude_or_open_design_style_workflows": True,
            "must_not_copy_closed_product_internals": True,
            "next_engineering_step": "Bind image/video/voice providers behind the asset manifest contract, then let Asset Agent request real media files.",
        }
