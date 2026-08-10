#!/usr/bin/env python3
"""Regression for the internal production evidence ledger."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.config import SaaSSettings  # noqa: E402
from jiejing_saas.production_evidence_ledger import (  # noqa: E402
    PRODUCTION_EVIDENCE_LEDGER_VERSION,
    build_production_evidence_ledger,
)
from jiejing_saas.repository import SaaSRepository  # noqa: E402
from tools.test_jiejing_production_release_gate import (  # noqa: E402
    EXPECTED_SECTIONS,
    _ready_mainland_payment,
    _ready_paid_launch_packet,
    _restore_env,
    _seed_ready_repository,
    _set_blocked_env,
    _set_ready_env,
)


OUT = Path(tempfile.mkdtemp(prefix="jiejing-production-evidence-ledger-test-"))
UNSAFE_FLAGS = (
    "public_paid_launch_allowed",
    "charge_now_allowed",
    "creates_checkout_session",
    "calls_stripe_api",
    "triggers_real_charge",
    "triggers_ebay_oauth",
    "repeat_ebay_oauth_allowed",
    "triggers_real_platform_write",
    "platform_write_now_allowed",
    "frontend_gets_payment_secret",
    "frontend_gets_provider_secret",
    "frontend_gets_ebay_token",
    "secret_exposed",
)


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    previous = _set_blocked_env()
    try:
        blocked = _build("blocked.sqlite")
        if blocked.get("contract_version") != PRODUCTION_EVIDENCE_LEDGER_VERSION:
            return fail("production evidence ledger contract missing")
        if blocked.get("status") != "blocked" or blocked.get("decision") != "keep_public_launch_blocked":
            return fail(f"blocked ledger should keep launch blocked: {blocked.get('summary')}")
        if blocked.get("audience") != "platform_internal_admin" or blocked.get("customer_visible") is not False:
            return fail("ledger must stay platform-internal")
        rows = {row.get("section_key"): row for row in blocked.get("evidence_rows", []) if isinstance(row, dict)}
        if set(rows) != EXPECTED_SECTIONS:
            return fail(f"ledger should mirror production release sections: {sorted(rows)}")
        if "mainland_wechat_payment_and_refund_controls" not in rows or "subscription_billing_webhook_and_quota" in rows:
            return fail(f"ledger billing section must use the canonical mainland contract: {sorted(rows)}")
        if not blocked.get("next_missing_evidence"):
            return fail("blocked ledger should explain next missing evidence")
        if not any(row.get("raw_secret_value_allowed") is False for row in blocked.get("evidence_rows", [])):
            return fail("ledger rows must explicitly reject raw secret values")
        _assert_unsafe_flags_false(blocked, "blocked ledger")
        _assert_rows_safe(blocked)
    finally:
        _restore_env(previous)

    previous = _set_ready_env()
    try:
        ready = _build("ready.sqlite", seed_ready_data=True)
        if ready.get("status") != "ready_for_owner_approval":
            return fail(f"ready ledger should only reach owner approval: {ready.get('summary')}")
        if ready.get("decision") != "ready_for_owner_approval_not_auto_launch":
            return fail(f"ready ledger must not auto-launch: {ready.get('decision')}")
        summary = ready.get("summary") if isinstance(ready.get("summary"), dict) else {}
        if summary.get("blocked_count") != 0 or summary.get("external_evidence_ready_count") != summary.get("external_evidence_count"):
            return fail(f"ready ledger summary should be complete: {summary}")
        rules = ready.get("acceptance_rules") if isinstance(ready.get("acceptance_rules"), dict) else {}
        for key in (
            "raw_secret_values_allowed_in_ledger",
            "config_flag_alone_is_not_customer_launch_proof",
            "ebay_refresh_requires_backend_audit_log_proof",
            "mainland_payment_requires_signed_callbacks_query_refund_and_controlled_acceptance",
            "owner_approval_is_required_but_never_auto_launches_public_paid_mode",
        ):
            expected = False if key == "raw_secret_values_allowed_in_ledger" else True
            if rules.get(key) is not expected:
                return fail(f"ledger acceptance rule missing or wrong: {key}={rules.get(key)}")
        audit_keys = {item.get("key") for item in ready.get("audit_log_requirements", []) if isinstance(item, dict)}
        for key in {"ebay_refresh_success", "wechat_payment_lifecycle", "owner_approval_packet"}:
            if key not in audit_keys:
                return fail(f"ledger missing audit requirement: {key}")
        external_rows = {item.get("key"): item for item in ready.get("external_evidence_rows", []) if isinstance(item, dict)}
        wechat_cutover = external_rows.get("wechat_pay_native_production_cutover") or {}
        if wechat_cutover.get("linked_section_key") != "mainland_wechat_payment_and_refund_controls":
            return fail(f"WeChat cutover evidence must link to the mainland billing section: {wechat_cutover}")
        if "stripe_live_billing" in external_rows:
            return fail("Stripe evidence must not remain a mainland evidence-ledger requirement")
        _assert_unsafe_flags_false(ready, "ready ledger")
        _assert_rows_safe(ready)
        serialized = json.dumps(ready, ensure_ascii=False).lower()
        for forbidden in ("sk_live_unit_secret", "whsec_live_unit_secret", "unit-vault-token", "test-client-secret", "refresh_token="):
            if forbidden in serialized:
                return fail(f"production evidence ledger leaked forbidden marker: {forbidden}")
        print("PASS jiejing_production_evidence_ledger")
        return 0
    finally:
        _restore_env(previous)


def _assert_unsafe_flags_false(payload: dict[str, object], label: str) -> None:
    for flag in UNSAFE_FLAGS:
        if payload.get(flag) is not False:
            raise AssertionError(f"{label} unsafe flag should be false: {flag}")


def _assert_rows_safe(payload: dict[str, object]) -> None:
    for row_key in ("evidence_rows", "external_evidence_rows"):
        for row in payload.get(row_key, []) or []:
            if not isinstance(row, dict):
                continue
            if row.get("customer_visible") is not False or row.get("ordinary_merchant_visible") is not False:
                raise AssertionError(f"{row_key} should stay internal: {row}")
            if row.get("raw_secret_value_allowed") is not False or row.get("secret_exposed") is not False:
                raise AssertionError(f"{row_key} should reject raw secrets: {row}")


def _build(name: str, *, seed_ready_data: bool = False) -> dict[str, object]:
    db_path = OUT / name
    runtime_db_path = OUT / f"runtime-{name}"
    settings = SaaSSettings.from_env(db_path=db_path, runtime_db_path=runtime_db_path, output_root=OUT, host="127.0.0.1", port=8788)
    repo = SaaSRepository(db_path, database_engine="sqlite", database_url="")
    repo.initialize()
    if seed_ready_data:
        _seed_ready_repository(repo)
        with patch(
            "jiejing_saas.production_release_gate.build_mainland_payment_launch_status",
            return_value=_ready_mainland_payment(),
        ), patch(
            "jiejing_saas.production_release_gate.build_paid_launch_approval_packet",
            return_value=_ready_paid_launch_packet(),
        ), patch(
            "jiejing_saas.production_release_gate.build_product_readiness_or_degraded",
            return_value={
                "production_ready": False,
                "beta_ready": True,
                "can_accept_real_customers": False,
                "reason": "expected_public_charge_approval_hold",
                "blocker_count": 0,
                "warning_count": 1,
                "items": [
                    {
                        "key": "billing_quota",
                        "label": "Billing and quota",
                        "status": "mainland_payment_ready_for_owner_approval",
                        "severity": "warning",
                        "detail": "Sanitized owner-preapproval hold.",
                        "next_action": "Keep public charging closed until final approval.",
                    }
                ],
                "product_evidence": {},
            },
        ):
            return build_production_evidence_ledger(settings, repo)
    return build_production_evidence_ledger(settings, repo)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        raise SystemExit(fail(str(exc)))
