#!/usr/bin/env node
"use strict";

// Real application markup, event delegation and navigation; synthetic loopback
// data only. No provider, production browser, product save or platform write.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const http = require("node:http");
const path = require("node:path");
const { chromium } = require("../output/codex-playwright-deps/node_modules/playwright-core");

const root = path.resolve(__dirname, "..");
const identity = { key: "navigation-project-b", source_report_id: "navigation-facts-b", candidate_id: "navigation-candidate-b" };
const fixture = {
  identity,
  report: {
    report_id: identity.source_report_id, task_id: "navigation-task-b", report_type: "merchant.product_facts",
    company_id: "navigation-company", store_id: "navigation-store", status: "saved", created_at: "2026-10-03T00:00:00Z",
    report: { listing_project_identity: identity, merchant_product_fact_packet: {
      product_name: "合成商品 B 咖啡量勺", source: "backend_product_vision_extraction",
      source_confirmed_facts: {}, merchant_confirmed_facts: {},
      derived_listing_suggestions: { product_name: "合成商品 B 咖啡量勺", material: "Steel" },
      unknown_facts: ["product_name", "condition", "material"], source_records: [], simulation_only: true,
    } },
  },
};

async function main() {
  const source = fs.readFileSync(path.join(root, "app.js"), "utf8");
  const boot = /exposeLocalJiejingTestHooks\(\);\r?\ninit\(\);\r?\nrunLocalJiejingQaScenarioFromUrl\(\);\s*$/;
  assert.match(source, boot, "real application boot marker must match");
  const app = source.replace(boot, "exposeLocalJiejingTestHooks();\n");
  const html = fs.readFileSync(path.join(root, "app.html"), "utf8")
    .replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, "")
    .replace(/<style\b[^>]*>[\s\S]*?<\/style>/gi, "")
    .replace(/<link\b[^>]*>/gi, "")
    .replace(/<img\b[^>]*>/gi, "")
    .replace("</head>", "<style>.is-hidden,.view:not(.is-active){display:none!important}</style></head>")
    .replace("</body>", '<script src="/app.js"></script></body>');
  const writes = [], errors = [];
  const server = http.createServer((req, res) => {
    const url = new URL(req.url, "http://127.0.0.1");
    if (req.method !== "GET") {
      writes.push({ method: req.method, path: url.pathname });
      res.writeHead(405); return res.end();
    }
    if (["/app.html", "/app.js"].includes(url.pathname)) {
      res.writeHead(200, { "content-type": url.pathname === "/app.js" ? "text/javascript; charset=utf-8" : "text/html; charset=utf-8" });
      return res.end(url.pathname === "/app.js" ? app : html);
    }
    res.writeHead(200, { "content-type": "application/json", "cache-control": "no-store" });
    res.end(JSON.stringify({ reports: [fixture.report], merchant_project_status: null, secret_exposed: false }));
  });
  let browser;
  try {
    await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
    const base = `http://127.0.0.1:${server.address().port}`;
    browser = await chromium.launch({ headless: true, channel: process.env.JIEJING_PLAYWRIGHT_CHANNEL || "chrome" });
    for (const scenario of ["bound", "missing-candidate", "different-source", "different-candidate", "different-company", "different-store", "stale-button"]) {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    page.on("pageerror", error => errors.push(error.message));
    await page.route("**/*", route => new URL(route.request().url()).origin === base ? route.continue() : route.abort());
    await page.goto(`${base}/app.html?start=app&qa=public-saas&view=cockpit&project=${identity.key}`);
    await page.evaluate(({ base, fixture, scenario }) => {
      window.__JIEJING_FORCE_PUBLIC_MVP__ = true;
      localStorage.setItem(saasStorageKeys.sessionHint, "1");
      localStorage.setItem(saasStorageKeys.storeId, "navigation-store");
      state.saasApiBase = base;
      state.saasIdentity = { user_id: "navigation-user", company_id: "navigation-company" };
      state.saasUser = { user_id: "navigation-user" }; state.saasCompany = { company_id: "navigation-company" };
      state.saasStores = [{ store_id: "navigation-store", company_id: "navigation-company", platform: "ebay", marketplace: "EBAY_US" }];
      state.saasConnected = true; state.saasProtectedStateReady = true;
      state.saasProtectedStateFromCache = false; state.saasLoading = false;
      state.saasReports = [structuredClone(fixture.report)]; state.saasTasks = [];
      state.saasListingComposerDraft = applySaasMerchantProductFactPacketToDraft({
        product: "合成商品 B 咖啡量勺", title: "合成商品 B 咖啡量勺", listing_project_identity: { ...fixture.identity },
        listing_project_key: fixture.identity.key, source_product_fact_report_id: fixture.report.report_id,
        fields: { title: "", selling_points: "", description: "" },
      }, fixture.report.report.merchant_product_fact_packet);
      if (scenario === "missing-candidate") delete state.saasListingComposerDraft.listing_project_identity.candidate_id;
      if (scenario === "different-source") state.saasReports[0].report.listing_project_identity.source_report_id = "other-source";
      if (scenario === "different-candidate") state.saasReports[0].report.listing_project_identity.candidate_id = "other-candidate";
      if (scenario === "different-company") state.saasReports[0].company_id = "other-company";
      if (scenario === "different-store") state.saasReports[0].store_id = "other-store";
      state.saasListingMode = "single";
      state.saasLastCeoCommand = { id: "navigation-command-b", text: "完善合成商品 B 资料", intent: "listing" };
      state.saasMerchantProjectStatus = { snapshot_version: "merchant_project_status_v1",
        project: { project_id: fixture.identity.key, product_name: "合成商品 B 咖啡量勺" }, stages: [],
        next_action: { view: "product", action: "complete_product_facts", label: "补齐商品资料" } };
      bindEvents();
      [entryShell, siteShell, onboardingShell].forEach(shell => shell.classList.add("is-hidden"));
      appShell.classList.remove("is-hidden"); document.body.classList.remove("site-locked");
      setView("cockpit", { aiCeoTaskContextMode: "active_product_task", aiCeoTaskContextExpanded: true,
        aiCeoTaskContextCommandId: "navigation-command-b", aiCeoTaskContextProjectId: fixture.identity.key });
    }, { base, fixture: structuredClone(fixture), scenario });
    const next = page.locator("[data-ai-ceo-task-next-action]");
    assert.equal(await next.isVisible(), true, "bound B task has a visible next action");
    assert.equal(await next.textContent(), "补齐商品资料");
    if (scenario === "stale-button") {
      // A saved task button must not follow another candidate with the same key
      // after the active context changes, even if that candidate is also saved.
      await page.evaluate(() => {
        state.saasListingComposerDraft.listing_project_identity.candidate_id = "later-candidate";
        state.saasReports[0].report.listing_project_identity.candidate_id = "later-candidate";
      });
    }
    const before = await page.evaluate(() => ({ identity: state.saasListingComposerDraft.listing_project_identity,
      packet: state.saasListingComposerDraft.merchant_product_fact_packet, fields: state.saasListingComposerDraft.fields,
      base: state.saasListingComposerDraft.source_product_fact_report_id }));
    await next.click();
    const route = new URL(page.url());
    assert.equal(route.searchParams.get("view"), "product");
    assert.equal(route.searchParams.get("project"), identity.key, "navigation must retain the complete bound project");
    if (scenario === "bound") {
      assert.notEqual(route.searchParams.get("mode"), "recent", "bound B facts action must open B single-product flow, not recent tasks");
      assert.equal(await page.locator('#view-product [data-listing-wizard-step="1"]').isVisible(), true);
      assert.equal(await page.locator('#view-product [data-saas-product-fact-field="product_name"]').inputValue(), "合成商品 B 咖啡量勺");
    } else {
      assert.equal(route.searchParams.get("mode"), "recent", `${scenario}: unresolved identity must remain in recent tasks`);
      assert.equal(await page.locator("#view-product .saas-recent-product-tasks").isVisible(), true);
      assert.equal(await page.locator("#view-product [data-saas-product-fact-field]").count(), 0,
        `${scenario}: a name or key alone must not open an editor`);
    }
    const after = await page.evaluate(() => ({ identity: state.saasListingComposerDraft.listing_project_identity,
      packet: state.saasListingComposerDraft.merchant_product_fact_packet, fields: state.saasListingComposerDraft.fields,
      base: state.saasListingComposerDraft.source_product_fact_report_id }));
    assert.deepEqual(after, before, `${scenario}: navigation must preserve facts, permissions, copy and CAS base`);
    assert.deepEqual(errors, [], "navigation must not throw application errors");
    assert.deepEqual(writes, [], "navigation must not save, create tasks or call models");
    console.log(`PASS bound product navigation: ${scenario}`);
    await page.close();
    }
  } finally {
    await browser?.close();
    await new Promise(resolve => server.close(resolve));
  }
}

main().catch(error => {
  console.error(`FAIL bound product navigation: ${error.message}`);
  process.exitCode = 1;
});
