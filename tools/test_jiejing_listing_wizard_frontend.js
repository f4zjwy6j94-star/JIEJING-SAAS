#!/usr/bin/env node
"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");
const source = fs.readFileSync(path.join(__dirname, "..", "app.js"), "utf8");
function load(names, extra = {}) {
  const context = vm.createContext({ state: { saasListingComposerDraft: {} },
    publicRuntimeText: String, saasMerchantProductFactLabel: key => key, ...extra });
  for (const name of names) {
    const start = source.search(new RegExp(`^(?:async )?function ${name}\\(`, "m"));
    assert(start >= 0, `${name} must exist`);
    const tail = source.slice(start);
    const next = tail.slice(1).search(/^function |^async function |^const |^let /m);
    vm.runInContext(next < 0 ? tail : tail.slice(0, next + 1), context);
  }
  return context;
}
test("facts continue uses confirmed core facts, independent of publish gaps", () => {
  const context = load(["saasMerchantProductFactValuePresent", "saasListingWizardCoreMissing"], {
    saasMerchantProductFactPacket: draft => draft.merchant_product_fact_packet,
  });
  const draft = { merchant_product_fact_packet: { merchant_confirmed_facts: {
    product_name: "Tablet stand", condition: "NEW", material: "Aluminum",
  }, unknown_facts: ["image_urls", "image_rights_confirmed", "sku"] } };
  assert.deepEqual(Array.from(context.saasListingWizardCoreMissing(draft)), []);
  delete draft.merchant_product_fact_packet.merchant_confirmed_facts.material;
  draft.merchant_product_fact_packet.derived_listing_suggestions = { material: "Aluminum" };
  assert.deepEqual(Array.from(context.saasListingWizardCoreMissing(draft)), ["material"]);
});
test("saving a partial step preserves other facts and revokes visible unknown values", () => {
  const context = load(["collectSaasMerchantProductFacts"], {
    saasMerchantProductFactPacket: () => ({ merchant_confirmed_facts: {
      product_name: "Tablet stand", material: "Aluminum", image_urls: "https://example.test/photo.png", image_rights_confirmed: true,
    }, unknown_facts: ["quantity"] }),
    sanitizeSaasWorkflowFeedbackText: String,
    saasMerchantProductFactValuePresent: (key, value) => key.endsWith("confirmed") ? value === true : Boolean(value),
    document: { querySelectorAll: () => [{ type: "text", value: "", dataset: {
      saasProductFactField: "material", productFactUnknown: "true", productFactConfirmed: "true",
    } }] },
  });
  const result = context.collectSaasMerchantProductFacts();
  assert.equal(result.merchantConfirmed.product_name, "Tablet stand");
  assert.equal(result.merchantConfirmed.image_rights_confirmed, true);
  assert.equal(result.merchantConfirmed.image_urls, "https://example.test/photo.png");
  assert.equal(Object.hasOwn(result.merchantConfirmed, "material"), false);
  assert(result.unknownFacts.includes("quantity"));
  assert(result.unknownFacts.includes("material"));
});
test("single workspace mounts exactly one step instead of stacking all editors", () => {
  const context = load(["renderSaasListingComposerWorkspace"], {
    saasListingSyncedProductRows: () => [], latestSaasAiCeoMarketResearchTurn: () => null,
    saasListingOpportunityFromDraft: () => null, escapeHtml: String,
    renderSaasListingSourceIntake: () => "INTAKE", renderSaasListingWizard: () => "WIZARD",
    state: { saasListingComposerDraft: { product: "Tablet stand" } },
  });
  const html = context.renderSaasListingComposerWorkspace({ pendingConfirmations: [], ctx: {} });
  assert(html.includes("WIZARD"));
  assert(!html.includes("INTAKE"));
});
test("a revoked image never returns from stale prefill or media writeback", () => {
  const context = load(["saasMerchantProductFactProjectedValue", "saasListingWizardImageUrls"], {
    saasMerchantProductFactPacket: draft => draft.merchant_product_fact_packet,
    saasListingMediaWritebackImageUrls: () => ["https://example.test/old-media.png"],
  });
  const draft = { merchant_product_fact_packet: { unknown_facts: ["image_urls"], values: {} },
    publish_prefill: { image_urls: "https://example.test/old.png" } };
  assert.deepEqual(Array.from(context.saasListingWizardImageUrls(draft)), []);
});
test("step 2 revalidates the copy restored by its final cloud read", async () => {
  const record = { key: "scope", step: 2, busy: false };
  const state = { saasListingComposerDraft: { fields: { title: "Title", selling_points: "Points", description: "Description" } } };
  const context = load(["navigateSaasListingWizard"], {
    state, saasListingAiGenerationEpoch: 1, saasListingWizardRecord: () => record,
    saasListingCloudContext: () => ({ key: "scope" }), captureSaasListingDraftEditor() {},
    saasListingWizardGenerationPending: () => false, requireSaasProtectedSessionForAction: () => true,
    hydrateSaasListingCloudCheckpoint: async () => { state.saasListingComposerDraft.fields.description = ""; return true; },
    saasListingCloudRecord: () => ({ status: "saved" }),
    setSaasListingWizardStep: step => { record.step = step; }, showActionToast() {}, renderProductListingCenter() {},
  });
  assert.equal(await context.navigateSaasListingWizard("next"), false);
  assert.equal(record.step, 2);
});
test("every scoped jump away from step 4 captures the unsaved publish form", () => {
  const record = { key: "scope", step: 4 };
  const context = load(["setSaasListingWizardStep"], {
    saasListingWizardRecord: () => record, saasPendingPublishIntakeFormValues: null,
    document: { querySelector: () => ({ dataset: { listingWizardScope: "scope" } }) },
    snapshotSaasPublishIntakeFormValues: () => ({ shipping_cost: "19.95", merchant_location_key: "warehouse" }),
    localStorage: { setItem() {} },
  });
  context.setSaasListingWizardStep(1);
  assert.equal(context.saasPendingPublishIntakeFormValues?.shipping_cost, "19.95");
});

