// Exercise the real homepage login request with synthetic browser/network boundaries.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const html = fs.readFileSync(require('node:path').join(__dirname, '..', 'index.html'), 'utf8');
function section(start, end) {
  const from = html.indexOf(start);
  const to = html.indexOf(end, from);
  assert(from >= 0 && to > from, `missing homepage section: ${start}`);
  return html.slice(from, to);
}
const apiSource = section('function entrySaasApiBase()', 'function entryGuideChoiceCode(');
const loginSource = section('async function submitEntryAuth(mode)', 'function showEntryLogin()');

async function loginDestination({ page, stored = '', meta = '', storageBlocked = false, expected }) {
  const calls = [], errors = [];
  const location = new URL(page);
  const context = {
    URL, URLSearchParams, console,
    window: { location },
    localStorage: { getItem() { if (storageBlocked) throw new Error('storage unavailable'); return stored; } },
    document: { querySelector: () => ({ content: meta, value: '' }) },
    readEntryAuthCredentials: () => ({ email: 'audit@example.test', password: 'synthetic-password', company: '' }),
    isValidEntryEmail: () => true, setEntryAuthPending() {}, setEntryAuthStatus() {}, showToast: value => errors.push(value),
    entryAuthErrorMessage: () => 'synthetic-error', saveEntryAuthSession() {}, warmWorkspaceAssets() {},
    continueAfterLogin: async () => {},
    fetch: async (url, options) => { calls.push({ url, options }); return { ok: true, json: async () => ({}) }; },
  };
  vm.createContext(context);
  vm.runInContext(apiSource + '\n' + loginSource, context);
  await context.submitEntryAuth('login');
  assert.equal(calls.length, 1, `login did not reach its safe endpoint: ${errors.join(';')}`);
  assert.equal(calls[0].url, `${expected}/auth/login`, 'homepage login must not follow an untrusted API override');
  assert.equal(calls[0].options.credentials, 'include');
  assert.equal(JSON.parse(calls[0].options.body).email, 'audit@example.test');
}

(async () => {
  for (const override of ['https://attacker.invalid', 'http://127.0.0.1:8788', '//attacker.invalid', 'https://app.jiejing.shop.attacker.invalid']) {
    await loginDestination({ page: `https://app.jiejing.shop/?saasApiBase=${encodeURIComponent(override)}`, expected: 'https://app.jiejing.shop' });
  }
  await loginDestination({ page: 'https://app.jiejing.shop/', stored: 'https://attacker.invalid', expected: 'https://app.jiejing.shop' });
  await loginDestination({ page: 'https://app.jiejing.shop/', meta: 'https://attacker.invalid', expected: 'https://app.jiejing.shop' });
  await loginDestination({ page: 'https://app.jiejing.shop/', storageBlocked: true, expected: 'https://app.jiejing.shop' });
  await loginDestination({ page: 'https://localhost.attacker.invalid/?saasApiBase=https://other.invalid', expected: 'https://localhost.attacker.invalid' });
  await loginDestination({ page: 'http://127.0.0.1:9034/?saasApiBase=http://127.0.0.1:8788', expected: 'http://127.0.0.1:8788' });
  await loginDestination({ page: 'http://localhost:9034/', storageBlocked: true, expected: 'http://localhost:9034' });
  console.log('PASS homepage auth destination boundary: 10 real-login scenarios; external requests=0');
})().catch(error => { console.error(error.message); process.exitCode = 1; });
