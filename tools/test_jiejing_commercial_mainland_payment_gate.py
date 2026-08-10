#!/usr/bin/env python3
"""Commercial gate must use the canonical mainland WeChat payment boundary."""

from __future__ import annotations

import sys
import tempfile
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.commercial_launch_gate import build_commercial_launch_gate  # noqa: E402
from jiejing_saas.config import SaaSSettings  # noqa: E402
from jiejing_saas.repository import SaaSRepository  # noqa: E402


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    with tempfile.TemporaryDirectory(
        prefix="jiejing-commercial-mainland-payment-",
        ignore_cleanup_errors=True,
    ) as temp_dir:
        root = Path(temp_dir)
        settings = SaaSSettings.from_env(
            db_path=root / "saas.sqlite",
            runtime_db_path=root / "runtime.sqlite",
            output_root=root / "output",
            host="127.0.0.1",
            port=8788,
        )
        repository = SaaSRepository(settings.db_path)
        repository.initialize()
        gate = _build(settings, repository, legacy_stripe_ready=True, mainland_owner_ready=False)
        billing = _groups(gate).get("billing_quota") or {}
        if billing.get("status") != "blocked":
            return fail("legacy Stripe readiness must not satisfy the mainland payment launch gate")
        evidence = billing.get("evidence") if isinstance(billing.get("evidence"), dict) else {}
        if evidence.get("mainland_payment_ready_for_owner_approval") is not False:
            return fail(f"commercial payment evidence must expose the canonical boolean only: {evidence}")
        if "billing_ready_for_paid_launch" in evidence:
            return fail("legacy Stripe readiness leaked into mainland commercial evidence")

        canonical_ready = _build(
            settings,
            repository,
            legacy_stripe_ready=False,
            mainland_owner_ready=True,
        )
        canonical_billing = _groups(canonical_ready).get("billing_quota") or {}
        if canonical_billing.get("status") != "ready":
            return fail("canonical WeChat owner-ready evidence must satisfy the mainland payment group")
        canonical_evidence = (
            canonical_billing.get("evidence")
            if isinstance(canonical_billing.get("evidence"), dict)
            else {}
        )
        if canonical_evidence.get("public_charging_allowed") is not False:
            return fail("WeChat owner-ready evidence must not open public charging")
        if canonical_ready.get("paid_commercial_launch_ready") is not False:
            return fail("payment owner readiness alone must not mark the commercial launch ready")

    print("PASS jiejing_commercial_mainland_payment_gate")
    return 0


def _build(
    settings: SaaSSettings,
    repository: SaaSRepository,
    *,
    legacy_stripe_ready: bool,
    mainland_owner_ready: bool,
) -> dict[str, object]:
    readiness = {
        "product_evidence": {},
        "counts": {},
        "production_ready": False,
        "beta_ready": False,
        "blocker_count": 1,
        "warning_count": 0,
        "items": [],
    }
    canonical = {
        "mainland_payment_ready_for_owner_approval": mainland_owner_ready,
        "provider_configured": mainland_owner_ready,
        "payment_path_status": (
            "controlled_acceptance_proven_public_charging_closed"
            if mainland_owner_ready
            else "provider_connection_in_progress"
        ),
        "configured_component_count": 9 if mainland_owner_ready else 0,
        "required_component_count": 9,
        "controlled_acceptance_proven": mainland_owner_ready,
        "verified_paid_order_count": 1 if mainland_owner_ready else 0,
        "next_paid_launch_blocker": (
            "merchant_payment_public_cutover_not_approved"
            if mainland_owner_ready
            else "merchant_payment_provider_connection_not_ready"
        ),
    }
    with ExitStack() as stack:
        stack.enter_context(patch("jiejing_saas.commercial_launch_gate.build_product_readiness", return_value=readiness))
        stack.enter_context(patch("jiejing_saas.commercial_launch_gate.build_infrastructure_driver_status", return_value={}))
        stack.enter_context(patch("jiejing_saas.commercial_launch_gate.build_backup_plan", return_value={}))
        stack.enter_context(
            patch(
                "jiejing_saas.commercial_launch_gate.build_billing_plan",
                return_value={"billing_ready_for_paid_launch": legacy_stripe_ready, "provider": {"selected": "stripe"}},
            )
        )
        stack.enter_context(
            patch("jiejing_saas.commercial_launch_gate.build_mainland_payment_launch_status", return_value={"canonical": True})
        )
        stack.enter_context(
            patch("jiejing_saas.commercial_launch_gate.validate_mainland_payment_launch_for_public", return_value=canonical)
        )
        stack.enter_context(patch("jiejing_saas.commercial_launch_gate.build_model_value_gate", return_value={}))
        stack.enter_context(patch("jiejing_saas.commercial_launch_gate.build_monitoring_status", return_value={}))
        stack.enter_context(patch("jiejing_saas.commercial_launch_gate.build_domain_readiness", return_value={}))
        stack.enter_context(patch("jiejing_saas.commercial_launch_gate.build_vault_adapter_contract", return_value={}))
        stack.enter_context(patch("jiejing_saas.commercial_launch_gate.build_current_store_ebay_evidence", return_value={}))
        stack.enter_context(patch("jiejing_saas.commercial_launch_gate._build_launch_action_plan", return_value={}))
        return build_commercial_launch_gate(settings, repository)


def _groups(gate: dict[str, object]) -> dict[str, dict[str, object]]:
    value = gate.get("groups")
    return {
        str(item.get("key") or ""): item
        for item in value if isinstance(item, dict)
    } if isinstance(value, list) else {}


if __name__ == "__main__":
    raise SystemExit(main())
