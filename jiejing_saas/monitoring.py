"""Monitoring and alerting contract for Jiejing SaaS."""

from __future__ import annotations

import os
from typing import Any

from .config import SaaSSettings
from .repository import SaaSRepository


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


def build_monitoring_status(settings: SaaSSettings, repository: SaaSRepository) -> dict[str, Any]:
    counts = repository.system_counts()
    queue_counts = repository.queue_status_counts()
    pending_confirmations = int(queue_counts.get("pending", 0))
    failed_jobs = int(queue_counts.get("failed", 0))
    safe_access_log_enabled = _safe_access_log_enabled(settings)
    cls_target = _cls_monitoring_target_status()
    runbook = _runbook_status()
    provider_observability = _provider_observability_status()
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


def _provider_observability_status() -> dict[str, Any]:
    metrics_enabled = _env_bool("JIEJING_PROVIDER_METRICS_ENABLED")
    latency_alerts_configured = _env_bool("JIEJING_PROVIDER_LATENCY_ALERTS_CONFIGURED")
    cost_alerts_configured = _env_bool("JIEJING_PROVIDER_COST_ALERTS_CONFIGURED")
    blocked_by: list[str] = []
    if not metrics_enabled:
        blocked_by.append("provider_metrics_not_enabled")
    if not latency_alerts_configured:
        blocked_by.append("provider_latency_alerts_not_configured")
    if not cost_alerts_configured:
        blocked_by.append("provider_cost_alerts_not_configured")
    return {
        "contract_version": "2026-07-12-provider-latency-cost-alerts-v1",
        "ready": not blocked_by,
        "metrics_enabled": metrics_enabled,
        "latency_alerts_configured": latency_alerts_configured,
        "cost_alerts_configured": cost_alerts_configured,
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
        "dimensions": ["environment", "provider", "model_or_driver", "route_group", "status"],
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


def _cls_monitoring_target_status() -> dict[str, Any]:
    enabled = _env_bool("JIEJING_CLS_ENABLED")
    region = os.environ.get("JIEJING_CLS_REGION") or os.environ.get("JIEJING_TENCENT_REGION") or "ap-guangzhou"
    logset_id = os.environ.get("JIEJING_CLS_LOGSET_ID") or os.environ.get("JIEJING_CLS_LOGSET") or ""
    topic_id = os.environ.get("JIEJING_CLS_TOPIC_ID") or os.environ.get("JIEJING_CLS_TOPIC") or ""
    alert_policy_configured = _env_bool("JIEJING_CLS_ALERT_POLICY_CONFIGURED")
    live_probe_at = os.environ.get("JIEJING_CLS_LIVE_PROBE_LAST_AT", "").strip()
    live_probe_required = _env_bool("JIEJING_CLS_LIVE_PROBE_REQUIRED")
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
    if live_probe_required and not live_probe_at:
        blockers.append("tencent_cls_live_probe_not_recorded")
    return {
        "provider": "tencent_cls",
        "enabled": enabled,
        "target_ready": bool(enabled and region and logset_id and topic_id and alert_policy_configured and (live_probe_at or not live_probe_required)),
        "region": region,
        "logset_configured": bool(logset_id),
        "topic_configured": bool(topic_id),
        "alert_policy_configured": alert_policy_configured,
        "credentials_configured": credentials_configured,
        "live_probe_required": live_probe_required,
        "last_live_probe_at": live_probe_at,
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
