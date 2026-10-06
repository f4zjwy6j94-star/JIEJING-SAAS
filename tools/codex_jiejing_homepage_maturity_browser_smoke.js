#!/usr/bin/env node
/* Rendered regression for the approved finish-review-v12 homepage.
   All resources are intercepted locally; no login, telemetry, charge, OAuth,
   provider call, or platform operation reaches a server. */
const fs = require("fs");
const path = require("path");
const assert = require("node:assert/strict");
const { chromium } = require("../output/codex-playwright-deps/node_modules/playwright-core");
const base = process.env.JIEJING_TEST_BASE || "http://127.0.0.1:8788";
const staticRoot = path.resolve(process.env.JIEJING_LOCAL_STATIC_ROOT || path.join(__dirname, ".."));
const browserChannel = process.env.JIEJING_PLAYWRIGHT_CHANNEL || "chrome";
const approvedHeroNodes = ["market", "listing", "media", "ads", "service", "finance"];
const approvedWorkflowSteps = ["goal", "research", "facts", "listing", "media", "confirm"];
const approvedImages = ["collection", "suitcase", "packing", "detail"];
const unexpectedRequests = [];

function localStaticPath(requestUrl) {
  const url = new URL(requestUrl);
  if (url.origin !== new URL(base).origin) return "";
  const pathname = decodeURIComponent(url.pathname.replace(/^\/+/, "")) || "index.html";
  const allowed = ["index.html", "app.html", "app.js", "styles.css", "privacy.html", "terms.html", "refund-policy.html", "support.html", "risk-disclosure.html"].includes(pathname) || pathname.startsWith("assets/");
  if (!allowed) return "";
  const candidate = path.resolve(staticRoot, pathname);
  const relative = path.relative(staticRoot, candidate);
  return relative.startsWith("..") || path.isAbsolute(relative) ? "" : candidate;
}
function contentTypeFor(filePath) {
  return ({".html":"text/html; charset=utf-8", ".css":"text/css; charset=utf-8", ".js":"text/javascript; charset=utf-8", ".svg":"image/svg+xml", ".png":"image/png", ".jpg":"image/jpeg", ".jpeg":"image/jpeg", ".webp":"image/webp", ".woff2":"font/woff2"})[path.extname(filePath).toLowerCase()] || "application/octet-stream";
}
async function installStaticRoute(context) {
  await context.route("**/*", (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.origin === new URL(base).origin && url.pathname === "/analytics/events") {
      return route.fulfill({status: 200, contentType:"application/json", body:'{"ok":true}'});
    }
    const file = request.method() === "GET" ? localStaticPath(request.url()) : "";
    if (file && fs.existsSync(file) && fs.statSync(file).isFile()) {
      return route.fulfill({status:200, contentType:contentTypeFor(file), headers:{"cache-control":"no-store"}, body:fs.readFileSync(file)});
    }
    unexpectedRequests.push(request.method() + " " + url.pathname);
    return route.fulfill({status:404, contentType:"application/json", body:'{"error":"offline_test_unexpected_request"}'});
  });
}
async function newPage(browser, viewport, options = {}) {
  const context = await browser.newContext({viewport, deviceScaleFactor:1, ...options});
  await installStaticRoute(context);
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", error => errors.push(String(error)));
  page.on("console", message => { if (["error", "warning"].includes(message.type())) errors.push(message.text()); });
  await page.goto(base + "/index.html", {waitUntil:"load"});
  await page.evaluate(() => document.fonts.ready);
  return {context, page, errors};
}
async function workflowSnapshot(page) {
  return page.evaluate(() => {
    const steps = [...document.querySelectorAll("[data-home-workflow-step]")];
    const panels = [...document.querySelectorAll("[data-home-workflow-panel]")];
    const active = steps.filter(item => item.getAttribute("aria-pressed") === "true");
    const visible = panels.filter(item => !item.hidden && item.getClientRects().length);
    return {
      steps:steps.map(item=>item.dataset.homeWorkflowStep),
      panels:panels.map(item=>item.dataset.homeWorkflowPanel),
      active:active[0]?.dataset.homeWorkflowStep,
      visible:visible[0]?.dataset.homeWorkflowPanel,
      synchronized:active.length === 1 && visible.length === 1 && active[0].dataset.homeWorkflowStep === visible[0].dataset.homeWorkflowPanel && panels.every(item=>item.inert === item.hidden),
      announcement:document.querySelector("[data-home-workflow-live]").textContent.trim()
    };
  });
}
async function assertHero(page, key) {
  const state = await page.evaluate(key => {
    const active = [...document.querySelectorAll('[data-home-ai-ceo-node][aria-pressed="true"]')];
    const lines = [...document.querySelectorAll("[data-home-ai-ceo-line].is-active")];
    const node = document.querySelector('[data-home-ai-ceo-node="' + key + '"]');
    return {
      active:active.length === 1 && active[0] === node,
      line:lines.length === 1 && lines[0].dataset.homeAiCeoLine === key,
      result:document.querySelector("#ceoResult").textContent === node.dataset.homeAiCeoResultCopy,
      title:document.querySelector("#ceoResultTitle").textContent === node.querySelector("strong").textContent
    };
  }, key);
  assert(Object.values(state).every(Boolean), "hero selection is inconsistent: " + JSON.stringify(state));
}
async function assertImage(page, key) {
  await page.waitForFunction(key => document.querySelector('[data-studio-image="' + key + '"]')?.getAttribute("aria-pressed") === "true" && document.querySelector("#studioImage").getAttribute("aria-busy") !== "true", key);
  const state = await page.evaluate(key => {
    const image = document.querySelector("#studioImage");
    const item = window.JiejingDemoMedia.find(item=>item.id === key);
    return {
      selected:document.querySelectorAll('[data-studio-image][aria-pressed="true"]').length === 1,
      loaded:image.complete && image.naturalWidth > 0,
      source:(image.currentSrc || image.src).includes("packing-" + key + "-v6-"),
      label:document.querySelector("#studioLabel").textContent === item.label,
      purpose:document.querySelector("#studioPurpose").textContent === item.purpose,
      prompt:document.querySelector("#studioPrompt").textContent === item.prompt,
      note:document.querySelector("#studioImageNote").textContent === item.note,
      noError:!document.querySelector("#studioLoadStatus").textContent
    };
  }, key);
  assert(Object.values(state).every(Boolean), "image selection is inconsistent: " + JSON.stringify(state));
}
async function inspectViewport(browser, viewport, name, reducedMotion = "no-preference") {
  const {context, page, errors} = await newPage(browser, viewport, {reducedMotion});
  try {
    const initial = await page.evaluate(() => ({
      version:document.body.dataset.homeVersion,
      sections:[...document.querySelectorAll("[data-home-section]")].map(item=>item.dataset.homeSection),
      plans:[...document.querySelectorAll(".path-card[data-plan]")].map(item=>item.dataset.plan),
      nodes:[...document.querySelectorAll("[data-home-ai-ceo-node]")].map(item=>item.dataset.homeAiCeoNode),
      lines:[...document.querySelectorAll("[data-home-ai-ceo-line]")].map(item=>item.dataset.homeAiCeoLine),
      modules:[...document.querySelectorAll("[data-workflow-module]")].map(item=>item.dataset.workflowModule),
      images:[...document.querySelectorAll("[data-studio-image]")].map(item=>item.dataset.studioImage),
      primary:document.querySelectorAll("[data-home-primary-cta]").length,
      overflow:Math.max(document.documentElement.scrollWidth, document.body.scrollWidth) - innerWidth,
      loginVisible:!!document.querySelector("#topLogin").getClientRects().length,
      previewNotice:!!document.querySelector("#previewNotice"),
      leadFont:parseFloat(getComputedStyle(document.querySelector(".lead")).fontSize),
      h1Font:parseFloat(getComputedStyle(document.querySelector("h1")).fontSize),
      motion:document.querySelector("#motionToggle").getAttribute("aria-pressed")
    }));
    assert.equal(initial.version, "finish-review-v12");
    assert.deepEqual(initial.sections, ["hero", "proof", "capabilities", "workflow", "merchants", "plans"]);
    assert.deepEqual(initial.plans, ["free", "single", "multi"]);
    assert.deepEqual(initial.nodes, approvedHeroNodes);
    assert.deepEqual(initial.lines, approvedHeroNodes);
    assert.deepEqual(initial.modules, ["cockpit", "product", "media", "confirm"]);
    assert.deepEqual(initial.images, approvedImages);
    assert(initial.primary === 1 && initial.loginVisible && !initial.previewNotice && initial.overflow <= 1);
    assert(initial.leadFont >= 15 && initial.h1Font >= 27, name + " typography: " + JSON.stringify({lead:initial.leadFont,h1:initial.h1Font}));
    if (reducedMotion === "reduce") assert.equal(initial.motion, "false");
    await assertHero(page, "market");
    for (const key of approvedHeroNodes) {
      await page.locator('[data-home-ai-ceo-node="' + key + '"]').click();
      await assertHero(page, key);
    }
    const firstNode = page.locator('[data-home-ai-ceo-node="market"]');
    await firstNode.focus();
    await page.keyboard.press("ArrowRight");
    await page.keyboard.press("Enter");
    await assertHero(page, "listing");
    assert(await page.locator('[data-home-ai-ceo-node="listing"]').evaluate(el=>el.matches(":focus-visible")));
    for (const key of approvedWorkflowSteps) {
      await page.locator('[data-home-workflow-step="' + key + '"]').click();
      const state = await workflowSnapshot(page);
      assert(state.synchronized && state.active === key && state.announcement);
      assert.deepEqual(state.steps, approvedWorkflowSteps);
      assert.deepEqual(state.panels, approvedWorkflowSteps);
    }
    await page.locator('[data-home-workflow-jump="facts"]').click();
    assert.equal((await workflowSnapshot(page)).active, "facts");
    await page.locator('[data-home-workflow-jump="research"]').click();
    assert.equal((await workflowSnapshot(page)).active, "research");
    await page.locator('[data-home-workflow-step="listing"]').click();
    if (viewport.width <= 600) assert(await page.locator("#previewListingTitle").evaluate(el=>parseFloat(getComputedStyle(el).fontSize) >= 16), "mobile editor input must remain readable without zoom");
    const original = await page.locator("#previewListingTitle").inputValue();
    await page.locator("#previewListingTitle").fill("Local illustration only");
    assert((await page.locator("#previewListingStatus").textContent()).includes("不会保存"));
    await page.locator("#resetListingPreview").click();
    assert.equal(await page.locator("#previewListingTitle").inputValue(), original);
    await page.locator('[data-home-workflow-step="media"]').click();
    for (const key of approvedImages) {
      await page.locator('[data-studio-image="' + key + '"]').click();
      await assertImage(page, key);
    }
    await page.locator('[data-studio-image="collection"]').focus();
    await page.keyboard.press("ArrowRight");
    await page.keyboard.press("Space");
    await assertImage(page, "suitcase");
    const noOverflow = await page.evaluate(()=>Math.max(document.documentElement.scrollWidth,document.body.scrollWidth) <= innerWidth + 1);
    assert(noOverflow, name + " media panel overflows horizontally");
    await page.locator("#motionToggle").click();
    const toggled = await page.locator("#motionToggle").getAttribute("aria-pressed");
    assert.equal(toggled, reducedMotion === "reduce" ? "true" : "false");
    await page.reload({waitUntil:"load"});
    assert.equal(await page.locator("#motionToggle").getAttribute("aria-pressed"), toggled);
    for (const id of ["topLogin", "heroWorkbenchLogin", "publicWorkbenchEnter", "choosePlan"]) {
      await page.locator("#" + id).click();
      await page.waitForSelector("#nextStepModal.is-open");
      assert(await page.locator("#entryLoginForm").isVisible(), id + " did not open real auth");
      await page.keyboard.press("Escape");
      assert(!(await page.locator("#nextStepModal").isVisible()));
    }
    for (const [plan, text] of [["free", "免费体验"], ["single", "有店铺"], ["multi", "多店铺"]]) {
      await page.locator('[data-plan="' + plan + '"]').click();
      assert(await page.locator('[data-plan="' + plan + '"]').evaluate(el=>el.classList.contains("is-active")));
      await page.locator("#choosePlan").click();
      await page.waitForSelector("#nextStepModal.is-open");
      const body = await page.locator("#nextStepBody").textContent();
      assert(body.includes(text), plan + " was not preserved in genuine entry copy: " + body);
      await page.keyboard.press("Escape");
    }
    assert.deepEqual(errors, [], name + " browser errors");
    return {name, viewport, ...initial, real_ctas_and_plans:true, six_examples:true, four_images:true, editor_reset:true, keyboard:true, motion_persisted:true, ok:true};
  } finally { await context.close(); }
}
async function inspectTouchInteractions(browser) {
  const {context, page, errors} = await newPage(browser, {width:390,height:844}, {isMobile:true,hasTouch:true});
  try {
    await page.locator('[data-home-ai-ceo-node="service"]').tap();
    await assertHero(page,"service");
    await page.locator('[data-home-workflow-step="media"]').tap();
    assert.equal((await workflowSnapshot(page)).active,"media");
    await page.locator('[data-studio-image="packing"]').tap();
    await assertImage(page,"packing");
    assert.deepEqual(errors,[]);
    return {ok:true};
  } finally { await context.close(); }
}
async function inspectJavascriptDisabled(browser) {
  const context = await browser.newContext({viewport:{width:1440,height:1000},javaScriptEnabled:false});
  await installStaticRoute(context);
  const page = await context.newPage();
  try {
    await page.goto(base + "/index.html",{waitUntil:"load"});
    assert(await page.locator("h1").isVisible());
    assert(await page.locator("#plans").isVisible());
    assert(await page.locator('[data-home-workflow-panel="goal"]').isVisible());
    const links = await page.locator('a[href*="assets/workbench-demo/index.html"]').count();
    assert(links > 0, "readable static page must retain the separate demonstration link");
    return {ok:true, public_copy_and_demo_link_readable:true};
  } finally { await context.close(); }
}

