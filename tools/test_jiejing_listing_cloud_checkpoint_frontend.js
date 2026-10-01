#!/usr/bin/env node
"use strict";

// Actual app, DOM input events and HTTP checkpoint contract. The only server is
// an owned loopback fixture; model, account and platform APIs do not exist here.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const http = require("node:http");
const os = require("node:os");
const path = require("node:path");
const { test, before, after } = require("node:test");
const { chromium } = require("../output/codex-playwright-deps/node_modules/playwright-core");

const root = path.resolve(__dirname, "..");
const companyId = "checkpoint-company", userId = "checkpoint-user", storeId = "checkpoint-store";
const identity = { key: "checkpoint-tablet-project", source_report_id: "checkpoint-origin", candidate_id: "tablet-candidate" };
const checkpointPath = `/stores/${storeId}/listing-drafts/${identity.key}/checkpoint`;
const fieldKeys = ["title", "selling_points", "description", "category", "item_specifics", "keywords", "price", "images", "logistics", "risk_notes"];
const visibleKeys = fieldKeys.filter((key) => !["keywords", "risk_notes"].includes(key));
const originalFields = Object.fromEntries(fieldKeys.map((key) => [key, `Original ${key}`]));
const baseReport = {
  report_id: "checkpoint-listing-base", task_id: "checkpoint-listing-task", report_type: "listing.package",
  company_id: companyId, store_id: storeId, runtime_run_id: "listing_draft_generation", status: "saved",
  created_at: "2026-09-06T01:00:00Z",
  report: {
    contract_version: "listing_ai_draft_generation_v1", product: "Foldable Tablet Stand",
    listing_project_identity: identity,
    listing_handoff: { ready_for_listing_draft: true, source_mode: "project_scoped_live_model",
      target_report_type: "listing.package", listing_fields: { ...originalFields, description_seed: originalFields.description } },
  },
};
const otherIdentity = { key: "checkpoint-other-project", source_report_id: "checkpoint-other-origin", candidate_id: "other-candidate" };
const otherPath = `/stores/${storeId}/listing-drafts/${otherIdentity.key}/checkpoint`;
const otherReport = { ...baseReport, report_id: "checkpoint-other-base", task_id: "checkpoint-other-task",
  report: { ...baseReport.report, product: "Other Tablet Holder", listing_project_identity: otherIdentity,
    listing_handoff: { ...baseReport.report.listing_handoff,
      listing_fields: { ...baseReport.report.listing_handoff.listing_fields, title: "Other project title" } } } };
let server, browser, base, checkpoint, requests, unexpected, checkpointHandler, factHandler;

function resetFixture() {
  checkpoint = null; requests = []; unexpected = []; checkpointHandler = null; factHandler = null;
}

function savedCheckpoint(fields, revision = 1) {
  return { checkpoint_id: `checkpoint-revision-${revision}`, revision, mutation_id: `other-device-mutation-${revision}`,
    company_id: companyId, store_id: storeId, listing_project_identity: identity, base_report_id: baseReport.report_id,
    fields: { ...fields }, merchant_edited_fields: ["title"], saved_at: new Date().toISOString(), source: "merchant_edit" };
}

function deferred() {
  let resolve;
  const promise = new Promise((done) => { resolve = done; });
  return { promise, resolve };
}

async function waitUntil(predicate, message) {
  const deadline = Date.now() + 5000;
  while (!predicate() && Date.now() < deadline) await new Promise((resolve) => setTimeout(resolve, 20));
  assert.ok(predicate(), message);
}

