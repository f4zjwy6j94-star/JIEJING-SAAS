#!/usr/bin/env node
"use strict";

// Replay saved backend records through the full frontend. No business API exists.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const http = require("node:http");
const path = require("node:path");
const { test, before, after } = require("node:test");
const { chromium } = require("../output/codex-playwright-deps/node_modules/playwright-core");
const company_id = "recent-company", store_id = "recent-store";
const identity = { key: "recent-tablet-project", source_report_id: "tablet-origin", candidate_id: "tablet-candidate" };
let server, browser, base;

function task(task_type, task_id = task_type, overrides = {}) {
  return { task_id, task_type, company_id, store_id, status: "completed", updated_at: "2026-09-06T01:00:00Z",
    input: { product: "Foldable Tablet Stand", listing_project_identity: identity }, ...overrides };
}

function report(task_id, overrides = {}) {
  return { report_id: "tablet-listing", task_id, report_type: "listing.package", company_id, store_id,
    runtime_run_id: "listing_draft_generation", status: "saved", created_at: "2026-09-06T01:00:00Z",
    report: { contract_version: "listing_ai_draft_generation_v1", product: "Foldable Tablet Stand",
      listing_project_identity: identity, listing_handoff: { ready_for_listing_draft: true,
        source_mode: "project_scoped_live_model", target_report_type: "listing.package",
        listing_fields: { title: "Foldable Aluminum Tablet Stand", description_seed: "A saved tabletop holder." } } },
    ...overrides };
}

before(async () => {
  const source = fs.readFileSync(path.join(__dirname, "..", "app.js"), "utf8");
  const boot = /exposeLocalJiejingTestHooks\(\);\r?\ninit\(\);\r?\nrunLocalJiejingQaScenarioFromUrl\(\);\s*$/;
  assert.match(source, boot);
  const appSource = source.replace(boot, "exposeLocalJiejingTestHooks();\n");
  const html = fs.readFileSync(path.join(__dirname, "..", "app.html"), "utf8")
    .replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, "")
    .replace(/<link\b[^>]*>/gi, "")
    .replace(/<img\b[^>]*>/gi, "")
    .replace("</body>", '<script src="/app.js"></script></body>');
  server = http.createServer((req, res) => {
    const url = new URL(req.url, "http://127.0.0.1");
    if (url.pathname === "/app.js") {
      res.writeHead(200, { "content-type": "text/javascript; charset=utf-8" }); res.end(appSource);
    } else if (url.pathname === "/app.html") {
      res.writeHead(200, { "content-type": "text/html; charset=utf-8" });
      res.end(html);
    } else { res.writeHead(404); res.end("No business API in this fixture"); }
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  base = `http://127.0.0.1:${server.address().port}`;
  browser = await chromium.launch({ headless: true, channel: process.env.JIEJING_PLAYWRIGHT_CHANNEL || "chrome" });
});
after(async () => {
  if (browser) await browser.close();
  if (server) await new Promise((resolve) => server.close(resolve));
});

async function withRecent(tasks, reports, run) {
  const context = await browser.newContext();
  const page = await context.newPage();
  const errors = [], unexpected = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.route("**/*", (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.origin === base && ["/app.html", "/app.js"].includes(url.pathname) && request.method() === "GET") return route.continue();
    unexpected.push(`${request.method()} ${url.pathname}`); return route.abort();
  });
  try {
    await page.goto(`${base}/app.html?start=app&qa=public-saas&project=${identity.key}`);
    await page.evaluate(({ tasks, reports, company_id, store_id }) => {
      window.__JIEJING_FORCE_PUBLIC_MVP__ = true;
      localStorage.setItem(saasStorageKeys.storeId, store_id);
      state.saasIdentity = { user_id: "recent-user", company_id };
      state.saasCompany = { company_id };
      state.saasStores = [{ store_id, company_id, platform: "ebay", marketplace: "EBAY_US" }];
      state.saasTasks = tasks; state.saasReports = reports;
      state.saasListingComposerDraft = null; state.saasDetachedListingProjectDrafts = {};
      state.view = "product";
      document.querySelector("#view-product").innerHTML = renderSaasRecentProductTasks();
    }, { tasks, reports, company_id, store_id });
    await run(page);
    assert.deepEqual(errors, []);
    assert.deepEqual(unexpected, [], "viewing and resuming saved tasks must not call any business API");
  } finally { await context.close(); }
}

test("actual Listing generation tasks appear and reopen the saved project without running AI", async () => {
  await withRecent([task("listing_draft_generation")], [report("listing_draft_generation")], async (page) => {
    assert.equal(await page.locator('[data-recent-product-task-type="listing_draft_generation"]').count(), 1);
    assert.equal(await page.locator('[data-open-recent-product-task="listing_draft_generation"]').count(), 1);
    const result = await page.evaluate(() => ({ opened: openSaasRecentProductTask("listing_draft_generation"),
      draft: state.saasListingComposerDraft, taskCount: state.saasTasks.length, reportCount: state.saasReports.length }));
    assert.equal(result.opened, true);
    assert.equal(result.draft.listing_project_identity.key, identity.key);
    assert.equal(result.draft.fields.title, "Foldable Aluminum Tablet Stand");
    assert.equal(result.taskCount, 1); assert.equal(result.reportCount, 1);
  });
});

