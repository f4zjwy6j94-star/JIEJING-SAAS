#!/usr/bin/env python3
"""Regression for the mainland paid-launch owner approval packet."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.config import SaaSSettings  # noqa: E402
from jiejing_saas.paid_launch_approval_packet import build_paid_launch_approval_packet  # noqa: E402
from jiejing_saas.repository import SaaSRepository  # noqa: E402


PRIMARY_SEQUENCE = {
    "stable_domain_hardening",
    "wechat_pay_native_cutover",
    "no_charge_launch_rehearsal",
    "new_ebay_account_low_risk_smoke",
}

WECHAT_ENV_KEYS = {
    "JIEJING_WECHAT_PAY_APP_ID",
    "JIEJING_WECHAT_PAY_MCH_ID",
    "JIEJING_WECHAT_PAY_MERCHANT_SERIAL_NO",
    "JIEJING_WECHAT_PAY_MERCHANT_PRIVATE_KEY_PEM",
    "JIEJING_WECHAT_PAY_API_V3_KEY",
    "JIEJING_WECHAT_PAY_NOTIFY_URL",
    "JIEJING_WECHAT_PAY_REFUND_NOTIFY_URL",
    "JIEJING_WECHAT_PAY_LIVE_API_ENABLED",
    "JIEJING_WECHAT_PAY_CHARGE_ALLOWED",
    "JIEJING_WECHAT_PAY_REFUND_ALLOWED",
}

NO_CHARGE_ENV = {
    "JIEJING_CUTOVER_ROLLBACK_VERIFIED": "1",
    "JIEJING_SECRET_SCAN_PASSED": "1",
    "JIEJING_READINESS_SNAPSHOT_RECORDED": "1",
    "JIEJING_BROWSER_SMOKE_PASSED": "1",
    "JIEJING_CUTOVER_ROLLBACK_AUDIT_PACKET_ID": "rollback-packet-present",
    "JIEJING_NO_CHARGE_SIGNED_WEBHOOK_SMOKE_PASSED": "1",
    "JIEJING_NO_CHARGE_READINESS_SMOKE_PASSED": "1",
    "JIEJING_NO_CHARGE_LIVE_DOMAIN_REHEARSAL_EVIDENCE_ID": "no-charge-evidence-present",
    "JIEJING_FINAL_COMMERCIAL_SMOKE_PASSED": "1",
    "JIEJING_FINAL_COMMERCIAL_SMOKE_EVIDENCE_ID": "final-smoke-evidence-present",
}


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    with tempfile.TemporaryDirectory(
        prefix="jiejing-paid-launch-packet-",
        ignore_cleanup_errors=True,
    ) as temp_dir:
        settings, repository = _runtime(Path(temp_dir))

        blocked = _build(
            settings,
            repository,
            mainland=_mainland_payment(owner_ready=False),
            domain_ready=False,
            no_charge_ready=False,
            new_account_ready=False,
        )
        if blocked.get("contract_version") != "2026-07-27-paid-launch-approval-packet-v2":
            return fail("approval packet contract version was not migrated")
        if blocked.get("status") != "blocked" or blocked.get("ready_for_owner_approval") is not False:
            return fail(f"blocked fixture should stay blocked: {blocked.get('summary')}")
        if set(_by_key(blocked.get("steps"))) != PRIMARY_SEQUENCE:
            return fail(f"approval packet steps drifted: {sorted(_by_key(blocked.get('steps')))}")
        if blocked.get("charge_now_allowed") is not False or blocked.get("calls_stripe_api") is not False:
            return fail("approval packet must not allow charging or call Stripe")
        if blocked.get("triggers_real_charge") is not False or blocked.get("triggers_real_platform_write") is not False:
            return fail("approval packet must remain no-charge and no-write")

        ready = _build(
            settings,
            repository,
            mainland=_mainland_payment(owner_ready=True),
            domain_ready=True,
            no_charge_ready=True,
            new_account_ready=True,
        )
        ready_steps = _by_key(ready.get("steps"))
        if ready.get("status") != "ready_for_owner_approval" or ready.get("ready_for_owner_approval") is not True:
            return fail(f"complete mainland fixture should be ready for owner approval: {ready.get('summary')}")
        if ready.get("public_paid_launch_allowed") is not False or ready.get("charge_now_allowed") is not False:
            return fail("owner-ready packet must never enable public charging")
        if ready_steps["wechat_pay_native_cutover"].get("status") != "ready":
            return fail(f"WeChat Native cutover should be owner-ready: {ready_steps['wechat_pay_native_cutover']}")
        if ready_steps["no_charge_launch_rehearsal"].get("status") != "ready":
            return fail(f"provider-neutral no-charge rehearsal should be ready: {ready_steps['no_charge_launch_rehearsal']}")
        summary = ready.get("summary") if isinstance(ready.get("summary"), dict) else {}
        if summary.get("blocked_count") != 0 or summary.get("next_step") != "":
            return fail(f"legacy Stripe rehearsal must not affect blocked count or next step: {summary}")
        if (
            summary.get("production_ready") is not False
            or summary.get("beta_ready") is not True
            or summary.get("can_accept_real_customers") is not False
        ):
            return fail(f"exact public-charge-hold preapproval state drifted: {summary}")

        final_ready = _build(
            settings,
            repository,
            mainland=_mainland_payment(owner_ready=True),
            domain_ready=True,
            no_charge_ready=True,
            new_account_ready=True,
            readiness_override=_final_product_readiness(),
        )
        if final_ready.get("ready_for_owner_approval") is not True:
            return fail(f"future all-green final readiness state must remain accepted: {final_ready.get('summary')}")

        invalid_readiness_cases = {
            "all_false": {
                **_preapproval_product_readiness(),
                "beta_ready": False,
            },
            "wrong_reason": {
                **_preapproval_product_readiness(),
                "reason": "generic_not_ready",
            },
            "extra_warning": {
                **_preapproval_product_readiness(),
                "warning_count": 2,
                "items": [
                    *_preapproval_product_readiness()["items"],
                    _readiness_item("another_warning", "not_ready", "warning"),
                ],
            },
            "blocker": {
                **_preapproval_product_readiness(),
                "blocker_count": 1,
                "items": [
                    *_preapproval_product_readiness()["items"],
                    _readiness_item("database_reachability", "blocked", "blocker"),
                ],
            },
            "count_mismatch": {
                **_preapproval_product_readiness(),
                "warning_count": 0,
            },
            "malformed_item": {
                **_preapproval_product_readiness(),
                "items": [{"key": "billing_quota", "status": True, "severity": "warning"}],
            },
        }
        for label, product_not_ready in invalid_readiness_cases.items():
            product_blocked = _build(
                settings,
                repository,
                mainland=_mainland_payment(owner_ready=True),
                domain_ready=True,
                no_charge_ready=True,
                new_account_ready=True,
                readiness_override=product_not_ready,
            )
            if (
                product_blocked.get("status") != "blocked"
                or product_blocked.get("ready_for_owner_approval") is not False
            ):
                return fail(f"strict product readiness must reject {label}: {product_blocked.get('summary')}")

        cross_store = _build(
            settings,
            repository,
            mainland=_mainland_payment(owner_ready=True),
            domain_ready=True,
            no_charge_ready=True,
            new_account_ready=True,
            ebay_hash_mismatch=True,
        )
        cross_store_step = _by_key(cross_store.get("steps")).get("new_ebay_account_low_risk_smoke") or {}
        if cross_store_step.get("status") != "blocked" or cross_store.get("ready_for_owner_approval") is not False:
            return fail("paid launch must reject all-true OAuth/evidence assembled from different store/connection hashes")

        external = _by_key(ready.get("external_configuration_needed"))
        if "wechat_pay_native_production_cutover" not in external:
            return fail(f"WeChat production cutover item missing: {sorted(external)}")
        if "stripe_live_products_prices_webhook" in external:
            return fail("Stripe live configuration must not remain in the mainland external sequence")
        wechat_keys = set(external["wechat_pay_native_production_cutover"].get("environment_keys") or [])
        if not WECHAT_ENV_KEYS.issubset(wechat_keys):
            return fail(f"WeChat backend environment keys incomplete: {sorted(WECHAT_ENV_KEYS - wechat_keys)}")
        if any("STRIPE" in key for key in wechat_keys):
            return fail(f"Stripe key leaked into WeChat cutover item: {sorted(wechat_keys)}")
        ebay_keys = set(external["clean_new_ebay_account_and_fresh_product"].get("environment_keys") or [])
        if {
            "JIEJING_NEW_EBAY_OAUTH_OPERATOR_APPROVED",
            "JIEJING_NEW_EBAY_ACCOUNT_OAUTH_COMPLETED",
        } & ebay_keys:
            return fail("paid launch packet must not present OAuth env flags as completion evidence")
        for item in external.values():
            if item.get("frontend_gets_secret") is not False or item.get("secret_exposed") is not False:
                return fail(f"external configuration item leaked secret surface: {item.get('key')}")

        future = ready.get("future_international_payment")
        if not isinstance(future, dict) or future.get("provider") != "stripe":
            return fail(f"Stripe should remain only as future international information: {future}")
        if future.get("blocks_mainland_launch") is not False or future.get("calls_stripe_api") is not False:
            return fail(f"future international lane must not block or call Stripe: {future}")
        mainland_projection = {
            "steps": [
                {
                    key: step.get(key)
                    for key in ("key", "title", "evidence_summary", "next_action", "verification", "blocked_by")
                }
                for step in ready.get("steps") or []
                if isinstance(step, dict)
            ],
            "external_configuration_needed": [
                {
                    key: item.get(key)
                    for key in ("key", "title", "environment_keys", "evidence_summary")
                }
                for item in ready.get("external_configuration_needed") or []
                if isinstance(item, dict)
            ],
            "blocked_keys": summary.get("blocked_keys"),
            "next_step": summary.get("next_step"),
        }
        if "stripe" in json.dumps(mainland_projection, ensure_ascii=False).lower():
            return fail("Stripe still participates in the mainland primary sequence")

        malformed = _mainland_payment(owner_ready=True)
        malformed["market"] = "not-mainland"
        malformed_packet = _build(
            settings,
            repository,
            mainland=malformed,
            domain_ready=True,
            no_charge_ready=True,
            new_account_ready=True,
        )
        malformed_step = _by_key(malformed_packet.get("steps")).get("wechat_pay_native_cutover") or {}
        if malformed_step.get("status") != "blocked":
            return fail(f"malformed canonical status must fail closed: {malformed_step}")

        readiness_sentinel = "paid-readiness-malformed-must-not-leak"
        for malformed_readiness in (
            [readiness_sentinel],
            readiness_sentinel,
            {"production_ready": float("nan"), "beta_ready": {"nested": readiness_sentinel}, "can_accept_real_customers": [readiness_sentinel]},
        ):
            try:
                malformed_readiness_packet = _build(
                    settings,
                    repository,
                    mainland=_mainland_payment(owner_ready=True),
                    domain_ready=True,
                    no_charge_ready=True,
                    new_account_ready=True,
                    readiness_override=malformed_readiness,
                )
                malformed_readiness_serialized = json.dumps(
                    malformed_readiness_packet,
                    ensure_ascii=False,
                    allow_nan=False,
                )
            except (TypeError, ValueError, OverflowError) as exc:
                return fail(f"paid launch malformed readiness must return stable JSON: {type(exc).__name__}")
            if malformed_readiness_packet.get("ready_for_owner_approval") is not False:
                return fail("paid launch malformed readiness must fail closed")
            if readiness_sentinel in malformed_readiness_serialized:
                return fail("paid launch malformed readiness values must not be reflected")

        missing_evidence = _build(
            settings,
            repository,
            mainland=_mainland_payment(owner_ready=True),
            domain_ready=True,
            no_charge_ready=False,
            new_account_ready=True,
        )
        missing_summary = missing_evidence.get("summary") if isinstance(missing_evidence.get("summary"), dict) else {}
        missing_step = _by_key(missing_evidence.get("steps")).get("no_charge_launch_rehearsal") or {}
        if missing_summary.get("next_step") != "no_charge_launch_rehearsal":
            return fail(f"missing no-charge proof should be the next blocker: {missing_summary}")
        if "wechat_zero_charge_rehearsal_evidence_missing" not in set(missing_step.get("blocked_by") or []):
            return fail(f"missing no-charge proof blocker is not precise: {missing_step}")

        serialized = json.dumps(ready, ensure_ascii=False).lower()
        for forbidden in ("authorization: bearer", "refresh_token=", "access_token=", "client_secret=", "merchant_private_key_pem="):
            if forbidden in serialized:
                return fail(f"approval packet leaked forbidden marker: {forbidden}")
        docs = set(ready.get("docs") or [])
        if "docs/superpowers/specs/2026-07-13-wechat-pay-native-design.md" not in docs:
            return fail(f"approved WeChat design is missing from packet docs: {sorted(docs)}")
        if "docs/JIEJING_WECHAT_PAY_PRODUCTION_RUNBOOK_20260713.md" not in docs:
            return fail(f"WeChat production runbook is missing from packet docs: {sorted(docs)}")

    print("PASS jiejing_paid_launch_approval_packet")
    return 0


def _runtime(root: Path) -> tuple[SaaSSettings, SaaSRepository]:
    settings = SaaSSettings.from_env(
        db_path=root / "saas.sqlite",
        runtime_db_path=root / "runtime.sqlite",
        output_root=root / "output",
        host="127.0.0.1",
        port=8788,
    )
    repository = SaaSRepository(settings.db_path)
    repository.initialize()
    return settings, repository


def _build(
    settings: SaaSSettings,
    repository: SaaSRepository,
    *,
    mainland: dict[str, object],
    domain_ready: bool,
    no_charge_ready: bool,
    new_account_ready: bool,
    omitted_env_key: str = "",
    readiness_override: object | None = None,
    ebay_hash_mismatch: bool = False,
) -> dict[str, object]:
    env_values = dict(NO_CHARGE_ENV) if no_charge_ready else {key: "" for key in NO_CHARGE_ENV}
    if omitted_env_key:
        env_values.pop(omitted_env_key, None)
    previous = {key: os.environ.get(key) for key in NO_CHARGE_ENV}
    for key in NO_CHARGE_ENV:
        if key in env_values:
            os.environ[key] = env_values[key]
        else:
            os.environ.pop(key, None)
    try:
        action_plan = {
            "paid_launch_cutover_decision": {
                "status": "blocked",
                "public_paid_launch_allowed": False,
                "wechat_zero_charge_rehearsal_ready": no_charge_ready,
            },
            "paid_launch_cutover_checklist": [],
            "new_ebay_account_smoke_runbook": [
                {"key": "clean_account", "status": "ready" if new_account_ready else "blocked"}
            ],
            "commercial_hardening_drills": [],
        }
        with ExitStack() as stack:
            stack.enter_context(
                patch(
                    "jiejing_saas.paid_launch_approval_packet.build_product_readiness_or_degraded",
                    return_value=(
                        readiness_override
                        if readiness_override is not None
                        else _preapproval_product_readiness()
                    ),
                )
            )
            stack.enter_context(
                patch("jiejing_saas.paid_launch_approval_packet.build_domain_readiness", return_value={
                    "production_domain_ready": domain_ready,
                    "stable_domain": "app.jiejing.shop" if domain_ready else "not_selected",
                    "dns_verified": domain_ready,
                    "tls_verified": domain_ready,
                    "ebay_callback_verified": domain_ready,
                    "cors_origin_aligned": domain_ready,
                    "security_headers_verified": domain_ready,
                    "blockers": [] if domain_ready else ["stable_domain_required"],
                })
            )
            stack.enter_context(
                patch("jiejing_saas.paid_launch_approval_packet.build_commercial_launch_gate", return_value={
                    "launch_action_plan": action_plan,
                    "current_store_oauth_boundary": {
                        "store_id_sha256": "store-current-hash",
                        "connection_id_sha256": "connection-oauth-hash",
                        "authorized": new_account_ready,
                        "current_store_selected": new_account_ready,
                        "strong_identity_ready": new_account_ready,
                        "backend_provenance_ready": new_account_ready,
                        "secret_exposed": False,
                    },
                    "current_store_ebay_evidence": {
                        "store_id_sha256": "store-other-hash" if ebay_hash_mismatch else "store-current-hash",
                        "connection_id_sha256": "connection-other-hash" if ebay_hash_mismatch else "connection-oauth-hash",
                        "secret_exposed": False,
                    },
                })
            )
            stack.enter_context(
                patch("jiejing_saas.paid_launch_approval_packet.build_mainland_payment_launch_status", return_value=mainland)
            )
            return build_paid_launch_approval_packet(settings, repository)
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _mainland_payment(*, owner_ready: bool) -> dict[str, object]:
    configured = owner_ready
    verified_count = 1 if owner_ready else 0
    return {
        "contract_version": "2026-07-27-mainland-payment-launch-v1",
        "market": "mainland_china",
        "primary_provider": "wechat_pay_native",
        "checkout_mode": "native_qr",
        "billing_mode": "one_time_30_day_plan",
        "future_international_payment": {
            "provider": "stripe",
            "role": "future_international_payment_only",
            "selected": False,
            "blocks_mainland_launch": False,
            "calls_stripe_api": False,
            "triggers_real_charge": False,
            "secret_exposed": False,
        },
        "configuration": {
            "required_count": 9,
            "completed_count": 9 if configured else 0,
            "complete": configured,
        },
        "code_capabilities": {
            "signed_payment_callback_implemented": True,
            "signed_refund_callback_implemented": True,
            "real_order_creation_implemented": True,
            "authenticated_order_query_implemented": True,
            "quota_entitlement_persistence_implemented": True,
            "high_risk_confirmation_boundary_implemented": True,
        },
        "acceptance_evidence": {
            "contract_version": "2026-07-27-domestic-payment-acceptance-evidence-v2",
            "provider": "wechat_pay_native",
            "acceptance_kind": "owner_approved_one_cny_live_acceptance",
            "controlled_acceptance_proven": owner_ready,
            "verified_paid_order_count": verified_count,
            "public_charging_allowed": False,
            "charge_now_allowed": False,
            "triggers_real_charge": False,
            "calls_external_payment_api": False,
            "secret_exposed": False,
        },
        "controlled_acceptance_proven": owner_ready,
        "provider_checkout_ready": owner_ready,
        "provider_runtime_activation_enabled": owner_ready,
        "provider_connection_evidence": {
            "contract_version": "2026-08-21-wechat-pay-provider-connection-evidence-v1",
            "provider": "wechat_pay_native",
            "proof_kind": "signed_read_only_order_query",
            "provider_connection_proof_ready": False,
            "verified_proof_count": 0,
            "latest_verified_at": "",
            "freshness_window_seconds": 86400,
            "proof_query_called_external_api": False,
            "calls_external_payment_api": False,
            "creates_payable_order": False,
            "public_charging_allowed": False,
            "charge_now_allowed": False,
            "triggers_real_charge": False,
            "triggers_real_refund": False,
            "real_platform_writes_enabled": False,
            "secret_exposed": False,
        },
        "production_environment": owner_ready,
        "refund_now_allowed": owner_ready,
        "mainland_payment_ready_for_owner_approval": owner_ready,
        "paid_launch_blockers": (
            ["paid_launch_owner_approval_packet_missing", "public_charging_requires_higher_commercial_release_gate"]
            if owner_ready
            else ["wechat_pay_configuration_contract_missing"]
        ),
        "public_charging_allowed": False,
        "charge_now_allowed": False,
        "triggers_real_charge": False,
        "triggers_real_refund": False,
        "calls_external_payment_api": False,
        "calls_stripe_api": False,
        "real_platform_writes_enabled": False,
        "frontend_gets_payment_secret": False,
        "secret_exposed": False,
    }


def _readiness_item(key: str, status: str, severity: str) -> dict[str, object]:
    return {
        "key": key,
        "label": key,
        "status": status,
        "severity": severity,
        "detail": "sanitized readiness detail",
        "next_action": "sanitized next action",
    }


def _preapproval_product_readiness() -> dict[str, object]:
    return {
        "production_ready": False,
        "beta_ready": True,
        "can_accept_real_customers": False,
        "reason": "expected_public_charge_approval_hold",
        "blocker_count": 0,
        "warning_count": 1,
        "items": [
            _readiness_item(
                "billing_quota",
                "mainland_payment_ready_for_owner_approval",
                "warning",
            )
        ],
    }


def _final_product_readiness() -> dict[str, object]:
    return {
        "production_ready": True,
        "beta_ready": True,
        "can_accept_real_customers": True,
        "reason": "ready",
        "blocker_count": 0,
        "warning_count": 0,
        "items": [],
    }


def _by_key(value: object) -> dict[str, dict[str, object]]:
    if not isinstance(value, list):
        return {}
    return {
        str(item.get("key") or ""): item
        for item in value
        if isinstance(item, dict) and str(item.get("key") or "")
    }


if __name__ == "__main__":
    raise SystemExit(main())
