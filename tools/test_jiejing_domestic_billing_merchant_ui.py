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
        "wechat_native_qr",
        "merchant_confirmed_one_time_30_day",
        "微信付款由商家主动发起，到账后系统开通权益",
        "只以微信支付签名回调或安全查单结果为准，浏览器不能自行开通权益",
        "免费体验有 7 天和 20 次捷境托管 AI",
        "qr_image_data_url",
        '"idempotency-key"',
        "function renderSaasMerchantMediaCreditsPanel",
        "素材点余额",
        "套餐内",
        "已购买",
        "含 1,000 素材点",
        "含 3,000 素材点",
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
        "选择要开通的软件套餐",
        "const selectedCheckoutPlanKey = [\"starter\", \"operator\"]",
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
    if "payment_mode=" in app:
        print("FAIL app.js exposes internal billing activity field: payment_mode=")
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
    trust_end = app.index("\nfunction renderSaasMerchantPricingModelPanel", trust_start)
    trust_renderer = app[trust_start:trust_end]
    for marker in ["Customer Portal", "Stripe", "托管支付边界", "跳转到安全支付页", "项已准备"]:
        if marker in trust_renderer:
            print(f"FAIL merchant billing trust panel contains stale provider copy: {marker}")
            return 1
    for marker in [
        "付款状态",
        "在线付款开放",
        "商家主动创建订单并微信扫码；到账后由后端更新套餐权益。",
        "由商家主动操作",
        "付款、退款和套餐变更都会先显示订单与结果。",
        "页面不展示任何支付密钥。",
    ]:
        if marker not in settings_panels:
            print(f"FAIL settings billing panel missing WeChat Pay marker: {marker}")
            return 1
    for marker in ["merchant_confirmed_one_time_30_day", "正式公开收费已开放", "eBay 公开发布仍保持关闭"]:
        if marker in settings_panels:
            print(f"FAIL settings billing panel exposes internal launch marker: {marker}")
            return 1
    for marker in ["¥99/月", "¥199/月", "¥299/月"]:
        if marker in app:
            print(f"FAIL app.js contains misleading auto-renew style price: {marker}")
            return 1
    approval_start = app.index("async function approveFirstSaasConfirmation")
    approval_end = app.index("\nasync function loginSaasBackendSession", approval_start)
    approval_flow = app[approval_start:approval_end]
    domestic_refund_guard = approval_flow.find("isSaasDomesticBillingRefundConfirmation")
    generic_preflight = approval_flow.find("/preflight")
    if domestic_refund_guard < 0 or generic_preflight < 0 or domestic_refund_guard > generic_preflight:
        print("FAIL approved domestic refunds must stop before the generic eBay confirmation preflight")
        return 1
    if "执行已批准退款" not in approval_flow or "这里不会自动退款" not in approval_flow:
        print("FAIL refund approval must explain the separate explicit money-moving step")
        return 1
    approval_label_start = app.index("function saasConfirmationApproveButtonLabel")
    approval_label_end = app.index("\nfunction saasWorkbenchConfirmationTitle", approval_label_start)
    approval_labels = app[approval_label_start:approval_label_end]
    if "isSaasDomesticBillingRefundConfirmation" not in approval_labels or "批准退款申请" not in approval_labels:
        print("FAIL a billing refund approval must not be mislabeled as if money moves immediately")
        return 1
    refund_execute_start = app.find("async function runSaasDomesticBillingExecuteRefund")
    refund_execute_end = app.find("\nfunction handleSaasAction", refund_execute_start)
    if refund_execute_start < 0 or refund_execute_end < 0:
        print("FAIL approved refunds need a merchant-accessible explicit execution action")
        return 1
    refund_execute_flow = app[refund_execute_start:refund_execute_end]
    for marker in [
        "window.confirm",
        "/refund-execute",
        "domestic_billing_refund_execution",
        "triggers_real_refund",
        "退款处理中",
    ]:
        if marker not in refund_execute_flow:
            print(f"FAIL explicit refund execution flow missing safety/result marker: {marker}")
            return 1
    for marker in [
        '"domestic-billing-refund-execute"',
        'data-saas-action="domestic-billing-refund-execute"',
        "执行已批准退款",
    ]:
        if marker not in app:
            print(f"FAIL approved refund execution is not wired into the confirmation center: {marker}")
            return 1
    refund_query_start = app.find("async function runSaasDomesticBillingQueryRefund")
    refund_query_end = app.find("\nfunction handleSaasAction", refund_query_start)
    if refund_query_start < 0 or refund_query_end < 0:
        print("FAIL processing refunds need a read-safe merchant status refresh action")
        return 1
    refund_query_flow = app[refund_query_start:refund_query_end]
    for marker in ["/refund-query", "domestic_billing_refund_query", "不会重复提交退款"]:
        if marker not in refund_query_flow:
            print(f"FAIL refund status refresh is missing its read-safe contract marker: {marker}")
            return 1
    for marker in ['"domestic-billing-refund-query"', 'data-saas-action="domestic-billing-refund-query"', "刷新退款状态"]:
        if marker not in app:
            print(f"FAIL processing refund status refresh is not wired into the merchant UI: {marker}")
            return 1
    refund_order_action_start = app.find("function renderSaasDomesticRefundOrderActions")
    refund_order_action_end = app.find("\nfunction renderSaasMerchantMediaCreditsPanel", refund_order_action_start)
    if refund_order_action_start < 0 or refund_order_action_end < 0:
        print("FAIL billing order history needs one shared refund next-action renderer")
        return 1
    refund_order_actions = app[refund_order_action_start:refund_order_action_end]
    for marker in ["refund_review_requested", "refund_processing", "refund_failed", "去确认退款", "执行已批准退款", "刷新退款状态"]:
        if marker not in refund_order_actions:
            print(f"FAIL billing order refund next-action renderer missing state: {marker}")
            return 1
    media_renderer_start = app.index("function renderSaasMerchantMediaCreditsPanel")
    media_renderer_end = app.index("\nfunction renderSaasMerchantDomesticPaymentPanel", media_renderer_start)
    payment_renderer_start = app.index("function renderSaasMerchantDomesticPaymentPanel")
    payment_renderer_end = app.index("\nfunction renderSaasMerchantBillingEntitlementPathPanel", payment_renderer_start)
    if "renderSaasDomesticRefundOrderActions(order)" not in app[media_renderer_start:media_renderer_end]:
        print("FAIL media-point order history must expose the refund next action")
        return 1
    if "renderSaasDomesticRefundOrderActions(order)" not in app[payment_renderer_start:payment_renderer_end]:
        print("FAIL subscription order history must expose the refund next action")
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
        merchant_tabs_start = app.index("function saasSettingsTabDefinitions")
        merchant_tabs = app[merchant_tabs_start:app.index("function renderSaasSettingsCleanLayout", merchant_tabs_start)]
        if marker in merchant_tabs:
            print(f"FAIL merchant settings expose internal operations marker: {marker}")
            return 1
    print("PASS jiejing_domestic_billing_merchant_ui")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
