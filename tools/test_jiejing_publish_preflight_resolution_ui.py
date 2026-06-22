#!/usr/bin/env python3
"""Static guard for backend publish preflight resolution routing UI."""

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

    for marker in [
        "function saasBackendPublishEvidenceTrust",
        "function saasBackendPublishRepairRoute",
        "function renderSaasBackendPreflightResolutionBoard",
        "data-preflight-resolution-board",
        "data-preflight-fix-action",
        "data-preflight-source-count",
        "data-preflight-confirm-route",
        "证据可信度",
        "修复入口",
        "确认中心路由",
        "source_records_visible",
        "no_secret_fields_rendered",
        "decision_center_required",
        "real_write_allowed_without_confirmation=",
        "renderSaasBackendPreflightResolutionBoard(readiness)",
    ]:
        if marker not in app_js:
            return fail(f"app.js missing preflight resolution marker: {marker}")

    for marker in [
        ".saas-backend-preflight-resolution-board",
        ".saas-backend-preflight-resolution",
        ".saas-backend-preflight-resolution article.is-green",
        ".saas-backend-preflight-resolution article.is-amber",
        ".saas-backend-preflight-resolution article.is-red",
    ]:
        if marker not in styles:
            return fail(f"styles.css missing preflight resolution marker: {marker}")

    for marker in [
        '"source_records": source_records',
        '"fix_action": fix_action',
        '"confirmation_gate": _publish_check_confirmation_gate',
        '"can_trigger_real_write": False',
        '"real_write_allowed_without_confirmation": False',
        '"requires_confirmation_center": True',
    ]:
        if marker not in backend:
            return fail(f"backend missing safe preflight evidence marker: {marker}")

    helper_start = app_js.index("function saasBackendPublishEvidenceTrust")
    helper_end = app_js.index("function saasBackendPublishImpact", helper_start)
    helper_body = app_js[helper_start:helper_end].lower()
    for forbidden in [
        "access_token",
        "refresh_token",
        "client_secret",
        "authorization header",
        "real_write_allowed_without_confirmation: true",
        "cantriggerrealwrite: true",
    ]:
        if forbidden in helper_body:
            return fail(f"preflight resolution helpers must not expose unsafe marker: {forbidden}")

    print("PASS jiejing_publish_preflight_resolution_ui")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
