#!/usr/bin/env node
"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const { chromium } = require("../output/codex-playwright-deps/node_modules/playwright-core");

const root = path.resolve(__dirname, "..");
const source = fs.readFileSync(path.join(root, "app.js"), "utf8");
const browserChannel = process.env.JIEJING_PLAYWRIGHT_CHANNEL || "chrome";

function extractFunction(name) {
  const asyncMarker = `async function ${name}(`;
  const marker = `function ${name}(`;
  const asyncStart = source.indexOf(asyncMarker);
  const start = asyncStart >= 0 ? asyncStart : source.indexOf(marker);
  assert.notEqual(start, -1, `${name} must exist in app.js`);
  const bodyStart = source.indexOf(") {", start) + 2;
  assert.ok(bodyStart > start, `${name} function body must exist in app.js`);
  let depth = 0;
  let quote = "";
  let escaped = false;
  for (let index = bodyStart; index < source.length; index += 1) {
    const char = source[index];
    if (escaped) {
      escaped = false;
      continue;
    }
    if (quote) {
      if (char === "\\") escaped = true;
      else if (char === quote) quote = "";
      continue;
    }
    if (char === '"' || char === "'" || char === "`") {
      quote = char;
      continue;
    }
    if (char === "{") depth += 1;
    if (char === "}") {
      depth -= 1;
      if (depth === 0) return source.slice(start, index + 1);
    }
  }
  throw new Error(`unterminated ${name} function`);
}

function extractOptionalFunction(name) {
  return source.includes(`function ${name}(`) ? extractFunction(name) : "";
}

const baseFunctionNames = [
  "saasMerchantProductFactDefinitions",
  "saasMerchantProductFactRequiredKeys",
  "saasMerchantProductFactValuePresent",
  "saasMerchantProductFactPacket",
  "saasMerchantProductFactOrigin",
  "saasMerchantProductFactReviewSummary",
  "saasMerchantProductFactSavedMessage",
  "renderSaasMerchantProductFactField",
  "renderSaasMerchantProductFactsModule",
  "saasMerchantProductFactLabel",
  "saasListingItemSpecificsWithMerchantFacts",
  "saasMerchantProductFactProjectedValue",
  "collectSaasMerchantProductFacts",
  "saveSaasMerchantProductFacts",
  "persistSaasMerchantProductFacts",
  "sanitizeSaasMerchantProductFactValues",
  "sanitizeSaasMerchantProductFactPacketSnapshot",
  "captureSaasListingFactsForAiGeneration",
  "generateSaasListingDraftFromCurrentProject",
  "saasListingMerchantEditableFieldKeys",
  "saasListingMerchantEditedFields",
  "setSaasListingDraftField",
  "captureSaasListingDraftEditor",
  "saasListingCurrentDraftFieldsForAi",
  "sanitizeSaasListingComposerDraftSnapshot",
];
const baseFunctions = baseFunctionNames.map((name) => {
  const functionSource = extractFunction(name);
  try {
    new Function(functionSource);
  } catch (error) {
    throw new Error(`${name} extraction is not valid JavaScript: ${error.message}\n${functionSource}`);
  }
  return functionSource;
}).join("\n") + `\n${extractOptionalFunction("markSaasMerchantProductFactEdited")}\n${extractOptionalFunction("confirmSaasMerchantProductFactSuggestion")}`;

