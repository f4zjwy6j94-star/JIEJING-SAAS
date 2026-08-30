#!/usr/bin/env python3
"""Freeze the merchant workflow while the premium UI shell is refactored."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    app_html = (ROOT / "app.html").read_text(encoding="utf-8")
    app_js = (ROOT / "app.js").read_text(encoding="utf-8")
    styles = (ROOT / "styles.css").read_text(encoding="utf-8")

    if 'id="appShell"' not in app_html or 'data-ui-generation="premium-merchant-workbench-v1"' not in app_html:
        raise AssertionError("merchant app shell must carry the premium workbench generation marker")

    nav_source = app_html[app_html.index('<nav class="nav-list"') : app_html.index("</nav>", app_html.index('<nav class="nav-list"'))]
    labels = re.findall(r'<button class="nav-item[^>]*data-view="([^"]+)"[^>]*>.*?<span>([^<]+)</span>\s*</button>', nav_source, flags=re.S)
    expected = [
        ("cockpit", "AI CEO"),
        ("product", "选品与上架"),
        ("media", "素材工坊"),
        ("confirm", "确认中心"),
        ("service", "客服与订单"),
        ("connect", "设置"),
    ]
    if labels != expected:
        raise AssertionError(f"merchant primary navigation drifted: {labels}")
    if 'data-view="activity"' in nav_source or 'data-view="bulk"' in nav_source:
        raise AssertionError("records and bulk modes must not re-enter primary navigation")

    for alias in ('activity: "cockpit"', 'report: "cockpit"', 'reports: "cockpit"'):
        if alias not in app_js:
            raise AssertionError(f"legacy record route is not safely normalized: {alias}")
    if 'data-internal-view="legacy-report-center" hidden' not in app_html:
        raise AssertionError("legacy records must remain preserved but unreachable from the merchant shell")

    for business_contract in (
        "handleSaasAiCeoImportMarketToListing",
        "approveLatestSaasMediaAssetJobForListingDraft",
        "createSaasExistingDraftPublishConfirmation",
        "approveFirstSaasConfirmation",
        "publish_listing",
        "save_ebay_listing_draft",
    ):
        if business_contract not in app_js:
            raise AssertionError(f"premium UI refactor lost a merchant workflow contract: {business_contract}")

    for token in (
        "--jiejing-shell-rail",
        "--jiejing-shell-canvas",
        "--jiejing-focus-ring",
        "premium-merchant-workbench-v1",
    ):
        if token not in styles:
            raise AssertionError(f"premium workbench design token missing: {token}")
    if "@media (prefers-reduced-motion: reduce)" not in styles:
        raise AssertionError("premium workbench must provide reduced-motion behavior")
    if "scroll-margin-top" not in styles:
        raise AssertionError("workbench anchors must stay visible below sticky chrome")

    print("PASS jiejing_workbench_contract_freeze")


if __name__ == "__main__":
    main()
