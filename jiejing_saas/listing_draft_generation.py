"""Project-scoped AI Listing draft generation over merchant-confirmed facts."""

from __future__ import annotations

import json
import re
from typing import Any

from .operations_metering import MeteredModelClient, model_cost_measurement
from .listing_draft_checkpoint import (
    FIELD_KEYS as LISTING_EDIT_FIELD_KEYS, CheckpointValidationError, normalize_identity,
)
from .platform_data_packet_handoff import build_runtime_handoff_from_platform_packet
from .repository import (
    SaaSRepository,
    normalize_listing_project_identity,
    normalize_merchant_product_fact_packet,
    _redact_secret_like,
)
from .sensitive_text import contains_secret_like_data, contains_secret_like_text


LISTING_DRAFT_GENERATION_CONTRACT_VERSION = "listing_ai_draft_generation_v1"
LISTING_DRAFT_CORE_FACT_KEYS = ("product_name", "condition", "material")
LISTING_BUYER_COPY_MIN_POINTS = 3
LISTING_BUYER_COPY_MAX_POINTS = 5
LISTING_BUYER_COPY_REWRITE_CONTRACT = "listing_buyer_copy_rewrite_v1"
LISTING_BUYER_COPY_FIELDS = frozenset({"title", "selling_points", "description"})
_CURRENT_DRAFT_FIELD_KEYS = frozenset(
    {"title", "selling_points", "description", "category", "item_specifics", "keywords", "merchant_edited_fields"}
)
_MODEL_SUGGESTED_ITEM_SPECIFIC_KEYS = frozenset({"type"})
_COMPATIBILITY_ASPECT_KEY_PATTERN = re.compile(
    r"(?:compatib|device|screen[\s_-]*size|display[\s_-]*size|"
    r"to[\s_-]*fit|supported[\s_-]*(?:product|device)|"
    r"(?:tablet|phone|device)[\s_-]*size|(?:maximum|minimum)[\s_-]*(?:tablet|phone|device)|\bfits?\b)",
    flags=re.IGNORECASE,
)
_DEVICE_TARGET = r"(?:iPads?|iPhones?|Samsung|Galaxy|Kindle|Surface|tablets?|phones?|devices?|e-?readers?|screens?)"
_SIZE_TARGET = r"\d+(?:\.\d+)?(?:\s*(?:-|–|to)\s*\d+(?:\.\d+)?)?\s*[- ]?\s*(?:in(?:ch(?:es)?)?|\")"
_UNVERIFIED_COMPATIBILITY_PATTERNS = tuple(
    re.compile(pattern, flags=re.IGNORECASE)
    for pattern in (
        r"\bcompatible\s+with\b",
        r"\b(?:universal|wide|broad|extensive)\s+compatibility\b",
        rf"\b(?:use|using)\s+with\s+(?:(?:your|the|an?|Apple)\s+)?{_DEVICE_TARGET}\b",
        rf"\bmade\s+to\s+(?:fit|hold|support)\s+(?:(?:your|the|an?|Apple)\s+)?{_DEVICE_TARGET}\b",
        rf"\b(?:to\s+fit|fits?)\b(?:\s+\w+){{0,5}}\s+(?:(?:with|on|for)\s+)?(?:(?:your|the|an?|Apple)\s+)?{_DEVICE_TARGET}\b",
        rf"\bworks?\b(?:\s+\w+){{0,5}}\s+with\s+(?:(?:your|the|an?|Apple)\s+)?{_DEVICE_TARGET}\b",
        rf"\b(?:supports?|holds?|accommodates?)\b(?:\s+\w+){{0,7}}\s+{_DEVICE_TARGET}\b",
        rf"\bfor\s+(?:(?:your|the|an?|Apple)\s+)?{_DEVICE_TARGET}\b",
        rf"\buniversal(?:ly)?\b(?:\s+\w+){{0,5}}\s+(?:for\s+(?:an?\s+)?|){_DEVICE_TARGET}\b",
        rf"\b{_SIZE_TARGET}\s+{_DEVICE_TARGET}\b",
        rf"\b(?:iPad|iPhone|Galaxy|Kindle|Surface)\b(?:\s+\w+){{0,3}}\s+\b(?:stand|holder|case|cover|dock|mount)\b",
    )
)
_UNVERIFIED_DEVICE_PRODUCT_TYPE_PATTERN = re.compile(
    r"(?:\b(?:ipad|iphone|samsung|galaxy|kindle|surface)\b.{0,40}\b(?:stand|holder|case|cover|dock|mount)\b|"
    r"\b\d+(?:\.\d+)?(?:\s*[-–]\s*\d+(?:\.\d+)?)?\s*[- ]?\s*(?:in(?:ch(?:es)?)?|\")"
    r".{0,30}\b(?:tablet|phone|device|e-?reader)\b)",
    flags=re.IGNORECASE,
)
_DEVICE_TARGET_PATTERN = re.compile(rf"\b{_DEVICE_TARGET}\b", flags=re.IGNORECASE)
_COMPATIBILITY_INTENT_PATTERN = re.compile(
    r"(?:compatib|\b(?:fit|fits|works|pairs|supports|accepts|accommodates|holds|cradles|secures)\b|"
    r"\b(?:use|made)\s+(?:with|to)\b|\b(?:ready|friendly)\b|\btailored\s+to\b|"
    r"\bbuilt\s+around\b|\badjustable\s+across\b)",
    flags=re.IGNORECASE,
)
_NON_LATIN_MARKETPLACE_SCRIPT_PATTERN = re.compile(
    r"[\u0400-\u052f\u0600-\u06ff\u0900-\u097f\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]"
)
_HIGH_CONFIDENCE_NON_ENGLISH_MARKERS = (
    (frozenset(
        {
            "almacenamiento", "almohadillas", "aluminio", "compacto", "construccion", "construcción",
            "ajustable", "descripcion", "descripción", "diseno", "diseño", "escritorio", "hecho", "medidas", "para",
            "plegable", "silicona", "soporte", "tableta",
        }
    ), 3),
    (frozenset({"bureau", "conçu", "leger", "léger", "pliable", "pour", "rangement", "tablette", "réglable"}), 2),
    (frozenset({"bureau", "inklapbaar", "opvouwbare", "standaard", "tafel", "verstelbaar", "voor"}), 2),
    (frozenset({"aluminiowy", "biurko", "podstawka", "regulowany", "skladany", "składany", "stojak"}), 2),
    (frozenset({"faltbar", "faltbarer", "halter", "kompakt", "schreibtisch", "silikon", "ständer", "verstellbar"}), 2),
    (frozenset({"alumínio", "dobravel", "dobrável", "mesa", "para", "silicone", "suporte"}), 2),
    (frozenset({"alluminio", "pieghevole", "scrivania", "silicone", "supporto", "tavolo"}), 2),
)
_HIGH_RISK_MATERIAL_TERMS = tuple(
    sorted(
        {
            "abs plastic",
            "acrylic",
            "aluminum",
            "bamboo",
            "carbon fiber",
            "ceramic",
            "glass",
            "leather",
            "nylon",
            "polyester",
            "resin",
            "silicone",
            "stainless steel",
            "titanium",
        },
        key=len,
        reverse=True,
    )
)
_HIGH_RISK_PERFORMANCE_PATTERNS = tuple(
    re.compile(pattern, flags=re.IGNORECASE)
    for pattern in (
        r"\bwater[ -]?proof\b",
        r"\bwater[ -]?resistant\b",
        r"\bdust[ -]?proof\b",
        r"\bfire[ -]?proof\b",
        r"\bflame[ -]?retardant\b",
        r"\brust[ -]?proof\b",
    )
)
_WARRANTY_CLAIM_PATTERN = re.compile(r"\b(?:warrant(?:y|ies|ed)|guarantee(?:d)?)\b", flags=re.IGNORECASE)
_CERTIFICATION_CLAIM_PATTERN = re.compile(
    r"\b(?:certif(?:ied|ication)|(?:CE|FCC|RoHS|UL|ETL|FDA|ISO(?:\s*\d{4,5})?)[ -]?(?:approved|compliant))\b",
    flags=re.IGNORECASE,
)
_DIMENSION_SEQUENCE_PATTERN = re.compile(
    r"(?P<values>\d+(?:\.\d+)?(?:\s*[x×]\s*\d+(?:\.\d+)?){1,3})\s*"
    r"(?P<unit>mm|cm|m|in(?:ch(?:es)?)?|\"|ft|feet|foot)(?![A-Za-z])",
    flags=re.IGNORECASE,
)
_DIMENSION_VALUE_PATTERN = re.compile(
    r"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>mm|cm|m|in(?:ch(?:es)?)?|\"|ft|feet|foot)(?![A-Za-z])",
    flags=re.IGNORECASE,
)
_WEIGHT_VALUE_PATTERN = re.compile(
    r"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>mg|g|gram(?:s)?|kg|kilogram(?:s)?|oz|ounce(?:s)?|lb|lbs|pound(?:s)?)\b",
    flags=re.IGNORECASE,
)
_UNSUPPORTED_NUMERIC_SPEC_PATTERN = re.compile(
    r"\b\d+(?:\.\d+)?\s*(?:ml|millilit(?:er|re)s?|l|lit(?:er|re)s?|fl\.?\s*oz|mah|wh|w|watts?|v|volts?)\b",
    flags=re.IGNORECASE,
)


