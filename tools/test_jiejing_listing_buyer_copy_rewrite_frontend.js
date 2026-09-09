#!/usr/bin/env node
"use strict";

// Full product functions and native DOM actions against one owned HTTP server.
// Only external responses are fixtures. No model, credentials or platform runs.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const http = require("node:http");
const os = require("node:os");
const path = require("node:path");
const { test, before, after } = require("node:test");
const { chromium } = require("../output/codex-playwright-deps/node_modules/playwright-core");
const root = path.resolve(__dirname, "..");
const companyId = "rewrite-company", userId = "rewrite-owner", storeId = "rewrite-store";
const identity = { key: "rewrite-tablet", source_report_id: "rewrite-source", candidate_id: "tablet" };
const checkpointPath = `/stores/${storeId}/listing-drafts/${identity.key}/checkpoint`;
const generationPath = `/stores/${storeId}/listing-drafts/generate`;
const generationStatusPath = `/stores/${storeId}/listing-drafts/${identity.key}/generation-status`;
const fieldKeys = ["title", "selling_points", "description", "category", "item_specifics", "keywords", "price", "images", "logistics", "risk_notes"];
const copyKeys = ["title", "selling_points", "description"];
const previousFields = { title: "可折叠平板支架", selling_points: "铝合金\n折叠收纳\n桌面使用", description: "商家原来的中文商品介绍",
  category: "", item_specifics: "Material: Aluminum", keywords: "", price: "29.00 USD", images: "https://example.invalid/owned.jpg",
  logistics: "Merchant shipping terms", risk_notes: "" };
const nextFields = { ...previousFields, title: "Foldable Aluminum Tablet Stand", selling_points: "Aluminum construction\nFoldable design\nFor desktop use", description: "An aluminum tablet stand with a folding design for desktop use." };
const sourceUnavailableFailure = { status: "blocked", failure_code: "listing_rewrite_source_unavailable",
  blocked_by: ["listing_rewrite_source_unavailable"],
  merchant_message: "原稿或商品资料已变化，或云端保存暂不可用；请核对后再重写。现有文案未被替换。",
  model_called: false, usage_consumed: false, report: null,
  real_platform_writes_enabled: false, secret_exposed: false };
const factPacket = { contract_version: "merchant_product_fact_packet_v1", product_name: "Foldable Tablet Stand",
  merchant_confirmed_facts: { product_name: "Foldable Tablet Stand", material: "Aluminum", condition: "NEW" },
  source_confirmed_facts: {}, derived_listing_suggestions: {}, unknown_facts: [], fact_conflicts: [], simulation_only: true };
const originalReport = { report_id: "rewrite-original-report", task_id: "rewrite-task", report_type: "listing.package",
  company_id: companyId, store_id: storeId, status: "saved", runtime_run_id: "listing_draft_generation", created_at: "2026-09-09T01:00:00Z",
  report: { contract_version: "listing_ai_draft_generation_v1", product: "Foldable Tablet Stand", listing_project_identity: identity,
    merchant_product_fact_packet: factPacket, listing_handoff: { ready_for_listing_draft: true, source_mode: "project_scoped_live_model",
      target_report_type: "listing.package", listing_fields: { title: previousFields.title, selling_points: previousFields.selling_points.split("\n"),
        description_seed: previousFields.description, merchant_product_fact_packet: factPacket } } } };
const rewriteReport = { ...originalReport, report_id: "rewrite-generated-report", created_at: "2026-09-09T02:00:00Z",
  report: { ...originalReport.report, listing_handoff: { ...originalReport.report.listing_handoff,
    listing_fields: { ...originalReport.report.listing_handoff.listing_fields, title: nextFields.title,
      selling_points: nextFields.selling_points.split("\n"), description_seed: nextFields.description,
      buyer_copy_rewrite: { contract_version: "listing_buyer_copy_rewrite_v1", previous_fields: previousFields, fields: nextFields,
        expected_base_report_id: "rewrite-original-report", expected_checkpoint_revision: 1,
        previous_merchant_edited_fields: ["title", "selling_points", "description", "price"], merchant_edited_fields: ["price"] } } } } };
let server, browser, base, head, currentBase, requests, unexpected, generationHandler, generationStatusHandler, checkpointHandler, supersededIds;
function reset() { head = null; currentBase = originalReport; requests = []; unexpected = []; generationHandler = null; generationStatusHandler = null; checkpointHandler = null; supersededIds = []; }
function json(res, status, body) { res.writeHead(status, { "content-type": "application/json", "cache-control": "no-store" }); res.end(JSON.stringify(body)); }
function checkpoint(fields, revision, mutation, reportId = currentBase.report_id) { return { checkpoint_id: `rewrite-edit-${revision}`, revision,
  mutation_id: mutation, company_id: companyId, store_id: storeId, listing_project_identity: identity, base_report_id: reportId,
  fields: { ...fields }, merchant_edited_fields: ["price"], saved_at: "2026-09-09T03:00:00Z", source: "merchant_edit" }; }
function deferred() { let resolve; const promise = new Promise((done) => { resolve = done; }); return { promise, resolve }; }
function unregisteredResult(operationId) { return { contract_version: "listing_generation_operation_v1", operation_id: operationId,
  task_id: "unregistered-task", company_id: companyId, user_id: userId, store_id: storeId, listing_project_identity: identity,
  generation_mode: null, expected_base_report_id: null, expected_checkpoint_revision: null, status: "not_found", can_retry: false,
  report: null, failure_code: "", message: "尚未登记", model_called: null, usage_consumed: null, report_save_attempted: null,
  real_platform_writes_enabled: false, secret_exposed: false }; }
