"""IP, logo, and brand-word screening over sanitized eBay data packets."""

from __future__ import annotations

import re
from typing import Any, Iterable

from .repository import SaaSRepository


CONTRACT_VERSION = "2026-05-20-ip-logo-brand-screening"

PROTECTED_BRAND_TERMS = {
    "adidas",
    "airpods",
    "apple",
    "chanel",
    "dior",
    "disney",
    "fender",
    "gibson",
    "gucci",
    "harley",
    "hello kitty",
    "iphone",
    "ipad",
    "lego",
    "louis vuitton",
    "marvel",
    "nike",
    "nintendo",
    "pokemon",
    "rolex",
    "samsung",
    "sony",
    "starbucks",
    "star wars",
    "stanley",
    "tesla",
    "yamaha",
}

LOGO_OR_WATERMARK_TERMS = {
    "brand mark",
    "copyright",
    "logo",
    "registered mark",
    "trademark",
    "watermark",
    "©",
    "®",
}

MERCHANT_TEXT_KEYS = {
    "title",
    "subtitle",
    "description",
    "description_html",
    "brand",
    "manufacturer",
    "model",
    "mpn",
    "sku",
    "category",
    "leaf_category",
    "aspects",
    "item_specifics",
    "image",
    "images",
    "picture",
    "pictures",
    "picture_url",
    "image_url",
    "url",
}

LISTING_COVERAGE_FIELDS = {"sku", "title", "price", "quantity", "condition"}


def build_ip_logo_brand_screening(
    repository: SaaSRepository,
    *,
    company_id: str,
    store_id: str,
    packet_id: str | None = None,
) -> dict[str, Any]:
    packet_record = _select_packet(repository, company_id=company_id, store_id=store_id, packet_id=packet_id)
    if not packet_record:
        return {
            "contract_version": CONTRACT_VERSION,
            "status": "blocked_missing_packet",
            "store_id": store_id,
            "packet_id": packet_id or "",
            "risk_level": "unknown",
            "risk_items": [],
            "coverage_gaps": ["official_sanitized_packet_missing"],
            "next_actions": ["先完成 eBay 官方只读同步并生成标准数据包。"],
            "runtime_gets_raw_ebay_token": False,
            "real_platform_writes_enabled": False,
            "secret_exposed": False,
        }
    return screen_ip_logo_brand_risk(packet_record)


def screen_ip_logo_brand_risk(packet_record: dict[str, Any]) -> dict[str, Any]:
    packet = packet_record.get("packet") if isinstance(packet_record.get("packet"), dict) else {}
    sections = packet.get("sections") if isinstance(packet.get("sections"), list) else []
    text_fields = list(_iter_packet_text_fields(sections))
    risk_items: list[dict[str, Any]] = []
    risk_items.extend(_brand_term_hits(text_fields))
    risk_items.extend(_logo_or_watermark_hits(text_fields))
    risk_items.extend(_category_brand_aspect_warnings(sections))
    coverage_gaps = _coverage_gaps(sections=sections, text_fields=text_fields)
    required_inputs = _required_inputs(sections=sections, text_fields=text_fields, coverage_gaps=coverage_gaps)
    status = _screening_status(risk_items=risk_items, coverage_gaps=coverage_gaps, text_fields=text_fields)
    return {
        "contract_version": CONTRACT_VERSION,
        "status": status,
        "source_packet_id": packet_record.get("packet_id") or packet.get("packet_id") or "",
        "source_mode": packet_record.get("source_mode") or packet.get("source_mode") or "",
        "source_label": packet.get("source_label") or packet_record.get("source_mode") or "",
        "store_id": packet_record.get("store_id") or packet.get("store_id") or "",
        "platform": packet_record.get("platform") or packet.get("platform") or "ebay",
        "risk_level": _risk_level(risk_items=risk_items, coverage_gaps=coverage_gaps, text_fields=text_fields),
        "checks": {
            "brand_word_scan": True,
            "logo_watermark_text_scan": True,
            "image_url_filename_scan": True,
            "visual_logo_recognition": "provider_required",
            "legal_trademark_database_lookup": "provider_required",
            "uses_official_sanitized_packet": (packet_record.get("source_mode") or packet.get("source_mode")) == "official_api",
        },
        "scanned_field_count": len(text_fields),
        "scanned_text_characters": sum(len(item["text"]) for item in text_fields),
        "listing_candidate_count": _listing_candidate_count(sections),
        "required_inputs": required_inputs,
        "blocks_full_store_screening": any(item["status"] != "ready" for item in required_inputs),
        "risk_items": risk_items,
        "coverage_gaps": coverage_gaps,
        "confirmation_suggestions": _confirmation_suggestions(risk_items=risk_items, coverage_gaps=coverage_gaps),
        "next_actions": _next_actions(risk_items=risk_items, coverage_gaps=coverage_gaps, text_fields=text_fields),
        "limits": [
            "当前版本只扫描官方标准数据包里的可见文本、字段名、图片 URL 或文件名。",
            "真实 Logo 图像识别和商标数据库核验需要后续接入专门 provider。",
            "该体检只做风险预警，不构成法律意见，也不会自动修改或下架 eBay listing。",
        ],
        "runtime_gets_raw_ebay_token": False,
        "real_platform_writes_enabled": False,
        "secret_exposed": False,
    }


