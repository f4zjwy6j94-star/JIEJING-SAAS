"""Grounded, backend-only product image understanding for AI CEO intake."""

from __future__ import annotations

import json
import math
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable


FAL_VISION_ENDPOINT = "https://fal.run/openrouter/router/vision"
DEFAULT_FAL_VISION_MODEL = "google/gemini-2.5-flash"
MAX_AI_CEO_SOURCE_IMAGES = 8
PRODUCT_VISION_CONTRACT_VERSION = "jiejing_ai_ceo_product_vision_intake_v1"
_ROLE_QUALIFIED_FACTS = {"net_weight_g": "net_weight", "product_origin": "manufacturing_origin"}
_SOURCE_FACT_KEYS = {
    "product_name",
    "source_url",
    "material",
    "product_dimensions_cm",
    "net_weight_g",
    "product_origin",
    "supplier_item_number",
    "supplier_brand",
    "craft",
    "style",
    "packaging_type",
    "included_items",
}
_CRITICAL_REQUIRED_KEYS = (
    "product_name",
    "sku",
    "condition",
    "material",
    "package_weight_g",
    "package_length_cm",
    "package_width_cm",
    "package_height_cm",
    "unit_cost",
    "selling_price",
    "currency",
    "quantity",
    "item_location",
    "image_urls",
    "image_rights_confirmed",
)
_SECRET_PATTERN = re.compile(
    r"\b(access[_-]?token|refresh[_-]?token|api[_-]?key|password|secret)\s*[:=]\s*[^,\s;，；]+",
    flags=re.IGNORECASE,
)


class ProductVisionError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


Transport = Callable[..., dict[str, Any]]


@dataclass(slots=True)
class FalProductVisionClient:
    credential: str
    transport: Transport | None = None
    model: str = DEFAULT_FAL_VISION_MODEL
    endpoint: str = FAL_VISION_ENDPOINT
    timeout_seconds: int = 55
    proxy_url: str = ""

    def analyze(self, *, image_urls: list[str], merchant_message: str) -> dict[str, Any]:
        safe_urls = [str(value or "").strip() for value in image_urls[:MAX_AI_CEO_SOURCE_IMAGES]]
        if not safe_urls or any(not value.startswith("https://") for value in safe_urls):
            raise ProductVisionError("vision_images_missing", "product vision requires secure source image URLs")
        if not self.credential:
            raise ProductVisionError("vision_provider_not_configured", "product vision provider is not configured")
        payload = {
            "image_urls": safe_urls,
            "prompt": _vision_prompt(merchant_message=merchant_message, image_count=len(safe_urls)),
            "system_prompt": (
                "You extract ecommerce product evidence from merchant-supplied images. "
                "Return one strict JSON object only. Never guess missing values, never convert net weight into package weight, "
                "never convert product origin into ship-from location, and preserve contradictory source claims as conflicts."
            ),
            "model": str(self.model or DEFAULT_FAL_VISION_MODEL).strip(),
            "temperature": 0,
            "max_tokens": 2600,
            "reasoning": False,
            "enable_web_search": False,
        }
        transport = self.transport or _post_json
        try:
            raw = transport(
                endpoint=self.endpoint,
                authorization=f"Key {self.credential}",
                payload=payload,
                timeout_seconds=max(10, min(int(self.timeout_seconds or 0), 90)),
                proxy_url=self.proxy_url,
            )
        except ProductVisionError:
            raise
        except Exception as exc:  # pragma: no cover - provider/network dependent
            raise ProductVisionError("vision_provider_failed", "product vision provider request failed") from exc
        response = raw.get("data") if isinstance(raw.get("data"), dict) else raw
        output = str(response.get("output") or response.get("text") or "").strip()
        parsed = _parse_json_object(output)
        if not parsed:
            raise ProductVisionError("vision_output_invalid", "product vision provider did not return valid structured facts")
        usage = response.get("usage") if isinstance(response.get("usage"), dict) else {}
        return {
            "contract_version": PRODUCT_VISION_CONTRACT_VERSION,
            "status": "completed",
            "provider": "fal",
            "model": str(self.model or DEFAULT_FAL_VISION_MODEL).strip(),
            "analysis": _sanitize_analysis(parsed),
            "usage": _sanitize_usage(usage),
            "image_count": len(safe_urls),
            "signed_source_urls_persisted": False,
            "frontend_gets_provider_key": False,
            "real_platform_writes_enabled": False,
            "secret_exposed": False,
        }


