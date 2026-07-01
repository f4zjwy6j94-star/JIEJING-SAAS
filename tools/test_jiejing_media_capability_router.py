#!/usr/bin/env python3
"""Regression for provider-neutral Jiejing media capability routing."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_runtime.media_capability_router import build_media_capability_router  # noqa: E402


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    deepseek = build_media_capability_router(preferred_model_provider="deepseek")
    if deepseek.get("mode") != "capability_router_no_generation_no_provider_call":
        return fail("media router must be read-only")
    if deepseek.get("selected_model_role") != "brain_planner_prompt_writer_review_rules":
        return fail("DeepSeek should be treated as planning/review brain")
    if deepseek.get("routing_decision", {}).get("image_driver") != "blocked_missing_image_provider":
        return fail("DeepSeek must not be assumed to generate images")
    if deepseek.get("routing_decision", {}).get("video_driver") != "brief_or_cover_only_until_video_provider_ready":
        return fail("DeepSeek must not be assumed to generate video")
    if "return_manifest_for_review" not in deepseek.get("routing_decision", {}).get("fallback_when_text_only_model", []):
        return fail("text-only model fallback must still return a manifest for review")

    openai = build_media_capability_router(
        preferred_model_provider="openai",
        media_provider="openai",
        image_provider_configured=True,
    )
    if openai.get("routing_decision", {}).get("image_driver") != "openai":
        return fail("OpenAI can be selected as image driver only when configured")
    if openai.get("asset_contract", {}).get("single_output_contract") != "AssetManifest":
        return fail("OpenAI image output must still use AssetManifest")

    fal = build_media_capability_router(
        preferred_model_provider="deepseek",
        media_provider="fal",
        image_provider_configured=True,
        video_provider_configured=True,
    )
    if fal.get("routing_decision", {}).get("brain_provider") != "deepseek":
        return fail("media driver must not replace the merchant model brain")
    if fal.get("routing_decision", {}).get("image_driver") != "fal" or fal.get("routing_decision", {}).get("video_driver") != "fal":
        return fail("configured FAL should be a replaceable media driver")

    for packet in (deepseek, openai, fal):
        if packet.get("secret_exposed") is not False:
            return fail("media router must not expose secrets")
        safety = packet.get("safety") if isinstance(packet.get("safety"), dict) else {}
        for marker in (
            "calls_model_api",
            "calls_image_provider",
            "calls_video_provider",
            "triggers_real_platform_write",
            "creates_checkout_session",
            "frontend_gets_model_api_key",
            "frontend_gets_media_api_key",
            "runtime_gets_raw_secret",
            "secret_exposed",
        ):
            if safety.get(marker) is not False:
                return fail(f"media router unsafe flag should be false: {marker}")

    print("PASS jiejing_media_capability_router")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
