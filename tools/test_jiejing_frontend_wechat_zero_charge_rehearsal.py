from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_JS = (ROOT / "app.js").read_text(encoding="utf-8")


def require(fragment: str, label: str) -> None:
    if fragment not in APP_JS:
        raise AssertionError(f"missing {label}: {fragment}")


def main() -> None:
    require("saasWechatPayZeroChargeRehearsal: null", "value-free rehearsal state")
    require("function saasCanRunWechatZeroChargeRehearsal()", "owner billing permission gate")
    require('role === "owner"', "owner-only UI gate")
    require('permissions.includes("manage_billing")', "manage_billing UI gate")
    require("function renderSaasWechatZeroChargeRehearsalPanel", "merchant control-room panel")
    require("wechat_pay_zero_charge_control_room_v1", "stable UI contract marker")
    require("只运行隔离假支付方", "merchant-readable zero-charge promise")
    require('data-saas-action="wechat-zero-charge-rehearsal"', "explicit user action")
    require('"wechat-zero-charge-rehearsal"', "protected action registration")
    require("async function runSaasWechatZeroChargeRehearsal", "one-shot UI handler")
    require("saasWechatZeroChargeRehearsalAttempted", "page-local one-shot claim")
    require('saasFetch("/billing/wechat-pay/zero-charge-rehearsal"', "dedicated backend route")
    require('exact_confirmation: "RUN WECHAT ZERO CHARGE REHEARSAL"', "exact safe-mode phrase")
    require("merchantSafeWechatZeroChargeRehearsal", "response allowlist")
    require("calls_external_payment_api: source.calls_external_payment_api === true", "external-call evidence normalization")
    require("creates_real_order: source.creates_real_order === true", "order evidence normalization")
    require("triggers_real_charge: source.triggers_real_charge === true", "charge evidence normalization")
    require("triggers_real_refund: source.triggers_real_refund === true", "refund evidence normalization")
    require("secret_exposed: source.secret_exposed === true", "secret evidence normalization")
    require("renderSaasWechatZeroChargeRehearsalPanel(ctx)", "billing settings placement")

    handler_start = APP_JS.index("async function runSaasWechatZeroChargeRehearsal")
    handler_end = min(
        position
        for position in (
            APP_JS.find("\nfunction ", handler_start + 1),
            APP_JS.find("\nasync function ", handler_start + 1),
        )
        if position >= 0
    )
    handler = APP_JS[handler_start:handler_end]
    forbidden = ("localStorage", "sessionStorage", "console.", "location.href", "window.open", "...result")
    for token in forbidden:
        if token in handler:
            raise AssertionError(f"zero-charge handler must not leak or redirect through {token}")

    panel_start = APP_JS.index("function renderSaasWechatZeroChargeRehearsalPanel")
    panel_end = APP_JS.index("\nfunction ", panel_start)
    panel = APP_JS[panel_start:panel_end]
    if 'if (!saasCanRunWechatZeroChargeRehearsal()) return "";' not in panel:
        raise AssertionError("zero-charge panel must be absent for non-owner/non-billing roles")

    print("PASS jiejing_frontend_wechat_zero_charge_rehearsal")


if __name__ == "__main__":
    main()
