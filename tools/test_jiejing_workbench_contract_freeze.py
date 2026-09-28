#!/usr/bin/env python3
"""Freeze the merchant workflow while the premium UI shell is refactored."""

from __future__ import annotations

import re
import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def assert_mutation_guard(script: Path) -> None:
    probe = """
const { assertSafeMutationBase } = require(process.argv[1]);
try { assertSafeMutationBase(process.argv[2]); process.stdout.write("ALLOW"); }
catch (error) { process.stdout.write(`BLOCK:${error.message}`); process.exitCode = 2; }
"""
    cases = [
        ("https://jiejing.shop", True, "jiejing.shop", False),
        ("https://app.jiejing.shop", True, "app.jiejing.shop", False),
        ("https://jiejing.shop.", True, "jiejing.shop", False),
        ("https://APP.JIEJING.SHOP.", True, "app.jiejing.shop", False),
        ("http://43.129.169.223", True, "43.129.169.223", False),
        ("http://43.129.205.244", True, "43.129.205.244", False),
        ("http://[::ffff:43.129.169.223]", True, "43.129.169.223", False),
        ("http://[::ffff:2b81:a9df]", True, "43.129.169.223", False),
        ("http://[0:0:0:0:0:ffff:2b81:cdf4]", True, "43.129.205.244", False),
        ("http://[::ffff:192.0.2.1]", True, "192.0.2.1", True),
        ("https://test.invalid", False, "test.invalid", False),
        ("https://test.invalid", True, "", False),
        ("https://test.invalid", True, "other.invalid", False),
        ("https://test.invalid.", True, "test.invalid", True),
        ("http://127.0.0.1:8788", False, "", True),
        ("http://localhost:8788", False, "", True),
        ("http://[::1]:8788", False, "", True),
    ]
    for target, opt_in, allowlist, expected_allow in cases:
        env = os.environ.copy()
        if opt_in:
            env["JIEJING_ALLOW_REMOTE_TEST_MUTATION"] = "true"
        else:
            env.pop("JIEJING_ALLOW_REMOTE_TEST_MUTATION", None)
        env["JIEJING_REMOTE_TEST_HOSTS"] = allowlist
        result = subprocess.run(
            ["node", "-e", probe, str(script), target],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        allowed = result.returncode == 0 and result.stdout == "ALLOW"
        if allowed != expected_allow:
            raise AssertionError(f"mutation guard result drifted for {target} opt_in={opt_in} allowlist={allowlist}: {result.stdout} {result.stderr}")


def main() -> None:
    app_html = (ROOT / "app.html").read_text(encoding="utf-8")
    app_js = (ROOT / "app.js").read_text(encoding="utf-8")
    styles = (ROOT / "styles.css").read_text(encoding="utf-8")
    index_html = (ROOT / "index.html").read_text(encoding="utf-8")
    merchant_project_smoke = (ROOT / "tools" / "codex_jiejing_merchant_project_status_browser_smoke.js").read_text(encoding="utf-8")

    if 'id="appShell"' not in app_html or 'data-ui-generation="premium-merchant-workbench-v1"' not in app_html:
        raise AssertionError("merchant app shell must carry the premium workbench generation marker")

    nav_source = app_html[app_html.index('<nav class="nav-list"') : app_html.index("</nav>", app_html.index('<nav class="nav-list"'))]
    labels = re.findall(r'<button class="nav-item[^>]*data-view="([^"]+)"[^>]*>.*?<span>([^<]+)</span>\s*</button>', nav_source, flags=re.S)
    expected = [
        ("cockpit", "JV AI"),
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

    assert_mutation_guard(ROOT / "tools" / "jiejing_browser_smoke_mutation_guard.js")
    if "assertSafeMutationBase(base);" not in merchant_project_smoke:
        raise AssertionError("merchant project smoke must invoke its mutation guard")
    if merchant_project_smoke.index("assertSafeMutationBase(base);") > merchant_project_smoke.index("await runSmoke();"):
        raise AssertionError("merchant project smoke must refuse production before runSmoke can register an account")

    for adaptive_ai_ceo_contract in (
        "function saasAiCeoTaskContextState",
        "function renderSaasAiCeoTaskContextMarkup",
        'data-ai-ceo-task-context="adaptive_task_context_v1"',
        "data-ai-ceo-task-context-toggle",
        "data-ai-ceo-task-next-action",
    ):
        if adaptive_ai_ceo_contract not in app_js:
            raise AssertionError(f"adaptive AI CEO contract missing: {adaptive_ai_ceo_contract}")

    for listing_mode_contract in (
        'data-listing-mode="single"',
        'data-listing-mode="bulk"',
        'data-listing-mode="recent"',
        'aria-current="page"',
        "单个商品",
        "批量选品与草稿",
        "最近任务",
    ):
        if listing_mode_contract not in app_js:
            raise AssertionError(f"listing workspace mode contract missing: {listing_mode_contract}")

    workflow_steps = re.findall(r'data-home-workflow-step="([^"]+)"', index_html)
    if workflow_steps != ["goal", "research", "facts", "listing", "media", "confirm"]:
        raise AssertionError(f"public six-step workflow drifted: {workflow_steps}")

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