test("step 2 generation captures one normalized packet for both wire signature checks", () => {
  const draft = { merchant_product_fact_packet: { merchant_confirmed_facts: { material: "Resin" },
    unknown_facts: ["image_urls"], listing_readiness: { ready: false } },
    fields: { title: "Merchant title" }, model_generated: true };
  const context = load(["captureSaasListingFactsForAiGeneration"], {
    state: { saasListingComposerDraft: draft }, document: { querySelector: () => null },
    saasMerchantProductFactPacket: value => value.merchant_product_fact_packet,
    sanitizeSaasMerchantProductFactPacketSnapshot: packet => ({
      merchant_confirmed_facts: { ...packet.merchant_confirmed_facts }, unknown_facts: [...packet.unknown_facts],
    }),
  });
  const packet = context.captureSaasListingFactsForAiGeneration();
  assert.equal(draft.merchant_product_fact_packet, packet);
  assert.deepEqual(packet.unknown_facts, ["image_urls"]);
  assert.equal(packet.merchant_confirmed_facts.material, "Resin");
  assert.equal(draft.fields.title, "Merchant title");
  assert.equal(draft.model_generated, true);
});

test("step 2 cannot start generation while its initial product save is pending", () => {
  const context = load(["renderSaasListingWizard"], {
    state: { saasListingProductFactSaveStatus: "saving", saasListingComposerDraft: {} },
    saasListingWizardRecord: () => ({ key: "scope", step: 2 }),
    saasListingWizardGenerationPending: () => false,
    saasSettingsDataSnapshotView: () => ({ accountTone: "green" }),
    renderSaasListingAiGenerationFeedback: () => "", renderSaasListingDraftEditor: () => "EDITOR", escapeHtml: String,
  });
  const html = context.renderSaasListingWizard({});
  assert.match(html, /data-saas-action="listing-generate-ai-draft" disabled/);
});

test("both wizard directions wait for the owned initial fact save to finish", async () => {
  const record = { key: "scope", step: 2, busy: false };
  const context = load(["navigateSaasListingWizard"], {
    state: { saasListingProductFactSaveStatus: "saving" },
    saasListingAiGenerationEpoch: 1, saasListingWizardRecord: () => record,
    saasListingCloudContext: () => ({ key: "scope" }), captureSaasListingDraftEditor() {}, showActionToast() {},
  });
  assert.equal(await context.navigateSaasListingWizard("next"), false);
  assert.equal(await context.navigateSaasListingWizard("previous"), false);
  assert.equal(record.step, 2);
});

test("resolving a generated-result cloud conflict releases the wizard generation control", () => {
  let releases = 0;
  const state = { saasListingComposerDraft: { ai_generation_feedback: {
    status: "generated_unapplied", context_key: "scope", rewrite_source: { base_report_id: "before", revision: 1 },
  } }, saasReports: [{ report_id: "after" }] };
  const context = load(["reconcileSaasListingRewriteFeedback"], {
    state, saasListingRewriteFeedbackSource: value => value,
    saasListingAiGenerationContextKey: () => "scope", saasListingCloudContext: () => ({ key: "scope" }),
    saasListingBuyerCopyRewriteFromReport: () => ({ expected_base_report_id: "before", expected_checkpoint_revision: 1 }),
    saveSaasProtectedStateSnapshot() {}, document: { querySelectorAll: () => [] },
    releaseSaasListingAiGenerationButtons: () => { releases += 1; },
  });
  assert.equal(context.reconcileSaasListingRewriteFeedback({ context: { key: "scope" }, loaded: true,
    supersededRewriteReportIds: new Set(), receipt: { base_report_id: "after" } }), true);
  assert.equal(state.saasListingComposerDraft.ai_generation_feedback, null);
  assert.equal(releases, 1);
});

