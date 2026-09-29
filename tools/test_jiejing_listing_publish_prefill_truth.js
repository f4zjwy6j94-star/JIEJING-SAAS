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

const publishPrefillSource = extractFunction(
  "function saasPublishIntakePrefillValues",
  "\nfunction renderSaasPublishInputField",
);
const buyerCopyRewriteLookupSource = extractFunction(
  "function saasListingBuyerCopyRewriteForDraft",
  "\nfunction renderSaasListingBuyerCopyRewriteHistory",
);
const duplicateGuardSource = extractFunction(
  "function saasPreTestPayloadText",
  "\nfunction saasPreTestFormSummary",
);
const factPacketProjectionSource = extractFunction(
  "function saasMerchantProductFactProjectedValue",
  "\nfunction applySaasAiCeoProductFactPacket",
);
const aiCeoProductFactApplySource = extractFunction(
  "function applySaasAiCeoProductFactPacket",
  "\nfunction sanitizeSaasMerchantProductFactValues",
);
const publishConfirmationSource = extractFunction(
  "async function createSaasPublishConfirmationFromIntakeForm",
  "\nfunction continueSaasMvpAfterAuth",
);
const factPacketSnapshotSource = extractFunction(
  "function sanitizeSaasMerchantProductFactPacketSnapshot",
  "\nfunction sanitizeSaasListingPublishPrefillSnapshot",
);
const listingDraftSnapshotSource = extractFunction(
  "function sanitizeSaasListingComposerDraftSnapshot",
  "\nfunction sanitizeSaasDetachedListingProjectDraftsSnapshot",
);

function publishPrefill({ input = "", logistics = "", draft = null }) {
  const sandbox = {
    __input: input,
    __logistics: logistics,
    __draft: draft,
  };
  vm.runInNewContext(
    `
const state = {
  saasListingComposerInput: globalThis.__input,
  saasListingSourceMode: "ai_ceo_market_report",
  saasReports: [],
  saasListingComposerDraft: globalThis.__draft || {
    product: "禅意佛手托莲花倒流香炉",
    title: "禅意佛手托莲花倒流香炉",
    source_type: "ai_ceo_market_report",
    publish_prefill: {},
    fields: {
      title: "Backflow Incense Burner with Lotus Flower and Hand Design",
      logistics: globalThis.__logistics,
      images: "https://cdn.example.test/incense-generated.jpg",
      item_specifics: "Brand: Unbranded\\nMPN: Does Not Apply",
      description: "Decorative incense burner.",
    },
  },
};
const saasPendingPublishIntakeFormValues = null;
const sanitizeSaasWorkflowFeedbackText = (value) => String(value || "");
const saasListingComposerDraftFromText = () => null;
const saasAccountScopedEbayPublishPrefillFromPacket = () => ({
  merchant_location_key: "shenzhen-warehouse",
  fulfillment_policy_id: "fulfillment-policy",
  payment_policy_id: "payment-policy",
  return_policy_id: "return-policy",
});
const parseSaasKeyValueLines = (value) => String(value || "").split(/\\r?\\n/).reduce((out, line) => {
  const match = line.match(/^([^:：]+)[:：]\\s*(.+)$/);
  if (match) out[match[1].trim()] = match[2].trim();
  return out;
}, {});
const saasListingMediaWritebackImageUrls = () => [];
${factPacketProjectionSource}
${buyerCopyRewriteLookupSource}
${publishPrefillSource}
globalThis.__result = saasPublishIntakePrefillValues();
`,
    sandbox,
  );
  return sandbox.__result;
}

function duplicateSignal(payload) {
  const sandbox = { __payload: payload };
  vm.runInNewContext(
    `${duplicateGuardSource}\nglobalThis.__result = saasPreTestDuplicateSignal(globalThis.__payload);`,
    sandbox,
  );
  return sandbox.__result;
}

function applyFactPacket(draft, packet) {
  const sandbox = { __draft: draft, __packet: packet };
  vm.runInNewContext(
    `
const saasListingItemSpecificsWithMerchantFacts = (current) => String(current || "");
const saasMerchantProductFactLabel = (key) => String(key || "");
${factPacketProjectionSource}
globalThis.__result = applySaasMerchantProductFactPacketToDraft(globalThis.__draft, globalThis.__packet);
`,
    sandbox,
  );
  return sandbox.__result;
}

function sanitizeFactPacketSnapshot(packet) {
  const sandbox = { __packet: packet };
  vm.runInNewContext(
    `
const SAAS_MERCHANT_PRODUCT_FACT_PACKET_CONTRACT = "merchant_product_fact_packet_v1";
const publicRuntimeText = (value) => String(value || "");
const sanitizeSaasWorkflowFeedbackText = (value, limit = 240) => String(value || "").slice(0, limit);
const sanitizeSaasMerchantProductFactValues = (value) => value && typeof value === "object" ? { ...value } : {};
${factPacketSnapshotSource}
globalThis.__result = sanitizeSaasMerchantProductFactPacketSnapshot(globalThis.__packet);
`,
    sandbox,
  );
  return sandbox.__result;
}

