"""Offline public-runner -> real adapter -> provider-wire regression tests.

Only the external provider transport is replaced. No credentials, network,
production accounts or material points are used by these tests.
"""
from __future__ import annotations

import os
import re
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_runtime.media_generation import MediaGenerationAdapter
from jiejing_saas.provider_job_runner import ProviderJobRunner


def image_job(scene: str, *, count: int = 1, output_type: str = "只做场景图：家居 / 户外 / 使用场景") -> dict:
    return {
        "provider_job_key": "media.asset_generation",
        "run_mode": "local_worker_now",
        "inputs": {
            "creative_job_spec": {
                "job_type": "eBay_listing_asset_package",
                "output_type": output_type,
                "text_rule": "no_text_no_numbers_no_certifications",
                "quality_mode": "fidelity_first",
                "fact_locks": ["product_structure", "color", "material", "included_parts", "logo_and_brand_marks"],
                "blocked_claims": ["unverified_certification"],
            },
            "product_facts": {
                "product": "two-drawer desktop storage box",
                "allowed_claims": ["two visible blue drawers"],
                "forbidden_claims": ["unverified material or dimensions"],
                "material_pending_label": True,
                "dimensions_pending_label": True,
                "supplier_facts": {"confirmed_visible_features": ["two drawers", "two handles"]},
                "target_marketplace_rules": {"platform": "ebay", "marketplace": "EBAY_US"},
                "reference_images": ["https://cdn.example.test/scene-test/source.jpg"],
            },
            "reference_image_url": "https://cdn.example.test/scene-test/source.jpg",
            "image_count": count,
            "image_sizes": ["1600x1600"],
            "scene_types": [scene, output_type],
            "video_generation_requested": False,
            "generation_tier": "draft",
            "quality_mode": "fidelity_first",
            "commercial_rights_confirmed": True,
            "live_provider_requested": True,
            "media_provider": "fal",
        },
    }


def provider_outcome(job: dict) -> tuple[dict, list]:
    wire_requests = []

    def provider_wire(_adapter, endpoint, authorization, payload, timeout_seconds, proxy_url=""):
        # Synthetic response describes provider shape, not a real generated file.
        if not endpoint.endswith("/edit") or authorization != "Key synthetic-test-only":
            raise AssertionError("Unexpected provider identity in offline test")
        wire_requests.append(payload)
        return {"images": [{"url": "https://cdn.example.test/scene-test/result.jpg", "width": 1024, "height": 1024}]}

    with patch.dict(os.environ, {
        "JIEJING_MEDIA_LIVE_PROVIDER_ENABLED": "true",
        "JIEJING_MEDIA_LIVE_VIDEO_ENABLED": "false",
        "JIEJING_MEDIA_GENERATION_PROVIDER": "fal",
        "JIEJING_FAL_KEY": "synthetic-test-only",
        "JIEJING_ENABLE_HERMES_WSL_SECRET_LOOKUP": "false",
    }, clear=True), patch.object(MediaGenerationAdapter, "_post_json", provider_wire), \
            patch("socket.create_connection", side_effect=AssertionError("Network forbidden")), \
            patch("socket.socket.connect", side_effect=AssertionError("Network forbidden")):
        result = ProviderJobRunner().run(
            company_id="scene-company", store_id="scene-store", user_id="scene-owner",
            task_id="scene-task", job_id="scene-job", job_body=job,
        )
    return result, wire_requests


def provider_request(job: dict) -> dict:
    result, wire_requests = provider_outcome(job)
    if result["status"] != "completed_live_media_provider":
        raise AssertionError(f"Fixture did not reach real media path: {result['status']}, {result.get('missing_inputs')}")
    if len(wire_requests) != 1:
        raise AssertionError(f"Expected only one image request, got {len(wire_requests)}")
    return wire_requests[0]