def _select_packet(
    repository: SaaSRepository,
    *,
    company_id: str,
    store_id: str,
    packet_id: str | None,
) -> dict[str, Any] | None:
    if packet_id:
        packet = repository.get_platform_data_packet(company_id=company_id, packet_id=packet_id)
        if packet and packet.get("store_id") == store_id:
            return packet
        return None
    packets = repository.list_platform_data_packets(company_id=company_id, store_id=store_id, platform="ebay", limit=1)
    return packets[0] if packets else None


def _iter_packet_text_fields(sections: list[Any]) -> Iterable[dict[str, str]]:
    for section in sections:
        if not isinstance(section, dict):
            continue
        section_key = str(section.get("key") or "section")
        data = section.get("data") if isinstance(section.get("data"), (dict, list)) else {}
        yield from _iter_text(data, path=section_key)


def _iter_text(value: Any, *, path: str) -> Iterable[dict[str, str]]:
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            normalized_key = str(key).strip().lower()
            if isinstance(child, str) and (_is_merchant_text_key(normalized_key) or _looks_like_image_or_url(child)):
                text = child.strip()
                if text:
                    yield {"path": child_path, "key": normalized_key, "text": text[:1000]}
            elif isinstance(child, (dict, list)):
                yield from _iter_text(child, path=child_path)
            elif _is_merchant_text_key(normalized_key) and child is not None:
                text = str(child).strip()
                if text:
                    yield {"path": child_path, "key": normalized_key, "text": text[:500]}
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _iter_text(child, path=f"{path}[{index}]")
    elif isinstance(value, str) and _looks_like_image_or_url(value):
        yield {"path": path, "key": "url", "text": value.strip()[:1000]}


def _is_merchant_text_key(key: str) -> bool:
    if key in MERCHANT_TEXT_KEYS:
        return True
    return any(token in key for token in ("title", "brand", "description", "image", "picture", "specific", "aspect", "url"))


def _looks_like_image_or_url(value: str) -> bool:
    text = value.strip().lower()
    return text.startswith(("http://", "https://")) or any(ext in text for ext in (".jpg", ".jpeg", ".png", ".webp", ".gif"))


def _brand_term_hits(text_fields: list[dict[str, str]]) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    for field in text_fields:
        text = field["text"]
        normalized = _normalize_text(text)
        for term in sorted(PROTECTED_BRAND_TERMS, key=len, reverse=True):
            if _contains_term(normalized, term):
                hits.append(
                    {
                        "risk_id": "protected_brand_term",
                        "severity": "high" if _high_signal_path(field["path"]) else "medium",
                        "label": "疑似品牌/IP 词",
                        "term": term,
                        "source_path": field["path"],
                        "evidence": _excerpt(text, term),
                        "recommended_action": "确认商家是否拥有授权；无授权时删除品牌/IP/角色词，并改成通用描述。",
                        "confirmation_required": True,
                    }
                )
    return _dedupe_risks(hits)


def _logo_or_watermark_hits(text_fields: list[dict[str, str]]) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    for field in text_fields:
        normalized = _normalize_text(field["text"])
        for term in sorted(LOGO_OR_WATERMARK_TERMS, key=len, reverse=True):
            if _contains_term(normalized, term):
                hits.append(
                    {
                        "risk_id": "logo_or_watermark_text_signal",
                        "severity": "medium",
                        "label": "Logo / 水印 / 版权提示",
                        "term": term,
                        "source_path": field["path"],
                        "evidence": _excerpt(field["text"], term),
                        "recommended_action": "检查图片是否含 Logo、水印、版权声明或竞品素材；未授权素材不要进入刊登。",
                        "confirmation_required": True,
                    }
                )
    return _dedupe_risks(hits)