function sendJson(res, status, body) {
  res.writeHead(status, { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" });
  res.end(JSON.stringify(body));
}

before(async () => {
  const source = fs.readFileSync(path.join(root, "app.js"), "utf8");
  const boot = /exposeLocalJiejingTestHooks\(\);\r?\ninit\(\);\r?\nrunLocalJiejingQaScenarioFromUrl\(\);\s*$/;
  assert.match(source, boot, "fixture removes startup only, not product functions");
  const appSource = source.replace(boot, "exposeLocalJiejingTestHooks();\n");
  const htmlWithInlineStyles = fs.readFileSync(path.join(root, "app.html"), "utf8")
    .replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, "")
    .replace(/<link\b[^>]*>/gi, "")
    .replace(/<img\b[^>]*>/gi, "")
    .replace("</body>", '<script src="/app.js"></script></body>');
  const html = htmlWithInlineStyles.replace(/<style\b[^>]*>[\s\S]*?<\/style>/gi, "");
  const styledHtml = htmlWithInlineStyles.replace("</head>", '<link rel="stylesheet" href="/styles.css"></head>');
  server = http.createServer(async (req, res) => {
    const url = new URL(req.url, "http://127.0.0.1");
    if (req.method === "GET" && url.pathname === "/app.js") {
      res.writeHead(200, { "content-type": "text/javascript; charset=utf-8" }); return res.end(appSource);
    }
    if (req.method === "GET" && url.pathname === "/app.html") {
      res.writeHead(200, { "content-type": "text/html; charset=utf-8" });
      return res.end(url.searchParams.get("visual") === "1" ? styledHtml : html);
    }
    const staticAssets = { "/styles.css": ["styles.css", "text/css; charset=utf-8"],
      "/assets/dashboard-preview.png": ["assets/dashboard-preview.png", "image/png"],
      "/assets/jiejing-app-icon.svg": ["assets/jiejing-app-icon.svg", "image/svg+xml"] };
    if (req.method === "GET" && Object.hasOwn(staticAssets, url.pathname)) {
      const [file, type] = staticAssets[url.pathname];
      res.writeHead(200, { "content-type": type }); return res.end(fs.readFileSync(path.join(root, file)));
    }
    if (req.method === "GET" && url.pathname === `/stores/${storeId}/merchant-project-status`
        && [...url.searchParams.keys()].length === 1
        && [identity.key, otherIdentity.key].includes(url.searchParams.get("project_id"))) {
      requests.push({ method: "GET", path: url.pathname, query: Object.fromEntries(url.searchParams) });
      return sendJson(res, 200, { merchant_project_status: null });
    }
    if (factHandler && req.method === "POST" && url.pathname === `/stores/${storeId}/product-facts`) {
      let raw = "";
      for await (const chunk of req) raw += chunk;
      const request = { method: "POST", path: url.pathname, body: JSON.parse(raw) };
      requests.push(request);
      return factHandler(request, res);
    }
    if (![checkpointPath, otherPath].includes(url.pathname) || !["GET", "POST"].includes(req.method)) {
      unexpected.push(`${req.method} ${url.pathname}`);
      return sendJson(res, 404, { error: "No other business API in this fixture" });
    }
    if (req.method === "GET") {
      const request = { method: "GET", path: url.pathname, query: Object.fromEntries(url.searchParams) };
      requests.push(request);
      if (checkpointHandler && await checkpointHandler(request, res)) return;
      const current = url.pathname === checkpointPath ? checkpoint : null;
      const report = url.pathname === checkpointPath ? baseReport : otherReport;
      return sendJson(res, 200, { status: current ? "saved" : "empty", checkpoint: current,
        current_revision: current?.revision || 0, current_base_report_id: report.report_id,
        current_base_report: report, base_changed: false });
    }
    let raw = "";
    for await (const chunk of req) raw += chunk;
    const body = JSON.parse(raw);
    const request = { method: "POST", path: url.pathname, body };
    requests.push(request);
    if (checkpointHandler && await checkpointHandler(request, res)) return;
    const revision = body.expected_revision + 1;
    checkpoint = { checkpoint_id: `checkpoint-revision-${revision}`, revision, mutation_id: body.mutation_id,
      company_id: companyId, store_id: storeId, listing_project_identity: identity,
      base_report_id: baseReport.report_id, fields: body.fields, merchant_edited_fields: body.merchant_edited_fields,
      saved_at: new Date().toISOString(), source: "merchant_edit" };
    return sendJson(res, 201, { status: "saved", checkpoint, idempotent_replay: false,
      model_called: false, usage_consumed: false, real_platform_writes_enabled: false, secret_exposed: false });
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  base = `http://127.0.0.1:${server.address().port}`;
  browser = await chromium.launch({ headless: true, channel: process.env.JIEJING_PLAYWRIGHT_CHANNEL || "chrome" });
});

after(async () => {
  if (browser) await browser.close();
  if (server) await new Promise((resolve) => server.close(resolve));
});

async function openDevice(options = {}) {
  const context = await browser.newContext({ viewport: { width: options.width || 1440, height: 900 } });
  const page = await context.newPage();
  const errors = [], consoleIssues = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => { if (["error", "warning"].includes(message.type())) consoleIssues.push(message.text()); });
  await page.route("**/*", (route) => {
    const url = new URL(route.request().url());
    if (url.origin === base) return route.continue();
    unexpected.push(`${route.request().method()} foreign-origin`);
    return route.abort();
  });
  await page.goto(`${base}/app.html?start=app&qa=public-saas&view=product&project=${identity.key}${options.visual ? "&visual=1" : ""}`);
  assert.equal(await page.evaluate(() => localStorage.length), 0, "new device has no draft or sync cache");
  await page.evaluate(({ companyId, userId, storeId, base, identity, originalFields, baseReport, visual }) => {
    window.__JIEJING_FORCE_PUBLIC_MVP__ = true;
    localStorage.setItem(saasStorageKeys.storeId, storeId);
    localStorage.setItem("jiejing_saas_backend_session_hint", "1");
    localStorage.setItem("jiejing_saas_session_hint", "1");
    state.saasApiBase = base;
    state.saasIdentity = { user_id: userId, company_id: companyId, role: "owner" };
    state.saasUser = { user_id: userId, email: "checkpoint@example.invalid" };
    state.saasCompany = { company_id: companyId };
    state.saasPermissions = ["create_task", "view_report"];
    state.saasStores = [{ store_id: storeId, company_id: companyId, platform: "ebay", marketplace: "EBAY_US" }];
    state.saasReports = [baseReport];
    state.saasTasks = [];
    state.saasProtectedStateReady = true;
    state.saasListingComposerDraft = { product: "Foldable Tablet Stand", title: "Original title",
      source_report_id: baseReport.report_id, listing_project_identity: identity,
      fields: { ...originalFields }, merchant_edited_fields: [], model_generated: false, safe_local_only: true };
    state.saasDetachedListingProjectDrafts = {};
    state.view = "product";
    bindEvents();
    document.querySelector("#view-product").innerHTML = renderSaasListingDraftEditor();
    if (visual) {
      document.documentElement.classList.add("app-ready");
      document.body.classList.add("saas-public-mvp");
      document.body.dataset.view = "product";
      document.querySelector("#appShell").classList.remove("is-hidden");
      document.querySelectorAll(".view").forEach((view) => view.classList.toggle("is-active", view.id === "view-product"));
    }
  }, { companyId, userId, storeId, base, identity: options.identity || identity, originalFields,
    baseReport: options.baseReport || baseReport, visual: options.visual === true });
  return { context, page, errors, consoleIssues };
}

async function mediaStepFixture(mode = "saved") {
  resetFixture();
  const image = "https://cdn.example.test/approved-gold-set.jpg";
  const packet = { product_name: "Gold wood-handled measuring set", simulation_only: true,
    source: "authenticated_merchant_request",
    merchant_confirmed_facts: { product_name: "Gold wood-handled measuring set", material: "Gold-tone metal and wood",
      condition: "NEW", image_urls: image, image_rights_confirmed: true },
    source_confirmed_facts: {}, unknown_facts: ["item_location"] };
  const facts = { ...structuredClone(baseReport), report_id: "media-facts-before", report_type: "merchant.product_facts",
    created_at: "2026-09-06T00:00:00Z", report: { listing_project_identity: identity, merchant_product_fact_packet: packet } };
  let currentBase = baseReport;
  let interrupted = false;
  checkpoint = savedCheckpoint({ ...originalFields, title: "Gold-Tone Measuring Set", selling_points: "4 cups\n4 spoons\nWood handles",
    description: "Eight gold-tone pieces with wood handles", images: image });
  const originalCopy = structuredClone(checkpoint.fields);
  checkpointHandler = async (request, res) => {
    if (request.method === "GET") {
      sendJson(res, 200, { status: "saved", checkpoint, current_revision: checkpoint.revision,
        current_base_report_id: currentBase.report_id, current_base_report: currentBase,
        base_changed: checkpoint.base_report_id !== currentBase.report_id });
    } else {
      if (mode === "interrupted" && !interrupted) {
        interrupted = true;
        sendJson(res, 503, { error_code: "checkpoint_storage_unavailable" });
        return true;
      }
      if (mode === "concurrent") checkpoint = { ...checkpoint, revision: 2,
        fields: { ...checkpoint.fields, title: "Other device reviewed copy" } };
      if (request.body.expected_revision !== checkpoint.revision || request.body.base_report_id !== currentBase.report_id) {
        sendJson(res, 409, { error_code: "listing_draft_revision_conflict", latest_checkpoint: checkpoint,
          current_revision: checkpoint.revision, current_base_report_id: currentBase.report_id, current_base_report: currentBase });
      } else {
        checkpoint = { ...checkpoint, checkpoint_id: "media-edit-2", revision: checkpoint.revision + 1,
          base_report_id: currentBase.report_id, mutation_id: request.body.mutation_id,
          fields: request.body.fields, merchant_edited_fields: request.body.merchant_edited_fields };
        sendJson(res, 201, { status: "saved", checkpoint });
      }
    }
    return true;
  };
  factHandler = (request, res) => {
    if (mode === "fact-failure") return sendJson(res, 503, { error_code: "product_fact_storage_unavailable" });
    currentBase = { ...facts, report_id: "media-facts-after", created_at: "2026-09-06T02:00:00Z",
      report: { ...facts.report, merchant_product_fact_packet: request.body.merchant_product_fact_packet } };
    if (mode === "changed-facts") currentBase.report.merchant_product_fact_packet.merchant_confirmed_facts.material = "Different material";
    sendJson(res, 201, { report: currentBase, merchant_product_fact_packet: currentBase.report.merchant_product_fact_packet,
      listing_project_identity: identity, is_current: true, current_fact_report_id: currentBase.report_id });
  };
  const device = await openDevice();
  await device.page.route(image, route => route.fulfill({ status: 200, contentType: "image/svg+xml",
    body: '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20"><rect width="20" height="20" fill="gold"/></svg>' }));
  await device.page.evaluate(({ facts, packet }) => {
    state.saasConnected = true;
    state.saasReports.push(facts);
    state.saasListingComposerDraft.merchant_product_fact_packet = packet;
    state.saasListingComposerDraft.source_product_fact_report_id = facts.report_id;
    setSaasListingWizardStep(3);
    renderProductListingCenter();
  }, { facts, packet });
  await device.page.evaluate(() => hydrateSaasListingCloudCheckpoint({ force: true }));
  return { device, originalCopy, latest: () => currentBase };
}

test("saving image step carries reviewed buyer copy to the saved fact version and a clean device", async () => {
  const { device, originalCopy, latest } = await mediaStepFixture();
  let second;
  try {
    await device.page.getByRole("button", { name: "保存并继续", exact: true }).click();
    await device.page.waitForFunction(() => !saasListingWizardRecord().busy);
    assert.equal(await device.page.evaluate(() => saasListingWizardRecord().step), 4);
    assert.equal(checkpoint.base_report_id, latest().report_id, "image save must not strand buyer copy on the old fact base");
    for (const key of ["title", "selling_points", "description"]) assert.equal(checkpoint.fields[key], originalCopy[key]);
    assert.match(checkpoint.fields.images, /approved-gold-set.jpg/);
    second = await openDevice({ baseReport: latest() });
    await second.page.evaluate(() => {
      restoreSaasListingComposerDraftFromBackendReports({ preferBackendLatest: true });
      document.querySelector('#view-product').innerHTML = renderSaasListingDraftEditor();
    });
    await second.page.evaluate(() => hydrateSaasListingCloudCheckpoint({ force: true }));
    for (const key of ["title", "selling_points", "description"]) {
      assert.equal(await second.page.locator(`[data-saas-listing-draft-field="${key}"]`).inputValue(), originalCopy[key]);
    }
    assert.equal(await second.page.evaluate(() => Boolean(saasListingCloudRecord().conflict)), false);
    assert.equal(await second.page.locator('.saas-listing-v2-draft-head > div > strong').textContent(), originalCopy.title);
    const rights = await second.page.evaluate(() => {
      const draft = state.saasListingComposerDraft;
      const assets = saasListingEbayFieldCoverage(draft).groups.find(group => group.key === "assets");
      return assets.fields.find(([label]) => label === "素材授权")[1];
    });
    assert.equal(rights, true, "the saved image-rights checkbox must agree with the field coverage display after restore");
    assert.equal(requests.filter(x => x.method === "POST" && x.path === checkpointPath).length, 1);
    assert.deepEqual(unexpected, []);
    assert.deepEqual(device.errors, []);
    assert.deepEqual(second.errors, []);
  } finally { if (second) await second.context.close(); await device.context.close(); }
});

test("image rights display only accepts confirmed facts for the exact currently selected images", async () => {
  const { device } = await mediaStepFixture();
  try {
    const results = await device.page.evaluate(() => {
      const draft = state.saasListingComposerDraft;
      const checked = () => saasListingEbayFieldCoverage(draft).groups.find(group => group.key === "assets")
        .fields.find(([label]) => label === "素材授权")[1];
      const before = checked();
      const image = draft.fields.images;
      draft.fields.images = "https://cdn.example.test/different.jpg";
      const changed = checked();
      draft.fields.images = "";
      const cleared = checked();
      draft.fields.images = image;
      draft.merchant_product_fact_packet.merchant_confirmed_facts.image_rights_confirmed = false;
      const unchecked = checked();
      draft.merchant_product_fact_packet.merchant_confirmed_facts.image_rights_confirmed = "true";
      const string = checked();
      draft.merchant_product_fact_packet.merchant_confirmed_facts.image_rights_confirmed = true;
      draft.merchant_product_fact_packet.unknown_facts.push("image_rights_confirmed");
      return { before, changed, cleared, unchecked, string, unknown: checked() };
    });
    assert.deepEqual(results, { before: true, changed: false, cleared: false, unchecked: false, string: false, unknown: false });
    assert.deepEqual(unexpected, []);
    assert.deepEqual(device.errors, []);
  } finally { await device.context.close(); }
});

for (const mode of ["concurrent", "fact-failure", "changed-facts", "interrupted"]) {
  test(`image-step copy continuity fails closed on ${mode}, preserving both content and the current step`, async () => {
    const { device, originalCopy } = await mediaStepFixture(mode);
    try {
      await device.page.getByRole("button", { name: "保存并继续", exact: true }).click();
      await device.page.waitForFunction(() => !saasListingWizardRecord().busy);
      assert.equal(await device.page.evaluate(() => saasListingWizardRecord().step), 3);
      assert.equal(await device.page.evaluate(() => state.saasListingComposerDraft.fields.title), originalCopy.title);
      if (mode === "concurrent") {
        assert.equal(checkpoint.fields.title, "Other device reviewed copy");
        assert.equal(await device.page.evaluate(() => saasListingCloudRecord().status), "conflict");
      } else if (mode === "interrupted") {
        // Recreate the in-memory sync layer using only its persisted cache and
        // a fresh authenticated GET, as a reload does. No force/CAS bypass.
        await device.page.evaluate(async () => {
          invalidateSaasListingCloudCheckpointContext();
          saasListingCloudRecords.clear();
          await hydrateSaasListingCloudCheckpoint({ force: true });
          await flushSaasListingCloudCheckpoint();
        });
        assert.equal(checkpoint.base_report_id, "media-facts-after");
        assert.equal(checkpoint.fields.title, originalCopy.title);
        assert.equal(await device.page.evaluate(() => saasListingCloudRecord().status), "saved");
        const posts = requests.filter(x => x.method === "POST" && x.path === checkpointPath);
        assert.equal(posts.length, 2);
        assert.deepEqual(posts[0].body, posts[1].body, "retry reuses its durable mutation, not another model or fact save");
      } else assert.equal(requests.filter(x => x.method === "POST" && x.path === checkpointPath).length, 0);
      assert.deepEqual(unexpected, []);
      assert.deepEqual(device.errors, []);
    } finally { await device.context.close(); }
  });
}

test("generation edit guard ignores empty checkpoint normalization but preserves real content and legacy-title clears", async () => {
  resetFixture();
  const device = await openDevice();
  try {
    await device.page.evaluate(async () => { await hydrateSaasListingCloudCheckpoint(); });
    const normalized = await device.page.evaluate(() => {
      const draft = state.saasListingComposerDraft;
      delete draft.fields.keywords;
      delete draft.fields.risk_notes;
      const before = saasListingAiGenerationEditSnapshot();
      draft.fields = { risk_notes: "", ...Object.fromEntries(Object.entries(draft.fields).reverse()), keywords: "" };
      return saasListingAiGenerationHasNewEdits(before);
    });
    assert.equal(normalized, false, "same ten field values with extra empty keys or reordered keys are not merchant edits");

    await device.page.evaluate(() => {
      delete state.saasListingComposerDraft.fields.title;
      document.querySelector("#view-product").innerHTML = renderSaasListingDraftEditor();
      window.__generationSnapshotBeforeClear = saasListingAiGenerationEditSnapshot();
    });
    assert.equal(await device.page.inputValue('[data-saas-listing-draft-field="title"]'), "Original title");
    await device.page.fill('[data-saas-listing-draft-field="title"]', "");
    assert.equal(await device.page.evaluate(() => saasListingAiGenerationHasNewEdits(window.__generationSnapshotBeforeClear)), true,
      "explicit clearing of a visible fallback title remains a real merchant edit");
    await device.page.evaluate(() => { window.__generationSnapshotBeforeFill = saasListingAiGenerationEditSnapshot(); });
    await device.page.fill('[data-saas-listing-draft-field="title"]', "Merchant replacement title");
    assert.equal(await device.page.evaluate(() => saasListingAiGenerationHasNewEdits(window.__generationSnapshotBeforeFill)), true,
      "empty to nonempty merchant input remains protected");

    const contentGuards = await device.page.evaluate(() => {
      const draft = state.saasListingComposerDraft;
      const changed = (prepare, mutate) => { prepare(); const before = saasListingAiGenerationEditSnapshot(); mutate(); return saasListingAiGenerationHasNewEdits(before); };
      return {
        longTail: changed(() => { draft.fields.description = "x".repeat(1400) + "A"; }, () => { draft.fields.description = "x".repeat(1400) + "B"; }),
        literalText: changed(() => { draft.fields.description = "Hermes 样例"; }, () => { draft.fields.description = "捷境系统 历史占位"; }),
        nonemptyToEmpty: changed(() => { draft.fields.description = "Real description"; }, () => { draft.fields.description = ""; }),
        facts: changed(() => { draft.merchant_product_fact_packet = { material: "Resin" }; }, () => { draft.merchant_product_fact_packet.material = "Steel"; }),
        prefill: changed(() => { draft.publish_prefill = { quantity: "1" }; }, () => { draft.publish_prefill.quantity = "2"; }),
      };
    });
    assert.deepEqual(contentGuards, { longTail: true, literalText: true, nonemptyToEmpty: true, facts: true, prefill: true },
      "the comparison must not truncate, rewrite, or discard actual field, fact, or prefill changes");
    assert.deepEqual(device.errors, []);
    assert.deepEqual(unexpected, []);
  } finally { await device.context.close(); }
});

test("editing the eight visible fields autosaves all ten fields, including clears, and a clean second device restores them", async () => {
  resetFixture();
  const first = await openDevice();
  let second;
  try {
    assert.equal(await first.page.locator("[data-saas-listing-draft-field]").count(), 8);
    const edited = { ...originalFields, title: "", category: "", selling_points: "Merchant point one\nMerchant point two",
      description: "Merchant description", item_specifics: "Material: Steel", price: "29.00 USD",
      images: "Merchant photo still required", logistics: "Weight to be confirmed" };
    const posted = first.page.waitForResponse((response) => new URL(response.url()).pathname === checkpointPath
      && response.request().method() === "POST", { timeout: 8000 });
    // Handle rejection immediately; missing autosave must be one clean RED, not
    // an unhandled promise rejection while another locator is still resolving.
    const observedPost = posted.then((response) => ({ response }), (error) => ({ error }));
    for (const key of visibleKeys) {
      await first.page.locator(`[data-saas-listing-draft-field="${key}"]`).fill(edited[key]);
    }
    const observed = await observedPost;
    assert.equal(observed.error, undefined, "real input must automatically POST a cloud checkpoint within 8 seconds");
    assert.equal(observed.response.status(), 201);
    const posts = requests.filter((item) => item.method === "POST");
    assert.equal(posts.length, 1, "one quiet edit batch makes one checkpoint, not a task or model request");
    const body = posts[0].body;
    assert.deepEqual(Object.keys(body).sort(), ["contract_version", "listing_project_identity", "base_report_id",
      "expected_revision", "mutation_id", "fields", "merchant_edited_fields"].sort(), "never upload full snapshot or client trust flags");
    assert.equal(body.contract_version, "listing_merchant_edit_v1");
    assert.deepEqual(body.listing_project_identity, identity);
    assert.equal(body.base_report_id, baseReport.report_id);
    assert.equal(body.expected_revision, 0);
    assert.match(body.mutation_id, /^[A-Za-z0-9._:-]{8,160}$/);
    assert.deepEqual(body.fields, edited, "all ten keys survive and explicit blanks are not filled with old values");
    assert.deepEqual([...body.merchant_edited_fields].sort(), [...visibleKeys].sort());
    second = await openDevice();
    await second.page.evaluate(() => hydrateSaasListingCloudCheckpoint({ force: true }));
    for (const key of visibleKeys) {
      assert.equal(await second.page.locator(`[data-saas-listing-draft-field="${key}"]`).inputValue(), edited[key], `second device renders saved ${key}`);
    }
    assert.deepEqual(await second.page.evaluate(() => state.saasListingComposerDraft.fields), edited);
    assert.equal(requests.filter((item) => item.method === "POST").length, 1, "restoring and rendering must not create another version");
    for (const get of requests.filter((item) => item.method === "GET")) {
      assert.deepEqual(get.query, { source_report_id: identity.source_report_id, candidate_id: identity.candidate_id });
    }
    assert.deepEqual(unexpected, [], "zero model, account, eBay, billing or other business requests");
    assert.deepEqual(first.errors, []);
    assert.deepEqual(second.errors, []);
  } finally {
    if (second) await second.context.close();
    await first.context.close();
  }
});

test("a held save receipt never overwrites newer input or marks that newer input as cloud-saved", async () => {
  resetFixture();
  const releasePost = deferred();
  let held = false;
  checkpointHandler = async (request) => {
    if (request.method === "POST" && !held) { held = true; await releasePost.promise; }
    return false;
  };
  const device = await openDevice();
  try {
    await device.page.evaluate(() => hydrateSaasListingCloudCheckpoint({ force: true }));
    await device.page.locator('[data-saas-listing-draft-field="title"]').fill("First submitted title");
    await device.page.evaluate(() => { window.firstSave = flushSaasListingCloudCheckpoint(); });
    await waitUntil(() => requests.some((request) => request.method === "POST"), "first save reaches fake HTTP boundary");
    await device.page.locator('[data-saas-listing-draft-field="title"]').fill("Newer input while saving");
    assert.equal(requests.filter((request) => request.method === "POST").length, 1);
    releasePost.resolve();
    await device.page.evaluate(() => window.firstSave);
    assert.equal(await device.page.locator('[data-saas-listing-draft-field="title"]').inputValue(), "Newer input while saving");
    assert.doesNotMatch(await device.page.locator("[data-saas-listing-cloud-status]").textContent(), /已云端保存/,
      "receipt for old input is not a receipt for new input");
    await device.page.evaluate(() => flushSaasListingCloudCheckpoint());
    const posts = requests.filter((request) => request.method === "POST");
    assert.equal(posts.length, 2);
    assert.equal(posts[0].body.fields.title, "First submitted title");
    assert.equal(posts[1].body.fields.title, "Newer input while saving");
    assert.equal(posts[1].body.expected_revision, 1);
    assert.notEqual(posts[1].body.mutation_id, posts[0].body.mutation_id);
    assert.match(await device.page.locator("[data-saas-listing-cloud-status]").textContent(), /已云端保存/);
    assert.deepEqual(unexpected, []);
    assert.deepEqual(device.errors, []);
  } finally {
    releasePost.resolve();
    await device.context.close();
  }
});

test("two first-save requests waiting on the initial GET produce only one in-flight POST", async () => {
  resetFixture();
  const releaseGet = deferred(), releasePost = deferred();
  checkpointHandler = async (request) => {
    await (request.method === "GET" ? releaseGet.promise : releasePost.promise);
    return false;
  };
  const device = await openDevice();
  try {
    await waitUntil(() => requests.some((request) => request.method === "GET"), "initial checkpoint GET is held");
    await device.page.locator('[data-saas-listing-draft-field="title"]').fill("First save before GET returns");
    await device.page.evaluate(() => { window.concurrentSaves = Promise.all([
      flushSaasListingCloudCheckpoint(), flushSaasListingCloudCheckpoint(),
    ]); });
    releaseGet.resolve();
    await waitUntil(() => requests.some((request) => request.method === "POST"), "save proceeds after the first GET");
    // Both await continuations and network dispatches have run; the first POST
    // remains unacknowledged, so there must not be a second same-scope writer.
    await device.page.evaluate(() => new Promise((resolve) => setTimeout(resolve, 150)));
    assert.equal(requests.filter((request) => request.method === "POST").length, 1,
      "single-flight must be rechecked after waiting for the shared initial GET");
    releasePost.resolve();
    await device.page.evaluate(() => window.concurrentSaves);
    assert.equal(await device.page.locator('[data-saas-listing-draft-field="title"]').inputValue(), "First save before GET returns");
    assert.deepEqual(unexpected, []);
    assert.deepEqual(device.errors, []);
  } finally {
    releaseGet.resolve(); releasePost.resolve();
    await device.context.close();
  }
});

test("input made during a held initial GET survives; choosing cloud keeps a visible local backup without POST", async () => {
  resetFixture();
  checkpoint = savedCheckpoint({ ...originalFields, title: "Title saved on another device", category: "" });
  const releaseGet = deferred();
  checkpointHandler = async (request) => { if (request.method === "GET") await releaseGet.promise; return false; };
  const device = await openDevice();
  try {
    await waitUntil(() => requests.some((request) => request.method === "GET"), "initial GET is in flight");
    await device.page.locator('[data-saas-listing-draft-field="title"]').fill("Local input before initial GET returns");
    await device.page.evaluate(() => { window.initialRead = hydrateSaasListingCloudCheckpoint({ force: true }); });
    releaseGet.resolve();
    await device.page.evaluate(() => window.initialRead);
    assert.equal(await device.page.locator('[data-saas-listing-draft-field="title"]').inputValue(), "Local input before initial GET returns");
    const status = device.page.locator("[data-saas-listing-cloud-status]");
    assert.match(await status.textContent(), /检测到其他更新/);
    assert.match(await status.textContent(), /Title saved on another device/);
    assert.equal(requests.filter((request) => request.method === "POST").length, 0, "a conflict must not overwrite either version");
    await device.page.locator('[data-saas-listing-cloud-action="use-cloud"]').click();
    await device.page.waitForFunction(() => document.querySelector('[data-saas-listing-draft-field="title"]').value === "Title saved on another device");
    assert.equal(await device.page.locator('[data-saas-listing-draft-field="category"]').inputValue(), "");
    assert.match(await status.textContent(), /查看保留的本机副本（1）/);
    assert.match(await status.textContent(), /Local input before initial GET returns/);
    assert.equal(requests.filter((request) => request.method === "POST").length, 0);
    assert.equal(await device.page.evaluate(() => state.saasListingComposerDraft.model_generated), false);
    assert.deepEqual(unexpected, []);
    assert.deepEqual(device.errors, []);
  } finally {
    releaseGet.resolve();
    await device.context.close();
  }
});

test("409 preserves both versions and keeping local uses the latest revision without bypassing a second conflict", async () => {
  resetFixture();
  const device = await openDevice();
  try {
    await device.page.evaluate(() => hydrateSaasListingCloudCheckpoint({ force: true }));
    checkpointHandler = async (request, res) => {
      if (request.method !== "POST") return false;
      const revision = request.body.expected_revision + 1;
      checkpoint = savedCheckpoint({ ...originalFields, title: `Other device revision ${revision}` }, revision);
      sendJson(res, 409, { error: "listing_draft_revision_conflict", code: "listing_draft_revision_conflict",
        latest_checkpoint: checkpoint, current_revision: revision, current_base_report_id: baseReport.report_id,
        current_base_report: baseReport });
      return true;
    };
    await device.page.locator('[data-saas-listing-draft-field="title"]').fill("Local version must survive both conflicts");
    await device.page.locator('[data-saas-listing-draft-field="category"]').fill("");
    await device.page.evaluate(() => flushSaasListingCloudCheckpoint());
    const status = device.page.locator("[data-saas-listing-cloud-status]");
    assert.match(await status.textContent(), /Other device revision 1/);
    assert.equal(await device.page.locator('[data-saas-listing-draft-field="title"]').inputValue(), "Local version must survive both conflicts");
    const secondConflict = device.page.waitForResponse((response) => new URL(response.url()).pathname === checkpointPath
      && response.request().method() === "POST" && response.status() === 409);
    await device.page.locator('[data-saas-listing-cloud-action="keep-local"]').click();
    await secondConflict;
    await device.page.waitForFunction(() => document.querySelector("[data-saas-listing-cloud-status]").textContent.includes("Other device revision 2"));
    const posts = requests.filter((request) => request.method === "POST");
    assert.equal(posts.length, 2);
    assert.equal(posts[0].body.expected_revision, 0);
    assert.equal(posts[1].body.expected_revision, 1);
    assert.notEqual(posts[0].body.mutation_id, posts[1].body.mutation_id);
    assert.deepEqual(posts[1].body.fields, posts[0].body.fields);
    assert.equal(await device.page.locator('[data-saas-listing-draft-field="category"]').inputValue(), "");
    assert.equal(await device.page.locator('[data-saas-listing-draft-field="title"]').inputValue(), "Local version must survive both conflicts");
    assert.match(await status.textContent(), /检测到其他更新/);
    assert.deepEqual(unexpected, []);
    assert.deepEqual(device.errors, []);
  } finally { await device.context.close(); }
});

test("a timed-out POST keeps local edits and the visible retry sends the exact same mutation and payload", async () => {
  resetFixture();
  const releaseLostPost = deferred();
  let lostFirstPost = false;
  checkpointHandler = async (request) => {
    if (request.method !== "POST" || lostFirstPost) return false;
    lostFirstPost = true;
    // Simulate an unacknowledged request without fabricating a saved receipt.
    // Exercise the real 15-second AbortController path, not a mocked app helper.
    await releaseLostPost.promise;
    return true;
  };
  const device = await openDevice();
  try {
    await device.page.evaluate(() => hydrateSaasListingCloudCheckpoint({ force: true }));
    await device.page.locator('[data-saas-listing-draft-field="title"]').fill("Text retained through timeout");
    await device.page.locator('[data-saas-listing-draft-field="category"]').fill("");
    assert.equal(await device.page.evaluate(() => flushSaasListingCloudCheckpoint()), false);
    const status = device.page.locator("[data-saas-listing-cloud-status]");
    assert.match(await status.textContent(), /暂未同步.*保留在本机/);
    assert.doesNotMatch(await status.textContent(), /已云端保存/);
    assert.equal(await device.page.locator('[data-saas-listing-draft-field="title"]').inputValue(), "Text retained through timeout");
    assert.equal(await device.page.locator('[data-saas-listing-draft-field="category"]').inputValue(), "");
    releaseLostPost.resolve();
    await device.page.locator('[data-saas-listing-cloud-action="retry"]').click();
    await device.page.waitForFunction(() => document.querySelector("[data-saas-listing-cloud-status]").textContent.includes("已云端保存"));
    const posts = requests.filter((request) => request.method === "POST");
    assert.equal(posts.length, 2);
    assert.deepEqual(posts[1].body, posts[0].body, "uncertain retry reuses the complete frozen mutation, including explicit blanks");
    assert.deepEqual(unexpected, []);
    assert.deepEqual(device.errors, []);
  } finally {
    releaseLostPost.resolve();
    await device.context.close();
  }
});

test("recent-task A to B to A switches reject the old save receipt while preserving new A input", async () => {
  resetFixture();
  const releasePost = deferred();
  checkpointHandler = async (request) => { if (request.method === "POST") await releasePost.promise; return false; };
  const device = await openDevice();
  try {
    await device.page.evaluate(({ baseReport, otherReport }) => {
      state.saasReports = [baseReport, otherReport];
      state.saasTasks = [baseReport, otherReport].map((report) => ({ task_id: report.task_id,
        company_id: report.company_id, store_id: report.store_id, task_type: "listing_draft_generation",
        status: "completed", updated_at: report.created_at,
        input: { product: report.report.product, listing_project_identity: report.report.listing_project_identity } }));
    }, { baseReport, otherReport });
    await device.page.evaluate(() => hydrateSaasListingCloudCheckpoint({ force: true }));
    await device.page.locator('[data-saas-listing-draft-field="title"]').fill("A before leaving, save pending");
    await device.page.evaluate(() => { window.oldASave = flushSaasListingCloudCheckpoint(); });
    await waitUntil(() => requests.some((request) => request.method === "POST"), "A save reaches HTTP");
    assert.equal(await device.page.evaluate((taskId) => openSaasRecentProductTask(taskId), otherReport.task_id), true);
    assert.equal(await device.page.evaluate(() => saasCurrentListingProjectIdentity().key), otherIdentity.key);
    assert.equal(await device.page.locator('[data-saas-listing-draft-field="title"]').inputValue(), "Other project title");
    assert.equal(await device.page.evaluate((taskId) => openSaasRecentProductTask(taskId), baseReport.task_id), true);
    assert.equal(await device.page.evaluate(() => saasCurrentListingProjectIdentity().key), identity.key);
    await device.page.locator('[data-saas-listing-draft-field="title"]').fill("New A input after returning");
    // Keep the old POST held beyond the actual one-second debounce. Releasing
    // it before the timer fires misses a lost wake-up in the single-flight path.
    await device.page.evaluate(() => new Promise((resolve) => setTimeout(resolve, 1250)));
    assert.equal(requests.filter((request) => request.method === "POST").length, 1,
      "new A debounce has fired, but its previous writer is still in flight");
    releasePost.resolve();
    assert.equal(await device.page.evaluate(() => window.oldASave), false, "same identity after A-B-A is still a newer navigation epoch");
    assert.equal(await device.page.locator('[data-saas-listing-draft-field="title"]').inputValue(), "New A input after returning");
    assert.doesNotMatch(await device.page.locator("[data-saas-listing-cloud-status]").textContent(), /已云端保存/);
    await device.page.waitForFunction(() => document.querySelector("[data-saas-listing-cloud-status]").textContent.includes("已云端保存"), null, { timeout: 8000 });
    const finalPost = requests.filter((request) => request.method === "POST").at(-1);
    assert.equal(finalPost.body.fields.title, "New A input after returning", "new A input eventually autosaves after the old promise releases its single-flight slot");
    assert.equal(finalPost.body.expected_revision, 1);
    assert.equal(await device.page.locator('[data-saas-listing-draft-field="title"]').inputValue(), "New A input after returning");
    assert.equal(requests.filter((request) => request.method === "POST" && request.path === otherPath).length, 0);
    assert.deepEqual(unexpected, []);
    assert.deepEqual(device.errors, []);
  } finally {
    releasePost.resolve();
    await device.context.close();
  }
});

test("merchant editing a vision-origin Listing with matching validated backend facts does not require another AI run", async () => {
  resetFixture();
  const device = await openDevice();
  try {
    await device.page.evaluate(() => hydrateSaasListingCloudCheckpoint({ force: true }));
    await device.page.evaluate(() => {
      const packet = { product_name: "Foldable Tablet Stand", source_confirmed_facts: {},
        merchant_confirmed_facts: { product_name: "Foldable Tablet Stand", material: "Aluminum", condition: "NEW" },
        unknown_facts: ["sku"], fact_conflicts: [], simulation_only: false };
      state.saasReports[0].report.merchant_product_fact_packet = structuredClone(packet);
      Object.assign(state.saasListingComposerDraft, { source_type: "ai_ceo_product_vision", model_generated: true,
        buyer_copy_requires_validated_listing_generation: true, merchant_product_fact_packet: packet });
    });
    await device.page.locator('[data-saas-listing-draft-field="title"]').fill("Merchant title with the same confirmed facts");
    const actual = await device.page.evaluate(() => ({ prefill: saasPublishIntakePrefillValues(""),
      modelGenerated: state.saasListingComposerDraft.model_generated }));
    assert.equal(actual.modelGenerated, false, "manual text is not falsely labelled model-generated");
    assert.equal(actual.prefill.title, "Merchant title with the same confirmed facts",
      "the existing same-scope validated generation satisfies the vision gate while unchanged facts still require normal review");
    assert.deepEqual(unexpected, []);
    assert.deepEqual(device.errors, []);
  } finally { await device.context.close(); }
});

test("switching accounts while a checkpoint GET is pending never restores the previous account's draft", async () => {
  resetFixture();
  checkpoint = savedCheckpoint({ ...originalFields, title: "Previous account cloud-only text" });
  const releaseGet = deferred();
  checkpointHandler = async (request) => { if (request.method === "GET") await releaseGet.promise; return false; };
  const device = await openDevice();
  try {
    await waitUntil(() => requests.some((request) => request.method === "GET"), "previous account GET is held");
    await device.page.evaluate(() => { window.previousAccountRead = hydrateSaasListingCloudCheckpoint({ force: true }); });
    await device.page.evaluate(() => startSaasAccountSwitch("next-account@example.invalid"));
    releaseGet.resolve();
    assert.equal(await device.page.evaluate(() => window.previousAccountRead), false);
    const stateAfter = await device.page.evaluate(() => ({ draft: state.saasListingComposerDraft,
      company: state.saasCompany, user: state.saasUser, identity: state.saasIdentity,
      checkpointCacheKeys: Object.keys(localStorage).filter((key) => key.startsWith("jiejing_listing_cloud_v1:")) }));
    assert.equal(stateAfter.draft, null);
    assert.equal(stateAfter.company, null);
    assert.equal(stateAfter.user, null);
    assert.equal(stateAfter.identity, null);
    assert.deepEqual(stateAfter.checkpointCacheKeys, [], "late GET must not persist data after account ownership ended");
    assert.doesNotMatch(await device.page.locator("body").textContent(), /Previous account cloud-only text/);
    assert.equal(requests.filter((request) => request.method === "POST").length, 0);
    assert.deepEqual(unexpected, []);
    assert.deepEqual(device.errors, []);
  } finally {
    releaseGet.resolve();
    await device.context.close();
  }
});

test("returning to A during its old GET starts a fresh read and restores new A without any POST", async () => {
  resetFixture();
  const oldCheckpoint = savedCheckpoint({ ...originalFields, title: "Old A cloud title" });
  checkpoint = savedCheckpoint({ ...originalFields, title: "Newest A cloud title" }, 2);
  const releaseOldGet = deferred();
  let firstAGet = true;
  checkpointHandler = async (request, res) => {
    if (request.method !== "GET" || request.path !== checkpointPath || !firstAGet) return false;
    firstAGet = false;
    await releaseOldGet.promise;
    sendJson(res, 200, { status: "saved", checkpoint: oldCheckpoint, current_revision: 1,
      current_base_report_id: baseReport.report_id, current_base_report: baseReport, base_changed: false });
    return true;
  };
  const device = await openDevice();
  try {
    await waitUntil(() => requests.some((request) => request.path === checkpointPath), "old A GET is held");
    await device.page.evaluate(({ baseReport, otherReport }) => {
      window.oldARead = hydrateSaasListingCloudCheckpoint({ force: true });
      state.saasReports = [baseReport, otherReport];
      state.saasTasks = [baseReport, otherReport].map((report) => ({ task_id: report.task_id,
        company_id: report.company_id, store_id: report.store_id, task_type: "listing_draft_generation",
        status: "completed", updated_at: report.created_at,
        input: { product: report.report.product, listing_project_identity: report.report.listing_project_identity } }));
      openSaasRecentProductTask(otherReport.task_id);
      openSaasRecentProductTask(baseReport.task_id);
    }, { baseReport, otherReport });
    releaseOldGet.resolve();
    assert.equal(await device.page.evaluate(() => window.oldARead), false, "old epoch read is discarded");
    await waitUntil(() => requests.filter((request) => request.method === "GET" && request.path === checkpointPath).length >= 2,
      "returning to A must not remain attached to its obsolete GET; a fresh scoped read must start automatically");
    await device.page.waitForFunction(() => document.querySelector('[data-saas-listing-draft-field="title"]').value === "Newest A cloud title", null, { timeout: 5000 });
    assert.equal(requests.filter((request) => request.method === "POST").length, 0);
    assert.deepEqual(unexpected, []);
    assert.deepEqual(device.errors, []);
  } finally {
    releaseOldGet.resolve();
    await device.context.close();
  }
});

test("manual vision copy cannot borrow generation proof from missing, invalid, foreign-scope or different-fact reports", async () => {
  resetFixture();
  const device = await openDevice();
  try {
    await device.page.evaluate(() => hydrateSaasListingCloudCheckpoint({ force: true }));
    const cases = ["missing_generation", "failed_generation", "wrong_runtime", "wrong_contract", "wrong_source_mode", "not_ready",
      "foreign_company", "foreign_store", "foreign_project", "foreign_source", "foreign_candidate", "missing_fact_packet",
      "changed_material", "cleared_material", "new_unknown", "new_conflict", "changed_simulation", "newer_different_facts"];
    for (const scenario of cases) {
      await device.page.evaluate(({ scenario, baseReport, identity, originalFields }) => {
        const packet = { product_name: "Foldable Tablet Stand", source_confirmed_facts: {},
          merchant_confirmed_facts: { product_name: "Foldable Tablet Stand", material: "Aluminum", condition: "NEW" },
          unknown_facts: ["sku"], fact_conflicts: [], simulation_only: false };
        const report = structuredClone(baseReport);
        report.report.merchant_product_fact_packet = structuredClone(packet);
        state.saasReports = [report];
        state.saasListingComposerDraft = { product: packet.product_name, title: "Original title", fields: { ...originalFields },
          listing_project_identity: identity, source_type: "ai_ceo_product_vision", model_generated: true,
          buyer_copy_requires_validated_listing_generation: true, merchant_product_fact_packet: packet };
        if (scenario === "missing_generation") state.saasReports = [];
        if (scenario === "failed_generation") report.status = "failed";
        if (scenario === "wrong_runtime") report.runtime_run_id = "legacy_workflow";
        if (scenario === "wrong_contract") report.report.contract_version = "legacy_contract";
        if (scenario === "wrong_source_mode") report.report.listing_handoff.source_mode = "vision_suggestion";
        if (scenario === "not_ready") report.report.listing_handoff.ready_for_listing_draft = false;
        if (scenario === "foreign_company") report.company_id = "another-company";
        if (scenario === "foreign_store") report.store_id = "another-store";
        if (scenario === "foreign_project") report.report.listing_project_identity.key = "another-project";
        if (scenario === "foreign_source") report.report.listing_project_identity.source_report_id = "another-origin";
        if (scenario === "foreign_candidate") report.report.listing_project_identity.candidate_id = "another-candidate";
        if (scenario === "missing_fact_packet") delete report.report.merchant_product_fact_packet;
        if (scenario === "changed_material") packet.merchant_confirmed_facts.material = "Steel";
        if (scenario === "cleared_material") delete packet.merchant_confirmed_facts.material;
        if (scenario === "new_unknown") packet.unknown_facts.push("material");
        if (scenario === "new_conflict") packet.fact_conflicts.push({ field: "material", values: ["Steel", "Aluminum"] });
        if (scenario === "changed_simulation") packet.simulation_only = true;
        if (scenario === "newer_different_facts") {
          const newer = structuredClone(report);
          newer.report_id = "newer-generation"; newer.created_at = "2026-09-06T02:00:00Z";
          newer.report.merchant_product_fact_packet.merchant_confirmed_facts.material = "Steel";
          state.saasReports.push(newer);
        }
      }, { scenario, baseReport, identity, originalFields });
      await device.page.locator('[data-saas-listing-draft-field="title"]').fill(`Manual title for ${scenario}`);
      const actual = await device.page.evaluate(() => ({ title: saasPublishIntakePrefillValues("").title,
        modelGenerated: state.saasListingComposerDraft.model_generated }));
      assert.equal(actual.modelGenerated, false, scenario);
      assert.equal(actual.title, "", `${scenario}: original vision-generation gate must remain closed`);
    }
    assert.deepEqual(unexpected, []);
    assert.deepEqual(device.errors, []);
  } finally { await device.context.close(); }
});

test("all ten explicit clears survive a new device and an empty manual title cannot reappear in publish prefill", async () => {
  resetFixture();
  const device = await openDevice();
  let second;
  try {
    await device.page.evaluate(() => hydrateSaasListingCloudCheckpoint({ force: true }));
    for (const key of visibleKeys) await device.page.locator(`[data-saas-listing-draft-field="${key}"]`).fill("");
    await device.page.evaluate(() => {
      setSaasListingDraftField("keywords", "", { merchantEdited: true });
      setSaasListingDraftField("risk_notes", "", { merchantEdited: true });
    });
    await device.page.evaluate(() => flushSaasListingCloudCheckpoint());
    const emptyFields = Object.fromEntries(fieldKeys.map((key) => [key, ""]));
    const posts = requests.filter((request) => request.method === "POST");
    assert.equal(posts.length, 1);
    assert.deepEqual(posts[0].body.fields, emptyFields);
    assert.deepEqual([...posts[0].body.merchant_edited_fields].sort(), [...fieldKeys].sort());
    second = await openDevice();
    await second.page.evaluate(() => hydrateSaasListingCloudCheckpoint({ force: true }));
    assert.deepEqual(await second.page.evaluate(() => state.saasListingComposerDraft.fields), emptyFields);
    for (const key of visibleKeys) assert.equal(await second.page.locator(`[data-saas-listing-draft-field="${key}"]`).inputValue(), "", key);
    assert.equal(await second.page.evaluate(() => saasPublishIntakePrefillValues("").title), "",
      "a deliberately cleared title is not a missing field and must not fall back to draft.title");
    assert.equal(requests.filter((request) => request.method === "POST").length, 1);
    assert.deepEqual(unexpected, []);
    assert.deepEqual(device.errors, []);
    assert.deepEqual(second.errors, []);
  } finally {
    if (second) await second.context.close();
    await device.context.close();
  }
});

test("an old-base GET cannot overwrite a newer generated draft installed while that read was in flight", async () => {
  resetFixture();
  const releaseOldGet = deferred();
  const oldCheckpoint = savedCheckpoint({ ...originalFields, title: "Old checkpoint before new generation" });
  const newerBase = structuredClone(baseReport);
  newerBase.report_id = "checkpoint-new-generation-base";
  newerBase.created_at = "2026-09-06T03:00:00Z";
  newerBase.report.listing_handoff.listing_fields.title = "Newly generated current title";
  let firstRead = true;
  checkpointHandler = async (request, res) => {
    if (request.method !== "GET" || request.path !== checkpointPath) return false;
    if (firstRead) {
      firstRead = false;
      await releaseOldGet.promise;
      sendJson(res, 200, { status: "saved", checkpoint: oldCheckpoint, current_revision: 1,
        current_base_report_id: baseReport.report_id, current_base_report: baseReport, base_changed: false });
    } else {
      sendJson(res, 200, { status: "empty", checkpoint: null, current_revision: 0,
        current_base_report_id: newerBase.report_id, current_base_report: newerBase, base_changed: false });
    }
    return true;
  };
  const device = await openDevice();
  try {
    await waitUntil(() => requests.some((request) => request.path === checkpointPath), "old-base GET is held");
    await device.page.evaluate((newerBase) => {
      window.oldBaseRead = hydrateSaasListingCloudCheckpoint({ force: true });
      // Represents the already completed generation/report response, not a new
      // provider call. Run the actual report restore and renderer for that base.
      state.saasReports = [newerBase, ...state.saasReports];
      restoreSaasListingComposerDraftFromBackendReports({ preferBackendLatest: true, projectId: newerBase.report.listing_project_identity.key });
      document.querySelector("#view-product").innerHTML = renderSaasListingDraftEditor();
    }, newerBase);
    assert.equal(await device.page.locator('[data-saas-listing-draft-field="title"]').inputValue(), "Newly generated current title");
    releaseOldGet.resolve();
    await device.page.evaluate(() => window.oldBaseRead);
    assert.equal(await device.page.locator('[data-saas-listing-draft-field="title"]').inputValue(), "Newly generated current title",
      "same-project identity is insufficient: the old read belongs to the superseded report base");
    await device.page.evaluate(() => ensureSaasListingCloudCheckpoint());
    await waitUntil(() => requests.filter((request) => request.path === checkpointPath).length >= 2,
      "ensure must refresh the changed base instead of treating the old read as loaded");
    assert.equal(await device.page.evaluate(() => state.saasListingComposerDraft.fields.title), "Newly generated current title");
    assert.equal(requests.filter((request) => request.method === "POST").length, 0);
    assert.deepEqual(unexpected, []);
    assert.deepEqual(device.errors, []);
  } finally {
    releaseOldGet.resolve();
    await device.context.close();
  }
});

test("merchant edits and clears take priority over stale publish-prefill content without changing account policies or location", async () => {
  resetFixture();
  const device = await openDevice();
  const accountValues = { merchant_location_key: "existing-merchant-location", item_location: "US",
    fulfillment_policy_id: "existing-fulfillment", payment_policy_id: "existing-payment", return_policy_id: "existing-return" };
  try {
    await device.page.evaluate(() => hydrateSaasListingCloudCheckpoint({ force: true }));
    await device.page.evaluate((accountValues) => {
      state.saasListingComposerDraft.source_type = "merchant_input";
      state.saasListingComposerDraft.publish_prefill = { ...accountValues, price: "88.00", currency: "USD",
        category_id: "11111", category_leaf: "Old category leaf", image_urls: "https://assets.example.invalid/old-prefill.jpg",
        description_html: "<p>OLD PUBLISH DESCRIPTION</p>" };
      state.saasListingComposerDraft.media_writeback = { image_urls: ["https://assets.example.invalid/old-reviewed.jpg"],
        asset_count: 1, review_status: "approved_for_listing", rights_status: "merchant_rights_confirmed",
        listing_use_status: "approved_for_listing_draft" };
    }, accountValues);
    const writebackBefore = await device.page.evaluate(() => state.saasListingComposerDraft.media_writeback);
    for (const [key, value] of Object.entries({ price: "35.50 USD", category: "", images: "",
      selling_points: "New merchant point one\nNew merchant point two", description: "Updated merchant description" })) {
      await device.page.locator(`[data-saas-listing-draft-field="${key}"]`).fill(value);
    }
    const changed = await device.page.evaluate(() => saasPublishIntakePrefillValues("Legacy prompt with https://assets.example.invalid/old-source.jpg"));
    const actualContent = Object.fromEntries(["price", "currency", "category_id", "category_leaf", "image_urls", "description_html"].map((key) => [key, changed[key]]));
    assert.deepEqual(actualContent, { price: "35.50", currency: "USD", category_id: "", category_leaf: "", image_urls: "",
      description_html: "New merchant point one\nNew merchant point two\n\nUpdated merchant description" },
    "hand-edited content wins over old publish_prefill, old reviewed image URLs and old source text");
    assert.deepEqual(Object.fromEntries(Object.keys(accountValues).map((key) => [key, changed[key]])), accountValues,
      "text edits do not change selected account policies or inventory location");
    assert.deepEqual(await device.page.evaluate(() => state.saasListingComposerDraft.media_writeback), writebackBefore,
      "clearing selected image URLs does not erase the separate rights-review evidence");
    for (const key of ["price", "selling_points", "description"]) await device.page.locator(`[data-saas-listing-draft-field="${key}"]`).fill("");
    const cleared = await device.page.evaluate(() => saasPublishIntakePrefillValues("Legacy prompt text must not refill deliberately cleared content"));
    assert.deepEqual(Object.fromEntries(["price", "category_id", "category_leaf", "image_urls", "description_html"].map((key) => [key, cleared[key]])),
      { price: "", category_id: "", category_leaf: "", image_urls: "", description_html: "" });
    assert.deepEqual(Object.fromEntries(Object.keys(accountValues).map((key) => [key, cleared[key]])), accountValues);
    assert.deepEqual(unexpected, []);
    assert.deepEqual(device.errors, []);
  } finally { await device.context.close(); }
});

test("a new protected-state refresh invalidates an old checkpoint GET even when project and report base are unchanged", async () => {
  resetFixture();
  const releaseOldGet = deferred();
  const oldCheckpoint = savedCheckpoint({ ...originalFields, title: "Before protected refresh" });
  checkpoint = savedCheckpoint({ ...originalFields, title: "After protected refresh" }, 2);
  let firstRead = true;
  checkpointHandler = async (request, res) => {
    if (request.method !== "GET" || !firstRead) return false;
    firstRead = false;
    await releaseOldGet.promise;
    sendJson(res, 200, { status: "saved", checkpoint: oldCheckpoint, current_revision: 1,
      current_base_report_id: baseReport.report_id, current_base_report: baseReport, base_changed: false });
    return true;
  };
  const device = await openDevice();
  try {
    await waitUntil(() => requests.some((request) => request.path === checkpointPath), "pre-refresh GET is held");
    await device.page.evaluate(() => {
      window.preRefreshRead = hydrateSaasListingCloudCheckpoint({ force: true });
      // The actual lifecycle counter advanced by refreshSaasState. Seed that
      // boundary directly so this test does not fake dozens of unrelated APIs.
      saasStateRefreshGeneration += 1;
      document.querySelector("#view-product").innerHTML = renderSaasListingDraftEditor();
    });
    releaseOldGet.resolve();
    assert.equal(await device.page.evaluate(() => window.preRefreshRead), false,
      "same project/base cannot make a response from an older protected-state refresh current");
    await device.page.evaluate(() => ensureSaasListingCloudCheckpoint());
    await waitUntil(() => requests.filter((request) => request.path === checkpointPath).length >= 2, "new refresh gets a fresh checkpoint read");
    await device.page.waitForFunction(() => document.querySelector('[data-saas-listing-draft-field="title"]').value === "After protected refresh", null, { timeout: 5000 });
    assert.equal(requests.filter((request) => request.method === "POST").length, 0);
    assert.deepEqual(unexpected, []);
    assert.deepEqual(device.errors, []);
  } finally {
    releaseOldGet.resolve();
    await device.context.close();
  }
});

for (const width of [1440, 1024]) {
  test(`styled Listing renderer at ${width}px keeps saved/conflict status readable and merchant-facing`, async () => {
    resetFixture();
    const device = await openDevice({ visual: true, width });
    const evidenceDir = fs.mkdtempSync(path.join(os.tmpdir(), `jiejing-checkpoint-ui-${width}-`));
    try {
      assert.equal(new URL(device.page.url()).origin, base);
      assert.match(await device.page.title(), /捷境|JIEJING|Jiejing/i);
      await device.page.evaluate(() => hydrateSaasListingCloudCheckpoint({ force: true }));
      const editor = device.page.locator(".saas-listing-v2-draft-editor");
      assert.equal(await editor.isVisible(), true);
      assert.equal(await editor.locator("[data-saas-listing-draft-field]").count(), 8);
      await editor.locator('[data-saas-listing-draft-field="title"]').fill("Foldable Tablet Stand for Desk Use");
      await device.page.waitForFunction(() => document.querySelector("[data-saas-listing-cloud-status]").textContent.includes("已云端保存"), null, { timeout: 8000 });
      const savedPath = path.join(evidenceDir, "saved.png");
      await editor.screenshot({ path: savedPath });
      checkpoint = savedCheckpoint({ ...checkpoint.fields, title: "Updated on another device", category: "",
        images: `https://assets.example.invalid/products/${"long-product-photo-path-".repeat(22)}image.jpg` }, 2);
      await editor.locator('[data-saas-listing-draft-field="title"]').fill("Local text retained for review");
      await device.page.evaluate(() => hydrateSaasListingCloudCheckpoint({ force: true }));
      const status = editor.locator("[data-saas-listing-cloud-status]");
      assert.match(await status.textContent(), /检测到其他更新/);
      const details = status.locator("details").first();
      await details.locator("summary").click();
      const conflictPath = path.join(evidenceDir, "conflict-details.png");
      await editor.screenshot({ path: conflictPath });
      console.log(JSON.stringify({ ui_evidence: { width, saved: savedPath, conflict: conflictPath,
        page_error_count: device.errors.length, console_issue_count: device.consoleIssues.length } }));
      assert.doesNotMatch(await details.innerText(), /"(?:title|selling_points|description|category|item_specifics|keywords|price|images|logistics|risk_notes)"\s*:/,
        "merchant conflict details use Chinese field labels, not an internal JSON object");
      const layout = await status.evaluate((element) => ({ scroll: element.scrollWidth, client: element.clientWidth,
        left: element.getBoundingClientRect().left, right: element.getBoundingClientRect().right, viewport: innerWidth }));
      assert.ok(layout.scroll <= layout.client + 1, `long cloud image URLs must wrap inside the status panel: ${JSON.stringify(layout)}`);
      assert.ok(layout.left >= 0 && layout.right <= layout.viewport + 1, `status stays within the ${width}px viewport`);
      for (const action of ["use-cloud", "keep-local"]) assert.equal(await status.locator(`[data-saas-listing-cloud-action="${action}"]`).isVisible(), true);
      await status.locator('[data-saas-listing-cloud-action="use-cloud"]').click();
      await device.page.waitForFunction(() => !document.querySelector('[data-saas-listing-cloud-action="use-cloud"]'));
      const backup = status.locator("details").filter({ hasText: "查看保留的本机副本" });
      await backup.locator("summary").click();
      const backupPath = path.join(evidenceDir, "local-backup.png");
      await editor.screenshot({ path: backupPath });
      console.log(JSON.stringify({ ui_evidence: { width, local_backup: backupPath } }));
      assert.match(await backup.innerText(), /Local text retained for review/);
      assert.doesNotMatch(await backup.innerText(), /"(?:title|selling_points|description|category|item_specifics|keywords|price|images|logistics|risk_notes)"\s*:/);
      assert.deepEqual(unexpected, []);
      assert.deepEqual(device.errors, []);
      assert.deepEqual(device.consoleIssues, []);
    } finally { await device.context.close(); }
  });
}

test("manual specifications and logistics override stale content while account policy and location keys stay unchanged", async () => {
  resetFixture();
  const device = await openDevice();
  try {
    await device.page.evaluate(() => hydrateSaasListingCloudCheckpoint({ force: true }));
    await device.page.evaluate(() => {
      state.saasListingComposerDraft.source_type = "merchant_input";
      state.saasListingComposerDraft.publish_prefill = { material: "Aluminum", item_location: "US",
        package_weight_g: "500", package_length_cm: "10", package_width_cm: "12", package_height_cm: "2",
        merchant_location_key: "keep-location-key", fulfillment_policy_id: "keep-fulfillment",
        payment_policy_id: "keep-payment", return_policy_id: "keep-return" };
    });
    await device.page.locator('[data-saas-listing-draft-field="item_specifics"]').fill("Material: Steel");
    await device.page.locator('[data-saas-listing-draft-field="logistics"]').fill("实际发货地: GB\n包装重量: 800g\n包装尺寸: 30 x 20 x 10 cm");
    const actual = await device.page.evaluate(() => saasPublishIntakePrefillValues("实际发货地: US\n包装重量: 500g\n包装尺寸: 10 x 12 x 2 cm"));
    const contentKeys = ["material", "item_location", "package_weight_g", "package_length_cm", "package_width_cm", "package_height_cm"];
    assert.deepEqual(Object.fromEntries(contentKeys.map((key) => [key, actual[key]])),
      { material: "Steel", item_location: "GB", package_weight_g: "800", package_length_cm: "30", package_width_cm: "20", package_height_cm: "10" });
    const accountExpected = { merchant_location_key: "keep-location-key", fulfillment_policy_id: "keep-fulfillment",
      payment_policy_id: "keep-payment", return_policy_id: "keep-return" };
    assert.deepEqual(Object.fromEntries(Object.keys(accountExpected).map((key) => [key, actual[key]])), accountExpected);
    await device.page.locator('[data-saas-listing-draft-field="item_specifics"]').fill("");
    await device.page.locator('[data-saas-listing-draft-field="logistics"]').fill("");
    const cleared = await device.page.evaluate(() => saasPublishIntakePrefillValues("实际发货地: US\n包装重量: 500g\n包装尺寸: 10 x 12 x 2 cm"));
    assert.deepEqual(Object.fromEntries(contentKeys.map((key) => [key, cleared[key]])), Object.fromEntries(contentKeys.map((key) => [key, ""])),
      "clear cannot revive old publish hints or the original composer prompt");
    assert.deepEqual(Object.fromEntries(Object.keys(accountExpected).map((key) => [key, cleared[key]])), accountExpected);
    assert.deepEqual(unexpected, []);
    assert.deepEqual(device.errors, []);
  } finally { await device.context.close(); }
});

test("a checkpoint from an older base keeps its conflict copy separate while current-base state and editor stay identical", async () => {
  resetFixture();
  const newerBase = structuredClone(baseReport);
  newerBase.report_id = "base-after-new-facts"; newerBase.created_at = "2026-09-06T04:00:00Z";
  newerBase.report.listing_handoff.listing_fields.title = "Current base generated title";
  newerBase.report.merchant_product_fact_packet = { source: "backend_product_vision_extraction",
    vision_contract_version: "jiejing_ai_ceo_product_vision_intake_v1", product_name: "Foldable Tablet Stand",
    source_confirmed_facts: {}, merchant_confirmed_facts: { product_name: "Foldable Tablet Stand", material: "Steel" },
    unknown_facts: ["sku"], fact_conflicts: [], simulation_only: false,
    buyer_copy_requires_validated_listing_generation: true };
  const oldCheckpoint = savedCheckpoint({ ...originalFields, title: "Previous-base cloud edit" });
  checkpointHandler = async (request, res) => {
    if (request.method !== "GET") return false;
    sendJson(res, 200, { status: "saved", checkpoint: oldCheckpoint, current_revision: 1,
      current_base_report_id: newerBase.report_id, current_base_report: newerBase, base_changed: true });
    return true;
  };
  const device = await openDevice();
  try {
    await device.page.evaluate(() => hydrateSaasListingCloudCheckpoint({ force: true }));
    assert.equal(await device.page.evaluate(() => state.saasListingComposerDraft.fields.title), "Current base generated title");
    assert.equal(await device.page.locator('[data-saas-listing-draft-field="title"]').inputValue(), "Current base generated title",
      "restoring newer report state must update the actual editable controls, not only the JS object");
    const status = device.page.locator("[data-saas-listing-cloud-status]");
    assert.match(await status.textContent(), /Previous-base cloud edit/, "previous cloud edit remains available for review");
    assert.match(await status.locator("details").first().locator("summary").textContent(), /之前.*云端|旧.*云端|上次.*云端/,
      "an old-base checkpoint is not described as the current cloud version");
    assert.match(await status.locator('[data-saas-listing-cloud-action="use-cloud"]').textContent(), /最新.*(?:资料|版本)/,
      "the action explains it will use the newest report, not the previous-base copy in the detail");
    await status.locator('[data-saas-listing-cloud-action="use-cloud"]').click();
    await device.page.waitForFunction(() => !document.querySelector('[data-saas-listing-cloud-action="use-cloud"]'));
    assert.equal(await device.page.locator('[data-saas-listing-draft-field="title"]').inputValue(), "Current base generated title");
    assert.equal(await device.page.evaluate(() => saasPublishIntakePrefillValues("").title), "Current base generated title",
      "selecting the newly validated vision-origin report must not turn it into ungenerated manual copy or force another AI run");
    assert.equal(requests.filter((request) => request.method === "POST").length, 0);
    assert.deepEqual(unexpected, []);
    assert.deepEqual(device.errors, []);
  } finally { await device.context.close(); }
});

test("draft heading follows restored and edited title without resurrecting old text or interpreting HTML", async () => {
  resetFixture();
  checkpoint = savedCheckpoint({ ...originalFields, title: "Gold-Tone Measuring Set" });
  const device = await openDevice();
  try {
    await device.page.evaluate(() => hydrateSaasListingCloudCheckpoint({ force: true }));
    const heading = device.page.locator('.saas-listing-v2-draft-head > div > strong');
    assert.equal(await heading.textContent(), "Gold-Tone Measuring Set", "cloud restore must update heading and input together");
    const literal = '<img src=x onerror="throw 1"> Gold set';
    await device.page.locator('[data-saas-listing-draft-field="title"]').fill(literal);
    assert.equal(await heading.textContent(), literal, "typing updates the heading as text, not markup");
    assert.equal(await heading.locator('img').count(), 0);
    await device.page.evaluate(() => { document.querySelector('#view-product').innerHTML = renderSaasListingDraftEditor(); });
    assert.equal(await heading.textContent(), literal, "a full rerender uses the current field too");
    assert.equal(await heading.locator('img').count(), 0);
    await device.page.locator('[data-saas-listing-draft-field="title"]').fill('');
    assert.equal(await heading.textContent(), "尚未填写标题", "clearing must not resurrect the generated title");
    await device.page.evaluate(() => { document.querySelector('#view-product').innerHTML = renderSaasListingDraftEditor(); });
    assert.equal(await heading.textContent(), "尚未填写标题");
    assert.deepEqual(unexpected, []);
    assert.deepEqual(device.errors, []);
  } finally { await device.context.close(); }
});

test("clearing the visible fallback title of a legacy draft with no title field creates an explicit empty checkpoint", async () => {
  resetFixture();
  const device = await openDevice();
  try {
    await device.page.evaluate(() => hydrateSaasListingCloudCheckpoint({ force: true }));
    await device.page.evaluate(() => {
      delete state.saasListingComposerDraft.fields.title;
      state.saasListingComposerDraft.title = "Legacy visible fallback title";
      document.querySelector("#view-product").innerHTML = renderSaasListingDraftEditor();
    });
    assert.equal(await device.page.locator('[data-saas-listing-draft-field="title"]').inputValue(), "Legacy visible fallback title");
    await device.page.locator('[data-saas-listing-draft-field="title"]').fill("");
    await waitUntil(() => requests.some((request) => request.method === "POST"),
      "clearing displayed fallback text is a real merchant edit, not an unchanged missing value");
    const post = requests.find((request) => request.method === "POST");
    assert.equal(post.body.fields.title, "");
    assert.ok(post.body.merchant_edited_fields.includes("title"));
    assert.equal(await device.page.locator('[data-saas-listing-draft-field="title"]').inputValue(), "");
    assert.deepEqual(unexpected, []);
    assert.deepEqual(device.errors, []);
  } finally { await device.context.close(); }
});

test("a real publish form snapshot preserves its current form but cannot override later Listing edits or another project", async () => {
  resetFixture();
  const device = await openDevice();
  try {
    await device.page.evaluate(() => hydrateSaasListingCloudCheckpoint({ force: true }));
    await device.page.evaluate(() => {
      const host = document.createElement("div"); host.id = "checkpoint-intake-fixture";
      host.innerHTML = renderSaasPublishConfirmationIntakePanel(undefined, { includeGuide: false });
      document.body.append(host);
    });
    await device.page.locator('#saasPublishIntakeForm [name="title"]').fill("Earlier publish-form title");
    await device.page.locator('#saasPublishIntakeForm [name="price"]').fill("88.00");
    await device.page.evaluate(() => {
      // The exact local capture/setup used before the inventory confirmation
      // request. No confirmation, inventory, or other platform API is called.
      saasPendingPublishIntakeFormValues = snapshotSaasPublishIntakeFormValues();
      document.querySelector("#checkpoint-intake-fixture").remove();
    });
    assert.equal(await device.page.evaluate(() => saasPublishIntakePrefillValues("").title), "Earlier publish-form title",
      "the snapshot still serves its original unmodified project/form context");
    await device.page.locator('[data-saas-listing-draft-field="title"]').fill("Later Listing editor title");
    await device.page.locator('[data-saas-listing-draft-field="price"]').fill("35.50 USD");
    const afterEdit = await device.page.evaluate(() => saasPublishIntakePrefillValues(""));
    assert.equal(afterEdit.title, "Later Listing editor title", "older form capture cannot cover a newer real Listing input");
    assert.equal(afterEdit.price, "35.50");
    await device.page.evaluate(({ baseReport, otherReport }) => {
      state.saasReports = [baseReport, otherReport];
      state.saasTasks = [baseReport, otherReport].map((report) => ({ task_id: report.task_id,
        company_id: report.company_id, store_id: report.store_id, task_type: "listing_draft_generation",
        status: "completed", updated_at: report.created_at,
        input: { product: report.report.product, listing_project_identity: report.report.listing_project_identity } }));
      openSaasRecentProductTask(otherReport.task_id);
    }, { baseReport, otherReport });
    const afterSwitch = await device.page.evaluate(() => saasPublishIntakePrefillValues(""));
    assert.equal(afterSwitch.title, "Other project title", "project B cannot borrow A's form snapshot");
    assert.notEqual(afterSwitch.price, "88.00");
    assert.deepEqual(unexpected, []);
    assert.deepEqual(device.errors, []);
  } finally { await device.context.close(); }
});

test("choosing the newest base remembers only that local base/revision choice and asks again when either changes", async () => {
  resetFixture();
  let latestBase = structuredClone(baseReport);
  latestBase.report_id = "choice-base-B"; latestBase.created_at = "2026-09-06T05:00:00Z";
  latestBase.report.listing_handoff.listing_fields.title = "Latest B title";
  let olderHead = savedCheckpoint({ ...originalFields, title: "Older A edit kept for viewing" });
  checkpointHandler = async (request, res) => {
    if (request.method !== "GET") return false;
    sendJson(res, 200, { status: "saved", checkpoint: olderHead, current_revision: olderHead.revision,
      current_base_report_id: latestBase.report_id, current_base_report: latestBase, base_changed: true });
    return true;
  };
  const device = await openDevice();
  try {
    await device.page.evaluate(() => hydrateSaasListingCloudCheckpoint({ force: true }));
    await device.page.locator('[data-saas-listing-cloud-action="use-cloud"]').click();
    await device.page.waitForFunction(() => !document.querySelector('[data-saas-listing-cloud-action="use-cloud"]'));
    assert.doesNotMatch(await device.page.locator("[data-saas-listing-cloud-status]").textContent(), /已云端保存/,
      "choosing a report is not a new cloud checkpoint save");
    await device.page.evaluate(() => hydrateSaasListingCloudCheckpoint({ force: true }));
    assert.equal(await device.page.locator('[data-saas-listing-cloud-action="use-cloud"]').count(), 0,
      "the same local base/revision choice is not presented as a new conflict on every GET");
    assert.match(await device.page.locator("[data-saas-listing-cloud-status]").textContent(), /Older A edit kept for viewing/,
      "acknowledging the latest base must not hide or discard the previous cloud edit");
    olderHead = savedCheckpoint({ ...originalFields, title: "New old-base revision needs review" }, 2);
    await device.page.evaluate(() => hydrateSaasListingCloudCheckpoint({ force: true }));
    assert.equal(await device.page.locator('[data-saas-listing-cloud-action="use-cloud"]').count(), 1, "new checkpoint revision needs a fresh choice");
    await device.page.locator('[data-saas-listing-cloud-action="use-cloud"]').click();
    await device.page.waitForFunction(() => !document.querySelector('[data-saas-listing-cloud-action="use-cloud"]'));
    latestBase = structuredClone(latestBase);
    latestBase.report_id = "choice-base-C"; latestBase.created_at = "2026-09-06T06:00:00Z";
    latestBase.report.listing_handoff.listing_fields.title = "Latest C title";
    await device.page.evaluate(() => hydrateSaasListingCloudCheckpoint({ force: true }));
    assert.equal(await device.page.locator('[data-saas-listing-cloud-action="use-cloud"]').count(), 1, "new report base needs a fresh choice even at the same checkpoint revision");
    assert.equal(requests.filter((request) => request.method === "POST").length, 0);
    assert.deepEqual(unexpected, []);
    assert.deepEqual(device.errors, []);
  } finally { await device.context.close(); }
});

test("Unicode characters at Listing field limits remain whole in the actual saved DTO", async () => {
  resetFixture();
  const device = await openDevice();
  try {
    await device.page.evaluate(() => hydrateSaasListingCloudCheckpoint({ force: true }));
    const category = `${"a".repeat(799)}😀`, description = `${"b".repeat(1399)}😀`;
    const literalTitle = "样例 / 测试草稿 / Hermes", literalUrl = "https://assets.example.invalid/Hermes/sample.jpg";
    await device.page.locator('[data-saas-listing-draft-field="category"]').fill(category);
    await device.page.locator('[data-saas-listing-draft-field="description"]').fill(description);
    await device.page.locator('[data-saas-listing-draft-field="title"]').fill(literalTitle);
    await device.page.locator('[data-saas-listing-draft-field="images"]').fill(literalUrl);
    await device.page.evaluate(() => flushSaasListingCloudCheckpoint());
    const post = requests.find((request) => request.method === "POST");
    assert.ok(post, "real input must submit the complete field DTO");
    assert.equal(post.body.fields.category, category, "800 Unicode code points must not be cut into a lone surrogate");
    assert.equal(post.body.fields.description, description, "the 1400-character description limit uses the same complete-character rule");
    assert.equal([...post.body.fields.category].length, 800);
    assert.equal([...post.body.fields.description].length, 1400);
    assert.equal(post.body.fields.title, literalTitle, "merchant literal text is not product-interface copy to rewrite");
    assert.equal(post.body.fields.images, literalUrl, "saving a source URL must not rewrite its path as product-interface copy");
    assert.deepEqual(unexpected, []);
    assert.deepEqual(device.errors, []);
  } finally { await device.context.close(); }
});

test("cloud latest-base restoration never borrows a same-key report with a different source or candidate", async () => {
  for (const anchor of ["candidate_id", "source_report_id"]) {
    resetFixture();
    const releaseGet = deferred();
    const latestA = structuredClone(baseReport);
    latestA.report_id = "latest-exact-A"; latestA.created_at = "2026-09-06T06:00:00Z";
    latestA.report.listing_handoff.listing_fields.title = "Latest exact-identity A title";
    const foreign = structuredClone(latestA);
    foreign.report_id = "newer-foreign-anchor"; foreign.created_at = "2026-09-06T07:00:00Z";
    foreign.report.listing_project_identity[anchor] = "different-anchor";
    foreign.report.listing_handoff.listing_fields.title = "FOREIGN ANCHOR COPY MUST NOT APPEAR";
    const oldCheckpoint = savedCheckpoint({ ...originalFields, title: "Older exact A merchant edit" });
    checkpointHandler = async (request, res) => {
      if (request.method !== "GET") return false;
      await releaseGet.promise;
      sendJson(res, 200, { status: "saved", checkpoint: oldCheckpoint, current_revision: 1,
        current_base_report_id: latestA.report_id, current_base_report: latestA, base_changed: true });
      return true;
    };
    const device = await openDevice();
    try {
      await device.page.evaluate((foreign) => {
        state.saasReports.push(foreign);
        window.exactScopeRead = hydrateSaasListingCloudCheckpoint({ force: true });
      }, foreign);
      releaseGet.resolve();
      await device.page.evaluate(() => window.exactScopeRead);
      const actualIdentity = await device.page.evaluate(() => state.saasListingComposerDraft.listing_project_identity);
      assert.deepEqual(actualIdentity, identity, `${anchor}: cloud restore must preserve every current identity anchor, not merely the shared project key`);
      assert.equal(await device.page.locator('[data-saas-listing-draft-field="title"]').inputValue(), "Latest exact-identity A title", anchor);
      assert.doesNotMatch(await device.page.locator("#view-product").textContent(), /FOREIGN ANCHOR COPY MUST NOT APPEAR/);
      assert.equal(requests.filter((request) => request.method === "POST").length, 0);
      assert.deepEqual(unexpected, []);
      assert.deepEqual(device.errors, []);
    } finally {
      releaseGet.resolve();
      await device.context.close();
    }
  }
});

test("explicit empty project anchors never match a newer report whose identity anchors are missing", async () => {
  resetFixture();
  const emptyIdentity = { key: identity.key, source_report_id: "", candidate_id: "" };
  const exactBase = structuredClone(baseReport);
  exactBase.report.listing_project_identity = emptyIdentity;
  const missingAnchors = structuredClone(exactBase);
  missingAnchors.report_id = "newer-missing-anchor-report";
  missingAnchors.created_at = "2026-09-06T07:00:00Z";
  missingAnchors.report.listing_project_identity = { key: identity.key };
  missingAnchors.report.listing_handoff.listing_fields.title = "MISSING ANCHOR COPY MUST NOT APPEAR";
  checkpointHandler = async (request, res) => {
    if (request.method === "GET") {
      sendJson(res, 200, { status: "empty", checkpoint: null, current_revision: 0,
        current_base_report_id: exactBase.report_id, current_base_report: exactBase, base_changed: false });
    } else {
      checkpoint = { ...savedCheckpoint(request.body.fields), listing_project_identity: emptyIdentity,
        mutation_id: request.body.mutation_id, merchant_edited_fields: request.body.merchant_edited_fields };
      sendJson(res, 201, { status: "saved", checkpoint, idempotent_replay: false,
        model_called: false, usage_consumed: false, real_platform_writes_enabled: false, secret_exposed: false });
    }
    return true;
  };
  const device = await openDevice({ identity: emptyIdentity, baseReport: exactBase });
  try {
    await device.page.evaluate(() => hydrateSaasListingCloudCheckpoint({ force: true }));
    await device.page.evaluate((missingAnchors) => state.saasReports.push(missingAnchors), missingAnchors);
    assert.equal(await device.page.evaluate(() => saasListingCloudBaseReport(saasListingCloudContext())?.report_id),
      exactBase.report_id, "missing raw identity properties are not explicit empty anchors or eligible report bases");
    assert.equal(await device.page.evaluate(() => hydrateSaasListingCloudCheckpoint({ force: true })), true);
    await device.page.locator('[data-saas-listing-draft-field="title"]').fill("Merchant edit with explicit empty anchors");
    await device.page.evaluate(() => flushSaasListingCloudCheckpoint());
    const post = requests.find((request) => request.method === "POST");
    assert.ok(post, "a malformed newer report must not permanently block cloud saving");
    assert.deepEqual(post.body.listing_project_identity, emptyIdentity);
    assert.equal(post.body.base_report_id, exactBase.report_id);
    assert.deepEqual(requests.find((request) => request.method === "GET" && request.path === checkpointPath).query,
      { source_report_id: "", candidate_id: "" });
    assert.doesNotMatch(await device.page.locator("#view-product").textContent(), /MISSING ANCHOR COPY MUST NOT APPEAR/);
    assert.deepEqual(unexpected, []);
    assert.deepEqual(device.errors, []);
  } finally { await device.context.close(); }
});
