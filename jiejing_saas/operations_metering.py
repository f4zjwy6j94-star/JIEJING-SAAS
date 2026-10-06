"""Privacy-safe, provider-neutral operations metering contracts."""

from __future__ import annotations

import hashlib
import json
import os
import time
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any


ANALYTICS_EVENT_KEYS = {
    "page_view",
    "pricing_view",
    "signup_started",
    "signup_completed",
    "login_started",
    "performance_sample",
}
ANALYTICS_PAGE_KEYS = {"landing", "pricing", "login", "register", "workbench"}
ANALYTICS_METADATA_KEYS = {"entry_surface", "plan_key"}
PERFORMANCE_SCOPES = {"page_load", "settings_module"}
PERFORMANCE_OUTCOMES = {"success", "error"}
PERFORMANCE_NUMERIC_KEYS = {
    "ttfb_ms",
    "fcp_ms",
    "lcp_ms",
    "cls_milli",
    "dom_ready_ms",
    "load_complete_ms",
    "app_shell_ready_ms",
    "duration_ms",
}
PERFORMANCE_MAX_VALUE = 120_000
PROVIDER_TELEMETRY_SCOPES = {"model", "public_search", "media_generation", "payment"}
PROVIDER_TELEMETRY_OUTCOMES = {"success", "partial", "error", "timeout", "blocked"}
PROVIDER_MONITOR_EVENT_TYPE = "jiejing_provider_monitor_aggregate"
PROVIDER_MONITOR_CONTRACT_VERSION = "2026-07-17-provider-monitor-aggregate-v1"
PROVIDER_ERROR_CLASSES = {
    "timeout",
    "http_error",
    "provider_error",
    "invalid_response",
    "no_output",
    "not_configured",
    "blocked_input",
}
PROVIDER_MONITOR_AGGREGATE_KEYS = {
    "event_type",
    "contract_version",
    "environment",
    "probe",
    "reliability_status",
    "reliability_evaluated_count",
    "reliability_attention_count",
    "reliability_critical_count",
    "cost_status",
    "cost_coverage_complete",
    "cost_budget_configured",
    "cost_total_minor",
}
RELIABILITY_ALERT_THRESHOLDS = {
    "model": {
        "minimum_requests": 5,
        "attention_p75_ms": 15_000,
        "critical_p75_ms": 30_000,
        "attention_failure_percent": 15.0,
        "critical_failure_percent": 30.0,
        "attention_timeout_percent": 10.0,
        "critical_timeout_percent": 20.0,
        "action_key": "review_model_routing_and_timeout",
    },
    "public_search": {
        "minimum_requests": 5,
        "attention_p75_ms": 8_000,
        "critical_p75_ms": 15_000,
        "attention_failure_percent": 20.0,
        "critical_failure_percent": 35.0,
        "attention_timeout_percent": 10.0,
        "critical_timeout_percent": 25.0,
        "action_key": "review_search_health_and_fallback",
    },
    "media_generation": {
        "minimum_requests": 5,
        "attention_p75_ms": 90_000,
        "critical_p75_ms": 115_000,
        "attention_failure_percent": 25.0,
        "critical_failure_percent": 50.0,
        "attention_timeout_percent": 15.0,
        "critical_timeout_percent": 30.0,
        "action_key": "review_media_queue_and_quality_gate",
    },
    "payment": {
        "minimum_requests": 5,
        "attention_p75_ms": 4_000,
        "critical_p75_ms": 8_000,
        "attention_failure_percent": 5.0,
        "critical_failure_percent": 15.0,
        "attention_timeout_percent": 2.0,
        "critical_timeout_percent": 10.0,
        "action_key": "review_payment_provider_health_and_reconciliation",
    },
}


def hash_analytics_identifier(value: str) -> str:
    raw = str(value or "").strip()
    if not raw or len(raw) > 160:
        return ""
    salt = (
        os.environ.get("JIEJING_ANALYTICS_HASH_SALT")
        or os.environ.get("JIEJING_SESSION_SECRET")
        or "jiejing-random-browser-id-hash-v1"
    )
    return hashlib.sha256(f"analytics-v1|{salt}|{raw}".encode("utf-8")).hexdigest()


