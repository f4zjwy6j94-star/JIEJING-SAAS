#!/usr/bin/env node
/* ASCII-only staging UI smoke for Jiejing's seven merchant modules. */

const fs = require("fs");
const path = require("path");
const { chromium } = require("../output/codex-playwright-deps/node_modules/playwright-core");

const base = process.env.JIEJING_TEST_BASE || "https://individually-buffalo-prescribed-blocking.trycloudflare.com";
const browserChannel = process.env.JIEJING_PLAYWRIGHT_CHANNEL || "chrome";
const localStaticRoot = process.env.JIEJING_LOCAL_STATIC_ROOT ? path.resolve(process.env.JIEJING_LOCAL_STATIC_ROOT) : "";
const viewportWidth = Number(process.env.JIEJING_SMOKE_VIEWPORT_WIDTH || 1440);
const viewportHeight = Number(process.env.JIEJING_SMOKE_VIEWPORT_HEIGHT || 920);
const stamp = new Date().toISOString().replace(/[:.]/g, "-");
const outDir = path.join("output", "browser-smoke", `${stamp}-all-modules-clean-ui`);
fs.mkdirSync(outDir, { recursive: true });

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
  const email = `codex-ui-${suffix}@local.invalid`;
  const password = `Codex-ui-${suffix}`;
  const registered = await api("/auth/register", {
    method: "POST",
    body: {
      email,
      password,
      company_name: "Codex UI Smoke",
    },
  });
  if (!registered.ok) {
    throw new Error(`register failed: ${registered.status} ${JSON.stringify(registered.json).slice(0, 300)}`);
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
    throw new Error(`billing test activation failed before store create: ${activatedBilling.status} ${JSON.stringify(activatedBilling.json).slice(0, 300)}`);
  }
  const created = await api("/stores", {
    token,
    method: "POST",
    body: {
      platform: "ebay",
      store_name: "Codex UI Smoke Store",
      marketplace: "EBAY_US",
      stage: "store_opened",
      settings: {
        created_from: "codex_browser_smoke",
        placeholder_store_name: true,
      },
    },
  });
  if (!created.ok) {
    throw new Error(`store create failed: ${created.status} ${JSON.stringify(created.json).slice(0, 300)}`);
  }
  return {
    token,
    email,
    userId: user.user_id || "",
    companyId: company.company_id || user.default_company_id || "",
    store: created.json.store,
  };
}

async function gotoWithRetry(page, url, attempts = 3) {
  let lastError = null;
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    try {
      await page.goto(url, { waitUntil: "commit", timeout: 90000 });
      await page.waitForSelector("body", { timeout: 30000 });
      return;
    } catch (error) {
      lastError = error;
      await page.waitForTimeout(2000 * attempt);
    }
  }
  throw lastError;
}

async function waitForWorkbenchReady(page, activeViewId = "") {
  await page.waitForFunction(
    (selector) => {
      const root = selector ? document.querySelector(selector) : document.body;
      if (!root) return false;
      if (selector && root.offsetParent === null) return false;
      return true;
    },
    activeViewId ? `#${activeViewId}` : "",
    { timeout: 60000 },
  );
  await page.waitForTimeout(500);
}

async function waitForVisibleCeoComposer(page) {
  await page.waitForFunction(
    () => {
      const root = document.querySelector("#view-cockpit.is-active");
      const input = root?.querySelector("#ceoInput");
      const form = root?.querySelector("#ceoForm");
      if (!root || !input || !form) return false;
      const inputStyle = getComputedStyle(input);
      const formStyle = getComputedStyle(form);
      const rect = input.getBoundingClientRect();
      return (
        document.documentElement.classList.contains("app-ready") &&
        !document.documentElement.classList.contains("saas-public-direct-start") &&
        inputStyle.display !== "none" &&
        inputStyle.visibility !== "hidden" &&
        formStyle.display !== "none" &&
        formStyle.visibility !== "hidden" &&
        rect.width > 120 &&
        rect.height > 20
      );
    },
    null,
    { timeout: 60000 },
  );
}

