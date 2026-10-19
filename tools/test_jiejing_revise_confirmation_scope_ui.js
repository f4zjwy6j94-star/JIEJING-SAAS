"use strict";

// Scoped deterministic VM regression. No app bootstrap or external I/O.
// Real dispatcher/fetch/guards/narrow readback; synthetic HTTP and UI boundaries.
// No node:test import, directory discovery, subprocess, network, or app bootstrap.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");
const { createHash } = require("node:crypto");

const APP = path.resolve(__dirname, "../app.js");
const sha256 = (bytes) => createHash("sha256").update(bytes).digest("hex");
const sourceBytes = fs.readFileSync(APP);
const EXPECTED_APP_SHA = sha256(sourceBytes);
const source = sourceBytes.toString("utf8");

// Same declaration-boundary convention as the existing 657 suite; no importing
// that suite, no source rewriting, and no fallback implementation.
function extract(name) {
  const starts = [...source.matchAll(new RegExp(`^(?:async )?function ${name}\\(`, "gm"))];
  assert.equal(starts.length, 1, `HARNESS: ${name} must have one declaration`);
  const tail = source.slice(starts[0].index);
  const next = tail.search(/\r?\n(?:async )?function /);
  assert(next > 0, `HARNESS: ${name} must have a following declaration boundary`);
  let declaration = tail.slice(0, next).trim();
  if (name === "refreshSaasState") {
    const constants = declaration.indexOf("\nconst SAAS_PRODUCT_FEEDBACK_ACCOUNT_WIDE_SCOPE");
    assert(constants > 0, "HARNESS: refresh trailing constant boundary unchanged");
    declaration = declaration.slice(0, constants).trim();
  }
  assert(declaration.endsWith("}"), `HARNESS: ${name} declaration boundary unexpected`);
  return declaration;
}

const names = [
  "handleSaasAction",
  "approveFirstSaasConfirmation", "saasConfirmationIdFromActionButton", "saasEbayRecoveryContext", "isSaasEbayRecoveryContextCurrent",
  "rememberSaasEbayExecutionRecovery", "isSaasReadOnlyOAuthSensitiveConfirmation", "isSaasInventoryLocationSensitiveConfirmation",
  "isSaasUniqueCurrentReadOnlyOAuthConfirmation", "isSaasUniqueCurrentUnpublishedDraftOAuthConfirmation", "isSaasUniqueCurrentReadOnlySyncConfirmation",
  "isSaasUniqueCurrentInventoryLocationConfirmation", "isSaasExactInventoryLocationConfirmation", "isSaasUniqueCurrentControlledExistingDraftPublishConfirmation",
  "saasControlledExistingDraftPublishReceipt", "isSaasDomesticBillingRefundConfirmation",
  "reviseSaasConfirmation",
  "refreshSaasRevisedConfirmation",
  "saasCompanyReviseRequestGuard",
  "saasReviseConfirmationAttemptKey",
  "saasRevisedConfirmationMatches",
  "saasReviseConfirmationButtonLabel", "syncSaasReviseConfirmationButtons", "saasReviseConfirmationBlocksApproval",
  "saasFetch",
  "saasRequestCanRetryAfterSessionRefresh",
  "assertSaasAccountSessionCurrent",
  "saasBackendErrorMessage",
  "requireSaasProtectedSessionForAction",
  "hasSaasProtectedSessionCandidate",
  "loadSaasSessionFromStorage",
  "hasSaasPersistentSessionHint",
  "purgeLegacySaasStoredBearerToken",
  "shouldPersistSaasBearerTokenForDev",
  "isSaasPublicMvpMode",
  "shouldAttachSaasBearerToken",
  "recordSaasServerClock",
  "refreshSaasState", "hasSaasProtectedBackendState", "assertSaasLiveIdentityScope",
  "ensureSaasDemoStoreAndConnection", "ensureSaasDemoSession", "saveSaasSessionToStorage",
  "activeSaasStore", "preferredSaasStore", "saasKnownStoreCandidates", "storedSaasStoreId",
  "normalizeSaasRecordStoreId", "saasRecordStoreId", "sortedSaasDataPackets", "saasConnectionsForStoreId",
  "isSaasUnrecoverableSessionError", "optionalSaasFetchFast",
  "verifySaasUnpublishedDraftSaveConfirmations", "verifySaasInventoryLocationConfirmations",
  "isSaasControlledExistingDraftPublishConfirmation", "resolveSaasEbaySubmittedOutcomes",
  "saasEbayStoreRequestGuard", "saasEbayRecoveryCard",
  "resetSaasActiveProjectForStoreSwitch",
  "saasCurrentListingProjectIdentity", "saasNormalizeListingProjectIdentity", "isLegacySampleMediaDraftKey", "saasIsConcreteProductLabel",
  "handleSaasUnrecoverableSession", "invalidateSaasProtectedSessionContext",
];

const context = vm.createContext(Object.create(null), {
  name: "revise-confirmation-R01-pure-vm",
  codeGeneration: { strings: false, wasm: false },
});
function evaluate(text, filename = "R01-harness.cjs") {
  return new vm.Script(text, { filename }).runInContext(context, { timeout: 1000 });
}

