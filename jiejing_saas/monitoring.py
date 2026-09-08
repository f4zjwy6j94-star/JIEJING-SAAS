"""Monitoring and alerting contract for Jiejing SaaS."""

from __future__ import annotations

import math
import hashlib
import os
import re
import time
from datetime import datetime, timezone
from typing import Any

from .config import SaaSSettings
from .operations_metering import (
    PROVIDER_MONITOR_AGGREGATE_KEYS,
    PROVIDER_MONITOR_EVENT_TYPE,
    build_provider_cost_alert_summary,
    build_provider_monitoring_aggregate_event,
)
from .repository import SaaSRepository
from .runtime_evidence import RuntimeEvidenceError, read_runtime_evidence


CLS_PROBE_MAX_AGE_HOURS = 24.0
EVIDENCE_MAX_FUTURE_SKEW_MINUTES = 5.0


class ProviderMonitoringScheduler:
    """Lease-protected evaluator for already-recorded provider telemetry."""

    def __init__(
        self,
        *,
        repository: SaaSRepository | None,
        environment: str,
        exporter: Any = None,
        enabled: bool | None = None,
        interval_seconds: int | None = None,
        reliability_window_minutes: int | None = None,
        cost_window_hours: int | None = None,
        warning_minor: Any = None,
        critical_minor: Any = None,
        owner_nonce: str | None = None,
    ) -> None:
        self.repository = repository
        self.environment = str(environment or "unknown")
        self.exporter = exporter or export_provider_monitoring_aggregate_to_cls
        self.enabled = _env_bool("JIEJING_PROVIDER_MONITOR_SCHEDULER_ENABLED") if enabled is None else bool(enabled)
        self.interval_seconds = _bounded_int_value(
            interval_seconds if interval_seconds is not None else os.environ.get("JIEJING_PROVIDER_MONITOR_INTERVAL_SECONDS"),
            default=300,
            minimum=60,
            maximum=3600,
        )
        self.reliability_window_minutes = _bounded_int_value(
            reliability_window_minutes
            if reliability_window_minutes is not None
            else os.environ.get("JIEJING_PROVIDER_MONITOR_WINDOW_MINUTES"),
            default=30,
            minimum=1,
            maximum=1440,
        )
        self.cost_window_hours = _bounded_int_value(
            cost_window_hours
            if cost_window_hours is not None
            else os.environ.get("JIEJING_PROVIDER_MONITOR_COST_WINDOW_HOURS"),
            default=24,
            minimum=1,
            maximum=168,
        )
        self.warning_minor = (
            warning_minor
            if warning_minor is not None
            else os.environ.get("JIEJING_PROVIDER_DAILY_COST_WARNING_MINOR")
        )
        self.critical_minor = (
            critical_minor
            if critical_minor is not None
            else os.environ.get("JIEJING_PROVIDER_DAILY_COST_CRITICAL_MINOR")
        )
        nonce = str(owner_nonce or f"{os.getpid()}|{time.time_ns()}|{id(self)}")
        self.owner_hash = hashlib.sha256(f"jiejing-provider-monitor|{nonce}".encode("utf-8")).hexdigest()

    def run_once(self, *, now_utc: datetime | None = None, now_epoch: int | None = None) -> dict[str, Any]:
        if not self.enabled:
            return {
                "status": "disabled",
                "external_provider_action_triggered": False,
                "real_platform_writes_enabled": False,
                "secret_exposed": False,
            }
        if self.repository is None:
            return _provider_monitoring_run_result(status="evaluation_failed")
        lease = self.repository.acquire_provider_monitoring_lease(
            scheduler_key="provider-monitor",
            owner_hash=self.owner_hash,
            lease_seconds=self.interval_seconds,
            now_epoch=now_epoch,
        )
        if not lease.get("acquired"):
            return _provider_monitoring_run_result(status="skipped_lease_contended")
        current = now_utc or datetime.now(timezone.utc)
        if current.tzinfo is None or current.utcoffset() is None:
            current = current.replace(tzinfo=timezone.utc)
        evaluated_at = current.astimezone(timezone.utc).isoformat()
        try:
            snapshot = self.repository.provider_monitoring_snapshot(
                reliability_window_minutes=self.reliability_window_minutes,
                cost_window_hours=self.cost_window_hours,
                now_utc=current,
            )
            reliability = snapshot.get("reliability") if isinstance(snapshot.get("reliability"), dict) else {}
            reliability_summary = reliability.get("alerts") if isinstance(reliability.get("alerts"), dict) else {}
            self.repository.reconcile_provider_reliability_alerts(
                alert_summary=reliability_summary,
                actor_user_id="system:provider-monitor-scheduler",
            )
            cost_summary = build_provider_cost_alert_summary(
                cost_total_minor=snapshot.get("cost_total_minor"),
                cost_coverage_complete=bool(snapshot.get("cost_coverage_complete")),
                warning_minor=self.warning_minor,
                critical_minor=self.critical_minor,
            )
            event = build_provider_monitoring_aggregate_event(
                reliability_summary=reliability_summary,
                cost_summary=cost_summary,
                environment=self.environment,
                probe=False,
            )
        except Exception:
            self.repository.complete_provider_monitoring_evaluation(
                scheduler_key="provider-monitor",
                owner_hash=self.owner_hash,
                evaluated_at=None,
                exported_at=None,
                outcome="query_failed",
                snapshot={},
            )
            return _provider_monitoring_run_result(status="query_failed")
        try:
            exported = bool(self.exporter(event))
        except Exception:
            exported = False
        outcome = "exported" if exported else "export_failed"
        self.repository.complete_provider_monitoring_evaluation(
            scheduler_key="provider-monitor",
            owner_hash=self.owner_hash,
            evaluated_at=evaluated_at,
            exported_at=evaluated_at if exported else None,
            outcome=outcome,
            snapshot=event,
        )
        return _provider_monitoring_run_result(
            status=outcome,
            reliability_status=str(reliability_summary.get("status") or "insufficient_data"),
            cost_status=str(cost_summary.get("status") or "blocked"),
            evaluated_scope_count=max(0, int(reliability_summary.get("evaluated_count") or 0)),
        )


