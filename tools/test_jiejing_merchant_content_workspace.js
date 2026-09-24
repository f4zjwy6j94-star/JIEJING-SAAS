"use strict";
// Real renderers with synthetic state; never connects to an account or provider.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const test = require("node:test");
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
  ctx.saasEbayPacketResourceRows = () => [{label:"订单履约",status:"present",summary:"official_api"},{label:"库存",status:"gap",summary:"<script>bad</script>"}];
  vm.runInContext(extract("renderSaasSettingsDataPanel"), ctx);
  const html = vm.runInContext("renderSaasSettingsDataPanel(ctx)", ctx);
  assert.match(html, /1\/2 已读取|1 类/);
  assert.match(html, /eBay 官方来源|待读取/);
  assert.doesNotMatch(html, /official_api|<script>bad<\/script>|>gap</);
  assert.match(html, /不代表实时状态/);
});
