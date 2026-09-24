#!/usr/bin/env node
/* Public homepage browser smoke at desktop, tablet and mobile sizes.
   It performs no login, charge, OAuth, or platform write. */

const fs = require("fs");
const path = require("path");
const { chromium } = require("../output/codex-playwright-deps/node_modules/playwright-core");

const base = process.env.JIEJING_TEST_BASE || "http://127.0.0.1:8788";
const staticRoot = path.resolve(process.env.JIEJING_LOCAL_STATIC_ROOT || path.join(__dirname, ".."));
const browserChannel = process.env.JIEJING_PLAYWRIGHT_CHANNEL || "chrome";
const approvedMaterialAssets = [
  "/assets/travel-compression-main-v2.webp",
  "/assets/travel-compression-scene-v2.webp",
  "/assets/travel-compression-feature-v2.webp",
  "/assets/travel-compression-detail-v2.webp",
  "/assets/travel-compression-video-cover.webp",
];
const approvedHeroNodes = ["market", "listing", "media", "ads", "service", "finance"];
const approvedHeroLabels = ["市场与货源", "Listing 草稿", "素材工坊", "广告费用", "客服物流", "财务风控"];
const approvedWorkflowSteps = ["goal", "research", "facts", "listing", "media", "confirm"];

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

async function materialSnapshot(page) {
  return page.evaluate(() => {
    const workflow = document.querySelector('[data-home-section="workflow"]');
    const options = Array.from(workflow?.querySelectorAll("button[data-home-material-option]") || []);
    const selected = options.filter((option) => option.getAttribute("aria-pressed") === "true");
    const canvas = workflow?.querySelector('[data-home-material-canvas="active-result"]');
    const image = canvas?.matches("img") ? canvas : canvas?.querySelector("img");
    const title = workflow?.querySelector('[data-home-material-title="active-title"]');
    const purpose = workflow?.querySelector('[data-home-material-purpose="active-purpose"]');
    const status = workflow?.querySelector('[data-home-material-status="listing-draft"]');
    const studio = workflow?.querySelector('[data-home-material-studio="listing-media-v3"]');
    const option = selected[0];
    const selectedSrc = option?.dataset.homeMaterialSrc ? new URL(option.dataset.homeMaterialSrc, location.href).href : "";
    const activeKey = studio?.dataset.homeActiveMaterial || "";
    return {
      selected_count: selected.length,
      selected_key: option?.dataset.homeMaterialOption || "",
      active_key: activeKey,
      image_src: image?.currentSrc || image?.src || "",
      title_text: title?.textContent.trim() || "",
      purpose_text: purpose?.textContent.trim() || "",
      listing_status_text: status?.textContent.trim() || "",
      synchronized: Boolean(
        option && activeKey &&
        option.dataset.homeMaterialOption === activeKey &&
        canvas?.dataset.homeMaterialKey === activeKey &&
        title?.dataset.homeMaterialKey === activeKey &&
        purpose?.dataset.homeMaterialKey === activeKey &&
        status?.dataset.homeMaterialKey === activeKey &&
        selectedSrc === (image?.currentSrc || image?.src || "") &&
        option.dataset.homeMaterialTitleCopy === (title?.textContent.trim() || "") &&
        option.dataset.homeMaterialPurposeCopy === (purpose?.textContent.trim() || "") &&
        status?.textContent.trim()
      ),
    };
  });
}

function materialTransitionIsConsistent(previous, current) {
  return current.selected_count === 1 && current.synchronized &&
    Boolean(current.active_key && current.image_src && current.title_text && current.purpose_text && current.listing_status_text) &&
    current.active_key !== previous.active_key &&
    current.image_src !== previous.image_src &&
    current.title_text !== previous.title_text &&
    current.purpose_text !== previous.purpose_text;
}

async function workflowSnapshot(page) {
  return page.evaluate(() => {
    const scope = document.querySelector('[data-home-workflow="merchant-loop-v1"]');
    const steps = Array.from(scope?.querySelectorAll("button[data-home-workflow-step]") || []);
    const panels = Array.from(scope?.querySelectorAll("[data-home-workflow-panel]") || []);
    const activeSteps = steps.filter((step) => step.getAttribute("aria-pressed") === "true");
    const visiblePanels = panels.filter((panel) => !panel.hidden && panel.getClientRects().length > 0);
    const live = scope?.querySelector('[data-home-workflow-live="active-step"]');
    return {
      step_order: steps.map((step) => step.dataset.homeWorkflowStep),
      panel_order: panels.map((panel) => panel.dataset.homeWorkflowPanel),
      active_step_count: activeSteps.length,
      active_step: activeSteps[0]?.dataset.homeWorkflowStep || "",
      visible_panel_count: visiblePanels.length,
      visible_panel: visiblePanels[0]?.dataset.homeWorkflowPanel || "",
      live_text: live?.textContent.trim() || "",
      keyboard_ready: steps.every((step) => step.tagName === "BUTTON" && step.hasAttribute("aria-pressed")),
      synchronized: Boolean(
        activeSteps.length === 1 && visiblePanels.length === 1 &&
        activeSteps[0].dataset.homeWorkflowStep === visiblePanels[0].dataset.homeWorkflowPanel &&
        live?.textContent.trim()
      ),
    };
  });
}