def _category_brand_aspect_warnings(sections: list[Any]) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    for section in sections:
        if not isinstance(section, dict) or section.get("key") != "taxonomy_listing_metadata":
            continue
        data = section.get("data") if isinstance(section.get("data"), dict) else {}
        required = [str(item).strip().lower() for item in data.get("required_aspects") or []]
        if "brand" in required:
            warnings.append(
                {
                    "risk_id": "brand_aspect_requires_review",
                    "severity": "medium",
                    "label": "eBay 类目要求 Brand 字段",
                    "term": "Brand",
                    "source_path": "taxonomy_listing_metadata.required_aspects",
                    "evidence": f"category_id={data.get('category_id') or 'unknown'} / leaf_category={data.get('leaf_category') or 'unknown'}",
                    "recommended_action": "发布前确认 Brand 是自有/已授权/真实无品牌；不能为了搜索流量写未经授权品牌名。",
                    "confirmation_required": True,
                }
            )
    return warnings


def _coverage_gaps(*, sections: list[Any], text_fields: list[dict[str, str]]) -> list[str]:
    gaps: list[str] = []
    inventory = next((section for section in sections if isinstance(section, dict) and section.get("key") == "inventory_and_offers"), None)
    evaluation = (inventory or {}).get("field_evaluation") if isinstance((inventory or {}).get("field_evaluation"), dict) else {}
    missing = set(str(item) for item in evaluation.get("missing_required_fields") or [])
    for field in sorted(missing & LISTING_COVERAGE_FIELDS):
        gaps.append(f"inventory_and_offers_missing_{field}")
    keys = {item["key"] for item in text_fields}
    if not any("title" in key for key in keys):
        gaps.append("listing_title_not_available_for_scan")
    if not any("description" in key for key in keys):
        gaps.append("listing_description_not_available_for_scan")
    if not any("brand" in key or "specific" in key or "aspect" in key for key in keys):
        gaps.append("listing_brand_or_item_specifics_not_available_for_scan")
    if not any(key in {"image", "images", "picture", "pictures", "picture_url", "image_url", "url"} or "image" in key or "picture" in key for key in keys):
        gaps.append("listing_images_not_available_for_logo_scan")
    if not _has_taxonomy_context(sections):
        gaps.append("listing_category_not_available_for_scan")
    if not _has_inventory_or_offer_context(sections):
        gaps.append("inventory_or_offer_detail_not_available_for_scan")
    return sorted(dict.fromkeys(gaps))


def _required_inputs(*, sections: list[Any], text_fields: list[dict[str, str]], coverage_gaps: list[str]) -> list[dict[str, Any]]:
    keys = {item["key"] for item in text_fields}

    def has_key_token(*tokens: str) -> bool:
        return any(any(token in key for token in tokens) for key in keys)

    title_ready = has_key_token("title")
    description_ready = has_key_token("description")
    brand_ready = has_key_token("brand", "specific", "aspect")
    image_ready = has_key_token("image", "picture", "url") and "listing_images_not_available_for_logo_scan" not in coverage_gaps
    taxonomy_ready = _has_taxonomy_context(sections)
    inventory_ready = _has_inventory_or_offer_context(sections)

    return [
        {
            "key": "title_description",
            "label": "标题 / 描述",
            "status": "ready" if title_ready and description_ready else "missing",
            "detail": "已拿到标题和描述" if title_ready and description_ready else "缺标题或描述，不能完整判断品牌词和侵权表述。",
        },
        {
            "key": "brand_item_specifics",
            "label": "品牌词 / Item specifics",
            "status": "ready" if brand_ready else "missing",
            "detail": "已拿到品牌或 item specifics 字段" if brand_ready else "缺 Brand、aspects 或 item specifics，不能判断品牌使用边界。",
        },
        {
            "key": "image_source",
            "label": "图片 URL / 来源",
            "status": "ready" if image_ready else "missing",
            "detail": "已拿到图片 URL 或来源字段" if image_ready else "缺图片 URL/来源，不能扫描 Logo、水印和素材授权风险。",
        },
        {
            "key": "category_taxonomy",
            "label": "eBay 类目",
            "status": "ready" if taxonomy_ready else "missing",
            "detail": "已拿到类目或 taxonomy 元数据" if taxonomy_ready else "缺 eBay 类目，不能判断类目必填字段和 Brand 风险。",
        },
        {
            "key": "inventory_offer",
            "label": "库存 / offer",
            "status": "ready" if inventory_ready else "missing",
            "detail": "已拿到库存或 offer 上下文" if inventory_ready else "缺库存/offer 上下文，不能声称完成全店商品筛查。",
        },
    ]