def _provider_monitoring_run_result(
    *,
    status: str,
    reliability_status: str | None = None,
    cost_status: str | None = None,
    evaluated_scope_count: int | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "status": str(status or "evaluation_failed"),
        "external_provider_action_triggered": False,
        "real_platform_writes_enabled": False,
        "secret_exposed": False,
    }
    if reliability_status is not None:
        result["reliability_status"] = reliability_status
    if cost_status is not None:
        result["cost_status"] = cost_status
    if evaluated_scope_count is not None:
        result["evaluated_scope_count"] = max(0, int(evaluated_scope_count))
    return result


def export_provider_monitoring_aggregate_to_cls(
    event: dict[str, Any],
    *,
    client_factory: Any = None,
    message_factory: Any = None,
) -> bool:
    """Upload one allowlisted aggregate through Tencent's protobuf-capable SDK."""

    if not _env_bool("JIEJING_CLS_ENABLED") or not isinstance(event, dict):
        return False
    if set(event) != PROVIDER_MONITOR_AGGREGATE_KEYS:
        return False
    if event.get("event_type") != PROVIDER_MONITOR_EVENT_TYPE:
        return False
    region = str(os.environ.get("JIEJING_CLS_REGION") or os.environ.get("JIEJING_TENCENT_REGION") or "").strip()
    topic_id = str(os.environ.get("JIEJING_CLS_TOPIC_ID") or os.environ.get("JIEJING_CLS_TOPIC") or "").strip()
    access_id = _tencent_secret_id()
    access_key = _tencent_secret_key()
    if not re.fullmatch(r"[a-z0-9-]{3,64}", region) or not topic_id or not access_id or not access_key:
        return False
    return upload_provider_monitoring_aggregate_to_cls(
        event,
        region=region,
        topic_id=topic_id,
        access_id=access_id,
        access_key=access_key,
        client_factory=client_factory,
        message_factory=message_factory,
    )