def sanitize_analytics_event(payload: dict[str, Any]) -> dict[str, Any]:
    event_key = str(payload.get("event_key") or payload.get("event") or "").strip().lower()
    page_key = str(payload.get("page_key") or payload.get("page") or "").strip().lower()
    if event_key not in ANALYTICS_EVENT_KEYS:
        raise ValueError("unsupported analytics event")
    if page_key not in ANALYTICS_PAGE_KEYS:
        raise ValueError("unsupported analytics page")
    metadata_input = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    metadata = {
        key: str(metadata_input.get(key) or "").strip()[:80]
        for key in ANALYTICS_METADATA_KEYS
        if str(metadata_input.get(key) or "").strip()
    }
    if event_key == "performance_sample":
        scope = str(metadata_input.get("performance_scope") or "").strip().lower()
        outcome = str(metadata_input.get("outcome") or "").strip().lower()
        if scope in PERFORMANCE_SCOPES:
            metadata["performance_scope"] = scope
        if outcome in PERFORMANCE_OUTCOMES:
            metadata["outcome"] = outcome
        for key in PERFORMANCE_NUMERIC_KEYS:
            if key not in metadata_input:
                continue
            try:
                value = int(round(float(metadata_input.get(key))))
            except (TypeError, ValueError, OverflowError):
                continue
            if value < 0:
                continue
            metadata[key] = min(value, PERFORMANCE_MAX_VALUE)
    return {
        "event_key": event_key,
        "page_key": page_key,
        "visitor_hash": hash_analytics_identifier(str(payload.get("visitor_id") or "")),
        "session_hash": hash_analytics_identifier(str(payload.get("session_id") or "")),
        "event_id_hash": hash_analytics_identifier(str(payload.get("event_id") or "")),
        "metadata": metadata,
    }


def extract_model_usage(body: dict[str, Any] | None) -> dict[str, int]:
    usage = body.get("usage") if isinstance(body, dict) and isinstance(body.get("usage"), dict) else {}
    input_tokens = _first_nonnegative_int(usage, "input_tokens", "prompt_tokens")
    output_tokens = _first_nonnegative_int(usage, "output_tokens", "completion_tokens")
    total_tokens = _first_nonnegative_int(usage, "total_tokens")
    if total_tokens <= 0:
        total_tokens = input_tokens + output_tokens
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
    }


def model_cost_measurement(*, usage_owner: str, usage: dict[str, Any]) -> dict[str, Any]:
    if usage_owner != "jiejing_platform_trial":
        return {"cost_minor": 0, "currency": "CNY", "cost_status": "merchant_billed_directly"}
    if max(0, _safe_int(usage.get("total_tokens"))) <= 0:
        return {"cost_minor": 0, "currency": "CNY", "cost_status": "unavailable"}
    input_rate = _decimal_env("JIEJING_PLATFORM_MODEL_INPUT_CNY_PER_MILLION_TOKENS")
    output_rate = _decimal_env("JIEJING_PLATFORM_MODEL_OUTPUT_CNY_PER_MILLION_TOKENS")
    if input_rate is None or output_rate is None:
        return {"cost_minor": 0, "currency": "CNY", "cost_status": "unavailable"}
    input_tokens = max(0, _safe_int(usage.get("input_tokens")))
    output_tokens = max(0, _safe_int(usage.get("output_tokens")))
    cost_cny = (Decimal(input_tokens) * input_rate + Decimal(output_tokens) * output_rate) / Decimal(1_000_000)
    return {
        "cost_minor": int((cost_cny * Decimal(100)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)),
        "currency": "CNY",
        "cost_status": "configured_estimate",
    }