evaluate(`
  const observations = { requests: [], renders: 0, toasts: [], dispatched: 0, completed: 0 };
  const state = {
    saasApiBase: "https://synthetic.invalid",
    saasToken: "", saasManualLogout: false, saasSessionExpiryHandled: false,
    saasCompany: { company_id: "company-A" },
    saasIdentity: { company_id: "company-A", user_id: "merchant-A" },
    saasStores: [{ company_id: "company-A", store_id: "store-A", platform: "ebay" }],
    saasConfirmations: [{ company_id: "company-A", store_id: "store-A",
      confirmation_id: "other-card", action_type: "publish_listing", status: "pending" }],
    saasListingComposerDraft: { listing_project_identity: { key: "project-A" } },
    saasError: "", saasLoading: false, view: "confirm", saasEbayRequestEpoch: 0,
  };
  let saasAccountSessionEpoch = 1;
  const saasStorageKeys = { token: "synthetic-token", sessionHint: "synthetic-session", storeId: "synthetic-store" };
  function memoryStorage(entries) {
    const values = new Map(entries);
    return { getItem: key => values.has(key) ? values.get(key) : null,
      setItem: (key, value) => values.set(key, String(value)), removeItem: key => values.delete(key) };
  }
  const localStorage = memoryStorage([[saasStorageKeys.sessionHint, "1"], [saasStorageKeys.storeId, "store-A"]]);
  const sessionStorage = memoryStorage([]);
  const window = { __JIEJING_FORCE_PUBLIC_MVP__: true };
  const document = { buttons: [], documentElement: { classList: { remove() {} } },
    querySelectorAll(selector) { return this.buttons.filter(button => selector.includes('"' + button.dataset.saasAction + '"')); } };
  let saasStateRefreshGeneration = 0;
  let saasBrowserSessionRefreshPromise = null;
  function publicRuntimeText(value = "") { return String(value); } // unrelated display sanitization boundary
  function clearSaasSessionFromStorage() { invalidateSaasProtectedSessionContext(); localStorage.removeItem(saasStorageKeys.sessionHint); }
  function resetSaasProtectedWorkbenchState() { state.saasConfirmations = []; state.saasTasks = []; }
  function openAuth() { observations.authOpened = (observations.authOpened || 0) + 1; }
  function refreshSaasBrowserSession() { observations.forbiddenRefresh = (observations.forbiddenRefresh || 0) + 1; throw new Error("HARNESS: unsafe POST session replay"); }
  let saasVerifiedUnpublishedDraftSaveConfirmations = new WeakSet();
  let saasVerifiedControlledPublishConfirmations = new WeakSet();
  let saasVerifiedInventoryLocationConfirmations = new WeakSet();
  const scenario = { success: false, serverCards: [], serverStores: [], serverConnections: [] };
  let timerSequence = 0;
  const timerTasks = new Map();
  function setTimeout(callback) { const id = ++timerSequence; timerTasks.set(id, callback); return id; }
  function clearTimeout(id) { timerTasks.delete(id); }
  // Synthetic UI/storage/history plumbing only. The full real refresh, its
  // transport, identity checks, store selection, and confirmation verifiers run.
  function saasAccountStorageAliases() { return [state.saasIdentity.user_id]; }
  function saasAiCeoHistoryRequestContext() { return {}; }
  function isCurrentSaasAiCeoHistoryRequest() { return true; }
  function hydrateSaasProtectedStateFromCache() { return false; }
  function fetchSaasMerchantBillingUsage() { return Promise.resolve({}); }
  function merchantSafeSaasBillingPlan(value) { return value; }
  function merchantSafeSaasOAuthRequests(value) { return value || []; }
  function consumeSaasStartupRequestedView() { return state.view; }
  function activeSaasRefreshView() { return state.view; }
  function setView(view) { state.view = view; }
  function isProtectedSaasAppRoute() { return false; }
  function saasListingCloudRecord() { return null; }
  function saasMerchantProjectRouteId() { return ""; }
  function reconcileSaasPendingNewListingProjectRequestFromReports() { return false; }
  function hydrateSaasCeoCommandFromBackend() { return Promise.resolve(null); }
  function refreshSaasMerchantProjectStatus() { return Promise.resolve(); }
  for (const name of ["normalizeSaasCeoCommand", "normalizeSaasAiCeoLatestTurn", "retainSaasAiCeoRecentThread"])
    globalThis[name] = value => value;
  function shouldKeepSaasAiCeoThreadTurn() { return true; }
  for (const name of ["loadSaasAiCeoThread", "loadSaasSourceRecords", "loadSaasMerchantFeedback", "sanitizeSaasDetachedListingProjectDraftsSnapshot"])
    globalThis[name] = () => [];
  for (const name of ["newestSaasCeoCommand", "backendSaasCeoCommandFromPayload", "loadSaasLastCeoCommand", "syncSaasAiCeoLatestTurnFromThread"])
    globalThis[name] = () => null;
  for (const name of ["renderAccountMenu", "syncSaasPublicMvpMode", "renderStoreContext", "renderGlobalLoopWorkbench",
    "invalidateSaasSettingsActionContext", "stopSaasAiCeoCrossDeviceSync", "stopSaasPendingNewListingProjectReconciliation",
    "setSaasAiCeoTaskContextState", "resetSaasProductFeedbackViewState", "resetSaasListingProjectTransientState", "syncSaasProjectRoute",
    "renderSaasCockpitRealWorkbench", "syncSaasOnboardingCompletionFromBackend", "updateSaasAiCeoHistoryPagination",
    "syncSaasAiCeoCloudDomState", "persistSaasLastCeoCommand", "recordSaasCeoCommandSourceRecord", "persistSaasAiCeoThread",
    "scheduleSaasAiCeoThreadBackendSync", "markSaasProductFeedbackLiveIdentity", "saveSaasProtectedStateSnapshot",
    "prepareSaasProductFeedbackScopeAfterIdentity", "markSaasMediaJobsAsCurrentSessionBackendEvidence",
    "pruneSaasDetachedListingProjectDraftsAgainstBackend", "restoreSaasListingComposerDraftFromBackendReports",
    "restoreSaasFreshListingCloudProjection", "restoreSaasExpiredListingGeneration", "startSaasAiCeoCrossDeviceSync",
    "applySaasReportsToActivities", "applySaasDataPacketsToActivities", "resumeSaasUncertainNewListingProjectRequestAfterRefresh",
    "syncAppStartVisibleShellGuard"]) globalThis[name] = () => {};
  function renderSaasBackendPanel() { observations.renders++; }
  function showActionToast(message) { observations.toasts.push(String(message)); }
  async function fetch(url, options) {
    const request = { url: String(url), method: String(options?.method || "GET"),
      body: options?.body ? JSON.parse(options.body) : null };
    observations.requests.push(request);
    if (request.body?.decision === "approve") return { ok: false, status: 409, headers: { get: () => "application/json" }, text: async () => JSON.stringify({ error: "synthetic_approve_conflict" }) };
    if (request.url.endsWith("/decision") && scenario.decisionFault) {
      if (scenario.decisionFault === "network") throw new Error("synthetic unknown POST delivery");
      if (scenario.decisionFault === "json") return { ok: true, status: 201, headers: { get: () => "application/json" }, json: async () => { throw new SyntaxError("synthetic JSON failure"); } };
      if (scenario.decisionFault === "html") return { ok: true, status: 201, headers: { get: () => "text/html" }, text: async () => "synthetic non-JSON response" };
      if (scenario.decisionFault === "mismatch") return { ok: true, status: 201, headers: { get: () => "application/json" }, json: async () => ({ confirmation: { ...scenario.serverCards[0], company_id: "wrong-company", status: "needs_revision" } }) };
      if (/^[0-9]+$/.test(scenario.decisionFault)) return { ok: false, status: Number(scenario.decisionFault), headers: { get: () => "application/json" },
        text: async () => JSON.stringify({ execution_recovery: { secret_exposed: false, automatic_retry_allowed: false, status: "execution_authority_blocked", zero_write_proven: true } }) };
    }
    if (scenario.readFailure && request.url.endsWith("/confirmations?limit=40")) throw new Error("synthetic readback offline");
    if (scenario.holdRoute && request.url.endsWith(scenario.holdRoute)) {
      scenario.holdRoute = "";
      await new Promise(resolve => { scenario.releaseRoute = resolve; });
      if (scenario.fault === "network") throw new Error("synthetic transport failure");
      if (scenario.fault === "409") return { ok: false, status: 409,
        headers: { get: () => "application/json" }, text: async () => JSON.stringify({ execution_recovery: {
          status: "execution_authority_blocked", zero_write_proven: true } }) };
    }
    if (scenario.holdDecision && request.url.endsWith("/decision")) {
      scenario.holdDecision = false;
      await new Promise(resolve => { scenario.releaseDecision = resolve; });
    }
    if (scenario.success) {
      const route = request.url.slice(state.saasApiBase.length);
      if (request.method === "POST") {
        if (!route.endsWith("/decision") || request.body?.decision !== "modify")
          throw new Error("HARNESS: unexpected mutation " + route);
        const id = decodeURIComponent(route.split("/")[2]);
        scenario.serverCards = scenario.serverCards.map(card => card.confirmation_id === id ? { ...card, status: "needs_revision" } : card);
      }
      const payload = route.endsWith("/decision") ? { confirmation: scenario.serverCards.find(card => card.confirmation_id === decodeURIComponent(route.split("/")[2])) } :
        route === "/tasks/task-A" ? { task: { task_id: "task-A", company_id: "company-A", store_id: "store-A", status: scenario.taskStatus || "needs_revision" } } :
        route === "/me" ? { company: { company_id: "company-A" }, user: { user_id: "merchant-A" },
        identity: { company_id: "company-A", user_id: "merchant-A" } } :
        route === "/stores" ? { stores: scenario.serverStores } :
        route === "/connections" ? { connections: scenario.serverConnections } :
        route === "/confirmations?limit=40" ? { confirmations: scenario.serverCards } : {};
      if (route === "/confirmations?limit=40" && scenario.cardMismatch) {
        const modified = { ...payload.confirmations[0] };
        if (scenario.cardMismatch === "missing") payload.confirmations = [];
        else if (scenario.cardMismatch === "duplicate") payload.confirmations = [modified, { ...modified }];
        else { modified[scenario.cardMismatch] = "wrong-value"; payload.confirmations = [modified]; }
      }
      if (route === "/tasks/task-A" && scenario.taskMismatch) payload.task[scenario.taskMismatch] = "wrong-value";
      return { ok: true, status: request.method === "POST" ? 201 : 200, headers: { get: name => name.toLowerCase() === "content-type" ? "application/json" : null },
        json: async () => JSON.parse(JSON.stringify(payload)) };
    }
    // This is a complete in-memory response, not a request to synthetic.invalid.
    // Every attempted request fails closed and naturally settles the action.
    return { ok: false, status: 409,
      headers: { get: name => name.toLowerCase() === "content-type" ? "application/json" : null },
      text: async () => JSON.stringify({ error: "synthetic_conflict",
        execution_recovery: { secret_exposed: false, automatic_retry_allowed: false,
          status: "execution_authority_blocked", zero_write_proven: true } }),
    };
  }
`);
evaluate(names.map(extract).join("\n\n"), "app.js:selected-real-declarations");

