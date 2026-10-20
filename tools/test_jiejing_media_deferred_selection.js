#!/usr/bin/env node
"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");
const source = fs.readFileSync(path.join(__dirname, "../app.js"), "utf8");
function fixture() {
  const select = { value: "6 秒产品展示视频", selectedOptions: [{ disabled: true }] };
  const ctx = { state: { mediaTaskEntry: "single" }, MEDIA_FACT_LOCKS: [],
    document: { querySelector: key => key === "#mediaVideoPresetSelect" ? select : null } };
  vm.createContext(ctx);
  for (const name of ["mediaGenerationTierKey", "mediaQualityModeKey", "mediaVideoDurationSeconds", "readMediaGenerationConfig"]) {
    const begin = source.indexOf(`function ${name}(`);
    assert.ok(begin >= 0);
    const end = source.indexOf("\nfunction ", begin + 1);
    vm.runInContext(source.slice(begin, end), ctx);
  }
  return { ctx, select };
}
test("restored unavailable video option returns to image-only before quoting", () => {
  const { ctx, select } = fixture();
  const config = ctx.readMediaGenerationConfig();
  assert.equal(config.videoDurationSeconds, 0);
  assert.equal(config.videoPreset, "不生成视频");
  assert.equal(select.value, "不生成视频");
});

test("explicit video request remains a video request for rejection by its gate", () => {
  const { ctx, select } = fixture();
  const config = ctx.readMediaGenerationConfig({ videoPreset: "10 秒产品展示视频", videoDurationSeconds: 10 });
  assert.equal(config.videoDurationSeconds, 10);
  assert.equal(config.videoPreset, "10 秒产品展示视频");
  assert.equal(select.value, "6 秒产品展示视频", "do not silently replace a rejected explicit request");
});

test("normal image-only selection remains unchanged", () => {
  const { ctx, select } = fixture();
  select.value = "不生成视频";
  select.selectedOptions = [{ disabled: false }];
  assert.equal(ctx.readMediaGenerationConfig().videoDurationSeconds, 0);
});
