#!/usr/bin/env python3
"""Static guard for the first-order eBay operating loop on the AI CEO cockpit."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    app_js = (ROOT / "app.js").read_text(encoding="utf-8")
    styles = (ROOT / "styles.css").read_text(encoding="utf-8")
    app_html = (ROOT / "app.html").read_text(encoding="utf-8")

    required_app_markers = [
        "function saasFirstOrderLaunchRows",
        "function renderSaasFirstOrderLaunchLoopPanel",
        "data-first-order-launch-loop",
        "首单经营闭环",
        "不用旧 demo 商品、旧图片、旧 SKU",
        "eBay refresh proof",
        "为 0 时不能假装 refresh ready",
        "publish_health_report",
        "confirmation_center_gate",
        "post_publish_cockpit",
        'data-saas-action="focus-publish-intake"',
        'data-saas-action="create-publish-confirmation"',
        'data-saas-action="open-confirm"',
        "这里不触发 OAuth、不扣款、不直接写 eBay",
    ]
    for marker in required_app_markers:
        if marker not in app_js:
            return fail(f"app.js missing first-order loop marker: {marker}")

    required_style_markers = [
        ".saas-first-order-loop",
        ".saas-first-order-head",
        ".saas-first-order-proof-strip",
        ".saas-first-order-grid",
        ".saas-first-order-card.is-red",
        ".saas-first-order-card.is-amber",
        ".saas-first-order-card.is-green",
        ".saas-first-order-boundary",
    ]
    for marker in required_style_markers:
        if marker not in styles:
            return fail(f"styles.css missing first-order loop marker: {marker}")

    if "20260624-ai-ceo-minimal-v2" not in app_html:
        return fail("app.html should bust app.js/styles.css cache after minimal AI CEO simplification")

    cockpit_start = app_js.index("function renderSaasCockpitRealWorkbench")
    cockpit_end = app_js.index("function renderCockpitExperience", cockpit_start)
    cockpit_scope = app_js[cockpit_start:cockpit_end]
    if "renderSaasFirstOrderLaunchLoopPanel(ctx)" in cockpit_scope:
        return fail("first-order loop must stay out of the default AI CEO cockpit; keep it in settings/details")

    loop_start = app_js.index("function saasFirstOrderLaunchRows")
    loop_end = app_js.index("function renderSaasPublishConfirmationIntakePanel", loop_start)
    loop_scope = app_js[loop_start:loop_end].lower()
    forbidden = [
        "auto_publish",
        "skip_confirmation",
        "refresh_token",
        "access_token",
        "client_secret",
        "real_write_allowed_without_confirmation: true",
    ]
    for marker in forbidden:
        if marker in loop_scope:
            return fail(f"first-order loop must not contain unsafe marker: {marker}")

    print("PASS jiejing_first_order_launch_loop_ui")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
