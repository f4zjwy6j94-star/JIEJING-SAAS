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

function supplierRevisionReport() {
  const candidate = { candidate_id: identity.candidate_id, name: product };
  return {
    report_id: "supplier-revision", report_type: "ai_ceo.market_research", status: "saved",
    company_id: companyId, store_id: storeId, created_at: "2026-09-04T01:00:00Z",
    report: {
      product, listing_project_identity: identity, merchant_question: "补充当前商品规格，供内部 Listing 演练，不发布。",
      answer: `商品：${product}\n材质：Stainless Steel\n商品状态：New\n仅为演练值，尚未核验真实商品。`,
      status: "answered", answer_quality: { accepted: true }, product_candidates: [candidate],
      selected_product_candidate: candidate,
      merchant_product_fact_packet: {
        product_name: product, simulation_only: true, fact_scope: "simulation_rehearsal",
        source_confirmed_facts: {}, merchant_confirmed_facts: { product_name: product },
        derived_listing_suggestions: { material: "Stainless Steel", condition: "New", unit_cost: "2.50", currency: "USD" },
        unknown_facts: ["material", "condition", "unit_cost", "currency", "image_rights_confirmed", "item_location"],
        source_records: [], fact_conflicts: [], listing_copy: {},
      },
      listing_handoff: { ready_for_listing_draft: false, listing_fields: {
        title: product, product_candidates: [candidate], selected_product_candidate: candidate,
      } },
    },
  };
}

test("importing a supplier revision retains the existing fact version and shows new suggestions without a false conflict", async () => {
  const facts = factReport({ report_id: "saved-facts-A" });
  facts.report.merchant_product_fact_packet = {
    source: "authenticated_merchant_request", product_name: product,
    source_confirmed_facts: {}, merchant_confirmed_facts: { product_name: product },
    derived_listing_suggestions: {}, unknown_facts: ["material", "condition"], listing_copy: {},
  };
  const revision = supplierRevisionReport();
  await withRestorePage([facts, revision], async (page) => {
    const imported = await page.evaluate(() => {
      state.saasProtectedStateReady = true;
      state.saasConnected = true;
      restoreSaasListingComposerDraftFromBackendReports({ ...window.restoreOptions,
        reports: state.saasReports.filter((row) => row.report_type === "merchant.product_facts") });
      renderProductListingCenter();
      const record = state.saasReports.find((row) => row.report_id === "supplier-revision");
      const turn = saasAiCeoMarketTurnFromReport(record);
      return { applied: applySaasAiCeoMarketTurnToListing({ ...turn, rendered_product: record.report.product }, { expectedProduct: record.report.product }), eligibility: saasAiCeoMarketResearchEligibility(turn),
        label: saasProductLabelForRecord(record), canStart: saasAiCeoMarketReportCanStartBlockedListingDraft(record) };
    });
    assert.equal(imported.applied, true, JSON.stringify(imported));
    assert.equal(await page.locator('[data-saas-product-fact-field="material"]').inputValue(), "Stainless Steel");
    assert.equal(await page.locator('[data-saas-product-fact-version-warning]').count(), 0,
      "a report import must not invent a conflict with the fact version that was already loaded");
    const current = await page.evaluate(() => ({
      draft: state.saasListingComposerDraft,
      save: prepareSaasProductFactSaveAttempt(state.saasListingComposerDraft, saasMerchantProductFactPacket()).saveContext,
    }));
    assert.equal(current.save.expected_fact_report_id, facts.report_id);
    assert.deepEqual(current.draft.listing_project_identity, identity);
    assert.equal(current.draft.merchant_product_fact_packet.simulation_only, true);
    assert.equal(current.draft.merchant_product_fact_packet.merchant_confirmed_facts.material, undefined);
  });
});

