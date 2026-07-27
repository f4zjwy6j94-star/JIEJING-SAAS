#!/usr/bin/env node
"use strict";

const fs = require("fs");
const http = require("http");
const path = require("path");
const { chromium } = require("playwright");

const ROOT = path.resolve(__dirname, "..");
const OUT = path.join(ROOT, "output", "jiejing-operations-console-browser-smoke");
const STATIC_FILES = new Set([
  "ops.html",
  "ops.css",
  "ops.js",
  "assets/jiejing-logo-mark.svg",
  "assets/jiejing-app-icon.svg",
]);

function overviewFixture(days) {
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
      model: { status: "instrumented", request_count: 214, success_count: 207, timeout_count: 3, p75_duration_ms: 4200 },
      public_search: { status: "instrumented", request_count: 96, success_count: 90, timeout_count: 2, p75_duration_ms: 980 },
      media_generation: { status: "instrumented", request_count: 38, success_count: 35, timeout_count: 1, p75_duration_ms: 12400 },
      payment: { status: "instrumented", request_count: 18, success_count: 18, timeout_count: 0, p75_duration_ms: 620 },
      alerts: { critical_count: 0, attention_count: 1 },
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
    data_quality: { scope: "merchant_accounts_and_commercial_transactions", synthetic_test_accounts_excluded: 5, acceptance_orders_excluded: 2 },
    merchant_navigation_visible: false,
    frontend_gets_secret: false,
    secret_exposed: false,
  };
}

function detailFixture(section, days) {
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
  };
  if (section === "traffic") return { ...common, summary: overviewFixture(days).traffic_analytics, performance: overviewFixture(days).performance_analytics, items: items.traffic };
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
  const context = await browser.newContext({ viewport, deviceScaleFactor: 1 });
  const page = await context.newPage();
  await page.route("**/permissions/me", (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ role: "owner", platform_internal_admin: true, secret_exposed: false }) }));
  await page.route("**/owner/operations-overview**", (route) => {
    const days = Number(new URL(route.request().url()).searchParams.get("period_days") || 30);
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ operations_overview: overviewFixture(days) }) });
  });
  await page.route("**/owner/operations/**", (route) => {
    const url = new URL(route.request().url());
    const section = url.pathname.split("/").filter(Boolean).at(-1);
    const days = Number(url.searchParams.get("period_days") || 30);
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ operations_detail: detailFixture(section, days) }) });
  });
  await page.goto(`${base}/ops.html`, { waitUntil: "networkidle" });
  await page.waitForSelector("#ops-app:not([hidden])");
  const screenshots = [];
  const views = name === "desktop" ? Object.keys({ overview: 1, traffic: 1, merchants: 1, transactions: 1, costs: 1, workflows: 1, reliability: 1, audit: 1, settings: 1 }) : ["overview", "transactions", "reliability"];
  for (const view of views) {
    await page.click(`[data-view="${view}"]`);
    await page.waitForFunction((title) => document.querySelector("#ops-title")?.textContent === title, ({ overview: "经营总览", traffic: "流量与转化", merchants: "商家与订阅", transactions: "交易与退款", costs: "AI 与素材成本", workflows: "任务与工作流", reliability: "系统可靠性", audit: "安全与审计", settings: "内部设置" })[view]);
    await page.waitForTimeout(60);
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

async function main() {
  fs.rmSync(OUT, { recursive: true, force: true });
  fs.mkdirSync(OUT, { recursive: true });
  const { server, base } = await startServer();
  const executablePath = process.env.JIEJING_PLAYWRIGHT_EXECUTABLE || "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
  const browser = await chromium.launch({ headless: true, executablePath });
  try {
    await runAccessStates(browser, base);
    const screenshots = [];
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
