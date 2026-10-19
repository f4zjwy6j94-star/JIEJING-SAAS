#!/usr/bin/env node
"use strict";

// Supplementary semantic/markup regression, not a DOM or browser runner.
// Execute named real app functions. Only HTTP, storage, timers, concrete slots
// and non-target protected-snapshot persistence are observation boundaries.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

const source = fs.readFileSync(path.join(__dirname, "..", "app.js"), "utf8");
const clone = (value) => JSON.parse(JSON.stringify(value));
function extractFunction(name) {
  const declaration = new RegExp(`^(?:async )?function ${name}\\(`, "m").exec(source);
  assert.ok(declaration, `${name} must exist in real app.js`);
  const tail = source.slice(declaration.index);
  const end = /\n\}\r?(?:\n|$)/.exec(tail);
  assert.ok(end, `${name} must have a complete column-zero closing brace`);
  return tail.slice(0, end.index + 2);
}
function sourceBetween(start, end) {
  const first = source.indexOf(start), last = source.indexOf(end, first + start.length);
  assert.ok(first >= 0 && last > first, `required real source block: ${start}`);
  return source.slice(first, last);
}
const realNames = [
  "escapeHtml", "productizeJiejingProductCopy", "merchantConversationText", "publicRuntimeText",
  "safeQueryParam", "safeStorageValue", "isLocalJiejingOrigin", "isPublicJiejingOrigin",
  "isProtectedSaasAppRoute", "localQaForcesSaasPublicMvpMode", "isSaasPublicMvpMode",
  "normalizeSaasRecordStoreId", "saasRecordStoreId", "sortedSaasDataPackets", "saasKnownStoreCandidates",
  "storedSaasStoreId", "preferredSaasStore", "activeSaasStore", "activeListingDraft",
  "isLegacySampleMediaDraftKey", "saasIsInvalidMarketProductLabel", "saasIsConcreteProductLabel",
  "hashString", "saasNormalizeListingProjectIdentity", "saasCurrentListingProjectIdentity",
  "saasTimestampMillis", "saasCanonicalJsonValue", "saasListingMerchantEditableFieldKeys",
  "saasListingMerchantEditedFields", "saasListingEditableFieldText", "saasListingCloudFields",
  "sanitizeSaasPublishIntakeDraftValues", "saasListingCloudPublishIntake", "saasListingCloudSamePublishIntake",
  "saasListingCloudContext", "saasListingCloudSameIdentity", "saasListingCloudReportMatchesContext",
  "saasListingRewriteReportIsSuperseded", "saasListingCloudBaseReport", "restoreSaasListingCloudBase",
  "saasListingCloudReceipt", "saasListingCloudRecord", "persistSaasListingCloudRecord",
  "invalidateSaasListingCloudCheckpointContext", "applySaasListingCloudFields", "applySaasPublishIntakeCloudRecord",
  "syncSaasListingCloudEditorFields", "syncSaasListingDraftHeading", "saasListingDraftHeading",
  "renderSaasListingCloudCheckpointStatus", "updateSaasListingCloudStatus", "saasListingCloudValidatePayload",
  "hydrateSaasListingCloudCheckpoint", "syncSaasPublishIntakeAfterCloudRead",
  "renderSaasListingRecoveredCheckpointBody", "updateSaasListingRecoveredCheckpointSlots",
  "saasListingAiGenerationContextKey", "sanitizeSaasWorkflowFeedbackText", "saasListingRewriteFeedbackSource",
  "saasListingGenerationOperation", "saasListingGenerationOperationContextKey", "saasListingLegacyGenerationTasks",
  "renderSaasListingAiGenerationFeedback", "reconcileSaasListingRewriteFeedback",
  "parseSaasKeyValueLines", "saasMerchantProductFactDefinitions", "saasMerchantProductFactRequiredKeys",
  "saasMerchantProductFactValuePresent", "saasMerchantProductFactPacket", "saasListingWizardCoreMissing",
  "saasListingWizardRecord", "saasListingWizardGenerationPending",
];

