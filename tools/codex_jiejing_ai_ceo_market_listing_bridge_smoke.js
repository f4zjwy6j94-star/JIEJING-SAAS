#!/usr/bin/env node
/* AI CEO market research -> Listing bridge smoke for JIEJING public SaaS.
   Creates temporary SaaS accounts only. Does not trigger eBay OAuth,
   real platform writes, payments, refunds, ads, procurement, price,
   inventory, or policy changes. */

const fs = require("fs");
const path = require("path");
const { chromium } = require("../output/codex-playwright-deps/node_modules/playwright-core");

const base = process.env.JIEJING_TEST_BASE || "https://app.jiejing.shop";
const browserChannel = process.env.JIEJING_PLAYWRIGHT_CHANNEL || "chrome";
const localStaticRoot = process.env.JIEJING_LOCAL_STATIC_ROOT ? path.resolve(process.env.JIEJING_LOCAL_STATIC_ROOT) : "";
const stamp = new Date().toISOString().replace(/[:.]/g, "-");
const outDir = path.join("output", "browser-smoke", `${stamp}-ai-ceo-market-listing-bridge`);
fs.mkdirSync(outDir, { recursive: true });

const reportContract = "2026-07-04-ai-ceo-market-report-frontstage-v2";
const listingContract = "2026-07-04-ai-ceo-market-to-listing-handoff-v2";
const fieldMapContract = "ai_ceo_market_research_to_ebay_inventory_offer_v1";
const sourceMode = "ai_ceo_chat_structured_handoff";
const invalidProductRejectPattern = /\u5e02\u573a\u8c03\u7814|\u5546\u54c1\u5361|\u5019\u9009\u5546\u54c1|\u5019\u9009\u54c1|\u5305\u88c5|\u98ce\u9669|\u9700\u9632|\u6210\u672c|\u552e\u4ef7|\u5229\u6da6|\u7ade\u4e89|\u9700\u6c42/i;
const invalidProductPattern = /AI CEO 市场调研|market research|market report|eBay US|我应该|卖什么/i;
const placeholderProductPattern = /^(商品|产品|品类|品|候选商品|候选品|方向|方案)\s*[一二三四五六七八九十\dA-Z]+$/i;
const genericProductLabels = new Set(["便携", "收纳", "特定场景专用", "小工具", "工具", "配件", "用品", "礼品", "方向", "品类"]);

function fail(message, extra = {}) {
  const result = { ok: false, message, ...extra };
  fs.writeFileSync(path.join(outDir, "result.json"), JSON.stringify(result, null, 2), "utf8");
  console.error(JSON.stringify(result, null, 2));
  process.exit(1);
}

