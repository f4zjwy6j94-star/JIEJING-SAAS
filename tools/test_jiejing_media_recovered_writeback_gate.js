#!/usr/bin/env node
"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const root = path.resolve(__dirname, "..");
const appSource = fs.readFileSync(path.join(root, "app.js"), "utf8");

function extractFunction(startMarker, endMarker) {
  const start = appSource.indexOf(startMarker);
  assert.notEqual(start, -1, `missing ${startMarker}`);
  const end = appSource.indexOf(endMarker, start);
  assert.notEqual(end, -1, `missing ${endMarker}`);
  return appSource.slice(start, end);
}

const gateSource = extractFunction(
  "function saasApprovedMediaWritebackGate",
  "\nfunction saasListingMediaWritebackForDraft",
);
const trustSource = extractFunction(
  "const saasMediaJobCurrentSessionBackendEvidence",
  "\nfunction upsertSaasMediaAssetJobForDisplay",
);
const applySource = extractFunction(
  "function applySaasMediaManifestToListingDraft",
  "\nfunction saasMediaWritebackBlockMessage",
);
const revalidationSource = extractFunction(
  "async function revalidateAndApplySaasMediaManifestToListingDraft",
  "\nfunction finishSaasMediaWritebackUi",
);

function approvedJob() {
  const reviewedAt = "2026-08-30T12:00:00.000Z";
  return {
    media_job_id: "media-job-approved-a",
    store_id: "store-a",
    status: "approved_for_listing",
    live_provider_called: true,
    spend_now_allowed: false,
    secret_exposed: false,
    job: {
      job_spec: {
        inputs: {
          product_facts: {
            listing_project_key: "listing-project-a",
            source_asset_id: "media-source-a",
            private_source_transport: "backend_asset_id",
            reference_images: [],
          },
        },
      },
    },
    asset_manifest_validation: { status: "manifest_ready" },
    merchant_review: {
      decision: "approve_for_listing_draft",
      confirmations: {
        fact_consistency_confirmed: true,
        commercial_rights_confirmed: true,
        platform_rules_checked: true,
        motion_and_usage_consistency_confirmed: true,
      },
      reviewed_by: "merchant-a",
      listing_draft_only: true,
      triggers_real_platform_write: false,
      secret_exposed: false,
    },
    asset_review: {
      status: "approved_for_listing_draft",
      listing_use_status: "approved_for_listing_draft",
      reviewed_at: reviewedAt,
    },
    asset_manifest: [
      {
        asset_id: "asset-a",
        asset_type: "product_image",
        url_or_file_path: "https://cdn.example.test/product-a.jpg",
        fact_review_status: "confirmed_by_merchant",
        commercial_use_status: "confirmed_by_merchant",
        listing_use_status: "approved_for_listing_draft",
        review_status: "approved_for_listing_draft",
      },
    ],
    updated_at: reviewedAt,
  };
}

function runGate(job, draft = { listing_project_key: "listing-project-a" }) {
  const sandbox = { __job: job, __draft: draft, URL };
  vm.runInNewContext(
    `
const state = { saasListingComposerDraft: globalThis.__draft };
const activeSaasStore = () => ({ store_id: "store-a" });
const saasMediaAssetJobProductFacts = (job = {}) => job?.job?.job_spec?.inputs?.product_facts || {};
const saasMediaAssetJobMatchesListingProject = (job = {}, draft = {}) => {
  const facts = saasMediaAssetJobProductFacts(job);
  return Boolean(facts.listing_project_key && facts.listing_project_key === draft.listing_project_key);
};
const saasMediaAssetJobIsConceptOnly = (job = {}) => job.concept_only === true;
const saasSafeListingAssetUrl = (value = "") => {
  try {
    const parsed = new URL(String(value || ""));
    return parsed.protocol === "https:" ? parsed.href : "";
  } catch (_error) {
    return "";
  }
};
const saasMediaManifestAssetsForListing = (job = {}) => (job.asset_manifest || [])
  .map((asset) => ({ url: saasSafeListingAssetUrl(asset.url_or_file_path || asset.url || asset.file_path) }))
  .filter((asset) => asset.url);
${gateSource}
globalThis.__result = saasApprovedMediaWritebackGate(globalThis.__job, globalThis.__draft);
`,
    sandbox,
  );
  return sandbox.__result;
}

