#!/usr/bin/env python3
"""Regression for stable domain/TLS launch gate."""

from __future__ import annotations

import os
import sys
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.config import SaaSSettings  # noqa: E402
from jiejing_saas.domain_readiness import build_domain_readiness  # noqa: E402
from jiejing_saas.repository import SaaSRepository  # noqa: E402
from jiejing_saas.commercial_launch_gate import build_commercial_launch_gate  # noqa: E402


OUT = ROOT / "output" / "jiejing-domain-launch-gate-test"


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    db_path = OUT / "saas.sqlite"
    db_path.unlink(missing_ok=True)
    previous = _set_blocked_env()
    try:
        settings = SaaSSettings.from_env(db_path=db_path, runtime_db_path=OUT / "runtime.sqlite", output_root=OUT, host="127.0.0.1", port=8788)
        blocked = build_domain_readiness(settings)
        if blocked.get("production_domain_ready") is not False:
            return fail("trycloudflare host must not satisfy stable domain gate")
        if "stable_domain_uses_temporary_or_ip_host" not in blocked.get("blockers", []):
            return fail(f"temporary host blocker missing: {blocked.get('blockers')}")
    finally:
        _restore_env(previous)

    previous = _set_ready_env()
    try:
        settings = SaaSSettings.from_env(db_path=db_path, runtime_db_path=OUT / "runtime.sqlite", output_root=OUT, host="127.0.0.1", port=8788)
        repo = SaaSRepository(db_path, database_engine="sqlite")
        repo.initialize()
        ready = build_domain_readiness(settings)
        if ready.get("production_domain_ready") is not True:
            return fail(f"stable domain should be ready when DNS/TLS/callback/CORS are verified: {ready.get('blockers')}")
        gate = build_commercial_launch_gate(settings, repo)
        groups = {item.get("key"): item for item in gate.get("groups", [])}
        if "stable_domain_tls" not in groups:
            return fail("commercial launch gate must include stable_domain_tls group")
        for required_group in {"ebay_token_refresh_vault_adapter", "new_ebay_account_low_risk_smoke", "legal_risk_boundary"}:
            if required_group not in groups:
                return fail(f"commercial launch gate must include {required_group} group")
        action_plan = gate.get("launch_action_plan") if isinstance(gate.get("launch_action_plan"), dict) else {}
        if action_plan.get("contract_version") != "2026-06-18-launch-action-plan":
            return fail("commercial launch gate should expose the structured launch action plan")
        action_items = {
            item.get("key")
            for section in action_plan.get("sections", [])
            if isinstance(section, dict)
            for item in section.get("items", [])
            if isinstance(item, dict)
        }
        for required_item in {
            "billing_quota",
            "stable_domain_tls",
            "ebay_token_refresh_vault_adapter",
            "account_health_incident_mode",
            "new_ebay_account_low_risk_smoke",
            "publish_safety_system",
            "store_sync_visibility",
            "post_publish_cockpit",
            "legal_risk_boundary",
            "final_commercial_smoke",
        }:
            if required_item not in action_items:
                return fail(f"launch action plan missing item: {required_item}")
        drills = {
            item.get("key"): item
            for item in action_plan.get("commercial_hardening_drills", [])
            if isinstance(item, dict)
        }
        if set(drills) != {
            "stripe_billing_live_mode",
            "stable_domain_cutover",
            "ebay_refresh_vault_probe",
            "account_health_incident_mode",
            "new_ebay_account_low_risk_smoke",
            "publish_health_confirmation_drill",
            "final_commercial_smoke",
        }:
            return fail(f"commercial hardening drills missing or unexpected: {sorted(drills)}")
        if gate.get("commercial_hardening_drills") != action_plan.get("commercial_hardening_drills"):
            return fail("commercial launch gate should expose top-level drills for settings UI")
        if drills["stable_domain_cutover"].get("status") != "ready":
            return fail(f"stable domain drill should be ready in stable-domain fixture: {drills['stable_domain_cutover']}")
        if drills["ebay_refresh_vault_probe"].get("evidence", {}).get("successful_refresh_probe_count") != 0:
            return fail("commercial drill must not invent eBay refresh proof")
        if drills["ebay_refresh_vault_probe"].get("evidence", {}).get("repeat_oauth_allowed") is not False:
            return fail("refresh drill must forbid repeating OAuth in this gate")
        if drills["new_ebay_account_low_risk_smoke"].get("evidence", {}).get("old_frozen_account_reuse_allowed") is not False:
            return fail("new-account smoke drill must explicitly forbid old frozen account reuse")
        if drills["publish_health_confirmation_drill"].get("requires_confirmation_center") is not True:
            return fail("publish health drill must keep real writes in the confirmation center")
        summary = action_plan.get("summary") if isinstance(action_plan.get("summary"), dict) else {}
        if summary.get("hardening_drill_total_count") != 7 or not summary.get("next_drill"):
            return fail(f"launch action summary should include drill counts and next drill: {summary}")
        smoke_runbook = {
            item.get("key"): item
            for item in action_plan.get("new_ebay_account_smoke_runbook", [])
            if isinstance(item, dict)
        }
        if set(smoke_runbook) != {
            "public_preflight_ready",
            "clean_new_account_declared",
            "new_account_oauth_authorization_gate",
            "official_packet_account_health_snapshot",
            "new_product_duplicate_guard",
            "publish_health_confirmation_gate",
            "controlled_real_publish_probe",
            "post_publish_cockpit_cleanup_gate",
        }:
            return fail(f"new eBay account smoke runbook missing or unexpected: {sorted(smoke_runbook)}")
        if gate.get("new_ebay_account_smoke_runbook") != action_plan.get("new_ebay_account_smoke_runbook"):
            return fail("commercial launch gate should expose top-level new-account smoke runbook for settings UI")
        if summary.get("new_account_smoke_total_count") != 8 or not summary.get("next_new_account_smoke_step"):
            return fail(f"launch action summary should include new-account smoke counts and next step: {summary}")
        for key, item in smoke_runbook.items():
            if item.get("triggers_real_charge") is not False:
                return fail(f"new-account smoke step must not trigger real charge: {key}")
            if item.get("triggers_real_platform_write") is not False:
                return fail(f"new-account smoke step must not silently trigger platform write: {key}")
            if item.get("old_frozen_account_reuse_allowed") is not False:
                return fail(f"new-account smoke step must forbid old frozen account reuse: {key}")
            if item.get("old_demo_product_or_sku_allowed") is not False:
                return fail(f"new-account smoke step must forbid old demo product/SKU reuse: {key}")
            if item.get("secret_exposed") is not False:
                return fail(f"new-account smoke step must not expose secrets: {key}")
        if smoke_runbook["new_account_oauth_authorization_gate"].get("repeat_oauth_allowed") is not False:
            return fail("new-account OAuth gate must forbid silent/repeated OAuth")
        if smoke_runbook["new_account_oauth_authorization_gate"].get("triggers_ebay_oauth") is not False:
            return fail("new-account OAuth gate must not start OAuth from the launch gate")
        if smoke_runbook["controlled_real_publish_probe"].get("confirmation_center_required") is not True:
            return fail("controlled real publish probe must require confirmation center")
        if smoke_runbook["controlled_real_publish_probe"].get("real_platform_write_step") is not True:
            return fail("controlled real publish probe should be marked as the real-write step")
        if smoke_runbook["post_publish_cockpit_cleanup_gate"].get("confirmation_center_required") is not True:
            return fail("post-publish cleanup gate must require confirmation center")
        if smoke_runbook["post_publish_cockpit_cleanup_gate"].get("real_platform_write_step") is not True:
            return fail("post-publish cleanup gate should be marked as a real-write step")
        deferred_strategy = action_plan.get("prelaunch_deferred_strategy") if isinstance(action_plan.get("prelaunch_deferred_strategy"), dict) else {}
        if gate.get("prelaunch_deferred_strategy") != deferred_strategy:
            return fail("commercial launch gate should expose top-level prelaunch deferred strategy for settings UI")
        if deferred_strategy.get("contract_version") != "2026-06-20-prelaunch-deferred-strategy-v1":
            return fail(f"prelaunch deferred strategy contract missing: {deferred_strategy}")
        if deferred_strategy.get("formal_payment_deferred") is not True:
            return fail("formal payment must stay explicitly deferred when owner postpones live payment cutover")
        if deferred_strategy.get("clean_ebay_account_validation_deferred") is not True:
            return fail("clean eBay account validation must stay explicitly deferred")
        if deferred_strategy.get("can_continue_without_payment") is not True:
            return fail("internal prelaunch hardening should continue without live payment")
        if deferred_strategy.get("can_continue_without_new_ebay_account") is not True:
            return fail("internal prelaunch hardening should continue without a clean eBay account")
        strategy_safety = deferred_strategy.get("safety_contract") if isinstance(deferred_strategy.get("safety_contract"), dict) else {}
        for key in ("triggers_real_charge", "triggers_ebay_oauth", "triggers_real_platform_write", "frontend_gets_secret", "secret_exposed"):
            if strategy_safety.get(key) is not False:
                return fail(f"prelaunch deferred strategy safety flag must be false: {key}")
        external_deferred = {
            item.get("key"): item
            for item in deferred_strategy.get("external_deferred_items", [])
            if isinstance(item, dict)
        }
        if set(external_deferred) != {"formal_payment_deferred", "clean_ebay_account_validation_deferred"}:
            return fail(f"prelaunch external deferred items missing or unexpected: {sorted(external_deferred)}")
        for key, item in external_deferred.items():
            if item.get("status") != "deferred" or item.get("external_dependency_deferred") is not True:
                return fail(f"external item should be deferred: {key}")
            if item.get("can_continue_internal_prelaunch_work") is not True:
                return fail(f"external deferred item should not block internal work: {key}")
            for flag in ("triggers_real_charge", "triggers_ebay_oauth", "triggers_real_platform_write", "secret_exposed"):
                if item.get(flag) is not False:
                    return fail(f"external deferred item must keep safety flag false: {key}.{flag}")
        internal_work = {
            item.get("key"): item
            for item in deferred_strategy.get("autonomous_internal_work", [])
            if isinstance(item, dict)
        }
        if set(internal_work) != {
            "legal_risk_boundary_docs",
            "monitoring_incident_runbooks",
            "backup_restore_drill_evidence",
            "no_charge_billing_rehearsal",
            "public_security_evidence_capture",
            "test_data_governance_review",
            "confirmation_center_copy_and_rollback",
            "browser_smoke_and_readiness_snapshot",
        }:
            return fail(f"autonomous internal work missing or unexpected: {sorted(internal_work)}")
        for key, item in internal_work.items():
            if item.get("can_continue_without_payment") is not True:
                return fail(f"internal work should continue without payment: {key}")
            if item.get("can_continue_without_new_ebay_account") is not True:
                return fail(f"internal work should continue without clean eBay account: {key}")
            if item.get("external_dependency_deferred") is not False:
                return fail(f"internal work must not be marked as external dependency: {key}")
            for flag in ("triggers_real_charge", "triggers_ebay_oauth", "triggers_real_platform_write", "secret_exposed"):
                if item.get(flag) is not False:
                    return fail(f"internal work must keep safety flag false: {key}.{flag}")
        for key in {"monitoring_incident_runbooks", "public_security_evidence_capture", "test_data_governance_review"}:
            if internal_work[key].get("status") != "ready":
                return fail(f"autonomous internal hardening should be ready without live payment or clean eBay: {key}={internal_work[key]}")
        strategy_summary = deferred_strategy.get("summary") if isinstance(deferred_strategy.get("summary"), dict) else {}
        if strategy_summary.get("external_deferred_count") != 2:
            return fail(f"prelaunch deferred summary should count two external deferred items: {strategy_summary}")
        if strategy_summary.get("autonomous_internal_total_count") != 8:
            return fail(f"prelaunch deferred summary should count autonomous internal work: {strategy_summary}")
        if strategy_summary.get("public_paid_launch_allowed") is not False:
            return fail("prelaunch deferred summary must not allow public paid launch")
        if summary.get("deferred_external_count") != 2 or summary.get("autonomous_internal_total_count") != 8:
            return fail(f"launch action summary should include deferred/internal counts: {summary}")
        cutover = {
            item.get("key"): item
            for item in action_plan.get("paid_launch_cutover_checklist", [])
            if isinstance(item, dict)
        }
        if set(cutover) != {
            "billing_provider_live_contract",
            "stripe_api_webhook_version_alignment",
            "stable_domain_dns_tls_callback",
            "backup_monitoring_restore_drill",
            "legal_risk_boundary_docs",
            "ebay_refresh_probe_after_new_account",
            "final_paid_launch_smoke_evidence",
        }:
            return fail(f"paid launch cutover checklist missing or unexpected: {sorted(cutover)}")
        if gate.get("paid_launch_cutover_checklist") != action_plan.get("paid_launch_cutover_checklist"):
            return fail("commercial launch gate should expose top-level cutover checklist for settings UI")
        decision = action_plan.get("paid_launch_cutover_decision") if isinstance(action_plan.get("paid_launch_cutover_decision"), dict) else {}
        if gate.get("paid_launch_cutover_decision") != decision:
            return fail("commercial launch gate should expose top-level cutover decision for settings UI")
        if decision.get("contract_version") != "2026-06-18-paid-launch-cutover-decision":
            return fail(f"paid launch cutover decision contract missing: {decision}")
        if decision.get("status") != "blocked" or decision.get("public_paid_launch_allowed") is not False:
            return fail(f"paid launch decision must stay blocked until every gate is green: {decision}")
        if decision.get("charge_now_allowed") is not False or decision.get("platform_write_now_allowed") is not False:
            return fail("cutover decision must not allow charges or platform writes")
        if decision.get("repeat_ebay_oauth_allowed") is not False:
            return fail("cutover decision must forbid repeating eBay OAuth")
        runbook = {
            item.get("key"): item
            for item in decision.get("billing_domain_cutover_runbook", [])
            if isinstance(item, dict)
        }
        if set(runbook) != {
            "stripe_account_live_mode_contract",
            "stripe_api_webhook_version_contract",
            "stripe_live_webhook_resilience",
            "stripe_customer_portal_failure_paths",
            "stable_domain_dns_tls_headers",
            "stable_domain_oauth_cors_alignment",
            "cutover_rollback_audit_packet",
        }:
            return fail(f"billing/domain cutover runbook missing or unexpected: {sorted(runbook)}")
        if decision.get("runbook_total_count") != 7 or not (decision.get("next_runbook_step") or {}).get("key"):
            return fail(f"cutover decision should expose runbook counts and next step: {decision}")
        for key, item in runbook.items():
            if item.get("triggers_real_charge") is not False:
                return fail(f"runbook item must not trigger real charge: {key}")
            if item.get("triggers_real_platform_write") is not False:
                return fail(f"runbook item must not trigger platform writes: {key}")
            if item.get("secret_exposed") is not False:
                return fail(f"runbook item must not expose secrets: {key}")
        if runbook["stable_domain_oauth_cors_alignment"].get("repeat_oauth_allowed") is not False:
            return fail("domain/OAuth runbook item must forbid repeating eBay OAuth")
        if runbook["stable_domain_oauth_cors_alignment"].get("triggers_ebay_oauth") is not False:
            return fail("domain/OAuth runbook item must not trigger eBay OAuth")
        lane_categories = {item.get("category") for item in decision.get("lanes", []) if isinstance(item, dict)}
        if lane_categories != {"billing", "domain", "reliability", "legal", "ebay", "release"}:
            return fail(f"cutover decision lanes missing: {lane_categories}")
        if not (decision.get("next_operator_step") or {}).get("key"):
            return fail("cutover decision should expose the next blocked operator step")
        if summary.get("cutover_decision_status") != decision.get("status"):
            return fail("launch action summary should include cutover decision status")
        if summary.get("runbook_total_count") != 7 or not summary.get("next_runbook_step"):
            return fail(f"launch action summary should include runbook counts and next step: {summary}")
        if cutover["stable_domain_dns_tls_callback"].get("status") != "ready":
            return fail("stable domain cutover checklist item should be ready in stable-domain fixture")
        if cutover["billing_provider_live_contract"].get("triggers_real_charge") is not False:
            return fail("billing cutover checklist must not trigger a real charge")
        if cutover["ebay_refresh_probe_after_new_account"].get("repeat_oauth_allowed") is not False:
            return fail("eBay refresh cutover item must forbid OAuth repeat")
        if cutover["ebay_refresh_probe_after_new_account"].get("triggers_real_platform_write") is not False:
            return fail("eBay refresh cutover item must not trigger platform writes")
        if summary.get("cutover_total_count") != 7 or not summary.get("next_cutover_item"):
            return fail(f"launch action summary should include cutover counts and next item: {summary}")
        serialized = json.dumps(action_plan, ensure_ascii=False).lower()
        for forbidden in ("access_token", "refresh_token=", "client_secret=", "api_key=", "password="):
            if forbidden in serialized:
                return fail(f"launch action plan leaked secret-shaped marker: {forbidden}")
        print("PASS jiejing_domain_launch_gate")
        return 0
    finally:
        _restore_env(previous)


