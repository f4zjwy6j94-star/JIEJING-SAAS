#!/usr/bin/env node
/* Browser regression for AI CEO continuation, terminal session expiry, and
   market-report project identity hydration. The fixture is strictly local and
   never calls a model, FAL, eBay, payment, refund, OAuth, or platform write. */

const fs = require("fs");
const http = require("http");
const path = require("path");
const { chromium } = require("../output/codex-playwright-deps/node_modules/playwright-core");

const root = path.resolve(__dirname, "..");
const browserChannel = process.env.JIEJING_PLAYWRIGHT_CHANNEL || "chrome";
let authMode = "valid";
let chatResponseProjectId = "listing-project-resilience";
const counters = { me: 0, refresh: 0, chat: 0, history: 0 };
let lastChatBody = null;

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
      localStorage.setItem(saasStorageKeys.sessionHint, "session-present");
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
        error: state.saasError || "",
        redirects,
        publicMode: isSaasPublicMvpMode(),
        protectedRoute: isProtectedSaasAppRoute(),
        redirectFlag: state.saasSessionExpiryRedirected,
      };
    });
    if (!terminal.handled || !terminal.timerStopped || !terminal.syncStopped || terminal.sessionHintPresent || terminal.connected) {
      throw new Error(`terminal auth state was not cleared: ${JSON.stringify(terminal)}`);
    }
    if (terminal.redirects !== 1 || !/登录已失效/.test(terminal.error)) {
      throw new Error(`terminal auth feedback must be explicit and idempotent: ${JSON.stringify(terminal)}`);
    }
    if (counters.history !== 1 || counters.me !== 4 || counters.refresh !== 1 || counters.chat !== 3) {
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
