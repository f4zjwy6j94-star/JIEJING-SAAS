#!/usr/bin/env node
/* Browser contract: saving source facts from an empty merchant workspace must
   create one backend project and survive reload. No eBay or payment action. */

const fs = require("fs");
const path = require("path");
const { chromium } = require("../output/codex-playwright-deps/node_modules/playwright-core");

const base = process.env.JIEJING_TEST_BASE || "http://127.0.0.1:8788";
const localStaticRoot = path.resolve(process.env.JIEJING_LOCAL_STATIC_ROOT || path.join(__dirname, ".."));
const browserChannel = process.env.JIEJING_PLAYWRIGHT_CHANNEL || "chrome";

async function api(pathname, { token = "", method = "GET", body } = {}) {
  const response = await fetch(`${base}${pathname}`, {
    method,
    cache: "no-store",
    headers: {
      "content-type": "application/json",
      ...(token ? { authorization: `Bearer ${token}` } : {}),
    },
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
  const allowed =
    ["app.html", "index.html", "app.js", "styles.css"].includes(pathname) || pathname.startsWith("assets/");
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

async function main() {
  const suffix = `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  const email = `codex-source-persistence-${suffix}@local.invalid`;
  const registered = await api("/auth/register", {
    method: "POST",
    body: {
      email,
      password: `Codex-source-persistence-${suffix}`,
      company_name: "Codex Source Persistence",
    },
  });
  const token = registered.token;
  const user = registered.user || {};
  const company = registered.company || {};
  const store = (
    await api("/stores", {
      token,
      method: "POST",
      body: {
        platform: "ebay",
        store_name: "Source Persistence Store",
        marketplace: "EBAY_US",
        stage: "store_opened",
        settings: { created_from: "source_intake_persistence_browser_smoke" },
      },
    })
  ).store;

  const browser = await chromium.launch({ channel: browserChannel, headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, deviceScaleFactor: 1 });
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
  await context.route(`${base}/**`, (route) => {
    const filePath = localStaticPath(route.request().url());
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
    () =>
      typeof state !== "undefined" &&
      state.saasProtectedStateReady === true &&
      state.saasLoading === false &&
      typeof setView === "function",
    null,
    { timeout: 60000 },
  );
  await page.evaluate(() => setView("product"));
  await page.waitForSelector('[data-source-manual-field="product_name"]', { timeout: 20000 });
  await page.fill('[data-source-manual-field="product_name"]', "Zen Lotus Hand Backflow Incense Burner");
  await page.fill('[data-source-manual-field="source_link"]', "https://example.invalid/source/incense-burner");
  await page.fill('[data-source-manual-field="purchase_price"]', "36.00");
  await page.selectOption('[data-source-manual-field="currency"]', "CNY");
  await page.fill('[data-source-manual-field="source_location"]', "Quanzhou, Fujian, China");
  await page.fill('[data-source-manual-field="package_weight"]', "451 g");
  await page.fill('[data-source-manual-field="package_dimensions"]', "16.2 x 7.7 x 17.9 cm");
  await page.fill('[data-source-manual-field="material"]', "Resin");
  await page.selectOption('[data-source-manual-field="dropship_rule"]', "owned_inventory");

  const persisted = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      response.url().includes(`/stores/${encodeURIComponent(store.store_id)}/product-facts`) &&
      response.status() === 201,
    { timeout: 20000 },
  );
  await page.click('[data-saas-action="save-new-product-facts"]');
  const persistedResponse = await persisted;
  const persistedPayload = await persistedResponse.json();
  const identity = persistedPayload.listing_project_identity || {};
  if (!identity.key) throw new Error("source intake did not create a listing_project_identity");
  if (persistedPayload.merchant_product_fact_packet?.product_name !== "Zen Lotus Hand Backflow Incense Burner") {
    throw new Error("source intake did not persist the submitted product name");
  }

  const reports = (await api("/reports?limit=20", { token })).reports || [];
  const factReport = reports.find(
    (item) =>
      item.report_type === "merchant.product_facts" &&
      item.report?.listing_project_identity?.key === identity.key,
  );
  if (!factReport) throw new Error("persisted product facts were not retrievable through the merchant reports API");

  await page.goto(
    `${base}/app.html?start=app&view=product&project=${encodeURIComponent(identity.key)}`,
    { waitUntil: "domcontentloaded" },
  );
  await page.waitForFunction(
    () =>
      typeof state !== "undefined" &&
      state.saasProtectedStateReady === true &&
      state.saasLoading === false &&
      typeof setView === "function",
    null,
    { timeout: 60000 },
  );
  await page.evaluate(() => setView("product"));
  const restoredName = page.locator('[data-saas-product-fact-field="product_name"]');
  await restoredName.waitFor({ state: "visible", timeout: 20000 });
  if ((await restoredName.inputValue()) !== "Zen Lotus Hand Backflow Incense Burner") {
    throw new Error("saved product facts did not restore into the Listing page after reload");
  }
  if (pageErrors.length) throw new Error(`page errors: ${JSON.stringify(pageErrors)}`);
  if (unsafeRequests.length) throw new Error(`unsafe requests triggered: ${JSON.stringify(unsafeRequests)}`);

  console.log(
    JSON.stringify(
      {
        ok: true,
        listing_project_id: identity.key,
        report_id: factReport.report_id,
        restored_product_name: await restoredName.inputValue(),
        no_real_platform_writes_triggered: true,
        no_charge_or_refund_triggered: true,
      },
      null,
      2,
    ),
  );
  await browser.close();
}

main().catch((error) => {
  console.error(error?.stack || error);
  process.exit(1);
});
