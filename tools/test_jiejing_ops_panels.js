"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const {test} = require("node:test");
const window = {};
vm.runInNewContext(fs.readFileSync(path.join(__dirname, "../assets/jiejing-ops-panels.js"), "utf8"), {window});
const panels = window.JiejingOpsPanels;

test("blocked, negative and unknown statuses never receive ready styling", () => {
  for (const status of ["private_beta_ready_public_launch_blocked", "not_ready", "incomplete", "unverified_success", "unknown", "<script>ready</script>"]) {
    const html = panels.renderOwnerLaunchControlPanel({status});
    assert.doesNotMatch(html, /ops-reliability-item is-ready/, status);
    assert.doesNotMatch(html, /<script>/);
  }
  assert.match(panels.renderOwnerLaunchControlPanel({status: "blocked"}), /is-critical/);
  assert.match(panels.renderOwnerLaunchControlPanel({status: "ready"}), /is-ready/);
});

test("runtime uses canonical health evidence, never the overall launch gate", () => {
  const html = panels.renderRuntimeSecurityPanel({status: "private_beta_ready_public_launch_blocked", evidence: {operational: {status: "ready"}, edge: {status: "blocked"}}});
  assert.doesNotMatch(html, /private_beta_ready_public_launch_blocked/);
  assert.match(html, /is-ready/);
  assert.match(html, /is-critical/);
  assert.doesNotMatch(panels.renderRuntimeSecurityPanel({status: "ready"}), /is-ready/);
});

test("backup overall readiness cannot stand in for independent PITR proof", () => {
  const html = panels.renderBackupRecoveryPanel({evidence: {backup: {status: "ready"}}});
  assert.match(html, /is-ready/);
  assert.match(html, /独立.*PITR.*证据/);
  assert.equal((html.match(/ops-reliability-item is-ready/g) || []).length, 1);
});

test("frontend asset identity is not presented as an applied source commit", () => {
  const html = panels.renderLaunchAlignment({ops_console_evidence: {release: {frontend_asset_version: "theme-resource-v1"}}});
  assert.match(html, /商家前端资源标识/);
  assert.match(html, /theme-resource-v1/);
  assert.match(html, /不是 Git 提交号/);
  assert.doesNotMatch(html, /当前代码版本/);
  assert.match(html, /not_connected/);
});

test("edge cutover preparation remains blocked without pretending the live site is down", () => {
  const html = panels.renderRuntimeSecurityPanel({ops_console_evidence: {runtime: {status: "ready", edge_status: "blocked"}}});
  assert.match(html, /域名与回调切换预检/);
  assert.match(html, /不能用来判断网站当前是否可访问/);
  assert.doesNotMatch(html, /<strong>公网边界<\/strong>/);
  assert.match(html, /is-critical/);
  assert.match(html, /title="blocked"/);
  assert.equal((html.match(/ops-reliability-item is-ready/g) || []).length, 1);
});

test("independent approval records do not override current production readiness", () => {
  const control = {status: "private_beta_ready_public_launch_blocked", ops_console_evidence: {readiness: {production_ready: true}}};
  const current = panels.renderLaunchAlignment(control);
  const workflow = panels.renderOwnerLaunchControlPanel(control);
  assert.match(current, /is-ready/);
  assert.match(workflow, /运营复核与交接记录/);
  assert.match(workflow, /复核流程状态/);
  assert.match(workflow, /不等于当前服务故障/);
  assert.match(workflow, /private_beta_ready_public_launch_blocked/);
  assert.match(workflow, /is-critical/);
  assert.doesNotMatch(workflow, /<strong>总体门禁<\/strong>/);
});

test("applied source identity needs an exact runtime match and preserves history", () => {
  const release = {source_commit: "a".repeat(40), production_deployment_status: "ready", receipt_matches_running_build: true, deployment_verified_at: "2026-10-10T00:00:00Z"};
  const html = panels.renderLaunchAlignment({ops_console_evidence: {release}});
  assert.match(html, /运行中的源码版本/);
  assert.match(html, /a{40}/);
  assert.match(html, /已应用回执与运行镜像源码一致/);
  assert.match(html, /版本绑定历史证据/);
  const mismatch = panels.renderLaunchAlignment({ops_console_evidence: {release: {...release, receipt_matches_running_build: false}}});
  assert.doesNotMatch(mismatch, /已应用回执与运行镜像源码一致/);
  assert.match(mismatch, /尚未接入与运行镜像一致/);
});
