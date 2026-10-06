#!/usr/bin/env python3
"""Static merchant-UX contract for WeChat Pay subscription checkout."""

from __future__ import annotations

from pathlib import Path
import os
import re
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]


def check_public_service_scope(app: str) -> None:
    payment = app[app.index("function renderSaasMerchantDomesticPaymentPanel"):app.index("\nfunction renderSaasMerchantBillingEntitlementPathPanel")]
    for text in ("通过 eBay API 正式发布", "店铺授权", "套餐权限", "预检", "确认", "订阅不会解除 eBay 账号限制", "不会自动发送买家消息"):
        assert text in payment, f"checkout must disclose its actual current service scope: {text}"
    assert "eBay 公开发布暂未开放" not in payment
    assert payment.index('aria-label="当前服务范围"') < payment.index('data-saas-action="domestic-billing-create-order"'), "service scope must be shown before purchase controls"


def check_subscription_support_route(app: str) -> None:
    trust = app[app.index("function renderSaasMerchantBillingCustomerTrustPanel"):app.index("\nfunction renderSaasMerchantPricingModelPanel")]
    assert 'data-workflow-feedback-open' in trust, "subscription support must open feedback to Jiejing"
    assert 'data-workflow-feedback-module-key="connect"' in trust
    assert 'data-workflow-feedback-stage="订阅与发票支持"' in trust
    assert 'data-global-flow-view="service"' not in trust, "SaaS payment help must not route to eBay buyer support"


