"""Real model value gate for Jiejing-owned Agents."""

from __future__ import annotations

import json
from typing import Any

from jiejing_runtime.model_clients import model_client_status_from_env

from .config import SaaSSettings
from .model_provider_catalog import MODEL_SECRET_PURPOSE, READY_MODEL_SECRET_STATUSES, provider_key_from_secret_ref
from .platform_model_status import build_platform_default_model_status
from .repository import SaaSRepository


CORE_MODEL_REPORT_TYPES = {
    "market.report",
    "market.data_packet",
    "listing.package",
    "product.listing",
}


def build_model_value_gate(settings: SaaSSettings, repository: SaaSRepository) -> dict[str, Any]:
    model_status = model_client_status_from_env()
    platform_model_status = build_platform_default_model_status()
    evidence = _model_report_evidence(repository)
    byok_evidence = _merchant_byok_model_evidence(repository)
    live_report_types = set(evidence.get("live_model_report_types", []))
    source_linked_report_types = set(evidence.get("source_packet_linked_live_report_types", []))
    required_types = {"market.report", "listing.package"}
    blockers: list[str] = []
    if (
        not model_status.get("configured")
        and not platform_model_status.get("configured")
        and not byok_evidence.get("configured")
    ):
        blockers.append("model_provider_not_configured")
    if model_status.get("live_disabled") or platform_model_status.get("live_disabled"):
        blockers.append("model_live_calls_disabled")
    if model_status.get("legacy_hermes_model_fallback_enabled") and settings.is_production_like:
        blockers.append("legacy_hermes_model_fallback_must_stay_disabled")
    if "hermes" in str(model_status.get("credential_source") or "").lower() and settings.is_production_like:
        blockers.append("production_model_credential_must_not_depend_on_hermes")
    if not required_types.issubset(live_report_types):
        blockers.append("market_and_listing_live_model_value_not_proven")
    if not required_types.issubset(source_linked_report_types):
        blockers.append("market_and_listing_source_packet_chain_not_proven")

    return {
        "contract_version": "2026-05-18-model-value-gate",
        "environment": settings.environment,
        "model_client": {
            "client": model_status.get("client"),
            "model": model_status.get("model"),
            "configured": bool(model_status.get("configured")),
            "endpoint_host": model_status.get("endpoint_host"),
            "credential_present": bool(model_status.get("credential_present")),
            "credential_source": model_status.get("credential_source"),
            "legacy_hermes_model_fallback_enabled": bool(model_status.get("legacy_hermes_model_fallback_enabled")),
            "live_disabled": bool(model_status.get("live_disabled")),
            "secret_exposed": False,
        },
        "platform_default_model": platform_model_status,
        "merchant_byok_model": byok_evidence,
        "required_commercial_proof": [
            {
                "key": "market.report",
                "description": "Market Report over sanitized official eBay packet",
            },
            {
                "key": "listing.package",
                "description": "Listing Package over sanitized official eBay packet",
            },
            {
                "key": "source.labels",
                "description": "Merchant-visible source labels and confidence",
            },
            {
                "key": "confirmation.items",
                "description": "Confirmation-center risk items generated from the reports",
            },
        ],
        "evidence": evidence,
        "ready_for_paid_value_claim": settings.is_production_like and not blockers,
        "blockers": blockers,
        "next_actions": _next_actions(blockers),
        "runtime_gets_raw_ebay_token": False,
        "frontend_gets_model_api_key": False,
        "real_platform_writes_enabled": False,
        "secret_exposed": False,
    }


def _model_report_evidence(repository: SaaSRepository) -> dict[str, Any]:
    repository.initialize()
    report_rows: list[Any] = []
    execution_rows: list[Any] = []
    with repository._connect() as conn:  # Internal readiness contract; no row values are returned raw.
        report_rows = conn.execute(
            """
            select report_type, report_json, created_at from reports
            order by created_at desc
            limit 100
            """
        ).fetchall()
        packet_rows = conn.execute(
            """
            select packet_id, source_mode, status, packet_json
            from platform_data_packets
            order by created_at desc
            limit 100
            """
        ).fetchall()
        execution_rows = conn.execute(
            """
            select result_json, created_at from execution_results
            order by created_at desc
            limit 100
            """
        ).fetchall()

    report_types: set[str] = set()
    live_model_report_types: set[str] = set()
    source_packet_linked_live_report_types: set[str] = set()
    fallback_report_types: set[str] = set()
    sanitized_packet_ids = {
        str(row["packet_id"] or "")
        for row in packet_rows
        if _is_sanitized_official_packet(row)
    }
    for row in report_rows:
        report_type = str(row["report_type"] or "")
        if report_type:
            report_types.add(report_type)
        payload = _json_object(row["report_json"])
        model_mode = _find_model_mode(payload)
        if _payload_has_live_model(payload) or _is_live_model_mode(model_mode):
            live_model_report_types.add(report_type)
            source_packet_id = _find_source_packet_id(payload)
            if source_packet_id and source_packet_id in sanitized_packet_ids:
                source_packet_linked_live_report_types.add(report_type)
        elif model_mode:
            fallback_report_types.add(report_type)

    live_execution_count = 0
    fallback_execution_count = 0
    for row in execution_rows:
        payload = _json_object(row["result_json"])
        if _payload_has_live_model(payload):
            live_execution_count += 1
        elif _find_model_mode(payload):
            fallback_execution_count += 1

    return {
        "report_count_sampled": len(report_rows),
        "execution_count_sampled": len(execution_rows),
        "core_report_types_present": sorted(report_types & CORE_MODEL_REPORT_TYPES),
        "sanitized_official_packet_count_sampled": len(sanitized_packet_ids),
        "live_model_report_types": sorted(item for item in live_model_report_types if item),
        "source_packet_linked_live_report_types": sorted(item for item in source_packet_linked_live_report_types if item),
        "fallback_model_report_types": sorted(item for item in fallback_report_types if item),
        "live_model_execution_count": live_execution_count,
        "fallback_model_execution_count": fallback_execution_count,
        "market_report_live_model_proven": "market.report" in live_model_report_types,
        "listing_package_live_model_proven": "listing.package" in live_model_report_types,
        "market_report_source_packet_chain_proven": "market.report" in source_packet_linked_live_report_types,
        "listing_package_source_packet_chain_proven": "listing.package" in source_packet_linked_live_report_types,
        "secret_exposed": False,
    }