async function heroInteractionSnapshot(page, key) {
  return page.evaluate((activeKey) => {
    const scope = document.querySelector('[data-home-section="hero"]');
    const nodes = Array.from(scope?.querySelectorAll("button[data-home-ai-ceo-node]") || []);
    const lines = Array.from(scope?.querySelectorAll("path[data-home-ai-ceo-line]") || []);
    const activeNodes = nodes.filter((node) => node.getAttribute("aria-pressed") === "true");
    const activeLines = lines.filter((line) => line.classList.contains("is-active"));
    const target = nodes.find((node) => node.dataset.homeAiCeoNode === activeKey);
    const result = scope?.querySelector('[data-home-ai-ceo-result="active-result"]');
    const focusStyle = target ? getComputedStyle(target) : null;
    return {
      key: activeKey,
      active_node_count: activeNodes.length,
      active_line_count: activeLines.length,
      active_node_key: activeNodes[0]?.dataset.homeAiCeoNode || "",
      active_line_key: activeLines[0]?.dataset.homeAiCeoLine || "",
      result_key: result?.dataset.homeAiCeoResultKey || "",
      result_text: result?.textContent.trim() || "",
      expected_result_text: target?.dataset.homeAiCeoResultCopy?.trim() || "",
      focus_outline_visible: Boolean(
        target?.matches(":focus-visible") &&
        focusStyle?.outlineStyle !== "none" &&
        parseFloat(focusStyle?.outlineWidth || "0") > 0
      ),
    };
  }, key);
}

function heroInteractionIsConsistent(snapshot, requireFocusOutline = false) {
  return snapshot.active_node_count === 1 &&
    snapshot.active_line_count === 1 &&
    snapshot.active_node_key === snapshot.key &&
    snapshot.active_line_key === snapshot.key &&
    snapshot.result_key === snapshot.key &&
    Boolean(snapshot.result_text && snapshot.result_text === snapshot.expected_result_text) &&
    (!requireFocusOutline || snapshot.focus_outline_visible);
}

async function keyboardNavigateAndActivateHeroNode(page, key) {
  for (let index = 0; index < 30; index += 1) {
    await page.keyboard.press("Tab");
    const focusedKey = await page.evaluate(() => document.activeElement?.dataset?.homeAiCeoNode || "");
    if (focusedKey === key) {
      await page.keyboard.press("Enter");
      return true;
    }
  }
  return false;
}

async function keyboardNavigateToMaterialOption(page, key) {
  for (let index = 0; index < 40; index += 1) {
    await page.keyboard.press("Tab");
    const focused = await page.evaluate(() => {
      const element = document.activeElement;
      const style = element ? getComputedStyle(element) : null;
      return {
        key: element?.dataset?.homeMaterialOption || "",
        interactive: Boolean(element && !element.disabled && element.tabIndex >= 0),
        focus_visible: Boolean(
          element?.matches(":focus-visible") &&
          ((style?.outlineStyle !== "none" && parseFloat(style?.outlineWidth || "0") > 0) ||
            (style?.boxShadow && style.boxShadow !== "none"))
        ),
      };
    });
    if (focused.key === key) return { reached: true, ...focused };
  }
  return { reached: false, key: "", interactive: false, focus_visible: false };
}

async function keyboardNavigateAndActivateWorkflowStep(page, key) {
  for (let index = 0; index < 50; index += 1) {
    await page.keyboard.press("Tab");
    const focusedKey = await page.evaluate(() => document.activeElement?.dataset?.homeWorkflowStep || "");
    if (focusedKey === key) {
      await page.keyboard.press("Enter");
      return true;
    }
  }
  return false;
}

