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
const duplicateGuardSource = extractFunction(
  "function saasPreTestPayloadText",
  "\nfunction saasPreTestFormSummary",
);
const factPacketProjectionSource = extractFunction(
  "function saasMerchantProductFactProjectedValue",
  "\nfunction applySaasAiCeoProductFactPacket",
);

function publishPrefill({ input, logistics }) {
  const sandbox = {
    __input: input,
    __logistics: logistics,
  };
  vm.runInNewContext(
    `
const state = {
  saasListingComposerInput: globalThis.__input,
  saasListingSourceMode: "ai_ceo_market_report",
  saasListingComposerDraft: {
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
