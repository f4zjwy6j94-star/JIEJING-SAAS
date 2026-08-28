from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_runtime.media_generation import MediaGenerationAdapter, MediaGenerationConfig


@contextmanager
def patched_env(**values: str | None):
    previous = {key: os.environ.get(key) for key in values}
    try:
        for key, value in values.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def main() -> int:
    app_html = (ROOT / "app.html").read_text(encoding="utf-8")
    app_js = (ROOT / "app.js").read_text(encoding="utf-8")

    required_html = (
        'id="mediaGenerationTierSelect"',
        "草稿图 · 20 点/张",
        "标准图（推荐） · 80 点/张",
        "高清图（最终候选） · 250 点/张",
        'id="mediaGenerationPointQuote"',
        "商品事实锁定",
        "默认开启，不可关闭",
        "6 秒产品展示视频",
        "10 秒产品展示视频",
    )
    for marker in required_html:
        if marker not in app_html:
            raise AssertionError(f"media quality UI is missing {marker}")
    count_select = app_html.split('id="mediaCountSelect"', 1)[1].split("</select>", 1)[0]
    tier_select = app_html.split('id="mediaGenerationTierSelect"', 1)[1].split("</select>", 1)[0]
    if '<option selected>1 张</option>' not in count_select or '<option selected>4 张</option>' in count_select:
        raise AssertionError("first media run must default to one image instead of silently quoting four")
    if '<option selected>草稿图 · 20 点/张</option>' not in tier_select or '<option selected>标准图（推荐） · 80 点/张</option>' in tier_select:
        raise AssertionError("first media run must default to the low-cost draft tier")
    for truthful_default in (
        '<strong id="mediaOutputStatus">1 张草稿 · 默认不生成视频</strong>',
        'data-media-template="standard" data-template-size="平台推荐自动匹配" data-template-count="1 张"',
        '<strong id="mediaChoiceCount">1 张 · 平台推荐自动匹配</strong>',
    ):
        if truthful_default not in app_html:
            raise AssertionError(f"media package summary must agree with the one-image draft default: {truthful_default}")
    if 'data-template-video="15 秒产品展示视频"' in app_html:
        raise AssertionError("image templates must not silently enable a video")
    if "<option>15 秒产品展示视频</option>" in app_html or "<option>30 秒产品短视频脚本</option>" in app_html:
        raise AssertionError("media UI must not promise unsupported video output")
    platform_select = app_html.split('id="mediaPlatformSelect"', 1)[1].split("</select>", 1)[0]
    for unsupported_platform in ("Amazon", "Shopify", "TikTok Shop", "通用独立站"):
        if unsupported_platform in platform_select:
            raise AssertionError(f"eBay-first media UI must hide unavailable platform preset: {unsupported_platform}")

    required_js = (
        'generation_tier: generationTier',
        'quality_mode: qualityMode',
        'fact_locks: factLocks',
        'facts_may_not_be_unlocked_by_merchant: true',
        'videoRequested = [6, 10].includes(videoDurationSeconds)',
        'videoIntent = "appearance_showcase"',
        '"camera_motion_only"',
        '"product_remains_static"',
        '"no_use_or_installation_demo"',
        'motion_and_usage_consistency_confirmed: evidence.motion_and_usage_consistency_confirmed',
        'readSaasMediaReviewEvidenceFromActiveModal(mediaJobId, hasVideoAsset)',
        'const groundingGate = saasMediaGenerationGroundingGate(productFacts, config)',
        'groundingGate.conceptOnly ? "concept_reference_only" : "reference_grounded_listing_draft"',
        "const mediaPointsByGenerationTier = { draft: 20, standard: 80, high_quality: 250 }",
        'setText("#mediaGenerationPointQuote"',
        'if (/草稿|快速|低成本/.test(String(value))) return "draft"',
        "function saasMediaAssetJobRequestedImageCount",
        "const plannedCount = saasMediaAssetJobRequestedImageCount(manifestJob || {}, config.count)",
        'asset.duration_seconds || "规格待确认"',
    )
    for marker in required_js:
        if marker not in app_js:
            raise AssertionError(f"media generation payload is missing {marker}")
    manifest_card_scope = app_js.split("function saasMediaManifestAssetCards", 1)[1].split(
        "function saasMediaSourceImageForReview", 1
    )[0]
    if '|| "provider_returned"' in manifest_card_scope:
        raise AssertionError("merchant media cards must not expose an internal provider lifecycle code as dimensions")
    approval_block = app_js.split("async function approveLatestSaasMediaAssetJobForListingDraft", 1)[1].split(
        "async function retrySaasMediaAssetJob", 1
    )[0]
    if "motion_and_usage_consistency_confirmed: true" in approval_block:
        raise AssertionError("media review must collect motion confirmation from the active checklist")
    active_media_sync = app_js.split("function syncSaasMediaProjectDraft", 1)[1].split("\nfunction ", 1)[0]
    if 'setText("#mediaGapTitle", gap)' not in active_media_sync:
        raise AssertionError("active media project must replace the legacy static gap with current product gaps")
    if "是否含香粒" in active_media_sync:
        raise AssertionError("active media project must not inherit incense-demo facts")
    for status_marker in ("概念参考图已返回 · 不可用于刊登", "真实素材已返回 · 等待审核", "素材正在后台生成"):
        if status_marker not in active_media_sync:
            raise AssertionError(f"media project refresh must derive current status from backend jobs: {status_marker}")
    if (
        'optionalSaasFetchFast("/media/capabilities"' not in app_js
        or "state.saasMediaCapabilities = mediaCapabilities.media_capabilities" not in app_js
    ):
        raise AssertionError("authenticated refresh must hydrate media capabilities before rendering the workshop")

    adapter = MediaGenerationAdapter()
    grounded = MediaGenerationConfig(
        product="foldable silicone drying mat",
        provider="fal",
        api_key="unit-test-only",
        image_quality="high",
        image_count=2,
        image_sizes=["1600x1600"],
        reference_image_url="https://cdn.example.test/jiejing/source.jpg",
    )
    with patched_env(JIEJING_FAL_IMAGE_MODEL=None, JIEJING_FAL_VIDEO_MODEL=None):
        image_connection = adapter._resolve_connection(grounded, "image")
        video_connection = adapter._resolve_connection(grounded, "video")
    if image_connection.get("model") != "openai/gpt-image-2/edit":
        raise AssertionError(f"grounded FAL generation must use the edit route: {image_connection}")
    image_payload = adapter._image_payload(grounded, provider="fal", model=image_connection["model"])
    if image_payload.get("quality") != "high":
        raise AssertionError(f"merchant quality tier must reach the FAL payload: {image_payload}")
    if image_payload.get("image_urls") != [grounded.reference_image_url]:
        raise AssertionError(f"grounded FAL generation must receive the reference image: {image_payload}")
    custom_text_model_config = MediaGenerationConfig(
        product=grounded.product,
        provider="fal",
        api_key="unit-test-only",
        image_model="custom/text-only-image-model",
        reference_image_url=grounded.reference_image_url,
    )
    custom_text_connection = adapter._resolve_connection(custom_text_model_config, "image")
    if custom_text_connection.get("model") != "openai/gpt-image-2/edit":
        raise AssertionError("grounded requests must not use a text-only image model that ignores the merchant source image")
    if video_connection.get("model") != "fal-ai/minimax/hailuo-2.3/standard/image-to-video":
        raise AssertionError(f"video driver must use the currently supported Hailuo route: {video_connection}")
    with patched_env(JIEJING_FAL_VIDEO_MODEL="fal-ai/minimax/video-01/image-to-video"):
        migrated_video_connection = adapter._resolve_connection(grounded, "video")
    if migrated_video_connection.get("model") != "fal-ai/minimax/hailuo-2.3/standard/image-to-video":
        raise AssertionError("legacy staging video model must migrate to the supported Hailuo route")
    if adapter._should_generate_video(grounded):
        raise AssertionError("a reference image alone must never trigger a paid video request")

    video_payload = adapter._video_payload(
        MediaGenerationConfig(
            product=grounded.product,
            provider="fal",
            reference_image_url=grounded.reference_image_url,
            video_prompt="[Push in] Preserve the product and use subtle motion.",
            video_duration_seconds=10,
        ),
        provider="fal",
        model=video_connection["model"],
    )
    if video_payload.get("duration") != "10" or video_payload.get("image_url") != grounded.reference_image_url:
        raise AssertionError(f"video duration and first frame must reach the FAL payload: {video_payload}")
    if not adapter._should_generate_video(
        MediaGenerationConfig(product=grounded.product, video_prompt="Create a reviewed 10-second product demo.")
    ):
        raise AssertionError("an explicit video prompt must enable video generation")

    print("PASS jiejing_media_quality_control")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
