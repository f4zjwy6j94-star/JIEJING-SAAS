"use strict";
// Real renderers with synthetic state; never connects to an account or provider.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const test = require("node:test");
const os = require("node:os");
const { spawn } = require("node:child_process");
const { withOwnedBrowser, startOwnedBackend, stopOwnedBackend } = require("./codex_jiejing_merchant_project_status_browser_smoke");

test("browser smoke owned backend releases its temporary directory before stop resolves", async () => {
  const owned = await startOwnedBackend();
  try {
    await stopOwnedBackend(owned);
    assert.equal(fs.existsSync(owned.tempRoot), false);
    await assert.rejects(fetch(`${owned.backendBase}/health`, { signal: AbortSignal.timeout(1500) }));
  } finally {
    if (owned.child.exitCode === null && owned.child.signalCode === null) owned.child.kill();
  }
});

async function holdWindowsFile(filePath, durationMs) {
  const began = Date.now();
  const lifecycle = { events: [], stderr: "" };
  const child = spawn("powershell.exe", ["-NoProfile", "-Command",
    "$stream = [IO.File]::Open($env:JIEJING_TEST_LOCK_PATH, 'Open', 'Read', 'None'); " +
    "[Console]::WriteLine('locked'); [Console]::Out.Flush(); " +
    `try { Start-Sleep -Milliseconds ${durationMs} } finally { $stream.Dispose() }; ` +
    "[Console]::WriteLine('released'); [Console]::Out.Flush()"], {
    env: { ...process.env, JIEJING_TEST_LOCK_PATH: filePath }, windowsHide: true, stdio: ["ignore", "pipe", "pipe"],
  });
  child.fixtureLifecycle = lifecycle;
  child.fixtureExited = new Promise(resolve => child.once("exit", (code, signal) => {
    lifecycle.events.push({ event: "exit", ms: Date.now() - began, code, signal });
    resolve();
  }));
  child.stderr.on("data", data => { lifecycle.stderr = (lifecycle.stderr + String(data)).slice(-2048); });
  let stdout = "";
  let ready = false;
  await new Promise((resolve, reject) => {
    const timer = setTimeout(() => { child.kill(); reject(new Error("file lock fixture did not start")); }, 5000);
    child.stdout.on("data", data => {
      stdout += String(data);
      let newline;
      while ((newline = stdout.indexOf("\n")) >= 0) {
        const line = stdout.slice(0, newline).trim();
        stdout = stdout.slice(newline + 1);
        if (line === "locked" || line === "released") {
          lifecycle.events.push({ event: line, ms: Date.now() - began });
        }
        if (line === "locked" && !ready) {
          ready = true;
          clearTimeout(timer);
          resolve();
        }
      }
    });
    child.once("error", error => { clearTimeout(timer); reject(error); });
    child.once("exit", () => {
      clearTimeout(timer);
      if (!ready) reject(new Error(`file lock fixture exited before ready: ${JSON.stringify(lifecycle)}`));
    });
  });
  return child;
}

test("browser smoke cleanup waits for a briefly locked Windows fixture file", { skip: process.platform !== "win32" }, async () => {
  const tempParent = path.resolve(os.tmpdir());
  const tempRoot = fs.mkdtempSync(path.join(tempParent, "jiejing-project-status-smoke-"));
  const filePath = path.join(tempRoot, "transient-lock.txt");
  fs.writeFileSync(filePath, "isolated file lock fixture");
  const lock = await holdWindowsFile(filePath, 350);
  try {
    await stopOwnedBackend({ child: { exitCode: 0 }, tempRoot, tempParent });
    assert.equal(fs.existsSync(tempRoot), false);
  } catch (error) {
    error.message += `; synthetic lock lifecycle: ${JSON.stringify(lock.fixtureLifecycle)}`;
    throw error;
  } finally {
    if (lock.exitCode === null && lock.signalCode === null) lock.kill();
    await lock.fixtureExited;
  }
});

