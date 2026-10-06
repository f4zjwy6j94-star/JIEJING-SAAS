#!/usr/bin/env node
"use strict";

// Complete DOM and product script. Only loopback HTTP routes are substituted.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const http = require("node:http");
const path = require("node:path");
const { test, before, after } = require("node:test");
const { chromium } = require("../output/codex-playwright-deps/node_modules/playwright-core");
const company = "expiry-company", user = "expiry-user", store = "expiry-store";
const identity = { key: "expiry-tablet", source_report_id: "expiry-source", candidate_id: "tablet" };
const operation = { operation_id: "743c4370-6ffd-48fa-97ab-bedd060380c8", company_id: company, user_id: user,
  store_id: store, listing_project_identity: identity, generation_mode: "rewrite_buyer_copy",
  expected_base_report_id: "expiry-facts", expected_checkpoint_revision: 6 };
const profile = { identity: { company_id: company, user_id: user, role: "owner" },
  user: { user_id: user, email: "expiry@example.invalid" }, company: { company_id: company } };
const stores = [{ store_id: store, company_id: company, platform: "ebay", marketplace: "EBAY_US" }];
const packet = { contract_version: "merchant_product_fact_packet_v1", source: "authenticated_merchant_request", product_name: "Tablet Stand",
  merchant_confirmed_facts: { product_name: "Tablet Stand", material: "Aluminum" }, source_confirmed_facts: {},
  derived_listing_suggestions: {}, fact_conflicts: [], unknown_facts: [], simulation_only: true };
const report = { report_id: "expiry-facts", task_id: "expiry-task", company_id: company, store_id: store, user_id: user,
  report_type: "merchant.product_facts", status: "saved", created_at: "2026-09-09T01:00:00Z",
  report: { product_name: "Tablet Stand", listing_project_identity: identity, merchant_product_fact_packet: packet } };
const fields = { title: "Original merchant title", selling_points: "Original merchant points", description: "Original description",
  category: "", item_specifics: "Material: Aluminum", keywords: "", price: "29 USD", images: "", logistics: "", risk_notes: "" };
const checkpoint = { checkpoint_id: "expiry-checkpoint", revision: 6, mutation_id: "expiry-mutation",
  company_id: company, store_id: store, listing_project_identity: identity, base_report_id: report.report_id,
  fields, merchant_edited_fields: ["title"], saved_at: "2026-09-09T01:00:00Z", source: "merchant_edit" };