class ListingDraftGenerationError(RuntimeError):
    """Safe, structured failure after a Listing model attempt."""

    def __init__(
        self,
        *,
        failure_code: str,
        task_id: str,
        model_called: bool,
        usage_consumed: bool,
        model_usage: dict[str, int],
        report_save_attempted: bool = True,
    ) -> None:
        super().__init__(failure_code)
        self.failure_code = str(failure_code or "listing_model_generation_failed")[:120]
        self.task_id = str(task_id or "")[:160]
        self.model_called = model_called is True
        self.usage_consumed = usage_consumed is True
        # Older callers and malformed values stay conservative. Only the
        # generation function's explicit False proves storage never started.
        self.report_save_attempted = report_save_attempted is not False
        self.model_usage = {
            key: max(0, int(model_usage.get(key) or 0))
            for key in ("request_count", "input_tokens", "output_tokens", "total_tokens")
        }


def listing_draft_core_missing_fields(packet: dict[str, Any]) -> list[str]:
    facts = _effective_listing_facts(packet)
    return [key for key in LISTING_DRAFT_CORE_FACT_KEYS if not str(facts.get(key) or packet.get(key) or "").strip()]


def listing_draft_generation_request_failure(current_draft_fields: Any, *, generation_mode: Any) -> str:
    """Validate explicit generation authority before resolving or charging a model."""
    if not isinstance(generation_mode, str) or generation_mode not in ("preserve_merchant_edits", "rewrite_buyer_copy"):
        return "listing_generation_mode_invalid"
    if generation_mode == "rewrite_buyer_copy":
        if not isinstance(current_draft_fields, dict) or set(current_draft_fields) != {
            *LISTING_EDIT_FIELD_KEYS, "merchant_edited_fields"
        }:
            return "listing_rewrite_snapshot_invalid"
        for key in LISTING_EDIT_FIELD_KEYS:
            value = current_draft_fields[key]
            if not isinstance(value, str) or len(value) > (1400 if key in ("description", "selling_points") else 800):
                return "listing_rewrite_snapshot_invalid"
            if "\x00" in value:
                return "listing_rewrite_snapshot_invalid"
            try:
                value.encode("utf-8")
            except UnicodeEncodeError:
                return "listing_rewrite_snapshot_invalid"
        edited = current_draft_fields["merchant_edited_fields"]
        if not isinstance(edited, list) or len(edited) > len(LISTING_EDIT_FIELD_KEYS) or any(
            not isinstance(key, str) or key not in LISTING_EDIT_FIELD_KEYS for key in edited
        ):
            return "listing_rewrite_snapshot_invalid"
        if contains_secret_like_data(current_draft_fields) or _redact_secret_like(current_draft_fields) != current_draft_fields:
            return "listing_rewrite_snapshot_sensitive_text"
    return ""


def is_listing_buyer_copy_rewrite_contract(value: Any) -> bool:
    """Only this bounded merchant-text DTO may bypass provider-label projection."""
    if not isinstance(value, dict) or set(value) != {
        "contract_version", "expected_base_report_id", "expected_checkpoint_revision", "previous_fields", "fields",
        "previous_merchant_edited_fields", "merchant_edited_fields",
    } or value["contract_version"] != LISTING_BUYER_COPY_REWRITE_CONTRACT:
        return False
    if (not isinstance(value["expected_base_report_id"], str)
        or not re.fullmatch(r"[A-Za-z0-9._:-]{1,160}", value["expected_base_report_id"])
        or type(value["expected_checkpoint_revision"]) is not int
        or not 0 <= value["expected_checkpoint_revision"] < 2147483647):
        return False
    for fields_key, edited_key in (("previous_fields", "previous_merchant_edited_fields"),
                                   ("fields", "merchant_edited_fields")):
        fields, edited = value[fields_key], value[edited_key]
        if not isinstance(fields, dict) or set(fields) != set(LISTING_EDIT_FIELD_KEYS) or listing_draft_generation_request_failure(
            {**fields, "merchant_edited_fields": edited}, generation_mode="rewrite_buyer_copy"
        ):
            return False
        if len(edited) != len(set(edited)):
            return False
    if contains_secret_like_data(value) or _redact_secret_like(value) != value:
        return False
    return (all(value["fields"][key] == value["previous_fields"][key]
                for key in LISTING_EDIT_FIELD_KEYS if key not in LISTING_BUYER_COPY_FIELDS)
            and set(value["merchant_edited_fields"]) == set(value["previous_merchant_edited_fields"]) - LISTING_BUYER_COPY_FIELDS)


