#!/usr/bin/env python3
"""Regression for the new eBay account low-risk runbook and checker."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNBOOK = ROOT / "docs" / "JIEJING_NEW_EBAY_ACCOUNT_LOW_RISK_RUNBOOK_20260617.md"
CHECKER = ROOT / "tools" / "jiejing_new_ebay_account_low_risk_check.py"


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    text = RUNBOOK.read_text(encoding="utf-8")
    app_js = (ROOT / "app.js").read_text(encoding="utf-8")
    for marker in [
        "Do not repeat OAuth for the old frozen account",
        "New product check",
        "Publish health report",
        "Confirmation center",
        "Post-publish cockpit",
        "Test cleanup",
        "JIEJING_NEW_EBAY_OLD_FROZEN_ACCOUNT_REJECTED",
        "JIEJING_NEW_EBAY_OAUTH_OPERATOR_APPROVED",
        "JIEJING_NEW_EBAY_FRESH_PRODUCT_DECLARED",
        "JIEJING_NEW_EBAY_FRESH_SKU_DECLARED",
        "JIEJING_NEW_EBAY_FRESH_ASSETS_DECLARED",
        "JIEJING_NEW_EBAY_NO_OLD_LISTING_OR_REPORT_REUSE",
        "JIEJING_NEW_EBAY_PUBLISH_CONFIRMATION_APPROVED",
        "JIEJING_NEW_EBAY_CLEANUP_CONFIRMATION_APPROVED",
    ]:
        if marker not in text:
            return fail(f"runbook missing marker: {marker}")
    for forbidden in ["refresh token=", "api key=", "password=", "client secret="]:
        if forbidden in text.lower():
            return fail(f"runbook should not contain secret-shaped instruction: {forbidden}")

    for marker in [
        "function renderSaasNewEbayAccountOnboardingPanel",
        "saas-new-ebay-onboarding-panel",
        "old_frozen_account_reuse_allowed=false",
        "triggers_ebay_oauth=false",
        "triggers_real_platform_write=false",
        "repeat_oauth_allowed=false",
        "本面板没有 eBay 授权按钮",
        "renderSaasNewEbayAccountOnboardingPanel()",
    ]:
        if marker not in app_js:
            return fail(f"app.js missing new-account onboarding marker: {marker}")

    completed = subprocess.run(
        [sys.executable, str(CHECKER), "--checklist-only"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if completed.returncode != 0:
        return fail(f"checklist mode should pass: {completed.stderr}")
    payload = json.loads(completed.stdout)
    if payload.get("contract_version") != "2026-06-18-new-ebay-account-low-risk-smoke":
        return fail(f"checklist should expose the runbook contract version: {payload}")
    phases = {item.get("key"): item for item in payload.get("phases", []) if isinstance(item, dict)}
    if set(phases) != {
        "public_preflight_ready",
        "clean_new_account_declared",
        "new_account_oauth_authorization_gate",
        "official_packet_account_health_snapshot",
        "new_product_duplicate_guard",
        "publish_health_confirmation_gate",
        "controlled_real_publish_probe",
        "post_publish_cockpit_cleanup_gate",
    }:
        return fail(f"checklist phases missing or unexpected: {sorted(phases)}")
    if payload.get("phase_count") != 8:
        return fail(f"checklist phase_count should be 8: {payload.get('phase_count')}")
    required_flags = payload.get("required_operator_flags") if isinstance(payload.get("required_operator_flags"), dict) else {}
    expected_required_flags = {
        "account_boundary": {"JIEJING_NEW_EBAY_ACCOUNT_CONFIRMED_CLEAN", "JIEJING_NEW_EBAY_OLD_FROZEN_ACCOUNT_REJECTED"},
        "oauth_boundary": {"JIEJING_NEW_EBAY_OAUTH_OPERATOR_APPROVED", "JIEJING_NEW_EBAY_ACCOUNT_OAUTH_COMPLETED"},
        "fresh_product_boundary": {
            "JIEJING_NEW_EBAY_FRESH_PRODUCT_DECLARED",
            "JIEJING_NEW_EBAY_FRESH_SKU_DECLARED",
            "JIEJING_NEW_EBAY_FRESH_ASSETS_DECLARED",
            "JIEJING_NEW_EBAY_NO_OLD_LISTING_OR_REPORT_REUSE",
            "JIEJING_NEW_EBAY_PRODUCT_DUPLICATE_GUARD_PASSED",
        },
        "publish_confirmation": {"JIEJING_NEW_EBAY_PUBLISH_HEALTH_CONFIRMATION_READY", "JIEJING_NEW_EBAY_PUBLISH_CONFIRMATION_APPROVED"},
        "controlled_real_publish": {"JIEJING_NEW_EBAY_PUBLISH_CONFIRMATION_APPROVED", "JIEJING_NEW_EBAY_ACCOUNT_REAL_PUBLISH_PASSED"},
        "cleanup_confirmation": {"JIEJING_NEW_EBAY_CLEANUP_CONFIRMATION_APPROVED", "JIEJING_NEW_EBAY_TEST_CLEANUP_CONFIRMED"},
    }
    for key, expected in expected_required_flags.items():
        actual = set(required_flags.get(key) or [])
        if actual != expected:
            return fail(f"checklist required flags mismatch for {key}: {sorted(actual)}")
    for key, phase in phases.items():
        if phase.get("secret_exposed") is not False:
            return fail(f"phase must not expose secrets: {key}")
        if phase.get("old_frozen_account_reuse_allowed") is not False:
            return fail(f"phase must forbid old frozen account reuse: {key}")
        if phase.get("old_demo_product_or_sku_allowed") is not False:
            return fail(f"phase must forbid old demo product/SKU reuse: {key}")
        if phase.get("triggers_real_platform_write") is not False:
            return fail(f"phase must not trigger a platform write from the checker: {key}")
    if phases["new_account_oauth_authorization_gate"].get("triggers_ebay_oauth") is not False:
        return fail("OAuth phase must not start OAuth from checklist/checker")
    if phases["new_account_oauth_authorization_gate"].get("repeat_oauth_allowed") is not False:
        return fail("OAuth phase must forbid silent OAuth repeat")
    if "owner approval to start new-account OAuth" not in phases["new_account_oauth_authorization_gate"].get("required_evidence", []):
        return fail("OAuth phase must require owner approval before any new-account OAuth")
    for evidence_marker in ["fresh product", "fresh SKU", "fresh images", "no old listing/report reuse", "duplicate guard proof"]:
        if evidence_marker not in phases["new_product_duplicate_guard"].get("required_evidence", []):
            return fail(f"product duplicate guard must require {evidence_marker}")
    if phases["controlled_real_publish_probe"].get("confirmation_center_required") is not True:
        return fail("real publish probe must require confirmation center")
    if phases["post_publish_cockpit_cleanup_gate"].get("confirmation_center_required") is not True:
        return fail("cleanup gate must require confirmation center")
    sequence = payload.get("sequence") or []
    if "new eBay account OAuth" not in sequence or "real publish" not in sequence:
        return fail(f"checklist should include new-account OAuth and real publish gates: {payload}")
    if payload.get("secret_exposed") is not False:
        return fail("checklist output should keep secret_exposed=false")
    print("PASS jiejing_new_ebay_account_low_risk_runbook")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