def media_cost_measurement(*, provider_output: dict[str, Any], media_points: int) -> dict[str, Any]:
    output_packet = provider_output.get("output_packet") if isinstance(provider_output.get("output_packet"), dict) else {}
    candidates = [
        provider_output.get("usage") if isinstance(provider_output.get("usage"), dict) else {},
        output_packet.get("usage") if isinstance(output_packet.get("usage"), dict) else {},
    ]
    for usage in candidates:
        for key in ("cost_cny_minor", "actual_cost_cny_minor", "billed_cost_cny_minor"):
            value = _safe_int(usage.get(key))
            if value > 0:
                return {"cost_minor": value, "currency": "CNY", "cost_status": "actual"}
    rate = _decimal_env("JIEJING_MEDIA_COST_CNY_PER_POINT")
    if rate is None:
        return {"cost_minor": 0, "currency": "CNY", "cost_status": "unavailable"}
    cost_cny = Decimal(max(0, int(media_points or 0))) * rate
    return {
        "cost_minor": int((cost_cny * Decimal(100)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)),
        "currency": "CNY",
        "cost_status": "configured_estimate",
    }


def public_search_cost_measurement(*, provider_output: dict[str, Any]) -> dict[str, Any]:
    output_packet = provider_output.get("output_packet") if isinstance(provider_output.get("output_packet"), dict) else {}
    candidates = [
        provider_output.get("usage") if isinstance(provider_output.get("usage"), dict) else {},
        output_packet.get("usage") if isinstance(output_packet.get("usage"), dict) else {},
    ]
    for usage in candidates:
        for key in ("cost_cny_minor", "actual_cost_cny_minor", "billed_cost_cny_minor"):
            value = _safe_int(usage.get(key))
            if value > 0:
                return {"cost_minor": value, "currency": "CNY", "cost_status": "actual"}
    rate = _decimal_env("JIEJING_PUBLIC_SEARCH_COST_CNY_PER_REQUEST")
    if rate is None:
        return {"cost_minor": 0, "currency": "CNY", "cost_status": "unavailable"}
    return {
        "cost_minor": int((rate * Decimal(100)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)),
        "currency": "CNY",
        "cost_status": "configured_estimate",
    }


def sanitize_provider_telemetry(
    *,
    scope: str,
    outcome: str,
    duration_ms: Any,
    error_class: Any = "",
) -> dict[str, Any]:
    normalized_scope = str(scope or "").strip().lower()
    if normalized_scope not in PROVIDER_TELEMETRY_SCOPES:
        raise ValueError("unsupported provider telemetry scope")
    normalized_outcome = str(outcome or "").strip().lower()
    if normalized_outcome not in PROVIDER_TELEMETRY_OUTCOMES:
        normalized_outcome = "error"
    try:
        normalized_duration = int(round(float(duration_ms)))
    except (TypeError, ValueError, OverflowError):
        normalized_duration = 0
    packet = {
        "scope": normalized_scope,
        "outcome": normalized_outcome,
        "duration_ms": min(max(0, normalized_duration), PERFORMANCE_MAX_VALUE),
    }
    safe_error_class = _provider_error_class(error_class)
    if safe_error_class and normalized_outcome != "success":
        packet["error_class"] = safe_error_class
    return packet


def provider_telemetry_from_result(
    *,
    scope: str,
    provider_output: dict[str, Any],
    duration_ms: Any,
) -> dict[str, Any]:
    status = str(provider_output.get("status") or "").strip().lower()
    missing = provider_output.get("missing_inputs") if isinstance(provider_output.get("missing_inputs"), list) else []
    signal = " ".join([status, *(str(item or "").lower() for item in missing)])
    if "timeout" in signal or "timed out" in signal:
        outcome, error_class = "timeout", "timeout"
    elif status.startswith("completed_live") or status in {"completed", "ready", "success"}:
        outcome, error_class = "success", ""
    elif "partial" in status:
        outcome, error_class = "partial", "no_output" if "no_asset" in signal or "no_output" in signal else "provider_error"
    elif status.startswith("blocked"):
        outcome = "blocked"
        error_class = "not_configured" if "secret" in signal or "not_configured" in signal else "blocked_input"
    else:
        outcome = "error"
        error_class = _provider_error_class(signal)
    return sanitize_provider_telemetry(
        scope=scope,
        outcome=outcome,
        duration_ms=duration_ms,
        error_class=error_class,
    )


