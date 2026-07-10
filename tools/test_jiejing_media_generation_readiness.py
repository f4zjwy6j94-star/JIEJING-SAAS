from __future__ import annotations

import json
import os
import sys
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.readiness import _public_media_generation_status


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
    if live_ready.get("live_video_generation_enabled") is not True:
        raise AssertionError("live video generation should be enabled only when the video gate is also ready")
    if "unit-test-secret" in json.dumps(live_ready, ensure_ascii=False):
        raise AssertionError("live media readiness leaked the credential")

    print("PASS jiejing_media_generation_readiness")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
