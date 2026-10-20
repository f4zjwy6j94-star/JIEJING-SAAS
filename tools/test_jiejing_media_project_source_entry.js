#!/usr/bin/env node
"use strict";

// Offline UI-event regression. No browser session, provider call or live data.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const test = require("node:test");
const root = path.resolve(__dirname, "..");
const source = fs.readFileSync(path.join(root, "app.js"), "utf8");
const html = fs.readFileSync(path.join(root, "app.html"), "utf8");

function extract(name) {
  const match = new RegExp(`(?:async )?function ${name}\\(`).exec(source);
  assert.ok(match, `${name} exists`);
  const tail = source.slice(match.index);
  const end = tail.search(/\n(?:async )?function /);
  return end < 0 ? tail : tail.slice(0, end);
}

function fixture() {
  const elements = new Map();
  for (const [, id] of html.matchAll(/\bid="([^"]+)"/g)) {
    elements.set(`#${id}`, {
      dataset: {}, value: "", clicks: 0, listeners: new Map(), classList: { add() {}, remove() {} },
      addEventListener(type, callback) {
        const callbacks = this.listeners.get(type) || [];
        callbacks.push(callback); this.listeners.set(type, callbacks);
      },
      click() { this.clicks += 1; for (const callback of this.listeners.get("click") || []) callback({ target: this }); },
      emit(type, extra = {}) { for (const callback of this.listeners.get(type) || []) callback({ target: this, ...extra }); },
    });
  }
  const view = elements.get("#view-media");
  view.querySelector = selector => elements.get(selector) || null;
  const identity = { key: "fixture-project", source_report_id: "fixture-report", candidate_id: "fixture-candidate" };
  const state = { activeMediaDraft: "fixture-media", mediaTaskEntry: "project",
    view: "media", saasIdentity: { user_id: "fixture-user", company_id: "fixture-company" },
    saasUser: { user_id: "fixture-user" }, saasCompany: { company_id: "fixture-company" },
    saasListingComposerDraft: { product: "Fixture measuring cups", listing_project_identity: identity,
      fields: { title: "Saved listing title" } } };
  const requests = [], sessionRequests = [], toasts = [], ui = {};
  const storage = new Map();
  const durableStorage = new Map();
  const context = { state, URL, AbortController, setTimeout, clearTimeout, crypto: require("node:crypto").webcrypto,
    saasMediaSourceReviewUrls: new WeakMap(),
    sessionStorage: { getItem: key => storage.get(key) || null, setItem: (key, value) => storage.set(key, value), removeItem: key => storage.delete(key) },
    localStorage: { getItem: key => durableStorage.get(key) || null, setItem: (key, value) => durableStorage.set(key, value), removeItem: key => durableStorage.delete(key) },
    saasAccountSessionEpoch: 0,
    SAAS_BROWSER_SESSION_REFRESH_TIMEOUT_MS: 10000, location: { hostname: "127.0.0.1" },
    window: { location: { href: "http://127.0.0.1/app.html?view=media&project=fixture-project" },
      addEventListener() {}, removeEventListener() {} },
    MutationObserver: class { observe() {} disconnect() {} takeRecords() { return []; } },
    document: { body: {}, querySelector: selector => elements.get(selector) || null },
    hasSaasProtectedSessionCandidate: () => true,
    saasCurrentListingProjectIdentity: draft => draft?.listing_project_identity || {},
    showActionToast: text => toasts.push(text),
    setMediaChannelMode() {}, readMediaGenerationConfig: overrides => overrides || {},
    inferMediaLocalPath: file => ({ path: file.name, note: "Local fixture" }),
    setText: (selector, value) => { ui[selector] = value; },
    syncMediaGenerationActionState() {}, syncMediaRequirementSummary() {}, refreshSaasMediaGeneratedAssetSurfaces() {}, publicRuntimeText: value => String(value),
    saveSaasProtectedStateSnapshot() {},
    saasMediaJobHasCurrentSessionBackendEvidence: job => job?.fresh === true,
    activeSaasStore: () => ({ store_id: "fixture-store" }),
    saasFetch: async (url, options) => {
      assert.notEqual(options.saasRequestIsCurrent?.(), false, "the real media guard must accept this fixture scope");
      if (url === "/me") {
        sessionRequests.push({ url, options });
        return { user: state.saasUser, company: state.saasCompany, identity: state.saasIdentity };
      }
      requests.push({ url, options });
      return { provider_reference_ready: true, media_source_asset: { asset_id: "fixture-asset", sha256: "aa",
        source_url: "https://example.test/private-source", rights_status: "unknown" } };
    },
  };
  vm.createContext(context);
  for (const name of ["saasNormalizeListingProjectIdentity", "createSaasMediaMutationGuard",
    "sanitizeSaasMediaUploadReceipt", "createSaasMediaRecoveryGuard",
    "saasMediaAssetJobProductFacts", "saasMediaRecoveryJobs", "saasMediaRecoveryJob", "renderSaasMediaRecoveryChoices", "maybeRecoverSaasMediaSourceUpload",
    "saasMediaMutationResultIsUncertain", "saasMediaMutationUncertainMessage", "ensureSaasMediaMutationSession",
    "ensureSaasProtectedSessionForMutation", "assertSaasLiveIdentityScope",
    "saasMediaUploadScope", "saasMediaUploadReceipt", "rememberSaasMediaUploadReceipt", "saasIndependentMediaSelectValues", "rememberSaasIndependentMediaDraft", "restoreSaasIndependentMediaDraft", "saasMediaSourceAssetFromResponse", "recoverSaasMediaSourceUpload", "saasMediaVideoGenerationGate", "saasIndependentMediaProductName",
    "setMediaNewTaskMode", "uploadSaasMediaSourceFile", "handleMediaSourceFile", "bindMediaSourceUploadEvents"]) {
    vm.runInContext(extract(name), context);
  }
  return { context, state, elements, view, requests, sessionRequests, toasts, ui, storage, durableStorage };
}

