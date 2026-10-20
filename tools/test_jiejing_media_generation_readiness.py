from __future__ import annotations

import json
import os
import sys
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.readiness import _public_media_generation_status, build_media_generation_capability_status


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


def assert_common_guardrails(status: dict) -> None:
    if status.get("asset_manifest_required") is not True:
        raise AssertionError("media readiness must require AssetManifest before claiming generated assets")
    if status.get("asset_review_required") is not True:
        raise AssertionError("media readiness must require asset review")
    if status.get("human_review_required_before_listing") is not True:
        raise AssertionError("media readiness must require human review before Listing use")
    if status.get("spend_now_allowed") is not False:
        raise AssertionError("media readiness must not allow immediate spend")
    if status.get("frontend_gets_media_api_key") is not False:
        raise AssertionError("frontend must not receive media API keys")
    if status.get("runtime_gets_raw_secret") is not False:
        raise AssertionError("runtime must not receive raw media secrets")
    if status.get("raw_provider_response_stored") is not False:
        raise AssertionError("raw media provider responses must not be stored")
    if status.get("secret_exposed") is not False:
        raise AssertionError("media readiness must not expose secrets")


def main() -> int:
    base_env = {
        "JIEJING_ENABLE_HERMES_WSL_SECRET_LOOKUP": "false",
        "JIEJING_MEDIA_GENERATION_PROVIDER": "fal",
        "JIEJING_MEDIA_LIVE_PROVIDER_ENABLED": "false",
        "JIEJING_MEDIA_LIVE_VIDEO_ENABLED": "false",
        "FAL_KEY": None,
        "FAL_KEY_ID": None,
        "FAL_KEY_SECRET": None,
        "JIEJING_FAL_KEY": None,
        "JIEJING_FAL_KEY_ID": None,
        "JIEJING_FAL_KEY_SECRET": None,
        "JIEJING_MEDIA_GENERATION_API_KEY": None,
        "OPENAI_API_KEY": None,
    }
    with patched_env(**base_env):
        missing = _public_media_generation_status()
    assert_common_guardrails(missing)
    if missing.get("configured") is not False:
        raise AssertionError(f"missing media driver should not be configured: {missing}")
    if missing.get("status") != "dry_run_review_chain_ready_missing_media_driver":
        raise AssertionError(f"missing media driver status should stay honest: {missing}")
    if missing.get("live_provider_calls_allowed") is not False:
        raise AssertionError("missing media driver cannot allow live calls")

    with patched_env(**{**base_env, "FAL_KEY": "unit-test-secret", "JIEJING_MEDIA_LIVE_PROVIDER_ENABLED": "false"}):
        configured_disabled = _public_media_generation_status()
    assert_common_guardrails(configured_disabled)
    if configured_disabled.get("configured") is not True:
        raise AssertionError("configured media driver should be detected")
    if configured_disabled.get("status") != "dry_run_review_chain_ready_live_generation_disabled":
        raise AssertionError(f"configured-but-disabled status should be explicit: {configured_disabled}")
    if "unit-test-secret" in json.dumps(configured_disabled, ensure_ascii=False):
        raise AssertionError("media readiness leaked the credential")

    with patched_env(
        **{
            **base_env,
            "FAL_KEY": "unit-test-secret",
            "JIEJING_MEDIA_LIVE_PROVIDER_ENABLED": "true",
            "JIEJING_MEDIA_LIVE_VIDEO_ENABLED": "true",
        }
    ):
        live_ready = _public_media_generation_status()
    assert_common_guardrails(live_ready)
    if live_ready.get("status") != "live_generation_ready_waiting_asset_review":
        raise AssertionError(f"live media readiness should still wait for review: {live_ready}")
    if live_ready.get("live_image_generation_enabled") is not True:
        raise AssertionError("live image generation should be enabled when driver and backend gate are ready")
    if live_ready.get("live_video_generation_enabled") is not False:
        raise AssertionError("configured video driver and live switches must not bypass unapproved video pricing")
    if live_ready.get("video_pricing_approved") is not False:
        raise AssertionError("unapproved video pricing must be projected separately from provider configuration")
    if live_ready.get("video_generation_blocked_by") != ["video_media_points_pricing_not_approved"]:
        raise AssertionError("video capability must explain the same pricing block enforced before queueing")
    if "视频生成暂未开放" not in live_ready.get("customer_visible_summary", ""):
        raise AssertionError("the merchant summary must not imply that configured video is available")
    if "unit-test-secret" in json.dumps(live_ready, ensure_ascii=False):
        raise AssertionError("live media readiness leaked the credential")

    # Public capability projection must preserve image behavior in every switch
    # combination without turning configured-but-unpriced video into readiness.
    for configured in (False, True):
        for live_enabled in (False, True):
            for video_enabled in (False, True):
                with patched_env(
                    **{
                        **base_env,
                        "FAL_KEY": "unit-test-secret" if configured else None,
                        "JIEJING_MEDIA_LIVE_PROVIDER_ENABLED": str(live_enabled),
                        "JIEJING_MEDIA_LIVE_VIDEO_ENABLED": str(video_enabled),
                    }
                ):
                    capability = build_media_generation_capability_status()
                    legacy_projection = _public_media_generation_status()
                assert_common_guardrails(capability)
                if capability != legacy_projection:
                    raise AssertionError("legacy readiness and merchant capability projections must agree")
                if capability.get("live_image_generation_enabled") is not (configured and live_enabled):
                    raise AssertionError("video pricing correction must not change image-generation behavior")
                if capability.get("live_provider_calls_allowed") is not (configured and live_enabled):
                    raise AssertionError("existing image/provider gates must remain unchanged")
                if capability.get("live_video_generation_enabled") is not False:
                    raise AssertionError("no switch combination may make unpriced video generation available")
                if capability.get("video_pricing_approved") is not False:
                    raise AssertionError("provider configuration is not a pricing approval")
                expected_blockers = []
                if not configured:
                    expected_blockers.append("media_provider_not_configured")
                if not live_enabled:
                    expected_blockers.append("live_media_generation_disabled")
                if not video_enabled:
                    expected_blockers.append("video_provider_disabled")
                expected_blockers.append("video_media_points_pricing_not_approved")
                if capability.get("video_generation_blocked_by") != expected_blockers:
                    raise AssertionError("video projection must preserve each independent admission blocker")
                if capability.get("contract_version") != "2026-07-05-media-generation-readiness":
                    raise AssertionError("existing capability consumers must retain the versioned projection")
                if "unit-test-secret" in json.dumps(capability, ensure_ascii=False):
                    raise AssertionError("capability matrix leaked the test credential")

    print("PASS jiejing_media_generation_readiness")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
