"""Runtime handoff helpers for sanitized platform data packets."""

from __future__ import annotations

from typing import Any


def build_runtime_handoff_from_platform_packet(packet_record: dict[str, Any] | None) -> dict[str, Any]:
    """Build Runtime-safe inputs from a stored platform_data_packet record."""

    if not isinstance(packet_record, dict):
        return {}
    packet = packet_record.get("packet") if isinstance(packet_record.get("packet"), dict) else {}
    if str(packet.get("platform") or packet_record.get("platform") or "").lower() != "ebay":
        return {}

    ebay_probe = _ebay_probe_from_packet(packet_record=packet_record, packet=packet)
    handoff: dict[str, Any] = {
        "platform_data_packet_handoff": {
            "packet_id": packet_record.get("packet_id"),
            "platform": "ebay",
            "packet_type": packet.get("packet_type") or packet_record.get("packet_type"),
            "source_label": packet.get("source_label"),
            "source_mode": packet.get("source_mode") or packet_record.get("source_mode"),
            "status": packet.get("status") or packet_record.get("status"),
            "present_resource_keys": list(packet.get("present_resource_keys") or []),
            "missing_resource_keys": list(packet.get("missing_resource_keys") or []),
            "source_gap_count": packet.get("source_gap_count"),
            "ready_for_runtime": bool(packet.get("ready_for_runtime")),
            "runtime_gets_sanitized_packet_only": True,
            "access_token_returned_to_runtime": False,
            "raw_ebay_response_stored": False,
            "real_platform_writes_enabled": False,
            "secret_exposed": False,
        },
        "market_probe_inputs": {
            "ebay_read_only": ebay_probe,
        },
    }

    listing_probe = _listing_metadata_probe_from_packet(packet_record=packet_record, packet=packet)
    if listing_probe:
        handoff["listing_metadata_probe"] = listing_probe
    return handoff


def merge_runtime_handoff_input(body: dict[str, Any], handoff: dict[str, Any]) -> dict[str, Any]:
    """Merge packet-derived Runtime inputs without overwriting explicit user input."""

    merged = dict(body)
    packet_handoff = handoff.get("platform_data_packet_handoff")
    if isinstance(packet_handoff, dict):
        merged.setdefault("platform_data_packet_handoff", packet_handoff)

    existing_market = merged.get("market_probe_inputs") if isinstance(merged.get("market_probe_inputs"), dict) else {}
    handoff_market = handoff.get("market_probe_inputs") if isinstance(handoff.get("market_probe_inputs"), dict) else {}
    if handoff_market:
        market_probe_inputs = dict(existing_market)
        for key, value in handoff_market.items():
            market_probe_inputs.setdefault(key, value)
        merged["market_probe_inputs"] = market_probe_inputs

    if "listing_metadata_probe" not in merged and isinstance(handoff.get("listing_metadata_probe"), dict):
        merged["listing_metadata_probe"] = handoff["listing_metadata_probe"]
    return merged


def _ebay_probe_from_packet(*, packet_record: dict[str, Any], packet: dict[str, Any]) -> dict[str, Any]:
    present = list(packet.get("present_resource_keys") or [])
    missing = list(packet.get("missing_resource_keys") or [])
    section_summary = packet.get("section_summary") if isinstance(packet.get("section_summary"), list) else []
    source_label = str(packet.get("source_label") or "")
    lineage = packet.get("lineage") if isinstance(packet.get("lineage"), dict) else {}
    official = source_label == "official_api" or lineage.get("probe_live_read_performed") is True
    status = "ready" if present else "pending_connector"
    confidence = "high" if official and not missing else "medium" if present else "low"
    source_type = "official_api" if official else "merchant_provided"
    packet_id = str(packet_record.get("packet_id") or "")
    summary = (
        f"Sanitized eBay read-only packet {packet_id or 'latest'} is available with "
        f"{len(present)}/{packet.get('resource_count') or len(section_summary) or len(present)} resource sections present. "
        f"Missing sections: {', '.join(missing) if missing else 'none'}. "
        "Use as Runtime context only; it does not authorize eBay writes."
    )
    return {
        "status": status,
        "source_type": source_type,
        "confidence": confidence,
        "summary": summary,
        "packet_id": packet_record.get("packet_id"),
        "packet_status": packet.get("status"),
        "source_label": packet.get("source_label"),
        "source_mode": packet.get("source_mode") or packet_record.get("source_mode"),
        "metrics": {
            "resource_count": packet.get("resource_count"),
            "present_resource_keys": present,
            "missing_resource_keys": missing,
            "source_gap_count": packet.get("source_gap_count"),
            "field_gap_count": packet.get("field_gap_count"),
            "section_summary": _safe_section_summary(section_summary),
            "readiness_for_modules": packet.get("readiness_for_modules") if isinstance(packet.get("readiness_for_modules"), dict) else {},
        },
        "next_action": "Run product workflow with this sanitized packet; keep publish and store edits confirmation-gated.",
        "access_token_returned_to_runtime": False,
        "raw_ebay_response_stored": False,
        "real_platform_writes_enabled": False,
        "secret_exposed": False,
    }


