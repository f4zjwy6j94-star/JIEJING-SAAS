#!/usr/bin/env node
/* Local-only browser fixture for confirmation-gated eBay unpublished-draft OAuth.
   No request is allowed to reach eBay and no platform write is performed. */

const fs = require("fs");
const http = require("http");
const path = require("path");
const { chromium } = require("../output/codex-playwright-deps/node_modules/playwright-core");

const root = path.resolve(__dirname, "..");
const companyId = "company-draft-oauth-ui";
const userId = "user-draft-oauth-ui";
const store = {
  store_id: "store-draft-oauth-ui",
  platform: "ebay",
  marketplace: "EBAY_US",
  status: "read_only_authorized",
  store_name: "Current fixture store",
};
const wrongStore = {
  store_id: "store-first-but-not-active",
  platform: "ebay",
  marketplace: "EBAY_US",
  status: "not_connected",
  store_name: "Must never receive the draft plan",
};
const scopes = [
  "https://api.ebay.com/oauth/api_scope",
  "https://api.ebay.com/oauth/api_scope/commerce.identity.readonly",
  "https://api.ebay.com/oauth/api_scope/sell.account.readonly",
  "https://api.ebay.com/oauth/api_scope/sell.inventory",
  "https://api.ebay.com/oauth/api_scope/sell.inventory.readonly",
  "https://api.ebay.com/oauth/api_scope/sell.fulfillment.readonly",
  "https://api.ebay.com/oauth/api_scope/sell.finances",
];
const counters = { intake: 0, decision: 0, preflight: 0, execute: 0, plan: 0 };
const planBodies = [];
let confirmations = [];
let connections = [readOnlyConnection()];
let responseMode = "valid";
let serverClockOffsetMs = 0;

function readOnlyConnection(status = "read_only_authorized") {
  return {
    connection_id: "connection-draft-oauth-ui",
    company_id: companyId,
    store_id: store.store_id,
    platform: "ebay",
    status,
    scopes: scopes.filter((scope) => !scope.endsWith("/sell.inventory")),
  };
}

function exactConfirmation({
  status = "pending",
  storeId = store.store_id,
  confirmationId = "confirm-draft-oauth-ui",
  decidedAt = "",
  item = {},
} = {}) {
  return {
    confirmation_id: confirmationId,
    company_id: companyId,
    store_id: storeId,
    action_type: "ebay_oauth_scope_change",
    title: "Approve eBay access to save unpublished drafts",
    status,
    default_action: "hold",
    created_at: new Date().toISOString(),
    ...(decidedAt ? { decided_at: decidedAt, decided_by: userId } : {}),
    item: {
      action_type: "ebay_oauth_scope_change",
      source: "controlled_ebay_unpublished_draft_save",
      requested_step: "unpublished_draft_oauth_authorization_gate",
      scope_profile: "seller_unpublished_draft",
      draft_save_capability_requested: true,
      public_publish_enabled: false,
      real_platform_writes_enabled: false,
      secret_exposed: false,
      ...item,
    },
  };
}

