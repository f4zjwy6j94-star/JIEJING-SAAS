#!/usr/bin/env node
"use strict";

// Local backend-report replay through the actual frontend restore/render code.
// No model, provider, account, or eBay requests are allowed by this fixture.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const http = require("node:http");
const path = require("node:path");
const { test, before, after } = require("node:test");
const { chromium } = require("../output/codex-playwright-deps/node_modules/playwright-core");

const root = path.resolve(__dirname, "..");
const identity = { key: "restore-tablet-project", source_report_id: "vision-tablet-report", candidate_id: "tablet-candidate" };
const companyId = "restore-company";
const storeId = "restore-store";
const product = "Foldable Tablet Stand";
const title = "Foldable Tablet Stand Aluminum Desk Holder";
let server;
let browser;
let base;

function factReport(overrides = {}) {
  return {
    report_id: "vision-tablet-report", report_type: "merchant.product_facts", status: "saved",
    company_id: companyId, store_id: storeId, created_at: "2026-09-01T01:00:00Z",
    report: {
      product, listing_project_identity: identity,
      merchant_product_fact_packet: {
        source: "backend_product_vision_extraction", vision_contract_version: "jiejing_ai_ceo_product_vision_intake_v1",
        product_name: product, source_confirmed_facts: {}, merchant_confirmed_facts: {},
        derived_listing_suggestions: { product_name: product, material: "Aluminum" },
        listing_copy: { title: "UNVALIDATED VISION COPY", description: "UNVALIDATED DESCRIPTION" },
        buyer_copy_requires_validated_listing_generation: true,
        field_evidence: { material: { image_indexes: [1], confidence: 0.9 } },
        source_records: [{ type: "merchant_product_image", asset_id: "tablet-photo" }],
        unknown_facts: ["product_name", "material", "condition", "sku"], fact_conflicts: [],
      },
    },
    ...overrides,
  };
}

function listingReport(overrides = {}) {
  return {
    report_id: "listing-tablet-v2", report_type: "listing.package", runtime_run_id: "listing_draft_generation",
    status: "saved", company_id: companyId, store_id: storeId, created_at: "2026-09-02T01:00:00Z",
    report: {
      contract_version: "listing_ai_draft_generation_v1", artifact_type: "listing.package", version: 2,
      product, listing_project_identity: identity,
      merchant_product_fact_packet: {
        ...factReport().report.merchant_product_fact_packet,
        merchant_confirmed_facts: { product_name: product, material: "Aluminum", condition: "NEW" },
        derived_listing_suggestions: {}, listing_copy: {}, unknown_facts: ["sku"],
      },
      listing_handoff: {
        ready_for_listing_draft: true, source_mode: "project_scoped_live_model", target_report_type: "listing.package",
        listing_fields: { title, selling_points: ["Foldable desktop holder", "Aluminum construction"], description_seed: "A foldable aluminum stand for tabletop use." },
        requires_human_review_before_publish: true, triggers_real_platform_write: false,
      },
    },
    ...overrides,
  };
}

