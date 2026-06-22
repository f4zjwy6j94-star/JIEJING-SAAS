#!/usr/bin/env node
/* Smoke-test the current deployed Jiejing SaaS flow with a pre-minted session. */

const fs = require("fs");
const path = require("path");
const { chromium } = require("../output/codex-playwright-deps/node_modules/playwright-core");

const token = process.env.JIEJING_TEST_TOKEN;
const userId = process.env.JIEJING_TEST_USER_ID;
const companyId = process.env.JIEJING_TEST_COMPANY_ID;
const storeId = process.env.JIEJING_TEST_STORE_ID;
const email = process.env.JIEJING_TEST_EMAIL;
const storeName = process.env.JIEJING_TEST_STORE_NAME;
const marketplace = process.env.JIEJING_TEST_MARKETPLACE;
const base = process.env.JIEJING_TEST_BASE || "https://individually-buffalo-prescribed-blocking.trycloudflare.com";
const headless = process.env.JIEJING_TEST_HEADLESS !== "0";
const skipLive = process.env.JIEJING_SKIP_LIVE_MODEL === "1";

if (!token || !storeId || !base) {
  throw new Error("missing JIEJING_TEST_TOKEN/JIEJING_TEST_STORE_ID/JIEJING_TEST_BASE");
}

const stamp = new Date().toISOString().replace(/[:.]/g, "-");
const outDir = path.join("output", "browser-smoke", `${stamp}-real-jiejing-flow`);
fs.mkdirSync(outDir, { recursive: true });

const zh = {
  login: "\u767b\u5f55",
  loginFirst: "\u8bf7\u5148\u767b\u5f55",
  today: "\u4eca\u65e5\u7ecf\u8425",
  factory: "Listing \u5de5\u5382",
  material: "\u7d20\u6750\u5de5\u574a",
  quality: "\u94fa\u8d27\u8d28\u68c0",
  report: "\u6c47\u62a5",
  queue: "\u51b3\u7b56\u961f\u5217",
  service: "\u5ba2\u670d\u7269\u6d41",
  settings: "\u8bbe\u7f6e",
  logout: "\u9000\u51fa\u767b\u5f55",
  switchAccount: "\u5207\u6362\u8d26\u53f7",
  official: "\u5b98\u65b9",
};

function maskEmail(value) {
  if (!value) return "";
  const [name, domain] = String(value).split("@");
  return `${name.slice(0, 2)}***@${domain || ""}`;
}

async function api(pathname, options = {}) {
  const res = await fetch(`${base}${pathname}`, {
    ...options,
    headers: {
      authorization: `Bearer ${token}`,
      "content-type": "application/json",
      ...(options.headers || {}),
    },
  });
  const text = await res.text();
  let json = null;
  try {
    json = text ? JSON.parse(text) : null;
  } catch (_error) {
    json = { raw: text.slice(0, 1000) };
  }
  return { ok: res.ok, status: res.status, json };
}

function listFrom(payload, key) {
  return Array.isArray(payload?.[key]?.json?.[key]) ? payload[key].json[key] : [];
}

function summarizeApi(payload) {
  const reports = listFrom(payload, "reports");
  const confirmations = listFrom(payload, "confirmations");
  const packets = Array.isArray(payload?.packets?.json?.data_packets) ? payload.packets.json.data_packets : [];
  const stores = listFrom(payload, "stores");
  const gate = payload?.modelGate?.json?.model_value_gate || {};
  const readiness = payload?.readiness?.json?.readiness || {};
  const byok = gate.merchant_byok_model || {};
  return {
    reports: reports.length,
    latest_report_types: reports.slice(0, 8).map((item) => item.report_type || item.type || item.title),
    confirmations: confirmations.length,
    pending_confirmations: confirmations.filter((item) => item.status === "pending").length,
    packets: packets.length,
    latest_packet_id: packets[0]?.packet_id || packets[0]?.id || "",
    stores: stores.length,
    store_names: stores.map((item) => item.store_name || item.name || "").filter(Boolean).slice(0, 5),
    model_value_ready: Boolean(gate.ready_for_paid_value_claim),
    byok_configured: Boolean(byok.configured),
    byok_ready_secret_refs: Number(byok.ready_secret_ref_count || 0),
    readiness: {
      beta_ready: Boolean(readiness.beta_ready),
      production_ready: Boolean(readiness.production_ready),
      can_accept_real_customers: Boolean(readiness.can_accept_real_customers),
      real_platform_writes_enabled: Boolean(readiness.real_platform_writes_enabled),
      blocker_count: Number(readiness.blocker_count || 0),
      warning_count: Number(readiness.warning_count || 0),
      secret_exposed: Boolean(readiness.secret_exposed),
    },
  };
}

async function collectApis() {
  const [stores, packets, reports, confirmations, modelGate, readiness] = await Promise.all([
    api("/stores"),
    api("/data-packets"),
    api("/reports?limit=40"),
    api("/confirmations?limit=40"),
    api("/model/value-gate"),
    fetch(`${base}/readiness`).then(async (res) => ({
      ok: res.ok,
      status: res.status,
      json: await res.json().catch(() => null),
    })),
  ]);
  return { stores, packets, reports, confirmations, modelGate, readiness };
}

