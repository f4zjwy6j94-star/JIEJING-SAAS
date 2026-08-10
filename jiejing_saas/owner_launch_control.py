"""Platform-internal launch-control evidence for Jiejing.

This module builds one sanitized internal packet for the launch settings tab.
It is deliberately read-only: no OAuth, no Checkout session, no platform write.
"""

from __future__ import annotations

import os
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .backup_plan import build_backup_plan
from .billing_domain_cutover_rehearsal import build_billing_domain_cutover_rehearsal
from .billing_plan import build_billing_plan, build_billing_usage
from .commercial_launch_gate import build_commercial_launch_gate
from .config import SaaSSettings
from .edge_cutover_preflight import build_edge_cutover_preflight
from .feasibility_review import build_feasibility_review
from .launch_progress import build_fixed_launch_progress
from .monitoring import build_monitoring_status
from .operational_health import build_operational_health
from .paid_launch_approval_packet import build_paid_launch_approval_packet
from .post_publish_cockpit import build_post_publish_cockpit
from .queue_adapter import build_queue_adapter_contract
from .readiness import build_product_readiness_or_degraded
from .repository import SaaSRepository


OWNER_LAUNCH_CONTROL_VERSION = "2026-08-10-owner-launch-control-v9"
FIXED_PROGRESS_RELEASE_EVIDENCE_CONTRACT = "2026-07-14-version-bound-release-evidence-v1"


def build_owner_launch_control(
    settings: SaaSSettings,
    repository: SaaSRepository,
    *,
    company_id: str,
    store_id: str | None = None,
) -> dict[str, Any]:
    """Return a sanitized internal launch control packet for platform admins."""

    stores = _safe_call("stores", lambda: repository.list_stores(company_id=company_id), [])
    selected_store_id = _selected_store_id(stores=stores, requested_store_id=store_id)
    readiness = _safe_call("readiness", lambda: build_product_readiness_or_degraded(settings, repository), {})
    evidence = readiness.get("product_evidence") if isinstance(readiness.get("product_evidence"), dict) else {}
    operational = _safe_call(
        "operational_health",
        lambda: build_operational_health(settings, repository, company_id=company_id),
        {},
    )
    launch_gate = _safe_call("commercial_launch_gate", lambda: build_commercial_launch_gate(settings, repository), {})
    billing = _safe_call("billing_plan", lambda: build_billing_plan(settings, repository), {})
    billing_usage = _safe_call("billing_usage", lambda: build_billing_usage(settings, repository, company_id=company_id), {})
    backup = _safe_call("backup_plan", lambda: build_backup_plan(settings, repository), {})
    monitoring = _safe_call("monitoring", lambda: build_monitoring_status(settings, repository), {})
    legacy_billing_cutover = _safe_call(
        "billing_domain_cutover_rehearsal",
        lambda: build_billing_domain_cutover_rehearsal(settings, repository),
        {},
    )
    edge = _safe_call("edge_cutover_preflight", lambda: build_edge_cutover_preflight(settings), {})
    paid_packet = _safe_call("paid_launch_approval_packet", lambda: build_paid_launch_approval_packet(settings, repository), {})
    edge = _owner_mainland_edge_view(edge=edge, paid_packet=paid_packet)
    billing = _owner_mainland_billing_view(billing=billing, paid_packet=paid_packet)
    billing_cutover = _owner_mainland_cutover_view(
        paid_packet=paid_packet,
        legacy_billing_cutover=legacy_billing_cutover,
    )
    queue_adapter = _safe_call("queue_adapter", lambda: build_queue_adapter_contract(settings), {})
    test_data_governance = _safe_call(
        "test_data_governance",
        lambda: repository.test_data_governance_snapshot(company_id=company_id),
        {},
    )
    merchant_workflow_validation = _safe_call(
        "merchant_workflow_validation",
        repository.merchant_workflow_validation_snapshot,
        {},
    )
    owner_pilot_workflow_validation = _safe_call(
        "owner_pilot_workflow_validation",
        lambda: repository.owner_pilot_workflow_validation_snapshot(company_id=company_id),
        {},
    )
    fixed_progress_release_evidence = _load_fixed_progress_release_evidence()
    fixed_progress_release_evidence["real_merchant_workflow_validation_passed"] = bool(
        merchant_workflow_validation.get("passed")
    )
    fixed_launch_progress = _safe_call(
        "fixed_launch_progress",
        lambda: build_fixed_launch_progress(
            readiness=readiness,
            launch_gate=launch_gate,
            billing=billing,
            operational=operational,
            test_data_governance=test_data_governance,
            release_evidence=fixed_progress_release_evidence,
        ),
        {},
    )
    data_packets = _safe_call(
        "platform_data_packets",
        lambda: repository.list_platform_data_packets(
            company_id=company_id,
            store_id=selected_store_id,
            platform="ebay",
            limit=5,
        ),
        [],
    )
    post_publish = _safe_call(
        "post_publish_cockpit",
        lambda: build_post_publish_cockpit(
            execution_results=repository.list_execution_results(company_id=company_id, limit=10),
            confirmations=repository.list_confirmations(company_id=company_id, limit=20),
            audit_logs=repository.list_audit_logs(company_id=company_id, limit=50),
        ),
        {},
    )
    latest_packet = data_packets[0] if data_packets else {}
    summary = _summary(
        settings=settings,
        readiness=readiness,
        evidence=evidence,
        operational=operational,
        launch_gate=launch_gate,
        billing=billing,
        backup=backup,
        billing_cutover=billing_cutover,
        edge=edge,
        paid_packet=paid_packet,
        queue_adapter=queue_adapter,
        post_publish=post_publish,
        latest_packet=latest_packet,
        store_count=len(stores),
        test_data_governance=test_data_governance,
    )
    operations_observability = _operations_observability(
        operational=operational,
        backup=backup,
        billing_usage=billing_usage,
        post_publish=post_publish,
        test_data_governance=test_data_governance,
    )
    resilience_war_room = _resilience_war_room(
        backup=backup,
        monitoring=monitoring,
        operational=operational,
        billing_usage=billing_usage,
        post_publish=post_publish,
        test_data_governance=test_data_governance,
    )
    subscription_shutdown_control = _subscription_shutdown_control(
        billing=billing,
        billing_usage=billing_usage,
    )
    feasibility_review = _safe_call(
        "feasibility_review",
        lambda: build_feasibility_review(
            readiness=readiness,
            launch_gate=launch_gate,
            billing=billing,
            billing_cutover=billing_cutover,
            backup=backup,
            operational=operational,
            edge=edge,
            monitoring=monitoring,
            evidence=evidence,
            post_publish=post_publish,
            test_data_governance=test_data_governance,
        ),
        {},
    )
    lanes = _lanes(
        readiness=readiness,
        evidence=evidence,
        operational=operational,
        launch_gate=launch_gate,
        billing=billing,
        backup=backup,
        billing_cutover=billing_cutover,
        edge=edge,
        paid_packet=paid_packet,
        queue_adapter=queue_adapter,
        operations_observability=operations_observability,
        test_data_governance=test_data_governance,
    )
    external_blockers = _external_blockers(
        billing=billing,
        billing_cutover=billing_cutover,
        edge=edge,
        paid_packet=paid_packet,
        launch_gate=launch_gate,
    )
    internal_work_queue = _internal_work_queue(
        operational=operational,
        edge=edge,
        paid_packet=paid_packet,
        billing_usage=billing_usage,
        operations_observability=operations_observability,
        test_data_governance=test_data_governance,
    )
    blocked_lanes = [lane for lane in lanes if lane.get("status") != "ready"]
    blocked_external = [item for item in external_blockers if item.get("status") != "ready"]
    public_paid_launch_allowed = bool(launch_gate.get("paid_commercial_launch_ready")) and bool(readiness.get("production_ready"))
    evidence_summary = _evidence_summary(
        readiness=readiness,
        evidence=evidence,
        operational=operational,
        billing=billing,
        backup=backup,
        billing_cutover=billing_cutover,
        edge=edge,
        paid_packet=paid_packet,
        post_publish=post_publish,
        latest_packet=latest_packet,
        selected_store_id=selected_store_id,
    )
    war_room = _war_room(
        summary=summary,
        lanes=lanes,
        external_blockers=external_blockers,
        internal_work_queue=internal_work_queue,
        operations_observability=operations_observability,
        test_data_governance=test_data_governance,
    )
    owner_review_packet = _owner_review_packet(
        summary=summary,
        lanes=lanes,
        external_blockers=external_blockers,
        internal_work_queue=internal_work_queue,
        war_room=war_room,
        operations_observability=operations_observability,
        resilience_war_room=resilience_war_room,
        subscription_shutdown_control=subscription_shutdown_control,
        test_data_governance=test_data_governance,
        evidence_summary=evidence_summary,
    )
    launch_rehearsal_audit_packet = _launch_rehearsal_audit_packet(
        settings=settings,
        summary=summary,
        lanes=lanes,
        external_blockers=external_blockers,
        internal_work_queue=internal_work_queue,
        billing_cutover=billing_cutover,
        edge=edge,
        paid_packet=paid_packet,
        owner_review_packet=owner_review_packet,
        operations_observability=operations_observability,
        resilience_war_room=resilience_war_room,
        subscription_shutdown_control=subscription_shutdown_control,
        evidence_summary=evidence_summary,
    )
    release_history = _release_history(
        settings=settings,
        summary=summary,
        evidence_summary=evidence_summary,
        owner_review_packet=owner_review_packet,
        launch_rehearsal_audit_packet=launch_rehearsal_audit_packet,
    )
    continuity_handoff_digest = _continuity_handoff_digest(
        settings=settings,
        summary=summary,
        evidence_summary=evidence_summary,
        lanes=lanes,
        external_blockers=external_blockers,
        internal_work_queue=internal_work_queue,
        release_history=release_history,
    )
    cutover_decision_checklist = _cutover_decision_checklist(
        settings=settings,
        summary=summary,
        lanes=lanes,
        external_blockers=external_blockers,
        internal_work_queue=internal_work_queue,
        owner_review_packet=owner_review_packet,
        launch_rehearsal_audit_packet=launch_rehearsal_audit_packet,
        continuity_handoff_digest=continuity_handoff_digest,
    )
    final_launch_rehearsal_execution_record = _final_launch_rehearsal_execution_record(
        settings=settings,
        summary=summary,
        evidence_summary=evidence_summary,
        owner_review_packet=owner_review_packet,
        launch_rehearsal_audit_packet=launch_rehearsal_audit_packet,
        release_history=release_history,
        continuity_handoff_digest=continuity_handoff_digest,
        cutover_decision_checklist=cutover_decision_checklist,
        external_blockers=external_blockers,
        internal_work_queue=internal_work_queue,
    )
    owner_paid_launch_approval_dossier = _owner_paid_launch_approval_dossier(
        settings=settings,
        summary=summary,
        evidence_summary=evidence_summary,
        billing_cutover=billing_cutover,
        paid_packet=paid_packet,
        launch_rehearsal_audit_packet=launch_rehearsal_audit_packet,
        final_launch_rehearsal_execution_record=final_launch_rehearsal_execution_record,
        external_blockers=external_blockers,
        internal_work_queue=internal_work_queue,
    )
    prelaunch_acceptance_report = _prelaunch_acceptance_report(
        settings=settings,
        summary=summary,
        evidence_summary=evidence_summary,
        owner_review_packet=owner_review_packet,
        launch_rehearsal_audit_packet=launch_rehearsal_audit_packet,
        release_history=release_history,
        continuity_handoff_digest=continuity_handoff_digest,
        cutover_decision_checklist=cutover_decision_checklist,
        final_launch_rehearsal_execution_record=final_launch_rehearsal_execution_record,
        owner_paid_launch_approval_dossier=owner_paid_launch_approval_dossier,
        external_blockers=external_blockers,
        internal_work_queue=internal_work_queue,
    )
    return {
        "contract_version": OWNER_LAUNCH_CONTROL_VERSION,
        "mode": "platform_internal_admin_read_only",
        "audience": "platform_internal_admin",
        "customer_visible": False,
        "environment": settings.environment,
        "status": _overall_status(
            public_paid_launch_allowed=public_paid_launch_allowed,
            beta_ready=bool(readiness.get("beta_ready")),
            blocked_lanes=blocked_lanes,
            blocked_external=blocked_external,
        ),
        "generated_at": datetime.now(timezone.utc).isoformat(),
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
        "frontend_gets_ebay_token": False,
        "secret_exposed": False,
        "summary": summary,
        "owner_review_packet": owner_review_packet,
        "launch_rehearsal_audit_packet": launch_rehearsal_audit_packet,
        "release_history": release_history,
        "continuity_handoff_digest": continuity_handoff_digest,
        "cutover_decision_checklist": cutover_decision_checklist,
        "final_launch_rehearsal_execution_record": final_launch_rehearsal_execution_record,
        "owner_paid_launch_approval_dossier": owner_paid_launch_approval_dossier,
        "prelaunch_acceptance_report": prelaunch_acceptance_report,
        "war_room": war_room,
        "feasibility_review": feasibility_review,
        "test_data_governance": test_data_governance,
        "merchant_workflow_validation": merchant_workflow_validation,
        "owner_pilot_workflow_validation": owner_pilot_workflow_validation,
        "operations_observability": operations_observability,
        "resilience_war_room": resilience_war_room,
        "subscription_shutdown_control": subscription_shutdown_control,
        "fixed_launch_progress": fixed_launch_progress,
        "lanes": lanes,
        "external_blockers": external_blockers,
        "internal_work_queue": internal_work_queue,
        "evidence": evidence_summary,
        "safety": {
            "owner_admin_only": True,
            "platform_internal_admin_only": True,
            "not_customer_visible": True,
            "frontend_gets_secret": False,
            "frontend_gets_raw_ebay_token": False,
            "frontend_gets_payment_secret": False,
            "runtime_gets_raw_ebay_token": False,
            "charge_now_allowed": False,
            "platform_write_now_allowed": False,
            "repeat_ebay_oauth_allowed": False,
            "old_frozen_ebay_account_reuse_allowed": False,
            "old_demo_product_or_sku_allowed": False,
            "confirmation_center_required_for_real_risk_actions": True,
            "secret_exposed": False,
        },
    }


def _owner_mainland_billing_view(*, billing: dict[str, Any], paid_packet: dict[str, Any]) -> dict[str, Any]:
    """Project the canonical mainland approval packet into legacy owner helpers.

    This is an internal compatibility view only.  It prevents the v7 helper
    graph from using the future-international Stripe lane as mainland truth.
    """

    summary = paid_packet.get("summary") if isinstance(paid_packet.get("summary"), dict) else {}
    ready = summary.get("mainland_payment_ready_for_owner_approval") is True
    provider = billing.get("provider") if isinstance(billing.get("provider"), dict) else {}
    view = dict(billing)
    view["provider"] = {
        **provider,
        "selected": "wechat_pay_native",
        "provider": "wechat_pay_native",
        "checkout_mode": "native_qr",
        "billing_mode": "one_time_30_day_plan",
        "calls_stripe_api": False,
        "triggers_real_charge": False,
        "secret_exposed": False,
    }
    view["mainland_payment_ready_for_owner_approval"] = ready
    view["billing_ready_for_paid_launch"] = ready
    view["future_international_payment"] = (
        dict(paid_packet.get("future_international_payment"))
        if isinstance(paid_packet.get("future_international_payment"), dict)
        else {
            "provider": "stripe",
            "role": "future_international_payment_only",
            "blocks_mainland_launch": False,
            "calls_stripe_api": False,
            "triggers_real_charge": False,
            "secret_exposed": False,
        }
    )
    view["public_charging_allowed"] = False
    view["charge_now_allowed"] = False
    view["calls_stripe_api"] = False
    view["triggers_real_charge"] = False
    view["secret_exposed"] = False
    return view


def _owner_mainland_edge_view(*, edge: dict[str, Any], paid_packet: dict[str, Any]) -> dict[str, Any]:
    summary = edge.get("summary") if isinstance(edge.get("summary"), dict) else {}
    callbacks = edge.get("callback_cutover") if isinstance(edge.get("callback_cutover"), dict) else {}
    paid_steps = _by_key(paid_packet.get("steps"))
    payment_ready = (paid_steps.get("wechat_pay_native_cutover") or {}).get("status") == "ready"
    callbacks_ready = callbacks.get("ebay_callback_verified") is True and payment_ready
    waf_ready = summary.get("waf_ready") is True
    origin_locked = summary.get("origin_locked") is True
    view = dict(edge)
    view["summary"] = {
        **summary,
        "callbacks_ready": callbacks_ready,
        "ready_count": sum(1 for ready in (waf_ready, origin_locked, callbacks_ready) if ready),
        "total_count": 3,
        "next_step": (
            ""
            if waf_ready and origin_locked and callbacks_ready
            else "complete_stable_domain_waf_origin_ebay_wechat_callbacks"
        ),
        "next_action": (
            "Stable domain, WAF, origin lock, eBay callback and WeChat signed callback proof are required."
        ),
    }
    view["status"] = "ready_for_owner_approval" if waf_ready and origin_locked and callbacks_ready else "blocked"
    view["required_callback_urls"] = {
        "ebay_oauth_callback": (
            edge.get("required_callback_urls", {}).get("ebay_oauth_callback")
            if isinstance(edge.get("required_callback_urls"), dict)
            else ""
        ),
        "wechat_pay_notify": "backend_configured_https_url",
        "wechat_pay_refund_notify": "backend_configured_https_url",
        "secret_exposed": False,
    }
    view["calls_stripe_api"] = False
    view["creates_checkout_session"] = False
    view["triggers_real_charge"] = False
    view["secret_exposed"] = False
    return view


def _owner_mainland_cutover_view(
    *,
    paid_packet: dict[str, Any],
    legacy_billing_cutover: dict[str, Any],
) -> dict[str, Any]:
    steps = _by_key(paid_packet.get("steps"))
    external = _by_key(paid_packet.get("external_configuration_needed"))
    payment = steps.get("wechat_pay_native_cutover") or {}
    no_charge = steps.get("no_charge_launch_rehearsal") or {}
    payment_ready = payment.get("status") == "ready"
    no_charge_ready = no_charge.get("status") == "ready"
    payment_blocked = [
        str(item)
        for item in payment.get("blocked_by") or []
        if isinstance(item, str) and item
    ]
    no_charge_blocked = [
        str(item)
        for item in no_charge.get("blocked_by") or []
        if isinstance(item, str) and item
    ]
    no_charge_external = external.get("no_charge_rehearsal_evidence_flags") or {}
    no_charge_evidence = {
        "key": "no_charge_rehearsal_evidence_flags",
        "status": "ready" if no_charge_ready else "blocked",
        "environment_keys": [
            str(item)
            for item in no_charge_external.get("environment_keys") or []
            if isinstance(item, str) and item
        ],
        "secret_value_returned": False,
        "frontend_gets_secret": False,
        "secret_exposed": False,
    }
    return {
        "contract_version": "2026-07-27-mainland-payment-owner-cutover-view-v1",
        "provider": "wechat_pay_native",
        "status": "ready_for_owner_approval" if payment_ready else "blocked",
        "summary": {
            "ready_count": 1 if payment_ready else 0,
            "total_count": 1,
            "blocked_count": 0 if payment_ready else 1,
            "blocked_keys": payment_blocked,
            "next_step": "" if payment_ready else "wechat_pay_native_cutover",
            "next_action": payment.get("next_action") or "Complete the WeChat Native production prerequisites.",
            "provider": "wechat_pay_native",
        },
        "no_charge_live_domain_evidence_packet": {
            "contract_version": "2026-07-27-no-charge-mainland-payment-evidence-v1",
            "status": "ready" if no_charge_ready else "blocked",
            "summary": {
                "ready_count": 1 if no_charge_ready else 0,
                "total_count": 1,
                "blocked_count": 0 if no_charge_ready else 1,
                "blocked_keys": no_charge_blocked,
            },
            "evidence_items": [no_charge_evidence],
            "public_paid_launch_allowed": False,
            "charge_now_allowed": False,
            "calls_external_payment_api": False,
            "triggers_real_charge": False,
            "secret_exposed": False,
        },
        "deprecated_stripe_rehearsal_status": (
            legacy_billing_cutover.get("status") if isinstance(legacy_billing_cutover, dict) else "unknown"
        ),
        "public_paid_launch_allowed": False,
        "charge_now_allowed": False,
        "calls_stripe_api": False,
        "triggers_real_charge": False,
        "secret_exposed": False,
    }


