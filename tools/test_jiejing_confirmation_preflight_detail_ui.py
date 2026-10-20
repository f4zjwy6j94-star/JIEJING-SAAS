#!/usr/bin/env python3
"""Static guard for publish confirmation preflight detail UI."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    app_js = (ROOT / "app.js").read_text(encoding="utf-8")
    styles = (ROOT / "styles.css").read_text(encoding="utf-8")

    for marker in [
        "function saasBackendPublishImpact",
        "function saasBackendPublishDecisionGate",
        "function renderSaasPublishCommandSummaryPanel",
        "影响范围",
        "确认要求",
        "安全边界",
        "no_direct_write",
        "fix_action_can_trigger_real_write=false",
        "blocked_before_confirmation",
        "confirmation_required_no_direct_write",
        "发布确认命令摘要",
        "它不会触发 OAuth、不会扣费、不会直接写入 eBay",
        "renderSaasPublishCommandSummaryPanel()",
    ]:
        if marker not in app_js:
            return fail(f"app.js missing confirmation preflight detail marker: {marker}")

    for marker in [
        ".saas-backend-preflight-route",
        ".saas-publish-command-summary",
        ".saas-publish-command-head",
        ".saas-publish-command-grid",
        ".saas-publish-command-grid article.is-red",
        ".saas-publish-command-grid article.is-amber",
        ".saas-publish-command-grid article.is-green",
    ]:
        if marker not in styles:
            return fail(f"styles.css missing confirmation preflight detail marker: {marker}")

    for forbidden in [
        "access_token",
        "refresh_token",
        "client_secret",
        "authorization header",
    ]:
        detail_start = app_js.index("function saasBackendPublishImpact")
        detail_end = app_js.index("function saasBackendPreflightDetailValue", detail_start)
        detail_body = app_js[detail_start:detail_end].lower()
        if forbidden in detail_body:
            return fail(f"preflight detail helpers must not introduce secret-shaped copy: {forbidden}")

    print("PASS jiejing_confirmation_preflight_detail_ui")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