async function inspectViewport(browser, viewport, name, reducedMotion = "no-preference") {
  const context = await browser.newContext({ viewport, deviceScaleFactor: 1, reducedMotion });
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
  await page.waitForSelector('[data-home-workflow="merchant-loop-v1"]', { timeout: 20000 });
  const initialWorkflow = await workflowSnapshot(page);
  await page.locator('[data-home-workflow-jump="media"]').click();
  const showcaseWorkflow = await workflowSnapshot(page);
  await page.locator('button[data-home-workflow-step="media"]').click();
  const mediaWorkflow = await workflowSnapshot(page);
  await page.waitForSelector('[data-home-material-studio="listing-media-v3"]', { timeout: 20000 });
  await page.locator('[data-home-material-studio="listing-media-v3"] img').evaluateAll(async (images) => {
    images.forEach((image) => { image.loading = "eager"; });
    await Promise.all(images.map((image) => image.complete ? Promise.resolve() : new Promise((resolve) => {
      image.addEventListener("load", resolve, { once: true });
      image.addEventListener("error", resolve, { once: true });
    })));
  });
  const state = await page.evaluate(() => {
    const planOrder = Array.from(document.querySelectorAll(".path-card[data-plan]")).map((item) => item.dataset.plan);
    const login = document.querySelector("#topLogin");
    const workflowScope = document.querySelector('[data-home-section="workflow"]');
    const workflowImages = Array.from(workflowScope?.querySelectorAll('[data-home-material-studio="listing-media-v3"] img') || []);
    const heroScope = document.querySelector('[data-home-section="hero"]');
    const heroNodeMarkers = Array.from(heroScope?.querySelectorAll("[data-home-ai-ceo-node]") || []);
    const heroNodes = Array.from(heroScope?.querySelectorAll("button[data-home-ai-ceo-node]") || []);
    const heroSvg = heroScope?.querySelector('svg[data-home-ai-ceo-connections="merchant-goal-router-v3"]');
    const heroLineMarkers = Array.from(heroScope?.querySelectorAll("[data-home-ai-ceo-line]") || []);
    const heroLinePaths = Array.from(heroSvg?.querySelectorAll("path[data-home-ai-ceo-line]") || []);
    const materialOptions = Array.from(workflowScope?.querySelectorAll("button[data-home-material-option]") || []);
    const workflowSteps = Array.from(workflowScope?.querySelectorAll("button[data-home-workflow-step]") || []);
    const workflowPanels = Array.from(workflowScope?.querySelectorAll("[data-home-workflow-panel]") || []);
    const activeWorkflowSteps = workflowSteps.filter((step) => step.getAttribute("aria-pressed") === "true");
    const visibleWorkflowPanels = workflowPanels.filter((panel) => !panel.hidden && panel.getClientRects().length > 0);
    const homepageText = Array.from(document.querySelectorAll("[data-home-section]"))
      .map((section) => section.innerText)
      .join(" ");
    const uniqueWorkflowAssets = Array.from(new Set(workflowImages.map((image) => new URL(image.currentSrc || image.src, location.href).pathname)));
    const activeHeroNodes = heroNodes.filter((node) => node.getAttribute("aria-pressed") === "true");
    const activeHeroLines = heroLinePaths.filter((line) => line.classList.contains("is-active"));
    const heroResult = heroScope?.querySelector('[data-home-ai-ceo-result="active-result"]');
    return {
      body_version: document.body.classList.contains("public-home-v3"),
      section_count: document.querySelectorAll("[data-home-section]").length,
      section_order: Array.from(document.querySelectorAll("[data-home-section]")).map((item) => item.dataset.homeSection),
      primary_cta_count: document.querySelectorAll('[data-home-primary-cta="jiejing_ai_ceo_workspace_v2"]').length,
      plan_order: planOrder,
      retired_dom_count: document.querySelectorAll("#retired-public-home-sections, #merchant-guide, #ai-ceo-workbench-technical, #ai-ceo-workbench").length,
      legacy_signal_canvas_count: document.querySelectorAll("#signalCanvas").length,
      hero_core_count: heroScope?.querySelectorAll('[data-home-ai-ceo-core="merchant-goal-router-v3"]').length || 0,
      hero_core_visible: heroScope?.querySelector('[data-home-ai-ceo-core="merchant-goal-router-v3"]')?.getClientRects().length > 0,
      hero_node_marker_count: heroNodeMarkers.length,
      hero_node_button_count: heroNodes.length,
      hero_node_order: heroNodes.map((node) => node.dataset.homeAiCeoNode),
      hero_node_texts: heroNodes.map((node) => node.textContent.trim()),
      hero_node_aria_labels: heroNodes.map((node) => node.getAttribute("aria-label") || ""),
      hero_nodes_keyboard_ready: heroNodes.every((node) => node.tagName === "BUTTON" && node.hasAttribute("aria-pressed")),
      hero_nodes_visible: heroNodes.every((node) => node.getClientRects().length > 0 && getComputedStyle(node).visibility !== "hidden"),
      hero_nodes_clear_of_core: heroNodes.every((node) => {
        const core = heroScope.querySelector('[data-home-ai-ceo-core]')?.getBoundingClientRect();
        const box = node.getBoundingClientRect();
        return core && !(box.left < core.right && box.right > core.left && box.top < core.bottom && box.bottom > core.top);
      }),
      hero_node_mappings_ready: heroNodes.every((node) => Boolean(
        node.dataset.homeAiCeoResultCopy?.trim() &&
        (node.textContent.trim() || node.getAttribute("aria-label")?.trim())
      )),
      hero_initial_active_node_count: activeHeroNodes.length,
      hero_line_marker_count: heroLineMarkers.length,
      hero_line_path_count: heroLinePaths.length,
      hero_line_order: heroLinePaths.map((line) => line.dataset.homeAiCeoLine),
      hero_initial_active_line_count: activeHeroLines.length,
      hero_initial_mapping_ready: Boolean(
        activeHeroNodes.length === 1 && activeHeroLines.length === 1 &&
        activeHeroNodes[0].dataset.homeAiCeoNode === activeHeroLines[0].dataset.homeAiCeoLine &&
        heroResult?.dataset.homeAiCeoResultKey === activeHeroNodes[0].dataset.homeAiCeoNode &&
        heroResult?.textContent.trim() === activeHeroNodes[0].dataset.homeAiCeoResultCopy?.trim()
      ),
      hero_svg_count: heroScope?.querySelectorAll('svg[data-home-ai-ceo-connections="merchant-goal-router-v3"]').length || 0,
      classic_orbit_count: heroScope?.querySelectorAll('[data-home-ai-ceo-layout="classic-orbit-v1"]').length || 0,
      legacy_hero_node_count: heroScope?.querySelectorAll('.home-command-step:not([data-home-ai-ceo-node])').length || 0,
      unmarked_hero_flow_line_count: heroScope?.querySelectorAll('.flow-line path:not([data-home-ai-ceo-line])').length || 0,
      legacy_hero_container_count: heroScope?.querySelectorAll("#signalCanvas, .home-command-steps").length || 0,
      hero_result_visible: heroScope?.querySelector('[data-home-ai-ceo-result="active-result"]')?.getClientRects().length > 0,
      login_is_text: Boolean(login?.classList.contains("button-text")),
      login_visible: Boolean(login?.getClientRects().length && getComputedStyle(login).visibility !== "hidden"),
      work_record_marketing_count: homepageText.includes("工作记录") ? 1 : 0,
      workflow_contract_count: workflowScope?.querySelectorAll('[data-home-workflow="merchant-loop-v1"]').length || 0,
      workflow_step_order: workflowSteps.map((step) => step.dataset.homeWorkflowStep),
      workflow_panel_order: workflowPanels.map((panel) => panel.dataset.homeWorkflowPanel),
      workflow_step_count: workflowSteps.length,
      workflow_initial_active_count: activeWorkflowSteps.length,
      workflow_initial_visible_panel_count: visibleWorkflowPanels.length,
      workflow_initial_synchronized: Boolean(
        activeWorkflowSteps.length === 1 && visibleWorkflowPanels.length === 1 &&
        activeWorkflowSteps[0].dataset.homeWorkflowStep === visibleWorkflowPanels[0].dataset.homeWorkflowPanel
      ),
      workflow_steps_keyboard_ready: workflowSteps.every((step) => step.tagName === "BUTTON" && step.hasAttribute("aria-pressed")),
      workflow_live_ready: Boolean(workflowScope?.querySelector('[data-home-workflow-live="active-step"][aria-live="polite"]')),
      workflow_workspace_cta_count: workflowScope?.querySelectorAll('[data-home-workflow-cta="workspace"]').length || 0,
      material_stage_order: Array.from(workflowScope?.querySelectorAll("[data-home-material-stage]") || []).map((item) => item.dataset.homeMaterialStage),
      material_task_order: Array.from(workflowScope?.querySelectorAll("[data-home-material-task]") || []).map((item) => item.dataset.homeMaterialTask),
      material_input_visible: workflowScope?.querySelector('[data-home-material-stage="input"]')?.getClientRects().length > 0,
      material_tasks_visible: Array.from(workflowScope?.querySelectorAll("[data-home-material-task]") || []).length === 4 &&
        Array.from(workflowScope?.querySelectorAll("[data-home-material-task]") || []).every((item) => item.getClientRects().length > 0),
      material_option_count: materialOptions.length,
      material_selected_count: materialOptions.filter((option) => option.getAttribute("aria-pressed") === "true").length,
      material_options_keyboard_ready: materialOptions.every((option) => option.tagName === "BUTTON" && option.hasAttribute("aria-pressed")),
      material_option_accessible_names_ready: materialOptions.every((option) => {
        const accessibleName = option.getAttribute("aria-label")?.trim() || option.textContent.trim();
        const title = option.dataset.homeMaterialTitleCopy?.trim() || "";
        return Boolean(accessibleName && title && accessibleName.includes(title));
      }),
      material_canvas_visible: workflowScope?.querySelector('[data-home-material-canvas="active-result"]')?.getClientRects().length > 0,
      material_title_visible: workflowScope?.querySelector('[data-home-material-title="active-title"]')?.getClientRects().length > 0,
      material_purpose_visible: workflowScope?.querySelector('[data-home-material-purpose="active-purpose"]')?.getClientRects().length > 0,
      material_listing_state_visible: Boolean(
        workflowScope?.querySelector('[data-home-material-status="listing-draft"]')?.getClientRects().length &&
        workflowScope?.querySelector('[data-home-material-status="listing-draft"]')?.textContent.trim()
      ),
      material_caption_exact: workflowScope?.querySelector(".home-example-caption")?.textContent.trim() === "流程示例｜实际结果以商家提供的商品资料与审核为准。",
      workflow_image_dom_count: workflowImages.length,
      workflow_unique_assets: uniqueWorkflowAssets,
      workflow_images_loaded: workflowImages.every((image) => image.complete && image.naturalWidth > 0),
      reduced_motion_marker: workflowScope?.querySelector('[data-home-motion-policy="respect-reduced-motion"]') !== null,
      auto_rotate_state: workflowScope?.querySelector('[data-home-material-studio="listing-media-v3"]')?.dataset.homeAutoRotate,
      horizontal_overflow: Math.max(0, document.documentElement.scrollWidth - document.documentElement.clientWidth),
      hero_type: (() => {
        const heading = heroScope?.querySelector("h1");
        const style = heading && getComputedStyle(heading);
        const size = parseFloat(style?.fontSize || "0");
        const width = heading?.getBoundingClientRect().width || 0;
        const lineHeight = parseFloat(style?.lineHeight || "0");
        return {
          font_size: size,
          line_height_ratio: size ? lineHeight / size : 0,
          column_size_ratio: width ? size / width : 1,
          readable: Boolean(size >= 32 && lineHeight >= size * 1.1 && width >= size / 0.14),
        };
      })(),
    };
  });
  state.workflow_default_goal = initialWorkflow.synchronized && initialWorkflow.active_step === "goal";
  state.showcase_opens_media = showcaseWorkflow.synchronized && showcaseWorkflow.active_step === "media";
  state.workflow_pointer_switch = mediaWorkflow.synchronized && mediaWorkflow.active_step === "media";
  if (name !== "reduced-motion") {
    await page.screenshot({ path: path.join("output", "browser-smoke", `homepage-maturity-${name}.png`), fullPage: true });
  }
  if (name === "mobile") {
    await page.locator('[data-home-example="travel-compression-workflow-v1"]').screenshot({
      path: path.join("output", "browser-smoke", "homepage-maturity-mobile-workflow.png"),
    });
  }
  if (name === "desktop") {
    const materialOptions = page.locator("button[data-home-material-option]");
    const studio = page.locator('[data-home-material-studio="listing-media-v3"]');
    const rotateInterval = Number(await studio.getAttribute("data-home-rotate-interval-ms"));
    state.material_rotate_interval_valid = Number.isFinite(rotateInterval) && rotateInterval >= 5000 && rotateInterval <= 7000;
    const initialMaterial = await materialSnapshot(page);
    await page.waitForTimeout(300);
    const staticMaterial = await materialSnapshot(page);
    state.material_default_static = JSON.stringify(initialMaterial) === JSON.stringify(staticMaterial) &&
      await studio.getAttribute("data-home-auto-rotate") === "false";
    const optionKeys = await materialOptions.evaluateAll((options) => options.map((option) => option.dataset.homeMaterialOption));
    const firstTargetIndex = optionKeys.findIndex((key) => key !== staticMaterial.active_key);
    await materialOptions.nth(firstTargetIndex).click();
    const firstUserMaterial = await materialSnapshot(page);
    const exercisedKeys = [firstUserMaterial.active_key];
    state.material_first_user_switch = materialTransitionIsConsistent(staticMaterial, firstUserMaterial);
    let priorMaterial = firstUserMaterial;
    const remainingIndices = Array.from({ length: optionKeys.length - 1 }, (_, offset) => (firstTargetIndex + offset + 1) % optionKeys.length);
    let keyboardTransitionsSynchronized = true;
    let keyboardFocusReady = true;
    let enterTransitionVerified = false;
    let spaceTransitionVerified = false;
    for (let index = 0; index < remainingIndices.length; index += 1) {
      const targetKey = optionKeys[remainingIndices[index]];
      const focusState = await keyboardNavigateToMaterialOption(page, targetKey);
      keyboardFocusReady = keyboardFocusReady && focusState.reached && focusState.interactive && focusState.focus_visible;
      const keyAction = index % 2 === 0 ? "Enter" : "Space";
      await page.keyboard.press(keyAction);
      const nextMaterial = await materialSnapshot(page);
      const transitionSynchronized = materialTransitionIsConsistent(priorMaterial, nextMaterial);
      keyboardTransitionsSynchronized = keyboardTransitionsSynchronized && transitionSynchronized;
      if (keyAction === "Enter") enterTransitionVerified = enterTransitionVerified || transitionSynchronized;
      if (keyAction === "Space") spaceTransitionVerified = spaceTransitionVerified || transitionSynchronized;
      exercisedKeys.push(nextMaterial.active_key);
      priorMaterial = nextMaterial;
    }
    state.material_first_user_switch = state.material_first_user_switch && keyboardTransitionsSynchronized;
    state.material_all_options_exercised = JSON.stringify([...new Set(exercisedKeys)].sort()) === JSON.stringify([...optionKeys].sort());
    state.material_keyboard_focus_ready = keyboardFocusReady;
    state.material_enter_selection = enterTransitionVerified;
    state.material_space_selection = spaceTransitionVerified;
    state.material_user_stops_rotation = await studio.getAttribute("data-home-auto-rotate") === "false";
    await page.reload({ waitUntil: "domcontentloaded", timeout: 60000 });
    await page.waitForSelector('button[data-home-ai-ceo-node="listing"]', { timeout: 20000 });
    state.hero_keyboard_navigated = await keyboardNavigateAndActivateHeroNode(page, "listing");
    const focusHeroState = await heroInteractionSnapshot(page, "listing");
    await page.locator('button[data-home-ai-ceo-node="media"]').hover();
    const hoverHeroState = await heroInteractionSnapshot(page, "media");
    await page.locator('button[data-home-ai-ceo-node="finance"]').click();
    const clickHeroState = await heroInteractionSnapshot(page, "finance");
    state.hero_keyboard_relation_active = heroInteractionIsConsistent(focusHeroState, true);
    state.hero_pointer_relation_active = heroInteractionIsConsistent(hoverHeroState) && heroInteractionIsConsistent(clickHeroState);
    state.workflow_keyboard_navigated = await keyboardNavigateAndActivateWorkflowStep(page, "confirm");
    const keyboardWorkflow = await workflowSnapshot(page);
    state.workflow_keyboard_switch = keyboardWorkflow.synchronized && keyboardWorkflow.active_step === "confirm";
    await page.click('[data-home-workflow-cta="workspace"]');
    await page.waitForSelector("#nextStepModal.is-open", { timeout: 10000 });
    state.workflow_cta_opens_entry = await page.evaluate(() => ({
      auth_mode: document.body.classList.contains("is-auth-mode"),
      login_form_visible: document.querySelector("#entryLoginForm")?.hidden === false,
      modal_title: document.querySelector("#nextStepTitle")?.textContent.trim() || "",
    }));
    await page.keyboard.press("Escape");
    await page.waitForFunction(() => !document.querySelector("#nextStepModal")?.classList.contains("is-open"), null, { timeout: 10000 });
    await page.click('[data-home-primary-cta="jiejing_ai_ceo_workspace_v2"]');
    await page.waitForSelector("#nextStepModal.is-open", { timeout: 10000 });
    state.primary_cta_opens_auth = await page.evaluate(() => document.body.classList.contains("is-auth-mode"));
  }
  if (name === "reduced-motion") {
    const studio = page.locator('[data-home-material-studio="listing-media-v3"]');
    const rotateInterval = Number(await studio.getAttribute("data-home-rotate-interval-ms"));
    const reducedBefore = await materialSnapshot(page);
    state.reduced_motion_static = await page.evaluate(() => {
      const scope = document.querySelector('[data-home-section="hero"]');
      const animated = Array.from(scope?.querySelectorAll('[data-home-ai-ceo-core], path[data-home-ai-ceo-line], button[data-home-ai-ceo-node][aria-pressed="true"]') || []);
      const stylesAreStatic = (element, pseudo) => {
        const style = getComputedStyle(element, pseudo);
        const names = style.animationName.split(",").map((name) => name.trim());
        const durations = style.animationDuration.split(",").map((duration) => parseFloat(duration) || 0);
        return names.every((name) => name === "none") || durations.every((duration) => duration === 0);
      };
      return animated.length === 8 && animated.every((item) =>
        stylesAreStatic(item, null) && stylesAreStatic(item, "::before") && stylesAreStatic(item, "::after")
      );
    });
    await page.waitForTimeout(rotateInterval + 300);
    const reducedAfter = await materialSnapshot(page);
    state.reduced_motion_no_rotation = JSON.stringify(reducedBefore) === JSON.stringify(reducedAfter);
  }
  await context.close();
  return { name, viewport, ...state, page_errors: pageErrors, console_issues: consoleIssues, bad_responses: badResponses };
}