def _summary(
    *,
    settings: SaaSSettings,
    readiness: dict[str, Any],
    evidence: dict[str, Any],
    operational: dict[str, Any],
    launch_gate: dict[str, Any],
    billing: dict[str, Any],
    backup: dict[str, Any],
    billing_cutover: dict[str, Any],
    edge: dict[str, Any],
    paid_packet: dict[str, Any],
    queue_adapter: dict[str, Any],
    post_publish: dict[str, Any],
        latest_packet: dict[str, Any],
        store_count: int,
        test_data_governance: dict[str, Any],
) -> dict[str, Any]:
    worker = operational.get("worker_runtime") if isinstance(operational.get("worker_runtime"), dict) else {}
    provider = billing.get("provider") if isinstance(billing.get("provider"), dict) else {}
    shutdown_closure = (
        billing.get("subscription_quota_shutdown_closure")
        if isinstance(billing.get("subscription_quota_shutdown_closure"), dict)
        else {}
    )
    edge_summary = edge.get("summary") if isinstance(edge.get("summary"), dict) else {}
    paid_summary = paid_packet.get("summary") if isinstance(paid_packet.get("summary"), dict) else {}
    return {
        "beta_ready": bool(readiness.get("beta_ready")),
        "production_ready": bool(readiness.get("production_ready")),
        "can_accept_real_customers": bool(readiness.get("can_accept_real_customers")),
        "warning_count": _as_int(readiness.get("warning_count")),
        "blocker_count": _as_int(readiness.get("blocker_count")),
        "latest_official_ebay_packet_id": evidence.get("latest_ebay_packet_id") or latest_packet.get("packet_id") or "",
        "latest_official_ebay_packet_status": evidence.get("latest_ebay_packet_status") or latest_packet.get("status") or "",
        "ebay_token_refresh_success_count": _as_int(evidence.get("ebay_token_refresh_success_count")),
        "model_value_ready": _provider_ready(readiness, "model_value"),
        "billing_provider": provider.get("selected") or "not_selected",
        "mainland_payment_provider": "wechat_pay_native",
        "mainland_payment_ready_for_owner_approval": (
            billing.get("mainland_payment_ready_for_owner_approval") is True
        ),
        "billing_ready_for_paid_launch": billing.get("mainland_payment_ready_for_owner_approval") is True,
        "subscription_shutdown_ready": bool(
            shutdown_closure.get("ready_for_no_charge_rehearsal") or shutdown_closure.get("ready_for_live_cutover")
        ),
        "subscription_shutdown_ready_count": _as_int(shutdown_closure.get("ready_count")),
        "subscription_shutdown_total_count": _as_int(shutdown_closure.get("total_count")),
        "subscription_shutdown_next_step": shutdown_closure.get("next_step") or "",
        "backup_ready_for_paid_launch": bool(backup.get("backup_ready_for_paid_launch")),
        "billing_cutover_status": billing_cutover.get("status") or "unknown",
        "stable_domain_ready": bool(edge_summary.get("callbacks_ready")) and bool(edge_summary.get("waf_ready")),
        "edge_ready_count": _as_int(edge_summary.get("ready_count")),
        "edge_total_count": _as_int(edge_summary.get("total_count")),
        "paid_packet_next_step": paid_summary.get("next_step") or "",
        "post_publish_status": post_publish.get("status") or "unknown",
        "queue_provider": queue_adapter.get("selected") or worker.get("queue_provider") or settings.queue_provider,
        "worker_heartbeat_status": worker.get("heartbeat_status") or "unknown",
        "store_count": store_count,
        "test_data_candidate_count": _as_int(test_data_governance.get("candidate_count")),
        "test_data_governance_status": test_data_governance.get("status") or "unknown",
        "real_platform_writes_enabled": bool(settings.effective_real_platform_writes_enabled),
        "public_paid_launch_allowed": bool(launch_gate.get("paid_commercial_launch_ready")) and bool(readiness.get("production_ready")),
        "secret_exposed": False,
    }


def _lanes(
    *,
    readiness: dict[str, Any],
    evidence: dict[str, Any],
    operational: dict[str, Any],
    launch_gate: dict[str, Any],
    billing: dict[str, Any],
    backup: dict[str, Any],
    billing_cutover: dict[str, Any],
    edge: dict[str, Any],
        paid_packet: dict[str, Any],
        queue_adapter: dict[str, Any],
        operations_observability: dict[str, Any],
        test_data_governance: dict[str, Any],
) -> list[dict[str, Any]]:
    groups = _by_key(launch_gate.get("groups"))
    launch_summary = launch_gate.get("readiness") if isinstance(launch_gate.get("readiness"), dict) else {}
    edge_summary = edge.get("summary") if isinstance(edge.get("summary"), dict) else {}
    paid_summary = paid_packet.get("summary") if isinstance(paid_packet.get("summary"), dict) else {}
    operational_status = str(operational.get("status") or "unknown")
    billing_provider = billing.get("provider") if isinstance(billing.get("provider"), dict) else {}
    shutdown_closure = (
        billing.get("subscription_quota_shutdown_closure")
        if isinstance(billing.get("subscription_quota_shutdown_closure"), dict)
        else {}
    )
    return [
        _lane(
            "launch_gate",
            "Public paid launch gate",
            "ready" if bool(launch_gate.get("paid_commercial_launch_ready")) else "blocked",
            f"production_ready={bool(launch_summary.get('production_ready') or readiness.get('production_ready'))}; beta_ready={bool(launch_summary.get('beta_ready') or readiness.get('beta_ready'))}",
            (launch_gate.get("next_actions") or ["Keep private beta hardening until all launch blockers are gone."])[0],
        ),
        _lane(
            "ebay_account",
            "eBay account and refresh proof",
            "ready" if _as_int(evidence.get("ebay_token_refresh_success_count")) > 0 and _group_ready(groups, "new_ebay_account_low_risk_smoke") else "blocked",
            f"latest_packet={evidence.get('latest_ebay_packet_id') or 'missing'}; refresh_success={_as_int(evidence.get('ebay_token_refresh_success_count'))}; old_account_allowed=false",
            "Use only a clean new eBay account, then run the low-risk smoke runbook. Do not repeat OAuth on the frozen account.",
        ),
        _lane(
            "billing",
            "Billing and quota cutover",
            "ready"
            if billing.get("mainland_payment_ready_for_owner_approval") is True
            and billing_cutover.get("status") == "ready_for_owner_approval"
            else "blocked",
            f"provider={billing_provider.get('selected') or 'not_selected'}; cutover={billing_cutover.get('status') or 'unknown'}",
            _summary_next_action(billing_cutover)
            or "Complete WeChat Native backend credentials, signed callbacks, query, refund and controlled-acceptance proof.",
        ),
        _lane(
            "subscription_shutdown",
            "Subscription shutdown closure",
            "ready"
            if bool(shutdown_closure.get("ready_for_no_charge_rehearsal") or shutdown_closure.get("ready_for_live_cutover"))
            else "blocked",
            f"ready={_as_int(shutdown_closure.get('ready_count'))}/{_as_int(shutdown_closure.get('total_count'))}; next={shutdown_closure.get('next_step') or 'none'}",
            ((shutdown_closure.get("operator_summary") or {}).get("next_action"))
            if isinstance(shutdown_closure.get("operator_summary"), dict)
            else "Run failed-payment, cancellation and quota hard-stop rehearsal before live provider cutover.",
        ),
        _lane(
            "domain_security",
            "Stable domain, WAF and callbacks",
            "ready" if edge.get("status") == "ready_for_owner_approval" else "blocked",
            f"ready={edge_summary.get('ready_count', 0)}/{edge_summary.get('total_count', 0)}; next={edge_summary.get('next_step') or 'none'}",
            edge_summary.get("next_action") or "Verify app.jiejing.shop HTTPS, WAF/Bot controls, origin lock and callback URLs.",
        ),
        _lane(
            "runtime_queue",
            "Database, queue and worker",
            "ready" if operational_status == "ready" and _queue_adapter_ready(queue_adapter) else "attention_required",
            f"health={operational_status}; queue_provider={queue_adapter.get('selected') or 'unknown'}",
            _operational_next_action(operational),
        ),
        _lane(
            "publish_safety",
            "Publish preflight and confirmation center",
            "ready" if _group_ready(groups, "publish_safety_system") else "blocked",
            _group_evidence(groups, "publish_safety_system"),
            "Keep every real publish, price, inventory, refund, ad and policy change behind the confirmation center.",
        ),
        _lane(
            "ops_observability",
            "Internal ops observability",
            "ready" if operations_observability.get("status") == "ready" else "attention_required",
            f"cards={_as_int((operations_observability.get('summary') or {}).get('card_count'))}; attention={_as_int((operations_observability.get('summary') or {}).get('attention_count'))}",
            "Use the internal ops evidence panel before each deploy and after each smoke run.",
        ),
        _lane(
            "backup_restore",
            "Backup and restore evidence",
            "ready" if bool(backup.get("backup_ready_for_paid_launch")) else "attention_required",
            f"blockers={len(backup.get('blockers') or [])}; restore_recorded={bool((backup.get('restore') or {}).get('restore_drill_recorded'))}",
            (backup.get("next_actions") or ["Keep restore drill evidence and backup alerts current."])[0],
        ),
        _lane(
            "no_charge_rehearsal",
            "No-real-charge final rehearsal",
            "ready" if bool(paid_packet.get("ready_for_owner_approval")) and paid_summary.get("blocked_count") == 0 else "blocked",
            f"approval_packet={paid_packet.get('status') or 'unknown'}; next={paid_summary.get('next_step') or 'none'}",
            paid_summary.get("next_step")
            or "Run the no-charge rehearsal only after WeChat Native, domain and clean eBay prerequisites are ready.",
        ),
        _lane(
            "test_data_governance",
            "Staging test data governance",
            "ready" if test_data_governance.get("status") == "no_test_data_detected" else "attention_required",
            f"scope={test_data_governance.get('scope') or 'unknown'}; candidates={_as_int(test_data_governance.get('candidate_count'))}; auto_delete=false",
            test_data_governance.get("next_action") or "Keep smoke data marked and isolated; do not delete automatically.",
        ),
    ]


def _external_blockers(
    *,
    billing: dict[str, Any],
    billing_cutover: dict[str, Any],
    edge: dict[str, Any],
    paid_packet: dict[str, Any],
    launch_gate: dict[str, Any],
) -> list[dict[str, Any]]:
    groups = _by_key(launch_gate.get("groups"))
    edge_summary = edge.get("summary") if isinstance(edge.get("summary"), dict) else {}
    paid_summary = paid_packet.get("summary") if isinstance(paid_packet.get("summary"), dict) else {}
    return [
        _external_item(
            "stable_domain_waf_callbacks",
            "Stable domain, WAF/Bot controls, origin lock, eBay and WeChat callback URLs",
            edge.get("status") == "ready_for_owner_approval",
            "Finish DNS/TLS/WAF/origin/callback verification for Cloudflare, Tencent, WeChat Pay and eBay.",
            evidence=f"edge_ready={edge_summary.get('ready_count', 0)}/{edge_summary.get('total_count', 0)}; next={edge_summary.get('next_step') or 'none'}",
        ),
        _external_item(
            "wechat_pay_native_production_cutover",
            "WeChat Pay Native credentials, signed callbacks, query, refund and controlled acceptance",
            billing.get("mainland_payment_ready_for_owner_approval") is True
            and billing_cutover.get("status") == "ready_for_owner_approval",
            _summary_next_action(billing_cutover)
            or "Finish backend-only WeChat Pay production prerequisites and stable callback URLs.",
            evidence=f"billing_cutover={billing_cutover.get('status') or 'unknown'}",
        ),
        _external_item(
            "clean_new_ebay_account",
            "Clean new eBay account",
            _group_ready(groups, "new_ebay_account_low_risk_smoke"),
            "Create and verify a clean new eBay seller account before any new OAuth or live smoke.",
            evidence=_group_evidence(groups, "new_ebay_account_low_risk_smoke"),
            triggers_ebay_oauth=False,
        ),
        _external_item(
            "fresh_real_test_product_assets",
            "Fresh real test product素材",
            _env_bool("JIEJING_FRESH_REAL_TEST_PRODUCT_ASSETS_READY"),
            "Prepare a new real low-risk test product with new photos, SKU, title, description, policy and supplier facts.",
            evidence=f"fresh_assets_ready={_env_bool('JIEJING_FRESH_REAL_TEST_PRODUCT_ASSETS_READY')}",
        ),
        _external_item(
            "no_charge_rehearsal_evidence",
            "Final no-real-charge rehearsal evidence",
            bool(paid_packet.get("ready_for_owner_approval")) and paid_summary.get("blocked_count") == 0,
            "After external prerequisites are ready, run the final no-real-charge rehearsal and record rollback proof.",
            evidence=f"approval_status={paid_packet.get('status') or 'unknown'}; next={paid_summary.get('next_step') or 'none'}",
        ),
    ]


def _internal_work_queue(
    *,
    operational: dict[str, Any],
    edge: dict[str, Any],
        paid_packet: dict[str, Any],
        billing_usage: dict[str, Any],
        operations_observability: dict[str, Any],
        test_data_governance: dict[str, Any],
) -> list[dict[str, Any]]:
    edge_summary = edge.get("summary") if isinstance(edge.get("summary"), dict) else {}
    paid_summary = paid_packet.get("summary") if isinstance(paid_packet.get("summary"), dict) else {}
    return [
        _work_item(
            "owner_launch_control",
            "Owner launch-control packet and UI",
            "ready",
            "This packet is backend-backed, platform-internal-admin-only, and read-only.",
            "python tools/test_jiejing_owner_launch_control.py",
        ),
        _work_item(
            "secret_scan",
            "Secret scan before bundle/deploy",
            "ready" if _env_bool("JIEJING_SECRET_SCAN_PASSED") else "pending",
            "Run secret scan after each production-adjacent change; never commit raw keys.",
            "python tools/jiejing_secret_scan.py",
        ),
        _work_item(
            "browser_smoke",
            "Browser smoke on app.jiejing.shop",
            "ready" if _env_bool("JIEJING_BROWSER_SMOKE_PASSED") else "pending",
            "Verify /health, login, Launch settings and owner panel after deployment.",
            "node tools/codex_jiejing_paid_cutover_decision_smoke.js",
        ),
        _work_item(
            "free_waf_bot_evidence",
            "Free WAF/Bot evidence capture",
            "ready" if edge_summary.get("waf_ready") else "pending",
            "Record free Cloudflare/Tencent evidence without enabling paid daily WAF products.",
            "/owner/edge-cutover-preflight",
        ),
        _work_item(
            "ops_observability",
            "Internal ops observability v1",
            "ready" if operations_observability.get("status") == "ready" else "attention_required",
            (operations_observability.get("summary") or {}).get("next_action") or "Review ops evidence cards before deploy.",
            "/owner/launch-control operations_observability",
        ),
        _work_item(
            "quota_state_visibility",
            "Subscription/quota lifecycle visibility",
            "ready" if _billing_entitlement_visible(billing_usage) else "pending",
            "Keep subscription state, failed payment and cancellation quota hard-stop visible in Settings.",
            "/billing/usage",
        ),
        _work_item(
            "test_data_governance",
            "Staging smoke data governance",
            "ready" if test_data_governance.get("status") == "no_test_data_detected" else "attention_required",
            test_data_governance.get("next_action") or "Review current-company smoke data markers; deletion remains disabled by default.",
            "/owner/launch-control test_data_governance",
        ),
        _work_item(
            "no_charge_rehearsal",
            "No-real-charge launch rehearsal",
            "ready" if paid_summary.get("blocked_count") == 0 else "blocked",
            "Run only after external domain, WeChat Native and clean eBay prerequisites are ready.",
            "python tools/test_jiejing_paid_launch_approval_packet.py",
        ),
        _work_item(
            "ops_health_followup",
            "Queue/worker health follow-up",
            "ready" if operational.get("status") == "ready" else "attention_required",
            _operational_next_action(operational),
            "/health/deep",
        ),
    ]


def _evidence_summary(
    *,
    readiness: dict[str, Any],
    evidence: dict[str, Any],
    operational: dict[str, Any],
    billing: dict[str, Any],
    backup: dict[str, Any],
    billing_cutover: dict[str, Any],
    edge: dict[str, Any],
    paid_packet: dict[str, Any],
    post_publish: dict[str, Any],
    latest_packet: dict[str, Any],
    selected_store_id: str,
) -> dict[str, Any]:
    billing_provider = billing.get("provider") if isinstance(billing.get("provider"), dict) else {}
    shutdown_closure = (
        billing.get("subscription_quota_shutdown_closure")
        if isinstance(billing.get("subscription_quota_shutdown_closure"), dict)
        else {}
    )
    edge_summary = edge.get("summary") if isinstance(edge.get("summary"), dict) else {}
    paid_summary = paid_packet.get("summary") if isinstance(paid_packet.get("summary"), dict) else {}
    return {
        "selected_store_id": selected_store_id,
        "readiness": {
            "status": readiness.get("status") or "",
            "beta_ready": bool(readiness.get("beta_ready")),
            "production_ready": bool(readiness.get("production_ready")),
            "can_accept_real_customers": bool(readiness.get("can_accept_real_customers")),
            "blocker_count": _as_int(readiness.get("blocker_count")),
            "warning_count": _as_int(readiness.get("warning_count")),
        },
        "ebay": {
            "latest_packet_id": evidence.get("latest_ebay_packet_id") or latest_packet.get("packet_id") or "",
            "latest_packet_status": evidence.get("latest_ebay_packet_status") or latest_packet.get("status") or "",
            "latest_packet_source_mode": evidence.get("latest_ebay_packet_source_mode") or latest_packet.get("source_mode") or "",
            "refresh_success_count": _as_int(evidence.get("ebay_token_refresh_success_count")),
            "frontend_gets_raw_token": False,
        },
        "billing": {
            "provider": billing_provider.get("selected") or "not_selected",
            "paid_launch_ready": billing.get("mainland_payment_ready_for_owner_approval") is True,
            "mainland_payment_ready_for_owner_approval": (
                billing.get("mainland_payment_ready_for_owner_approval") is True
            ),
            "private_beta_ready": bool(billing.get("billing_ready_for_private_beta")),
            "cutover_status": billing_cutover.get("status") or "unknown",
            "next_action": _summary_next_action(billing_cutover),
            "subscription_shutdown_ready": bool(
                shutdown_closure.get("ready_for_no_charge_rehearsal") or shutdown_closure.get("ready_for_live_cutover")
            ),
            "subscription_shutdown_next_step": shutdown_closure.get("next_step") or "",
            "charge_now_allowed": False,
        },
        "backup": {
            "status": "ready" if bool(backup.get("backup_ready_for_paid_launch")) else "attention_required",
            "ready_for_paid_launch": bool(backup.get("backup_ready_for_paid_launch")),
            "blockers": _safe_string_list(backup.get("blockers")),
            "next_action": (backup.get("next_actions") or [""])[0] if isinstance(backup.get("next_actions"), list) else "",
        },
        "post_publish": {
            "status": post_publish.get("status") or "unknown",
            "ready_for_ui": bool(post_publish.get("ready_for_ui")),
            "published": bool(post_publish.get("published")),
            "triggers_real_charge": bool(((post_publish.get("safety") or {}).get("triggers_real_charge"))),
            "triggers_ebay_oauth": bool(((post_publish.get("safety") or {}).get("triggers_ebay_oauth"))),
            "triggers_real_platform_write": bool(((post_publish.get("safety") or {}).get("triggers_real_platform_write"))),
        },
        "edge": {
            "status": edge.get("status") or "unknown",
            "ready_count": _as_int(edge_summary.get("ready_count")),
            "total_count": _as_int(edge_summary.get("total_count")),
            "next_step": edge_summary.get("next_step") or "",
            "waf_ready": bool(edge_summary.get("waf_ready")),
            "origin_locked": bool(edge_summary.get("origin_locked")),
            "callbacks_ready": bool(edge_summary.get("callbacks_ready")),
        },
        "operational": {
            "status": operational.get("status") or "unknown",
            "blockers": _safe_string_list(operational.get("blockers")),
            "warnings": _safe_string_list(operational.get("warnings")),
        },
        "paid_launch_packet": {
            "status": paid_packet.get("status") or "unknown",
            "next_step": paid_summary.get("next_step") or "",
            "blocked_count": _as_int(paid_summary.get("blocked_count")),
        },
        "secret_exposed": False,
    }


