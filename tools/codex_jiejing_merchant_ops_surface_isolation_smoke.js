#!/usr/bin/env node
/*
 * Merchant/ops isolation smoke.
 *
 * Default mode is an offline, fail-closed source fixture. Browser mode is only
 * enabled when both explicit fixture origins are supplied. Production Jiejing
 * hosts are always rejected.
 */

const fs = require("fs");
const path = require("path");

const root = path.resolve(__dirname, "..");
const merchantFixtureBase = String(process.env.JIEJING_MERCHANT_FIXTURE_BASE || "").trim();
const opsFixtureBase = String(process.env.JIEJING_OPS_FIXTURE_BASE || "").trim();

const roleMatrix = Object.freeze([
  { surface: "app", role: "merchant", internalUi: false, internalRequests: false },
  { surface: "app", role: "internal_admin", internalUi: false, internalRequests: false },
  { surface: "ops", role: "internal_admin", internalUi: true, internalRequests: true },
  { surface: "ops", role: "merchant", internalUi: false, internalRequests: false },
]);

const internalRequestPrefixes = Object.freeze([
  "/owner/",
  "/vault/",
  "/database/",
  "/backup/",
  "/queue/",
  "/billing/payment-options",
  "/billing/wechat-pay/zero-charge-rehearsal",
]);

const internalUiMarkers = Object.freeze([
  "主理人高级",
  "固定正式上线准备度",
  "上线与发布",
  "支付验收",
  "备份与恢复",
  "运行与安全",
]);

function read(relativePath, { optional = false } = {}) {
  const absolute = path.join(root, relativePath);
  if (optional && !fs.existsSync(absolute)) return "";
  return fs.readFileSync(absolute, "utf8");
}

function sourceWindow(source, startMarker, endMarker) {
  const start = source.indexOf(startMarker);
  const end = source.indexOf(endMarker, start + startMarker.length);
  if (start < 0 || end < 0) return "";
  return source.slice(start, end);
}

function braceBlockAt(source, markerStart) {
  const open = source.indexOf("{", markerStart);
  if (open < 0) return null;
  let depth = 0;
  for (let index = open; index < source.length; index += 1) {
    if (source[index] === "{") depth += 1;
    if (source[index] === "}") depth -= 1;
    if (depth === 0) {
      return {
        header: source.slice(markerStart, open).trim(),
        body: source.slice(open + 1, index),
        full: source.slice(markerStart, index + 1),
      };
    }
  }
  return null;
}

function braceBlocks(source, expression) {
  const blocks = [];
  expression.lastIndex = 0;
  for (let match = expression.exec(source); match; match = expression.exec(source)) {
    const block = braceBlockAt(source, match.index);
    if (block) blocks.push(block);
  }
  return blocks;
}

function caddySiteBlocks(source, expression) {
  const blocks = [];
  expression.lastIndex = 0;
  for (let match = expression.exec(source); match; match = expression.exec(source)) {
    // A placeholder host such as {$JIEJING_PRODUCTION_HOST} contains braces of
    // its own. The actual site block is always the final "{" in the matched
    // host declaration, not the placeholder's opening brace.
    const declaration = match[0];
    const open = match.index + declaration.lastIndexOf("{");
    let depth = 0;
    for (let index = open; index < source.length; index += 1) {
      if (source[index] === "{") depth += 1;
      if (source[index] === "}") depth -= 1;
      if (depth === 0) {
        blocks.push({
          header: source.slice(match.index, open).trim(),
          body: source.slice(open + 1, index),
          full: source.slice(match.index, index + 1),
        });
        break;
      }
    }
  }
  return blocks;
}

