#!/usr/bin/env node
"use strict";

// Real app functions with an isolated VM and explicitly substituted rendering /
// HTTP seams. This verifies auth state transitions, not browser layout or live API.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

const source = fs.readFileSync(path.join(__dirname, "..", "app.js"), "utf8");
function extractFunction(name, optional = false) {
  const declaration = new RegExp(`^(?:async )?function ${name}\\(`, "m").exec(source);
  if (!declaration && optional) return "";
  assert.ok(declaration, `${name} must be present in real app.js`);
  const tail = source.slice(declaration.index);
  // Product functions are top-level declarations, with their closing brace in
  // column zero. Keep the original complete body; do not copy its decisions.
  const end = /\n\}\r?(?:\n|$)/.exec(tail);
  assert.ok(end, `${name} must have a complete top-level body`);
  return tail.slice(0, end.index + 2);
}

function classList(initial = []) {
  const values = new Set(initial);
  return {
    add(...names) { names.forEach((name) => values.add(name)); },
    remove(...names) { names.forEach((name) => values.delete(name)); },
    contains(name) { return values.has(name); },
    toggle(name, force) {
      const enabled = force === undefined ? !values.has(name) : force;
      if (enabled) values.add(name); else values.delete(name);
      return enabled;
    },
  };
}
function storage(entries = []) {
  const data = new Map(entries);
  return {
    getItem(key) { return data.has(key) ? data.get(key) : null; },
    setItem(key, value) { data.set(key, String(value)); },
    removeItem(key) { data.delete(key); },
  };
}
function deferred() {
  let resolve;
  const promise = new Promise((done) => { resolve = done; });
  return { promise, resolve };
}

function harness() {
  const localStorage = storage([["last-account", "fixture-user-a"], ["session-hint", "1"],
    ["ceo-thread", JSON.stringify({ "fixture-user-a": [{ assistant_id: "fixture-history-a",
      user_text: "ACCOUNT_A_PRIVATE_HISTORY_SENTINEL", assistant_text: "Retained account history" }] })]]);
  const appShell = { classList: classList() };
  const context = {
    state: {
      view: "product", saasConnected: true, saasLoading: false,
      saasProtectedStateReady: true, saasProtectedStateFromCache: false,
      saasIdentity: { user_id: "fixture-user-a", company_id: "fixture-company-a" },
      saasUser: { user_id: "fixture-user-a" }, saasCompany: { company_id: "fixture-company-a" },
      saasAiCeoThread: [], saasAiCeoLatestTurn: null, saasLastCeoCommand: null,
      saasStores: [], saasConnections: [], saasDataPackets: [], saasReports: [],
      saasSessionExpiryHandled: false, saasManualLogout: false, saasToken: "",
    },
    localStorage, sessionStorage: storage(), appShell,
    entryShell: { classList: classList(["is-hidden"]) },
    siteShell: { classList: classList(["is-hidden"]) },
    onboardingShell: { classList: classList(["is-hidden"]) },
    document: {
      documentElement: { classList: classList(["app-start-requested", "app-ready"]), dataset: {} },
      body: { classList: classList(), dataset: {} },
      querySelector: (selector) => selector === "#appShell" ? appShell : null,
      querySelectorAll: () => [],
    },
    window: { clearTimeout() {}, setTimeout() {} },
    saasStorageKeys: { lastAccount: "last-account", sessionHint: "session-hint", token: "unused-fixture-token-key", protectedSnapshot: "snapshot", ceoThread: "ceo-thread" },
    saasStateRefreshGeneration: 0, saasAccountSessionEpoch: 0, saasBrowserSessionRefreshPromise: null,
    isSaasPublicMvpMode: () => true, isProtectedSaasAppRoute: () => true,
    loadSaasSessionFromStorage() {},
    safeStorageValue: (key) => localStorage.getItem(key) || "",
    hasSaasPersistentSessionHint: () => localStorage.getItem("session-hint") === "1",
    saasAccountStorageAliases: () => ["fixture-user-a"],
    saasCeoCommandStorageScope: () => "fixture-user-a",
    readSaasExpiredListingGeneration: () => null,
    saasExpiredListingGenerationStorageKey: () => "expired-fixture",
    saasProtectedSnapshotStorageKey: () => "snapshot:fixture-user-a",
    hydrateSaasProtectedStateFromCache: () => false,
    normalizeSaasCeoCommand: (value) => value || null,
    normalizeSaasAiCeoLatestTurn: (value) => value || null,
    shouldKeepSaasAiCeoThreadTurn: () => true,
    activeSaasRefreshView: () => "product",
    isSaasUnrecoverableSessionError: () => false,
    syncAppStartVisibleShellGuard() {},
  };
  // Explicitly stub effects outside the auth boundary. All functions under test
  // and the context invalidator below come from app.js, including refresh logic.
  for (const name of [
    "invalidateSaasSettingsActionContext", "stopSaasAiCeoCrossDeviceSync",
    "resetSaasAiCeoHistoryArchive", "resetSaasAiCeoComposerDrafts",
    "clearSaasProductFeedbackLiveIdentity", "resetSaasProductFeedbackViewState",
    "resetSaasListingProjectTransientState", "stopSaasPendingNewListingProjectReconciliation",
    "clearStoredSaasStoreContext", "renderAccountMenu", "renderStoreContext",
    "renderGlobalLoopWorkbench", "renderSaasBackendPanel", "syncSaasPublicMvpMode",
    "closeAccountMenu", "prefillSaasLoginEmail", "showActionToast", "setView",
  ]) context[name] = () => {};
  context.openAuth = () => { context.authOpened = true; };
  vm.createContext(context);
  const required = [
    "hasSaasProtectedSessionCandidate", "hasSaasProtectedBackendState",
    "isSaasUnrecoverableSessionError",
    "shouldReadSaasAccountScopedLocalCache", "loadSaasAiCeoThread", "shouldDeferSaasProtectedAppReveal",
    "clearSaasSessionFromStorage", "resetSaasProtectedWorkbenchState",
    "resolveSaasEbaySubmittedOutcomes",
    "resetSaasAccountShellState", "startSaasAccountSwitch", "refreshSaasState",
  ];
  const optional = ["invalidateSaasProtectedSessionContext", "assertSaasAccountSessionCurrent", "assertSaasLiveIdentityScope"];
  vm.runInContext([...required.map((name) => extractFunction(name)),
    ...optional.map((name) => extractFunction(name, true))].join("\n"), context);
  return context;
}
function run(context, expression) { return vm.runInContext(expression, context); }