test("browser smoke cleanup rejects a persistently locked Windows fixture file", { skip: process.platform !== "win32" }, async () => {
  const tempParent = path.resolve(os.tmpdir());
  const tempRoot = fs.mkdtempSync(path.join(tempParent, "jiejing-project-status-smoke-"));
  const filePath = path.join(tempRoot, "persistent-lock.txt");
  fs.writeFileSync(filePath, "isolated persistent file lock fixture");
  const lock = await holdWindowsFile(filePath, 30000);
  try {
    await assert.rejects(stopOwnedBackend({ child: { exitCode: 0 }, tempRoot, tempParent }),
      error => ["EPERM", "EBUSY"].includes(error.code));
    assert.equal(fs.existsSync(filePath), true);
  } finally {
    if (lock.exitCode === null && lock.signalCode === null) {
      const exited = new Promise(resolve => lock.once("exit", resolve));
      lock.kill();
      await exited;
    }
    await fs.promises.rm(tempRoot, { recursive: true, force: true, maxRetries: 6, retryDelay: 100 });
  }
});

test("browser smoke cleanup leaves a directory outside its owned prefix untouched", async () => {
  const tempParent = path.resolve(os.tmpdir());
  const tempRoot = fs.mkdtempSync(path.join(tempParent, "jiejing-cleanup-scope-"));
  const filePath = path.join(tempRoot, "must-remain.txt");
  fs.writeFileSync(filePath, "unrelated fixture");
  try {
    await stopOwnedBackend({ child: { exitCode: 0 }, tempRoot, tempParent });
    assert.equal(fs.readFileSync(filePath, "utf8"), "unrelated fixture");
  } finally {
    fs.rmSync(tempRoot, { recursive: true, force: true });
  }
});

test("browser smoke cleanup preserves unrelated filesystem errors", async (context) => {
  const failure = Object.assign(new Error("isolated filesystem failure"), { code: "EIO" });
  const tempParent = path.resolve(os.tmpdir());
  context.mock.method(fs.promises, "rm", async () => { throw failure; });
  await assert.rejects(stopOwnedBackend({
    child: { exitCode: 0 }, tempParent,
    tempRoot: path.join(tempParent, "jiejing-project-status-smoke-error-fixture"),
  }), error => error === failure);
});

test("browser smoke closes its owned browser when an assertion fails", async () => {
  const failure = new Error("expected isolated assertion failure");
  let closes = 0;
  const owned = { close: async () => { closes += 1; } };
  await assert.rejects(withOwnedBrowser(async () => { throw failure; }, async () => owned), (error) => error === failure);
  assert.equal(closes, 1);
});