before(async () => {
  const source = fs.readFileSync(path.join(root, "app.js"), "utf8");
  const boot = /exposeLocalJiejingTestHooks\(\);\r?\ninit\(\);\r?\nrunLocalJiejingQaScenarioFromUrl\(\);\s*$/;
  assert.match(source, boot);
  const app = source.replace(boot, "exposeLocalJiejingTestHooks();\n");
  const styledHtml = fs.readFileSync(path.join(root, "app.html"), "utf8").replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, "")
    .replace(/<link\b[^>]*>/gi, "").replace(/<img\b[^>]*>/gi, "")
    .replace("</head>", '<link rel="stylesheet" href="/styles.css"></head>')
    .replace("</body>", '<script src="/app.js"></script></body>');
  const html = styledHtml.replace(/<style\b[^>]*>[\s\S]*?<\/style>/gi, "").replace(/<link\b[^>]*>/gi, "");
  server = http.createServer(async (req, res) => {
    const url = new URL(req.url, "http://127.0.0.1");
    if (req.method === "GET" && ["/app.html", "/app.js"].includes(url.pathname)) {
      res.writeHead(200, { "content-type": url.pathname === "/app.js" ? "text/javascript; charset=utf-8" : "text/html; charset=utf-8" });
      return res.end(url.pathname === "/app.js" ? app : url.searchParams.get("visual") === "1" ? styledHtml : html);
    }
    const staticAssets = { "/styles.css": ["styles.css", "text/css; charset=utf-8"],
      "/assets/dashboard-preview.png": ["assets/dashboard-preview.png", "image/png"],
      "/assets/jiejing-app-icon.svg": ["assets/jiejing-app-icon.svg", "image/svg+xml"] };
    if (req.method === "GET" && Object.hasOwn(staticAssets, url.pathname)) {
      const [file, type] = staticAssets[url.pathname]; res.writeHead(200, { "content-type": type }); return res.end(fs.readFileSync(path.join(root, file)));
    }
    if (req.method === "GET" && url.pathname === `/stores/${storeId}/merchant-project-status`) return json(res, 200, { merchant_project_status: null });
    if (![checkpointPath, generationPath, generationStatusPath].includes(url.pathname)) { unexpected.push(`${req.method} ${url.pathname}`); return json(res, 404, {}); }
    let raw = ""; for await (const chunk of req) raw += chunk;
    const request = { method: req.method, path: url.pathname, query: Object.fromEntries(url.searchParams), body: raw ? JSON.parse(raw) : null };
    requests.push(request);
    if (url.pathname === generationStatusPath) {
      if (generationStatusHandler && await generationStatusHandler(request, res)) return;
      return json(res, 404, {});
    }
    if (url.pathname === generationPath && req.method === "POST") {
      if (generationHandler && await generationHandler(request, res)) return;
      currentBase = rewriteReport;
      return json(res, 201, { status: "completed", report: rewriteReport, listing_project_identity: identity, missing_fields: [] });
    }
    if (checkpointHandler && await checkpointHandler(request, res)) return;
    if (req.method === "GET") return json(res, 200, { contract_version: "listing_merchant_edit_v1",
      model_called: false, usage_consumed: false, real_platform_writes_enabled: false, secret_exposed: false,
      status: head ? "saved" : "empty", checkpoint: head,
      current_revision: head?.revision || 0, current_base_report_id: currentBase.report_id, current_base_report: currentBase,
      base_changed: Boolean(head && head.base_report_id !== currentBase.report_id), superseded_rewrite_report_ids: supersededIds });
    if (request.body.expected_revision !== (head?.revision || 0) || request.body.base_report_id !== currentBase.report_id) {
      return json(res, 409, { status: "conflict", current_revision: head?.revision || 0, latest_checkpoint: head,
        current_base_report_id: currentBase.report_id, current_base_report: currentBase });
    }
    head = checkpoint(request.body.fields, (head?.revision || 0) + 1, request.body.mutation_id);
    head.merchant_edited_fields = [...request.body.merchant_edited_fields].sort();
    head.fields = Object.fromEntries(Object.entries(head.fields).reverse());
    return json(res, 201, { status: "saved", checkpoint: head });
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  base = `http://127.0.0.1:${server.address().port}`;
  browser = await chromium.launch({ headless: true, channel: "chrome" });
});
after(async () => { if (browser) await browser.close(); if (server) { server.closeAllConnections(); await new Promise((r) => server.close(r)); } });
async function device(report = originalReport, options = {}) {
  const context = await browser.newContext({ viewport: { width: options.width || 1440, height: 1024 } });
  const page = await context.newPage(), errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.route("**/*", (route) => { if (new URL(route.request().url()).origin === base) return route.continue(); unexpected.push("external"); return route.abort(); });
  await page.goto(`${base}/app.html?start=app&qa=public-saas&view=product&project=${identity.key}${options.visual ? "&visual=1" : ""}`);
  await page.evaluate(({ base, companyId, userId, storeId, identity, report, previousFields, factPacket, visual }) => {
    window.__JIEJING_FORCE_PUBLIC_MVP__ = true;
    localStorage.setItem(saasStorageKeys.storeId, storeId);
    localStorage.setItem(saasStorageKeys.lastAccount, userId);
    localStorage.setItem("jiejing_saas_backend_session_hint", "1"); localStorage.setItem("jiejing_saas_session_hint", "1");
    state.saasApiBase = base; state.saasIdentity = { company_id: companyId, user_id: userId, role: "owner" };
    state.saasCompany = { company_id: companyId }; state.saasUser = { user_id: userId, email: "rewrite@example.invalid" };
    state.saasPermissions = ["create_task", "view_report"]; state.saasProtectedStateReady = true;
    state.saasStores = [{ store_id: storeId, company_id: companyId, marketplace: "EBAY_US", platform: "ebay" }];
    state.saasReports = [report]; state.saasTasks = []; state.view = "product";
    state.saasListingComposerDraft = { product: "Foldable Tablet Stand", title: previousFields.title, listing_project_identity: identity,
      source_report_id: identity.source_report_id, fields: { ...previousFields }, merchant_product_fact_packet: factPacket,
      merchant_edited_fields: ["title", "selling_points", "description", "price"], publish_prefill: { quantity: "7" },
      model_generated: false, safe_local_only: true, simulation_only: true };
    if (report.report_id !== "rewrite-original-report") state.saasListingComposerDraft = saasListingDraftFromReport(report);
    state.saasDetachedListingProjectDrafts = {}; bindEvents();
    document.querySelector("#view-product").innerHTML = renderSaasListingDraftEditor();
    document.querySelector("#view-product").classList.add("is-active");
    if (visual) {
      document.documentElement.classList.add("app-ready"); document.body.classList.add("saas-public-mvp"); document.body.dataset.view = "product";
      document.querySelector("#appShell").classList.remove("is-hidden");
      document.querySelectorAll(".view").forEach((view) => view.classList.toggle("is-active", view.id === "view-product"));
    }
  }, { base, companyId, userId, storeId, identity, report, previousFields, factPacket, visual: options.visual === true });
  await page.evaluate(() => hydrateSaasListingCloudCheckpoint({ force: true }));
  return { page, context, errors };
}

test("editing while the first request is being signed keeps the edit and ends as unsent so an explicit request remains possible", async () => {
  reset(); generationHandler = async (_request, res) => { json(res, 503, sourceUnavailableFailure); return true; };
  const first = await device();
  try {
    await first.page.evaluate(() => {
      const digest = crypto.subtle.digest.bind(crypto.subtle);
      let held = false;
      crypto.subtle.digest = async (...args) => {
        const result = await digest(...args);
        if (!held) { held = true; window.__firstHashEntered = true; await new Promise((resolve) => { window.__releaseFirstHash = resolve; }); }
        return result;
      };
    });
    await first.page.getByRole("button", { name: "让 AI 重写买家文案", exact: true }).click();
    await first.page.waitForFunction(() => window.__firstHashEntered === true);
    const unsentId = await first.page.evaluate(() => state.saasListingComposerDraft.ai_generation_feedback.operation.operation_id);
    await first.page.locator('[data-saas-listing-draft-field="description"]').fill("Merchant changes while signing");
    await first.page.evaluate(() => window.__releaseFirstHash());
    await first.page.waitForFunction(() => !saasListingAiGenerationInFlight.size);
    assert.equal(requests.filter((request) => request.path === generationPath).length, 0);
    assert.equal(await first.page.locator('[data-saas-listing-draft-field="description"]').inputValue(), "Merchant changes while signing");
    assert.equal(await first.page.evaluate(() => state.saasListingComposerDraft.ai_generation_feedback.status), "blocked");
    assert.match(await first.page.locator("[data-saas-listing-ai-feedback]").innerText(), /未调用 AI/);
    await first.page.getByRole("button", { name: "让 AI 重写买家文案", exact: true }).click();
    await first.page.waitForFunction(() => !saasListingAiGenerationInFlight.size);
    assert.equal(requests.filter((request) => request.path === generationPath).length, 1);
    assert.notEqual(requests.find((request) => request.path === generationPath).body.operation_id, unsentId);
    assert.deepEqual(first.errors, []); assert.deepEqual(unexpected, []);
  } finally { await first.page.evaluate(() => window.__releaseFirstHash?.()); await first.context.close(); }
});

test("continuing an unregistered request reads a changed checkpoint without absorbing or overwriting it", async () => {
  reset();
  generationHandler = async (_request, res) => { json(res, 400, { status: "blocked", failure_code: "listing_generation_operation_invalid",
    model_called: false, usage_consumed: false, report: null }); return true; };
  generationStatusHandler = async (request, res) => { json(res, 200, { contract_version: "listing_generation_operation_v1",
    operation_id: request.query.operation_id, task_id: "unregistered-operation-task", company_id: companyId, user_id: userId, store_id: storeId,
    listing_project_identity: identity, generation_mode: null, expected_base_report_id: null, expected_checkpoint_revision: null,
    status: "not_found", can_retry: false, report: null, failure_code: "", message: "尚未找到本次生成。",
    model_called: null, usage_consumed: null, report_save_attempted: null, real_platform_writes_enabled: false, secret_exposed: false }); return true; };
  const first = await device();
  try {
    await first.page.getByRole("button", { name: "让 AI 重写买家文案", exact: true }).click();
    await first.page.waitForFunction(() => state.saasListingComposerDraft.ai_generation_feedback?.status === "generation_uncertain");
    await first.page.getByRole("button", { name: "核对本次结果", exact: true }).click();
    await first.page.waitForFunction(() => state.saasListingComposerDraft.ai_generation_feedback?.resume_available === true);
    const before = await first.page.evaluate(() => ({ fields: state.saasListingComposerDraft.fields,
      record: { revision: saasListingCloudRecord().revision, base: saasListingCloudRecord().baseReportId, seq: saasListingCloudRecord().seq },
      reports: state.saasReports.map((report) => report.report_id) }));
    head = { ...head, revision: 2, fields: { ...head.fields, title: "Other device newer title" } };
    await first.page.getByRole("button", { name: "继续本次生成", exact: true }).click();
    await first.page.waitForFunction(() => !state.saasListingComposerDraft.ai_generation_feedback?.checking);
    assert.deepEqual(await first.page.evaluate(() => ({ fields: state.saasListingComposerDraft.fields,
      record: { revision: saasListingCloudRecord().revision, base: saasListingCloudRecord().baseReportId, seq: saasListingCloudRecord().seq },
      reports: state.saasReports.map((report) => report.report_id) })), before);
    assert.equal(requests.filter((request) => request.path === generationPath).length, 1);
    assert.equal(requests.filter((request) => request.path === checkpointPath && request.method === "POST").length, 1);
    assert.deepEqual(first.errors, []); assert.deepEqual(unexpected, []);
  } finally { await first.context.close(); }
});

test("continuation is single flight and rechecks editing, scope, descriptor, and signatures across awaits", async () => {
  for (const kind of ["double-click", "edit-get", "edit-hash", "scope-hash", "descriptor-get", "signature-get", "refresh-get", "running", "failed"]) {
    reset(); const entered = deferred(), released = deferred();
    generationHandler = async (_request, res) => { json(res, requests.filter((r) => r.path === generationPath).length === 1 ? 400 : kind === "failed" ? 422 : 201, {}); return true; };
    generationStatusHandler = async (request, res) => {
      const count = requests.filter((r) => r.path === generationStatusPath).length;
      if (count === 2) { entered.resolve(); await released.promise; }
      const submitted = requests.find((r) => r.path === generationPath).body;
      const result = unregisteredResult(request.query.operation_id);
      if ((kind === "running" && count === 2) || count === 3) Object.assign(result, {
        generation_mode: "rewrite_buyer_copy", expected_base_report_id: submitted.expected_base_report_id,
        expected_checkpoint_revision: submitted.expected_checkpoint_revision, report_save_attempted: false,
        status: kind === "failed" ? "failed_before_report" : "running", can_retry: kind === "failed",
        model_called: true, usage_consumed: true, failure_code: kind === "failed" ? "listing_model_output_ungrounded_material" : "",
      });
      json(res, 200, result); return true;
    };
    const first = await device();
    try {
      await first.page.getByRole("button", { name: "让 AI 重写买家文案", exact: true }).click();
      await first.page.waitForFunction(() => !saasListingAiGenerationInFlight.size);
      const wire = requests.find((r) => r.path === generationPath).body;
      await first.page.getByRole("button", { name: "核对本次结果", exact: true }).click();
      await first.page.waitForFunction(() => state.saasListingComposerDraft.ai_generation_feedback?.resume_available === true);
      if (kind.endsWith("hash")) await first.page.evaluate(() => {
        const digest = crypto.subtle.digest.bind(crypto.subtle); let held = false;
        crypto.subtle.digest = async (...args) => { const value = await digest(...args);
          if (!held) { held = true; window.__resumeHashEntered = true; await new Promise((resolve) => { window.__resumeHashRelease = resolve; }); } return value; };
      });
      const button = first.page.getByRole("button", { name: "继续本次生成", exact: true });
      if (kind === "double-click") { const box = await button.boundingBox(); await first.page.mouse.dblclick(box.x + box.width / 2, box.y + box.height / 2); }
      else await button.click();
      await entered.promise;
      assert.equal(requests.filter((r) => r.path === generationStatusPath).length, 2, "one action-time read, including double click");
      if (kind === "edit-get") await first.page.locator('[data-saas-listing-draft-field="description"]').fill("Edited during result read");
      if (kind === "descriptor-get") await first.page.evaluate(() => { state.saasListingComposerDraft.ai_generation_feedback.operation.expected_checkpoint_revision += 1; });
      if (kind === "signature-get") await first.page.evaluate(() => { state.saasListingComposerDraft.ai_generation_feedback.request_signature = "e".repeat(64); });
      if (kind === "refresh-get") await first.page.evaluate(() => { saasStateRefreshGeneration += 1; });
      released.resolve();
      if (kind.endsWith("hash")) {
        await first.page.waitForFunction(() => window.__resumeHashEntered);
        if (kind === "edit-hash") await first.page.locator('[data-saas-listing-draft-field="description"]').fill("Edited during request hash");
        else await first.page.evaluate(() => {
          state.saasListingComposerDraft.listing_project_identity = { key: "other-project", source_report_id: "other-source", candidate_id: "other" };
          state.saasListingComposerDraft.ai_generation_feedback = null;
        });
        await first.page.evaluate(() => window.__resumeHashRelease());
      }
      await first.page.waitForFunction(() => !saasListingAiGenerationInFlight.size);
      const sends = requests.filter((r) => r.path === generationPath);
      assert.equal(sends.length, ["double-click", "failed"].includes(kind) ? 2 : 1, kind);
      if (sends.length === 2) assert.deepEqual(sends[1].body, wire);
      if (kind === "failed") assert.equal(await first.page.evaluate(() => state.saasListingComposerDraft.ai_generation_feedback.status), "failed");
      if (kind === "scope-hash") assert.equal(await first.page.evaluate(() => state.saasListingComposerDraft.ai_generation_feedback), null);
      if (kind.startsWith("edit")) assert.equal(await first.page.locator('[data-saas-listing-draft-field="description"]').inputValue(), kind === "edit-get" ? "Edited during result read" : "Edited during request hash");
      assert.deepEqual(first.errors, []); assert.deepEqual(unexpected, []);
    } finally { released.resolve(); await first.page.evaluate(() => window.__resumeHashRelease?.()); await first.context.close(); }
  }
});

test("a damaged request signature remains damaged across actual reload instead of becoming legacy permission", async () => {
  reset(); generationHandler = async (_request, res) => { json(res, 400, {}); return true; };
  generationStatusHandler = async (request, res) => { json(res, 200, unregisteredResult(request.query.operation_id)); return true; };
  const first = await device();
  try {
    await first.page.getByRole("button", { name: "让 AI 重写买家文案", exact: true }).click();
    await first.page.waitForFunction(() => !saasListingAiGenerationInFlight.size);
    await first.page.evaluate(() => { state.saasListingComposerDraft.ai_generation_feedback.request_signature = "damaged-original-proof"; saveSaasProtectedStateSnapshot(); });
    await first.page.reload();
    assert.equal(await first.page.evaluate((base) => {
      window.__JIEJING_FORCE_PUBLIC_MVP__ = true; state.saasApiBase = base;
      const restored = hydrateSaasProtectedStateFromCache();
      state.saasProtectedStateReady = true; state.saasProtectedStateFromCache = false; state.view = "product";
      bindEvents(); renderProductListingCenter(); return restored;
    }, base), true);
    assert.notEqual(await first.page.evaluate(() => state.saasListingComposerDraft.ai_generation_feedback.request_signature), null);
    await first.page.getByRole("button", { name: "核对本次结果", exact: true }).click();
    await first.page.waitForFunction(() => !state.saasListingComposerDraft.ai_generation_feedback.checking);
    assert.equal(await first.page.getByRole("button", { name: "继续本次生成", exact: true }).count(), 0);
    assert.match(await first.page.locator("[data-saas-listing-ai-feedback]").innerText(), /暂时无法安全继续/);
    assert.equal(requests.filter((request) => request.path === generationPath).length, 1);
    assert.deepEqual(await first.page.evaluate(() => state.saasListingComposerDraft.fields), previousFields);
    assert.deepEqual(first.errors, []); assert.deepEqual(unexpected, []);
  } finally { await first.context.close(); }
});

test("legacy default without an original request signature stays protected with an accurate merchant message", async () => {
  reset(); generationHandler = async (_request, res) => { json(res, 400, {}); return true; };
  generationStatusHandler = async (request, res) => { json(res, 200, unregisteredResult(request.query.operation_id)); return true; };
  const first = await device();
  try {
    await first.page.evaluate(() => renderProductListingCenter());
    await first.page.getByRole("button", { name: "AI 生成 Listing 草稿", exact: true }).click();
    await first.page.waitForFunction(() => !saasListingAiGenerationInFlight.size);
    await first.page.evaluate(() => { delete state.saasListingComposerDraft.ai_generation_feedback.request_signature; saveSaasProtectedStateSnapshot(); });
    await first.page.getByRole("button", { name: "核对本次结果", exact: true }).click();
    await first.page.waitForFunction(() => !state.saasListingComposerDraft.ai_generation_feedback.checking);
    assert.equal(await first.page.getByRole("button", { name: "继续本次生成", exact: true }).count(), 0);
    assert.match(await first.page.locator("[data-saas-listing-ai-feedback]").innerText(), /暂时无法安全继续/);
    assert.equal(requests.filter((request) => request.path === generationPath).length, 1);
    assert.equal(await first.page.evaluate(() => state.saasListingComposerDraft.ai_generation_feedback.request_signature), null);
    assert.deepEqual(first.errors, []); assert.deepEqual(unexpected, []);
  } finally { await first.context.close(); }
});

test("the explicit continuation feedback fits desktop and tablet with the real stylesheet", async () => {
  const output = fs.mkdtempSync(path.join(os.tmpdir(), "jiejing-original-operation-ui-"));
  for (const width of [1440, 768]) {
    reset(); generationHandler = async (_request, res) => { json(res, 400, {}); return true; };
    generationStatusHandler = async (request, res) => { json(res, 200, unregisteredResult(request.query.operation_id)); return true; };
    const first = await device(originalReport, { visual: true, width });
    try {
      await first.page.getByRole("button", { name: "让 AI 重写买家文案", exact: true }).click();
      await first.page.waitForFunction(() => !saasListingAiGenerationInFlight.size);
      await first.page.getByRole("button", { name: "核对本次结果", exact: true }).click();
      await first.page.waitForFunction(() => state.saasListingComposerDraft.ai_generation_feedback?.resume_available === true);
      const button = first.page.getByRole("button", { name: "继续本次生成", exact: true });
      await button.scrollIntoViewIfNeeded();
      assert.equal(await button.isVisible(), true);
      assert.equal(await first.page.locator("[data-saas-listing-ai-feedback]").evaluate((node) => node.scrollWidth <= node.clientWidth + 1), true);
      assert.equal(requests.filter((request) => request.path === generationPath).length, 1);
      const screenshot = path.join(output, `continue-operation-${width}.png`);
      await first.page.locator("[data-saas-listing-ai-feedback]").screenshot({ path: screenshot });
      console.log(JSON.stringify({ continuation_ui_evidence: { width, screenshot, stylesheet: "styles.css", app_inline_guards_retained: true } }));
      assert.deepEqual(first.errors, []); assert.deepEqual(unexpected, []);
    } finally { await first.context.close(); }
  }
});

test("signed default cannot continue when only a non-wire price edit mark changes", async () => {
  reset(); head = checkpoint(previousFields, 1, "original-mutation"); head.merchant_edited_fields = [...copyKeys];
  generationHandler = async (_request, res) => { json(res, 400, {}); return true; };
  generationStatusHandler = async (request, res) => { json(res, 200, { contract_version: "listing_generation_operation_v1",
    operation_id: request.query.operation_id, task_id: "unregistered-task", company_id: companyId, user_id: userId, store_id: storeId,
    listing_project_identity: identity, generation_mode: null, expected_base_report_id: null, expected_checkpoint_revision: null,
    status: "not_found", can_retry: false, report: null, failure_code: "", message: "尚未登记",
    model_called: null, usage_consumed: null, report_save_attempted: null, real_platform_writes_enabled: false, secret_exposed: false }); return true; };
  const first = await device();
  try {
    await first.page.evaluate(() => renderProductListingCenter());
    await first.page.getByRole("button", { name: "AI 生成 Listing 草稿", exact: true }).click();
    await first.page.waitForFunction(() => !saasListingAiGenerationInFlight.size);
    const before = await first.page.evaluate(() => saasListingAiGenerationEditSnapshot().draft);
    await first.page.locator('[data-saas-listing-draft-field="price"]').fill(previousFields.price);
    assert.equal(await first.page.evaluate(() => saasListingAiGenerationEditSnapshot().draft), before, "only the edit mark changes");
    assert.deepEqual(requests.find((request) => request.path === generationPath).body.current_draft_fields.merchant_edited_fields, copyKeys);
    assert.ok(await first.page.evaluate(() => saasListingMerchantEditedFields().includes("price")));
    head = { ...head, revision: 2, merchant_edited_fields: [...copyKeys, "price"] };
    await first.page.getByRole("button", { name: "核对本次结果", exact: true }).click();
    await first.page.waitForFunction(() => state.saasListingComposerDraft.ai_generation_feedback?.resume_available === true);
    await first.page.getByRole("button", { name: "继续本次生成", exact: true }).click();
    await first.page.waitForFunction(() => !saasListingAiGenerationInFlight.size);
    assert.equal(requests.filter((request) => request.path === generationPath).length, 1);
    assert.deepEqual(first.errors, []); assert.deepEqual(unexpected, []);
  } finally { await first.context.close(); }
});

test("resume rejects incomplete raw checkpoint evidence even when normalized empty marks look equal", async () => {
  for (const kind of ["missing-marks", "invalid-marks", "duplicate-marks", "wrong-contract", "string-revision", "string-safety"]) {
    reset(); generationHandler = async (_request, res) => { json(res, 400, {}); return true; };
    generationStatusHandler = async (request, res) => { json(res, 200, { contract_version: "listing_generation_operation_v1",
      operation_id: request.query.operation_id, task_id: "unregistered-task", company_id: companyId, user_id: userId, store_id: storeId,
      listing_project_identity: identity, generation_mode: null, expected_base_report_id: null, expected_checkpoint_revision: null,
      status: "not_found", can_retry: false, report: null, failure_code: "", message: "尚未登记",
      model_called: null, usage_consumed: null, report_save_attempted: null, real_platform_writes_enabled: false, secret_exposed: false }); return true; };
    const first = await device();
    try {
      await first.page.evaluate(() => { state.saasListingComposerDraft.merchant_edited_fields = []; });
      await first.page.getByRole("button", { name: "让 AI 重写买家文案", exact: true }).click();
      await first.page.waitForFunction(() => !saasListingAiGenerationInFlight.size);
      await first.page.getByRole("button", { name: "核对本次结果", exact: true }).click();
      await first.page.waitForFunction(() => state.saasListingComposerDraft.ai_generation_feedback.resume_available === true);
      checkpointHandler = async (request, res) => {
        if (request.method !== "GET") return false;
        const payload = { contract_version: "listing_merchant_edit_v1", status: "saved", checkpoint: structuredClone(head),
          current_revision: head.revision, current_base_report_id: currentBase.report_id, current_base_report: currentBase, base_changed: false,
          model_called: false, usage_consumed: false, real_platform_writes_enabled: false, secret_exposed: false };
        if (kind === "missing-marks") delete payload.checkpoint.merchant_edited_fields;
        if (kind === "invalid-marks") payload.checkpoint.merchant_edited_fields = ["not-an-editable-field"];
        if (kind === "duplicate-marks") payload.checkpoint.merchant_edited_fields = ["title", "title"];
        if (kind === "wrong-contract") payload.contract_version = "other_contract";
        if (kind === "string-revision") payload.current_revision = String(head.revision);
        if (kind === "string-safety") payload.model_called = "false";
        json(res, 200, payload); return true;
      };
      await first.page.getByRole("button", { name: "继续本次生成", exact: true }).click();
      await first.page.waitForFunction(() => !saasListingAiGenerationInFlight.size);
      assert.equal(requests.filter((request) => request.path === generationPath).length, 1, kind);
      assert.deepEqual(await first.page.evaluate(() => state.saasListingComposerDraft.fields), previousFields);
      assert.deepEqual(first.errors, []); assert.deepEqual(unexpected, []);
    } finally { await first.context.close(); }
  }
});

test("fact snapshot copy metadata is idempotent across persistence without losing real copy or vision restrictions", async () => {
  reset(); const first = await device();
  try {
    const actualCopy = { title: "Merchant source title", selling_points: ["Foldable", "For desktop use"], description: "Merchant source description." };
    const samples = await first.page.evaluate(({ packet, copy }) => [
      { ...packet }, { ...packet, listing_copy: {} }, { ...packet, listing_copy: copy },
      { ...packet, source: "backend_product_vision_extraction", listing_copy: copy },
    ].map((input) => {
      const once = sanitizeSaasMerchantProductFactPacketSnapshot(input);
      return { once, twice: sanitizeSaasMerchantProductFactPacketSnapshot(once) };
    }), { packet: factPacket, copy: actualCopy });
    for (const [index, sample] of samples.entries()) assert.deepEqual(sample.once, sample.twice, `snapshot sample ${index}`);
    assert.deepEqual(samples[0].once.listing_copy, {}); assert.deepEqual(samples[1].once.listing_copy, {});
    assert.deepEqual(samples[2].once.listing_copy, actualCopy);
    assert.deepEqual(samples[3].once.listing_copy, {});
    assert.equal(samples[3].once.buyer_copy_requires_validated_listing_generation, true);
    assert.deepEqual(first.errors, []); assert.deepEqual(unexpected, []);
  } finally { await first.context.close(); }
});

test("unknown generation keeps an operation identity and explicit result check reads one exact operation without another model call", async () => {
  reset();
  generationHandler = async (_request, res) => {
    res.writeHead(200, { "content-type": "application/json" }); res.end('{"status":'); return true;
  };
  generationStatusHandler = async (request, res) => {
    json(res, 200, { contract_version: "listing_generation_operation_v1", operation_id: request.query.operation_id,
      company_id: companyId, store_id: storeId, user_id: userId, listing_project_identity: identity,
      generation_mode: "rewrite_buyer_copy", expected_base_report_id: originalReport.report_id, expected_checkpoint_revision: 1,
      task_id: "known-failed-task", status: "failed_before_report", report_save_attempted: false, can_retry: true,
      model_called: true, usage_consumed: true, report: null, failure_code: "listing_model_output_ungrounded_material",
      message: "本次文案未通过材质检查，旧稿未被替换。", real_platform_writes_enabled: false, secret_exposed: false });
    return true;
  };
  const first = await device();
  try {
    await first.page.getByRole("button", { name: "让 AI 重写买家文案", exact: true }).click();
    await first.page.waitForFunction(() => state.saasListingComposerDraft.ai_generation_feedback?.status === "generation_uncertain");
    const operation = requests.find((request) => request.path === generationPath).body.operation_id;
    assert.match(operation || "", /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i);
    assert.equal(await first.page.evaluate((id) => Object.values(localStorage).some((value) => value.includes(id)), operation), true);
    await first.page.getByRole("button", { name: "核对本次结果", exact: true }).click();
    await first.page.waitForFunction(() => state.saasListingComposerDraft.ai_generation_feedback?.status === "failed");
    assert.match(await first.page.locator("[data-saas-listing-ai-feedback]").innerText(), /未通过材质检查/);
    assert.deepEqual(requests.filter((request) => request.path === generationStatusPath).map(({ method, query }) => ({ method, query })),
      [{ method: "GET", query: { operation_id: operation, source_report_id: identity.source_report_id, candidate_id: identity.candidate_id } }]);
    assert.equal(requests.filter((request) => request.path === generationPath).length, 1);
    assert.deepEqual(await first.page.evaluate(() => state.saasListingComposerDraft.fields), previousFields);
    assert.deepEqual(first.errors, []); assert.deepEqual(unexpected, []);
  } finally { await first.context.close(); }
});

test("result check adopts the exact saved rewrite through the original revision and never repeats generation", async () => {
  reset();
  generationHandler = async (_request, res) => {
    currentBase = rewriteReport;
    res.writeHead(200, { "content-type": "application/json" }); res.end('{"status":'); return true;
  };
  generationStatusHandler = async (request, res) => {
    json(res, 200, { contract_version: "listing_generation_operation_v1", operation_id: request.query.operation_id,
      company_id: companyId, store_id: storeId, user_id: userId, listing_project_identity: identity,
      generation_mode: "rewrite_buyer_copy", expected_base_report_id: originalReport.report_id, expected_checkpoint_revision: 1,
      task_id: "rewrite-task", status: "report_saved", report_save_attempted: true, can_retry: false,
      model_called: true, usage_consumed: true, report: { ...rewriteReport, user_id: userId }, failure_code: null,
      message: "本次文案已保存。", real_platform_writes_enabled: false, secret_exposed: false });
    return true;
  };
  const first = await device();
  try {
    await first.page.getByRole("button", { name: "让 AI 重写买家文案", exact: true }).click();
    await first.page.waitForFunction(() => state.saasListingComposerDraft.ai_generation_feedback?.status === "generation_uncertain");
    await first.page.getByRole("button", { name: "核对本次结果", exact: true }).click();
    await first.page.waitForFunction((title) => state.saasListingComposerDraft.fields.title === title, nextFields.title, { timeout: 3000 });
    assert.deepEqual(await first.page.evaluate(() => state.saasListingComposerDraft.fields), nextFields);
    assert.equal(head.base_report_id, rewriteReport.report_id); assert.equal(head.revision, 2);
    assert.equal(requests.filter((r) => r.path === generationPath).length, 1);
    assert.deepEqual(requests.filter((r) => r.path === checkpointPath && r.method === "POST").map((r) => r.body.expected_revision), [0, 1]);
    assert.equal(await first.page.evaluate(() => state.saasListingComposerDraft.ai_generation_feedback), null);
    assert.deepEqual(first.errors, []); assert.deepEqual(unexpected, []);
  } finally { await first.context.close(); }
});

test("saved rewrite recovery requires its original signature and preserves changes before or during hashing", async () => {
  for (const kind of ["missing", "malformed", "different", "facts", "copy", "prefill", "hash-edit", "hash-scope"]) {
    reset();
    generationHandler = async (_request, res) => {
      currentBase = rewriteReport;
      res.writeHead(200, { "content-type": "application/json" }); res.end('{"status":'); return true;
    };
    generationStatusHandler = async (request, res) => {
      json(res, 200, { contract_version: "listing_generation_operation_v1", operation_id: request.query.operation_id,
        company_id: companyId, store_id: storeId, user_id: userId, listing_project_identity: identity,
        generation_mode: "rewrite_buyer_copy", expected_base_report_id: originalReport.report_id, expected_checkpoint_revision: 1,
        task_id: "rewrite-task", status: "report_saved", report_save_attempted: true, can_retry: false,
        model_called: true, usage_consumed: true, report: { ...rewriteReport, user_id: userId }, failure_code: null,
        message: "本次文案已保存。", real_platform_writes_enabled: false, secret_exposed: false }); return true;
    };
    const first = await device();
    try {
      await first.page.evaluate(() => {
        const draft = state.saasListingComposerDraft;
        draft.merchant_product_fact_packet = sanitizeSaasMerchantProductFactPacketSnapshot(draft.merchant_product_fact_packet);
      });
      await first.page.getByRole("button", { name: "让 AI 重写买家文案", exact: true }).click();
      await first.page.waitForFunction(() => state.saasListingComposerDraft.ai_generation_feedback?.status === "generation_uncertain");
      const originalSignature = await first.page.evaluate(() => state.saasListingComposerDraft.ai_generation_feedback.input_signature);
      assert.match(originalSignature, /^[a-f0-9]{64}$/);
      if (kind === "copy") await first.page.locator('[data-saas-listing-draft-field="title"]').fill("Merchant copy after generation");
      await first.page.evaluate((kind) => {
        const draft = state.saasListingComposerDraft;
        if (kind === "missing") delete draft.ai_generation_feedback.input_signature;
        if (kind === "malformed") draft.ai_generation_feedback.input_signature = "invalid-signature";
        if (kind === "different") draft.ai_generation_feedback.input_signature = "f".repeat(64);
        if (kind === "facts") draft.merchant_product_fact_packet.merchant_confirmed_facts.material = "Wood";
        if (kind === "prefill") draft.publish_prefill.quantity = "8";
        if (kind.startsWith("hash-")) {
          const nativeDigest = crypto.subtle.digest.bind(crypto.subtle);
          crypto.subtle.digest = async (...args) => {
            const result = await nativeDigest(...args); // Preserve the real hash; delay only its acknowledgement.
            window.__rewriteHashEntered = true;
            await new Promise((resolve) => { window.__releaseRewriteHash = resolve; });
            return result;
          };
        }
      }, kind);
      await first.page.getByRole("button", { name: "核对本次结果", exact: true }).click();
      if (kind.startsWith("hash-")) {
        await first.page.waitForFunction(() => window.__rewriteHashEntered === true);
        if (kind === "hash-edit") await first.page.locator('[data-saas-listing-draft-field="description"]').fill("Merchant edit during hash");
        else await first.page.evaluate(() => {
          state.saasListingComposerDraft.listing_project_identity = { key: "other-project", source_report_id: "other-source", candidate_id: "other" };
          state.saasListingComposerDraft.ai_generation_feedback = null;
        });
        await first.page.evaluate(() => { window.__releaseRewriteHash(); });
      }
      if (kind !== "hash-scope") await first.page.waitForFunction(() => state.saasListingComposerDraft.ai_generation_feedback?.status === "generated_unapplied");
      // Await the actual action, not just its HTTP headers or an arbitrary delay.
      await first.page.waitForFunction(() => !state.saasListingComposerDraft.ai_generation_feedback?.checking);
      const observed = await first.page.evaluate(() => ({ fields: state.saasListingComposerDraft.fields,
        packet: state.saasListingComposerDraft.merchant_product_fact_packet, prefill: state.saasListingComposerDraft.publish_prefill,
        feedback: state.saasListingComposerDraft.ai_generation_feedback, reports: state.saasReports.map((report) => report.report_id) }));
      assert.deepEqual(observed.fields, { ...previousFields,
        ...(kind === "copy" ? { title: "Merchant copy after generation" } : {}),
        ...(kind === "hash-edit" ? { description: "Merchant edit during hash" } : {}) }, kind);
      if (kind === "facts") assert.equal(observed.packet.merchant_confirmed_facts.material, "Wood");
      assert.equal(observed.prefill.quantity, kind === "prefill" ? "8" : "7");
      if (kind === "hash-scope") { assert.equal(observed.feedback, null); assert.ok(!observed.reports.includes(rewriteReport.report_id)); }
      else if (["missing", "malformed"].includes(kind)) assert.doesNotMatch(observed.feedback.input_signature || "", /^[a-f0-9]{64}$/, "invalid or absent proof must never be replaced with a fresh signature");
      else assert.equal(observed.feedback.input_signature, kind === "different" ? "f".repeat(64) : originalSignature);
      assert.equal(requests.filter((r) => r.path === generationPath).length, 1, kind);
      assert.equal(requests.filter((r) => r.path === generationStatusPath).length, 1, kind);
      assert.equal(requests.filter((r) => r.path === checkpointPath && r.method === "POST" && r.body.base_report_id === rewriteReport.report_id).length, 0, kind);
      assert.deepEqual(first.errors, []); assert.deepEqual(unexpected, []);
    } finally { await first.context.close(); }
  }
});

test("only the fresh own rewrite waiting on its original checkpoint may pass a cloud transition conflict", async () => {
  for (const kind of ["valid", "other-head", "revision", "fields", "marks", "stale-refresh", "new-edit", "cas-conflict"]) {
    reset(); const saved = { ...rewriteReport, user_id: userId };
    generationHandler = async (_request, res) => {
      currentBase = saved; res.writeHead(200, { "content-type": "application/json" }); res.end('{"status":'); return true;
    };
    generationStatusHandler = async (request, res) => {
      json(res, 200, { contract_version: "listing_generation_operation_v1", operation_id: request.query.operation_id,
        company_id: companyId, store_id: storeId, user_id: userId, listing_project_identity: identity,
        generation_mode: "rewrite_buyer_copy", expected_base_report_id: originalReport.report_id, expected_checkpoint_revision: 1,
        task_id: "rewrite-task", status: "report_saved", report_save_attempted: true, can_retry: false,
        model_called: true, usage_consumed: true, report: saved, failure_code: null,
        message: "本次文案已保存。", real_platform_writes_enabled: false, secret_exposed: false }); return true;
    };
    const first = await device();
    try {
      await first.page.getByRole("button", { name: "让 AI 重写买家文案", exact: true }).click();
      await first.page.waitForFunction(() => state.saasListingComposerDraft.ai_generation_feedback?.status === "generation_uncertain");
      if (kind === "other-head") currentBase = { ...saved, report_id: "another-new-head", created_at: "2026-09-09T04:00:00Z" };
      if (kind === "revision") head.revision = 2;
      if (kind === "fields") head.fields = { ...head.fields, description: "Another checkpoint copy" };
      if (kind === "marks") head.merchant_edited_fields = ["title"];
      // This is a real HTTP read through the product hydration path, not a
      // manufactured record.conflict or a direct call to the adoption helper.
      assert.equal(await first.page.evaluate(() => hydrateSaasListingCloudCheckpoint({ force: true })), true);
      assert.equal(await first.page.evaluate(() => saasListingCloudRecord().status), "conflict", kind);
      if (kind === "stale-refresh") await first.page.evaluate(() => { saasStateRefreshGeneration += 1; });
      if (kind === "new-edit") await first.page.locator('[data-saas-listing-draft-field="title"]').fill("Merchant input after cloud read");
      if (kind === "cas-conflict") checkpointHandler = async (request, res) => {
        if (request.method !== "POST" || request.body.base_report_id !== saved.report_id) return false;
        assert.equal(request.body.expected_revision, 1);
        head = checkpoint({ ...previousFields, description: "Another window won the CAS" }, 2, "outside-mutation-02", originalReport.report_id);
        currentBase = { ...originalReport, report_id: "new-facts-after-read", created_at: "2026-09-09T04:00:00Z" };
        json(res, 409, { status: "conflict", current_revision: 2, latest_checkpoint: head,
          current_base_report_id: currentBase.report_id, current_base_report: currentBase }); return true;
      };
      await first.page.getByRole("button", { name: "核对本次结果", exact: true }).click();
      await first.page.waitForFunction((adopt) => adopt ? state.saasListingComposerDraft.ai_generation_feedback === null
        : state.saasListingComposerDraft.ai_generation_feedback?.status === "generated_unapplied", kind === "valid");
      const adoptions = requests.filter((r) => r.path === checkpointPath && r.method === "POST" && r.body.base_report_id === saved.report_id);
      assert.equal(adoptions.length, ["valid", "cas-conflict"].includes(kind) ? 1 : 0, kind);
      if (adoptions.length) assert.equal(adoptions[0].body.expected_revision, 1, "always use the original revision, never absorb the read's revision");
      assert.deepEqual(await first.page.evaluate(() => state.saasListingComposerDraft.fields), kind === "valid" ? nextFields
        : { ...previousFields, ...(kind === "new-edit" ? { title: "Merchant input after cloud read" } : {}) }, kind);
      assert.equal(await first.page.evaluate(() => Boolean(saasListingCloudRecord().conflict)), kind !== "valid", kind);
      assert.equal(requests.filter((r) => r.path === generationPath).length, 1, kind);
      assert.equal(requests.filter((r) => r.path === generationStatusPath).length, 1, kind);
      assert.deepEqual(first.errors, []); assert.deepEqual(unexpected, []);
    } finally { await first.context.close(); }
  }
});

test("a real reload retains a running operation and result checking preserves edits made before or during the GET", async () => {
  reset(); const submitted = deferred(), finish = deferred(), read = deferred(), releaseRead = deferred();
  generationHandler = async (_request, res) => { submitted.resolve(); await finish.promise; json(res, 200, {}); return true; };
  generationStatusHandler = async (request, res) => {
    read.resolve(); await releaseRead.promise;
    json(res, 200, { contract_version: "listing_generation_operation_v1", operation_id: request.query.operation_id,
      company_id: companyId, store_id: storeId, user_id: userId, listing_project_identity: identity,
      generation_mode: "rewrite_buyer_copy", expected_base_report_id: originalReport.report_id, expected_checkpoint_revision: 1,
      task_id: "rewrite-task", status: "report_saved", report_save_attempted: true, can_retry: false,
      model_called: true, usage_consumed: true, report: { ...rewriteReport, user_id: userId }, failure_code: null,
      message: "本次文案已保存。", real_platform_writes_enabled: false, secret_exposed: false }); return true;
  };
  const first = await device();
  try {
    await first.page.getByRole("button", { name: "让 AI 重写买家文案", exact: true }).click(); await submitted.promise;
    const operation = requests.find((r) => r.path === generationPath).body.operation_id;
    assert.equal(await first.page.evaluate(() => {
      restoreSaasListingComposerDraftFromBackendReports({ preferBackendLatest: true, projectId: "rewrite-tablet" });
      renderProductListingCenter();
      return state.saasListingComposerDraft.ai_generation_feedback?.operation?.operation_id;
    }), operation, "same-project backend restoration must not discard a running operation");
    await first.page.reload();
    assert.equal(await first.page.evaluate((base) => {
      window.__JIEJING_FORCE_PUBLIC_MVP__ = true; state.saasApiBase = base;
      const restored = hydrateSaasProtectedStateFromCache();
      // This owned fixture is authenticated as the same account; cache by
      // itself must not grant access in the real product.
      state.saasProtectedStateReady = true; state.saasProtectedStateFromCache = false; state.view = "product";
      bindEvents(); renderProductListingCenter();
      document.querySelector("#view-product").classList.add("is-active"); return restored;
    }, base), true);
    assert.equal(await first.page.evaluate(() => state.saasListingComposerDraft.ai_generation_feedback.operation.operation_id), operation);
    assert.deepEqual(await first.page.evaluate(() => ({ saved: state.saasListingComposerDraft.ai_generation_feedback.context_key, current: saasListingAiGenerationContextKey() })),
      { saved: JSON.stringify([companyId, userId, storeId, identity.key, identity.source_report_id, identity.candidate_id]), current: JSON.stringify([companyId, userId, storeId, identity.key, identity.source_report_id, identity.candidate_id]) });
    await first.page.getByRole("button", { name: "让 AI 重写买家文案", exact: true }).click();
    assert.equal(requests.filter((r) => r.path === generationPath).length, 1);
    await first.page.locator('[data-saas-listing-draft-field="title"]').fill("Merchant new title before check");
    assert.equal(await first.page.getByRole("button", { name: "核对本次结果", exact: true }).count(), 1);
    await first.page.getByRole("button", { name: "核对本次结果", exact: true }).click(); await read.promise;
    await first.page.locator('[data-saas-listing-draft-field="description"]').fill("Merchant new description during check");
    releaseRead.resolve();
    await first.page.waitForFunction(() => state.saasListingComposerDraft.ai_generation_feedback?.status === "generated_unapplied");
    assert.equal(await first.page.getByText("查看重写前文案", { exact: true }).count(), 1);
    assert.equal(await first.page.locator('[data-saas-listing-draft-field="title"]').inputValue(), "Merchant new title before check");
    assert.equal(await first.page.locator('[data-saas-listing-draft-field="description"]').inputValue(), "Merchant new description during check");
    assert.equal(requests.filter((r) => r.path === generationPath).length, 1);
    assert.equal(requests.filter((r) => r.path === checkpointPath && r.method === "POST" && r.body.base_report_id === rewriteReport.report_id).length, 0);
    assert.deepEqual(first.errors, []); assert.deepEqual(unexpected, []);
  } finally { finish.resolve(); releaseRead.resolve(); await first.context.close(); }
});

test("only a complete 422 quality rejection permits a new explicit operation; malformed client errors and success bodies remain protected", async () => {
  for (const kind of ["known", "attempted", "missing", "other-code", "bare409", "bare422", "bare200"]) {
    reset(); const secondEntered = deferred(), releaseSecond = deferred();
    generationHandler = async (_request, res) => {
      if (kind === "known" && requests.filter((r) => r.path === generationPath).length === 2) {
        secondEntered.resolve(); await releaseSecond.promise;
      }
      const body = { status: "failed", report_save_attempted: false, report: null, task_id: "quality-rejected-task",
        failure_code: "listing_model_output_ungrounded_material", merchant_message: "本次文案未通过材质检查。",
        model_called: true, usage_consumed: true, model_usage: { request_count: 1 }, real_platform_writes_enabled: false, secret_exposed: false };
      if (kind === "attempted") body.report_save_attempted = true;
      if (kind === "missing") delete body.report_save_attempted;
      if (kind === "other-code") body.failure_code = "report_storage_json_error";
      json(res, kind === "bare409" ? 409 : kind === "bare200" ? 200 : 422, kind.startsWith("bare") ? {} : body); return true;
    };
    const first = await device();
    try {
      await first.page.getByRole("button", { name: "让 AI 重写买家文案", exact: true }).click();
      await first.page.waitForFunction(() => !state.saasLoading);
      assert.equal(await first.page.evaluate(() => state.saasListingComposerDraft.ai_generation_feedback.status), kind === "known" ? "failed" : "generation_uncertain", kind);
      const firstOp = requests.find((r) => r.path === generationPath).body.operation_id;
      if (kind === "known") {
        await first.page.evaluate(() => renderProductListingCenter());
        await first.page.getByRole("button", { name: "AI 生成 Listing 草稿", exact: true }).click(); await secondEntered.promise;
        const running = await first.page.evaluate(() => state.saasListingComposerDraft.ai_generation_feedback);
        assert.equal(running.operation.generation_mode, "preserve_merchant_edits");
        assert.equal(running.rewrite_source, null, "a new default operation must not inherit the previous failed rewrite source");
        assert.equal(running.result_report_id, null, "a new operation must not inherit a previous result");
        assert.equal(await first.page.evaluate((id) => Object.values(localStorage).some((value) => value.includes(id)), running.operation.operation_id), true);
        releaseSecond.resolve();
        await first.page.waitForFunction(() => !state.saasLoading);
        assert.equal(requests.filter((r) => r.path === generationPath).length, 2);
        assert.notEqual(requests.filter((r) => r.path === generationPath)[1].body.operation_id, firstOp);
      } else {
        await first.page.getByRole("button", { name: "让 AI 重写买家文案", exact: true }).click();
        assert.equal(requests.filter((r) => r.path === generationPath).length, 1, kind);
      }
      assert.deepEqual(await first.page.evaluate(() => state.saasListingComposerDraft.fields), kind === "known" ? { ...previousFields, cost_price: "" } : previousFields);
      assert.deepEqual(first.errors, []); assert.deepEqual(unexpected, []);
    } finally { releaseSecond.resolve(); await first.context.close(); }
  }
});

test("result status rejects mismatched ownership anchors and false-like proofs, and coalesces double clicks across a late foreign-context response", async () => {
  for (const kind of ["company", "store", "user", "candidate", "source", "base", "revision", "operation", "missing", "false-string", "contradictory", "not-found", "late"]) {
    reset(); const entered = deferred(), release = deferred();
    generationHandler = async (_request, res) => { res.writeHead(200, { "content-type": "application/json" }); res.end('{"status":'); return true; };
    generationStatusHandler = async (request, res) => {
      const result = { contract_version: "listing_generation_operation_v1", operation_id: request.query.operation_id,
        company_id: companyId, store_id: storeId, user_id: userId, listing_project_identity: { ...identity },
        generation_mode: "rewrite_buyer_copy", expected_base_report_id: originalReport.report_id, expected_checkpoint_revision: 1,
        task_id: "known-failed-task", status: "failed_before_report", report_save_attempted: false, can_retry: true,
        model_called: true, usage_consumed: true, report: null, failure_code: "listing_model_output_ungrounded_material",
        message: "未保存新文案。", real_platform_writes_enabled: false, secret_exposed: false };
      if (["company", "store", "user"].includes(kind)) result[`${kind}_id`] = `foreign-${kind}`;
      if (kind === "candidate") result.listing_project_identity.candidate_id = "foreign";
      if (kind === "source") result.listing_project_identity.source_report_id = "foreign";
      if (kind === "base") result.expected_base_report_id = "foreign";
      if (kind === "revision") result.expected_checkpoint_revision = 2;
      if (kind === "operation") result.operation_id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
      if (kind === "missing") delete result.report_save_attempted;
      if (kind === "false-string") result.report_save_attempted = "false";
      if (kind === "contradictory") result.report = rewriteReport;
      if (kind === "not-found") { result.status = "not_found"; result.can_retry = false; result.generation_mode = null; result.expected_base_report_id = null; result.expected_checkpoint_revision = null; }
      entered.resolve(); await release.promise; json(res, 200, result); return true;
    };
    const first = await device();
    try {
      await first.page.getByRole("button", { name: "让 AI 重写买家文案", exact: true }).click();
      await first.page.waitForFunction(() => state.saasListingComposerDraft.ai_generation_feedback?.status === "generation_uncertain");
      await first.page.getByRole("button", { name: "核对本次结果", exact: true }).dblclick(); await entered.promise;
      if (kind === "late") await first.page.evaluate(() => {
        state.saasListingComposerDraft.listing_project_identity = { key: "other-project", source_report_id: "other-source", candidate_id: "other" };
        state.saasListingComposerDraft.ai_generation_feedback = null;
      });
      release.resolve();
      await first.page.waitForResponse((r) => new URL(r.url()).pathname === generationStatusPath);
      // Await the public action's settled DOM state without an arbitrary sleep.
      if (kind !== "late") await first.page.waitForFunction(() => state.saasListingComposerDraft.ai_generation_feedback?.message.startsWith("暂时无法") || state.saasListingComposerDraft.ai_generation_feedback?.message === "未保存新文案。");
      assert.equal(requests.filter((r) => r.path === generationStatusPath).length, 1, kind);
      assert.equal(await first.page.evaluate(() => state.saasListingComposerDraft.ai_generation_feedback?.status || null), kind === "late" ? null : "generation_uncertain", kind);
      assert.deepEqual(await first.page.evaluate(() => state.saasListingComposerDraft.fields), previousFields);
      assert.equal(requests.filter((r) => r.path === generationPath).length, 1); assert.deepEqual(first.errors, []); assert.deepEqual(unexpected, []);
    } finally { release.resolve(); await first.context.close(); }
  }
});

test("failure to persist the operation stops before generation without weakening checkpoint storage", async () => {
  reset(); const first = await device();
  try {
    await first.page.evaluate(() => {
      const original = Storage.prototype.setItem;
      Storage.prototype.setItem = function (key, value) {
        if (String(value).includes('"operation_id"')) throw new DOMException("owned storage boundary", "QuotaExceededError");
        return original.call(this, key, value);
      };
    });
    await first.page.getByRole("button", { name: "让 AI 重写买家文案", exact: true }).click();
    await first.page.waitForFunction(() => !state.saasLoading);
    assert.equal(requests.filter((r) => r.path === generationPath).length, 0);
    assert.equal(head.revision, 1);
    assert.match(await first.page.locator("[data-saas-listing-ai-feedback]").innerText(), /本机.*存|操作.*保留/);
    assert.deepEqual(await first.page.evaluate(() => state.saasListingComposerDraft.fields), previousFields);
    assert.deepEqual(first.errors, []); assert.deepEqual(unexpected, []);
  } finally { await first.context.close(); }
});

test("default generation also recovers its exact saved report with null rewrite anchors", async () => {
  reset();
  const saved = { ...originalReport, report_id: "default-operation-result", user_id: userId };
  generationHandler = async (_request, res) => { currentBase = saved; res.writeHead(200, { "content-type": "application/json" }); res.end('{"status":'); return true; };
  generationStatusHandler = async (request, res) => {
    json(res, 200, { contract_version: "listing_generation_operation_v1", operation_id: request.query.operation_id,
      company_id: companyId, store_id: storeId, user_id: userId, listing_project_identity: identity,
      generation_mode: "preserve_merchant_edits", expected_base_report_id: null, expected_checkpoint_revision: null,
      task_id: saved.task_id, status: "report_saved", report_save_attempted: true, can_retry: false,
      model_called: true, usage_consumed: true, report: saved, failure_code: null,
      message: "本次草稿已保存。", real_platform_writes_enabled: false, secret_exposed: false }); return true;
  };
  const first = await device();
  try {
    await first.page.evaluate(() => renderProductListingCenter());
    await first.page.getByRole("button", { name: "AI 生成 Listing 草稿", exact: true }).click();
    await first.page.waitForFunction(() => state.saasListingComposerDraft.ai_generation_feedback?.status === "generation_uncertain");
    await first.page.getByRole("button", { name: "核对本次结果", exact: true }).click();
    await first.page.waitForFunction(() => state.saasListingComposerDraft.ai_generation_feedback === null, null, { timeout: 3000 });
    assert.equal(await first.page.evaluate(() => state.saasListingAiGenerationStatus), "completed");
    assert.equal(await first.page.evaluate(() => state.saasReports.some((r) => r.report_id === "default-operation-result")), true);
    assert.equal(requests.filter((r) => r.path === generationPath).length, 1);
    assert.equal(requests.filter((r) => r.path === checkpointPath && r.method === "POST").length, 0);
    assert.deepEqual(first.errors, []); assert.deepEqual(unexpected, []);
  } finally { await first.context.close(); }
});

test("a known default generation success with newer merchant edits shows the saved report instead of remaining running", async () => {
  reset(); const entered = deferred(), release = deferred();
  const saved = { ...originalReport, report_id: "known-default-result", user_id: userId, created_at: "2026-09-09T04:00:00Z" };
  generationHandler = async (_request, res) => { entered.resolve(); await release.promise; currentBase = saved;
    json(res, 201, { status: "completed", report: saved, listing_project_identity: identity, missing_fields: [] }); return true; };
  generationStatusHandler = async (request, res) => {
    json(res, 200, { contract_version: "listing_generation_operation_v1", operation_id: request.query.operation_id,
      company_id: companyId, store_id: storeId, user_id: userId, listing_project_identity: identity,
      generation_mode: "preserve_merchant_edits", expected_base_report_id: null, expected_checkpoint_revision: null,
      task_id: saved.task_id, status: "report_saved", report_save_attempted: true, can_retry: false,
      model_called: true, usage_consumed: true, report: saved, failure_code: null,
      message: "本次草稿已保存。", real_platform_writes_enabled: false, secret_exposed: false }); return true;
  };
  const first = await device();
  try {
    await first.page.evaluate(() => renderProductListingCenter());
    await first.page.getByRole("button", { name: "AI 生成 Listing 草稿", exact: true }).click(); await entered.promise;
    await first.page.locator('[data-saas-listing-draft-field="title"]').fill("Merchant title typed during generation");
    release.resolve(); await first.page.waitForFunction(() => state.saasListingAiGenerationStatus === "completed" && !state.saasLoading);
    const result = await first.page.evaluate(() => ({ title: state.saasListingComposerDraft.fields.title,
      feedback: state.saasListingComposerDraft.ai_generation_feedback, reports: state.saasReports.map((report) => report.report_id) }));
    assert.equal(result.title, "Merchant title typed during generation");
    assert.equal(result.feedback.status, "generated_unapplied"); assert.equal(result.feedback.result_report_id, saved.report_id);
    assert.ok(result.reports.includes(saved.report_id)); assert.equal(requests.filter((r) => r.path === generationPath).length, 1);
    assert.match(await first.page.locator("[data-saas-listing-ai-feedback]").innerText(), /已生成/);
    await first.page.getByRole("button", { name: "核对本次结果", exact: true }).click();
    await first.page.waitForFunction(() => state.saasListingComposerDraft.ai_generation_feedback?.status === "generated_unapplied");
    assert.equal(requests.filter((r) => r.path === generationStatusPath).length, 1);
    assert.equal(requests.find((r) => r.path === generationStatusPath).query.operation_id, result.feedback.operation.operation_id);
    await first.page.locator('[data-saas-listing-draft-field="title"]').blur();
    await first.page.getByRole("button", { name: "保留本机修改并重新保存", exact: true }).waitFor({ state: "visible", timeout: 5000 });
    assert.equal(await first.page.evaluate(() => state.saasListingComposerDraft.ai_generation_feedback.status), "generated_unapplied");
    await first.page.getByRole("button", { name: "保留本机修改并重新保存", exact: true }).click();
    await first.page.waitForFunction((reportId) => {
      const record = saasListingCloudRecord();
      return record?.loaded && !record.dirty && !record.pending && !record.conflict && !record.write && !record.read &&
        record.receipt?.base_report_id === reportId && record.status === "saved";
    }, saved.report_id, { timeout: 5000 });
    assert.equal(head.base_report_id, saved.report_id);
    assert.equal(head.fields.title, "Merchant title typed during generation");
    assert.equal(await first.page.locator('[data-saas-listing-draft-field="title"]').inputValue(), head.fields.title);
    assert.equal(requests.filter((r) => r.path === generationPath).length, 1, "normal cloud conflict recovery must not repeat generation");
    assert.equal(await first.page.evaluate(() => state.saasListingComposerDraft.ai_generation_feedback), null,
      "a confirmed cloud save on the exact generated base must finish default-mode result review without replacing merchant edits");
    assert.deepEqual(first.errors, []); assert.deepEqual(unexpected, []);
  } finally { release.resolve(); await first.context.close(); }
});

test("default saved results stay protected without a fresh matching cloud receipt or while merchant edits are still pending", async () => {
  for (const kind of ["use-cloud-with-old-receipt", "foreign-current-base", "edit-during-save"]) {
    reset(); const generated = deferred(), release = deferred(), saving = deferred(), releaseSave = deferred();
    const saved = { ...originalReport, report_id: "negative-default-result", user_id: userId, created_at: "2026-09-09T04:00:00Z" };
    head = checkpoint(previousFields, 1, "original-saved-edit", originalReport.report_id);
    generationHandler = async (_request, res) => { generated.resolve(); await release.promise; currentBase = saved;
      json(res, 201, { status: "completed", report: saved, listing_project_identity: identity, missing_fields: [] }); return true; };
    const first = await device();
    try {
      await first.page.evaluate(() => renderProductListingCenter());
      await first.page.getByRole("button", { name: "AI 生成 Listing 草稿", exact: true }).click(); await generated.promise;
      await first.page.locator('[data-saas-listing-draft-field="title"]').fill("Merchant changed title before saved result");
      release.resolve(); await first.page.waitForFunction(() => state.saasListingAiGenerationStatus === "completed" && !state.saasLoading);
      assert.equal(await first.page.evaluate(() => state.saasListingComposerDraft.ai_generation_feedback?.status), "generated_unapplied", kind);
      await first.page.locator('[data-saas-listing-draft-field="title"]').blur();
      const keep = first.page.getByRole("button", { name: "保留本机修改并重新保存", exact: true });
      await keep.waitFor({ state: "visible", timeout: 5000 });
      if (kind === "use-cloud-with-old-receipt") {
        await first.page.locator('[data-saas-listing-cloud-action="use-cloud"]').click();
        await first.page.waitForFunction(() => saasListingCloudRecord()?.status === "current");
        assert.equal(await first.page.evaluate(() => saasListingCloudRecord().receipt), null);
        assert.equal(head.base_report_id, originalReport.report_id, "selecting a base is not a saved N receipt");
      } else if (kind === "foreign-current-base") {
        checkpointHandler = async (request, res) => {
          if (request.method !== "GET") return false;
          json(res, 200, { status: "saved", checkpoint: head, current_revision: head.revision,
            current_base_report_id: saved.report_id, current_base_report: { ...saved, company_id: "different-company" }, base_changed: true }); return true;
        };
        await keep.click(); await first.page.waitForFunction(() => saasListingCloudRecord()?.status === "error");
        assert.equal(await first.page.locator('[data-saas-listing-draft-field="title"]').inputValue(), "Merchant changed title before saved result");
      } else {
        checkpointHandler = async (request) => {
          if (request.method !== "POST" || request.body.base_report_id !== saved.report_id) return false;
          saving.resolve(); await releaseSave.promise; return false;
        };
        await keep.click(); await saving.promise;
        await first.page.locator('[data-saas-listing-draft-field="title"]').fill("Newer title typed during cloud save");
        const accepted = first.page.waitForResponse((response) => response.request().method() === "POST" &&
          new URL(response.url()).pathname === checkpointPath && response.status() === 201);
        releaseSave.resolve(); await accepted;
        await first.page.waitForFunction(() => saasListingCloudRecord()?.dirty && !saasListingCloudRecord()?.write);
        assert.equal(head.fields.title, "Merchant changed title before saved result");
        assert.equal(await first.page.locator('[data-saas-listing-draft-field="title"]').inputValue(), "Newer title typed during cloud save");
      }
      assert.equal(await first.page.evaluate(() => state.saasListingComposerDraft.ai_generation_feedback?.status), "generated_unapplied", kind);
      await first.page.getByRole("button", { name: "AI 生成 Listing 草稿", exact: true }).click();
      assert.equal(requests.filter((r) => r.path === generationPath).length, 1, kind);
      assert.deepEqual(first.errors, []); assert.deepEqual(unexpected, []);
    } finally { release.resolve(); releaseSave.resolve(); await first.context.close(); }
  }
});

test("complete pre-model blocked responses preserve the reason and allow action only after fixing it, unlike incomplete blocked bodies", async () => {
  for (const kind of ["missing", "connection", "trial", "incomplete"]) {
    reset();
    generationHandler = async (_request, res) => {
      const body = { status: "blocked", blocked_by: [], model_called: false, usage_consumed: false,
        report: null, listing_project_identity: identity, real_platform_writes_enabled: false, secret_exposed: false };
      if (kind === "missing") { body.missing_fields = ["material"]; body.blocked_by = ["listing_core_fact_missing:material"]; }
      if (kind === "connection") { body.model_resolution = { status: "blocked" }; body.blocked_by = ["listing_model_not_ready"]; }
      if (kind === "trial" || kind === "incomplete") { body.model_resolution = { status: "resolved" }; body.platform_trial_quota = { allowed: false };
        body.blocked_by = ["platform_default_model_trial_expired"]; body.merchant_message = "试用已到期；已有资料保留。"; }
      if (kind === "incomplete") delete body.usage_consumed;
      json(res, kind === "trial" || kind === "incomplete" ? 402 : kind === "connection" ? 202 : 200, body); return true;
    };
    const first = await device();
    try {
      await first.page.getByRole("button", { name: "让 AI 重写买家文案", exact: true }).click(); await first.page.waitForFunction(() => !state.saasLoading);
      assert.equal(await first.page.evaluate(() => state.saasListingComposerDraft.ai_generation_feedback.status), kind === "incomplete" ? "generation_uncertain" : "blocked", kind);
      if (kind === "trial") assert.match(await first.page.locator("[data-saas-listing-ai-feedback]").innerText(), /试用已到期/);
      assert.deepEqual(await first.page.evaluate(() => state.saasListingComposerDraft.fields), previousFields);
      assert.equal(requests.filter((r) => r.path === generationPath).length, 1); assert.deepEqual(first.errors, []); assert.deepEqual(unexpected, []);
    } finally { await first.context.close(); }
  }
});

test("legacy unknown offers explicit scoped failed tasks and only immutable failed-ledger proof releases the selected attempt", async () => {
  reset();
  generationStatusHandler = async (request, res) => {
    json(res, 200, { contract_version: "listing_generation_legacy_recovery_v1", task_id: request.query.legacy_task_id,
      company_id: companyId, store_id: storeId, user_id: userId, listing_project_identity: identity,
      expected_base_report_id: originalReport.report_id, expected_checkpoint_revision: 1,
      status: "legacy_failed_before_report", can_retry: true, proof_kind: "immutable_failed_usage_ledger", report: null,
      failure_code: "listing_model_output_ungrounded_material", merchant_message: "已核对此次失败，旧文案保留，可以主动重写。",
      model_called: false, usage_consumed: false, real_platform_writes_enabled: false, secret_exposed: false }); return true;
  };
  const first = await device();
  try {
    await first.page.evaluate(({ companyId, storeId, userId, identity }) => {
      const task = { task_id: "legacy-failed-1", task_type: "listing_draft_generation", company_id: companyId, store_id: storeId, user_id: userId,
        status: "failed", created_at: "2026-09-09T01:10:00Z", input: { contract_version: "listing_ai_draft_generation_v1", generation_mode: "rewrite_buyer_copy", listing_project_identity: identity, product: "平板支架" } };
      state.saasTasks = [task, { ...task, task_id: "legacy-failed-2", created_at: "2026-09-09T02:10:00Z" },
        { ...task, task_id: "foreign-user", user_id: "other" }, { ...task, task_id: "foreign-source", input: { ...task.input, listing_project_identity: { ...identity, source_report_id: "other" } } }];
      state.saasListingComposerDraft.ai_generation_feedback = { status: "generation_uncertain", context_key: saasListingAiGenerationContextKey(),
        message: "生成结果尚未确认。", rewrite_source: { base_report_id: "rewrite-original-report", revision: 1 } };
      renderProductListingCenter();
    }, { companyId, storeId, userId, identity });
    assert.equal(await first.page.getByRole("button", { name: "核对此次失败", exact: true }).count(), 2);
    assert.equal(requests.filter((r) => r.path === generationStatusPath).length, 0, "no latest-task inference");
    await first.page.locator('[data-saas-action="listing-check-legacy-generation-result"][data-task-id="legacy-failed-1"]').click();
    await first.page.waitForFunction(() => state.saasListingComposerDraft.ai_generation_feedback?.status === "failed");
    assert.deepEqual(requests.filter((r) => r.path === generationStatusPath).map((r) => r.query), [{ legacy_task_id: "legacy-failed-1",
      source_report_id: identity.source_report_id, candidate_id: identity.candidate_id, expected_base_report_id: originalReport.report_id, expected_checkpoint_revision: "1" }]);
    assert.equal(requests.filter((r) => r.path === generationPath).length, 0);
    assert.deepEqual(await first.page.evaluate(() => state.saasListingComposerDraft.fields), previousFields);
    assert.deepEqual(first.errors, []); assert.deepEqual(unexpected, []);
  } finally { await first.context.close(); }
});

test("legacy recovery does not infer proof from matching dates, another task, missing fields, or a late response", async () => {
  for (const kind of ["proof", "task", "company", "user", "source", "base", "revision", "string-true", "incomplete", "report", "late"]) {
    reset(); const entered = deferred(), release = deferred();
    generationStatusHandler = async (_request, res) => {
      const result = { contract_version: "listing_generation_legacy_recovery_v1", task_id: "legacy-selected",
        company_id: companyId, store_id: storeId, user_id: userId, listing_project_identity: { ...identity },
        expected_base_report_id: originalReport.report_id, expected_checkpoint_revision: 1,
        status: "legacy_failed_before_report", can_retry: true, proof_kind: "immutable_failed_usage_ledger", report: null,
        failure_code: "listing_model_output_ungrounded_material", merchant_message: "这次记录仍需核对。",
        model_called: false, usage_consumed: false, real_platform_writes_enabled: false, secret_exposed: false };
      if (kind === "proof") result.proof_kind = "task_status_failed";
      if (kind === "task") result.task_id = "same-date-other-task";
      if (kind === "company") result.company_id = "foreign";
      if (kind === "user") result.user_id = "foreign";
      if (kind === "source") result.listing_project_identity.source_report_id = "foreign";
      if (kind === "base") result.expected_base_report_id = "different-base";
      if (kind === "revision") result.expected_checkpoint_revision = 2;
      if (kind === "string-true") result.can_retry = "true";
      if (kind === "incomplete") delete result.secret_exposed;
      if (kind === "report") result.report = rewriteReport;
      entered.resolve(); await release.promise; json(res, 200, result); return true;
    };
    const first = await device();
    try {
      await first.page.evaluate(({ companyId, userId, storeId, identity }) => {
        state.saasTasks = [{ task_id: "legacy-selected", task_type: "listing_draft_generation", status: "failed", company_id: companyId,
          user_id: userId, store_id: storeId, input: { contract_version: "listing_ai_draft_generation_v1", generation_mode: "rewrite_buyer_copy", listing_project_identity: identity } }];
        state.saasListingComposerDraft.ai_generation_feedback = { status: "generation_uncertain", context_key: saasListingAiGenerationContextKey(),
          message: "旧操作尚未确认。", rewrite_source: { base_report_id: "rewrite-original-report", revision: 1 } }; renderProductListingCenter();
      }, { companyId, userId, storeId, identity });
      await first.page.getByRole("button", { name: "核对此次失败", exact: true }).dblclick(); await entered.promise;
      if (kind === "late") await first.page.evaluate(() => { state.saasIdentity.user_id = "new-user"; state.saasUser.user_id = "new-user"; state.saasListingComposerDraft.ai_generation_feedback = null; });
      const completed = first.page.waitForResponse((r) => new URL(r.url()).pathname === generationStatusPath); release.resolve(); await completed;
      if (kind !== "late") await first.page.waitForFunction(() => state.saasListingComposerDraft.ai_generation_feedback?.message !== "旧操作尚未确认。");
      assert.equal(await first.page.evaluate(() => state.saasListingComposerDraft.ai_generation_feedback?.status || null), kind === "late" ? null : "generation_uncertain", kind);
      assert.equal(requests.filter((r) => r.path === generationStatusPath).length, 1);
      assert.equal(requests.filter((r) => r.path === generationPath).length, 0);
      assert.deepEqual(await first.page.evaluate(() => state.saasListingComposerDraft.fields), previousFields);
      assert.deepEqual(first.errors, []); assert.deepEqual(unexpected, []);
    } finally { release.resolve(); await first.context.close(); }
  }
});

test("a failed generation in Recent returns to the same protected draft instead of asking for new sourcing facts", async () => {
  reset(); const first = await device();
  try {
    await first.page.evaluate(({ companyId, userId, storeId, identity }) => {
      state.saasTasks = [{ task_id: "legacy-recent", task_type: "listing_draft_generation", status: "failed", company_id: companyId, user_id: userId, store_id: storeId,
        input: { contract_version: "listing_ai_draft_generation_v1", generation_mode: "rewrite_buyer_copy", listing_project_identity: identity, product: "平板支架" },
        output: { failure_code: "listing_model_output_ungrounded_material" } }];
      state.saasListingComposerDraft.ai_generation_feedback = { status: "generation_uncertain", context_key: saasListingAiGenerationContextKey(), message: "结果待核对。",
        rewrite_source: { base_report_id: "rewrite-original-report", revision: 1 } };
      activateSaasListingMode("recent");
    }, { companyId, userId, storeId, identity });
    const card = first.page.locator('[data-recent-product-task-id="legacy-recent"]');
    assert.doesNotMatch(await card.innerText(), /补充商品链接|补商品资料/);
    await card.getByRole("button", { name: "返回已有商品草稿", exact: true }).click();
    assert.equal(await first.page.getByRole("button", { name: "核对此次失败", exact: true }).count(), 1);
    assert.deepEqual(await first.page.evaluate(() => state.saasListingComposerDraft.fields), previousFields);
    assert.equal(await first.page.evaluate(() => state.saasListingComposerDraft.ai_generation_feedback.status), "generation_uncertain");
    assert.equal(requests.filter((r) => r.method === "POST").length, 0);
    assert.deepEqual(first.errors, []); assert.deepEqual(unexpected, []);
  } finally { await first.context.close(); }
});

test("a generation POST replay uses its original proof while a legacy saved result without that proof preserves current copy", async () => {
  for (const kind of ["post-dto", "legacy-saved"]) {
    reset();
    const saved = { ...rewriteReport, user_id: userId };
    const reply = (operationId) => ({ contract_version: "listing_generation_operation_v1", operation_id: operationId, company_id: companyId, store_id: storeId, user_id: userId,
      listing_project_identity: identity, generation_mode: "rewrite_buyer_copy", expected_base_report_id: originalReport.report_id, expected_checkpoint_revision: 1,
      status: "report_saved", task_id: saved.task_id, report: saved, report_save_attempted: true, model_called: true, usage_consumed: true,
      can_retry: false, message: "已找到本次文案。", failure_code: null, real_platform_writes_enabled: false, secret_exposed: false });
    generationHandler = async (request, res) => { currentBase = saved; json(res, 200, reply(request.body.operation_id)); return true; };
    generationStatusHandler = async (_request, res) => {
      currentBase = saved;
      json(res, 200, { contract_version: "listing_generation_legacy_recovery_v1", company_id: companyId, store_id: storeId, user_id: userId,
        listing_project_identity: identity, expected_base_report_id: originalReport.report_id, expected_checkpoint_revision: 1,
        task_id: saved.task_id, status: "report_saved", can_retry: false, proof_kind: "", report: saved, failure_code: "", merchant_message: "已找到这次保存的文案。",
        model_called: false, usage_consumed: false, real_platform_writes_enabled: false, secret_exposed: false }); return true;
    };
    if (kind === "legacy-saved") { head = checkpoint(previousFields, 1, "legacy-before-generation", originalReport.report_id); head.merchant_edited_fields = ["title", "selling_points", "description", "price"]; }
    const first = await device();
    try {
      if (kind === "post-dto") await first.page.getByRole("button", { name: "让 AI 重写买家文案", exact: true }).click();
      else {
        await first.page.evaluate(({ companyId, userId, storeId, identity }) => {
          state.saasTasks = [{ task_id: "rewrite-task", task_type: "listing_draft_generation", status: "failed", company_id: companyId, user_id: userId, store_id: storeId,
            input: { contract_version: "listing_ai_draft_generation_v1", generation_mode: "rewrite_buyer_copy", listing_project_identity: identity } }];
          state.saasListingComposerDraft.ai_generation_feedback = { status: "generation_uncertain", context_key: saasListingAiGenerationContextKey(), message: "历史结果未知。",
            rewrite_source: { base_report_id: "rewrite-original-report", revision: 1 } }; renderProductListingCenter();
        }, { companyId, userId, storeId, identity });
        await first.page.getByRole("button", { name: "核对此次失败", exact: true }).click();
      }
      if (kind === "post-dto") {
        await first.page.waitForFunction((title) => state.saasListingComposerDraft.fields.title === title, nextFields.title, { timeout: 3000 });
        assert.deepEqual(await first.page.evaluate(() => state.saasListingComposerDraft.fields), nextFields);
        assert.equal(head.revision, 2); assert.equal(head.base_report_id, saved.report_id);
      } else {
        await first.page.waitForFunction(() => state.saasListingComposerDraft.ai_generation_feedback?.status === "generated_unapplied");
        assert.deepEqual(await first.page.evaluate(() => state.saasListingComposerDraft.fields), previousFields);
        assert.equal(head.revision, 1); assert.equal(head.base_report_id, originalReport.report_id);
        assert.equal(requests.filter((r) => r.path === checkpointPath && r.method === "POST").length, 0);
        assert.ok(await first.page.evaluate((id) => state.saasReports.some((report) => report.report_id === id), saved.report_id));
        assert.equal(await first.page.getByText("查看重写前文案", { exact: true }).count(), 1);
        assert.doesNotMatch(await first.page.evaluate(() => state.saasListingComposerDraft.ai_generation_feedback.input_signature || ""), /^[a-f0-9]{64}$/, "never invent original proof for a legacy result");
      }
      assert.equal(requests.filter((r) => r.path === generationPath).length, kind === "post-dto" ? 1 : 0);
      assert.deepEqual(first.errors, []); assert.deepEqual(unexpected, []);
    } finally { await first.context.close(); }
  }
});

test("explicit buyer-copy rewrite saves only three fields through fixed-revision CAS and restores old copy without undoing later price edits", async () => {
  reset();
  const first = await device();
  let second;
  try {
    assert.equal(await first.page.getByRole("button", { name: "让 AI 重写买家文案", exact: true }).count(), 1);
    const completed = first.page.waitForResponse((r) => new URL(r.url()).pathname === checkpointPath && r.request().method() === "POST"
      && r.request().postDataJSON().base_report_id === rewriteReport.report_id);
    const observed = completed.then((response) => ({ response }), (error) => ({ error }));
    await first.page.getByRole("button", { name: "让 AI 重写买家文案", exact: true }).click();
    const result = await observed; assert.equal(result.error, undefined); assert.equal(result.response.status(), 201);
    await first.page.waitForFunction((expected) => state.saasListingComposerDraft.fields.title === expected, nextFields.title);
    assert.deepEqual(await first.page.evaluate(() => state.saasListingComposerDraft.fields), nextFields);
    assert.equal(await first.page.evaluate(() => state.saasListingComposerDraft.publish_prefill.quantity), "7");
    const generation = requests.filter((r) => r.path === generationPath);
    assert.equal(generation.length, 1); assert.equal(generation[0].body.generation_mode, "rewrite_buyer_copy");
    assert.deepEqual(Object.fromEntries(fieldKeys.map((key) => [key, generation[0].body.current_draft_fields[key]])), previousFields);
    assert.deepEqual(generation[0].body.merchant_product_fact_packet, factPacket, "rewrite sends saved facts, not suggestions derived again from price or prefill");
    const saves = requests.filter((r) => r.path === checkpointPath && r.method === "POST");
    assert.equal(saves.length, 2); assert.equal(saves[0].body.base_report_id, originalReport.report_id);
    assert.equal(saves[1].body.expected_revision, 1); assert.deepEqual(saves[1].body.fields, nextFields);
    await first.page.locator('[data-saas-listing-draft-field="price"]').fill("35.00 USD");
    await first.page.getByText("查看重写前文案", { exact: true }).click();
    await first.page.getByRole("button", { name: "恢复这三个旧文案", exact: true }).click();
    await first.page.evaluate(() => flushSaasListingCloudCheckpoint());
    assert.deepEqual(await first.page.evaluate(() => state.saasListingComposerDraft.fields), { ...previousFields, price: "35.00 USD" });
    second = await device(rewriteReport);
    assert.deepEqual(await second.page.evaluate(() => state.saasListingComposerDraft.fields), { ...previousFields, price: "35.00 USD" });
    assert.equal(await second.page.getByText("查看重写前文案", { exact: true }).count(), 1);
    assert.deepEqual(first.errors, []); assert.deepEqual(second.errors, []); assert.deepEqual(unexpected, []);
  } finally { await first.context.close(); if (second) await second.context.close(); }
});

test("unsaved product facts are kept as form edits and block rewrite before a model request", async () => {
  reset();
  const first = await device();
  try {
    await first.page.evaluate(() => renderProductListingCenter());
    const before = await first.page.evaluate(() => JSON.stringify(state.saasListingComposerDraft.merchant_product_fact_packet));
    await first.page.locator('[data-saas-product-fact-field="material"]').fill("Steel pending merchant save");
    await first.page.getByRole("button", { name: "让 AI 重写买家文案", exact: true }).click();
    assert.match(await first.page.locator("#actionToast").textContent(), /商品资料.*尚未保存/);
    assert.equal(requests.filter((r) => r.path === generationPath).length, 0);
    assert.equal(await first.page.locator('[data-saas-product-fact-field="material"]').inputValue(), "Steel pending merchant save");
    assert.equal(await first.page.evaluate(() => JSON.stringify(state.saasListingComposerDraft.merchant_product_fact_packet)), before);
    assert.deepEqual(first.errors, []); assert.deepEqual(unexpected, []);
  } finally { await first.context.close(); }
});

test("new merchant edits during rewrite survive and the generated result is visible without another model call", async () => {
  reset(); const entered = deferred(), release = deferred();
  generationHandler = async (_request, res) => { entered.resolve(); await release.promise; currentBase = rewriteReport;
    json(res, 201, { status: "completed", report: rewriteReport, listing_project_identity: identity }); return true; };
  const first = await device();
  try {
    await first.page.getByRole("button", { name: "让 AI 重写买家文案", exact: true }).click(); await entered.promise;
    await first.page.locator('[data-saas-listing-draft-field="title"]').fill("Merchant typing during generation");
    release.resolve();
    await first.page.waitForFunction(() => state.saasListingAiGenerationStatus === "completed");
    assert.equal(await first.page.inputValue('[data-saas-listing-draft-field="title"]'), "Merchant typing during generation");
    assert.equal(requests.filter((r) => r.path === checkpointPath && r.body?.base_report_id === rewriteReport.report_id).length, 0);
    assert.match(await first.page.locator('[data-saas-listing-ai-feedback]').textContent(), /新文案已生成/);
    assert.equal(await first.page.getByText("查看重写前文案", { exact: true }).count(), 1);
    await first.page.getByRole("button", { name: "让 AI 重写买家文案", exact: true }).click();
    assert.equal(requests.filter((r) => r.path === generationPath).length, 1);
    assert.deepEqual(first.errors, []); assert.deepEqual(unexpected, []);
  } finally { release.resolve(); await first.context.close(); }
});

test("background checkpoint reads cannot adopt a generated report before its held CAS is acknowledged", async () => {
  reset(); const entered = deferred(), release = deferred();
  checkpointHandler = async (request) => {
    if (request.method === "POST" && request.body.base_report_id === rewriteReport.report_id) { entered.resolve(); await release.promise; }
    return false;
  };
  const first = await device();
  try {
    await first.page.getByRole("button", { name: "让 AI 重写买家文案", exact: true }).click(); await entered.promise;
    assert.equal(await first.page.getByRole("button", { name: "让 AI 重写买家文案", exact: true }).isDisabled(), true);
    await first.page.evaluate(async () => { await hydrateSaasListingCloudCheckpoint({ force: true }); renderProductListingCenter(); });
    assert.deepEqual(await first.page.evaluate(() => state.saasListingComposerDraft.fields), previousFields);
    assert.equal(requests.filter((r) => r.path === generationPath).length, 1);
    release.resolve();
    await first.page.waitForFunction(() => state.saasListingAiGenerationStatus === "completed");
    assert.deepEqual(await first.page.evaluate(() => state.saasListingComposerDraft.fields), nextFields);
    assert.equal(await first.page.evaluate(() => saasListingCloudRecord().status), "saved");
    assert.deepEqual(first.errors, []); assert.deepEqual(unexpected, []);
  } finally { release.resolve(); await first.context.close(); }
});

test("a newer device checkpoint rejects the frozen revision and refresh does not silently adopt its unapplied rewrite", async () => {
  reset();
  generationHandler = async (_request, res) => {
    head = checkpoint({ ...previousFields, title: "Other device title" }, 2, "other-device-saved", originalReport.report_id);
    currentBase = rewriteReport;
    json(res, 201, { status: "completed", report: rewriteReport, listing_project_identity: identity }); return true;
  };
  const first = await device(); let second;
  try {
    await first.page.getByRole("button", { name: "让 AI 重写买家文案", exact: true }).click();
    await first.page.waitForFunction(() => state.saasListingAiGenerationStatus === "completed");
    assert.deepEqual(await first.page.evaluate(() => state.saasListingComposerDraft.fields), previousFields);
    assert.equal(await first.page.evaluate(() => saasListingCloudRecord().status), "conflict");
    const attempts = requests.filter((r) => r.path === checkpointPath && r.body?.base_report_id === rewriteReport.report_id);
    assert.equal(attempts.length, 1); assert.equal(attempts[0].body.expected_revision, 1);
    assert.equal(head.fields.title, "Other device title");
    await first.page.getByRole("button", { name: "让 AI 重写买家文案", exact: true }).click();
    assert.equal(requests.filter((r) => r.path === generationPath).length, 1);
    second = await device(rewriteReport);
    assert.deepEqual(await second.page.evaluate(() => state.saasListingComposerDraft.fields), previousFields);
    assert.equal(await second.page.evaluate(() => saasListingCloudRecord().status), "conflict");
    assert.equal(await second.page.getByText("查看重写前文案", { exact: true }).count(), 1);
    assert.deepEqual(first.errors, []); assert.deepEqual(second.errors, []); assert.deepEqual(unexpected, []);
  } finally { await first.context.close(); if (second) await second.context.close(); }
});

test("an uncertain adoption response keeps copy until a read reconciles the committed checkpoint and never reruns the model", async () => {
  reset();
  checkpointHandler = async (request, res) => {
    if (request.method !== "POST" || request.body.base_report_id !== rewriteReport.report_id) return false;
    head = checkpoint(request.body.fields, 2, request.body.mutation_id);
    // A truncated acknowledgement after headers avoids Chromium's own transport
    // retry of a socket closed before any response (not an application retry).
    res.writeHead(200, { "content-type": "application/json" }); res.end('{"status":"saved"'); return true;
  };
  const first = await device(); let second;
  try {
    await first.page.getByRole("button", { name: "让 AI 重写买家文案", exact: true }).click();
    await first.page.waitForFunction(() => state.saasListingAiGenerationStatus === "completed");
    assert.deepEqual(await first.page.evaluate(() => state.saasListingComposerDraft.fields), previousFields);
    assert.match(await first.page.locator('[data-saas-listing-ai-feedback]').textContent(), /新文案已生成.*采用/);
    assert.equal(requests.filter((r) => r.path === generationPath).length, 1);
    assert.equal(requests.filter((r) => r.body?.base_report_id === rewriteReport.report_id).length, 1);
    second = await device(rewriteReport);
    assert.deepEqual(await second.page.evaluate(() => state.saasListingComposerDraft.fields), nextFields);
    assert.equal(requests.filter((r) => r.path === generationPath).length, 1);
    assert.deepEqual(first.errors, []); assert.deepEqual(second.errors, []); assert.deepEqual(unexpected, []);
  } finally { await first.context.close(); if (second) await second.context.close(); }
});

test("a lost generation acknowledgement is not reported as failure and is reconciled without a second model request", async () => {
  reset();
  generationHandler = async (_request, res) => { currentBase = rewriteReport;
    res.writeHead(200, { "content-type": "application/json" }); res.end('{"status":"completed"'); return true; };
  const first = await device();
  try {
    await first.page.getByRole("button", { name: "让 AI 重写买家文案", exact: true }).click();
    await first.page.waitForFunction(() => !saasListingAiGenerationInFlight.size);
    assert.match(await first.page.locator('[data-saas-listing-ai-feedback]').textContent(), /生成结果尚未确认/);
    assert.doesNotMatch(await first.page.locator('[data-saas-listing-ai-feedback]').textContent(), /AI 草稿未生成/);
    assert.equal(await first.page.evaluate(() => Object.values(localStorage).some((value) => String(value).includes("generation_uncertain"))), true);
    assert.deepEqual(await first.page.evaluate(() => state.saasListingComposerDraft.fields), previousFields);
    await first.page.getByRole("button", { name: "让 AI 重写买家文案", exact: true }).click();
    assert.equal(requests.filter((r) => r.path === generationPath).length, 1);
    await first.page.evaluate(async () => { await hydrateSaasListingCloudCheckpoint({ force: true }); renderProductListingCenter(); });
    assert.deepEqual(await first.page.evaluate(() => state.saasListingComposerDraft.fields), previousFields);
    assert.equal(await first.page.getByText("查看重写前文案", { exact: true }).count(), 1);
    assert.deepEqual(first.errors, []); assert.deepEqual(unexpected, []);
  } finally { await first.context.close(); }
});

test("a definite pre-model source failure preserves copy and permits only a second explicit rewrite click", async () => {
  reset(); let attempts = 0;
  generationHandler = async (request, res) => {
    attempts += 1;
    if (attempts === 1) { json(res, 503, sourceUnavailableFailure); return true; }
    const report = JSON.parse(JSON.stringify(rewriteReport));
    report.report.listing_handoff.listing_fields.buyer_copy_rewrite.expected_checkpoint_revision = request.body.expected_checkpoint_revision;
    currentBase = report;
    json(res, 201, { status: "completed", report, listing_project_identity: identity }); return true;
  };
  const first = await device();
  try {
    const firstResponse = first.page.waitForResponse((r) => new URL(r.url()).pathname === generationPath && r.request().method() === "POST");
    await first.page.getByRole("button", { name: "让 AI 重写买家文案", exact: true }).click();
    assert.equal((await firstResponse).status(), 503);
    await first.page.waitForFunction(() => !saasListingAiGenerationRequest);
    assert.deepEqual(await first.page.evaluate(() => state.saasListingComposerDraft.fields), previousFields);
    assert.equal(attempts, 1, "pre-model rejection does not automatically retry the generation request");
    const retried = first.page.waitForResponse((r) => new URL(r.url()).pathname === generationPath && r.request().method() === "POST",
      { timeout: 3000 }).then((response) => response, () => null);
    await first.page.getByRole("button", { name: "让 AI 重写买家文案", exact: true }).click();
    const response = await retried;
    assert.ok(response, "a second deliberate click can retry after the server definitively rejected before model use");
    assert.equal(response.status(), 201);
    await first.page.waitForFunction(() => state.saasListingComposerDraft.fields.title === "Foldable Aluminum Tablet Stand");
    assert.equal(attempts, 2);
    assert.deepEqual(first.errors, []); assert.deepEqual(unexpected, []);
  } finally { await first.context.close(); }
});

async function assertUncertainSourceFailure(payload, label, httpStatus = 503) {
  reset(); let attempts = 0;
  generationHandler = async (_request, res) => { attempts += 1; json(res, httpStatus, payload); return true; };
  const first = await device();
  try {
    await first.page.getByRole("button", { name: "让 AI 重写买家文案", exact: true }).click();
    await first.page.waitForFunction(() => !saasListingAiGenerationRequest);
    assert.equal(await first.page.evaluate(() => state.saasListingComposerDraft.ai_generation_feedback.status), "generation_uncertain", label);
    assert.deepEqual(await first.page.evaluate(() => state.saasListingComposerDraft.fields), previousFields, label);
    assert.equal(attempts, 1, label);
    await first.page.getByRole("button", { name: "让 AI 重写买家文案", exact: true }).click();
    await first.page.waitForFunction(() => !saasListingAiGenerationRequest);
    assert.equal(attempts, 1, `${label}: unknown response cannot authorize another model request`);
    assert.deepEqual(first.errors, []); assert.deepEqual(unexpected, []);
  } finally { await first.context.close(); }
}

test("a source-unavailable 503 missing any required envelope field remains uncertain", async () => {
  for (const key of Object.keys(sourceUnavailableFailure)) {
    const incomplete = { ...sourceUnavailableFailure }; delete incomplete[key];
    await assertUncertainSourceFailure(incomplete, `missing ${key}`);
  }
});

test("false-like strings in source-unavailable safety or usage fields cannot authorize retry", async () => {
  for (const key of ["model_called", "usage_consumed", "real_platform_writes_enabled", "secret_exposed"]) {
    await assertUncertainSourceFailure({ ...sourceUnavailableFailure, [key]: "false" }, `${key} is a string`);
  }
});

test("task or persistence-phase fields cannot turn an ambiguous 503 into a pre-model rejection", async () => {
  const additions = [{ task_id: "task_possible_generation" }, { task_id: null },
    { report_save_attempted: true }, { report_save_attempted: false },
    { model_usage: { request_count: 1 } }, { model_usage: { request_count: 0 } }];
  for (const extra of additions) {
    await assertUncertainSourceFailure({ ...sourceUnavailableFailure, ...extra }, `additional ${Object.keys(extra)[0]}`);
  }
});

test("only the exact blocked source code, singleton reason and null report prove a pre-model rejection", async () => {
  const changes = [{ status: "failed" }, { failure_code: "listing_model_generation_failed" },
    { blocked_by: [] }, { blocked_by: [sourceUnavailableFailure.failure_code, sourceUnavailableFailure.failure_code] },
    { blocked_by: sourceUnavailableFailure.failure_code }, { report: { report_id: "possible_generated_report" } }];
  for (const change of changes) {
    await assertUncertainSourceFailure({ ...sourceUnavailableFailure, ...change }, `inconsistent ${Object.keys(change)[0]}`);
  }
});

test("a source-shaped envelope on any other server error does not unlock blind retry", async () => {
  for (const status of [500, 502, 504]) await assertUncertainSourceFailure(sourceUnavailableFailure, `HTTP ${status}`, status);
});

test("a complete pre-report terminal failure permits an explicit retry, while attempted or unknown 502 results stay uncertain", async () => {
  const complete = { status: "failed", failure_code: "listing_model_output_marketplace_language", task_id: "task_rewrite_quality_failed",
    model_called: true, usage_consumed: true, model_usage: { request_count: 2 }, report: null,
    real_platform_writes_enabled: false, secret_exposed: false, report_save_attempted: false,
    merchant_message: "AI 返回的文案未通过检查，本次没有保存 Listing。" };
  const { report_save_attempted: _marker, ...withoutMarker } = complete;
  const cases = [complete, { ...complete, report_save_attempted: true }, withoutMarker,
    { ...complete, report_save_attempted: "false" }, { status: "failed", failure_code: complete.failure_code, report: null }];
  for (const [index, payload] of cases.entries()) {
    const terminal = index === 0;
    reset(); let attempts = 0;
    generationHandler = async (request, res) => {
      attempts += 1;
      if (attempts === 1) { json(res, 502, payload); return true; }
      const report = JSON.parse(JSON.stringify(rewriteReport));
      report.report.listing_handoff.listing_fields.buyer_copy_rewrite.expected_checkpoint_revision = request.body.expected_checkpoint_revision;
      currentBase = report;
      json(res, 201, { status: "completed", report, listing_project_identity: identity }); return true;
    };
    const first = await device();
    try {
      await first.page.getByRole("button", { name: "让 AI 重写买家文案", exact: true }).click();
      await first.page.waitForFunction(() => !saasListingAiGenerationRequest);
      assert.equal(await first.page.evaluate(() => state.saasListingComposerDraft.ai_generation_feedback.status), terminal ? "failed" : "generation_uncertain");
      if (terminal) assert.match(await first.page.locator('[data-saas-listing-ai-feedback]').textContent(), /再次点击“让 AI 重写买家文案”/);
      assert.deepEqual(await first.page.evaluate(() => state.saasListingComposerDraft.fields), previousFields);
      assert.equal(attempts, 1, "there is no automatic model retry");
      await first.page.getByRole("button", { name: "让 AI 重写买家文案", exact: true }).click();
      if (terminal) await first.page.waitForFunction(() => state.saasListingComposerDraft.fields.title === "Foldable Aluminum Tablet Stand");
      assert.equal(attempts, terminal ? 2 : 1);
      assert.deepEqual(first.errors, []); assert.deepEqual(unexpected, []);
    } finally { await first.context.close(); }
  }
});

test("a foreign or malformed rewrite receipt is never cached as a current-account report", async () => {
  for (const kind of ["company", "candidate", "snapshot"]) {
    reset();
    const bad = structuredClone(rewriteReport); bad.report_id = `untrusted-${kind}-report`;
    if (kind === "company") bad.company_id = "untrusted-other-company";
    if (kind === "candidate") bad.report.listing_project_identity.candidate_id = "untrusted-other-candidate";
    if (kind === "snapshot") bad.report.listing_handoff.listing_fields.buyer_copy_rewrite.fields.price = "untrusted-price-change";
    generationHandler = async (_request, res) => { json(res, 201, { status: "completed", report: bad, listing_project_identity: identity }); return true; };
    const first = await device();
    try {
      await first.page.getByRole("button", { name: "让 AI 重写买家文案", exact: true }).click();
      await first.page.waitForFunction(() => !saasListingAiGenerationInFlight.size);
      const persisted = await first.page.evaluate(() => JSON.stringify([state.saasReports, state.saasListingComposerDraft, Object.entries(localStorage)]));
      assert.doesNotMatch(persisted, /untrusted-/);
      assert.deepEqual(await first.page.evaluate(() => state.saasListingComposerDraft.fields), previousFields);
      assert.equal(requests.filter((r) => r.body?.base_report_id === bad.report_id).length, 0);
      assert.deepEqual(first.errors, []); assert.deepEqual(unexpected, []);
    } finally { await first.context.close(); }
  }
});

test("an actual unauthorized adoption response remains forbidden and does not retry or erase the existing copy", async () => {
  reset();
  checkpointHandler = async (request, res) => {
    if (request.method !== "POST" || request.body.base_report_id !== rewriteReport.report_id) return false;
    json(res, 401, { error: "session_expired" }); return true;
  };
  const first = await device();
  try {
    await first.page.getByRole("button", { name: "让 AI 重写买家文案", exact: true }).click();
    await first.page.waitForFunction(() => state.saasListingAiGenerationStatus === "completed");
    assert.equal(await first.page.evaluate(() => saasListingCloudRecord().status), "forbidden");
    assert.deepEqual(await first.page.evaluate(() => state.saasListingComposerDraft.fields), previousFields);
    assert.match(await first.page.locator('[data-saas-listing-ai-feedback]').textContent(), /新文案已生成/);
    assert.equal(requests.filter((r) => r.body?.base_report_id === rewriteReport.report_id).length, 1);
    assert.equal(requests.filter((r) => r.path === generationPath).length, 1);
    assert.deepEqual(first.errors, []); assert.deepEqual(unexpected, []);
  } finally { await first.context.close(); }
});

test("late generation and adoption responses cannot change a different company, user, store or project", async () => {
  for (const phase of ["generation", "adoption"]) for (const scope of ["company", "user", "store", "project"]) {
    reset(); const entered = deferred(), release = deferred();
    if (phase === "generation") generationHandler = async (_request, res) => { entered.resolve(); await release.promise;
      currentBase = rewriteReport; json(res, 201, { status: "completed", report: rewriteReport, listing_project_identity: identity }); return true; };
    else checkpointHandler = async (request) => { if (request.method === "POST" && request.body.base_report_id === rewriteReport.report_id) {
      entered.resolve(); await release.promise; } return false; };
    const first = await device();
    try {
      await first.page.getByRole("button", { name: "让 AI 重写买家文案", exact: true }).click(); await entered.promise;
      await first.page.evaluate((scope) => {
        invalidateSaasListingAiGenerationContext();
        if (scope === "company") { state.saasCompany.company_id = "different-company"; state.saasIdentity.company_id = "different-company"; }
        if (scope === "user") { state.saasUser.user_id = "different-user"; state.saasIdentity.user_id = "different-user"; }
        if (scope === "store") { state.saasStores.unshift({ store_id: "different-store", platform: "ebay", marketplace: "EBAY_US" }); localStorage.setItem(saasStorageKeys.storeId, "different-store"); }
        if (scope === "project") state.saasListingComposerDraft.listing_project_identity = { key: "different-project", source_report_id: "different-source", candidate_id: "different-candidate" };
        state.saasListingComposerDraft.fields.title = "Current scope merchant title";
        state.saasListingComposerDraft.ai_generation_feedback = null;
      }, scope);
      release.resolve(); await first.page.waitForFunction(() => !saasListingAiGenerationInFlight.size);
      assert.equal(await first.page.evaluate(() => state.saasListingComposerDraft.fields.title), "Current scope merchant title");
      assert.equal(await first.page.evaluate(() => state.saasReports.some((r) => r.report_id === "rewrite-generated-report")), false);
      assert.equal(await first.page.evaluate(() => state.saasListingComposerDraft.ai_generation_feedback), null);
      assert.deepEqual(first.errors, []); assert.deepEqual(unexpected, []);
    } finally { release.resolve(); await first.context.close(); }
  }
});

test("a fresh report restore keeps old copy before checkpoint adoption and history wraps on a tablet", async () => {
  reset(); currentBase = rewriteReport;
  const first = await device(rewriteReport);
  try {
    await first.page.setViewportSize({ width: 768, height: 1024 });
    await first.page.evaluate(() => {
      state.saasListingComposerDraft = null;
      restoreSaasListingComposerDraftFromBackendReports({ preferBackendLatest: true, projectId: "rewrite-tablet" });
      document.querySelector("#view-product").innerHTML = renderSaasListingDraftEditor();
    });
    assert.deepEqual(await first.page.evaluate((keys) => Object.fromEntries(keys.map((key) => [key, state.saasListingComposerDraft.fields[key]])), fieldKeys), previousFields);
    assert.equal(await first.page.evaluate(() => state.saasListingComposerDraft.model_generated), false);
    await first.page.getByText("查看重写前文案", { exact: true }).click();
    const wraps = await first.page.locator('[data-saas-listing-copy-history] pre').evaluateAll((rows) => rows.every((row) =>
      getComputedStyle(row).whiteSpace === "pre-wrap" && getComputedStyle(row).overflowWrap === "anywhere"));
    assert.equal(wraps, true);
    assert.equal(requests.filter((r) => r.method === "POST").length, 0);
    assert.deepEqual(first.errors, []); assert.deepEqual(unexpected, []);
  } finally { await first.context.close(); }
});

test("an adopted verified rewrite with no remaining edited fields reaches prefill, but old copy or changed facts cannot borrow that proof", async () => {
  reset(); currentBase = structuredClone(rewriteReport);
  currentBase.report.listing_handoff.listing_fields.buyer_copy_rewrite.merchant_edited_fields = [];
  currentBase.report.listing_handoff.listing_fields.buyer_copy_rewrite.previous_merchant_edited_fields = [...copyKeys];
  head = checkpoint(nextFields, 2, "verified-rewrite-adoption"); head.merchant_edited_fields = [];
  const first = await device(currentBase);
  try {
    const outcomes = await first.page.evaluate(({ nextFields, previousFields }) => {
      const draft = state.saasListingComposerDraft;
      draft.source_type = "ai_ceo_product_vision"; draft.buyer_copy_requires_validated_listing_generation = true;
      draft.publish_prefill = { description_html: "Obsolete description before rewrite", quantity: "7" };
      const read = () => { const values = saasPublishIntakePrefillValues(); return { title: values.title, description: values.description_html, quantity: values.quantity }; };
      const valid = read();
      draft.fields = { ...previousFields }; const oldCopy = read();
      draft.fields = { ...nextFields }; draft.merchant_product_fact_packet.merchant_confirmed_facts.material = "Steel"; const factsChanged = read();
      draft.merchant_product_fact_packet.merchant_confirmed_facts.material = "Aluminum"; state.saasReports = []; const noReport = read();
      return { valid, oldCopy, factsChanged, noReport };
    }, { nextFields, previousFields });
    assert.equal(outcomes.valid.title, nextFields.title);
    assert.equal(outcomes.valid.description, `${nextFields.selling_points}\n\n${nextFields.description}`);
    assert.equal(outcomes.valid.quantity, "7");
    for (const key of ["oldCopy", "factsChanged", "noReport"]) assert.equal(outcomes[key].title, "", key);
    assert.equal(requests.filter((r) => r.method === "POST").length, 0);
    assert.deepEqual(first.errors, []); assert.deepEqual(unexpected, []);
  } finally { await first.context.close(); }
});

test("a rejected rewrite remains in history but an authoritative read and explicit keep-local restore normal saving", async () => {
  reset();
  checkpointHandler = async (request, res) => {
    if (request.method !== "POST" || request.body.base_report_id !== rewriteReport.report_id) return false;
    currentBase = originalReport; supersededIds = [rewriteReport.report_id];
    head = checkpoint({ ...previousFields, title: "Other device changed title" }, 2, "other-device-mutation", originalReport.report_id);
    json(res, 409, { status: "conflict", current_revision: 2, latest_checkpoint: head,
      current_base_report_id: originalReport.report_id, current_base_report: originalReport,
      superseded_rewrite_report_ids: supersededIds }); return true;
  };
  const first = await device();
  try {
    await first.page.getByRole("button", { name: "让 AI 重写买家文案", exact: true }).click();
    await first.page.waitForFunction(() => state.saasListingAiGenerationStatus === "completed");
    assert.equal(await first.page.evaluate(() => saasListingCloudRecord().status), "conflict");
    assert.deepEqual(await first.page.evaluate(() => state.saasListingComposerDraft.fields), previousFields);
    // 409 itself is not our source-selection authority: the next authenticated
    // GET supplies scoped, irreversibly invalidated IDs before keep-local saves.
    await first.page.locator('[data-saas-listing-cloud-action="keep-local"]').click();
    await first.page.waitForFunction(() => saasListingCloudRecord().status === "saved", null, { timeout: 8000 });
    await first.page.waitForFunction(() => state.saasListingComposerDraft.ai_generation_feedback === null, null, { timeout: 8000 });
    assert.equal(head.base_report_id, originalReport.report_id); assert.deepEqual(head.fields, previousFields);
    assert.equal(await first.page.evaluate(() => saasListingCloudBaseReport(saasListingCloudContext()).report_id), originalReport.report_id);
    assert.equal(await first.page.evaluate(() => state.saasListingComposerDraft.ai_generation_feedback), null);
    assert.equal(await first.page.evaluate(() => state.saasReports.some((r) => r.report_id === "rewrite-generated-report")), true);
    assert.equal(await first.page.getByText("查看重写前文案", { exact: true }).count(), 1);
    const unauthorizedProof = await first.page.evaluate(() => {
      const active = state.saasReports.find((r) => r.report_id === "rewrite-original-report");
      state.saasReports = state.saasReports.filter((r) => r !== active);
      const draft = state.saasListingComposerDraft;
      draft.fields = { ...saasListingBuyerCopyRewriteForDraft().fields };
      draft.merchant_edited_fields = [];
      const proof = saasListingMerchantEditHasValidatedBase(draft);
      const restored = saasListingDraftFromReport(state.saasReports[0]);
      state.saasReports.push(active);
      return { proof, restored };
    });
    assert.equal(unauthorizedProof.proof, false); assert.equal(unauthorizedProof.restored, null);
    await first.page.evaluate(async () => { await hydrateSaasListingCloudCheckpoint({ force: true }); renderProductListingCenter(); });
    await first.page.locator('[data-saas-listing-draft-field="price"]').fill("38.00 USD");
    await first.page.evaluate(() => flushSaasListingCloudCheckpoint());
    assert.equal(head.fields.price, "38.00 USD"); assert.equal(head.fields.title, previousFields.title);
    assert.equal(requests.filter((r) => r.path === generationPath).length, 1, "recovery is not another AI request");
    assert.deepEqual(first.errors, []); assert.deepEqual(unexpected, []);
  } finally { await first.context.close(); }
});

test("a later authenticated adopted checkpoint supersedes an older read exclusion without reviving other invalid rewrites", async () => {
  reset();
  const other = JSON.parse(JSON.stringify(rewriteReport));
  other.report_id = "rewrite-other-invalid"; other.created_at = "2026-09-09T04:00:00Z";
  head = checkpoint(previousFields, 1, "old-checkpoint", originalReport.report_id);
  supersededIds = [rewriteReport.report_id, other.report_id];
  const first = await device();
  try {
    await first.page.evaluate(({ report, other }) => state.saasReports.push(report, other), { report: rewriteReport, other });
    assert.equal(await first.page.evaluate(() => saasListingCloudBaseReport(saasListingCloudContext()).report_id), originalReport.report_id);
    assert.deepEqual(await first.page.evaluate(() => state.saasListingComposerDraft.fields), previousFields);
    // The prior GET crossed another device's adoption and carried old A/R.
    // This later full-scope GET is positive proof that N/R+1 is now adopted.
    currentBase = rewriteReport; head = checkpoint(nextFields, 2, "other-device-adopted");
    supersededIds = [other.report_id];
    assert.equal(await first.page.evaluate(() => hydrateSaasListingCloudCheckpoint({ force: true })), true);
    assert.deepEqual(await first.page.evaluate(() => state.saasListingComposerDraft.fields), nextFields);
    assert.equal(await first.page.evaluate(() => saasListingCloudBaseReport(saasListingCloudContext()).report_id), rewriteReport.report_id);
    const retained = await first.page.evaluate(() => {
      const excluded = state.saasReports.find((r) => r.report_id === "rewrite-other-invalid");
      return { excluded: saasListingRewriteReportIsSuperseded(excluded), restored: saasListingDraftFromReport(excluded),
        history: state.saasReports.some((r) => r.report_id === "rewrite-other-invalid") };
    });
    assert.deepEqual(retained, { excluded: true, restored: null, history: true });
    // A self-contradictory current response is still rejected; positive proof
    // does not authorize ignoring the exclusion checks in the same envelope.
    supersededIds = [rewriteReport.report_id, other.report_id];
    assert.equal(await first.page.evaluate(() => hydrateSaasListingCloudCheckpoint({ force: true })), false);
    assert.equal(await first.page.evaluate(() => saasListingCloudRecord().status), "error");
    assert.deepEqual(await first.page.evaluate(() => state.saasListingComposerDraft.fields), nextFields);
    assert.equal(requests.filter((r) => r.method === "POST").length, 0);
    assert.deepEqual(first.errors, []); assert.deepEqual(unexpected, []);
  } finally { await first.context.close(); }
});

test("real stylesheet keeps rewrite controls and old-copy history inside desktop and tablet editors", async () => {
  const output = fs.mkdtempSync(path.join(os.tmpdir(), "jiejing-buyer-copy-rewrite-ui-"));
  for (const width of [1440, 768]) {
    reset(); currentBase = rewriteReport; head = checkpoint(nextFields, 2, "visual-adopted-rewrite");
    const first = await device(rewriteReport, { visual: true, width });
    try {
      await first.page.getByText("查看重写前文案", { exact: true }).click();
      const layout = await first.page.locator(".saas-listing-v2-draft-editor").evaluate((editor) => {
        const bounds = editor.getBoundingClientRect();
        const controls = [...editor.querySelectorAll('[data-saas-action="listing-rewrite-buyer-copy"], [data-saas-listing-draft-field="title"], [data-saas-listing-draft-field="description"], [data-saas-listing-copy-history]')];
        const copyButton = controls[0].getBoundingClientRect();
        const title = editor.querySelector('[data-saas-listing-draft-field="title"]').getBoundingClientRect();
        return { editorFits: editor.scrollWidth <= editor.clientWidth + 1,
          pageFits: document.documentElement.scrollWidth <= window.innerWidth + 1,
          controlsFit: controls.every((item) => { const box = item.getBoundingClientRect(); return box.left >= bounds.left - 1 && box.right <= bounds.right + 1; }),
          copyIsPrimary: title.width > copyButton.width && title.top >= copyButton.bottom };
      });
      assert.deepEqual(layout, { editorFits: true, pageFits: true, controlsFit: true, copyIsPrimary: true });
      const screenshot = path.join(output, `rewrite-editor-${width}.png`);
      await first.page.locator(".saas-listing-v2-draft-editor").screenshot({ path: screenshot });
      console.log(JSON.stringify({ rewrite_ui_evidence: { width, screenshot, stylesheet: "styles.css", app_inline_guards_retained: true } }));
      assert.deepEqual(first.errors, []); assert.deepEqual(unexpected, []);
    } finally { await first.context.close(); }
  }
});
