#!/usr/bin/env node
"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const http = require("node:http");
const { chromium } = require("../output/codex-playwright-deps/node_modules/playwright-core");

const root = path.resolve(__dirname, "..");
const source = fs.readFileSync(path.join(root, "app.js"), "utf8");
const browserChannel = process.env.JIEJING_PLAYWRIGHT_CHANNEL || "chrome";
const manualSourceBrowserRuns = [];

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

async function withManualSourcePage(run) {
  const startedAt = new Date().toISOString();
  const pending = [];
  const server = http.createServer((req, res) => {
    if (req.method === "GET" && req.url === "/") {
      res.writeHead(200, { "content-type": "text/html" });
      res.end('<!doctype html><title>Local product fact save</title><main id="view-product"></main>');
      return;
    }
    if (req.method !== "POST" || !/^\/stores\/fixture-store-[AB]\/product-facts$/.test(req.url)) {
      res.writeHead(404); res.end(); return;
    }
    let raw = "";
    req.on("data", (chunk) => { raw += chunk; });
    req.on("end", () => {
      const body = JSON.parse(raw);
      pending.push({ body, reply(status = 201, extra = {}) {
        res.writeHead(status, { "content-type": "application/json" });
        res.end(JSON.stringify({ ...(status === 201 ? {
          merchant_product_fact_packet: body.merchant_product_fact_packet,
          listing_project_identity: body.listing_project_identity,
          report: { report_id: `fixture-report-${pending.indexOf(this)}` },
          task: { task_id: `fixture-task-${pending.indexOf(this)}` },
        } : { error: "synthetic local save failure" }), ...extra }));
      } });
    });
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const browser = await chromium.launch({ channel: browserChannel, headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
    const errors = [];
    const observed = { loopback: 0, external: 0 };
    page.on("pageerror", (error) => errors.push(String(error)));
    page.on("request", (request) => {
      const host = new URL(request.url()).hostname;
      observed[host === "127.0.0.1" ? "loopback" : "external"]++;
    });
    await page.goto(`http://127.0.0.1:${server.address().port}/`);
    const starterBegin = source.indexOf('<section class="source-manual-form is-active saas-listing-source-facts-starter"');
    const starter = source.slice(starterBegin, source.indexOf("</section>", starterBegin) + "</section>".length);
    const functions = [...new Set([...baseFunctionNames, "handleSaasAction", "collectManualSourceFacts",
      "persistSaasManualSourceFacts", "saasFetch", "saasListingDraftFromManualSourceFacts",
      "buildSaasAiCeoSupplierFactIntake", "isFilledOperationalValue", "saasListingComposerDraftFromText",
      "saasListingSafeMaterialValue", "saasIsConcreteProductLabel", "saasIsInvalidMarketProductLabel",
      "saasCurrentListingProjectIdentity", "saasNormalizeListingProjectIdentity", "hashString",
      "resetSaasListingPublishEvidenceForNewProject", "setSaasAiCeoTaskContextState", "saasAiCeoTaskContextState",
      "parseSaasKeyValueLines"] )].map(extractFunction).join("\n");
    await page.evaluate((html) => { document.querySelector("main").innerHTML = html; }, starter);
    await page.addScriptTag({ content: `
      const SAAS_MERCHANT_PRODUCT_FACT_PACKET_CONTRACT = "merchant_product_fact_packet_v1";
      let saasStateRefreshGeneration = 0;
      const state = { saasConnected: true, saasApiBase: location.origin, saasToken: "", saasTasks: [], saasReports: [],
        saasIdentity: { company_id: "fixture-company-A", user_id: "fixture-user-A" }, manualSourceFacts: {} };
      window.__storeId = "fixture-store-A";
      window.__savePromises = []; window.__toasts = []; window.__snapshots = []; window.__unauthorized = 0;
      const publicRuntimeText = (value) => String(value ?? "");
      const sanitizeSaasWorkflowFeedbackText = (value, limit = 1000) => String(value ?? "").slice(0, limit);
      const activeSaasStore = () => ({ store_id: window.__storeId });
      const activeListingDraft = () => null;
      const isSaasPublicMvpMode = () => true;
      const isLegacySampleMediaDraftKey = () => false;
      const requireSaasProtectedSessionForAction = () => true;
      const formatDecisionTime = () => "synthetic local time";
      const recordSaasServerClock = () => {};
      const saasRequestCanRetryAfterSessionRefresh = () => false;
      const saasBackendErrorMessage = () => "synthetic local error";
      const handleSaasUnrecoverableSession = () => { window.__unauthorized++; };
      const showActionToast = (message) => window.__toasts.push(message);
      const saveSaasProtectedStateSnapshot = () => window.__snapshots.push(state.saasListingComposerDraft?.product);
      const renderSourceIntakePanel = () => {};
      const renderProductListingCenter = () => {};
      const scheduleSaasListingDraftSnapshotSave = () => {};
      ${generationContextHelpers}
      ${functions}
      const originalManualSave = persistSaasManualSourceFacts;
      persistSaasManualSourceFacts = (...args) => { const promise = originalManualSave(...args); window.__savePromises.push(promise); return promise; };
      document.addEventListener("click", (event) => {
        const button = event.target.closest("[data-saas-action]");
        if (button) handleSaasAction(button);
      });
      document.addEventListener("input", (event) => {
        if (event.target.matches("[data-saas-listing-draft-field]")) {
          setSaasListingDraftField(event.target.dataset.saasListingDraftField, event.target.value, { merchantEdited: true });
        }
      });
    ` });
    const fill = async (name) => page.locator('[data-source-manual-field="product_name"]').fill(name);
    const click = async () => page.locator('[data-saas-action="save-new-product-facts"]').click();
    const waitRequests = async (count) => {
      for (let i = 0; i < 100 && pending.length < count; i++) await new Promise((resolve) => setTimeout(resolve, 10));
      assert.equal(pending.length, count);
    };
    await run({ page, pending, fill, click, waitRequests });
    assert.deepEqual(errors, []);
    assert.equal(observed.external, 0);
    manualSourceBrowserRuns.push({ started_at: startedAt, ended_at: new Date().toISOString(),
      channel: browserChannel, browser_version: browser.version(), viewport: "1280x900",
      requests: observed, page_errors: errors.length, real_DOM_and_loopback_HTTP: true,
      route_handlers: 0, app_functions_extracted: true, full_app_rendering: false });
  } finally {
    await browser.close();
    server.closeAllConnections();
    await new Promise((resolve) => server.close(resolve));
  }
}

test.after(() => {
  if (manualSourceBrowserRuns.length) console.log(JSON.stringify({ manual_source_browser_runs: manualSourceBrowserRuns }));
});

test("manual product save sends a distinct action and its observed fact version", async () => {
  await withManualSourcePage(async ({ page, pending, fill, click, waitRequests }) => {
    await fill("Fixture Tablet Stand A"); await click(); await waitRequests(1);
    const first = pending[0].body.save_context;
    assert.equal(first?.contract_version, "merchant_product_fact_save_v1");
    assert.match(first.mutation_id, /^[A-Za-z0-9._:-]{8,160}$/);
    assert.equal(first.expected_fact_report_id, "");
    pending[0].reply(); await page.evaluate(() => window.__savePromises[0]);
    await page.locator('[data-source-manual-field="material"]').fill("Steel");
    await click(); await waitRequests(2);
    const second = pending[1].body.save_context;
    assert.equal(second.expected_fact_report_id, "fixture-report-0");
    assert.notEqual(second.mutation_id, first.mutation_id);
    pending[1].reply(); await page.evaluate(() => window.__savePromises[1]);
  });
});

test("manual product retry retains the failed action and base despite a fresh draft object", async () => {
  await withManualSourcePage(async ({ page, pending, fill, click, waitRequests }) => {
    await fill("Fixture Tablet Stand A"); await click(); await waitRequests(1);
    pending[0].reply(); await page.evaluate(() => window.__savePromises[0]);
    await page.locator('[data-source-manual-field="material"]').fill("Steel");
    await click(); await waitRequests(2);
    pending[1].reply(500); await page.evaluate(() => window.__savePromises[1]);
    await click(); await waitRequests(3);
    assert.deepEqual(pending[2].body.save_context, pending[1].body.save_context);
    assert.equal(pending[2].body.save_context.expected_fact_report_id, "fixture-report-0");
    pending[2].reply(); await page.evaluate(() => window.__savePromises[2]);
  });
});

for (const status of [201, 409]) {
  test(`manual facts preserve edits when ${status} reports a newer authoritative version`, async () => {
    await withManualSourcePage(async ({ page, pending, fill, click, waitRequests }) => {
      await fill("Fixture Tablet Stand A"); await click(); await waitRequests(1);
      pending[0].reply(status, { is_current: false, current_fact_report_id: "newer-cloud-version" });
      assert.equal(await page.evaluate(() => window.__savePromises[0]), false);
      assert.equal(await page.locator('[data-source-manual-field="product_name"]').inputValue(), "Fixture Tablet Stand A");
      assert.deepEqual(await page.evaluate(() => state.saasReports), []);
      assert.equal(await page.evaluate(() => state.saasListingProductFactSaveStatus), "local_only");
      assert.match(await page.evaluate(() => window.__toasts.at(-1)), /已有更新.*没有覆盖新版本/);
      assert.equal(pending.length, 1, "conflict must not automatically send another write");
    });
  });
}

test("existing fact form reuses a failed action but versions an intentional revert", async () => {
  await withProductFactPage(async (page) => {
    await page.evaluate(() => {
      state.saasConnected = true;
      state.saasCompany = { company_id: "company-A" };
      state.saasUser = { user_id: "user-A" };
      window.__productFactStore = { store_id: "store-A" };
      state.saasListingComposerDraft.source_product_fact_report_id = "fact-base-A";
      window.__factActions = [];
      window.__productFactFetch = async (_path, options) => {
        const body = JSON.parse(options.body);
        window.__factActions.push(body);
        if (window.__factActions.length === 1) throw new Error("synthetic lost response");
        return { merchant_product_fact_packet: body.merchant_product_fact_packet,
          listing_project_identity: body.listing_project_identity,
          report: { report_id: "fact-result-" + window.__factActions.length }, is_current: true };
      };
    });
    await page.locator('[data-saas-product-fact-field="material"]').fill("Steel");
    const save = page.locator('[data-saas-action="save-merchant-product-facts"]');
    await save.click(); await page.evaluate(() => window.__productFactSavePromise);
    await save.click(); await page.evaluate(() => window.__productFactSavePromise);
    await page.locator('[data-saas-product-fact-field="material"]').fill("Aluminum");
    await save.click(); await page.evaluate(() => window.__productFactSavePromise);
    const actions = await page.evaluate(() => window.__factActions.map(body => body.save_context));
    assert.deepEqual(actions[1], actions[0]);
    assert.equal(actions[0].expected_fact_report_id, "fact-base-A");
    assert.equal(actions[2].expected_fact_report_id, "fact-result-2");
    assert.notEqual(actions[2].mutation_id, actions[1].mutation_id);
    assert.equal(await page.locator('[data-saas-product-fact-field="material"]').inputValue(), "Aluminum");
  });
});

test("fact version fallback ignores other stores and candidates and keeps an observed draft base", async () => {
  await withProductFactPage(async (page) => {
    const result = await page.evaluate(() => {
      state.saasCompany = { company_id: "company-A" };
      state.saasUser = { user_id: "user-A" };
      window.__productFactStore = { store_id: "store-A" };
      const draft = state.saasListingComposerDraft;
      draft.listing_project_identity = { key: "project-A", source_report_id: "source-A", candidate_id: "candidate-A" };
      const row = { report_id: "matching-facts", company_id: "company-A", store_id: "store-A", status: "saved",
        report_type: "merchant.product_facts", created_at: "2026-09-07T08:00:00Z",
        report: { listing_project_identity: draft.listing_project_identity } };
      state.saasReports = [row, { ...row, report_id: "wrong-store", store_id: "store-B", created_at: "2027-01-01T00:00:00Z" },
        { ...row, report_id: "wrong-candidate", created_at: "2027-01-01T00:00:00Z",
          report: { listing_project_identity: { ...draft.listing_project_identity, candidate_id: "candidate-B" } } }];
      const fallback = prepareSaasProductFactSaveAttempt(draft, draft.merchant_product_fact_packet).saveContext;
      draft.source_product_fact_report_id = "observed-older-base";
      const observed = prepareSaasProductFactSaveAttempt(draft, draft.merchant_product_fact_packet).saveContext;
      const restoredDraft = sanitizeSaasListingComposerDraftSnapshot(draft);
      state.saasListingComposerDraft = restoredDraft;
      const restored = prepareSaasProductFactSaveAttempt(restoredDraft, restoredDraft.merchant_product_fact_packet).saveContext;
      state.saasListingComposerDraft = draft;
      draft.source_product_fact_report_id = "";
      const emptyBase = prepareSaasProductFactSaveAttempt(draft, draft.merchant_product_fact_packet).saveContext;
      draft.source_product_fact_report_id = "observed-older-base";
      state.saasUser = { user_id: "user-B" };
      const switched = prepareSaasProductFactSaveAttempt(draft, draft.merchant_product_fact_packet).saveContext;
      draft.listing_project_identity = { key: "legacy-key", source_report_id: "", candidate_id: "" };
      delete draft.source_product_fact_report_id;
      state.saasReports = [{ ...row, report_id: "partial-identity", report: { listing_project_identity: { key: "legacy-key" } } }];
      const partial = prepareSaasProductFactSaveAttempt(draft, draft.merchant_product_fact_packet).saveContext;
      return { fallback, observed, restored, emptyBase, switched, partial };
    });
    assert.equal(result.fallback.expected_fact_report_id, "matching-facts");
    assert.equal(result.observed.expected_fact_report_id, "observed-older-base");
    assert.equal(result.restored.expected_fact_report_id, "observed-older-base", "cached edits must retain their observed concurrency base, not borrow a newer report token");
    assert.equal(result.emptyBase.expected_fact_report_id, "", "an observed empty base must not borrow a newly arrived report token");
    assert.notEqual(result.switched.mutation_id, result.observed.mutation_id);
    assert.equal(result.partial.expected_fact_report_id, "");
  });
});

test("new source save preserves B when A replies after B's visible save", async () => {
  await withManualSourcePage(async ({ page, pending, fill, click, waitRequests }) => {
    await fill("Fixture Tablet Stand A"); await click(); await waitRequests(1);
    await fill("Fixture Tablet Stand B"); await click(); await waitRequests(2);
    pending[1].reply(); await page.evaluate(() => window.__savePromises[1]);
    pending[0].reply(); await page.evaluate(() => window.__savePromises[0]);
    assert.equal(await page.evaluate(() => state.saasListingComposerDraft.product), "Fixture Tablet Stand B");
    assert.equal(await page.locator('[data-source-manual-field="product_name"]').inputValue(), "Fixture Tablet Stand B");
    assert.deepEqual(await page.evaluate(() => state.saasReports.map((item) => item.report_id)), ["fixture-report-1"]);
  });
});

for (const status of [201, 500, 401]) {
  test(`new source save ignores late ${status} while B is still saving`, async () => {
    await withManualSourcePage(async ({ page, pending, fill, click, waitRequests }) => {
      await fill("Fixture Tablet Stand A"); await click(); await waitRequests(1);
      await fill("Fixture Tablet Stand B"); await click(); await waitRequests(2);
      pending[0].reply(status); await page.evaluate(() => window.__savePromises[0]);
      assert.deepEqual(await page.evaluate(() => ({ product: state.saasListingComposerDraft.product,
        status: state.saasListingProductFactSaveStatus, unauthorized: window.__unauthorized,
        reports: state.saasReports.length, toasts: window.__toasts.length,
        pending: Boolean(state.saasListingProductFactSaveRequest) })),
      { product: "Fixture Tablet Stand B", status: "saving", unauthorized: 0, reports: 0, toasts: 0, pending: true });
      pending[1].reply(); await page.evaluate(() => window.__savePromises[1]);
      assert.equal(await page.evaluate(() => state.saasListingProductFactSaveStatus), "saved");
    });
  });
}

test("new source save does not overwrite a newer visit to A or changed facts in the same project", async () => {
  for (const sameProject of [false, true]) {
    await withManualSourcePage(async ({ page, pending, fill, click, waitRequests }) => {
      await fill("Fixture Tablet Stand A");
      await page.locator('[data-source-manual-field="material"]').fill("Aluminum");
      await click(); await waitRequests(1);
      if (!sameProject) await fill("Fixture Tablet Stand B");
      await page.locator('[data-source-manual-field="material"]').fill("Steel");
      await click(); await waitRequests(2);
      await fill("Fixture Tablet Stand A");
      await page.locator('[data-source-manual-field="material"]').fill("Aluminum");
      await click(); await waitRequests(3);
      pending[2].reply(); await page.evaluate(() => window.__savePromises[2]);
      for (const index of [0, 1]) { pending[index].reply(); await page.evaluate((i) => window.__savePromises[i], index); }
      assert.equal(await page.evaluate(() => state.saasListingComposerDraft.product), "Fixture Tablet Stand A");
      assert.equal(await page.evaluate(() => state.saasListingComposerDraft.merchant_product_fact_packet.merchant_confirmed_facts.material), "Aluminum");
      assert.deepEqual(await page.evaluate(() => state.saasReports.map((item) => item.report_id)), ["fixture-report-2"]);
    });
  }
});

test("new source save deduplicates identical pending clicks without resetting hand edits", async () => {
  await withManualSourcePage(async ({ page, pending, fill, click, waitRequests }) => {
    await fill("Fixture Tablet Stand A"); await click(); await waitRequests(1);
    await page.evaluate(() => {
      const input = document.createElement("input"); input.dataset.saasListingDraftField = "title";
      document.querySelector("main").append(input);
    });
    await page.locator('[data-saas-listing-draft-field="title"]').fill("Merchant copy written during save");
    await click();
    assert.equal(await page.evaluate(() => window.__savePromises.length), 2);
    pending[0].reply(); await page.evaluate(() => Promise.all(window.__savePromises));
    assert.equal(pending.length, 1);
    assert.equal(await page.evaluate(() => state.saasListingComposerDraft.fields.title), "Merchant copy written during save");
    assert.equal(await page.locator('[data-saas-listing-draft-field="title"]').inputValue(), "Merchant copy written during save");
    assert.match(await page.evaluate(() => window.__toasts.at(-1)), /新修改仍保留/);
  });
});

for (const scope of ["company", "user", "store", "refresh", "visit"]) {
  test(`new source save rejects success and 401 after ${scope} changes`, async () => {
    for (const status of [201, 401]) {
      await withManualSourcePage(async ({ page, pending, fill, click, waitRequests }) => {
        await fill("Fixture Tablet Stand A"); await click(); await waitRequests(1);
        await page.evaluate((scope) => {
          if (scope === "company") state.saasIdentity.company_id = "fixture-company-B";
          if (scope === "user") state.saasIdentity.user_id = "fixture-user-B";
          if (scope === "store") window.__storeId = "fixture-store-B";
          if (scope === "refresh") saasStateRefreshGeneration++;
          if (scope === "visit") invalidateSaasListingAiGenerationContext();
          state.saasListingComposerDraft.fields.title = "Current scope copy";
          state.saasListingProductFactSaveStatus = "idle";
        }, scope);
        pending[0].reply(status); await page.evaluate(() => window.__savePromises[0]);
        assert.deepEqual(await page.evaluate(() => ({ reports: state.saasReports.length, tasks: state.saasTasks.length,
          snapshots: window.__snapshots.length, unauthorized: window.__unauthorized, toasts: window.__toasts.length,
          title: state.saasListingComposerDraft.fields.title, status: state.saasListingProductFactSaveStatus })),
        { reports: 0, tasks: 0, snapshots: 0, unauthorized: 0, toasts: 0, title: "Current scope copy", status: "idle" });
      });
    }
  });
}

test("new source save preserves unsaved manual input and still handles a current failure", async () => {
  for (const status of [201, 500]) {
    await withManualSourcePage(async ({ page, pending, fill, click, waitRequests }) => {
      await fill("Fixture Tablet Stand A"); await click(); await waitRequests(1);
      await fill("New unsaved product name");
      pending[0].reply(status); await page.evaluate(() => window.__savePromises[0]);
      assert.equal(await page.locator('[data-source-manual-field="product_name"]').inputValue(), "New unsaved product name");
      assert.equal(await page.evaluate(() => state.saasListingProductFactSaveStatus), status === 201 ? "saved" : "local_only");
      assert.equal(await page.evaluate(() => state.saasListingProductFactSaveRequest), null);
      assert.equal(await page.evaluate(() => state.saasListingProductFactSavePromise), null);
    });
  }
});

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
  "applySaasMerchantProductFactPacketToDraft",
  "saasCanonicalJsonValue",
  "invalidateSaasListingValidationForFactChange",
  "collectSaasMerchantProductFacts",
  "saveSaasMerchantProductFacts",
  "persistSaasMerchantProductFacts",
  "prepareSaasProductFactSaveAttempt",
  "assertSaasProductFactSaveIsCurrent",
  "saasProductFactSaveFailureMessage",
  "sanitizeSaasMerchantProductFactValues",
  "sanitizeSaasMerchantProductFactPacketSnapshot",
  "captureSaasListingFactsForAiGeneration",
  "generateSaasListingDraftFromCurrentProject",
  "saasListingMerchantEditableFieldKeys",
  "saasListingMerchantEditedFields",
  "saasListingEditableFieldText",
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
const generationContextHelpers = source.slice(
  source.indexOf("let saasListingAiGenerationEpoch ="),
  source.indexOf("async function generateSaasListingDraftFromCurrentProject("),
);

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
        let saasStateRefreshGeneration = 0;
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
        const saasCurrentListingProjectIdentity = (draft = state.saasListingComposerDraft) =>
          draft?.listing_project_identity || { key: "listing-project-tablet-stand" };
        const saasNormalizeListingProjectIdentity = (value) => value || null;
        const pickSaasSnapshotFields = (value, keys) => Object.fromEntries(
          keys.filter((key) => Object.prototype.hasOwnProperty.call(value || {}, key)).map((key) => [key, value[key]]),
        );
        const sanitizeSaasListingPublishPrefillSnapshot = (value) => ({ ...(value || {}) });
        const sanitizeSaasListingMediaWritebackSnapshot = (value) => ({ ...(value || {}) });
        const escapeHtml = (value) => String(value == null ? "" : value)
          .replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;")
          .replaceAll('"', "&quot;").replaceAll("'", "&#039;");
        ${generationContextHelpers}
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

async function seedValidatedAluminumListing(page) {
  await page.evaluate(() => {
      const draft = state.saasListingComposerDraft;
      draft.fields.title = "Aluminum Tablet Stand";
      draft.fields.selling_points = "Aluminum frame\nFoldable stand";
      draft.fields.description = "An aluminum tabletop stand.";
      draft.merchant_product_fact_packet = {
        source: "merchant_product_fact_packet", product_name: "Tablet Stand", simulation_only: false,
        merchant_confirmed_facts: { product_name: "Tablet Stand", condition: "NEW", material: "Aluminum" },
      };
      draft.model_generated = true;
      draft.safe_local_only = false;
      draft.buyer_copy_requires_validated_listing_generation = true;
      renderProductListingCenter();
      document.querySelector('[data-saas-listing-draft-field="title"]').value = draft.fields.title;
      document.querySelector('[data-saas-listing-draft-field="description"]').value = draft.fields.description;
    });
}

test("changing a confirmed material revokes old Listing validation without replacing its copy", async () => {
  await withProductFactPage(async (page) => {
    await seedValidatedAluminumListing(page);
    await page.locator('[data-saas-product-fact-field="material"]').fill("Steel");
    const draft = await page.evaluate(() => { captureSaasListingFactsForAiGeneration(); return state.saasListingComposerDraft; });
    assert.equal(draft.model_generated, false);
    assert.equal(draft.buyer_copy_requires_validated_listing_generation, true);
    assert.equal(draft.fields.title, "Aluminum Tablet Stand");
    assert.equal(draft.fields.selling_points, "Aluminum frame\nFoldable stand");
    assert.equal(draft.merchant_product_fact_packet.merchant_confirmed_facts.material, "Steel");
  });
});

test("same-value fact capture and save do not revoke an already validated Listing", async () => {
  await withProductFactPage(async (page) => {
    await seedValidatedAluminumListing(page);
    await page.locator('[data-saas-product-fact-field="material"]').fill("Aluminum");
    const result = await page.evaluate(async () => {
      captureSaasListingFactsForAiGeneration();
      const captured = state.saasListingComposerDraft.model_generated;
      await saveSaasMerchantProductFacts();
      return { captured, saved: state.saasListingComposerDraft.model_generated };
    });
    assert.deepEqual(result, { captured: true, saved: true });
  });
});

test("clearing a confirmed material revokes validation and does not resurrect its old value", async () => {
  await withProductFactPage(async (page) => {
    await seedValidatedAluminumListing(page);
    await page.locator('[data-saas-product-fact-field="material"]').fill("");
    const draft = await page.evaluate(() => { captureSaasListingFactsForAiGeneration(); return state.saasListingComposerDraft; });
    assert.equal(draft.model_generated, false);
    assert.equal(draft.buyer_copy_requires_validated_listing_generation, true);
    assert.equal(draft.merchant_product_fact_packet.merchant_confirmed_facts.material, undefined);
    assert.ok(draft.merchant_product_fact_packet.unknown_facts.includes("material"));
    assert.equal(draft.fields.title, "Aluminum Tablet Stand");
  });
});

test("failed regeneration keeps old copy visible but never restores validation for changed facts", async () => {
  await withProductFactPage(async (page) => {
    await seedValidatedAluminumListing(page);
    await page.locator('[data-saas-product-fact-field="material"]').fill("Steel");
    const result = await page.evaluate(async () => {
      state.saasConnected = true;
      window.__productFactStore = { store_id: "store-tablet" };
      window.__productFactFetch = async () => { throw new Error("fixture generation refused"); };
      const generated = await generateSaasListingDraftFromCurrentProject();
      return { generated, draft: state.saasListingComposerDraft, snapshot: sanitizeSaasListingComposerDraftSnapshot(state.saasListingComposerDraft) };
    });
    assert.equal(result.generated, false);
    for (const draft of [result.draft, result.snapshot]) {
      assert.equal(draft.model_generated, false);
      assert.equal(draft.buyer_copy_requires_validated_listing_generation, true);
      assert.equal(draft.fields.title, "Aluminum Tablet Stand");
      assert.equal(draft.fields.selling_points, "Aluminum frame\nFoldable stand");
      assert.equal(draft.fields.description, "An aluminum tabletop stand.");
    }
  });
});

test("saving changed facts also revokes validation before a later same-value capture", async () => {
  await withProductFactPage(async (page) => {
    await seedValidatedAluminumListing(page);
    await page.locator('[data-saas-product-fact-field="material"]').fill("Steel");
    const result = await page.evaluate(async () => {
      await saveSaasMerchantProductFacts();
      const saved = state.saasListingComposerDraft.model_generated;
      captureSaasListingFactsForAiGeneration();
      return { saved, captured: state.saasListingComposerDraft.model_generated };
    });
    assert.deepEqual(result, { saved: false, captured: false });
  });
});

async function startPendingProductFactSave(page) {
  await page.evaluate(async () => {
    state.saasConnected = true;
    state.saasCompany = { company_id: "company-A" };
    state.saasUser = { user_id: "user-A" };
    window.__productFactStore = { store_id: "store-A" };
    state.saasListingComposerDraft.listing_project_identity = { key: "project-A" };
    window.__pendingFactRequests = [];
    window.__productFactFetch = (_path, options) => new Promise((resolve, reject) => {
      window.__pendingFactRequests.push({ resolve, reject, options, body: JSON.parse(options.body) });
    });
    window.__firstFactSave = saveSaasMerchantProductFacts();
    await Promise.resolve();
  });
}

test("a completed fact save cannot replace the project opened while its request was pending", async () => {
  await withProductFactPage(async (page) => {
    await startPendingProductFactSave(page);
    const result = await page.evaluate(async () => {
      invalidateSaasListingAiGenerationContext();
      state.saasListingComposerDraft = {
        product: "B product", listing_project_identity: { key: "project-B" },
        fields: { title: "B newer copy" }, merchant_product_fact_packet: {},
      };
      const request = window.__pendingFactRequests[0];
      request.resolve({ merchant_product_fact_packet: request.body.merchant_product_fact_packet,
        listing_project_identity: request.body.listing_project_identity,
        task: { task_id: "old-A-task" }, report: { report_id: "old-A-report" } });
      await window.__firstFactSave;
      return { project: state.saasListingComposerDraft.listing_project_identity.key,
        title: state.saasListingComposerDraft.fields.title, tasks: state.saasTasks, reports: state.saasReports,
        toasts: window.__productFactToasts };
    });
    assert.equal(result.project, "project-B");
    assert.equal(result.title, "B newer copy");
    assert.deepEqual(result.tasks, []);
    assert.deepEqual(result.reports, []);
    assert.deepEqual(result.toasts, []);
  });
});

test("returning to the same project cannot accept a fact-save response from its previous visit", async () => {
  await withProductFactPage(async (page) => {
    await startPendingProductFactSave(page);
    const result = await page.evaluate(async () => {
      const original = state.saasListingComposerDraft;
      invalidateSaasListingAiGenerationContext();
      state.saasListingComposerDraft = { ...original, listing_project_identity: { key: "project-B" } };
      invalidateSaasListingAiGenerationContext();
      state.saasListingComposerDraft = { ...original, fields: { title: "A new visit edits" } };
      const request = window.__pendingFactRequests[0];
      const currentBeforeReply = request.options.saasRequestIsCurrent();
      request.resolve({ merchant_product_fact_packet: request.body.merchant_product_fact_packet,
        listing_project_identity: request.body.listing_project_identity });
      await window.__firstFactSave;
      return { currentBeforeReply, title: state.saasListingComposerDraft.fields.title, toasts: window.__productFactToasts };
    });
    assert.equal(result.currentBeforeReply, false);
    assert.equal(result.title, "A new visit edits");
    assert.deepEqual(result.toasts, []);
  });
});

for (const outcome of ["success", "failure"]) {
  test(`an old fact-save ${outcome} cannot clear a newer project's saving state or request`, async () => {
    await withProductFactPage(async (page) => {
      await startPendingProductFactSave(page);
      const result = await page.evaluate(async (outcome) => {
        invalidateSaasListingAiGenerationContext();
        state.saasListingComposerDraft = {
          ...state.saasListingComposerDraft, listing_project_identity: { key: "project-B" },
          fields: { title: "B current copy" },
        };
        renderProductListingCenter();
        const second = saveSaasMerchantProductFacts();
        await Promise.resolve();
        const requestCount = window.__pendingFactRequests.length;
        const firstRequest = window.__pendingFactRequests[0];
        if (outcome === "failure") firstRequest.reject(new Error("old A save failed"));
        else firstRequest.resolve({ merchant_product_fact_packet: firstRequest.body.merchant_product_fact_packet,
          listing_project_identity: firstRequest.body.listing_project_identity });
        await window.__firstFactSave;
        const intermediate = { status: state.saasListingProductFactSaveStatus,
          samePromise: state.saasListingProductFactSavePromise === second,
          buttonDisabled: document.querySelector('[data-saas-action="save-merchant-product-facts"]').disabled,
          toasts: [...window.__productFactToasts], project: saasCurrentListingProjectIdentity().key };
        const secondRequest = window.__pendingFactRequests[1];
        if (secondRequest) secondRequest.resolve({ merchant_product_fact_packet: secondRequest.body.merchant_product_fact_packet,
          listing_project_identity: secondRequest.body.listing_project_identity,
          report: { report_id: "B-facts-report" } });
        await second;
        return { requestCount, intermediate, finalStatus: state.saasListingProductFactSaveStatus,
          finalProject: saasCurrentListingProjectIdentity().key, savedReport: state.saasListingComposerDraft.source_product_fact_report_id,
          finalPromise: state.saasListingProductFactSavePromise };
      }, outcome);
      assert.equal(result.requestCount, 2);
      assert.deepEqual(result.intermediate, { status: "saving", samePromise: true, buttonDisabled: true, toasts: [], project: "project-B" });
      assert.equal(result.finalStatus, "saved");
      assert.equal(result.finalProject, "project-B");
      assert.equal(result.savedReport, "B-facts-report");
      assert.equal(result.finalPromise, null);
    });
  });
}

for (const changedScope of ["company", "user", "store", "source", "candidate"]) {
  test(`changing only ${changedScope} invalidates a pending fact-save response`, async () => {
    await withProductFactPage(async (page) => {
      await startPendingProductFactSave(page);
      const result = await page.evaluate(async (changedScope) => {
        if (changedScope === "company") state.saasCompany = { company_id: "company-B" };
        if (changedScope === "user") state.saasUser = { user_id: "user-B" };
        if (changedScope === "store") window.__productFactStore = { store_id: "store-B" };
        if (changedScope === "source") state.saasListingComposerDraft.listing_project_identity.source_report_id = "source-B";
        if (changedScope === "candidate") state.saasListingComposerDraft.listing_project_identity.candidate_id = "candidate-B";
        const currentDraft = state.saasListingComposerDraft;
        const request = window.__pendingFactRequests[0];
        const stillCurrent = request.options.saasRequestIsCurrent();
        request.resolve({ merchant_product_fact_packet: request.body.merchant_product_fact_packet,
          listing_project_identity: request.body.listing_project_identity,
          report: { report_id: "stale-report" } });
        await window.__firstFactSave;
        return { stillCurrent, sameDraft: state.saasListingComposerDraft === currentDraft,
          reports: state.saasReports, toasts: window.__productFactToasts };
      }, changedScope);
      assert.deepEqual(result, { stillCurrent: false, sameDraft: true, reports: [], toasts: [] });
    });
  });
}

test("a fact save still completes when only the current project's page changes", async () => {
  await withProductFactPage(async (page) => {
    await startPendingProductFactSave(page);
    const result = await page.evaluate(async () => {
      state.view = "media";
      const request = window.__pendingFactRequests[0];
      const stillCurrent = request.options.saasRequestIsCurrent();
      request.resolve({ merchant_product_fact_packet: request.body.merchant_product_fact_packet,
        listing_project_identity: request.body.listing_project_identity,
        report: { report_id: "A-saved-report" } });
      await window.__firstFactSave;
      return { stillCurrent, view: state.view, status: state.saasListingProductFactSaveStatus,
        savedReport: state.saasListingComposerDraft.source_product_fact_report_id, count: window.__pendingFactRequests.length };
    });
    assert.deepEqual(result, { stillCurrent: true, view: "media", status: "saved", savedReport: "A-saved-report", count: 1 });
  });
});

test("pending fact saves lock only the fact controls and unlock them after either outcome", async () => {
  for (const outcome of ["success", "failure"]) {
    await withProductFactPage(async (page) => {
      await startPendingProductFactSave(page);
      const during = await page.evaluate(() => ({
        factsLocked: [...document.querySelectorAll('[data-saas-product-fact-field]')].every(field => field.disabled),
        factActionsLocked: [...document.querySelectorAll('[data-saas-action="confirm-product-fact-suggestion"], [data-saas-action="mark-product-fact-unknown"]')].every(button => button.disabled),
        listingCopyEditable: !document.querySelector('[data-saas-listing-draft-field="title"]').disabled,
      }));
      assert.deepEqual(during, { factsLocked: true, factActionsLocked: true, listingCopyEditable: true });
      await page.evaluate(async (outcome) => {
        const request = window.__pendingFactRequests[0];
        if (outcome === "failure") request.reject(new Error("fixture fact save failed"));
        else request.resolve({ merchant_product_fact_packet: request.body.merchant_product_fact_packet,
          listing_project_identity: request.body.listing_project_identity });
        await window.__firstFactSave;
      }, outcome);
      assert.equal(await page.locator('[data-saas-product-fact-field="material"]').isEnabled(), true);
      await page.locator('[data-saas-product-fact-field="material"]').fill("A later edit");
      assert.equal(await page.locator('[data-saas-product-fact-field="material"]').inputValue(), "A later edit");
    });
  }
});

test("editing buyer copy during a fact save preserves those edits without restoring old validation", async () => {
  await withProductFactPage(async (page) => {
    await seedValidatedAluminumListing(page);
    await page.locator('[data-saas-product-fact-field="material"]').fill("Steel");
    await startPendingProductFactSave(page);
    await page.evaluate(() => {
      document.querySelector('#listing-draft-test-root').insertAdjacentHTML('beforeend',
        '<textarea data-saas-listing-draft-field="selling_points"></textarea>');
    });
    await page.locator('[data-saas-listing-draft-field="title"]').fill("New merchant title");
    await page.locator('[data-saas-listing-draft-field="selling_points"]').fill("New merchant point");
    await page.locator('[data-saas-listing-draft-field="description"]').fill("New merchant description");
    const result = await page.evaluate(async () => {
      const request = window.__pendingFactRequests[0];
      request.resolve({ merchant_product_fact_packet: request.body.merchant_product_fact_packet,
        listing_project_identity: request.body.listing_project_identity });
      await window.__firstFactSave;
      return state.saasListingComposerDraft;
    });
    assert.equal(result.fields.title, "New merchant title");
    assert.equal(result.fields.selling_points, "New merchant point");
    assert.equal(result.fields.description, "New merchant description");
    assert.equal(result.model_generated, false);
    assert.equal(result.buyer_copy_requires_validated_listing_generation, true);
    assert.deepEqual(result.merchant_edited_fields, ["title", "selling_points", "description"]);
  });
});