const identity = Object.freeze({ key: "expiry-tablet", source_report_id: "expiry-source", candidate_id: "tablet" });
const expectedFields = Object.freeze({ title: "Original merchant title", selling_points: "Original merchant points",
  description: "Original description", category: "", item_specifics: "Material: Aluminum", keywords: "",
  price: "29 USD", images: "", logistics: "", risk_notes: "" });
const packet = Object.freeze({ contract_version: "merchant_product_fact_packet_v1", source: "authenticated_merchant_request",
  product_name: "Tablet Stand", merchant_confirmed_facts: { product_name: "Tablet Stand", material: "Aluminum" },
  source_confirmed_facts: {}, derived_listing_suggestions: {}, fact_conflicts: [], unknown_facts: [], simulation_only: true });
const report = Object.freeze({ report_id: "expiry-facts", task_id: "expiry-task", company_id: "expiry-company",
  store_id: "expiry-store", user_id: "expiry-user", report_type: "merchant.product_facts", status: "saved",
  created_at: "2026-09-09T01:00:00Z", report: { product_name: "Tablet Stand", listing_project_identity: identity,
    merchant_product_fact_packet: packet } });
const checkpoint = Object.freeze({ checkpoint_id: "expiry-checkpoint", revision: 6, mutation_id: "expiry-mutation",
  company_id: "expiry-company", store_id: "expiry-store", listing_project_identity: identity,
  base_report_id: "expiry-facts", fields: expectedFields, merchant_edited_fields: ["title"],
  saved_at: "2026-09-09T01:00:00Z", source: "merchant_edit" });
const operation = Object.freeze({ operation_id: "743c4370-6ffd-48fa-97ab-bedd060380c8", company_id: "expiry-company",
  user_id: "expiry-user", store_id: "expiry-store", listing_project_identity: identity, generation_mode: "rewrite_buyer_copy",
  expected_base_report_id: "expiry-facts", expected_checkpoint_revision: 6 });
function payload(copy = checkpoint) {
  return clone({ contract_version: "listing_merchant_edit_v1", status: copy ? "saved" : "empty", checkpoint: copy,
    current_revision: copy?.revision || 0, current_base_report_id: "expiry-facts", current_base_report: report,
    base_changed: false, model_called: false, usage_consumed: false, real_platform_writes_enabled: false, secret_exposed: false });
}
function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

