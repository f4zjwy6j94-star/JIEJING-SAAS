#!/usr/bin/env node
"use strict";

const fs = require("fs");
const http = require("http");
const os = require("os");
const path = require("path");
const { chromium } = require("../output/codex-playwright-deps/node_modules/playwright-core");

const ROOT = path.resolve(__dirname, "..");
const OUT = process.env.JIEJING_OPERATIONS_SMOKE_OUT || path.join(os.tmpdir(), "jiejing-operations-console-browser-smoke");
const STATIC_FILES = new Set([
  "ops.html",
  "ops.css",
  "ops.js",
  "assets/jiejing-logo-mark.svg",
  "assets/jiejing-app-icon.svg",
]);

function overviewFixture(days, feedbackStatus = "open") {
  const today = new Date();
  const daily = Array.from({ length: days }, (_, index) => {
    const date = new Date(today);
    date.setUTCDate(today.getUTCDate() - (days - index - 1));
    return {
      day: date.toISOString().slice(0, 10),
      visitors: index % 6 === 0 ? 0 : 3 + (index % 9),
      sessions: 5 + (index % 11),
      page_views: 12 + index,
      pricing_views: index % 4,
      signup_started: index % 3,
      signup_completed: index % 5 === 0 ? 1 : 0,
    };
  });
  return {
    contract_version: "2026-07-15-platform-operations-overview-v9",
    audience: "platform_internal_admin",
    period: { days, started_at: daily[0].day },
    accounts: { registered_users: 28, merchant_companies: 24, stores_created: 17, connected_stores: 9, team_members: 31, active_merchant_companies: 14 },
    subscriptions: [{ plan_key: "starter", status: "active", count: 6 }, { plan_key: "growth", status: "active", count: 3 }],
    domestic_payments: [{ status: "paid", count: 9, amount_minor: 137100, currency: "CNY" }],
    tasks: { completed: 183, failed: 7, running: 4 },
    product_feedback: {
      total: 2,
      open: 1 + (feedbackStatus === "open" ? 1 : 0),
      reviewing: feedbackStatus === "reviewing" ? 1 : 0,
      resolved: feedbackStatus === "resolved" ? 1 : 0,
      by_module: { workflow: 1, media: 1 },
      by_reason: { unclear: 1, wrong_result: 1 },
      oldest_open_age_seconds: feedbackStatus === "open" ? 3600 : null,
    },
    media_points: { account_count: 12, balance_points: 6820, reserved_points: 240, lifetime_granted_points: 12000, lifetime_spent_points: 4940 },
    traffic_analytics: {
      status: "instrumented",
      event_count: 1120,
      visitors: 346,
      sessions: 508,
      page_views: 1048,
      pricing_views: 88,
      signup_started: 41,
      signup_completed: 24,
      signup_completed_visitors: 22,
      visitor_to_signup_percent: 6.36,
      daily_trend: daily,
      page_breakdown: [
        { page_key: "landing", visitors: 346, sessions: 508, page_views: 782, signup_completed: 0 },
        { page_key: "pricing", visitors: 94, sessions: 103, page_views: 126, signup_completed: 0 },
        { page_key: "register", visitors: 47, sessions: 52, page_views: 64, signup_completed: 24 },
      ],
      automated_browser_collection_enabled: false,
      raw_ip_stored: false,
      user_agent_stored: false,
    },
    performance_analytics: { sample_count: 126, status: "instrumented" },
    provider_reliability_analytics: {
      model: { status: "instrumented", request_count: 214, success_count: 207, timeout_count: 3, p75_duration_ms: 25202 },
      public_search: { status: "instrumented", request_count: 96, success_count: 90, timeout_count: 2, p75_duration_ms: 980 },
      media_generation: { status: "instrumented", request_count: 38, success_count: 35, timeout_count: 1, p75_duration_ms: 12400 },
      payment: { status: "instrumented", request_count: 18, success_count: 18, timeout_count: 0, p75_duration_ms: 620 },
      alerts: {
        critical_count: 0,
        attention_count: 1,
        items: [
          {
            scope: "model",
            status: "attention",
            request_count: 214,
            p75_duration_ms: 25202,
            failure_rate_percent: 3.27,
            timeout_rate_percent: 1.4,
            reason_codes: ["high_latency", "ops-reliability-reason-sentinel"],
            action_key: "review_model_routing_and_timeout",
            raw_error: "ops-reliability-secret-sentinel",
          },
        ],
      },
    },
    model_cost_analytics: { current_metering_health: "ready" },
    unit_economics: {
      status: "partial",
      paid_order_count: 9,
      paid_company_count: 8,
      paid_revenue_minor: 137100,
      active_subscriber_company_count: 9,
      normalized_mrr_minor: 137100,
      mrr_status: "ready",
      mrr_missing_order_count: 0,
      platform_model_cost_minor: 12840,
      total_provider_cost_minor: 22860,
      contribution_margin_minor: null,
      cost_coverage_complete: false,
      current_unmetered_model_tasks: 0,
      unknown_provider_cost_records: 2,
    },
    data_quality: { scope: "merchant_accounts_and_commercial_transactions", synthetic_test_accounts_excluded: 5, synthetic_test_feedback_excluded: 2, acceptance_orders_excluded: 2 },
    merchant_navigation_visible: false,
    frontend_gets_secret: false,
    secret_exposed: false,
  };
}