evaluate(`
    const originalRevise = reviseSaasConfirmation;
    const originalApprove = approveFirstSaasConfirmation;
    let observedApprove;
    approveFirstSaasConfirmation = function(...args) { observedApprove = originalApprove(...args); return observedApprove; };
    let observedPromise;
    reviseSaasConfirmation = function(...args) {
      observations.dispatched++;
      observedPromise = originalRevise(...args);
      return observedPromise;
    };
`);

async function rejectedCase(label, id, cards) {
  const pending = evaluate(`
    state.saasReviseConfirmationAttempts = new Map();
    observations.requests = []; observations.toasts = [];
    observations.dispatched = 0; observations.completed = 0; observations.renders = 0;
    state.saasConfirmations = ${JSON.stringify(cards)};
    handleSaasAction({ dataset: { saasAction: "revise-confirmation", saasConfirmation: ${JSON.stringify(id)} } });
    if (!observedPromise || typeof observedPromise.then !== "function") {
      throw new Error("HARNESS: real dispatcher did not invoke revise action");
    }
    observedPromise.then(result => { observations.completed++; return result; });
  `);
  let timeout;
  try {
    const result = await Promise.race([
      pending,
      new Promise((_, reject) => { timeout = setTimeout(() => reject(new Error("HARNESS: action did not settle in 5s")), 5000); }),
    ]);
    const observed = JSON.parse(evaluate(`JSON.stringify({ observations, confirmations: state.saasConfirmations })`));
    assert.equal(result, false, "HARNESS: failed or rejected revise must settle false");
    assert.equal(observed.observations.dispatched, 1, "HARNESS: exact action must be dispatched once");
    assert.equal(observed.observations.completed, 1, "HARNESS: exact action must settle once");
    assert.deepEqual(observed.confirmations, cards, "other pending cards remain unchanged");
    assert.equal(sha256(fs.readFileSync(APP)), EXPECTED_APP_SHA, "HARNESS: source changed during R01");
    console.log(JSON.stringify({ case: label, source_sha256: EXPECTED_APP_SHA,
      dispatched: observed.observations.dispatched, completed: observed.observations.completed,
      requests: observed.observations.requests, result }, null, 2));
    // Target RED assertion. The unchanged product currently records one modify
    // request for other-card here; a harness/import/runtime error is not this RED.
    assert.equal(observed.observations.requests.length, 0, `${label}_TARGET: ambiguous or missing explicit card must not send a decision`);
    assert(!observed.observations.toasts.some(text => text.startsWith("已退回补资料")), "no false success receipt");
    console.log(`PASS ${label}`);
  } finally {
    clearTimeout(timeout);
  }
}

