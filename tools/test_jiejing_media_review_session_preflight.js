#!/usr/bin/env node
"use strict";

// Real application markup, review checkboxes and submit handler. Only the
// loopback HTTP service is a fixture; no model, media provider or platform I/O.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const http = require("node:http");
const path = require("node:path");
const { test: nodeTest, before, after } = require("node:test");
const { chromium } = require("../output/codex-playwright-deps/node_modules/playwright-core");

const root = path.resolve(__dirname, "..");
const scope = { user_id: "review-user", company_id: "review-company", store_id: "review-store" };
const identity = { key: "review-project", source_report_id: "review-source", candidate_id: "review-candidate" };
const profile = { user: { user_id: scope.user_id }, company: { company_id: scope.company_id },
  identity: { user_id: scope.user_id, company_id: scope.company_id } };
const checks = ["product_structure", "product_appearance", "product_claims", "commercial_rights", "platform_claims", "listing_draft_boundary"];
const job = { media_job_id: "review-media-job", company_id: scope.company_id, store_id: scope.store_id,
  status: "waiting_review", live_provider_called: true, secret_exposed: false, spend_now_allowed: false,
  updated_at: "2026-10-03T00:00:00Z", asset_manifest_validation: { status: "manifest_ready" },
  job: { job_spec: { inputs: { product_facts: { listing_project_key: identity.key,
    listing_project_identity: identity, source_asset_id: "review-source-image", private_source_transport: "backend_asset_id" } } } },
  asset_manifest: [{ asset_id: "review-image", asset_type: "product_image", url_or_file_path: "https://example.invalid/review-image.png",
    listing_use_status: "draft_only_until_review", commercial_use_status: "needs_review" }] };
let server, browser, base, fixture;
function test(name, run) { return nodeTest(name, { timeout: 20000 }, run); }
function deferred() { let resolve; const promise = new Promise(done => { resolve = done; }); return { promise, resolve }; }
async function bounded(promise, label, ms = 8000) {
  let timer;
  try { return await Promise.race([promise, new Promise((_, reject) => {
    timer = setTimeout(() => reject(new Error(`fixture timed out: ${label}`)), ms);
  })]); } finally { clearTimeout(timer); }
}

function json(res, status, body, headers = {}) {
  res.writeHead(status, { "content-type": "application/json; charset=utf-8", "cache-control": "no-store", ...headers });
  res.end(JSON.stringify(body));
}
async function holdMutation(current) {
  if (!current.mutationHold) return;
  const hold = current.mutationHold; current.mutationHold = null;
  hold.entered.resolve(); await hold.release.promise;
}

