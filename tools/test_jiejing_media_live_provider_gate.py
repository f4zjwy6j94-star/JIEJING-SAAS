from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import jiejing_saas.provider_job_runner as runner_module
from jiejing_saas.provider_job_runner import ProviderJobRunner


@contextmanager
def patched_env(**values: str):
    previous = {key: os.environ.get(key) for key in values}
    try:
        for key, value in values.items():
            os.environ[key] = value
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


class FakeMediaGenerationAdapter:
    def generate(self, config):
        return {
            "status": "ready",
            "source_type": "media_provider",
            "product": config.product,
            "provider": "fake-provider",
            "assets": [
                {
                    "asset_id": "fake-main-01",
                    "asset_type": "product_image",
                    "url": "https://cdn.example.test/jiejing/fake-main-01.jpg",
                    "dimensions": "1600x1600",
                    "commercial_use_status": "needs_rights_review",
                    "status": "generated",
                },
                {
                    "asset_id": "fake-video-01",
                    "asset_type": "product_video",
                    "url": "https://cdn.example.test/jiejing/fake-video-01.mp4",
                    "duration_seconds": 20,
                    "commercial_use_status": "needs_rights_review",
                    "status": "generated",
                },
            ],
            "provider_status": {
                "credential_present": True,
                "secret_exposed": False,
            },
            "secret_exposed": False,
        }


def media_job_body(*, live_requested: bool = True) -> dict:
    return {
        "provider_job_key": "media.asset_generation",
        "inputs": {
            "creative_job_spec": {
                "job_type": "eBay_listing_asset_package",
                "blocked_claims": ["unverified_certification"],
            },
            "product_facts": {
                "product": "foldable silicone drying mat",
                "forbidden_claims": ["medical"],
                "supplier_facts": {"material": "silicone", "package_dimensions_cm": {"length": 30, "width": 8, "height": 8}},
                "target_marketplace_rules": {"platform": "ebay", "marketplace": "EBAY_US"},
            },
            "image_count": 2,
            "image_sizes": ["1600x1600"],
            "scene_types": ["white_background", "detail_page"],
            "video_script": "15 second product demo script",
            "video_generation_requested": True,
            "live_provider_requested": live_requested,
            "media_provider": "fal",
        },
        "run_mode": "local_worker_now",
    }


def main() -> int:
    original_adapter = runner_module.MediaGenerationAdapter
    try:
        runner_module.MediaGenerationAdapter = FakeMediaGenerationAdapter
        with patched_env(JIEJING_MEDIA_LIVE_PROVIDER_ENABLED="true", JIEJING_MEDIA_LIVE_VIDEO_ENABLED="true"):
            live = ProviderJobRunner().run(
                company_id="co_test",
                store_id="store_test",
                user_id="user_test",
                task_id="task_test",
                job_id="job_test",
                job_body=media_job_body(),
            )
        if live.get("status") != "completed_live_media_provider":
            raise AssertionError(f"live media provider should complete through backend gate: {live}")
        if live.get("safety", {}).get("live_provider_called") is not True:
            raise AssertionError("live media safety marker should be true")
        if live.get("safety", {}).get("spend_now_allowed") is not False:
            raise AssertionError("live media provider result must keep spend_now_allowed=false")
        packet = live.get("output_packet", {})
        manifest = packet.get("asset_manifest") if isinstance(packet.get("asset_manifest"), list) else []
        if len(manifest) != 2 or not all(item.get("url_or_file_path", "").startswith("https://cdn.example.test/") for item in manifest):
            raise AssertionError(f"live media assets should be normalized into AssetManifest: {manifest}")
        if packet.get("asset_manifest_validation", {}).get("status") != "manifest_ready":
            raise AssertionError("live media AssetManifest should validate before review")
        if packet.get("asset_review", {}).get("listing_use_status") != "not_ready_for_listing_until_review":
            raise AssertionError("live media assets must still wait for Listing review")
        if live.get("secret_exposed") is not False:
            raise AssertionError("live media provider branch must not expose secrets")

        with patched_env(JIEJING_MEDIA_LIVE_PROVIDER_ENABLED="false", JIEJING_MEDIA_LIVE_VIDEO_ENABLED="false"):
            dry = ProviderJobRunner().run(
                company_id="co_test",
                store_id="store_test",
                user_id="user_test",
                task_id="task_test_dry",
                job_id="job_test_dry",
                job_body=media_job_body(),
            )
        if dry.get("status") != "completed_dry_run":
            raise AssertionError("media provider must remain dry-run when backend live gate is disabled")
        if dry.get("safety", {}).get("live_provider_called") is not False:
            raise AssertionError("dry-run media branch must keep live_provider_called=false")
        if dry.get("safety", {}).get("spend_now_allowed") is not False:
            raise AssertionError("dry-run media branch must keep spend_now_allowed=false")
        print("PASS jiejing_media_live_provider_gate")
        return 0
    finally:
        runner_module.MediaGenerationAdapter = original_adapter


if __name__ == "__main__":
    raise SystemExit(main())
