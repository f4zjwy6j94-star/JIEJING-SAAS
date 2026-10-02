"use strict";
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
function fixture() {
  const context = vm.createContext({
    state: { saasConfirmations: [] },
    identity: { key: "project-A", source_report_id: "report-A", candidate_id: "candidate-A" },
    store: { store_id: "store-A" },
    sku: "SKU-A",
    saasCurrentListingProjectIdentity() { return this.identity; },
  });
  vm.runInContext(`
    const activeSaasStore = () => store;
    const saasCurrentListingProjectIdentity = () => identity;
    const saasListingDraftAuthoritativeSku = () => sku;
    const saasCurrentUnpublishedDraftReceipt = () => null;
    const saasNormalizeListingProjectIdentity = value => value || null;
    ${extract("saasConfirmationMatchesActiveListingContext")}
    ${extract("saasListingConfirmationsForCurrentProject")}
  `, context);
  return context;
}
function card(id, overrides = {}) {
  return { confirmation_id: id, store_id: "store-A", action_type: "publish_listing", status: "pending",
    item: { listing_project_identity: { key: "project-A", source_report_id: "report-A", candidate_id: "candidate-A" } }, ...overrides };
}
function ids(context, cards) {
  context.state.saasConfirmations = cards;
  return Array.from(vm.runInContext("saasListingConfirmationsForCurrentProject()", context), row => row.confirmation_id);
}
test("current product excludes other projects, stores, actions and unbound confirmations", () => {
  const ctx = fixture();
  assert.deepEqual(ids(ctx, [card("current"), card("save", { action_type: "save_ebay_listing_draft" }),
    card("foreign-project", { item: { listing_project_identity: { key: "project-B" }, sku: "SKU-A" } }),
    card("foreign-candidate", { item: { listing_project_identity: { key: "project-A", source_report_id: "report-A", candidate_id: "other" }, sku: "SKU-A" } }),
    card("foreign-store", { store_id: "store-B" }), card("unknown-store", { store_id: "" }),
    card("refund", { action_type: "refund_order" }), card("unbound", { item: {} })]), ["current", "save"]);
});
test("legacy same-product SKU works but empty product context never selects all account history", () => {
  const ctx = fixture();
  assert.deepEqual(ids(ctx, [card("legacy", { item: { sku: "SKU-A" } })]), ["legacy"]);
  ctx.identity = {}; ctx.sku = "";
  assert.deepEqual(ids(ctx, [card("unrelated")]), []);
});
test("display filtering does not remove records from account confirmation center", () => {
  const ctx = fixture();
  const cards = [card("current"), card("old", { store_id: "store-B" })];
  ids(ctx, cards);
  assert.equal(ctx.state.saasConfirmations.length, 2);
});
test("the rendered next-action panel cannot advertise another product's confirmation or receipt", () => {
  const ctx = fixture();
  ctx.escapeHtml = value => String(value ?? "");
  ctx.saasListingDraftPreflightSummary = () => ({ red: 0, checks: [], readyForConfirmation: true, headline: "Current product" });
  ctx.saasListingEbayFieldCoverage = () => ({ score: 100, missingQuestions: [] });
  ctx.saasExecutionResultForConfirmation = () => { throw new Error("foreign receipt must never be requested"); };
  ctx.draft = { product: "Current tablet stand" };
  ctx.state.saasConfirmations = [card("old", { item: { listing_project_identity: { key: "project-B" } } })];
  vm.runInContext(extract("renderSaasListingNextActionPanel"), ctx);
  let html = vm.runInContext("renderSaasListingNextActionPanel(draft, {}, state.saasConfirmations)", ctx);
  assert.match(html, /可生成确认单/);
  assert.doesNotMatch(html, /个待确认操作|已回填发布结果|is-open-confirm/);
  ctx.state.saasConfirmations.push(card("save", { action_type: "save_ebay_listing_draft" }));
  html = vm.runInContext("renderSaasListingNextActionPanel(draft, {}, state.saasConfirmations)", ctx);
  assert.match(html, /本商品 1 个待确认操作/);
  assert.match(html, /data-saas-action="open-confirm"\s*>打开确认中心/);
});
test("all three single-product panels avoid unscoped fallback confirmations", () => {
  for (const name of ["renderSaasListingNextActionPanel", "renderSaasListingPublishFeedbackPanel", "renderSaasListingVisiblePublishBridge"]) {
    assert.doesNotMatch(extract(name), /saasLatestPublishConfirmation\(\)\s*\|\|\s*pendingConfirmations/);
  }
  assert.doesNotMatch(source, /saasLatestPublishConfirmation\(\)\s*\|\|\s*pendingConfirmations/);
  assert.match(extract("renderSaasProductListingCenter"), /saasListingConfirmationsForCurrentProject\(\)\.filter/);
});