def build_reliability_alert_summary(reliability_analytics: dict[str, Any]) -> dict[str, Any]:
    """Classify provider-neutral telemetry without storing merchant or provider content."""

    items: list[dict[str, Any]] = []
    for scope in ("model", "public_search", "media_generation", "payment"):
        thresholds = RELIABILITY_ALERT_THRESHOLDS[scope]
        source = reliability_analytics.get(scope) if isinstance(reliability_analytics.get(scope), dict) else {}
        request_count = max(0, _safe_int(source.get("request_count")))
        failure_count = min(request_count, max(0, _safe_int(source.get("failure_count"))))
        timeout_count = min(request_count, max(0, _safe_int(source.get("timeout_count"))))
        sample_count = max(0, _safe_int(source.get("sample_count")))
        p75_duration_ms = max(0, _safe_int(source.get("p75_duration_ms"))) or None
        failure_rate = round((failure_count / request_count) * 100, 2) if request_count else 0.0
        timeout_rate = round((timeout_count / request_count) * 100, 2) if request_count else 0.0
        status = "insufficient_data"
        reason_codes: list[str] = []
        action_key = "collect_more_samples"
        if request_count >= int(thresholds["minimum_requests"]):
            critical_reasons = _reliability_threshold_reasons(
                p75_duration_ms=p75_duration_ms,
                failure_rate_percent=failure_rate,
                timeout_rate_percent=timeout_rate,
                thresholds=thresholds,
                severity="critical",
            )
            attention_reasons = _reliability_threshold_reasons(
                p75_duration_ms=p75_duration_ms,
                failure_rate_percent=failure_rate,
                timeout_rate_percent=timeout_rate,
                thresholds=thresholds,
                severity="attention",
            )
            if critical_reasons:
                status = "critical"
                reason_codes = critical_reasons
                action_key = str(thresholds["action_key"])
            elif attention_reasons:
                status = "attention"
                reason_codes = attention_reasons
                action_key = str(thresholds["action_key"])
            else:
                status = "healthy"
                action_key = "none"
        items.append(
            {
                "scope": scope,
                "status": status,
                "request_count": request_count,
                "sample_count": sample_count,
                "p75_duration_ms": p75_duration_ms,
                "failure_count": failure_count,
                "timeout_count": timeout_count,
                "failure_rate_percent": failure_rate,
                "timeout_rate_percent": timeout_rate,
                "reason_codes": reason_codes,
                "action_key": action_key,
            }
        )
    critical_count = sum(1 for item in items if item["status"] == "critical")
    attention_count = sum(1 for item in items if item["status"] == "attention")
    evaluated_count = sum(1 for item in items if item["status"] != "insufficient_data")
    status = (
        "critical"
        if critical_count
        else "attention"
        if attention_count
        else "healthy"
        if evaluated_count
        else "insufficient_data"
    )
    return {
        "contract_version": "2026-07-15-provider-reliability-alerts-v2",
        "status": status,
        "alert_required": bool(critical_count or attention_count),
        "critical_count": critical_count,
        "attention_count": attention_count,
        "evaluated_count": evaluated_count,
        "items": items,
        "provider_neutral": True,
        "prompts_stored": False,
        "responses_stored": False,
        "queries_stored": False,
        "raw_errors_stored": False,
        "raw_provider_response_stored": False,
    }


def build_provider_cost_alert_summary(
    *,
    cost_total_minor: Any,
    cost_coverage_complete: bool,
    warning_minor: Any,
    critical_minor: Any,
) -> dict[str, Any]:
    """Classify aggregate platform cost without inventing an operating budget."""

    warning = _positive_minor_threshold(warning_minor)
    critical = _positive_minor_threshold(critical_minor)
    if warning is None or critical is None or critical < warning:
        return {
            "contract_version": "2026-07-17-provider-cost-alert-v1",
            "status": "blocked",
            "reason_codes": ["provider_cost_budget_not_configured"],
            "budget_configured": False,
            "cost_coverage_complete": bool(cost_coverage_complete),
            "cost_total_minor": max(0, _safe_int(cost_total_minor)),
            "alert_required": False,
        }
    if not bool(cost_coverage_complete):
        return {
            "contract_version": "2026-07-17-provider-cost-alert-v1",
            "status": "attention",
            "reason_codes": ["provider_cost_coverage_incomplete"],
            "budget_configured": True,
            "cost_coverage_complete": False,
            "cost_total_minor": max(0, _safe_int(cost_total_minor)),
            "alert_required": True,
        }
    total = max(0, _safe_int(cost_total_minor))
    if total >= critical:
        status = "critical"
        reason_codes = ["provider_cost_critical_reached"]
    elif total >= warning:
        status = "attention"
        reason_codes = ["provider_cost_warning_reached"]
    else:
        status = "healthy"
        reason_codes = []
    return {
        "contract_version": "2026-07-17-provider-cost-alert-v1",
        "status": status,
        "reason_codes": reason_codes,
        "budget_configured": True,
        "cost_coverage_complete": bool(cost_coverage_complete),
        "cost_total_minor": total,
        "alert_required": bool(reason_codes),
    }


