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
