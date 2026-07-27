#!/usr/bin/env python3
"""Verify privacy-safe analytics and provider-neutral cost metering contracts."""

from __future__ import annotations

import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.operations_metering import (  # noqa: E402
    MeteredModelClient,
    build_provider_cost_alert_summary,
    build_provider_monitoring_aggregate_event,
    build_reliability_alert_summary,
    hash_analytics_identifier,
    media_cost_measurement,
    model_cost_measurement,
    public_search_cost_measurement,
    reconcile_reliability_alert_state,
    sanitize_analytics_event,
    sanitize_provider_telemetry,
)
import jiejing_saas.public_search_handoff as search_handoff_module  # noqa: E402
from jiejing_saas.public_search_handoff import build_public_search_market_handoff  # noqa: E402


class UsageClient:
    model = "serving-model"

    def __init__(self) -> None:
        self.calls = 0

    def generate_text(self, **_kwargs):  # noqa: ANN003, ANN201
        self.calls += 1
        return {
            "text": "ok",
            "_usage": {
                "input_tokens": 100 * self.calls,
                "output_tokens": 20 * self.calls,
                "total_tokens": 120 * self.calls,
            },
        }


class FailingUsageClient:
    model = "failing-model"

    def generate_text(self, **_kwargs):  # noqa: ANN003, ANN201
        raise TimeoutError("raw provider timeout detail must never be stored")


class CapturingRepository:
    def __init__(self) -> None:
        self.provider_costs = []

    def record_provider_cost(self, **kwargs):  # noqa: ANN003, ANN201
        self.provider_costs.append(kwargs)
        return kwargs


class SuccessfulSearchRunner:
    def __init__(self, **_kwargs) -> None:  # noqa: ANN003
        pass

    def run(self, **_kwargs):  # noqa: ANN003, ANN201
        return {
            "status": "completed_live_read",
            "provider_family": "replaceable-search-provider",
            "output_packet": {
                "packet_type": "market_public_search_signal",
                "records": [{"title": "Public market source", "url": "https://example.test/source"}],
                "result_count": 1,
            },
            "source_record": {"source_mode": "live_public_search"},
            "safety": {"live_provider_called": True, "raw_secret_read": True},
            "merchant_visible_summary": "One public source was normalized.",
            "secret_exposed": False,
        }


