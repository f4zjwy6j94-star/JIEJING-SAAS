#!/usr/bin/env node
/* Browser contract for cross-tab session refresh coordination.
   The fixture is strictly 127.0.0.1 and never calls OAuth, payment, or platform APIs. */

const fs = require("fs");
const http = require("http");
const path = require("path");
const { chromium } = require("../output/codex-playwright-deps/node_modules/playwright-core");

const root = path.resolve(__dirname, "..");
const browserChannel = process.env.JIEJING_PLAYWRIGHT_CHANNEL || "chrome";
const initialAccess = "SENTINEL-INITIAL-ACCESS";
const initialRefresh = "SENTINEL-INITIAL-REFRESH";
const nextAccess = "SENTINEL-NEXT-ACCESS";
const nextRefresh = "SENTINEL-NEXT-REFRESH";
const counters = { me: 0, refresh: 0 };

function json(res, status, body, headers = {}) {
  res.writeHead(status, {
    "content-type": "application/json; charset=utf-8",
    "cache-control": "no-store",
    ...headers,
  });
  res.end(JSON.stringify(body));
}

function testableAppSource() {
  const source = fs.readFileSync(path.join(root, "app.js"), "utf8");
  const boot = /exposeLocalJiejingTestHooks\(\);\r?\ninit\(\);\r?\nrunLocalJiejingQaScenarioFromUrl\(\);\s*$/;
  if (!boot.test(source)) throw new Error("app boot marker changed");
  return source.replace(boot, "exposeLocalJiejingTestHooks();\n");
}

async function main() {
  const appSource = testableAppSource();
  const server = http.createServer((req, res) => {
    const url = new URL(req.url || "/", "http://127.0.0.1");
    const cookie = String(req.headers.cookie || "");
    if (url.pathname === "/harness.html") {
      res.writeHead(200, {
        "content-type": "text/html; charset=utf-8",
        "cache-control": "no-store",
      });
      res.end('<!doctype html><html><head><meta charset="utf-8"></head><body><main id="app"></main><script src="/app-test.js"></script></body></html>');
      return;
    }
    if (url.pathname === "/app-test.js") {
      res.writeHead(200, {
        "content-type": "text/javascript; charset=utf-8",
        "cache-control": "no-store",
      });
      res.end(appSource);
      return;
    }
    if (url.pathname === "/me" && req.method === "GET") {
      counters.me += 1;
      if (cookie.includes(`jiejing_saas_session=${nextAccess}`)) {
        json(res, 200, { user: { user_id: "browser-session-smoke" }, secret_exposed: false });
      } else {
        json(res, 401, { error: "session expired", secret_exposed: false });
      }
      return;
    }
    if (url.pathname === "/auth/refresh" && req.method === "POST") {
      counters.refresh += 1;
      if (!cookie.includes(`jiejing_saas_refresh=${initialRefresh}`)) {
        json(res, 401, { error: "session_refresh_invalid", secret_exposed: false });
        return;
      }
      setTimeout(
        () =>
          json(
            res,
            200,
            { ok: true, session_refreshed: true, secret_exposed: false },
            {
              "set-cookie": [
                `jiejing_saas_session=${nextAccess}; Path=/; HttpOnly; SameSite=Lax`,
                `jiejing_saas_refresh=${nextRefresh}; Path=/; HttpOnly; SameSite=Strict`,
              ],
            },
          ),
        150,
      );
      return;
    }
    json(res, 404, { error: "fixture_not_found", secret_exposed: false });
  });

  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });
  const address = server.address();
  const base = `http://127.0.0.1:${address.port}`;
  let browser;
  try {
    browser = await chromium.launch({ headless: true, channel: browserChannel });
    const context = await browser.newContext();
    await context.addCookies([
      { name: "jiejing_saas_session", value: initialAccess, url: base, httpOnly: true, sameSite: "Lax" },
      { name: "jiejing_saas_refresh", value: initialRefresh, url: base, httpOnly: true, sameSite: "Strict" },
    ]);
    const consoleValues = [];
    const pageA = await context.newPage();
    const pageB = await context.newPage();
    for (const page of [pageA, pageB]) {
      page.on("console", (message) => consoleValues.push(message.text()));
      await page.goto(`${base}/harness.html?saasApiBase=${encodeURIComponent(base)}`, { waitUntil: "load" });
    }
    const lockReady = await pageA.evaluate(() => Boolean(globalThis.navigator?.locks?.request));
    if (!lockReady) throw new Error("browser Web Locks API is required for the cross-tab session contract");
    const [resultA, resultB] = await Promise.all([
      pageA.evaluate(() => refreshSaasBrowserSession()),
      pageB.evaluate(() => refreshSaasBrowserSession()),
    ]);
    if (resultA !== true || resultB !== true) {
      throw new Error(`both tabs must recover through one rotation; results=${resultA},${resultB}`);
    }
    if (counters.refresh !== 1 || counters.me !== 2) {
      throw new Error(`cross-tab refresh must rotate once after two locked probes; counters=${JSON.stringify(counters)}`);
    }
    const visibleLeak = await pageA.evaluate((sentinels) => {
      const storage = `${JSON.stringify(localStorage)} ${JSON.stringify(sessionStorage)}`;
      const dom = document.documentElement.outerHTML;
      return sentinels.some((value) => storage.includes(value) || dom.includes(value));
    }, [initialAccess, initialRefresh, nextAccess, nextRefresh]);
    if (visibleLeak || consoleValues.some((value) => [initialAccess, initialRefresh, nextAccess, nextRefresh].some((secret) => value.includes(secret)))) {
      throw new Error("browser session tokens must not enter DOM, storage, or console output");
    }
    await context.close();
    console.log("PASS jiejing_rotating_browser_session_smoke");
  } finally {
    if (browser) await browser.close();
    await new Promise((resolve) => server.close(resolve));
  }
}

main().catch((error) => {
  console.error(`FAIL ${error.message}`);
  process.exitCode = 1;
});