function browserRefreshHarness() {
  const context = harness();
  context.SAAS_BROWSER_SESSION_REFRESH_LOCK = "fixture-refresh-lock";
  context.state.saasApiBase = "http://127.0.0.1:0";
  vm.runInContext(["refreshSaasBrowserSession", "refreshSaasBrowserSessionInsideLock"]
    .map((name) => extractFunction(name)).join("\n"), context);
  return context;
}

test("old session probe cannot issue refresh POST after an account switch", async () => {
  const context = browserRefreshHarness();
  const probe = deferred();
  const calls = [];
  context.saasBrowserSessionRefreshFetch = async (url, options) => {
    calls.push(options.method);
    return probe.promise;
  };
  const pending = run(context, "refreshSaasBrowserSessionInsideLock()").then(() => null, (error) => error);
  run(context, "invalidateSaasProtectedSessionContext()");
  probe.resolve({ok:false,status:401});
  assert.equal((await pending).code, "saas_account_context_changed");
  assert.deepEqual(calls, ["GET"]);
});

test("a queued browser lock retains its original account epoch", async () => {
  const context = browserRefreshHarness();
  const lock = deferred();
  let callback;
  let calls = 0;
  context.navigator = {locks:{request: (_name, action) => {callback=action; return lock.promise;}}};
  context.saasBrowserSessionRefreshFetch = async () => {calls += 1; return {ok:true};};
  const pending = run(context, "refreshSaasBrowserSession()");
  run(context, "invalidateSaasProtectedSessionContext()");
  try { lock.resolve(await callback()); } catch (error) { lock.resolve(Promise.reject(error)); }
  assert.equal(await pending, false);
  assert.equal(calls, 0);
});

test("new account refresh does not join old work and old completion does not clear the new promise", async () => {
  const context = browserRefreshHarness();
  const probes = [deferred(), deferred()];
  let calls = 0;
  context.saasBrowserSessionRefreshFetch = async () => probes[calls++].promise;
  const old = run(context, "refreshSaasBrowserSession()");
  run(context, "invalidateSaasProtectedSessionContext()");
  const current = run(context, "refreshSaasBrowserSession()");
  const currentShared = context.saasBrowserSessionRefreshPromise;
  assert.equal(calls, 2);
  probes[0].resolve({ok:true,status:200});
  assert.equal(await old, false);
  assert.equal(context.saasBrowserSessionRefreshPromise, currentShared);
  const joined = run(context, "refreshSaasBrowserSession()");
  assert.equal(calls, 2, "same account shares the still-pending request");
  probes[1].resolve({ok:true,status:200});
  assert.equal(await current, true);
  assert.equal(await joined, true);
  assert.equal(context.saasBrowserSessionRefreshPromise, null);
});

for (const change of ["user", "company"]) {
  test(`warm live ${change} change hides old business state before applying the new identity`, async () => {
    const context = harness();
    const retainedHistory = context.localStorage.getItem("ceo-thread");
    context.state.saasReports = [{report_id:"OLD_PRIVATE_REPORT"}];
    context.state.saasMediaAssetJobs = [{job_id:"OLD_PRIVATE_MEDIA"}];
    context.state.saasAiCeoThread = [{assistant_text:"OLD_PRIVATE_CHAT"}];
    let savedScope;
    context.saveSaasProtectedStateSnapshot = () => {
      savedScope = [context.state.saasUser.user_id, context.state.saasCompany.company_id];
    };
    context.saveSaasSessionToStorage = () => assert.fail("changed identity must not be committed by the old request");
    const liveUserId = change === "user" ? "fixture-user-b" : "fixture-user-a";
    const liveCompanyId = change === "company" ? "fixture-company-b" : "fixture-company-a";
    context.saasFetch = async (endpoint) => {
      assert.equal(endpoint, "/me");
      return { user:{user_id:liveUserId}, identity:{user_id:liveUserId,company_id:liveCompanyId},
        company:{company_id:liveCompanyId} };
    };
    vm.runInContext(extractFunction("ensureSaasDemoSession"), context);
    await assert.rejects(run(context, "ensureSaasDemoSession()"), {code:"saas_account_context_changed"});
    assert.deepEqual(savedScope, ["fixture-user-a","fixture-company-a"]);
    assert.equal(context.state.saasIdentity, null);
    assert.equal(context.state.saasReports.length, 0);
    assert.equal(context.state.saasMediaAssetJobs.length, 0);
    assert.equal(context.state.saasAiCeoThread.length, 0);
    assert.equal(context.appShell.classList.contains("is-hidden"), true);
    assert.equal(context.localStorage.getItem("ceo-thread"), retainedHistory);
    assert.equal(context.localStorage.getItem("session-hint"), "1");
  });
}

test("partial core failure cannot promote cold identity into a ready workbench", async () => {
  const context = harness();
  Object.assign(context.state, {saasProtectedStateReady:false,saasIdentity:null,saasUser:null,saasCompany:null});
  context.ensureSaasDemoStoreAndConnection = async () => {
    Object.assign(context.state,{saasIdentity:{user_id:"fixture-user-a",company_id:"fixture-company-a"},
      saasUser:{user_id:"fixture-user-a"},saasCompany:{company_id:"fixture-company-a"}});
    return {store_id:"fixture-store-a"};
  };
  context.saasAiCeoHistoryRequestContext = () => ({});
  context.optionalSaasFetchFast = async (_endpoint, fallback) => fallback;
  const coreRequests = [];
  const rejectedStatuses = [];
  context.saasFetch = async (endpoint) => {
    coreRequests.push(endpoint);
    if (endpoint === "/permissions/me") {
      const error = new Error("fixture core temporarily unavailable");
      error.status = 503;
      rejectedStatuses.push(error.status);
      throw error;
    }
    if (endpoint === "/me") return { identity:{...context.state.saasIdentity},
      user:{...context.state.saasUser}, company:{...context.state.saasCompany} };
    if (endpoint === "/stores") return { stores: [{store_id:"fixture-store-a",company_id:"fixture-company-a"}] };
    if (endpoint === "/connections") return { connections: [] };
    if (endpoint.startsWith("/tasks?")) return { tasks: [] };
    if (endpoint.startsWith("/confirmations?")) return { confirmations: [] };
    throw new Error(`unexpected fixture endpoint: ${endpoint}`);
  };
  await run(context,"refreshSaasState({silent:true})");
  assert.deepEqual(coreRequests, ["/me", "/permissions/me", "/stores", "/connections",
    "/tasks?limit=20&store_id=fixture-store-a", "/confirmations?limit=40"]);
  assert.deepEqual(rejectedStatuses, [503]);
  assert.equal(context.state.saasError, "工作台部分状态读取失败：fixture core temporarily unavailable");
  assert.equal(context.state.saasIdentity.user_id, "fixture-user-a", "identity alone remains insufficient");
  assert.equal(context.state.saasProtectedStateReady,false);
  assert.equal(run(context,"shouldDeferSaasProtectedAppReveal()"),true);
  assert.equal(context.localStorage.getItem("session-hint"),"1");
});