async function main() {
  const card = { company_id: "company-A", store_id: "store-A", confirmation_id: "other-card",
    action_type: "publish_listing", status: "pending", task_id: "task-A" };
  await rejectedCase("R01-explicit-missing-id", "missing-card", [card]);
  await rejectedCase("R02-duplicate-id", "other-card", [card, { ...card, company_id: "company-B", store_id: "store-B" }]);
  await rejectedCase("R03-empty-id", "", [{ ...card, confirmation_id: "" }, card]);
  await rejectedCase("R03-no-longer-pending", "other-card", [{ ...card, status: "needs_revision" }]);
  evaluate(`
    observations.requests = []; observations.toasts = []; state.saasError = "";
    state.saasReviseConfirmationAttempts = new Map();
    state.saasConfirmations = ${JSON.stringify([card])};
    state.saasConnections = [{ store_id: "store-A", platform: "ebay", status: "authorized" }];
    scenario.success = true; scenario.serverCards = ${JSON.stringify([card])};
    scenario.serverStores = state.saasStores; scenario.serverConnections = state.saasConnections;
  `);
  const result = await evaluate(`handleSaasAction({ dataset: { saasAction: "revise-confirmation", saasConfirmation: "other-card" } }); observedPromise;`);
  const normal = JSON.parse(evaluate(`JSON.stringify({ state, observations, timers: timerTasks.size })`));
  assert.equal(result, true, "R04 current exact card succeeds");
  assert.equal(normal.state.saasError, "", "R04 real refresh has no hidden harness/read error");
  assert.equal(normal.state.saasConfirmations[0].status, "needs_revision", "R04 real refresh applies returned card");
  assert.equal(normal.observations.requests.filter(request => request.method !== "GET").length, 1, "R04 only exact decision mutation");
  assert.equal(normal.observations.requests[0].url, "https://synthetic.invalid/confirmations/other-card/decision");
  assert.equal(normal.state.saasLoading, false); assert.equal(normal.timers, 0);
  assert(normal.observations.toasts.some(text => text.startsWith("已退回补资料")));
  console.log("PASS R04-current-ebay-real-narrow-readback");
  assert(normal.observations.requests.every(request => /\/confirmations(?:\/|\?)|\/tasks\/task-A$/.test(request.url)),
    "R04N_TARGET: revising one card must not bootstrap or refresh unrelated stores/connections");
  evaluate(`
    observations.requests = []; observations.toasts = []; observations.renders = 0;
    state.saasReviseConfirmationAttempts = new Map();
    state.saasError = ""; state.saasLoading = false;
    state.saasConfirmations = ${JSON.stringify([card])};
    state.saasStores = [{ store_id: "store-A", platform: "ebay" }, { store_id: "store-B", platform: "ebay" }];
    state.saasConnections = state.saasStores.map(store => ({ ...store, status: "authorized" }));
    scenario.serverCards = ${JSON.stringify([card])}; scenario.serverStores = state.saasStores;
    scenario.serverConnections = state.saasConnections; scenario.holdDecision = true;
  `);
  const delayed = evaluate(`handleSaasAction({ dataset: { saasAction: "revise-confirmation", saasConfirmation: "other-card" } }); observedPromise;`);
  assert.equal(evaluate(`typeof scenario.releaseDecision`), "function", "R05 decision reaches deferred HTTP boundary");
  evaluate(`
    localStorage.setItem(saasStorageKeys.storeId, "store-B"); state.saasEbayRequestEpoch++;
    state.saasConfirmations = [{ confirmation_id: "current-B", company_id: "company-A", store_id: "store-B", status: "pending" }];
    state.saasError = "CURRENT-B"; state.saasLoading = true;
    observations.renders = 0; observations.toasts = []; scenario.releaseDecision();
  `);
  await delayed;
  const late = JSON.parse(evaluate(`JSON.stringify({ state, observations })`));
  assert.equal(late.state.saasError, "CURRENT-B", "R05_TARGET: late A success must preserve current B error/state");
  assert.equal(late.state.saasConfirmations[0].confirmation_id, "current-B");
  assert.equal(late.state.saasLoading, true); assert.equal(late.observations.renders, 0);
  assert.equal(late.observations.toasts.length, 0); assert.equal(late.observations.requests.length, 1);
  console.log("PASS R05-store-change-late-success");
  await lateCase("R06-store-late-409", "/decision", "409", "store");
  await lateCase("R06-store-late-network", "/decision", "network", "store");
  await lateCase("R07-store-ABA-success", "/decision", "", "aba");
  await lateCase("R07-store-ABA-error", "/decision", "network", "aba");
  await lateCase("R08-new-global-refresh", "/confirmations?limit=40", "", "refresh");
  await lateCase("R08-readback-store-ABA-error", "/tasks/task-A", "network", "aba");
  await lateCase("R09-new-same-store-selection", "/confirmations?limit=40", "", "interaction");
  await lateCase("R09-replaced-card", "/confirmations?limit=40", "", "replace");
  await normalCompanyCase();
  evaluate(`scenario.success = false; localStorage.setItem(saasStorageKeys.storeId, "store-A");
    state.saasStores = [{ company_id: "company-A", store_id: "store-A", platform: "ebay" }];`);
  await rejectedCase("R11-foreign-company-card", "other-card", [{ ...card, company_id: "company-B" }]);
  await rejectedCase("R11-ebay-missing-store", "other-card", [{ ...card, store_id: "" }]);
  await lateCase("R11-company-change-late-success", "/decision", "", "company");
  await runningTaskCase();
  await doubleClickCase();
  await readbackRetryCase();
  await unknownRetryCase("network");
  await unknownRetryCase("json");
  await unknownRetryCase("html");
  await unknownRetryCase("mismatch");
  await unknownRetryCase("409");
  await unknownRetryCase("403");
  await unknownRetryCase("500");
  await lateCase("R11-same-company-user-switch", "/decision", "", "user");
  await lateCase("R11-company-ABA-network", "/decision", "network", "companyABA");
  await lateCase("R09-project-change", "/decision", "", "project");
  await lateCase("R09-project-ABA", "/confirmations?limit=40", "network", "projectABA");
  await lateCase("R09-view-ABA", "/confirmations?limit=40", "", "viewABA");
  await lateCase("R09-card-fields-edited", "/confirmations?limit=40", "", "fields");
  for (const field of ["missing", "duplicate", "company_id", "store_id", "task_id", "action_type", "status"])
    await mismatchedReadbackCase(field, "");
  for (const field of ["task_id", "company_id", "store_id"]) await mismatchedReadbackCase("", field);
  await approveConflictCase();
  for (const fault of ["", "network", "json", "409", "403"]) await approvalAfterOutcomeCase(fault);
  await independentCardCase();
  await unauthorizedCase();
}

