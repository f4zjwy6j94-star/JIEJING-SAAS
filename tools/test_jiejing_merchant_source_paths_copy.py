#!/usr/bin/env python3
"""Merchant app access and product-source paths stay honest and compact."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def extract_element(html: str, start_marker: str, end_marker: str) -> str:
    start = html.find(start_marker)
    end = html.find(end_marker, start + len(start_marker))
    if start < 0 or end < 0:
        raise ValueError(f"missing merchant shell boundary: {start_marker} -> {end_marker}")
    return html[start:end]


def main() -> int:
    app_html = (ROOT / "app.html").read_text(encoding="utf-8")
    app_js = (ROOT / "app.js").read_text(encoding="utf-8")

    try:
        access_shell = extract_element(
            app_html,
            '<div class="site-shell is-hidden" id="siteShell">',
            '<div class="onboarding-shell is-hidden" id="onboardingShell">',
        )
    except ValueError as exc:
        return fail(str(exc))

    if '<section class="landing-section' in access_shell:
        return fail("merchant app still embeds a second long-form marketing homepage")
    if access_shell.count("<section") > 2:
        return fail("merchant access shell is not a compact login/onboarding gateway")

    required_access_hooks = (
        'id="siteShell"',
        'id="heroStart"',
        'id="previewProduct"',
        'id="heroCommandText"',
        'id="heroCommandPills"',
        'id="preselectGrid"',
        'id="preselectTitle"',
        'id="preselectCopy"',
        'id="preselectSteps"',
        'id="startSelectedPath"',
        'id="changeLater"',
        'id="skipToApp"',
        'id="openPlans"',
        'id="pricingGrid"',
        'id="pricingDetail"',
        'id="pricingDetailTitle"',
        'id="pricingDetailPrice"',
        'id="pricingDetailDesc"',
        'id="pricingDetailList"',
        'id="pricingStart"',
        'id="pricingCompare"',
        'id="landingEvidencePreview"',
    )
    for marker in required_access_hooks:
        if marker not in access_shell:
            return fail(f"compact access shell removed a required behavior hook: {marker}")

    if not re.search(r'data-open-auth="login"', access_shell):
        return fail("compact access shell is missing login")
    if not re.search(r'data-open-auth="register"', access_shell):
        return fail("compact access shell is missing registration")

    required_source_path_copy = (
        "有真实货源",
        "图片、链接或规格",
        "捷境整理 Listing",
        "还没有货源",
        "AI CEO 给选品建议",
        "找到真实货源后补充商品事实",
    )
    for marker in required_source_path_copy:
        if marker not in app_html:
            return fail(f"merchant source path is unclear: {marker}")

    forbidden_capability_claims = (
        'data-bulk-action="source-1688"',
        'data-source-intake="ai_search"',
        'data-source-intake="api"',
        'data-source-action="run_ai_search"',
        'data-source-action="send_source_to_product"',
        'data-source-action="open_source_api_modal"',
        'class="source-api-binding-card"',
        "AI 帮我找货源",
        "AI 去 1688 匹配",
        "AI 按 eBay 机会词匹配相近货源",
        "开始找货源",
        "生成采购单",
        "绑定采购接口",
        "配置货源 API",
        'value="https://detail.1688.com/offer/..."',
        'value="¥6.80 - ¥9.20"',
        "价格 ¥7.80 起",
        "价格 ¥6.30 起",
    )
    for marker in forbidden_capability_claims:
        if marker in app_html:
            return fail(f"merchant app promises an unimplemented sourcing capability: {marker}")

    for marker in (
        "demoSupplierFactsForDraft",
        "候选 A",
        "AI 找货源模拟",
        "已模拟完成",
        "自动完成演示类目校验",
        "演示已校验",
        "自动生成采购单",
    ):
        if marker in app_js:
            return fail(f"merchant runtime still carries simulated sourcing or verification behavior: {marker}")

    if "function productFactsForDraft" not in app_js or "state.manualProductFacts?.[draft.id]" not in app_js:
        return fail("listing facts must come from the merchant's saved product record")

    print("PASS jiejing_merchant_source_paths_copy")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
