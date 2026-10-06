#!/usr/bin/env python3
"""Guard merchant surfaces from project-owner and implementation copy."""

from __future__ import annotations

from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
INDEX_HTML = (ROOT / "index.html").read_text(encoding="utf-8")
APP_HTML = (ROOT / "app.html").read_text(encoding="utf-8")
APP_JS = (ROOT / "app.js").read_text(encoding="utf-8")
STYLES = (ROOT / "styles.css").read_text(encoding="utf-8")


def scope(start_marker: str, end_marker: str) -> str:
    start = APP_JS.index(start_marker)
    end = APP_JS.index(end_marker, start + len(start_marker))
    return APP_JS[start:end]


def validate_publication_capability_render() -> None:
    script = r'''
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('app.js', 'utf8').replace(/\r\n/g, '\n');
function definition(name) {
  const start = source.indexOf(`function ${name}(`);
  assert(start >= 0, `missing real renderer/helper: ${name}`);
  const next = source.indexOf('\nfunction ', start + 1);
  assert(next > start, `missing function boundary: ${name}`);
  return source.slice(start, next);
}
const code = ['saasListingPublicationCapabilityView', 'isSaasRealPlatformWritesEnabled', 'ensureSaasConfirmScaffold'].map(definition).join('\n');
assert(definition('renderSaasConfirmPanel').includes('saasListingPublicationCapabilityView('), 'confirmation summary must use the same publication projection');
const cases = [
  [{real_platform_writes_enabled:false, controlled_existing_draft_publish_enabled:true}, 'enabled', '通过 eBay API 正式发布'],
  [{real_platform_writes_enabled:true, controlled_existing_draft_publish_enabled:false}, 'enabled', '通过 eBay API 正式发布'],
  [{controlled_existing_draft_publish_enabled:true}, 'enabled', '通过 eBay API 正式发布'],
  [{real_platform_writes_enabled:false, controlled_existing_draft_publish_enabled:false}, 'disabled', '当前发布通道未启用'],
  [null, 'unknown', '发布状态待核对'],
  [{}, 'unknown', '发布状态待核对'],
  [{real_platform_writes_enabled:false}, 'unknown', '发布状态待核对'],
  [{real_platform_writes_enabled:'true', controlled_existing_draft_publish_enabled:'false'}, 'unknown', '发布状态待核对'],
];
for (const [adapter, status, expected] of cases) {
  const before = JSON.stringify(adapter);
  const view = {innerHTML:''};
  const sandbox = {
    state: {saasEbayWriteAdapter:adapter},
    document: {querySelector: selector => selector === '#view-confirm' ? view : null},
    isSaasPublicMvpMode: () => true,
    escapeHtml: value => String(value).replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char])),
    jiejingTrustedTemplate: () => (parts, ...values) => parts.reduce((text, part, i) => text + part + (values[i] ?? ''), ''),
  };
  vm.createContext(sandbox);
  vm.runInContext(code, sandbox);
  const result = vm.runInContext('saasListingPublicationCapabilityView()', sandbox);
  assert.equal(result.status, status);
  vm.runInContext('ensureSaasConfirmScaffold()', sandbox);
  assert(view.innerHTML.includes(expected), `rendered ${status}: expected ${expected}`);
  assert(!view.innerHTML.includes('eBay 正式发布暂未开放'));
  assert(!view.innerHTML.includes('real writes'));
  assert(view.innerHTML.includes('确认'), 'confirmation boundary must remain visible');
  assert.equal(JSON.stringify(sandbox.state.saasEbayWriteAdapter), before, 'display must not mutate backend flags');
  assert.equal(vm.runInContext('isSaasRealPlatformWritesEnabled()', sandbox), adapter?.real_platform_writes_enabled === true, 'broad-write permission helper must remain separate');
}
console.log('PASS publication capability real renderer: 8 cases; permissions unchanged');
'''
    result = subprocess.run(["node", "-"], input=script, text=True, encoding="utf-8", cwd=ROOT, capture_output=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    print(result.stdout.strip())


def main() -> None:
    validate_publication_capability_render()
    for obsolete_publication_claim in (
        "真实发布、退款、改价、广告和客服发送仍然关闭",
        "发布、退款、改价、广告执行和客服发送仍然关闭",
        "仅可保存未公开草稿 · 公开发布仍关闭",
        "确认后也只记录受控交接",
        "确认中心只会记录受控交接，不会写入 eBay",
        "当前真实平台写入关闭",
    ):
        assert obsolete_publication_claim not in APP_JS + APP_HTML, obsolete_publication_claim

    for marker in (
        "为什么要做捷境",
        "不要一开始做“大而全”",
        "底层逻辑",
        "AssetManifest",
    ):
        assert marker not in APP_HTML

    assert "捷境 eBay-first AI CEO SaaS · 高风险动作必须经过确认中心。" not in INDEX_HTML

    settings = scope("function renderSaasSettingsReadableMap", "function renderSaasSettingsOneGlanceStrip")
    for marker in (
        "普通商家只看",
        "内测阶段",
        "不展示技术排查和部署细节",
        "旧 demo",
        "商家能理解的一句话",
    ):
        assert marker not in settings

    assert "商家能理解的一句话" not in APP_JS
    for marker in (
        "AssetManifest",
        "体检证据包",
        "<span>确认门禁</span>",
        "<span>真实动作门禁</span>",
        ">查看证据包</button>",
    ):
        assert marker not in APP_JS

    workbench = scope("function renderSaasWorkbenchTruthPanel", "function renderSaasAccountHealthPanel")
    for marker in (
        "首页、同步面板、店铺资料、AI CEO 报告和确认中心会以捷境后端返回结果为准",
        "刷新真实结果",
        "/reports 已读取",
        "/confirmations 已读取",
        "真实 API 来源",
    ):
        assert marker not in workbench

    for marker in (
        '<strong>${escapeHtml(ctx.latestPacket?.packet_id || "waiting")}</strong>',
        "<strong>${escapeHtml(sourcePacket)}</strong>",
        "只展示证据标识，不展示敏感凭证",
    ):
        assert marker not in APP_JS

    account_health = scope("function renderSaasAccountHealthPanel", "function renderSaasSettingsStatusCards")
    for marker in (
        "缺 store_profile 或官方 packet",
        "eBay 官方只读 packet",
        "Seller 状态",
        "selling limits",
        "事故模式",
    ):
        assert marker not in account_health

    merchant_evidence = scope("function renderSaasMerchantEvidencePanel", "function saasModelProviderRows")
    assert "<strong>${escapeHtml(packetId)}</strong>" not in merchant_evidence
    assert 'id="ceoInput" type="text" name="ai_ceo_prompt" aria-label="交给 AI CEO 的问题或商品任务"' in APP_HTML
    assert 'id="ceoInput" type="text" name="ai_ceo_prompt" aria-label="交给 AI CEO 的问题或商品任务"' in APP_JS
    assert ".source-form-grid label:focus-within" in STYLES
    print("PASS jiejing_merchant_copy_maturity")


if __name__ == "__main__":
    main()
