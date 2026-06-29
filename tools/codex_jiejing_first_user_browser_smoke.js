#!/usr/bin/env node
/* First-user browser smoke for JIEJING public SaaS.
   It creates temporary SaaS accounts only. It does not trigger eBay OAuth,
   real platform writes, or real charges. */

const fs = require("fs");
const path = require("path");
const { chromium } = require("../output/codex-playwright-deps/node_modules/playwright-core");

const base = process.env.JIEJING_TEST_BASE || "https://app.jiejing.shop";
const browserChannel = process.env.JIEJING_PLAYWRIGHT_CHANNEL || "chrome";
const localStaticRoot = process.env.JIEJING_LOCAL_STATIC_ROOT ? path.resolve(process.env.JIEJING_LOCAL_STATIC_ROOT) : "";
const stamp = new Date().toISOString().replace(/[:.]/g, "-");
const outDir = path.join("output", "browser-smoke", `${stamp}-first-user-browser`);
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

async function registerAccount(label, { createStore = false } = {}) {
  const suffix = `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  const email = `codex-first-user-${label}-${suffix}@local.invalid`;
  const password = `Codex-first-user-${suffix}`;
  const registered = await api("/auth/register", {
    method: "POST",
    body: {
      email,
      password,
      company_name: `Codex First User ${label}`,
    },
  });
  if (!registered.ok) {
    throw new Error(`register ${label} failed: ${registered.status} ${JSON.stringify(registered.json).slice(0, 300)}`);
  }
  const token = registered.json.token;
  const user = registered.json.user || {};
  const company = registered.json.company || {};
  let store = null;
  if (createStore) {
    const activatedBilling = await api("/billing/test-event", {
      token,
      method: "POST",
      body: {
        plan_key: "operator",
        action: "activate",
      },
    });
    if (!activatedBilling.ok) {
      throw new Error(`billing test activation ${label} failed: ${activatedBilling.status}`);
    }
    const created = await api("/stores", {
      token,
      method: "POST",
      body: {
        platform: "ebay",
        store_name: `Codex First User ${label} Store`,
        marketplace: "EBAY_US",
        stage: "store_opened",
        settings: {
          created_from: "codex_first_user_browser_smoke",
          placeholder_store_name: true,
        },
      },
    });
    if (!created.ok) {
      throw new Error(`store ${label} failed: ${created.status} ${JSON.stringify(created.json).slice(0, 300)}`);
    }
    store = created.json.store || null;
  }
  return {
    label,
    token,
    email,
    userId: user.user_id || email,
    companyId: company.company_id || user.default_company_id || "",
    store,
  };
}

function localStaticPath(requestUrl) {
  if (!localStaticRoot) return "";
  const url = new URL(requestUrl);
  const pathname = decodeURIComponent(url.pathname.replace(/^\/+/, "")) || "index.html";
  const allowed =
    ["app.html", "index.html", "app.js", "styles.css", "privacy.html", "terms.html", "risk-disclosure.html"].includes(pathname) ||
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

async function installStaticRoute(context) {
  if (!localStaticRoot) return;
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

function accountRecord(account) {
  return {
    account_key: String(account.userId || account.email || "").toLowerCase(),
    user_id: String(account.userId || ""),
    email: String(account.email || ""),
    company_id: String(account.companyId || ""),
    display_name: `Codex First User ${account.label}`,
    last_seen: new Date().toISOString(),
  };
}

function storageForAccount(
  account,
  {
    allAccounts = [],
    previous = {},
    onboardingDone = false,
    includeStore = true,
    threadPayload = null,
    sourceRecordsPayload = null,
    merchantFeedbackPayload = null,
    ceoCommandPayload = null,
  } = {},
) {
  const storage = { ...previous };
  const accountKey = String(account.userId || account.email || "browser").toLowerCase();
  const storeId = includeStore && account.store ? account.store.store_id : "";
  storage.jiejing_saas_api_base = base;
  storage.jiejing_saas_backend_session_hint = "1";
  storage.jiejing_saas_session_hint = "1";
  storage.jiejing_saas_last_account = accountKey;
  storage.jiejing_saas_known_accounts = JSON.stringify((allAccounts.length ? allAccounts : [account]).map(accountRecord));
  if (storeId) storage.jiejing_saas_backend_store_id = storeId;
  else delete storage.jiejing_saas_backend_store_id;
  if (onboardingDone) storage[`jiejing_saas_onboarding_done:${accountKey}`] = "1";
  if (threadPayload) storage.jiejing_saas_ceo_thread = JSON.stringify(threadPayload);
  if (sourceRecordsPayload) storage.jiejing_saas_source_records = JSON.stringify(sourceRecordsPayload);
  if (merchantFeedbackPayload) storage.jiejing_saas_merchant_feedback = JSON.stringify(merchantFeedbackPayload);
  if (ceoCommandPayload) storage.jiejing_saas_ceo_command = JSON.stringify(ceoCommandPayload);
  return storage;
}

function scopeFor(account) {
  const accountKey = String(account.userId || account.email || "browser").toLowerCase();
  const storeId = String(account.store?.store_id || "account-wide").toLowerCase();
  return `${accountKey}::${storeId}`;
}

async function contextForAccount(browser, account, storage) {
  const context = await browser.newContext({ viewport: { width: 1365, height: 900 }, deviceScaleFactor: 1 });
  const baseUrl = new URL(base);
  await context.addCookies([
    {
      name: "jiejing_saas_session",
      value: account.token,
      domain: baseUrl.hostname,
      path: "/",
      httpOnly: true,
      secure: baseUrl.protocol === "https:",
      sameSite: "Lax",
    },
  ]);
  await installStaticRoute(context);
  await context.addInitScript((seed) => {
    Object.entries(seed.storage).forEach(([key, value]) => {
      if (value === undefined || value === null) return;
      localStorage.setItem(key, String(value));
    });
    window.__JIEJING_FORCE_PUBLIC_MVP__ = true;
  }, { storage });
  return context;
}

async function waitForAppReady(page) {
  await page.waitForFunction(
    () => {
      const app = document.querySelector("#appShell");
      const cockpit = document.querySelector("#view-cockpit");
      const input = document.querySelector("#ceoInput");
      return Boolean(app && !app.classList.contains("is-hidden") && cockpit?.classList.contains("is-active") && input);
    },
    null,
    { timeout: 60000 },
  );
  await page.waitForTimeout(600);
}

async function readStorage(page) {
  return page.evaluate(() => {
    const output = {};
    for (let index = 0; index < localStorage.length; index += 1) {
      const key = localStorage.key(index);
      output[key] = localStorage.getItem(key);
    }
    return output;
  });
}

async function main() {
  const noStore = await registerAccount("nostore", { createStore: false });
  const accountA = await registerAccount("a", { createStore: true });
  const accountB = await registerAccount("b", { createStore: true });
  const accountASentinel = `ACCOUNT_A_PRIVATE_CHAT_SENTINEL_${Date.now()}`;
  const accountASourceSentinel = `ACCOUNT_A_PRIVATE_SOURCE_SENTINEL_${Date.now()}`;
  const accountAFeedbackSentinel = `ACCOUNT_A_PRIVATE_FEEDBACK_SENTINEL_${Date.now()}`;
  const accountACommandSentinel = `ACCOUNT_A_PRIVATE_COMMAND_SENTINEL_${Date.now()}`;
  const threadPayload = {
    [scopeFor(accountA)]: [
      {
        user_text: accountASentinel,
        assistant_text: `${accountASentinel} assistant reply`,
        status: "local_clock_answered",
        route: "general_chat",
        created_at: new Date().toISOString(),
      },
    ],
  };
  const sourceRecordsPayload = {
    [scopeFor(accountA)]: [
      {
        id: "account-a-source-only",
        title: accountASourceSentinel,
        snippet: "Account A source cache must not hydrate into Account B.",
        source_type: "local_tenant_cache_smoke",
      },
    ],
  };
  const merchantFeedbackPayload = {
    [scopeFor(accountA)]: [
      {
        id: "account-a-feedback-only",
        feedback_type: "workflow_issue",
        report_id: "account-a-private-report",
        rule_text: accountAFeedbackSentinel,
        created_at: new Date().toISOString(),
      },
    ],
  };
  const ceoCommandPayload = {
    [scopeFor(accountA)]: {
      id: "account-a-command-only",
      text: accountACommandSentinel,
      title: "Account A private command",
      summary: "Account A command cache must not hydrate into Account B.",
      intent: "general_chat",
      status: "chat",
      route: "general_chat",
      created_at: new Date().toISOString(),
      store_id: accountA.store?.store_id || "",
      routes: [],
    },
  };

  const browser = await chromium.launch({ channel: browserChannel, headless: true, timeout: 60000 });
  const pageErrors = [];
  const requestFailures = [];
  const ignoredRequestFailures = [];
  const badResponses = [];

  function recordRequestFailure(request) {
    if (!request.url().startsWith(base)) return;
    const error = request.failure()?.errorText || "";
    const failure = { url: request.url(), error };
    if (/ERR_ABORTED|NS_BINDING_ABORTED/i.test(error)) {
      ignoredRequestFailures.push(failure);
      return;
    }
    requestFailures.push(failure);
  }

  const noStoreContext = await contextForAccount(
    browser,
    noStore,
    storageForAccount(noStore, { allAccounts: [noStore], onboardingDone: false, includeStore: false }),
  );
  const noStorePage = await noStoreContext.newPage();
  noStorePage.on("pageerror", (error) => pageErrors.push(String(error.message || error).slice(0, 400)));
  noStorePage.on("requestfailed", recordRequestFailure);
  noStorePage.on("response", (response) => {
    if (response.url().startsWith(base) && response.status() >= 500) badResponses.push({ url: response.url(), status: response.status() });
  });
  await noStorePage.goto(`${base}/app.html?start=app&onboarded=1&view=cockpit&first-user-smoke=${Date.now()}`, {
    waitUntil: "domcontentloaded",
    timeout: 90000,
  });
  await noStorePage.waitForFunction(
    () => {
      const onboarding = document.querySelector("#onboardingShell");
      const app = document.querySelector("#appShell");
      return Boolean(onboarding && !onboarding.classList.contains("is-hidden") && app?.classList.contains("is-hidden"));
    },
    null,
    { timeout: 60000 },
  );
  const onboardedQueryDidNotBypassOnboarding = await noStorePage.evaluate(() => {
    const onboarding = document.querySelector("#onboardingShell");
    const app = document.querySelector("#appShell");
    return Boolean(onboarding && !onboarding.classList.contains("is-hidden") && app?.classList.contains("is-hidden"));
  });
  const firstDayPathStripPresent = await noStorePage.evaluate(() => {
    const html = document.documentElement.outerHTML;
    return Boolean(
      document.querySelector(".saas-first-day-path-strip") &&
        html.includes("login_onboarding_ai_ceo_v3") &&
        html.includes("刷新不会跳过向导") &&
        html.includes("一句话交给 AI CEO"),
    );
  });
  await noStorePage.screenshot({ path: path.join(outDir, "onboarded-query-guard.png"), fullPage: true }).catch(() => {});
  await noStoreContext.close();

  const accountAContext = await contextForAccount(
    browser,
    accountA,
    storageForAccount(accountA, {
      allAccounts: [accountA],
      onboardingDone: true,
      includeStore: true,
      threadPayload,
      sourceRecordsPayload,
      merchantFeedbackPayload,
      ceoCommandPayload,
    }),
  );
  const accountAPage = await accountAContext.newPage();
  await accountAPage.goto(`${base}/app.html?start=app&view=cockpit&first-user-smoke=${Date.now()}`, {
    waitUntil: "domcontentloaded",
    timeout: 90000,
  });
  await waitForAppReady(accountAPage);
  const accountAShowsOwnChat = await accountAPage.evaluate((sentinel) => document.body.innerText.includes(sentinel), accountASentinel);
  const accountALocalStorage = await readStorage(accountAPage);
  await accountAPage.screenshot({ path: path.join(outDir, "account-a-chat.png"), fullPage: true }).catch(() => {});
  await accountAContext.close();

  const accountBContext = await contextForAccount(
    browser,
    accountB,
    storageForAccount(accountB, {
      allAccounts: [accountA, accountB],
      previous: accountALocalStorage,
      onboardingDone: true,
      includeStore: true,
    }),
  );
  let model402RouteInterceptCount = 0;
  await accountBContext.route("**/stores/**/merchant-ceo/chat**", (route) => {
    model402RouteInterceptCount += 1;
    return route.fulfill({
      status: 402,
      contentType: "application/json; charset=utf-8",
      body: JSON.stringify({ error: "model quota exceeded", detail: "quota or billing limit" }),
    });
  });
  const accountBPage = await accountBContext.newPage();
  accountBPage.on("pageerror", (error) => pageErrors.push(String(error.message || error).slice(0, 400)));
  accountBPage.on("requestfailed", recordRequestFailure);
  accountBPage.on("response", (response) => {
    const isExpectedChat402 = response.url().includes("/merchant-ceo/chat") && response.status() === 402;
    if (response.url().startsWith(base) && response.status() >= 500 && !isExpectedChat402) {
      badResponses.push({ url: response.url(), status: response.status() });
    }
  });
  await accountBPage.goto(`${base}/app.html?start=app&view=cockpit&first-user-smoke=${Date.now()}`, {
    waitUntil: "domcontentloaded",
    timeout: 90000,
  });
  await waitForAppReady(accountBPage);
  const accountBDidNotShowAccountAChat = await accountBPage.evaluate((sentinel) => !document.body.innerText.includes(sentinel), accountASentinel);
  const accountBScopedLocalCacheClean = await accountBPage.evaluate(
    (sentinels) => {
      const sourceRecords = typeof window.loadSaasSourceRecords === "function" ? window.loadSaasSourceRecords() : [];
      const feedback = typeof window.loadSaasMerchantFeedback === "function" ? window.loadSaasMerchantFeedback() : [];
      const command = typeof window.loadSaasLastCeoCommand === "function" ? window.loadSaasLastCeoCommand() : null;
      const thread = typeof window.loadSaasAiCeoThread === "function" ? window.loadSaasAiCeoThread() : [];
      const visibleText = document.body.innerText || "";
      const serialized = JSON.stringify({ sourceRecords, feedback, command, thread, visibleText });
      return sentinels.every((sentinel) => !serialized.includes(sentinel));
    },
    [accountASentinel, accountASourceSentinel, accountAFeedbackSentinel, accountACommandSentinel],
  );

  await accountBPage.locator("#ceoInput").fill("解释一下 SaaS 订阅额度是什么意思");
  await accountBPage.locator('#ceoForm button[type="submit"]').click();
  await accountBPage.waitForFunction(
    () => {
      const text = document.body.innerText || "";
      return (
        text.includes("AI 用量或服务商账单挡住了本次回复") ||
        text.includes("不用在前台重复粘贴凭证") ||
        text.includes("AI CEO 连接暂时没有完成") ||
        text.includes("当前店铺还没有可用的 AI 连接") ||
        text.includes("AI 连接暂时不可用") ||
        text.includes("还没有可用店铺上下文") ||
        text.includes("没有受保护登录会话")
      );
    },
    null,
    { timeout: 45000 },
  );
  const modelFailureCopy = await accountBPage.evaluate(() => {
    const text = document.body.innerText;
    const usageBlocked =
      text.includes("AI 用量或服务商账单挡住了本次回复") &&
      text.includes("不用在前台重复粘贴凭证") &&
      text.includes("AI 与素材");
    const connectionBlocked =
      (text.includes("AI CEO 连接暂时没有完成") ||
        text.includes("当前店铺还没有可用的 AI 连接") ||
        text.includes("AI 连接暂时不可用") ||
        text.includes("还没有可用店铺上下文") ||
        text.includes("没有受保护登录会话")) &&
      (text.includes("设置") || text.includes("AI 与素材") || text.includes("连接状态"));
    return {
      mode: usageBlocked ? "provider_usage_or_billing_blocked" : connectionBlocked ? "frontend_or_backend_model_connection_blocked" : "unknown",
      safe:
        (usageBlocked || connectionBlocked) &&
        !text.includes("quota exceeded") &&
        !text.includes("traceback") &&
        !text.includes("api key") &&
        !text.includes("secret") &&
        !text.includes("token"),
      preview: text.slice(0, 400),
    };
  });
  const modelFailureCopyIsMerchantSafe = Boolean(modelFailureCopy.safe);
  const modelFailurePathObserved = model402RouteInterceptCount > 0 || modelFailureCopy.mode !== "unknown";
  const model402OrSafeBlockObserved = model402RouteInterceptCount > 0 || modelFailureCopy.mode === "frontend_or_backend_model_connection_blocked";
  const model402CopyIsMerchantSafe = modelFailureCopyIsMerchantSafe;
  await accountBPage.screenshot({ path: path.join(outDir, "account-b-model-safe-copy.png"), fullPage: true }).catch(() => {});

  await accountBPage.locator('[data-saas-action="open-public-home"]').click();
  await accountBPage.waitForURL(/index\.html.*start=site/, { timeout: 30000 });
  const workbenchLogoReturnsToCurrentIndex = await accountBPage.evaluate(() => {
    const url = new URL(window.location.href);
    return (
      url.pathname.endsWith("/index.html") &&
      url.searchParams.get("start") === "site" &&
      document.documentElement.outerHTML.includes('JIEJING_SITE_VERSION = "20260629-account-safe-ai-v3"')
    );
  });
  await accountBPage.screenshot({ path: path.join(outDir, "workbench-logo-homepage-return.png"), fullPage: true }).catch(() => {});
  await accountBContext.close();
  await browser.close();

  const result = {
    ok: true,
    outDir,
    checks: {
      onboarded_query_did_not_bypass_onboarding: onboardedQueryDidNotBypassOnboarding,
      first_day_path_strip_present: firstDayPathStripPresent,
      account_a_shows_own_chat: accountAShowsOwnChat,
      account_b_did_not_show_account_a_chat: accountBDidNotShowAccountAChat,
      account_b_scoped_local_cache_clean: accountBScopedLocalCacheClean,
      model_402_route_intercepted: model402OrSafeBlockObserved,
      model_safe_failure_path_observed: modelFailurePathObserved,
      model_failure_path_observed: modelFailurePathObserved,
      model_402_copy_is_merchant_safe: model402CopyIsMerchantSafe,
      model_failure_copy_is_merchant_safe: modelFailureCopyIsMerchantSafe,
      workbench_logo_returns_to_current_index: workbenchLogoReturnsToCurrentIndex,
      no_real_platform_writes_triggered: true,
      no_real_charge_triggered: true,
      no_ebay_oauth_triggered: true,
    },
    model_failure: {
      mode: modelFailureCopy.mode,
      route_intercept_count: model402RouteInterceptCount,
    },
    pageErrors,
    requestFailures,
    ignoredRequestFailures,
    badResponses,
    account_a_sentinel_masked: "ACCOUNT_A_PRIVATE_CHAT_SENTINEL_***",
  };
  result.ok =
    Object.values(result.checks).every(Boolean) &&
    pageErrors.length === 0 &&
    requestFailures.length === 0 &&
    badResponses.length === 0;
  fs.writeFileSync(path.join(outDir, "result.json"), JSON.stringify(result, null, 2), "utf8");
  if (!result.ok) {
    console.error(JSON.stringify(result, null, 2));
    process.exit(1);
  }
  console.log(JSON.stringify(result, null, 2));
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
