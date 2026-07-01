#!/usr/bin/env python3
"""Static guard for the platform-internal launch-control UI."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    app_js = (ROOT / "app.js").read_text(encoding="utf-8")
    styles = (ROOT / "styles.css").read_text(encoding="utf-8")
    api_server = (ROOT / "jiejing_saas" / "api_server.py").read_text(encoding="utf-8")
    deploy = (ROOT / "deploy" / "apply-staging-patch.sh").read_text(encoding="utf-8")
    nginx = (ROOT / "deploy" / "nginx.public-staging.conf").read_text(encoding="utf-8")
    production_caddy = (ROOT / "deploy" / "Caddyfile.production").read_text(encoding="utf-8")

    for marker in [
        "saasOwnerLaunchControl: null",
        'optionalSaasFetchFast("/owner/launch-control"',
        "state.saasOwnerLaunchControl = ownerLaunchControl.owner_launch_control",
        "async function refreshSaasOwnerLaunchControl",
        "function maybeRefreshSaasOwnerLaunchControlForActiveTab",
        "maybeRefreshSaasOwnerLaunchControlForActiveTab();",
        'data-saas-action="refresh-owner-launch-control"',
        'if (action === "refresh-owner-launch-control")',
        "function renderSaasOwnerLaunchControlPanel",
        "function saasOwnerLaunchCanView",
        'control?.audience === "platform_internal_admin"',
        'if (!saasOwnerLaunchCanView()) return "";',
        "saas-owner-launch-control",
        "owner_admin_only",
        "platform_internal_admin_only",
        "not_customer_visible",
        "charge_now_allowed=false",
        "platform_write_now_allowed=false",
        "repeat_ebay_oauth_allowed=false",
        "secret_exposed=false",
        "owner_war_room_v3",
        "expert_feasibility_review_v1",
        "saas-owner-feasibility-review",
        "saas-owner-feasibility-grid",
        "saas-owner-feasibility-actions",
        "saas-owner-feasibility-note",
        "feasible_for_private_beta",
        "feasible_for_paid_public_launch",
        "owner_review_packet_v1",
        'data-saas-action="copy-owner-review-packet"',
        'data-saas-action="download-owner-review-packet"',
        'data-saas-action="copy-launch-rehearsal-audit"',
        'data-saas-action="download-launch-rehearsal-audit"',
        'data-saas-action="copy-release-history"',
        'data-saas-action="download-release-history"',
        'data-saas-action="copy-continuity-handoff"',
        'data-saas-action="download-continuity-handoff"',
        'data-saas-action="copy-cutover-decision-checklist"',
        'data-saas-action="download-cutover-decision-checklist"',
        'data-saas-action="copy-final-launch-rehearsal-record"',
        'data-saas-action="download-final-launch-rehearsal-record"',
        'data-saas-action="copy-prelaunch-acceptance-report"',
        'data-saas-action="download-prelaunch-acceptance-report"',
        "function buildSaasOwnerReviewPacketDownloadPayload",
        "function buildSaasLaunchRehearsalAuditDownloadPayload",
        "function buildSaasReleaseHistoryDownloadPayload",
        "function buildSaasContinuityHandoffDownloadPayload",
        "function buildSaasCutoverDecisionChecklistDownloadPayload",
        "function buildSaasFinalLaunchRehearsalRecordDownloadPayload",
        "function buildSaasPrelaunchAcceptanceReportDownloadPayload",
        "function copySaasOwnerReviewPacket",
        "function downloadSaasOwnerReviewPacket",
        "function copySaasLaunchRehearsalAudit",
        "function downloadSaasLaunchRehearsalAudit",
        "function copySaasReleaseHistory",
        "function downloadSaasReleaseHistory",
        "function copySaasContinuityHandoff",
        "function downloadSaasContinuityHandoff",
        "function copySaasCutoverDecisionChecklist",
        "function downloadSaasCutoverDecisionChecklist",
        "function copySaasFinalLaunchRehearsalRecord",
        "function downloadSaasFinalLaunchRehearsalRecord",
        "function copySaasPrelaunchAcceptanceReport",
        "function downloadSaasPrelaunchAcceptanceReport",
        "saas-owner-review-packet",
        "saas-owner-review-grid",
        "saas-owner-review-note",
        "cutover_decision_checklist_v1",
        "saas-owner-cutover-checklist",
        "saas-owner-cutover-grid",
        "saas-owner-cutover-actions",
        "saas-owner-cutover-note",
        "founder_external_actions",
        "codex_internal_actions",
        "final_launch_rehearsal_execution_record_v1",
        "saas-owner-final-rehearsal-record",
        "saas-owner-final-rehearsal-grid",
        "saas-owner-final-rehearsal-actions",
        "saas-owner-final-rehearsal-note",
        "remaining_external_blockers",
        "remaining_internal_actions",
        "rollback_controls",
        "prelaunch_acceptance_report_v1",
        "saas-owner-prelaunch-report",
        "saas-owner-prelaunch-grid",
        "saas-owner-prelaunch-actions",
        "saas-owner-prelaunch-note",
        "founder_required_actions",
        "codex_continue_actions",
        "report_markdown",
        "launch_rehearsal_audit_v1",
        "saas-owner-launch-audit",
        "saas-owner-launch-audit-grid",
        "saas-owner-launch-audit-note",
        "owner_release_history_v1",
        "saas-owner-release-history",
        "saas-owner-release-history-grid",
        "saas-owner-release-check-grid",
        "saas-owner-release-rollback-list",
        "saas-owner-release-history-note",
        "continuity_handoff_v1",
        "saas-owner-continuity-handoff",
        "saas-owner-continuity-grid",
        "saas-owner-continuity-actions",
        "saas-owner-continuity-no-go",
        "saas-owner-continuity-note",
        "includes_raw_tokens=${Boolean",
        "includes_payment_secret=${Boolean",
        "reads_env_secret_values=${Boolean",
        "operations_observability_v1",
        "resilience_war_room_v1",
        "subscription_shutdown_control_v1",
        "test_data_governance",
        "saas-owner-war-room",
        "saas-owner-ops-observability",
        "saas-owner-ops-grid",
        "saas-owner-ops-note",
        "saas-owner-resilience-war-room",
        "saas-owner-resilience-grid",
        "saas-owner-resilience-note",
        "saas-owner-subscription-shutdown",
        "saas-owner-subscription-shutdown-grid",
        "saas-owner-subscription-shutdown-note",
        "public_charging_allowed=${Boolean",
        "frontend_gets_payment_secret=${Boolean",
        "frontend_gets_api_key=${Boolean",
        "exports_database=${Boolean",
        "exports_raw_secret=${Boolean",
        "saas-owner-test-data",
        "需要你外部介入",
        "我方内部继续推进",
        "renderSaasOwnerLaunchControlPanel()",
    ]:
        if marker not in app_js:
            return fail(f"app.js missing owner launch-control marker: {marker}")

    for marker in [
        ".saas-owner-launch-control",
        ".saas-owner-launch-head",
        ".saas-owner-launch-head-actions",
        ".saas-owner-launch-summary",
        ".saas-owner-launch-safety",
        ".saas-owner-launch-lanes",
        ".saas-owner-launch-queues",
        ".saas-owner-launch-evidence",
        ".saas-owner-war-room",
        ".saas-owner-war-room-grid",
        ".saas-owner-feasibility-review",
        ".saas-owner-feasibility-grid",
        ".saas-owner-feasibility-actions",
        ".saas-owner-feasibility-note",
        ".saas-owner-review-packet",
        ".saas-owner-review-grid",
        ".saas-owner-review-note",
        ".saas-owner-launch-audit",
        ".saas-owner-launch-audit-grid",
        ".saas-owner-launch-audit-note",
        ".saas-owner-release-history",
        ".saas-owner-release-history-grid",
        ".saas-owner-release-check-grid",
        ".saas-owner-release-rollback-list",
        ".saas-owner-release-history-note",
        ".saas-owner-continuity-handoff",
        ".saas-owner-continuity-grid",
        ".saas-owner-continuity-actions",
        ".saas-owner-continuity-no-go",
        ".saas-owner-continuity-note",
        ".saas-owner-cutover-checklist",
        ".saas-owner-cutover-grid",
        ".saas-owner-cutover-actions",
        ".saas-owner-cutover-note",
        ".saas-owner-final-rehearsal-record",
        ".saas-owner-final-rehearsal-grid",
        ".saas-owner-final-rehearsal-actions",
        ".saas-owner-final-rehearsal-note",
        ".saas-owner-prelaunch-report",
        ".saas-owner-prelaunch-grid",
        ".saas-owner-prelaunch-actions",
        ".saas-owner-prelaunch-note",
        ".saas-owner-ops-observability",
        ".saas-owner-ops-grid",
        ".saas-owner-ops-note",
        ".saas-owner-resilience-war-room",
        ".saas-owner-resilience-grid",
        ".saas-owner-resilience-note",
        ".saas-owner-subscription-shutdown",
        ".saas-owner-subscription-shutdown-grid",
        ".saas-owner-subscription-shutdown-note",
        ".saas-owner-test-data",
        ".saas-owner-test-data-grid",
        ".saas-confirm-approval-brief",
        ".saas-confirm-impact-grid",
        ".saas-confirm-evidence-list",
        ".saas-confirm-rollback-plan",
    ]:
        if marker not in styles:
            return fail(f"styles.css missing owner launch-control marker: {marker}")

    for marker in [
        "from .owner_launch_control import build_owner_launch_control",
        '"owner/"',
        'if path == "owner/launch-control":',
        "internal_admin_emails",
        "_is_platform_internal_admin",
        "platform-internal admin only",
        '"owner_launch_control": build_owner_launch_control',
        '"platform-internal-admin-only launch-control evidence"',
        '"GET /security/rate-limit/status"',
    ]:
        if marker not in api_server:
            return fail(f"api_server.py missing owner launch-control marker: {marker}")

    for marker in [
        "jiejing_saas/owner_launch_control.py",
        "tools/test_jiejing_owner_launch_control.py",
        "tools/test_jiejing_owner_launch_control_ui.py",
        "tools/codex_jiejing_owner_launch_control_smoke.js",
    ]:
        if marker not in deploy:
            return fail(f"staging patch should include owner launch-control file: {marker}")

    if "owner" not in nginx or "/owner/*" not in production_caddy:
        return fail("public proxy configs must route owner launch-control API to backend")

    scope = _function_scope(app_js, "function renderSaasOwnerLaunchControlPanel", "function renderSaasPublicSecurityStatusPanel")
    for forbidden in [
        "refresh_token",
        "access_token",
        "client_secret",
        "sk_live",
        "whsec",
        'data-saas-action="plan-ebay-oauth"',
        'data-saas-action="create-checkout-session"',
        "createStripeCheckout",
        "auto_publish",
        "skip_confirmation",
    ]:
        if forbidden in scope.lower():
            return fail(f"owner launch-control panel must not contain unsafe marker: {forbidden}")

    confirm_scope = _function_scope(app_js, "function saasWorkbenchApprovalBriefMarkup", "function saasWorkbenchActionLabel")
    for marker in [
        "function saasConfirmationApprovalLevel",
        "function saasConfirmationImpactRows",
        "function saasConfirmationEvidenceChecklist",
        "function saasConfirmationRollbackPlan",
        "P0 money movement",
        "P1 platform write",
        "P1 buyer promise",
        "no_secret",
        "saas-confirm-approval-brief",
    ]:
        if marker not in confirm_scope:
            return fail(f"confirmation approval brief missing marker: {marker}")
    for forbidden in ["sk_live", "whsec", "refresh_token", "access_token", "client_secret"]:
        if forbidden in confirm_scope.lower():
            return fail(f"confirmation approval brief must not contain unsafe marker: {forbidden}")

    print("PASS jiejing_owner_launch_control_ui")
    return 0


def _function_scope(text: str, start_marker: str, end_marker: str) -> str:
    try:
        start = text.index(start_marker)
        end = text.index(end_marker, start)
    except ValueError as exc:
        raise AssertionError(f"missing function scope marker: {exc}") from exc
    return text[start:end]


if __name__ == "__main__":
    raise SystemExit(main())