before(async () => {
  const source = fs.readFileSync(path.join(root, "app.js"), "utf8");
  const boot = /exposeLocalJiejingTestHooks\(\);\r?\ninit\(\);\r?\nrunLocalJiejingQaScenarioFromUrl\(\);\s*$/;
  assert.match(source, boot);
  const appSource = source.replace(boot, "exposeLocalJiejingTestHooks();\n");
  server = http.createServer((req, res) => {
    const url = new URL(req.url, "http://127.0.0.1");
    if (url.pathname === "/app.js") {
      res.writeHead(200, { "content-type": "text/javascript; charset=utf-8" });
      res.end(appSource);
    } else if (url.pathname === "/app.html") {
      res.writeHead(200, { "content-type": "text/html; charset=utf-8" });
      res.end('<!doctype html><html><head><title>Listing restore local regression</title></head><body data-view="product"><section id="view-product"></section><script src="/app.js"></script></body></html>');
    } else {
      res.writeHead(404);
      res.end("Local fixture: no business API");
    }
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  base = `http://127.0.0.1:${server.address().port}`;
  browser = await chromium.launch({ headless: true, channel: process.env.JIEJING_PLAYWRIGHT_CHANNEL || "chrome" });
});

after(async () => {
  if (browser) await browser.close();
  if (server) await new Promise((resolve) => server.close(resolve));
});

async function withRestorePage(reports, run, options = {}) {
  const context = await browser.newContext();
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.route("**/*", (route) => route.request().url().startsWith(base) ? route.continue() : route.abort());
  try {
    await page.goto(`${base}/app.html?start=app&qa=public-saas&project=${identity.key}`);
    await page.evaluate(({ reports, identity, companyId, storeId, options }) => {
      window.__JIEJING_FORCE_PUBLIC_MVP__ = true;
      localStorage.setItem(saasStorageKeys.storeId, storeId);
      state.saasIdentity = { user_id: "restore-user", company_id: companyId };
      state.saasUser = { user_id: "restore-user", email: "restore@example.invalid" };
      state.saasCompany = { company_id: companyId };
      state.saasStores = [{ store_id: storeId, company_id: companyId, platform: "ebay", marketplace: "EBAY_US" }];
      state.saasReports = reports;
      state.saasListingComposerDraft = options.currentDraft || null;
      state.saasListingSourceMode = options.currentDraft ? "local_unsaved_draft" : "";
      state.saasDetachedListingProjectDrafts = {};
      state.activeMediaDraft = "";
      state.view = "product";
      window.restoreOptions = { projectId: identity.key, ...options.restoreOptions };
    }, { reports, identity, companyId, storeId, options });
    await run(page);
    assert.deepEqual(errors, [], "actual frontend code has no uncaught errors");
  } finally {
    await context.close();
  }
}

test("reopening a vision-origin project renders its newer validated Listing, not an empty vision draft", async () => {
  const older = listingReport({ report_id: "listing-tablet-v1", created_at: "2026-09-01T12:00:00Z" });
  older.report.listing_handoff.listing_fields.title = "Older Tablet Holder Copy";
  await withRestorePage([factReport(), older, listingReport()], async (page) => {
    const restored = await page.evaluate(() => {
      const draft = restoreSaasListingComposerDraftFromBackendReports(window.restoreOptions);
      document.querySelector("#view-product").innerHTML = renderSaasListingDraftEditor(draft);
      return draft;
    });
    assert.equal(restored.fields.title, title);
    assert.equal(restored.fields.description, "A foldable aluminum stand for tabletop use.");
    assert.equal(restored.model_generated, true);
    assert.equal(restored.safe_local_only, false);
    assert.equal(restored.source_product_fact_report_id, "vision-tablet-report");
    assert.equal(restored.merchant_product_fact_packet.merchant_confirmed_facts.material, "Aluminum");
    assert.equal(await page.locator('[data-saas-listing-draft-field="title"]').inputValue(), title);
  });
});

test("later fact changes and explicit unknowns survive restore and require Listing revalidation", async () => {
  const confirmation = factReport({ report_id: "confirmed-tablet-facts", created_at: "2026-09-03T01:00:00Z" });
  confirmation.report.merchant_product_fact_packet = {
    ...confirmation.report.merchant_product_fact_packet,
    source: "merchant_product_fact_confirmation",
    merchant_confirmed_facts: { product_name: product, material: "Steel" },
    derived_listing_suggestions: {}, unknown_facts: ["condition", "sku"],
    fact_conflicts: [{ field: "package_weight_g", values: ["150", "180"] }],
    field_evidence: {}, source_records: [], listing_copy: {},
  };
  for (const hasCurrentDraft of [false, true]) {
    await withRestorePage([confirmation, factReport(), listingReport()], async (page) => {
      const draft = await page.evaluate((hasCurrentDraft) => {
        if (hasCurrentDraft) {
          state.saasListingComposerDraft = saasListingDraftFromReport(state.saasReports[2], "listing_ai_generation");
          state.saasListingComposerDraft.model_generated = true;
        }
        return restoreSaasListingComposerDraftFromBackendReports(window.restoreOptions);
      }, hasCurrentDraft);
      const packet = draft.merchant_product_fact_packet;
      assert.equal(draft.fields.title, title, "saved buyer copy remains reviewable, not silently regenerated");
      assert.equal(packet.merchant_confirmed_facts.material, "Steel");
      assert.equal(packet.merchant_confirmed_facts.condition, undefined, "explicit clear must not retain the older confirmed value");
      assert.equal(draft.publish_prefill.condition, "");
      assert.deepEqual(packet.fact_conflicts, [{ field: "package_weight_g", values: ["150", "180"] }]);
      assert.deepEqual(packet.field_evidence.material.image_indexes, [1]);
      assert.equal(packet.source_records[0].asset_id, "tablet-photo");
      assert.equal(draft.model_generated, false, "old copy is not validated against changed facts");
      assert.equal(draft.buyer_copy_requires_validated_listing_generation, true);
    });
  }
});

test("restore excludes other companies, stores, projects and origin identities before selecting the newest Listing", async () => {
  const foreignCases = [
    { company_id: "other-company" },
    { store_id: "other-store" },
    { report: { ...listingReport().report, listing_project_identity: { ...identity, key: "other-project" } } },
    { report: { ...listingReport().report, listing_project_identity: { ...identity, source_report_id: "other-origin" } } },
    { report: { ...listingReport().report, listing_project_identity: { ...identity, candidate_id: "other-candidate" } } },
  ];
  for (const foreignScope of foreignCases) {
    const foreign = listingReport({ ...foreignScope, report_id: "foreign-listing", created_at: "2026-09-04T01:00:00Z" });
    foreign.report = {
      ...foreign.report,
      listing_handoff: { ...foreign.report.listing_handoff, listing_fields: { ...foreign.report.listing_handoff.listing_fields, title: "Foreign Product Copy" } },
    };
    await withRestorePage([foreign, factReport(), listingReport()], async (page) => {
      const draft = await page.evaluate(() => restoreSaasListingComposerDraftFromBackendReports(window.restoreOptions));
      assert.equal(draft.fields.title, title, `foreign scope must not win: ${JSON.stringify(foreignScope)}`);
      assert.equal(draft.listing_project_identity.key, identity.key);
    });
  }
});

test("refresh preserves current merchant copy edits and does not reintroduce older vision unknowns", async () => {
  await withRestorePage([factReport(), listingReport()], async (page) => {
    const draft = await page.evaluate(() => {
      state.saasListingComposerDraft = saasListingDraftFromReport(state.saasReports[1], "listing_ai_generation");
      state.saasListingComposerDraft.model_generated = true;
      setSaasListingDraftField("title", "Merchant edited tablet title");
      setSaasListingDraftField("description", "Merchant edited description.");
      return restoreSaasListingComposerDraftFromBackendReports(window.restoreOptions);
    });
    assert.equal(draft.fields.title, "Merchant edited tablet title");
    assert.equal(draft.fields.description, "Merchant edited description.");
    assert.equal(draft.merchant_product_fact_packet.merchant_confirmed_facts.material, "Aluminum");
    assert.equal(draft.publish_prefill.condition, "NEW");
    assert.equal(draft.source_product_fact_report_id, "vision-tablet-report", "Listing version is not mislabeled as a fact report");
  });
});

test("a newer Listing on another device cannot validate preserved older buyer copy against its new facts", async () => {
  const newer = listingReport({ report_id: "listing-tablet-v3", created_at: "2026-09-03T01:00:00Z" });
  newer.report.merchant_product_fact_packet.merchant_confirmed_facts.material = "Steel";
  newer.report.listing_handoff.listing_fields = {
    title: "Foldable Steel Tablet Stand",
    selling_points: ["Steel construction"],
    description_seed: "A foldable steel stand for tabletop use.",
  };
  for (const merchantEdited of [false, true]) {
    await withRestorePage([factReport(), listingReport(), newer], async (page) => {
      const draft = await page.evaluate((merchantEdited) => {
        state.saasListingComposerDraft = saasListingDraftFromReport(state.saasReports[1], "listing_ai_generation");
        state.saasListingComposerDraft.model_generated = true;
        if (merchantEdited) setSaasListingDraftField("title", "My aluminum tablet holder title");
        return restoreSaasListingComposerDraftFromBackendReports(window.restoreOptions);
      }, merchantEdited);
      assert.equal(draft.fields.title, merchantEdited ? "My aluminum tablet holder title" : title);
      assert.equal(draft.fields.description, "A foldable aluminum stand for tabletop use.");
      assert.equal(draft.merchant_product_fact_packet.merchant_confirmed_facts.material, "Steel");
      assert.equal(draft.model_generated, false, "newer report must not grant validation to older preserved copy");
      assert.equal(draft.safe_local_only, true);
      assert.equal(draft.buyer_copy_requires_validated_listing_generation, true);
      const restoredAgain = await page.evaluate(() => restoreSaasListingComposerDraftFromBackendReports(window.restoreOptions));
      assert.equal(restoredAgain.model_generated, false, "a second refresh must not revalidate the stale copy");
      assert.equal(restoredAgain.fields.title, draft.fields.title);
    });
  }
});

test("vision-only or unvalidated report metadata never restores buyer copy as validated", async () => {
  const invalidListings = [
    null,
    listingReport({ status: "failed" }),
    listingReport({ runtime_run_id: "legacy_workflow" }),
    listingReport({ report: { ...listingReport().report, contract_version: "legacy_listing_v0" } }),
    listingReport({ report: { ...listingReport().report, listing_handoff: { ...listingReport().report.listing_handoff, source_mode: "vision_suggestion" } } }),
    listingReport({ report: { ...listingReport().report, listing_handoff: { ...listingReport().report.listing_handoff, ready_for_listing_draft: false } } }),
  ];
  for (const invalid of invalidListings) {
    await withRestorePage([factReport(), ...(invalid ? [invalid] : [])], async (page) => {
      const draft = await page.evaluate(() => restoreSaasListingComposerDraftFromBackendReports(window.restoreOptions));
      assert.equal(draft.fields.title, "");
      assert.equal(draft.fields.description, "");
      assert.equal(draft.fields.selling_points, "");
      assert.equal(draft.model_generated, false);
      assert.equal(draft.buyer_copy_requires_validated_listing_generation, true);
      assert.equal(draft.merchant_product_fact_packet.derived_listing_suggestions.material, "Aluminum");
    });
  }
});

test("vision-only latest explicit clears stay empty while source evidence and conflicts remain", async () => {
  const confirmed = factReport({ report_id: "confirmed-vision", created_at: "2026-09-02T01:00:00Z" });
  confirmed.report.merchant_product_fact_packet.merchant_confirmed_facts = { product_name: product, material: "Aluminum" };
  confirmed.report.merchant_product_fact_packet.unknown_facts = ["sku", "condition"];
  const cleared = factReport({ report_id: "cleared-vision", created_at: "2026-09-03T01:00:00Z" });
  cleared.report.merchant_product_fact_packet = {
    ...cleared.report.merchant_product_fact_packet,
    merchant_confirmed_facts: { product_name: product }, derived_listing_suggestions: {},
    unknown_facts: ["sku", "condition", "material"], field_evidence: {}, source_records: [],
    fact_conflicts: [{ field: "material", values: ["Aluminum", "Steel"] }],
  };
  await withRestorePage([cleared, factReport(), confirmed], async (page) => {
    const draft = await page.evaluate(() => restoreSaasListingComposerDraftFromBackendReports(window.restoreOptions));
    const packet = draft.merchant_product_fact_packet;
    assert.equal(draft.fields.title, "");
    assert.equal(packet.merchant_confirmed_facts.material, undefined);
    assert.equal(packet.derived_listing_suggestions.material, undefined);
    assert.equal(draft.publish_prefill.material, "");
    assert.deepEqual(packet.field_evidence.material.image_indexes, [1]);
    assert.equal(packet.source_records[0].asset_id, "tablet-photo");
    assert.deepEqual(packet.fact_conflicts, [{ field: "material", values: ["Aluminum", "Steel"] }]);
  });
});
