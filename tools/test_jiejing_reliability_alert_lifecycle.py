#!/usr/bin/env python3
"""Durable, deduplicated internal reliability alert lifecycle contract."""

from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.repository import SaaSRepository  # noqa: E402


OUT = ROOT / "output" / "jiejing-reliability-alert-lifecycle-test"


def critical_search_alert() -> dict:
    return {
        "scope": "public_search",
        "status": "critical",
        "request_count": 10,
        "sample_count": 10,
        "p75_duration_ms": 18_000,
        "failure_count": 4,
        "timeout_count": 3,
        "failure_rate_percent": 40.0,
        "timeout_rate_percent": 30.0,
        "reason_codes": ["high_latency", "high_failure_rate", "high_timeout_rate"],
        "action_key": "review_search_health_and_fallback",
    }


def healthy_search_alert() -> dict:
    return {
        **critical_search_alert(),
        "status": "healthy",
        "p75_duration_ms": 500,
        "failure_count": 0,
        "timeout_count": 0,
        "failure_rate_percent": 0.0,
        "timeout_rate_percent": 0.0,
        "reason_codes": [],
        "action_key": "none",
    }


def main() -> int:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True, exist_ok=True)
    repo = SaaSRepository(OUT / "saas.sqlite")

    first_lease = repo.acquire_provider_monitoring_lease(
        scheduler_key="provider-monitor",
        owner_hash="process-a-hash",
        lease_seconds=60,
        now_epoch=100,
    )
    assert first_lease["acquired"] is True
    contended_lease = repo.acquire_provider_monitoring_lease(
        scheduler_key="provider-monitor",
        owner_hash="process-b-hash",
        lease_seconds=60,
        now_epoch=120,
    )
    assert contended_lease == {
        "acquired": False,
        "status": "skipped_lease_contended",
        "secret_exposed": False,
    }
    expired_lease = repo.acquire_provider_monitoring_lease(
        scheduler_key="provider-monitor",
        owner_hash="process-b-hash",
        lease_seconds=60,
        now_epoch=161,
    )
    assert expired_lease["acquired"] is True
    rejected_completion = repo.complete_provider_monitoring_evaluation(
        scheduler_key="provider-monitor",
        owner_hash="process-a-hash",
        evaluated_at="2026-07-17T00:00:00+00:00",
        exported_at="2026-07-17T00:00:01+00:00",
        outcome="exported",
        snapshot={"event_type": "jiejing_provider_monitor_aggregate", "probe": False},
    )
    assert rejected_completion["updated"] is False
    completed = repo.complete_provider_monitoring_evaluation(
        scheduler_key="provider-monitor",
        owner_hash="process-b-hash",
        evaluated_at="2026-07-17T00:00:00+00:00",
        exported_at="2026-07-17T00:00:01+00:00",
        outcome="exported",
        snapshot={"event_type": "jiejing_provider_monitor_aggregate", "probe": False},
    )
    assert completed["updated"] is True
    monitor_state = repo.provider_monitoring_state(scheduler_key="provider-monitor")
    assert monitor_state["last_outcome"] == "exported"
    assert monitor_state["last_evaluated_at"] == "2026-07-17T00:00:00+00:00"
    assert monitor_state["last_exported_at"] == "2026-07-17T00:00:01+00:00"
    assert monitor_state["aggregate"]["probe"] is False
    serialized_monitor_state = json.dumps(monitor_state, ensure_ascii=False).lower()
    assert "process-a-hash" not in serialized_monitor_state
    assert "process-b-hash" not in serialized_monitor_state

    empty_snapshot = repo.provider_monitoring_snapshot(
        reliability_window_minutes=30,
        cost_window_hours=24,
        now_utc=datetime(2026, 7, 17, tzinfo=timezone.utc),
    )
    assert empty_snapshot["reliability"]["alerts"]["status"] == "insufficient_data"
    assert empty_snapshot["reliability"]["alerts"]["evaluated_count"] == 0
    assert empty_snapshot["cost_total_minor"] == 0
    assert empty_snapshot["cost_coverage_complete"] is True

    first = repo.reconcile_provider_reliability_alerts(
        alert_summary={"items": [critical_search_alert()]},
        actor_user_id="internal-owner",
    )
    assert first["states"][0]["lifecycle_status"] == "pending"
    assert first["transition_count"] == 0

    opened = repo.reconcile_provider_reliability_alerts(
        alert_summary={"items": [critical_search_alert()]},
        actor_user_id="internal-owner",
    )
    assert opened["states"][0]["lifecycle_status"] == "open"
    assert opened["transition_count"] == 1
    assert opened["events"][0]["transition_key"] == "opened"

    duplicate = repo.reconcile_provider_reliability_alerts(
        alert_summary={"items": [critical_search_alert()]},
        actor_user_id="internal-owner",
    )
    assert duplicate["states"][0]["lifecycle_status"] == "open"
    assert duplicate["transition_count"] == 0
    assert len(repo.provider_reliability_alert_lifecycle()["events"]) == 1

    acknowledged = repo.acknowledge_provider_reliability_alert(
        scope="public_search",
        actor_user_id="internal-owner",
        action_key="investigating",
    )
    assert acknowledged["ok"] is True
    assert acknowledged["duplicate"] is False
    duplicate_acknowledgement = repo.acknowledge_provider_reliability_alert(
        scope="public_search",
        actor_user_id="internal-owner",
        action_key="investigating",
    )
    assert duplicate_acknowledgement["ok"] is True
    assert duplicate_acknowledgement["duplicate"] is True
    lifecycle_after_ack = repo.provider_reliability_alert_lifecycle()
    assert lifecycle_after_ack["states"][0]["acknowledgement_action"] == "investigating"
    assert [event["transition_key"] for event in lifecycle_after_ack["events"]].count("acknowledged") == 1

    recovering = repo.reconcile_provider_reliability_alerts(
        alert_summary={"items": [healthy_search_alert()]},
        actor_user_id="internal-owner",
    )
    assert recovering["states"][0]["lifecycle_status"] == "recovering"
    recovered = repo.reconcile_provider_reliability_alerts(
        alert_summary={"items": [healthy_search_alert()]},
        actor_user_id="internal-owner",
    )
    assert recovered["states"][0]["lifecycle_status"] == "healthy"
    assert recovered["transition_count"] == 1
    assert recovered["events"][0]["transition_key"] == "recovered"

    repo.reconcile_provider_reliability_alerts(
        alert_summary={"items": [critical_search_alert()]},
        actor_user_id="internal-owner",
    )
    reopened = repo.reconcile_provider_reliability_alerts(
        alert_summary={"items": [critical_search_alert()]},
        actor_user_id="internal-owner",
    )
    assert reopened["states"][0]["lifecycle_status"] == "open"
    assert reopened["transition_count"] == 1
    final_events = repo.provider_reliability_alert_lifecycle()["events"]
    assert [event["transition_key"] for event in final_events].count("opened") == 2

    serialized = json.dumps(repo.provider_reliability_alert_lifecycle(), ensure_ascii=False).lower()
    for forbidden in ("api_key", "client_secret", "refresh_token", "private_key", "merchant query", '"fal"'):
        assert forbidden not in serialized

    print("PASS jiejing_reliability_alert_lifecycle")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