def upload_provider_monitoring_aggregate_to_cls(
    event: dict[str, Any],
    *,
    region: str,
    topic_id: str,
    access_id: str,
    access_key: str,
    client_factory: Any = None,
    message_factory: Any = None,
) -> bool:
    """Upload one allowlisted aggregate through Tencent CloudAPI UploadLog."""

    if set(event) != PROVIDER_MONITOR_AGGREGATE_KEYS or event.get("event_type") != PROVIDER_MONITOR_EVENT_TYPE:
        return False
    if not re.fullmatch(r"[a-z0-9-]{3,64}", str(region or "")) or not all(
        str(value or "").strip() for value in (topic_id, access_id, access_key)
    ):
        return False
    try:
        if client_factory is None:
            client_factory = _tencent_cloudapi_cls_upload_client
        if message_factory is None:
            from .cls_log_pb2 import LogGroupList

            message_factory = LogGroupList
        packet = message_factory()
        group = packet.logGroupList.add()
        log = group.logs.add()
        log.time = int(time.time() * 1_000_000)
        for key in sorted(PROVIDER_MONITOR_AGGREGATE_KEYS):
            value = event[key]
            content = log.contents.add()
            content.key = key
            content.value = str(value).lower() if isinstance(value, bool) else str(value)
        endpoint = "https://cls.tencentcloudapi.com"
        client = client_factory(endpoint, region, access_id, access_key)
        client.timeout = 5
        client.put_log_raw(topic_id, packet)
        return True
    except Exception:
        return False


class _TencentCloudApiClsUploadClient:
    def __init__(self, client: Any, request_factory: Any) -> None:
        self._client = client
        self._request_factory = request_factory
        self.timeout = 5

    def put_log_raw(self, topic_id: str, packet: Any) -> Any:
        request = self._request_factory()
        request.TopicId = str(topic_id)
        return self._client.UploadLog(request, packet.SerializeToString())


def _tencent_cloudapi_cls_upload_client(endpoint: str, region: str, access_id: str, access_key: str) -> Any:
    from tencentcloud.common import credential
    from tencentcloud.common.profile.client_profile import ClientProfile
    from tencentcloud.common.profile.http_profile import HttpProfile
    from tencentcloud.cls.v20201016 import cls_client, models

    hostname = str(endpoint or "").removeprefix("https://").removeprefix("http://").strip("/")
    if hostname != "cls.tencentcloudapi.com":
        raise ValueError("invalid CLS CloudAPI endpoint")
    if not re.fullmatch(r"[a-z0-9-]{3,64}", region):
        raise ValueError("invalid CLS region")
    http_profile = HttpProfile()
    http_profile.endpoint = hostname
    http_profile.reqTimeout = 5
    client_profile = ClientProfile(httpProfile=http_profile)
    client = cls_client.ClsClient(
        credential.Credential(str(access_id), str(access_key)),
        region,
        client_profile,
    )
    return _TencentCloudApiClsUploadClient(client, models.UploadLogRequest)


ALERT_CONTRACTS = [
    {
        "key": "oauth_callback_failure",
        "label": "eBay OAuth callback failure",
        "severity": "critical",
        "source": "audit_logs.oauth.callback",
    },
    {
        "key": "vault_resolution_failure",
        "label": "Vault/KMS secret resolution failure",
        "severity": "critical",
        "source": "vault_secret_resolver",
    },
    {
        "key": "ebay_sync_failure",
        "label": "eBay read-only sync failure",
        "severity": "warning",
        "source": "queue_jobs.ebay_read_only_snapshot",
    },
    {
        "key": "queue_backlog_or_stuck_job",
        "label": "Queue backlog or stuck job",
        "severity": "warning",
        "source": "queue_jobs",
    },
    {
        "key": "database_endpoint_or_dns_unreachable",
        "label": "Managed database endpoint or DNS unreachable",
        "severity": "critical",
        "source": "operational_health.database_live_probe",
    },
    {
        "key": "cloud_billing_or_resource_suspension",
        "label": "Cloud billing arrears or managed resource suspension",
        "severity": "critical",
        "source": "cloud_account.billing_and_resource_status",
    },
    {
        "key": "confirmation_backlog",
        "label": "Merchant confirmation backlog",
        "severity": "warning",
        "source": "confirmations",
    },
    {
        "key": "platform_write_failure",
        "label": "eBay platform write failure",
        "severity": "critical",
        "source": "execution_results.publish_listing",
    },
    {
        "key": "billing_webhook_failure",
        "label": "Billing webhook failure",
        "severity": "critical",
        "source": "billing.webhook",
    },
    {
        "key": "backup_restore_drill_overdue",
        "label": "Backup restore drill overdue",
        "severity": "critical",
        "source": "backup_plan.restore",
    },
    {
        "key": "ai_model_latency_or_error_spike",
        "label": "AI model latency or error spike",
        "severity": "warning",
        "source": "ai_ceo_chat.performance.model",
    },
    {
        "key": "public_search_latency_or_no_result_spike",
        "label": "Public search latency or no-result spike",
        "severity": "warning",
        "source": "ai_ceo_chat.performance.search",
    },
    {
        "key": "media_provider_cost_or_retry_spike",
        "label": "Media provider cost, retry, or duplicate-submission spike",
        "severity": "critical",
        "source": "media_asset_jobs.cost_guard",
    },
]


