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
    app_html = (ROOT / "app.html").read_text(encoding="utf-8")
    app_text = (ROOT / "app.js").read_text(encoding="utf-8")

    for marker in [
        "旅行压缩收纳袋",
        "便携首饰盒",
        "香薰蜡烛套装",
        "倒流香炉",
        "Backflow Incense",
        "backflow incense",
        "IP 防侵权",
        "侵权检测通过",
        "Home Decor / Incense",
        "Waterfall smoke effect",
        "JJ-BFI-001",
    ]:
        if marker.lower() in app_html.lower():
            return fail(f"merchant app shell must not expose fixed product fixtures or unsafe claims: {marker}")

    cockpit_start = app_html.find('<section class="view is-active" id="view-cockpit"')
    cockpit_end = app_html.find('<section class="view" id="view-dna"', cockpit_start)
    if cockpit_start < 0 or cockpit_end < 0:
        return fail("merchant workbench static cockpit boundary is missing")
    merchant_static_workbench = app_html[cockpit_start:cockpit_end]
    for marker in [
        "倒流香炉",
        "Backflow Incense",
        "backflow-incense",
        "旅行压缩收纳袋",
        "便携首饰盒",
        "香薰蜡烛套装",
        "Ceramic / Resin style finish",
        "Bronze / Brown",
        "Incense burner only",
        "是否含香粒",
    ]:
        if marker in merchant_static_workbench:
            return fail(f"merchant static workbench must not seed a fixed product: {marker}")
    if 'data-merchant-blank-workbench="merchant_blank_workbench_v1"' not in merchant_static_workbench:
        return fail("merchant static workbench must expose the approved blank-state contract")

    entry_start = app_html.find('<div class="entry-shell" id="entryShell">')
    entry_end = app_html.find('<div class="site-shell is-hidden" id="siteShell">', entry_start)
    if entry_start < 0 or entry_end < 0:
        return fail("merchant entry shell boundary is missing")
    merchant_entry_shell = app_html[entry_start:entry_end]
    for marker in ["旅行压缩收纳袋", "倒流香炉", "Backflow Incense", "新手商家，还没开店", "IP 防侵权"]:
        if marker in merchant_entry_shell:
            return fail(f"merchant entry shell must not seed a fixed product or retired promise: {marker}")
    for marker in ["免费生成第一条草稿", "已有 eBay 店铺", "多店铺", "侵权风险初筛，仍需商家核对"]:
        if marker not in merchant_entry_shell:
            return fail(f"merchant entry shell is missing approved merchant copy: {marker}")

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

    account_tab_start = app_text.index('id: "account",', app_text.index("function saasSettingsTabDefinitions"))
    account_tab_end = app_text.index('id: "model",', account_tab_start)
    account_tab = app_text[account_tab_start:account_tab_end]
    if "renderSaasSettingsAccountWorkspace(ctx, options)" not in account_tab:
        return fail("account settings must render its account and store workspace")
    workspace_start = app_text.index("function renderSaasSettingsAccountWorkspace")
    workspace_end = app_text.index("\nfunction ", workspace_start + 1)
    account_workspace = app_text[workspace_start:workspace_end]
    if "renderSaasAccountHealthPanel()" not in account_workspace:
        return fail("account settings must render the detailed account-health incident and recovery guidance")
    if "renderSaasMerchantOnboardingPanel({ compact: true, accountWorkspace: true })" not in account_workspace:
        return fail("account workspace must keep its compact onboarding next action visible")

    print("PASS jiejing_merchant_onboarding_frontend")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
