#!/usr/bin/env node
/* ASCII-only no-write smoke for Bulk -> Listing -> Media -> Listing handoff. */

const fs = require("fs");
const path = require("path");
const { chromium } = require("../output/codex-playwright-deps/node_modules/playwright-core");

const base = process.env.JIEJING_TEST_BASE || "https://app.jiejing.shop";
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
    if (
      /signin\.ebay|auth\.ebay|ebay\.com\/signin|\/oauth\/authorize|\/oauth\/callback|stripe\.com|paypal\.com|checkout\.stripe\.com|\/billing\/checkout-session|\/billing\/provider-rehearsal|\/ebay\/publish|\/ads\/|\/refund|\/procurement|\/inventory\/write/i.test(
        url,
      )
    ) {
      forbiddenRequests.push(url);
    }
  });
  page.on("requestfailed", (request) => {
    if (request.url().startsWith(base)) {
      const failure = request.failure()?.errorText || "";
      const resourceType = request.resourceType();
      // Images can be aborted during intentional view transitions. Treat only app/API/script failures as smoke blockers.
      if (resourceType === "image" && /ERR_ABORTED/i.test(failure)) return;
      requestFailures.push({ url: request.url(), error: failure, resourceType });
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
    const riskyActionLabels = Array.from(root?.querySelectorAll("button:not([disabled]), a[href]") || [])
      .map((item) => (item.textContent || "").replace(/\s+/g, " ").trim())
      .filter((label) => /(直接发布|一键发布|上传到 eBay|发布到 eBay)/.test(label) && !/(不|不会|确认单|体检)/.test(label));
    return {
      visible: Boolean(root && root.offsetParent !== null),
      has_generate_button: Boolean(root?.querySelector('[data-bulk-action="generate-candidates"]')),
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
    ].join("\n"),
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
    const riskyActionLabels = Array.from(root?.querySelectorAll("button:not([disabled]), a[href]") || [])
      .map((item) => (item.textContent || "").replace(/\s+/g, " ").trim())
      .filter((label) => /(直接发布|一键发布|上传到 eBay|发布到 eBay)/.test(label) && !/(不|不会|确认单|体检)/.test(label));
    return {
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
  const sourceFixturePath = path.join(outDir, "controlled-merchant-source.png");
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
      try {
        const sourceUrl = new URL(String(state.saasMediaSourceUpload?.source_url || ""));
        const isLoopback = ["127.0.0.1", "localhost", "::1"].includes(sourceUrl.hostname);
        const transportAllowed = sourceUrl.protocol === "https:" || (isLoopback && sourceUrl.protocol === "http:");
        return Boolean(assetId && transportAllowed && sourceUrl.searchParams.get("signature"));
      } catch (_error) {
        return false;
      }
    },
    null,
    { timeout: 60000 },
  );
  const sourceUpload = await page.evaluate(() => ({
    asset_id: state.saasMediaSourceUpload?.asset_id || "",
    content_type: state.saasMediaSourceUpload?.content_type || "",
    size_bytes: state.saasMediaSourceUpload?.size_bytes || 0,
    listing_project_key: state.saasMediaSourceUpload?.listing_project_key || "",
    source_url_signed: (() => {
      try {
        const sourceUrl = new URL(String(state.saasMediaSourceUpload?.source_url || ""));
        const isLoopback = ["127.0.0.1", "localhost", "::1"].includes(sourceUrl.hostname);
        return Boolean(
          (sourceUrl.protocol === "https:" || (isLoopback && sourceUrl.protocol === "http:")) &&
            sourceUrl.searchParams.get("signature"),
        );
      } catch (_error) {
        return false;
      }
    })(),
    secret_exposed: JSON.stringify(state.saasMediaSourceUpload || {}).toLowerCase().includes("api_key"),
  }));

  await page.evaluate(({ includeVideo }) => {
    const videoPreset = document.querySelector("#view-media.is-active #mediaVideoPresetSelect");
    if (includeVideo && videoPreset) {
      videoPreset.value = "10 秒产品展示视频";
      videoPreset.dispatchEvent(new Event("change", { bubbles: true }));
    }
    document.querySelector("#view-media.is-active #mediaGenerateImagesDraft")?.click();
  }, { includeVideo });
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
  let mediaJobsApi = await api(`/stores/${encodeURIComponent(session.store.store_id)}/media-asset-jobs?limit=8`, {
    token: session.token,
  });
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
    live_provider_called: latestBackendMediaJob.live_provider_called,
    spend_now_allowed: latestBackendMediaJob.spend_now_allowed,
    secret_exposed: latestBackendMediaJob.secret_exposed,
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
  mediaJobsApi = await api(`/stores/${encodeURIComponent(session.store.store_id)}/media-asset-jobs?limit=8`, {
    token: session.token,
  });
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
    live_provider_called: latestBackendMediaJob.live_provider_called,
    spend_now_allowed: latestBackendMediaJob.spend_now_allowed,
    secret_exposed: latestBackendMediaJob.secret_exposed,
  };

  await page.evaluate(() => {
    document.querySelector("#view-media.is-active #mediaConfirmDraft")?.click();
  });
  smokeStage = "writing_media_back_to_listing";
  await waitForReady(page, "#view-product.is-active");
  await page.waitForFunction(
    () =>
      document.body?.dataset?.view === "product" &&
      state.saasListingComposerDraft?.source_type === "bulk_handoff" &&
      state.saasListingComposerDraft?.media_writeback?.status === "merchant_reviewed_for_listing_draft",
    null,
    { timeout: 60000 },
  );
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
    bulk_initial_visible_and_safe: bulkInitial.visible && bulkInitial.has_generate_button && bulkInitial.has_safety_copy && !bulkInitial.has_direct_publish_button,
    bulk_candidates_generated: bulkGenerated.preview_count > 0 && bulkGenerated.has_accept_button && bulkGenerated.has_grouping_copy && bulkGenerated.has_safety_copy,
    bulk_handoff_reaches_listing:
      productAfterBulk.source_type === "bulk_handoff" &&
      productAfterBulk.active_media_draft.startsWith("saas-bulk-") &&
      productAfterBulk.active_title_cn === acceptanceProduct &&
      productAfterBulk.cost_price.includes("11.8") &&
      productAfterBulk.logistics.includes("Yiwu") &&
      productAfterBulk.handoff_status === "sent" &&
      productAfterBulk.title_is_not_generic_ai_ceo_report &&
      productAfterBulk.has_media_button,
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
      sourceUpload.source_url_signed === true &&
      sourceUpload.secret_exposed === false,
    media_generation_creates_reviewable_assets:
      ["submitted", "generated", "done"].includes(mediaGenerated.media_generation_status) &&
      mediaGenerated.has_review_copy &&
      mediaGenerated.has_no_direct_publish_button,
    media_generation_created_backend_asset_job:
      backendMediaJob.ok &&
      backendMediaJob.count >= 1 &&
      backendMediaJob.job_status === "approved_for_listing" &&
      backendMediaJob.manifest_count > 0 &&
      backendMediaJob.validation_status === "manifest_ready" &&
      backendMediaJob.live_provider_called === true &&
      backendMediaJob.spend_now_allowed === false &&
      backendMediaJob.secret_exposed === false,
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
    no_secret_exposed:
      !JSON.stringify({ bulkInitial, bulkGenerated, productAfterBulk, mediaOpened, mediaGenerated, backendMediaJob, productAfterMedia })
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
    },
    checks,
    bulkInitial,
    bulkGenerated,
    productAfterBulk,
    mediaOpened,
    sourceUpload,
    mediaGenerated,
    backendMediaJob,
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
