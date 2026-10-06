#!/usr/bin/env python3
"""Regression for source-grounded image and video generation from the media studio."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def assert_concept_review_modal_browser(app_js: str) -> None:
    """Exercise the real preview renderer and checkbox handler without a backend."""
    visual_start = app_js.index("function assetVisualMarkup(asset)")
    modal_start = app_js.index("\nfunction openAssetPreview", visual_start)
    modal_end = app_js.index("\nfunction openEvidence", modal_start)
    app_html = (ROOT / "app.html").read_text(encoding="utf-8")
    html_start = app_html.index('    <div class="modal-backdrop" id="assetModal"')
    html_end = app_html.index('    <div class="modal-backdrop" id="mediaAcceptanceModal"', html_start)
    payload = {
        "source": app_js[visual_start:modal_end],
        "modal": app_html[html_start:html_end],
    }
    script = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { chromium } = require('./output/codex-playwright-deps/node_modules/playwright-core');
const payload = JSON.parse(fs.readFileSync(0, 'utf8'));
(async () => {
  const browser = await chromium.launch({headless:true, channel:process.env.JIEJING_PLAYWRIGHT_CHANNEL || 'chrome'});
  const screenshots = fs.mkdtempSync(path.join(os.tmpdir(), 'jiejing-concept-review-'));
  const network = [], errors = [];
  let scenarios = 0;
  try {
    for (const width of [1440, 390]) {
      const context = await browser.newContext({viewport:{width, height:1000}, serviceWorkers:'block'});
      await context.route('**/*', route => {
        network.push(route.request().method() + ' ' + new URL(route.request().url()).pathname);
        return route.abort();
      });
      const page = await context.newPage();
      page.on('pageerror', error => errors.push(error.message));
      page.on('console', message => {
        if (['error', 'warning'].includes(message.type())) errors.push(message.text());
      });
      await page.setContent('<!doctype html><html><head><title>Offline Jiejing media review</title>' +
        '<style>body{font-family:sans-serif;margin:16px}.modal{max-width:900px}img{max-width:160px}' +
        'button{padding:12px;margin:6px}li{margin:10px 0}[hidden]{display:none!important}</style></head>' +
        '<body><button id="openFixture">打开素材预览</button>' + payload.modal + '</body></html>');
      await page.addScriptTag({content:`
const state = {};
const assetModal = document.querySelector('#assetModal');
let fixtureAsset;
function escapeHtml(value) { return String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char])); }
function activeMediaAssetPreview() { return fixtureAsset; }
function saasMediaManifestAssetPreview() { return fixtureAsset; }
function latestSaasMediaAssetJobWithManifest() { return {media_job_id:'offline-media-job'}; }
function closeModals() { assetModal.hidden = true; document.body.classList.remove('site-locked'); }
${payload.source}
document.querySelector('#openFixture').addEventListener('click', () => openAssetPreview('fixture'));
document.querySelectorAll('[data-close-modal]').forEach(button => button.addEventListener('click', closeModals));
window.setFixture = value => { fixtureAsset = value; };
`});
      assert.equal(await page.title(), 'Offline Jiejing media review');
      assert.equal(page.url(), 'about:blank');
      const outputImage = 'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" width="40" height="40"%3E%3Crect width="40" height="40" fill="blue"/%3E%3C/svg%3E';
      const sourceImage = 'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" width="40" height="40"%3E%3Crect width="40" height="40" fill="green"/%3E%3C/svg%3E';
      for (const scenario of [
        {name:'concept-without-source', conceptOnly:true, hasGroundedSource:false},
        {name:'concept-with-source', conceptOnly:true, hasGroundedSource:true},
        {name:'grounded-listing', conceptOnly:false, hasGroundedSource:true},
      ]) {
        const asset = {...scenario, role:scenario.conceptOnly?'概念参考图':'待审核商品图',
          title:scenario.name, intro:'离线素材审核合同', meta:scenario.conceptOnly?'不可用于刊登':'待审核',
          requiresReviewConfirmation:true, visualClass:'asset-render-main', image:outputImage,
          sourceImage:scenario.hasGroundedSource?sourceImage:'', script:'',
          checklist:scenario.conceptOnly?['只供构图参考','不确认商品事实','重新生成后再审核','不可回写 Listing']:
            ['商品结构','商品外观','商品事实','商业权利','平台规则','只回写草稿'],
          reviewChecklistIds:scenario.conceptOnly?[]:
            ['product_structure','product_appearance','product_claims','commercial_rights','platform_claims','listing_draft_boundary']};
        await page.evaluate(asset => window.setFixture(asset), asset);
        for (let reopened = 0; reopened < 2; reopened += 1) {
          await page.locator('#openFixture').click();
          assert.equal(await page.locator('#assetModal').isVisible(), true);
          const review = page.locator('#assetSendConfirm');
          assert.equal(await review.isDisabled(), true, `${scenario.name}: starts disabled`);
          const checks = page.locator('#assetModalChecklist input[type="checkbox"]');
          const count = await checks.count();
          for (let index = 0; index < count; index += 1) await checks.nth(index).check();
          const source = page.locator('#assetModalVisual img[alt="商品来源图"]');
          assert.equal(await source.count(), scenario.hasGroundedSource ? 1 : 0,
            `${scenario.name}: source comparison must follow the supplied evidence`);
          if (scenario.hasGroundedSource) assert.equal(await source.getAttribute('src'), sourceImage);
          if (scenario.conceptOnly) {
            assert.equal(await review.isDisabled(), true, `${scenario.name}: checking every item must never enable review`);
            assert.equal(count, 0, `${scenario.name}: concept guidance is not an approval checklist`);
            await page.locator('#assetModalChecklist').dispatchEvent('change');
            assert.equal(await review.isDisabled(), true, `${scenario.name}: change event must remain disabled`);
            const text = await page.locator('#assetModalVisual').innerText();
            assert.ok(text.includes('不可用于刊登'), `${scenario.name}: listing exclusion visible`);
            assert.equal(text.includes('未提供真实商品来源图'), !scenario.hasGroundedSource,
              `${scenario.name}: source copy follows source evidence, not concept mode`);
          } else {
            assert.equal(count, 6);
            assert.equal(await review.isEnabled(), true, 'grounded: full review remains available');
            await checks.first().uncheck();
            assert.equal(await review.isDisabled(), true, 'grounded: revoking one acknowledgment blocks review');
            await checks.first().check();
            assert.equal(await review.isEnabled(), true, 'grounded: completing the checklist re-enables review');
          }
          if (!reopened) await page.screenshot({path:path.join(screenshots, `${scenario.name}-${width}.png`), fullPage:true});
          await page.locator('#assetModal [data-close-modal]').first().click();
          assert.equal(await page.locator('#assetModal').isVisible(), false);
        }
        scenarios += 1;
      }
      await context.close();
    }
    assert.deepEqual(network, [], 'offline modal must not request any business or external URL');
    assert.deepEqual(errors, [], 'modal must not emit console or page errors');
    console.log(JSON.stringify({status:'pass', scenarios, open_close_cycles:scenarios*2,
      network_requests:network.length, console_errors:errors.length, screenshots}));
  } finally { await browser.close(); }
})().catch(error => { console.error(error.stack || error); process.exitCode = 1; });
"""
    completed = subprocess.run(
        ["node", "-e", script], input=json.dumps(payload), cwd=ROOT,
        capture_output=True, text=True, encoding="utf-8", check=False, timeout=90,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
    print(completed.stdout.strip())


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
    assert "function saasMediaSourceAssetForListingDraft" in app_js
    source_asset_start = app_js.index("function saasMediaSourceAssetForListingDraft")
    source_asset_end = app_js.index("\nfunction currentMediaStudioProductFacts", source_asset_start)
    source_asset_source = app_js[source_asset_start:source_asset_end]
    source_asset_script = f"""
{source_asset_source}
const draft = {{
  merchant_product_fact_packet: {{
    source_records: [
      {{ type: "merchant_product_image", asset_id: "media_src_tall", sha256: "sha-tall", source_index: 2, width: 790, height: 1028, rights_status: "pending_merchant_confirmation" }},
      {{ type: "merchant_product_image", asset_id: "media_src_primary", sha256: "sha-primary", source_index: 4, width: 800, height: 800, rights_status: "pending_merchant_confirmation" }},
      {{ type: "merchant_product_link", url: "https://example.test/item" }},
    ],
  }},
}};
const selected = saasMediaSourceAssetForListingDraft(draft);
if (selected.asset_id !== "media_src_primary" || selected.sha256 !== "sha-primary") {{
  throw new Error(`AI CEO source bridge must prefer the clearest square product image: ${{JSON.stringify(selected)}}`);
}}
if (selected.rights_status !== "pending_merchant_confirmation") {{
  throw new Error("source bridge must preserve the rights-review boundary");
}}
"""
    source_asset_completed = subprocess.run(
        ["node", "-e", source_asset_script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert source_asset_completed.returncode == 0, source_asset_completed.stderr or source_asset_completed.stdout
    assert "saasMediaSourceAssetForListingDraft(composer)" in product_facts_source
    assert 'private_source_transport: sourceAssetId ? "backend_asset_id" : ""' in product_facts_source
    assert 'source_bridge_contract: reportSourceAsset && !uploadMatchesProject ? "ai_ceo_private_source_asset_to_media_v1"' in product_facts_source
    assert 'source_rights_status: uploadMatchesProject ? upload?.rights_status || "" : reportSourceAsset?.rights_status || ""' in product_facts_source
    assert "packetFacts.product_dimensions_cm" in product_facts_source
    assert "packetFacts.net_weight_g" in product_facts_source
    assert 'material_pending_label: ["待补", "待确认"].includes(material)' in product_facts_source
    assert "dimensions_pending_label: !dimensions" in product_facts_source
    visual_start = app_js.index("function assetVisualMarkup(asset)")
    visual_end = app_js.index("\nfunction openAssetPreview", visual_start)
    visual_script = f"""
function escapeHtml(value) {{ return String(value || ""); }}
{app_js[visual_start:visual_end]}
const concept = assetVisualMarkup({{
  conceptOnly: true, visualClass: "asset-render-main",
  image: "https://cdn.example.test/concept.jpg", title: "概念参考图",
}});
if (concept.includes("来源图已安全绑定") || !concept.includes("未提供真实商品来源图")) {{
  throw new Error("concept preview must not invent an existing source image");
}}
if (concept.includes("识别商品主体") || !concept.includes("不可用于刊登")) {{
  throw new Error("concept preview must not claim source-photo editing or listing eligibility");
}}
const grounded = assetVisualMarkup({{
  conceptOnly: false, visualClass: "asset-render-main",
  image: "https://cdn.example.test/result.jpg", sourceImage: "https://cdn.example.test/source.jpg",
}});
if (!grounded.includes("source.jpg") || !grounded.includes("商品来源图")) {{
  throw new Error("grounded preview must retain its real source comparison");
}}
"""
    visual_completed = subprocess.run(
        ["node", "-e", visual_script], cwd=ROOT, capture_output=True,
        text=True, encoding="utf-8", check=False,
    )
    assert visual_completed.returncode == 0, visual_completed.stderr or visual_completed.stdout
    generated_start = app_js.index("function syncMediaStudioGenerated")
    generated_end = app_js.index("\nfunction recordMediaGeneration", generated_start)
    record_end = app_js.index("\nfunction runMediaGenerationFromCeo", generated_end)
    generated_script = f"""
const state = {{ mediaGenerationCount: 0 }};
const texts = {{}};
const records = [];
const document = {{querySelector: () => null, querySelectorAll: () => []}};
function readMediaGenerationConfig(options) {{return {{...options, entry:"project", entryLabel:"商品草稿", count:"1 张", voice:"英语脚本"}};}}
function setText(key, value) {{texts[key] = value;}}
function renderMediaQualityBoard() {{}}
function activeMediaDraftProfileForDisplay() {{return null;}}
function activeMediaDraftProductNameForDisplay() {{return "当前商品";}}
function isSaasPublicMvpMode() {{return true;}}
function upsertActivity(id, record) {{records.push(record);}}
function setActivityFeedback(value) {{texts.activityFeedback = value;}}
{app_js[generated_start:record_end]}
syncMediaStudioGenerated("商品方向", {{conceptOnly:true, returnedAssetCount:1}});
if (!texts["#mediaSourceTitle"].includes("未提供真实来源图") || texts["#mediaSourceNote"].includes("原图版本")) {{
  throw new Error("successful concept generation must not claim a source photo was received");
}}
if (!texts["#mediaDecisionSummary"].includes("不可回写 Listing") || texts["#mediaOutputStatus"].includes("英语脚本")) {{
  throw new Error("concept completion must not promise listing writeback or an ungenerated script");
}}
syncMediaStudioGenerated("有来源的创意探索", {{conceptOnly:true, hasGroundedSource:true, returnedAssetCount:1}});
if (texts["#mediaSourceTitle"].includes("未提供") || !texts["#mediaSourceNote"].includes("已提供来源") || !texts["#mediaSourceNote"].includes("不可用于刊登")) {{
  throw new Error("grounded creative exploration must retain source evidence without gaining listing eligibility");
}}
for (const hasGroundedSource of [false, true]) {{
  recordMediaGeneration("商品方向", {{conceptOnly:true, hasGroundedSource, returnedAssetCount:1}});
  const record = records.at(-1);
  if (!record.title.includes("概念参考图") || record.action.includes("准备回写") || !record.result.includes("实际返回 1 个概念参考文件") || !record.result.includes("不可回写 Listing")) {{
    throw new Error("saved concept result must record its actual output and listing exclusion");
  }}
  if (!texts.activityFeedback.includes("实际返回 1 个文件") || !texts.activityFeedback.includes("不可用于刊登") || texts.activityFeedback.includes("视频脚本")) {{
    throw new Error("saved result feedback must not invent completion of video or script artifacts");
  }}
}}
"""
    generated_completed = subprocess.run(
        ["node", "-e", generated_script], cwd=ROOT, capture_output=True,
        text=True, encoding="utf-8", check=False,
    )
    assert generated_completed.returncode == 0, generated_completed.stderr or generated_completed.stdout
    assert_concept_review_modal_browser(app_js)
    print("PASS jiejing_media_source_grounding_gate")


if __name__ == "__main__":
    main()