async function inspectTouchInteractions(browser) {
  const context = await browser.newContext({
    viewport: { width: 390, height: 844 },
    deviceScaleFactor: 1,
    hasTouch: true,
    isMobile: true,
    reducedMotion: "no-preference",
  });
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
  await page.locator('button[data-home-workflow-step="media"]').tap();
  const workflowTap = await workflowSnapshot(page);
  const studio = page.locator('[data-home-material-studio="listing-media-v3"]');
  await studio.waitFor({ state: "visible", timeout: 20000 });
  const rotateInterval = Number(await studio.getAttribute("data-home-rotate-interval-ms"));
  const initial = await materialSnapshot(page);
  const materialOptions = page.locator("button[data-home-material-option]");
  const optionKeys = await materialOptions.evaluateAll((options) => options.map((option) => option.dataset.homeMaterialOption));
  const targetIndex = optionKeys.findIndex((key) => key !== initial.active_key);
  await materialOptions.nth(targetIndex).tap();
  const tapped = await materialSnapshot(page);
  await page.waitForTimeout(rotateInterval + 300);
  const held = await materialSnapshot(page);
  const materialTapStopsRotation =
    rotateInterval >= 5000 && rotateInterval <= 7000 &&
    materialTransitionIsConsistent(initial, tapped) &&
    JSON.stringify(tapped) === JSON.stringify(held) &&
    await studio.getAttribute("data-home-auto-rotate") === "false";
  await page.locator('button[data-home-ai-ceo-node="service"]').tap();
  const heroTap = await heroInteractionSnapshot(page, "service");
  await context.close();
  return {
    material_tap_was_first_user_input: materialTapStopsRotation,
    workflow_tap_active: workflowTap.synchronized && workflowTap.active_step === "media",
    hero_tap_active: heroInteractionIsConsistent(heroTap),
    page_errors: pageErrors,
    console_issues: consoleIssues,
    bad_responses: badResponses,
    ok: materialTapStopsRotation && workflowTap.synchronized && workflowTap.active_step === "media" && heroInteractionIsConsistent(heroTap) && pageErrors.length === 0 && consoleIssues.length === 0 && badResponses.length === 0,
  };
}