def build_provider_monitoring_aggregate_event(
    *,
    reliability_summary: dict[str, Any],
    cost_summary: dict[str, Any],
    environment: Any,
    probe: bool = False,
) -> dict[str, Any]:
    """Return the flat allowlisted CLS event for passive provider monitoring."""

    reliability = reliability_summary if isinstance(reliability_summary, dict) else {}
    cost = cost_summary if isinstance(cost_summary, dict) else {}
    reliability_status = str(reliability.get("status") or "insufficient_data").strip().lower()
    if reliability_status not in {"insufficient_data", "healthy", "attention", "critical"}:
        reliability_status = "insufficient_data"
    cost_status = str(cost.get("status") or "blocked").strip().lower()
    if cost_status not in {"blocked", "healthy", "attention", "critical"}:
        cost_status = "blocked"
    environment_class = str(environment or "unknown").strip().lower()
    if environment_class not in {"development", "test", "staging", "production"}:
        environment_class = "unknown"
    return {
        "event_type": PROVIDER_MONITOR_EVENT_TYPE,
        "contract_version": PROVIDER_MONITOR_CONTRACT_VERSION,
        "environment": environment_class,
        "probe": bool(probe),
        "reliability_status": reliability_status,
        "reliability_evaluated_count": max(0, _safe_int(reliability.get("evaluated_count"))),
        "reliability_attention_count": max(0, _safe_int(reliability.get("attention_count"))),
        "reliability_critical_count": max(0, _safe_int(reliability.get("critical_count"))),
        "cost_status": cost_status,
        "cost_coverage_complete": bool(cost.get("cost_coverage_complete")),
        "cost_budget_configured": bool(cost.get("budget_configured")),
        "cost_total_minor": max(0, _safe_int(cost.get("cost_total_minor"))),
    }