def _owner_review_packet(
    *,
    summary: dict[str, Any],
    lanes: list[dict[str, Any]],
    external_blockers: list[dict[str, Any]],
    internal_work_queue: list[dict[str, Any]],
    war_room: dict[str, Any],
    operations_observability: dict[str, Any],
    resilience_war_room: dict[str, Any],
    subscription_shutdown_control: dict[str, Any],
    test_data_governance: dict[str, Any],
    evidence_summary: dict[str, Any],
) -> dict[str, Any]:
    blocked_lanes = [item for item in lanes if item.get("status") != "ready"]
    blocked_external = [item for item in external_blockers if item.get("status") != "ready"]
    review_items = [
        _review_item(
            "paid_launch_gate",
            "Paid public launch gate",
            "ready" if summary.get("production_ready") and summary.get("can_accept_real_customers") else "blocked",
            f"beta_ready={bool(summary.get('beta_ready'))}; production_ready={bool(summary.get('production_ready'))}; can_accept_real_customers={bool(summary.get('can_accept_real_customers'))}",
            "Keep paid public launch blocked until production readiness and real-customer acceptance are both true.",
            "/readiness/product-saas",
        ),
        _review_item(
            "billing_cutover",
            "Billing provider cutover",
            "ready" if summary.get("mainland_payment_ready_for_owner_approval") is True else "blocked",
            f"provider={summary.get('billing_provider') or 'not_selected'}; cutover={summary.get('billing_cutover_status') or 'unknown'}; charge_now_allowed=false",
            "Finish live provider setup and no-real-charge rehearsal before any real checkout path is enabled.",
            "/billing/plans",
        ),
        _review_item(
            "subscription_shutdown",
            "Subscription and quota shutdown",
            "ready" if summary.get("subscription_shutdown_ready") else "attention_required",
            f"ready={_as_int(summary.get('subscription_shutdown_ready_count'))}/{_as_int(summary.get('subscription_shutdown_total_count'))}; next={summary.get('subscription_shutdown_next_step') or 'none'}",
            "Keep failed-payment, cancellation and quota hard-stop evidence current before live billing cutover.",
            "/billing/usage",
        ),
        _review_item(
            "stable_domain_waf_callbacks",
            "Stable domain, WAF and callback URLs",
            "ready" if summary.get("stable_domain_ready") else "attention_required",
            f"edge={_as_int(summary.get('edge_ready_count'))}/{_as_int(summary.get('edge_total_count'))}; app_domain=app.jiejing.shop",
            "Verify free WAF/Bot controls, origin lock, and eBay/WeChat callback URLs on the stable domain.",
            "/owner/edge-cutover-preflight",
        ),
        _review_item(
            "ebay_account_refresh",
            "eBay account and refresh proof",
            "ready" if _as_int(summary.get("ebay_token_refresh_success_count")) > 0 else "blocked",
            f"latest_packet={summary.get('latest_official_ebay_packet_id') or 'missing'}; refresh_success={_as_int(summary.get('ebay_token_refresh_success_count'))}; old_account_allowed=false",
            "Wait for a clean new eBay account before OAuth or low-risk smoke; do not reuse the frozen account.",
            "/readiness/product-saas product_evidence",
        ),
        _review_item(
            "backup_restore",
            "Backup and restore evidence",
            "ready" if summary.get("backup_ready_for_paid_launch") else "attention_required",
            f"backup_ready={bool(summary.get('backup_ready_for_paid_launch'))}",
            "Keep managed backup, restore drill and alert owner evidence current.",
            "/backup/plan",
        ),
        _review_item(
            "operations_observability",
            "Operations observability",
            "ready" if operations_observability.get("status") == "ready" else "attention_required",
            f"cards={_as_int((operations_observability.get('summary') or {}).get('card_count'))}; attention={_as_int((operations_observability.get('summary') or {}).get('attention_count'))}",
            (operations_observability.get("summary") or {}).get("next_action") or "Review operations evidence before deploy.",
            "/owner/launch-control operations_observability",
        ),
        _review_item(
            "resilience_war_room",
            "Incident and resilience war room",
            "ready" if resilience_war_room.get("status") == "ready" else "attention_required",
            f"cards={_as_int((resilience_war_room.get('summary') or {}).get('card_count'))}; attention={_as_int((resilience_war_room.get('summary') or {}).get('attention_count'))}",
            (resilience_war_room.get("summary") or {}).get("next_action") or "Review backup, incident and queue runbook evidence.",
            "/owner/launch-control resilience_war_room",
        ),
        _review_item(
            "test_data_governance",
            "Test data governance",
            "ready" if test_data_governance.get("status") == "no_test_data_detected" else "attention_required",
            f"scope={test_data_governance.get('scope') or 'unknown'}; candidates={_as_int(test_data_governance.get('candidate_count'))}; auto_delete=false",
            test_data_governance.get("next_action") or "Keep staging smoke data marked and isolated.",
            "/owner/launch-control test_data_governance",
        ),
        _review_item(
            "confirmation_center",
            "Confirmation center boundary",
            "ready",
            "real publish/payment/refund/price/inventory/ads/policy/customer-promise actions must stop for confirmation",
            "Keep every high-risk eBay business action confirmation-gated and audit-backed.",
            "/confirmations",
        ),
    ]
    blocked_reviews = [item for item in review_items if item.get("status") == "blocked"]
    attention_reviews = [item for item in review_items if item.get("status") == "attention_required"]
    status = "ready_for_owner_approval" if not blocked_reviews and not blocked_lanes and not blocked_external else "blocked"
    next_action = (
        blocked_reviews[0]["next_action"]
        if blocked_reviews
        else attention_reviews[0]["next_action"]
        if attention_reviews
        else "Keep this owner review packet attached to the final launch rehearsal."
    )
    return {
        "contract_version": "2026-06-20-owner-review-packet-v1",
        "audience": "platform_internal_admin",
        "mode": "sanitized_read_only_launch_review",
        "customer_visible": False,
        "status": status,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "status": status,
            "review_item_count": len(review_items),
            "ready_count": len([item for item in review_items if item.get("status") == "ready"]),
            "blocked_count": len(blocked_reviews),
            "attention_count": len(attention_reviews),
            "lane_count": len(lanes),
            "blocked_lane_count": len(blocked_lanes),
            "external_blocker_count": len(blocked_external),
            "next_action": next_action,
            "beta_ready": bool(summary.get("beta_ready")),
            "production_ready": bool(summary.get("production_ready")),
            "can_accept_real_customers": bool(summary.get("can_accept_real_customers")),
            "latest_official_ebay_packet_id": summary.get("latest_official_ebay_packet_id") or "",
            "ebay_token_refresh_success_count": _as_int(summary.get("ebay_token_refresh_success_count")),
            "billing_provider": summary.get("billing_provider") or "not_selected",
            "secret_exposed": False,
        },
        "review_items": review_items,
        "external_blockers": external_blockers[:8],
        "internal_work_queue": internal_work_queue[:10],
        "war_room_summary": {
            "contract_version": war_room.get("contract_version") or "",
            "status": war_room.get("status") or "unknown",
            "counts": war_room.get("counts") if isinstance(war_room.get("counts"), dict) else {},
            "public_paid_launch_allowed": False,
            "charge_now_allowed": False,
            "platform_write_now_allowed": False,
            "repeat_ebay_oauth_allowed": False,
            "secret_exposed": False,
        },
        "operations_observability_summary": operations_observability.get("summary")
        if isinstance(operations_observability.get("summary"), dict)
        else {},
        "resilience_war_room_summary": resilience_war_room.get("summary")
        if isinstance(resilience_war_room.get("summary"), dict)
        else {},
        "subscription_shutdown_summary": subscription_shutdown_control.get("summary")
        if isinstance(subscription_shutdown_control.get("summary"), dict)
        else {},
        "test_data_governance_summary": {
            "status": test_data_governance.get("status") or "unknown",
            "scope": test_data_governance.get("scope") or "unknown",
            "candidate_count": _as_int(test_data_governance.get("candidate_count")),
            "delete_now_allowed": bool((test_data_governance.get("cleanup_policy") or {}).get("delete_now_allowed")),
            "automatic_delete_allowed": bool((test_data_governance.get("cleanup_policy") or {}).get("automatic_delete_allowed")),
            "global_tenant_scan_exposed": bool(test_data_governance.get("global_tenant_scan_exposed")),
            "secret_exposed": False,
        },
        "evidence": {
            "selected_store_id": evidence_summary.get("selected_store_id") or "",
            "readiness": evidence_summary.get("readiness") if isinstance(evidence_summary.get("readiness"), dict) else {},
            "ebay": evidence_summary.get("ebay") if isinstance(evidence_summary.get("ebay"), dict) else {},
            "billing": evidence_summary.get("billing") if isinstance(evidence_summary.get("billing"), dict) else {},
            "edge": evidence_summary.get("edge") if isinstance(evidence_summary.get("edge"), dict) else {},
            "operational": evidence_summary.get("operational") if isinstance(evidence_summary.get("operational"), dict) else {},
            "paid_launch_packet": evidence_summary.get("paid_launch_packet")
            if isinstance(evidence_summary.get("paid_launch_packet"), dict)
            else {},
            "secret_exposed": False,
        },
        "safety": _owner_review_safety_flags(),
        "download_allowed_for_internal_admin": True,
        "exports_database": False,
        "exports_raw_secret": False,
        "includes_raw_tokens": False,
        "includes_payment_secret": False,
        "calls_stripe_api": False,
        "creates_checkout_session": False,
        "triggers_real_charge": False,
        "triggers_ebay_oauth": False,
        "triggers_real_platform_write": False,
        "frontend_gets_secret": False,
        "secret_exposed": False,
    }


def _review_item(key: str, label: str, status: str, evidence: str, next_action: str, source_endpoint: str) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "status": status,
        "tone": _tone(status),
        "evidence_summary": str(evidence or "")[:520],
        "next_action": str(next_action or "")[:520],
        "source_endpoint": source_endpoint,
        "owner": "platform_ops",
        "customer_visible": False,
        "exports_database": False,
        "exports_raw_secret": False,
        "includes_raw_tokens": False,
        "includes_payment_secret": False,
        "calls_stripe_api": False,
        "creates_checkout_session": False,
        "triggers_real_charge": False,
        "triggers_ebay_oauth": False,
        "triggers_real_platform_write": False,
        "frontend_gets_secret": False,
        "secret_exposed": False,
    }


def _owner_review_safety_flags() -> dict[str, bool]:
    return {
        "read_only": True,
        "platform_internal_admin_only": True,
        "customer_visible": False,
        "download_allowed_for_internal_admin": True,
        "exports_database": False,
        "exports_raw_secret": False,
        "includes_raw_tokens": False,
        "includes_payment_secret": False,
        "calls_stripe_api": False,
        "creates_checkout_session": False,
        "triggers_real_charge": False,
        "charge_now_allowed": False,
        "triggers_ebay_oauth": False,
        "repeat_ebay_oauth_allowed": False,
        "triggers_real_platform_write": False,
        "platform_write_now_allowed": False,
        "frontend_gets_secret": False,
        "frontend_gets_payment_secret": False,
        "frontend_gets_ebay_token": False,
        "secret_exposed": False,
    }


def _launch_rehearsal_audit_packet(
    *,
    settings: SaaSSettings,
    summary: dict[str, Any],
    lanes: list[dict[str, Any]],
    external_blockers: list[dict[str, Any]],
    internal_work_queue: list[dict[str, Any]],
    billing_cutover: dict[str, Any],
    edge: dict[str, Any],
    paid_packet: dict[str, Any],
    owner_review_packet: dict[str, Any],
    operations_observability: dict[str, Any],
    resilience_war_room: dict[str, Any],
    subscription_shutdown_control: dict[str, Any],
    evidence_summary: dict[str, Any],
) -> dict[str, Any]:
    billing_summary = billing_cutover.get("summary") if isinstance(billing_cutover.get("summary"), dict) else {}
    no_charge_packet = (
        billing_cutover.get("no_charge_live_domain_evidence_packet")
        if isinstance(billing_cutover.get("no_charge_live_domain_evidence_packet"), dict)
        else {}
    )
    edge_summary = edge.get("summary") if isinstance(edge.get("summary"), dict) else {}
    paid_summary = paid_packet.get("summary") if isinstance(paid_packet.get("summary"), dict) else {}
    owner_review_summary = owner_review_packet.get("summary") if isinstance(owner_review_packet.get("summary"), dict) else {}
    ops_summary = operations_observability.get("summary") if isinstance(operations_observability.get("summary"), dict) else {}
    resilience_summary = resilience_war_room.get("summary") if isinstance(resilience_war_room.get("summary"), dict) else {}
    shutdown_summary = subscription_shutdown_control.get("summary") if isinstance(subscription_shutdown_control.get("summary"), dict) else {}
    checks = [
        _audit_check(
            "predeploy_health_readiness_snapshot",
            "Pre-deploy health and readiness snapshot",
            "ready" if _env_bool("JIEJING_READINESS_SNAPSHOT_RECORDED") else "blocked",
            f"health=required; readiness beta={bool(summary.get('beta_ready'))}; production={bool(summary.get('production_ready'))}; warnings={_as_int(summary.get('warning_count'))}",
            "Record /health, /health/deep and /readiness/product-saas JSON before owner approval.",
            "/health /health/deep /readiness/product-saas",
        ),
        _audit_check(
            "secret_scan_evidence",
            "Secret scan evidence",
            "ready" if _env_bool("JIEJING_SECRET_SCAN_PASSED") else "blocked",
            f"secret_scan_passed={_env_bool('JIEJING_SECRET_SCAN_PASSED')}; secret_exposed=false",
            "Run python tools/jiejing_secret_scan.py after each production-adjacent change.",
            "tools/jiejing_secret_scan.py",
        ),
        _audit_check(
            "browser_smoke_evidence",
            "Browser smoke evidence",
            "ready" if _env_bool("JIEJING_BROWSER_SMOKE_PASSED") else "blocked",
            f"browser_smoke_passed={_env_bool('JIEJING_BROWSER_SMOKE_PASSED')}; public_base={os.environ.get('JIEJING_PUBLIC_BASE_URL', '') or 'not_recorded'}",
            "Run app load, settings launch tab, pricing, owner visibility and console smoke on app.jiejing.shop.",
            "tools/codex_jiejing_all_modules_clean_smoke.js",
        ),
        _audit_check(
            "owner_review_packet_snapshot",
            "Owner review packet snapshot",
            "ready" if owner_review_packet.get("contract_version") == "2026-06-20-owner-review-packet-v1" else "blocked",
            f"review_status={owner_review_packet.get('status') or 'unknown'}; blocked={_as_int(owner_review_summary.get('blocked_count'))}; attention={_as_int(owner_review_summary.get('attention_count'))}",
            "Attach the sanitized owner review packet to each final launch rehearsal.",
            "/owner/launch-control owner_review_packet",
        ),
        _audit_check(
            "billing_no_charge_rehearsal",
            "Billing no-charge rehearsal",
            "ready" if no_charge_packet.get("status") == "ready" else "blocked",
            f"no_charge_rehearsal={no_charge_packet.get('status') or 'unknown'}; charge_now_allowed=false",
            "Keep payable QR creation disabled until the no-charge rehearsal is owner-approved.",
            "/owner/paid-launch-approval-packet no_charge_launch_rehearsal",
        ),
        _audit_check(
            "edge_waf_callback_snapshot",
            "Stable domain, WAF and callback snapshot",
            "ready" if edge.get("status") == "ready_for_owner_approval" else "blocked",
            f"edge={edge.get('status') or 'unknown'}; ready={_as_int(edge_summary.get('ready_count'))}/{_as_int(edge_summary.get('total_count'))}; callbacks={bool(edge_summary.get('callbacks_ready'))}",
            edge_summary.get("next_action") or "Verify stable domain, WAF/Bot controls, origin lock and callback URLs.",
            "/owner/edge-cutover-preflight",
        ),
        _audit_check(
            "subscription_shutdown_snapshot",
            "Subscription shutdown and quota snapshot",
            "ready" if subscription_shutdown_control.get("status") == "ready" else "blocked",
            f"shutdown={subscription_shutdown_control.get('status') or 'unknown'}; ready={_as_int(shutdown_summary.get('ready_count'))}/{_as_int(shutdown_summary.get('card_count'))}; charge_now_allowed=false",
            shutdown_summary.get("next_action") or "Keep failed-payment, cancellation and quota hard-stop evidence current.",
            "/billing/usage",
        ),
        _audit_check(
            "paid_launch_approval_snapshot",
            "Paid launch approval packet snapshot",
            "ready" if paid_packet.get("ready_for_owner_approval") is True else "blocked",
            f"approval={paid_packet.get('status') or 'unknown'}; blocked={_as_int(paid_summary.get('blocked_count'))}; public_paid_launch_allowed=false",
            paid_summary.get("next_step") or "Keep paid launch blocked until domain, billing, no-charge rehearsal and clean eBay smoke are ready.",
            "/owner/paid-launch-approval-packet",
        ),
        _audit_check(
            "rollback_controls_verified",
            "Rollback controls verified",
            "ready" if _env_bool("JIEJING_CUTOVER_ROLLBACK_VERIFIED") else "blocked",
            f"rollback_verified={_env_bool('JIEJING_CUTOVER_ROLLBACK_VERIFIED')}; database_exported=false; destructive_cleanup=false",
            "Record rollback steps, previous bundle/backup pointer, and operator command path without deleting merchant data.",
            "deploy/staging rollback notes",
        ),
        _audit_check(
            "ops_resilience_snapshot",
            "Operations and resilience snapshot",
            "ready" if operations_observability.get("status") == "ready" and resilience_war_room.get("status") == "ready" else "attention_required",
            f"ops_attention={_as_int(ops_summary.get('attention_count'))}; resilience_attention={_as_int(resilience_summary.get('attention_count'))}",
            ops_summary.get("next_action") or resilience_summary.get("next_action") or "Review queue, backup, incident and alert evidence after deploy.",
            "/owner/launch-control operations_observability resilience_war_room",
        ),
    ]
    blocked = [item for item in checks if item.get("status") == "blocked"]
    attention = [item for item in checks if item.get("status") == "attention_required"]
    status = "ready_for_owner_approval" if not blocked else "blocked"
    next_action = (
        blocked[0]["next_action"]
        if blocked
        else attention[0]["next_action"]
        if attention
        else "Attach this audit packet to the final owner approval record."
    )
    return {
        "contract_version": "2026-06-20-launch-rehearsal-audit-v1",
        "audience": "platform_internal_admin",
        "mode": "internal_rehearsal_record_no_charge_no_write",
        "environment": settings.environment,
        "customer_visible": False,
        "status": status,
        "ready_for_owner_approval": status == "ready_for_owner_approval",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "status": status,
            "ready_count": len([item for item in checks if item.get("status") == "ready"]),
            "blocked_count": len(blocked),
            "attention_count": len(attention),
            "check_count": len(checks),
            "next_action": next_action,
            "beta_ready": bool(summary.get("beta_ready")),
            "production_ready": bool(summary.get("production_ready")),
            "can_accept_real_customers": bool(summary.get("can_accept_real_customers")),
            "latest_official_ebay_packet_id": summary.get("latest_official_ebay_packet_id") or "",
            "ebay_token_refresh_success_count": _as_int(summary.get("ebay_token_refresh_success_count")),
            "billing_provider": summary.get("billing_provider") or "not_selected",
            "public_base_url": os.environ.get("JIEJING_PUBLIC_BASE_URL", ""),
            "secret_exposed": False,
        },
        "checks": checks,
        "rollback_controls": [
            "keep_current_database_and_merchant_records_unchanged",
            "rollback_only_application_bundle_or_runtime_config_when_needed",
            "use_deploy_staging_patch_backup_pointer_before_redeploy",
            "keep_public_checkout_disabled_until_owner_approval",
            "keep_real_ebay_writes_confirmation_gated_after_cutover",
            "if_secret_exposure_is_suspected_rotate_only_inside_backend_vault_boundary",
            "after_timeout_check_platform_state_before_retrying_any_real_write",
        ],
        "evidence_register": [
            "/health",
            "/health/deep",
            "/readiness/product-saas",
            "/owner/launch-control",
            "/owner/edge-cutover-preflight",
            "/owner/paid-launch-approval-packet",
            "python tools/jiejing_secret_scan.py",
            "node tools/codex_jiejing_all_modules_clean_smoke.js",
            "node tools/codex_jiejing_owner_launch_control_smoke.js",
        ],
        "source_snapshots": {
            "lanes": [{"key": item.get("key"), "status": item.get("status")} for item in lanes],
            "external_blockers": [{"key": item.get("key"), "status": item.get("status")} for item in external_blockers],
            "internal_work_queue": [{"key": item.get("key"), "status": item.get("status")} for item in internal_work_queue],
            "readiness": evidence_summary.get("readiness") if isinstance(evidence_summary.get("readiness"), dict) else {},
            "billing": evidence_summary.get("billing") if isinstance(evidence_summary.get("billing"), dict) else {},
            "edge": evidence_summary.get("edge") if isinstance(evidence_summary.get("edge"), dict) else {},
            "secret_exposed": False,
        },
        "safety": _launch_rehearsal_audit_safety_flags(),
        "download_allowed_for_internal_admin": True,
        "exports_database": False,
        "exports_raw_secret": False,
        "includes_raw_tokens": False,
        "includes_payment_secret": False,
        "calls_stripe_api": False,
        "creates_checkout_session": False,
        "triggers_real_charge": False,
        "charge_now_allowed": False,
        "triggers_ebay_oauth": False,
        "repeat_ebay_oauth_allowed": False,
        "triggers_real_platform_write": False,
        "platform_write_now_allowed": False,
        "frontend_gets_secret": False,
        "secret_exposed": False,
    }


def _audit_check(key: str, label: str, status: str, evidence: str, next_action: str, source_endpoint: str) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "status": status,
        "tone": _tone(status),
        "evidence_summary": str(evidence or "")[:560],
        "next_action": str(next_action or "")[:560],
        "source_endpoint": source_endpoint,
        "owner": "release_manager",
        "customer_visible": False,
        "exports_database": False,
        "exports_raw_secret": False,
        "includes_raw_tokens": False,
        "includes_payment_secret": False,
        "calls_stripe_api": False,
        "creates_checkout_session": False,
        "triggers_real_charge": False,
        "charge_now_allowed": False,
        "triggers_ebay_oauth": False,
        "repeat_ebay_oauth_allowed": False,
        "triggers_real_platform_write": False,
        "platform_write_now_allowed": False,
        "frontend_gets_secret": False,
        "secret_exposed": False,
    }


def _launch_rehearsal_audit_safety_flags() -> dict[str, bool]:
    return {
        "read_only": True,
        "platform_internal_admin_only": True,
        "customer_visible": False,
        "download_allowed_for_internal_admin": True,
        "exports_database": False,
        "exports_raw_secret": False,
        "includes_raw_tokens": False,
        "includes_payment_secret": False,
        "calls_stripe_api": False,
        "creates_checkout_session": False,
        "triggers_real_charge": False,
        "charge_now_allowed": False,
        "triggers_ebay_oauth": False,
        "repeat_ebay_oauth_allowed": False,
        "triggers_real_platform_write": False,
        "platform_write_now_allowed": False,
        "frontend_gets_secret": False,
        "frontend_gets_payment_secret": False,
        "frontend_gets_ebay_token": False,
        "secret_exposed": False,
    }


