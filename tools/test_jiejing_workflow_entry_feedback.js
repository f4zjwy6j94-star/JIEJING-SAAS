#!/usr/bin/env node
"use strict";

// Exercise the real merchant DOM and event handlers against a loopback-only
// HTTP fixture. No accounts, models, providers, or production APIs are used.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const http = require("node:http");
const path = require("node:path");
const { test, before, after } = require("node:test");
const { chromium } = require("../output/codex-playwright-deps/node_modules/playwright-core");

const root = path.resolve(__dirname, "..");
const store = { store_id: "entry-store", company_id: "entry-company", platform: "ebay", marketplace: "EBAY_US" };
const identity = { user_id: "entry-user", company_id: store.company_id };
const connection = { connection_id: "entry-connection", store_id: store.store_id, company_id: store.company_id, platform: "ebay", status: "read_only_pending" };
const packet = { packet_id: "entry-packet", store_id: store.store_id, platform: "ebay", status: "ready", packet: { sections: [] } };
const modelSettings = { configured: true, active_provider: "fixture-model" };
let browser;
let server;
let base;

before(async () => {
  const source = fs.readFileSync(path.join(root, "app.js"), "utf8");
  const boot = /exposeLocalJiejingTestHooks\(\);\r?\ninit\(\);\r?\nrunLocalJiejingQaScenarioFromUrl\(\);\s*$/;
  assert.match(source, boot);
  const app = source.replace(boot, "");
  const html = fs.readFileSync(path.join(root, "app.html"), "utf8")
    .replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, "")
    .replace("</body>", '<script src="/app.js"></script></body>');
  server = http.createServer((req, res) => {
    const pathname = new URL(req.url, "http://localhost").pathname;
    if (pathname === "/app.html" || pathname === "/app.js") {
      res.writeHead(200, { "content-type": pathname.endsWith(".js") ? "text/javascript; charset=utf-8" : "text/html; charset=utf-8" });
      res.end(pathname.endsWith(".js") ? app : html);
      return;
    }
    const relative = pathname.replace(/^\/+/, "");
    const file = path.resolve(root, relative);
    if ((pathname === "/styles.css" || pathname.startsWith("/assets/")) && file.startsWith(root + path.sep) && fs.existsSync(file)) {
      const type = file.endsWith(".css") ? "text/css" : file.endsWith(".js") ? "text/javascript" : file.endsWith(".svg") ? "image/svg+xml" : "application/octet-stream";
      res.writeHead(200, { "content-type": type });
      res.end(fs.readFileSync(file));
      return;
    }
    res.writeHead(404);
    res.end("Local regression fixture only");
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  base = `http://127.0.0.1:${server.address().port}`;
  browser = await chromium.launch({ headless: true, channel: process.env.JIEJING_PLAYWRIGHT_CHANNEL || "chrome" });
});

after(async () => {
  if (browser) await browser.close();
  if (server) await new Promise((resolve) => server.close(resolve));
});

async function withMerchantPage(run, options = {}) {
  const context = await browser.newContext({ viewport: { width: options.width || 1440, height: 1000 } });
  const page = await context.newPage();
  const errors = [];
  const requests = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.route("**/*", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.origin !== base) return route.abort();
    if (!url.pathname.startsWith("/api/")) return route.continue();
    const endpoint = url.pathname.slice(4);
    requests.push({ method: request.method(), endpoint });
    const configured = options.respond?.(endpoint, request.method());
    if (configured) return route.fulfill({ status: configured.status || 200, contentType: "application/json", body: JSON.stringify(configured.body) });
    const defaults = {
      "/me": { identity, user: { user_id: identity.user_id, email: "entry@example.invalid" }, company: { company_id: store.company_id } },
      "/stores": { stores: [store] },
      "/connections": { connections: [connection] },
      "/permissions/me": { team_member: { role: "owner" }, permissions: ["manage_store", "create_task", "view_report"] },
      "/data-packets": { data_packets: [packet] },
      [`/stores/${store.store_id}/model/settings`]: { model_settings: modelSettings },
      "/health": { status: "ok" },
    };
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(defaults[endpoint] || {}) });
  });
  try {
    await page.goto(`${base}/app.html?start=app&qa=public-saas`);
    await page.evaluate(({ base, store, identity, packet, modelSettings, connection }) => {
      window.__JIEJING_FORCE_PUBLIC_MVP__ = true;
      document.body.classList.add("saas-public-mvp");
      sessionStorage.setItem(saasStorageKeys.token, "local-entry-fixture-token");
      localStorage.setItem(saasStorageKeys.storeId, store.store_id);
      Object.assign(state, {
        saasApiBase: `${base}/api`, saasToken: "local-entry-fixture-token", saasConnected: true, saasProtectedStateReady: true,
        saasIdentity: identity, saasUser: { user_id: identity.user_id, email: "entry@example.invalid" },
        saasCompany: { company_id: identity.company_id }, saasStores: [store], saasConnections: [connection], saasDataPackets: [packet], saasModelSettings: modelSettings,
      });
      bindEvents();
      openApp("bulk");
    }, { base, store, identity, packet, modelSettings, connection });
    await run(page, requests);
    assert.deepEqual(errors, [], "actual merchant UI has no uncaught errors");
  } finally {
    await context.close();
  }
}

