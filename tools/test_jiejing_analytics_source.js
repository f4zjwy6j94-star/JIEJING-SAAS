"use strict";
const {test} = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const code = fs.readFileSync(path.join(__dirname, "../assets/jiejing-first-party-analytics.js"), "utf8");
const storage = () => {const values = new Map(); return {getItem: key => values.get(key), setItem: (key, value) => values.set(key, value), removeItem: key => values.delete(key)};};
function load(hash, session = storage(), options = {}) {
  const requests = [];
  const {setupWindow, ...browserOptions} = options;
  const window = {location: {hostname: "app.jiejing.shop", pathname: "/", origin: "https://app.jiejing.shop", hash}, navigator: {}, localStorage: storage(), sessionStorage: session, crypto: {randomUUID: () => "synthetic-random-id"}, addEventListener() {}, ...browserOptions};
  if (setupWindow) setupWindow(window);
  const document = {readyState: "loading", addEventListener() {}, querySelector: () => null};
  const sandbox = {window, document, URL, fetch: (url, request) => {requests.push(JSON.parse(request.body)); return Promise.resolve();}};
  Object.defineProperty(sandbox, "localStorage", {get: () => window.localStorage});
  vm.runInNewContext(code, sandbox);
  return {api: window.JiejingAnalytics, requests, session};
}
test("source tag is allowlisted, carried into signup and bounded to a session", () => {
  const first = load("#from-douyin");
  assert.equal(first.api.context().metadata.traffic_source, "douyin");
  first.api.track("page_view", {metadata: {traffic_source: "arbitrary"}});
  assert.equal(first.requests[0].metadata.traffic_source, "douyin");
  assert.equal(load("#pricing", first.session).api.context().metadata.traffic_source, "douyin");
  assert.equal(load("#from-private@example.com").api.context().metadata.traffic_source, undefined);
  first.session.setItem("jiejing_analytics_source_v1", JSON.stringify({source: "douyin", expires_at: 1}));
  assert.equal(load("", first.session).api.context().metadata.traffic_source, undefined);
});
test("explicit internal preview suppresses browser collection without changing business authorization", () => {
  const first = load("#internal-test");
  first.api.track("page_view");
  assert.equal(first.requests.length, 0);
  const next = load("", first.session);
  next.api.track("page_view");
  assert.equal(next.requests.length, 0);
});

test("internal browser setting persists across reloads and can be cancelled", () => {
  const local = storage();
  const first = load("", storage(), {localStorage: local});
  assert.equal(first.api.getInternalBrowserStatus().internal, false);
  assert.equal(first.api.setInternalBrowser(true).ok, true);
  assert.equal(first.api.getInternalBrowserStatus().persistent, true);
  first.api.track("page_view");
  assert.equal(first.requests.length, 0);

  const reload = load("", storage(), {localStorage: local});
  assert.equal(reload.api.getInternalBrowserStatus().internal, true);
  reload.api.track("page_view");
  assert.equal(reload.requests.length, 0);
  assert.equal(reload.api.setInternalBrowser(false).ok, true);
  assert.equal(reload.api.getInternalBrowserStatus().internal, false);
  reload.api.track("page_view");
  assert.equal(reload.requests.length, 1);
});

test("blocked storage reports failure and pauses only the current page", () => {
  const blocked = {getItem() {throw new Error("blocked");}, setItem() {throw new Error("blocked");}, removeItem() {throw new Error("blocked");}};
  const page = load("", storage(), {localStorage: blocked});
  assert.equal(page.api.getInternalBrowserStatus().storage_available, false);
  const enabled = page.api.setInternalBrowser(true);
  assert.equal(enabled.ok, false);
  assert.equal(enabled.internal, true);
  assert.equal(enabled.persistent, false);
  assert.equal(enabled.page_only, true);
  assert.equal(enabled.error, "storage_unavailable");
  page.api.track("page_view");
  assert.equal(page.requests.length, 0);
  assert.equal(page.api.setInternalBrowser(false).ok, false);
  page.api.track("page_view");
  assert.equal(page.requests.length, 0);
});

