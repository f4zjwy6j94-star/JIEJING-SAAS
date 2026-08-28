#!/usr/bin/env python3
"""Prevent duplicate protected-state requests during one workbench refresh."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "app.js").read_text(encoding="utf-8")


def main() -> None:
    start = APP.index("async function refreshSaasState")
    end = APP.index("function clearSaasProductFeedbackLiveIdentity", start)
    refresh = APP[start:end]

    for marker in (
        "Promise.resolve(coreSecretRefs)",
        "Promise.resolve(coreModelSettings)",
        "Promise.resolve(coreDataPackets)",
        "Promise.resolve(coreExecutions)",
    ):
        assert marker in refresh

    for endpoint_fragment in (
        "/secret-refs?store_id=",
        "/model/settings",
        "/data-packets?platform=ebay&limit=5",
        "/execution-results?limit=20",
    ):
        assert refresh.count(endpoint_fragment) == 1, endpoint_fragment

    print("PASS jiejing_workbench_boot_efficiency")


if __name__ == "__main__":
    main()
