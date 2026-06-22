#!/usr/bin/env node
/* Verify the deployed Jiejing staging UI after backend recovery. */

const fs = require("fs");
const path = require("path");
const { chromium } = require("../output/codex-playwright-deps/node_modules/playwright-core");

const base = process.env.JIEJING_TEST_BASE || "https://individually-buffalo-prescribed-blocking.trycloudflare.com";
const token = process.env.JIEJING_TEST_TOKEN;
const userId = process.env.JIEJING_TEST_USER_ID || "";
const companyId = process.env.JIEJING_TEST_COMPANY_ID || "";
const storeId = process.env.JIEJING_TEST_STORE_ID || "";
const email = process.env.JIEJING_TEST_EMAIL || "";
const storeName = process.env.JIEJING_TEST_STORE_NAME || "";
const marketplace = process.env.JIEJING_TEST_MARKETPLACE || "";
const expectedPacketId = process.env.JIEJING_EXPECT_PACKET_ID || "";
const expectedNavCount = Number(process.env.JIEJING_EXPECT_NAV_COUNT || 7);

if (!token || !storeId) {
  throw new Error("missing JIEJING_TEST_TOKEN/JIEJING_TEST_STORE_ID");
}

const stamp = new Date().toISOString().replace(/[:.]/g, "-");
const outDir = path.join("output", "browser-smoke", `${stamp}-ui-recovery`);
fs.mkdirSync(outDir, { recursive: true });

function maskEmail(value) {
  const [name, domain] = String(value || "").split("@");
  return `${name.slice(0, 2)}***@${domain || ""}`;
}

