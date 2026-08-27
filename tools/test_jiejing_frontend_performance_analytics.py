#!/usr/bin/env python3
"""Verify privacy-safe page and lazy-module performance analytics."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.operations_metering import sanitize_analytics_event  # noqa: E402


def main() -> int:
    analytics_js = (ROOT / "assets" / "jiejing-first-party-analytics.js").read_text(encoding="utf-8")
    app_js = (ROOT / "app.js").read_text(encoding="utf-8")
    ops_js = (ROOT / "ops.js").read_text(encoding="utf-8")
    repository = (ROOT / "jiejing_saas" / "repository.py").read_text(encoding="utf-8")

    for marker in (
        "PerformanceObserver",
        'getEntriesByType("navigation")',
        'getEntriesByName("first-contentful-paint")',
        'track("performance_sample"',
        "markAppShellReady",
        "page_load",
        "app_shell_ready_ms",
        "cls_milli",
        "navigator.webdriver",
        "__JIEJING_ANALYTICS_TEST_MODE__",
        "Automated browser traffic is excluded",
    ):
        assert marker in analytics_js, marker

    for forbidden in (
        "navigator.userAgent",
        "document.referrer",
        "location.href",
        "location.search",
        "performance.getEntriesByType(\"resource\")",
    ):
        assert forbidden not in analytics_js, forbidden

    for marker in (
        'trackPerformance?.("settings_module"',
        'recordPerformance("success")',
        'recordPerformance("error")',
        "markAppShellReady",
    ):
        assert marker in app_js, marker

    for marker in (
        "performance_analytics",
        "首屏体验 P75",
        "设置模块 P75",
    ):
        assert marker in ops_js, marker

    clean = sanitize_analytics_event(
        {
            "event_key": "performance_sample",
            "page_key": "workbench",
            "visitor_id": "visitor",
            "session_id": "session",
            "event_id": "event",
            "metadata": {
                "performance_scope": "page_load",
                "outcome": "success",
                "ttfb_ms": "152",
                "fcp_ms": 380,
                "lcp_ms": 740,
                "cls_milli": 3,
                "dom_ready_ms": 610,
                "load_complete_ms": 880,
                "app_shell_ready_ms": 690,
                "raw_url": "must-not-pass",
                "prompt": "must-not-pass",
            },
        }
    )
    assert clean["metadata"] == {
        "performance_scope": "page_load",
        "outcome": "success",
        "ttfb_ms": 152,
        "fcp_ms": 380,
        "lcp_ms": 740,
        "cls_milli": 3,
        "dom_ready_ms": 610,
        "load_complete_ms": 880,
        "app_shell_ready_ms": 690,
    }

    clamped = sanitize_analytics_event(
        {
            "event_key": "performance_sample",
            "page_key": "workbench",
            "visitor_id": "visitor",
            "session_id": "session",
            "event_id": "event-2",
            "metadata": {
                "performance_scope": "settings_module",
                "outcome": "error",
                "duration_ms": 999999999,
                "ttfb_ms": -2,
            },
        }
    )
    assert clamped["metadata"] == {
        "performance_scope": "settings_module",
        "outcome": "error",
        "duration_ms": 120000,
    }

    for marker in (
        'event_key = \'performance_sample\'',
        '"performance_analytics"',
        '"sample_count"',
        '"p75"',
        '"raw_url_stored": False',
    ):
        assert marker in repository, marker

    print("PASS jiejing_frontend_performance_analytics")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
