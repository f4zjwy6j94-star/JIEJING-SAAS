#!/usr/bin/env python3
"""Internal-only operations overview contract without fabricated analytics."""

from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.operations_metering import hash_analytics_identifier  # noqa: E402
from jiejing_saas.repository import SaaSRepository  # noqa: E402


OUT = ROOT / "output" / "jiejing-platform-operations-overview-test"


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    repository_source = (ROOT / "jiejing_saas" / "repository.py").read_text(encoding="utf-8")
    for marker in (
        "datetime(occurred_at) >= datetime(?)",
        "date(datetime(occurred_at), '+8 hours')",
        "to_char(occurred_at AT TIME ZONE 'Asia/Shanghai', 'YYYY-MM-DD')",
        "analytics_period_started_utc",
    ):
        if marker not in repository_source:
            return fail(f"daily operations analytics is missing dialect-aware timezone semantics: {marker}")
    if "substr(cast(occurred_at as text), 1, 10)" in repository_source:
        return fail("daily operations analytics must not group timestamptz rows by their stored text prefix")
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True, exist_ok=True)
    midnight_repo = SaaSRepository(OUT / "midnight.sqlite")
    midnight_event_hash = hash_analytics_identifier("beijing-midnight-boundary-event")
    midnight_repo.record_platform_analytics_event(
        event_key="page_view",
        page_key="landing",
        event_id_hash=midnight_event_hash,
        visitor_hash=hash_analytics_identifier("beijing-midnight-visitor"),
        session_hash=hash_analytics_identifier("beijing-midnight-session"),
    )
    with midnight_repo._connect() as conn:
        conn.execute(
            "update platform_analytics_events set occurred_at = ? where event_id_hash = ?",
            ("2026-08-04T01:15:00+08:00", midnight_event_hash),
        )
    legacy_utc_hash = hash_analytics_identifier("beijing-midnight-legacy-utc-event")
    midnight_repo.record_platform_analytics_event(
        event_key="page_view",
        page_key="landing",
        event_id_hash=legacy_utc_hash,
        visitor_hash=hash_analytics_identifier("beijing-midnight-legacy-utc-visitor"),
        session_hash=hash_analytics_identifier("beijing-midnight-legacy-utc-session"),
    )
    with midnight_repo._connect() as conn:
        conn.execute(
            "update platform_analytics_events set occurred_at = ? where event_id_hash = ?",
            ("2026-08-03T17:15:00+00:00", legacy_utc_hash),
        )
    midnight_overview = midnight_repo.platform_operations_overview(
        period_days=1,
        now_utc=datetime(2026, 8, 3, 17, 30, tzinfo=timezone.utc),
    )
    midnight_traffic = midnight_overview.get("traffic_analytics", {})
    midnight_trend = midnight_traffic.get("daily_trend") or []
    if (
        midnight_traffic.get("page_views") != 2
        or len(midnight_trend) != 1
        or midnight_trend[0].get("day") != "2026-08-04"
        or midnight_trend[0].get("page_views") != 2
    ):
        return fail(f"Beijing midnight analytics window is inconsistent: {midnight_overview}")
    repo = SaaSRepository(OUT / "saas.sqlite")
    fixture = repo.create_user_with_company(
        email="platform-operations@jiejing-shop.cn",
        password="platform-operations-password",
        company_name="Jiejing Platform Operations Test",
    )
    synthetic_fixture = repo.create_user_with_company(
        email="platform-operations-smoke@jiejing.local",
        password="platform-operations-smoke-password",
        company_name="Jiejing Synthetic Operations Test",
    )
    acceptance_only_fixture = repo.create_user_with_company(
        email="platform-operations-acceptance@jiejing-shop.cn",
        password="platform-operations-acceptance-password",
        company_name="Jiejing Payment Acceptance Test",
    )
    repo.apply_media_credit_operation(
        company_id=fixture["company"]["company_id"],
        user_id=fixture["user"]["user_id"],
        operation_type="grant",
        points=300,
        idempotency_key="platform-operations-welcome-v1",
        reference_type="onboarding",
        reference_id="welcome",
    )
    company_id = fixture["company"]["company_id"]
    user_id = fixture["user"]["user_id"]
    synthetic_company_id = synthetic_fixture["company"]["company_id"]
    synthetic_user_id = synthetic_fixture["user"]["user_id"]
    repo.apply_media_credit_operation(
        company_id=synthetic_company_id,
        user_id=synthetic_user_id,
        operation_type="grant",
        points=900,
        idempotency_key="platform-operations-synthetic-welcome-v1",
        reference_type="onboarding",
        reference_id="synthetic-welcome",
    )
    store = repo.create_store(
        company_id=company_id,
        user_id=user_id,
        payload={"platform": "ebay", "store_name": "Verified merchant store", "marketplace": "EBAY_US"},
    )
    legacy_chat_task = repo.create_task(
        company_id=company_id,
        store_id=store["store_id"],
        user_id=user_id,
        task_type="merchant_ceo_chat",
        title="Legacy unmetered chat fixture",
        input_data={"test_fixture": True},
    )
    legacy_task_at = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    with repo._connect() as conn:
        conn.execute(
            "update tasks set created_at = ?, updated_at = ? where task_id = ?",
            (legacy_task_at, legacy_task_at, legacy_chat_task["task_id"]),
        )
        conn.commit()
    repo.create_platform_connection(
        company_id=company_id,
        store_id=store["store_id"],
        user_id=user_id,
        payload={"platform": "ebay", "connection_type": "oauth", "status": "draft_save_authorized"},
    )
    for index, event_key in enumerate(("page_view", "pricing_view", "signup_started", "signup_completed"), start=1):
        repo.record_platform_analytics_event(
            event_key=event_key,
            page_key="register" if "signup" in event_key else "landing",
            event_id_hash=hash_analytics_identifier(f"event-{index}"),
            visitor_hash=hash_analytics_identifier("visitor-one"),
            session_hash=hash_analytics_identifier("session-one"),
            company_id=company_id if event_key == "signup_completed" else None,
            user_id=user_id if event_key == "signup_completed" else None,
        )
    for index, lcp_ms in enumerate((100, 200, 300, 400), start=1):
        repo.record_platform_analytics_event(
            event_key="performance_sample",
            page_key="workbench",
            event_id_hash=hash_analytics_identifier(f"performance-page-{index}"),
            visitor_hash=hash_analytics_identifier("visitor-one"),
            session_hash=hash_analytics_identifier("session-one"),
            metadata={
                "performance_scope": "page_load",
                "outcome": "success",
                "ttfb_ms": 50 + index,
                "lcp_ms": lcp_ms,
                "cls_milli": index,
            },
        )
    for index, outcome in enumerate(("success", "error"), start=1):
        repo.record_platform_analytics_event(
            event_key="performance_sample",
            page_key="workbench",
            event_id_hash=hash_analytics_identifier(f"performance-settings-{index}"),
            visitor_hash=hash_analytics_identifier("visitor-one"),
            session_hash=hash_analytics_identifier("session-one"),
            metadata={
                "performance_scope": "settings_module",
                "outcome": outcome,
                "duration_ms": 100 * index,
            },
        )
    repo.record_model_usage(
        company_id=company_id,
        user_id=user_id,
        task_id=None,
        usage_owner="jiejing_platform_trial",
        model_family="provider_neutral",
        model_label="serving-model",
        request_count=1,
        input_tokens=100,
        output_tokens=50,
        total_tokens=150,
        cost_minor=12,
        currency="CNY",
        cost_status="configured_estimate",
        idempotency_key="model-usage-one",
        details={
            "reliability": {
                "scope": "model",
                "request_count": 1,
                "success_count": 1,
                "failure_count": 0,
                "timeout_count": 0,
                "p75_duration_ms": 240,
                "max_duration_ms": 240,
                "error_classes": {},
            }
        },
    )
    repo.record_provider_cost(
        company_id=company_id,
        user_id=user_id,
        task_id=None,
        reference_type="media_job",
        reference_id="media-job-one",
        cost_category="media_generation",
        resource_type="image",
        unit_count=1,
        media_points=12,
        cost_minor=34,
        currency="CNY",
        cost_status="actual",
        idempotency_key="provider-cost-one",
        details={
            "telemetry": {
                "scope": "media_generation",
                "outcome": "success",
                "duration_ms": 1200,
            }
        },
    )
    repo.record_provider_cost(
        company_id=company_id,
        user_id=user_id,
        task_id=None,
        reference_type="public_search_request",
        reference_id="search-one",
        cost_category="public_search",
        resource_type="request",
        unit_count=1,
        media_points=0,
        cost_minor=8,
        currency="CNY",
        cost_status="configured_estimate",
        idempotency_key="provider-search-one",
        details={
            "telemetry": {
                "scope": "public_search",
                "outcome": "timeout",
                "duration_ms": 3200,
                "error_class": "timeout",
            }
        },
    )
    repo.record_provider_cost(
        company_id=company_id,
        user_id=user_id,
        task_id=None,
        reference_type="payment_provider_call",
        reference_id="commercial-order-one",
        cost_category="payment_processing",
        resource_type="checkout_create",
        unit_count=1,
        media_points=0,
        cost_minor=0,
        currency="CNY",
        cost_status="not_applicable",
        idempotency_key="provider-payment-one",
        details={
            "telemetry": {
                "scope": "payment",
                "outcome": "success",
                "duration_ms": 880,
            }
        },
    )
    fixture_paid_at = datetime.now(timezone.utc).isoformat()
    repo.create_domestic_billing_order_record(
        order_id="acceptance-order-one",
        company_id=company_id,
        user_id=user_id,
        provider="wechat_pay_native",
        plan_key="starter",
        amount_minor=100,
        currency="CNY",
        duration_days=30,
        status="paid",
        idempotency_key_hash="acceptance-order-one-hash",
        order={"live_acceptance_test": True, "display_name": "controlled acceptance"},
        paid_at=fixture_paid_at,
    )
    repo.create_domestic_billing_order_record(
        order_id="commercial-order-one",
        company_id=company_id,
        user_id=user_id,
        provider="wechat_pay_native",
        plan_key="starter",
        amount_minor=9900,
        currency="CNY",
        duration_days=30,
        status="paid",
        idempotency_key_hash="commercial-order-one-hash",
        order={"live_acceptance_test": False, "display_name": "Jiejing Starter"},
        paid_at=fixture_paid_at,
    )
    repo.apply_billing_webhook_event(
        event={
            "provider": "wechat_pay_native",
            "event_type": "subscription.activated",
            "event_id": "commercial-subscription-one",
            "company_id": company_id,
            "provider_customer_id": "commercial-customer-one",
            "provider_subscription_id": "commercial-subscription-one",
            "provider_plan_id": "starter",
            "plan_key": "starter",
            "subscription_status": "active",
        }
    )
    repo.apply_billing_webhook_event(
        event={
            "provider": "stripe_test_mock",
            "event_type": "subscription.activated",
            "event_id": "synthetic-subscription-one",
            "company_id": synthetic_company_id,
            "provider_customer_id": "synthetic-customer-one",
            "provider_subscription_id": "synthetic-subscription-one",
            "provider_plan_id": "starter-test",
            "plan_key": "starter",
            "subscription_status": "active",
        }
    )
    repo.apply_billing_webhook_event(
        event={
            "provider": "wechat_pay_native",
            "event_type": "subscription.activated",
            "event_id": "acceptance-subscription-one",
            "company_id": acceptance_only_fixture["company"]["company_id"],
            "provider_customer_id": "acceptance-customer-one",
            "provider_subscription_id": "acceptance-subscription-one",
            "provider_plan_id": "starter",
            "plan_key": "starter",
            "subscription_status": "active",
        }
    )
    fast_route_task = repo.create_task(
        company_id=company_id,
        store_id=store["store_id"],
        user_id=user_id,
        task_type="merchant_ceo_chat",
        title="AI CEO fast chat turn without model usage",
        input_data={
            "provider_key": "fast_route",
            "model_usage_required": False,
            "secret_exposed": False,
        },
    )
    repo.update_task_status(
        task_id=fast_route_task["task_id"],
        company_id=company_id,
        status="completed",
        output={"status": "capability_status_answered", "secret_exposed": False},
        audit_summary="Fast route completed without a model call.",
    )
    fast_route_monitoring = repo.provider_monitoring_snapshot(now_utc=datetime.now(timezone.utc))
    if (
        fast_route_monitoring.get("current_unmetered_model_tasks") != 0
        or fast_route_monitoring.get("cost_coverage_complete") is not True
    ):
        return fail(f"model-free fast routes must not create false metering alerts: {fast_route_monitoring}")
    fast_route_overview = repo.platform_operations_overview()
    fast_route_economics = fast_route_overview.get("unit_economics", {})
    if (
        fast_route_economics.get("current_unmetered_model_tasks") != 0
        or fast_route_economics.get("current_metering_health") != "ready"
    ):
        return fail(f"model-free fast routes must not degrade platform metering health: {fast_route_economics}")
    provider_monitoring = repo.provider_monitoring_snapshot(
        reliability_window_minutes=30,
        cost_window_hours=24,
        now_utc=datetime.now(timezone.utc),
    )
    monitored_reliability = provider_monitoring.get("reliability", {})
    if monitored_reliability.get("model", {}).get("request_count") != 1:
        return fail(f"focused provider monitor lost eligible model telemetry: {provider_monitoring}")
    if monitored_reliability.get("public_search", {}).get("request_count") != 1:
        return fail(f"focused provider monitor lost eligible search telemetry: {provider_monitoring}")
    if monitored_reliability.get("media_generation", {}).get("request_count") != 1:
        return fail(f"focused provider monitor lost eligible media telemetry: {provider_monitoring}")
    if monitored_reliability.get("payment", {}).get("request_count") != 1:
        return fail(f"focused provider monitor lost eligible payment telemetry: {provider_monitoring}")
    if monitored_reliability.get("alerts", {}).get("status") != "insufficient_data":
        return fail(f"focused low-volume telemetry must remain insufficient_data: {provider_monitoring}")
    if provider_monitoring.get("cost_total_minor") != 54 or provider_monitoring.get("cost_coverage_complete") is not True:
        return fail(f"focused 24-hour cost aggregate is wrong: {provider_monitoring}")
    overview = repo.platform_operations_overview()
    if overview.get("audience") != "platform_internal_admin" or overview.get("merchant_navigation_visible") is not False:
        return fail(f"overview is not internal-only: {overview}")
    if overview.get("accounts", {}).get("registered_users") != 2:
        return fail(f"registered user aggregate is wrong: {overview}")
    if overview.get("accounts", {}).get("connected_stores") != 1:
        return fail(f"authorized store aggregate is wrong: {overview}")
    if overview.get("media_points", {}).get("balance_points") != 300:
        return fail(f"media point aggregate is wrong: {overview}")
    traffic = overview.get("traffic_analytics", {})
    if traffic.get("status") != "instrumented" or traffic.get("visitors") != 1 or traffic.get("signup_completed") != 1:
        return fail(f"traffic aggregation is wrong: {traffic}")
    if traffic.get("raw_ip_stored") is not False or traffic.get("user_agent_stored") is not False:
        return fail(f"traffic privacy boundary is wrong: {traffic}")
    daily_trend = traffic.get("daily_trend", [])
    if len(daily_trend) != 30 or daily_trend[-1].get("visitors") != 1 or daily_trend[-1].get("page_views") != 1:
        return fail(f"traffic daily trend is incomplete: {daily_trend}")
    page_breakdown = {item.get("page_key"): item for item in traffic.get("page_breakdown", [])}
    if page_breakdown.get("landing", {}).get("pricing_views") != 1:
        return fail(f"landing traffic breakdown is wrong: {page_breakdown}")
    if page_breakdown.get("register", {}).get("signup_completed") != 1:
        return fail(f"registration funnel breakdown is wrong: {page_breakdown}")
    if traffic.get("automated_browser_collection_enabled") is not False:
        return fail(f"automated browser traffic must be excluded from first-party analytics: {traffic}")
    performance = overview.get("performance_analytics", {})
    if performance.get("sample_count") != 6 or performance.get("page_load", {}).get("p75", {}).get("lcp_ms") != 300:
        return fail(f"performance P75 aggregation is wrong: {performance}")
    settings_performance = performance.get("settings_module", {})
    if settings_performance.get("success_count") != 1 or settings_performance.get("error_count") != 1:
        return fail(f"settings performance aggregation is wrong: {settings_performance}")
    if performance.get("raw_url_stored") is not False or performance.get("prompt_or_response_stored") is not False:
        return fail(f"performance privacy boundary is wrong: {performance}")
    model_cost = overview.get("model_cost_analytics", {})
    if model_cost.get("byok_tokens_are_merchant_billed") is not True or model_cost.get("platform_trial_tokens") != 150:
        return fail(f"model cost boundary is misleading: {model_cost}")
    if overview.get("provider_cost_analytics", {}).get("media_cost_minor") != 34:
        return fail(f"provider cost aggregate is wrong: {overview}")
    reliability = overview.get("provider_reliability_analytics", {})
    if reliability.get("model", {}).get("p75_duration_ms") != 240:
        return fail(f"model reliability aggregate is wrong: {reliability}")
    if reliability.get("public_search", {}).get("timeout_count") != 1:
        return fail(f"public search reliability aggregate is wrong: {reliability}")
    if reliability.get("media_generation", {}).get("success_count") != 1:
        return fail(f"media reliability aggregate is wrong: {reliability}")
    if reliability.get("payment", {}).get("success_count") != 1:
        return fail(f"payment reliability aggregate is wrong: {reliability}")
    if reliability.get("prompts_stored") is not False or reliability.get("raw_errors_stored") is not False:
        return fail(f"provider reliability privacy boundary is wrong: {reliability}")
    reliability_alerts = reliability.get("alerts", {})
    if reliability_alerts.get("status") != "insufficient_data" or reliability_alerts.get("alert_required") is not False:
        return fail(f"low-volume reliability telemetry must not raise a false alert: {reliability_alerts}")
    if reliability_alerts.get("critical_count") != 0 or reliability_alerts.get("attention_count") != 0:
        return fail(f"low-volume reliability alert counters are wrong: {reliability_alerts}")
    if reliability_alerts.get("queries_stored") is not False or reliability_alerts.get("raw_errors_stored") is not False:
        return fail(f"reliability alert privacy boundary is wrong: {reliability_alerts}")
    reliability_lifecycle = reliability.get("lifecycle", {})
    if reliability_lifecycle.get("status") != "ready_no_evaluations":
        return fail(f"GET overview must not advance an unevaluated lifecycle: {reliability_lifecycle}")
    if reliability_lifecycle.get("merchant_navigation_visible") is not False:
        return fail(f"reliability lifecycle must stay internal-only: {reliability_lifecycle}")
    subscriptions = overview.get("subscriptions", [])
    if subscriptions != [{"plan_key": "starter", "status": "active", "count": 1}]:
        return fail(f"commercial subscription aggregate is wrong: {subscriptions}")
    if overview.get("accounts", {}).get("active_merchant_companies") != 1:
        return fail(f"period active merchant aggregate is wrong: {overview.get('accounts')}")
    payments = overview.get("domestic_payments", [])
    if payments != [{"status": "paid", "count": 1, "amount_minor": 9900, "currency": "CNY"}]:
        return fail(f"commercial payment aggregate is wrong: {payments}")
    unit_economics = overview.get("unit_economics", {})
    if (
        unit_economics.get("paid_company_count") != 1
        or unit_economics.get("active_subscriber_company_count") != 1
        or unit_economics.get("normalized_mrr_minor") != 9900
        or unit_economics.get("mrr_status") != "ready"
    ):
        return fail(f"paid-company or MRR aggregate is wrong: {unit_economics}")
    if unit_economics.get("contribution_margin_minor") is not None or unit_economics.get("status") != "partial":
        return fail(f"unknown historical costs must keep contribution margin incomplete: {unit_economics}")
    if (
        unit_economics.get("current_metering_health") != "ready"
        or unit_economics.get("legacy_unmetered_model_tasks") != 1
        or unit_economics.get("current_unmetered_model_tasks") != 0
        or not unit_economics.get("metering_started_at")
    ):
        return fail(f"historical and current model metering are not separated: {unit_economics}")
    data_quality = overview.get("data_quality", {})
    if data_quality.get("synthetic_test_accounts_excluded") != 1:
        return fail(f"synthetic account exclusion is wrong: {data_quality}")
    if data_quality.get("acceptance_orders_excluded") != 1 or data_quality.get("test_subscriptions_excluded") != 2:
        return fail(f"non-commercial billing exclusion is wrong: {data_quality}")
    one_day = repo.platform_operations_overview(period_days=1)
    if one_day.get("subscriptions") != subscriptions:
        return fail(f"current subscriptions must not disappear when the revenue period changes: {one_day}")
    if one_day.get("unit_economics", {}).get("normalized_mrr_minor") != 9900:
        return fail(f"MRR must use current subscription evidence, not period revenue only: {one_day}")
    serialized = json.dumps(overview, ensure_ascii=False).lower()
    for forbidden in ("api_key", "client_secret", "refresh_token", "private_key", "visitor-one", "session-one", "\"fal\"", "raw provider timeout detail"):
        if forbidden in serialized:
            return fail(f"operations overview leaked secret or replaceable provider detail: {forbidden}")

    rehearsal_task = repo.create_task(
        company_id=company_id,
        store_id=store["store_id"],
        user_id=user_id,
        task_type="model_value_rehearsal",
        title="Excluded rehearsal telemetry",
        input_data={"rehearsal": True},
    )
    repo.record_model_usage(
        company_id=company_id,
        user_id=user_id,
        task_id=rehearsal_task["task_id"],
        usage_owner="jiejing_platform_trial",
        model_family="provider_neutral",
        model_label="rehearsal-model",
        request_count=8,
        input_tokens=800,
        output_tokens=80,
        total_tokens=880,
        cost_minor=999,
        currency="CNY",
        cost_status="configured_estimate",
        idempotency_key="excluded-model-rehearsal",
        details={
            "reliability": {
                "request_count": 8,
                "success_count": 0,
                "timeout_count": 8,
                "p75_duration_ms": 120_000,
            }
        },
    )
    repo.record_provider_cost(
        company_id=synthetic_company_id,
        user_id=synthetic_user_id,
        task_id=None,
        reference_type="public_search_request",
        reference_id="excluded-synthetic-search",
        cost_category="public_search",
        resource_type="request",
        unit_count=1,
        media_points=0,
        cost_minor=999,
        currency="CNY",
        cost_status="actual",
        idempotency_key="excluded-synthetic-search",
        details={"telemetry": {"scope": "public_search", "outcome": "timeout", "duration_ms": 120_000}},
    )
    with repo._connect() as conn:
        conn.execute(
            "update users set default_company_id = ? where user_id = ?",
            (company_id, synthetic_user_id),
        )
    repo.record_provider_cost(
        company_id=company_id,
        user_id=synthetic_user_id,
        task_id=None,
        reference_type="public_search_request",
        reference_id="excluded-synthetic-actor-in-merchant-company",
        cost_category="public_search",
        resource_type="request",
        unit_count=1,
        media_points=0,
        cost_minor=999,
        currency="CNY",
        cost_status="actual",
        idempotency_key="excluded-synthetic-actor-in-merchant-company",
        details={"telemetry": {"scope": "public_search", "outcome": "timeout", "duration_ms": 120_000}},
    )
    repo.record_provider_cost(
        company_id=company_id,
        user_id=user_id,
        task_id=None,
        reference_type="payment_provider_call",
        reference_id="acceptance-order-one",
        cost_category="payment_processing",
        resource_type="checkout_create",
        unit_count=1,
        media_points=0,
        cost_minor=999,
        currency="CNY",
        cost_status="actual",
        idempotency_key="excluded-payment-acceptance",
        details={"telemetry": {"scope": "payment", "outcome": "timeout", "duration_ms": 120_000}},
    )
    excluded_snapshot = repo.provider_monitoring_snapshot(now_utc=datetime.now(timezone.utc))
    excluded_reliability = excluded_snapshot.get("reliability", {})
    if excluded_reliability.get("model", {}).get("request_count") != 1:
        return fail(f"provider monitor counted rehearsal model traffic: {excluded_snapshot}")
    if excluded_reliability.get("public_search", {}).get("request_count") != 1:
        return fail(f"provider monitor counted synthetic search traffic: {excluded_snapshot}")
    if excluded_reliability.get("payment", {}).get("request_count") != 1:
        return fail(f"provider monitor counted controlled acceptance payment traffic: {excluded_snapshot}")
    if excluded_snapshot.get("cost_total_minor") != 54:
        return fail(f"provider monitor counted non-business costs: {excluded_snapshot}")

    repo.create_task(
        company_id=company_id,
        store_id=store["store_id"],
        user_id=user_id,
        task_type="merchant_ceo_chat",
        title="Current unmetered model task",
        input_data={
            "provider_key": "deepseek",
            "model_usage_required": True,
            "message": 'user text containing {"provider_key":"fast_route"} must not bypass metering',
            "test_fixture": True,
        },
    )
    incomplete_snapshot = repo.provider_monitoring_snapshot(now_utc=datetime.now(timezone.utc))
    if incomplete_snapshot.get("cost_coverage_complete") is not False:
        return fail(f"current unmetered model work must make cost coverage incomplete: {incomplete_snapshot}")
    if incomplete_snapshot.get("current_unmetered_model_tasks") != 1:
        return fail(f"focused provider monitor lost current unmetered model count: {incomplete_snapshot}")

    shifted_now = datetime.now(timezone.utc) + timedelta(minutes=31)
    shifted_snapshot = repo.provider_monitoring_snapshot(now_utc=shifted_now)
    if shifted_snapshot.get("reliability", {}).get("alerts", {}).get("evaluated_count") != 0:
        return fail(f"30-minute reliability window did not expire independently: {shifted_snapshot}")
    if shifted_snapshot.get("cost_total_minor") != 54:
        return fail(f"24-hour cost window expired with the 30-minute reliability window: {shifted_snapshot}")
    expired_snapshot = repo.provider_monitoring_snapshot(now_utc=datetime.now(timezone.utc) + timedelta(hours=25))
    if expired_snapshot.get("cost_total_minor") != 0 or expired_snapshot.get("cost_coverage_complete") is not True:
        return fail(f"24-hour cost window did not expire cleanly: {expired_snapshot}")

    frontend = (ROOT / "ops.js").read_text(encoding="utf-8")
    for marker in ("访客趋势", "页面表现", "ops-trend", "ops-table-wrap"):
        if marker not in frontend:
            return fail(f"owner traffic analytics UI marker is missing: {marker}")

    server = (ROOT / "jiejing_saas" / "api_server.py").read_text(encoding="utf-8")
    route_start = server.index('if path == "owner/operations-overview":')
    route_end = server.index("\n\n", route_start)
    route = server[route_start:route_end]
    if "_require_platform_internal_admin" not in route:
        return fail("operations overview endpoint is missing the internal-admin gate")
    for owner_route in (
        'if path == "owner/operations-reliability-alerts/reconcile":',
        'if path == "owner/operations-reliability-alerts/acknowledge":',
    ):
        route_start = server.index(owner_route)
        route = server[route_start : route_start + 1800]
        if "_require_platform_internal_admin" not in route:
            return fail(f"reliability duty endpoint is missing the internal-admin gate: {owner_route}")
        if '"external_provider_action_triggered": False' not in route:
            return fail(f"reliability duty endpoint is missing the no-external-action boundary: {owner_route}")

    app_js = (ROOT / "app.js").read_text(encoding="utf-8")
    ops_js = (ROOT / "ops.js").read_text(encoding="utf-8")
    for marker in (
        "function renderOverview",
        "function renderReliability",
        "owner/operations-overview?period_days=",
        "待处理告警",
        "系统可靠性",
        "页面性能样本",
        "供应商中性指标",
        "不记录原始错误、查询或回复",
    ):
        if marker not in ops_js:
            return fail(f"internal operations frontend is missing marker: {marker}")
    for forbidden in ("/owner/operations-overview", "renderSaasOwnerOperationsOverviewPanel", 'id: "owner_ops"'):
        if forbidden in app_js:
            return fail(f"merchant workbench still exposes internal operations marker: {forbidden}")

    print("PASS jiejing_platform_operations_overview")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
