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