async function independentCardCase() {
  evaluate(`
    document.buttons = []; state.saasReviseConfirmationAttempts = new Map();
    state.saasCompany = { company_id: "company-A" }; state.saasIdentity = { company_id: "company-A", user_id: "merchant-A" };
    state.saasStores = []; localStorage.removeItem(saasStorageKeys.storeId);
    state.saasConfirmations = ["card-A", "card-B"].map(confirmation_id => ({ confirmation_id, company_id: "company-A", action_type: "company_policy_review", status: "pending" }));
    scenario.serverCards = JSON.parse(JSON.stringify(state.saasConfirmations)); scenario.success = true;
    scenario.holdRoute = "/decision"; scenario.fault = ""; scenario.decisionFault = ""; scenario.readFailure = false;
    observations.requests = []; observations.toasts = []; state.saasError = "";
  `);
  const first = evaluate(`handleSaasAction({ dataset: { saasAction: "revise-confirmation", saasConfirmation: "card-A" } }); observedPromise;`);
  assert.equal(evaluate("typeof scenario.releaseRoute"), "function");
  const second = await evaluate(`handleSaasAction({ dataset: { saasAction: "revise-confirmation", saasConfirmation: "card-B" } }); observedPromise;`);
  assert.equal(second, true, "separate card not locked by old in-flight attempt");
  evaluate("scenario.releaseRoute();"); await first;
  assert.equal(evaluate("state.saasReviseConfirmationAttempts.size"), 2, "attempt records scoped by exact card");
  const count = evaluate(`observations.requests.filter(r => r.method === "POST").length`);
  assert.equal(count, 2, "two different cards each sent once");
  evaluate(`state.saasIdentity.user_id = "merchant-B"; invalidateSaasProtectedSessionContext(); state.saasIdentity.user_id = "merchant-A"; invalidateSaasProtectedSessionContext();`);
  await evaluate(`handleSaasAction({ dataset: { saasAction: "revise-confirmation", saasConfirmation: "card-A" } }); observedPromise;`);
  assert.equal(evaluate(`observations.requests.filter(r => r.method === "POST").length`), count, "account ABA retains original attempt; only readback, never resends");
  assert.equal(evaluate("state.saasConfirmations[0].status"), "needs_revision");
  console.log("PASS independent-cards-and-account-ABA-attempt-fence");
}

async function approveConflictCase() {
  evaluate(`
    state.saasReviseConfirmationAttempts = new Map();
    state.saasCompany = { company_id: "company-A" }; state.saasIdentity = { company_id: "company-A", user_id: "merchant-A" };
    state.saasStores = []; localStorage.removeItem(saasStorageKeys.storeId);
    state.saasConfirmations = [{ confirmation_id: "company-card", company_id: "company-A", action_type: "company_policy_review", status: "pending" },
      { confirmation_id: "separate-card", company_id: "company-A", action_type: "company_policy_review", status: "pending" }];
    scenario.serverCards = JSON.parse(JSON.stringify(state.saasConfirmations)); scenario.success = true;
    scenario.cardMismatch = ""; scenario.taskMismatch = ""; scenario.decisionFault = ""; scenario.readFailure = false; scenario.fault = ""; scenario.holdRoute = "";
    observations.requests = []; observations.toasts = []; state.saasError = "";
    document.buttons = [{ dataset: { saasAction: "approve-confirmation", saasConfirmation: "company-card" }, disabled: false },
      { dataset: { saasAction: "approve-confirmation", saasConfirmation: "separate-card" }, disabled: false }];
  `);
  await evaluate(`handleSaasAction({ dataset: { saasAction: "approve-confirmation", saasConfirmation: "separate-card" } }); observedApprove;`);
  assert.equal(evaluate(`observations.requests.filter(request => request.body?.decision === "approve").length`), 1, "R18 positive: genuine approve dispatcher reaches transport on another card");
  evaluate(`observations.requests = []; scenario.holdRoute = "/decision";`);
  const modifying = evaluate(`handleSaasAction({ dataset: { saasAction: "revise-confirmation", saasConfirmation: "company-card" } }); observedPromise;`);
  assert.equal(evaluate("typeof scenario.releaseRoute"), "function");
  assert.equal(evaluate("document.buttons[0].disabled"), true, "R18 real button sync disables the exact conflicting approve button");
  assert.equal(evaluate("document.buttons[1].disabled"), false, "R18 unrelated card button remains available");
  await evaluate(`handleSaasAction({ dataset: { saasAction: "approve-confirmation", saasConfirmation: "company-card" } }); observedApprove;`);
  const oppositeDecisions = evaluate(`observations.requests.filter(request => request.body?.decision === "approve").length`);
  evaluate(`scenario.releaseRoute();`); await modifying;
  assert.equal(oppositeDecisions, 0, "R18_TARGET: pending modify forbids same-card approve POST");
  console.log("PASS R18-modify-inflight-blocks-same-card-approve");
}

