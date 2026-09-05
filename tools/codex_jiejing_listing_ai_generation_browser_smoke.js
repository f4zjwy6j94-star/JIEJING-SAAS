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

  let capturedGenerationBody = null;
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
    if (request.method() === "POST" && request.url().includes(`/stores/${encodeURIComponent(store.store_id)}/listing-drafts/generate`)) {
      capturedGenerationBody = JSON.parse(request.postData() || "{}");
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