test("a restored approved job for the same Listing project can write back only to the draft", () => {
  const result = runGate(approvedJob());
  assert.equal(result.allowed, true);
  assert.equal(result.reason, "approved_for_listing_draft");
  assert.equal(result.assets.length, 1);
});

test("recovered media writeback fails closed across the full trust matrix", () => {
  const cases = [
    ["missing job", null, "missing_job"],
    ["revision missing", (() => { const job = approvedJob(); job.updated_at = ""; return job; })(), "job_revision_missing"],
    ["cross store", (() => { const job = approvedJob(); job.store_id = "store-b"; return job; })(), "store_mismatch"],
    ["cross project", (() => { const job = approvedJob(); job.job.job_spec.inputs.product_facts.listing_project_key = "listing-project-b"; return job; })(), "project_mismatch"],
    ["unapproved job", (() => { const job = approvedJob(); job.status = "waiting_review"; return job; })(), "job_not_approved"],
    ["provider result absent", (() => { const job = approvedJob(); job.live_provider_called = false; return job; })(), "provider_result_missing"],
    ["manifest validation absent", (() => { const job = approvedJob(); job.asset_manifest_validation.status = "validation_failed"; return job; })(), "manifest_not_ready"],
    ["concept-only output", (() => { const job = approvedJob(); job.concept_only = true; return job; })(), "concept_only"],
    ["spend boundary unsafe", (() => { const job = approvedJob(); job.spend_now_allowed = true; return job; })(), "unsafe_job_boundary"],
    ["secret boundary unsafe", (() => { const job = approvedJob(); job.secret_exposed = true; return job; })(), "unsafe_job_boundary"],
    ["ungrounded product facts", (() => { const job = approvedJob(); const facts = job.job.job_spec.inputs.product_facts; facts.source_asset_id = ""; facts.private_source_transport = ""; facts.reference_images = []; return job; })(), "product_facts_not_grounded"],
    ["unsafe asset URL", (() => { const job = approvedJob(); job.asset_manifest[0].url_or_file_path = "http://attacker.invalid/product.jpg"; return job; })(), "unsafe_asset_url"],
    ["merchant rights missing", (() => { const job = approvedJob(); job.merchant_review.confirmations.commercial_rights_confirmed = false; return job; })(), "merchant_review_not_audited"],
    ["merchant identity missing", (() => { const job = approvedJob(); job.merchant_review.reviewed_by = ""; return job; })(), "merchant_review_not_audited"],
    ["asset audit timestamp missing", (() => { const job = approvedJob(); job.asset_review.reviewed_at = ""; return job; })(), "asset_review_not_audited"],
    ["manifest rights audit missing", (() => { const job = approvedJob(); job.asset_manifest[0].commercial_use_status = "needs_review"; return job; })(), "manifest_review_not_audited"],
  ];
  for (const [label, job, reason] of cases) {
    const result = runGate(job);
    assert.equal(result.allowed, false, label);
    assert.equal(result.reason, reason, label);
    assert.equal(result.assets.length, 0, label);
  }
});

test("video writeback additionally requires the audited motion and usage confirmation", () => {
  const job = approvedJob();
  job.asset_manifest[0].asset_type = "product_video";
  job.asset_manifest[0].url_or_file_path = "https://cdn.example.test/product-a.mp4";
  job.merchant_review.confirmations.motion_and_usage_consistency_confirmed = false;
  const result = runGate(job);
  assert.equal(result.allowed, false);
  assert.equal(result.reason, "merchant_review_not_audited");
});

