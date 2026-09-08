#!/usr/bin/env node
/* Browser contract: a merchant can generate a project-scoped AI Listing draft
   inside Jiejing. The UI preserves merchant edits, persists the report trace,
   survives reload, and triggers no eBay/payment action. */

const fs = require("fs");
const crypto = require("crypto");
const net = require("net");
const os = require("os");
const path = require("path");
const { spawn } = require("child_process");
const { chromium } = require("../output/codex-playwright-deps/node_modules/playwright-core");
const {
  assertSafeMutationBase,
  mappedIpv4Address,
  normalizedHostname,
} = require("./jiejing_browser_smoke_mutation_guard");

let base = String(process.env.JIEJING_TEST_BASE || "").trim();
const localStaticRoot = path.resolve(process.env.JIEJING_LOCAL_STATIC_ROOT || path.join(__dirname, ".."));
const browserChannel = process.env.JIEJING_PLAYWRIGHT_CHANNEL || "chrome";
const viewportWidth = Number(process.env.JIEJING_SMOKE_VIEWPORT_WIDTH || 1440);
const viewportHeight = Number(process.env.JIEJING_SMOKE_VIEWPORT_HEIGHT || 1000);
const ownedBackendTempPrefix = "jiejing-listing-ai-smoke-";

function assertLoopbackMutationBase(testBase) {
  const cleanBase = String(testBase || "").trim();
  const parsed = new URL(cleanBase);
  if (!["http:", "https:"].includes(parsed.protocol)) {
    throw new Error(`Listing AI browser smoke requires an HTTP(S) base: ${parsed.protocol}`);
  }
  if (parsed.username || parsed.password) {
    throw new Error("Listing AI browser smoke refuses credentials in JIEJING_TEST_BASE");
  }
  assertSafeMutationBase(cleanBase);
  const hostname = normalizedHostname(cleanBase);
  const effectiveHostname = mappedIpv4Address(hostname) || hostname;
  if (!["127.0.0.1", "localhost", "::1"].includes(effectiveHostname)) {
    throw new Error(`Listing AI browser smoke only permits a loopback base: ${effectiveHostname}`);
  }
  return parsed.origin;
}

function reserveLocalPort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.unref();
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      const port = address && typeof address === "object" ? address.port : 0;
      server.close((error) => (error ? reject(error) : resolve(port)));
    });
  });
}

async function waitForOwnedBackend(owned) {
  const deadline = Date.now() + 30000;
  while (Date.now() < deadline) {
    if (owned.spawnError) throw owned.spawnError;
    if (owned.child.exitCode !== null) {
      throw new Error(`isolated Listing AI backend exited before health check: ${owned.child.exitCode}`);
    }
    try {
      const response = await fetch(`${owned.backendBase}/health`, { cache: "no-store" });
      if (response.ok) return;
    } catch (_error) {
      // The isolated backend may still be initializing its temporary schema.
    }
    await new Promise((resolve) => setTimeout(resolve, 150));
  }
  throw new Error("isolated Listing AI backend did not become healthy within 30 seconds");
}

async function startOwnedBackend() {
  const tempParent = path.resolve(os.tmpdir());
  const tempRoot = fs.mkdtempSync(path.join(tempParent, ownedBackendTempPrefix));
  const owned = {
    backendBase: "",
    child: null,
    spawnError: null,
    tempParent,
    tempRoot,
  };
  try {
    const port = await reserveLocalPort();
    owned.backendBase = `http://127.0.0.1:${port}`;
    const python = process.env.JIEJING_TEST_PYTHON || (process.platform === "win32" ? "python" : "python3");
    owned.child = spawn(
      python,
      [
        path.join(localStaticRoot, "tools", "jiejing_saas_backend_cli.py"),
        "serve",
        "--db",
        path.join(tempRoot, "saas.sqlite"),
        "--runtime-db",
        path.join(tempRoot, "runtime.sqlite"),
        "--output-root",
        path.join(tempRoot, "output"),
        "--host",
        "127.0.0.1",
        "--port",
        String(port),
      ],
      {
        cwd: localStaticRoot,
        env: {
          ...process.env,
          JIEJING_SAAS_ENV: "test",
          JIEJING_SAAS_SESSION_SECRET: crypto.randomBytes(32).toString("hex"),
          JIEJING_PUBLIC_BASE_URL: owned.backendBase,
          JIEJING_DATABASE_ENGINE: "sqlite",
          JIEJING_DATABASE_ADAPTER: "sqlite-local",
          JIEJING_DATABASE_URL: "",
          JIEJING_QUEUE_PROVIDER: "local_worker",
          JIEJING_QUEUE_URL: "",
          JIEJING_EXECUTION_ADAPTER: "demo_no_platform_write",
          JIEJING_ALLOW_HERMES_ADAPTERS: "0",
          JIEJING_ENABLE_REAL_PLATFORM_WRITES: "0",
          JIEJING_EBAY_OAUTH_EXCHANGE_LIVE: "0",
          JIEJING_EBAY_TOKEN_REFRESH_LIVE: "0",
          JIEJING_EBAY_READ_ONLY_LIVE: "0",
          JIEJING_EBAY_WRITE_LIVE: "0",
          JIEJING_EBAY_DRAFT_SAVE_LIVE: "0",
          JIEJING_EBAY_CONTROLLED_PUBLISH_LIVE: "0",
          JIEJING_WECHAT_PAY_CHARGE_ALLOWED: "0",
          JIEJING_WECHAT_PAY_REFUND_ALLOWED: "0",
          JIEJING_VAULT_ENABLED: "0",
        },
        stdio: ["ignore", "pipe", "pipe"],
        windowsHide: true,
      },
    );
    owned.child.once("error", (error) => {
      owned.spawnError = error;
    });
    owned.child.stdout.resume();
    owned.child.stderr.resume();
    await waitForOwnedBackend(owned);
    return owned;
  } catch (error) {
    await stopOwnedBackend(owned);
    throw error;
  }
}

async function stopOwnedBackend(owned) {
  if (!owned) return;
  if (owned.child && owned.child.exitCode === null) {
    owned.child.kill();
    await Promise.race([
      new Promise((resolve) => owned.child.once("exit", resolve)),
      new Promise((resolve) => setTimeout(resolve, 5000)),
    ]);
    if (owned.child.exitCode === null) {
      owned.child.kill("SIGKILL");
      await Promise.race([
        new Promise((resolve) => owned.child.once("exit", resolve)),
        new Promise((resolve) => setTimeout(resolve, 2000)),
      ]);
    }
  }
  const resolvedRoot = path.resolve(owned.tempRoot);
  const expectedParent = path.resolve(owned.tempParent);
  if (path.dirname(resolvedRoot) !== expectedParent || !path.basename(resolvedRoot).startsWith(ownedBackendTempPrefix)) {
    throw new Error(`refusing to remove unexpected Listing AI smoke path: ${resolvedRoot}`);
  }
  fs.rmSync(resolvedRoot, { recursive: true, force: true });
}

