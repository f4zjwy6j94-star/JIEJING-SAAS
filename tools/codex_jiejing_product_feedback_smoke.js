#!/usr/bin/env node
/* Browser smoke for authenticated product-feedback delivery and its scoped outbox.
   All HTTP responses come from this local fixture server. The smoke never calls
   eBay, payment providers, or any external network service. */

const fs = require("fs");
const http = require("http");
const os = require("os");
const path = require("path");
const { chromium } = require("../output/codex-playwright-deps/node_modules/playwright-core");

const root = path.resolve(__dirname, "..");
const browserChannel = process.env.JIEJING_PLAYWRIGHT_CHANNEL || "chrome";
const stamp = new Date().toISOString().replace(/[:.]/g, "-");
const outDir = path.join(os.tmpdir(), "jiejing-product-feedback-smoke", stamp);
fs.mkdirSync(outDir, { recursive: true });

const accountA = {
  companyId: "company-feedback-smoke-a",
  userId: "user-feedback-smoke-a",
  storeId: "store-feedback-smoke-a",
  stores: [{ store_id: "store-feedback-smoke-a", platform: "ebay", store_name: "Feedback Smoke Store A", marketplace: "EBAY_US" }],
};
const accountB = {
  companyId: "company-feedback-smoke-b",
  userId: "user-feedback-smoke-b",
  storeId: "store-feedback-smoke-b1",
  stores: [
    { store_id: "store-feedback-smoke-b1", platform: "ebay", store_name: "Feedback Smoke Store B1", marketplace: "EBAY_US" },
    { store_id: "store-feedback-smoke-b2", platform: "ebay", store_name: "Feedback Smoke Store B2", marketplace: "EBAY_UK" },
  ],
};
const accountC = {
  companyId: "company-feedback-smoke-c",
  userId: "user-feedback-smoke-c",
  storeId: "store-feedback-smoke-c",
  stores: [{ store_id: "store-feedback-smoke-c", platform: "ebay", store_name: "Feedback Smoke Store C", marketplace: "EBAY_US" }],
};
const fixture = {
  mode: "success",
  feedbackRequests: [],
  nextReceipt: 1,
  account: accountA,
  meMode: "success",
  hangingResponses: [],
};

function contentType(filePath) {
  const ext = path.extname(filePath).toLowerCase();
  if (ext === ".html") return "text/html; charset=utf-8";
  if (ext === ".css") return "text/css; charset=utf-8";
  if (ext === ".js") return "text/javascript; charset=utf-8";
  if (ext === ".svg") return "image/svg+xml";
  if (ext === ".png") return "image/png";
  if (ext === ".webp") return "image/webp";
  if (ext === ".jpg" || ext === ".jpeg") return "image/jpeg";
  return "application/octet-stream";
}

function json(res, status, body) {
  res.writeHead(status, {
    "content-type": "application/json; charset=utf-8",
    "cache-control": "no-store",
  });
  res.end(JSON.stringify(body));
}

function apiFixture(method, pathname, requestBody, res) {
  if (method === "POST" && pathname === "/product-feedback") {
    fixture.feedbackRequests.push(requestBody);
    if (fixture.mode === "hang") {
      fixture.hangingResponses.push(res);
      return;
    }
    if (fixture.mode === "network") {
      res.destroy();
      return;
    }
    if (fixture.mode === "delayed_invalid") {
      setTimeout(() => json(res, 400, { error: "fixture_delayed_invalid" }), 250);
      return;
    }
    const delayedErrorStatus = {
      delayed_unauthorized: 401,
      delayed_rate_limited: 429,
      delayed_unavailable: 503,
      delayed_conflict: 409,
    }[fixture.mode];
    if (delayedErrorStatus) {
      setTimeout(() => json(res, delayedErrorStatus, { error: `fixture_${fixture.mode}` }), 250);
      return;
    }
    const errorStatus = { unauthorized: 401, rate_limited: 429, unavailable: 503, invalid: 400, conflict: 409 }[fixture.mode];
    if (errorStatus) {
      json(res, errorStatus, { error: `fixture_${fixture.mode}` });
      return;
    }
    const receiptId = `feedback-browser-smoke-${fixture.nextReceipt++}`;
    const response = {
      product_feedback: {
        contract_version: "2026-08-03-product-feedback-receipt-v1",
        feedback_id: receiptId,
        feedback_type: "product_improvement",
        module_key: requestBody.module_key,
        reason: requestBody.reason,
        status: "open",
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        resolved_at: "",
        duplicate_request: false,
        secret_exposed: false,
      },
      delivered: true,
      external_provider_action_triggered: false,
      real_platform_write_performed: false,
      secret_exposed: false,
    };
    if (fixture.mode === "invalid_receipt_flags") response.real_platform_write_performed = true;
    if (fixture.mode === "invalid_receipt_mismatch") response.product_feedback.module_key = "media";
    if (fixture.mode === "invalid_receipt_unsafe") response.product_feedback.feedback_id = "<unsafe-id>";
    json(res, 201, response);
    return;
  }
  if (method === "GET" && pathname === "/me") {
    if (fixture.meMode === "hang") {
      fixture.hangingResponses.push(res);
      return;
    }
    const current = fixture.account;
    json(res, 200, {
      identity: { company_id: current.companyId, user_id: current.userId },
      user: { user_id: current.userId, email: `${current.userId}@local.invalid` },
      company: { company_id: current.companyId, company_name: "Feedback Smoke" },
    });
    return;
  }
  if (method === "GET" && pathname === "/permissions/me") {
    json(res, 200, { permissions: ["view_reports"], roles: ["owner"], platform_internal_admin: false });
    return;
  }
  if (method === "GET" && pathname === "/stores") {
    json(res, 200, { stores: fixture.account.stores });
    return;
  }
  if (method === "GET" && pathname === "/connections") {
    json(res, 200, {
      connections: fixture.account.stores.map((store, index) => ({
        connection_id: `connection-feedback-smoke-${index}`,
        store_id: store.store_id,
        platform: "ebay",
        status: "read_only_pending",
      })),
    });
    return;
  }
  if (method === "GET" && pathname === "/tasks") return json(res, 200, { tasks: [] });
  if (method === "GET" && pathname === "/reports") return json(res, 200, { reports: [] });
  if (method === "GET" && pathname === "/confirmations") return json(res, 200, { confirmations: [] });
  if (method === "GET" && pathname === "/health") return json(res, 200, { status: "ok" });
  if (method === "GET" && pathname === "/readiness/product-saas") return json(res, 200, { readiness: { beta_ready: true, production_ready: false } });
  if (method === "POST" && pathname === "/auth/logout") return json(res, 200, { logged_out: true });
  json(res, 200, {});
}