test("a supplier revision preserves merchant facts and copy while its unsaved suggestions survive a report refresh", async () => {
  const facts = factReport({ report_id: "saved-facts-A" });
  facts.report.merchant_product_fact_packet = {
    source: "authenticated_merchant_request", product_name: product,
    source_confirmed_facts: {}, merchant_confirmed_facts: { product_name: product, material: "Aluminum" },
    derived_listing_suggestions: {}, unknown_facts: ["condition"], listing_copy: {},
  };
  await withRestorePage([facts, supplierRevisionReport()], async (page) => {
    const result = await page.evaluate(() => {
      state.saasProtectedStateReady = true;
      state.saasConnected = true;
      restoreSaasListingComposerDraftFromBackendReports({ ...window.restoreOptions,
        reports: state.saasReports.filter((row) => row.report_type === "merchant.product_facts") });
      state.saasListingComposerDraft.fields.title = "My edited product title";
      state.saasListingComposerDraft.merchant_edited_fields = ["title"];
      renderProductListingCenter();
      const record = state.saasReports.find((row) => row.report_id === "supplier-revision");
      const turn = { ...saasAiCeoMarketTurnFromReport(record), rendered_product: record.report.product };
      const applied = applySaasAiCeoMarketTurnToListing(turn, { expectedProduct: record.report.product });
      const beforeRefresh = structuredClone(state.saasListingComposerDraft);
      restoreSaasListingComposerDraftFromBackendReports(window.restoreOptions);
      renderProductListingCenter();
      return { applied, beforeRefresh, afterRefresh: state.saasListingComposerDraft };
    });
    assert.equal(result.applied, true);
    for (const draft of [result.beforeRefresh, result.afterRefresh]) {
      assert.equal(draft.merchant_product_fact_packet.merchant_confirmed_facts.material, "Aluminum");
      assert.equal(draft.merchant_product_fact_packet.derived_listing_suggestions.condition, "New");
      assert.equal(draft.merchant_product_fact_packet.simulation_only, true);
      assert.equal(draft.source_product_fact_report_id, facts.report_id);
      assert.equal(draft.fields.title, "My edited product title");
      assert.deepEqual(draft.merchant_edited_fields, ["title"]);
    }
    assert.equal(await page.locator('[data-saas-product-fact-version-warning]').count(), 0);
  });
});

test("import does not rebase an older editor when another device has saved newer facts", async () => {
  const facts = factReport({ report_id: "saved-facts-A" });
  const newer = factReport({ report_id: "saved-facts-B", created_at: "2026-09-05T01:00:00Z" });
  await withRestorePage([facts, supplierRevisionReport()], async (page) => {
    const result = await page.evaluate((newer) => {
      state.saasProtectedStateReady = true;
      state.saasConnected = true;
      restoreSaasListingComposerDraftFromBackendReports({ ...window.restoreOptions,
        reports: state.saasReports.filter((row) => row.report_type === "merchant.product_facts") });
      renderProductListingCenter();
      state.saasReports.push(newer);
      const record = state.saasReports.find((row) => row.report_id === "supplier-revision");
      applySaasAiCeoMarketTurnToListing({ ...saasAiCeoMarketTurnFromReport(record), rendered_product: record.report.product },
        { expectedProduct: record.report.product });
      restoreSaasListingComposerDraftFromBackendReports(window.restoreOptions);
      renderProductListingCenter();
      return prepareSaasProductFactSaveAttempt(state.saasListingComposerDraft, saasMerchantProductFactPacket()).saveContext;
    }, newer);
    assert.equal(result.expected_fact_report_id, facts.report_id, "CAS must reject a later save against B, not silently overwrite B");
    assert.equal(await page.locator('[data-saas-product-fact-version-warning]').count(), 1);
    assert.equal(await page.locator('[data-saas-product-fact-field="condition"]').inputValue(), "New");
  });
});

test("direct report import chooses only the same tenant store and exact origin fact baseline", async () => {
  const facts = factReport({ report_id: "saved-facts-A" });
  const foreign = ["company_id", "store_id", "source_report_id", "candidate_id"].map((key, index) => {
    const row = structuredClone(facts);
    row.report_id = `foreign-${key}`;
    row.created_at = `2026-09-1${index}T01:00:00Z`;
    if (["company_id", "store_id"].includes(key)) row[key] = "different-scope";
    else row.report.listing_project_identity[key] = "different-origin";
    return row;
  });
  await withRestorePage([...foreign, facts, supplierRevisionReport()], async (page) => {
    const draft = await page.evaluate(() => {
      state.saasProtectedStateReady = true;
      state.saasConnected = true;
      const record = state.saasReports.find((row) => row.report_id === "supplier-revision");
      applySaasAiCeoMarketTurnToListing({ ...saasAiCeoMarketTurnFromReport(record), rendered_product: record.report.product },
        { expectedProduct: record.report.product });
      return state.saasListingComposerDraft;
    });
    assert.equal(draft.source_product_fact_report_id, facts.report_id);
    assert.deepEqual(draft.listing_project_identity, identity);
    assert.equal(await page.locator('[data-saas-product-fact-version-warning]').count(), 0);
  });
});