async function inspectKeyboardFirstStop(browser) {
  const context = await browser.newContext({
    viewport: { width: 1440, height: 1000 },
    deviceScaleFactor: 1,
    reducedMotion: "no-preference",
  });
  await installStaticRoute(context);
  const page = await context.newPage();
  const pageErrors = [];
  const badResponses = [];
  page.on("pageerror", (error) => pageErrors.push(String(error)));
  page.on("response", (response) => {
    if (response.status() >= 500) badResponses.push({ url: response.url(), status: response.status() });
  });
  await page.goto(`${base}/index.html`, { waitUntil: "domcontentloaded", timeout: 60000 });
  const workflowKeyboardReached = await keyboardNavigateAndActivateWorkflowStep(page, "media");
  const workflowKeyboardState = await workflowSnapshot(page);
  const studio = page.locator('[data-home-material-studio="listing-media-v3"]');
  await studio.waitFor({ state: "visible", timeout: 20000 });
  const rotateInterval = Number(await studio.getAttribute("data-home-rotate-interval-ms"));
  const initial = await materialSnapshot(page);
  const optionKeys = await page.locator("button[data-home-material-option]").evaluateAll((options) => options.map((option) => option.dataset.homeMaterialOption));
  const targetKey = optionKeys.find((key) => key !== initial.active_key);
  const focusState = await keyboardNavigateToMaterialOption(page, targetKey);
  await page.keyboard.press("Enter");
  const activated = await materialSnapshot(page);
  await page.waitForTimeout(rotateInterval + 300);
  const held = await materialSnapshot(page);
  const keyboardFirstStopsRotation =
    rotateInterval >= 5000 && rotateInterval <= 7000 &&
    focusState.reached && focusState.interactive && focusState.focus_visible &&
    materialTransitionIsConsistent(initial, activated) &&
    JSON.stringify(activated) === JSON.stringify(held) &&
    await studio.getAttribute("data-home-auto-rotate") === "false";
  await context.close();
  return {
    keyboard_first_activation: "Enter",
    workflow_keyboard_activation: workflowKeyboardReached && workflowKeyboardState.synchronized && workflowKeyboardState.active_step === "media",
    keyboard_first_stops_rotation: keyboardFirstStopsRotation,
    page_errors: pageErrors,
    bad_responses: badResponses,
    ok: workflowKeyboardReached && workflowKeyboardState.synchronized && workflowKeyboardState.active_step === "media" && keyboardFirstStopsRotation && pageErrors.length === 0 && badResponses.length === 0,
  };
}