before(async () => {
  const source = fs.readFileSync(path.join(root, "app.js"), "utf8");
  const boot = /exposeLocalJiejingTestHooks\(\);\r?\ninit\(\);\r?\nrunLocalJiejingQaScenarioFromUrl\(\);\s*$/;
  assert.match(source, boot);
  const app = source.replace(boot, "exposeLocalJiejingTestHooks();\n");
  const html = fs.readFileSync(path.join(root, "app.html"), "utf8")
    .replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, "")
    .replace(/<style\b[^>]*>[\s\S]*?<\/style>/gi, "").replace(/<link\b[^>]*>/gi, "")
    .replace(/<img\b[^>]*>/gi, "")
    .replace("</head>", "<style>.is-hidden,.view:not(.is-active){display:none!important}</style></head>")
    .replace("</body>", '<script src="/app.js"></script></body>');
  server = http.createServer(async (req, res) => {
    const url = new URL(req.url, "http://127.0.0.1");
    if (["/app.html", "/index.html", "/app.js"].includes(url.pathname)) {
      res.writeHead(200, { "content-type": url.pathname.endsWith(".js") ? "text/javascript; charset=utf-8" : "text/html; charset=utf-8" });
      return res.end(url.pathname.endsWith(".js") ? app : html);
    }
    const event = { path: url.pathname, method: req.method };
    const current = fixture;
    current.requests.push(event);
    if (url.pathname === "/me") {
      if (current.meHold) {
        const hold = current.meHold; current.meHold = null;
        hold.entered.resolve(); await hold.release.promise;
      }
      if (!String(req.headers.cookie || "").includes("review_access=fresh")) return json(res, 401, { error: "session_expired" });
      return json(res, 200, current.profile || profile);
    }
    if (url.pathname === "/auth/refresh" && req.method === "POST") {
      if (current.refreshRevoked) return json(res, 401, { error: "session_revoked" });
      return json(res, 200, { ok: true, session_refreshed: true, secret_exposed: false },
        { "set-cookie": "review_access=fresh; Path=/; HttpOnly; SameSite=Strict" });
    }
    if (url.pathname === `/stores/${scope.store_id}/publish-precheck` && req.method === "POST") {
      const chunks = []; for await (const chunk of req) chunks.push(chunk);
      event.body = JSON.parse(Buffer.concat(chunks).toString("utf8"));
      if (current.precheckDenied || !String(req.headers.cookie || "").includes("review_access=fresh")) {
        return json(res, 401, { error: "session_expired" });
      }
      return json(res, 200, { read_only: true, store_id: scope.store_id, listing_project_key: identity.key,
        simulation_only: true, confirmation_created: false, task_created: false,
        platform_write_attempted: false, real_execution_allowed: false,
        publish_readiness: { checks: [{ key: "simulation_only", label: "模拟保护", status: "blocked", blocking: true }] } });
    }
    if (url.pathname === `/stores/${scope.store_id}/merchant-ceo/chat` && req.method === "POST") {
      const chunks = []; for await (const chunk of req) chunks.push(chunk);
      event.body = JSON.parse(Buffer.concat(chunks).toString("utf8"));
      const dispatch = { contract_version: "ai_ceo_semantic_dispatch_v1", status: "ready", project_action: "none",
        command_id: event.body.command.id, idempotency_key: event.body.idempotency_key, request_task_id: "review-chat-request",
        company_id: scope.company_id, store_id: scope.store_id,
        submitted_project_identity: event.body.active_listing_context?.listing_project_identity || {},
        target_project_identity: {}, consumed_source_asset_ids: [], workflow_target: "general_chat" };
      return json(res, 200, { semantic_dispatch: dispatch, ai_ceo_chat: { status: "model_answered", route: "general_chat",
        answer: "Synthetic local response; no publication.", semantic_dispatch: dispatch, source_records: [], work_records: [], confirmation_items: [] },
        usage_consumed: false, listing_created: false, real_platform_writes_enabled: false, secret_exposed: false });
    }
    if (url.pathname === "/ai-ceo/chat-history/sync" && req.method === "POST") {
      const chunks = []; for await (const chunk of req) chunks.push(chunk);
      event.body = JSON.parse(Buffer.concat(chunks).toString("utf8"));
      return json(res, 200, { ai_ceo_chat_history: { scope: "account", cross_store: true, turns: event.body.turns || [] }, secret_exposed: false });
    }
    if (url.pathname === `/media-asset-jobs/${job.media_job_id}/review` && req.method === "POST") {
      const chunks = [];
      for await (const chunk of req) chunks.push(chunk);
      event.body = JSON.parse(Buffer.concat(chunks).toString("utf8"));
      if (current.reviewDenied || !String(req.headers.cookie || "").includes("review_access=fresh")) return json(res, 401, { error: "session_expired" });
      await holdMutation(current);
      return json(res, 200, { media_asset_job: { ...job, status: "approved_for_listing",
        merchant_review: { decision: event.body.decision, reviewed_by: scope.user_id } }, secret_exposed: false });
    }
    if (req.method === "POST" && [ `/media-asset-jobs/${job.media_job_id}/retry`,
      `/stores/${scope.store_id}/provider-jobs/queue`, `/stores/${scope.store_id}/media-source-assets` ].includes(url.pathname)) {
      const chunks = []; for await (const chunk of req) chunks.push(chunk);
      const body = Buffer.concat(chunks); event.bytes = body.length;
      if (url.pathname.endsWith("/media-source-assets")) event.filename = decodeURIComponent(String(req.headers["x-jiejing-file-name"] || ""));
      if (String(req.headers["content-type"] || "").includes("application/json")) event.body = JSON.parse(body.toString("utf8"));
      if (current.mutationDenied || !String(req.headers.cookie || "").includes("review_access=fresh")) return json(res, 401, { error: "session_expired" });
      await holdMutation(current);
      if (url.pathname.endsWith("/media-source-assets")) return json(res, 200, {
        media_source_asset: { asset_id: "review-new-source", source_url: `${base}/source.png`, sha256: "b".repeat(64) }, provider_reference_ready: true });
      return json(res, 200, { media_asset_job: { ...job, media_job_id: "review-created-job" }, secret_exposed: false });
    }
    if (req.method !== "GET") current.unexpectedWrites.push(url.pathname);
    return json(res, 200, { reports: [], turns: [], secret_exposed: false });
  });
  await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
  base = `http://127.0.0.1:${server.address().port}`;
  browser = await chromium.launch({ headless: true, channel: process.env.JIEJING_PLAYWRIGHT_CHANNEL || "chrome" });
});
after(async () => { if (browser) await browser.close(); if (server) await new Promise(resolve => server.close(resolve)); });