async function main() {
  const before = await collectApis();
  const browser = await chromium.launch({ channel: "msedge", headless, timeout: 60000 });
  const context = await browser.newContext({ viewport: { width: 1512, height: 900 }, deviceScaleFactor: 1 });
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
  await context.addInitScript(
    ({ token, storeId, userId, email, companyId, storeName, base }) => {
      localStorage.setItem("jiejing_saas_backend_store_id", storeId);
      localStorage.setItem("jiejing_saas_api_base", base);
      localStorage.setItem("jiejing_saas_backend_session_hint", "1");
      window.__JIEJING_FORCE_PUBLIC_MVP__ = true;
      localStorage.setItem("jiejing_saas_last_account", String(userId || email || "browser").toLowerCase());
      localStorage.setItem(`jiejing_saas_onboarding_done:${String(userId || email || "browser").toLowerCase()}`, "1");
      localStorage.setItem(
        "jiejing_saas_known_accounts",
        JSON.stringify([
          {
            account_key: String(userId || email || "").toLowerCase(),
            user_id: userId,
            email,
            company_name: storeName || "Jiejing merchant",
            display_name: storeName || email,
            last_seen: new Date().toISOString(),
          },
        ]),
      );
      window.__CODEX_REAL_FLOW_SESSION__ = { companyId, storeId, storeName };
    },
    { token, storeId, userId, email, companyId, storeName, base },
  );

  const page = await context.newPage();
  page.setDefaultTimeout(45000);
  const consoleErrors = [];
  page.on("console", (msg) => {
    if (["error", "warning"].includes(msg.type())) {
      consoleErrors.push({ type: msg.type(), text: msg.text().slice(0, 500) });
    }
  });
  page.on("pageerror", (error) => {
    consoleErrors.push({ type: "pageerror", text: String(error.message || error).slice(0, 500) });
  });

  const url = `${base}/app.html?start=app&view=workflow&stage=store_opened&v=${Date.now()}`;
  await page.goto(url, { waitUntil: "domcontentloaded", timeout: 90000 });
  await page.waitForLoadState("networkidle", { timeout: 45000 }).catch(() => {});
  await page.waitForTimeout(5000);
  await page.screenshot({ path: path.join(outDir, "01-workflow-initial.png"), fullPage: true });

  let text = await page.locator("body").innerText({ timeout: 20000 }).catch(() => "");
  const demoRe = /\u5012\u6d41\u9999\u7089|\u65c5\u884c\u538b\u7f29\u6536\u7eb3\u888b|\u4fbf\u643a\u9996\u9970\u76d2|\u9999\u85b0\u8721\u70db\u5957\u88c5|\u684c\u9762\u7406\u7ebf\u5939/;
  const simRe = /\u6a21\u62df|\u6837\u4f8b|\u6d4b\u8bd5\u8349\u7a3f|demo/i;
  const initialChecks = {
    url: page.url(),
    title: await page.title().catch(() => ""),
    hasEnterSplash: text.includes("\u6b63\u5728\u8fdb\u5165\u6377\u5883\u5de5\u4f5c\u8231"),
    hasLoginRequired: text.includes(zh.loginFirst) || text.includes(zh.login),
    hasToday: text.includes(zh.today),
    hasListingFactory: text.includes(zh.factory),
    hasMaterialStudio: text.includes(zh.material),
    hasQuality: text.includes(zh.quality),
    hasAiCeoReport: text.includes("AI CEO") && text.includes(zh.report),
    hasDecisionQueue: text.includes(zh.queue),
    hasCustomerLogistics: text.includes(zh.service),
    hasSettings: text.includes(zh.settings),
    hasLogout: text.includes(zh.logout),
    hasSwitchAccount: text.includes(zh.switchAccount),
    hasStoreName: text.includes(storeName),
    hasOfficialPacket: text.includes("official") || text.includes(zh.official) || text.includes("packet_0b5dd20476f71eab"),
    hasDemoProducts: demoRe.test(text),
    hasSimulationCopy: simRe.test(text),
    textPreview: text.slice(0, 1800),
  };

  const accountTrigger = page.locator("#accountMenuTrigger");
  let accountMenuChecks = { opened: false };
  if ((await accountTrigger.count()) > 0) {
    await accountTrigger.first().click().catch(() => {});
    await page.waitForTimeout(500);
    const accountText = await page.locator("#accountMenuPopover").innerText({ timeout: 5000 }).catch(() => "");
    accountMenuChecks = {
      opened: Boolean(accountText),
      hasLogout: accountText.includes(zh.logout),
      hasSwitchAccount: accountText.includes(zh.switchAccount),
      hasStoreName: accountText.includes(storeName),
      textPreview: accountText.slice(0, 800),
    };
    await page.keyboard.press("Escape").catch(() => {});
  }

  const candidates = await page.locator("button").evaluateAll((buttons) =>
    buttons.map((button, index) => ({
      index,
      text: (button.innerText || button.textContent || "").trim(),
      action: button.getAttribute("data-saas-action") || "",
      disabled: button.disabled,
      visible: Boolean(button.offsetWidth || button.offsetHeight || button.getClientRects().length),
    })),
  );
  const liveButtons = page.locator('[data-saas-action="run-model-value-rehearsal"]');
  let target = null;
  for (let index = 0; index < (await liveButtons.count()); index += 1) {
    const candidate = liveButtons.nth(index);
    if ((await candidate.isVisible().catch(() => false)) && !(await candidate.isDisabled().catch(() => true))) {
      target = { index, locator: candidate, text: (await candidate.innerText().catch(() => "")).trim() };
      break;
    }
  }
  let clickResult = {
    clicked: false,
    reason: "no_enabled_button",
    target: null,
    visibleButtons: candidates.filter((button) => button.visible).slice(0, 30),
  };
  if (skipLive) {
    clickResult = { clicked: false, reason: "skipped_by_env", target: target ? { index: target.index, text: target.text, action: "run-model-value-rehearsal" } : null };
    await page.screenshot({ path: path.join(outDir, "02-live-model-skipped.png"), fullPage: true });
  } else if (target) {
    clickResult = { clicked: true, target: { index: target.index, text: target.text, action: "run-model-value-rehearsal" } };
    await target.locator.click();
    await page.waitForLoadState("networkidle", { timeout: 120000 }).catch(() => {});
    await page.waitForTimeout(25000);
    await page.screenshot({ path: path.join(outDir, "02-after-live-model-click.png"), fullPage: true });
    text = await page.locator("body").innerText({ timeout: 20000 }).catch(() => text);
  } else {
    await page.screenshot({ path: path.join(outDir, "02-no-live-button.png"), fullPage: true });
  }

  const after = await collectApis();
  let directRun = { attempted: false };
  if (!clickResult.clicked && !skipLive) {
    const activeSecret = before.modelGate?.json?.model_value?.active_secret_ref || "";
    directRun = await api(`/stores/${encodeURIComponent(storeId)}/model/value-rehearsal`, {
      method: "POST",
      body: JSON.stringify({
        allow_live_model: true,
        use_merchant_byok: true,
        model_secret_ref: activeSecret,
        packet_id: "packet_0b5dd20476f71eab",
        product: "Official eBay packet without selected SKU; analyze store-level listing readiness and missing product inputs",
        merchant_goal:
          "Codex end-to-end smoke: generate live Market Report and Listing Package from official eBay packet with merchant BYOK.",
      }),
    });
    directRun.attempted = true;
    await page.reload({ waitUntil: "domcontentloaded", timeout: 90000 }).catch(() => {});
    await page.waitForLoadState("networkidle", { timeout: 45000 }).catch(() => {});
    await page.waitForTimeout(5000);
    await page.screenshot({ path: path.join(outDir, "03-after-direct-api-run.png"), fullPage: true });
  }

  const finalApis = await collectApis();
  const result = {
    timestamp: new Date().toISOString(),
    target: {
      base,
      user_id: userId,
      company_id: companyId,
      store_id: storeId,
      store_name: storeName,
      marketplace,
      email_masked: maskEmail(email),
    },
    before: summarizeApi(before),
    after_click: summarizeApi(after),
    final: summarizeApi(finalApis),
    initialChecks,
    accountMenuChecks,
    clickResult,
    directRun: directRun.attempted ? { attempted: true, ok: directRun.ok, status: directRun.status, response: directRun.json } : directRun,
    consoleErrors,
    screenshots: {
      initial: path.join(outDir, "01-workflow-initial.png"),
      afterClick: path.join(outDir, clickResult.clicked ? "02-after-live-model-click.png" : skipLive ? "02-live-model-skipped.png" : "02-no-live-button.png"),
      afterDirectApi: directRun.attempted ? path.join(outDir, "03-after-direct-api-run.png") : "",
    },
  };
  fs.writeFileSync(path.join(outDir, "real-flow-result.json"), JSON.stringify(result, null, 2));
  console.log(
    JSON.stringify(
      {
        outDir,
        target: result.target,
        before: result.before,
        after_click: result.after_click,
        final: result.final,
        checks: initialChecks,
        accountMenuChecks,
        clickResult,
        directRun: result.directRun.attempted
          ? {
              attempted: true,
              ok: result.directRun.ok,
              status: result.directRun.status,
              responseType: result.directRun.response?.model_value_rehearsal?.status || result.directRun.response?.error || "",
            }
          : result.directRun,
        consoleErrors: consoleErrors.slice(0, 8),
        screenshots: result.screenshots,
      },
      null,
      2,
    ),
  );
  await browser.close();
}

main().catch((error) => {
  console.error(JSON.stringify({ error: String((error && error.stack) || error) }, null, 2));
  process.exit(1);
});
