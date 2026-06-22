#!/usr/bin/env python3
"""Regression for Lemon Squeezy as a supported paid billing provider."""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.billing_plan import build_billing_plan  # noqa: E402
from jiejing_saas.config import SaaSSettings  # noqa: E402
from jiejing_saas.repository import SaaSRepository  # noqa: E402


OUT = ROOT / "output" / "jiejing-billing-lemon-squeezy-test"


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True, exist_ok=True)
    previous = _set_env()
    try:
        settings = SaaSSettings.from_env(
            db_path=OUT / "saas.sqlite",
            runtime_db_path=OUT / "runtime.sqlite",
            output_root=OUT,
            host="127.0.0.1",
            port=8788,
        )
        repo = SaaSRepository(settings.db_path, database_engine="sqlite", database_url="")
        plan = build_billing_plan(settings, repo)
    finally:
        _restore_env(previous)

    provider = plan.get("provider") if isinstance(plan.get("provider"), dict) else {}
    if provider.get("selected") != "lemon_squeezy":
        return fail(f"billing provider should normalize Lemon Squeezy, got {provider.get('selected')}")
    if "lemon_squeezy" not in provider.get("allowed_external_providers", []):
        return fail("billing plan should expose Lemon Squeezy as an allowed external provider")
    provider_contract = provider.get("signed_webhook_contract") if isinstance(provider.get("signed_webhook_contract"), dict) else {}
    if provider_contract.get("paid_provider_ready") is not True:
        return fail(f"Lemon Squeezy provider webhook contract should be ready when configured: {provider_contract}")
    if plan.get("billing_ready_for_paid_launch") is not False:
        return fail("Lemon Squeezy must not satisfy paid launch until a checkout/portal adapter is implemented")
    if "billing_checkout_adapter_not_implemented_for_provider" not in plan.get("paid_launch_blockers", []):
        return fail(f"Lemon Squeezy paid launch should be blocked by missing checkout adapter: {plan.get('paid_launch_blockers')}")
    serialized = json.dumps(plan, ensure_ascii=False)
    for forbidden in ("ls_api_unit", "ls_webhook_unit"):
        if forbidden in serialized:
            return fail(f"billing plan leaked payment secret marker: {forbidden}")
    print("PASS jiejing_billing_lemon_squeezy_readiness")
    return 0


def _set_env() -> dict[str, str | None]:
    keys = [
        "JIEJING_SAAS_ENV",
        "JIEJING_BILLING_PROVIDER",
        "JIEJING_BILLING_PLANS_PUBLISHED",
        "JIEJING_QUOTA_ENFORCEMENT_ENABLED",
        "JIEJING_LEMON_SQUEEZY_API_KEY",
        "JIEJING_LEMON_SQUEEZY_WEBHOOK_SECRET",
        "JIEJING_BILLING_WEBHOOK_URL",
        "JIEJING_LEMON_SQUEEZY_VARIANT_STARTER_ID",
        "JIEJING_LEMON_SQUEEZY_VARIANT_OPERATOR_ID",
        "JIEJING_LEMON_SQUEEZY_VARIANT_TEAM_ID",
    ]
    previous = {key: os.environ.get(key) for key in keys}
    os.environ.update(
        {
            "JIEJING_SAAS_ENV": "staging",
            "JIEJING_BILLING_PROVIDER": "lemonsqueezy",
            "JIEJING_BILLING_PLANS_PUBLISHED": "1",
            "JIEJING_QUOTA_ENFORCEMENT_ENABLED": "1",
            "JIEJING_LEMON_SQUEEZY_API_KEY": "ls_api_unit",
            "JIEJING_LEMON_SQUEEZY_WEBHOOK_SECRET": "ls_webhook_unit",
            "JIEJING_BILLING_WEBHOOK_URL": "https://app.example.test/billing/webhook",
            "JIEJING_LEMON_SQUEEZY_VARIANT_STARTER_ID": "456",
            "JIEJING_LEMON_SQUEEZY_VARIANT_OPERATOR_ID": "789",
            "JIEJING_LEMON_SQUEEZY_VARIANT_TEAM_ID": "999",
        }
    )
    return previous


def _restore_env(previous: dict[str, str | None]) -> None:
    for key, value in previous.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


if __name__ == "__main__":
    raise SystemExit(main())