function detailFixture(section, days, feedbackStatus = "open") {
  const common = { contract_version: "2026-07-15-platform-operations-detail-v1", section, period: { days }, filters: {}, next_cursor: "", has_more: false, merchant_content_exposed: false, provider_neutral: true, secret_exposed: false };
  const items = {
    traffic: overviewFixture(days).traffic_analytics.page_breakdown,
    merchants: [
      { company_ref: "6f31c281d5b0", company_name: '<img src=x onerror="window.__opsXss=1">', email_masked: "zh******@example.cn", account_status: "active", plan_key: "starter", subscription_status: "active", entitlement_active: true, store_count: 2, registered_at: "2026-07-01T08:00:00Z", last_active_at: "2026-07-15T02:10:00Z" },
      { company_ref: "b63d9211a027", company_name: "北方家居选品工作室", email_masked: "li*****@example.cn", account_status: "active", plan_key: "free", subscription_status: "none", entitlement_active: false, store_count: 0, registered_at: "2026-07-10T08:00:00Z", last_active_at: "2026-07-14T06:30:00Z" },
    ],
    transactions: [
      { transaction_ref: "8a9c76ec3d50", company_ref: "6f31c281d5b0", kind: "subscription", plan_key: "starter", status: "paid", amount_minor: 9900, currency: "CNY", payment_channel: "domestic_payment", created_at: "2026-07-14T08:00:00Z" },
      { transaction_ref: "30ff72aebd1c", company_ref: "a7d83b68b552", kind: "media_credit", plan_key: "media_credit_100", status: "refund_review_requested", amount_minor: 3900, currency: "CNY", payment_channel: "domestic_payment", created_at: "2026-07-13T08:00:00Z" },
    ],
    costs: [
      { cost_ref: "0f2a3d64ab12", company_ref: "6f31c281d5b0", category: "model", resource_type: "text_model", usage_owner: "merchant_account_byok", units: 8, total_tokens: 18540, cost_minor: 0, currency: "CNY", cost_status: "not_applicable", created_at: "2026-07-15T01:00:00Z" },
      { cost_ref: "7f42a80ce998", company_ref: "6f31c281d5b0", category: "media_generation", resource_type: "image", units: 4, media_points: 48, cost_minor: 620, currency: "CNY", cost_status: "actual", created_at: "2026-07-14T01:00:00Z" },
    ],
    workflows: [
      { task_ref: "4eb992fdd123", company_ref: "6f31c281d5b0", module: "merchant_ceo_market_research", status: "completed", job_count: 3, attempt_count: 3, created_at: "2026-07-15T00:00:00Z", updated_at: "2026-07-15T00:03:00Z" },
      { task_ref: "95eabf40d273", company_ref: "b63d9211a027", module: "media_asset_generation", status: "failed", job_count: 1, attempt_count: 2, created_at: "2026-07-14T00:00:00Z", updated_at: "2026-07-14T00:02:00Z" },
    ],
    audit: [
      { audit_ref: "11ee5873a0cc", company_ref: "6f31c281d5b0", actor_type: "user", action_type: "billing.order.paid", target_type: "billing_order", result: "recorded", created_at: "2026-07-14T08:02:00Z" },
      { audit_ref: "f7c2d100e91a", company_ref: "6f31c281d5b0", actor_type: "system", action_type: "media.job.failed", target_type: "media_job", result: "failed", created_at: "2026-07-14T07:00:00Z" },
    ],
    feedback: [
      { feedback_id: "feedback_ops_smoke_001", module_key: "workflow", reason: "unclear", status: feedbackStatus, stage_title: "确认经营步骤", detail: "这里的下一步不够清楚。", created_at: "2026-08-03T06:00:00Z", updated_at: "2026-08-03T06:00:00Z", resolved_at: feedbackStatus === "resolved" ? "2026-08-03T06:10:00Z" : "" },
      { feedback_id: "feedback_ops_smoke_xss", module_key: "media", reason: "wrong_result", status: "open", stage_title: '<img src=x onerror="window.__opsFeedbackXss=1">', detail: '<script>window.__opsFeedbackXss=1</script>', created_at: "2026-08-03T05:00:00Z", updated_at: "2026-08-03T05:00:00Z", resolved_at: "" },
    ],
  };
  if (section === "traffic") return { ...common, summary: overviewFixture(days).traffic_analytics, performance: overviewFixture(days).performance_analytics, items: items.traffic };
  if (section === "feedback") return { ...common, raw_merchant_content_exposed: false, sanitized_feedback_text_internal_only: true, items: items.feedback };
  return { ...common, items: items[section] || [] };
}