def check_media_balance_browser(app: str) -> None:
    """Replay the real Billing fetch/render path; all HTTP is local fixtures."""
    from playwright.sync_api import sync_playwright

    boot = r"exposeLocalJiejingTestHooks\(\);\r?\ninit\(\);\r?\nrunLocalJiejingQaScenarioFromUrl\(\);\s*$"
    assert re.search(boot, app), "frontend boot boundary not found"
    script = re.sub(boot, "exposeLocalJiejingTestHooks();", app)
    assert app.count("fetchSaasMerchantBillingUsage(),") == 1, "Settings refresh must use the combined merchant-safe Billing fetch"
    base = "http://127.0.0.1:45678"
    safe = {
        "contract_version": "2026-08-27-merchant-media-points-v1",
        "total_points": 820, "available_points": 820,
        "included_points": 500, "purchased_points": 320, "promotional_points": 0,
        "packs": [{"key": "pack_1000", "points": 1000, "amount_minor": 1000}],
        "purchase": {"status": "not_open", "purchase_enabled": False},
    }
    seen = []
    summary_status = {"http": 200}
    usage_status = {"http": 200}

    def route_request(route):
        request = route.request
        parsed = urlparse(request.url)
        assert f"{parsed.scheme}://{parsed.netloc}" == base
        assert request.method == "GET", "Billing display must not mutate anything"
        seen.append(parsed.path)
        if parsed.path == "/app.html":
            route.fulfill(content_type="text/html; charset=utf-8", body='<html><body><main id="billing-test"></main><script src="/app.js"></script></body></html>')
        elif parsed.path == "/app.js":
            route.fulfill(content_type="text/javascript; charset=utf-8", body=script)
        elif parsed.path == "/billing/usage":
            route.fulfill(status=usage_status["http"], json={"billing_usage": {"subscription": {"entitlement_active": True}, "media_credits": {
                "account": {"balance": 999999, "available": 999999, "owner_testing_points": 999999},
                "recent_activity": [{"operation_type": "settle", "points": 999999}],
            }}} if usage_status["http"] == 200 else {"error": "temporarily_unavailable"})
        elif parsed.path == "/billing/media-credits":
            route.fulfill(status=summary_status["http"], json={"media_credits": safe} if summary_status["http"] == 200 else {"error": "temporarily_unavailable"})
        else:
            raise AssertionError(f"unexpected request: {parsed.path}")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, channel=os.environ.get("JIEJING_PLAYWRIGHT_CHANNEL", "chrome"))
        try:
            page = browser.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.route("**/*", route_request)
            page.goto(f"{base}/app.html?start=app&qa=public-saas")
            page.evaluate("document.querySelector('#billing-test').innerHTML = renderSaasMerchantMediaCreditsPanel()")
            assert "暂未获取" in page.locator(".saas-merchant-media-credits .saas-settings-card-head strong").inner_text()
            payload = page.evaluate("""async (base) => {
                state.saasApiBase = base;
                const response = await fetchSaasMerchantBillingUsage();
                state.saasBillingUsage = response.billing_usage;
                document.querySelector('#billing-test').innerHTML = renderSaasMerchantMediaCreditsPanel();
                return response.billing_usage;
            }""", base)
            assert page.locator(".saas-merchant-media-credits .saas-settings-card-head strong").inner_text() == "素材点余额 820"
            assert page.get_by_role("button", name="购买素材点").is_disabled()
            assert payload["subscription"]["entitlement_active"] is True
            assert "account" not in payload["media_credits"]
            assert "999999" not in page.locator("#billing-test").inner_text()
            assert "使用明细暂未提供" in page.locator("#billing-test").inner_text()
            assert page.locator(".saas-media-credit-balance-grid article").count() == 3
            assert "累计使用" not in page.locator(".saas-media-credit-balance-grid").inner_text()
            assert "最近素材点记录" not in page.locator("#billing-test").inner_text()
            assert seen.count("/billing/media-credits") == 1
            safe['usage'] = {
                'contract_version':'2026-09-25-merchant-media-usage-v1', 'status':'ready',
                'held_points':80, 'has_more':False, 'incomplete':False,
                'scope':'recent_image_reservations',
                'items':[
                    {'activity_id':'1234567890abcdef','state':'settled','estimated_points':240,'spent_points':80,'released_points':160,'created_at':'2026-09-25T08:00:00Z','updated_at':'2026-09-25T08:01:00Z'},
                    {'activity_id':'abcdef1234567890','state':'released','estimated_points':80,'spent_points':0,'released_points':80,'created_at':'2026-09-25T08:00:00Z','updated_at':'2026-09-25T08:02:00Z'},
                    {'activity_id':'aabbccddeeff0011','state':'reserved','estimated_points':80,'spent_points':None,'released_points':0,'created_at':'2026-09-25T08:03:00Z','updated_at':'2026-09-25T08:03:00Z'},
                ],
            }
            page.evaluate("""async () => {
                state.saasBillingUsage = (await fetchSaasMerchantBillingUsage()).billing_usage;
                document.querySelector('#billing-test').innerHTML = renderSaasMerchantMediaCreditsPanel();
            }""")
            history = page.locator('[data-media-usage-contract]')
            assert history.count() == 1, 'merchant usage disclosure missing'
            assert not history.get_attribute('open')
            history.locator('summary').click()
            assert '实际消耗 80 点' in history.inner_text()
            assert '解除占用 160 点' in history.inner_text()
            assert '处理中' in history.inner_text()
            assert '未扣点' in history.inner_text()
            assert '不等于现金退款' in history.inner_text()
            assert history.locator('article').count() == 3
            history.locator('summary').click()
            assert not history.get_attribute('open')
            safe['usage']['items'] = []
            page.evaluate("""async () => {
                state.saasBillingUsage = (await fetchSaasMerchantBillingUsage()).billing_usage;
                document.querySelector('#billing-test').innerHTML = renderSaasMerchantMediaCreditsPanel();
            }""")
            page.locator('[data-media-usage-contract] summary').click()
            assert '没有可核对的图片点数记录' in page.locator('#billing-test').inner_text()
            safe['usage']['incomplete'] = True
            safe['usage']['has_more'] = True
            page.evaluate("""async () => {
                state.saasBillingUsage = (await fetchSaasMerchantBillingUsage()).billing_usage;
                document.querySelector('#billing-test').innerHTML = renderSaasMerchantMediaCreditsPanel();
            }""")
            page.locator('[data-media-usage-contract] summary').click()
            assert '部分历史记录暂时无法核对' in page.locator('#billing-test').inner_text()
            assert '不代表完整历史' in page.locator('#billing-test').inner_text()
            safe['usage']['held_points'] = None
            page.evaluate("""async () => {
                state.saasBillingUsage = (await fetchSaasMerchantBillingUsage()).billing_usage;
                document.querySelector('#billing-test').innerHTML = renderSaasMerchantMediaCreditsPanel();
            }""")
            assert page.locator('[data-media-usage-contract]').count() == 0
            assert '使用明细暂未提供' in page.locator('#billing-test').inner_text()
            safe['usage']['held_points'] = 0
            safe['usage']['items'] = [{'activity_id':'<img src=x onerror=alert(1)>','state':'released',
                'estimated_points':80,'spent_points':0,'released_points':80}]
            page.evaluate("""async () => {
                state.saasBillingUsage = (await fetchSaasMerchantBillingUsage()).billing_usage;
                document.querySelector('#billing-test').innerHTML = renderSaasMerchantMediaCreditsPanel();
            }""")
            assert page.locator('[data-media-usage-contract]').count() == 0
            assert page.locator('#billing-test img').count() == 0
            summary_status["http"] = 503
            page.evaluate("""async () => {
                state.saasBillingUsage = (await fetchSaasMerchantBillingUsage()).billing_usage;
                document.querySelector('#billing-test').innerHTML = renderSaasMerchantMediaCreditsPanel();
            }""")
            assert "暂未获取" in page.locator(".saas-merchant-media-credits .saas-settings-card-head strong").inner_text()
            assert "素材点余额 0" not in page.locator("#billing-test").inner_text()
            summary_status["http"] = 200
            safe.update(available_points=0, included_points=0, purchased_points=0)
            safe["total_points"] = 820  # A zero available balance must not fall back to another total.
            safe["purchase"] = {"status": "available", "purchase_enabled": True}
            page.evaluate("""async () => {
                state.saasBillingUsage = (await fetchSaasMerchantBillingUsage()).billing_usage;
                document.querySelector('#billing-test').innerHTML = renderSaasMerchantMediaCreditsPanel();
            }""")
            assert page.locator(".saas-merchant-media-credits .saas-settings-card-head strong").inner_text() == "素材点余额 0"
            assert page.get_by_role("button", name="购买素材点").is_enabled()
            safe['purchase'] = {'status':'not_open', 'purchase_enabled':False, 'unavailable_reason':'payment_unavailable'}
            page.evaluate("""async () => {
                state.saasBillingUsage = (await fetchSaasMerchantBillingUsage()).billing_usage;
                document.querySelector('#billing-test').innerHTML = renderSaasMerchantMediaCreditsPanel();
            }""")
            assert '素材点支付暂不可用' in page.locator('#billing-test').inner_text()
            assert page.get_by_role('button', name='购买素材点').is_disabled()
            safe["available_points"] = None
            page.evaluate("""async () => {
                state.saasBillingUsage = (await fetchSaasMerchantBillingUsage()).billing_usage;
                document.querySelector('#billing-test').innerHTML = renderSaasMerchantMediaCreditsPanel();
            }""")
            assert "暂未获取" in page.locator(".saas-merchant-media-credits .saas-settings-card-head strong").inner_text()
            assert page.get_by_role("button", name="购买素材点").is_disabled()
            usage_status["http"] = 503
            assert page.evaluate("async () => (await fetchSaasMerchantBillingUsage()).billing_usage") is None, "missing Billing usage must remain missing for subscription consumers"
            page.evaluate("""() => {
                state.saasBillingUsage = {subscription: {provider:'manual_seed', status:'private_beta_manual_seed', entitlement_active:true}};
                state.saasDomesticBillingContract = {provider:'wechat_pay_native', real_checkout_ready:true, charge_now_allowed:true};
                document.querySelector('#billing-test').innerHTML = renderSaasMerchantDomesticPaymentPanel();
            }""")
            preview_text = page.locator('#billing-test').inner_text()
            assert '体验权益可用' in preview_text
            assert page.locator('[aria-label="当前服务范围"]').is_visible()
            assert '通过 eBay API 正式发布' in preview_text
            assert 'eBay 公开发布暂未开放' not in preview_text
            assert '订阅不会解除 eBay 账号限制' in preview_text
            assert '不会自动发送买家消息' in preview_text
            assert '到期时间暂未提供' not in preview_text
            assert '顺延到现有有效期' not in preview_text
            assert page.get_by_role('button', name='续购当前套餐').count() == 0
            assert page.get_by_role('button', name='微信扫码开通 有店铺').is_enabled()
            for kind in ('owner_preview', 'free_trial'):
                page.evaluate("""(kind) => {
                    state.saasBillingUsage = {subscription: {provider:kind, access_kind:kind,
                        status:kind + '_active', entitlement_active:true, plan_key:kind === 'free_trial' ? 'free' : 'starter',
                        test_mode:kind === 'owner_preview', active_until:kind === 'free_trial' ? '2099-10-24T00:00:00Z' : ''}};
                    document.querySelector('#billing-test').innerHTML = renderSaasMerchantDomesticPaymentPanel();
                }""", kind)
                assert '体验权益可用' in page.locator('#billing-test').inner_text()
                if kind == 'free_trial':
                    assert '免费体验有效期至 2099-10-24' in page.locator('#billing-test').inner_text()
                assert page.get_by_role('button', name='续购当前套餐').count() == 0
                assert page.get_by_role('button', name='微信扫码开通 有店铺').is_enabled()
            page.evaluate("""() => {
                state.saasBillingUsage = {subscription: {status:'active', entitlement_active:true, plan_key:'starter'}};
                state.saasDomesticBillingContract = {provider:'wechat_pay_native', real_checkout_ready:true, charge_now_allowed:true};
                document.querySelector('#billing-test').innerHTML = renderSaasMerchantDomesticPaymentPanel();
            }""")
            payment_text = page.locator('#billing-test').inner_text()
            assert "到期时间暂未提供" in payment_text
            assert "当前套餐有效期至 当前套餐" not in payment_text
            assert page.get_by_role('button', name='续购当前套餐').is_disabled()
            assert '顺延到现有有效期' not in payment_text
            page.evaluate("""() => {
                state.saasBillingUsage.subscription.active_until = '2099-10-24T00:00:00Z';
                document.querySelector('#billing-test').innerHTML = renderSaasMerchantDomesticPaymentPanel();
            }""")
            assert "当前套餐有效期至 2099-10-24。" in page.locator('#billing-test').inner_text()
            assert "到期时间暂未提供" not in page.locator('#billing-test').inner_text()
            assert page.get_by_role('button', name='续购当前套餐').is_enabled()
            for expiry in ('not-a-date', '2020-01-01T00:00:00Z'):
                page.evaluate("""(expiry) => {
                    state.saasBillingUsage.subscription.active_until = expiry;
                    document.querySelector('#billing-test').innerHTML = renderSaasMerchantDomesticPaymentPanel();
                }""", expiry)
                assert page.get_by_role('button', name='续购当前套餐').is_disabled()
                assert '顺延到现有有效期' not in page.locator('#billing-test').inner_text()
            for plan_key, title, price in (('starter', '有店铺', '¥99 / 30 天'), ('operator', '多店铺', '¥199 / 30 天')):
                page.evaluate("""(planKey) => {
                    state.selectedPlan = planKey;
                    state.saasBillingUsage = {subscription: {access_kind:'free_trial', provider:'free_trial',
                        status:'free_trial_active', entitlement_active:true, plan_key:'free', active_until:'2099-10-24T00:00:00Z'}};
                    document.querySelector('#billing-test').innerHTML = renderSaasMerchantDomesticPaymentPanel()
                        + renderSaasMerchantBillingCustomerTrustPanel();
                }""", plan_key)
                selected = page.locator('[data-saas-action="domestic-billing-select-plan"][aria-pressed="true"]')
                assert selected.get_attribute('data-domestic-plan-key') == plan_key
                assert price in selected.inner_text()
                assert page.get_by_role('button', name=f'微信扫码开通 {title}').is_enabled()
                prices = page.locator('.saas-merchant-billing-trust-grid article').filter(has_text='价格与续购').inner_text()
                assert '有店铺 ¥99 / 30 天' in prices, 'trust explanation must identify the starter plan price'
                assert '多店铺 ¥199 / 30 天' in prices, 'trust explanation must not present every plan as ¥99'
                assert '不会自动续费或自动扣款' in prices
            for contract in (None, {'provider':'wechat_pay_native', 'real_checkout_ready':False, 'charge_now_allowed':False}):
                page.evaluate("""(contract) => {
                    state.saasDomesticBillingContract = contract;
                    state.saasBillingUsage = {subscription: {status:'active', entitlement_active:true,
                        plan_key:'operator', active_until:'2099-10-24T00:00:00Z'}};
                    document.querySelector('#billing-test').innerHTML = renderSaasMerchantDomesticPaymentPanel()
                        + renderSaasMerchantBillingCustomerTrustPanel() + renderSaasMerchantBillingPlainSummaryPanel()
                        + renderSaasMerchantPricingModelPanel() + renderSaasMerchantBillingEntitlementPathPanel();
                }""", contract)
                degraded = page.locator('#billing-test').inner_text()
                assert '当前套餐与续购' in degraded, 'payment outage must not relabel an active customer as a trial'
                assert '当前套餐有效期至 2099-10-24。' in degraded
                assert '试用阶段' not in degraded and '先使用试用套餐' not in degraded
                assert '试用模式' not in degraded
                assert '公开付款开关' not in degraded
                assert page.get_by_role('button', name='刷新付款状态', exact=True).is_enabled()
                assert page.locator('[data-saas-action="manual-beta-create-order"]').count() == 0
                assert page.locator('[data-saas-action="domestic-billing-create-order"]').count() == 0
                assert page.get_by_role('button', name='联系捷境支持').is_enabled()
                assert page.evaluate('state.saasBillingUsage.subscription.plan_key') == 'operator'
                page.evaluate("""() => {
                    state.saasDomesticBillingContract = {provider:'wechat_pay_native', real_checkout_ready:true, charge_now_allowed:true};
                    document.querySelector('#billing-test').innerHTML = renderSaasMerchantDomesticPaymentPanel();
                }""")
                renewal = page.get_by_role('button', name='续购当前套餐', exact=True)
                assert renewal.is_enabled() and renewal.get_attribute('data-domestic-plan-key') == 'operator'
                assert '当前套餐有效期至 2099-10-24。' in page.locator('#billing-test').inner_text()
                assert page.locator('[data-saas-action="manual-beta-create-order"]').count() == 0
            for amount, expected in ((None, '价格待核对'), (0, '价格待核对'), (-1, '价格待核对'),
                                     ('invalid', '价格待核对'), (19900, '¥199 / 30 天')):
                page.evaluate("""(amount) => {
                    state.saasBillingUsage = {subscription: {status:'active', entitlement_active:true, plan_key:'operator'},
                        plan: {key:'operator', amount_minor:amount}};
                    document.querySelector('#billing-test').innerHTML = renderSaasMerchantBillingPlainSummaryPanel();
                }""", amount)
                summary_plan = page.locator('.saas-merchant-billing-plain-grid article').filter(has_text='软件套餐')
                assert f'多店铺 · {expected}' in summary_plan.inner_text(), 'missing or invalid paid price must not be shown as free'
            page.evaluate("""() => {
                state.saasBillingUsage = {subscription:{plan_key:'free'}, plan:{key:'free', amount_minor:0}};
                document.querySelector('#billing-test').innerHTML = renderSaasMerchantBillingPlainSummaryPanel();
            }""")
            assert '免费体验 · ¥0' in page.locator('#billing-test').inner_text()
            page.evaluate("""() => {
                state.saasBillingPlan = {};
                state.saasBillingUsage = null;
                document.querySelector('#billing-test').innerHTML = renderSaasMerchantBillingPlainSummaryPanel();
            }""")
            assert '套餐待核对 · 价格待核对' in page.locator('#billing-test').inner_text(), 'missing account billing data must not invent a paid plan'
            assert errors == []
        finally:
            browser.close()