async function inspectExpiredSessionHint(browser) {
  const context = await browser.newContext({
    viewport: { width: 820, height: 1180 },
    deviceScaleFactor: 1,
  });
  await installStaticRoute(context);
  const sessionRequests = [];
  // A revoked session includes an explicit refresh rejection. An unmocked
  // network failure is retryable and must not erase the merchant's session hint.
  for (const endpoint of ["/merchant-onboarding/primary-ebay", "/me", "/auth/refresh"]) {
    await context.route(`${base}${endpoint}`, (route) => {
      sessionRequests.push(`${route.request().method()}:${endpoint}`);
      return route.fulfill({
        status: 401,
        contentType: "application/json",
        body: JSON.stringify({ error: endpoint === "/auth/refresh" ? "session_refresh_invalid" : "login_required" }),
      });
    });
  }
  await context.addInitScript(() => {
    localStorage.setItem("jiejing_saas_backend_session_hint", "1");
  });
  const page = await context.newPage();
  const pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(String(error)));
  await page.goto(`${base}/index.html`, { waitUntil: "domcontentloaded", timeout: 60000 });
  await page.locator('[data-home-primary-cta="jiejing_ai_ceo_workspace_v2"]').click();
  await page.waitForSelector("#nextStepModal.is-open", { timeout: 10000 });
  const state = await page.evaluate(() => ({
    login_form_visible: document.querySelector("#entryLoginForm")?.hidden === false,
    mode_area_hidden: document.querySelector("#entryModeArea")?.hidden === true,
    modal_title: document.querySelector("#nextStepTitle")?.textContent.trim() || "",
    auth_status: document.querySelector("#entryAuthStatus")?.textContent.trim() || "",
    stale_hint_cleared: localStorage.getItem("jiejing_saas_backend_session_hint") !== "1",
  }));
  await context.close();
  return {
    ...state,
    session_requests: sessionRequests,
    page_errors: pageErrors,
    ok: state.login_form_visible && state.mode_area_hidden && state.modal_title === "进入捷境账号。" &&
      state.auth_status.includes("登录状态已过期") && state.stale_hint_cleared && pageErrors.length === 0 &&
      JSON.stringify(sessionRequests) === JSON.stringify(["GET:/merchant-onboarding/primary-ebay", "GET:/me", "POST:/auth/refresh"]),
  };
}