test("browser smoke closes its owned browser on success", async () => {
  let closes = 0;
  const owned = { close: async () => { closes += 1; } };
  assert.equal(await withOwnedBrowser(async (browser) => browser === owned, async () => owned), true);
  assert.equal(closes, 1);
});
const source = fs.readFileSync(path.join(__dirname, "../app.js"), "utf8");
function extract(name) {
  const start = source.indexOf(`function ${name}(`);
  assert.ok(start >= 0, `${name} exists`);
  const tail = source.slice(start);
  const end = tail.search(/\n(?:async )?function /);
  return end < 0 ? tail : tail.slice(0, end);
}
function fixture(cards = []) {
  const view = { innerHTML: "" };
  const context = {
    state: { saasConfirmations: cards, saasExecutionResults: [] },
    view,
    ctx: { connection: {}, presentKeys: [], packetBody: {}, lastSync: "2026-08-28T02:20:00Z" },
    saasMerchantWorkbenchContext() { return context.ctx; },
    saasConfirmationsForDisplay: rows => rows.filter(row => row.inScope !== false),
    saasEbayOperationsSnapshot: () => ({ orderCount: 0, listingCount: 0 }),
    publicRuntimeText: value => String(value ?? ""),
    escapeHtml: value => String(value ?? "").replace(/[&<>"']/g, ch => ({"&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;"}[ch])),
    saasCompactValue: value => String(value ?? ""),
    saasTimestampLabel: () => "08/28 10:20",
    renderSaasModuleAiGoalStrip: () => "",
    jiejingTrustedTemplate: () => (strings, ...values) => strings.reduce((text, part, i) => text + part + (values[i] ?? ""), ""),
    fetch: () => { throw new Error("No network allowed in content tests"); },
  };
  vm.createContext(context);
  for (const name of ["saasPendingServiceConfirmations", "saasServiceTraceStateLabel", "saasServiceTraceRecords", "renderSaasServiceTrace", "renderSaasServiceCenter"]) {
    if (source.includes(`function ${name}(`)) vm.runInContext(extract(name), context);
  }
  return context;
}
function service(context) {
  vm.runInContext("renderSaasServiceCenter(view)", context);
  return context.view.innerHTML;
}
test("service does not count historical, out-of-scope or prose-matched cards as pending", () => {
  const ctx = fixture([
    { confirmation_id: "approved", status: "approved", action_type: "send_customer_reply" },
    { confirmation_id: "foreign", status: "pending", action_type: "refund", inScope: false },
    { confirmation_id: "listing", status: "pending", action_type: "publish_listing", title: "Shipping address and return policy" },
    { confirmation_id: "cancelled", status: "cancelled", action_type: "buyer_message_send" },
  ]);
  const html = service(ctx);
  assert.match(html, /<span>确认事项<\/span>\s*<strong>0<\/strong>/);
  assert.doesNotMatch(html, /处理需要确认的回复/);
});
test("service pending count and link use the same current display scope", () => {
  const ctx = fixture([
    { confirmation_id: "reply", status: "pending", action_type: "sensitive_customer_reply" },
    { confirmation_id: "refund", status: "pending", action_type: "partial_refund" },
    { confirmation_id: "policy", status: "pending", action_type: "change_shipping_policy" },
  ]);
  const html = service(ctx);
  assert.match(html, /<span>确认事项<\/span>\s*<strong>2<\/strong>/);
  assert.match(html, /data-global-flow-view="confirm">查看 2 项待确认/);
  assert.equal(ctx.state.saasConfirmations.length, 3, "display filtering must not delete history");
});
test("orders are dated snapshots, not pending messages or automatic replies", () => {
  const ctx = fixture();
  ctx.ctx.presentKeys = ["orders_and_fulfillment", "inventory_and_offers"];
  ctx.saasEbayOperationsSnapshot = () => ({ orderCount: 2, listingCount: 1, orderLabel: "2 笔订单", fulfillment: "部分已完成" });
  const html = service(ctx);
  assert.match(html, /最近同步：08\/28 10:20/);
  assert.match(html, /买家消息暂未接入/);
  assert.doesNotMatch(html, /2.*待回复|当前没有待处理订单|查看需要确认的回复/);
  assert.match(html, /data-global-flow-view="cockpit">前往 AI CEO 起草回复/);
});
test("service trace keeps draft, sent and simulated records separate and escaped", () => {
  const ctx = fixture([{ confirmation_id: "draft", status: "pending", action_type: "buyer_message_send", title: "<img src=x>", item: { reply_text: "<script>bad</script>" } }]);
  ctx.state.saasExecutionResults = [
    { execution_id: "sim", action_type: "buyer_message_send", status: "simulated_no_platform_write" },
    { execution_id: "sent", action_type: "buyer_message_send", status: "completed", result: { platform_result: { message_sent: true } } },
    { execution_id: "not-sent", action_type: "buyer_message_send", status: "completed", result: {} },
  ];
  const html = service(ctx);
  assert.match(html, /data-service-trace-state="ai_suggested"/);
  assert.match(html, /data-service-trace-state="simulated"/);
  assert.match(html, /data-service-trace-state="sent"/);
  assert.doesNotMatch(html, /data-service-trace-id="not-sent"|<img src=x>|<script>bad/);
});
test("confirmation center avoids duplicate guidance and distinguishes approval from execution", () => {
  const body = extract("renderSaasConfirmPanel");
  assert.doesNotMatch(body, /受控交接|其他记录和复盘放在设置里|只记录安全交接/);
  assert.match(body, /批准不代表已执行/);
  assert.match(body, /status === "pending" \? `<div class="saas-confirm-card-decision">/);
  assert.match(body, /data-global-flow-view="product">继续处理商品/);
  for (const action of ["approve-confirmation", "revise-confirmation", "recover-publish"]) assert.ok(body.includes(action));
});
test("service and account confirmations do not inherit the active product title", () => {
  const ctx = fixture();
  ctx.isSaasDomesticBillingRefundConfirmation = () => false;
  ctx.saasProductLabelForConfirmation = () => "Listing product from task";
  vm.runInContext(extract("saasConfirmationCardProductLabel"), ctx);
  for (const action of ["sensitive_customer_reply", "refund", "ebay_oauth_scope_change"]) {
    ctx.card = {action_type:action};
    assert.equal(vm.runInContext('saasConfirmationCardProductLabel(card, "Active tablet stand")', ctx), "");
  }
  ctx.card = {action_type:"sensitive_customer_reply",item:{product:"Explicit product"}};
  assert.equal(vm.runInContext("saasConfirmationCardProductLabel(card)", ctx), "Explicit product");
  ctx.card = {action_type:"publish_listing"};
  assert.equal(vm.runInContext("saasConfirmationCardProductLabel(card)", ctx), "Listing product from task");
});
test("customer confirmation shows the exact reply draft and target, never interpolates HTML", () => {
  const ctx = fixture();
  vm.runInContext(extract("renderSaasConfirmationReplyPreview"), ctx);
  ctx.card = {action_type:"sensitive_customer_reply",item:{message_draft:"Exact <img> draft",reply_text:"Old draft",order_id:"ORDER-1"}};
  const html = vm.runInContext("renderSaasConfirmationReplyPreview(card)", ctx);
  assert.match(html, /Exact &lt;img&gt; draft/);
  assert.match(html, /关联订单：ORDER-1/);
  assert.doesNotMatch(html, /Old draft|<img>/);
  ctx.card = {action_type:"send_customer_reply",item:{}};
  assert.match(vm.runInContext("renderSaasConfirmationReplyPreview(card)", ctx), /尚未提供回复正文/);
  ctx.card = {action_type:"publish_listing",item:{message_draft:"not customer service"}};
  assert.equal(vm.runInContext("renderSaasConfirmationReplyPreview(card)", ctx), "");
});
test("Settings puts actions before optional pricing explanation and preserves all panels", () => {
  const body = extract("saasSettingsTabDefinitions");
  const billing = body.slice(body.indexOf('id: "billing"'));
  assert.ok(billing.indexOf("renderSaasMerchantDomesticPaymentPanel(ctx)") < billing.indexOf("renderSaasMerchantBillingPlainSummaryPanel(ctx)"));
  assert.match(billing, /title: "费用与额度说明"/);
  for (const panel of ["renderSaasMerchantMediaCreditsPanel", "renderSaasMerchantBillingEntitlementPathPanel", "renderSaasMerchantSecurityBoundaryPanel"]) assert.ok(billing.includes(panel));
  const payment = extract("renderSaasMerchantDomesticPaymentPanel");
  assert.doesNotMatch(payment, /当前套餐有效期以订阅状态为准/);
  assert.match(payment, /到期时间暂未提供/);
});
test("store-data copy translates statuses without treating source coverage as publish readiness", () => {
  const ctx = fixture();
  ctx.state.saasConnected = true;
  Object.assign(ctx.ctx, {hasPacket:true,presentCount:1,coverageTotal:2,missingKeys:["inventory_and_offers"],sourceLabel:"eBay 官方来源"});
  ctx.isSaasAuthorizedConnectionStatus = () => true;
  ctx.saasEbayResourceLabel = () => "Listing / 库存";
  ctx.saasAccountHealthSnapshot = () => ({});
  ctx.saasEbayPacketResourceRows = () => [{label:"订单履约",status:"present",summary:"official_api"},{label:"库存",status:"gap",summary:"<script>bad</script>"}];
  vm.runInContext(extract("saasSettingsDataSnapshotView"), ctx);
  vm.runInContext(extract("renderSaasSettingsDataPanel"), ctx);
  const html = vm.runInContext("renderSaasSettingsDataPanel(ctx)", ctx);
  assert.match(html, /1\/2 类已保存/);
  assert.match(html, /eBay 官方来源 · 截至最后同步/);
  assert.doesNotMatch(html, /official_api|<script>bad<\/script>|>gap</);
  assert.match(html, /不能据此判断当前状态/);
  assert.match(html, /已保存资料不代表账号可用/);
  ctx.ctx.store = { store_id: "restricted-store" };
  ctx.saasAccountHealthSnapshot = () => ({ store_id: "restricted-store", status: "restricted", incident_mode: true });
  const restricted = vm.runInContext("renderSaasSettingsDataPanel(ctx)", ctx);
  assert.match(restricted, /账号受限/);
  assert.match(restricted, /真实发布已暂停/);
  assert.doesNotMatch(restricted, /最近核验未见限制/);
});
