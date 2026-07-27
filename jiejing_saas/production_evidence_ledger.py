"""Internal production evidence ledger for Jiejing SaaS.

This ledger normalizes the release-gate evidence into an operator-reviewable
packet. It is read-only, owner-only, and never records raw secret values.
"""

from __future__ import annotations

from typing import Any

from .config import SaaSSettings
from .production_release_gate import build_production_release_gate
from .repository import SaaSRepository


PRODUCTION_EVIDENCE_LEDGER_VERSION = "2026-07-27-production-evidence-ledger-v2"


_SECTION_SOURCE_TYPES = {
    "deployment_artifact_and_rollback": "release_artifact_and_local_smoke",
    "stable_domain_edge_origin_callbacks": "external_dns_tls_waf_and_callback_console",
    "managed_data_plane_and_secret_boundary": "managed_cloud_runtime_and_backend_live_probe",
    "backup_restore_dr_and_secret_recovery": "managed_backup_restore_drill_and_alert",
    "mainland_wechat_payment_and_refund_controls": "wechat_native_signed_callbacks_query_refund_and_controlled_acceptance",
    "ebay_clean_account_refresh_and_write_boundary": "backend_audit_log_and_clean_platform_account",
    "monitoring_alerts_incidents_and_customer_support": "cloud_monitoring_alerts_and_runbooks",
    "final_owner_approval_and_launch_switch_hold": "owner_approval_packet_and_launch_switch_review",
}


_SECTION_CATEGORIES = {
    "deployment_artifact_and_rollback": "deployment",
    "stable_domain_edge_origin_callbacks": "edge",
    "managed_data_plane_and_secret_boundary": "infrastructure",
    "backup_restore_dr_and_secret_recovery": "recovery",
    "mainland_wechat_payment_and_refund_controls": "billing",
    "ebay_clean_account_refresh_and_write_boundary": "platform",
    "monitoring_alerts_incidents_and_customer_support": "operations",
    "final_owner_approval_and_launch_switch_hold": "approval",
}


_EXTERNAL_TO_SECTION = {
    "stable_domain_edge_origin": "stable_domain_edge_origin_callbacks",
    "managed_postgres_redis_vault": "managed_data_plane_and_secret_boundary",
    "backup_restore_drill": "backup_restore_dr_and_secret_recovery",
    "wechat_pay_native_production_cutover": "mainland_wechat_payment_and_refund_controls",
    "new_ebay_account_refresh": "ebay_clean_account_refresh_and_write_boundary",
    "monitoring_incident_support": "monitoring_alerts_incidents_and_customer_support",
    "final_owner_approval": "final_owner_approval_and_launch_switch_hold",
}


def build_production_evidence_ledger(settings: SaaSSettings, repository: SaaSRepository) -> dict[str, Any]:
    """Build the internal evidence ledger without side effects."""

    gate = build_production_release_gate(settings, repository)
    sections = [section for section in gate.get("sections", []) if isinstance(section, dict)]
    section_rows = [_section_row(section, index + 1) for index, section in enumerate(sections)]
    external_rows = _external_rows(gate, section_rows)
    blocked_rows = [row for row in section_rows if row.get("status") != "ready"]
    missing = _next_missing_evidence(section_rows)
    ready_for_owner_approval = bool(gate.get("ready_for_owner_approval")) and not blocked_rows
    return {
        "contract_version": PRODUCTION_EVIDENCE_LEDGER_VERSION,
        "mode": "internal_admin_read_only_evidence_review_no_charge_no_write",
        "audience": "platform_internal_admin",
        "environment": settings.environment,
        "status": "ready_for_owner_approval" if ready_for_owner_approval else "blocked",
        "decision": "ready_for_owner_approval_not_auto_launch" if ready_for_owner_approval else "keep_public_launch_blocked",
        "ready_for_owner_approval": ready_for_owner_approval,
        "requires_owner_approval_before_public_launch": True,
        "customer_visible": False,
        "ordinary_merchant_visible": False,
        "summary": {
            "ready_count": len(section_rows) - len(blocked_rows),
            "total_count": len(section_rows),
            "blocked_count": len(blocked_rows),
            "blocked_section_keys": [str(row.get("section_key") or "") for row in blocked_rows],
            "next_missing_section": (missing[0] if missing else {}).get("section_key", ""),
            "next_missing_check": (missing[0] if missing else {}).get("check", ""),
            "external_evidence_count": len(external_rows),
            "external_evidence_ready_count": len([row for row in external_rows if row.get("status") == "ready"]),
            "public_paid_launch_allowed": False,
            "charge_now_allowed": False,
            "platform_write_now_allowed": False,
            "repeat_ebay_oauth_allowed": False,
            "secret_exposed": False,
        },
        "evidence_rows": section_rows,
        "external_evidence_rows": external_rows,
        "next_missing_evidence": missing,
        "acceptance_rules": {
            "raw_secret_values_allowed_in_ledger": False,
            "secret_names_may_appear_but_values_must_stay_in_backend_env_or_vault": True,
            "config_flag_alone_is_not_customer_launch_proof": True,
            "ebay_refresh_requires_backend_audit_log_proof": True,
            "mainland_payment_requires_signed_callbacks_query_refund_and_controlled_acceptance": True,
            "owner_approval_is_required_but_never_auto_launches_public_paid_mode": True,
            "old_frozen_ebay_account_or_old_demo_sku_is_not_accepted_as_evidence": True,
        },
        "audit_log_requirements": [
            {
                "key": "ebay_refresh_success",
                "action_type": "oauth.token_refresh.executed",
                "required_before_public_launch": True,
                "frontend_gets_token": False,
                "secret_exposed": False,
            },
            {
                "key": "wechat_payment_lifecycle",
                "action_type": "billing.wechat_pay.*",
                "required_before_public_launch": True,
                "frontend_gets_payment_secret": False,
                "secret_exposed": False,
            },
            {
                "key": "owner_approval_packet",
                "action_type": "production_release.owner_approval.recorded",
                "required_before_public_launch": True,
                "auto_launches_public_paid_mode": False,
                "secret_exposed": False,
            },
        ],
        "production_release_gate_status": gate.get("status") or "unknown",
        "production_release_gate_contract_version": gate.get("contract_version") or "",
        "public_paid_launch_allowed": False,
        "charge_now_allowed": False,
        "creates_checkout_session": False,
        "calls_stripe_api": False,
        "triggers_real_charge": False,
        "triggers_ebay_oauth": False,
        "repeat_ebay_oauth_allowed": False,
        "triggers_real_platform_write": False,
        "platform_write_now_allowed": False,
        "frontend_gets_payment_secret": False,
        "frontend_gets_provider_secret": False,
        "frontend_gets_ebay_token": False,
        "exports_raw_secret": False,
        "includes_raw_tokens": False,
        "secret_exposed": False,
    }