function startServer() {
  const server = http.createServer((request, response) => {
    const pathname = decodeURIComponent(new URL(request.url, "http://127.0.0.1").pathname).replace(/^\/+/, "") || "ops.html";
    if (!STATIC_FILES.has(pathname)) { response.writeHead(404); response.end("Not found"); return; }
    const file = path.join(ROOT, pathname);
    const ext = path.extname(file).toLowerCase();
    const type = { ".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8", ".js": "application/javascript; charset=utf-8", ".svg": "image/svg+xml" }[ext] || "application/octet-stream";
    response.writeHead(200, { "content-type": type, "cache-control": "no-store" });
    fs.createReadStream(file).pipe(response);
  });
  return new Promise((resolve) => server.listen(0, "127.0.0.1", () => resolve({ server, base: `http://127.0.0.1:${server.address().port}` })));
}

async function runViewport(browser, base, name, viewport) {
  for (const status of ["open", "reviewing", "resolved"]) {
    const feedback = overviewFixture(30, status).product_feedback;
    const lifecycleTotal = Number(feedback.open || 0) + Number(feedback.reviewing || 0) + Number(feedback.resolved || 0);
    const moduleTotal = Object.values(feedback.by_module || {}).reduce((sum, value) => sum + Number(value || 0), 0);
    const reasonTotal = Object.values(feedback.by_reason || {}).reduce((sum, value) => sum + Number(value || 0), 0);
    if (lifecycleTotal !== feedback.total || moduleTotal !== feedback.total || reasonTotal !== feedback.total) {
      throw new Error(`${name}/overview fixture feedback counts are inconsistent for ${status}: ${JSON.stringify(feedback)}`);
    }
  }
  const context = await browser.newContext({ viewport, deviceScaleFactor: 1 });
  const page = await context.newPage();
  const consoleProblems = [];
  const pageErrors = [];
  let expectedConflictConsoleCount = 0;
  let expectedServiceUnavailableConsoleCount = 0;
  page.on("console", (message) => {
    const text = message.text();
    if (message.type() === "error" && text.includes("409 (Conflict)")) {
      expectedConflictConsoleCount += 1;
      return;
    }
    if (message.type() === "error" && text.includes("503 (Service Unavailable)")) {
      expectedServiceUnavailableConsoleCount += 1;
      return;
    }
    if (["error", "warning"].includes(message.type())) consoleProblems.push(`${message.type()}: ${text}`);
  });
  page.on("pageerror", (error) => pageErrors.push(error.message));
  let feedbackStatus = "open";
  let failFirstReview = true;
  let failNextFeedbackFilter = false;
  let failNextFeedbackLoadMore = false;
  let feedbackHasMore = false;
  let overviewRequestCount = 0;
  await page.route("**/permissions/me", (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ role: "owner", platform_internal_admin: true, secret_exposed: false }) }));
  await page.route("**/owner/operations-overview**", (route) => {
    overviewRequestCount += 1;
    const days = Number(new URL(route.request().url()).searchParams.get("period_days") || 30);
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ operations_overview: overviewFixture(days, feedbackStatus) }) });
  });
  await page.route("**/owner/operations/**", (route) => {
    const url = new URL(route.request().url());
    const section = url.pathname.split("/").filter(Boolean).at(-1);
    const days = Number(url.searchParams.get("period_days") || 30);
    const fixture = detailFixture(section, days, feedbackStatus);
    const statusFilter = url.searchParams.get("status");
    const moduleFilter = url.searchParams.get("module");
    if (section === "feedback") {
      if (url.searchParams.has("cursor") && failNextFeedbackLoadMore) {
        failNextFeedbackLoadMore = false;
        return route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ error: "加载更多暂时不可用" }) });
      }
      if (!url.searchParams.has("cursor") && failNextFeedbackFilter) {
        failNextFeedbackFilter = false;
        return route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ error: "反馈筛选暂时不可用" }) });
      }
      fixture.items = fixture.items.filter((item) => (!statusFilter || item.status === statusFilter) && (!moduleFilter || item.module_key === moduleFilter));
      fixture.has_more = feedbackHasMore;
      fixture.next_cursor = feedbackHasMore ? "feedback-cursor-1" : "";
    }
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ operations_detail: fixture }) });
  });
  await page.route("**/owner/product-feedback/review", (route) => {
    if (failFirstReview) {
      failFirstReview = false;
      return route.fulfill({ status: 409, contentType: "application/json", body: JSON.stringify({ error: "反馈状态已由其他运营人员更新" }) });
    }
    feedbackStatus = "reviewing";
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ product_feedback: { feedback_id: "feedback_ops_smoke_001", status: feedbackStatus }, secret_exposed: false }) });
  });
  await page.route("**/owner/product-feedback/resolve", (route) => {
    feedbackStatus = "resolved";
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ product_feedback: { feedback_id: "feedback_ops_smoke_001", status: feedbackStatus }, secret_exposed: false }) });
  });
  await page.goto(`${base}/ops.html`, { waitUntil: "networkidle" });
  await page.waitForSelector("#ops-app:not([hidden])");
  const feedbackMetricText = await page.locator(".ops-metric", { hasText: "待处理反馈" }).innerText();
  for (const expected of ["待处理 2", "处理中 0", "已解决 0", "主要集中：素材工坊"]) {
    if (!feedbackMetricText.includes(expected)) throw new Error(`${name}/overview feedback metric is incomplete: ${feedbackMetricText}`);
  }
  const screenshots = [];
  const views = name === "desktop"
    ? Object.keys({ overview: 1, traffic: 1, merchants: 1, transactions: 1, costs: 1, workflows: 1, feedback: 1, reliability: 1, audit: 1, settings: 1 })
    : name === "mobile"
      ? ["overview", "feedback", "reliability"]
      : ["overview", "transactions", "reliability"];
  for (const view of views) {
    await page.click(`[data-view="${view}"]`);
    await page.waitForFunction((title) => document.querySelector("#ops-title")?.textContent === title, ({ overview: "经营总览", traffic: "流量与转化", merchants: "商家与订阅", transactions: "交易与退款", costs: "AI 与素材成本", workflows: "任务与工作流", feedback: "产品反馈", reliability: "系统可靠性", audit: "安全与审计", settings: "内部设置" })[view]);
    await page.waitForTimeout(60);
    if (view === "reliability") {
      const alertDetail = await page.locator(".ops-reliability-alert-detail").innerText();
      for (const expected of ["告警明细", "模型能力", "关注", "高延迟", "检查模型路由与超时策略", "样本 214"]) {
        if (!alertDetail.includes(expected)) throw new Error(`${name}/reliability alert detail is incomplete: ${alertDetail}`);
      }
      const reliabilityContent = await page.locator("#ops-content").innerText();
      if (["ops-reliability-secret-sentinel", "ops-reliability-reason-sentinel"].some((sentinel) => reliabilityContent.includes(sentinel))) {
        throw new Error(`${name}/reliability alert detail leaked an unapproved backend field`);
      }
    }
    if (view === "feedback") {
      const initialXss = await page.evaluate(() => ({ executed: window.__opsFeedbackXss === 1, injected: Boolean(document.querySelector('img[src="x"]')) }));
      if (initialXss.executed || initialXss.injected) throw new Error(`${name}/feedback XSS boundary failed: ${JSON.stringify(initialXss)}`);
      failNextFeedbackFilter = true;
      await page.locator('[data-filter="status"]').selectOption("open");
      await page.locator("#ops-alert").getByText("反馈筛选暂时不可用", { exact: true }).waitFor();
      await page.waitForFunction(() => document.querySelector("#ops-data-status")?.textContent === "筛选失败，结果未更新");
      if (!(await page.locator('[data-feedback-action="review"]').first().isVisible())) throw new Error(`${name}/feedback filter failure discarded the last valid result`);
      feedbackHasMore = true;
      await page.locator('[data-filter="module"]').selectOption("workflow");
      await page.locator('[data-load-more]').waitFor();
      failNextFeedbackLoadMore = true;
      await page.locator('[data-load-more]').click();
      await page.locator("#ops-alert").getByText("加载更多暂时不可用", { exact: true }).waitFor();
      await page.waitForFunction(() => document.querySelector("#ops-data-status")?.textContent === "加载失败，记录未更新");
      if (!(await page.locator('[data-load-more]').isEnabled())) throw new Error(`${name}/feedback load-more failure left retry disabled`);
      feedbackHasMore = false;
      await page.locator('[data-filter="module"]').selectOption("");
      await page.waitForFunction(() => document.querySelector("#ops-data-status")?.textContent === "筛选结果已更新");
      await page.locator('[data-filter="module"]').selectOption("workflow");
      await page.waitForFunction(() => document.querySelector("#ops-data-status")?.textContent === "筛选结果已更新");
      if (await page.locator("#ops-alert").isVisible()) throw new Error(`${name}/feedback successful retry did not clear the prior failure`);
      if (name === "mobile") {
        const mobileFeedback = await page.evaluate(() => {
          const wrap = document.querySelector(".ops-feedback-table-wrap");
          const nav = document.querySelector("#ops-nav");
          const tableHint = document.querySelector("#ops-feedback-scroll-hint");
          const navHint = document.querySelector("#ops-nav-scroll-hint");
          if (!wrap) return { missing_wrap: true };
          wrap.scrollLeft = 0;
          const wrapRect = wrap.getBoundingClientRect();
          const statusRect = wrap.querySelector("tbody .ops-feedback-status-column")?.getBoundingClientRect();
          const actionRect = wrap.querySelector("tbody .ops-feedback-action-column")?.getBoundingClientRect();
          const within = (rect) => Boolean(rect && rect.left >= wrapRect.left - 1 && rect.right <= wrapRect.right + 1);
          return {
            focusable: wrap.tabIndex === 0,
            aria_label: wrap.getAttribute("aria-label") || "",
            table_hint_visible: Boolean(tableHint && getComputedStyle(tableHint).display !== "none" && tableHint.getBoundingClientRect().height > 0),
            nav_focusable: nav?.tabIndex === 0,
            nav_hint_visible: Boolean(navHint && getComputedStyle(navHint).display !== "none" && navHint.getBoundingClientRect().height > 0),
            status_initially_visible: within(statusRect),
            action_initially_visible: within(actionRect),
          };
        });
        if (!mobileFeedback.focusable || !mobileFeedback.aria_label || !mobileFeedback.table_hint_visible || !mobileFeedback.nav_focusable || !mobileFeedback.nav_hint_visible || !mobileFeedback.status_initially_visible || !mobileFeedback.action_initially_visible) {
          throw new Error(`${name}/feedback mobile scroll affordance failed: ${JSON.stringify(mobileFeedback)}`);
        }
      }
      const before = path.join(OUT, `${name}-feedback-open.png`);
      await page.screenshot({ path: before, fullPage: true });
      screenshots.push(before);
      await page.locator('[data-feedback-action="review"]').click();
      await page.locator("#ops-alert").getByText("反馈状态已由其他运营人员更新").waitFor();
      if (!(await page.locator('[data-feedback-action="review"]').isVisible())) throw new Error(`${name}/feedback failure optimistically changed state`);
      const overviewBeforeSuccess = overviewRequestCount;
      await page.locator('[data-feedback-action="review"]').click();
      await page.locator(".ops-empty").waitFor();
      if (overviewRequestCount <= overviewBeforeSuccess) throw new Error(`${name}/feedback review did not refresh overview`);
      await page.locator('[data-filter="status"]').selectOption("reviewing");
      await page.locator('[data-feedback-action="resolve"]').waitFor();
      const overviewBeforeResolve = overviewRequestCount;
      await page.locator('[data-feedback-action="resolve"]').click();
      await page.locator(".ops-empty").waitFor();
      if (overviewRequestCount <= overviewBeforeResolve) throw new Error(`${name}/feedback resolve did not refresh overview`);
      await page.locator('[data-filter="status"]').selectOption("resolved");
      await page.getByText("已完成", { exact: true }).waitFor();
      const after = path.join(OUT, `${name}-feedback-resolved.png`);
      await page.screenshot({ path: after, fullPage: true });
      screenshots.push(after);
    }
    const layout = await page.evaluate(() => {
      const viewportWidth = window.innerWidth;
      const overflowingButtons = [...document.querySelectorAll("button")].filter((button) => {
        if (button.closest(".ops-nav")) return false;
        return button.getBoundingClientRect().right > viewportWidth + 2 || button.getBoundingClientRect().left < -2;
      }).length;
      const visibleContent = document.querySelector("#ops-content")?.innerText?.trim().length || 0;
      return { body_overflow: document.documentElement.scrollWidth > viewportWidth + 2, overflowing_buttons: overflowingButtons, visible_content_chars: visibleContent };
    });
    if (layout.body_overflow || layout.overflowing_buttons || layout.visible_content_chars < 20) throw new Error(`${name}/${view} layout failed: ${JSON.stringify(layout)}`);
    if (view === "merchants") {
      const xss = await page.evaluate(() => ({ executed: window.__opsXss === 1, injected_image: Boolean(document.querySelector('img[src="x"]')) }));
      if (xss.executed || xss.injected_image) throw new Error(`merchant table XSS boundary failed: ${JSON.stringify(xss)}`);
    }
    if (view === "overview" || view === "transactions" || (name === "desktop" && view === "costs")) {
      const screenshot = path.join(OUT, `${name}-${view}.png`);
      await page.screenshot({ path: screenshot, fullPage: true });
      if (fs.statSync(screenshot).size < 10000) throw new Error(`${screenshot} appears blank`);
      screenshots.push(screenshot);
    }
  }
  if ((name === "desktop" || name === "mobile") && expectedConflictConsoleCount !== 1) throw new Error(`${name} expected one handled conflict signal, received ${expectedConflictConsoleCount}`);
  if ((name === "desktop" || name === "mobile") && expectedServiceUnavailableConsoleCount !== 2) throw new Error(`${name} expected two handled service-unavailable signals, received ${expectedServiceUnavailableConsoleCount}`);
  if (consoleProblems.length || pageErrors.length) throw new Error(`${name} browser errors: ${JSON.stringify({ consoleProblems, pageErrors })}`);
  await context.close();
  return screenshots;
}