def fal_product_vision_client_from_env() -> FalProductVisionClient:
    credential = str(os.environ.get("JIEJING_FAL_KEY") or os.environ.get("FAL_KEY") or "").strip()
    if not credential:
        key_id = str(os.environ.get("JIEJING_FAL_KEY_ID") or os.environ.get("FAL_KEY_ID") or "").strip()
        key_secret = str(os.environ.get("JIEJING_FAL_KEY_SECRET") or os.environ.get("FAL_KEY_SECRET") or "").strip()
        if key_id and key_secret:
            credential = f"{key_id}:{key_secret}"
    return FalProductVisionClient(
        credential=credential,
        model=str(os.environ.get("JIEJING_FAL_VISION_MODEL") or DEFAULT_FAL_VISION_MODEL).strip(),
        endpoint=str(os.environ.get("JIEJING_FAL_VISION_ENDPOINT") or FAL_VISION_ENDPOINT).strip(),
        timeout_seconds=_env_int("JIEJING_FAL_VISION_TIMEOUT_SECONDS", 55, minimum=10, maximum=90),
        proxy_url=str(
            os.environ.get("JIEJING_FAL_PROXY_URL")
            or os.environ.get("FAL_PROXY_URL")
            or os.environ.get("HTTPS_PROXY")
            or os.environ.get("HTTP_PROXY")
            or ""
        ).strip(),
    )


def build_product_vision_capability_status() -> dict[str, Any]:
    """Return merchant-safe availability without exposing provider configuration."""

    client = fal_product_vision_client_from_env()
    configured = bool(str(client.credential or "").strip())
    return {
        "contract_version": "jiejing_product_image_recognition_capability_v1",
        "configured": configured,
        "status": "ready" if configured else "not_configured",
        "max_source_images": MAX_AI_CEO_SOURCE_IMAGES,
        "extracts_visible_facts_only": True,
        "merchant_review_required": True,
        "frontend_gets_provider_key": False,
        "secret_exposed": False,
    }


