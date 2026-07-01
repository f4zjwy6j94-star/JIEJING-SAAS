#!/usr/bin/env python3
"""Regression for Jiejing platform authorization strategy."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.platform_authorization_strategy import build_platform_authorization_strategy  # noqa: E402


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    strategy = build_platform_authorization_strategy()
    if strategy.get("product_positioning") != "eBay-first AI CEO SaaS":
        return fail("strategy must preserve Jiejing product positioning")
    if strategy.get("mode") != "read_only_strategy_packet_no_oauth_no_platform_call":
        return fail("strategy packet must be read-only")
    rules = strategy.get("operating_rules") if isinstance(strategy.get("operating_rules"), dict) else {}
    for marker in (
        "jiejing_task_protocol_owns_workflow",
        "platform_adapter_translates_fields",
        "manual_import_is_a_valid_beta_lane",
        "read_only_before_write",
        "writes_require_confirmation_center",
        "oauth_scope_change_requires_confirmation",
    ):
        if rules.get(marker) is not True:
            return fail(f"platform strategy missing operating rule: {marker}")
    for marker in ("frontend_gets_raw_token", "runtime_gets_raw_token", "agent_gets_raw_token", "secret_exposed"):
        if rules.get(marker) is not False:
            return fail(f"platform strategy unsafe rule should be false: {marker}")

    lanes = {item.get("key"): item for item in strategy.get("lanes", []) if isinstance(item, dict)}
    for key in ("ebay", "shopify", "etsy", "tiktok_shop", "amazon_sp_api"):
        if key not in lanes:
            return fail(f"platform lane missing: {key}")
    if lanes["ebay"].get("current_role") != "primary_sales_channel":
        return fail("eBay must stay the primary channel")
    if "repeat_old_frozen_account_oauth" not in lanes["ebay"].get("never_do", []):
        return fail("strategy must forbid repeating the frozen eBay account OAuth")
    if lanes["amazon_sp_api"].get("current_role") != "future_reserved_not_p0":
        return fail("Amazon SP-API must be reserved, not a launch blocker")
    if "do_not_make_amazon_api_access_a_launch_blocker" not in lanes["amazon_sp_api"].get("jiejing_solution", []):
        return fail("Amazon fallback strategy must be explicit")
    if "perform_platform_write_without_confirmation" not in strategy.get("blocked_actions", []):
        return fail("strategy must block unconfirmed platform writes")
    if strategy.get("secret_exposed") is not False:
        return fail("strategy must not expose secrets")

    print("PASS jiejing_platform_authorization_strategy")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