def _generation_request_blocked(failure_code: str, identity: dict[str, str]) -> dict[str, Any]:
    return {"status": "blocked", "blocked_by": [failure_code], "failure_code": failure_code,
            "merchant_message": "重写请求不完整或已失效，请保留现有草稿并刷新后重试；本次未调用模型。",
            "missing_fields": [], "model_called": False, "usage_consumed": False, "report": None,
            "listing_project_identity": identity, "real_platform_writes_enabled": False, "secret_exposed": False}


def listing_draft_rewrite_source(
    *, repository: SaaSRepository, company_id: str, store_id: str, listing_project_identity: Any,
    current_draft_fields: dict[str, Any], expected_base_report_id: Any, expected_checkpoint_revision: Any,
    merchant_product_fact_packet: Any,
) -> dict[str, Any]:
    """Bind the copied editor snapshot to a saved, fully scoped source before model use."""
    if (not isinstance(expected_base_report_id, str)
        or not re.fullmatch(r"[A-Za-z0-9._:-]{1,160}", expected_base_report_id)
        or isinstance(expected_checkpoint_revision, bool) or not isinstance(expected_checkpoint_revision, int)
        or not 0 <= expected_checkpoint_revision < 2147483647):
        return {"failure_code": "listing_rewrite_source_invalid"}
    try:
        identity = normalize_identity(listing_project_identity)
        view = repository.get_listing_draft_checkpoint(company_id=company_id, store_id=store_id, identity=identity)
    except CheckpointValidationError:
        return {"failure_code": "listing_rewrite_source_invalid"}
    except KeyError:
        return {"failure_code": "listing_rewrite_source_conflict"}
    checkpoint = view.get("checkpoint") or {}
    if (view.get("current_base_report_id") != expected_base_report_id
        or view.get("current_revision") != expected_checkpoint_revision
        or checkpoint.get("base_report_id") != expected_base_report_id
        or checkpoint.get("fields") != {key: current_draft_fields[key] for key in LISTING_EDIT_FIELD_KEYS}
        or checkpoint.get("merchant_edited_fields") != sorted(set(current_draft_fields["merchant_edited_fields"]))):
        return {"failure_code": "listing_rewrite_source_conflict"}
    saved_packet = (view["current_base_report"].get("report") or {}).get("merchant_product_fact_packet")
    if not isinstance(saved_packet, dict):
        return {"failure_code": "listing_rewrite_source_facts_conflict"}
    normalized_saved = normalize_merchant_product_fact_packet(saved_packet, source="authenticated_merchant_request")
    submitted_packet = normalize_merchant_product_fact_packet(merchant_product_fact_packet, source="authenticated_merchant_request")
    fact_keys = ("merchant_confirmed_facts", "derived_listing_suggestions", "simulation_only", "source_records",
                 "field_evidence", "fact_conflicts", "buyer_copy_requires_validated_listing_generation",
                 "vision_contract_version", "source_mode", "sensitive_text_detected")
    if any(normalized_saved[key] != submitted_packet[key] for key in fact_keys):
        return {"failure_code": "listing_rewrite_source_facts_conflict"}
    # The editor snapshot is never authority for facts or publication flags.
    return {"failure_code": "", "base_report": view["current_base_report"], "packet": normalized_saved}


def listing_draft_merchant_copy_failure(
    current_draft_fields: Any,
    *,
    marketplace: str,
    merchant_product_fact_packet: dict[str, Any] | None = None,
) -> str:
    """Validate only explicit merchant edits before resolving or calling a model."""

    return _merchant_edited_copy_failure_code(
        _safe_current_draft_fields(current_draft_fields),
        marketplace=str(marketplace or "EBAY_US"),
        merchant_product_fact_packet=merchant_product_fact_packet,
    )


