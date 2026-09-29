#!/usr/bin/env node
/* Owned local fixture: real app history controls, controlled history HTTP.
   No model, FAL, eBay, payment, refund, OAuth, or production requests. */
const fs = require("fs");
const http = require("http");
const path = require("path");
const os = require("os");
const assert = require("assert/strict");
const crypto = require("crypto");
const { chromium } = require("../output/codex-playwright-deps/node_modules/playwright-core");
const root = path.resolve(__dirname, "..");
const turns = Array.from({ length: 75 }, (_, index) => ({
  assistant_id: `history-local-${String(index + 1).padStart(3, "0")}`,
  user_text: `本地历史问题 ${index + 1}`,
  assistant_text: `本地历史回答 ${index + 1}。这段内容用于核对更早对话可见、顺序正确和滚动位置稳定。`,
  created_at: new Date(Date.UTC(2026, 8, 1, 0, index)).toISOString(),
  status: "model_answered", route: "general_chat", store_id: "history-store",
  market_report_id: `report_history_${index + 1}`,
}));
const counters = { get: 0, older: 0, sync: 0, expensive: 0, authProbe: 0, authRefresh: 0 };
const archiveProtocol = { requests: [], syncBodies: [], turns: [], responseStatus: 200, loseFinal: false };
let historyControl = null;
let server;
let browser;
function send(res, status, value) {
  res.writeHead(status, { "content-type": "application/json", "cache-control": "no-store" });
  res.end(JSON.stringify(value));
}
function holdNextHistory(status = 0, payload = null) {
  let release;
  let received;
  const receivedPromise = new Promise((resolve) => { received = resolve; });
  const releasePromise = new Promise((resolve) => { release = resolve; });
  historyControl = { status, payload, received, releasePromise };
  return { release, receivedPromise };
}
async function seedAccount(page, userId = "history-user", reset = false) {
  await page.evaluate(({ userId, reset }) => {
    if (reset) {
      clearSaasSessionFromStorage();
      resetSaasProtectedWorkbenchState();
    }
    state.saasToken = "local-fixture-only";
    state.saasUser = { user_id: userId };
    state.saasIdentity = { user_id: userId, company_id: `company-${userId}` };
    state.saasCompany = { company_id: `company-${userId}` };
    state.saasStores = [{ store_id: "history-store", platform: "ebay" }];
    state.saasProtectedStateReady = true;
    state.saasSessionExpiryHandled = false;
    bindSaasAiCeoHistoryControls(document.querySelector("#ceoChat"));
  }, { userId, reset });
}
async function verifyActualChatLayout(browser, base) {
  const results = [];
  for (const width of [1440, 1024]) {
    for (const variant of ["empty", "project"]) {
      const context = await browser.newContext({ viewport: { width, height: width === 1440 ? 1000 : 900 } });
      const errors = [];
      const requests = [];
      await context.route("**/*", (route) => {
        const request = route.request();
        const url = new URL(request.url());
        if (url.origin === base && request.method() === "GET" && /^\/(visual-app\.html|app\.js|styles\.css|assets\/)/.test(url.pathname)) return route.continue();
        if (url.protocol === "data:") return route.continue();
        requests.push(`${request.method()} ${url.pathname}`);
        return route.abort();
      });
      const visual = await context.newPage();
      visual.on("pageerror", (error) => errors.push(error.message));
      await visual.goto(`${base}/visual-app.html?start=app&view=cockpit&qa=public-saas&saasApiBase=${encodeURIComponent(base)}`);
      await visual.evaluate(({ variant, width }) => {
        window.__JIEJING_FORCE_PUBLIC_MVP__ = true;
        localStorage.setItem(saasStorageKeys.sessionHint, "1");
        localStorage.setItem(saasStorageKeys.storeId, "ui-fixture-store");
        state.saasToken = "local-visual-fixture-only";
        state.saasIdentity = { user_id: "ui-fixture-user", company_id: "ui-fixture-company" };
        state.saasUser = { user_id: "ui-fixture-user", email: "ui-fixture@example.test" };
        state.saasCompany = { company_id: "ui-fixture-company" };
        state.saasStores = [{ store_id: "ui-fixture-store", store_name: "eBay 店铺", platform: "ebay", status: "authorized" }];
        state.activeStore = "ui-fixture-store";
        state.saasConnected = true;
        state.saasProtectedStateReady = true;
        state.saasLoading = false;
        state.saasSessionExpiryHandled = false;
        state.saasAiCeoThread = [];
        state.saasAiCeoLatestTurn = null;
        state.saasReports = [];
        state.saasTasks = [];
        state.saasCeoCommandChatVisible = false;
        state.saasMerchantProjectStatus = null;
        state.view = "cockpit";
        state.dna.merchantStage = "store_opened";
        syncSaasPublicMvpMode();
        if (variant === "project") {
          const identity = { key: "ui-fixture-tablet-project", source_report_id: "ui-fixture-report", candidate_id: "candidate_1" };
          state.saasAiCeoThread = [
            { assistant_id: "ui-fixture-chat-1", user_text: "我有一款折叠平板电脑支架，帮我整理商品资料并准备 eBay Listing。", assistant_text: "可以。先把商品图片和现有规格发给我，我会整理到商品资料中。缺少或互相冲突的信息会标为待确认，不会自动当成真实事实。", created_at: "2026-09-05T08:00:00Z" },
            { assistant_id: "ui-fixture-chat-2", user_text: "图片已经补充，先整理草稿，材质和包装重量我再核对。", assistant_text: "已整理当前商品资料，并保留材质和包装重量两项待确认。\n\n你可以在“选品与上架”检查标题、描述和商品规格。商品事实与图片审核完成后，再进行 eBay 发布前检查；最终发布仍需要你确认。", created_at: "2026-09-05T08:01:00Z" },
          ].map((turn) => normalizeSaasAiCeoLatestTurn({ ...turn, store_id: "ui-fixture-store", route: "ebay_workflow", status: "model_answered", listing_project_identity: identity }));
          state.saasAiCeoLatestTurn = state.saasAiCeoThread[1];
          state.saasMerchantProjectStatus = { snapshot_version: "merchant_project_status_v1", project: { project_id: identity.key, product_name: "折叠平板电脑支架" }, current_stage: "facts", overall_status: "blocked", stages: [
            { key: "research", label: "商品方向", status: "completed" },
            { key: "facts", label: "商品资料", status: "blocked", is_current: true, detail: "请核对材质和包装重量，再继续完善 Listing。" },
          ], blocker: { key: "merchant_product_facts_missing", title: "还有 2 项资料待确认" }, next_action: { view: "product", label: "核对商品资料" } };
          state.saasListingComposerDraft = { product: "折叠平板电脑支架", listing_project_identity: identity, merchant_required_answers: ["材质", "包装重量"] };
          setSaasAiCeoTaskContextState("active_product_task", width >= 1280, { projectId: identity.key });
        } else setSaasAiCeoTaskContextState("plain_consultation", false);
        [entryShell, siteShell, onboardingShell].forEach((shell) => shell.classList.add("is-hidden"));
        appShell.classList.remove("is-hidden");
        document.documentElement.classList.add("app-ready");
        document.documentElement.classList.remove("app-shell-empty", "app-auth-pending");
        document.body.classList.remove("site-locked");
        document.querySelectorAll(".view").forEach((view) => view.classList.toggle("is-active", view.id === "view-cockpit"));
        renderAccountMenu();
        renderSaasCockpitRealWorkbench();
        document.addEventListener("click", (event) => {
          const control = event.target.closest("[data-ai-ceo-task-context-toggle], [data-ai-ceo-task-context-close]");
          if (control) { event.preventDefault(); handleSaasAiCeoTaskContextToggle(control); }
        });
      }, { variant, width });
      await visual.locator("#ceoInput").fill("本地界面检查，不发送");
      assert.equal(await visual.locator("#ceoInput").inputValue(), "本地界面检查，不发送");
      await visual.locator("#ceoInput").fill("");
      const geometry = await visual.evaluate(() => {
        const chat = document.querySelector(".saas-ai-ceo-thread").getBoundingClientRect();
        const composer = document.querySelector("#ceoForm").getBoundingClientRect();
        const send = document.querySelector("#ceoForm button[type=submit]");
        const button = send.getBoundingClientRect();
        const hit = document.elementFromPoint(button.x + button.width / 2, button.bottom - 2);
        return { chatBottom: chat.bottom, composerBottom: composer.bottom, sendBottomHit: hit === send || send.contains(hit), overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth };
      });
      const screenshot = path.join(os.tmpdir(), `jiejing-ai-ceo-layout-${variant}-${width}-${Date.now()}.png`);
      await visual.screenshot({ path: screenshot });
      assert(geometry.composerBottom <= geometry.chatBottom + 1 && geometry.sendBottomHit, `${variant} ${width}: composer and send button must remain fully usable: ${JSON.stringify(geometry)}`);
      assert(geometry.overflow <= 1, `${variant} ${width}: no horizontal overflow`);
      const taskStates = [];
      if (variant === "project") {
        for (let transition = 0; transition < 3; transition += 1) {
          const taskGeometry = await visual.evaluate(() => {
            const task = document.querySelector("[data-ai-ceo-task-context]");
            const summary = task.querySelector("[data-ai-ceo-task-context-toggle]");
            const expanded = summary.getAttribute("aria-expanded") === "true";
            const panel = task.getBoundingClientRect();
            const chat = document.querySelector(".saas-ai-ceo-thread").getBoundingClientRect();
            const firstUser = document.querySelector("#ceoChat .message.user").getBoundingClientRect();
            const toggle = summary.getBoundingClientRect();
            const hit = document.elementFromPoint(toggle.x + toggle.width / 2, toggle.y + toggle.height / 2);
            const detail = task.querySelector("[data-ai-ceo-task-context-detail]");
            const action = task.querySelector("[data-ai-ceo-task-next-action]");
            const actionBox = action.getBoundingClientRect();
            const actionHit = document.elementFromPoint(actionBox.x + actionBox.width / 2, actionBox.y + actionBox.height / 2);
            const composer = document.querySelector("#ceoForm").getBoundingClientRect();
            const send = document.querySelector("#ceoForm button[type=submit]");
            const sendBox = send.getBoundingClientRect();
            const sendHit = document.elementFromPoint(sendBox.x + sendBox.width / 2, sendBox.bottom - 2);
            return { expanded, summaryHit: hit === summary || summary.contains(hit), chatWidth: chat.width, taskWidth: panel.width,
              overlap: panel.x < firstUser.right && panel.right > firstUser.x && panel.y < firstUser.bottom && panel.bottom > firstUser.y,
              composerUsable: composer.bottom <= chat.bottom + 1 && (sendHit === send || send.contains(sendHit)),
              detailVisible: !detail.hidden && !!detail.getClientRects().length, actionHit: actionHit === action || action.contains(actionHit) };
          });
          if (!taskGeometry.expanded || width > 1100) {
            assert.equal(taskGeometry.overlap, false, `${width}: task summary must not cover conversation: ${JSON.stringify(taskGeometry)}`);
            assert.equal(taskGeometry.summaryHit, true, `${width}: task summary must remain clickable`);
            assert.equal(taskGeometry.composerUsable, true, `${width}: toggling the task must leave the composer usable`);
          }
          if (taskGeometry.expanded) {
            assert(taskGeometry.detailVisible && taskGeometry.actionHit, `${width}: expanded task detail action must be reachable`);
            if (width > 1100) assert(taskGeometry.chatWidth > taskGeometry.taskWidth * 1.8, "desktop conversation must remain primary");
          }
          taskStates.push(taskGeometry);
          if (transition < 2) {
            taskGeometry.screenshot = path.join(os.tmpdir(), `jiejing-ai-ceo-layout-project-${taskGeometry.expanded ? "expanded" : "collapsed"}-${width}-${Date.now()}.png`);
            await visual.screenshot({ path: taskGeometry.screenshot });
          }
          if (transition < 2) await visual.locator(taskGeometry.expanded && width <= 1100 ? "[data-ai-ceo-task-context-close]" : "[data-ai-ceo-task-context-toggle]").click();
        }
      }
      assert.deepEqual(errors, []);
      assert.deepEqual(requests, [], "visual inspection must not invoke APIs or external providers");
      results.push({ variant, width, screenshot, ...geometry, task_states: taskStates });
      await context.close();
    }
  }
  return results;
}
async function main() {
  const source = fs.readFileSync(path.join(root, "app.js"), "utf8");
  const boot = /exposeLocalJiejingTestHooks\(\);\r?\ninit\(\);\r?\nrunLocalJiejingQaScenarioFromUrl\(\);\s*$/;
  assert(boot.test(source), "actual app boot seam must remain available");
  server = http.createServer(async (req, res) => {
    const url = new URL(req.url, "http://127.0.0.1");
    if (url.pathname === "/visual-app.html" || url.pathname === "/app.js" || url.pathname.startsWith("/assets/")) {
      const name = url.pathname === "/visual-app.html" ? "app.html" : url.pathname.slice(1);
      const file = path.resolve(root, name);
      if (!file.startsWith(root + path.sep) || !fs.existsSync(file) || !fs.statSync(file).isFile()) return send(res, 404, {});
      const mime = { ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png", ".webp": "image/webp", ".jpg": "image/jpeg", ".woff2": "font/woff2" };
      res.writeHead(200, { "content-type": mime[path.extname(file)] || "application/octet-stream" });
      return res.end(name === "app.js" ? source.replace(boot, "exposeLocalJiejingTestHooks();\n") : fs.readFileSync(file));
    }
    if (url.pathname === "/app.html") {
      res.writeHead(200, { "content-type": "text/html; charset=utf-8" });
      return res.end(`<!doctype html><html><head><meta charset="utf-8"><title>捷境 AI CEO 历史本地验收</title>
        <link rel="stylesheet" href="/styles.css"><style>body{margin:0;padding:24px;background:#f6f8f7}main{max-width:980px;margin:auto}.saas-ai-ceo-thread{background:white;border:1px solid #dae4df;border-radius:16px;padding:18px}#ceoChat{height:680px;overflow:auto;overflow-anchor:none}.message{margin:12px 0}h1{font-size:22px}</style></head>
        <body data-view="cockpit"><main><h1>AI CEO · 对话历史</h1><section class="saas-ai-ceo-thread"><div id="ceoChat"></div></section></main><script src="/app-test.js"></script></body></html>`);
    }
    if (url.pathname === "/app-test.js") {
      res.writeHead(200, { "content-type": "text/javascript; charset=utf-8" });
      return res.end(source.replace(boot, "exposeLocalJiejingTestHooks();\n"));
    }
    if (url.pathname === "/styles.css") {
      res.writeHead(200, { "content-type": "text/css" });
      return res.end(fs.readFileSync(path.join(root, "styles.css")));
    }
    if (req.headers["x-local-archive-fixture"] === "1") {
      if (url.pathname === "/me") return send(res, 200, { user: { user_id: "archive-user" }, company: { company_id: "company-archive-user" } });
      let raw = "";
      for await (const chunk of req) raw += chunk;
      const body = raw ? JSON.parse(raw) : {};
      if (url.pathname === "/stores/history-store/merchant-ceo/chat") {
        archiveProtocol.requests.push(body);
        const failure = archiveProtocol.responseStatus >= 400;
        const requestId = "task_ai_ceo_request_" + crypto.createHash("sha256").update(`ai-ceo-chat-request-v1\0company-archive-user\0history-store\0${body.idempotency_key}`).digest("hex").slice(0, 40);
        const metadata = { contract_version: "server_finalized_chat_archive_v1", request_task_id: requestId, assistant_id: "ceo-server-" + crypto.createHash("sha256").update(requestId).digest("hex").slice(0, 32), created_at: new Date(Date.UTC(2026, 8, 5, 8, archiveProtocol.requests.length)).toISOString(), archived: true };
        const chat = { status: failure ? "model_call_failed" : "model_answered", answer: failure ? "模型暂时不可用，这次没有生成新内容。" : "毛利扣除商品直接成本，净利还扣除经营费用。", route: "general_chat" };
        archiveProtocol.turns.push({ assistant_id: metadata.assistant_id, created_at: metadata.created_at, user_text: body.message, assistant_text: chat.answer, status: chat.status, route: chat.route, store_id: "history-store" });
        if (archiveProtocol.loseFinal) return send(res, 200, { ai_ceo_chat_request: { status: "outcome_unknown" }, execution_result_known: false, ai_ceo_chat: { status: "request_outcome_unknown", answer: "正在核对本次请求。" } });
        if (failure) return send(res, archiveProtocol.responseStatus, { ai_ceo_chat: chat, ai_ceo_chat_history_turn: metadata, error_code: "model_call_failed", error: chat.answer });
        res.writeHead(200, { "content-type": "application/x-ndjson" });
        return res.end(JSON.stringify({ type: "delta", delta: chat.answer }) + "\n" + JSON.stringify({ type: "final", payload: { ai_ceo_chat: chat, ai_ceo_chat_history_turn: metadata } }) + "\n");
      }
      if (url.pathname.startsWith("/ai-ceo/chat-history")) {
        if (req.method === "POST") archiveProtocol.syncBodies.push(body);
        return send(res, 200, { ai_ceo_chat_history: { turns: archiveProtocol.turns, revision: "archive-v1", has_more: false, next_cursor: "", page_size: 30 } });
      }
      return send(res, 200, {});
    }
    if (url.pathname === "/me") { counters.authProbe += 1; return send(res, 401, { error: "session expired" }); }
    if (url.pathname === "/auth/refresh") { counters.authRefresh += 1; return send(res, 401, { error: "session_refresh_invalid" }); }
    if ((url.pathname === "/ai-ceo/chat-history" && req.method === "GET") || url.pathname === "/ai-ceo/chat-history/sync") {
      if (req.method === "POST") counters.sync += 1;
      else counters.get += 1;
      const cursor = url.searchParams.get("cursor");
      if (cursor) counters.older += 1;
      const control = historyControl;
      if (control) {
        historyControl = null;
        control.received();
        await control.releasePromise;
        if (control.status) return send(res, control.status, { error: control.status === 401 ? "session expired" : "local history temporarily unavailable" });
        if (control.payload) return send(res, 200, control.payload);
      }
      const end = cursor ? Number(cursor) : turns.length;
      const start = Math.max(0, end - 30);
      return send(res, 200, { ai_ceo_chat_history: {
        scope: "account", cross_store: true, turns: turns.slice(start, end), revision: "local-revision",
        has_more: start > 0, next_cursor: start > 0 ? String(start) : "", page_size: 30,
        pagination_contract: "2026-09-05-ai-ceo-history-keyset-v1",
      } });
    }
    if (url.pathname === "/ai-ceo/chat-history/sync") counters.sync += 1;
    if (/chat|media|publish|refund|checkout/.test(url.pathname)) counters.expensive += 1;
    return send(res, 404, { error: "fixture_not_found" });
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const base = `http://127.0.0.1:${server.address().port}`;
  browser = await chromium.launch({ channel: process.env.JIEJING_PLAYWRIGHT_CHANNEL || "chrome", headless: true });
  const layoutCases = await verifyActualChatLayout(browser, base);
  const browserContext = await browser.newContext({ viewport: { width: Number(process.env.JIEJING_HISTORY_VIEWPORT_WIDTH || 1440), height: 1000 } });
  const errors = [];
  browserContext.on("page", (createdPage) => createdPage.on("pageerror", (error) => errors.push(error.message)));
  await browserContext.route("**/*", (route) => {
    const url = new URL(route.request().url());
    if (url.origin === base || url.protocol === "data:") return route.continue();
    errors.push(`External request blocked: ${url.origin}`);
    return route.abort();
  });
  const page = await browserContext.newPage();
  await page.goto(`${base}/app.html?start=app&qa=public-saas&saasApiBase=${encodeURIComponent(base)}`);
  await seedAccount(page);
  await page.evaluate(() => refreshSaasAiCeoThreadFromBackend());
  assert.equal(await page.locator("#ceoChat .message.ai").count(), 12);
  const recentBefore = await page.evaluate(() => ({ context: saasAiCeoConversationHistoryForRequest(), sync: saasAiCeoThreadForBackendSync() }));
  for (let i = 0; i < 20; i += 1) {
    const button = page.locator("[data-ceo-load-older]");
    if (!(await button.count())) break;
    await button.click();
    await page.waitForTimeout(60);
  }
  assert.equal(await page.locator("#ceoChat .message.ai").count(), 75, "visible history must continue past the local 30-turn window");
  assert.equal(counters.older, 2, "history controls must fetch each earlier backend page once");
  assert.equal(counters.sync, 0, "reading an archive must not send it back to sync");
  assert.equal(counters.expensive, 0, "reading an archive must not trigger model/media/platform operations");
  const recentAfter = await page.evaluate(() => ({ context: saasAiCeoConversationHistoryForRequest(), sync: saasAiCeoThreadForBackendSync() }));
  assert.deepEqual(recentAfter, recentBefore, "archive display must not expand/change model context or sync payload");
  assert.equal(recentAfter.context.length, 8);
  assert.equal(recentAfter.context[7].market_report_id, "report_history_75", "Model follow-up must carry only the report reference for server-side evidence resolution");
  assert.equal(Object.hasOwn(recentAfter.context[7], "source_records"), false, "Browser snippets must not become authoritative report evidence");
  const pendingOrder = await page.evaluate(() => [
    { assistant_id: "server-future", created_at: "2026-09-29T12:04:00Z", pending: false },
    { assistant_id: "local-pending", created_at: "2026-09-29T12:01:00Z", pending: true },
  ].sort(compareSaasAiCeoThreadTurns).map((turn) => turn.assistant_id));
  assert.deepEqual(pendingOrder, ["server-future", "local-pending"], "A new pending question must remain after completed history despite client/server clock skew");
  const reusedSourceCopy = await page.evaluate(() => renderSaasAiCeoPerformanceSummaryMarkup({
    assistant_text: "修订后的报告", status: "model_answered", route: "ebay_workflow",
    performance: { search_cache_status: "report_reuse", source_record_count: 5 },
  }));
  assert.match(reusedSourceCopy, /沿用原报告 5 条来源 · 本轮未联网/);
  assert.doesNotMatch(reusedSourceCopy, /已查|已尝试联网/);
  assert.equal(recentAfter.sync.length, 30);
  const beforeRefresh = await page.evaluate(() => {
    const chat = document.querySelector("#ceoChat");
    chat.scrollTop = 150;
    chat.dataset.aiCeoScrollInitialized = "true";
    state.saasAiCeoAutoFollow = false;
    return { top: chat.scrollTop, cursor: saasAiCeoHistoryArchive().cursor };
  });
  turns.push({ ...turns[74], assistant_id: "history-local-076", user_text: "另一设备的新问题", created_at: "2026-09-02T00:00:00Z" });
  await page.evaluate(() => refreshSaasAiCeoThreadFromBackend());
  assert.equal(await page.locator("#history-local-001").count(), 1, "latest refresh must not push a previously displayed historical turn out of the view");
  const afterRefresh = await page.evaluate(() => ({ top: document.querySelector("#ceoChat").scrollTop, cursor: saasAiCeoHistoryArchive().cursor }));
  assert.deepEqual(afterRefresh, beforeRefresh, "latest refresh must retain the archive cursor and reading position");
  await page.evaluate(() => syncSaasAiCeoThreadWithBackend());
  assert.equal(await page.locator("#history-local-001").count(), 1, "sync response must preserve loaded archive turns");
  assert.equal(await page.evaluate(() => saasAiCeoHistoryArchive().cursor), beforeRefresh.cursor);
  const cases = ["75_turns_via_visible_control", "archive_not_model_or_sync_input", "latest_refresh_and_sync_preserve_archive"];
  const addCasePage = async () => {
    const casePage = await browserContext.newPage();
    await casePage.goto(`${base}/app.html?start=app&qa=public-saas&saasApiBase=${encodeURIComponent(base)}`);
    await seedAccount(casePage);
    await casePage.evaluate(() => refreshSaasAiCeoThreadFromBackend());
    for (let i = 0; i < 3; i += 1) await casePage.locator("[data-ceo-load-older]").click();
    assert.equal(await casePage.locator("#ceoChat .message.ai").count(), 30);
    return casePage;
  };
  const retryPage = await addCasePage();
  const previousCursor = await retryPage.evaluate(() => saasAiCeoHistoryArchive().cursor);
  const failedOlder = holdNextHistory(503);
  await retryPage.locator("[data-ceo-load-older]").click();
  await failedOlder.receivedPromise;
  const requestsWhileHeld = counters.older;
  await retryPage.evaluate(() => { void revealOlderSaasAiCeoTurns(document.querySelector("#ceoChat")); });
  await retryPage.waitForTimeout(40);
  assert.equal(counters.older, requestsWhileHeld, "repeated activation during a pending older-page request is single-flight");
  failedOlder.release();
  await retryPage.waitForFunction(() => saasAiCeoHistoryArchive().error);
  assert.equal(await retryPage.locator("#ceoChat .message.ai").count(), 30, "failed page keeps already displayed messages");
  assert.equal(await retryPage.evaluate(() => saasAiCeoHistoryArchive().cursor), previousCursor, "failure must not advance the cursor");
  assert.match(await retryPage.locator("[data-ceo-load-older]").innerText(), /重试/);
  const firstVisibleId = await retryPage.locator("#ceoChat .message.ai").first().getAttribute("id");
  const anchorBefore = await retryPage.locator(`[id="${firstVisibleId}"]`).evaluate((element) => element.getBoundingClientRect().top);
  await retryPage.locator("[data-ceo-load-older]").click();
  await retryPage.waitForFunction(() => !saasAiCeoHistoryArchive().loading && !saasAiCeoHistoryArchive().error && state.saasAiCeoVisibleTurnLimit === 38);
  await retryPage.waitForTimeout(80);
  const anchorAfter = await retryPage.locator(`[id="${firstVisibleId}"]`).evaluate((element) => element.getBoundingClientRect().top);
  assert(Math.abs(anchorAfter - anchorBefore) < 4, `older-page prepend must preserve the reading anchor (${anchorBefore} -> ${anchorAfter})`);
  assert.equal(await retryPage.locator("#ceoChat .message.ai").count(), 38);
  cases.push("singleflight", "failed_page_retry", "prepend_scroll_anchor");
  await retryPage.close();

  const filteredPage = await addCasePage();
  const filtered = holdNextHistory(0, { ai_ceo_chat_history: {
    scope: "account", cross_store: true, turns: [{ ...turns[0], status: "historical_no_model_reply" }],
    has_more: true, next_cursor: "15", page_size: 30,
  } });
  await filteredPage.locator("[data-ceo-load-older]").click();
  await filtered.receivedPromise;
  filtered.release();
  await filteredPage.waitForFunction(() => !saasAiCeoHistoryArchive().loading);
  assert.equal(await filteredPage.locator("#ceoChat .message.ai").count(), 30, "technical placeholder filtering is preserved");
  assert.equal(await filteredPage.locator("[data-ceo-load-older]").count(), 1, "a filtered page with has_more must not end pagination");
  await filteredPage.locator("[data-ceo-load-older]").click();
  await filteredPage.waitForFunction(() => state.saasAiCeoVisibleTurnLimit === 38);
  cases.push("filtered_page_keeps_cursor_progress");
  await filteredPage.close();

  for (const method of ["refresh", "sync", "older"]) {
    for (const returnToA of [false, true]) {
      const contextPage = await addCasePage();
      const stale = holdNextHistory();
      await contextPage.evaluate((method) => {
        window.oldHistoryRequest = method === "sync" ? syncSaasAiCeoThreadWithBackend() : method === "older"
          ? revealOlderSaasAiCeoTurns(document.querySelector("#ceoChat")) : refreshSaasAiCeoThreadFromBackend();
      }, method);
      await stale.receivedPromise;
      await seedAccount(contextPage, "account-b", true);
      if (returnToA) await seedAccount(contextPage, "history-user", true);
      const currentRequest = holdNextHistory();
      await contextPage.evaluate(() => { window.newHistoryRequest = refreshSaasAiCeoThreadFromBackend(); });
      await currentRequest.receivedPromise;
      stale.release();
      await contextPage.evaluate(() => window.oldHistoryRequest);
      const staleResult = await contextPage.evaluate(() => ({
        count: state.saasAiCeoThread.length, archiveCount: saasAiCeoHistoryArchive().turns.length,
        revision: state.saasAiCeoHistoryRevision, currentPending: Boolean(state.saasAiCeoThreadRefreshPromise),
        cache: localStorage.getItem(saasStorageKeys.ceoThread),
      }));
      assert.equal(staleResult.count, 0, "old response cannot merge into new-account recent history");
      assert.equal(staleResult.archiveCount, 0, "old response cannot merge into new-account archive");
      assert.equal(staleResult.revision, "", "old response cannot project a new-account revision");
      assert.equal(staleResult.currentPending, true, "old finally cannot clear the current account request");
      currentRequest.release();
      await contextPage.evaluate(() => window.newHistoryRequest);
      cases.push(`${method}_${returnToA ? "a_b_a_epoch" : "account_switch"}`);
      await contextPage.close();
    }
  }
  const stalePage = await browserContext.newPage();
  await stalePage.goto(`${base}/app.html?start=app&qa=public-saas&saasApiBase=${encodeURIComponent(base)}`);
  await seedAccount(stalePage, "account-a");
  const staleUnauthorized = holdNextHistory(401);
  await stalePage.evaluate(() => { window.pendingHistory = refreshSaasAiCeoThreadFromBackend(); });
  await staleUnauthorized.receivedPromise;
  await seedAccount(stalePage, "account-b", true);
  staleUnauthorized.release();
  await stalePage.waitForTimeout(200);
  assert.equal(counters.authProbe, 0, "an old-account 401 must not probe/refresh the new-account session");
  assert.equal(counters.authRefresh, 0, "an old-account 401 must not refresh the new-account session");
  assert.equal(await stalePage.evaluate(() => state.saasUser?.user_id), "account-b", "an old-account 401 must not log out the new account");
  cases.push("old_account_401_does_not_refresh_or_logout");
  await stalePage.close();
  for (const initialCount of [0, 10]) {
    const allTurns = turns.slice();
    turns.splice(0, turns.length, ...allTurns.slice(0, initialCount));
    const growingPage = await browserContext.newPage();
    await growingPage.goto(`${base}/app.html?start=app&qa=public-saas&saasApiBase=${encodeURIComponent(base)}`);
    await seedAccount(growingPage);
    await growingPage.evaluate(() => refreshSaasAiCeoThreadFromBackend());
    assert.equal(await growingPage.locator("[data-ceo-load-older]").count(), 0);
    turns.splice(0, turns.length, ...allTurns);
    await growingPage.evaluate(() => refreshSaasAiCeoThreadFromBackend());
    for (let i = 0; i < 20; i += 1) {
      const button = growingPage.locator("[data-ceo-load-older]");
      if (!(await button.count())) break;
      await button.click();
      await growingPage.waitForTimeout(30);
    }
    assert.equal(await growingPage.locator("#ceoChat .message.ai").count(), 76, "a previously complete short history must discover later backend pages");
    cases.push(`initial_${initialCount}_grows_to_76`);
    await growingPage.close();
  }
  const archiveIdsBeforeBurst = await page.locator("#ceoChat .message.ai").evaluateAll((elements) => elements.map((element) => element.id));
  for (let index = 77; index <= 146; index += 1) turns.push({
    ...turns[75], assistant_id: `history-local-${String(index).padStart(3, "0")}`,
    user_text: `其他设备新增问题 ${index}`, created_at: new Date(Date.UTC(2026, 8, 3, 0, index)).toISOString(),
  });
  await page.evaluate(() => refreshSaasAiCeoThreadFromBackend());
  for (const id of archiveIdsBeforeBurst) assert.equal(await page.locator(`[id="${id}"]`).count(), 1, "a disjoint latest window keeps already displayed archive messages");
  for (let i = 0; i < 30; i += 1) {
    const button = page.locator("[data-ceo-load-older]");
    if (!(await button.count())) break;
    await button.click();
    await page.waitForTimeout(35);
  }
  const afterBurstIds = await page.locator("#ceoChat .message.ai").evaluateAll((elements) => elements.map((element) => element.id));
  assert.equal(afterBurstIds.length, 146, "over 30 new messages must not leave a gap between recent and loaded archive history");
  assert.equal(new Set(afterBurstIds).size, 146, "reanchored pagination must deduplicate already loaded historical pages");
  assert.equal(afterBurstIds[0], "history-local-001");
  assert.equal(afterBurstIds[145], "history-local-146");
  assert.equal(await page.locator("[data-ceo-load-older]").count(), 0, "duplicate pages must still advance through the final cursor");
  cases.push("disjoint_latest_window_recovers_gap", "duplicate_pages_advance_without_duplicates");
  const overlappingPage = await addCasePage();
  const delayedOlder = holdNextHistory();
  await overlappingPage.locator("[data-ceo-load-older]").click();
  await delayedOlder.receivedPromise;
  for (let index = 147; index <= 216; index += 1) turns.push({
    ...turns[145], assistant_id: `history-local-${String(index).padStart(3, "0")}`,
    user_text: `并发新增问题 ${index}`, created_at: new Date(Date.UTC(2026, 8, 4, 0, index)).toISOString(),
  });
  await overlappingPage.evaluate(() => refreshSaasAiCeoThreadFromBackend());
  const reanchoredCursor = await overlappingPage.evaluate(() => saasAiCeoHistoryArchive().cursor);
  const pendingAnchor = await overlappingPage.evaluate(() => {
    const chat = document.querySelector("#ceoChat");
    chat.scrollTop = 260;
    state.saasAiCeoAutoFollow = false;
    const item = chat.querySelector(".message.ai");
    return { id: item.id, top: item.getBoundingClientRect().top };
  });
  delayedOlder.release();
  await overlappingPage.waitForFunction(() => !saasAiCeoHistoryArchive().loading);
  await overlappingPage.waitForTimeout(80);
  assert.equal(await overlappingPage.evaluate(() => saasAiCeoHistoryArchive().cursor), reanchoredCursor, "an earlier in-flight page must not overwrite a newer gap recovery cursor");
  const pendingAnchorAfter = await overlappingPage.locator(`[id="${pendingAnchor.id}"]`).evaluate((element) => element.getBoundingClientRect().top);
  assert(Math.abs(pendingAnchorAfter - pendingAnchor.top) < 4, "older response respects reading position changed while loading");
  cases.push("latest_reanchor_while_older_pending", "scroll_during_pending_page");
  await overlappingPage.close();
  const archivePage = await browserContext.newPage();
  await archivePage.setExtraHTTPHeaders({ "x-local-archive-fixture": "1" });
  await archivePage.goto(`${base}/app.html?start=app&qa=public-saas&saasApiBase=${encodeURIComponent(base)}`);
  await seedAccount(archivePage, "archive-user", true);
  const archiveResult = await archivePage.evaluate(async () => {
    state.saasToken = "archive-fixture-only";
    state.saasConnected = true;
    state.activeStore = "history-store";
    localStorage.setItem(saasStorageKeys.storeId, "history-store");
    const submitted = handleSaasCeoCommandSubmit("解释一下毛利和净利的区别。");
    await Promise.resolve(state.saasLastCeoCommandPersistPromise);
    await syncSaasAiCeoThreadWithBackend();
    await refreshSaasAiCeoThreadFromBackend();
    return { submitted: Boolean(submitted), turns: saasAiCeoThreadForBackendSync(), latest: state.saasAiCeoLatestTurn };
  });
  assert.equal(archiveProtocol.requests.length, 1, JSON.stringify({ archiveResult, counters }));
  assert.equal(archiveProtocol.requests[0].chat_archive_contract, "server_finalized_chat_archive_v1", "new chat requests must opt in to server terminal archiving");
  assert.equal(archiveResult.turns.length, 1, "server refresh and browser sync must not duplicate one completed answer");
  assert.equal(archiveResult.turns[0].assistant_id, archiveProtocol.turns[0].assistant_id);
  assert.equal(Date.parse(archiveResult.turns[0].created_at), Date.parse(archiveProtocol.turns[0].created_at));
  assert(archiveProtocol.syncBodies.every((body) => (body.turns || []).every((turn) => turn.assistant_id === archiveProtocol.turns[0].assistant_id)), "no completed placeholder ID may reach SYNC");
  assert.equal(await archivePage.locator("#ceoChat .message.ai").count(), 1);
  const frozenProtocols = await archivePage.evaluate(() => {
    const command = buildSaasCeoCommand("请新建一个全新的独立商品项目。目标商品：平板支架。", saasMerchantWorkbenchContext());
    const payload = buildSaasAiCeoChatRequestEnvelope(command, [], { suppressActiveListingContext: true, suppressConversationHistory: true, suppressSupplierFacts: true }).payload;
    const current = sanitizeSaasFrozenNewProjectRequestPayload(payload, { storeId: "history-store" });
    const legacy = { ...payload }; delete legacy.chat_archive_contract;
    const old = sanitizeSaasFrozenNewProjectRequestPayload(legacy, { storeId: "history-store" });
    return { current: current?.chat_archive_contract, legacy: old?.chat_archive_contract || "", preserved: JSON.stringify(current) === JSON.stringify(sanitizeSaasFrozenNewProjectRequestPayload(current, { storeId: "history-store" })) };
  });
  assert.deepEqual(frozenProtocols, { current: "server_finalized_chat_archive_v1", legacy: "", preserved: true });
  archiveProtocol.responseStatus = 503;
  const failedArchive = await archivePage.evaluate(async () => {
    handleSaasCeoCommandSubmit("再解释一下净利润和现金流的区别。");
    await Promise.resolve(state.saasLastCeoCommandPersistPromise);
    await syncSaasAiCeoThreadWithBackend();
    await refreshSaasAiCeoThreadFromBackend();
    return saasAiCeoThreadForBackendSync();
  });
  assert.equal(failedArchive.length, 2, "HTTP failure plus server refresh must keep exactly one failed answer");
  assert(failedArchive.every((turn) => turn.assistant_id.startsWith("ceo-server-")), "failed responses must also replace the submitted placeholder before SYNC");
  assert.equal(await archivePage.locator("#ceoChat .message.ai").count(), 2);
  archiveProtocol.responseStatus = 200;
  archiveProtocol.loseFinal = true;
  const lostFinal = await archivePage.evaluate(async () => {
    handleSaasCeoCommandSubmit("解释收到回答前关页时，毛利和净利如何核对。");
    await Promise.resolve(state.saasLastCeoCommandPersistPromise);
    const beforeSync = saasAiCeoThreadForBackendSync();
    await syncSaasAiCeoThreadWithBackend();
    await refreshSaasAiCeoThreadFromBackend();
    return { beforeSync, after: saasAiCeoThreadForBackendSync() };
  });
  assert.equal(lostFinal.beforeSync.length, 2, "an unconfirmed terminal response must not be archived by browser SYNC");
  assert.equal(lostFinal.after.length, 3, "a lost final response must recover by exact canonical identity without a ghost turn");
  assert.equal(lostFinal.after[2].assistant_id, archiveProtocol.turns[2].assistant_id);
  assert.equal(lostFinal.after[2].status, "model_answered");
  assert.equal(await archivePage.locator("#ceoChat .message.ai").count(), 3);
  const cryptoRequestCount = archiveProtocol.requests.length;
  const noCrypto = await archivePage.evaluate(async () => {
    Object.defineProperty(window.crypto, "subtle", { configurable: true, value: null });
    handleSaasCeoCommandSubmit("没有安全摘要能力时不应发送这个请求。");
    await Promise.resolve(state.saasLastCeoCommandPersistPromise);
    return { sync: saasAiCeoThreadForBackendSync(), latest: state.saasAiCeoLatestTurn };
  });
  assert.equal(archiveProtocol.requests.length, cryptoRequestCount, "missing WebCrypto must stop before sending the new-protocol chat");
  assert.equal(noCrypto.sync.length, 3, "missing WebCrypto must not SYNC an unconfirmed placeholder");
  assert.equal(noCrypto.latest.archive_pending, true);
  const archiveScreenshot = path.join(os.tmpdir(), `jiejing-ai-ceo-server-archive-${Date.now()}.png`);
  await archivePage.screenshot({ path: archiveScreenshot });
  cases.push("server_archive_canonical_identity", "server_archive_no_sync_duplicate", "frozen_request_archive_protocol_compatibility");
  cases.push("failed_response_archive_identity");
  cases.push("lost_final_recovers_by_request_identity");
  cases.push("missing_webcrypto_fails_before_request_or_sync");
  await archivePage.close();
  assert.deepEqual(errors, []);
  const screenshot = path.join(os.tmpdir(), `jiejing-ai-ceo-history-${Date.now()}.png`);
  await page.locator("#ceoChat").evaluate((chat) => { chat.scrollTop = 0; });
  await page.screenshot({ path: screenshot });
  console.log(JSON.stringify({ status: "pass", visible_turns: 146, cases, layout_cases: layoutCases, counters, screenshot_path: screenshot, archive_screenshot_path: archiveScreenshot }));
}
main().catch((error) => { console.error(error); process.exitCode = 1; }).finally(async () => {
  if (browser) await browser.close();
  if (server) await new Promise((resolve) => server.close(resolve));
});
