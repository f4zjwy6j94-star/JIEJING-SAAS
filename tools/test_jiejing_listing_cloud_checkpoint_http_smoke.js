#!/usr/bin/env node
"use strict";

// Invoked by the Python HTTP suite with an owned, temporary API and session on
// stdin. Only startup is removed from app.js; no business API is mocked here.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const http = require("node:http");
const path = require("node:path");
const { chromium } = require("../output/codex-playwright-deps/node_modules/playwright-core");

async function main() {
  let input = "";
  for await (const chunk of process.stdin) input += chunk;
  const fixture = JSON.parse(input);
  const api = new URL(fixture.api_base);
  assert.equal(api.protocol, "http:");
  assert.equal(api.hostname, "127.0.0.1", "only the owned loopback API is permitted");
  assert.ok(api.port && !api.username && !api.password);
  const root = path.resolve(__dirname, "..");
  const source = fs.readFileSync(path.join(root, "app.js"), "utf8");
  const boot = /exposeLocalJiejingTestHooks\(\);\r?\ninit\(\);\r?\nrunLocalJiejingQaScenarioFromUrl\(\);\s*$/;
  assert.match(source, boot);
  const app = source.replace(boot, "exposeLocalJiejingTestHooks();\n");
  const html = fs.readFileSync(path.join(root, "app.html"), "utf8")
    .replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, "")
    .replace(/<style\b[^>]*>[\s\S]*?<\/style>/gi, "")
    .replace(/<link\b[^>]*>/gi, "")
    .replace(/<img\b[^>]*>/gi, "")
    .replace("</body>", '<script src="/app.js"></script></body>');
  const checkpointPath = `/stores/${fixture.store_id}/listing-drafts/${fixture.identity.key}/checkpoint`;
  const statusPath = `/stores/${fixture.store_id}/merchant-project-status`;
  const requests = [], forbidden = [], errors = [];
  const server = http.createServer((req, res) => {
    const url = new URL(req.url, "http://127.0.0.1");
    if (req.method === "GET" && ["/app.html", "/app.js"].includes(url.pathname)) {
      res.writeHead(200, { "content-type": url.pathname === "/app.js" ? "text/javascript; charset=utf-8" : "text/html; charset=utf-8" });
      return res.end(url.pathname === "/app.js" ? app : html);
    }
    const checkpointRequest = url.pathname === checkpointPath && ["GET", "POST"].includes(req.method);
    const statusRequest = url.pathname === statusPath && req.method === "GET"
      && url.searchParams.size === 1 && url.searchParams.get("project_id") === fixture.identity.key;
    if (!checkpointRequest && !statusRequest) {
      forbidden.push("unapproved_request"); res.writeHead(404); return res.end();
    }
    // The browser's real HttpOnly session cookie is forwarded unchanged. The
    // Python server, not this proxy, authenticates and applies all persistence.
    if (checkpointRequest) requests.push({ method: req.method, query: Object.fromEntries(url.searchParams) });
    const upstream = http.request(new URL(req.url, api), { method: req.method, headers: req.headers }, (response) => {
      res.writeHead(response.statusCode, response.headers); response.pipe(res);
    });
    upstream.on("error", () => { errors.push("loopback_proxy_failure"); res.writeHead(502); res.end(); });
    req.pipe(upstream);
  });
  let browser;
  try {
    await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
    const base = `http://127.0.0.1:${server.address().port}`;
    browser = await chromium.launch({ headless: true, channel: process.env.JIEJING_PLAYWRIGHT_CHANNEL || "chrome" });
    const keys = ["title", "selling_points", "description", "category", "item_specifics", "keywords", "price", "images", "logistics", "risk_notes"];
    const visibleKeys = keys.filter((key) => !["keywords", "risk_notes"].includes(key));
    const originalFields = Object.fromEntries(keys.map((key) => [key, `Original ${key}`]));
    const edited = { ...originalFields, title: "", category: "", selling_points: "Merchant point one\nMerchant point two",
      description: "Merchant FAL description stays exact", item_specifics: "Material: Aluminum", price: "29.00 USD",
      images: "Merchant photo still required", logistics: "Weight to be confirmed" };
    async function device() {
      const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
      await context.addCookies([{ name: "jiejing_saas_session", value: fixture.session_token,
        url: base, httpOnly: true, sameSite: "Lax" }]);
      const page = await context.newPage();
      page.on("pageerror", () => errors.push("page_error"));
      await page.route("**/*", (route) => {
        if (new URL(route.request().url()).origin === base) return route.continue();
        forbidden.push("foreign_request"); return route.abort();
      });
      await page.goto(`${base}/app.html?start=app&qa=public-saas&view=product&project=${fixture.identity.key}`);
      assert.equal(await page.evaluate(() => localStorage.length), 0);
      await page.evaluate(({ fixture, base, originalFields }) => {
        window.__JIEJING_FORCE_PUBLIC_MVP__ = true;
        localStorage.setItem(saasStorageKeys.storeId, fixture.store_id);
        localStorage.setItem("jiejing_saas_backend_session_hint", "1");
        localStorage.setItem("jiejing_saas_session_hint", "1");
        state.saasApiBase = base;
        state.saasIdentity = fixture.profile.identity;
        state.saasUser = fixture.profile.user;
        state.saasCompany = fixture.profile.company;
        state.saasPermissions = fixture.profile.permissions;
        state.saasStores = [{ store_id: fixture.store_id, company_id: fixture.profile.identity.company_id,
          platform: "ebay", marketplace: "EBAY_US" }];
        state.saasReports = [fixture.base_report]; state.saasTasks = [];
        state.saasProtectedStateReady = true;
        state.saasListingComposerDraft = { product: "Foldable Tablet Stand", title: "Original title",
          source_report_id: fixture.base_report.report_id, listing_project_identity: fixture.identity,
          fields: { ...originalFields }, merchant_edited_fields: [], model_generated: false, safe_local_only: true };
        state.saasDetachedListingProjectDrafts = {}; state.view = "product";
        bindEvents();
        document.querySelector("#view-product").innerHTML = renderSaasListingDraftEditor();
      }, { fixture: { ...fixture, session_token: undefined }, base, originalFields });
      return { context, page };
    }
    const first = await device();
    assert.equal(await first.page.locator("[data-saas-listing-draft-field]").count(), 8);
    const posted = first.page.waitForResponse((response) => new URL(response.url()).pathname === checkpointPath
      && response.request().method() === "POST", { timeout: 10000 }).catch(() => null);
    for (const key of visibleKeys) await first.page.locator(`[data-saas-listing-draft-field="${key}"]`).fill(edited[key]);
    const response = await posted;
    assert.ok(response, "actual input must reach the real Python checkpoint POST");
    assert.equal(response.status(), 201);
    const receipt = await response.json();
    assert.deepEqual(receipt.checkpoint.fields, edited);
    assert.equal(receipt.checkpoint.base_report_id, fixture.base_report.report_id);
    assert.deepEqual(receipt.checkpoint.listing_project_identity, fixture.identity);
    assert.equal(receipt.model_called || receipt.usage_consumed || receipt.real_platform_writes_enabled, false);
    await first.context.close();
    const second = await device();
    await second.page.evaluate(() => hydrateSaasListingCloudCheckpoint({ force: true }));
    for (const key of visibleKeys) assert.equal(await second.page.locator(`[data-saas-listing-draft-field="${key}"]`).inputValue(), edited[key]);
    assert.deepEqual(await second.page.evaluate(() => state.saasListingComposerDraft.fields), edited);
    assert.equal(requests.filter((item) => item.method === "POST").length, 1);
    for (const request of requests.filter((item) => item.method === "GET")) {
      assert.deepEqual(request.query, { source_report_id: fixture.identity.source_report_id, candidate_id: fixture.identity.candidate_id });
    }
    assert.deepEqual(forbidden, []); assert.deepEqual(errors, []);
    await second.context.close();
    process.stdout.write(JSON.stringify({ visible_controls: 8, restored_fields: 10, post_count: 1,
      get_count: requests.filter((item) => item.method === "GET").length, external_requests: 0, page_errors: 0 }));
  } finally {
    if (browser) await browser.close();
    server.closeAllConnections();
    await new Promise((resolve) => server.close(resolve));
  }
}

main().catch(() => { process.stderr.write("checkpoint_http_browser_smoke_failed\n"); process.exitCode = 1; });
