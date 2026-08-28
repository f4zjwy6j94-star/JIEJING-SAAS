"""Project-scoped AI Listing draft generation over merchant-confirmed facts."""

from __future__ import annotations

import json
import re
from typing import Any

from .operations_metering import MeteredModelClient, model_cost_measurement
from .platform_data_packet_handoff import build_runtime_handoff_from_platform_packet
from .repository import (
    SaaSRepository,
    normalize_listing_project_identity,
    normalize_merchant_product_fact_packet,
)


LISTING_DRAFT_GENERATION_CONTRACT_VERSION = "listing_ai_draft_generation_v1"
LISTING_DRAFT_CORE_FACT_KEYS = ("product_name", "condition", "material")
_CURRENT_DRAFT_FIELD_KEYS = frozenset(
    {"title", "selling_points", "description", "category", "item_specifics", "keywords"}
)


def listing_draft_core_missing_fields(packet: dict[str, Any]) -> list[str]:
    facts = packet.get("merchant_confirmed_facts") if isinstance(packet.get("merchant_confirmed_facts"), dict) else {}
    return [key for key in LISTING_DRAFT_CORE_FACT_KEYS if not str(facts.get(key) or packet.get(key) or "").strip()]


def generate_listing_draft(
    *,
    repository: SaaSRepository,
    company_id: str,
    store_id: str,
    user_id: str,
    listing_project_identity: dict[str, Any],
    merchant_product_fact_packet: dict[str, Any],
    current_draft_fields: dict[str, Any],
    model_client: Any,
    model_resolution: dict[str, Any] | None = None,
    packet_record: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Generate and persist one Listing version without any eBay write."""

    identity = normalize_listing_project_identity(listing_project_identity)
    packet = normalize_merchant_product_fact_packet(
        merchant_product_fact_packet,
        source="authenticated_merchant_request",
    )
    missing_core = listing_draft_core_missing_fields(packet)
    if not identity.get("key"):
        missing_core.append("listing_project_identity")
    if missing_core:
        return {
            "status": "blocked",
            "blocked_by": [f"listing_core_fact_missing:{key}" for key in missing_core],
            "missing_fields": missing_core,
            "model_called": False,
            "usage_consumed": False,
            "report": None,
            "listing_project_identity": identity,
            "real_platform_writes_enabled": False,
            "secret_exposed": False,
        }

    safe_current = _safe_current_draft_fields(current_draft_fields)
    selected_packet = packet_record
    if selected_packet is None:
        packets = repository.list_platform_data_packets(
            company_id=company_id,
            store_id=store_id,
            platform="ebay",
            limit=1,
        )
        selected_packet = packets[0] if packets else None
    ebay_handoff = build_runtime_handoff_from_platform_packet(selected_packet)
    model_meta = _safe_model_metadata(model_resolution)
    product_name = str(packet.get("product_name") or "")[:120]
    task = repository.create_task(
        company_id=company_id,
        store_id=store_id,
        user_id=user_id,
        task_type="listing_draft_generation",
        title=f"AI Listing 草稿：{product_name}"[:180],
        input_data={
            "contract_version": LISTING_DRAFT_GENERATION_CONTRACT_VERSION,
            "listing_project_identity": identity,
            "merchant_product_fact_packet": packet,
            "current_draft_fields": safe_current,
            "source_packet_id": str((selected_packet or {}).get("packet_id") or ""),
            "model_usage_owner": _usage_owner(model_resolution),
            "provider_key": model_meta.get("provider_key"),
            "model_usage_required": True,
            "frontend_gets_model_api_key": False,
            "runtime_gets_raw_ebay_token": False,
            "real_platform_writes_enabled": False,
            "secret_exposed": False,
        },
    )
    metered = MeteredModelClient(model_client)
    try:
        model_result = metered.generate_text(
            system_prompt=_listing_system_prompt(),
            user_prompt=_listing_user_prompt(
                packet=packet,
                current_draft_fields=safe_current,
                ebay_handoff=ebay_handoff,
                marketplace=str((selected_packet or {}).get("packet", {}).get("marketplace") or "EBAY_US"),
            ),
            temperature=0.2,
            max_output_tokens=1800,
            timeout_seconds=60,
        )
        model_output = _parse_model_output(model_result)
        listing_handoff = _merge_listing_fields(
            packet=packet,
            current_draft_fields=safe_current,
            model_output=model_output,
            ebay_handoff=ebay_handoff,
        )
        missing_fields = _listing_missing_fields(packet=packet, listing_handoff=listing_handoff)
        version = _next_listing_version(repository, company_id=company_id, identity=identity)
        report = repository.save_listing_draft_report(
            task=task,
            listing_project_identity=identity,
            listing_handoff=listing_handoff,
            merchant_product_fact_packet=packet,
            missing_fields=missing_fields,
            model_metadata=model_meta,
            version=version,
        )
        usage = metered.usage_summary()
        task = repository.update_task_status(
            task_id=task["task_id"],
            company_id=company_id,
            status="completed",
            output={
                "report_id": report.get("report_id"),
                "version": version,
                "missing_fields": missing_fields,
                "model_called": True,
                "real_platform_writes_enabled": False,
                "secret_exposed": False,
            },
            audit_summary="AI Listing draft generated and saved without an eBay write.",
        )
        if int(usage.get("request_count") or 0) > 0:
            usage_owner = _usage_owner(model_resolution)
            cost = model_cost_measurement(usage_owner=usage_owner, usage=usage)
            repository.record_model_usage(
                company_id=company_id,
                user_id=user_id,
                task_id=task["task_id"],
                usage_owner=usage_owner,
                model_family=str(model_meta.get("provider_key") or "provider_neutral"),
                model_label=str(model_meta.get("model") or getattr(model_client, "model", "")),
                request_count=int(usage.get("request_count") or 0),
                input_tokens=int(usage.get("input_tokens") or 0),
                output_tokens=int(usage.get("output_tokens") or 0),
                total_tokens=int(usage.get("total_tokens") or 0),
                cost_minor=int(cost.get("cost_minor") or 0),
                currency=str(cost.get("currency") or "CNY"),
                cost_status=str(cost.get("cost_status") or "unavailable"),
                idempotency_key=f"{task['task_id']}:listing-draft-model-usage:v1",
                details={
                    "provider_reported_tokens": bool(usage.get("total_tokens")),
                    "prompts_stored": False,
                    "responses_stored": False,
                },
            )
        return {
            "status": "completed",
            "task": task,
            "report": report,
            "listing_project_identity": identity,
            "listing_handoff": listing_handoff,
            "missing_fields": missing_fields,
            "model_called": True,
            "usage_consumed": bool(usage.get("request_count")),
            "model_usage": usage,
            "real_platform_writes_enabled": False,
            "secret_exposed": False,
        }
    except Exception as exc:
        repository.update_task_status(
            task_id=task["task_id"],
            company_id=company_id,
            status="failed",
            output={
                "failure_code": _safe_failure_code(exc),
                "model_called": bool(metered.usage_summary().get("request_count")),
                "real_platform_writes_enabled": False,
                "secret_exposed": False,
            },
            audit_summary="AI Listing draft generation failed before any eBay write.",
        )
        raise


def _safe_current_draft_fields(value: Any) -> dict[str, Any]:
    raw = value if isinstance(value, dict) else {}
    safe: dict[str, Any] = {}
    for key in _CURRENT_DRAFT_FIELD_KEYS:
        field = raw.get(key)
        if isinstance(field, str):
            safe[key] = field[:4000]
        elif key in {"selling_points", "keywords"} and isinstance(field, list):
            safe[key] = [str(item)[:240] for item in field[:12] if str(item).strip()]
        elif key == "item_specifics" and isinstance(field, dict):
            safe[key] = {str(name)[:80]: str(item)[:240] for name, item in list(field.items())[:30]}
    return safe


def _safe_model_metadata(value: Any) -> dict[str, Any]:
    raw = value if isinstance(value, dict) else {}
    return {
        "provider_key": str(raw.get("provider_key") or "provider_neutral")[:80],
        "model": str(raw.get("model") or "")[:160],
        "mode": str(raw.get("mode") or "")[:80],
        "model_tier": str(raw.get("model_tier") or "fast")[:40],
        "secret_exposed": False,
    }


def _usage_owner(value: Any) -> str:
    raw = value if isinstance(value, dict) else {}
    return "merchant_account_byok" if raw.get("merchant_pays_provider_directly") is True else "jiejing_platform_trial"


def _listing_system_prompt() -> str:
    return (
        "You are the Listing writer inside Jiejing, an eBay-first merchant SaaS. Return ONLY one JSON object. "
        "Generate buyer-facing copy and suggestions, never authoritative product or account facts. "
        "Do not invent brand, MPN, material, size, weight, origin, cost, inventory, item location, image rights, "
        "category ID, policy ID, or platform execution. Keep English buyer copy concise and factual."
    )


def _listing_user_prompt(
    *, packet: dict[str, Any], current_draft_fields: dict[str, Any], ebay_handoff: dict[str, Any], marketplace: str
) -> str:
    prompt = {
        "contract": LISTING_DRAFT_GENERATION_CONTRACT_VERSION,
        "marketplace": marketplace[:40],
        "merchant_product_facts": packet,
        "merchant_current_draft": current_draft_fields,
        "sanitized_ebay_context": ebay_handoff,
        "required_output": {
            "title": "string, <=80 chars",
            "selling_points": ["string"],
            "description": "string",
            "category_suggestion": "string, suggestion only",
            "keywords": ["string"],
            "item_specifics": {"Type": "string"},
        },
        "forbidden_authority": [
            "category_id",
            "condition",
            "quantity",
            "material",
            "weight",
            "dimensions",
            "policy_ids",
            "image_rights",
        ],
    }
    return json.dumps(prompt, ensure_ascii=False, separators=(",", ":"))


def _parse_model_output(result: Any) -> dict[str, Any]:
    text = str((result or {}).get("text") or "").strip() if isinstance(result, dict) else ""
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE).strip()
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError("listing_model_output_not_object")
    title = str(parsed.get("title") or "").strip()[:80]
    description = str(parsed.get("description") or "").strip()[:6000]
    if not title or not description:
        raise ValueError("listing_model_output_missing_buyer_copy")
    return {
        "title": title,
        "selling_points": _string_list(parsed.get("selling_points"), limit=8, item_limit=300),
        "description": description,
        "category_suggestion": str(parsed.get("category_suggestion") or "")[:160],
        "keywords": _string_list(parsed.get("keywords"), limit=20, item_limit=80),
        "item_specifics": _safe_item_specifics(parsed.get("item_specifics")),
    }


def _merge_listing_fields(
    *,
    packet: dict[str, Any],
    current_draft_fields: dict[str, Any],
    model_output: dict[str, Any],
    ebay_handoff: dict[str, Any],
) -> dict[str, Any]:
    facts = packet.get("merchant_confirmed_facts") if isinstance(packet.get("merchant_confirmed_facts"), dict) else {}
    metadata = ebay_handoff.get("listing_metadata_probe") if isinstance(ebay_handoff.get("listing_metadata_probe"), dict) else {}
    title = str(current_draft_fields.get("title") or model_output.get("title") or packet.get("product_name") or "")[:80]
    description = str(current_draft_fields.get("description") or model_output.get("description") or "")[:6000]
    selling_points = _string_list(
        current_draft_fields.get("selling_points") or model_output.get("selling_points"), limit=8, item_limit=300
    )
    keywords = _string_list(current_draft_fields.get("keywords") or model_output.get("keywords"), limit=20, item_limit=80)
    aspects = _safe_item_specifics(model_output.get("item_specifics"))
    current_aspects = _safe_item_specifics(current_draft_fields.get("item_specifics"))
    aspects.update(current_aspects)
    for key, label in (("brand", "Brand"), ("mpn", "MPN"), ("material", "Material"), ("style", "Style")):
        if str(facts.get(key) or "").strip():
            aspects[label] = [str(facts[key])[:240]]
        elif label in {"Brand", "MPN", "Material"}:
            aspects.pop(label, None)
    category_id = str(metadata.get("category_id") or "")[:80]
    category_suggestion = str(current_draft_fields.get("category") or model_output.get("category_suggestion") or "")[:160]
    policies = {
        "fulfillmentPolicyId": _first_policy_id(metadata.get("fulfillment_policy_response"), "fulfillmentPolicies", "fulfillmentPolicyId"),
        "paymentPolicyId": _first_policy_id(metadata.get("payment_policy_response"), "paymentPolicies", "paymentPolicyId"),
        "returnPolicyId": _first_policy_id(metadata.get("return_policy_response"), "returnPolicies", "returnPolicyId"),
    }
    policies = {key: value for key, value in policies.items() if value}
    image_urls = re.findall(r"https?://[^\s,，；;]+", str(facts.get("image_urls") or ""))[:12]
    quantity = _positive_int(facts.get("quantity"))
    item_specifics = {key: values for key, values in aspects.items() if values}
    missing = list(packet.get("unknown_facts") or [])
    return {
        "contract_version": LISTING_DRAFT_GENERATION_CONTRACT_VERSION,
        "title": title,
        "selling_points": selling_points,
        "description_seed": description,
        "keywords": keywords,
        "category_id": category_id,
        "category_suggestion": category_suggestion,
        "condition": str(facts.get("condition") or "")[:40],
        "quantity": str(quantity or ""),
        "sku": str(facts.get("sku") or "")[:80],
        "item_specifics": item_specifics,
        "merchant_product_fact_packet": packet,
        "ebay_inventory_item_draft": {
            "sku": str(facts.get("sku") or "")[:80],
            "condition": str(facts.get("condition") or "")[:40],
            "product": {
                "title": title,
                "description": description,
                "aspects": item_specifics,
                "imageUrls": image_urls,
            },
            "availability": {"shipToLocationAvailability": {"quantity": quantity or 0}},
        },
        "ebay_offer_draft": {
            "categoryId": category_id,
            "marketplaceId": str(metadata.get("marketplace_id") or "EBAY_US")[:40],
            "listingDescription": description,
            "listingPolicies": policies,
            "pricingSummary": {
                "price": {
                    "value": str(facts.get("selling_price") or "")[:40],
                    "currency": str(facts.get("currency") or "USD")[:12],
                }
            },
        },
        "image_requirements": {
            "imageUrls": image_urls,
            "rights_check_required": facts.get("image_rights_confirmed") is not True,
            "ebay_accessible_url_required": not bool(image_urls),
        },
        "logistics_requirements": {
            "item_location": str(facts.get("item_location") or "")[:160],
            "package_weight_g": str(facts.get("package_weight_g") or "")[:40],
            "package_length_cm": str(facts.get("package_length_cm") or "")[:40],
            "package_width_cm": str(facts.get("package_width_cm") or "")[:40],
            "package_height_cm": str(facts.get("package_height_cm") or "")[:40],
            "fulfillment_policy_id": policies.get("fulfillmentPolicyId", ""),
            "payment_policy_id": policies.get("paymentPolicyId", ""),
            "return_policy_id": policies.get("returnPolicyId", ""),
        },
        "publish_preflight_gaps": missing,
        "merchant_required_answers": missing,
        "listing_readiness": {
            "ready_for_listing_draft": True,
            "ready_for_real_publish": False,
            "reason": "AI Listing 草稿已生成；商品事实、eBay 字段和确认中心仍需复核。",
        },
        "draft_source": "project_scoped_live_model",
        "ready_for_listing_draft": True,
        "triggers_real_platform_write": False,
        "real_platform_writes_enabled": False,
        "secret_exposed": False,
    }


def _listing_missing_fields(*, packet: dict[str, Any], listing_handoff: dict[str, Any]) -> list[str]:
    missing = [str(item) for item in packet.get("unknown_facts") or [] if str(item).strip()]
    offer = listing_handoff.get("ebay_offer_draft") if isinstance(listing_handoff.get("ebay_offer_draft"), dict) else {}
    policies = offer.get("listingPolicies") if isinstance(offer.get("listingPolicies"), dict) else {}
    if not offer.get("categoryId"):
        missing.append("ebay_category_id")
    for key, label in (
        ("fulfillmentPolicyId", "fulfillment_policy_id"),
        ("paymentPolicyId", "payment_policy_id"),
        ("returnPolicyId", "return_policy_id"),
    ):
        if not policies.get(key):
            missing.append(label)
    return list(dict.fromkeys(missing))


def _next_listing_version(repository: SaaSRepository, *, company_id: str, identity: dict[str, str]) -> int:
    version = 1
    for report in repository.list_reports(company_id=company_id):
        if report.get("report_type") != "listing.package":
            continue
        body = report.get("report") if isinstance(report.get("report"), dict) else {}
        report_identity = normalize_listing_project_identity(body.get("listing_project_identity"))
        if report_identity == identity:
            version = max(version, int(body.get("version") or 0) + 1)
    return version


def _safe_item_specifics(value: Any) -> dict[str, list[str]]:
    if isinstance(value, str):
        raw: dict[str, Any] = {}
        for line in value.splitlines():
            if ":" not in line:
                continue
            key, item = line.split(":", 1)
            raw[key.strip()] = item.strip()
        value = raw
    if not isinstance(value, dict):
        return {}
    safe: dict[str, list[str]] = {}
    for raw_key, raw_value in list(value.items())[:30]:
        key = str(raw_key or "").strip()[:80]
        if not key:
            continue
        values = raw_value if isinstance(raw_value, list) else [raw_value]
        clean = [str(item).strip()[:240] for item in values[:8] if str(item).strip()]
        if clean:
            safe[key] = clean
    return safe


def _string_list(value: Any, *, limit: int, item_limit: int) -> list[str]:
    items = value if isinstance(value, list) else re.split(r"\r?\n|[,，;；]+", str(value or ""))
    return [str(item).strip()[:item_limit] for item in items if str(item).strip()][:limit]


def _first_policy_id(value: Any, array_key: str, id_key: str) -> str:
    raw = value if isinstance(value, dict) else {}
    rows = raw.get(array_key) if isinstance(raw.get(array_key), list) else []
    first = rows[0] if rows and isinstance(rows[0], dict) else {}
    return str(first.get(id_key) or "")[:120]


def _positive_int(value: Any) -> int:
    try:
        return max(0, int(float(str(value))))
    except (TypeError, ValueError):
        return 0


def _safe_failure_code(exc: Exception) -> str:
    text = f"{exc.__class__.__name__}:{exc}".lower()
    if "json" in text or "listing_model_output" in text:
        return "listing_model_output_invalid"
    if "timeout" in text:
        return "listing_model_timeout"
    return "listing_model_generation_failed"
