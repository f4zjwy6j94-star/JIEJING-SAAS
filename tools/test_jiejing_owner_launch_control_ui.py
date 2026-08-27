#!/usr/bin/env python3
"""Static contract: launch control lives on ops, never in the merchant app."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def function_scope(source: str, function_name: str) -> str:
    start = source.find(f"function {function_name}(")
    if start < 0:
        return ""
    next_sync = source.find("\nfunction ", start + 1)
    next_async = source.find("\nasync function ", start + 1)
    ends = [position for position in (next_sync, next_async) if position >= 0]
    return source[start : min(ends) if ends else len(source)]


def main() -> int:
    app_js = (ROOT / "app.js").read_text(encoding="utf-8")
    app_html = (ROOT / "app.html").read_text(encoding="utf-8")
    merchant_panels = (ROOT / "assets" / "jiejing-settings-panels.js").read_text(encoding="utf-8")
    ops_html = (ROOT / "ops.html").read_text(encoding="utf-8")
    ops_js = (ROOT / "ops.js").read_text(encoding="utf-8")
    ops_panels_path = ROOT / "assets" / "jiejing-ops-panels.js"
    ops_panels = ops_panels_path.read_text(encoding="utf-8") if ops_panels_path.exists() else ""
    api_server = (ROOT / "jiejing_saas" / "api_server.py").read_text(encoding="utf-8")
    deploy = (ROOT / "deploy" / "apply-staging-patch.sh").read_text(encoding="utf-8")

    merchant_bundle = "\n".join((app_html, app_js, merchant_panels))
    for marker in (
        "/owner/launch-control",
        "renderSaasOwnerLaunchControlPanel",
        "saasOwnerLaunchControl",
        "saas-owner-launch-control",
        "owner_war_room_v3",
        "owner_review_packet_v1",
        "owner_release_history_v1",
        "continuity_handoff_v1",
        "固定正式上线准备度",
        "主理人高级",
        "refresh-owner-launch-control",
        "copy-owner-review-packet",
        "download-owner-review-packet",
        "copy-launch-rehearsal-audit",
        "download-launch-rehearsal-audit",
        "copy-release-history",
        "download-release-history",
        "copy-continuity-handoff",
        "download-continuity-handoff",
    ):
        if marker in merchant_bundle:
            return fail(f"merchant bundle contains owner launch-control marker: {marker}")

    if not ops_panels_path.exists():
        return fail("physically separate assets/jiejing-ops-panels.js is missing")
    if "jiejing-ops-panels.js" not in ops_html:
        return fail("ops.html must load the physically separate ops panels bundle")
    ops_bundle = "\n".join((ops_html, ops_js, ops_panels))
    for marker in (
        "上线与发布",
        "支付验收",
        "备份与恢复",
        "运行与安全",
        "/owner/launch-control",
    ):
        if marker not in ops_bundle:
            return fail(f"ops bundle is missing launch-control capability: {marker}")

    for marker in (
        "global.JiejingOpsPanels",
        "function renderOwnerLaunchControlPanel",
        "renderOwnerLaunchControlPanel",
    ):
        if marker not in ops_panels:
            return fail(f"ops panels bundle is missing its launch-control renderer/export: {marker}")
    if "window.JiejingOpsPanels" not in ops_js or "renderOwnerLaunchControlPanel" not in ops_js:
        return fail("ops.js must invoke the exported launch-control renderer")

    for marker in (
        "secret_exposed",
        "charge_now_allowed",
        "platform_write_now_allowed",
        "repeat_ebay_oauth_allowed",
        "frontend_gets_payment_secret",
        "frontend_gets_api_key",
        "exports_database",
        "exports_raw_secret",
        "owner_review_packet_v1",
        "launch_rehearsal_audit_v1",
        "owner_release_history_v1",
        "continuity_handoff_v1",
    ):
        if marker not in ops_bundle:
            return fail(f"ops launch control is missing safety/evidence field: {marker}")

    for action in (
        "refresh-owner-launch-control",
        "copy-owner-review-packet",
        "download-owner-review-packet",
        "copy-launch-rehearsal-audit",
        "download-launch-rehearsal-audit",
        "copy-release-history",
        "download-release-history",
        "copy-continuity-handoff",
        "download-continuity-handoff",
    ):
        if action not in ops_bundle:
            return fail(f"ops launch control is missing safe operator action: {action}")

    for handler in (
        "async function refreshSaasOwnerLaunchControl",
        "function copySaasOwnerReviewPacket",
        "function downloadSaasOwnerReviewPacket",
        "function copySaasLaunchRehearsalAudit",
        "function downloadSaasLaunchRehearsalAudit",
        "function copySaasReleaseHistory",
        "function downloadSaasReleaseHistory",
        "function copySaasContinuityHandoff",
        "function downloadSaasContinuityHandoff",
    ):
        if handler not in ops_bundle:
            return fail(f"ops launch control is missing migrated action handler: {handler}")
    for action in (
        "refresh-owner-launch-control",
        "copy-owner-review-packet",
        "download-owner-review-packet",
        "copy-launch-rehearsal-audit",
        "download-launch-rehearsal-audit",
        "copy-release-history",
        "download-release-history",
        "copy-continuity-handoff",
        "download-continuity-handoff",
    ):
        if f'if (action === "{action}")' not in ops_bundle:
            return fail(f"ops launch control action is not registered: {action}")

    export_builders = (
        "buildSaasOwnerReviewPacketDownloadPayload",
        "buildSaasLaunchRehearsalAuditDownloadPayload",
        "buildSaasReleaseHistoryDownloadPayload",
        "buildSaasContinuityHandoffDownloadPayload",
    )
    for builder in export_builders:
        scope = function_scope(ops_bundle, builder)
        if not scope:
            return fail(f"ops launch control is missing safe export builder: {builder}")
        if "secret_exposed: false" not in scope:
            return fail(f"ops launch control export must state secret_exposed=false: {builder}")
        for forbidden in (
            "process.env",
            "localStorage",
            "sessionStorage",
            "refresh_token",
            "access_token",
            "client_secret",
            "sk_live",
            "whsec",
            "...source",
            "...packet",
        ):
            if forbidden.lower() in scope.lower():
                return fail(f"ops launch control export is not allowlisted ({builder}): {forbidden}")

    renderer_start = ops_panels.find("function renderOwnerLaunchControlPanel")
    renderer_end = ops_panels.find("\n  function ", renderer_start + 1)
    renderer_scope = ops_panels[renderer_start : renderer_end if renderer_end >= 0 else len(ops_panels)]
    for forbidden in (
        "refresh_token",
        "access_token",
        "client_secret",
        "sk_live",
        "whsec",
        "auto_publish",
        "skip_confirmation",
    ):
        if forbidden in renderer_scope.lower():
            return fail(f"ops launch-control renderer exposes unsafe marker: {forbidden}")

    route_start = api_server.find('if path == "owner/launch-control":')
    route_end = api_server.find("\n        if path == ", route_start + 1)
    if route_start < 0:
        return fail("owner launch-control backend route is missing")
    route_scope = api_server[route_start : route_end if route_end >= 0 else len(api_server)]
    if "_require_platform_internal_admin" not in route_scope:
        return fail("owner launch-control route must require platform-internal admin in its own scope")
    surface_guards = (
        "_require_operations_console_request(",
        "_require_operations_console_surface(",
        "_require_ops_surface(",
        "_require_owner_ops_surface(",
    )
    if not any(marker in route_scope for marker in surface_guards):
        return fail("owner launch-control route must call the unified ops-surface request guard in its own scope")

    if "assets/jiejing-ops-panels.js" not in deploy:
        return fail("staging patch must ship the physically separate ops panels bundle")

    # Merchant confirmation safety remains a merchant workflow concern.
    confirmation_scope_start = app_js.find("function saasWorkbenchApprovalBriefMarkup")
    confirmation_scope_end = app_js.find("function saasWorkbenchActionLabel", confirmation_scope_start)
    if confirmation_scope_start < 0 or confirmation_scope_end < 0:
        return fail("merchant confirmation approval brief is missing")
    confirmation_scope = app_js[confirmation_scope_start:confirmation_scope_end]
    for marker in ("资金/预算动作", "平台动作", "买家承诺", "敏感凭证隔离"):
        if marker not in confirmation_scope:
            return fail(f"merchant confirmation approval brief is missing: {marker}")
    for forbidden in ("sk_live", "whsec", "refresh_token", "access_token", "client_secret"):
        if forbidden in confirmation_scope.lower():
            return fail(f"merchant confirmation approval brief exposes secret marker: {forbidden}")

    print("PASS jiejing_owner_launch_control_ui")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