function nginxLocationBlocks(serverBlock) {
  return braceBlocks(serverBlock, /^\s*location\s+[^\n{]+\{/gm);
}

function nginxRejectCoversRoute(header, route) {
  const normalized = header.replace(/\s+/g, " ").trim();
  const direct = new RegExp(`^location (?:\\^~ )?/${route}/$`);
  const regexPrefix =
    normalized.startsWith("location ~") &&
    normalized.includes("^/") &&
    new RegExp(`\\b${route}\\b`).test(normalized) &&
    (normalized.includes("(/|$)") || normalized.includes("(?:/|$)"));
  return direct.test(normalized) || regexPrefix;
}

function nginxProxyMentionsRoute(header, route) {
  return new RegExp(`/${route}(?:/|\\b)`).test(header) ||
    (header.includes("^/") && new RegExp(`\\b${route}\\b`).test(header));
}

function nginxProxyCouldMatchOwnerPrefix(header) {
  const normalized = header.replace(/\s+/g, " ").trim();
  if (normalized === "location /" || normalized === "location ^~ /") return true;
  if (/\/owner(?:\/|\b)/.test(normalized) || /\bowner\b/.test(normalized)) return true;
  return normalized.startsWith("location ~") && normalized.includes("^/") && /(?:\.\*|\[\^|\(.+\))/.test(normalized);
}

function caddyMatcherScopes(siteBlock) {
  const scopes = new Map();
  for (const match of siteBlock.matchAll(/^\s*@([\w-]+)\s+([^\n{][^\n]*)$/gm)) {
    scopes.set(match[1], match[2].trim());
  }
  for (const match of siteBlock.matchAll(/^\s*@([\w-]+)\s*\{/gm)) {
    const block = braceBlockAt(siteBlock, match.index);
    if (block) scopes.set(match[1], block.full);
  }
  return scopes;
}

function caddyScopeCoversRoute(scope, route) {
  return new RegExp(`/${route}/\\*`).test(scope);
}

function caddyMatcherRejects(siteBlock, matcherName) {
  if (new RegExp(`^\\s*respond\\s+@${matcherName}\\s+(?:"[^"]*"\\s+)?404\\b`, "m").test(siteBlock)) {
    return true;
  }
  const handleBlocks = braceBlocks(
    siteBlock,
    new RegExp(`^\\s*handle\\s+@${matcherName}\\s*\\{`, "gm"),
  );
  return handleBlocks.length === 1 && /\brespond\b[^\n]*\b404\b/.test(handleBlocks[0].body) && !handleBlocks[0].body.includes("reverse_proxy");
}

function safePathname(rawUrl) {
  try {
    return new URL(rawUrl).pathname;
  } catch (_error) {
    return "invalid-url";
  }
}

function isInternalPath(pathname) {
  return internalRequestPrefixes.some((prefix) => pathname.startsWith(prefix));
}

function staticFixtureContract() {
  const failures = [];
  const appJs = read("app.js");
  const appHtml = read("app.html");
  const merchantPanels = read("assets/jiejing-settings-panels.js");
  const opsHtml = read("ops.html");
  const opsJs = read("ops.js");
  const opsPanels = read("assets/jiejing-ops-panels.js", { optional: true });
  const nginx = read("deploy/nginx.public-staging.conf");
  const productionCaddy = read("deploy/Caddyfile.production");

  if (roleMatrix.length !== 4) failures.push("fixture matrix must cover exactly four surface/role combinations");
  for (const expected of ["app:merchant", "app:internal_admin", "ops:internal_admin", "ops:merchant"]) {
    if (!roleMatrix.some((item) => `${item.surface}:${item.role}` === expected)) {
      failures.push(`fixture matrix is missing ${expected}`);
    }
  }

  const settingsScope = sourceWindow(
    appJs,
    "function saasSettingsTabDefinitions",
    "function renderSaasSettingsCleanLayout",
  );
  const labels = [...settingsScope.matchAll(/\n\s*label:\s*"([^"]+)"/g)].map((match) => match[1]);
  const expectedLabels = ["账号与店铺", "AI 与素材", "店铺数据", "团队权限", "套餐与付款"];
  if (JSON.stringify(labels) !== JSON.stringify(expectedLabels)) {
    failures.push(`app Settings is not the same five-tab merchant surface for both roles: ${JSON.stringify(labels)}`);
  }

  const merchantBundle = [appHtml, appJs, merchantPanels].join("\n");
  for (const marker of [
    ...internalRequestPrefixes,
    "renderSaasOwnerLaunchControlPanel",
    "renderCommercialLaunchActionPlanPanel",
    "renderQueueHealthPanel",
    "renderPublicSecurityStatusPanel",
    "owner_testing_points",
    "隔离假支付方",
  ]) {
    if (merchantBundle.includes(marker)) failures.push(`merchant bundle contains internal marker: ${marker}`);
  }

  const opsBundle = [opsHtml, opsJs, opsPanels].join("\n");
  if (!opsPanels) failures.push("offline fixture is missing assets/jiejing-ops-panels.js");
  if (!opsHtml.includes("jiejing-ops-panels.js")) failures.push("ops.html does not load the isolated ops bundle");
  for (const marker of internalUiMarkers.slice(2)) {
    if (!opsBundle.includes(marker)) failures.push(`ops bundle is missing internal view: ${marker}`);
  }
  if (!opsBundle.includes("/owner/launch-control")) failures.push("ops bundle is missing launch-control request");

  const nginxServers = braceBlocks(nginx, /^\s*server\s*\{/gm);
  const appServer = nginxServers.find((block) => block.body.includes("listen 80 default_server;"));
  const opsServer = nginxServers.find((block) => block.body.includes("server_name ops.jiejing.shop"));
  if (!appServer) failures.push("nginx fixture cannot identify the merchant server block");
  if (!opsServer) failures.push("nginx fixture cannot identify the ops server block");
  const appLocations = appServer ? nginxLocationBlocks(appServer.full) : [];
  for (const route of ["owner", "vault", "database", "backup", "queue"]) {
    const rejectBlocks = appLocations.filter(
      (block) =>
        nginxRejectCoversRoute(block.header, route) &&
        /\breturn\s+404\b/.test(block.body) &&
        !block.body.includes("proxy_pass"),
    );
    if (rejectBlocks.length !== 1) {
      failures.push(`merchant nginx host needs one explicit non-proxy 404 route for /${route}/`);
    }
    const proxyBlocks = appLocations.filter(
      (block) => block.body.includes("proxy_pass") && nginxProxyMentionsRoute(block.header, route),
    );
    if (proxyBlocks.length) failures.push(`merchant nginx host still proxies /${route}/ in a route matcher`);
  }
  const opsLocations = opsServer ? nginxLocationBlocks(opsServer.full) : [];
  const launchAllowlist = opsLocations.filter(
    (block) => block.header.replace(/\s+/g, " ").trim() === "location = /owner/launch-control" && block.body.includes("proxy_pass"),
  );
  if (launchAllowlist.length !== 1) failures.push("ops nginx host needs one exact launch-control proxy route");
  const ownerPrefixRejects = opsLocations.filter(
    (block) =>
      nginxRejectCoversRoute(block.header, "owner") &&
      /\breturn\s+404\b/.test(block.body) &&
      !block.body.includes("proxy_pass"),
  );
  if (ownerPrefixRejects.length !== 1) {
    failures.push("ops nginx host needs one explicit /owner/ prefix 404 for every non-allowlisted owner path");
  }
  const unsafeOpsOwnerProxies = opsLocations.filter((block) => {
    if (!block.body.includes("proxy_pass")) return false;
    const normalized = block.header.replace(/\s+/g, " ").trim();
    if (normalized.startsWith("location = /owner/")) return false;
    return nginxProxyCouldMatchOwnerPrefix(normalized);
  });
  if (unsafeOpsOwnerProxies.length) {
    failures.push("ops nginx host has a prefix/generic proxy that can bypass the exact owner allowlist")
  }

  const caddySites = caddySiteBlocks(
    productionCaddy,
    /^\s*(?:\{\$JIEJING_PRODUCTION_HOST\}|(?:https?:\/\/)?[\w.,*\s-]*app\.jiejing\.shop[^\n{]*)\s*\{/gm,
  );
  const merchantCaddy = caddySites[0] || null;
  if (!merchantCaddy) failures.push("production Caddy fixture cannot identify the app.jiejing.shop site block");
  const matcherScopes = merchantCaddy ? caddyMatcherScopes(merchantCaddy.full) : new Map();
  const reverseProxyMatchers = merchantCaddy
    ? [...merchantCaddy.full.matchAll(/^\s*reverse_proxy\s+@([\w-]+)\b/gm)].map((match) => match[1])
    : [];
  for (const route of ["owner", "vault", "database", "backup", "queue"]) {
    const rejectingMatchers = [...matcherScopes.entries()].filter(
      ([name, scope]) =>
        caddyScopeCoversRoute(scope, route) &&
        caddyMatcherRejects(merchantCaddy ? merchantCaddy.full : "", name),
    );
    if (rejectingMatchers.length !== 1) {
      failures.push(`production app Caddy needs one explicit 404 matcher for /${route}/*`);
    }
    for (const matcherName of reverseProxyMatchers) {
      if (caddyScopeCoversRoute(matcherScopes.get(matcherName) || "", route)) {
        failures.push(`production app Caddy reverse-proxy matcher ${matcherName} still includes /${route}/*`);
      }
    }
  }

  return {
    ok: failures.length === 0,
    mode: "offline_static_fixture",
    matrix: roleMatrix,
    failures,
    browser_runtime_executed: false,
    external_network_used: false,
    secret_exposed: false,
  };
}

function validatedFixtureOrigin(raw, label) {
  const parsed = new URL(raw);
  const hostname = parsed.hostname.toLowerCase();
  if (hostname === "app.jiejing.shop" || hostname === "ops.jiejing.shop" || hostname.endsWith(".jiejing.shop")) {
    throw new Error(`${label} must never target a production Jiejing host`);
  }
  const localHosts = new Set(["127.0.0.1", "localhost", "::1"]);
  if (!localHosts.has(hostname) && process.env.JIEJING_ALLOW_EXPLICIT_REMOTE_FIXTURE !== "true") {
    throw new Error(`${label} must be loopback unless JIEJING_ALLOW_EXPLICIT_REMOTE_FIXTURE=true`);
  }
  return parsed.origin;
}

async function browserFixtureContract() {
  const merchantBase = validatedFixtureOrigin(merchantFixtureBase, "merchant fixture");
  const opsBase = validatedFixtureOrigin(opsFixtureBase, "ops fixture");
  const playwrightPath = path.join(root, "output", "codex-playwright-deps", "node_modules", "playwright-core");
  if (!fs.existsSync(playwrightPath)) throw new Error("explicit browser fixture requested but playwright-core is unavailable");
  const { chromium } = require(playwrightPath);
  const launchOptions = { headless: true };
  if (process.env.JIEJING_PLAYWRIGHT_EXECUTABLE) launchOptions.executablePath = process.env.JIEJING_PLAYWRIGHT_EXECUTABLE;
  if (process.env.JIEJING_PLAYWRIGHT_CHANNEL) launchOptions.channel = process.env.JIEJING_PLAYWRIGHT_CHANNEL;
  const browser = await chromium.launch(launchOptions);
  const results = [];

  try {
    for (const matrixItem of roleMatrix) {
      const base = matrixItem.surface === "app" ? merchantBase : opsBase;
      const context = await browser.newContext({
        viewport: { width: 1366, height: 900 },
        extraHTTPHeaders: { "x-jiejing-fixture-role": matrixItem.role },
      });
      const page = await context.newPage();
      const requestedPaths = [];
      page.on("request", (request) => requestedPaths.push(safePathname(request.url())));
      const response = await page.goto(
        matrixItem.surface === "app" ? `${base}/app.html?start=app&view=connect` : `${base}/`,
        { waitUntil: "networkidle", timeout: 45000 },
      );
      const bodyText = await page.locator("body").innerText();
      const internalRequests = requestedPaths.filter(isInternalPath);
      const directInternalStatus = await page.evaluate(async () => {
        const result = await fetch("/owner/launch-control", { cache: "no-store" });
        return result.status;
      });
      let ok = Boolean(response);
      if (matrixItem.surface === "app") {
        const labels = await page.locator("[data-saas-settings-tab]").allTextContents();
        const normalized = labels.map((item) => item.trim()).filter(Boolean);
        ok =
          ok &&
          normalized.length === 5 &&
          !internalUiMarkers.some((marker) => bodyText.includes(marker)) &&
          internalRequests.length === 0 &&
          directInternalStatus === 404;
      } else if (matrixItem.role === "internal_admin") {
        ok =
          ok &&
          internalUiMarkers.slice(2).every((marker) => bodyText.includes(marker)) &&
          directInternalStatus === 200;
      } else {
        ok =
          ok &&
          !internalUiMarkers.slice(2).some((marker) => bodyText.includes(marker)) &&
          [401, 403].includes(directInternalStatus);
      }
      results.push({
        surface: matrixItem.surface,
        role: matrixItem.role,
        ok,
        internal_request_count: internalRequests.length,
        direct_internal_status: directInternalStatus,
      });
      await context.close();
    }
  } finally {
    await browser.close();
  }

  return {
    ok: results.every((item) => item.ok),
    mode: "explicit_browser_fixture",
    matrix: results,
    browser_runtime_executed: true,
    external_network_used: false,
    secret_exposed: false,
  };
}

async function main() {
  if (Boolean(merchantFixtureBase) !== Boolean(opsFixtureBase)) {
    throw new Error("set both JIEJING_MERCHANT_FIXTURE_BASE and JIEJING_OPS_FIXTURE_BASE, or neither");
  }
  const result = merchantFixtureBase ? await browserFixtureContract() : staticFixtureContract();
  console.log(JSON.stringify(result, null, 2));
  if (!result.ok) process.exitCode = 1;
}

main().catch((error) => {
  console.error(
    JSON.stringify(
      {
        ok: false,
        mode: merchantFixtureBase ? "explicit_browser_fixture" : "offline_static_fixture",
        error: String(error && error.message ? error.message : error).slice(0, 1000),
        external_network_used: false,
        secret_exposed: false,
      },
      null,
      2,
    ),
  );
  process.exitCode = 1;
});