def _effective_listing_facts(packet: dict[str, Any]) -> dict[str, Any]:
    merchant = packet.get("merchant_confirmed_facts") if isinstance(packet.get("merchant_confirmed_facts"), dict) else {}
    if packet.get("simulation_only") is not True:
        return dict(merchant)
    derived = packet.get("derived_listing_suggestions") if isinstance(packet.get("derived_listing_suggestions"), dict) else {}
    # Simulation suggestions may exercise the internal workflow, but they remain
    # separately labelled and can never become merchant-confirmed publish facts.
    return {**derived, **merchant}


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
    generation_mode: str = "preserve_merchant_edits",
    expected_base_report_id: str | None = None,
    expected_checkpoint_revision: int | None = None,
) -> dict[str, Any]:
    """Generate and persist one Listing version without any eBay write."""

    identity = normalize_listing_project_identity(listing_project_identity)
    request_failure = listing_draft_generation_request_failure(current_draft_fields, generation_mode=generation_mode)
    if request_failure:
        return _generation_request_blocked(request_failure, identity)
    if generation_mode == "rewrite_buyer_copy":
        source = listing_draft_rewrite_source(
            repository=repository, company_id=company_id, store_id=store_id,
            listing_project_identity=listing_project_identity, current_draft_fields=current_draft_fields,
            expected_base_report_id=expected_base_report_id, expected_checkpoint_revision=expected_checkpoint_revision,
            merchant_product_fact_packet=merchant_product_fact_packet,
        )
        if source["failure_code"]:
            return _generation_request_blocked(source["failure_code"], identity)
        merchant_product_fact_packet = source["packet"]
    packet = normalize_merchant_product_fact_packet(
        merchant_product_fact_packet,
        source="authenticated_merchant_request",
    )
    if packet.get("sensitive_text_detected") is True:
        return {
            "status": "blocked",
            "blocked_by": ["listing_product_fact_sensitive_text"],
            "failure_code": "listing_product_fact_sensitive_text",
            "merchant_message": "商品资料中包含疑似凭证或密钥文本，请删除后再保存；本次未调用模型。",
            "missing_fields": [],
            "model_called": False,
            "usage_consumed": False,
            "report": None,
            "listing_project_identity": identity,
            "real_platform_writes_enabled": False,
            "secret_exposed": False,
        }
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

    rewrite_buyer_copy = generation_mode == "rewrite_buyer_copy"
    safe_current = (
        {**{key: current_draft_fields[key] for key in LISTING_EDIT_FIELD_KEYS},
         "merchant_edited_fields": sorted(set(current_draft_fields["merchant_edited_fields"]))}
        if rewrite_buyer_copy else _safe_current_draft_fields(current_draft_fields)
    )
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
    marketplace = str((selected_packet or {}).get("packet", {}).get("marketplace") or "EBAY_US")[:40]
    merchant_copy_failure = "" if rewrite_buyer_copy else _merchant_edited_copy_failure_code(
        safe_current,
        marketplace=marketplace,
        merchant_product_fact_packet=packet,
    )
    if merchant_copy_failure:
        return {
            "status": "blocked",
            "blocked_by": [merchant_copy_failure],
            "failure_code": merchant_copy_failure,
            "merchant_message": "请先把商家手改文案调整为目标站点语言，并保留 3–5 条有事实依据的卖点。",
            "missing_fields": [],
            "model_called": False,
            "usage_consumed": False,
            "report": None,
            "listing_project_identity": identity,
            "real_platform_writes_enabled": False,
            "secret_exposed": False,
        }
    task = repository.create_task(
        company_id=company_id,
        store_id=store_id,
        user_id=user_id,
        task_type="listing_draft_generation",
        title=f"AI Listing 草稿：{product_name}"[:180],
        input_data={
            "contract_version": LISTING_DRAFT_GENERATION_CONTRACT_VERSION,
            "generation_mode": generation_mode,
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
    usage_recorded = False
    report_save_attempted = False
    try:
        model_output = _generate_valid_model_output(
            metered=metered,
            packet=packet,
            current_draft_fields=safe_current,
            ebay_handoff=ebay_handoff,
            marketplace=marketplace,
            generation_mode=generation_mode,
        )
        listing_handoff = _merge_listing_fields(
            packet=packet,
            current_draft_fields={} if rewrite_buyer_copy else safe_current,
            model_output=model_output,
            ebay_handoff=ebay_handoff,
            marketplace=marketplace,
        )
        if rewrite_buyer_copy:
            previous_fields = {key: safe_current[key] for key in LISTING_EDIT_FIELD_KEYS}
            listing_handoff["buyer_copy_rewrite"] = {
                "contract_version": LISTING_BUYER_COPY_REWRITE_CONTRACT,
                "expected_base_report_id": expected_base_report_id,
                "expected_checkpoint_revision": expected_checkpoint_revision,
                "previous_fields": previous_fields,
                "fields": {**previous_fields, "title": listing_handoff["title"],
                           "selling_points": "\n".join(listing_handoff["selling_points"]),
                           "description": listing_handoff["description_seed"]},
                "previous_merchant_edited_fields": list(safe_current["merchant_edited_fields"]),
                "merchant_edited_fields": [key for key in safe_current["merchant_edited_fields"]
                                          if key not in LISTING_BUYER_COPY_FIELDS],
            }
        missing_fields = _listing_missing_fields(packet=packet, listing_handoff=listing_handoff)
        version = _next_listing_version(repository, company_id=company_id, identity=identity)
        usage = metered.usage_summary()
        _record_listing_model_usage(
            repository=repository,
            company_id=company_id,
            user_id=user_id,
            task_id=task["task_id"],
            model_resolution=model_resolution,
            model_meta=model_meta,
            model_client=model_client,
            usage=usage,
            outcome="model_completed",
        )
        usage_recorded = bool(usage.get("request_count"))
        task = repository.update_task_status(
            task_id=task["task_id"],
            company_id=company_id,
            status="completed",
            output={
                "version": version,
                "missing_fields": missing_fields,
                "model_called": True,
                "usage_consumed": bool(usage.get("request_count")),
                "model_request_count": int(usage.get("request_count") or 0),
                "real_platform_writes_enabled": False,
                "secret_exposed": False,
            },
            audit_summary="AI Listing draft passed generation and quality validation without an eBay write.",
        )
        report_save_attempted = True
        report = repository.save_listing_draft_report(
            task=task,
            listing_project_identity=identity,
            listing_handoff=listing_handoff,
            merchant_product_fact_packet=packet,
            missing_fields=missing_fields,
            model_metadata=model_meta,
            version=version,
        )
        # The immediate response must carry the same authenticated ownership
        # as GET /reports; consumers must not infer it from browser state.
        report = {**report, "company_id": company_id, "store_id": store_id}
        try:
            task = repository.update_task_status(
                task_id=task["task_id"],
                company_id=company_id,
                status="completed",
                output={
                    "report_id": report.get("report_id"),
                    "version": version,
                    "missing_fields": missing_fields,
                    "model_called": True,
                    "usage_consumed": bool(usage.get("request_count")),
                    "model_request_count": int(usage.get("request_count") or 0),
                    "real_platform_writes_enabled": False,
                    "secret_exposed": False,
                },
                audit_summary="AI Listing draft generated and saved without an eBay write.",
            )
        except Exception:
            # The report is already a valid project artifact. A secondary task
            # metadata refresh must not tell the merchant to regenerate it.
            task = repository.get_task(company_id=company_id, task_id=task["task_id"]) or task
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
        usage = metered.usage_summary()
        failure_code = _safe_failure_code(exc)
        if not usage_recorded:
            try:
                _record_listing_model_usage(
                    repository=repository,
                    company_id=company_id,
                    user_id=user_id,
                    task_id=task["task_id"],
                    model_resolution=model_resolution,
                    model_meta=model_meta,
                    model_client=model_client,
                    usage=usage,
                    outcome="failed",
                    failure_code=failure_code,
                )
                usage_recorded = bool(usage.get("request_count"))
            except Exception:
                usage_recorded = False
        try:
            repository.update_task_status(
                task_id=task["task_id"],
                company_id=company_id,
                status="failed",
                output={
                    "failure_code": failure_code,
                    "model_called": bool(usage.get("request_count")),
                    "usage_consumed": bool(usage.get("request_count")),
                    "model_request_count": int(usage.get("request_count") or 0),
                    "usage_ledger_recorded": usage_recorded,
                    "real_platform_writes_enabled": False,
                    "secret_exposed": False,
                },
                audit_summary="AI Listing draft generation failed before any eBay write.",
            )
        except Exception:
            # Failure-audit storage can be unavailable for the same reason as
            # the original write. Preserve metered usage for quota settlement;
            # an ordinary audit exception would be mistaken for zero requests.
            pass
        raise ListingDraftGenerationError(
            failure_code=failure_code,
            task_id=task["task_id"],
            model_called=bool(usage.get("request_count")),
            usage_consumed=bool(usage.get("request_count")),
            model_usage=usage,
            report_save_attempted=report_save_attempted,
        ) from exc


def _safe_current_draft_fields(value: Any) -> dict[str, Any]:
    raw = value if isinstance(value, dict) else {}
    safe: dict[str, Any] = {}
    for key in _CURRENT_DRAFT_FIELD_KEYS - {"merchant_edited_fields"}:
        field = raw.get(key)
        if isinstance(field, str):
            if not contains_secret_like_text(field):
                safe[key] = field[:4000]
        elif key in {"selling_points", "keywords"} and isinstance(field, list):
            clean_items = [
                str(item)[:240]
                for item in field[:12]
                if str(item).strip() and not contains_secret_like_text(item)
            ]
            if clean_items:
                safe[key] = clean_items
        elif key == "item_specifics" and isinstance(field, dict):
            clean_specifics = {
                str(name)[:80]: str(item)[:240]
                for name, item in list(field.items())[:30]
                if not contains_secret_like_text(name) and not contains_secret_like_text(item)
            }
            if clean_specifics:
                safe[key] = clean_specifics
    edited_fields = raw.get("merchant_edited_fields") if isinstance(raw.get("merchant_edited_fields"), list) else []
    safe["merchant_edited_fields"] = [
        str(item)
        for item in edited_fields[:12]
        if str(item) in safe and str(item) in _CURRENT_DRAFT_FIELD_KEYS
    ]
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
        "category ID, policy ID, platform execution, or device compatibility. Keep English buyer copy concise and factual."
    )


def _listing_user_prompt(
    *,
    packet: dict[str, Any],
    current_draft_fields: dict[str, Any],
    ebay_handoff: dict[str, Any],
    marketplace: str,
    repair_failure_code: str = "",
    generation_mode: str = "preserve_merchant_edits",
) -> str:
    prompt = {
        "contract": LISTING_DRAFT_GENERATION_CONTRACT_VERSION,
        "marketplace": marketplace[:40],
        "merchant_product_facts": _listing_prompt_fact_packet(packet),
        "merchant_current_draft": current_draft_fields,
        "sanitized_ebay_context": ebay_handoff,
        "required_output": {
            "title": "string, <=80 chars",
            "selling_points": ["3 to 5 concise buyer-facing English strings; every claim must be grounded in merchant_product_facts"],
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
            "device_compatibility",
        ],
    }
    if generation_mode == "rewrite_buyer_copy":
        prompt["generation_mode"] = generation_mode
        prompt["merchant_current_draft"] = {}
        prompt["sanitized_ebay_context"] = {}
        prompt["required_output"] = {
            "title": "string, <=80 chars",
            "selling_points": ["3 to 5 concise factual English strings; newline-joined length <=1400 chars"],
            "description": "concise factual English string, <=1400 chars",
        }
    if repair_failure_code:
        prompt["repair_attempt"] = {
            "attempt": 1,
            "previous_failure_code": str(repair_failure_code)[:120],
            "instruction": "Regenerate the complete JSON once. Correct only format, marketplace language, and fact-boundary violations.",
        }
    return json.dumps(prompt, ensure_ascii=False, separators=(",", ":"))


def _listing_prompt_fact_packet(packet: dict[str, Any]) -> dict[str, Any]:
    merchant_facts = (
        packet.get("merchant_confirmed_facts")
        if isinstance(packet.get("merchant_confirmed_facts"), dict)
        else {}
    )
    prompt_packet: dict[str, Any] = {
        "contract_version": str(packet.get("contract_version") or "")[:80],
        "fact_scope": str(packet.get("fact_scope") or "merchant_product")[:40],
        "simulation_only": packet.get("simulation_only") is True,
        "merchant_confirmed_facts": merchant_facts,
        "provenance_summary": {
            "source_mode": str(packet.get("source_mode") or "")[:40],
            "source_record_count": len(packet.get("source_records") or []),
            "unknown_facts": [str(item)[:80] for item in (packet.get("unknown_facts") or [])[:40]],
        },
    }
    if packet.get("simulation_only") is True:
        prompt_packet["simulation_listing_suggestions"] = (
            packet.get("derived_listing_suggestions")
            if isinstance(packet.get("derived_listing_suggestions"), dict)
            else {}
        )
    return prompt_packet


def _generate_valid_model_output(
    *,
    metered: MeteredModelClient,
    packet: dict[str, Any],
    current_draft_fields: dict[str, Any],
    ebay_handoff: dict[str, Any],
    marketplace: str,
    generation_mode: str = "preserve_merchant_edits",
) -> dict[str, Any]:
    merchant_current_draft = _merchant_edited_current_draft_fields(current_draft_fields)
    prompt_args = {
        "packet": packet,
        "current_draft_fields": merchant_current_draft,
        "ebay_handoff": ebay_handoff,
        "marketplace": marketplace,
        "generation_mode": generation_mode,
    }
    model_result = metered.generate_text(
        system_prompt=_listing_system_prompt(),
        user_prompt=_listing_user_prompt(**prompt_args),
        temperature=0.2,
        max_output_tokens=1800,
        timeout_seconds=60,
    )
    try:
        return _parse_model_output(model_result, marketplace=marketplace, packet=packet, generation_mode=generation_mode)
    except (json.JSONDecodeError, TypeError, ValueError) as first_error:
        repair_code = _safe_failure_code(first_error)
    repaired_result = metered.generate_text(
        system_prompt=_listing_system_prompt(),
        user_prompt=_listing_user_prompt(**prompt_args, repair_failure_code=repair_code),
        temperature=0.1,
        max_output_tokens=1800,
        timeout_seconds=60,
    )
    return _parse_model_output(repaired_result, marketplace=marketplace, packet=packet, generation_mode=generation_mode)


def _merchant_edited_current_draft_fields(value: dict[str, Any]) -> dict[str, Any]:
    edited = {
        str(item or "").strip()
        for item in value.get("merchant_edited_fields") or []
        if str(item or "").strip() in _CURRENT_DRAFT_FIELD_KEYS
    }
    return {
        key: field_value
        for key, field_value in value.items()
        if key in edited or key == "merchant_edited_fields"
    }


def _merchant_edited_copy_failure_code(
    value: dict[str, Any],
    *,
    marketplace: str,
    merchant_product_fact_packet: dict[str, Any] | None = None,
) -> str:
    edited = {
        str(item or "").strip()
        for item in value.get("merchant_edited_fields") or []
        if str(item or "").strip() in {"title", "selling_points", "description"}
    }
    grounding_values: list[str] = []
    for key in ("title", "description"):
        text = str(value.get(key) or "").strip() if key in edited else ""
        if not text:
            continue
        grounding_values.append(text)
        if marketplace.upper() == "EBAY_US" and _contains_non_english_marketplace_text((text,)):
            return "listing_merchant_copy_marketplace_language"
        if _contains_unverified_compatibility(text):
            return "listing_merchant_copy_unverified_compatibility"
    if "selling_points" in edited:
        points = _selling_points_list(
            value.get("selling_points"),
            limit=LISTING_BUYER_COPY_MAX_POINTS + 1,
            item_limit=300,
        )
        if points and not LISTING_BUYER_COPY_MIN_POINTS <= len(points) <= LISTING_BUYER_COPY_MAX_POINTS:
            return "listing_merchant_copy_selling_points_count"
        if marketplace.upper() == "EBAY_US" and _contains_non_english_marketplace_text(tuple(points)):
            return "listing_merchant_copy_marketplace_language"
        if any(_contains_unverified_compatibility(point) for point in points):
            return "listing_merchant_copy_unverified_compatibility"
        grounding_values.extend(points)
    grounding_failure = _buyer_copy_grounding_failure(
        tuple(grounding_values),
        merchant_product_fact_packet,
    )
    if grounding_failure:
        return f"listing_merchant_copy_{grounding_failure}"
    return ""


def _parse_model_output(result: Any, *, marketplace: str, packet: dict[str, Any],
                        generation_mode: str = "preserve_merchant_edits") -> dict[str, Any]:
    text = str((result or {}).get("text") or "").strip() if isinstance(result, dict) else ""
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE).strip()
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError("listing_model_output_not_object")
    if generation_mode == "rewrite_buyer_copy":
        buyer_copy = {key: parsed.get(key) for key in LISTING_BUYER_COPY_FIELDS}
        raw_points = buyer_copy["selling_points"]
        if (not isinstance(buyer_copy["title"], str) or not isinstance(buyer_copy["description"], str)
            or not isinstance(raw_points, list) or any(not isinstance(point, str) for point in raw_points)):
            raise ValueError("listing_model_output_rewrite_copy_invalid")
        for value in [buyer_copy["title"], buyer_copy["description"], *raw_points]:
            if "\x00" in value:
                raise ValueError("listing_model_output_rewrite_copy_invalid")
            try:
                value.encode("utf-8")
            except UnicodeEncodeError:
                raise ValueError("listing_model_output_rewrite_copy_invalid") from None
        if (len(buyer_copy["title"]) > 80 or len(buyer_copy["description"]) > 1400
            or len("\n".join(raw_points)) > 1400 or any(len(point) > 300 for point in raw_points)):
            raise ValueError("listing_model_output_rewrite_copy_too_long")
        if contains_secret_like_data(buyer_copy) or _redact_secret_like(buyer_copy) != buyer_copy:
            raise ValueError("listing_model_output_rewrite_copy_sensitive_text")
    title = str(parsed.get("title") or "").strip()[:80]
    description = str(parsed.get("description") or "").strip()[:6000]
    if not title or not description:
        raise ValueError("listing_model_output_missing_buyer_copy")
    selling_points = _selling_points_list(
        parsed.get("selling_points"),
        limit=LISTING_BUYER_COPY_MAX_POINTS + 1,
        item_limit=300,
    )
    if not LISTING_BUYER_COPY_MIN_POINTS <= len(selling_points) <= LISTING_BUYER_COPY_MAX_POINTS:
        raise ValueError("listing_model_output_selling_points_count")
    if generation_mode == "rewrite_buyer_copy" and (
        len(description) > 1400 or len("\n".join(selling_points)) > 1400
    ):
        raise ValueError("listing_model_output_rewrite_copy_too_long")
    _validate_buyer_copy(
        title=title,
        description=description,
        selling_points=selling_points,
        marketplace=marketplace,
        failure_prefix="listing_model_output",
        merchant_product_fact_packet=packet,
    )
    if generation_mode == "rewrite_buyer_copy":
        return {"title": title, "selling_points": selling_points, "description": description}
    keywords = _string_list(parsed.get("keywords"), limit=20, item_limit=80)
    item_specifics = _safe_model_item_specifics(parsed.get("item_specifics"))
    supplemental_grounding_failure = _buyer_copy_grounding_failure(
        tuple(
            [*keywords]
            + [item for values in item_specifics.values() for item in values]
        ),
        packet,
    )
    if supplemental_grounding_failure:
        raise ValueError(f"listing_model_output_{supplemental_grounding_failure}")
    return {
        "title": title,
        "selling_points": selling_points,
        "description": description,
        "category_suggestion": str(parsed.get("category_suggestion") or "")[:160],
        "keywords": keywords,
        "item_specifics": item_specifics,
    }


