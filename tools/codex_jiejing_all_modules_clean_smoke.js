#!/usr/bin/env node
/* ASCII-only staging UI smoke for Jiejing's seven merchant modules. */

const fs = require("fs");
const path = require("path");
const { chromium } = require("../output/codex-playwright-deps/node_modules/playwright-core");

const base = process.env.JIEJING_TEST_BASE || "https://app.jiejing.shop";
const browserChannel = process.env.JIEJING_PLAYWRIGHT_CHANNEL || "chrome";
const localStaticRoot = process.env.JIEJING_LOCAL_STATIC_ROOT ? path.resolve(process.env.JIEJING_LOCAL_STATIC_ROOT) : "";
const viewportWidth = Number(process.env.JIEJING_SMOKE_VIEWPORT_WIDTH || 1440);
const viewportHeight = Number(process.env.JIEJING_SMOKE_VIEWPORT_HEIGHT || 920);
const stamp = new Date().toISOString().replace(/[:.]/g, "-");
const outDir = path.join("output", "browser-smoke", `${stamp}-all-modules-clean-ui`);
fs.mkdirSync(outDir, { recursive: true });

async function api(pathname, { token = "", cookie = "", method = "GET", body } = {}) {
  const res = await fetch(`${base}${pathname}`, {
    method,
    cache: "no-store",
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
  const sessionCookie = String(registered.setCookie || "")
    .split(";", 1)[0]
    .trim();
  const token = registered.json.token || (sessionCookie.startsWith("jiejing_saas_session=") ? sessionCookie.slice("jiejing_saas_session=".length) : "");
  if (!token || !sessionCookie) {
    throw new Error("register did not establish the backend-only browser session cookie");
  }
  const user = registered.json.user || {};
  const company = registered.json.company || {};
  const activatedBilling = await api("/billing/test-event", {
    token,
    cookie: sessionCookie,
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
    cookie: sessionCookie,
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
        return Boolean(card && card.offsetParent !== null && button?.getAttribute("data-global-flow-view") === expectedTarget);
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
    ["app.html", "index.html", "app.js", "styles.css", "privacy.html", "terms.html", "refund-policy.html", "support.html", "risk-disclosure.html"].includes(pathname) || pathname.startsWith("assets/");
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
      return route.fulfill({
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
  const clientResponses = [];
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
      const isIgnorableStreamAbort =
        failure.resourceType === "fetch" &&
        failure.url.includes("/merchant-ceo/chat?stream=1") &&
        /ERR_ABORTED|NS_BINDING_ABORTED/i.test(failure.error);
      if (isIgnorableAssetAbort || isIgnorableStreamAbort) {
        ignoredRequestFailures.push(failure);
        return;
      }
      requestFailures.push(failure);
    }
  });
  page.on("response", (response) => {
    if (response.url().startsWith(base) && response.status() >= 400 && response.status() < 500) {
      clientResponses.push({ url: response.url(), status: response.status() });
    }
    if (response.url().startsWith(base) && response.status() >= 500) {
      badResponses.push({ url: response.url(), status: response.status() });
    }
  });

  await gotoWithRetry(page, `${base}/app.html?start=app&view=cockpit&smoke=${Date.now()}`);
  await page.waitForLoadState("networkidle", { timeout: 45000 }).catch(() => {});
  await waitForWorkbenchReady(page, "view-cockpit");
  try {
    await waitForVisibleCeoComposer(page);
  } catch (error) {
    await page.screenshot({ path: path.join(outDir, "cockpit-composer-timeout.png"), fullPage: true }).catch(() => {});
    const diagnostic = await page.evaluate(() => {
      const root = document.querySelector("#view-cockpit.is-active");
      const input = root?.querySelector("#ceoInput");
      const form = root?.querySelector("#ceoForm");
      const inputStyle = input ? getComputedStyle(input) : null;
      const formStyle = form ? getComputedStyle(form) : null;
      const rect = input?.getBoundingClientRect();
      return {
        html_classes: document.documentElement.className,
        root_visible: Boolean(root && root.offsetParent !== null),
        input_exists: Boolean(input),
        input_display: inputStyle?.display || "",
        input_visibility: inputStyle?.visibility || "",
        input_width: Number(rect?.width || 0),
        input_height: Number(rect?.height || 0),
        form_exists: Boolean(form),
        form_display: formStyle?.display || "",
        form_visibility: formStyle?.visibility || "",
        auth_overlay_visible: Boolean(document.querySelector(".auth-overlay:not([hidden]), .auth-modal:not([hidden])")),
        saas_loading: Boolean(window.state?.saasLoading),
        saas_connected: Boolean(window.state?.saasConnected),
        protected_state_ready: Boolean(window.state?.saasProtectedStateReady),
        protected_state_from_cache: Boolean(window.state?.saasProtectedStateFromCache),
        has_user: Boolean(window.state?.saasUser),
        saas_error: String(window.state?.saasError || "").slice(0, 300),
        body_preview: String(document.body?.innerText || "").slice(0, 500),
      };
    });
    throw new Error(
      `AI CEO composer did not become visible: ${JSON.stringify({ ...diagnostic, requestFailures, clientResponses, badResponses, pageErrors })}; ${error.message || error}`,
    );
  }
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
    const oneTaskFocus = root?.querySelector('.saas-ai-ceo-one-task-focus[data-ai-ceo-one-task-focus="first_day_one_task_focus_v1"]');
    const firstDayPath = root?.querySelector('.saas-ai-ceo-first-day-path[data-ai-ceo-first-day-path="first_day_ai_ceo_path_v2"]');
    const feedbackToggle = document.querySelector("#workflowFeedbackToggle");
    const sendButton = root?.querySelector('#ceoForm button[type="submit"]');
    const overlaps = (left, right) => {
      if (!left || !right || left.offsetParent === null || right.offsetParent === null) return false;
      const a = left.getBoundingClientRect();
      const b = right.getBoundingClientRect();
      return a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top;
    };
    return {
      has_one_sentence_title: text.includes("一句话交给 AI CEO"),
      has_plain_chat_copy: text.includes("问问题直接答") && text.includes("真实发布、付款、退款和广告先问你"),
      has_input_example: placeholder.includes("帮我调研这个商品") && placeholder.includes("Listing 草稿"),
      has_plain_chat_hint:
        text.includes("也可以直接问普通问题") && text.includes("自动进入 Listing、批量、素材、客服或决策中心"),
      has_first_run_handoff: Boolean(handoff && handoff.offsetParent !== null),
      has_first_run_handoff_marker: handoff?.getAttribute("data-ai-ceo-first-run-handoff") === "first_run_ai_ceo_handoff_v1",
      handoff_does_not_trigger_real_write: handoff?.getAttribute("data-does-not-trigger-real-write") === "true",
      has_first_day_path: Boolean(firstDayPath && firstDayPath.offsetParent !== null),
      first_day_path_step_count: firstDayPath?.querySelectorAll("article").length || 0,
      has_first_day_path_copy: text.includes("说目标") && text.includes("看判断") && text.includes("再确认"),
      has_one_task_focus: Boolean(oneTaskFocus && oneTaskFocus.offsetParent !== null),
      one_task_focus_card_count: oneTaskFocus?.querySelectorAll(".saas-ai-ceo-one-task-option").length || 0,
      one_task_focus_prompt_count: oneTaskFocus?.querySelectorAll(".saas-ai-ceo-one-task-option[data-ceo-prompt]").length || 0,
      has_one_task_focus_copy:
        text.includes("现在只做一件事") &&
        text.includes("把手上的商品、链接、图片或订单问题发给 AI CEO") &&
        text.includes("有商品想上架") &&
        text.includes("只有图片或链接") &&
        text.includes("不知道下一步"),
      has_first_run_handoff_copy:
        text.includes("直接说经营目标，不用先找功能") &&
        text.includes("点一句只会填入输入框") &&
        text.includes("我还没接 eBay，先用资料跑草稿"),
      first_run_handoff_action_count: root?.querySelectorAll(".saas-ai-ceo-first-run-actions [data-ceo-prompt]").length || 0,
      has_starter_prompts: Boolean(starterPrompts && getComputedStyle(starterPrompts).display !== "none"),
      has_route_card: Boolean(routeCard && routeCard.offsetParent !== null),
      feedback_overlaps_send: overlaps(feedbackToggle, sendButton),
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
  const ceoFirstRunFocusPrefill = await page.evaluate(() => {
    const input = document.querySelector("#view-cockpit.is-active #ceoInput");
    const button = document.querySelector("#view-cockpit.is-active .saas-ai-ceo-one-task-option[data-ceo-prompt]");
    if (!input || !button) return { ok: false, reason: "missing_input_or_focus_prompt" };
    input.value = "";
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
      has_v2_marker: card?.getAttribute("data-ai-ceo-route-task-card") === "ai_ceo_route_task_card_v2",
      has_why_rows: document.querySelectorAll("#view-cockpit .saas-ceo-routing-why article").length === 3,
      has_simple_copy:
        (card?.innerText || "").includes("我理解") &&
        (card?.innerText || "").includes("推荐去") &&
        (card?.innerText || "").includes("安全边界"),
      has_next_step_copy:
        (card?.innerText || "").includes("下一步建议") &&
        (card?.innerText || "").includes("不会自动执行真实动作") &&
        (card?.innerText || "").includes("点按钮后只打开对应工作台继续整理"),
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
    {
      label: "research-evidence-followup",
      text: "继续 report_5eaf36a405de7331，只补 eBay US Sold & Completed 成交证据并做三选一；不能复用品牌或图片，不生成 Listing、不生图、不写 eBay。",
      target: "cockpit",
    },
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
        has_v2_marker: card?.getAttribute("data-ai-ceo-route-task-card") === "ai_ceo_route_task_card_v2",
        has_why_rows: document.querySelectorAll("#view-cockpit .saas-ceo-routing-why article").length === 3,
        has_simple_copy: text.includes("我理解") && text.includes("推荐去") && text.includes("安全边界"),
        has_next_step_copy:
          text.includes("下一步建议") &&
          text.includes("不会自动执行真实动作") &&
          (scenario.target === "confirm"
            ? text.includes("点按钮后只进入决策中心")
            : text.includes("点按钮后只打开对应工作台继续整理")),
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
    if (view === "product") {
      const draftState = await page.evaluate(() => {
        const section = document.getElementById("view-product");
        if (section?.querySelector(".saas-listing-v2-draft-editor")) return "already";
        const input = section?.querySelector("#saasListingComposerInput");
        if (input && !String(input.value || "").trim() && window.state?.saasListingComposerInput) {
          input.value = window.state.saasListingComposerInput;
        }
        if (typeof window.handleSaasListingComposeDraft === "function") {
          return window.handleSaasListingComposeDraft() ? "called_handler" : "handler_blocked";
        }
        const buttons = Array.from(section?.querySelectorAll('[data-saas-action="listing-compose-draft"]') || []);
        const button = buttons.find((item) => item.offsetParent !== null && !item.disabled);
        if (!button) return "missing";
        button.click();
        return "clicked";
      });
      if (draftState === "clicked" || draftState === "called_handler") {
        await page
          .waitForFunction(() => Boolean(document.querySelector("#view-product .saas-listing-v2-draft-editor")), null, {
            timeout: 10000,
          })
          .catch(() => {});
        await page.waitForTimeout(400);
      }
    }
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
        const viewportWidth = window.innerWidth;
        const clippedControls = Array.from(section?.querySelectorAll("button, input, textarea, select, summary") || []).filter((control) => {
          if (control.offsetParent === null) return false;
          const rect = control.getBoundingClientRect();
          return rect.width > 0 && (rect.left < -2 || rect.right > viewportWidth + 2);
        });
        return {
          view,
          exists: Boolean(section),
          visible: Boolean(section && section.offsetParent !== null),
          text_length: text.trim().length,
          topbar_style: styleOf("#appShell .main > .topbar"),
          flow_style: styleOf(".global-flow-bar"),
          handoff_style: styleOf(".saas-ceo-module-handoff"),
          horizontal_overflow: document.documentElement.scrollWidth > viewportWidth + 2,
          document_scroll_width: document.documentElement.scrollWidth,
          viewport_width: viewportWidth,
          clipped_control_count: clippedControls.length,
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
          has_listing_draft_editor: sectionHas(".saas-listing-v2-draft-editor"),
          has_listing_draft_state: Boolean(window.state?.saasListingComposerDraft),
          has_listing_source_collapsed_after_draft:
            sectionHas('[data-listing-source-details="listing_source_collapsed_after_draft_v1"]') &&
            !section?.querySelector('[data-listing-source-details="listing_source_collapsed_after_draft_v1"]')?.open,
          has_listing_market_stage: text.includes("市场结论"),
          has_listing_draft_stage: text.includes("Listing 草稿"),
          has_listing_asset_profit_stage: text.includes("素材/利润"),
          has_listing_publish_confirmation_stage: text.includes("发布确认"),
          has_listing_preflight_bridge:
            sectionHas('[data-listing-visible-publish-bridge="listing_visible_publish_bridge_v1"]') &&
            sectionHas('[data-listing-preflight-bridge="listing_preflight_bridge_visible_v1"]') &&
            sectionHas(".saas-listing-preflight-bridge [data-saas-action=\"run-pretest-check\"]") &&
            sectionHas(".saas-listing-preflight-bridge [data-saas-action=\"create-publish-confirmation\"]"),
          listing_preflight_action_count: sectionCount(".saas-listing-preflight-bridge [data-saas-action]"),
          has_listing_publish_flow_collapsed:
            sectionHas('[data-listing-publish-flow-details="publish_intake_collapsed_v1"]') &&
            !section?.querySelector('[data-listing-publish-flow-details="publish_intake_collapsed_v1"]')?.open &&
            sectionHas('[data-listing-publish-flow-details="publish_intake_collapsed_v1"] > summary'),
          has_listing_publish_feedback:
            sectionHas('[data-listing-visible-publish-bridge="listing_visible_publish_bridge_v1"]') &&
            sectionHas('[data-listing-publish-feedback="listing_publish_feedback_visible_v1"]') &&
            sectionHas(".saas-listing-publish-feedback [data-saas-action=\"open-confirm\"]"),
          has_listing_publish_loop:
            sectionHas('[data-listing-publish-loop="listing_publish_loop_v1"]') &&
            sectionCount('[data-listing-publish-loop="listing_publish_loop_v1"] article') >= 4,
          listing_publish_feedback_action_count: sectionCount(".saas-listing-publish-feedback [data-saas-action]"),
          has_listing_internal_copy: /Listing Package|Market Report|数据包|后台证据|后台排查|Backend preflight|backend_preflight|publish_readiness|confirmation_id|local draft|可导入报告|极简开始/.test(text),
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
          has_backend_preflight_waiting_copy: text.includes("系统发布体检") && text.includes("等待创建发布确认单"),
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
          has_media_asset_jobs_panel:
            sectionHas(".saas-media-asset-jobs") &&
            text.includes("素材任务记录") &&
            text.includes("AssetManifest") &&
            text.includes("不会把旧测试图当成真实生成结果"),
          has_media_internal_copy: /官方数据包|Listing Package|数据包可用|等待数据包|确认记录|费用和用量|素材状态拆分|Provider Hub|素材 Provider|素材 brief|后台证据|后台状态|素材清单已回写|流程导入不需要本机路径/.test(text),
          has_bulk_simple_headline: text.includes("先小批量筛，不一键乱铺"),
          has_bulk_import_preview: sectionHas(".bulk-manual-source-intake") && text.includes("预览导入"),
          has_bulk_grouping_copy: text.includes("能试") && text.includes("要补") && text.includes("先不做"),
          has_bulk_one_next_step: text.includes("生成三类候选") && text.includes("只进入预览和草稿"),
          has_bulk_internal_copy: /真实账号批量质检|官方数据包|字段完整度|质检槽位|等待数据包/.test(text),
          has_service_simple_headline: text.includes("客服、物流和售后放在一页"),
          has_service_simple_flow:
            text.includes("今日处理台") &&
            text.includes("当前没有待处理订单") &&
            text.includes("没有真实订单时不显示虚构买家"),
          has_service_first_run_strip:
            sectionHas(".saas-service-first-run-strip") && text.includes("没有订单就保持安静") && text.includes("只引用已知事实"),
          has_service_internal_copy: /官方数据包|Listing Package|等待官方订单|等待官方同步|官方数据可用|客服事实表|Provider Hub|provider|后台排查|后台状态|连接和排查在设置|去设置同步 eBay/.test(text),
          has_confirm_simple_headline: text.includes("只让你处理真正要拍板的事"),
          has_confirm_simple_action_copy: text.includes("这里只做三种选择"),
          has_confirm_decision_v2:
            sectionHas(".saas-confirm-action-model") &&
            text.includes("你没点头前不会执行") &&
            (sectionHas(".runtime-confirm-empty") ||
              (text.includes("点同意后") &&
                text.includes("不会自动付款") &&
                sectionHas(".saas-confirm-card-decision") &&
                sectionHas(".saas-confirm-safety-detail") &&
                sectionHas(".saas-confirm-merchant-brief"))),
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
          has_collapsed_history: Boolean(document.querySelector("#saasAiCeoHistory:not([hidden]), #view-cockpit .saas-ai-ceo-history summary")),
          has_login_overlay: Boolean(document.querySelector(".auth-shell, .saas-login-modal, [data-auth-view]")),
          has_ceo_pending_status: Boolean(document.querySelector("#view-cockpit .saas-ai-ceo-pending-status")),
          visible_ceo_pending_status_count: Array.from(
            document.querySelectorAll("#view-cockpit .saas-ai-ceo-pending-status"),
          ).filter((status) => status.getClientRects().length > 0).length,
          ceo_pending_is_single_thinking_dot: (() => {
            const status = Array.from(
              document.querySelectorAll("#view-cockpit .saas-ai-ceo-pending-status.is-compact"),
            ).find((candidate) => candidate.getClientRects().length > 0);
            const dot = status?.querySelector(":scope > span.saas-ai-ceo-thinking-dot");
            if (!status) return true;
            if (!dot) return false;
            const style = getComputedStyle(dot);
            const rect = dot.getBoundingClientRect();
            return (
              rect.width >= 5 &&
              rect.width <= 18 &&
              Math.abs(rect.width - rect.height) <= 1 &&
              style.borderRadius !== "0px" &&
              style.backgroundColor === "rgb(17, 17, 17)"
            );
          })(),
          has_complex_ceo_pending_preview: Boolean(
            document.querySelector(
              '#view-cockpit #ceoChat .message.ai.is-pending [data-ai-ceo-provisional-answer="quick_then_full_report_v1"]',
            ),
          ),
          ceo_pending_preview_copy: (() => {
            const pending = Array.from(document.querySelectorAll("#view-cockpit #ceoChat .message.ai.is-pending")).slice(-1)[0];
            const preview = pending?.querySelector('[data-ai-ceo-provisional-answer="quick_then_full_report_v1"]');
            if (!preview) return true;
            const previewText = preview.innerText || "";
            return previewText.includes("先短答") && (previewText.includes("完整报告") || previewText.includes("临时方向"));
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
            const billingForbiddenMarkers = [
              "大陆收款方式",
              "大陆用户",
              "个体工商户",
              "个体户",
              "主体资料",
              "聚合收单",
              "支付宝",
              "云闪付",
              "个人码",
              "个人收款码",
              "平台管理员",
              "主理人",
              "上线前检查",
              "支付后台配置",
              "正式商户支付",
              "provider",
              "webhook",
              "quota",
              "Customer Portal",
              "Stripe",
              "测试付款",
              "测试开通",
              "等待演练模式",
              "无扣费演练",
              "审计证据",
              "模型 key",
              "eBay OAuth",
              "BYOK",
              "client secret",
              "provider cutover",
            ];
            const billingForbiddenVisibleMarkers = billingForbiddenMarkers.filter((marker) => text.includes(marker));
            const modelForbiddenMarkers = [
              "provider",
              "BYOK",
              "token",
              "tokens",
              "secret_ref",
              "live adapter",
              "raw provider",
              "FAL",
              "API key",
              "模型 key",
              "Provider Hub",
              "素材 Provider",
              "base_url",
              "webhook",
              "quota",
            ];
            const modelForbiddenVisibleMarkers =
              id === "model" ? modelForbiddenMarkers.filter((marker) => text.includes(marker)) : [];
            const merchantSettingsForbiddenMarkers = [
              "callback",
              "回调地址",
              "OAuth",
              "token",
              "secret_ref",
              "Vault",
              "provider",
              "preflight",
              "packet",
              "BYOK",
              "API key",
              "模型 key",
              "webhook",
              "quota",
              "Customer Portal",
              "Stripe",
              "正式商户支付",
              "上线前检查",
              "技术排查",
              "后台排查",
              "后台证据",
              "后台状态",
            ];
            const merchantSettingsForbiddenVisibleMarkers = ["account", "data", "governance"].includes(id)
              ? merchantSettingsForbiddenMarkers.filter((marker) => text.includes(marker))
              : [];
            const sectionGroups = Array.from(section?.querySelectorAll(".saas-settings-section-group") || []);
            const openSectionGroups = sectionGroups.filter((group) => group.hasAttribute("open"));
            return {
              id,
              has_home_hub: Boolean(section?.querySelector(".saas-settings-home-hub")),
              has_section_group: sectionGroups.length > 0,
              section_group_count: sectionGroups.length,
              open_section_group_count: openSectionGroups.length,
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
              has_billing_plain_summary: (() => {
                const summary = section?.querySelector(
                  '.saas-merchant-billing-plain-summary[data-billing-summary="merchant_billing_plain_summary_v1"]',
                );
                return (
                  Boolean(summary) &&
                  summary.querySelectorAll(".saas-merchant-billing-plain-grid article").length >= 5
                );
              })(),
              has_billing_pricing_split: (() => {
                const split = section?.querySelector(
                  '.saas-merchant-pricing-split[data-billing-split="subscription_ai_media_platform_v1"]',
                );
                return Boolean(split) && split.querySelectorAll(":scope > article").length === 4;
              })(),
              has_billing_continuity:
                Boolean(
                  section?.querySelector(
                    '.saas-merchant-billing-continuity[data-billing-continuity="merchant_subscription_shutdown_closure_v2"]',
                  ),
                ) &&
                rawText.includes("billing_never_deletes_audit_records") &&
                rawText.includes("billing_blocks_metered_work_only") &&
                rawText.includes("no_repeat_oauth_for_billing_recovery") &&
                rawText.includes("no_model_key_reentry_for_billing_recovery") &&
                rawText.includes("triggers_real_charge=false") &&
                rawText.includes("frontend_gets_payment_secret=false"),
              has_billing_internal_payment_ops:
                Boolean(
                  section?.querySelector(
                    '.saas-billing-domain-review[data-billing-domain-cutover-review="stable_domain_checkout_portal_webhook_review_v1"]',
                  ),
                ) &&
                rawText.includes("billing_domain_cutover_review_v1") &&
                rawText.includes("billing_domain_cutover_rehearsal") &&
                rawText.includes("creates_checkout_session=false") &&
                rawText.includes("calls_stripe_api=false") &&
                rawText.includes("triggers_real_charge=false") &&
                rawText.includes("repeat_ebay_oauth_allowed=false") &&
                rawText.includes("frontend_gets_payment_secret=false"),
              has_billing_secondary_group:
                id === "billing" &&
                sectionGroups.length === 1 &&
                rawText.includes("计费与安全说明") &&
                rawText.includes("按需查看"),
              billing_secondary_group_closed: id === "billing" && sectionGroups.length === 1 && openSectionGroups.length === 0,
              billing_secondary_copy_hidden:
                id === "billing" &&
                !text.includes("用量计费路线") &&
                !text.includes("付费前客户信任说明") &&
                !text.includes("续费和停用闭环"),
              governance_roles_collapsed:
                id === "governance" &&
                Boolean(section?.querySelector(".saas-permission-current-role")) &&
                Boolean(section?.querySelector(".saas-permission-role-details:not([open])")),
              has_billing_internal_customer_copy: billingForbiddenVisibleMarkers.length > 0,
              billing_internal_visible_markers: billingForbiddenVisibleMarkers,
              has_model_internal_customer_copy: modelForbiddenVisibleMarkers.length > 0,
              model_internal_visible_markers: modelForbiddenVisibleMarkers,
              has_internal_settings_customer_copy: merchantSettingsForbiddenVisibleMarkers.length > 0,
              internal_settings_visible_markers: merchantSettingsForbiddenVisibleMarkers,
              preview: text.trim().slice(0, 180),
            };
          }, tabId),
        );
      }
      check.settings_child_audit = settingsChildAudit;
      check.settings_children_are_focused = settingsChildAudit.every(
        (item) =>
          !item.has_focus_panel &&
          !item.has_one_glance &&
          item.one_glance_count === 0 &&
          !item.has_one_glance_copy &&
          !item.has_home_hub &&
          (item.id === "billing"
            ? item.section_group_count === 1 && item.open_section_group_count === 0
            : item.section_group_count === 0) &&
          !item.has_subpage_strip,
      );
      const modelAudit = settingsChildAudit.find((item) => item.id === "model") || {};
      const billingAudit = settingsChildAudit.find((item) => item.id === "billing") || {};
      const merchantSettingsInternalAudits = settingsChildAudit.filter((item) => item.has_internal_settings_customer_copy);
      check.settings_model_has_home_hub = modelAudit.has_home_hub || false;
      check.settings_model_has_subpage_strip = modelAudit.has_subpage_strip || false;
      check.settings_model_has_model_panel = modelAudit.has_model_provider_panel || false;
      check.settings_model_has_internal_customer_copy = modelAudit.has_model_internal_customer_copy || false;
      check.settings_model_internal_visible_markers = modelAudit.model_internal_visible_markers || [];
      check.settings_billing_has_current_status = billingAudit.has_billing_current_panel || false;
      check.settings_billing_has_plain_summary = billingAudit.has_billing_plain_summary || false;
      check.settings_billing_has_pricing_split = billingAudit.has_billing_pricing_split || false;
      check.settings_billing_has_continuity = billingAudit.has_billing_continuity || false;
      check.settings_billing_has_secondary_group = billingAudit.has_billing_secondary_group || false;
      check.settings_billing_secondary_group_closed = billingAudit.billing_secondary_group_closed || false;
      check.settings_billing_secondary_copy_hidden = billingAudit.billing_secondary_copy_hidden || false;
      check.settings_governance_roles_collapsed =
        (settingsChildAudit.find((item) => item.id === "governance") || {}).governance_roles_collapsed || false;
      check.settings_billing_has_internal_payment_ops = billingAudit.has_billing_internal_payment_ops || false;
      check.settings_billing_has_internal_customer_copy = billingAudit.has_billing_internal_customer_copy || false;
      check.settings_child_has_internal_customer_copy = merchantSettingsInternalAudits.length > 0;
      check.settings_child_internal_visible_markers = merchantSettingsInternalAudits.map((item) => ({
        id: item.id,
        markers: item.internal_settings_visible_markers || [],
      }));
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
    clientResponses,
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
    if (check.horizontal_overflow) failures.push(`${check.view} horizontal overflow ${check.document_scroll_width}/${check.viewport_width}`);
    if (check.clipped_control_count) failures.push(`${check.view} clipped controls ${check.clipped_control_count}`);
  }
  const product = moduleChecks.find((item) => item.view === "product") || {};
  if (!product.has_listing_cplus_stack || !product.has_listing_input_panel) failures.push("product C+ listing input surface missing");
  if (!product.has_listing_ai_handoff || !product.has_listing_ai_handoff_input) failures.push("product AI CEO to Listing handoff missing");
  if (!product.has_listing_source_grid) failures.push("product Listing source choices missing");
  if (!product.has_listing_draft_editor && !product.has_listing_first_run_strip) failures.push("product first-run assurance strip missing");
  if (!product.has_listing_draft_editor && !product.has_listing_workflow_action) failures.push("product C+ listing backend workflow action missing");
  if (product.has_listing_draft_editor && !product.has_listing_source_collapsed_after_draft) {
    failures.push("product existing draft must collapse raw source intake by default");
  }
  if (!product.has_listing_market_stage || !product.has_listing_draft_stage) failures.push("product C+ market-to-draft flow missing");
  if (!product.has_listing_asset_profit_stage || !product.has_listing_publish_confirmation_stage) {
    failures.push("product C+ asset/profit or publish confirmation stage missing");
  }
  if (product.listing_preflight_action_count < 2) failures.push("product Listing draft is missing publish-preparation actions");
  if (!product.has_listing_publish_loop) {
    failures.push("product Listing publish confirmation loop missing");
  }
  if (!product.has_listing_publish_flow_collapsed) {
    failures.push("product publish intake form should stay collapsed until the merchant needs fields");
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
  if (!connect.settings_children_are_focused) failures.push("ordinary settings child tabs still contain redundant summary/map panels");
  if (connect.settings_model_has_home_hub) failures.push("settings child page repeats overview map");
  if (connect.settings_model_has_subpage_strip) failures.push("settings child page still shows redundant intro/map");
  if (!connect.settings_model_has_model_panel) failures.push("settings child page content missing");
  if (connect.settings_model_has_internal_customer_copy) failures.push("ordinary settings model tab exposes internal model/media copy");
  if (connect.settings_child_has_internal_customer_copy) failures.push("ordinary settings child tab exposes internal account/data/governance copy");
  if (connect.settings_billing_has_current_status) failures.push("settings billing tab still shows duplicate current status panel");
  if (!connect.settings_billing_has_plain_summary) failures.push("settings billing plain summary missing");
  if (!connect.settings_billing_has_pricing_split) failures.push("settings billing pricing split missing");
  if (!connect.settings_billing_has_continuity) failures.push("settings billing continuity closure missing");
  if (!connect.settings_billing_has_secondary_group || !connect.settings_billing_secondary_group_closed) {
    failures.push("settings billing secondary explanation group must stay collapsed by default");
  }
  if (!connect.settings_billing_secondary_copy_hidden) failures.push("settings billing secondary copy is visible before expansion");
  if (!connect.settings_governance_roles_collapsed) failures.push("settings governance full role catalogue must stay collapsed by default");
  if (connect.settings_billing_has_internal_payment_ops) failures.push("ordinary settings billing tab exposes internal payment cutover review");
  if (connect.settings_billing_has_internal_customer_copy) failures.push("ordinary settings billing tab exposes internal/founder payment strategy copy");
  const media = moduleChecks.find((item) => item.view === "media") || {};
  if (!media.has_media_tabs) failures.push("media tabs missing");
  if (!media.has_media_simple_headline || !media.has_media_simple_flow) failures.push("media simple workflow surface missing");
  if (!media.has_media_first_run_strip) failures.push("media first-run assurance strip missing");
  if (!media.has_media_asset_jobs_panel) failures.push("media asset job manifest panel missing");
  if (media.has_media_internal_copy) failures.push("media daily surface exposes internal evidence/provider copy");
  const bulk = moduleChecks.find((item) => item.view === "bulk") || {};
  if (!bulk.has_bulk_simple_headline || !bulk.has_bulk_import_preview || !bulk.has_bulk_grouping_copy) {
    failures.push("bulk simple grouping surface missing");
  }
  if (!bulk.has_bulk_one_next_step) failures.push("bulk one-next-step empty state missing");
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
    !ceoFirstRunEntry.has_first_day_path ||
    ceoFirstRunEntry.first_day_path_step_count !== 3 ||
    !ceoFirstRunEntry.has_first_day_path_copy ||
    !ceoFirstRunEntry.has_one_task_focus ||
    ceoFirstRunEntry.one_task_focus_card_count !== 3 ||
    ceoFirstRunEntry.one_task_focus_prompt_count !== 3 ||
    !ceoFirstRunEntry.has_one_task_focus_copy ||
    !ceoFirstRunEntry.has_first_run_handoff_copy ||
    ceoFirstRunEntry.first_run_handoff_action_count < 3
  ) {
    failures.push("AI CEO first-run entry is not a low-learning-cost one-sentence composer");
  }
  if (!ceoFirstRunPrefill.ok || !ceoFirstRunPrefill.still_no_route_card || !ceoFirstRunPrefill.still_no_chat_message) {
    failures.push("AI CEO first-run handoff prompts must only prefill the composer");
  }
  if (!ceoFirstRunFocusPrefill.ok || !ceoFirstRunFocusPrefill.still_no_route_card || !ceoFirstRunFocusPrefill.still_no_chat_message) {
    failures.push("AI CEO first-run focus cards must only prefill the composer");
  }
  if (ceoFirstRunEntry.has_starter_prompts || ceoFirstRunEntry.has_route_card) {
    failures.push("AI CEO first-run entry still exposes starter prompts or a route card before user intent");
  }
  if (ceoFirstRunEntry.feedback_overlaps_send) {
    failures.push("workflow feedback toggle overlaps the AI CEO send button");
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
  if (!ceoRouteTask.has_v2_marker || !ceoRouteTask.has_why_rows || !ceoRouteTask.has_simple_copy || !ceoRouteTask.has_next_step_copy) {
    failures.push("AI CEO routing task card copy missing");
  }
  for (const scenario of ceoRouteScenarios) {
    if (
      !scenario.visible ||
      scenario.target !== scenario.expected ||
      !scenario.has_v2_marker ||
      !scenario.has_why_rows ||
      !scenario.has_simple_copy ||
      !scenario.has_next_step_copy
    ) {
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
  if (!cockpit.ceo_pending_is_single_thinking_dot) {
    failures.push("AI CEO pending state is not the single compact thinking dot");
  }
  if (cockpit.visible_ceo_pending_status_count > 1) {
    failures.push(`AI CEO shows ${cockpit.visible_ceo_pending_status_count} simultaneous waiting indicators`);
  }
  if (cockpit.has_complex_ceo_pending_preview) {
    failures.push("AI CEO pending state still exposes the old complex waiting card");
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
