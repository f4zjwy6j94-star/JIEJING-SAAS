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
    configs = []
    force_image_only = False

    def generate(self, config):
        self.configs.append(config)
        assets = [
            {
                "asset_id": "fake-main-01",
                "asset_type": "product_image",
                "url": "https://cdn.example.test/jiejing/fake-main-01.jpg",
                "dimensions": "1600x1600",
                "commercial_use_status": "needs_rights_review",
                "status": "generated",
            }
        ]
        if config.video_prompt and not self.force_image_only:
            assets.append(
                {
                    "asset_id": "fake-video-01",
                    "asset_type": "product_video",
                    "url": "https://cdn.example.test/jiejing/fake-video-01.mp4",
                    "duration_seconds": 20,
                    "commercial_use_status": "needs_rights_review",
                    "status": "generated",
                }
            )
        return {
            "status": "ready",
            "source_type": "media_provider",
            "product": config.product,
            "provider": "fake-provider",
            "assets": assets,
            "provider_status": {
                "credential_present": True,
                "secret_exposed": False,
            },
            "secret_exposed": False,
        }


def media_job_body(*, live_requested: bool = True, video_requested: bool = True) -> dict:
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
                "reference_images": ["https://cdn.example.test/jiejing/source-mat.jpg"],
            },
            "reference_image_url": "https://cdn.example.test/jiejing/source-mat.jpg",
            "image_count": 2,
            "image_sizes": ["1600x1600"],
            "scene_types": ["white_background", "detail_page"],
            **({"video_script": "15 second product demo script"} if video_requested else {}),
            "video_generation_requested": video_requested,
            "live_provider_requested": live_requested,
            "media_provider": "fal",
        },
        "run_mode": "local_worker_now",
    }


def main() -> int:
    app_js = (ROOT / "app.js").read_text(encoding="utf-8")
    if "function saasMediaAssetJobIsConceptOnly" not in app_js:
        raise AssertionError("frontend must identify concept-only media jobs")
    if "manifest.length > 0 && !hasGroundedReferenceImage" not in app_js:
        raise AssertionError("frontend must classify legacy ungrounded media jobs as concept-only")
    if "概念参考图不可用于刊登" not in app_js:
        raise AssertionError("frontend must label concept-only media before merchant review")
    if "概念参考，不能通过 Listing 审核" not in app_js:
        raise AssertionError("frontend must block concept-only Listing approval with merchant-facing guidance")
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

        concept_body = media_job_body(video_requested=False)
        concept_body["inputs"]["product_facts"].pop("reference_images", None)
        concept_body["inputs"].pop("reference_image_url", None)
        concept_body["inputs"]["creative_job_spec"]["output_safety_mode"] = "concept_reference_only"
        with patched_env(JIEJING_MEDIA_LIVE_PROVIDER_ENABLED="true", JIEJING_MEDIA_LIVE_VIDEO_ENABLED="false"):
            concept = ProviderJobRunner().run(
                company_id="co_test",
                store_id="store_test",
                user_id="user_test",
                task_id="task_test_concept",
                job_id="job_test_concept",
                job_body=concept_body,
            )
        concept_manifest = concept.get("output_packet", {}).get("asset_manifest", [])
        if not concept_manifest or concept_manifest[0].get("asset_type") != "concept_reference_image":
            raise AssertionError(f"ungrounded generation must remain concept-only: {concept_manifest}")
        if concept_manifest[0].get("listing_use_status") != "concept_only_not_eligible_for_listing":
            raise AssertionError("concept-only media must never be Listing eligible")
        if "No text, letters, numbers" not in FakeMediaGenerationAdapter.configs[-1].image_prompt:
            raise AssertionError("concept generation prompt must prohibit text and unsupported labels")

        with patched_env(JIEJING_MEDIA_LIVE_PROVIDER_ENABLED="true", JIEJING_MEDIA_LIVE_VIDEO_ENABLED="true"):
            image_only = ProviderJobRunner().run(
                company_id="co_test",
                store_id="store_test",
                user_id="user_test",
                task_id="task_test_image_only",
                job_id="job_test_image_only",
                job_body=media_job_body(video_requested=False),
            )
        if image_only.get("status") != "completed_live_media_provider":
            raise AssertionError(f"image-only media job must not require a video script: {image_only}")
        image_only_manifest = image_only.get("output_packet", {}).get("asset_manifest", [])
        if len(image_only_manifest) != 1 or image_only_manifest[0].get("asset_type") != "product_image":
            raise AssertionError(f"image-only media job returned the wrong manifest: {image_only_manifest}")

        FakeMediaGenerationAdapter.force_image_only = True
        with patched_env(JIEJING_MEDIA_LIVE_PROVIDER_ENABLED="true", JIEJING_MEDIA_LIVE_VIDEO_ENABLED="true"):
            partial_video = ProviderJobRunner().run(
                company_id="co_test",
                store_id="store_test",
                user_id="user_test",
                task_id="task_test_partial_video",
                job_id="job_test_partial_video",
                job_body=media_job_body(video_requested=True),
            )
        FakeMediaGenerationAdapter.force_image_only = False
        if partial_video.get("status") != "partial_live_media_provider":
            raise AssertionError(f"missing requested video must not be reported as complete: {partial_video}")
        if "video_provider_no_asset_returned" not in partial_video.get("missing_inputs", []):
            raise AssertionError("partial video result must identify the missing requested output")
        partial_status = partial_video.get("output_packet", {}).get("live_media_provider_status", {})
        if partial_status.get("video_requested") is not True or partial_status.get("video_asset_returned") is not False:
            raise AssertionError(f"partial video status must remain explicit: {partial_status}")

        video_without_script_body = media_job_body(video_requested=True)
        video_without_script_body["inputs"].pop("video_script", None)
        with patched_env(JIEJING_MEDIA_LIVE_PROVIDER_ENABLED="true", JIEJING_MEDIA_LIVE_VIDEO_ENABLED="true"):
            video_without_script = ProviderJobRunner().run(
                company_id="co_test",
                store_id="store_test",
                user_id="user_test",
                task_id="task_test_video_missing_script",
                job_id="job_test_video_missing_script",
                job_body=video_without_script_body,
            )
        if video_without_script.get("status") != "blocked_missing_input" or "video_script" not in video_without_script.get("missing_inputs", []):
            raise AssertionError("video generation must still require an explicit video script")

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
        FakeMediaGenerationAdapter.force_image_only = False
        runner_module.MediaGenerationAdapter = original_adapter


if __name__ == "__main__":
    raise SystemExit(main())