function harness(t, { mounted = true, feedback = true, cacheEntries = [] } = {}) {
  const violations = [], requests = [], events = [], timers = new Map();
  const denied = (name) => { violations.push(name); throw new Error(`unexpected fixture boundary: ${name}`); };
  const values = new Map([["jiejing_saas_backend_store_id", "expiry-store"], ...cacheEntries]);
  const localStorage = { getItem: (key) => values.get(key) ?? null,
    setItem(key, value) { values.set(key, String(value)); events.push(["storage", key]); },
    removeItem(key) { values.delete(key); } };
  const slots = {};
  const slot = (name, initial = "") => {
    let html = initial;
    return { hidden: !initial, writes: [], get innerHTML() { return html; },
      set innerHTML(value) { html = String(value); this.writes.push(html); events.push([name, html]); } };
  };
  slots.preview = slot("preview"); slots.cloud = slot("cloud");
  const input = { value: "unsaved material detail", selectionStart: 7, selectionEnd: 12 };
  const facts = { input, scrollTop: 37, get innerHTML() { return "existing facts nodes"; },
    set innerHTML(_value) { denied("whole facts replacement"); } };
  const body = { scrollTop: 149, set innerHTML(_value) { denied("whole page replacement"); } };
  const feedbackSlot = { html: "", get innerHTML() { return this.html; },
    set innerHTML(_value) { denied("feedback controls replaced"); } };
  const checkButton = { action: "listing-check-generation-result", disabled: false };
  const heading = { textContent: "Tablet Stand" };
  const document = { activeElement: input, body,
    querySelector(selector) { if (selector === "#saasPublishIntakeForm") return null; return denied(`querySelector ${selector}`); },
    querySelectorAll(selector) {
      switch (selector) {
        case "[data-saas-listing-recovered-checkpoint-slot]": return mounted ? [slots.preview] : [];
        case "[data-saas-listing-cloud-slot]": return [slots.cloud];
        case "[data-saas-listing-draft-heading]": return [heading];
        case "[data-saas-listing-ai-feedback-slot]": return [feedbackSlot];
        // Cold step 1 has neither copy editor nor publish-intake form.
        case "[data-saas-listing-draft-field]":
        case "[data-saas-publish-intake-draft-status]":
        case "[data-saas-publish-cloud-slot]": return [];
        default: return denied(`querySelectorAll ${selector}`);
      }
    } };
  const state = { saasProtectedStateReady: true, saasProtectedStateFromCache: false, saasSessionExpiryHandled: false,
    saasIdentity: { company_id: "expiry-company", user_id: "expiry-user", role: "owner" },
    saasCompany: { company_id: "expiry-company" }, saasUser: { user_id: "expiry-user" },
    saasStores: [{ store_id: "expiry-store", company_id: "expiry-company", platform: "ebay", marketplace: "EBAY_US" }],
    saasConnections: [], saasSecretRefs: [], saasDataPackets: [], saasReports: [clone(report)], saasTasks: [],
    saasListingComposerInput: "", activeListingDraft: "", saasListingComposerDraft: {
      product: "Tablet Stand", listing_project_identity: clone(identity), source_report_id: "expiry-source",
      merchant_product_fact_packet: clone(packet), merchant_edited_fields: [],
      fields: { ...Object.fromEntries(Object.keys(expectedFields).map((key) => [key, ""])), cost_price: "7.80" },
    } };
  const context = { state, document, localStorage, URLSearchParams,
    window: { location: new URL("http://127.0.0.1:8788/app.html?start=app&qa=public-saas") },
    sessionStorage: { getItem: () => null }, listingDraftCatalog: [], saasStateRefreshGeneration: 0,
    saasListingCloudRecords: new Map(), saasListingCloudEpoch: 0, saasListingWizardRecords: new Map(),
    saasListingAiGenerationInFlight: new Map(), SAAS_LISTING_CLOUD_CONTRACT: "listing_merchant_edit_v1",
    SAAS_MERCHANT_PRODUCT_FACT_PACKET_CONTRACT: "merchant_product_fact_packet_v1",
    setTimeout(callback, delay) {
      if (delay !== 1000) return denied(`timer ${delay}`);
      const id = timers.size + 1; timers.set(id, { callback, delay }); return id;
    }, clearTimeout(id) { timers.delete(id); },
    saveSaasProtectedStateSnapshot() { events.push(["protected-snapshot-boundary"]); },
    saasFetchWithTimeout(route, options, timeout) {
      try {
        assert.equal(route, "/stores/expiry-store/listing-drafts/expiry-tablet/checkpoint?source_report_id=expiry-source&candidate_id=tablet");
        assert.deepEqual(Object.keys(options).sort(), ["saasDeferUnauthorizedTermination", "saasRequestIsCurrent"]);
        assert.equal(options.saasDeferUnauthorizedTermination, true); assert.equal(timeout, 15000);
        assert.equal(typeof options.saasRequestIsCurrent, "function");
        assert.equal(options.saasRequestIsCurrent(), true);
      } catch (error) {
        violations.push("checkpoint transport contract"); throw error;
      }
      const waiting = deferred(); requests.push({ route, options, timeout, waiting }); return waiting.promise;
    },
    // These branches are outside E01's fixed current-base/no-publish fixture.
    // Tripwires fail the case even if a real app catch converts the error.
    restoreSaasListingComposerDraftFromBackendReports() { return denied("unrequested base replacement"); },
    flushSaasListingCloudCheckpoint() { return denied("checkpoint write"); },
    saasListingBuyerCopyRewriteFromReport() { return denied("unrequested rewrite report"); },
    releaseSaasListingAiGenerationButtons() { return denied("generation controls changed"); },
  };
  // Preserve the actual normalization constants rather than inventing identity
  // rules. No complete app evaluation, init tail, DOM parser, browser or sockets.
  const constants = sourceBetween("const legacyExecutionBrand =", "function productizeJiejingProductCopy(") +
    sourceBetween("const saasStorageKeys = {", "function resolveJiejingApiBase(");
  assert.doesNotMatch(constants, /^(?:async )?function /m, "constant block must not pull in unrelated functions");
  vm.createContext(context);
  vm.runInContext(constants + "\n" + realNames.map(extractFunction).join("\n"), context, { timeout: 1000 });
  const scope = context.saasListingCloudContext();
  assert.deepEqual(clone(scope.identity), clone(identity));
  assert.equal(scope.key, JSON.stringify(["expiry-company", "expiry-user", "expiry-store", "expiry-tablet", "expiry-source", "tablet"]));
  const draft = state.saasListingComposerDraft;
  if (feedback) draft.ai_generation_feedback = { status: "generation_uncertain", operation: clone(operation),
    rewrite_source: { base_report_id: "expiry-facts", revision: 6 }, result_report_id: null,
    input_signature: "a".repeat(64), request_signature: "b".repeat(64),
    context_key: context.saasListingAiGenerationContextKey(), message: "Old local response" };
  feedbackSlot.html = context.renderSaasListingAiGenerationFeedback();
  const originalFeedback = clone(draft.ai_generation_feedback || null), originalFacts = clone(draft.merchant_product_fact_packet);
  const originalFeedbackHtml = feedbackSlot.html;
  const wizard = context.saasListingWizardRecord();
  assert.equal(wizard.step, 1); assert.deepEqual(clone(context.saasListingWizardCoreMissing()), ["condition"]);
  if (mounted) slots.preview.innerHTML = context.renderSaasListingRecoveredCheckpointBody();
  t.after(() => { assert.deepEqual(violations, [], "no caught unsupported fixture path"); });
  function unchanged() {
    assert.equal(context.saasListingWizardRecord(), wizard); assert.equal(wizard.step, 1);
    assert.equal(state.saasListingComposerDraft, draft); assert.equal(facts.input, input);
    assert.equal(input.value, "unsaved material detail"); assert.equal(input.selectionStart, 7); assert.equal(input.selectionEnd, 12);
    assert.equal(document.activeElement, input); assert.equal(facts.scrollTop, 37); assert.equal(body.scrollTop, 149);
    assert.deepEqual(clone(draft.merchant_product_fact_packet), originalFacts);
    assert.deepEqual(clone(draft.ai_generation_feedback || null), originalFeedback);
    assert.equal(feedbackSlot.innerHTML, originalFeedbackHtml); assert.equal(checkButton.disabled, false);
    assert.equal(context.saasListingWizardGenerationPending(), feedback);
    assert.equal((context.renderSaasListingAiGenerationFeedback().match(/data-saas-action="listing-check-generation-result"/g) || []).length, feedback ? 1 : 0);
    assert.doesNotMatch(context.renderSaasListingAiGenerationFeedback(), /data-saas-action="listing-resume-generation"/);
    assert.equal(draft.fields.cost_price, "7.80"); assert.deepEqual(violations, []);
  }
  async function read(result = payload()) {
    const before = requests.length, promise = context.hydrateSaasListingCloudCheckpoint({ force: true });
    assert.equal(requests.length, before + 1);
    const request = requests.at(-1); request.waiting.resolve(clone(result));
    return promise;
  }
  return { context, state, scope, draft, slots, requests, events, timers, values, unchanged, read,
    mountPreview() {
      mounted = true;
      // This exercises the real first-projection renderer, not a DOM mount.
      // Exact real module/wizard mount callsites are separately structural.
      slots.preview.innerHTML = context.renderSaasListingRecoveredCheckpointBody();
      slots.preview.hidden = !slots.preview.innerHTML;
    }, record: () => context.saasListingCloudRecord() };
}
function expectBody(h, fields = expectedFields) {
  const html = h.slots.preview.innerHTML;
  assert.equal(h.slots.preview.hidden, false);
  assert.match(html, /data-saas-listing-recovered-checkpoint\b/);
  for (const name of ["title", "selling_points", "description"]) {
    assert.ok(html.includes(`data-saas-listing-recovered-field="${name}"`));
    assert.ok(html.includes(h.context.escapeHtml(fields[name] === "" ? "已清空" : fields[name])));
  }
  assert.match(html, /white-space:pre-wrap/);
  assert.doesNotMatch(html, /<(?:input|textarea|button|script|iframe)\b|contenteditable|data-saas-action=/i);
}