def _release_history(
    *,
    settings: SaaSSettings,
    summary: dict[str, Any],
    evidence_summary: dict[str, Any],
    owner_review_packet: dict[str, Any],
    launch_rehearsal_audit_packet: dict[str, Any],
) -> dict[str, Any]:
    output_root = settings.output_root
    bundle_records = _bundle_manifest_records(output_root=output_root)
    rollback_points = _rollback_points(output_root=output_root)
    current_asset_version = _current_frontend_asset_version()
    latest_record = bundle_records[0] if bundle_records else {}
    readiness = evidence_summary.get("readiness") if isinstance(evidence_summary.get("readiness"), dict) else {}
    billing = evidence_summary.get("billing") if isinstance(evidence_summary.get("billing"), dict) else {}
    edge = evidence_summary.get("edge") if isinstance(evidence_summary.get("edge"), dict) else {}
    return {
        "contract_version": "2026-06-20-owner-release-history-v1",
        "audience": "platform_internal_admin",
        "mode": "sanitized_local_artifact_history",
        "environment": settings.environment,
        "customer_visible": False,
        "status": "available" if bundle_records or rollback_points else "no_local_release_artifacts",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "bundle_record_count": len(bundle_records),
            "rollback_point_count": len(rollback_points),
            "latest_bundle": latest_record.get("zip_file") or "",
            "latest_bundle_sha256": latest_record.get("zip_sha256") or "",
            "latest_bundle_created_at": latest_record.get("created_at") or "",
            "current_frontend_asset_version": current_asset_version,
            "health_expected": "ok",
            "deep_health_expected": "ready",
            "readiness_beta_ready": bool(readiness.get("beta_ready") if readiness else summary.get("beta_ready")),
            "readiness_production_ready": bool(readiness.get("production_ready") if readiness else summary.get("production_ready")),
            "can_accept_real_customers": bool(
                readiness.get("can_accept_real_customers") if readiness else summary.get("can_accept_real_customers")
            ),
            "billing_provider": (billing.get("provider") if isinstance(billing, dict) else "") or summary.get("billing_provider") or "not_selected",
            "billing_ready_for_paid_launch": bool(
                billing.get("mainland_payment_ready_for_owner_approval")
                if isinstance(billing, dict)
                else summary.get("mainland_payment_ready_for_owner_approval")
            ),
            "edge_status": edge.get("status") if isinstance(edge, dict) else "unknown",
            "owner_review_status": owner_review_packet.get("status") or "unknown",
            "launch_rehearsal_audit_status": launch_rehearsal_audit_packet.get("status") or "unknown",
            "secret_exposed": False,
        },
        "records": bundle_records,
        "rollback_points": rollback_points,
        "release_checks": _release_history_checks(
            summary=summary,
            evidence_summary=evidence_summary,
            latest_record=latest_record,
            rollback_points=rollback_points,
            current_asset_version=current_asset_version,
        ),
        "safety": _release_history_safety_flags(),
        "download_allowed_for_internal_admin": True,
        "exports_database": False,
        "exports_raw_secret": False,
        "includes_raw_tokens": False,
        "includes_payment_secret": False,
        "reads_env_secret_values": False,
        "calls_stripe_api": False,
        "creates_checkout_session": False,
        "triggers_real_charge": False,
        "charge_now_allowed": False,
        "triggers_ebay_oauth": False,
        "repeat_ebay_oauth_allowed": False,
        "triggers_real_platform_write": False,
        "platform_write_now_allowed": False,
        "frontend_gets_secret": False,
        "secret_exposed": False,
    }


def _bundle_manifest_records(*, output_root: Path) -> list[dict[str, Any]]:
    manifests = sorted(
        (output_root / "jiejing-public-staging-bundle").glob("jiejing-public-staging-*.manifest.json"),
        key=lambda item: item.stat().st_mtime if item.exists() else 0,
        reverse=True,
    )
    records: list[dict[str, Any]] = []
    for manifest_path in manifests[:8]:
        manifest = _read_json_file(manifest_path)
        created_at = str(manifest.get("created_at") or _mtime_iso(manifest_path))
        zip_file = _portable_artifact_filename(
            manifest.get("zip_path"),
            fallback=manifest_path.name.replace(".manifest.json", ".zip"),
        )
        records.append(
            {
                "key": manifest_path.stem.replace(".manifest", ""),
                "created_at": created_at,
                "manifest_file": manifest_path.name,
                "zip_file": zip_file,
                "zip_sha256": str(manifest.get("zip_sha256") or ""),
                "file_count": _as_int(manifest.get("file_count")),
                "bundle": str(manifest.get("bundle") or "public_staging"),
                "product": str(manifest.get("product") or "Jiejing SaaS"),
                "rollback_source": "staging_patch_backup",
                "secret_exposed": False,
                "exports_database": False,
                "exports_raw_secret": False,
                "includes_raw_tokens": False,
            }
        )
    return records


def _portable_artifact_filename(value: Any, *, fallback: str) -> str:
    normalized = str(value or "").strip().replace("\\", "/").rstrip("/")
    filename = normalized.rsplit("/", 1)[-1] if normalized else ""
    return filename or fallback


def _rollback_points(*, output_root: Path) -> list[dict[str, Any]]:
    backup_root = output_root / "staging-patch-backups"
    if not backup_root.exists():
        return []
    points: list[dict[str, Any]] = []
    for item in sorted([entry for entry in backup_root.iterdir() if entry.is_dir()], key=lambda entry: entry.stat().st_mtime, reverse=True)[:8]:
        points.append(
            {
                "key": item.name,
                "label": f"staging patch backup {item.name}",
                "created_at": _mtime_iso(item),
                "backup_dir_name": item.name,
                "rollback_scope": "application_bundle_and_runtime_config_only",
                "merchant_data_delete_allowed": False,
                "database_restore_triggered": False,
                "secret_exposed": False,
                "exports_database": False,
                "exports_raw_secret": False,
            }
        )
    return points


def _release_history_checks(
    *,
    summary: dict[str, Any],
    evidence_summary: dict[str, Any],
    latest_record: dict[str, Any],
    rollback_points: list[dict[str, Any]],
    current_asset_version: str,
) -> list[dict[str, Any]]:
    readiness = evidence_summary.get("readiness") if isinstance(evidence_summary.get("readiness"), dict) else {}
    ebay = evidence_summary.get("ebay") if isinstance(evidence_summary.get("ebay"), dict) else {}
    return [
        _release_check(
            "latest_bundle_manifest",
            "Latest bundle manifest",
            "ready" if latest_record.get("zip_sha256") else "attention_required",
            f"zip={latest_record.get('zip_file') or 'missing'}; sha256_present={bool(latest_record.get('zip_sha256'))}; file_count={_as_int(latest_record.get('file_count'))}",
            "Create a public staging bundle before each deploy and keep its manifest for rollback review.",
        ),
        _release_check(
            "frontend_asset_version",
            "Frontend asset version",
            "ready" if current_asset_version else "attention_required",
            f"asset_version={current_asset_version or 'missing'}",
            "Keep app.html/index.html cache-busting version aligned with each deploy.",
        ),
        _release_check(
            "rollback_backup_pointer",
            "Rollback backup pointer",
            "ready" if rollback_points else "attention_required",
            f"rollback_points={len(rollback_points)}",
            "Keep at least one staging patch backup pointer before every production-adjacent deploy.",
        ),
        _release_check(
            "readiness_snapshot",
            "Readiness snapshot",
            "ready" if readiness else "attention_required",
            f"beta={bool(readiness.get('beta_ready') if readiness else summary.get('beta_ready'))}; production={bool(readiness.get('production_ready') if readiness else summary.get('production_ready'))}; customers={bool(readiness.get('can_accept_real_customers') if readiness else summary.get('can_accept_real_customers'))}",
            "Attach /readiness/product-saas after deploy and keep public paid launch blocked until production readiness is true.",
        ),
        _release_check(
            "ebay_refresh_proof_snapshot",
            "eBay refresh proof snapshot",
            "ready" if _as_int(ebay.get("refresh_success_count") or summary.get("ebay_token_refresh_success_count")) > 0 else "blocked",
            f"latest_packet={ebay.get('latest_packet_id') or summary.get('latest_official_ebay_packet_id') or 'missing'}; refresh_success={_as_int(ebay.get('refresh_success_count') or summary.get('ebay_token_refresh_success_count'))}",
            "Do not mark production launch ready until backend-only eBay refresh proof is greater than zero on a clean account.",
        ),
        _release_check(
            "billing_public_charge_block",
            "Billing public charge block",
            "ready"
            if summary.get("mainland_payment_ready_for_owner_approval") is not True
            else "attention_required",
            f"provider={summary.get('billing_provider') or 'not_selected'}; owner_ready={summary.get('mainland_payment_ready_for_owner_approval') is True}; charge_now_allowed=false",
            "Keep public charging disabled until live provider and no-charge rehearsal are owner-approved.",
        ),
    ]


def _release_check(key: str, label: str, status: str, evidence: str, next_action: str) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "status": status,
        "tone": _tone(status),
        "evidence_summary": str(evidence or "")[:520],
        "next_action": str(next_action or "")[:520],
        "customer_visible": False,
        "exports_database": False,
        "exports_raw_secret": False,
        "includes_raw_tokens": False,
        "includes_payment_secret": False,
        "calls_stripe_api": False,
        "creates_checkout_session": False,
        "triggers_real_charge": False,
        "triggers_ebay_oauth": False,
        "triggers_real_platform_write": False,
        "secret_exposed": False,
    }


def _release_history_safety_flags() -> dict[str, bool]:
    return {
        "read_only": True,
        "platform_internal_admin_only": True,
        "customer_visible": False,
        "download_allowed_for_internal_admin": True,
        "exports_database": False,
        "exports_raw_secret": False,
        "includes_raw_tokens": False,
        "includes_payment_secret": False,
        "reads_env_secret_values": False,
        "calls_stripe_api": False,
        "creates_checkout_session": False,
        "triggers_real_charge": False,
        "charge_now_allowed": False,
        "triggers_ebay_oauth": False,
        "repeat_ebay_oauth_allowed": False,
        "triggers_real_platform_write": False,
        "platform_write_now_allowed": False,
        "frontend_gets_secret": False,
        "secret_exposed": False,
    }


def _continuity_handoff_digest(
    *,
    settings: SaaSSettings,
    summary: dict[str, Any],
    evidence_summary: dict[str, Any],
    lanes: list[dict[str, Any]],
    external_blockers: list[dict[str, Any]],
    internal_work_queue: list[dict[str, Any]],
    release_history: dict[str, Any],
) -> dict[str, Any]:
    release_summary = release_history.get("summary") if isinstance(release_history.get("summary"), dict) else {}
    readiness = evidence_summary.get("readiness") if isinstance(evidence_summary.get("readiness"), dict) else {}
    ebay = evidence_summary.get("ebay") if isinstance(evidence_summary.get("ebay"), dict) else {}
    billing = evidence_summary.get("billing") if isinstance(evidence_summary.get("billing"), dict) else {}
    blocked_lanes = [item for item in lanes if item.get("status") != "ready"]
    blocked_external = [item for item in external_blockers if item.get("status") != "ready"]
    pending_internal = [item for item in internal_work_queue if item.get("status") not in {"ready", "done"}]
    current_state = [
        _handoff_line(
            "public_entry",
            "Public app entry",
            "ready",
            "https://app.jiejing.shop",
            "Keep this as the stable HTTPS entry for app, health, callbacks and browser smoke.",
        ),
        _handoff_line(
            "readiness",
            "Product readiness",
            "blocked" if not bool(readiness.get("production_ready") if readiness else summary.get("production_ready")) else "ready",
            f"beta={bool(readiness.get('beta_ready') if readiness else summary.get('beta_ready'))}; production={bool(readiness.get('production_ready') if readiness else summary.get('production_ready'))}; customers={bool(readiness.get('can_accept_real_customers') if readiness else summary.get('can_accept_real_customers'))}",
            "Keep public paid launch blocked until production_ready and can_accept_real_customers are both true.",
        ),
        _handoff_line(
            "ebay_refresh_proof",
            "eBay refresh proof",
            "blocked" if _as_int(ebay.get("refresh_success_count") or summary.get("ebay_token_refresh_success_count")) <= 0 else "ready",
            f"latest_packet={ebay.get('latest_packet_id') or summary.get('latest_official_ebay_packet_id') or 'missing'}; refresh_success={_as_int(ebay.get('refresh_success_count') or summary.get('ebay_token_refresh_success_count'))}",
            "Do not repeat OAuth or claim ready until a clean new account has backend-only refresh success proof.",
        ),
        _handoff_line(
            "billing",
            "Billing provider",
            "blocked"
            if summary.get("mainland_payment_ready_for_owner_approval") is not True
            else "ready",
            f"provider={(billing.get('provider') if isinstance(billing, dict) else '') or summary.get('billing_provider') or 'not_selected'}; owner_ready={summary.get('mainland_payment_ready_for_owner_approval') is True}; charge_now_allowed=false",
            "Use test/mock billing until live provider, prices, portal and signed webhook are owner-approved.",
        ),
        _handoff_line(
            "latest_release",
            "Latest release artifact",
            "ready" if release_summary.get("latest_bundle_sha256") else "attention_required",
            f"bundle={release_summary.get('latest_bundle') or 'missing'}; sha256={release_summary.get('latest_bundle_sha256') or 'missing'}; asset={release_summary.get('current_frontend_asset_version') or 'missing'}",
            "Create and verify a signed staging bundle before every production-adjacent deploy.",
        ),
    ]
    next_internal_actions = [
        _handoff_action(item, source="internal_work_queue")
        for item in pending_internal[:6]
        if isinstance(item, dict)
    ]
    next_external_actions = [
        _handoff_action(item, source="external_blocker")
        for item in blocked_external[:6]
        if isinstance(item, dict)
    ]
    do_not_do = [
        "Do not repeat eBay OAuth with the frozen old account.",
        "Do not create a payable QR or call a live payment provider until owner-approved cutover.",
        "Do not perform real eBay writes, price changes, inventory changes, refunds, ads or policy edits outside confirmation center.",
        "Do not export database rows, raw secrets, eBay tokens, refresh tokens, model keys, API keys or payment secrets.",
        "Do not automatically delete smoke/test data; keep cleanup as a reviewed plan.",
    ]
    proof_links = [
        {"label": "health", "url": "https://app.jiejing.shop/health"},
        {"label": "deep_health", "url": "https://app.jiejing.shop/health/deep"},
        {"label": "readiness", "url": "https://app.jiejing.shop/readiness/product-saas"},
        {"label": "owner_launch_control", "url": "/owner/launch-control"},
    ]
    handoff_lines = [
        "Jiejing owner continuity handoff",
        f"environment={settings.environment}",
        "public_app=https://app.jiejing.shop",
        f"beta_ready={bool(summary.get('beta_ready'))}",
        f"production_ready={bool(summary.get('production_ready'))}",
        f"can_accept_real_customers={bool(summary.get('can_accept_real_customers'))}",
        f"latest_ebay_packet={summary.get('latest_official_ebay_packet_id') or 'missing'}",
        f"ebay_refresh_success={_as_int(summary.get('ebay_token_refresh_success_count'))}",
        f"billing_provider={summary.get('billing_provider') or 'not_selected'}",
        f"latest_bundle={release_summary.get('latest_bundle') or 'missing'}",
        f"latest_bundle_sha256={release_summary.get('latest_bundle_sha256') or 'missing'}",
        "public_paid_launch_allowed=false",
        "charge_now_allowed=false",
        "platform_write_now_allowed=false",
        "repeat_ebay_oauth_allowed=false",
        "secret_exposed=false",
    ]
    return {
        "contract_version": "2026-06-20-owner-continuity-handoff-v1",
        "audience": "platform_internal_admin",
        "mode": "sanitized_next_operator_handoff",
        "environment": settings.environment,
        "customer_visible": False,
        "status": "blocked_for_public_launch" if blocked_lanes or blocked_external else "ready_for_owner_review",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "blocked_lane_count": len(blocked_lanes),
            "external_blocker_count": len(blocked_external),
            "pending_internal_action_count": len(pending_internal),
            "current_state_count": len(current_state),
            "do_not_do_count": len(do_not_do),
            "latest_bundle": release_summary.get("latest_bundle") or "",
            "latest_bundle_sha256": release_summary.get("latest_bundle_sha256") or "",
            "current_frontend_asset_version": release_summary.get("current_frontend_asset_version") or "",
            "next_owner_step": next_external_actions[0]["next_action"] if next_external_actions else "Continue internal hardening and smoke verification.",
            "secret_exposed": False,
        },
        "current_state": current_state,
        "next_internal_actions": next_internal_actions,
        "next_external_actions": next_external_actions,
        "do_not_do": do_not_do,
        "proof_links": proof_links,
        "handoff_text": "\n".join(handoff_lines),
        "safety": _continuity_handoff_safety_flags(),
        "download_allowed_for_internal_admin": True,
        "exports_database": False,
        "exports_raw_secret": False,
        "includes_raw_tokens": False,
        "includes_payment_secret": False,
        "reads_env_secret_values": False,
        "calls_stripe_api": False,
        "creates_checkout_session": False,
        "triggers_real_charge": False,
        "charge_now_allowed": False,
        "triggers_ebay_oauth": False,
        "repeat_ebay_oauth_allowed": False,
        "triggers_real_platform_write": False,
        "platform_write_now_allowed": False,
        "frontend_gets_secret": False,
        "secret_exposed": False,
    }


def _handoff_line(key: str, label: str, status: str, evidence: str, next_action: str) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "status": status,
        "tone": _tone(status),
        "evidence_summary": str(evidence or "")[:520],
        "next_action": str(next_action or "")[:520],
        "customer_visible": False,
        "secret_exposed": False,
    }


def _handoff_action(item: dict[str, Any], *, source: str) -> dict[str, Any]:
    return {
        "key": str(item.get("key") or source)[:120],
        "label": str(item.get("label") or item.get("title") or item.get("key") or source)[:180],
        "status": str(item.get("status") or "attention_required")[:80],
        "tone": str(item.get("tone") or _tone(str(item.get("status") or "")))[:40],
        "evidence_summary": str(item.get("evidence_summary") or item.get("detail") or item.get("evidence") or "")[:520],
        "next_action": str(item.get("next_action") or "Review current owner launch-control evidence.")[:520],
        "source": source,
        "source_endpoint": str(item.get("source_endpoint") or "/owner/launch-control")[:180],
        "customer_visible": False,
        "secret_exposed": False,
    }


def _continuity_handoff_safety_flags() -> dict[str, bool]:
    return {
        "read_only": True,
        "platform_internal_admin_only": True,
        "customer_visible": False,
        "download_allowed_for_internal_admin": True,
        "exports_database": False,
        "exports_raw_secret": False,
        "includes_raw_tokens": False,
        "includes_payment_secret": False,
        "reads_env_secret_values": False,
        "calls_stripe_api": False,
        "creates_checkout_session": False,
        "triggers_real_charge": False,
        "charge_now_allowed": False,
        "triggers_ebay_oauth": False,
        "repeat_ebay_oauth_allowed": False,
        "triggers_real_platform_write": False,
        "platform_write_now_allowed": False,
        "frontend_gets_secret": False,
        "secret_exposed": False,
    }


def _cutover_decision_checklist(
    *,
    settings: SaaSSettings,
    summary: dict[str, Any],
    lanes: list[dict[str, Any]],
    external_blockers: list[dict[str, Any]],
    internal_work_queue: list[dict[str, Any]],
    owner_review_packet: dict[str, Any],
    launch_rehearsal_audit_packet: dict[str, Any],
    continuity_handoff_digest: dict[str, Any],
) -> dict[str, Any]:
    blocked_lanes = [item for item in lanes if item.get("status") != "ready"]
    blocked_external = [item for item in external_blockers if item.get("status") != "ready"]
    pending_internal = [item for item in internal_work_queue if item.get("status") not in {"ready", "done"}]
    owner_review_summary = owner_review_packet.get("summary") if isinstance(owner_review_packet.get("summary"), dict) else {}
    audit_summary = (
        launch_rehearsal_audit_packet.get("summary")
        if isinstance(launch_rehearsal_audit_packet.get("summary"), dict)
        else {}
    )
    handoff_summary = (
        continuity_handoff_digest.get("summary")
        if isinstance(continuity_handoff_digest.get("summary"), dict)
        else {}
    )
    codex_can_continue = bool(summary.get("beta_ready")) and not bool(summary.get("secret_exposed"))
    external_done = not blocked_external
    rehearsal_ready = (
        external_done
        and launch_rehearsal_audit_packet.get("status") == "ready_for_owner_approval"
        and _as_int(audit_summary.get("blocked_count")) == 0
    )
    live_ready = (
        rehearsal_ready
        and bool(summary.get("production_ready"))
        and bool(summary.get("can_accept_real_customers"))
        and summary.get("mainland_payment_ready_for_owner_approval") is True
        and _as_int(summary.get("ebay_token_refresh_success_count")) > 0
    )
    recommended_next_step = (
        "continue_internal_hardening"
        if pending_internal
        else "wait_for_founder_external_console"
        if blocked_external
        else "run_final_no_real_charge_rehearsal"
        if not rehearsal_ready
        else "prepare_owner_live_cutover_approval"
        if live_ready
        else "keep_public_paid_launch_blocked"
    )
    phase_checklist = [
        _cutover_phase(
            "current_beta_state",
            "Current beta state",
            "ready" if bool(summary.get("beta_ready")) else "attention_required",
            f"beta_ready={bool(summary.get('beta_ready'))}; production_ready={bool(summary.get('production_ready'))}; can_accept_real_customers={bool(summary.get('can_accept_real_customers'))}",
            "Keep using private beta evidence until production readiness and real-customer acceptance are both true.",
            owner="platform_ops",
        ),
        _cutover_phase(
            "codex_internal_continuation",
            "Codex/platform ops can continue",
            "ready" if codex_can_continue else "attention_required",
            f"pending_internal={len(pending_internal)}; owner_review_blocked={_as_int(owner_review_summary.get('blocked_count'))}; audit_blocked={_as_int(audit_summary.get('blocked_count'))}",
            "Continue no-charge rehearsals, owner-only evidence, secret scan, browser smoke and release history without external side effects.",
            owner="codex_or_platform_ops",
        ),
        _cutover_phase(
            "founder_external_console",
            "Founder external console work",
            "blocked" if blocked_external else "ready",
            f"external_blockers={len(blocked_external)}; next={blocked_external[0].get('key') if blocked_external else 'none'}",
            blocked_external[0]["next_action"] if blocked_external else "All external console blockers are currently cleared.",
            owner="founder_operator",
            external_console_required=bool(blocked_external),
        ),
        _cutover_phase(
            "final_no_real_charge_rehearsal",
            "Final no-real-charge rehearsal",
            "ready" if rehearsal_ready else "blocked",
            f"external_done={external_done}; audit_status={launch_rehearsal_audit_packet.get('status') or 'unknown'}; charge_now_allowed=false",
            "Run the final no-real-charge rehearsal only after external WeChat/domain/eBay prerequisites are ready.",
            owner="platform_ops",
        ),
        _cutover_phase(
            "live_paid_public_launch",
            "Live paid public launch",
            "ready" if live_ready else "blocked",
            f"mainland_payment_owner_ready={summary.get('mainland_payment_ready_for_owner_approval') is True}; refresh_success={_as_int(summary.get('ebay_token_refresh_success_count'))}; public_paid_launch_allowed=false",
            "Live charging and real-customer launch remain blocked until owner approval after all proof is attached.",
            owner="founder_operator",
            external_console_required=True,
        ),
    ]
    forbidden_actions = [
        "Do not create a payable QR or call a live payment provider from this panel.",
        "Do not repeat eBay OAuth until a clean new eBay account is ready.",
        "Do not reuse the frozen old eBay account for live smoke.",
        "Do not perform real eBay writes, price, inventory, refund, ad or policy changes outside confirmation center.",
        "Do not export database rows, raw secrets, eBay tokens, refresh tokens, model keys, API keys or payment secrets.",
        "Do not automatically delete smoke or test data.",
    ]
    return {
        "contract_version": "2026-06-20-cutover-decision-checklist-v1",
        "audience": "platform_internal_admin",
        "mode": "sanitized_cutover_decision_checklist",
        "environment": settings.environment,
        "customer_visible": False,
        "status": "ready_for_final_rehearsal" if rehearsal_ready else "blocked_for_paid_public_launch",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "recommended_next_step": recommended_next_step,
            "codex_can_continue_without_user": codex_can_continue,
            "external_blocker_count": len(blocked_external),
            "pending_internal_count": len(pending_internal),
            "blocked_lane_count": len(blocked_lanes),
            "phase_count": len(phase_checklist),
            "owner_review_status": owner_review_packet.get("status") or "unknown",
            "launch_rehearsal_audit_status": launch_rehearsal_audit_packet.get("status") or "unknown",
            "handoff_status": continuity_handoff_digest.get("status") or "unknown",
            "handoff_next_owner_step": handoff_summary.get("next_owner_step") or "",
            "beta_ready": bool(summary.get("beta_ready")),
            "production_ready": bool(summary.get("production_ready")),
            "can_accept_real_customers": bool(summary.get("can_accept_real_customers")),
            "billing_ready_for_paid_launch": summary.get("mainland_payment_ready_for_owner_approval") is True,
            "mainland_payment_ready_for_owner_approval": (
                summary.get("mainland_payment_ready_for_owner_approval") is True
            ),
            "ebay_token_refresh_success_count": _as_int(summary.get("ebay_token_refresh_success_count")),
            "public_paid_launch_allowed": False,
            "charge_now_allowed": False,
            "platform_write_now_allowed": False,
            "repeat_ebay_oauth_allowed": False,
            "secret_exposed": False,
        },
        "phase_checklist": phase_checklist,
        "founder_external_actions": [_cutover_action(item, source="external_blocker") for item in blocked_external[:8]],
        "codex_internal_actions": [_cutover_action(item, source="internal_work_queue") for item in (pending_internal or internal_work_queue)[:8]],
        "forbidden_actions": forbidden_actions,
        "proof_links": [
            {"label": "health", "url": "https://app.jiejing.shop/health"},
            {"label": "deep_health", "url": "https://app.jiejing.shop/health/deep"},
            {"label": "readiness", "url": "https://app.jiejing.shop/readiness/product-saas"},
            {"label": "owner_launch_control", "url": "/owner/launch-control"},
        ],
        "safety": _cutover_decision_safety_flags(),
        "download_allowed_for_internal_admin": True,
        "exports_database": False,
        "exports_raw_secret": False,
        "includes_raw_tokens": False,
        "includes_payment_secret": False,
        "reads_env_secret_values": False,
        "calls_stripe_api": False,
        "creates_checkout_session": False,
        "triggers_real_charge": False,
        "charge_now_allowed": False,
        "triggers_ebay_oauth": False,
        "repeat_ebay_oauth_allowed": False,
        "triggers_real_platform_write": False,
        "platform_write_now_allowed": False,
        "frontend_gets_secret": False,
        "frontend_gets_payment_secret": False,
        "frontend_gets_ebay_token": False,
        "secret_exposed": False,
    }