for (const failure of ["503", "timeout"]) {
  test(`real refresh distinguishes model-settings ${failure} and recovers without credential writes`, async () => {
    const context = harness();
    context.ensureSaasDemoStoreAndConnection = async () => ({store_id:"fixture-store-a"});
    context.saasAiCeoHistoryRequestContext = () => ({});
    context.syncSaasOnboardingCompletionFromBackend = () => {};
    context.verifySaasUnpublishedDraftSaveConfirmations = async () => {
      throw new Error("fixture-stop-after-real-core-assignment");
    };
    context.setTimeout = (callback, ms) => setTimeout(callback, Math.min(ms, 5));
    context.clearTimeout = clearTimeout;
    context.console = {warn() {}};
    context.saasModelBlockedReasonText = () => "";
    let connectionRecovered = false;
    const requestMethods = [];
    context.saasFetch = async (endpoint, options = {}) => {
      requestMethods.push(options.method || "GET");
      if (endpoint.endsWith("/model/settings")) {
        if (connectionRecovered) return {model_settings:{configured:true,connection_state:"ready"}};
        if (failure === "timeout") return new Promise(() => {});
        const error = new Error("fixture model settings 503");
        error.status = 503;
        throw error;
      }
      if (endpoint === "/me") return {identity:{...context.state.saasIdentity},user:{...context.state.saasUser},company:{...context.state.saasCompany}};
      if (endpoint === "/stores") return {stores:[{store_id:"fixture-store-a",company_id:"fixture-company-a"}]};
      return {};
    };
    vm.runInContext(["recordOptionalSaasSoftTimeout", "optionalSaasFetchFast", "saasModelConnectionAttemptState"].map(name => extractFunction(name)).join("\n"), context);
    await run(context, "refreshSaasState({silent:true})");
    assert.equal(context.state.saasError, "工作台部分状态读取失败：fixture-stop-after-real-core-assignment", "the real core assignment was reached");
    const status = run(context, "saasModelConnectionAttemptState()");
    assert.equal(status.state, "read_failed");
    assert.equal(status.requiresReentry, false);
    assert.equal(status.canRetry, false, "retry must read state, not invoke a model verification");
    assert.equal(context.state.saasModelSettings.configured, false, "unknown status must not grant AI availability");
    connectionRecovered = true;
    await run(context, "refreshSaasState({silent:true})");
    const recovered = run(context, "saasModelConnectionAttemptState()");
    assert.equal(recovered.state, "ready", "a fresh successful read clears the transient failure");
    assert.equal(recovered.requiresReentry, false);
    assert.equal(context.state.saasModelSettings.configured, true);
    assert.ok(requestMethods.every(method => method === "GET"), "recovery never saves credentials or invokes model verification");
  });
}

function cachedDraftHarness() {
  const context = harness();
  context.state.saasProtectedStateReady = false;
  context.state.saasPermissions = ["view_report"];
  context.state.saasRoles = ["merchant"];
  context.state.saasListingComposerDraft = null;
  context.state.saasStores = [{ store_id: "fixture-store-a", company_id: "fixture-company-a" }];
  const draft = { product: "Aluminum tablet stand", fields: { title: "Merchant unsent title", description: "Merchant unsent description" },
    merchant_edited_fields: ["title", "description"], listing_project_identity: { key: "fixture-tablet-project", source_report_id: "fixture-source", candidate_id: "tablet" } };
  const snapshot = { version: "2026-09-01-project-isolation-idempotency-v5", account_key: "fixture-user-a",
    saved_at: new Date().toISOString(), connected: true,
    identity: { user_id: "fixture-user-a", company_id: "fixture-company-a", role: "cached-owner" },
    user: { user_id: "fixture-user-a", display_name: "Cached identity must not replace live identity" },
    company: { company_id: "fixture-company-a", company_name: "Cached company label" },
    permissions: ["cached_admin_permission"], roles: ["cached_owner"],
    store_id: "fixture-store-a", stores: [{ store_id: "fixture-store-a", company_id: "fixture-company-a", store_name: "Cached store label" }],
    listing_composer_draft: draft };
  context.readSaasProtectedStateSnapshotFromStorage = () => structuredClone(snapshot);
  context.saasServerNowMs = () => Date.now();
  context.sanitizeSaasDetachedListingProjectDraftsSnapshot = () => [];
  context.sanitizeSaasPendingNewListingProjectRequestSnapshot = () => null;
  context.saasMerchantProjectRouteId = () => "";
  context.publicRuntimeText = (value) => String(value || "");
  context.markSaasMediaJobsAsUntrustedUiCache = () => {};
  vm.runInContext(["saasIsInvalidMarketProductLabel", "saasIsConcreteProductLabel",
    "saasListingDraftHasConcreteProduct", "hydrateSaasProtectedStateFromCache"]
    .map((name) => extractFunction(name)).join("\n"), context);
  const live = { me: { identity: structuredClone(context.state.saasIdentity), user: structuredClone(context.state.saasUser),
    company: structuredClone(context.state.saasCompany) }, stores: structuredClone(context.state.saasStores), storeId: "fixture-store-a" };
  return { context, draft, snapshot, live };
}

test("cached business state requires explicit live identity and store evidence", () => {
  const { context } = cachedDraftHarness();
  Object.assign(context.state, { saasIdentity: null, saasUser: null, saasCompany: null, saasStores: [] });
  assert.equal(run(context, "hydrateSaasProtectedStateFromCache()"), false);
  assert.equal(context.state.saasListingComposerDraft, null);
  assert.equal(context.state.saasIdentity, null);
});