def _merge_listing_fields(
    *,
    packet: dict[str, Any],
    current_draft_fields: dict[str, Any],
    model_output: dict[str, Any],
    ebay_handoff: dict[str, Any],
    marketplace: str,
) -> dict[str, Any]:
    facts = _effective_listing_facts(packet)
    simulation_only = packet.get("simulation_only") is True
    metadata = ebay_handoff.get("listing_metadata_probe") if isinstance(ebay_handoff.get("listing_metadata_probe"), dict) else {}
    merchant_edited_fields = {
        str(item or "").strip()
        for item in current_draft_fields.get("merchant_edited_fields") or []
        if str(item or "").strip() in _CURRENT_DRAFT_FIELD_KEYS
    }
    current_title = str(current_draft_fields.get("title") or "").strip() if "title" in merchant_edited_fields else ""
    product_name = str(packet.get("product_name") or "").strip()
    title = str(current_title or model_output.get("title") or product_name)[:80]
    current_description = (
        str(current_draft_fields.get("description") or "").strip() if "description" in merchant_edited_fields else ""
    )
    description = str(current_description or model_output.get("description") or "")[:6000]
    current_selling_points = (
        _selling_points_list(
            current_draft_fields.get("selling_points"),
            limit=LISTING_BUYER_COPY_MAX_POINTS + 1,
            item_limit=300,
        )
        if "selling_points" in merchant_edited_fields
        else []
    )
    selling_points = _selling_points_list(
        current_selling_points or model_output.get("selling_points"),
        limit=LISTING_BUYER_COPY_MAX_POINTS + 1,
        item_limit=300,
    )
    _validate_buyer_copy(
        title=title,
        description=description,
        selling_points=selling_points,
        marketplace=marketplace,
        failure_prefix="listing_final_copy",
        merchant_product_fact_packet=packet,
    )
    keywords = _string_list(
        current_draft_fields.get("keywords") if "keywords" in merchant_edited_fields else model_output.get("keywords"),
        limit=20,
        item_limit=80,
    )
    aspects = _safe_model_item_specifics(model_output.get("item_specifics"))
    if "item_specifics" in merchant_edited_fields:
        aspects.update(_safe_merchant_item_specifics(current_draft_fields.get("item_specifics")))
    for key, label in (("brand", "Brand"), ("mpn", "MPN"), ("material", "Material"), ("style", "Style")):
        if str(facts.get(key) or "").strip():
            aspects[label] = [str(facts[key])[:240]]
        elif label in {"Brand", "MPN", "Material"}:
            aspects.pop(label, None)
    category_id = str(metadata.get("category_id") or "")[:80]
    current_category = current_draft_fields.get("category") if "category" in merchant_edited_fields else ""
    category_suggestion = str(current_category or model_output.get("category_suggestion") or "")[:160]
    policies = {
        "fulfillmentPolicyId": _first_policy_id(metadata.get("fulfillment_policy_response"), "fulfillmentPolicies", "fulfillmentPolicyId"),
        "paymentPolicyId": _first_policy_id(metadata.get("payment_policy_response"), "paymentPolicies", "paymentPolicyId"),
        "returnPolicyId": _first_policy_id(metadata.get("return_policy_response"), "returnPolicies", "returnPolicyId"),
    }
    policies = {key: value for key, value in policies.items() if value}
    image_urls = re.findall(r"https?://[^\s,，；;]+", str(facts.get("image_urls") or ""))[:12]
    quantity = _positive_int(facts.get("quantity"))
    item_specifics = {key: values for key, values in aspects.items() if values}
    supplemental_grounding_failure = _buyer_copy_grounding_failure(
        tuple([*keywords] + [item for values in item_specifics.values() for item in values]),
        packet,
    )
    if supplemental_grounding_failure:
        raise ValueError(f"listing_final_copy_{supplemental_grounding_failure}")
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
            "reason": (
                "模拟演练 Listing 已生成；仅供内部流程测试，不可保存到 eBay 或正式发布。"
                if simulation_only
                else "AI Listing 草稿已生成；商品事实、eBay 字段和确认中心仍需复核。"
            ),
        },
        "draft_source": "project_scoped_live_model",
        "ready_for_listing_draft": True,
        "simulation_only": simulation_only,
        "safe_local_only": simulation_only,
        "fact_scope": "simulation_rehearsal" if simulation_only else "merchant_product",
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