test("E01 structural first-mount callsites exist beside feedback in facts and step 2", () => {
  const facts = extractFunction("renderSaasMerchantProductFactsModule");
  const wizard = extractFunction("renderSaasListingWizard");
  for (const fn of [facts, wizard]) {
    assert.match(fn, /const recoveredCheckpoint = renderSaasListingRecoveredCheckpointBody\(draft\);/);
    assert.match(fn, /data-saas-listing-ai-feedback-slot[\s\S]*data-saas-listing-recovered-checkpoint-slot/);
    assert.match(fn, /data-saas-listing-recovered-checkpoint-slot \$\{recoveredCheckpoint \? "" : "hidden"\}>\$\{recoveredCheckpoint\}/);
  }
  const feedback = extractFunction("renderSaasListingAiGenerationFeedback");
  assert.doesNotMatch(feedback, /RecoveredCheckpoint/, "preview does not depend on feedback's early-return path");
});

test("real hydrate validates R6, applies exact fields and updates only preview after its read retires", async (t) => {
  const h = harness(t);
  const promise = h.context.hydrateSaasListingCloudCheckpoint();
  assert.equal(h.requests.length, 1); assert.ok(h.record().read);
  assert.equal(h.context.renderSaasListingRecoveredCheckpointBody(), "");
  assert.equal(h.slots.preview.hidden, true);
  h.requests[0].waiting.resolve(payload());
  assert.equal(await promise, true);
  assert.equal(h.record().read, null); assert.equal(h.record().loaded, true); assert.equal(h.record().revision, 6);
  assert.deepEqual(clone(h.context.saasListingCloudFields(h.draft.fields)), clone(expectedFields));
  assert.deepEqual(clone(h.draft.merchant_edited_fields), ["title"]);
  assert.deepEqual(clone(h.record().receipt.fields), clone(expectedFields));
  expectBody(h); h.unchanged(); assert.equal(h.requests.length, 1); assert.equal(h.timers.size, 0);
});