async function runAccessStates(browser, base) {
  const loginContext = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  const loginPage = await loginContext.newPage();
  await loginPage.route("**/permissions/me", (route) => route.fulfill({ status: 401, contentType: "application/json", body: JSON.stringify({ error: "authentication required" }) }));
  await loginPage.goto(`${base}/ops.html`, { waitUntil: "networkidle" });
  if (!(await loginPage.locator("#ops-login").isVisible())) throw new Error("unauthenticated login gate missing");
  await loginPage.screenshot({ path: path.join(OUT, "access-login.png"), fullPage: true });
  await loginContext.close();

  const deniedContext = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  const deniedPage = await deniedContext.newPage();
  await deniedPage.route("**/permissions/me", (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ role: "owner", platform_internal_admin: false }) }));
  await deniedPage.goto(`${base}/ops.html`, { waitUntil: "networkidle" });
  if (!(await deniedPage.locator("#ops-denied").isVisible())) throw new Error("ordinary merchant denied gate missing");
  await deniedContext.close();
}

async function runRotatingSessionRecovery(browser, base) {
  const context = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  const pages = [await context.newPage(), await context.newPage()];
  let initialIdentityResponsesRemaining = 2;
  let initialOverviewResponsesRemaining = 2;
  let refreshCompleted = false;
  let refreshCount = 0;
  let feedbackPostCount = 0;
  const routeIdentity = (route) => {
    if (initialIdentityResponsesRemaining > 0 || refreshCompleted) {
      initialIdentityResponsesRemaining = Math.max(0, initialIdentityResponsesRemaining - 1);
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ role: "owner", platform_internal_admin: true, secret_exposed: false }) });
    }
    return route.fulfill({ status: 401, contentType: "application/json", body: JSON.stringify({ error: "authentication required" }) });
  };
  const routeOverview = (route) => {
    if (initialOverviewResponsesRemaining > 0 || refreshCompleted) {
      initialOverviewResponsesRemaining = Math.max(0, initialOverviewResponsesRemaining - 1);
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ operations_overview: overviewFixture(30) }) });
    }
    return route.fulfill({ status: 401, contentType: "application/json", body: JSON.stringify({ error: "authentication required" }) });
  };
  for (const page of pages) {
    page.setDefaultTimeout(5000);
    await page.route("**/permissions/me", routeIdentity);
    await page.route("**/owner/operations-overview**", routeOverview);
    await page.route("**/auth/refresh", async (route) => {
      refreshCount += 1;
      await new Promise((resolve) => setTimeout(resolve, 100));
      refreshCompleted = true;
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ok: true, session_refreshed: true, secret_exposed: false }) });
    });
    await page.route("**/owner/operations/feedback**", (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ operations_detail: detailFixture("feedback", 30) }) }));
    await page.route("**/owner/product-feedback/review", (route) => {
      feedbackPostCount += 1;
      return route.fulfill({ status: 401, contentType: "application/json", body: JSON.stringify({ error: "authentication required" }) });
    });
  }
  await Promise.all(pages.map((page) => page.goto(`${base}/ops.html`, { waitUntil: "networkidle" })));
  await Promise.all(pages.map((page) => page.waitForSelector("#ops-app:not([hidden])")));
  await Promise.all(pages.map((page) => page.locator("#ops-refresh").click()));
  await Promise.all(pages.map((page) => page.waitForFunction(() => document.querySelector("#ops-data-status")?.textContent === "真实数据已更新")));
  if (refreshCount !== 1) throw new Error(`cross-tab operations session refresh must happen exactly once: ${refreshCount}`);
  await pages[0].click('[data-view="feedback"]');
  await pages[0].locator('[data-feedback-action="review"]').first().click();
  await pages[0].locator("#ops-login").waitFor({ state: "visible" });
  await pages[0].waitForFunction(() => document.querySelector("#ops-data-status")?.textContent === "登录已过期，请重新登录");
  const expiredContent = await pages[0].locator("#ops-content").innerText();
  if (!expiredContent.includes("旧经营数据已从当前页面清除")) {
    throw new Error(`expired operations session must clear stale content: ${expiredContent}`);
  }
  if (feedbackPostCount !== 1) throw new Error(`operations mutation must never be replayed after 401: ${feedbackPostCount}`);
  if (refreshCount !== 1) throw new Error(`operations mutation incorrectly triggered session refresh: ${refreshCount}`);
  await context.close();
}