test("a silently rejected write is not reported as persistent success", () => {
  const local = storage();
  const page = load("", storage(), {localStorage: local});
  const originalWrite = local.setItem;
  local.setItem = () => {};
  const enabled = page.api.setInternalBrowser(true);
  assert.equal(enabled.ok, false);
  assert.equal(enabled.error, "storage_write_not_verified");
  assert.equal(enabled.page_only, true);
  assert.equal(enabled.persistent, false);
  page.api.track("page_view");
  assert.equal(page.requests.length, 0);
  local.setItem = originalWrite;
  assert.equal(page.api.setInternalBrowser(true).ok, true);
  local.removeItem = () => {};
  const cancelled = page.api.setInternalBrowser(false);
  assert.equal(cancelled.ok, false);
  assert.equal(cancelled.internal, true);
  assert.equal(cancelled.error, "storage_write_not_verified");
});

test("a denied localStorage property does not crash the page or fake persistence", () => {
  const page = load("", storage(), {setupWindow(window) {
    Object.defineProperty(window, "localStorage", {get() {throw new Error("SecurityError");}});
  }});
  assert.equal(page.api.getInternalBrowserStatus().storage_available, false);
  assert.equal(page.api.setInternalBrowser(true).ok, false);
  assert.equal(page.api.getInternalBrowserStatus().page_only, true);
  page.api.track("page_view");
  assert.equal(page.requests.length, 0);
});

test("invalid non-boolean settings cannot silently cancel an internal marker", () => {
  const page = load("");
  page.api.setInternalBrowser(true);
  for (const value of [0, "false", null, undefined]) {
    const result = page.api.setInternalBrowser(value);
    assert.equal(result.ok, false);
    assert.equal(result.error, "invalid_internal_browser_setting");
    assert.equal(result.internal, true);
  }
});

test("existing tabs re-read the shared internal marker before each event", () => {
  const local = storage();
  const first = load("", storage(), {localStorage: local});
  const second = load("", storage(), {localStorage: local});
  first.api.setInternalBrowser(true);
  second.api.track("page_view");
  assert.equal(second.requests.length, 0);
  second.api.setInternalBrowser(false);
  first.api.track("page_view");
  assert.equal(first.requests.length, 1);
  const otherBrowser = load("");
  first.api.setInternalBrowser(true);
  otherBrowser.api.track("page_view");
  assert.equal(otherBrowser.requests.length, 1);
});

test("test mode cannot bypass an explicit internal-browser marker", () => {
  const page = load("", storage(), {__JIEJING_ANALYTICS_TEST_MODE__: true});
  page.api.setInternalBrowser(true);
  page.api.track("page_view");
  assert.equal(page.requests.length, 0);
  page.api.setInternalBrowser(false);
  page.api.track("page_view");
  assert.equal(page.requests.length, 1);
});

test("ordinary browsers collect while webdriver and localhost remain excluded", () => {
  const ordinary = load("", storage(), {role: "owner"});
  ordinary.api.track("page_view");
  assert.equal(ordinary.requests.length, 1);
  const automated = load("", storage(), {navigator: {webdriver: true}});
  automated.api.track("page_view");
  assert.equal(automated.requests.length, 0);
  const local = load("", storage(), {location: {hostname: "localhost", pathname: "/", origin: "http://localhost", hash: ""}});
  local.api.track("page_view");
  assert.equal(local.requests.length, 0);
});

test("the existing temporary preview still expires without becoming persistent", () => {
  const first = load("#internal-test");
  first.api.track("page_view");
  assert.equal(first.requests.length, 0);
  assert.equal(first.api.getInternalBrowserStatus().persistent, false);
  first.session.setItem("jiejing_analytics_internal_preview_until_v1", "1");
  const expired = load("", first.session);
  expired.api.track("page_view");
  assert.equal(expired.requests.length, 1);
});

test("storage recovery allows cancelling a current-page-only pause", () => {
  const local = storage();
  const originalWrite = local.setItem;
  local.setItem = () => {throw new Error("QuotaExceededError");};
  const page = load("", storage(), {localStorage: local});
  assert.equal(page.api.setInternalBrowser(true).ok, false);
  local.setItem = originalWrite;
  const result = page.api.setInternalBrowser(false);
  assert.equal(result.ok, true);
  assert.equal(result.page_only, false);
  page.api.track("page_view");
  assert.equal(page.requests.length, 1);
});
