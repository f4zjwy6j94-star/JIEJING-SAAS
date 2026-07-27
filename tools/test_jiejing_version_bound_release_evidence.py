#!/usr/bin/env python3
"""Regression for version-bound fixed launch progress evidence."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.owner_launch_control import _load_fixed_progress_release_evidence


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def write_fixture(root: Path, *, marker: str, recorded_marker: str, public_passed: bool = True) -> None:
    (root / "deploy").mkdir(parents=True, exist_ok=True)
    (root / "index.html").write_text(f'<script src="./app.js?v={marker}"></script>', encoding="utf-8")
    (root / "deploy" / "release-evidence.json").write_text(
        json.dumps(
            {
                "contract_version": "2026-07-14-version-bound-release-evidence-v1",
                "frontend_asset_version": recorded_marker,
                "precloud_gate_passed": True,
                "local_browser_smoke_passed": True,
                "public_browser_smoke_passed": public_passed,
                "secret_scan_passed": True,
                "real_merchant_workflow_validation_passed": True,
                "public_charging_approved": False,
            }
        ),
        encoding="utf-8",
    )


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="jiejing-release-evidence-") as temp:
        root = Path(temp)
        write_fixture(root, marker="release-v1", recorded_marker="release-v1")
        matching = _load_fixed_progress_release_evidence(root)
        if matching.get("browser_smoke_passed") is not True:
            return fail(f"matching release evidence should pass: {matching}")
        if matching.get("frontend_asset_version") != "release-v1":
            return fail(f"current marker missing: {matching}")
        if matching.get("public_domain_tls_passed") is not True:
            return fail(f"matching HTTPS release evidence should prove the public domain route: {matching}")
        if matching.get("real_merchant_workflow_validation_passed") is not False:
            return fail(f"manual release JSON must not award real merchant validation points: {matching}")
        if matching.get("manual_real_merchant_validation_flag_ignored") is not True:
            return fail(f"manual merchant validation flag should be explicitly ignored: {matching}")

        write_fixture(root, marker="release-v2", recorded_marker="release-v1")
        stale = _load_fixed_progress_release_evidence(root)
        if stale.get("browser_smoke_passed") is not False:
            return fail(f"stale evidence must not pass a newer release: {stale}")

        write_fixture(root, marker="release-v2", recorded_marker="release-v2", public_passed=False)
        incomplete = _load_fixed_progress_release_evidence(root)
        if incomplete.get("browser_smoke_passed") is not False:
            return fail(f"incomplete public smoke must not earn progress: {incomplete}")

        serialized = str(matching).lower()
        for forbidden in ("api_key", "client_secret", "refresh_token", "access_token", "payment_secret"):
            if forbidden in serialized:
                return fail(f"release evidence must not expose secret-like fields: {forbidden}")

    print("PASS jiejing_version_bound_release_evidence")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