def build_monitoring_status(
    settings: SaaSSettings,
    repository: SaaSRepository,
    *,
    now_utc: datetime | None = None,
) -> dict[str, Any]:
    counts = repository.system_counts()
    queue_counts = repository.queue_status_counts()
    pending_confirmations = int(queue_counts.get("pending", 0))
    failed_jobs = int(queue_counts.get("failed", 0))
    safe_access_log_enabled = _safe_access_log_enabled(settings)
    evidence_unavailable = False
    try:
        evidence = read_runtime_evidence()
    except RuntimeEvidenceError:
        evidence, evidence_unavailable = {}, True
    cls_target = _cls_monitoring_target_status(now_utc=now_utc, runtime_evidence=evidence)
    runbook = _runbook_status()
    provider_observability = _provider_observability_status(repository, now_utc=now_utc, runtime_evidence=evidence)
    if evidence_unavailable:
        cls_target["target_ready"] = cls_target["control_plane_ready"] = False
        cls_target["blocked_by"].append("runtime_evidence_unavailable")
        provider_observability["ready"] = False
        provider_observability["blocked_by"].append("runtime_evidence_unavailable")
    blockers = _monitoring_blockers(settings, safe_access_log_enabled, cls_target, runbook, provider_observability)
    return {
        "contract_version": "2026-05-18-tencent-cls-monitoring-boundary",
        "environment": settings.environment,
        "production_monitoring_ready": bool(
            settings.is_production_like
            and safe_access_log_enabled
            and cls_target["target_ready"]
            and provider_observability["ready"]
            and not blockers
        ),
        "safe_access_logs": {
            "enabled": safe_access_log_enabled,
            "required_in_production": True,
            "records_request_body": False,
            "records_authorization_header": False,
            "records_raw_tokens": False,
        },
        "cloud_monitoring": cls_target,
        "provider_observability": provider_observability,
        "health_checks": {
            "health_endpoint": "/health",
            "readiness_endpoint": "/readiness/product-saas",
            "monitoring_endpoint": "/monitoring/status",
            "public_health_does_not_expose_secrets": True,
        },
        "signals": {
            "database_tables": counts,
            "queue_status_counts": queue_counts,
            "failed_queue_jobs": failed_jobs,
            "pending_confirmation_items": int(counts.get("confirmations", 0)),
            "report_count": int(counts.get("reports", 0)),
            "platform_data_packet_count": int(counts.get("platform_data_packets", 0)),
            "audit_log_count": int(counts.get("audit_logs", 0)),
        },
        "alert_contracts": ALERT_CONTRACTS,
        "incident_runbooks": runbook,
        "external_monitoring_targets": [
        "Tencent CLS log topic for safe backend access and audit signals",
        "Prometheus/Grafana or cloud metrics for latency and queue depth",
        "Cloud alert for OAuth/Vault/eBay sync failures",
        "Cloud billing balance and managed database endpoint availability alerts",
        "Backup and restore drill alerts for managed database",
        ],
        "current_blockers": blockers,
        "real_platform_writes_enabled": False,
        "secret_exposed": False,
    }


def _monitoring_blockers(
    settings: SaaSSettings,
    safe_access_log_enabled: bool,
    cls_target: dict[str, Any],
    runbook: dict[str, Any],
    provider_observability: dict[str, Any],
) -> list[str]:
    blockers: list[str] = []
    if settings.is_production_like and not safe_access_log_enabled:
        blockers.append("safe_access_log_disabled_in_production")
    if settings.is_production_like:
        for item in cls_target["blocked_by"]:
            if item not in blockers:
                blockers.append(item)
        for item in runbook["blocked_by"]:
            if item not in blockers:
                blockers.append(item)
        for item in provider_observability["blocked_by"]:
            if item not in blockers:
                blockers.append(item)
    if not settings.is_production_like:
        blockers.extend(
            [
                "external_error_capture_not_configured",
                "cloud_metrics_not_configured",
                "backup_restore_alerts_not_configured",
            ]
        )
    return blockers


