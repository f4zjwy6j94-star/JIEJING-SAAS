#!/usr/bin/env node
/* ASCII-only smoke: one live media image -> AssetManifest -> media studio UI. */

const fs = require("fs");
const path = require("path");
const { chromium } = require("../output/codex-playwright-deps/node_modules/playwright-core");

const base = process.env.JIEJING_TEST_BASE || "https://app.jiejing.shop";
const browserChannel = process.env.JIEJING_PLAYWRIGHT_CHANNEL || "chrome";
const localStaticRoot = process.env.JIEJING_LOCAL_STATIC_ROOT ? path.resolve(process.env.JIEJING_LOCAL_STATIC_ROOT) : "";
const stamp = new Date().toISOString().replace(/[:.]/g, "-");
const outDir = path.join("output", "browser-smoke", `${stamp}-media-live-manifest-ui`);
const smokeMarker = "codex_jiejing_media_live_manifest_ui_smoke";
fs.mkdirSync(outDir, { recursive: true });
const merchantVisibleProviderLeakPattern = /\bFAL\b|fal\.ai|provider key|API key|refresh token/i;
let currentStage = "start";
let currentPage = null;

function stage(name) {
  currentStage = name;
}

function fail(message, details = {}) {
  const error = new Error(message);
  error.details = details;
  throw error;
}