test("no-source bulk entry opens an editable AI CEO research goal with chosen constraints without submitting", async () => {
  await withMerchantPage(async (page, requests) => {
    await page.locator('[data-bulk-count="20"]').click();
    await page.locator(".bulk-source-choice-grid button").first().click();
    assert.equal(await page.evaluate(() => state.view), "cockpit");
    const input = page.locator("#ceoInput");
    const goal = await input.inputValue();
    assert.match(goal, /20/);
    assert.match(goal, /小件轻货/);
    assert.match(goal, /不带电/);
    assert.match(goal, /自行.*货源|自己.*货源/);
    assert.match(goal, /不.*发布/);
    assert.equal(await input.evaluate((node) => node === document.activeElement), true);
    assert.equal(requests.filter((request) => request.method !== "GET").length, 0);
    assert.equal(await page.evaluate(() => state.saasAiCeoThread.length), 0);
  });
});

test("leaving AI CEO for bulk research preserves unsent text and repeated entry appends the goal only once", async () => {
  await withMerchantPage(async (page, requests) => {
    await page.evaluate(() => setView("cockpit"));
    await page.locator("#ceoInput").fill("先保留我的补充要求：不要推荐易碎商品。");
    await page.locator('.nav-item[data-view="product"]').click();
    await page.locator('[data-listing-mode="bulk"]').first().click();
    await page.locator(".bulk-source-choice-grid button").first().click();
    const first = await page.locator("#ceoInput").inputValue();
    assert.match(first, /^先保留我的补充要求：不要推荐易碎商品。/);
    assert.equal(first.split("【批量选品调研目标】").length - 1, 1);
    await page.locator('.nav-item[data-view="product"]').click();
    await page.locator('[data-listing-mode="bulk"]').first().click();
    await page.locator(".bulk-source-choice-grid button").first().click();
    assert.equal(await page.locator("#ceoInput").inputValue(), first);
    assert.equal(requests.filter((request) => request.method !== "GET").length, 0);
  });
});

test("composer drafts are store-scoped and stale account DOM cannot be captured into the next account", async () => {
  await withMerchantPage(async (page) => {
    await page.evaluate(() => setView("cockpit"));
    await page.locator("#ceoInput").fill("Store A unsent text");
    await page.evaluate(() => {
      window.oldComposer = document.querySelector("#ceoInput");
      state.saasStores.push({ ...state.saasStores[0], store_id: "entry-store-b" });
      localStorage.setItem(saasStorageKeys.storeId, "entry-store-b");
      setView("bulk");
      setView("cockpit");
    });
    assert.equal(await page.locator("#ceoInput").inputValue(), "");
    await page.locator("#ceoInput").fill("Store B unsent text");
    await page.evaluate(() => {
      localStorage.setItem(saasStorageKeys.storeId, "entry-store");
      setView("bulk"); setView("cockpit");
    });
    assert.equal(await page.locator("#ceoInput").inputValue(), "Store A unsent text");
    await page.evaluate(() => {
      state.saasIdentity = { user_id: "another-user", company_id: "another-company" };
      state.saasUser = { user_id: "another-user", email: "another@example.invalid" };
      state.saasCompany = { company_id: "another-company" };
      window.oldComposer.value = "late stale input";
      window.oldComposer.dispatchEvent(new Event("input", { bubbles: true }));
      setView("bulk"); setView("cockpit");
    });
    assert.equal(await page.locator("#ceoInput").inputValue(), "");
    await page.locator("#ceoInput").fill("Another account unsent");
    await page.evaluate(({ identity, store }) => {
      state.saasIdentity = identity; state.saasUser = { user_id: identity.user_id, email: "entry@example.invalid" };
      state.saasCompany = { company_id: store.company_id };
      setView("bulk"); setView("cockpit");
    }, { identity, store });
    assert.equal(await page.locator("#ceoInput").inputValue(), "", "returning to an old account does not resurrect its cleared memory draft");
  });
});

