#!/usr/bin/env python3
"""Regression for asset manifest validation and Hermes import checks."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_runtime import AssetManifestValidator
from jiejing_runtime.workflow_templates import ProductWorkflowRequest, build_product_workflow

RUN_DIR = ROOT / "output" / "jiejing-agent-runtime-samples" / "asset-manifest-validator"


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    validator = AssetManifestValidator()
    brief = validator.validate_text(brief_only_text())
    if brief.get("status") != "brief_only":
        return fail(f"plain brief should stay brief_only: {brief.get('summary')}")
    claimed = validator.validate_text("The main image and video are generated and ready for review.")
    if claimed.get("status") != "blocked_missing_manifest":
        return fail("generated asset claim without manifest should be blocked_missing_manifest")
    ready = validator.validate_text(asset_manifest_text())
    if ready.get("status") != "manifest_ready":
        return fail(f"complete asset manifest should be manifest_ready: {ready.get('summary')}")
    bad_manifest = validator.validate_text(
        """
Generated assets are ready.
```json
{"assets":[{"asset_id":"img_01","asset_type":"main_image","url":"https://example.com/main.jpg"}]}
```
"""
    )
    if bad_manifest.get("status") != "blocked_incomplete_manifest":
        return fail("manifest missing source, rights, and dimensions should be incomplete")
    if not validator.missing_inputs_from_validation(bad_manifest):
        return fail("incomplete manifest should produce missing inputs")

    tasks = build_product_workflow(
        ProductWorkflowRequest(
            product="Backflow Incense Burner",
            merchant_goal="Validate asset manifest import.",
            project_id="asset-manifest-validator-regression",
        )
    )
    asset_task = next(task for task in tasks if task["task_type"] == "asset.brief")
    packet_json = RUN_DIR / "asset_brief_packet.json"
    role_output = RUN_DIR / "asset_manager_output.md"
    output_json = RUN_DIR / "imported_asset_brief_result.json"
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    packet_json.write_text(
        json.dumps(
            {
                "task": asset_task,
                "target_role": "asset-manager",
                "dispatch_prompt": "Validate asset manifest output.",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    role_output.write_text(asset_manifest_text(), encoding="utf-8")
    command = [
        sys.executable,
        str(ROOT / "tools" / "jiejing_runtime_cli.py"),
        "import-handoff-result",
        "--packet-json",
        str(packet_json),
        "--role-output",
        str(role_output),
        "--output-json",
        str(output_json),
    ]
    completed = subprocess.run(command, cwd=str(ROOT), text=True, capture_output=True, check=False)
    if completed.returncode != 0:
        print(completed.stdout)
        print(completed.stderr)
        return fail("import-handoff-result failed for asset brief")
    imported = json.loads(output_json.read_text(encoding="utf-8"))
    validation = imported.get("report", {}).get("asset_manifest_validation", {})
    if validation.get("status") != "manifest_ready":
        return fail("Hermes importer should attach asset manifest validation")
    if imported.get("audit", {}).get("real_execution_allowed") is not False:
        return fail("asset import must keep real execution blocked")

    print("PASS asset_manifest_validator_regression")
    return 0


def brief_only_text() -> str:
    return """
# Asset Manager Brief

## image_plan
Create white background, lifestyle, dimension, and feature images after product facts are confirmed.

## detail_page_plan
Create one vertical detail page with material, size, package, and use-scene sections.

## video_plan
Create a 20 second handling and use-scene video after final claims are reviewed.

## asset_settings
Marketplace: eBay US. Suggested image size: 1600x1600.

## claim_risk
Avoid unverified medical, handmade, waterproof, or performance claims.

## media_manifest_status
Brief only. No generated files are claimed in this handoff.
"""


def asset_manifest_text() -> str:
    return """
# Asset Manager Output

## image_plan
Main image, scene image, detail page, size chart, and cover image are generated for review.

## detail_page_plan
Detail page covers usage scene, material, size, package contents, and buyer questions.

## video_plan
Short video draft uses product close-up, hand placement, smoke-flow scene, and end card.

## asset_settings
Marketplace: eBay US. Square images use 1600x1600. Detail page uses 1200x3600.

## claim_risk
All copy stays demo-only and avoids unverified therapeutic or handmade claims.

## media_manifest_status
Generated files are ready for review. Manifest:

```json
{
  "assets": [
    {
      "asset_id": "img_main_01",
      "asset_type": "main_image",
      "url": "https://example.com/assets/backflow-main.jpg",
      "dimensions": "1600x1600",
      "source": "image_generation",
      "commercial_use_status": "demo_only",
      "status": "generated"
    },
    {
      "asset_id": "img_detail_01",
      "asset_type": "detail_page",
      "url": "https://example.com/assets/backflow-detail.jpg",
      "dimensions": "1200x3600",
      "source": "image_generation",
      "commercial_use_status": "demo_only",
      "status": "generated"
    },
    {
      "asset_id": "video_01",
      "asset_type": "product_video",
      "url": "https://example.com/assets/backflow-video.mp4",
      "duration_seconds": 24,
      "source": "video_generation",
      "commercial_use_status": "demo_only",
      "status": "generated"
    }
  ]
}
```
"""


if __name__ == "__main__":
    raise SystemExit(main())
