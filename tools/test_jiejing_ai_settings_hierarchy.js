"use strict";
// Offline UI fixture: real production renderers, synthetic account states, no API calls.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const http = require("node:http");
const root = path.resolve(__dirname, "..");
const source = fs.readFileSync(path.join(root, "app.js"), "utf8");
function extract(name) {
  const start = source.indexOf(`function ${name}(`);
  assert.ok(start >= 0, name);
  const tail = source.slice(start);
  const end = tail.search(/\n(?:async )?function /);
  return end < 0 ? tail : tail.slice(0, end);
}
const states = ["ready", "not_configured", "storage_recovery_required", "saved_needs_verification", "ready_with_failed_update", "save_failed", "long", "loading"];
function renderFixture(mode = "ready") {
  assert.ok(states.includes(mode));
  const configured = ["ready", "ready_with_failed_update", "long", "loading"].includes(mode);
  const connectionState = ["long", "loading"].includes(mode) ? "ready" : mode;
  const model = mode === "long" ? 'very-long-model-name-'.repeat(9) + '<unsafe>' : "deepseek-v4-pro";
  const active = configured ? { provider_key: "deepseek", model } : null;
  const ctx = { store: mode === "loading" ? null : { store_id: "local-fixture" }, hasPacket: true };
  const readyState = title => ({ title, tone: "green", detail: "本地合成状态，用于验证布局和展开说明；不代表线上检测结果。" });
  const sandbox = {
    state: { saasLoading: mode === "loading", saasSettingsTab: "model", saasModelSettings: { configured, connection_state: connectionState } },
    escapeHtml: value => String(value ?? "").replace(/[&<>"']/g, char => ({"&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;"}[char])),
    saasModelProviderRows: () => [{ provider_key: "deepseek", label: "DeepSeek", supported_live_adapter: true, default_model: "deepseek-v4-pro", default_base_url: "https://api.deepseek.com" }],
    saasActiveModelSecretRef: () => active,
    isSaasMerchantModelConfigured: () => configured,
    isSaasModelConfigured: () => configured,
    saasMerchantWorkbenchContext: () => ctx,
    saasPlatformTrialModelState: () => ({ allowed: !configured }),
    saasPrimaryTextAiState: () => configured ? readyState("账号 AI 已保存") : ({ tone: "amber", title: "等待连接", detail: "请先配置账号 AI。" }),
    saasImageRecognitionState: () => readyState("图片识别服务已连接"),
    saasPublicSearchState: () => ({ tone: "amber", title: "联网搜索暂不可用", detail: "暂时无法访问搜索服务，请稍后重试。" }),
    saasMediaGenerationState: () => readyState("图片和视频已接入"),
    saasModelBlockedReasonText: () => "",
    fetch: () => { throw new Error("UI renderer must not send requests"); },
  };
  vm.createContext(sandbox);
  vm.runInContext(extract("saasModelConnectionAttemptState") + "\n" + extract("renderSaasMerchantModelProviderPanel"), sandbox);
  const panel = vm.runInContext("renderSaasMerchantModelProviderPanel()", sandbox);
  sandbox.saasSettingsTabDefinitions = () => [
    { id: "account", label: "账号与店铺", title: "账号与店铺", panels: [] },
    { id: "model", label: "AI 与素材", title: "AI 与素材", intro: "管理 AI 可用状态、素材生成入口和费用口径。", panels: [panel] },
    { id: "data", label: "店铺数据", title: "店铺数据", panels: [] },
    { id: "governance", label: "团队权限", title: "团队权限", panels: [] },
    { id: "billing", label: "套餐与付款", title: "套餐与付款", panels: [] },
  ];
  vm.runInContext(extract("renderSaasSettingsCleanLayout"), sandbox);
  const layout = vm.runInContext("renderSaasSettingsCleanLayout()", sandbox);
  const html = `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>AI 设置 · 本地布局预览</title><link rel="stylesheet" href="/styles.css"></head>
  <body class="saas-public-mvp" data-view="connect"><div class="app-shell" id="appShell" data-ui-generation="premium-merchant-workbench-v1"><aside class="sidebar"><strong>捷境</strong><p>本地预览</p><p>合成数据</p></aside><main class="main"><section class="view is-active" id="view-connect">${layout}</section></main></div></body></html>`;
  return { panel, html };
}
function test() {
  for (const mode of states) {
    const { panel } = renderFixture(mode);
    const isReady = ["ready", "long", "loading"].includes(mode);
    assert.equal(/class="saas-model-connection-details" open/.test(panel), !isReady, `${mode}: connection issues stay expanded`);
    assert.equal(/class="saas-model-config-details" open/.test(panel), !["ready", "long", "loading", "storage_recovery_required"].includes(mode), `${mode}: preserve safe form defaults`);
    assert.match(panel, /id="saas-model-api-key" type="password" value=""/);
    assert.equal((panel.match(/data-ai-media-capability="/g) || []).length, 4);
    assert.match(panel, /联网搜索暂不可用/);
    for (const action of ["save-model-api-key", "run-model-value-rehearsal", "refresh-merchant-memory"]) assert.match(panel, new RegExp(`data-saas-action="${action}"`));
    assert.ok(panel.indexOf('class="saas-model-config-details"') < panel.indexOf('class="saas-model-capabilities"'));
    assert.doesNotMatch(panel, /class="saas-model-more-tools" open/);
    if (mode === "not_configured") assert.match(panel, /会消耗试用额度/);
    if (mode === "saved_needs_verification") assert.match(panel, /data-saas-action="verify-model-connection"/);
    if (mode === "storage_recovery_required") assert.match(panel, /请联系支持检查恢复/);
    if (mode === "long") { assert.doesNotMatch(panel, /<unsafe>/); assert.match(panel, /&lt;unsafe&gt;/); }
    if (mode === "loading") assert.match(panel, /data-saas-action="save-model-api-key" disabled/);
  }
  console.log(`PASS AI settings hierarchy: ${states.length} account states; controls, escaping, retry and recovery preserved`);
}
if (require.main === module) {
  test();
  if (process.argv.includes("--preview")) {
    http.createServer((req, res) => {
      const url = new URL(req.url, "http://127.0.0.1");
      res.setHeader("Cache-Control", "no-store");
      if (url.pathname === "/styles.css") { res.setHeader("Content-Type", "text/css"); res.end(fs.readFileSync(path.join(root, "styles.css"))); }
      else if (url.pathname === "/") {
        const mode = url.searchParams.get("state") || "ready";
        if (!states.includes(mode)) { res.writeHead(400); return res.end(); }
        res.setHeader("Content-Type", "text/html; charset=utf-8"); res.end(renderFixture(mode).html);
      } else { res.writeHead(404); res.end(); }
    }).listen(9048, "127.0.0.1", () => console.log("Local synthetic preview: http://127.0.0.1:9048/"));
  }
}
module.exports = { renderFixture };
