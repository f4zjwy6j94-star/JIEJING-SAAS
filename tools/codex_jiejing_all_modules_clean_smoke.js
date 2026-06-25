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

async function waitForCeoRouteTaskTarget(page, target) {
  await page
    .waitForFunction(
      (expectedTarget) => {
        const card = document.querySelector("#view-cockpit .saas-ceo-routing-task-card");
        const button = card?.querySelector("[data-global-flow-view]");
        const pending = document.querySelector("#view-cockpit #ceoChat .message.ai.is-pending");
        return Boolean(card && card.offsetParent !== null && button?.getAttribute("data-global-flow-view") === expectedTarget && !pending);
      },
      target,
      { timeout: 12000 },
    )
    .catch(() => {});
  await page.waitForTimeout(250);
}

async function waitForCeoPlainConsultationSettled(page) {
  await page
    .waitForFunction(
      () => {
        const messages = Array.from(document.querySelectorAll("#view-cockpit #ceoChat .message.ai"));
        const lastAi = messages[messages.length - 1] || null;
        const card = document.querySelector("#view-cockpit .saas-ceo-routing-task-card");
        const pending = document.querySelector("#view-cockpit #ceoChat .message.ai.is-pending");
        return Boolean(lastAi?.getAttribute("data-status") === "local_clock_answered" && !(card && card.offsetParent !== null) && !pending);
      },
      null,
      { timeout: 12000 },
    )
    .catch(() => {});
  await page.waitForTimeout(250);
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
    .screenshot({ path: path.join(outDir, "cockpit-first-run.png"), fullPage: true, timeout: 15000 })
    .catch((error) => screenshotFailures.push({ view: "cockpit-first-run", error: String(error.message || error).slice(0, 300) }));
  const ceoFirstRunEntry = await page.evaluate(() => {
    const root = document.querySelector("#view-cockpit.is-active");
    const text = root?.innerText || "";
    const placeholder = root?.querySelector("#ceoInput")?.getAttribute("placeholder") || "";
    const starterPrompts = root?.querySelector(".saas-ai-ceo-starter-prompts");
    const routeCard = root?.querySelector(".saas-ceo-routing-task-card");
    const handoff = root?.querySelector(".saas-ai-ceo-first-run-handoff");
    return {
      has_one_sentence_title: text.includes("一句话交给 AI CEO"),
      has_plain_chat_copy: text.includes("问问题直接答") && text.includes("真实发布、付款、退款和广告先问你"),
      has_input_example: placeholder.includes("帮我调研这个商品") && placeholder.includes("Listing 草稿"),
      has_plain_chat_hint:
        text.includes("也可以直接问普通问题") && text.includes("自动进入 Listing、批量、素材、客服或决策中心"),
      has_first_run_handoff: Boolean(handoff && handoff.offsetParent !== null),
      has_first_run_handoff_marker: handoff?.getAttribute("data-ai-ceo-first-run-handoff") === "first_run_ai_ceo_handoff_v1",
      handoff_does_not_trigger_real_write: handoff?.getAttribute("data-does-not-trigger-real-write") === "true",
      has_first_run_handoff_copy:
        text.includes("直接说经营目标，不用先找功能") &&
        text.includes("点一句只会填入输入框") &&
        text.includes("我还没接 eBay，先用资料跑草稿"),
      first_run_handoff_action_count: root?.querySelectorAll(".saas-ai-ceo-first-run-actions [data-ceo-prompt]").length || 0,
      has_starter_prompts: Boolean(starterPrompts && getComputedStyle(starterPrompts).display !== "none"),
      has_route_card: Boolean(routeCard && routeCard.offsetParent !== null),
      exposes_internal_copy: /packet|provider|preflight|数据包|后台|排查/i.test(text),
      placeholder,
      preview: text.trim().slice(0, 240),
    };
  });
  const ceoFirstRunPrefill = await page.evaluate(() => {
    const input = document.querySelector("#view-cockpit.is-active #ceoInput");
    const button = document.querySelector("#view-cockpit.is-active .saas-ai-ceo-first-run-actions [data-ceo-prompt]");
    if (!input || !button) return { ok: false, reason: "missing_input_or_prompt" };
    button.click();
    return {
      ok: input.value === button.getAttribute("data-ceo-prompt"),
      value: input.value,
      still_no_route_card: !document.querySelector("#view-cockpit .saas-ceo-routing-task-card"),
      still_no_chat_message: !document.querySelector("#view-cockpit #ceoChat .message"),
    };
  });
  await page
    .locator("#view-cockpit.is-active #ceoInput")
    .fill("帮我调研 eBay 热销收纳小商品，并先整理 Listing 草稿", { timeout: 15000 });
  await page.locator('#view-cockpit.is-active #ceoForm button[type="submit"]').click();
  await waitForCeoRouteTaskTarget(page, "product");
  await page
    .screenshot({ path: path.join(outDir, "cockpit-route-card.png"), fullPage: true, timeout: 15000 })
    .catch((error) => screenshotFailures.push({ view: "cockpit-route-card", error: String(error.message || error).slice(0, 300) }));
  const ceoRouteTask = await page.evaluate(() => {
    const card = document.querySelector("#view-cockpit .saas-ceo-routing-task-card");
    const button = card?.querySelector("[data-global-flow-view]");
    return {
      visible: Boolean(card && card.offsetParent !== null),
      text: card?.innerText || "",
      target: button?.getAttribute("data-global-flow-view") || "",
      button: button?.innerText || "",
      has_why_rows: document.querySelectorAll("#view-cockpit .saas-ceo-routing-why article").length === 3,
      has_simple_copy:
        (card?.innerText || "").includes("我理解") &&
        (card?.innerText || "").includes("推荐去") &&
        (card?.innerText || "").includes("安全边界"),
      has_internal_copy: /packet|provider|preflight|数据包|后台|排查/i.test(card?.innerText || ""),
    };
  });
  if (ceoRouteTask.visible) {
    await page.locator('#view-cockpit .saas-ceo-routing-task-card [data-global-flow-view="product"]').click();
    await waitForWorkbenchReady(page, "view-product");
    await page.waitForTimeout(500);
    ceoRouteTask.clicked_product_route = await page.evaluate(() => document.body?.dataset?.view === "product");
    await page.locator('.nav-item[data-view="cockpit"]').click();
    await waitForWorkbenchReady(page, "view-cockpit");
    await page.waitForTimeout(400);
  }

  const routeScenarioDefs = [
    { label: "bulk", text: "帮我批量筛 10 个 eBay 热销小商品", target: "bulk" },
    { label: "media", text: "帮我把这张货源图生成主图和详情页", target: "media" },
    { label: "service", text: "帮我整理买家消息和订单物流回复草稿", target: "service" },
    { label: "confirm", text: "帮我直接发布并开广告预算", target: "confirm" },
  ];
  const ceoRouteScenarios = [];
  for (const scenario of routeScenarioDefs) {
    await page.locator("#view-cockpit.is-active #ceoInput").fill(scenario.text, { timeout: 15000 });
    await page.locator('#view-cockpit.is-active #ceoForm button[type="submit"]').click();
    await waitForCeoRouteTaskTarget(page, scenario.target);
    const scenarioResult = await page.evaluate((scenario) => {
      const card = document.querySelector("#view-cockpit .saas-ceo-routing-task-card");
      const button = card?.querySelector("[data-global-flow-view]");
      const text = card?.innerText || "";
      return {
        label: scenario.label,
        expected: scenario.target,
        visible: Boolean(card && card.offsetParent !== null),
        target: button?.getAttribute("data-global-flow-view") || "",
        has_why_rows: document.querySelectorAll("#view-cockpit .saas-ceo-routing-why article").length === 3,
        has_simple_copy: text.includes("我理解") && text.includes("推荐去") && text.includes("安全边界"),
        has_internal_copy: /packet|provider|preflight|数据包|后台|排查/i.test(text),
        text: text.slice(0, 240),
      };
    }, scenario);
    await page.locator(`#view-cockpit .saas-ceo-routing-task-card [data-global-flow-view="${scenario.target}"]`).click();
    await waitForWorkbenchReady(page, `view-${scenario.target}`);
    await page.waitForTimeout(500);
    scenarioResult.module_goal = await page.evaluate((scenario) => {
      const section = document.getElementById(`view-${scenario.target}`);
      const strip = section?.querySelector(".saas-module-ai-goal-strip");
      const text = strip?.innerText || "";
      return {
        visible: Boolean(strip && strip.offsetParent !== null),
        marker: strip?.getAttribute("data-ai-ceo-module-goal-strip") || "",
        view: strip?.getAttribute("data-ai-ceo-module-view") || "",
        has_goal_step: text.includes("目标"),
        has_next_step: text.includes("下一步"),
        has_boundary_step: text.includes("边界"),
        has_internal_copy: /packet|provider|preflight|数据包|后台|排查/i.test(text),
        text: text.slice(0, 240),
      };
    }, scenario);
    ceoRouteScenarios.push(scenarioResult);
    await page.locator('.nav-item[data-view="cockpit"]').click();
    await waitForWorkbenchReady(page, "view-cockpit");
    await page.waitForTimeout(400);
  }

  await page.locator("#view-cockpit.is-active #ceoInput").fill("今天几号", { timeout: 15000 });
  await page.locator('#view-cockpit.is-active #ceoForm button[type="submit"]').click();
  await waitForCeoPlainConsultationSettled(page);
  const ceoPlainConsultation = await page.evaluate(() => {
    const messages = Array.from(document.querySelectorAll("#view-cockpit #ceoChat .message.ai"));
    const lastAi = messages[messages.length - 1] || null;
    const lastText = lastAi?.innerText || "";
    const card = document.querySelector("#view-cockpit .saas-ceo-routing-task-card");
    return {
      has_answer: lastText.trim().length > 12,
      has_route_task_card: Boolean(card && card.offsetParent !== null),
      has_last_work_detail: Boolean(lastAi?.querySelector(".saas-ai-ceo-work-detail")),
      last_status: lastAi?.getAttribute("data-status") || "",
      last_text: lastText.slice(0, 240),
      exposes_internal_copy: /packet|provider|preflight|数据包|后台|排查|工作详情|来源记录/i.test(lastText),
    };
  });

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
          has_listing_first_run_strip:
            sectionHas(".saas-first-run-strip") && text.includes("不用完整") && text.includes("缺口会停住"),
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
          has_settings_home_hub: sectionHas(".saas-settings-home-hub"),
          settings_home_status_count: sectionCount(".saas-settings-home-status article"),
          has_settings_simple_copy: text.includes("普通商家只看 5 个入口") && text.includes("什么时候需要打开设置"),
          has_settings_one_glance: sectionHas(".saas-settings-one-glance") && text.includes("本页重点"),
          settings_one_glance_count: sectionCount(".saas-settings-one-glance-grid article"),
          has_media_tabs: Boolean(document.querySelector("#mediaProjectTabs, .media-project-tabs, [data-media-project-tab]")),
          has_media_simple_headline: text.includes("把商品图变成可用素材包"),
          has_media_simple_flow:
            text.includes("来源") &&
            text.includes("成品") &&
            text.includes("审核") &&
            text.includes("回写 Listing"),
          has_media_first_run_strip: Array.from(section?.querySelectorAll(".saas-media-first-run-strip, .saas-first-run-strip") || []).some((node) => {
            const nodeText = node.innerText || "";
            return nodeText.includes("输入") && nodeText.includes("只回写草稿");
          }),
          has_media_internal_copy: /官方数据包|Listing Package|数据包可用|等待数据包|确认记录|费用和用量|素材状态拆分|Provider Hub|素材 Provider|素材 brief|后台证据|后台状态|素材清单已回写|流程导入不需要本机路径/.test(text),
          has_bulk_simple_headline: text.includes("先小批量筛，不一键乱铺"),
          has_bulk_roadmap: sectionHas(".bulk-output-snapshot"),
          has_bulk_grouping_copy: text.includes("能试") && text.includes("要补") && text.includes("先不做"),
          has_bulk_first_run_strip: sectionHas(".bulk-output-snapshot") && text.includes("真实发布") && text.includes("决策中心"),
          has_bulk_internal_copy: /真实账号批量质检|官方数据包|字段完整度|质检槽位|等待数据包/.test(text),
          has_service_simple_headline: text.includes("三件事：消息、订单、回复"),
          has_service_simple_flow: text.includes("消息、订单、回复") && text.includes("没有真实订单时保持空白"),
          has_service_first_run_strip:
            sectionHas(".saas-service-first-run-strip") && text.includes("没有订单不造假") && text.includes("只引用已知事实"),
          has_service_internal_copy: /官方数据包|Listing Package|等待官方订单|等待官方同步|官方数据可用|客服事实表|Provider Hub|provider|后台排查|后台状态|连接和排查在设置|去设置同步 eBay/.test(text),
          has_confirm_simple_headline: text.includes("只让你处理真正要拍板的事"),
          has_confirm_simple_action_copy: text.includes("这里只做三种选择"),
          has_confirm_decision_v2:
            sectionHas(".saas-confirm-action-model") &&
            text.includes("你没点头前不会执行") &&
            (sectionHas(".runtime-confirm-empty") ||
              (sectionHas(".saas-confirm-card-decision") && sectionHas(".saas-confirm-safety-detail"))),
          has_confirm_internal_copy: /高级细节|上线检查|后台|运维|preflight|packet|provider/.test(text),
          has_chat_reply: Boolean(document.querySelector("#view-cockpit #ceoChat .message.ai")),
          has_chat_stream: Boolean(document.querySelector("#view-cockpit #ceoChat")),
          has_ceo_route_task_card: Boolean(document.querySelector("#view-cockpit .saas-ceo-routing-task-card")),
          ceo_route_task_target: document.querySelector("#view-cockpit .saas-ceo-routing-task-card [data-global-flow-view]")?.getAttribute("data-global-flow-view") || "",
          ceo_route_task_copy:
            text.includes("AI CEO 已接住") &&
            text.includes("我理解") &&
            text.includes("推荐去") &&
            text.includes("安全边界"),
          ceo_route_task_internal_copy: /packet|provider|preflight|数据包|后台|排查/i.test(
            document.querySelector("#view-cockpit .saas-ceo-routing-task-card")?.innerText || "",
          ),
          ceo_starter_prompts_visible: (() => {
            const prompts = document.querySelector("#view-cockpit .saas-ai-ceo-starter-prompts");
            return Boolean(prompts && getComputedStyle(prompts).display !== "none");
          })(),
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
          ceo_pending_chip_is_not_avatar: (() => {
            const chip = document.querySelector("#view-cockpit .saas-ai-ceo-pending-status span");
            if (!chip) return true;
            const style = getComputedStyle(chip);
            const rect = chip.getBoundingClientRect();
            return (
              rect.width > 34 &&
              rect.height < 30 &&
              style.backgroundColor !== "rgb(16, 28, 23)" &&
              style.color !== "rgb(255, 255, 255)"
            );
          })(),
          preview: text.trim().slice(0, 240),
        };
      },
      { id, view },
    );
    if (view === "connect" && (await page.locator('.saas-settings-clean-nav [data-saas-settings-tab="model"]').count())) {
      const settingsChildTabs = ["account", "model", "data", "governance", "billing"];
      const settingsChildAudit = [];
      for (const tabId of settingsChildTabs) {
        await page.locator(`.saas-settings-clean-nav [data-saas-settings-tab="${tabId}"]`).click();
        await page.waitForTimeout(220);
        settingsChildAudit.push(
          await page.evaluate((id) => {
            const section = document.getElementById("view-connect");
            const text = section?.innerText || "";
            const rawText = section?.textContent || "";
            return {
              id,
              has_home_hub: Boolean(section?.querySelector(".saas-settings-home-hub")),
              has_section_group: Boolean(section?.querySelector(".saas-settings-section-group")),
              has_focus_panel: Boolean(section?.querySelector(".saas-settings-focus-panel")),
              has_subpage_strip: Boolean(section?.querySelector(".saas-settings-subpage-strip")),
              has_one_glance: Boolean(section?.querySelector(".saas-settings-one-glance")),
              one_glance_count: section?.querySelectorAll(".saas-settings-one-glance-grid article").length || 0,
              has_one_glance_copy: text.includes("本页只看三件事") && text.includes("先理解状态"),
              has_model_provider_panel: Boolean(section?.querySelector(".saas-model-provider-panel")),
              has_billing_current_panel:
                Boolean(section?.querySelector(".saas-merchant-billing-current")) &&
                rawText.includes("merchant_visible_billing_status_v1") &&
                rawText.includes("triggers_real_charge=false") &&
                rawText.includes("frontend_gets_payment_secret=false"),
              has_billing_pricing_split:
                Boolean(
                  section?.querySelector(
                    '.saas-merchant-pricing-split[data-billing-split="subscription_ai_media_platform_v1"]',
                  ),
                ) &&
                text.includes("¥99/月是基础订阅") &&
                text.includes("用量计费路线"),
              preview: text.trim().slice(0, 180),
            };
          }, tabId),
        );
      }
      check.settings_child_audit = settingsChildAudit;
      check.settings_children_are_focused = settingsChildAudit.every(
        (item) =>
          item.has_focus_panel &&
          !item.has_one_glance &&
          item.one_glance_count === 0 &&
          !item.has_one_glance_copy &&
          !item.has_home_hub &&
          !item.has_section_group &&
          !item.has_subpage_strip,
      );
      const modelAudit = settingsChildAudit.find((item) => item.id === "model") || {};
      const billingAudit = settingsChildAudit.find((item) => item.id === "billing") || {};
      check.settings_model_has_home_hub = modelAudit.has_home_hub || false;
      check.settings_model_has_subpage_strip = modelAudit.has_subpage_strip || false;
      check.settings_model_has_model_panel = modelAudit.has_model_provider_panel || false;
      check.settings_billing_has_current_status = billingAudit.has_billing_current_panel || false;
      check.settings_billing_has_pricing_split = billingAudit.has_billing_pricing_split || false;
      await page
        .screenshot({ path: path.join(outDir, "connect-model.png"), fullPage: true, timeout: 15000 })
        .catch((error) => screenshotFailures.push({ view: "connect-model", error: String(error.message || error).slice(0, 300) }));
      await page.locator('.saas-settings-clean-nav [data-saas-settings-tab="general"]').click();
      await page.waitForTimeout(250);
    }
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
    ceoFirstRunEntry,
    ceoFirstRunPrefill,
    ceoRouteTask,
    ceoRouteScenarios,
    ceoPlainConsultation,
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
  if (!product.has_listing_first_run_strip) failures.push("product first-run assurance strip missing");
  if (!product.has_listing_workflow_action) failures.push("product C+ listing backend workflow action missing");
  if (!product.has_listing_market_stage || !product.has_listing_draft_stage) failures.push("product C+ market-to-draft flow missing");
  if (!product.has_listing_asset_profit_stage || !product.has_listing_publish_confirmation_stage) {
    failures.push("product C+ asset/profit or publish confirmation stage missing");
  }
  if (product.has_listing_internal_copy) failures.push("product daily Listing surface exposes internal report/debug copy");
  if (product.has_direct_publish_button) failures.push("product daily Listing surface exposes a direct publish button");
  const connect = moduleChecks.find((item) => item.view === "connect") || {};
  if (!connect.has_settings_shell || connect.settings_tab_count < 6 || connect.settings_tab_count > 7) failures.push("settings clean shell/tabs missing");
  if (!connect.has_settings_home_hub || connect.settings_home_status_count < 4) {
    failures.push("settings compact hub/status missing");
  }
  if (!connect.has_settings_simple_copy) failures.push("settings simple usage copy missing");
  if (!connect.has_settings_one_glance || connect.settings_one_glance_count < 3) {
    failures.push("settings one-glance summary missing");
  }
  if (!connect.settings_children_are_focused) failures.push("ordinary settings child tabs are not focused");
  if (connect.settings_model_has_home_hub) failures.push("settings child page repeats overview map");
  if (connect.settings_model_has_subpage_strip) failures.push("settings child page still shows redundant intro/map");
  if (!connect.settings_model_has_model_panel) failures.push("settings child page content missing");
  if (!connect.settings_billing_has_current_status) failures.push("settings billing current merchant status missing");
  if (!connect.settings_billing_has_pricing_split) failures.push("settings billing pricing split missing");
  const media = moduleChecks.find((item) => item.view === "media") || {};
  if (!media.has_media_tabs) failures.push("media tabs missing");
  if (!media.has_media_simple_headline || !media.has_media_simple_flow) failures.push("media simple workflow surface missing");
  if (!media.has_media_first_run_strip) failures.push("media first-run assurance strip missing");
  if (media.has_media_internal_copy) failures.push("media daily surface exposes internal evidence/provider copy");
  const bulk = moduleChecks.find((item) => item.view === "bulk") || {};
  if (!bulk.has_bulk_simple_headline || !bulk.has_bulk_roadmap || !bulk.has_bulk_grouping_copy) {
    failures.push("bulk simple grouping surface missing");
  }
  if (!bulk.has_bulk_first_run_strip) failures.push("bulk first-run assurance strip missing");
  if (bulk.has_bulk_internal_copy) failures.push("bulk daily surface exposes internal evidence/debug copy");
  const service = moduleChecks.find((item) => item.view === "service") || {};
  if (!service.has_service_simple_headline || !service.has_service_simple_flow) failures.push("service simple workflow surface missing");
  if (!service.has_service_first_run_strip) failures.push("service first-run assurance strip missing");
  if (service.has_service_internal_copy) failures.push("service daily surface exposes internal evidence/provider copy");
  const confirm = moduleChecks.find((item) => item.view === "confirm") || {};
  if (!confirm.has_confirm_simple_headline || !confirm.has_confirm_simple_action_copy) {
    failures.push("confirm simple decision surface missing");
  }
  if (!confirm.has_confirm_decision_v2) failures.push("confirm decision v2 lightweight approval model missing");
  if (confirm.has_confirm_internal_copy) failures.push("confirm surface exposes internal/debug copy");
  const cockpit = moduleChecks.find((item) => item.view === "cockpit") || {};
  if (!cockpit.has_chat_stream || !cockpit.has_ceo_composer_visible || !cockpit.chat_before_form) {
    failures.push("AI CEO chat stream/composer missing or wrong order");
  }
  if (
    !ceoFirstRunEntry.has_one_sentence_title ||
    !ceoFirstRunEntry.has_plain_chat_copy ||
    !ceoFirstRunEntry.has_input_example ||
    !ceoFirstRunEntry.has_plain_chat_hint ||
    !ceoFirstRunEntry.has_first_run_handoff ||
    !ceoFirstRunEntry.has_first_run_handoff_marker ||
    !ceoFirstRunEntry.handoff_does_not_trigger_real_write ||
    !ceoFirstRunEntry.has_first_run_handoff_copy ||
    ceoFirstRunEntry.first_run_handoff_action_count < 3
  ) {
    failures.push("AI CEO first-run entry is not a low-learning-cost one-sentence composer");
  }
  if (!ceoFirstRunPrefill.ok || !ceoFirstRunPrefill.still_no_route_card || !ceoFirstRunPrefill.still_no_chat_message) {
    failures.push("AI CEO first-run handoff prompts must only prefill the composer");
  }
  if (ceoFirstRunEntry.has_starter_prompts || ceoFirstRunEntry.has_route_card) {
    failures.push("AI CEO first-run entry still exposes starter prompts or a route card before user intent");
  }
  if (ceoFirstRunEntry.exposes_internal_copy) {
    failures.push("AI CEO first-run entry exposes internal/debug copy");
  }
  if (!ceoRouteTask.visible || ceoRouteTask.target !== "product" || !ceoRouteTask.clicked_product_route) {
    failures.push("AI CEO lightweight routing task card did not route to Listing");
  }
  if (ceoRouteTask.has_internal_copy || cockpit.ceo_route_task_internal_copy) {
    failures.push("AI CEO routing task card exposes internal packet/provider/preflight copy");
  }
  if (!ceoRouteTask.has_why_rows || !ceoRouteTask.has_simple_copy) {
    failures.push("AI CEO routing task card copy missing");
  }
  for (const scenario of ceoRouteScenarios) {
    if (!scenario.visible || scenario.target !== scenario.expected || !scenario.has_why_rows || !scenario.has_simple_copy) {
      failures.push(`AI CEO route scenario ${scenario.label} failed`);
    }
    if (scenario.has_internal_copy) {
      failures.push(`AI CEO route scenario ${scenario.label} exposes internal copy`);
    }
    if (
      !scenario.module_goal?.visible ||
      scenario.module_goal?.marker !== "ai_ceo_module_goal_v1" ||
      scenario.module_goal?.view !== scenario.expected ||
      !scenario.module_goal?.has_goal_step ||
      !scenario.module_goal?.has_next_step ||
      !scenario.module_goal?.has_boundary_step
    ) {
      failures.push(`AI CEO route scenario ${scenario.label} did not hand goal to target module`);
    }
    if (scenario.module_goal?.has_internal_copy) {
      failures.push(`AI CEO module goal strip ${scenario.label} exposes internal copy`);
    }
  }
  if (!ceoPlainConsultation.has_answer) failures.push("AI CEO plain consultation did not render an answer");
  if (ceoPlainConsultation.has_route_task_card) failures.push("AI CEO plain consultation still shows a routing task card");
  if (ceoPlainConsultation.has_last_work_detail) failures.push("AI CEO plain consultation still shows work details");
  if (ceoPlainConsultation.exposes_internal_copy) failures.push("AI CEO plain consultation exposes internal/debug copy");
  if (cockpit.ceo_starter_prompts_visible) {
    failures.push("AI CEO first screen still exposes starter prompt buttons");
  }
  if (cockpit.has_collapsed_history) failures.push("AI CEO conversation is still hidden behind a collapsed history section");
  if (!cockpit.ceo_pending_chip_is_not_avatar) {
    failures.push("AI CEO pending status chip is inheriting avatar styling on small screens");
  }

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