async function harness(run) {
  fixture = { requests: [], unexpectedWrites: [] };
  const context = await browser.newContext(), page = await context.newPage(), errors = [];
  page.setDefaultTimeout(8000);
  page.on("pageerror", error => errors.push(error.name));
  await page.route("**/*", route => new URL(route.request().url()).origin === base ? route.continue() : route.abort());
  try {
    await page.goto(`${base}/app.html?start=app&view=media&project=${identity.key}`);
    await page.evaluate(({ base, scope, identity, job, profile }) => {
      window.__JIEJING_FORCE_PUBLIC_MVP__ = true;
      localStorage.setItem(saasStorageKeys.sessionHint, "1");
      localStorage.setItem(saasStorageKeys.storeId, scope.store_id);
      state.saasApiBase = base;
      state.saasIdentity = profile.identity; state.saasUser = profile.user; state.saasCompany = profile.company;
      state.saasStores = [{ store_id: scope.store_id, company_id: scope.company_id, platform: "ebay", marketplace: "EBAY_US", status: "authorized" }];
      state.saasConnected = true; state.saasProtectedStateReady = true; state.saasProtectedStateFromCache = false;
      state.saasLoading = false; state.saasReports = []; state.saasTasks = []; state.saasAiCeoThread = [];
      state.saasListingComposerDraft = { product: "Synthetic measuring spoon", listing_project_identity: identity,
        source_report_id: identity.source_report_id, fields: { title: "Synthetic measuring spoon" },
        merchant_product_fact_packet: { product_name: "Synthetic measuring spoon", source_records: [] } };
      state.saasMediaAssetJobs = [job]; state.mediaTaskEntry = "listing";
      markSaasMediaJobsAsCurrentSessionBackendEvidence(job);
      bindEvents();
      [entryShell, siteShell, onboardingShell].forEach(shell => shell.classList.add("is-hidden"));
      appShell.classList.remove("is-hidden"); document.body.classList.remove("site-locked");
      setView("media");
      openAssetPreview(saasMediaManifestAssetCards(job)[0].key);
    }, { base, scope, identity, job, profile });
    assert.equal(await page.locator("#assetModal").isVisible(), true);
    assert.equal(await page.locator("[data-media-review-check]").count(), checks.length);
    for (const id of checks) await page.locator(`[data-media-review-check="${id}"]`).check();
    assert.equal(await page.locator("#assetSendConfirm").isEnabled(), true);
    await run({ page, fixture, context });
    assert.deepEqual(fixture.unexpectedWrites, []);
    assert.deepEqual(errors, []);
  } finally { await context.close(); }
}

async function waitForReviewSettled(page) {
  await page.waitForFunction(() => document.querySelector("#assetSendConfirm")?.textContent !== "正在保存审核", null, { timeout: 13000 });
}

async function assertNoReview(fixture) {
  assert.equal(fixture.requests.filter(row => row.path.endsWith("/review")).length, 0,
    "invalidated preflight must not send the original or a replacement review");
}

async function openPublishPrecheck(page) {
  await page.locator('#assetModal .modal-close[data-close-modal]').click();
  await page.evaluate(() => {
    state.saasListingComposerDraft.merchant_product_fact_packet.simulation_only = true;
    setView("product"); setSaasListingWizardStep(4); renderProductListingCenter();
  });
  assert.equal(await page.locator('[data-saas-action="run-publish-precheck"]').first().isEnabled(), true);
}

for (const mode of ["expired", "fresh"]) test(`publish precheck ${mode} session is verified before one read-only request`, async () => {
  await harness(async ({ page, fixture, context }) => {
    if (mode === "fresh") await context.addCookies([{ name: "review_access", value: "fresh", url: base, httpOnly: true }]);
    await openPublishPrecheck(page);
    const result = page.waitForResponse(response => new URL(response.url()).pathname.endsWith("/publish-precheck"));
    await page.locator('[data-saas-action="run-publish-precheck"]').first().click();
    assert.equal((await result).status(), 200, "checking an idle page must renew before the POST, not log the merchant out");
    await page.waitForFunction(() => state.saasReadonlyPublishCheck?.status === "checked");
    const posts = fixture.requests.filter(row => row.path.endsWith("/publish-precheck"));
    assert.equal(posts.length, 1);
    assert.equal(posts[0].body.listing_project_identity.key, identity.key);
    assert.equal(posts[0].body.simulation_only, true);
    assert.equal(fixture.requests[0].path, "/me");
    assert.equal(fixture.requests.filter(row => row.path === "/auth/refresh").length, mode === "expired" ? 1 : 0);
    assert.match(await page.locator('[data-listing-visible-publish-bridge]').textContent(), /1 项阻断/);
  });
});

test("publish precheck revoked renewal sends no product request", async () => {
  await harness(async ({ page, fixture }) => {
    fixture.refreshRevoked = true;
    await openPublishPrecheck(page);
    await page.locator('[data-saas-action="run-publish-precheck"]').first().click();
    await page.waitForURL("**/index.html?reason=session_expired*");
    assert.equal(fixture.requests.filter(row => row.path.endsWith("/publish-precheck")).length, 0);
  });
});

test("publish precheck POST401 is neither refreshed nor replayed", async () => {
  await harness(async ({ page, fixture, context }) => {
    await context.addCookies([{ name: "review_access", value: "fresh", url: base, httpOnly: true }]);
    fixture.precheckDenied = true;
    await openPublishPrecheck(page);
    const result = page.waitForResponse(response => new URL(response.url()).pathname.endsWith("/publish-precheck"));
    await page.locator('[data-saas-action="run-publish-precheck"]').first().click();
    assert.equal((await result).status(), 401);
    await page.waitForURL("**/index.html?reason=session_expired*");
    assert.equal(fixture.requests.filter(row => row.path.endsWith("/publish-precheck")).length, 1);
    assert.equal(fixture.requests.filter(row => row.path === "/auth/refresh").length, 0);
  });
});