test("protected reload snapshot preserves the canonical merchant review audit", () => {
  const snapshotSection = extractFunction("function buildSaasProtectedStateSnapshot", "\nfunction saveSaasProtectedStateSnapshot");
  assert.match(snapshotSection, /"merchant_review"/);
  assert.match(appSource, /const writebackGate = saasApprovedMediaWritebackGate\(job\)/);
  assert.match(appSource, /\? "revalidation_required"/);
});

test("a fully tampered protected snapshot remains untrusted UI cache and cannot unlock writeback", () => {
  const sandbox = { __job: approvedJob() };
  vm.runInNewContext(
    `
${trustSource}
markSaasMediaJobsAsUntrustedUiCache([globalThis.__job]);
globalThis.__untrusted = saasMediaJobHasCurrentSessionBackendEvidence(globalThis.__job);
markSaasMediaJobsAsCurrentSessionBackendEvidence([globalThis.__job]);
globalThis.__trustedAfterBackendRead = saasMediaJobHasCurrentSessionBackendEvidence(globalThis.__job);
`,
    sandbox,
  );
  assert.equal(sandbox.__untrusted, false);
  assert.equal(sandbox.__trustedAfterBackendRead, true);
  const proofGuard = applySource.indexOf("consumeSaasMediaWritebackRevalidationProof(authoritativeJob, revalidationToken)");
  const strictGate = applySource.indexOf("saasApprovedMediaWritebackGate(job)");
  assert.ok(proofGuard >= 0 && proofGuard < strictGate, "ordinary synchronous apply must fail before reading cached job fields");
});

async function runRevalidation(mode) {
  const job = approvedJob();
  job.project_key = "listing-project-a";
  if (mode === "revoked") job.status = "needs_rework";
  if (mode === "cross_store") job.store_id = "store-b";
  const sandbox = { __job: job, __mode: mode, __requests: [], __toasts: [], __applies: 0 };
  await vm.runInNewContext(
    `(async () => {
const state = { saasMediaAssetJobs: [globalThis.__job] };
const activeSaasStore = () => ({ store_id: "store-a" });
const latestSaasMediaAssetJobWithManifest = () => state.saasMediaAssetJobs[0] || null;
const saasMediaAssetJobMatchesListingProject = (job = {}) => job.project_key === "listing-project-a";
const markSaasMediaJobsAsCurrentSessionBackendEvidence = () => {};
const upsertSaasMediaAssetJobForDisplay = (job) => { state.saasMediaAssetJobs = [job]; };
const saasApprovedMediaWritebackGate = (job = {}) => ({
  allowed: job.status === "approved_for_listing" && job.store_id === "store-a" && job.project_key === "listing-project-a",
  reason: job.status === "approved_for_listing" ? "store_mismatch" : "job_not_approved",
});
const issueSaasMediaWritebackRevalidationProof = () => "one-time-proof";
const applySaasMediaManifestToListingDraft = ({ authoritativeJob, revalidationToken }) => {
  globalThis.__applies += 1;
  return authoritativeJob === state.saasMediaAssetJobs[0] && revalidationToken === "one-time-proof" ? { ok: true } : null;
};
const showActionToast = (message) => globalThis.__toasts.push(String(message));
const publicRuntimeText = (value = "") => String(value || "");
const saasMediaWritebackBlockMessage = (reason = "") => reason;
const saasFetch = async (path) => {
  globalThis.__requests.push(path);
  if (globalThis.__mode === "network") throw new Error("offline");
  return { media_asset_job: globalThis.__job };
};
${revalidationSource}
globalThis.__result = await revalidateAndApplySaasMediaManifestToListingDraft({ entry: "project" });
})()`,
    sandbox,
  );
  return sandbox;
}

