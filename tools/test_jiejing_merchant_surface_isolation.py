#!/usr/bin/env python3
"""RED contract for keeping the merchant app physically separate from ops."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _scope(source: str, start_marker: str, end_marker: str) -> str:
    start = source.find(start_marker)
    end = source.find(end_marker, start + len(start_marker))
    if start < 0 or end < 0:
        raise AssertionError(f"missing source scope: {start_marker} -> {end_marker}")
    return source[start:end]


def _all_keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        keys = {str(key) for key in value}
        for item in value.values():
            keys.update(_all_keys(item))
        return keys
    if isinstance(value, list):
        keys: set[str] = set()
        for item in value:
            keys.update(_all_keys(item))
        return keys
    return set()


class _MediaCreditFixtureRepository:
    def get_media_credit_account(self, *, company_id: str) -> dict[str, Any]:
        assert company_id == "company-red-contract"
        return {
            "available_points": 320,
            "included_points": 100,
            "purchased_points": 200,
            "controlled_acceptance_points": 10,
            "controlled_acceptance_reserved_points": 2,
            "owner_testing_points": 10,
            "owner_testing_reserved_points": 1,
            "owner_testing_expires_at": "2026-09-01T00:00:00Z",
        }

    def list_media_credit_ledger(self, *, company_id: str, limit: int) -> list[dict[str, Any]]:
        assert company_id == "company-red-contract"
        assert limit == 30
        return [
            {
                "ledger_id": "ledger_internal_red_contract",
                "source_type": "owner_testing",
                "balance_after": 320,
            }
        ]


def main() -> int:
    failures: list[str] = []

    app_js = (ROOT / "app.js").read_text(encoding="utf-8")
    app_html = (ROOT / "app.html").read_text(encoding="utf-8")
    merchant_module = (ROOT / "assets" / "jiejing-settings-panels.js").read_text(encoding="utf-8")
    api_server = (ROOT / "jiejing_saas" / "api_server.py").read_text(encoding="utf-8")

    settings_scope = _scope(
        app_js,
        "function saasSettingsTabDefinitions",
        "function renderSaasSettingsCleanLayout",
    )
    settings_labels = re.findall(r'\n\s*label:\s*"([^"]+)"', settings_scope)
    expected_labels = ["账号与店铺", "AI 与素材", "店铺数据", "团队权限", "套餐与付款"]
    if settings_labels != expected_labels:
        failures.append(f"merchant Settings must expose exactly five tabs: {settings_labels}")
    for marker in ("owner_ops", "saasOwnerLaunchCanView", "主理人高级", "正式收费和公网安全", "运行可靠性"):
        if marker in settings_scope:
            failures.append(f"merchant Settings still contains internal owner branch: {marker}")

    merchant_sources = {"app.html": app_html, "app.js": app_js, "jiejing-settings-panels.js": merchant_module}
    forbidden_merchant_markers = (
        "/owner/launch-control",
        "/owner/edge-cutover-preflight",
        "/owner/paid-launch-approval-packet",
        "/vault/status",
        "/database/plan",
        "/backup/plan",
        "/queue/plan",
        "/queue/health",
        "/billing/payment-options",
        "/billing/wechat-pay/zero-charge-rehearsal",
        "renderSaasOwnerLaunchControlPanel",
        "renderCommercialLaunchActionPlanPanel",
        "renderEdgeCutoverReadinessPanel",
        "renderQueueHealthPanel",
        "renderPublicSecurityStatusPanel",
        "owner_testing_points",
        "隔离假支付方",
        "等待 Owner 发起",
    )
    for filename, source in merchant_sources.items():
        for marker in forbidden_merchant_markers:
            if marker in source:
                failures.append(f"{filename} physically contains internal marker: {marker}")

    billing_scope = _scope(api_server, 'if path == "billing/plans":', 'if path == "billing/payment-options":')
    if "_is_platform_internal_admin" in billing_scope:
        failures.append("/billing/plans changes merchant response by platform-internal role")
    if "plan = self._merchant_safe_billing_plan(plan)" not in billing_scope:
        failures.append("/billing/plans does not always apply the merchant-safe projection")

    frontend_projection = _scope(
        app_js,
        "function merchantSafeSaasBillingPlan",
        "function merchantSafeSaasOAuthRequest",
    )
    if "saasOwnerLaunchCanView" in frontend_projection:
        failures.append("merchant billing projection bypasses sanitization for an internal admin")

    from jiejing_saas import media_credits

    merchant_projection = getattr(media_credits, "build_merchant_media_credit_summary", None)
    if not callable(merchant_projection):
        failures.append("merchant media-credit projection helper is missing: build_merchant_media_credit_summary")
    else:
        media_summary = merchant_projection(
            _MediaCreditFixtureRepository(),
            company_id="company-red-contract",
            limit=30,
        )
        expected_points = {
            "total_points": 300,
            "available_points": 300,
            "included_points": 100,
            "purchased_points": 200,
        }
        if not isinstance(media_summary, dict) or not media_summary:
            failures.append("merchant media-credit projection must return a non-empty object")
        else:
            for field, expected in expected_points.items():
                actual = media_summary.get(field)
                if not isinstance(actual, int) or isinstance(actual, bool) or actual != expected:
                    failures.append(
                        f"merchant media-credit projection has invalid {field}: expected={expected} actual={actual!r}"
                    )
            exposed_keys = _all_keys(media_summary)
            forbidden_media_keys = {
                "controlled_acceptance_points",
                "controlled_acceptance_reserved_points",
                "owner_testing_points",
                "owner_testing_reserved_points",
                "owner_testing_expires_at",
                "ledger_id",
                "balance_after",
                "source_type",
                "recent_activity",
            }
            leaked_media_keys = sorted(forbidden_media_keys & exposed_keys)
            if leaked_media_keys:
                failures.append(
                    f"merchant media-credit projection exposes internal bucket/ledger keys: {leaked_media_keys}"
                )
            if media_summary.get("secret_exposed") is not False:
                failures.append("merchant media-credit projection must explicitly keep secret_exposed=false")

    media_route_start = api_server.find('if path == "billing/media-credits":')
    media_route_end = api_server.find("\n        if path == ", media_route_start + 1)
    media_route_scope = api_server[
        media_route_start : media_route_end if media_route_end >= 0 else len(api_server)
    ]
    if media_route_start < 0 or "build_merchant_media_credit_summary(" not in media_route_scope:
        failures.append("/billing/media-credits does not use the dedicated merchant projection")

    # Make the RED output deterministic and safe to paste into implementation notes.
    if failures:
        for failure in failures:
            print(f"FAIL {failure}")
        print(json.dumps({"ok": False, "failure_count": len(failures), "secret_exposed": False}, ensure_ascii=False))
        return 1

    print("PASS jiejing_merchant_surface_isolation")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