for (const changed of ["company", "project", "source", "input"]) test(`publish precheck ${changed} changes cancel held renewal`, async () => {
  await harness(async ({ page, fixture }) => {
    await openPublishPrecheck(page);
    const hold = { entered: deferred(), release: deferred() }; fixture.meHold = hold;
    try {
      await page.locator('[data-saas-action="run-publish-precheck"]').first().click();
      await bounded(hold.entered.promise, "publish /me arrival");
      await page.evaluate(changed => {
        if (changed === "company") { state.saasIdentity.company_id = "replacement-company"; state.saasCompany.company_id = "replacement-company"; }
        if (changed === "project") state.saasListingComposerDraft.listing_project_identity.key = "replacement-project";
        if (changed === "source") state.saasListingComposerDraft.fields.title = "Changed title";
        if (changed === "input") {
          const input = document.querySelector('#saasPublishIntakeForm [name="price"]');
          input.value = "14.95"; input.dispatchEvent(new Event("input", { bubbles: true }));
        }
      }, changed);
      const returned = page.waitForResponse(response => new URL(response.url()).pathname === "/me");
      hold.release.resolve(); await returned;
      await page.waitForFunction(() => state.saasReadonlyPublishCheck?.status !== "checking");
      assert.equal(fixture.requests.filter(row => row.path.endsWith("/publish-precheck")).length, 0);
      assert.equal(fixture.requests.filter(row => row.path === "/auth/refresh").length, 0);
      assert.equal(await page.locator('[data-listing-visible-publish-bridge]').getByText("只读检查已完成", { exact: true }).count(), 0);
    } finally { hold.release.resolve(); }
  });
});

test("publish precheck rejects a different cookie account before sending product facts", async () => {
  await harness(async ({ page, fixture }) => {
    fixture.profile = { user: { user_id: "other-user" }, company: profile.company,
      identity: { ...profile.identity, user_id: "other-user" } };
    await openPublishPrecheck(page);
    await page.locator('[data-saas-action="run-publish-precheck"]').first().click();
    await page.waitForFunction(() => state.saasReadonlyPublishCheck?.status !== "checking");
    assert.equal(fixture.requests.filter(row => row.path.endsWith("/publish-precheck")).length, 0);
  });
});

test("publish precheck bounds a stalled session probe and ignores its late response", async () => {
  await harness(async ({ page, fixture }) => {
    await openPublishPrecheck(page);
    const hold = { entered: deferred(), release: deferred() }; fixture.meHold = hold;
    try {
      await page.locator('[data-saas-action="run-publish-precheck"]').first().click();
      await bounded(hold.entered.promise, "stalled publish /me arrival");
      await page.waitForFunction(() => state.saasReadonlyPublishCheck?.status === "error", null, { timeout: 13000 });
      assert.equal(await page.locator('[data-saas-action="run-publish-precheck"]').first().isEnabled(), true);
      assert.equal(fixture.requests.filter(row => row.path.endsWith("/publish-precheck")).length, 0);
      hold.release.resolve(); await new Promise(setImmediate);
      await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
      assert.equal(fixture.requests.filter(row => row.path === "/auth/refresh").length, 0);
      assert.equal(fixture.requests.filter(row => row.path.endsWith("/publish-precheck")).length, 0);
    } finally { hold.release.resolve(); }
  });
});

test("actual media review renews an expired access session before its one mutation", async () => {
  await harness(async ({ page, fixture }) => {
    const result = page.waitForResponse(response => new URL(response.url()).pathname.endsWith("/review"));
    await page.locator("#assetSendConfirm").click();
    const response = await result;
    const writes = fixture.requests.filter(row => row.path.endsWith("/review"));
    assert.equal(response.status(), 200, "valid refresh must be used before, never after, the review POST");
    assert.equal(writes.length, 1, "merchant approval must never be automatically replayed");
    assert.equal(fixture.requests.filter(row => row.path === "/auth/refresh").length, 1);
    assert.equal(fixture.requests[0].path, "/me");
    assert.equal(fixture.requests.at(-1).path, `/media-asset-jobs/${job.media_job_id}/review`);
    assert.deepEqual(writes[0].body.acknowledged_review_items, checks);
    await page.waitForFunction(() => state.saasMediaAssetJobs[0]?.status === "approved_for_listing");
    assert.equal(await page.locator("#assetModal").isVisible(), false);
  });
});

