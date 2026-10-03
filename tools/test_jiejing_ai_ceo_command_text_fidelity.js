#!/usr/bin/env node
"use strict";

// Full application markup and submit handler, with a loopback HTTP boundary.
// Synthetic text only; no external model, platform, credential or production I/O.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const http = require("node:http");
const path = require("node:path");
const { chromium } = require("../output/codex-playwright-deps/node_modules/playwright-core");

const root = path.resolve(__dirname, "..");
const scope = { user_id: "fidelity-user", company_id: "fidelity-company", store_id: "fidelity-store" };
const identity = { key: "fidelity-project", source_report_id: "fidelity-source", candidate_id: "candidate-fidelity" };
let activeCase = "setup";

function json(res, status, value) {
  res.writeHead(status, { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" });
  res.end(JSON.stringify(value));
}

function ready(body) {
  const dispatch = {
    contract_version: "ai_ceo_semantic_dispatch_v1", status: "ready", project_action: "none",
    command_id: body.command.id, idempotency_key: body.idempotency_key,
    request_task_id: "fidelity-request-task", company_id: scope.company_id, store_id: scope.store_id,
    submitted_project_identity: body.active_listing_context?.listing_project_identity || {},
    target_project_identity: {}, consumed_source_asset_ids: [], workflow_target: "general_chat",
  };
  return { semantic_dispatch: dispatch, ai_ceo_chat: { status: "model_answered", answer: "本地原文检查完成。",
    route: "general_chat", semantic_dispatch: dispatch, source_records: [], work_records: [], confirmation_items: [] },
  usage_consumed: false, listing_created: false, real_platform_writes_enabled: false, secret_exposed: false };
}

function savedFacts(body) {
  const result = ready(body);
  Object.assign(result.semantic_dispatch, { project_action: "new", target_project_identity: identity, workflow_target: "listing_draft" });
  Object.assign(result.ai_ceo_chat, { route: "ebay_workflow", listing_project_identity: identity });
  const packet = { product_name: "合成咖啡量勺", source: "backend_semantic_product_fact_intake", source_mode: "merchant_supplied",
    source_confirmed_facts: {}, merchant_confirmed_facts: {},
    derived_listing_suggestions: { sku: "MOCK-B-015", material: "模拟桦木" },
    unknown_facts: ["sku", "material"], field_evidence: {}, source_records: [], fact_conflicts: [], simulation_only: true };
  result.product_vision_fact_packet = packet;
  result.product_vision_report = { report_id: "report-fidelity-facts", task_id: "fidelity-fact-task", status: "saved",
    report_type: "merchant.product_facts", company_id: scope.company_id, store_id: scope.store_id,
    created_at: new Date().toISOString(), report: { listing_project_identity: identity,
      semantic_dispatch: result.semantic_dispatch, merchant_product_fact_packet: packet } };
  return result;
}

async function seed(page, base) {
  await page.goto(`${base}/app.html?start=app&qa=public-saas&view=cockpit`);
  await page.evaluate(({ base, scope }) => {
    window.__JIEJING_FORCE_PUBLIC_MVP__ = true;
    localStorage.setItem(saasStorageKeys.sessionHint, "1");
    localStorage.setItem(saasStorageKeys.storeId, scope.store_id);
    state.saasApiBase = base;
    state.saasIdentity = { user_id: scope.user_id, company_id: scope.company_id };
    state.saasUser = { user_id: scope.user_id }; state.saasCompany = { company_id: scope.company_id };
    state.saasStores = [{ store_id: scope.store_id, company_id: scope.company_id, platform: "ebay",
      marketplace: "EBAY_US", status: "authorized" }];
    state.saasConnected = true; state.saasProtectedStateReady = true;
    state.saasProtectedStateFromCache = false; state.saasLoading = false;
    state.saasReports = []; state.saasTasks = []; state.saasAiCeoThread = [];
    state.saasListingComposerDraft = null; state.saasLastCeoCommand = null;
    bindEvents();
    [entryShell, siteShell, onboardingShell].forEach(shell => shell.classList.add("is-hidden"));
    appShell.classList.remove("is-hidden"); document.body.classList.remove("site-locked");
    setView("cockpit");
  }, { base, scope });
  assert.match(await page.title(), /捷境|JIEJING/i, "real application page title must be present");
  assert.equal(await page.locator("#ceoInput").isVisible(), true, "real composer must be visible");
  assert.equal(await page.locator("#ceoForm button[type=submit]").isVisible(), true);
}

async function main() {
  const original = fs.readFileSync(path.join(root, "app.js"), "utf8");
  const boot = /exposeLocalJiejingTestHooks\(\);\r?\ninit\(\);\r?\nrunLocalJiejingQaScenarioFromUrl\(\);\s*$/;
  assert.match(original, boot, "real application boot marker must match");
  const app = original.replace(boot, "exposeLocalJiejingTestHooks();\n");
  const html = fs.readFileSync(path.join(root, "app.html"), "utf8")
    .replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, "")
    .replace(/<style\b[^>]*>[\s\S]*?<\/style>/gi, "")
    .replace(/<link\b[^>]*>/gi, "")
    .replace(/<img\b[^>]*>/gi, "")
    .replace("</head>", "<style>.is-hidden,.view:not(.is-active){display:none!important}</style></head>")
    .replace("</body>", '<script src="/app.js"></script></body>');
  const requests = [], historySyncs = [], unexpectedWrites = [], errors = [];
  let respond = ready;
  const server = http.createServer(async (req, res) => {
    const url = new URL(req.url, "http://127.0.0.1");
    if (req.method === "POST" && url.pathname === `/stores/${scope.store_id}/merchant-ceo/chat`) {
      const chunks = [];
      for await (const chunk of req) chunks.push(chunk);
      const body = JSON.parse(Buffer.concat(chunks).toString("utf8"));
      requests.push(body);
      return json(res, 200, respond(body));
    }
    if (req.method === "POST" && url.pathname === "/ai-ceo/chat-history/sync") {
      // Reconciliation normally persists its recovered turn through this API.
      const chunks = [];
      for await (const chunk of req) chunks.push(chunk);
      const body = JSON.parse(Buffer.concat(chunks).toString("utf8"));
      historySyncs.push(body);
      return json(res, 200, { ai_ceo_chat_history: { scope: "account", cross_store: true, turns: body.turns || [] }, secret_exposed: false });
    }
    if (req.method !== "GET") { unexpectedWrites.push(url.pathname); return json(res, 405, {}); }
    if (["/app.html", "/app.js"].includes(url.pathname)) {
      res.writeHead(200, { "content-type": url.pathname.endsWith(".js") ? "text/javascript; charset=utf-8" : "text/html; charset=utf-8" });
      return res.end(url.pathname.endsWith(".js") ? app : html);
    }
    if (url.pathname === "/me") return json(res, 200, { user: { user_id: scope.user_id },
      company: { company_id: scope.company_id }, identity: { user_id: scope.user_id, company_id: scope.company_id } });
    return json(res, 200, { reports: [], turns: [], secret_exposed: false });
  });
  let browser;
  try {
    await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
    const base = `http://127.0.0.1:${server.address().port}`;
    browser = await chromium.launch({ headless: true, channel: process.env.JIEJING_PLAYWRIGHT_CHANNEL || "chrome" });
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    page.setDefaultTimeout(10000);
    page.on("pageerror", error => errors.push(error.name));
    await page.route("**/*", route => new URL(route.request().url()).origin === base ? route.continue() : route.abort());
    await seed(page, base);
    activeCase = "raw-simulation-and-sku-form-submit";
    const input = "继续那把：仅用于内部模拟，SKU MOCK-B-015；包装重量45g，暂不发布。";
    await page.locator("#ceoInput").fill(input);
    const response = page.waitForResponse(r => new URL(r.url()).pathname === `/stores/${scope.store_id}/merchant-ceo/chat`);
    await page.locator("#ceoForm button[type=submit]").click();
    await response;
    await page.evaluate(async () => { await state.saasLastCeoCommandPersistPromise; stopSaasPendingNewListingProjectReconciliation(); });
    assert.equal(requests.length, 1, "one visible submission must make one local chat request");
    const body = requests[0];
    console.log(JSON.stringify({ case: activeCase, raw_message_equal: body.message === input,
      raw_command_equal: body.command?.text === input, simulation_word_preserved: body.message.includes("内部模拟"),
      sku_preserved: body.message.includes("MOCK-B-015") }));
    assert.equal(body.message, input, "semantic message must preserve merchant text, not productize it");
    assert.equal(body.command.text, input, "command text must preserve the same source text");
    console.log(`PASS command text fidelity: ${activeCase}`);

    activeCase = "historical-assistant-data-on-next-submit";
    await seed(page, base);
    const history = { user_text: "仅供内部模拟，SKU MOCK-B-015。", assistant_text: "MOCK-B-015 的模拟材料为桦木；不要发布，也不要改成真实货品。" };
    await page.evaluate(({ history, scope }) => {
      state.saasAiCeoThread = [
        { ...history, assistant_id: "fidelity-prior", status: "model_answered", route: "general_chat", store_id: scope.store_id },
        { user_text: "其他店铺资料", assistant_text: "不得进入当前上下文", assistant_id: "foreign-prior", status: "model_answered", store_id: "other-store" },
      ];
    }, { history, scope });
    await page.locator("#ceoInput").fill("保留上一轮约束，仅检查文本。");
    const historyResponse = page.waitForResponse(r => new URL(r.url()).pathname === `/stores/${scope.store_id}/merchant-ceo/chat`);
    await page.locator("#ceoForm button[type=submit]").click();
    await historyResponse;
    await page.evaluate(async () => { await state.saasLastCeoCommandPersistPromise; stopSaasPendingNewListingProjectReconciliation(); });
    const historyBody = requests.at(-1);
    console.log(JSON.stringify({ case: activeCase, history_count: historyBody.conversation_history.length,
      raw_user_equal: historyBody.conversation_history[0]?.user_text === history.user_text,
      raw_assistant_equal: historyBody.conversation_history[0]?.assistant_text === history.assistant_text }));
    assert.equal(historyBody.conversation_history.length, 1, "foreign-store history must remain filtered");
    assert.equal(historyBody.conversation_history[0].user_text, history.user_text);
    assert.equal(historyBody.conversation_history[0].assistant_text, history.assistant_text,
      "assistant source data sent back to the model must not use display replacements");
    console.log(`PASS command text fidelity: ${activeCase}`);

    const negationTail = "；不要发布，不要收费，不改变 SKU MOCK-B-015。";
    const secretInput = `仅内部模拟；${"sk-" + "x".repeat(20)}；${"AIAK" + "Z".repeat(16)}；api_key=synthetic_secret；password:synthetic_password；SKU MOCK-B-015。`;
    const secretExpected = "仅内部模拟；[model_key_redacted]；[cloud_key_redacted]；api_key=[redacted]；password=[redacted]；SKU MOCK-B-015。";
    for (const scenario of [
      { name: "unicode-and-numeric-values", input: "内部模拟 🥄 café e\u0301 桦木　尺寸 16×4×2.5cm，包装45g；不要发布。" },
      { name: "900-characters-retain-negation-tail", input: "中".repeat(900 - negationTail.length) + negationTail },
      { name: "synthetic-secrets-redacted-not-productized", input: secretInput, expected: secretExpected },
      { name: "html-text-remains-inert", input: '<b>模拟 MOCK-B-015</b> & "不得发布"' },
    ]) {
      activeCase = scenario.name;
      await seed(page, base);
      const start = requests.length;
      await page.locator("#ceoInput").fill(scenario.input);
      const response = page.waitForResponse(r => new URL(r.url()).pathname === `/stores/${scope.store_id}/merchant-ceo/chat`);
      await page.locator("#ceoForm button[type=submit]").click();
      await response;
      await page.evaluate(async () => { await state.saasLastCeoCommandPersistPromise; stopSaasPendingNewListingProjectReconciliation(); });
      assert.equal(requests.length, start + 1);
      assert.equal(requests.at(-1).message, scenario.expected ?? scenario.input);
      assert.equal(requests.at(-1).command.text, scenario.expected ?? scenario.input);
      if (scenario.name === "html-text-remains-inert") {
        assert.equal(await page.locator("#ceoChat .message.user b").count(), 0, "user markup must never become an element");
        assert.equal(await page.locator("#ceoChat .message.user p").last().textContent(), scenario.input);
      }
      console.log(`PASS command text fidelity: ${activeCase}`);
    }

    activeCase = "901-characters-rejected-with-input-intact";
    await seed(page, base);
    const tooLong = "中".repeat(901 - negationTail.length) + negationTail;
    const beforeRejected = requests.length;
    await page.locator("#ceoInput").fill(tooLong);
    await page.locator("#ceoForm button[type=submit]").click();
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    assert.equal(requests.length, beforeRejected, "over-limit submission must not send or truncate a request");
    assert.equal(await page.locator("#ceoInput").inputValue(), tooLong);
    assert.equal(await page.evaluate(() => state.saasPendingNewListingProjectRequest), null);
    console.log(`PASS command text fidelity: ${activeCase}`);

    activeCase = "history-masking-length-and-pending-scope-guards";
    await seed(page, base);
    const historyPrefix = `模拟 MOCK-B-015；不要发布；${"sk-" + "q".repeat(20)}；`;
    await page.evaluate(({ scope, historyPrefix }) => {
      state.saasAiCeoThread = [
        { user_text: "模拟：不要发布", assistant_text: historyPrefix + "文".repeat(3300), assistant_id: "fidelity-long", status: "model_answered", store_id: scope.store_id },
        { user_text: "尚未完成", assistant_text: "不能加入历史", assistant_id: "fidelity-pending", status: "pending", pending: true, store_id: scope.store_id },
      ];
    }, { scope, historyPrefix });
    await page.locator("#ceoInput").fill("保留历史约束，仅检查。");
    const guardedResponse = page.waitForResponse(r => new URL(r.url()).pathname === `/stores/${scope.store_id}/merchant-ceo/chat`);
    await page.locator("#ceoForm button[type=submit]").click();
    await guardedResponse;
    await page.evaluate(async () => { await state.saasLastCeoCommandPersistPromise; stopSaasPendingNewListingProjectReconciliation(); });
    const guardedHistory = requests.at(-1).conversation_history;
    assert.equal(guardedHistory.length, 1);
    assert.equal(guardedHistory[0].assistant_text, ("模拟 MOCK-B-015；不要发布；[model_key_redacted]；" + "文".repeat(3300)).slice(0, 3200));
    console.log(`PASS command text fidelity: ${activeCase}`);

    activeCase = "uncertain-frozen-payload-survives-reload-and-live-edits";
    await seed(page, base);
    respond = () => ({ ai_ceo_chat_request: { status: "in_progress", retry_after_ms: 10 }, usage_consumed: false, listing_created: false });
    const replayInput = "仅用于内部模拟，SKU MOCK-B-015；Unicode 🥄；不要发布。";
    const replayHistory = { user_text: "模拟准备，SKU MOCK-B-015。", assistant_text: "模拟桦木 MOCK-B-015；不要发布。" };
    await page.evaluate(({ replayHistory, scope }) => {
      state.saasAiCeoThread = [{ ...replayHistory, assistant_id: "fidelity-replay-prior", status: "model_answered", store_id: scope.store_id }];
    }, { replayHistory, scope });
    const replayStart = requests.length;
    await page.locator("#ceoInput").fill(replayInput);
    await page.locator("#ceoForm button[type=submit]").click();
    const pending = await page.evaluate(async () => {
      await state.saasLastCeoCommandPersistPromise; stopSaasPendingNewListingProjectReconciliation();
      saveSaasProtectedStateSnapshot();
      return state.saasPendingNewListingProjectRequest;
    });
    assert.equal(pending?.phase, "uncertain");
    const frozen = requests[replayStart];
    assert.equal(frozen.message, replayInput);
    assert.equal(frozen.command.text, replayInput);
    assert.equal(frozen.conversation_history[0].assistant_text, replayHistory.assistant_text);
    assert.deepEqual(pending.requestPayload, frozen);
    await page.locator("#ceoInput").fill("另一个尚未提交的输入；不要替换冻结原文。");
    await page.evaluate(() => {
      state.saasAiCeoThread = [{ user_text: "未提交的新上下文", assistant_text: "不可覆盖旧请求", assistant_id: "unrelated-turn", status: "model_answered" }];
      saveSaasProtectedStateSnapshot();
    });
    await seed(page, base);
    respond = ready;
    const replayed = await page.evaluate(async ({ scope }) => {
      state.saasProtectedStateReady = false;
      const hydrated = hydrateSaasProtectedStateFromCache({
        me: { user: { user_id: scope.user_id }, company: { company_id: scope.company_id },
          identity: { user_id: scope.user_id, company_id: scope.company_id } },
        storeId: scope.store_id, stores: [{ store_id: scope.store_id, company_id: scope.company_id }],
      });
      state.saasProtectedStateReady = true;
      const payload = state.saasPendingNewListingProjectRequest?.requestPayload;
      await runSaasPendingNewListingProjectReconcileAttempt({ scheduleNext: false });
      stopSaasPendingNewListingProjectReconciliation();
      return { hydrated, payload, pending: state.saasPendingNewListingProjectRequest };
    }, { scope });
    assert.equal(replayed.hydrated, true);
    assert.deepEqual(replayed.payload, frozen);
    assert.equal(replayed.pending, null, "one completed replay must clear its own pending state");
    assert(requests.length > replayStart + 1, "recovery must cross the real local HTTP boundary");
    for (const request of requests.slice(replayStart)) assert.deepEqual(request, frozen, "all inline and restored retries must reuse the exact payload and idempotency key");
    console.log(`PASS command text fidelity: ${activeCase}`);

    activeCase = "saved-typed-facts-protected-cache-reload";
    await seed(page, base);
    respond = savedFacts;
    await page.locator("#ceoInput").fill("新建合成咖啡量勺，仅用于内部模拟；SKU MOCK-B-015，材质模拟桦木，不发布。");
    const factResponse = page.waitForResponse(r => new URL(r.url()).pathname === `/stores/${scope.store_id}/merchant-ceo/chat`);
    await page.locator("#ceoForm button[type=submit]").click();
    await factResponse;
    const live = await page.evaluate(async () => {
      await state.saasLastCeoCommandPersistPromise; stopSaasPendingNewListingProjectReconciliation();
      const facts = state.saasListingComposerDraft?.merchant_product_fact_packet?.derived_listing_suggestions;
      saveSaasProtectedStateSnapshot();
      state.saasListingMode = "single"; setSaasListingWizardStep(1); setView("product");
      return facts;
    });
    console.log(JSON.stringify({ case: activeCase, stage: "live", has_packet: Boolean(live),
      packet_sku_preserved: live?.sku === "MOCK-B-015", packet_material_preserved: live?.material === "模拟桦木" }));
    assert.equal(live?.sku, "MOCK-B-015", "accepted saved artifact must initially project literal SKU");
    assert.equal(live?.material, "模拟桦木", "accepted saved artifact must initially project literal material");
    await page.locator(".saas-listing-wizard-other-facts > summary").click();
    assert.equal(await page.locator('[data-saas-product-fact-field="sku"]').inputValue(), "MOCK-B-015");
    assert.equal(await page.locator('[data-saas-product-fact-field="material"]').inputValue(), "模拟桦木");
    await seed(page, base);
    const restored = await page.evaluate(({ scope }) => {
      state.saasProtectedStateReady = false;
      const hydrated = hydrateSaasProtectedStateFromCache({
        me: { user: { user_id: scope.user_id }, company: { company_id: scope.company_id },
          identity: { user_id: scope.user_id, company_id: scope.company_id } },
        storeId: scope.store_id, stores: [{ store_id: scope.store_id, company_id: scope.company_id }],
      });
      state.saasProtectedStateReady = true;
      state.saasListingMode = "single"; setSaasListingWizardStep(1); setView("product");
      return { hydrated, facts: state.saasListingComposerDraft?.merchant_product_fact_packet?.derived_listing_suggestions };
    }, { scope });
    await page.locator(".saas-listing-wizard-other-facts > summary").click();
    const restoredSku = await page.locator('[data-saas-product-fact-field="sku"]').inputValue();
    const restoredMaterial = await page.locator('[data-saas-product-fact-field="material"]').inputValue();
    console.log(JSON.stringify({ case: activeCase, hydrated: restored.hydrated,
      packet_sku_preserved: restored.facts?.sku === "MOCK-B-015", packet_material_preserved: restored.facts?.material === "模拟桦木",
      input_sku_preserved: restoredSku === "MOCK-B-015", input_material_preserved: restoredMaterial === "模拟桦木" }));
    assert.equal(restored.hydrated, true, "reload must use the scoped protected snapshot");
    assert.deepEqual(restored.facts, live, "cache must preserve approved typed values, not productize them");
    assert.equal(restoredSku, "MOCK-B-015");
    assert.equal(restoredMaterial, "模拟桦木");
    console.log(`PASS command text fidelity: ${activeCase}`);

    activeCase = "typed-facts-explicit-confirmation-collection";
    const unconfirmed = await page.evaluate(() => collectSaasMerchantProductFacts());
    assert.equal(unconfirmed.merchantConfirmed.sku, undefined, "cached suggestion must not become confirmed");
    assert.equal(unconfirmed.merchantConfirmed.material, undefined);
    for (const key of ["sku", "material"]) {
      await page.locator(`[data-saas-action="confirm-product-fact-suggestion"][data-product-fact-key="${key}"]`).click();
      assert.equal(await page.locator(`[data-saas-product-fact-field="${key}"]`).getAttribute("data-product-fact-confirmed"), "true");
    }
    const confirmed = await page.evaluate(() => collectSaasMerchantProductFacts());
    console.log(JSON.stringify({ case: activeCase, sku_preserved: confirmed.merchantConfirmed.sku === "MOCK-B-015",
      material_preserved: confirmed.merchantConfirmed.material === "模拟桦木" }));
    assert.equal(confirmed.merchantConfirmed.sku, "MOCK-B-015", "explicit confirmation must not rewrite a literal SKU");
    assert.equal(confirmed.merchantConfirmed.material, "模拟桦木");
    console.log(`PASS command text fidelity: ${activeCase}`);

    activeCase = "typed-value-whitelist-rights-length-and-secret-boundaries";
    const safeFacts = await page.evaluate(() => sanitizeSaasMerchantProductFactValues({
      sku: "MOCK-" + "x".repeat(300), material: "模拟桦木；" + "sk-" + "v".repeat(20),
      source_url: "u".repeat(750), image_urls: "i".repeat(2500), image_rights_confirmed: "true",
      merchant_owned_product_confirmed: true, arbitrary_field: "must-not-survive",
    }));
    assert.equal(safeFacts.sku, ("MOCK-" + "x".repeat(300)).slice(0, 240));
    assert.equal(safeFacts.material, "模拟桦木；[model_key_redacted]");
    assert.equal(safeFacts.source_url.length, 700);
    assert.equal(safeFacts.image_urls.length, 2400);
    assert.equal(safeFacts.image_rights_confirmed, false);
    assert.equal(safeFacts.merchant_owned_product_confirmed, true);
    assert.equal(Object.hasOwn(safeFacts, "arbitrary_field"), false);
    for (const sync of historySyncs) assert((sync.turns || []).every(turn => turn.store_id === scope.store_id), "recovered history sync must remain scoped");
    assert.deepEqual(errors, [], "real app submit must not throw");
    assert.deepEqual(unexpectedWrites, [], "fixture must not perform non-chat business writes");
    console.log(`PASS command text fidelity: ${activeCase}`);
  } finally {
    await browser?.close();
    await new Promise(resolve => server.close(resolve));
  }
}

main().catch(error => {
  console.error(JSON.stringify({ status: "FAIL", case: activeCase, error_type: error.name,
    location: String(error.stack || "").match(/test_jiejing_ai_ceo_command_text_fidelity\.js:\d+:\d+/)?.[0] || null }));
  process.exitCode = 1;
});
