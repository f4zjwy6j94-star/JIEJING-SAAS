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
    assert "if (pendingMediaGenerationAcceptance) return;" in handler, "duplicate click handlers must share one acceptance point"
    assert "saasMediaGenerationGroundingGate" in handler, "generate action must fail closed before queueing a provider job"
    assert handler.index("saasMediaGenerationGroundingGate") < handler.index("queueSaasMediaAssetJobFromStudio")
    assert "await requestMediaGenerationAcceptance(groundingGate)" in handler, "merchant must explicitly confirm commercial and AI-generation rights"
    assert "window.confirm" not in handler, "media acceptance must use an in-page confirmation instead of a blocking browser dialog"
    assert (
        handler.index("await requestMediaGenerationAcceptance(groundingGate)") < handler.index("queueSaasMediaAssetJobFromStudio")
    ), "commercial-rights confirmation must happen before the paid media job is queued"
    assert (
        'state.mediaGenerationStatus = "needs_rights_confirmation"' in handler
    ), "declining commercial rights must leave an explicit non-generated state"
    assert (
        "config.commercialRightsConfirmed = groundingGate.hasGroundedSource === true" in handler
    ), "source-free concept acceptance must not claim commercial rights to a nonexistent source image"
    assert (
        handler.index("config.commercialRightsConfirmed = groundingGate.hasGroundedSource === true")
        < handler.index("queueSaasMediaAssetJobFromStudio")
    ), "the confirmed rights flag must be set before the queue payload is built"
    assert "不可刊登的概念参考图" in handler, "concept-only media must receive its own merchant acceptance copy"
    assert "config.conceptOnlyAccepted = groundingGate.conceptOnly === true" in handler

    action_state_start = app_js.index("function syncMediaGenerationActionState")
    action_state_end = app_js.index("\nfunction buildSaasMediaAssetJobPayload", action_state_start)
    action_state = app_js[action_state_start:action_state_end]
    assert 'button.disabled = !groundingGate.allowed' in action_state
    assert '"先上传来源图或选择概念探索"' in action_state
    assert '"生成概念参考图"' in action_state
    assert 'writebackButton.disabled = !listingWritebackAllowed' in action_state
    assert '"概念图不可回写 Listing"' in action_state
    assert '"只作概念方向参考，不进入产品刊登"' in action_state

    acceptance_start = app_js.index("function requestMediaGenerationAcceptance")
    acceptance_end = app_js.index("\nfunction openManualAction", acceptance_start)
    acceptance_source = app_js[acceptance_start:acceptance_end]
    assert '"确认生成概念参考图"' in acceptance_source
    assert '"不会回写 Listing，不会自动发布、付款或写入 eBay。"' in acceptance_source

    payload_start = app_js.index("function buildSaasMediaAssetJobPayload")
    payload_end = app_js.index("\nasync function pollSaasMediaAssetJobUntilReview", payload_start)
    payload_source = app_js[payload_start:payload_end]
    assert (
        "commercial_rights_confirmed: config.commercialRightsConfirmed === true" in payload_source
    ), "the backend payload must carry the strict commercial-rights confirmation boolean"
    assert "concept_only_accepted: config.conceptOnlyAccepted === true" in payload_source

    failure_marker = "function saasMediaQueueFailureView"
    assert failure_marker in app_js, "media queue failures must be translated into merchant-actionable copy"
    failure_start = app_js.index(failure_marker)
    failure_end = app_js.index("\nasync function queueSaasMediaAssetJobFromStudio", failure_start)
    failure_source = app_js[failure_start:failure_end]
    failure_script = f"""
function publicRuntimeText(value) {{ return String(value || \"\"); }}
{failure_source}
const insufficient = saasMediaQueueFailureView({{
  status: 402,
  payload: {{ error: \"素材点不足，当前任务没有进入生成队列。\" }},
}});
if (!insufficient.statusText.includes(\"素材点不足\") || !insufficient.note.includes(\"没有调用生成服务\")) {{
  throw new Error(`402 failure copy must explain the safe no-charge outcome: ${{JSON.stringify(insufficient)}}`);
}}
const invalidFacts = saasMediaQueueFailureView({{
  status: 422,
  payload: {{ error: \"商品事实尚未完整。\" }},
}});
if (!invalidFacts.statusText.includes(\"资料待补\") || !invalidFacts.note.includes(\"商品事实尚未完整\")) {{
  throw new Error(`422 failure copy must preserve the safe backend reason: ${{JSON.stringify(invalidFacts)}}`);
}}
"""
    failure_completed = subprocess.run(
        ["node", "-e", failure_script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert failure_completed.returncode == 0, failure_completed.stderr or failure_completed.stdout

    queue_start = app_js.index("async function queueSaasMediaAssetJobFromStudio")
    queue_end = app_js.index("\nasync function handleMediaGenerateImagesDraftClick", queue_start)
    queue_source = app_js[queue_start:queue_end]
    assert "saasMediaQueueFailureView(error)" in queue_source
    assert 'setText("#mediaProductionStatus", failure.statusText)' in queue_source
    assert 'setText("#mediaPreviewNote", failure.note)' in queue_source
    product_facts_start = app_js.index("function currentMediaStudioProductFacts")
    product_facts_end = app_js.index("\nfunction saasMediaGenerationGroundingGate", product_facts_start)
    product_facts_source = app_js[product_facts_start:product_facts_end]
    assert 'material_pending_label: ["待补", "待确认"].includes(material)' in product_facts_source
    assert "dimensions_pending_label: !dimensions" in product_facts_source
    print("PASS jiejing_media_source_grounding_gate")


if __name__ == "__main__":
    main()
