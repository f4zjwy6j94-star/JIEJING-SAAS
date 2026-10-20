#!/usr/bin/env node
"use strict";

// Offline public HTML contract; no browser session, provider call or live data.
// Runtime recovery of an old selection is covered by test_jiejing_media_deferred_selection.js.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const root = path.resolve(__dirname, "..");
const home = fs.readFileSync(path.join(root, "index.html"), "utf8");
const workbench = fs.readFileSync(path.join(root, "app.html"), "utf8");
const textContent = html => html.replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim();

test("homepage retains the image and video module and distinguishes available images/scripts from unopened video files", () => {
  const article = [...home.matchAll(/<article\b[^>]*>[\s\S]*?<\/article>/g)]
    .map(match => match[0]).find(markup => /<span>图片与视频<\/span>/.test(markup));
  assert.ok(article, "existing image/video module remains visible");
  const visible = textContent(article);
  assert.match(visible, /生成图片与视频脚本/);
  assert.match(visible, /主图、场景图/);
  assert.match(visible, /视频生成尚未开放/);
  assert.match(visible, /脚本[^。；]*不是视频文件/);
});

test("homepage material-package choice offers image candidates and written scripts, not generated video files", () => {
  const option = home.match(/\["先重做素材包",\s*"([^"]+)"/);
  assert.ok(option, "existing material-package choice remains available");
  assert.match(option[1], /主图、场景图/);
  assert.match(option[1], /视频脚本/);
  assert.match(option[1], /视频生成尚未开放/);
  assert.doesNotMatch(option[1], /视频先生成候选/);
});

test("workbench keeps the video entry but disables unopened durations and leaves the image-only default usable", () => {
  const block = [...workbench.matchAll(/<label\b[^>]*>[\s\S]*?<\/label>/g)]
    .map(match => match[0]).find(markup => /id="mediaVideoPresetSelect"/.test(markup));
  assert.ok(block, "video entry is preserved");
  const select = block.match(/<select\b([^>]*)>([\s\S]*?)<\/select>/);
  assert.ok(select, "duration selector is present");
  assert.doesNotMatch(select[1], /\bdisabled\b/, "the image-only default remains selectable");
  const options = [...select[2].matchAll(/<option\b([^>]*)>([\s\S]*?)<\/option>/g)]
    .map(([, attributes, content]) => ({ attributes, text: textContent(content) }));
  const imageOnly = options.find(option => option.text === "不生成视频");
  assert.ok(imageOnly, "image-only option remains present");
  assert.match(imageOnly.attributes, /\bselected\b/);
  assert.doesNotMatch(imageOnly.attributes, /\bdisabled\b/);
  for (const seconds of [6, 10]) {
    const video = options.find(option => option.text.startsWith(`${seconds} 秒产品展示视频`));
    assert.ok(video, `${seconds}-second video entry is retained`);
    assert.match(video.attributes, /\bdisabled\b/, "unopened video cannot be selected");
    assert.match(video.attributes, new RegExp(`\\bvalue="${seconds} 秒产品展示视频"`), "existing value is retained for safe restoration");
    assert.match(video.text, /尚未开放/);
  }
  const visible = textContent(block);
  assert.match(visible, /视频生成尚未开放/);
  assert.match(visible, /入口保留/);
  assert.match(visible, /当前可使用图片生成/);
  assert.match(visible, /脚本[^。；]*不是视频文件/);
});