def _cutover_phase(
    key: str,
    label: str,
    status: str,
    evidence: str,
    next_action: str,
    *,
    owner: str,
    external_console_required: bool = False,
) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "status": status,
        "tone": _tone(status),
        "owner": owner,
        "external_console_required": external_console_required,
        "evidence_summary": str(evidence or "")[:520],
        "next_action": str(next_action or "")[:520],
        "customer_visible": False,
        "exports_database": False,
        "exports_raw_secret": False,
        "includes_raw_tokens": False,
        "includes_payment_secret": False,
        "calls_stripe_api": False,
        "creates_checkout_session": False,
        "triggers_real_charge": False,
        "triggers_ebay_oauth": False,
        "triggers_real_platform_write": False,
        "frontend_gets_secret": False,
        "secret_exposed": False,
    }


def _cutover_action(item: dict[str, Any], *, source: str) -> dict[str, Any]:
    return {
        "key": str(item.get("key") or source)[:120],
        "label": str(item.get("label") or item.get("title") or item.get("key") or source)[:180],
        "status": str(item.get("status") or "attention_required")[:80],
        "tone": str(item.get("tone") or _tone(str(item.get("status") or "")))[:40],
        "owner": str(item.get("owner") or ("founder_operator" if source == "external_blocker" else "codex_or_platform_ops"))[:80],
        "evidence_summary": str(item.get("evidence_summary") or item.get("detail") or item.get("evidence") or "")[:520],
        "next_action": str(item.get("next_action") or item.get("verification") or "Review current owner launch-control evidence.")[:520],
        "source": source,
        "source_endpoint": str(item.get("source_endpoint") or "/owner/launch-control")[:180],
        "external_console_required": bool(item.get("external_console_required") or source == "external_blocker"),
        "customer_visible": False,
        "exports_database": False,
        "exports_raw_secret": False,
        "includes_raw_tokens": False,
        "includes_payment_secret": False,
        "calls_stripe_api": False,
        "creates_checkout_session": False,
        "triggers_real_charge": False,
        "triggers_ebay_oauth": bool(item.get("triggers_ebay_oauth")),
        "repeat_ebay_oauth_allowed": False,
        "triggers_real_platform_write": False,
        "frontend_gets_secret": False,
        "secret_exposed": False,
    }


def _cutover_decision_safety_flags() -> dict[str, bool]:
    return {
        "read_only": True,
        "platform_internal_admin_only": True,
        "customer_visible": False,
        "download_allowed_for_internal_admin": True,
        "exports_database": False,
        "exports_raw_secret": False,
        "includes_raw_tokens": False,
        "includes_payment_secret": False,
        "reads_env_secret_values": False,
        "calls_stripe_api": False,
        "creates_checkout_session": False,
        "triggers_real_charge": False,
        "charge_now_allowed": False,
        "triggers_ebay_oauth": False,
        "repeat_ebay_oauth_allowed": False,
        "triggers_real_platform_write": False,
        "platform_write_now_allowed": False,
        "frontend_gets_secret": False,
        "frontend_gets_payment_secret": False,
        "frontend_gets_ebay_token": False,
        "secret_exposed": False,
    }


def _final_launch_rehearsal_execution_record(
    *,
    settings: SaaSSettings,
    summary: dict[str, Any],
    evidence_summary: dict[str, Any],
    owner_review_packet: dict[str, Any],
    launch_rehearsal_audit_packet: dict[str, Any],
    release_history: dict[str, Any],
    continuity_handoff_digest: dict[str, Any],
    cutover_decision_checklist: dict[str, Any],
    external_blockers: list[dict[str, Any]],
    internal_work_queue: list[dict[str, Any]],
) -> dict[str, Any]:
    readiness = evidence_summary.get("readiness") if isinstance(evidence_summary.get("readiness"), dict) else {}
    ebay = evidence_summary.get("ebay") if isinstance(evidence_summary.get("ebay"), dict) else {}
    billing = evidence_summary.get("billing") if isinstance(evidence_summary.get("billing"), dict) else {}
    edge = evidence_summary.get("edge") if isinstance(evidence_summary.get("edge"), dict) else {}
    operational = evidence_summary.get("operational") if isinstance(evidence_summary.get("operational"), dict) else {}
    release_summary = release_history.get("summary") if isinstance(release_history.get("summary"), dict) else {}
    owner_review_summary = owner_review_packet.get("summary") if isinstance(owner_review_packet.get("summary"), dict) else {}
    audit_summary = (
        launch_rehearsal_audit_packet.get("summary")
        if isinstance(launch_rehearsal_audit_packet.get("summary"), dict)
        else {}
    )
    cutover_summary = (
        cutover_decision_checklist.get("summary")
        if isinstance(cutover_decision_checklist.get("summary"), dict)
        else {}
    )
    handoff_summary = (
        continuity_handoff_digest.get("summary")
        if isinstance(continuity_handoff_digest.get("summary"), dict)
        else {}
    )
    release_checks = (
        release_history.get("release_checks")
        if isinstance(release_history.get("release_checks"), list)
        else []
    )
    release_check_by_key = {
        str(item.get("key") or ""): item
        for item in release_checks
        if isinstance(item, dict) and item.get("key")
    }
    blocked_external = [item for item in external_blockers if item.get("status") != "ready"]
    pending_internal = [item for item in internal_work_queue if item.get("status") not in {"ready", "done"}]
    rollback_points = release_history.get("rollback_points") if isinstance(release_history.get("rollback_points"), list) else []
    bundle_ready = bool(release_summary.get("latest_bundle_sha256"))
    stable_domain_ready = bool(summary.get("stable_domain_ready") or edge.get("callbacks_ready"))
    billing_rehearsal_ready = bool(billing.get("subscription_shutdown_ready")) and (
        summary.get("mainland_payment_ready_for_owner_approval") is not True
    )
    refresh_success_count = _as_int(ebay.get("refresh_success_count") or summary.get("ebay_token_refresh_success_count"))
    owner_approval_ready = (
        not blocked_external
        and not pending_internal
        and bool(readiness.get("production_ready") or summary.get("production_ready"))
        and bool(summary.get("can_accept_real_customers"))
        and summary.get("mainland_payment_ready_for_owner_approval") is True
        and refresh_success_count > 0
        and bool(rollback_points)
    )
    execution_steps = [
        _final_rehearsal_step(
            "predeploy_health_readiness_snapshot",
            "Predeploy health and readiness snapshot",
            "ready" if bool(summary.get("beta_ready")) and bool(readiness) else "attention_required",
            f"beta_ready={bool(summary.get('beta_ready'))}; production_ready={bool(summary.get('production_ready'))}; can_accept_real_customers={bool(summary.get('can_accept_real_customers'))}; warnings={_as_int(readiness.get('warning_count') or summary.get('warning_count'))}",
            "Capture /health, /health/deep and /readiness/product-saas immediately before any owner approval.",
            source_endpoint="/health + /health/deep + /readiness/product-saas",
        ),
        _final_rehearsal_step(
            "secret_scan_snapshot",
            "Secret scan snapshot",
            "ready" if _env_bool("JIEJING_SECRET_SCAN_PASSED") else "attention_required",
            f"secret_scan_passed={_env_bool('JIEJING_SECRET_SCAN_PASSED')}; secret_exposed=false",
            "Run python tools/jiejing_secret_scan.py after each production-adjacent change.",
            source_endpoint="tools/jiejing_secret_scan.py",
        ),
        _final_rehearsal_step(
            "browser_smoke_snapshot",
            "Browser smoke snapshot",
            "ready" if _env_bool("JIEJING_BROWSER_SMOKE_PASSED") else "attention_required",
            f"browser_smoke_passed={_env_bool('JIEJING_BROWSER_SMOKE_PASSED')}; app=https://app.jiejing.shop",
            "Run browser smoke for app shell, owner/admin gating, publish health and billing guardrails.",
            source_endpoint="tools/codex_jiejing_owner_launch_control_smoke.js",
        ),
        _final_rehearsal_step(
            "bundle_integrity_and_sha",
            "Bundle integrity and SHA",
            "ready" if bundle_ready else "attention_required",
            f"bundle={release_summary.get('latest_bundle') or 'missing'}; sha256={release_summary.get('latest_bundle_sha256') or 'missing'}; asset={release_summary.get('current_frontend_asset_version') or 'missing'}",
            "Keep a fresh staging bundle manifest and SHA256 before final rehearsal.",
            source_endpoint="output/jiejing-public-staging-bundle",
        ),
        _final_rehearsal_step(
            "rollback_backup_pointer",
            "Rollback backup pointer",
            "ready" if rollback_points else "attention_required",
            f"rollback_points={len(rollback_points)}; scope=application_bundle_and_runtime_config_only",
            "Keep at least one staging patch backup pointer before owner approval.",
            source_endpoint="output/staging-patch-backups",
        ),
        _final_rehearsal_step(
            "owner_review_packet_attached",
            "Owner review packet attached",
            "ready" if owner_review_packet.get("contract_version") == "2026-06-20-owner-review-packet-v1" else "blocked",
            f"owner_review_status={owner_review_packet.get('status') or 'unknown'}; blocked={_as_int(owner_review_summary.get('blocked_count'))}; attention={_as_int(owner_review_summary.get('attention_count'))}",
            "Attach the sanitized owner review packet to the final rehearsal evidence.",
            source_endpoint="/owner/launch-control owner_review_packet",
        ),
        _final_rehearsal_step(
            "cutover_decision_checklist_attached",
            "Cutover decision checklist attached",
            "ready" if cutover_decision_checklist.get("contract_version") == "2026-06-20-cutover-decision-checklist-v1" else "blocked",
            f"cutover_status={cutover_decision_checklist.get('status') or 'unknown'}; next={cutover_summary.get('recommended_next_step') or 'unknown'}; external={_as_int(cutover_summary.get('external_blocker_count'))}; internal={_as_int(cutover_summary.get('pending_internal_count'))}",
            "Attach the cutover checklist and keep live charge, OAuth and platform writes disabled.",
            source_endpoint="/owner/launch-control cutover_decision_checklist",
        ),
        _final_rehearsal_step(
            "no_real_charge_billing_rehearsal",
            "No-real-charge billing rehearsal",
            "ready" if billing_rehearsal_ready else "blocked",
            f"provider={billing.get('provider') or summary.get('billing_provider') or 'not_selected'}; owner_ready={summary.get('mainland_payment_ready_for_owner_approval') is True}; subscription_shutdown_ready={bool(billing.get('subscription_shutdown_ready'))}; charge_now_allowed=false",
            "Use mock/test mode until live prices, portal and signed webhook are configured and owner-approved.",
            source_endpoint="/billing/plans + /billing/usage",
        ),
        _final_rehearsal_step(
            "edge_waf_callback_snapshot",
            "Edge, WAF and callback snapshot",
            "ready" if stable_domain_ready else "attention_required",
            f"edge_status={edge.get('status') or 'unknown'}; ready={_as_int(edge.get('ready_count'))}/{_as_int(edge.get('total_count'))}; waf_ready={bool(edge.get('waf_ready'))}; callbacks_ready={bool(edge.get('callbacks_ready'))}; origin_locked={bool(edge.get('origin_locked'))}",
            "Verify Cloudflare/Tencent edge, stable domain, callback URLs and origin-lock posture before final rehearsal.",
            source_endpoint="/owner/edge-cutover-preflight",
        ),
        _final_rehearsal_step(
            "ebay_new_account_refresh_proof",
            "New eBay account refresh proof",
            "ready" if refresh_success_count > 0 else "blocked",
            f"latest_packet={ebay.get('latest_packet_id') or summary.get('latest_official_ebay_packet_id') or 'missing'}; refresh_success={refresh_success_count}",
            "Do not repeat OAuth or claim production-ready until a clean new eBay account has backend-only refresh proof.",
            source_endpoint="/readiness/product-saas",
        ),
        _final_rehearsal_step(
            "final_owner_approval_hold",
            "Final owner approval hold",
            "ready" if owner_approval_ready else "blocked",
            f"owner_approval_ready={owner_approval_ready}; public_paid_launch_allowed=false; charge_now_allowed=false; platform_write_now_allowed=false",
            "Keep launch blocked until the founder explicitly approves after all final rehearsal evidence is attached.",
            source_endpoint="/owner/launch-control",
        ),
    ]
    ready_count = len([item for item in execution_steps if item.get("status") == "ready"])
    blocked_count = len([item for item in execution_steps if item.get("status") == "blocked"])
    attention_count = len([item for item in execution_steps if item.get("status") == "attention_required"])
    status = (
        "ready_to_record_no_charge_rehearsal"
        if not blocked_external and blocked_count == 0
        else "blocked_for_external_prerequisites"
        if blocked_external
        else "blocked_for_final_rehearsal_evidence"
    )
    recommended_next_step = (
        "founder_finish_external_console_prerequisites"
        if blocked_external
        else "run_internal_no_real_charge_rehearsal"
        if blocked_count == 0 and attention_count > 0
        else "prepare_owner_live_cutover_approval"
        if owner_approval_ready
        else "keep_public_paid_launch_blocked"
    )
    return {
        "contract_version": "2026-06-21-final-launch-rehearsal-execution-record-v1",
        "audience": "platform_internal_admin",
        "mode": "sanitized_final_rehearsal_execution_record",
        "environment": settings.environment,
        "customer_visible": False,
        "status": status,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "recommended_next_step": recommended_next_step,
            "step_count": len(execution_steps),
            "ready_count": ready_count,
            "blocked_count": blocked_count,
            "attention_count": attention_count,
            "external_blocker_count": len(blocked_external),
            "pending_internal_count": len(pending_internal),
            "latest_bundle": release_summary.get("latest_bundle") or "",
            "latest_bundle_sha256": release_summary.get("latest_bundle_sha256") or "",
            "frontend_asset_version": release_summary.get("current_frontend_asset_version") or "",
            "owner_review_status": owner_review_packet.get("status") or "unknown",
            "launch_rehearsal_audit_status": launch_rehearsal_audit_packet.get("status") or "unknown",
            "launch_rehearsal_blocked_count": _as_int(audit_summary.get("blocked_count")),
            "cutover_status": cutover_decision_checklist.get("status") or "unknown",
            "handoff_status": continuity_handoff_digest.get("status") or "unknown",
            "handoff_next_owner_step": handoff_summary.get("next_owner_step") or "",
            "operation_health_status": operational.get("status") or "unknown",
            "beta_ready": bool(summary.get("beta_ready")),
            "production_ready": bool(summary.get("production_ready")),
            "can_accept_real_customers": bool(summary.get("can_accept_real_customers")),
            "billing_ready_for_paid_launch": summary.get("mainland_payment_ready_for_owner_approval") is True,
            "mainland_payment_ready_for_owner_approval": (
                summary.get("mainland_payment_ready_for_owner_approval") is True
            ),
            "ebay_token_refresh_success_count": refresh_success_count,
            "public_paid_launch_allowed": False,
            "charge_now_allowed": False,
            "platform_write_now_allowed": False,
            "repeat_ebay_oauth_allowed": False,
            "secret_exposed": False,
        },
        "execution_steps": execution_steps,
        "remaining_external_blockers": [_final_rehearsal_action(item, source="external_blocker") for item in blocked_external[:8]],
        "remaining_internal_actions": [_final_rehearsal_action(item, source="internal_work_queue") for item in (pending_internal or internal_work_queue)[:8]],
        "rollback_controls": [
            {
                "key": "staging_patch_backup_pointer",
                "label": "Staging patch backup pointer",
                "status": "ready" if rollback_points else "attention_required",
                "tone": "green" if rollback_points else "amber",
                "evidence_summary": f"rollback_points={len(rollback_points)}",
                "next_action": "Keep the latest backup pointer before each production-adjacent deploy.",
                "customer_visible": False,
                "secret_exposed": False,
            },
            {
                "key": "latest_bundle_sha256",
                "label": "Latest bundle SHA256",
                "status": "ready" if bundle_ready else "attention_required",
                "tone": "green" if bundle_ready else "amber",
                "evidence_summary": f"sha256={release_summary.get('latest_bundle_sha256') or 'missing'}",
                "next_action": "Attach the fresh public staging bundle manifest to the rehearsal record.",
                "customer_visible": False,
                "secret_exposed": False,
            },
            {
                "key": "readiness_public_launch_hold",
                "label": "Public launch hold",
                "status": "ready",
                "tone": "green",
                "evidence_summary": "public_paid_launch_allowed=false; charge_now_allowed=false; platform_write_now_allowed=false",
                "next_action": "Do not lift the hold until final owner approval.",
                "customer_visible": False,
                "secret_exposed": False,
            },
        ],
        "proof_links": [
            {"label": "health", "url": "https://app.jiejing.shop/health"},
            {"label": "deep_health", "url": "https://app.jiejing.shop/health/deep"},
            {"label": "readiness", "url": "https://app.jiejing.shop/readiness/product-saas"},
            {"label": "owner_launch_control", "url": "/owner/launch-control"},
            {"label": "release_history", "url": "/owner/launch-control release_history"},
        ],
        "release_check_index": {
            key: {
                "status": str(item.get("status") or "unknown")[:80],
                "evidence_summary": str(item.get("evidence_summary") or "")[:520],
                "next_action": str(item.get("next_action") or "")[:520],
                "secret_exposed": False,
            }
            for key, item in release_check_by_key.items()
        },
        "safety": _final_launch_rehearsal_safety_flags(),
        "download_allowed_for_internal_admin": True,
        "exports_database": False,
        "exports_raw_secret": False,
        "includes_raw_tokens": False,
        "includes_payment_secret": False,
        "reads_env_secret_values": False,
        "calls_stripe_api": False,
        "creates_checkout_session": False,
        "triggers_real_charge": False,
        "charge_now_allowed": False,
        "triggers_ebay_oauth": False,
        "repeat_ebay_oauth_allowed": False,
        "triggers_real_platform_write": False,
        "platform_write_now_allowed": False,
        "frontend_gets_secret": False,
        "frontend_gets_payment_secret": False,
        "frontend_gets_ebay_token": False,
        "secret_exposed": False,
    }