def _safe_model_item_specifics(value: Any) -> dict[str, list[str]]:
    safe: dict[str, list[str]] = {}
    for key, values in _safe_item_specifics(value).items():
        normalized_key = re.sub(r"[^a-z0-9]+", " ", key.casefold()).strip()
        if normalized_key not in _MODEL_SUGGESTED_ITEM_SPECIFIC_KEYS:
            continue
        if _COMPATIBILITY_ASPECT_KEY_PATTERN.search(key) or any(
            _contains_unverified_compatibility(item) or _UNVERIFIED_DEVICE_PRODUCT_TYPE_PATTERN.search(str(item or ""))
            for item in values
        ):
            continue
        safe[key] = values
    return safe


def _safe_merchant_item_specifics(value: Any) -> dict[str, list[str]]:
    return {
        key: values
        for key, values in _safe_item_specifics(value).items()
        if not _COMPATIBILITY_ASPECT_KEY_PATTERN.search(key)
        and not any(
            _contains_unverified_compatibility(item) or _UNVERIFIED_DEVICE_PRODUCT_TYPE_PATTERN.search(str(item or ""))
            for item in values
        )
    }


def _string_list(value: Any, *, limit: int, item_limit: int) -> list[str]:
    items = value if isinstance(value, list) else re.split(r"\r?\n|[,，;；]+", str(value or ""))
    return [str(item).strip()[:item_limit] for item in items if str(item).strip()][:limit]