def reconcile_reliability_alert_state(
    *,
    previous_state: dict[str, Any] | None,
    observed_alert: dict[str, Any],
    evaluated_at: str,
) -> dict[str, Any]:
    """Confirm noisy provider telemetry before opening a durable internal alert."""

    scope = str(observed_alert.get("scope") or "").strip().lower()
    if scope not in PROVIDER_TELEMETRY_SCOPES:
        raise ValueError("unsupported reliability alert scope")
    observed_status = str(observed_alert.get("status") or "insufficient_data").strip().lower()
    if observed_status not in {"insufficient_data", "healthy", "attention", "critical"}:
        observed_status = "insufficient_data"
    previous = previous_state if isinstance(previous_state, dict) else {}
    if str(previous.get("scope") or scope) != scope:
        previous = {}
    prior_lifecycle = str(previous.get("lifecycle_status") or "sampling")
    prior_severity = str(previous.get("severity") or "none")
    prior_breach_count = max(0, _safe_int(previous.get("consecutive_breach_count")))
    prior_healthy_count = max(0, _safe_int(previous.get("consecutive_healthy_count")))
    prior_fingerprint = str(previous.get("fingerprint") or "")
    alert_is_active = prior_lifecycle in {"open", "recovering"}
    reason_codes = sorted(
        {
            str(item).strip()
            for item in (observed_alert.get("reason_codes") if isinstance(observed_alert.get("reason_codes"), list) else [])
            if str(item).strip() in {"high_latency", "high_failure_rate", "high_timeout_rate"}
        }
    )
    observation_fingerprint = hashlib.sha256(
        f"reliability-alert-v1|{scope}|{observed_status}|{'|'.join(reason_codes)}".encode("utf-8")
    ).hexdigest()
    evaluated = str(evaluated_at or "")[:80]
    transition_key = ""
    transition_fingerprint = ""
    if observed_status in {"attention", "critical"}:
        breach_count = prior_breach_count + 1 if prior_lifecycle in {"pending", "open", "recovering"} else 1
        healthy_count = 0
        lifecycle_status = "open" if alert_is_active or breach_count >= 2 else "pending"
        is_escalation = alert_is_active and prior_severity == "attention" and observed_status == "critical"
        severity = "critical" if observed_status == "critical" or prior_severity == "critical" else "attention"
        fingerprint = (
            hashlib.sha256(f"{prior_fingerprint}|critical|{evaluated}".encode("utf-8")).hexdigest()
            if is_escalation
            else prior_fingerprint
            if prior_lifecycle == "pending" or alert_is_active
            else hashlib.sha256(f"{observation_fingerprint}|{evaluated}".encode("utf-8")).hexdigest()
        )
        opened_at = str(previous.get("opened_at") or evaluated) if lifecycle_status == "open" else ""
        recovered_at = ""
        if is_escalation:
            transition_key = "escalated"
            transition_fingerprint = fingerprint
        elif lifecycle_status == "open" and prior_lifecycle not in {"open", "recovering"}:
            transition_key = "opened"
            transition_fingerprint = fingerprint
    elif observed_status == "healthy" and alert_is_active:
        breach_count = 0
        healthy_count = prior_healthy_count + 1 if prior_lifecycle == "recovering" else 1
        if healthy_count >= 2:
            lifecycle_status = "healthy"
            severity = "none"
            fingerprint = ""
            opened_at = ""
            recovered_at = evaluated
            transition_key = "recovered"
            transition_fingerprint = prior_fingerprint
        else:
            lifecycle_status = "recovering"
            severity = prior_severity
            fingerprint = prior_fingerprint
            opened_at = str(previous.get("opened_at") or "")
            recovered_at = ""
            reason_codes = [
                str(item)
                for item in (previous.get("reason_codes") if isinstance(previous.get("reason_codes"), list) else [])
                if str(item) in {"high_latency", "high_failure_rate", "high_timeout_rate"}
            ]
    elif observed_status == "insufficient_data" and prior_lifecycle in {"pending", "open", "recovering"}:
        lifecycle_status = prior_lifecycle
        severity = prior_severity
        breach_count = prior_breach_count
        healthy_count = prior_healthy_count
        fingerprint = prior_fingerprint
        opened_at = str(previous.get("opened_at") or "")
        recovered_at = str(previous.get("recovered_at") or "")
        reason_codes = [
            str(item)
            for item in (previous.get("reason_codes") if isinstance(previous.get("reason_codes"), list) else [])
            if str(item) in {"high_latency", "high_failure_rate", "high_timeout_rate"}
        ]
    else:
        lifecycle_status = "healthy" if observed_status == "healthy" else "sampling"
        severity = "none"
        breach_count = 0
        healthy_count = min(prior_healthy_count + 1, 2) if observed_status == "healthy" else 0
        fingerprint = ""
        opened_at = ""
        recovered_at = str(previous.get("recovered_at") or "")
    state = {
        "scope": scope,
        "lifecycle_status": lifecycle_status,
        "severity": severity,
        "observed_status": observed_status,
        "consecutive_breach_count": breach_count,
        "consecutive_healthy_count": healthy_count,
        "fingerprint": fingerprint,
        "reason_codes": reason_codes,
        "action_key": str(observed_alert.get("action_key") or previous.get("action_key") or "none")[:80],
        "opened_at": opened_at,
        "recovered_at": recovered_at,
        "acknowledged_at": str(previous.get("acknowledged_at") or ""),
        "acknowledged_by": str(previous.get("acknowledged_by") or ""),
        "acknowledgement_action": str(previous.get("acknowledgement_action") or ""),
        "last_evaluated_at": evaluated,
        "updated_at": evaluated,
        "observation": {
            "request_count": max(0, _safe_int(observed_alert.get("request_count"))),
            "sample_count": max(0, _safe_int(observed_alert.get("sample_count"))),
            "p75_duration_ms": max(0, _safe_int(observed_alert.get("p75_duration_ms"))) or None,
            "failure_count": max(0, _safe_int(observed_alert.get("failure_count"))),
            "timeout_count": max(0, _safe_int(observed_alert.get("timeout_count"))),
        },
        "provider_neutral": True,
        "secret_exposed": False,
    }
    transition = None
    if transition_key:
        transition = {
            "transition_key": transition_key,
            "scope": scope,
            "severity": prior_severity if transition_key == "recovered" else state["severity"],
            "fingerprint": transition_fingerprint,
            "action_key": state["action_key"],
            "created_at": state["updated_at"],
            "provider_neutral": True,
            "secret_exposed": False,
        }
    return {"state": state, "transition": transition}


