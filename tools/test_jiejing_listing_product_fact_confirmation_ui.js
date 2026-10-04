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
  return extractFunctionFromText(name, source);
}

function extractFunctionFromText(name, text) {
  const asyncMarker = `async function ${name}(`;
  const marker = `function ${name}(`;
  const asyncStart = text.indexOf(asyncMarker);
  const start = asyncStart >= 0 ? asyncStart : text.indexOf(marker);
  assert.notEqual(start, -1, `${name} must exist in app.js`);
  const bodyStart = text.indexOf(") {", start) + 2;
  assert.ok(bodyStart > start, `${name} function body must exist in app.js`);
  let depth = 0;
  let quote = "";
  let escaped = false;
  let comment = "";
  for (let index = bodyStart; index < text.length; index += 1) {
    const char = text[index], next = text[index + 1];
    if (comment) {
      if (comment === "line" && (char === "\n" || char === "\r")) comment = "";
      else if (comment === "block" && char === "*" && next === "/") { comment = ""; index += 1; }
      continue;
    }
    if (escaped) {
      escaped = false;
      continue;
    }
    if (quote) {
      if (char === "\\") escaped = true;
      else if (char === quote) quote = "";
      continue;
    }
    if (char === "/" && (next === "/" || next === "*")) {
      comment = next === "/" ? "line" : "block";
      index += 1;
      continue;
    }
    if (char === '"' || char === "'" || char === "`") {
      quote = char;
      continue;
    }
    if (char === "{") depth += 1;
    if (char === "}") {
      depth -= 1;
      if (depth === 0) return text.slice(start, index + 1);
    }
  }
  throw new Error(`unterminated ${name} function`);
}