function startFixtureServer() {
  return new Promise((resolve, reject) => {
    const server = http.createServer((req, res) => {
      const url = new URL(req.url, "http://127.0.0.1");
      const pathname = decodeURIComponent(url.pathname);
      const relative = pathname.replace(/^\/+/, "") || "index.html";
      const staticCandidate = path.resolve(root, relative);
      const relativeToRoot = path.relative(root, staticCandidate);
      if (!relativeToRoot.startsWith("..") && !path.isAbsolute(relativeToRoot) && fs.existsSync(staticCandidate) && fs.statSync(staticCandidate).isFile()) {
        res.writeHead(200, { "content-type": contentType(staticCandidate), "cache-control": "no-store" });
        fs.createReadStream(staticCandidate).pipe(res);
        return;
      }
      let body = "";
      req.setEncoding("utf8");
      req.on("data", (chunk) => {
        body = `${body}${chunk}`.slice(0, 100000);
      });
      req.on("end", () => {
        let parsed = {};
        try {
          parsed = body ? JSON.parse(body) : {};
        } catch (_error) {
          parsed = {};
        }
        apiFixture(req.method || "GET", pathname, parsed, res);
      });
    });
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => resolve(server));
  });
}

async function waitForWorkbench(page) {
  await page.waitForFunction(
    () => {
      const shell = document.querySelector("#appShell");
      const feedback = document.querySelector("#workflowFeedbackShell");
      return Boolean(shell && !shell.classList.contains("is-hidden") && feedback && !feedback.hidden);
    },
    null,
    { timeout: 30000 },
  );
  await page.waitForTimeout(250);
}

async function submitFeedback(page, detail) {
  if (await page.locator("#workflowFeedbackDrawer").getAttribute("hidden") !== null) await page.click("#workflowFeedbackToggle");
  await page.click('[data-workflow-feedback-reason="unclear"]');
  await page.fill("#workflowFeedbackText", detail);
  await page.click("[data-workflow-feedback-submit]");
}

async function storageJson(page, key) {
  return page.evaluate((storageKey) => {
    try {
      return JSON.parse(localStorage.getItem(storageKey) || "{}");
    } catch (_error) {
      return {};
    }
  }, key);
}

async function waitForFeedbackState(page, state) {
  await page.waitForFunction(
    (expected) => document.querySelector("#workflowFeedbackStatus")?.dataset?.feedbackState === expected,
    state,
    { timeout: 8000 },
  );
}

function allScopedItems(storage) {
  return Object.values(storage).flatMap((items) => (Array.isArray(items) ? items : []));
}

async function currentOutboxItems(page) {
  return allScopedItems(await storageJson(page, "jiejing_saas_product_feedback_outbox_v1"));
}

async function switchStore(page, storeId) {
  await page.evaluate((value) => {
    const select = document.querySelector("#storeSwitch");
    if (!select) throw new Error("store switch is missing");
    select.value = `saas:${value}`;
    select.dispatchEvent(new Event("change", { bubbles: true }));
  }, storeId);
}

