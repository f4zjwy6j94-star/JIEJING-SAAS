#!/usr/bin/env python3
"""Static merchant-UX contract for WeChat Pay subscription checkout."""

from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    app = (ROOT / "app.js").read_text(encoding="utf-8")
    settings_panels = (ROOT / "assets" / "jiejing-settings-panels.js").read_text(encoding="utf-8")
    styles = (ROOT / "styles.css").read_text(encoding="utf-8")
    required_app = [
        "saasDomesticBillingCheckout: null",
        "function saasDomesticBillingIdempotencyKey",
        "async function runSaasDomesticBillingCreateOrder",
        "async function runSaasDomesticBillingContinueOrder",
        "async function runSaasDomesticBillingQueryOrder",
        "async function runSaasDomesticBillingCloseOrder",
        "async function runSaasDomesticBillingRefundRequest",
        "function scheduleSaasDomesticBillingPoll",
        "merchant_confirmed_renewal_v1",
        "继续上一笔付款",
        "续购当前套餐",
        "当前套餐有效期",
        "online && !entitlementActive && !checkout && !pendingPayment",
        "online && pendingPayment && !checkout",
        "attempt >= 120",
        "checkout_expired",
        "二维码已过期",
        'data-saas-action="domestic-billing-create-order"',
        'data-saas-action="domestic-billing-select-plan"',
        'data-domestic-plan-key="operator"',
        'data-domestic-plan-key="team"',
        'data-saas-action="domestic-billing-query-order"',
        'data-saas-action="domestic-billing-close-order"',
        'data-saas-action="domestic-billing-refund-request"',
        "微信扫码开通",
        "付款成功后自动开通",
        "最近订单",
        "订单号：",
        "支付记录已保存；订单记录不等同税务发票。",
        "微信扫码，不输入银行卡",
        "单次购买 30 天",
        "按已付款订单人工受理",
        'data-global-flow-view="service"',
        "merchant_billing_customer_trust_packet_v2",
        "payment_mode=",
        "wechat_native_qr",
        "merchant_confirmed_one_time_30_day",
        "微信扫码、到账确认、权益开通和自主续购",
        "后端验签确认后开通",
        "四档套餐是 30 天软件使用权",
        "qr_image_data_url",
        '"idempotency-key"',
        "function renderSaasMerchantMediaCreditsPanel",
        "素材点余额",
        "购买素材点",
        'data-media-credit-pack-key=',
        'data-media-credit-checkout="merchant_media_points_checkout_v1"',
        'item?.purchase_type === "media_points"',
        'item?.purchase_type !== "media_points"',
        "到账后素材点会自动进入当前账号空间",
        "不会改变软件套餐，也不会自动续费",
        "生成前预估，完成后按实际结算",
        "商家自带模型",
        "不消耗素材点",
        "1 个店铺 · 2 个席位 · 100 个经营任务",
        "3 个店铺 · 5 个席位 · 500 个经营任务",
        "5 个店铺 · 5 个席位 · 1500 个经营任务",
        "选择要开通的软件套餐",
        "const selectedCheckoutPlanKey = [\"starter\", \"operator\", \"team\"]",
    ]
    required_styles = [
        ".saas-domestic-checkout",
        ".saas-domestic-checkout-qr",
        ".saas-domestic-order-list",
        ".saas-domestic-order-actions",
    ]
    for marker in required_app:
        if marker not in app:
            print(f"FAIL app.js missing merchant billing marker: {marker}")
            return 1
    for marker in required_styles:
        if marker not in styles:
            print(f"FAIL styles.css missing merchant billing marker: {marker}")
            return 1
    renderer_start = app.index("function renderSaasMerchantDomesticPaymentPanel")
    renderer_end = app.index("\nfunction renderSaasMerchantBillingEntitlementPathPanel", renderer_start)
    renderer = app[renderer_start:renderer_end]
    forbidden = ["client_secret", "api_v3_key", "merchant_private_key", "weixin://", "内部验收", "主理人"]
    for marker in forbidden:
        if marker in renderer.lower():
            print(f"FAIL merchant billing panel exposes internal/provider detail: {marker}")
            return 1
    trust_start = app.index("function renderSaasMerchantBillingCustomerTrustPanel")
    trust_end = app.index("\nfunction renderSaasMerchantBillingGuardrailPanel", trust_start)
    trust_renderer = app[trust_start:trust_end]
    for marker in ["Customer Portal", "Stripe", "托管支付边界", "跳转到安全支付页", "项已准备"]:
        if marker in trust_renderer:
            print(f"FAIL merchant billing trust panel contains stale provider copy: {marker}")
            return 1
    for marker in ["微信扫码付款可用", "到期自主续购", "merchant_confirmed_one_time_30_day"]:
        if marker not in settings_panels:
            print(f"FAIL settings billing panel missing WeChat Pay marker: {marker}")
            return 1
    for marker in ["¥99/月", "¥199/月", "¥299/月"]:
        if marker in app:
            print(f"FAIL app.js contains misleading auto-renew style price: {marker}")
            return 1
    customer_assets = {
        "app.js": app,
        "app.html": (ROOT / "app.html").read_text(encoding="utf-8"),
        "styles.css": styles,
        "settings_panels": settings_panels,
    }
    for name, content in customer_assets.items():
        if re.search(r"\bfal\b", content, flags=re.IGNORECASE):
            print(f"FAIL {name} exposes replaceable media provider name")
            return 1
    for marker in ["开发者数据平台", "平台收入总览", "全站访问明细"]:
        merchant_tabs = app[app.index("function saasSettingsTabDefinitions"):app.index("if (saasOwnerLaunchCanView())", app.index("function saasSettingsTabDefinitions"))]
        if marker in merchant_tabs:
            print(f"FAIL merchant settings expose internal operations marker: {marker}")
            return 1
    print("PASS jiejing_domestic_billing_merchant_ui")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