function sanitizeListingDraftSnapshot(draft) {
  const sandbox = { __draft: draft };
  vm.runInNewContext(
    `
const publicRuntimeText = (value) => String(value || "");
const pickSaasSnapshotFields = (source = {}, fields = []) => Object.fromEntries(
  fields.filter((field) => source[field] !== undefined && source[field] !== null).map((field) => [field, source[field]]),
);
const saasCurrentListingProjectIdentity = () => ({ key: "listing-project-vision", source_report_id: "report-vision" });
const saasListingMerchantEditedFields = () => [];
const sanitizeSaasListingPublishPrefillSnapshot = (value) => value && typeof value === "object" ? { ...value } : {};
const sanitizeSaasMerchantProductFactPacketSnapshot = (value) => value && typeof value === "object" ? { ...value } : null;
const sanitizeSaasListingMediaWritebackSnapshot = () => null;
${listingDraftSnapshotSource}
globalThis.__result = sanitizeSaasListingComposerDraftSnapshot(globalThis.__draft);
`,
    sandbox,
  );
  return sandbox.__result;
}

function applyAiCeoProductVisionPacket(packet) {
  const sandbox = { __packet: packet };
  vm.runInNewContext(
    `
const state = {
  saasListingComposerDraft: null,
  saasListingComposerInput: "",
  saasListingSourceMode: "",
  saasReports: [],
};
const saasListingComposerDraftFromText = () => ({
  product: "Local Seed",
  title: "Local Seed",
  fields: {
    title: "Local Seed",
    selling_points: "Local unvalidated point",
    description: "Local unvalidated description",
    item_specifics: "",
  },
  publish_prefill: {},
});
const saasListingItemSpecificsWithMerchantFacts = (current) => String(current || "");
const saasMerchantProductFactLabel = (key) => String(key || "");
const saasNormalizeListingProjectIdentity = () => null;
const saasCurrentListingProjectIdentity = () => ({ key: "listing-project-vision" });
const saveSaasProtectedStateSnapshot = () => true;
${factPacketProjectionSource}
${aiCeoProductFactApplySource}
globalThis.__result = applySaasAiCeoProductFactPacket(globalThis.__packet, "merchant image", null);
`,
    sandbox,
  );
  return sandbox.__result;
}

async function createConfirmationFromUnvalidatedVisionDraft() {
  const sandbox = {};
  vm.runInNewContext(
    `
const state = {
  saasListingComposerDraft: {
    source_type: "ai_ceo_product_vision",
    buyer_copy_requires_validated_listing_generation: true,
    model_generated: false,
  },
  saasLoading: false,
  saasError: "",
  saasConfirmations: [],
  saasPreflightResults: [],
};
const requireSaasProtectedSessionForAction = () => true;
const activeSaasStore = () => ({ store_id: "store-vision" });
const readSaasPublishIntakeForm = () => ({
  listing_project_identity: { key: "listing-project-vision" },
  listing: { title: "Universal iPad Stand", category_id: "176970", price: { value: "19.99" } },
});
const renderSaasBackendPanel = () => {};
const publicRuntimeText = (value) => String(value || "");
const showActionToast = (message) => { globalThis.__toasts.push(String(message || "")); };
const saasFetch = async () => {
  globalThis.__fetchCount += 1;
  return { confirmation: {}, preflight: {}, publish_readiness: {} };
};
const refreshSaasState = async () => {};
const setView = () => {};
const renderSaasConfirmPanel = () => {};
const window = { setTimeout: () => {} };
const document = { querySelector: () => null };
globalThis.__fetchCount = 0;
globalThis.__toasts = [];
${publishConfirmationSource}
globalThis.__promise = createSaasPublishConfirmationFromIntakeForm("ebay-draft");
`,
    sandbox,
  );
  const result = await sandbox.__promise;
  return { result, fetchCount: sandbox.__fetchCount, toasts: sandbox.__toasts };
}

test("net weight, product dimensions, and origin notes never prefill package logistics", () => {
  const result = publishPrefill({
    input:
      "商品约16.2×7.7×17.9cm；净重451g，不是包装重量；" +
      "产地福建德化，不是eBay实际发货地；包装重量和实际Item location继续阻断。",
    logistics:
      "商品净重: 451 g（不等于包装重量）\n" +
      "商品尺寸: 16.2 x 7.7 x 17.9 cm\n" +
      "商品产地: 福建德化（不等于发货地）",
  });

  assert.equal(result.package_weight_g, "");
  assert.equal(result.package_length_cm, "");
  assert.equal(result.package_width_cm, "");
  assert.equal(result.package_height_cm, "");
  assert.equal(result.item_location, "");
});

