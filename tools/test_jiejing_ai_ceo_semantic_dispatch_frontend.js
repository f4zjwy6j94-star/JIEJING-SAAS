#!/usr/bin/env node
/* Real browser / local HTTP boundary regression. No external model or platform calls. */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const http = require("node:http");
const path = require("node:path");
const { chromium } = require("../output/codex-playwright-deps/node_modules/playwright-core");

const root = path.resolve(__dirname, "..");
const oldIdentity = { key: "semantic-project-a", source_report_id: "report-a", candidate_id: "candidate-a" };
const newIdentity = { key: "semantic-project-b", source_report_id: "report-b", candidate_id: "candidate-b" };
const bodies = [];
let releaseResponse;
let receivedRequest;
let responseReady;
let respond;
let responseStatus = 200;

function json(res, status, body) {
  res.writeHead(status, { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" });
  res.end(JSON.stringify(body));
}

function dispatch(body, action = "new", overrides = {}) {
  return {
    contract_version: "ai_ceo_semantic_dispatch_v1", status: "ready", project_action: action,
    command_id: body.command.id, idempotency_key: body.idempotency_key,
    request_task_id: "task-semantic-browser", company_id: "semantic-company", store_id: "semantic-store",
    submitted_project_identity: body.active_listing_context?.listing_project_identity || {},
    target_project_identity: action === "new" ? newIdentity : action === "current" ? oldIdentity : {},
    consumed_source_asset_ids: [], workflow_target: "research", ...overrides,
  };
}

function success(body, action = "new", overrides = {}) {
  const semantic = dispatch(body, action, overrides);
  return {
    semantic_dispatch: semantic,
    ai_ceo_chat: { status: "model_answered", answer: "后端语义计划已完成。", route: "ebay_workflow",
      listing_project_identity: semantic.target_project_identity, semantic_dispatch: semantic,
      source_records: [], work_records: [], confirmation_items: [] },
    usage_consumed: true, listing_created: false, real_platform_writes_enabled: false,
  };
}

async function seed(page, base) {
  await page.goto(`${base}/app.html?start=app&qa=public-saas&project=${oldIdentity.key}&saasApiBase=${encodeURIComponent(base)}`);
  await page.evaluate(({ identity, apiBase }) => {
    window.__JIEJING_FORCE_PUBLIC_MVP__ = true;
    localStorage.setItem(saasStorageKeys.sessionHint, "1");
    localStorage.setItem(saasStorageKeys.storeId, "semantic-store");
    state.saasApiBase = apiBase;
    state.saasConnected = true;
    state.saasProtectedStateReady = true;
    state.saasIdentity = { user_id: "semantic-user", company_id: "semantic-company" };
    state.saasUser = { user_id: "semantic-user", email: "merchant@local.invalid" };
    state.saasCompany = { company_id: "semantic-company" };
    state.saasStores = [{ store_id: "semantic-store", platform: "ebay", marketplace: "EBAY_US", status: "authorized" }];
    state.activeStore = "semantic-store";
    state.view = "cockpit";
    state.aiCeoTaskContextMode = "active_product_task";
    state.aiCeoTaskContextProjectId = identity.key;
    state.saasListingComposerDraft = {
      product: "原商品A", title: "原商品A", listing_project_key: identity.key, listing_project_identity: identity,
      fields: { title: "商家编辑的标题", selling_points: "商家编辑的卖点", description: "商家编辑的描述" },
      merchant_edited_fields: ["title", "selling_points", "description"],
      merchant_product_fact_packet: { product_name: "原商品A", source_confirmed_facts: {},
        merchant_confirmed_facts: { material: "Steel", sku: "OLD-A" }, derived_listing_suggestions: {}, unknown_facts: [] },
    };
    state.saasAiCeoThread = [{ user_text: "完善原商品", assistant_text: "原商品资料已保存。", assistant_id: "prior-turn",
      status: "model_answered", store_id: "semantic-store", route: "ebay_workflow", listing_project_identity: identity,
      created_at: new Date(Date.now() - 1000).toISOString() }];
    bindCeoForm();
  }, { identity: oldIdentity, apiBase: base });
}

async function snapshot(page) {
  return page.evaluate(() => ({ route: saasMerchantProjectRouteId(), current: saasCurrentMerchantProjectId(),
    draft: state.saasListingComposerDraft, task: state.aiCeoTaskContextProjectId,
    pending: state.saasPendingNewListingProjectRequest, turns: state.saasAiCeoThread,
    detached: state.saasDetachedListingProjectDrafts }));
}

async function main() {
  const source = fs.readFileSync(path.join(root, "app.js"), "utf8");
  const appSource = source.replace(/exposeLocalJiejingTestHooks\(\);\r?\ninit\(\);\r?\nrunLocalJiejingQaScenarioFromUrl\(\);\s*$/, "exposeLocalJiejingTestHooks();\n");
  assert.notEqual(appSource, source, "application boot marker must match");
  const server = http.createServer(async (req, res) => {
    const url = new URL(req.url, "http://127.0.0.1");
    if (url.pathname === "/app.html") {
      res.writeHead(200, { "content-type": "text/html; charset=utf-8" });
      return res.end('<!doctype html><html><head><title>AI CEO semantic fixture</title></head><body data-view="cockpit"><section id="view-cockpit" class="view is-active"><div class="cockpit-chat-panel"><div id="ceoChat"></div><div id="saasCeoRouteTaskSlot"></div><form id="ceoForm"><input id="ceoInput"><button type="submit">发送</button></form></div></section><section id="view-product" class="view"></section><div id="actionToast" hidden></div><script src="/app-test.js"></script></body></html>');
    }
    if (url.pathname === "/app-test.js") { res.writeHead(200, { "content-type": "text/javascript" }); return res.end(appSource); }
    if (url.pathname === "/me") return json(res, 200, { user: { user_id: "semantic-user" }, company: { company_id: "semantic-company" }, identity: { user_id: "semantic-user", company_id: "semantic-company" } });
    if (url.pathname === "/reports") return json(res, 200, { reports: [] });
    if (url.pathname === "/ai-ceo/chat-history") return json(res, 200, { turns: [] });
    if (url.pathname === "/stores/semantic-store/merchant-ceo/chat") {
      const chunks = [];
      for await (const chunk of req) chunks.push(chunk);
      const body = JSON.parse(Buffer.concat(chunks).toString("utf8"));
      bodies.push(body);
      receivedRequest?.(body);
      await responseReady;
      return json(res, responseStatus, respond(body));
    }
    return json(res, 200, { secret_exposed: false });
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const base = `http://127.0.0.1:${server.address().port}`;
  let browser;
  try {
    browser = await chromium.launch({ headless: true, channel: process.env.JIEJING_PLAYWRIGHT_CHANNEL || "chrome" });
    const page = await browser.newPage({ viewport: { width: 1100, height: 800 } });
    const errors = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.route("**/*", (route) => new URL(route.request().url()).origin === base ? route.continue() : route.abort());
    await seed(page, base);
    await page.evaluate(() => { state.saasAiCeoPendingAttachments = [{ asset_id: "asset-new-unconsumed", original_filename: "new.jpg" }]; });
    responseReady = new Promise((resolve) => { releaseResponse = resolve; });
    const received = new Promise((resolve) => { receivedRequest = resolve; });
    respond = (body) => success(body);
    await page.locator("#ceoInput").fill("新建一个独立商品项目：银色木柄咖啡量勺，旧商品保持原样。");
    await page.locator("#ceoForm button").click();
    const body = await received;
    const before = await snapshot(page);
    assert.equal(before.route, oldIdentity.key, "submitting text must not clear the current route before the server plan");
    assert.equal(before.draft.fields.title, "商家编辑的标题");
    assert.deepEqual(body.active_listing_context.listing_project_identity, oldIdentity);
    assert.ok(body.conversation_history.length, "planner must receive frozen conversation context");
    assert.equal(body.command.intent, "general_chat", "browser command must remain neutral before planning");
    releaseResponse();
    await page.evaluate(async () => { await state.saasLastCeoCommandPersistPromise; });
    const after = await snapshot(page);
    assert.equal(after.route, newIdentity.key, "only a validated server new-project plan may bind the new project");
    assert.equal(after.detached[oldIdentity.key].draft.fields.title, "商家编辑的标题");
    assert.equal(after.pending, null);
    assert.deepEqual(await page.evaluate(() => saasAiCeoPendingSourceAssetIds()), ["asset-new-unconsumed"],
      "a successfully committed new project must retain its unconsumed input attachment");
    assert.deepEqual(errors, []);
    console.log("PASS semantic frontend: deferred new-project binding and old-draft preservation");
    await page.close();

    const replayPage = await browser.newPage();
    await seed(replayPage, base);
    await replayPage.evaluate(() => { state.saasAiCeoPendingAttachments = [{ asset_id: "asset-reconcile-unconsumed", original_filename: "reconcile.jpg" }]; });
    responseReady = Promise.resolve();
    respond = () => ({ ai_ceo_chat_request: { status: "in_progress", retry_after_ms: 10 }, usage_consumed: false, listing_created: false });
    const replayStart = bodies.length;
    await replayPage.locator("#ceoInput").fill("这次换一个单独商品，原来的别动。");
    await replayPage.locator("#ceoForm button").click();
    await replayPage.evaluate(async () => {
      await state.saasLastCeoCommandPersistPromise;
      stopSaasPendingNewListingProjectReconciliation();
      saveSaasProtectedStateSnapshot();
    });
    const beforeRefresh = await snapshot(replayPage);
    assert.equal(beforeRefresh.pending.phase, "uncertain");
    respond = (body) => success(body);
    await seed(replayPage, base);
    const replayResult = await replayPage.evaluate(async () => {
      state.saasProtectedStateReady = false;
      const hydrated = hydrateSaasProtectedStateFromCache({
        me: { user: { user_id: "semantic-user" }, company: { company_id: "semantic-company" }, identity: { user_id: "semantic-user", company_id: "semantic-company" } },
        storeId: "semantic-store", stores: [{ store_id: "semantic-store", company_id: "semantic-company" }],
      });
      state.saasProtectedStateReady = true;
      const result = await runSaasPendingNewListingProjectReconcileAttempt({ scheduleNext: false });
      return { hydrated, result, route: saasMerchantProjectRouteId(), pending: state.saasPendingNewListingProjectRequest };
    });
    assert.equal(replayResult.hydrated, true, "reload must hydrate a scoped protected snapshot");
    assert.equal(replayResult.route, newIdentity.key, "a reconciled server semantic plan must complete the same pending request after refresh");
    assert.equal(replayResult.pending, null);
    assert.deepEqual(await replayPage.evaluate(() => saasAiCeoPendingSourceAssetIds()), ["asset-reconcile-unconsumed"],
      "reconciliation must restore unconsumed attachments after its own accepted project switch");
    for (const body of bodies.slice(replayStart)) assert.deepEqual(body, bodies[replayStart], "reconciliation must replay the exact frozen payload");
    console.log("PASS semantic frontend: refresh reconciliation uses one frozen request and binds its server plan");
    await replayPage.close();

    const currentPage = await browser.newPage();
    await seed(currentPage, base);
    responseReady = Promise.resolve();
    respond = (body) => ({ ...success(body, "current", { consumed_source_asset_ids: ["asset-current"], workflow_target: "product_intake" }),
      product_vision_report: { report_id: "report-current-vision", report_type: "merchant.product_facts", listing_project_identity: oldIdentity },
      product_vision_fact_packet: { product_name: "原商品A", source: "backend_product_vision_extraction",
        source_confirmed_facts: { material: "Wood" }, merchant_confirmed_facts: {},
        derived_listing_suggestions: { net_weight_g: "35" }, unknown_facts: ["net_weight_g"], source_records: [], fact_conflicts: [], field_evidence: {} },
    });
    await currentPage.evaluate(() => { state.saasAiCeoPendingAttachments = [{ asset_id: "asset-current", original_filename: "current.jpg" }]; });
    await currentPage.locator("#ceoInput").fill("补充这张实物图，请整理当前商品待核对的信息。");
    await currentPage.locator("#ceoForm button").click();
    await currentPage.evaluate(async () => { await state.saasLastCeoCommandPersistPromise; });
    const current = await snapshot(currentPage);
    assert.equal(current.route, oldIdentity.key);
    assert.deepEqual(current.draft.fields, { title: "商家编辑的标题", selling_points: "商家编辑的卖点", description: "商家编辑的描述" });
    assert.equal(current.draft.merchant_product_fact_packet.merchant_confirmed_facts.material, "Steel");
    assert.equal(current.draft.merchant_product_fact_packet.derived_listing_suggestions.net_weight_g, "35");
    assert.equal(current.draft.merchant_product_fact_packet.derived_listing_suggestions.material, "Wood");
    assert.equal(current.pending, null);
    console.log("PASS semantic frontend: current-product image intake preserves confirmed facts and edited copy");
    await currentPage.close();

    for (const action of ["new", "current"]) {
      const textPage = await browser.newPage();
      await seed(textPage, base);
      responseReady = Promise.resolve();
      const packet = { product_name: "银色木柄15mL咖啡量勺", source: "backend_semantic_project_anchor",
        source_confirmed_facts: {}, merchant_confirmed_facts: {}, derived_listing_suggestions: {
          material: "304不锈钢和实木", supplier_item_number: "SPOON15", length_cm: "18", width_cm: "4", height_cm: "2", net_weight_g: "42",
        }, unknown_facts: ["material", "supplier_item_number", "length_cm", "width_cm", "height_cm", "net_weight_g"],
        source_records: [], field_evidence: {}, fact_conflicts: [] };
      respond = (body) => {
        const payload = success(body, action, { workflow_target: "listing_draft" });
        return { ...payload, product_vision_fact_packet: packet, product_vision_report: {
          report_id: "report-text-facts", report_type: "merchant.product_facts", status: "saved", task_id: "text-facts-task",
          company_id: "semantic-company", store_id: "semantic-store",
          report: { listing_project_identity: payload.semantic_dispatch.target_project_identity,
            semantic_dispatch: payload.semantic_dispatch, merchant_product_fact_packet: packet },
        } };
      };
      await textPage.evaluate(() => { state.saasAiCeoPendingAttachments = [{ asset_id: "asset-text-unconsumed", original_filename: "not-read.jpg" }]; });
      await textPage.locator("#ceoInput").fill("整理量勺资料：材质304不锈钢和实木，货号SPOON15，尺寸18×4×2cm，净重42g；图片先不要用。");
      await textPage.locator("#ceoForm button").click();
      await textPage.evaluate(async () => { await state.saasLastCeoCommandPersistPromise; });
      const textResult = await snapshot(textPage);
      assert.equal(textResult.route, action === "new" ? newIdentity.key : oldIdentity.key);
      assert.deepEqual(textResult.draft.merchant_product_fact_packet.derived_listing_suggestions, packet.derived_listing_suggestions,
        `${action} saved text suggestions must reach the real product draft`);
      assert.equal(textResult.draft.merchant_product_fact_packet.merchant_confirmed_facts.material, action === "new" ? undefined : "Steel");
      if (action === "current") assert.equal(textResult.draft.fields.title, "商家编辑的标题");
      else assert.equal(textResult.detached[oldIdentity.key].draft.fields.title, "商家编辑的标题");
      assert.deepEqual(await textPage.evaluate(() => saasAiCeoPendingSourceAssetIds()), ["asset-text-unconsumed"]);
      console.log(`PASS semantic frontend: ${action} saved text suggestions remain unconfirmed and preserve unconsumed images`);
      await textPage.close();
    }

    for (const invalid of ["missing artifact", "wrong artifact identity", "foreign artifact company", "wrong artifact command", "unconsumed vision artifact"]) {
      const textNegativePage = await browser.newPage();
      await seed(textNegativePage, base);
      responseReady = Promise.resolve();
      respond = (body) => {
        const payload = success(body, "current");
        const packet = { product_name: "不得覆盖A", source: invalid === "unconsumed vision artifact" ? "backend_product_vision_extraction" : "backend_semantic_project_anchor",
          source_confirmed_facts: {}, merchant_confirmed_facts: {}, derived_listing_suggestions: { net_weight_g: "42" }, unknown_facts: ["net_weight_g"] };
        const report = { report_id: "text-negative-facts", report_type: "merchant.product_facts", status: "saved", task_id: "text-negative-task",
          company_id: invalid === "foreign artifact company" ? "other-company" : "semantic-company", store_id: "semantic-store",
          report: { listing_project_identity: invalid === "wrong artifact identity" ? newIdentity : oldIdentity,
            semantic_dispatch: { ...payload.semantic_dispatch, ...(invalid === "wrong artifact command" ? { command_id: "other-command" } : {}) },
            merchant_product_fact_packet: packet } };
        return { ...payload, product_vision_fact_packet: packet, product_vision_report: invalid === "missing artifact" ? null : report };
      };
      const prior = await snapshot(textNegativePage);
      await textNegativePage.locator("#ceoInput").fill("补充当前商品净重42g，先作为待确认资料。");
      await textNegativePage.locator("#ceoForm button").click();
      await textNegativePage.evaluate(async () => { await state.saasLastCeoCommandPersistPromise; });
      const actual = await snapshot(textNegativePage);
      assert.deepEqual(actual.draft, prior.draft, `${invalid} cannot project text facts`);
      console.log(`PASS semantic frontend: ${invalid} cannot authorize text fact projection`);
      await textNegativePage.close();
    }

    for (const [label, action, overrides] of [
      ["clarification", "clarify", { status: "clarification_required" }],
      ["blocked", "none", { status: "blocked" }],
      ["ordinary consultation", "none", {}],
      ["foreign company", "current", { company_id: "another-company", consumed_source_asset_ids: ["asset-negative"] }],
      ["wrong command", "current", { command_id: "other-command", consumed_source_asset_ids: ["asset-negative"] }],
      ["wrong source identity", "current", { submitted_project_identity: { ...oldIdentity, source_report_id: "other-report" }, consumed_source_asset_ids: ["asset-negative"] }],
      ["foreign attachment", "current", { consumed_source_asset_ids: ["asset-not-submitted"] }],
      ["unconsumed attachment", "current", {}],
      ["image read without saved artifact", "current", { consumed_source_asset_ids: ["asset-negative"] }],
    ]) {
      const negativePage = await browser.newPage();
      await seed(negativePage, base);
      responseReady = Promise.resolve();
      respond = (body) => ({ ...success(body, action, overrides), product_vision_fact_packet: {
        product_name: "不得覆盖原品", source_confirmed_facts: { material: "Wood" }, merchant_confirmed_facts: {}, derived_listing_suggestions: {}, unknown_facts: [],
      } });
      await negativePage.evaluate(() => { state.saasAiCeoPendingAttachments = [{ asset_id: "asset-negative", original_filename: "input.jpg" }]; });
      const beforeNegative = await snapshot(negativePage);
      await negativePage.locator("#ceoInput").fill("这张图怎么办，你先看看。");
      await negativePage.locator("#ceoForm button").click();
      await negativePage.evaluate(async () => { await state.saasLastCeoCommandPersistPromise; });
      const afterNegative = await snapshot(negativePage);
      assert.equal(afterNegative.route, oldIdentity.key, `${label} must not rebind the project`);
      assert.deepEqual(afterNegative.draft, beforeNegative.draft, `${label} must not apply a returned artifact`);
      const attachmentIds = await negativePage.evaluate(() => saasAiCeoPendingSourceAssetIds());
      assert.deepEqual(attachmentIds, label === "image read without saved artifact" ? [] : ["asset-negative"], `${label} must preserve unconsumed input attachments`);
      console.log(`PASS semantic frontend: ${label} leaves project and attachments intact`);
      await negativePage.close();
    }

    const latePage = await browser.newPage();
    await seed(latePage, base);
    await latePage.evaluate(() => { state.saasAiCeoPendingAttachments = [{ asset_id: "asset-late-unconsumed", original_filename: "late.jpg" }]; });
    responseReady = new Promise((resolve) => { releaseResponse = resolve; });
    const lateReceived = new Promise((resolve) => { receivedRequest = resolve; });
    respond = (body) => success(body);
    await latePage.locator("#ceoInput").fill("换成另一件商品独立处理。");
    await latePage.locator("#ceoForm button").click();
    await lateReceived;
    await latePage.evaluate(() => {
      const identity = { key: "semantic-project-c", source_report_id: "report-c", candidate_id: "candidate-c" };
      syncSaasProjectRoute("cockpit", { projectId: identity.key });
      state.saasListingComposerDraft = { product: "用户随后打开的C", title: "用户随后打开的C", listing_project_identity: identity };
      state.aiCeoTaskContextProjectId = identity.key;
    });
    releaseResponse();
    await latePage.evaluate(async () => { await state.saasLastCeoCommandPersistPromise; });
    const late = await snapshot(latePage);
    assert.equal(late.route, "semantic-project-c");
    assert.equal(late.draft.title, "用户随后打开的C");
    assert.equal(late.task, "semantic-project-c");
    assert.deepEqual(await latePage.evaluate(() => saasAiCeoPendingSourceAssetIds()), [],
      "a late response must not restore the previous project's attachment into a later selected project");
    assert.ok(late.turns.some((turn) => turn.semantic_dispatch?.target_project_identity?.key === newIdentity.key));
    console.log("PASS semantic frontend: a late new-project result is retained without replacing a later selected project");
    await latePage.close();

    const candidatePage = await browser.newPage();
    await seed(candidatePage, base);
    const selectedCandidate = await candidatePage.evaluate(() => {
      const identity = { key: "server-candidate-one", source_report_id: "report_candidates", candidate_id: "candidate_1" };
      const candidate = { candidate_id: "candidate_1", name: "Compact Cable Organizer", selected: true, listing_project_identity: identity };
      const report = { report_id: "report_candidates", report_type: "ai_ceo.market_research", store_id: "semantic-store", company_id: "semantic-company",
        status: "saved", created_at: new Date().toISOString(), report: { product: candidate.name, answer: "候选商品 1：Compact Cable Organizer", merchant_question: "帮我寻找适合的新商品方向。",
          product_candidates: [candidate], selected_product_candidate: candidate, listing_handoff: { ready_for_listing_draft: true },
          semantic_dispatch: { contract_version: "ai_ceo_semantic_dispatch_v1", status: "ready", project_action: "none", command_id: "candidate-command",
            idempotency_key: "ai-ceo:candidate-command", request_task_id: "candidate-task", company_id: "semantic-company", store_id: "semantic-store",
            submitted_project_identity: {}, target_project_identity: {}, consumed_source_asset_ids: [], workflow_target: "research" } } };
      state.saasReports = [report];
      const turn = saasAiCeoMarketTurnFromReport(report);
      const routeBefore = saasMerchantProjectRouteId();
      updateSaasAiCeoLatestReply(turn);
      const routeAfterReport = saasMerchantProjectRouteId();
      const imported = applySaasAiCeoMarketTurnToListing(turn);
      return { imported, routeBefore, routeAfterReport, identity: state.saasListingComposerDraft?.listing_project_identity,
        reference: saasAiCeoActiveListingContext()?.listing_project_identity };
    });
    assert.equal(selectedCandidate.routeAfterReport, selectedCandidate.routeBefore, "research candidates must not automatically select a project");
    assert.equal(selectedCandidate.imported, true);
    assert.deepEqual(selectedCandidate.identity, { key: "server-candidate-one", source_report_id: "report_candidates", candidate_id: "candidate_1" }, "explicit candidate import must use its server-issued identity");
    assert.deepEqual(selectedCandidate.reference, selectedCandidate.identity, "first continuation must send that same candidate identity");
    console.log("PASS semantic frontend: research remains unbound until explicit candidate import adopts server identity");
    await candidatePage.close();

    const upgradePage = await browser.newPage();
    await seed(upgradePage, base);
    responseReady = Promise.resolve();
    responseStatus = 409;
    respond = () => ({ error_code: "ai_ceo_client_upgrade_required", usage_consumed: false, listing_created: false });
    const upgradeText = "请继续当前商品，图片先留着。";
    await upgradePage.evaluate(() => { state.saasAiCeoPendingAttachments = [{ asset_id: "asset-upgrade", original_filename: "upgrade.jpg" }]; });
    const beforeUpgrade = await snapshot(upgradePage);
    const upgradeStart = bodies.length;
    await upgradePage.locator("#ceoInput").fill(upgradeText);
    await upgradePage.locator("#ceoForm button").click();
    await upgradePage.evaluate(async () => { await state.saasLastCeoCommandPersistPromise; });
    const afterUpgrade = await snapshot(upgradePage);
    assert.equal(bodies.length, upgradeStart + 1, "upgrade rejection must not automatically retry");
    assert.equal(bodies.at(-1).semantic_dispatch_contract, "ai_ceo_semantic_dispatch_v1");
    assert.equal(afterUpgrade.route, beforeUpgrade.route);
    assert.deepEqual(afterUpgrade.draft, beforeUpgrade.draft);
    assert.equal(afterUpgrade.pending.phase, "failed");
    assert.equal(await upgradePage.locator("#ceoInput").inputValue(), upgradeText);
    assert.deepEqual(await upgradePage.evaluate(() => saasAiCeoPendingSourceAssetIds()), ["asset-upgrade"]);
    assert.match(await upgradePage.locator("body").innerText(), /刷新页面后重新发送/);
    console.log("PASS semantic frontend: upgrade rejection preserves input and attachments without retrying");
    await upgradePage.close();
    responseStatus = 200;

    const longPage = await browser.newPage();
    await seed(longPage, base);
    responseReady = Promise.resolve();
    respond = (body) => success(body, "none");
    await longPage.evaluate(() => { state.saasAiCeoPendingAttachments = [{ asset_id: "asset-long", original_filename: "long.jpg" }]; });
    const longText = "请核对当前商品。".repeat(120) + "最后补充：不要创建新项目，不要保存图片。";
    assert.ok(longText.length > 900);
    const longStart = bodies.length;
    await longPage.locator("#ceoInput").fill(longText);
    await longPage.locator("#ceoForm button").click();
    await longPage.evaluate(async () => { await state.saasLastCeoCommandPersistPromise; });
    assert.equal(bodies.length, longStart, "overlong raw input must be rejected before any truncated model request");
    assert.equal(await longPage.locator("#ceoInput").inputValue(), longText);
    assert.deepEqual(await longPage.evaluate(() => saasAiCeoPendingSourceAssetIds()), ["asset-long"]);
    assert.match(await longPage.locator("body").innerText(), /900/);
    console.log("PASS semantic frontend: overlong input is rejected without truncating or losing the draft");
    await longPage.close();
  } finally {
    releaseResponse?.();
    if (browser) await browser.close();
    await new Promise((resolve) => server.close(resolve));
  }
}
main().catch((error) => { console.error(error); process.exitCode = 1; });