def main() -> int:
    missing_cost_budget = build_provider_cost_alert_summary(
        cost_total_minor=0,
        cost_coverage_complete=True,
        warning_minor=None,
        critical_minor=None,
    )
    assert missing_cost_budget["status"] == "blocked"
    assert missing_cost_budget["reason_codes"] == ["provider_cost_budget_not_configured"]
    assert missing_cost_budget["budget_configured"] is False

    incomplete_cost_coverage = build_provider_cost_alert_summary(
        cost_total_minor=25_000,
        cost_coverage_complete=False,
        warning_minor=10_000,
        critical_minor=20_000,
    )
    assert incomplete_cost_coverage["status"] == "attention"
    assert incomplete_cost_coverage["reason_codes"] == ["provider_cost_coverage_incomplete"]
    assert incomplete_cost_coverage["alert_required"] is True

    warning_cost = build_provider_cost_alert_summary(
        cost_total_minor=10_000,
        cost_coverage_complete=True,
        warning_minor=10_000,
        critical_minor=20_000,
    )
    assert warning_cost["status"] == "attention"
    assert warning_cost["reason_codes"] == ["provider_cost_warning_reached"]
    critical_cost = build_provider_cost_alert_summary(
        cost_total_minor=20_000,
        cost_coverage_complete=True,
        warning_minor=10_000,
        critical_minor=20_000,
    )
    assert critical_cost["status"] == "critical"
    assert critical_cost["reason_codes"] == ["provider_cost_critical_reached"]
    healthy_cost = build_provider_cost_alert_summary(
        cost_total_minor=9_999,
        cost_coverage_complete=True,
        warning_minor=10_000,
        critical_minor=20_000,
    )
    assert healthy_cost["status"] == "healthy"
    assert healthy_cost["alert_required"] is False

    monitoring_event = build_provider_monitoring_aggregate_event(
        reliability_summary={
            "status": "insufficient_data",
            "evaluated_count": 0,
            "attention_count": 0,
            "critical_count": 0,
            "items": [{"merchant_id": "must-not-pass"}],
        },
        cost_summary={
            **healthy_cost,
            "raw_cloud_id": "must-not-pass",
        },
        environment="staging",
        probe=True,
    )
    assert monitoring_event == {
        "event_type": "jiejing_provider_monitor_aggregate",
        "contract_version": "2026-07-17-provider-monitor-aggregate-v1",
        "environment": "staging",
        "probe": True,
        "reliability_status": "insufficient_data",
        "reliability_evaluated_count": 0,
        "reliability_attention_count": 0,
        "reliability_critical_count": 0,
        "cost_status": "healthy",
        "cost_coverage_complete": True,
        "cost_budget_configured": True,
        "cost_total_minor": 9_999,
    }
    assert "must-not-pass" not in str(monitoring_event)

    raw_visitor = "opaque-random-visitor"
    visitor_hash = hash_analytics_identifier(raw_visitor)
    assert len(visitor_hash) == 64 and raw_visitor not in visitor_hash
    event = sanitize_analytics_event(
        {
            "event_key": "page_view",
            "page_key": "landing",
            "visitor_id": raw_visitor,
            "session_id": "opaque-random-session",
            "event_id": "opaque-random-event",
            "metadata": {"entry_surface": "public_home", "raw_url": "must-not-pass"},
        }
    )
    assert event["visitor_hash"] == visitor_hash
    assert "raw_url" not in event["metadata"]

    client = MeteredModelClient(UsageClient())
    client.generate_text(system_prompt="not stored", user_prompt="not stored")
    client.generate_text(system_prompt="not stored", user_prompt="not stored")
    assert client.usage_summary() == {
        "request_count": 2,
        "input_tokens": 300,
        "output_tokens": 60,
        "total_tokens": 360,
    }
    reliability = client.reliability_summary()
    assert reliability["request_count"] == 2
    assert reliability["success_count"] == 2
    assert reliability["failure_count"] == 0
    assert reliability["p75_duration_ms"] >= 0
    assert "prompt" not in reliability and "response" not in reliability

    failing_client = MeteredModelClient(FailingUsageClient())
    try:
        failing_client.generate_text(system_prompt="must not persist", user_prompt="must not persist")
    except TimeoutError:
        pass
    else:
        raise AssertionError("failing provider call did not raise")
    failed_reliability = failing_client.reliability_summary()
    assert failed_reliability["request_count"] == 1
    assert failed_reliability["timeout_count"] == 1
    assert failed_reliability["error_classes"] == {"timeout": 1}
    assert "raw provider timeout detail" not in str(failed_reliability)

    telemetry = sanitize_provider_telemetry(
        scope="public_search",
        outcome="timeout",
        duration_ms=999999,
        error_class="TimeoutError: raw secret value",
    )
    assert telemetry == {
        "scope": "public_search",
        "outcome": "timeout",
        "duration_ms": 120000,
        "error_class": "timeout",
    }
    payment_telemetry = sanitize_provider_telemetry(
        scope="payment",
        outcome="success",
        duration_ms=3880,
    )
    assert payment_telemetry == {
        "scope": "payment",
        "outcome": "success",
        "duration_ms": 3880,
    }

    alert_summary = build_reliability_alert_summary(
        {
            "model": {
                "request_count": 10,
                "success_count": 9,
                "failure_count": 1,
                "timeout_count": 0,
                "sample_count": 10,
                "p75_duration_ms": 16_000,
            },
            "public_search": {
                "request_count": 10,
                "success_count": 6,
                "failure_count": 4,
                "timeout_count": 3,
                "sample_count": 10,
                "p75_duration_ms": 16_000,
            },
            "media_generation": {
                "request_count": 2,
                "success_count": 1,
                "failure_count": 1,
                "timeout_count": 1,
                "sample_count": 2,
                "p75_duration_ms": 120_000,
            },
            "payment": {
                "request_count": 10,
                "success_count": 10,
                "failure_count": 0,
                "timeout_count": 0,
                "sample_count": 10,
                "p75_duration_ms": 3880,
            },
        }
    )
    assert alert_summary["status"] == "critical"
    assert alert_summary["alert_required"] is True
    assert alert_summary["critical_count"] == 1
    assert alert_summary["attention_count"] == 1
    alerts_by_scope = {item["scope"]: item for item in alert_summary["items"]}
    assert alerts_by_scope["model"]["status"] == "attention"
    assert alerts_by_scope["model"]["reason_codes"] == ["high_latency"]
    assert alerts_by_scope["public_search"]["status"] == "critical"
    assert alerts_by_scope["public_search"]["failure_rate_percent"] == 40.0
    assert alerts_by_scope["public_search"]["timeout_rate_percent"] == 30.0
    assert set(alerts_by_scope["public_search"]["reason_codes"]) == {
        "high_latency",
        "high_failure_rate",
        "high_timeout_rate",
    }
    assert alerts_by_scope["media_generation"]["status"] == "insufficient_data"
    assert alerts_by_scope["media_generation"]["reason_codes"] == []
    assert alerts_by_scope["payment"]["status"] == "healthy"
    assert alerts_by_scope["payment"]["action_key"] == "none"
    assert alert_summary["prompts_stored"] is False
    assert alert_summary["queries_stored"] is False
    assert alert_summary["raw_errors_stored"] is False

    first_breach = reconcile_reliability_alert_state(
        previous_state=None,
        observed_alert=alerts_by_scope["public_search"],
        evaluated_at="2026-07-14T01:00:00+00:00",
    )
    assert first_breach["state"]["lifecycle_status"] == "pending"
    assert first_breach["state"]["consecutive_breach_count"] == 1
    assert first_breach["transition"] is None

    confirmed_breach = reconcile_reliability_alert_state(
        previous_state=first_breach["state"],
        observed_alert=alerts_by_scope["public_search"],
        evaluated_at="2026-07-14T01:01:00+00:00",
    )
    assert confirmed_breach["state"]["lifecycle_status"] == "open"
    assert confirmed_breach["state"]["severity"] == "critical"
    assert confirmed_breach["transition"]["transition_key"] == "opened"

    duplicate_breach = reconcile_reliability_alert_state(
        previous_state=confirmed_breach["state"],
        observed_alert=alerts_by_scope["public_search"],
        evaluated_at="2026-07-14T01:02:00+00:00",
    )
    assert duplicate_breach["state"]["lifecycle_status"] == "open"
    assert duplicate_breach["state"]["fingerprint"] == confirmed_breach["state"]["fingerprint"]
    assert duplicate_breach["transition"] is None

    attention_pending = reconcile_reliability_alert_state(
        previous_state=None,
        observed_alert=alerts_by_scope["model"],
        evaluated_at="2026-07-14T02:00:00+00:00",
    )
    attention_open = reconcile_reliability_alert_state(
        previous_state=attention_pending["state"],
        observed_alert=alerts_by_scope["model"],
        evaluated_at="2026-07-14T02:01:00+00:00",
    )
    critical_model_alert = {**alerts_by_scope["model"], "status": "critical", "reason_codes": ["high_latency"]}
    escalated = reconcile_reliability_alert_state(
        previous_state=attention_open["state"],
        observed_alert=critical_model_alert,
        evaluated_at="2026-07-14T02:02:00+00:00",
    )
    assert escalated["state"]["lifecycle_status"] == "open"
    assert escalated["state"]["severity"] == "critical"
    assert escalated["state"]["fingerprint"] != attention_open["state"]["fingerprint"]
    assert escalated["transition"]["transition_key"] == "escalated"

    healthy_observation = {
        **critical_model_alert,
        "status": "healthy",
        "reason_codes": [],
        "action_key": "none",
    }
    recovering = reconcile_reliability_alert_state(
        previous_state=escalated["state"],
        observed_alert=healthy_observation,
        evaluated_at="2026-07-14T02:03:00+00:00",
    )
    assert recovering["state"]["lifecycle_status"] == "recovering"
    assert recovering["state"]["severity"] == "critical"
    assert recovering["state"]["consecutive_healthy_count"] == 1
    assert recovering["transition"] is None

    sampling_during_recovery = reconcile_reliability_alert_state(
        previous_state=recovering["state"],
        observed_alert={**healthy_observation, "status": "insufficient_data"},
        evaluated_at="2026-07-14T02:04:00+00:00",
    )
    assert sampling_during_recovery["state"]["lifecycle_status"] == "recovering"
    assert sampling_during_recovery["state"]["fingerprint"] == recovering["state"]["fingerprint"]
    assert sampling_during_recovery["transition"] is None

    recovered = reconcile_reliability_alert_state(
        previous_state=sampling_during_recovery["state"],
        observed_alert=healthy_observation,
        evaluated_at="2026-07-14T02:05:00+00:00",
    )
    assert recovered["state"]["lifecycle_status"] == "healthy"
    assert recovered["state"]["severity"] == "none"
    assert recovered["state"]["fingerprint"] == ""
    assert recovered["transition"]["transition_key"] == "recovered"
    assert recovered["transition"]["fingerprint"] == recovering["state"]["fingerprint"]

    original_search_runner = search_handoff_module.ProviderJobRunner
    search_repository = CapturingRepository()
    try:
        search_handoff_module.ProviderJobRunner = SuccessfulSearchRunner
        handoff = build_public_search_market_handoff(
            settings=object(),
            repository=search_repository,
            company_id="company-metering",
            store={"store_id": "store-metering", "marketplace": "EBAY_US"},
            user_id="user-metering",
            body={"product": "private merchant query must not enter metering"},
        )
    finally:
        search_handoff_module.ProviderJobRunner = original_search_runner
    assert handoff["metering_status"] == "recorded"
    assert handoff["telemetry"]["scope"] == "public_search"
    assert handoff["telemetry"]["outcome"] == "success"
    assert len(search_repository.provider_costs) == 1
    metered_search = search_repository.provider_costs[0]
    assert metered_search["cost_category"] == "public_search"
    metered_serialized = str(metered_search).lower()
    assert "private merchant query" not in metered_serialized
    assert "replaceable-search-provider" not in metered_serialized

    previous_input_rate = os.environ.get("JIEJING_PLATFORM_MODEL_INPUT_CNY_PER_MILLION_TOKENS")
    previous_output_rate = os.environ.get("JIEJING_PLATFORM_MODEL_OUTPUT_CNY_PER_MILLION_TOKENS")
    previous_media_rate = os.environ.get("JIEJING_MEDIA_COST_CNY_PER_POINT")
    previous_search_rate = os.environ.get("JIEJING_PUBLIC_SEARCH_COST_CNY_PER_REQUEST")
    try:
        os.environ["JIEJING_PLATFORM_MODEL_INPUT_CNY_PER_MILLION_TOKENS"] = "2"
        os.environ["JIEJING_PLATFORM_MODEL_OUTPUT_CNY_PER_MILLION_TOKENS"] = "8"
        model_cost = model_cost_measurement(usage_owner="jiejing_platform_trial", usage=client.usage_summary())
        assert model_cost["cost_status"] == "configured_estimate"
        assert model_cost["cost_minor"] >= 0
        assert model_cost_measurement(usage_owner="merchant_account_byok", usage=client.usage_summary())["cost_status"] == "merchant_billed_directly"

        actual_media = media_cost_measurement(
            provider_output={"usage": {"actual_cost_cny_minor": 88}},
            media_points=12,
        )
        assert actual_media == {"cost_minor": 88, "currency": "CNY", "cost_status": "actual"}
        os.environ["JIEJING_MEDIA_COST_CNY_PER_POINT"] = "0.05"
        estimated_media = media_cost_measurement(provider_output={}, media_points=12)
        assert estimated_media == {"cost_minor": 60, "currency": "CNY", "cost_status": "configured_estimate"}
        os.environ["JIEJING_PUBLIC_SEARCH_COST_CNY_PER_REQUEST"] = "0.08"
        estimated_search = public_search_cost_measurement(provider_output={})
        assert estimated_search == {"cost_minor": 8, "currency": "CNY", "cost_status": "configured_estimate"}
    finally:
        _restore_env("JIEJING_PLATFORM_MODEL_INPUT_CNY_PER_MILLION_TOKENS", previous_input_rate)
        _restore_env("JIEJING_PLATFORM_MODEL_OUTPUT_CNY_PER_MILLION_TOKENS", previous_output_rate)
        _restore_env("JIEJING_MEDIA_COST_CNY_PER_POINT", previous_media_rate)
        _restore_env("JIEJING_PUBLIC_SEARCH_COST_CNY_PER_REQUEST", previous_search_rate)

    analytics_js = (ROOT / "assets" / "jiejing-first-party-analytics.js").read_text(encoding="utf-8")
    for forbidden in ("navigator.userAgent", "document.referrer", "location.href", "location.search"):
        assert forbidden not in analytics_js, forbidden
    for marker in ("/analytics/events", "signup_started", "pricing_view", "JiejingAnalytics"):
        assert marker in analytics_js, marker

    api_server = (ROOT / "jiejing_saas" / "api_server.py").read_text(encoding="utf-8")
    for marker in (
        'if path == "analytics/events":',
        "_check_public_analytics_rate_limit",
        "MeteredModelClient",
        "record_model_usage",
        '"signup_completed"',
    ):
        assert marker in api_server, marker
    worker = (ROOT / "jiejing_saas" / "worker.py").read_text(encoding="utf-8")
    assert "record_provider_cost" in worker
    assert "raw_provider_response_stored" not in analytics_js
    nginx_config = (ROOT / "deploy" / "nginx.public-staging.conf").read_text(encoding="utf-8")
    assert "|analytics|" in nginx_config, "public staging must proxy analytics events to the backend"

    print("PASS jiejing_operations_metering")
    return 0


def _restore_env(name: str, value: str | None) -> None:
    if value is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = value


if __name__ == "__main__":
    raise SystemExit(main())
