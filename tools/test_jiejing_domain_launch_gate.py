#!/usr/bin/env python3
"""Regression for stable domain/TLS launch gate."""

from __future__ import annotations

import os
import sys
import json
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.config import SaaSSettings  # noqa: E402
from jiejing_saas.domain_readiness import build_domain_readiness  # noqa: E402
from jiejing_saas.repository import SaaSRepository  # noqa: E402
from jiejing_saas.commercial_launch_gate import (  # noqa: E402
    _build_paid_launch_cutover_decision,
    build_commercial_launch_gate,
    build_current_store_ebay_evidence,
)


OUT = ROOT / "output" / "jiejing-domain-launch-gate-test"


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    with patch("jiejing_saas.commercial_launch_gate._build_billing_domain_cutover_runbook", return_value=[]):
        owner_ready_decision = _build_paid_launch_cutover_decision(
            cutover_checklist=[],
            billing={},
            domain={},
            paid_launch_ready=True,
        )
    if owner_ready_decision.get("status") != "ready_for_owner_approval":
        return fail("complete cutover evidence should reach owner approval state")
    if owner_ready_decision.get("public_paid_launch_allowed") is not False:
        return fail("ready_for_owner_approval must never directly enable public paid launch")
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
        smoke_by_key = {
            item.get("key"): item
            for item in action_plan.get("new_ebay_account_smoke_runbook", [])
            if isinstance(item, dict)
        }
        oauth_step = smoke_by_key.get("new_account_oauth_authorization_gate") or {}
        if oauth_step.get("status") != "blocked":
            return fail("OAuth completion env flags must not satisfy the commercial gate without current-store backend proof")
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
        oauth_verification = smoke_runbook["new_account_oauth_authorization_gate"].get("verification") or []
        if "/connections?store_id={store_id}" not in oauth_verification:
            return fail("new-account OAuth gate must verify current-store connections before any fallback plan")
        if "/stores/{store_id}/ebay-oauth/read-only-status" not in oauth_verification:
            return fail("new-account OAuth gate must verify backend-derived identity/provenance status")
        if "/stores/{store_id}/ebay-oauth/read-only-plan" not in oauth_verification:
            return fail("new-account OAuth gate must reference the implemented read-only-plan API")
        if "/stores/{store_id}/ebay-oauth/start" in oauth_verification:
            return fail("new-account OAuth gate must not reference the nonexistent ebay-oauth/start API")
        official_verification = smoke_runbook["official_packet_account_health_snapshot"].get("verification") or []
        for required in (
            "/stores/{store_id}/account-health",
            "/connections?store_id={store_id}",
            "/stores/{store_id}/ebay-oauth/read-only-status",
            "/data-packets?store_id={store_id}&platform=ebay&limit=1",
            "/queue-jobs?status=completed&limit=200",
            "/audit-logs?limit=200",
        ):
            if required not in official_verification:
                return fail(f"official evidence phase must include authenticated provenance endpoint: {required}")
        if smoke_runbook["controlled_real_publish_probe"].get("confirmation_center_required") is not True:
            return fail("controlled real publish probe must require confirmation center")
        if smoke_runbook["controlled_real_publish_probe"].get("real_platform_write_step") is not True:
            return fail("controlled real publish probe should be marked as the real-write step")
        if smoke_runbook["post_publish_cockpit_cleanup_gate"].get("confirmation_center_required") is not True:
            return fail("post-publish cleanup gate must require confirmation center")
        if smoke_runbook["post_publish_cockpit_cleanup_gate"].get("real_platform_write_step") is not True:
            return fail("post-publish cleanup gate should be marked as a real-write step")
        misleading_new_account_flags = {
            "JIEJING_NEW_EBAY_ACCOUNT_LOW_RISK_SMOKE_PASSED": "1",
            "JIEJING_NEW_EBAY_PUBLISH_HEALTH_CONFIRMATION_READY": "1",
            "JIEJING_NEW_EBAY_PUBLISH_CONFIRMATION_APPROVED": "1",
            "JIEJING_NEW_EBAY_ACCOUNT_REAL_PUBLISH_PASSED": "1",
            "JIEJING_NEW_EBAY_CLEANUP_CONFIRMATION_APPROVED": "1",
            "JIEJING_NEW_EBAY_TEST_CLEANUP_CONFIRMED": "1",
        }
        previous_misleading_flags = {key: os.environ.get(key) for key in misleading_new_account_flags}
        os.environ.update(misleading_new_account_flags)
        try:
            no_current_store_evidence_gate = build_commercial_launch_gate(settings, repo)
        finally:
            _restore_env(previous_misleading_flags)
        unbound_smoke = {
            item.get("key"): item
            for item in no_current_store_evidence_gate.get("new_ebay_account_smoke_runbook", [])
            if isinstance(item, dict)
        }
        for key in (
            "publish_health_confirmation_gate",
            "controlled_real_publish_probe",
            "post_publish_cockpit_cleanup_gate",
        ):
            if (unbound_smoke.get(key) or {}).get("status") != "blocked":
                return fail(f"global/env new-account evidence must not satisfy current-store step: {key}")
        global_only_readiness = {
            "beta_ready": True,
            "production_ready": True,
            "can_accept_real_customers": True,
            "blocker_count": 0,
            "warning_count": 0,
            "counts": {"confirmations": 9, "execution_results": 9, "stores": 1, "platform_connections": 1},
            "items": [],
            "product_evidence": {
                "latest_ebay_packet_id": "global-history-packet",
                "latest_ebay_packet_source_mode": "official_api",
                "latest_ebay_packet_present_resource_keys": [
                    "store_profile",
                    "account_business_policies",
                    "inventory_and_offers",
                    "orders_and_fulfillment",
                    "finances",
                    "taxonomy_listing_metadata",
                ],
            },
        }
        with patch("jiejing_saas.commercial_launch_gate.build_product_readiness", return_value=global_only_readiness):
            global_only_gate = build_commercial_launch_gate(settings, repo)
        global_only_groups = {
            item.get("key"): item
            for item in global_only_gate.get("groups", [])
            if isinstance(item, dict)
        }
        for key in ("publish_safety_system", "post_publish_cockpit", "new_ebay_account_low_risk_smoke"):
            if (global_only_groups.get(key) or {}).get("status") != "blocked":
                return fail(f"top-level commercial group must reject global/env action evidence without current store: {key}")
        attention_evidence = _attention_account_health_evidence()
        if attention_evidence.get("account_health_ready") is not False:
            return fail("current-store account health must require strict normal status; attention must remain blocked")
        malformed_sentinel = "commercial-malformed-count-must-not-leak"
        malformed_readiness = {
            "beta_ready": True,
            "production_ready": False,
            "can_accept_real_customers": False,
            "blocker_count": {"nested": malformed_sentinel},
            "warning_count": float("nan"),
            "counts": {
                "confirmations": True,
                "execution_results": float("inf"),
                "users": [malformed_sentinel],
                "stores": malformed_sentinel,
                "tasks": {"nested": malformed_sentinel},
            },
            "items": [],
            "product_evidence": {"ebay_token_refresh_success_count": float("inf")},
        }
        try:
            with patch("jiejing_saas.commercial_launch_gate.build_product_readiness", return_value=malformed_readiness):
                malformed_gate = build_commercial_launch_gate(settings, repo)
            malformed_serialized = json.dumps(malformed_gate, ensure_ascii=False, allow_nan=False)
        except (TypeError, ValueError, OverflowError) as exc:
            return fail(f"commercial gate malformed counts/readiness must return stable fail-closed JSON: {type(exc).__name__}")
        malformed_smoke = {
            item.get("key"): item
            for item in malformed_gate.get("new_ebay_account_smoke_runbook", [])
            if isinstance(item, dict)
        }
        if (malformed_smoke.get("public_preflight_ready") or {}).get("status") != "blocked":
            return fail("malformed commercial readiness counts must fail closed")
        if malformed_sentinel in malformed_serialized:
            return fail("malformed commercial count values must not be reflected in public gate JSON")
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
        if "JIEJING_STRIPE_WEBHOOK_FAILURE_PATH_EVIDENCE_ID" not in runbook["stripe_live_webhook_resilience"].get("environment_keys", []):
            return fail("webhook resilience runbook must require a failure-path evidence id")
        if "JIEJING_STRIPE_CUSTOMER_PORTAL_FAILURE_PATH_EVIDENCE_ID" not in runbook["stripe_customer_portal_failure_paths"].get("environment_keys", []):
            return fail("Customer Portal failure-path runbook must require an evidence id")
        if "JIEJING_CUTOVER_ROLLBACK_AUDIT_PACKET_ID" not in runbook["cutover_rollback_audit_packet"].get("environment_keys", []):
            return fail("rollback runbook must require an audit packet id")
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
    finally:
        _restore_env(previous)
    print("PASS jiejing_domain_launch_gate")
    return 0