def _listing_candidate_count(sections: list[Any]) -> int:
    inventory = next((section for section in sections if isinstance(section, dict) and section.get("key") == "inventory_and_offers"), None)
    data = inventory.get("data") if isinstance(inventory, dict) and isinstance(inventory.get("data"), dict) else {}
    for key in ("items", "inventory_items", "offers", "listings"):
        value = data.get(key)
        if isinstance(value, list):
            return len(value)
    return 1 if data else 0


def _has_taxonomy_context(sections: list[Any]) -> bool:
    for section in sections:
        if not isinstance(section, dict) or section.get("key") != "taxonomy_listing_metadata":
            continue
        data = section.get("data") if isinstance(section.get("data"), dict) else {}
        return any(data.get(key) for key in ("category_id", "leaf_category", "required_aspects", "aspects", "item_specifics"))
    return False


def _has_inventory_or_offer_context(sections: list[Any]) -> bool:
    inventory = next((section for section in sections if isinstance(section, dict) and section.get("key") == "inventory_and_offers"), None)
    data = inventory.get("data") if isinstance(inventory, dict) and isinstance(inventory.get("data"), dict) else {}
    if any(data.get(key) for key in ("inventory_item_count", "offer_count", "location_count")):
        return True
    for key in ("items", "inventory_items", "offers", "listings"):
        value = data.get(key)
        if isinstance(value, list) and value:
            return True
    return False


def _screening_status(*, risk_items: list[dict[str, Any]], coverage_gaps: list[str], text_fields: list[dict[str, str]]) -> str:
    if risk_items:
        return "needs_rights_review"
    if not text_fields or "listing_title_not_available_for_scan" in coverage_gaps:
        return "blocked_missing_listing_content"
    if coverage_gaps:
        return "ready_with_coverage_gaps"
    return "ready_no_hits"


def _risk_level(*, risk_items: list[dict[str, Any]], coverage_gaps: list[str], text_fields: list[dict[str, str]]) -> str:
    severities = {item.get("severity") for item in risk_items}
    if "high" in severities:
        return "high"
    if risk_items:
        return "medium"
    if not text_fields or "listing_title_not_available_for_scan" in coverage_gaps:
        return "unknown"
    if coverage_gaps:
        return "medium"
    return "low"


def _confirmation_suggestions(*, risk_items: list[dict[str, Any]], coverage_gaps: list[str]) -> list[dict[str, Any]]:
    suggestions: list[dict[str, Any]] = []
    if risk_items:
        suggestions.append(
            {
                "action_type": "listing_ip_risk_review",
                "title": "复核疑似品牌/IP/Logo 风险",
                "reason": "检测到疑似品牌词、IP 词、Logo/水印/版权提示或 Brand 字段风险；发布前必须确认授权和素材来源。",
                "default_action": "hold",
                "high_risk": True,
            }
        )
    if coverage_gaps:
        suggestions.append(
            {
                "action_type": "listing_content_gap_review",
                "title": "补齐 Listing 文本和图片后再做侵权体检",
                "reason": "官方数据包缺少标题、描述、图片或关键 Listing 字段，当前不能完整判断 IP/Logo/品牌词风险。",
                "default_action": "hold",
                "high_risk": False,
            }
        )
    return suggestions


def _next_actions(*, risk_items: list[dict[str, Any]], coverage_gaps: list[str], text_fields: list[dict[str, str]]) -> list[str]:
    actions: list[str] = []
    if risk_items:
        actions.append("先处理疑似品牌/IP/Logo 风险，保留授权证明或改成通用描述。")
    if coverage_gaps:
        actions.append("补齐 Listing 标题、描述、图片和 item specifics 后重新体检。")
    if not actions and text_fields:
        actions.append("当前可见文本未命中内置风险词，发布前仍需确认图片授权和品牌使用权。")
    actions.append("后续接入商标数据库和视觉识别 provider，提升 Logo / 品牌图案检测能力。")
    return actions


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.lower())


def _contains_term(normalized_text: str, term: str) -> bool:
    pattern = r"(?<![a-z0-9])" + re.escape(term.lower()) + r"(?![a-z0-9])"
    return re.search(pattern, normalized_text) is not None


def _high_signal_path(path: str) -> bool:
    lowered = path.lower()
    return any(token in lowered for token in ("title", "brand", "description", "image", "picture"))


def _excerpt(text: str, term: str) -> str:
    lowered = text.lower()
    index = lowered.find(term.lower())
    if index < 0:
        return text[:160]
    start = max(0, index - 60)
    end = min(len(text), index + len(term) + 60)
    return text[start:end]


def _dedupe_risks(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str]] = set()
    deduped: list[dict[str, Any]] = []
    for item in items:
        key = (str(item.get("risk_id") or ""), str(item.get("term") or ""), str(item.get("source_path") or ""))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped[:50]