test("saving imported suggestions uses the observed base and ends the local import hold only on success", async () => {
  const facts = factReport({ report_id: "saved-facts-A" });
  await withRestorePage([facts, supplierRevisionReport()], async (page) => {
    const requests = [];
    await page.route(`**/stores/${storeId}/product-facts`, async (route) => {
      const body = route.request().postDataJSON();
      requests.push(body);
      const report = { ...facts, report_id: "saved-import", created_at: "2026-09-06T01:00:00Z",
        report: { listing_project_identity: identity, merchant_product_fact_packet: body.merchant_product_fact_packet } };
      await route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify({
        is_current: true, listing_project_identity: identity, merchant_product_fact_packet: body.merchant_product_fact_packet, report,
      }) });
    });
    const result = await page.evaluate(async () => {
      state.saasProtectedStateReady = true;
      state.saasConnected = true;
      state.saasApiBase = location.origin;
      const record = state.saasReports.find((row) => row.report_id === "supplier-revision");
      applySaasAiCeoMarketTurnToListing({ ...saasAiCeoMarketTurnFromReport(record), rendered_product: record.report.product },
        { expectedProduct: record.report.product });
      const saved = await saveSaasMerchantProductFacts();
      return { saved, draft: state.saasListingComposerDraft };
    });
    assert.equal(result.saved, true);
    assert.equal(requests.length, 1);
    assert.equal(requests[0].save_context.expected_fact_report_id, facts.report_id);
    assert.equal(requests[0].merchant_product_fact_packet.simulation_only, true);
    assert.equal(result.draft.source_product_fact_report_id, "saved-import");
    assert.equal(result.draft.pending_product_fact_import, undefined);
    assert.equal(await page.locator('[data-saas-product-fact-version-warning]').count(), 0);
  });
});

test("an authenticated reload resumes a pending import from its scoped local snapshot without losing suggestions", async () => {
  const facts = factReport({ report_id: "saved-facts-A" });
  await withRestorePage([facts, supplierRevisionReport()], async (page) => {
    const draft = await page.evaluate(() => {
      state.saasProtectedStateReady = true;
      state.saasConnected = true;
      const record = state.saasReports.find((row) => row.report_id === "supplier-revision");
      applySaasAiCeoMarketTurnToListing({ ...saasAiCeoMarketTurnFromReport(record), rendered_product: record.report.product },
        { expectedProduct: record.report.product });
      state.saasListingComposerDraft = sanitizeSaasListingComposerDraftSnapshot(state.saasListingComposerDraft);
      return restoreSaasListingComposerDraftFromBackendReports({ ...window.restoreOptions,
        preferBackendLatest: true, restoreDetachedDraft: true });
    });
    assert.equal(draft.source_product_fact_report_id, facts.report_id);
    assert.equal(draft.merchant_product_fact_packet.simulation_only, true);
    assert.equal(draft.merchant_product_fact_packet.derived_listing_suggestions.unit_cost, "2.50");
    assert.ok(draft.pending_product_fact_import);
  });
});