async function inspectResponsiveAuth(browser) {
  const results = [];
  for (const viewport of [{ width: 320, height: 568 }, { width: 390, height: 460 }, { width: 390, height: 844 }, { width: 680, height: 700 }, { width: 681, height: 700 }, { width: 720, height: 900 }, { width: 768, height: 900 }, { width: 1024, height: 900 }]) {
    const context = await browser.newContext({ viewport, deviceScaleFactor: 1 });
    await installStaticRoute(context);
    const page = await context.newPage();
    const errors = [];
    const posts = [];
    page.on("pageerror", (error) => errors.push(String(error)));
    page.on("request", (request) => { if (request.method() === "POST" && new URL(request.url()).pathname !== "/analytics/events") posts.push(request.url()); });
    await page.goto(`${base}/index.html`, { waitUntil: "domcontentloaded" });
    await page.evaluate(() => document.fonts.ready);
    await page.locator("#heroWorkbenchLogin").click();
    await page.waitForSelector("#nextStepModal.is-open");
    await page.locator(".entry-modal-panel").evaluate((panel) => Promise.all(
      panel.getAnimations().map((animation) => animation.finished.catch(() => {})),
    ));
    const geometry = await page.evaluate(() => {
      const box = (selector) => document.querySelector(selector).getBoundingClientRect().toJSON();
      const email = box("#entryAuthEmail"), password = box("#entryAuthPassword");
      const title = box("#nextStepTitle"), close = box("#nextStepModal .modal-close");
      const shell = box(".entry-auth-shell");
      const backgroundHidden = ["#top", "#proof", "#main", ".topbar"].every((selector) => !document.querySelector(selector)?.getClientRects().length);
      return { email, password, title, close, shell, backgroundHidden,
        ok: backgroundHidden && [email, password].every((item) => item.width >= 160 && item.left >= 0 && item.right <= innerWidth + 1) &&
          title.top >= 0 && title.width >= 200 && close.top >= 0 && close.bottom <= innerHeight &&
          shell.width >= 260 && shell.left >= 0 && shell.right <= innerWidth + 1 };
    });
    if (geometry.ok) {
      await page.locator("#entryAuthEmail").fill("layout@example.invalid");
      await page.locator("#entryAuthPassword").fill("local-only-not-submitted");
      await page.getByRole("button", { name: "关闭", exact: true }).click();
    }
    const closed = await page.evaluate(() => !document.querySelector("#nextStepModal").classList.contains("is-open"));
    results.push({ viewport, geometry, closed, errors, posts, ok: geometry.ok && closed && errors.length === 0 && posts.length === 0 });
    await context.close();
  }
  return { results, ok: results.every((item) => item.ok) };
}