test("product vision copy cannot prefill the publish form before validated AI Listing generation", () => {
  const result = publishPrefill({
    draft: {
      product: "Foldable Tablet Stand",
      title: "视觉识别出的本地标题",
      source_type: "ai_ceo_product_vision",
      buyer_copy_requires_validated_listing_generation: true,
      model_generated: false,
      publish_prefill: {},
      fields: {
        title: "Universal iPad Pro Stand",
        selling_points: "Fits 4-13 inch tablets\nWorks with iPad Pro\nUniversal compatibility",
        description: "Compatible with iPad Pro and Galaxy tablets.",
        logistics: "",
        images: "",
        item_specifics: "Brand: Unbranded\nType: Tablet Stand",
      },
    },
  });

  assert.equal(result.product, "Foldable Tablet Stand");
  assert.equal(result.title, "");
  assert.equal(result.description_html, "");
});

test("a legitimate new backflow incense product is not rejected by generic category words", () => {
  const result = duplicateSignal({
    product: "禅意佛手托莲花倒流香炉",
    listing: {
      sku: "JJ-INCENSE-JC2023041300002-01",
      title: "Backflow Incense Burner with Lotus Flower and Hand Design",
      description_html: "Decorative incense burner for use with compatible backflow cones.",
      category_leaf: "Incense Holders",
      item_specifics: { Brand: "Unbranded", MPN: "Does Not Apply" },
    },
    asset_manifest: {
      assets: [{ url: "https://cdn.example.test/generated-incense-main.jpg" }],
    },
  });

  assert.equal(result, "");
});

test("explicit package logistics still prefill the eBay publish form", () => {
  const result = publishPrefill({
    input: "实际商品资料已经单独确认。",
    logistics:
      "发货地: Shenzhen, China\n" +
      "包装重量: 620 g\n" +
      "包装尺寸: 20 x 12 x 22 cm",
  });

  assert.equal(result.item_location, "Shenzhen, China");
  assert.equal(result.package_weight_g, "620");
  assert.equal(result.package_length_cm, "20");
  assert.equal(result.package_width_cm, "12");
  assert.equal(result.package_height_cm, "22");
});

test("exact historical SKU or asset identity remains blocked", () => {
  assert.equal(
    duplicateSignal({ listing: { sku: "JJ-BACKFLOW-20260523-003" } }),
    "jj-backflow-20260523-003",
  );
  assert.equal(
    duplicateSignal({
      listing: { sku: "JJ-FRESH-OTHER" },
      asset_manifest: { assets: [{ url: "assets/backflow-incense-generated-main.webp" }] },
    }),
    "assets/backflow-incense-",
  );
});

test("confirmed net weight and product dimensions clear stale package logistics", () => {
  const result = applyFactPacket(
    {
      product: "禅意佛手托莲花倒流香炉",
      publish_prefill: {
        item_location: "福建德化",
        package_weight_g: "451",
        package_length_cm: "16.2",
        package_width_cm: "7.7",
        package_height_cm: "17.9",
      },
      fields: { item_specifics: "Brand: Unbranded", logistics: "商品净重: 451 g" },
    },
    {
      product_name: "禅意佛手托莲花倒流香炉",
      merchant_confirmed_facts: {
        net_weight_g: "451",
        product_dimensions_cm: "16.2 x 7.7 x 17.9",
        product_origin: "福建德化",
      },
      unknown_facts: [
        "item_location",
        "package_weight_g",
        "package_length_cm",
        "package_width_cm",
        "package_height_cm",
      ],
    },
  );

  assert.equal(result.publish_prefill.item_location, "");
  assert.equal(result.publish_prefill.package_weight_g, "");
  assert.equal(result.publish_prefill.package_length_cm, "");
  assert.equal(result.publish_prefill.package_width_cm, "");
  assert.equal(result.publish_prefill.package_height_cm, "");
  assert.equal(result.publish_prefill.product_dimensions_cm, "16.2 x 7.7 x 17.9");
  assert.match(result.fields.logistics, /商品净重: 451 g（不等于包装重量）/);
  assert.match(result.fields.logistics, /商品产地: 福建德化（不等于发货地）/);
});

