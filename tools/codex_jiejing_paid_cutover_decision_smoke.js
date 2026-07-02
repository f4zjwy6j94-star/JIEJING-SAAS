#!/usr/bin/env node
/* ASCII-only smoke for the paid launch cutover decision in Settings. */

const fs = require("fs");
const path = require("path");
const { chromium } = require("../output/codex-playwright-deps/node_modules/playwright-core");

const base = process.env.JIEJING_TEST_BASE || "https://app.jiejing.shop";
const browserChannel = process.env.JIEJING_PLAYWRIGHT_CHANNEL || "chrome";
const stamp = new Date().toISOString().replace(/[:.]/g, "-");
const outDir = path.join("output", "browser-smoke", `${stamp}-paid-cutover-decision`);
fs.mkdirSync(outDir, { recursive: true });

async function api(pathname, { token = "", method = "GET", body } = {}) {
  const res = await fetch(`${base}${pathname}`, {
    method,
    cache: "no-store",
    headers: {
      "content-type": "application/json",
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
  const email = `codex-cutover-${suffix}@local.invalid`;
  const password = `Codex-cutover-${suffix}`;
  const registered = await api("/auth/register", {
    method: "POST",
    body: {
      email,
      password,
      company_name: "Codex Cutover Decision Smoke",
    },
  });
  if (!registered.ok) {
    throw new Error(`register failed: ${registered.status} ${JSON.stringify(registered.json).slice(0, 300)}`);
  }
  const token = registered.json.token;
  const user = registered.json.user || {};
  const company = registered.json.company || {};
  const activatedBilling = await api("/billing/test-event", {
    token,
    method: "POST",
    body: {
      plan_key: "operator",
      action: "activate",
    },
  });
  if (!activatedBilling.ok) {
    throw new Error(`billing test activation failed before store create: ${activatedBilling.status} ${JSON.stringify(activatedBilling.json).slice(0, 300)}`);
  }
  const created = await api("/stores", {
    token,
    method: "POST",
    body: {
      platform: "ebay",
      store_name: "Codex Cutover Decision Store",
      marketplace: "EBAY_US",
      stage: "store_opened",
      settings: {
        created_from: "codex_paid_cutover_decision_smoke",
        placeholder_store_name: true,
      },
    },
  });
  if (!created.ok) {
    throw new Error(`store create failed: ${created.status} ${JSON.stringify(created.json).slice(0, 300)}`);
  }
  return {
    token,
    email,
    userId: user.user_id || "",
    companyId: company.company_id || user.default_company_id || "",
    activatedBilling: activatedBilling.json.billing_test_event || {},
    store: created.json.store,
  };
}

async function main() {
  const session = await makeSession();
  const gate = await api("/commercial/launch-gate", { token: session.token });
  if (!gate.ok) {
    throw new Error(`launch gate fetch failed: ${gate.status}`);
  }
  const billing = await api("/billing/plans", { token: session.token });
  if (!billing.ok) {
    throw new Error(`billing plan fetch failed: ${billing.status}`);
  }
  const protectedEvidence = {
    legacyBillingDomain: await api("/commercial/billing-domain-cutover-rehearsal", { token: session.token }),
    ownerBillingDomain: await api("/owner/billing-domain-cutover-rehearsal", { token: session.token }),
    legacyEdge: await api("/domain/edge-cutover-preflight", { token: session.token }),
    ownerEdge: await api("/owner/edge-cutover-preflight", { token: session.token }),
    legacyApproval: await api("/commercial/paid-launch-approval-packet", { token: session.token }),
    ownerApproval: await api("/owner/paid-launch-approval-packet", { token: session.token }),
    legacyProviderRegister: await api("/commercial/billing-provider-evidence-register", { token: session.token }),
    ownerProviderRegister: await api("/owner/billing-provider-evidence-register", { token: session.token }),
    paymentOptions: await api("/billing/payment-options", { token: session.token }),
  };
  const ownerPacketResponse = await api("/owner/launch-control", { token: session.token });
  const launchGate = gate.json.commercial_launch_gate || {};
  const plan = launchGate.launch_action_plan || {};
  const decision = plan.paid_launch_cutover_decision || launchGate.paid_launch_cutover_decision || {};
  const smokeRunbook = plan.new_ebay_account_smoke_runbook || launchGate.new_ebay_account_smoke_runbook || [];
  const billingPlan = billing.json.billing_plan || {};
  const billingMatrix = Array.isArray(billingPlan.billing_live_cutover_matrix) ? billingPlan.billing_live_cutover_matrix : [];
  const rehearsal = (protectedEvidence.ownerBillingDomain.json || {}).billing_domain_cutover_rehearsal || {};
  const rehearsalStages = Array.isArray(rehearsal.stages) ? rehearsal.stages : [];
  const noChargeEvidencePacket = rehearsal.no_charge_live_domain_evidence_packet || {};
  const noChargeEvidenceItems = Array.isArray(noChargeEvidencePacket.evidence_items) ? noChargeEvidencePacket.evidence_items : [];
  const edgePreflight = (protectedEvidence.ownerEdge.json || {}).edge_cutover_preflight || {};
  const edgeStages = Array.isArray(edgePreflight.stages) ? edgePreflight.stages : [];
  const approvalPacket = (protectedEvidence.ownerApproval.json || {}).paid_launch_approval_packet || {};
  const approvalSteps = Array.isArray(approvalPacket.steps) ? approvalPacket.steps : [];
  const providerRegister = (protectedEvidence.ownerProviderRegister.json || {}).billing_provider_evidence_register || {};
  const providerRegisterRows = Array.isArray(providerRegister.evidence_rows) ? providerRegister.evidence_rows : [];
  const providerCutoverDossier =
    providerRegister.provider_cutover_dossier && typeof providerRegister.provider_cutover_dossier === "object"
      ? providerRegister.provider_cutover_dossier
      : {};
  const providerCutoverDossierSummary =
    providerCutoverDossier.summary && typeof providerCutoverDossier.summary === "object" ? providerCutoverDossier.summary : {};
  const providerCutoverDossierSections = Array.isArray(providerCutoverDossier.sections) ? providerCutoverDossier.sections : [];
  const providerCutoverDossierActivation = Array.isArray(providerCutoverDossier.activation_sequence)
    ? providerCutoverDossier.activation_sequence
    : [];
  const appHtmlResponse = await fetch(`${base}/app.html?start=app&view=connect&smoke-source=${Date.now()}`, { cache: "no-store" });
  if (!appHtmlResponse.ok) {
    throw new Error(`app html fetch failed: ${appHtmlResponse.status}`);
  }
  const appHtml = await appHtmlResponse.text();

  const browser = await chromium.launch({ channel: browserChannel, headless: true, timeout: 60000 });
  const context = await browser.newContext({ viewport: { width: 1440, height: 920 }, deviceScaleFactor: 1 });
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
            display_name: "Codex Cutover Decision",
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
  const relevantConsoleMessages = [];
  page.on("pageerror", (error) => pageErrors.push(String(error.message || error).slice(0, 500)));
  page.on("console", (message) => {
    if (["error", "warning"].includes(message.type())) {
      const rendered = `${message.type()}: ${message.text()}`.slice(0, 500);
      if (!isIgnorableConsoleMessage(rendered)) {
        relevantConsoleMessages.push(rendered);
      }
    }
  });

  await page.goto(`${base}/app.html?start=app&view=connect&smoke=${Date.now()}`, { waitUntil: "commit", timeout: 90000 });
  await page.waitForSelector(".saas-settings-clean-shell", { timeout: 60000 });
  const ownerOpsTab = page.locator('[data-saas-settings-tab="owner_ops"]');
  const ownerOpsVisible = (await ownerOpsTab.count()) > 0;
  if (ownerOpsVisible) {
    await ownerOpsTab.click();
    await page.waitForSelector(".saas-edge-cutover-readiness", { timeout: 60000 });
    await page.waitForSelector(".saas-paid-launch-cutover-decision", { timeout: 60000 });
    await page.waitForSelector(".saas-new-ebay-smoke-runbook", { timeout: 60000 });
    await page.waitForSelector(".saas-billing-live-cutover-matrix", { timeout: 60000 });
    await page.waitForSelector(".saas-billing-domain-cutover-rehearsal", { timeout: 60000 });
    await page.waitForSelector(".saas-paid-launch-approval-packet", { timeout: 60000 });
  } else {
    await page.locator('[data-saas-settings-tab="billing"]').click();
    await page.waitForSelector(".saas-merchant-billing-plain-summary", { timeout: 60000 });
    await page.waitForSelector(".saas-merchant-billing-continuity", { timeout: 60000 });
  }
  let screenshotError = "";
  await page
    .screenshot({ path: path.join(outDir, "paid-cutover-decision.png"), fullPage: true, timeout: 30000 })
    .catch((error) => {
      screenshotError = String(error.message || error).slice(0, 500);
    });

  const ui = await page.evaluate(() => {
    const decision = document.querySelector(".saas-paid-launch-cutover-decision");
    const launch = document.querySelector(".saas-launch-action-plan");
    const smoke = document.querySelector(".saas-new-ebay-smoke-runbook");
    const settings = document.querySelector(".saas-settings-clean-content");
    const edge = document.querySelector(".saas-edge-cutover-readiness");
    const billing = document.querySelector(".saas-billing-live-cutover-matrix");
    const rehearsal = document.querySelector(".saas-billing-domain-cutover-rehearsal");
    const approval = document.querySelector(".saas-paid-launch-approval-packet");
    const ownerOpsTab = document.querySelector('[data-saas-settings-tab="owner_ops"]');
    const publicBillingCutover = document.querySelector(".saas-paid-cutover-blockers");
    const incidentRunbook = document.querySelector(".saas-merchant-billing-incident-runbook");
    const text = launch?.innerText || decision?.innerText || "";
    const settingsText = settings?.innerText || text;
    const edgeText = edge?.innerText || settingsText;
    const billingText = billing?.innerText || settingsText;
    const rehearsalText = rehearsal?.innerText || settingsText;
    const approvalText = approval?.innerText || settingsText;
    const merchantBillingForbiddenVisible = [
      "大陆收款方式",
      "大陆用户",
      "个体工商户",
      "个体户",
      "主体资料",
      "聚合收单",
      "微信",
      "支付宝",
      "云闪付",
      "个人码",
      "个人收款码",
      "平台管理员",
      "主理人",
      "上线前检查",
      "支付后台配置",
      "正式商户支付",
    ].some((marker) => settingsText.includes(marker));
    return {
      visible: Boolean(decision && decision.offsetParent !== null),
      launchVisible: Boolean(launch && launch.offsetParent !== null),
      smokeVisible: Boolean(smoke && smoke.offsetParent !== null),
      edgeVisible: Boolean(edge && edge.offsetParent !== null),
      billingVisible: Boolean(billing && billing.offsetParent !== null),
      rehearsalVisible: Boolean(rehearsal && rehearsal.offsetParent !== null),
      approvalVisible: Boolean(approval && approval.offsetParent !== null),
      ownerOpsTabVisible: Boolean(ownerOpsTab && ownerOpsTab.offsetParent !== null),
      publicBillingCutoverVisible: Boolean(publicBillingCutover && publicBillingCutover.offsetParent !== null),
      incidentRunbookVisible: Boolean(incidentRunbook && incidentRunbook.offsetParent !== null),
      text,
      cardCount: decision?.querySelectorAll("article").length || 0,
      hasBlockedStatus: text.includes("blocked"),
      hasNoCharge: text.includes("charge_now_allowed=false"),
      hasNoPlatformWrite: text.includes("platform_write_now_allowed=false"),
      hasRepeatOauthFalse: text.includes("repeat_oauth=false"),
      hasBillingNextStep: text.includes("billing_provider_live_contract") || text.includes("Stripe subscription billing contract"),
      hasRunbook: text.includes("billing_domain_cutover_runbook"),
      hasWebhookResilience: text.includes("Stripe live webhook resilience") || text.includes("stripe_live_webhook_resilience"),
      hasStableDomainOauthCors: text.includes("Stable domain OAuth callback and CORS alignment") || text.includes("stable_domain_oauth_cors_alignment"),
      hasNewAccountSmoke: text.includes("new_ebay_account_smoke_runbook"),
      hasCleanAccountStep: text.includes("clean_new_account_declared") || text.includes("Clean new eBay account boundary"),
      hasOauthGate: text.includes("new_account_oauth_authorization_gate") || text.includes("New-account OAuth authorization gate"),
      hasCleanupGate: text.includes("post_publish_cockpit_cleanup_gate") || text.includes("Post-publish cockpit and test cleanup gate"),
      hasEdgeCutover: edgeText.includes("edge_cutover_preflight") || edgeText.includes("稳定域名 / WAF / 源站锁体检"),
      hasEdgeStableDomain: edgeText.includes("stable_domain_purchase_confirmed"),
      hasEdgeWaf: edgeText.includes("waf_edge_onboarded"),
      hasEdgeOriginLock: edgeText.includes("origin_direct_access_locked"),
      hasEdgeCallbacks: edgeText.includes("ebay_stripe_callbacks_on_stable_domain"),
      hasEdgeNoCharge: edgeText.includes("charge_now_allowed=false"),
      hasEdgeNoCheckout: edgeText.includes("creates_checkout_session=false") || edgeText.includes("no_checkout_created"),
      hasEdgeNoStripeCall: edgeText.includes("calls_stripe_api=false"),
      hasEdgeNoOauth: edgeText.includes("triggers_ebay_oauth=false") || edgeText.includes("no_oauth"),
      hasEdgeNoWrite: edgeText.includes("triggers_real_platform_write=false") || edgeText.includes("no_platform_write"),
      hasEdgeNoFrontendSecret: edgeText.includes("frontend_gets_payment_secret=false") || edgeText.includes("secret_exposed_false"),
      hasBillingMatrix: billingText.includes("stripe_billing_live_cutover_matrix"),
      hasBillingProviderStep: billingText.includes("stripe_live_provider_selected") || billingText.includes("Stripe live provider"),
      hasBillingWebhookStep: billingText.includes("stripe_signed_webhook_contract") || billingText.includes("Signed webhook endpoint contract"),
      hasBillingQuotaLifecycle: billingText.includes("stripe_entitlement_quota_lifecycle") || billingText.includes("Entitlement, quota and payment-failure lifecycle"),
      hasRehearsal: rehearsalText.includes("stripe_domain_cutover_rehearsal"),
      hasRehearsalCheckoutUrls: rehearsalText.includes("stripe_checkout_return_urls_on_stable_domain"),
      hasRehearsalSignedWebhook: rehearsalText.includes("stripe_signed_webhook_on_stable_domain"),
      hasRehearsalQuotaLifecycle: rehearsalText.includes("subscription_state_and_quota_lifecycle_rehearsed"),
      hasRehearsalNoCheckoutCreated: rehearsalText.includes("creates_checkout_session=false") || rehearsalText.includes("no_checkout_created"),
      hasRehearsalNoStripeCall: rehearsalText.includes("calls_stripe_api=false") || rehearsalText.includes("no_stripe_call"),
      hasRehearsalNoEbayOauth: rehearsalText.includes("triggers_ebay_oauth=false") || rehearsalText.includes("no_oauth"),
      hasRehearsalNoFrontendSecret: rehearsalText.includes("frontend_gets_payment_secret=false") || rehearsalText.includes("secret_exposed_false"),
      hasApprovalPacket: approvalText.includes("paid_launch_approval_packet"),
      hasApprovalStableDomain: approvalText.includes("stable_domain_hardening"),
      hasApprovalStripeCutover: approvalText.includes("stripe_live_cutover"),
      hasApprovalNoChargeRehearsal: approvalText.includes("no_charge_launch_rehearsal"),
      hasApprovalNewEbaySmoke: approvalText.includes("new_ebay_account_low_risk_smoke"),
      hasApprovalExternalConfig: approvalText.includes("external_configuration_needed"),
      hasApprovalNoCharge: approvalText.includes("charge_now_allowed=false") || approvalText.includes("no_charge"),
      hasApprovalNoStripeCall: approvalText.includes("calls_stripe_api=false") || approvalText.includes("no_stripe_call"),
      hasApprovalNoOauth: approvalText.includes("triggers_ebay_oauth=false") || approvalText.includes("no_oauth"),
      hasApprovalNoWrite: approvalText.includes("triggers_real_platform_write=false") || approvalText.includes("no_platform_write"),
      runbookCardCount: decision?.querySelectorAll(".saas-paid-launch-runbook").length || 0,
      smokeCardCount: smoke?.querySelectorAll("article").length || 0,
      edgeCardCount: edge?.querySelectorAll("article").length || 0,
      billingMatrixCardCount: billing?.querySelectorAll("article").length || 0,
      rehearsalCardCount: rehearsal?.querySelectorAll("article").length || 0,
      approvalCardCount: approval?.querySelectorAll("article").length || 0,
      laneCount: Array.from(decision?.querySelectorAll("article strong") || []).filter((node) =>
        ["billing", "domain", "reliability", "legal", "ebay", "release"].includes((node.textContent || "").trim()),
      ).length,
      hasLoginOverlay: Boolean(document.querySelector(".auth-shell, .saas-login-modal, [data-auth-view]")),
      publicBillingText: publicBillingCutover?.textContent || "",
      incidentRunbookText: incidentRunbook?.textContent || "",
      merchantBillingForbiddenVisible,
    };
  });

  const result = {
    timestamp: new Date().toISOString(),
    base,
    outDir,
    api: {
      decision_version: decision.contract_version || "",
      decision_status: decision.status || "",
      public_paid_launch_allowed: Boolean(decision.public_paid_launch_allowed),
      charge_now_allowed: Boolean(decision.charge_now_allowed),
      platform_write_now_allowed: Boolean(decision.platform_write_now_allowed),
      repeat_ebay_oauth_allowed: Boolean(decision.repeat_ebay_oauth_allowed),
      next_operator_step: (decision.next_operator_step || {}).key || "",
      lane_count: Array.isArray(decision.lanes) ? decision.lanes.length : 0,
      runbook_total_count: Number(decision.runbook_total_count || 0),
      runbook_blocked_count: Number(decision.runbook_blocked_count || 0),
      next_runbook_step: (decision.next_runbook_step || {}).key || "",
      runbook_keys: Array.isArray(decision.billing_domain_cutover_runbook)
        ? decision.billing_domain_cutover_runbook.map((item) => item && item.key).filter(Boolean)
        : [],
      new_account_smoke_total_count: Array.isArray(smokeRunbook) ? smokeRunbook.length : 0,
      new_account_smoke_keys: Array.isArray(smokeRunbook) ? smokeRunbook.map((item) => item && item.key).filter(Boolean) : [],
      billing_live_cutover_total_count: billingMatrix.length,
      billing_live_cutover_ready_count: Number((billingPlan.billing_live_cutover_summary || {}).ready_count || 0),
      billing_live_cutover_keys: billingMatrix.map((item) => item && item.key).filter(Boolean),
      billing_domain_rehearsal_version: rehearsal.contract_version || "",
      billing_domain_rehearsal_status: rehearsal.status || "",
      billing_domain_rehearsal_mode: rehearsal.mode || "",
      billing_domain_rehearsal_ready_for_owner_approval: Boolean(rehearsal.ready_for_owner_approval),
      billing_domain_rehearsal_charge_now_allowed: Boolean(rehearsal.charge_now_allowed),
      billing_domain_rehearsal_calls_stripe_api: Boolean(rehearsal.calls_stripe_api),
      billing_domain_rehearsal_creates_checkout_session: Boolean(rehearsal.creates_checkout_session),
      billing_domain_rehearsal_triggers_ebay_oauth: Boolean(rehearsal.triggers_ebay_oauth),
      billing_domain_rehearsal_public_paid_launch_allowed: Boolean(rehearsal.public_paid_launch_allowed),
      billing_domain_rehearsal_total_count: rehearsalStages.length,
      billing_domain_rehearsal_keys: rehearsalStages.map((item) => item && item.key).filter(Boolean),
      no_charge_evidence_packet_version: noChargeEvidencePacket.contract_version || "",
      no_charge_evidence_packet_status: noChargeEvidencePacket.status || "",
      no_charge_evidence_packet_mode: noChargeEvidencePacket.mode || "",
      no_charge_evidence_packet_ready_for_owner_review: Boolean(noChargeEvidencePacket.ready_for_owner_review),
      no_charge_evidence_packet_charge_now_allowed: Boolean(noChargeEvidencePacket.charge_now_allowed),
      no_charge_evidence_packet_calls_stripe_api: Boolean(noChargeEvidencePacket.calls_stripe_api),
      no_charge_evidence_packet_creates_checkout_session: Boolean(noChargeEvidencePacket.creates_checkout_session),
      no_charge_evidence_packet_triggers_ebay_oauth: Boolean(noChargeEvidencePacket.triggers_ebay_oauth),
      no_charge_evidence_packet_triggers_real_platform_write: Boolean(noChargeEvidencePacket.triggers_real_platform_write),
      no_charge_evidence_packet_frontend_gets_payment_secret: Boolean(noChargeEvidencePacket.frontend_gets_payment_secret),
      no_charge_evidence_packet_total_count: noChargeEvidenceItems.length,
      no_charge_evidence_packet_keys: noChargeEvidenceItems.map((item) => item && item.key).filter(Boolean),
      edge_cutover_contract_version: edgePreflight.contract_version || "",
      edge_cutover_status: edgePreflight.status || "",
      edge_cutover_mode: edgePreflight.mode || "",
      edge_cutover_ready_for_owner_approval: Boolean(edgePreflight.ready_for_owner_approval),
      edge_cutover_public_paid_launch_allowed: Boolean(edgePreflight.public_paid_launch_allowed),
      edge_cutover_charge_now_allowed: Boolean(edgePreflight.charge_now_allowed),
      edge_cutover_calls_stripe_api: Boolean(edgePreflight.calls_stripe_api),
      edge_cutover_creates_checkout_session: Boolean(edgePreflight.creates_checkout_session),
      edge_cutover_triggers_ebay_oauth: Boolean(edgePreflight.triggers_ebay_oauth),
      edge_cutover_triggers_real_platform_write: Boolean(edgePreflight.triggers_real_platform_write),
      edge_cutover_frontend_gets_payment_secret: Boolean(edgePreflight.frontend_gets_payment_secret),
      edge_cutover_total_count: edgeStages.length,
      edge_cutover_stage_keys: edgeStages.map((item) => item && item.key).filter(Boolean),
      paid_launch_approval_version: approvalPacket.contract_version || "",
      paid_launch_approval_status: approvalPacket.status || "",
      paid_launch_approval_mode: approvalPacket.mode || "",
      paid_launch_approval_ready_for_owner_approval: Boolean(approvalPacket.ready_for_owner_approval),
      paid_launch_approval_charge_now_allowed: Boolean(approvalPacket.charge_now_allowed),
      paid_launch_approval_calls_stripe_api: Boolean(approvalPacket.calls_stripe_api),
      paid_launch_approval_creates_checkout_session: Boolean(approvalPacket.creates_checkout_session),
      paid_launch_approval_triggers_ebay_oauth: Boolean(approvalPacket.triggers_ebay_oauth),
      paid_launch_approval_triggers_real_platform_write: Boolean(approvalPacket.triggers_real_platform_write),
      paid_launch_approval_total_count: approvalSteps.length,
      paid_launch_approval_keys: approvalSteps.map((item) => item && item.key).filter(Boolean),
      billing_provider_evidence_version: providerRegister.contract_version || "",
      billing_provider_evidence_status: providerRegister.status || "",
      billing_provider_evidence_ready_for_owner_review: Boolean(providerRegister.ready_for_owner_review),
      billing_provider_evidence_public_paid_launch_allowed: Boolean(providerRegister.public_paid_launch_allowed),
      billing_provider_evidence_charge_now_allowed: Boolean(providerRegister.charge_now_allowed),
      billing_provider_evidence_calls_stripe_api: Boolean(providerRegister.calls_stripe_api),
      billing_provider_evidence_creates_checkout_session: Boolean(providerRegister.creates_checkout_session),
      billing_provider_evidence_triggers_ebay_oauth: Boolean(providerRegister.triggers_ebay_oauth),
      billing_provider_evidence_repeat_ebay_oauth_allowed: Boolean(providerRegister.repeat_ebay_oauth_allowed),
      billing_provider_evidence_triggers_real_platform_write: Boolean(providerRegister.triggers_real_platform_write),
      billing_provider_evidence_frontend_gets_payment_secret: Boolean(providerRegister.frontend_gets_payment_secret),
      billing_provider_evidence_total_count: providerRegisterRows.length,
      billing_provider_evidence_keys: providerRegisterRows.map((item) => item && item.key).filter(Boolean),
      billing_provider_cutover_dossier_version: providerCutoverDossier.contract_version || "",
      billing_provider_cutover_dossier_status: providerCutoverDossier.status || "",
      billing_provider_cutover_dossier_decision: providerCutoverDossierSummary.decision || "",
      billing_provider_cutover_dossier_ready_for_owner_review: Boolean(providerCutoverDossier.ready_for_owner_review),
      billing_provider_cutover_dossier_public_paid_launch_allowed: Boolean(providerCutoverDossier.public_paid_launch_allowed),
      billing_provider_cutover_dossier_charge_now_allowed: Boolean(providerCutoverDossier.charge_now_allowed),
      billing_provider_cutover_dossier_calls_stripe_api: Boolean(providerCutoverDossier.calls_stripe_api),
      billing_provider_cutover_dossier_creates_checkout_session: Boolean(providerCutoverDossier.creates_checkout_session),
      billing_provider_cutover_dossier_triggers_ebay_oauth: Boolean(providerCutoverDossier.triggers_ebay_oauth),
      billing_provider_cutover_dossier_triggers_real_platform_write: Boolean(providerCutoverDossier.triggers_real_platform_write),
      billing_provider_cutover_dossier_frontend_gets_payment_secret: Boolean(providerCutoverDossier.frontend_gets_payment_secret),
      billing_provider_cutover_dossier_section_count: providerCutoverDossierSections.length,
      billing_provider_cutover_dossier_section_keys: providerCutoverDossierSections.map((item) => item && item.key).filter(Boolean),
      billing_provider_cutover_dossier_activation_count: providerCutoverDossierActivation.length,
      billing_provider_cutover_dossier_activation_keys: providerCutoverDossierActivation.map((item) => item && item.key).filter(Boolean),
      owner_launch_control_status: Number(ownerPacketResponse.status || 0),
      protected_evidence_statuses: {
        legacy_billing_domain: Number(protectedEvidence.legacyBillingDomain.status || 0),
        owner_billing_domain: Number(protectedEvidence.ownerBillingDomain.status || 0),
        legacy_edge: Number(protectedEvidence.legacyEdge.status || 0),
        owner_edge: Number(protectedEvidence.ownerEdge.status || 0),
        legacy_paid_launch: Number(protectedEvidence.legacyApproval.status || 0),
        owner_paid_launch: Number(protectedEvidence.ownerApproval.status || 0),
        legacy_billing_provider: Number(protectedEvidence.legacyProviderRegister.status || 0),
        owner_billing_provider: Number(protectedEvidence.ownerProviderRegister.status || 0),
        payment_options: Number(protectedEvidence.paymentOptions.status || 0),
      },
      secret_exposed: Boolean(launchGate.secret_exposed),
    },
    ui,
    pageErrors,
    relevantConsoleMessages,
    screenshotError,
  };
  fs.writeFileSync(path.join(outDir, "result.json"), JSON.stringify(result, null, 2));
  await browser.close();

  const failures = [];
  if (pageErrors.length) failures.push(`page errors: ${pageErrors.length}`);
  if (relevantConsoleMessages.length) failures.push(`console issues: ${relevantConsoleMessages.length}`);
  if (decision.contract_version !== "2026-06-18-paid-launch-cutover-decision") failures.push("api decision contract missing");
  if (decision.status !== "blocked") failures.push(`api decision status ${decision.status}`);
  if (decision.public_paid_launch_allowed !== false) failures.push("api public paid launch unexpectedly allowed");
  if (decision.charge_now_allowed !== false) failures.push("api charge now unexpectedly allowed");
  if (decision.platform_write_now_allowed !== false) failures.push("api platform write unexpectedly allowed");
  if (decision.repeat_ebay_oauth_allowed !== false) failures.push("api repeat oauth unexpectedly allowed");
  if ((decision.next_operator_step || {}).key !== "billing_provider_live_contract") failures.push("api next step should be billing provider contract");
  if (Number(decision.runbook_total_count || 0) !== 7) failures.push(`api runbook count ${decision.runbook_total_count}`);
  if (!Array.isArray(decision.billing_domain_cutover_runbook)) failures.push("api runbook missing");
  if (!((decision.next_runbook_step || {}).key)) failures.push("api next runbook step missing");
  if (!result.api.runbook_keys.includes("stripe_live_webhook_resilience")) failures.push("api runbook missing stripe webhook resilience");
  if (!result.api.runbook_keys.includes("stable_domain_oauth_cors_alignment")) failures.push("api runbook missing stable domain oauth/cors");
  if (result.api.new_account_smoke_total_count !== 8) failures.push(`api new-account smoke count ${result.api.new_account_smoke_total_count}`);
  for (const key of [
    "public_preflight_ready",
    "clean_new_account_declared",
    "new_account_oauth_authorization_gate",
    "official_packet_account_health_snapshot",
    "new_product_duplicate_guard",
    "publish_health_confirmation_gate",
    "controlled_real_publish_probe",
    "post_publish_cockpit_cleanup_gate",
  ]) {
    if (!result.api.new_account_smoke_keys.includes(key)) failures.push(`api new-account smoke missing ${key}`);
  }
  if (result.api.owner_launch_control_status !== 403 && !ui.ownerOpsTabVisible) failures.push(`ordinary owner launch-control status ${result.api.owner_launch_control_status}`);
  if (ui.ownerOpsTabVisible) {
    if (!ui.visible || ui.cardCount < 4) failures.push("cutover decision UI missing");
    if (!ui.hasBlockedStatus || !ui.hasNoCharge || !ui.hasNoPlatformWrite || !ui.hasRepeatOauthFalse) failures.push("cutover decision UI missing safety flags");
    if (!ui.hasBillingNextStep) failures.push("cutover decision UI missing billing next step");
    if (!ui.hasRunbook || ui.runbookCardCount < 1) failures.push("cutover decision UI missing runbook");
    if (!ui.hasWebhookResilience) failures.push("cutover decision UI missing webhook resilience");
    if (!ui.hasStableDomainOauthCors) failures.push("cutover decision UI missing stable domain oauth/cors");
    if (!ui.smokeVisible || ui.smokeCardCount < 8) failures.push("new-account smoke UI missing");
    if (!ui.hasNewAccountSmoke || !ui.hasCleanAccountStep || !ui.hasOauthGate || !ui.hasCleanupGate) failures.push("new-account smoke UI missing key stages");
  } else {
    if (
      ui.visible ||
      ui.smokeVisible ||
      ui.edgeVisible ||
      ui.billingVisible ||
      ui.rehearsalVisible ||
      ui.approvalVisible ||
      ui.publicBillingCutoverVisible ||
      ui.incidentRunbookVisible
    ) {
      failures.push("platform-internal paid launch UI exposed to ordinary merchant");
    }
    if (ui.publicBillingText.includes("paid_launch_cutover") || ui.publicBillingText.includes("cutover")) {
      failures.push("ordinary billing UI exposes internal paid-launch cutover copy");
    }
    if (ui.incidentRunbookText.includes("runbook") || ui.incidentRunbookText.includes("webhook")) {
      failures.push("ordinary billing UI exposes internal billing runbook copy");
    }
    if (ui.merchantBillingForbiddenVisible) {
      failures.push("ordinary billing UI exposes founder/internal payment strategy copy");
    }
  }
  if (ui.ownerOpsTabVisible) {
  if (result.api.billing_live_cutover_total_count !== 8) failures.push(`api billing live cutover count ${result.api.billing_live_cutover_total_count}`);
  for (const key of [
    "stripe_live_provider_selected",
    "stripe_live_price_catalog",
    "stripe_subscription_checkout_contract",
    "stripe_customer_portal_contract",
    "stripe_signed_webhook_contract",
    "stripe_api_webhook_version_alignment",
    "stripe_webhook_failure_paths",
    "stripe_entitlement_quota_lifecycle",
  ]) {
    if (!result.api.billing_live_cutover_keys.includes(key)) failures.push(`api billing live cutover missing ${key}`);
  }
  if (ui.ownerOpsTabVisible) {
    if (!ui.billingVisible || ui.billingMatrixCardCount < 8) failures.push("billing live cutover UI missing");
    if (!ui.hasBillingMatrix || !ui.hasBillingProviderStep || !ui.hasBillingWebhookStep || !ui.hasBillingQuotaLifecycle) failures.push("billing live cutover UI missing key stages");
  }
  if (result.api.billing_domain_rehearsal_version !== "2026-06-18-stripe-domain-cutover-rehearsal") failures.push("api billing domain rehearsal contract missing");
  if (result.api.billing_domain_rehearsal_status !== "blocked") failures.push(`api billing domain rehearsal status ${result.api.billing_domain_rehearsal_status}`);
  if (result.api.billing_domain_rehearsal_mode !== "dry_run_no_charge") failures.push(`api billing domain rehearsal mode ${result.api.billing_domain_rehearsal_mode}`);
  if (result.api.billing_domain_rehearsal_ready_for_owner_approval !== false) failures.push("api billing domain rehearsal unexpectedly owner-approved");
  if (result.api.billing_domain_rehearsal_charge_now_allowed !== false) failures.push("api billing domain rehearsal unexpectedly allows charge");
  if (result.api.billing_domain_rehearsal_calls_stripe_api !== false) failures.push("api billing domain rehearsal unexpectedly calls Stripe API");
  if (result.api.billing_domain_rehearsal_creates_checkout_session !== false) failures.push("api billing domain rehearsal unexpectedly creates Checkout Session");
  if (result.api.billing_domain_rehearsal_triggers_ebay_oauth !== false) failures.push("api billing domain rehearsal unexpectedly triggers eBay OAuth");
  if (result.api.billing_domain_rehearsal_public_paid_launch_allowed !== false) failures.push("api billing domain rehearsal unexpectedly allows public paid launch");
  if (result.api.billing_domain_rehearsal_total_count !== 10) failures.push(`api billing domain rehearsal stage count ${result.api.billing_domain_rehearsal_total_count}`);
  for (const key of [
    "stripe_live_provider_selected",
    "stripe_live_price_ids_verified",
    "stable_domain_dns_tls_headers",
    "stripe_checkout_return_urls_on_stable_domain",
    "stripe_customer_portal_return_url_on_stable_domain",
    "stripe_signed_webhook_on_stable_domain",
    "stripe_api_webhook_version_pinned",
    "stripe_webhook_resilience_rehearsed",
    "subscription_state_and_quota_lifecycle_rehearsed",
    "cutover_rollback_audit_packet_recorded",
  ]) {
    if (!result.api.billing_domain_rehearsal_keys.includes(key)) failures.push(`api billing domain rehearsal missing ${key}`);
  }
  if (result.api.no_charge_evidence_packet_version !== "2026-07-02-no-charge-live-domain-rehearsal-evidence-packet") failures.push("api no-charge evidence packet contract missing");
  if (result.api.no_charge_evidence_packet_status !== "blocked") failures.push(`api no-charge evidence packet status ${result.api.no_charge_evidence_packet_status}`);
  if (result.api.no_charge_evidence_packet_mode !== "read_only_no_charge_no_checkout") failures.push(`api no-charge evidence packet mode ${result.api.no_charge_evidence_packet_mode}`);
  if (result.api.no_charge_evidence_packet_ready_for_owner_review !== false) failures.push("api no-charge evidence packet unexpectedly owner-approved");
  if (result.api.no_charge_evidence_packet_charge_now_allowed !== false) failures.push("api no-charge evidence packet unexpectedly allows charge");
  if (result.api.no_charge_evidence_packet_calls_stripe_api !== false) failures.push("api no-charge evidence packet unexpectedly calls Stripe API");
  if (result.api.no_charge_evidence_packet_creates_checkout_session !== false) failures.push("api no-charge evidence packet unexpectedly creates Checkout Session");
  if (result.api.no_charge_evidence_packet_triggers_ebay_oauth !== false) failures.push("api no-charge evidence packet unexpectedly triggers eBay OAuth");
  if (result.api.no_charge_evidence_packet_triggers_real_platform_write !== false) failures.push("api no-charge evidence packet unexpectedly triggers platform write");
  if (result.api.no_charge_evidence_packet_frontend_gets_payment_secret !== false) failures.push("api no-charge evidence packet unexpectedly exposes payment secret");
  if (result.api.no_charge_evidence_packet_total_count !== 7) failures.push(`api no-charge evidence packet item count ${result.api.no_charge_evidence_packet_total_count}`);
  for (const key of [
    "checkout_return_url_smoke",
    "customer_portal_return_url_smoke",
    "signed_webhook_smoke",
    "subscription_quota_lifecycle_smoke",
    "secret_scan_and_browser_smoke",
    "rollback_audit_packet",
    "no_charge_evidence_id_recorded",
  ]) {
    if (!result.api.no_charge_evidence_packet_keys.includes(key)) failures.push(`api no-charge evidence packet missing ${key}`);
  }
  if (ui.ownerOpsTabVisible) {
    if (!ui.rehearsalVisible || ui.rehearsalCardCount < 10) failures.push("billing domain rehearsal UI missing");
    if (!ui.hasRehearsal || !ui.hasRehearsalCheckoutUrls || !ui.hasRehearsalSignedWebhook || !ui.hasRehearsalQuotaLifecycle) failures.push("billing domain rehearsal UI missing key stages");
    if (!ui.hasRehearsalNoCheckoutCreated || !ui.hasRehearsalNoStripeCall || !ui.hasRehearsalNoEbayOauth || !ui.hasRehearsalNoFrontendSecret) failures.push("billing domain rehearsal UI missing safety flags");
  }
  if (result.api.edge_cutover_contract_version !== "2026-06-18-edge-waf-origin-callback-preflight") failures.push("api edge cutover contract missing");
  if (result.api.edge_cutover_status !== "blocked") failures.push(`api edge cutover status ${result.api.edge_cutover_status}`);
  if (result.api.edge_cutover_mode !== "owner_console_preflight_no_write_no_charge") failures.push(`api edge cutover mode ${result.api.edge_cutover_mode}`);
  if (result.api.edge_cutover_ready_for_owner_approval !== false) failures.push("api edge cutover unexpectedly owner-approved");
  if (result.api.edge_cutover_public_paid_launch_allowed !== false) failures.push("api edge cutover unexpectedly allows public paid launch");
  if (result.api.edge_cutover_charge_now_allowed !== false) failures.push("api edge cutover unexpectedly allows charge");
  if (result.api.edge_cutover_calls_stripe_api !== false) failures.push("api edge cutover unexpectedly calls Stripe API");
  if (result.api.edge_cutover_creates_checkout_session !== false) failures.push("api edge cutover unexpectedly creates Checkout Session");
  if (result.api.edge_cutover_triggers_ebay_oauth !== false) failures.push("api edge cutover unexpectedly triggers eBay OAuth");
  if (result.api.edge_cutover_triggers_real_platform_write !== false) failures.push("api edge cutover unexpectedly triggers platform write");
  if (result.api.edge_cutover_frontend_gets_payment_secret !== false) failures.push("api edge cutover unexpectedly exposes payment secret");
  if (result.api.edge_cutover_total_count !== 4) failures.push(`api edge cutover stage count ${result.api.edge_cutover_total_count}`);
  for (const key of [
    "stable_domain_purchase_confirmed",
    "waf_edge_onboarded",
    "origin_direct_access_locked",
    "ebay_stripe_callbacks_on_stable_domain",
  ]) {
    if (!result.api.edge_cutover_stage_keys.includes(key)) failures.push(`api edge cutover missing ${key}`);
  }
  if (ui.ownerOpsTabVisible) {
    if (!ui.edgeVisible || ui.edgeCardCount < 7) failures.push("edge cutover UI missing");
    if (!ui.hasEdgeCutover || !ui.hasEdgeStableDomain || !ui.hasEdgeWaf || !ui.hasEdgeOriginLock || !ui.hasEdgeCallbacks) failures.push("edge cutover UI missing key stages");
    if (!ui.hasEdgeNoCharge || !ui.hasEdgeNoCheckout || !ui.hasEdgeNoStripeCall || !ui.hasEdgeNoOauth || !ui.hasEdgeNoWrite || !ui.hasEdgeNoFrontendSecret) failures.push("edge cutover UI missing safety flags");
  }
  if (result.api.paid_launch_approval_version !== "2026-06-18-paid-launch-approval-packet") failures.push("api paid launch approval contract missing");
  if (result.api.paid_launch_approval_status !== "blocked") failures.push(`api paid launch approval status ${result.api.paid_launch_approval_status}`);
  if (result.api.paid_launch_approval_mode !== "owner_approval_packet_no_charge_no_write") failures.push(`api paid launch approval mode ${result.api.paid_launch_approval_mode}`);
  if (result.api.paid_launch_approval_ready_for_owner_approval !== false) failures.push("api paid launch approval unexpectedly owner-approved");
  if (result.api.paid_launch_approval_charge_now_allowed !== false) failures.push("api paid launch approval unexpectedly allows charge");
  if (result.api.paid_launch_approval_calls_stripe_api !== false) failures.push("api paid launch approval unexpectedly calls Stripe API");
  if (result.api.paid_launch_approval_creates_checkout_session !== false) failures.push("api paid launch approval unexpectedly creates Checkout Session");
  if (result.api.paid_launch_approval_triggers_ebay_oauth !== false) failures.push("api paid launch approval unexpectedly triggers eBay OAuth");
  if (result.api.paid_launch_approval_triggers_real_platform_write !== false) failures.push("api paid launch approval unexpectedly triggers platform write");
  if (result.api.paid_launch_approval_total_count !== 4) failures.push(`api paid launch approval step count ${result.api.paid_launch_approval_total_count}`);
  for (const key of ["stable_domain_hardening", "stripe_live_cutover", "no_charge_launch_rehearsal", "new_ebay_account_low_risk_smoke"]) {
    if (!result.api.paid_launch_approval_keys.includes(key)) failures.push(`api paid launch approval missing ${key}`);
  }
  if (ui.ownerOpsTabVisible) {
    if (!ui.approvalVisible || ui.approvalCardCount < 4) failures.push("paid launch approval UI missing");
    if (!ui.hasApprovalPacket || !ui.hasApprovalStableDomain || !ui.hasApprovalStripeCutover || !ui.hasApprovalNoChargeRehearsal || !ui.hasApprovalNewEbaySmoke) failures.push("paid launch approval UI missing key stages");
    if (!ui.hasApprovalExternalConfig || !ui.hasApprovalNoCharge || !ui.hasApprovalNoStripeCall || !ui.hasApprovalNoOauth || !ui.hasApprovalNoWrite) failures.push("paid launch approval UI missing safety flags");
    if (ui.laneCount !== 6) failures.push(`cutover decision lane count ${ui.laneCount}`);
  }
  if (result.api.billing_provider_evidence_version !== "2026-07-02-live-billing-provider-evidence-register") failures.push("api billing provider evidence register contract missing");
  if (result.api.billing_provider_evidence_status !== "blocked") failures.push(`api billing provider evidence register status ${result.api.billing_provider_evidence_status}`);
  if (result.api.billing_provider_evidence_ready_for_owner_review !== false) failures.push("api billing provider evidence register unexpectedly ready for owner review");
  if (result.api.billing_provider_evidence_public_paid_launch_allowed !== false) failures.push("api billing provider evidence register unexpectedly allows public paid launch");
  if (result.api.billing_provider_evidence_charge_now_allowed !== false) failures.push("api billing provider evidence register unexpectedly allows charge");
  if (result.api.billing_provider_evidence_calls_stripe_api !== false) failures.push("api billing provider evidence register unexpectedly calls Stripe API");
  if (result.api.billing_provider_evidence_creates_checkout_session !== false) failures.push("api billing provider evidence register unexpectedly creates Checkout Session");
  if (result.api.billing_provider_evidence_triggers_ebay_oauth !== false) failures.push("api billing provider evidence register unexpectedly triggers eBay OAuth");
  if (result.api.billing_provider_evidence_repeat_ebay_oauth_allowed !== false) failures.push("api billing provider evidence register unexpectedly allows repeated eBay OAuth");
  if (result.api.billing_provider_evidence_triggers_real_platform_write !== false) failures.push("api billing provider evidence register unexpectedly triggers platform write");
  if (result.api.billing_provider_evidence_frontend_gets_payment_secret !== false) failures.push("api billing provider evidence register unexpectedly exposes payment secret");
  if (result.api.billing_provider_evidence_total_count !== 15) failures.push(`api billing provider evidence row count ${result.api.billing_provider_evidence_total_count}`);
  for (const key of [
    "live_provider_account",
    "stripe_account_activation_go_live_evidence",
    "stripe_live_price_catalog",
    "stripe_live_mode_test_object_isolation",
    "stripe_subscription_checkout_contract",
    "stripe_customer_portal_contract",
    "stripe_signed_webhook_contract",
    "stripe_api_webhook_version_alignment",
    "stripe_webhook_failure_paths",
    "stripe_entitlement_quota_lifecycle",
    "merchant_billing_state_machine_proof",
    "stripe_tax_invoice_receipt_branding_evidence",
    "stable_domain_billing_callbacks",
    "no_charge_live_domain_rehearsal_packet",
    "cutover_rollback_audit_packet",
  ]) {
    if (!result.api.billing_provider_evidence_keys.includes(key)) failures.push(`api billing provider evidence register missing ${key}`);
  }
  if (result.api.billing_provider_cutover_dossier_version !== "2026-07-02-live-billing-provider-cutover-dossier-v1") failures.push("api billing provider cutover dossier contract missing");
  if (result.api.billing_provider_cutover_dossier_status !== "blocked") failures.push(`api billing provider cutover dossier status ${result.api.billing_provider_cutover_dossier_status}`);
  if (result.api.billing_provider_cutover_dossier_decision !== "keep_public_paid_launch_blocked") failures.push(`api billing provider cutover dossier decision ${result.api.billing_provider_cutover_dossier_decision}`);
  if (result.api.billing_provider_cutover_dossier_ready_for_owner_review !== false) failures.push("api billing provider cutover dossier unexpectedly ready for owner review");
  if (result.api.billing_provider_cutover_dossier_public_paid_launch_allowed !== false) failures.push("api billing provider cutover dossier unexpectedly allows paid launch");
  if (result.api.billing_provider_cutover_dossier_charge_now_allowed !== false) failures.push("api billing provider cutover dossier unexpectedly allows charge");
  if (result.api.billing_provider_cutover_dossier_calls_stripe_api !== false) failures.push("api billing provider cutover dossier unexpectedly calls Stripe API");
  if (result.api.billing_provider_cutover_dossier_creates_checkout_session !== false) failures.push("api billing provider cutover dossier unexpectedly creates Checkout Session");
  if (result.api.billing_provider_cutover_dossier_triggers_ebay_oauth !== false) failures.push("api billing provider cutover dossier unexpectedly triggers eBay OAuth");
  if (result.api.billing_provider_cutover_dossier_triggers_real_platform_write !== false) failures.push("api billing provider cutover dossier unexpectedly triggers platform write");
  if (result.api.billing_provider_cutover_dossier_frontend_gets_payment_secret !== false) failures.push("api billing provider cutover dossier unexpectedly exposes payment secret");
  if (result.api.billing_provider_cutover_dossier_section_count !== 8) failures.push(`api billing provider cutover dossier section count ${result.api.billing_provider_cutover_dossier_section_count}`);
  for (const key of [
    "provider_account_and_live_mode",
    "product_price_catalog",
    "checkout_portal_contracts",
    "signed_webhook_version_and_failures",
    "entitlement_quota_and_portal_lifecycle",
    "billing_ops_customer_trust",
    "no_charge_rehearsal_and_rollback",
    "owner_approval_hold",
  ]) {
    if (!result.api.billing_provider_cutover_dossier_section_keys.includes(key)) failures.push(`api billing provider cutover dossier missing section ${key}`);
  }
  if (result.api.billing_provider_cutover_dossier_activation_count !== 6) failures.push(`api billing provider cutover dossier activation count ${result.api.billing_provider_cutover_dossier_activation_count}`);
  for (const key of [
    "freeze_current_private_beta_boundary",
    "verify_live_catalog_and_callbacks",
    "prove_signed_webhook_lifecycle",
    "review_customer_billing_trust",
    "run_no_charge_rehearsal_and_rollback",
    "record_owner_approval_hold",
  ]) {
    if (!result.api.billing_provider_cutover_dossier_activation_keys.includes(key)) failures.push(`api billing provider cutover dossier missing activation ${key}`);
  }
  } else {
    if (result.api.billing_live_cutover_total_count !== 0) failures.push("ordinary billing plan exposes internal live cutover matrix");
    for (const [key, status] of Object.entries(result.api.protected_evidence_statuses || {})) {
      if (status !== 403) failures.push(`ordinary merchant protected evidence ${key} status ${status}`);
    }
  }
  if (ui.hasLoginOverlay) failures.push("login overlay visible during authenticated smoke");

  if (failures.length) {
    console.error(JSON.stringify({ ok: false, failures, result }, null, 2));
    process.exit(1);
  }
  console.log(JSON.stringify({ ok: true, outDir, api: result.api, ui: { ...ui, text: ui.text.slice(0, 300) } }, null, 2));
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});

function isIgnorableConsoleMessage(text) {
  const rendered = String(text || "");
  return (
    /was preloaded using link preload but not used/i.test(rendered) ||
    /owner launch control is platform-internal admin only/i.test(rendered) ||
    /Failed to load resource: the server responded with a status of 403/i.test(rendered) ||
    /Failed to load resource: net::ERR_CONNECTION_CLOSED/i.test(rendered) ||
    /Failed to load resource: net::ERR_TIMED_OUT/i.test(rendered)
  );
}