async function runFailureRecoveryStates(browser, base) {
  const context = await browser.newContext({ viewport: { width: 1280, height: 800 }, deviceScaleFactor: 1 });
  const page = await context.newPage();
  page.setDefaultTimeout(5000);
  const consoleProblems = [];
  const pageErrors = [];
  let expectedServiceUnavailableConsoleCount = 0;
  let failInitialFeedbackDetail = true;
  let failNextMutationDetailRefresh = false;
  let failNextMutationOverviewRefresh = false;
  let delayNextReview = false;
  let feedbackStatus = "open";
  let reviewPostCount = 0;
  let feedbackDetailRequestCount = 0;
  let feedbackFilteredRequestCount = 0;
  let feedbackCursorRequestCount = 0;
  page.on("console", (message) => {
    const text = message.text();
    if (message.type() === "error" && text.includes("503 (Service Unavailable)")) {
      expectedServiceUnavailableConsoleCount += 1;
      return;
    }
    if (["error", "warning"].includes(message.type())) consoleProblems.push(`${message.type()}: ${text}`);
  });
  page.on("pageerror", (error) => pageErrors.push(error.message));
  await page.route("**/permissions/me", (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ role: "owner", platform_internal_admin: true, secret_exposed: false }) }));
  await page.route("**/owner/operations-overview**", (route) => {
    const days = Number(new URL(route.request().url()).searchParams.get("period_days") || 30);
    if (failNextMutationOverviewRefresh) {
      failNextMutationOverviewRefresh = false;
      return route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ error: "经营概览刷新暂时不可用" }) });
    }
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ operations_overview: overviewFixture(days, feedbackStatus) }) });
  });
  await page.route("**/owner/operations/**", (route) => {
    const url = new URL(route.request().url());
    const section = url.pathname.split("/").filter(Boolean).at(-1);
    const days = Number(url.searchParams.get("period_days") || 30);
    if (section === "feedback") {
      feedbackDetailRequestCount += 1;
      if (url.searchParams.has("status") || url.searchParams.has("module")) feedbackFilteredRequestCount += 1;
      if (url.searchParams.has("cursor")) feedbackCursorRequestCount += 1;
    }
    if (section === "feedback" && failInitialFeedbackDetail) {
      failInitialFeedbackDetail = false;
      return route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ error: "产品反馈暂时不可用" }) });
    }
    if (section === "feedback" && failNextMutationDetailRefresh) {
      failNextMutationDetailRefresh = false;
      return route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ error: "产品反馈刷新暂时不可用" }) });
    }
    const fixture = detailFixture(section, days, feedbackStatus);
    if (section === "feedback") {
      fixture.has_more = true;
      fixture.next_cursor = "feedback-concurrency-cursor";
    }
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ operations_detail: fixture }) });
  });
  await page.route("**/owner/product-feedback/review", async (route) => {
    reviewPostCount += 1;
    if (delayNextReview) {
      delayNextReview = false;
      await new Promise((resolve) => setTimeout(resolve, 250));
    }
    feedbackStatus = "reviewing";
    failNextMutationDetailRefresh = true;
    failNextMutationOverviewRefresh = true;
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ product_feedback: { feedback_id: "feedback_ops_smoke_001", status: feedbackStatus }, secret_exposed: false }) });
  });
  await page.goto(`${base}/ops.html`, { waitUntil: "networkidle" });
  await page.waitForSelector("#ops-app:not([hidden])");
  await page.click('[data-view="feedback"]');
  await page.locator("#ops-alert").getByText("产品反馈暂时不可用", { exact: true }).waitFor();
  await page.waitForFunction(() => document.querySelector("#ops-data-status")?.textContent === "下钻数据读取失败");
  await page.locator(".ops-empty").getByText("产品反馈暂时无法读取，请使用刷新按钮重试。", { exact: true }).waitFor();
  await page.locator("#ops-refresh").click();
  await page.locator('[data-feedback-action="review"]').first().waitFor();
  await page.waitForFunction(() => document.querySelector("#ops-data-status")?.textContent === "真实数据已更新");
  if (await page.locator("#ops-alert").isVisible()) throw new Error("initial feedback retry did not clear the prior failure");
  const requestsBeforeMutation = {
    detail: feedbackDetailRequestCount,
    filtered: feedbackFilteredRequestCount,
    cursor: feedbackCursorRequestCount,
  };
  delayNextReview = true;
  await page.locator('[data-feedback-id="feedback_ops_smoke_001"][data-feedback-action="review"]').click();
  await page.waitForFunction(() => [...document.querySelectorAll("[data-filter], [data-load-more], [data-feedback-action]")].every((element) => element.disabled));
  await page.locator('[data-filter="status"]').dispatchEvent("change");
  await page.locator('[data-load-more]').dispatchEvent("click");
  await page.locator("#ops-alert").getByText("反馈状态已更新，列表刷新失败，请刷新", { exact: true }).waitFor();
  await page.waitForFunction(() => document.querySelector("#ops-data-status")?.textContent === "反馈状态已更新，列表待刷新");
  await page.locator(".ops-empty").getByText("反馈状态已更新，列表刷新失败，请使用刷新按钮重试。", { exact: true }).waitFor();
  if (reviewPostCount !== 1) throw new Error(`mutation refresh failure repeated the POST: ${reviewPostCount}`);
  if (await page.locator('[data-feedback-id="feedback_ops_smoke_001"][data-feedback-action="review"]').count()) throw new Error("mutation refresh failure left the stale review action available");
  if (feedbackDetailRequestCount !== requestsBeforeMutation.detail + 1 || feedbackFilteredRequestCount !== requestsBeforeMutation.filtered || feedbackCursorRequestCount !== requestsBeforeMutation.cursor) {
    throw new Error(`delayed mutation raced filter/load-more requests: ${JSON.stringify({ requestsBeforeMutation, feedbackDetailRequestCount, feedbackFilteredRequestCount, feedbackCursorRequestCount })}`);
  }
  await page.locator("#ops-refresh").click();
  await page.locator('[data-feedback-id="feedback_ops_smoke_001"][data-feedback-action="resolve"]').waitFor();
  await page.waitForFunction(() => document.querySelector("#ops-data-status")?.textContent === "真实数据已更新");
  if (reviewPostCount !== 1) throw new Error(`manual refresh repeated the successful POST: ${reviewPostCount}`);
  const screenshot = path.join(OUT, "failure-recovery-feedback.png");
  await page.screenshot({ path: screenshot, fullPage: true });
  if (expectedServiceUnavailableConsoleCount !== 3) throw new Error(`failure recovery expected three handled service-unavailable signals, received ${expectedServiceUnavailableConsoleCount}`);
  if (consoleProblems.length || pageErrors.length) throw new Error(`failure recovery browser errors: ${JSON.stringify({ consoleProblems, pageErrors })}`);
  await context.close();
  return [screenshot];
}