async function main() {
  const server = await startFixtureServer();
  const address = server.address();
  const base = `http://127.0.0.1:${address.port}`;
  const browser = await chromium.launch({ channel: browserChannel, headless: true, timeout: 60000 });
  const context = await browser.newContext({ viewport: { width: 1365, height: 900 }, deviceScaleFactor: 1 });
  const page = await context.newPage();
  const pageErrors = [];
  const consoleErrors = [];
  page.on("pageerror", (error) => pageErrors.push(String(error)));
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  await page.addInitScript(
    ({ apiBase, userId, storeId }) => {
      window.__JIEJING_FORCE_PUBLIC_MVP__ = true;
      let selected = { userId, storeId };
      try {
        selected = JSON.parse(localStorage.getItem("jiejing_feedback_smoke_identity") || "null") || selected;
      } catch (_error) {
        selected = { userId, storeId };
      }
      localStorage.setItem("jiejing_saas_api_base", apiBase);
      localStorage.setItem("jiejing_saas_backend_session_hint", "1");
      localStorage.setItem("jiejing_saas_last_account", selected.userId);
      localStorage.setItem("jiejing_saas_backend_store_id", selected.storeId);
      localStorage.setItem(`jiejing_saas_onboarding_done:${selected.userId}`, "1");
    },
    { apiBase: base, userId: accountA.userId, storeId: accountA.storeId },
  );

  try {
    await page.goto(`${base}/app.html?start=app&onboarded=1&view=cockpit&qa=public-saas`, { waitUntil: "domcontentloaded", timeout: 30000 });
    await waitForWorkbench(page);
    fixture.mode = "success";
    fixture.feedbackRequests = [];
    await submitFeedback(page, "The browser smoke needs a real server receipt.");
    await page.waitForFunction(() => document.querySelector("#actionToast")?.textContent?.includes("已送达"), null, { timeout: 5000 });
    if (fixture.feedbackRequests.length !== 1) {
      throw new Error(`online success must POST exactly once, got ${fixture.feedbackRequests.length}`);
    }
    const firstRequest = fixture.feedbackRequests[0] || {};
    if (!firstRequest.idempotency_key || firstRequest.feedback_type !== "product_improvement") {
      throw new Error(`online success request lacks stable key or type: ${JSON.stringify(firstRequest)}`);
    }
    const outbox = await storageJson(page, "jiejing_saas_product_feedback_outbox_v1");
    const receipts = await storageJson(page, "jiejing_saas_product_feedback_receipts_v1");
    if (Object.values(outbox).some((items) => Array.isArray(items) && items.length)) {
      throw new Error(`online success left an outbox item: ${JSON.stringify(outbox)}`);
    }
    if (!Object.values(receipts).some((items) => Array.isArray(items) && items.length === 1)) {
      throw new Error(`online success did not persist one server receipt: ${JSON.stringify(receipts)}`);
    }

    fixture.meMode = "hang";
    fixture.feedbackRequests = [];
    await page.reload({ waitUntil: "domcontentloaded", timeout: 30000 });
    await waitForWorkbench(page);
    await page.click("#workflowFeedbackToggle");
    await page.click('[data-workflow-feedback-reason="unclear"]');
    await page.fill("#workflowFeedbackText", "Cached identity must not establish a feedback scope.");
    if (!(await page.locator("[data-workflow-feedback-submit]").isDisabled())) {
      throw new Error("cached /me snapshot enabled product-feedback submit");
    }
    if (fixture.feedbackRequests.length !== 0) throw new Error("cached /me snapshot allowed product feedback to send");
    if ((await currentOutboxItems(page)).some((item) => item.payload.detail.includes("Cached identity"))) {
      throw new Error("cached /me snapshot allowed product feedback to read or write the scoped outbox");
    }
    for (const response of fixture.hangingResponses.splice(0)) response.destroy();
    fixture.meMode = "success";
    await page.reload({ waitUntil: "domcontentloaded", timeout: 30000 });
    await waitForWorkbench(page);

    fixture.mode = "unavailable";
    fixture.feedbackRequests = [];
    await submitFeedback(page, "Queue this while the feedback service is unavailable.");
    await waitForFeedbackState(page, "queued_local");
    let queued = await currentOutboxItems(page);
    if (queued.length !== 1) throw new Error(`503 must retain exactly one queued item: ${JSON.stringify(queued)}`);
    const queuedKey = queued[0].idempotency_key;
    if (fixture.feedbackRequests[0]?.idempotency_key !== queuedKey) throw new Error("503 request key does not match the queued item");

    await page.reload({ waitUntil: "domcontentloaded", timeout: 30000 });
    await waitForWorkbench(page);
    await page.waitForFunction(() => document.querySelector("#workflowFeedbackStatus")?.textContent?.includes("本机"), null, { timeout: 8000 });
    queued = await currentOutboxItems(page);
    if (queued.length !== 1 || queued[0].idempotency_key !== queuedKey) throw new Error("reload lost or changed the queued idempotency key");
    if (!fixture.feedbackRequests.every((request) => request.idempotency_key === queuedKey)) throw new Error("automatic reload retry changed the idempotency key");

    fixture.mode = "success";
    const windowRequestCount = fixture.feedbackRequests.length;
    await page.evaluate(() => window.dispatchEvent(new Event("online")));
    await page.waitForTimeout(350);
    if (fixture.feedbackRequests.length !== windowRequestCount) throw new Error("online ignored the per-item retry throttle");
    await page.click("#workflowFeedbackToggle");
    await page.click("[data-workflow-feedback-retry]");
    await page.waitForTimeout(250);
    if (fixture.feedbackRequests.length !== windowRequestCount) throw new Error("manual retry ignored the per-item retry throttle");
    await page.evaluate((key) => {
      const storageKey = "jiejing_saas_product_feedback_outbox_v1";
      const raw = JSON.parse(localStorage.getItem(storageKey) || "{}");
      for (const items of Object.values(raw)) {
        if (!Array.isArray(items)) continue;
        for (const item of items) if (item.idempotency_key === key) item.next_retry_at = "2000-01-01T00:00:00.000Z";
      }
      localStorage.setItem(storageKey, JSON.stringify(raw));
    }, queuedKey);
    await page.click("[data-workflow-feedback-retry]");
    await page.waitForFunction(() => {
      const raw = JSON.parse(localStorage.getItem("jiejing_saas_product_feedback_outbox_v1") || "{}");
      return Object.values(raw).every((items) => !Array.isArray(items) || items.length === 0);
    }, null, { timeout: 8000 });
    if (fixture.feedbackRequests.length !== windowRequestCount + 1 || fixture.feedbackRequests.at(-1)?.idempotency_key !== queuedKey) {
      throw new Error("online retry did not reuse the original queued key exactly once");
    }

    fixture.mode = "unauthorized";
    fixture.feedbackRequests = [];
    await submitFeedback(page, "Keep this feedback local until identity is loaded again.");
    await page.waitForURL(
      (url) => url.pathname.endsWith("/index.html") && url.searchParams.get("reason") === "session_expired",
      { timeout: 8000 },
    );
    queued = await currentOutboxItems(page);
    const unauthorizedItem = queued.find((item) => item.payload.detail.includes("identity"));
    const unauthorizedKey = unauthorizedItem?.idempotency_key;
    if (!unauthorizedKey) throw new Error("401 did not retain the feedback in the authenticated scope");
    if (unauthorizedItem.delivery_state !== "wait_for_live_identity" || unauthorizedItem.last_error_class !== "unauthorized") {
      throw new Error(`401 did not persist the live-identity retry boundary: ${JSON.stringify(unauthorizedItem)}`);
    }
    fixture.mode = "success";
    const unauthorizedRequestCount = fixture.feedbackRequests.length;
    await page.evaluate(() => window.dispatchEvent(new Event("online")));
    await page.waitForTimeout(350);
    if (fixture.feedbackRequests.length !== unauthorizedRequestCount) {
      throw new Error("login page online event bypassed the new-live-identity requirement after 401");
    }
    await page.goto(`${base}/app.html?start=app&onboarded=1&view=cockpit&qa=public-saas`, {
      waitUntil: "domcontentloaded",
      timeout: 30000,
    });
    await waitForWorkbench(page);
    await page.waitForFunction((key) => {
      const raw = JSON.parse(localStorage.getItem("jiejing_saas_product_feedback_outbox_v1") || "{}");
      return Object.values(raw).every((items) => !Array.isArray(items) || !items.some((item) => item.idempotency_key === key));
    }, unauthorizedKey, { timeout: 15000 });
    if (fixture.feedbackRequests.at(-1)?.idempotency_key !== unauthorizedKey) throw new Error("identity reload did not retry the 401 item with the same key");
    if (fixture.feedbackRequests.length !== unauthorizedRequestCount + 1) throw new Error("identity reload retried the 401 item more than once");

    for (const [mode, detail] of [
      ["rate_limited", "Rate limited feedback should remain local."],
      ["unavailable", "Unavailable feedback should support manual retry."],
    ]) {
      fixture.mode = mode;
      fixture.feedbackRequests = [];
      await submitFeedback(page, detail);
      await waitForFeedbackState(page, "queued_local");
      queued = await currentOutboxItems(page);
      const item = queued.find((candidate) => candidate.payload.detail === detail);
      if (!item) throw new Error(`${mode} did not retain its queued item`);
      fixture.mode = "success";
      await page.click("[data-workflow-feedback-retry]");
      await page.waitForTimeout(250);
      if (fixture.feedbackRequests.length !== 1) throw new Error(`${mode} manual retry ignored its throttle`);
      await page.evaluate((key) => {
        const storageKey = "jiejing_saas_product_feedback_outbox_v1";
        const raw = JSON.parse(localStorage.getItem(storageKey) || "{}");
        for (const items of Object.values(raw)) {
          if (!Array.isArray(items)) continue;
          for (const candidate of items) if (candidate.idempotency_key === key) candidate.next_retry_at = "2000-01-01T00:00:00.000Z";
        }
        localStorage.setItem(storageKey, JSON.stringify(raw));
      }, item.idempotency_key);
      await page.click("[data-workflow-feedback-retry]");
      await page.waitForFunction(
        (key) => {
          const raw = JSON.parse(localStorage.getItem("jiejing_saas_product_feedback_outbox_v1") || "{}");
          return Object.values(raw).every((items) => !Array.isArray(items) || !items.some((candidate) => candidate.idempotency_key === key));
        },
        item.idempotency_key,
        { timeout: 8000 },
      );
      if (fixture.feedbackRequests.at(-1)?.idempotency_key !== item.idempotency_key) throw new Error(`${mode} manual retry changed the idempotency key`);
    }

    fixture.mode = "delayed_invalid";
    fixture.feedbackRequests = [];
    const invalidDraft = "Keep this editable after the server rejects it.";
    await submitFeedback(page, invalidDraft);
    const activeDraftDuring400 = "This newer draft must survive the old background 400.";
    await page.fill("#workflowFeedbackText", activeDraftDuring400);
    await waitForFeedbackState(page, "needs_edit");
    if ((await page.inputValue("#workflowFeedbackText")) !== activeDraftDuring400) throw new Error("old background 400 overwrote the active draft");
    queued = await currentOutboxItems(page);
    const invalidItem = queued.find((item) => item.payload.detail === invalidDraft);
    if (!invalidItem || invalidItem.delivery_state !== "needs_edit") throw new Error("400 did not quarantine the original item as needs_edit");
    await page.click("[data-workflow-feedback-edit]");
    if ((await page.inputValue("#workflowFeedbackText")) !== activeDraftDuring400) throw new Error("recovery action overwrote a non-empty active draft");
    await page.fill("#workflowFeedbackText", "");
    await page.click("[data-workflow-feedback-edit]");
    if ((await page.inputValue("#workflowFeedbackText")) !== invalidDraft) throw new Error("explicit recovery did not load the quarantined 400 item");
    const unchanged400RequestCount = fixture.feedbackRequests.length;
    fixture.mode = "success";
    await page.click("[data-workflow-feedback-submit]");
    await page.waitForTimeout(300);
    if (fixture.feedbackRequests.length !== unchanged400RequestCount) throw new Error("unchanged 400 recovery was sent again");
    await page.fill("#workflowFeedbackText", `${invalidDraft} Edited.`);
    await page.click("[data-workflow-feedback-submit]");
    await waitForFeedbackState(page, "delivered");
    if ((await currentOutboxItems(page)).some((item) => item.local_id === invalidItem.local_id)) throw new Error("edited 400 recovery did not replace the quarantined record");

    fixture.mode = "conflict";
    fixture.feedbackRequests = [];
    const conflictDraft = "A conflict must fail closed without a blind retry.";
    await submitFeedback(page, conflictDraft);
    await waitForFeedbackState(page, "conflict");
    queued = await currentOutboxItems(page);
    const conflictItem = queued.find((item) => item.payload.detail === conflictDraft);
    if (!conflictItem || conflictItem.delivery_state !== "conflict") throw new Error("409 did not retain a fail-closed conflict record");
    const conflictRequestCount = fixture.feedbackRequests.length;
    fixture.mode = "success";
    await page.evaluate(() => window.dispatchEvent(new Event("online")));
    await page.waitForTimeout(600);
    if (fixture.feedbackRequests.length !== conflictRequestCount) throw new Error("409 conflict was retried blindly on online");
    await page.click("[data-workflow-feedback-edit]");
    if ((await page.inputValue("#workflowFeedbackText")) !== conflictDraft) throw new Error("explicit 409 recovery did not load the conflict item");
    await page.click("[data-workflow-feedback-submit]");
    await page.waitForTimeout(250);
    if (fixture.feedbackRequests.length !== conflictRequestCount) throw new Error("unchanged 409 recovery was resubmitted");
    await page.fill("#workflowFeedbackText", `${conflictDraft} Edited as a new opinion.`);
    await page.click("[data-workflow-feedback-submit]");
    await waitForFeedbackState(page, "delivered");
    if ((await currentOutboxItems(page)).some((item) => item.local_id === conflictItem.local_id)) throw new Error("edited 409 recovery did not replace the conflict record");

    fixture.mode = "conflict";
    fixture.feedbackRequests = [];
    await submitFeedback(page, "Discard this second conflict and free the local cap.");
    await waitForFeedbackState(page, "conflict");
    const discardedConflict = (await currentOutboxItems(page)).find((item) => item.payload.detail.includes("Discard this second conflict"));
    await page.click("[data-workflow-feedback-discard]");
    if (!discardedConflict || (await currentOutboxItems(page)).some((item) => item.local_id === discardedConflict.local_id)) {
      throw new Error("409 discard path did not free the quarantined record");
    }

    fixture.mode = "success";
    fixture.feedbackRequests = [];
    const secretSamples = [
      ["Authorization: Bearer ", "abcdefghijklmnopqrstuvwxyz123456"].join(""),
      "password = this is a private value with spaces",
      ["sk_", "live_1234567890abcdefghijklmnop"].join(""),
      ["AK", "IA1234567890ABCDEF"].join(""),
      ["gh", "p_1234567890abcdefghijklmnopqrstuv"].join(""),
      ["xo", "xb-1234567890-abcdefghijklmnop"].join(""),
      ["ey", "Jabcdefghijk.abcdefghijklmnop.abcdefghijklmnop"].join(""),
      ["-----BEGIN PRIVATE ", "KEY-----"].join(""),
      "eBay refresh token: abcdefghijklmnopqrstuvwxyz",
      ["AI", "za", "A".repeat(35)].join(""),
    ];
    for (const secretSample of secretSamples) {
      const beforeSecretRequests = fixture.feedbackRequests.length;
      await submitFeedback(page, secretSample);
      await waitForFeedbackState(page, "secret_blocked");
      if (fixture.feedbackRequests.length !== beforeSecretRequests) throw new Error("secret guard allowed a product-feedback request");
      const storedValues = await page.evaluate(() => Object.keys(localStorage).map((key) => localStorage.getItem(key) || "").join("\n"));
      if (storedValues.includes(secretSample) || consoleErrors.some((message) => message.includes(secretSample))) {
        throw new Error("secret guard leaked raw sensitive input into storage or console output");
      }
    }
    const benignDetail = "The API key is missing, so explain the setup state more clearly.";
    await submitFeedback(page, benignDetail);
    await waitForFeedbackState(page, "delivered");
    if (fixture.feedbackRequests.at(-1)?.detail !== benignDetail) throw new Error("secret guard rejected benign missing-key product feedback");

    const receiptsBeforeInvalid = allScopedItems(await storageJson(page, "jiejing_saas_product_feedback_receipts_v1")).length;
    for (const invalidReceiptMode of ["invalid_receipt_flags", "invalid_receipt_mismatch", "invalid_receipt_unsafe"]) {
      fixture.mode = invalidReceiptMode;
      fixture.feedbackRequests = [];
      const invalidReceiptDetail = `Reject malformed server receipt: ${invalidReceiptMode}.`;
      await submitFeedback(page, invalidReceiptDetail);
      await waitForFeedbackState(page, "failed");
      const invalidReceiptItem = (await currentOutboxItems(page)).find((item) => item.payload.detail === invalidReceiptDetail);
      if (!invalidReceiptItem || invalidReceiptItem.delivery_state !== "blocked_error" || invalidReceiptItem.last_error_class !== "invalid_receipt") {
        throw new Error(`${invalidReceiptMode} did not remain quarantined after strict receipt validation`);
      }
      const receiptsAfterInvalid = allScopedItems(await storageJson(page, "jiejing_saas_product_feedback_receipts_v1")).length;
      if (receiptsAfterInvalid !== receiptsBeforeInvalid) throw new Error(`${invalidReceiptMode} created a false delivered receipt`);
      await page.click("[data-workflow-feedback-discard]");
    }

    fixture.mode = "success";
    fixture.feedbackRequests = [];
    const corruptRaw = "{broken-product-feedback-storage";
    await page.evaluate(({ corrupt, unrelated }) => {
      localStorage.setItem("jiejing_saas_product_feedback_outbox_v1", corrupt);
      localStorage.setItem("jiejing_feedback_unrelated_sentinel", unrelated);
    }, { corrupt: corruptRaw, unrelated: "keep-unrelated-bytes" });
    const corruptDraft = "Keep this draft while corrupt storage fails closed.";
    await submitFeedback(page, corruptDraft);
    await waitForFeedbackState(page, "storage_failed");
    if (fixture.feedbackRequests.length !== 0) throw new Error("corrupt product-feedback storage still triggered a request");
    if ((await page.inputValue("#workflowFeedbackText")) !== corruptDraft) throw new Error("corrupt storage erased the active draft");
    const corruptEvidence = await page.evaluate(() => ({
      outbox: localStorage.getItem("jiejing_saas_product_feedback_outbox_v1"),
      unrelated: localStorage.getItem("jiejing_feedback_unrelated_sentinel"),
    }));
    if (corruptEvidence.outbox !== corruptRaw || corruptEvidence.unrelated !== "keep-unrelated-bytes") {
      throw new Error(`corrupt storage was overwritten: ${JSON.stringify(corruptEvidence)}`);
    }
    await page.evaluate(() => localStorage.setItem("jiejing_saas_product_feedback_outbox_v1", "{}"));
    const liveScope = await page.evaluate(() => {
      const receipts = JSON.parse(localStorage.getItem("jiejing_saas_product_feedback_receipts_v1") || "{}");
      return Object.keys(receipts)[0] || "";
    });
    if (!liveScope) throw new Error("product feedback smoke could not identify the live receipt scope");
    for (const [storageKey, label] of [
      ["jiejing_saas_product_feedback_outbox_v1", "outbox"],
      ["jiejing_saas_product_feedback_receipts_v1", "receipts"],
    ]) {
      const scopedCorruptRaw = JSON.stringify({ [liveScope]: { damaged: true, label } });
      await page.evaluate(({ key, raw }) => localStorage.setItem(key, raw), { key: storageKey, raw: scopedCorruptRaw });
      fixture.feedbackRequests = [];
      const scopedDraft = `Keep ${label} draft when the current scope is not an array.`;
      await submitFeedback(page, scopedDraft);
      await waitForFeedbackState(page, "storage_failed");
      if (fixture.feedbackRequests.length !== 0) throw new Error(`${label} scoped corruption still triggered a request`);
      if ((await page.inputValue("#workflowFeedbackText")) !== scopedDraft) throw new Error(`${label} scoped corruption erased the active draft`);
      const preserved = await page.evaluate((key) => localStorage.getItem(key), storageKey);
      if (preserved !== scopedCorruptRaw) throw new Error(`${label} scoped corruption was overwritten`);
      await page.evaluate((key) => localStorage.setItem(key, "{}"), storageKey);
      await page.click("[data-workflow-feedback-close]");
    }
    await page.reload({ waitUntil: "domcontentloaded", timeout: 30000 });
    await waitForWorkbench(page);

    for (const mode of ["delayed_unauthorized", "delayed_rate_limited", "delayed_unavailable", "delayed_conflict"]) {
      fixture.mode = mode;
      fixture.feedbackRequests = [];
      const uncertainDetail = `Do not retry after ${mode} storage persistence fails.`;
      await submitFeedback(page, uncertainDetail);
      await waitForFeedbackState(page, "submitting");
      await page.evaluate(() => {
        if (!window.__jiejingOriginalStorageSetItem) window.__jiejingOriginalStorageSetItem = Storage.prototype.setItem;
        window.__jiejingFailNextFeedbackOutboxWrite = true;
        Storage.prototype.setItem = function patchedSetItem(key, value) {
          if (key === "jiejing_saas_product_feedback_outbox_v1" && window.__jiejingFailNextFeedbackOutboxWrite) {
            window.__jiejingFailNextFeedbackOutboxWrite = false;
            throw new DOMException("synthetic product feedback storage failure", "QuotaExceededError");
          }
          return window.__jiejingOriginalStorageSetItem.call(this, key, value);
        };
      });
      await waitForFeedbackState(page, "storage_failed");
      const firstRequestCount = fixture.feedbackRequests.length;
      if (firstRequestCount !== 1) throw new Error(`${mode} did not reach the single response-under-test request`);
      await page.evaluate(() => {
        Storage.prototype.setItem = window.__jiejingOriginalStorageSetItem;
        window.dispatchEvent(new Event("online"));
      });
      const retry = page.locator("[data-workflow-feedback-retry]");
      if (await retry.isVisible()) await retry.click();
      await page.waitForTimeout(350);
      if (fixture.feedbackRequests.length !== firstRequestCount) throw new Error(`${mode} blindly retried after response-state persistence failed`);
      await page.evaluate(() => localStorage.setItem("jiejing_saas_product_feedback_outbox_v1", "{}"));
      await page.click("[data-workflow-feedback-close]");
    }
    fixture.mode = "success";

    fixture.account = accountB;
    await page.evaluate(({ userId, storeId }) => {
      localStorage.setItem("jiejing_feedback_smoke_identity", JSON.stringify({ userId, storeId }));
      localStorage.setItem("jiejing_saas_last_account", userId);
      localStorage.setItem("jiejing_saas_backend_store_id", storeId);
      localStorage.setItem(`jiejing_saas_onboarding_done:${userId}`, "1");
      localStorage.removeItem("jiejing_saas_protected_snapshot");
      Object.keys(localStorage).filter((key) => key.startsWith("jiejing_saas_protected_snapshot:")).forEach((key) => localStorage.removeItem(key));
    }, { userId: accountB.userId, storeId: accountB.storeId });
    fixture.feedbackRequests = [];
    await page.reload({ waitUntil: "domcontentloaded", timeout: 30000 });
    await waitForWorkbench(page);
    await page.waitForTimeout(700);
    if (fixture.feedbackRequests.length !== 0) throw new Error("account switch replayed another account's conflict outbox");

    fixture.mode = "hang";
    const storeB1Detail = "Store B1 hanging request must not absorb Store B2.";
    await submitFeedback(page, storeB1Detail);
    await waitForFeedbackState(page, "submitting");
    await page.waitForTimeout(150);
    queued = await currentOutboxItems(page);
    const storeB1Item = queued.find((item) => item.payload.detail === storeB1Detail);
    if (!storeB1Item || fixture.feedbackRequests.filter((request) => request.detail === storeB1Detail).length !== 1) {
      throw new Error("store B1 did not anchor and start exactly one hanging request");
    }
    fixture.mode = "success";
    await switchStore(page, accountB.stores[1].store_id);
    await page.waitForFunction((storeId) => localStorage.getItem("jiejing_saas_backend_store_id") === storeId, accountB.stores[1].store_id, { timeout: 8000 });
    await page.waitForTimeout(1200);
    const storeB2Detail = "Store B2 must send while Store B1 is still hanging.";
    await submitFeedback(page, storeB2Detail);
    await waitForFeedbackState(page, "delivered");
    if (fixture.feedbackRequests.filter((request) => request.detail === storeB1Detail).length !== 1 || fixture.feedbackRequests.filter((request) => request.detail === storeB2Detail).length !== 1) {
      throw new Error("per-scope flush map regression: " + JSON.stringify(fixture.feedbackRequests));
    }
    for (const response of fixture.hangingResponses.splice(0)) response.destroy();
    await page.waitForTimeout(350);
    if (await page.locator("#workflowFeedbackStatus").getAttribute("data-feedback-state") !== "delivered") {
      throw new Error("old Store B1 failure overwrote the active Store B2 UI");
    }
    await switchStore(page, accountB.stores[0].store_id);
    await page.waitForFunction((storeId) => localStorage.getItem("jiejing_saas_backend_store_id") === storeId, accountB.stores[0].store_id, { timeout: 8000 });
    await page.waitForTimeout(1200);
    await page.evaluate((key) => {
      const storageKey = "jiejing_saas_product_feedback_outbox_v1";
      const raw = JSON.parse(localStorage.getItem(storageKey) || "{}");
      for (const items of Object.values(raw)) {
        if (!Array.isArray(items)) continue;
        for (const item of items) if (item.idempotency_key === key) item.next_retry_at = "2000-01-01T00:00:00.000Z";
      }
      localStorage.setItem(storageKey, JSON.stringify(raw));
    }, storeB1Item.idempotency_key);
    const b1StillQueued = (await currentOutboxItems(page)).some((item) => item.idempotency_key === storeB1Item.idempotency_key);
    if (b1StillQueued) {
      if (await page.locator("#workflowFeedbackDrawer").getAttribute("hidden") !== null) await page.click("#workflowFeedbackToggle");
      await page.click("[data-workflow-feedback-retry]");
    }
    await page.waitForFunction(
      (key) => {
        const raw = JSON.parse(localStorage.getItem("jiejing_saas_product_feedback_outbox_v1") || "{}");
        return Object.values(raw).every((items) => !Array.isArray(items) || !items.some((item) => item.idempotency_key === key));
      },
      storeB1Item.idempotency_key,
      { timeout: 15000 },
    );
    if (fixture.feedbackRequests.at(-1)?.idempotency_key !== storeB1Item.idempotency_key) throw new Error("Store B1 recovery did not reuse its scoped key");

    fixture.account = accountC;
    const legacyScope = `${accountC.userId}::${accountC.storeId}`;
    const legacyRecords = [
      {
        id: "legacy-useful-must-stay",
        feedback_type: "useful",
        report_id: "legacy-report-useful",
        rule_text: "Keep this merchant memory untouched.",
        created_at: "2026-08-01T00:00:00.000Z",
      },
      ...Array.from({ length: 25 }, (_, index) => ({
        id: "legacy-product-improvement-" + (index + 1),
        feedback_type: "product_improvement",
        report_id: "legacy-report-" + (index + 1),
        report_type: index % 2 ? "media" : "workflow",
        report_title: "Legacy stage " + (index + 1),
        rule_text: "Migrate product improvement " + (index + 1) + " exactly once.",
        workflow_context: {
          module_key: index % 2 ? "media" : "workflow",
          reason: index % 3 ? "missing_action" : "unclear",
          stage_title: "Legacy stage " + (index + 1),
        },
        created_at: new Date(Date.parse("2026-08-01T00:01:00.000Z") + index * 1000).toISOString(),
      })),
    ];
    await page.evaluate(({ userId, storeId, oldScope, records }) => {
      localStorage.setItem("jiejing_feedback_smoke_identity", JSON.stringify({ userId, storeId }));
      localStorage.setItem("jiejing_saas_last_account", userId);
      localStorage.setItem("jiejing_saas_backend_store_id", storeId);
      localStorage.setItem(`jiejing_saas_onboarding_done:${userId}`, "1");
      const legacy = JSON.parse(localStorage.getItem("jiejing_saas_merchant_feedback") || "{}");
      legacy[oldScope] = records;
      localStorage.setItem("jiejing_saas_merchant_feedback", JSON.stringify(legacy));
      localStorage.removeItem("jiejing_saas_protected_snapshot");
      Object.keys(localStorage).filter((key) => key.startsWith("jiejing_saas_protected_snapshot:")).forEach((key) => localStorage.removeItem(key));
    }, { userId: accountC.userId, storeId: accountC.storeId, oldScope: legacyScope, records: legacyRecords });
    fixture.mode = "success";
    fixture.feedbackRequests = [];
    await page.reload({ waitUntil: "domcontentloaded", timeout: 30000 });
    await waitForWorkbench(page);
    await page.waitForFunction(() => {
      const markers = JSON.parse(localStorage.getItem("jiejing_saas_product_feedback_migration_v1") || "{}");
      return Object.values(markers).some((marker) =>
        marker?.legacy_scope === "user-feedback-smoke-c::store-feedback-smoke-c" &&
        marker?.completed === true &&
        marker?.processed_fingerprints?.length === 25
      );
    }, null, { timeout: 15000 });
    const migrationStorage = await storageJson(page, "jiejing_saas_product_feedback_migration_v1");
    const migratedEntry = Object.entries(migrationStorage).find(([, marker]) => marker?.legacy_scope === legacyScope);
    const migratedScope = migratedEntry?.[0];
    const migratedMarker = migratedEntry?.[1];
    if (!migratedScope) throw new Error("legacy migration marker was not scoped to the authenticated account/store");
    if (migratedMarker?.next_index !== legacyRecords.length) throw new Error("resumable migration did not advance its bounded cursor past every legacy record");
    await page.waitForFunction(
      (scope) => {
        const outbox = JSON.parse(localStorage.getItem("jiejing_saas_product_feedback_outbox_v1") || "{}");
        return !Array.isArray(outbox[scope]) || outbox[scope].length === 0;
      },
      migratedScope,
      { timeout: 15000 },
    );
    const migratedOutbox = await storageJson(page, "jiejing_saas_product_feedback_outbox_v1");
    if ((migratedOutbox[migratedScope] || []).length !== 0) throw new Error("resumable migration did not drain all 25 records");
    const preservedLegacy = (await storageJson(page, "jiejing_saas_merchant_feedback"))[legacyScope];
    if (JSON.stringify(preservedLegacy) !== JSON.stringify(legacyRecords)) throw new Error("legacy migration mutated useful memory or source records");
    const deliveredMigrationKeys = fixture.feedbackRequests.map((request) => request.idempotency_key);
    if (fixture.feedbackRequests.length !== 25 || new Set(deliveredMigrationKeys).size !== 25) {
      throw new Error("resumable migration did not deliver 25 unique stable keys exactly once");
    }
    fixture.feedbackRequests = [];
    await page.reload({ waitUntil: "domcontentloaded", timeout: 30000 });
    await waitForWorkbench(page);
    await page.waitForTimeout(700);
    if (fixture.feedbackRequests.length !== 0) throw new Error("completed legacy migration replayed on the next authenticated load");

    await page.screenshot({ path: path.join(outDir, "desktop-product-feedback.png"), fullPage: true });
    await page.setViewportSize({ width: 390, height: 844 });
    await page.evaluate(() => setView("connect"));
    await page.waitForSelector("#view-connect.is-active #workflowFeedbackToggle, #view-connect.is-active", { timeout: 10000 });
    await page.click("#workflowFeedbackToggle");
    const mobileActionBox = await page.locator("[data-workflow-feedback-submit]").boundingBox();
    if (!mobileActionBox || mobileActionBox.y < 0 || mobileActionBox.y + mobileActionBox.height > 844) {
      throw new Error(`mobile feedback submit action is clipped: ${JSON.stringify(mobileActionBox)}`);
    }
    await page.screenshot({ path: path.join(outDir, "mobile-product-feedback.png"), fullPage: true });
    const unexpectedConsoleErrors = consoleErrors.filter(
      (message) => !/Failed to load resource: (the server responded with a status of (400|401|409|429|503)|net::ERR_EMPTY_RESPONSE)/i.test(message),
    );
    if (pageErrors.length || unexpectedConsoleErrors.length) {
      throw new Error(`browser errors: ${JSON.stringify({ pageErrors, unexpectedConsoleErrors })}`);
    }
    console.log(`PASS codex_jiejing_product_feedback_smoke ${outDir}`);
  } finally {
    await browser.close();
    await new Promise((resolve) => server.close(resolve));
  }
}

main().catch((error) => {
  console.error(`FAIL codex_jiejing_product_feedback_smoke: ${error.stack || error}`);
  process.exit(1);
});
