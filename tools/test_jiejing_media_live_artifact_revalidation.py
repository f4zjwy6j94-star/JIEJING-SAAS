#!/usr/bin/env python3
"""Revalidate the latest downloaded live image/video proof without provider calls."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_runtime.media_generation import _mp4_duration_seconds
from jiejing_saas.media_asset_pipeline import build_media_asset_generation_packet


def main() -> int:
    latest_path = ROOT / "output" / "jiejing-controlled-media-video-proof" / "latest.json"
    latest = json.loads(latest_path.read_text(encoding="utf-8"))
    downloaded = latest.get("downloaded_assets") if isinstance(latest.get("downloaded_assets"), list) else []
    image = next((item for item in downloaded if "image" in str(item.get("asset_type") or "")), None)
    video = next((item for item in downloaded if "video" in str(item.get("asset_type") or "")), None)
    if not image or not video:
        raise AssertionError("latest live proof does not contain both downloaded image and video assets")
    image_path = Path(str(image.get("local_path") or ""))
    video_path = Path(str(video.get("local_path") or ""))
    duration = _mp4_duration_seconds(video_path.read_bytes())
    if not duration:
        raise AssertionError("downloaded MP4 does not expose a valid movie duration")

    captured_at = datetime.now(timezone.utc).isoformat()
    snapshot = {
        "provider": "configured_media_provider",
        "assets": [
            {
                "asset_id": "controlled_live_image_01",
                "asset_type": "product_image",
                "path": str(image_path.resolve()),
                "dimensions": "provider_returned",
                "commercial_use_status": "needs_review",
                "status": "generated",
            },
            {
                "asset_id": "controlled_live_video_01",
                "asset_type": "product_video",
                "path": str(video_path.resolve()),
                "dimensions": f"{duration}s",
                "duration_seconds": duration,
                "commercial_use_status": "needs_review",
                "status": "generated",
            },
        ],
    }
    packet = build_media_asset_generation_packet(
        base={"provider_job_key": "media.asset_generation", "captured_at": captured_at},
        contract_key="media.asset_generation",
        inputs={
            "image_count": 1,
            "image_sizes": ["1024x1024"],
            "scene_types": ["white_background"],
            "video_script": "Controlled product demo proof",
            "product_facts": {"product": "Controlled capability proof only", "material": "unverified"},
            "creative_job_spec": {"job_type": "controlled_media_capability_proof"},
        },
        captured_at=captured_at,
        live_media_snapshot=snapshot,
    )
    validation = packet.get("asset_manifest_validation", {})
    if validation.get("status") != "manifest_ready":
        raise AssertionError(f"downloaded live artifacts still fail AssetManifest validation: {validation}")
    if packet.get("safety", {}).get("calls_video_provider") is not True:
        raise AssertionError("revalidated manifest did not retain the real video asset")
    revalidated = {
        "ok": True,
        "acceptance_product": latest.get("acceptance_product"),
        "revalidated_at": captured_at,
        "source_live_proof_captured_at": latest.get("captured_at"),
        "source_evidence": str(latest_path.resolve()),
        "image_path": str(image_path.resolve()),
        "video_path": str(video_path.resolve()),
        "video_duration_seconds": duration,
        "asset_manifest_validation": validation,
        "asset_review_status": packet.get("asset_review", {}).get("status"),
        "calls_image_provider": packet.get("safety", {}).get("calls_image_provider"),
        "calls_video_provider": packet.get("safety", {}).get("calls_video_provider"),
        "triggers_real_platform_write": False,
        "secret_exposed": False,
    }
    revalidated_path = latest_path.with_name("revalidated-latest.json")
    revalidated_path.write_text(json.dumps(revalidated, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"PASS jiejing_media_live_artifact_revalidation duration_seconds={duration}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
