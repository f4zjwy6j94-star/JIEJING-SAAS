#!/usr/bin/env python3
"""Focused contract for a value-free WeChat Pay provider connection proof."""

from __future__ import annotations

import json
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.billing_payment_options import (  # noqa: E402
    MAINLAND_PAYMENT_CONTRACT_VERSION,
    MAINLAND_WECHAT_CONFIGURATION_KEYS,
    _build_mainland_payment_launch_status,
    validate_mainland_payment_launch_for_public,
)
from jiejing_saas.repository import SaaSRepository  # noqa: E402
from tools.jiejing_wechat_pay_noncharge_acceptance import record_provider_connection_proof  # noqa: E402


PROOF_ACTION = "billing.wechat_pay.provider_connection.proven"
PROOF_TARGET_TYPE = "billing_provider"
PROOF_TARGET_ID = "wechat_pay_native"
PROOF_CONTRACT = "2026-08-21-wechat-pay-provider-connection-proof-v1"


def _details(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "contract_version": PROOF_CONTRACT,
        "provider": "wechat_pay_native",
        "query_authenticated": True,
        "provider_query_accepted": True,
        "provider_response_signature_verified": True,
        "provider_order_found": False,
        "calls_external_payment_api": True,
        "creates_payable_order": False,
        "triggers_real_charge": False,
        "triggers_real_refund": False,
        "public_charging_allowed": False,
        "real_platform_writes_enabled": False,
        "secret_exposed": False,
    }
    value.update(overrides)
    return value


def _repository() -> tuple[SaaSRepository, dict[str, object]]:
    temp_dir = Path(tempfile.mkdtemp(prefix="jiejing-provider-proof-"))
    repository = SaaSRepository(temp_dir / "provider-proof.sqlite")
    repository.initialize()
    identity = repository.create_user_with_company(
        email="provider-proof@example.test",
        password="Provider-proof-2026!",
        company_name="Provider Proof Test",
    )
    return repository, identity


def _write_proof(
    repository: SaaSRepository,
    identity: dict[str, object],
    *,
    details: dict[str, object] | None = None,
    action_type: str = PROOF_ACTION,
) -> dict[str, object]:
    company = identity["company"]
    user = identity["user"]
    assert isinstance(company, dict) and isinstance(user, dict)
    return repository.write_audit(
        company_id=str(company["company_id"]),
        user_id=str(user["user_id"]),
        action_type=action_type,
        target_type=PROOF_TARGET_TYPE,
        target_id=PROOF_TARGET_ID,
        summary="WeChat Pay provider connection proven by signed read-only query",
        details=details or _details(),
        actor_type="platform_internal_admin",
    )


def _rewrite_created_at(repository: SaaSRepository, audit: dict[str, object], value: str) -> None:
    mutated = dict(audit)
    mutated["created_at"] = value
    with repository._connect() as conn:  # type: ignore[attr-defined]
        conn.execute(
            "update audit_logs set created_at = ?, audit_json = ? where audit_id = ?",
            (value, json.dumps(mutated, ensure_ascii=False), str(audit["audit_id"])),
        )


def _valid_strategy() -> dict[str, object]:
    return {
        "contract_version": MAINLAND_PAYMENT_CONTRACT_VERSION,
        "charge_now_allowed": False,
        "triggers_real_charge": False,
        "frontend_gets_payment_secret": False,
        "secret_exposed": False,
        "cross_border_lanes": [],
    }


def _valid_wechat() -> dict[str, object]:
    return {
        "contract_version": "2026-07-14-wechat-pay-native-v3",
        "provider": "wechat_pay_native",
        "checkout_mode": "native_qr",
        "billing_mode": "one_time_30_day_plan",
        "merchant_credentials_backend_only": True,
        "frontend_gets_payment_secret": False,
        "secret_exposed": False,
        "configured": {key: True for key in MAINLAND_WECHAT_CONFIGURATION_KEYS},
        "signed_callback_implemented": True,
        "signed_refund_callback_implemented": True,
        "real_order_creation_implemented": True,
        "refund_execution_confirmation_required": True,
        "provider_connection_ready": False,
        "production_environment": False,
        "owner_approval_recorded": False,
        "refund_now_allowed": False,
    }


def _valid_acceptance() -> dict[str, object]:
    return {
        "contract_version": "2026-07-27-domestic-payment-acceptance-evidence-v2",
        "provider": "wechat_pay_native",
        "acceptance_kind": "owner_approved_one_cny_live_acceptance",
        "controlled_acceptance_proven": True,
        "verified_paid_order_count": 1,
        "public_charging_allowed": False,
        "charge_now_allowed": False,
        "triggers_real_charge": False,
        "calls_external_payment_api": False,
        "secret_exposed": False,
    }


def _assert_not_ready(value: dict[str, object], label: str) -> None:
    if value.get("provider_connection_proof_ready") is not False:
        raise AssertionError(f"{label} must fail closed: {value}")