test("explicit clearing, accepted submission and logout never resurrect an old composer draft", async () => {
  await withMerchantPage(async (page) => {
    await page.evaluate(() => setView("cockpit"));
    await page.locator("#ceoInput").fill("will be cleared");
    await page.locator("#ceoInput").fill("");
    await page.evaluate(() => { setView("bulk"); setView("cockpit"); });
    assert.equal(await page.locator("#ceoInput").inputValue(), "");
    await page.locator("#ceoInput").fill("现在几点？");
    await page.locator('#ceoForm button[type="submit"]').click();
    assert.equal(await page.locator("#ceoInput").inputValue(), "", "accepted submit clears the rendered composer");
    await page.evaluate(() => { setView("bulk"); setView("cockpit"); });
    assert.equal(await page.locator("#ceoInput").inputValue(), "", "accepted submit clears the memory draft");
    await page.locator("#ceoInput").fill("must not survive logout");
    await page.evaluate(() => {
      const stale = document.querySelector("#ceoInput");
      clearSaasSessionFromStorage();
      stale.dispatchEvent(new Event("input", { bubbles: true }));
      sessionStorage.setItem(saasStorageKeys.token, "local-entry-fixture-token");
      state.saasToken = "local-entry-fixture-token";
      state.saasSessionExpiryHandled = false;
      state.saasConnected = true; state.saasProtectedStateReady = true;
      setView("bulk"); setView("cockpit");
    });
    assert.equal(await page.locator("#ceoInput").inputValue(), "");
  });
});