class SceneDeliveryTests(unittest.TestCase):
    def test_reference_is_product_identity_not_a_fixed_photograph_to_cut_out(self):
        payload = provider_request(image_job("办公桌/收纳整理场景", count=4))
        prompt = payload["prompt"]
        self.assertIn("not merely cut out the original photo or replace its background", prompt)
        self.assertIn("new photographic composition", prompt)
        self.assertIn("different camera distances", prompt)
        self.assertIn("supported by the reference", prompt)
        self.assertIn("printed artwork and legible lettering", prompt)
        self.assertEqual(payload["num_images"],4)

    def test_selected_desk_scene_reaches_provider_without_plain_background_override(self):
        payload = provider_request(image_job("办公桌/收纳整理场景"))
        self.assertIn("办公桌/收纳整理场景", payload["prompt"])
        self.assertNotIn("Use a clean plain background", payload["prompt"])
        self.assertEqual(payload["num_images"], 1)
        self.assertEqual(payload["image_urls"], ["https://cdn.example.test/scene-test/source.jpg"])
        self.assertIn("Locked facts", payload["prompt"])
        self.assertIn("physical", payload["prompt"])

    def test_explicit_lifestyle_scene_is_not_overridden_by_package_main_image_label(self):
        payload = provider_request(image_job(
            "家居/礼品/使用场景", output_type="完整素材包：主图 + 场景图 + 详情页 + 尺寸图",
        ))
        self.assertIn("家居/礼品/使用场景", payload["prompt"])
        self.assertNotIn("including tables, trays", payload["prompt"])

    def test_white_background_keeps_single_main_image_and_product_protection(self):
        for scene in ("白底或浅灰背景", "white_background", "main_white_bg"):
            with self.subTest(scene=scene):
                payload = provider_request(image_job(scene))
                self.assertIn("exactly one coherent single-view", payload["prompt"])
                self.assertIn("including tables, trays", payload["prompt"])
                self.assertIn("Keep any base that is structurally part", payload["prompt"])
                self.assertIn("brand marks on the actual product unchanged", payload["prompt"])

    def test_four_scene_choices_produce_four_distinct_requests_without_extra_spend(self):
        scenes = ["家居/礼品/使用场景", "办公桌/收纳整理场景", "茶室/东方审美场景", "白底或浅灰背景"]
        prompts = []
        for scene in scenes:
            payload = provider_request(image_job(scene, count=4))
            prompts.append(payload["prompt"])
            self.assertEqual(payload["num_images"], 4)
            self.assertEqual(payload["quality"], "low")
            self.assertIn(scene, payload["prompt"])
            self.assertIn("Do not invent hidden geometry", payload["prompt"])
        self.assertEqual(len(set(prompts)), 4)

    def test_automatic_scene_does_not_turn_mixed_package_into_white_only(self):
        mixed = provider_request(image_job("按商品用途自动选择", output_type="完整素材包：主图 + 场景图 + 详情页 + 尺寸图"))
        primary = provider_request(image_job("按商品用途自动选择", output_type="只做 eBay 主图：白底 / 干净背景 / 主体清晰"))
        self.assertNotIn("including tables, trays", mixed["prompt"])
        self.assertIn("including tables, trays", primary["prompt"])

    def test_explicit_pixel_size_is_not_silently_downgraded_to_a_preset(self):
        for width, height in [(1600, 1600), (1200, 1200), (1200, 1600), (1600, 1200)]:
            with self.subTest(width=width, height=height):
                job = image_job("白底或浅灰背景")
                job["inputs"]["image_sizes"] = [f"{width}x{height}"]
                payload = provider_request(job)
                self.assertEqual(payload["image_size"], {"width": width, "height": height})

    def test_unsupported_explicit_size_fails_before_external_provider_spend(self):
        for size in ["1200x1500", "16:9 横版场景 1600×900", "-1600x1600", "1600x-1600",
                     "0x1600", "5000x5000", "64x64", "3840x800", "3200x3200"]:
            with self.subTest(size=size):
                job = image_job("办公桌/收纳整理场景")
                job["inputs"]["image_sizes"] = [size]
                result, wire_requests = provider_outcome(job)
                self.assertEqual(wire_requests, [])
                self.assertNotEqual(result["status"], "completed_live_media_provider")

    def test_every_size_offered_by_the_live_form_reaches_the_provider_exactly(self):
        html = (ROOT / "app.html").read_text(encoding="utf-8")
        choices = re.search(r'<select id="mediaSizeSelect">(.*?)</select>', html, re.S).group(1)
        labels = re.findall(r"<option[^>]*>([^<]*\d+×\d+)</option>", choices)
        self.assertGreaterEqual(len(set(labels)), 7)
        for label in labels:
            with self.subTest(label=label):
                width_text, height_text = re.search(r"(\d+)×(\d+)$", label).groups()
                width, height = int(width_text), int(height_text)
                job = image_job("办公桌/收纳整理场景")
                # The real form sends the full option label, not bare pixels.
                job["inputs"]["image_sizes"] = [label]
                payload = provider_request(job)
                self.assertEqual(payload["image_size"], {"width": width, "height": height})



if __name__ == "__main__":
    unittest.main()