def _merchant_byok_model_evidence(repository: SaaSRepository) -> dict[str, Any]:
    repository.initialize()
    with repository._connect() as conn:  # Internal readiness contract; no secret values are returned.
        rows = conn.execute(
            """
            select secret_ref, company_id, store_id, provider, purpose, status, created_by, created_at, metadata_json
            from secret_refs
            where purpose = ?
            order by created_at desc
            limit 50
            """,
            (MODEL_SECRET_PURPOSE,),
        ).fetchall()
    refs = [repository._secret_ref_row_to_dict(row) for row in rows]
    ready_refs = [item for item in refs if str(item.get("status") or "") in READY_MODEL_SECRET_STATUSES]
    providers = sorted({provider_key_from_secret_ref(item) for item in ready_refs if provider_key_from_secret_ref(item)})
    return {
        "mode": "merchant_byok",
        "configured": bool(ready_refs),
        "ready_secret_ref_count": len(ready_refs),
        "total_secret_ref_count": len(refs),
        "providers": providers,
        "merchant_pays_provider_directly": True,
        "credential_scope": "account_default_with_store_context",
        "jiejing_account_scoped_model_secret_ref": True,
        "jiejing_stores_only_secret_ref": False,
        "frontend_gets_model_api_key": False,
        "runtime_gets_model_api_key": False,
        "reports_get_model_api_key": False,
        "secret_exposed": False,
    }


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _find_model_mode(payload: Any) -> str:
    if isinstance(payload, dict):
        for key in ("model_mode", "model_client_boundary"):
            value = payload.get(key)
            if isinstance(value, str) and value:
                return value
        for value in payload.values():
            found = _find_model_mode(value)
            if found:
                return found
    if isinstance(payload, list):
        for item in payload:
            found = _find_model_mode(item)
            if found:
                return found
    return ""


def _payload_has_live_model(payload: Any) -> bool:
    if isinstance(payload, dict):
        if payload.get("uses_live_model") is True:
            return True
        if _is_live_model_mode(str(payload.get("model_mode") or "")):
            return True
        return any(_payload_has_live_model(value) for value in payload.values())
    if isinstance(payload, list):
        return any(_payload_has_live_model(item) for item in payload)
    return False


def _find_source_packet_id(payload: Any) -> str:
    if isinstance(payload, dict):
        for key in ("source_packet_id", "packet_id"):
            value = str(payload.get(key) or "").strip()
            if value.startswith("packet_"):
                return value
        rehearsal = payload.get("model_value_rehearsal")
        if isinstance(rehearsal, dict):
            value = str(rehearsal.get("source_packet_id") or "").strip()
            if value.startswith("packet_"):
                return value
        for value in payload.values():
            found = _find_source_packet_id(value)
            if found:
                return found
    if isinstance(payload, list):
        for item in payload:
            found = _find_source_packet_id(item)
            if found:
                return found
    return ""


def _is_sanitized_official_packet(row: Any) -> bool:
    payload = _json_object(row["packet_json"])
    source_mode = str(row["source_mode"] or payload.get("source_mode") or "").lower()
    status = str(row["status"] or payload.get("status") or "").lower()
    missing = payload.get("missing_resource_keys")
    present = payload.get("present_resource_keys")
    return bool(
        "official_api" in source_mode
        and ("sanitized" in status or payload.get("secret_exposed") is False)
        and isinstance(present, list)
        and len(present) >= 1
        and (not isinstance(missing, list) or len(missing) == 0)
    )


def _is_live_model_mode(value: str) -> bool:
    text = value.lower()
    return "live_http_model" in text or "live_responses_model" in text or ("deepseek" in text and "fallback" not in text)


def _next_actions(blockers: list[str]) -> list[str]:
    if not blockers:
        return ["sample_review_model_backed_market_and_listing_reports_with_seed_merchants"]
    actions = []
    if "model_provider_not_configured" in blockers:
        actions.append("configure_backend_model_provider_secret_ref_or_environment")
    if "model_live_calls_disabled" in blockers:
        actions.append("enable_controlled_live_model_smoke_with_cost_limit")
    if "production_model_credential_must_not_depend_on_hermes" in blockers:
        actions.append("move_model_api_key_into_jiejing_vault_kms_boundary")
    if "legacy_hermes_model_fallback_must_stay_disabled" in blockers:
        actions.append("set_JIEJING_ALLOW_HERMES_MODEL_FALLBACK_false_in_staging_and_production")
    if "market_and_listing_live_model_value_not_proven" in blockers:
        actions.append("run_market_report_and_listing_package_with_live_model_over_sanitized_packet")
    if "market_and_listing_source_packet_chain_not_proven" in blockers:
        actions.append("rerun_model_value_rehearsal_from_sanitized_official_ebay_packet")
    return actions
