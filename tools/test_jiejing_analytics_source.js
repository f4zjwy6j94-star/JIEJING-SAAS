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
  const window = {location: {hostname: "app.jiejing.shop", pathname: "/", origin: "https://app.jiejing.shop", hash}, navigator: {}, localStorage: storage(), sessionStorage: session, crypto: {randomUUID: () => "synthetic-random-id"}, addEventListener() {}, ...options};
  const document = {readyState: "loading", addEventListener() {}, querySelector: () => null};
  vm.runInNewContext(code, {window, document, localStorage: window.localStorage, URL, fetch: (url, request) => {requests.push(JSON.parse(request.body)); return Promise.resolve();}});
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