async function approvalAfterOutcomeCase(fault) {
  evaluate(`
    document.buttons = [{ dataset: { saasAction: "approve-confirmation", saasConfirmation: "company-card" }, disabled: false },
      { dataset: { saasAction: "approve-confirmation", saasConfirmation: "company-card" }, disabled: true }];
    state.saasReviseConfirmationAttempts = new Map();
    state.saasCompany = { company_id: "company-A" }; state.saasIdentity = { company_id: "company-A", user_id: "merchant-A" };
    state.saasStores = []; localStorage.removeItem(saasStorageKeys.storeId);
    state.saasConfirmations = [{ confirmation_id: "company-card", company_id: "company-A", action_type: "company_policy_review", status: "pending" }];
    scenario.serverCards = JSON.parse(JSON.stringify(state.saasConfirmations)); scenario.success = true;
    scenario.holdRoute = ""; scenario.fault = ""; scenario.decisionFault = ${JSON.stringify(fault)}; scenario.readFailure = ${!fault};
    observations.requests = []; observations.toasts = []; state.saasError = "";
  `);
  await evaluate(`handleSaasAction({ dataset: { saasAction: "revise-confirmation", saasConfirmation: "company-card" } }); observedPromise;`);
  await evaluate(`handleSaasAction({ dataset: { saasAction: "approve-confirmation", saasConfirmation: "company-card" } }); observedApprove;`);
  assert.equal(evaluate(`observations.requests.filter(r => r.body?.decision === "approve").length`), 0, "R18 " + fault + ": unresolved modify blocks opposite decision");
  evaluate(`scenario.decisionFault = ""; scenario.readFailure = false;`);
  await evaluate(`handleSaasAction({ dataset: { saasAction: "revise-confirmation", saasConfirmation: "company-card" } }); observedPromise;`);
  if (fault === "403") {
    assert.equal(evaluate("document.buttons[0].disabled"), false, "R20_TARGET: exact rejection/pending readback releases only revise-owned disabled button");
    assert.equal(evaluate("document.buttons[1].disabled"), true, "R20 pre-disabled button remains disabled");
  }
  await evaluate(`handleSaasAction({ dataset: { saasAction: "approve-confirmation", saasConfirmation: "company-card" } }); observedApprove;`);
  assert.equal(evaluate(`observations.requests.filter(r => r.body?.decision === "modify").length`), 1, "R18 readonly retry never repeats modify");
  assert.equal(evaluate(`observations.requests.filter(r => r.body?.decision === "approve").length`), fault === "403" ? 1 : 0,
    "R19_TARGET: only confirmed rejection plus exact pending readback restores existing approve admission");
  console.log("PASS R18-outcome-approval-fence-" + (fault || "accepted-readback-offline"));
}

async function mismatchedReadbackCase(cardField, taskField) {
  evaluate(`
    state.saasReviseConfirmationAttempts = new Map(); state.saasCompany = { company_id: "company-A" }; state.saasIdentity = { company_id: "company-A", user_id: "merchant-A" };
    state.saasStores = [{ company_id: "company-A", store_id: "store-A", platform: "ebay" }]; localStorage.setItem(saasStorageKeys.storeId, "store-A");
    state.saasConfirmations = [{ confirmation_id: "other-card", company_id: "company-A", store_id: "store-A", task_id: "task-A", action_type: "publish_listing", status: "pending" }];
    state.saasTasks = [{ task_id: "task-A", company_id: "company-A", store_id: "store-A", status: "waiting_confirmation" }];
    scenario.serverCards = JSON.parse(JSON.stringify(state.saasConfirmations)); scenario.success = true; scenario.decisionFault = ""; scenario.holdRoute = "";
    scenario.cardMismatch = ${JSON.stringify(cardField)}; scenario.taskMismatch = ${JSON.stringify(taskField)};
    observations.requests = []; observations.toasts = [];
  `);
  const before = evaluate("JSON.stringify([state.saasConfirmations, state.saasTasks])");
  const result = await evaluate(`handleSaasAction({ dataset: { saasAction: "revise-confirmation", saasConfirmation: "other-card" } }); observedPromise;`);
  assert.equal(result, false); assert.equal(evaluate("JSON.stringify([state.saasConfirmations, state.saasTasks])"), before);
  assert.match(evaluate("state.saasError"), /已提交.*回读尚未确认/);
  assert.equal(evaluate("[...state.saasReviseConfirmationAttempts.values()][0].outcome"), "accepted");
  assert.equal(evaluate("[...state.saasReviseConfirmationAttempts.values()][0].decision.confirmation.status"), "needs_revision");
  assert.equal(evaluate(`observations.requests.filter(request => request.method === "POST").length`), 1);
  assert.equal(evaluate(`saasReviseConfirmationButtonLabel(state.saasConfirmations[0])`), "只读核对退回状态");
  evaluate(`scenario.cardMismatch = ""; scenario.taskMismatch = "";`);
  console.log(`PASS R16-readback-${cardField || "task-" + taskField}-rejects-partial-state`);
}

async function unknownRetryCase(fault) {
  evaluate(`
    state.saasReviseConfirmationAttempts = new Map();
    state.saasConfirmations = [{ company_id: "company-A", confirmation_id: "unknown-card", action_type: "company_policy_review", status: "pending" }];
    scenario.serverCards = JSON.parse(JSON.stringify(state.saasConfirmations)); scenario.success = true;
    scenario.holdRoute = ""; scenario.decisionFault = ${JSON.stringify(fault)};
    observations.requests = []; observations.toasts = []; state.saasError = "";
  `);
  const first = await evaluate(`handleSaasAction({ dataset: { saasAction: "revise-confirmation", saasConfirmation: "unknown-card" } }); observedPromise;`);
  assert.equal(first, false);
  assert.equal(evaluate("[...state.saasReviseConfirmationAttempts.values()][0].outcome"), fault === "403" ? "rejected" : "unknown");
  assert.equal(evaluate("[...state.saasReviseConfirmationAttempts.values()][0].decision"), null);
  evaluate(`scenario.decisionFault = "";`);
  await evaluate(`handleSaasAction({ dataset: { saasAction: "revise-confirmation", saasConfirmation: "unknown-card" } }); observedPromise;`);
  assert.equal(evaluate(`observations.requests.filter(request => request.method === "POST").length`), 1,
    `R15-${fault}_TARGET: unknown POST delivery cannot be retried by another click`);
  assert.equal(evaluate("state.saasConfirmations[0].status"), "pending", "pending readback cannot establish previous POST was not delivered");
  assert(!evaluate(`observations.toasts.some(text => text.startsWith("已退回补资料"))`));
  console.log(`PASS R15-${fault}-retry-read-only`);
}

async function unauthorizedCase() {
  evaluate(`
    state.saasReviseConfirmationAttempts = new Map(); state.saasSessionExpiryHandled = false;
    state.saasCompany = { company_id: "company-A" }; state.saasIdentity = { company_id: "company-A", user_id: "merchant-A" };
    state.saasConfirmations = [{ company_id: "company-A", confirmation_id: "401-card", action_type: "company_policy_review", status: "pending" }];
    scenario.serverCards = JSON.parse(JSON.stringify(state.saasConfirmations)); scenario.decisionFault = "401"; scenario.holdRoute = "";
    observations.requests = []; observations.toasts = []; observations.forbiddenRefresh = 0;
  `);
  const result = await evaluate(`handleSaasAction({ dataset: { saasAction: "revise-confirmation", saasConfirmation: "401-card" } }); observedPromise;`);
  assert.equal(result, false); assert.equal(evaluate("observations.requests.length"), 1);
  assert.equal(evaluate("observations.forbiddenRefresh"), 0); assert.equal(evaluate("state.saasSessionExpiryHandled"), true);
  assert.match(evaluate("state.saasError"), /登录已失效/);
  assert.equal(evaluate("[...state.saasReviseConfirmationAttempts.values()][0].outcome"), "rejected");
  console.log("PASS R12-401-no-session-refresh-no-POST-replay");
}

