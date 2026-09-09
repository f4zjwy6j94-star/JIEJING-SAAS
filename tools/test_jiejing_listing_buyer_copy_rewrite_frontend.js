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
let server, browser, base, head, currentBase, requests, unexpected, generationHandler, checkpointHandler, supersededIds;
function reset() { head = null; currentBase = originalReport; requests = []; unexpected = []; generationHandler = null; checkpointHandler = null; supersededIds = []; }
function json(res, status, body) { res.writeHead(status, { "content-type": "application/json", "cache-control": "no-store" }); res.end(JSON.stringify(body)); }
function checkpoint(fields, revision, mutation, reportId = currentBase.report_id) { return { checkpoint_id: `rewrite-edit-${revision}`, revision,
  mutation_id: mutation, company_id: companyId, store_id: storeId, listing_project_identity: identity, base_report_id: reportId,
  fields: { ...fields }, merchant_edited_fields: ["price"], saved_at: "2026-09-09T03:00:00Z", source: "merchant_edit" }; }
function deferred() { let resolve; const promise = new Promise((done) => { resolve = done; }); return { promise, resolve }; }
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
    if (![checkpointPath, generationPath].includes(url.pathname)) { unexpected.push(`${req.method} ${url.pathname}`); return json(res, 404, {}); }
    let raw = ""; for await (const chunk of req) raw += chunk;
    const request = { method: req.method, path: url.pathname, body: raw ? JSON.parse(raw) : null };
    requests.push(request);
    if (url.pathname === generationPath && req.method === "POST") {
      if (generationHandler && await generationHandler(request, res)) return;
      currentBase = rewriteReport;
      return json(res, 201, { status: "completed", report: rewriteReport, listing_project_identity: identity, missing_fields: [] });
    }
    if (checkpointHandler && await checkpointHandler(request, res)) return;
    if (req.method === "GET") return json(res, 200, { status: head ? "saved" : "empty", checkpoint: head,
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
