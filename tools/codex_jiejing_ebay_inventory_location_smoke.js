#!/usr/bin/env node
/* Local-only browser fixture for confirmation-gated eBay inventory locations.
   It never reaches eBay and fulfills the sole provider write in the local server. */

const crypto = require("crypto");
const fs = require("fs");
const http = require("http");
const path = require("path");
const { chromium } = require("../output/codex-playwright-deps/node_modules/playwright-core");

const root = path.resolve(__dirname, "..");
const companyId = "company-inventory-location-ui";
const userId = "user-inventory-location-ui";
const store = {
  store_id: "store-inventory-location-ui",
  platform: "ebay",
  marketplace: "EBAY_US",
  status: "draft_save_authorized",
  store_name: "Current fixture store",
};
const wrongStoreId = "store-wrong-location-ui";
const listingProjectIdentity = {
  key: "listing-project-inventory-location-ui",
  source_report_id: "report-inventory-location-ui",
  candidate_id: "candidate-inventory-location-ui",
};
const listingProduct = "Foldable Aluminum Tablet Stand";
const listingReport = {
  report_id: listingProjectIdentity.source_report_id,
  company_id: companyId,
  store_id: store.store_id,
  task_id: "task-inventory-location-ui",
  report_type: "listing.package",
  created_at: new Date().toISOString(),
  listing_project_identity: listingProjectIdentity,
  report: {
    product: listingProduct,
    listing_project_identity: listingProjectIdentity,
    listing_handoff: {
      ready_for_listing_draft: true,
      listing_fields: {
        product: listingProduct,
        title: listingProduct,
        sku: "JJ-LOCATION-FIXTURE",
        category_id: "176970",
        condition: "NEW",
        quantity: "1",
        price_band: "24.99",
        description_seed: "Local inventory-location browser fixture listing.",
        item_specifics: { Brand: "Unbranded", Material: "Aluminum" },
        selected_product_candidate: {
          candidate_id: listingProjectIdentity.candidate_id,
          name: listingProduct,
          selected: true,
        },
        ready_for_listing_draft: true,
      },
    },
  },
};
const locationInput = {
  merchant_location_key: "shenzhen-warehouse",
  name: "Shenzhen Warehouse",
  location_types: ["WAREHOUSE"],
  address: { city: "Shenzhen", state_or_province: "Guangdong", country: "CN" },
};
const counters = { intake: 0, decision: 0, execute: 0, reconcile: 0, preflight: 0, genericExecute: 0 };
let confirmations = [];

function canonical(value) {
  if (Array.isArray(value)) return value.map(canonical);
  if (value && typeof value === "object") {
    return Object.keys(value).sort().reduce((out, key) => {
      if (value[key] !== undefined) out[key] = canonical(value[key]);
      return out;
    }, {});
  }
  return value;
}

function sha256(value) {
  return crypto.createHash("sha256").update(JSON.stringify(canonical(value))).digest("hex");
}

function providerPayload(input = locationInput) {
  return {
    merchantLocationKey: input.merchant_location_key,
    name: input.name,
    locationTypes: [...input.location_types],
    location: {
      address: {
        city: input.address.city,
        stateOrProvince: input.address.state_or_province,
        country: input.address.country,
      },
    },
  };
}

function exactCard({
  id = "confirmation-inventory-location-ui",
  status = "pending",
  storeId = store.store_id,
  payload = providerPayload(),
  hash = "",
  actionType = "create_ebay_inventory_location",
  item = {},
} = {}) {
  return {
    confirmation_id: id,
    company_id: companyId,
    store_id: storeId,
    task_id: "task-inventory-location-ui",
    runtime_run_id: "merchant_ebay_inventory_location_setup",
    action_type: actionType,
    title: "Create eBay inventory location",
    status,
    default_action: "hold",
    high_risk: true,
    created_at: new Date().toISOString(),
    item: {
      source: "merchant_ebay_inventory_location_setup",
      requested_step: "inventory_location_confirmation_gate",
      company_id: companyId,
      store_id: storeId,
      merchant_location_key: payload.merchantLocationKey,
      country: payload.location.address.country,
      location_payload: payload,
      location_payload_sha256: hash || sha256(payload),
      high_risk: true,
      writes_to_ebay_after_approval: true,
      public_publish_enabled: false,
      public_listing_created: false,
      secret_exposed: false,
      ...item,
    },
  };
}