test("saved product facts can reopen the same project's Listing, even when it came from another task", async () => {
  const facts = report("merchant_product_facts", { report_id: "saved-facts", report_type: "merchant.product_facts" });
  await withRecent([task("merchant_product_facts")], [facts, report("older-generation-task")], async (page) => {
    assert.equal(await page.locator('[data-recent-product-task-type="merchant_product_facts"]').count(), 1);
    assert.equal(await page.locator('[data-open-recent-product-task="merchant_product_facts"]').count(), 1);
    const result = await page.evaluate(() => ({ opened: openSaasRecentProductTask("merchant_product_facts"), draft: state.saasListingComposerDraft }));
    assert.equal(result.opened, true);
    assert.equal(result.draft.fields.title, "Foldable Aluminum Tablet Stand");
    assert.equal(result.draft.listing_project_identity.key, identity.key);
  });
});

test("only merchant chats with their own concrete saved research are product tasks", async () => {
  const research = report("research", { report_id: "tablet-research", report_type: "ai_ceo.market_research" });
  research.report.product_candidates = [{ candidate_id: "tablet-candidate", name: "Foldable Tablet Stand", selected: true }];
  research.report.selected_candidate_id = "tablet-candidate";
  const tasks = [task("merchant_ceo_chat", "research", { title: "AI CEO fast chat turn", input: { listing_project_identity: identity } }), task("merchant_ceo_chat", "plain-chat"),
    task("merchant_ceo_chat_attempt", "attempt"), task("provider_execution", "provider"),
    task("internal_runtime", "internal")];
  await withRecent(tasks, [research, report("older-generation-task")], async (page) => {
    assert.deepEqual(await page.locator("[data-recent-product-task-id]").evaluateAll((cards) => cards.map((card) => card.dataset.recentProductTaskId)), ["research"]);
    assert.equal(await page.locator(".saas-recent-product-card-main strong").textContent(), "Foldable Tablet Stand");
    const result = await page.evaluate(() => ({ opened: openSaasRecentProductTask("research"), draft: state.saasListingComposerDraft }));
    assert.equal(result.opened, true);
    assert.equal(result.draft.fields.title, "Foldable Aluminum Tablet Stand");
    assert.equal(result.draft.listing_project_identity.key, identity.key);
  });
});

test("recent tasks never cross tenant, store, project or candidate boundaries when linking reports", async () => {
  const foreignReports = [
    report("saved-task", { company_id: "other-company" }),
    report("saved-task", { store_id: "other-store" }),
    report("saved-task", { company_id: undefined, store_id: undefined }),
    ...[{ key: "other-project" }, { source_report_id: "other-origin" }, { candidate_id: "other-candidate" }].map((change) => {
      const value = report("saved-task"); value.report.listing_project_identity = { ...identity, ...change }; return value;
    }),
  ];
  await withRecent([task("listing_draft_generation", "saved-task"),
    task("listing_draft_generation", "foreign-company", { company_id: "other-company" }),
    task("merchant_product_facts", "foreign-store", { store_id: "other-store" }),
    task("listing_draft_generation", "unscoped", { company_id: undefined })], foreignReports, async (page) => {
    assert.deepEqual(await page.locator("[data-recent-product-task-id]").evaluateAll((cards) => cards.map((card) => card.dataset.recentProductTaskId)), ["saved-task"]);
    assert.equal(await page.locator("[data-open-recent-product-task]").count(), 0);
    assert.equal(await page.locator('[data-continue-recent-product-task="saved-task"]').count(), 1);
    assert.equal(await page.evaluate(() => openSaasRecentProductTask("saved-task")), false);
  });
});

test("legacy product tasks remain visible and tasks without a saved Listing only offer fact continuation", async () => {
  await withRecent([task("product_workflow", "legacy"), task("merchant_product_facts", "facts-only")], [], async (page) => {
    assert.equal(await page.locator("[data-recent-product-task-id]").count(), 2);
    assert.equal(await page.locator("[data-open-recent-product-task]").count(), 0);
    assert.equal(await page.locator("[data-continue-recent-product-task]").count(), 2);
  });
});

test("a failed generation without local feedback returns to the saved draft without promising a missing recovery card", async () => {
  const failed = task("listing_draft_generation", "failed-before-report", { user_id: "recent-user", status: "failed" });
  await withRecent([failed], [], async (page) => {
    const card = await page.locator('[data-recent-product-task-id="failed-before-report"]').innerText();
    assert.doesNotMatch(card, /查看生成反馈/, "a saved task cannot promise browser-local feedback still exists");
    assert.match(card, /核对已保存内容/);
    assert.match(card, /不会自动重新生成/);
    const result = await page.evaluate(({ identity }) => {
      state.saasProtectedStateReady = true;
      state.saasProtectedStateFromCache = false;
      state.saasSessionExpiryHandled = false;
      state.saasListingComposerDraft = { product: "Foldable Tablet Stand", listing_project_identity: identity,
        fields: { title: "My saved tablet title", description: "My saved buyer copy" }, ai_generation_feedback: null };
      const before = JSON.stringify(state.saasListingComposerDraft);
      const returned = continueSaasRecentProductTaskFacts("failed-before-report");
      return { returned, unchanged: JSON.stringify(state.saasListingComposerDraft) === before,
        feedback: state.saasListingComposerDraft.ai_generation_feedback,
        view: state.view, mode: state.saasListingMode, text: document.body.innerText };
    }, { identity });
    assert.equal(result.returned, true);
    assert.equal(result.unchanged, true);
    assert.equal(result.feedback, null, "missing recovery metadata must not be synthesized from an unrelated task");
    assert.equal(result.view, "product");
    assert.equal(result.mode, "single");
    assert.doesNotMatch(result.text, /请在生成反馈中核对本次结果/);
    assert.match(result.text, /已保存内容保留/);
    assert.match(result.text, /没有重新生成或补建商品/);
  });
});