test("product vision packet preserves facts but never projects its unvalidated listing copy", () => {
  const result = applyFactPacket(
    {
      product: "",
      title: "",
      publish_prefill: {},
      fields: { title: "", selling_points: "", description: "", item_specifics: "" },
    },
    {
      source: "backend_product_vision_extraction",
      vision_contract_version: "product_vision_fact_packet_v1",
      product_name: "Foldable Tablet Stand",
      source_confirmed_facts: { material: "Aluminum Alloy" },
      merchant_confirmed_facts: {},
      listing_copy: {
        title: "Universal iPad Pro Stand",
        selling_points: ["Fits 4-13 inch tablets", "Works with iPad Pro", "Universal compatibility"],
        description: "Compatible with iPad Pro and Galaxy tablets.",
      },
      unknown_facts: ["package_weight_g"],
    },
  );

  assert.equal(result.product, "Foldable Tablet Stand");
  assert.equal(result.publish_prefill.material, "Aluminum Alloy");
  assert.equal(result.fields.title, "");
  assert.equal(result.fields.selling_points, "");
  assert.equal(result.fields.description, "");
  assert.equal(result.buyer_copy_requires_validated_listing_generation, true);
});

test("persisted product vision packets keep their boundary marker and drop legacy buyer copy", () => {
  const result = sanitizeFactPacketSnapshot({
    source: "backend_product_vision_extraction",
    vision_contract_version: "product_vision_fact_packet_v1",
    product_name: "Foldable Tablet Stand",
    source_confirmed_facts: { material: "Aluminum Alloy" },
    merchant_confirmed_facts: {},
    listing_copy: {
      title: "Universal iPad Pro Stand",
      selling_points: ["Fits iPad Pro", "Supports 13-inch tablets", "Universal compatibility"],
      description: "Compatible with iPad Pro and Galaxy tablets.",
    },
    buyer_copy_requires_validated_listing_generation: true,
  });

  assert.equal(result.source, "backend_product_vision_extraction");
  assert.equal(result.vision_contract_version, "product_vision_fact_packet_v1");
  assert.equal(result.buyer_copy_requires_validated_listing_generation, true);
  assert.equal(Object.keys(result.listing_copy).length, 0);
  assert.equal(result.source_confirmed_facts.material, "Aluminum Alloy");
});

test("protected Listing snapshots preserve validated-generation provenance", () => {
  const pending = sanitizeListingDraftSnapshot({
    source_type: "ai_ceo_product_vision",
    product: "Foldable Tablet Stand",
    model_generated: false,
    buyer_copy_requires_validated_listing_generation: true,
    buyer_copy_status: "waiting_for_validated_listing_generation",
    fields: { title: "", selling_points: "", description: "" },
    merchant_product_fact_packet: { source: "backend_product_vision_extraction" },
  });
  assert.equal(pending.model_generated, false);
  assert.equal(pending.buyer_copy_requires_validated_listing_generation, true);
  assert.equal(pending.buyer_copy_status, "waiting_for_validated_listing_generation");

  const generated = sanitizeListingDraftSnapshot({
    source_type: "listing_ai_generation",
    product: "Foldable Tablet Stand",
    model_generated: true,
    buyer_copy_requires_validated_listing_generation: false,
    buyer_copy_status: "validated_listing_generated",
    fields: { title: "Foldable Aluminum Tablet Stand", selling_points: "One\nTwo\nThree", description: "Copy" },
  });
  assert.equal(generated.model_generated, true);
  assert.equal(generated.buyer_copy_requires_validated_listing_generation, false);
  assert.equal(generated.buyer_copy_status, "validated_listing_generated");
});

test("AI CEO product vision intake opens a fact project with buyer copy still awaiting validated generation", () => {
  const result = applyAiCeoProductVisionPacket({
    source: "backend_product_vision_extraction",
    vision_contract_version: "product_vision_fact_packet_v1",
    product_name: "Foldable Tablet Stand",
    source_confirmed_facts: { material: "Aluminum Alloy" },
    merchant_confirmed_facts: {},
    listing_copy: {
      title: "Universal iPad Pro Stand",
      selling_points: ["Fits iPad Pro", "Universal compatibility", "Supports 13-inch screens"],
      description: "Compatible with iPad Pro.",
    },
    unknown_facts: ["package_weight_g"],
  });

  assert.equal(result.product, "Foldable Tablet Stand");
  assert.equal(result.title, "Foldable Tablet Stand");
  assert.equal(result.fields.title, "");
  assert.equal(result.fields.selling_points, "");
  assert.equal(result.fields.description, "");
  assert.equal(result.model_generated, false);
  assert.equal(result.buyer_copy_requires_validated_listing_generation, true);
  assert.equal(result.buyer_copy_status, "waiting_for_validated_listing_generation");
});

test("product vision project cannot create an eBay confirmation before validated AI Listing generation", async () => {
  const outcome = await createConfirmationFromUnvalidatedVisionDraft();

  assert.equal(outcome.result, false);
  assert.equal(outcome.fetchCount, 0);
  assert.match(outcome.toasts.join("\n"), /AI Listing/);
});
