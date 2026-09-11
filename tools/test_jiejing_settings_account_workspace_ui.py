#!/usr/bin/env python3
"""Focused, offline regression for the merchant account/store settings workspace."""

from __future__ import annotations

import json
import re
import subprocess
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def function_source(source: str, name: str) -> str:
    match = re.search(rf"(?m)^(?:async )?function {re.escape(name)}\(", source)
    if not match:
        raise AssertionError(f"missing account workspace function: {name}")
    following = re.search(r"(?m)^(?:(?:async )?function \w+\(|(?:const|let|class) )", source[match.end() :])
    end = match.end() + following.start() if following else len(source)
    return source[match.start() : end]


class Markup(HTMLParser):
    def __init__(self, source: str) -> None:
        super().__init__()
        self.elements: list[tuple[str, dict[str, str | None], int]] = []
        self.details_depth = 0
        self.feed(source)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.elements.append((tag, dict(attrs), self.details_depth))
        if tag == "details":
            self.details_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag == "details":
            self.details_depth -= 1

    def with_attr(self, name: str, value: str | None = None) -> list[tuple[str, dict[str, str | None], int]]:
        return [item for item in self.elements if name in item[1] and (value is None or item[1][name] == value)]


RUNTIME_FIXTURE = r"""
const assert = require('node:assert/strict');
const state = {};
let ctx;
let readOnlyConfirmation = null;
let draftConfirmation = null;
let selectedElement = null;
const saasSettingsAccountDisclosureSnapshots = new WeakMap();
const saasBrowserSessionButtonBindings = new WeakMap();
const document = { querySelector: selector => selector === '#storeSwitch' ? selectedElement : null };
const window = {};
const forbidSideEffect = () => { throw new Error('settings renderer must not call network/storage'); };
Object.defineProperty(document, 'cookie', { get: forbidSideEffect, set: forbidSideEffect });
globalThis.fetch = forbidSideEffect;
globalThis.localStorage = { getItem: forbidSideEffect, setItem: forbidSideEffect, removeItem: forbidSideEffect };
globalThis.sessionStorage = globalThis.localStorage;
function saasFetch() { return forbidSideEffect(); }
function escapeHtml(value) { return String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[ch])); }
function publicRuntimeText(value) { return String(value ?? ''); }
function activeSaasStore() { return ctx.store; }
function saasMerchantWorkbenchContext() { return ctx; }
function currentKnownSaasAccountRecord() { return null; }
function saasConnectionForStore(store) { return state.saasConnections.find(item => item.store_id === store?.store_id) || null; }
function saasStoreDisplayName(store, connection) { return store?.store_name || connection?.store_name || 'eBay 店铺'; }
function saasStoreStatusLabel(status) { return status === 'connected' ? '只读已连接' : '等待连接'; }
function saasMerchantRoleLabel(role) { return role === 'owner' ? '账号所有者' : '成员'; }
function isSaasModelConfigured() { return false; }
function isSaasAuthorizedConnectionStatus(status) { return ['connected', 'authorized'].includes(status); }
function isSaasEbayUnpublishedDraftAuthorized() { return false; }
function hasSaasProtectedSessionCandidate() { return state.saasConnected; }
function saasAccountDisplayName() { return saasCurrentAccountSummary().displayName; }
function normalizeSaasRecordStoreId(value) { return String(value || '').trim(); }
function saasRecordStoreId(item) { return normalizeSaasRecordStoreId(item?.store_id); }
function sortedSaasDataPackets(items) { return [...items]; }
function saasMerchantVisiblePublishCode(value, fallback) { return value || fallback; }
function saasCompactValue(value) { return JSON.stringify(value); }
function saasExactReadOnlyOAuthConfirmationForStore() { return readOnlyConfirmation; }
function saasExactUnpublishedDraftOAuthConfirmationForStore() { return draftConfirmation; }
function isSaasFreshApprovedReadOnlyOAuthConfirmation(value) { return value?.fresh === true; }
function isSaasFreshApprovedUnpublishedDraftOAuthConfirmation(value) { return value?.fresh === true; }
function resetFixture() {
  for (const key of Object.keys(state)) delete state[key];
  Object.assign(state, {
    saasConnected: true, saasLoading: false,
    saasUser: { user_id: 'user-a', email: 'merchant-fixture@example.test' },
    saasCompany: { company_id: 'company-a', company_name: '商家 <M&N>' },
    saasStores: [
      { store_id: 'store-a', store_name: '当前 <A&B> 店铺', marketplace: 'EBAY_US' },
      { store_id: 'store-b', store_name: '另一店铺', marketplace: 'EBAY_GB' },
    ],
    saasConnections: [{ store_id: 'store-a', store_name: '当前 <A&B> 店铺', marketplace: 'EBAY_US', status: 'connected' }, { store_id: 'store-b', store_name: '另一店铺', status: 'connected' }],
    saasDataPackets: [], saasSecretRefs: [], saasAccountHealth: null,
    saasMerchantOnboarding: { store_id: 'store-a', effective_stage: 'read_only_check_required', stage_label: '请更新只读资料' },
    saasBrowserSessions: [
      { session_ref: 'private-edge-ref', device_label: 'Edge · Windows', status: 'active', secret_exposed: false, current: false },
      { session_ref: 'private-chrome-ref', device_label: 'Chrome · Windows', status: 'active', secret_exposed: false, current: true },
      { session_ref: 'private-invalid-ref', device_label: 'arbitrary-agent', status: 'active', secret_exposed: false },
    ],
  });
  ctx = { store: state.saasStores[0], connection: state.saasConnections[0] };
  readOnlyConfirmation = null; draftConfirmation = null;
}
"""