test("Settings memory refresh failure gives a merchant recovery step without backend diagnostics", async () => {
  await withMerchantPage(async (page, requests) => {
    await page.evaluate(() => { state.saasSettingsTab = "model"; setView("connect"); });
    await page.locator('[data-saas-action="refresh-merchant-memory"]').click();
    await page.waitForFunction(() => !state.saasLoading);
    const feedback = await page.evaluate(() => ({ toast: document.querySelector("#actionToast").textContent, error: state.saasError }));
    assert.match(feedback.toast, /重试|稍后/);
    assert.match(feedback.toast, /意见|支持/);
    assert.doesNotMatch(feedback.toast + feedback.error, /后端|日志|503|internal_failure|traceback|\/opt\//i);
    assert.equal(requests.filter((request) => request.method === "POST").length, 1);
  }, { respond: (endpoint, method) => method === "POST" && endpoint.endsWith("/merchant-memory/refresh")
    ? { status: 503, body: { error: "internal_failure", detail: "/opt/internal/worker.py traceback" } } : null });
});

test("Settings report generation unknown failure does not expose operational proof or raw diagnostics", async () => {
  await withMerchantPage(async (page, requests) => {
    await page.evaluate(() => { state.saasSettingsTab = "model"; setView("connect"); });
    await page.locator('[data-saas-action="run-model-value-rehearsal"]').click();
    await page.waitForFunction(() => !state.saasLoading);
    const feedback = await page.evaluate(() => ({ toast: document.querySelector("#actionToast").textContent, error: state.saasError }));
    assert.match(feedback.toast, /报告|上架资料/);
    assert.match(feedback.toast, /重试|稍后|刷新/);
    assert.doesNotMatch(feedback.toast + feedback.error, /live|模型证明|后端|503|internal_failure|traceback|\/opt\//i);
    assert.equal(requests.filter((request) => request.method === "POST").length, 1);
  }, { respond: (endpoint, method) => method === "POST" && endpoint.endsWith("/model/value-rehearsal")
    ? { status: 503, body: { error: "internal_failure", detail: "/opt/internal/worker.py traceback" } } : null });
});

test("Settings memory refresh success describes the updated merchant records and keeps the action usable", async () => {
  await withMerchantPage(async (page) => {
    await page.evaluate(() => { state.saasSettingsTab = "model"; setView("connect"); });
    await page.locator('[data-saas-action="refresh-merchant-memory"]').click();
    await page.waitForFunction(() => !state.saasLoading);
    assert.match(await page.locator("#actionToast").textContent(), /已更新 3 条经营记录/);
    assert.doesNotMatch(await page.locator("#actionToast").textContent(), /回填|后端|日志/);
  }, { respond: (endpoint, method) => method === "POST" && endpoint.endsWith("/merchant-memory/refresh")
    ? { body: { merchant_memory_refresh: { inserted_or_updated: 3 } } } : null });
});

test("Settings report generation explains known blockers and safely handles unknown blocker codes", async () => {
  for (const scenario of [
    { status: 200, code: "model_quota_or_billing_blocked", expected: /额度|余额/ },
    { status: 200, code: "unknown_internal_worker_code", expected: /暂时|稍后|重试/ },
    { status: 403, code: "model_authentication_failed", expected: /连接|权限/ },
  ]) {
    await withMerchantPage(async (page, requests) => {
      await page.evaluate(() => { state.saasSettingsTab = "model"; setView("connect"); });
      await page.locator('[data-saas-action="run-model-value-rehearsal"]').click();
      await page.waitForFunction(() => !state.saasLoading);
      const feedback = await page.locator("#actionToast").textContent();
      assert.match(feedback, scenario.expected);
      assert.match(feedback, /报告|上架资料/);
      assert.doesNotMatch(feedback, /live|模型证明|unknown_internal|model_authentication_failed|后端|日志/);
      assert.equal(requests.filter((request) => request.endpoint.endsWith("/model/value-rehearsal")).length, 1);
    }, { respond: (endpoint, method) => method === "POST" && endpoint.endsWith("/model/value-rehearsal")
      ? { status: scenario.status, body: { blocked_by: [scenario.code], model_value_rehearsal: { blockers: [scenario.code] } } } : null });
  }
});

test("Settings report generation success names the saved merchant outputs rather than an internal proof", async () => {
  await withMerchantPage(async (page) => {
    await page.evaluate(() => { state.saasSettingsTab = "model"; setView("connect"); });
    await page.locator('[data-saas-action="run-model-value-rehearsal"]').click();
    await page.waitForFunction(() => !state.saasLoading);
    const feedback = await page.locator("#actionToast").textContent();
    assert.match(feedback, /报告和上架资料已生成/);
    assert.match(feedback, /选品与上架|商品/);
    assert.doesNotMatch(feedback, /Market Report|Listing Package|live|证明|记忆/);
  }, { respond: (endpoint, method) => method === "POST" && endpoint.endsWith("/model/value-rehearsal")
    ? { body: { model_value_rehearsal: { status: "completed", blockers: [] } } } : null });
});

test("Settings report generation cannot claim success from an empty or unrecognized response", async () => {
  for (const body of [
    {},
    { model_value_rehearsal: {} },
    { model_value_rehearsal: { blockers: [] } },
    { model_value_rehearsal: { status: "completed" } },
    { model_value_rehearsal: { status: "completed", blockers: "not_an_array" } },
    { model_value_rehearsal: { status: "unexpected_internal_status", blockers: [] } },
    { model_value_rehearsal: { status: "blocked_before_model_rehearsal", blockers: [] } },
  ]) {
    await withMerchantPage(async (page, requests) => {
      await page.evaluate(() => { state.saasSettingsTab = "model"; setView("connect"); });
      await page.locator('[data-saas-action="run-model-value-rehearsal"]').click();
      await page.waitForFunction(() => !state.saasLoading);
      const feedback = await page.locator("#actionToast").textContent();
      assert.match(feedback, /未能确认.*完成/);
      assert.match(feedback, /刷新/);
      assert.doesNotMatch(feedback, /报告和上架资料已生成|unexpected_internal_status/);
      assert.equal(requests.filter((request) => request.method === "POST" && request.endpoint !== "/ai-ceo/chat-history/sync").length, 1);
    }, { respond: (endpoint, method) => method === "POST" && endpoint.endsWith("/model/value-rehearsal")
      ? { body } : null });
  }
});

test("Settings memory refresh cannot invent a count from an incomplete or invalid response", async () => {
  for (const body of [
    {}, { merchant_memory_refresh: {} },
    ...[null, false, "3", -1, 1.5].map((inserted_or_updated) => ({ merchant_memory_refresh: { inserted_or_updated } })),
  ]) {
    await withMerchantPage(async (page, requests) => {
      await page.evaluate(() => { state.saasSettingsTab = "model"; setView("connect"); });
      await page.locator('[data-saas-action="refresh-merchant-memory"]').click();
      await page.waitForFunction(() => !state.saasLoading);
      const feedback = await page.locator("#actionToast").textContent();
      assert.match(feedback, /未能确认.*完成/);
      assert.match(feedback, /刷新/);
      assert.doesNotMatch(feedback, /已更新.*条经营记录/);
      assert.equal(requests.filter((request) => request.method === "POST" && request.endpoint !== "/ai-ceo/chat-history/sync").length, 1);
    }, { respond: (endpoint, method) => method === "POST" && endpoint.endsWith("/merchant-memory/refresh")
      ? { body } : null });
  }
});

test("late Settings responses cannot overwrite the next store action or terminate its session", async () => {
  for (const oldAction of ["run-model-value-rehearsal", "refresh-merchant-memory"]) {
    await withMerchantPage(async (page, requests) => {
      const pending = [];
      await page.route("**/api/stores/**", async (route) => {
        if (route.request().method() !== "POST") return route.fallback();
        pending.push(route);
      });
      await page.evaluate(() => { state.saasSettingsTab = "model"; setView("connect"); });
      const oldStarted = page.waitForRequest((request) => request.method() === "POST");
      await page.locator(`[data-saas-action="${oldAction}"]`).click();
      await oldStarted;
      assert.equal(pending.length, 1);
      await page.evaluate(({ store, connection, packet, modelSettings }) => {
        resetSaasActiveProjectForStoreSwitch();
        const nextStore = { ...store, store_id: "entry-next-store" };
        state.saasStores = [nextStore];
        state.saasConnections = [{ ...connection, store_id: nextStore.store_id }];
        state.saasDataPackets = [{ ...packet, store_id: nextStore.store_id }];
        state.saasModelSettings = modelSettings;
        localStorage.setItem(saasStorageKeys.storeId, nextStore.store_id);
        state.saasLoading = false; state.saasError = "New store feedback";
        showActionToast("New store feedback"); renderSaasBackendPanel();
      }, { store, connection, packet, modelSettings });
      const nextStarted = page.waitForRequest((request) => request.method() === "POST" && request.url().includes("entry-next-store"));
      await page.locator('[data-saas-action="refresh-merchant-memory"]').click();
      await nextStarted;
      assert.equal(pending.length, 2);
      const oldResponse = page.waitForResponse((response) => response.url() === pending[0].request().url());
      await pending[0].fulfill({ status: 401, contentType: "application/json", body: JSON.stringify({ error: "old_store_expired" }) });
      await (await oldResponse).finished();
      await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))));
      assert.deepEqual(await page.evaluate(() => ({
        loading: state.saasLoading, error: state.saasError, toast: document.querySelector("#actionToast").textContent,
        store: activeSaasStore()?.store_id, session: Boolean(state.saasToken) && state.saasSessionExpiryHandled !== true,
      })), { loading: true, error: "New store feedback", toast: "New store feedback", store: "entry-next-store", session: true });
      assert.equal(requests.filter((request) => request.endpoint.startsWith("/auth/")).length, 0);
      await pending[1].fulfill({ status: 200, contentType: "application/json", body: "{}" });
      await page.waitForFunction(() => !state.saasLoading);
      assert.match(await page.locator("#actionToast").textContent(), /未能确认经营记录更新完成/);
    });
  }
});