test("writeback succeeds only after an authoritative current backend GET", async () => {
  const sandbox = await runRevalidation("approved");
  assert.deepEqual(Array.from(sandbox.__requests), ["/media-asset-jobs/media-job-approved-a"]);
  assert.equal(sandbox.__applies, 1);
  assert.equal(sandbox.__result?.ok, true);
});

test("backend revocation, cross-store scope and network failure all block writeback", async () => {
  for (const mode of ["revoked", "cross_store", "network"]) {
    const sandbox = await runRevalidation(mode);
    assert.deepEqual(Array.from(sandbox.__requests), ["/media-asset-jobs/media-job-approved-a"], mode);
    assert.equal(sandbox.__applies, 0, mode);
    assert.equal(sandbox.__result, null, mode);
    assert.ok(sandbox.__toasts.length > 0, mode);
  }
});

// Exercise the real revalidation -> apply -> facts -> wizard -> collection seam.
// A media_writeback snapshot alone used to pass while step 3 still hid the image.
function writebackWizardHarness(job = approvedJob(), previousImages = "") {
  const state = { saasMediaAssetJobs: [job], saasListingComposerDraft: {
    listing_project_key: "listing-project-a", source_product_fact_report_id: "facts-a",
    product: "Wood Handle Measuring Set", simulation_only: true,
    fields: { title: "Merchant title", description: "Merchant description", price: "12.99" },
    publish_prefill: { image_urls: previousImages, price: "12.99" },
    merchant_product_fact_packet: {
      simulation_only: true, source_confirmed_facts: { material: "Gold-tone metal and wood" },
      merchant_confirmed_facts: { product_name: "Wood Handle Measuring Set", condition: "NEW",
        source_url: "https://supplier.example.test/item", selling_price: "12.99",
        ...(previousImages ? { image_urls: previousImages, image_rights_confirmed: true } : {}) },
      unknown_facts: ["image_urls", "image_rights_confirmed", "item_location"],
    },
  } };
  const controls = [];
  const context = vm.createContext({ state, URL, __requests: [], __snapshots: [], __toasts: [],
    SAAS_MERCHANT_PRODUCT_FACT_PACKET_CONTRACT: "merchant_product_fact_packet_v1",
    window: { location: { origin: "https://app.example.test", hostname: "app.example.test" } },
    document: { querySelectorAll: () => controls, querySelector: () => null },
    activeSaasStore: () => ({ store_id: "store-a" }),
    activeMediaDraftProductNameForDisplay: () => state.saasListingComposerDraft.product,
    saasCurrentListingProjectIdentity: () => ({ key: state.saasListingComposerDraft.listing_project_key }),
    saasListingAiGenerationContextKey: () => "company-a:store-a:listing-project-a",
    saasMediaAssetJobMatchesListingProject: (item, draft = state.saasListingComposerDraft) =>
      item?.job?.job_spec?.inputs?.product_facts?.listing_project_key === draft?.listing_project_key,
    saasMediaAssetJobIsConceptOnly: item => item.concept_only === true,
    latestSaasMediaAssetJobWithManifest: () => state.saasMediaAssetJobs[0],
    upsertSaasMediaAssetJobForDisplay: item => { state.saasMediaAssetJobs = [item]; },
    publicRuntimeText: value => String(value || ""),
    sanitizeSaasWorkflowFeedbackText: (value, limit = 280) => String(value || "").slice(0, limit),
    escapeHtml: value => String(value || ""),
    saasMerchantProductFactLabel: key => key,
    showActionToast: message => context.__toasts.push(message),
    saveSaasProtectedStateSnapshot: () => context.__snapshots.push(context.sanitizeSaasListingComposerDraftSnapshot(state.saasListingComposerDraft)),
    saasFetch: async route => { context.__requests.push(route); return { media_asset_job: job }; },
  });
  vm.runInContext(trustSource + gateSource + applySource + revalidationSource, context);
  for (const name of ["hashString", "saasMediaAssetJobProductFacts", "saasSafeListingAssetUrl",
    "saasMediaManifestAssetCards", "saasMediaManifestAssetsForListing", "saasMerchantAssetSpecification", "saasMediaWritebackBlockMessage",
    "parseSaasKeyValueLines", "saasMerchantProductFactDefinitions", "saasMerchantProductFactRequiredKeys",
    "saasMerchantProductFactValuePresent", "saasMerchantProductFactPacket", "saasMerchantProductFactOrigin",
    "saasMerchantProductFactProjectedValue", "saasListingWizardImageUrls", "renderSaasMerchantProductFactField",
    "saasListingMediaWritebackForDraft", "saasListingMediaWritebackImageUrls", "saasListingMediaWritebackRightsReady",
    "renderSaasListingMediaWritebackPanel", "renderSaasListingWizardImages", "sanitizeSaasCeoCommandSourceText", "collectSaasMerchantProductFacts",
    "sanitizeSaasMerchantProductFactValues", "sanitizeSaasMerchantProductFactPacketSnapshot",
    "pickSaasSnapshotFields", "sanitizeSaasListingPublishPrefillSnapshot", "sanitizeSaasListingMediaWritebackSnapshot",
    "saasListingMerchantEditableFieldKeys", "saasListingMerchantEditedFields", "sanitizeSaasListingComposerDraftSnapshot",
    "saasListingItemSpecificsWithMerchantFacts", "applySaasMerchantProductFactPacketToDraft",
    "saasCanonicalJsonValue", "invalidateSaasListingValidationForFactChange", "clearSaasPendingProductFactEditor"]) {
    const start = appSource.search(new RegExp(`^(?:async )?function ${name}\\(`, "m"));
    assert(start >= 0, name);
    const tail = appSource.slice(start);
    const next = tail.slice(1).search(/^function |^async function |^const |^let /m);
    vm.runInContext(next < 0 ? tail : tail.slice(0, next + 1), context);
  }
  return { context, state, controls };
}

