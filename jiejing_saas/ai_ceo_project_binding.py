"""Server-owned product binding and receipts for semantic AI CEO turns."""
from __future__ import annotations

import hashlib
from typing import Any

from .repository import normalize_listing_project_identity, normalize_merchant_product_fact_packet


def submitted_project_identity(context: Any) -> dict[str, str]:
    if not isinstance(context, dict) or context.get("contract_version") != "active_listing_context_v1":
        return {}
    return normalize_listing_project_identity(context.get("listing_project_identity"))


def new_project_identity(*, company_id: str, store_id: str, request_task_id: str) -> dict[str, str]:
    digest = hashlib.sha256(f"semantic-project|{company_id}|{store_id}|{request_task_id}".encode()).hexdigest()[:32]
    return {"key": "listing-project-" + digest,
            "source_report_id": "report_semantic_" + digest, "candidate_id": "candidate_" + digest}


def new_project_fact_packet(product_name: str) -> dict[str, Any]:
    # A model-selected name is useful for display, but does not confirm facts.
    return normalize_merchant_product_fact_packet({
        "product_name": product_name,
        "derived_listing_suggestions": {"product_name": product_name},
    }, source="backend_semantic_project_anchor")


def merge_product_fact_proposals(packet: dict[str, Any], proposals: list[dict[str, str]]) -> dict[str, Any]:
    """Merge planner-validated, message-grounded values as unconfirmed suggestions."""
    normalized = normalize_merchant_product_fact_packet({
        "derived_listing_suggestions": {item["field"]: item["value"] for item in proposals},
        "buyer_copy_requires_validated_listing_generation": True,
    }, source="backend_semantic_product_proposals")
    suggestions = normalized["derived_listing_suggestions"]
    evidence = dict(packet.get("field_evidence") or {})
    conflicts = list(packet.get("fact_conflicts") or [])
    for item in proposals:
        field = item["field"]
        if field not in suggestions:
            continue
        previous = (packet.get("derived_listing_suggestions") or {}).get(field)
        if previous and str(previous) != suggestions[field]:
            conflicts.append({"field": field, "values": [str(previous), suggestions[field]],
                "reason": "本轮文字资料与图片建议不同，均未确认，请核对真实商品资料。"})
        evidence[field] = {"source_type": "merchant_message_model_proposal", "source_quote": item["source_quote"],
                           "image_indexes": [], "confidence": 0.0, "merchant_confirmation_received": False}
    return {**packet,
        "derived_listing_suggestions": {**(packet.get("derived_listing_suggestions") or {}), **suggestions},
        "field_evidence": evidence, "fact_conflicts": conflicts,
        "product_fact_proposals": [dict(item) for item in proposals],
        "buyer_copy_requires_validated_listing_generation": True,
        "real_platform_writes_enabled": False,
    }


def semantic_dispatch_receipt(*, plan: dict[str, Any], status: str, command_id: str,
                              idempotency_key: str, request_task_id: str, company_id: str,
                              store_id: str, submitted_identity: dict[str, str],
                              target_identity: dict[str, str], consumed_asset_ids: list[str]) -> dict[str, Any]:
    ready = status == "ready"
    action = str(plan.get("project_action") or "none")
    target = normalize_listing_project_identity(target_identity) if ready and action in {"new", "current"} else {}
    return {"contract_version": "ai_ceo_semantic_dispatch_v1", "status": status,
            "project_action": action, "command_id": command_id, "idempotency_key": idempotency_key,
            "request_task_id": request_task_id, "company_id": company_id, "store_id": store_id,
            "submitted_project_identity": submitted_identity,
            "target_project_identity": target, "consumed_source_asset_ids": list(consumed_asset_ids) if ready else [],
            "workflow_target": str(plan.get("workflow_target") or "") if ready else ""}