test("reopened tab recovers the exact safe receipt with GET, not a new paid job", async () => {
  const f = fixture();
  f.context.rememberSaasMediaUploadReceipt(f.context.saasMediaUploadScope(), {
    upload_id: "fixture_durable_upload_1234", status: "completed", created_at: Date.now(),
    source_url: "https://private.test/?signature=must-not-persist", rights_confirmed: true,
  });
  f.storage.clear(); f.state.saasMediaUploadReceipts = {};
  await f.context.recoverSaasMediaSourceUpload();
  assert.equal(f.state.saasMediaSourceUpload?.asset_id, "fixture-asset");
  assert.equal(f.requests.length, 1);
  assert.equal(f.requests[0].options.method, "GET");
  assert.doesNotMatch([...f.durableStorage.values()].join(), /signature=|rights_confirmed|source_url/);
});

test("entering the independent channel restores its saved source without a second manual button", async () => {
  const f = fixture();
  f.state.mediaTaskEntry = "single";
  f.context.rememberSaasMediaUploadReceipt(f.context.saasMediaUploadScope(), {
    upload_id: "fixture_channel_restore_1234", status: "completed", created_at: Date.now(),
  });
  f.state.mediaTaskEntry = "project";
  f.context.setMediaNewTaskMode({ recover: true });
  await new Promise(setImmediate);
  assert.equal(f.state.saasMediaSourceUpload?.asset_id, "fixture-asset");
  assert.equal(f.requests.length, 1);
  assert.equal(f.requests[0].options.method, "GET");
});

test("read-only recovery survives an unrelated Listing hydration while independent mode is unchanged", async () => {
  const f = fixture(); f.state.mediaTaskEntry = "single";
  f.context.rememberSaasMediaUploadReceipt(f.context.saasMediaUploadScope(), {
    upload_id: "fixture_hydrating_upload_1234", status: "completed", created_at: Date.now(),
  });
  let resolve;
  f.context.saasFetch = () => new Promise(done => { resolve = done; });
  const pending = f.context.recoverSaasMediaSourceUpload();
  f.state.saasListingComposerDraft = { listing_project_identity: { key: "hydrated-unrelated-listing" } };
  f.context.window.location.href += "&project=hydrated-unrelated-listing";
  resolve({ provider_reference_ready: true, media_source_asset: { asset_id: "fixture-asset", source_url: "https://example.test/source" } });
  await pending;
  assert.equal(f.state.saasMediaSourceUpload?.asset_id, "fixture-asset");
});

test("lost browser receipt restores only one unambiguous server-backed independent source", async () => {
  const f=fixture(); f.state.mediaTaskEntry="single";
  f.state.saasMediaAssetJobs=[{ fresh:true,media_job_id:"media_job_fixture_restore",company_id:"fixture-company",store_id:"fixture-store",created_by:"fixture-user",
    job_spec:{inputs:{product_facts:{source_asset_id:"fixture-asset",product:"Storage box"},image_sizes:["1600×1600"],image_count:1}} }];
  f.context.saasFetch=async (url,options)=>{
    f.requests.push({url,options});
    return {media_job_id:"media_job_fixture_restore",upload_id:"fixture_restored_by_job_1234",provider_reference_ready:true,
      media_source_asset:{asset_id:"fixture-asset",source_url:"https://example.test/source",created_at:100}};
  };
  await f.context.maybeRecoverSaasMediaSourceUpload();
  assert.equal(f.requests.length,1);
  assert.match(f.requests[0].url,/media-asset-jobs\/media_job_fixture_restore\/source$/);
  assert.equal(f.requests[0].options.method,"GET");
  assert.equal(f.state.saasIndependentMediaProduct.product,"Storage box");
  assert.equal(f.context.saasMediaUploadReceipt().upload_id,"fixture_restored_by_job_1234");
});

test("cached, foreign, Listing-bound and ambiguous jobs never silently select a new source", async () => {
  const f=fixture(); f.state.mediaTaskEntry="single";
  const job={fresh:true,media_job_id:"media_job_fixture_restore",company_id:"fixture-company",store_id:"fixture-store",created_by:"fixture-user",job_spec:{inputs:{product_facts:{source_asset_id:"source-a"}}}};
  for(const invalid of [{...job,fresh:false},{...job,created_by:"other-user"},{...job,store_id:"other-store"},
    {...job,job_spec:{inputs:{product_facts:{source_asset_id:"source-a",listing_project_key:"old-project"}}}}]) {
    f.state.saasMediaAssetJobs=[invalid];
    await f.context.maybeRecoverSaasMediaSourceUpload();
    assert.equal(f.requests.length,0);
  }
  f.state.saasMediaAssetJobs=[job,{...job,media_job_id:"media_job_other",job_spec:{inputs:{product_facts:{source_asset_id:"source-b"}}}}];
  await f.context.maybeRecoverSaasMediaSourceUpload();
  assert.equal(f.requests.length,0);
});

