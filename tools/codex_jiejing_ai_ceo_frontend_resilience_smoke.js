#!/usr/bin/env node
/* Browser regression for AI CEO continuation, brand-new project transitions,
   terminal session expiry, and market-report project identity hydration. The
   fixture is strictly local and never calls a model, FAL, eBay, payment,
   refund, OAuth, or platform write. */

const fs = require("fs");
const http = require("http");
const path = require("path");
const { chromium } = require("../output/codex-playwright-deps/node_modules/playwright-core");

const root = path.resolve(__dirname, "..");
const browserChannel = process.env.JIEJING_PLAYWRIGHT_CHANNEL || "chrome";
let authMode = "valid";
let chatResponseProjectId = "listing-project-resilience";
let ordinaryProductVisionFactPacket = null;
let newProjectChatControl = null;
const counters = { me: 0, refresh: 0, chat: 0, history: 0 };
let lastChatBody = null;
const chatBodies = [];
const optionalRequestControls = new Map();

function json(res, status, body) {
  res.writeHead(status, {
    "content-type": "application/json; charset=utf-8",
    "cache-control": "no-store",
  });
  res.end(JSON.stringify(body));
}

function testableAppSource() {
  const source = fs.readFileSync(path.join(root, "app.js"), "utf8");
  const boot = /exposeLocalJiejingTestHooks\(\);\r?\ninit\(\);\r?\nrunLocalJiejingQaScenarioFromUrl\(\);\s*$/;
  if (!boot.test(source)) throw new Error("app boot marker changed");
  return source.replace(boot, "exposeLocalJiejingTestHooks();\n");
}

async function readBody(req) {
  const chunks = [];
  for await (const chunk of req) chunks.push(chunk);
  return Buffer.concat(chunks).toString("utf8");
}

async function optionalFetchLifecycleSmoke(browser, base) {
  const page = await browser.newPage();
  const externalRequests = [];
  const pageErrors = [];
  const unhandledRejections = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  await page.exposeFunction("reportOptionalUnhandledRejection", (reason) => unhandledRejections.push(reason));
  await page.addInitScript(() => {
    window.addEventListener("unhandledrejection", (event) => window.reportOptionalUnhandledRejection(String(event.reason?.message || event.reason)));
  });
  await page.route("**/*", (route) => {
    if (new URL(route.request().url()).origin === base) return route.continue();
    externalRequests.push(route.request().url());
    return route.abort();
  });
  try {
    await page.clock.install({ time: new Date("2026-09-08T00:00:00Z") });
    await page.clock.pauseAt(new Date("2026-09-08T00:00:01Z"));
    await page.goto(`${base}/app.html?start=app&qa=public-saas&saasApiBase=${encodeURIComponent(base)}`, { waitUntil: "load" });
    const success = await page.evaluate(async (apiBase) => {
      state.saasApiBase = apiBase;
      state.saasOptionalSoftTimeouts = [];
      window.optionalFallbackCalls = 0;
      const result = await optionalSaasFetchFast("/optional-lifecycle/success", () => {
        window.optionalFallbackCalls += 1;
        return { status: "unavailable" };
      }, 5000);
      document.getElementById("ceoChat").textContent = result.status;
      return result;
    }, base);
    if (success.status !== "fixture_ready") throw new Error("optional success did not consume the real local HTTP response");
    await page.clock.runFor(5001);
    const afterSuccessDeadline = await page.evaluate(() => ({
      fallbacks: window.optionalFallbackCalls,
      timeouts: state.saasOptionalSoftTimeouts,
      displayed: document.getElementById("ceoChat").textContent,
    }));
    if (afterSuccessDeadline.fallbacks !== 0 || afterSuccessDeadline.timeouts.length || afterSuccessDeadline.displayed !== "fixture_ready") {
      throw new Error(`completed optional HTTP success must not later record a timeout or invoke fallback: ${JSON.stringify(afterSuccessDeadline)}`);
    }
    const failed = await page.evaluate(async () => {
      state.saasOptionalSoftTimeouts = [];
      window.optionalFallbackCalls = 0;
      return optionalSaasFetchFast("/optional-lifecycle/failure", (error) => {
        window.optionalFallbackCalls += 1;
        return { status: "unavailable", httpStatus: error.status };
      }, 5000);
    });
    await page.clock.runFor(5001);
    const afterFailureDeadline = await page.evaluate(() => ({
      fallbacks: window.optionalFallbackCalls,
      timeouts: state.saasOptionalSoftTimeouts,
    }));
    if (failed.httpStatus !== 503 || afterFailureDeadline.fallbacks !== 1 || afterFailureDeadline.timeouts.length) {
      throw new Error(`completed optional HTTP failure must use fallback once without a false timeout: ${JSON.stringify({ failed, afterFailureDeadline })}`);
    }

    let markReceived;
    let releaseResponse;
    const received = new Promise((resolve) => { markReceived = resolve; });
    const release = new Promise((resolve) => { releaseResponse = resolve; });
    optionalRequestControls.set("/optional-lifecycle/late-failure", { markReceived, release });
    await page.evaluate(() => {
      state.saasOptionalSoftTimeouts = [];
      window.optionalFallbackCalls = 0;
      window.optionalRequestResult = optionalSaasFetchFast("/optional-lifecycle/late-failure", (error) => {
        window.optionalFallbackCalls += 1;
        return { status: "unavailable", reason: error.message };
      }, 5000);
    });
    await received;
    await page.clock.runFor(5000);
    const timedOut = await page.evaluate(async () => ({
      result: await window.optionalRequestResult,
      fallbacks: window.optionalFallbackCalls,
      timeouts: state.saasOptionalSoftTimeouts,
    }));
    if (timedOut.result.reason !== "timed out after 5000ms" || timedOut.fallbacks !== 1 || timedOut.timeouts.length !== 1 || timedOut.timeouts[0].path !== "/optional-lifecycle/late-failure") {
      throw new Error(`a real optional HTTP timeout must produce exactly one diagnostic and fallback: ${JSON.stringify(timedOut)}`);
    }
    const lateFailureLogged = page.waitForEvent("console", {
      predicate: (message) => message.type() === "warning" && message.text().includes("[JIEJING optional API skipped] /optional-lifecycle/late-failure"),
      timeout: 10000,
    });
    releaseResponse();
    await lateFailureLogged;
    await page.clock.runFor(5001);
    const afterLateFailure = await page.evaluate(async () => ({
      result: await window.optionalRequestResult,
      fallbacks: window.optionalFallbackCalls,
      timeouts: state.saasOptionalSoftTimeouts,
    }));
    if (afterLateFailure.fallbacks !== 1 || afterLateFailure.timeouts.length !== 1 || afterLateFailure.result.reason !== "timed out after 5000ms") {
      throw new Error(`a late optional HTTP failure must not invoke fallback a second time: ${JSON.stringify(afterLateFailure)}`);
    }

    let markLateSuccessReceived;
    let releaseLateSuccess;
    const lateSuccessReceived = new Promise((resolve) => { markLateSuccessReceived = resolve; });
    const lateSuccessRelease = new Promise((resolve) => { releaseLateSuccess = resolve; });
    optionalRequestControls.set("/optional-lifecycle/late-success", { markReceived: markLateSuccessReceived, release: lateSuccessRelease });
    await page.evaluate(() => {
      state.saasOptionalSoftTimeouts = [];
      window.optionalObjectFallback = { status: "unavailable", marker: "object_fallback" };
      window.optionalRequestResult = optionalSaasFetchFast("/optional-lifecycle/late-success", window.optionalObjectFallback, 5000);
    });
    await lateSuccessReceived;
    await page.clock.runFor(5000);
    const objectFallback = await page.evaluate(async () => (await window.optionalRequestResult) === window.optionalObjectFallback);
    if (!objectFallback) throw new Error("a real optional timeout must preserve the caller's object fallback");
    const lateSuccessResponse = page.waitForResponse((response) => response.url() === `${base}/optional-lifecycle/late-success` && response.status() === 200);
    releaseLateSuccess();
    await (await lateSuccessResponse).finished();
    await page.clock.runFor(5001);
    const afterLateSuccess = await page.evaluate(async () => ({
      result: await window.optionalRequestResult,
      sameObject: (await window.optionalRequestResult) === window.optionalObjectFallback,
      timeouts: state.saasOptionalSoftTimeouts,
    }));
    if (!afterLateSuccess.sameObject || afterLateSuccess.result.marker !== "object_fallback" || afterLateSuccess.timeouts.length !== 1) {
      throw new Error(`a late optional HTTP success must not replace the settled timeout or repeat diagnostics: ${JSON.stringify(afterLateSuccess)}`);
    }

    const permission = await page.evaluate(async () => {
      window.__JIEJING_FORCE_PUBLIC_MVP__ = true;
      localStorage.setItem(saasStorageKeys.sessionHint, "1");
      state.saasSessionExpiryHandled = false;
      state.saasOptionalSoftTimeouts = [];
      window.optionalFallbackCalls = 0;
      const result = await optionalSaasFetchFast("/permission-check", (error) => {
        window.optionalFallbackCalls += 1;
        return { status: "unavailable", httpStatus: error.status };
      }, 5000);
      return { result, sessionHintPresent: hasSaasPersistentSessionHint(), handled: state.saasSessionExpiryHandled };
    });
    await page.clock.runFor(5001);
    const permissionAfterDeadline = await page.evaluate(() => ({ fallbacks: window.optionalFallbackCalls, timeouts: state.saasOptionalSoftTimeouts }));
    if (permission.result.httpStatus !== 403 || !permission.sessionHintPresent || permission.handled || permissionAfterDeadline.fallbacks !== 1 || permissionAfterDeadline.timeouts.length) {
      throw new Error(`optional permission failure must remain a fallback, not a logout or soft timeout: ${JSON.stringify({ permission, permissionAfterDeadline })}`);
    }

    const expired = await page.evaluate(async () => {
      state.saasOptionalSoftTimeouts = [];
      window.optionalFallbackCalls = 0;
      try {
        await optionalSaasFetchFast("/optional-lifecycle/expired", () => {
          window.optionalFallbackCalls += 1;
          return { status: "unavailable" };
        }, 5000, { saasRequestRetriedAfterRefresh: true, saasDeferUnauthorizedTermination: true });
        return { rejected: false };
      } catch (error) {
        return { rejected: true, status: error.status, code: error.code, unrecoverable: isSaasUnrecoverableSessionError(error) };
      }
    });
    await page.clock.runFor(5001);
    const expiredAfterDeadline = await page.evaluate(() => ({ fallbacks: window.optionalFallbackCalls, timeouts: state.saasOptionalSoftTimeouts }));
    if (!expired.rejected || expired.status !== 401 || expired.code !== "saas_session_expired" || !expired.unrecoverable || expiredAfterDeadline.fallbacks !== 0 || expiredAfterDeadline.timeouts.length) {
      throw new Error(`optional unrecoverable session failure must throw without fallback or a later timeout: ${JSON.stringify({ expired, expiredAfterDeadline })}`);
    }
    if (externalRequests.length || pageErrors.length || unhandledRejections.length) {
      throw new Error(`optional lifecycle fixture must stay local and runtime-error free: ${JSON.stringify({ externalRequests, pageErrors, unhandledRejections })}`);
    }
  } finally {
    await page.close();
  }
}

