from __future__ import annotations

import base64
import json
import os
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_runtime.media_generation import MediaGenerationAdapter, MediaGenerationConfig
from jiejing_saas.provider_job_runner import ProviderJobRunner
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


def media_job_body() -> dict:
    return {
        "provider_job_key": "media.asset_generation",
        "inputs": {
            "creative_job_spec": {
                "job_type": "eBay_listing_asset_package",
                "blocked_claims": ["unverified_certification", "medical_claim"],
            },
            "product_facts": {
                "product": "foldable silicone drying mat",
                "forbidden_claims": ["medical"],
                "supplier_facts": {
                    "material": "silicone",
                    "package_dimensions_cm": {"length": 30, "width": 8, "height": 8},
                },
                "target_marketplace_rules": {"platform": "ebay", "marketplace": "EBAY_US"},
            },
            "image_count": 1,
            "image_sizes": ["1:1"],
            "scene_types": ["white_background"],
            "video_script": "No video generation requested; retain a short Listing video script placeholder only.",
            "live_provider_requested": True,
            "media_provider": "provider_neutral",
        },
        "run_mode": "local_worker_now",
    }


def main() -> int:
    fake_image = base64.b64encode(b"fake-openai-image-bytes").decode("ascii")
    captured: dict[str, object] = {}
    original_post = MediaGenerationAdapter._post_json

    def fake_post(self, endpoint, authorization, payload, timeout_seconds, proxy_url):  # noqa: ANN001
        captured["endpoint"] = endpoint
        captured["authorization"] = authorization
        captured["payload"] = payload
        captured["timeout_seconds"] = timeout_seconds
        captured["proxy_url"] = proxy_url
        return {"data": [{"b64_json": fake_image, "revised_prompt": "safe product image"}]}

    try:
        MediaGenerationAdapter._post_json = fake_post
        with tempfile.TemporaryDirectory() as tmpdir:
            with patched_env(
                JIEJING_ENABLE_HERMES_WSL_SECRET_LOOKUP="false",
                JIEJING_MEDIA_GENERATION_PROVIDER="openai",
                JIEJING_MEDIA_OPENAI_API_KEY="unit-test-openai-secret",
                OPENAI_API_KEY=None,
                JIEJING_MEDIA_GENERATED_ASSET_DIR=tmpdir,
                JIEJING_MEDIA_LIVE_PROVIDER_ENABLED="true",
                JIEJING_MEDIA_LIVE_VIDEO_ENABLED="false",
            ):
                readiness = _public_media_generation_status()
                if readiness.get("configured") is not True:
                    raise AssertionError(f"OpenAI media provider should be configured without a custom endpoint: {readiness}")
                if readiness.get("live_image_generation_enabled") is not True:
                    raise AssertionError(f"OpenAI live image gate should be ready when enabled: {readiness}")
                if "unit-test-openai-secret" in json.dumps(readiness, ensure_ascii=False):
                    raise AssertionError("readiness leaked OpenAI media credential")

                snapshot = MediaGenerationAdapter().generate(
                    MediaGenerationConfig(
                        product="foldable silicone drying mat",
                        image_prompt="Generate one eBay-safe white background product image.",
                        image_count=1,
                        image_sizes=["1:1"],
                        live_enabled=True,
                    )
                )
                if snapshot.get("status") != "ready":
                    raise AssertionError(f"OpenAI image snapshot should be ready: {snapshot}")
                assets = snapshot.get("assets") if isinstance(snapshot.get("assets"), list) else []
                if len(assets) != 1:
                    raise AssertionError(f"OpenAI image response should normalize one asset: {snapshot}")
                file_path = Path(str(assets[0].get("file_path") or ""))
                if not file_path.exists() or file_path.parent != Path(tmpdir):
                    raise AssertionError(f"OpenAI b64 asset should be stored in the configured backend dir: {assets}")
                if captured.get("endpoint") != "https://api.openai.com/v1/images/generations":
                    raise AssertionError(f"OpenAI image endpoint should default safely: {captured}")
                if captured.get("authorization") != "Bearer unit-test-openai-secret":
                    raise AssertionError("OpenAI media request should use backend bearer auth")
                payload = captured.get("payload") if isinstance(captured.get("payload"), dict) else {}
                if payload.get("model") != "gpt-image-1" or payload.get("size") != "1024x1024":
                    raise AssertionError(f"OpenAI image payload should use supported defaults: {payload}")
                if "unit-test-openai-secret" in json.dumps(payload, ensure_ascii=False):
                    raise AssertionError("OpenAI media payload leaked the credential")

                live = ProviderJobRunner().run(
                    company_id="co_test",
                    store_id="store_test",
                    user_id="user_test",
                    task_id="task_test",
                    job_id="job_test",
                    job_body=media_job_body(),
                )
                if live.get("status") != "completed_live_media_provider":
                    raise AssertionError(f"provider-neutral media job should resolve to configured OpenAI provider: {live}")
                packet = live.get("output_packet") if isinstance(live.get("output_packet"), dict) else {}
                if packet.get("asset_manifest_validation", {}).get("status") != "manifest_ready":
                    raise AssertionError(f"OpenAI live media result should produce a valid AssetManifest: {packet}")
                if live.get("safety", {}).get("live_provider_called") is not True:
                    raise AssertionError("OpenAI media job should mark live provider called")
                if "unit-test-openai-secret" in json.dumps(live, ensure_ascii=False):
                    raise AssertionError("OpenAI media provider output leaked the credential")
    finally:
        MediaGenerationAdapter._post_json = original_post

    print("PASS jiejing_media_openai_adapter")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
