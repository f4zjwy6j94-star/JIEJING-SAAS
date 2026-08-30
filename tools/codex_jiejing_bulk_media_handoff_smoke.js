#!/usr/bin/env node
/* Isolated-account smoke for Bulk -> Listing -> Media -> Listing handoff.
   It requires a dedicated local fixture backend and creates account/task/media
   state, so production is always forbidden. An environment 404 is setup failure,
   not an A-scheme product RED. */

const fs = require("fs");
const path = require("path");
const { chromium } = require("../output/codex-playwright-deps/node_modules/playwright-core");
const { assertSafeMutationBase } = require("./jiejing_browser_smoke_mutation_guard");

const base = process.env.JIEJING_TEST_BASE || "http://127.0.0.1:8788";
const browserChannel = process.env.JIEJING_PLAYWRIGHT_CHANNEL || "chrome";
const localStaticRoot = process.env.JIEJING_LOCAL_STATIC_ROOT ? path.resolve(process.env.JIEJING_LOCAL_STATIC_ROOT) : "";
const viewportWidth = Number(process.env.JIEJING_SMOKE_VIEWPORT_WIDTH || 1440);
const viewportHeight = Number(process.env.JIEJING_SMOKE_VIEWPORT_HEIGHT || 920);
const stamp = new Date().toISOString().replace(/[:.]/g, "-");
const outDir = path.join("output", "browser-smoke", `${stamp}-bulk-media-handoff`);
const smokeMarker = "codex_jiejing_bulk_media_handoff_smoke";
const includeVideo = /^(1|true|yes|on)$/i.test(String(process.env.JIEJING_ACCEPTANCE_INCLUDE_VIDEO || ""));
const acceptanceProduct = process.env.JIEJING_ACCEPTANCE_PRODUCT || `Acceptance fixture lightweight organizer ${Date.now()}`;
let smokeStage = "starting";
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
      "user-agent": "Mozilla/5.0 Codex Jiejing Bulk Media Smoke",
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
  const email = `codex-bulk-media-${suffix}@local.invalid`;
  const password = `Codex-bulk-media-${suffix}`;
  const registered = await api("/auth/register", {
    method: "POST",
    body: {
      email,
      password,
      company_name: "Codex Bulk Media Smoke",
    },
  });
  if (!registered.ok) {
    fail(`register failed: ${registered.status}`, { body: registered.json });
  }
  const token = registered.json.token;
  const user = registered.json.user || {};
  const company = registered.json.company || {};
  const trialActivation = registered.json.platform_trial_activation;
  const platformTrialActivation = {
    present: Boolean(trialActivation && typeof trialActivation === "object"),
    status: String(trialActivation?.status || ""),
    platform_trial_allowed: trialActivation?.platform_trial_allowed === true,
    secret_exposed: trialActivation?.secret_exposed === true,
  };
  if (platformTrialActivation.secret_exposed) {
    fail("registration trial metadata exposed a secret");
  }
  const created = await api("/stores", {
    token,
    method: "POST",
    body: {
      platform: "ebay",
      store_name: "Codex Bulk Media Store",
      marketplace: "EBAY_US",
      stage: "store_opened",
      settings: {
        created_from: "codex_bulk_media_handoff_smoke",
        placeholder_store_name: true,
      },
    },
  });
  if (!created.ok) {
    fail(`store create failed: ${created.status}`, { body: created.json });
  }
  return {
    token,
    email,
    userId: user.user_id || "",
    companyId: company.company_id || user.default_company_id || "",
    platformTrialActivation,
    store: created.json.store || {},
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

function buildFrontendMediaFixtureJob(jobSpec = {}, assetUrl = "", storeId = "") {
  const mediaJobId = `media-fixture-${Date.now()}`;
  const now = new Date().toISOString();
  return {
    media_job_id: mediaJobId,
    store_id: storeId,
    idempotency_key: String(jobSpec.idempotency_key || mediaJobId),
    status: "waiting_review",
    job: { job_spec: jobSpec },
    live_provider_called: true,
    spend_now_allowed: false,
    secret_exposed: false,
    fixture_only: true,
    external_provider_called: false,
    asset_manifest_validation: { status: "manifest_ready" },
    asset_manifest: [
      {
        asset_id: `${mediaJobId}-image-1`,
        asset_type: "product_image",
        url: assetUrl,
        url_or_file_path: assetUrl,
        dimensions: "720x720",
        commercial_use_status: "needs_review",
        fact_review_status: "needs_review",
        listing_use_status: "not_ready_for_listing_until_review",
      },
    ],
    created_at: now,
    updated_at: now,
  };
}

async function setupContext(browser, session, appHtml, mediaFixtureState, controlledSourcePath) {
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
      const request = route.request();
      const requestUrl = new URL(request.url());
      const method = request.method();
      const fulfillJson = (status, payload) =>
        route.fulfill({
          status,
          contentType: "application/json; charset=utf-8",
          headers: { "cache-control": "no-store" },
          body: JSON.stringify(payload),
        });
      if (requestUrl.pathname === "/__jiejing-smoke__/controlled-media.png") {
        if (!fs.existsSync(controlledSourcePath)) return route.fulfill({ status: 404, body: "fixture not ready" });
        return route.fulfill({ status: 200, contentType: "image/png", body: fs.readFileSync(controlledSourcePath) });
      }
      if (method === "POST" && /\/stores\/[^/]+\/provider-jobs\/queue$/.test(requestUrl.pathname)) {
        const jobSpec = request.postDataJSON() || {};
        mediaFixtureState.job = buildFrontendMediaFixtureJob(
          jobSpec,
          `${base}/__jiejing-smoke__/controlled-media.png`,
          session.store.store_id,
        );
        mediaFixtureState.requests.push({ method, path: requestUrl.pathname, fixture: "queue" });
        return fulfillJson(200, { media_asset_job: mediaFixtureState.job, fixture_only: true });
      }
      if (method === "POST" && /\/media-asset-jobs\/[^/]+\/review$/.test(requestUrl.pathname)) {
        if (!mediaFixtureState.job) return fulfillJson(404, { error: "fixture media job missing" });
        const reviewedAt = new Date().toISOString();
        mediaFixtureState.job = {
          ...mediaFixtureState.job,
          status: "approved_for_listing",
          merchant_review: {
            contract_version: "2026-07-11-media-review-v2",
            decision: "approve_for_listing_draft",
            confirmations: {
              fact_consistency_confirmed: true,
              commercial_rights_confirmed: true,
              platform_rules_checked: true,
              motion_and_usage_consistency_confirmed: true,
            },
            reviewed_by: "fixture-merchant",
            listing_draft_only: true,
            triggers_real_platform_write: false,
            secret_exposed: false,
          },
          asset_review: {
            status: "approved_for_listing_draft",
            listing_use_status: "approved_for_listing_draft",
            reviewed_at: reviewedAt,
            fixture_only: true,
          },
          asset_manifest: mediaFixtureState.job.asset_manifest.map((asset) => ({
            ...asset,
            commercial_use_status: "confirmed_by_merchant",
            fact_review_status: "confirmed_by_merchant",
            listing_use_status: "approved_for_listing_draft",
            review_status: "approved_for_listing_draft",
          })),
          updated_at: reviewedAt,
        };
        mediaFixtureState.requests.push({ method, path: requestUrl.pathname, fixture: "review" });
        return fulfillJson(200, { media_asset_job: mediaFixtureState.job, fixture_only: true });
      }
      if (method === "GET" && /\/media-asset-jobs\/[^/]+$/.test(requestUrl.pathname)) {
        mediaFixtureState.requests.push({ method, path: requestUrl.pathname, fixture: "job" });
        return mediaFixtureState.job
          ? fulfillJson(200, { media_asset_job: mediaFixtureState.job, fixture_only: true })
          : fulfillJson(404, { error: "fixture media job missing" });
      }
      if (method === "GET" && /\/stores\/[^/]+\/media-asset-jobs$/.test(requestUrl.pathname)) {
        mediaFixtureState.requests.push({ method, path: requestUrl.pathname, fixture: "list" });
        return fulfillJson(200, { media_asset_jobs: mediaFixtureState.job ? [mediaFixtureState.job] : [], fixture_only: true });
      }
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
            display_name: "Codex Bulk Media Smoke",
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

async function waitForReady(page, selector, timeoutMs = 60000) {
  await page.waitForFunction(
    (selector) => {
      const root = document.querySelector(selector);
      return Boolean(
        root &&
          root.offsetParent !== null &&
          document.documentElement.classList.contains("app-ready") &&
          !document.querySelector(".auth-shell, .saas-login-modal, [data-auth-view]"),
      );
    },
    selector,
    { timeout: timeoutMs },
  );
  await page.waitForTimeout(350);
}

async function main() {
  assertSafeMutationBase(base);
  smokeStage = "creating_safe_test_account";
  const session = await makeSession();
  smokeStage = "loading_workbench";
  const appHtmlResponse = localStaticRoot
    ? { ok: true, text: async () => fs.readFileSync(path.join(localStaticRoot, "app.html"), "utf8"), status: 200 }
    : await fetch(`${base}/app.html?start=app&view=bulk&bulk-media-smoke=${Date.now()}`, { cache: "no-store" });
  if (!appHtmlResponse.ok) {
    fail(`app html fetch failed: ${appHtmlResponse.status}`);
  }
  const appHtml = await appHtmlResponse.text();
  const sourceFixturePath = path.join(outDir, "controlled-merchant-source.png");
  const mediaFixtureState = { job: null, requests: [] };
  const mediaFixtureApi = () => ({
    ok: true,
    status: 200,
    json: { media_asset_jobs: mediaFixtureState.job ? [mediaFixtureState.job] : [], fixture_only: true },
  });
  const browser = await chromium.launch({ channel: browserChannel, headless: true, timeout: 60000 });
  const context = await setupContext(browser, session, appHtml, mediaFixtureState, sourceFixturePath);
  const page = await context.newPage();
  page.setDefaultTimeout(45000);

  const pageErrors = [];
  const requestFailures = [];
  const badResponses = [];
  const forbiddenRequests = [];
  const workflowMutationRequests = [];
  const screenshotFailures = [];
  page.on("pageerror", (error) => pageErrors.push(String(error.message || error).slice(0, 500)));
  page.on("request", (request) => {
    const url = request.url();
    if (request.method() !== "GET" && /\/tasks(?:[/?]|$)|\/reports(?:[/?]|$)|\/merchant-ceo(?:[/?]|$)/i.test(url)) {
      workflowMutationRequests.push({ method: request.method(), url });
    }
    if (
      /signin\.ebay|auth\.ebay|ebay\.com\/signin|\/oauth\/authorize|\/oauth\/callback|stripe\.com|paypal\.com|checkout\.stripe\.com|\/billing\/test-event|\/billing\/checkout-session|\/billing\/provider-rehearsal|\/ebay\/publish|\/ads\/|\/refund|\/procurement|\/inventory\/write/i.test(
        url,
      )
    ) {
      forbiddenRequests.push(url);
    }
  });
  page.on("requestfailed", (request) => {
    const requestUrl = request.url();
    if (requestUrl.startsWith(base)) {
      const failure = request.failure()?.errorText || "";
      const resourceType = request.resourceType();
      // Images can be aborted during intentional view transitions. Treat only app/API/script failures as smoke blockers.
      if (resourceType === "image" && /ERR_ABORTED/i.test(failure)) return;
      // Cloudflare RUM is optional edge telemetry and is commonly cancelled when the test closes the page.
      if (resourceType === "ping" && requestUrl.includes("/cdn-cgi/rum") && /ERR_ABORTED/i.test(failure)) return;
      requestFailures.push({ url: requestUrl, error: failure, resourceType });
    }
  });
  page.on("response", (response) => {
    if (response.url().startsWith(base) && response.status() >= 500) {
      badResponses.push({ url: response.url(), status: response.status() });
    }
  });

  await page.goto(`${base}/app.html?start=app&view=bulk&bulk-media-smoke=${Date.now()}`, {
    waitUntil: "commit",
    timeout: 90000,
  });
  await page.waitForSelector("body", { timeout: 30000 });
  await page.waitForLoadState("networkidle", { timeout: 45000 }).catch(() => {});
  smokeStage = "waiting_for_initial_workbench";
  await page.waitForFunction(
    () =>
      document.documentElement.classList.contains("app-ready") &&
      !document.querySelector(".auth-shell, .saas-login-modal, [data-auth-view]") &&
      typeof setView === "function",
    null,
    { timeout: 90000 },
  );
  await page.evaluate(() => setView("bulk"));
  await waitForReady(page, "#view-bulk.is-active");
  smokeStage = "bulk_ready";
  await page
    .screenshot({ path: path.join(outDir, "01-bulk-initial.png"), fullPage: true, timeout: 15000 })
    .catch((error) => screenshotFailures.push({ view: "bulk-initial", error: String(error.message || error).slice(0, 300) }));

  const bulkInitial = await page.evaluate(() => {
    const root = document.querySelector("#view-bulk.is-active");
    const text = root?.innerText || "";
    const listingModes = Array.from(root?.querySelectorAll("[data-listing-mode]") || []);
    const riskyActionLabels = Array.from(root?.querySelectorAll("button:not([disabled]), a[href]") || [])
      .map((item) => (item.textContent || "").replace(/\s+/g, " ").trim())
      .filter((label) => /(直接发布|一键发布|上传到 eBay|发布到 eBay)/.test(label) && !/(不|不会|确认单|体检)/.test(label));
    return {
      visible: Boolean(root && root.offsetParent !== null),
      has_generate_button: Boolean(root?.querySelector('[data-bulk-action="generate-candidates"]')),
      listing_mode_order: listingModes.map((item) => item.dataset.listingMode),
      bulk_mode_active: listingModes.filter((item) => item.getAttribute("aria-current") === "page").map((item) => item.dataset.listingMode),
      product_primary_nav_active: document.querySelector('.nav-item[data-view="product"]')?.classList.contains("is-active") === true,
      bulk_primary_nav_count: document.querySelectorAll('.nav-item[data-view="bulk"]').length,
      has_direct_publish_button: riskyActionLabels.length > 0,
      has_safety_copy: text.includes("不会自动执行"),
      preview: text.trim().slice(0, 240),
    };
  });

  await page.fill(
    "#bulkManualSourceInput",
    [
      `${acceptanceProduct} | https://supplier.invalid/product-grade-acceptance | 11.8 CNY | 240 | Yiwu | 190g / 32x8x6cm`,
      `Acceptance fixture backup ${Date.now()} | https://supplier.invalid/product-grade-backup | 8.6 CNY | 500 | Ningbo | 120g / 18x9x7cm`,
      `${acceptanceProduct} | https://supplier.invalid/product-grade-acceptance | 11.8 CNY | 240 | Yiwu | 190g / 32x8x6cm`,
    ].join("\n"),
  );
  await page.click('[data-bulk-action="import-manual-source"]');
  await page.waitForFunction(
    () =>
      state.saasBulkImportPreview?.candidates?.length === 2 &&
      state.saasBulkImportPreview?.duplicates === 1 &&
      document.querySelectorAll(".bulk-import-preview-row").length === 3,
    null,
    { timeout: 30000 },
  );
  await page.click('[data-bulk-action="import-manual-source"]');
  smokeStage = "importing_bulk_candidates";
  await page.waitForFunction(
    () => Array.isArray(state.saasBulkCandidates) && state.saasBulkCandidates.length === 2,
    null,
    { timeout: 30000 },
  );

  await page.evaluate(() => {
    document.querySelector('#view-bulk.is-active [data-bulk-action="generate-candidates"]')?.click();
  });
  smokeStage = "generating_bulk_candidates";
  await page.waitForFunction(
    () => {
      const root = document.querySelector("#view-bulk.is-active");
      return Boolean(root?.querySelector('[data-bulk-action="accept-candidates"]') && Number(state.batchPreviewCount || 0) > 0);
    },
    null,
    { timeout: 60000 },
  );
  await page
    .screenshot({ path: path.join(outDir, "02-bulk-generated-candidates.png"), fullPage: true, timeout: 15000 })
    .catch((error) => screenshotFailures.push({ view: "bulk-generated-candidates", error: String(error.message || error).slice(0, 300) }));

  const bulkGenerated = await page.evaluate(() => {
    const root = document.querySelector("#view-bulk.is-active");
    const text = root?.innerText || "";
    return {
      preview_count: Number(state.batchPreviewCount || 0),
      approved_count: Number(state.bulkApprovedCount || 0),
      has_accept_button: Boolean(root?.querySelector('[data-bulk-action="accept-candidates"]')),
      has_grouping_copy: text.includes("建议先测") && text.includes("需要补资料") && text.includes("暂时不做"),
      has_safety_copy: text.includes("只生成草稿") && text.includes("不会自动"),
      preview: text.trim().slice(0, 240),
    };
  });

  await page.evaluate(() => {
    document.querySelector('#view-bulk.is-active [data-bulk-action="accept-candidates"]')?.click();
  });
  smokeStage = "opening_listing_from_bulk";
  await waitForReady(page, "#view-product.is-active");
  await page.waitForFunction(
    (expectedProduct) => {
      return Boolean(
        state.saasListingComposerDraft?.source_type === "bulk_handoff" &&
          state.saasListingComposerDraft?.product === expectedProduct &&
          String(state.activeMediaDraft || "").startsWith("saas-bulk-"),
      );
    },
    acceptanceProduct,
    { timeout: 60000 },
  );
  await page
    .screenshot({ path: path.join(outDir, "03-product-after-bulk-accept.png"), fullPage: true, timeout: 15000 })
    .catch((error) => screenshotFailures.push({ view: "product-after-bulk-accept", error: String(error.message || error).slice(0, 300) }));

  const productAfterBulk = await page.evaluate(() => {
    const root = document.querySelector("#view-product.is-active");
    const active = state.saasListingComposerDraft || {};
    const text = root?.innerText || "";
    const listingModes = Array.from(root?.querySelectorAll("[data-listing-mode]") || []);
    const riskyActionLabels = Array.from(root?.querySelectorAll("button:not([disabled]), a[href]") || [])
      .map((item) => (item.textContent || "").replace(/\s+/g, " ").trim())
      .filter((label) => /(直接发布|一键发布|上传到 eBay|发布到 eBay)/.test(label) && !/(不|不会|确认单|体检)/.test(label));
    return {
      listing_mode_order: listingModes.map((item) => item.dataset.listingMode),
      single_mode_active: listingModes.filter((item) => item.getAttribute("aria-current") === "page").map((item) => item.dataset.listingMode),
      active_listing_draft: state.activeListingDraft || "",
      active_media_draft: state.activeMediaDraft || "",
      active_title_cn: active?.product || active?.title || "",
      active_title_en: active?.fields?.title || "",
      source_type: active?.source_type || "",
      cost_price: active?.fields?.cost_price || "",
      logistics: active?.fields?.logistics || "",
      handoff_status: state.sourceHandoffStatus || "",
      bulk_approved_count: Number(state.bulkApprovedCount || 0),
      has_bulk_feedback: text.includes("批量铺货") && text.includes("素材工坊"),
      has_media_button: Boolean(root?.querySelector('[data-saas-action="open-media"], [data-product-action="media"]')),
      title_is_not_generic_ai_ceo_report: active?.product !== "AI CEO 市场调研",
      has_no_direct_publish_button: riskyActionLabels.length === 0,
      preview: text.trim().slice(0, 240),
    };
  });
  const bulkProductFixture = await page.evaluate(() => ({
    composer: JSON.parse(JSON.stringify(state.saasListingComposerDraft || {})),
    active_listing_draft: state.activeListingDraft || "",
    active_media_draft: state.activeMediaDraft || "",
    listing_source_mode: state.saasListingSourceMode || "",
    source_handoff_status: state.sourceHandoffStatus || "",
  }));

  const recentFixture = await page.evaluate(() => {
    const stamp = Date.now();
    const reportId = `report-recent-existing-${stamp}`;
    const productTaskId = `task-recent-product-${stamp}`;
    const noReportTaskId = `task-recent-no-report-${stamp}`;
    const unrelatedTaskId = `task-recent-service-${stamp}`;
    const storeId = activeSaasStore()?.store_id || "";
    const companyId = state.saasCompany?.company_id || state.saasIdentity?.company_id || "";
    const projectIdentity = { key: `listing-project-recent-${stamp}`, source_report_id: reportId, candidate_id: `candidate-${stamp}` };
    const report = {
      report_id: reportId,
      task_id: productTaskId,
      report_type: "listing.package",
      store_id: storeId,
      company_id: companyId,
      status: "completed",
      created_at: new Date(stamp - 1000).toISOString(),
      listing_project_identity: projectIdentity,
      report: {
        title: "Existing saved travel organizer",
        summary: "Existing report fixture for resume-only browser validation.",
        listing_project_identity: projectIdentity,
      },
    };
    const productTask = {
      task_id: productTaskId,
      task_type: "product_workflow",
      store_id: storeId,
      company_id: companyId,
      listing_project_identity: projectIdentity,
      title: "Existing saved travel organizer",
      status: "blocked_facts",
      source_report_id: reportId,
      report_id: reportId,
      updated_at: new Date(stamp).toISOString(),
    };
    const noReportTask = {
      task_id: noReportTaskId,
      task_type: "product_workflow",
      store_id: storeId,
      company_id: companyId,
      title: "Existing task waiting for product facts",
      status: "completed_with_blocks",
      missing_fields: ["package_dimensions"],
      updated_at: new Date(stamp + 2).toISOString(),
    };
    const unrelatedTask = {
      task_id: unrelatedTaskId,
      task_type: "customer_service",
      store_id: storeId,
      company_id: companyId,
      title: "Must not appear in recent products",
      status: "open",
      updated_at: new Date(stamp + 1).toISOString(),
    };
    state.saasTasks = [unrelatedTask, noReportTask, productTask, ...(Array.isArray(state.saasTasks) ? state.saasTasks : [])];
    state.saasReports = [report, ...(Array.isArray(state.saasReports) ? state.saasReports : [])];
    renderProductListingCenter();
    return {
      report_id: reportId,
      product_task_id: productTaskId,
      no_report_task_id: noReportTaskId,
      unrelated_task_id: unrelatedTaskId,
      task_count: state.saasTasks.length,
      report_count: state.saasReports.length,
    };
  });
  const recentMutationRequestStart = workflowMutationRequests.length;
  await page.click('#view-product.is-active [data-listing-mode="recent"]');
  await page.waitForSelector(
    `#view-product.is-active [data-recent-product-task-id="${recentFixture.product_task_id}"]`,
    { timeout: 20000 },
  );
  const recentList = await page.evaluate(() => ({
    task_ids: Array.from(document.querySelectorAll("#view-product.is-active [data-recent-product-task-id]")).map(
      (item) => item.dataset.recentProductTaskId,
    ),
    task_types: Array.from(document.querySelectorAll("#view-product.is-active [data-recent-product-task-type]")).map(
      (item) => item.dataset.recentProductTaskType,
    ),
  }));
  await page.click(
    `#view-product.is-active [data-continue-recent-product-task="${recentFixture.no_report_task_id}"]`,
  );
  await page.waitForFunction(
    (taskId) => state.view === "cockpit" && state.aiCeoExplicitTaskContext?.taskId === taskId,
    recentFixture.no_report_task_id,
    { timeout: 20000 },
  );
  const recentNoReportContext = await page.evaluate(() => ({
    task_id: state.aiCeoExplicitTaskContext?.taskId || "",
    title: state.aiCeoExplicitTaskContext?.title || "",
    missing_facts: state.aiCeoExplicitTaskContext?.missingFacts || [],
  }));
  await page.click('#view-cockpit.is-active [data-global-flow-view="product"][data-global-flow-key="recent"]');
  await page.waitForSelector(
    `#view-product.is-active [data-open-recent-product-task="${recentFixture.product_task_id}"]`,
    { timeout: 20000 },
  );
  await page.click(
    `#view-product.is-active [data-open-recent-product-task="${recentFixture.product_task_id}"]`,
  );
  await page.waitForFunction(
    ({ reportId }) =>
      state.saasListingComposerDraft?.source_report_id === reportId &&
      state.saasListingSourceMode === "recent_product_task" &&
      state.view === "product",
    { reportId: recentFixture.report_id },
    { timeout: 20000 },
  );
  const recentResume = await page.evaluate(() => ({
    source_report_id: state.saasListingComposerDraft?.source_report_id || "",
    listing_project_key: saasCurrentListingProjectIdentity(state.saasListingComposerDraft)?.key || "",
    source_mode: state.saasListingSourceMode || "",
    route_view: new URL(window.location.href).searchParams.get("view") || "",
    task_count: Array.isArray(state.saasTasks) ? state.saasTasks.length : -1,
    report_count: Array.isArray(state.saasReports) ? state.saasReports.length : -1,
    active_mode: document.querySelector('#view-product.is-active [data-listing-mode][aria-current="page"]')?.dataset.listingMode || "",
  }));
  await page.waitForTimeout(750);
  const recentMutationRequests = workflowMutationRequests.slice(recentMutationRequestStart);

  const bulkReturnMutationRequestStart = workflowMutationRequests.length;
  await page.evaluate((fixture) => {
    state.saasListingComposerDraft = JSON.parse(JSON.stringify(fixture.composer || {}));
    state.activeListingDraft = fixture.active_listing_draft || "";
    state.activeMediaDraft = fixture.active_media_draft || "";
    state.saasListingSourceMode = fixture.listing_source_mode || "bulk_handoff";
    state.sourceHandoffStatus = fixture.source_handoff_status || "sent";
    state.saasActiveListingMode = "single";
    state.mediaTaskEntry = "project";
    saveSaasProtectedStateSnapshot();
    setView("product");
    renderProductListingCenter();
  }, bulkProductFixture);
  await page.waitForFunction(
    (expectedProduct) =>
      state.view === "product" &&
      state.saasListingComposerDraft?.source_type === "bulk_handoff" &&
      state.saasListingComposerDraft?.product === expectedProduct,
    acceptanceProduct,
    { timeout: 20000 },
  );
  const bulkReturn = await page.evaluate(() => ({
    product: state.saasListingComposerDraft?.product || "",
    source_type: state.saasListingComposerDraft?.source_type || "",
    active_media_draft: state.activeMediaDraft || "",
    active_mode: document.querySelector('#view-product.is-active [data-listing-mode][aria-current="page"]')?.dataset.listingMode || "",
  }));
  const bulkReturnMutationRequests = workflowMutationRequests.slice(bulkReturnMutationRequestStart);

  await page.evaluate(() => {
    document.querySelector('#view-product.is-active [data-saas-action="open-media"], #view-product.is-active [data-product-action="media"]')?.click();
  });
  smokeStage = "opening_media_for_listing_project";
  await waitForReady(page, "#view-media.is-active");
  await page.waitForFunction(
    () => {
      const activeTab = document.querySelector("#view-media.is-active .media-project-tab.is-active");
      return Boolean(activeTab && activeTab.getAttribute("data-media-draft") === state.activeMediaDraft && String(state.activeMediaDraft || "").startsWith("listing-project-"));
    },
    null,
    { timeout: 60000 },
  );
  await page
    .screenshot({ path: path.join(outDir, "04-media-bulk-draft-open.png"), fullPage: true, timeout: 15000 })
    .catch((error) => screenshotFailures.push({ view: "media-bulk-draft-open", error: String(error.message || error).slice(0, 300) }));

  const mediaOpened = await page.evaluate(() => {
    const root = document.querySelector("#view-media.is-active");
    const activeTab = root?.querySelector(".media-project-tab.is-active");
    const text = root?.innerText || "";
    return {
      active_media_draft: state.activeMediaDraft || "",
      active_tab_draft: activeTab?.getAttribute("data-media-draft") || "",
      listing_project_key: typeof saasCurrentListingProjectIdentity === "function" ? saasCurrentListingProjectIdentity()?.key || "" : "",
      product_name: typeof activeMediaDraftProductNameForDisplay === "function" ? activeMediaDraftProductNameForDisplay() : "",
      has_asset_jobs_panel: Boolean(root?.querySelector(".saas-media-asset-jobs")),
      has_generated_assets_panel: Boolean(root?.querySelector(".saas-media-generated-assets")),
      has_generate_button: Boolean(root?.querySelector("#mediaGenerateImagesDraft")),
      has_writeback_button: Boolean(root?.querySelector("#mediaConfirmDraft")),
      has_workflow_copy: text.includes("回写 Listing") && text.includes("不直接发布"),
      exposes_provider_copy: /FAL|provider|API key|refresh token/i.test(text),
      preview: text.trim().slice(0, 240),
    };
  });

  smokeStage = "uploading_grounded_media_source";
  const fixturePage = await context.newPage();
  await fixturePage.setViewportSize({ width: 720, height: 720 });
  await fixturePage.setContent(
    '<main style="width:680px;height:680px;display:grid;place-items:center;background:#fff;border:20px solid #0a8f87;font-family:Arial,sans-serif;text-align:center"><div><strong id="fixture-label" style="display:block;font-size:42px;color:#10241f"></strong><span style="display:block;margin-top:24px;font-size:24px;color:#52645f">CONTROLLED QA SOURCE IMAGE<br>NOT FOR REAL LISTING</span></div></main>',
  );
  await fixturePage.locator("#fixture-label").evaluate((node, label) => {
    node.textContent = label;
  }, acceptanceProduct);
  await fixturePage.locator("main").screenshot({ path: sourceFixturePath });
  await fixturePage.close();
  await page.setInputFiles("#mediaSourceFileInput", sourceFixturePath);
  await page.waitForFunction(
    () => {
        const assetId = String(state.saasMediaSourceUpload?.asset_id || "");
        return Boolean(assetId && state.saasMediaSourceUpload?.provider_reference_ready === true);
    },
    null,
    { timeout: 60000 },
  );
  const sourceUpload = await page.evaluate(() => ({
    asset_id: state.saasMediaSourceUpload?.asset_id || "",
    content_type: state.saasMediaSourceUpload?.content_type || "",
    size_bytes: state.saasMediaSourceUpload?.size_bytes || 0,
    listing_project_key: state.saasMediaSourceUpload?.listing_project_key || "",
    provider_reference_ready: state.saasMediaSourceUpload?.provider_reference_ready === true,
    source_url_retained: Boolean(state.saasMediaSourceUpload?.source_url),
    secret_exposed: JSON.stringify(state.saasMediaSourceUpload || {}).toLowerCase().includes("api_key"),
  }));

  await page.evaluate(({ includeVideo }) => {
    const countSelect = document.querySelector("#view-media.is-active #mediaCountSelect");
    if (countSelect) {
      const singleOption = Array.from(countSelect.options || []).find((option) => /^1\s/.test(String(option.value || option.textContent || "")));
      if (singleOption) countSelect.value = singleOption.value;
      countSelect.dispatchEvent(new Event("change", { bubbles: true }));
    }
    const videoPreset = document.querySelector("#view-media.is-active #mediaVideoPresetSelect");
    if (includeVideo && videoPreset) {
      videoPreset.value = "10 秒产品展示视频";
      videoPreset.dispatchEvent(new Event("change", { bubbles: true }));
    }
    document.querySelector("#view-media.is-active #mediaGenerateImagesDraft")?.click();
  }, { includeVideo });
  await page.waitForSelector("#mediaAcceptanceModal:not([hidden]) #mediaAcceptanceConfirm", { timeout: 10000 });
  const mediaGenerationAcceptance = await page.evaluate(() => {
    const modal = document.querySelector("#mediaAcceptanceModal:not([hidden])");
    const text = modal?.innerText || "";
    return {
      visible: Boolean(modal),
      confirms_rights: text.includes("商业使用") || text.includes("图片权利"),
      preserves_draft_boundary: text.includes("不会自动发布") && text.includes("不会") && text.includes("eBay"),
      confirm_label: document.querySelector("#mediaAcceptanceConfirm")?.textContent?.trim() || "",
    };
  });
  await page.locator("#mediaAcceptanceModal:not([hidden]) #mediaAcceptanceConfirm").click();
  smokeStage = "generating_media_assets";
  await page.waitForFunction(
    () => ["submitted", "generated", "done"].includes(state.mediaGenerationStatus) && (document.querySelector("#mediaProductionStatus")?.textContent || "").length > 0,
    null,
    { timeout: 60000 },
  );
  const assetWaitTimeout = includeVideo ? 480000 : 60000;
  await page
    .waitForFunction(
      ({ includeVideo }) =>
        (state.saasMediaAssetJobs || []).some(
          (job) =>
            job &&
            String(job.status || "") === "waiting_review" &&
            Array.isArray(job.asset_manifest) &&
            job.asset_manifest.length > 0 &&
            (!includeVideo || job.asset_manifest.some((asset) => /video/i.test(String(asset?.asset_type || "")))),
        ),
      { includeVideo },
      { timeout: assetWaitTimeout },
    )
    .catch(() => {});
  let mediaJobsApi = mediaFixtureApi();
  let backendMediaJobs = Array.isArray(mediaJobsApi.json?.media_asset_jobs) ? mediaJobsApi.json.media_asset_jobs : [];
  let latestBackendMediaJob = backendMediaJobs[0] || {};
  let backendMediaJob = {
    ok: mediaJobsApi.ok,
    status: mediaJobsApi.status,
    count: backendMediaJobs.length,
    media_job_id: latestBackendMediaJob.media_job_id || "",
    job_status: latestBackendMediaJob.status || "",
    manifest_count: Array.isArray(latestBackendMediaJob.asset_manifest) ? latestBackendMediaJob.asset_manifest.length : 0,
    manifest_types: Array.isArray(latestBackendMediaJob.asset_manifest)
      ? latestBackendMediaJob.asset_manifest.map((asset) => String(asset?.asset_type || ""))
      : [],
    validation_status: latestBackendMediaJob.asset_manifest_validation?.status || "",
    ui_contract_assets_returned: latestBackendMediaJob.live_provider_called === true,
    spend_now_allowed: latestBackendMediaJob.spend_now_allowed,
    secret_exposed: latestBackendMediaJob.secret_exposed,
    fixture_only: latestBackendMediaJob.fixture_only === true,
    external_provider_called: latestBackendMediaJob.external_provider_called === true,
  };
  await page
    .screenshot({ path: path.join(outDir, "05-media-generated-assets.png"), fullPage: true, timeout: 15000 })
    .catch((error) => screenshotFailures.push({ view: "media-generated-assets", error: String(error.message || error).slice(0, 300) }));

  const mediaGenerated = await page.evaluate(() => {
    const root = document.querySelector("#view-media.is-active");
    const text = root?.innerText || "";
    const riskyActionLabels = Array.from(root?.querySelectorAll("button:not([disabled]), a[href]") || [])
      .map((item) => (item.textContent || "").replace(/\s+/g, " ").trim())
      .filter((label) => /(直接发布|一键发布|自动发布|上传到 eBay|发布到 eBay)/.test(label) && !/(不|不会|确认单|体检)/.test(label));
    return {
      media_generation_status: state.mediaGenerationStatus || "",
      has_quality_board: Boolean(root?.querySelector(".media-quality-board, .media-review-board")),
      has_preview_cards: (root?.querySelectorAll("[data-asset-preview]").length || 0) >= 3,
      has_review_copy: text.includes("发布前") || text.includes("审核"),
      has_no_direct_publish_button: riskyActionLabels.length === 0,
      preview: text.trim().slice(0, 240),
    };
  });

  const mediaBeforeReload = await page.evaluate(() => {
    const currentProject = typeof saasCurrentListingProjectIdentity === "function" ? saasCurrentListingProjectIdentity() : {};
    const visibleJobs = typeof saasMediaAssetJobsForDisplay === "function" ? saasMediaAssetJobsForDisplay() : [];
    return {
      listing_project_key: currentProject?.key || "",
      product: currentProject?.product || "",
      media_job_id: visibleJobs[0]?.media_job_id || "",
      visible_job_count: visibleJobs.length,
    };
  });
  smokeStage = "reloading_media_asset_job";
  await page.reload({ waitUntil: "commit", timeout: 90000 });
  await page.waitForSelector("body", { timeout: 30000 });
  await page.waitForLoadState("networkidle", { timeout: 45000 }).catch(() => {});
  await page.waitForFunction(
    () =>
      document.documentElement.classList.contains("app-ready") &&
      !document.querySelector(".auth-shell, .saas-login-modal, [data-auth-view]") &&
      typeof setView === "function",
    null,
    { timeout: 90000 },
  );
  await page.evaluate(() => setView("media"));
  await waitForReady(page, "#view-media.is-active");
  let mediaReloadWaitError = "";
  await page
    .waitForFunction(
      (expectedMediaJobId) => {
        const visibleJobs = typeof saasMediaAssetJobsForDisplay === "function" ? saasMediaAssetJobsForDisplay() : [];
        return Boolean(expectedMediaJobId && visibleJobs.some((job) => job?.media_job_id === expectedMediaJobId));
      },
      mediaBeforeReload.media_job_id,
      { timeout: 60000 },
    )
    .catch((error) => {
      mediaReloadWaitError = String(error?.message || error).slice(0, 500);
    });
  const mediaAfterReload = await page.evaluate(() => {
    const currentProject = typeof saasCurrentListingProjectIdentity === "function" ? saasCurrentListingProjectIdentity() : {};
    const visibleJobs = typeof saasMediaAssetJobsForDisplay === "function" ? saasMediaAssetJobsForDisplay() : [];
    const allJobs = Array.isArray(state.saasMediaAssetJobs) ? state.saasMediaAssetJobs : [];
    const snapshotKeys = typeof saasProtectedSnapshotStorageKeys === "function" ? saasProtectedSnapshotStorageKeys() : [];
    const snapshot = snapshotKeys
      .map((key) => {
        try {
          return JSON.parse(localStorage.getItem(key) || "null");
        } catch (_error) {
          return null;
        }
      })
      .find(Boolean);
    return {
      listing_project_key: currentProject?.key || "",
      product: currentProject?.product || "",
      media_job_id: visibleJobs[0]?.media_job_id || "",
      visible_job_count: visibleJobs.length,
      restored_from_snapshot: Boolean(state.saasListingComposerDraft?.listing_project_key),
      exposes_other_product: visibleJobs.some((job) => !saasMediaAssetJobMatchesListingProject(job)),
      active_media_draft: state.activeMediaDraft || "",
      composer: {
        listing_project_key: state.saasListingComposerDraft?.listing_project_key || "",
        product: state.saasListingComposerDraft?.product || "",
        source_type: state.saasListingComposerDraft?.source_type || "",
        source_report_id: state.saasListingComposerDraft?.source_report_id || "",
        candidate_id: state.saasListingComposerDraft?.selected_product_candidate?.candidate_id || "",
      },
      all_jobs: allJobs.map((job) => ({
        media_job_id: job?.media_job_id || "",
        status: job?.status || "",
        listing_project_key: saasMediaAssetJobProductFacts(job)?.listing_project_key || "",
        product: saasMediaAssetJobProductFacts(job)?.product || "",
        matches: saasMediaAssetJobMatchesListingProject(job),
      })),
      snapshot: snapshot
        ? {
            version: snapshot.version || "",
            listing_project_key: snapshot.listing_composer_draft?.listing_project_key || "",
            product: snapshot.listing_composer_draft?.product || "",
            active_media_draft: snapshot.active_media_draft || "",
            media_job_ids: Array.isArray(snapshot.media_asset_jobs) ? snapshot.media_asset_jobs.map((job) => job?.media_job_id || "") : [],
          }
        : null,
    };
  });
  if (mediaReloadWaitError) {
    fail("media asset job was not restored after reload", { mediaReloadWaitError, mediaBeforeReload, mediaAfterReload });
  }

  const manifestPreview = page.locator('#view-media.is-active [data-asset-preview^="manifest:"]').first();
  await manifestPreview.click();
  await page.waitForSelector("#assetModal:not([hidden])", { timeout: 30000 });
  const reviewChecks = page.locator("#assetModal [data-media-review-check]");
  const reviewCheckCount = await reviewChecks.count();
  if (reviewCheckCount < 3) fail("media review checklist is incomplete", { reviewCheckCount });
  for (let index = 0; index < reviewCheckCount; index += 1) {
    await reviewChecks.nth(index).check();
  }
  await page.click("#assetSendConfirm");
  await page.waitForFunction(
    () => (state.saasMediaAssetJobs || []).some((job) => job?.status === "approved_for_listing"),
    null,
    { timeout: 30000 },
  );
  mediaJobsApi = mediaFixtureApi();
  backendMediaJobs = Array.isArray(mediaJobsApi.json?.media_asset_jobs) ? mediaJobsApi.json.media_asset_jobs : [];
  latestBackendMediaJob = backendMediaJobs[0] || {};
  backendMediaJob = {
    ok: mediaJobsApi.ok,
    status: mediaJobsApi.status,
    count: backendMediaJobs.length,
    media_job_id: latestBackendMediaJob.media_job_id || "",
    job_status: latestBackendMediaJob.status || "",
    manifest_count: Array.isArray(latestBackendMediaJob.asset_manifest) ? latestBackendMediaJob.asset_manifest.length : 0,
    manifest_types: Array.isArray(latestBackendMediaJob.asset_manifest)
      ? latestBackendMediaJob.asset_manifest.map((asset) => String(asset?.asset_type || ""))
      : [],
    validation_status: latestBackendMediaJob.asset_manifest_validation?.status || "",
    ui_contract_assets_returned: latestBackendMediaJob.live_provider_called === true,
    spend_now_allowed: latestBackendMediaJob.spend_now_allowed,
    secret_exposed: latestBackendMediaJob.secret_exposed,
    fixture_only: latestBackendMediaJob.fixture_only === true,
    external_provider_called: latestBackendMediaJob.external_provider_called === true,
  };

  smokeStage = "reloading_approved_media_audit";
  await page.reload({ waitUntil: "commit", timeout: 90000 });
  await page.waitForSelector("body", { timeout: 30000 });
  await page.waitForLoadState("networkidle", { timeout: 45000 }).catch(() => {});
  await page.waitForFunction(
    () =>
      document.documentElement.classList.contains("app-ready") &&
      !document.querySelector(".auth-shell, .saas-login-modal, [data-auth-view]") &&
      typeof setView === "function",
    null,
    { timeout: 90000 },
  );
  await page.evaluate(() => setView("media"));
  await waitForReady(page, "#view-media.is-active");
  await page.waitForFunction(
    () => {
      const job = latestSaasMediaAssetJobWithManifest({ requireCurrentProject: true });
      const button = document.querySelector("#view-media.is-active #mediaConfirmDraft");
      return job?.status === "approved_for_listing" && button?.disabled === false && button?.dataset?.mediaWritebackGate === "revalidation_required";
    },
    null,
    { timeout: 30000 },
  );
  const approvedMediaAfterReload = await page.evaluate(() => {
    const job = latestSaasMediaAssetJobWithManifest({ requireCurrentProject: true });
    const gate = saasApprovedMediaWritebackGate(job);
    let snapshot = null;
    try {
      snapshot = JSON.parse(localStorage.getItem(saasProtectedSnapshotStorageKey()) || "null");
    } catch (_error) {
      snapshot = null;
    }
    const snapshotJob = Array.isArray(snapshot?.media_asset_jobs)
      ? snapshot.media_asset_jobs.find((item) => item?.media_job_id === job?.media_job_id)
      : null;
    const button = document.querySelector("#view-media.is-active #mediaConfirmDraft");
    return {
      media_job_id: job?.media_job_id || "",
      status: job?.status || "",
      gate_allowed: gate.allowed === true,
      gate_reason: gate.reason || "",
      button_disabled: Boolean(button?.disabled),
      button_gate: button?.dataset?.mediaWritebackGate || "",
      source_upload_present: Boolean(state.saasMediaSourceUpload),
      merchant_review_decision: job?.merchant_review?.decision || "",
      commercial_rights_confirmed: job?.merchant_review?.confirmations?.commercial_rights_confirmed === true,
      snapshot_merchant_review_decision: snapshotJob?.merchant_review?.decision || "",
    };
  });

  const mediaWritebackRevalidationRequestStart = mediaFixtureState.requests.length;
  const mediaWritebackClick = await page.evaluate(() => {
    const button = document.querySelector("#view-media.is-active #mediaConfirmDraft");
    const before = {
      found: Boolean(button),
      disabled: Boolean(button?.disabled),
      media_generation_status: state.mediaGenerationStatus || "",
      visible_jobs: saasMediaAssetJobsForDisplay().map((job) => ({ media_job_id: job?.media_job_id || "", status: job?.status || "" })),
    };
    button?.click();
    return before;
  });
  smokeStage = "writing_media_back_to_listing";
  let mediaWritebackViewError = "";
  await waitForReady(page, "#view-product.is-active", 10000).catch((error) => {
    mediaWritebackViewError = String(error?.message || error).slice(0, 500);
  });
  if (mediaWritebackViewError) {
    const mediaWritebackViewDebug = await page.evaluate(() => {
      return {
        body_view: document.body?.dataset?.view || "",
        state_view: state.view || "",
        button_disabled: Boolean(document.querySelector("#mediaConfirmDraft")?.disabled),
        composer: {
          source_type: state.saasListingComposerDraft?.source_type || "",
          product: state.saasListingComposerDraft?.product || "",
          listing_project_key: state.saasListingComposerDraft?.listing_project_key || "",
          media_writeback: state.saasListingComposerDraft?.media_writeback || null,
        },
        media_generation_status: state.mediaGenerationStatus || "",
        visible_jobs: saasMediaAssetJobsForDisplay().map((job) => ({
          media_job_id: job?.media_job_id || "",
          status: job?.status || "",
          manifest_count: Array.isArray(job?.asset_manifest) ? job.asset_manifest.length : 0,
          concept_only: saasMediaAssetJobIsConceptOnly(job),
          listing_asset_count: saasMediaManifestAssetsForListing(job).length,
          asset_references: (job?.asset_manifest || []).map((asset) => {
            const raw = String(asset?.url_or_file_path || asset?.url || asset?.file_path || "");
            let scheme = "";
            try {
              scheme = new URL(raw, window.location.origin).protocol;
            } catch (_error) {
              scheme = "invalid";
            }
            return {
              scheme,
              starts_with_slash: raw.startsWith("/"),
              starts_with_data: raw.startsWith("data:"),
              safe_for_listing: Boolean(saasSafeListingAssetUrl(raw)),
            };
          }),
          matches: saasMediaAssetJobMatchesListingProject(job),
        })),
      };
    });
    fail("media writeback did not open Listing after reload", { mediaWritebackViewError, mediaWritebackClick, mediaWritebackViewDebug });
  }
  let mediaWritebackWaitError = "";
  await page
    .waitForFunction(
      () =>
        document.body?.dataset?.view === "product" &&
        state.saasListingComposerDraft?.source_type === "bulk_handoff" &&
        state.saasListingComposerDraft?.media_writeback?.status === "merchant_reviewed_for_listing_draft",
      null,
      { timeout: 60000 },
    )
    .catch((error) => {
      mediaWritebackWaitError = String(error?.message || error).slice(0, 500);
    });
  if (mediaWritebackWaitError) {
    const mediaWritebackDebug = await page.evaluate(() => ({
      body_view: document.body?.dataset?.view || "",
      state_view: state.view || "",
      button_disabled: Boolean(document.querySelector("#mediaConfirmDraft")?.disabled),
      composer: {
        source_type: state.saasListingComposerDraft?.source_type || "",
        product: state.saasListingComposerDraft?.product || "",
        listing_project_key: state.saasListingComposerDraft?.listing_project_key || "",
        media_writeback: state.saasListingComposerDraft?.media_writeback || null,
      },
      media_generation_status: state.mediaGenerationStatus || "",
      visible_jobs: saasMediaAssetJobsForDisplay().map((job) => ({
        media_job_id: job?.media_job_id || "",
        status: job?.status || "",
        matches: saasMediaAssetJobMatchesListingProject(job),
      })),
    }));
    fail("approved media was not written back to Listing after reload", { mediaWritebackWaitError, mediaWritebackDebug });
  }
  const mediaWritebackRevalidationRequests = mediaFixtureState.requests
    .slice(mediaWritebackRevalidationRequestStart)
    .filter((item) => item.method === "GET" && item.fixture === "job");
  await page
    .screenshot({ path: path.join(outDir, "06-product-after-media-writeback.png"), fullPage: true, timeout: 15000 })
    .catch((error) => screenshotFailures.push({ view: "product-after-media-writeback", error: String(error.message || error).slice(0, 300) }));

  const productAfterMedia = await page.evaluate(() => {
    const root = document.querySelector("#view-product.is-active");
    const text = root?.innerText || "";
    const riskyActionLabels = Array.from(root?.querySelectorAll("button:not([disabled]), a[href]") || [])
      .map((item) => (item.textContent || "").replace(/\s+/g, " ").trim())
      .filter((label) => /(直接发布|一键发布|上传到 eBay|发布到 eBay)/.test(label) && !/(不|不会|确认单|体检)/.test(label));
    return {
      active_listing_draft: state.activeListingDraft || "",
      active_media_draft: state.activeMediaDraft || "",
      active_flow_key: state.activeFlowKey || "",
      has_writeback_feedback: text.includes("素材包已回写") || text.includes("素材工坊"),
      has_publish_confirmation_flow: text.includes("发布前") || text.includes("确认中心"),
      has_no_direct_publish_button: riskyActionLabels.length === 0,
      preview: text.trim().slice(0, 240),
    };
  });

  const [healthApi, readinessApi] = await Promise.all([api("/health"), api("/readiness/product-saas")]);
  const checks = {
    bulk_initial_visible_and_safe:
      bulkInitial.visible &&
      bulkInitial.has_generate_button &&
      bulkInitial.has_safety_copy &&
      !bulkInitial.has_direct_publish_button &&
      JSON.stringify(bulkInitial.listing_mode_order) === JSON.stringify(["single", "bulk", "recent"]) &&
      JSON.stringify(bulkInitial.bulk_mode_active) === JSON.stringify(["bulk"]) &&
      bulkInitial.product_primary_nav_active === true &&
      bulkInitial.bulk_primary_nav_count === 0,
    bulk_candidates_generated: bulkGenerated.preview_count > 0 && bulkGenerated.has_accept_button && bulkGenerated.has_grouping_copy && bulkGenerated.has_safety_copy,
    bulk_handoff_reaches_listing:
      productAfterBulk.source_type === "bulk_handoff" &&
      productAfterBulk.active_media_draft.startsWith("saas-bulk-") &&
      productAfterBulk.active_title_cn === acceptanceProduct &&
      productAfterBulk.cost_price.includes("11.8") &&
      productAfterBulk.logistics.includes("Yiwu") &&
      productAfterBulk.handoff_status === "sent" &&
      productAfterBulk.title_is_not_generic_ai_ceo_report &&
      productAfterBulk.has_media_button &&
      JSON.stringify(productAfterBulk.listing_mode_order) === JSON.stringify(["single", "bulk", "recent"]) &&
      JSON.stringify(productAfterBulk.single_mode_active) === JSON.stringify(["single"]),
    recent_filters_real_product_workflow_tasks:
      recentList.task_ids.includes(recentFixture.product_task_id) &&
      !recentList.task_ids.includes(recentFixture.unrelated_task_id) &&
      recentList.task_types.length === recentList.task_ids.length &&
      recentList.task_types.every((taskType) => taskType === "product_workflow"),
    recent_resumes_existing_identity_without_rerun:
      recentResume.source_report_id === recentFixture.report_id &&
      recentResume.listing_project_key.startsWith("listing-project-recent-") &&
      recentResume.source_mode === "recent_product_task" &&
      recentResume.route_view === "product" &&
      recentResume.task_count === recentFixture.task_count &&
      recentResume.report_count === recentFixture.report_count &&
      recentResume.active_mode === "single" &&
      recentMutationRequests.length === 0,
    recent_no_report_binds_explicit_context_without_rerun:
      recentNoReportContext.task_id === recentFixture.no_report_task_id &&
      Boolean(recentNoReportContext.title) &&
      recentNoReportContext.missing_facts.includes("包装尺寸") &&
      recentMutationRequests.length === 0,
    bulk_return_restores_original_product_without_rerun:
      bulkReturn.product === acceptanceProduct &&
      bulkReturn.source_type === "bulk_handoff" &&
      bulkReturn.active_media_draft.startsWith("saas-bulk-") &&
      bulkReturn.active_mode === "single" &&
      bulkReturnMutationRequests.length === 0,
    media_opens_same_bulk_draft:
      mediaOpened.active_media_draft.startsWith("listing-project-") &&
      mediaOpened.active_media_draft === mediaOpened.listing_project_key &&
      mediaOpened.active_tab_draft === mediaOpened.active_media_draft &&
      mediaOpened.product_name === acceptanceProduct &&
      mediaOpened.has_asset_jobs_panel &&
      mediaOpened.has_generate_button &&
      mediaOpened.has_writeback_button &&
      mediaOpened.has_workflow_copy &&
      !mediaOpened.exposes_provider_copy,
    grounded_source_upload_ready:
      Boolean(sourceUpload.asset_id) &&
      sourceUpload.content_type === "image/png" &&
      sourceUpload.size_bytes > 0 &&
      sourceUpload.listing_project_key === mediaOpened.listing_project_key &&
      sourceUpload.provider_reference_ready === true &&
      sourceUpload.source_url_retained === false &&
      sourceUpload.secret_exposed === false,
    media_generation_acceptance_is_explicit_and_safe:
      mediaGenerationAcceptance.visible &&
      mediaGenerationAcceptance.confirms_rights &&
      mediaGenerationAcceptance.preserves_draft_boundary &&
      mediaGenerationAcceptance.confirm_label.includes("确认"),
    media_generation_creates_reviewable_assets:
      ["submitted", "generated", "done"].includes(mediaGenerated.media_generation_status) &&
      mediaGenerated.has_review_copy &&
      mediaGenerated.has_no_direct_publish_button,
    media_generation_created_reviewable_frontend_fixture:
      backendMediaJob.ok &&
      backendMediaJob.count >= 1 &&
      backendMediaJob.job_status === "approved_for_listing" &&
      backendMediaJob.manifest_count > 0 &&
      backendMediaJob.validation_status === "manifest_ready" &&
      backendMediaJob.ui_contract_assets_returned === true &&
      backendMediaJob.fixture_only === true &&
      backendMediaJob.external_provider_called === false &&
      backendMediaJob.spend_now_allowed === false &&
      backendMediaJob.secret_exposed === false,
    approved_media_audit_survives_reload_and_unlocks_same_draft:
      approvedMediaAfterReload.status === "approved_for_listing" &&
      approvedMediaAfterReload.gate_allowed === true &&
      approvedMediaAfterReload.gate_reason === "approved_for_listing_draft" &&
      approvedMediaAfterReload.button_disabled === false &&
      approvedMediaAfterReload.button_gate === "revalidation_required" &&
      approvedMediaAfterReload.source_upload_present === false &&
      approvedMediaAfterReload.merchant_review_decision === "approve_for_listing_draft" &&
      approvedMediaAfterReload.commercial_rights_confirmed === true &&
      approvedMediaAfterReload.snapshot_merchant_review_decision === "approve_for_listing_draft",
    media_writeback_revalidates_authoritative_backend_job:
      mediaWritebackRevalidationRequests.length === 1 &&
      mediaWritebackRevalidationRequests[0].path === `/media-asset-jobs/${approvedMediaAfterReload.media_job_id}`,
    media_job_survives_reload_for_same_listing:
      Boolean(mediaBeforeReload.media_job_id) &&
      mediaAfterReload.media_job_id === mediaBeforeReload.media_job_id &&
      mediaAfterReload.listing_project_key === mediaBeforeReload.listing_project_key &&
      mediaAfterReload.product === mediaBeforeReload.product &&
      mediaAfterReload.visible_job_count > 0 &&
      mediaAfterReload.restored_from_snapshot === true &&
      mediaAfterReload.exposes_other_product === false,
    requested_video_returned:
      !includeVideo || backendMediaJob.manifest_types.some((assetType) => /video/i.test(assetType)),
    media_writeback_returns_to_listing:
      productAfterMedia.active_media_draft === mediaOpened.active_media_draft &&
      productAfterMedia.active_flow_key === "product" &&
      productAfterMedia.has_writeback_feedback &&
      productAfterMedia.has_publish_confirmation_flow &&
      productAfterMedia.has_no_direct_publish_button,
    no_real_platform_writes_triggered: healthApi.json?.real_platform_writes_enabled === false,
    public_gate_still_not_production_ready:
      readinessApi.ok &&
      readinessApi.json?.readiness?.production_ready === false && readinessApi.json?.readiness?.can_accept_real_customers === false,
    no_forbidden_requests: forbiddenRequests.length === 0,
    no_paid_or_external_media_call:
      mediaFixtureState.requests.some((item) => item.fixture === "queue") &&
      mediaFixtureState.requests.some((item) => item.fixture === "review") &&
      backendMediaJob.fixture_only === true &&
      backendMediaJob.external_provider_called === false,
    registration_trial_metadata_safe: session.platformTrialActivation.secret_exposed === false,
    no_secret_exposed:
      !JSON.stringify({ bulkInitial, bulkGenerated, productAfterBulk, mediaOpened, mediaGenerated, mediaBeforeReload, mediaAfterReload, backendMediaJob, productAfterMedia })
        .toLowerCase()
        .includes("refresh_token"),
  };
  const result = {
    ok: Object.values(checks).every(Boolean) && !pageErrors.length && !requestFailures.length && !badResponses.length && !forbiddenRequests.length,
    marker: smokeMarker,
    acceptance_product: acceptanceProduct,
    include_video: includeVideo,
    timestamp: new Date().toISOString(),
    base,
    outDir,
    session: {
      email_masked: session.email.replace(/^(.{2}).*(@.*)$/, "$1***$2"),
      store_id: session.store.store_id,
      platform_trial_activation: session.platformTrialActivation,
    },
    checks,
    bulkInitial,
    bulkGenerated,
    productAfterBulk,
    recentFixture,
    recentList,
    recentNoReportContext,
    recentResume,
    recentMutationRequests,
    bulkReturn,
    bulkReturnMutationRequests,
    mediaOpened,
    sourceUpload,
    mediaGenerationAcceptance,
    mediaGenerated,
    mediaBeforeReload,
    mediaAfterReload,
    approvedMediaAfterReload,
    mediaWritebackRevalidationRequests,
    backendMediaJob,
    mediaFixtureRequests: mediaFixtureState.requests,
    productAfterMedia,
    api: {
      real_platform_writes_enabled: healthApi.json?.real_platform_writes_enabled,
      readiness_status: readinessApi.status,
      readiness_ok: readinessApi.ok,
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
    fail(`bulk media handoff smoke failed: ${failures.join(", ")}`, { outDir });
  }
  console.log(JSON.stringify(result, null, 2));
}

if (require.main === module) {
  main().catch((error) => {
    console.error(
      JSON.stringify(
        {
          ok: false,
          message: error.message,
          stage: smokeStage,
          details: error.details || {},
          outDir,
        },
        null,
        2,
      ),
    );
    process.exit(1);
  });
}
