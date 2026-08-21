#!/usr/bin/env python3
"""Validate the value-free public readiness summary after CLS maintenance."""

from __future__ import annotations

import json
import sys
from typing import Any


def public_readiness_ready(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    readiness = payload.get("readiness")
    if not isinstance(readiness, dict):
        return False
    items = readiness.get("items")
    if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
        return False

    item_by_key: dict[str, dict[str, Any]] = {}
    for item in items:
        key = item.get("key")
        if not isinstance(key, str) or not key or key in item_by_key:
            return False
        item_by_key[key] = item

    # The public endpoint intentionally exposes warning/blocker items only.
    # A monitoring item here therefore means monitoring is not ready; the
    # positive CLS proof is independently verified before this contract runs.
    if "monitoring_alerting" in item_by_key:
        return False

    billing_item = item_by_key.get("billing_quota")
    provider_status = readiness.get("provider_status")
    if not isinstance(billing_item, dict) or not isinstance(provider_status, dict):
        return False
    billing = provider_status.get("billing")
    if not isinstance(billing, dict):
        return False

    return (
        billing_item.get("status") == "private_beta_ready_paid_launch_pending"
        and billing.get("public_charging_allowed") is False
        and billing.get("charge_now_allowed") is False
        and billing.get("triggers_real_charge") is False
        and billing.get("triggers_real_refund") is False
        and billing.get("real_platform_writes_enabled") is False
        and billing.get("secret_exposed") is False
        and readiness.get("production_ready") is False
        and readiness.get("can_accept_real_customers") is False
        and readiness.get("real_platform_writes_enabled") is False
        and readiness.get("requested_real_platform_writes") is False
        and readiness.get("secret_exposed") is False
    )


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError, UnicodeError):
        print("blocked")
        return 2
    if not public_readiness_ready(payload):
        print("blocked")
        return 2
    print("verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
