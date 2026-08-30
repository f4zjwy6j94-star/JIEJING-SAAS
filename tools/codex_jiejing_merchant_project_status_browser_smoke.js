#!/usr/bin/env node
/* Browser contract for one backend-authoritative merchant project status.
   Uses an isolated local account and local product facts only. It does not
   trigger eBay OAuth, platform writes, charges, refunds, or media spend. */

const fs = require("fs");
const net = require("net");
const os = require("os");
const path = require("path");
const { spawn } = require("child_process");
const { chromium } = require("../output/codex-playwright-deps/node_modules/playwright-core");

let base = process.env.JIEJING_TEST_BASE || "";
const localStaticRoot = path.resolve(process.env.JIEJING_LOCAL_STATIC_ROOT || path.join(__dirname, ".."));
const browserChannel = process.env.JIEJING_PLAYWRIGHT_CHANNEL || "chrome";
const projectId = `project-incense-browser-${Date.now()}`;

function reserveLocalPort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.unref();
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      const port = address && typeof address === "object" ? address.port : 0;
      server.close((error) => (error ? reject(error) : resolve(port)));
    });
  });
}

async function waitForOwnedBackend(backendBase, child) {
  const deadline = Date.now() + 30000;
  while (Date.now() < deadline) {
    if (child.exitCode !== null) throw new Error(`isolated backend exited before health check: ${child.exitCode}`);
    try {
      const response = await fetch(`${backendBase}/health`, { cache: "no-store" });
      if (response.ok) return;
    } catch (_error) {
      // The isolated backend may still be initializing its local schema.
    }
    await new Promise((resolve) => setTimeout(resolve, 150));
  }
  throw new Error("isolated backend did not become healthy within 30 seconds");
}

async function startOwnedBackend() {
  const tempParent = path.resolve(os.tmpdir());
  const tempRoot = fs.mkdtempSync(path.join(tempParent, "jiejing-project-status-smoke-"));
  const port = await reserveLocalPort();
  const python = process.env.JIEJING_TEST_PYTHON || (process.platform === "win32" ? "python" : "python3");
  const child = spawn(
    python,
    [
      path.join(localStaticRoot, "tools", "jiejing_saas_backend_cli.py"),
      "serve",
      "--db",
      path.join(tempRoot, "jiejing.sqlite3"),
      "--runtime-db",
      path.join(tempRoot, "runtime.sqlite3"),
      "--output-root",
      path.join(tempRoot, "runtime-output"),
      "--host",
      "127.0.0.1",
      "--port",
      String(port),
    ],
    {
      cwd: localStaticRoot,
      env: {
        ...process.env,
        JIEJING_ENVIRONMENT: "development",
        JIEJING_ENABLE_REAL_PLATFORM_WRITES: "0",
        JIEJING_EBAY_WRITE_ADAPTER_ENABLED: "0",
      },
      stdio: ["ignore", "pipe", "pipe"],
      windowsHide: true,
    },
  );
  child.stdout.resume();
  child.stderr.resume();
  const backendBase = `http://127.0.0.1:${port}`;
  try {
    await waitForOwnedBackend(backendBase, child);
    return { child, tempRoot, tempParent, backendBase };
  } catch (error) {
    child.kill();
    throw error;
  }
}

async function stopOwnedBackend(owned) {
  if (!owned) return;
  if (owned.child.exitCode === null) {
    owned.child.kill();
    await Promise.race([
      new Promise((resolve) => owned.child.once("exit", resolve)),
      new Promise((resolve) => setTimeout(resolve, 5000)),
    ]);
    if (owned.child.exitCode === null) owned.child.kill("SIGKILL");
  }
  const resolvedRoot = path.resolve(owned.tempRoot);
  if (path.dirname(resolvedRoot) === owned.tempParent && path.basename(resolvedRoot).startsWith("jiejing-project-status-smoke-")) {
    fs.rmSync(resolvedRoot, { recursive: true, force: true });
  }
}

