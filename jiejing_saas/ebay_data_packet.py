"""Sanitized eBay read-only data packet builder for Jiejing SaaS."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .ebay_read_contract import field_contract_for
from .ebay_read_normalizers import normalize_read_resource


SENSITIVE_MARKERS = (
    "secret",
    "token",
    "password",
    "api_key",
    "apikey",
    "refresh",
    "authorization",
    "cookie",
    "buyer",
    "recipient",
    "address",
    "phone",
    "email",
    "name",
    "street",
    "postal",
)


def build_ebay_read_only_data_packet(
    *,
    company_id: str,
    store: dict[str, Any],
    user_id: str,
    probe_plan: dict[str, Any],
    source_mode: str,
    sample_payload: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build a Runtime-safe packet from read-only resource plans.

    The packet may hold sanitized manual/sample data, but never raw eBay
    responses, tokens, cookies, buyer PII, or full customer credentials.
    """

    sample_payload = sample_payload if isinstance(sample_payload, dict) else {}
    sections = []
    for resource in probe_plan.get("resources", []):
        if not isinstance(resource, dict):
            continue
        key = str(resource.get("key") or "")
        raw_section = sample_payload.get(key) if isinstance(sample_payload.get(key), dict) else {}
        normalized_result = normalize_read_resource(key, raw_section)
        normalized_section = normalized_result["normalized"] if isinstance(normalized_result.get("normalized"), dict) else {}
        sanitized_section = sanitize_packet_payload(normalized_section)
        source_type = _section_source_type(probe_plan=probe_plan, source_mode=source_mode, data_present=bool(raw_section))
        sanitized_evaluation = normalize_read_resource(key, sanitized_section if isinstance(sanitized_section, dict) else {}).get("field_evaluation", {})
        sections.append(
            {
                "key": key,
                "label": resource.get("label"),
                "api_family": resource.get("api_family"),
                "source_type": source_type,
                "status": _section_status(source_type=source_type, data_present=bool(raw_section)),
                "confidence": _confidence_for_source(source_type),
                "pii_or_financial_sensitivity": resource.get("pii_or_financial_sensitivity"),
                "downstream_module": resource.get("downstream_module") or [],
                "fallback": resource.get("fallback") or [],
                "data_present": bool(raw_section),
                "field_contract": field_contract_for(key),
                "field_evaluation": sanitized_evaluation,
                "normalizer_version": normalized_result.get("normalizer_version"),
                "data": sanitized_section,
            }
        )

    created_at = datetime.now(timezone.utc).isoformat()
    source_gap_count = sum(1 for section in sections if not section["data_present"])
    present_resource_keys = [section["key"] for section in sections if section["data_present"]]
    missing_resource_keys = [section["key"] for section in sections if not section["data_present"]]
    route_health = _route_health(probe_plan.get("route_results") if isinstance(probe_plan.get("route_results"), list) else [])
    return {
        "packet_version": "2026-05-15-ebay-readonly-data-packet",
        "platform": "ebay",
        "packet_type": "ebay_read_only_snapshot",
        "packet_schema": {
            "name": "jiejing.ebay_read_only_snapshot",
            "version": "2026-05-18",
            "compatible_runtime_contract": "jiejing_runtime.standard_data_packet.v1",
        },
        "company_id": company_id,
        "store_id": store.get("store_id"),
        "store_name": store.get("store_name"),
        "marketplace": store.get("marketplace") or "EBAY_US",
        "created_by": user_id,
        "created_at": created_at,
        "source_mode": source_mode or "manual_or_sample",
        "source_label": "official_api" if probe_plan.get("live_read_performed") else "manual_or_sample_or_source_gap",
        "status": "packet_cached_with_source_gaps" if source_gap_count else "packet_cached_sanitized",
        "freshness": {
            "status": "fresh_at_creation",
            "snapshot_created_at": created_at,
            "stale_after_seconds": 6 * 60 * 60,
            "official_request_count": int(probe_plan.get("request_count") or 0),
            "route_success_count": route_health["successful_route_count"],
            "route_failure_count": route_health["failed_route_count"],
        },
        "route_health": route_health,
        "retry_policy": {
            "retryable": bool(route_health["failed_resource_keys"] or missing_resource_keys),
            "retry_scope": route_health["failed_resource_keys"] or missing_resource_keys,
            "safe_to_retry": True,
            "real_platform_writes_enabled": False,
        },
        "ready_for_runtime": True,
        "safe_for_reports": True,
        "safe_for_real_platform_write": False,
        "resource_count": len(sections),
        "source_gap_count": source_gap_count,
        "field_gap_count": sum(
            len(section.get("field_evaluation", {}).get("missing_required_fields", []) or [])
            for section in sections
            if section["data_present"]
        ),
        "present_resource_keys": present_resource_keys,
        "missing_resource_keys": missing_resource_keys,
        "section_summary": [
            {
                "key": section["key"],
                "source_type": section["source_type"],
                "status": section["status"],
                "data_present": section["data_present"],
                "confidence": section["confidence"],
                "contract_ready": section.get("field_evaluation", {}).get("contract_ready"),
                "missing_required_fields": section.get("field_evaluation", {}).get("missing_required_fields", []),
            }
            for section in sections
        ],
        "sections": sections,
        "readiness_for_modules": _module_readiness(sections),
        "probe_status": probe_plan.get("status"),
        "probe_blockers": probe_plan.get("blocked_by") or [],
        "lineage": {
            "probe_live_read_performed": bool(probe_plan.get("live_read_performed")),
            "access_token_used": bool(probe_plan.get("access_token_used")),
            "access_token_returned_to_frontend": bool(probe_plan.get("access_token_returned_to_frontend")),
            "raw_ebay_response_stored": False,
            "raw_secret_stored": False,
            "pii_redacted": True,
        },
        "runtime_use": [
            "market_data_packet",
            "listing_package_context",
            "customer_service_product_context",
            "finance_review_context",
            "confirmation_center_context",
        ],
        "notes": [
            "Every section carries a source label; blocked official reads stay visible as source gaps.",
            "PII-like fields and secret-like fields are redacted before persistence.",
            "This packet can guide reports and drafts, but cannot authorize platform writes.",
        ],
        "secret_exposed": False,
    }