async function main() {
  const browser = await chromium.launch({channel:browserChannel,headless:true});
  try {
    const results = [];
    for (const [name, viewport, motion] of [
      ["desktop",{width:1440,height:1000},"no-preference"],
      ["tablet",{width:920,height:1000},"no-preference"],
      ["mobile",{width:390,height:844},"no-preference"],
      ["small-mobile",{width:320,height:740},"no-preference"],
      ["reduced-motion",{width:1440,height:1000},"reduce"]
    ]) results.push(await inspectViewport(browser,viewport,name,motion));
    const touchInteractions = await inspectTouchInteractions(browser);
    const javascriptDisabled = await inspectJavascriptDisabled(browser);
    const expiredSessionHint = await inspectExpiredSessionHint(browser);
    const responsiveAuth = await inspectResponsiveAuth(browser);
    const ok = results.every(item=>item.ok) && touchInteractions.ok && javascriptDisabled.ok && expiredSessionHint.ok && responsiveAuth.ok && unexpectedRequests.length === 0;
    console.log(JSON.stringify({ok,results,touch_interactions:touchInteractions,javascript_disabled:javascriptDisabled,expired_session_hint:expiredSessionHint,responsive_auth:responsiveAuth,unexpected_requests:unexpectedRequests,no_login_performed:true,no_real_world_action:true,network_fully_intercepted:true},null,2));
    if (!ok) process.exitCode = 1;
  } finally { await browser.close(); }
}
main().catch(error=>{console.error(error);process.exitCode=1;});