def build_product_vision_fact_packet(
    *,
    analysis: dict[str, Any],
    merchant_message: str,
    source_assets: list[dict[str, Any]],
) -> dict[str, Any]:
    body = analysis.get("analysis") if isinstance(analysis.get("analysis"), dict) else {}
    conflicts = _normalize_conflicts(body.get("conflicts"))
    conflict_keys = {str(item.get("field") or "") for item in conflicts}
    product_name_record = body.get("product_name")
    facts_body = body.get("facts") if isinstance(body.get("facts"), dict) else {}
    candidates = {**facts_body, "product_name": product_name_record}
    extracted_suggestions: dict[str, Any] = {}
    evidence: dict[str, Any] = {}
    unresolved_roles: list[str] = []
    for key, record in candidates.items():
        safe_key = str(key or "").strip()
        if safe_key not in _SOURCE_FACT_KEYS or safe_key in conflict_keys:
            continue
        if safe_key in _ROLE_QUALIFIED_FACTS and (
                not isinstance(record, dict) or record.get("evidence_role") != _ROLE_QUALIFIED_FACTS[safe_key]):
            unresolved_roles.append(safe_key)
            continue
        value, confidence, image_indexes = _fact_record(record)
        if not value or confidence < 0.82:
            continue
        extracted_suggestions[safe_key] = value
        evidence[safe_key] = {
            "source_type": "ai_extracted_from_merchant_image",
            "image_indexes": image_indexes,
            "confidence": confidence,
            "merchant_confirmation_received": False,
            **({"evidence_role": record["evidence_role"]} if safe_key in _ROLE_QUALIFIED_FACTS else {}),
        }
    source_url = _first_http_url(merchant_message)
    if source_url:
        extracted_suggestions["source_url"] = source_url
        evidence["source_url"] = {
            "source_type": "merchant_supplied_link",
            "image_indexes": [],
            "confidence": 1.0,
            "merchant_confirmation_received": False,
        }
    # Vision is an evidence extractor, not the buyer-copy authority.  Even if a
    # provider returns legacy ``listing_copy`` output, keep it outside the
    # persisted product-fact packet so it cannot flow into a publish form.
    listing_copy: dict[str, Any] = {}
    # Defaults are not evidence and must not manufacture conflicts with an
    # explicit supplier currency or assert the product's condition.
    derived = dict(extracted_suggestions)
    source_records: list[dict[str, Any]] = []
    for index, asset in enumerate(source_assets[:MAX_AI_CEO_SOURCE_IMAGES], start=1):
        source_records.append(
            {
                "type": "merchant_product_image",
                "source_index": index,
                "asset_id": _safe_text(asset.get("asset_id"), 120),
                "sha256": _safe_hash(asset.get("sha256")),
                "original_filename": _safe_text(asset.get("original_filename"), 120),
                "width": _safe_positive_int(asset.get("width")),
                "height": _safe_positive_int(asset.get("height")),
                "rights_status": "pending_merchant_confirmation",
                "signed_url_persisted": False,
                "secret_exposed": False,
            }
        )
    if source_url:
        source_records.append(
            {
                "type": "merchant_product_link",
                "url": source_url,
                "rights_status": "not_applicable",
                "secret_exposed": False,
            }
        )
    # Neither model extraction nor a URL pasted into chat is merchant
    # confirmation.  Keep every required field unknown until the merchant
    # explicitly confirms it in the product-fact module.
    vision_suggestion_keys = [
        key
        for key, value in derived.items()
        if value not in (None, "", [], {})
    ]
    source_confirmation_unknown = ["source_url" if source_url else "merchant_owned_product_confirmed"]
    unknown = list(dict.fromkeys([*_CRITICAL_REQUIRED_KEYS, *vision_suggestion_keys, *unresolved_roles, *source_confirmation_unknown]))
    blocked_by = [f"merchant_product_fact_missing:{key}" for key in _CRITICAL_REQUIRED_KEYS]
    blocked_by.append("merchant_product_source_unconfirmed")
    blocked_by.extend(f"merchant_product_fact_conflict:{key}" for key in sorted(conflict_keys) if key)
    product_name = _safe_text(derived.get("product_name"), 120)
    return {
        "contract_version": "merchant_product_fact_packet_v1",
        "vision_contract_version": PRODUCT_VISION_CONTRACT_VERSION,
        "source": "backend_product_vision_extraction",
        "source_mode": "merchant_source_supplied" if source_url else "merchant_images_supplied",
        "product_name": product_name,
        "source_confirmed_facts": {},
        "merchant_confirmed_facts": {},
        "derived_listing_suggestions": derived,
        "listing_copy": listing_copy,
        "buyer_copy_requires_validated_listing_generation": True,
        "field_evidence": evidence,
        "fact_conflicts": conflicts,
        "unknown_facts": unknown,
        "source_records": source_records,
        "ready_for_listing_draft": bool(product_name),
        "listing_readiness": {
            "ready_fact_count": 0,
            "total_fact_count": len(_CRITICAL_REQUIRED_KEYS) + 1,
            "completion_percent": 0,
            "ready_for_listing_generation": False,
            "ready_for_real_publish": False,
            "reason": "图片与链接已形成待核对商品事实；买家文案必须再经过 AI Listing 生成与校验",
        },
        "blocked_by": blocked_by,
        "vision_usage": analysis.get("usage") if isinstance(analysis.get("usage"), dict) else {},
        "signed_source_urls_persisted": False,
        "requires_human_review_before_publish": True,
        "real_platform_writes_enabled": False,
        "secret_exposed": False,
    }


