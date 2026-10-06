from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    app_js = (ROOT / "app.js").read_text(encoding="utf-8")
    merchant_module = (ROOT / "assets" / "jiejing-settings-panels.js").read_text(encoding="utf-8")
    ops_html = (ROOT / "ops.html").read_text(encoding="utf-8")
    ops_js = (ROOT / "ops.js").read_text(encoding="utf-8")
    ops_panels_path = ROOT / "assets" / "jiejing-ops-panels.js"
    ops_panels = ops_panels_path.read_text(encoding="utf-8") if ops_panels_path.exists() else ""
    api_server = (ROOT / "jiejing_saas" / "api_server.py").read_text(encoding="utf-8")

    merchant_bundle = app_js + "\n" + merchant_module
    for marker in (
        "/billing/wechat-pay/zero-charge-rehearsal",
        "renderSaasWechatZeroChargeRehearsalPanel",
        'data-saas-action="wechat-zero-charge-rehearsal"',
        "wechat_pay_zero_charge_control_room_v1",
        "隔离假支付方",
    ):
        if marker in merchant_bundle:
            raise AssertionError(f"merchant bundle must not contain WeChat acceptance rehearsal: {marker}")

    ops_bundle = "\n".join((ops_html, ops_js, ops_panels))
    for marker in (
        "支付验收",
        "/owner/billing/wechat-pay/zero-charge-rehearsal",
        "RUN WECHAT ZERO CHARGE REHEARSAL",
    ):
        if marker not in ops_bundle:
            raise AssertionError(f"ops bundle is missing internal WeChat acceptance control: {marker}")

    required_ops_markers = (
        "function renderSaasWechatZeroChargeRehearsalPanel",
        'if (action === "wechat-zero-charge-rehearsal")',
        "async function runSaasWechatZeroChargeRehearsal",
        "saasWechatZeroChargeRehearsalAttempted",
        "function merchantSafeWechatZeroChargeRehearsal",
        "calls_external_payment_api: source.calls_external_payment_api === true",
        "creates_real_order: source.creates_real_order === true",
        "triggers_real_charge: source.triggers_real_charge === true",
        "triggers_real_refund: source.triggers_real_refund === true",
        "secret_exposed: source.secret_exposed === true",
    )
    for marker in required_ops_markers:
        if marker not in ops_bundle:
            raise AssertionError(f"ops WeChat acceptance safety contract is missing: {marker}")
    if not any(
        marker in ops_bundle
        for marker in (
            'data-ops-action="wechat-zero-charge-rehearsal"',
            'data-saas-action="wechat-zero-charge-rehearsal"',
        )
    ):
        raise AssertionError("ops WeChat acceptance control is missing its explicit action binding")

    handler_start = ops_bundle.find("async function runSaasWechatZeroChargeRehearsal")
    handler_candidates = [
        ops_bundle.find("\nfunction ", handler_start + 1),
        ops_bundle.find("\nasync function ", handler_start + 1),
    ]
    handler_ends = [position for position in handler_candidates if position >= 0]
    handler = ops_bundle[handler_start : min(handler_ends) if handler_ends else len(ops_bundle)]
    for marker in (
        "saasWechatZeroChargeRehearsalAttempted",
        "saasWechatZeroChargeRehearsalAttempted = true",
        "merchantSafeWechatZeroChargeRehearsal",
    ):
        if marker not in handler:
            raise AssertionError(f"ops WeChat acceptance handler is missing one-shot/allowlist marker: {marker}")
    for forbidden in ("localStorage", "sessionStorage", "console.", "location.href", "window.open", "...result"):
        if forbidden in handler:
            raise AssertionError(f"ops WeChat acceptance handler must not store, redirect, log, or spread raw response: {forbidden}")

    projection_start = ops_bundle.find("function merchantSafeWechatZeroChargeRehearsal")
    projection_end = ops_bundle.find("\nfunction ", projection_start + 1)
    projection = ops_bundle[projection_start : projection_end if projection_end >= 0 else len(ops_bundle)]
    for forbidden in ("return source", "...source", "...result", "raw_response"):
        if forbidden in projection:
            raise AssertionError(f"ops WeChat acceptance response must use an allowlist: {forbidden}")

    old_route = 'if path == "billing/wechat-pay/zero-charge-rehearsal":'
    if old_route in api_server:
        raise AssertionError("merchant billing route must not expose the zero-charge acceptance rehearsal")
    new_start = api_server.find('if path == "owner/billing/wechat-pay/zero-charge-rehearsal":')
    if new_start < 0:
        raise AssertionError("owner-only zero-charge acceptance route is missing")
    new_end = api_server.find("\n        if path == ", new_start + 1)
    route_scope = api_server[new_start : new_end if new_end >= 0 else len(api_server)]
    if "_require_platform_internal_admin" not in route_scope:
        raise AssertionError("zero-charge acceptance route must require platform-internal admin")
    surface_guards = (
        "_require_operations_console_request(",
        "_require_operations_console_surface(",
        "_require_ops_surface(",
        "_require_owner_ops_surface(",
    )
    if not any(marker in route_scope for marker in surface_guards):
        raise AssertionError("zero-charge acceptance route must call the unified ops-surface request guard")

    print("PASS jiejing_frontend_wechat_zero_charge_rehearsal")


if __name__ == "__main__":
    main()