test("read-before-slot semantic projection works without feedback; actual mount remains structural/UI responsibility", async (t) => {
  const h = harness(t, { mounted: false, feedback: false });
  assert.equal(await h.read(), true); assert.equal(h.slots.preview.innerHTML, "");
  h.mountPreview(); expectBody(h); h.unchanged();
});

test("a cached valid receipt never projects before a new authenticated read", async (t) => {
  const fresh = harness(t); assert.equal(await fresh.read(), true);
  const cacheKey = `jiejing_listing_cloud_v1:${fresh.scope.key}`;
  const cold = harness(t, { cacheEntries: [[cacheKey, fresh.values.get(cacheKey)]] });
  assert.ok(cold.record().receipt); assert.equal(cold.record().loaded, false);
  assert.equal(cold.context.renderSaasListingRecoveredCheckpointBody(), "");
  assert.equal(cold.draft.fields.title, ""); assert.equal(cold.requests.length, 0); cold.unchanged();
});

test("a new read hides old saved preview, then failed read cannot expose the old receipt", async (t) => {
  const h = harness(t); assert.equal(await h.read(), true); expectBody(h);
  const promise = h.context.hydrateSaasListingCloudCheckpoint({ force: true });
  assert.equal(h.slots.preview.hidden, true); assert.equal(h.slots.preview.innerHTML, "");
  h.requests.at(-1).waiting.reject(Object.assign(new Error("fixed synthetic failure"), { status: 503 }));
  assert.equal(await promise, false); assert.equal(h.record().status, "error"); assert.equal(h.record().read, null);
  assert.equal(h.slots.preview.innerHTML, ""); h.unchanged();
});

