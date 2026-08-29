#!/usr/bin/env python3
"""Static contract for the simplified merchant entry and bounded free trial."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    index = (ROOT / "index.html").read_text(encoding="utf-8")
    app_html = (ROOT / "app.html").read_text(encoding="utf-8")
    app = (ROOT / "app.js").read_text(encoding="utf-8")
    api = (ROOT / "jiejing_saas" / "api_server.py").read_text(encoding="utf-8")
    readiness = (ROOT / "jiejing_saas" / "readiness.py").read_text(encoding="utf-8")

    public_path_buttons = re.findall(r'<button class="path-card[^>]*data-path="([^"]+)"', index)
    if public_path_buttons != ["trial", "opened", "multi"]:
        return fail(f"public entry must present free/single/multi only: {public_path_buttons}")

    public_plan_buttons = re.findall(
        r'<button class="path-card[^>]*data-path="([^"]+)"[^>]*data-plan="([^"]+)"',
        index,
    )
    if public_plan_buttons != [("trial", "free"), ("opened", "single"), ("multi", "multi")]:
        return fail(f"public path and pricing choices must be merged: {public_plan_buttons}")
    if 'class="price-card' in index:
        return fail("public homepage must not repeat the three choices in a second pricing grid")

    hero_cta_match = re.search(
        r'document\.querySelector\("#heroWorkbenchLogin"\)\?\.addEventListener\("click",\s*\(\)\s*=>\s*\{(.*?)\n\s*\}\);',
        index,
        flags=re.DOTALL,
    )
    if not hero_cta_match:
        return fail("AI CEO workspace CTA click handler is missing")
    hero_cta_body = hero_cta_match.group(1)
    for marker in ["openWorkbenchOrAuth()"]:
        if marker not in hero_cta_body:
            return fail(f"AI CEO workspace CTA must preserve the session-aware entry path: {marker}")

    plan_data_start = index.find("const planData = {")
    plan_data_end = index.find("const guideData = {", plan_data_start)
    if plan_data_start < 0 or plan_data_end < 0:
        return fail("public plan detail catalog is missing")
    public_plan_data = index[plan_data_start:plan_data_end]
    if "pro:" in public_plan_data or "团队版" in public_plan_data:
        return fail("public plan detail catalog must not restore the retired team entry")
    for marker in ["不赠送生图素材点", "含 1,000 素材点", "含 3,000 素材点"]:
        if marker not in public_plan_data:
            return fail(f"public plan detail is out of sync with the approved media entitlement: {marker}")

    landing_profiles_match = re.search(
        r"const landingProfiles = \[(.*?)\n\];\n\nconst heroCommands",
        app,
        flags=re.DOTALL,
    )
    if not landing_profiles_match:
        return fail("workbench landing profile catalog is missing")
    landing_profile_values = re.findall(r'value:\s*"([^"]+)"', landing_profiles_match.group(1))
    if landing_profile_values != ["trial", "store_opened", "multi_store"]:
        return fail(f"workbench entry must expose trial/store_opened/multi_store only: {landing_profile_values}")

    if "guideData.trial = guideData.opened" in index:
        return fail("free trial must not reuse the paid store-connection guide")
    for marker in [
        "merchant_blank_trial_entry_v1",
        "guideData.trial = {",
        'key === "trial"',
        'finishGuideAndOpenWorkspace("draft_only")',
        "progress?.preferences_saved",
        "markSaasOnboardingCompleted()",
        "const blankTrialFirstDraft",
        "!blankTrialFirstDraft",
    ]:
        if marker not in index + app:
            return fail(f"free trial must enter the account-scoped blank workbench: {marker}")

    for marker in [
        "¥0 / 7 天",
        "20 次捷境托管 AI",
        "不绑卡、不自动续费",
        'const publicPathKeys = ["opened", "multi", "trial"]',
        'target.searchParams.set("settings", "billing")',
        'target.searchParams.set("plan", activePlan)',
        "套餐与付款",
    ]:
        if marker not in index + app_html + app:
            return fail(f"missing simplified trial/pricing marker: {marker}")

    homepage_visible = re.sub(r"<script\b.*?</script>|<style\b.*?</style>", " ", index, flags=re.S | re.I)
    homepage_visible = re.sub(r"<[^>]+>", " ", homepage_visible)
    for retired in ["小白起步", "已有订单处理", "永久免费", "免费版可长期使用"]:
        if retired in homepage_visible:
            return fail(f"retired public path or pricing promise is still visible: {retired}")

    for marker in [
        'PLATFORM_MODEL_TRIAL_DEFAULT_MONTHLY_LIMIT = 20',
        'PLATFORM_MODEL_TRIAL_DEFAULT_DURATION_DAYS = 7',
        '"platform_default_model_trial_expired"',
        '"quota_source": "backend_task_audit_and_activation_window"',
        '"trial_quota_scope": "account_trial_window"',
        '"trial_request_limit": _strict_nonnegative_int(platform_model.get("trial_request_limit"))',
        '"trial_duration_days": _strict_nonnegative_int(platform_model.get("trial_duration_days"))',
    ]:
        if marker not in api + readiness:
            return fail(f"backend trial enforcement marker missing: {marker}")

    billing_plan = (ROOT / "jiejing_saas" / "billing_plan.py").read_text(encoding="utf-8")
    for marker in [
        '"label": "免费体验",\n        "intended_user": "first-time merchant validating one safe operating workflow",\n        "amount_minor": 0,\n        "currency": "CNY",\n        "duration_days": 7,',
        '"label": "有店铺"',
        '"label": "多店铺"',
        '"amount_minor": 9900',
        '"amount_minor": 19900',
    ]:
        if marker not in billing_plan:
            return fail(f"backend plan catalog is out of sync with public pricing: {marker}")

    if 'data-domestic-plan-key="team"' in app:
        return fail("new public checkout should not offer the high-complexity team plan")
    if 'const selectedCheckoutPlanKey = ["starter", "operator"]' not in app:
        return fail("public checkout should offer single-store and multi-store paid plans")

    print("PASS jiejing_trial_pricing_entry")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
