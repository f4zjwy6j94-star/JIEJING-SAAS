#!/usr/bin/env python3
"""The browser may send evidence identifiers, never award image rights itself."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def function_body(source: str, name: str) -> str:
    start = source.index(f"function {name}(")
    next_function = source.find("\nfunction ", start + 1)
    return source[start : next_function if next_function >= 0 else len(source)]


def main() -> None:
    app_js = (ROOT / "app.js").read_text(encoding="utf-8")
    body = function_body(app_js, "readSaasPublishIntakeForm")
    assert "publish_evidence_refs" in body, body
    assert "product_fact_report_id" in body, body
    assert "media_job_id" in body, body
    assert "asset_id" in body, body
    assert 'source: "merchant_publish_confirmation_intake"' not in body, body
    for forbidden in (
        "rights_status",
        "commercial_use_status",
        "review_status",
        "reviewed_by",
        "reviewed_at",
        "server_resolved",
    ):
        assert forbidden not in body, (forbidden, body)
    print("PASS jiejing_publish_intake_evidence_refs")


if __name__ == "__main__":
    main()