def _provider_observability_status(
    repository: SaaSRepository,
    *,
    now_utc: datetime | None = None,
    runtime_evidence: dict[str, str] | None = None,
) -> dict[str, Any]:
    evidence = read_runtime_evidence() if runtime_evidence is None else runtime_evidence
    metrics_enabled = _env_bool("JIEJING_PROVIDER_METRICS_ENABLED")
    legacy_latency_flag = _env_bool("JIEJING_PROVIDER_LATENCY_ALERTS_CONFIGURED")
    legacy_cost_flag = _env_bool("JIEJING_PROVIDER_COST_ALERTS_CONFIGURED")
    scheduler_enabled = _env_bool("JIEJING_PROVIDER_MONITOR_SCHEDULER_ENABLED")
    interval_seconds = _bounded_int_value(
        os.environ.get("JIEJING_PROVIDER_MONITOR_INTERVAL_SECONDS"),
        default=300,
        minimum=60,
        maximum=3600,
    )
    reliability_window_minutes = _bounded_int_value(
        os.environ.get("JIEJING_PROVIDER_MONITOR_WINDOW_MINUTES"),
        default=30,
        minimum=1,
        maximum=1440,
    )
    cost_window_hours = _bounded_int_value(
        os.environ.get("JIEJING_PROVIDER_MONITOR_COST_WINDOW_HOURS"),
        default=24,
        minimum=1,
        maximum=168,
    )
    evidence_max_age_minutes = _env_positive_float("JIEJING_PROVIDER_MONITOR_EVIDENCE_MAX_AGE_MINUTES", 15.0)
    alarm_max_age_days = _env_positive_float("JIEJING_PROVIDER_ALARM_VERIFICATION_MAX_AGE_DAYS", 7.0)
    evidence_now = now_utc or datetime.now(timezone.utc)
    state = repository.provider_monitoring_state()
    aggregate = state.get("aggregate") if isinstance(state.get("aggregate"), dict) else {}
    evaluation_evidence = _timestamp_evidence_status(
        str(state.get("last_evaluated_at") or ""),
        evidence_max_age_minutes / 60.0,
        evidence_now,
    )
    export_evidence = _timestamp_evidence_status(
        str(state.get("last_exported_at") or ""),
        evidence_max_age_minutes / 60.0,
        evidence_now,
    )
    latency_alarm_evidence = _timestamp_evidence_status(
        evidence.get("JIEJING_PROVIDER_LATENCY_ALARM_VERIFIED_AT", "").strip(),
        alarm_max_age_days * 24.0,
        evidence_now,
    )
    cost_alarm_evidence = _timestamp_evidence_status(
        evidence.get("JIEJING_PROVIDER_COST_ALARM_VERIFIED_AT", "").strip(),
        alarm_max_age_days * 24.0,
        evidence_now,
    )
    cost_summary = build_provider_cost_alert_summary(
        cost_total_minor=aggregate.get("cost_total_minor"),
        cost_coverage_complete=bool(aggregate.get("cost_coverage_complete")),
        warning_minor=os.environ.get("JIEJING_PROVIDER_DAILY_COST_WARNING_MINOR"),
        critical_minor=os.environ.get("JIEJING_PROVIDER_DAILY_COST_CRITICAL_MINOR"),
    )
    blocked_by: list[str] = []
    if not metrics_enabled:
        blocked_by.append("provider_metrics_not_enabled")
    if not scheduler_enabled:
        blocked_by.append("provider_monitor_scheduler_not_enabled")
    _append_evidence_blocker(
        blocked_by,
        prefix="provider_monitor_evaluation",
        raw_value=str(state.get("last_evaluated_at") or ""),
        evidence=evaluation_evidence,
    )
    _append_evidence_blocker(
        blocked_by,
        prefix="provider_monitor_export",
        raw_value=str(state.get("last_exported_at") or ""),
        evidence=export_evidence,
    )
    if not cost_summary.get("budget_configured"):
        blocked_by.append("provider_cost_budget_not_configured")
    _append_evidence_blocker(
        blocked_by,
        prefix="provider_latency_alarm_verification",
        raw_value=evidence.get("JIEJING_PROVIDER_LATENCY_ALARM_VERIFIED_AT", ""),
        evidence=latency_alarm_evidence,
    )
    _append_evidence_blocker(
        blocked_by,
        prefix="provider_cost_alarm_verification",
        raw_value=evidence.get("JIEJING_PROVIDER_COST_ALARM_VERIFIED_AT", ""),
        evidence=cost_alarm_evidence,
    )
    return {
        "contract_version": "2026-07-17-passive-provider-monitoring-v1",
        "ready": not blocked_by,
        "metrics_enabled": metrics_enabled,
        "scheduler_enabled": scheduler_enabled,
        "interval_seconds": interval_seconds,
        "reliability_window_minutes": reliability_window_minutes,
        "cost_window_hours": cost_window_hours,
        "legacy_latency_flag": legacy_latency_flag,
        "legacy_cost_flag": legacy_cost_flag,
        "legacy_flags_prove_readiness": False,
        "evaluation_evidence": _derived_evidence(evaluation_evidence, max_age_minutes=evidence_max_age_minutes),
        "export_evidence": _derived_evidence(export_evidence, max_age_minutes=evidence_max_age_minutes),
        "alarm_evidence": {
            "latency": _derived_evidence(latency_alarm_evidence, max_age_minutes=alarm_max_age_days * 1440.0),
            "cost": _derived_evidence(cost_alarm_evidence, max_age_minutes=alarm_max_age_days * 1440.0),
            "max_age_days": alarm_max_age_days,
        },
        "reliability_status": str(aggregate.get("reliability_status") or "insufficient_data"),
        "evaluated_scope_count": max(0, _safe_nonnegative_int(aggregate.get("reliability_evaluated_count"))),
        "cost_status": str(cost_summary.get("status") or "blocked"),
        "cost_budget_configured": bool(cost_summary.get("budget_configured")),
        "cost_coverage_complete": bool(cost_summary.get("cost_coverage_complete")),
        "metric_contracts": [
            {
                "key": "ai_model_request",
                "measures": ["latency_ms", "timeout_count", "initial_retry_count", "failure_code"],
                "warning_latency_ms": _env_int("JIEJING_AI_MODEL_LATENCY_WARNING_MS", 15000),
            },
            {
                "key": "public_search_request",
                "measures": ["latency_ms", "result_count", "no_result_count", "failure_code"],
                "warning_latency_ms": _env_int("JIEJING_PUBLIC_SEARCH_LATENCY_WARNING_MS", 4000),
            },
            {
                "key": "media_provider_job",
                "measures": ["queue_age_ms", "provider_duration_ms", "estimated_cost_cents", "actual_cost_cents", "retry_count", "duplicate_submission_count"],
                "warning_latency_ms": _env_int("JIEJING_MEDIA_PROVIDER_LATENCY_WARNING_MS", 120000),
            },
        ],
        "dimensions": ["environment", "scope", "status"],
        "records_raw_prompts": False,
        "records_source_text": False,
        "records_secrets": False,
        "blocked_by": blocked_by,
        "secret_exposed": False,
    }


