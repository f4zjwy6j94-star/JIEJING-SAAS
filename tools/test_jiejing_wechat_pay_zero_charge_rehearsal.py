#!/usr/bin/env python3
"""Regression for the isolated WeChat Pay zero-charge rehearsal."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.billing_wechat_pay_rehearsal import (  # noqa: E402
    WECHAT_PAY_ZERO_CHARGE_AUDIT_CONTRACT_VERSION,
    WECHAT_PAY_ZERO_CHARGE_AUDIT_TARGET_ID,
    WECHAT_PAY_ZERO_CHARGE_AUDIT_TARGET_TYPE,
    WECHAT_PAY_ZERO_CHARGE_REHEARSAL_CONFIRMATION,
    run_wechat_pay_zero_charge_rehearsal,
)
from jiejing_saas.commercial_launch_gate import _wechat_zero_charge_rehearsal_evidence  # noqa: E402
from jiejing_saas.repository import SaaSRepository  # noqa: E402


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    with patch(
        "jiejing_saas.billing_wechat_pay_rehearsal.rsa.generate_private_key",
        side_effect=AssertionError("wrong phrase reached key generation"),
    ):
        blocked = run_wechat_pay_zero_charge_rehearsal(exact_confirmation="")
    if blocked.get("status") != "blocked" or blocked.get("reason") != "exact_rehearsal_confirmation_required":
        return fail(f"missing exact confirmation must fail closed: {blocked}")
    if blocked.get("transport_invoked") is not False:
        return fail("blocked rehearsal must not touch even the injected fake transport")
    _assert_always_safe(blocked)

    isolated_repository_calls: list[dict[str, object]] = []

    def isolated_repository_factory(
        db_path: Path,
        *,
        database_engine: str | None = None,
        database_url: str | None = None,
    ) -> SaaSRepository:
        isolated_repository_calls.append(
            {
                "db_path": db_path,
                "database_engine": database_engine,
                "database_url": database_url,
            }
        )
        if database_engine != "sqlite" or database_url != "":
            raise AssertionError("isolated rehearsal inherited the production database")
        return SaaSRepository(
            db_path,
            database_engine=database_engine,
            database_url=database_url,
        )

    with patch.dict(
        os.environ,
        {
            "JIEJING_DATABASE_ENGINE": "postgres",
            "JIEJING_DATABASE_URL": "postgresql://production-database-must-not-be-used.invalid/jiejing",
        },
    ), patch(
        "jiejing_saas.billing_wechat_pay_rehearsal.SaaSRepository",
        side_effect=isolated_repository_factory,
    ):
        production_shaped_environment = run_wechat_pay_zero_charge_rehearsal(
            exact_confirmation=WECHAT_PAY_ZERO_CHARGE_REHEARSAL_CONFIRMATION
        )
    if production_shaped_environment.get("status") != "ready":
        return fail(
            "production environment variables must not escape the isolated SQLite rehearsal: "
            f"{production_shaped_environment} calls={isolated_repository_calls}"
        )
    if len(isolated_repository_calls) != 1:
        return fail(f"isolated rehearsal must create exactly one private repository: {isolated_repository_calls}")

    ready = run_wechat_pay_zero_charge_rehearsal(
        exact_confirmation=WECHAT_PAY_ZERO_CHARGE_REHEARSAL_CONFIRMATION
    )
    if ready.get("status") != "ready" or ready.get("ready_for_owner_review") is not True:
        return fail(f"isolated WeChat rehearsal should complete: {ready}")
    if ready.get("transport_invoked") is not True or ready.get("fake_transport_call_count") != 1:
        return fail(f"exact confirmation should invoke the internal fake transport once: {ready}")
    steps = {
        str(item.get("key") or ""): item
        for item in ready.get("steps", [])
        if isinstance(item, dict)
    }
    expected_steps = {
        "native_order_request_contract",
        "signed_callback_and_replay",
        "entitlement_after_verified_payment",
        "refund_confirmation_boundary",
        "refund_accounting_recovery",
    }
    if set(steps) != expected_steps or any(item.get("status") != "ready" for item in steps.values()):
        return fail(f"WeChat zero-charge rehearsal steps are incomplete: {steps}")
    if steps["signed_callback_and_replay"].get("verified_apply_count") != 1:
        return fail("signed callback replay must apply payment exactly once")
    if steps["refund_confirmation_boundary"].get("provider_call_count") != 0:
        return fail("refund transport must stay untouched before exact confirmation approval")
    if steps["refund_accounting_recovery"].get("entitlement_closed") is not True:
        return fail("verified fake refund result must close the isolated entitlement")
    _assert_always_safe(ready)

    with tempfile.TemporaryDirectory(
        prefix="jiejing-wechat-rehearsal-audit-",
        ignore_cleanup_errors=True,
    ) as temp_dir:
        repository = SaaSRepository(Path(temp_dir) / "audit.sqlite")
        owner = repository.create_user_with_company(
            email="wechat-rehearsal-audit@example.test",
            password="WeChat-rehearsal-audit-2026",
            company_name="WeChat Rehearsal Audit",
        )
        company_id = str(owner["company"]["company_id"])
        user_id = str(owner["user"]["user_id"])
        audited = run_wechat_pay_zero_charge_rehearsal(
            exact_confirmation=WECHAT_PAY_ZERO_CHARGE_REHEARSAL_CONFIRMATION,
            repository=repository,
            company_id=company_id,
            user_id=user_id,
        )
        if audited.get("evidence_recorded") is not True:
            return fail(f"authenticated rehearsal must record safe backend evidence: {audited}")
        audit_logs = repository.list_audit_logs(company_id=company_id, limit=10)
        audit = next(
            (
                item
                for item in audit_logs
                if item.get("action_type") == "billing.wechat_pay.zero_charge_rehearsal.completed"
            ),
            {},
        )
        if not audit:
            return fail("WeChat rehearsal audit evidence was not persisted")
        details = audit.get("details") if isinstance(audit.get("details"), dict) else {}
        build_artifact_id = str(details.get("build_artifact_id") or "")
        if (
            details.get("contract_version") != WECHAT_PAY_ZERO_CHARGE_AUDIT_CONTRACT_VERSION
            or audit.get("target_type") != WECHAT_PAY_ZERO_CHARGE_AUDIT_TARGET_TYPE
            or audit.get("target_id") != WECHAT_PAY_ZERO_CHARGE_AUDIT_TARGET_ID
            or len(build_artifact_id) != 64
            or any(character not in "0123456789abcdef" for character in build_artifact_id)
        ):
            return fail(f"rehearsal audit must bind contract, target and current build: {audit}")
        current_evidence = _wechat_zero_charge_rehearsal_evidence(
            repository=repository,
            company_id=company_id,
        )
        if current_evidence.get("ready") is not True:
            return fail(f"fresh current-build rehearsal evidence should be ready: {current_evidence}")
        if build_artifact_id in json.dumps(current_evidence, ensure_ascii=False):
            return fail("public commercial evidence must not expose the build artifact id")
        for index in range(150):
            repository.write_audit(
                company_id=company_id,
                user_id=user_id,
                actor_type="user",
                action_type="test.unrelated.high_volume_audit",
                target_type="unrelated_test_target",
                target_id=f"noise-{index}",
                summary="Unrelated sanitized test audit.",
                details={"secret_exposed": False},
            )
        latest_page = repository.list_audit_logs(company_id=company_id, limit=100)
        if any(
            item.get("action_type") == "billing.wechat_pay.zero_charge_rehearsal.completed"
            for item in latest_page
        ):
            return fail("high-volume audit fixture did not displace rehearsal evidence from latest 100")
        crowded_evidence = _wechat_zero_charge_rehearsal_evidence(
            repository=repository,
            company_id=company_id,
        )
        if crowded_evidence.get("ready") is not True:
            return fail(f"targeted rehearsal evidence must survive unrelated audit volume: {crowded_evidence}")

        now = datetime.now(timezone.utc).replace(microsecond=0)
        cases: list[tuple[str, dict[str, object]]] = []
        missing = deepcopy(audit)
        missing["details"].pop("contract_version", None)
        cases.append(("missing_contract", missing))
        malformed = deepcopy(audit)
        malformed["details"]["ready"] = "true"
        cases.append(("malformed", malformed))
        old = deepcopy(audit)
        old["created_at"] = (now - timedelta(hours=25)).isoformat()
        cases.append(("old", old))
        future = deepcopy(audit)
        future["created_at"] = (now + timedelta(minutes=6)).isoformat()
        cases.append(("future", future))
        wrong_target = deepcopy(audit)
        wrong_target["target_id"] = "wrong-target"
        cases.append(("wrong_target", wrong_target))
        wrong_version = deepcopy(audit)
        wrong_version["details"]["contract_version"] = "wrong-version"
        cases.append(("wrong_version", wrong_version))
        wrong_build = deepcopy(audit)
        wrong_build["details"]["build_artifact_id"] = "f" * 64
        cases.append(("wrong_build", wrong_build))
        for label, candidate in cases:
            candidate_evidence = _wechat_zero_charge_rehearsal_evidence(
                repository=_AuditRepository(candidate),
                company_id=company_id,
                now=now,
                expected_build_artifact_id=build_artifact_id,
            )
            if candidate_evidence.get("ready") is not False:
                return fail(f"{label} rehearsal audit must fail closed: {candidate_evidence}")
        unavailable_evidence = _wechat_zero_charge_rehearsal_evidence(
            repository=_UnavailableAuditRepository(),
            company_id=company_id,
            now=now,
            expected_build_artifact_id=build_artifact_id,
        )
        if unavailable_evidence.get("evidence_code") != "zero_charge_rehearsal_audit_unavailable":
            return fail(f"targeted audit query errors must fail closed: {unavailable_evidence}")

    serialized = json.dumps({"blocked": blocked, "ready": ready}, ensure_ascii=False).lower()
    for forbidden in (
        "merchant_private_key",
        "api_v3_key",
        "platform_certificate",
        "transaction_id",
        "order_id",
        "mchid",
        "appid",
        "pem",
    ):
        if forbidden in serialized:
            return fail(f"public rehearsal report leaked a forbidden field: {forbidden}")
    api_server = (ROOT / "jiejing_saas" / "api_server.py").read_text(encoding="utf-8")
    if "billing/wechat-pay/zero-charge-rehearsal" not in api_server:
        return fail("authenticated WeChat zero-charge rehearsal route is missing")
    if "run_wechat_pay_zero_charge_rehearsal" not in api_server:
        return fail("WeChat rehearsal route is not wired to the dedicated implementation")
    runbook = (
        ROOT / "docs" / "JIEJING_WECHAT_PAY_PRODUCTION_RUNBOOK_20260713.md"
    ).read_text(encoding="utf-8")
    normalized_runbook = " ".join(runbook.split())
    if (
        "The successful report and tenant-scoped audit are limited to sanitized "
        "contract/version, mode, status, and step-key metadata plus booleans, codes, "
        "and counts."
    ) not in normalized_runbook:
        return fail("runbook must describe the sanitized zero-charge metadata contract precisely")
    if "contain only booleans, status codes, and counts" in normalized_runbook:
        return fail("runbook must not contradict the sanitized metadata contract")
    if (
        "They contain no merchant, order, transaction, key, certificate, PEM, or "
        "filesystem-path value."
    ) not in normalized_runbook:
        return fail("runbook must retain the explicit forbidden-value boundary")

    print("PASS jiejing_wechat_pay_zero_charge_rehearsal")
    return 0


def _assert_always_safe(report: dict[str, object]) -> None:
    for key in (
        "creates_real_order",
        "calls_external_api",
        "calls_external_payment_api",
        "triggers_charge",
        "triggers_real_charge",
        "charge_allowed",
        "public_charging_allowed",
        "triggers_real_refund",
        "secret_exposed",
    ):
        if report.get(key) is not False:
            raise AssertionError(f"{key} must remain false: {report}")


class _AuditRepository:
    def __init__(self, audit: dict[str, object]) -> None:
        self.audit = audit

    def find_latest_audit_log_by_target(
        self,
        *,
        company_id: str,
        store_id: str | None,
        action_type: str,
        target_type: str,
        target_id: str,
    ) -> dict[str, object] | None:
        del company_id
        if (
            store_id is None
            and action_type == "billing.wechat_pay.zero_charge_rehearsal.completed"
            and target_type == WECHAT_PAY_ZERO_CHARGE_AUDIT_TARGET_TYPE
            and target_id == WECHAT_PAY_ZERO_CHARGE_AUDIT_TARGET_ID
        ):
            return self.audit
        return None


class _UnavailableAuditRepository:
    def find_latest_audit_log_by_target(self, **kwargs: object) -> None:
        del kwargs
        raise RuntimeError("simulated targeted audit query failure")


if __name__ == "__main__":
    raise SystemExit(main())