function sendJson(res, status, payload) {
  res.writeHead(status, { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" });
  res.end(JSON.stringify(payload));
}

async function readBody(req) {
  const chunks = [];
  for await (const chunk of req) chunks.push(chunk);
  try {
    return chunks.length ? JSON.parse(Buffer.concat(chunks).toString("utf8")) : {};
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
  if (pathname === "/me") return {
    identity: { company_id: companyId, user_id: userId },
    user: { user_id: userId },
    company: { company_id: companyId },
    team_member: { role: "owner" },
  };
  if (pathname === "/permissions/me") return {
    permissions: ["manage_connections", "approve_high_risk", "execute_confirmed_action", "create_task"],
    roles: ["owner"],
    team_member: { role: "owner" },
  };
  if (pathname === "/stores") return { stores: [store] };
  if (pathname === "/connections") return { connections: [{
    connection_id: "connection-inventory-location-ui",
    company_id: companyId,
    store_id: store.store_id,
    platform: "ebay",
    status: "draft_save_authorized",
    scope_profile: "seller_unpublished_draft",
  }] };
  if (pathname === "/confirmations") return { confirmations };
  if (pathname === "/tasks") return { tasks: [{
    task_id: "task-latest-product-ui",
    task_type: "product_workflow",
    title: "Latest unrelated product task",
    status: "completed",
    created_at: new Date().toISOString(),
  }] };
  if (pathname === "/data-packets") return { data_packets: [{
    packet_id: "packet-inventory-location-ui",
    platform: "ebay",
    source_mode: "official_api",
    body: { present_resource_keys: ["account_business_policies", "inventory_items"], missing_resource_keys: [] },
  }] };
  if (pathname === "/reports") return { reports: [listingReport] };
  if (pathname === "/health") return { status: "ok" };
  if (pathname === "/health/deep") return { operational_health: { status: "ready" } };
  if (pathname === "/readiness/product-saas") return { readiness: { beta_ready: true, production_ready: false, public_charging_allowed: false } };
  if (pathname === "/merchant-onboarding/primary-ebay") return { merchant_onboarding: { connection_current: true, store_id: store.store_id } };
  if (pathname === "/ebay-write/adapter/status") return { ebay_write_adapter: { real_platform_writes_enabled: false, effective_ebay_draft_save_enabled: true } };
  return {};
}

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, "http://127.0.0.1");
  const file = staticFile(url.pathname);
  if (req.method === "GET" && file) {
    const ext = path.extname(file);
    const contentType = ext === ".html" ? "text/html; charset=utf-8" : ext === ".js" ? "text/javascript; charset=utf-8" : ext === ".css" ? "text/css; charset=utf-8" : "application/octet-stream";
    res.writeHead(200, { "content-type": contentType, "cache-control": "no-store" });
    fs.createReadStream(file).pipe(res);
    return;
  }
  if (req.method === "POST" && url.pathname === `/stores/${store.store_id}/ebay-inventory-location/confirmation`) {
    counters.intake += 1;
    const body = await readBody(req);
    if (JSON.stringify(body) !== JSON.stringify(locationInput)) {
      sendJson(res, 400, { error: "location_input_mismatch" });
      return;
    }
    confirmations = [exactCard()];
    sendJson(res, 201, { inventory_location_confirmation: {
      confirmation_id: confirmations[0].confirmation_id,
      company_id: companyId,
      store_id: store.store_id,
      status: "pending",
      action_type: "create_ebay_inventory_location",
      source: "merchant_ebay_inventory_location_setup",
      requested_step: "inventory_location_confirmation_gate",
      merchant_location_key: locationInput.merchant_location_key,
      country: "CN",
      location_write_started: false,
      public_listing_created: false,
      secret_exposed: false,
    } });
    return;
  }
  if (req.method === "POST" && /^\/confirmations\/[^/]+\/decision$/.test(url.pathname)) {
    counters.decision += 1;
    const body = await readBody(req);
    const id = decodeURIComponent(url.pathname.split("/")[2] || "");
    const card = confirmations.find((candidate) => candidate.confirmation_id === id);
    if (!card || card.status !== "pending" || body.decision !== "approve") {
      sendJson(res, 409, { error: "exact_pending_required" });
      return;
    }
    confirmations = confirmations.map((candidate) => candidate.confirmation_id === id
      ? { ...candidate, status: "approved", decided_by: userId, decided_at: new Date().toISOString() }
      : candidate);
    sendJson(res, 201, { confirmation: confirmations.find((candidate) => candidate.confirmation_id === id) });
    return;
  }
  if (req.method === "POST" && url.pathname === `/stores/${store.store_id}/ebay-inventory-location/execute`) {
    counters.execute += 1;
    const body = await readBody(req);
    const card = confirmations.find((candidate) => candidate.confirmation_id === body.confirmation_id);
    if (!card || card.status !== "approved") {
      sendJson(res, 409, { error: "exact_approval_required" });
      return;
    }
    confirmations = confirmations.map((candidate) => candidate.confirmation_id === body.confirmation_id
      ? { ...candidate, status: "executed" }
      : candidate);
    sendJson(res, 200, { inventory_location_execution: {
      status: "inventory_location_created",
      action_type: "create_ebay_inventory_location",
      merchant_location_key: locationInput.merchant_location_key,
      location_write_completed: true,
      public_listing_created: false,
      secret_exposed: false,
    } });
    return;
  }
  if (req.method === "POST" && url.pathname === `/stores/${store.store_id}/ebay-inventory-location/reconcile`) {
    counters.reconcile += 1;
    const body = await readBody(req);
    const card = confirmations.find((candidate) => candidate.confirmation_id === body.confirmation_id);
    if (!card || card.status !== "external_execution_processing_manual_reconcile") {
      sendJson(res, 409, { error: "exact_manual_reconcile_required" });
      return;
    }
    confirmations = confirmations.map((candidate) => candidate.confirmation_id === body.confirmation_id
      ? { ...candidate, status: "executed" }
      : candidate);
    sendJson(res, 200, { inventory_location_reconciliation: {
      status: "inventory_location_created",
      action_type: "create_ebay_inventory_location",
      confirmation_id: body.confirmation_id,
      company_id: companyId,
      store_id: store.store_id,
      merchant_location_key: locationInput.merchant_location_key,
      location_write_completed: true,
      reconciled_from_provider_read: true,
      writes_to_ebay: false,
      public_listing_created: false,
      secret_exposed: false,
    } });
    return;
  }
  if (req.method === "POST" && /\/preflight$/.test(url.pathname)) counters.preflight += 1;
  if (req.method === "POST" && /\/execute$/.test(url.pathname)) counters.genericExecute += 1;
  if (req.method === "POST") {
    await readBody(req);
    sendJson(res, 200, {});
    return;
  }
  sendJson(res, 200, getPayload(url.pathname));
});