test("fresh approved media replaces the missing-image fact and survives wizard save/restore", async () => {
  const { context, state, controls } = writebackWizardHarness();
  assert.deepEqual(Array.from(context.saasListingWizardImageUrls()), []);
  const result = await context.revalidateAndApplySaasMediaManifestToListingDraft({ entry: "single" });
  const imageUrl = approvedJob().asset_manifest[0].url_or_file_path;
  assert(result, `backend-approved writeback succeeds: ${context.__toasts.join("; ")}`);
  assert.deepEqual(Array.from(context.__requests), ["/media-asset-jobs/media-job-approved-a"]);
  assert.deepEqual(Array.from(context.saasListingWizardImageUrls()), [imageUrl], "step 3 must see the image, not only the success toast");
  let packet = context.saasMerchantProductFactPacket();
  assert.equal(packet.merchant_confirmed_facts.image_urls, imageUrl);
  assert(!packet.unknown_facts.includes("image_urls"));
  assert(packet.unknown_facts.includes("image_rights_confirmed"), "writeback never checks the final rights checkbox");
  assert(packet.unknown_facts.includes("item_location"));
  assert.equal(packet.simulation_only, true);
  assert.equal(packet.source_confirmed_facts.material, "Gold-tone metal and wood");
  assert.equal(state.saasListingComposerDraft.fields.title, "Merchant title");
  assert.equal(state.saasListingComposerDraft.source_product_fact_report_id, "facts-a");
  assert.equal(context.__snapshots[0].pending_product_fact_import, "company-a:store-a:listing-project-a");
  const html = context.renderSaasListingWizardImages(state.saasListingComposerDraft);
  assert.match(html, /已关联 1 张图片/);
  assert(html.includes(imageUrl));
  const input = html.match(/<textarea data-saas-product-fact-field="image_urls"([^>]*)>([^<]*)<\/textarea>/);
  assert(input, "real fact control is rendered");
  assert.match(input[1], /data-product-fact-confirmed="true"/);
  controls.push({ type: "textarea", value: input[2], dataset: { saasProductFactField: "image_urls",
    productFactConfirmed: "true", productFactOriginState: "merchant_confirmed" } });
  const collected = context.collectSaasMerchantProductFacts();
  assert.equal(collected.merchantConfirmed.image_urls, imageUrl);
  packet = context.sanitizeSaasMerchantProductFactPacketSnapshot({ ...packet,
    merchant_confirmed_facts: collected.merchantConfirmed, unknown_facts: collected.unknownFacts });
  state.saasListingComposerDraft = context.applySaasMerchantProductFactPacketToDraft(context.__snapshots[0], packet);
  assert.deepEqual(Array.from(context.saasListingWizardImageUrls()), [imageUrl]);
  assert.equal(state.saasListingComposerDraft.publish_prefill.image_rights_confirmed, false);
  assert.equal(state.saasListingComposerDraft.simulation_only, true);
  // Removing a previously confirmed picture must still revoke stale prefill.
  controls[0].value = "";
  controls[0].dataset.productFactUnknown = "true";
  const revoked = context.collectSaasMerchantProductFacts();
  state.saasListingComposerDraft.merchant_product_fact_packet = { ...packet,
    merchant_confirmed_facts: revoked.merchantConfirmed, unknown_facts: revoked.unknownFacts };
  assert.deepEqual(Array.from(context.saasListingWizardImageUrls()), []);
});

