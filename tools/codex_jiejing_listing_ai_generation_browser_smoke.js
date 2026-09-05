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
    const generationStore = new URL(request.url()).pathname.match(/^\/stores\/([^/]+)\/listing-drafts\/generate$/);
    if (request.method() === "POST" && generationStore) {
      generationRequestCount += 1;
      capturedGenerationBody = JSON.parse(request.postData() || "{}");
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
  await page.evaluate(() => setView("product"));
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
  await page.fill('[data-saas-listing-draft-field="description"]', "Merchant-confirmed description must remain unchanged.");
  const generationResponse = page.waitForResponse(
    (response) => response.request().method() === "POST" && response.url().includes("/listing-drafts/generate") && response.status() === 201,
    { timeout: 20000 },
  );
  await page.click('[data-saas-action="listing-generate-ai-draft"]');
  await generationResponse;
  await page.waitForFunction(
    () => document.querySelector('[data-saas-listing-draft-field="title"]')?.value === "Merchant Edited Zen Lotus Incense Burner",
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
  await page.evaluate(() => setView("product"));
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
  const returnedPayload = generatedPayload(heldGeneration.body, heldGeneration.storeId);
  returnedPayload.report.report_id = "report-before-project-leave";
  await heldGeneration.route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify(returnedPayload) });
  heldGeneration.resolve();
  await page.waitForTimeout(150);
  const returnResult = await page.evaluate(() => ({
    title: document.querySelector('[data-saas-listing-draft-field="title"]')?.value,
    staleReportPresent: (state.saasReports || []).some((item) => item.report_id === "report-before-project-leave"),
  }));
  if (returnResult.title !== "Returned Project New Unsaved Title" || returnResult.staleReportPresent) {
    throw new Error(`leaving and returning revived an old Listing request: ${JSON.stringify(returnResult)}`);
  }
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
  const contextCases = ["store_switch", "project_leave_return", "edits_during_generation", "duplicate_inflight"];
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
  const beginHeldRequest = async () => {
    heldGeneration = null;
    await page.click('[data-saas-action="listing-generate-ai-draft"]');
    const deadline = Date.now() + 10000;
    while (!heldGeneration && Date.now() < deadline) await new Promise((resolve) => setTimeout(resolve, 20));
    if (!heldGeneration) throw new Error("context matrix request was not held");
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
    await page.waitForTimeout(100);
  };
  for (const scope of ["project", "company", "user"]) {
    for (const outcome of ["success", "blocked", "failure"]) {
      await restoreFixture();
      const held = await beginHeldRequest();
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
        staleArtifact: [...state.saasReports, ...state.saasTasks].some((item) => item.report_id === marker || item.task_id === marker),
      }), marker);
      if (result.title !== "Current Context Must Keep This Title" || !result.busy || result.status !== "running" || JSON.stringify(result.missing) !== '["current-context-only"]' || result.staleArtifact) {
        throw new Error(`stale ${scope}/${outcome} modified current editor, error, cache or busy state: ${JSON.stringify(result)}`);
      }
      contextCases.push(`${scope}_${outcome}`);
    }
  }
  await restoreFixture();
  const viewRequest = await beginHeldRequest();
  await page.click('.nav-item[data-view="media"]');
  await finishHeldRequest(viewRequest, "success", "same-project-other-view-result");
  const otherViewResult = await page.evaluate(() => ({
    view: state.view,
    retained: state.saasReports.some((item) => item.report_id === "same-project-other-view-result"),
    busy: state.saasLoading,
  }));
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
  await restoreFixture();
  const screenshotPath = path.join(os.tmpdir(), `jiejing-listing-context-guard-${Date.now()}.png`);
  await page.screenshot({ path: screenshotPath, fullPage: false });
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
    screenshot_path: screenshotPath,
  }, null, 2));
  } finally {
    if (browser) await browser.close();
  }
}

async function main() {
  let ownedBackend = null;
  try {
    if (base) {
      base = assertLoopbackMutationBase(base);
    } else {
      ownedBackend = await startOwnedBackend();
      base = assertLoopbackMutationBase(ownedBackend.backendBase);
    }
    await runSmoke();
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
