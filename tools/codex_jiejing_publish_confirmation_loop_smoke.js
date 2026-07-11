#!/usr/bin/env node
/* ASCII-only no-write smoke for Listing draft -> confirmation center -> publish receipt. */

const fs = require("fs");
const path = require("path");
const { chromium } = require("../output/codex-playwright-deps/node_modules/playwright-core");

const base = process.env.JIEJING_TEST_BASE || "https://app.jiejing.shop";
const browserChannel = process.env.JIEJING_PLAYWRIGHT_CHANNEL || "chrome";
const localStaticRoot = process.env.JIEJING_LOCAL_STATIC_ROOT ? path.resolve(process.env.JIEJING_LOCAL_STATIC_ROOT) : "";
const viewportWidth = Number(process.env.JIEJING_SMOKE_VIEWPORT_WIDTH || 1440);
const viewportHeight = Number(process.env.JIEJING_SMOKE_VIEWPORT_HEIGHT || 920);
const stamp = new Date().toISOString().replace(/[:.]/g, "-");
const outDir = path.join("output", "browser-smoke", `${stamp}-publish-confirmation-loop`);
const smokeMarker = "codex_jiejing_publish_confirmation_loop_smoke";
fs.mkdirSync(outDir, { recursive: true });

function fail(message, details = {}) {
  const error = new Error(message);
  error.details = details;
  throw error;
}

