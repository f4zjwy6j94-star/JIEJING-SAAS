#!/usr/bin/env node
"use strict";

const { chromium } = require("../output/codex-playwright-deps/node_modules/playwright-core");

async function main() {
  const baseUrl = process.env.JIEJING_FRONTEND_SMOKE_BASE || "http://127.0.0.1:8766";
  const mode = process.env.JIEJING_FRONTEND_SMOKE_MODE || "workbench";
  const browser = await chromium.launch({ headless: true, channel: "chrome" });
  const page = await browser.newPage({ viewport: { width: 1365, height: 900 } });
  const analytics = [];
  const settingsRequests = [];
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("request", (request) => {
    if (request.url().includes("jiejing-settings-panels.js")) settingsRequests.push(request.url());
  });
  if (mode === "workbench") {
    await page.addInitScript(() => {
      window.__JIEJING_ANALYTICS_TEST_MODE__ = true;
      localStorage.setItem("jiejing_saas_backend_session_hint", "1");
    });
  } else {
    await page.addInitScript(() => {
      window.__JIEJING_ANALYTICS_TEST_MODE__ = true;
    });
  }
  await page.route("**/analytics/events", async (route) => {
    try {
      analytics.push(JSON.parse(route.request().postData() || "{}"));
    } catch (error) {
      errors.push(`analytics JSON: ${error.message}`);
    }
    await route.fulfill({ status: 200, contentType: "application/json", body: '{"ok":true}' });
  });
  await page.route("http://127.0.0.1:8788/**", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: "{}" });
  });
  try {
    const targetUrl =
      mode === "landing"
        ? `${baseUrl}/index.html?verify=reliability-v90&analytics_test=1`
        : `${baseUrl}/app.html?start=app&view=cockpit&onboarded=1&analytics_test=1`;
    await page.goto(targetUrl, { waitUntil: "load" });
    await page.waitForTimeout(2300);
    const settingsBefore = settingsRequests.length;
    const pageSamples = analytics.filter(
      (item) => item.event_key === "performance_sample" && item.metadata?.performance_scope === "page_load",
    );
    if (mode === "workbench") {
      await page.evaluate(() => {
        if (!window.JIEJING_TEST_HOOKS?.openApp) throw new Error("local QA hooks unavailable");
        window.JIEJING_TEST_HOOKS.state.saasIdentity = { user_id: "qa-performance-user" };
        window.JIEJING_TEST_HOOKS.state.saasUser = { user_id: "qa-performance-user" };
        window.JIEJING_TEST_HOOKS.openApp("connect");
      });
      await page.waitForTimeout(900);
    }
    const settingsAfter = settingsRequests.length;
    const settingsSamples = analytics.filter(
      (item) => item.event_key === "performance_sample" && item.metadata?.performance_scope === "settings_module",
    );
    const forbidden = analytics.some((item) =>
      /raw_url|prompt|userAgent|referrer|location\.href/i.test(JSON.stringify(item)),
    );
    const result = {
      settings_requests_before: settingsBefore,
      settings_requests_after: settingsAfter,
      page_performance_samples: pageSamples.length,
      settings_performance_samples: settingsSamples.length,
      page_metadata: pageSamples[0]?.metadata || {},
      settings_metadata: settingsSamples[0]?.metadata || {},
      forbidden_metadata_present: forbidden,
      page_errors: errors,
    };
    const failures = [];
    if (mode === "workbench" && (settingsBefore !== 0 || settingsAfter !== 1)) {
      failures.push("settings_lazy_load_contract_failed");
    }
    if (pageSamples.length !== 1) failures.push("page_performance_sample_count_failed");
    if (mode === "workbench" && (settingsSamples.length !== 1 || settingsSamples[0]?.metadata?.outcome !== "success")) {
      failures.push("settings_performance_sample_failed");
    }
    if (forbidden) failures.push("forbidden_performance_metadata_present");
    if (errors.length) failures.push("browser_page_errors_present");
    console.log(JSON.stringify({ ok: failures.length === 0, failures, result }, null, 2));
    if (failures.length) process.exitCode = 1;
  } finally {
    await browser.close();
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