test("function extraction ignores comment punctuation without treating string URLs as comments", () => {
  const fixture = [
    "async function fixture() {",
    "  // A visit's unfinished quote and } do not end or extend the function.",
    "  /* An unmatched brace { and quote ' are comment data. */",
    '  const url = "https://example.invalid/a/*literal*/";',
    "  return { url };",
    "}",
  ].join("\n");
  assert.equal(extractFunctionFromText("fixture", fixture + "\nfunction later() { return 1; }"), fixture);
  assert.doesNotThrow(() => new Function(extractFunctionFromText("fixture", fixture)));
});

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
      "persistSaasManualSourceFacts", "saasFetch", "assertSaasAccountSessionCurrent", "saasListingDraftFromManualSourceFacts",
      "buildSaasAiCeoSupplierFactIntake", "isFilledOperationalValue", "saasListingComposerDraftFromText",
      "saasListingSafeMaterialValue", "saasIsConcreteProductLabel", "saasIsInvalidMarketProductLabel",
      "saasCurrentListingProjectIdentity", "saasNormalizeListingProjectIdentity", "hashString",
      "resetSaasListingPublishEvidenceForNewProject", "setSaasAiCeoTaskContextState", "saasAiCeoTaskContextState",
      "parseSaasKeyValueLines"] )].map(extractFunction).join("\n");
    await page.evaluate((html) => { document.querySelector("main").innerHTML = html; }, starter);
    await page.addScriptTag({ content: `
      const SAAS_MERCHANT_PRODUCT_FACT_PACKET_CONTRACT = "merchant_product_fact_packet_v1";
      let saasStateRefreshGeneration = 0;
      let saasAccountSessionEpoch = 0;
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
      ${source.slice(source.indexOf("function escapeHtml(value) {"), source.indexOf("const jiejingTrustedHtmlBlockedPattern ="))}
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
      await page.evaluate(() => document.querySelector("main").insertAdjacentHTML("beforeend", renderSaasMerchantProductFactsModule()));
      await fill("Fixture Tablet Stand B"); await click(); await waitRequests(2);
      pending[0].reply(status); await page.evaluate(() => window.__savePromises[0]);
      assert.deepEqual(await page.evaluate(() => ({ product: state.saasListingComposerDraft.product,
        status: state.saasListingProductFactSaveStatus, unauthorized: window.__unauthorized,
        reports: state.saasReports.length, toasts: window.__toasts.length,
        pending: Boolean(state.saasListingProductFactSaveRequest) })),
      { product: "Fixture Tablet Stand B", status: "saving", unauthorized: 0, reports: 0, toasts: 0, pending: true });
      assert.equal(await page.locator('[data-saas-action="listing-generate-ai-draft"]').isDisabled(), true);
      assert.equal(await page.locator('[data-saas-action="save-merchant-product-facts"]').textContent(), "保存中…");
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
        await page.evaluate(() => document.querySelector("main").insertAdjacentHTML("beforeend", renderSaasMerchantProductFactsModule()));
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
          title: state.saasListingComposerDraft.fields.title, status: state.saasListingProductFactSaveStatus,
          requestPresent: !!state.saasListingProductFactSaveRequest, promisePresent: !!state.saasListingProductFactSavePromise,
          generateDisabled: document.querySelector('[data-saas-action="listing-generate-ai-draft"]').disabled,
          saveText: document.querySelector('[data-saas-action="save-merchant-product-facts"]').textContent })),
        { reports: 0, tasks: 0, snapshots: 0, unauthorized: 0, toasts: 0, title: "Current scope copy", status: "idle",
          requestPresent: false, promisePresent: false, generateDisabled: scope !== "refresh",
          saveText: scope === "refresh" ? "保存已确认资料" : "保存中…" });
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

test("new source save outcomes release only their rendered locks and preserve copy provenance and other busy work", async () => {
  for (const status of [201, 500]) for (const otherBusy of [false, true]) {
  await withManualSourcePage(async ({ page, pending, fill, click, waitRequests }) => {
    await fill("Fixture Tablet Stand A"); await click(); await waitRequests(1);
    await page.evaluate(() => {
      state.saasListingComposerDraft.merchant_product_fact_packet.derived_listing_suggestions.brand = "Unconfirmed fixture brand";
      document.querySelector("main").insertAdjacentHTML("beforeend", renderSaasMerchantProductFactsModule() +
        '<input data-saas-listing-draft-field="title" />');
      window.__factValuesAndOrigins = () => [...document.querySelectorAll('[data-saas-product-fact-field]')].map(field => ({
        key: field.dataset.saasProductFactField, value: field.value, checked: field.checked,
        origin: field.dataset.productFactOriginState, confirmed: field.dataset.productFactConfirmed,
        unknown: field.dataset.productFactUnknown,
      }));
    });
    assert.equal(await page.locator('[data-saas-product-fact-field="material"]').isDisabled(), true);
    assert.ok(await page.locator('.saas-product-facts-module input[type="checkbox"]').count());
    assert.ok(await page.locator('.saas-product-facts-module textarea').count());
    assert.ok(await page.locator('[data-saas-action="confirm-product-fact-suggestion"]').count());
    const factFieldsBefore = await page.evaluate(() => window.__factValuesAndOrigins());
    await page.locator('[data-saas-listing-draft-field="title"]').fill("Copy typed during save");
    await page.evaluate((busy) => {
      window.__typedCopyNode = document.activeElement; document.activeElement.setSelectionRange(2, 7);
      state.saasLoading = busy;
      state.saasListingAiGenerationStatus = busy ? "running" : "idle";
    }, otherBusy);
    pending[0].reply(status); await page.evaluate(() => window.__savePromises[0]);
    const result = await page.evaluate(() => ({
      status: state.saasListingProductFactSaveStatus,
      factControlDisabled: [...document.querySelectorAll('.saas-product-facts-module [data-saas-product-fact-field], .saas-product-facts-module [data-saas-action="mark-product-fact-unknown"], .saas-product-facts-module [data-saas-action="confirm-product-fact-suggestion"]')].some(control => control.disabled),
      generateDisabled: document.querySelector('[data-saas-action="listing-generate-ai-draft"]').disabled,
      generateText: document.querySelector('[data-saas-action="listing-generate-ai-draft"]').textContent,
      saveDisabled: document.querySelector('[data-saas-action="save-merchant-product-facts"]').disabled,
      saveText: document.querySelector('[data-saas-action="save-merchant-product-facts"]').textContent,
      title: document.querySelector('[data-saas-listing-draft-field="title"]').value,
      sameFocusedNode: document.activeElement === window.__typedCopyNode && window.__typedCopyNode.isConnected,
      selection: [document.activeElement.selectionStart, document.activeElement.selectionEnd],
    }));
    assert.deepEqual(result, { status: status === 201 ? "saved" : "local_only", factControlDisabled: false,
      generateDisabled: otherBusy, generateText: otherBusy ? "AI 正在生成…" : "AI 生成 Listing 草稿",
      saveDisabled: otherBusy, saveText: "保存已确认资料", title: "Copy typed during save",
      sameFocusedNode: true, selection: [2, 7] });
    assert.deepEqual(await page.evaluate(() => window.__factValuesAndOrigins()), factFieldsBefore);
    assert.equal(pending.length, 1, "settling the save must not send another request");
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
  "renderSaasListingGapAndRiskPanel",
  "markSaasMerchantProductFactUnknown",
  "saasMerchantProductFactLabel",
  "saasListingItemSpecificsWithMerchantFacts",
  "saasMerchantProductFactProjectedValue",
  "applySaasMerchantProductFactPacketToDraft",
  "saasCanonicalJsonValue",
  "invalidateSaasListingValidationForFactChange",
  "sanitizeSaasCeoCommandSourceText",
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
  "saasListingDraftHeading",
  "syncSaasListingDraftHeading",
  "setSaasListingDraftField",
  "captureSaasListingDraftEditor",
  "saasListingCurrentDraftFieldsForAi",
  "sanitizeSaasListingComposerDraftSnapshot",
  "saasSha256Hex",
  "readSaasProtectedStateSnapshotFromStorage",
  "saasListingCloudSameIdentity",
  "saasListingWizardGenerationPending",
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
// These legacy fact forms have no wizard instance. Keep the real pending
// predicate above so pending generation still prevents a premature unlock.
const generationContextHelpers = "const saasListingWizardRecord = () => null;\n" + source.slice(
  source.indexOf("let saasListingAiGenerationEpoch ="),
  source.indexOf("async function generateSaasListingDraftFromCurrentProject("),
);

async function withProductFactPage(run) {
  const browser = await chromium.launch({ channel: browserChannel, headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
    const pageErrors = [];
    page.on("pageerror", (error) => pageErrors.push(String(error?.stack || error)));
    await page.route("http://127.0.0.1/product-fact-test", (route) => route.fulfill({ contentType: "text/html", body: '<main id="product-fact-test-root"></main><section id="listing-draft-test-root"></section>' }));
    await page.goto("http://127.0.0.1/product-fact-test");
    await page.addScriptTag({
      content: `
        const SAAS_MERCHANT_PRODUCT_FACT_PACKET_CONTRACT = "merchant_product_fact_packet_v1";
        let saasStateRefreshGeneration = 0;
        const state = {
          saasLoading: false,
          saasConnected: false,
          saasTasks: [],
          saasReports: [],
          saasCompany: { company_id: "fact-test-company" },
          saasUser: { user_id: "fact-test-user" },
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
        const saasProtectedSnapshotStorageKeys = () => ["product-fact-test-snapshot"];
        const saveSaasProtectedStateSnapshot = () => {
          window.__savedFactPacket = sanitizeSaasMerchantProductFactPacketSnapshot(state.saasListingComposerDraft?.merchant_product_fact_packet);
          localStorage.setItem("product-fact-test-snapshot", JSON.stringify({ listing_composer_draft: sanitizeSaasListingComposerDraftSnapshot(state.saasListingComposerDraft) }));
          return true;
        };
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

test("mixed provenance labels each unconfirmed suggestion by its own evidence", async () => {
  await withProductFactPage(async (page) => {
    await page.evaluate(() => {
      const packet = state.saasListingComposerDraft.merchant_product_fact_packet;
      packet.source = "backend_product_vision_extraction";
      packet.vision_contract_version = "jiejing_ai_ceo_product_vision_intake_v1";
      packet.field_evidence = {
        material: { source_type: "merchant_message_model_proposal" },
        package_weight_g: { source_type: "ai_extracted_from_merchant_image" },
      };
      document.querySelector("#product-fact-test-root").innerHTML =
        renderSaasMerchantProductFactsModule(state.saasListingComposerDraft);
    });
    assert.equal(await page.locator('[data-product-fact-key="material"] [data-product-fact-origin]').textContent(), "AI 建议 · 待确认");
    assert.equal(await page.locator('[data-product-fact-key="package_weight_g"] [data-product-fact-origin]').textContent(), "图片识别 · 待确认");
    const collected = await page.evaluate(() => collectSaasMerchantProductFacts());
    assert.equal(collected.merchantConfirmed.material, undefined);
    assert.equal(collected.merchantConfirmed.package_weight_g, undefined);
    assert.ok(collected.unknownFacts.includes("material"));
    assert.ok(collected.unknownFacts.includes("package_weight_g"));
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
        throw Object.assign(new Error("provider unavailable"), { status: 502, payload: { status: "failed", report_save_attempted: false,
          report: null, task_id: "fact-generation-failed", failure_code: "listing_model_generation_failed", model_called: false,
          usage_consumed: false, model_usage: { request_count: 0 }, real_platform_writes_enabled: false, secret_exposed: false } });
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

async function installPendingFactEditor(page) {
  // Exercise the real overlay and identity functions inside the existing DOM fixture.
  // Only the surrounding page/store/HTTP boundary remains synthetic.
  const functions = ["saasProductFactEditorScope", "saasProductFactEditorFields",
    "captureSaasPendingProductFactEditor", "restoreSaasPendingProductFactEditor",
    "saasLatestObservedListingProductFactReport", "saasListingCloudContext",
    "saasListingCloudReportMatchesContext", "saasTimestampMillis",
    "clearSaasPendingProductFactEditor",
    "captureSaasListingEditorFocus", "restoreSaasListingEditorFocus",
    "renderProductListingCenter", "saveSaasMerchantProductFacts", "persistSaasMerchantProductFacts",
    "saasListingAiGenerationContextKey", "saasCurrentListingProjectIdentity",
    "saasNormalizeListingProjectIdentity", "saasIsConcreteProductLabel",
    "saasIsInvalidMarketProductLabel", "hashString"].map(extractFunction).join("\n");
  await page.addScriptTag({ content: `(() => {
    const activeListingDraft = () => null;
    const isSaasPublicMvpMode = () => true;
    const isLegacySampleMediaDraftKey = () => false;
    ${functions}
    const root = document.querySelector('#product-fact-test-root');
    const view = document.createElement('section');
    view.id = 'view-product';
    root.replaceWith(view); view.append(root);
    const renderSaasProductListingCenter = () => {
      root.innerHTML = renderSaasMerchantProductFactsModule(state.saasListingComposerDraft);
    };
    // Bind the original click listener to real saves whose lexical renderer is
    // the real public wrapper, not the old fixture-wide const renderer.
    window.saveSaasMerchantProductFacts = saveSaasMerchantProductFacts;
    window.persistSaasMerchantProductFacts = persistSaasMerchantProductFacts;
    window.captureSaasPendingProductFactEditor = captureSaasPendingProductFactEditor;
    window.clearSaasPendingProductFactEditor = clearSaasPendingProductFactEditor;
    state.saasCompany = { company_id: 'company-A' };
    state.saasUser = { user_id: 'user-A' };
    window.__productFactStore = { store_id: 'store-A' };
    state.saasListingComposerDraft.listing_project_identity = {
      key: 'project-A', source_report_id: 'source-A', candidate_id: 'candidate-A' };
    state.saasListingComposerDraft.source_product_fact_report_id = 'base-A';
    window.__pendingFactEditor = {
      scope: saasProductFactEditorScope,
      fields: () => saasProductFactEditorFields(view),
      capture: () => captureSaasPendingProductFactEditor(view),
      restore: (pending) => restoreSaasPendingProductFactEditor(view, pending),
      render: renderProductListingCenter,
    };
    restoreSaasPendingProductFactEditor(view, null);
  })();` });
}

test("pending fact editor keeps only same-context DOM differences across repeated redraws", async () => {
  await withProductFactPage(async (page) => {
    await installPendingFactEditor(page);
    const material = page.locator('[data-saas-product-fact-field="material"]');
    await material.fill("Steel merchant edit");
    const result = await page.evaluate(() => {
      const field = document.querySelector('[data-saas-product-fact-field="material"]');
      field.setSelectionRange(2, 7);
      const editor = window.__pendingFactEditor;
      const before = editor.fields().find((item) => item.key === 'material');
      const packet = state.saasListingComposerDraft.merchant_product_fact_packet;
      packet.source_confirmed_facts.brand = 'New source brand';
      const packetBefore = JSON.stringify(packet);
      let writes = 0;
      window.__productFactFetch = async () => { writes++; return {}; };
      const edited = editor.capture().fields.map((item) => item.key);
      editor.render(); editor.render();
      const active = document.activeElement;
      return { before, after: editor.fields().find((item) => item.key === 'material'), edited,
        brand: document.querySelector('[data-saas-product-fact-field="brand"]').value,
        focus: active.dataset.saasProductFactField, selection: [active.selectionStart, active.selectionEnd],
        packetUnchanged: JSON.stringify(packet) === packetBefore, writes,
        baselineValue: document.querySelector('#view-product').saasProductFactEditorBaseline.fields.find((item) => item.key === 'material').value };
    });
    assert.deepEqual(result.after, result.before);
    assert.deepEqual(result.edited, ["material"]);
    assert.equal(result.brand, "New source brand", "untouched fields must take the fresh render, not the old DOM");
    assert.equal(result.focus, "material");
    assert.deepEqual(result.selection, [2, 7]);
    assert.equal(result.baselineValue, "Aluminum Alloy", "a restored edit must not become the saved baseline");
    assert.equal(result.packetUnchanged, true);
    assert.equal(result.writes, 0);
  });
});

test("pending fact editor preserves empty unknown checkbox and provenance without upgrading facts", async () => {
  await withProductFactPage(async (page) => {
    await installPendingFactEditor(page);
    await page.evaluate(() => {
      state.saasListingComposerDraft.merchant_product_fact_packet.source_confirmed_facts.brand = 'Source Brand';
      window.__pendingFactEditor.render();
    });
    await page.locator('[data-saas-product-fact-field="material"]').fill("");
    await page.locator('[data-saas-product-fact-field="merchant_owned_product_confirmed"]').check();
    await page.locator('[data-product-fact-key="package_weight_g"] [data-saas-action="confirm-product-fact-suggestion"]').click();
    const result = await page.evaluate(() => {
      const editor = window.__pendingFactEditor;
      const before = editor.fields();
      const packet = JSON.stringify(state.saasListingComposerDraft.merchant_product_fact_packet);
      editor.render(); editor.render();
      return { before, after: editor.fields(), packetUnchanged: packet === JSON.stringify(state.saasListingComposerDraft.merchant_product_fact_packet) };
    });
    assert.deepEqual(result.after, result.before, "all values and source/confirmation labels must remain exact");
    const fields = Object.fromEntries(result.after.map((field) => [field.key, field]));
    assert.equal(fields.material.value, "");
    assert.equal(fields.material.unknown, "true");
    assert.equal(fields.material.confirmed, "false");
    assert.equal(fields.merchant_owned_product_confirmed.value, true);
    assert.equal(fields.package_weight_g.confirmationDisabled, true);
    assert.equal(fields.package_weight_g.confirmationText, "已确认");
    assert.notEqual(fields.brand.origin, "merchant_confirmed");
    assert.notEqual(fields.condition.confirmed, "true");
    assert.equal(result.packetUnchanged, true);
    await page.locator('[data-saas-product-fact-field="merchant_owned_product_confirmed"]').uncheck();
    await page.evaluate(() => window.__pendingFactEditor.render());
    assert.equal(await page.locator('[data-saas-product-fact-field="merchant_owned_product_confirmed"]').isChecked(), false);
  });
});

test("pending fact editor isolates identity changes but anchors cross-base edits to their observed version", async () => {
  await withProductFactPage(async (page) => {
    await installPendingFactEditor(page);
    const original = await page.evaluate(() => JSON.parse(JSON.stringify(state.saasListingComposerDraft)));
    for (const changed of ["company", "user", "store", "key", "source", "candidate", "epoch", "empty_source", "empty_candidate", "no_draft", "no_identity"]) {
      await page.evaluate((draft) => {
        state.saasCompany = { company_id: 'company-A' }; state.saasUser = { user_id: 'user-A' };
        window.__productFactStore = { store_id: 'store-A' }; saasListingAiGenerationEpoch = 10;
        state.saasListingComposerDraft = draft;
        renderProductListingCenter(); window.__pendingFactEditor.restore(null);
      }, original);
      await page.locator('[data-saas-product-fact-field="material"]').fill("Never leak this edit");
      const result = await page.evaluate((changed) => {
        const editor = window.__pendingFactEditor, pending = editor.capture();
        const draft = state.saasListingComposerDraft;
        if (changed === 'company') state.saasCompany.company_id = 'company-B';
        if (changed === 'user') state.saasUser.user_id = 'user-B';
        if (changed === 'store') window.__productFactStore.store_id = 'store-B';
        if (changed === 'key') draft.listing_project_identity.key = 'project-B';
        if (changed === 'source') draft.listing_project_identity.source_report_id = 'source-B';
        if (changed === 'candidate') draft.listing_project_identity.candidate_id = 'candidate-B';
        if (changed === 'epoch') saasListingAiGenerationEpoch++;
        if (changed === 'empty_source') draft.listing_project_identity.source_report_id = '';
        if (changed === 'empty_candidate') draft.listing_project_identity.candidate_id = '';
        if (changed === 'no_draft') state.saasListingComposerDraft = null;
        if (changed === 'no_identity') state.saasListingComposerDraft = {};
        const capturedAfterChange = editor.capture();
        document.querySelector('#product-fact-test-root').innerHTML = renderSaasMerchantProductFactsModule(draft);
        editor.restore(pending);
        return { capturedAfterChange, value: document.querySelector('[data-saas-product-fact-field="material"]').value };
      }, changed);
      assert.equal(result.capturedAfterChange, null, `${changed} must reject the previous DOM baseline`);
      assert.equal(result.value, "Aluminum Alloy", `${changed} must not receive another scope's pending edit`);
    }
    for (const [oldBase, newBase, input] of [["base-A", "base-B", "Unsaved Steel"], ["base-A", "", ""], ["", "base-B", "Unsaved Resin"]]) {
      const caseLabel = oldBase === "" ? "empty_to_version" : newBase === "" ? "version_to_empty" : "version_to_version";
      await page.evaluate(({ draft, oldBase }) => {
        state.saasCompany = { company_id: 'company-A' }; state.saasUser = { user_id: 'user-A' };
        window.__productFactStore = { store_id: 'store-A' }; saasListingAiGenerationEpoch = 10;
        state.saasListingComposerDraft = draft;
        draft.source_product_fact_report_id = oldBase;
        state.saasConnected = true; state.saasReports = []; state.saasProductFactSaveAttempt = null;
        renderProductListingCenter(); window.__pendingFactEditor.restore(null);
        window.__crossBaseWrites = [];
        window.__crossBaseSignatures = [];
        window.__productFactFetch = async (_path, options) => {
          window.__crossBaseWrites.push(JSON.parse(options.body));
          window.__crossBaseSignatures.push({ epoch: saasListingAiGenerationEpoch,
            signature: state.saasProductFactSaveAttempt.signature });
          const error = new Error('synthetic version conflict'); error.status = 409; throw error;
        };
      }, { draft: original, oldBase });
      await page.locator('[data-saas-product-fact-field="material"]').fill(input);
      const refreshed = await page.evaluate((newBase) => {
        const packet = JSON.stringify(state.saasListingComposerDraft.merchant_product_fact_packet);
        state.saasListingComposerDraft.source_product_fact_report_id = newBase;
        window.__pendingFactEditor.render(); window.__pendingFactEditor.render();
        return { pending: window.__pendingFactEditor.capture(), writes: window.__crossBaseWrites.length,
          packetUnchanged: packet === JSON.stringify(state.saasListingComposerDraft.merchant_product_fact_packet) };
      }, newBase);
      assert.equal(await page.locator('[data-saas-product-fact-field="material"]').inputValue(), input);
      assert.equal(refreshed.pending.expectedFactReportId, oldBase);
      assert.equal(refreshed.pending.hasVersionConflict, true);
      assert.equal(refreshed.packetUnchanged, true);
      assert.equal(refreshed.writes, 0, "a newer cloud base must not automatically save local edits");
      assert.equal(await page.locator('[data-saas-product-fact-version-warning]').count(), 1);
      await page.locator('[data-saas-action="save-merchant-product-facts"]').click();
      await page.evaluate(() => window.__productFactSavePromise);
      const afterConflict = await page.evaluate(() => {
        window.__pendingFactEditor.render(); window.__pendingFactEditor.render();
        const packet = state.saasListingComposerDraft.merchant_product_fact_packet;
        return { pending: window.__pendingFactEditor.capture(), writes: window.__crossBaseWrites.length,
          value: document.querySelector('[data-saas-product-fact-field="material"]').value,
          merchantMaterial: packet.merchant_confirmed_facts.material ?? null,
          materialUnknown: packet.unknown_facts.includes('material') };
      });
      assert.equal(afterConflict.value, input, `${caseLabel}: local packet projection must keep the actual input`);
      assert.equal(afterConflict.merchantMaterial, input || null, `${caseLabel}: local packet must contain C or an explicit unknown`);
      assert.equal(afterConflict.materialUnknown, input === "");
      assert.equal(afterConflict.pending.expectedFactReportId, oldBase, "local packet projection must not upgrade the sticky CAS anchor");
      assert.equal(afterConflict.pending.hasVersionConflict, true);
      assert.equal(afterConflict.writes, 1, "409 must not automatically retry");
      assert.equal(await page.locator('[data-saas-product-fact-version-warning]').count(), 1);
      await page.locator('[data-saas-action="save-merchant-product-facts"]').click();
      await page.evaluate(() => window.__productFactSavePromise);
      const sameContentRetry = await page.evaluate(() => {
        const packets = window.__crossBaseWrites.map((body) => {
          const packet = { ...body.merchant_product_fact_packet }; delete packet.saved_at; return packet;
        });
        return { count: window.__crossBaseWrites.length,
          canonicalEqual: JSON.stringify(saasCanonicalJsonValue(packets[0])) === JSON.stringify(saasCanonicalJsonValue(packets[1])),
          attempts: window.__crossBaseWrites.map((body) => body.save_context) };
      });
      assert.equal(sameContentRetry.count, 2, `${caseLabel}: only the explicit retry adds a POST`);
      assert.equal(sameContentRetry.canonicalEqual, true, `${caseLabel}: verify identical complete content before checking action reuse`);
      assert.equal(sameContentRetry.attempts[0].mutation_id, sameContentRetry.attempts[1].mutation_id,
        `${caseLabel}: an explicit unchanged-content retry must reuse its action`);
      assert.deepEqual(sameContentRetry.attempts.map((attempt) => attempt.expected_fact_report_id), [oldBase, oldBase]);
      const refreshedAgain = await page.evaluate((packet) => {
        // An independently refreshed server packet B must not erase the still-unsaved C overlay.
        state.saasListingComposerDraft.merchant_product_fact_packet = packet;
        const packetBefore = JSON.stringify(packet);
        window.__pendingFactEditor.render(); window.__pendingFactEditor.render();
        return { pending: window.__pendingFactEditor.capture(), writes: window.__crossBaseWrites.length,
          packetUnchanged: packetBefore === JSON.stringify(state.saasListingComposerDraft.merchant_product_fact_packet) };
      }, original.merchant_product_fact_packet);
      assert.equal(await page.locator('[data-saas-product-fact-field="material"]').inputValue(), input, "C must survive local packet C then server packet B redraws");
      assert.equal(refreshedAgain.pending.expectedFactReportId, oldBase);
      assert.equal(refreshedAgain.pending.hasVersionConflict, true);
      assert.equal(refreshedAgain.writes, 2, `${caseLabel}: rendering server data must not automatically POST`);
      assert.equal(refreshedAgain.packetUnchanged, true);
      assert.equal(await page.locator('[data-saas-product-fact-version-warning]').count(), 1);
      if (oldBase === "base-A" && newBase === "base-B") {
        const whileHidden = await page.evaluate(() => {
          const editor = window.__pendingFactEditor;
          const pending = editor.capture();
          document.querySelector('#product-fact-test-root').innerHTML = '';
          editor.restore(pending);
          return editor.capture();
        });
        assert.ok(whileHidden, "temporarily absent fact controls must retain the pending editor snapshot");
        assert.equal(whileHidden.expectedFactReportId, oldBase, "hiding controls must not advance the CAS anchor");
        await page.evaluate(() => window.__pendingFactEditor.render());
        assert.equal(await page.locator('[data-saas-product-fact-field="material"]').inputValue(), input, "reopening the fact module must restore the unsaved C value");
        assert.equal(await page.evaluate(() => window.__pendingFactEditor.capture().expectedFactReportId), oldBase);
        assert.equal(await page.locator('[data-saas-product-fact-version-warning]').count(), 1);
      }
      await page.locator('[data-saas-action="save-merchant-product-facts"]').click();
      await page.evaluate(() => window.__productFactSavePromise);
      const { attempts, diagnostics } = await page.evaluate(({ caseLabel, input, originalMaterial }) => {
        const packets = window.__crossBaseWrites.slice(-2).map((body) => {
          const packet = { ...body.merchant_product_fact_packet }; delete packet.saved_at; return packet;
        });
        const canonical = (value) => JSON.stringify(saasCanonicalJsonValue(value));
        const changedPaths = (left, right, prefix = '') => {
          if (canonical(left) === canonical(right)) return [];
          if (!left || !right || typeof left !== 'object' || typeof right !== 'object' || Array.isArray(left) || Array.isArray(right)) return [prefix];
          return [...new Set([...Object.keys(left), ...Object.keys(right)])].sort().flatMap((key) =>
            changedPaths(left[key], right[key], [prefix, /^[a-z_]{1,80}$/.test(key) ? key : '[field]'].filter(Boolean).join('.')));
        };
        const observed = window.__crossBaseSignatures.slice(-2);
        const signatures = observed.map((item) => JSON.parse(item.signature));
        return { attempts: window.__crossBaseWrites.map((body) => body.save_context), diagnostics: {
          case: caseLabel,
          sanitized_packet_equal_excluding_saved_at: canonical(packets[0]) === canonical(packets[1]),
          changed_packet_paths: changedPaths(packets[0], packets[1]).slice(0, 20),
          derived_material: packets.map((packet) => ({
            present: Object.prototype.hasOwnProperty.call(packet.derived_listing_suggestions, 'material'),
            matches_original: packet.derived_listing_suggestions.material === originalMaterial,
            matches_input: packet.derived_listing_suggestions.material === input,
            empty: packet.derived_listing_suggestions.material === '',
          })),
          authority_fields_equal: Object.fromEntries(['source', 'source_mode', 'vision_contract_version', 'simulation_only',
            'fact_scope', 'buyer_copy_requires_validated_listing_generation', 'source_confirmed_facts', 'merchant_confirmed_facts']
            .map((key) => [key, canonical(packets[0][key]) === canonical(packets[1][key])])),
          epoch_equal: observed[0].epoch === observed[1].epoch,
          context_equal: signatures[0][0] === signatures[1][0], expected_equal: signatures[0][1] === signatures[1][1],
          signature_equal: observed[0].signature === observed[1].signature,
          signature_content_matches_request: signatures.map((signature, index) => canonical(signature[2]) === canonical(packets[index])),
        } };
      }, { caseLabel, input, originalMaterial: original.merchant_product_fact_packet.derived_listing_suggestions.material });
      assert.deepEqual(attempts.map((attempt) => attempt.expected_fact_report_id), [oldBase, oldBase, oldBase]);
      assert.equal(attempts[1].mutation_id === attempts[2].mutation_id, diagnostics.sanitized_packet_equal_excluding_saved_at,
        `${caseLabel}: action identity must follow actual payload equality; ${JSON.stringify(diagnostics)}`);
      assert.equal(await page.locator('[data-saas-product-fact-field="material"]').inputValue(), input);
    }
  });
});

test("pending fact editor cannot overlay an old edit after a successful save advances its base", async () => {
  await withProductFactPage(async (page) => {
    await installPendingFactEditor(page);
    await page.locator('[data-saas-product-fact-field="material"]').fill("Old pending Steel");
    await page.evaluate(() => {
      window.__staleFactOverlay = window.__pendingFactEditor.capture();
      state.saasConnected = true;
      window.__factEditorWrites = 0;
      window.__productFactFetch = async (_path, options) => {
        window.__factEditorWrites++;
        const body = JSON.parse(options.body);
        return { merchant_product_fact_packet: body.merchant_product_fact_packet,
          listing_project_identity: body.listing_project_identity, report: { report_id: 'base-B' }, is_current: true };
      };
    });
    await page.locator('[data-saas-product-fact-field="material"]').fill("New saved Resin");
    await page.locator('[data-saas-action="save-merchant-product-facts"]').click();
    await page.evaluate(() => window.__productFactSavePromise);
    const result = await page.evaluate(() => {
      const packet = JSON.stringify(state.saasListingComposerDraft.merchant_product_fact_packet);
      const view = document.querySelector('#view-product');
      const baseline = view.saasProductFactEditorBaseline;
      const cleared = !baseline?.pendingEditor && !(baseline?.pendingFieldKeys || []).length;
      const generationAdvanced = view.saasProductFactEditorGeneration > window.__staleFactOverlay.generation;
      window.__pendingFactEditor.restore(window.__staleFactOverlay);
      return { value: document.querySelector('[data-saas-product-fact-field="material"]').value,
        base: state.saasListingComposerDraft.source_product_fact_report_id, writes: window.__factEditorWrites,
        cleared, generationAdvanced, baselineReport: baseline?.baseReportId,
        packetUnchanged: packet === JSON.stringify(state.saasListingComposerDraft.merchant_product_fact_packet) };
    });
    assert.equal(result.value, "New saved Resin");
    assert.equal(result.base, "base-B");
    assert.equal(result.writes, 1, "restoring the editor must never automatically POST");
    assert.equal(result.cleared, true, "a current successful server receipt clears old pending edits, not the new baseline");
    assert.equal(result.baselineReport, "base-B");
    assert.equal(result.generationAdvanced, true, "clearing must reject already captured old overlays");
    assert.equal(result.packetUnchanged, true);
  });
});

test("pending fact editor retains same-base HTTP failures across a later server refresh", async () => {
  for (const input of ["Unsaved same-base Steel", ""]) {
    await withProductFactPage(async (page) => {
      await seedValidatedAluminumListing(page);
      await installPendingFactEditor(page);
      assert.equal(await page.locator('[data-product-fact-key="material"] [data-saas-action="confirm-product-fact-suggestion"]').count(), 0);
      await page.evaluate(() => {
        window.__sameBaseServerPacket = JSON.parse(JSON.stringify(state.saasListingComposerDraft.merchant_product_fact_packet));
        state.saasConnected = true;
        window.__sameBaseWrites = [];
        window.__productFactFetch = async (_path, options) => {
          window.__sameBaseWrites.push(JSON.parse(options.body));
          const error = new Error('synthetic temporary failure'); error.status = 500; throw error;
        };
      });
      await page.locator('[data-saas-product-fact-field="material"]').fill(input);
      await page.locator('[data-saas-action="save-merchant-product-facts"]').click();
      await page.evaluate(() => window.__productFactSavePromise);
      const projected = await page.evaluate(() => {
        window.__pendingFactEditor.render(); window.__pendingFactEditor.render();
        const packet = state.saasListingComposerDraft.merchant_product_fact_packet;
        return { value: document.querySelector('[data-saas-product-fact-field="material"]').value,
          merchantMaterial: packet.merchant_confirmed_facts.material ?? null,
          materialUnknown: packet.unknown_facts.includes('material'),
          expected: window.__sameBaseWrites[0].save_context.expected_fact_report_id };
      });
      assert.equal(projected.value, input, "500 must keep the local C projection");
      assert.equal(projected.merchantMaterial, input || null);
      assert.equal(projected.materialUnknown, input === "");
      assert.equal(projected.expected, "base-A");
      const refreshed = await page.evaluate(() => {
        state.saasListingComposerDraft.merchant_product_fact_packet = window.__sameBaseServerPacket;
        window.__pendingFactEditor.render(); window.__pendingFactEditor.render();
        const field = document.querySelector('[data-saas-product-fact-field="material"]');
        return { value: field.value, unknown: field.dataset.productFactUnknown === 'true',
          expected: window.__pendingFactEditor.capture()?.expectedFactReportId,
          writes: window.__sameBaseWrites.length, base: state.saasListingComposerDraft.source_product_fact_report_id };
      });
      assert.equal(refreshed.value, input, "same-base server A must not erase the unsaved C after HTTP 500");
      assert.equal(refreshed.unknown, input === "");
      assert.equal(refreshed.expected, "base-A");
      assert.equal(refreshed.base, "base-A");
      assert.equal(refreshed.writes, 1, "neither failure nor server refresh may automatically POST");
    });
  }
});
test("fact footer and save feedback retain every pending or missing label at summary boundaries", async () => {
  await withProductFactPage(async (page) => {
    const facts = [
      ["sku", "SKU"],
      ["material", "材质"],
      ["package_weight_g", "包装重量 g"],
      ["package_length_cm", "包装长 cm"],
      ["package_width_cm", "包装宽 cm"],
      ["package_height_cm", "包装高 cm"],
    ];
    for (const kind of ["missing", "pending"]) {
      for (const count of [0, 4, 5, 6]) {
        const selected = facts.slice(0, count);
        await page.evaluate(({ kind, selected }) => {
          const definitions = saasMerchantProductFactDefinitions().flatMap((group) => group.fields);
          const merchant = { source_url: "https://example.invalid/owned-fixture" };
          for (const key of saasMerchantProductFactRequiredKeys()) {
            const type = definitions.find(([field]) => field === key)[3];
            merchant[key] = type === "checkbox" ? true : type === "number" ? "1"
              : key === "image_urls" ? "https://example.invalid/owned-fixture.jpg" : `Confirmed ${key}`;
          }
          const derived = {};
          for (const [key] of selected) {
            if (kind === "pending") derived[key] = merchant[key];
            delete merchant[key];
          }
          state.saasListingComposerDraft = {
            product: "Summary Boundary Fixture", title: "Summary Boundary Fixture",
            fields: {}, publish_prefill: {},
            merchant_product_fact_packet: {
              contract_version: "merchant_product_fact_packet_v1", simulation_only: true,
              merchant_confirmed_facts: merchant, source_confirmed_facts: {},
              derived_listing_suggestions: derived, unknown_facts: selected.map(([key]) => key),
            },
          };
          window.__productFactToasts = [];
          renderProductListingCenter();
        }, { kind, selected });
        const footer = await page.locator(".saas-product-facts-footer strong").innerText();
        const labels = selected.map(([, label]) => label).join("、");
        assert.equal(footer, count ? `${kind === "pending" ? "待确认" : "仍缺"}：${labels}`
          : "可以继续生成 Listing 文案和发布体检", `${kind} ${count}: footer must list every field`);
        const status = await page.locator(".saas-product-facts-module").innerText();
        if (count) assert.ok(status.includes(`${count} 项${kind === "pending" ? " AI 建议待确认" : "资料缺失"}`));
        await page.locator('[data-saas-action="save-merchant-product-facts"]').click();
        await page.evaluate(() => window.__productFactSavePromise);
        const message = await page.evaluate(() => window.__productFactToasts.at(-1));
        assert.equal(message, (count
          ? `商品资料已保存；${kind === "pending" ? "待确认" : "仍缺"} ${labels}，不会编造或真实发布。`
          : "商品资料已保存；可以继续审核 Listing，真实发布仍需确认中心。") + " 登录后会写入账号工作记录。",
        `${kind} ${count}: actual save feedback must list every field`);
      }
    }
  });
});

async function captureRiskPanelFixture(page, name, width) {
  const directory = process.env.JIEJING_RISK_FIXTURE_SCREENSHOT_DIR;
  if (!directory) return;
  assert.ok(path.isAbsolute(directory), "risk fixture screenshots require an explicit absolute output directory");
  await page.setViewportSize({ width, height: 900 });
  await page.route("**/*", (route) => route.abort());
  await page.addStyleTag({ content: fs.readFileSync(path.join(root, "styles.css"), "utf8") });
  await page.evaluate(() => {
    document.body.classList.add("saas-public-mvp");
    document.querySelector("#product-fact-test-root").hidden = true;
    Object.assign(document.querySelector("#listing-draft-test-root").style,
      { width: "100%", padding: "24px", boxSizing: "border-box" });
  });
  fs.mkdirSync(directory, { recursive: true });
  await page.getByRole("complementary", { name: "发布前缺口和风险" }).screenshot({ path: path.join(directory, name) });
}

test("advanced risk hints reflect current tablet facts without changing saved copy or historical reports", async () => {
  await withProductFactPage(async (page) => {
    const before = await page.evaluate(() => {
      const staleHints = {
        bullets: ["核心材质/规格待补", "物流、重量、尺寸待补", "价格、采购成本和费用待补", "主图、场景图和细节图待补"],
        gaps: ["sku", "item_location", "image_rights_confirmed", "售价、采购价或成本", "重量、尺寸、发货地或物流承诺"],
        risks: ["真实发布必须进入确认中心"],
      };
      const packet = {
        contract_version: "merchant_product_fact_packet_v1", source: "authenticated_merchant_request",
        source_mode: "merchant_owned_product", product_name: "Foldable Tablet Stand", simulation_only: true,
        source_confirmed_facts: {}, derived_listing_suggestions: {},
        merchant_confirmed_facts: {
          product_name: "Foldable Tablet Stand", merchant_owned_product_confirmed: true,
          condition: "NEW", brand: "Unbranded", mpn: "Does Not Apply", material: "Aluminum Alloy",
          product_dimensions_cm: "15 x 12 x 8", net_weight_g: "220",
          package_weight_g: "320", package_length_cm: "20", package_width_cm: "15", package_height_cm: "5",
          unit_cost: "3.5", selling_price: "16.99", currency: "USD", quantity: "2",
          image_urls: "https://example.invalid/tablet-fixture.jpg",
        },
        unknown_facts: ["sku", "item_location", "image_rights_confirmed"],
      };
      state.saasReports = [{ report_id: "fixture-original-research", report_type: "ai_ceo.market_research",
        report: { listing_handoff: { publish_preflight_gaps: structuredClone(staleHints.gaps) } } }];
      state.saasListingComposerDraft = applySaasMerchantProductFactPacketToDraft({
        product: "Foldable Tablet Stand", title: "Foldable Tablet Stand", ...structuredClone(staleHints),
        source_report_id: "fixture-original-research", source_product_fact_report_id: "fixture-adopted-rewrite",
        fields: {
          title: "Foldable Portable Tablet Stand", selling_points: "Portable support for a tablet.",
          description: "A folding tablet stand for a desk.", item_specifics: "Material: Aluminum Alloy",
          category: "Tablet Stands", keywords: "tablet stand", price: "16.99", cost_price: "3.5",
          images: "", logistics: "",
        },
        publish_prefill: {},
      }, packet);
      window.__riskFixtureCheckpoint = { revision: 8, base_report_id: "fixture-adopted-rewrite",
        fields: Object.fromEntries(saasListingMerchantEditableFieldKeys().map((key) =>
          [key, String(state.saasListingComposerDraft.fields[key] || "")])) };
      window.__riskFixtureBusinessCalls = 0;
      window.__productFactFetch = async () => { window.__riskFixtureBusinessCalls += 1; throw new Error("risk rendering cannot call a business API"); };
      const snapshot = { draft: structuredClone(state.saasListingComposerDraft), reports: structuredClone(state.saasReports),
        checkpoint: structuredClone(window.__riskFixtureCheckpoint) };
      renderProductListingCenter();
      document.querySelector("#listing-draft-test-root").innerHTML =
        renderSaasListingGapAndRiskPanel(state.saasListingComposerDraft, {});
      return snapshot;
    });
    const panel = await page.getByRole("complementary", { name: "发布前缺口和风险" }).innerText();
    const after = await page.evaluate(() => ({ draft: state.saasListingComposerDraft, reports: state.saasReports,
      checkpoint: window.__riskFixtureCheckpoint }));
    assert.deepEqual(after, before, "rendering current hints must not rewrite R8 fields, fact provenance, or the original report");
    assert.equal(await page.evaluate(() => window.__riskFixtureBusinessCalls), 0);
    assert.doesNotMatch(panel, /核心材质\/规格待补|物流、重量、尺寸待补|价格、采购成本和费用待补|售价、采购价或成本|重量、尺寸、发货地或物流承诺/,
      "confirmed current material, dimensions, weights and prices must not inherit the original empty-draft hints");
    for (const label of ["SKU", "实际发货地", "图片商业使用权"]) assert.ok(panel.includes(label), `${label} remains an unresolved fact`);
    assert.doesNotMatch(panel, /\bsku\b|item_location|image_rights_confirmed/, "known fact keys must use their merchant-facing labels");
    assert.match(panel, /模拟/);
    assert.match(panel, /不可|不能|不允许/, "simulation must remain ineligible for eBay writing");
    assert.match(panel, /确认中心/);
    await captureRiskPanelFixture(page, "risk-current-facts-local-1280.png", 1280);
  });
});

test("advanced risk hints keep packaging and dispatch gaps separate from confirmed product measurements", async () => {
  await withProductFactPage(async (page) => {
    await page.evaluate(() => {
      const packet = {
        contract_version: "merchant_product_fact_packet_v1", simulation_only: true,
        source_confirmed_facts: { material: "Aluminum Alloy", product_dimensions_cm: "15 x 12 x 8",
          net_weight_g: "220", product_origin: "China" },
        merchant_confirmed_facts: {
          product_name: "Foldable Tablet Stand", merchant_owned_product_confirmed: true,
          sku: "LOCAL-TABLET-BOUNDARY", condition: "NEW", unit_cost: "3.5", selling_price: "16.99",
          currency: "USD", quantity: "2", image_urls: "https://example.invalid/tablet-fixture.jpg", image_rights_confirmed: true,
        },
        derived_listing_suggestions: {},
        unknown_facts: ["package_weight_g", "package_length_cm", "package_width_cm", "package_height_cm", "item_location"],
      };
      state.saasListingComposerDraft = applySaasMerchantProductFactPacketToDraft({
        product: "Foldable Tablet Stand", fields: {}, publish_prefill: {},
        bullets: ["已出现物流、尺寸或重量线索，可以继续做履约体检"], gaps: [],
        risks: ["真实发布必须进入确认中心"],
      }, packet);
      renderProductListingCenter();
      document.querySelector("#listing-draft-test-root").innerHTML = renderSaasListingGapAndRiskPanel(state.saasListingComposerDraft, {});
    });
    for (const [key, value] of [["product_dimensions_cm", "15 x 12 x 8"], ["net_weight_g", "220"], ["product_origin", "China"]]) {
      assert.equal(await page.locator(`[data-saas-product-fact-field="${key}"]`).inputValue(), value);
      assert.equal(await page.locator(`[data-product-fact-key="${key}"] [data-product-fact-origin]`).innerText(), "来源资料");
    }
    const panel = page.getByRole("complementary", { name: "发布前缺口和风险" });
    const gaps = panel.locator("article").filter({ has: page.getByText("资料缺口", { exact: true }) });
    const labels = ["包装重量 g", "包装长 cm", "包装宽 cm", "包装高 cm", "实际发货地"];
    const gapRows = await gaps.locator("li").allTextContents();
    assert.equal(gapRows.length, labels.length, "product measurements and origin cannot fill any of the five shipping gaps");
    for (const label of labels) assert.ok(gapRows.some((row) => row.includes(label)), `${label} remains visible`);
    assert.match(await gaps.locator("strong").innerText(), /5/);
    assert.doesNotMatch(gapRows.join("\n"), /商品尺寸|商品净重|商品产地|package_weight_g|package_length_cm|package_width_cm|package_height_cm|item_location/);
    const projection = await page.evaluate(() => state.saasListingComposerDraft.publish_prefill);
    for (const key of ["package_weight_g", "package_length_cm", "package_width_cm", "package_height_cm", "item_location"]) assert.equal(projection[key], "");
    assert.match(await panel.innerText(), /模拟/);
    await captureRiskPanelFixture(page, "risk-packaging-gaps-local-919.png", 919);
  });
});

test("advanced risk hints retain suggestion confirmation and unknown transitions without truncating long gaps", async () => {
  await withProductFactPage(async (page) => {
    await page.evaluate(() => document.addEventListener("click", (event) => {
      const button = event.target?.closest?.('[data-saas-action="mark-product-fact-unknown"]');
      if (button) markSaasMerchantProductFactUnknown(button);
    }));
    const renderGaps = async () => {
      await page.evaluate(() => {
        document.querySelector("#listing-draft-test-root").innerHTML = renderSaasListingGapAndRiskPanel(state.saasListingComposerDraft, {});
      });
      const gaps = page.getByRole("complementary", { name: "发布前缺口和风险" }).locator("article")
        .filter({ has: page.getByText("资料缺口", { exact: true }) });
      return { rows: await gaps.locator("li").allTextContents(), headline: await gaps.locator("strong").innerText() };
    };
    const remainingLabels = ["SKU", "包装重量 g", "包装长 cm", "包装宽 cm", "包装高 cm", "实际发货地", "图片商业使用权"];
    for (const origin of ["ai", "vision"]) {
      await page.evaluate((origin) => {
        const packet = {
          contract_version: "merchant_product_fact_packet_v1", simulation_only: true,
          source: origin === "vision" ? "backend_product_vision_extraction" : "authenticated_merchant_request",
          vision_contract_version: origin === "vision" ? "jiejing_ai_ceo_product_vision_intake_v1" : "",
          source_confirmed_facts: {},
          merchant_confirmed_facts: { product_name: "Foldable Tablet Stand", merchant_owned_product_confirmed: true,
            condition: "NEW", unit_cost: "3.5", currency: "USD", quantity: "2", image_urls: "https://example.invalid/tablet-fixture.jpg" },
          derived_listing_suggestions: { material: "Aluminum Alloy", selling_price: "16.99" },
          unknown_facts: ["material", "selling_price", "sku", "package_weight_g", "package_length_cm", "package_width_cm",
            "package_height_cm", "item_location", "image_rights_confirmed"],
        };
        state.saasListingComposerDraft = applySaasMerchantProductFactPacketToDraft({
          product: "Foldable Tablet Stand", fields: {}, publish_prefill: {}, gaps: [], bullets: [],
          risks: ["真实发布必须进入确认中心"],
        }, packet);
        renderProductListingCenter();
      }, origin);
      for (const key of ["material", "selling_price"]) {
        assert.equal(await page.locator(`[data-product-fact-key="${key}"] [data-product-fact-origin]`).innerText(),
          origin === "vision" ? "图片识别 · 待确认" : "AI 建议 · 待确认");
      }
      let gaps = await renderGaps();
      assert.equal(gaps.rows.length, 9, `${origin}: two suggestions plus seven missing facts must all remain visible`);
      assert.match(gaps.headline, /9/);
      for (const label of ["材质", "计划售价"]) assert.ok(gaps.rows.some((row) => row.includes("待确认") && row.includes(label)));
      for (const label of remainingLabels) assert.ok(gaps.rows.some((row) => row.includes(label)), `${origin}: ${label} is not truncated`);
      for (const key of ["material", "selling_price"]) await page.locator(`[data-product-fact-key="${key}"] [data-saas-action="confirm-product-fact-suggestion"]`).click();
      await page.locator('[data-saas-action="save-merchant-product-facts"]').click();
      await page.evaluate(() => window.__productFactSavePromise);
      gaps = await renderGaps();
      assert.equal(gaps.rows.length, 7, `${origin}: confirmation removes only those two pending facts`);
      assert.match(gaps.headline, /7/);
      assert.doesNotMatch(gaps.rows.join("\n"), /材质|计划售价/);
      for (const label of remainingLabels) assert.ok(gaps.rows.some((row) => row.includes(label)));
      for (const key of ["material", "selling_price"]) await page.locator(`[data-product-fact-key="${key}"] [data-saas-action="mark-product-fact-unknown"]`).click();
      await page.locator('[data-saas-action="save-merchant-product-facts"]').click();
      await page.evaluate(() => window.__productFactSavePromise);
      gaps = await renderGaps();
      assert.equal(gaps.rows.length, 9, `${origin}: explicitly unknown facts reappear without reviving old suggestions`);
      assert.match(gaps.headline, /9/);
      for (const label of ["材质", "计划售价"]) assert.ok(gaps.rows.some((row) => row.includes("待补") && row.includes(label)));
      assert.ok(gaps.rows.at(-1).includes("图片商业使用权"), `${origin}: the final missing fact must never be cut off at six`);
      const packet = await page.evaluate(() => state.saasListingComposerDraft.merchant_product_fact_packet);
      for (const key of ["material", "selling_price"]) {
        assert.equal(Boolean(packet.merchant_confirmed_facts[key]), false);
        assert.equal(Boolean(packet.derived_listing_suggestions[key]), false);
        assert.ok(packet.unknown_facts.includes(key));
      }
      assert.equal(packet.simulation_only, true);
      assert.equal(packet.source, origin === "vision" ? "backend_product_vision_extraction" : "authenticated_merchant_request");
      assert.equal(packet.vision_contract_version || "", origin === "vision" ? "jiejing_ai_ceo_product_vision_intake_v1" : "");
    }
  });
});

test("fact module copy requires an explicit AI generation action after saving", async () => {
  await withProductFactPage(async (page) => {
    const explanation = await page.locator(".saas-product-facts-head p").innerText();
    const generateLabel = await page.locator('[data-saas-action="listing-generate-ai-draft"]').innerText();
    assert.doesNotMatch(explanation, /保存后[^。]*会继续生成/, "saving must not promise automatic generation or preflight");
    assert.match(explanation, /保存只记录资料/);
    assert.ok(explanation.includes(`请点击“${generateLabel}”`), "the next action must name the actual separate generation button");
    assert.match(explanation, /再进行本地发布体检/);
  });
});

// The current four-step bridge uses the backend read-only check, covered by the
// full-app cloud checkpoint browser suite. These legacy advanced panels retain
// their original local guard and never bypass the server confirmation gate.
test("legacy advanced confirmation entrances retain draft guards and local preflight", async () => {
  await withProductFactPage(async (page) => {
    await page.addScriptTag({ content: [
      "saasListingMediaWritebackForDraft", "saasListingMediaWritebackImageUrls", "saasListingMediaWritebackRightsReady",
      "saasListingDraftPreflightSummary", "renderSaasListingPreflightBridgePanel",
      "renderSaasListingPublishFeedbackPanel",
      "saasPreTestPayloadText", "saasPreTestDuplicateSignal", "saasPreTestFormSummary", "saasPreTestCheckRows",
      "saasPublishHealthSummary", "saasAccountHealthSnapshot", "saasAccountHealthTone",
      "saasLatestExecutionResult", "saasExecutionResultForConfirmation", "saasLatestPublishConfirmation",
      "saasListingConfirmationsForCurrentProject", "saasListingPublishCheckContext",
      "saasLatestProductWorkflowTask", "saasReportsForDisplay", "latestSaasReportByTypes",
      "saasMerchantVisiblePublishCode", "saasListingPublishLoopSteps", "renderSaasListingPublishLoopTracker",
    ].map(extractFunction).join("\n\n") });
    for (const scenario of ["missing image", "missing title", "missing buyer copy", "missing packet", "ready", "loading"]) {
      await page.evaluate((scenario) => {
        const draft = {
          product: "Publish Button Fixture", title: "Publish Button Fixture",
          merchant_product_fact_packet: { simulation_only: true },
          fields: {
            title: "Publish Button Fixture", selling_points: "Synthetic owned product",
            description: "Synthetic fixture description", images: "https://example.invalid/owned-fixture.jpg",
          },
        };
        if (scenario === "missing image") draft.fields.images = "";
        if (scenario === "missing title") draft.fields.title = "";
        if (scenario === "missing buyer copy") draft.fields.selling_points = draft.fields.description = "";
        const ctx = { hasPacket: scenario !== "missing packet" };
        state.saasListingComposerDraft = draft;
        state.saasLoading = scenario === "loading";
        document.querySelector("#product-fact-test-root").innerHTML =
          renderSaasListingPreflightBridgePanel(draft, ctx, []) +
          renderSaasListingPublishFeedbackPanel(draft, ctx, []);
      }, scenario);
      const buttons = await page.locator('[data-saas-action="create-publish-confirmation"]').evaluateAll(
        (elements) => elements.map((element) => ({ text: element.textContent.trim(), disabled: element.disabled })),
      );
      assert.deepEqual(buttons.map((button) => button.text), ["生成确认单", "生成确认单并体检"]);
      const expectedDisabled = scenario !== "ready";
      assert.equal(buttons[0].disabled, expectedDisabled, `${scenario}: ordinary entrance is the existing reference`);
      for (const button of buttons) {
        assert.equal(button.disabled, expectedDisabled, `${scenario}: ${button.text} must share the ordinary entrance guard`);
      }
      const localPreflight = await page.locator('[data-saas-action="run-pretest-check"]').evaluateAll(
        (elements) => elements.map((element) => element.disabled),
      );
      assert.deepEqual(localPreflight, [false, false], `${scenario}: local preflight must remain available`);
    }
  });
});