function preflightFixture() {
  const ctx = fixture();
  Object.assign(ctx, {
    saasPreTestFormSummary: () => ({ hasProduct: true, hasTitle: true, hasSku: true, hasPrice: true,
      hasCategory: true, hasSpecifics: true, hasImage: true, hasLocation: true, hasProfit: true }),
    saasAccountHealthSnapshot: () => ({ can_execute_real_writes: true, incident_mode: false }),
    saasAccountHealthTone: () => "green", latestSaasReportByTypes: () => null,
    saasMerchantWorkbenchContext: () => ({ hasPacket: true }), escapeHtml: value => String(value ?? ""),
    renderSaasPublishConfirmationEvidencePanel: () => "", renderSaasBackendPublishPreflightPanel: () => "",
  });
  ctx.state.saasListingComposerDraft = { merchant_product_fact_packet: { simulation_only: false } };
  vm.runInContext([
    "saasLatestExecutionResult", "saasExecutionResultForConfirmation", "saasPreTestCheckRows",
    "saasPublishHealthSummary", "renderSaasPreTestCheckGrid", "renderSaasPublishHealthReportPanel",
    ...(source.includes("function saasListingPublishCheckContext(") ? ["saasListingPublishCheckContext"] : []),
  ].map(extract).join("\n"), ctx);
  return ctx;
}

test("local preflight and source badges cannot borrow a different product's confirmations, execution or readiness", () => {
  const ctx = preflightFixture();
  ctx.state.saasConfirmations = [card("old", { item: { listing_project_identity: { key: "project-B" } } })];
  ctx.state.saasExecutionResults = [{ confirmation_id: "old", action_type: "publish_listing", status: "published_to_ebay" }];
  ctx.state.saasLastPublishReadiness = { checks: [{ key: "old-check", blocking: false }] };
  ctx.state.saasPreflightResults = [{ listing_project_key: "project-B", status: "ready" }];
  const rows = vm.runInContext("saasPreTestCheckRows()", ctx);
  assert.equal(rows.find(row => row.label.startsWith("10 ")).status, "等待发布确认单");
  assert.equal(rows.find(row => row.label.startsWith("11 ")).tone, "amber");
  const html = vm.runInContext("renderSaasPublishHealthReportPanel()", ctx);
  assert.doesNotMatch(html, /已有确认单|已有执行结果|1\/1 已通过/);
  assert.equal(ctx.state.saasConfirmations.length, 1, "display filtering never deletes history");
});

test("only a current-product successful publication gets a green result; failures remain reviewable", () => {
  const ctx = preflightFixture();
  ctx.state.saasConfirmations = [card("current")];
  ctx.state.saasExecutionResults = [{ confirmation_id: "current", action_type: "publish_listing", status: "failed" }];
  let rows = vm.runInContext("saasPreTestCheckRows()", ctx);
  assert.equal(rows.find(row => row.label.startsWith("10 ")).tone, "green");
  assert.equal(rows.find(row => row.label.startsWith("11 ")).tone, "amber");
  assert.match(rows.find(row => row.label.startsWith("11 ")).status, /未完成发布/);
  ctx.state.saasExecutionResults[0].status = "published_to_ebay";
  rows = vm.runInContext("saasPreTestCheckRows()", ctx);
  assert.equal(rows.find(row => row.label.startsWith("11 ")).tone, "green");
});

test("simulation local check explicitly blocks eBay even with complete form fields", () => {
  const ctx = preflightFixture();
  ctx.state.saasListingComposerDraft.merchant_product_fact_packet.simulation_only = true;
  const rows = vm.runInContext("saasPreTestCheckRows()", ctx);
  assert.ok(rows.some(row => row.tone === "red" && /模拟/.test(row.status)));
});

test("both confirmation buttons explain simulation locally without a request or model action", async () => {
  const ctx = preflightFixture();
  ctx.messages = [];
  ctx.state.saasListingComposerDraft = { model_generated: true, merchant_product_fact_packet: { simulation_only: true } };
  ctx.requireSaasProtectedSessionForAction = () => true;
  ctx.showActionToast = message => ctx.messages.push(message);
  ctx.readSaasPublishIntakeForm = () => { throw new Error("simulation must stop before the publish request"); };
  vm.runInContext(`async ${extract("createSaasPublishConfirmationFromIntakeForm")}`, ctx);
  for (const mode of ["publish", "ebay-draft"]) {
    ctx.mode = mode;
    assert.equal(await vm.runInContext("createSaasPublishConfirmationFromIntakeForm(mode)", ctx), false);
    assert.match(ctx.messages.at(-1), /模拟演练.*不能.*eBay/);
  }
});