test("matching live account company and store can restore unsent draft without restoring cached authority", () => {
  const { context, draft, live } = cachedDraftHarness();
  const authority = JSON.stringify({ identity: context.state.saasIdentity, user: context.state.saasUser,
    company: context.state.saasCompany, stores: context.state.saasStores,
    permissions: context.state.saasPermissions, roles: context.state.saasRoles });
  context.liveCacheEvidence = live;
  assert.equal(run(context, "hydrateSaasProtectedStateFromCache(liveCacheEvidence)"), true,
    "matching-account unsent edits must survive the authentication boundary repair");
  assert.equal(JSON.stringify(context.state.saasListingComposerDraft), JSON.stringify(draft));
  assert.equal(JSON.stringify({ identity: context.state.saasIdentity, user: context.state.saasUser,
    company: context.state.saasCompany, stores: context.state.saasStores,
    permissions: context.state.saasPermissions, roles: context.state.saasRoles }), authority,
    "snapshot identity permissions roles and store list must not overwrite live server authority");
});

test("cached draft is rejected when selected store differs or lacks live ownership evidence", () => {
  for (const mismatch of ["different-selected-store", "selected-store-not-in-live-stores"]) {
    const { context, live } = cachedDraftHarness();
    if (mismatch === "different-selected-store") {
      live.storeId = "fixture-store-b";
      live.stores = [{ store_id: "fixture-store-b", company_id: "fixture-company-a" }];
    } else {
      live.stores = [{ store_id: "fixture-store-b", company_id: "fixture-company-a" }];
    }
    context.liveCacheEvidence = live;
    assert.equal(run(context, "hydrateSaasProtectedStateFromCache(liveCacheEvidence)"), false, mismatch);
    assert.equal(context.state.saasListingComposerDraft, null, mismatch);
  }
});

test("authenticated refresh completes extended hydration with and without a matching draft cache", async () => {
  for (const restoreCache of [true, false]) {
    const { context, live, draft } = cachedDraftHarness();
    if (!restoreCache) context.readSaasProtectedStateSnapshotFromStorage = () => null;
    const calls = [];
    const restoredOptions = [];
    let completedSnapshots = 0;
    let synchronizationStarted = false;
    context.ensureSaasDemoStoreAndConnection = async () => live.stores[0];
    context.saasAiCeoHistoryRequestContext = () => ({});
    context.optionalSaasFetchFast = async (_endpoint, fallback) => fallback;
    context.saasFetch = async (endpoint) => {
      calls.push(endpoint);
      if (endpoint === "/me") return structuredClone(live.me);
      if (endpoint === "/permissions/me") return { permissions: ["view_report"], roles: ["merchant"] };
      if (endpoint === "/stores") return { stores: structuredClone(live.stores) };
      if (endpoint === "/connections") return { connections: [] };
      if (endpoint.startsWith("/tasks?")) return { tasks: [] };
      if (endpoint.startsWith("/confirmations?")) return { confirmations: [] };
      if (endpoint.startsWith("/reports?")) return { reports: [{ report_id: "LIVE_REPORT" }] };
      throw new Error(`unexpected fixture endpoint: ${endpoint}`);
    };
    context.newestSaasCeoCommand = () => null;
    context.backendSaasCeoCommandFromPayload = () => null;
    context.loadSaasLastCeoCommand = () => null;
    context.retainSaasAiCeoRecentThread = (turns) => turns;
    context.syncSaasAiCeoLatestTurnFromThread = () => null;
    context.consumeSaasStartupRequestedView = () => "product";
    context.fetchSaasMerchantBillingUsage = async () => ({ billing_usage: null });
    context.loadSaasSourceRecords = () => [];
    context.loadSaasMerchantFeedback = () => [];
    context.merchantSafeSaasBillingPlan = (plan) => plan;
    context.activeSaasStore = () => live.stores[0];
    context.merchantSafeSaasOAuthRequests = () => [];
    context.reconcileSaasPendingNewListingProjectRequestFromReports = () => false;
    context.saasListingCloudRecord = () => null;
    // The real refresh and real cache restoration run to completion. These
    // business/rendering effects are only observations, not replacement gates.
    context.restoreSaasListingComposerDraftFromBackendReports = (options) => restoredOptions.push({ ...options });
    context.saveSaasProtectedStateSnapshot = () => { completedSnapshots += 1; };
    context.startSaasAiCeoCrossDeviceSync = () => { synchronizationStarted = true; };
    context.openApp = () => {
      assert.equal(run(context, "shouldDeferSaasProtectedAppReveal()"), false);
      return true;
    };
    context.verifySaasUnpublishedDraftSaveConfirmations = async () => ({ draftSave: new WeakSet(), controlledPublish: new WeakSet() });
    context.verifySaasInventoryLocationConfirmations = async () => new WeakSet();
    for (const name of ["syncSaasOnboardingCompletionFromBackend", "updateSaasAiCeoHistoryPagination", "syncSaasAiCeoCloudDomState",
      "persistSaasAiCeoThread", "scheduleSaasAiCeoThreadBackendSync", "markSaasProductFeedbackLiveIdentity",
      "prepareSaasProductFeedbackScopeAfterIdentity", "hydrateSaasCeoCommandFromBackend", "saveSaasSessionToStorage",
      "markSaasMediaJobsAsCurrentSessionBackendEvidence", "pruneSaasDetachedListingProjectDraftsAgainstBackend",
      "restoreSaasFreshListingCloudProjection", "restoreSaasExpiredListingGeneration", "refreshSaasMerchantProjectStatus",
      "applySaasReportsToActivities", "applySaasDataPacketsToActivities", "resumeSaasUncertainNewListingProjectRequestAfterRefresh"])
      context[name] = () => {};
    await run(context, "refreshSaasState({silent:true})");
    assert.equal(context.state.saasError, "", `extended refresh must finish normally; cache=${restoreCache}`);
    assert.ok(calls.includes("/reports?limit=24"));
    assert.deepEqual(restoredOptions, [{ preferBackendLatest: restoreCache, restoreDetachedDraft: restoreCache }]);
    assert.equal(context.state.saasReports[0].report_id, "LIVE_REPORT");
    assert.equal(JSON.stringify(context.state.saasListingComposerDraft), JSON.stringify(restoreCache ? draft : null));
    assert.equal(completedSnapshots, 2, "both authenticated core and completed extended state are retained");
    assert.equal(synchronizationStarted, true, "the successful post-hydration continuation must be reached");
    assert.equal(context.state.saasLoading, false);
    assert.equal(run(context, "shouldDeferSaasProtectedAppReveal()"), false);
  }
});

