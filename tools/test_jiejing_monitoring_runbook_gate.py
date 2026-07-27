#!/usr/bin/env python3
"""Regression for monitoring, alerting, and incident runbook launch gates."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.config import SaaSSettings  # noqa: E402
from jiejing_saas.monitoring import build_monitoring_status  # noqa: E402
from jiejing_saas.readiness import build_product_readiness  # noqa: E402
from jiejing_saas.repository import SaaSRepository  # noqa: E402


OUT = ROOT / "output" / "jiejing-monitoring-runbook-gate-test"
ENV_KEYS = (
    "JIEJING_SAAS_ENV",
    "JIEJING_SAAS_SESSION_SECRET",
    "JIEJING_CLS_ENABLED",
    "JIEJING_CLS_REGION",
    "JIEJING_CLS_LOGSET_ID",
    "JIEJING_CLS_TOPIC_ID",
    "JIEJING_CLS_ALERT_POLICY_CONFIGURED",
    "JIEJING_CLS_LIVE_PROBE_REQUIRED",
    "JIEJING_CLS_LIVE_PROBE_LAST_AT",
    "JIEJING_CLS_INGESTION_LIVE_PROBE_PASSED",
    "JIEJING_CLS_INGESTION_LIVE_PROBE_LAST_AT",
    "JIEJING_CLS_PROBE_MAX_AGE_HOURS",
    "JIEJING_INCIDENT_RUNBOOK_PUBLISHED",
    "JIEJING_ONCALL_ALERT_ROUTE_CONFIGURED",
    "JIEJING_BACKUP_RESTORE_DRILL_RUNBOOK_PUBLISHED",
    "JIEJING_POST_PUBLISH_RECOVERY_RUNBOOK_PUBLISHED",
    "JIEJING_BILLING_INCIDENT_RUNBOOK_PUBLISHED",
    "JIEJING_CLOUD_BILLING_INCIDENT_RUNBOOK_PUBLISHED",
    "JIEJING_DATABASE_ENDPOINT_INCIDENT_RUNBOOK_PUBLISHED",
    "JIEJING_PROVIDER_METRICS_ENABLED",
    "JIEJING_PROVIDER_LATENCY_ALERTS_CONFIGURED",
    "JIEJING_PROVIDER_COST_ALERTS_CONFIGURED",
    "JIEJING_PROVIDER_MONITOR_SCHEDULER_ENABLED",
    "JIEJING_PROVIDER_MONITOR_INTERVAL_SECONDS",
    "JIEJING_PROVIDER_MONITOR_WINDOW_MINUTES",
    "JIEJING_PROVIDER_MONITOR_COST_WINDOW_HOURS",
    "JIEJING_PROVIDER_MONITOR_EVIDENCE_MAX_AGE_MINUTES",
    "JIEJING_PROVIDER_DAILY_COST_WARNING_MINOR",
    "JIEJING_PROVIDER_DAILY_COST_CRITICAL_MINOR",
    "JIEJING_PROVIDER_LATENCY_ALARM_VERIFIED_AT",
    "JIEJING_PROVIDER_COST_ALARM_VERIFIED_AT",
    "JIEJING_PROVIDER_ALARM_VERIFICATION_MAX_AGE_DAYS",
)


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    previous = {key: os.environ.get(key) for key in ENV_KEYS}
    db_path = OUT / "monitoring-runbook.sqlite"
    db_path.unlink(missing_ok=True)
    try:
        _clear_env()
        now = datetime.now(timezone.utc).replace(microsecond=0)
        os.environ.update(
            {
                "JIEJING_SAAS_ENV": "staging",
                "JIEJING_SAAS_SESSION_SECRET": "staging-monitoring-runbook-secret-long-enough",
                "JIEJING_CLS_ENABLED": "true",
                "JIEJING_CLS_REGION": "ap-guangzhou",
                "JIEJING_CLS_LOGSET_ID": "logset-jiejing",
                "JIEJING_CLS_TOPIC_ID": "topic-saas-backend",
                "JIEJING_CLS_ALERT_POLICY_CONFIGURED": "true",
                "JIEJING_CLS_LIVE_PROBE_REQUIRED": "true",
                "JIEJING_CLS_LIVE_PROBE_LAST_AT": (now - timedelta(minutes=2)).isoformat(),
            }
        )
        settings = _settings(db_path)
        repo = SaaSRepository(settings.db_path, database_engine="sqlite")
        repo.initialize()
        blocked = build_monitoring_status(settings, repo)
        runbook_blockers = blocked.get("incident_runbooks", {}).get("blocked_by", [])
        if "incident_runbook_published" not in runbook_blockers or "oncall_alert_route_configured" not in runbook_blockers:
            return fail(f"production-like monitoring must block without published runbooks and alert route: {runbook_blockers}")
        if blocked.get("production_monitoring_ready") is not False:
            return fail("monitoring must not be production-ready before runbook evidence exists")
        cls_blockers = blocked.get("cloud_monitoring", {}).get("blocked_by", [])
        if "tencent_cls_ingestion_live_probe_not_passed" not in cls_blockers:
            return fail(f"CLS must block when control-plane access exists without ingestion evidence: {cls_blockers}")
        provider_blockers = blocked.get("provider_observability", {}).get("blocked_by", [])
        for required in (
            "provider_metrics_not_enabled",
            "provider_monitor_scheduler_not_enabled",
            "provider_monitor_evaluation_not_recorded",
            "provider_monitor_export_not_recorded",
            "provider_cost_budget_not_configured",
            "provider_latency_alarm_verification_not_recorded",
            "provider_cost_alarm_verification_not_recorded",
        ):
            if required not in provider_blockers:
                return fail(f"production monitoring must block without provider telemetry: {provider_blockers}")

        os.environ.update(
            {
                "JIEJING_INCIDENT_RUNBOOK_PUBLISHED": "true",
                "JIEJING_ONCALL_ALERT_ROUTE_CONFIGURED": "true",
                "JIEJING_BACKUP_RESTORE_DRILL_RUNBOOK_PUBLISHED": "true",
                "JIEJING_POST_PUBLISH_RECOVERY_RUNBOOK_PUBLISHED": "true",
                "JIEJING_BILLING_INCIDENT_RUNBOOK_PUBLISHED": "true",
                "JIEJING_CLOUD_BILLING_INCIDENT_RUNBOOK_PUBLISHED": "true",
                "JIEJING_DATABASE_ENDPOINT_INCIDENT_RUNBOOK_PUBLISHED": "true",
                "JIEJING_PROVIDER_METRICS_ENABLED": "true",
                "JIEJING_PROVIDER_LATENCY_ALERTS_CONFIGURED": "true",
                "JIEJING_PROVIDER_COST_ALERTS_CONFIGURED": "true",
                "JIEJING_CLS_INGESTION_LIVE_PROBE_PASSED": "true",
                "JIEJING_CLS_INGESTION_LIVE_PROBE_LAST_AT": (now - timedelta(minutes=1)).isoformat(),
            }
        )
        manual_flags_only = build_monitoring_status(settings, repo, now_utc=now)
        manual_provider_blockers = manual_flags_only.get("provider_observability", {}).get("blocked_by", [])
        if manual_flags_only.get("production_monitoring_ready") is not False:
            return fail("legacy provider booleans alone must not prove production monitoring readiness")
        if "provider_monitor_scheduler_not_enabled" not in manual_provider_blockers:
            return fail(f"manual provider booleans did not expose the missing scheduler: {manual_provider_blockers}")
        manual_readiness_items = {
            item.get("key"): item
            for item in build_product_readiness(settings, repo).get("items", [])
            if isinstance(item, dict)
        }
        manual_monitoring_item = manual_readiness_items.get("monitoring_alerting", {})
        if manual_monitoring_item.get("status") != "blocked_provider_monitoring_evidence":
            return fail(f"public readiness must not treat legacy provider booleans as proof: {manual_monitoring_item}")
        if manual_monitoring_item.get("severity") != "warning":
            return fail(f"incomplete paid-launch monitoring evidence must warn beta without regressing beta eligibility: {manual_monitoring_item}")
        manual_monitoring_dump = json.dumps(manual_monitoring_item, ensure_ascii=False)
        if any(
            internal_code in manual_monitoring_dump
            for internal_code in (
                "provider_monitor_evaluation_not_recorded",
                "provider_monitor_export_not_recorded",
                "provider_cost_budget_not_configured",
            )
        ):
            return fail(f"public readiness must keep provider diagnostics generic: {manual_monitoring_item}")
        os.environ.update(
            {
                "JIEJING_PROVIDER_MONITOR_SCHEDULER_ENABLED": "true",
                "JIEJING_PROVIDER_MONITOR_INTERVAL_SECONDS": "300",
                "JIEJING_PROVIDER_MONITOR_WINDOW_MINUTES": "30",
                "JIEJING_PROVIDER_MONITOR_COST_WINDOW_HOURS": "24",
                "JIEJING_PROVIDER_MONITOR_EVIDENCE_MAX_AGE_MINUTES": "15",
                "JIEJING_PROVIDER_DAILY_COST_WARNING_MINOR": "10000",
                "JIEJING_PROVIDER_DAILY_COST_CRITICAL_MINOR": "20000",
                "JIEJING_PROVIDER_LATENCY_ALARM_VERIFIED_AT": (now - timedelta(minutes=1)).isoformat(),
                "JIEJING_PROVIDER_COST_ALARM_VERIFIED_AT": (now - timedelta(minutes=1)).isoformat(),
                "JIEJING_PROVIDER_ALARM_VERIFICATION_MAX_AGE_DAYS": "7",
            }
        )
        repo.acquire_provider_monitoring_lease(
            scheduler_key="provider-monitor",
            owner_hash="monitoring-gate-fixture",
            lease_seconds=300,
            now_epoch=int(now.timestamp()) - 60,
        )
        repo.complete_provider_monitoring_evaluation(
            scheduler_key="provider-monitor",
            owner_hash="monitoring-gate-fixture",
            evaluated_at=(now - timedelta(minutes=1)).isoformat(),
            exported_at=(now - timedelta(minutes=1)).isoformat(),
            outcome="exported",
            snapshot={
                "event_type": "jiejing_provider_monitor_aggregate",
                "contract_version": "2026-07-17-provider-monitor-aggregate-v1",
                "environment": "staging",
                "probe": False,
                "reliability_status": "insufficient_data",
                "reliability_evaluated_count": 0,
                "reliability_attention_count": 0,
                "reliability_critical_count": 0,
                "cost_status": "healthy",
                "cost_coverage_complete": True,
                "cost_budget_configured": True,
                "cost_total_minor": 0,
            },
        )
        ready = build_monitoring_status(settings, repo, now_utc=now)
        if ready.get("production_monitoring_ready") is not True:
            return fail(f"monitoring should be ready with CLS and runbook evidence: {ready.get('current_blockers')}")
        ready_readiness_items = {
            item.get("key"): item
            for item in build_product_readiness(settings, repo).get("items", [])
            if isinstance(item, dict)
        }
        if ready_readiness_items.get("monitoring_alerting", {}).get("status") != "cloud_monitoring_ready":
            return fail(f"public readiness should recognize fresh provider monitoring evidence: {ready_readiness_items.get('monitoring_alerting')}")
        alert_keys = {item.get("key") for item in ready.get("alert_contracts", []) if isinstance(item, dict)}
        for key in {
            "billing_webhook_failure",
            "platform_write_failure",
            "backup_restore_drill_overdue",
            "cloud_billing_or_resource_suspension",
            "database_endpoint_or_dns_unreachable",
            "ai_model_latency_or_error_spike",
            "public_search_latency_or_no_result_spike",
            "media_provider_cost_or_retry_spike",
        }:
            if key not in alert_keys:
                return fail(f"missing paid-launch alert contract: {key}")
        provider_observability = ready.get("provider_observability", {})
        if provider_observability.get("ready") is not True:
            return fail(f"provider observability must be production-ready with evidence: {provider_observability}")
        if provider_observability.get("reliability_status") != "insufficient_data":
            return fail(f"zero eligible provider samples must remain insufficient_data: {provider_observability}")
        if provider_observability.get("evaluated_scope_count") != 0:
            return fail(f"zero eligible provider samples must expose zero evaluated scopes: {provider_observability}")
        if provider_observability.get("records_raw_prompts") is not False or provider_observability.get("records_secrets") is not False:
            return fail(f"provider monitoring must not record prompts or secrets: {provider_observability}")
        provider_dump = json.dumps(provider_observability, ensure_ascii=False)
        for forbidden_value in (
            os.environ["JIEJING_PROVIDER_LATENCY_ALARM_VERIFIED_AT"],
            os.environ["JIEJING_PROVIDER_COST_ALARM_VERIFIED_AT"],
            repo.provider_monitoring_state()["last_evaluated_at"],
            repo.provider_monitoring_state()["last_exported_at"],
        ):
            if forbidden_value and forbidden_value in provider_dump:
                return fail("provider status must expose derived freshness without raw evidence timestamps")

        aggregate = repo.provider_monitoring_state()["aggregate"]
        repo.complete_provider_monitoring_evaluation(
            scheduler_key="provider-monitor",
            owner_hash="monitoring-gate-fixture",
            evaluated_at=(now - timedelta(minutes=16)).isoformat(),
            exported_at=(now - timedelta(minutes=1)).isoformat(),
            outcome="exported",
            snapshot=aggregate,
        )
        stale_evaluation = build_monitoring_status(settings, repo, now_utc=now)
        if "provider_monitor_evaluation_stale" not in stale_evaluation.get("provider_observability", {}).get("blocked_by", []):
            return fail(f"stale scheduler evaluation must block readiness: {stale_evaluation.get('provider_observability')}")
        repo.complete_provider_monitoring_evaluation(
            scheduler_key="provider-monitor",
            owner_hash="monitoring-gate-fixture",
            evaluated_at=(now - timedelta(minutes=15)).isoformat(),
            exported_at=(now - timedelta(minutes=15)).isoformat(),
            outcome="exported",
            snapshot=aggregate,
        )
        exact_provider_threshold = build_monitoring_status(settings, repo, now_utc=now).get("provider_observability", {})
        if exact_provider_threshold.get("ready") is not True:
            return fail(f"provider evidence exactly at 15 minutes must remain fresh: {exact_provider_threshold}")
        repo.complete_provider_monitoring_evaluation(
            scheduler_key="provider-monitor",
            owner_hash="monitoring-gate-fixture",
            evaluated_at=(now + timedelta(minutes=6)).isoformat(),
            exported_at=(now - timedelta(minutes=1)).isoformat(),
            outcome="exported",
            snapshot=aggregate,
        )
        future_evaluation = build_monitoring_status(settings, repo, now_utc=now).get("provider_observability", {})
        if "provider_monitor_evaluation_timestamp_in_future" not in (future_evaluation.get("blocked_by") or []):
            return fail(f"future scheduler evidence must block readiness: {future_evaluation}")
        repo.complete_provider_monitoring_evaluation(
            scheduler_key="provider-monitor",
            owner_hash="monitoring-gate-fixture",
            evaluated_at=(now - timedelta(minutes=1)).isoformat(),
            exported_at=(now - timedelta(minutes=1)).isoformat(),
            outcome="exported",
            snapshot=aggregate,
        )
        os.environ["JIEJING_PROVIDER_LATENCY_ALARM_VERIFIED_AT"] = (now - timedelta(days=8)).isoformat()
        stale_alarm = build_monitoring_status(settings, repo, now_utc=now).get("provider_observability", {})
        if "provider_latency_alarm_verification_stale" not in (stale_alarm.get("blocked_by") or []):
            return fail(f"stale cloud alarm readback must block readiness: {stale_alarm}")
        os.environ["JIEJING_PROVIDER_LATENCY_ALARM_VERIFIED_AT"] = (now - timedelta(days=7)).isoformat()
        exact_alarm_threshold = build_monitoring_status(settings, repo, now_utc=now).get("provider_observability", {})
        if exact_alarm_threshold.get("ready") is not True:
            return fail(f"cloud alarm evidence exactly at seven days must remain fresh: {exact_alarm_threshold}")
        os.environ["JIEJING_PROVIDER_DAILY_COST_WARNING_MINOR"] = "0"
        invalid_budget = build_monitoring_status(settings, repo, now_utc=now).get("provider_observability", {})
        if "provider_cost_budget_not_configured" not in (invalid_budget.get("blocked_by") or []):
            return fail(f"invalid explicit cost budget must block readiness: {invalid_budget}")
        os.environ["JIEJING_PROVIDER_DAILY_COST_WARNING_MINOR"] = "10000"
        os.environ["JIEJING_PROVIDER_LATENCY_ALARM_VERIFIED_AT"] = (now - timedelta(minutes=1)).isoformat()
        os.environ["JIEJING_CLS_LIVE_PROBE_LAST_AT"] = (now - timedelta(hours=25)).isoformat()
        stale_control_plane = build_monitoring_status(settings, repo)
        stale_cls_blockers = stale_control_plane.get("cloud_monitoring", {}).get("blocked_by", [])
        if "tencent_cls_live_probe_stale" not in stale_cls_blockers:
            return fail(f"stale CLS control-plane evidence must block monitoring readiness: {stale_cls_blockers}")
        if stale_control_plane.get("production_monitoring_ready") is not False:
            return fail("stale CLS control-plane evidence must keep production monitoring blocked")
        os.environ["JIEJING_CLS_LIVE_PROBE_LAST_AT"] = (now - timedelta(minutes=2)).isoformat()
        os.environ["JIEJING_CLS_INGESTION_LIVE_PROBE_LAST_AT"] = (now - timedelta(hours=25)).isoformat()
        stale_ingestion = build_monitoring_status(settings, repo)
        stale_ingestion_blockers = stale_ingestion.get("cloud_monitoring", {}).get("blocked_by", [])
        if "tencent_cls_ingestion_live_probe_stale" not in stale_ingestion_blockers:
            return fail(f"stale CLS ingestion evidence must block monitoring readiness: {stale_ingestion_blockers}")
        os.environ["JIEJING_CLS_LIVE_PROBE_LAST_AT"] = "not-an-iso-timestamp"
        os.environ["JIEJING_CLS_INGESTION_LIVE_PROBE_LAST_AT"] = (now - timedelta(minutes=1)).isoformat()
        invalid_control_plane = build_monitoring_status(settings, repo)
        invalid_control_blockers = invalid_control_plane.get("cloud_monitoring", {}).get("blocked_by", [])
        if "tencent_cls_live_probe_timestamp_invalid" not in invalid_control_blockers:
            return fail(f"invalid CLS control-plane timestamp must block monitoring readiness: {invalid_control_blockers}")
        os.environ["JIEJING_CLS_LIVE_PROBE_LAST_AT"] = (now - timedelta(minutes=2)).isoformat()
        os.environ["JIEJING_CLS_INGESTION_LIVE_PROBE_LAST_AT"] = "not-an-iso-timestamp"
        invalid_ingestion = build_monitoring_status(settings, repo)
        invalid_ingestion_blockers = invalid_ingestion.get("cloud_monitoring", {}).get("blocked_by", [])
        if "tencent_cls_ingestion_live_probe_timestamp_invalid" not in invalid_ingestion_blockers:
            return fail(f"invalid CLS ingestion timestamp must block monitoring readiness: {invalid_ingestion_blockers}")
        os.environ["JIEJING_CLS_LIVE_PROBE_LAST_AT"] = (now + timedelta(minutes=6)).isoformat()
        os.environ["JIEJING_CLS_INGESTION_LIVE_PROBE_LAST_AT"] = (now - timedelta(minutes=1)).isoformat()
        future_control_plane = build_monitoring_status(settings, repo, now_utc=now)
        future_control_blockers = future_control_plane.get("cloud_monitoring", {}).get("blocked_by", [])
        if "tencent_cls_live_probe_timestamp_in_future" not in future_control_blockers:
            return fail(f"future CLS control-plane timestamp must block monitoring readiness: {future_control_blockers}")
        os.environ["JIEJING_CLS_LIVE_PROBE_LAST_AT"] = (now - timedelta(minutes=2)).isoformat()
        os.environ["JIEJING_CLS_INGESTION_LIVE_PROBE_LAST_AT"] = (now + timedelta(minutes=6)).isoformat()
        future_ingestion = build_monitoring_status(settings, repo, now_utc=now)
        future_ingestion_blockers = future_ingestion.get("cloud_monitoring", {}).get("blocked_by", [])
        if "tencent_cls_ingestion_live_probe_timestamp_in_future" not in future_ingestion_blockers:
            return fail(f"future CLS ingestion timestamp must block monitoring readiness: {future_ingestion_blockers}")
        os.environ["JIEJING_CLS_LIVE_PROBE_LAST_AT"] = (now - timedelta(hours=24)).isoformat()
        os.environ["JIEJING_CLS_INGESTION_LIVE_PROBE_LAST_AT"] = (now - timedelta(hours=24)).isoformat()
        exact_threshold = build_monitoring_status(settings, repo, now_utc=now)
        exact_cls = exact_threshold.get("cloud_monitoring", {})
        if exact_cls.get("target_ready") is not True or exact_cls.get("live_probe_fresh") is not True:
            return fail(f"CLS evidence exactly at the 24-hour threshold must remain fresh: {exact_cls}")
        if exact_cls.get("live_probe_age_hours") != 24.0 or exact_cls.get("live_probe_max_age_hours") != 24.0:
            return fail(f"CLS status must expose exact evidence age and default threshold: {exact_cls}")
        os.environ["JIEJING_CLS_PROBE_MAX_AGE_HOURS"] = "2"
        os.environ["JIEJING_CLS_LIVE_PROBE_LAST_AT"] = (now - timedelta(hours=3)).isoformat()
        os.environ["JIEJING_CLS_INGESTION_LIVE_PROBE_LAST_AT"] = (now - timedelta(minutes=1)).isoformat()
        custom_threshold = build_monitoring_status(settings, repo, now_utc=now)
        custom_cls = custom_threshold.get("cloud_monitoring", {})
        if "tencent_cls_live_probe_stale" not in (custom_cls.get("blocked_by") or []):
            return fail(f"custom two-hour threshold must reject three-hour-old CLS evidence: {custom_cls}")
        if custom_cls.get("live_probe_max_age_hours") != 2.0:
            return fail(f"CLS status must expose the custom evidence threshold: {custom_cls}")
        os.environ["JIEJING_CLS_LIVE_PROBE_LAST_AT"] = (now - timedelta(hours=23)).isoformat()
        os.environ["JIEJING_CLS_INGESTION_LIVE_PROBE_LAST_AT"] = (now - timedelta(hours=23)).isoformat()
        for invalid_threshold in ("0", "-1", "nan", "inf", "garbage"):
            os.environ["JIEJING_CLS_PROBE_MAX_AGE_HOURS"] = invalid_threshold
            fallback_threshold = build_monitoring_status(settings, repo, now_utc=now)
            fallback_cls = fallback_threshold.get("cloud_monitoring", {})
            if fallback_cls.get("live_probe_max_age_hours") != 24.0 or fallback_cls.get("target_ready") is not True:
                return fail(
                    f"invalid CLS threshold {invalid_threshold!r} must safely fall back to 24 hours: {fallback_cls}"
                )
        os.environ.pop("JIEJING_CLS_PROBE_MAX_AGE_HOURS", None)
        os.environ["JIEJING_CLS_LIVE_PROBE_LAST_AT"] = (now + timedelta(minutes=5)).isoformat()
        os.environ["JIEJING_CLS_INGESTION_LIVE_PROBE_LAST_AT"] = (now + timedelta(minutes=5)).isoformat()
        allowed_clock_skew = build_monitoring_status(settings, repo, now_utc=now)
        allowed_clock_skew_cls = allowed_clock_skew.get("cloud_monitoring", {})
        if allowed_clock_skew_cls.get("target_ready") is not True:
            return fail(f"CLS evidence exactly five minutes ahead must remain within clock skew: {allowed_clock_skew_cls}")
        os.environ["JIEJING_CLS_LIVE_PROBE_LAST_AT"] = now.replace(tzinfo=None).isoformat()
        os.environ["JIEJING_CLS_INGESTION_LIVE_PROBE_LAST_AT"] = (now - timedelta(minutes=1)).isoformat()
        naive_timestamp = build_monitoring_status(settings, repo, now_utc=now)
        naive_cls = naive_timestamp.get("cloud_monitoring", {})
        if "tencent_cls_live_probe_timestamp_invalid" not in (naive_cls.get("blocked_by") or []):
            return fail(f"timezone-naive CLS evidence must be rejected: {naive_cls}")
        runbook_dump = json.dumps(ready.get("incident_runbooks", {}), ensure_ascii=False)
        for required in ("cloud billing arrears", "managed database endpoint"):
            if required not in runbook_dump:
                return fail(f"runbook coverage should mention {required}: {runbook_dump}")
        dumped = json.dumps(ready, ensure_ascii=False)
        for forbidden in ("access_token", "refresh_token", "client_secret", "password"):
            if forbidden in dumped:
                return fail(f"monitoring status leaked forbidden marker: {forbidden}")
        print("PASS jiejing_monitoring_runbook_gate")
        return 0
    finally:
        _restore_env(previous)


def _settings(db_path: Path) -> SaaSSettings:
    return SaaSSettings.from_env(
        db_path=db_path,
        runtime_db_path=OUT / "runtime.sqlite",
        output_root=OUT,
        host="127.0.0.1",
        port=8788,
    )


def _clear_env() -> None:
    for key in ENV_KEYS:
        os.environ.pop(key, None)


def _restore_env(previous: dict[str, str | None]) -> None:
    for key, value in previous.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


if __name__ == "__main__":
    raise SystemExit(main())