function sendJson(res, status, payload) {
  res.writeHead(status, {
    "content-type": "application/json; charset=utf-8",
    "cache-control": "no-store",
    date: new Date(Date.now() + serverClockOffsetMs).toUTCString(),
  });
  res.end(JSON.stringify(payload));
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

function staticFile(pathname) {
  const relative = pathname === "/" ? "app.html" : pathname.replace(/^\/+/, "");
  if (!["app.html", "app.js", "styles.css"].includes(relative) && !relative.startsWith("assets/")) return "";
  const candidate = path.resolve(root, relative);
  return candidate.startsWith(root + path.sep) && fs.existsSync(candidate) ? candidate : "";
}

function getPayload(pathname) {
  if (pathname === "/me") {
    return {
      identity: { company_id: companyId, user_id: userId },
      user: { user_id: userId },
      company: { company_id: companyId },
      team_member: { role: "owner" },
    };
  }
  if (pathname === "/permissions/me") {
    return { permissions: ["manage_connections", "approve_high_risk"], roles: ["owner"], team_member: { role: "owner" } };
  }
  if (pathname === "/stores") return { stores: [wrongStore, store] };
  if (pathname === "/connections") return { connections };
  if (pathname === "/confirmations") return { confirmations };
  if (pathname === "/oauth/requests") return { oauth_requests: [] };
  if (pathname === "/tasks") return { tasks: [] };
  if (pathname === "/reports") return { reports: [] };
  if (pathname === "/health") return { status: "ok" };
  if (pathname === "/health/deep") return { operational_health: { status: "ready" } };
  if (pathname === "/readiness/product-saas") {
    return { readiness: { beta_ready: true, production_ready: false, public_charging_allowed: false } };
  }
  if (pathname === "/merchant-onboarding/primary-ebay") {
    return { merchant_onboarding: { effective_stage: "official_sync_required", connection_current: true, store_id: store.store_id } };
  }
  return {};
}

function authorizationUrl(stateNonce = "draft-oauth-state-local") {
  const url = new URL("https://auth.ebay.com/oauth2/authorize");
  url.searchParams.set("client_id", "fixture-client");
  url.searchParams.set("redirect_uri", "fixture-runame");
  url.searchParams.set("response_type", "code");
  url.searchParams.set("scope", scopes.join(" "));
  url.searchParams.set("state", stateNonce);
  url.searchParams.set("prompt", "login");
  return url.toString();
}

function planResponse(body) {
  const stateNonce = "draft-oauth-state-local";
  const url = authorizationUrl(stateNonce);
  const security = {
    draft_save_capability_requested: true,
    public_publish_enabled: false,
    real_platform_writes_enabled: false,
    secret_exposed: false,
  };
  const plan = {
    status: "ready_to_redirect",
    company_id: companyId,
    store_id: store.store_id,
    confirmation_id: body.confirmation_id,
    scope_profile: "seller_unpublished_draft",
    scopes: [...scopes],
    state_nonce: stateNonce,
    authorization_url: url,
    write_actions_requested: ["save_ebay_listing_draft"],
    ...security,
  };
  const requestBody = {
    ...plan,
    authorization_url: url,
  };
  const request = {
    status: "ready_to_redirect",
    company_id: companyId,
    store_id: store.store_id,
    confirmation_id: body.confirmation_id,
    scopes: [...scopes],
    state_nonce: stateNonce,
    auth_url: url,
    request: requestBody,
    ...security,
  };
  const payload = { oauth_plan: plan, oauth_request: request, ...security };
  if (responseMode === "wrong_company") payload.oauth_plan.company_id = "wrong-company";
  if (responseMode === "wrong_store") payload.oauth_request.request.store_id = "wrong-store";
  if (responseMode === "wrong_plan_confirmation") payload.oauth_plan.confirmation_id = "wrong-confirmation";
  if (responseMode === "wrong_request_confirmation") payload.oauth_request.confirmation_id = "wrong-confirmation";
  if (responseMode === "wrong_nested_confirmation") payload.oauth_request.request.confirmation_id = "wrong-confirmation";
  if (responseMode === "bad_flags") payload.oauth_request.public_publish_enabled = true;
  if (responseMode === "bad_scopes") payload.oauth_request.request.scopes = [...scopes].reverse();
  if (responseMode === "bad_url_state") {
    const badUrl = new URL(url);
    badUrl.searchParams.set("state", "wrong-state");
    payload.oauth_plan.authorization_url = badUrl.toString();
    payload.oauth_request.auth_url = badUrl.toString();
    payload.oauth_request.request.authorization_url = badUrl.toString();
  }
  return payload;
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
  if (req.method === "POST" && url.pathname === `/stores/${store.store_id}/ebay-oauth/unpublished-draft-confirmation`) {
    counters.intake += 1;
    confirmations = [exactConfirmation()];
    const card = confirmations[0];
    sendJson(res, 201, {
      oauth_confirmation: {
        confirmation_id: card.confirmation_id,
        company_id: companyId,
        store_id: store.store_id,
        status: "pending",
        action_type: "ebay_oauth_scope_change",
        source: "controlled_ebay_unpublished_draft_save",
        requested_step: "unpublished_draft_oauth_authorization_gate",
        scope_profile: "seller_unpublished_draft",
        decision_required: true,
        oauth_state_created: false,
        authorization_url_created: false,
        oauth_request_created: false,
        draft_save_capability_requested: true,
        public_publish_enabled: false,
        real_platform_writes_enabled: false,
        secret_exposed: false,
      },
    });
    return;
  }
  if (req.method === "POST" && /^\/confirmations\/[^/]+\/decision$/.test(url.pathname)) {
    counters.decision += 1;
    const body = await readBody(req);
    const confirmationId = decodeURIComponent(url.pathname.split("/")[2] || "");
    const card = confirmations.find((candidate) => candidate.confirmation_id === confirmationId);
    if (!card || card.status !== "pending" || body.decision !== "approve") {
      sendJson(res, 409, { error: "exact_pending_confirmation_required" });
      return;
    }
    confirmations = confirmations.map((candidate) =>
      candidate.confirmation_id === confirmationId
        ? { ...candidate, status: "approved", decided_at: new Date(Date.now() + serverClockOffsetMs).toISOString(), decided_by: userId }
        : candidate,
    );
    sendJson(res, 201, { confirmation: confirmations.find((candidate) => candidate.confirmation_id === confirmationId) });
    return;
  }
  if (req.method === "POST" && /^\/confirmations\/[^/]+\/preflight$/.test(url.pathname)) {
    counters.preflight += 1;
    await readBody(req);
    sendJson(res, 409, { error: "draft_oauth_must_never_preflight" });
    return;
  }
  if (req.method === "POST" && /^\/confirmations\/[^/]+\/execute$/.test(url.pathname)) {
    counters.execute += 1;
    await readBody(req);
    sendJson(res, 409, { error: "draft_oauth_must_never_execute" });
    return;
  }
  if (req.method === "POST" && url.pathname === `/stores/${store.store_id}/ebay-oauth/unpublished-draft-plan`) {
    counters.plan += 1;
    const body = await readBody(req);
    planBodies.push(body);
    const card = confirmations.find((candidate) => candidate.confirmation_id === body.confirmation_id);
    if (
      !card ||
      card.status !== "approved" ||
      body.scope_profile !== "seller_unpublished_draft" ||
      JSON.stringify(body.scopes) !== JSON.stringify(scopes)
    ) {
      sendJson(res, 409, { error: "exact_draft_approval_required" });
      return;
    }
    confirmations = confirmations.map((candidate) =>
      candidate.confirmation_id === card.confirmation_id ? { ...candidate, status: "executed" } : candidate,
    );
    sendJson(res, 201, planResponse(body));
    return;
  }
  if (req.method === "POST") {
    await readBody(req);
    sendJson(res, 200, {});
    return;
  }
  sendJson(res, 200, getPayload(url.pathname));
});