def _runbook_status() -> dict[str, Any]:
    required = {
        "incident_runbook_published": _env_bool("JIEJING_INCIDENT_RUNBOOK_PUBLISHED"),
        "oncall_alert_route_configured": _env_bool("JIEJING_ONCALL_ALERT_ROUTE_CONFIGURED"),
        "backup_restore_drill_runbook_published": _env_bool("JIEJING_BACKUP_RESTORE_DRILL_RUNBOOK_PUBLISHED"),
        "post_publish_recovery_runbook_published": _env_bool("JIEJING_POST_PUBLISH_RECOVERY_RUNBOOK_PUBLISHED"),
        "billing_incident_runbook_published": _env_bool("JIEJING_BILLING_INCIDENT_RUNBOOK_PUBLISHED"),
        "cloud_billing_incident_runbook_published": _env_bool("JIEJING_CLOUD_BILLING_INCIDENT_RUNBOOK_PUBLISHED"),
        "database_endpoint_incident_runbook_published": _env_bool("JIEJING_DATABASE_ENDPOINT_INCIDENT_RUNBOOK_PUBLISHED"),
    }
    blockers = [key for key, ready in required.items() if not ready]
    return {
        **required,
        "runbook_ready": not blockers,
        "blocked_by": blockers,
        "must_cover": [
            "eBay OAuth or token resolution failure",
            "eBay read-only packet failure",
            "real publish failure or ambiguous 502",
            "billing webhook failure or payment dispute",
            "cloud billing arrears or managed resource suspension",
            "managed database endpoint, DNS, or connectivity failure",
            "backup failure or restore drill overdue",
            "model provider failure or runaway cost",
        ],
        "secret_exposed": False,
    }