async function api(pathname, { token = "", method = "GET", body } = {}) {
  const response = await fetch(`${base}${pathname}`, {
    method,
    cache: "no-store",
    headers: {
      "content-type": "application/json",
      ...(token ? { authorization: `Bearer ${token}` } : {}),
    },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
  const text = await response.text();
  let json = null;
  try {
    json = text ? JSON.parse(text) : null;
  } catch (_error) {
    json = { raw: text.slice(0, 500) };
  }
  if (!response.ok) {
    throw new Error(`${method} ${pathname} failed: ${response.status} ${JSON.stringify(json).slice(0, 500)}`);
  }
  return json;
}

function localStaticPath(requestUrl) {
  const url = new URL(requestUrl);
  const pathname = decodeURIComponent(url.pathname.replace(/^\/+/, "")) || "index.html";
  const allowed =
    ["app.html", "index.html", "app.js", "styles.css", "privacy.html", "terms.html", "refund-policy.html", "support.html", "risk-disclosure.html"].includes(pathname) ||
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

async function runSmoke() {
  const suffix = `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  const email = `codex-project-status-${suffix}@local.invalid`;
  const registered = await api("/auth/register", {
    method: "POST",
    body: {
      email,
      password: `Codex-project-status-${suffix}`,
      company_name: "Codex Merchant Project Status",
    },
  });
  const token = registered.token;
  const user = registered.user || {};
  const company = registered.company || {};
  const createdStore = await api("/stores", {
    token,
    method: "POST",
    body: {
      platform: "ebay",
      store_name: "Codex Incense Status Store",
      marketplace: "EBAY_US",
      stage: "store_opened",
      settings: { created_from: "merchant_project_status_browser_smoke" },
    },
  });
  const store = createdStore.store || {};
  const listingProjectIdentity = {
    key: projectId,
    source_report_id: "",
    candidate_id: "candidate-incense-browser",
  };
  const savedFacts = await api(`/stores/${encodeURIComponent(store.store_id)}/product-facts`, {
    token,
    method: "POST",
    body: {
      listing_project_identity: listingProjectIdentity,
      merchant_product_fact_packet: {
        contract_version: "merchant_product_fact_packet_v1",
        source_mode: "merchant_source_supplied",
        product_name: "禅意佛手托莲花倒流香炉",
        merchant_confirmed_facts: {
          product_name: "禅意佛手托莲花倒流香炉",
          sku: "JJ-INCENSE-BROWSER-01",
          material: "树脂",
          package_weight_g: "451",
          package_length_cm: "16.2",
          package_width_cm: "7.7",
          package_height_cm: "17.9",
          condition: "NEW",
          quantity: "1",
        },
        unknown_facts: [],
        source_records: [{ type: "merchant_product_link", url: "https://example.invalid/incense-source", rights_status: "not_applicable" }],
        blocked_by: [],
        secret_exposed: false,
      },
    },
  });

  const expectedSnapshot = (await api(
    `/stores/${encodeURIComponent(store.store_id)}/merchant-project-status?project_id=${encodeURIComponent(projectId)}`,
    { token },
  )).merchant_project_status;
  if (expectedSnapshot?.snapshot_version !== "merchant_project_status_v1") {
    throw new Error("backend did not return merchant_project_status_v1");
  }
  if (expectedSnapshot?.work_record_index?.contract_version !== "merchant_project_work_record_index_v1") {
    throw new Error("backend did not return the project-scoped work record index");
  }
  const expectedWorkRecordIds = new Set((expectedSnapshot.work_record_index.items || []).map((item) => item.record_id));
  if (!expectedWorkRecordIds.has(savedFacts.task?.task_id) || !expectedWorkRecordIds.has(savedFacts.report?.report_id)) {
    throw new Error("saved product facts task/report were not indexed under the current project");
  }
  if (expectedSnapshot.blocker?.key === "project_evidence_missing") {
    const taskPayload = await api("/tasks?limit=20", { token });
    const taskDiagnostics = (taskPayload.tasks || []).map((item) => ({
      task_id: item.task_id || "",
      company_id: item.company_id || "",
      store_id: item.store_id || "",
      task_type: item.task_type || "",
      created_at: item.created_at || "",
      updated_at: item.updated_at || "",
      listing_project_identity: item.input?.listing_project_identity || null,
    }));
    throw new Error(
      `saved product facts were not visible to project status: ${JSON.stringify({
        response_identity: savedFacts.listing_project_identity || null,
        evidence_cutoff: expectedSnapshot.evidence_cutoff || "",
        task_diagnostics: taskDiagnostics,
      })}`,
    );
  }

  const browser = await chromium.launch({ channel: browserChannel, headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, deviceScaleFactor: 1 });
  const baseUrl = new URL(base);
  await context.addCookies([
    {
      name: "jiejing_saas_session",
      value: token,
      domain: baseUrl.hostname,
      path: "/",
      httpOnly: true,
      secure: baseUrl.protocol === "https:",
      sameSite: "Lax",
    },
  ]);
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
  const accountKey = String(user.user_id || email).toLowerCase();
  await context.addInitScript(
    (seed) => {
      localStorage.setItem("jiejing_saas_api_base", seed.base);
      localStorage.setItem("jiejing_saas_backend_session_hint", "1");
      localStorage.setItem("jiejing_saas_session_hint", "1");
      localStorage.setItem("jiejing_saas_last_account", seed.accountKey);
      localStorage.setItem("jiejing_saas_backend_store_id", seed.storeId);
      localStorage.setItem(`jiejing_saas_onboarding_done:${seed.accountKey}`, "1");
      localStorage.setItem(
        "jiejing_saas_known_accounts",
        JSON.stringify([
          {
            account_key: seed.accountKey,
            user_id: seed.userId,
            email: seed.email,
            company_id: seed.companyId,
            display_name: "Codex Merchant Project Status",
            last_seen: new Date().toISOString(),
          },
        ]),
      );
      window.__JIEJING_FORCE_PUBLIC_MVP__ = true;
    },
    {
      base,
      accountKey,
      storeId: store.store_id,
      userId: user.user_id || "",
      email,
      companyId: company.company_id || user.default_company_id || "",
    },
  );

  const page = await context.newPage();
  const pageErrors = [];
  const badResponses = [];
  const statusRequests = [];
  page.on("pageerror", (error) => pageErrors.push(String(error)));
  page.on("response", (response) => {
    if (response.url().includes("/merchant-project-status")) statusRequests.push({ url: response.url(), status: response.status() });
    if (response.status() >= 500) badResponses.push({ url: response.url(), status: response.status() });
  });

  await page.goto(`${base}/app.html?start=app&view=product&project=${encodeURIComponent(projectId)}`, {
    waitUntil: "domcontentloaded",
    timeout: 60000,
  });
  await page.waitForFunction(
    () => {
      const shell = document.querySelector("#appShell");
      return Boolean(shell && !shell.classList.contains("is-hidden") && typeof setView === "function");
    },
    null,
    { timeout: 60000 },
  );
  await page.waitForFunction(
    () =>
      typeof state !== "undefined" &&
      Array.isArray(state.saasStores) &&
      state.saasStores.length > 0 &&
      state.saasLoading === false &&
      state.saasProtectedStateReady === true,
    null,
    { timeout: 60000 },
  );
  const initialDiagnostic = await page.evaluate(async () => {
    const snapshot = await refreshSaasMerchantProjectStatus();
    const markupBeforeSetView = renderSaasMerchantProjectStatusStrip();
    setView("product");
    const stripCountAfterSetView = document.querySelectorAll('[data-merchant-project-status="merchant_project_status_v1"]').length;
    return {
      snapshot_version: snapshot?.snapshot_version || "",
      snapshot_project: snapshot?.project?.project_id || "",
      state_snapshot_version: state.saasMerchantProjectStatus?.snapshot_version || "",
      current_view: state.view,
      active_store_id: activeSaasStore()?.store_id || "",
      public_mode: isSaasPublicMvpMode(),
      protected_ready: state.saasProtectedStateReady,
      loading: state.saasLoading,
      markup_length: markupBeforeSetView.length,
      strip_count_after_set_view: stripCountAfterSetView,
      route: window.location.href,
      strip_count: document.querySelectorAll('[data-merchant-project-status="merchant_project_status_v1"]').length,
    };
  });
  if (initialDiagnostic.snapshot_version !== "merchant_project_status_v1") {
    await browser.close();
    throw new Error(`merchant project snapshot did not load in browser: ${JSON.stringify(initialDiagnostic)}`);
  }
  if (initialDiagnostic.current_view !== "product" || initialDiagnostic.strip_count < 1) {
    await browser.close();
    throw new Error(`merchant project strip did not mount: ${JSON.stringify(initialDiagnostic)}`);
  }
  await page.waitForSelector('#view-product.is-active [data-merchant-project-status="merchant_project_status_v1"]', { timeout: 60000 });

  const viewResults = {};
  for (const view of ["product", "media", "confirm", "cockpit"]) {
    await page.evaluate((nextView) => setView(nextView), view);
    await page.waitForSelector(`#view-${view}.is-active [data-merchant-project-status="merchant_project_status_v1"]`, { timeout: 20000 });
    viewResults[view] = await page.evaluate(
      ({ view, projectId, expectedStage }) => {
        const strip = document.querySelector(`#view-${view}.is-active [data-merchant-project-status="merchant_project_status_v1"]`);
        const stages = Array.from(strip?.querySelectorAll(".saas-merchant-project-stages li") || []);
        const current = stages.filter((item) => item.classList.contains("is-current"));
        const url = new URL(window.location.href);
        return {
          strip_present: Boolean(strip),
          stage_count: stages.length,
          current_count: current.length,
          current_label: current[0]?.textContent?.trim() || "",
          route_project: url.searchParams.get("project") || "",
          route_view: url.searchParams.get("view") || "",
          expected_stage: expectedStage,
          project_match: (url.searchParams.get("project") || "") === projectId,
        };
      },
      { view, projectId, expectedStage: expectedSnapshot.current_stage },
    );
  }
  const legacyActivityRoute = await page.evaluate(() => {
    setView("activity");
    const url = new URL(window.location.href);
    return {
      current_view: state.view,
      route_view: url.searchParams.get("view") || "",
      activity_active: document.querySelector("#view-activity")?.classList.contains("is-active") === true,
      activity_nav_count: document.querySelectorAll('.nav-item[data-view="activity"]').length,
    };
  });
  await page.evaluate(() => setView("service"));
  await page.waitForSelector(
    '#view-service.is-active [data-service-trace-contract="customer_service_trace_v1"]',
    { timeout: 20000 },
  );
  await page.waitForFunction(
    () => {
      const root = document.querySelector('[data-service-trace-contract="customer_service_trace_v1"]');
      const labels = Array.from(root?.querySelectorAll(".saas-service-lane-grid article strong") || []).map((item) =>
        item.textContent.trim(),
      );
      return (
        labels.length === 0 &&
        root?.textContent?.includes("当前没有买家消息或回复记录") === true &&
        root?.textContent?.includes("订单数据不等于买家消息") === true
      );
    },
    null,
    { timeout: 20000 },
  );
  const serviceTraceUi = await page.evaluate(() => {
    const root = document.querySelector('[data-service-trace-contract="customer_service_trace_v1"]');
    return {
      present: Boolean(root),
      state_labels: Array.from(root?.querySelectorAll(".saas-service-lane-grid article strong") || []).map((item) => item.textContent.trim()),
      record_count: root?.querySelectorAll("[data-service-trace-id]").length || 0,
      empty_state: root?.textContent?.includes("当前没有买家消息或回复记录") === true,
      honest_order_boundary: root?.textContent?.includes("订单数据不等于买家消息") === true,
    };
  });

  await page.reload({ waitUntil: "domcontentloaded", timeout: 60000 });
  await page.waitForSelector('#view-service.is-active [data-service-trace-contract="customer_service_trace_v1"]', { timeout: 60000 });
  await page.waitForFunction(
    (expectedProjectId) =>
      typeof state !== "undefined" &&
      state.saasLoading === false &&
      state.saasProtectedStateReady === true &&
      (state.saasMerchantProjectStatus?.project?.project_id || "") === expectedProjectId,
    projectId,
    { timeout: 60000 },
  );
  const afterReload = await page.evaluate((expectedProjectId) => {
    const url = new URL(window.location.href);
    const serviceTrace = document.querySelector('#view-service.is-active [data-service-trace-contract="customer_service_trace_v1"]');
    return {
      service_trace_present: Boolean(serviceTrace),
      snapshot_project: state.saasMerchantProjectStatus?.project?.project_id || "",
      route_project: url.searchParams.get("project") || "",
      route_view: url.searchParams.get("view") || "",
      project_match: (url.searchParams.get("project") || "") === expectedProjectId,
      snapshot_match: (state.saasMerchantProjectStatus?.project?.project_id || "") === expectedProjectId,
      view_match: (url.searchParams.get("view") || "") === "service",
    };
  }, projectId);

  const responsiveResults = [];
  for (const viewport of [
    { name: "desktop", width: 1440, height: 1000 },
    { name: "tablet", width: 1024, height: 900 },
    { name: "mobile", width: 390, height: 844 },
  ]) {
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    for (const view of ["product", "confirm", "cockpit"]) {
      await page.evaluate((nextView) => setView(nextView), view);
      await page.waitForSelector(`#view-${view}.is-active [data-merchant-project-status="merchant_project_status_v1"]`, {
        timeout: 20000,
      });
      responsiveResults.push(
        await page.evaluate(
          ({ viewport, view }) => {
            const root = document.documentElement;
            const activeView = document.querySelector(`#view-${view}.is-active`);
            const strip = activeView?.querySelector('[data-merchant-project-status="merchant_project_status_v1"]');
            return {
              viewport: viewport.name,
              view,
              strip_present: Boolean(strip),
              horizontal_overflow: Math.max(0, root.scrollWidth - root.clientWidth),
              active_view_overflow: activeView ? Math.max(0, activeView.scrollWidth - activeView.clientWidth) : -1,
              fake_later_action_count: activeView
                ? Array.from(activeView.querySelectorAll("button")).filter((button) => button.textContent.trim() === "稍后处理").length
                : -1,
            };
          },
          { viewport, view },
        ),
      );
    }
  }

  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.evaluate(() => setView("product"));
  await page.waitForSelector('#view-product.is-active [data-merchant-project-status="merchant_project_status_v1"]', { timeout: 20000 });
  await page.screenshot({ path: path.join("output", "browser-smoke", "merchant-project-status-phase4.png"), fullPage: true });
  await browser.close();

  const viewChecksPass = Object.values(viewResults).every(
    (item) => item.strip_present && item.stage_count === 8 && item.current_count === 1 && item.project_match,
  );
  const responsiveChecksPass = responsiveResults.every(
    (item) =>
      item.strip_present &&
      item.horizontal_overflow === 0 &&
      item.active_view_overflow === 0 &&
      item.fake_later_action_count === 0,
  );
  const ok =
    viewChecksPass &&
    responsiveChecksPass &&
    afterReload.service_trace_present &&
    afterReload.project_match &&
    afterReload.snapshot_match &&
    afterReload.view_match &&
    statusRequests.some((item) => item.status === 200 && item.url.includes(encodeURIComponent(projectId))) &&
    legacyActivityRoute.current_view === "cockpit" &&
    legacyActivityRoute.route_view === "cockpit" &&
    legacyActivityRoute.activity_active === false &&
    legacyActivityRoute.activity_nav_count === 0 &&
    serviceTraceUi.present &&
    serviceTraceUi.record_count === 0 &&
    serviceTraceUi.empty_state &&
    serviceTraceUi.honest_order_boundary &&
    serviceTraceUi.state_labels.length === 0 &&
    pageErrors.length === 0 &&
    badResponses.length === 0;
  const failedChecks = Object.entries({
    view_checks: viewChecksPass,
    responsive_checks: responsiveChecksPass,
    reload_service_trace: afterReload.service_trace_present,
    reload_project_route: afterReload.project_match,
    reload_project_snapshot: afterReload.snapshot_match,
    reload_view_route: afterReload.view_match,
    project_status_200: statusRequests.some((item) => item.status === 200 && item.url.includes(encodeURIComponent(projectId))),
    legacy_activity_routes_to_cockpit:
      legacyActivityRoute.current_view === "cockpit" && legacyActivityRoute.route_view === "cockpit",
    legacy_activity_hidden:
      legacyActivityRoute.activity_active === false && legacyActivityRoute.activity_nav_count === 0,
    service_trace_root: serviceTraceUi.present,
    service_trace_empty: serviceTraceUi.record_count === 0 && serviceTraceUi.empty_state,
    service_trace_order_boundary: serviceTraceUi.honest_order_boundary,
    service_trace_empty_labels_suppressed: serviceTraceUi.state_labels.length === 0,
    page_errors: pageErrors.length === 0,
    bad_responses: badResponses.length === 0,
  })
    .filter(([, passed]) => !passed)
    .map(([key]) => key);
  const result = {
    ok,
    failed_checks: failedChecks,
    project_id: projectId,
    backend_current_stage: expectedSnapshot.current_stage,
    backend_blocker: expectedSnapshot.blocker?.key || "",
    initial_diagnostic: initialDiagnostic,
    view_results: viewResults,
    after_reload: afterReload,
    legacy_activity_route: legacyActivityRoute,
    service_trace_ui: serviceTraceUi,
    responsive_results: responsiveResults,
    status_requests: statusRequests,
    page_errors: pageErrors,
    bad_responses: badResponses,
    no_real_platform_writes_triggered: true,
    no_real_charge_triggered: true,
    no_ebay_oauth_triggered: true,
  };
  console.log(JSON.stringify(result, null, 2));
  if (!ok) process.exitCode = 1;
}

async function main() {
  let ownedBackend = null;
  try {
    if (!base) {
      ownedBackend = await startOwnedBackend();
      base = ownedBackend.backendBase;
    }
    await runSmoke();
  } finally {
    await stopOwnedBackend(ownedBackend);
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