def sanitize_packet_payload(value: Any) -> Any:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            lower = str(key).lower()
            if any(marker in lower for marker in SENSITIVE_MARKERS):
                out[key] = "[REDACTED]"
            else:
                out[key] = sanitize_packet_payload(item)
        return out
    if isinstance(value, list):
        return [sanitize_packet_payload(item) for item in value]
    return value


def _section_source_type(*, probe_plan: dict[str, Any], source_mode: str, data_present: bool) -> str:
    if not data_present:
        return "source_gap"
    if probe_plan.get("live_read_performed"):
        return "official_api"
    return str(source_mode or "manual_sample")


def _section_status(*, source_type: str, data_present: bool) -> str:
    if not data_present:
        return "source_gap_recorded"
    if source_type == "official_api":
        return "official_api_sanitized"
    if data_present:
        return "sanitized_sample_cached"
    return "source_gap_recorded"


def _confidence_for_source(source_type: str) -> str:
    if source_type == "official_api":
        return "high"
    if source_type in {"manual_export", "seller_export", "manual_sample", "sample_payload"}:
        return "medium"
    if source_type == "source_gap":
        return "none"
    return "low"


def _route_health(route_results: list[dict[str, Any]]) -> dict[str, Any]:
    rows = []
    for item in route_results:
        if not isinstance(item, dict):
            continue
        resource_key = str(item.get("resource_key") or "")
        path_count = int(item.get("path_count") or len(item.get("paths") or []))
        successful_path_count = int(item.get("successful_path_count") or 0)
        failed_paths = []
        for path in item.get("paths") or []:
            if not isinstance(path, dict):
                continue
            status = str(path.get("status") or "")
            if status != "ok":
                failed_paths.append(
                    {
                        "path": path.get("path") or path.get("path_template"),
                        "status": status or "unknown",
                        "http_status": path.get("http_status"),
                        "error_type": path.get("error_type"),
                    }
                )
        rows.append(
            {
                "resource_key": resource_key,
                "path_count": path_count,
                "successful_path_count": successful_path_count,
                "data_present": bool(item.get("data_present")),
                "status": "ok" if bool(item.get("data_present")) and not failed_paths else "partial" if bool(item.get("data_present")) else "failed",
                "failed_paths": failed_paths,
            }
        )
    failed = [row for row in rows if row["status"] != "ok"]
    return {
        "route_count": len(rows),
        "successful_route_count": len([row for row in rows if row["status"] == "ok"]),
        "partial_route_count": len([row for row in rows if row["status"] == "partial"]),
        "failed_route_count": len([row for row in rows if row["status"] == "failed"]),
        "failed_resource_keys": [row["resource_key"] for row in failed if row["resource_key"]],
        "routes": rows,
    }


def _module_readiness(sections: list[dict[str, Any]]) -> dict[str, Any]:
    present = {section["key"] for section in sections if section["data_present"]}
    required_by_module = {
        "ai_ceo_home": {"store_profile"},
        "market_report": {"inventory_and_offers", "taxonomy_listing_metadata"},
        "product_listing": {"account_business_policies", "taxonomy_listing_metadata", "inventory_and_offers"},
        "customer_service": {"orders_and_fulfillment", "inventory_and_offers"},
        "finance_review": {"finances", "orders_and_fulfillment"},
        "confirmation_center": {"account_business_policies", "orders_and_fulfillment"},
    }
    readiness: dict[str, Any] = {}
    for module, required in required_by_module.items():
        missing = sorted(required - present)
        readiness[module] = {
            "ready": not missing,
            "required": sorted(required),
            "missing": missing,
            "source": "sanitized_data_packet",
        }
    return readiness
