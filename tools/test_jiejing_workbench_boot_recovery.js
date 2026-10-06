#!/usr/bin/env node
"use strict";

// Real entry HTML, inline bootstrap and CSS; only external I/O and time are
// controlled. This is an isolated fixture, never a production merchant session.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const os = require("node:os");
const { test, before, after } = require("node:test");
const { chromium } = require("../output/codex-playwright-deps/node_modules/playwright-core");
const root = path.resolve(__dirname, "..");
const origin = "https://jiejing-boot.example.invalid";
let browser;

before(async () => { browser = await chromium.launch({ headless: true, channel: process.env.JIEJING_PLAYWRIGHT_CHANNEL || "chrome" }); });
after(async () => { if (browser) await browser.close(); });

async function withPendingScript(run, options = {}) {
  const context = await browser.newContext({ viewport: { width: options.width || 1440, height: 900 } });
  const page = await context.newPage();
  const requests = [];
  let release;
  const pending = new Promise((resolve) => { release = resolve; });
  await page.clock.install();
  await page.route("**/*", async (route) => {
    const url = new URL(route.request().url());
    requests.push({ path: url.pathname, method: route.request().method() });
    if (url.origin !== origin) return route.abort();
    if (url.pathname === "/seed.html") return route.fulfill({ contentType: "text/html", body: "<!doctype html><title>Isolated bootstrap fixture</title>" });
    if (url.pathname === "/app.js") {
      if (options.failScript) return route.abort("failed");
      await pending;
      return route.fulfill({ contentType: "text/javascript", body: "/* loaded network boundary fixture */" }).catch(() => {});
    }
    if (url.pathname.endsWith(".js")) return route.fulfill({ contentType: "text/javascript", body: "" });
    const file = path.resolve(root, url.pathname.replace(/^\/+/, ""));
    if (!file.startsWith(root + path.sep) || !fs.existsSync(file)) return route.fulfill({ status: 404, body: "fixture only" });
    return route.fulfill({ contentType: file.endsWith(".html") ? "text/html; charset=utf-8" : file.endsWith(".css") ? "text/css" : "image/svg+xml", body: fs.readFileSync(file) });
  });
  try {
    await page.goto(`${origin}/seed.html`);
    await page.evaluate(() => {
      localStorage.setItem("jiejing_saas_backend_session_hint", "1");
      localStorage.setItem("jiejing_saas_last_account", "boot@example.invalid");
      localStorage.setItem("jiejing_saas_onboarding_done:boot@example.invalid", "1");
      localStorage.setItem("boot-history-sentinel", "preserve-existing-history");
    });
    await page.goto(`${origin}/app.html?start=app&view=cockpit&project=fixture-original-product`, { waitUntil: "commit" });
    await page.locator("#appBootLoading").waitFor({ state: "visible" });
    await run(page, requests, release);
  } finally {
    release();
    await context.close();
  }
}

test("a stalled main script offers a usable recovery before DOMContentLoaded without revealing merchant data", async () => {
  await withPendingScript(async (page, requests) => {
    await page.clock.fastForward(21000);
    await page.getByRole("button", { name: "重新加载页面", exact: true }).waitFor({ state: "visible", timeout: 1500 });
    assert.equal(await page.getByText("页面资源加载缓慢，请重试", { exact: true }).isVisible(), true);
    assert.equal(await page.locator("#appBootLoading").evaluate((node) => getComputedStyle(node, "::before").display), "none",
      "the recovery replaces the loading card instead of adding a second stacked card");
    assert.equal(await page.locator("#appShell").isVisible(), false);
    assert.equal(await page.evaluate(() => document.readyState), "loading");
    assert.equal(requests.some((request) => request.path.startsWith("/api/")), false);
    assert.equal(await page.evaluate(() => localStorage.getItem("jiejing_saas_backend_session_hint")), "1");
  });
});

test("explicit reload keeps the original project, session hint and history without sending business requests", async () => {
  await withPendingScript(async (page, requests) => {
    await page.clock.fastForward(21000);
    const before = requests.filter((request) => request.path === "/app.html").length;
    await Promise.all([
      page.waitForRequest((request) => new URL(request.url()).pathname === "/app.html"),
      page.getByRole("button", { name: "重新加载页面", exact: true }).click(),
    ]);
    await page.locator("#appBootLoading").waitFor({ state: "visible" });
    assert.equal(new URL(page.url()).searchParams.get("project"), "fixture-original-product");
    assert.equal(requests.filter((request) => request.path === "/app.html").length, before + 1);
    assert.equal(await page.evaluate(() => localStorage.getItem("jiejing_saas_backend_session_hint")), "1");
    assert.equal(await page.evaluate(() => localStorage.getItem("boot-history-sentinel")), "preserve-existing-history");
    assert.equal(requests.some((request) => request.path.startsWith("/api/") || request.method !== "GET"), false);
  });
});

test("a late successful script clears only resource recovery, never the authentication boundary", async () => {
  await withPendingScript(async (page, _requests, release) => {
    await page.clock.fastForward(21000);
    assert.equal(await page.getByRole("button", { name: "重新加载页面", exact: true }).isVisible(), true);
    release();
    await page.waitForLoadState("load");
    assert.equal(await page.getByRole("button", { name: "重新加载页面", exact: true }).isVisible(), false);
    assert.equal(await page.locator("#appShell").isVisible(), false);
    assert.equal(await page.evaluate(() => document.documentElement.classList.contains("app-ready")), false);
    await page.clock.fastForward(30000);
    assert.equal(await page.getByRole("button", { name: "重新加载页面", exact: true }).isVisible(), false);
  });
});

test("script network failure exposes recovery immediately and fits a tablet without revealing the workbench", async () => {
  await withPendingScript(async (page) => {
    await page.waitForLoadState("load");
    assert.equal(await page.getByRole("button", { name: "重新加载页面", exact: true }).isVisible(), true);
    assert.equal(await page.locator("#appShell").isVisible(), false);
    const bounds = await page.locator("#appAssetRecovery").boundingBox();
    assert.ok(bounds.x >= 0 && bounds.x + bounds.width <= 820);
    assert.ok(bounds.y >= 0 && bounds.y + bounds.height <= 900);
    const evidence = path.join(fs.mkdtempSync(path.join(os.tmpdir(), "jiejing-boot-recovery-")), "tablet.png");
    await page.screenshot({ path: evidence });
    console.log(`Isolated fixture screenshot: ${evidence}`);
  }, { failScript: true, width: 820 });
});
