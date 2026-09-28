#!/usr/bin/env python3
"""Guard merchant surfaces from project-owner and implementation copy."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INDEX_HTML = (ROOT / "index.html").read_text(encoding="utf-8")
APP_HTML = (ROOT / "app.html").read_text(encoding="utf-8")
APP_JS = (ROOT / "app.js").read_text(encoding="utf-8")
STYLES = (ROOT / "styles.css").read_text(encoding="utf-8")


def scope(start_marker: str, end_marker: str) -> str:
    start = APP_JS.index(start_marker)
    end = APP_JS.index(end_marker, start + len(start_marker))
    return APP_JS[start:end]


def main() -> None:
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
    assert 'id="ceoInput" type="text" name="ai_ceo_prompt" aria-label="交给 JV AI 的问题或商品任务"' in APP_HTML
    assert 'id="ceoInput" type="text" name="ai_ceo_prompt" aria-label="交给 JV AI 的问题或商品任务"' in APP_JS
    assert ".source-form-grid label:focus-within" in STYLES
    print("PASS jiejing_merchant_copy_maturity")


if __name__ == "__main__":
    main()