async function main() {
  fs.rmSync(OUT, { recursive: true, force: true });
  fs.mkdirSync(OUT, { recursive: true });
  const { server, base } = await startServer();
  const executablePath = String(process.env.JIEJING_PLAYWRIGHT_EXECUTABLE || "").trim();
  const launchOptions = { headless: true };
  if (executablePath) {
    launchOptions.executablePath = executablePath;
  } else {
    launchOptions.channel = process.env.JIEJING_PLAYWRIGHT_CHANNEL || "chrome";
  }
  const browser = await chromium.launch(launchOptions);
  try {
    await runAccessStates(browser, base);
    await runRotatingSessionRecovery(browser, base);
    const screenshots = [];
    screenshots.push(...await runFailureRecoveryStates(browser, base));
    screenshots.push(...await runViewport(browser, base, "desktop", { width: 1440, height: 960 }));
    screenshots.push(...await runViewport(browser, base, "tablet", { width: 1024, height: 768 }));
    screenshots.push(...await runViewport(browser, base, "mobile", { width: 390, height: 844 }));
    console.log(JSON.stringify({ status: "PASS", screenshots }, null, 2));
  } finally {
    await browser.close();
    await new Promise((resolve) => server.close(resolve));
  }
}

main().catch((error) => { console.error(error.stack || error); process.exit(1); });
