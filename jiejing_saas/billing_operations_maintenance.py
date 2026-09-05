"""Bounded domestic billing maintenance for the private worker runtime."""

from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from typing import Any, Callable

from .billing_domestic import (
    build_domestic_billing_operations_snapshot,
    query_and_reconcile_domestic_billing_order,
    query_and_reconcile_domestic_billing_refund,
)
from .repository import SaaSRepository


PaymentQuery = Callable[[SaaSRepository, str, str], dict[str, Any]]
RefundQuery = Callable[[SaaSRepository, str, str], dict[str, Any]]
RECOVERABLE_PAYMENT_INCIDENTS = {"checkout_expired", "paid_entitlement_recovery_required"}
RECOVERABLE_REFUND_INCIDENTS = {"refund_provider_processing"}


def run_domestic_billing_maintenance(
    repository: SaaSRepository,
    *,
    now: datetime | None = None,
    auto_reconcile: bool = False,
    max_companies: int = 25,
    max_orders_per_company: int = 10,
    max_queries_per_run: int = 50,
    query_payment: PaymentQuery | None = None,
    query_refund: RefundQuery | None = None,
) -> dict[str, Any]:
    """Scan recent billing tenants and optionally perform query-only recovery."""

    current = _normalized_utc(now or datetime.now(timezone.utc))
    safe_company_limit = max(1, min(int(max_companies), 100))
    safe_order_limit = max(1, min(int(max_orders_per_company), 10))
    safe_query_limit = max(1, min(int(max_queries_per_run), 100))
    payment_query = query_payment or _default_payment_query
    refund_query = query_refund or _default_refund_query
    company_ids = repository.list_domestic_billing_company_ids(limit=safe_company_limit)
    company_results: list[dict[str, Any]] = []
    action_required_count = 0
    critical_count = 0
    query_attempt_count = 0
    provider_query_count = 0
    failed_query_count = 0
    recoverable_incident_count = 0

    for company_id in company_ids:
        snapshot = build_domestic_billing_operations_snapshot(
            repository,
            company_id=company_id,
            now=current,
            limit=100,
        )
        incidents = snapshot.get("incidents") if isinstance(snapshot.get("incidents"), list) else []
        action_required_count += int(snapshot.get("action_required_count") or 0)
        critical_count += int(snapshot.get("critical_count") or 0)
        query_results: list[dict[str, Any]] = []
        if auto_reconcile:
            recoverable = [
                incident
                for incident in incidents
                if str(incident.get("code") or "") in RECOVERABLE_PAYMENT_INCIDENTS | RECOVERABLE_REFUND_INCIDENTS
            ][:safe_order_limit]
            recoverable_incident_count += len(recoverable)
            for incident in recoverable:
                if query_attempt_count >= safe_query_limit:
                    break
                order_id = str(incident.get("order_id") or "").strip()
                if not order_id:
                    continue
                query_attempt_count += 1
                code = str(incident.get("code") or "")
                try:
                    if code in RECOVERABLE_REFUND_INCIDENTS:
                        result = refund_query(repository, company_id, order_id)
                    else:
                        result = payment_query(repository, company_id, order_id)
                except Exception:
                    result = {
                        "ok": False,
                        "status": "query_failed",
                        "reason": "billing_provider_query_failed",
                        "calls_external_payment_api": False,
                    }
                if result.get("calls_external_payment_api") is True:
                    provider_query_count += 1
                if result.get("ok") is not True:
                    failed_query_count += 1
                query_results.append(_safe_query_result(order_id=order_id, incident_code=code, result=result))
        company_results.append(
            {
                "company_ref": _opaque_ref(company_id),
                "status": snapshot.get("status"),
                "order_count": int(snapshot.get("order_count") or 0),
                "action_required_count": int(snapshot.get("action_required_count") or 0),
                "critical_count": int(snapshot.get("critical_count") or 0),
                "incident_counts": dict(snapshot.get("incident_counts") or {}),
                "query_results": query_results,
            }
        )

    return {
        "event": "domestic_billing_maintenance",
        "status": "attention_required" if action_required_count or failed_query_count else "healthy" if company_ids else "idle",
        "generated_at": current.replace(microsecond=0).isoformat(),
        "company_count": len(company_ids),
        "max_companies": safe_company_limit,
        "max_orders_per_company": safe_order_limit,
        "max_queries_per_run": safe_query_limit,
        "recoverable_incident_count": recoverable_incident_count,
        "query_budget_exhausted": bool(auto_reconcile and recoverable_incident_count > query_attempt_count),
        "action_required_count": action_required_count,
        "critical_count": critical_count,
        "query_attempt_count": query_attempt_count,
        "provider_query_count": provider_query_count,
        "failed_query_count": failed_query_count,
        "alert_required": bool(critical_count or failed_query_count),
        "auto_reconcile_enabled": bool(auto_reconcile),
        "companies": company_results,
        "calls_external_payment_api": provider_query_count > 0,
        "query_only": True,
        "triggers_real_charge": False,
        "triggers_real_refund": False,
        "real_platform_writes_enabled": False,
        "frontend_gets_payment_secret": False,
        "secret_exposed": False,
    }


def _default_payment_query(repository: SaaSRepository, company_id: str, order_id: str) -> dict[str, Any]:
    return query_and_reconcile_domestic_billing_order(repository, company_id=company_id, order_id=order_id)


def _default_refund_query(repository: SaaSRepository, company_id: str, order_id: str) -> dict[str, Any]:
    allowlist = tuple(value.strip().lower() for value in os.environ.get("JIEJING_INTERNAL_ADMIN_EMAILS", "").split(",") if value.strip())
    return query_and_reconcile_domestic_billing_refund(repository, company_id=company_id, order_id=order_id, internal_admin_emails=allowlist)


def _safe_query_result(*, order_id: str, incident_code: str, result: dict[str, Any]) -> dict[str, Any]:
    return {
        "order_ref": _opaque_ref(order_id),
        "incident_code": incident_code,
        "ok": result.get("ok") is True,
        "status": str(result.get("status") or "unknown")[:64],
        "reason": str(result.get("reason") or "")[:96],
        "calls_external_payment_api": result.get("calls_external_payment_api") is True,
        "triggers_real_charge": False,
        "triggers_real_refund": False,
        "secret_exposed": False,
    }


def _opaque_ref(value: str) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()[:12]


def _normalized_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