test("current product exposes a source picker without switching to an independent task", () => {
  const start = html.indexOf('<div class="media-source-card">');
  const end = html.indexOf('<div class="media-queue-board"', start);
  assert.match(html.slice(start, end), /id="mediaProjectSourceButton"/, "source picker belongs to current product, not hidden independent channel");
  const f = fixture();
  const before = JSON.stringify(f.state);
  f.context.bindMediaSourceUploadEvents(f.view);
  f.context.bindMediaSourceUploadEvents(f.view);
  f.elements.get("#mediaProjectSourceButton").click();
  assert.equal(f.elements.get("#mediaSourceFileInput").clicks, 1);
  assert.equal(JSON.stringify(f.state), before, "opening or cancelling the chooser must preserve the Listing and project");
  assert.equal(f.requests.length, 0, "opening the picker must not upload, generate, spend or publish");
});

test("source selection uploads once to the current product and never confirms rights or starts generation", async () => {
  const f = fixture();
  f.context.bindMediaSourceUploadEvents(f.view);
  f.context.bindMediaSourceUploadEvents(f.view);
  const input = f.elements.get("#mediaSourceFileInput");
  const file = new Blob(["local test bytes"], { type: "image/png" });
  file.name = "local-test.png";
  input.files = [file]; input.value = file.name;
  input.emit("change");
  await new Promise(setImmediate);
  assert.equal(f.requests.length, 1);
  assert.equal(f.sessionRequests.length, 1, "the source picker must safely preflight before its sole upload");
  assert.equal(f.requests[0].url, "/stores/fixture-store/media-source-assets");
  assert.equal(f.requests[0].options.body, file);
  assert.equal(input.value, "");
  assert.equal(f.state.mediaTaskEntry, "project");
  assert.equal(f.state.saasMediaSourceUpload.listing_project_key, "fixture-project");
  assert.equal(f.state.saasMediaSourceUpload.rights_status, "unknown");
  assert.equal(f.state.saasMediaSourceUpload.source_url, undefined, "signed source URL must not be retained");
  assert.equal(f.state.saasListingComposerDraft.fields.title, "Saved listing title");
  assert.equal(f.state.saasListingComposerDraft.publish_prefill, undefined);
  assert.match(f.ui["#mediaProjectSourceStatus"], /已上传/);
  URL.revokeObjectURL(f.state.mediaSourceObjectUrl);
});

test("failed upload keeps the saved Listing and renders a retry next to the project picker", async () => {
  const f = fixture();
  f.context.saasFetch = async () => { throw new Error("fixture upload rejected"); };
  f.context.bindMediaSourceUploadEvents(f.view);
  const file = new Blob(["local test bytes"], { type: "image/png" }); file.name = "local-test.png";
  const input = f.elements.get("#mediaSourceFileInput"); input.files = [file]; input.emit("change");
  await new Promise(setImmediate);
  assert.equal(f.state.saasMediaSourceUpload, null);
  assert.equal(f.state.saasListingComposerDraft.fields.title, "Saved listing title");
  assert.match(f.ui["#mediaProjectSourceStatus"], /未上传成功.*重新选择图片/);
  URL.revokeObjectURL(f.state.mediaSourceObjectUrl);
});

test("no current product is not silently turned into a new Listing, and independent upload remains available", () => {
  const f = fixture();
  f.state.saasListingComposerDraft = null;
  f.context.bindMediaSourceUploadEvents(f.view);
  f.elements.get("#mediaProjectSourceButton").click();
  assert.equal(f.elements.get("#mediaSourceFileInput").clicks, 0);
  assert.match(f.toasts.at(-1), /选品与上架/);
  f.elements.get("#mediaBrowseFileButton").click();
  assert.equal(f.elements.get("#mediaSourceFileInput").clicks, 1);
  assert.equal(f.requests.length, 0);
  assert.equal(f.state.saasListingComposerDraft, null);
});