def product_vision_prompt_context(packet: dict[str, Any]) -> dict[str, Any]:
    """Bound the product evidence passed into the merchant text model."""

    return {
        "contract_version": PRODUCT_VISION_CONTRACT_VERSION,
        "product_name": _safe_text(packet.get("product_name"), 120),
        "source_confirmed_facts": packet.get("source_confirmed_facts") if isinstance(packet.get("source_confirmed_facts"), dict) else {},
        "derived_listing_suggestions": packet.get("derived_listing_suggestions") if isinstance(packet.get("derived_listing_suggestions"), dict) else {},
        "listing_copy": {},
        "buyer_copy_requires_validated_listing_generation": True,
        "fact_conflicts": packet.get("fact_conflicts") if isinstance(packet.get("fact_conflicts"), list) else [],
        "unknown_facts": packet.get("unknown_facts") if isinstance(packet.get("unknown_facts"), list) else [],
        "source_record_count": len(packet.get("source_records") or []),
        "evidence_policy": {
            "source_facts_are_ai_extracted_not_merchant_confirmed": True,
            "conflicts_must_remain_unresolved": True,
            "net_weight_is_not_package_weight": True,
            "product_origin_is_not_item_location": True,
            "image_rights_require_merchant_confirmation": True,
        },
        "signed_source_urls_included": False,
        "secret_exposed": False,
    }


def _vision_prompt(*, merchant_message: str, image_count: int) -> str:
    return json.dumps(
        {
            "task": "Extract a grounded product fact packet from all merchant images for an eBay Listing draft.",
            "merchant_message": _safe_text(merchant_message, 900),
            "image_count": image_count,
            "image_indexing": "The first image_urls entry is image 1.",
            "required_output": {
                "product_name": {"value": "", "confidence": 0.0, "image_indexes": []},
                "facts": {
                    "material": {"value": "", "confidence": 0.0, "image_indexes": []},
                    "product_dimensions_cm": {"value": "L x W x H", "confidence": 0.0, "image_indexes": []},
                    "net_weight_g": {"value": "", "confidence": 0.0, "image_indexes": [], "evidence_role": ""},
                    "product_origin": {"value": "", "confidence": 0.0, "image_indexes": [], "evidence_role": ""},
                    "supplier_item_number": {"value": "", "confidence": 0.0, "image_indexes": []},
                    "supplier_brand": {"value": "", "confidence": 0.0, "image_indexes": []},
                    "craft": {"value": "", "confidence": 0.0, "image_indexes": []},
                    "style": {"value": "", "confidence": 0.0, "image_indexes": []},
                    "packaging_type": {"value": "", "confidence": 0.0, "image_indexes": []},
                    "included_items": {"value": "", "confidence": 0.0, "image_indexes": []},
                },
                "conflicts": [{"field": "material", "values": [], "image_indexes": [], "reason": ""}],
                "missing_facts": [],
            },
            "rules": [
                "Return JSON only.",
                "Use only visible image evidence and merchant_message; do not use web knowledge.",
                "If sources say resin and purple sand for material, put both in conflicts and omit the material fact.",
                "A value labelled N.W. or net weight is net_weight_g only, never package_weight_g.",
                "For net_weight_g classify evidence_role as net_weight, gross_weight, or unspecified_weight. A generic weight/重量 column is unspecified_weight even at high confidence; never infer net weight from it.",
                "An origin such as Dehua, Fujian is product_origin only, never item_location or ship-from.",
                "For product_origin classify evidence_role as manufacturing_origin, supplier_dispatch, supplier_address, or unknown. Only an explicit product manufacturing origin qualifies; 发货地 is supplier_dispatch, not origin.",
                "Do not resolve ambiguous dimension/weight tables into a confirmed product or package size. Respect the full merchant message's conflicts, negation, and unknown fields, not just isolated numbers.",
                "A supplier brand is supplier_brand only; it does not prove merchant brand authorization.",
                "Do not claim image commercial rights, stock, price, cost, condition, ship-from, handling time, or package dimensions unless explicit.",
                "Do not produce buyer-facing Listing title, selling points, description, compatibility, or device-fit claims; a separate validated Listing generator owns that step.",
            ],
        },
        ensure_ascii=False,
    )