def main() -> int:
    repository, identity = _repository()
    company = identity["company"]
    assert isinstance(company, dict)
    provider_result = {
        "reason": "wechat_pay_provider_rejected_request",
        "provider_code": "ORDER_NOT_EXIST",
        "calls_external_payment_api": True,
        "provider_response_signature_verified": True,
        "provider_transaction_id": "provider-transaction-sentinel-must-not-persist",
    }
    if not record_provider_connection_proof(
        repository,
        company_id=str(company["company_id"]),
        result=provider_result,
    ):
        raise AssertionError("exact signed read-only provider result must persist proof")
    proof_audit = repository.find_latest_audit_log_by_target(
        company_id=str(company["company_id"]),
        store_id=None,
        action_type=PROOF_ACTION,
        target_type=PROOF_TARGET_TYPE,
        target_id=PROOF_TARGET_ID,
    )
    if not isinstance(proof_audit, dict):
        raise AssertionError("operator probe did not persist the exact proof audit")
    evidence = repository.domestic_payment_provider_connection_evidence()
    if evidence.get("provider_connection_proof_ready") is not True:
        raise AssertionError(f"fresh exact provider proof must be ready: {evidence}")
    if evidence.get("verified_proof_count") != 1 or not evidence.get("latest_verified_at"):
        raise AssertionError(f"provider proof count/time mismatch: {evidence}")
    serialized = json.dumps(evidence, ensure_ascii=False, sort_keys=True)
    for marker in (
        str(proof_audit["audit_id"]),
        "provider-proof@example.test",
        "Provider-proof-2026!",
        "provider-transaction-sentinel-must-not-persist",
    ):
        if marker in serialized:
            raise AssertionError("provider proof evidence leaked an internal identifier or credential")
    audit_serialized = json.dumps(proof_audit, ensure_ascii=False, sort_keys=True)
    if "provider-transaction-sentinel-must-not-persist" in audit_serialized:
        raise AssertionError("operator probe persisted a raw provider response field")

    rejected_repository, rejected_identity = _repository()
    rejected_company = rejected_identity["company"]
    assert isinstance(rejected_company, dict)
    rejected_result = dict(provider_result)
    rejected_result["provider_response_signature_verified"] = False
    if record_provider_connection_proof(
        rejected_repository,
        company_id=str(rejected_company["company_id"]),
        result=rejected_result,
    ):
        raise AssertionError("unverified provider response must not persist proof")
    _assert_not_ready(
        rejected_repository.domestic_payment_provider_connection_evidence(),
        "unverified provider response",
    )

    stale_repository, stale_identity = _repository()
    stale_audit = _write_proof(stale_repository, stale_identity)
    _rewrite_created_at(
        stale_repository,
        stale_audit,
        (datetime.now(timezone.utc) - timedelta(hours=24, seconds=1)).isoformat(),
    )
    _assert_not_ready(stale_repository.domestic_payment_provider_connection_evidence(), "stale proof")

    future_repository, future_identity = _repository()
    future_audit = _write_proof(future_repository, future_identity)
    _rewrite_created_at(
        future_repository,
        future_audit,
        (datetime.now(timezone.utc) + timedelta(seconds=60)).isoformat(),
    )
    _assert_not_ready(future_repository.domestic_payment_provider_connection_evidence(), "future proof")

    unsafe_repository, unsafe_identity = _repository()
    _write_proof(unsafe_repository, unsafe_identity, details=_details(triggers_real_charge=True))
    _assert_not_ready(unsafe_repository.domestic_payment_provider_connection_evidence(), "unsafe proof")

    wrong_repository, wrong_identity = _repository()
    _write_proof(wrong_repository, wrong_identity, action_type="billing.wechat_pay.provider_connection.claimed")
    _assert_not_ready(wrong_repository.domestic_payment_provider_connection_evidence(), "wrong-action proof")

    malformed_repository, malformed_identity = _repository()
    malformed_audit = _write_proof(malformed_repository, malformed_identity)
    with malformed_repository._connect() as conn:  # type: ignore[attr-defined]
        conn.execute(
            "update audit_logs set audit_json = ? where audit_id = ?",
            ("{malformed-json", str(malformed_audit["audit_id"])),
        )
    _assert_not_ready(malformed_repository.domestic_payment_provider_connection_evidence(), "malformed proof")

    launch = _build_mainland_payment_launch_status(
        strategy=_valid_strategy(),
        wechat=_valid_wechat(),
        acceptance=_valid_acceptance(),
        provider_connection_evidence=evidence,
    )
    if launch.get("provider_checkout_ready") is not True:
        raise AssertionError(f"fresh signed provider proof must satisfy only the connection slice: {launch}")
    if "wechat_pay_live_api_disabled" in launch.get("paid_launch_blockers", []):
        raise AssertionError(f"proof-backed connection must not retain the runtime activation blocker: {launch}")
    if "public_checkout_requires_production_environment" not in launch.get("paid_launch_blockers", []):
        raise AssertionError(f"connection proof must not bypass production readiness: {launch}")
    for key in (
        "public_charging_allowed",
        "charge_now_allowed",
        "triggers_real_charge",
        "triggers_real_refund",
        "real_platform_writes_enabled",
        "secret_exposed",
    ):
        if launch.get(key) is not False:
            raise AssertionError(f"provider proof must not enable {key}: {launch}")
    public = validate_mainland_payment_launch_for_public(launch)
    if public.get("provider_connection_proof_ready") is not True:
        raise AssertionError(f"public readiness must surface only the safe proof marker: {public}")
    if public.get("payment_path_status") != "production_environment_pending":
        raise AssertionError(f"proof must advance only to the next real blocker: {public}")
    if public.get("next_paid_launch_blocker") != "merchant_payment_production_environment_required":
        raise AssertionError(f"public readiness must retain the production environment blocker: {public}")
    future_launch = json.loads(json.dumps(launch))
    future_launch["provider_connection_evidence"]["latest_verified_at"] = (
        datetime.now(timezone.utc) + timedelta(seconds=60)
    ).isoformat()
    future_public = validate_mainland_payment_launch_for_public(future_launch)
    if future_public.get("provider_connection_proof_ready") is not False:
        raise AssertionError(f"future public proof timestamp must fail closed: {future_public}")

    print("PASS jiejing_wechat_pay_provider_connection_proof")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
