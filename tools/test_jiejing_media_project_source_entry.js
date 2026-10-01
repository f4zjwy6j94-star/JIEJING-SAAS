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
      dataset: {}, clicks: 0, listeners: new Map(), classList: { add() {}, remove() {} },
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
    saasListingComposerDraft: { product: "Fixture measuring cups", listing_project_identity: identity,
      fields: { title: "Saved listing title" } } };
  const requests = [], toasts = [], ui = {};
  const context = { state, URL, location: { hostname: "127.0.0.1" },
    document: { querySelector: selector => elements.get(selector) || null },
    saasCurrentListingProjectIdentity: draft => draft?.listing_project_identity || {},
    showActionToast: text => toasts.push(text),
    setMediaNewTaskMode: () => { state.mediaTaskEntry = "single"; },
    inferMediaLocalPath: file => ({ path: file.name, note: "Local fixture" }),
    setText: (selector, value) => { ui[selector] = value; },
    syncMediaGenerationActionState() {}, publicRuntimeText: value => String(value),
    activeSaasStore: () => ({ store_id: "fixture-store" }),
    saasFetch: async (url, options) => {
      requests.push({ url, options });
      return { provider_reference_ready: true, media_source_asset: { asset_id: "fixture-asset", sha256: "aa",
        source_url: "https://example.test/private-source", rights_status: "unknown" } };
    },
  };
  vm.createContext(context);
  for (const name of ["uploadSaasMediaSourceFile", "handleMediaSourceFile", "bindMediaSourceUploadEvents"]) {
    vm.runInContext(extract(name), context);
  }
  return { context, state, elements, view, requests, toasts, ui };
}

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
