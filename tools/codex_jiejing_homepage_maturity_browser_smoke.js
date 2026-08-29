#!/usr/bin/env node
/* Public homepage browser smoke at desktop, tablet and mobile sizes.
   It performs no login, charge, OAuth, or platform write. */

const fs = require("fs");
const path = require("path");
const { chromium } = require("../output/codex-playwright-deps/node_modules/playwright-core");

const base = process.env.JIEJING_TEST_BASE || "http://127.0.0.1:8788";
const staticRoot = path.resolve(process.env.JIEJING_LOCAL_STATIC_ROOT || path.join(__dirname, ".."));
const browserChannel = process.env.JIEJING_PLAYWRIGHT_CHANNEL || "chrome";

function localStaticPath(requestUrl) {
  const pathname = decodeURIComponent(new URL(requestUrl).pathname.replace(/^\/+/, "")) || "index.html";
  const allowed = ["index.html", "app.html", "app.js", "styles.css", "privacy.html", "terms.html", "refund-policy.html", "support.html", "risk-disclosure.html"].includes(pathname) || pathname.startsWith("assets/");
  if (!allowed) return "";
  const candidate = path.resolve(staticRoot, pathname);
  const relative = path.relative(staticRoot, candidate);
  return relative.startsWith("..") || path.isAbsolute(relative) ? "" : candidate;
}

function contentTypeFor(filePath) {
  const ext = path.extname(filePath).toLowerCase();
  if (ext === ".html") return "text/html; charset=utf-8";
  if (ext === ".css") return "text/css; charset=utf-8";
  if (ext === ".js") return "text/javascript; charset=utf-8";
  if (ext === ".svg") return "image/svg+xml";
  if (ext === ".png") return "image/png";
  if (ext === ".jpg" || ext === ".jpeg") return "image/jpeg";
  if (ext === ".webp") return "image/webp";
  return "application/octet-stream";
}

async function installStaticRoute(context) {
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

async function inspectViewport(browser, viewport, name) {
  const context = await browser.newContext({ viewport, deviceScaleFactor: 1 });
  await installStaticRoute(context);
  const page = await context.newPage();
  const pageErrors = [];
  const badResponses = [];
  const consoleIssues = [];
  page.on("pageerror", (error) => pageErrors.push(String(error)));
  page.on("console", (message) => {
    if (["error", "warning"].includes(message.type())) consoleIssues.push(message.text());
  });
  page.on("response", (response) => {
    if (response.status() >= 500) badResponses.push({ url: response.url(), status: response.status() });
  });
  await page.goto(`${base}/index.html`, { waitUntil: "domcontentloaded", timeout: 60000 });
  await page.waitForSelector('[data-home-example="travel-compression-workflow-v1"]', { timeout: 20000 });
  await page.locator('[data-home-example="travel-compression-workflow-v1"] img').evaluateAll(async (images) => {
    images.forEach((image) => { image.loading = "eager"; });
    await Promise.all(images.map((image) => image.complete ? Promise.resolve() : new Promise((resolve) => {
      image.addEventListener("load", resolve, { once: true });
      image.addEventListener("error", resolve, { once: true });
    })));
  });
  const state = await page.evaluate(() => {
    const planOrder = Array.from(document.querySelectorAll(".path-card[data-plan]")).map((item) => item.dataset.plan);
    const login = document.querySelector("#topLogin");
    const workflowImages = Array.from(document.querySelectorAll('[data-home-example="travel-compression-workflow-v1"] img'));
    return {
      section_count: document.querySelectorAll("[data-home-section]").length,
      section_order: Array.from(document.querySelectorAll("[data-home-section]")).map((item) => item.dataset.homeSection),
      primary_cta_count: document.querySelectorAll('[data-home-primary-cta="jiejing_ai_ceo_workspace_v2"]').length,
      plan_order: planOrder,
      retired_dom_count: document.querySelectorAll("#retired-public-home-sections, #merchant-guide, #ai-ceo-workbench-technical, #ai-ceo-workbench").length,
      radiating_hero_count: document.querySelectorAll("#signalCanvas, .hero .flow-line, .hero .role-node").length,
      login_is_text: Boolean(login?.classList.contains("button-text")),
      workflow_step_count: document.querySelectorAll("[data-home-workflow-step]").length,
      workflow_image_count: workflowImages.length,
      workflow_images_loaded: workflowImages.every((image) => image.complete && image.naturalWidth > 0),
      workflow_disclaimer_visible: document.querySelector(".home-example-caption")?.getClientRects().length > 0,
      horizontal_overflow: Math.max(0, document.documentElement.scrollWidth - document.documentElement.clientWidth),
    };
  });
  await page.screenshot({ path: path.join("output", "browser-smoke", `homepage-maturity-${name}.png`), fullPage: true });
  if (name === "mobile") {
    await page.locator('[data-home-example="travel-compression-workflow-v1"]').screenshot({
      path: path.join("output", "browser-smoke", "homepage-maturity-mobile-workflow.png"),
    });
  }
  if (name === "desktop") {
    await page.click('[data-home-primary-cta="jiejing_ai_ceo_workspace_v2"]');
    await page.waitForSelector("#nextStepModal.is-open", { timeout: 10000 });
    state.primary_cta_opens_auth = await page.evaluate(() => document.body.classList.contains("is-auth-mode"));
  }
  await context.close();
  return { name, viewport, ...state, page_errors: pageErrors, console_issues: consoleIssues, bad_responses: badResponses };
}

async function main() {
  const browser = await chromium.launch({ channel: browserChannel, headless: true });
  try {
    const results = [];
    for (const item of [
      ["desktop", { width: 1440, height: 1000 }],
      ["tablet", { width: 1024, height: 900 }],
      ["mobile", { width: 390, height: 844 }],
    ]) {
      results.push(await inspectViewport(browser, item[1], item[0]));
    }
    const ok = results.every(
      (item) =>
        item.section_count === 6 &&
        JSON.stringify(item.section_order) === JSON.stringify(["hero", "proof", "capabilities", "workflow", "merchants", "plans"]) &&
        item.primary_cta_count === 1 &&
        JSON.stringify(item.plan_order) === JSON.stringify(["free", "single", "multi"]) &&
        item.retired_dom_count === 0 &&
        item.radiating_hero_count === 0 &&
        item.login_is_text &&
        item.workflow_step_count === 6 &&
        item.workflow_image_count === 5 &&
        item.workflow_images_loaded &&
        item.workflow_disclaimer_visible &&
        item.horizontal_overflow <= 1 &&
        item.page_errors.length === 0 &&
        item.console_issues.length === 0 &&
        item.bad_responses.length === 0 &&
        (item.name !== "desktop" || item.primary_cta_opens_auth === true),
    );
    console.log(JSON.stringify({ ok, results, no_login_performed: true, no_real_world_action: true }, null, 2));
    if (!ok) process.exitCode = 1;
  } finally {
    await browser.close();
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