async function openPage(context, base, consoleErrors, requireListing = true) {
  const page = await context.newPage();
  page.on("console", (message) => {
    if (["error", "warning"].includes(message.type())) consoleErrors.push(message.text());
  });
  page.on("pageerror", (error) => consoleErrors.push(String(error.message || error)));
  await page.goto(`${base}/app.html?start=app`, { waitUntil: "domcontentloaded" });
  try {
    await page.waitForFunction(() => document.querySelector("#appShell") && !document.querySelector("#appShell").classList.contains("is-hidden"), null, { timeout: 10000 });
  } catch (error) {
    const body = String(await page.locator("body").textContent().catch(() => "") || "").replace(/\s+/g, " ").slice(0, 240);
    throw new Error(`app shell did not become visible: ${body}; console=${consoleErrors.slice(0, 3).join(" | ")}; ${error.message}`);
  }
  await page.waitForFunction(() => typeof state === "object" && state.saasConfirmationsLiveLoaded === true, null, { timeout: 10000 });
  if (requireListing) {
    await page.locator('button[data-view="product"]:visible').click();
    const publishDetails = page.locator('details[data-listing-publish-flow-details="publish_intake_collapsed_v1"]');
    await publishDetails.waitFor({ state: "attached", timeout: 10000 });
    await publishDetails.evaluate((element) => { element.open = true; });
    await page.locator("#saasPublishIntakeForm").waitFor({ state: "visible", timeout: 10000 });
  }
  return page;
}