test("feedback updates release a retryable failure but keep uncertain, saving and busy generation locked", () => {
  const button = { dataset: { saasAction: "listing-generate-ai-draft" }, disabled: true, textContent: "等待本次生成结果" };
  const record = { busy: false };
  const state = { saasLoading: false, saasListingProductFactSaveStatus: "saved" };
  let pending = false;
  const context = load(["releaseSaasListingAiGenerationButtons", "updateSaasListingGenerationFeedbackSlots"], {
    state, saasListingWizardGenerationPending: () => pending, saasListingWizardRecord: () => record,
    document: { querySelectorAll: selector => selector.startsWith('[data-saas-action="listing-generate-ai-draft"]') ? [button] : [] },
  });
  context.updateSaasListingGenerationFeedbackSlots();
  assert.equal(button.disabled, false);
  assert.equal(button.textContent, "AI 生成 Listing 草稿");
  for (const cause of ["uncertain", "saving", "wizard-save"]) {
    pending = cause === "uncertain"; state.saasListingProductFactSaveStatus = cause === "saving" ? "saving" : "saved";
    record.busy = cause === "wizard-save";
    context.updateSaasListingGenerationFeedbackSlots();
    assert.equal(button.disabled, true, cause);
  }
});

test("resume releases its same-visit rendered lock after success clears feedback, never another project", async () => {
  for (const switchProject of [false, true]) {
    let scope = "scope", releases = 0, renderedLocked = false;
    const inflight = new Map();
    const state = { saasListingComposerDraft: { ai_generation_feedback: { operation: { operation_id: "op" },
      context_key: "scope", resume_available: true, input_signature: "input", request_signature: "request" } } };
    const context = load(["resumeSaasListingGeneration"], {
      state, saasListingAiGenerationEpoch: 1, saasStateRefreshGeneration: 1,
      requireSaasProtectedSessionForAction: () => true, saasListingGenerationOperation: value => value,
      saasListingAiGenerationContextKey: () => scope, saasListingGenerationOperationContextKey: () => "scope",
      saasListingAiGenerationInFlight: inflight, saasListingAiGenerationEditSnapshot: () => ({}),
      updateSaasListingGenerationFeedbackSlots() {}, saasListingGenerationWireRequest: () => ({}),
      readSaasListingGenerationResult: async () => ({}), saasListingGenerationNotFoundMatches: () => false,
      applySaasListingGenerationResult: async () => {
        state.saasListingComposerDraft.ai_generation_feedback = null;
        renderedLocked = inflight.has("scope");
        if (switchProject) scope = "other";
        return true;
      },
      releaseSaasListingAiGenerationButtons: () => { assert.equal(inflight.size, 0); releases += 1; },
    });
    assert.equal(await context.resumeSaasListingGeneration(), true);
    assert.equal(renderedLocked, true);
    assert.equal(releases, switchProject ? 0 : 1);
  }
});

test("adopting a generated report preserves the same project's observed fact CAS baseline", async () => {
  const signature = "a".repeat(64);
  const state = { saasReports: [], saasListingComposerDraft: { source_product_fact_report_id: "observed-facts-A",
    merchant_product_fact_packet: {}, ai_generation_feedback: { input_signature: signature } } };
  const operation = { user_id: "user", generation_mode: "preserve_merchant_edits", listing_project_identity: { key: "project" } };
  const report = { report_id: "generated", task_id: "task", user_id: "user", status: "saved", report_type: "listing.package",
    runtime_run_id: "listing_draft_generation", report: { contract_version: "listing_ai_draft_generation_v1",
      listing_handoff: { source_mode: "project_scoped_live_model", ready_for_listing_draft: true } } };
  const context = load(["applySaasListingGenerationResult"], { state,
    saasListingGenerationOperationContextKey: () => "scope", saasListingAiGenerationContextKey: () => "scope",
    saasListingGenerationResultMatches: () => true, saasListingGenerationNotFoundMatches: () => false,
    saasListingCloudContext: () => ({}), saasListingCloudReportMatchesContext: () => true,
    saasListingBuyerCopyRewriteFromReport: () => null, saasSha256Hex: async () => signature,
    saasListingAiGenerationHasNewEdits: () => false, saasListingDraftFromReport: () => ({ fields: { title: "Generated" } }),
    saveSaasProtectedStateSnapshot() {}, renderProductListingCenter() {},
  });
  assert.equal(await context.applySaasListingGenerationResult({ status: "report_saved", report_save_attempted: true,
    can_retry: false, task_id: "task", report }, operation, () => true, { draft: "signed" }), true);
  assert.equal(state.saasListingComposerDraft.source_product_fact_report_id, "observed-facts-A");
});