test("approved media reaches the real image editor, survives a backend refresh, and saves using its fact base", async () => {
  const facts = factReport({ report_id: "saved-facts-A" });
  facts.report.merchant_product_fact_packet = { ...listingReport().report.merchant_product_fact_packet,
    simulation_only: true, unknown_facts: ["image_urls", "image_rights_confirmed", "item_location"] };
  const url = "https://cdn.example.test/approved-tablet.jpg";
  const job = { media_job_id: "approved-tablet-media", store_id: storeId, status: "approved_for_listing",
    live_provider_called: true, updated_at: "2026-09-06T03:00:00Z",
    job: { job_spec: { inputs: { product_facts: { listing_project_key: identity.key, listing_project_identity: identity,
      source_asset_id: "supplier-tablet-photo", private_source_transport: "backend_asset_id" } } } },
    asset_manifest_validation: { status: "manifest_ready" },
    merchant_review: { decision: "approve_for_listing_draft", reviewed_by: "restore-user",
      listing_draft_only: true, triggers_real_platform_write: false,
      confirmations: { fact_consistency_confirmed: true, commercial_rights_confirmed: true, platform_rules_checked: true } },
    asset_review: { status: "approved_for_listing_draft", listing_use_status: "approved_for_listing_draft",
      reviewed_at: "2026-09-06T03:00:00Z" },
    asset_manifest: [{ asset_id: "approved-photo", asset_type: "product_image", url_or_file_path: url,
      fact_review_status: "confirmed_by_merchant", commercial_use_status: "confirmed_by_merchant",
      listing_use_status: "approved_for_listing_draft", review_status: "approved_for_listing_draft" }],
  };
  await withRestorePage([facts, listingReport()], async (page) => {
    const requests = [];
    await page.route("**/media-asset-jobs/approved-tablet-media", route => route.fulfill({
      status: 200, contentType: "application/json", body: JSON.stringify({ media_asset_job: job }) }));
    await page.route(`**/stores/${storeId}/product-facts`, async route => {
      const body = route.request().postDataJSON(); requests.push(body);
      const report = { ...facts, report_id: "saved-media-facts", created_at: "2026-09-06T04:00:00Z",
        report: { listing_project_identity: identity, merchant_product_fact_packet: body.merchant_product_fact_packet } };
      await route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify({
        is_current: true, listing_project_identity: identity, merchant_product_fact_packet: body.merchant_product_fact_packet, report }) });
    });
    const selected = await page.evaluate(async job => {
      state.saasProtectedStateReady = true; state.saasConnected = true; state.saasApiBase = location.origin;
      restoreSaasListingComposerDraftFromBackendReports(window.restoreOptions);
      state.saasMediaAssetJobs = [job];
      const view = document.querySelector("#view-product");
      view.innerHTML = renderSaasListingWizardImages(state.saasListingComposerDraft);
      restoreSaasPendingProductFactEditor(view, null);
      const result = await revalidateAndApplySaasMediaManifestToListingDraft({ entry: "single" });
      state.saasListingComposerDraft = sanitizeSaasListingComposerDraftSnapshot(state.saasListingComposerDraft);
      const restored = restoreSaasListingComposerDraftFromBackendReports({ ...window.restoreOptions,
        preferBackendLatest: true, restoreDetachedDraft: true });
      view.innerHTML = renderSaasListingWizardImages(restored);
      restoreSaasPendingProductFactEditor(view, null);
      return { result, draft: restored, urls: saasListingWizardImageUrls(restored) };
    }, job);
    assert(selected.result);
    assert.deepEqual(selected.urls, [url]);
    assert.equal(selected.draft.source_product_fact_report_id, facts.report_id);
    assert.equal(selected.draft.merchant_product_fact_packet.simulation_only, true);
    assert.equal(await page.locator('[data-saas-product-fact-field="image_urls"]').inputValue(), url);
    assert.equal(await page.locator('[data-saas-product-fact-field="image_rights_confirmed"]').isChecked(), false);
    const saved = await page.evaluate(async () => ({ ok: await saveSaasMerchantProductFacts(), draft: state.saasListingComposerDraft }));
    assert.equal(saved.ok, true);
    assert.equal(requests.length, 1);
    assert.equal(requests[0].save_context.expected_fact_report_id, facts.report_id);
    assert.equal(requests[0].merchant_product_fact_packet.merchant_confirmed_facts.image_urls, url);
    assert.equal(requests[0].merchant_product_fact_packet.merchant_confirmed_facts.image_rights_confirmed, undefined);
    assert.equal(saved.draft.source_product_fact_report_id, "saved-media-facts");
    assert.equal(saved.draft.pending_product_fact_import, undefined);
  });
});