async function api(pathname, { token = "", method = "GET", body } = {}) {
  const response = await fetch(`${base}${pathname}`, {
    method,
    cache: "no-store",
    headers: {
      "content-type": "application/json",
      "user-agent": "Mozilla/5.0 Codex Jiejing Media Live Manifest UI Smoke",
      ...(token ? { authorization: `Bearer ${token}` } : {}),
    },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
  const text = await response.text();
  let json = null;
  try {
    json = text ? JSON.parse(text) : null;
  } catch (_error) {
    json = { raw: text.slice(0, 500) };
  }
  return { ok: response.ok, status: response.status, json };
}

async function makeSession() {
  const suffix = `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  const email = `codex-media-live-${suffix}@local.invalid`;
  const password = `Codex-media-live-${suffix}`;
  const registered = await api("/auth/register", {
    method: "POST",
    body: {
      email,
      password,
      company_name: "Codex Media Live Smoke",
    },
  });
  if (!registered.ok) fail(`register failed: ${registered.status}`, { body: registered.json });

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
  if (!activatedBilling.ok) fail(`billing test activation failed: ${activatedBilling.status}`, { body: activatedBilling.json });

  const created = await api("/stores", {
    token,
    method: "POST",
    body: {
      platform: "ebay",
      store_name: "Codex Media Live Store",
      marketplace: "EBAY_US",
      stage: "store_opened",
      settings: {
        created_from: smokeMarker,
        placeholder_store_name: true,
      },
    },
  });
  if (!created.ok) fail(`store create failed: ${created.status}`, { body: created.json });
  return {
    token,
    email,
    userId: user.user_id || "",
    companyId: company.company_id || user.default_company_id || "",
    store: created.json.store || {},
  };
}

async function createLiveMediaJob(session) {
  const product = "foldable silicone sink drying mat";
  const queued = await api(`/stores/${encodeURIComponent(session.store.store_id)}/provider-jobs/queue`, {
    token: session.token,
    method: "POST",
    body: {
      provider_job_key: "media.asset_generation",
      title: "Codex live image AssetManifest smoke",
      idempotency_key: `codex-media-live-manifest-ui-${Date.now()}`,
      inputs: {
        media_provider: "fal",
        model_provider: "account_model_or_platform_default",
        live_provider_requested: true,
        video_generation_requested: false,
        video_script: "No video generation requested for this smoke; keep video as a later reviewed step.",
        image_count: 1,
        image_sizes: ["1024x1024"],
        scene_types: ["white_background"],
        cost_limit_cents: 100,
        creative_job_spec: {
          job_type: "eBay_listing_asset_package",
          platform: "eBay",
          output_type: "main_product_image",
          output_count: 1,
          image_sizes: ["1024x1024"],
          scene_types: ["white_background"],
          text_rule: "avoid_text_and_unverified_claims",
          fidelity: "fact_checked",
          blocked_claims: ["medical_claim", "brand_authorization_without_proof", "unverified_certification"],
          workflow_source: smokeMarker,
        },
        product_facts: {
          product,
          marketplace: "EBAY_US",
          supplier_facts: {
            material: "silicone",
            logistics: "lightweight non-electric kitchen accessory",
            package_dimensions_cm: { length: 35, width: 8, height: 8 },
          },
          forbidden_claims: ["medical", "certified", "brand_authorized"],
          target_marketplace_rules: {
            platform: "ebay",
            marketplace: "EBAY_US",
            no_auto_publish: true,
          },
        },
      },
      run_mode: "local_worker_now",
    },
  });
  if (!queued.ok) fail(`media provider job queue failed: ${queued.status}`, { body: queued.json });
  const mediaJob = queued.json?.media_asset_job || {};
  const manifest = Array.isArray(mediaJob.asset_manifest) ? mediaJob.asset_manifest : [];
  if (mediaJob.status !== "waiting_review") fail("media job did not reach waiting_review", { mediaJob });
  if (!manifest.length) fail("media job did not return an AssetManifest asset", { mediaJob });
  if (mediaJob.asset_manifest_validation?.status !== "manifest_ready") fail("AssetManifest did not validate", { mediaJob });
  if (mediaJob.live_provider_called !== true) fail("live provider was not called", { mediaJob });
  if (mediaJob.spend_now_allowed !== false) fail("media job should not mark spend_now_allowed true", { mediaJob });
  if (mediaJob.secret_exposed !== false) fail("media job exposed secret marker", { mediaJob });
  return mediaJob;
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

async function launchBrowser() {
  try {
    return await chromium.launch({ channel: browserChannel, headless: true, timeout: 60000 });
  } catch (channelError) {
    return chromium.launch({ headless: true, timeout: 60000 });
  }
}

async function setupContext(browser, session, appHtml) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 960 }, deviceScaleFactor: 1 });
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
  if (localStaticRoot) {
    await context.route(`${base}/app.html**`, (route) =>
      route.fulfill({
        status: 200,
        contentType: "text/html; charset=utf-8",
        headers: { "cache-control": "no-store" },
        body: appHtml,
      }),
    );
    await context.route(`${base}/**`, (route) => {
      const filePath = localStaticPath(route.request().url());
      if (!filePath || !fs.existsSync(filePath)) return route.continue();
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
            display_name: "Codex Media Live Smoke",
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

async function waitForReady(page) {
  await page.waitForFunction(
    () => {
      const root = document.querySelector("#view-media.is-active");
      return Boolean(
        root &&
          root.offsetParent !== null &&
          document.documentElement.classList.contains("app-ready") &&
          !document.querySelector(".auth-shell, .saas-login-modal, [data-auth-view]"),
      );
    },
    null,
    { timeout: 90000 },
  );
}

async function main() {
  stage("make_session");
  const session = await makeSession();
  stage("create_live_media_job");
  const mediaJob = await createLiveMediaJob(session);
  stage("load_app_html");
  const appHtml = localStaticRoot
    ? fs.readFileSync(path.join(localStaticRoot, "app.html"), "utf8")
    : await (await fetch(`${base}/app.html?start=app&view=media&media-live-manifest-smoke=${Date.now()}`, { cache: "no-store" })).text();

  stage("launch_browser");
  const browser = await launchBrowser();
  const context = await setupContext(browser, session, appHtml);
  const page = await context.newPage();
  currentPage = page;
  page.setDefaultTimeout(60000);

  const pageErrors = [];
  const requestFailures = [];
  const badResponses = [];
  const forbiddenRequests = [];
  page.on("pageerror", (error) => pageErrors.push(String(error.message || error).slice(0, 500)));
  page.on("request", (request) => {
    const url = request.url();
    if (
      /signin\.ebay|auth\.ebay|ebay\.com\/signin|\/oauth\/authorize|\/oauth\/callback|checkout\.stripe\.com|paypal\.com|\/billing\/checkout-session|\/billing\/provider-rehearsal|\/ebay\/publish|\/ads\/|\/refund|\/procurement|\/inventory\/write/i.test(
        url,
      )
    ) {
      forbiddenRequests.push(url);
    }
  });
  page.on("requestfailed", (request) => {
    if (!request.url().startsWith(base)) return;
    const failure = request.failure()?.errorText || "";
    if (request.resourceType() === "image" && /ERR_ABORTED/i.test(failure)) return;
    requestFailures.push({ url: request.url(), error: failure, resourceType: request.resourceType() });
  });
  page.on("response", (response) => {
    if (response.url().startsWith(base) && response.status() >= 500) {
      badResponses.push({ url: response.url(), status: response.status() });
    }
  });

  stage("goto_media_view");
  await page.goto(`${base}/app.html?start=app&view=media&media-live-manifest-smoke=${Date.now()}`, {
    waitUntil: "commit",
    timeout: 90000,
  });
  stage("body_loaded");
  await page.waitForSelector("body", { timeout: 30000 });
  await page.waitForLoadState("networkidle", { timeout: 45000 }).catch(() => {});
  stage("app_ready_media_view");
  await waitForReady(page);

  stage("media_job_visible_in_frontend_state");
  await page.waitForFunction(
    (mediaJobId) =>
      (state.saasMediaAssetJobs || []).some(
        (job) =>
          job &&
          job.media_job_id === mediaJobId &&
          job.status === "waiting_review" &&
          Array.isArray(job.asset_manifest) &&
          job.asset_manifest.length > 0,
      ),
    mediaJob.media_job_id,
    { timeout: 90000 },
  );
  stage("media_manifest_card_visible");
  await page.waitForSelector('#view-media [data-asset-preview^="manifest:"]', { timeout: 30000 });
  await page.screenshot({ path: path.join(outDir, "01-media-live-manifest.png"), fullPage: true });

  const ui = await page.evaluate((mediaJobId) => {
    const root = document.querySelector("#view-media.is-active");
    const text = root?.innerText || "";
    const merchantVisibleProviderLeakPattern = /\bFAL\b|fal\.ai|provider key|API key|refresh token/i;
    const cards = Array.from(root?.querySelectorAll('[data-asset-preview^="manifest:"]') || []);
    const imageSources = cards
      .map((card) => card.querySelector("img, video")?.getAttribute("src") || "")
      .filter(Boolean);
    const matchingJob = (state.saasMediaAssetJobs || []).find((job) => job?.media_job_id === mediaJobId) || {};
    return {
      visible: Boolean(root && root.offsetParent !== null),
      manifest_card_count: cards.length,
      image_sources: imageSources.slice(0, 4),
      has_review_copy: /审核|审查|待审核|回写|Listing/.test(text),
      exposes_provider_brand: merchantVisibleProviderLeakPattern.test(text),
      media_job_status: matchingJob.status || "",
      manifest_count: Array.isArray(matchingJob.asset_manifest) ? matchingJob.asset_manifest.length : 0,
      validation_status: matchingJob.asset_manifest_validation?.status || "",
      live_provider_called: matchingJob.live_provider_called,
      spend_now_allowed: matchingJob.spend_now_allowed,
      secret_exposed: matchingJob.secret_exposed,
      preview: text.replace(/\s+/g, " ").trim().slice(0, 320),
    };
  }, mediaJob.media_job_id);

  stage("open_manifest_preview_modal");
  await page.click('#view-media [data-asset-preview^="manifest:"]');
  await page.waitForSelector("#assetModal:not([hidden])", { timeout: 30000 });
  stage("preview_media_loaded");
  await page.waitForFunction(
    () => {
      const image = document.querySelector("#assetModal:not([hidden]) .real-asset-image.primary");
      return Boolean(image && image.complete && image.naturalWidth > 0 && image.naturalHeight > 0);
    },
    null,
    { timeout: 30000 },
  );
  await page.screenshot({ path: path.join(outDir, "02-media-live-manifest-preview.png"), fullPage: true });
  const modal = await page.evaluate(() => {
    const modal = document.querySelector("#assetModal:not([hidden])");
    const text = modal?.innerText || "";
    const primary = modal?.querySelector(".real-asset-image.primary");
    return {
      visible: Boolean(modal),
      has_live_asset_copy: /真实生成|AssetManifest|待审核|Listing/.test(text),
      has_media_preview: Boolean(modal?.querySelector("img, video")),
      primary_image_loaded: Boolean(primary && primary.complete && primary.naturalWidth > 0 && primary.naturalHeight > 0),
      duplicate_secondary_count: modal?.querySelectorAll(".real-asset-image.secondary").length || 0,
      preview: text.replace(/\s+/g, " ").trim().slice(0, 320),
    };
  });

  stage("merchant_review_asset");
  const reviewChecks = page.locator("#assetModal [data-media-review-check]");
  const reviewCheckCount = await reviewChecks.count();
  if (reviewCheckCount < 3) fail("media review checklist is incomplete", { reviewCheckCount });
  for (let index = 0; index < reviewCheckCount; index += 1) {
    await reviewChecks.nth(index).check();
  }
  await page.click("#assetSendConfirm");
  await page.waitForFunction(
    (mediaJobId) =>
      (state.saasMediaAssetJobs || []).some(
        (job) => job?.media_job_id === mediaJobId && job?.status === "approved_for_listing",
      ),
    mediaJob.media_job_id,
    { timeout: 30000 },
  );

  stage("writeback_to_listing");
  await page.locator("#mediaConfirmDraft").scrollIntoViewIfNeeded();
  await page.click("#mediaConfirmDraft");
  await page.waitForSelector("#view-product.is-active", { timeout: 30000 });
  stage("listing_writeback_state_ready");
  await page.waitForFunction(
    () =>
      Boolean(
        state.saasListingComposerDraft?.media_writeback &&
          state.saasListingComposerDraft.media_writeback.status === "merchant_reviewed_for_listing_draft" &&
          (state.saasListingComposerDraft.media_writeback.image_urls || []).length > 0,
      ),
    null,
    { timeout: 30000 },
  );
  await page.screenshot({ path: path.join(outDir, "03-media-writeback-listing.png"), fullPage: true });
  const listingWriteback = await page.evaluate(() => {
    const draft = state.saasListingComposerDraft || {};
    const writeback = draft.media_writeback || {};
    const root = document.querySelector("#view-product.is-active");
    const text = root?.innerText || "";
    const merchantVisibleProviderLeakPattern = /\bFAL\b|fal\.ai|provider key|API key|refresh token/i;
    const coverage = saasListingEbayFieldCoverage(draft, saasMerchantWorkbenchContext());
    const assetGroup = (coverage.groups || []).find((group) => group.key === "assets") || {};
    const publishValues = saasPublishIntakePrefillValues();
    return {
      visible: Boolean(root && root.offsetParent !== null),
      has_panel: Boolean(root?.querySelector('[data-listing-media-writeback="media_asset_manifest_writeback_v1"]')),
      status: writeback.status || "",
      asset_count: writeback.asset_count || 0,
      image_url_count: Array.isArray(writeback.image_urls) ? writeback.image_urls.length : 0,
      field_images_mentions_manifest: /素材清单/.test(String(draft.fields?.images || "")),
      field_images_hides_raw_provider_url: !/https?:\/\/[^\s,，；;]*fal\./i.test(String(draft.fields?.images || "")),
      publish_prefill_has_url: /https?:\/\//i.test(String(draft.publish_prefill?.image_urls || "")),
      publish_intake_has_url: /https?:\/\//i.test(String(publishValues.image_urls || "")),
      asset_group_done: assetGroup.done || 0,
      asset_group_total: assetGroup.total || 0,
      asset_group_tone: assetGroup.tone || "",
      rights_confirmed_for_draft: assetGroup.tone === "green" && (assetGroup.done || 0) === (assetGroup.total || 0),
      triggers_real_platform_write: writeback.triggers_real_platform_write,
      confirmation_center_required: writeback.confirmation_center_required,
      spend_now_allowed: writeback.spend_now_allowed,
      secret_exposed: writeback.secret_exposed,
      exposes_provider_brand: merchantVisibleProviderLeakPattern.test(text),
      preview: text.replace(/\s+/g, " ").trim().slice(0, 360),
    };
  });

  stage("fetch_backend_verification");
  const [healthApi, readinessApi, mediaJobsApi] = await Promise.all([
    api("/health"),
    api("/readiness/product-saas"),
    api(`/stores/${encodeURIComponent(session.store.store_id)}/media-asset-jobs?limit=8`, { token: session.token }),
  ]);
  const backendJobs = Array.isArray(mediaJobsApi.json?.media_asset_jobs) ? mediaJobsApi.json.media_asset_jobs : [];
  const backendJob = backendJobs.find((job) => job.media_job_id === mediaJob.media_job_id) || backendJobs[0] || {};

  const checks = {
    live_media_job_created:
      mediaJob.status === "waiting_review" &&
      Array.isArray(mediaJob.asset_manifest) &&
      mediaJob.asset_manifest.length === 1 &&
      mediaJob.asset_manifest_validation?.status === "manifest_ready" &&
      mediaJob.live_provider_called === true &&
      mediaJob.spend_now_allowed === false &&
      mediaJob.secret_exposed === false,
    backend_media_job_listed:
      mediaJobsApi.ok &&
      backendJob.media_job_id === mediaJob.media_job_id &&
      backendJob.status === "approved_for_listing" &&
      Array.isArray(backendJob.asset_manifest) &&
      backendJob.asset_manifest.length === 1,
    media_ui_shows_manifest_assets:
      ui.visible &&
      ui.manifest_card_count >= 1 &&
      ui.manifest_count >= 1 &&
      ui.validation_status === "manifest_ready" &&
      ui.live_provider_called === true,
    media_ui_keeps_review_gate:
      ui.has_review_copy && ui.spend_now_allowed === false && ui.secret_exposed === false && !ui.exposes_provider_brand,
    preview_modal_opens_live_asset:
      modal.visible && modal.has_live_asset_copy && modal.has_media_preview && modal.primary_image_loaded && modal.duplicate_secondary_count === 0,
    media_writeback_updates_listing_draft:
      listingWriteback.visible &&
      listingWriteback.has_panel &&
      listingWriteback.status === "merchant_reviewed_for_listing_draft" &&
      listingWriteback.asset_count >= 1 &&
      listingWriteback.image_url_count >= 1 &&
      listingWriteback.field_images_mentions_manifest &&
      listingWriteback.field_images_hides_raw_provider_url &&
      listingWriteback.publish_prefill_has_url &&
      listingWriteback.publish_intake_has_url,
    media_writeback_keeps_publish_review_gate:
      listingWriteback.asset_group_done >= 1 &&
      listingWriteback.asset_group_tone === "green" &&
      listingWriteback.rights_confirmed_for_draft &&
      listingWriteback.triggers_real_platform_write === false &&
      listingWriteback.confirmation_center_required === true &&
      listingWriteback.spend_now_allowed === false &&
      listingWriteback.secret_exposed === false &&
      !listingWriteback.exposes_provider_brand,
    no_real_platform_writes_triggered: healthApi.json?.real_platform_writes_enabled === false,
    public_gate_still_not_production_ready:
      readinessApi.ok &&
      readinessApi.json?.readiness?.production_ready === false &&
      readinessApi.json?.readiness?.can_accept_real_customers === false,
    no_forbidden_requests: forbiddenRequests.length === 0,
    no_runtime_errors: pageErrors.length === 0 && requestFailures.length === 0 && badResponses.length === 0,
  };

  const result = {
    ok: Object.values(checks).every(Boolean),
    marker: smokeMarker,
    timestamp: new Date().toISOString(),
    base,
    local_static_root_used: Boolean(localStaticRoot),
    outDir,
    session: {
      email_masked: session.email.replace(/^(.{2}).*(@.*)$/, "$1***$2"),
      store_id: session.store.store_id,
    },
    media_job: {
      media_job_id: mediaJob.media_job_id,
      status: mediaJob.status,
      manifest_count: Array.isArray(mediaJob.asset_manifest) ? mediaJob.asset_manifest.length : 0,
      validation_status: mediaJob.asset_manifest_validation?.status || "",
      live_provider_called: mediaJob.live_provider_called,
      spend_now_allowed: mediaJob.spend_now_allowed,
      secret_exposed: mediaJob.secret_exposed,
      asset_host: (() => {
        try {
          return new URL(String(mediaJob.asset_manifest?.[0]?.url_or_file_path || mediaJob.asset_manifest?.[0]?.url || "")).host;
        } catch (_error) {
          return "";
        }
      })(),
    },
    checks,
    ui,
    modal,
    listingWriteback,
    api: {
      real_platform_writes_enabled: healthApi.json?.real_platform_writes_enabled,
      readiness_status: readinessApi.status,
      production_ready: readinessApi.json?.readiness?.production_ready,
      can_accept_real_customers: readinessApi.json?.readiness?.can_accept_real_customers,
    },
    pageErrors,
    requestFailures,
    badResponses,
    forbiddenRequests,
  };
  fs.writeFileSync(path.join(outDir, "result.json"), JSON.stringify(result, null, 2));
  await browser.close();
  currentPage = null;

  if (!result.ok) {
    console.error(JSON.stringify(result, null, 2));
    fail("media live manifest UI smoke failed", { outDir });
  }
  console.log(JSON.stringify(result, null, 2));
}

main().catch(async (error) => {
  let pageState = {};
  if (currentPage && !currentPage.isClosed()) {
    try {
      await currentPage.screenshot({ path: path.join(outDir, "failure.png"), fullPage: true });
    } catch (_screenshotError) {}
    try {
      pageState = await currentPage.evaluate(() => {
        const activeView = Array.from(document.querySelectorAll(".view.is-active, [id^='view-'].is-active"))
          .map((node) => node.id || node.className)
          .filter(Boolean);
        return {
          url: location.href,
          ready: document.documentElement.classList.contains("app-ready"),
          active_view: activeView.slice(0, 5),
          has_auth_shell: Boolean(document.querySelector(".auth-shell, .saas-login-modal, [data-auth-view]")),
          media_job_count: Array.isArray(window.state?.saasMediaAssetJobs) ? window.state.saasMediaAssetJobs.length : null,
          media_job_statuses: Array.isArray(window.state?.saasMediaAssetJobs)
            ? window.state.saasMediaAssetJobs.slice(0, 5).map((job) => ({
                media_job_id: job?.media_job_id || "",
                status: job?.status || "",
                manifest_count: Array.isArray(job?.asset_manifest) ? job.asset_manifest.length : 0,
              }))
            : [],
          text_preview: (document.body?.innerText || "").replace(/\s+/g, " ").trim().slice(0, 500),
        };
      });
      fs.writeFileSync(path.join(outDir, "failure-state.json"), JSON.stringify(pageState, null, 2));
    } catch (_stateError) {}
  }
  console.error(
    JSON.stringify(
      {
        ok: false,
        marker: smokeMarker,
        stage: currentStage,
        message: error.message,
        details: error.details || {},
        pageState,
        outDir,
      },
      null,
      2,
    ),
  );
  process.exit(1);
});