def _final_rehearsal_step(
    key: str,
    label: str,
    status: str,
    evidence: str,
    next_action: str,
    *,
    source_endpoint: str,
) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "status": status,
        "tone": _tone(status),
        "evidence_summary": str(evidence or "")[:520],
        "next_action": str(next_action or "")[:520],
        "source_endpoint": str(source_endpoint or "/owner/launch-control")[:180],
        "customer_visible": False,
        "exports_database": False,
        "exports_raw_secret": False,
        "includes_raw_tokens": False,
        "includes_payment_secret": False,
        "calls_stripe_api": False,
        "creates_checkout_session": False,
        "triggers_real_charge": False,
        "triggers_ebay_oauth": False,
        "triggers_real_platform_write": False,
        "frontend_gets_secret": False,
        "secret_exposed": False,
    }


def _final_rehearsal_action(item: dict[str, Any], *, source: str) -> dict[str, Any]:
    return {
        "key": str(item.get("key") or source)[:120],
        "label": str(item.get("label") or item.get("title") or item.get("key") or source)[:180],
        "status": str(item.get("status") or "attention_required")[:80],
        "tone": str(item.get("tone") or _tone(str(item.get("status") or "")))[:40],
        "owner": str(item.get("owner") or ("founder_operator" if source == "external_blocker" else "codex_or_platform_ops"))[:80],
        "evidence_summary": str(item.get("evidence_summary") or item.get("detail") or item.get("evidence") or "")[:520],
        "next_action": str(item.get("next_action") or item.get("verification") or "Review current owner launch-control evidence.")[:520],
        "source": source,
        "source_endpoint": str(item.get("source_endpoint") or "/owner/launch-control")[:180],
        "external_console_required": bool(item.get("external_console_required") or source == "external_blocker"),
        "customer_visible": False,
        "exports_database": False,
        "exports_raw_secret": False,
        "includes_raw_tokens": False,
        "includes_payment_secret": False,
        "calls_stripe_api": False,
        "creates_checkout_session": False,
        "triggers_real_charge": False,
        "triggers_ebay_oauth": False,
        "repeat_ebay_oauth_allowed": False,
        "triggers_real_platform_write": False,
        "frontend_gets_secret": False,
        "secret_exposed": False,
    }


def _final_launch_rehearsal_safety_flags() -> dict[str, bool]:
    return {
        "read_only": True,
        "platform_internal_admin_only": True,
        "customer_visible": False,
        "download_allowed_for_internal_admin": True,
        "exports_database": False,
        "exports_raw_secret": False,
        "includes_raw_tokens": False,
        "includes_payment_secret": False,
        "reads_env_secret_values": False,
        "calls_stripe_api": False,
        "creates_checkout_session": False,
        "triggers_real_charge": False,
        "charge_now_allowed": False,
        "triggers_ebay_oauth": False,
        "repeat_ebay_oauth_allowed": False,
        "triggers_real_platform_write": False,
        "platform_write_now_allowed": False,
        "frontend_gets_secret": False,
        "frontend_gets_payment_secret": False,
        "frontend_gets_ebay_token": False,
        "secret_exposed": False,
    }


def _dossier_evidence(**items: Any) -> str:
    parts: list[str] = []
    for key, value in items.items():
        normalized = str(value).replace("\n", " ").replace("\r", " ")
        parts.append(f"{key}={normalized[:180]}")
    return "; ".join(parts)[:900]


def _owner_paid_launch_approval_dossier(
    *,
    settings: SaaSSettings,
    summary: dict[str, Any],
    evidence_summary: dict[str, Any],
    billing_cutover: dict[str, Any],
    paid_packet: dict[str, Any],
    launch_rehearsal_audit_packet: dict[str, Any],
    final_launch_rehearsal_execution_record: dict[str, Any],
    external_blockers: list[dict[str, Any]],
    internal_work_queue: list[dict[str, Any]],
) -> dict[str, Any]:
    readiness = evidence_summary.get("readiness") if isinstance(evidence_summary.get("readiness"), dict) else {}
    ebay = evidence_summary.get("ebay") if isinstance(evidence_summary.get("ebay"), dict) else {}
    billing = evidence_summary.get("billing") if isinstance(evidence_summary.get("billing"), dict) else {}
    paid_summary = paid_packet.get("summary") if isinstance(paid_packet.get("summary"), dict) else {}
    billing_summary = billing_cutover.get("summary") if isinstance(billing_cutover.get("summary"), dict) else {}
    no_charge_packet = (
        billing_cutover.get("no_charge_live_domain_evidence_packet")
        if isinstance(billing_cutover.get("no_charge_live_domain_evidence_packet"), dict)
        else {}
    )
    no_charge_summary = no_charge_packet.get("summary") if isinstance(no_charge_packet.get("summary"), dict) else {}
    no_charge_items = no_charge_packet.get("evidence_items") if isinstance(no_charge_packet.get("evidence_items"), list) else []
    audit_summary = (
        launch_rehearsal_audit_packet.get("summary")
        if isinstance(launch_rehearsal_audit_packet.get("summary"), dict)
        else {}
    )
    final_summary = (
        final_launch_rehearsal_execution_record.get("summary")
        if isinstance(final_launch_rehearsal_execution_record.get("summary"), dict)
        else {}
    )
    refresh_success_count = _as_int(ebay.get("refresh_success_count") or summary.get("ebay_token_refresh_success_count"))
    blocked_external = [item for item in external_blockers if item.get("status") != "ready"]
    pending_internal = [item for item in internal_work_queue if item.get("status") not in {"ready", "done"}]
    sections = [
        _approval_dossier_section(
            "public_readiness_truth",
            "Public readiness truth",
            "ready" if bool(summary.get("production_ready")) and bool(summary.get("can_accept_real_customers")) else "blocked",
            _dossier_evidence(
                beta_ready=bool(summary.get("beta_ready")),
                production_ready=bool(summary.get("production_ready")),
                can_accept_real_customers=bool(summary.get("can_accept_real_customers")),
                warnings=_as_int(readiness.get("warning_count") or summary.get("warning_count")),
                public_paid_launch_allowed=False,
            ),
            "Keep public paid launch blocked until readiness returns production_ready=true and can_accept_real_customers=true.",
            source_endpoint="/readiness/product-saas",
        ),
        _approval_dossier_section(
            "mainland_payment_truth",
            "Mainland WeChat Native payment truth",
            "ready"
            if summary.get("mainland_payment_ready_for_owner_approval") is True
            else "blocked",
            _dossier_evidence(
                provider=billing.get("provider") or summary.get("billing_provider") or "not_selected",
                mainland_payment_ready_for_owner_approval=(
                    summary.get("mainland_payment_ready_for_owner_approval") is True
                ),
                cutover_status=billing_cutover.get("status") or "unknown",
                cutover_ready=f"{billing_summary.get('ready_count', 0)}/{billing_summary.get('total_count', 0)}",
                creates_checkout_session=False,
                charge_now_allowed=False,
            ),
            billing_summary.get("next_action")
            or "Finish WeChat Native credentials, signed callbacks, query, refund and controlled acceptance before charging.",
            source_endpoint="/owner/paid-launch-approval-packet",
        ),
        _approval_dossier_section(
            "no_charge_live_domain_evidence",
            "No-charge live-domain evidence packet",
            "ready" if no_charge_packet.get("status") == "ready" else "blocked",
            _dossier_evidence(
                packet=no_charge_packet.get("contract_version") or "missing",
                status=no_charge_packet.get("status") or "missing",
                ready=f"{no_charge_summary.get('ready_count', 0)}/{no_charge_summary.get('total_count', 0)}",
                blocked=",".join([str(item) for item in no_charge_summary.get("blocked_keys") or [] if str(item)]),
            ),
            "Complete all no-charge live-domain smoke, webhook, readiness, secret-scan, browser-smoke and rollback evidence flags.",
            source_endpoint="/owner/paid-launch-approval-packet no_charge_launch_rehearsal",
            evidence_items=_approval_dossier_evidence_items(no_charge_items),
        ),
        _approval_dossier_section(
            "new_ebay_account_refresh_proof",
            "Clean new eBay account refresh proof",
            "ready" if refresh_success_count > 0 else "blocked",
            _dossier_evidence(
                latest_packet=ebay.get("latest_packet_id") or summary.get("latest_official_ebay_packet_id") or "missing",
                refresh_success=refresh_success_count,
                old_frozen_account_reuse_allowed=False,
                repeat_ebay_oauth_allowed=False,
            ),
            "Wait for a clean new eBay account and backend-only refresh proof; do not repeat OAuth on the frozen account.",
            source_endpoint="/readiness/product-saas",
        ),
        _approval_dossier_section(
            "paid_launch_packet_truth",
            "Paid launch approval packet truth",
            "ready" if paid_packet.get("ready_for_owner_approval") is True else "blocked",
            _dossier_evidence(
                packet=paid_packet.get("contract_version") or "missing",
                status=paid_packet.get("status") or "unknown",
                ready=f"{paid_summary.get('ready_count', 0)}/{paid_summary.get('total_count', 0)}",
                blocked=",".join([str(item) for item in paid_summary.get("blocked_keys") or [] if str(item)]),
                no_charge_evidence_packet_status=paid_summary.get("no_charge_evidence_packet_status") or "unknown",
            ),
            paid_summary.get("next_step") or "Keep the paid launch approval packet blocked until domain, billing, no-charge and new eBay account proofs are complete.",
            source_endpoint="/owner/paid-launch-approval-packet",
        ),
        _approval_dossier_section(
            "final_rehearsal_and_rollback",
            "Final rehearsal and rollback evidence",
            "ready"
            if _as_int(final_summary.get("blocked_count")) == 0 and launch_rehearsal_audit_packet.get("status") == "ready_for_owner_approval"
            else "blocked",
            _dossier_evidence(
                final_status=final_launch_rehearsal_execution_record.get("status") or "unknown",
                final_ready=f"{final_summary.get('ready_count', 0)}/{final_summary.get('step_count', 0)}",
                final_blocked=_as_int(final_summary.get("blocked_count")),
                audit_status=launch_rehearsal_audit_packet.get("status") or "unknown",
                audit_blocked=_as_int(audit_summary.get("blocked_count")),
            ),
            "Attach final no-real-charge rehearsal, rollback pointer, secret scan, browser smoke and readiness snapshots before owner approval.",
            source_endpoint="/owner/launch-control final_launch_rehearsal_execution_record",
        ),
    ]
    blocked = [item for item in sections if item.get("status") != "ready"]
    ready_count = len(sections) - len(blocked)
    status = "ready_for_owner_review" if not blocked and not blocked_external and not pending_internal else "blocked"
    next_step = (
        str((blocked[0] if blocked else {}).get("key") or "")
        or str((blocked_external[0] if blocked_external else {}).get("key") or "")
        or str((pending_internal[0] if pending_internal else {}).get("key") or "")
        or "founder_owner_approval"
    )
    return {
        "contract_version": "2026-07-02-owner-paid-launch-approval-dossier-v1",
        "audience": "platform_internal_admin",
        "mode": "internal_admin_read_only_no_charge_no_write",
        "environment": settings.environment,
        "customer_visible": False,
        "merchant_surface_safe": True,
        "ordinary_merchant_visible": False,
        "status": status,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "decision": "do_not_enable_paid_public_launch_yet" if blocked or blocked_external else "ready_for_founder_owner_cutover_review",
            "ready_count": ready_count,
            "blocked_count": len(blocked),
            "section_count": len(sections),
            "external_blocker_count": len(blocked_external),
            "pending_internal_count": len(pending_internal),
            "readiness_score_percent": int(round((ready_count / max(len(sections), 1)) * 100)),
            "blocked_keys": [str(item.get("key") or "") for item in blocked],
            "next_step": next_step,
            "beta_ready": bool(summary.get("beta_ready")),
            "production_ready": bool(summary.get("production_ready")),
            "can_accept_real_customers": bool(summary.get("can_accept_real_customers")),
            "billing_provider": billing.get("provider") or summary.get("billing_provider") or "not_selected",
            "billing_ready_for_paid_launch": summary.get("mainland_payment_ready_for_owner_approval") is True,
            "mainland_payment_ready_for_owner_approval": (
                summary.get("mainland_payment_ready_for_owner_approval") is True
            ),
            "no_charge_evidence_packet_status": no_charge_packet.get("status") or "missing",
            "no_charge_evidence_ready_count": _as_int(no_charge_summary.get("ready_count")),
            "no_charge_evidence_total_count": _as_int(no_charge_summary.get("total_count")),
            "ebay_token_refresh_success_count": refresh_success_count,
            "public_paid_launch_allowed": False,
            "charge_now_allowed": False,
            "platform_write_now_allowed": False,
            "repeat_ebay_oauth_allowed": False,
            "secret_exposed": False,
        },
        "sections": sections,
        "no_charge_evidence_items": _approval_dossier_evidence_items(no_charge_items),
        "remaining_external_blockers": [_final_rehearsal_action(item, source="external_blocker") for item in blocked_external[:8]],
        "remaining_internal_actions": [_final_rehearsal_action(item, source="internal_work_queue") for item in (pending_internal or internal_work_queue)[:8]],
        "proof_links": [
            {"label": "health", "url": "https://app.jiejing.shop/health"},
            {"label": "deep_health", "url": "https://app.jiejing.shop/health/deep"},
            {"label": "readiness", "url": "https://app.jiejing.shop/readiness/product-saas"},
            {"label": "mainland_payment_approval", "url": "/owner/paid-launch-approval-packet"},
            {"label": "paid_launch_approval_packet", "url": "/owner/paid-launch-approval-packet"},
            {"label": "owner_launch_control", "url": "/owner/launch-control"},
        ],
        "safety": _owner_paid_launch_approval_dossier_safety_flags(),
        "download_allowed_for_internal_admin": True,
        "exports_database": False,
        "exports_raw_secret": False,
        "includes_raw_tokens": False,
        "includes_payment_secret": False,
        "reads_env_secret_values": False,
        "calls_stripe_api": False,
        "creates_checkout_session": False,
        "triggers_real_charge": False,
        "charge_now_allowed": False,
        "triggers_ebay_oauth": False,
        "repeat_ebay_oauth_allowed": False,
        "triggers_real_platform_write": False,
        "platform_write_now_allowed": False,
        "frontend_gets_secret": False,
        "frontend_gets_payment_secret": False,
        "frontend_gets_ebay_token": False,
        "secret_exposed": False,
    }


def _approval_dossier_section(
    key: str,
    label: str,
    status: str,
    evidence: str,
    next_action: str,
    *,
    source_endpoint: str,
    evidence_items: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "status": status,
        "tone": _tone(status),
        "evidence_summary": str(evidence or "")[:720],
        "next_action": str(next_action or "")[:720],
        "source_endpoint": str(source_endpoint or "/owner/launch-control")[:220],
        "evidence_items": evidence_items or [],
        "customer_visible": False,
        "ordinary_merchant_visible": False,
        "exports_database": False,
        "exports_raw_secret": False,
        "includes_raw_tokens": False,
        "includes_payment_secret": False,
        "calls_stripe_api": False,
        "creates_checkout_session": False,
        "triggers_real_charge": False,
        "charge_now_allowed": False,
        "triggers_ebay_oauth": False,
        "repeat_ebay_oauth_allowed": False,
        "triggers_real_platform_write": False,
        "platform_write_now_allowed": False,
        "frontend_gets_secret": False,
        "frontend_gets_payment_secret": False,
        "frontend_gets_ebay_token": False,
        "secret_exposed": False,
    }


