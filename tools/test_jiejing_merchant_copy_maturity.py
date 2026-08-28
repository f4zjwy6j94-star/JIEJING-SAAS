#!/usr/bin/env python3
"""Guard merchant surfaces from project-owner and implementation copy."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
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
    ):
        assert marker not in APP_HTML

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
    assert 'id="ceoInput" type="text" name="ai_ceo_prompt" aria-label="交给 AI CEO 的问题或商品任务"' in APP_HTML
    assert 'id="ceoInput" type="text" name="ai_ceo_prompt" aria-label="交给 AI CEO 的问题或商品任务"' in APP_JS
    assert ".source-form-grid label:focus-within" in STYLES
    print("PASS jiejing_merchant_copy_maturity")


if __name__ == "__main__":
    main()