async function showAccountSettings(page) {
  await page.waitForTimeout(250);
  await page.locator('button[data-view="connect"]:visible').click();
  await page.locator('[data-saas-settings-tab="account"]:visible').waitFor({ state: "visible", timeout: 5000 });
  await page.locator('[data-saas-settings-tab="account"]:visible').click();
  await page.waitForTimeout(100);
}

async function openPage(context, base, consoleErrors) {
  const page = await context.newPage();
  page.on("console", (message) => {
    if (["error", "warning"].includes(message.type())) consoleErrors.push(message.text());
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
  await page.waitForTimeout(120);
  return page;
}

function resetFixture({ cards = [], connectionStatus = "read_only_authorized", mode = "valid", clockOffsetMs = 0 } = {}) {
  confirmations = cards;
  connections = [readOnlyConnection(connectionStatus)];
  responseMode = mode;
  serverClockOffsetMs = clockOffsetMs;
}

async function assertNoSensitiveConfirmationLeak(page, confirmationId, consoleErrors) {
  const leak = await page.evaluate((id) => ({
    dom: document.documentElement.innerHTML.includes(id),
    url: window.location.href.includes(id),
    storage: Object.keys(localStorage).some((key) => key.includes(id) || String(localStorage.getItem(key) || "").includes(id)),
  }), confirmationId);
  if (leak.dom || leak.url || leak.storage || consoleErrors.some((line) => line.includes(confirmationId))) {
    throw new Error(`OAuth confirmation ID leaked to public browser surfaces: ${JSON.stringify(leak)}`);
  }
}

async function main() {
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  const base = `http://127.0.0.1:${address.port}`;
  const browser = await chromium.launch({ channel: process.env.JIEJING_PLAYWRIGHT_CHANNEL || "chrome", headless: true });
  const context = await browser.newContext({ viewport: { width: 1365, height: 900 } });
  const consoleErrors = [];
  let oauthRedirects = 0;
  await context.route("https://auth.ebay.com/**", async (route) => {
    oauthRedirects += 1;
    await route.fulfill({
      status: 200,
      contentType: "text/html",
      body: "<!doctype html><html><body><main>Local unpublished-draft OAuth handoff fixture</main></body></html>",
    });
  });
  await context.addInitScript(({ apiBase, company, user, storeId }) => {
    localStorage.setItem("jiejing_saas_api_base", apiBase);
    localStorage.setItem("jiejing_saas_backend_session_hint", "1");
    localStorage.setItem("jiejing_saas_last_account", user);
    localStorage.setItem(`jiejing_saas_onboarding_done:${user}`, "1");
    localStorage.setItem("jiejing_saas_selected_store_id", storeId);
    localStorage.setItem(`jiejing_saas_protected_snapshot:${user}`, JSON.stringify({
      version: "2026-07-12-listing-media-restore-v3",
      saved_at: new Date().toISOString(),
      account_key: user,
      connected: true,
      store_id: storeId,
      identity: { company_id: company, user_id: user },
      company: { company_id: company },
      user: { user_id: user },
      stores: [{ store_id: storeId, platform: "ebay", marketplace: "EBAY_US" }],
      confirmations: [],
    }));
  }, { apiBase: base, company: companyId, user: userId, storeId: store.store_id });

  try {
    resetFixture();
    const firstCounts = { ...counters };
    const page = await openPage(context, base, consoleErrors);
    const draftButton = page.locator('[data-saas-action="plan-ebay-draft-oauth"]:visible').first();
    await draftButton.click();
    await page.waitForTimeout(400);
    if (counters.intake !== firstCounts.intake + 1 || counters.plan !== firstCounts.plan || oauthRedirects !== 0) {
      throw new Error("first click must create exactly one pending confirmation and no plan/redirect");
    }
    await assertNoSensitiveConfirmationLeak(page, "confirm-draft-oauth-ui", consoleErrors);
    const approve = page.locator('[data-saas-action="approve-confirmation"]:not([disabled])').first();
    await approve.click();
    await page.waitForTimeout(400);
    if (counters.decision !== firstCounts.decision + 1 || counters.preflight !== 0 || counters.execute !== 0 || counters.plan !== firstCounts.plan) {
      throw new Error("confirmation approval must be decision-only with no preflight, execute, or OAuth plan");
    }
    await showAccountSettings(page);
    await page.locator('[data-saas-action="plan-ebay-draft-oauth"]:visible').first().click();
    await page.waitForFunction(() => document.body?.textContent?.includes("Local unpublished-draft OAuth handoff fixture"), null, { timeout: 5000 });
    if (counters.plan !== firstCounts.plan + 1 || oauthRedirects !== 1) {
      throw new Error("second click with one exact fresh approval must create one exact plan and local fulfilled redirect");
    }
    const body = planBodies.at(-1) || {};
    if (
      body.confirmation_id !== "confirm-draft-oauth-ui" ||
      body.scope_profile !== "seller_unpublished_draft" ||
      JSON.stringify(body.scopes) !== JSON.stringify(scopes)
    ) throw new Error("draft plan request did not bind the exact confirmation/profile/scopes");
    await page.close();

    const sixMinuteServerLeadMs = 6 * 60 * 1000;
    resetFixture({
      cards: [exactConfirmation({
        status: "approved",
        decidedAt: new Date(Date.now() + sixMinuteServerLeadMs).toISOString(),
      })],
      clockOffsetMs: sixMinuteServerLeadMs,
    });
    const serverClockBefore = { ...counters, redirects: oauthRedirects };
    const serverClockPage = await openPage(context, base, consoleErrors);
    await serverClockPage.evaluate(async () => planSaasEbayUnpublishedDraftOAuth());
    await serverClockPage.waitForTimeout(300);
    if (counters.plan !== serverClockBefore.plan + 1 || oauthRedirects !== serverClockBefore.redirects + 1) {
      throw new Error("a fresh approval must use the trusted response server clock when the browser clock is six minutes behind");
    }
    await serverClockPage.close();

    for (const [name, cards, expectedIntakeDelta] of [
      ["malformed", [exactConfirmation({ item: { public_publish_enabled: true } })], 0],
      ["unbound", [exactConfirmation({ storeId: "" })], 0],
      ["duplicate", [exactConfirmation(), exactConfirmation({ confirmationId: "confirm-draft-oauth-duplicate" })], 0],
      ["wrong-store", [exactConfirmation({ storeId: wrongStore.store_id })], 1],
      ["future", [exactConfirmation({ status: "approved", decidedAt: new Date(Date.now() + 5 * 60 * 1000).toISOString() })], 0],
      ["expired", [exactConfirmation({ status: "approved", decidedAt: new Date(Date.now() - 20 * 60 * 1000).toISOString() })], 1],
    ]) {
      resetFixture({ cards });
      const before = { ...counters, redirects: oauthRedirects };
      const attackPage = await openPage(context, base, consoleErrors);
      await attackPage.evaluate(async () => planSaasEbayUnpublishedDraftOAuth());
      await attackPage.waitForTimeout(250);
      if (
        counters.intake !== before.intake + expectedIntakeDelta ||
        counters.plan !== before.plan ||
        oauthRedirects !== before.redirects
      ) throw new Error(`${name} confirmation must preserve the exact intake/plan boundary`);
      if (name === "expired" && (confirmations.length !== 1 || confirmations[0]?.status !== "pending")) {
        throw new Error("an expired exact draft OAuth approval must become one replacement pending confirmation");
      }
      await attackPage.close();
    }

    resetFixture({ cards: [exactConfirmation({ status: "approved", decidedAt: new Date().toISOString() })], connectionStatus: "draft_save_authorized" });
    const authorizedBefore = { ...counters, redirects: oauthRedirects };
    const authorizedPage = await openPage(context, base, consoleErrors);
    await authorizedPage.evaluate(async () => planSaasEbayUnpublishedDraftOAuth());
    if (counters.intake !== authorizedBefore.intake || counters.plan !== authorizedBefore.plan || oauthRedirects !== authorizedBefore.redirects) {
      throw new Error("already-authorized store must not repeat intake, plan, or redirect");
    }
    const authorizedText = await authorizedPage.locator('[data-saas-action="plan-ebay-draft-oauth"]:visible').first().textContent();
    if (!String(authorizedText || "").includes("草稿") || String(authorizedText || "").includes("发布")) {
      throw new Error("authorized UI must use unpublished-draft semantics, never public-publish wording");
    }
    await authorizedPage.close();

    for (const mode of [
      "wrong_company",
      "wrong_store",
      "wrong_plan_confirmation",
      "wrong_request_confirmation",
      "wrong_nested_confirmation",
      "bad_flags",
      "bad_scopes",
      "bad_url_state",
    ]) {
      resetFixture({ cards: [exactConfirmation({ status: "approved", decidedAt: new Date().toISOString() })], mode });
      const before = { ...counters, redirects: oauthRedirects };
      const attackPage = await openPage(context, base, consoleErrors);
      await attackPage.evaluate(async () => planSaasEbayUnpublishedDraftOAuth());
      await attackPage.waitForTimeout(200);
      if (counters.plan !== before.plan + 1 || oauthRedirects !== before.redirects) {
        throw new Error(`${mode} plan response must be attempted once then fail closed before redirect`);
      }
      await attackPage.close();
    }

    resetFixture({ cards: [exactConfirmation({ status: "approved", decidedAt: new Date().toISOString() })], mode: "bad_flags" });
    const oneShotBefore = counters.plan;
    const oneShotPage = await openPage(context, base, consoleErrors);
    await oneShotPage.evaluate(async () => {
      await planSaasEbayUnpublishedDraftOAuth();
      await planSaasEbayUnpublishedDraftOAuth();
    });
    if (counters.plan !== oneShotBefore + 1) throw new Error("one page must attempt the exact draft OAuth plan at most once");
    await oneShotPage.close();

    if (counters.preflight !== 0 || counters.execute !== 0) throw new Error("draft OAuth browser flow must never preflight or execute a platform action");
    if (consoleErrors.length) throw new Error(`browser console must stay clean: ${consoleErrors[0]}`);
    process.stdout.write("PASS jiejing_unpublished_draft_oauth_browser\n");
  } finally {
    await context.close();
    await browser.close();
    await new Promise((resolve) => server.close(resolve));
  }
}

main().catch((error) => {
  process.stderr.write(`FAIL jiejing_unpublished_draft_oauth_browser: ${error.message}\n`);
  process.exitCode = 1;
});