def _cls_monitoring_target_status(*, now_utc: datetime | None = None, runtime_evidence: dict[str, str] | None = None) -> dict[str, Any]:
    evidence = read_runtime_evidence() if runtime_evidence is None else runtime_evidence
    enabled = _env_bool("JIEJING_CLS_ENABLED")
    region = os.environ.get("JIEJING_CLS_REGION") or os.environ.get("JIEJING_TENCENT_REGION") or "ap-guangzhou"
    logset_id = os.environ.get("JIEJING_CLS_LOGSET_ID") or os.environ.get("JIEJING_CLS_LOGSET") or ""
    topic_id = os.environ.get("JIEJING_CLS_TOPIC_ID") or os.environ.get("JIEJING_CLS_TOPIC") or ""
    alert_policy_configured = _env_bool("JIEJING_CLS_ALERT_POLICY_CONFIGURED")
    live_probe_at = evidence.get("JIEJING_CLS_LIVE_PROBE_LAST_AT", "").strip()
    live_probe_required = _env_bool("JIEJING_CLS_LIVE_PROBE_REQUIRED")
    ingestion_probe_passed = evidence.get("JIEJING_CLS_INGESTION_LIVE_PROBE_PASSED", "").strip().lower() in {"1", "true", "yes", "on"}
    ingestion_probe_at = evidence.get("JIEJING_CLS_INGESTION_LIVE_PROBE_LAST_AT", "").strip()
    probe_max_age_hours = _env_positive_float("JIEJING_CLS_PROBE_MAX_AGE_HOURS", CLS_PROBE_MAX_AGE_HOURS)
    evidence_now = now_utc or datetime.now(timezone.utc)
    live_evidence = _timestamp_evidence_status(live_probe_at, probe_max_age_hours, evidence_now)
    ingestion_evidence = _timestamp_evidence_status(ingestion_probe_at, probe_max_age_hours, evidence_now)
    credentials_configured = bool(_tencent_secret_id()) and bool(_tencent_secret_key())
    blockers: list[str] = []
    if not enabled:
        blockers.append("tencent_cls_not_enabled")
    if not region:
        blockers.append("JIEJING_CLS_REGION")
    if not logset_id:
        blockers.append("JIEJING_CLS_LOGSET_ID")
    if not topic_id:
        blockers.append("JIEJING_CLS_TOPIC_ID")
    if not alert_policy_configured:
        blockers.append("JIEJING_CLS_ALERT_POLICY_CONFIGURED")
    if live_probe_required:
        if not live_probe_at:
            blockers.append("tencent_cls_live_probe_not_recorded")
        elif not live_evidence["timestamp_valid"]:
            blockers.append("tencent_cls_live_probe_timestamp_invalid")
        elif live_evidence["timestamp_in_future"]:
            blockers.append("tencent_cls_live_probe_timestamp_in_future")
        elif not live_evidence["fresh"]:
            blockers.append("tencent_cls_live_probe_stale")
    if live_probe_required:
        if not (ingestion_probe_passed and ingestion_probe_at):
            blockers.append("tencent_cls_ingestion_live_probe_not_passed")
        elif not ingestion_evidence["timestamp_valid"]:
            blockers.append("tencent_cls_ingestion_live_probe_timestamp_invalid")
        elif ingestion_evidence["timestamp_in_future"]:
            blockers.append("tencent_cls_ingestion_live_probe_timestamp_in_future")
        elif not ingestion_evidence["fresh"]:
            blockers.append("tencent_cls_ingestion_live_probe_stale")
    control_plane_ready = bool(
        enabled
        and region
        and logset_id
        and topic_id
        and alert_policy_configured
        and (live_evidence["fresh"] or not live_probe_required)
    )
    return {
        "provider": "tencent_cls",
        "enabled": enabled,
        "control_plane_ready": control_plane_ready,
        "target_ready": bool(
            control_plane_ready
            and ((ingestion_probe_passed and ingestion_evidence["fresh"]) or not live_probe_required)
        ),
        "region": region,
        "logset_configured": bool(logset_id),
        "topic_configured": bool(topic_id),
        "alert_policy_configured": alert_policy_configured,
        "credentials_configured": credentials_configured,
        "live_probe_required": live_probe_required,
        "last_live_probe_at": live_probe_at,
        "live_probe_timestamp_valid": live_evidence["timestamp_valid"],
        "live_probe_timestamp_in_future": live_evidence["timestamp_in_future"],
        "live_probe_fresh": live_evidence["fresh"],
        "live_probe_age_hours": live_evidence["age_hours"],
        "live_probe_max_age_hours": probe_max_age_hours,
        "ingestion_live_probe_passed": ingestion_probe_passed,
        "last_ingestion_live_probe_at": ingestion_probe_at,
        "ingestion_live_probe_timestamp_valid": ingestion_evidence["timestamp_valid"],
        "ingestion_live_probe_timestamp_in_future": ingestion_evidence["timestamp_in_future"],
        "ingestion_live_probe_fresh": ingestion_evidence["fresh"],
        "ingestion_live_probe_age_hours": ingestion_evidence["age_hours"],
        "records_request_body": False,
        "records_authorization_header": False,
        "records_raw_tokens": False,
        "blocked_by": blockers,
        "secret_exposed": False,
    }