async function inspectJavascriptDisabled(browser) {
  const context = await browser.newContext({
    viewport: { width: 1440, height: 1000 },
    deviceScaleFactor: 1,
    javaScriptEnabled: false,
  });
  await installStaticRoute(context);
  const page = await context.newPage();
  const badResponses = [];
  page.on("response", (response) => {
    if (response.status() >= 500) badResponses.push({ url: response.url(), status: response.status() });
  });
  await page.goto(`${base}/index.html`, { waitUntil: "load", timeout: 60000 });
  const studio = page.locator('[data-home-material-studio="listing-media-v3"]');
  await studio.waitFor({ state: "visible", timeout: 20000 });
  const firstImage = studio.locator('[data-home-material-canvas="active-result"][src], [data-home-material-canvas="active-result"] img').first();
  await firstImage.scrollIntoViewIfNeeded();
  await firstImage.evaluate((image) => {
    if (image.complete) return image.naturalWidth > 0;
    return new Promise((resolve) => {
      image.addEventListener("load", () => resolve(image.naturalWidth > 0), { once: true });
      image.addEventListener("error", () => resolve(false), { once: true });
    });
  });
  const state = await page.evaluate(() => {
    const scope = document.querySelector('[data-home-material-studio="listing-media-v3"]');
    const workflow = document.querySelector('[data-home-workflow="merchant-loop-v1"]');
    const workflowPanels = Array.from(workflow?.querySelectorAll("[data-home-workflow-panel]") || []);
    const canvas = scope?.querySelector('[data-home-material-canvas="active-result"]');
    const image = canvas?.matches("img") ? canvas : canvas?.querySelector("img");
    const title = scope?.querySelector('[data-home-material-title="active-title"]');
    const purpose = scope?.querySelector('[data-home-material-purpose="active-purpose"]');
    const status = scope?.querySelector('[data-home-material-status="listing-draft"]');
    const caption = scope?.querySelector(".home-example-caption");
    return {
      workflow_panel_order: workflowPanels.map((panel) => panel.dataset.homeWorkflowPanel),
      workflow_panels_readable: workflowPanels.length === 6 && workflowPanels.every((panel) => panel.getClientRects().length > 0 && panel.textContent.trim()),
      studio_visible: scope?.getClientRects().length > 0,
      first_image_visible: image?.getClientRects().length > 0,
      first_image_loaded: Boolean(image?.complete && image?.naturalWidth > 0),
      first_title_visible: Boolean(title?.getClientRects().length && title.textContent.trim()),
      first_purpose_visible: Boolean(purpose?.getClientRects().length && purpose.textContent.trim()),
      listing_status_visible: Boolean(status?.getClientRects().length && status.textContent.trim()),
      caption_exact: caption?.getClientRects().length > 0 && caption.textContent.trim() === "流程示例｜实际结果以商家提供的商品资料与审核为准。",
    };
  });
  await context.close();
  return {
    ...state,
    bad_responses: badResponses,
    ok: JSON.stringify(state.workflow_panel_order) === JSON.stringify(approvedWorkflowSteps) && state.workflow_panels_readable && state.studio_visible && state.first_image_visible && state.first_image_loaded && state.first_title_visible && state.first_purpose_visible && state.listing_status_visible && state.caption_exact && badResponses.length === 0,
  };
}