RUNTIME_CHECKS = r"""
resetFixture();
const renders = {};
renders.normal = renderSaasSettingsAccountWorkspace(ctx, { ebayAuthorized: true });
assert(renders.normal.includes('商家 &lt;M&amp;N&gt;'), 'account summary must escape current company');
assert(renders.normal.includes('当前 &lt;A&amp;B&gt; 店铺'), 'store display must escape current name');
assert(renders.normal.includes('saas-account-store-market">美国站</span>'), 'US marketplace must retain its readable label');
assert.equal(state.saasStores[1].marketplace, 'EBAY_GB');
assert.equal(state.saasConnections[1].marketplace, undefined);
assert(renders.normal.includes('saas-account-store-market">英国站</span>'), 'declared GB store must not inherit normalized connection default US');
assert(renders.normal.indexOf('Edge · Windows') < renders.normal.indexOf('Chrome · Windows'), 'session display order changed');
assert(!renders.normal.includes('private-edge-ref') && !renders.normal.includes('private-invalid-ref'), 'session reference leaked into HTML');
const sessionButtons = [{}, {}];
bindSaasBrowserSessionControls({ querySelectorAll: () => sessionButtons });
assert.equal(saasBrowserSessionButtonBindings.get(sessionButtons[0]), 'private-edge-ref');
assert.equal(saasBrowserSessionButtonBindings.get(sessionButtons[1]), 'private-chrome-ref');
const nonGreen = value => assert(!['green', 'success'].includes(value.tone), 'unverified/restricted account became green');
nonGreen(saasSettingsAccountStoreStatus(ctx));
state.saasAccountHealth = { status: 'normal', severity: 'green', evidence_package: { official_packet_present: false } };
nonGreen(saasSettingsAccountStoreStatus(ctx));
state.saasAccountHealth.evidence_package.official_packet_present = true;
assert(['green', 'success'].includes(saasSettingsAccountStoreStatus(ctx).tone), 'verified normal account should be distinguishable');
renders.verified = renderSaasSettingsAccountWorkspace(ctx, { ebayAuthorized: true });
for (const status of ['restricted', 'suspended', 'payout_hold', 'quota_limited']) {
  state.saasAccountHealth = { status, evidence_package: { official_packet_present: true } };
  nonGreen(saasSettingsAccountStoreStatus(ctx));
}
state.saasAccountHealth = { status: 'normal', incident_mode: true, evidence_package: { official_packet_present: true } };
nonGreen(saasSettingsAccountStoreStatus(ctx));
resetFixture();
renders.healthUnknown = renderSaasAccountHealthPanel();
renders.policiesUnknown = renderSaasSettingsAccountPolicies();
state.saasMerchantOnboarding.business_policy_statuses = { fulfillment: true, payment: false };
renders.policiesMixed = renderSaasSettingsAccountPolicies();
state.saasLoading = true;
renders.policiesLoading = renderSaasSettingsAccountPolicies();
state.saasLoading = false;
state.saasStores = []; state.saasConnections = []; ctx = { store: null, connection: null };
renders.empty = renderSaasSettingsAccountWorkspace(ctx);
nonGreen(saasSettingsAccountStoreStatus(ctx));
state.saasConnected = false; state.saasUser = null; state.saasCompany = null;
renders.signedOut = renderSaasSettingsAccountWorkspace(ctx);

resetFixture();
assert.equal(saasSettingsAccountOnboardingMatchesStore(ctx), true, 'exact top-level store binding must match');
state.saasMerchantOnboarding.business_policy_statuses = { fulfillment: true, payment: true, return: true };
state.saasMerchantOnboarding.stage_label = 'ONLY_PRIMARY_STORE_A_NEXT_STEP';
renders.onboardingScoped = [];
function recordUnboundOnboarding(name) {
  assert.equal(saasSettingsAccountOnboardingMatchesStore(ctx), false, `${name}: onboarding store binding must fail closed`);
  renders.onboardingScoped.push({ name, html: renderSaasSettingsAccountWorkspace(ctx), policies: renderSaasSettingsAccountPolicies(ctx) });
}
ctx = { store: state.saasStores[1], connection: state.saasConnections[1] };
recordUnboundOnboarding('different-current-store');
ctx = { store: state.saasStores[0], connection: state.saasConnections[0] };
delete state.saasMerchantOnboarding.store_id;
recordUnboundOnboarding('missing-top-level-binding');
state.saasMerchantOnboarding.store = { store_id: 'store-a' };
recordUnboundOnboarding('nested-binding-is-not-authority');
state.saasMerchantOnboarding.store_id = 'store-a';
ctx = { store: null, connection: null };
state.saasStores = []; state.saasConnections = [];
recordUnboundOnboarding('missing-current-store');
state.saasMerchantOnboarding.store_id = '';
recordUnboundOnboarding('both-store-ids-empty');
state.saasMerchantOnboarding = null;
recordUnboundOnboarding('missing-onboarding');

resetFixture();
state.saasMerchantOnboarding.effective_stage = 'account_review_required';
renders.accountReview = renderSaasSettingsAccountWorkspace(ctx);
renders.accountReviewOtherCompact = renderSaasMerchantOnboardingPanel({ compact: true });
renders.accountReviewFull = renderSaasMerchantOnboardingPanel();
state.saasLoading = true;
renders.accountReviewLoading = renderSaasSettingsAccountWorkspace(ctx);
state.saasLoading = false;
for (const [stage, action] of Object.entries({
  seller_registration_required: 'open-official-ebay-seller-registration',
  authorization_required: 'plan-ebay-oauth',
  read_only_check_required: 'sync-ebay-readonly',
  business_policies_required: 'open-official-ebay-business-policies',
  ready_for_publish_preflight: 'focus-publish-intake',
  loading: 'refresh',
})) {
  state.saasMerchantOnboarding.effective_stage = stage;
  const html = renderSaasMerchantOnboardingPanel({ compact: true, accountWorkspace: true });
  assert(html.includes(`data-saas-action="${action}"`), `${stage}: existing onboarding action changed`);
  assert(!html.includes('data-saas-account-open-health'), `${stage}: health disclosure override must be review-only`);
}

resetFixture();
renders.oauth = [];
for (const status of ['not_started', 'pending', 'approved', 'rejected', 'executed']) {
  readOnlyConfirmation = status === 'not_started' ? null : { status, fresh: true };
  draftConfirmation = status === 'not_started' ? null : { status, fresh: true };
  renders.oauth.push({ status, html: renderSaasSettingsAccountWorkspace(ctx) });
}
readOnlyConfirmation = { status: 'approved', fresh: false };
draftConfirmation = { status: 'approved', fresh: false };
renders.expired = renderSaasSettingsAccountWorkspace(ctx);
assert(renders.expired.includes('确认已失效'), 'expired approvals must remain visible');
renders.authorized = renderSaasSettingsAccountWorkspace(ctx, { ebayAuthorized: true, ebayDraftAuthorized: true });
assert(renders.authorized.includes('data-ebay-oauth-confirmation-status="authorized"'));
assert(renders.authorized.includes('data-ebay-draft-oauth-confirmation-status="authorized"'));
state.saasEbayRefreshProofStatusStoreId = 'store-a';
state.saasEbayRefreshProofStatus = { current_store_selected: true, refresh_success_ready: true, refresh_same_connection_ready: true, store_id_sha256: 'a'.repeat(64), connection_id_sha256: 'b'.repeat(64), secret_exposed: false };
renders.proofVerified = renderSaasSettingsAccountWorkspace(ctx, { ebayAuthorized: true });
assert(renders.proofVerified.includes('data-ebay-refresh-proof-status="verified"'));
state.saasEbayRefreshProofStatusStoreId = 'store-b';
renders.proofOtherStore = renderSaasSettingsAccountWorkspace(ctx, { ebayAuthorized: true });
assert(renders.proofOtherStore.includes('data-ebay-refresh-proof-status="pending"'), 'another store proof must not verify current connection');

resetFixture();
const keys = ['account', 'store', 'health', 'sessions', 'security', 'policies'];
const root = { details: [], querySelectorAll: () => root.details };
function newDetails(open = []) { root.details = keys.map(key => ({ dataset: { saasAccountDisclosure: key }, open: open.includes(key) })); }
function rerender() { const snapshot = captureSaasSettingsAccountDisclosureState(root, ctx); newDetails(); restoreSaasSettingsAccountDisclosureState(root, snapshot); return snapshot; }
newDetails(['store']);
assert.deepEqual(rerender().openKeys, [], 'first visit must not adopt unscoped DOM state');
root.details.find(item => item.dataset.saasAccountDisclosure === 'store').open = true;
root.details.find(item => item.dataset.saasAccountDisclosure === 'sessions').open = true;
assert.deepEqual(rerender().openKeys, ['store', 'sessions'], 'same-scope refresh lost open disclosures');
assert(root.details.find(item => item.dataset.saasAccountDisclosure === 'store').open);
root.details = [];
assert.deepEqual(rerender().openKeys, ['store', 'sessions'], 'temporary different settings tab lost same-scope state');
state.saasUser.user_id = 'user-b';
assert.deepEqual(rerender().openKeys, [], 'different user inherited disclosure state');
root.details[0].open = true; rerender();
state.saasCompany.company_id = 'company-b';
assert.deepEqual(rerender().openKeys, [], 'same user different company inherited disclosure state');
root.details[1].open = true; rerender();
ctx = { store: state.saasStores[1], connection: state.saasConnections[1] };
assert.deepEqual(rerender().openKeys, [], 'store switch inherited disclosure state');
state.saasUser.user_id = 'user-a'; state.saasCompany.company_id = 'company-a'; ctx.store = state.saasStores[0];
assert.deepEqual(rerender().openKeys, [], 'returning to old scope resurrected discarded disclosure state');
state.saasUser = { id: 'id-fallback', email: 'fallback@example.test' }; state.saasCompany = { id: 'company-fallback' };
assert.deepEqual(JSON.parse(saasSettingsAccountDisclosureScope(ctx)), ['id-fallback', 'company-fallback', 'store-a']);
delete state.saasUser.id;
assert.deepEqual(JSON.parse(saasSettingsAccountDisclosureScope(ctx)), ['fallback@example.test', 'company-fallback', 'store-a']);

resetFixture();
function focusFixture() {
  const doc = { body: { tagName: 'BODY' }, activeElement: null };
  const focusCalls = [];
  const target = {
    ownerDocument: doc,
    contains: element => element?.owner === target,
    querySelector: selector => selector === '[data-saas-action="refresh"]' ? target.refresh : null,
    querySelectorAll: selector => selector === '[data-saas-account-disclosure]' ? target.details : selector === '[data-saas-settings-tab]' ? target.tabs : [],
  };
  function control(key, properties = {}) {
    const element = { owner: target, disabled: false, dataset: {}, ...properties };
    element.focus = options => { assert.equal(element.disabled, false, 'cannot focus disabled control'); focusCalls.push({ key, options }); doc.activeElement = element; };
    return element;
  }
  function replace(disabled = false) {
    target.refresh = control('refresh', { tagName: 'BUTTON', dataset: { saasAction: 'refresh' }, disabled });
    target.tabs = ['account', 'model'].map(key => control(`tab:${key}`, { tagName: 'BUTTON', dataset: { saasSettingsTab: key } }));
    target.details = keys.map(key => {
      const item = { open: false, dataset: { saasAccountDisclosure: key } };
      item.summary = control(`summary:${key}`, { tagName: 'SUMMARY', parentElement: item });
      item.querySelector = selector => selector === 'summary' ? item.summary : null;
      return item;
    });
    doc.activeElement = doc.body;
  }
  function rerenderFocus(disabled = false) {
    const snapshot = captureSaasSettingsAccountDisclosureState(target, ctx);
    replace(disabled);
    restoreSaasSettingsAccountDisclosureState(target, snapshot);
    return snapshot;
  }
  replace();
  restoreSaasSettingsAccountDisclosureState(target, { scope: saasSettingsAccountDisclosureScope(ctx), openKeys: [], focusKey: null });
  return { target, doc, focusCalls, rerenderFocus };
}
const focusState = focusFixture();
const storeDisclosure = focusState.target.details.find(item => item.dataset.saasAccountDisclosure === 'store');
storeDisclosure.open = true;
focusState.doc.activeElement = storeDisclosure.summary;
assert.equal(focusState.rerenderFocus().focusKey, 'summary:store');
assert.equal(focusState.doc.activeElement, focusState.target.details.find(item => item.dataset.saasAccountDisclosure === 'store').summary);
assert.equal(focusState.target.details.find(item => item.dataset.saasAccountDisclosure === 'store').open, true);
assert.deepEqual(focusState.focusCalls.at(-1), { key: 'summary:store', options: { preventScroll: true } }, 'summary restore must not jump scroll');
focusState.doc.activeElement = focusState.target.tabs[1];
assert.equal(focusState.rerenderFocus().focusKey, 'tab:model');
assert.equal(focusState.doc.activeElement, focusState.target.tabs[1]);
assert.deepEqual(focusState.focusCalls.at(-1).options, { preventScroll: true });
focusState.doc.activeElement = focusState.target.refresh;
const callsBeforeRefresh = focusState.focusCalls.length;
assert.equal(focusState.rerenderFocus(true).pendingFocus, true);
assert.equal(focusState.doc.activeElement, focusState.doc.body, 'disabled refresh render should defer focus');
assert.equal(focusState.focusCalls.length, callsBeforeRefresh);
assert.equal(focusState.rerenderFocus(true).focusKey, 'refresh', 'body focus during loading must retain pending refresh target');
const completedFocus = focusState.rerenderFocus(false);
assert.equal(completedFocus.pendingFocus, false);
assert.equal(focusState.doc.activeElement, focusState.target.refresh, 'enabled refresh must regain focus after loading');
assert.equal(focusState.focusCalls.length, callsBeforeRefresh + 1);
assert.deepEqual(focusState.focusCalls.at(-1), { key: 'refresh', options: { preventScroll: true } });
focusState.doc.activeElement = focusState.doc.body;
assert.equal(focusState.rerenderFocus().focusKey, null, 'successful restoration must not retain an indefinite body-focus claim');
assert.equal(focusState.focusCalls.length, callsBeforeRefresh + 1);

for (const reason of ['outside-root', 'different-user', 'different-company', 'different-store']) {
  resetFixture();
  const deferred = focusFixture();
  deferred.doc.activeElement = deferred.target.refresh;
  deferred.rerenderFocus(true);
  if (reason === 'outside-root') deferred.doc.activeElement = { tagName: 'INPUT' };
  if (reason === 'different-user') state.saasUser.user_id = 'user-focus-b';
  if (reason === 'different-company') state.saasCompany.company_id = 'company-focus-b';
  if (reason === 'different-store') ctx = { store: state.saasStores[1], connection: state.saasConnections[1] };
  const snapshot = deferred.rerenderFocus(false);
  assert.equal(snapshot.focusKey, null, `${reason}: old pending focus must be discarded`);
  assert.equal(snapshot.pendingFocus, false, `${reason}: discarded focus must not remain pending`);
  assert.equal(deferred.focusCalls.length, 0, `${reason}: settings must not steal focus`);
}

resetFixture();
function button(storeId) { return { disabled: false, dataset: { saasAccountStore: storeId }, addEventListener(type, callback) { assert.equal(type, 'click'); this.click = callback; } }; }
const valid = button('store-b'), invalid = button('unlisted-store'), disabled = button('store-b');
disabled.disabled = true;
let events = [];
selectedElement = { value: 'saas:store-a', options: [{ value: 'saas:store-a' }, { value: 'saas:store-b' }], dispatchEvent: event => events.push(event) };
function storeControlsRoot(buttons) { return { querySelectorAll: selector => selector === '[data-saas-account-store]' ? buttons : [] }; }
bindSaasSettingsAccountControls(storeControlsRoot([valid, invalid, disabled]));
invalid.click(); disabled.click(); assert.equal(events.length, 0, 'invalid or disabled store fired change');
state.saasLoading = true; valid.click(); assert.equal(events.length, 0, 'loading store fired change');
state.saasLoading = false; valid.click();
assert.equal(selectedElement.value, 'saas:store-b'); assert.equal(events.length, 1);
assert.equal(events[0].type, 'change'); assert.equal(events[0].bubbles, true);
valid.click(); assert.equal(events.length, 1, 'double click duplicated switch transaction');
selectedElement = null;
const absent = button('store-b'); bindSaasSettingsAccountControls(storeControlsRoot([absent])); absent.click();
assert.equal(events.length, 1, 'missing real selector must fail closed');
const openCurrent = button('');
let focused = 0, scrolled = 0;
const currentDetails = {
  open: false,
  querySelector: selector => selector === 'summary' ? { focus: () => focused++ } : null,
  scrollIntoView: options => { assert.equal(options.block, 'nearest'); scrolled++; },
};
const fallbackRoot = {
  querySelectorAll: selector => selector === '[data-saas-account-open-store]' ? [openCurrent] : [],
  querySelector: selector => selector === '[data-saas-account-disclosure="store"]' ? currentDetails : null,
};
bindSaasSettingsAccountControls(fallbackRoot);
openCurrent.click();
assert.equal(currentDetails.open, true, 'unbound onboarding fallback must open current store details');
assert.equal(focused, 1, 'fallback must move focus to current store summary');
assert.equal(scrolled, 1, 'fallback must reveal current store details');
assert.equal(events.length, 1, 'fallback must not switch stores or refresh primary onboarding');
fallbackRoot.querySelector = () => null;
openCurrent.click();
assert.equal(focused, 1, 'missing details must be a safe no-op');
const openHealth = button('');
let healthFocused = 0, healthScrolled = 0;
const healthDetails = {
  open: false,
  querySelector: selector => selector === 'summary' ? { focus: () => healthFocused++ } : null,
  scrollIntoView: options => { assert.equal(options.block, 'nearest'); healthScrolled++; },
};
currentDetails.open = false;
const healthRoot = {
  querySelectorAll: selector => selector === '[data-saas-account-open-health]' ? [openHealth] : [],
  querySelector: selector => selector === '[data-saas-account-disclosure="store"]' ? currentDetails : selector === '[data-saas-account-disclosure="health"]' ? healthDetails : null,
};
bindSaasSettingsAccountControls(healthRoot);
openHealth.disabled = true; openHealth.click();
assert.equal(currentDetails.open, false, 'disabled health action must not open store');
assert.equal(healthDetails.open, false, 'disabled health action must not open health');
openHealth.disabled = false; openHealth.click();
assert.equal(currentDetails.open, true, 'health action must reveal outer store disclosure');
assert.equal(healthDetails.open, true, 'health action must reveal inner health disclosure');
assert.equal(healthFocused, 1, 'health action must focus inner health summary');
assert.equal(healthScrolled, 1, 'health action must reveal inner health details');
assert.equal(focused, 1, 'health action must not stop focus at outer store summary');
assert.equal(scrolled, 1, 'health action must scroll health rather than outer store');
assert.equal(events.length, 1, 'health action must not navigate, switch or refresh');
currentDetails.open = false; healthDetails.open = false;
healthRoot.querySelector = selector => selector === '[data-saas-account-disclosure="store"]' ? currentDetails : null;
openHealth.click();
assert.equal(currentDetails.open, false, 'missing health detail must not partially expand or navigate');
assert.equal(healthFocused, 1, 'missing health detail must be a safe no-op');
process.stdout.write(JSON.stringify(renders));
"""