async function main() {
  const browser = await chromium.launch({ channel: "msedge", headless: true, timeout: 60000 });
  const context = await browser.newContext({ viewport: { width: 1440, height: 920 }, deviceScaleFactor: 1 });
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
    ({ base, token, userId, companyId, storeId, email, storeName }) => {
      localStorage.setItem("jiejing_saas_api_base", base);
      localStorage.setItem("jiejing_saas_backend_store_id", storeId);
      localStorage.setItem("jiejing_saas_backend_session_hint", "1");
      localStorage.setItem("jiejing_saas_last_account", String(userId || email || "browser").toLowerCase());
      localStorage.setItem(`jiejing_saas_onboarding_done:${String(userId || email || "browser").toLowerCase()}`, "1");
      localStorage.setItem(
        "jiejing_saas_known_accounts",
        JSON.stringify([
          {
            account_key: String(userId || email || "").toLowerCase(),
            user_id: userId,
            email,
            company_id: companyId,
            display_name: storeName || email,
            last_seen: new Date().toISOString(),
          },
        ]),
      );
    },
    { base, token, userId, companyId, storeId, email, storeName },
  );

  const page = await context.newPage();
  page.setDefaultTimeout(45000);
  const consoleIssues = [];
  const failedRequests = [];
  const badResponses = [];
  page.on("console", (msg) => {
    if (["error", "warning"].includes(msg.type())) {
      consoleIssues.push({ type: msg.type(), text: msg.text().slice(0, 500) });
    }
  });
  page.on("requestfailed", (request) => {
    const url = request.url();
    if (url.startsWith(base)) {
      failedRequests.push({ url, error: request.failure()?.errorText || "" });
    }
  });
  page.on("response", (response) => {
    const url = response.url();
    if (url.startsWith(base) && response.status() >= 400) {
      badResponses.push({ url, status: response.status(), statusText: response.statusText() });
    }
  });

  await page.goto(`${base}/app.html?start=app&view=cockpit&smoke=${Date.now()}`, {
    waitUntil: "domcontentloaded",
    timeout: 90000,
  });
  await page.waitForLoadState("networkidle", { timeout: 45000 }).catch(() => {});
  await page.waitForTimeout(3500);

  const apiSummary = await page.evaluate(
    async ({ base, token, storeId }) => {
      async function get(pathname) {
        const res = await fetch(`${base}${pathname}`, {
          headers: { authorization: `Bearer ${token}`, "content-type": "application/json" },
        });
        const text = await res.text();
        let json = null;
        try {
          json = text ? JSON.parse(text) : null;
        } catch (_error) {
          json = { raw: text.slice(0, 300) };
        }
        return { ok: res.ok, status: res.status, json };
      }
      const [health, readiness, stores, packets, reports, confirmations, modelGate] = await Promise.all([
        fetch(`${base}/health`).then(async (res) => ({ ok: res.ok, status: res.status, json: await res.json() })),
        get("/readiness/product-saas"),
        get("/stores"),
        get(`/data-packets?store_id=${encodeURIComponent(storeId)}&platform=ebay`),
        get("/reports?limit=40"),
        get("/confirmations?limit=40"),
        get("/model/value-gate"),
      ]);
      const readinessBody = readiness.json?.readiness || {};
      const packetList = packets.json?.data_packets || [];
      const reportList = reports.json?.reports || [];
      const confirmationList = confirmations.json?.confirmations || [];
      const byok = modelGate.json?.model_value_gate?.merchant_byok_model || {};
      return {
        health: {
          status: health.status,
          database_startup_status: health.json?.database_startup_status,
          real_platform_writes_enabled: health.json?.real_platform_writes_enabled,
          secret_exposed: health.json?.secret_exposed,
        },
        readiness: {
          status: readiness.status,
          production_ready: readinessBody.production_ready,
          beta_ready: readinessBody.beta_ready,
          blocker_count: readinessBody.blocker_count,
          warning_count: readinessBody.warning_count,
          platform_connections: readinessBody.counts?.platform_connections,
          platform_data_packets: readinessBody.counts?.platform_data_packets,
          reports: readinessBody.counts?.reports,
          confirmations: readinessBody.counts?.confirmations,
          latest_ebay_packet_id: readinessBody.product_evidence?.latest_ebay_packet_id,
          real_platform_writes_enabled: readinessBody.real_platform_writes_enabled,
          secret_exposed: readinessBody.secret_exposed,
        },
        stores: { status: stores.status, count: (stores.json?.stores || []).length },
        packets: {
          status: packets.status,
          count: packetList.length,
          latest_packet_id: packetList[0]?.packet_id || "",
          latest_source_mode: packetList[0]?.source_mode || "",
          latest_status: packetList[0]?.status || "",
        },
        reports: { status: reports.status, count: reportList.length },
        confirmations: {
          status: confirmations.status,
          count: confirmationList.length,
          pending: confirmationList.filter((item) => item.status === "pending").length,
        },
        byok: {
          status: modelGate.status,
          configured: Boolean(byok.configured),
          ready_secret_ref_count: Number(byok.ready_secret_ref_count || 0),
        },
      };
    },
    { base, token, storeId },
  );

  await page
    .waitForFunction(
      (expected) => {
        const ctx = typeof window.saasMerchantWorkbenchContext === "function"
          ? window.saasMerchantWorkbenchContext()
          : null;
        if (!ctx || !ctx.connection || !ctx.hasPacket || Number(ctx.presentCount || 0) <= 0) return false;
        if (Number(expected.pending || 0) > 0 && Number(ctx.pendingConfirmations?.length || 0) <= 0) return false;
        return true;
      },
      { pending: apiSummary.confirmations.pending },
      { timeout: 90000 },
    )
    .catch(() => {});
  await page.waitForFunction(() => !document.querySelector(".saas-protected-loading-view"), null, { timeout: 30000 }).catch(() => {});
  await page.waitForTimeout(1000);

  const frontendContext = await page.evaluate(() => {
    const ctx = typeof window.saasMerchantWorkbenchContext === "function" ? window.saasMerchantWorkbenchContext() : null;
    return {
      hasPacket: Boolean(ctx?.hasPacket),
      presentCount: Number(ctx?.presentCount || 0),
      coverageTotal: Number(ctx?.coverageTotal || 0),
      latestPacketId: ctx?.latestPacket?.packet_id || ctx?.packetBody?.packet_id || "",
      connectionStatus: ctx?.connection?.status || "",
      storeId: ctx?.store?.store_id || "",
      pendingConfirmations: Number(ctx?.pendingConfirmations?.length || 0),
      reportCount: Number(ctx?.reports?.length || 0),
    };
  });

  const modules = [
    ["cockpit", "view-cockpit"],
    ["product", "view-product"],
    ["bulk", "view-bulk"],
    ["media", "view-media"],
    ["confirm", "view-confirm"],
    ["service", "view-service"],
    ["connect", "view-connect"],
  ];
  const moduleChecks = [];
  for (const [view, id] of modules) {
    await page.locator(`.nav-item[data-view="${view}"]`).click();
    await page.waitForFunction(() => !document.querySelector(".saas-protected-loading-view"), null, { timeout: 30000 }).catch(() => {});
    await page.waitForTimeout(900);
    const section = page.locator(`#${id}`);
    const text = await section.innerText({ timeout: 15000 }).catch(() => "");
    await page.screenshot({ path: path.join(outDir, `${view}.png`), fullPage: true });
    moduleChecks.push({
      view,
      visible: await section.isVisible().catch(() => false),
      text_length: text.length,
      blank: text.trim().length < 120,
      has_login_overlay: /进入捷境账号|登录失败|请先登录/.test(text),
      has_expected_media_controls:
        view !== "media" || (/流程导入/.test(text) && /独立素材/.test(text) && /生成/.test(text)),
      has_expected_bulk_controls: view !== "bulk" || (/批量/.test(text) && /质检/.test(text)),
      preview: text.slice(0, 500),
    });
  }

  const navCount = await page.locator(".nav-item").count();
  const bodyText = await page.locator("body").innerText({ timeout: 15000 });
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
    navCount,
    apiSummary,
    frontendContext,
    moduleChecks,
    pageChecks: {
      final_url: page.url(),
      title: await page.title(),
      has_login_overlay: /进入捷境账号|登录失败|请先登录/.test(bodyText),
      has_ai_ceo: /AI CEO/.test(bodyText),
      has_secret_token_words: /refresh token|access token/i.test(bodyText),
      has_api_key_label: /api key/i.test(bodyText),
      has_raw_secret_hint: /refresh token|access token|client secret|secret value/i.test(bodyText),
    },
    failedRequests,
    badResponses,
    consoleIssues: consoleIssues.slice(0, 20),
    outDir,
  };
  fs.writeFileSync(path.join(outDir, "ui-recovery-result.json"), JSON.stringify(result, null, 2));
  console.log(JSON.stringify(result, null, 2));
  if (navCount !== expectedNavCount) {
    throw new Error(`expected ${expectedNavCount} navigation modules, got ${navCount}`);
  }
  const blankModules = moduleChecks.filter((item) => item.blank || !item.visible || item.has_login_overlay);
  if (blankModules.length) {
    throw new Error(`module render regression: ${blankModules.map((item) => item.view).join(", ")}`);
  }
  const missingExpectedControls = moduleChecks.filter((item) => !item.has_expected_media_controls || !item.has_expected_bulk_controls);
  if (missingExpectedControls.length) {
    throw new Error(`module control regression: ${missingExpectedControls.map((item) => item.view).join(", ")}`);
  }
  if (apiSummary.health.database_startup_status !== "ready") {
    throw new Error(`backend database startup is not ready: ${apiSummary.health.database_startup_status}`);
  }
  if (apiSummary.health.real_platform_writes_enabled !== false || apiSummary.readiness.real_platform_writes_enabled !== false) {
    throw new Error("staging smoke must keep real platform writes disabled");
  }
  if (apiSummary.readiness.secret_exposed !== false || apiSummary.health.secret_exposed !== false) {
    throw new Error("readiness or health exposed a secret flag");
  }
  if (expectedPacketId) {
    const observedPackets = [
      apiSummary.readiness.latest_ebay_packet_id,
      apiSummary.packets.latest_packet_id,
      frontendContext.latestPacketId,
    ];
    if (!observedPackets.every((packetId) => packetId === expectedPacketId)) {
      throw new Error(`expected packet ${expectedPacketId}, got ${observedPackets.join(" / ")}`);
    }
  }
  if (result.pageChecks.has_login_overlay) {
    throw new Error("authenticated smoke still shows login overlay");
  }
  if (result.pageChecks.has_raw_secret_hint) {
    throw new Error("page text contains raw secret/token wording");
  }
  if (failedRequests.length) {
    throw new Error(`staging smoke had failed backend requests: ${failedRequests.map((item) => item.url).join(", ")}`);
  }
  if (badResponses.length) {
    throw new Error(`staging smoke had bad backend responses: ${badResponses.map((item) => `${item.status} ${item.url}`).join(", ")}`);
  }
  if (apiSummary.packets.count > 0 && !frontendContext.hasPacket) {
    throw new Error("frontend context did not expose the backend eBay data packet");
  }
  if (apiSummary.packets.count > 0 && frontendContext.presentCount <= 0) {
    throw new Error("frontend context did not expose official packet resource coverage");
  }
  if (apiSummary.confirmations.pending > 0 && frontendContext.pendingConfirmations <= 0) {
    throw new Error("frontend context did not expose pending confirmations");
  }
  await browser.close();
}

main().catch((error) => {
  console.error(JSON.stringify({ error: String(error && error.stack ? error.stack : error) }, null, 2));
  process.exit(1);
});