async function inspectExpiredSessionHint(browser) {
  const context = await browser.newContext({
    viewport: { width: 820, height: 1180 },
    deviceScaleFactor: 1,
  });
  await installStaticRoute(context);
  await context.route(`${base}/merchant-onboarding/primary-ebay`, (route) => route.fulfill({
    status: 401,
    contentType: "application/json",
    body: JSON.stringify({ error: "login_required" }),
  }));
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
    page_errors: pageErrors,
    ok: state.login_form_visible && state.mode_area_hidden && state.modal_title === "进入捷境账号。" &&
      state.auth_status.includes("登录状态已过期") && state.stale_hint_cleared && pageErrors.length === 0,
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
    page.on("request", (request) => { if (request.method() === "POST") posts.push(request.url()); });
    await page.goto(`${base}/index.html`, { waitUntil: "domcontentloaded" });
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
      return { email, password, title, close, shell,
        ok: [email, password].every((item) => item.width >= 160 && item.left >= 0 && item.right <= innerWidth + 1) &&
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
  const browser = await chromium.launch({ channel: browserChannel, headless: true });
  try {
    const results = [];
    for (const item of [
      ["desktop", { width: 1440, height: 1000 }, "no-preference"],
      ["tablet", { width: 1024, height: 900 }, "no-preference"],
      ["mobile", { width: 390, height: 844 }, "no-preference"],
      ["reduced-motion", { width: 1440, height: 1000 }, "reduce"],
    ]) {
      results.push(await inspectViewport(browser, item[1], item[0], item[2]));
    }
    const keyboardFirst = await inspectKeyboardFirstStop(browser);
    const touchInteractions = await inspectTouchInteractions(browser);
    const javascriptDisabled = await inspectJavascriptDisabled(browser);
    const expiredSessionHint = await inspectExpiredSessionHint(browser);
    const responsiveAuth = await inspectResponsiveAuth(browser);
    const ok = responsiveAuth.ok && keyboardFirst.ok && touchInteractions.ok && javascriptDisabled.ok && expiredSessionHint.ok && results.every(
      (item) =>
        item.body_version &&
        item.section_count === 6 &&
        JSON.stringify(item.section_order) === JSON.stringify(["hero", "proof", "capabilities", "workflow", "merchants", "plans"]) &&
        item.primary_cta_count === 1 &&
        JSON.stringify(item.plan_order) === JSON.stringify(["free", "single", "multi"]) &&
        item.retired_dom_count === 0 &&
        item.legacy_signal_canvas_count === 0 &&
        item.hero_core_count === 1 &&
        item.hero_core_visible &&
        item.hero_node_marker_count === 6 &&
        item.hero_node_button_count === 6 &&
        JSON.stringify(item.hero_node_order) === JSON.stringify(approvedHeroNodes) &&
        item.hero_nodes_keyboard_ready &&
        item.hero_nodes_visible &&
        item.hero_nodes_clear_of_core &&
        item.hero_node_mappings_ready &&
        item.hero_node_texts.every((text, index) => text.includes(approvedHeroLabels[index]) || item.hero_node_aria_labels[index].includes(approvedHeroLabels[index])) &&
        item.hero_initial_active_node_count === 1 &&
        item.hero_line_marker_count === 6 &&
        item.hero_line_path_count === 6 &&
        JSON.stringify(item.hero_line_order) === JSON.stringify(approvedHeroNodes) &&
        item.hero_initial_active_line_count === 1 &&
        item.hero_initial_mapping_ready &&
        item.hero_svg_count === 1 &&
        item.classic_orbit_count === 1 &&
        item.legacy_hero_node_count === 0 &&
        item.unmarked_hero_flow_line_count === 0 &&
        item.legacy_hero_container_count === 0 &&
        item.login_is_text &&
        item.login_visible &&
        item.work_record_marketing_count === 0 &&
        item.workflow_contract_count === 1 &&
        item.workflow_step_count === 6 &&
        JSON.stringify(item.workflow_step_order) === JSON.stringify(approvedWorkflowSteps) &&
        JSON.stringify(item.workflow_panel_order) === JSON.stringify(approvedWorkflowSteps) &&
        item.workflow_initial_active_count === 1 &&
        item.workflow_initial_visible_panel_count === 1 &&
        item.workflow_initial_synchronized &&
        item.workflow_steps_keyboard_ready &&
        item.workflow_live_ready &&
        item.workflow_workspace_cta_count === 1 &&
        item.workflow_default_goal &&
        item.showcase_opens_media &&
        item.workflow_pointer_switch &&
        JSON.stringify(item.material_stage_order) === JSON.stringify(["input", "generation", "review", "listing"]) &&
        JSON.stringify(item.material_task_order) === JSON.stringify(["main", "scene", "selling-points", "detail"]) &&
        item.material_input_visible &&
        item.material_tasks_visible &&
        item.material_option_count === 5 &&
        item.material_selected_count === 1 &&
        item.material_options_keyboard_ready &&
        item.material_option_accessible_names_ready &&
        item.material_canvas_visible &&
        item.material_title_visible &&
        item.material_purpose_visible &&
        item.material_listing_state_visible &&
        item.material_caption_exact &&
        item.workflow_image_dom_count >= 5 &&
        JSON.stringify([...item.workflow_unique_assets].sort()) === JSON.stringify([...approvedMaterialAssets].sort()) &&
        item.workflow_images_loaded &&
        item.reduced_motion_marker &&
        item.auto_rotate_state === "false" &&
        item.horizontal_overflow <= 1 &&
        item.hero_type.readable &&
        item.page_errors.length === 0 &&
        item.console_issues.length === 0 &&
        item.bad_responses.length === 0 &&
        (item.name !== "desktop" || (item.primary_cta_opens_auth === true && item.material_rotate_interval_valid === true && item.material_default_static === true && item.material_first_user_switch === true && item.material_all_options_exercised === true && item.material_keyboard_focus_ready === true && item.material_enter_selection === true && item.material_space_selection === true && item.material_user_stops_rotation === true && item.hero_keyboard_navigated === true && item.hero_keyboard_relation_active === true && item.hero_pointer_relation_active === true && item.workflow_keyboard_navigated === true && item.workflow_keyboard_switch === true && item.workflow_cta_opens_entry?.auth_mode === true && item.workflow_cta_opens_entry?.login_form_visible === true && Boolean(item.workflow_cta_opens_entry?.modal_title))) &&
        (item.name !== "reduced-motion" || (item.reduced_motion_static === true && item.reduced_motion_no_rotation === true)),
    );
    console.log(JSON.stringify({ ok, results, keyboard_first: keyboardFirst, touch_interactions: touchInteractions, javascript_disabled: javascriptDisabled, expired_session_hint: expiredSessionHint, responsive_auth: responsiveAuth, no_login_performed: true, no_real_world_action: true }, null, 2));
    if (!ok) process.exitCode = 1;
  } finally {
    await browser.close();
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