test("Settings requests remain invalid after leaving and returning to the same account or store", async () => {
  for (const resetKind of ["account", "store"]) {
    for (const oldAction of ["run-model-value-rehearsal", "refresh-merchant-memory"]) {
      await withMerchantPage(async (page) => {
        const pending = [];
        await page.route("**/api/stores/**", async (route) => {
          if (route.request().method() !== "POST") return route.fallback();
          pending.push(route);
        });
        await page.evaluate(() => { state.saasSettingsTab = "model"; setView("connect"); });
        const oldStarted = page.waitForRequest((request) => request.method() === "POST");
        await page.locator(`[data-saas-action="${oldAction}"]`).click();
        await oldStarted;
        await page.locator(`[data-saas-action="${oldAction}"]`).dispatchEvent("click");
        assert.equal(pending.length, 1, "a duplicate click cannot submit another costly action");
        await page.evaluate(({ resetKind, store, identity, connection, packet, modelSettings }) => {
          if (resetKind === "account") {
            clearSaasSessionFromStorage(); resetSaasProtectedWorkbenchState();
          } else {
            resetSaasActiveProjectForStoreSwitch();
            localStorage.setItem(saasStorageKeys.storeId, "temporary-other-store");
            resetSaasActiveProjectForStoreSwitch();
          }
          Object.assign(state, {
            saasIdentity: identity, saasCompany: { company_id: identity.company_id }, saasUser: { user_id: identity.user_id },
            saasStores: [store], saasConnections: [connection], saasDataPackets: [packet], saasModelSettings: modelSettings,
            saasToken: "new-roundtrip-fixture-token", saasSessionExpiryHandled: false, saasConnected: true, saasProtectedStateReady: true,
            saasLoading: false, saasError: "New request feedback", saasLastModelValueRehearsal: { marker: "new-result" },
          });
          sessionStorage.setItem(saasStorageKeys.token, state.saasToken);
          localStorage.setItem(saasStorageKeys.storeId, store.store_id);
          state.saasSettingsTab = "model"; setView("connect"); showActionToast("New request feedback");
        }, { resetKind, store, identity, connection, packet, modelSettings });
        const newStarted = page.waitForRequest((request) => request.method() === "POST");
        await page.locator('[data-saas-action="refresh-merchant-memory"]').click();
        await newStarted;
        assert.equal(pending.length, 2);
        const oldResponse = page.waitForResponse((response) => response.url() === pending[0].request().url());
        await pending[0].fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
          model_value_rehearsal: { status: "completed", blockers: [], marker: "old-result" },
          merchant_memory_refresh: { inserted_or_updated: 99 },
        }) });
        await (await oldResponse).finished();
        await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))));
        assert.deepEqual(await page.evaluate(() => ({
          loading: state.saasLoading, error: state.saasError, toast: document.querySelector("#actionToast").textContent,
          result: state.saasLastModelValueRehearsal?.marker,
        })), { loading: true, error: "New request feedback", toast: "New request feedback", result: "new-result" });
        await pending[1].fulfill({ status: 200, contentType: "application/json", body: "{}" });
        await page.waitForFunction(() => !state.saasLoading);
      });
    }
  }
});