async function readbackRetryCase() {
  evaluate(`
    state.saasReviseConfirmationAttempts = new Map();
    state.saasConfirmations = [{ company_id: "company-A", confirmation_id: "accepted-card", action_type: "company_policy_review", status: "pending" }];
    scenario.serverCards = JSON.parse(JSON.stringify(state.saasConfirmations)); scenario.success = true;
    scenario.holdRoute = ""; scenario.readFailure = true;
    observations.requests = []; observations.toasts = [];
  `);
  const first = await evaluate(`handleSaasAction({ dataset: { saasAction: "revise-confirmation", saasConfirmation: "accepted-card" } }); observedPromise;`);
  assert.equal(first, false); assert.match(evaluate("state.saasError"), /已提交.*回读尚未确认/);
  evaluate(`scenario.readFailure = false;`);
  const second = await evaluate(`handleSaasAction({ dataset: { saasAction: "revise-confirmation", saasConfirmation: "accepted-card" } }); observedPromise;`);
  assert.equal(evaluate(`observations.requests.filter(request => request.method === "POST").length`), 1,
    "R14_TARGET: accepted modify then readback failure cannot be posted twice");
  assert.equal(second, true); assert.equal(evaluate("state.saasConfirmations[0].status"), "needs_revision");
  console.log("PASS R14-accepted-readback-retry-read-only");
}

async function doubleClickCase() {
  evaluate(`
    state.saasReviseConfirmationAttempts = new Map();
    state.saasCompany = { company_id: "company-A" }; state.saasIdentity = { company_id: "company-A", user_id: "merchant-A" };
    state.saasStores = []; state.saasConnections = []; localStorage.removeItem(saasStorageKeys.storeId);
    state.saasConfirmations = [{ company_id: "company-A", confirmation_id: "attempt-card", action_type: "company_policy_review", status: "pending" }];
    scenario.serverCards = JSON.parse(JSON.stringify(state.saasConfirmations)); scenario.success = true;
    scenario.holdRoute = "/decision"; scenario.fault = ""; scenario.releaseRoute = null;
    observations.requests = []; observations.toasts = [];
  `);
  const first = evaluate(`handleSaasAction({ dataset: { saasAction: "revise-confirmation", saasConfirmation: "attempt-card" } }); observedPromise;`);
  assert.equal(evaluate("typeof scenario.releaseRoute"), "function");
  const second = evaluate(`handleSaasAction({ dataset: { saasAction: "revise-confirmation", saasConfirmation: "attempt-card" } }); observedPromise;`);
  const count = evaluate(`observations.requests.filter(request => request.method === "POST").length`);
  evaluate(`scenario.releaseRoute();`);
  await Promise.all([first, second]);
  assert.equal(count, 1, "R13_TARGET: concurrent double click sends exactly one modify POST");
  assert.equal(evaluate("state.saasConfirmations[0].status"), "needs_revision", "first request still completes");
  console.log("PASS R13-double-click-single-modify");
}

async function runningTaskCase() {
  evaluate(`
    state.saasReviseConfirmationAttempts = new Map();
    state.saasCompany = { company_id: "company-A" }; state.saasIdentity = { company_id: "company-A", user_id: "merchant-A" };
    state.saasStores = [{ company_id: "company-A", store_id: "store-A", platform: "ebay" }];
    localStorage.setItem(saasStorageKeys.storeId, "store-A");
    state.saasConfirmations = [{ confirmation_id: "other-card", company_id: "company-A", store_id: "store-A", action_type: "publish_listing", task_id: "task-A", status: "pending" }];
    state.saasTasks = [{ task_id: "task-A", company_id: "company-A", store_id: "store-A", status: "running" }, { task_id: "untouched-task", status: "queued" },
      { task_id: "task-A", company_id: "company-A", store_id: "store-B", status: "queued", sentinel: "foreign-store-local-task" }];
    scenario.serverCards = JSON.parse(JSON.stringify(state.saasConfirmations)); scenario.taskStatus = "running";
    scenario.holdRoute = ""; scenario.fault = ""; scenario.success = true;
    state.saasError = ""; observations.requests = []; observations.toasts = [];
  `);
  const result = await evaluate(`handleSaasAction({ dataset: { saasAction: "revise-confirmation", saasConfirmation: "other-card" } }); observedPromise;`);
  assert.equal(result, true, "R10T_TARGET: valid running task may remain running after modify per repository contract");
  assert.equal(evaluate("state.saasTasks[0].status"), "running");
  assert.equal(evaluate("state.saasTasks[1].status"), "queued");
  assert.equal(evaluate("state.saasTasks[2].sentinel"), "foreign-store-local-task", "R17_TARGET: exact task ID and company in another store must not be replaced");
  evaluate(`scenario.taskStatus = "";`);
  console.log("PASS R10T-valid-running-task");
}

async function normalCompanyCase() {
  evaluate(`
    state.saasReviseConfirmationAttempts = new Map();
    state.saasStores = []; state.saasConnections = []; localStorage.removeItem(saasStorageKeys.storeId);
    state.saasCompany = { company_id: "company-A" }; state.saasIdentity = { company_id: "company-A", user_id: "merchant-A" };
    state.saasError = ""; state.saasLoading = true;
    state.saasConfirmations = [{ company_id: "company-A", confirmation_id: "company-card", action_type: "company_policy_review", status: "pending" },
      { company_id: "company-A", confirmation_id: "untouched-card", action_type: "company_policy_review", status: "pending" }];
    scenario.success = true; scenario.fault = ""; scenario.holdRoute = "";
    scenario.serverCards = [JSON.parse(JSON.stringify(state.saasConfirmations[0]))];
    observations.requests = []; observations.toasts = []; observations.renders = 0;
  `);
  const result = await evaluate(`handleSaasAction({ dataset: { saasAction: "revise-confirmation", saasConfirmation: "company-card" } }); observedPromise;`);
  const normal = JSON.parse(evaluate("JSON.stringify({ state, observations })"));
  assert.equal(result, true, "R10 company-level exact card works without an eBay store");
  assert.equal(normal.state.saasError, ""); assert.equal(normal.state.saasLoading, true);
  assert.equal(normal.state.saasConfirmations[0].status, "needs_revision");
  assert.equal(normal.state.saasConfirmations[1].status, "pending");
  assert.equal(normal.state.saasStores.length, 0); assert.equal(normal.state.saasConnections.length, 0);
  assert.deepEqual(normal.observations.requests.map(request => [request.method, request.url.replace("https://synthetic.invalid", "")]),
    [["POST", "/confirmations/company-card/decision"], ["GET", "/confirmations?limit=40"]]);
  console.log("PASS R10-company-without-store-preserves-other-card-and-loading");
}

