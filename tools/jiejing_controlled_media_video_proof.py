#!/usr/bin/env python3
"""Run one explicitly authorized live image-to-video capability proof."""

from __future__ import annotations

import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_runtime.media_generation import MediaGenerationAdapter, MediaGenerationConfig
from jiejing_saas.media_asset_pipeline import build_media_asset_generation_packet


def _download(url: str, target: Path) -> int:
    request = urllib.request.Request(url, headers={"User-Agent": "Jiejing controlled media proof"})
    with urllib.request.urlopen(request, timeout=90) as response:
        data = response.read()
    target.write_bytes(data)
    return len(data)


def main() -> int:
    if os.environ.get("JIEJING_CONTROLLED_MEDIA_VIDEO_PROOF", "").strip().lower() not in {"1", "true", "yes"}:
        raise SystemExit("Set JIEJING_CONTROLLED_MEDIA_VIDEO_PROOF=true for this one authorized provider call.")

    captured_at = datetime.now(timezone.utc).isoformat()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    output_root = ROOT / "output" / "jiejing-controlled-media-video-proof" / stamp
    output_root.mkdir(parents=True, exist_ok=True)

    snapshot = MediaGenerationAdapter().generate(
        MediaGenerationConfig(
            product="Adjustable Drawer Dividers - controlled capability proof only",
            image_prompt=(
                "Create one realistic studio product image of an unbranded adjustable drawer divider set on a pure white background. "
                "Show only the product, preserve a plausible simple structure, and add no text, logo, certification, price or performance claim. "
                "This is a controlled media capability proof, not a real supplier product photo."
            ),
            video_prompt=(
                "Create a short product-focused demonstration from the supplied first frame. Use a slow camera push-in and subtle parallax only. "
                "Preserve the divider structure and color. Add no people, hands, logos, text, price or unsupported claim."
            ),
            image_count=1,
            image_sizes=["1024x1024"],
            scene_types=["white_background"],
            live_enabled=True,
            provider="fal",
            timeout_seconds=420,
        )
    )
    inputs = {
        "media_provider": "provider_neutral",
        "model_provider": "account_model_or_platform_default",
        "image_count": 1,
        "image_sizes": ["1024x1024"],
        "scene_types": ["white_background"],
        "video_script": "Controlled short product demonstration; no unsupported claims.",
        "product_facts": {
            "product": "Adjustable Drawer Dividers - controlled capability proof only",
            "material": "unverified",
        },
        "creative_job_spec": {
            "job_type": "controlled_media_capability_proof",
            "blocked_claims": ["certification", "performance", "brand authorization"],
        },
        "cost_limit_cents": 1300,
    }
    packet = build_media_asset_generation_packet(
        base={"provider_job_key": "media.asset_generation", "captured_at": captured_at},
        contract_key="media.asset_generation",
        inputs=inputs,
        captured_at=captured_at,
        live_media_snapshot=snapshot,
    )
    assets = packet.get("asset_manifest") if isinstance(packet.get("asset_manifest"), list) else []
    downloaded: list[dict[str, object]] = []
    for index, asset in enumerate(assets, start=1):
        url = str(asset.get("url_or_file_path") or asset.get("url") or "").strip()
        if not url.startswith(("http://", "https://")):
            continue
        is_video = "video" in str(asset.get("asset_type") or "").lower()
        target = output_root / (f"asset-{index:02d}.mp4" if is_video else f"asset-{index:02d}.jpg")
        byte_count = _download(url, target)
        signature = target.read_bytes()[:32]
        valid_file = byte_count > 1024 and (
            (b"ftyp" in signature)
            if is_video
            else signature[:3] == b"\xff\xd8\xff" or signature[:4] in {b"\x89PNG", b"RIFF"}
        )
        downloaded.append(
            {
                "asset_type": asset.get("asset_type"),
                "url_host": urllib.parse.urlparse(url).netloc,
                "local_path": str(target.resolve()),
                "bytes": byte_count,
                "file_signature_valid": valid_file,
                "review_status": asset.get("review_status"),
                "listing_use_status": asset.get("listing_use_status"),
            }
        )

    has_image = any("image" in str(item.get("asset_type") or "") for item in downloaded)
    has_video = any("video" in str(item.get("asset_type") or "") for item in downloaded)
    all_files_valid = bool(downloaded) and all(item.get("file_signature_valid") is True for item in downloaded)
    evidence = {
        "ok": bool(
            has_image
            and has_video
            and all_files_valid
            and packet.get("asset_manifest_validation", {}).get("status") == "manifest_ready"
            and packet.get("safety", {}).get("calls_video_provider") is True
        ),
        "captured_at": captured_at,
        "purpose": "controlled_capability_proof_only_not_a_real_listing",
        "asset_count": len(assets),
        "downloaded_assets": downloaded,
        "asset_manifest_validation": packet.get("asset_manifest_validation"),
        "asset_review_status": packet.get("asset_review", {}).get("status"),
        "calls_image_provider": packet.get("safety", {}).get("calls_image_provider"),
        "calls_video_provider": packet.get("safety", {}).get("calls_video_provider"),
        "real_platform_writes_enabled": False,
        "triggers_real_platform_write": False,
        "raw_provider_response_stored": False,
        "secret_exposed": False,
    }
    (output_root / "evidence.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    latest = ROOT / "output" / "jiejing-controlled-media-video-proof" / "latest.json"
    latest.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"ok": evidence["ok"], "asset_count": evidence["asset_count"], "output_root": str(output_root), "secret_exposed": False}))
    return 0 if evidence["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