function localStaticPath(requestUrl) {
  if (!localStaticRoot) return "";
  const url = new URL(requestUrl);
  const pathname = decodeURIComponent(url.pathname.replace(/^\/+/, "")) || "index.html";
  const allowed =
    ["app.html", "index.html", "app.js", "styles.css", "privacy.html"].includes(pathname) || pathname.startsWith("assets/");
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

async function main() {
  const session = await makeSession();
  let appHtml = "";
  if (localStaticRoot) {
    appHtml = fs.readFileSync(path.join(localStaticRoot, "app.html"), "utf8");
  } else {
    const appHtmlResponse = await fetch(`${base}/app.html?start=app&view=cockpit&smoke-source=${Date.now()}`, {
      cache: "no-store",
    });
    if (!appHtmlResponse.ok) {
      throw new Error(`app html fetch failed: ${appHtmlResponse.status}`);
    }
    appHtml = await appHtmlResponse.text();
  }
  const browser = await chromium.launch({ channel: browserChannel, headless: true, timeout: 60000 });
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
  if (localStaticRoot) {
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
  } else {
    await context.route(`${base}/app.html**`, (route) =>
      route.fulfill({
        status: 200,
        contentType: "text/html; charset=utf-8",
        headers: { "cache-control": "no-store" },
        body: appHtml,
      }),
    );
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
            display_name: "Codex UI Smoke",
            last_seen: new Date().toISOString(),
          },
        ]),
      );
      window.__JIEJING_FORCE_PUBLIC_MVP__ = true;
    },
    { base, session },
  );

  const page = await context.newPage();
  page.setDefaultTimeout(45000);
  const pageErrors = [];
  const requestFailures = [];
  const ignoredRequestFailures = [];
  const badResponses = [];
  const screenshotFailures = [];
  page.on("pageerror", (error) => pageErrors.push(String(error.message || error).slice(0, 500)));
  page.on("requestfailed", (request) => {
    if (request.url().startsWith(base)) {
      const failure = { url: request.url(), error: request.failure()?.errorText || "", resourceType: request.resourceType() };
      const isIgnorableAssetAbort =
        failure.resourceType === "image" &&
        failure.url.startsWith(`${base}/assets/`) &&
        /ERR_ABORTED|NS_BINDING_ABORTED/i.test(failure.error);
      if (isIgnorableAssetAbort) {
        ignoredRequestFailures.push(failure);
        return;
      }
      requestFailures.push(failure);
    }
  });
  page.on("response", (response) => {
    if (response.url().startsWith(base) && response.status() >= 500) {
      badResponses.push({ url: response.url(), status: response.status() });
    }
  });

  await gotoWithRetry(page, `${base}/app.html?start=app&view=cockpit&smoke=${Date.now()}`);
  await page.waitForLoadState("networkidle", { timeout: 45000 }).catch(() => {});
  await waitForWorkbenchReady(page, "view-cockpit");
  await waitForVisibleCeoComposer(page);
  await page
    .locator("#view-cockpit.is-active #ceoInput")
    .fill("帮我调研 eBay 热销收纳小商品，并先整理 Listing 草稿", { timeout: 15000 });
  await page.locator("#view-cockpit.is-active #ceoForm").evaluate((form) => form.requestSubmit());
  await page.waitForTimeout(1200);

  const modules = [
    ["cockpit", "view-cockpit"],
    ["product", "view-product"],
    ["bulk", "view-bulk"],
    ["media", "view-media"],
    ["confirm", "view-confirm"],
    ["service", "view-service"],
    ["connect", "view-connect"],
  ];
  const moduleChecks = [];
  for (const [view, id] of modules) {
    await page.locator(`.nav-item[data-view="${view}"]`).click();
    await waitForWorkbenchReady(page, id);
    await page.waitForTimeout(900);
    await page
      .screenshot({ path: path.join(outDir, `${view}.png`), fullPage: true, timeout: 15000 })
      .catch((error) => screenshotFailures.push({ view, error: String(error.message || error).slice(0, 300) }));
    const check = await page.evaluate(
      ({ id, view }) => {
        const section = document.getElementById(id);
        const text = section?.innerText || "";
        const sectionHas = (selector) => Boolean(section?.querySelector(selector));
        const sectionCount = (selector) => section?.querySelectorAll(selector).length || 0;
        const styleOf = (selector) => {
          const el = document.querySelector(selector);
          if (!el) return "missing";
          const style = getComputedStyle(el);
          return `${style.display}/${style.visibility}`;
        };
        return {
          view,
          exists: Boolean(section),
          visible: Boolean(section && section.offsetParent !== null),
          text_length: text.trim().length,
          topbar_style: styleOf("#appShell .main > .topbar"),
          flow_style: styleOf(".global-flow-bar"),
          handoff_style: styleOf(".saas-ceo-module-handoff"),
          has_listing_simple_head: Boolean(document.querySelector(".saas-listing-simple-head")),
          has_listing_products: Boolean(document.querySelector(".saas-listing-simple-products")),
          has_listing_cplus_stack: sectionHas(".saas-listing-cplus-stack"),
          has_listing_input_panel: sectionHas(".saas-listing-input-panel"),
          has_listing_source_grid: sectionHas(".saas-listing-v2-source-grid"),
          has_listing_status_rail: sectionHas(".saas-listing-v2-status-bar"),
          has_listing_workflow_action: sectionHas('[data-saas-action="listing-start-backend-workflow"]') && text.includes("生成经营链路"),
          has_listing_ai_handoff: sectionHas(".saas-listing-ai-handoff") && text.includes("来自 AI CEO"),
          has_listing_ai_handoff_input: String(section?.querySelector("#saasListingComposerInput")?.value || "").includes("不要触发真实 eBay 写入"),
          has_listing_market_stage: text.includes("市场结论"),
          has_listing_draft_stage: text.includes("Listing 草稿"),
          has_listing_asset_profit_stage: text.includes("素材/利润"),
          has_listing_publish_confirmation_stage: text.includes("发布确认"),
          has_listing_internal_copy: /Listing Package|Market Report|数据包|后台证据|后台排查|local draft|可导入报告|极简开始/.test(text),
          has_direct_publish_button: Array.from(section?.querySelectorAll("button") || []).some((button) =>
            /直接发布|立即发布/.test(button.innerText || ""),
          ),
          has_publish_health_report: sectionHas(".saas-publish-health-report"),
          has_publish_health_report_title: text.includes("发布体检红黄绿报告"),
          publish_health_color_count: sectionCount(
            ".saas-publish-health-summary article.is-red, .saas-publish-health-summary article.is-amber, .saas-publish-health-summary article.is-green",
          ),
          publish_health_source_count: sectionCount(".saas-publish-health-sources article"),
          has_backend_preflight_panel: sectionHas(".saas-backend-preflight-panel"),
          has_backend_preflight_waiting_copy: text.includes("Backend preflight 证据") && text.includes("等待创建发布确认单"),
          backend_preflight_action_count: sectionCount(".saas-backend-preflight-panel [data-saas-action]"),
          has_incident_mode_ops: sectionHas(".saas-incident-mode-ops"),
          has_incident_mode_copy: text.includes("事故模式") && text.includes("真实发布"),
          has_settings_shell: Boolean(document.querySelector(".saas-settings-clean-shell")),
          settings_tab_count: document.querySelectorAll("[data-saas-settings-tab]").length,
          has_media_tabs: Boolean(document.querySelector("#mediaProjectTabs, .media-project-tabs, [data-media-project-tab]")),
          has_media_simple_headline: text.includes("把商品图变成可用素材包"),
          has_media_simple_flow:
            text.includes("选来源") &&
            text.includes("选素材包") &&
            text.includes("看预览") &&
            text.includes("回写 Listing"),
          has_media_internal_copy: /官方数据包|Listing Package|数据包可用|等待数据包|确认记录|费用和用量|素材状态拆分|Provider Hub|素材 Provider|素材 brief|后台证据|后台状态|素材清单已回写|流程导入不需要本机路径/.test(text),
          has_bulk_simple_headline: text.includes("先小批量筛，不一键乱铺"),
          has_bulk_roadmap: sectionHas(".bulk-saas-roadmap"),
          has_bulk_grouping_copy: text.includes("建议先测") && text.includes("需要补资料") && text.includes("暂时不做"),
          has_bulk_internal_copy: /真实账号批量质检|官方数据包|字段完整度|质检槽位|等待数据包/.test(text),
          has_service_simple_headline: text.includes("三件事：消息、订单、回复"),
          has_service_simple_flow: text.includes("消息、订单、回复") && text.includes("没有真实订单时保持空白"),
          has_service_internal_copy: /官方数据包|Listing Package|等待官方订单|等待官方同步|官方数据可用|客服事实表|Provider Hub|provider|后台排查|后台状态|连接和排查在设置|去设置同步 eBay/.test(text),
          has_chat_reply: Boolean(document.querySelector("#view-cockpit #ceoChat .message.ai")),
          has_chat_stream: Boolean(document.querySelector("#view-cockpit #ceoChat")),
          has_ceo_composer_visible: (() => {
            const input = document.querySelector("#view-cockpit #ceoInput");
            const form = document.querySelector("#view-cockpit #ceoForm");
            if (!input || !form) return false;
            const inputStyle = getComputedStyle(input);
            const formStyle = getComputedStyle(form);
            const rect = input.getBoundingClientRect();
            return (
              inputStyle.display !== "none" &&
              inputStyle.visibility !== "hidden" &&
              formStyle.display !== "none" &&
              formStyle.visibility !== "hidden" &&
              rect.width > 120 &&
              rect.height > 20
            );
          })(),
          chat_before_form:
            Boolean(document.querySelector("#ceoChat")) &&
            Boolean(document.querySelector("#ceoForm")) &&
            document.querySelector("#ceoChat").compareDocumentPosition(document.querySelector("#ceoForm")) &
              Node.DOCUMENT_POSITION_FOLLOWING,
          has_collapsed_history: Boolean(document.querySelector("#saasAiCeoHistory, #view-cockpit summary")),
          has_login_overlay: Boolean(document.querySelector(".auth-shell, .saas-login-modal, [data-auth-view]")),
          preview: text.trim().slice(0, 240),
        };
      },
      { id, view },
    );
    moduleChecks.push(check);
  }

  const result = {
    timestamp: new Date().toISOString(),
    base,
    outDir,
    session: {
      email_masked: session.email.replace(/^(.{2}).*(@.*)$/, "$1***$2"),
      store_id: session.store.store_id,
    },
    pageErrors,
    requestFailures,
    ignoredRequestFailures,
    badResponses,
    screenshotFailures,
    navCount: await page.locator(".nav-item").count(),
    moduleChecks,
  };
  fs.writeFileSync(path.join(outDir, "result.json"), JSON.stringify(result, null, 2));
  await browser.close();

  const failures = [];
  if (pageErrors.length) failures.push(`page errors: ${pageErrors.length}`);
  if (requestFailures.length) failures.push(`request failures: ${requestFailures.length}`);
  if (badResponses.length) failures.push(`5xx responses: ${badResponses.length}`);
  if (result.navCount !== 7) failures.push(`nav count ${result.navCount}`);
  for (const check of moduleChecks) {
    if (!check.exists || !check.visible) failures.push(`${check.view} not visible`);
    if (check.text_length < 60) failures.push(`${check.view} too little text`);
    if (!String(check.topbar_style).startsWith("none/")) failures.push(`${check.view} topbar still visible`);
    if (!String(check.flow_style).startsWith("none/")) failures.push(`${check.view} flow bar still visible`);
    if (check.handoff_style !== "missing" && !String(check.handoff_style).startsWith("none/")) failures.push(`${check.view} handoff visible`);
    if (check.has_login_overlay) failures.push(`${check.view} login overlay visible`);
  }
  const product = moduleChecks.find((item) => item.view === "product") || {};
  if (!product.has_listing_cplus_stack || !product.has_listing_input_panel) failures.push("product C+ listing input surface missing");
  if (!product.has_listing_ai_handoff || !product.has_listing_ai_handoff_input) failures.push("product AI CEO to Listing handoff missing");
  if (!product.has_listing_source_grid || !product.has_listing_status_rail) failures.push("product C+ listing source/status rail missing");
  if (!product.has_listing_workflow_action) failures.push("product C+ listing backend workflow action missing");
  if (!product.has_listing_market_stage || !product.has_listing_draft_stage) failures.push("product C+ market-to-draft flow missing");
  if (!product.has_listing_asset_profit_stage || !product.has_listing_publish_confirmation_stage) {
    failures.push("product C+ asset/profit or publish confirmation stage missing");
  }
  if (product.has_listing_internal_copy) failures.push("product daily Listing surface exposes internal report/debug copy");
  if (product.has_direct_publish_button) failures.push("product daily Listing surface exposes a direct publish button");
  const connect = moduleChecks.find((item) => item.view === "connect") || {};
  if (!connect.has_settings_shell || connect.settings_tab_count !== 7) failures.push("settings clean shell/tabs missing");
  const media = moduleChecks.find((item) => item.view === "media") || {};
  if (!media.has_media_tabs) failures.push("media tabs missing");
  if (!media.has_media_simple_headline || !media.has_media_simple_flow) failures.push("media simple workflow surface missing");
  if (media.has_media_internal_copy) failures.push("media daily surface exposes internal evidence/provider copy");
  const bulk = moduleChecks.find((item) => item.view === "bulk") || {};
  if (!bulk.has_bulk_simple_headline || !bulk.has_bulk_roadmap || !bulk.has_bulk_grouping_copy) {
    failures.push("bulk simple grouping surface missing");
  }
  if (bulk.has_bulk_internal_copy) failures.push("bulk daily surface exposes internal evidence/debug copy");
  const service = moduleChecks.find((item) => item.view === "service") || {};
  if (!service.has_service_simple_headline || !service.has_service_simple_flow) failures.push("service simple workflow surface missing");
  if (service.has_service_internal_copy) failures.push("service daily surface exposes internal evidence/provider copy");
  const cockpit = moduleChecks.find((item) => item.view === "cockpit") || {};
  if (!cockpit.has_chat_stream || !cockpit.has_ceo_composer_visible || !cockpit.chat_before_form) {
    failures.push("AI CEO chat stream/composer missing or wrong order");
  }
  if (cockpit.has_collapsed_history) failures.push("AI CEO conversation is still hidden behind a collapsed history section");

  if (failures.length) {
    console.error(JSON.stringify({ ok: false, failures, result }, null, 2));
    process.exit(1);
  }
  console.log(JSON.stringify({ ok: true, outDir, moduleChecks }, null, 2));
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
