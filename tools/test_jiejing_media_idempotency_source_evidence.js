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

const hashStringSource = extractFunction("function hashString", "\nfunction extractSaasSourceRecordsFromReport");
const payloadBuilderSource = extractFunction(
  "function buildSaasMediaAssetJobPayload",
  "\nasync function pollSaasMediaAssetJobUntilReview",
);

const sandbox = {
  __facts: {},
  state: { saasModelSettings: {} },
};
vm.runInNewContext(
  `
const MEDIA_FACT_LOCKS = [];
const activeSaasStore = () => ({ store_id: "store-test" });
const currentMediaStudioProductFacts = () => JSON.parse(JSON.stringify(globalThis.__facts));
const mediaGenerationTierKey = () => "standard";
const mediaQualityModeKey = () => "fidelity_first";
const mediaVideoDurationSeconds = () => 0;
const saasMediaGenerationGroundingGate = () => ({ conceptOnly: false });
${hashStringSource}
${payloadBuilderSource}
globalThis.__buildPayload = buildSaasMediaAssetJobPayload;
`,
  sandbox,
);

const baseFacts = {
  product: "merchant product",
  listing_project_key: "listing-project-1",
  reference_images: ["https://cdn.example.test/source-b.jpg", "https://cdn.example.test/source-a.jpg"],
  source_asset_id: "asset-source-a",
  source_image_sha256: "a".repeat(64),
};
const baseConfig = {
  count: 2,
  commercialRightsConfirmed: true,
  generationTierKey: "standard",
  qualityMode: "fidelity_first",
  videoDurationSeconds: 0,
};

function idempotencyKey(facts, config = baseConfig) {
  sandbox.__facts = facts;
  return sandbox.__buildPayload("Create listing images", config).idempotency_key;
}

test("replacing only the source asset changes the media job idempotency key", () => {
  const original = idempotencyKey(baseFacts);
  const replaced = idempotencyKey({ ...baseFacts, source_asset_id: "asset-source-b" });
  assert.notEqual(replaced, original);
});

test("replacing only the source image digest changes the media job idempotency key", () => {
  const original = idempotencyKey(baseFacts);
  const replaced = idempotencyKey({ ...baseFacts, source_image_sha256: "b".repeat(64) });
  assert.notEqual(replaced, original);
});

test("replacing only the reference images changes the media job idempotency key", () => {
  const original = idempotencyKey(baseFacts);
  const replaced = idempotencyKey({
    ...baseFacts,
    reference_images: ["https://cdn.example.test/source-c.jpg", "https://cdn.example.test/source-a.jpg"],
  });
  assert.notEqual(replaced, original);
});

test("reference image order does not change the media job idempotency key", () => {
  const original = idempotencyKey(baseFacts);
  const reordered = idempotencyKey({ ...baseFacts, reference_images: [...baseFacts.reference_images].reverse() });
  assert.equal(reordered, original);
});

test("identical source evidence produces a stable media job idempotency key", () => {
  const first = idempotencyKey({ ...baseFacts, reference_images: [...baseFacts.reference_images] });
  const second = idempotencyKey({ ...baseFacts, reference_images: [...baseFacts.reference_images] });
  assert.equal(second, first);
});
