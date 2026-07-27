#!/usr/bin/env python3
"""Regression for source-grounded image and video generation from the media studio."""

from __future__ import annotations

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    app_js = (ROOT / "app.js").read_text(encoding="utf-8")
    marker = "function saasMediaGenerationGroundingGate"
    assert marker in app_js, "media studio must have an explicit source-grounding gate"

    start = app_js.index(marker)
    end = app_js.index("\nfunction buildSaasMediaAssetJobPayload", start)
    function_source = app_js[start:end]
    node_script = f"""
{function_source}
const cases = [
  [{{ reference_images: [], source_asset_id: "" }}, {{ qualityMode: "fidelity_first", videoDurationSeconds: 0 }}, false, true],
  [{{ reference_images: [], source_asset_id: "" }}, {{ qualityMode: "creative_exploration", videoDurationSeconds: 0 }}, true, true],
  [{{ reference_images: [], source_asset_id: "" }}, {{ qualityMode: "creative_exploration", videoDurationSeconds: 6 }}, false, true],
  [{{ reference_images: ["https://cdn.example.test/source.jpg"], source_asset_id: "" }}, {{ qualityMode: "fidelity_first", videoDurationSeconds: 10 }}, true, false],
  [{{ reference_images: [], source_asset_id: "asset_private_1" }}, {{ qualityMode: "fidelity_first", videoDurationSeconds: 0 }}, true, false],
];
for (const [facts, config, allowed, conceptOnly] of cases) {{
  const result = saasMediaGenerationGroundingGate(facts, config);
  if (result.allowed !== allowed || result.conceptOnly !== conceptOnly) {{
    throw new Error(`unexpected gate ${{JSON.stringify(result)}} for ${{JSON.stringify({{facts, config}})}}`);
  }}
}}
"""
    completed = subprocess.run(
        ["node", "-e", node_script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout

    handler_start = app_js.index("function handleMediaGenerateImagesDraftClick")
    handler_end = app_js.index("\nasync function handleMediaScriptDraftClick", handler_start)
    handler = app_js[handler_start:handler_end]
    assert "saasMediaGenerationGroundingGate" in handler, "generate action must fail closed before queueing a provider job"
    assert handler.index("saasMediaGenerationGroundingGate") < handler.index("queueSaasMediaAssetJobFromStudio")
    print("PASS jiejing_media_source_grounding_gate")


if __name__ == "__main__":
    main()