function deferred() { let resolve; const promise = new Promise((done) => { resolve = done; }); return { promise, resolve }; }
let server, browser, base;
before(async () => {
  const source = fs.readFileSync(path.join(__dirname, "..", "app.js"), "utf8");
  const boot = /exposeLocalJiejingTestHooks\(\);\r?\ninit\(\);\r?\nrunLocalJiejingQaScenarioFromUrl\(\);\s*$/;
  assert.match(source, boot);
  const app = source.replace(boot, "exposeLocalJiejingTestHooks();\n");
  const html = fs.readFileSync(path.join(__dirname, "..", "app.html"), "utf8")
    .replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, "").replace(/<link\b[^>]*>/gi, "")
    .replace(/<img\b[^>]*>/gi, "").replace("</body>", '<script src="/app.js"></script></body>');
  server = http.createServer((req, res) => {
    const script = new URL(req.url, "http://127.0.0.1").pathname === "/app.js";
    res.writeHead(200, { "content-type": script ? "text/javascript; charset=utf-8" : "text/html; charset=utf-8" });
    res.end(script ? app : html);
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  base = "http://127.0.0.1:" + server.address().port;
  browser = await chromium.launch({ headless: true, channel: process.env.JIEJING_PLAYWRIGHT_CHANNEL || "chrome" });
});
after(async () => { if (browser) await browser.close(); if (server) await new Promise((resolve) => server.close(resolve)); });

async function harness(run) {
  const context = await browser.newContext(), page = await context.newPage(), requests = [], errors = [];
  const fixture = { profile, stores, reports: [report], checkpoint };
  page.on("pageerror", (error) => errors.push(error.message));
  await page.route("**/*", async (route) => {
    const req = route.request(), url = new URL(req.url());
    if (url.origin !== base) { errors.push("external request blocked"); return route.abort(); }
    if (["/app.html", "/index.html", "/app.js"].includes(url.pathname)) return route.continue();
    requests.push({ path: url.pathname, method: req.method() });
    if (fixture.meStatus && url.pathname === "/me") return route.fulfill({ status: fixture.meStatus,
      contentType: "application/json", body: JSON.stringify({ error: "temporary verification unavailable" }) });
    if (req.method() !== "GET" && !(url.pathname === "/ai-ceo/chat-history/sync" && req.method() === "POST")) {
      errors.push("unexpected action"); return route.abort();
    }
    let body = {};
    if (url.pathname === "/me") body = fixture.profile;
    if (url.pathname === "/stores") body = { stores: fixture.stores };
    if (url.pathname === "/connections") body = { connections: [{ connection_id: "expiry-connection", store_id: fixture.stores[0]?.store_id, platform: "ebay", status: "authorized" }] };
    if (url.pathname === "/permissions/me") body = { permissions: ["view_report", "create_task"], roles: ["owner"] };
    if (url.pathname === "/reports") { if (fixture.reportsHold) await fixture.reportsHold.promise; body = { reports: fixture.reports }; }
    if (url.pathname === "/health") body = { status: "ok" };
    if (url.pathname.startsWith("/ai-ceo/chat-history")) body = { ai_ceo_chat_history: { scope: "account", cross_store: true, turns: [] } };
    if (url.pathname.endsWith("/checkpoint")) body = { contract_version: "listing_merchant_edit_v1", status: fixture.checkpoint ? "saved" : "empty",
      checkpoint: fixture.checkpoint, current_revision: fixture.checkpoint?.revision || 0, current_base_report_id: fixture.reports[0]?.report_id || "",
      current_base_report: fixture.reports[0] || null,
      base_changed: false, model_called: false, usage_consumed: false, real_platform_writes_enabled: false, secret_exposed: false };
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  });
  const open = async () => {
    await page.goto(base + "/app.html?start=app&view=product&project=" + identity.key);
    await page.evaluate((base) => { window.__JIEJING_FORCE_PUBLIC_MVP__ = true; state.saasDemoBootstrapEnabled = false; state.saasApiBase = base; }, base);
  };
  try { await open(); await run({ page, requests, fixture, open }); assert.deepEqual(errors, []); }
  finally { await context.close(); }
}
async function seed(page) {
  return page.evaluate(({ profile, stores, report, identity, packet, operation, fields }) => {
    state.saasIdentity = profile.identity; state.saasUser = profile.user; state.saasCompany = profile.company;
    state.saasStores = stores; state.saasReports = [report]; state.saasConnected = true; state.saasProtectedStateReady = true;
    localStorage.setItem(saasStorageKeys.lastAccount, profile.user.user_id); saveSaasSessionToStorage(stores[0].store_id);
    state.saasListingComposerDraft = { product: "Tablet Stand", listing_project_identity: identity,
      source_report_id: identity.source_report_id, fields,
      merchant_product_fact_packet: packet, merchant_edited_fields: ["title"] };
    state.saasListingComposerDraft.ai_generation_feedback = { status: "generation_uncertain",
      context_key: saasListingAiGenerationContextKey(), operation,
      rewrite_source: { base_report_id: "expiry-facts", revision: 6 }, result_report_id: null,
      input_signature: "a".repeat(64), request_signature: "b".repeat(64), message: "Old local response" };
    saveSaasProtectedStateSnapshot();
    return state.saasListingComposerDraft.ai_generation_feedback;
  }, { profile, stores, report, identity, packet, operation, fields });
}
async function expire(page) {
  return page.evaluate(() => {
    history.replaceState({}, "", "/index.html");
    const handled = handleSaasUnrecoverableSession({ status: 401 });
    return { handled, token: state.saasToken, candidate: hasSaasProtectedSessionCandidate(),
      draft: state.saasListingComposerDraft, hydrate: hydrateSaasProtectedStateFromCache() };
  });
}
async function loginRefresh(page, actualProfile = profile) {
  await page.evaluate(async (profile) => {
    rememberSaasAuthAccount(profile); saveSaasSessionToStorage();
    state.saasSessionExpiryHandled = false; state.saasSessionExpiryRedirected = false;
    await refreshSaasState({ silent: true });
  }, actualProfile);
  assert.equal(await page.evaluate(() => state.saasError), "", "actual refresh must complete");
}

test("expired authentication clears live access but fresh same-account login restores the original pending generation", async () => {
  await harness(async ({ page, requests, open }) => {
    const expected = await seed(page);
    assert.deepEqual(await expire(page), { handled: true, token: "", candidate: false, draft: null, hydrate: false });
    await open(); await loginRefresh(page);
    const restored = await page.evaluate(() => state.saasListingComposerDraft?.ai_generation_feedback ?? null);
    assert.ok(restored, "same-account reauthentication must retain the original uncertain operation instead of losing it with the expired session");
    for (const key of ["operation", "rewrite_source", "result_report_id", "input_signature", "request_signature"]) assert.deepEqual(restored[key], expected[key], key);
    assert.equal(restored.status, "generation_uncertain");
    await page.evaluate(async () => { const record = saasListingCloudRecord(); if (record?.read) await record.read; });
    assert.deepEqual(await page.evaluate(() => state.saasListingComposerDraft.fields), { ...fields, cost_price: "" }, "R6 cloud checkpoint, not expiry metadata, restores saved merchant copy");
    assert.deepEqual(await page.evaluate(() => state.saasListingComposerDraft.merchant_edited_fields), ["title"]);
    assert.equal(restored.resume_available, undefined, "a cached summary cannot authorize continuation");
    await page.evaluate(() => setView("product"));
    assert.equal(await page.locator('[data-saas-action="listing-check-generation-result"]').count() > 0, true);
    assert.equal(await page.locator('[data-saas-action="listing-resume-generation"]').count(), 0);
    assert.deepEqual(requests.filter((request) => request.method !== "GET" && request.path !== "/ai-ceo/chat-history/sync"), []);
  });
});

test("expiry preserves only bounded operation metadata and repeated 401 does not overwrite it", async () => {
  await harness(async ({ page, open }) => {
    await seed(page);
    await page.evaluate(() => {
      state.saasListingComposerDraft.fields.description = "DO_NOT_RETAIN_COPY";
      state.saasListingComposerDraft.merchant_product_fact_packet.private_note = "DO_NOT_RETAIN_FACTS";
      Object.assign(state.saasListingComposerDraft.ai_generation_feedback, {
        message: "DO_NOT_RETAIN_FREE_TEXT", checking: true, resume_available: true, extra: { api_key: "DO_NOT_RETAIN_SECRET" } });
      state.saasPermissions = ["DO_NOT_RETAIN_PERMISSIONS"];
    });
    await expire(page);
    const saved = await page.evaluate(() => ({
      full: localStorage.getItem(saasProtectedSnapshotStorageKey()),
      raw: localStorage.getItem(saasExpiredListingGenerationStorageKey()),
      identity: state.saasIdentity, permissions: state.saasPermissions, reports: state.saasReports
    }));
    assert.equal(saved.full, null); assert.equal(saved.identity, null);
    assert.deepEqual(saved.permissions, []); assert.deepEqual(saved.reports, []);
    assert.ok(saved.raw.length < 4096);
    assert.doesNotMatch(saved.raw, /DO_NOT_RETAIN|email|permissions|packet|chat|fields|api_key|checking|resume_available/);
    await expire(page);
    assert.equal(await page.evaluate(() => localStorage.getItem(saasExpiredListingGenerationStorageKey())), saved.raw);
    await open();
    assert.equal(await page.evaluate(() => hydrateSaasProtectedStateFromCache()), false);
    assert.equal(await page.evaluate(() => state.saasListingComposerDraft), null);
  });
});

test("fresh user, tenant, store and every project identity component must match, even with matching email aliases", async () => {
  for (const scope of ["user", "company", "store", "project", "source", "candidate"]) {
    await harness(async ({ page, fixture, open }) => {
      await seed(page); await expire(page); await open();
      fixture.profile = structuredClone(profile); fixture.stores = structuredClone(stores); fixture.reports = [structuredClone(report)];
      if (scope === "user") fixture.profile.user.user_id = fixture.profile.identity.user_id = "other-user";
      if (scope === "company") fixture.profile.company.company_id = fixture.profile.identity.company_id = fixture.stores[0].company_id = fixture.reports[0].company_id = "other-company";
      if (scope === "store") fixture.stores[0].store_id = fixture.reports[0].store_id = "other-store";
      if (["project", "source", "candidate"].includes(scope)) {
        const key = { project: "key", source: "source_report_id", candidate: "candidate_id" }[scope];
        fixture.reports[0].report.listing_project_identity[key] = "other-" + scope;
      }
      fixture.checkpoint = null;
      await loginRefresh(page, fixture.profile);
      assert.equal(await page.evaluate(() => state.saasListingComposerDraft?.ai_generation_feedback ?? null), null, scope);
      assert.equal(await page.locator('[data-saas-action="listing-resume-generation"]').count(), 0);
    });
  }
});

test("explicit session clearing removes recovery, including a preserve-chat-only caller", async () => {
  for (const options of [{}, { preserveCeoThread: true }]) {
    await harness(async ({ page, open }) => {
      await seed(page); await expire(page);
      await page.evaluate((options) => clearSaasSessionFromStorage(options), options);
      assert.equal(await page.evaluate(() => localStorage.getItem(saasExpiredListingGenerationStorageKey())), null);
      await open(); await loginRefresh(page);
      assert.equal(await page.evaluate(() => state.saasListingComposerDraft?.ai_generation_feedback ?? null), null);
    });
  }
});

test("core refresh saves the normal cache without overwriting the independent pending record", async () => {
  await harness(async ({ page, fixture, open }) => {
    await seed(page); await expire(page); await open();
    const raw = await page.evaluate(() => localStorage.getItem(saasExpiredListingGenerationStorageKey()));
    fixture.reportsHold = deferred();
    const login = loginRefresh(page);
    try {
      await page.waitForFunction(() => state.saasProtectedStateReady === true && state.saasReports.length === 0);
      assert.equal(await page.evaluate(() => localStorage.getItem(saasExpiredListingGenerationStorageKey())), raw);
      assert.ok(await page.evaluate(() => localStorage.getItem(saasProtectedSnapshotStorageKey())));
      assert.equal(await page.evaluate(() => state.saasListingComposerDraft?.ai_generation_feedback ?? null), null);
    } finally { fixture.reportsHold.resolve(); }
    await login;
    assert.equal(await page.evaluate(() => state.saasListingComposerDraft.ai_generation_feedback.operation.operation_id), operation.operation_id);
  });
});

test("a temporary login identity verification failure retains the login hint but denies workbench access and retains the pending record", async () => {
  await harness(async ({ page, fixture, open }) => {
    await seed(page); await expire(page); await open();
    const raw = await page.evaluate(() => localStorage.getItem(saasExpiredListingGenerationStorageKey()));
    fixture.meStatus = 503;
    await page.evaluate(async (profile) => {
      rememberSaasAuthAccount(profile); saveSaasSessionToStorage();
      try { await ensureSaasDemoSession(); } catch (error) { /* Expected protected verification failure. */ }
    }, profile);
    assert.equal(await page.evaluate(() => hasSaasProtectedSessionCandidate()), true);
    assert.equal(await page.evaluate(() => state.saasProtectedStateReady), false);
    assert.equal(await page.evaluate(() => shouldDeferSaasProtectedAppReveal()), true);
    assert.equal(await page.evaluate(() => localStorage.getItem(saasExpiredListingGenerationStorageKey())), raw);
    fixture.meStatus = 0;
    await loginRefresh(page);
    assert.equal(await page.evaluate(() => state.saasListingComposerDraft.ai_generation_feedback.operation.operation_id), operation.operation_id);
  });
});

test("another project's normal cache remains writable and returning to the original project still recovers its operation", async () => {
  await harness(async ({ page, fixture, open }) => {
    await seed(page); await expire(page); await open();
    const raw = await page.evaluate(() => localStorage.getItem(saasExpiredListingGenerationStorageKey()));
    const other = structuredClone(report); other.report_id = "other-facts"; other.report.listing_project_identity.key = "other-tablet";
    fixture.reports = [other]; fixture.checkpoint = null;
    await page.evaluate(() => history.replaceState({}, "", "/app.html?start=app&view=product&project=other-tablet"));
    await loginRefresh(page);
    assert.equal(await page.evaluate(() => JSON.parse(localStorage.getItem(saasProtectedSnapshotStorageKey())).listing_composer_draft.listing_project_identity.key), "other-tablet");
    assert.equal(await page.evaluate(() => localStorage.getItem(saasExpiredListingGenerationStorageKey())), raw);
    fixture.reports = [report]; fixture.checkpoint = checkpoint;
    await page.evaluate((key) => history.replaceState({}, "", "/app.html?start=app&view=product&project=" + key), identity.key);
    await page.evaluate(() => refreshSaasState({ silent: true }));
    assert.equal(await page.evaluate(() => state.saasListingComposerDraft.ai_generation_feedback.operation.operation_id), operation.operation_id);
  });
});

test("malformed original signatures survive reload as invalid, never legacy or newly signed permission", async () => {
  await harness(async ({ page, open }) => {
    await seed(page);
    await page.evaluate(() => {
      state.saasListingComposerDraft.ai_generation_feedback.request_signature = "broken-original-signature";
      state.saasListingComposerDraft.ai_generation_feedback.input_signature = "broken-original-input";
    });
    await expire(page); await open(); await loginRefresh(page);
    const feedback = await page.evaluate(() => state.saasListingComposerDraft.ai_generation_feedback);
    assert.equal(feedback.request_signature, "invalid");
    assert.equal(feedback.input_signature, "invalid");
    assert.equal(feedback.resume_available, undefined);
    assert.equal(feedback.operation.operation_id, operation.operation_id);
  });
});

test("tampered, oversized, expired or secret-bearing recovery envelopes are rejected without restoring any draft data", async () => {
  await harness(async ({ page }) => {
    await seed(page); await expire(page);
    const original = await page.evaluate(() => localStorage.getItem(saasExpiredListingGenerationStorageKey()));
    const variants = [
      (v) => { delete v.feedback.request_signature; },
      (v) => { v.saved_at += " ".repeat(4000); },
      (v) => { v.saved_at = "2020-01-01T00:00:00.000Z"; },
      (v) => { v.feedback.operation.listing_project_identity.source_report_id = "sk-" + "s".repeat(32); },
      (v) => { v.feedback.operation.extra = { password: "not-a-real-password" }; },
      (v) => { v.feedback.resume_available = true; },
    ];
    for (const mutate of variants) {
      const value = JSON.parse(original); mutate(value);
      await page.evaluate((raw) => localStorage.setItem(saasExpiredListingGenerationStorageKey(), raw), JSON.stringify(value));
      assert.equal(await page.evaluate(() => readSaasExpiredListingGeneration()), null);
      assert.equal(await page.evaluate(() => state.saasListingComposerDraft), null);
    }
  });
});