async function openConfirm(page) {
  await page.locator('button[data-view="confirm"]:visible').click();
  await page.evaluate(() => {
    state.saasStartupRequestedView = "cockpit";
    setView(activeSaasRefreshView("cockpit"), { preserveFlowKey: true });
  });
  await page.locator("#saasConfirmPanel").waitFor({ state: "visible", timeout: 5000 });
}

async function assertNoConfirmationLeak(page, id, consoleErrors) {
  const leak = await page.evaluate((needle) => ({
    dom: document.documentElement.innerHTML.includes(needle),
    url: window.location.href.includes(needle),
    storage: Object.keys(localStorage).some((key) => key.includes(needle) || String(localStorage.getItem(key) || "").includes(needle)),
  }), id);
  if (leak.dom || leak.url || leak.storage || consoleErrors.some((line) => line.includes(id))) {
    throw new Error(`inventory-location confirmation leaked to browser surfaces: ${JSON.stringify(leak)}`);
  }
}

async function main() {
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const base = `http://127.0.0.1:${server.address().port}`;
  const browser = await chromium.launch({ channel: process.env.JIEJING_PLAYWRIGHT_CHANNEL || "chrome", headless: true });
  const context = await browser.newContext({ viewport: { width: 1365, height: 900 } });
  const consoleErrors = [];
  await context.addInitScript(({ apiBase, company, user, storeId, product, projectIdentity }) => {
    localStorage.setItem("jiejing_saas_api_base", apiBase);
    localStorage.setItem("jiejing_saas_backend_store_id", storeId);
    localStorage.setItem("jiejing_saas_backend_session_hint", "1");
    localStorage.setItem("jiejing_saas_session_hint", "1");
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
      listing_composer_input: product,
      listing_composer_draft: {
        source_type: "ai_ceo_market_report",
        source_report_id: projectIdentity.source_report_id,
        listing_project_key: projectIdentity.key,
        listing_project_identity: projectIdentity,
        selected_product_candidate: {
          candidate_id: projectIdentity.candidate_id,
          name: product,
          selected: true,
        },
        product,
        title: product,
        fields: {
          title: product,
          description: "Local fixture listing draft",
          category: "Tablet & eBook Reader Stands",
          item_specifics: "Brand: Unbranded\nMaterial: Aluminum",
        },
        publish_prefill: { sku: "JJ-LOCATION-FIXTURE", category_id: "176970", price: "24.99", currency: "USD" },
      },
    }));
    localStorage.setItem("jiejing_saas_known_accounts", JSON.stringify([{
      account_key: user,
      user_id: user,
      email: "inventory-location-ui@example.com",
      company_id: company,
      display_name: "Inventory Location UI",
      last_seen: new Date().toISOString(),
    }]));
    window.__JIEJING_FORCE_PUBLIC_MVP__ = true;
  }, {
    apiBase: base,
    company: companyId,
    user: userId,
    storeId: store.store_id,
    product: listingProduct,
    projectIdentity: listingProjectIdentity,
  });

  try {
    confirmations = [];
    const page = await openPage(context, base, consoleErrors);
    for (const [name, value] of Object.entries({
      inventory_location_key: "shenzhen-warehouse",
      inventory_location_name: "Shenzhen Warehouse",
      inventory_location_city: "Shenzhen",
      inventory_location_state: "Guangdong",
      inventory_location_country: "CN",
    })) await page.locator(`#saasPublishIntakeForm [name="${name}"]`).fill(value);
    await page.locator('[data-saas-action="create-ebay-inventory-location-confirmation"]:visible').click();
    await page.waitForFunction(() => document.body?.textContent?.includes("创建 eBay 库存位置"), null, { timeout: 5000 });
    if (counters.intake !== 1 || counters.execute !== 0 || counters.preflight !== 0 || counters.genericExecute !== 0) {
      throw new Error("first action must create one confirmation and zero provider execution");
    }
    await assertNoConfirmationLeak(page, "confirmation-inventory-location-ui", consoleErrors);
    const approve = page.locator('[data-saas-confirmation-flow="ebay-inventory-location-current-store"]:not([disabled])');
    if (await approve.count() !== 1) throw new Error("one exact current-store inventory-location approval must be visible");
    await approve.click();
    await page.waitForTimeout(250);
    if (counters.decision !== 1 || counters.execute !== 0 || counters.preflight !== 0 || counters.genericExecute !== 0) {
      throw new Error("inventory-location approval must be decision-only");
    }
    await page.locator('button[data-view="product"]:visible').click();
    const approvedPublishDetails = page.locator('details[data-listing-publish-flow-details="publish_intake_collapsed_v1"]');
    await approvedPublishDetails.waitFor({ state: "attached", timeout: 5000 });
    await approvedPublishDetails.evaluate((element) => { element.open = true; });
    const execute = page.locator('[data-saas-action="execute-ebay-inventory-location"]:visible');
    await execute.waitFor({ state: "visible", timeout: 5000 });
    if (await execute.isDisabled()) throw new Error("one exact fresh approval must enable the separate execution action");
    await execute.click();
    await page.waitForFunction(() => document.querySelector('#saasPublishIntakeForm [name="merchant_location_key"]')?.value === "shenzhen-warehouse", null, { timeout: 5000 });
    await page.evaluate(async () => executeSaasApprovedInventoryLocation());
    if (counters.execute !== 1 || counters.preflight !== 0 || counters.genericExecute !== 0) {
      throw new Error("the approved inventory location must execute once and block same-page replay");
    }
    await assertNoConfirmationLeak(page, "confirmation-inventory-location-ui", consoleErrors);
    await page.close();

    confirmations = [{
      ...exactCard({ status: "external_execution_processing_manual_reconcile" }),
      decided_by: userId,
      decided_at: new Date().toISOString(),
    }];
    const reconcilePage = await openPage(context, base, consoleErrors);
    const blockedExecute = reconcilePage.locator('[data-saas-action="execute-ebay-inventory-location"]:visible');
    if (!(await blockedExecute.isDisabled())) {
      throw new Error("manual-reconcile state must disable the provider execution action");
    }
    const reconcile = reconcilePage.locator('[data-saas-action="reconcile-ebay-inventory-location"]:visible');
    await reconcile.waitFor({ state: "visible", timeout: 5000 });
    if (await reconcile.isDisabled()) throw new Error("one exact manual-reconcile location must enable a read-only check");
    const executeBeforeReconcile = counters.execute;
    await reconcile.click();
    await reconcilePage.waitForFunction(() => document.querySelector('#saasPublishIntakeForm [name="merchant_location_key"]')?.value === "shenzhen-warehouse", null, { timeout: 5000 });
    await reconcilePage.evaluate(async () => reconcileSaasInventoryLocation());
    if (counters.reconcile !== 1 || counters.execute !== executeBeforeReconcile) {
      throw new Error("read-only reconciliation must run once without repeating the provider write");
    }
    await assertNoConfirmationLeak(reconcilePage, "confirmation-inventory-location-ui", consoleErrors);
    await reconcilePage.close();

    for (const [name, cards] of [
      ["wrong-store", [exactCard({ storeId: wrongStoreId })]],
      ["tampered-payload", [exactCard({ payload: { ...providerPayload(), name: "Tampered" }, hash: "a".repeat(64) })]],
      ["duplicate-id", [exactCard(), { ...exactCard(), action_type: "change_price", item: { action_type: "change_price" } }]],
    ]) {
      confirmations = cards;
      const attackPage = await openPage(context, base, consoleErrors, false);
      await openConfirm(attackPage);
      const visibleLocation = attackPage.locator("#saasConfirmPanel").getByText("创建 eBay 库存位置", { exact: false });
      if (await visibleLocation.count()) throw new Error(`${name} inventory-location evidence must fail closed from the confirmation center`);
      const before = counters.decision;
      const enabledApprovals = attackPage.locator('#saasConfirmPanel [data-saas-action="approve-confirmation"]:not([disabled])');
      if (await enabledApprovals.count()) throw new Error(`${name} inventory-location evidence must expose no approval action`);
      if (counters.decision !== before) throw new Error(`${name} must not create a decision`);
      await attackPage.close();
    }

    if (consoleErrors.length) throw new Error(`browser console must stay clean: ${consoleErrors[0]}`);
    process.stdout.write("PASS jiejing_ebay_inventory_location_browser\n");
  } finally {
    await context.close();
    await browser.close();
    await new Promise((resolve) => server.close(resolve));
  }
}

main().catch((error) => {
  process.stderr.write(`FAIL jiejing_ebay_inventory_location_browser: ${error.stack || error.message}\n`);
  process.exitCode = 1;
});