def _section_row(section: dict[str, Any], order: int) -> dict[str, Any]:
    key = str(section.get("key") or "")
    env_keys = [str(item) for item in section.get("environment_keys", []) if item]
    blocked_checks = [str(item) for item in section.get("blocked_checks", []) if item]
    checks = section.get("checks") if isinstance(section.get("checks"), dict) else {}
    return {
        "order": order,
        "section_key": key,
        "category": _SECTION_CATEGORIES.get(key, "release"),
        "title": str(section.get("title") or key),
        "status": "ready" if section.get("status") == "ready" else "blocked",
        "ready_count": int(section.get("ready_count") or 0),
        "total_count": int(section.get("total_count") or len(checks)),
        "blocked_checks": blocked_checks,
        "proof_source_type": _SECTION_SOURCE_TYPES.get(key, "release_gate_section"),
        "verification": [str(item) for item in section.get("verification", []) if item],
        "environment_key_names": env_keys,
        "backend_only_secret_key_names": [key_name for key_name in env_keys if _looks_secret_env_key(key_name)],
        "raw_secret_value_allowed": False,
        "external_resource_required": section.get("external_resource_required") is True,
        "customer_visible": False,
        "ordinary_merchant_visible": False,
        "evidence_summary": str(section.get("evidence_summary") or "")[:900],
        "next_action": str(section.get("next_action") or ""),
        "public_paid_launch_allowed": False,
        "charge_now_allowed": False,
        "creates_checkout_session": False,
        "calls_stripe_api": False,
        "triggers_real_charge": False,
        "triggers_ebay_oauth": False,
        "repeat_ebay_oauth_allowed": False,
        "triggers_real_platform_write": False,
        "platform_write_now_allowed": False,
        "frontend_gets_payment_secret": False,
        "frontend_gets_provider_secret": False,
        "frontend_gets_ebay_token": False,
        "secret_exposed": False,
    }


def _external_rows(gate: dict[str, Any], section_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sections = {str(row.get("section_key") or ""): row for row in section_rows}
    rows: list[dict[str, Any]] = []
    for index, item in enumerate(gate.get("required_external_evidence", []) or [], start=1):
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "")
        section_key = _EXTERNAL_TO_SECTION.get(key, "")
        linked = sections.get(section_key, {})
        env_keys = [str(value) for value in item.get("environment_keys", []) if value]
        rows.append(
            {
                "order": index,
                "key": key,
                "linked_section_key": section_key,
                "status": "ready" if linked.get("status") == "ready" else "blocked",
                "environment_key_names": env_keys,
                "backend_only_secret_key_names": [key_name for key_name in env_keys if _looks_secret_env_key(key_name)],
                "secret_values_required_in_backend_only": True,
                "raw_secret_value_allowed": False,
                "frontend_gets_secret": False,
                "customer_visible": False,
                "ordinary_merchant_visible": False,
                "secret_exposed": False,
            }
        )
    return rows


def _next_missing_evidence(section_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    missing: list[dict[str, Any]] = []
    for row in section_rows:
        for check in row.get("blocked_checks", []) or []:
            missing.append(
                {
                    "section_key": row.get("section_key") or "",
                    "check": check,
                    "category": row.get("category") or "",
                    "proof_source_type": row.get("proof_source_type") or "",
                    "external_resource_required": row.get("external_resource_required") is True,
                    "operator_action": row.get("next_action") or "",
                    "customer_visible": False,
                    "secret_exposed": False,
                }
            )
    return missing[:24]


def _looks_secret_env_key(name: str) -> bool:
    upper = str(name or "").upper()
    return any(marker in upper for marker in ("SECRET", "TOKEN", "KEY", "DATABASE_URL", "QUEUE_URL", "VAULT_ADDR"))