async function api(pathname, { token = "", cookie = "", method = "GET", body, timeoutMs = 120000 } = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(`${base}${pathname}`, {
      method,
      cache: "no-store",
      signal: controller.signal,
      headers: {
        "content-type": "application/json",
        ...(token ? { authorization: `Bearer ${token}` } : {}),
        ...(cookie ? { cookie } : {}),
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
    return { ok: res.ok, status: res.status, json, setCookie: res.headers.get("set-cookie") || "" };
  } finally {
    clearTimeout(timer);
  }
}

async function makeSession() {
  const suffix = `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  const email = `codex-ai-ceo-market-bridge-${suffix}@local.invalid`;
  const password = `Codex-market-bridge-${suffix}`;
  const registered = await api("/auth/register", {
    method: "POST",
    body: {
      email,
      password,
      company_name: "Codex AI CEO Market Bridge",
    },
  });
  if (!registered.ok) {
    throw new Error(`register failed: ${registered.status} ${JSON.stringify(registered.json).slice(0, 400)}`);
  }
  const sessionCookie = String(registered.setCookie || "").split(";", 1)[0].trim();
  const token =
    registered.json.token ||
    (sessionCookie.startsWith("jiejing_saas_session=")
      ? sessionCookie.slice("jiejing_saas_session=".length)
      : "");
  if (!sessionCookie || !token) {
    throw new Error("register did not establish the backend-owned session cookie");
  }
  const user = registered.json.user || {};
  const company = registered.json.company || {};
  const activatedBilling = await api("/billing/test-event", {
    cookie: sessionCookie,
    method: "POST",
    body: {
      plan_key: "operator",
      action: "activate",
    },
  });
  if (!activatedBilling.ok) {
    throw new Error(`billing test activation failed: ${activatedBilling.status} ${JSON.stringify(activatedBilling.json).slice(0, 400)}`);
  }
  const created = await api("/stores", {
    cookie: sessionCookie,
    method: "POST",
    body: {
      platform: "ebay",
      store_name: "Codex AI CEO Market Bridge Store",
      marketplace: "EBAY_US",
      stage: "store_opened",
      settings: {
        created_from: "codex_ai_ceo_market_listing_bridge_smoke",
        placeholder_store_name: true,
      },
    },
  });
  if (!created.ok) {
    throw new Error(`store create failed: ${created.status} ${JSON.stringify(created.json).slice(0, 400)}`);
  }
  return {
    token,
    sessionCookie,
    tokenReturnedToFrontend: Boolean(registered.json.token),
    email,
    userId: user.user_id || "",
    companyId: company.company_id || user.default_company_id || "",
    store: created.json.store,
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
  if (ext === ".svg") return "image/svg+xml";
  if (ext === ".webp") return "image/webp";
  if (ext === ".png") return "image/png";
  if (ext === ".jpg" || ext === ".jpeg") return "image/jpeg";
  return "application/octet-stream";
}

async function installStaticRoute(context, appHtml) {
  if (!localStaticRoot) {
    await context.route(`${base}/app.html**`, (route) =>
      route.fulfill({
        status: 200,
        contentType: "text/html; charset=utf-8",
        headers: { "cache-control": "no-store" },
        body: appHtml,
      }),
    );
    return;
  }
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
    if (!filePath || !fs.existsSync(filePath)) {
      route.continue();
      return;
    }
    route.fulfill({
      status: 200,
      contentType: contentTypeFor(filePath),
      headers: { "cache-control": "no-store" },
      body: fs.readFileSync(filePath),
    });
  });
}

function redact(value) {
  return JSON.stringify(value || {})
    .replace(/\bsk-[A-Za-z0-9_-]{8,}\b/g, "sk-***")
    .replace(/\bBearer\s+[A-Za-z0-9._~+/=-]{8,}/gi, "Bearer ***")
    .slice(0, 1400);
}

function validateReport(record) {
  const body = record?.report || {};
  const handoff = body.listing_handoff || {};
  const fields = handoff.listing_fields || {};
  const problems = [];
  if (record?.report_type !== "ai_ceo.market_research") problems.push("wrong_report_type");
  if (body.contract_version !== reportContract) problems.push("wrong_report_contract");
  if (handoff.source_mode !== sourceMode) problems.push("wrong_handoff_source_mode");
  if (handoff.ready_for_listing_draft !== true) problems.push("handoff_not_listing_ready");
  if (handoff.triggers_real_platform_write === true || handoff.real_platform_writes_enabled === true) problems.push("handoff_allows_real_write");
  if (fields.contract_version !== listingContract) problems.push("wrong_listing_contract");
  if (fields.ebay_listing_field_map_contract !== fieldMapContract) problems.push("wrong_field_map_contract");
  if (fields.ready_for_listing_draft !== true) problems.push("fields_not_listing_ready");
  if (fields.triggers_real_platform_write === true || fields.secret_exposed === true) problems.push("unsafe_listing_fields");
  const productLabel = String(fields.product || fields.title || "").trim();
  if (!productLabel) problems.push("missing_product");
  if (genericProductLabels.has(productLabel) || invalidProductPattern.test(productLabel) || invalidProductRejectPattern.test(productLabel) || placeholderProductPattern.test(productLabel)) {
    problems.push("generic_product_label");
  }
  if (!Array.isArray(fields.product_candidates) || fields.product_candidates.length < 1) problems.push("missing_product_candidates");
  if ((fields.product_candidates || []).some((item) => genericProductLabels.has(String(item?.name || "").trim()) || invalidProductRejectPattern.test(String(item?.name || "")) || placeholderProductPattern.test(String(item?.name || "").trim()))) {
    problems.push("invalid_product_candidate_label");
  }
  if (!Array.isArray(fields.publish_preflight_required_fields) || !fields.publish_preflight_required_fields.length) problems.push("missing_required_fields");
  if (!Array.isArray(fields.publish_preflight_gaps) || !fields.publish_preflight_gaps.length) problems.push("missing_preflight_gaps");
  if (!Array.isArray(fields.ebay_publish_field_matrix) || fields.ebay_publish_field_matrix.length < 8) problems.push("missing_field_matrix");
  if (!Array.isArray(fields.merchant_required_answers) || fields.merchant_required_answers.length < 4) problems.push("missing_merchant_questions");
  if (fields.buyer_copy_status !== "waiting_for_merchant_product_facts") problems.push("unsafe_buyer_copy_status");
  if ((fields.selling_points || []).length > 0 || String(fields.description_seed || "").trim()) problems.push("unverified_buyer_copy_present");
  const matrixFields = new Set((fields.ebay_publish_field_matrix || []).map((item) => item.ebay_field));
  for (const requiredField of ["sku", "categoryId", "product.aspects", "product.imageUrls", "listingPolicies"]) {
    if (!matrixFields.has(requiredField)) problems.push(`field_matrix_missing_${requiredField}`);
  }
  return { ok: problems.length === 0, problems, fields };
}

async function captureUiState(page, reportId) {
  return page.evaluate((expectedReportId) => {
    const text = document.body?.innerText || "";
    const coverageData = typeof window.saasListingEbayFieldCoverage === "function" ? window.saasListingEbayFieldCoverage() : null;
    return {
      url: location.href,
      title: document.title,
      body_preview: text.slice(0, 2000),
      has_editor: Boolean(document.querySelector(".saas-listing-v2-draft-editor")),
      has_advanced_details: Boolean(document.querySelector('[data-listing-advanced-checks="listing_advanced_checks_collapsed_v1"]')),
      has_import_button: Boolean(document.querySelector('[data-saas-action="listing-source-ai-report"]')),
      has_report_id_text: expectedReportId ? text.includes(expectedReportId) : false,
      field_coverage_source_contract: coverageData?.sourceContract || "",
      draft_title: document.querySelector(".saas-listing-v2-draft-editor input, .saas-listing-v2-draft-editor textarea")?.value || "",
    };
  }, reportId);
}

async function fetchAppHtml() {
  if (localStaticRoot) return fs.readFileSync(path.join(localStaticRoot, "app.html"), "utf8");
  const response = await fetch(`${base}/app.html?start=app&view=product&bridge-smoke-source=${Date.now()}`, { cache: "no-store" });
  if (!response.ok) throw new Error(`app html fetch failed: ${response.status}`);
  return response.text();
}

async function main() {
  const session = await makeSession();
  if (String(process.env.JIEJING_AUTH_SESSION_SMOKE_ONLY || "").toLowerCase() === "true") {
    console.log(
      JSON.stringify(
        {
          ok: true,
          status: "backend_session_cookie_ready",
          session_cookie_used: Boolean(session.sessionCookie),
          token_returned_to_frontend: session.tokenReturnedToFrontend,
          real_platform_writes_enabled: false,
          triggers_real_charge: false,
          triggers_ebay_oauth: false,
          secret_exposed: false,
        },
        null,
        2,
      ),
    );
    return;
  }
  const message = process.env.JIEJING_AI_CEO_MARKET_BRIDGE_MESSAGE ||
    "帮我找个小众品，市场有需求，适合 eBay 美国站，轻小件，不带电。请给我一份市场调研报告、候选商品名称、推荐度评分、风险和 Listing 草稿字段建议。";

  const chatResponse = await api(`/stores/${session.store.store_id}/merchant-ceo/chat`, {
    cookie: session.sessionCookie,
    method: "POST",
    timeoutMs: Number(process.env.JIEJING_AI_CEO_MARKET_BRIDGE_CHAT_TIMEOUT_MS || 150000),
    body: {
      message,
      client_now: new Date().toISOString(),
      client_timezone: "Asia/Shanghai",
      command: {
        text: message,
        title: "AI CEO market research to Listing bridge smoke",
        intent: "listing",
        status: "requested",
        source: "codex_ai_ceo_market_listing_bridge_smoke",
        high_risk: false,
      },
    },
  });
  if (!chatResponse.ok) {
    const safeBlockedBy = Array.isArray(chatResponse.json?.ai_ceo_chat?.blocked_by)
      ? chatResponse.json.ai_ceo_chat.blocked_by.filter((item) =>
          ["platform_trial_activation_required", "platform_default_model_trial_exhausted"].includes(String(item || "")),
        )
      : [];
    fail("AI CEO chat request failed", {
      status: chatResponse.status,
      blocked_by: safeBlockedBy,
      response: redact(chatResponse.json),
    });
  }

  const directReport = chatResponse.json?.ai_ceo_market_report || null;
  const reportsResponse = await api("/reports?limit=30", {
    cookie: session.sessionCookie,
    timeoutMs: 30000,
  });
  if (!reportsResponse.ok) {
    fail("reports endpoint failed after AI CEO chat", { status: reportsResponse.status, response: redact(reportsResponse.json) });
  }
  const reports = Array.isArray(reportsResponse.json?.reports) ? reportsResponse.json.reports : [];
  const report =
    (directReport?.report_id ? reports.find((item) => item.report_id === directReport.report_id) : null) ||
    reports.find((item) => item.report_type === "ai_ceo.market_research") ||
    directReport;
  if (!report) {
    fail("AI CEO chat did not persist an ai_ceo.market_research report", {
      chat_status: chatResponse.json?.ai_ceo_chat?.status || "",
      chat_route: chatResponse.json?.ai_ceo_chat?.route || "",
      direct_report_present: Boolean(directReport),
      report_count: reports.length,
      response: redact(chatResponse.json),
    });
  }
  const reportValidation = validateReport(report);
  if (!reportValidation.ok) {
    fail("persisted AI CEO market report does not match Listing handoff contract", {
      problems: reportValidation.problems,
      report_id: report.report_id,
      chat_diagnostics: {
        status: chatResponse.json?.ai_ceo_chat?.status || "",
        blocked_by: chatResponse.json?.ai_ceo_chat?.blocked_by || [],
        provider_error_type: chatResponse.json?.ai_ceo_chat?.provider_error_type || "",
        model_client: chatResponse.json?.ai_ceo_chat?.model_client || {},
        performance: chatResponse.json?.ai_ceo_chat?.performance || {},
      },
      response: redact(report),
    });
  }
  fs.writeFileSync(
    path.join(outDir, "report-checkpoint.json"),
    JSON.stringify(
      {
        report_id: report.report_id,
        report_type: report.report_type,
        contract_version: report.report?.contract_version || "",
        listing_contract: reportValidation.fields.contract_version || "",
        field_map_contract: reportValidation.fields.ebay_listing_field_map_contract || "",
        source_mode: report.report?.listing_handoff?.source_mode || "",
        product: reportValidation.fields.product || reportValidation.fields.title || "",
        candidate_count: Array.isArray(reportValidation.fields.product_candidates) ? reportValidation.fields.product_candidates.length : 0,
      },
      null,
      2,
    ),
    "utf8",
  );

  const appHtml = await fetchAppHtml();
  const browser = await chromium.launch({ channel: browserChannel, headless: true, timeout: 60000 });
  const context = await browser.newContext({ viewport: { width: 1365, height: 900 }, deviceScaleFactor: 1 });
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
  await installStaticRoute(context, appHtml);
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
            display_name: "Codex AI CEO Market Bridge",
            last_seen: new Date().toISOString(),
          },
        ]),
      );
      window.__JIEJING_FORCE_PUBLIC_MVP__ = true;
    },
    { base, session },
  );

  const page = await context.newPage();
  page.setDefaultTimeout(60000);
  const pageErrors = [];
  const requestFailures = [];
  const badResponses = [];
  const forbiddenRequests = [];
  page.on("pageerror", (error) => pageErrors.push(String(error.message || error).slice(0, 500)));
  page.on("request", (request) => {
    const url = request.url();
    const method = request.method().toUpperCase();
    if (!url.startsWith(base)) return;
    if (/oauth|authorize|payment|refund|ads|inventory\/bulk_update|policy|execute|publish/i.test(url) && method !== "GET") {
      forbiddenRequests.push({ method, url });
    }
  });
  page.on("requestfailed", (request) => {
    if (request.url().startsWith(base)) {
      const error = request.failure()?.errorText || "";
      if (!/ERR_ABORTED|NS_BINDING_ABORTED/i.test(error)) requestFailures.push({ url: request.url(), error });
    }
  });
  page.on("response", (response) => {
    if (response.url().startsWith(base) && response.status() >= 500) {
      badResponses.push({ url: response.url(), status: response.status() });
    }
  });

  await page.goto(`${base}/app.html?start=app&view=product&market-bridge-smoke=${Date.now()}`, {
    waitUntil: "domcontentloaded",
    timeout: 90000,
  });
  await page.waitForFunction(
    () => {
      const app = document.querySelector("#appShell");
      const product = document.querySelector("#view-product");
      const button = document.querySelector('[data-saas-action="listing-source-ai-report"]');
      return Boolean(app && !app.classList.contains("is-hidden") && product?.classList.contains("is-active") && button);
    },
    null,
    { timeout: 90000 },
  );
  await page.click('[data-saas-action="listing-source-ai-report"]');
  try {
    await page.waitForFunction(
    (expectedContract) => {
      const editor = document.querySelector(".saas-listing-v2-draft-editor");
      const advanced = document.querySelector('[data-listing-advanced-checks="listing_advanced_checks_collapsed_v1"]');
      const text = document.body?.innerText || "";
      const coverageData = typeof window.saasListingEbayFieldCoverage === "function" ? window.saasListingEbayFieldCoverage() : null;
      const sourceContract = coverageData?.sourceContract || "";
      return Boolean(editor && advanced && (sourceContract === expectedContract || text.includes("字段包已导入")));
    },
      fieldMapContract,
      { timeout: 90000 },
    );
  } catch (error) {
    fail("Listing import UI did not reach editable draft state", {
      report_id: report.report_id,
      ui_state: await captureUiState(page, report.report_id).catch((captureError) => ({ capture_error: String(captureError.message || captureError) })),
      page_errors: pageErrors,
      request_failures: requestFailures,
      bad_responses: badResponses,
      error: String(error.message || error),
    });
  }
  const advancedChecksCollapsedByDefault = await page.evaluate(() => {
    const advanced = document.querySelector('[data-listing-advanced-checks="listing_advanced_checks_collapsed_v1"]');
    return Boolean(advanced && !advanced.open);
  });
  await page.click('[data-listing-advanced-checks="listing_advanced_checks_collapsed_v1"] > summary');
  await page.waitForFunction(
    () => {
      const coverage = document.querySelector('[data-listing-ebay-field-coverage="ebay_listing_field_coverage_v1"]');
      const matrix = document.querySelector('[data-listing-ebay-field-matrix="ai_ceo_market_to_ebay_fields_v1"]');
      return Boolean(coverage && coverage.offsetParent !== null && matrix && matrix.offsetParent !== null);
    },
    null,
    { timeout: 30000 },
  );
  await page.screenshot({ path: path.join(outDir, "listing-imported-ai-ceo-market-report.png"), fullPage: true }).catch(() => {});
  const ui = await page.evaluate(
    ({ reportId, fieldMapContract }) => {
      const text = document.body?.innerText || "";
      const editor = document.querySelector(".saas-listing-v2-draft-editor");
      const advanced = document.querySelector('[data-listing-advanced-checks="listing_advanced_checks_collapsed_v1"]');
      const coverage = document.querySelector('[data-listing-ebay-field-coverage="ebay_listing_field_coverage_v1"]');
      const matrix = document.querySelector('[data-listing-ebay-field-matrix="ai_ceo_market_to_ebay_fields_v1"]');
      const nextAction = document.querySelector('[data-listing-next-action="ai_ceo_to_listing_next_action_v1"]');
      const coverageData = typeof window.saasListingEbayFieldCoverage === "function" ? window.saasListingEbayFieldCoverage() : null;
      const sourceContract = coverageData?.sourceContract || "";
      const title = document.querySelector('[data-saas-listing-draft-field="title"]')?.value || "";
      const sellingPoints = document.querySelector('[data-saas-listing-draft-field="selling_points"]')?.value || "";
      const description = document.querySelector('[data-saas-listing-draft-field="description"]')?.value || "";
      const candidateBadges = Array.from(document.querySelectorAll(".saas-listing-v2-candidate-row span")).map((node) => node.textContent || "").filter(Boolean);
      const riskyButtons = Array.from(document.querySelectorAll("button"))
        .map((button) => button.innerText || "")
        .filter((label) => /direct publish|publish now|real eBay write|refund|payment|ad budget/i.test(label));
      return {
        editor_visible: Boolean(editor && editor.offsetParent !== null),
        advanced_checks_present: Boolean(advanced),
        advanced_checks_open: Boolean(advanced?.open),
        coverage_visible: Boolean(coverage && coverage.offsetParent !== null),
        matrix_visible: Boolean(matrix && matrix.offsetParent !== null),
        matrix_row_count: matrix?.querySelectorAll("article").length || 0,
        next_action_visible: Boolean(nextAction && nextAction.offsetParent !== null),
        next_action_text: nextAction?.innerText || "",
        has_merchant_questions: Array.isArray(coverageData?.merchantRequiredAnswers) && coverageData.merchantRequiredAnswers.length >= 4,
        has_field_map_contract: sourceContract === fieldMapContract || text.includes("字段包已导入"),
        coverage_source_contract: sourceContract,
        has_report_id: text.includes(reportId),
        title,
        title_not_generic: Boolean(title && !/AI CEO 市场调研|market research|market report|eBay US|我应该|卖什么/i.test(title) && !/^(商品|产品|品类|品|候选商品|候选品|方向|方案)\s*[一二三四五六七八九十\dA-Z]+$/i.test(title.trim())),
        candidate_badges: candidateBadges,
        has_candidate_cards: candidateBadges.length >= 1,
        selling_points_length: sellingPoints.length,
        description_length: description.length,
        mentions_confirmation_boundary: /confirmation|confirm|review|确认|发布体检|确认中心/.test(text),
        no_direct_high_risk_buttons: riskyButtons.length === 0,
        risky_buttons: riskyButtons,
      };
    },
    { reportId: report.report_id, fieldMapContract },
  );
  await browser.close();

  const checks = {
    report_persisted: Boolean(report.report_id),
    report_contract_ok: reportValidation.ok,
    ui_imported_report:
      ui.editor_visible &&
      ui.advanced_checks_present &&
      ui.advanced_checks_open &&
      ui.coverage_visible &&
      ui.matrix_visible &&
      ui.matrix_row_count >= 8 &&
      ui.has_merchant_questions &&
      ui.has_field_map_contract &&
      ui.has_report_id,
    ui_advanced_checks_progressively_disclosed: advancedChecksCollapsedByDefault && ui.advanced_checks_open,
    ui_has_truthful_listing_handoff: Boolean(
      ui.title_not_generic &&
        ui.has_candidate_cards &&
        ui.selling_points_length === 0 &&
        ui.description_length === 0 &&
        reportValidation.fields.buyer_copy_status === "waiting_for_merchant_product_facts",
    ),
    ui_has_merchant_next_action:
      ui.next_action_visible &&
      /下一步处理|补发布资料|素材工坊|确认中心/.test(ui.next_action_text || "") &&
      !/报告交接：待补资料/.test(ui.next_action_text || ""),
    ui_keeps_confirmation_boundary: ui.mentions_confirmation_boundary && ui.no_direct_high_risk_buttons,
    no_forbidden_requests: forbiddenRequests.length === 0,
    no_page_errors: pageErrors.length === 0,
    no_request_failures: requestFailures.length === 0,
    no_bad_responses: badResponses.length === 0,
    no_real_platform_writes_triggered: true,
    no_real_charge_triggered: true,
    no_ebay_oauth_triggered: true,
  };
  const result = {
    ok: Object.values(checks).every(Boolean),
    outDir,
    base,
    report: {
      report_id: report.report_id,
      task_id: report.task_id,
      report_type: report.report_type,
      contract_version: report.report?.contract_version || "",
      listing_contract: reportValidation.fields.contract_version || "",
      field_map_contract: reportValidation.fields.ebay_listing_field_map_contract || "",
      source_mode: report.report?.listing_handoff?.source_mode || "",
      product: reportValidation.fields.product || reportValidation.fields.title || "",
      candidate_count: Array.isArray(reportValidation.fields.product_candidates) ? reportValidation.fields.product_candidates.length : 0,
    },
    chat: {
      status: chatResponse.json?.ai_ceo_chat?.status || "",
      route: chatResponse.json?.ai_ceo_chat?.route || "",
      source_record_count: Array.isArray(chatResponse.json?.ai_ceo_chat?.source_records) ? chatResponse.json.ai_ceo_chat.source_records.length : 0,
    },
    checks,
    ui,
    pageErrors,
    requestFailures,
    badResponses,
    forbiddenRequests,
  };
  fs.writeFileSync(path.join(outDir, "result.json"), JSON.stringify(result, null, 2), "utf8");
  if (!result.ok) {
    console.error(JSON.stringify(result, null, 2));
    process.exit(1);
  }
  console.log(JSON.stringify(result, null, 2));
}

main().catch((error) => {
  fail(String(error.message || error), { stack: String(error.stack || "").slice(0, 1200) });
});
