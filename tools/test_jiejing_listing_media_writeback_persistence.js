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

const snapshotSource = extractFunction(
  "function sanitizeSaasListingMediaWritebackSnapshot",
  "\nfunction buildSaasProtectedStateSnapshot",
);
const mediaWritebackSource = extractFunction(
  "function applySaasMediaManifestToListingDraft",
  "\nfunction renderSaasListingMediaWritebackPanel",
);

function snapshotDraft(draft) {
  const sandbox = { __draft: draft };
  vm.runInNewContext(
    `
const publicRuntimeText = (value = "") => String(value || "");
const sanitizeSaasWorkflowFeedbackText = (value = "", limit = 280) => String(value || "").slice(0, limit);
const pickSaasSnapshotFields = (source = {}, fields = []) => Object.fromEntries(
  fields.filter((field) => source[field] !== undefined).map((field) => [field, source[field]])
);
const saasCurrentListingProjectIdentity = () => ({ key: "incense-project" });
const sanitizeSaasListingPublishPrefillSnapshot = (value) => ({ ...(value || {}) });
const sanitizeSaasMerchantProductFactPacketSnapshot = () => null;
${snapshotSource}
globalThis.__result = sanitizeSaasListingComposerDraftSnapshot(globalThis.__draft);
`,
    sandbox,
  );
  return sandbox.__result;
}

test("approved Listing media survives the protected snapshot used after reload", () => {
  const imageUrl = "https://cdn.example.test/generated-incense-main.jpg";
  const restored = snapshotDraft({
    product: "禅意佛手托莲花倒流香炉",
    title: "禅意佛手托莲花倒流香炉",
    fields: { title: "Backflow Incense Burner", images: "已接入素材清单：1 个素材" },
    publish_prefill: { image_urls: imageUrl, image_rights_confirmed: true },
    media_writeback: {
      contract_version: "2026-07-05-media-to-listing-writeback-v1",
      status: "merchant_reviewed_for_listing_draft",
      source: "media_asset_manifest",
      media_job_id: "media_job_real_incense",
      asset_count: 1,
      image_count: 1,
      asset_urls: [imageUrl],
      image_urls: [imageUrl],
      assets: [
        {
          asset_id: "asset_1",
          asset_type: "product_image",
          url: imageUrl,
          is_video: false,
          review_status: "merchant_review_confirmed",
          commercial_use_status: "merchant_rights_confirmed",
          listing_use_status: "approved_for_listing_draft",
          media_job_id: "media_job_real_incense",
        },
      ],
      asset_manifest_validation_status: "manifest_ready",
      review_status: "approved_for_listing",
      rights_status: "merchant_rights_confirmed",
      listing_use_status: "approved_for_listing_draft",
      review_required_before_publish: false,
      fact_review_required_before_publish: true,
      confirmation_center_required: true,
      triggers_real_platform_write: false,
      spend_now_allowed: false,
      secret_exposed: false,
    },
  });

  assert.deepEqual(Array.from(restored.media_writeback.image_urls || []), [imageUrl]);
  assert.equal(restored.media_writeback.rights_status, "merchant_rights_confirmed");
  assert.equal(restored.media_writeback.listing_use_status, "approved_for_listing_draft");
  assert.equal(restored.media_writeback.assets?.[0]?.review_status, "merchant_review_confirmed");
  assert.equal(restored.media_writeback.assets?.[0]?.commercial_use_status, "merchant_rights_confirmed");
  assert.equal(restored.media_writeback.assets?.[0]?.listing_use_status, "approved_for_listing_draft");
  assert.equal(restored.media_writeback.triggers_real_platform_write, false);
  assert.equal(restored.media_writeback.secret_exposed, false);
});

test("media writeback saves the protected snapshot before returning", () => {
  const draftAssignment = mediaWritebackSource.indexOf("state.saasListingComposerDraft = {");
  const snapshotSave = mediaWritebackSource.indexOf("saveSaasProtectedStateSnapshot();");
  const returnWriteback = mediaWritebackSource.lastIndexOf("return writeback;");

  assert.notEqual(draftAssignment, -1);
  assert.notEqual(snapshotSave, -1, "writeback must be persisted immediately instead of waiting for unrelated UI edits");
  assert.notEqual(returnWriteback, -1);
  assert.ok(draftAssignment < snapshotSave);
  assert.ok(snapshotSave < returnWriteback);
});