for (const name of ["cancel-modal", "cancel-and-reopen", "uncheck-rights", "uncheck-and-recheck-rights",
  "navigate-away", "navigate-away-and-back", "account-epoch", "store", "company", "company-denied-renewal", "source-anchor", "candidate-anchor",
  "replacement-job", "manifest-changed"]) {
  test(`review preflight refuses ${name} during renewal`, async () => {
    await harness(async ({ page, fixture }) => {
      const hold = { entered: deferred(), release: deferred() }; fixture.meHold = hold;
      try {
        await page.locator("#assetSendConfirm").click();
        await bounded(hold.entered.promise, "review /me arrival");
        if (name === "cancel-modal" || name === "cancel-and-reopen") {
          await page.locator('#assetModal .modal-close[data-close-modal]').click();
          if (name === "cancel-and-reopen") {
            await page.evaluate(() => openAssetPreview(saasMediaManifestAssetCards()[0].key));
            for (const id of checks) await page.locator(`[data-media-review-check="${id}"]`).check();
          }
        } else if (name.startsWith("uncheck")) {
          await page.locator('[data-media-review-check="commercial_rights"]').uncheck();
          if (name === "uncheck-and-recheck-rights") await page.locator('[data-media-review-check="commercial_rights"]').check();
        } else {
          await page.evaluate(name => {
            if (name.startsWith("navigate")) { setView("cockpit"); if (name.endsWith("back")) setView("media"); }
            if (name === "account-epoch") invalidateSaasProtectedSessionContext();
            if (name === "store") {
              state.saasStores = [{ ...state.saasStores[0], store_id: "other-review-store" }];
              localStorage.setItem(saasStorageKeys.storeId, "other-review-store");
            }
            if (name.startsWith("company")) { state.saasIdentity.company_id = "other-review-company"; state.saasCompany.company_id = "other-review-company"; }
            if (name === "source-anchor") state.saasListingComposerDraft.listing_project_identity.source_report_id = "other-review-source";
            if (name === "candidate-anchor") state.saasListingComposerDraft.listing_project_identity.candidate_id = "other-review-candidate";
            if (name === "replacement-job") state.saasMediaAssetJobs = [{ ...state.saasMediaAssetJobs[0], media_job_id: "other-review-job" }];
            if (name === "manifest-changed") state.saasMediaAssetJobs[0].asset_manifest[0].url_or_file_path = "https://example.invalid/replacement.png";
          }, name);
        }
        if (name === "company-denied-renewal") fixture.refreshRevoked = true;
        hold.release.resolve();
        await waitForReviewSettled(page);
        await assertNoReview(fixture);
        if (name.startsWith("company")) {
          const replacement = await page.evaluate(() => ({ company: state.saasIdentity?.company_id,
            draftRetained: Boolean(state.saasListingComposerDraft) })).catch(() => ({ redirected: true }));
          assert.deepEqual(replacement, { company: "other-review-company", draftRetained: true },
            "a late preflight for the old company must not clear or redirect the replacement local scope");
        }
      } finally { hold.release.resolve(); }
    });
  });
}

test("revoked refresh denies review instead of replaying merchant approval", async () => {
  await harness(async ({ page, fixture }) => {
    fixture.refreshRevoked = true;
    await page.locator("#assetSendConfirm").click();
    await waitForReviewSettled(page);
    await assertNoReview(fixture);
    assert.equal(fixture.requests.filter(row => row.path === "/auth/refresh").length, 1);
  });
});

test("an externally switched cookie identity cannot approve the prior account's evidence", async () => {
  await harness(async ({ page, fixture }) => {
    fixture.profile = { user: { user_id: "other-user" }, company: profile.company,
      identity: { ...profile.identity, user_id: "other-user" } };
    await page.locator("#assetSendConfirm").click();
    await waitForReviewSettled(page);
    await assertNoReview(fixture);
  });
});

test("stalled session preflight releases the button and never submits after its late aborted response", async () => {
  await harness(async ({ page, fixture }) => {
    const hold = { entered: deferred(), release: deferred() }; fixture.meHold = hold;
    try {
      await page.locator("#assetSendConfirm").click(); await bounded(hold.entered.promise, "stalled /me arrival");
      await waitForReviewSettled(page);
      assert.equal(await page.locator("#assetSendConfirm").isEnabled(), true, "bounded verification failure must allow an explicit new attempt");
      await assertNoReview(fixture);
      hold.release.resolve(); await new Promise(setImmediate);
      await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
      await assertNoReview(fixture);
      assert.equal(fixture.requests.filter(row => row.path === "/auth/refresh").length, 0,
        "the aborted late /me must not start a new renewal or mutation");
    } finally { hold.release.resolve(); }
  });
});

test("ordinary review POST401 still neither refreshes nor replays after a successful preflight", async () => {
  await harness(async ({ page, fixture, context }) => {
    await context.addCookies([{ name: "review_access", value: "fresh", url: base, httpOnly: true }]);
    fixture.reviewDenied = true;
    const rejected = page.waitForResponse(response => new URL(response.url()).pathname.endsWith("/review"));
    await page.locator("#assetSendConfirm").click();
    assert.equal((await rejected).status(), 401);
    await waitForReviewSettled(page);
    assert.equal(fixture.requests.filter(row => row.path.endsWith("/review")).length, 1);
    assert.equal(fixture.requests.filter(row => row.path === "/auth/refresh").length, 0,
      "preflight does not grant permission to replay an ordinary mutation");
  });
});