for (const failure of ["rejected", "source_unavailable"]) {
  test(`a saved ${failure} AI report explains its actual failure through the real non-importable report resolver`, async () => {
    const report = supplierRevisionReport();
    if (failure === "rejected") {
      report.report.status = "model_answer_rejected";
      report.report.answer_quality = { accepted: false, blocked_by: ["model_answer_truncated_table"] };
    } else report.report.evidence_status = "supplier_source_unavailable";
    await withRestorePage([report], async (page) => {
      const result = await page.evaluate(() => {
        const turn = saasAiCeoMarketTurnFromReport(state.saasReports[0]);
        const markup = renderSaasAiCeoMarketReportDeliveryMarkup(turn);
        document.querySelector('#view-product').innerHTML = markup;
        return { authoritative: saasAuthoritativeAiCeoMarketReportForTurn(turn), markup };
      });
      assert.equal(result.authoritative, null, "failed reports must remain ineligible for import");
      assert.ok(result.markup.includes(failure === "rejected" ? "本次内容未通过校验" : "来源页面暂不可读取"));
      assert.doesNotMatch(result.markup, /补齐候选商品|导入 Listing 草稿/);
    });
  });
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

for (const change of ["pending", "withdrawn-rights", "hash", "url", "asset", "distinct-source"]) {
  test(`source history uses the latest scoped observation without hiding a ${change} change`, async () => {
    const previous = factReport({ report_id: "previous-source", created_at: "2026-09-03T01:00:00Z" });
    const originalSource = { type: "merchant_product_image", url: "https://images.example.test/selected.jpg",
      asset_id: "selected-asset", sha256: "a".repeat(64), rights_status: "merchant_confirmed" };
    const retainedSource = { type: "merchant_product_image", asset_id: "historical-upload",
      rights_status: "pending_merchant_confirmation" };
    previous.report.merchant_product_fact_packet.source_records = [originalSource, retainedSource];
    previous.report.merchant_product_fact_packet.merchant_confirmed_facts = {
      product_name: product, material: "Aluminum", condition: "NEW",
      image_urls: originalSource.url, image_rights_confirmed: true };
    previous.report.merchant_product_fact_packet.unknown_facts = ["sku"];
    const current = structuredClone(previous);
    Object.assign(current, { report_id: "current-source", created_at: "2026-09-04T01:00:00Z" });
    const newestSource = { ...originalSource, signed_url_persisted: false };
    if (["pending", "withdrawn-rights"].includes(change)) newestSource.rights_status = "pending_merchant_confirmation";
    if (change === "hash") newestSource.sha256 = "b".repeat(64);
    if (["url", "distinct-source"].includes(change)) newestSource.url = "https://images.example.test/replacement.jpg";
    if (["asset", "distinct-source"].includes(change)) newestSource.asset_id = "replacement-asset";
    current.report.merchant_product_fact_packet.source_records = [newestSource, retainedSource];
    if (["pending", "withdrawn-rights"].includes(change)) {
      current.report.merchant_product_fact_packet.merchant_confirmed_facts.image_rights_confirmed = false;
    }
    await withRestorePage([current, listingReport(), previous], async (page) => {
      const result = await page.evaluate((previousPacket) => {
        const draft = restoreSaasListingComposerDraftFromBackendReports(window.restoreOptions);
        document.querySelector("#view-product").innerHTML = renderSaasMerchantProductFactsModule(draft);
        return { draft, previousSignature: saasListingMediaCopyFactSignature(previousPacket, { includeMedia: true }),
          currentSignature: saasListingMediaCopyFactSignature(draft.merchant_product_fact_packet, { includeMedia: true }) };
      }, previous.report.merchant_product_fact_packet);
      const packet = result.draft.merchant_product_fact_packet;
      assert.deepEqual(packet.source_records[0], newestSource,
        "the later record wins as a whole, even when an older record has stronger rights or more metadata");
      assert.equal(packet.source_records.filter(record => record.asset_id === retainedSource.asset_id).length, 1,
        "distinct historical evidence remains available without duplicate projection");
      const previousSelected = packet.source_records.filter(record => record.url === originalSource.url && record.asset_id === originalSource.asset_id);
      assert.equal(previousSelected.length, change === "distinct-source" || ["pending", "withdrawn-rights", "hash"].includes(change) ? 1 : 0);
      assert.notEqual(result.currentSignature, result.previousSignature, "real source changes remain part of the unchanged-facts guard");
      if (["pending", "withdrawn-rights"].includes(change)) {
        assert.equal(packet.merchant_confirmed_facts.image_rights_confirmed, false);
        assert.equal(await page.locator('[data-saas-product-fact-field="image_rights_confirmed"]').isChecked(), false,
          "a prior confirmed source must not check the current merchant authorization control");
        assert.equal(packet.source_records.some(record => record.url === newestSource.url && record.rights_status === "merchant_confirmed"), false);
      }
      assert.equal(result.draft.source_product_fact_report_id, current.report_id);
    });
  });
}

test("history merging leaves the latest source snapshot and observation order intact", async () => {
  const previous = factReport({ report_id: "previous-observations" });
  const current = structuredClone(previous);
  Object.assign(current, { report_id: "latest-observations", created_at: "2026-09-03T01:00:00Z" });
  const url = "https://images.example.test/shared-source.jpg";
  const sources = [
    { type: "merchant_product_link", url, rights_status: "not_applicable" },
    { type: "merchant_product_image", url, asset_id: "tablet-photo", rights_status: "pending_merchant_confirmation" },
    { type: "merchant_product_image", url, asset_id: "tablet-photo", rights_status: "merchant_confirmed" },
  ];
  current.report.merchant_product_fact_packet.source_records = sources;
  await withRestorePage([current, previous], async (page) => {
    const draft = await page.evaluate(() => restoreSaasListingComposerDraftFromBackendReports(window.restoreOptions));
    assert.deepEqual(draft.merchant_product_fact_packet.source_records, sources,
      "cross-report precedence must not discard or reorder observations already in the latest authoritative report");
  });
});

test("known full identity rejects foreign facts while ambiguous key-only cold restore imports neither origin", async () => {
  const current = factReport({ report_id: "current-pending", created_at: "2026-09-03T01:00:00Z" });
  const source = { type: "merchant_product_image", url: "https://images.example.test/current.jpg",
    asset_id: "current-asset", rights_status: "pending_merchant_confirmation" };
  current.report.merchant_product_fact_packet.source_records = [source];
  for (const scope of ["company", "store", "project", "source", "candidate"]) {
    const foreign = structuredClone(current);
    Object.assign(foreign, { report_id: `foreign-${scope}`, created_at: "2026-09-05T01:00:00Z" });
    foreign.report.merchant_product_fact_packet.source_records[0].rights_status = "merchant_confirmed";
    if (scope === "company") foreign.company_id = "different-company";
    if (scope === "store") foreign.store_id = "different-store";
    if (scope === "project") foreign.report.listing_project_identity.key = "different-project";
    if (scope === "source") foreign.report.listing_project_identity.source_report_id = "different-source";
    if (scope === "candidate") foreign.report.listing_project_identity.candidate_id = "different-candidate";
    for (const mode of ["cold", "current", "prefer-backend"]) {
      await withRestorePage([foreign, current, listingReport()], async (page) => {
        const result = await page.evaluate((mode) => {
          if (mode !== "cold") state.saasListingComposerDraft = saasListingDraftFromReport(state.saasReports[2], "existing_project");
          const reportsBefore = JSON.stringify(state.saasReports);
          const draft = restoreSaasListingComposerDraftFromBackendReports({ ...window.restoreOptions,
            preferBackendLatest: mode === "prefer-backend" });
          return { draft, reportsUnchanged: reportsBefore === JSON.stringify(state.saasReports), active: state.saasListingComposerDraft };
        }, mode);
        assert.equal(result.reportsUnchanged, true, "ambiguity must not delete or rewrite either source's persisted reports");
        if (mode === "cold" && ["source", "candidate"].includes(scope)) {
          assert.equal(result.draft, null, "a route key alone cannot select a different complete origin identity");
          assert.equal(result.active, null, "neither ambiguous origin may be imported into the editor");
        } else {
          assert.deepEqual(result.draft.merchant_product_fact_packet.source_records.find(record => record.url === source.url), source, `${scope}/${mode}`);
          assert.equal(result.draft.source_product_fact_report_id, current.report_id, `${scope}/${mode}`);
          assert.deepEqual(result.draft.listing_project_identity, identity, `${scope}/${mode}`);
        }
      });
    }
  }
});

test("incomplete source identities cannot seed a cold restore or replace an explicitly empty complete anchor", async () => {
  for (const missing of ["source_report_id", "candidate_id"]) {
    const incomplete = structuredClone(factReport({ report_id: `incomplete-${missing}`, created_at: "2026-09-05T01:00:00Z" }));
    delete incomplete.report.listing_project_identity[missing];
    incomplete.report.merchant_product_fact_packet.merchant_confirmed_facts.image_rights_confirmed = true;
    await withRestorePage([incomplete], async (page) => {
      assert.equal(await page.evaluate(() => restoreSaasListingComposerDraftFromBackendReports(window.restoreOptions)), null);
    });
    const complete = factReport({ report_id: "explicit-empty-origin" });
    complete.report.listing_project_identity = { key: identity.key, source_report_id: "", candidate_id: "" };
    complete.report.merchant_product_fact_packet.merchant_confirmed_facts.image_rights_confirmed = false;
    await withRestorePage([incomplete, complete], async (page) => {
      const draft = await page.evaluate(() => restoreSaasListingComposerDraftFromBackendReports(window.restoreOptions));
      assert.deepEqual(draft.listing_project_identity, complete.report.listing_project_identity);
      assert.equal(draft.merchant_product_fact_packet.merchant_confirmed_facts.image_rights_confirmed, false);
    });
  }
});

test("navigating from a different draft to an ambiguous route preserves its local copy without displaying it in the target", async () => {
  const first = factReport();
  const second = structuredClone(first);
  second.report_id = "ambiguous-second-origin";
  second.report.listing_project_identity.source_report_id = "another-origin";
  const previous = listingReport({ report_id: "previous-project-listing" });
  previous.report.listing_project_identity = { ...identity, key: "previous-project" };
  await withRestorePage([first, second, previous], async (page) => {
    const result = await page.evaluate(() => {
      const reportsBefore = JSON.stringify(state.saasReports);
      state.saasListingComposerDraft = saasListingDraftFromReport(state.saasReports[2], "existing_project");
      state.saasListingComposerDraft.fields.title = "Unsaved previous project title";
      state.saasListingComposerDraft.merchant_edited_fields = ["title"];
      const restored = restoreSaasListingComposerDraftFromBackendReports(window.restoreOptions);
      renderProductListingCenter();
      return { restored, active: state.saasListingComposerDraft,
        retained: detachedSaasListingProjectDraft("previous-project")?.draft,
        reportsUnchanged: JSON.stringify(state.saasReports) === reportsBefore,
        visibleDraftControls: document.querySelectorAll('[data-saas-listing-draft-field]').length };
    });
    assert.equal(result.restored, null);
    assert.equal(result.active, null, "a failed restore must not leave the previous project's editable projection on the new route");
    assert.equal(result.visibleDraftControls, 0);
    assert.equal(result.retained.fields.title, "Unsaved previous project title", "local copy stays in its existing project-scoped holding area");
    assert.equal(result.reportsUnchanged, true);
  });
});

for (const localOrigin of ["missing-anchor", "unobserved-third-origin"]) {
  test(`ambiguous cold restore holds ${localOrigin} local copy without leaving an editable same-key projection`, async () => {
    const first = factReport();
    const second = structuredClone(first);
    second.report_id = "second-observed-origin";
    second.report.listing_project_identity.source_report_id = "second-origin";
    await withRestorePage([first, second], async (page) => {
      const result = await page.evaluate((localOrigin) => {
        state.saasConnected = true; state.saasProtectedStateReady = true;
        const reportsBefore = JSON.stringify(state.saasReports);
        const draft = saasListingDraftFromReport(state.saasReports[0], "local_unsaved_draft");
        draft.listing_project_identity = structuredClone(draft.listing_project_identity);
        if (localOrigin === "missing-anchor") delete draft.listing_project_identity.source_report_id;
        else draft.listing_project_identity.source_report_id = localOrigin;
        draft.fields.title = "UNVERIFIED SAME-KEY LOCAL TITLE";
        draft.merchant_edited_fields = ["title"];
        state.saasListingComposerDraft = draft;
        const restored = restoreSaasListingComposerDraftFromBackendReports(window.restoreOptions);
        setSaasListingWizardStep(2); renderProductListingCenter();
        return { restored, active: state.saasListingComposerDraft,
          retained: detachedSaasListingProjectDraft(draft.listing_project_identity.key)?.draft,
          reportsUnchanged: JSON.stringify(state.saasReports) === reportsBefore,
          editableControls: document.querySelectorAll('[data-saas-listing-draft-field]:not([disabled])').length };
      }, localOrigin);
      assert.equal(result.restored, null);
      assert.equal(result.active, null);
      assert.equal(result.editableControls, 0, "returning null alone must not leave the unverified draft editable on this route");
      assert.equal(result.retained.fields.title, "UNVERIFIED SAME-KEY LOCAL TITLE");
      assert.equal(result.reportsUnchanged, true);
    });
  });
}

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

test("anchored restore excludes other companies, stores, projects and origin identities before selecting the newest Listing", async () => {
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
      const draft = await page.evaluate(() => {
        state.saasListingComposerDraft = saasListingDraftFromReport(state.saasReports[2], "existing_project");
        return restoreSaasListingComposerDraftFromBackendReports({ ...window.restoreOptions, preferBackendLatest: true });
      });
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

test("facts-only restore preserves exact empty-anchor edits but rejects another origin's detached draft", async () => {
  const emptyIdentity = { key: identity.key, source_report_id: "", candidate_id: "" };
  const facts = factReport({ report_id: "manual-facts-current", created_at: "2026-09-03T01:00:00Z" });
  facts.report.listing_project_identity = emptyIdentity;
  facts.report.merchant_product_fact_packet = {
    source: "authenticated_merchant_request", product_name: product,
    source_confirmed_facts: {}, merchant_confirmed_facts: { product_name: product, material: "Aluminum" },
    derived_listing_suggestions: {}, listing_copy: {}, unknown_facts: ["sku"], fact_conflicts: [],
  };
  const outcomes = {};
  for (const variant of ["same", "source", "candidate"]) {
    await withRestorePage([facts], async (page) => {
      outcomes[variant] = await page.evaluate((variant) => {
        const backend = restoreSaasListingComposerDraftFromBackendReports({
          ...window.restoreOptions, preferBackendLatest: true, restoreDetachedDraft: false,
        });
        const local = structuredClone(backend);
        local.fields.title = "My locally edited tablet stand title";
        if (variant === "source") local.listing_project_identity.source_report_id = "different-source";
        if (variant === "candidate") local.listing_project_identity.candidate_id = "different-candidate";
        if (variant !== "same") local.source_product_fact_report_id = "another-origin-facts";
        state.saasListingComposerDraft = local;
        state.saasListingSourceMode = "local_unsaved_draft";
        const stashed = stashSaasCurrentListingProjectDraft();
        const watermarks = [];
        if (variant === "same") {
          // New reports in another origin can arrive after this exact-origin
          // draft was stashed. They must not invalidate its local edit baseline.
          for (const [index, anchor] of ["source_report_id", "candidate_id"].entries()) {
            const foreign = structuredClone(state.saasReports[0]);
            foreign.report_id = `other-origin-facts-${index}`;
            foreign.created_at = `2026-09-0${4 + index}T01:00:00Z`;
            foreign.report.listing_project_identity[anchor] = `different-${anchor}`;
            state.saasReports.push(foreign);
            watermarks.push(saasListingDraftSourceReportTimestamp(local));
          }
        }
        const restored = restoreSaasListingComposerDraftFromBackendReports({
          ...window.restoreOptions, reports: [state.saasReports[0]],
          preferBackendLatest: true, restoreDetachedDraft: true,
        });
        document.querySelector("#view-product").innerHTML = renderSaasListingDraftEditor(restored);
        return { stashed, watermarks, draft: restored,
          titleInput: document.querySelector('[data-saas-listing-draft-field="title"]').value };
      }, variant);
    });
  }
  assert.equal(outcomes.same.stashed, true);
  assert.deepEqual(outcomes.same.watermarks, [facts.created_at, facts.created_at],
    "later reports from either different origin anchor must not change this draft's backend watermark");
  assert.deepEqual(outcomes.same.draft.listing_project_identity, emptyIdentity);
  assert.equal(outcomes.same.draft.source_product_fact_report_id, facts.report_id);
  assert.equal(outcomes.same.titleInput, "My locally edited tablet stand title");
  for (const variant of ["source", "candidate"]) {
    assert.equal(outcomes[variant].stashed, true, `${variant}: exercise a real sanitized detached snapshot`);
    assert.deepEqual(outcomes[variant].draft.listing_project_identity, emptyIdentity,
      `${variant}: an explicit empty origin must not act as a wildcard for local drafts`);
    assert.equal(outcomes[variant].draft.source_product_fact_report_id, facts.report_id);
    assert.equal(outcomes[variant].titleInput, "", `${variant}: another origin's buyer copy must not be rendered`);
    assert.equal(outcomes[variant].draft.model_generated, false);
  }
});