test("startup and restored DOM share the same upload binding", () => {
  assert.match(extract("bindRestoredMediaStudioEvents"), /bindMediaSourceUploadEvents\(view\)/);
  assert.match(extract("init"), /bindEvents\(\)/);
  assert.match(extract("bindEvents"), /bindMediaSourceUploadEvents\(\)/);
  assert.equal((source.match(/handleMediaSourceFile\(event\.target\.files/g) || []).length, 1);
});

test("refreshing another product cannot keep the previous product's uploaded status", () => {
  const f = fixture();
  let facts = { source_asset_id: "fixture-asset" };
  Object.assign(f.context, {
    currentMediaStudioProductFacts: () => facts,
    latestSaasMediaAssetJobWithManifest: () => null,
    saasApprovedMediaWritebackGate: () => ({ allowed: false }),
    saasMediaJobHasCurrentSessionBackendEvidence: () => false,
  });
  for (const name of ["saasMediaGenerationGroundingGate", "syncMediaGenerationActionState"]) vm.runInContext(extract(name), f.context);
  const config = { qualityMode: "fidelity_first", videoDurationSeconds: 0, count: "1 张", entryLabel: "当前商品" };
  f.context.syncMediaGenerationActionState(config);
  assert.match(f.ui["#mediaProjectSourceStatus"], /已关联/);
  facts = {}; f.state.saasMediaSourceUpload = null;
  f.state.saasListingComposerDraft = { product: "Other product", listing_project_identity: { key: "another-project" } };
  f.context.syncMediaGenerationActionState(config);
  assert.doesNotMatch(f.ui["#mediaProjectSourceStatus"], /已关联|已上传/);
  assert.equal(f.elements.get("#mediaProjectSourceButton").textContent, "上传本商品来源图");
  assert.equal(f.elements.get("#mediaGenerateImagesDraft").disabled, true);
  f.state.saasListingComposerDraft = null;
  f.context.syncMediaGenerationActionState(config);
  assert.equal(f.elements.get("#mediaProjectSourceButton").disabled, true);
});

test("independent source facts never inherit an open Listing or its saved source image", () => {
  const f = fixture();
  const originalDraft = JSON.stringify(f.state.saasListingComposerDraft);
  f.state.mediaTaskEntry = "single";
  Object.assign(f.context, {
    isSaasPublicMvpMode: () => true,
    saasMerchantWorkbenchContext: () => ({ store: { marketplace: "EBAY_US" } }),
    activeListingDraft: () => ({ titleCn: "Old tablet stand", material: "steel" }),
    isLegacySampleMediaDraftKey: () => false,
    latestSaasReportByTypes: () => ({ title: "Old tablet stand report" }),
    saasMediaSourceAssetForListingDraft: draft => draft.product ? { asset_id: "old-listing-source" } : null,
  });
  vm.runInContext(extract("currentMediaStudioProductFacts"), f.context);
  let facts = f.context.currentMediaStudioProductFacts({ entry: "single" });
  assert.equal(facts.listing_project_key || "", "", "new independent work must not bind to the old Listing");
  assert.equal(facts.source_asset_id, "", "old source must not satisfy a new task's grounding gate");
  assert.equal(facts.product, "当前商品");
  assert.equal(facts.supplier_facts.material, "待补");
  f.state.saasMediaSourceUpload = { asset_id: "new-box-source", sha256: "bb", listing_project_key: "", rights_status: "unknown" };
  facts = f.context.currentMediaStudioProductFacts({ entry: "single" });
  assert.equal(facts.source_asset_id, "new-box-source");
  assert.equal(JSON.stringify(f.state.saasListingComposerDraft), originalDraft, "the saved Listing must remain intact");
});

test("upload in independent mode has no old Listing binding even while its draft is open", async () => {
  const f = fixture();
  f.state.mediaTaskEntry = "single";
  const before = JSON.stringify(f.state.saasListingComposerDraft);
  const file = new Blob(["new box"], { type: "image/png" }); file.name = "box.png";
  await f.context.handleMediaSourceFile(file);
  assert.equal(f.requests.length, 1);
  assert.equal(f.state.saasMediaSourceUpload.listing_project_key, "");
  assert.equal(f.state.saasMediaSourceUpload.listing_project_identity, null);
  assert.equal(JSON.stringify(f.state.saasListingComposerDraft), before);
  URL.revokeObjectURL(f.state.mediaSourceObjectUrl);
});

test("a lost upload response is recovered by its exact attempt using GET, never a second POST", async () => {
  const f = fixture();
  const requests = [];
  f.context.saasFetch = async (url, options = {}) => {
    if (url === "/me") return { user: f.state.saasUser, company: f.state.saasCompany, identity: f.state.saasIdentity };
    assert.notEqual(options.saasRequestIsCurrent?.(), false);
    requests.push({ url, options });
    if (options.method === "POST") throw new TypeError("fixture connection lost after saving");
    return { upload_status: "completed", provider_reference_ready: true,
      media_source_asset: { asset_id: "recovered-box", sha256: "cc", source_url: "https://example.test/private-source" } };
  };
  const file = new Blob(["box"], { type: "image/png" }); file.name = "box.png";
  await f.context.handleMediaSourceFile(file);
  assert.equal(requests.length, 2, "unknown upload must be followed by one read-only receipt lookup");
  assert.equal(requests[0].options.method, "POST");
  const uploadId = requests[0].options.headers["x-jiejing-upload-id"];
  assert.match(uploadId, /^[A-Za-z0-9_-]{16,96}$/);
  assert.equal(requests[1].options.method, "GET");
  assert.equal(requests[1].url, `/stores/fixture-store/media-source-uploads/${uploadId}`);
  assert.equal(f.state.saasMediaSourceUpload.asset_id, "recovered-box");
  assert.equal(f.state.saasMediaSourceUpload.source_url, undefined);
  URL.revokeObjectURL(f.state.mediaSourceObjectUrl);
});

test("first independent upload with no open project survives the real channel transition", async () => {
  const f = fixture();
  f.state.activeMediaDraft = null;
  f.state.saasListingComposerDraft = null;
  const file = new Blob(["new box"], { type: "image/png" }); file.name = "box.png";
  await f.context.handleMediaSourceFile(file);
  assert.equal(f.state.mediaTaskEntry, "single");
  assert.equal(f.requests.length, 1);
  assert.equal(f.state.saasMediaSourceUpload?.asset_id, "fixture-asset");
  assert.equal(f.state.saasMediaSourceUpload.listing_project_key, "");
  URL.revokeObjectURL(f.state.mediaSourceObjectUrl);
});

test("independent results exclude old product jobs and cannot authorize writeback to the open Listing", () => {
  const f = fixture();
  f.state.mediaTaskEntry = "single";
  f.context.saasSafeListingAssetUrl = value => value;
  for (const name of ["saasMediaAssetJobProductFacts", "saasMediaAssetJobMatchesListingProject", "saasMediaAssetJobMatchesIndependentTask", "latestSaasMediaAssetJobWithManifest", "saasMediaAssetJobsForDisplay"]) vm.runInContext(extract(name), f.context);
  const job = (id, facts) => ({ media_job_id: id, live_provider_called: true,
    asset_manifest: [{ url: "https://example.test/image.png" }], job_spec: { inputs: { product_facts: facts } } });
  const old = job("old", { listing_project_key: "fixture-project", listing_project_identity: f.state.saasListingComposerDraft.listing_project_identity, source_asset_id: "old-source" });
  const current = job("current", { source_asset_id: "new-source" });
  f.state.saasMediaAssetJobs = [old, job("unrelated", { source_asset_id: "other-source" }), current];
  f.state.saasMediaSourceUpload = { asset_id: "new-source" };
  assert.equal(f.context.latestSaasMediaAssetJobWithManifest()?.media_job_id, "current");
  assert.equal(f.context.saasMediaAssetJobsForDisplay().map(row => row.media_job_id).join(), "current");
  assert.equal(f.context.latestSaasMediaAssetJobWithManifest({ requireCurrentProject: true }), null);
  assert.equal(f.context.latestSaasMediaAssetJobWithManifest({ draft: f.state.saasListingComposerDraft, requireCurrentProject: true })?.media_job_id, "old", "explicit Listing context remains available without modifying it");
  f.state.saasMediaSourceUpload = null;
  assert.equal(f.context.latestSaasMediaAssetJobWithManifest(), null);
});

test("pending receipt survives memory refresh and does not resend when a second file is selected", async () => {
  const f = fixture();
  const scope = f.context.saasMediaUploadScope();
  const receipt = { upload_id: "fixture_pending_upload_1234", status: "pending", created_at: Date.now() };
  f.context.rememberSaasMediaUploadReceipt(scope, receipt);
  f.state.saasMediaUploadReceipts = {};
  const requests = [];
  f.context.saasFetch = async (url, options) => {
    requests.push({ url, options });
    throw Object.assign(new Error("fixture not yet found"), { status: 404, payload: { code: "upload_not_found" } });
  };
  const file = new Blob(["different"], { type: "image/png" }); file.name = "different.png";
  await f.context.handleMediaSourceFile(file);
  assert.equal(requests.length, 1);
  assert.equal(requests[0].options.method, "GET");
  assert.match(requests[0].url, /fixture_pending_upload_1234$/);
  assert.equal(f.context.saasMediaUploadReceipt().status, "pending");
  assert.match(f.ui["#mediaProductionStatus"], /不要重复提交/);
});

test("upload recovery cannot read a previous account or store receipt or apply a late response", async () => {
  const f = fixture();
  const originalIdentity = { ...f.state.saasIdentity };
  const scope = f.context.saasMediaUploadScope();
  f.context.rememberSaasMediaUploadReceipt(scope, { upload_id: "fixture_scope_upload_1234", status: "pending", created_at: Date.now() });
  f.state.saasIdentity.user_id = "different-user";
  assert.equal(await f.context.recoverSaasMediaSourceUpload(), null);
  assert.equal(f.requests.length, 0);
  f.state.saasIdentity = originalIdentity;
  f.context.activeSaasStore = () => ({ store_id: "different-store" });
  assert.equal(await f.context.recoverSaasMediaSourceUpload(), null);
  assert.equal(f.requests.length, 0);
  f.context.activeSaasStore = () => ({ store_id: "fixture-store" });
  let resolve;
  f.context.saasFetch = () => new Promise(done => { resolve = done; });
  const pending = f.context.recoverSaasMediaSourceUpload();
  f.state.saasIdentity = { user_id: "another-user", company_id: "another-company" };
  resolve({ provider_reference_ready: true, media_source_asset: { asset_id: "late-old-source", source_url: "https://example.test/source" } });
  await pending;
  assert.equal(f.state.saasMediaSourceUpload, undefined);
  assert.equal(f.state.saasMediaUploadRecoveryBusy, false);
});

test("configured video without an approved price is not presented or enabled as ready, while images remain usable", async () => {
  const f = fixture();
  const config = { qualityMode: "fidelity_first", videoDurationSeconds: 6, count: "1 张" };
  Object.assign(f.context, {
    pendingMediaGenerationAcceptance: null,
    readMediaGenerationConfig: () => config,
    currentMediaStudioProductFacts: () => ({ source_asset_id: "box-source" }),
    latestSaasMediaAssetJobWithManifest: () => null,
    saasApprovedMediaWritebackGate: () => ({ allowed: false }),
    saasMediaJobHasCurrentSessionBackendEvidence: () => false,
    requestMediaGenerationAcceptance: () => { throw new Error("must not request approval for unavailable generation"); },
  });
  f.state.saasMediaCapabilities = { image_generation: { configured: true,
    live_image_generation_enabled: true, live_video_generation_enabled: true, live_provider_calls_allowed: true,
    video_pricing_approved: false, video_generation_blocked_by: ["video_media_points_pricing_not_approved"] } };
  for (const name of ["saasMediaGenerationGroundingGate", "syncMediaGenerationActionState", "saasMediaGenerationState", "handleMediaGenerateImagesDraftClick"]) vm.runInContext(extract(name), f.context);
  assert.equal(f.context.saasMediaGenerationState().videoReady, false);
  assert.doesNotMatch(f.context.saasMediaGenerationState().title, /图片和视频已接入/);
  f.context.syncMediaGenerationActionState(config);
  assert.equal(f.elements.get("#mediaGenerateImagesDraft").disabled, true);
  await f.context.handleMediaGenerateImagesDraftClick();
  assert.match(f.ui["#mediaProductionStatus"], /视频生成暂未开放/);
  assert.equal(f.requests.length, 0);
  f.context.syncMediaGenerationActionState({ ...config, videoDurationSeconds: 0 });
  assert.equal(f.elements.get("#mediaGenerateImagesDraft").disabled, false);
});

test("independent merchant product input reaches the actual backend fact gate without old facts", () => {
  const f = fixture();
  f.state.mediaTaskEntry = "single";
  f.state.saasMediaSourceUpload = { asset_id: "box-source", sha256: "bb" };
  const nameInput = f.elements.get("#mediaIndependentProductName");
  assert.ok(nameInput, "independent upload must provide a product-identity input");
  Object.assign(f.context, {
    isSaasPublicMvpMode: () => true, saasMerchantWorkbenchContext: () => ({}),
    activeListingDraft: () => ({ titleCn: "Old stand", material: "steel" }),
    isLegacySampleMediaDraftKey: () => false, latestSaasReportByTypes: () => null,
    saasMediaSourceAssetForListingDraft: () => null, MEDIA_FACT_LOCKS: [],
    mediaGenerationTierKey: () => "standard", mediaQualityModeKey: () => "fidelity_first", mediaVideoDurationSeconds: () => 0,
  });
  for (const name of ["currentMediaStudioProductFacts", "saasMediaGenerationGroundingGate", "hashString", "buildSaasMediaAssetJobPayload"]) vm.runInContext(extract(name), f.context);
  f.context.bindMediaSourceUploadEvents(f.view);
  nameInput.value = "两层抽屉收纳盒"; nameInput.emit("input");
  const payload = f.context.buildSaasMediaAssetJobPayload("生成商品白底图", { entry: "single", count: 1, qualityMode: "fidelity_first", videoDurationSeconds: 0 });
  assert.equal(payload.inputs.product_facts.product, "两层抽屉收纳盒");
  assert.equal(payload.inputs.product_facts.supplier_facts.material, "待补");
  assert.equal(payload.inputs.product_facts.listing_project_key || "", "");
  // The server independently validates/hydrates the private source before this gate;
  // this synthetic fixture supplies that server result, not a new client permission.
  const { execFileSync } = require("node:child_process");
  const result = execFileSync("python", ["-B", "-c", "import json,sys; from jiejing_saas.media_asset_pipeline import missing_media_product_fact_keys; x=json.loads(sys.stdin.buffer.read().decode('utf-8')); x['private_media_source_preflight_validated']=True; print(json.dumps(missing_media_product_fact_keys(x)))"],
    { cwd: root, input: JSON.stringify(payload.inputs), encoding: "utf8" });
  assert.deepEqual(JSON.parse(result), []);
  f.state.saasMediaSourceUpload = { asset_id: "another-source" };
  assert.equal(f.context.currentMediaStudioProductFacts({ entry: "single" }).product, "当前商品", "a replacement image must not silently reuse confirmed product identity");
});

test("expired receipt clears the previous source and rechecks the generate button", async () => {
  const f = fixture();
  f.state.saasMediaSourceUpload = { asset_id: "expired-source", provider_reference_ready: true };
  f.context.rememberSaasMediaUploadReceipt(f.context.saasMediaUploadScope(), { upload_id: "fixture_expired_upload_1234", status: "completed", created_at: 1 });
  let syncs = 0;
  f.context.syncMediaGenerationActionState = () => { syncs += 1; };
  f.context.saasFetch = async () => { throw Object.assign(new Error("expired"), { status: 410, payload: { code: "asset_expired" } }); };
  await f.context.recoverSaasMediaSourceUpload();
  assert.equal(f.state.saasMediaSourceUpload, null);
  assert.equal(f.context.saasMediaUploadReceipt(), null);
  assert.equal(syncs, 1);
});

test("a previous image job finishing after replacement cannot mark the new task completed", async () => {
  const f = fixture();
  f.state.mediaTaskEntry = "single";
  f.state.saasMediaSourceUpload = { asset_id: "source-A" };
  let resolve, rendered = 0, upserted = 0;
  Object.assign(f.context, {
    currentMediaStudioProductFacts: () => ({ source_asset_id: f.state.saasMediaSourceUpload.asset_id }),
    saasFetch: () => new Promise(done => { resolve = done; }),
    markSaasMediaJobsAsCurrentSessionBackendEvidence() {},
    upsertSaasMediaAssetJobForDisplay: () => { upserted += 1; },
    runMediaGenerationFromCeo: () => { rendered += 1; },
    refreshSaasMediaGeneratedAssetSurfaces() {}, saasMediaAssetJobIsConceptOnly: () => false,
    saasMediaGenerationGroundingGate: () => ({ hasGroundedSource: true }), saasMediaAssetJobProductFacts: () => ({}),
  });
  vm.runInContext(extract("pollSaasMediaAssetJobUntilReview"), f.context);
  const pending = f.context.pollSaasMediaAssetJobUntilReview({ mediaJobId: "job-A", config: { entry: "single" } });
  f.state.saasMediaSourceUpload = { asset_id: "source-B" };
  f.state.saasMediaSourceUploadEpoch = 2;
  f.state.mediaGenerationStatus = "new-source-ready";
  resolve({ media_asset_job: { media_job_id: "job-A", status: "waiting_review", live_provider_called: true, asset_manifest: [{}] } });
  await pending;
  assert.equal(rendered, 0);
  assert.equal(upserted, 0);
  assert.equal(f.state.mediaGenerationStatus, "new-source-ready");
  assert.equal(f.state.saasMediaAssetJobPolls["job-A"], undefined);
});

test("upload recovery times out even if session renewal ignores abort, and rejects its late reply", async () => {
  const f = fixture();
  f.context.rememberSaasMediaUploadReceipt(f.context.saasMediaUploadScope(), {
    upload_id: "fixture_timeout_upload_1234", status: "pending", created_at: Date.now(),
  });
  let timeout, resolve, request;
  f.context.setTimeout = callback => { timeout = callback; return 1; };
  f.context.clearTimeout = () => {};
  f.context.saasFetch = (_url, options) => { request = options; return new Promise(done => { resolve = done; }); };
  const pending = f.context.recoverSaasMediaSourceUpload();
  timeout();
  const result = await Promise.race([pending.then(() => "settled"), new Promise(done => setImmediate(() => done("still waiting")))]);
  assert.equal(result, "settled", "an abort-insensitive shared session renewal must not leave the button busy");
  assert.equal(request.signal.aborted, true);
  assert.equal(request.saasRequestIsCurrent(), false);
  assert.equal(f.state.saasMediaUploadRecoveryBusy, false);
  assert.equal(f.context.saasMediaUploadReceipt().status, "pending");
  resolve({ provider_reference_ready: true, media_source_asset: { asset_id: "late-timed-out-source", source_url: "https://example.test/source" } });
  await new Promise(setImmediate);
  assert.equal(f.state.saasMediaSourceUpload, undefined);
  f.context.saasFetch = async (_url, options) => {
    assert.equal(options.method, "GET");
    return { provider_reference_ready: true, media_source_asset: { asset_id: "recovered-on-next-check", source_url: "https://example.test/source" } };
  };
  await f.context.recoverSaasMediaSourceUpload();
  assert.equal(f.state.saasMediaSourceUpload.asset_id, "recovered-on-next-check");
});

test("switching to independent saves its existing safe snapshot once, but rerendering does not write", () => {
  const f = fixture();
  const oldDraft = JSON.stringify(f.state.saasListingComposerDraft);
  const savedModes = [];
  f.context.saveSaasProtectedStateSnapshot = () => savedModes.push(f.state.mediaTaskEntry);
  f.context.setMediaNewTaskMode();
  assert.deepEqual(savedModes, ["single"]);
  f.context.setMediaNewTaskMode();
  assert.deepEqual(savedModes, ["single"]);
  assert.equal(JSON.stringify(f.state.saasListingComposerDraft), oldDraft);
});

test("recovered independent source clears stale waiting and concept-only summaries", () => {
  const f = fixture();
  f.state.mediaTaskEntry = "single";
  Object.assign(f.context, {
    currentMediaStudioProductFacts: () => ({ product: "Fixture storage box", source_asset_id: "confirmed-source" }),
    latestSaasMediaAssetJobWithManifest: () => null,
    saasApprovedMediaWritebackGate: () => ({ allowed: false }),
    saasMediaJobHasCurrentSessionBackendEvidence: () => false,
  });
  for (const name of ["saasMediaGenerationGroundingGate", "syncMediaGenerationActionState"]) vm.runInContext(extract(name), f.context);
  f.ui["#mediaDecisionSummary"] = "没有真实商品来源图";
  f.context.syncMediaGenerationActionState({ entry: "single", qualityMode: "fidelity_first", videoDurationSeconds: 0 });
  assert.doesNotMatch(f.ui["#mediaDecisionSummary"], /没有真实商品来源图/);
  assert.match(f.ui["#mediaSourceTitle"], /Fixture storage box/);
  assert.match(f.ui["#mediaFactTitle"], /已核对/);
  assert.match(f.ui["#mediaProductionTarget"], /独立/);
  f.context.syncMediaGenerationActionState({ entry: "single", qualityMode: "creative_exploration", videoDurationSeconds: 0 });
  assert.doesNotMatch(f.ui["#mediaDecisionSummary"], /没有真实商品来源图/);
  assert.match(f.ui["#mediaDecisionSummary"], /概念/);
});

test("review shows the uploaded original for the same product without exposing another product or account", async () => {
  const f = fixture();
  f.context.setMediaNewTaskMode();
  const file = new Blob(["local source fixture"], { type: "image/png" });
  file.name = "review-original.png";
  await f.context.handleMediaSourceFile(file);
  Object.assign(f.context, {
    saasMediaAssetJobProductFacts: job => job.facts || {},
    saasSafeListingAssetUrl: value => /^https:\/\//.test(String(value)) ? value : "",
  });
  vm.runInContext(extract("saasMediaSourceImageForReview"), f.context);
  const job = { facts: { source_asset_id: "fixture-asset", reference_images: [] } };
  assert.match(f.context.saasMediaSourceImageForReview(job), /^blob:/, "the actual original remains available for comparison after upload");
  assert.equal(f.context.saasMediaSourceImageForReview({ facts: { source_asset_id: "another-source" } }), "");
  f.state.saasIdentity = { user_id: "another-user", company_id: "another-company" };
  assert.equal(f.context.saasMediaSourceImageForReview(job), "", "same asset id cannot cross the account boundary");
  assert.equal(f.state.saasMediaSourceUpload.source_url, undefined);
  assert.doesNotMatch(JSON.stringify(f.context.saasMediaUploadReceipt()), /private-source|blob:/);
});

test("refresh recovery redraws results with the verified original, without persisting its signed URL or claiming no earlier generation", async () => {
  const f = fixture();
  f.context.setMediaNewTaskMode();
  f.context.rememberSaasMediaUploadReceipt(f.context.saasMediaUploadScope(), {
    upload_id: "fixture_refresh_completed_1234", status: "completed", created_at: Date.now(),
  });
  let redraws = 0;
  Object.assign(f.context, {
    refreshSaasMediaGeneratedAssetSurfaces: () => { redraws += 1; },
    saasMediaAssetJobProductFacts: job => job.facts || {},
    saasSafeListingAssetUrl: value => /^https:\/\//.test(String(value)) ? value : "",
  });
  vm.runInContext(extract("saasMediaSourceImageForReview"), f.context);
  await f.context.recoverSaasMediaSourceUpload();
  assert.equal(redraws, 1, "results must appear without leaving and re-entering the page");
  const job = { facts: { source_asset_id: "fixture-asset" } };
  assert.equal(f.context.saasMediaSourceImageForReview(job), "https://example.test/private-source");
  assert.equal(f.state.saasMediaSourceUpload.source_url, undefined);
  assert.doesNotMatch(JSON.stringify(f.state), /private-source/);
  assert.doesNotMatch(JSON.stringify(f.context.saasMediaUploadReceipt()), /private-source/);
  assert.doesNotMatch(f.toasts.at(-1), /生成尚未提交|尚未调用生成/);
  f.state.mediaTaskEntry = "project";
  assert.equal(f.context.saasMediaSourceImageForReview(job), "");
  assert.equal(f.requests.length, 1);
  assert.equal(f.requests[0].options.method, "GET");
});

test("independent product name and selected image settings survive refresh only for their recovered source", async () => {
  const f = fixture();
  f.context.setMediaNewTaskMode();
  const file = new Blob(["local draft fixture"], { type: "image/png" });
  file.name = "draft-original.png";
  await f.context.handleMediaSourceFile(file);
  const scene = f.elements.get("#mediaSceneSelect");
  scene.options = [{ value: "按商品用途自动选择" }, { value: "桌面收纳场景" }];
  scene.value = "桌面收纳场景";
  f.context.bindMediaSourceUploadEvents(f.view);
  const product = f.elements.get("#mediaIndependentProductName");
  product.value = "My two-drawer storage box";
  product.emit("input");
  f.state.saasMediaSourceUpload = null;
  f.state.saasIndependentMediaProduct = null;
  f.state.saasMediaUploadReceipts = {};
  product.value = "";
  scene.value = "按商品用途自动选择";
  await f.context.recoverSaasMediaSourceUpload();
  assert.equal(f.context.saasIndependentMediaProductName(), "My two-drawer storage box");
  assert.equal(product.value, "My two-drawer storage box");
  assert.equal(scene.value, "桌面收纳场景");
  assert.equal(f.state.saasMediaSourceUpload.rights_status, "unknown", "restoring a draft never restores a rights approval");
  assert.equal(f.requests.filter(request => request.options.method === "POST").length, 1);
  assert.equal(f.requests.filter(request => request.options.method === "GET").length, 1);
  assert.doesNotMatch(JSON.stringify(f.context.saasMediaUploadReceipt()), /private-source|blob:|rights_status|videoPreset/);
});

test("changing only an image setting saves the draft without rights or video options", async () => {
  const f = fixture();
  f.context.setMediaNewTaskMode();
  const file = new Blob(["settings fixture"], { type: "image/png" });
  file.name = "settings.png";
  await f.context.handleMediaSourceFile(file);
  f.context.bindMediaSourceUploadEvents(f.view);
  f.elements.get("#mediaIndependentProductName").value = "Storage box";
  f.elements.get("#mediaIndependentProductName").emit("input");
  f.elements.get("#mediaSceneSelect").value = "桌面收纳场景";
  f.elements.get("#mediaVideoPresetSelect").value = "disabled video";
  Object.assign(f.context, { mediaPointsByGenerationTier: { standard: 80 }, renderMediaQualityBoard() {} });
  vm.runInContext(extract("syncMediaRequirementSummary"), f.context);
  f.context.syncMediaRequirementSummary();
  const saved = f.context.saasMediaUploadReceipt().draft;
  assert.equal(saved.product, "Storage box");
  assert.equal(saved.selections.mediaSceneSelect, "桌面收纳场景");
  assert.equal(saved.selections.mediaVideoPresetSelect, undefined);
  assert.equal(f.requests.length, 1, "a settings edit does not generate or upload");
});

test("recovery preserves newer typing and selection changes, rejects disabled settings and a different source", async () => {
  for (const differentSource of [false, true]) {
    const f = fixture();
    f.context.setMediaNewTaskMode();
    const scene = f.elements.get("#mediaSceneSelect");
    scene.options = [{ value: "default" }, { value: "saved" }, { value: "edited" }];
    scene.value = "default";
    const size = f.elements.get("#mediaSizeSelect");
    size.options = [{ value: "current" }, { value: "retired", disabled: true }];
    size.value = "current";
    f.context.rememberSaasMediaUploadReceipt(f.context.saasMediaUploadScope(), {
      upload_id: "fixture_async_recovery_1234", status: "completed",
      draft: { source_asset_id: "fixture-asset", product: "Saved box", selections: { mediaSceneSelect: "saved", mediaSizeSelect: "retired" } },
    });
    f.context.bindMediaSourceUploadEvents(f.view);
    let resolve;
    f.context.saasFetch = () => new Promise(done => { resolve = done; });
    const pending = f.context.recoverSaasMediaSourceUpload();
    if (!differentSource) {
      f.elements.get("#mediaIndependentProductName").value = "Newer product name";
      f.elements.get("#mediaIndependentProductName").emit("input");
      scene.value = "edited";
    }
    resolve({ provider_reference_ready: true, media_source_asset: { asset_id: differentSource ? "changed-source" : "fixture-asset", source_url: "https://example.test/original" } });
    await pending;
    assert.equal(f.context.saasIndependentMediaProductName(), differentSource ? "" : "Newer product name");
    assert.equal(scene.value, differentSource ? "default" : "edited");
    assert.equal(size.value, "current", "disabled legacy choices cannot be restored");
  }
});
