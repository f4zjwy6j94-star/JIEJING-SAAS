#!/usr/bin/env node
/* Public HTTPS smoke that verifies ordinary merchants cannot see platform-internal launch control. */

const fs = require("fs");
const path = require("path");
const { chromium } = require("../output/codex-playwright-deps/node_modules/playwright-core");

const base = process.env.JIEJING_TEST_BASE || "https://app.jiejing.shop";
const browserChannel = process.env.JIEJING_PLAYWRIGHT_CHANNEL || "chrome";
const userAgent =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36";
const stamp = new Date().toISOString().replace(/[:.]/g, "-");
const outDir = path.join("output", "browser-smoke", `${stamp}-owner-launch-control-public`);
fs.mkdirSync(outDir, { recursive: true });

async function api(pathname, { token = "", method = "GET", body } = {}) {
  const res = await fetch(`${base}${pathname}`, {
    method,
    cache: "no-store",
    headers: {
      "content-type": "application/json",
      "user-agent": userAgent,
      ...(token ? { authorization: `Bearer ${token}` } : {}),
    },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
  const text = await res.text();
  let json = null;
  try {
    json = text ? JSON.parse(text) : null;
  } catch (_error) {
    json = { raw: text.slice(0, 500) };
  }
  return { ok: res.ok, status: res.status, json };
}

async function makeSession() {
  const suffix = `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  const email = `codex-owner-launch-${suffix}@local.invalid`;
  const password = `Codex-owner-launch-${suffix}`;
  const registered = await api("/auth/register", {
    method: "POST",
    body: {
      email,
      password,
      company_name: "Codex Owner Launch Smoke",
    },
  });
  if (!registered.ok) {
    throw new Error(`register failed: ${registered.status} ${JSON.stringify(registered.json).slice(0, 300)}`);
  }

  const token = registered.json.token;
  const user = registered.json.user || {};
  const company = registered.json.company || {};
  const billingActivation = await api("/billing/test-event", {
    token,
    method: "POST",
    body: {
      plan_key: "operator",
      action: "activate",
    },
  });
  const billingEvent = billingActivation.json?.billing_test_event || {};
  if (
    !billingActivation.ok ||
    billingEvent.ok !== true ||
    billingEvent.calls_stripe_api !== false ||
    billingEvent.triggers_real_charge !== false ||
    billingEvent.frontend_gets_payment_secret !== false
  ) {
    throw new Error(`test billing activation failed: ${billingActivation.status} ${JSON.stringify(billingActivation.json).slice(0, 300)}`);
  }
  const created = await api("/stores", {
    token,
    method: "POST",
    body: {
      platform: "ebay",
      store_name: "Codex Owner Launch Smoke Store",
      marketplace: "EBAY_US",
      stage: "store_opened",
      settings: {
        created_from: "codex_owner_launch_control_smoke",
        external_platform_authorization: false,
      },
    },
  });
  const store = created.ok ? created.json.store : { store_id: "" };

  return {
    token,
    email,
    userId: user.user_id || "",
    companyId: company.company_id || user.default_company_id || "",
    store,
    storeCreated: created.ok,
    storeCreateStatus: created.status,
    billingEvent,
  };
}

async function main() {
  const session = await makeSession();
  const ownerPacketResponse = await api("/owner/launch-control", { token: session.token });
  if (ownerPacketResponse.status !== 403) {
    throw new Error(`ordinary merchant should not fetch owner launch-control: ${ownerPacketResponse.status}`);
  }

  const appHtmlResponse = await fetch(`${base}/app.html?start=app&view=connect&smoke-source=${Date.now()}`, {
    cache: "no-store",
    headers: { "user-agent": userAgent },
  });
  if (!appHtmlResponse.ok) {
    throw new Error(`app html fetch failed: ${appHtmlResponse.status}`);
  }
  const appHtml = await appHtmlResponse.text();

  const browser = await chromium.launch({ channel: browserChannel, headless: true, timeout: 60000 });
  const context = await browser.newContext({ viewport: { width: 1440, height: 920 }, deviceScaleFactor: 1, userAgent });
  const baseUrl = new URL(base);
  await context.addCookies([
    {
      name: "jiejing_saas_session",
      value: session.token,
      domain: baseUrl.hostname,
      path: "/",
      httpOnly: true,
      secure: baseUrl.protocol === "https:",
      sameSite: "Lax",
    },
  ]);
  await context.route(`${base}/app.html**`, (route) =>
    route.fulfill({
      status: 200,
      contentType: "text/html; charset=utf-8",
      headers: { "cache-control": "no-store" },
      body: appHtml,
    }),
  );
  await context.addInitScript(
    ({ base, session }) => {
      const accountKey = String(session.userId || session.email || "codex").toLowerCase();
      localStorage.setItem("jiejing_saas_api_base", base);
      localStorage.setItem("jiejing_saas_backend_store_id", session.store.store_id);
      localStorage.setItem("jiejing_saas_backend_session_hint", "1");
      localStorage.setItem("jiejing_saas_session_hint", "1");
      localStorage.setItem("jiejing_saas_last_account", accountKey);
      localStorage.setItem(`jiejing_saas_onboarding_done:${accountKey}`, "1");
      localStorage.setItem(
        "jiejing_saas_known_accounts",
        JSON.stringify([
          {
            account_key: accountKey,
            user_id: session.userId,
            email: session.email,
            company_id: session.companyId,
            display_name: "Codex Owner Launch",
            last_seen: new Date().toISOString(),
          },
        ]),
      );
      window.__JIEJING_FORCE_PUBLIC_MVP__ = true;
    },
    { base, session },
  );

  const page = await context.newPage();
  page.setDefaultTimeout(45000);
  const pageErrors = [];
  const consoleMessages = [];
  page.on("pageerror", (error) => pageErrors.push(String(error.message || error).slice(0, 500)));
  page.on("console", (message) => {
    if (["error", "warning"].includes(message.type())) {
      const rendered = `${message.type()}: ${message.text()}`.slice(0, 500);
      if (
        !rendered.includes("cdn-cgi/rum") &&
        !rendered.includes("Cloudflare") &&
        !rendered.includes("[Jiejing optional API skipped] /owner/launch-control") &&
        !rendered.includes("the server responded with a status of 403") &&
        !rendered.includes("preloaded using link preload but not used")
      ) {
        consoleMessages.push(rendered);
      }
    }
  });

  await page.goto(`${base}/app.html?start=app&view=connect&smoke=${Date.now()}`, { waitUntil: "commit", timeout: 90000 });
  await page.waitForSelector(".saas-settings-clean-shell", { timeout: 60000 });
  await page.locator('[data-saas-settings-tab="launch"]').click();
  await page.waitForTimeout(3000);
  await page.screenshot({ path: path.join(outDir, "owner-launch-control-hidden-public.png"), fullPage: true, timeout: 15000 });

  const ui = await page.evaluate(() => {
    const panel = document.querySelector(".saas-owner-launch-control");
    const text = panel?.innerText || "";
    return {
      hasOwnerPanel: Boolean(panel && panel.offsetParent !== null),
      summaryCount: panel?.querySelectorAll(".saas-owner-launch-summary article").length || 0,
      laneCount: panel?.querySelectorAll(".saas-owner-launch-lanes article").length || 0,
      queueColumnCount: panel?.querySelectorAll(".saas-owner-launch-queues article").length || 0,
      safetyPillCount: panel?.querySelectorAll(".saas-owner-launch-safety span").length || 0,
      warRoomCount: panel?.querySelectorAll(".saas-owner-war-room-grid article").length || 0,
      ownerReviewCardCount: panel?.querySelectorAll(".saas-owner-review-grid article").length || 0,
      launchAuditCardCount: panel?.querySelectorAll(".saas-owner-launch-audit-grid article").length || 0,
      releaseHistoryCardCount: panel?.querySelectorAll(".saas-owner-release-history-grid article").length || 0,
      releaseHistoryCheckCount: panel?.querySelectorAll(".saas-owner-release-check-grid article").length || 0,
      rollbackPointCount: panel?.querySelectorAll(".saas-owner-release-rollback-list span").length || 0,
      continuityHandoffCardCount: panel?.querySelectorAll(".saas-owner-continuity-grid article").length || 0,
      continuityHandoffActionCount: panel?.querySelectorAll(".saas-owner-continuity-actions article").length || 0,
      continuityHandoffNoGoCount: panel?.querySelectorAll(".saas-owner-continuity-no-go span").length || 0,
      opsCardCount: panel?.querySelectorAll(".saas-owner-ops-grid article").length || 0,
      resilienceCardCount: panel?.querySelectorAll(".saas-owner-resilience-grid article").length || 0,
      subscriptionShutdownCardCount: panel?.querySelectorAll(".saas-owner-subscription-shutdown-grid article").length || 0,
      testDataMetricCount: panel?.querySelectorAll(".saas-owner-test-data-grid article").length || 0,
      hasChargeFalse: text.includes("charge_now_allowed=false"),
      hasWriteFalse: text.includes("platform_write_now_allowed=false"),
      hasOauthFalse: text.includes("repeat_ebay_oauth_allowed=false"),
      hasSecretFalse: text.includes("secret_exposed=false"),
      hasBillingExternalBlocker: text.includes("Stripe live Products"),
      hasEbayExternalBlocker: text.includes("Clean new eBay account"),
      hasWarRoom: Boolean(panel?.querySelector('.saas-owner-war-room[aria-label="owner war room v3"]')),
      hasOwnerReviewPacket: Boolean(panel?.querySelector('.saas-owner-review-packet[aria-label="owner review packet"]')),
      hasLaunchRehearsalAudit: Boolean(panel?.querySelector('.saas-owner-launch-audit[aria-label="launch rehearsal audit"]')),
      hasReleaseHistory: Boolean(panel?.querySelector('.saas-owner-release-history[aria-label="owner release history"]')),
      hasContinuityHandoff: Boolean(panel?.querySelector('.saas-owner-continuity-handoff[aria-label="owner continuity handoff"]')),
      hasOpsObservability: Boolean(panel?.querySelector('.saas-owner-ops-observability[aria-label="owner operations observability"]')),
      hasResilienceWarRoom: Boolean(panel?.querySelector('.saas-owner-resilience-war-room[aria-label="owner resilience war room"]')),
      hasSubscriptionShutdownControl: Boolean(panel?.querySelector('.saas-owner-subscription-shutdown[aria-label="owner subscription shutdown control"]')),
      hasTestDataGovernance: Boolean(panel?.querySelector('.saas-owner-test-data[aria-label="owner test data governance"]')),
      hasDeleteBlocked: text.includes("delete_now_allowed") && text.includes("false"),
    };
  });

  await browser.close();
  const result = {
    ok:
      ownerPacketResponse.status === 403 &&
      !ui.hasOwnerPanel &&
      ui.summaryCount === 0 &&
      ui.warRoomCount === 0 &&
      ui.ownerReviewCardCount === 0 &&
      ui.launchAuditCardCount === 0 &&
      ui.releaseHistoryCardCount === 0 &&
      ui.releaseHistoryCheckCount === 0 &&
      ui.rollbackPointCount === 0 &&
      ui.continuityHandoffCardCount === 0 &&
      ui.continuityHandoffActionCount === 0 &&
      ui.continuityHandoffNoGoCount === 0 &&
      ui.opsCardCount === 0 &&
      ui.resilienceCardCount === 0 &&
      ui.subscriptionShutdownCardCount === 0 &&
      ui.testDataMetricCount === 0 &&
      !ui.hasWarRoom &&
      !ui.hasOwnerReviewPacket &&
      !ui.hasLaunchRehearsalAudit &&
      !ui.hasReleaseHistory &&
      !ui.hasContinuityHandoff &&
      !ui.hasOpsObservability &&
      !ui.hasResilienceWarRoom &&
      !ui.hasSubscriptionShutdownControl &&
      !ui.hasTestDataGovernance &&
      pageErrors.length === 0 &&
      consoleMessages.length === 0,
    base,
    session: {
      userId: session.userId,
      companyId: session.companyId,
      storeId: session.store?.store_id || "",
      storeCreated: session.storeCreated,
      storeCreateStatus: session.storeCreateStatus,
    },
    billingTestActivation: {
      status: session.billingEvent.status,
      provider: session.billingEvent.provider,
      callsStripeApi: session.billingEvent.calls_stripe_api,
      triggersRealCharge: session.billingEvent.triggers_real_charge,
      frontendGetsPaymentSecret: session.billingEvent.frontend_gets_payment_secret,
      secretExposed: session.billingEvent.secret_exposed,
    },
    ownerEndpoint: {
      status: ownerPacketResponse.status,
      ordinaryMerchantForbidden: ownerPacketResponse.status === 403,
      secretExposed: false,
    },
    ui,
    consoleMessages,
    pageErrors,
    output_root: path.resolve(outDir),
    secret_exposed: false,
  };
  fs.writeFileSync(path.join(outDir, "owner_launch_control_public_result.json"), JSON.stringify(result, null, 2));
  console.log(JSON.stringify(result, null, 2));
  if (!result.ok) process.exitCode = 1;
}

main().catch((error) => {
  const result = {
    ok: false,
    base,
    error: String(error && error.stack ? error.stack : error).slice(0, 2000),
    output_root: path.resolve(outDir),
    secret_exposed: false,
  };
  fs.writeFileSync(path.join(outDir, "owner_launch_control_public_result.json"), JSON.stringify(result, null, 2));
  console.error(JSON.stringify(result, null, 2));
  process.exitCode = 1;
});
