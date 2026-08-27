#!/usr/bin/env python3
"""Merchant-facing pricing and media-point copy stays one coherent contract."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def section(source: str, start: str, end: str) -> str:
    start_index = source.index(start)
    return source[start_index : source.index(end, start_index)]


def main() -> int:
    app = (ROOT / "app.js").read_text(encoding="utf-8")
    app_html = (ROOT / "app.html").read_text(encoding="utf-8")
    index_html = (ROOT / "index.html").read_text(encoding="utf-8")
    settings_module = (ROOT / "assets" / "jiejing-settings-panels.js").read_text(encoding="utf-8")

    public_plan_catalog = section(app, "const planDetails = {", "\n\nconst saasExactReadOnlyOAuthConfirmationButtonBindings")
    billing_summary = section(app, "function renderSaasMerchantBillingPlainSummaryPanel", "\nfunction renderSaasMerchantSubscriptionActivationPanel")
    media_points = section(app, "function renderSaasMerchantMediaCreditsPanel", "\nfunction saasDomesticBillingDateLabel")
    payment = section(app, "function renderSaasMerchantDomesticPaymentPanel", "\nfunction renderSaasMerchantBillingEntitlementPathPanel")
    pricing = section(app, "function renderSaasMerchantPricingModelPanel", "\nfunction renderSaasCeoCockpitStatusStrip")
    merchant_copy = "\n".join((
        public_plan_catalog,
        billing_summary,
        media_points,
        payment,
        pricing,
        settings_module,
        app_html,
        index_html,
    ))

    required = [
        'title: "免费体验"',
        'title: "有店铺"',
        'title: "多店铺"',
        "¥0 / 7 天",
        "20 次捷境托管 AI",
        "不绑卡、不自动续费",
        "免费体验不赠送生图素材点",
        "¥99 / 30 天",
        "1 个店铺 · 2 个席位 · 100 个经营任务",
        "1,000 素材点",
        "¥199 / 30 天",
        "3 个店铺 · 5 个席位 · 500 个经营任务",
        "3,000 素材点",
        "套餐已包含素材点；用完后才需要加购",
        "1,000 点 / ¥10",
        "5,000 点 / ¥50",
        "10,000 点 / ¥100",
        "草稿图 20 点/张",
        "标准图 80 点/张",
        "高清图 250 点/张",
    ]
    for marker in required:
        if marker not in merchant_copy:
            print(f"FAIL merchant pricing copy missing: {marker}")
            return 1

    forbidden = [
        "基础版",
        "运营版",
        "单店版",
        "多店铺版",
        "团队版",
        "套餐只包含捷境软件使用权",
        "套餐只含软件",
        "快速样图",
        "超清图",
        "内部测试",
        "testing points",
        "owner_testing_points",
        "provider 美元",
    ]
    for marker in forbidden:
        if marker.lower() in merchant_copy.lower():
            print(f"FAIL merchant pricing copy exposes stale/internal wording: {marker}")
            return 1

    print("PASS jiejing_merchant_pricing_media_copy")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
