#!/usr/bin/env node
/* Local browser fixture for the merchant eBay read-only OAuth confirmation flow.
   It never calls eBay and never performs a real OAuth redirect. */

const fs = require("fs");
const http = require("http");
const path = require("path");
const { chromium } = require("../output/codex-playwright-deps/node_modules/playwright-core");

const root = path.resolve(__dirname, "..");
const store = {
  store_id: "store-oauth-ui-fixture",
  platform: "ebay",
  marketplace: "EBAY_US",
  status: "read_only_pending",
  store_name: "Waiting for eBay authorization",
};
const counters = { confirmation: 0, decision: 0, preflight: 0, execute: 0, plan: 0, connectionsGet: 0 };
const planBodies = [];
let confirmations = [];
let connections = [];
let tasks = [];
let confirmationReadDelayMs = 0;
let planResponseMode = "valid";

function exactOAuthConfirmation(status = "pending", storeId = store.store_id, decidedAt = "", confirmationId = "confirm-oauth-ui-fixture") {
  return {
    confirmation_id: confirmationId,
    company_id: "company-oauth-ui-fixture",
    store_id: storeId,
    action_type: "ebay_oauth_scope_change",
    status,
    default_action: "hold",
    created_at: "2026-08-11T00:00:00Z",
    ...(decidedAt ? { decided_at: decidedAt, decided_by: "user-oauth-ui-fixture" } : {}),
    item: {
      source: "new_ebay_account_low_risk_smoke",
      requested_step: "new_account_oauth_authorization_gate",
      scope_profile: "seller_read_only",
      real_platform_writes_enabled: false,
      secret_exposed: false,
    },
  };
}