test("new image selection resets old image rights without promoting videos or rejected jobs", async () => {
  const replacement = writebackWizardHarness(approvedJob(), "https://cdn.example.test/previous.jpg");
  await replacement.context.revalidateAndApplySaasMediaManifestToListingDraft();
  const replacementPacket = replacement.context.saasMerchantProductFactPacket();
  assert.notEqual(replacementPacket.values.image_rights_confirmed, true);
  for (const mode of ["video", "revoked", "cross_project", "unreviewed"]) {
    const job = approvedJob();
    if (mode === "video") {
      job.asset_manifest[0].asset_type = "product_video";
      job.asset_manifest[0].url_or_file_path = "https://cdn.example.test/product.mp4";
    }
    if (mode === "revoked") job.status = "needs_rework";
    if (mode === "cross_project") job.job.job_spec.inputs.product_facts.listing_project_key = "other-project";
    if (mode === "unreviewed") job.merchant_review.confirmations.commercial_rights_confirmed = false;
    const { context, state } = writebackWizardHarness(job);
    const before = JSON.stringify(state.saasListingComposerDraft.merchant_product_fact_packet);
    await context.revalidateAndApplySaasMediaManifestToListingDraft();
    assert.deepEqual(Array.from(context.saasListingWizardImageUrls()), [], mode);
    assert.equal(JSON.stringify(state.saasListingComposerDraft.merchant_product_fact_packet), before, mode);
  }
});

test("a duplicate approved selection keeps its existing confirmation, while changed facts revoke copy validation", async () => {
  const job = approvedJob();
  const { context, state } = writebackWizardHarness(job, job.asset_manifest[0].url_or_file_path);
  state.saasListingComposerDraft.model_generated = true;
  await context.revalidateAndApplySaasMediaManifestToListingDraft();
  assert.equal(context.saasMerchantProductFactPacket().values.image_rights_confirmed, true);
  assert.equal(state.saasListingComposerDraft.model_generated, true, "unchanged image selection is idempotent");
  const changed = writebackWizardHarness();
  changed.state.saasListingComposerDraft.model_generated = true;
  await changed.context.revalidateAndApplySaasMediaManifestToListingDraft();
  assert.equal(changed.state.saasListingComposerDraft.model_generated, false);
  assert.equal(changed.state.saasListingComposerDraft.buyer_copy_requires_validated_listing_generation, true);
  assert.equal(changed.state.saasListingComposerDraft.fields.title, "Merchant title");
});