def _set_blocked_env() -> dict[str, str | None]:
    keys = _keys()
    previous = {key: os.environ.get(key) for key in keys}
    os.environ.update(
        {
            "JIEJING_SAAS_ENV": "staging",
            "JIEJING_PUBLIC_BASE_URL": "https://example.trycloudflare.com",
            "JIEJING_CORS_ORIGIN": "https://example.trycloudflare.com",
        }
    )
    return previous


def _set_ready_env() -> dict[str, str | None]:
    keys = _keys()
    previous = {key: os.environ.get(key) for key in keys}
    os.environ.update(
        {
            "JIEJING_SAAS_ENV": "staging",
            "JIEJING_PUBLIC_BASE_URL": "https://app.jiejing.example",
            "JIEJING_STABLE_DOMAIN": "app.jiejing.example",
            "JIEJING_CORS_ORIGIN": "https://app.jiejing.example",
            "JIEJING_DOMAIN_DNS_VERIFIED": "1",
            "JIEJING_TLS_VERIFIED": "1",
            "JIEJING_EBAY_CALLBACK_VERIFIED": "1",
            "JIEJING_DEPLOYMENT_HARDENED": "1",
            "JIEJING_SECURITY_HEADERS_VERIFIED": "1",
            "JIEJING_NEW_EBAY_ACCOUNT_CONFIRMED_CLEAN": "0",
            "JIEJING_NEW_EBAY_ACCOUNT_OAUTH_COMPLETED": "0",
            "JIEJING_NEW_EBAY_PRODUCT_DUPLICATE_GUARD_PASSED": "0",
            "JIEJING_NEW_EBAY_ACCOUNT_REAL_PUBLISH_PASSED": "0",
            "JIEJING_NEW_EBAY_TEST_CLEANUP_CONFIRMED": "0",
            "JIEJING_PRIVACY_POLICY_VERIFIED": "1",
            "JIEJING_TERMS_VERIFIED": "1",
            "JIEJING_RISK_DISCLOSURE_VERIFIED": "1",
            "JIEJING_CONFIRMATION_TERMS_VISIBLE": "1",
            "JIEJING_INCIDENT_RUNBOOK_PUBLISHED": "1",
            "JIEJING_ONCALL_ALERT_ROUTE_CONFIGURED": "1",
            "JIEJING_BACKUP_RESTORE_DRILL_RUNBOOK_PUBLISHED": "1",
            "JIEJING_POST_PUBLISH_RECOVERY_RUNBOOK_PUBLISHED": "1",
            "JIEJING_BILLING_INCIDENT_RUNBOOK_PUBLISHED": "1",
            "JIEJING_TEST_DATA_GOVERNANCE_REVIEWED": "1",
        }
    )
    return previous