def main() -> int:
    app = (ROOT / "app.js").read_text(encoding="utf-8")
    ops = (ROOT / "ops.js").read_text(encoding="utf-8")
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
        'data-workflow-feedback-stage="订阅与发票支持"',
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
        "生成前显示预计用量，完成后按实际结算",
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
    if not re.search(r'isSaasDomesticBillingRefundConfirmation\(card\)\s*\?\s*renderSaasDomesticRefundConfirmationAction\(card\)\s*:\s*status === "pending"', app):
        print("FAIL SaaS refund cards must bypass generic merchant approval controls")
        return 1
    refund_card_start = app.index("function renderSaasDomesticRefundConfirmationAction")
    refund_card_end = app.index("\nfunction saasConfirmationActionAttributes", refund_card_start)
    refund_card = app[refund_card_start:refund_card_end]
    for marker in ["data-saas-refund-progress", "捷境运营审核", 'data-saas-action="domestic-billing-refund-query"']:
        if marker not in refund_card:
            print(f"FAIL merchant refund card missing review/progress/query contract: {marker}")
            return 1
    for marker in ['data-saas-action="approve-confirmation"', 'data-saas-action="domestic-billing-refund-execute"']:
        if marker in refund_card:
            print(f"FAIL merchant refund card exposes platform-only money permission: {marker}")
            return 1
    refund_execute_start = app.find("async function runSaasDomesticBillingExecuteRefund")
    refund_execute_end = app.find("\nasync function runSaasDomesticBillingQueryRefund", refund_execute_start)
    if refund_execute_start < 0 or refund_execute_end < 0:
        print("FAIL legacy merchant refund actions need a safe non-executing handler")
        return 1
    refund_execute_flow = app[refund_execute_start:refund_execute_end]
    for marker in ["saasFetch(", "fetch(", "/refund-execute", "/owner/billing/domestic/refunds"]:
        if marker in refund_execute_flow:
            print(f"FAIL legacy merchant refund handler must not send a money action: {marker}")
            return 1
    if "捷境运营审核和处理" not in refund_execute_flow or 'data-saas-action="domestic-billing-refund-execute"' in app:
        print("FAIL merchants must see platform review progress, not a self-execution button")
        return 1
    refund_request_start = app.index("async function runSaasDomesticBillingRefundRequest")
    refund_request = app[refund_request_start:refund_execute_start]
    for marker in ["/refund-request", "JSON.stringify({ reason })", "不会立即退款"]:
        if marker not in refund_request:
            print(f"FAIL merchant refund application missing required contract: {marker}")
            return 1
    ops_refund_start = ops.index("function renderRefundReviews")
    ops_refund_end = ops.index("\n  function renderCosts", ops_refund_start)
    for marker in ["platform_review_verified", 'data-refund-action="approve"', 'data-refund-action="reject"', 'data-refund-action="execute"', 'data-refund-action="query"', "review_reason", "review_evidence", "company_id", "amount_minor"]:
        if marker not in ops[ops_refund_start:ops_refund_end]:
            print(f"FAIL platform refund UI missing reviewed money workflow: {marker}")
            return 1
    ops_action_start = ops.index("function bindDetailControls")
    ops_action_end = ops.index('elements.content.querySelectorAll("[data-filter]")', ops_action_start)
    for marker in ["window.confirm", "row.company_id", "row.order_id", "row.amount_minor", "row.review_reason", "reason.length < 10", "body.exact_confirmation = row.execution_confirmation", "/owner/billing/domestic/refunds/", "不会自动重复提交资金动作"]:
        if marker not in ops[ops_action_start:ops_action_end]:
            print(f"FAIL platform refund execution missing target/reason/confirmation safety: {marker}")
            return 1
    refund_query_start = app.find("async function runSaasDomesticBillingQueryRefund")
    refund_query_end = app.find("\nfunction handleSaasAction", refund_query_start)
    if refund_query_start < 0 or refund_query_end < 0:
        print("FAIL processing refunds need a read-safe merchant status refresh action")
        return 1
    refund_query_flow = app[refund_query_start:refund_query_end]
    for marker in ["/refund-execute", "/owner/billing/domestic/refunds"]:
        if marker in refund_query_flow:
            print(f"FAIL merchant refund query must never issue a money action: {marker}")
            return 1
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
    for marker in ["refund_review_requested", "refund_processing", "refund_failed", "data-saas-refund-progress", "运营处理", "未通过审核", "尚未向微信支付提交", "刷新退款状态"]:
        if marker not in refund_order_actions:
            print(f"FAIL billing order refund next-action renderer missing state: {marker}")
            return 1
    for marker in ['data-saas-action="approve-confirmation"', 'data-saas-action="domestic-billing-refund-execute"']:
        if marker in refund_order_actions:
            print(f"FAIL merchant order history exposes platform-only money permission: {marker}")
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
    check_public_service_scope(app)
    check_subscription_support_route(app)
    check_media_balance_browser(app)
    print("PASS jiejing_domestic_billing_merchant_ui")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