async function main() {
  const appSource = testableAppSource();
  const server = http.createServer(async (req, res) => {
    const url = new URL(req.url || "/", "http://127.0.0.1");
    if (url.pathname === "/app.html") {
      res.writeHead(200, { "content-type": "text/html; charset=utf-8", "cache-control": "no-store" });
      res.end(`<!doctype html><html><head><meta charset="utf-8"></head><body data-view="cockpit">
        <section id="view-cockpit" class="view is-active">
          <div class="cockpit-chat-panel"><div id="ceoChat"></div><div id="saasCeoRouteTaskSlot"></div>
            <form id="ceoForm"><input id="ceoInput"><button type="submit">send</button></form>
          </div>
        </section>
        <section id="view-product" class="view"></section>
        <script src="/app-test.js"></script></body></html>`);
      return;
    }
    if (url.pathname === "/app-test.js") {
      res.writeHead(200, { "content-type": "text/javascript; charset=utf-8", "cache-control": "no-store" });
      res.end(appSource);
      return;
    }
    if (["success", "failure", "late-failure", "late-success", "expired"].some((name) => url.pathname === `/optional-lifecycle/${name}`)) {
      const control = optionalRequestControls.get(url.pathname);
      if (control) {
        control.markReceived();
        await control.release;
      }
      if (url.pathname.endsWith("success")) json(res, 200, { status: "fixture_ready", secret_exposed: false });
      else if (url.pathname.endsWith("expired")) json(res, 401, { error: "session expired", secret_exposed: false });
      else json(res, 503, { error: "optional_fixture_unavailable", secret_exposed: false });
      return;
    }
    if (url.pathname === "/me" && req.method === "GET") {
      counters.me += 1;
      if (authMode === "valid") {
        json(res, 200, {
          user: { user_id: "resilience-user", email: "merchant@local.invalid" },
          company: { company_id: "resilience-company" },
          identity: { user_id: "resilience-user", email: "merchant@local.invalid" },
          secret_exposed: false,
        });
      } else {
        json(res, 401, { error: "session expired", secret_exposed: false });
      }
      return;
    }
    if (url.pathname === "/auth/refresh" && req.method === "POST") {
      counters.refresh += 1;
      json(res, 401, { error: "session_refresh_invalid", secret_exposed: false });
      return;
    }
    if (url.pathname === "/ai-ceo/chat-history" && req.method === "GET") {
      counters.history += 1;
      json(res, 401, { error: "session expired", secret_exposed: false });
      return;
    }
    if (url.pathname === "/permission-check" && req.method === "GET") {
      json(res, 403, { error: "permission denied", secret_exposed: false });
      return;
    }
    if (/^\/stores\/[^/]+\/merchant-ceo\/chat$/.test(url.pathname) && req.method === "POST") {
      counters.chat += 1;
      const body = JSON.parse((await readBody(req)) || "{}");
      lastChatBody = body;
      chatBodies.push(JSON.parse(JSON.stringify(body)));
      const explicitNewProjectRequest = /新建一个全新的独立商品项目/.test(String(body.message || ""));
      if (explicitNewProjectRequest && newProjectChatControl) {
        const control = newProjectChatControl;
        const identity = {
          key: control.projectId || "listing-project-tablet-stand",
          source_report_id: control.reportId || "report-tablet-stand",
          candidate_id: control.candidateId || "candidate-tablet-stand",
        };
        control.markRequestReceived();
        await control.waitForResponseRelease;
        control.requestCount = Number(control.requestCount || 0) + 1;
        if (control.responseMode === "in_progress_once" && control.requestCount === 1) {
          json(res, 202, {
            ai_ceo_chat_request: {
              status: "in_progress",
              request_task_id: "task-ai-ceo-idempotency-local",
              retry_after_ms: 10,
            },
            usage_consumed: false,
            listing_created: false,
            real_platform_writes_enabled: false,
            secret_exposed: false,
          });
          return;
        }
        if (control.responseMode === "idempotency_conflict") {
          json(res, 409, {
            error: "同一幂等标识不能用于不同的 AI CEO 请求。",
            error_code: "ai_ceo_idempotency_payload_conflict",
            request_task_id: "task-ai-ceo-idempotency-conflict-local",
            real_platform_writes_enabled: false,
            secret_exposed: false,
          });
          return;
        }
        if (control.responseMode === "failure") {
          json(res, 503, {
            _http_status: 503,
            ai_ceo_chat: {
              status: "model_call_failed",
              answer: "新商品项目暂时没有建立成功，请稍后重试。",
              route: "ebay_workflow",
              route_label: "AI CEO 市场调研",
              work_records: [],
              source_records: [],
              confirmation_items: [],
            },
            usage_consumed: false,
            listing_created: false,
            real_platform_writes_enabled: false,
            secret_exposed: false,
          });
          return;
        }
        json(res, 201, {
          ai_ceo_chat: {
            status: "model_answered",
            answer: "已为平板电脑支架建立全新的独立商品项目。",
            route: "ebay_workflow",
            route_label: "AI CEO 市场调研",
            work_records: [],
            source_records: [],
            confirmation_items: [],
          },
          ai_ceo_market_report: {
            report_id: identity.source_report_id,
            report_type: "ai_ceo.market_research",
            store_id: "store-resilience",
            status: "saved",
            created_at: new Date().toISOString(),
            listing_project_identity: identity,
            report: {
              answer: "已为平板电脑支架建立全新的独立商品项目。",
              merchant_question: body.message || "",
              product: "平板电脑支架",
              product_candidates: [{
                candidate_id: identity.candidate_id,
                name: "平板电脑支架",
                selected: true,
              }],
              selected_product_candidate: {
                candidate_id: identity.candidate_id,
                name: "平板电脑支架",
                selected: true,
              },
              listing_project_identity: identity,
              listing_handoff: {
                ready_for_listing_draft: true,
                requires_human_review_before_publish: true,
                triggers_real_platform_write: false,
                real_platform_writes_enabled: false,
              },
              source_records: [],
              source_record_count: 0,
              secret_exposed: false,
            },
            secret_exposed: false,
          },
          ...(control.productVisionFactPacket ? { product_vision_fact_packet: control.productVisionFactPacket } : {}),
          usage_consumed: true,
          listing_created: false,
          real_platform_writes_enabled: false,
          secret_exposed: false,
        });
        return;
      }
      const projectMismatch = Boolean(chatResponseProjectId) && chatResponseProjectId !== "listing-project-resilience";
      json(res, 200, {
        ai_ceo_chat: {
          status: "answered",
          answer: "已继续当前商品项目的下一轮选品调研。",
          route: "ebay_workflow",
          route_label: "AI CEO 选品调研",
          listing_project_identity: chatResponseProjectId ? {
            key: chatResponseProjectId,
            source_report_id: projectMismatch ? "report-foreign" : "report-resilience",
            candidate_id: projectMismatch ? "candidate-foreign" : "candidate-resilience",
          } : null,
          work_records: [],
          source_records: [],
          confirmation_items: [],
        },
        ai_ceo_market_report: projectMismatch ? {
          report_id: "report-foreign",
          report_type: "ai_ceo.market_research",
          listing_project_identity: {
            key: chatResponseProjectId,
            source_report_id: "report-foreign",
            candidate_id: "candidate-foreign",
          },
        } : null,
        ...(ordinaryProductVisionFactPacket ? { product_vision_fact_packet: ordinaryProductVisionFactPacket } : {}),
        request_message: body.message || "",
        secret_exposed: false,
      });
      return;
    }
    json(res, 404, { error: "fixture_not_found", secret_exposed: false });
  });

  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });
  const address = server.address();
  const base = `http://127.0.0.1:${address.port}`;
  let browser;
  try {
    browser = await chromium.launch({ headless: true, channel: browserChannel });
    await optionalFetchLifecycleSmoke(browser, base);
    const page = await browser.newPage();
    await page.goto(`${base}/app.html?start=app&qa=public-saas&project=listing-project-resilience&saasApiBase=${encodeURIComponent(base)}`, { waitUntil: "load" });

    const identityResult = await page.evaluate(() => {
      const identity = {
        key: "listing-project-resilience",
        source_report_id: "report-resilience",
        candidate_id: "candidate-resilience",
      };
      const turn = saasAiCeoMarketTurnFromReport({
        report_id: "report-resilience",
        report_type: "ai_ceo.market_research",
        status: "saved",
        created_at: new Date().toISOString(),
        report: {
          answer: "结构化市场调研已保存。",
          merchant_question: "帮我找一个轻小非电商品",
          listing_project_identity: identity,
        },
      });
      state.saasListingComposerDraft = {
        product: "Stale cached product",
        title: "Stale cached product",
        selected_product_candidate: { id: "candidate-stale", name: "Stale cached product" },
        listing_project_identity: {
          key: "listing-project-stale-cached-draft",
          source_report_id: "report-stale",
          candidate_id: "candidate-stale",
        },
      };
      const restoredFromUnrelatedReports = restoreSaasListingComposerDraftFromBackendReports({ reports: [] });
      state.aiCeoTaskContextProjectId = "listing-project-resilience";
      const foreignBound = bindSaasAiCeoTaskContextFromTurn({
        user_text: "另一商品项目",
        assistant_text: "另一项目结果",
        status: "answered",
        listing_project_identity: {
          key: "listing-project-foreign",
          source_report_id: "report-foreign",
          candidate_id: "candidate-foreign",
        },
      }, { render: false });
      return {
        identity: turn?.listing_project_identity || null,
        currentProjectId: saasCurrentMerchantProjectId(),
        restoredDraftProjectId: saasCurrentListingProjectIdentity(restoredFromUnrelatedReports)?.key || "",
        foreignBound,
        contextProjectId: state.aiCeoTaskContextProjectId,
      };
    });
    if (identityResult?.identity?.key !== "listing-project-resilience") {
      throw new Error(`report reload lost listing project identity: ${JSON.stringify(identityResult)}`);
    }
    if (identityResult.currentProjectId !== "listing-project-resilience") {
      throw new Error(`explicit project route must outrank a stale cached draft: ${JSON.stringify(identityResult)}`);
    }
    if (identityResult.restoredDraftProjectId) {
      throw new Error(`explicit route must not restore an unrelated cached draft: ${JSON.stringify(identityResult)}`);
    }
    if (identityResult.foreignBound || identityResult.contextProjectId !== "listing-project-resilience") {
      throw new Error(`history from another project must not replace the explicit route project: ${JSON.stringify(identityResult)}`);
    }

    const continuation = await page.evaluate(async () => {
      window.__JIEJING_FORCE_PUBLIC_MVP__ = true;
      localStorage.setItem(saasStorageKeys.sessionHint, "1");
      localStorage.setItem(saasStorageKeys.storeId, "store-resilience");
      state.saasConnected = true;
      state.saasProtectedStateFromCache = false;
      state.saasIdentity = { user_id: "resilience-user", email: "merchant@local.invalid" };
      state.saasUser = { user_id: "resilience-user", email: "merchant@local.invalid" };
      state.saasCompany = { company_id: "resilience-company" };
      state.saasStores = [{
        store_id: "store-resilience",
        store_name: "Resilience Store",
        platform: "ebay",
        marketplace: "EBAY_US",
        status: "authorized",
      }];
      state.activeStore = "store-resilience";
      state.saasListingComposerDraft = null;
      state.saasReports = [{
        report_id: "report-resilience",
        report_type: "ai_ceo.market_research",
        store_id: "store-resilience",
        status: "saved",
        created_at: new Date().toISOString(),
        listing_project_identity: {
          key: "listing-project-resilience",
          source_report_id: "report-resilience",
          candidate_id: "candidate-resilience",
        },
        report: {
          answer: "结构化市场调研已保存。",
          product_candidates: [{
            candidate_id: "candidate-resilience",
            name: "轻小非电测试商品",
            selected: true,
          }],
          selected_product_candidate: {
            candidate_id: "candidate-resilience",
            name: "轻小非电测试商品",
          },
          listing_project_identity: {
            key: "listing-project-resilience",
            source_report_id: "report-resilience",
            candidate_id: "candidate-resilience",
          },
        },
      }];
      activeListingDraft = () => ({ id: "foreign-active-listing", titleCn: "另一商品的旧 Listing" });
      const unrelatedProject = saasCurrentListingProjectIdentity(null);
      state.saasMediaAssetJobs = [{
        media_job_id: "media-job-foreign",
        live_provider_called: true,
        asset_manifest: [{ url_or_file_path: "https://i.ebayimg.com/images/g/test/s-l1600.jpg" }],
        job_spec: {
          inputs: {
            product_facts: {
              listing_project_key: unrelatedProject.key,
            },
          },
        },
      }];
      state.saasConfirmations = [{
        confirmation_id: "confirmation-foreign-draft",
        action_type: "save_ebay_listing_draft",
        item: {
          listing_project_identity: { key: unrelatedProject.key },
          publish_payload: { listing: { sku: "FOREIGN-SKU-01" } },
        },
      }];
      state.saasExecutionResults = [{
        execution_id: "execution-foreign-draft",
        confirmation_id: "confirmation-foreign-draft",
        action_type: "save_ebay_listing_draft",
        result: {
          action_type: "save_ebay_listing_draft",
          status: "saved_to_ebay_draft",
          platform_result: {
            offer_id: "foreign-offer-01",
            offer_status: "UNPUBLISHED",
            sku: "FOREIGN-SKU-01",
            writes_to_ebay: true,
            public_listing_created: false,
            published_to_ebay: false,
          },
          secret_exposed: false,
        },
      }];
      state.saasAiCeoThread = [];
      state.saasLastCeoCommand = buildSaasCeoCommand(
        "帮我调研轻小、不带电、适合 eBay 美国站的商品，并给出候选。",
        saasMerchantWorkbenchContext(),
      );
      scheduleSaasAiCeoThreadBackendSync = () => false;
      setView = () => true;
      bindCeoForm(document);
      const button = document.createElement("button");
      button.dataset.globalFlowView = "cockpit";
      button.dataset.globalFlowKey = "research";
      handleGlobalFlowNavigation(button);
      handleGlobalFlowNavigation(button);
      await Promise.resolve(state.saasLastCeoCommandPersistPromise);
      return {
        input: document.querySelector("#ceoInput")?.value || "",
        lastText: state.saasLastCeoCommand?.text || "",
        status: state.saasAiCeoLatestTurn?.status || "",
      };
    });
    if (counters.chat !== 1) throw new Error(`research continuation must submit exactly one chat POST; counters=${JSON.stringify(counters)}`);
    if (lastChatBody?.active_listing_context?.listing_project_identity?.key !== "listing-project-resilience") {
      throw new Error(`report-only continuation must preserve the explicit route project: ${JSON.stringify(lastChatBody)}`);
    }
    if (lastChatBody?.active_listing_context?.media?.asset_manifest_count !== 0) {
      throw new Error(`report-only continuation must not attach another project's media: ${JSON.stringify(lastChatBody)}`);
    }
    if (Object.keys(lastChatBody?.active_listing_context?.ebay_draft || {}).length) {
      throw new Error(`report-only continuation must not attach another project's eBay draft: ${JSON.stringify(lastChatBody)}`);
    }
    if (
      !/继续|下一轮/.test(continuation.lastText) ||
      !/不要更换商品|不新增候选/.test(continuation.lastText) ||
      /补充新的可售候选/.test(continuation.lastText)
    ) {
      throw new Error(`research continuation prompt is not explicit: ${JSON.stringify(continuation)}`);
    }

    chatResponseProjectId = "listing-project-foreign-response";
    const responseProjectGuard = await page.evaluate(async () => {
      const payload = await requestSaasAiCeoChat(state.saasLastCeoCommand, {}, [], { enforceProjectIdentity: true });
      return {
        status: payload?.ai_ceo_chat?.status || "",
        projectId: payload?.ai_ceo_chat?.listing_project_identity?.key || "",
        marketReportPresent: Boolean(payload?.ai_ceo_market_report),
        guardStatus: payload?.project_context_guard?.status || "",
      };
    });
    if (
      responseProjectGuard.status !== "project_context_mismatch" ||
      responseProjectGuard.projectId !== "listing-project-resilience" ||
      responseProjectGuard.marketReportPresent ||
      responseProjectGuard.guardStatus !== "blocked"
    ) {
      throw new Error(`mismatched backend project identity must be quarantined: ${JSON.stringify(responseProjectGuard)}`);
    }
    chatResponseProjectId = "";
    const ordinaryChatWithinProject = await page.evaluate(async () => {
      const command = {
        ...state.saasLastCeoCommand,
        text: "今天上海天气怎么样？",
        intent: "general_chat",
        route: "general_chat",
        route_label: "直接回答",
      };
      const payload = await requestSaasAiCeoChat(command, {}, []);
      return {
        status: payload?.ai_ceo_chat?.status || "",
        guardPresent: Boolean(payload?.project_context_guard),
      };
    });
    if (ordinaryChatWithinProject.status !== "answered" || ordinaryChatWithinProject.guardPresent) {
      throw new Error(`ordinary chat inside a project route must not require a listing identity: ${JSON.stringify(ordinaryChatWithinProject)}`);
    }
    chatResponseProjectId = "listing-project-resilience";

    let markNewProjectRequestReceived;
    let releaseNewProjectResponse;
    const newProjectRequestReceived = new Promise((resolve) => {
      markNewProjectRequestReceived = resolve;
    });
    const waitForNewProjectResponseRelease = new Promise((resolve) => {
      releaseNewProjectResponse = resolve;
    });
    newProjectChatControl = {
      markRequestReceived: markNewProjectRequestReceived,
      waitForResponseRelease: waitForNewProjectResponseRelease,
    };
    await page.evaluate(() => {
      const oldIdentity = {
        key: "listing-project-resilience",
        source_report_id: "report-resilience",
        candidate_id: "candidate-resilience",
      };
      window.history.replaceState(
        window.history.state,
        "",
        `${window.location.pathname}?start=app&view=cockpit&project=${oldIdentity.key}`,
      );
      state.view = "cockpit";
      state.saasListingMode = "single";
      state.saasListingComposerDraft = {
        product: "旧商品项目",
        title: "旧商品项目",
        selected_product_candidate: { candidate_id: oldIdentity.candidate_id, name: "旧商品项目" },
        listing_project_identity: oldIdentity,
        merchant_product_fact_packet: {
          product_name: "旧商品项目",
          source_confirmed_facts: {},
          merchant_confirmed_facts: {},
          derived_listing_suggestions: {},
          unknown_facts: [],
        },
      };
      state.saasMerchantProjectStatus = {
        snapshot_version: "merchant_project_status_v1",
        project: { project_id: oldIdentity.key, listing_project_identity: oldIdentity },
      };
      state.aiCeoTaskContextMode = "active_product_task";
      state.aiCeoTaskContextProjectId = oldIdentity.key;
      state.saasAiCeoLatestTurn = null;
      state.saasAiCeoThread = [{
        user_text: "继续旧商品项目",
        assistant_text: "旧商品项目仍在处理中。",
        assistant_id: "old-project-turn",
        status: "model_answered",
        store_id: "store-resilience",
        route: "ebay_workflow",
        listing_project_identity: oldIdentity,
        pending: false,
        created_at: new Date(Date.now() - 60_000).toISOString(),
      }];
      handleSaasCeoCommandSubmit(
        "请新建一个全新的独立商品项目，不复用任何历史项目。目标商品：平板电脑支架。请完成 eBay US 市场调研。",
      );
    });
    await newProjectRequestReceived;
    const chatCountBeforePendingSupplement = counters.chat;
    await page.evaluate(() => {
      handleSaasCeoCommandSubmit("补充：平板电脑支架优先考虑轻量便携。");
    });
    await page.waitForTimeout(50);
    if (counters.chat !== chatCountBeforePendingSupplement) {
      throw new Error(`supplemental text during a pending new-project request must not be sent into the previous project; counters=${JSON.stringify(counters)}`);
    }
    const blockedFormState = await page.evaluate(() => {
      state.saasAiCeoPendingAttachments = [{ asset_id: "asset-pending-duplicate", file_name: "pending.png" }];
      const input = document.querySelector("#ceoInput");
      input.value = "请新建一个全新的独立商品项目。目标商品：另一个支架。";
      document.querySelector("#ceoForm").dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
      return {
        input: input.value,
        sourceAssetIds: saasAiCeoPendingSourceAssetIds(),
        pendingCommandId: state.saasPendingNewListingProjectRequest?.commandId || "",
      };
    });
    await page.waitForTimeout(50);
    if (
      counters.chat !== chatCountBeforePendingSupplement ||
      !/另一个支架/.test(blockedFormState.input) ||
      JSON.stringify(blockedFormState.sourceAssetIds) !== JSON.stringify(["asset-pending-duplicate"]) ||
      !blockedFormState.pendingCommandId
    ) {
      throw new Error(`a repeated explicit new-project submit must be idempotently blocked without clearing form data: ${JSON.stringify({
        counters,
        blockedFormState,
      })}`);
    }
    await page.evaluate(() => {
      state.saasAiCeoPendingAttachments = [];
      document.querySelector("#ceoInput").value = "";
    });
    const newProjectBeforeResponse = await page.evaluate(() => ({
      routeProjectId: new URLSearchParams(window.location.search).get("project") || "",
      currentProjectId: saasCurrentMerchantProjectId(),
      taskContextProjectId: state.aiCeoTaskContextProjectId || "",
      draftProjectId: state.saasListingComposerDraft?.listing_project_identity?.key || "",
      draftTitle: state.saasListingComposerDraft?.title || "",
      pendingPhase: state.saasPendingNewListingProjectRequest?.phase || "",
    }));
    const newProjectRequestIdentity = lastChatBody?.active_listing_context?.listing_project_identity || null;
    const newProjectConversationHistory = lastChatBody?.conversation_history || [];
    await page.evaluate(() => {
      const crossDeviceTurn = {
        user_text: "另一设备上的普通咨询",
        assistant_text: "另一设备已同步一条较新的普通回复。",
        assistant_id: "cross-device-newer-turn",
        status: "model_answered",
        store_id: "store-resilience",
        route: "general_chat",
        pending: false,
        created_at: new Date(Date.now() + 1_000).toISOString(),
      };
      state.saasAiCeoLatestTurn = crossDeviceTurn;
      state.saasAiCeoThread = [...state.saasAiCeoThread, crossDeviceTurn];
    });
    releaseNewProjectResponse();
    await page.evaluate(async () => {
      await Promise.resolve(state.saasLastCeoCommandPersistPromise);
    });
    const newProjectAfterResponse = await page.evaluate(() => ({
      routeProjectId: new URLSearchParams(window.location.search).get("project") || "",
      currentProjectId: saasCurrentMerchantProjectId(),
      taskContextProjectId: state.aiCeoTaskContextProjectId || "",
      responseProjectId: state.saasAiCeoThread.find((turn) => turn.market_report_id === "report-tablet-stand")?.listing_project_identity?.key || "",
      reportId: state.saasAiCeoThread.find((turn) => turn.market_report_id === "report-tablet-stand")?.market_report_id || "",
      latestAssistantId: state.saasAiCeoLatestTurn?.assistant_id || "",
      pendingRequest: state.saasPendingNewListingProjectRequest || null,
    }));
    newProjectChatControl = null;
    if (
      newProjectBeforeResponse.routeProjectId ||
      newProjectBeforeResponse.currentProjectId ||
      newProjectBeforeResponse.taskContextProjectId ||
      newProjectRequestIdentity ||
      newProjectConversationHistory.length
    ) {
      throw new Error(`a brand-new project request must detach the previous project before POST: ${JSON.stringify({
        beforeResponse: newProjectBeforeResponse,
        requestIdentity: newProjectRequestIdentity,
        conversationHistory: newProjectConversationHistory,
        afterResponse: newProjectAfterResponse,
      })}`);
    }
    if (
      newProjectBeforeResponse.draftProjectId !== "listing-project-resilience" ||
      newProjectBeforeResponse.draftTitle !== "旧商品项目" ||
      newProjectBeforeResponse.pendingPhase !== "pending"
    ) {
      throw new Error(`a pending new-project request must preserve the previous local draft until backend identity exists: ${JSON.stringify(newProjectBeforeResponse)}`);
    }
    if (
      newProjectAfterResponse.routeProjectId !== "listing-project-tablet-stand" ||
      newProjectAfterResponse.currentProjectId !== "listing-project-tablet-stand" ||
      newProjectAfterResponse.taskContextProjectId !== "listing-project-tablet-stand" ||
      newProjectAfterResponse.responseProjectId !== "listing-project-tablet-stand" ||
      newProjectAfterResponse.reportId !== "report-tablet-stand" ||
      newProjectAfterResponse.latestAssistantId !== "cross-device-newer-turn" ||
      newProjectAfterResponse.pendingRequest
    ) {
      throw new Error(`a successful brand-new project report must commit the backend identity: ${JSON.stringify(newProjectAfterResponse)}`);
    }

    const newProjectIntentCases = await page.evaluate(() => ({
      direct: saasExplicitNewListingProjectRequest("请新建一个全新的独立商品项目。"),
      namedProduct: saasExplicitNewListingProjectRequest("请新建一个平板电脑支架的独立项目。"),
      clauseOverride: saasExplicitNewListingProjectRequest("不要重复新建旧项目，请新建一个全新商品项目。"),
      naturalCommand: saasExplicitNewListingProjectRequest("请新建一个商品项目，目标是平板电脑支架，并且独立于旧项目。"),
      politeRequest: saasExplicitNewListingProjectRequest("是否可以帮我新建一个全新的商品项目？"),
      politeModal: saasExplicitNewListingProjectRequest("可以帮我新建商品项目吗？"),
      canHelp: saasExplicitNewListingProjectRequest("能帮我新建一个全新商品项目吗？"),
      courteous: saasExplicitNewListingProjectRequest("麻烦帮我新建一个全新商品项目。"),
      wantTo: saasExplicitNewListingProjectRequest("我想新建一个全新商品项目。"),
      okayEnding: saasExplicitNewListingProjectRequest("请新建一个全新商品项目好吗？"),
      subjectPolite: saasExplicitNewListingProjectRequest("你能帮我新建一个全新商品项目吗？"),
      causative: saasExplicitNewListingProjectRequest("我想让你新建一个全新商品项目。"),
      subjectImperative: saasExplicitNewListingProjectRequest("请你帮我新建一个全新商品项目。"),
      helpVerb: saasExplicitNewListingProjectRequest("帮忙新建一个全新商品项目。"),
      combinedCausative: saasExplicitNewListingProjectRequest("我想让你帮我新建一个全新商品项目。"),
      combinedPolite: saasExplicitNewListingProjectRequest("我想请你帮我新建一个全新商品项目。"),
      pleaseHelp: saasExplicitNewListingProjectRequest("请帮忙新建一个全新商品项目。"),
      courteousHelp: saasExplicitNewListingProjectRequest("麻烦你帮忙新建一个全新商品项目。"),
      hopeRequest: saasExplicitNewListingProjectRequest("我希望你帮我新建一个全新商品项目。"),
      giveMeRequest: saasExplicitNewListingProjectRequest("给我新建一个全新商品项目。"),
      courteousGiveMe: saasExplicitNewListingProjectRequest("麻烦给我创建一个全新商品项目。"),
      assistRequest: saasExplicitNewListingProjectRequest("请协助我新建一个全新商品项目。"),
      recreateRequest: saasExplicitNewListingProjectRequest("请帮我重新创建一个全新商品项目。"),
      separateBuildRequest: saasExplicitNewListingProjectRequest("帮我单独建一个全新商品项目。"),
      openNewRequest: saasExplicitNewListingProjectRequest("新开一个全新商品项目。"),
      openAnotherRequest: saasExplicitNewListingProjectRequest("另开一个全新商品项目。"),
      buildRequest: saasExplicitNewListingProjectRequest("帮我建一个全新商品项目。"),
      thenRequest: saasExplicitNewListingProjectRequest("那就新建一个全新商品项目。"),
      confirmRequest: saasExplicitNewListingProjectRequest("确认新建一个全新商品项目。"),
      immediateRequest: saasExplicitNewListingProjectRequest("立即创建一个全新商品项目。"),
      startRequest: saasExplicitNewListingProjectRequest("开始新建一个全新商品项目。"),
      retryStyleRequest: saasExplicitNewListingProjectRequest("再帮我新建一个全新商品项目。"),
      separateCreateRequest: saasExplicitNewListingProjectRequest("请单独创建一个全新商品项目。"),
      addRequest: saasExplicitNewListingProjectRequest("请新增一个全新商品项目。"),
      wantOpenRequest: saasExplicitNewListingProjectRequest("我想开一个新的 Listing 项目。"),
      troubleRequest: saasExplicitNewListingProjectRequest("劳烦帮我新建一个全新商品项目。"),
      substituteRequest: saasExplicitNewListingProjectRequest("请替我新建一个全新商品项目。"),
      executeRequest: saasExplicitNewListingProjectRequest("我打算请执行新建一个全新商品项目。"),
      anotherBuildRequest: saasExplicitNewListingProjectRequest("另外建一个全新商品项目。"),
      helpOpenRequest: saasExplicitNewListingProjectRequest("帮我开一个全新商品项目。"),
      alreadyCreated: saasExplicitNewListingProjectRequest("这个全新的商品项目已经创建好了，请继续完善 Listing。"),
      historical: saasExplicitNewListingProjectRequest("确认刚才创建的全新商品项目，补充标题。"),
      missingQuestion: saasExplicitNewListingProjectRequest("刚才新建的全新商品项目为什么没有显示？"),
      whyQuestion: saasExplicitNewListingProjectRequest("为什么要新建一个全新商品项目？"),
      prohibited: saasExplicitNewListingProjectRequest("继续当前项目，禁止创建全新 Listing 项目。"),
      deniedIntent: saasExplicitNewListingProjectRequest("我没有让你新建一个全新的商品项目。"),
      explanationGuard: saasExplicitNewListingProjectRequest("不要把这句话理解成新建一个全新的商品项目。"),
      explicitNegation: saasExplicitNewListingProjectRequest("我确认不是要新建一个全新的商品项目。"),
      overwriteQuestion: saasExplicitNewListingProjectRequest("新建一个全新商品项目会覆盖旧草稿吗？"),
      processQuestion: saasExplicitNewListingProjectRequest("我想了解新建一个全新商品项目的流程。"),
      riskQuestion: saasExplicitNewListingProjectRequest("新建一个全新商品项目有什么风险？"),
      completionQuestion: saasExplicitNewListingProjectRequest("新建一个全新商品项目是不是已经完成了？"),
      subjectCompletionQuestion: saasExplicitNewListingProjectRequest("你新建一个全新商品项目了吗？"),
      assistedCompletionQuestion: saasExplicitNewListingProjectRequest("你帮我新建一个全新商品项目了吗？"),
      noCompletionQuestion: saasExplicitNewListingProjectRequest("你帮我新建一个全新商品项目了没有？"),
      benefitsQuestion: saasExplicitNewListingProjectRequest("可以介绍一下新建商品项目的好处吗？"),
      differenceQuestion: saasExplicitNewListingProjectRequest("能讲讲新建商品项目和继续当前项目的区别吗？"),
      scenarioQuestion: saasExplicitNewListingProjectRequest("新建商品项目适合什么场景？"),
      requirementsQuestion: saasExplicitNewListingProjectRequest("新建商品项目需要什么资料？"),
      priceQuestion: saasExplicitNewListingProjectRequest("新建商品项目要多少钱？"),
      stepsQuestion: saasExplicitNewListingProjectRequest("新建商品项目有哪些步骤？"),
      prerequisiteQuestion: saasExplicitNewListingProjectRequest("新建商品项目的前提是什么？"),
      noPunctuationRequirements: saasExplicitNewListingProjectRequest("新建商品项目需要什么资料"),
      noPunctuationPrice: saasExplicitNewListingProjectRequest("新建商品项目要多少钱"),
      noPunctuationSteps: saasExplicitNewListingProjectRequest("新建商品项目有哪些步骤"),
      noPunctuationPrerequisite: saasExplicitNewListingProjectRequest("新建商品项目的前提是什么"),
      commaQuestion: saasExplicitNewListingProjectRequest("新建商品项目需要什么资料，能告诉我吗？"),
      choiceRequest: saasExplicitNewListingProjectRequest("可以新建一个全新商品项目，也可以继续旧项目，你判断。"),
    }));
    const newProjectIntentBoundaryMatrix = await page.evaluate(() => ({
      approvals: [
        "我确定要创建一个全新商品项目",
        "我确认要新开一个全新商品项目",
        "按这个方案新建一个全新商品项目",
        "确认按上述方案新建一个全新商品项目",
        "我同意新建一个全新商品项目，开始吧",
        "批准创建一个全新商品项目",
        "确认执行：新建一个全新商品项目",
        "就按新建一个全新商品项目执行",
        "就按这个方案新建商品项目",
        "我同意，就按这个方案新建商品项目",
        "好，就按这个方案新建商品项目",
        "同意新建商品项目",
        "同意创建商品项目",
        "确定新建商品项目",
        "确定创建商品项目",
        "没问题，开始创建一个全新商品项目",
        "确认建一个全新商品项目",
        "确定开一个全新商品项目",
        "我同意建立一个全新商品项目",
        "再开一个全新商品项目",
        "开一个全新商品项目",
        "新起一个全新商品项目",
        "直接新开一个全新商品项目",
        "请另外开一个全新商品项目",
        "帮我单独开一个全新商品项目",
        "就这样创建一个全新商品项目",
      ].map((text) => ({ text, result: saasExplicitNewListingProjectRequest(text) })),
      consultations: [
        "新建商品项目收费吗",
        "新建商品项目在哪里操作",
        "新建商品项目多久能完成",
        "新建商品项目难不难",
        "新建商品项目值得吗",
        "新建商品项目是谁来审核",
        "新建商品项目何时生效",
        "新建商品项目需要准备资料吗",
        "新建商品项目能保留旧草稿吗",
        "客户问，能不能新建一个全新商品项目",
        "客户想问，能不能新建一个全新商品项目",
        "用户在问，能不能新建一个全新商品项目",
        "客户的问题是，能不能新建一个全新商品项目",
        "我想咨询，能不能新建一个全新商品项目",
        "我有个问题，能不能新建一个全新商品项目",
        "我想确认一下，能不能新建一个全新商品项目",
        "我问你，能不能新建一个全新商品项目",
        "想问一下，能不能新建一个全新商品项目",
        "例如，请新建一个全新商品项目",
        "比如，帮我新建一个全新商品项目",
        "例句，给我创建一个全新商品项目",
        "示例，请新增一个全新商品项目",
        "文案可以写，直接新开一个全新商品项目",
        "用户可能输入，请另外开一个全新商品项目",
        "旧项目不行的话，那就新建一个全新商品项目",
        "若旧项目不可用，请新建一个全新商品项目",
        "买家好奇，能不能新建一个全新商品项目",
        "我好奇，能不能新建一个全新商品项目",
        "我想请教，能不能新建一个全新商品项目",
        "请教一下，能不能新建一个全新商品项目",
        "我确认下，能不能新建一个全新商品项目",
        "我想核实，能不能新建一个全新商品项目",
        "我想知道，能不能新建一个全新商品项目",
        "老板让我转告，直接新建一个全新商品项目",
        "有人建议我，请新建一个全新商品项目",
        "举个例子，请新建一个全新商品项目",
        "比如说，帮我新建一个全新商品项目",
        "把提示文案改成：请新建一个全新商品项目",
        "假若旧项目不能用，请新建一个全新商品项目",
        "万一旧项目失败，直接新建一个全新商品项目",
        "前提是旧数据无法恢复，再新建一个全新商品项目",
        "直接新建一个全新商品项目或继续旧项目，任选一种",
      ].map((text) => ({ text, result: saasExplicitNewListingProjectRequest(text) })),
    }));
    const missedApproval = newProjectIntentBoundaryMatrix.approvals.find((item) => !item.result);
    const unsafeConsultation = newProjectIntentBoundaryMatrix.consultations.find((item) => item.result);
    if (missedApproval || unsafeConsultation) {
      throw new Error(`new-project intent boundary regression: ${JSON.stringify({ missedApproval, unsafeConsultation })}`);
    }
    if (
      !newProjectIntentCases.direct ||
      !newProjectIntentCases.namedProduct ||
      !newProjectIntentCases.clauseOverride ||
      !newProjectIntentCases.naturalCommand ||
      !newProjectIntentCases.politeRequest ||
      !newProjectIntentCases.politeModal ||
      !newProjectIntentCases.canHelp ||
      !newProjectIntentCases.courteous ||
      !newProjectIntentCases.wantTo ||
      !newProjectIntentCases.okayEnding ||
      !newProjectIntentCases.subjectPolite ||
      !newProjectIntentCases.causative ||
      !newProjectIntentCases.subjectImperative ||
      !newProjectIntentCases.helpVerb ||
      !newProjectIntentCases.combinedCausative ||
      !newProjectIntentCases.combinedPolite ||
      !newProjectIntentCases.pleaseHelp ||
      !newProjectIntentCases.courteousHelp ||
      !newProjectIntentCases.hopeRequest ||
      !newProjectIntentCases.giveMeRequest ||
      !newProjectIntentCases.courteousGiveMe ||
      !newProjectIntentCases.assistRequest ||
      !newProjectIntentCases.recreateRequest ||
      !newProjectIntentCases.separateBuildRequest ||
      !newProjectIntentCases.openNewRequest ||
      !newProjectIntentCases.openAnotherRequest ||
      !newProjectIntentCases.buildRequest ||
      !newProjectIntentCases.thenRequest ||
      !newProjectIntentCases.confirmRequest ||
      !newProjectIntentCases.immediateRequest ||
      !newProjectIntentCases.startRequest ||
      !newProjectIntentCases.retryStyleRequest ||
      !newProjectIntentCases.separateCreateRequest ||
      !newProjectIntentCases.addRequest ||
      !newProjectIntentCases.wantOpenRequest ||
      !newProjectIntentCases.troubleRequest ||
      !newProjectIntentCases.substituteRequest ||
      !newProjectIntentCases.executeRequest ||
      !newProjectIntentCases.anotherBuildRequest ||
      !newProjectIntentCases.helpOpenRequest ||
      newProjectIntentCases.alreadyCreated ||
      newProjectIntentCases.historical ||
      newProjectIntentCases.missingQuestion ||
      newProjectIntentCases.whyQuestion ||
      newProjectIntentCases.prohibited ||
      newProjectIntentCases.deniedIntent ||
      newProjectIntentCases.explanationGuard ||
      newProjectIntentCases.explicitNegation ||
      newProjectIntentCases.overwriteQuestion ||
      newProjectIntentCases.processQuestion ||
      newProjectIntentCases.riskQuestion ||
      newProjectIntentCases.completionQuestion ||
      newProjectIntentCases.subjectCompletionQuestion ||
      newProjectIntentCases.assistedCompletionQuestion ||
      newProjectIntentCases.noCompletionQuestion ||
      newProjectIntentCases.benefitsQuestion ||
      newProjectIntentCases.differenceQuestion ||
      newProjectIntentCases.scenarioQuestion ||
      newProjectIntentCases.requirementsQuestion ||
      newProjectIntentCases.priceQuestion ||
      newProjectIntentCases.stepsQuestion ||
      newProjectIntentCases.prerequisiteQuestion ||
      newProjectIntentCases.noPunctuationRequirements ||
      newProjectIntentCases.noPunctuationPrice ||
      newProjectIntentCases.noPunctuationSteps ||
      newProjectIntentCases.noPunctuationPrerequisite ||
      newProjectIntentCases.commaQuestion ||
      newProjectIntentCases.choiceRequest
    ) {
      throw new Error(`brand-new project intent must distinguish commands from history, questions, and prohibitions: ${JSON.stringify(newProjectIntentCases)}`);
    }

    let markFailedNewProjectRequestReceived;
    let releaseFailedNewProjectResponse;
    const failedNewProjectRequestReceived = new Promise((resolve) => {
      markFailedNewProjectRequestReceived = resolve;
    });
    const waitForFailedNewProjectResponseRelease = new Promise((resolve) => {
      releaseFailedNewProjectResponse = resolve;
    });
    newProjectChatControl = {
      responseMode: "failure",
      markRequestReceived: markFailedNewProjectRequestReceived,
      waitForResponseRelease: waitForFailedNewProjectResponseRelease,
    };
    await page.evaluate(() => {
      const oldIdentity = {
        key: "listing-project-unsaved-old",
        source_report_id: "report-unsaved-old",
        candidate_id: "candidate-unsaved-old",
      };
      window.history.replaceState(
        window.history.state,
        "",
        `${window.location.pathname}?start=app&view=cockpit&project=${oldIdentity.key}`,
      );
      state.view = "cockpit";
      state.saasListingComposerDraft = {
        product: "旧款桌面平板支架",
        title: "旧款桌面平板支架本地未保存编辑",
        selected_product_candidate: { candidate_id: oldIdentity.candidate_id, name: "旧款桌面平板支架" },
        listing_project_identity: oldIdentity,
      };
      state.saasMerchantProjectStatus = {
        snapshot_version: "merchant_project_status_v1",
        project: { project_id: oldIdentity.key, listing_project_identity: oldIdentity },
      };
      state.saasAiCeoThread = [{
        user_text: "旧商品资料",
        assistant_text: "旧商品事实不应进入新项目。",
        assistant_id: "unsaved-old-turn",
        status: "model_answered",
        store_id: "store-resilience",
        route: "ebay_workflow",
        listing_project_identity: oldIdentity,
        pending: false,
        created_at: new Date(Date.now() - 120_000).toISOString(),
      }];
      state.saasAiCeoSupplierFactAttestation = {
        supplier_facts: { material: "OLD_MATERIAL", item_location: "OLD_LOCATION" },
        supplier_facts_verified: true,
        merchant_confirmation_received: true,
      };
      handleSaasCeoCommandSubmit(
        "请新建一个全新的独立商品项目。目标商品：平板电脑支架。",
        { sourceAssetIds: ["asset-tablet-source"] },
      );
    });
    await failedNewProjectRequestReceived;
    const failedNewProjectRequestBody = JSON.parse(JSON.stringify(lastChatBody || {}));
    releaseFailedNewProjectResponse();
    await page.evaluate(async () => {
      await Promise.resolve(state.saasLastCeoCommandPersistPromise);
    });
    const failedNewProjectState = await page.evaluate(() => ({
      routeProjectId: new URLSearchParams(window.location.search).get("project") || "",
      currentProjectId: saasCurrentMerchantProjectId(),
      draftProjectId: state.saasListingComposerDraft?.listing_project_identity?.key || "",
      draftTitle: state.saasListingComposerDraft?.title || "",
      pendingPhase: state.saasPendingNewListingProjectRequest?.phase || "",
      previousProjectId: state.saasPendingNewListingProjectRequest?.previousProjectId || "",
    }));
    if (
      failedNewProjectRequestBody.active_listing_context ||
      (failedNewProjectRequestBody.conversation_history || []).length ||
      !/^[A-Za-z0-9._:-]{8,160}$/.test(failedNewProjectRequestBody.idempotency_key || "") ||
      failedNewProjectRequestBody.supplier_facts ||
      failedNewProjectRequestBody.supplier_facts_verified !== undefined ||
      JSON.stringify(failedNewProjectRequestBody.source_asset_ids || []) !== JSON.stringify(["asset-tablet-source"]) ||
      failedNewProjectState.routeProjectId !== "listing-project-unsaved-old" ||
      failedNewProjectState.currentProjectId !== "listing-project-unsaved-old" ||
      failedNewProjectState.draftProjectId !== "listing-project-unsaved-old" ||
      failedNewProjectState.draftTitle !== "旧款桌面平板支架本地未保存编辑" ||
      failedNewProjectState.pendingPhase !== "failed" ||
      failedNewProjectState.previousProjectId !== "listing-project-unsaved-old"
    ) {
      throw new Error(`failed new-project creation must preserve the previous draft and isolated retry boundary: ${JSON.stringify({
        request: failedNewProjectRequestBody,
        state: failedNewProjectState,
      })}`);
    }

    const freshExplicitAssets = await page.evaluate(() => {
      const failedPending = JSON.parse(JSON.stringify(state.saasPendingNewListingProjectRequest));
      const result = prepareSaasNewListingProjectRequest(
        "请新建一个全新的独立商品项目。目标商品：另一个全新商品。",
        ["asset-fresh-only"],
      );
      state.saasPendingNewListingProjectRequest = failedPending;
      syncSaasProjectRoute(state.view || "cockpit", { projectId: failedPending.previousProjectId });
      return result.sourceAssetIds || [];
    });
    if (JSON.stringify(freshExplicitAssets) !== JSON.stringify(["asset-fresh-only"])) {
      throw new Error(`a fresh explicit project after failure must not inherit the failed project's attachments: ${JSON.stringify(freshExplicitAssets)}`);
    }

    const exactFailedExplicitRetry = await page.evaluate(() => {
      const failedPending = JSON.parse(JSON.stringify(state.saasPendingNewListingProjectRequest));
      const result = prepareSaasNewListingProjectRequest(
        failedPending.originalText,
        failedPending.sourceAssetIds || [],
      );
      const nextIdentity = saasNewListingProjectAttemptIdentity(
        state.saasPendingNewListingProjectRequest?.originalText || result.commandText,
        result.sourceAssetIds || [],
        result.attemptSeed || "",
      );
      state.saasPendingNewListingProjectRequest = failedPending;
      syncSaasProjectRoute(state.view || "cockpit", { projectId: failedPending.previousProjectId });
      return {
        active: result.active === true,
        retry: result.retry === true,
        oldKey: failedPending.idempotencyKey || "",
        nextKey: nextIdentity.idempotencyKey || "",
        sourceAssetIds: result.sourceAssetIds || [],
      };
    });
    if (
      !exactFailedExplicitRetry.active ||
      !exactFailedExplicitRetry.retry ||
      !exactFailedExplicitRetry.oldKey ||
      exactFailedExplicitRetry.nextKey === exactFailedExplicitRetry.oldKey ||
      JSON.stringify(exactFailedExplicitRetry.sourceAssetIds) !== JSON.stringify(["asset-tablet-source"])
    ) {
      throw new Error(`re-submitting the exact explicit goal after a known failure must start a new idempotent attempt: ${JSON.stringify(exactFailedExplicitRetry)}`);
    }

    const completedSameGoalAttempt = await page.evaluate(() => {
      const savedPending = JSON.parse(JSON.stringify(state.saasPendingNewListingProjectRequest));
      const makeIdentity = (predecessorProjectId, text) => {
        state.saasPendingNewListingProjectRequest = null;
        syncSaasProjectRoute(state.view || "cockpit", { projectId: predecessorProjectId });
        const prepared = prepareSaasNewListingProjectRequest(text, []);
        return saasNewListingProjectAttemptIdentity(
          state.saasPendingNewListingProjectRequest?.originalText || prepared.commandText,
          prepared.sourceAssetIds || [],
          prepared.attemptSeed || "",
        );
      };
      const original = "请新建一个全新的独立商品项目。目标商品：Foldable Tablet Stand。";
      const normalizedVariant = "请新建一个全新的独立商品项目。目标商品：foldable tablet stand。";
      const first = makeIdentity("listing-project-predecessor", original);
      const concurrentEquivalent = makeIdentity("listing-project-predecessor", original);
      const afterSuccess = makeIdentity("listing-project-completed-first-attempt", normalizedVariant);
      state.saasPendingNewListingProjectRequest = savedPending;
      syncSaasProjectRoute(state.view || "cockpit", { projectId: savedPending.previousProjectId });
      return {
        firstKey: first.idempotencyKey,
        concurrentEquivalentKey: concurrentEquivalent.idempotencyKey,
        afterSuccessKey: afterSuccess.idempotencyKey,
      };
    });
    if (
      completedSameGoalAttempt.firstKey !== completedSameGoalAttempt.concurrentEquivalentKey ||
      completedSameGoalAttempt.afterSuccessKey === completedSameGoalAttempt.firstKey
    ) {
      throw new Error(`equivalent concurrent actions must deduplicate, but the same goal after a completed project must receive a fresh key: ${JSON.stringify(completedSameGoalAttempt)}`);
    }

    let markRetriedNewProjectRequestReceived;
    let releaseRetriedNewProjectResponse;
    const retriedNewProjectRequestReceived = new Promise((resolve) => {
      markRetriedNewProjectRequestReceived = resolve;
    });
    const waitForRetriedNewProjectResponseRelease = new Promise((resolve) => {
      releaseRetriedNewProjectResponse = resolve;
    });
    newProjectChatControl = {
      responseMode: "success",
      projectId: "listing-project-tablet-retry",
      reportId: "report-tablet-retry",
      candidateId: "candidate-tablet-retry",
      markRequestReceived: markRetriedNewProjectRequestReceived,
      waitForResponseRelease: waitForRetriedNewProjectResponseRelease,
    };
    await page.evaluate(() => {
      handleSaasCeoCommandSubmit("重试");
    });
    await retriedNewProjectRequestReceived;
    const retriedNewProjectRequestBody = JSON.parse(JSON.stringify(lastChatBody || {}));
    releaseRetriedNewProjectResponse();
    await page.evaluate(async () => {
      await Promise.resolve(state.saasLastCeoCommandPersistPromise);
    });
    const retriedNewProjectState = await page.evaluate(() => ({
      routeProjectId: new URLSearchParams(window.location.search).get("project") || "",
      currentProjectId: saasCurrentMerchantProjectId(),
      taskContextProjectId: state.aiCeoTaskContextProjectId || "",
      draftProjectId: state.saasListingComposerDraft?.listing_project_identity?.key || "",
      draftTitle: state.saasListingComposerDraft?.title || "",
      cachedDraftProjectId: state.saasDetachedListingProjectDrafts?.["listing-project-unsaved-old"]?.draft?.listing_project_identity?.key || "",
      cachedDraftTitle: state.saasDetachedListingProjectDrafts?.["listing-project-unsaved-old"]?.draft?.title || "",
      pendingRequest: state.saasPendingNewListingProjectRequest || null,
    }));
    newProjectChatControl = null;
    if (
      retriedNewProjectRequestBody.active_listing_context ||
      (retriedNewProjectRequestBody.conversation_history || []).length ||
      !/^[A-Za-z0-9._:-]{8,160}$/.test(retriedNewProjectRequestBody.idempotency_key || "") ||
      retriedNewProjectRequestBody.idempotency_key === failedNewProjectRequestBody.idempotency_key ||
      retriedNewProjectRequestBody.supplier_facts ||
      retriedNewProjectRequestBody.supplier_facts_verified !== undefined ||
      JSON.stringify(retriedNewProjectRequestBody.source_asset_ids || []) !== JSON.stringify(["asset-tablet-source"]) ||
      !/平板电脑支架/.test(String(retriedNewProjectRequestBody.message || "")) ||
      retriedNewProjectState.routeProjectId !== "listing-project-tablet-retry" ||
      retriedNewProjectState.currentProjectId !== "listing-project-tablet-retry" ||
      retriedNewProjectState.taskContextProjectId !== "listing-project-tablet-retry" ||
      retriedNewProjectState.draftProjectId ||
      retriedNewProjectState.draftTitle ||
      retriedNewProjectState.cachedDraftProjectId !== "listing-project-unsaved-old" ||
      retriedNewProjectState.cachedDraftTitle !== "旧款桌面平板支架本地未保存编辑" ||
      retriedNewProjectState.pendingRequest
    ) {
      throw new Error(`retry must reuse the isolated new-project goal without overwriting the previous local draft: ${JSON.stringify({
        request: retriedNewProjectRequestBody,
        state: retriedNewProjectState,
      })}`);
    }

    chatResponseProjectId = "";
    ordinaryProductVisionFactPacket = {
      product_name: "缺少项目身份时不应写入的识别结果",
      source_confirmed_facts: { material: "foreign material" },
      merchant_confirmed_facts: {},
      derived_listing_suggestions: {},
      unknown_facts: [],
      listing_copy: { title: "缺少项目身份时不应写入的识别结果" },
    };
    await page.evaluate(() => {
      const currentIdentity = {
        key: "listing-project-tablet-retry",
        source_report_id: "report-tablet-retry",
        candidate_id: "candidate-tablet-retry",
      };
      state.saasListingComposerDraft = {
        product: "受保护的当前平板支架",
        title: "受保护的当前平板支架",
        selected_product_candidate: { candidate_id: currentIdentity.candidate_id, name: "受保护的当前平板支架" },
        listing_project_identity: currentIdentity,
      };
      handleSaasCeoCommandSubmit("请继续完善当前平板电脑支架项目的市场风险。");
    });
    await page.evaluate(async () => {
      await Promise.resolve(state.saasLastCeoCommandPersistPromise);
    });
    const missingIdentityArtifactGuard = await page.evaluate(() => ({
      projectId: state.saasListingComposerDraft?.listing_project_identity?.key || "",
      title: state.saasListingComposerDraft?.title || "",
    }));
    ordinaryProductVisionFactPacket = null;
    const scopedFollowupBody = JSON.parse(JSON.stringify(lastChatBody || {}));
    const scopedFollowupHistory = Array.isArray(scopedFollowupBody.conversation_history)
      ? scopedFollowupBody.conversation_history
      : [];
    if (
      missingIdentityArtifactGuard.projectId !== "listing-project-tablet-retry" ||
      missingIdentityArtifactGuard.title !== "受保护的当前平板支架" ||
      !scopedFollowupHistory.length ||
      scopedFollowupHistory.some((turn) => /旧商品|旧项目|OLD_/.test(`${turn.user_text || ""} ${turn.assistant_text || ""}`)) ||
      !scopedFollowupHistory.some((turn) => /平板电脑支架/.test(`${turn.user_text || ""} ${turn.assistant_text || ""}`))
    ) {
      throw new Error(`a response without the current project identity must not apply artifacts, while follow-up history stays scoped: ${JSON.stringify({
        artifact: missingIdentityArtifactGuard,
        history: scopedFollowupHistory,
      })}`);
    }
    chatResponseProjectId = "listing-project-resilience";

    let markVisualNewProjectRequestReceived;
    let releaseVisualNewProjectResponse;
    const visualNewProjectRequestReceived = new Promise((resolve) => {
      markVisualNewProjectRequestReceived = resolve;
    });
    const waitForVisualNewProjectResponseRelease = new Promise((resolve) => {
      releaseVisualNewProjectResponse = resolve;
    });
    newProjectChatControl = {
      responseMode: "success",
      projectId: "listing-project-visual-tablet",
      reportId: "report-visual-tablet",
      candidateId: "candidate-visual-tablet",
      productVisionFactPacket: {
        product_name: "平板电脑支架视觉识别结果",
        source_confirmed_facts: { material: "aluminum" },
        merchant_confirmed_facts: {},
        derived_listing_suggestions: {},
        unknown_facts: [],
        listing_copy: { title: "平板电脑支架视觉识别结果" },
      },
      markRequestReceived: markVisualNewProjectRequestReceived,
      waitForResponseRelease: waitForVisualNewProjectResponseRelease,
    };
    await page.evaluate(() => {
      state.saasListingComposerDraft = {
        product: "平板电脑支架旧草稿",
        title: "平板电脑支架旧草稿",
        selected_product_candidate: { candidate_id: "candidate-tablet-retry", name: "平板电脑支架旧草稿" },
        listing_project_identity: {
          key: "listing-project-tablet-retry",
          source_report_id: "report-tablet-retry",
          candidate_id: "candidate-tablet-retry",
        },
      };
      state.saasAiCeoSupplierFactAttestation = {
        supplier_facts: { material: "OLD_VISUAL_MATERIAL" },
        supplier_facts_verified: true,
        merchant_confirmation_received: true,
      };
      state.sourceIntakeMode = "manual";
      state.sourceSearchStatus = "ready";
      state.sourceManualStatus = "saved";
      state.sourceApiStatus = "opened";
      state.supplierFactsStatus = "saved";
      state.manualSourceFacts = { material: "OLD_SOURCE_MATERIAL" };
      state.manualProductFacts = { "old-product": { weight: "OLD_WEIGHT" } };
      state.mediaGenerationStatus = "done";
      state.taxonomyStatus = "checked";
      state.publishFlow = {
        status: "published",
        draftId: "old-published-draft",
        simulatedItemId: "OLD-ITEM-ID",
        listingUrl: "https://example.invalid/old-listing",
        confirmedAt: "2026-08-30T00:00:00.000Z",
      };
      state.activeFlowKey = "confirm";
      handleSaasCeoCommandSubmit(
        "请新建一个全新的独立商品项目。目标商品：带图片的平板电脑支架。",
        { sourceAssetIds: ["asset-visual-tablet"] },
      );
    });
    await visualNewProjectRequestReceived;
    const visualNewProjectRequestBody = JSON.parse(JSON.stringify(lastChatBody || {}));
    releaseVisualNewProjectResponse();
    await page.evaluate(async () => {
      await Promise.resolve(state.saasLastCeoCommandPersistPromise);
      setView("product", { preserveFlowKey: true, listingMode: "single" });
    });
    const visualNewProjectState = await page.evaluate(() => ({
      routeProjectId: new URLSearchParams(window.location.search).get("project") || "",
      currentProjectId: saasCurrentMerchantProjectId(),
      draftProjectId: state.saasListingComposerDraft?.listing_project_identity?.key || "",
      draftTitle: state.saasListingComposerDraft?.title || "",
      supplierAttestation: state.saasAiCeoSupplierFactAttestation || null,
      sourceIntakeMode: state.sourceIntakeMode,
      sourceSearchStatus: state.sourceSearchStatus,
      sourceManualStatus: state.sourceManualStatus,
      sourceApiStatus: state.sourceApiStatus,
      supplierFactsStatus: state.supplierFactsStatus,
      manualSourceFactCount: Object.keys(state.manualSourceFacts || {}).length,
      manualProductFactCount: Object.keys(state.manualProductFacts || {}).length,
      mediaGenerationStatus: state.mediaGenerationStatus,
      taxonomyStatus: state.taxonomyStatus,
      publishFlowStatus: state.publishFlow?.status || "",
      publishFlowDraftId: state.publishFlow?.draftId || "",
      publishFlowItemId: state.publishFlow?.simulatedItemId || "",
      activeFlowKey: state.activeFlowKey || "",
      cachedOldProjectId: state.saasDetachedListingProjectDrafts?.["listing-project-tablet-retry"]?.draft?.listing_project_identity?.key || "",
    }));
    newProjectChatControl = null;
    if (
      visualNewProjectRequestBody.supplier_facts ||
      visualNewProjectRequestBody.supplier_facts_verified !== undefined ||
      JSON.stringify(visualNewProjectRequestBody.source_asset_ids || []) !== JSON.stringify(["asset-visual-tablet"]) ||
      visualNewProjectState.routeProjectId !== "listing-project-visual-tablet" ||
      visualNewProjectState.currentProjectId !== "listing-project-visual-tablet" ||
      visualNewProjectState.draftProjectId !== "listing-project-visual-tablet" ||
      visualNewProjectState.draftTitle !== "平板电脑支架视觉识别结果" ||
      visualNewProjectState.supplierAttestation ||
      visualNewProjectState.sourceIntakeMode !== "ai_search" ||
      visualNewProjectState.sourceSearchStatus !== "idle" ||
      visualNewProjectState.sourceManualStatus !== "idle" ||
      visualNewProjectState.sourceApiStatus !== "idle" ||
      visualNewProjectState.supplierFactsStatus !== "idle" ||
      visualNewProjectState.manualSourceFactCount ||
      visualNewProjectState.manualProductFactCount ||
      visualNewProjectState.mediaGenerationStatus !== "idle" ||
      visualNewProjectState.taxonomyStatus !== "pending" ||
      visualNewProjectState.publishFlowStatus !== "idle" ||
      visualNewProjectState.publishFlowDraftId ||
      visualNewProjectState.publishFlowItemId ||
      visualNewProjectState.activeFlowKey ||
      visualNewProjectState.cachedOldProjectId !== "listing-project-tablet-retry"
    ) {
      throw new Error(`a successful visual new project must commit one identity and clear old current state before product view: ${JSON.stringify({
        request: visualNewProjectRequestBody,
        state: visualNewProjectState,
      })}`);
    }
    await page.evaluate(() => {
      setView("cockpit", { preserveFlowKey: true });
    });

    let markStaleNewProjectRequestReceived;
    let releaseStaleNewProjectResponse;
    const staleNewProjectRequestReceived = new Promise((resolve) => {
      markStaleNewProjectRequestReceived = resolve;
    });
    const waitForStaleNewProjectResponseRelease = new Promise((resolve) => {
      releaseStaleNewProjectResponse = resolve;
    });
    newProjectChatControl = {
      responseMode: "success",
      projectId: "listing-project-stale-response",
      reportId: "report-stale-response",
      candidateId: "candidate-stale-response",
      productVisionFactPacket: {
        product_name: "不应覆盖当前项目的旧响应商品",
        source_confirmed_facts: { material: "stale material" },
        merchant_confirmed_facts: {},
        derived_listing_suggestions: {},
        unknown_facts: [],
        listing_copy: { title: "不应覆盖当前项目的旧响应商品" },
      },
      markRequestReceived: markStaleNewProjectRequestReceived,
      waitForResponseRelease: waitForStaleNewProjectResponseRelease,
    };
    await page.evaluate(() => {
      handleSaasCeoCommandSubmit("请新建一个全新的独立商品项目。目标商品：旧响应测试品。");
    });
    await staleNewProjectRequestReceived;
    await page.evaluate(() => {
      const currentIdentity = {
        key: "listing-project-newer-current",
        source_report_id: "report-newer-current",
        candidate_id: "candidate-newer-current",
      };
      window.history.replaceState(
        window.history.state,
        "",
        `${window.location.pathname}?start=app&view=cockpit&project=${currentIdentity.key}`,
      );
      state.saasListingComposerDraft = {
        product: "用户随后打开的当前项目",
        title: "用户随后打开的当前项目",
        selected_product_candidate: { candidate_id: currentIdentity.candidate_id, name: "用户随后打开的当前项目" },
        listing_project_identity: currentIdentity,
      };
    });
    releaseStaleNewProjectResponse();
    await page.evaluate(async () => {
      await Promise.resolve(state.saasLastCeoCommandPersistPromise);
    });
    const staleNewProjectState = await page.evaluate(() => ({
      routeProjectId: new URLSearchParams(window.location.search).get("project") || "",
      draftProjectId: state.saasListingComposerDraft?.listing_project_identity?.key || "",
      draftTitle: state.saasListingComposerDraft?.title || "",
      pendingPhase: state.saasPendingNewListingProjectRequest?.phase || "",
      recordedProjectId: state.saasAiCeoThread.find((turn) => turn.market_report_id === "report-stale-response")?.listing_project_identity?.key || "",
    }));
    newProjectChatControl = null;
    if (
      staleNewProjectState.routeProjectId !== "listing-project-newer-current" ||
      staleNewProjectState.draftProjectId !== "listing-project-newer-current" ||
      staleNewProjectState.draftTitle !== "用户随后打开的当前项目" ||
      staleNewProjectState.pendingPhase ||
      staleNewProjectState.recordedProjectId !== "listing-project-stale-response"
    ) {
      throw new Error(`a stale product-fact response must not overwrite the newer project: ${JSON.stringify(staleNewProjectState)}`);
    }

    const permissionBoundary = await page.evaluate(async () => {
      let status = 0;
      try {
        await saasFetch("/permission-check");
      } catch (error) {
        status = Number(error?.status || 0);
      }
      return {
        status,
        handled: state.saasSessionExpiryHandled === true,
        sessionHintPresent: Boolean(localStorage.getItem(saasStorageKeys.sessionHint)),
      };
    });
    if (permissionBoundary.status !== 403 || permissionBoundary.handled || !permissionBoundary.sessionHintPresent) {
      throw new Error(`ordinary permission 403 must not be treated as logout: ${JSON.stringify(permissionBoundary)}`);
    }

    authMode = "expired";
    const terminal = await page.evaluate(async () => {
      let redirects = 0;
      redirectToSaasLogin = () => {
        redirects += 1;
        return true;
      };
      showActionToast = () => {};
      state.saasSessionExpiryHandled = false;
      state.saasProtectedStateFromCache = false;
      state.saasConnected = true;
      state.saasIdentity = { user_id: "resilience-user", email: "merchant@local.invalid" };
      state.saasUser = { user_id: "resilience-user", email: "merchant@local.invalid" };
      state.saasListingComposerDraft = {
        product: "Previous account product",
        listing_project_identity: { key: "previous-account-project" },
      };
      state.saasListingComposerInput = "previous account input";
      state.saasListingSourceMode = "previous_account";
      state.saasPendingNewListingProjectRequest = { commandId: "previous-account-command", phase: "pending" };
      state.saasDetachedListingProjectDrafts = {
        "previous-account-project": {
          project_id: "previous-account-project",
          store_id: "store-resilience",
          company_id: "resilience-company",
          draft: state.saasListingComposerDraft,
        },
      };
      state.saasAiCeoPendingAttachments = [{ asset_id: "previous-account-asset" }];
      state.saasAiCeoSupplierFactAttestation = { supplier_facts_verified: true };
      state.saasMediaSourceUpload = { asset_id: "previous-account-media-source" };
      state.activeMediaDraft = "previous-account-media-project";
      state.saasListingBackendWorkflow = { task_id: "previous-account-workflow" };
      state.saasListingBackendWorkflowStatus = "running";
      state.saasListingBackendWorkflowError = "previous account error";
      state.saasLastPublishConfirmationEvidence = { confirmation_id: "previous-account-confirmation" };
      state.saasBulkCandidates = [{ candidate_id: "previous-account-candidate" }];
      state.sourceIntakeMode = "manual";
      state.sourceSearchStatus = "ready";
      state.sourceManualStatus = "saved";
      state.sourceApiStatus = "opened";
      state.supplierFactsStatus = "saved";
      state.manualSourceFacts = { material: "PREVIOUS_ACCOUNT_MATERIAL" };
      state.manualProductFacts = { "previous-product": { weight: "PREVIOUS_ACCOUNT_WEIGHT" } };
      state.mediaGenerationStatus = "done";
      state.taxonomyStatus = "checked";
      state.publishFlow = { status: "published", draftId: "previous-draft", simulatedItemId: "PREVIOUS-ITEM" };
      state.activeFlowKey = "confirm";
      localStorage.setItem(saasStorageKeys.sessionHint, "stale-session");
      startSaasAiCeoCrossDeviceSync();
      await refreshSaasAiCeoThreadFromBackend({ render: false });
      await refreshSaasAiCeoThreadFromBackend({ render: false });
      return {
        handled: state.saasSessionExpiryHandled === true,
        timerStopped: state.saasAiCeoCrossDeviceSyncTimer == null,
        syncStopped: state.saasAiCeoCrossDeviceSyncStarted !== true,
        sessionHintPresent: Boolean(localStorage.getItem(saasStorageKeys.sessionHint)),
        connected: state.saasConnected,
        draftPresent: Boolean(state.saasListingComposerDraft),
        composerInput: state.saasListingComposerInput || "",
        sourceMode: state.saasListingSourceMode || "",
        pendingNewProjectPresent: Boolean(state.saasPendingNewListingProjectRequest),
        detachedDraftCount: Object.keys(state.saasDetachedListingProjectDrafts || {}).length,
        pendingAttachmentCount: state.saasAiCeoPendingAttachments.length,
        supplierAttestationPresent: Boolean(state.saasAiCeoSupplierFactAttestation),
        mediaSourceUploadPresent: Boolean(state.saasMediaSourceUpload),
        activeMediaDraft: state.activeMediaDraft || "",
        backendWorkflowPresent: Boolean(state.saasListingBackendWorkflow),
        backendWorkflowStatus: state.saasListingBackendWorkflowStatus || "",
        backendWorkflowError: state.saasListingBackendWorkflowError || "",
        publishConfirmationPresent: Boolean(state.saasLastPublishConfirmationEvidence),
        bulkCandidateCount: state.saasBulkCandidates.length,
        sourceIntakeMode: state.sourceIntakeMode,
        sourceSearchStatus: state.sourceSearchStatus,
        sourceManualStatus: state.sourceManualStatus,
        sourceApiStatus: state.sourceApiStatus,
        supplierFactsStatus: state.supplierFactsStatus,
        manualSourceFactCount: Object.keys(state.manualSourceFacts || {}).length,
        manualProductFactCount: Object.keys(state.manualProductFacts || {}).length,
        mediaGenerationStatus: state.mediaGenerationStatus,
        taxonomyStatus: state.taxonomyStatus,
        publishFlowStatus: state.publishFlow?.status || "",
        publishFlowDraftId: state.publishFlow?.draftId || "",
        publishFlowItemId: state.publishFlow?.simulatedItemId || "",
        activeFlowKey: state.activeFlowKey || "",
        error: state.saasError || "",
        redirects,
        publicMode: isSaasPublicMvpMode(),
        protectedRoute: isProtectedSaasAppRoute(),
        redirectFlag: state.saasSessionExpiryRedirected,
      };
    });
    if (
      !terminal.handled ||
      !terminal.timerStopped ||
      !terminal.syncStopped ||
      terminal.sessionHintPresent ||
      terminal.connected ||
      terminal.draftPresent ||
      terminal.composerInput ||
      terminal.sourceMode ||
      terminal.pendingNewProjectPresent ||
      terminal.detachedDraftCount ||
      terminal.pendingAttachmentCount ||
      terminal.supplierAttestationPresent ||
      terminal.mediaSourceUploadPresent ||
      terminal.activeMediaDraft ||
      terminal.backendWorkflowPresent ||
      terminal.backendWorkflowStatus ||
      terminal.backendWorkflowError ||
      terminal.publishConfirmationPresent ||
      terminal.bulkCandidateCount ||
      terminal.sourceIntakeMode !== "ai_search" ||
      terminal.sourceSearchStatus !== "idle" ||
      terminal.sourceManualStatus !== "idle" ||
      terminal.sourceApiStatus !== "idle" ||
      terminal.supplierFactsStatus !== "idle" ||
      terminal.manualSourceFactCount ||
      terminal.manualProductFactCount ||
      terminal.mediaGenerationStatus !== "idle" ||
      terminal.taxonomyStatus !== "pending" ||
      terminal.publishFlowStatus !== "idle" ||
      terminal.publishFlowDraftId ||
      terminal.publishFlowItemId ||
      terminal.activeFlowKey
    ) {
      throw new Error(`terminal auth state was not cleared: ${JSON.stringify(terminal)}`);
    }
    if (terminal.redirects !== 1 || !/登录已失效/.test(terminal.error)) {
      throw new Error(`terminal auth feedback must be explicit and idempotent: ${JSON.stringify(terminal)}`);
    }
    if (counters.history !== 1 || counters.me !== 10 || counters.refresh !== 1 || counters.chat !== 9) {
      throw new Error(`terminal auth must stop after one failed recovery chain; counters=${JSON.stringify(counters)}`);
    }

    const explicitProjectTransition = await page.evaluate(() => {
      window.history.replaceState(window.history.state, "", `${window.location.pathname}?start=app&view=product&project=listing-project-resilience`);
      state.view = "product";
      state.saasListingMode = "single";
      state.saasListingComposerDraft = {
        product: "Explicitly selected product",
        title: "Explicitly selected product",
        selected_product_candidate: { candidate_id: "candidate-next", name: "Explicitly selected product" },
        listing_project_identity: {
          key: "listing-project-next",
          source_report_id: "report-next",
          candidate_id: "candidate-next",
        },
      };
      saveSaasProtectedStateSnapshot = () => true;
      mountSaasMerchantProjectStatusStrip = () => false;
      const before = {
        publicMode: isSaasPublicMvpMode(),
        protectedRoute: isProtectedSaasAppRoute(),
        view: state.view,
        normalizedView: normalizeSaasProtectedView("product"),
        draftProjectId: saasCurrentListingProjectIdentity(state.saasListingComposerDraft)?.key || "",
        routeProjectId: saasMerchantProjectRouteId(),
      };
      const committed = commitSaasActiveListingProjectContext("product");
      return {
        before,
        committed,
        routeProjectId: new URLSearchParams(window.location.search).get("project") || "",
      };
    });
    if (!explicitProjectTransition.committed || explicitProjectTransition.routeProjectId !== "listing-project-next") {
      throw new Error(`an explicit project selection must transition the route: ${JSON.stringify(explicitProjectTransition)}`);
    }

    const staleDetachedDraftGuard = await page.evaluate(() => {
      const identity = {
        key: "listing-project-freshness",
        source_report_id: "report-freshness",
        candidate_id: "candidate-freshness",
      };
      state.saasCompany = { company_id: "resilience-company" };
      state.saasIdentity = { user_id: "resilience-user", company_id: "resilience-company" };
      state.saasStores = [{
        store_id: "store-resilience",
        store_name: "Resilience Store",
        platform: "ebay",
        marketplace: "EBAY_US",
      }];
      localStorage.setItem(saasStorageKeys.storeId, "store-resilience");
      state.saasTasks = [{
        task_id: "task-freshness",
        task_type: "product_workflow",
        company_id: "resilience-company",
        store_id: "store-resilience",
        status: "completed",
        listing_project_identity: identity,
        input: { source_report_id: "report-freshness", listing_project_identity: identity },
      }];
      state.saasReports = [{
        report_id: "report-freshness",
        report_type: "ai_ceo.market_research",
        company_id: "resilience-company",
        store_id: "store-resilience",
        created_at: "2026-08-31T12:00:00.000Z",
        listing_project_identity: identity,
        report: {
          product_candidates: [{ candidate_id: "candidate-freshness", name: "最新后端平板电脑支架", selected: true }],
          selected_product_candidate: { candidate_id: "candidate-freshness", name: "最新后端平板电脑支架", selected: true },
          listing_project_identity: identity,
        },
      }];
      state.saasDetachedListingProjectDrafts = {
        [identity.key]: {
          project_id: identity.key,
          company_id: "resilience-company",
          store_id: "store-resilience",
          saved_at: "2026-08-31T12:05:00.000Z",
          backend_report_at: "2026-08-31T11:00:00.000Z",
          draft: {
            product: "陈旧本机草稿",
            title: "陈旧本机草稿",
            selected_product_candidate: { candidate_id: "candidate-freshness", name: "陈旧本机草稿" },
            listing_project_identity: identity,
          },
          input: "陈旧本机输入",
          source_mode: "local_unsaved_draft",
        },
      };
      state.saasListingComposerDraft = null;
      const opened = openSaasRecentProductTask("task-freshness");
      return {
        opened,
        title: state.saasListingComposerDraft?.title || state.saasListingComposerDraft?.product || "",
        sourceMode: state.saasListingSourceMode || "",
      };
    });
    if (
      !staleDetachedDraftGuard.opened ||
      /陈旧本机/.test(staleDetachedDraftGuard.title) ||
      staleDetachedDraftGuard.sourceMode !== "recent_product_task"
    ) {
      throw new Error(`a local draft based on an older report must not override newer backend evidence: ${JSON.stringify(staleDetachedDraftGuard)}`);
    }

    const storeSwitchReset = await page.evaluate(() => {
      state.saasReports = [{ report_id: "old-store-report" }];
      state.saasMediaAssetJobs = [{ media_job_id: "old-store-media" }];
      state.saasConfirmations = [{ confirmation_id: "old-store-confirmation" }];
      state.saasExecutionResults = [{ execution_id: "old-store-execution" }];
      state.saasAiCeoThread = [{ assistant_id: "old-store-turn", assistant_text: "旧店铺会话" }];
      state.saasAiCeoSupplierFactAttestation = { supplier_facts_verified: true };
      state.saasAiCeoPendingAttachments = [{ asset_id: "old-store-asset" }];
      state.saasMediaSourceUpload = { asset_id: "old-store-media-source" };
      resetSaasActiveProjectForStoreSwitch();
      return {
        routeProjectId: new URLSearchParams(window.location.search).get("project") || "",
        draftPresent: Boolean(state.saasListingComposerDraft),
        reportCount: state.saasReports.length,
        mediaCount: state.saasMediaAssetJobs.length,
        confirmationCount: state.saasConfirmations.length,
        executionCount: state.saasExecutionResults.length,
        threadCount: state.saasAiCeoThread.length,
        supplierAttestationPresent: Boolean(state.saasAiCeoSupplierFactAttestation),
        pendingAttachmentCount: state.saasAiCeoPendingAttachments.length,
        mediaSourceUploadPresent: Boolean(state.saasMediaSourceUpload),
        contextMode: state.aiCeoTaskContextMode,
      };
    });
    if (
      storeSwitchReset.routeProjectId ||
      storeSwitchReset.draftPresent ||
      storeSwitchReset.reportCount ||
      storeSwitchReset.mediaCount ||
      storeSwitchReset.confirmationCount ||
      storeSwitchReset.executionCount ||
      storeSwitchReset.threadCount ||
      storeSwitchReset.supplierAttestationPresent ||
      storeSwitchReset.pendingAttachmentCount ||
      storeSwitchReset.mediaSourceUploadPresent ||
      storeSwitchReset.contextMode !== "plain_consultation"
    ) {
      throw new Error(`switching stores must clear the previous store project scope: ${JSON.stringify(storeSwitchReset)}`);
    }

    const staleStatusResponse = await page.evaluate(async () => {
      const storeA = { store_id: "store-a", store_name: "Store A", platform: "ebay", marketplace: "EBAY_US" };
      const storeB = { store_id: "store-b", store_name: "Store B", platform: "ebay", marketplace: "EBAY_US" };
      state.saasStores = [storeA, storeB];
      localStorage.setItem(saasStorageKeys.storeId, storeA.store_id);
      window.history.replaceState(window.history.state, "", `${window.location.pathname}?start=app&view=product&project=project-store-a`);
      state.view = "product";
      state.saasListingComposerDraft = {
        product: "Store A product",
        listing_project_identity: { key: "project-store-a", source_report_id: "report-store-a", candidate_id: "candidate-store-a" },
      };
      let releaseStatus;
      optionalSaasFetchFast = () => new Promise((resolve) => {
        releaseStatus = resolve;
      });
      const pendingStatus = refreshSaasMerchantProjectStatus({ store: storeA, projectId: "project-store-a" });
      await Promise.resolve();
      resetSaasActiveProjectForStoreSwitch();
      localStorage.setItem(saasStorageKeys.storeId, storeB.store_id);
      releaseStatus({
        merchant_project_status: {
          snapshot_version: "merchant_project_status_v1",
          project: { project_id: "project-store-a" },
        },
      });
      const result = await pendingStatus;
      return {
        resultPresent: Boolean(result),
        snapshotPresent: Boolean(state.saasMerchantProjectStatus),
        routeProjectId: new URLSearchParams(window.location.search).get("project") || "",
        activeStoreId: activeSaasStore()?.store_id || "",
      };
    });
    if (
      staleStatusResponse.resultPresent ||
      staleStatusResponse.snapshotPresent ||
      staleStatusResponse.routeProjectId ||
      staleStatusResponse.activeStoreId !== "store-b"
    ) {
      throw new Error(`a delayed status response from the previous store must be ignored: ${JSON.stringify(staleStatusResponse)}`);
    }

    const staleAttachmentUpload = await page.evaluate(async () => {
      const storeA = state.saasStores.find((store) => store.store_id === "store-a");
      const storeB = state.saasStores.find((store) => store.store_id === "store-b");
      localStorage.setItem(saasStorageKeys.storeId, storeA.store_id);
      window.history.replaceState(window.history.state, "", `${window.location.pathname}?start=app&view=cockpit&project=project-store-a`);
      state.view = "cockpit";
      state.saasListingComposerDraft = {
        product: "Store A product",
        listing_project_identity: { key: "project-store-a", source_report_id: "report-store-a", candidate_id: "candidate-store-a" },
      };
      let releaseUpload;
      uploadSaasMediaSourceFile = () => new Promise((resolve) => {
        releaseUpload = resolve;
      });
      const pendingUpload = handleSaasAiCeoAttachmentFiles([
        new File(["image"], "store-a.png", { type: "image/png" }),
      ]);
      await Promise.resolve();
      resetSaasActiveProjectForStoreSwitch();
      localStorage.setItem(saasStorageKeys.storeId, storeB.store_id);
      releaseUpload({ asset_id: "asset-store-a", original_filename: "store-a.png" });
      const result = await pendingUpload;
      return {
        result,
        attachmentCount: state.saasAiCeoPendingAttachments.length,
        uploading: state.saasAiCeoAttachmentUploading,
        activeStoreId: activeSaasStore()?.store_id || "",
        routeProjectId: new URLSearchParams(window.location.search).get("project") || "",
      };
    });
    if (
      staleAttachmentUpload.result !== false ||
      staleAttachmentUpload.attachmentCount ||
      staleAttachmentUpload.uploading ||
      staleAttachmentUpload.activeStoreId !== "store-b" ||
      staleAttachmentUpload.routeProjectId
    ) {
      throw new Error(`a delayed attachment upload from the previous store must not rebind: ${JSON.stringify(staleAttachmentUpload)}`);
    }

    const futureSnapshotPage = await browser.newPage();
    await futureSnapshotPage.goto(`${base}/app.html?start=app&qa=public-saas&saasApiBase=${encodeURIComponent(base)}`, { waitUntil: "load" });
    const futureSnapshotGuard = await futureSnapshotPage.evaluate(() => {
      window.__JIEJING_FORCE_PUBLIC_MVP__ = true;
      const accountKey = "future-snapshot-user";
      localStorage.setItem(saasStorageKeys.lastAccount, accountKey);
      localStorage.setItem(saasStorageKeys.sessionHint, "1");
      state.saasProtectedStateReady = false;
      const identity = {
        key: "future-snapshot-project",
        source_report_id: "future-snapshot-report",
        candidate_id: "future-snapshot-candidate",
      };
      localStorage.setItem(saasProtectedSnapshotStorageKey(), JSON.stringify({
        version: "2026-09-01-project-isolation-v4",
        saved_at: new Date(Date.now() + 24 * 60 * 60 * 1000).toISOString(),
        account_key: accountKey,
        store_id: "future-snapshot-store",
        connected: true,
        identity: { user_id: accountKey, company_id: "future-snapshot-company" },
        user: { user_id: accountKey },
        company: { company_id: "future-snapshot-company" },
        stores: [{ store_id: "future-snapshot-store", platform: "ebay", marketplace: "EBAY_US" }],
        listing_composer_draft: {
          product: "未来时间伪造草稿",
          title: "未来时间伪造草稿",
          listing_project_identity: identity,
        },
      }));
      const hydrated = hydrateSaasProtectedStateFromCache();
      return {
        hydrated,
        draftPresent: Boolean(state.saasListingComposerDraft),
        protectedReady: state.saasProtectedStateReady,
      };
    });
    await futureSnapshotPage.close();
    if (futureSnapshotGuard.hydrated || futureSnapshotGuard.draftPresent || futureSnapshotGuard.protectedReady) {
      throw new Error(`a protected snapshot dated materially in the future must be rejected: ${JSON.stringify(futureSnapshotGuard)}`);
    }

    const accountBoundaryPage = await browser.newPage();
    await accountBoundaryPage.goto(`${base}/app.html?start=app&qa=public-saas&project=account-a-project&saasApiBase=${encodeURIComponent(base)}`, { waitUntil: "load" });
    const accountBoundaryGuard = await accountBoundaryPage.evaluate(() => {
      window.__JIEJING_FORCE_PUBLIC_MVP__ = true;
      localStorage.setItem(saasStorageKeys.storeId, "account-a-store");
      state.saasIdentity = { user_id: "account-a", company_id: "account-a-company" };
      state.saasUser = { user_id: "account-a", email: "account-a@example.invalid" };
      state.saasCompany = { company_id: "account-a-company" };
      state.saasStores = [{ store_id: "account-a-store", platform: "ebay", marketplace: "EBAY_US" }];
      state.saasListingComposerDraft = {
        product: "账号 A 未保存商品",
        title: "账号 A 未保存商品",
        listing_project_identity: {
          key: "account-a-project",
          source_report_id: "account-a-report",
          candidate_id: "account-a-candidate",
        },
      };
      state.saasListingComposerInput = "账号 A 的未保存输入";
      state.saasListingSourceMode = "account_a_cache";
      state.saasDetachedListingProjectDrafts = {
        "account-a-project": {
          project_id: "account-a-project",
          company_id: "account-a-company",
          store_id: "account-a-store",
          saved_at: new Date().toISOString(),
          backend_report_at: new Date(Date.now() - 1000).toISOString(),
          draft: state.saasListingComposerDraft,
        },
      };
      state.saasPendingNewListingProjectRequest = { commandId: "account-a-command", phase: "pending" };
      const sameAccount = reconcileSaasCachedProjectStateForConfirmedAccount(
        ["account-b", "account-b@example.invalid"],
        new Set(["account-a", "account-a@example.invalid"]),
      );
      return {
        sameAccount,
        draftPresent: Boolean(state.saasListingComposerDraft),
        detachedCount: Object.keys(state.saasDetachedListingProjectDrafts || {}).length,
        pendingPresent: Boolean(state.saasPendingNewListingProjectRequest),
        composerInput: state.saasListingComposerInput || "",
        sourceMode: state.saasListingSourceMode || "",
        routeProjectId: new URLSearchParams(window.location.search).get("project") || "",
      };
    });
    await accountBoundaryPage.close();
    if (
      accountBoundaryGuard.sameAccount ||
      accountBoundaryGuard.draftPresent ||
      accountBoundaryGuard.detachedCount ||
      accountBoundaryGuard.pendingPresent ||
      accountBoundaryGuard.composerInput ||
      accountBoundaryGuard.sourceMode ||
      accountBoundaryGuard.routeProjectId
    ) {
      throw new Error(`a confirmed account change must clear cached project state before saving the new account snapshot: ${JSON.stringify(accountBoundaryGuard)}`);
    }

    const cachedDraftFreshnessPage = await browser.newPage();
    await cachedDraftFreshnessPage.goto(`${base}/app.html?start=app&qa=public-saas&project=cached-freshness-project&saasApiBase=${encodeURIComponent(base)}`, { waitUntil: "load" });
    const cachedDraftFreshnessGuard = await cachedDraftFreshnessPage.evaluate(() => {
      window.__JIEJING_FORCE_PUBLIC_MVP__ = true;
      const identity = {
        key: "cached-freshness-project",
        source_report_id: "cached-freshness-report",
        candidate_id: "cached-freshness-candidate",
      };
      const backendTimestamp = new Date(Date.now() - 60 * 1000).toISOString();
      localStorage.setItem(saasStorageKeys.storeId, "cached-freshness-store");
      state.saasIdentity = { user_id: "cached-freshness-user", company_id: "cached-freshness-company" };
      state.saasUser = { user_id: "cached-freshness-user", email: "cached-freshness@example.invalid" };
      state.saasCompany = { company_id: "cached-freshness-company" };
      state.saasStores = [{ store_id: "cached-freshness-store", platform: "ebay", marketplace: "EBAY_US" }];
      state.saasReports = [{
        report_id: identity.source_report_id,
        report_type: "ai_ceo.market_research",
        company_id: "cached-freshness-company",
        store_id: "cached-freshness-store",
        created_at: backendTimestamp,
        listing_project_identity: identity,
        report: {
          product_candidates: [{ candidate_id: identity.candidate_id, name: "最新后端平板支架", selected: true }],
          selected_product_candidate: { candidate_id: identity.candidate_id, name: "最新后端平板支架", selected: true },
          listing_project_identity: identity,
        },
      }];
      const cachedDraft = (title) => ({
        product: title,
        title,
        selected_product_candidate: { candidate_id: identity.candidate_id, name: title },
        listing_project_identity: identity,
      });
      state.saasListingComposerDraft = cachedDraft("陈旧顶层缓存草稿");
      state.saasListingSourceMode = "protected_snapshot_cache";
      state.saasDetachedListingProjectDrafts = {
        [identity.key]: {
          project_id: identity.key,
          company_id: "cached-freshness-company",
          store_id: "cached-freshness-store",
          saved_at: new Date().toISOString(),
          backend_report_at: new Date(Date.parse(backendTimestamp) - 60 * 60 * 1000).toISOString(),
          draft: cachedDraft("陈旧 detached 草稿"),
          input: "陈旧本机输入",
          source_mode: "local_unsaved_draft",
        },
      };
      pruneSaasDetachedListingProjectDraftsAgainstBackend();
      restoreSaasListingComposerDraftFromBackendReports({
        preferBackendLatest: true,
        restoreDetachedDraft: true,
      });
      const staleResult = {
        title: state.saasListingComposerDraft?.title || state.saasListingComposerDraft?.product || "",
        sourceMode: state.saasListingSourceMode || "",
      };

      state.saasListingComposerDraft = cachedDraft("同项目未保存本地编辑");
      state.saasListingComposerInput = "同项目未保存本地输入";
      state.saasListingSourceMode = "local_unsaved_draft";
      state.saasDetachedListingProjectDrafts = {};
      const protectedSnapshot = buildSaasProtectedStateSnapshot();
      state.saasDetachedListingProjectDrafts = Object.fromEntries(
        (protectedSnapshot.detached_listing_project_drafts || []).map((entry) => [entry.project_id, entry]),
      );
      state.saasListingComposerDraft = cachedDraft("需要由后端重新建立的顶层缓存");
      state.saasListingComposerInput = "";
      state.saasListingSourceMode = "protected_snapshot_cache";
      pruneSaasDetachedListingProjectDraftsAgainstBackend();
      restoreSaasListingComposerDraftFromBackendReports({
        preferBackendLatest: true,
        restoreDetachedDraft: true,
      });
      const matchingResult = {
        title: state.saasListingComposerDraft?.title || state.saasListingComposerDraft?.product || "",
        input: state.saasListingComposerInput || "",
        sourceMode: state.saasListingSourceMode || "",
        snapshotDetachedCount: (protectedSnapshot.detached_listing_project_drafts || []).length,
      };
      return { staleResult, matchingResult };
    });
    await cachedDraftFreshnessPage.close();
    if (
      /陈旧/.test(cachedDraftFreshnessGuard.staleResult.title) ||
      !/最新后端平板支架/.test(cachedDraftFreshnessGuard.staleResult.title) ||
      cachedDraftFreshnessGuard.matchingResult.snapshotDetachedCount !== 1 ||
      cachedDraftFreshnessGuard.matchingResult.title !== "同项目未保存本地编辑" ||
      cachedDraftFreshnessGuard.matchingResult.input !== "同项目未保存本地输入" ||
      cachedDraftFreshnessGuard.matchingResult.sourceMode !== "local_unsaved_draft"
    ) {
      throw new Error(`backend freshness must outrank stale cache while an exact-watermark local edit remains recoverable: ${JSON.stringify(cachedDraftFreshnessGuard)}`);
    }

    const pendingSnapshotPage = await browser.newPage();
    await pendingSnapshotPage.goto(`${base}/app.html?start=app&qa=public-saas&saasApiBase=${encodeURIComponent(base)}`, { waitUntil: "load" });
    const pendingSnapshotGuard = await pendingSnapshotPage.evaluate(() => {
      window.__JIEJING_FORCE_PUBLIC_MVP__ = true;
      localStorage.setItem(saasStorageKeys.sessionHint, "1");
      localStorage.setItem(saasStorageKeys.storeId, "store-resilience");
      state.saasConnected = true;
      state.saasProtectedStateReady = true;
      state.saasSessionExpiryHandled = false;
      state.saasSessionExpiryRedirected = false;
      state.saasIdentity = { user_id: "resilience-user", company_id: "resilience-company" };
      state.saasUser = { user_id: "resilience-user", email: "merchant@local.invalid" };
      state.saasCompany = { company_id: "resilience-company" };
      state.saasStores = [{ store_id: "store-resilience", platform: "ebay", marketplace: "EBAY_US" }];
      state.activeStore = "store-resilience";
      const rawText = "请新建一个全新的独立商品项目。目标商品：平板电脑支架。password=TOP_SECRET_SENTINEL";
      const command = buildSaasCeoCommand(rawText, saasMerchantWorkbenchContext());
      const envelope = buildSaasAiCeoChatRequestEnvelope(command, ["asset-pending-snapshot"], {
        suppressActiveListingContext: true,
        suppressConversationHistory: true,
        suppressSupplierFacts: true,
      });
      state.saasPendingNewListingProjectRequest = {
        commandId: "",
        originalText: rawText,
        previousProjectId: "listing-project-before-pending",
        sourceAssetIds: ["asset-pending-snapshot"],
        phase: "preparing",
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
      };
      const bound = bindSaasNewListingProjectRequestToCommand(command.id, envelope?.payload || null);
      state.saasPendingNewListingProjectRequest.reconcileAttempts = 2;
      const snapshot = buildSaasProtectedStateSnapshot();
      const restored = sanitizeSaasPendingNewListingProjectRequestSnapshot(
        snapshot.pending_new_listing_project_request,
        { companyId: "resilience-company", storeId: "store-resilience", restoring: true },
      );
      const wrongCompany = sanitizeSaasPendingNewListingProjectRequestSnapshot(
        snapshot.pending_new_listing_project_request,
        { companyId: "foreign-company", storeId: "store-resilience", restoring: true },
      );
      const wrongStore = sanitizeSaasPendingNewListingProjectRequestSnapshot(
        snapshot.pending_new_listing_project_request,
        { companyId: "resilience-company", storeId: "foreign-store", restoring: true },
      );
      const expiredActive = sanitizeSaasPendingNewListingProjectRequestSnapshot({
        ...snapshot.pending_new_listing_project_request,
        phase: "pending",
        createdAt: new Date(Date.now() - 31 * 60 * 1000).toISOString(),
        updatedAt: new Date(Date.now() - 31 * 60 * 1000).toISOString(),
      }, { companyId: "resilience-company", storeId: "store-resilience", restoring: true });
      const retainedFailed = sanitizeSaasPendingNewListingProjectRequestSnapshot({
        ...snapshot.pending_new_listing_project_request,
        phase: "failed",
        failureReason: "http_503",
        createdAt: new Date(Date.now() - 20 * 24 * 60 * 60 * 1000).toISOString(),
        updatedAt: new Date(Date.now() - 13 * 24 * 60 * 60 * 1000).toISOString(),
      }, { companyId: "resilience-company", storeId: "store-resilience", restoring: true });
      const expiredFailed = sanitizeSaasPendingNewListingProjectRequestSnapshot({
        ...snapshot.pending_new_listing_project_request,
        phase: "failed",
        failureReason: "http_503",
        createdAt: new Date(Date.now() - 20 * 24 * 60 * 60 * 1000).toISOString(),
        updatedAt: new Date(Date.now() - 15 * 24 * 60 * 60 * 1000).toISOString(),
      }, { companyId: "resilience-company", storeId: "store-resilience", restoring: true });
      state.saasPendingNewListingProjectRequest = expiredActive;
      const expiredResumeScheduled = resumeSaasUncertainNewListingProjectRequestAfterRefresh();
      state.saasListingComposerDraft = null;
      state.saasMerchantProjectStatus = null;
      syncSaasProjectRoute(state.view || "cockpit", { clearProject: true });
      state.saasReports = [{
        report_id: "legacy-report-without-store",
        report_type: "ai_ceo.market_research",
        created_at: new Date().toISOString(),
        listing_project_identity: {
          key: "legacy-project-without-store",
          source_report_id: "legacy-report-without-store",
          candidate_id: "legacy-candidate-without-store",
        },
        report: {
          product: "不应进入当前店铺的旧商品",
          listing_project_identity: {
            key: "legacy-project-without-store",
            source_report_id: "legacy-report-without-store",
            candidate_id: "legacy-candidate-without-store",
          },
        },
      }];
      const missingStoreActiveContext = saasAiCeoActiveListingContext();
      return {
        bound,
        version: snapshot.version,
        pendingPhase: snapshot.pending_new_listing_project_request?.phase || "",
        restoredPhase: restored?.phase || "",
        validKey: /^[A-Za-z0-9._:-]{8,160}$/.test(snapshot.pending_new_listing_project_request?.idempotencyKey || ""),
        wrongCompanyRestored: Boolean(wrongCompany),
        wrongStoreRestored: Boolean(wrongStore),
        maxReconcileAttempts: SAAS_NEW_LISTING_PROJECT_MAX_RECONCILE_ATTEMPTS,
        reconcileAttempts: Number(restored?.reconcileAttempts || 0),
        expiredActivePhase: expiredActive?.phase || "",
        expiredActiveReason: expiredActive?.failureReason || "",
        expiredActiveAttempts: Number(expiredActive?.reconcileAttempts || 0),
        retainedFailedReason: retainedFailed?.failureReason || "",
        expiredFailedPresent: Boolean(expiredFailed),
        expiredResumeScheduled,
        expiredResumeTimerPresent: Boolean(state.saasPendingNewListingProjectReconcileTimer),
        missingStoreActiveContextPresent: Boolean(missingStoreActiveContext),
        containsSecretSentinel: JSON.stringify(snapshot).includes("TOP_SECRET_SENTINEL"),
      };
    });
    await pendingSnapshotPage.close();
    if (
      !pendingSnapshotGuard.bound ||
      pendingSnapshotGuard.version !== "2026-09-01-project-isolation-idempotency-v5" ||
      pendingSnapshotGuard.pendingPhase !== "pending" ||
      pendingSnapshotGuard.restoredPhase !== "uncertain" ||
      !pendingSnapshotGuard.validKey ||
      pendingSnapshotGuard.wrongCompanyRestored ||
      pendingSnapshotGuard.wrongStoreRestored ||
      pendingSnapshotGuard.reconcileAttempts !== 2 ||
      pendingSnapshotGuard.expiredActivePhase !== "uncertain" ||
      pendingSnapshotGuard.expiredActiveReason ||
      pendingSnapshotGuard.expiredActiveAttempts !== pendingSnapshotGuard.maxReconcileAttempts ||
      pendingSnapshotGuard.retainedFailedReason !== "http_503" ||
      pendingSnapshotGuard.expiredFailedPresent ||
      pendingSnapshotGuard.expiredResumeScheduled ||
      pendingSnapshotGuard.expiredResumeTimerPresent ||
      pendingSnapshotGuard.missingStoreActiveContextPresent ||
      pendingSnapshotGuard.containsSecretSentinel
    ) {
      throw new Error(`pending new-project snapshot must be scope-bound, replayable, and secret-safe: ${JSON.stringify(pendingSnapshotGuard)}`);
    }

    const legacyPendingPage = await browser.newPage();
    await legacyPendingPage.goto(`${base}/app.html?start=app&qa=public-saas&saasApiBase=${encodeURIComponent(base)}`, { waitUntil: "load" });
    const legacyPendingGuard = await legacyPendingPage.evaluate(() => {
      window.__JIEJING_FORCE_PUBLIC_MVP__ = true;
      const accountKey = "legacy-pending-user";
      localStorage.setItem(saasStorageKeys.lastAccount, accountKey);
      localStorage.setItem(saasStorageKeys.sessionHint, "session-present");
      state.saasProtectedStateReady = false;
      localStorage.setItem(saasProtectedSnapshotStorageKey(), JSON.stringify({
        version: "2026-09-01-project-isolation-v4",
        saved_at: new Date().toISOString(),
        account_key: accountKey,
        store_id: "legacy-pending-store",
        connected: true,
        identity: { user_id: accountKey, company_id: "legacy-pending-company" },
        user: { user_id: accountKey },
        company: { company_id: "legacy-pending-company" },
        stores: [{ store_id: "legacy-pending-store", platform: "ebay", marketplace: "EBAY_US" }],
        pending_new_listing_project_request: { phase: "pending", commandId: "injected-command" },
      }));
      const hydrated = hydrateSaasProtectedStateFromCache();
      return { hydrated, pendingPresent: Boolean(state.saasPendingNewListingProjectRequest) };
    });
    await legacyPendingPage.close();
    if (!legacyPendingGuard.hydrated || legacyPendingGuard.pendingPresent) {
      throw new Error(`legacy snapshots must ignore injected pending requests: ${JSON.stringify(legacyPendingGuard)}`);
    }

    authMode = "valid";
    const idempotentReplayBodiesStart = chatBodies.length;
    newProjectChatControl = {
      responseMode: "in_progress_once",
      projectId: "listing-project-idempotent-tablet",
      reportId: "report-idempotent-tablet",
      candidateId: "candidate-idempotent-tablet",
      markRequestReceived: () => {},
      waitForResponseRelease: Promise.resolve(),
    };
    const idempotentReplayPage = await browser.newPage();
    await idempotentReplayPage.goto(`${base}/app.html?start=app&qa=public-saas&saasApiBase=${encodeURIComponent(base)}`, { waitUntil: "load" });
    const idempotentReplayState = await idempotentReplayPage.evaluate(async () => {
      window.__JIEJING_FORCE_PUBLIC_MVP__ = true;
      localStorage.setItem(saasStorageKeys.sessionHint, "1");
      localStorage.setItem(saasStorageKeys.storeId, "store-resilience");
      state.saasConnected = true;
      state.saasProtectedStateReady = true;
      state.saasSessionExpiryHandled = false;
      state.saasSessionExpiryRedirected = false;
      state.saasIdentity = { user_id: "resilience-user", company_id: "resilience-company" };
      state.saasUser = { user_id: "resilience-user", email: "merchant@local.invalid" };
      state.saasCompany = { company_id: "resilience-company" };
      state.saasStores = [{ store_id: "store-resilience", platform: "ebay", marketplace: "EBAY_US" }];
      state.activeStore = "store-resilience";
      const text = "请新建一个全新的独立商品项目。目标商品：折叠平板电脑支架。";
      const explicitIntent = saasExplicitNewListingProjectRequest(text);
      const submitted = handleSaasCeoCommandSubmit(text);
      await Promise.resolve(state.saasLastCeoCommandPersistPromise);
      return {
        explicitIntent,
        submitted: Boolean(submitted),
        connected: state.saasConnected,
        protectedCandidate: hasSaasProtectedSessionCandidate(),
        lastCommandId: state.saasLastCeoCommand?.id || "",
        projectId: saasCurrentMerchantProjectId(),
        pendingPresent: Boolean(state.saasPendingNewListingProjectRequest),
      };
    });
    await idempotentReplayPage.close();
    const idempotentReplayBodies = chatBodies.slice(idempotentReplayBodiesStart);
    newProjectChatControl = null;
    if (
      idempotentReplayBodies.length !== 2 ||
      JSON.stringify(idempotentReplayBodies[0]) !== JSON.stringify(idempotentReplayBodies[1]) ||
      !/^[A-Za-z0-9._:-]{8,160}$/.test(idempotentReplayBodies[0]?.idempotency_key || "") ||
      idempotentReplayState.projectId !== "listing-project-idempotent-tablet" ||
      idempotentReplayState.pendingPresent
    ) {
      throw new Error(`202 reconciliation must replay the exact frozen request once and commit one project: ${JSON.stringify({
        bodies: idempotentReplayBodies,
        state: idempotentReplayState,
      })}`);
    }

    const boundedReconcilePage = await browser.newPage();
    await boundedReconcilePage.goto(`${base}/app.html?start=app&qa=public-saas&saasApiBase=${encodeURIComponent(base)}`, { waitUntil: "load" });
    const boundedReconcileGuard = await boundedReconcilePage.evaluate(async () => {
      window.__JIEJING_FORCE_PUBLIC_MVP__ = true;
      localStorage.setItem(saasStorageKeys.sessionHint, "1");
      localStorage.setItem(saasStorageKeys.storeId, "store-resilience");
      state.saasConnected = true;
      state.saasProtectedStateReady = true;
      state.saasSessionExpiryHandled = false;
      state.saasSessionExpiryRedirected = false;
      state.saasIdentity = { user_id: "resilience-user", company_id: "resilience-company" };
      state.saasUser = { user_id: "resilience-user", email: "merchant@local.invalid" };
      state.saasCompany = { company_id: "resilience-company" };
      state.saasStores = [{ store_id: "store-resilience", platform: "ebay", marketplace: "EBAY_US" }];
      state.activeStore = "store-resilience";
      const runCase = async (suffix, payloadFactory) => {
        stopSaasPendingNewListingProjectReconciliation();
        state.saasPendingNewListingProjectRequest = null;
        state.saasReports = [];
        const text = `请新建一个全新的独立商品项目。目标商品：${suffix}平板支架。`;
        const prepared = prepareSaasNewListingProjectRequest(text, []);
        const attemptIdentity = saasNewListingProjectAttemptIdentity(text, [], suffix);
        const command = normalizeSaasCeoCommand({
          ...buildSaasCeoCommand(text, saasMerchantWorkbenchContext()),
          id: attemptIdentity.commandId,
          created_at: attemptIdentity.clientNow,
        });
        const frozen = buildSaasAiCeoChatRequestEnvelope(command, [], {
          idempotencyKey: attemptIdentity.idempotencyKey,
          clientNow: attemptIdentity.clientNow,
          suppressActiveListingContext: true,
          suppressConversationHistory: true,
          suppressSupplierFacts: true,
        })?.payload || null;
        const bound = prepared.active && bindSaasNewListingProjectRequestToCommand(command.id, frozen);
        state.saasPendingNewListingProjectRequest = {
          ...state.saasPendingNewListingProjectRequest,
          phase: "uncertain",
          reconcileAttempts: SAAS_NEW_LISTING_PROJECT_MAX_RECONCILE_ATTEMPTS - 1,
        };
        const expectedPayload = JSON.stringify(state.saasPendingNewListingProjectRequest?.requestPayload || null);
        const events = [];
        let replayPayload = "";
        const result = await runSaasPendingNewListingProjectReconcileAttempt({
          scheduleNext: false,
          reportsFetcher: async () => {
            events.push("reports");
            return { reports: [] };
          },
          chatRequester: async (_command, _hooks, _sourceAssetIds, requestOptions) => {
            events.push("replay");
            replayPayload = JSON.stringify(requestOptions?.frozenRequestPayload || null);
            return payloadFactory();
          },
        });
        const pendingKeyBeforeOrdinaryChat = state.saasPendingNewListingProjectRequest?.idempotencyKey || "";
        const ordinaryChatPreparation = prepareSaasNewListingProjectRequest("今天上海天气怎么样？", []);
        return {
          bound,
          expectedPayload,
          replayPayload,
          events,
          result,
          phase: state.saasPendingNewListingProjectRequest?.phase || "",
          failureReason: state.saasPendingNewListingProjectRequest?.failureReason || "",
          reconcileAttempts: Number(state.saasPendingNewListingProjectRequest?.reconcileAttempts || 0),
          timerPresent: Boolean(state.saasPendingNewListingProjectReconcileTimer),
          ordinaryChatActive: ordinaryChatPreparation.active === true,
          pendingKeyBeforeOrdinaryChat,
          pendingKeyAfterOrdinaryChat: state.saasPendingNewListingProjectRequest?.idempotencyKey || "",
        };
      };
      return {
        persistent202: await runCase("持续202", () => ({
          _http_status: 202,
          ai_ceo_chat_request: { status: "in_progress", retry_after_ms: 10 },
        })),
        networkUnknown: await runCase("网络未知", () => ({
          _transport_unknown: true,
          ai_ceo_chat: { status: "model_call_failed", answer: "网络结果未知" },
        })),
        backendOutcomeUnknown: await runCase("后端结果未知", () => ({
          _http_status: 409,
          execution_result_known: false,
          usage_consumed: null,
          ai_ceo_chat: { status: "request_outcome_unknown", answer: "执行结果需要先对账。" },
        })),
        maxAttempts: SAAS_NEW_LISTING_PROJECT_MAX_RECONCILE_ATTEMPTS,
      };
    });
    await boundedReconcilePage.close();
    for (const [label, record] of Object.entries({
      persistent202: boundedReconcileGuard.persistent202,
      networkUnknown: boundedReconcileGuard.networkUnknown,
      backendOutcomeUnknown: boundedReconcileGuard.backendOutcomeUnknown,
    })) {
      if (
        !record.bound ||
        record.expectedPayload !== record.replayPayload ||
        JSON.stringify(record.events) !== JSON.stringify(["reports", "replay"]) ||
        record.phase !== "uncertain" ||
        record.failureReason ||
        record.reconcileAttempts !== boundedReconcileGuard.maxAttempts ||
        record.timerPresent ||
        record.ordinaryChatActive ||
        !record.pendingKeyBeforeOrdinaryChat ||
        record.pendingKeyAfterOrdinaryChat !== record.pendingKeyBeforeOrdinaryChat ||
        record.result?.status !== "uncertain"
      ) {
        throw new Error(`${label} reconciliation must fetch reports, replay the exact frozen request, and remain uncertain without a new model attempt at the bounded limit: ${JSON.stringify(record)}`);
      }
    }

    const conflictBodiesStart = chatBodies.length;
    newProjectChatControl = {
      responseMode: "idempotency_conflict",
      markRequestReceived: () => {},
      waitForResponseRelease: Promise.resolve(),
    };
    const conflictPage = await browser.newPage();
    await conflictPage.goto(`${base}/app.html?start=app&qa=public-saas&saasApiBase=${encodeURIComponent(base)}`, { waitUntil: "load" });
    const conflictState = await conflictPage.evaluate(async () => {
      window.__JIEJING_FORCE_PUBLIC_MVP__ = true;
      localStorage.setItem(saasStorageKeys.sessionHint, "1");
      localStorage.setItem(saasStorageKeys.storeId, "store-resilience");
      state.saasConnected = true;
      state.saasProtectedStateReady = true;
      state.saasSessionExpiryHandled = false;
      state.saasSessionExpiryRedirected = false;
      state.saasIdentity = { user_id: "resilience-user", company_id: "resilience-company" };
      state.saasUser = { user_id: "resilience-user", email: "merchant@local.invalid" };
      state.saasCompany = { company_id: "resilience-company" };
      state.saasStores = [{ store_id: "store-resilience", platform: "ebay", marketplace: "EBAY_US" }];
      state.activeStore = "store-resilience";
      handleSaasCeoCommandSubmit("请新建一个全新的独立商品项目。目标商品：409 冲突测试支架。");
      await Promise.resolve(state.saasLastCeoCommandPersistPromise);
      return {
        pendingPhase: state.saasPendingNewListingProjectRequest?.phase || "",
        failureReason: state.saasPendingNewListingProjectRequest?.failureReason || "",
        reconcileAttempts: Number(state.saasPendingNewListingProjectRequest?.reconcileAttempts || 0),
      };
    });
    await conflictPage.close();
    const conflictBodies = chatBodies.slice(conflictBodiesStart);
    newProjectChatControl = null;
    if (
      conflictBodies.length !== 1 ||
      conflictState.pendingPhase !== "failed" ||
      conflictState.failureReason !== "ai_ceo_idempotency_payload_conflict" ||
      conflictState.reconcileAttempts !== 0
    ) {
      throw new Error(`a known 409 idempotency conflict must terminate without transport replay: ${JSON.stringify({
        bodies: conflictBodies,
        state: conflictState,
      })}`);
    }

    console.log("PASS jiejing_ai_ceo_frontend_resilience_smoke");
  } finally {
    if (browser) await browser.close();
    await new Promise((resolve) => server.close(resolve));
  }
}

main().catch((error) => {
  console.error(`FAIL ${error.message}`);
  process.exitCode = 1;
});
