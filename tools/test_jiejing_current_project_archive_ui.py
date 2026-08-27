#!/usr/bin/env python3
"""Static contract: current Listing project and history cannot share progress."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    app_js = (ROOT / "app.js").read_text(encoding="utf-8")
    required = (
        "saasMerchantProjectStatus",
        "/merchant-project-status?project_id=",
        "merchant_project_status_v1",
        "renderSaasMerchantProjectStatusStrip",
        "syncSaasProjectRoute",
    )
    for marker in required:
        if marker not in app_js:
            raise AssertionError(f"current project status integration missing: {marker}")

    status_scope_start = app_js.index("function renderSaasMerchantProjectStatusStrip")
    status_scope_end = app_js.index("function ", status_scope_start + 20)
    status_scope = app_js[status_scope_start:status_scope_end]
    for forbidden in ("旧手机壳", "OLD-CASE", "JJ-DRAFT-PROOF", "media_job_a82cc638bf481bb7"):
        if forbidden in status_scope:
            raise AssertionError(f"current project strip contains historical fixture: {forbidden}")

    if "URLSearchParams" not in app_js or 'searchParams.set("project"' not in app_js:
        raise AssertionError("view routing does not preserve the opaque current project")

    print("PASS jiejing_current_project_archive_ui")


if __name__ == "__main__":
    main()
