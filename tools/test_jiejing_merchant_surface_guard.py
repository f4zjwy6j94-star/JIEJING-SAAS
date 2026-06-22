#!/usr/bin/env python3
"""Static guard for merchant-facing Jiejing SaaS surfaces.

This test is intentionally narrow: internal engineering terms may remain in
backend code or hidden operator-only branches, but the public homepage and the
merchant workbench render paths must stay focused on seller value.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


PUBLIC_FORBIDDEN = [
    "Public staging",
    "Public/staging",
    "<em>Staging</em>",
    "Jiejing Runtime",
    "Runtime API",
    "Hermes",
    "商用上线前",
    "正式上线前",
    "项目完善度",
    "演示产品成熟度",
    "正式上线准备",
    "Postgres",
    "Redis",
    "Vault",
    "KMS",
]

PUBLIC_VISIBLE_FORBIDDEN = [
    "模拟",
    "演示",
    "内测",
    "测试用",
    "Demo",
    "demo",
    "Mock",
    "mock",
    "Sample",
    "sample",
    "simulated",
    "tutorial",
]


MERCHANT_SCOPE_FUNCTIONS = [
    "renderGlobalLoopWorkbench",
    "renderSaasCockpitLiveStrip",
    "renderLaunchGapBoard",
    "renderSaasMerchantTruthPanel",
    "renderSaasMerchantOperatingPath",
    "renderSaasMerchantAiValueMap",
    "renderSaasMerchantDataCoveragePanel",
    "renderSaasMerchantAiValuePanel",
    "renderSaasMerchantWorkbenchPanel",
    "renderSaasCockpitRealWorkbench",
    "renderSaasProductListingCenter",
    "applySaasReportsToActivities",
    "applySaasDataPacketsToActivities",
    "renderTaskSplitStatusBoard",
    "renderReadinessScoreBoard",
]


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def visible_text(html: str) -> str:
    text = re.sub(r"<!--.*?-->", " ", html, flags=re.S)
    text = re.sub(r"<script\b.*?</script>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<style\b.*?</style>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", "\n", text)
    return re.sub(r"\s+", " ", text)


def function_scope(source: str, name: str) -> str:
    marker = f"function {name}("
    start = source.find(marker)
    if start < 0:
        raise ValueError(f"missing function {name}")
    next_match = re.search(r"\nfunction\s+\w+\(", source[start + len(marker) :])
    if not next_match:
        return source[start:]
    end = start + len(marker) + next_match.start()
    return source[start:end]


def main() -> int:
    index_html = (ROOT / "index.html").read_text(encoding="utf-8")
    app_html = (ROOT / "app.html").read_text(encoding="utf-8")
    app_js = (ROOT / "app.js").read_text(encoding="utf-8")
    public_text = visible_text(index_html)
    app_static_text = visible_text(app_html)

    for marker in PUBLIC_FORBIDDEN:
        if marker in public_text:
            return fail(f"public homepage visible text exposes internal marker: {marker}")

    for marker in PUBLIC_VISIBLE_FORBIDDEN:
        if marker in public_text:
            return fail(f"public homepage visible text still feels simulated: {marker}")
        if marker in app_static_text:
            return fail(f"merchant workbench static text still feels simulated: {marker}")

    if "捷境 JIEJING / eBay 自动化工作台" not in public_text:
        return fail("public homepage should lead with the merchant product positioning")
    if "登录后按四种商家身份进入向导" not in public_text:
        return fail("public homepage should explain the login-to-onboarding flow")

    for function_name in MERCHANT_SCOPE_FUNCTIONS:
        scope = function_scope(app_js, function_name)
        for marker in PUBLIC_FORBIDDEN:
            if marker in scope:
                return fail(f"{function_name} exposes internal marker: {marker}")
        if function_name == "renderSaasProductListingCenter":
            for marker in ["测试草稿", "倒流香炉", "Backflow Incense", "旅行压缩收纳袋"]:
                if marker in scope:
                    return fail(f"{function_name} leaks legacy listing sample into real SaaS workbench: {marker}")

    cockpit_scope = function_scope(app_js, "renderSaasCockpitRealWorkbench")
    for marker in ["倒流香炉", "Backflow Incense", "5 个候选品", "1688 货源图"]:
        if marker in cockpit_scope:
            return fail(f"renderSaasCockpitRealWorkbench leaks legacy cockpit sample into real SaaS workbench: {marker}")

    for required_guard in [
        "function normalizeSaasProtectedView",
        "function hasCompletedSaasOnboarding",
        "function markSaasOnboardingCompleted",
        "openApp(normalizeSaasProtectedView(params.get(\"view\") || \"cockpit\"));",
        "markSaasOnboardingCompleted();",
    ]:
        if required_guard not in app_js:
            return fail(f"real SaaS route/onboarding guard missing: {required_guard}")

    for required in [
        "AI CEO 经营价值核对",
        "eBay 经营数据同步",
        "AI CEO 经营输出",
        "确认中心",
        "发布、付款、退款、改价或承诺买家",
        "AI CEO 只接收标准数据包",
    ]:
        if required not in app_js:
            return fail(f"merchant workbench is missing required product copy: {required}")

    print("PASS jiejing_merchant_surface_guard")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
