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
        "快速样图（低成本）",
        "标准质量（推荐）",
        "精细质量（最终候选）",
        "商品事实锁定",
        "默认开启，不可关闭",
        "6 秒产品展示视频",
        "10 秒产品展示视频",
    )
    for marker in required_html:
        if marker not in app_html:
            raise AssertionError(f"media quality UI is missing {marker}")
    if 'data-template-video="15 秒产品展示视频"' in app_html:
        raise AssertionError("image templates must not silently enable a video")
    if "<option>15 秒产品展示视频</option>" in app_html or "<option>30 秒产品短视频脚本</option>" in app_html:
        raise AssertionError("media UI must not promise unsupported video output")

    required_js = (
        'generation_tier: generationTier',
        'quality_mode: qualityMode',
        'fact_locks: factLocks',
        'facts_may_not_be_unlocked_by_merchant: true',
        'videoRequested = [6, 10].includes(videoDurationSeconds)',
        'qualityMode !== "creative_exploration"',
    )
    for marker in required_js:
        if marker not in app_js:
            raise AssertionError(f"media generation payload is missing {marker}")
    if (
        'optionalSaasFetchFast("/readiness/product-saas"' not in app_js
        or "state.saasReadiness = coreReadiness.readiness" not in app_js
    ):
        raise AssertionError("authenticated refresh must hydrate media readiness before rendering the workshop")

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