function sendJson(res, status, payload) {
  res.writeHead(status, { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" });
  res.end(JSON.stringify(payload));
}

function staticFile(pathname) {
  const relative = pathname === "/" ? "app.html" : pathname.replace(/^\/+/, "");
  if (!["app.html", "app.js", "styles.css"].includes(relative) && !relative.startsWith("assets/")) return "";
  const candidate = path.resolve(root, relative);
  return candidate.startsWith(root + path.sep) && fs.existsSync(candidate) ? candidate : "";
}

function apiPayload(pathname) {
  if (pathname === "/me") {
    return {
      identity: { company_id: "company-oauth-ui-fixture", user_id: "user-oauth-ui-fixture" },
      user: { user_id: "user-oauth-ui-fixture" },
      company: { company_id: "company-oauth-ui-fixture" },
      team_member: { role: "owner" },
    };
  }
  if (pathname === "/permissions/me") {
    return { permissions: ["manage_connections", "approve_high_risk", "create_task"], roles: ["owner"], team_member: { role: "owner" } };
  }
  if (pathname === "/stores") return { stores: [store] };
  if (pathname === "/connections") {
    counters.connectionsGet += 1;
    return { connections };
  }
  if (pathname === "/oauth/requests") {
    return {
      oauth_requests: [{
        oauth_request_id: "oauth-request-ui-fixture",
        company_id: "company-oauth-ui-fixture",
        store_id: store.store_id,
        platform: "ebay",
        status: "ready_to_redirect",
        scopes: ["https://api.ebay.com/oauth/api_scope/sell.account.readonly"],
        auth_url: "https://auth.ebay.com/oauth2/authorize?state=oauth-url-state-sentinel",
        state_nonce: "oauth-state-sentinel",
        request: {
          scope_profile: "seller_read_only",
          authorization_url: "https://auth.ebay.com/oauth2/authorize?state=oauth-url-state-sentinel",
          state_nonce: "oauth-state-sentinel",
        },
      }],
    };
  }
  if (pathname === "/confirmations") return { confirmations };
  if (pathname === "/tasks") return { tasks };
  if (pathname === "/reports") return { reports: [] };
  if (pathname === "/health") return { status: "ok" };
  if (pathname === "/health/deep") return { operational_health: { status: "ready" } };
  if (pathname === "/readiness/product-saas") return { readiness: { beta_ready: true, production_ready: false, public_charging_allowed: false } };
  if (pathname === "/merchant-onboarding/primary-ebay") {
    const connectionCurrent = connections.some((connection) => connection.store_id === store.store_id && connection.status === "read_only_authorized");
    return {
      merchant_onboarding: {
        effective_stage: connectionCurrent ? "official_sync_required" : "authorization_required",
        connection_current: connectionCurrent,
        store_id: store.store_id,
      },
    };
  }
  return {};
}

async function readBody(req) {
  const chunks = [];
  for await (const chunk of req) chunks.push(chunk);
  if (!chunks.length) return {};
  try {
    return JSON.parse(Buffer.concat(chunks).toString("utf8"));
  } catch (_error) {
    return {};
  }
}

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, "http://127.0.0.1");
  const file = staticFile(url.pathname);
  if (req.method === "GET" && file) {
    const ext = path.extname(file);
    const type = ext === ".html" ? "text/html; charset=utf-8" : ext === ".js" ? "text/javascript; charset=utf-8" : ext === ".css" ? "text/css; charset=utf-8" : "application/octet-stream";
    res.writeHead(200, { "content-type": type, "cache-control": "no-store" });
    fs.createReadStream(file).pipe(res);
    return;
  }
  if (req.method === "POST" && url.pathname === "/__fixture/plan-response-mode") {
    const body = await readBody(req);
    planResponseMode = String(body.mode || "valid");
    sendJson(res, 200, { status: "ok" });
    return;
  }
  if (req.method === "POST" && url.pathname === `/stores/${store.store_id}/ebay-oauth/read-only-confirmation`) {
    counters.confirmation += 1;
    confirmations = [
      exactOAuthConfirmation(),
      ...confirmations.filter((card) => card.action_type !== "ebay_oauth_scope_change"),
    ];
    sendJson(res, 201, {
      oauth_confirmation: {
        confirmation_id: confirmations[0].confirmation_id,
        status: "pending",
        action_type: "ebay_oauth_scope_change",
        requested_step: "new_account_oauth_authorization_gate",
        scope_profile: "seller_read_only",
        decision_required: true,
        oauth_state_created: false,
        authorization_url_created: false,
        oauth_request_created: false,
        real_platform_writes_enabled: false,
        secret_exposed: false,
      },
    });
    return;
  }
  if (req.method === "POST" && url.pathname === `/stores/${store.store_id}/ebay-oauth/read-only-plan`) {
    counters.plan += 1;
    const body = await readBody(req);
    planBodies.push(body);
    if (!body.confirmation_id) {
      sendJson(res, 409, { error: "oauth_plan_exact_approval_required" });
      return;
    }
    if (body.confirmation_id !== confirmations[0]?.confirmation_id || confirmations[0]?.status !== "approved") {
      sendJson(res, 409, { error: "oauth_plan_exact_approval_required" });
      return;
    }
    const safeScopes = [
      "https://api.ebay.com/oauth/api_scope",
      "https://api.ebay.com/oauth/api_scope/commerce.identity.readonly",
      "https://api.ebay.com/oauth/api_scope/sell.account.readonly",
      "https://api.ebay.com/oauth/api_scope/sell.inventory.readonly",
      "https://api.ebay.com/oauth/api_scope/sell.fulfillment.readonly",
      "https://api.ebay.com/oauth/api_scope/sell.finances",
    ];
    const stateNonce = "oauth-plan-state-fixture";
    const authorizationUrl = new URL("https://auth.ebay.com/oauth2/authorize");
    authorizationUrl.searchParams.set("client_id", "fixture-client");
    authorizationUrl.searchParams.set("redirect_uri", "fixture-runame");
    authorizationUrl.searchParams.set("response_type", "code");
    authorizationUrl.searchParams.set("scope", safeScopes.join(" "));
    authorizationUrl.searchParams.set("state", stateNonce);
    authorizationUrl.searchParams.set("prompt", "login");
    const responsePayload = {
      oauth_plan: {
        status: "ready_to_redirect",
        company_id: "company-oauth-ui-fixture",
        store_id: store.store_id,
        scope_profile: "seller_read_only",
        scopes: safeScopes,
        state_nonce: stateNonce,
        secret_exposed: false,
        real_platform_writes_enabled: false,
        authorization_url: authorizationUrl.toString(),
      },
      oauth_request: {
        status: "ready_to_redirect",
        company_id: "company-oauth-ui-fixture",
        store_id: store.store_id,
        scopes: safeScopes,
        state_nonce: stateNonce,
        auth_url: authorizationUrl.toString(),
        real_platform_writes_enabled: false,
        secret_exposed: false,
        request: {
          confirmation_id: body.confirmation_id,
          scope_profile: "seller_read_only",
          state_nonce: stateNonce,
          authorization_url: authorizationUrl.toString(),
          scopes: safeScopes,
          real_platform_writes_enabled: false,
          secret_exposed: false,
        },
      },
      real_platform_writes_enabled: false,
      secret_exposed: false,
    };
    const setAllAuthorizationUrls = (value) => {
      responsePayload.oauth_plan.authorization_url = value;
      responsePayload.oauth_request.auth_url = value;
      responsePayload.oauth_request.request.authorization_url = value;
    };
    if (planResponseMode === "wrong_company") responsePayload.oauth_plan.company_id = "wrong-company";
    if (planResponseMode === "wrong_store") responsePayload.oauth_request.store_id = "wrong-store";
    if (planResponseMode === "wrong_confirmation") responsePayload.oauth_request.request.confirmation_id = "wrong-confirmation";
    if (planResponseMode === "write_scope") {
      responsePayload.oauth_plan.scopes = [...safeScopes, "https://api.ebay.com/oauth/api_scope/sell.inventory"];
      responsePayload.oauth_request.scopes = [...responsePayload.oauth_plan.scopes];
    }
    if (planResponseMode === "url_write_scope") {
      const unsafeUrl = new URL(responsePayload.oauth_plan.authorization_url);
      unsafeUrl.searchParams.set("scope", [...safeScopes, "https://api.ebay.com/oauth/api_scope/sell.inventory"].join(" "));
      setAllAuthorizationUrls(unsafeUrl.toString());
    }
    if (planResponseMode === "url_unknown_scope") {
      const unsafeUrl = new URL(responsePayload.oauth_plan.authorization_url);
      unsafeUrl.searchParams.set("scope", [...safeScopes, "https://api.ebay.com/oauth/api_scope/unknown.readonly"].join(" "));
      setAllAuthorizationUrls(unsafeUrl.toString());
    }
    if (planResponseMode === "url_missing_scope") {
      const unsafeUrl = new URL(responsePayload.oauth_plan.authorization_url);
      unsafeUrl.searchParams.delete("scope");
      setAllAuthorizationUrls(unsafeUrl.toString());
    }
    if (planResponseMode === "url_duplicate_scope") {
      const unsafeUrl = new URL(responsePayload.oauth_plan.authorization_url);
      unsafeUrl.searchParams.append("scope", safeScopes.join(" "));
      setAllAuthorizationUrls(unsafeUrl.toString());
    }
    if (planResponseMode === "url_scope_mismatch") {
      const unsafeUrl = new URL(responsePayload.oauth_plan.authorization_url);
      unsafeUrl.searchParams.set("scope", [...safeScopes].reverse().join(" "));
      setAllAuthorizationUrls(unsafeUrl.toString());
    }
    if (planResponseMode === "url_empty_scope_token") {
      const unsafeUrl = new URL(responsePayload.oauth_plan.authorization_url);
      unsafeUrl.searchParams.set("scope", `${safeScopes[0]}  ${safeScopes.slice(1).join(" ")}`);
      setAllAuthorizationUrls(unsafeUrl.toString());
    }
    if (planResponseMode === "url_encoded_scope_bypass") {
      const unsafeUrl = new URL(responsePayload.oauth_plan.authorization_url);
      unsafeUrl.searchParams.set("scope", `${safeScopes.join(" ")} https%3A%2F%2Fapi.ebay.com%2Foauth%2Fapi_scope%2Fsell.inventory`);
      setAllAuthorizationUrls(unsafeUrl.toString());
    }
    if (planResponseMode === "url_state_missing") {
      const unsafeUrl = new URL(responsePayload.oauth_plan.authorization_url);
      unsafeUrl.searchParams.delete("state");
      setAllAuthorizationUrls(unsafeUrl.toString());
    }
    if (planResponseMode === "url_state_mismatch") {
      const unsafeUrl = new URL(responsePayload.oauth_plan.authorization_url);
      unsafeUrl.searchParams.set("state", "wrong-url-state");
      setAllAuthorizationUrls(unsafeUrl.toString());
    }
    if (planResponseMode === "url_duplicate_state") {
      const unsafeUrl = new URL(responsePayload.oauth_plan.authorization_url);
      unsafeUrl.searchParams.append("state", stateNonce);
      setAllAuthorizationUrls(unsafeUrl.toString());
    }
    if (planResponseMode === "request_state_mismatch") responsePayload.oauth_request.state_nonce = "wrong-request-state";
    if (planResponseMode === "nested_state_mismatch") responsePayload.oauth_request.request.state_nonce = "wrong-nested-state";
    if (planResponseMode === "request_url_mismatch") {
      const mismatchUrl = new URL(responsePayload.oauth_request.auth_url);
      mismatchUrl.searchParams.set("client_id", "wrong-client");
      responsePayload.oauth_request.auth_url = mismatchUrl.toString();
    }
    if (planResponseMode === "request_alias_url_mismatch") {
      const mismatchUrl = new URL(responsePayload.oauth_request.auth_url);
      mismatchUrl.searchParams.set("client_id", "wrong-client");
      responsePayload.oauth_request.authorization_url = mismatchUrl.toString();
    }
    if (planResponseMode === "nested_url_mismatch") {
      const mismatchUrl = new URL(responsePayload.oauth_request.request.authorization_url);
      mismatchUrl.searchParams.set("client_id", "wrong-client");
      responsePayload.oauth_request.request.authorization_url = mismatchUrl.toString();
    }
    if (planResponseMode === "extra_query") {
      const unsafeUrl = new URL(responsePayload.oauth_plan.authorization_url);
      unsafeUrl.searchParams.set("return_to", "https://attacker.invalid/");
      setAllAuthorizationUrls(unsafeUrl.toString());
    }
    if (planResponseMode === "url_fragment") {
      const unsafeUrl = new URL(responsePayload.oauth_plan.authorization_url);
      unsafeUrl.hash = "oauth-fragment-sentinel";
      setAllAuthorizationUrls(unsafeUrl.toString());
    }
    if (planResponseMode === "request_scope_mismatch") responsePayload.oauth_request.scopes = [...safeScopes].reverse();
    if (planResponseMode === "nested_scope_mismatch") responsePayload.oauth_request.request.scopes = [...safeScopes].reverse();
    if (planResponseMode === "body_write_flag") responsePayload.real_platform_writes_enabled = true;
    if (planResponseMode === "body_secret_flag") responsePayload.secret_exposed = true;
    if (planResponseMode === "plan_write_flag") responsePayload.oauth_plan.real_platform_writes_enabled = true;
    if (planResponseMode === "plan_secret_flag") responsePayload.oauth_plan.secret_exposed = true;
    if (planResponseMode === "request_write_flag") responsePayload.oauth_request.real_platform_writes_enabled = true;
    if (planResponseMode === "request_secret_flag") responsePayload.oauth_request.secret_exposed = true;
    if (planResponseMode === "nested_write_flag") responsePayload.oauth_request.request.real_platform_writes_enabled = true;
    if (planResponseMode === "nested_secret_flag") responsePayload.oauth_request.request.secret_exposed = true;
    if (planResponseMode === "missing_security_flag") delete responsePayload.oauth_request.secret_exposed;
    if (planResponseMode === "malformed_scopes") responsePayload.oauth_plan.scopes = "seller_read_only";
    if (planResponseMode === "wrong_host") responsePayload.oauth_plan.authorization_url = "https://attacker.invalid/oauth2/authorize";
    if (planResponseMode === "wrong_path") responsePayload.oauth_plan.authorization_url = "https://auth.ebay.com/signin";
    if (planResponseMode === "status_mismatch") responsePayload.oauth_request.status = "blocked_missing_oauth_config";
    if (planResponseMode === "missing_request") delete responsePayload.oauth_request;
    sendJson(res, 201, responsePayload);
    return;
  }
  if (req.method === "POST" && url.pathname === "/confirmations/confirm-oauth-ui-fixture/decision") {
    counters.decision += 1;
    const body = await readBody(req);
    if (body.decision !== "approve") {
      sendJson(res, 409, { error: "oauth_confirmation_decision_invalid" });
      return;
    }
    confirmations = confirmations.map((card) => ({
      ...card,
      status: "approved",
      decided_at: new Date().toISOString(),
      decided_by: "user-oauth-ui-fixture",
    }));
    sendJson(res, 200, { confirmation: confirmations[0] });
    return;
  }
  if (req.method === "POST" && url.pathname === "/confirmations/confirm-oauth-ui-fixture/preflight") {
    counters.preflight += 1;
    await readBody(req);
    sendJson(res, 200, { preflight: { status: "blocked" } });
    return;
  }
  if (req.method === "POST" && url.pathname === "/confirmations/confirm-oauth-ui-fixture/execute") {
    counters.execute += 1;
    await readBody(req);
    sendJson(res, 200, { execution: { status: "blocked" } });
    return;
  }
  if (req.method === "POST" && url.pathname === `/stores/${store.store_id}/connections`) {
    await readBody(req);
    sendJson(res, 201, {
      connection: {
        connection_id: "connection-oauth-ui-fixture",
        store_id: store.store_id,
        platform: "ebay",
        status: "read_only_pending",
        scopes: ["sell.account.readonly", "sell.inventory.readonly", "sell.fulfillment.readonly"],
      },
    });
    return;
  }
  if (req.method === "POST") {
    await readBody(req);
    sendJson(res, 200, {});
    return;
  }
  if (req.method === "GET" && url.pathname === "/confirmations" && confirmationReadDelayMs > 0) {
    await new Promise((resolve) => setTimeout(resolve, confirmationReadDelayMs));
  }
  sendJson(res, 200, apiPayload(url.pathname));
});