def _listing_metadata_probe_from_packet(*, packet_record: dict[str, Any], packet: dict[str, Any]) -> dict[str, Any]:
    lineage = packet.get("lineage") if isinstance(packet.get("lineage"), dict) else {}
    if packet.get("source_label") != "official_api" and lineage.get("probe_live_read_performed") is not True:
        return {}
    sections = _sections_by_key(packet)
    policies = _section_data(sections, "account_business_policies")
    taxonomy = _section_data(sections, "taxonomy_listing_metadata")
    if not policies and not taxonomy:
        return {}
    marketplace = str(packet.get("marketplace") or taxonomy.get("marketplace_id") or policies.get("policy_marketplace") or "EBAY_US")
    category_id = str(taxonomy.get("category_id") or "")
    required_aspects = taxonomy.get("required_aspects") if isinstance(taxonomy.get("required_aspects"), list) else []
    return {
        "marketplace_id": marketplace,
        "category_id": category_id,
        "category_tree_id": str(taxonomy.get("category_tree_id") or "0"),
        "source_type": "official_api",
        "confidence": "high",
        "source_packet_id": packet_record.get("packet_id"),
        "taxonomy_response": {
            "aspects": [
                {"localizedAspectName": str(name), "aspectConstraint": {"aspectRequired": True}}
                for name in required_aspects
                if str(name).strip()
            ],
        },
        "fulfillment_policy_response": _policy_response(
            array_key="fulfillmentPolicies",
            id_key="fulfillmentPolicyId",
            policy_id=policies.get("fulfillment_policy_id"),
            marketplace=marketplace,
        ),
        "payment_policy_response": _policy_response(
            array_key="paymentPolicies",
            id_key="paymentPolicyId",
            policy_id=policies.get("payment_policy_id"),
            marketplace=marketplace,
        ),
        "return_policy_response": _policy_response(
            array_key="returnPolicies",
            id_key="returnPolicyId",
            policy_id=policies.get("return_policy_id"),
            marketplace=marketplace,
        ),
        "live_enabled": False,
        "real_execution_allowed": False,
        "secret_exposed": False,
    }


def _sections_by_key(packet: dict[str, Any]) -> dict[str, dict[str, Any]]:
    sections = packet.get("sections") if isinstance(packet.get("sections"), list) else []
    return {
        str(section.get("key")): section
        for section in sections
        if isinstance(section, dict) and section.get("key")
    }


def _section_data(sections: dict[str, dict[str, Any]], key: str) -> dict[str, Any]:
    section = sections.get(key) if isinstance(sections.get(key), dict) else {}
    data = section.get("data") if isinstance(section.get("data"), dict) else {}
    return data


def _policy_response(*, array_key: str, id_key: str, policy_id: Any, marketplace: str) -> dict[str, Any]:
    if not policy_id:
        return {array_key: []}
    return {
        array_key: [
            {
                id_key: policy_id,
                "name": "Sanitized policy from latest eBay read-only packet",
                "marketplaceId": marketplace,
            }
        ]
    }


def _safe_section_summary(section_summary: list[Any]) -> list[dict[str, Any]]:
    safe = []
    for item in section_summary:
        if not isinstance(item, dict):
            continue
        safe.append(
            {
                "key": item.get("key"),
                "source_type": item.get("source_type"),
                "status": item.get("status"),
                "data_present": bool(item.get("data_present")),
                "confidence": item.get("confidence"),
                "missing_required_fields": list(item.get("missing_required_fields") or []),
            }
        )
    return safe
