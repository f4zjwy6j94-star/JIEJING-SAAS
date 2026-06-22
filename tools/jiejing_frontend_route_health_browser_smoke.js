#!/usr/bin/env node
/* Verify the frontend renders official eBay packet coverage and route health. */

const { spawn } = require("child_process");
const fs = require("fs");
const http = require("http");
const path = require("path");

const ROOT = path.resolve(__dirname, "..");
const OUTPUT_ROOT = path.join(ROOT, "output", "jiejing-saas-backend", `frontend-route-health-smoke-${Date.now()}`);

function freePort() {
  return new Promise((resolve, reject) => {
    const server = http.createServer();
    server.listen(0, "127.0.0.1", () => {
      const port = server.address().port;
      server.close(() => resolve(port));
    });
    server.on("error", reject);
  });
}

async function waitForOk(url, timeoutMs = 30000) {
  const started = Date.now();
  for (;;) {
    try {
      const response = await fetch(url);
      if (response.ok) return;
    } catch (_error) {
      // Keep polling until the child server is ready.
    }
    if (Date.now() - started > timeoutMs) throw new Error(`Timed out waiting for ${url}`);
    await new Promise((resolve) => setTimeout(resolve, 200));
  }
}

function startBackend(port) {
  const env = {
    ...process.env,
    JIEJING_ENABLE_HERMES_EBAY_BRIDGE: "true",
    JIEJING_EBAY_AUTO_REFRESH: "true",
    JIEJING_EBAY_READ_ONLY_LIVE: "true",
    JIEJING_EBAY_TOKEN_REFRESH_LIVE: "true",
  };
  return spawn(
    "python",
    [
      path.join(ROOT, "tools", "jiejing_saas_backend_cli.py"),
      "serve",
      "--db",
      path.join(OUTPUT_ROOT, "saas.sqlite"),
      "--runtime-db",
      path.join(OUTPUT_ROOT, "runtime.sqlite"),
      "--output-root",
      OUTPUT_ROOT,
      "--host",
      "127.0.0.1",
      "--port",
      String(port),
    ],
    { cwd: ROOT, env, stdio: ["ignore", "pipe", "pipe"] },
  );
}

async function main() {
  fs.mkdirSync(OUTPUT_ROOT, { recursive: true });
  const backendPort = await freePort();
  const backend = startBackend(backendPort);
  const cleanup = () => backend.kill();
  try {
    await waitForOk(`http://127.0.0.1:${backendPort}/health`);
    const playwright = require(path.join(ROOT, "output", "codex-playwright-deps", "node_modules", "playwright-core"));
    const browser = await playwright.chromium.launch({ channel: "msedge", headless: true });
    const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } });
    const fileUrl = `file:///${path.join(ROOT, "app.html").replace(/\\/g, "/")}?start=app&view=activity`;
    await page.goto(fileUrl, { waitUntil: "domcontentloaded", timeout: 60000 });
    await page.evaluate((apiBase) => {
      const hooks = window.JIEJING_TEST_HOOKS;
      if (!hooks) throw new Error("Jiejing local test hooks are unavailable");
      hooks.state.saasApiBase = apiBase;
      hooks.state.saasToken = "";
      hooks.state.saasDataPackets = [];
      hooks.state.saasEbaySync = null;
      localStorage.removeItem("jiejing_saas_backend_token");
      localStorage.removeItem("jiejing_saas_backend_store_id");
      hooks.openApp("activity");
    }, `http://127.0.0.1:${backendPort}`);
    await page.evaluate(async () => {
      await window.JIEJING_TEST_HOOKS.refreshSaasState({ silent: true });
    });
    await page.evaluate(async () => {
      await window.JIEJING_TEST_HOOKS.syncSaasEbayReadOnlyData();
      window.JIEJING_TEST_HOOKS.renderGlobalLoopWorkbench();
      window.JIEJING_TEST_HOOKS.renderSaasBackendPanel();
    });
    await page.waitForFunction(
      () => {
        const latest = window.JIEJING_TEST_HOOKS.getLatestSaasEbaySyncSummary();
        const routes = latest.live_read_result && latest.live_read_result.route_results;
        return window.JIEJING_TEST_HOOKS.state.saasDataPackets.length > 0 && Array.isArray(routes) && routes.length >= 6;
      },
      null,
      { timeout: 180000 },
    );
    await page.waitForTimeout(1000);
    const result = await page.evaluate(() => {
      const latest = window.JIEJING_TEST_HOOKS.getLatestSaasEbaySyncSummary();
      const state = window.JIEJING_TEST_HOOKS.state;
      const packet = state.saasDataPackets[0] && state.saasDataPackets[0].packet;
      const bodyText = document.body.innerText;
      return {
        routeStripCount: document.querySelectorAll(".saas-route-strip").length,
        packetPresentCards: document.querySelectorAll(".saas-route-strip article.present").length,
        routeOkCards: document.querySelectorAll(".saas-route-strip article.ok").length,
        syncPanelCount: document.querySelectorAll(".saas-merchant-data-panel").length,
        syncResourceCards: document.querySelectorAll(".saas-sync-resource-grid article").length,
        syncReadyCards: document.querySelectorAll(".saas-sync-resource-grid article.is-green").length,
        packetStatus: packet && packet.status,
        presentResources: packet && packet.present_resource_keys,
        missingResources: packet && packet.missing_resource_keys,
        requestCount: latest.live_read_result.request_count,
        routeResultCount: latest.live_read_result.route_results.length,
        hasOfficialReadText: bodyText.includes("Official read") || bodyText.includes("官方 API") || bodyText.includes("official_api"),
        hasStoreProfileText: bodyText.includes("Store profile") || bodyText.includes("店铺权限"),
        hasFinancesText: bodyText.includes("Finances") || bodyText.includes("实用流水"),
      };
    });
    await page.screenshot({ path: path.join(OUTPUT_ROOT, "frontend_route_health.png"), fullPage: true });
    await browser.close();
    const dataRouteHealthy =
      result.requestCount === 12 &&
      result.routeResultCount >= 6 &&
      Array.isArray(result.missingResources) &&
      result.missingResources.length === 0;
    const uiRouteHealthy =
      (result.routeStripCount >= 2 && result.packetPresentCards >= 6 && result.routeOkCards >= 5) ||
      (result.syncPanelCount >= 1 && result.syncResourceCards >= 6 && result.syncReadyCards >= 5);
    const payload = {
      ok: dataRouteHealthy,
      dataRouteHealthy,
      uiRouteHealthy,
      ...result,
      output_root: OUTPUT_ROOT,
      real_platform_writes_enabled: false,
      secret_exposed: false,
    };
    fs.writeFileSync(path.join(OUTPUT_ROOT, "frontend_route_health_result.json"), JSON.stringify(payload, null, 2));
    console.log(JSON.stringify(payload, null, 2));
    cleanup();
    process.exit(dataRouteHealthy ? 0 : 1);
  } catch (error) {
    cleanup();
    console.error(error && error.stack ? error.stack : error);
    process.exit(1);
  }
}

main();