def _selling_points_list(value: Any, *, limit: int, item_limit: int) -> list[str]:
    items = value if isinstance(value, list) else str(value or "").splitlines()
    return [str(item).strip()[:item_limit] for item in items if str(item).strip()][:limit]


def _contains_unverified_compatibility(value: Any) -> bool:
    text = str(value or "")
    if any(pattern.search(text) is not None for pattern in _UNVERIFIED_COMPATIBILITY_PATTERNS):
        return True
    return _DEVICE_TARGET_PATTERN.search(text) is not None and _COMPATIBILITY_INTENT_PATTERN.search(text) is not None


def _contains_non_english_marketplace_text(values: tuple[str, ...]) -> bool:
    combined = " ".join(str(value or "") for value in values)
    if _NON_LATIN_MARKETPLACE_SCRIPT_PATTERN.search(combined):
        return True
    tokens = re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ]+", combined.casefold())
    if not tokens:
        return True
    token_set = set(tokens)
    return any(len(token_set.intersection(markers)) >= threshold for markers, threshold in _HIGH_CONFIDENCE_NON_ENGLISH_MARKERS)


def _validate_buyer_copy(
    *,
    title: str,
    description: str,
    selling_points: list[str],
    marketplace: str,
    failure_prefix: str,
    merchant_product_fact_packet: dict[str, Any] | None = None,
) -> None:
    values = (str(title or "").strip(), str(description or "").strip(), *selling_points)
    if not values[0] or not values[1]:
        raise ValueError(f"{failure_prefix}_missing_buyer_copy")
    if not LISTING_BUYER_COPY_MIN_POINTS <= len(selling_points) <= LISTING_BUYER_COPY_MAX_POINTS:
        raise ValueError(f"{failure_prefix}_selling_points_count")
    if marketplace.upper() == "EBAY_US" and _contains_non_english_marketplace_text(values):
        raise ValueError(f"{failure_prefix}_marketplace_language")
    if any(_contains_unverified_compatibility(value) for value in values):
        raise ValueError(f"{failure_prefix}_unverified_compatibility")
    grounding_failure = _buyer_copy_grounding_failure(values, merchant_product_fact_packet)
    if grounding_failure:
        raise ValueError(f"{failure_prefix}_{grounding_failure}")


