"""Billing, plan, and quota readiness contract for Jiejing SaaS."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from .config import SaaSSettings
from .billing_checkout import STRIPE_API_VERSION, build_billing_checkout_contract
from .billing_payment_options import build_mainland_payment_launch_status, build_mainland_payment_strategy
from .billing_webhook import PRIVATE_BETA_BILLING_PROVIDERS, TEST_BILLING_PROVIDERS, build_billing_provider_contract, billing_plan_ids
from .repository import SaaSRepository


PLAN_CATALOG = [
    {
        "key": "free",
        "label": "免费体验",
        "intended_user": "first-time merchant validating one safe operating workflow",
        "amount_minor": 0,
        "currency": "CNY",
        "duration_days": 7,
        "workspace_quota": 1,
        "team_member_quota": 1,
        "monthly_task_quota": 20,
        "connected_store_quota": 1,
        "provider_job_quota": 30,
        "batch_row_quota": 0,
        "store_access_mode": "read_only",
        "media_points_included": 0,
        "includes_real_platform_writes": False,
    },
    {
        "key": "starter",
        "label": "有店铺",
        "intended_user": "single-store merchant running a complete listing workflow",
        "amount_minor": 9900,
        "currency": "CNY",
        "duration_days": 30,
        "workspace_quota": 1,
        "team_member_quota": 2,
        "monthly_task_quota": 100,
        "connected_store_quota": 1,
        "provider_job_quota": 300,
        "batch_row_quota": 20,
        "store_access_mode": "full_workflow",
        "media_points_included": 1000,
        "includes_real_platform_writes": False,
    },
    {
        "key": "operator",
        "label": "多店铺",
        "intended_user": "growing merchant reusing workflows across several stores",
        "amount_minor": 19900,
        "currency": "CNY",
        "duration_days": 30,
        "workspace_quota": 1,
        "team_member_quota": 5,
        "monthly_task_quota": 500,
        "connected_store_quota": 3,
        "provider_job_quota": 1500,
        "batch_row_quota": 200,
        "store_access_mode": "multi_store",
        "media_points_included": 3000,
        "includes_real_platform_writes": False,
    },
]

# Retired plans stay readable for existing subscriptions and historical orders,
# but never re-enter the merchant acquisition catalog or a new checkout path.
LEGACY_PLAN_CATALOG = {
    "team": {
        "key": "team",
        "label": "团队版",
        "intended_user": "existing team-plan merchants only",
        "amount_minor": 29900,
        "currency": "CNY",
        "duration_days": 30,
        "workspace_quota": 1,
        "team_member_quota": 5,
        "monthly_task_quota": 1500,
        "connected_store_quota": 5,
        "provider_job_quota": 4500,
        "batch_row_quota": 1000,
        "store_access_mode": "team_controlled",
        "media_points_included": 0,
        "includes_real_platform_writes": False,
    }
}


QUOTA_ACTION_UNITS = {
    "connected_store": "connected_store_quota",
    "ai_ceo_task": "monthly_task_quota",
    "official_ebay_sync": "provider_job_quota",
    "provider_job": "provider_job_quota",
    "model_report_assist": "provider_job_quota",
}
STRIPE_CURRENT_API_VERSION = "2026-06-24.dahlia"
STRIPE_GO_LIVE_DOCS = [
    "https://docs.stripe.com/get-started/checklist/go-live",
    "https://docs.stripe.com/billing/testing",
    "https://docs.stripe.com/customer-management/integrate-customer-portal",
    "https://docs.stripe.com/api/versioning",
]


def stripe_webhook_api_version() -> str:
    return os.environ.get("JIEJING_STRIPE_WEBHOOK_API_VERSION", "").strip()


def stripe_webhook_api_version_aligned() -> bool:
    return _env_bool("JIEJING_STRIPE_WEBHOOK_API_VERSION_VERIFIED") and stripe_webhook_api_version() == STRIPE_CURRENT_API_VERSION


def _env_text(name: str) -> str:
    return os.environ.get(name, "").strip()


def build_billing_plan(settings: SaaSSettings, repository: SaaSRepository) -> dict[str, Any]:
    counts = repository.system_counts()
    provider = os.environ.get("JIEJING_BILLING_PROVIDER", "").strip().lower()
    provider_contract = build_billing_provider_contract()
    checkout_contract = build_billing_checkout_contract()
    payment_strategy = build_mainland_payment_strategy(settings)
    mainland_payment_launch = build_mainland_payment_launch_status(settings, repository)
    webhook_configured = bool(provider_contract.get("webhook_configured")) or _env_bool("JIEJING_BILLING_WEBHOOK_CONFIGURED")
    plans_published = _env_bool("JIEJING_BILLING_PLANS_PUBLISHED")
    quota_enforcement_enabled = _env_bool("JIEJING_QUOTA_ENFORCEMENT_ENABLED")
    provider = _canonical_provider(provider)
    allowed_provider = provider in {"stripe", "paddle", "lemon_squeezy", "manual_seed"} or provider in TEST_BILLING_PROVIDERS or provider in PRIVATE_BETA_BILLING_PROVIDERS
    external_provider = provider in {"stripe", "paddle", "lemon_squeezy"}
    test_provider = provider in TEST_BILLING_PROVIDERS
    manual_seed_provider = provider == "manual_seed"
    private_beta_provider = provider in PRIVATE_BETA_BILLING_PROVIDERS
    blockers: list[str] = []
    if not allowed_provider:
        blockers.append("billing_provider_not_selected")
    if not plans_published:
        blockers.append("billing_plans_not_published")
    if external_provider and not webhook_configured:
        blockers.append("billing_webhook_not_configured")
    if external_provider and not provider_contract.get("api_key_configured"):
        blockers.append(f"{provider}_api_key_not_configured")
    if external_provider and provider_contract.get("missing_plan_ids"):
        blockers.append("billing_plan_ids_missing")
    if external_provider and provider != "stripe":
        blockers.append("billing_checkout_adapter_not_implemented_for_provider")
    if provider == "stripe" and not checkout_contract.get("checkout_sessions", {}).get("ready"):
        blockers.append("stripe_checkout_not_ready")
    if provider == "stripe" and not checkout_contract.get("customer_portal", {}).get("ready"):
        blockers.append("stripe_customer_portal_not_ready")
    if test_provider and not checkout_contract.get("checkout_sessions", {}).get("ready"):
        blockers.append("billing_test_checkout_not_ready")
    if test_provider and not checkout_contract.get("customer_portal", {}).get("ready"):
        blockers.append("billing_test_customer_portal_not_ready")
    if not quota_enforcement_enabled:
        blockers.append("quota_enforcement_not_enabled")
    paid_launch_blockers = list(blockers)
    if manual_seed_provider or private_beta_provider:
        paid_launch_blockers.append("external_paid_subscription_provider_not_configured")
    if test_provider:
        paid_launch_blockers.append("test_billing_provider_not_allowed_for_paid_launch")
    live_cutover_matrix = _build_billing_live_cutover_matrix(
        provider=provider,
        provider_contract=provider_contract,
        checkout_contract=checkout_contract,
        plans_published=plans_published,
        quota_enforcement_enabled=quota_enforcement_enabled,
    )
    live_cutover_ready_count = sum(1 for item in live_cutover_matrix if item["status"] == "ready")
    live_cutover_blocked = [item for item in live_cutover_matrix if item["status"] != "ready"]
    legacy_paid_launch_ready = settings.is_production_like and external_provider and not paid_launch_blockers
    future_international_payment = dict(mainland_payment_launch.get("future_international_payment") or {})
    future_international_payment.update(
        {
            "provider": "stripe",
            "role": "future_international_payment_only",
            "subscription_provider_contract_version": provider_contract.get("contract_version", ""),
            "checkout_portal_contract_version": checkout_contract.get("contract_version", ""),
            "legacy_paid_launch_compatibility_ready": legacy_paid_launch_ready,
            "blocks_mainland_launch": False,
            "calls_stripe_api": False,
            "triggers_real_charge": False,
            "secret_exposed": False,
        }
    )

    return {
        "contract_version": "2026-05-18-billing-quota-boundary",
        "environment": settings.environment,
        "billing_ready_for_private_beta": settings.is_production_like and not blockers,
        "billing_ready_for_paid_launch": legacy_paid_launch_ready,
        "mainland_payment_ready_for_owner_approval": bool(
            mainland_payment_launch.get("mainland_payment_ready_for_owner_approval")
        ),
        "provider": {
            "selected": provider or "not_selected",
            "allowed_external_providers": ["stripe", "paddle", "lemon_squeezy"],
            "recommended_mainland_provider_order": payment_strategy["recommended_provider_order"],
            "mainland_payment_strategy_contract": payment_strategy["contract_version"],
            "allowed_test_providers": sorted(TEST_BILLING_PROVIDERS),
            "allowed_private_beta_providers": sorted(PRIVATE_BETA_BILLING_PROVIDERS),
            "manual_seed_allowed_for_private_beta": True,
            "manual_beta_allowed_for_private_beta": True,
            "test_provider_allowed_for_private_beta": True,
            "external_paid_provider_configured": external_provider,
            "test_billing_provider_configured": test_provider,
            "manual_beta_private_provider_configured": private_beta_provider,
            "payment_flow_test_mode": test_provider,
            "webhook_configured": webhook_configured,
            "signed_webhook_contract": provider_contract,
            "checkout_portal_contract": checkout_contract,
            "calls_external_payment_api": bool(provider_contract.get("calls_external_payment_api")),
            "can_run_without_payment_provider_account": bool(provider_contract.get("can_run_without_payment_provider_account")),
            "triggers_real_charge": False,
            "charge_now_allowed": False,
            "raw_payment_secret_exposed": False,
        },
        "payment_strategy": payment_strategy,
        "mainland_payment_launch": mainland_payment_launch,
        "future_international_payment": future_international_payment,
        "plan_catalog": _plan_catalog_with_provider_ids(),
        "quota_contract": {
            "enabled": quota_enforcement_enabled,
            "metered_units": [
                "connected_store",
                "ai_ceo_task",
                "provider_job",
                "official_ebay_sync",
                "model_report_assist",
            ],
            "hard_stop_on_quota_exhaustion": quota_enforcement_enabled,
            "merchant_visible_usage_required": True,
            "merchant_byok_chat_not_counted_as_workflow_task": True,
            "media_generation_uses_separate_media_points": True,
            "media_points_are_not_bundled_with_subscription": False,
            "cost_control_required_before_live_media_or_large_model_batches": True,
        },
        "add_on_catalog": [
            {"key": "extra_store_30d", "label": "增加 1 个店铺", "amount_minor": 3900, "currency": "CNY", "duration_days": 30},
            {"key": "extra_seat_30d", "label": "增加 1 个成员", "amount_minor": 1900, "currency": "CNY", "duration_days": 30},
        ],
        "billing_live_cutover_matrix": live_cutover_matrix,
        "billing_live_cutover_summary": {
            "contract_version": "2026-06-18-stripe-billing-live-cutover",
            "ready_count": live_cutover_ready_count,
            "total_count": len(live_cutover_matrix),
            "blocked_count": len(live_cutover_blocked),
            "next_step": live_cutover_blocked[0]["key"] if live_cutover_blocked else "",
            "ready_for_owner_approval": not live_cutover_blocked,
            "charge_now_allowed": False,
            "frontend_gets_payment_secret": False,
            "secret_exposed": False,
        },
        "merchant_launch_path": _build_merchant_billing_launch_path(
            provider=provider,
            external_provider=external_provider,
            test_provider=test_provider,
            manual_seed_provider=manual_seed_provider,
            private_beta_provider=private_beta_provider,
            checkout_contract=checkout_contract,
            provider_contract=provider_contract,
            plans_published=plans_published,
            quota_enforcement_enabled=quota_enforcement_enabled,
            paid_launch_blockers=paid_launch_blockers,
        ),
        "billing_test_rehearsal_summary": _build_billing_test_rehearsal_summary(
            provider=provider,
            test_provider=test_provider,
            provider_contract=provider_contract,
            checkout_contract=checkout_contract,
            plans_published=plans_published,
            quota_enforcement_enabled=quota_enforcement_enabled,
        ),
        "subscription_quota_shutdown_closure": _build_subscription_quota_shutdown_closure(
            provider=provider,
            test_provider=test_provider,
            provider_contract=provider_contract,
            checkout_contract=checkout_contract,
            quota_enforcement_enabled=quota_enforcement_enabled,
        ),
        "billing_incident_runbook": _build_billing_incident_runbook(
            provider=provider,
            test_provider=test_provider,
            provider_contract=provider_contract,
            checkout_contract=checkout_contract,
            quota_enforcement_enabled=quota_enforcement_enabled,
        ),
        "customer_billing_trust_packet": _build_customer_billing_trust_packet(
            provider=provider,
            external_provider=external_provider,
            test_provider=test_provider,
            provider_contract=provider_contract,
            checkout_contract=checkout_contract,
            payment_strategy=payment_strategy,
            plans_published=plans_published,
            quota_enforcement_enabled=quota_enforcement_enabled,
        ),
        "current_usage_shape": {
            "users": counts.get("users", 0),
            "companies": counts.get("companies", 0),
            "stores": counts.get("stores", 0),
            "tasks": counts.get("tasks", 0),
            "queue_jobs": counts.get("queue_jobs", 0),
            "reports": counts.get("reports", 0),
            "platform_data_packets": counts.get("platform_data_packets", 0),
        },
        "confirmation_boundary": {
            "billing_changes_need_owner_or_admin": True,
            "real_platform_writes_not_included_in_any_current_plan": True,
            "refunds_and_payment_disputes_need_human_operator": True,
        },
        "blockers": blockers,
        "paid_launch_blockers": paid_launch_blockers,
        "next_actions": _next_actions(blockers),
        "real_platform_writes_enabled": False,
        "secret_exposed": False,
    }


def _build_merchant_billing_launch_path(
    *,
    provider: str,
    external_provider: bool,
    test_provider: bool,
    manual_seed_provider: bool,
    private_beta_provider: bool,
    checkout_contract: dict[str, Any],
    provider_contract: dict[str, Any],
    plans_published: bool,
    quota_enforcement_enabled: bool,
    paid_launch_blockers: list[str],
) -> dict[str, Any]:
    """Merchant-visible subscription activation path without provider secrets."""

    checkout_sessions = checkout_contract.get("checkout_sessions") if isinstance(checkout_contract.get("checkout_sessions"), dict) else {}
    customer_portal = checkout_contract.get("customer_portal") if isinstance(checkout_contract.get("customer_portal"), dict) else {}
    checkout_ready = bool(checkout_sessions.get("ready"))
    portal_ready = bool(customer_portal.get("ready"))
    backend_confirmation_ready = bool(provider_contract.get("webhook_configured")) or test_provider or manual_seed_provider or private_beta_provider
    if external_provider and checkout_ready and portal_ready and backend_confirmation_ready:
        current_stage = "online_subscription_ready"
        headline = "在线订阅已准备好，付款仍以支付页和后端账单结果为准"
    elif test_provider:
        current_stage = "invited_beta_no_real_charge"
        headline = "当前是受邀试用演练，不会自动扣费"
    elif manual_seed_provider or private_beta_provider:
        current_stage = "service_confirmed_trial"
        headline = "当前由服务支持确认试用订阅"
    else:
        current_stage = "payment_not_open"
        headline = "在线付款暂未开放，当前不会自动扣费"
    blocker = paid_launch_blockers[0] if paid_launch_blockers else ""
    return {
        "contract_version": "2026-07-03-merchant-billing-launch-path-v1",
        "current_stage": current_stage,
        "headline": headline,
        "current_charge_status": "no_real_charge_now" if not external_provider else "provider_hosted_payment_required",
        "merchant_visible": True,
        "internal_launch_evidence_visible": False,
        "plans_published": bool(plans_published),
        "public_paid_launch_allowed": False,
        "charge_now_allowed": False,
        "triggers_real_charge": False,
        "creates_checkout_session_from_browser": False,
        "frontend_gets_payment_secret": False,
        "frontend_can_grant_entitlement": False,
        "frontend_can_grant_quota": False,
        "backend_confirmation_required_before_entitlement": True,
        "backend_confirmation_source": "signed_webhook_or_order_query",
        "hosted_payment_page_required_for_formal_payment": True,
        "customer_portal_required_for_self_service_cancel": True,
        "quota_enforcement_enabled": bool(quota_enforcement_enabled),
        "quota_grant_source": "backend_subscription_state",
        "history_visible_after_billing_problem": True,
        "metered_work_only_blocks_on_billing_problem": True,
        "repeat_ebay_oauth_required_for_billing_recovery": False,
        "model_key_reentry_required_for_billing_recovery": False,
        "next_paid_launch_blocker": blocker,
        "steps": [
            {
                "key": "current_charge_status",
                "label": "当前是否扣费",
                "title": "当前不会自动扣费" if not external_provider else "付款在安全支付页完成",
                "detail": "在线付款开放前只显示套餐、申请状态和可用额度。" if not external_provider else "商家付款由支付方托管页完成，捷境页面不保存支付资料。",
                "ready": True,
            },
            {
                "key": "hosted_payment_page",
                "label": "正式付款",
                "title": "正式付款走安全支付页",
                "detail": "付款资料只在支付方安全页面处理，捷境页面不保存卡号或支付凭证。",
                "ready": bool(external_provider and checkout_ready),
            },
            {
                "key": "backend_confirmation_before_entitlement",
                "label": "订阅生效",
                "title": "系统确认后开通权益",
                "detail": "只有系统确认付款、试用资格或订阅状态后，才会更新套餐权益。",
                "ready": backend_confirmation_ready,
            },
            {
                "key": "quota_from_subscription_state",
                "label": "额度发放",
                "title": "额度按订阅状态发放",
                "detail": "AI、联网报告和素材生成额度只能由系统账单状态发放或停用，浏览器不能自行恢复。",
                "ready": bool(quota_enforcement_enabled),
            },
        ],
        "secret_exposed": False,
    }


def _build_billing_test_rehearsal_summary(
    *,
    provider: str,
    test_provider: bool,
    provider_contract: dict[str, Any],
    checkout_contract: dict[str, Any],
    plans_published: bool,
    quota_enforcement_enabled: bool,
) -> dict[str, Any]:
    checkout_sessions = checkout_contract.get("checkout_sessions") if isinstance(checkout_contract.get("checkout_sessions"), dict) else {}
    customer_portal = checkout_contract.get("customer_portal") if isinstance(checkout_contract.get("customer_portal"), dict) else {}
    event_types = set(provider_contract.get("webhook_event_types") or [])
    required_events = {
        "test.customer.subscription.updated",
        "test.invoice.paid",
        "test.invoice.payment_failed",
        "test.customer.subscription.deleted",
    }
    steps = [
        {
            "key": "test_provider_selected",
            "status": "ready" if test_provider else "blocked",
            "evidence_summary": _compact_billing_evidence(provider=provider or "not_selected", no_stripe_account_required=test_provider),
            "next_action": "Set JIEJING_BILLING_PROVIDER=stripe_test_mock for no-charge billing rehearsal.",
        },
        {
            "key": "test_plan_catalog_available",
            "status": "ready" if plans_published and not provider_contract.get("missing_plan_ids") else "blocked",
            "evidence_summary": _compact_billing_evidence(plans_published=plans_published, missing_plan_ids=provider_contract.get("missing_plan_ids") or []),
            "next_action": "Publish the current Starter and Operator plan catalog for the rehearsal provider.",
        },
        {
            "key": "test_checkout_and_portal_contract",
            "status": "ready" if checkout_sessions.get("ready") and customer_portal.get("ready") else "blocked",
            "evidence_summary": _compact_billing_evidence(
                checkout_ready=bool(checkout_sessions.get("ready")),
                portal_ready=bool(customer_portal.get("ready")),
                calls_stripe_api=bool(checkout_sessions.get("calls_stripe_api")),
                creates_real_checkout_session=bool(checkout_sessions.get("creates_real_checkout_session")),
            ),
            "next_action": "Configure stable success, cancel and portal return URLs.",
        },
        {
            "key": "test_subscription_lifecycle_events",
            "status": "ready" if required_events.issubset(event_types) else "blocked",
            "evidence_summary": _compact_billing_evidence(required_events_present=required_events.issubset(event_types)),
            "next_action": "Use POST /billing/test-event to rehearse activate, invoice_paid, payment_failed and cancel states.",
        },
        {
            "key": "test_provider_order_query_or_signed_webhook",
            "status": "ready" if test_provider and required_events.issubset(event_types) else "blocked",
            "evidence_summary": _compact_billing_evidence(
                backend_order_query_proof=True,
                signed_webhook_or_order_query_required=True,
                frontend_can_grant_entitlement=False,
            ),
            "next_action": "Use POST /owner/billing/provider-rehearsal from the operations console to prove checkout, backend proof, entitlement and quota in one no-charge path.",
        },
        {
            "key": "quota_hard_stop_rehearsal",
            "status": "ready" if quota_enforcement_enabled else "blocked",
            "evidence_summary": _compact_billing_evidence(quota_enabled=quota_enforcement_enabled),
            "next_action": "Enable quota enforcement so payment failure and cancellation stop metered work.",
        },
    ]
    ready_count = sum(1 for item in steps if item["status"] == "ready")
    blocked = [item for item in steps if item["status"] != "ready"]
    return {
        "contract_version": "2026-06-18-no-charge-billing-rehearsal",
        "provider": provider or "not_selected",
        "ready": test_provider and not blocked,
        "ready_count": ready_count,
        "total_count": len(steps),
        "blocked_count": len(blocked),
        "next_step": blocked[0]["key"] if blocked else "",
        "steps": [
            {
                **item,
                "severity": "info" if item["status"] == "ready" else "blocker",
                "external_resource_required": False,
                "creates_real_checkout_session": False,
                "calls_stripe_api": False,
                "triggers_real_charge": False,
                "charge_now_allowed": False,
                "frontend_gets_payment_secret": False,
                "secret_exposed": False,
            }
            for item in steps
        ],
        "paid_launch_ready": False,
        "public_charging_allowed": False,
        "external_resource_required": False,
        "creates_real_checkout_session": False,
        "calls_stripe_api": False,
        "triggers_real_charge": False,
        "charge_now_allowed": False,
        "frontend_gets_payment_secret": False,
        "secret_exposed": False,
    }


def _build_subscription_quota_shutdown_closure(
    *,
    provider: str,
    test_provider: bool,
    provider_contract: dict[str, Any],
    checkout_contract: dict[str, Any],
    quota_enforcement_enabled: bool,
) -> dict[str, Any]:
    """Describe the billing lifecycle drill that prevents unpaid usage."""

    event_types = set(provider_contract.get("webhook_event_types") or [])
    customer_portal = checkout_contract.get("customer_portal") if isinstance(checkout_contract.get("customer_portal"), dict) else {}
    live_lifecycle_flags = {
        "portal": _env_bool("JIEJING_STRIPE_CUSTOMER_PORTAL_TESTED"),
        "cancel": _env_bool("JIEJING_STRIPE_SUBSCRIPTION_CANCEL_TESTED"),
        "invoice_paid": _env_bool("JIEJING_STRIPE_INVOICE_PAID_TESTED"),
        "payment_failed": _env_bool("JIEJING_STRIPE_PAYMENT_FAILURE_TESTED"),
    }
    if test_provider:
        required_events = {
            "test.customer.subscription.updated",
            "test.invoice.paid",
            "test.invoice.payment_failed",
            "test.customer.subscription.deleted",
        }
        lifecycle_events_ready = required_events.issubset(event_types)
        portal_changes_ready = bool(customer_portal.get("ready"))
        invoice_paid_ready = "test.invoice.paid" in event_types
        payment_failed_ready = "test.invoice.payment_failed" in event_types
        cancel_ready = "test.customer.subscription.deleted" in event_types
        external_resource_required = False
    else:
        required_events = {
            "customer.subscription.created",
            "customer.subscription.updated",
            "customer.subscription.deleted",
            "invoice.paid",
            "invoice.payment_failed",
        }
        lifecycle_events_ready = required_events.issubset(event_types) and bool(provider_contract.get("webhook_configured"))
        portal_changes_ready = bool(customer_portal.get("ready")) and live_lifecycle_flags["portal"]
        invoice_paid_ready = "invoice.paid" in event_types and live_lifecycle_flags["invoice_paid"]
        payment_failed_ready = "invoice.payment_failed" in event_types and live_lifecycle_flags["payment_failed"]
        cancel_ready = "customer.subscription.deleted" in event_types and live_lifecycle_flags["cancel"]
        external_resource_required = provider in {"stripe", "paddle", "lemon_squeezy"}
    steps = [
        _billing_shutdown_step(
            "subscription_activation_grants_entitlement",
            "Activation writes a subscription record and grants entitlement",
            lifecycle_events_ready,
            evidence_summary=_compact_billing_evidence(
                provider=provider or "not_selected",
                required_events_present=lifecycle_events_ready,
                signed_webhook=bool(provider_contract.get("webhook_configured")),
            ),
            next_action="Rehearse subscription created or updated through signed webhook/test event before enabling paid launch.",
            external_resource_required=external_resource_required,
        ),
        _billing_shutdown_step(
            "invoice_paid_keeps_quota_open",
            "Invoice paid keeps entitlement and quota open",
            invoice_paid_ready,
            evidence_summary=_compact_billing_evidence(
                invoice_paid_event_present=invoice_paid_ready,
                live_invoice_paid_tested=live_lifecycle_flags["invoice_paid"],
                test_provider=test_provider,
            ),
            next_action="Run invoice paid rehearsal and confirm the merchant plan remains active.",
            external_resource_required=external_resource_required,
        ),
        _billing_shutdown_step(
            "payment_failed_disables_entitlement",
            "Payment failure disables entitlement",
            payment_failed_ready and quota_enforcement_enabled,
            evidence_summary=_compact_billing_evidence(
                payment_failed_event_present=payment_failed_ready,
                quota_enabled=quota_enforcement_enabled,
                live_payment_failure_tested=live_lifecycle_flags["payment_failed"],
                test_provider=test_provider,
            ),
            next_action="Run payment_failed rehearsal and confirm metered AI CEO work returns billing_subscription_not_active.",
            external_resource_required=external_resource_required,
            owner_approval_required=True,
        ),
        _billing_shutdown_step(
            "subscription_cancel_disables_entitlement",
            "Cancellation disables entitlement",
            cancel_ready and quota_enforcement_enabled,
            evidence_summary=_compact_billing_evidence(
                cancel_event_present=cancel_ready,
                quota_enabled=quota_enforcement_enabled,
                live_cancel_tested=live_lifecycle_flags["cancel"],
                test_provider=test_provider,
            ),
            next_action="Run cancel/delete rehearsal and confirm usage stays visible but new metered work is blocked.",
            external_resource_required=external_resource_required,
            owner_approval_required=True,
        ),
        _billing_shutdown_step(
            "quota_guardrail_blocks_metered_work",
            "Quota guardrail blocks unpaid or exhausted metered work",
            quota_enforcement_enabled,
            evidence_summary=_compact_billing_evidence(
                quota_enabled=quota_enforcement_enabled,
                hard_stop_on_inactive_subscription=True,
                covered_units="/".join(sorted(QUOTA_ACTION_UNITS)),
            ),
            next_action="Keep quota enforcement enabled for AI CEO tasks, provider jobs and connected-store limits.",
            external_resource_required=False,
        ),
        _billing_shutdown_step(
            "customer_portal_changes_audited",
            "Customer Portal changes remain inside provider and audit boundary",
            portal_changes_ready,
            evidence_summary=_compact_billing_evidence(
                portal_ready=bool(customer_portal.get("ready")),
                live_portal_tested=live_lifecycle_flags["portal"],
                frontend_gets_payment_secret=False,
            ),
            next_action="Verify portal plan changes, cancel and provider-side payment updates never expose payment or provider secrets to frontend.",
            external_resource_required=external_resource_required,
        ),
        _billing_shutdown_step(
            "provider_cutover_no_real_charge_safety",
            "Provider cutover drill is no-charge until owner approval",
            True,
            evidence_summary=_compact_billing_evidence(
                creates_checkout_session=False,
                calls_stripe_api=False,
                triggers_real_charge=False,
                frontend_gets_payment_secret=False,
            ),
            next_action="Use the rehearsal flow first; only switch to live Checkout after live provider env, webhook and owner approval are present.",
            external_resource_required=False,
        ),
    ]
    ready_count = sum(1 for item in steps if item["status"] == "ready")
    blocked = [item for item in steps if item["status"] != "ready"]
    next_step = blocked[0]["key"] if blocked else ""
    return {
        "contract_version": "2026-06-20-subscription-quota-shutdown-closure",
        "provider": provider or "not_selected",
        "mode": "no_charge_test_provider" if test_provider else "live_provider_rehearsal",
        "ready": not blocked,
        "ready_for_no_charge_rehearsal": test_provider and not blocked,
        "ready_for_live_cutover": provider == "stripe" and not test_provider and not blocked,
        "ready_count": ready_count,
        "total_count": len(steps),
        "blocked_count": len(blocked),
        "next_step": next_step,
        "operator_summary": {
            "status": "ready" if not blocked else "blocked",
            "ready_text": f"{ready_count}/{len(steps)} subscription shutdown controls ready",
            "blocked_text": f"{len(blocked)} billing shutdown controls still need evidence",
            "next_action": blocked[0]["next_action"] if blocked else "Keep no-charge failed-payment, cancellation and quota shutdown rehearsal evidence current.",
            "secret_exposed": False,
        },
        "steps": steps,
        "covered_actions": sorted(QUOTA_ACTION_UNITS),
        "shutdown_guards": {
            "covered_action_count": len(QUOTA_ACTION_UNITS),
            "hard_stop_on_inactive_subscription": quota_enforcement_enabled,
            "payment_failure_blocks_metered_work": quota_enforcement_enabled and payment_failed_ready,
            "cancellation_blocks_metered_work": quota_enforcement_enabled and cancel_ready,
            "usage_remains_visible_after_shutdown": True,
            "owner_approval_required_for_reenable": True,
            "secret_exposed": False,
        },
        "payment_failure_blocks_metered_work": quota_enforcement_enabled and payment_failed_ready,
        "cancellation_blocks_metered_work": quota_enforcement_enabled and cancel_ready,
        "public_charging_allowed": False,
        "creates_checkout_session": False,
        "calls_stripe_api": False,
        "triggers_real_charge": False,
        "charge_now_allowed": False,
        "frontend_gets_payment_secret": False,
        "frontend_gets_api_key": False,
        "secret_exposed": False,
    }


def _build_billing_incident_runbook(
    *,
    provider: str,
    test_provider: bool,
    provider_contract: dict[str, Any],
    checkout_contract: dict[str, Any],
    quota_enforcement_enabled: bool,
) -> dict[str, Any]:
    """Operator-facing billing incident handling without payment secrets."""

    event_types = set(provider_contract.get("webhook_event_types") or [])
    customer_portal = checkout_contract.get("customer_portal") if isinstance(checkout_contract.get("customer_portal"), dict) else {}
    refund_events = {"charge.refunded", "charge.dispute.created", "charge.dispute.closed"}
    cards = [
        _billing_incident_card(
            "customer_portal_change",
            "Customer Portal plan change",
            bool(customer_portal.get("ready")),
            trigger="merchant_self_service_portal",
            visible_result="Provider keeps card/payment method management outside Jiejing; subscription changes return through signed webhook before quota changes.",
            operator_action="Verify signed subscription.updated or subscription.deleted event, then review quota and audit state.",
            signed_webhook_required=True,
            frontend_action_allowed=False,
        ),
        _billing_incident_card(
            "payment_failed",
            "Payment failed",
            ("invoice.payment_failed" in event_types or "test.invoice.payment_failed" in event_types) and quota_enforcement_enabled,
            trigger="provider_signed_invoice_payment_failed",
            visible_result="Subscription enters payment attention; metered AI CEO/provider/model work is blocked while reports and audit stay visible.",
            operator_action="Ask merchant to update payment method or confirm manual recovery; do not request eBay OAuth or model key re-entry.",
            signed_webhook_required=True,
            frontend_action_allowed=False,
        ),
        _billing_incident_card(
            "subscription_cancelled",
            "Subscription cancelled",
            ("customer.subscription.deleted" in event_types or "test.customer.subscription.deleted" in event_types) and quota_enforcement_enabled,
            trigger="provider_signed_subscription_deleted",
            visible_result="Entitlement turns inactive and high-cost work is hard-stopped; historical business evidence remains readable.",
            operator_action="Let merchant restore through Customer Portal or internal admin recovery after payment proof.",
            signed_webhook_required=True,
            frontend_action_allowed=False,
        ),
        _billing_incident_card(
            "refund_or_dispute",
            "Refund or payment dispute",
            test_provider or bool(refund_events.intersection(event_types)),
            trigger="provider_signed_refund_or_dispute_webhook",
            visible_result="Refund/dispute moves subscription into payment attention and blocks metered work until operator review.",
            operator_action="Handle the money movement inside Stripe/provider dashboard and keep Jiejing as audit/subscription state only.",
            signed_webhook_required=True,
            frontend_action_allowed=False,
            confirmation_center_required=True,
        ),
        _billing_incident_card(
            "quota_hard_stop",
            "Quota hard-stop",
            quota_enforcement_enabled,
            trigger="backend_quota_evaluation",
            visible_result="Only new metered work is blocked; reports, settings, confirmation records and audit remain visible.",
            operator_action="Review billing status, plan limits and failed/cancel/refund evidence before re-enabling.",
            signed_webhook_required=False,
            frontend_action_allowed=False,
        ),
    ]
    ready_count = sum(1 for item in cards if item["status"] == "ready")
    return {
        "contract_version": "2026-07-01-billing-incident-runbook-v1",
        "provider": provider or "not_selected",
        "mode": "no_charge_test_provider" if test_provider else "live_provider_rehearsal",
        "cards": cards,
        "ready_count": ready_count,
        "total_count": len(cards),
        "blocked_count": len(cards) - ready_count,
        "refund_dispute_supported_by_signed_webhook": bool(refund_events.intersection(event_types)),
        "customer_portal_changes_require_signed_webhook": True,
        "refund_or_dispute_cannot_be_frontend_executed": True,
        "payment_failed_cancel_blocks_metered_work": quota_enforcement_enabled,
        "history_and_audit_remain_visible": True,
        "public_charging_allowed": False,
        "triggers_real_charge": False,
        "charge_now_allowed": False,
        "frontend_gets_payment_secret": False,
        "secret_exposed": False,
    }


def _billing_incident_card(
    key: str,
    title: str,
    ready: bool,
    *,
    trigger: str,
    visible_result: str,
    operator_action: str,
    signed_webhook_required: bool,
    frontend_action_allowed: bool,
    confirmation_center_required: bool = False,
) -> dict[str, Any]:
    return {
        "key": key,
        "title": title,
        "status": "ready" if ready else "blocked",
        "severity": "info" if ready else "blocker",
        "trigger": trigger,
        "visible_result": visible_result,
        "operator_action": operator_action,
        "signed_webhook_required": signed_webhook_required,
        "frontend_action_allowed": frontend_action_allowed,
        "confirmation_center_required": confirmation_center_required,
        "creates_checkout_session": False,
        "calls_stripe_api": False,
        "triggers_real_charge": False,
        "charge_now_allowed": False,
        "frontend_gets_payment_secret": False,
        "secret_exposed": False,
    }


def _build_customer_billing_trust_packet(
    *,
    provider: str,
    external_provider: bool,
    test_provider: bool,
    provider_contract: dict[str, Any],
    checkout_contract: dict[str, Any],
    payment_strategy: dict[str, Any],
    plans_published: bool,
    quota_enforcement_enabled: bool,
) -> dict[str, Any]:
    """Merchant-facing billing promises required before public paid launch."""

    checkout_sessions = checkout_contract.get("checkout_sessions") if isinstance(checkout_contract.get("checkout_sessions"), dict) else {}
    customer_portal = checkout_contract.get("customer_portal") if isinstance(checkout_contract.get("customer_portal"), dict) else {}
    urls = checkout_contract.get("urls") if isinstance(checkout_contract.get("urls"), dict) else {}
    merchant_packet = payment_strategy.get("merchant_application_packet") if isinstance(payment_strategy.get("merchant_application_packet"), dict) else {}
    review_urls = merchant_packet.get("review_urls") if isinstance(merchant_packet.get("review_urls"), dict) else {}
    customer_brief = merchant_packet.get("customer_review_brief") if isinstance(merchant_packet.get("customer_review_brief"), dict) else {}
    refund_support = customer_brief.get("refund_and_support") if isinstance(customer_brief.get("refund_and_support"), dict) else {}
    signed_webhook_ready = bool(provider_contract.get("webhook_configured"))
    links_ready = bool(review_urls.get("terms") and review_urls.get("privacy") and review_urls.get("refund_policy") and review_urls.get("support"))
    portal_ready = bool(customer_portal.get("ready")) and bool(urls.get("portal_return_url_configured"))
    checkout_ready = bool(checkout_sessions.get("ready")) and checkout_sessions.get("mode") == "subscription" and checkout_sessions.get("uses_price_ids") is True
    cards = [
        _customer_billing_trust_card(
            "price_and_renewal_terms",
            "Plan price and renewal terms",
            plans_published,
            merchant_promise="Merchant sees the plan, billing period, quota boundary, cancellation path and usage-cost boundary before payment.",
            evidence="plan_catalog + merchant billing summary + public terms/refund policy",
            next_action="Publish live Price IDs and keep subscription/usage/platform-cost boundaries visible before any public charge.",
        ),
        _customer_billing_trust_card(
            "hosted_checkout_payment_boundary",
            "Hosted subscription checkout",
            checkout_ready,
            merchant_promise="Initial subscription payment is hosted by the payment provider; Jiejing frontend never handles card data or provider secrets.",
            evidence="Checkout Sessions mode=subscription, configured success/cancel URLs, company metadata and Price IDs.",
            next_action="Use provider-hosted subscription Checkout with stable-domain return URLs.",
        ),
        _customer_billing_trust_card(
            "self_service_cancel_portal",
            "Self-service billing portal",
            portal_ready,
            merchant_promise="Merchant can update payment method, manage plan and cancel through Customer Portal after provider-side proof.",
            evidence="Customer Portal return URL is configured and request override is locked to backend config.",
            next_action="Verify Customer Portal plan change and cancellation events through signed webhook before paid launch.",
        ),
        _customer_billing_trust_card(
            "invoice_receipt_tax_path",
            "Receipt, invoice and tax path",
            external_provider and plans_published and signed_webhook_ready,
            merchant_promise="Receipt/invoice/tax questions have a support path and remain linked to provider order, subscription and audit evidence.",
            evidence="merchant payment application packet + signed webhook/order-query proof + support/refund public pages.",
            next_action="Finalize merchant entity, settlement identity and tax invoice policy outside the frontend before public paid launch.",
            owner_approval_required=True,
        ),
        _customer_billing_trust_card(
            "refund_support_public_entry",
            "Refund and support entry",
            links_ready,
            merchant_promise="Merchant can find terms, privacy, refund policy, support and risk disclosure before paying.",
            evidence="public legal/support URLs are present in the payment-review packet.",
            next_action="Keep public support contact current and route refund/dispute handling through provider dashboard plus audit.",
            owner_approval_required=refund_support.get("support_contact_status") != "ready",
        ),
        _customer_billing_trust_card(
            "entitlement_recovery_boundary",
            "Entitlement recovery boundary",
            quota_enforcement_enabled,
            merchant_promise="Payment failure, cancellation, refund or dispute only blocks new metered work; history remains visible and recovery does not repeat eBay OAuth.",
            evidence="billing incident runbook + subscription/quota shutdown closure.",
            next_action="Keep no-charge lifecycle rehearsal current for payment failed, cancel, refund and dispute events.",
        ),
    ]
    ready_count = sum(1 for item in cards if item["status"] == "ready")
    return {
        "contract_version": "2026-07-01-customer-billing-trust-packet-v1",
        "provider": provider or "not_selected",
        "mode": "test_provider_rehearsal" if test_provider else "live_provider_customer_trust",
        "cards": cards,
        "ready_count": ready_count,
        "total_count": len(cards),
        "blocked_count": len(cards) - ready_count,
        "next_step": next((item["key"] for item in cards if item["status"] != "ready"), ""),
        "review_urls": {
            "terms": str(review_urls.get("terms") or ""),
            "privacy": str(review_urls.get("privacy") or ""),
            "refund_policy": str(review_urls.get("refund_policy") or ""),
            "support": str(review_urls.get("support") or ""),
            "risk_disclosure": str(review_urls.get("risk_disclosure") or ""),
        },
        "checkout_is_hosted_by_provider": True,
        "customer_can_cancel_in_portal": portal_ready,
        "invoice_receipt_requires_live_provider": True,
        "tax_invoice_policy_requires_merchant_entity": True,
        "support_refund_links_visible": links_ready,
        "entitlement_recovery_does_not_repeat_ebay_oauth": True,
        "ready_for_paid_customer_display": external_provider and ready_count == len(cards),
        "public_charging_allowed": False,
        "creates_checkout_session": False,
        "calls_stripe_api": False,
        "triggers_real_charge": False,
        "charge_now_allowed": False,
        "frontend_gets_payment_secret": False,
        "secret_exposed": False,
    }


def _customer_billing_trust_card(
    key: str,
    title: str,
    ready: bool,
    *,
    merchant_promise: str,
    evidence: str,
    next_action: str,
    owner_approval_required: bool = False,
) -> dict[str, Any]:
    return {
        "key": key,
        "title": title,
        "status": "ready" if ready else "blocked",
        "severity": "info" if ready else "blocker",
        "merchant_promise": merchant_promise,
        "evidence": evidence,
        "next_action": next_action,
        "owner_approval_required": owner_approval_required,
        "frontend_action_allowed": False,
        "creates_checkout_session": False,
        "calls_stripe_api": False,
        "triggers_real_charge": False,
        "charge_now_allowed": False,
        "frontend_gets_payment_secret": False,
        "secret_exposed": False,
    }


def _billing_shutdown_step(
    key: str,
    title: str,
    ready: bool,
    *,
    evidence_summary: str,
    next_action: str,
    external_resource_required: bool,
    owner_approval_required: bool = False,
) -> dict[str, Any]:
    return {
        "key": key,
        "title": title,
        "status": "ready" if ready else "blocked",
        "severity": "info" if ready else "blocker",
        "evidence_summary": evidence_summary,
        "next_action": next_action,
        "external_resource_required": external_resource_required,
        "owner_approval_required": owner_approval_required,
        "creates_checkout_session": False,
        "calls_stripe_api": False,
        "triggers_real_charge": False,
        "charge_now_allowed": False,
        "frontend_gets_payment_secret": False,
        "secret_exposed": False,
    }


def _build_billing_live_cutover_matrix(
    *,
    provider: str,
    provider_contract: dict[str, Any],
    checkout_contract: dict[str, Any],
    plans_published: bool,
    quota_enforcement_enabled: bool,
) -> list[dict[str, Any]]:
    checkout_sessions = checkout_contract.get("checkout_sessions") if isinstance(checkout_contract.get("checkout_sessions"), dict) else {}
    customer_portal = checkout_contract.get("customer_portal") if isinstance(checkout_contract.get("customer_portal"), dict) else {}
    urls = checkout_contract.get("urls") if isinstance(checkout_contract.get("urls"), dict) else {}
    plan_ids = provider_contract.get("plan_ids") if isinstance(provider_contract.get("plan_ids"), dict) else {}
    event_types = set(provider_contract.get("webhook_event_types") or [])
    required_stripe_events = {
        "checkout.session.completed",
        "customer.subscription.created",
        "customer.subscription.updated",
        "customer.subscription.deleted",
        "invoice.paid",
        "invoice.payment_failed",
    }
    live_object_flags = [
        "JIEJING_STRIPE_LIVE_PRODUCTS_VERIFIED",
        "JIEJING_STRIPE_LIVE_PRICES_VERIFIED",
        "JIEJING_STRIPE_NO_TEST_OBJECTS_IN_LIVE_CONFIG",
    ]
    webhook_resilience_flags = [
        "JIEJING_STRIPE_WEBHOOK_DUPLICATE_TESTED",
        "JIEJING_STRIPE_WEBHOOK_DELAYED_TESTED",
        "JIEJING_STRIPE_WEBHOOK_OUT_OF_ORDER_TESTED",
    ]
    webhook_failure_path_evidence_id = _env_text("JIEJING_STRIPE_WEBHOOK_FAILURE_PATH_EVIDENCE_ID")
    billing_lifecycle_flags = [
        "JIEJING_STRIPE_CUSTOMER_PORTAL_TESTED",
        "JIEJING_STRIPE_SUBSCRIPTION_CANCEL_TESTED",
        "JIEJING_STRIPE_INVOICE_PAID_TESTED",
        "JIEJING_STRIPE_PAYMENT_FAILURE_TESTED",
    ]
    portal_failure_path_evidence_id = _env_text("JIEJING_STRIPE_CUSTOMER_PORTAL_FAILURE_PATH_EVIDENCE_ID")
    return [
        _billing_live_cutover_step(
            "stripe_live_provider_selected",
            "Stripe live provider and backend secret boundary",
            provider == "stripe" and bool(provider_contract.get("external_provider_configured")) and bool(provider_contract.get("api_key_configured")),
            owner="platform_ops",
            category="provider",
            evidence_summary=_compact_billing_evidence(
                provider=provider or "not_selected",
                api_key_configured=bool(provider_contract.get("api_key_configured")),
                frontend_gets_payment_secret=False,
            ),
            next_action="Select Stripe as the live subscription provider and keep API keys inside backend environment or Vault only.",
            environment_keys=["JIEJING_BILLING_PROVIDER", "JIEJING_STRIPE_SECRET_KEY"],
            verification=["/billing/plans", "/billing/checkout-contract", "tools/test_jiejing_stripe_checkout_portal.py"],
            docs=[STRIPE_GO_LIVE_DOCS[0], STRIPE_GO_LIVE_DOCS[3]],
        ),
        _billing_live_cutover_step(
            "stripe_live_price_catalog",
            "Live product and Price catalog",
            plans_published and all(bool(plan_ids.get(key)) for key in ("starter", "operator")) and all(_env_bool(name) for name in live_object_flags),
            owner="commercial_ops",
            category="price_catalog",
            evidence_summary=_compact_billing_evidence(
                plans_published=plans_published,
                starter_price=bool(plan_ids.get("starter")),
                operator_price=bool(plan_ids.get("operator")),
                legacy_team_price_optional=bool(plan_ids.get("team")),
                live_objects_verified=all(_env_bool(name) for name in live_object_flags),
            ),
            next_action="Publish live Starter and Operator Price IDs and verify they are not sandbox/test objects before public charging.",
            environment_keys=[
                "JIEJING_BILLING_PLANS_PUBLISHED",
                "JIEJING_STRIPE_PRICE_STARTER_ID",
                "JIEJING_STRIPE_PRICE_OPERATOR_ID",
                *live_object_flags,
            ],
            verification=["/billing/plans", "Stripe live Products and Prices"],
            docs=[STRIPE_GO_LIVE_DOCS[0]],
        ),
        _billing_live_cutover_step(
            "stripe_subscription_checkout_contract",
            "Subscription Checkout contract",
            bool(checkout_sessions.get("ready"))
            and checkout_sessions.get("mode") == "subscription"
            and checkout_sessions.get("uses_price_ids") is True
            and urls.get("success_url_configured") is True
            and urls.get("cancel_url_configured") is True
            and urls.get("request_override_must_match_configured_url") is True,
            owner="platform_ops",
            category="checkout",
            evidence_summary=_compact_billing_evidence(
                checkout_ready=bool(checkout_sessions.get("ready")),
                mode=checkout_sessions.get("mode") or "missing",
                uses_price_ids=checkout_sessions.get("uses_price_ids") is True,
                success_url=urls.get("success_url_configured") is True,
                cancel_url=urls.get("cancel_url_configured") is True,
                overrides_locked_to_configured_url=urls.get("request_override_must_match_configured_url") is True,
            ),
            next_action="Use Stripe Checkout Sessions in subscription mode with live Price IDs, success/cancel URLs and company metadata.",
            environment_keys=["JIEJING_BILLING_SUCCESS_URL", "JIEJING_BILLING_CANCEL_URL"],
            verification=["/billing/checkout-contract", "tools/test_jiejing_stripe_checkout_portal.py"],
            docs=[STRIPE_GO_LIVE_DOCS[1]],
        ),
        _billing_live_cutover_step(
            "stripe_customer_portal_contract",
            "Customer Portal contract",
            bool(customer_portal.get("ready"))
            and urls.get("portal_return_url_configured") is True
            and urls.get("request_override_must_match_configured_url") is True,
            owner="platform_ops",
            category="portal",
            evidence_summary=_compact_billing_evidence(
                portal_ready=bool(customer_portal.get("ready")),
                portal_return_url=urls.get("portal_return_url_configured") is True,
                overrides_locked_to_configured_url=urls.get("request_override_must_match_configured_url") is True,
            ),
            next_action="Verify Customer Portal can manage subscription changes, payment method updates and cancellation without exposing payment secrets.",
            environment_keys=["JIEJING_BILLING_PORTAL_RETURN_URL"],
            verification=["/billing/customer-portal", "tools/test_jiejing_stripe_checkout_portal.py"],
            docs=[STRIPE_GO_LIVE_DOCS[2]],
        ),
        _billing_live_cutover_step(
            "stripe_signed_webhook_contract",
            "Signed webhook endpoint contract",
            bool(provider_contract.get("webhook_configured")) and required_stripe_events.issubset(event_types),
            owner="platform_ops",
            category="webhook",
            evidence_summary=_compact_billing_evidence(
                webhook_configured=bool(provider_contract.get("webhook_configured")),
                required_events_present=required_stripe_events.issubset(event_types),
            ),
            next_action="Register the live Stripe webhook endpoint with subscription, invoice paid and payment-failure events; verify every event with signature checking.",
            environment_keys=["JIEJING_STRIPE_WEBHOOK_SECRET", "JIEJING_BILLING_WEBHOOK_URL"],
            verification=["/billing/webhook", "tools/test_jiejing_billing_provider_webhook.py"],
            docs=[STRIPE_GO_LIVE_DOCS[0], STRIPE_GO_LIVE_DOCS[1]],
        ),
        _billing_live_cutover_step(
            "stripe_api_webhook_version_alignment",
            "API and webhook version alignment",
            STRIPE_API_VERSION == STRIPE_CURRENT_API_VERSION
            and checkout_contract.get("stripe_api_version") == STRIPE_CURRENT_API_VERSION
            and stripe_webhook_api_version_aligned(),
            owner="platform_ops",
            category="versioning",
            evidence_summary=_compact_billing_evidence(
                request_api_version=checkout_contract.get("stripe_api_version") or "missing",
                expected_api_version=STRIPE_CURRENT_API_VERSION,
                recorded_webhook_api_version=stripe_webhook_api_version() or "missing",
                webhook_endpoint_version_verified=_env_bool("JIEJING_STRIPE_WEBHOOK_API_VERSION_VERIFIED"),
                webhook_endpoint_version_aligned=stripe_webhook_api_version() == STRIPE_CURRENT_API_VERSION,
            ),
            next_action="Keep backend Stripe-Version and live webhook endpoint API version aligned to the reviewed Stripe version.",
            environment_keys=["JIEJING_STRIPE_WEBHOOK_API_VERSION", "JIEJING_STRIPE_WEBHOOK_API_VERSION_VERIFIED"],
            verification=["/billing/checkout-contract", "Stripe webhook endpoint metadata"],
            docs=[STRIPE_GO_LIVE_DOCS[0], STRIPE_GO_LIVE_DOCS[3]],
        ),
        _billing_live_cutover_step(
            "stripe_webhook_failure_paths",
            "Webhook delayed, duplicate and out-of-order failure paths",
            bool(provider_contract.get("webhook_configured"))
            and all(_env_bool(name) for name in webhook_resilience_flags)
            and bool(webhook_failure_path_evidence_id),
            owner="platform_ops",
            category="resilience",
            evidence_summary=_compact_billing_evidence(
                signed_webhook=bool(provider_contract.get("webhook_configured")),
                duplicate_tested=_env_bool("JIEJING_STRIPE_WEBHOOK_DUPLICATE_TESTED"),
                delayed_tested=_env_bool("JIEJING_STRIPE_WEBHOOK_DELAYED_TESTED"),
                out_of_order_tested=_env_bool("JIEJING_STRIPE_WEBHOOK_OUT_OF_ORDER_TESTED"),
                evidence_id_present=bool(webhook_failure_path_evidence_id),
            ),
            next_action="Prove webhook handling is idempotent and resilient to delayed, duplicate and out-of-order delivery before charging real merchants.",
            environment_keys=[*webhook_resilience_flags, "JIEJING_STRIPE_WEBHOOK_FAILURE_PATH_EVIDENCE_ID"],
            verification=["tools/test_jiejing_billing_provider_webhook.py", "tools/test_jiejing_billing_webhook_subscription_state.py"],
            docs=[STRIPE_GO_LIVE_DOCS[0], STRIPE_GO_LIVE_DOCS[1]],
            local_contract_proof={
                "duplicate_event_idempotent": True,
                "unsupported_event_cannot_grant_entitlement": True,
                "missing_event_id_cannot_grant_entitlement": True,
                "unmapped_provider_identity_cannot_grant_entitlement": True,
                "evidence_id_required": True,
                "evidence_id_present": bool(webhook_failure_path_evidence_id),
                "raw_webhook_payload_persisted": False,
                "verification": "tools/test_jiejing_billing_webhook_subscription_state.py",
            },
        ),
        _billing_live_cutover_step(
            "stripe_entitlement_quota_lifecycle",
            "Entitlement, quota and payment-failure lifecycle",
            quota_enforcement_enabled and all(_env_bool(name) for name in billing_lifecycle_flags) and bool(portal_failure_path_evidence_id),
            owner="platform_ops",
            category="entitlement",
            evidence_summary=_compact_billing_evidence(
                quota_enabled=quota_enforcement_enabled,
                portal_tested=_env_bool("JIEJING_STRIPE_CUSTOMER_PORTAL_TESTED"),
                cancel_tested=_env_bool("JIEJING_STRIPE_SUBSCRIPTION_CANCEL_TESTED"),
                invoice_paid_tested=_env_bool("JIEJING_STRIPE_INVOICE_PAID_TESTED"),
                payment_failure_tested=_env_bool("JIEJING_STRIPE_PAYMENT_FAILURE_TESTED"),
                evidence_id_present=bool(portal_failure_path_evidence_id),
            ),
            next_action="Verify invoice paid provisioning, cancellation, payment failure, portal changes and hard-stop quota behavior before owner approval.",
            environment_keys=["JIEJING_QUOTA_ENFORCEMENT_ENABLED", *billing_lifecycle_flags, "JIEJING_STRIPE_CUSTOMER_PORTAL_FAILURE_PATH_EVIDENCE_ID"],
            verification=["/billing/usage", "tools/test_jiejing_billing_webhook_subscription_state.py", "tools/test_jiejing_billing_quota_guardrail.py"],
            docs=[STRIPE_GO_LIVE_DOCS[1], STRIPE_GO_LIVE_DOCS[2]],
            owner_approval_required=True,
        ),
    ]


def _billing_live_cutover_step(
    key: str,
    title: str,
    ready: bool,
    *,
    owner: str,
    category: str,
    evidence_summary: str,
    next_action: str,
    environment_keys: list[str],
    verification: list[str],
    docs: list[str],
    owner_approval_required: bool = False,
    local_contract_proof: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "key": key,
        "title": title,
        "status": "ready" if ready else "blocked",
        "severity": "info" if ready else "blocker",
        "owner": owner,
        "category": category,
        "evidence_summary": evidence_summary,
        "next_action": next_action,
        "environment_keys": environment_keys,
        "verification": verification,
        "docs": docs,
        "owner_approval_required": owner_approval_required,
        "local_contract_proof": local_contract_proof or {},
        "external_resource_required": True,
        "triggers_real_charge": False,
        "charge_now_allowed": False,
        "frontend_gets_payment_secret": False,
        "raw_payment_secret_exposed": False,
        "secret_exposed": False,
    }


def _compact_billing_evidence(**values: Any) -> str:
    return "; ".join(f"{key}={value}" for key, value in values.items())


def build_billing_usage(settings: SaaSSettings, repository: SaaSRepository, *, company_id: str) -> dict[str, Any]:
    """Return merchant-visible usage and quota status without payment secrets."""

    subscription = repository.get_billing_subscription(company_id=company_id)
    provider = _provider()
    entitlement_active = _entitlement_active(provider=provider, subscription=subscription)
    plan_key = _selected_plan_key(subscription=subscription, entitlement_active=entitlement_active)
    plan = _plan_by_key(plan_key)
    usage = _company_usage(repository, company_id=company_id)
    quota_status = _quota_status(plan=plan, usage=usage)
    public_subscription = _public_subscription(subscription=subscription, provider=provider, entitlement_active=entitlement_active)
    from .media_credits import build_media_credit_summary

    return {
        "contract_version": "2026-05-19-billing-usage-quota",
        "environment": settings.environment,
        "company_id": company_id,
        "plan": {
            "key": plan["key"],
            "label": plan["label"],
            "source": _plan_source(provider=provider, subscription=subscription),
            "provider_plan_id": plan.get("provider_plan_id") or "",
            "amount_minor": int(plan.get("amount_minor") or 0),
            "currency": plan.get("currency") or "CNY",
            "duration_days": int(plan.get("duration_days") or 30),
            "team_member_quota": int(plan.get("team_member_quota") or 1),
            "batch_row_quota": int(plan.get("batch_row_quota") or 0),
            "media_points_included": int(plan.get("media_points_included") or 0),
            "includes_real_platform_writes": False,
        },
        "subscription": public_subscription,
        "quota_enforcement_enabled": _env_bool("JIEJING_QUOTA_ENFORCEMENT_ENABLED"),
        "usage": usage,
        "quota_status": quota_status,
        "blocked_units": [item["unit"] for item in quota_status if item["would_block_next_unit"]],
        "media_credits": build_media_credit_summary(repository, company_id=company_id),
        "subscription_quota_shutdown_state": _build_subscription_quota_shutdown_state(
            subscription=public_subscription,
            quota_enforcement_enabled=_env_bool("JIEJING_QUOTA_ENFORCEMENT_ENABLED"),
            blocked_units=[item["unit"] for item in quota_status if item["would_block_next_unit"]],
        ),
        "merchant_visible": True,
        "frontend_gets_payment_secret": False,
        "real_platform_writes_enabled": False,
        "secret_exposed": False,
    }


def _build_subscription_quota_shutdown_state(
    *,
    subscription: dict[str, Any],
    quota_enforcement_enabled: bool,
    blocked_units: list[str],
) -> dict[str, Any]:
    entitlement_active = bool(subscription.get("entitlement_active"))
    payment_attention_required = bool(subscription.get("payment_attention_required"))
    inactive_paid_subscription = quota_enforcement_enabled and not entitlement_active
    return {
        "contract_version": "2026-06-20-merchant-billing-shutdown-state",
        "subscription_status": subscription.get("status") or "subscription_missing",
        "entitlement_active": entitlement_active,
        "payment_attention_required": payment_attention_required,
        "quota_enforcement_enabled": quota_enforcement_enabled,
        "blocks_metered_work_when_inactive": inactive_paid_subscription,
        "block_reason": subscription.get("block_reason") or ("billing_subscription_not_active" if inactive_paid_subscription else ""),
        "blocked_units": blocked_units,
        "blocked_units_count": len(blocked_units),
        "merchant_visible": True,
        "creates_checkout_session": False,
        "calls_stripe_api": False,
        "triggers_real_charge": False,
        "charge_now_allowed": False,
        "frontend_gets_payment_secret": False,
        "secret_exposed": False,
    }


def evaluate_quota_action(
    settings: SaaSSettings,
    repository: SaaSRepository,
    *,
    company_id: str,
    action_unit: str,
    requested_units: int = 1,
) -> dict[str, Any]:
    """Evaluate whether a merchant action can proceed under the current plan."""

    usage_report = build_billing_usage(settings, repository, company_id=company_id)
    quota_key = QUOTA_ACTION_UNITS.get(action_unit)
    enforcement_enabled = bool(usage_report.get("quota_enforcement_enabled"))
    blocked = False
    reason = ""
    subscription = usage_report.get("subscription") if isinstance(usage_report.get("subscription"), dict) else {}
    if enforcement_enabled and subscription.get("entitlement_active") is False:
        blocked = True
        reason = str(subscription.get("block_reason") or "billing_subscription_not_active")
    elif enforcement_enabled and quota_key:
        plan = _plan_by_key(str((usage_report.get("plan") or {}).get("key") or "starter"))
        usage = usage_report.get("usage") if isinstance(usage_report.get("usage"), dict) else {}
        current = int(usage.get(_usage_key_for_quota(quota_key)) or 0)
        limit = int(plan.get(quota_key) or 0)
        blocked = limit > 0 and current + max(1, int(requested_units)) > limit
        if blocked:
            reason = f"{action_unit} would exceed {quota_key}"
    elif enforcement_enabled and not quota_key:
        reason = "unmetered_action_allowed"
    else:
        reason = "quota_enforcement_disabled"
    return {
        "action_unit": action_unit,
        "requested_units": max(1, int(requested_units)),
        "allowed": not blocked,
        "blocked": blocked,
        "reason": reason or "within_quota",
        "usage": usage_report,
        "merchant_visible": True,
        "real_platform_writes_enabled": False,
        "secret_exposed": False,
    }


def _company_usage(repository: SaaSRepository, *, company_id: str) -> dict[str, Any]:
    stores = repository.list_stores(company_id=company_id)
    tasks = repository.list_tasks(company_id=company_id)
    queue_jobs = repository.list_queue_jobs(company_id=company_id, limit=10000)
    reports = repository.list_reports(company_id=company_id)
    month_prefix = datetime.now(timezone.utc).strftime("%Y-%m")
    monthly_tasks = [item for item in tasks if str(item.get("created_at") or "").startswith(month_prefix)]
    provider_tasks = [
        item
        for item in monthly_tasks
        if str(item.get("task_type") or "") in {"provider_job", "ebay_read_only_sync", "ebay_read_only_live_plan", "model_value_rehearsal"}
    ]
    model_reports = [
        item
        for item in reports
        if str(item.get("created_at") or "").startswith(month_prefix)
        and str(item.get("report_type") or "") in {"market.report", "listing.package", "market.data_packet", "product.listing"}
    ]
    return {
        "period": month_prefix,
        "connected_store_count": len(stores),
        "monthly_task_count": len(monthly_tasks),
        "monthly_provider_job_count": len(provider_tasks),
        "monthly_model_report_assist_count": len(model_reports),
        "queue_job_count_sampled": len(queue_jobs),
        "secret_exposed": False,
    }


def _quota_status(*, plan: dict[str, Any], usage: dict[str, Any]) -> list[dict[str, Any]]:
    rows = [
        ("connected_store", "connected_store_count", "connected_store_quota"),
        ("ai_ceo_task", "monthly_task_count", "monthly_task_quota"),
        ("provider_job", "monthly_provider_job_count", "provider_job_quota"),
        ("model_report_assist", "monthly_model_report_assist_count", "provider_job_quota"),
    ]
    status = []
    for unit, usage_key, quota_key in rows:
        used = int(usage.get(usage_key) or 0)
        limit = int(plan.get(quota_key) or 0)
        remaining = max(0, limit - used) if limit > 0 else 0
        status.append(
            {
                "unit": unit,
                "used": used,
                "limit": limit,
                "remaining": remaining,
                "would_block_next_unit": limit > 0 and remaining <= 0,
            }
        )
    return status


def _usage_key_for_quota(quota_key: str) -> str:
    return {
        "connected_store_quota": "connected_store_count",
        "monthly_task_quota": "monthly_task_count",
        "provider_job_quota": "monthly_provider_job_count",
    }.get(quota_key, "")


def _plan_catalog_with_provider_ids() -> list[dict[str, Any]]:
    provider_plan_ids = billing_plan_ids()
    enriched = []
    for plan in PLAN_CATALOG:
        enriched.append({**plan, "provider_plan_id": provider_plan_ids.get(plan["key"], "")})
    return enriched


def _selected_plan_key(*, subscription: dict[str, Any] | None = None, entitlement_active: bool = False) -> str:
    entitlement_plan_keys = {item["key"] for item in PLAN_CATALOG} | set(LEGACY_PLAN_CATALOG)
    if entitlement_active and subscription:
        value = str(subscription.get("plan_key") or "").strip().lower()
        if value in entitlement_plan_keys:
            return value
    value = os.environ.get("JIEJING_DEFAULT_PLAN_KEY", "free").strip().lower() or "free"
    return value if value in {item["key"] for item in PLAN_CATALOG} else "free"


def _plan_by_key(plan_key: str) -> dict[str, Any]:
    plans = {item["key"]: item for item in _plan_catalog_with_provider_ids()}
    provider_plan_ids = billing_plan_ids()
    plans.update(
        {
            key: {**plan, "provider_plan_id": provider_plan_ids.get(key, "")}
            for key, plan in LEGACY_PLAN_CATALOG.items()
        }
    )
    return plans.get(plan_key) or plans["free"]


def _provider() -> str:
    raw = os.environ.get("JIEJING_BILLING_PROVIDER", "").strip().lower().replace("-", "_")
    return _canonical_provider(raw)


def _canonical_provider(raw: str) -> str:
    text = str(raw or "").strip().lower().replace("-", "_")
    aliases = {
        "lemonsqueezy": "lemon_squeezy",
        "lemon_squeezy": "lemon_squeezy",
        "stripe_mock": "stripe_test_mock",
        "stripe_test": "stripe_test_mock",
        "test_stripe": "stripe_test_mock",
        "mock_stripe": "stripe_test_mock",
        "mock_billing": "stripe_test_mock",
        "manual": "manual_beta",
        "manual_qr": "manual_beta",
        "manual_beta": "manual_beta",
    }
    return aliases.get(text, text)


def _entitlement_active(*, provider: str, subscription: dict[str, Any] | None) -> bool:
    if provider == "manual_seed":
        return True
    if provider not in {"stripe", "paddle", "lemon_squeezy"} and provider not in TEST_BILLING_PROVIDERS and provider not in PRIVATE_BETA_BILLING_PROVIDERS:
        return False
    return bool(subscription and subscription.get("entitlement_active") and not subscription.get("payment_attention_required"))


def _plan_source(*, provider: str, subscription: dict[str, Any] | None) -> str:
    if provider == "manual_seed":
        return "env_default_private_beta"
    if provider in PRIVATE_BETA_BILLING_PROVIDERS:
        return "manual_beta_confirmed_payment" if subscription else "manual_beta_payment_missing"
    if provider in TEST_BILLING_PROVIDERS:
        return "test_billing_provider_subscription" if subscription else "test_billing_subscription_missing"
    return "provider_subscription" if subscription else "provider_subscription_missing"


def _public_subscription(*, subscription: dict[str, Any] | None, provider: str, entitlement_active: bool) -> dict[str, Any]:
    if provider == "manual_seed":
        return {
            "provider": "manual_seed",
            "status": "private_beta_manual_seed",
            "entitlement_active": True,
            "payment_attention_required": False,
            "block_reason": "",
            "frontend_gets_payment_secret": False,
            "secret_exposed": False,
        }
    if provider in TEST_BILLING_PROVIDERS and not subscription:
        return {
            "provider": provider,
            "status": "test_subscription_missing",
            "entitlement_active": False,
            "payment_attention_required": False,
            "block_reason": "billing_test_subscription_not_rehearsed",
            "test_mode": True,
            "creates_real_charge": False,
            "frontend_gets_payment_secret": False,
            "secret_exposed": False,
        }
    if provider in PRIVATE_BETA_BILLING_PROVIDERS and not subscription:
        return {
            "provider": provider,
            "status": "manual_beta_payment_missing",
            "entitlement_active": False,
            "payment_attention_required": False,
            "block_reason": "manual_beta_payment_not_confirmed",
            "manual_reconciliation_required": True,
            "private_beta_only": True,
            "creates_real_charge": False,
            "frontend_gets_payment_secret": False,
            "secret_exposed": False,
        }
    if not subscription:
        return {
            "provider": provider or "not_selected",
            "status": "subscription_missing",
            "entitlement_active": False,
            "payment_attention_required": False,
            "block_reason": "billing_subscription_not_found",
            "frontend_gets_payment_secret": False,
            "secret_exposed": False,
        }
    status = str(subscription.get("status") or "unknown")
    subscription_json = subscription.get("subscription") if isinstance(subscription.get("subscription"), dict) else {}
    return {
        "provider": subscription.get("provider") or provider,
        "status": status,
        "plan_key": subscription.get("plan_key") or "unknown",
        "provider_customer_id_present": bool(subscription.get("provider_customer_id")),
        "provider_subscription_id_present": bool(subscription.get("provider_subscription_id")),
        "provider_plan_id_present": bool(subscription.get("provider_plan_id")),
        "entitlement_active": bool(entitlement_active),
        "payment_attention_required": bool(subscription.get("payment_attention_required")),
        "updated_at": subscription.get("updated_at"),
        "active_until": subscription_json.get("active_until") or "",
        "manual_reconciliation_required": bool(subscription_json.get("manual_reconciliation_required")),
        "private_beta_only": bool(subscription_json.get("private_beta_only")),
        "block_reason": "" if entitlement_active else "billing_subscription_not_active",
        "test_mode": provider in TEST_BILLING_PROVIDERS or subscription.get("provider") in TEST_BILLING_PROVIDERS,
        "creates_real_charge": False,
        "frontend_gets_payment_secret": False,
        "secret_exposed": False,
    }


def _next_actions(blockers: list[str]) -> list[str]:
    if not blockers:
        return ["monitor_plan_usage_and_provider_costs_before_public_launch"]
    actions = []
    if "billing_provider_not_selected" in blockers:
        actions.append("choose_external_subscription_provider_or_manual_seed_beta")
    if "billing_plans_not_published" in blockers:
        actions.append("publish_starter_operator_team_plan_ids")
    if "billing_webhook_not_configured" in blockers:
        actions.append("configure_signed_billing_webhook_before_paid_launch")
    if "stripe_checkout_not_ready" in blockers:
        actions.append("configure_stripe_checkout_success_cancel_urls_and_price_ids")
    if "stripe_customer_portal_not_ready" in blockers:
        actions.append("configure_stripe_customer_portal_return_url")
    if "billing_checkout_adapter_not_implemented_for_provider" in blockers:
        actions.append("use_stripe_first_or_implement_selected_provider_checkout_adapter")
    if "billing_test_checkout_not_ready" in blockers:
        actions.append("configure_stable_success_cancel_urls_for_no_charge_billing_rehearsal")
    if "billing_test_customer_portal_not_ready" in blockers:
        actions.append("configure_stable_portal_return_url_for_no_charge_billing_rehearsal")
    if "quota_enforcement_not_enabled" in blockers:
        actions.append("enable_quota_enforcement_for_tasks_provider_jobs_and_model_calls")
    return actions


def _env_bool(name: str) -> bool:
    return str(os.environ.get(name) or "").strip().lower() in {"1", "true", "yes", "on"}
