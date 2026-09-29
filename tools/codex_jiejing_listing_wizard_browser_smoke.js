#!/usr/bin/env node
"use strict";
// Real app renderers and input/click handlers; an owned loopback HTTP fixture
// supplies scoped save receipts. No real account, model or platform exists.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const os = require("node:os");
const http = require("node:http");
const { chromium } = require("../output/codex-playwright-deps/node_modules/playwright-core");
const root = path.resolve(__dirname, "..");
const output = fs.mkdtempSync(path.join(os.tmpdir(), "jiejing-listing-wizard-"));
const identity = { key: "wizard-tablet", source_report_id: "wizard-origin", candidate_id: "wizard-candidate" };
const company = "wizard-company", user = "wizard-user", store = "wizard-store";
const fields = { title: "Aluminum Tablet Stand", selling_points: "Aluminum construction\nDesktop support\nPortable stand", description: "An aluminum desktop tablet stand.", category: "Tablet Stands", item_specifics: "Material: Aluminum", images: "", price: "", logistics: "", keywords: "", risk_notes: "" };
const packet = { contract_version: "merchant_product_fact_packet_v1", source: "merchant_input", product_name: "Tablet Stand",
  source_confirmed_facts: {}, merchant_confirmed_facts: { product_name: "Tablet Stand", condition: "NEW", material: "Aluminum" }, derived_listing_suggestions: {}, unknown_facts: ["image_urls", "image_rights_confirmed", "quantity"], source_records: [], secret_exposed: false };
let revision = 0, checkpoint = null, factNumber = 0, mode = "ok", calls = [], unexpected = [], releaseFact = null;
let factPacket = structuredClone(packet);
let baseReport = { report_id: "wizard-listing", task_id: "wizard-task", report_type: "listing.package", company_id: company, store_id: store,
  status: "saved", created_at: "2026-09-29T00:00:00Z", report: { product: "Tablet Stand", listing_project_identity: identity,
    listing_handoff: { ready_for_listing_draft: true, listing_fields: { ...fields, description_seed: fields.description } } } };
const source = fs.readFileSync(path.join(root, "app.js"), "utf8").replace(/exposeLocalJiejingTestHooks\(\);\r?\ninit\(\);\r?\nrunLocalJiejingQaScenarioFromUrl\(\);\s*$/, "exposeLocalJiejingTestHooks();\n");
const html = fs.readFileSync(path.join(root, "app.html"), "utf8").replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, "")
  .replace(/<link\b[^>]*>/gi, "").replace("</head>", '<link rel="stylesheet" href="/styles.css"></head>')
  .replace("</body>", '<script src="/app.js"></script></body>');
