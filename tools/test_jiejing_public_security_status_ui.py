#!/usr/bin/env python3
"""Static guard for the owner-only public security status panel."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    app_js = (ROOT / "app.js").read_text(encoding="utf-8")
    module_js = (ROOT / "assets" / "jiejing-settings-panels.js").read_text(encoding="utf-8")
    deploy = (ROOT / "deploy" / "apply-staging-patch.sh").read_text(encoding="utf-8")

    for marker in [
        "saasRateLimitStatus",
        'optionalSaasFetchFast("/security/rate-limit/status"',
        "function renderSaasPublicSecurityStatusPanel",
        "if (!saasOwnerLaunchCanView()) return \"\";",
        "saas-owner-public-security-status",
        "平台内部安全审计",
        "普通商家不会看到这些工程排查项",
        "not_customer_visible=true",
        "platform_internal_admin_only=true",
        "Cloudflare free baseline",
        "High-cost API rate limit",
        "route_group_evidence",
        "active_bucket_summary",
        "Active high-cost buckets",
        "Origin direct access",
        "token never shown in browser",
        "prevents_complete_copy=false",
        "makes_scraping_costly=true",
        "renderSaasPublicSecurityStatusPanel()",
    ]:
        if marker not in app_js:
            return fail(f"app.js missing public security status marker: {marker}")

    for marker in [
        "function renderPublicSecurityStatusPanel",
        "renderPublicSecurityStatusPanel,",
        "saas-owner-public-security-status",
        "平台内部安全审计",
        "普通商家不会看到这些工程排查项",
        "High-cost API rate limit",
        "route_group_evidence",
        "active_bucket_summary",
        "Active high-cost buckets",
        "not_customer_visible=true",
    ]:
        if marker not in module_js:
            return fail(f"settings module missing public security status marker: {marker}")

    if "tools/test_jiejing_public_security_status_ui.py" not in deploy:
        return fail("staging patch contract should run the public security status UI regression")

    print("PASS jiejing_public_security_status_ui")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
