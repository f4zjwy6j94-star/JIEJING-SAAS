#!/usr/bin/env python3
"""Static contract checks for the landing guide and evidence-led workbench handoff."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    index_text = (ROOT / "index.html").read_text(encoding="utf-8")
    app_text = (ROOT / "app.js").read_text(encoding="utf-8")

    for marker in (
        'const ENTRY_MERCHANT_ONBOARDING_PATH = "/merchant-onboarding/primary-ebay"',
        'const OFFICIAL_EBAY_SELLER_REGISTRATION_URL = "https://www.ebay.com/sl/sell"',
        "async function loadEntryMerchantOnboarding",
        "async function saveEntryMerchantOnboarding",
        "function renderEntrySellerRegistrationAction",
        'window.addEventListener("focus", handleEntrySellerRegistrationReturn)',
        '"noopener,noreferrer"',
        "sellerReturned: true",
        "entry_onboarding_backend_v1",
    ):
        if marker not in index_text:
            return fail(f"landing onboarding closure is missing: {marker}")

    finish_match = re.search(r"function finishGuideAndOpenWorkspace\(.*?\n\s*}\n", index_text, flags=re.DOTALL)
    if not finish_match:
        return fail("landing guide completion function is missing")
    finish_text = finish_match.group(0)
    if "saveEntryMerchantOnboarding" not in finish_text:
        return fail("entering the workbench must persist the backend onboarding state first")
    if "markEntryOnboardingCompleted" in finish_text:
        return fail("local completion flags must not override backend onboarding truth")

    for marker in (
        "saasMerchantOnboarding: null",
        'optionalSaasFetchFast("/merchant-onboarding/primary-ebay"',
        "function renderSaasMerchantOnboardingPanel",
        "merchant_onboarding_single_next_step_v1",
        "business_policy_statuses",
        'key: "open-official-ebay-seller-registration"',
        'key: "sync-ebay-readonly"',
        "triggers_real_platform_write=false",
    ):
        if marker not in app_text:
            return fail(f"workbench onboarding closure is missing: {marker}")

    if "innerHTML = merchantOnboarding" in app_text:
        return fail("backend onboarding values must not be inserted as unescaped HTML")

    print("PASS jiejing_merchant_onboarding_frontend")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