async function api(pathname, { token = "", method = "GET", body } = {}) {
  const response = await fetch(`${base}${pathname}`, {
    method,
    cache: "no-store",
    headers: { "content-type": "application/json", ...(token ? { authorization: `Bearer ${token}` } : {}) },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
  const text = await response.text();
  const json = text ? JSON.parse(text) : null;
  if (!response.ok) throw new Error(`${method} ${pathname} failed: ${response.status} ${text.slice(0, 400)}`);
  return json;
}

async function waitForTimingGate(promise, label) {
  let timer;
  try {
    return await Promise.race([promise, new Promise((_, reject) => {
      timer = setTimeout(() => reject(new Error(`${label} did not reach the controlled timing gate`)), 10000);
    })]);
  } finally { clearTimeout(timer); }
}

async function waitForRefreshCompletion(promise, label) {
  let timer;
  try {
    // Full refresh includes sequential core/extended reads and a project read;
    // an optional endpoint alone has a 12-second budget. This is not the
    // 10-second deadline for arriving at an intentionally held response gate.
    return await Promise.race([promise, new Promise((_, reject) => {
      timer = setTimeout(() => reject(new Error(`${label} did not complete the full refresh`)), 60000);
    })]);
  } finally { clearTimeout(timer); }
}

async function verifySlowOptionalAuditRefresh(page, refresh) {
  const auditUrl = `${base}/audit-logs?limit=80`;
  const evidence = { hits: 0, elapsed_ms: null, original_status: null, response_consumed: false, handler_settled: false, cleanup_completed: false };
  let expectedAuditLogs;
  let delayTimer;
  let releaseDelay;
  let handler = Promise.resolve();
  let handlerError;
  const delayAudit = (route) => {
    if (route.request().method() !== "GET" || evidence.hits) return route.continue();
    evidence.hits += 1;
    const requestedAt = performance.now();
    handler = (async () => {
      try {
        const response = await route.fetch({ timeout: 15000 });
        evidence.original_status = response.status();
        expectedAuditLogs = (await response.json()).audit_logs;
        await new Promise((resolve) => {
          releaseDelay = resolve;
          delayTimer = setTimeout(resolve, Math.max(0, 10500 - (performance.now() - requestedAt)));
        });
        await route.fulfill({ response });
        evidence.elapsed_ms = Math.round(performance.now() - requestedAt);
      } catch (error) {
        handlerError = error;
        await route.abort().catch(() => {});
      } finally {
        evidence.handler_settled = true;
      }
    })();
    return handler;
  };
  await page.route(auditUrl, delayAudit);
  let refreshPromise;
  let failure;
  try {
    refreshPromise = refresh();
    await waitForRefreshCompletion(refreshPromise, "Refresh regression baseline");
  } catch (error) {
    failure = error;
  } finally {
    let cleanupTimer;
    try {
      // A timed-out wait does not cancel the real refresh. Let this one bounded
      // fixture response and its consumer finish before removing the route.
      await Promise.race([
        Promise.all([handler, Promise.resolve(refreshPromise).catch(() => {})]),
        new Promise((_, reject) => { cleanupTimer = setTimeout(() => reject(new Error("audit refresh fixture cleanup timed out")), 60000); }),
      ]);
      evidence.cleanup_completed = true;
    } catch (error) {
      failure ||= error;
    } finally {
      releaseDelay?.();
      clearTimeout(delayTimer);
      clearTimeout(cleanupTimer);
      await page.unroute(auditUrl, delayAudit);
    }
  }
  if (Array.isArray(expectedAuditLogs)) {
    evidence.response_consumed = await page.evaluate((expected) => {
      const consumed = state.saasAuditLogs !== window.__listingSlowAuditPriorArray &&
        JSON.stringify(state.saasAuditLogs) === expected;
      delete window.__listingSlowAuditPriorArray;
      return consumed;
    }, JSON.stringify(expectedAuditLogs));
  }
  if (!failure && (handlerError || evidence.hits !== 1 || evidence.original_status !== 200 ||
      evidence.elapsed_ms < 10000 || evidence.elapsed_ms >= 12000 || !evidence.response_consumed ||
      !evidence.handler_settled || !evidence.cleanup_completed)) {
    failure = new Error("slow optional audit response was not consumed within its existing 12-second contract");
  }
  if (failure) {
    failure.audit_refresh_timing = evidence;
    throw failure;
  }
  return evidence;
}

function localStaticPath(requestUrl) {
  const url = new URL(requestUrl);
  const pathname = decodeURIComponent(url.pathname.replace(/^\/+/, "")) || "index.html";
  const allowed = ["app.html", "index.html", "app.js", "styles.css"].includes(pathname) || pathname.startsWith("assets/");
  if (!allowed) return "";
  const candidate = path.resolve(localStaticRoot, pathname);
  const relative = path.relative(localStaticRoot, candidate);
  return relative.startsWith("..") || path.isAbsolute(relative) ? "" : candidate;
}

function contentTypeFor(filePath) {
  const ext = path.extname(filePath).toLowerCase();
  if (ext === ".html") return "text/html; charset=utf-8";
  if (ext === ".css") return "text/css; charset=utf-8";
  if (ext === ".js") return "text/javascript; charset=utf-8";
  if (ext === ".svg") return "image/svg+xml";
  if (ext === ".webp") return "image/webp";
  if (ext === ".png") return "image/png";
  if (ext === ".jpg" || ext === ".jpeg") return "image/jpeg";
  return "application/octet-stream";
}

function generatedPayload(requestBody, storeId) {
  const identity = requestBody.listing_project_identity || {};
  const packet = requestBody.merchant_product_fact_packet || {};
  const current = requestBody.current_draft_fields || {};
  const product = packet.product_name || packet.merchant_confirmed_facts?.product_name || "Zen Incense Burner";
  const title = current.title || "AI Zen Lotus Backflow Incense Burner";
  const description = current.description || "AI buyer-facing description grounded in merchant facts.";
  const report = {
    report_id: "report-browser-listing-ai-1",
    task_id: "task-browser-listing-ai-1",
    runtime_run_id: "listing_draft_generation",
    report_type: "listing.package",
    title: `Listing 草稿 v1：${product}`,
    status: "saved",
    created_at: new Date().toISOString(),
    report: {
      contract_version: "listing_ai_draft_generation_v1",
      artifact_type: "listing.package",
      version: 1,
      product,
      listing_project_identity: identity,
      merchant_product_fact_packet: packet,
      listing_handoff: {
        ready_for_listing_draft: true,
        source_mode: "project_scoped_live_model",
        target_report_type: "listing.package",
        triggers_real_platform_write: false,
        real_platform_writes_enabled: false,
        listing_fields: {
          contract_version: "listing_ai_draft_generation_v1",
          title,
          selling_points: ["Lotus hand silhouette", "Backflow smoke display", "Resin construction"],
          description_seed: description,
          category_id: "20682",
          category_suggestion: "Incense Holders",
          condition: "NEW",
          quantity: "3",
          item_specifics: { Material: ["Resin"], Type: ["Backflow Incense Burner"] },
          merchant_product_fact_packet: packet,
          ebay_inventory_item_draft: {
            sku: "JJ-ZEN-BROWSER-01",
            condition: "NEW",
            product: {
              title,
              description,
              aspects: { Material: ["Resin"], Type: ["Backflow Incense Burner"] },
              imageUrls: [],
            },
            availability: { shipToLocationAvailability: { quantity: 3 } },
          },
          ebay_offer_draft: {
            categoryId: "20682",
            marketplaceId: "EBAY_US",
            listingDescription: description,
            listingPolicies: {},
            pricingSummary: { price: { value: "", currency: "USD" } },
          },
          listing_readiness: { ready_for_real_publish: false, reason: "草稿已生成，发布前仍需体检。" },
          draft_source: "project_scoped_live_model",
          ready_for_listing_draft: true,
          triggers_real_platform_write: false,
          real_platform_writes_enabled: false,
          secret_exposed: false,
        },
      },
      missing_fields: ["sku", "selling_price", "image_urls"],
      requires_human_review_before_publish: true,
      real_platform_writes_enabled: false,
      secret_exposed: false,
    },
    secret_exposed: false,
  };
  return {
    status: "completed",
    task: {
      task_id: report.task_id,
      store_id: storeId,
      task_type: "listing_draft_generation",
      title: `AI Listing 草稿：${product}`,
      status: "completed",
      created_at: report.created_at,
      input: { listing_project_identity: identity, real_platform_writes_enabled: false, secret_exposed: false },
      output: { report_id: report.report_id, model_called: true, real_platform_writes_enabled: false, secret_exposed: false },
    },
    report,
    listing_project_identity: identity,
    missing_fields: report.report.missing_fields,
    model_called: true,
    usage_consumed: true,
    real_platform_writes_enabled: false,
    secret_exposed: false,
  };
}

async function runListingFocusSmoke() {
  const suffix = `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  const registered = await api("/auth/register", {
    method: "POST",
    body: { email: `listing-focus-${suffix}@local.invalid`, password: `Listing-focus-${suffix}`, company_name: "Local Listing Focus" },
  });
  const store = (await api("/stores", {
    token: registered.token, method: "POST",
    body: { platform: "ebay", store_name: "Local Focus Store", marketplace: "EBAY_US" },
  })).store;
  const browser = await chromium.launch({ channel: browserChannel, headless: true });
  const externalRequests = [];
  const unsafeRequests = [];
  const pageErrors = [];
  let heldReports = null;
  let holdReports = false;
  let reportsReady = null;
  let markReportsReady = null;
  try {
    const context = await browser.newContext({ viewport: { width: viewportWidth, height: viewportHeight } });
    await context.addCookies([{ name: "jiejing_saas_session", value: registered.token,
      domain: new URL(base).hostname, path: "/", httpOnly: true, secure: new URL(base).protocol === "https:", sameSite: "Lax" }]);
    await context.addInitScript(({ apiBase, accountKey, storeId }) => {
      localStorage.setItem("jiejing_saas_api_base", apiBase);
      localStorage.setItem("jiejing_saas_backend_session_hint", "1");
      localStorage.setItem("jiejing_saas_session_hint", "1");
      localStorage.setItem("jiejing_saas_last_account", accountKey);
      localStorage.setItem("jiejing_saas_backend_store_id", storeId);
      localStorage.setItem(`jiejing_saas_onboarding_done:${accountKey}`, "1");
      window.__JIEJING_FORCE_PUBLIC_MVP__ = true;
    }, { apiBase: base, accountKey: String(registered.user.user_id).toLowerCase(), storeId: store.store_id });
    await context.route("**/*", async (route) => {
      const request = route.request();
      const url = new URL(request.url());
      if (url.origin !== base) { externalRequests.push(url.origin); return route.abort(); }
      if (request.method() !== "GET" && /oauth|publish|checkout|refund|media-asset-jobs|listing-drafts\/generate/i.test(url.pathname)) {
        unsafeRequests.push(`${request.method()} ${url.pathname}`);
        return route.abort();
      }
      if (holdReports && request.method() === "GET" && url.pathname === "/reports" && url.searchParams.get("limit") === "24") {
        holdReports = false;
        const response = await route.fetch();
        await new Promise((resolve) => { heldReports = { route, response, resolve }; markReportsReady(); });
        return;
      }
      const filePath = localStaticPath(request.url());
      if (filePath && fs.existsSync(filePath)) return route.fulfill({ status: 200, contentType: contentTypeFor(filePath), body: fs.readFileSync(filePath) });
      return route.continue();
    });
    const page = await context.newPage();
    page.on("pageerror", (error) => pageErrors.push(error.message));
    await page.goto(`${base}/app.html?start=app&view=product`, { waitUntil: "domcontentloaded" });
    await page.waitForFunction(() => typeof state !== "undefined" && state.saasProtectedStateReady && !state.saasLoading, null, { timeout: 60000 });
    await page.evaluate(async () => { await refreshSaasState({ silent: true }); setView("product", { listingMode: "single" }); });
    await page.fill('[data-source-manual-field="product_name"]', "Local Focus Tablet Stand");
    await page.fill('[data-source-manual-field="material"]', "Aluminum");
    await page.selectOption('[data-source-manual-field="condition"]', "NEW");
    const factsSaved = page.waitForResponse((response) => response.request().method() === "POST" && response.url().includes("/product-facts") && response.status() === 201);
    await page.click('[data-saas-action="save-new-product-facts"]');
    await factsSaved;
    await page.waitForSelector('[data-saas-listing-draft-field="title"]');
    await page.evaluate(async () => { await refreshSaasState({ silent: true }); await saasListingCloudRecord()?.read; });

    for (const field of ["title", "description"]) {
      reportsReady = new Promise((resolve) => { markReportsReady = resolve; });
      holdReports = true;
      await page.evaluate(() => { window.__listingFocusRefresh = refreshSaasState({ silent: true }); });
      await waitForTimingGate(reportsReady, `Focused ${field} refresh response`);
      const input = page.locator(`[data-saas-listing-draft-field="${field}"]`);
      await input.focus();
      const before = await input.evaluate((element) => {
        element.setSelectionRange(2, Math.min(8, element.value.length), "forward");
        return { value: element.value, start: element.selectionStart, end: element.selectionEnd, direction: element.selectionDirection };
      });
      if (heldReports.response.status() !== 200) throw new Error("focus regression did not receive a real local reports response");
      await heldReports.route.fulfill({ response: heldReports.response });
      heldReports.resolve();
      heldReports = null;
      await waitForRefreshCompletion(page.evaluate(() => window.__listingFocusRefresh), `Focused ${field} refresh completion`);
      const after = await input.evaluate((element) => ({
        value: element.value, focused: document.activeElement === element,
        start: element.selectionStart, end: element.selectionEnd, direction: element.selectionDirection,
      }));
      if (!after.focused || after.value !== before.value || after.start !== before.start || after.end !== before.end || after.direction !== before.direction) {
        throw new Error(`background refresh must preserve same-project ${field} focus and selection: ${JSON.stringify({ before, after })}`);
      }
      await page.keyboard.insertText("Edited");
      const expected = before.value.slice(0, before.start) + "Edited" + before.value.slice(before.end);
      const received = await page.evaluate((key) => ({
        dom: document.querySelector(`[data-saas-listing-draft-field="${key}"]`)?.value,
        draft: state.saasListingComposerDraft?.fields?.[key], cloud: saasListingCloudRecord()?.fields?.[key],
        edited: saasListingMerchantEditedFields().includes(key),
      }), field);
      if (received.dom !== expected || received.draft !== expected || received.cloud !== expected || !received.edited) {
        throw new Error(`native ${field} input after refresh was not received by the editor and checkpoint: ${JSON.stringify(received)}`);
      }
    }
    await page.evaluate(async () => { await flushSaasListingCloudCheckpoint(); });
    const renderEffects = await page.evaluate(() => {
      const view = document.querySelector("#view-product");
      const input = view.querySelector('[data-saas-listing-draft-field="title"]');
      input.focus();
      input.setSelectionRange(1, 4);
      const before = { title: input.value, seq: saasListingCloudRecord()?.seq };
      const events = [];
      const recordEvent = (event) => {
        if (event.target.matches?.("[data-saas-listing-draft-field]")) events.push(event.type);
      };
      view.addEventListener("input", recordEvent);
      view.addEventListener("change", recordEvent);
      try {
        renderProductListingCenter();
        const unchanged = view.querySelector('[data-saas-listing-draft-field="title"]');
        const sameValue = unchanged.value === before.title;
        // A newer field value is already in application state before rendering.
        // Focus restoration may not merge the old DOM value back into it.
        const expected = "Newer cloud checkpoint title";
        state.saasListingComposerDraft.fields.title = expected;
        renderProductListingCenter();
        const current = view.querySelector('[data-saas-listing-draft-field="title"]');
        return { sameValue, expected, title: current.value, draft: state.saasListingComposerDraft.fields.title,
          focused: document.activeElement === current, beforeSeq: before.seq,
          afterSeq: saasListingCloudRecord()?.seq, events };
      } finally {
        view.removeEventListener("input", recordEvent);
        view.removeEventListener("change", recordEvent);
      }
    });
    if (!renderEffects.sameValue || !renderEffects.focused || renderEffects.title !== renderEffects.expected ||
        renderEffects.draft !== renderEffects.expected || renderEffects.beforeSeq !== renderEffects.afterSeq || renderEffects.events.length) {
      throw new Error(`same-project rendering must not restore stale values or synthesize merchant edits: ${JSON.stringify(renderEffects)}`);
    }
    const scopeCases = await page.evaluate(() => {
      const baseline = JSON.parse(JSON.stringify({
        identity: state.saasIdentity, user: state.saasUser, company: state.saasCompany,
        stores: state.saasStores, activeStore: state.activeStore,
        storedStoreId: storedSaasStoreId(),
        draft: state.saasListingComposerDraft, sourceMode: state.saasListingSourceMode,
      }));
      const results = [];
      for (const kind of ["user", "company", "store", "project", "source_report", "candidate", "epoch"]) {
        invalidateSaasListingCloudCheckpointContext();
        state.saasIdentity = { ...baseline.identity };
        state.saasUser = { ...baseline.user };
        state.saasCompany = { ...baseline.company };
        state.saasStores = baseline.stores.map((store) => ({ ...store }));
        state.activeStore = baseline.activeStore;
        localStorage.setItem(saasStorageKeys.storeId, baseline.storedStoreId);
        state.saasListingComposerDraft = JSON.parse(JSON.stringify(baseline.draft));
        state.saasListingSourceMode = baseline.sourceMode;
        renderProductListingCenter();
        const previousInput = document.querySelector('[data-saas-listing-draft-field="title"]');
        previousInput.focus();
        previousInput.setSelectionRange(1, 4);
        const beforeScope = saasProductFactEditorScope();
        const beforeStoreId = activeSaasStore()?.store_id;
        if (kind === "user") {
          state.saasIdentity.user_id = "local-focus-other-user";
          state.saasUser.user_id = "local-focus-other-user";
        } else if (kind === "company") {
          state.saasIdentity.company_id = "local-focus-other-company";
          state.saasCompany.company_id = "local-focus-other-company";
        } else if (kind === "store") {
          state.saasStores = [{ ...state.saasStores[0], store_id: "local-focus-other-store" }];
          state.activeStore = "local-focus-other-store";
          localStorage.setItem(saasStorageKeys.storeId, "local-focus-other-store");
        } else if (kind === "project") {
          state.saasListingComposerDraft.listing_project_identity.key = "local-focus-other-project";
          state.saasListingComposerDraft.listing_project_key = "local-focus-other-project";
        } else if (kind === "source_report") {
          state.saasListingComposerDraft.listing_project_identity.source_report_id = "local-focus-other-source";
        } else if (kind === "candidate") {
          state.saasListingComposerDraft.listing_project_identity.candidate_id = "local-focus-other-candidate";
        } else {
          resetSaasListingProjectTransientState();
        }
        const expected = `New ${kind} scope title`;
        state.saasListingComposerDraft.fields.title = expected;
        const scopeChanged = beforeScope !== saasProductFactEditorScope();
        const storeChanged = kind !== "store" || beforeStoreId !== activeSaasStore()?.store_id;
        renderProductListingCenter();
        const currentInput = document.querySelector('[data-saas-listing-draft-field="title"]');
        results.push({ kind, expected, title: currentInput?.value, scopeChanged, storeChanged,
          stoleFocus: document.activeElement === currentInput, previousConnected: previousInput.isConnected });
      }
      invalidateSaasListingCloudCheckpointContext();
      return results;
    });
    for (const result of scopeCases) {
      if (!result.scopeChanged || !result.storeChanged || result.stoleFocus || result.previousConnected || result.title !== result.expected) {
        throw new Error(`changed ${result.kind} scope must not transfer editor focus or restore old values: ${JSON.stringify(result)}`);
      }
    }
    const inactiveCases = await page.evaluate(() => {
      const results = [];
      for (const kind of ["other_view", "bulk", "recent", "disabled", "readonly", "loading"]) {
        state.view = "product";
        state.saasListingMode = "single";
        state.saasLoading = false;
        renderProductListingCenter();
        const previous = document.querySelector('[data-saas-listing-draft-field="title"]');
        previous.focus();
        previous.setSelectionRange(1, 4);
        if (kind === "other_view") state.view = "connect";
        else if (["bulk", "recent"].includes(kind)) state.saasListingMode = kind;
        else if (kind === "disabled") previous.disabled = true;
        else if (kind === "readonly") previous.readOnly = true;
        else state.saasLoading = true;
        renderProductListingCenter();
        const current = document.querySelector('[data-saas-listing-draft-field="title"]');
        results.push({ kind, focused: Boolean(current && document.activeElement === current),
          editable: Boolean(current && !current.disabled && !current.readOnly), previousConnected: previous.isConnected });
      }
      invalidateSaasListingCloudCheckpointContext();
      return results;
    });
    for (const result of inactiveCases) {
      // Loading does not disable the Listing fields: merchants may keep typing
      // while generation runs, and that existing behavior must remain usable.
      const expectedFocus = result.kind === "loading";
      if (result.focused !== expectedFocus || result.previousConnected || (expectedFocus && !result.editable)) {
        throw new Error(`editor ${result.kind} focus did not follow actual editability: ${JSON.stringify(result)}`);
      }
    }
    if (externalRequests.length || unsafeRequests.length || pageErrors.length) throw new Error(`focus smoke boundary failure: ${JSON.stringify({ externalRequests, unsafeRequests, pageErrors })}`);
    console.log(`PASS listing_focus_refresh_title_description_${scopeCases.length}_scope_boundaries_${inactiveCases.length - 1}_inactive_boundaries_loading_editable_no_value_or_edit_side_effects`);
  } finally {
    heldReports?.resolve();
    await browser.close();
  }
}

async function runSmoke() {
  const suffix = `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  const email = `codex-listing-ai-${suffix}@local.invalid`;
  const registered = await api("/auth/register", {
    method: "POST",
    body: { email, password: `Codex-listing-ai-${suffix}`, company_name: "Codex Listing AI" },
  });
  const token = registered.token;
  const user = registered.user || {};
  const store = (
    await api("/stores", {
      token,
      method: "POST",
      body: { platform: "ebay", store_name: "Listing AI Store", marketplace: "EBAY_US" },
    })
  ).store;
  const otherStore = (
    await api("/stores", {
      token,
      method: "POST",
      body: { platform: "ebay", store_name: "Other Listing Store", marketplace: "EBAY_US" },
    })
  ).store;

  let capturedGenerationBody = null;
  let holdGeneration = false;
  let heldGeneration = null;
  let generationRequestCount = 0;
  let initialCloudReadHeld = false;
  let resolveInitialCloudRead;
  const initialCloudRead = new Promise((resolve) => { resolveInitialCloudRead = resolve; });
  let resolveInitialGeneration;
  const initialGeneration = new Promise((resolve) => { resolveInitialGeneration = resolve; });
  let browser = null;
  try {
  browser = await chromium.launch({ channel: browserChannel, headless: true });
  const context = await browser.newContext({ viewport: { width: viewportWidth, height: viewportHeight }, deviceScaleFactor: 1 });
  const baseUrl = new URL(base);
  await context.addCookies([
    {
      name: "jiejing_saas_session",
      value: token,
      domain: baseUrl.hostname,
      path: "/",
      httpOnly: true,
      secure: baseUrl.protocol === "https:",
      sameSite: "Lax",
    },
  ]);
  await context.route(`${base}/**`, async (route) => {
    const request = route.request();
    // Exercise a real checkpoint response arriving during generation. This
    // previously mistook the checkpoint's missing-to-empty field normalization
    // for new merchant edits and left the generated package unapplied.
    if (!initialCloudReadHeld && request.method() === "GET" && /\/checkpoint(?:\?|$)/.test(request.url())) {
      initialCloudReadHeld = true;
      const response = await route.fetch();
      await new Promise((resolve) => { resolveInitialCloudRead({ route, response, resolve }); });
      return;
    }
    const generationStore = new URL(request.url()).pathname.match(/^\/stores\/([^/]+)\/listing-drafts\/generate$/);
    if (request.method() === "POST" && generationStore) {
      generationRequestCount += 1;
      capturedGenerationBody = JSON.parse(request.postData() || "{}");
      if (generationRequestCount === 1) {
        await new Promise((resolve) => { resolveInitialGeneration({ route, resolve }); });
        return;
      }
      if (holdGeneration) {
        await new Promise((resolve) => {
          heldGeneration = { route, body: capturedGenerationBody, storeId: decodeURIComponent(generationStore[1]), resolve };
        });
        return;
      }
      return route.fulfill({
        status: 201,
        contentType: "application/json; charset=utf-8",
        body: JSON.stringify(generatedPayload(capturedGenerationBody, store.store_id)),
      });
    }
    const filePath = localStaticPath(request.url());
    if (!filePath || !fs.existsSync(filePath)) return route.continue();
    return route.fulfill({
      status: 200,
      contentType: contentTypeFor(filePath),
      headers: { "cache-control": "no-store" },
      body: fs.readFileSync(filePath),
    });
  });
  const accountKey = String(user.user_id || email).toLowerCase();
  await context.addInitScript(
    (seed) => {
      localStorage.setItem("jiejing_saas_api_base", seed.base);
      localStorage.setItem("jiejing_saas_backend_session_hint", "1");
      localStorage.setItem("jiejing_saas_session_hint", "1");
      localStorage.setItem("jiejing_saas_last_account", seed.accountKey);
      localStorage.setItem("jiejing_saas_backend_store_id", seed.storeId);
      localStorage.setItem(`jiejing_saas_onboarding_done:${seed.accountKey}`, "1");
      window.__JIEJING_FORCE_PUBLIC_MVP__ = true;
    },
    { base, accountKey, storeId: store.store_id },
  );

  const page = await context.newPage();
  const pageErrors = [];
  const unsafeRequests = [];
  page.on("pageerror", (error) => pageErrors.push(String(error.message || error)));
  page.on("request", (request) => {
    if (/oauth|publish|checkout|refund|media-asset-jobs/i.test(request.url()) && request.method() !== "GET") {
      unsafeRequests.push(`${request.method()} ${request.url()}`);
    }
  });

  await page.goto(`${base}/app.html?start=app&view=product`, { waitUntil: "domcontentloaded" });
  await page.waitForFunction(
    () => typeof state !== "undefined" && state.saasProtectedStateReady === true && state.saasLoading === false,
    null,
    { timeout: 60000 },
  );
  await page.evaluate(() => setView("product", { listingMode: "single" }));
  await page.waitForSelector('[data-source-manual-field="product_name"]', { timeout: 20000 });
  await page.fill('[data-source-manual-field="product_name"]', "Zen Lotus Hand Backflow Incense Burner");
  await page.fill('[data-source-manual-field="material"]', "Resin");
  await page.selectOption('[data-source-manual-field="condition"]', "NEW");
  const factsSaved = page.waitForResponse(
    (response) => response.request().method() === "POST" && response.url().includes("/product-facts") && response.status() === 201,
    { timeout: 20000 },
  );
  await page.click('[data-saas-action="save-new-product-facts"]');
  await factsSaved;

  await page.waitForSelector('[data-saas-listing-draft-field="title"]', { timeout: 20000 });
  await page.fill('[data-saas-listing-draft-field="title"]', "Merchant Edited Zen Lotus Incense Burner");
  await page.fill('[data-saas-listing-draft-field="selling_points"]', "Merchant first point\nMerchant second point\nMerchant third point");
  await page.fill('[data-saas-listing-draft-field="description"]', "Merchant-confirmed description must remain unchanged.");
  const generationResponse = page.waitForResponse(
    (response) => response.request().method() === "POST" && response.url().includes("/listing-drafts/generate") && response.status() === 201,
    { timeout: 20000 },
  );
  await page.click('[data-saas-action="listing-generate-ai-draft"]');
  const firstGeneration = await waitForTimingGate(initialGeneration, "Listing generation");
  const firstCloudRead = await waitForTimingGate(initialCloudRead, "Initial checkpoint read");
  await firstCloudRead.route.fulfill({ response: firstCloudRead.response });
  firstCloudRead.resolve();
  await page.evaluate(async () => { await saasListingCloudRecord()?.read; });
  await firstGeneration.route.fulfill({
    status: 201,
    contentType: "application/json; charset=utf-8",
    body: JSON.stringify(generatedPayload(capturedGenerationBody, store.store_id)),
  });
  firstGeneration.resolve();
  await generationResponse;
  await page.waitForFunction(
    () => state.saasListingAiGenerationStatus === "completed" && state.saasLoading === false &&
      !saasListingAiGenerationInFlight.has(saasListingAiGenerationContextKey()) &&
      document.querySelector('[data-saas-listing-draft-field="title"]')?.value === "Merchant Edited Zen Lotus Incense Burner",
    null,
    { timeout: 20000 },
  );

  if (!capturedGenerationBody?.listing_project_identity?.key) throw new Error("Listing AI request missed project identity");
  if (capturedGenerationBody?.merchant_product_fact_packet?.merchant_confirmed_facts?.material !== "Resin") {
    throw new Error("Listing AI request missed merchant-confirmed material");
  }
  if (capturedGenerationBody?.current_draft_fields?.title !== "Merchant Edited Zen Lotus Incense Burner") {
    throw new Error("Listing AI request did not preserve the merchant-edited title");
  }
  if (capturedGenerationBody?.current_draft_fields?.selling_points !== "Merchant first point\nMerchant second point\nMerchant third point") {
    throw new Error("Listing AI request cleared existing selling points before receiving a model result");
  }
  const merchantEditedFields = capturedGenerationBody?.current_draft_fields?.merchant_edited_fields || [];
  if (!merchantEditedFields.includes("title") || !merchantEditedFields.includes("description")) {
    throw new Error(`Listing AI request lost explicit merchant-edit provenance: ${JSON.stringify(merchantEditedFields)}`);
  }
  if (/api_key|secret_ref|secret_value|access_token|refresh_token|password/i.test(JSON.stringify(capturedGenerationBody))) {
    throw new Error("Listing AI request contained credential-shaped fields");
  }
  const savedTrace = await page.evaluate(() => ({
    report: (state.saasReports || []).find((item) => item.report_id === "report-browser-listing-ai-1") || null,
    task: (state.saasTasks || []).find((item) => item.task_id === "task-browser-listing-ai-1") || null,
    sourceMode: state.saasListingSourceMode,
  }));
  if (!savedTrace.report || !savedTrace.task || savedTrace.sourceMode !== "listing_ai_generation") {
    throw new Error(`Listing AI trace was not stored in merchant state: ${JSON.stringify(savedTrace)}`);
  }

  await page.reload({ waitUntil: "domcontentloaded" });
  await page.waitForFunction(
    () => typeof state !== "undefined" && state.saasProtectedStateReady === true && state.saasLoading === false,
    null,
    { timeout: 60000 },
  );
  await page.evaluate(() => setView("product", { listingMode: "single" }));
  await page.waitForSelector('[data-saas-listing-draft-field="title"]', { timeout: 20000 });
  const restoredTitle = await page.inputValue('[data-saas-listing-draft-field="title"]');
  const restoredDescription = await page.inputValue('[data-saas-listing-draft-field="description"]');
  if (restoredTitle !== "Merchant Edited Zen Lotus Incense Burner") throw new Error("AI Listing title did not survive reload");
  if (restoredDescription !== "Merchant-confirmed description must remain unchanged.") {
    throw new Error("AI Listing description did not survive reload");
  }
  const layout = await page.evaluate(() => ({
    viewport_width: window.innerWidth,
    scroll_width: document.documentElement.scrollWidth,
    clipped_controls: Array.from(document.querySelectorAll("#view-product button, #view-product input, #view-product textarea, #view-product select"))
      .filter((item) => item.offsetParent !== null)
      .filter((item) => {
        const rect = item.getBoundingClientRect();
        return rect.width > 0 && (rect.left < -2 || rect.right > window.innerWidth + 2);
      }).length,
  }));
  if (layout.scroll_width > layout.viewport_width + 2 || layout.clipped_controls) {
    throw new Error(`Listing AI workflow overflows the viewport: ${JSON.stringify(layout)}`);
  }

  // Exercise the actual store selector while a real app handler awaits its
  // model response. Only the external generation response is delayed/mocked.
  holdGeneration = true;
  await page.click('[data-saas-action="listing-generate-ai-draft"]');
  const heldDeadline = Date.now() + 10000;
  while (!heldGeneration && Date.now() < heldDeadline) await new Promise((resolve) => setTimeout(resolve, 20));
  if (!heldGeneration) throw new Error("generation request was not held for context-switch regression");
  // The compact workbench hides this legacy selector; dispatch its native
  // change event to exercise the real switch handler, then assert visible UI.
  await page.selectOption("#storeSwitch", `saas:${otherStore.store_id}`, { force: true });
  await page.waitForFunction(
    (storeId) => activeSaasStore()?.store_id === storeId && state.saasLoading === false,
    otherStore.store_id,
    { timeout: 30000 },
  );
  await page.waitForSelector('[data-source-manual-field="product_name"]', { timeout: 20000 });
  await page.fill('[data-source-manual-field="product_name"]', "Other Store Tablet Stand");
  await page.fill('[data-source-manual-field="material"]', "Aluminum");
  await page.selectOption('[data-source-manual-field="condition"]', "NEW");
  const otherFactsSaved = page.waitForResponse(
    (response) => response.request().method() === "POST" && response.url().includes(`/stores/${otherStore.store_id}/product-facts`) && response.ok(),
    { timeout: 20000 },
  );
  await page.click('[data-saas-action="save-new-product-facts"]');
  await otherFactsSaved;
  await page.waitForSelector('[data-saas-listing-draft-field="title"]', { timeout: 20000 });
  await page.fill('[data-saas-listing-draft-field="title"]', "Other Store Unsaved Tablet Title");
  await page.locator('[data-saas-listing-draft-field="title"]').blur();
  const contextBeforeOldResponse = await page.evaluate(() => ({
    storeId: activeSaasStore()?.store_id,
    projectId: saasCurrentListingProjectIdentity().key,
    title: document.querySelector('[data-saas-listing-draft-field="title"]')?.value,
    staleReportPresent: (state.saasReports || []).some((item) => item.report_id === "report-old-context-must-not-enter-new-store"),
  }));
  const oldPayload = generatedPayload(heldGeneration.body, heldGeneration.storeId);
  oldPayload.report.report_id = "report-old-context-must-not-enter-new-store";
  const oldResponseFinished = page.waitForResponse((response) => response.url().includes(`/stores/${store.store_id}/listing-drafts/generate`));
  await heldGeneration.route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify(oldPayload) });
  heldGeneration.resolve();
  await oldResponseFinished;
  await page.waitForTimeout(150);
  const contextAfterOldResponse = await page.evaluate(() => ({
    storeId: activeSaasStore()?.store_id,
    projectId: saasCurrentListingProjectIdentity().key,
    title: document.querySelector('[data-saas-listing-draft-field="title"]')?.value,
    staleReportPresent: (state.saasReports || []).some((item) => item.report_id === "report-old-context-must-not-enter-new-store"),
  }));
  if (JSON.stringify(contextBeforeOldResponse) !== JSON.stringify(contextAfterOldResponse)) {
    throw new Error(`old Listing response changed the current store editor/cache: ${JSON.stringify({ before: contextBeforeOldResponse, after: contextAfterOldResponse })}`);
  }
  heldGeneration = null;
  await page.click('[data-saas-action="listing-generate-ai-draft"]');
  const returnDeadline = Date.now() + 10000;
  while (!heldGeneration && Date.now() < returnDeadline) await new Promise((resolve) => setTimeout(resolve, 20));
  if (!heldGeneration) throw new Error("return-to-project generation request was not held");
  await page.evaluate(() => {
    const original = state.saasListingComposerDraft;
    resetSaasListingProjectTransientState();
    state.saasListingComposerDraft = { ...original, listing_project_identity: { key: "temporary-other-project" } };
    resetSaasListingProjectTransientState();
    state.saasListingComposerDraft = original;
    // Model another view's completed work; the old request no longer owns it.
    state.saasLoading = false;
    renderProductListingCenter();
  });
  await page.fill('[data-saas-listing-draft-field="title"]', "Returned Project New Unsaved Title");
  await page.locator('[data-saas-listing-draft-field="title"]').blur();
  const returnedInput = await page.evaluate(() => ({
    dom: document.querySelector('[data-saas-listing-draft-field="title"]')?.value,
    draft: state.saasListingComposerDraft?.fields?.title,
    cloud: saasListingCloudRecord()?.fields?.title,
  }));
  if (Object.values(returnedInput).some((value) => value !== "Returned Project New Unsaved Title")) {
    throw new Error(`returned-project title input was not received before releasing the old response: ${JSON.stringify(returnedInput)}`);
  }
  const returnedPayload = generatedPayload(heldGeneration.body, heldGeneration.storeId);
  returnedPayload.report.report_id = "report-before-project-leave";
  await heldGeneration.route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify(returnedPayload) });
  heldGeneration.resolve();
  await page.waitForTimeout(150);
  const returnResult = await page.evaluate(() => ({
    title: document.querySelector('[data-saas-listing-draft-field="title"]')?.value,
    staleReportPresent: (state.saasReports || []).some((item) => item.report_id === "report-before-project-leave"),
  }));
  if (returnResult.staleReportPresent) throw new Error(`old Listing report entered the returned project: ${JSON.stringify(returnResult)}`);
  if (returnResult.title !== "Returned Project New Unsaved Title") throw new Error(`received returned-project title was later overwritten: ${JSON.stringify(returnResult)}`);
  heldGeneration = null;
  await page.click('[data-saas-action="listing-generate-ai-draft"]');
  const editDeadline = Date.now() + 10000;
  while (!heldGeneration && Date.now() < editDeadline) await new Promise((resolve) => setTimeout(resolve, 20));
  if (!heldGeneration) throw new Error("edit-during-generation request was not held");
  await page.fill('[data-saas-listing-draft-field="title"]', "Merchant Typed While AI Was Running");
  await page.fill('[data-saas-product-fact-field="material"]', "Updated material awaiting save");
  const editedPayload = generatedPayload(heldGeneration.body, heldGeneration.storeId);
  editedPayload.report.report_id = "report-generated-before-new-merchant-edits";
  await heldGeneration.route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify(editedPayload) });
  heldGeneration.resolve();
  await page.waitForTimeout(150);
  const editResult = await page.evaluate(() => ({
    title: document.querySelector('[data-saas-listing-draft-field="title"]')?.value,
    material: document.querySelector('[data-saas-product-fact-field="material"]')?.value,
    generating: state.saasLoading,
    buttonDisabled: document.querySelector('[data-saas-action="listing-generate-ai-draft"]')?.disabled,
    reportRetained: (state.saasReports || []).some((item) => item.report_id === "report-generated-before-new-merchant-edits"),
  }));
  if (editResult.title !== "Merchant Typed While AI Was Running" || editResult.material !== "Updated material awaiting save" || editResult.generating || editResult.buttonDisabled || !editResult.reportRetained) {
    throw new Error(`generation discarded new edits or left the editor busy: ${JSON.stringify(editResult)}`);
  }
  heldGeneration = null;
  const requestCountBeforeDuplicate = generationRequestCount;
  await page.click('[data-saas-action="listing-generate-ai-draft"]');
  const duplicateDeadline = Date.now() + 10000;
  while (!heldGeneration && Date.now() < duplicateDeadline) await new Promise((resolve) => setTimeout(resolve, 20));
  if (!heldGeneration) throw new Error("duplicate-generation request was not held");
  await page.evaluate(() => { void generateSaasListingDraftFromCurrentProject(); });
  await page.waitForTimeout(150);
  if (generationRequestCount !== requestCountBeforeDuplicate + 1) {
    throw new Error(`duplicate invocation sent ${generationRequestCount - requestCountBeforeDuplicate} model requests for one in-flight project`);
  }
  await heldGeneration.route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify(generatedPayload(heldGeneration.body, heldGeneration.storeId)) });
  heldGeneration.resolve();
  await page.waitForFunction(() => state.saasLoading === false);
  const contextCases = ["checkpoint_normalization_during_generation", "store_switch", "project_leave_return", "edits_during_generation", "duplicate_inflight"];
  await page.evaluate(() => {
    stopSaasAiCeoCrossDeviceSync();
    window.__listingContextFixture = structuredClone({
      saasCompany: state.saasCompany, saasIdentity: state.saasIdentity, saasUser: state.saasUser,
      saasListingComposerDraft: state.saasListingComposerDraft,
      saasReports: state.saasReports, saasTasks: state.saasTasks,
    });
  });
  const restoreFixture = () => page.evaluate(() => {
    resetSaasListingProjectTransientState();
    Object.assign(state, structuredClone(window.__listingContextFixture));
    state.saasLoading = false;
    state.saasListingAiGenerationStatus = "idle";
    state.saasListingAiGenerationMissingFields = [];
    setView("product", { listingMode: "single" });
  });
  const beginHeldRequest = async (label = "context matrix") => {
    heldGeneration = null;
    await page.click('[data-saas-action="listing-generate-ai-draft"]');
    const deadline = Date.now() + 10000;
    while (!heldGeneration && Date.now() < deadline) await new Promise((resolve) => setTimeout(resolve, 20));
    if (!heldGeneration) {
      const reason = await page.evaluate(() => ({
        view: state.view, busy: state.saasLoading, status: state.saasListingAiGenerationStatus,
        hasStore: Boolean(activeSaasStore()?.store_id), hasProject: Boolean(saasCurrentListingProjectIdentity().key),
        inflight: saasListingAiGenerationInFlight.size, toast: document.querySelector("#actionToast")?.textContent,
      }));
      throw new Error(`${label} request was not held: ${JSON.stringify(reason)}`);
    }
    heldGeneration.contextKey = await page.evaluate(() => saasListingAiGenerationRequest?.contextKey);
    if (!heldGeneration.contextKey) throw new Error(`${label} has no active client request context`);
    return heldGeneration;
  };
  const finishHeldRequest = async (held, outcome, marker) => {
    const payload = outcome === "success" ? generatedPayload(held.body, held.storeId)
      : outcome === "blocked" ? { status: "blocked", missing_fields: ["material"], merchant_message: "Old context blocked" }
        : { error: "fixture_model_unavailable", merchant_message: "Old context failure" };
    if (payload.report) payload.report.report_id = marker;
    if (payload.task) payload.task.task_id = marker;
    await held.route.fulfill({ status: outcome === "failure" ? 503 : 200, contentType: "application/json", body: JSON.stringify(payload) });
    held.resolve();
    await page.waitForFunction((key) => !saasListingAiGenerationInFlight.has(key), held.contextKey);
  };
  for (const scope of ["project", "company", "user"]) {
    for (const outcome of ["success", "blocked", "failure"]) {
      await restoreFixture();
      const held = await beginHeldRequest(`${scope}/${outcome}`);
      const marker = `old-${scope}-${outcome}`;
      await page.evaluate(({ scope }) => {
        if (scope === "project") {
          resetSaasListingProjectTransientState();
          state.saasListingComposerDraft.listing_project_identity.key = "other-project-context";
          state.saasListingComposerDraft.listing_project_key = "other-project-context";
        } else if (scope === "company") {
          state.saasCompany = { ...state.saasCompany, company_id: "other-company-context" };
          state.saasIdentity = { ...state.saasIdentity, company_id: "other-company-context" };
        } else {
          state.saasUser = { ...state.saasUser, user_id: "other-user-context" };
          state.saasIdentity = { ...state.saasIdentity, user_id: "other-user-context" };
        }
        state.saasListingComposerDraft.fields.title = "Current Context Must Keep This Title";
        state.saasLoading = true;
        state.saasListingAiGenerationStatus = "running";
        state.saasListingAiGenerationMissingFields = ["current-context-only"];
        renderProductListingCenter();
      }, { scope });
      await finishHeldRequest(held, outcome, marker);
      const result = await page.evaluate((marker) => ({
        title: document.querySelector('[data-saas-listing-draft-field="title"]')?.value,
        busy: state.saasLoading,
        status: state.saasListingAiGenerationStatus,
        missing: state.saasListingAiGenerationMissingFields,
        staleFeedback: Boolean(document.querySelector('[data-saas-listing-ai-feedback]')),
        staleArtifact: [...state.saasReports, ...state.saasTasks].some((item) => item.report_id === marker || item.task_id === marker),
      }), marker);
      if (result.title !== "Current Context Must Keep This Title" || !result.busy || result.status !== "running" || JSON.stringify(result.missing) !== '["current-context-only"]' || result.staleArtifact || result.staleFeedback) {
        throw new Error(`stale ${scope}/${outcome} modified current editor, error, cache or busy state: ${JSON.stringify(result)}`);
      }
      contextCases.push(`${scope}_${outcome}`);
    }
  }
  await restoreFixture();
  const viewRequest = await beginHeldRequest();
  await page.click('.nav-item[data-view="media"]');
  await finishHeldRequest(viewRequest, "success", "same-project-other-view-result");
  const otherViewResult = await page.evaluate((requestContext) => ({
    view: state.view,
    retained: state.saasReports.some((item) => item.report_id === "same-project-other-view-result"),
    busy: state.saasLoading,
    sameContext: requestContext === saasListingAiGenerationContextKey(),
  }), viewRequest.contextKey);
  if (otherViewResult.view !== "media" || !otherViewResult.retained || otherViewResult.busy) {
    throw new Error(`same-project navigation cancelled or redirected generation: ${JSON.stringify(otherViewResult)}`);
  }
  contextCases.push("same_project_other_view");
  await restoreFixture();
  const requestBeforeVisibleSwitch = await beginHeldRequest();
  const recentPayload = generatedPayload(requestBeforeVisibleSwitch.body, requestBeforeVisibleSwitch.storeId);
  recentPayload.report.report_id = "report-visible-recent-project";
  recentPayload.report.task_id = "task-visible-recent-project";
  recentPayload.task.task_id = "task-visible-recent-project";
  recentPayload.task.task_type = "product_workflow";
  recentPayload.task.output.report_id = recentPayload.report.report_id;
  recentPayload.report.report.listing_project_identity = { key: "visible-recent-project", source_report_id: "", candidate_id: "" };
  recentPayload.task.input.listing_project_identity = recentPayload.report.report.listing_project_identity;
  await page.evaluate((payload) => {
    const companyId = state.saasCompany?.company_id || state.saasIdentity?.company_id;
    payload.report.company_id = companyId;
    payload.report.store_id = activeSaasStore().store_id;
    payload.task.company_id = companyId;
    state.saasReports.unshift(payload.report);
    state.saasTasks.unshift(payload.task);
  }, recentPayload);
  await page.click('[data-listing-mode="recent"]');
  await page.click('[data-open-recent-product-task="task-visible-recent-project"]');
  await page.waitForSelector('[data-saas-listing-draft-field="title"]');
  await page.fill('[data-saas-listing-draft-field="title"]', "Visible Recent Project Must Remain");
  await finishHeldRequest(requestBeforeVisibleSwitch, "success", "old-before-visible-project-switch");
  const visibleSwitchResult = await page.evaluate(() => ({
    projectId: saasCurrentListingProjectIdentity().key,
    title: document.querySelector('[data-saas-listing-draft-field="title"]')?.value,
    staleArtifact: state.saasReports.some((item) => item.report_id === "old-before-visible-project-switch"),
  }));
  if (visibleSwitchResult.projectId !== "visible-recent-project" || visibleSwitchResult.title !== "Visible Recent Project Must Remain" || visibleSwitchResult.staleArtifact) {
    throw new Error(`visible recent-project navigation was overwritten: ${JSON.stringify(visibleSwitchResult)}`);
  }
  contextCases.push("visible_recent_project_navigation");
  await restoreFixture();
  const overlappingA = await beginHeldRequest();
  await page.evaluate(() => {
    resetSaasListingProjectTransientState();
    state.saasListingComposerDraft.listing_project_identity.key = "overlapping-project-b";
    state.saasListingComposerDraft.listing_project_key = "overlapping-project-b";
    renderProductListingCenter();
  });
  const overlappingB = await beginHeldRequest();
  await finishHeldRequest(overlappingA, "failure", "overlapping-a-failure");
  const overlappingBusy = await page.evaluate(() => ({
    busy: state.saasLoading,
    status: state.saasListingAiGenerationStatus,
    buttonDisabled: document.querySelector('[data-saas-action="listing-generate-ai-draft"]')?.disabled,
  }));
  if (!overlappingBusy.busy || overlappingBusy.status !== "running" || !overlappingBusy.buttonDisabled) {
    throw new Error(`old failure cleared a newer actual request: ${JSON.stringify(overlappingBusy)}`);
  }
  await finishHeldRequest(overlappingB, "success", "overlapping-b-result");
  await page.waitForFunction(() => state.saasLoading === false && state.saasListingAiGenerationStatus === "completed");
  contextCases.push("overlapping_request_busy_owner");
  const generationFeedback = page.locator('[data-saas-listing-ai-feedback]');
  await restoreFixture();
  await page.evaluate(() => {
    const draft = state.saasListingComposerDraft;
    draft.merchant_product_fact_packet.merchant_confirmed_facts.material = "Aluminum";
    draft.model_generated = true;
    draft.safe_local_only = false;
    draft.buyer_copy_requires_validated_listing_generation = true;
    renderProductListingCenter();
  });
  const blockedGeneration = await beginHeldRequest();
  if (!await page.evaluate(() => state.saasListingComposerDraft.model_generated === true)) {
    throw new Error("same-value fact capture revoked the existing Listing validation");
  }
  await page.fill('[data-saas-listing-draft-field="selling_points"]', "New edit while waiting");
  await page.fill('[data-saas-product-fact-field="material"]', "New unsaved material while waiting");
  await finishHeldRequest(blockedGeneration, "blocked", "blocked-with-new-edits");
  if (await page.inputValue('[data-saas-listing-draft-field="selling_points"]') !== "New edit while waiting" ||
      await page.inputValue('[data-saas-product-fact-field="material"]') !== "New unsaved material while waiting" ||
      !await generationFeedback.isVisible() || !(await generationFeedback.textContent()).includes("材质")) {
    throw new Error("blocked generation failed to show an inline reason while retaining in-flight edits");
  }
  contextCases.push("blocked_generation_inline_reason_preserves_inflight_edits");
  await page.evaluate(() => {
    state.saasListingComposerDraft.merchant_product_fact_packet.listing_copy = {};
    renderProductListingCenter();
  });
  const retainedCopy = { title: "原中文标题", selling_points: "原卖点一\n原卖点二\n原卖点三", description: "原描述保留" };
  for (const [key, value] of Object.entries(retainedCopy)) await page.fill(`[data-saas-listing-draft-field="${key}"]`, value);
  await page.fill('[data-saas-product-fact-field="material"]', "Steel");
  const rejectedGeneration = await beginHeldRequest();
  const changedFactValidation = await page.evaluate(() => ({
    generated: state.saasListingComposerDraft.model_generated,
    requiresValidation: state.saasListingComposerDraft.buyer_copy_requires_validated_listing_generation,
  }));
  if (changedFactValidation.generated !== false || changedFactValidation.requiresValidation !== true) {
    throw new Error("changed material retained the old Listing validation before regeneration completed");
  }
  if (await generationFeedback.count()) throw new Error("retry retained the previous generation error while running");
  const expiredMessage = "捷境托管 AI 试用已到期；请在设置查看套餐或已有模型连接。";
  await rejectedGeneration.route.fulfill({ status: 402, contentType: "application/json", body: JSON.stringify({ error: "platform_trial_expired", merchant_message: expiredMessage }) });
  rejectedGeneration.resolve();
  await page.waitForFunction(() => !state.saasLoading);
  await page.waitForTimeout(2900); // The transient action toast has expired.
  for (const [key, value] of Object.entries(retainedCopy)) {
    if (await page.inputValue(`[data-saas-listing-draft-field="${key}"]`) !== value) throw new Error(`rejected generation lost ${key}`);
  }
  if (!await generationFeedback.isVisible() || !(await generationFeedback.textContent()).includes(expiredMessage)) {
    throw new Error("rejected Listing generation has no persistent visible project-scoped reason after toast expiry");
  }
  for (const scope of ["company", "user", "project"]) {
    const leaked = await page.evaluate((scope) => {
      const original = structuredClone({ company: state.saasCompany, identity: state.saasIdentity, user: state.saasUser, draft: state.saasListingComposerDraft });
      if (scope === "company") state.saasCompany.company_id = "different-feedback-company";
      if (scope === "user") state.saasUser.user_id = "different-feedback-user";
      if (scope === "project") state.saasListingComposerDraft.listing_project_identity.key = "different-feedback-project";
      renderProductListingCenter();
      const leaked = Boolean(document.querySelector('[data-saas-listing-ai-feedback]'));
      Object.assign(state, { saasCompany: original.company, saasIdentity: original.identity, saasUser: original.user, saasListingComposerDraft: original.draft });
      renderProductListingCenter();
      return leaked;
    }, scope);
    if (leaked) throw new Error(`generation feedback leaked into a different ${scope}`);
  }
  await page.click('.nav-item[data-view="media"]');
  await page.evaluate(() => setView("product", { listingMode: "single" }));
  if (!await generationFeedback.isVisible()) throw new Error("generation reason disappeared after same-project navigation");
  await page.reload({ waitUntil: "domcontentloaded" });
  await page.waitForFunction(() => typeof state !== "undefined" && state.saasProtectedStateReady && !state.saasLoading);
  await page.evaluate(() => setView("product", { listingMode: "single" }));
  if (!await generationFeedback.isVisible() || !(await generationFeedback.textContent()).includes(expiredMessage)) {
    throw new Error("generation reason disappeared after same-project reload");
  }
  for (const [key, value] of Object.entries(retainedCopy)) {
    if (await page.inputValue(`[data-saas-listing-draft-field="${key}"]`) !== value) throw new Error(`rejected generation reload lost ${key}`);
  }
  if (!await page.evaluate(() => state.saasListingComposerDraft.model_generated === false && state.saasListingComposerDraft.buyer_copy_requires_validated_listing_generation === true)) {
    throw new Error("failed regeneration or reload revived the previous fact snapshot's Listing validation");
  }
  const publishBoundary = await page.evaluate(async () => ({
    title: saasPublishIntakePrefillValues().title,
    description: saasPublishIntakePrefillValues().description_html,
    publish: await createSaasPublishConfirmationFromIntakeForm("publish"),
    ebayDraft: await createSaasPublishConfirmationFromIntakeForm("ebay-draft"),
  }));
  if (publishBoundary.title || publishBoundary.description || publishBoundary.publish !== false || publishBoundary.ebayDraft !== false) {
    throw new Error("changed facts allowed old buyer copy into publishing or eBay draft confirmation");
  }
  await generationFeedback.scrollIntoViewIfNeeded();
  const failureScreenshotPath = path.join(os.tmpdir(), `jiejing-listing-generation-rejected-${viewportWidth}-${Date.now()}.png`);
  await page.screenshot({ path: failureScreenshotPath, fullPage: false });
  contextCases.push("rejected_generation_copy_and_persistent_reason");
  const screenshotPath = path.join(os.tmpdir(), `jiejing-listing-context-guard-${Date.now()}.png`);
  await page.screenshot({ path: screenshotPath, fullPage: false });

  // A refresh exposes the editor after core data, before its second-stage
  // reports GET completes. Hold a real local response, not a fabricated fact
  // packet, and wait for the actual refresh promise rather than a sleep.
  const auditRefreshTiming = await verifySlowOptionalAuditRefresh(page, () => page.evaluate(async () => {
    await state.saasListingProductFactSavePromise;
    window.__listingSlowAuditPriorArray = state.saasAuditLogs;
    await refreshSaasState({ silent: true });
  }));
  const refreshScope = await page.evaluate(() => ({
    companyId: state.saasIdentity?.company_id,
    userId: state.saasIdentity?.user_id,
    storeId: activeSaasStore()?.store_id,
    identity: saasCurrentListingProjectIdentity(),
    baseReportId: state.saasListingComposerDraft?.source_product_fact_report_id,
  }));
  const matchingFacts = (payload) => (payload.reports || []).filter((report) =>
    report.report_type === "merchant.product_facts" && report.status === "saved" &&
    report.company_id === refreshScope.companyId && report.store_id === refreshScope.storeId &&
    ["key", "source_report_id", "candidate_id"].every((key) =>
      typeof report.report?.listing_project_identity?.[key] === "string" &&
      report.report.listing_project_identity[key] === refreshScope.identity[key]))
    .sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at) || b.report_id.localeCompare(a.report_id));
  const baselineFactReport = matchingFacts(await api("/reports?limit=24", { token }))[0];
  if (!baselineFactReport || baselineFactReport.report_id !== refreshScope.baseReportId) {
    throw new Error("refresh regression requires the current project's real saved fact baseline");
  }
  const baselineMaterial = baselineFactReport.report.merchant_product_fact_packet.merchant_confirmed_facts.material;
  let factPostCount = 0;
  const countFactPosts = (request) => {
    if (request.method() === "POST" && new URL(request.url()).pathname === `/stores/${refreshScope.storeId}/product-facts`) factPostCount += 1;
  };
  page.on("request", countFactPosts);
  const reportsUrl = `${base}/reports?limit=24`;
  let releaseReports;
  let resolveHeldReports;
  let reportsHeldOnce = false;
  const heldReports = new Promise((resolve) => { resolveHeldReports = resolve; });
  const holdReports = async (route) => {
    if (route.request().method() !== "GET" || reportsHeldOnce) return route.continue();
    reportsHeldOnce = true;
    const response = await route.fetch();
    await new Promise((resolve) => {
      releaseReports = resolve;
      resolveHeldReports(response);
    });
    await route.fulfill({ response });
  };
  await page.route(reportsUrl, holdReports);
  try {
    await page.evaluate(() => {
      window.__listingRefreshRegressionDone = false;
      window.__listingRefreshRegressionPromise = refreshSaasState({ silent: true }).then(() => {
        window.__listingRefreshRegressionDone = true;
      });
    });
    const reportsResponse = await waitForTimingGate(heldReports, "Second-stage reports response");
    if (!reportsResponse.ok()) throw new Error("held second-stage reports GET was not a successful real response");
    const heldFactReport = matchingFacts(await reportsResponse.json())[0];
    if (heldFactReport?.report_id !== baselineFactReport.report_id) throw new Error("fact baseline changed before controlled refresh edits");
    if (!await page.evaluate(() => state.saasLoading === false && window.__listingRefreshRegressionDone === false)) {
      throw new Error("reports response was not held inside the real core-ready, refresh-pending window");
    }
    const refreshTitle = "Merchant Title While Refresh Is Pending";
    const refreshMaterial = "Merchant material awaiting explicit save";
    await page.fill('[data-saas-listing-draft-field="title"]', refreshTitle);
    await page.fill('[data-saas-product-fact-field="material"]', refreshMaterial);
    const factProvenanceAfterInput = await page.evaluate(() => Array.from(
      document.querySelectorAll("#view-product [data-saas-product-fact-field]"), (field) => [
        field.dataset.saasProductFactField, field.dataset.productFactConfirmed || "",
        field.dataset.productFactOriginState || "", field.dataset.productFactUnknown || "",
      ]));
    releaseReports();
    await waitForRefreshCompletion(page.evaluate(() => window.__listingRefreshRegressionPromise), "Second-stage refresh completion");
    await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(resolve)));
    const afterRefresh = await page.evaluate(() => ({
      companyId: state.saasIdentity?.company_id, userId: state.saasIdentity?.user_id,
      storeId: activeSaasStore()?.store_id, identity: saasCurrentListingProjectIdentity(),
      baseReportId: state.saasListingComposerDraft?.source_product_fact_report_id,
      title: document.querySelector('[data-saas-listing-draft-field="title"]')?.value,
      material: document.querySelector('[data-saas-product-fact-field="material"]')?.value,
      provenance: Array.from(document.querySelectorAll("#view-product [data-saas-product-fact-field]"), (field) => [
        field.dataset.saasProductFactField, field.dataset.productFactConfirmed || "",
        field.dataset.productFactOriginState || "", field.dataset.productFactUnknown || "",
      ]),
    }));
    if (afterRefresh.companyId !== refreshScope.companyId || afterRefresh.userId !== refreshScope.userId ||
        afterRefresh.storeId !== refreshScope.storeId || afterRefresh.baseReportId !== refreshScope.baseReportId ||
        ["key", "source_report_id", "candidate_id"].some((key) => afterRefresh.identity[key] !== refreshScope.identity[key])) {
      throw new Error("controlled refresh changed the merchant's project scope or fact baseline");
    }
    if (afterRefresh.title !== refreshTitle || afterRefresh.material !== refreshMaterial) {
      throw new Error("second-stage refresh discarded unsaved title or merchant material");
    }
    if (JSON.stringify(afterRefresh.provenance) !== JSON.stringify(factProvenanceAfterInput)) {
      throw new Error("second-stage refresh changed untouched fact confirmation or unknown provenance");
    }
    const stillSaved = matchingFacts(await api("/reports?limit=24", { token }))[0];
    if (factPostCount !== 0 || stillSaved?.report_id !== baselineFactReport.report_id ||
        stillSaved.report.merchant_product_fact_packet.merchant_confirmed_facts.material !== baselineMaterial) {
      throw new Error("refresh saved pending merchant facts without an explicit save action");
    }
    const explicitFactSave = page.waitForResponse((response) => response.request().method() === "POST" &&
      new URL(response.url()).pathname === `/stores/${refreshScope.storeId}/product-facts` && response.status() === 201,
    { timeout: 20000 });
    await page.click('[data-saas-action="save-merchant-product-facts"]');
    const savedFactResponse = await explicitFactSave;
    await page.evaluate(async () => { await state.saasListingProductFactSavePromise; });
    const savedFactPayload = await savedFactResponse.json();
    const independentlySaved = matchingFacts(await api("/reports?limit=24", { token }))[0];
    if (factPostCount !== 1 || independentlySaved?.report_id !== savedFactPayload.report?.report_id ||
        independentlySaved.report_id === baselineFactReport.report_id ||
        independentlySaved.report.merchant_product_fact_packet.merchant_confirmed_facts.material !== refreshMaterial) {
      throw new Error("explicit merchant save did not persist the retained material in the real backend");
    }
    contextCases.push("second_stage_refresh_preserves_unsaved_facts_until_explicit_save");
  } finally {
    releaseReports?.();
    await page.unroute(reportsUrl, holdReports);
    page.off("request", countFactPosts);
  }

  // The second client below is a synthetic local HTTP fixture, not a claimed
  // merchant UI journey. Its new fact version must not discard this page's
  // unsaved input or silently advance the page's compare-and-swap baseline.
  const factVersionA = matchingFacts(await api("/reports?limit=24", { token }))[0];
  if (!factVersionA || !await page.evaluate((reportId) =>
    state.saasListingComposerDraft?.source_product_fact_report_id === reportId, factVersionA.report_id)) {
    throw new Error("cross-base regression requires the fact version saved by the preceding UI case");
  }
  const pendingMaterialC = "Unsaved material C from the first client";
  await page.fill('[data-saas-product-fact-field="material"]', pendingMaterialC);
  const secondClientPacket = structuredClone(factVersionA.report.merchant_product_fact_packet);
  const secondClientMaterialB = "Saved material B from the second client";
  secondClientPacket.merchant_confirmed_facts.material = secondClientMaterialB;
  const savedBySecondClient = await api(`/stores/${refreshScope.storeId}/product-facts`, {
    token, method: "POST", body: {
      listing_project_identity: Object.fromEntries(["key", "source_report_id", "candidate_id"].map((key) => [key, refreshScope.identity[key]])),
      merchant_product_fact_packet: secondClientPacket,
      save_context: { contract_version: "merchant_product_fact_save_v1", mutation_id: crypto.randomUUID(),
        expected_fact_report_id: factVersionA.report_id },
    },
  });
  const factVersionB = savedBySecondClient.report;
  if (!factVersionB?.report_id || factVersionB.report_id === factVersionA.report_id) {
    throw new Error("second-client HTTP fixture did not save a distinct real fact version B");
  }
  const firstClientFactBodies = [];
  const captureFirstClientFactPost = (request) => {
    if (request.method() === "POST" && new URL(request.url()).pathname === `/stores/${refreshScope.storeId}/product-facts`) {
      firstClientFactBodies.push(JSON.parse(request.postData() || "{}"));
    }
  };
  page.on("request", captureFirstClientFactPost);
  try {
    await waitForRefreshCompletion(page.evaluate(() => refreshSaasState({ silent: true })), "Refresh to fact version B");
    if (await page.inputValue('[data-saas-product-fact-field="material"]') !== pendingMaterialC) {
      throw new Error("new fact version discarded the first client's unsaved material C");
    }
    const versionWarning = page.locator('[data-saas-product-fact-version-warning]');
    if (!await versionWarning.isVisible() || !/更新/.test(await versionWarning.textContent()) ||
        !/保留/.test(await versionWarning.textContent())) {
      throw new Error("retained old-base facts have no visible new-version warning");
    }
    if (firstClientFactBodies.length !== 0) throw new Error("refresh automatically submitted old-base merchant facts");
    // Merely visiting another workspace is not the explicit project reopen
    // below. Both routes really remove the fact controls before returning.
    const readNavigationFactState = () => page.evaluate(() => ({
      context: saasListingAiGenerationContextKey(), epoch: saasListingAiGenerationEpoch,
      baseReportId: state.saasListingComposerDraft?.source_product_fact_report_id,
      material: document.querySelector('#view-product [data-saas-product-fact-field="material"]')?.value,
      provenance: Array.from(document.querySelectorAll("#view-product [data-saas-product-fact-field]"), (field) => [
        field.dataset.saasProductFactField, field.dataset.productFactConfirmed || "",
        field.dataset.productFactOriginState || "", field.dataset.productFactUnknown || "",
      ]),
    }));
    const beforeTemporaryNavigation = await readNavigationFactState();
    for (const target of ["recent", "media"]) {
      if (target === "recent") {
        await page.click('#view-product [data-listing-mode="recent"]');
        await page.waitForFunction(() => state.view === "product" && state.saasListingMode === "recent" &&
          !document.querySelector("#view-product [data-saas-product-fact-field]"));
        await page.click('#view-product [data-listing-mode="single"]');
      } else {
        await page.click('.nav-item[data-view="media"]');
        await page.waitForFunction(() => state.view === "media" &&
          !document.querySelector("#view-product [data-saas-product-fact-field]"));
        await page.click('.nav-item[data-view="product"]');
      }
      await page.waitForFunction(() => state.view === "product" && state.saasListingMode === "single" &&
        document.querySelector('#view-product [data-saas-product-fact-field="material"]'));
      const afterTemporaryNavigation = await readNavigationFactState();
      if (JSON.stringify(afterTemporaryNavigation) !== JSON.stringify(beforeTemporaryNavigation) ||
          afterTemporaryNavigation.material !== pendingMaterialC || firstClientFactBodies.length !== 0 ||
          !await versionWarning.isVisible() || !/更新/.test(await versionWarning.textContent()) ||
          !/保留/.test(await versionWarning.textContent())) {
        throw new Error(`temporary ${target} navigation lost pending facts, changed scope, hid the version warning, or submitted facts`);
      }
    }
    // The original real POST/409 assertion next proves that navigation did not
    // silently rebase the retained input from A onto the newer saved version B.
    const conflictResponse = page.waitForResponse((response) => response.request().method() === "POST" &&
      new URL(response.url()).pathname === `/stores/${refreshScope.storeId}/product-facts` && response.status() === 409,
    { timeout: 20000 });
    await page.click('[data-saas-action="save-merchant-product-facts"]');
    await conflictResponse;
    await page.evaluate(async () => { await state.saasListingProductFactSavePromise; });
    if (firstClientFactBodies.length !== 1 || firstClientFactBodies[0].save_context?.expected_fact_report_id !== factVersionA.report_id ||
        await page.inputValue('[data-saas-product-fact-field="material"]') !== pendingMaterialC) {
      throw new Error("old-base save did not retain input C and submit the original fact version A for CAS");
    }
    // Exercise real completion boundaries after the 409; no automatic retry or
    // fabricated timer delay is needed to finish a read-only refresh.
    await waitForRefreshCompletion(page.evaluate(() => refreshSaasState({ silent: true })), "Refresh after fact CAS conflict");
    const afterConflict = matchingFacts(await api("/reports?limit=24", { token }))[0];
    const conflictSettled = await page.evaluate(() =>
      state.saasListingProductFactSaveRequest == null && state.saasListingProductFactSavePromise == null);
    if (firstClientFactBodies.length !== 1 || !conflictSettled || afterConflict?.report_id !== factVersionB.report_id ||
        afterConflict.report.merchant_product_fact_packet.merchant_confirmed_facts.material !== secondClientMaterialB ||
        await page.inputValue('[data-saas-product-fact-field="material"]') !== pendingMaterialC) {
      throw new Error(`fact conflict retried automatically, overwrote version B, or discarded retained input C: ${JSON.stringify({
        postCount: firstClientFactBodies.length,
        conflictSettled,
        sameServerReport: afterConflict?.report_id === factVersionB.report_id,
        serverMaterialUnchanged: afterConflict?.report?.merchant_product_fact_packet?.merchant_confirmed_facts?.material === secondClientMaterialB,
        pendingInputRetained: await page.inputValue('[data-saas-product-fact-field="material"]') === pendingMaterialC,
      })}`);
    }
    await page.reload({ waitUntil: "domcontentloaded" });
    await page.waitForFunction(() => typeof state !== "undefined" && state.saasProtectedStateReady && !state.saasLoading);
    await waitForRefreshCompletion(page.evaluate(() => refreshSaasState({ silent: true })), "Explicit reopen at fact version B");
    if (await page.inputValue('[data-saas-product-fact-field="material"]') !== secondClientMaterialB ||
        !await page.evaluate((reportId) => state.saasListingComposerDraft?.source_product_fact_report_id === reportId, factVersionB.report_id) ||
        await page.locator('[data-saas-product-fact-version-warning]').count()) {
      throw new Error("explicit reopen did not discard the old DOM overlay and restore real fact version B");
    }
    const newMaterialD = "New material D after explicit reopen";
    await page.fill('[data-saas-product-fact-field="material"]', newMaterialD);
    const finalSave = page.waitForResponse((response) => response.request().method() === "POST" &&
      new URL(response.url()).pathname === `/stores/${refreshScope.storeId}/product-facts` && response.status() === 201,
    { timeout: 20000 });
    await page.click('[data-saas-action="save-merchant-product-facts"]');
    const finalSavedPayload = await (await finalSave).json();
    await page.evaluate(async () => { await state.saasListingProductFactSavePromise; });
    const factVersionD = matchingFacts(await api("/reports?limit=24", { token }))[0];
    if (firstClientFactBodies.length !== 2 || firstClientFactBodies[1].save_context?.expected_fact_report_id !== factVersionB.report_id ||
        factVersionD?.report_id !== finalSavedPayload.report?.report_id || factVersionD.report_id === factVersionB.report_id ||
        factVersionD.report.merchant_product_fact_packet.merchant_confirmed_facts.material !== newMaterialD) {
      throw new Error("explicit reopen and merchant save did not create version D from observed version B");
    }
    contextCases.push("new_fact_base_retains_unsaved_input_and_original_cas_until_explicit_reopen");
  } finally {
    page.off("request", captureFirstClientFactPost);
  }
  if (pageErrors.length) throw new Error(`page errors: ${JSON.stringify(pageErrors)}`);
  if (unsafeRequests.length) throw new Error(`unsafe requests triggered: ${JSON.stringify(unsafeRequests)}`);

  console.log(JSON.stringify({
    ok: true,
    listing_project_id: capturedGenerationBody.listing_project_identity.key,
    report_id: savedTrace.report.report_id,
    task_id: savedTrace.task.task_id,
    restored_title: restoredTitle,
    viewport_width: layout.viewport_width,
    no_real_platform_writes_triggered: true,
    no_charge_or_refund_triggered: true,
    context_guard_cases: contextCases,
    audit_refresh_timing: auditRefreshTiming,
    failure_screenshot_path: failureScreenshotPath,
    screenshot_path: screenshotPath,
  }, null, 2));
  } finally {
    if (browser) await browser.close();
  }
}

async function main(options = {}) {
  let ownedBackend = null;
  try {
    if (base) {
      base = assertLoopbackMutationBase(base);
    } else {
      ownedBackend = await startOwnedBackend();
      base = assertLoopbackMutationBase(ownedBackend.backendBase);
    }
    await runListingFocusSmoke();
    if (options.focusOnly !== true) await runSmoke();
  } finally {
    await stopOwnedBackend(ownedBackend);
  }
}

if (require.main === module) {
  main().catch((error) => {
    console.error(error?.stack || error);
    process.exitCode = 1;
  });
}

module.exports = {
  assertLoopbackMutationBase,
  main,
  runSmoke,
  startOwnedBackend,
  stopOwnedBackend,
};