test("cold account hint cannot authorize reading prior local conversation cache", () => {
  const context = harness();
  Object.assign(context.state, { saasConnected: false, saasProtectedStateReady: false,
    saasIdentity: null, saasUser: null, saasCompany: null });
  assert.equal(run(context, "shouldReadSaasAccountScopedLocalCache()"), false,
    "lastAccount alone is not current authentication");
  assert.equal(run(context, "loadSaasAiCeoThread().length"), 0,
    "the actual chat reader must not expose the retained prior-account sentinel");
});

test("identity restored from a snapshot cannot reveal the protected workbench", () => {
  const context = harness();
  context.state.saasProtectedStateFromCache = true;
  assert.equal(run(context, "shouldDeferSaasProtectedAppReveal()"), true,
    "cached identity must remain behind the authentication boundary");
  assert.equal(run(context, "shouldReadSaasAccountScopedLocalCache()"), false);
});

test("unfinished authenticated hydration cannot reveal the protected workbench", () => {
  const context = harness();
  context.state.saasProtectedStateReady = false;
  assert.equal(run(context, "shouldDeferSaasProtectedAppReveal()"), true,
    "a partial identity response must not count as ready");
});

test("missing session candidate cannot reveal even if identity objects remain", () => {
  const context = harness();
  context.localStorage.removeItem("session-hint");
  assert.equal(run(context, "shouldDeferSaasProtectedAppReveal()"), true,
    "absence of authentication must fail closed");
  assert.equal(run(context, "loadSaasAiCeoThread().length"), 0,
    "a cleared session must not keep reading old history through leftover identity objects");
});

test("matching live identity with ready state can reveal and restore account cache", () => {
  const context = harness();
  assert.equal(run(context, "shouldDeferSaasProtectedAppReveal()"), false);
  assert.equal(run(context, "shouldReadSaasAccountScopedLocalCache()"), true);
  assert.equal(run(context, "loadSaasAiCeoThread()[0].user_text"), "ACCOUNT_A_PRIVATE_HISTORY_SENTINEL",
    "valid authentication must still restore existing history");
});

test("mixed identity and user accounts cannot reveal or read cached conversations", () => {
  const context = harness();
  context.state.saasUser.user_id = "fixture-user-b";
  assert.equal(run(context, "shouldDeferSaasProtectedAppReveal()"), true,
    "both populated identity objects must refer to the same account");
  assert.equal(run(context, "shouldReadSaasAccountScopedLocalCache()"), false);
});

test("session clear and workbench reset complete even when the app shell is absent", () => {
  const context = harness();
  context.appShell = null;
  context.document.querySelector = () => null;
  context.state.saasToken = "fixture-token-before-cleanup";
  context.localStorage.setItem(context.saasStorageKeys.token, "fixture-local-token");
  context.sessionStorage.setItem(context.saasStorageKeys.token, "fixture-session-token");
  context.localStorage.setItem("snapshot:fixture-user-a", "fixture-protected-snapshot");
  context.localStorage.setItem("snapshot", "fixture-legacy-snapshot");
  const retainedHistory = context.localStorage.getItem("ceo-thread");

  assert.doesNotThrow(() => run(context, "clearSaasSessionFromStorage()"));
  assert.equal(context.saasAccountSessionEpoch, 1);
  assert.equal(context.saasStateRefreshGeneration, 1);
  assert.equal(context.state.saasToken, "");
  assert.equal(context.localStorage.getItem("session-hint"), null);
  assert.equal(context.localStorage.getItem(context.saasStorageKeys.token), null);
  assert.equal(context.sessionStorage.getItem(context.saasStorageKeys.token), null);
  assert.equal(context.localStorage.getItem("snapshot:fixture-user-a"), null);
  assert.equal(context.localStorage.getItem("snapshot"), null);
  assert.equal(context.state.saasProtectedStateReady, false);
  assert.equal(context.document.documentElement.classList.contains("app-auth-pending"), true);
  assert.equal(context.document.documentElement.classList.contains("app-ready"), false);

  context.state.saasProtectedStateReady = true;
  context.state.saasReports = [{ report_id: "PRIVATE_REPORT_BEFORE_RESET" }];
  assert.doesNotThrow(() => run(context, "resetSaasProtectedWorkbenchState()"));
  assert.equal(context.saasAccountSessionEpoch, 2);
  assert.equal(context.saasStateRefreshGeneration, 2);
  assert.equal(context.state.saasProtectedStateReady, false);
  assert.equal(context.state.saasConnected, false);
  assert.equal(context.state.saasIdentity, null);
  assert.equal(context.state.saasUser, null);
  assert.equal(context.state.saasReports.length, 0);
  assert.equal(context.localStorage.getItem("ceo-thread"), retainedHistory,
    "missing UI must neither interrupt credential cleanup nor delete retained conversation history");
});

for (const action of ["clearSaasSessionFromStorage()", "resetSaasProtectedWorkbenchState()", "startSaasAccountSwitch()"]) {
  test(`${action} invalidates an already pending real refresh before it can repopulate identity`, async () => {
    const context = harness();
    const heldStore = deferred();
    const reachedStore = deferred();
    context.ensureSaasDemoStoreAndConnection = () => { reachedStore.resolve(); return heldStore.promise; };
    // The stale-path sentinel stops unrelated downstream reads if the old source
    // wrongly continues. The actual refresh catch/finally still run, exposing its
    // incorrect state transition instead of converting this into a stubbed pass.
    let staleEffects = 0;
    context.syncSaasPublicMvpMode = () => {
      if (context.actionCompleted && context.state.saasConnected) {
        staleEffects += 1;
        throw new Error("fixture-stale-refresh-crossed-auth-boundary");
      }
    };
    const pending = run(context, "refreshSaasState({silent:true})");
    await reachedStore.promise;
    const retainedHistory = context.localStorage.getItem("ceo-thread");
    run(context, action);
    assert.equal(context.appShell.classList.contains("is-hidden"), true,
      "ending or switching an auth context must immediately conceal its workbench");
    assert.equal(context.document.documentElement.classList.contains("app-auth-pending"), true);
    assert.equal(context.state.saasProtectedStateReady, false);
    assert.equal(context.state.saasLoading, false,
      "invalidating the old request must release its busy state for the next login or registration");
    assert.equal(context.localStorage.getItem("ceo-thread"), retainedHistory,
      "ending access must retain the account history for future authenticated restoration");
    context.actionCompleted = true;
    heldStore.resolve({ store_id: "fixture-store-a" });
    let failure;
    try { await pending; } catch (error) { failure = error; }
    assert.equal(staleEffects, 0, "a response from the prior authentication context must be ignored");
    assert.equal(failure, undefined, "invalidated refresh should settle without performing stale effects");
    if (action !== "clearSaasSessionFromStorage()") {
      assert.equal(context.state.saasIdentity, null);
      assert.equal(context.state.saasUser, null);
    }
    if (action === "startSaasAccountSwitch()") assert.equal(context.authOpened, true);
  });
}

