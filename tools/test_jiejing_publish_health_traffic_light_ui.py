#!/usr/bin/env python3
"""Static guard for the publish-health red/yellow/green report."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    app_js = (ROOT / "app.js").read_text(encoding="utf-8")
    styles = (ROOT / "styles.css").read_text(encoding="utf-8")
    backend = (ROOT / "jiejing_saas" / "ebay_write_adapter.py").read_text(encoding="utf-8")

    required_backend_markers = [
        '"traffic_light_report": traffic_light_report',
        '"backend_evidence_packet": _publish_readiness_evidence_packet',
        "2026-06-18-publish-health-traffic-light",
        "2026-06-19-backend-publish-preflight-evidence",
        '"red_count": len(red)',
        '"yellow_count": len(yellow)',
        '"green_count": len(green)',
        '"requires_confirmation_center": True',
        '"real_write_allowed_without_confirmation": False',
        '"secret_exposed": False',
        '"source_records": source_records',
        '"fix_action": fix_action',
        '"confirmation_gate": _publish_check_confirmation_gate',
        "def _publish_check_source_records",
        "def _publish_check_fix_action",
    ]
    for marker in required_backend_markers:
        if marker not in backend:
            return fail(f"backend missing publish traffic-light marker: {marker}")

    required_app_markers = [
        "function saasPublishTrafficLightReport",
        "function renderSaasPublishTrafficLightReport",
        "function renderSaasBackendPublishPreflightPanel",
        "function renderSaasPublishConfirmationEvidencePanel",
        "function saasBackendPublishFixAction",
        "function saasBackendPreflightDetailRows",
        "check.source_records",
        "check.fix_action",
        "backend_evidence_packet",
        "证据已整理；敏感连接信息不会显示在页面里",
        "backend fix_action safe",
        "readiness?.traffic_light_report",
        "real_write_allowed_without_confirmation: false",
        "state.saasLastPublishConfirmationEvidence",
        "renderSaasPublishConfirmationEvidencePanel(readiness, ctx)",
        "确认单与系统体检",
        "真实 eBay 写入仍必须走确认中心",
        "敏感连接信息不会显示在页面里",
        "renderSaasPublishTrafficLightReport(readiness)",
        "renderSaasBackendPublishPreflightPanel(readiness, ctx, options)",
        'data-saas-action="open-confirm"',
        'data-preflight-key="${escapeHtml(check.key || "")}"',
        'check.blocking ? "is-red"',
        "saas-publish-traffic-summary",
        "系统体检已回填，先修红项，再进确认中心",
    ]
    for marker in required_app_markers:
        if marker not in app_js:
            return fail(f"app.js missing publish traffic-light marker: {marker}")

    required_style_markers = [
        ".saas-backend-preflight-panel",
        ".saas-publish-confirmation-evidence",
        ".saas-publish-confirmation-evidence-grid",
        ".saas-backend-preflight-summary",
        ".saas-backend-preflight-card.is-red",
        ".saas-backend-preflight-details",
        ".saas-confirm-summary article.is-green",
        ".saas-confirm-summary article.is-amber",
        ".saas-confirm-summary article.is-red",
        ".saas-confirm-summary article.saas-publish-traffic-summary",
        "grid-column: 1 / -1",
    ]
    for marker in required_style_markers:
        if marker not in styles:
            return fail(f"styles.css missing publish traffic-light marker: {marker}")

    print("PASS jiejing_publish_health_traffic_light_ui")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