function endpointFor(action) {
  return action === "upload" ? `/stores/${scope.store_id}/media-source-assets`
    : action === "queue" ? `/stores/${scope.store_id}/provider-jobs/queue` : `/media-asset-jobs/${job.media_job_id}/retry`;
}

const syntheticFile = { name: "synthetic-review.png", mimeType: "image/png",
  buffer: Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScLbtAAAAABJRU5ErkJggg==", "base64") };

async function startAdjacent(page, action, beforeAccept = null) {
  if (action === "retry") {
    await page.locator("#assetReworkCurrent").click();
  } else {
    await page.locator('#assetModal .modal-close[data-close-modal]').click();
    if (action === "upload") {
      await page.locator("#mediaSourceFileInput").setInputFiles(syntheticFile);
      return;
    }
    await page.evaluate(() => {
      state.saasListingComposerDraft.merchant_product_fact_packet.source_records = [{ type: "merchant_product_image",
        asset_id: "review-source-image", sha256: "a".repeat(64), rights_status: "pending_merchant_confirmation" }];
      syncMediaGenerationActionState();
    });
    assert.equal(await page.locator("#mediaGenerateImagesDraft").isEnabled(), true);
    await page.locator("#mediaGenerateImagesDraft").click();
  }
  assert.equal(await page.locator("#mediaAcceptanceModal").isVisible(), true);
  if (beforeAccept) await beforeAccept();
  await page.locator("#mediaAcceptanceConfirm").click();
}

for (const action of ["upload", "queue", "retry"]) {
  for (const mode of ["expired", "fresh"]) test(`adjacent ${action} actual ${mode} entry submits one original mutation`, async () => {
    await harness(async ({ page, fixture, context }) => {
      if (mode === "fresh") await context.addCookies([{ name: "review_access", value: "fresh", url: base, httpOnly: true }]);
      const endpoint = endpointFor(action);
      const result = page.waitForResponse(response => new URL(response.url()).pathname === endpoint);
      await startAdjacent(page, action);
      const response = await result;
      assert.equal(response.status(), 200, `${action} must renew before the first mutation, not retry its 401`);
      assert.equal(fixture.requests.filter(row => row.path === endpoint).length, 1);
      assert.equal(fixture.requests.filter(row => row.path === "/auth/refresh").length, mode === "expired" ? 1 : 0);
      assert.equal(fixture.requests[0].path, "/me");
      if (action === "upload") assert.equal(fixture.requests.find(row => row.path === endpoint).bytes, syntheticFile.buffer.length);
    });
  });

  test(`adjacent ${action} revoked refresh sends no mutation`, async () => {
    await harness(async ({ page, fixture }) => {
      fixture.refreshRevoked = true;
      await startAdjacent(page, action);
      await page.waitForURL("**/index.html?reason=session_expired*");
      assert.equal(fixture.requests.filter(row => row.path === endpointFor(action)).length, 0);
    });
  });

  test(`adjacent ${action} ordinary POST401 is not refreshed or replayed`, async () => {
    await harness(async ({ page, fixture, context }) => {
      await context.addCookies([{ name: "review_access", value: "fresh", url: base, httpOnly: true }]);
      fixture.mutationDenied = true;
      const result = page.waitForResponse(response => new URL(response.url()).pathname === endpointFor(action));
      await startAdjacent(page, action);
      assert.equal((await result).status(), 401);
      await page.waitForURL("**/index.html?reason=session_expired*");
      assert.equal(fixture.requests.filter(row => row.path === endpointFor(action)).length, 1);
      assert.equal(fixture.requests.filter(row => row.path === "/auth/refresh").length, 0);
    });
  });

  for (const changed of ["scope", "action"]) test(`adjacent ${action} ${changed} change invalidates held preflight`, async () => {
    await harness(async ({ page, fixture }) => {
      const hold = { entered: deferred(), release: deferred() }; fixture.meHold = hold;
      try {
        await startAdjacent(page, action); await bounded(hold.entered.promise, `${action} /me arrival`);
        if (action === "queue") assert.equal(await page.evaluate(() => state.saasMediaAssetJobs.some(row => String(row.media_job_id).startsWith("local-"))), false,
          "preflight must not persist a queued job before any backend mutation");
        await page.evaluate(({ action, changed }) => {
          if (changed === "scope") { state.saasIdentity.company_id = "replacement-company"; state.saasCompany.company_id = "replacement-company"; }
          else if (action === "upload") state.saasMediaSourceUploadEpoch += 1;
          else if (action === "queue") state.saasListingComposerDraft.merchant_product_fact_packet.source_records[0].asset_id = "replacement-source-image";
          else state.saasMediaAssetJobs[0].asset_version = { version: 99 };
        }, { action, changed });
        fixture.refreshRevoked = true;
        const oldMe = page.waitForResponse(response => new URL(response.url()).pathname === "/me");
        hold.release.resolve(); await oldMe;
        await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
        assert.equal(fixture.requests.filter(row => row.path === endpointFor(action)).length, 0);
        assert.equal(fixture.requests.filter(row => row.path === "/auth/refresh").length, 0);
        if (changed === "scope") assert.equal(await page.evaluate(() => state.saasIdentity.company_id), "replacement-company");
      } finally { hold.release.resolve(); }
    });
  });
}

for (const change of ["project", "config"]) test(`adjacent queue confirmation cannot authorize changed ${change}`, async () => {
  await harness(async ({ page, fixture }) => {
    await startAdjacent(page, "queue", async () => {
      if (change === "config") {
        await page.locator(".media-advanced-settings > summary").click();
        await page.selectOption("#mediaCountSelect", { label: "2 张" });
      }
      else await page.evaluate(() => { state.saasListingComposerDraft.listing_project_identity.source_report_id = "changed-during-confirmation"; });
    });
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    assert.equal(fixture.requests.filter(row => row.path === endpointFor("queue")).length, 0);
    assert.equal(fixture.requests.filter(row => row.path === "/me").length, 0, "stale rights confirmation must be rejected before even preflighting");
  });
});

for (const action of ["review", "queue", "retry", "upload"]) test(`late accepted ${action} result does not claim nonexecution or change the replacement scope`, async () => {
  await harness(async ({ page, fixture, context }) => {
    await context.addCookies([{ name: "review_access", value: "fresh", url: base, httpOnly: true }]);
    const hold = { entered: deferred(), release: deferred() }; fixture.mutationHold = hold;
    const endpoint = action === "review" ? `/media-asset-jobs/${job.media_job_id}/review` : endpointFor(action);
    try {
      if (action === "review") await page.locator("#assetSendConfirm").click();
      else await startAdjacent(page, action);
      await bounded(hold.entered.promise, `${action} accepted by server`);
      await page.evaluate(() => {
        state.saasIdentity.company_id = "replacement-company"; state.saasCompany.company_id = "replacement-company";
        state.saasListingComposerDraft.fields.title = "replacement scope title";
        state.saasMediaSourceUpload = { asset_id: "replacement-scope-source" };
        state.mediaGenerationStatus = "replacement-scope-status";
      });
      const returned = page.waitForResponse(response => new URL(response.url()).pathname === endpoint);
      hold.release.resolve(); await returned;
      await page.waitForFunction(() => /没有保存|没有创建|尚未创建|没有上传成功|未能确认/.test(document.querySelector("#actionToast")?.textContent || ""));
      assert.match(await page.locator("#actionToast").textContent(), /请求已发送.*未能确认/,
        "a sent mutation with a discarded late response has an unknown result, not proven nonexecution");
      assert.equal(fixture.requests.filter(row => row.path === endpoint).length, 1);
      assert.equal(fixture.requests.filter(row => row.path === "/auth/refresh").length, 0);
      assert.deepEqual(await page.evaluate(() => ({ company: state.saasIdentity.company_id,
        title: state.saasListingComposerDraft.fields.title, source: state.saasMediaSourceUpload?.asset_id,
        mediaStatus: state.mediaGenerationStatus })), { company: "replacement-company", title: "replacement scope title",
        source: "replacement-scope-source", mediaStatus: "replacement-scope-status" });
    } finally { hold.release.resolve(); }
  });
});

test("adjacent AI CEO image upload without a project remains valid after renewal", async () => {
  await harness(async ({ page, fixture }) => {
    await page.locator('#assetModal .modal-close[data-close-modal]').click();
    await page.evaluate(() => {
      state.saasListingComposerDraft = null; state.activeListingDraft = ""; state.activeMediaDraft = "";
      state.saasLastCeoCommand = null; state.saasMediaAssetJobs = [];
      syncSaasProjectRoute("cockpit", { clearProject: true }); setView("cockpit");
    });
    assert.equal(await page.evaluate(() => saasCurrentListingProjectIdentity().key), "");
    const uploaded = page.waitForResponse(response => new URL(response.url()).pathname === endpointFor("upload"));
    await page.locator("#ceoAttachmentInput").setInputFiles(syntheticFile);
    assert.equal((await uploaded).status(), 200);
    await page.waitForFunction(() => state.saasAiCeoPendingAttachments?.length === 1);
    assert.equal(await page.evaluate(() => state.saasListingComposerDraft), null);
    assert.equal(await page.evaluate(() => state.saasAiCeoPendingAttachments[0].asset_id), "review-new-source");
    assert.equal(fixture.requests.filter(row => row.path === endpointFor("upload")).length, 1);
  });
});

test("CEO attachment cancelled by a real sidebar roundtrip releases its own busy lock and permits text", async () => {
  await harness(async ({ page, fixture }) => {
    await page.locator('#assetModal .modal-close[data-close-modal]').click();
    await page.locator('.nav-item[data-view="cockpit"]').click();
    const hold = { entered: deferred(), release: deferred() }; fixture.meHold = hold;
    try {
      await page.locator("#ceoAttachmentInput").setInputFiles(syntheticFile);
      await bounded(hold.entered.promise, "CEO attachment /me arrival");
      await page.locator('.nav-item[data-view="media"]').click();
      await page.locator('.nav-item[data-view="cockpit"]').click();
      const oldMe = page.waitForResponse(response => new URL(response.url()).pathname === "/me");
      hold.release.resolve(); await oldMe;
      await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
      assert.deepEqual(await page.evaluate(() => ({ company: state.saasIdentity.company_id,
        project: saasCurrentListingProjectIdentity().key, generation: state.saasAiCeoAttachmentUploadGeneration })),
        { company: scope.company_id, project: identity.key, generation: 1 });
      assert.equal(fixture.requests.filter(row => row.path === endpointFor("upload")).length, 0);
      assert.equal(await page.evaluate(() => state.saasAiCeoAttachmentUploading), false,
        "a cancelled route-only attempt must release its own upload busy state");
      const message = "Do not publish; only resume the current draft.";
      await page.locator("#ceoInput").fill(message);
      const chat = page.waitForResponse(response => new URL(response.url()).pathname.endsWith("/merchant-ceo/chat"));
      await page.locator("#ceoForm button[type=submit]").click();
      assert.equal((await chat).status(), 200);
      await page.evaluate(async () => { await state.saasLastCeoCommandPersistPromise; stopSaasPendingNewListingProjectReconciliation(); });
      const chats = fixture.requests.filter(row => row.path.endsWith("/merchant-ceo/chat"));
      assert.equal(chats.length, 1);
      assert.equal(chats[0].body.message, message);
    } finally { hold.release.resolve(); }
  });
});

test("CEO attachment from an old account cannot clear the replacement account's busy state", async () => {
  await harness(async ({ page, fixture }) => {
    await page.locator('#assetModal .modal-close[data-close-modal]').click();
    await page.locator('.nav-item[data-view="cockpit"]').click();
    const hold = { entered: deferred(), release: deferred() }; fixture.meHold = hold;
    try {
      await page.locator("#ceoAttachmentInput").setInputFiles(syntheticFile);
      await bounded(hold.entered.promise, "old account attachment /me arrival");
      await page.evaluate(() => {
        invalidateSaasProtectedSessionContext();
        state.saasIdentity = { user_id: "replacement-user", company_id: "replacement-company" };
        state.saasUser = { user_id: "replacement-user" }; state.saasCompany = { company_id: "replacement-company" };
        state.saasProtectedStateReady = true; state.saasConnected = true;
        state.saasAiCeoAttachmentUploading = true;
        state.saasAiCeoPendingAttachments = [{ asset_id: "replacement-account-attachment" }];
      });
      const oldMe = page.waitForResponse(response => new URL(response.url()).pathname === "/me");
      hold.release.resolve(); await oldMe;
      await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
      assert.equal(fixture.requests.filter(row => row.path === endpointFor("upload")).length, 0);
      assert.deepEqual(await page.evaluate(() => ({ user: state.saasIdentity.user_id, company: state.saasIdentity.company_id,
        uploading: state.saasAiCeoAttachmentUploading, generation: state.saasAiCeoAttachmentUploadGeneration,
        attachment: state.saasAiCeoPendingAttachments[0]?.asset_id })), { user: "replacement-user", company: "replacement-company",
        uploading: true, generation: 1, attachment: "replacement-account-attachment" });
    } finally { hold.release.resolve(); }
  });
});

test("CEO attachment superseded by a new file does not release the newer upload's busy state", async () => {
  await harness(async ({ page, fixture }) => {
    await page.locator('#assetModal .modal-close[data-close-modal]').click();
    await page.locator('.nav-item[data-view="cockpit"]').click();
    const first = { entered: deferred(), release: deferred() }; fixture.meHold = first;
    const second = { entered: deferred(), release: deferred() };
    try {
      await page.locator("#ceoAttachmentInput").setInputFiles(syntheticFile);
      await bounded(first.entered.promise, "superseded attachment /me arrival");
      fixture.mutationHold = second;
      await page.locator("#ceoAttachmentInput").setInputFiles({ ...syntheticFile, name: "replacement-review.png" });
      await bounded(second.entered.promise, "replacement file upload arrival");
      const oldMe = page.waitForResponse(response => new URL(response.url()).pathname === "/me");
      first.release.resolve(); await oldMe;
      await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
      assert.equal(await page.evaluate(() => state.saasAiCeoAttachmentUploading), true,
        "the still-pending second file, not the completed cancellation, owns the busy state");
      assert.equal(await page.evaluate(() => state.saasAiCeoAttachmentUploadGeneration), 2);
      const uploads = fixture.requests.filter(row => row.path === endpointFor("upload"));
      assert.equal(uploads.length, 1);
      assert.equal(uploads[0].filename, "replacement-review.png");
      const uploaded = page.waitForResponse(response => new URL(response.url()).pathname === endpointFor("upload"));
      second.release.resolve(); assert.equal((await uploaded).status(), 200);
      await page.waitForFunction(() => state.saasAiCeoAttachmentUploading === false && state.saasAiCeoPendingAttachments?.length === 1);
      assert.equal(await page.evaluate(() => state.saasAiCeoPendingAttachments[0].asset_id), "review-new-source");
    } finally { first.release.resolve(); second.release.resolve(); }
  });
});