def _reliability_threshold_reasons(
    *,
    p75_duration_ms: int | None,
    failure_rate_percent: float,
    timeout_rate_percent: float,
    thresholds: dict[str, Any],
    severity: str,
) -> list[str]:
    reasons: list[str] = []
    if p75_duration_ms is not None and p75_duration_ms >= int(thresholds[f"{severity}_p75_ms"]):
        reasons.append("high_latency")
    if failure_rate_percent >= float(thresholds[f"{severity}_failure_percent"]):
        reasons.append("high_failure_rate")
    if timeout_rate_percent >= float(thresholds[f"{severity}_timeout_percent"]):
        reasons.append("high_timeout_rate")
    return reasons


def _positive_minor_threshold(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        normalized = int(str(value).strip())
    except (TypeError, ValueError, OverflowError):
        return None
    return normalized if normalized > 0 else None


def safe_metering_json(value: Any, *, limit: int = 2000) -> str:
    encoded = json.dumps(value if isinstance(value, dict) else {}, ensure_ascii=False, sort_keys=True)
    return encoded[:limit]


class MeteredModelClient:
    """Accumulate provider-reported usage across retries without collecting content."""

    def __init__(self, client: Any, *, _shared_calls: list[dict[str, Any]] | None = None, _wrap_fallback: bool = True) -> None:
        self._client = client
        self._calls = _shared_calls if _shared_calls is not None else []
        if _wrap_fallback:
            for name in ("jiejing_fallback_model_client", "jiejing_empty_answer_model_client"):
                fallback_client = getattr(client, name, None)
                if fallback_client is not None:
                    setattr(self, name, MeteredModelClient(
                        fallback_client, _shared_calls=self._calls, _wrap_fallback=False,
                    ))

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)

    def generate_text(self, **kwargs: Any) -> dict[str, Any]:
        return self._run(self._client.generate_text, **kwargs)

    def generate_report(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return self._run(self._client.generate_report, *args, **kwargs)

    def usage_summary(self) -> dict[str, int]:
        return {
            "request_count": len(self._calls),
            "input_tokens": sum(item["input_tokens"] for item in self._calls),
            "output_tokens": sum(item["output_tokens"] for item in self._calls),
            "total_tokens": sum(item["total_tokens"] for item in self._calls),
        }

    def reliability_summary(self) -> dict[str, Any]:
        durations = sorted(max(0, _safe_int(item.get("duration_ms"))) for item in self._calls)
        first_outputs = sorted(
            max(0, _safe_int(item.get("first_output_ms")))
            for item in self._calls
            if item.get("first_output_ms") is not None
        )
        errors: dict[str, int] = {}
        for item in self._calls:
            error_class = str(item.get("error_class") or "")
            if error_class:
                errors[error_class] = errors.get(error_class, 0) + 1
        success_count = sum(1 for item in self._calls if item.get("outcome") == "success")
        timeout_count = sum(1 for item in self._calls if item.get("outcome") == "timeout")
        return {
            "scope": "model",
            "request_count": len(self._calls),
            "success_count": success_count,
            "failure_count": len(self._calls) - success_count,
            "timeout_count": timeout_count,
            "p75_duration_ms": _p75(durations),
            "max_duration_ms": max(durations) if durations else None,
            "duration_samples_ms": durations[-50:],
            "streamed_request_count": len(first_outputs),
            "p75_first_output_ms": _p75(first_outputs),
            "max_first_output_ms": max(first_outputs) if first_outputs else None,
            "first_output_samples_ms": first_outputs[-50:],
            "error_classes": errors,
            "prompts_stored": False,
            "responses_stored": False,
            "raw_errors_stored": False,
        }

    def _run(self, operation: Any, *args: Any, **kwargs: Any) -> dict[str, Any]:
        started_at = time.perf_counter()
        first_output_ms: int | None = None
        original_delta_callback = kwargs.get("on_text_delta")
        if callable(original_delta_callback):
            def _metered_delta_callback(fragment: Any) -> Any:
                nonlocal first_output_ms
                if first_output_ms is None and str(fragment or ""):
                    first_output_ms = int(round((time.perf_counter() - started_at) * 1000))
                return original_delta_callback(fragment)

            kwargs["on_text_delta"] = _metered_delta_callback
        try:
            result = operation(*args, **kwargs)
        except Exception as exc:
            duration_ms = int(round((time.perf_counter() - started_at) * 1000))
            telemetry = sanitize_provider_telemetry(
                scope="model",
                outcome="timeout" if _provider_error_class(exc) == "timeout" else "error",
                duration_ms=duration_ms,
                error_class=exc,
            )
            if first_output_ms is not None:
                telemetry["first_output_ms"] = min(120000, max(0, first_output_ms))
            self._capture(None, telemetry=telemetry)
            raise
        duration_ms = int(round((time.perf_counter() - started_at) * 1000))
        mode = str(result.get("model_mode") or "").lower() if isinstance(result, dict) else ""
        if "not_configured" in mode:
            outcome, error_class = "blocked", "not_configured"
        elif "error" in mode:
            outcome, error_class = "error", "provider_error"
        else:
            outcome, error_class = "success", ""
        telemetry = sanitize_provider_telemetry(
            scope="model",
            outcome=outcome,
            duration_ms=duration_ms,
            error_class=error_class,
        )
        if first_output_ms is not None:
            telemetry["first_output_ms"] = min(120000, max(0, first_output_ms))
        self._capture(result, telemetry=telemetry)
        return result

    def _capture(self, result: Any, *, telemetry: dict[str, Any]) -> None:
        usage = result.get("_usage") if isinstance(result, dict) and isinstance(result.get("_usage"), dict) else {}
        normalized = {
            "input_tokens": max(0, _safe_int(usage.get("input_tokens"))),
            "output_tokens": max(0, _safe_int(usage.get("output_tokens"))),
            "total_tokens": max(0, _safe_int(usage.get("total_tokens"))),
        }
        if normalized["total_tokens"] <= 0:
            normalized["total_tokens"] = normalized["input_tokens"] + normalized["output_tokens"]
        self._calls.append({**normalized, **telemetry})


def _p75(values: list[int]) -> int | None:
    if not values:
        return None
    return values[max(0, ((len(values) * 3 + 3) // 4) - 1)]


def _provider_error_class(value: Any) -> str:
    text = f"{value.__class__.__name__} {value}".lower() if isinstance(value, BaseException) else str(value or "").lower()
    if not text:
        return ""
    if "timeout" in text or "timed out" in text:
        return "timeout"
    if "http" in text or "urlerror" in text or "connection" in text:
        return "http_error"
    if "not_configured" in text or "missing_secret" in text or "missing secret" in text:
        return "not_configured"
    if "no_asset" in text or "no asset" in text or "no_output" in text or "no output" in text:
        return "no_output"
    if "invalid" in text or "decode" in text or "json" in text:
        return "invalid_response"
    if "blocked" in text or "missing_input" in text:
        return "blocked_input"
    return "provider_error"


def _first_nonnegative_int(values: dict[str, Any], *keys: str) -> int:
    for key in keys:
        if key in values:
            return max(0, _safe_int(values.get(key)))
    return 0


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _decimal_env(name: str) -> Decimal | None:
    raw = str(os.environ.get(name) or "").strip()
    if not raw:
        return None
    try:
        value = Decimal(raw)
    except InvalidOperation:
        return None
    return value if value >= 0 else None