for (const identityChange of ["user", "company"]) {
  test(`cached account A business data cannot appear on first reveal after a live ${identityChange} change`, async () => {
    const context = harness();
    const heldExtended = deferred();
    const extendedStarted = deferred();
    const cached = {
      version: "2026-09-01-project-isolation-idempotency-v5", account_key: "fixture-user-a",
      saved_at: new Date().toISOString(), connected: true,
      identity: { user_id: "fixture-user-a", company_id: "fixture-company-a" },
      user: { user_id: "fixture-user-a" }, company: { company_id: "fixture-company-a" },
      store_id: "fixture-store-a", stores: [{ store_id: "fixture-store-a", company_id: "fixture-company-a" }],
      reports: [{ report_id: "ACCOUNT_A_REPORT_SENTINEL", company_id: "fixture-company-a" }],
      media_asset_jobs: [{ job_id: "ACCOUNT_A_MEDIA_SENTINEL", company_id: "fixture-company-a" }],
      merchant_project_status: { snapshot_version: "merchant_project_status_v1", project_id: "ACCOUNT_A_PROJECT_SENTINEL" },
      account_health: { account_id: "ACCOUNT_A_HEALTH_SENTINEL" },
    };
    const live = {
      identity: { user_id: identityChange === "user" ? "fixture-user-b" : "fixture-user-a", company_id: "fixture-company-b" },
      user: { user_id: identityChange === "user" ? "fixture-user-b" : "fixture-user-a" },
      company: { company_id: "fixture-company-b" },
    };
    const liveStores = [{ store_id: "fixture-store-b", company_id: "fixture-company-b" }];
    Object.assign(context.state, { saasIdentity: null, saasUser: null, saasCompany: null,
      saasProtectedStateReady: false, saasProtectedStateFromCache: false, saasConnected: false,
      saasReports: [], saasMediaAssetJobs: [], saasMerchantProjectStatus: null, saasAccountHealth: null });
    context.readSaasProtectedStateSnapshotFromStorage = () => structuredClone(cached);
    context.saasServerNowMs = () => Date.now();
    context.sanitizeSaasDetachedListingProjectDraftsSnapshot = () => [];
    context.sanitizeSaasPendingNewListingProjectRequestSnapshot = () => null;
    context.saasListingDraftHasConcreteProduct = () => false;
    context.saasMerchantProjectRouteId = () => "";
    context.publicRuntimeText = (value) => String(value || "");
    context.markSaasMediaJobsAsUntrustedUiCache = () => {};
    context.ensureSaasDemoStoreAndConnection = async () => liveStores[0];
    context.saasAiCeoHistoryRequestContext = () => ({ scope: "fixture-user-a", epoch: 0 });
    context.isCurrentSaasAiCeoHistoryRequest = () => true;
    context.optionalSaasFetchFast = async (endpoint, fallback) => {
      if (endpoint === "/billing/plans") { extendedStarted.resolve(); return heldExtended.promise; }
      return fallback;
    };
    context.saasFetch = async (endpoint) => {
      if (endpoint === "/me") return structuredClone(live);
      if (endpoint === "/permissions/me") return { permissions: [], roles: [] };
      if (endpoint === "/stores") return { stores: structuredClone(liveStores) };
      if (endpoint === "/connections") return { connections: [] };
      if (endpoint.startsWith("/tasks?")) return { tasks: [] };
      if (endpoint.startsWith("/confirmations?")) return { confirmations: [] };
      if (endpoint.startsWith("/reports?")) return heldExtended.promise;
      throw new Error(`unexpected fixture endpoint: ${endpoint}`);
    };
    context.saasCeoCommandStorageScope = () => context.state.saasUser?.user_id || "fixture-user-a";
    context.newestSaasCeoCommand = () => null;
    context.backendSaasCeoCommandFromPayload = () => null;
    context.loadSaasLastCeoCommand = () => null;
    context.retainSaasAiCeoRecentThread = (turns) => turns;
    context.syncSaasAiCeoLatestTurnFromThread = () => null;
    context.consumeSaasStartupRequestedView = () => "product";
    context.fetchSaasMerchantBillingUsage = async () => ({ billing_usage: null });
    context.verifySaasUnpublishedDraftSaveConfirmations = async () => ({ draftSave: new WeakSet(), controlledPublish: new WeakSet() });
    context.verifySaasInventoryLocationConfirmations = async () => new WeakSet();
    for (const name of ["syncSaasProjectRoute", "syncSaasOnboardingCompletionFromBackend",
      "updateSaasAiCeoHistoryPagination", "syncSaasAiCeoCloudDomState", "persistSaasAiCeoThread",
      "scheduleSaasAiCeoThreadBackendSync", "markSaasProductFeedbackLiveIdentity",
      "saveSaasProtectedStateSnapshot", "prepareSaasProductFeedbackScopeAfterIdentity",
      "hydrateSaasCeoCommandFromBackend"]) context[name] = () => {};
    const reveals = [];
    context.openApp = () => {
      if (run(context, "shouldDeferSaasProtectedAppReveal()")) return false;
      reveals.push(JSON.parse(JSON.stringify({ user: context.state.saasUser, company: context.state.saasCompany,
        ready: context.state.saasProtectedStateReady, fromCache: context.state.saasProtectedStateFromCache,
        reports: context.state.saasReports, media: context.state.saasMediaAssetJobs,
        project: context.state.saasMerchantProjectStatus, health: context.state.saasAccountHealth })));
      return true;
    };
    vm.runInContext(["hydrateSaasProtectedStateFromCache", "reconcileSaasCachedProjectStateForConfirmedAccount"]
      .map((name) => extractFunction(name)).join("\n"), context);
    const pending = run(context, "refreshSaasState({silent:true})");
    try {
      await Promise.race([extendedStarted.promise, pending.then(() => {
        throw new Error(`fixture did not reach extended reads: ${context.state.saasError || "unknown failure"}`);
      })]);
      for (const reveal of reveals) {
        assert.equal(reveal.company.company_id, live.company.company_id);
        assert.equal(reveal.user.user_id, live.user.user_id);
        assert.doesNotMatch(JSON.stringify(reveal), /ACCOUNT_A_(?:REPORT|MEDIA|PROJECT|HEALTH)_SENTINEL/,
          `first protected reveal must not combine live ${identityChange} identity with prior account business data: ${JSON.stringify(reveal)}`);
      }
    } finally {
      // Terminate the synthetic pending refresh through the real account boundary.
      run(context, "resetSaasProtectedWorkbenchState()");
      heldExtended.resolve({ reports: [], billing_plan: null });
      await pending;
    }
  });
}