def _keys() -> list[str]:
    return [
        "JIEJING_SAAS_ENV",
        "JIEJING_PUBLIC_BASE_URL",
        "JIEJING_STABLE_DOMAIN",
        "JIEJING_SELECTED_DOMAIN",
        "JIEJING_ROOT_DOMAIN",
        "JIEJING_PENDING_DOMAIN",
        "JIEJING_DOMAIN_REGISTRATION_STATUS",
        "JIEJING_DOMAIN_PURCHASE_STATUS",
        "JIEJING_DOMAIN_REGISTERED",
        "JIEJING_DOMAIN_PURCHASED",
        "JIEJING_TARGET_APP_HOST",
        "JIEJING_APP_HOST",
        "JIEJING_CORS_ORIGIN",
        "JIEJING_DOMAIN_DNS_VERIFIED",
        "JIEJING_TLS_VERIFIED",
        "JIEJING_EBAY_CALLBACK_VERIFIED",
        "JIEJING_DEPLOYMENT_HARDENED",
        "JIEJING_SECURITY_HEADERS_VERIFIED",
        "JIEJING_NEW_EBAY_ACCOUNT_CONFIRMED_CLEAN",
        "JIEJING_NEW_EBAY_ACCOUNT_OAUTH_COMPLETED",
        "JIEJING_NEW_EBAY_PRODUCT_DUPLICATE_GUARD_PASSED",
        "JIEJING_NEW_EBAY_ACCOUNT_REAL_PUBLISH_PASSED",
        "JIEJING_NEW_EBAY_TEST_CLEANUP_CONFIRMED",
        "JIEJING_PRIVACY_POLICY_VERIFIED",
        "JIEJING_TERMS_VERIFIED",
        "JIEJING_RISK_DISCLOSURE_VERIFIED",
        "JIEJING_CONFIRMATION_TERMS_VISIBLE",
        "JIEJING_INCIDENT_RUNBOOK_PUBLISHED",
        "JIEJING_ONCALL_ALERT_ROUTE_CONFIGURED",
        "JIEJING_BACKUP_RESTORE_DRILL_RUNBOOK_PUBLISHED",
        "JIEJING_POST_PUBLISH_RECOVERY_RUNBOOK_PUBLISHED",
        "JIEJING_BILLING_INCIDENT_RUNBOOK_PUBLISHED",
        "JIEJING_TEST_DATA_GOVERNANCE_REVIEWED",
    ]


def _restore_env(previous: dict[str, str | None]) -> None:
    for key, value in previous.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


if __name__ == "__main__":
    raise SystemExit(main())