def _buyer_copy_grounding_failure(
    values: tuple[str, ...],
    merchant_product_fact_packet: dict[str, Any] | None,
) -> str:
    if not isinstance(merchant_product_fact_packet, dict):
        return ""
    facts = _effective_listing_facts(merchant_product_fact_packet)
    material_fact_text = _canonical_material_spelling(str(facts.get("material") or "").casefold())
    buyer_text = " ".join(values).casefold()
    buyer_material_text = _canonical_material_spelling(buyer_text)
    for material in _HIGH_RISK_MATERIAL_TERMS:
        canonical_material = _canonical_material_spelling(material)
        if re.search(rf"(?<![a-z]){re.escape(canonical_material)}(?![a-z])", buyer_material_text) and not re.search(
            rf"(?<![a-z]){re.escape(canonical_material)}(?![a-z])",
            material_fact_text,
        ):
            return "ungrounded_material"
    for pattern in _HIGH_RISK_PERFORMANCE_PATTERNS:
        if pattern.search(buyer_text):
            return "ungrounded_performance_claim"
    if _WARRANTY_CLAIM_PATTERN.search(buyer_text):
        return "ungrounded_warranty"
    if _CERTIFICATION_CLAIM_PATTERN.search(buyer_text):
        return "ungrounded_certification"
    if _numeric_spec_grounding_failure(buyer_text, facts):
        return "ungrounded_numeric_spec"
    return ""


def _canonical_material_spelling(value: str) -> str:
    return re.sub(r"(?<![a-z])aluminium(?![a-z])", "aluminum", str(value or ""), flags=re.IGNORECASE)


def _numeric_spec_grounding_failure(buyer_text: str, facts: dict[str, Any]) -> bool:
    if _UNSUPPORTED_NUMERIC_SPEC_PATTERN.search(buyer_text):
        return True

    product_dimensions = _fact_numbers(facts.get("product_dimensions_cm"))
    package_dimensions = _fact_numbers(
        " ".join(
            str(facts.get(key) or "")
            for key in ("package_length_cm", "package_width_cm", "package_height_cm")
        )
    )
    dimension_spans: list[tuple[int, int]] = []
    for match in _DIMENSION_SEQUENCE_PATTERN.finditer(buyer_text):
        dimension_spans.append(match.span())
        factor = _dimension_to_cm_factor(match.group("unit"))
        claimed = [float(item) * factor for item in re.findall(r"\d+(?:\.\d+)?", match.group("values"))]
        allowed = package_dimensions if _is_package_context(buyer_text, match.start()) else product_dimensions
        if not allowed or any(not _approximately_in(value, allowed) for value in claimed):
            return True
    for match in _DIMENSION_VALUE_PATTERN.finditer(buyer_text):
        if any(start <= match.start() and match.end() <= end for start, end in dimension_spans):
            continue
        factor = _dimension_to_cm_factor(match.group("unit"))
        claimed = float(match.group("value")) * factor
        allowed = package_dimensions if _is_package_context(buyer_text, match.start()) else product_dimensions
        if not allowed or not _approximately_in(claimed, allowed):
            return True

    net_weights = _fact_numbers(facts.get("net_weight_g"))
    package_weights = _fact_numbers(facts.get("package_weight_g"))
    for match in _WEIGHT_VALUE_PATTERN.finditer(buyer_text):
        claimed = float(match.group("value")) * _weight_to_grams_factor(match.group("unit"))
        context = buyer_text[max(0, match.start() - 32) : match.start()]
        if re.search(r"\b(?:package|packaged|shipping|shipment|carton)\b", context, flags=re.IGNORECASE):
            allowed = package_weights
        elif re.search(r"\b(?:net|item|product)\s+weight\b", context, flags=re.IGNORECASE):
            allowed = net_weights
        else:
            allowed = net_weights
        if not allowed or not _approximately_in(claimed, allowed):
            return True
    return False


def _fact_numbers(value: Any) -> list[float]:
    return [float(item) for item in re.findall(r"\d+(?:\.\d+)?", str(value or ""))]


def _dimension_to_cm_factor(unit: str) -> float:
    normalized = str(unit or "").casefold()
    if normalized == "mm":
        return 0.1
    if normalized == "m":
        return 100.0
    if normalized in {'"', "in", "inch", "inches"}:
        return 2.54
    if normalized in {"ft", "feet", "foot"}:
        return 30.48
    return 1.0


def _weight_to_grams_factor(unit: str) -> float:
    normalized = str(unit or "").casefold()
    if normalized == "mg":
        return 0.001
    if normalized in {"kg", "kilogram", "kilograms"}:
        return 1000.0
    if normalized in {"oz", "ounce", "ounces"}:
        return 28.349523125
    if normalized in {"lb", "lbs", "pound", "pounds"}:
        return 453.59237
    return 1.0


def _approximately_in(value: float, allowed: list[float]) -> bool:
    return any(abs(value - candidate) <= max(0.05, abs(candidate) * 0.01) for candidate in allowed)


def _is_package_context(text: str, position: int) -> bool:
    context = text[max(0, position - 32) : position]
    return re.search(r"\b(?:package|packaged|shipping|shipment|carton)\b", context, flags=re.IGNORECASE) is not None


def _record_listing_model_usage(
    *,
    repository: SaaSRepository,
    company_id: str,
    user_id: str,
    task_id: str,
    model_resolution: dict[str, Any] | None,
    model_meta: dict[str, Any],
    model_client: Any,
    usage: dict[str, int],
    outcome: str,
    failure_code: str = "",
) -> None:
    if int(usage.get("request_count") or 0) <= 0:
        return
    usage_owner = _usage_owner(model_resolution)
    cost = model_cost_measurement(usage_owner=usage_owner, usage=usage)
    try:
        repository.record_model_usage(
            company_id=company_id,
            user_id=user_id,
            task_id=task_id,
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
            idempotency_key=f"{task_id}:listing-draft-model-usage:v1",
            details={
                "provider_reported_tokens": bool(usage.get("total_tokens")),
                "outcome": str(outcome or "unknown")[:40],
                "failure_code": str(failure_code or "")[:120],
                "prompts_stored": False,
                "responses_stored": False,
            },
        )
    except Exception as exc:
        raise RuntimeError("listing_model_usage_ledger_failed") from exc


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
    raw = str(exc or "").strip().lower()
    if raw == "listing_model_usage_ledger_failed":
        return raw
    if re.fullmatch(r"listing_(?:model_output|final_copy)_[a-z0-9_]+", raw):
        return raw[:120]
    text = f"{exc.__class__.__name__}:{raw}".lower()
    if "json" in text:
        return "listing_model_output_invalid_json"
    if "timeout" in text:
        return "listing_model_timeout"
    return "listing_model_generation_failed"