async function lateCase(label, route, fault, change) {
  evaluate(`
    state.saasReviseConfirmationAttempts = new Map();
    state.saasStores = [{ company_id: "company-A", store_id: "store-A", platform: "ebay" }, { company_id: "company-A", store_id: "store-B", platform: "ebay" }];
    scenario.decisionFault = ""; scenario.readFailure = false;
    localStorage.setItem(saasStorageKeys.storeId, "store-A");
    state.saasCompany = { company_id: "company-A" }; state.saasIdentity = { company_id: "company-A", user_id: "merchant-A" };
    state.saasError = ""; state.saasLoading = false; state.view = "confirm";
    state.saasListingComposerDraft = { listing_project_identity: { key: "project-A" } };
    state.saasConfirmations = [{ company_id: "company-A", store_id: "store-A", confirmation_id: "other-card", status: "pending", action_type: "publish_listing", task_id: "task-A" }];
    ${change.startsWith("company") ? 'delete state.saasConfirmations[0].store_id; delete state.saasConfirmations[0].task_id; state.saasConfirmations[0].action_type = "company_policy_review"; state.saasStores = []; localStorage.removeItem(saasStorageKeys.storeId);' : ""}
    scenario.serverCards = JSON.parse(JSON.stringify(state.saasConfirmations)); scenario.success = true;
    scenario.holdRoute = ${JSON.stringify(route)}; scenario.fault = ${JSON.stringify(fault)}; scenario.releaseRoute = null;
    observations.requests = []; observations.renders = 0; observations.toasts = [];
  `);
  const pending = evaluate(`handleSaasAction({ dataset: { saasAction: "revise-confirmation", saasConfirmation: "other-card" } }); observedPromise;`);
  for (let i = 0; i < 30 && evaluate("typeof scenario.releaseRoute") !== "function"; i++) await Promise.resolve();
  assert.equal(evaluate("typeof scenario.releaseRoute"), "function", `${label} reaches real transport boundary`);
  if (change === "store" || change === "aba") evaluate(`
    localStorage.setItem(saasStorageKeys.storeId, "store-B"); resetSaasActiveProjectForStoreSwitch();
    ${change === "aba" ? 'localStorage.setItem(saasStorageKeys.storeId, "store-A"); resetSaasActiveProjectForStoreSwitch();' : ""}
  `);
  if (change === "refresh") evaluate(`saasStateRefreshGeneration++;`);
  if (change === "interaction") evaluate(`saasEbayStoreRequestGuard("store-A", { interaction: true });`);
  if (change === "replace") evaluate(`state.saasConfirmations = state.saasConfirmations.map(card => ({ ...card }));`);
  if (change === "company") evaluate(`state.saasCompany = { company_id: "company-B" }; state.saasIdentity = { company_id: "company-B", user_id: "merchant-B" };`);
  if (change === "user") evaluate(`state.saasIdentity = { company_id: "company-A", user_id: "merchant-B" };`);
  if (change === "companyABA") evaluate(`state.saasCompany = { company_id: "company-B" }; invalidateSaasProtectedSessionContext(); state.saasCompany = { company_id: "company-A" }; invalidateSaasProtectedSessionContext();`);
  if (change === "project") evaluate(`state.saasListingComposerDraft.listing_project_identity.key = "project-B";`);
  if (change === "projectABA") evaluate(`state.saasListingComposerDraft.listing_project_identity.key = "project-B"; state.saasMerchantProjectStatusRequestGeneration = (state.saasMerchantProjectStatusRequestGeneration || 0) + 1; state.saasListingComposerDraft.listing_project_identity.key = "project-A"; state.saasMerchantProjectStatusRequestGeneration++;`);
  if (change === "viewABA") evaluate(`state.view = "cockpit"; state.saasEbayViewEpoch = (state.saasEbayViewEpoch || 0) + 1; state.view = "confirm"; state.saasEbayViewEpoch++;`);
  if (change === "fields") evaluate(`state.saasConfirmations[0].task_id = "new-task";`);
  evaluate(`state.saasError = "CURRENT-SENTINEL"; state.saasLoading = true; observations.renders = 0; observations.toasts = [];`);
  const before = JSON.parse(evaluate("JSON.stringify({ cards: state.saasConfirmations, tasks: state.saasTasks || [], requestCount: observations.requests.length })"));
  evaluate("scenario.releaseRoute();");
  const result = await pending;
  const after = JSON.parse(evaluate("JSON.stringify({ state, observations })"));
  assert.equal(result, false, `${label}_TARGET: stale work must not report success`);
  assert.deepEqual(after.state.saasConfirmations, before.cards, `${label}_TARGET: stale result cannot change current cards`);
  assert.deepEqual(after.state.saasTasks || [], before.tasks, `${label}: stale result cannot change current tasks`);
  assert.equal(after.state.saasError, "CURRENT-SENTINEL", `${label}: stale error suppressed`);
  assert.equal(after.state.saasLoading, true, `${label}: other loading owner preserved`);
  assert.equal(after.observations.renders, 0); assert.equal(after.observations.toasts.length, 0);
  assert.equal(after.observations.requests.length, before.requestCount, `${label}: no continued stale reads or replay`);
  assert.equal(result, false); console.log(`PASS ${label}`);
}

const hardStop = setTimeout(() => { console.error("HARNESS: suite exceeded 25s"); process.exit(2); }, 25000);
main().catch(error => { console.error(error); process.exitCode = 1; }).finally(() => clearTimeout(hardStop));