test("no checkpoint does not invent saved body", async (t) => {
  const h = harness(t); assert.equal(await h.read(payload(null)), true);
  assert.equal(h.record().status, "idle"); assert.equal(h.draft.fields.title, "");
  assert.equal(h.slots.preview.innerHTML, ""); h.unchanged();
});

for (const [label, corrupt] of [
  ["foreign company receipt", (p) => { p.checkpoint.company_id = "other-company"; }],
  ["foreign store receipt", (p) => { p.checkpoint.store_id = "other-store"; }],
  ["foreign project receipt", (p) => { p.checkpoint.listing_project_identity.candidate_id = "other-candidate"; }],
  ["invalid receipt field type", (p) => { p.checkpoint.fields.title = 42; }],
  ["invalid current base identity", (p) => { p.current_base_report.report.listing_project_identity.source_report_id = "other-source"; }],
]) test(label + " is rejected by real validation with no preview", async (t) => {
  const h = harness(t), p = payload(); corrupt(p);
  assert.equal(await h.read(p), false); assert.equal(h.record().status, "error");
  assert.equal(h.draft.fields.title, ""); assert.equal(h.slots.preview.innerHTML, ""); h.unchanged();
});

test("older-base conflict retains current draft and does not call it restored saved body", async (t) => {
  const h = harness(t), p = payload(); p.checkpoint.base_report_id = "older-facts";
  assert.equal(await h.read(p), true); assert.equal(h.record().status, "conflict");
  assert.equal(h.draft.fields.title, ""); assert.equal(h.slots.preview.innerHTML, ""); h.unchanged();
});

for (const [label, change] of [
  ["company", (h) => { h.state.saasIdentity.company_id = "other-company"; h.state.saasCompany.company_id = "other-company"; }],
  ["user", (h) => { h.state.saasIdentity.user_id = "other-user"; h.state.saasUser.user_id = "other-user"; }],
  ["store", (h) => { h.state.saasStores = [{ store_id: "other-store", platform: "ebay" }]; h.values.set("jiejing_saas_backend_store_id", "other-store"); }],
  ["project key", (h) => { h.draft.listing_project_identity.key = "other-project"; }],
  ["source", (h) => { h.draft.listing_project_identity.source_report_id = "other-source"; }],
  ["candidate", (h) => { h.draft.listing_project_identity.candidate_id = "other-candidate"; }],
]) test(`delayed old ${label} response cannot project or update the new scope`, async (t) => {
  const h = harness(t), oldRecord = h.record(), promise = h.context.hydrateSaasListingCloudCheckpoint();
  change(h); h.context.invalidateSaasListingCloudCheckpointContext();
  const afterSwitchWrites = h.slots.preview.writes.length;
  assert.equal(h.requests[0].options.saasRequestIsCurrent(), false);
  h.requests[0].waiting.resolve(payload()); assert.equal(await promise, false);
  assert.equal(oldRecord.read, null); assert.equal(h.slots.preview.writes.length, afterSwitchWrites);
  assert.equal(h.slots.preview.innerHTML, ""); assert.equal(h.draft.fields.title, "");
});

test("old refresh read cannot retire or project over a new read in the same scope", async (t) => {
  const h = harness(t), old = h.context.hydrateSaasListingCloudCheckpoint();
  h.context.saasStateRefreshGeneration += 1;
  const current = h.context.hydrateSaasListingCloudCheckpoint({ force: true }), ownedRead = h.record().read;
  assert.equal(h.requests.length, 2);
  h.requests[0].waiting.resolve(payload()); assert.equal(await old, false);
  assert.equal(h.record().read, ownedRead); assert.equal(h.slots.preview.innerHTML, "");
  h.requests[1].waiting.resolve(payload()); assert.equal(await current, true);
  assert.equal(h.record().read, null); expectBody(h); h.unchanged();
});