test("a prior account's delayed 401 cannot refresh or terminate the newly selected account", async () => {
  const context = harness();
  const response = deferred();
  const requestStarted = deferred();
  let refreshAttempts = 0;
  let redirects = 0;
  context.state.saasApiBase = "http://127.0.0.1:0";
  context.fetch = async () => { requestStarted.resolve(); return response.promise; };
  context.recordSaasServerClock = () => {};
  context.refreshSaasBrowserSession = async () => { refreshAttempts += 1; return false; };
  context.redirectToSaasLogin = () => { redirects += 1; return true; };
  context.saasBackendErrorMessage = () => "fixture old session rejected";
  context.saveSaasSessionToStorage = () => {};
  vm.runInContext(["saasFetch", "saasRequestCanRetryAfterSessionRefresh", "shouldAttachSaasBearerToken",
    "ensureSaasDemoSession", "handleSaasUnrecoverableSession"].map((name) => extractFunction(name)).join("\n"), context);
  const pending = run(context, "ensureSaasDemoSession()").then(() => null, (error) => error);
  await requestStarted.promise;
  run(context, "startSaasAccountSwitch()");
  // Stand in for a newly completed login. The old request must not affect this
  // newer context; this does not claim to exercise the login form or backend.
  Object.assign(context.state, { saasProtectedStateReady: true, saasProtectedStateFromCache: false,
    saasConnected: true, saasSessionExpiryHandled: false,
    saasIdentity: { user_id: "fixture-user-b", company_id: "fixture-company-b" },
    saasUser: { user_id: "fixture-user-b" }, saasCompany: { company_id: "fixture-company-b" } });
  context.localStorage.setItem("session-hint", "1");
  response.resolve({ status: 401, ok: false, headers: { get: () => "application/json" },
    text: async () => JSON.stringify({ error: "session expired" }) });
  const failure = await pending;
  assert.equal(refreshAttempts, 0, "a stale 401 must not invoke refresh for the newer browser session");
  assert.equal(redirects, 0, "a stale 401 must not send the new account back to login");
  assert.equal(context.state.saasUser?.user_id, "fixture-user-b");
  assert.equal(run(context, "hasSaasProtectedSessionCandidate()"), true);
  assert.ok(["saas_account_context_changed", "saas_request_context_changed"].includes(failure?.code),
    "the obsolete request must settle as changed context");
});

test("temporary identity verification failure preserves the login hint and unrevealed cache", async () => {
  const context = harness();
  context.state.saasApiBase = "http://127.0.0.1:0";
  context.state.saasProtectedStateFromCache = true;
  context.localStorage.setItem("snapshot:fixture-user-a", "RETAINED_PENDING_EDITOR_FIXTURE");
  const history = context.localStorage.getItem("ceo-thread");
  context.fetch = async () => ({ status: 503, ok: false,
    headers: { get: () => "application/json" },
    text: async () => JSON.stringify({ error: "temporary identity verification unavailable" }) });
  context.recordSaasServerClock = () => {};
  context.saasBackendErrorMessage = () => "fixture temporary identity verification failure";
  context.saveSaasSessionToStorage = () => assert.fail("failed identity must not be persisted as verified");
  vm.runInContext(["saasFetch", "saasRequestCanRetryAfterSessionRefresh", "shouldAttachSaasBearerToken",
    "ensureSaasDemoSession"].map((name) => extractFunction(name)).join("\n"), context);
  await assert.rejects(run(context, "ensureSaasDemoSession()"), (error) => error.status === 503);
  assert.equal(context.localStorage.getItem("session-hint"), "1",
    "temporary failure is not proof that the existing session expired");
  assert.equal(context.localStorage.getItem("snapshot:fixture-user-a"), "RETAINED_PENDING_EDITOR_FIXTURE");
  assert.equal(context.localStorage.getItem("ceo-thread"), history);
  assert.equal(run(context, "shouldDeferSaasProtectedAppReveal()"), true,
    "preserving a retryable session must not reveal cached protected data");
});

test("an obsolete optional history request rejects without reporting a backend outage or applying fallback", async () => {
  const context = harness();
  const heldBody = deferred();
  const readingBody = deferred();
  const warnings = [];
  let fallbacks = 0;
  context.state.saasApiBase = "http://127.0.0.1:0";
  context.historyRequestCurrent = true;
  context.setTimeout = setTimeout;
  context.clearTimeout = clearTimeout;
  context.console = { warn: (message) => warnings.push(message) };
  context.historyFallback = () => { fallbacks += 1; return { turns: [] }; };
  context.recordSaasServerClock = () => {};
  context.fetch = async () => ({ status: 200, ok: true,
    headers: { get: () => "application/json" },
    json: () => { readingBody.resolve(); return heldBody.promise; } });
  vm.runInContext(["saasFetch", "shouldAttachSaasBearerToken", "optionalSaasFetchFast",
    "recordOptionalSaasSoftTimeout"].map((name) => extractFunction(name)).join("\n"), context);
  const pending = run(context, 'optionalSaasFetchFast("/ai-ceo/chat-history?limit=30", historyFallback, 5000, { saasRequestIsCurrent: () => historyRequestCurrent })')
    .then((value) => ({ value }), (error) => ({ error }));
  await readingBody.promise;
  context.historyRequestCurrent = false;
  heldBody.resolve({ turns: [{ user_text: "STALE_HISTORY_SENTINEL" }] });
  const outcome = await pending;
  assert.deepEqual(warnings, [], "intentional context invalidation is not a backend warning");
  assert.equal(outcome.error?.code, "saas_request_context_changed",
    "superseded history must remain cancellation, not a successful empty-history fallback");
  assert.equal(outcome.value, undefined);
  assert.equal(fallbacks, 0);
  assert.equal(context.state.saasOptionalSoftTimeouts?.length || 0, 0);
  assert.equal(context.state.saasSessionExpiryHandled, false);
});

