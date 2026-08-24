#!/usr/bin/env python3
"""Regression test for image -> FAL queue video -> AssetManifest chaining."""

from __future__ import annotations

import os
import struct
import sys
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_runtime.media_generation import MediaGenerationAdapter, MediaGenerationConfig, _mp4_duration_seconds


@contextmanager
def patched_env(**changes: str):
    previous = {key: os.environ.get(key) for key in changes}
    try:
        os.environ.update(changes)
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


class FakeFalAdapter(MediaGenerationAdapter):
    def __init__(self) -> None:
        self.queue_payload: dict[str, object] = {}

    def _post_json(self, endpoint, authorization, payload, timeout_seconds, proxy_url=""):
        if endpoint.startswith("https://queue.fal.run/"):
            self.queue_payload = dict(payload)
            return {
                "request_id": "video-request-01",
                "status_url": "https://queue.example.test/status/video-request-01",
                "response_url": "https://queue.example.test/result/video-request-01",
            }
        return {
            "provider": "fal",
            "images": [
                {
                    "url": "https://cdn.example.test/jiejing/product-main.jpg",
                    "width": 1024,
                    "height": 1024,
                }
            ],
        }

    def _get_json(self, endpoint, authorization, timeout_seconds, proxy_url=""):
        if "/status/" in endpoint:
            return {"status": "COMPLETED"}
        return {
            "video": {
                "url": "https://cdn.example.test/jiejing/object?id=product-demo",
                "mime_type": "video/mp4; charset=binary",
                "duration": 6,
            }
        }


def main() -> int:
    mvhd = b"mvhd" + b"\x00\x00\x00\x00" + struct.pack(">IIII", 0, 0, 1000, 5640)
    if _mp4_duration_seconds(b"prefix" + mvhd) != 5.64:
        raise AssertionError("MP4 duration parser did not return the exact media duration")
    adapter = FakeFalAdapter()
    with patched_env(JIEJING_FAL_VIDEO_USE_QUEUE="true"):
        snapshot = adapter.generate(
            MediaGenerationConfig(
                product="Adjustable Drawer Dividers",
                image_prompt="Create a factual product image.",
                video_prompt="Use a slow push-in while preserving the confirmed product structure.",
                image_count=1,
                image_sizes=["1024x1024"],
                scene_types=["white_background"],
                live_enabled=True,
                provider="fal",
                api_key="unit-test-secret",
                timeout_seconds=30,
            )
        )

    assets = snapshot.get("assets") if isinstance(snapshot.get("assets"), list) else []
    image_assets = [asset for asset in assets if "image" in str(asset.get("asset_type") or "")]
    video_assets = [asset for asset in assets if "video" in str(asset.get("asset_type") or "")]
    if len(image_assets) != 1 or len(video_assets) != 1:
        raise AssertionError(f"expected one image and one video asset, got: {assets}")
    if video_assets[0].get("mime_type") != "video/mp4":
        raise AssertionError(f"extensionless FAL video MIME was not preserved canonically: {video_assets[0]}")
    if adapter.queue_payload.get("image_url") != image_assets[0].get("url"):
        raise AssertionError("video generation did not inherit the generated image URL")
    if "prompt" not in adapter.queue_payload or "safety" in adapter.queue_payload or "product" in adapter.queue_payload:
        raise AssertionError(f"FAL video payload does not match the provider schema: {adapter.queue_payload}")
    if snapshot.get("provider_status", {}).get("secret_exposed") is not False:
        raise AssertionError("media provider status must keep secrets hidden")
    if snapshot.get("video_provider", {}).get("asset_count") != 1:
        raise AssertionError("video provider summary should count the returned video")
    print("PASS jiejing_media_fal_video_chain")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