test("Settings memory refresh accepts an explicit zero without inventing newly updated records", async () => {
  await withMerchantPage(async (page) => {
    await page.evaluate(() => { state.saasSettingsTab = "model"; setView("connect"); });
    await page.locator('[data-saas-action="refresh-merchant-memory"]').click();
    await page.waitForFunction(() => !state.saasLoading);
    assert.match(await page.locator("#actionToast").textContent(), /已更新 0 条经营记录/);
  }, { respond: (endpoint, method) => method === "POST" && endpoint.endsWith("/merchant-memory/refresh")
    ? { body: { merchant_memory_refresh: { inserted_or_updated: 0 } } } : null });
});

test("an older Settings failure cannot replace a newer refresh feedback or release its busy state", async () => {
  await withMerchantPage(async (page) => {
    let actionRoute;
    await page.route("**/api/stores/entry-store/merchant-memory/refresh", (route) => { actionRoute = route; });
    await page.route("**/api/me", () => {});
    await page.evaluate(() => { state.saasSettingsTab = "model"; setView("connect"); });
    const actionStarted = page.waitForRequest((request) => request.method() === "POST");
    await page.locator('[data-saas-action="refresh-merchant-memory"]').click();
    await actionStarted;
    const refreshStarted = page.waitForRequest((request) => request.url().endsWith("/api/me"));
    await page.evaluate(() => { void refreshSaasState({ silent: true }); });
    await refreshStarted;
    await page.evaluate(() => { state.saasError = "New refresh feedback"; showActionToast("New refresh feedback"); });
    const oldResponse = page.waitForResponse((response) => response.url() === actionRoute.request().url());
    await actionRoute.fulfill({ status: 503, contentType: "application/json", body: "{}" });
    await (await oldResponse).finished();
    await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    assert.deepEqual(await page.evaluate(() => ({ loading: state.saasLoading, error: state.saasError, toast: document.querySelector("#actionToast").textContent })),
      { loading: true, error: "New refresh feedback", toast: "New refresh feedback" });
  });
});