def _attention_account_health_evidence() -> dict[str, object]:
    company_id = "company-attention"
    store_id = "store-attention"
    connection_id = "connection-attention"
    packet_id = "packet-attention"
    job_id = "job-attention"
    now = datetime.now(timezone.utc).isoformat()
    connection_hash = hashlib.sha256(connection_id.encode("utf-8")).hexdigest()

    class RepositoryFixture:
        def current_ebay_read_only_oauth_boundary(self, **_kwargs: object) -> dict[str, object]:
            return {
                "authorized": True,
                "current_store_selected": True,
                "strong_identity_ready": True,
                "backend_provenance_ready": True,
                "store_id_sha256": hashlib.sha256(store_id.encode("utf-8")).hexdigest(),
                "connection_id_sha256": connection_hash,
            }

        def get_store_for_company(self, **_kwargs: object) -> dict[str, object]:
            return {"store_id": store_id, "company_id": company_id, "platform": "ebay"}

        def list_platform_data_packets(self, **_kwargs: object) -> list[dict[str, object]]:
            resources = ["store_profile", "account_business_policies", "inventory_and_offers", "orders_and_fulfillment", "finances", "taxonomy_listing_metadata"]
            return [{"packet_id": packet_id, "company_id": company_id, "store_id": store_id, "platform": "ebay", "source_mode": "official_api", "created_at": now, "packet": {"company_id": company_id, "store_id": store_id, "platform": "ebay", "source_mode": "official_api", "source_label": "official_api", "created_at": now, "present_resource_keys": resources, "missing_resource_keys": [], "freshness": {"official_request_count": 5, "route_success_count": 5, "route_failure_count": 0}, "lineage": {"probe_live_read_performed": True, "access_token_returned_to_frontend": False, "raw_ebay_response_stored": False}, "safe_for_real_platform_write": False, "secret_exposed": False}}]

        def list_queue_jobs(self, **_kwargs: object) -> list[dict[str, object]]:
            return [{"job_id": job_id, "company_id": company_id, "status": "completed", "job": {"kind": "ebay_read_only_live_plan", "store_id": store_id, "live_read_plan": {"token_boundary": {"connection_id": connection_id}}, "updates": [{"data_packet_id": packet_id, "live_read_performed": True, "request_count": 5, "created_at": now}]}}]

        def find_latest_audit_log_by_target(self, **kwargs: object) -> dict[str, object]:
            if kwargs.get("action_type") != "ebay.read_only.live.completed":
                return {}
            return {"company_id": company_id, "store_id": store_id, "actor_type": "system", "target_id": job_id, "created_at": now, "details": {"data_packet_id": packet_id, "request_count": 5, "raw_response_stored": False, "secret_exposed": False}}

        def list_confirmations(self, **_kwargs: object) -> list[dict[str, object]]:
            return []

        def list_execution_results(self, **_kwargs: object) -> list[dict[str, object]]:
            return []

        def list_audit_logs(self, **_kwargs: object) -> list[dict[str, object]]:
            return []

    snapshot = {"company_id": company_id, "store_id": store_id, "status": "attention", "incident_mode": False, "can_execute_real_writes": True, "evidence_package": {"packet_id": packet_id, "official_packet_present": True}}
    with patch("jiejing_saas.commercial_launch_gate.build_account_health_snapshot", return_value=snapshot):
        return build_current_store_ebay_evidence(repository=RepositoryFixture(), company_id=company_id, store_id=store_id)


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
            "JIEJING_CLS_ENABLED": "1",
            "JIEJING_CLS_REGION": "ap-guangzhou",
            "JIEJING_CLS_LOGSET_ID": "logset-jiejing",
            "JIEJING_CLS_TOPIC_ID": "topic-saas-backend",
            "JIEJING_CLS_ALERT_POLICY_CONFIGURED": "1",
            "JIEJING_NEW_EBAY_ACCOUNT_CONFIRMED_CLEAN": "0",
            "JIEJING_NEW_EBAY_OAUTH_OPERATOR_APPROVED": "1",
            "JIEJING_NEW_EBAY_ACCOUNT_OAUTH_COMPLETED": "1",
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
            "JIEJING_CLOUD_BILLING_INCIDENT_RUNBOOK_PUBLISHED": "1",
            "JIEJING_DATABASE_ENDPOINT_INCIDENT_RUNBOOK_PUBLISHED": "1",
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
        "JIEJING_CLS_ENABLED",
        "JIEJING_CLS_REGION",
        "JIEJING_CLS_LOGSET_ID",
        "JIEJING_CLS_TOPIC_ID",
        "JIEJING_CLS_ALERT_POLICY_CONFIGURED",
        "JIEJING_NEW_EBAY_ACCOUNT_CONFIRMED_CLEAN",
        "JIEJING_NEW_EBAY_OAUTH_OPERATOR_APPROVED",
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
        "JIEJING_CLOUD_BILLING_INCIDENT_RUNBOOK_PUBLISHED",
        "JIEJING_DATABASE_ENDPOINT_INCIDENT_RUNBOOK_PUBLISHED",
        "JIEJING_TEST_DATA_GOVERNANCE_REVIEWED",
        "JIEJING_STRIPE_WEBHOOK_FAILURE_PATH_EVIDENCE_ID",
        "JIEJING_STRIPE_CUSTOMER_PORTAL_FAILURE_PATH_EVIDENCE_ID",
        "JIEJING_CUTOVER_ROLLBACK_AUDIT_PACKET_ID",
    ]


def _restore_env(previous: dict[str, str | None]) -> None:
    for key, value in previous.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


if __name__ == "__main__":
    raise SystemExit(main())