for (const wrapper of ["optionalSaasFetch", "optionalSaasFetchFast"]) {
  test(`${wrapper} preserves account cancellation instead of returning another account's fallback`, async () => {
    const context = harness();
    const heldResponse = deferred();
    const started = deferred();
    const warnings = [];
    context.state.saasApiBase = "http://127.0.0.1:0";
    context.setTimeout = setTimeout;
    context.clearTimeout = clearTimeout;
    context.console = { warn: (message) => warnings.push(message) };
    context.fallbackCalls = 0;
    context.fetch = async () => { started.resolve(); return heldResponse.promise; };
    context.recordSaasServerClock = () => {};
    vm.runInContext(["saasFetch", "shouldAttachSaasBearerToken", wrapper, "recordOptionalSaasSoftTimeout"]
      .map((name) => extractFunction(name)).join("\n"), context);
    const pending = run(context, `${wrapper}("/ai-ceo/chat-history?limit=30", () => { fallbackCalls += 1; return { turns: [] }; })`)
      .then((value) => ({ value }), (error) => ({ error }));
    await started.promise;
    run(context, "startSaasAccountSwitch()");
    heldResponse.resolve({ status: 200, ok: true, headers: { get: () => "application/json" },
      json: async () => ({ turns: [{ user_text: "STALE_ACCOUNT_HISTORY_SENTINEL" }] }) });
    const outcome = await pending;
    assert.equal(outcome.error?.code, "saas_account_context_changed");
    assert.equal(outcome.value, undefined);
    assert.equal(context.fallbackCalls, 0);
    assert.deepEqual(warnings, []);
    assert.equal(context.state.saasUser, null);
    assert.equal(context.state.saasOptionalSoftTimeouts?.length || 0, 0);
  });

  test(`${wrapper} still reports a real 503 and returns its unavailable fallback`, async () => {
    const context = harness();
    const warnings = [];
    context.state.saasApiBase = "http://127.0.0.1:0";
    context.setTimeout = setTimeout;
    context.clearTimeout = clearTimeout;
    context.console = { warn: (message) => warnings.push(message) };
    context.fetch = async () => ({ status: 503, ok: false,
      headers: { get: () => "application/json" }, text: async () => '{"error":"backend_unavailable"}' });
    context.recordSaasServerClock = () => {};
    context.saasBackendErrorMessage = () => "backend_unavailable";
    vm.runInContext(["saasFetch", "shouldAttachSaasBearerToken", wrapper, "recordOptionalSaasSoftTimeout"]
      .map((name) => extractFunction(name)).join("\n"), context);
    const result = await run(context, `${wrapper}("/ai-ceo/chat-history?limit=30", (error) => ({ unavailable: true, status: error.status }))`);
    assert.equal(result.unavailable, true);
    assert.equal(result.status, 503);
    assert.equal(warnings.length, 1, "real outages must not be silently filtered");
    assert.match(warnings[0], /backend_unavailable/);
    assert.equal(context.state.saasSessionExpiryHandled, false);
  });
}

test("successful headers do not authorize a JSON body arriving after the account changed", async () => {
  const context = harness();
  const heldBody = deferred();
  const readingBody = deferred();
  context.state.saasApiBase = "http://127.0.0.1:0";
  context.fetch = async () => ({ status: 200, ok: true,
    headers: { get: () => "application/json" },
    json: () => { readingBody.resolve(); return heldBody.promise; } });
  context.recordSaasServerClock = () => {};
  vm.runInContext(["saasFetch", "shouldAttachSaasBearerToken"]
    .map((name) => extractFunction(name)).join("\n"), context);
  const pending = run(context, 'saasFetch("/me")').then((value) => ({ value }), (error) => ({ error }));
  await readingBody.promise;
  run(context, "startSaasAccountSwitch()");
  heldBody.resolve({ user: { user_id: "STALE_JSON_ACCOUNT" } });
  const outcome = await pending;
  assert.equal(outcome.value, undefined, "no caller may receive the prior account's late JSON payload");
  assert.ok(["saas_account_context_changed", "saas_request_context_changed"].includes(outcome.error?.code));
  assert.equal(context.state.saasIdentity, null);
  assert.equal(context.state.saasUser, null);
});

for (const action of ["clearSaasSessionFromStorage()", "resetSaasProtectedWorkbenchState()", "startSaasAccountSwitch()"]) {
  test(`${action} rejects a core identity response that completes after the account context changed`, async () => {
    const context = harness();
    const heldIdentity = deferred();
    const requestedIdentity = deferred();
    context.ensureSaasDemoStoreAndConnection = async () => ({ store_id: "fixture-store-a" });
    context.saasAiCeoHistoryRequestContext = () => ({ scope: "fixture-user-a", epoch: 0 });
    context.isCurrentSaasAiCeoHistoryRequest = () => true;
    context.optionalSaasFetchFast = async (_endpoint, fallback) => fallback;
    context.saasFetch = async (endpoint) => {
      if (endpoint === "/me") { requestedIdentity.resolve(); return heldIdentity.promise; }
      if (endpoint === "/permissions/me") return { permissions: [], roles: [] };
      if (endpoint === "/stores") return { stores: [] };
      if (endpoint === "/connections") return { connections: [] };
      if (endpoint.startsWith("/tasks?")) return { tasks: [] };
      if (endpoint.startsWith("/confirmations?")) return { confirmations: [] };
      throw new Error(`unexpected fixture endpoint: ${endpoint}`);
    };
    let staleCoreApplications = 0;
    context.syncSaasOnboardingCompletionFromBackend = () => {
      staleCoreApplications += 1;
      // This is a bounded integration seam: real refresh has already assigned
      // core identity here. Stop unrelated business hydration after observing it.
      throw new Error("fixture-stale-core-identity-was-applied");
    };
    const pending = run(context, "refreshSaasState({silent:true})");
    await requestedIdentity.promise;
    run(context, action);
    heldIdentity.resolve({ identity: { user_id: "STALE_CORE_USER", company_id: "fixture-company-a" },
      user: { user_id: "STALE_CORE_USER" }, company: { company_id: "fixture-company-a" } });
    await pending;
    assert.equal(staleCoreApplications, 0, "old core identity must not pass the real refresh guard");
    assert.notEqual(context.state.saasIdentity?.user_id, "STALE_CORE_USER");
    assert.notEqual(context.state.saasUser?.user_id, "STALE_CORE_USER");
    if (action === "startSaasAccountSwitch()") assert.equal(context.authOpened, true);
  });
}