test("a separately observed newer fact version is visible without rebasing retained inputs", () => {
  for (const sameScope of [false, true]) {
    const warnings = [];
    const state = { saasListingComposerDraft: { source_product_fact_report_id: "facts-A" }, saasReports: [
      { report_id: "facts-B", report_type: "merchant.product_facts", status: "saved", created_at: "2026-09-29T02:00:00Z", sameScope },
    ] };
    const view = { saasProductFactEditorGeneration: 1,
      querySelector: selector => selector === '.saas-product-facts-module' ? { prepend: warning => warnings.push(warning) } : null,
      querySelectorAll: () => [] };
    const context = load(["saasLatestObservedListingProductFactReport", "restoreSaasPendingProductFactEditor"], { state,
      saasProductFactEditorScope: () => "scope", saasProductFactEditorFields: () => [],
      saasListingCloudContext: () => ({}), saasListingCloudReportMatchesContext: report => report.sameScope,
      saasTimestampMillis: Date.parse,
      document: { createElement: () => ({ dataset: {}, setAttribute() {}, appendChild() {} }) },
    });
    context.restoreSaasPendingProductFactEditor(view, { scope: "scope", generation: 1, expectedFactReportId: "facts-A",
      fields: [{ key: "material", value: "Unsaved C" }] });
    assert.equal(warnings.length, sameScope ? 1 : 0);
    assert.equal(view.saasProductFactEditorBaseline.pendingBaseReportId, "facts-A");
    assert.equal(state.saasListingComposerDraft.source_product_fact_report_id, "facts-A");
  }
});

test("explicit fact recovery confirms, retains copy and old history, and rejects cancellation or changed scope", () => {
  for (const outcome of ["accept", "cancel", "scope-change", "report-change", "missing"]) {
    let scope = "scope", saved = 0, cleared = 0, invalidated = 0;
    const original = { source_product_fact_report_id: "facts-A", fields: { title: "Unsaved title" },
      merchant_product_fact_packet: { merchant_confirmed_facts: { material: "A" } } };
    const latest = { report_id: "facts-B", report: { merchant_product_fact_packet: { merchant_confirmed_facts: { material: "B" } } } };
    let head = outcome === "missing" ? null : latest;
    const state = { saasListingComposerDraft: original, saasListingProductFactSaveStatus: "local_only", saasReports: [latest] };
    const context = load(["loadSaasLatestListingProductFacts"], {
      state, saasListingAiGenerationEpoch: 1, requireSaasProtectedSessionForAction: () => true,
      saasListingCloudContext: () => ({ key: scope }), saasListingWizardRecord: () => ({ busy: false }),
      saasListingAiGenerationInFlight: new Map(), saasListingAiGenerationContextKey: () => scope,
      saasLatestObservedListingProductFactReport: () => head,
      window: { confirm: message => {
        assert.match(message, /放弃本机未保存的商品资料/); assert.match(message, /Listing 文案保留/);
        if (outcome === "scope-change") scope = "other";
        if (outcome === "report-change") head = { ...latest, report_id: "facts-C" };
        return outcome !== "cancel";
      } },
      applySaasMerchantProductFactPacketToDraft: (draft, packet) => ({ ...draft, merchant_product_fact_packet: packet, fields: { title: "Should not replace copy" } }),
      invalidateSaasListingValidationForFactChange: () => { invalidated += 1; },
      clearSaasPendingProductFactEditor: () => { cleared += 1; }, saveSaasProtectedStateSnapshot: () => { saved += 1; },
      renderProductListingCenter() {}, showActionToast() {},
    });
    assert.equal(context.loadSaasLatestListingProductFacts(), outcome === "accept");
    assert.equal(state.saasListingComposerDraft.source_product_fact_report_id, outcome === "accept" ? "facts-B" : "facts-A");
    assert.equal(state.saasListingComposerDraft.fields.title, "Unsaved title");
    assert.equal(saved, outcome === "accept" ? 1 : 0);
    assert.equal(cleared, saved); assert.equal(invalidated, saved);
    assert.equal(state.saasReports.length, 1);
  }
});