async function openAccountSettingsPage(context, base, consoleErrors) {
  const page = await context.newPage();
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  page.on("pageerror", (error) => consoleErrors.push(String(error.message || error)));
  await page.goto(`${base}/app.html?start=app`, { waitUntil: "domcontentloaded" });
  await page.waitForFunction(
    () => document.querySelector("#appShell") && !document.querySelector("#appShell").classList.contains("is-hidden"),
    null,
    { timeout: 10000 },
  );
  await showAccountSettings(page);
  await page.locator('[data-saas-action="refresh"]').first().click();
  await page.waitForTimeout(150);
  return page;
}

async function showAccountSettings(page) {
  await page.waitForTimeout(400);
  await page.locator('button[data-view="connect"]:visible').click();
  await page.waitForTimeout(100);
  const activeView = await page.evaluate(() => document.body?.dataset?.view || "");
  if (activeView !== "connect") throw new Error(`settings navigation did not activate; view=${activeView || "missing"}`);
  const accountTab = page.locator('[data-saas-settings-tab="account"]:visible');
  await accountTab.waitFor({ state: "visible", timeout: 5000 });
  await accountTab.click();
}

async function main() {
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  const base = `http://127.0.0.1:${address.port}`;
  const browser = await chromium.launch({ channel: process.env.JIEJING_PLAYWRIGHT_CHANNEL || "chrome", headless: true });
  const context = await browser.newContext({ viewport: { width: 1365, height: 900 } });
  let oauthRedirects = 0;
  await context.route("https://auth.ebay.com/**", async (route) => {
    oauthRedirects += 1;
    await route.fulfill({
      status: 200,
      contentType: "text/html",
      body: "<!doctype html><html><body><main>Local read-only OAuth handoff fixture</main></body></html>",
    });
  });
  await context.addInitScript(({ apiBase }) => {
    localStorage.setItem("jiejing_saas_api_base", apiBase);
    localStorage.setItem("jiejing_saas_backend_session_hint", "1");
    localStorage.setItem("jiejing_saas_last_account", "user-oauth-ui-fixture");
    localStorage.setItem("jiejing_saas_onboarding_done:user-oauth-ui-fixture", "1");
    localStorage.setItem("jiejing_saas_protected_snapshot:user-oauth-ui-fixture", JSON.stringify({
      version: "2026-07-12-listing-media-restore-v3",
      saved_at: new Date().toISOString(),
      account_key: "user-oauth-ui-fixture",
      connected: true,
      store_id: "store-oauth-ui-fixture",
      identity: { company_id: "company-oauth-ui-fixture", user_id: "user-oauth-ui-fixture" },
      company: { company_id: "company-oauth-ui-fixture" },
      user: { user_id: "user-oauth-ui-fixture" },
      stores: [{ store_id: "store-oauth-ui-fixture", platform: "ebay", marketplace: "EBAY_US" }],
      confirmations: [{
        confirmation_id: "oauth-old-snapshot-sentinel",
        company_id: "company-oauth-ui-fixture",
        store_id: "store-oauth-ui-fixture",
        action_type: "ebay_oauth_scope_change",
        status: "approved",
        decided_by: "owner-fixture",
        decided_at: new Date().toISOString(),
        item: {
          source: "new_ebay_account_low_risk_smoke",
          requested_step: "new_account_oauth_authorization_gate",
          scope_profile: "seller_read_only",
        },
      }],
    }));
    window.__JIEJING_FORCE_PUBLIC_MVP__ = true;
  }, { apiBase: base });
  confirmationReadDelayMs = 700;
  tasks = [{
    task_id: "latest-product-task-fixture",
    task_type: "product_workflow",
    created_at: "2026-08-11T01:00:00Z",
    input: { product: "Fixture product" },
  }];
  confirmations = [{
    confirmation_id: "latest-task-confirmation-fixture",
    company_id: "company-oauth-ui-fixture",
    store_id: store.store_id,
    task_id: tasks[0].task_id,
    action_type: "listing_publish",
    status: "approved",
    created_at: "2026-08-11T01:01:00Z",
    item: { product: "Fixture product" },
  }];
  const page = await context.newPage();
  const consoleErrors = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  page.on("pageerror", (error) => consoleErrors.push(String(error.message || error)));
  try {
    await page.goto(`${base}/app.html?start=app`, { waitUntil: "domcontentloaded" });
    try {
      await page.waitForFunction(() => document.querySelector("#appShell") && !document.querySelector("#appShell").classList.contains("is-hidden"), null, { timeout: 10000 });
    } catch (error) {
      const shell = page.locator("#appShell");
      throw new Error(`app shell did not open; count=${await shell.count()} class=${await shell.getAttribute("class")} console=${consoleErrors[0] || "none"}`);
    }
    const legacySnapshotContract = await page.evaluate(() => {
      const sentinel = "oauth-old-snapshot-sentinel";
      return {
        sensitiveStatePresent: (state.saasConfirmations || []).some((card) => String(card?.confirmation_id || "") === sentinel),
        sensitiveStoragePresent: Object.keys(localStorage).some((key) => String(localStorage.getItem(key) || "").includes(sentinel)),
      };
    });
    confirmationReadDelayMs = 0;
    if (legacySnapshotContract.sensitiveStatePresent || legacySnapshotContract.sensitiveStoragePresent) {
      throw new Error(`legacy protected snapshot must be removed before exact OAuth state can hydrate; result=${JSON.stringify(legacySnapshotContract)}`);
    }
    const approvalTimeContract = await page.evaluate(({ storeId }) => {
      const referenceNow = Date.now();
      const card = (decidedAt) => ({
        store_id: storeId,
        action_type: "ebay_oauth_scope_change",
        status: "approved",
        decided_by: "owner-fixture",
        decided_at: decidedAt,
        item: {
          source: "new_ebay_account_low_risk_smoke",
          requested_step: "new_account_oauth_authorization_gate",
          scope_profile: "seller_read_only",
        },
      });
      return {
        futureWithinClockSkew: isSaasFreshApprovedReadOnlyOAuthConfirmation(card(new Date(referenceNow + 60 * 1000).toISOString()), storeId, referenceNow),
        futureBeyondClockSkew: isSaasFreshApprovedReadOnlyOAuthConfirmation(card(new Date(referenceNow + 60 * 1000 + 1).toISOString()), storeId, referenceNow),
        invalid: isSaasFreshApprovedReadOnlyOAuthConfirmation(card("not-a-time"), storeId, referenceNow),
        naive: isSaasFreshApprovedReadOnlyOAuthConfirmation(card(new Date(referenceNow - 1000).toISOString().replace(/Z$/, "")), storeId, referenceNow),
        exactBoundary: isSaasFreshApprovedReadOnlyOAuthConfirmation(card(new Date(referenceNow - 15 * 60 * 1000).toISOString()), storeId, referenceNow),
        overBoundary: isSaasFreshApprovedReadOnlyOAuthConfirmation(card(new Date(referenceNow - 15 * 60 * 1000 - 1).toISOString()), storeId, referenceNow),
      };
    }, { storeId: store.store_id });
    if (
      !approvalTimeContract.futureWithinClockSkew ||
      approvalTimeContract.futureBeyondClockSkew ||
      approvalTimeContract.invalid ||
      approvalTimeContract.naive ||
      !approvalTimeContract.exactBoundary ||
      approvalTimeContract.overBoundary
    ) {
      throw new Error(`OAuth approval timestamp contract must allow only 60s server/browser clock skew, reject larger future/invalid/naive timestamps, and enforce the 15m inclusive age boundary; result=${JSON.stringify(approvalTimeContract)}`);
    }
    await showAccountSettings(page);
    await page.locator('[data-saas-action="plan-ebay-oauth"]').first().click();
    await page.waitForFunction(() =>
      state.saasLoading === false &&
      (state.saasConfirmations || []).some((card) => card.status === "pending" && card.action_type === "ebay_oauth_scope_change"),
      null,
      { timeout: 5000 },
    );
    if (counters.confirmation !== 1 || counters.plan !== 0) {
      throw new Error(`first click must create exactly one pending confirmation and zero OAuth plans; confirmation=${counters.confirmation} plan=${counters.plan}`);
    }
    await page.locator("#saasConfirmPanel").waitFor({ state: "visible" });
    if ((await page.locator('#saasConfirmPanel [data-saas-action="approve-confirmation"]').count()) !== 1) {
      throw new Error("pending OAuth confirmation must be visible in the confirmation center");
    }
    if (
      !(await page.locator('#saasConfirmPanel [data-saas-confirmation-flow="ebay-read-only-oauth-current-store"]').isVisible()) ||
      counters.confirmation !== 1 ||
      counters.plan !== 0
    ) {
      throw new Error("latest product task must not hide or duplicate the exact current-store OAuth pending confirmation");
    }
    const sensitiveConfirmationId = "confirm-oauth-ui-fixture";
    const pendingDom = await page.content();
    const pendingStorage = await page.evaluate(() =>
      Object.keys(localStorage).map((key) => `${key}=${localStorage.getItem(key) || ""}`).join("\n"),
    );
    const oauthRequestSentinelInState = await page.evaluate(() => {
      const serialized = JSON.stringify(state.saasOauthRequests || []);
      return serialized.includes("oauth-url-state-sentinel") || serialized.includes("oauth-state-sentinel");
    });
    const leakedToDom = pendingDom.includes(sensitiveConfirmationId);
    const leakedToStorage = pendingStorage.includes(sensitiveConfirmationId);
    const leakedToUrl = page.url().includes(sensitiveConfirmationId);
    if (leakedToDom || leakedToStorage || leakedToUrl) {
      const domLeakShape = await page.evaluate((sentinel) => {
        const element = Array.from(document.querySelectorAll("*")).reverse().find((candidate) => candidate.outerHTML.includes(sentinel));
        if (!element) return "none";
        const attributes = Array.from(element.attributes).filter((attribute) => attribute.value.includes(sentinel)).map((attribute) => attribute.name);
        return `${element.tagName.toLowerCase()}:${attributes.join(",") || "text"}:parent=${element.parentElement?.className || "none"}`;
      }, sensitiveConfirmationId);
      throw new Error(`exact OAuth confirmation identity must stay out of DOM, URL, and localStorage; dom=${leakedToDom} storage=${leakedToStorage} url=${leakedToUrl} shape=${domLeakShape}`);
    }
    if (
      oauthRequestSentinelInState ||
      pendingDom.includes("oauth-url-state-sentinel") ||
      pendingDom.includes("oauth-state-sentinel") ||
      pendingStorage.includes("oauth-url-state-sentinel") ||
      pendingStorage.includes("oauth-state-sentinel")
    ) {
      throw new Error(`seller_read_only OAuth request URL/state must be removed before frontend state/DOM/storage; state=${oauthRequestSentinelInState}`);
    }
    await page.evaluate(() => {
      const liveButton = document.querySelector('#saasConfirmPanel [data-saas-confirmation-flow="ebay-read-only-oauth-current-store"]');
      const forgedButton = liveButton?.cloneNode(true);
      if (!forgedButton) throw new Error("missing_oauth_confirmation_button_fixture");
      document.querySelector("#saasConfirmPanel")?.appendChild(forgedButton);
      forgedButton.click();
    });
    await page.waitForTimeout(150);
    if (counters.decision !== 0 || counters.preflight !== 0 || counters.execute !== 0) {
      throw new Error(`unbound opaque OAuth button must fail closed without arbitrary pending fallback; decision=${counters.decision} preflight=${counters.preflight} execute=${counters.execute}`);
    }
    const bindingAttackContract = await page.evaluate(({ companyId, primaryStoreId }) => {
      const panel = document.querySelector("#saasConfirmPanel");
      const staleButton = panel?.querySelector('[data-saas-confirmation-flow="ebay-read-only-oauth-current-store"]');
      renderSaasConfirmPanel();
      panel?.appendChild(staleButton);
      const staleBlocked = saasConfirmationIdFromActionButton(staleButton) === "";

      const primaryStore = state.saasStores.find((item) => item.store_id === primaryStoreId);
      const primaryCard = state.saasConfirmations.find((item) => item.store_id === primaryStoreId);
      const secondStoreId = "store-oauth-ui-fixture-second";
      const secondStore = { ...primaryStore, store_id: secondStoreId, store_name: "Second store" };
      const secondCard = {
        ...primaryCard,
        confirmation_id: "confirm-oauth-ui-fixture-second",
        company_id: companyId,
        store_id: secondStoreId,
        created_at: new Date(Date.now() + 1000).toISOString(),
        item: { ...primaryCard.item },
      };
      const genericPending = {
        confirmation_id: "confirm-generic-ui-fixture",
        company_id: companyId,
        store_id: primaryStoreId,
        action_type: "publish_listing",
        status: "pending",
        created_at: new Date(Date.now() + 2000).toISOString(),
        item: { source: "fixture" },
      };
      state.saasStores = [primaryStore, secondStore];
      state.saasConfirmations = [genericPending, primaryCard, secondCard];
      localStorage.setItem(saasStorageKeys.storeId, secondStoreId);
      renderSaasConfirmPanel();
      const buttons = Array.from(document.querySelectorAll('#saasConfirmPanel [data-saas-confirmation-flow="ebay-read-only-oauth-current-store"]'));
      const secondStoreMatches = buttons.map((button) => saasConfirmationIdFromActionButton(button));
      localStorage.setItem(saasStorageKeys.storeId, primaryStoreId);
      const staleAfterStoreSwitchBlocked = buttons.every((button) => saasConfirmationIdFromActionButton(button) === "");
      renderSaasConfirmPanel();
      const primaryButtons = Array.from(document.querySelectorAll('#saasConfirmPanel [data-saas-confirmation-flow="ebay-read-only-oauth-current-store"]'));
      const primaryStoreMatches = primaryButtons.map((button) => saasConfirmationIdFromActionButton(button));

      state.saasConnections = [{
        connection_id: "connection-primary-authorized-fixture",
        company_id: companyId,
        store_id: primaryStoreId,
        platform: "ebay",
        status: "read_only_authorized",
      }];
      localStorage.setItem(saasStorageKeys.storeId, secondStoreId);
      const selectedSecondStore = activeSaasStore()?.store_id === secondStoreId;
      const secondStoreConnectionMissing = saasConnectionForStore(secondStore) === null;
      const secondStoreUnauthorized = isSaasEbayReadOnlyAuthorized() === false;
      localStorage.setItem(saasStorageKeys.storeId, primaryStoreId);
      const primaryStoreAuthorized = isSaasEbayReadOnlyAuthorized() === true;

      state.saasStores = [primaryStore];
      state.saasConnections = [];
      state.saasConfirmations = [primaryCard];
      localStorage.setItem(saasStorageKeys.storeId, primaryStoreId);
      renderSaasConfirmPanel();
      return {
        staleBlocked,
        buttonCount: buttons.length,
        primaryButtonCount: primaryButtons.length,
        secondStoreMatches,
        primaryStoreMatches,
        staleAfterStoreSwitchBlocked,
        selectedSecondStore,
        secondStoreConnectionMissing,
        secondStoreUnauthorized,
        primaryStoreAuthorized,
      };
    }, { companyId: "company-oauth-ui-fixture", primaryStoreId: store.store_id });
    if (
      !bindingAttackContract.staleBlocked ||
      bindingAttackContract.buttonCount !== 1 ||
      bindingAttackContract.primaryButtonCount !== 1 ||
      bindingAttackContract.secondStoreMatches.length !== 1 ||
      bindingAttackContract.secondStoreMatches[0] !== "confirm-oauth-ui-fixture-second" ||
      bindingAttackContract.primaryStoreMatches.length !== 1 ||
      bindingAttackContract.primaryStoreMatches[0] !== sensitiveConfirmationId ||
      !bindingAttackContract.staleAfterStoreSwitchBlocked ||
      !bindingAttackContract.selectedSecondStore ||
      !bindingAttackContract.secondStoreConnectionMissing ||
      !bindingAttackContract.secondStoreUnauthorized ||
      !bindingAttackContract.primaryStoreAuthorized
    ) {
      throw new Error(`opaque OAuth buttons must bind exact card/company/store across rerender and store switches; result=${JSON.stringify(bindingAttackContract)}`);
    }
    const malformedCallCounts = { decision: counters.decision, preflight: counters.preflight, execute: counters.execute, plan: counters.plan };
    const malformedContract = await page.evaluate(async ({ companyId, storeId }) => {
      const exact = state.saasConfirmations[0];
      const malformed = [
        { ...exact, confirmation_id: "oauth-malformed-source", item: { ...exact.item, source: "merchant_metadata" } },
        { ...exact, confirmation_id: "oauth-malformed-step", item: { ...exact.item, requested_step: "wrong_step" } },
        { ...exact, confirmation_id: "oauth-malformed-scope", item: { ...exact.item, scope_profile: "seller_write" } },
        { ...exact, confirmation_id: "oauth-malformed-store", store_id: "wrong-store" },
        { ...exact, confirmation_id: "oauth-malformed-missing", item: {} },
      ];
      state.saasConfirmations = malformed;
      renderSaasConfirmPanel();
      const malformedHtml = document.querySelector("#saasConfirmPanel")?.innerHTML || "";
      const malformedIdsHidden = malformed.every((card) => !malformedHtml.includes(card.confirmation_id));
      const malformedApprovalsEnabled = Array.from(
        document.querySelectorAll('#saasConfirmPanel [data-saas-action="approve-confirmation"]'),
      ).filter((button) => !button.disabled && button.dataset.saasConfirmationFlow !== "ebay-read-only-oauth-blocked").length;
      await approveFirstSaasConfirmation(malformed[0].confirmation_id);

      const pendingA = { ...exact, confirmation_id: "oauth-duplicate-pending-a", company_id: companyId, store_id: storeId };
      const pendingB = { ...exact, confirmation_id: "oauth-duplicate-pending-b", company_id: companyId, store_id: storeId };
      const approvedB = {
        ...pendingB,
        status: "approved",
        decided_by: "owner-fixture",
        decided_at: new Date().toISOString(),
      };
      const combinations = [
        [pendingA, pendingB],
        [pendingA, approvedB],
        [{ ...pendingA, status: "approved", decided_by: "owner-fixture", decided_at: new Date().toISOString() }, approvedB],
      ];
      const duplicateResults = combinations.map((cards) => {
        state.saasConfirmations = cards;
        renderSaasConfirmPanel();
        const html = document.querySelector("#saasConfirmPanel")?.innerHTML || "";
        return {
          enabledExactButtons: document.querySelectorAll('#saasConfirmPanel [data-saas-confirmation-flow="ebay-read-only-oauth-current-store"]:not([disabled])').length,
          idsHidden: cards.every((card) => !html.includes(card.confirmation_id)),
        };
      });

      state.saasConfirmations = [exact];
      renderSaasConfirmPanel();
      return { malformedIdsHidden, malformedApprovalsEnabled, duplicateResults };
    }, { companyId: "company-oauth-ui-fixture", storeId: store.store_id });
    if (
      !malformedContract.malformedIdsHidden ||
      malformedContract.malformedApprovalsEnabled !== 0 ||
      malformedContract.duplicateResults.some((result) => result.enabledExactButtons !== 0 || !result.idsHidden) ||
      counters.decision !== malformedCallCounts.decision ||
      counters.preflight !== malformedCallCounts.preflight ||
      counters.execute !== malformedCallCounts.execute ||
      counters.plan !== malformedCallCounts.plan
    ) {
      throw new Error(`malformed/duplicate OAuth confirmations must remain value-free and execute nothing; result=${JSON.stringify(malformedContract)}`);
    }
    const duplicatePlanCount = counters.plan;
    const pendingServerConfirmations = confirmations;
    const approvedServerConfirmation = exactOAuthConfirmation("approved", store.store_id, new Date().toISOString());
    confirmations = [
      approvedServerConfirmation,
      { ...approvedServerConfirmation, confirmation_id: "oauth-duplicate-approved-plan-fixture" },
    ];
    await page.evaluate(async () => {
      await planSaasEbayReadOnlyOAuth();
    });
    confirmations = pendingServerConfirmations;
    await page.evaluate(async () => {
      await refreshSaasState({ silent: true });
      renderSaasConfirmPanel();
    });
    if (counters.plan !== duplicatePlanCount) {
      throw new Error("duplicate exact OAuth approvals must fail closed before plan POST");
    }
    await showAccountSettings(page);
    const pendingGuidanceNode = page.locator('[data-ebay-oauth-confirmation-status="pending"]');
    const pendingGuidance = (await pendingGuidanceNode.count()) ? await pendingGuidanceNode.textContent() : "";
    if (!pendingGuidance.includes("待你确认")) {
      throw new Error("pending OAuth UI must explain that owner confirmation comes before eBay authorization");
    }
    await page.locator('[data-saas-action="plan-ebay-oauth"]').first().click();
    await page.waitForTimeout(150);
    if (counters.confirmation !== 1 || counters.plan !== 0) {
      throw new Error(`pending confirmation must be idempotent in the UI; confirmation=${counters.confirmation} plan=${counters.plan}`);
    }
    await page.locator('#saasConfirmPanel [data-saas-action="approve-confirmation"]').click();
    await page.waitForFunction(() => document.querySelector("#saasConfirmPanel"));
    await page.waitForTimeout(200);
    if (counters.decision !== 1 || counters.preflight !== 0 || counters.execute !== 0) {
      throw new Error(`OAuth approval must record only the owner decision; decision=${counters.decision} preflight=${counters.preflight} execute=${counters.execute}`);
    }
    await showAccountSettings(page);
    const validRedirect = context.waitForEvent("request", {
      predicate: (request) => /^https:\/\/auth\.ebay\.com\/oauth2\/authorize(?:\?|$)/.test(request.url()),
      timeout: 5000,
    });
    await page.locator('[data-saas-action="plan-ebay-oauth"]').first().click();
    await validRedirect;
    await page.waitForTimeout(300);
    const allowedScopes = new Set([
      "https://api.ebay.com/oauth/api_scope",
      "https://api.ebay.com/oauth/api_scope/sell.account.readonly",
      "https://api.ebay.com/oauth/api_scope/sell.inventory.readonly",
      "https://api.ebay.com/oauth/api_scope/sell.fulfillment.readonly",
      "https://api.ebay.com/oauth/api_scope/sell.finances",
    ]);
    const planBody = planBodies[0] || {};
    if (
      counters.plan !== 1 ||
      planBody.confirmation_id !== "confirm-oauth-ui-fixture" ||
      !Array.isArray(planBody.scopes) ||
      planBody.scopes.some((scope) => !allowedScopes.has(scope))
    ) {
      throw new Error(`approved current-store confirmation must create one exact seller_read_only plan; plan=${counters.plan}`);
    }
    if (oauthRedirects !== 1) throw new Error(`browser must redirect only after the approved plan; redirects=${oauthRedirects}`);

    await page.close();
    for (const mode of [
      "wrong_company",
      "wrong_store",
      "wrong_confirmation",
      "write_scope",
      "url_write_scope",
      "url_unknown_scope",
      "url_missing_scope",
      "url_duplicate_scope",
      "url_scope_mismatch",
      "url_empty_scope_token",
      "url_encoded_scope_bypass",
      "url_state_missing",
      "url_state_mismatch",
      "url_duplicate_state",
      "request_state_mismatch",
      "nested_state_mismatch",
      "request_url_mismatch",
      "request_alias_url_mismatch",
      "nested_url_mismatch",
      "extra_query",
      "url_fragment",
      "request_scope_mismatch",
      "nested_scope_mismatch",
      "body_write_flag",
      "body_secret_flag",
      "plan_write_flag",
      "plan_secret_flag",
      "request_write_flag",
      "request_secret_flag",
      "nested_write_flag",
      "nested_secret_flag",
      "missing_security_flag",
      "malformed_scopes",
      "wrong_host",
      "wrong_path",
      "status_mismatch",
      "missing_request",
    ]) {
      await fetch(`${base}/__fixture/plan-response-mode`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ mode }),
      });
      confirmations = [exactOAuthConfirmation("approved", store.store_id, new Date().toISOString())];
      connections = [];
      const attackCounts = { plan: counters.plan, redirects: oauthRedirects };
      const attackPage = await openAccountSettingsPage(context, base, consoleErrors);
      let attackPagePlanRequests = 0;
      attackPage.on("request", (request) => {
        if (request.method() === "POST" && request.url().endsWith(`/stores/${store.store_id}/ebay-oauth/read-only-plan`)) {
          attackPagePlanRequests += 1;
        }
      });
      await attackPage.locator('[data-saas-action="plan-ebay-oauth"]').first().click();
      await attackPage.waitForTimeout(800);
      if (attackPagePlanRequests !== 1 || counters.plan < attackCounts.plan + 1 || oauthRedirects !== attackCounts.redirects) {
        throw new Error(`malformed OAuth plan response must fail closed without redirect; mode=${mode} plan=${counters.plan} redirects=${oauthRedirects}`);
      }
      await showAccountSettings(attackPage);
      await attackPage.locator('[data-saas-action="plan-ebay-oauth"]').first().click();
      await attackPage.waitForTimeout(300);
      if (attackPagePlanRequests !== 1) {
        throw new Error(`malformed OAuth plan response must not retry or consume the same confirmation twice; mode=${mode} page_plan_requests=${attackPagePlanRequests}`);
      }
      const attackStorage = await attackPage.evaluate(() => JSON.stringify(localStorage));
      if (attackStorage.includes("wrong-confirmation") || attackStorage.includes("attacker.invalid")) {
        throw new Error(`malformed OAuth plan response must not persist response values; mode=${mode}`);
      }
      await attackPage.close();
    }

    await fetch(`${base}/__fixture/plan-response-mode`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ mode: "missing_request" }),
    });
    confirmations = [exactOAuthConfirmation("approved", store.store_id, new Date().toISOString())];
    const concurrentPage = await openAccountSettingsPage(context, base, consoleErrors);
    let concurrentPagePlanRequests = 0;
    concurrentPage.on("request", (request) => {
      if (request.method() === "POST" && request.url().endsWith(`/stores/${store.store_id}/ebay-oauth/read-only-plan`)) {
        concurrentPagePlanRequests += 1;
      }
    });
    await concurrentPage.evaluate(async () => {
      await Promise.allSettled([window.planSaasEbayReadOnlyOAuth(), window.planSaasEbayReadOnlyOAuth()]);
    });
    await concurrentPage.waitForTimeout(500);
    if (concurrentPagePlanRequests !== 1) {
      throw new Error(`concurrent OAuth clicks must claim one in-memory exact confirmation attempt; page_plan_requests=${concurrentPagePlanRequests}`);
    }
    await concurrentPage.close();

    await fetch(`${base}/__fixture/plan-response-mode`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ mode: "valid" }),
    });
    confirmations = [exactOAuthConfirmation("approved", store.store_id, new Date().toISOString())];
    const networkPage = await openAccountSettingsPage(context, base, consoleErrors);
    await networkPage.evaluate(({ storeId }) => {
      const originalFetch = window.fetch.bind(window);
      window.__fixturePlanFetchAttempts = 0;
      window.fetch = (input, init) => {
        const target = typeof input === "string" ? input : String(input?.url || input || "");
        if (target.endsWith(`/stores/${storeId}/ebay-oauth/read-only-plan`)) {
          window.__fixturePlanFetchAttempts += 1;
          return Promise.reject(new TypeError("fixture_network_error"));
        }
        return originalFetch(input, init);
      };
    }, { storeId: store.store_id });
    const networkAttemptCount = async () => networkPage.evaluate(() => window.__fixturePlanFetchAttempts);
    await networkPage.locator('[data-saas-action="plan-ebay-oauth"]').first().click();
    await networkPage.waitForFunction(() => window.__fixturePlanFetchAttempts === 1 && state.saasLoading === false, null, { timeout: 5000 });
    if ((await networkAttemptCount()) !== 1) {
      throw new Error(`network failure fixture must reach exactly one initial plan attempt; fetch_attempts=${await networkAttemptCount()}`);
    }
    const networkClaimCount = await networkPage.evaluate(() => saasReadOnlyOAuthPlanAttemptKeys.size);
    if (networkClaimCount !== 1) {
      throw new Error(`network failure must retain one memory-only confirmation claim; claims=${networkClaimCount}`);
    }
    await showAccountSettings(networkPage);
    await networkPage.locator('[data-saas-action="plan-ebay-oauth"]').first().click();
    await networkPage.waitForFunction(
      () => String(state.saasError || "").includes("oauth_plan_already_attempted_in_this_page"),
      null,
      { timeout: 5000 },
    );
    if ((await networkAttemptCount()) !== 1) {
      throw new Error(`network failure must not retry the same confirmation in this page; fetch_attempts=${await networkAttemptCount()}`);
    }
    await networkPage.close();

    await fetch(`${base}/__fixture/plan-response-mode`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ mode: "missing_request" }),
    });
    confirmations = [exactOAuthConfirmation("approved", store.store_id, new Date().toISOString(), "oauth-replaced-old-sentinel")];
    const replacementPage = await openAccountSettingsPage(context, base, consoleErrors);
    let replacementPagePlanRequests = 0;
    replacementPage.on("request", (request) => {
      if (request.method() === "POST" && request.url().endsWith(`/stores/${store.store_id}/ebay-oauth/read-only-plan`)) {
        replacementPagePlanRequests += 1;
      }
    });
    await replacementPage.locator('[data-saas-action="plan-ebay-oauth"]').first().click();
    await replacementPage.waitForTimeout(500);
    confirmations = [exactOAuthConfirmation("approved", store.store_id, new Date().toISOString(), "oauth-replaced-new-sentinel")];
    await showAccountSettings(replacementPage);
    await replacementPage.locator('[data-saas-action="plan-ebay-oauth"]').first().click();
    await replacementPage.waitForTimeout(500);
    if (replacementPagePlanRequests !== 2) {
      throw new Error(`a distinct live replacement confirmation must receive its own in-memory claim; page_plan_requests=${replacementPagePlanRequests}`);
    }
    const replacementStorage = await replacementPage.evaluate(() => JSON.stringify(localStorage));
    if (replacementStorage.includes("oauth-replaced-old-sentinel") || replacementStorage.includes("oauth-replaced-new-sentinel")) {
      throw new Error("OAuth plan attempt claims must remain memory-only");
    }
    await replacementPage.close();

    await fetch(`${base}/__fixture/plan-response-mode`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ mode: "valid" }),
    });
    const authorizedCounts = { confirmation: counters.confirmation, plan: counters.plan };
    connections = [{
      connection_id: "connection-oauth-ui-fixture",
      store_id: store.store_id,
      platform: "ebay",
      status: "read_only_authorized",
    }];
    const authorizedPage = await openAccountSettingsPage(context, base, consoleErrors);
    const authorizedButton = authorizedPage.locator('[data-saas-action="plan-ebay-oauth"]').first();
    await authorizedPage.waitForTimeout(800);
    if (!(await authorizedButton.isDisabled())) {
      const shapes = await authorizedPage.locator('[data-saas-action="plan-ebay-oauth"]').evaluateAll((nodes) => nodes.map((node) => ({ disabled: node.disabled, hidden: node.offsetParent === null })));
      throw new Error(`authorized current store must disable repeat OAuth; connection_reads=${counters.connectionsGet} buttons=${JSON.stringify(shapes)}`);
    }
    if (counters.confirmation !== authorizedCounts.confirmation || counters.plan !== authorizedCounts.plan) {
      throw new Error("authorized current store must not create another confirmation or OAuth plan");
    }
    await authorizedPage.close();

    connections = [];
    confirmations = [exactOAuthConfirmation("rejected")];
    const rejectedCounts = { confirmation: counters.confirmation, plan: counters.plan };
    const rejectedPage = await openAccountSettingsPage(context, base, consoleErrors);
    await rejectedPage.evaluate(async () => {
      await planSaasEbayReadOnlyOAuth();
    });
    if (counters.confirmation !== rejectedCounts.confirmation || counters.plan !== rejectedCounts.plan) {
      throw new Error("rejected exact confirmation must fail closed without intake or plan");
    }
    await rejectedPage.close();

    confirmations = [
      exactOAuthConfirmation("approved", store.store_id, "2026-01-01T00:00:00Z"),
      exactOAuthConfirmation("expired", store.store_id, "2025-12-31T23:58:00Z", "confirm-oauth-history-expired-fixture"),
      exactOAuthConfirmation("rejected", store.store_id, "2025-12-31T23:57:00Z", "confirm-oauth-history-rejected-fixture"),
    ];
    const expiredCounts = { confirmation: counters.confirmation, plan: counters.plan };
    const expiredPage = await openAccountSettingsPage(context, base, consoleErrors);
    await expiredPage.locator('[data-saas-action="plan-ebay-oauth"]').first().click();
    await expiredPage.waitForTimeout(800);
    if (
      counters.plan !== expiredCounts.plan ||
      counters.confirmation !== expiredCounts.confirmation + 1 ||
      confirmations[0]?.status !== "pending"
    ) {
      throw new Error("expired exact confirmation must ignore historical terminal OAuth cards and atomically request one replacement pending card without creating an OAuth plan");
    }
    await expiredPage.close();

    confirmations = [exactOAuthConfirmation("pending", "store-wrong-oauth-ui-fixture")];
    const wrongStoreCounts = { confirmation: counters.confirmation, plan: counters.plan };
    const wrongStorePage = await openAccountSettingsPage(context, base, consoleErrors);
    await wrongStorePage.locator('[data-saas-action="plan-ebay-oauth"]').first().click();
    await wrongStorePage.waitForTimeout(800);
    if (counters.confirmation !== wrongStoreCounts.confirmation + 1 || counters.plan !== wrongStoreCounts.plan) {
      throw new Error(`wrong-store confirmation must never authorize the current store plan; confirmation=${counters.confirmation} expected=${wrongStoreCounts.confirmation + 1} plan=${counters.plan} expectedPlan=${wrongStoreCounts.plan}`);
    }
    await wrongStorePage.setViewportSize({ width: 390, height: 844 });
    await showAccountSettings(wrongStorePage);
    const mobileLayout = await wrongStorePage.evaluate(() => {
      const guidance = document.querySelector(".saas-oauth-confirmation-guidance");
      const rect = guidance?.getBoundingClientRect();
      return {
        documentWidth: document.documentElement.scrollWidth,
        viewportWidth: window.innerWidth,
        guidanceLeft: rect?.left ?? -1,
        guidanceRight: rect?.right ?? window.innerWidth + 1,
      };
    });
    if (
      mobileLayout.documentWidth > mobileLayout.viewportWidth + 1 ||
      mobileLayout.guidanceLeft < 0 ||
      mobileLayout.guidanceRight > mobileLayout.viewportWidth + 1
    ) {
      throw new Error(`mobile OAuth confirmation guidance must not overflow; layout=${JSON.stringify(mobileLayout)}`);
    }
    await wrongStorePage.close();

    if (consoleErrors.length) throw new Error(`browser console must stay clean: ${consoleErrors[0]}`);
    process.stdout.write("PASS jiejing_oauth_confirmation_first_click\n");
  } finally {
    await context.close();
    await browser.close();
    await new Promise((resolve) => server.close(resolve));
  }
}

main().catch((error) => {
  process.stderr.write(`FAIL jiejing_oauth_confirmation_first_click: ${error.message}\n`);
  process.exitCode = 1;
});