async function api(pathname, { token = "", method = "GET", body } = {}) {
  const res = await fetch(`${base}${pathname}`, {
    method,
    cache: "no-store",
    headers: {
      "content-type": "application/json",
      ...(token ? { authorization: `Bearer ${token}` } : {}),
    },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
  const text = await res.text();
  let json = null;
  try {
    json = text ? JSON.parse(text) : null;
  } catch (_error) {
    json = { raw: text.slice(0, 500) };
  }
  return { ok: res.ok, status: res.status, json };
}

async function makeSession() {
  const suffix = `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  const email = `codex-publish-loop-${suffix}@local.invalid`;
  const password = `Codex-publish-loop-${suffix}`;
  const registered = await api("/auth/register", {
    method: "POST",
    body: {
      email,
      password,
      company_name: "Codex Publish Loop Smoke",
    },
  });
  if (!registered.ok) {
    fail(`register failed: ${registered.status}`, { body: registered.json });
  }
  const token = registered.json.token;
  const user = registered.json.user || {};
  const company = registered.json.company || {};
  const activatedBilling = await api("/billing/test-event", {
    token,
    method: "POST",
    body: {
      plan_key: "operator",
      action: "activate",
    },
  });
  if (!activatedBilling.ok) {
    fail(`billing test activation failed: ${activatedBilling.status}`, { body: activatedBilling.json });
  }
  const created = await api("/stores", {
    token,
    method: "POST",
    body: {
      platform: "ebay",
      store_name: "Codex Publish Loop Store",
      marketplace: "EBAY_US",
      stage: "store_opened",
      settings: {
        created_from: "codex_publish_confirmation_loop_smoke",
        placeholder_store_name: true,
      },
    },
  });
  if (!created.ok) {
    fail(`store create failed: ${created.status}`, { body: created.json });
  }
  const store = created.json.store || {};
  const packet = await api(`/stores/${encodeURIComponent(store.store_id)}/ebay-read-only/data-packet`, {
    token,
    method: "POST",
    body: {
      resources: ["store_profile", "finances", "account_business_policies", "inventory_and_offers"],
      source_mode: "official_api",
      sample_payload: {
        store_profile: {
          seller_account_status: "active",
          account_status: "active",
          selling_status: "active",
          status: "active",
          restrictions: [],
          selling_limits: { remaining_quantity: 50, remaining_amount: "1000" },
        },
        finances: {
          payout_status: "available",
          payment_status: "available",
        },
        account_business_policies: {
          fulfillment_policy_id: "codex-fulfillment-policy",
          payment_policy_id: "codex-payment-policy",
          return_policy_id: "codex-return-policy",
        },
        inventory_and_offers: {
          merchant_location_key: "codex-main-location",
          item_location: "US",
        },
      },
    },
  });
  if (!packet.ok || !packet.json?.data_packet?.packet_id) {
    fail(`data packet create failed: ${packet.status}`, { body: packet.json });
  }
  return {
    token,
    email,
    userId: user.user_id || "",
    companyId: company.company_id || user.default_company_id || "",
    store,
    packet: packet.json.data_packet,
  };
}

function localStaticPath(requestUrl) {
  if (!localStaticRoot) return "";
  const url = new URL(requestUrl);
  const pathname = decodeURIComponent(url.pathname.replace(/^\/+/, "")) || "index.html";
  const allowed =
    ["app.html", "index.html", "app.js", "styles.css", "privacy.html", "terms.html", "refund-policy.html", "support.html", "risk-disclosure.html"].includes(pathname) ||
    pathname.startsWith("assets/");
  if (!allowed) return "";
  const candidate = path.resolve(localStaticRoot, pathname);
  const relative = path.relative(localStaticRoot, candidate);
  if (relative.startsWith("..") || path.isAbsolute(relative)) return "";
  return candidate;
}

function contentTypeFor(filePath) {
  const ext = path.extname(filePath).toLowerCase();
  if (ext === ".html") return "text/html; charset=utf-8";
  if (ext === ".css") return "text/css; charset=utf-8";
  if (ext === ".js") return "text/javascript; charset=utf-8";
  if (ext === ".webp") return "image/webp";
  if (ext === ".png") return "image/png";
  if (ext === ".jpg" || ext === ".jpeg") return "image/jpeg";
  if (ext === ".svg") return "image/svg+xml";
  return "application/octet-stream";
}

async function setupContext(browser, session, appHtml) {
  const context = await browser.newContext({ viewport: { width: viewportWidth, height: viewportHeight }, deviceScaleFactor: 1 });
  const baseUrl = new URL(base);
  await context.addCookies([
    {
      name: "jiejing_saas_session",
      value: session.token,
      domain: baseUrl.hostname,
      path: "/",
      httpOnly: true,
      secure: baseUrl.protocol === "https:",
      sameSite: "Lax",
    },
  ]);
  await context.route(`${base}/app.html**`, (route) =>
    route.fulfill({
      status: 200,
      contentType: "text/html; charset=utf-8",
      headers: { "cache-control": "no-store" },
      body: appHtml,
    }),
  );
  if (localStaticRoot) {
    await context.route(`${base}/**`, (route) => {
      const filePath = localStaticPath(route.request().url());
      if (!filePath || !fs.existsSync(filePath)) {
        route.continue();
        return;
      }
      return route.fulfill({
        status: 200,
        contentType: contentTypeFor(filePath),
        headers: { "cache-control": "no-store" },
        body: fs.readFileSync(filePath),
      });
    });
  }
  await context.addInitScript(
    ({ base, session }) => {
      const accountKey = String(session.userId || session.email || "codex").toLowerCase();
      localStorage.setItem("jiejing_saas_api_base", base);
      localStorage.setItem("jiejing_saas_backend_store_id", session.store.store_id);
      localStorage.setItem("jiejing_saas_backend_session_hint", "1");
      localStorage.setItem("jiejing_saas_session_hint", "1");
      localStorage.setItem("jiejing_saas_last_account", accountKey);
      localStorage.setItem(`jiejing_saas_onboarding_done:${accountKey}`, "1");
      localStorage.setItem(
        "jiejing_saas_known_accounts",
        JSON.stringify([
          {
            account_key: accountKey,
            user_id: session.userId,
            email: session.email,
            company_id: session.companyId,
            display_name: "Codex Publish Loop Smoke",
            last_seen: new Date().toISOString(),
          },
        ]),
      );
      window.__JIEJING_FORCE_PUBLIC_MVP__ = true;
    },
    { base, session },
  );
  return context;
}

async function setListingDraft(page, seed) {
  await page.evaluate((seed) => {
    const draft = {
      product: seed.product,
      title: seed.title,
      source: "codex_no_write_publish_loop_smoke",
      bullets: ["Acceptance product identity preserved", "Fresh smoke SKU only", "No real platform write"],
      gaps: [],
      risks: ["真实发布仍需确认中心"],
      fields: {
        title: seed.title,
        selling_points: `Controlled acceptance draft for ${seed.product}; merchant facts still require review.`,
        description: seed.description,
        category: seed.categoryLeaf,
        images: seed.imageUrl,
        price: seed.price,
        item_specifics: "Brand: Unbranded\nType: Acceptance Test Fixture\nMaterial: Requires merchant verification",
        logistics: "test fixture only; merchant must verify location, weight and dimensions",
      },
    };
    state.saasListingComposerInput = `${seed.product}\n${seed.description}`;
    state.saasListingComposerDraft = draft;
    state.saasListingSourceMode = "merchant_input";
    setView("product", { preserveFlowKey: true });
  }, seed);
}

async function fillPublishIntakeForm(page, seed) {
  const fill = async (name, value) => {
    const locator = page.locator(`#saasPublishIntakeForm [name="${name}"]`);
    await locator.waitFor({ state: "attached", timeout: 30000 });
    await locator.fill(String(value));
  };
  await fill("product", seed.product);
  await fill("sku", seed.sku);
  await fill("title", seed.title);
  await fill("price", seed.price);
  await fill("currency", "USD");
  await fill("procurement_cost", "2.10");
  await fill("shipping_cost", "1.25");
  await fill("ebay_fee", "1.10");
  await fill("net_profit", "5.54");
  await fill("gross_margin_percent", "55.4");
  await fill("image_urls", seed.imageUrl);
  await fill("description_html", seed.description);
  await fill("category_id", seed.categoryId);
  await fill("category_leaf", seed.categoryLeaf);
  await fill("merchant_location_key", "codex-main-location");
  await fill("item_specifics", "Brand: Unbranded\nType: Acceptance Test Fixture\nMaterial: Requires merchant verification");
  await fill("quantity", "1");
  await fill("item_location", "US");
  await fill("package_weight_g", "60");
  await fill("package_length_cm", "10");
  await fill("package_width_cm", "6");
  await fill("package_height_cm", "2");
  await fill("material", "Requires merchant verification");
}

async function main() {
  const session = await makeSession();
  const acceptanceProduct = process.env.JIEJING_ACCEPTANCE_PRODUCT || `Acceptance fixture label set ${Date.now()}`;
  const seed = {
    product: acceptanceProduct,
    sku: `JJ-PUBLISH-LOOP-${Date.now()}`,
    title: acceptanceProduct.slice(0, 80),
    description: `<p>Controlled acceptance draft for ${acceptanceProduct.replace(/[<>&]/g, "")}. Product facts require merchant verification before any real listing.</p>`,
    categoryId: "299",
    categoryLeaf: "Synthetic no-write category fixture; requires taxonomy review",
    price: "9.99",
    imageUrl: "https://example.com/jiejing-no-write-label-tabs.jpg",
  };
  const appHtmlResponse = localStaticRoot
    ? { ok: true, text: async () => fs.readFileSync(path.join(localStaticRoot, "app.html"), "utf8"), status: 200 }
    : await fetch(`${base}/app.html?start=app&view=product&publish-loop-smoke=${Date.now()}`, { cache: "no-store" });
  if (!appHtmlResponse.ok) {
    fail(`app html fetch failed: ${appHtmlResponse.status}`);
  }
  const appHtml = await appHtmlResponse.text();
  const browser = await chromium.launch({ channel: browserChannel, headless: true, timeout: 60000 });
  const context = await setupContext(browser, session, appHtml);
  const page = await context.newPage();
  page.setDefaultTimeout(45000);

  const pageErrors = [];
  const requestFailures = [];
  const badResponses = [];
  const forbiddenRequests = [];
  const screenshotFailures = [];
  page.on("pageerror", (error) => pageErrors.push(String(error.message || error).slice(0, 500)));
  page.on("request", (request) => {
    const url = request.url();
    if (/signin\.ebay|auth\.ebay|ebay\.com\/signin|\/oauth\/authorize|\/oauth\/callback|stripe\.com|paypal\.com|checkout\.stripe\.com|\/billing\/checkout-session|\/billing\/provider-rehearsal/i.test(url)) {
      forbiddenRequests.push(url);
    }
  });
  page.on("requestfailed", (request) => {
    if (request.url().startsWith(base)) {
      requestFailures.push({ url: request.url(), error: request.failure()?.errorText || "", resourceType: request.resourceType() });
    }
  });
  page.on("response", (response) => {
    if (response.url().startsWith(base) && response.status() >= 500) {
      badResponses.push({ url: response.url(), status: response.status() });
    }
  });

  await page.goto(`${base}/app.html?start=app&view=product&publish-loop-smoke=${Date.now()}`, {
    waitUntil: "commit",
    timeout: 90000,
  });
  await page.waitForSelector("body", { timeout: 30000 });
  await page.waitForLoadState("networkidle", { timeout: 45000 }).catch(() => {});
  await page.waitForFunction(
    () => document.documentElement.classList.contains("app-ready") && !document.querySelector(".auth-shell, .saas-login-modal, [data-auth-view]"),
    null,
    { timeout: 60000 },
  );
  await setListingDraft(page, seed);
  await page.waitForFunction(
    () =>
      Array.from(document.querySelectorAll('#view-product.is-active [data-saas-action="focus-publish-intake"]')).some(
        (button) => button && button.offsetParent !== null && !button.disabled,
      ),
    null,
    { timeout: 60000 },
  );
  await page.evaluate(() => {
    const button = Array.from(document.querySelectorAll('#view-product.is-active [data-saas-action="focus-publish-intake"]')).find(
      (candidate) => candidate && candidate.offsetParent !== null && !candidate.disabled,
    );
    button?.click();
  });
  await page.waitForFunction(
    () => {
      const details = document.querySelector('[data-listing-publish-flow-details="publish_intake_collapsed_v1"]');
      const form = document.querySelector("#view-product.is-active #saasPublishIntakeForm");
      return Boolean(details?.open && form && form.offsetParent !== null);
    },
    null,
    { timeout: 60000 },
  );
  await fillPublishIntakeForm(page, seed);
  await page.waitForSelector(".saas-listing-publish-loop", { timeout: 30000 });
  await page
    .screenshot({ path: path.join(outDir, "01-product-draft-before-confirmation.png"), fullPage: true, timeout: 15000 })
    .catch((error) => screenshotFailures.push({ view: "product-before-confirmation", error: String(error.message || error).slice(0, 300) }));

  const createButton = page.locator(".saas-publish-intake-panel .saas-publish-intake-actions [data-saas-action=\"create-publish-confirmation\"]").first();
  await page.waitForFunction(
    () => {
      const button = document.querySelector(".saas-publish-intake-panel .saas-publish-intake-actions [data-saas-action=\"create-publish-confirmation\"]");
      return Boolean(button && !button.disabled);
    },
    null,
    { timeout: 60000 },
  );
  await createButton.click();
  await page.waitForFunction(
    (sku) => {
      const confirmations = typeof state !== "undefined" && Array.isArray(state.saasConfirmations) ? state.saasConfirmations : [];
      return confirmations.some((item) => item?.action_type === "publish_listing" && JSON.stringify(item).includes(sku));
    },
    seed.sku,
    { timeout: 90000 },
  );
  const confirmation = await page.evaluate((sku) => {
    const confirmations = typeof state !== "undefined" && Array.isArray(state.saasConfirmations) ? state.saasConfirmations : [];
    return confirmations.find((item) => item?.action_type === "publish_listing" && JSON.stringify(item).includes(sku)) || null;
  }, seed.sku);
  if (!confirmation?.confirmation_id) {
    fail("publish confirmation was not created from the Listing intake form", { confirmation });
  }
  await page
    .screenshot({ path: path.join(outDir, "02-product-after-confirmation.png"), fullPage: true, timeout: 15000 })
    .catch((error) => screenshotFailures.push({ view: "product-after-confirmation", error: String(error.message || error).slice(0, 300) }));

  await page.waitForFunction(
    () =>
      Array.from(document.querySelectorAll('#view-product.is-active [data-saas-action="open-confirm"]')).some(
        (button) => button && button.offsetParent !== null && !button.disabled,
      ),
    null,
    { timeout: 60000 },
  );
  await page.evaluate(() => {
    const button = Array.from(document.querySelectorAll('#view-product.is-active [data-saas-action="open-confirm"]')).find(
      (candidate) => candidate && candidate.offsetParent !== null && !candidate.disabled,
    );
    button?.click();
  });
  await page.waitForSelector("#view-confirm.is-active .saas-confirm-card", { timeout: 60000 });
  const approveButton = page.locator(`[data-saas-action="approve-confirmation"][data-saas-confirmation="${confirmation.confirmation_id}"]`).first();
  await approveButton.waitFor({ state: "visible", timeout: 30000 });
  const confirmCenterBeforeApproval = await page.evaluate((confirmationId) => {
    const button = document.querySelector(`[data-saas-action="approve-confirmation"][data-saas-confirmation="${confirmationId}"]`);
    const card = button?.closest(".saas-confirm-card");
    const text = card?.innerText || "";
    return {
      visible: Boolean(card && card.offsetParent !== null && button && button.offsetParent !== null),
      has_merchant_decision_copy: text.includes("你要判断") && text.includes("你没点头前不会执行"),
      has_safety_detail: text.includes("为什么停住"),
      has_publish_action_label: text.includes("发布") || text.includes("上架"),
      has_no_unspecified_sku_copy: !text.includes("没有指定 SKU"),
      text_preview: text.trim().slice(0, 240),
    };
  }, confirmation.confirmation_id);
  await page
    .screenshot({ path: path.join(outDir, "03-confirm-center-before-approve.png"), fullPage: true, timeout: 15000 })
    .catch((error) => screenshotFailures.push({ view: "confirm-before-approve", error: String(error.message || error).slice(0, 300) }));
  await approveButton.click();
  await page.waitForFunction(
    (confirmationId) => {
      const confirmations = typeof state !== "undefined" && Array.isArray(state.saasConfirmations) ? state.saasConfirmations : [];
      const executions = typeof state !== "undefined" && Array.isArray(state.saasExecutionResults) ? state.saasExecutionResults : [];
      const item = confirmations.find((record) => record?.confirmation_id === confirmationId);
      const execution = executions.find((record) => record?.confirmation_id === confirmationId || record?.result?.audit?.confirmation_id === confirmationId);
      return Boolean(item?.status === "approved" && execution);
    },
    confirmation.confirmation_id,
    { timeout: 90000 },
  );
  await page
    .screenshot({ path: path.join(outDir, "04-confirm-center-approved.png"), fullPage: true, timeout: 15000 })
    .catch((error) => screenshotFailures.push({ view: "confirm-approved", error: String(error.message || error).slice(0, 300) }));
  await page.evaluate(() => setView("product", { preserveFlowKey: true }));
  await page.waitForSelector("#view-product.is-active .saas-listing-publish-loop", { timeout: 60000 });
  await page
    .screenshot({ path: path.join(outDir, "05-product-publish-receipt.png"), fullPage: true, timeout: 15000 })
    .catch((error) => screenshotFailures.push({ view: "product-publish-receipt", error: String(error.message || error).slice(0, 300) }));

  const ui = await page.evaluate((confirmationId) => {
    const product = document.querySelector("#view-product.is-active");
    const confirm = document.querySelector("#view-confirm");
    const loop = product?.querySelector(".saas-listing-publish-loop");
    const feedback = product?.querySelector(".saas-listing-publish-feedback");
    const confirmations = typeof state !== "undefined" && Array.isArray(state.saasConfirmations) ? state.saasConfirmations : [];
    const executions = typeof state !== "undefined" && Array.isArray(state.saasExecutionResults) ? state.saasExecutionResults : [];
    const confirmation = confirmations.find((item) => item?.confirmation_id === confirmationId) || null;
    const execution = executions.find((record) => record?.confirmation_id === confirmationId || record?.result?.audit?.confirmation_id === confirmationId) || null;
    const text = [product?.innerText || "", confirm?.innerText || ""].join("\n");
    return {
      loop_visible: Boolean(loop && loop.offsetParent !== null),
      feedback_visible: Boolean(feedback && feedback.offsetParent !== null),
      has_loop_copy: text.includes("草稿到确认中心再回到发布回执") && text.includes("没有通过系统体检不会写入 eBay"),
      has_receipt_copy: text.includes("发布回执") && (text.includes("已记录交接") || text.includes("结果会回写到 Listing")),
      has_confirm_center_copy: text.includes("你没点头前不会执行") && text.includes("点同意后"),
      confirmation_status: confirmation?.status || "",
      execution_status: execution?.status || execution?.result?.status || "",
      execution_mode: execution?.result?.audit?.execution_mode || execution?.result?.audit?.execution_intent?.mode || "",
      published_to_ebay: execution?.status === "published_to_ebay" || execution?.result?.status === "published_to_ebay",
      real_execution: execution?.result?.audit?.real_execution || {},
      secret_exposed: JSON.stringify({ confirmation, execution }).toLowerCase().includes("refresh_token"),
      confirmation_id: confirmationId,
    };
  }, confirmation.confirmation_id);

  const [confirmationsApi, executionsApi, healthApi, readinessApi] = await Promise.all([
    api("/confirmations?limit=40", { token: session.token }),
    api("/execution-results?limit=20", { token: session.token }),
    api("/health"),
    api("/readiness/product-saas"),
  ]);
  const apiConfirmation = (confirmationsApi.json?.confirmations || []).find((item) => item.confirmation_id === confirmation.confirmation_id) || null;
  const apiExecution = (executionsApi.json?.execution_results || []).find((item) => item.confirmation_id === confirmation.confirmation_id) || null;
  const checks = {
    listing_draft_visible: ui.loop_visible && ui.has_loop_copy,
    publish_confirmation_created: Boolean(apiConfirmation?.confirmation_id),
    confirmation_center_card_visible_before_approve:
      confirmCenterBeforeApproval.visible &&
      confirmCenterBeforeApproval.has_merchant_decision_copy &&
      confirmCenterBeforeApproval.has_safety_detail &&
      confirmCenterBeforeApproval.has_publish_action_label &&
      confirmCenterBeforeApproval.has_no_unspecified_sku_copy,
    confirmation_center_approved: apiConfirmation?.status === "approved" && ui.confirmation_status === "approved",
    execution_service_handoff_recorded: apiExecution?.status === "simulated_no_platform_write" && ui.execution_status === "simulated_no_platform_write",
    publish_receipt_returned_to_listing: ui.feedback_visible && ui.has_receipt_copy,
    no_real_platform_writes_triggered:
      healthApi.json?.real_platform_writes_enabled === false &&
      apiExecution?.status !== "published_to_ebay" &&
      ui.published_to_ebay !== true &&
      apiExecution?.result?.audit?.real_execution?.published_to_ebay !== true,
    no_real_charge_triggered: !forbiddenRequests.some((url) => /stripe|paypal|checkout-session|provider-rehearsal/i.test(url)),
    no_ebay_oauth_triggered: !forbiddenRequests.some((url) => /signin\.ebay|auth\.ebay|oauth\/authorize|oauth\/callback/i.test(url)),
    no_secret_exposed: ui.secret_exposed === false,
    public_gate_still_not_production_ready:
      readinessApi.json?.readiness?.production_ready === false && readinessApi.json?.readiness?.can_accept_real_customers === false,
  };
  const result = {
    ok: Object.values(checks).every(Boolean) && !pageErrors.length && !requestFailures.length && !badResponses.length && !forbiddenRequests.length,
    marker: smokeMarker,
    timestamp: new Date().toISOString(),
    base,
    outDir,
    session: {
      email_masked: session.email.replace(/^(.{2}).*(@.*)$/, "$1***$2"),
      store_id: session.store.store_id,
      packet_id: session.packet.packet_id,
    },
    seed: {
      product: seed.product,
      sku: seed.sku,
      title: seed.title,
      category_id: seed.categoryId,
    },
    confirmation_id: confirmation.confirmation_id,
    checks,
    confirmCenterBeforeApproval,
    ui,
    api: {
      confirmation_status: apiConfirmation?.status || "",
      execution_status: apiExecution?.status || "",
      real_platform_writes_enabled: healthApi.json?.real_platform_writes_enabled,
      production_ready: readinessApi.json?.readiness?.production_ready,
      can_accept_real_customers: readinessApi.json?.readiness?.can_accept_real_customers,
    },
    pageErrors,
    requestFailures,
    badResponses,
    forbiddenRequests,
    screenshotFailures,
  };
  fs.writeFileSync(path.join(outDir, "result.json"), JSON.stringify(result, null, 2));
  await browser.close();

  const failures = [];
  for (const [key, value] of Object.entries(checks)) {
    if (!value) failures.push(key);
  }
  if (pageErrors.length) failures.push(`page errors: ${pageErrors.length}`);
  if (requestFailures.length) failures.push(`request failures: ${requestFailures.length}`);
  if (badResponses.length) failures.push(`5xx responses: ${badResponses.length}`);
  if (forbiddenRequests.length) failures.push(`forbidden requests: ${forbiddenRequests.length}`);
  if (screenshotFailures.length) failures.push(`screenshot failures: ${screenshotFailures.length}`);
  if (failures.length) {
    console.error(JSON.stringify(result, null, 2));
    fail(`publish confirmation loop smoke failed: ${failures.join(", ")}`, { outDir });
  }
  console.log(JSON.stringify(result, null, 2));
}

main().catch((error) => {
  console.error(
    JSON.stringify(
      {
        ok: false,
        message: error.message,
        details: error.details || {},
        outDir,
      },
      null,
      2,
    ),
  );
  process.exit(1);
});