function send(res, status, payload) { res.writeHead(status, { "content-type": "application/json" }); res.end(JSON.stringify(payload)); }
const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, "http://127.0.0.1");
  if (req.method === "GET" && url.pathname === "/app.html") { res.writeHead(200, { "content-type": "text/html" }); return res.end(html); }
  if (req.method === "GET" && url.pathname === "/app.js") { res.writeHead(200, { "content-type": "text/javascript" }); return res.end(source); }
  if (req.method === "GET" && (url.pathname === "/styles.css" || /^\/assets\/[a-zA-Z0-9/_.,-]+$/.test(url.pathname))) {
    const file = path.join(root, url.pathname.slice(1));
    if (fs.existsSync(file)) { res.writeHead(200, { "content-type": url.pathname.endsWith(".css") ? "text/css" : url.pathname.endsWith(".svg") ? "image/svg+xml" : "image/png" }); return res.end(fs.readFileSync(file)); }
  }
  if (req.method === "GET" && url.pathname === `/stores/${store}/merchant-project-status`) return send(res, 200, { merchant_project_status: null });
  const checkpointPath = `/stores/${store}/listing-drafts/${identity.key}/checkpoint`;
  if (req.method === "GET" && url.pathname === checkpointPath) {
    calls.push("checkpoint-read");
    return send(res, 200, { checkpoint, current_revision: revision, current_base_report_id: baseReport.report_id, current_base_report: baseReport });
  }
  if (req.method === "POST" && [checkpointPath, `/stores/${store}/product-facts`].includes(url.pathname)) {
    let text = ""; for await (const chunk of req) text += chunk;
    const payload = JSON.parse(text); calls.push({ path: url.pathname, payload });
    if (url.pathname.endsWith("product-facts")) {
      if (mode === "facts-fail") return send(res, 503, { error: "fixture_save_unavailable" });
      if (mode === "facts-delay") await new Promise(resolve => { releaseFact = resolve; });
      factPacket = payload.merchant_product_fact_packet;
      factNumber += 1;
      const report = { ...baseReport, report_id: `wizard-facts-${factNumber}`, report_type: "merchant.product_facts", created_at: new Date().toISOString(),
        report: { product_name: "Tablet Stand", listing_project_identity: identity, merchant_product_fact_packet: factPacket } };
      baseReport = report;
      return send(res, 201, { is_current: true, status: "saved", report, listing_project_identity: identity, merchant_product_fact_packet: factPacket });
    }
    if (mode === "copy-fail") return send(res, 503, { error: "fixture_checkpoint_unavailable" });
    if (mode === "copy-conflict") return send(res, 409, { latest_checkpoint: checkpoint, current_revision: revision, current_base_report_id: baseReport.report_id, current_base_report: baseReport });
    revision += 1;
    checkpoint = { checkpoint_id: `wizard-checkpoint-${revision}`, revision, mutation_id: payload.mutation_id, company_id: company, store_id: store,
      listing_project_identity: identity, base_report_id: payload.base_report_id, fields: payload.fields, merchant_edited_fields: payload.merchant_edited_fields,
      saved_at: new Date().toISOString(), source: "merchant_edit" };
    return send(res, 201, { status: "saved", checkpoint });
  }
  unexpected.push(`${req.method} ${url.pathname}`); send(res, 404, { error: "fixture_blocks_other_api" });
});
const errors = [], consoleIssues = [], screenshots = [], checks = [];
let browser;
async function bootstrap(page, base, options = {}) {
  await page.evaluate(({ company, user, store, identity, baseReport, factPacket, fields, base, options }) => {
    window.__JIEJING_FORCE_PUBLIC_MVP__ = true;
    localStorage.setItem(saasStorageKeys.storeId, store); localStorage.setItem(saasStorageKeys.sessionHint, "1");
    state.saasApiBase = base; state.saasToken = "isolated-fixture";
    state.saasIdentity = { user_id: user, company_id: company, role: "owner" };
    state.saasUser = { user_id: user, email: "wizard@example.test" }; state.saasCompany = { company_id: company };
    state.saasStores = [{ store_id: store, company_id: company, platform: "ebay", marketplace: "EBAY_US", status: "authorized" }];
    state.saasConnected = true; state.saasProtectedStateReady = true; state.saasProtectedStateFromCache = false;
    state.saasPermissions = ["create_task", "view_report"]; state.saasLoading = false;
    state.saasReports = [baseReport]; state.saasTasks = []; state.saasListingMode = "single";
    state.saasListingComposerDraft = { product: "Tablet Stand", title: fields.title, fields: { ...fields }, listing_project_identity: identity,
      source_product_fact_report_id: baseReport.report_type === "merchant.product_facts" ? baseReport.report_id : "",
      merchant_product_fact_packet: factPacket, merchant_edited_fields: [] };
    state.saasAccountHealth = { store_id: store, company_id: company, status: "restricted", incident_mode: true, can_execute_real_writes: false };
    state.view = "product"; syncSaasPublicMvpMode(); bindEvents();
    [entryShell, siteShell, onboardingShell].forEach(shell => shell.classList.add("is-hidden")); appShell.classList.remove("is-hidden");
    document.documentElement.classList.add("app-ready"); document.documentElement.classList.remove("app-shell-empty", "app-auth-pending");
    document.body.classList.remove("site-locked"); document.body.dataset.view = "product";
    document.querySelectorAll(".view").forEach(view => view.classList.toggle("is-active", view.id === "view-product"));
    document.querySelectorAll(".nav-item").forEach(item => item.classList.toggle("is-active", item.dataset.view === "product"));
    if (options.startStep) setSaasListingWizardStep(options.startStep);
    renderProductListingCenter();
  }, { company, user, store, identity, baseReport, factPacket, fields, base, options });
}
async function step(page, value) { await page.waitForSelector(`[data-listing-wizard-step="${value}"]`); assert.equal(await page.locator("[data-listing-wizard-step]").count(), 1); }
async function next(page) { await page.locator('[data-saas-action="listing-wizard-next"]').click(); }
async function back(page) { await page.locator('[data-saas-action="listing-wizard-previous"]').click(); }
async function screenshot(page, name) { const file = path.join(output, `${name}.png`); await page.screenshot({ path: file }); screenshots.push(file); }
(async () => {
  await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
  const base = `http://127.0.0.1:${server.address().port}`;
  browser = await chromium.launch({ headless: true, channel: process.env.JIEJING_PLAYWRIGHT_CHANNEL || "chrome" });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  await context.route("**/*", route => {
    const url = new URL(route.request().url());
    if (url.origin === base) return route.continue();
    if (url.hostname === "media.example.test") return route.fulfill({ status: 200, contentType: "image/svg+xml", body: '<svg xmlns="http://www.w3.org/2000/svg" width="200" height="200"><rect width="200" height="200" fill="#e7ece9"/></svg>' });
    unexpected.push(`foreign:${route.request().method()}`); return route.abort();
  });
  const page = await context.newPage();
  page.on("pageerror", error => errors.push(error.message));
  page.on("console", message => { if (["warning", "error"].includes(message.type()) && !/503|409/.test(message.text())) consoleIssues.push(message.text()); });
  await page.goto(`${base}/app.html?start=app&qa=public-saas&view=product`);
  await bootstrap(page, base, { startStep: 1 });
  assert((await page.title()).length > 0); assert(page.url().startsWith(base));
  await page.evaluate(() => {
    state.saasListingComposerDraft = null;
    state.saasReports = [];
    state.saasListingComposerInput = "";
    renderProductListingCenter();
  });
  const callsBeforeResearchEntry = calls.length;
  await page.getByRole("button", { name: "去 AI CEO", exact: true }).click();
  assert(await page.locator("#view-cockpit.is-active").isVisible());
  assert(await page.getByRole("textbox", { name: "交给 AI CEO 的问题或商品任务", exact: true }).isVisible());
  assert.equal(calls.length, callsBeforeResearchEntry, "Navigation must not import, generate or save");
  checks.push("empty-account research entry navigates to AI CEO without a business request");
  await page.evaluate(({ identity }) => {
    state.saasMerchantProjectStatus = null;
    state.saasReports = [{ report_id: identity.source_report_id, report_type: "ai_ceo.market_research",
      report: { listing_project_identity: identity, status: "model_answer_rejected", answer_quality: { accepted: false },
        candidate_products: [], source_records: [{ url: "https://example.test/research" }] } }];
    setView("cockpit", { aiCeoTaskContextMode: "active_product_task", aiCeoTaskContextExpanded: true,
      aiCeoTaskContextProjectId: identity.key, aiCeoTaskContextCommandId: "fixture-research" });
  }, { identity });
  const taskContext = page.locator(".saas-ai-ceo-task-context");
  assert(await taskContext.isVisible());
  assert(!(await taskContext.locator('[aria-label="已完成事项"]').innerText()).includes("市场报告"));
  assert((await taskContext.innerText()).includes("商品事实尚未完成核对"));
  await screenshot(page, "research-pending-desktop");
  checks.push("failed research stays pending even before backend status arrives; absent facts stay unverified");
  await page.evaluate(() => {
    const command = { id: "fixture-empty-answer", text: "请新建独立商品项目，调研轻小不带电商品。",
      ai_reply_status: "model_call_failed", ai_reply: "模型没有返回可用正文，本次未生成调研报告或草稿。", route: "ebay_workflow" };
    state.saasLastCeoCommand = command;
    state.saasPendingNewListingProjectRequest = { commandId: command.id, phase: "failed", failureReason: "empty_model_answer" };
    state.saasAiCeoLatestTurn = { assistant_id: "fixture-empty-reply", user_text: command.text,
      assistant_text: command.ai_reply, status: "model_call_failed", route: "ebay_workflow", pending: false,
      store_id: "wizard-store", blocked_by: ["empty_model_answer"], created_at: new Date().toISOString() };
    state.saasAiCeoThread = [state.saasAiCeoLatestTurn];
    setSaasAiCeoTaskContextState("active_product_task", true, { projectId: "", commandId: command.id });
    renderSaasCockpitRealWorkbench();
  });
  for (const width of [1440, 820]) {
    await page.setViewportSize({ width, height: 1000 });
    await page.evaluate(() => { state.aiCeoTaskContextExpanded = true; refreshSaasAiCeoTaskContext(); });
    const detail = page.locator("#saasAiCeoTaskContextDetail");
    assert(await detail.isVisible());
    assert((await detail.innerText()).includes("本次任务未完成"));
    assert(!(await detail.innerText()).includes("正在建立商品任务"));
    assert(!(await page.locator("#ceoChat").innerText()).includes("连接需要先恢复"));
    assert((await page.getByRole("button", { name: "返回本次对话", exact: true }).boundingBox()).height <= 64,
      "task recovery button must not stretch to fill the tablet drawer");
    await screenshot(page, `model-failure-${width}`);
    await page.getByRole("button", { name: "返回本次对话", exact: true }).click();
    assert(!(await detail.isVisible()));
    assert(await page.getByRole("textbox", { name: "交给 AI CEO 的问题或商品任务", exact: true }).isVisible());
  }
  checks.push("empty-answer failure terminates task panel and returns to preserved conversation on desktop and tablet");
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.reload(); await bootstrap(page, base, { startStep: 1 });
  await step(page, 1);
  assert.equal(await page.locator('[data-saas-listing-draft-field="title"]').count(), 0);
  assert.equal(await page.locator('[data-saas-product-fact-field="image_rights_confirmed"]').count(), 0);
  assert.equal(await page.locator("#saasPublishIntakeForm").count(), 0);
  assert.equal(await page.locator('.saas-listing-wizard-other-facts').getAttribute("open"), null);
  assert.equal(await page.locator('[data-saas-product-fact-field="material"]').isVisible(), true);
  assert.equal(await page.locator('[data-saas-product-fact-field="condition"]').isVisible(), true);
  assert.equal(await page.locator('[data-saas-product-fact-field="sku"]').isVisible(), false);
  await screenshot(page, "facts-desktop");
  mode = "facts-fail";
  await page.locator('[data-saas-product-fact-field="material"]').fill("Aluminum alloy");
  await next(page); await page.waitForFunction(() => !saasListingWizardRecord().busy);
  await step(page, 1); assert.match(await page.locator("[data-listing-wizard-message]").innerText(), /尚未保存/);
  assert.equal(await page.locator('[data-saas-product-fact-field="material"]').inputValue(), "Aluminum alloy");
  checks.push("facts failure stays on step 1 and preserves input");
  mode = "ok"; await next(page); await step(page, 2);
  assert.equal(factPacket.merchant_confirmed_facts.material, "Aluminum alloy");
  assert.equal(await page.locator('[data-saas-product-fact-field="material"]').count(), 0);
  checks.push("confirmed three facts continue despite image/quantity/publish gaps");
  revision += 1;
  checkpoint = { checkpoint_id: `wizard-checkpoint-${revision}`, revision, mutation_id: "cloud-cleared-description", company_id: company, store_id: store,
    listing_project_identity: identity, base_report_id: baseReport.report_id, fields: { ...fields, description: "" }, merchant_edited_fields: ["description"],
    saved_at: new Date().toISOString(), source: "merchant_edit" };
  await page.evaluate(() => { const record = saasListingCloudRecord(); record.loaded = false; record.observedRefreshGeneration = -1; });
  await next(page); await page.waitForFunction(() => !saasListingWizardRecord().busy);
  assert.equal(await page.locator('[data-listing-wizard-step]').getAttribute("data-listing-wizard-step"), "2", "cloud-cleared copy must stay in step 2");
  assert.equal(await page.locator('[data-saas-listing-draft-field="description"]').inputValue(), "");
  checks.push("cloud restoration clearing copy is checked again before advancing");
  await page.locator('[data-saas-listing-draft-field="description"]').fill("Merchant edited aluminum stand description.");
  mode = "copy-fail"; await next(page); await page.waitForFunction(() => !saasListingWizardRecord().busy);
  await step(page, 2); assert.match(await page.locator("[data-listing-wizard-message]").innerText(), /尚未成功保存|无法核对/);
  checks.push("cloud failure stays on step 2");
  mode = "copy-conflict"; await next(page); await page.waitForFunction(() => !saasListingWizardRecord().busy);
  await step(page, 2); assert.match(await page.locator("[data-listing-wizard-message]").innerText(), /冲突/);
  checks.push("cloud conflict stays on step 2");
  mode = "ok";
  await page.evaluate(async () => { await resolveSaasListingCloudCheckpoint("keep-local"); });
  await next(page); await step(page, 3);
  assert.equal(await page.locator('[data-saas-product-fact-field="image_rights_confirmed"]').isChecked(), false);
  await page.locator(".saas-listing-wizard-images details > summary").click();
  await page.locator('[data-saas-product-fact-field="image_urls"]').fill("https://media.example.test/tablet.png");
  await back(page); await step(page, 2); await next(page); await step(page, 3);
  await page.locator(".saas-listing-wizard-images details > summary").click();
  assert.equal(await page.locator('[data-saas-product-fact-field="image_urls"]').inputValue(), "https://media.example.test/tablet.png");
  checks.push("back and forward preserve unsaved image input");
  await next(page); await page.waitForFunction(() => !saasListingWizardRecord().busy);
  await step(page, 3); assert.match(await page.locator("[data-listing-wizard-message]").innerText(), /商业使用权/);
  assert.equal(factPacket.merchant_confirmed_facts.material, "Aluminum alloy");
  checks.push("image save preserves step 1 facts and never checks rights automatically");
  await page.locator('[data-saas-product-fact-field="image_rights_confirmed"]').check();
  await screenshot(page, "images-desktop");
  await next(page); await step(page, 4);
  assert.equal(await page.locator("#saasPublishIntakeForm").count(), 1);
  assert(await page.locator('[data-saas-action="create-ebay-draft-confirmation"]').count());
  assert(await page.locator('[data-saas-action="create-publish-confirmation"]').count());
  assert.equal(await page.locator('[data-saas-product-fact-field="material"]').count(), 0);
  checks.push("step 4 retains separate unpublished draft and publish confirmation controls");
  await page.locator('[data-listing-publish-flow-details] > summary').click();
  await page.locator('#saasPublishIntakeForm [name="shipping_cost"]').fill("19.95");
  await page.locator('#saasPublishIntakeForm [name="merchant_location_key"]').fill("merchant-unsaved-warehouse");
  await page.locator('[data-listing-advanced-checks] > summary').click();
  await page.locator('[data-saas-listing-gap-prompt="SKU"]').first().click(); await step(page, 1);
  await page.evaluate(() => focusSaasPublishIntakeForm()); await step(page, 4);
  assert.equal(await page.locator('#saasPublishIntakeForm [name="shipping_cost"]').inputValue(), "19.95");
  assert.equal(await page.locator('#saasPublishIntakeForm [name="merchant_location_key"]').inputValue(), "merchant-unsaved-warehouse");
  checks.push("actual missing-field shortcut preserves unsaved publish form values");
  await back(page); await step(page, 3);
  await page.locator(".saas-listing-wizard-images details > summary").click();
  await page.locator('[data-saas-product-fact-field="image_urls"]').fill("");
  assert.equal(await page.locator('[data-saas-product-fact-field="image_rights_confirmed"]').isChecked(), true);
  await next(page); await page.waitForFunction(() => !saasListingWizardRecord().busy);
  assert.equal(await page.locator('[data-listing-wizard-step]').getAttribute("data-listing-wizard-step"), "3", "cleared image must not revive from prefill");
  assert.deepEqual(await page.evaluate(() => ({ urls: saasListingWizardImageUrls(), prefill: state.saasListingComposerDraft.publish_prefill.image_urls,
    publishForm: saasPublishIntakePrefillValues().image_urls })), { urls: [], prefill: "", publishForm: "" });
  checks.push("cleared image blocks step 3 with rights still confirmed and stays cleared in final prefill");
  await page.locator(".saas-listing-wizard-images details > summary").click();
  await page.locator('[data-saas-product-fact-field="image_urls"]').fill("https://media.example.test/tablet.png");
  await next(page); await step(page, 4);
  await page.reload(); await bootstrap(page, base); await step(page, 4);
  checks.push("reload restores scoped current step without regeneration");
  const scoped = await page.evaluate(() => {
    const original = state.saasListingComposerDraft, identity = original.listing_project_identity;
    state.saasListingComposerDraft = { ...original, fields: {}, merchant_product_fact_packet: {}, listing_project_identity: { ...identity, key: "other-project" } };
    const otherStep = saasListingWizardRecord().step;
    state.saasListingComposerDraft = original;
    const sameStep = saasListingWizardRecord().step;
    state.saasIdentity.user_id = "other-user"; state.saasUser.user_id = "other-user";
    const userRecord = saasListingWizardRecord();
    return { otherStep, sameStep, userStep: userRecord.step, key: userRecord.key };
  });
  assert.equal(scoped.otherStep, 1); assert.equal(scoped.sameStep, 4); assert.notEqual(scoped.userStep, 4); assert(scoped.key.includes("other-user"));
  checks.push("project and user navigation preferences stay isolated");
  await page.evaluate(() => { state.saasIdentity.user_id = "wizard-user"; state.saasUser.user_id = "wizard-user"; setSaasListingWizardStep(3); renderProductListingCenter(); });
  for (const width of [920, 390, 320]) {
    await page.setViewportSize({ width, height: 900 });
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1), `no overflow at ${width}`);
    await screenshot(page, `images-${width}`);
  }
  checks.push("desktop tablet and mobile render with no horizontal overflow");
  await page.locator('[data-saas-action="listing-wizard-previous"]').scrollIntoViewIfNeeded();
  const buttonClear = await page.locator('[data-saas-action="listing-wizard-previous"]').evaluate(button => {
    const rect = button.getBoundingClientRect(), hit = document.elementFromPoint(rect.x + rect.width / 2, rect.y + rect.height / 2);
    return hit === button || button.contains(hit);
  });
  assert(buttonClear, "mobile step control is not covered by bottom navigation");
  await screenshot(page, "images-mobile-navigation");
  await back(page); await step(page, 2);
  await page.evaluate(() => { state.saasListingComposerDraft.ai_generation_feedback = { status: "running", context_key: saasListingAiGenerationContextKey(), message: "Fixture pending generation" }; renderProductListingCenter(); });
  await next(page); await step(page, 2); assert.match(await page.locator("#actionToast").innerText().catch(() => page.locator("body").innerText()), /尚未确认/);
  checks.push("pending generation cannot advance or cause another generation");
  await page.evaluate(() => { delete state.saasListingComposerDraft.ai_generation_feedback; setSaasListingWizardStep(1); renderProductListingCenter(); });
  mode = "facts-delay";
  await next(page);
  for (let tries = 0; !releaseFact && tries < 100; tries += 1) await new Promise(resolve => setTimeout(resolve, 20));
  assert(releaseFact, "fact save is in flight");
  await page.evaluate(() => {
    const draft = state.saasListingComposerDraft;
    state.saasListingComposerDraft = { ...draft, product: "Other product", fields: {}, merchant_product_fact_packet: {},
      listing_project_identity: { ...draft.listing_project_identity, key: "other-project" } };
    renderProductListingCenter();
  });
  releaseFact(); mode = "ok";
  await page.waitForFunction(() => !state.saasListingProductFactSaveRequest);
  await step(page, 1); assert.equal(await page.evaluate(() => state.saasListingComposerDraft.product), "Other product");
  checks.push("late save receipt cannot advance or replace a switched project");
  assert.deepEqual(errors, []); assert.deepEqual(consoleIssues, []); assert.deepEqual(unexpected, []);
  const evidence = { ok: true, base, checks, screenshots, errors, consoleIssues, unexpected, calls: calls.map(item => typeof item === "string" ? item : item.path) };
  fs.writeFileSync(path.join(output, "evidence.json"), JSON.stringify(evidence, null, 2));
  console.log(JSON.stringify({ ok: true, checks, evidence: path.join(output, "evidence.json"), screenshots }, null, 2));
})().catch(error => { console.error(error); process.exitCode = 1; }).finally(async () => { if (browser) await browser.close(); await new Promise(resolve => server.close(resolve)); });