def _safe_access_log_enabled(settings: SaaSSettings) -> bool:
    if settings.is_production_like:
        return True
    return str(os.environ.get("JIEJING_SAFE_ACCESS_LOG") or "").strip().lower() in {"1", "true", "yes", "on"}


def _tencent_secret_id() -> str:
    return os.environ.get("JIEJING_TENCENT_SECRET_ID") or os.environ.get("TENCENTCLOUD_SECRET_ID") or ""


def _tencent_secret_key() -> str:
    return os.environ.get("JIEJING_TENCENT_SECRET_KEY") or os.environ.get("TENCENTCLOUD_SECRET_KEY") or ""


def _env_bool(name: str) -> bool:
    return str(os.environ.get(name) or "").strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    try:
        return max(1, int(str(os.environ.get(name) or default).strip()))
    except (TypeError, ValueError):
        return default


def _bounded_int_value(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        normalized = int(str(value if value not in {None, ""} else default).strip())
    except (TypeError, ValueError):
        normalized = default
    return min(maximum, max(minimum, normalized))


def _env_positive_float(name: str, default: float) -> float:
    raw = str(os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    if not math.isfinite(value) or value <= 0:
        return default
    return value


def _timestamp_evidence_status(value: str, max_age_hours: float, now_utc: datetime) -> dict[str, Any]:
    age_hours: float | None = None
    if value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            parsed = None
        if parsed is not None and parsed.tzinfo is not None:
            current = now_utc.astimezone(timezone.utc)
            age_hours = (current - parsed.astimezone(timezone.utc)).total_seconds() / 3600
    timestamp_valid = bool(value and age_hours is not None)
    timestamp_in_future = bool(
        timestamp_valid and age_hours is not None and age_hours < -(EVIDENCE_MAX_FUTURE_SKEW_MINUTES / 60)
    )
    fresh = bool(
        timestamp_valid
        and age_hours is not None
        and not timestamp_in_future
        and age_hours <= max_age_hours
    )
    return {
        "timestamp_valid": timestamp_valid,
        "timestamp_in_future": timestamp_in_future,
        "fresh": fresh,
        "age_hours": round(age_hours, 3) if age_hours is not None else None,
    }


def _append_evidence_blocker(
    blockers: list[str],
    *,
    prefix: str,
    raw_value: str,
    evidence: dict[str, Any],
) -> None:
    if not str(raw_value or "").strip():
        blockers.append(f"{prefix}_not_recorded")
    elif not evidence.get("timestamp_valid"):
        blockers.append(f"{prefix}_timestamp_invalid")
    elif evidence.get("timestamp_in_future"):
        blockers.append(f"{prefix}_timestamp_in_future")
    elif not evidence.get("fresh"):
        blockers.append(f"{prefix}_stale")


def _derived_evidence(evidence: dict[str, Any], *, max_age_minutes: float) -> dict[str, Any]:
    age_hours = evidence.get("age_hours")
    return {
        "recorded": bool(evidence.get("timestamp_valid")),
        "timestamp_valid": bool(evidence.get("timestamp_valid")),
        "timestamp_in_future": bool(evidence.get("timestamp_in_future")),
        "fresh": bool(evidence.get("fresh")),
        "age_minutes": round(float(age_hours) * 60.0, 3) if age_hours is not None else None,
        "max_age_minutes": float(max_age_minutes),
    }


def _safe_nonnegative_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError, OverflowError):
        return 0