for (const [label, mutate] of [
  ["not authenticated", (h, r) => { h.state.saasProtectedStateReady = false; }],
  ["cached auth", (h, r) => { h.state.saasProtectedStateFromCache = true; }],
  ["expired session", (h, r) => { h.state.saasSessionExpiryHandled = true; }],
  ["not loaded", (h, r) => { r.loaded = false; }],
  ["old refresh generation", (h, r) => { h.context.saasStateRefreshGeneration += 1; }],
  ["different observed base", (h, r) => { r.observedBaseReportId = "older-facts"; }],
  ["different record base", (h, r) => { r.baseReportId = "older-facts"; }],
  ["different current base", (h, r) => { h.state.saasReports[0].report_id = "newer-facts"; }],
  ["dirty", (h, r) => { r.dirty = true; }],
  ["pending", (h, r) => { r.pending = { mutation_id: "pending-mutation" }; }],
  ["conflicting", (h, r) => { r.conflict = {}; }],
  ["read pending", (h, r) => { r.read = Promise.resolve(); }],
  ["write pending", (h, r) => { r.write = Promise.resolve(); }],
  ["error status", (h, r) => { r.status = "error"; }],
  ["receipt revision mismatch", (h, r) => { r.receipt.revision += 1; }],
  ["receipt base mismatch", (h, r) => { r.receipt.base_report_id = "older-facts"; }],
  ["record fields mismatch", (h, r) => { r.fields = { ...r.fields, title: "unsaved record" }; }],
  ["draft fields mismatch", (h, r) => { h.draft.fields.title = "unsaved draft"; }],
  ["record edited flags mismatch", (h, r) => { r.edited = []; }],
  ["draft edited flags mismatch", (h, r) => { h.draft.merchant_edited_fields = []; }],
  ["publish intake mismatch", (h, r) => { r.receipt.publish_intake = { values: { title: "other" }, basis: {} }; }],
]) test(`saved preview refuses ${label}`, async (t) => {
  const h = harness(t); assert.equal(await h.read(), true); expectBody(h);
  mutate(h, h.record()); h.context.updateSaasListingRecoveredCheckpointSlots();
  assert.equal(h.slots.preview.hidden, true); assert.equal(h.slots.preview.innerHTML, "");
  assert.equal(h.requests.length, 1);
});

test("real read with local copy edits preserves edits as conflict and never labels them saved", async (t) => {
  const h = harness(t), promise = h.context.hydrateSaasListingCloudCheckpoint(), r = h.record();
  r.fields = { ...clone(expectedFields), title: "Unsaved local title" }; r.edited = ["title"];
  r.dirty = true; r.copyDirty = true; r.seq += 1;
  h.requests[0].waiting.resolve(payload()); assert.equal(await promise, true);
  assert.equal(r.status, "conflict"); assert.equal(h.draft.fields.title, "Unsaved local title");
  assert.equal(h.slots.preview.innerHTML, ""); h.unchanged();
});

test("safe read-only presentation escapes markup and preserves line breaks and intentional clears", async (t) => {
  const h = harness(t), p = payload();
  p.checkpoint.fields.title = '<img src=x onerror="alert(1)">&\'title';
  p.checkpoint.fields.selling_points = "Line one\nLine two";
  p.checkpoint.fields.description = "";
  const expected = clone(p.checkpoint.fields);
  assert.equal(await h.read(p), true); expectBody(h, expected);
  assert.ok(h.slots.preview.innerHTML.includes("&lt;img"));
  assert.ok(h.slots.preview.innerHTML.includes("Line one\nLine two"));
  assert.doesNotMatch(h.slots.preview.innerHTML, /<img\b/); h.unchanged();
});

test("targeted projection is idempotent and has no persistence, form, control or network side effects", async (t) => {
  const h = harness(t); assert.equal(await h.read(), true); expectBody(h);
  const eventCount = h.events.length, writeCount = h.slots.preview.writes.length;
  const before = JSON.stringify(h.draft);
  h.context.updateSaasListingRecoveredCheckpointSlots(); h.context.updateSaasListingRecoveredCheckpointSlots();
  assert.equal(h.slots.preview.writes.length, writeCount); assert.equal(h.events.length, eventCount);
  assert.equal(JSON.stringify(h.draft), before); assert.equal(h.requests.length, 1); assert.equal(h.timers.size, 0);
  h.unchanged();
});