def _approval_dossier_evidence_items(items: list[Any]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for item in items[:12]:
        if not isinstance(item, dict):
            continue
        verification = item.get("verification") if isinstance(item.get("verification"), list) else []
        output.append(
            {
                "key": str(item.get("key") or "")[:140],
                "title": str(item.get("title") or item.get("label") or item.get("key") or "")[:180],
                "status": str(item.get("status") or "unknown")[:80],
                "severity": str(item.get("severity") or "")[:80],
                "source": str(item.get("source") or "")[:160],
                "evidence_summary": str(item.get("evidence_summary") or "")[:520],
                "verification": [str(value)[:180] for value in verification[:6] if value],
                "customer_visible": False,
                "ordinary_merchant_visible": False,
                "exports_raw_secret": False,
                "includes_raw_tokens": False,
                "includes_payment_secret": False,
                "calls_stripe_api": False,
                "creates_checkout_session": False,
                "triggers_real_charge": False,
                "charge_now_allowed": False,
                "triggers_ebay_oauth": False,
                "repeat_ebay_oauth_allowed": False,
                "triggers_real_platform_write": False,
                "platform_write_now_allowed": False,
                "frontend_gets_payment_secret": False,
                "frontend_gets_ebay_token": False,
                "secret_exposed": False,
            }
        )
    return output


def _owner_paid_launch_approval_dossier_safety_flags() -> dict[str, bool]:
    return {
        "read_only": True,
        "platform_internal_admin_only": True,
        "customer_visible": False,
        "ordinary_merchant_visible": False,
        "merchant_surface_safe": True,
        "download_allowed_for_internal_admin": True,
        "exports_database": False,
        "exports_raw_secret": False,
        "includes_raw_tokens": False,
        "includes_payment_secret": False,
        "reads_env_secret_values": False,
        "calls_stripe_api": False,
        "creates_checkout_session": False,
        "triggers_real_charge": False,
        "charge_now_allowed": False,
        "triggers_ebay_oauth": False,
        "repeat_ebay_oauth_allowed": False,
        "triggers_real_platform_write": False,
        "platform_write_now_allowed": False,
        "frontend_gets_secret": False,
        "frontend_gets_payment_secret": False,
        "frontend_gets_ebay_token": False,
        "secret_exposed": False,
    }


def _prelaunch_acceptance_report(
    *,
    settings: SaaSSettings,
    summary: dict[str, Any],
    evidence_summary: dict[str, Any],
    owner_review_packet: dict[str, Any],
    launch_rehearsal_audit_packet: dict[str, Any],
    release_history: dict[str, Any],
    continuity_handoff_digest: dict[str, Any],
    cutover_decision_checklist: dict[str, Any],
    final_launch_rehearsal_execution_record: dict[str, Any],
    owner_paid_launch_approval_dossier: dict[str, Any],
    external_blockers: list[dict[str, Any]],
    internal_work_queue: list[dict[str, Any]],
) -> dict[str, Any]:
    readiness = evidence_summary.get("readiness") if isinstance(evidence_summary.get("readiness"), dict) else {}
    ebay = evidence_summary.get("ebay") if isinstance(evidence_summary.get("ebay"), dict) else {}
    billing = evidence_summary.get("billing") if isinstance(evidence_summary.get("billing"), dict) else {}
    edge = evidence_summary.get("edge") if isinstance(evidence_summary.get("edge"), dict) else {}
    operational = evidence_summary.get("operational") if isinstance(evidence_summary.get("operational"), dict) else {}
    release_summary = release_history.get("summary") if isinstance(release_history.get("summary"), dict) else {}
    final_summary = (
        final_launch_rehearsal_execution_record.get("summary")
        if isinstance(final_launch_rehearsal_execution_record.get("summary"), dict)
        else {}
    )
    dossier_summary = (
        owner_paid_launch_approval_dossier.get("summary")
        if isinstance(owner_paid_launch_approval_dossier.get("summary"), dict)
        else {}
    )
    blocked_external = [item for item in external_blockers if item.get("status") != "ready"]
    pending_internal = [item for item in internal_work_queue if item.get("status") not in {"ready", "done"}]
    refresh_success_count = _as_int(ebay.get("refresh_success_count") or summary.get("ebay_token_refresh_success_count"))
    report_items = [
        _prelaunch_report_item(
            "public_entry_and_domain",
            "Public entry and stable domain",
            "ready" if bool(summary.get("stable_domain_ready") or edge.get("callbacks_ready")) else "attention_required",
            f"app=https://app.jiejing.shop; edge_status={edge.get('status') or 'unknown'}; waf_ready={bool(edge.get('waf_ready'))}; callbacks_ready={bool(edge.get('callbacks_ready'))}; origin_locked={bool(edge.get('origin_locked'))}",
            "Keep app.jiejing.shop as the stable HTTPS entry and verify WAF/origin-lock posture before paid launch.",
        ),
        _prelaunch_report_item(
            "operational_health",
            "Operational health",
            "ready" if operational.get("status") == "ready" else "attention_required",
            f"operational_status={operational.get('status') or 'unknown'}; database_queue_worker_public_summary_ready=true",
            "Recheck /health and /health/deep immediately before owner approval.",
        ),
        _prelaunch_report_item(
            "billing_provider",
            "Billing provider and quota",
            "blocked"
            if summary.get("mainland_payment_ready_for_owner_approval") is not True
            else "ready",
            f"provider={billing.get('provider') or summary.get('billing_provider') or 'not_selected'}; owner_ready={summary.get('mainland_payment_ready_for_owner_approval') is True}; charge_now_allowed=false",
            "Complete WeChat Native credentials, signed callbacks, query, refund and controlled acceptance before any real merchant charge.",
        ),
        _prelaunch_report_item(
            "ebay_refresh_proof",
            "eBay clean account refresh proof",
            "blocked" if refresh_success_count <= 0 else "ready",
            f"latest_packet={ebay.get('latest_packet_id') or summary.get('latest_official_ebay_packet_id') or 'missing'}; refresh_success={refresh_success_count}; repeat_ebay_oauth_allowed=false",
            "Wait for a clean new eBay account; do not reuse the frozen account or repeat OAuth now.",
        ),
        _prelaunch_report_item(
            "confirmation_center_boundary",
            "Confirmation center boundary",
            "ready",
            "real platform writes remain confirmation-gated; price/inventory/refund/ads/policy/customer-sensitive promises require confirmation center.",
            "Keep all high-risk actions behind human approval even after paid launch.",
        ),
        _prelaunch_report_item(
            "secret_and_data_boundary",
            "Secret and data boundary",
            "ready" if not bool(summary.get("secret_exposed")) else "blocked",
            "secret_exposed=false; frontend_gets_secret=false; database_export_allowed=false",
            "Keep BYOK, eBay tokens, refresh tokens, client secrets and payment secrets inside backend/Vault boundaries.",
        ),
        _prelaunch_report_item(
            "release_artifact_and_rollback",
            "Release artifact and rollback",
            "ready" if release_summary.get("latest_bundle_sha256") else "attention_required",
            f"bundle={release_summary.get('latest_bundle') or 'missing'}; sha256={release_summary.get('latest_bundle_sha256') or 'missing'}; rollback_points={release_summary.get('rollback_point_count') or 0}",
            "Keep a fresh bundle manifest, SHA256 and rollback pointer for every production-adjacent deploy.",
        ),
        _prelaunch_report_item(
            "final_rehearsal_record",
            "Final rehearsal record",
            "blocked" if _as_int(final_summary.get("blocked_count")) > 0 else "attention_required",
            f"status={final_launch_rehearsal_execution_record.get('status') or 'unknown'}; ready={_as_int(final_summary.get('ready_count'))}/{_as_int(final_summary.get('step_count'))}; blocked={_as_int(final_summary.get('blocked_count'))}; attention={_as_int(final_summary.get('attention_count'))}",
            "Attach final no-real-charge rehearsal evidence after external billing and clean eBay prerequisites are complete.",
        ),
        _prelaunch_report_item(
            "owner_paid_launch_approval_dossier",
            "Owner paid launch approval dossier",
            "ready" if owner_paid_launch_approval_dossier.get("status") == "ready_for_owner_review" else "blocked",
            f"status={owner_paid_launch_approval_dossier.get('status') or 'unknown'}; score={_as_int(dossier_summary.get('readiness_score_percent'))}%; ready={_as_int(dossier_summary.get('ready_count'))}/{_as_int(dossier_summary.get('section_count'))}; blocked={_as_int(dossier_summary.get('blocked_count'))}; no_charge={dossier_summary.get('no_charge_evidence_packet_status') or 'unknown'}",
            "Use the internal approval dossier as the final owner decision material; keep it hidden from ordinary merchant accounts.",
        ),
    ]
    ready_count = len([item for item in report_items if item.get("status") == "ready"])
    blocked_count = len([item for item in report_items if item.get("status") == "blocked"])
    attention_count = len([item for item in report_items if item.get("status") == "attention_required"])
    readiness_score_percent = int(round((ready_count / max(len(report_items), 1)) * 100))
    public_paid_launch_allowed = False
    decision = "do_not_launch_paid_public_yet"
    status = "blocked_for_paid_public_launch" if blocked_count or blocked_external else "ready_for_no_real_charge_rehearsal_review"
    summary_block = {
        "decision": decision,
        "status": status,
        "readiness_score_percent": readiness_score_percent,
        "ready_count": ready_count,
        "blocked_count": blocked_count,
        "attention_count": attention_count,
        "report_item_count": len(report_items),
        "external_blocker_count": len(blocked_external),
        "pending_internal_count": len(pending_internal),
        "beta_ready": bool(summary.get("beta_ready")),
        "production_ready": bool(summary.get("production_ready")),
        "can_accept_real_customers": bool(summary.get("can_accept_real_customers")),
        "billing_provider": billing.get("provider") or summary.get("billing_provider") or "not_selected",
        "billing_ready_for_paid_launch": summary.get("mainland_payment_ready_for_owner_approval") is True,
        "mainland_payment_ready_for_owner_approval": (
            summary.get("mainland_payment_ready_for_owner_approval") is True
        ),
        "ebay_token_refresh_success_count": refresh_success_count,
        "latest_bundle": release_summary.get("latest_bundle") or "",
        "latest_bundle_sha256": release_summary.get("latest_bundle_sha256") or "",
        "frontend_asset_version": release_summary.get("current_frontend_asset_version") or "",
        "owner_review_status": owner_review_packet.get("status") or "unknown",
        "launch_rehearsal_audit_status": launch_rehearsal_audit_packet.get("status") or "unknown",
        "cutover_status": cutover_decision_checklist.get("status") or "unknown",
        "handoff_status": continuity_handoff_digest.get("status") or "unknown",
        "final_rehearsal_status": final_launch_rehearsal_execution_record.get("status") or "unknown",
        "owner_paid_launch_approval_dossier_status": owner_paid_launch_approval_dossier.get("status") or "unknown",
        "approval_dossier_blocked_count": _as_int(dossier_summary.get("blocked_count")),
        "public_paid_launch_allowed": public_paid_launch_allowed,
        "charge_now_allowed": False,
        "platform_write_now_allowed": False,
        "repeat_ebay_oauth_allowed": False,
        "secret_exposed": False,
    }
    founder_actions = [_prelaunch_report_action(item, source="external_blocker") for item in blocked_external[:8]]
    internal_actions = [_prelaunch_report_action(item, source="internal_work_queue") for item in (pending_internal or internal_work_queue)[:8]]
    report_markdown = _prelaunch_report_markdown(
        settings=settings,
        summary=summary_block,
        report_items=report_items,
        founder_actions=founder_actions,
        internal_actions=internal_actions,
    )
    return {
        "contract_version": "2026-06-21-prelaunch-acceptance-report-v1",
        "audience": "platform_internal_admin",
        "mode": "sanitized_prelaunch_acceptance_report",
        "environment": settings.environment,
        "customer_visible": False,
        "status": status,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": summary_block,
        "report_items": report_items,
        "founder_required_actions": founder_actions,
        "codex_continue_actions": internal_actions,
        "decision_record": {
            "key": "paid_public_launch_decision",
            "decision": decision,
            "decision_label": "Do not launch paid public SaaS yet",
            "can_continue_private_beta": bool(summary.get("beta_ready")) and not bool(summary.get("secret_exposed")),
            "paid_public_launch_allowed": public_paid_launch_allowed,
            "primary_blockers": [
                item.get("label") or item.get("key")
                for item in report_items
                if isinstance(item, dict) and item.get("status") == "blocked"
            ],
            "next_safe_step": founder_actions[0]["next_action"] if founder_actions else "Continue internal no-real-charge rehearsal evidence.",
            "customer_visible": False,
            "secret_exposed": False,
        },
        "proof_links": [
            {"label": "health", "url": "https://app.jiejing.shop/health"},
            {"label": "deep_health", "url": "https://app.jiejing.shop/health/deep"},
            {"label": "readiness", "url": "https://app.jiejing.shop/readiness/product-saas"},
            {"label": "owner_launch_control", "url": "/owner/launch-control"},
        ],
        "report_markdown": report_markdown,
        "safety": _prelaunch_acceptance_report_safety_flags(),
        "download_allowed_for_internal_admin": True,
        "exports_database": False,
        "exports_raw_secret": False,
        "includes_raw_tokens": False,
        "includes_payment_secret": False,
        "reads_env_secret_values": False,
        "calls_stripe_api": False,
        "creates_checkout_session": False,
        "triggers_real_charge": False,
        "charge_now_allowed": False,
        "triggers_ebay_oauth": False,
        "repeat_ebay_oauth_allowed": False,
        "triggers_real_platform_write": False,
        "platform_write_now_allowed": False,
        "frontend_gets_secret": False,
        "frontend_gets_payment_secret": False,
        "frontend_gets_ebay_token": False,
        "secret_exposed": False,
    }


def _prelaunch_report_item(key: str, label: str, status: str, evidence: str, next_action: str) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "status": status,
        "tone": _tone(status),
        "evidence_summary": str(evidence or "")[:620],
        "next_action": str(next_action or "")[:620],
        "customer_visible": False,
        "exports_database": False,
        "exports_raw_secret": False,
        "includes_raw_tokens": False,
        "includes_payment_secret": False,
        "calls_stripe_api": False,
        "creates_checkout_session": False,
        "triggers_real_charge": False,
        "triggers_ebay_oauth": False,
        "triggers_real_platform_write": False,
        "frontend_gets_secret": False,
        "secret_exposed": False,
    }


def _prelaunch_report_action(item: dict[str, Any], *, source: str) -> dict[str, Any]:
    return {
        "key": str(item.get("key") or source)[:120],
        "label": str(item.get("label") or item.get("title") or item.get("key") or source)[:180],
        "status": str(item.get("status") or "attention_required")[:80],
        "tone": str(item.get("tone") or _tone(str(item.get("status") or "")))[:40],
        "owner": str(item.get("owner") or ("founder_operator" if source == "external_blocker" else "codex_or_platform_ops"))[:80],
        "evidence_summary": str(item.get("evidence_summary") or item.get("detail") or item.get("evidence") or "")[:620],
        "next_action": str(item.get("next_action") or item.get("verification") or "Review current owner launch-control evidence.")[:620],
        "source": source,
        "source_endpoint": str(item.get("source_endpoint") or "/owner/launch-control")[:180],
        "external_console_required": bool(item.get("external_console_required") or source == "external_blocker"),
        "customer_visible": False,
        "exports_database": False,
        "exports_raw_secret": False,
        "includes_raw_tokens": False,
        "includes_payment_secret": False,
        "calls_stripe_api": False,
        "creates_checkout_session": False,
        "triggers_real_charge": False,
        "triggers_ebay_oauth": False,
        "repeat_ebay_oauth_allowed": False,
        "triggers_real_platform_write": False,
        "frontend_gets_secret": False,
        "secret_exposed": False,
    }


def _prelaunch_report_markdown(
    *,
    settings: SaaSSettings,
    summary: dict[str, Any],
    report_items: list[dict[str, Any]],
    founder_actions: list[dict[str, Any]],
    internal_actions: list[dict[str, Any]],
) -> str:
    lines = [
        "# Jiejing prelaunch acceptance report",
        "",
        f"- environment: {settings.environment}",
        f"- decision: {summary.get('decision')}",
        f"- readiness_score_percent: {summary.get('readiness_score_percent')}",
        f"- beta_ready: {bool(summary.get('beta_ready'))}",
        f"- production_ready: {bool(summary.get('production_ready'))}",
        f"- can_accept_real_customers: {bool(summary.get('can_accept_real_customers'))}",
        f"- billing_provider: {summary.get('billing_provider')}",
        f"- mainland_payment_ready_for_owner_approval: {summary.get('mainland_payment_ready_for_owner_approval') is True}",
        f"- ebay_token_refresh_success_count: {_as_int(summary.get('ebay_token_refresh_success_count'))}",
        f"- public_paid_launch_allowed: {bool(summary.get('public_paid_launch_allowed'))}",
        f"- charge_now_allowed: {bool(summary.get('charge_now_allowed'))}",
        f"- platform_write_now_allowed: {bool(summary.get('platform_write_now_allowed'))}",
        f"- repeat_ebay_oauth_allowed: {bool(summary.get('repeat_ebay_oauth_allowed'))}",
        f"- secret_exposed: {bool(summary.get('secret_exposed'))}",
        "",
        "## Acceptance checks",
    ]
    for item in report_items:
        lines.extend(
            [
                f"- [{str(item.get('status') or 'unknown').upper()}] {item.get('label') or item.get('key')}",
                f"  - evidence: {item.get('evidence_summary') or ''}",
                f"  - next_action: {item.get('next_action') or ''}",
            ]
        )
    lines.append("")
    lines.append("## Founder required actions")
    if founder_actions:
        for item in founder_actions:
            lines.append(f"- {item.get('label') or item.get('key')}: {item.get('next_action') or ''}")
    else:
        lines.append("- none recorded")
    lines.append("")
    lines.append("## Codex/platform actions")
    if internal_actions:
        for item in internal_actions:
            lines.append(f"- {item.get('label') or item.get('key')}: {item.get('next_action') or ''}")
    else:
        lines.append("- routine smoke, secret scan and release evidence only")
    lines.append("")
    lines.append("## No-go boundary")
    lines.extend(
        [
            "- Do not create a payable QR or call a live payment provider from this report.",
            "- Do not run or repeat eBay OAuth until a clean new eBay account is ready.",
            "- Do not perform real eBay writes, price, inventory, refund, ad, policy or sensitive customer-promise actions outside confirmation center.",
            "- Do not export database rows, raw secrets, eBay tokens, refresh tokens, model keys, API keys or payment secrets.",
        ]
    )
    return "\n".join(lines)[:12000]


def _prelaunch_acceptance_report_safety_flags() -> dict[str, bool]:
    return {
        "read_only": True,
        "platform_internal_admin_only": True,
        "customer_visible": False,
        "download_allowed_for_internal_admin": True,
        "exports_database": False,
        "exports_raw_secret": False,
        "includes_raw_tokens": False,
        "includes_payment_secret": False,
        "reads_env_secret_values": False,
        "calls_stripe_api": False,
        "creates_checkout_session": False,
        "triggers_real_charge": False,
        "charge_now_allowed": False,
        "triggers_ebay_oauth": False,
        "repeat_ebay_oauth_allowed": False,
        "triggers_real_platform_write": False,
        "platform_write_now_allowed": False,
        "frontend_gets_secret": False,
        "frontend_gets_payment_secret": False,
        "frontend_gets_ebay_token": False,
        "secret_exposed": False,
    }


def _read_json_file(path: Path) -> dict[str, Any]:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
        return loaded if isinstance(loaded, dict) else {}
    except Exception:
        return {}


def _mtime_iso(path: Path) -> str:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()
    except Exception:
        return ""


def _current_frontend_asset_version() -> str:
    for path in (Path("app.html"), Path("index.html")):
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        marker = "?v="
        if marker in text:
            value = text.split(marker, 1)[1].split('"', 1)[0].split("'", 1)[0].split("&", 1)[0]
            if value:
                return value[:80]
    return ""


def _load_fixed_progress_release_evidence(root: Path | None = None) -> dict[str, Any]:
    """Load only release evidence that is bound to the currently deployed frontend."""

    project_root = root or Path(__file__).resolve().parents[1]
    evidence = _read_json_file(project_root / "deploy" / "release-evidence.json")
    expected_version = str(evidence.get("frontend_asset_version") or "")[:80]
    current_version = ""
    for path in (project_root / "index.html", project_root / "app.html"):
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        if expected_version and expected_version in text:
            current_version = expected_version
            break

    browser_smoke_passed = (
        evidence.get("contract_version") == FIXED_PROGRESS_RELEASE_EVIDENCE_CONTRACT
        and bool(expected_version)
        and current_version == expected_version
        and evidence.get("precloud_gate_passed") is True
        and evidence.get("local_browser_smoke_passed") is True
        and evidence.get("public_browser_smoke_passed") is True
        and evidence.get("secret_scan_passed") is True
    )
    return {
        "contract_version": FIXED_PROGRESS_RELEASE_EVIDENCE_CONTRACT,
        "frontend_asset_version": current_version,
        "browser_smoke_passed": browser_smoke_passed,
        "public_domain_tls_passed": browser_smoke_passed,
        "real_merchant_workflow_validation_passed": False,
        "manual_real_merchant_validation_flag_ignored": True,
        "public_charging_approved": bool(evidence.get("public_charging_approved")),
        "secret_exposed": False,
    }


def _war_room(
    *,
    summary: dict[str, Any],
    lanes: list[dict[str, Any]],
    external_blockers: list[dict[str, Any]],
    internal_work_queue: list[dict[str, Any]],
    operations_observability: dict[str, Any],
    test_data_governance: dict[str, Any],
) -> dict[str, Any]:
    blocked_lanes = [item for item in lanes if item.get("status") != "ready"]
    blocked_external = [item for item in external_blockers if item.get("status") != "ready"]
    pending_internal = [item for item in internal_work_queue if item.get("status") not in {"ready", "done"}]
    return {
        "contract_version": "2026-06-20-owner-war-room-v3",
        "audience": "platform_internal_admin",
        "customer_visible": False,
        "status": "public_launch_blocked" if blocked_lanes or blocked_external else "ready_for_owner_approval",
        "sections": [
            _war_room_section(
                "entry_security",
                "Public entry and anti-scrape",
                "ready" if bool(summary.get("stable_domain_ready")) else "attention_required",
                f"edge={summary.get('edge_ready_count', 0)}/{summary.get('edge_total_count', 0)}; app_domain=app.jiejing.shop",
                "Verify free WAF/Bot rules, high-cost API limits and origin-lock evidence before real traffic.",
            ),
            _war_room_section(
                "billing_revenue",
                "Billing and revenue cutover",
                "ready"
                if summary.get("mainland_payment_ready_for_owner_approval") is True
                else "blocked",
                f"provider={summary.get('billing_provider') or 'unknown'}; cutover={summary.get('billing_cutover_status') or 'unknown'}",
                "WeChat Native credentials, signed callbacks, query, refund and controlled-acceptance proof are required before charging.",
            ),
            _war_room_section(
                "ebay_account",
                "eBay account and refresh proof",
                "ready" if _as_int(summary.get("ebay_token_refresh_success_count")) > 0 else "blocked",
                f"packet={summary.get('latest_official_ebay_packet_id') or 'missing'}; refresh_success={_as_int(summary.get('ebay_token_refresh_success_count'))}",
                "Do not reuse the frozen account. Wait for a clean eBay account before OAuth or low-risk smoke.",
            ),
            _war_room_section(
                "operations",
                "Database, queue and worker",
                "ready" if summary.get("worker_heartbeat_status") == "ready" else "attention_required",
                f"queue={summary.get('queue_provider') or 'unknown'}; worker={summary.get('worker_heartbeat_status') or 'unknown'}",
                "Keep /health/deep, queue lag, dead letters and worker heartbeat monitored after each deploy.",
            ),
            _war_room_section(
                "ops_observability",
                "Internal ops observability",
                "ready" if operations_observability.get("status") == "ready" else "attention_required",
                f"cards={_as_int((operations_observability.get('summary') or {}).get('card_count'))}; attention={_as_int((operations_observability.get('summary') or {}).get('attention_count'))}",
                (operations_observability.get("summary") or {}).get("next_action") or "Review ops evidence cards before deploy.",
            ),
            _war_room_section(
                "test_data",
                "Test data governance",
                "ready" if test_data_governance.get("status") == "no_test_data_detected" else "attention_required",
                f"scope={test_data_governance.get('scope') or 'unknown'}; candidates={_as_int(test_data_governance.get('candidate_count'))}; auto_delete=false",
                test_data_governance.get("next_action") or "Keep test data marked and isolated.",
            ),
            _war_room_section(
                "confirmation_center",
                "Confirmation center enforcement",
                "ready",
                "publish/payment/refund/price/inventory/ads/policy/customer promise must stop for approval",
                "Continue enriching approval cards with impact, evidence, rollback and audit context.",
            ),
        ],
        "counts": {
            "blocked_lanes": len(blocked_lanes),
            "blocked_external": len(blocked_external),
            "pending_internal": len(pending_internal),
            "test_data_candidates": _as_int(test_data_governance.get("candidate_count")),
        },
        "launch_decision": {
            "public_paid_launch_allowed": False,
            "can_accept_real_customers": bool(summary.get("can_accept_real_customers")),
            "charge_now_allowed": False,
            "platform_write_now_allowed": False,
            "repeat_ebay_oauth_allowed": False,
            "next_owner_decision": "Keep private beta until WeChat Native, a clean eBay account, refresh proof and no-charge rehearsal are complete.",
        },
        "secret_exposed": False,
    }