def main() -> None:
    app = (ROOT / "app.js").read_text(encoding="utf-8")
    workspace = function_source(app, "renderSaasSettingsAccountWorkspace")
    for marker in (
        "saas-account-workspace",
        "saas-account-identity",
        "saas-account-store-list",
    ):
        if marker not in workspace:
            raise AssertionError(f"account workspace lost merchant layout hook: {marker}")
    for sample in ("示例商家", "owner@example.com", "示例 eBay 店铺", "local-session-", "布局预览"):
        if sample in workspace:
            raise AssertionError(f"production workspace contains preview fixture: {sample}")
    definitions = function_source(app, "saasSettingsTabDefinitions")
    account_tab = definitions[definitions.index('id: "account"') : definitions.index('id: "model"')]
    if account_tab.count("renderSaasSettingsAccountWorkspace(ctx, options)") != 1:
        raise AssertionError("account tab must render exactly one account workspace")
    for retired_panel in ("renderSaasSettingsAccountAccessPanel(", "renderSaasAccountHealthPanel(", "renderSaasBrowserSessionsPanel("):
        if retired_panel in account_tab:
            raise AssertionError("account tab must not duplicate workspace panels outside their disclosures")
    connect = function_source(app, "renderSaasConnectCenter")
    sequence = [connect.index(marker) for marker in (
        "captureSaasSettingsAccountDisclosureState(view, ctx)", "setJiejingTrustedHtml(",
        "bindSaasBrowserSessionControls(view)", "restoreSaasSettingsAccountDisclosureState(view, disclosureState)",
        "bindSaasSettingsAccountControls(view)",
    )]
    if sequence != sorted(sequence):
        raise AssertionError("settings rerender must capture before replacement and restore/bind afterward")
    for name in ("saasSettingsAccountStoreStatus", "saasSettingsAccountDisclosureScope", "captureSaasSettingsAccountDisclosureState", "restoreSaasSettingsAccountDisclosureState", "bindSaasSettingsAccountControls", "saasSettingsAccountOnboardingMatchesStore", "renderSaasSettingsAccountPolicies", "renderSaasSettingsAccountWorkspace"):
        if re.search(r"\b(?:fetch|saasFetch|localStorage|sessionStorage|XMLHttpRequest)\b", function_source(app, name)):
            raise AssertionError(f"layout-only helper introduced direct backend/storage access: {name}")
    names = (
        "saasCurrentAccountSummary", "saasKnownStoreCandidates", "saasAccountHealthSnapshot",
        "saasMerchantSafeSettingsText", "saasAccountHealthTone", "saasSellerOnboardingGuidance",
        "renderSaasAccountHealthPanel", "renderSaasMerchantOnboardingPanel",
        "saasReadOnlyConnectionConfirmationView", "saasUnpublishedDraftConnectionConfirmationView",
        "saasCurrentStoreEbayRefreshProofView", "renderSaasSettingsAccountPanel",
        "renderSaasSettingsAccountAccessPanel", "safeSaasBrowserSessionsForDisplay",
        "saasBrowserSessionTime", "renderSaasBrowserSessionsPanel", "bindSaasBrowserSessionControls",
        "saasSettingsAccountStoreStatus", "saasSettingsAccountDisclosureScope",
        "captureSaasSettingsAccountDisclosureState", "restoreSaasSettingsAccountDisclosureState",
        "bindSaasSettingsAccountControls", "saasSettingsAccountOnboardingMatchesStore",
        "renderSaasSettingsAccountPolicies", "renderSaasSettingsAccountWorkspace",
    )
    script = RUNTIME_FIXTURE + "\n" + "\n".join(function_source(app, name) for name in names) + RUNTIME_CHECKS
    result = subprocess.run(["node", "-"], input=script, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=30)
    if result.returncode:
        raise AssertionError(f"account workspace runtime regression:\n{result.stderr}")
    renders = json.loads(result.stdout)
    normal = Markup(renders["normal"])
    identity = re.search(r'<details[^>]*class="saas-account-identity"[^>]*>\s*<summary>(.*?)</summary>', renders["normal"], re.DOTALL)
    if not identity or not all(value in identity.group(1) for value in ("商家 &lt;M&amp;N&gt;", "merchant-fixture@example.test")):
        raise AssertionError("account header must show real escaped identity before expansion")
    for key in ("account", "store", "sessions"):
        rows = normal.with_attr("data-saas-account-disclosure", key)
        if len(rows) != 1 or rows[0][0] != "details" or "open" in rows[0][1]:
            raise AssertionError(f"{key} must start as one native collapsed disclosure")
    for name in ("plan-ebay-oauth", "plan-ebay-draft-oauth", "verify-ebay-credential-proof", "refresh"):
        if not normal.with_attr("data-saas-action", name):
            raise AssertionError(f"workspace lost existing action: {name}")
    for name in ("switch-account", "logout"):
        if not normal.with_attr("data-account-action", name):
            raise AssertionError(f"workspace lost account action: {name}")
    for name in ("data-saas-session-revoke", "data-saas-session-revoke-others"):
        if not normal.with_attr(name):
            raise AssertionError(f"workspace lost session action: {name}")
    next_action = normal.with_attr("data-saas-action", "sync-ebay-readonly")
    if len(next_action) != 1 or next_action[0][2] != 0:
        raise AssertionError("current onboarding next action must remain outside collapsed details")
    account_review = Markup(renders["accountReview"])
    health_action = account_review.with_attr("data-saas-account-open-health")
    if len(health_action) != 1 or health_action[0][2] != 0 or account_review.with_attr("data-saas-action", "open-connect"):
        raise AssertionError("account review must visibly open local health details, not reenter current settings")
    if "disabled" not in Markup(renders["accountReviewLoading"]).with_attr("data-saas-account-open-health")[0][1]:
        raise AssertionError("local health review action must stay disabled while loading")
    for name in ("accountReviewOtherCompact", "accountReviewFull"):
        original = Markup(renders[name])
        if not original.with_attr("data-saas-action", "open-connect") or original.with_attr("data-saas-account-open-health"):
            raise AssertionError("account-workspace health override must not change other onboarding callers")
    if not normal.with_attr("data-saas-account-store", "store-b") or normal.with_attr("id", "storeSwitch"):
        raise AssertionError("workspace must switch other stores through the existing unique header selector")
    verified = Markup(renders["verified"])
    status_rows = [attrs for _, attrs, _ in verified.elements if "saas-account-store-status" in str(attrs.get("class", ""))]
    if len(status_rows) != 2 or "is-success" in str(status_rows[1].get("class", "")):
        raise AssertionError("another store must not inherit current store health")
    if "未发现付款冻结" in renders["healthUnknown"]:
        raise AssertionError("missing payout evidence must not imply no payment freeze")
    payout_row = re.search(r'<article\b([^>]*)>\s*<span>付款/资金</span>', renders["healthUnknown"])
    if not payout_row or "is-green" in payout_row.group(1):
        raise AssertionError("missing payout evidence must not render a green funds row")
    if renders["policiesUnknown"].count("<dd>待核实</dd>") != 3:
        raise AssertionError("missing policy evidence must leave all three policies unverified")
    for label, expected in (("配送政策", "已读取"), ("付款政策", "待补齐"), ("退货政策", "待核实")):
        if f"<dt>{label}</dt><dd>{expected}</dd>" not in renders["policiesMixed"]:
            raise AssertionError(f"policy evidence state changed: {label}={expected}")
    policy_action = Markup(renders["policiesMixed"]).with_attr("data-saas-action", "open-official-ebay-business-policies")
    if len(policy_action) != 1 or "disabled" in policy_action[0][1]:
        raise AssertionError("policy management must retain its existing enabled official action")
    if "disabled" not in Markup(renders["policiesLoading"]).with_attr("data-saas-action", "open-official-ebay-business-policies")[0][1]:
        raise AssertionError("policy management must stay disabled while loading")
    for item in renders["onboardingScoped"]:
        if item["policies"].count("<dd>待核实</dd>") != 3:
            raise AssertionError(f"unbound primary-store policies leaked into current store: {item['name']}")
        parsed = Markup(item["html"])
        if "ONLY_PRIMARY_STORE_A_NEXT_STEP" in item["html"] or parsed.with_attr("data-onboarding-contract") or parsed.with_attr("data-saas-action", "sync-ebay-readonly"):
            raise AssertionError(f"unbound primary-store next action leaked into current store: {item['name']}")
        fallback = parsed.with_attr("data-saas-account-open-store")
        if len(fallback) != 1 or fallback[0][2] != 0 or "data-saas-action" in fallback[0][1]:
            raise AssertionError(f"unbound onboarding must keep a visible details-only fallback: {item['name']}")
    for item in renders["oauth"]:
        parsed = Markup(item["html"])
        for attr in ("data-ebay-oauth-confirmation-status", "data-ebay-draft-oauth-confirmation-status"):
            if not parsed.with_attr(attr, item["status"]):
                raise AssertionError(f"workspace lost confirmation state {attr}={item['status']}")
    for name in ("plan-ebay-oauth", "plan-ebay-draft-oauth"):
        if "disabled" not in Markup(renders["authorized"]).with_attr("data-saas-action", name)[0][1]:
            raise AssertionError(f"authorized control must not repeat permission flow: {name}")
    if "disabled" not in Markup(renders["proofVerified"]).with_attr("data-saas-action", "verify-ebay-credential-proof")[0][1]:
        raise AssertionError("verified connection must not offer duplicate verification")
    if "尚未关联" not in renders["empty"] or Markup(renders["empty"]).with_attr("data-saas-account-store"):
        raise AssertionError("empty account must not invent store rows")
    if any("disabled" not in attrs for _, attrs, _ in Markup(renders["signedOut"]).with_attr("data-account-action", "logout")):
        raise AssertionError("signed-out account cannot offer active logout")
    print("PASS jiejing_settings_account_workspace_ui")


if __name__ == "__main__":
    main()
