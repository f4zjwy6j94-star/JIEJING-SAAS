const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const html = fs.readFileSync(require('node:path').join(__dirname, '..', 'index.html'), 'utf8');
function section(start, end) {
  const from = html.indexOf(start), to = html.indexOf(end, from);
  assert(from >= 0 && to > from, `missing homepage section: ${start}`);
  return html.slice(from, to);
}
const loadStart = html.includes('let entryBrowserSessionRefreshPromise = null;')
  ? 'let entryBrowserSessionRefreshPromise = null;' : 'async function loadEntryMerchantOnboarding()';
const source = section(loadStart, 'async function saveEntryMerchantOnboarding(')
  + section('async function validateEntrySaasSessionCandidate()', 'function appStageForPath(')
  + section('function isEntrySessionAuthError(error)', 'function setEntryAuthStatus(');

async function scenario(kind) {
  let accessReady = kind === 'fresh', cleared = 0, applied = 0, lockCount = 0;
  const calls = [];
  const reply = (status, data = {}) => ({ status, ok: status >= 200 && status < 300, json: async () => data });
  const c = {
    AbortSignal, console, entryLoggedIn: false, entryMerchantOnboarding: null,
    entrySaasApiUrl: path => `https://app.jiejing.shop${path}`,
    ENTRY_MERCHANT_ONBOARDING_PATH: '/merchant-onboarding/primary-ebay',
    hasEntrySaasSessionCandidate: () => kind !== 'no-hint',
    clearEntrySaasSessionCandidate: () => { cleared++; },
    entryAuthErrorMessage: (data, fallback) => data.error || fallback,
    applyEntryMerchantOnboarding: model => { c.entryMerchantOnboarding = model; applied++; },
    navigator: { locks: { request: async (name, callback) => {
      assert.equal(name, 'jiejing-browser-session-refresh-v1'); lockCount++;
      if (kind === 'other-tab') accessReady = true;
      return callback();
    } } },
    fetch: async (url, options = {}) => {
      const path = new URL(url).pathname;
      calls.push({ path, method: options.method || 'GET' });
      assert.equal(options.credentials, 'include');
      assert(options.signal instanceof AbortSignal, 'session probes must have a bounded cancellation signal');
      if (path === '/auth/refresh') {
        if (kind === 'network') throw new Error('synthetic network outage');
        if (kind === 'temporary') return reply(503, { error: 'temporarily unavailable' });
        if (kind === 'revoked') return reply(401, { error: 'session_refresh_invalid' });
        accessReady = true;
        return reply(200, kind === 'malformed' ? {} : { ok: true, session_refreshed: true, secret_exposed: false });
      }
      if (kind === 'forbidden') return reply(403, { error: 'permission denied' });
      if (path === '/me') return reply(accessReady ? 200 : 401);
      if (!accessReady || kind === 'retry-unauthorized') return reply(401, { error: 'login_required' });
      return reply(200, { merchant_onboarding: { progress: { preferences_saved: true, current_step_key: 'trialStart' } } });
    },
  };
  vm.createContext(c); vm.runInContext(source, c);
  const results = kind === 'concurrent'
    ? await Promise.all([c.validateEntrySaasSessionCandidate(), c.validateEntrySaasSessionCandidate()])
    : [await c.validateEntrySaasSessionCandidate()];
  const refreshes = calls.filter(call => call.path === '/auth/refresh');
  if (['fresh', 'stale', 'concurrent', 'other-tab'].includes(kind)) {
    assert(results.every(result => result.valid), `${kind}: existing login must resume without entering a password`);
    assert.equal(cleared, 0);
    assert.equal(applied, results.length);
    assert.equal(refreshes.length, ['fresh', 'other-tab'].includes(kind) ? 0 : 1);
    if (kind !== 'fresh') assert.equal(lockCount, 1);
  } else if (['revoked', 'retry-unauthorized'].includes(kind)) {
    assert.equal(results[0].valid, false); assert.equal(results[0].expired, true); assert.equal(cleared, 1);
  } else {
    assert.equal(results[0].valid, false); assert.equal(results[0].expired, false, `${kind}: not proof of a revoked login`);
    assert.equal(cleared, 0, `${kind}: must retain the session hint for a safe retry`);
  }
  if (kind === 'no-hint') assert.equal(calls.length, 0, 'visiting the homepage must not silently log in');
  assert(calls.every(call => call.method === 'GET' || (call.path === '/auth/refresh' && call.method === 'POST')));
}
(async () => {
  for (const kind of ['stale', 'fresh', 'concurrent', 'other-tab', 'revoked', 'temporary', 'network', 'forbidden', 'malformed', 'retry-unauthorized', 'no-hint']) await scenario(kind);
  console.log('PASS homepage session restoration: 11 scenarios; no business writes or credential reads');
})().catch(error => { console.error(error.message); process.exitCode = 1; });