def _operations_observability(
    *,
    operational: dict[str, Any],
    backup: dict[str, Any],
    billing_usage: dict[str, Any],
    post_publish: dict[str, Any],
    test_data_governance: dict[str, Any],
) -> dict[str, Any]:
    queue = operational.get("queue_runtime") if isinstance(operational.get("queue_runtime"), dict) else {}
    worker = operational.get("worker_runtime") if isinstance(operational.get("worker_runtime"), dict) else {}
    shutdown = (
        billing_usage.get("subscription_quota_shutdown_state")
        if isinstance(billing_usage.get("subscription_quota_shutdown_state"), dict)
        else {}
    )
    post_safety = post_publish.get("safety") if isinstance(post_publish.get("safety"), dict) else {}
    cards = [
        _ops_card(
            "queue_worker_runtime",
            "Queue and worker runtime",
            "ready" if operational.get("status") == "ready" else "attention_required",
            "Operational health is read from /health/deep and company-scoped queue summaries.",
            f"queue_provider={queue.get('queue_provider') or worker.get('queue_provider') or 'unknown'}; queued={_as_int((queue.get('counts') or {}).get('queued'))}; running={_as_int((queue.get('counts') or {}).get('running'))}; dead_letter={_as_int((queue.get('counts') or {}).get('dead_letter'))}; worker={worker.get('heartbeat_status') or 'unknown'}",
            _operational_next_action(operational),
            "/health/deep",
        ),
        _ops_card(
            "backup_restore_drill",
            "Backup and restore drill",
            "ready" if bool(backup.get("backup_ready_for_paid_launch")) else "attention_required",
            "Backup evidence is read-only; it never exports merchant data or secrets.",
            f"ready={bool(backup.get('backup_ready_for_paid_launch'))}; blockers={len(backup.get('blockers') or [])}; restore_recorded={bool((backup.get('restore') or {}).get('restore_drill_recorded'))}",
            (backup.get("next_actions") or ["Keep managed backup, restore drill and alerts current."])[0],
            "/backup/plan",
        ),
        _ops_card(
            "high_cost_api_protection",
            "High-cost API protection",
            "ready",
            "Route-group limit evidence is operator-panel-only and separately exposed through /security/rate-limit/status.",
            "protected_groups=owner/post-publish/billing/model/reports/ebay-write; customer_visible=false; prevents_complete_copy=false; makes_scraping_costly=true",
            "Check /security/rate-limit/status after deploy and after any new expensive route is added.",
            "/security/rate-limit/status",
        ),
        _ops_card(
            "post_publish_dry_run",
            "Post-publish cockpit dry-run",
            "ready" if bool(post_publish.get("ready_for_ui")) and not _any_true(post_safety, ["triggers_real_platform_write", "triggers_ebay_oauth", "triggers_real_charge"]) else "attention_required",
            "Post-publish evidence can render without a real listing and stays confirmation-gated for cleanup.",
            f"status={post_publish.get('status') or 'unknown'}; published={bool(post_publish.get('published'))}; write={bool(post_safety.get('triggers_real_platform_write'))}; oauth={bool(post_safety.get('triggers_ebay_oauth'))}; charge={bool(post_safety.get('triggers_real_charge'))}",
            "After a clean new-account publish, verify 1h/24h/7d review windows and cleanup confirmation evidence.",
            "/post-publish/cockpit",
        ),
        _ops_card(
            "subscription_quota_shutdown",
            "Subscription and quota shutdown",
            "ready" if shutdown.get("merchant_visible") is True and shutdown.get("charge_now_allowed") is False else "attention_required",
            "Billing shutdown state is visible without calling a live payment provider or exposing payment secrets.",
            f"subscription={shutdown.get('subscription_status') or 'unknown'}; entitlement_active={bool(shutdown.get('entitlement_active'))}; quota_enabled={bool(shutdown.get('quota_enforcement_enabled'))}; blocked_units={_as_int(shutdown.get('blocked_units_count'))}",
            "Keep failed-payment, cancellation and quota hard-stop visible before live provider cutover.",
            "/billing/usage",
        ),
        _ops_card(
            "test_data_governance",
            "Test data governance",
            "ready" if test_data_governance.get("status") == "no_test_data_detected" else "attention_required",
            "Smoke records are current-company scoped; automatic deletion remains disabled.",
            f"scope={test_data_governance.get('scope') or 'unknown'}; candidates={_as_int(test_data_governance.get('candidate_count'))}; delete_now_allowed={bool((test_data_governance.get('cleanup_policy') or {}).get('delete_now_allowed'))}",
            test_data_governance.get("next_action") or "Keep smoke data marked and isolated.",
            "/owner/launch-control test_data_governance",
        ),
    ]
    attention = [card for card in cards if card.get("status") != "ready"]
    return {
        "contract_version": "2026-06-20-owner-ops-observability-v1",
        "audience": "platform_internal_admin",
        "customer_visible": False,
        "status": "ready" if not attention else "attention_required",
        "summary": {
            "card_count": len(cards),
            "attention_count": len(attention),
            "ready_count": len(cards) - len(attention),
            "next_action": attention[0]["next_action"] if attention else "Keep internal ops evidence refreshed after each deploy.",
            "secret_exposed": False,
        },
        "cards": cards,
        "safety": {
            "read_only": True,
            "calls_stripe_api": False,
            "creates_checkout_session": False,
            "triggers_real_charge": False,
            "triggers_ebay_oauth": False,
            "triggers_real_platform_write": False,
            "frontend_gets_secret": False,
            "customer_visible": False,
            "secret_exposed": False,
        },
        "secret_exposed": False,
    }


def _subscription_shutdown_control(
    *,
    billing: dict[str, Any],
    billing_usage: dict[str, Any],
) -> dict[str, Any]:
    closure = (
        billing.get("subscription_quota_shutdown_closure")
        if isinstance(billing.get("subscription_quota_shutdown_closure"), dict)
        else {}
    )
    usage_state = (
        billing_usage.get("subscription_quota_shutdown_state")
        if isinstance(billing_usage.get("subscription_quota_shutdown_state"), dict)
        else {}
    )
    operator_summary = closure.get("operator_summary") if isinstance(closure.get("operator_summary"), dict) else {}
    guards = closure.get("shutdown_guards") if isinstance(closure.get("shutdown_guards"), dict) else {}
    steps = [item for item in closure.get("steps", []) if isinstance(item, dict)]
    cards = [
        _subscription_shutdown_card(
            str(item.get("key") or "billing_shutdown_step"),
            str(item.get("title") or item.get("key") or "Billing shutdown step"),
            "ready" if item.get("status") == "ready" else "blocked",
            str(item.get("evidence_summary") or ""),
            str(item.get("next_action") or ""),
            "/billing/plans",
            owner_approval_required=bool(item.get("owner_approval_required")),
            external_resource_required=bool(item.get("external_resource_required")),
        )
        for item in steps
    ]
    cards.append(
        _subscription_shutdown_card(
            "current_company_shutdown_state",
            "Current company shutdown state",
            "ready" if usage_state.get("merchant_visible") is True and usage_state.get("charge_now_allowed") is False else "blocked",
            f"subscription={usage_state.get('subscription_status') or 'unknown'}; entitlement_active={bool(usage_state.get('entitlement_active'))}; blocks_metered_work_when_inactive={bool(usage_state.get('blocks_metered_work_when_inactive'))}; blocked_units={_as_int(usage_state.get('blocked_units_count'))}",
            "Keep merchant-visible usage after cancellation or failed payment, but block new metered work when entitlement is inactive.",
            "/billing/usage",
            owner_approval_required=False,
            external_resource_required=False,
        )
    )
    ready_count = sum(1 for card in cards if card.get("status") == "ready")
    attention = [card for card in cards if card.get("status") != "ready"]
    ready_for_no_charge = bool(closure.get("ready_for_no_charge_rehearsal"))
    ready_for_live = bool(closure.get("ready_for_live_cutover"))
    return {
        "contract_version": "2026-06-20-owner-subscription-shutdown-control-v1",
        "audience": "platform_internal_admin",
        "customer_visible": False,
        "status": "ready" if ready_for_no_charge or ready_for_live else "attention_required",
        "provider": closure.get("provider") or "not_selected",
        "mode": closure.get("mode") or "unknown",
        "ready_for_no_charge_rehearsal": ready_for_no_charge,
        "ready_for_live_cutover": ready_for_live,
        "summary": {
            "ready_count": ready_count,
            "card_count": len(cards),
            "attention_count": len(attention),
            "closure_ready_count": _as_int(closure.get("ready_count")),
            "closure_total_count": _as_int(closure.get("total_count")),
            "next_step": closure.get("next_step") or "",
            "next_action": operator_summary.get("next_action")
            or (attention[0]["next_action"] if attention else "Keep subscription shutdown rehearsal evidence current."),
            "secret_exposed": False,
        },
        "guards": guards,
        "current_state": usage_state,
        "cards": cards,
        "safety": {
            "read_only": True,
            "customer_visible": False,
            "public_charging_allowed": False,
            "calls_stripe_api": False,
            "creates_checkout_session": False,
            "triggers_real_charge": False,
            "charge_now_allowed": False,
            "triggers_ebay_oauth": False,
            "triggers_real_platform_write": False,
            "frontend_gets_payment_secret": False,
            "frontend_gets_api_key": False,
            "secret_exposed": False,
        },
        "secret_exposed": False,
    }


def _resilience_war_room(
    *,
    backup: dict[str, Any],
    monitoring: dict[str, Any],
    operational: dict[str, Any],
    billing_usage: dict[str, Any],
    post_publish: dict[str, Any],
    test_data_governance: dict[str, Any],
) -> dict[str, Any]:
    queue = operational.get("queue_runtime") if isinstance(operational.get("queue_runtime"), dict) else {}
    worker = operational.get("worker_runtime") if isinstance(operational.get("worker_runtime"), dict) else {}
    cls = monitoring.get("cloud_monitoring") if isinstance(monitoring.get("cloud_monitoring"), dict) else {}
    runbooks = monitoring.get("incident_runbooks") if isinstance(monitoring.get("incident_runbooks"), dict) else {}
    restore = backup.get("restore") if isinstance(backup.get("restore"), dict) else {}
    backup_alerts = backup.get("alerts") if isinstance(backup.get("alerts"), dict) else {}
    object_storage = backup.get("object_storage") if isinstance(backup.get("object_storage"), dict) else {}
    shutdown = (
        billing_usage.get("subscription_quota_shutdown_state")
        if isinstance(billing_usage.get("subscription_quota_shutdown_state"), dict)
        else {}
    )
    post_safety = post_publish.get("safety") if isinstance(post_publish.get("safety"), dict) else {}
    cards = [
        _resilience_card(
            "backup_restore_rehearsal",
            "Backup restore rehearsal",
            "ready" if bool(backup.get("backup_ready_for_paid_launch")) else "attention_required",
            "Restore evidence is status-only; it never exports database rows, Vault secrets or raw merchant files.",
            f"restore_recorded={bool(restore.get('restore_drill_recorded'))}; alerts={bool(backup_alerts.get('configured'))}; object_storage={bool(object_storage.get('target_ready'))}; blockers={len(backup.get('blockers') or [])}",
            (backup.get("next_actions") or ["Record recurring restore drill proof and backup alert owner."])[0],
            "/backup/plan",
        ),
        _resilience_card(
            "incident_runbook_coverage",
            "Incident runbook coverage",
            "ready" if bool(runbooks.get("runbook_ready")) else "attention_required",
            "Runbook coverage is internal-only and covers eBay, billing, backup, queue, model and post-publish failure paths.",
            f"ready={bool(runbooks.get('runbook_ready'))}; blocked={len(runbooks.get('blocked_by') or [])}; cover={len(runbooks.get('must_cover') or [])}",
            (runbooks.get("blocked_by") or ["Keep incident runbooks reviewed after each launch-gate change."])[0],
            "/monitoring/status",
        ),
        _resilience_card(
            "alert_route_and_cls",
            "Alert route and CLS target",
            "ready" if bool(monitoring.get("production_monitoring_ready")) else "attention_required",
            "Safe access logs and alert contracts are evidence-only; request bodies and authorization headers remain excluded.",
            f"cls_ready={bool(cls.get('target_ready'))}; safe_logs={bool((monitoring.get('safe_access_logs') or {}).get('enabled'))}; alerts={len(monitoring.get('alert_contracts') or [])}; blockers={len(monitoring.get('current_blockers') or [])}",
            (monitoring.get("current_blockers") or ["Keep OAuth/Vault/eBay/billing/backup alerts routed to an owner."])[0],
            "/monitoring/status",
        ),
        _resilience_card(
            "queue_worker_incident_mode",
            "Queue and worker incident mode",
            "ready" if operational.get("status") == "ready" else "attention_required",
            "Queue recovery evidence stays operational; it never retries high-risk writes without confirmation center boundaries.",
            f"queue_provider={queue.get('queue_provider') or worker.get('queue_provider') or 'unknown'}; stale={_as_int(queue.get('stale_running_count'))}; dead_letter={_as_int((queue.get('counts') or {}).get('dead_letter'))}; worker={worker.get('heartbeat_status') or 'unknown'}",
            _operational_next_action(operational),
            "/health/deep",
        ),
        _resilience_card(
            "billing_quota_incident_mode",
            "Billing and quota incident mode",
            "ready" if shutdown.get("merchant_visible") is True and shutdown.get("charge_now_allowed") is False else "attention_required",
            "Billing incidents can show entitlement/quota shutdown without creating a payable QR or calling a live payment provider.",
            f"merchant_visible={bool(shutdown.get('merchant_visible'))}; charge_now_allowed={bool(shutdown.get('charge_now_allowed'))}; quota_enabled={bool(shutdown.get('quota_enforcement_enabled'))}; blocked_units={_as_int(shutdown.get('blocked_units_count'))}",
            "Keep failed-payment, cancellation and quota hard-stop rehearsals current before live provider cutover.",
            "/billing/usage",
        ),
        _resilience_card(
            "ebay_write_incident_containment",
            "eBay write incident containment",
            "ready" if not _any_true(post_safety, ["triggers_real_platform_write", "triggers_ebay_oauth", "triggers_real_charge"]) else "attention_required",
            "Incident review is read-only; no OAuth retry, no publish retry and no cleanup write happens from this panel.",
            f"post_publish={post_publish.get('status') or 'unknown'}; oauth={bool(post_safety.get('triggers_ebay_oauth'))}; write={bool(post_safety.get('triggers_real_platform_write'))}; charge={bool(post_safety.get('triggers_real_charge'))}",
            "After a clean-account publish, keep ambiguous publish failures, 502s and cleanup actions confirmation-gated.",
            "/post-publish/cockpit",
        ),
        _resilience_card(
            "test_data_rollback_boundary",
            "Test data rollback boundary",
            "ready" if test_data_governance.get("status") == "no_test_data_detected" else "attention_required",
            "Rollback evidence is scoped to the current company; automatic cross-tenant deletion stays disabled.",
            f"scope={test_data_governance.get('scope') or 'unknown'}; candidates={_as_int(test_data_governance.get('candidate_count'))}; auto_delete={bool((test_data_governance.get('cleanup_policy') or {}).get('automatic_delete_allowed'))}",
            test_data_governance.get("next_action") or "Keep smoke data marked and isolated before any cleanup.",
            "/owner/launch-control test_data_governance",
        ),
    ]
    attention = [card for card in cards if card.get("status") != "ready"]
    return {
        "contract_version": "2026-06-20-owner-resilience-war-room-v1",
        "audience": "platform_internal_admin",
        "customer_visible": False,
        "status": "ready" if not attention else "attention_required",
        "summary": {
            "card_count": len(cards),
            "ready_count": len(cards) - len(attention),
            "attention_count": len(attention),
            "next_action": attention[0]["next_action"] if attention else "Keep restore drills, runbooks and alert routes reviewed after each deploy.",
            "secret_exposed": False,
        },
        "cards": cards,
        "safety": {
            "read_only": True,
            "exports_database": False,
            "exports_raw_secret": False,
            "calls_stripe_api": False,
            "creates_checkout_session": False,
            "triggers_real_charge": False,
            "triggers_ebay_oauth": False,
            "triggers_real_platform_write": False,
            "frontend_gets_secret": False,
            "customer_visible": False,
            "secret_exposed": False,
        },
        "secret_exposed": False,
    }


def _resilience_card(
    key: str,
    label: str,
    status: str,
    detail: str,
    evidence: str,
    next_action: str,
    source_endpoint: str,
) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "status": status,
        "tone": _tone(status),
        "detail": str(detail or "")[:420],
        "evidence_summary": str(evidence or "")[:520],
        "next_action": str(next_action or "")[:520],
        "source_endpoint": source_endpoint,
        "owner": "platform_ops",
        "external_resource_required": False,
        "customer_visible": False,
        "exports_database": False,
        "exports_raw_secret": False,
        "calls_stripe_api": False,
        "creates_checkout_session": False,
        "triggers_real_charge": False,
        "triggers_ebay_oauth": False,
        "triggers_real_platform_write": False,
        "frontend_gets_secret": False,
        "secret_exposed": False,
    }


def _subscription_shutdown_card(
    key: str,
    label: str,
    status: str,
    evidence: str,
    next_action: str,
    source_endpoint: str,
    *,
    owner_approval_required: bool,
    external_resource_required: bool,
) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "status": status,
        "tone": _tone(status),
        "evidence_summary": str(evidence or "")[:520],
        "next_action": str(next_action or "")[:520],
        "source_endpoint": source_endpoint,
        "owner": "billing_ops",
        "owner_approval_required": owner_approval_required,
        "external_resource_required": external_resource_required,
        "customer_visible": False,
        "public_charging_allowed": False,
        "calls_stripe_api": False,
        "creates_checkout_session": False,
        "triggers_real_charge": False,
        "charge_now_allowed": False,
        "triggers_ebay_oauth": False,
        "triggers_real_platform_write": False,
        "frontend_gets_payment_secret": False,
        "frontend_gets_api_key": False,
        "secret_exposed": False,
    }


def _ops_card(
    key: str,
    label: str,
    status: str,
    detail: str,
    evidence: str,
    next_action: str,
    source_endpoint: str,
) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "status": status,
        "tone": _tone(status),
        "detail": str(detail or "")[:420],
        "evidence_summary": str(evidence or "")[:520],
        "next_action": str(next_action or "")[:520],
        "source_endpoint": source_endpoint,
        "owner": "codex_or_platform_ops",
        "external_resource_required": False,
        "customer_visible": False,
        "calls_stripe_api": False,
        "creates_checkout_session": False,
        "triggers_real_charge": False,
        "triggers_ebay_oauth": False,
        "triggers_real_platform_write": False,
        "frontend_gets_secret": False,
        "secret_exposed": False,
    }


def _war_room_section(key: str, label: str, status: str, evidence: str, next_action: str) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "status": status,
        "tone": _tone(status),
        "evidence_summary": str(evidence or "")[:420],
        "next_action": str(next_action or "")[:520],
        "secret_exposed": False,
    }


def _lane(key: str, label: str, status: str, evidence: str, next_action: str) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "status": status,
        "tone": _tone(status),
        "evidence_summary": str(evidence or "")[:420],
        "next_action": str(next_action or "")[:520],
        "owner_action_required": status != "ready",
        "frontend_gets_secret": False,
        "secret_exposed": False,
    }


def _external_item(
    key: str,
    label: str,
    ready: bool,
    next_action: str,
    *,
    evidence: str,
    triggers_ebay_oauth: bool = False,
) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "status": "ready" if ready else "blocked",
        "tone": "green" if ready else "red",
        "owner": "founder_operator",
        "external_console_required": True,
        "external_resource_required": True,
        "evidence_summary": str(evidence or "")[:420],
        "next_action": str(next_action or "")[:520],
        "triggers_ebay_oauth": triggers_ebay_oauth,
        "repeat_ebay_oauth_allowed": False,
        "creates_checkout_session": False,
        "triggers_real_charge": False,
        "triggers_real_platform_write": False,
        "frontend_gets_secret": False,
        "secret_exposed": False,
    }


def _work_item(key: str, label: str, status: str, detail: str, verification: str) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "status": status,
        "tone": _tone(status),
        "owner": "codex_or_platform_ops",
        "detail": str(detail or "")[:420],
        "verification": verification,
        "external_resource_required": False,
        "triggers_ebay_oauth": False,
        "creates_checkout_session": False,
        "triggers_real_charge": False,
        "triggers_real_platform_write": False,
        "frontend_gets_secret": False,
        "secret_exposed": False,
    }


def _safe_call(label: str, fn: Callable[[], Any], fallback: Any) -> Any:
    try:
        return fn()
    except Exception as exc:  # pragma: no cover - defensive degraded packet.
        if isinstance(fallback, dict):
            return {
                **fallback,
                "status": "degraded",
                "degraded_source": label,
                "error_type": type(exc).__name__,
                "secret_exposed": False,
            }
        return fallback


def _selected_store_id(*, stores: list[dict[str, Any]], requested_store_id: str | None) -> str:
    if requested_store_id and any(str(store.get("store_id") or "") == requested_store_id for store in stores if isinstance(store, dict)):
        return requested_store_id
    for store in stores:
        if isinstance(store, dict) and store.get("store_id"):
            return str(store["store_id"])
    return ""


def _overall_status(
    *,
    public_paid_launch_allowed: bool,
    beta_ready: bool,
    blocked_lanes: list[dict[str, Any]],
    blocked_external: list[dict[str, Any]],
) -> str:
    if public_paid_launch_allowed and not blocked_lanes and not blocked_external:
        return "ready_for_owner_approval"
    if beta_ready:
        return "private_beta_ready_public_launch_blocked"
    return "blocked"


def _by_key(items: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(items, list):
        return {}
    return {str(item.get("key") or ""): item for item in items if isinstance(item, dict) and item.get("key")}


def _group_ready(groups: dict[str, dict[str, Any]], key: str) -> bool:
    return groups.get(key, {}).get("status") == "ready"


def _group_evidence(groups: dict[str, dict[str, Any]], key: str) -> str:
    group = groups.get(key) or {}
    evidence = group.get("evidence") if isinstance(group.get("evidence"), dict) else {}
    parts = [f"{item_key}={item_value}" for item_key, item_value in evidence.items() if not isinstance(item_value, (dict, list))]
    return "; ".join(parts[:8]) or str(group.get("status") or "unknown")


def _summary_next_action(packet: dict[str, Any]) -> str:
    summary = packet.get("summary") if isinstance(packet.get("summary"), dict) else {}
    return str(summary.get("next_action") or "")


def _provider_ready(readiness: dict[str, Any], key: str) -> bool:
    providers = readiness.get("provider_status") if isinstance(readiness.get("provider_status"), dict) else {}
    value = providers.get(key) if isinstance(providers.get(key), dict) else {}
    return bool(value.get("ready") or value.get("configured"))


def _queue_adapter_ready(queue_adapter: dict[str, Any]) -> bool:
    if queue_adapter.get("ready") is True or queue_adapter.get("status") == "ready":
        return True
    selected = str(queue_adapter.get("selected") or queue_adapter.get("provider") or "").lower()
    return selected in {"postgres_durable", "redis_streams", "cloud_tasks", "sqs", "tencent_ckafka"}


def _operational_next_action(operational: dict[str, Any]) -> str:
    blockers = _safe_string_list(operational.get("blockers"))
    warnings = _safe_string_list(operational.get("warnings"))
    if blockers:
        return "Clear operational blockers: " + ", ".join(blockers[:4])
    if warnings:
        return "Review operational warnings: " + ", ".join(warnings[:4])
    return "Keep queue, worker heartbeat and database live probes monitored."


def _billing_entitlement_visible(billing_usage: dict[str, Any]) -> bool:
    subscription = billing_usage.get("subscription") if isinstance(billing_usage.get("subscription"), dict) else {}
    return bool(subscription.get("status") or billing_usage.get("usage"))


def _safe_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item)[:160] for item in value if item is not None][:12]


def _as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _any_true(packet: dict[str, Any], keys: list[str]) -> bool:
    return any(bool(packet.get(key)) for key in keys)


def _tone(status: str) -> str:
    normalized = str(status or "").lower()
    if normalized == "ready":
        return "green"
    if normalized in {"attention_required", "private_beta_ready_public_launch_blocked"}:
        return "amber"
    return "red"


def _env_bool(name: str) -> bool:
    return str(os.environ.get(name) or "").strip().lower() in {"1", "true", "yes", "on", "ready", "verified"}