async function withProductFactPage(run) {
  const browser = await chromium.launch({ channel: browserChannel, headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
    const pageErrors = [];
    page.on("pageerror", (error) => pageErrors.push(String(error?.stack || error)));
    await page.setContent('<main id="product-fact-test-root"></main><section id="listing-draft-test-root"></section>');
    await page.addScriptTag({
      content: `
        const SAAS_MERCHANT_PRODUCT_FACT_PACKET_CONTRACT = "merchant_product_fact_packet_v1";
        const state = {
          saasLoading: false,
          saasConnected: false,
          saasTasks: [],
          saasReports: [],
          saasListingAiGenerationStatus: "idle",
          saasListingComposerInput: "",
          saasListingComposerDraft: {
            product: "Foldable Tablet Stand",
            title: "Foldable Tablet Stand",
            fields: { item_specifics: "", description: "" },
            publish_prefill: {},
            merchant_product_fact_packet: {
              contract_version: "merchant_product_fact_packet_v1",
              source_mode: "source_missing",
              product_name: "Foldable Tablet Stand",
              simulation_only: true,
              source_confirmed_facts: {},
              merchant_confirmed_facts: {},
              derived_listing_suggestions: {
                product_name: "Foldable Tablet Stand",
                condition: "NEW",
                material: "Aluminum Alloy",
                package_weight_g: "450"
              },
              unknown_facts: ["product_name", "condition", "material", "package_weight_g", "sku"]
            }
          }
        };
        const publicRuntimeText = (value) => String(value == null ? "" : value);
        const sanitizeSaasWorkflowFeedbackText = (value, limit = 1000) => String(value == null ? "" : value).slice(0, limit);
        const parseSaasKeyValueLines = () => ({});
        window.__productFactToasts = [];
        const showActionToast = (message) => window.__productFactToasts.push(String(message || ""));
        const saveSaasProtectedStateSnapshot = () => { window.__savedFactPacket = sanitizeSaasMerchantProductFactPacketSnapshot(state.saasListingComposerDraft?.merchant_product_fact_packet); return true; };
        const requireSaasProtectedSessionForAction = () => true;
        const scheduleSaasListingDraftSnapshotSave = () => true;
        const renderProductListingCenter = () => {
          const root = document.querySelector("#product-fact-test-root");
          if (root) root.innerHTML = renderSaasMerchantProductFactsModule(state.saasListingComposerDraft);
        };
        window.__productFactStore = null;
        window.__productFactFetch = async () => ({});
        const activeSaasStore = () => window.__productFactStore;
        const saasFetch = (...args) => window.__productFactFetch(...args);
        const saasCurrentListingProjectIdentity = () => ({ key: "listing-project-tablet-stand" });
        const saasNormalizeListingProjectIdentity = (value) => value || null;
        const pickSaasSnapshotFields = (value, keys) => Object.fromEntries(
          keys.filter((key) => Object.prototype.hasOwnProperty.call(value || {}, key)).map((key) => [key, value[key]]),
        );
        const sanitizeSaasListingPublishPrefillSnapshot = (value) => ({ ...(value || {}) });
        const sanitizeSaasListingMediaWritebackSnapshot = (value) => ({ ...(value || {}) });
        const applySaasMerchantProductFactPacketToDraft = (draft, packet) => ({ ...draft, merchant_product_fact_packet: packet });
        const escapeHtml = (value) => String(value == null ? "" : value)
          .replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;")
          .replaceAll('"', "&quot;").replaceAll("'", "&#039;");
        ${baseFunctions}
        document.querySelector("#product-fact-test-root").innerHTML =
          renderSaasMerchantProductFactsModule(state.saasListingComposerDraft);
        document.querySelector("#listing-draft-test-root").innerHTML =
          '<input data-saas-listing-draft-field="title" value="Foldable Tablet Stand" />' +
          '<textarea data-saas-listing-draft-field="description"></textarea>' +
          '<input data-saas-listing-draft-field="category" value="Tablet & eBook Reader Accs" />';
        document.addEventListener("input", (event) => {
          if (event.target?.matches?.("[data-saas-listing-draft-field]")) {
            setSaasListingDraftField(
              event.target.dataset.saasListingDraftField || "",
              event.target.value || "",
              { merchantEdited: true },
            );
          }
          if (event.target?.matches?.("[data-saas-product-fact-field]") && typeof markSaasMerchantProductFactEdited === "function") {
            markSaasMerchantProductFactEdited(event.target);
          }
        });
        document.addEventListener("click", (event) => {
          const button = event.target?.closest?.('[data-saas-action="confirm-product-fact-suggestion"]');
          if (button && typeof confirmSaasMerchantProductFactSuggestion === "function") {
            confirmSaasMerchantProductFactSuggestion(button);
          }
          const saveButton = event.target?.closest?.('[data-saas-action="save-merchant-product-facts"]');
          if (saveButton) window.__productFactSavePromise = saveSaasMerchantProductFacts();
          const generateButton = event.target?.closest?.('[data-saas-action="listing-generate-ai-draft"]');
          if (generateButton) window.__capturedSimulationPacket = captureSaasListingFactsForAiGeneration();
        });
      `,
    });
    assert.deepEqual(pageErrors, [], `product fact UI setup failed: ${pageErrors.join("\n")}`);
    await run(page);
    assert.deepEqual(pageErrors, [], `product fact UI interaction failed: ${pageErrors.join("\n")}`);
  } finally {
    await browser.close();
  }
}

test("untouched AI suggestions stay suggestions instead of becoming merchant-confirmed facts", async () => {
  await withProductFactPage(async (page) => {
    assert.match(await page.locator('[data-product-fact-key="material"] [data-product-fact-origin]').textContent(), /AI 建议/);
    assert.equal(await page.locator('[data-saas-product-fact-field="material"]').inputValue(), "Aluminum Alloy");

    const collected = await page.evaluate(() => collectSaasMerchantProductFacts());
    assert.equal(collected.merchantConfirmed.material, undefined);
    assert.equal(collected.merchantConfirmed.package_weight_g, undefined);
    assert.ok(collected.unknownFacts.includes("material"));
    assert.ok(collected.unknownFacts.includes("package_weight_g"));
  });
});

test("editing an AI suggestion explicitly promotes only that field to merchant-confirmed", async () => {
  await withProductFactPage(async (page) => {
    await page.locator('[data-saas-product-fact-field="material"]').fill("ABS Plastic");
    const collected = await page.evaluate(() => collectSaasMerchantProductFacts());

    assert.equal(collected.merchantConfirmed.material, "ABS Plastic");
    assert.equal(collected.merchantConfirmed.package_weight_g, undefined);
    assert.ok(collected.unknownFacts.includes("package_weight_g"));
  });
});

test("merchant can explicitly confirm one AI suggestion without accepting the others", async () => {
  await withProductFactPage(async (page) => {
    const confirmButton = page.locator('[data-product-fact-key="package_weight_g"] [data-saas-action="confirm-product-fact-suggestion"]');
    assert.equal(await confirmButton.count(), 1);
    await confirmButton.click();
    const collected = await page.evaluate(() => collectSaasMerchantProductFacts());

    assert.equal(collected.merchantConfirmed.package_weight_g, "450");
    assert.equal(collected.merchantConfirmed.material, undefined);
    assert.equal(await page.locator('[data-product-fact-key="package_weight_g"] [data-product-fact-origin]').textContent(), "商家确认");
  });
});

test("vision-extracted fields are labelled as image recognition and confirmed one by one", async () => {
  await withProductFactPage(async (page) => {
    await page.evaluate(() => {
      const packet = state.saasListingComposerDraft.merchant_product_fact_packet;
      packet.source = "backend_product_vision_extraction";
      packet.vision_contract_version = "jiejing_ai_ceo_product_vision_intake_v1";
      packet.derived_listing_suggestions.source_url = "https://supplier.example/tablet-stand";
      document.querySelector("#product-fact-test-root").innerHTML =
        renderSaasMerchantProductFactsModule(state.saasListingComposerDraft);
    });

    assert.equal(
      await page.locator('[data-product-fact-key="material"] [data-product-fact-origin]').textContent(),
      "图片识别 · 待确认",
    );
    assert.equal(
      await page.locator('[data-product-fact-key="source_url"] [data-product-fact-origin]').textContent(),
      "图片识别 · 待确认",
    );
    const normalizedBeforeConfirmation = await page.evaluate(() =>
      saasMerchantProductFactPacket(state.saasListingComposerDraft),
    );
    assert.ok(normalizedBeforeConfirmation.unknown_facts.includes("source_url"));
    assert.ok(normalizedBeforeConfirmation.listing_readiness.ready_fact_count >= 0);
    assert.ok(normalizedBeforeConfirmation.listing_readiness.completion_percent >= 0);
    await page.locator('[data-product-fact-key="material"] [data-saas-action="confirm-product-fact-suggestion"]').click();
    const collected = await page.evaluate(() => collectSaasMerchantProductFacts());

    assert.equal(collected.merchantConfirmed.material, "Aluminum Alloy");
    assert.equal(collected.merchantConfirmed.source_url, undefined);
    assert.ok(collected.unknownFacts.includes("source_url"));
    assert.deepEqual(await page.evaluate(() => state.saasListingComposerDraft.merchant_product_fact_packet.source_confirmed_facts), {});
  });
});

test("image-only vision intake stays neutral until the merchant confirms product ownership", async () => {
  await withProductFactPage(async (page) => {
    await page.evaluate(() => {
      const packet = state.saasListingComposerDraft.merchant_product_fact_packet;
      packet.source = "backend_product_vision_extraction";
      packet.vision_contract_version = "jiejing_ai_ceo_product_vision_intake_v1";
      packet.source_mode = "merchant_images_supplied";
      delete packet.derived_listing_suggestions.source_url;
      document.querySelector("#product-fact-test-root").innerHTML =
        renderSaasMerchantProductFactsModule(state.saasListingComposerDraft);
    });

    const normalized = await page.evaluate(() => saasMerchantProductFactPacket(state.saasListingComposerDraft));
    assert.ok(normalized.unknown_facts.includes("merchant_owned_product_confirmed"));
    assert.equal(normalized.unknown_facts.includes("source_url"), false);
    await page.locator('[data-saas-product-fact-field="merchant_owned_product_confirmed"]').check();
    const collected = await page.evaluate(() => collectSaasMerchantProductFacts());
    assert.equal(collected.merchantConfirmed.merchant_owned_product_confirmed, true);
    assert.equal(collected.unknownFacts.includes("merchant_owned_product_confirmed"), false);
  });
});

test("saving untouched source facts preserves source provenance instead of relabeling it as merchant confirmation", async () => {
  await withProductFactPage(async (page) => {
    await page.evaluate(() => {
      state.saasListingComposerDraft.merchant_product_fact_packet.source_confirmed_facts.brand = "Source Brand";
      document.querySelector("#product-fact-test-root").innerHTML =
        renderSaasMerchantProductFactsModule(state.saasListingComposerDraft);
    });
    await page.locator('[data-saas-action="save-merchant-product-facts"]').click();
    await page.evaluate(() => window.__productFactSavePromise);
    const packet = await page.evaluate(() => state.saasListingComposerDraft.merchant_product_fact_packet);

    assert.equal(packet.source_confirmed_facts.brand, "Source Brand");
    assert.equal(packet.merchant_confirmed_facts.brand, undefined);
  });
});

test("clearing an AI suggestion records an explicit unknown instead of restoring the suggestion on save", async () => {
  await withProductFactPage(async (page) => {
    await page.locator('[data-saas-product-fact-field="material"]').fill("");
    await page.locator('[data-saas-action="save-merchant-product-facts"]').click();
    await page.evaluate(() => window.__productFactSavePromise);
    const packet = await page.evaluate(() => state.saasListingComposerDraft.merchant_product_fact_packet);

    assert.equal(Boolean(packet.derived_listing_suggestions.material), false);
    assert.ok(packet.unknown_facts.includes("material"));
  });
});

test("product fact summary separates AI suggestions awaiting confirmation from genuinely missing facts", async () => {
  await withProductFactPage(async (page) => {
    const moduleText = await page.locator(".saas-product-facts-module").innerText();
    const materialOrigin = await page.locator('[data-product-fact-key="material"] [data-product-fact-origin]').textContent();

    assert.equal(materialOrigin, "AI 建议 · 待确认");
    assert.match(moduleText, /待确认：[^\n]*(材质|包装重量)/);
    assert.match(moduleText, /仍缺：[^\n]*(SKU|实际发货地|图片 URL)/);
  });
});

test("saving confirmed facts preserves untouched AI suggestions in the suggestion layer", async () => {
  await withProductFactPage(async (page) => {
    await page.locator('[data-saas-action="save-merchant-product-facts"]').click();
    await page.evaluate(() => window.__productFactSavePromise);
    const packet = await page.evaluate(() => state.saasListingComposerDraft.merchant_product_fact_packet);

    assert.equal(packet.derived_listing_suggestions.material, "Aluminum Alloy");
    assert.equal(packet.derived_listing_suggestions.package_weight_g, "450");
    assert.equal(packet.merchant_confirmed_facts.material, undefined);
    assert.equal(packet.merchant_confirmed_facts.package_weight_g, undefined);
  });
});

test("save feedback tells the merchant which values await confirmation and which facts are absent", async () => {
  await withProductFactPage(async (page) => {
    await page.locator('[data-saas-action="save-merchant-product-facts"]').click();
    await page.evaluate(() => window.__productFactSavePromise);
    const message = await page.evaluate(() => window.__productFactToasts.at(-1) || "");

    assert.match(message, /待确认[^。]*(材质|包装重量)/);
    assert.match(message, /仍缺[^。]*(SKU|实际发货地|图片 URL)/);
  });
});

test("rapid product-fact saves share one request and expose a busy button", async () => {
  await withProductFactPage(async (page) => {
    const result = await page.evaluate(async () => {
      state.saasConnected = true;
      window.__productFactStore = { store_id: "store-tablet" };
      let requestCount = 0;
      let releaseRequest;
      const requestGate = new Promise((resolve) => { releaseRequest = resolve; });
      window.__productFactFetch = async (_path, options) => {
        requestCount += 1;
        await requestGate;
        const body = JSON.parse(options.body);
        return {
          merchant_product_fact_packet: body.merchant_product_fact_packet,
          listing_project_identity: body.listing_project_identity,
          task: { task_id: "task-product-facts" },
          report: { report_id: "report-product-facts" },
        };
      };
      const first = saveSaasMerchantProductFacts();
      const second = saveSaasMerchantProductFacts();
      await Promise.resolve();
      const button = document.querySelector('[data-saas-action="save-merchant-product-facts"]');
      const busy = {
        disabled: button?.disabled === true,
        label: button?.textContent || "",
        status: state.saasListingProductFactSaveStatus,
      };
      releaseRequest();
      await Promise.all([first, second]);
      return { requestCount, samePromise: first === second, busy };
    });

    assert.equal(result.requestCount, 1);
    assert.equal(result.samePromise, true);
    assert.equal(result.busy.disabled, true);
    assert.match(result.busy.label, /保存中/);
    assert.equal(result.busy.status, "saving");
  });
});

test("simulation generation carries AI suggestions without relabeling them as merchant facts", async () => {
  await withProductFactPage(async (page) => {
    await page.locator('[data-saas-action="listing-generate-ai-draft"]').click();
    const packet = await page.evaluate(() => window.__capturedSimulationPacket);

    assert.equal(packet.simulation_only, true);
    assert.equal(packet.derived_listing_suggestions.material, "Aluminum Alloy");
    assert.equal(packet.derived_listing_suggestions.package_weight_g, "450");
    assert.equal(packet.merchant_confirmed_facts.material, undefined);
    assert.ok(packet.unknown_facts.includes("material"));
  });
});

test("a blocked vision Listing generation keeps image provenance and the unconfirmed source boundary", async () => {
  await withProductFactPage(async (page) => {
    const captured = await page.evaluate(async () => {
      const packet = state.saasListingComposerDraft.merchant_product_fact_packet;
      packet.source = "backend_product_vision_extraction";
      packet.source_mode = "merchant_images_supplied";
      packet.vision_contract_version = "jiejing_ai_ceo_product_vision_intake_v1";
      packet.buyer_copy_requires_validated_listing_generation = true;
      packet.field_evidence = { material: { image_indexes: [0], confidence: 0.94 } };
      packet.fact_conflicts = [{ field: "material", values: ["Aluminum", "Plastic"], reason: "image conflict" }];
      packet.source_records = [{ type: "merchant_product_image", url: "https://images.example/tablet-stand.jpg", rights_status: "pending" }];
      state.saasConnected = true;
      window.__productFactStore = { store_id: "store-tablet" };
      let result;
      window.__productFactFetch = async (_path, options) => {
        result = JSON.parse(options.body).merchant_product_fact_packet;
        throw new Error("provider unavailable");
      };
      const completed = await generateSaasListingDraftFromCurrentProject();
      return { completed, status: state.saasListingAiGenerationStatus, result, statePacket: state.saasListingComposerDraft.merchant_product_fact_packet, savedPacket: window.__savedFactPacket };
    });

    assert.equal(captured.completed, false);
    assert.equal(captured.status, "failed");
    for (const packet of [captured.result, captured.statePacket, captured.savedPacket]) {
      assert.equal(packet.source, "backend_product_vision_extraction");
      assert.equal(packet.source_mode, "merchant_images_supplied");
      assert.equal(packet.vision_contract_version, "jiejing_ai_ceo_product_vision_intake_v1");
      assert.equal(packet.buyer_copy_requires_validated_listing_generation, true);
      assert.deepEqual(packet.field_evidence.material.image_indexes, [0]);
      assert.equal(packet.fact_conflicts[0].field, "material");
      assert.equal(packet.source_records[0].rights_status, "pending");
      assert.notEqual(packet.source_mode, "merchant_owned_product");
    }
  });
});

test("vision suggestions survive refresh but an explicitly cleared field cannot revive during generation", async () => {
  await withProductFactPage(async (page) => {
    await page.evaluate(() => {
      const draft = state.saasListingComposerDraft;
      draft.merchant_product_fact_packet.source = "backend_product_vision_extraction";
      draft.merchant_product_fact_packet.vision_contract_version = "jiejing_ai_ceo_product_vision_intake_v1";
      draft.merchant_product_fact_packet = sanitizeSaasMerchantProductFactPacketSnapshot(saasMerchantProductFactPacket(draft));
      renderProductListingCenter();
    });
    assert.equal(await page.locator('[data-saas-product-fact-field="material"]').inputValue(), "Aluminum Alloy");
    await page.locator('[data-saas-product-fact-field="material"]').fill("");
    const packet = await page.evaluate(() => {
      captureSaasListingFactsForAiGeneration();
      state.saasListingComposerDraft.publish_prefill.material = "Stale Aluminum Alloy";
      return saasMerchantProductFactPacket(state.saasListingComposerDraft);
    });
    assert.equal(packet.derived_listing_suggestions.material, undefined);
    assert.equal(packet.merchant_confirmed_facts.material, undefined);
    assert.ok(packet.unknown_facts.includes("material"));
  });
});

test("a legacy owned-product label never substitutes for the ownership checkbox", async () => {
  await withProductFactPage(async (page) => {
    const packet = await page.evaluate(() => {
      state.saasListingComposerDraft.merchant_product_fact_packet.source_mode = "merchant_owned_product";
      return saasMerchantProductFactPacket(state.saasListingComposerDraft);
    });
    assert.equal(packet.source_mode, "source_missing");
    assert.ok(packet.unknown_facts.includes("merchant_owned_product_confirmed"));
  });
});

test("only real Listing input events add fields to merchant edit provenance sent to AI", async () => {
  await withProductFactPage(async (page) => {
    await page.locator('[data-saas-listing-draft-field="title"]').fill("Merchant Edited Tablet Stand");
    await page.locator('[data-saas-listing-draft-field="description"]').fill("Merchant-authored buyer copy.");

    const currentDraftFields = await page.evaluate(() => saasListingCurrentDraftFieldsForAi());
    assert.deepEqual(currentDraftFields.merchant_edited_fields, ["title", "description"]);
  });
});

test("capturing rendered Listing fields does not claim untouched AI fields were merchant edited", async () => {
  await withProductFactPage(async (page) => {
    await page.evaluate(() => {
      document.querySelector('[data-saas-listing-draft-field="category"]').value = "AI suggested category";
      captureSaasListingDraftEditor();
    });

    const provenance = await page.evaluate(() => ({
      draft: state.saasListingComposerDraft.merchant_edited_fields || [],
      request: saasListingCurrentDraftFieldsForAi().merchant_edited_fields || [],
    }));
    assert.deepEqual(provenance.draft, []);
    assert.deepEqual(provenance.request, []);
  });
});

test("merchant edit provenance survives the protected Listing draft snapshot", async () => {
  await withProductFactPage(async (page) => {
    await page.locator('[data-saas-listing-draft-field="title"]').fill("Merchant Edited Tablet Stand");
    await page.locator('[data-saas-listing-draft-field="description"]').fill("Merchant-authored buyer copy.");

    const savedFields = await page.evaluate(() =>
      sanitizeSaasListingComposerDraftSnapshot(state.saasListingComposerDraft).merchant_edited_fields,
    );
    assert.deepEqual(savedFields, ["title", "description"]);
  });
});