def _post_json(*, endpoint: str, authorization: str, payload: dict, timeout_seconds: int, proxy_url: str) -> dict[str, Any]:
    request = urllib.request.Request(
        endpoint,
        method="POST",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"authorization": authorization, "content-type": "application/json", "user-agent": "Jiejing product vision/1.0"},
    )
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url})
    ) if proxy_url else urllib.request.build_opener()
    try:
        with opener.open(request, timeout=timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:  # pragma: no cover - provider dependent
        raise ProductVisionError("vision_provider_http_error", f"product vision provider HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:  # pragma: no cover - provider dependent
        raise ProductVisionError("vision_provider_unavailable", "product vision provider is temporarily unavailable") from exc
    except json.JSONDecodeError as exc:  # pragma: no cover - provider dependent
        raise ProductVisionError("vision_provider_invalid_json", "product vision provider returned invalid JSON") from exc


def _parse_json_object(value: str) -> dict[str, Any]:
    text = str(value or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            return {}
        try:
            parsed = json.loads(text[start : end + 1])
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}


def _sanitize_analysis(value: dict[str, Any]) -> dict[str, Any]:
    serialized = json.dumps(value, ensure_ascii=False, default=str)
    serialized = _SECRET_PATTERN.sub(r"\1=[redacted]", serialized)
    return json.loads(serialized[:60_000]) if len(serialized) <= 60_000 else {}


def _sanitize_usage(value: dict[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        safe[key] = _safe_positive_int(value.get(key))
    try:
        cost = float(value.get("cost") or 0)
    except (TypeError, ValueError):
        cost = 0.0
    safe["cost_usd"] = round(cost, 8) if math.isfinite(cost) and cost >= 0 else 0.0
    return safe


def _fact_record(value: Any) -> tuple[str, float, list[int]]:
    record = value if isinstance(value, dict) else {"value": value}
    text = _safe_text(record.get("value"), 500)
    try:
        confidence = float(record.get("confidence") or 0)
    except (TypeError, ValueError):
        confidence = 0.0
    indexes = []
    for item in record.get("image_indexes", []) if isinstance(record.get("image_indexes"), list) else []:
        parsed = _safe_positive_int(item)
        if parsed and parsed <= MAX_AI_CEO_SOURCE_IMAGES and parsed not in indexes:
            indexes.append(parsed)
    return text, max(0.0, min(confidence, 1.0)), indexes


def _normalize_conflicts(value: Any) -> list[dict[str, Any]]:
    conflicts: list[dict[str, Any]] = []
    for item in value[:12] if isinstance(value, list) else []:
        if not isinstance(item, dict):
            continue
        field = _safe_text(item.get("field"), 80)
        if not field:
            continue
        values = [_safe_text(candidate, 160) for candidate in (item.get("values") or [])[:6]] if isinstance(item.get("values"), list) else []
        indexes = [_safe_positive_int(candidate) for candidate in (item.get("image_indexes") or [])[:8]] if isinstance(item.get("image_indexes"), list) else []
        conflicts.append(
            {
                "field": field,
                "values": [candidate for candidate in values if candidate],
                "image_indexes": [candidate for candidate in indexes if candidate],
                "reason": _safe_text(item.get("reason"), 300),
                "requires_merchant_confirmation": True,
            }
        )
    return conflicts


def _normalize_listing_copy(value: Any) -> dict[str, Any]:
    raw = value if isinstance(value, dict) else {}
    points = [
        _safe_text(item, 240)
        for item in (raw.get("selling_points") if isinstance(raw.get("selling_points"), list) else [])[:5]
    ]
    return {
        "title": _safe_text(raw.get("title"), 80),
        "selling_points": [item for item in points if item],
        "description": _safe_text(raw.get("description"), 2400),
    }


def _first_http_url(value: str) -> str:
    match = re.search(r"https?://[^\s,，；;]+", str(value or ""), flags=re.IGNORECASE)
    return _safe_text(match.group(0), 700) if match else ""


def _safe_text(value: Any, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()[:limit]
    return _SECRET_PATTERN.sub(r"\1=[redacted]", text)


def _safe_hash(value: Any) -> str:
    text = str(value or "").strip().lower()
    return text if re.fullmatch(r"[a-f0-9]{64}", text) else ""


def _safe_positive_int(value: Any) -> int:
    try:
        parsed = int(value or 0)
    except (TypeError, ValueError):
        return 0
    return parsed if parsed > 0 else 0


def _env_int(key: str, default: int, *, minimum: int, maximum: int) -> int:
    try:
        value = int(str(os.environ.get(key) or default).strip())
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(value, maximum))