test("bulk research preserves the selected project, candidates and manual-source path on desktop and tablet", async () => {
  for (const width of [1440, 1024]) {
    await withMerchantPage(async (page, requests) => {
      await page.evaluate(() => {
        state.saasListingComposerDraft = {
          listing_project_identity: { key: "entry-tablet-project", source_report_id: "entry-report", candidate_id: "entry-candidate" },
          product: "Tablet Stand", fields: { title: "Merchant draft title", material: "Pending" },
          merchant_product_fact_packet: { product_name: "Tablet Stand", unknown_facts: ["material"], fact_conflicts: [] },
        };
        state.saasBulkCandidates = [{ candidate_id: "keep-candidate", name: "Tablet Stand", source_type: "merchant_supplied" }];
        state.batchSourcingPrefs = ["no_battery", "not_fragile"];
        syncSaasProjectRoute("bulk", { projectId: "entry-tablet-project" });
        renderBulkFactory();
      });
      const before = await page.evaluate(() => JSON.stringify([state.saasListingComposerDraft, state.saasBulkCandidates, saasCurrentMerchantProjectId(), state.selectedPlan]));
      for (const count of [10, 50]) {
        if (count === 50) await page.evaluate(() => setView("bulk"));
        await page.locator(`[data-bulk-count="${count}"]`).click();
        await page.locator(".bulk-source-choice-grid button").first().click();
        const value = await page.locator("#ceoInput").inputValue();
        assert.match(value, new RegExp(`调研 ${count} 个`));
        assert.match(value, /不带电、不易碎/);
        assert.doesNotMatch(value, /供应商稳定|小件轻货/);
        assert.equal(await page.evaluate(() => JSON.stringify([state.saasListingComposerDraft, state.saasBulkCandidates, saasCurrentMerchantProjectId(), state.selectedPlan])), before);
      }
      await page.evaluate(() => setView("bulk"));
      await page.locator('[data-bulk-action="source-manual"]').click();
      assert.equal(await page.evaluate(() => state.view), "bulk");
      assert.equal(await page.locator("#bulkManualSourceInput").isVisible(), true);
      assert.equal(requests.filter((request) => request.method !== "GET").length, 0);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1), false);
    }, { width });
  }
});

test("Settings actions stay blocked with no selected store and rejected chat submission retains input", async () => {
  await withMerchantPage(async (page, requests) => {
    await page.evaluate(() => {
      state.saasStores = []; state.saasConnections = []; state.saasDataPackets = [];
      localStorage.removeItem(saasStorageKeys.storeId);
      state.saasSettingsTab = "model"; setView("connect");
    });
    assert.equal(await page.locator('[data-saas-action="refresh-merchant-memory"]').isDisabled(), true);
    assert.equal(await page.locator('[data-saas-action="run-model-value-rehearsal"]').isDisabled(), true);
    assert.equal(requests.filter((request) => request.method !== "GET").length, 0);
    await page.evaluate(({ store, connection }) => {
      state.saasStores = [store]; state.saasConnections = [connection];
      localStorage.setItem(saasStorageKeys.storeId, store.store_id);
      setView("cockpit"); state.saasAiCeoAttachmentUploading = true;
    }, { store, connection });
    await page.locator("#ceoInput").fill("Keep this until my upload finishes");
    await page.locator('#ceoForm button[type="submit"]').click();
    await page.evaluate(() => { state.saasAiCeoAttachmentUploading = false; setView("bulk"); setView("cockpit"); });
    assert.equal(await page.locator("#ceoInput").inputValue(), "Keep this until my upload finishes");
    assert.equal(requests.filter((request) => request.method !== "GET").length, 0);
  });
});
