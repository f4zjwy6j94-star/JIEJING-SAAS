"""Backend-only eBay write adapter for the formal SaaS boundary.

The live actions supported here are intentionally narrow: a confirmed
unpublished draft save and a confirmed single ``publish_listing`` through the
eBay Inventory API. Other high-risk actions remain contract-only until they
get their own adapter and tests.
"""

from __future__ import annotations

import html
import hashlib
import json
import re
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from .config import SaaSSettings
from .ebay_http_client import EbayReadOnlyHttpClient, HttpTransport, _urlopen_transport
from .ebay_oauth import UNPUBLISHED_DRAFT_SCOPES


WRITE_ACTIONS = [
    {
        "action_type": "save_ebay_listing_draft",
        "label": "Save unpublished eBay draft",
        "risk_level": "high",
        "adapter_route_candidates": ["Inventory API inventory item + unpublished offer; never publishOffer"],
        "requires_preflight_fields": [
            "listing.sku",
            "listing.title",
            "listing.description_html",
            "listing.category_id",
            "listing.condition",
            "listing.price",
            "listing.quantity",
            "listing.item_specifics",
            "listing.merchant_location_key",
            "business_policies.fulfillment_policy_id",
            "business_policies.payment_policy_id",
            "business_policies.return_policy_id",
            "asset_manifest.assets",
            "confirmation_record",
            "idempotency_key",
        ],
        "requires_confirmation": True,
        "sandbox_first": True,
        "creates_public_listing": False,
        "calls_publish_offer": False,
    },
    {
        "action_type": "publish_listing",
        "label": "Publish new eBay listing",
        "risk_level": "critical",
        "adapter_route_candidates": ["Trading API AddFixedPriceItem", "Inventory/Offer publish if account permission allows"],
        "requires_preflight_fields": [
            "listing.sku",
            "listing.title",
            "listing.description_html",
            "listing.category_id",
            "listing.condition",
            "listing.price",
            "listing.quantity",
            "listing.item_specifics",
            "listing.merchant_location_key",
            "business_policies.fulfillment_policy_id",
            "business_policies.payment_policy_id",
            "business_policies.return_policy_id",
            "supplier_facts.package_weight_g",
            "supplier_facts.package_dimensions_cm",
            "asset_manifest.assets",
            "finance_review.net_profit_money",
            "idempotency_key",
        ],
        "requires_confirmation": True,
        "sandbox_first": True,
    },
    {
        "action_type": "revise_listing",
        "label": "Revise existing listing",
        "risk_level": "critical",
        "adapter_route_candidates": ["Trading API ReviseFixedPriceItem", "Inventory/Offer revise if account permission allows"],
        "requires_preflight_fields": ["listing_id", "change_set", "confirmation_record", "idempotency_key"],
        "requires_confirmation": True,
        "sandbox_first": True,
    },
    {
        "action_type": "change_price",
        "label": "Change listing price",
        "risk_level": "critical",
        "adapter_route_candidates": ["Trading API ReviseInventoryStatus", "Trading API ReviseFixedPriceItem"],
        "requires_preflight_fields": ["listing_id", "new_price", "finance_review", "confirmation_record", "idempotency_key"],
        "requires_confirmation": True,
        "sandbox_first": True,
    },
    {
        "action_type": "change_inventory",
        "label": "Change listing inventory",
        "risk_level": "critical",
        "adapter_route_candidates": ["Trading API ReviseInventoryStatus", "Inventory API if account permission allows"],
        "requires_preflight_fields": ["listing_id", "new_quantity", "reason", "confirmation_record", "idempotency_key"],
        "requires_confirmation": True,
        "sandbox_first": True,
    },
    {
        "action_type": "ad_budget",
        "label": "Create or change ad budget",
        "risk_level": "critical",
        "adapter_route_candidates": ["Marketing API when enabled for the account"],
        "requires_preflight_fields": ["campaign_or_listing_id", "budget_amount", "budget_period", "reason", "confirmation_record", "idempotency_key"],
        "requires_confirmation": True,
        "sandbox_first": True,
    },
    {
        "action_type": "refund",
        "label": "Refund or partial refund",
        "risk_level": "critical",
        "adapter_route_candidates": ["Fulfillment/Order refund route when enabled and policy-checked"],
        "requires_preflight_fields": ["order_id", "refund_amount", "reason", "buyer_case_status", "confirmation_record", "idempotency_key"],
        "requires_confirmation": True,
        "sandbox_first": True,
    },
    {
        "action_type": "procurement_payment",
        "label": "Place or pay supplier order",
        "risk_level": "critical",
        "adapter_route_candidates": ["1688 or authorized sourcing provider adapter"],
        "requires_preflight_fields": ["supplier_id_or_link", "purchase_amount", "ship_to_address_mode", "confirmation_record", "idempotency_key"],
        "requires_confirmation": True,
        "sandbox_first": True,
    },
    {
        "action_type": "policy_edit",
        "label": "Edit store policy",
        "risk_level": "critical",
        "adapter_route_candidates": ["Account API policy route when permission allows"],
        "requires_preflight_fields": ["policy_type", "policy_id", "change_set", "confirmation_record", "idempotency_key"],
        "requires_confirmation": True,
        "sandbox_first": True,
    },
    {
        "action_type": "tracking_write",
        "label": "Write tracking or shipment update",
        "risk_level": "high",
        "adapter_route_candidates": ["Trading/Fulfillment shipment tracking route when enabled"],
        "requires_preflight_fields": ["order_id", "carrier", "tracking_number", "confirmation_or_saved_rule", "idempotency_key"],
        "requires_confirmation": True,
        "sandbox_first": True,
    },
]


def build_ebay_write_adapter_contract(settings: SaaSSettings) -> dict[str, Any]:
    requested_enabled = bool(settings.requested_real_platform_writes)
    live_enabled = bool(settings.effective_real_platform_writes_enabled)
    draft_live_enabled = bool(settings.effective_ebay_draft_save_enabled)
    controlled_publish_enabled = bool(settings.effective_ebay_controlled_publish_enabled)
    blockers = []
    if not requested_enabled:
        blockers.append("JIEJING_ENABLE_REAL_PLATFORM_WRITES")
    if not settings.ebay_write_live_enabled:
        blockers.append("JIEJING_EBAY_WRITE_LIVE")
    if not settings.is_production_like:
        blockers.append("environment_not_production_like")
    if not settings.ebay_token_refresh_live_enabled:
        blockers.append("ebay_token_refresh_not_ready")
    if not settings.ebay_read_only_live_enabled:
        blockers.append("ebay_read_only_not_ready")
    return {
        "adapter": "ebay_write_adapter",
        "version": "2026-07-14-draft-save-v2",
        "enabled": live_enabled,
        "real_platform_writes_enabled": live_enabled,
        "draft_save_live_enabled": draft_live_enabled,
        "controlled_existing_draft_publish_enabled": controlled_publish_enabled,
        "requested_enabled": requested_enabled,
        "writes_supported": live_enabled or draft_live_enabled or controlled_publish_enabled,
        "contract_only": not (live_enabled or draft_live_enabled or controlled_publish_enabled),
        "blocked_by": blockers,
        "actions": WRITE_ACTIONS,
        "live_actions_supported": (
            ["save_ebay_listing_draft", "publish_listing"]
            if live_enabled
            else ["save_ebay_listing_draft", "publish_listing"]
            if controlled_publish_enabled
            else ["save_ebay_listing_draft"]
            if draft_live_enabled
            else []
        ),
        "live_actions_not_supported": [
            "revise_listing",
            "change_price",
            "change_inventory",
            "ad_budget",
            "refund",
            "procurement_payment",
            "policy_edit",
            "tracking_write",
        ],
        "required_chain": [
            "approved_confirmation",
            "execution_preflight_passed",
            "vault_resolved_token_backend_only",
            "queued_execution_job",
            "idempotency_key",
            "platform_http_adapter",
            "audit_log_before_and_after",
            "merchant_visible_result",
        ],
        "guardrails": {
            "frontend_gets_token": False,
            "runtime_gets_token": False,
            "agent_can_call_write_adapter": False,
            "confirmation_required": True,
            "preflight_required": True,
            "audit_required": True,
            "sandbox_first": True,
            "single_publish_only": True,
            "real_write_enabled": live_enabled,
            "controlled_existing_draft_publish_enabled": controlled_publish_enabled,
        },
        "next_engineering_steps": [
            "Reauthorize the seller with the eBay sell.inventory write scope.",
            "Run one confirmation-gated unpublished draft save and verify that no public listing exists.",
            "Run one low-volume publish_listing test from the confirmation center.",
            "Add idempotency keys so retries do not duplicate listings, refunds, payments, or policy edits.",
            "Persist platform request/response summaries with sensitive fields redacted.",
        ],
    }


def build_publish_readiness(
    payload: dict[str, Any],
    *,
    preflight: dict[str, Any] | None = None,
    latest_execution_results: list[dict[str, Any]] | None = None,
    recent_confirmations: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a merchant-visible readiness checklist without calling eBay."""

    payload = payload if isinstance(payload, dict) else {}
    preflight = preflight if isinstance(preflight, dict) else {}
    listing = payload.get("listing") if isinstance(payload.get("listing"), dict) else {}
    policies = payload.get("business_policies") if isinstance(payload.get("business_policies"), dict) else {}
    supplier = payload.get("supplier_facts") if isinstance(payload.get("supplier_facts"), dict) else {}
    assets = payload.get("asset_manifest") if isinstance(payload.get("asset_manifest"), dict) else {}
    preflight_issues = [item for item in preflight.get("issues", []) if isinstance(item, dict)]
    missing = [str(item) for item in preflight.get("missing_fields", []) if str(item).strip()]
    checks: list[dict[str, Any]] = []

    account_health = _account_health_readiness(payload=payload, preflight_issues=preflight_issues, missing_fields=missing)
    _add_check(
        checks,
        key="account_health_gate",
        label="账号健康门禁",
        status=account_health["status"],
        summary=account_health["summary"],
        blocking=account_health["blocking"],
        details=account_health["details"],
    )

    _add_check(
        checks,
        key="field_completeness",
        label="发布字段完整度",
        status="blocked" if missing else "passed",
        summary="缺少真实发布字段，不能交给 eBay。" if missing else "必填字段已齐，可以进入平台适配器。",
        blocking=bool(missing),
        details={"missing_fields": missing, "required_fields": preflight.get("required_fields") or []},
    )

    category_blockers = [item for item in preflight_issues if item.get("key") == "listing.category_id"]
    _add_check(
        checks,
        key="category_match",
        label="eBay 类目校验",
        status="blocked" if category_blockers else ("passed" if listing.get("category_id") else "needs_attention"),
        summary=(
            str(category_blockers[0].get("message") or "类目和商品不匹配。")
            if category_blockers
            else f"类目 {listing.get('category_id')} / {listing.get('category_leaf') or 'leaf pending'} 已进入预检。"
            if listing.get("category_id")
            else "还没有可发布的 eBay 类目。"
        ),
        blocking=bool(category_blockers or not listing.get("category_id")),
        details={"category_id": listing.get("category_id"), "category_leaf": listing.get("category_leaf") or listing.get("leaf_category")},
    )

    policy_missing = [
        field
        for field in ("fulfillment_policy_id", "payment_policy_id", "return_policy_id")
        if not str(policies.get(field) or "").strip()
    ]
    _add_check(
        checks,
        key="business_policies",
        label="店铺政策",
        status="blocked" if policy_missing else "passed",
        summary="缺少发货/付款/退货政策，eBay 发布会失败。" if policy_missing else "已带入发货、付款、退货政策。",
        blocking=bool(policy_missing),
        details={"missing_fields": [f"business_policies.{field}" for field in policy_missing]},
    )

    location_key = str(listing.get("merchant_location_key") or "").strip()
    _add_check(
        checks,
        key="inventory_location",
        label="库存位置",
        status="passed" if location_key else "blocked",
        summary=f"库存位置 {location_key} 已准备。" if location_key else "缺少 merchant_location_key，需要先建 eBay inventory location。",
        blocking=not bool(location_key),
        details={"merchant_location_key": location_key},
    )

    dimensions = supplier.get("package_dimensions_cm") if isinstance(supplier.get("package_dimensions_cm"), dict) else {}
    package_missing = []
    if _float(supplier.get("package_weight_g")) is None:
        package_missing.append("supplier_facts.package_weight_g")
    for field in ("length", "width", "height"):
        if not isinstance(dimensions, dict) or _float(dimensions.get(field)) is None:
            package_missing.append(f"supplier_facts.package_dimensions_cm.{field}")
    if not str(supplier.get("material") or "").strip():
        package_missing.append("supplier_facts.material")
    if not str(supplier.get("item_location") or "").strip():
        package_missing.append("supplier_facts.item_location")
    _add_check(
        checks,
        key="package_facts",
        label="规格和发货地",
        status="blocked" if package_missing else "passed",
        summary="缺少重量、尺寸、材质或发货地，不能真实发布。" if package_missing else "重量、尺寸、材质和发货地已齐。",
        blocking=bool(package_missing),
        details={"missing_fields": package_missing},
    )

    urls = _image_urls(assets.get("assets"))
    raw_asset_count = len(assets.get("assets")) if isinstance(assets.get("assets"), list) else 0
    invalid_count = max(0, raw_asset_count - len(urls))
    _add_check(
        checks,
        key="asset_reachability",
        label="图片资产",
        status="blocked" if not urls else ("needs_attention" if invalid_count else "passed"),
        summary=(
            "缺少可上传给 eBay 的图片 URL。"
            if not urls
            else f"{len(urls)} 张图片可用，{invalid_count} 个资产不是 http/https URL。"
        ),
        blocking=not bool(urls),
        details={"image_url_count": len(urls), "invalid_asset_count": invalid_count},
    )

    duplicate_findings = _duplicate_product_findings(
        payload=payload,
        latest_execution_results=latest_execution_results or [],
        recent_confirmations=recent_confirmations or [],
    )
    _add_check(
        checks,
        key="new_product_duplicate_guard",
        label="新商品查重",
        status="blocked" if duplicate_findings["blocking_matches"] else ("needs_attention" if duplicate_findings["review_matches"] else "passed"),
        summary=(
            "发现和历史发布/确认记录重复的 SKU、标题或图片，必须换全新商品和全新素材后再测。"
            if duplicate_findings["blocking_matches"]
            else "发现相似标题或素材痕迹，建议人工确认这不是旧品旧图重复测试。"
            if duplicate_findings["review_matches"]
            else "当前 SKU、标题和图片没有命中最近发布/确认记录。"
        ),
        blocking=bool(duplicate_findings["blocking_matches"]),
        details=duplicate_findings,
    )

    item_specifics = listing.get("item_specifics") if isinstance(listing.get("item_specifics"), dict) else {}
    specific_missing = [
        field
        for field in ("Brand", "Type")
        if not str(item_specifics.get(field) or item_specifics.get(field.lower()) or "").strip()
    ]
    _add_check(
        checks,
        key="item_specifics_quality",
        label="Item specifics",
        status="blocked" if not item_specifics or specific_missing else "passed",
        summary=(
            "缺少 eBay 类目字段，Inventory API 发布 active listing 时很容易失败。"
            if not item_specifics or specific_missing
            else f"已提供 {len(item_specifics)} 个 item specifics。"
        ),
        blocking=bool(not item_specifics or specific_missing),
        details={"missing_fields": [f"listing.item_specifics.{field}" for field in specific_missing], "specific_count": len(item_specifics)},
    )

    text_blob = " ".join(
        [
            str(listing.get("title") or ""),
            str(listing.get("description_html") or ""),
            " ".join(str(value) for value in item_specifics.values()),
        ]
    )
    ip_findings = _ip_and_prohibited_findings(text_blob=text_blob, brand=str(item_specifics.get("Brand") or item_specifics.get("brand") or ""))
    _add_check(
        checks,
        key="ip_vero_and_claims",
        label="IP / VeRO / 禁售词",
        status="blocked" if ip_findings.get("blocking_terms") else ("needs_attention" if ip_findings.get("review_terms") else "passed"),
        summary=(
            "发现高风险品牌词、侵权词或禁售词，发布前必须改标题/描述/图片来源。"
            if ip_findings.get("blocking_terms")
            else "未发现内置高风险品牌词或禁售词；仍需保留图片和文字来源。"
            if not ip_findings.get("review_terms")
            else "发现需要人工确认的兼容性/品牌表述。"
        ),
        blocking=bool(ip_findings.get("blocking_terms")),
        details=ip_findings,
    )

    regulatory = payload.get("regulatory") if isinstance(payload.get("regulatory"), dict) else {}
    gpsr_required = _gpsr_required(payload, listing=listing)
    gpsr_missing = [
        field
        for field in ("responsible_person", "manufacturer", "product_safety_contact")
        if not str(regulatory.get(field) or "").strip()
    ]
    _add_check(
        checks,
        key="gpsr_regulatory_fields",
        label="GPSR / 法规字段",
        status="blocked" if gpsr_required and gpsr_missing else ("passed" if gpsr_required else "not_applicable"),
        summary=(
            "目标市场可能触发 EU/北爱 GPSR 字段，缺少责任人、制造商或安全联系方式。"
            if gpsr_required and gpsr_missing
            else "目标市场未标记为 EU/北爱；GPSR 字段暂不阻塞。"
            if not gpsr_required
            else "GPSR 关键字段已进入发布资料。"
        ),
        blocking=bool(gpsr_required and gpsr_missing),
        details={"gpsr_required": gpsr_required, "missing_fields": [f"regulatory.{field}" for field in gpsr_missing]},
    )

    price = listing.get("price") if isinstance(listing.get("price"), dict) else {"value": listing.get("price"), "currency": "USD"}
    unit_price = _float(price.get("value"))
    quantity = _int(listing.get("quantity"))
    exposure = round(unit_price * quantity, 2) if unit_price is not None and quantity is not None else None
    prior_limit_error = _latest_platform_error(latest_execution_results or [], sku=str(listing.get("sku") or ""))
    price_status = "needs_attention"
    price_summary = "价格或库存数量不完整，不能计算额度占用。"
    if unit_price is not None and quantity is not None:
        price_status = "passed"
        price_summary = f"本次发布预计占用 {price.get('currency') or 'USD'} {exposure:.2f} 的刊登额度。"
    if prior_limit_error:
        price_status = "blocked"
        price_summary = "最近一次发布触发 eBay 卖家刊登额度限制；需要降价、降数量或提升额度后再发。"
    _add_check(
        checks,
        key="price_quantity_exposure",
        label="价格 x 库存额度",
        status=price_status,
        summary=price_summary,
        blocking=bool(prior_limit_error or unit_price is None or quantity is None),
        details={
            "unit_price": unit_price,
            "currency": price.get("currency") or "USD",
            "quantity": quantity,
            "estimated_listing_amount": exposure,
            "last_platform_error": prior_limit_error or {},
        },
    )

    finance = payload.get("finance_review") if isinstance(payload.get("finance_review"), dict) else {}
    ebay_fee = _money_float(finance.get("ebay_fee_money"))
    if ebay_fee is None:
        ebay_fee = _float(finance.get("ebay_fee"))
    ad_budget = _money_float(finance.get("ad_budget_money"))
    if ad_budget is None:
        ad_budget = _float(finance.get("ad_budget"))
    return_risk_reserve = _money_float(finance.get("return_risk_reserve_money"))
    if return_risk_reserve is None:
        return_risk_reserve = _float(finance.get("return_risk_reserve"))
    exchange_rate = _float(finance.get("exchange_rate"))
    net_profit = _money_float(finance.get("net_profit_money"))
    if net_profit is None:
        net_profit = _float(finance.get("net_profit"))
    procurement_cost = _money_float(finance.get("procurement_cost_money"))
    if procurement_cost is None:
        procurement_cost = _float(finance.get("procurement_cost"))
    shipping_cost = _money_float(finance.get("shipping_cost_money"))
    if shipping_cost is None:
        shipping_cost = _float(finance.get("shipping_cost"))
    margin = _float(finance.get("gross_margin_percent"))
    calculated_profit = _calculated_contribution_profit(
        unit_price=unit_price,
        procurement_cost=procurement_cost,
        shipping_cost=shipping_cost,
        ebay_fee=ebay_fee,
        ad_budget=ad_budget,
        return_risk_reserve=return_risk_reserve,
    )
    profit_blocking = net_profit is None and procurement_cost is None
    effective_profit = net_profit if net_profit is not None else calculated_profit
    if effective_profit is not None and effective_profit < 0:
        profit_blocking = True
    missing_profit_inputs = [
        key
        for key, value in {
            "售价": unit_price,
            "采购成本": procurement_cost,
            "eBay fee": ebay_fee,
            "广告预算": ad_budget,
            "物流成本": shipping_cost,
            "退货风险预留": return_risk_reserve,
            "汇率": exchange_rate,
        }.items()
        if value is None
    ]
    _add_check(
        checks,
        key="profit_and_fee_sanity",
        label="费用与贡献毛利",
        status="blocked" if profit_blocking else ("needs_attention" if missing_profit_inputs else "passed"),
        summary=(
            "缺少采购成本/净利润，不能把 AI CEO 变成只会发品的工具。"
            if net_profit is None and procurement_cost is None
            else "净利润为负，发布前必须改价、降成本或暂停。"
            if effective_profit is not None and effective_profit < 0
            else "利润大脑已带入售价、采购、eBay fee、广告、物流、退货风险和汇率口径。"
            if not missing_profit_inputs
            else "利润大脑已启动，但还缺 " + "、".join(missing_profit_inputs) + "，只能进入人工复核。"
        ),
        blocking=profit_blocking,
        details={
            "net_profit": net_profit,
            "calculated_contribution_profit": calculated_profit,
            "effective_profit": effective_profit,
            "procurement_cost": procurement_cost,
            "ebay_fee": ebay_fee,
            "ad_budget": ad_budget,
            "shipping_cost": shipping_cost,
            "return_risk_reserve": return_risk_reserve,
            "exchange_rate": exchange_rate,
            "gross_margin_percent": margin,
            "missing_profit_inputs": missing_profit_inputs,
        },
    )

    _add_check(
        checks,
        key="inventory_api_lifecycle",
        label="发布后生命周期",
        status="passed" if listing.get("sku") else "blocked",
        summary=(
            "Inventory API 发布后的改价、库存、下架、补图和描述修改必须继续由捷境 API 生命周期管理，并进入确认中心。"
            if listing.get("sku")
            else "缺少 SKU，无法建立发布后生命周期和幂等恢复。"
        ),
        blocking=not bool(listing.get("sku")),
        details={
            "sku": listing.get("sku"),
            "confirmation_required_for": ["price", "inventory", "end_listing", "revise_description", "replace_images"],
        },
    )

    blocking_checks = [item for item in checks if item.get("blocking")]
    post_publish_cockpit_plan = _post_publish_cockpit_plan(listing=listing, finance=finance)
    failure_knowledge = _failure_knowledge_base(latest_execution_results or [], sku=str(listing.get("sku") or ""))
    traffic_light_report = _publish_health_traffic_light_report(checks, preflight=preflight)
    return {
        "status": "blocked_missing_facts" if blocking_checks else "ready_for_execution",
        "action_type": "publish_listing",
        "checks": checks,
        "traffic_light_report": traffic_light_report,
        "backend_evidence_packet": _publish_readiness_evidence_packet(checks, preflight=preflight),
        "blocking_check_count": len(blocking_checks),
        "ready_for_platform_adapter": not blocking_checks and preflight.get("status") == "ready_for_platform_adapter",
        "retry_rule": "Do not retry after timeout/502 until publish recovery confirms no published offer exists.",
        "post_publish_cockpit_plan": post_publish_cockpit_plan,
        "failure_knowledge_base": failure_knowledge,
        "merchant_rule_memory_policy": {
            "ordinary_chat_long_term_memory": False,
            "explicit_rule_phrase_required": True,
            "explicit_rule_phrases": ["记住这个规则", "以后都按这个做"],
            "workflow_confirmation_execution_report_memory": "permanent_audit_and_operating_memory",
        },
        "trusted_source_policy": {
            "must_label_sources": True,
            "source_types": ["official_ebay_packet", "orders", "finance_records", "public_search", "model_reasoning", "merchant_input"],
        },
        "secret_exposed": False,
    }


class _DraftPreparationState:
    """Private request-local state; deliberately not a dataclass/serializer."""

    __slots__ = (
        "company_id",
        "store_id",
        "marketplace_id",
        "sku",
        "access_token",
        "token_source",
        "inventory_body_json",
        "offer_body_json",
        "expected_offer_id",
        "expected_offer_fingerprint",
        "inspection_steps",
        "payload_sha256",
        "confirmation_id",
        "task_id",
        "idempotency_key",
        "prepared_at_epoch",
        "credential_binding_items",
        "preparation_sha256",
    )

    def __init__(self, **values: Any) -> None:
        for name in self.__slots__:
            object.__setattr__(self, name, values[name])

    def __repr__(self) -> str:
        return "_DraftPreparationState(<redacted>)"

    def __reduce__(self) -> Any:
        raise TypeError("prepared_ebay_draft_state_not_serializable")

    def __reduce_ex__(self, protocol: int) -> Any:
        del protocol
        raise TypeError("prepared_ebay_draft_state_not_serializable")


class _DraftPreparationHandle:
    """Opaque process-local handle; prepared token and bodies stay in adapter memory."""

    __slots__ = ("_handle", "_safe_binding")

    def __init__(self, *, handle: str, safe_binding: dict[str, str]) -> None:
        self._handle = handle
        self._safe_binding = dict(safe_binding)

    def claim_binding(self) -> dict[str, str]:
        return dict(self._safe_binding)

    def __repr__(self) -> str:
        return "_DraftPreparationHandle(<redacted>)"

    def __reduce__(self) -> Any:
        raise TypeError("prepared_ebay_draft_save_not_serializable")

    def __reduce_ex__(self, protocol: int) -> Any:
        del protocol
        raise TypeError("prepared_ebay_draft_save_not_serializable")


class _InventoryLocationPreparationState:
    """Private one-request state for a confirmed inventory-location write."""

    __slots__ = (
        "company_id",
        "store_id",
        "confirmation_id",
        "task_id",
        "marketplace_id",
        "merchant_location_key",
        "access_token",
        "location_payload_json",
        "payload_sha256",
        "prepared_at_epoch",
        "credential_binding_items",
    )

    def __init__(self, **values: Any) -> None:
        for name in self.__slots__:
            object.__setattr__(self, name, values[name])

    def __repr__(self) -> str:
        return "_InventoryLocationPreparationState(<redacted>)"

    def __reduce__(self) -> Any:
        raise TypeError("prepared_ebay_inventory_location_not_serializable")


class _InventoryLocationPreparationHandle:
    __slots__ = ("_handle", "_safe_binding")

    def __init__(self, *, handle: str, safe_binding: dict[str, str]) -> None:
        self._handle = handle
        self._safe_binding = dict(safe_binding)

    def claim_binding(self) -> dict[str, str]:
        return dict(self._safe_binding)

    def __repr__(self) -> str:
        return "_InventoryLocationPreparationHandle(<redacted>)"

    def __reduce__(self) -> Any:
        raise TypeError("prepared_ebay_inventory_location_not_serializable")


class EbayWriteHttpAdapter:
    """Executes confirmed eBay publish writes behind the SaaS backend."""

    def __init__(self, settings: SaaSSettings, *, transport: HttpTransport | None = None) -> None:
        self.settings = settings
        self.transport = transport or _urlopen_transport
        self._draft_prepare_nonce = secrets.token_urlsafe(32)
        self._draft_prepare_lock = __import__("threading").Lock()
        self._draft_prepared_registry: dict[str, _DraftPreparationState] = {}
        self._inventory_location_registry: dict[str, _InventoryLocationPreparationState] = {}

    def prepare_inventory_location(
        self,
        *,
        confirmation: dict[str, Any],
        location_payload: dict[str, Any],
        credential_boundary: dict[str, Any],
        marketplace_id: str,
    ) -> _InventoryLocationPreparationHandle | dict[str, Any]:
        """Resolve the exact credential and prove the location is absent."""

        if not (
            self.settings.effective_ebay_draft_save_enabled
            or self.settings.effective_real_platform_writes_enabled
        ):
            return _inventory_location_blocked("inventory_location_write_disabled")
        if not _exact_inventory_location_confirmation(
            confirmation=confirmation,
            location_payload=location_payload,
            required_status="approved",
        ):
            return _inventory_location_blocked("inventory_location_approval_invalid")
        company_id = str(confirmation.get("company_id") or "")
        store_id = str(confirmation.get("store_id") or "")
        credential = _validated_unpublished_draft_credential_boundary(
            credential_boundary=credential_boundary,
            company_id=company_id,
            store_id=store_id,
        )
        if not credential:
            return _inventory_location_blocked("inventory_location_credential_boundary_not_ready")
        token = self._resolve_access_token(
            secret_ref_id=str(credential["connection"]["secret_ref"]),
            company_id=company_id,
            store_id=store_id,
        )
        if not token.get("ok"):
            return _inventory_location_blocked("inventory_location_token_resolution_failed")
        location_key = str(location_payload.get("merchantLocationKey") or "")
        base_url = _base_url(self.settings)
        location_path = f"/sell/inventory/v1/location/{urllib.parse.quote(location_key, safe='')}"
        inspection = self._get_json(
            url=f"{base_url}{location_path}",
            access_token=str(token["access_token"]),
            marketplace_id=marketplace_id,
        )
        if inspection.get("status") == "ok":
            existing = inspection.get("json") if isinstance(inspection.get("json"), dict) else {}
            if str(existing.get("merchantLocationKey") or "") == location_key:
                return {
                    "status": "inventory_location_already_exists",
                    "merchant_location_key": location_key,
                    "writes_to_ebay": False,
                    "public_listing_created": False,
                    "secret_exposed": False,
                }
            return _inventory_location_blocked("inventory_location_existing_response_mismatch")
        if not _is_exact_missing_inventory_location(inspection):
            return _inventory_location_blocked("inventory_location_preflight_blocked")
        credential_items = tuple(sorted({
            "connection_id_sha256": credential["connection_id_sha256"],
            "credential_ref_sha256": credential["credential_ref_sha256"],
            "oauth_request_id_sha256": credential["oauth_request_id_sha256"],
            "seller_identity_sha256": credential["seller_identity_sha256"],
        }.items()))
        payload_sha256 = hashlib.sha256(_canonical_json_bytes(location_payload)).hexdigest()
        handle = secrets.token_urlsafe(32)
        state = _InventoryLocationPreparationState(
            company_id=company_id,
            store_id=store_id,
            confirmation_id=str(confirmation.get("confirmation_id") or ""),
            task_id=str(confirmation.get("task_id") or ""),
            marketplace_id=marketplace_id,
            merchant_location_key=location_key,
            access_token=str(token["access_token"]),
            location_payload_json=_canonical_json_bytes(location_payload),
            payload_sha256=payload_sha256,
            prepared_at_epoch=time.time(),
            credential_binding_items=credential_items,
        )
        with self._draft_prepare_lock:
            self._inventory_location_registry[handle] = state
        return _InventoryLocationPreparationHandle(
            handle=handle,
            safe_binding={
                "confirmation_id": state.confirmation_id,
                "company_id": state.company_id,
                "store_id": state.store_id,
                "action_type": "create_ebay_inventory_location",
                "task_id": state.task_id,
                "marketplace_id": state.marketplace_id,
                "payload_sha256": state.payload_sha256,
                **dict(state.credential_binding_items),
            },
        )

    def execute_prepared_inventory_location(
        self,
        *,
        confirmation: dict[str, Any],
        prepared: _InventoryLocationPreparationHandle,
        marketplace_id: str,
    ) -> dict[str, Any]:
        """Create one location from a process-local, one-shot preparation."""

        with self._draft_prepare_lock:
            state = self._inventory_location_registry.pop(getattr(prepared, "_handle", ""), None)
        item = confirmation.get("item") if isinstance(confirmation.get("item"), dict) else {}
        location_payload = item.get("location_payload") if isinstance(item.get("location_payload"), dict) else {}
        valid = bool(
            isinstance(prepared, _InventoryLocationPreparationHandle)
            and isinstance(state, _InventoryLocationPreparationState)
            and _exact_inventory_location_confirmation(
                confirmation=confirmation,
                location_payload=location_payload,
                required_status="external_execution_processing_manual_reconcile",
            )
            and confirmation.get("external_execution_claimed") is True
            and state.company_id == str(confirmation.get("company_id") or "")
            and state.store_id == str(confirmation.get("store_id") or "")
            and state.confirmation_id == str(confirmation.get("confirmation_id") or "")
            and state.task_id == str(confirmation.get("task_id") or "")
            and state.marketplace_id == marketplace_id
            and state.payload_sha256 == hashlib.sha256(_canonical_json_bytes(location_payload)).hexdigest()
            and 0 <= time.time() - state.prepared_at_epoch <= 30
        )
        if not valid:
            return _inventory_location_blocked("inventory_location_preparation_invalid")
        provider_payload = json.loads(state.location_payload_json.decode("utf-8"))
        provider_payload.pop("merchantLocationKey", None)
        location_path = f"/sell/inventory/v1/location/{urllib.parse.quote(state.merchant_location_key, safe='')}"
        write_result = self._send_json(
            method="POST",
            url=f"{_base_url(self.settings)}{location_path}",
            access_token=state.access_token,
            marketplace_id=marketplace_id,
            body=provider_payload,
        )
        if write_result.get("status") != "ok":
            return {
                "status": "inventory_location_manual_reconcile",
                "action_type": "create_ebay_inventory_location",
                "task_id": state.task_id,
                "automatic_retry_allowed": False,
                "location_write_completed": False,
                "public_listing_created": False,
                "secret_exposed": False,
            }
        return {
            "status": "inventory_location_created",
            "action_type": "create_ebay_inventory_location",
            "task_id": state.task_id,
            "merchant_location_key": state.merchant_location_key,
            "location_write_completed": True,
            "public_listing_created": False,
            "audit": {
                "real_execution": {
                    "inventory_location_created": True,
                    "published_to_ebay": False,
                    "public_listing_created": False,
                },
                "credential_binding": dict(state.credential_binding_items),
                "secret_exposed": False,
            },
            "secret_exposed": False,
        }

    def reconcile_inventory_location(
        self,
        *,
        confirmation: dict[str, Any],
        location_payload: dict[str, Any],
        credential_boundary: dict[str, Any],
        marketplace_id: str,
    ) -> dict[str, Any]:
        """Read the exact location after an uncertain write; never retry it."""

        if not _exact_inventory_location_confirmation(
            confirmation=confirmation,
            location_payload=location_payload,
            required_status="external_execution_processing_manual_reconcile",
        ):
            return _inventory_location_blocked("inventory_location_reconcile_confirmation_invalid")
        company_id = str(confirmation.get("company_id") or "")
        store_id = str(confirmation.get("store_id") or "")
        credential = _validated_unpublished_draft_credential_boundary(
            credential_boundary=credential_boundary,
            company_id=company_id,
            store_id=store_id,
        )
        if not credential:
            return _inventory_location_blocked("inventory_location_credential_boundary_not_ready")
        token = self._resolve_access_token(
            secret_ref_id=str(credential["connection"]["secret_ref"]),
            company_id=company_id,
            store_id=store_id,
        )
        if not token.get("ok"):
            return _inventory_location_blocked("inventory_location_token_resolution_failed")
        location_key = str(location_payload.get("merchantLocationKey") or "")
        location_path = f"/sell/inventory/v1/location/{urllib.parse.quote(location_key, safe='')}"
        inspection = self._get_json(
            url=f"{_base_url(self.settings)}{location_path}",
            access_token=str(token["access_token"]),
            marketplace_id=marketplace_id,
        )
        if inspection.get("status") != "ok":
            return {
                **_inventory_location_blocked("inventory_location_reconcile_unconfirmed"),
                "automatic_retry_allowed": False,
                "reconciled_from_provider_read": True,
            }
        existing = inspection.get("json") if isinstance(inspection.get("json"), dict) else {}
        if not _is_exact_inventory_location_match(existing=existing, expected=location_payload):
            return {
                **_inventory_location_blocked("inventory_location_reconcile_response_mismatch"),
                "automatic_retry_allowed": False,
                "reconciled_from_provider_read": True,
            }
        credential_binding = {
            "connection_id_sha256": credential["connection_id_sha256"],
            "credential_ref_sha256": credential["credential_ref_sha256"],
            "oauth_request_id_sha256": credential["oauth_request_id_sha256"],
            "seller_identity_sha256": credential["seller_identity_sha256"],
        }
        return {
            "status": "inventory_location_created",
            "action_type": "create_ebay_inventory_location",
            "task_id": str(confirmation.get("task_id") or ""),
            "merchant_location_key": location_key,
            "location_write_completed": True,
            "reconciled_from_provider_read": True,
            "writes_to_ebay": False,
            "public_listing_created": False,
            "audit": {
                "real_execution": {
                    "inventory_location_created": True,
                    "reconciled_from_provider_read": True,
                    "published_to_ebay": False,
                    "public_listing_created": False,
                },
                "credential_binding": credential_binding,
                "secret_exposed": False,
            },
            "secret_exposed": False,
        }

    def discard_inventory_location_preparation(self, prepared: Any) -> None:
        """Best-effort removal when the database claim loses a race."""

        with self._draft_prepare_lock:
            self._inventory_location_registry.pop(getattr(prepared, "_handle", ""), None)

    def publish_listing(
        self,
        *,
        request: Any,
        preflight: dict[str, Any],
        connections: list[dict[str, Any]],
        secret_refs: list[dict[str, Any]],
        marketplace_id: str,
    ) -> dict[str, Any]:
        if not self.settings.effective_real_platform_writes_enabled:
            return _blocked("real_platform_writes_disabled", ["JIEJING_ENABLE_REAL_PLATFORM_WRITES_OR_JIEJING_EBAY_WRITE_LIVE"])
        if str(getattr(request, "action_type", "") or "") != "publish_listing":
            return _blocked("unsupported_write_action", ["only_publish_listing_supported"])
        if preflight.get("status") != "ready_for_platform_adapter":
            return _blocked("preflight_not_ready", preflight.get("missing_fields") or ["execution_preflight_not_ready"], preflight=preflight)

        connection = _find_publish_connection(connections)
        if not connection:
            return _blocked("ebay_publish_scope_missing", ["seller_must_authorize_sell.inventory_scope"], preflight=preflight)

        secret_ref_id = str(connection.get("secret_ref") or _first_secret_ref(secret_refs) or "")
        token = self._resolve_access_token(
            secret_ref_id=secret_ref_id,
            company_id=str(getattr(request, "company_id", "") or ""),
            store_id=str(getattr(request, "store_id", "") or ""),
        )
        if not token.get("ok"):
            return _blocked("token_resolution_failed", token.get("blocked_by") or ["access_token_unavailable"], preflight=preflight)

        payload = getattr(request, "payload", {}) if isinstance(getattr(request, "payload", {}), dict) else {}
        listing = payload.get("listing") if isinstance(payload.get("listing"), dict) else {}
        sku = str(listing.get("sku") or "").strip()
        base_url = _base_url(self.settings)
        inventory_body = _inventory_item_body(payload)
        offer_body = _offer_body(payload, marketplace_id=marketplace_id)
        if not sku or not inventory_body or not offer_body:
            return _blocked("publish_payload_invalid", ["listing_payload_not_mappable_to_ebay_inventory_api"], preflight=preflight)

        access_token = str(token["access_token"])
        steps: list[dict[str, Any]] = []
        inventory_path = f"/sell/inventory/v1/inventory_item/{urllib.parse.quote(sku, safe='')}"
        inventory_result = self._send_json(
            method="PUT",
            url=f"{base_url}{inventory_path}",
            access_token=access_token,
            marketplace_id=marketplace_id,
            body=inventory_body,
        )
        steps.append(_step_summary("create_or_replace_inventory_item", inventory_path, inventory_result))
        if inventory_result.get("status") != "ok":
            return _write_result("blocked_platform_error", "eBay inventory item write failed.", steps, preflight=preflight)

        offer_path = "/sell/inventory/v1/offer"
        offer_result = self._send_json(
            method="POST",
            url=f"{base_url}{offer_path}",
            access_token=access_token,
            marketplace_id=marketplace_id,
            body=offer_body,
        )
        steps.append(_step_summary("create_offer", offer_path, offer_result))
        if offer_result.get("status") != "ok":
            return _write_result("blocked_platform_error", "eBay offer creation failed.", steps, preflight=preflight)

        offer_id = str((offer_result.get("json") or {}).get("offerId") or (offer_result.get("json") or {}).get("offer_id") or "").strip()
        if not offer_id:
            return _write_result("blocked_missing_offer_id", "eBay did not return an offerId.", steps, preflight=preflight)

        publish_path = f"/sell/inventory/v1/offer/{urllib.parse.quote(offer_id, safe='')}/publish"
        publish_result = self._send_json(
            method="POST",
            url=f"{base_url}{publish_path}",
            access_token=access_token,
            marketplace_id=marketplace_id,
            body={},
        )
        steps.append(_step_summary("publish_offer", publish_path, publish_result))
        if publish_result.get("status") != "ok":
            return _write_result("blocked_platform_error", "eBay publishOffer failed.", steps, preflight=preflight)

        publish_json = publish_result.get("json") if isinstance(publish_result.get("json"), dict) else {}
        listing_id = str(publish_json.get("listingId") or publish_json.get("listing_id") or "").strip()
        audit = _audit(
            request=request,
            preflight=preflight,
            real_execution={
                "published_to_ebay": True,
                "procurement_paid": False,
                "refund_executed": False,
                "ad_budget_changed": False,
                "store_policy_changed": False,
            },
            platform_result={
                "offer_id": offer_id,
                "listing_id": listing_id,
                "marketplace_id": marketplace_id,
                "sku": sku,
                "token_source": token.get("source"),
                "access_token_returned_to_frontend": False,
                "access_token_returned_to_runtime": False,
                "raw_response_stored": False,
            },
        )
        return {
            "status": "published_to_ebay",
            "action_type": "publish_listing",
            "task_id": getattr(request, "task_id", ""),
            "message": "Confirmed listing was published to eBay through the backend write adapter.",
            "steps": steps,
            "platform_result": audit["platform_result"],
            "audit": audit,
            "secret_exposed": False,
        }

    def publish_existing_listing_draft(
        self,
        *,
        request: Any,
        preflight: dict[str, Any],
        credential_boundary: dict[str, Any],
        marketplace_id: str,
        expected_offer_id: str,
    ) -> dict[str, Any]:
        """Publish one exact, already saved eBay Offer without recreating it."""

        if not self.settings.effective_ebay_controlled_publish_enabled:
            return _blocked(
                "controlled_existing_draft_publish_disabled",
                ["JIEJING_EBAY_CONTROLLED_PUBLISH_LIVE"],
            )
        if str(getattr(request, "action_type", "") or "") != "publish_listing":
            return _blocked("unsupported_write_action", ["only_publish_listing_supported"])
        if preflight.get("status") != "ready_for_platform_adapter":
            return _blocked(
                "preflight_not_ready",
                preflight.get("missing_fields") or ["execution_preflight_not_ready"],
                preflight=preflight,
            )
        payload = getattr(request, "payload", {}) if isinstance(getattr(request, "payload", {}), dict) else {}
        listing = payload.get("listing") if isinstance(payload.get("listing"), dict) else {}
        draft = payload.get("existing_ebay_draft") if isinstance(payload.get("existing_ebay_draft"), dict) else {}
        sku = str(listing.get("sku") or "").strip()
        expected_offer_id = str(expected_offer_id or "").strip()
        if not (
            sku
            and expected_offer_id
            and str(draft.get("offer_id") or "").strip() == expected_offer_id
            and str(draft.get("sku") or "").strip() == sku
            and str(draft.get("offer_status") or "").strip().upper() == "UNPUBLISHED"
            and draft.get("public_listing_created") is False
            and str(draft.get("source_execution_id") or "").strip()
            and str(draft.get("source_confirmation_id") or "").strip()
        ):
            return _write_result(
                "controlled_publish_binding_invalid",
                "The approved confirmation is not bound to one exact unpublished eBay draft.",
                [],
                preflight=preflight,
            )
        credential = _validated_unpublished_draft_credential_boundary(
            credential_boundary=credential_boundary,
            company_id=str(getattr(request, "company_id", "") or ""),
            store_id=str(getattr(request, "store_id", "") or ""),
        )
        if not credential:
            return _blocked(
                "controlled_publish_credential_boundary_blocked",
                ["exact_unique_unpublished_draft_connection_and_secret_required"],
                preflight=preflight,
            )
        connection = credential["connection"]
        secret_ref_id = str(connection["secret_ref"])
        token = self._resolve_access_token(
            secret_ref_id=secret_ref_id,
            company_id=str(getattr(request, "company_id", "") or ""),
            store_id=str(getattr(request, "store_id", "") or ""),
        )
        if not token.get("ok"):
            return _blocked(
                "token_resolution_failed",
                token.get("blocked_by") or ["access_token_unavailable"],
                preflight=preflight,
            )

        access_token = str(token["access_token"])
        base_url = _base_url(self.settings)
        steps: list[dict[str, Any]] = []
        kyc_path = "/sell/account/v1/kyc"
        kyc_result = self._get_json(
            url=f"{base_url}{kyc_path}",
            access_token=access_token,
            marketplace_id=marketplace_id,
        )
        steps.append(_step_summary("inspect_account_kyc", kyc_path, kyc_result))
        if kyc_result.get("status") != "ok":
            return _write_result(
                "controlled_publish_account_verification_inspection_failed",
                "The current eBay account verification state could not be checked, so publishOffer was not called.",
                steps,
                preflight=preflight,
            )
        kyc_json = kyc_result.get("json") if isinstance(kyc_result.get("json"), dict) else {}
        kyc_checks = _safe_ebay_kyc_checks(kyc_json)
        if kyc_checks:
            return _write_result(
                "controlled_publish_account_verification_required",
                "eBay still has an account verification or KYC action item; publishOffer was not called.",
                steps,
                preflight=preflight,
                platform_result={
                    "account_verification_status": "verification_required",
                    "kyc_check_count": len(kyc_checks),
                    "kyc_checks": kyc_checks,
                    "published_to_ebay": False,
                    "raw_response_stored": False,
                    "secret_exposed": False,
                },
            )
        offers_path = f"/sell/inventory/v1/offer?sku={urllib.parse.quote(sku, safe='')}"
        offers_result = self._get_json(
            url=f"{base_url}{offers_path}",
            access_token=access_token,
            marketplace_id=marketplace_id,
        )
        offers_result = _normalize_missing_offer_inspection(offers_result)
        steps.append(_step_summary("inspect_existing_offer", offers_path, offers_result))
        if offers_result.get("status") != "ok":
            return _write_result(
                "controlled_publish_offer_inspection_failed",
                "The existing eBay draft could not be checked, so publishOffer was not called.",
                steps,
                preflight=preflight,
            )
        offers_json = offers_result.get("json") if isinstance(offers_result.get("json"), dict) else {}
        offers = offers_json.get("offers") if isinstance(offers_json.get("offers"), list) else []
        published_offer = _published_offer(offers)
        if published_offer:
            return _write_result(
                "controlled_publish_already_public",
                "The SKU already has a public eBay listing; the controlled publish stopped.",
                steps,
                preflight=preflight,
            )
        target_marketplace = str(marketplace_id or "").strip().upper()
        unpublished = []
        for raw in offers:
            candidate = _unpublished_offer([raw], marketplace_id=marketplace_id)
            if not candidate:
                continue
            candidate_marketplace = str(candidate.get("marketplace_id") or "").strip().upper()
            if target_marketplace and candidate_marketplace and candidate_marketplace != target_marketplace:
                continue
            unpublished.append(candidate)
        exact = [item for item in unpublished if str(item.get("offer_id") or "").strip() == expected_offer_id]
        if len(unpublished) != 1 or len(exact) != 1:
            return _write_result(
                "controlled_publish_offer_mismatch",
                "The current eBay draft no longer matches the approved Offer ID; publishOffer was not called.",
                steps,
                preflight=preflight,
            )

        publish_path = f"/sell/inventory/v1/offer/{urllib.parse.quote(expected_offer_id, safe='')}/publish"
        publish_result = self._send_json(
            method="POST",
            url=f"{base_url}{publish_path}",
            access_token=access_token,
            marketplace_id=marketplace_id,
            body={},
        )
        steps.append(_step_summary("publish_existing_offer", publish_path, publish_result))
        if publish_result.get("status") != "ok":
            return _write_result(
                "blocked_platform_error",
                "eBay publishOffer failed for the approved existing draft.",
                steps,
                preflight=preflight,
            )
        publish_json = publish_result.get("json") if isinstance(publish_result.get("json"), dict) else {}
        listing_id = str(publish_json.get("listingId") or publish_json.get("listing_id") or "").strip()
        audit = _audit(
            request=request,
            preflight=preflight,
            real_execution={
                "published_to_ebay": True,
                "procurement_paid": False,
                "refund_executed": False,
                "ad_budget_changed": False,
                "store_policy_changed": False,
            },
            platform_result={
                "offer_id": expected_offer_id,
                "listing_id": listing_id,
                "marketplace_id": marketplace_id,
                "sku": sku,
                "published_existing_offer": True,
                "source_execution_id": str(draft.get("source_execution_id") or ""),
                "source_confirmation_id": str(draft.get("source_confirmation_id") or ""),
                "token_source": token.get("source"),
                "access_token_returned_to_frontend": False,
                "access_token_returned_to_runtime": False,
                "raw_response_stored": False,
            },
        )
        return {
            "status": "published_to_ebay",
            "action_type": "publish_listing",
            "task_id": getattr(request, "task_id", ""),
            "message": "The confirmed existing eBay draft was published without creating another offer.",
            "steps": steps,
            "platform_result": audit["platform_result"],
            "audit": audit,
            "secret_exposed": False,
        }

    def save_listing_draft(
        self,
        *,
        request: Any,
        preflight: dict[str, Any],
        connections: list[dict[str, Any]],
        secret_refs: list[dict[str, Any]],
        marketplace_id: str,
    ) -> dict[str, Any]:
        """Retired unsafe seam: callers must use prepare -> repository claim -> execute."""

        del request, connections, secret_refs, marketplace_id
        return _draft_blocked(
            "draft_prepare_claim_execute_required",
            ["repository_claim_capability_required"],
            preflight=preflight,
        )

    def prepare_listing_draft(
        self,
        *,
        request: Any,
        preflight: dict[str, Any],
        credential_boundary: dict[str, Any],
        marketplace_id: str,
    ) -> _DraftPreparationHandle | dict[str, Any]:
        """Perform every deterministic check and the read-only offer lookup."""

        action_type = str(getattr(request, "action_type", "") or "")
        if not (
            self.settings.effective_ebay_draft_save_enabled
            or self.settings.effective_real_platform_writes_enabled
        ):
            return _draft_blocked(
                "ebay_draft_save_disabled",
                ["JIEJING_EBAY_DRAFT_SAVE_LIVE"],
            )
        if action_type != "save_ebay_listing_draft":
            return _draft_blocked("unsupported_write_action", ["only_save_ebay_listing_draft_supported"])
        if preflight.get("status") != "ready_for_platform_adapter":
            return _draft_blocked(
                "preflight_not_ready",
                preflight.get("missing_fields") or ["execution_preflight_not_ready"],
                preflight=preflight,
            )

        credential = _validated_unpublished_draft_credential_boundary(
            credential_boundary=credential_boundary,
            company_id=str(getattr(request, "company_id", "") or ""),
            store_id=str(getattr(request, "store_id", "") or ""),
        )
        if not credential:
            return _draft_blocked(
                "ebay_draft_connection_boundary_not_ready",
                ["exact_unique_unpublished_draft_connection_and_secret_required"],
                preflight=preflight,
            )

        connection = credential["connection"]
        secret_ref_id = str(connection["secret_ref"])
        token = self._resolve_access_token(
            secret_ref_id=secret_ref_id,
            company_id=str(getattr(request, "company_id", "") or ""),
            store_id=str(getattr(request, "store_id", "") or ""),
        )
        if not token.get("ok"):
            return _draft_blocked("token_resolution_failed", token.get("blocked_by") or ["access_token_unavailable"], preflight=preflight)

        payload = getattr(request, "payload", {}) if isinstance(getattr(request, "payload", {}), dict) else {}
        listing = payload.get("listing") if isinstance(payload.get("listing"), dict) else {}
        sku = str(listing.get("sku") or "").strip()
        inventory_body = _inventory_item_body(payload)
        offer_body = _offer_body(payload, marketplace_id=marketplace_id)
        if not sku or not inventory_body or not offer_body:
            return _draft_blocked("draft_payload_invalid", ["listing_payload_not_mappable_to_ebay_inventory_api"], preflight=preflight)

        access_token = str(token["access_token"])
        base_url = _base_url(self.settings)
        steps: list[dict[str, Any]] = []
        offers_path = f"/sell/inventory/v1/offer?sku={urllib.parse.quote(sku, safe='')}"
        offers_result = self._get_json(
            url=f"{base_url}{offers_path}",
            access_token=access_token,
            marketplace_id=marketplace_id,
        )
        offers_result = _normalize_missing_offer_inspection(offers_result)
        steps.append(_step_summary("inspect_offers_by_sku", offers_path, offers_result))
        if offers_result.get("status") != "ok":
            return _draft_write_result(
                "blocked_offer_inspection_failed",
                "Existing eBay offers could not be checked, so no new draft offer was created.",
                steps,
                preflight=preflight,
            )

        offers_json = offers_result.get("json") if isinstance(offers_result.get("json"), dict) else {}
        offers = offers_json.get("offers") if isinstance(offers_json.get("offers"), list) else []
        published_offer = _published_offer(offers)
        if published_offer:
            return _draft_write_result(
                "blocked_existing_published_offer",
                "This SKU already has a published eBay offer; draft save stopped to avoid changing a live listing.",
                steps,
                preflight=preflight,
                platform_result={
                    "sku": sku,
                    "published_offer": published_offer,
                    "published_to_ebay": False,
                    "public_listing_created": False,
                    "writes_to_ebay": False,
                },
            )

        existing_offer = _unpublished_offer(offers, marketplace_id=marketplace_id)
        existing_offer_id = str((existing_offer or {}).get("offer_id") or "")
        binding_items = tuple(sorted({
            "contract_version": "2026-08-13-unpublished-draft-credential-v1",
            "connection_id_sha256": credential["connection_id_sha256"],
            "credential_ref_sha256": credential["credential_ref_sha256"],
            "oauth_request_id_sha256": credential["oauth_request_id_sha256"],
            "seller_identity_sha256": credential["seller_identity_sha256"],
        }.items()))
        preparation_data = {
            "company_id": str(getattr(request, "company_id", "") or ""),
            "store_id": str(getattr(request, "store_id", "") or ""),
            "marketplace_id": marketplace_id,
            "sku": sku,
            "payload_sha256": _draft_payload_sha256(payload),
            "confirmation_id": str(getattr(request, "confirmation_id", "") or ""),
            "task_id": str(getattr(request, "task_id", "") or ""),
            "idempotency_key": str(getattr(request, "idempotency_key", "") or ""),
            "credential_binding": binding_items,
            "offer_fingerprint": _offer_snapshot_fingerprint(offers),
        }
        preparation_sha256 = hashlib.sha256(_canonical_json_bytes(preparation_data)).hexdigest()
        handle = secrets.token_urlsafe(32)
        state = _DraftPreparationState(
            company_id=str(getattr(request, "company_id", "") or ""),
            store_id=str(getattr(request, "store_id", "") or ""),
            marketplace_id=marketplace_id,
            sku=sku,
            access_token=access_token,
            token_source=str(token.get("source") or ""),
            inventory_body_json=_canonical_json_bytes(inventory_body),
            offer_body_json=_canonical_json_bytes(offer_body),
            expected_offer_id=existing_offer_id,
            expected_offer_fingerprint=_offer_snapshot_fingerprint(offers),
            inspection_steps=tuple(steps),
            payload_sha256=_draft_payload_sha256(payload),
            confirmation_id=str(getattr(request, "confirmation_id", "") or ""),
            task_id=str(getattr(request, "task_id", "") or ""),
            idempotency_key=str(getattr(request, "idempotency_key", "") or ""),
            prepared_at_epoch=time.time(),
            credential_binding_items=binding_items,
            preparation_sha256=preparation_sha256,
        )
        with self._draft_prepare_lock:
            self._draft_prepared_registry[handle] = state
        return _DraftPreparationHandle(
            handle=handle,
            safe_binding={
                "confirmation_id": state.confirmation_id,
                "company_id": state.company_id,
                "store_id": state.store_id,
                "action_type": "save_ebay_listing_draft",
                "task_id": state.task_id,
                "idempotency_key": state.idempotency_key,
                "marketplace_id": state.marketplace_id,
                "payload_sha256": state.payload_sha256,
                "preparation_sha256": state.preparation_sha256,
                **dict(state.credential_binding_items),
            },
        )

    def execute_prepared_listing_draft(
        self,
        *,
        request: Any,
        preflight: dict[str, Any],
        prepared: _DraftPreparationHandle,
        claim_capability: Any,
        marketplace_id: str,
    ) -> dict[str, Any]:
        """Write only with a repository-minted, one-shot claim capability."""

        with self._draft_prepare_lock:
            state = self._draft_prepared_registry.pop(getattr(prepared, "_handle", ""), None)
        payload = getattr(request, "payload", {}) if isinstance(getattr(request, "payload", {}), dict) else {}
        binding_valid = bool(
            isinstance(prepared, _DraftPreparationHandle)
            and isinstance(state, _DraftPreparationState)
            and str(getattr(request, "action_type", "") or "") == "save_ebay_listing_draft"
            and state.company_id == str(getattr(request, "company_id", "") or "")
            and state.store_id == str(getattr(request, "store_id", "") or "")
            and state.marketplace_id == marketplace_id
            and state.payload_sha256 == _draft_payload_sha256(payload)
            and state.confirmation_id == str(getattr(request, "confirmation_id", "") or "")
            and state.task_id == str(getattr(request, "task_id", "") or "")
            and state.idempotency_key == str(getattr(request, "idempotency_key", "") or "")
            and 0 <= time.time() - state.prepared_at_epoch <= 30
            and _valid_draft_claim_capability(
                capability=claim_capability,
                request=request,
                prepared=state,
            )
            and preflight.get("status") == "ready_for_platform_adapter"
        )
        if not binding_valid:
            abort = getattr(claim_capability, "abort", None)
            if callable(abort):
                try:
                    abort(reason_code="prepared_binding_invalid")
                except Exception:
                    pass
            return _draft_blocked("prepared_draft_binding_invalid", ["prepare_claim_write_binding_mismatch"], preflight=preflight)

        sku = state.sku
        access_token = state.access_token
        inventory_body = json.loads(state.inventory_body_json.decode("utf-8"))
        offer_body = json.loads(state.offer_body_json.decode("utf-8"))
        steps = list(state.inspection_steps)
        base_url = _base_url(self.settings)
        offers_path = f"/sell/inventory/v1/offer?sku={urllib.parse.quote(sku, safe='')}"
        recheck_result = self._get_json(
            url=f"{base_url}{offers_path}",
            access_token=access_token,
            marketplace_id=marketplace_id,
        )
        recheck_result = _normalize_missing_offer_inspection(recheck_result)
        steps.append(_step_summary("recheck_offers_by_sku", offers_path, recheck_result))
        recheck_json = recheck_result.get("json") if isinstance(recheck_result.get("json"), dict) else {}
        recheck_offers = recheck_json.get("offers") if isinstance(recheck_json.get("offers"), list) else []
        if (
            recheck_result.get("status") != "ok"
            or _published_offer(recheck_offers)
            or _offer_snapshot_fingerprint(recheck_offers) != state.expected_offer_fingerprint
        ):
            try:
                claim_capability.abort(reason_code="offer_state_changed")
            except Exception:
                pass
            return _draft_write_result(
                "blocked_offer_state_changed_before_write",
                "The eBay offer state changed after preparation; no write was attempted.",
                steps,
                preflight=preflight,
                platform_result={"sku": sku, "writes_to_ebay": False, "published_to_ebay": False, "public_listing_created": False},
            )
        try:
            consumed_claim = claim_capability.consume()
        except Exception:
            try:
                claim_capability.abort(reason_code="claim_consume_failed")
            except Exception:
                pass
            return _draft_blocked(
                "draft_claim_consume_failed",
                ["database_claim_capability_not_consumed"],
                preflight=preflight,
            )
        if not _valid_consumed_draft_execution_claim(
            claim=consumed_claim,
            request=request,
            prepared=state,
        ):
            return _draft_blocked(
                "draft_claim_consume_failed",
                ["database_claim_capability_not_consumed"],
                preflight=preflight,
            )
        existing_offer = _unpublished_offer(recheck_offers, marketplace_id=marketplace_id)
        inventory_path = f"/sell/inventory/v1/inventory_item/{urllib.parse.quote(sku, safe='')}"
        inventory_result = self._send_json(
            method="PUT",
            url=f"{base_url}{inventory_path}",
            access_token=access_token,
            marketplace_id=marketplace_id,
            body=inventory_body,
        )
        steps.append(_step_summary("create_or_replace_inventory_item", inventory_path, inventory_result))
        if inventory_result.get("status") != "ok":
            return _draft_write_result("blocked_platform_error", "eBay inventory draft write failed.", steps, preflight=preflight)

        if existing_offer:
            offer_id = str(existing_offer.get("offer_id") or "").strip()
            offer_path = f"/sell/inventory/v1/offer/{urllib.parse.quote(offer_id, safe='')}"
            offer_result = self._send_json(
                method="PUT",
                url=f"{base_url}{offer_path}",
                access_token=access_token,
                marketplace_id=marketplace_id,
                body=offer_body,
            )
            operation = "update_unpublished_offer"
        else:
            offer_path = "/sell/inventory/v1/offer"
            offer_result = self._send_json(
                method="POST",
                url=f"{base_url}{offer_path}",
                access_token=access_token,
                marketplace_id=marketplace_id,
                body=offer_body,
            )
            offer_json = offer_result.get("json") if isinstance(offer_result.get("json"), dict) else {}
            offer_id = str(offer_json.get("offerId") or offer_json.get("offer_id") or "").strip()
            operation = "create_unpublished_offer"
        steps.append(_step_summary(operation, offer_path, offer_result))
        if offer_result.get("status") != "ok":
            return _draft_write_result("blocked_platform_error", "eBay unpublished offer save failed.", steps, preflight=preflight)
        if not offer_id:
            return _draft_write_result("blocked_missing_offer_id", "eBay did not return or retain an offerId.", steps, preflight=preflight)

        platform_result = {
            "offer_id": offer_id,
            "sku": sku,
            "marketplace_id": marketplace_id,
            "operation": operation,
            "offer_status": "UNPUBLISHED",
            "published_to_ebay": False,
            "public_listing_created": False,
            "writes_to_ebay": True,
            "token_source": state.token_source,
            "access_token_returned_to_frontend": False,
            "access_token_returned_to_runtime": False,
            "raw_response_stored": False,
            **dict(state.credential_binding_items),
            "authorization_kind": "unpublished_draft",
            "scope_profile": "seller_unpublished_draft",
        }
        audit = _audit(
            request=request,
            preflight=preflight,
            real_execution={
                "ebay_draft_saved": True,
                "published_to_ebay": False,
                "procurement_paid": False,
                "refund_executed": False,
                "ad_budget_changed": False,
                "store_policy_changed": False,
            },
            platform_result=platform_result,
        )
        return {
            "status": "saved_to_ebay_draft",
            "action_type": "save_ebay_listing_draft",
            "task_id": getattr(request, "task_id", ""),
            "message": "Confirmed Listing data was saved as an unpublished eBay offer; no public listing was created.",
            "steps": steps,
            "platform_result": audit["platform_result"],
            "audit": audit,
            "secret_exposed": False,
        }

    def inspect_publish_state(
        self,
        *,
        request: Any,
        connections: list[dict[str, Any]],
        secret_refs: list[dict[str, Any]],
        marketplace_id: str,
    ) -> dict[str, Any]:
        """Read eBay by SKU after ambiguous publish outcomes; never writes."""

        payload = getattr(request, "payload", {}) if isinstance(getattr(request, "payload", {}), dict) else {}
        listing = payload.get("listing") if isinstance(payload.get("listing"), dict) else {}
        draft = payload.get("existing_ebay_draft") if isinstance(payload.get("existing_ebay_draft"), dict) else {}
        sku = str(listing.get("sku") or "").strip()
        if not sku:
            return _recovery_result("blocked_missing_sku", sku="", checks=[], safe_to_retry=False)

        connection = _find_publish_connection(connections)
        if not connection:
            return _recovery_result("ebay_publish_scope_missing", sku=sku, checks=[], safe_to_retry=False)

        secret_ref_id = str(connection.get("secret_ref") or _first_secret_ref(secret_refs) or "")
        token = self._resolve_access_token(
            secret_ref_id=secret_ref_id,
            company_id=str(getattr(request, "company_id", "") or ""),
            store_id=str(getattr(request, "store_id", "") or ""),
        )
        if not token.get("ok"):
            return _recovery_result(
                "token_resolution_failed",
                sku=sku,
                checks=[],
                safe_to_retry=False,
                blocked_by=token.get("blocked_by") or ["access_token_unavailable"],
            )

        access_token = str(token["access_token"])
        base_url = _base_url(self.settings)
        item_path = f"/sell/inventory/v1/inventory_item/{urllib.parse.quote(sku, safe='')}"
        offers_path = f"/sell/inventory/v1/offer?sku={urllib.parse.quote(sku, safe='')}"
        item_result = self._get_json(
            url=f"{base_url}{item_path}",
            access_token=access_token,
            marketplace_id=marketplace_id,
        )
        offers_result = self._get_json(
            url=f"{base_url}{offers_path}",
            access_token=access_token,
            marketplace_id=marketplace_id,
        )
        offers_json = offers_result.get("json") if isinstance(offers_result.get("json"), dict) else {}
        offers = offers_json.get("offers") if isinstance(offers_json.get("offers"), list) else []
        published = _published_offer(offers)
        expected_offer_id = str(draft.get("offer_id") or "").strip()
        unpublished = [
            candidate
            for raw in offers
            if (candidate := _unpublished_offer([raw], marketplace_id=marketplace_id))
        ]
        exact_unpublished = next(
            (
                candidate
                for candidate in unpublished
                if expected_offer_id and str(candidate.get("offer_id") or "") == expected_offer_id
            ),
            {},
        )
        checks = [
            _step_summary("inspect_inventory_item", item_path, item_result),
            _step_summary("inspect_offers_by_sku", offers_path, offers_result),
        ]
        inventory_found = item_result.get("status") == "ok"
        has_offers = bool(offers)
        has_published_offer = bool(published)
        safe_to_retry = not inventory_found and not has_offers
        safe_to_request_fresh_confirmation = bool(
            inventory_found
            and not has_published_offer
            and len(offers) == 1
            and len(unpublished) == 1
            and exact_unpublished
        )
        if has_published_offer:
            recommended_action = "backfill_execution_record"
        elif safe_to_request_fresh_confirmation:
            recommended_action = "request_fresh_exact_offer_confirmation"
        elif has_offers:
            recommended_action = "manual_review_existing_offer"
        elif safe_to_retry:
            recommended_action = "retry_publish_after_preflight"
        else:
            recommended_action = "manual_review_inventory_item"
        return {
            "status": "publish_state_checked",
            "action_type": "publish_listing",
            "sku": sku,
            "inventory_item_found": inventory_found,
            "offer_count": len(offers),
            "published_offer": published,
            "exact_unpublished_offer": exact_unpublished,
            "safe_to_retry_publish": safe_to_retry,
            "safe_to_request_fresh_confirmation": safe_to_request_fresh_confirmation,
            "recommended_action": recommended_action,
            "checks": checks,
            "cleanup_plan": _cleanup_plan(sku=sku, published_offer=published, offer_count=len(offers), inventory_found=inventory_found),
            "access_token_returned_to_frontend": False,
            "access_token_returned_to_runtime": False,
            "raw_response_stored": False,
            "secret_exposed": False,
        }

    def execute_cleanup_plan(
        self,
        *,
        request: Any,
        preflight: dict[str, Any],
        connections: list[dict[str, Any]],
        secret_refs: list[dict[str, Any]],
        marketplace_id: str,
    ) -> dict[str, Any]:
        """Execute only an explicitly confirmed, fixed-shape publish cleanup plan."""

        if not self.settings.effective_real_platform_writes_enabled:
            return _cleanup_blocked("real_platform_writes_disabled", ["real_platform_writes_not_enabled"], preflight=preflight)
        if str(getattr(request, "action_type", "") or "") != "cleanup_test_listing":
            return _cleanup_blocked("unsupported_write_action", ["only_cleanup_test_listing_supported"], preflight=preflight)
        if preflight.get("status") != "ready_for_platform_adapter":
            return _cleanup_blocked(
                "preflight_not_ready",
                preflight.get("missing_fields") or ["execution_preflight_not_ready"],
                preflight=preflight,
            )
        payload = getattr(request, "payload", {}) if isinstance(getattr(request, "payload", {}), dict) else {}
        plan = payload.get("cleanup_plan") if isinstance(payload.get("cleanup_plan"), dict) else {}
        operations = plan.get("operations") if isinstance(plan.get("operations"), list) else []
        if plan.get("confirmation_required") is not True or not operations:
            return _cleanup_blocked("cleanup_plan_invalid", ["exact_confirmed_cleanup_plan_required"], preflight=preflight)
        normalized = [item for item in operations if isinstance(item, dict)]
        if len(normalized) != len(operations) or any(
            str(item.get("operation") or "") not in {"end_listing", "withdraw_offer", "delete_offer", "delete_inventory_item"}
            for item in normalized
        ):
            return _cleanup_blocked("cleanup_plan_invalid", ["unsupported_cleanup_operation"], preflight=preflight)

        connection = _find_publish_connection(connections)
        if not connection:
            return _cleanup_blocked("ebay_publish_scope_missing", ["seller_must_authorize_sell.inventory_scope"], preflight=preflight)
        secret_ref_id = str(connection.get("secret_ref") or _first_secret_ref(secret_refs) or "")
        token = self._resolve_access_token(
            secret_ref_id=secret_ref_id,
            company_id=str(getattr(request, "company_id", "") or ""),
            store_id=str(getattr(request, "store_id", "") or ""),
        )
        if not token.get("ok"):
            return _cleanup_blocked("token_resolution_failed", token.get("blocked_by") or ["access_token_unavailable"], preflight=preflight)

        offer_id = next((str(item.get("offer_id") or "").strip() for item in normalized if str(item.get("offer_id") or "").strip()), "")
        access_token = str(token["access_token"])
        base_url = _base_url(self.settings)
        steps: list[dict[str, Any]] = []
        for item in normalized:
            operation = str(item.get("operation") or "")
            if operation in {"end_listing", "withdraw_offer"}:
                target = str(item.get("offer_id") or offer_id).strip()
                if not target:
                    return _cleanup_blocked("cleanup_plan_invalid", ["withdraw_offer_id_missing"], preflight=preflight)
                path = f"/sell/inventory/v1/offer/{urllib.parse.quote(target, safe='')}/withdraw"
                result = self._send_json(
                    method="POST",
                    url=f"{base_url}{path}",
                    access_token=access_token,
                    marketplace_id=marketplace_id,
                    body={},
                )
            elif operation == "delete_offer":
                target = str(item.get("offer_id") or "").strip()
                if not target:
                    return _cleanup_blocked("cleanup_plan_invalid", ["delete_offer_id_missing"], preflight=preflight)
                path = f"/sell/inventory/v1/offer/{urllib.parse.quote(target, safe='')}"
                result = self._send_json(
                    method="DELETE",
                    url=f"{base_url}{path}",
                    access_token=access_token,
                    marketplace_id=marketplace_id,
                    body={},
                )
            else:
                target = str(item.get("sku") or "").strip()
                if not target:
                    return _cleanup_blocked("cleanup_plan_invalid", ["delete_inventory_sku_missing"], preflight=preflight)
                path = f"/sell/inventory/v1/inventory_item/{urllib.parse.quote(target, safe='')}"
                result = self._send_json(
                    method="DELETE",
                    url=f"{base_url}{path}",
                    access_token=access_token,
                    marketplace_id=marketplace_id,
                    body={},
                )
            steps.append(_step_summary(operation, path, result))
            if result.get("status") != "ok":
                return _cleanup_write_result(
                    "blocked_platform_error",
                    "eBay test listing cleanup stopped after a platform error.",
                    steps,
                    preflight=preflight,
                )

        audit = _audit(
            request=request,
            preflight=preflight,
            real_execution={
                "cleanup_test_listing": True,
                "published_to_ebay": False,
                "procurement_paid": False,
                "refund_executed": False,
                "ad_budget_changed": False,
                "store_policy_changed": False,
            },
            platform_result={
                "operation_count": len(steps),
                "token_source": token.get("source"),
                "access_token_returned_to_frontend": False,
                "access_token_returned_to_runtime": False,
                "raw_response_stored": False,
            },
        )
        return {
            "status": "cleanup_completed",
            "action_type": "cleanup_test_listing",
            "task_id": getattr(request, "task_id", ""),
            "message": "Confirmed eBay test listing cleanup completed through the backend write adapter.",
            "steps": steps,
            "platform_result": audit["platform_result"],
            "audit": audit,
            "secret_exposed": False,
        }

    def _resolve_access_token(self, *, secret_ref_id: str, company_id: str, store_id: str) -> dict[str, Any]:
        return EbayReadOnlyHttpClient(self.settings, transport=self.transport)._resolve_access_token(
            secret_ref_id=secret_ref_id,
            company_id=company_id,
            store_id=store_id,
        )

    def _send_json(self, *, method: str, url: str, access_token: str, marketplace_id: str, body: dict[str, Any]) -> dict[str, Any]:
        data = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=data,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Content-Language": "en-US",
                "X-EBAY-C-MARKETPLACE-ID": marketplace_id,
            },
            method=method,
        )
        try:
            status, headers, raw = self.transport(request, 30)
            parsed = json.loads(raw.decode("utf-8")) if raw else {}
            return {
                "status": "ok" if status < 400 else "http_error",
                "http_status": status,
                "headers": _safe_headers(headers),
                "response_size": len(raw),
                "json": parsed if isinstance(parsed, dict) else {},
                "secret_exposed": False,
            }
        except urllib.error.HTTPError as exc:  # pragma: no cover - live provider dependent
            raw = exc.read() if hasattr(exc, "read") else b""
            return {
                "status": "http_error",
                "http_status": exc.code,
                "response_size": len(raw),
                "error_type": "HTTPError",
                "json": _safe_error_json(raw),
                "secret_exposed": False,
            }
        except Exception as exc:  # pragma: no cover - live provider dependent
            return {
                "status": "http_error",
                "http_status": None,
                "response_size": 0,
                "error_type": type(exc).__name__,
                "json": {},
                "secret_exposed": False,
            }

    def _get_json(self, *, url: str, access_token: str, marketplace_id: str) -> dict[str, Any]:
        request = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
                "Content-Language": "en-US",
                "X-EBAY-C-MARKETPLACE-ID": marketplace_id,
            },
            method="GET",
        )
        try:
            status, headers, raw = self.transport(request, 30)
            parsed = json.loads(raw.decode("utf-8")) if raw else {}
            return {
                "status": "ok" if status < 400 else "http_error",
                "http_status": status,
                "headers": _safe_headers(headers),
                "response_size": len(raw),
                "json": parsed if isinstance(parsed, dict) else {},
                "secret_exposed": False,
            }
        except urllib.error.HTTPError as exc:  # pragma: no cover - live provider dependent
            raw = exc.read() if hasattr(exc, "read") else b""
            return {
                "status": "not_found" if exc.code == 404 else "http_error",
                "http_status": exc.code,
                "response_size": len(raw),
                "error_type": "HTTPError",
                "json": _safe_error_json(raw),
                "secret_exposed": False,
            }
        except Exception as exc:  # pragma: no cover - live provider dependent
            return {
                "status": "http_error",
                "http_status": None,
                "response_size": 0,
                "error_type": type(exc).__name__,
                "json": {},
                "secret_exposed": False,
            }


def _inventory_item_body(payload: dict[str, Any]) -> dict[str, Any]:
    listing = payload.get("listing") if isinstance(payload.get("listing"), dict) else {}
    supplier = payload.get("supplier_facts") if isinstance(payload.get("supplier_facts"), dict) else {}
    assets = payload.get("asset_manifest") if isinstance(payload.get("asset_manifest"), dict) else {}
    body = {
        "availability": {"shipToLocationAvailability": {"quantity": _int(listing.get("quantity"))}},
        "condition": _condition(str(listing.get("condition") or "")),
        "product": {
            "title": str(listing.get("title") or "").strip(),
            "description": _plain_text(listing.get("description_html") or listing.get("description") or ""),
            "aspects": _aspects(listing.get("item_specifics")),
            "imageUrls": _image_urls(assets.get("assets")),
        },
    }
    dimensions = supplier.get("package_dimensions_cm") if isinstance(supplier.get("package_dimensions_cm"), dict) else {}
    weight_g = _float(supplier.get("package_weight_g"))
    if dimensions and weight_g is not None:
        body["packageWeightAndSize"] = {
            "dimensions": {
                "height": _float(dimensions.get("height")),
                "length": _float(dimensions.get("length")),
                "width": _float(dimensions.get("width")),
                "unit": "CENTIMETER",
            },
            "weight": {"value": weight_g, "unit": "GRAM"},
        }
    return body


def _offer_body(payload: dict[str, Any], *, marketplace_id: str) -> dict[str, Any]:
    listing = payload.get("listing") if isinstance(payload.get("listing"), dict) else {}
    policies = payload.get("business_policies") if isinstance(payload.get("business_policies"), dict) else {}
    price = listing.get("price") if isinstance(listing.get("price"), dict) else {"value": listing.get("price"), "currency": "USD"}
    return {
        "sku": str(listing.get("sku") or "").strip(),
        "marketplaceId": marketplace_id,
        "format": "FIXED_PRICE",
        "availableQuantity": _int(listing.get("quantity")),
        "categoryId": str(listing.get("category_id") or "").strip(),
        "merchantLocationKey": str(listing.get("merchant_location_key") or "").strip(),
        "listingDescription": str(listing.get("description_html") or listing.get("description") or "").strip(),
        "listingPolicies": {
            "fulfillmentPolicyId": str(policies.get("fulfillment_policy_id") or "").strip(),
            "paymentPolicyId": str(policies.get("payment_policy_id") or "").strip(),
            "returnPolicyId": str(policies.get("return_policy_id") or "").strip(),
        },
        "pricingSummary": {
            "price": {
                "value": str(price.get("value") or "").strip(),
                "currency": str(price.get("currency") or "USD").strip() or "USD",
            }
        },
    }


def _find_publish_connection(connections: list[dict[str, Any]]) -> dict[str, Any] | None:
    for item in connections:
        if str(item.get("platform") or "").lower() != "ebay":
            continue
        if str(item.get("connection_type") or "").lower() != "oauth":
            continue
        scopes = [str(scope).lower() for scope in item.get("scopes", []) if str(scope).strip()]
        if any(scope.endswith("/sell.inventory") for scope in scopes):
            return item
    return None


def _exact_unpublished_draft_credential(
    *,
    connections: list[dict[str, Any]],
    secret_refs: list[dict[str, Any]],
    company_id: str,
    store_id: str,
) -> dict[str, Any] | None:
    """Resolve one callback-proven draft credential without a fallback secret."""

    if not company_id or not store_id:
        return None
    active_statuses = {"read_only_authorized", "draft_save_authorized", "publish_authorized"}
    active = [
        item
        for item in connections
        if str(item.get("platform") or "").lower() == "ebay"
        and str(item.get("connection_type") or "").lower() == "oauth"
        and str(item.get("status") or "") in active_statuses
    ]
    if len(active) != 1:
        return None
    connection = active[0]
    metadata = connection.get("metadata") if isinstance(connection.get("metadata"), dict) else {}
    scopes = connection.get("scopes") if isinstance(connection.get("scopes"), list) else []
    connection_id = str(connection.get("connection_id") or "")
    secret_ref_id = str(connection.get("secret_ref") or "")
    oauth_request_id = str(metadata.get("oauth_request_id") or "")
    seller_identity_hash = str(metadata.get("ebay_user_id_hash") or "")
    if not (
        connection_id
        and str(connection.get("company_id") or "") == company_id
        and str(connection.get("store_id") or "") == store_id
        and str(connection.get("status") or "") == "draft_save_authorized"
        and scopes == UNPUBLISHED_DRAFT_SCOPES
        and secret_ref_id
        and oauth_request_id
        and seller_identity_hash
        and str(metadata.get("confirmation_id") or "")
        and str(metadata.get("scope_profile") or "") == "seller_unpublished_draft"
        and str(metadata.get("authorization_kind") or "") == "unpublished_draft"
        and metadata.get("draft_save_scope_authorized") is True
        and metadata.get("publish_scope_authorized") is False
        and metadata.get("public_publish_enabled") is False
        and metadata.get("real_platform_writes_enabled") is False
        and str(metadata.get("credential_source") or "") == "jiejing_vault_secret_ref"
        and str(metadata.get("account_deletion_identity_mapping_status") or "") == "identity_mapping_ready"
        and metadata.get("secret_exposed") is False
    ):
        return None
    exact_secret_rows = [item for item in secret_refs if str(item.get("secret_ref") or "") == secret_ref_id]
    if len(exact_secret_rows) != 1:
        return None
    secret = exact_secret_rows[0]
    secret_metadata = secret.get("metadata") if isinstance(secret.get("metadata"), dict) else {}
    if not (
        str(secret.get("company_id") or "") == company_id
        and str(secret.get("store_id") or "") == store_id
        and str(secret.get("provider") or "").lower() == "ebay"
        and str(secret.get("purpose") or "").lower() == "ebay_refresh_token"
        and str(secret.get("status") or "") in {"local_secret_resolver_stored", "managed_vault_stored"}
        and str(secret_metadata.get("oauth_request_id") or "") == oauth_request_id
        and str(secret_metadata.get("credential_owner") or "") == "jiejing_saas_backend"
        and secret_metadata.get("secret_exposed") is False
    ):
        return None
    return {
        "connection": connection,
        "connection_id_sha256": hashlib.sha256(connection_id.encode("utf-8")).hexdigest(),
        "credential_ref_sha256": hashlib.sha256(secret_ref_id.encode("utf-8")).hexdigest(),
        "oauth_request_id_sha256": hashlib.sha256(oauth_request_id.encode("utf-8")).hexdigest(),
        "seller_identity_sha256": hashlib.sha256(seller_identity_hash.encode("utf-8")).hexdigest(),
    }


def _validated_unpublished_draft_credential_boundary(
    *,
    credential_boundary: dict[str, Any],
    company_id: str,
    store_id: str,
) -> dict[str, Any] | None:
    """Validate a private repository resolver result without exposing raw bindings."""

    if not isinstance(credential_boundary, dict) or credential_boundary.get("ready") is not True:
        return None
    if (
        str(credential_boundary.get("contract_version") or "")
        != "2026-08-13-unpublished-draft-credential-v1"
        or str(credential_boundary.get("company_id") or "") != company_id
        or str(credential_boundary.get("store_id") or "") != store_id
        or credential_boundary.get("secret_exposed") is not False
    ):
        return None
    connection = credential_boundary.get("connection") if isinstance(credential_boundary.get("connection"), dict) else {}
    secret = credential_boundary.get("secret_reference") if isinstance(credential_boundary.get("secret_reference"), dict) else {}
    exact = _exact_unpublished_draft_credential(
        connections=[connection] if connection else [],
        secret_refs=[secret] if secret else [],
        company_id=company_id,
        store_id=store_id,
    )
    if not exact:
        return None
    expected = {
        "connection_id_sha256": exact["connection_id_sha256"],
        "credential_ref_sha256": exact["credential_ref_sha256"],
        "oauth_request_id_sha256": exact["oauth_request_id_sha256"],
        "seller_identity_sha256": exact["seller_identity_sha256"],
    }
    if any(str(credential_boundary.get(key) or "") != value for key, value in expected.items()):
        return None
    return exact


def _draft_payload_sha256(payload: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _inventory_location_blocked(status: str) -> dict[str, Any]:
    return {
        "status": status,
        "action_type": "create_ebay_inventory_location",
        "location_write_completed": False,
        "writes_to_ebay": False,
        "public_listing_created": False,
        "secret_exposed": False,
    }


def _exact_inventory_location_confirmation(
    *,
    confirmation: dict[str, Any],
    location_payload: dict[str, Any],
    required_status: str,
) -> bool:
    item = confirmation.get("item") if isinstance(confirmation.get("item"), dict) else {}
    stored_payload = item.get("location_payload") if isinstance(item.get("location_payload"), dict) else {}
    try:
        payload_sha256 = hashlib.sha256(_canonical_json_bytes(location_payload)).hexdigest()
        payload_exact = _canonical_json_bytes(stored_payload) == _canonical_json_bytes(location_payload)
    except (TypeError, ValueError):
        return False
    return bool(
        str(confirmation.get("status") or "") == required_status
        and str(confirmation.get("action_type") or "") == "create_ebay_inventory_location"
        and str(confirmation.get("runtime_run_id") or "") == "merchant_ebay_inventory_location_setup"
        and str(confirmation.get("company_id") or "")
        and str(confirmation.get("store_id") or "")
        and str(confirmation.get("confirmation_id") or "")
        and str(confirmation.get("task_id") or "")
        and str(item.get("source") or "") == "merchant_ebay_inventory_location_setup"
        and str(item.get("requested_step") or "") == "inventory_location_confirmation_gate"
        and str(item.get("company_id") or "") == str(confirmation.get("company_id") or "")
        and str(item.get("store_id") or "") == str(confirmation.get("store_id") or "")
        and str(item.get("merchant_location_key") or "") == str(location_payload.get("merchantLocationKey") or "")
        and str(item.get("location_payload_sha256") or "") == payload_sha256
        and payload_exact
        and item.get("writes_to_ebay_after_approval") is True
        and item.get("public_publish_enabled") is False
        and item.get("public_listing_created") is False
        and item.get("secret_exposed") is False
    )


def _is_exact_missing_inventory_location(result: dict[str, Any]) -> bool:
    body = result.get("json") if isinstance(result.get("json"), dict) else {}
    errors = body.get("errors") if isinstance(body.get("errors"), list) else []
    error = errors[0] if len(errors) == 1 and isinstance(errors[0], dict) else {}
    return bool(
        result.get("status") == "not_found"
        and result.get("http_status") == 404
        and str(error.get("errorId") or "") == "25805"
        and str(error.get("domain") or "") == "API_INVENTORY"
        and str(error.get("category") or "") == "REQUEST"
        and not str(error.get("subdomain") or "")
    )


def _is_exact_inventory_location_match(*, existing: dict[str, Any], expected: dict[str, Any]) -> bool:
    existing_location = existing.get("location") if isinstance(existing.get("location"), dict) else {}
    expected_location = expected.get("location") if isinstance(expected.get("location"), dict) else {}
    existing_address = existing_location.get("address") if isinstance(existing_location.get("address"), dict) else {}
    expected_address = expected_location.get("address") if isinstance(expected_location.get("address"), dict) else {}
    return bool(
        str(existing.get("merchantLocationKey") or "") == str(expected.get("merchantLocationKey") or "")
        and str(existing.get("name") or "") == str(expected.get("name") or "")
        and existing.get("locationTypes") == expected.get("locationTypes") == ["WAREHOUSE"]
        and str(existing_address.get("city") or "") == str(expected_address.get("city") or "")
        and str(existing_address.get("stateOrProvince") or "")
        == str(expected_address.get("stateOrProvince") or "")
        and str(existing_address.get("country") or "") == str(expected_address.get("country") or "")
    )


def _offer_snapshot_fingerprint(offers: list[Any]) -> str:
    safe = [item for item in offers if isinstance(item, dict)]
    return hashlib.sha256(_canonical_json_bytes(safe)).hexdigest()


def _expected_draft_claim_binding(*, prepared: _DraftPreparationState) -> dict[str, str]:
    binding = dict(prepared.credential_binding_items)
    return {
        "confirmation_id": prepared.confirmation_id,
        "company_id": prepared.company_id,
        "store_id": prepared.store_id,
        "action_type": "save_ebay_listing_draft",
        "task_id": prepared.task_id,
        "idempotency_key": prepared.idempotency_key,
        "marketplace_id": prepared.marketplace_id,
        "payload_sha256": prepared.payload_sha256,
        "preparation_sha256": prepared.preparation_sha256,
        "contract_version": binding.get("contract_version", ""),
        "connection_id_sha256": binding.get("connection_id_sha256", ""),
        "credential_ref_sha256": binding.get("credential_ref_sha256", ""),
        "oauth_request_id_sha256": binding.get("oauth_request_id_sha256", ""),
        "seller_identity_sha256": binding.get("seller_identity_sha256", ""),
    }


def _valid_draft_claim_capability(*, capability: Any, request: Any, prepared: _DraftPreparationState) -> bool:
    # Import locally to keep the adapter's module dependency one-way while
    # requiring the repository's opaque DB-backed capability type.  A dict or
    # look-alike object with ``consume`` methods must never authorize a write.
    from .repository import UnpublishedDraftClaimCapability

    if not (
        isinstance(capability, UnpublishedDraftClaimCapability)
        and getattr(capability, "_minted", False) is True
    ):
        return False
    claim_binding_reader = getattr(capability, "claim_binding", None)
    consume = getattr(capability, "consume", None)
    abort = getattr(capability, "abort", None)
    if not callable(claim_binding_reader) or not callable(consume) or not callable(abort):
        return False
    try:
        claim_binding = claim_binding_reader()
    except Exception:
        return False
    expected = _expected_draft_claim_binding(prepared=prepared)
    return bool(
        isinstance(claim_binding, dict)
        and all(str(claim_binding.get(key) or "") == str(value or "") for key, value in expected.items())
        and len(claim_binding) == len(expected)
        and str(getattr(request, "confirmation_id", "") or "") == prepared.confirmation_id
    )


def _valid_consumed_draft_execution_claim(
    *,
    claim: dict[str, Any],
    request: Any,
    prepared: _DraftPreparationState,
) -> bool:
    if not isinstance(claim, dict) or claim.get("external_execution_claimed") is not True:
        return False
    expected = _expected_draft_claim_binding(prepared=prepared)
    claim_binding = claim.get("external_execution_claim_binding")
    return bool(
        isinstance(claim_binding, dict)
        and claim.get("status") == "external_execution_processing_manual_reconcile"
        and all(str(claim_binding.get(key) or "") == str(value or "") for key, value in expected.items())
        and len(claim_binding) == len(expected)
        and str(getattr(request, "confirmation_id", "") or "") == prepared.confirmation_id
    )


def _first_secret_ref(secret_refs: list[dict[str, Any]]) -> str | None:
    for item in secret_refs:
        if str(item.get("provider") or "").lower() == "ebay" and str(item.get("purpose") or "").lower() == "ebay_refresh_token":
            return str(item.get("secret_ref") or "") or None
    return None


def _base_url(settings: SaaSSettings) -> str:
    return "https://api.sandbox.ebay.com" if settings.ebay_oauth_environment == "sandbox" else "https://api.ebay.com"


def _condition(value: str) -> str:
    text = value.strip().upper().replace(" ", "_")
    if text in {"NEW", "USED", "LIKE_NEW", "VERY_GOOD", "GOOD", "ACCEPTABLE"}:
        return text
    if value.strip().lower().startswith("new"):
        return "NEW"
    return text or "NEW"


def _aspects(value: Any) -> dict[str, list[str]]:
    if not isinstance(value, dict):
        return {}
    out: dict[str, list[str]] = {}
    source = value.get("fixed_common") if isinstance(value.get("fixed_common"), dict) else value
    for key, item in source.items():
        if isinstance(item, list):
            values = [str(part).strip() for part in item if str(part).strip()]
        else:
            values = [str(item).strip()] if str(item).strip() else []
        if values:
            out[str(key)] = values
    return out


def _image_urls(value: Any) -> list[str]:
    urls: list[str] = []
    for item in value if isinstance(value, list) else []:
        if isinstance(item, str):
            url = item.strip()
        elif isinstance(item, dict):
            url = str(item.get("url") or item.get("src") or "").strip()
        else:
            url = ""
        if url.startswith("http://") or url.startswith("https://"):
            urls.append(url)
    return urls


def _int(value: Any) -> int | None:
    try:
        if isinstance(value, str) and any(marker in value for marker in ("-", "~", "to")):
            return None
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return None


def _float(value: Any) -> float | None:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _money_float(value: Any) -> float | None:
    if isinstance(value, dict):
        return _float(value.get("value"))
    return _float(value)


def _calculated_contribution_profit(
    *,
    unit_price: float | None,
    procurement_cost: float | None,
    shipping_cost: float | None,
    ebay_fee: float | None,
    ad_budget: float | None,
    return_risk_reserve: float | None,
) -> float | None:
    values = [unit_price, procurement_cost, shipping_cost, ebay_fee, ad_budget, return_risk_reserve]
    if any(value is None for value in values):
        return None
    return round(float(unit_price or 0) - float(procurement_cost or 0) - float(shipping_cost or 0) - float(ebay_fee or 0) - float(ad_budget or 0) - float(return_risk_reserve or 0), 2)


def _duplicate_product_findings(
    *,
    payload: dict[str, Any],
    latest_execution_results: list[dict[str, Any]],
    recent_confirmations: list[dict[str, Any]],
) -> dict[str, Any]:
    listing = payload.get("listing") if isinstance(payload.get("listing"), dict) else {}
    assets = payload.get("asset_manifest") if isinstance(payload.get("asset_manifest"), dict) else {}
    current_sku = _normalized_key(listing.get("sku"))
    current_title = _normalized_text(listing.get("title"))
    current_images = {_normalized_url(url) for url in _image_urls(assets.get("assets"))}
    current_images.discard("")
    existing_draft = payload.get("existing_ebay_draft") if isinstance(payload.get("existing_ebay_draft"), dict) else {}
    source_execution_id = str(existing_draft.get("source_execution_id") or "").strip()
    source_confirmation_id = str(existing_draft.get("source_confirmation_id") or "").strip()
    source_draft_binding_valid = bool(
        source_execution_id
        and source_confirmation_id
        and str(existing_draft.get("offer_id") or "").strip()
        and _normalized_key(existing_draft.get("sku")) == current_sku
        and str(existing_draft.get("offer_status") or "").strip().upper() == "UNPUBLISHED"
        and existing_draft.get("public_listing_created") is False
    )
    blocking_matches: list[dict[str, Any]] = []
    review_matches: list[dict[str, Any]] = []

    for record in recent_confirmations[:50]:
        if source_draft_binding_valid and str(record.get("confirmation_id") or "").strip() == source_confirmation_id:
            continue
        item = record.get("item") if isinstance(record.get("item"), dict) else {}
        previous_payload = item.get("publish_payload") if isinstance(item.get("publish_payload"), dict) else {}
        previous_listing = previous_payload.get("listing") if isinstance(previous_payload.get("listing"), dict) else {}
        previous_assets = previous_payload.get("asset_manifest") if isinstance(previous_payload.get("asset_manifest"), dict) else {}
        source_id = str(record.get("confirmation_id") or item.get("source_confirmation_id") or "").strip()
        previous_sku = _normalized_key(previous_listing.get("sku"))
        previous_title = _normalized_text(previous_listing.get("title"))
        previous_images = {_normalized_url(url) for url in _image_urls(previous_assets.get("assets"))}
        previous_images.discard("")
        if current_sku and previous_sku and current_sku == previous_sku:
            blocking_matches.append({"match_type": "sku", "source": "confirmation", "source_id": source_id, "value": previous_listing.get("sku")})
        shared_images = sorted(current_images & previous_images)
        if shared_images:
            blocking_matches.append({"match_type": "image_url", "source": "confirmation", "source_id": source_id, "count": len(shared_images)})
        if _similar_text(current_title, previous_title):
            review_matches.append({"match_type": "similar_title", "source": "confirmation", "source_id": source_id})

    for record in latest_execution_results[:50]:
        if source_draft_binding_valid and str(record.get("execution_id") or "").strip() == source_execution_id:
            continue
        result = record.get("result") if isinstance(record.get("result"), dict) else record
        platform = result.get("platform_result") if isinstance(result.get("platform_result"), dict) else {}
        previous_sku = _normalized_key(platform.get("sku"))
        if current_sku and previous_sku and current_sku == previous_sku:
            blocking_matches.append({"match_type": "sku", "source": "execution_result", "source_id": record.get("execution_id") or record.get("task_id") or "", "value": platform.get("sku")})

    return {
        "blocking_matches": blocking_matches,
        "review_matches": review_matches,
        "checked_recent_confirmations": min(len(recent_confirmations), 50),
        "checked_execution_results": min(len(latest_execution_results), 50),
        "current_sku_present": bool(current_sku),
        "current_image_url_count": len(current_images),
    }


def _post_publish_cockpit_plan(*, listing: dict[str, Any], finance: dict[str, Any]) -> dict[str, Any]:
    sku = str(listing.get("sku") or "").strip()
    return {
        "status": "plan_ready" if sku else "blocked_missing_sku",
        "sku": sku,
        "review_windows": [
            {"after": "1h", "checks": ["曝光", "点击", "收藏", "客服风险", "是否需要补图"], "confirmation_required_for": ["改价", "补图", "暂停"]},
            {"after": "24h", "checks": ["曝光趋势", "点击率", "费用", "贡献毛利", "询单/售出"], "confirmation_required_for": ["改价", "库存", "广告预算"]},
            {"after": "7d", "checks": ["售出", "退货风险", "利润", "客服问题", "是否扩量"], "confirmation_required_for": ["下架", "扩库存", "调广告"]},
        ],
        "profit_fields_expected": ["price", "ebay_fee", "ad_budget", "shipping_cost", "procurement_cost", "return_risk_reserve", "exchange_rate"],
        "finance_snapshot_present": bool(finance),
        "real_changes_stay_confirmation_gated": True,
    }


def _failure_knowledge_base(execution_results: list[dict[str, Any]], *, sku: str) -> dict[str, Any]:
    error = _latest_platform_error(execution_results, sku=sku)
    if not error:
        return {
            "status": "ready_no_recent_platform_rejection",
            "rule_candidates": [],
            "next_preflight_rule": "",
            "permanent_audit_memory": True,
        }
    code = str(error.get("code") or "platform_error")
    return {
        "status": "rule_candidate_from_latest_platform_error",
        "latest_error": error,
        "rule_candidates": [
            {
                "rule_key": f"ebay_{code}",
                "source": "execution_result",
                "summary": "把这次 eBay 拒绝原因沉淀为下次发布体检规则。",
                "blocking_preflight": code in {"seller_listing_limit", "policy_violation", "category_restricted"},
            }
        ],
        "next_preflight_rule": f"preflight_should_check_{code}",
        "permanent_audit_memory": True,
    }


def _normalized_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9_-]+", "", str(value or "").strip().lower())


def _normalized_text(value: Any) -> str:
    text = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", str(value or "").strip().lower())
    return re.sub(r"\s+", " ", text).strip()


def _normalized_url(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    parsed = urllib.parse.urlparse(text)
    host = (parsed.netloc or "").lower()
    path = re.sub(r"/+", "/", parsed.path or "").rstrip("/")
    return f"{host}{path}".lower()


def _similar_text(left: str, right: str) -> bool:
    if not left or not right:
        return False
    if left == right:
        return True
    left_terms = {term for term in left.split() if len(term) >= 3}
    right_terms = {term for term in right.split() if len(term) >= 3}
    if len(left_terms | right_terms) < 4:
        return False
    return len(left_terms & right_terms) / max(1, len(left_terms | right_terms)) >= 0.72


def _ip_and_prohibited_findings(*, text_blob: str, brand: str) -> dict[str, Any]:
    text = str(text_blob or "").lower()
    brand_text = str(brand or "").strip().lower()
    watched_brands = [
        "apple",
        "nike",
        "adidas",
        "disney",
        "lego",
        "pokemon",
        "stanley",
        "dyson",
        "dewalt",
        "makita",
    ]
    prohibited_terms = [
        "counterfeit",
        "replica",
        "fake",
        "unauthorized logo",
        "vape",
        "tobacco",
        "weapon",
        "prescription",
        "medical cure",
    ]
    detected_brands = [term for term in watched_brands if re.search(rf"\b{re.escape(term)}\b", text)]
    detected_prohibited = [term for term in prohibited_terms if term in text]
    unbranded = brand_text in {"", "unbranded", "generic", "no brand"}
    blocking_terms = list(detected_prohibited)
    review_terms: list[str] = []
    if detected_brands and unbranded:
        blocking_terms.extend([f"unbranded_with_{term}" for term in detected_brands])
    elif detected_brands:
        review_terms.extend([f"brand_reference_{term}" for term in detected_brands])
    return {
        "blocking_terms": sorted(set(blocking_terms)),
        "review_terms": sorted(set(review_terms)),
        "brand": brand,
        "policy": "Use own text/images, verify brand rights, and only use compatibility wording when truthful and necessary.",
    }


def _gpsr_required(payload: dict[str, Any], *, listing: dict[str, Any]) -> bool:
    marketplace = str(payload.get("marketplace_id") or listing.get("marketplace_id") or "").upper()
    if marketplace in {"EBAY_DE", "EBAY_FR", "EBAY_IT", "EBAY_ES", "EBAY_IE", "EBAY_NL", "EBAY_BE", "EBAY_PL", "EBAY_AT"}:
        return True
    ships_to = payload.get("ships_to") if isinstance(payload.get("ships_to"), list) else []
    text = " ".join(str(item).upper() for item in ships_to)
    return any(marker in text for marker in ("EU", "EUROPE", "NORTHERN_IRELAND", "GB", "IE", "DE", "FR", "IT", "ES"))


def _account_health_readiness(
    *,
    payload: dict[str, Any],
    preflight_issues: list[dict[str, Any]],
    missing_fields: list[str],
) -> dict[str, Any]:
    health = payload.get("account_health") if isinstance(payload.get("account_health"), dict) else {}
    status = str(health.get("status") or "").strip().lower()
    selling_status = str(health.get("selling_status") or "").strip().lower()
    payout_status = str(health.get("payout_status") or "").strip().lower()
    restrictions = health.get("restrictions") if isinstance(health.get("restrictions"), list) else []
    restriction_text = " ".join(str(item).lower() for item in restrictions)
    issue_keys = {str(item.get("key") or "") for item in preflight_issues}
    missing_health = "account_health.status" in missing_fields or not status
    risky_terms = (
        "frozen",
        "freeze",
        "restricted",
        "restriction",
        "suspended",
        "limited",
        "limit",
        "hold",
        "payout_hold",
        "unverified",
        "blocked",
        "payment_hold",
        "below_standard",
        "unknown",
    )
    risky = (
        "account_health.status" in issue_keys
        or any(term in status for term in risky_terms)
        or any(term in selling_status for term in risky_terms)
        or any(term in payout_status for term in risky_terms)
        or any(term in restriction_text for term in risky_terms)
    )
    details = {
        "status": status or None,
        "selling_status": selling_status or None,
        "payout_status": payout_status or None,
        "restriction_count": len(restrictions),
        "restrictions": [str(item) for item in restrictions[:10]],
        "incident_mode": bool(missing_health or risky),
        "allowed_when_blocked": ["diagnostics", "evidence_package", "read_only_sync"],
        "blocked_real_actions": ["publish", "revise_price", "change_inventory", "refund", "ads", "policy_change"],
    }
    if missing_health:
        return {
            "status": "blocked",
            "blocking": True,
            "summary": "还没有账号健康快照；不能在看不见冻结、受限、付款冻结或额度风险时继续真实发布。",
            "details": details,
        }
    if risky:
        return {
            "status": "blocked",
            "blocking": True,
            "summary": "账号健康存在冻结、受限、付款冻结、额度或验证风险；进入事故模式，只允许诊断和证据包，不允许真实写入。",
            "details": details,
        }
    return {
        "status": "passed",
        "blocking": False,
        "summary": "账号健康快照显示可继续发布体检；真实发布仍必须进入决策中心确认。",
        "details": details,
    }


def _plain_text(value: Any) -> str:
    text = str(value or "")
    text = re.sub(r"(?is)<(br|/p|/li|/h[1-6])\b[^>]*>", "\n", text)
    text = re.sub(r"(?is)<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s+", "\n", text)
    return text.strip()


def _add_check(
    checks: list[dict[str, Any]],
    *,
    key: str,
    label: str,
    status: str,
    summary: str,
    blocking: bool,
    details: dict[str, Any] | None = None,
) -> None:
    source_records = _publish_check_source_records(key, details or {})
    fix_action = _publish_check_fix_action(key, blocking=blocking)
    checks.append(
        {
            "key": key,
            "label": label,
            "status": status,
            "summary": summary,
            "blocking": bool(blocking),
            "details": details or {},
            "source_records": source_records,
            "fix_action": fix_action,
            "confirmation_gate": _publish_check_confirmation_gate(key, blocking=blocking),
            "frontend_gets_token": False,
            "secret_exposed": False,
        }
    )


def _publish_check_source_records(key: str, details: dict[str, Any]) -> list[dict[str, Any]]:
    source_map = {
        "account_health_gate": ["official_ebay_packet", "account_health_snapshot"],
        "field_completeness": ["execution_preflight", "merchant_input"],
        "category_match": ["execution_preflight", "ebay_category_rules", "merchant_input"],
        "business_policies": ["official_ebay_packet", "merchant_input"],
        "inventory_location": ["official_ebay_packet", "merchant_input"],
        "package_facts": ["merchant_input"],
        "asset_reachability": ["merchant_input", "public_asset_urls"],
        "new_product_duplicate_guard": ["confirmation_history", "execution_results"],
        "item_specifics_quality": ["merchant_input", "ebay_category_rules"],
        "ip_vero_and_claims": ["policy_screening", "merchant_input"],
        "gpsr_regulatory_fields": ["regulatory_screening", "merchant_input"],
        "price_quantity_exposure": ["finance_records", "merchant_input"],
        "profit_and_fee_sanity": ["finance_records", "merchant_input"],
        "inventory_api_lifecycle": ["confirmation_center", "inventory_api_contract"],
    }
    source_types = source_map.get(str(key or ""), ["backend_preflight"])
    details = details if isinstance(details, dict) else {}
    return [
        {
            "source_type": source_type,
            "source_id": _source_record_id(source_type, details),
            "trust_boundary": "backend_sanitized_evidence",
            "raw_secret_visible": False,
            "frontend_gets_token": False,
            "secret_exposed": False,
        }
        for source_type in source_types
    ]


def _source_record_id(source_type: str, details: dict[str, Any]) -> str:
    if source_type == "official_ebay_packet":
        return "latest_sanitized_packet"
    if source_type == "account_health_snapshot":
        return "account_health"
    if source_type == "ebay_category_rules":
        return str(details.get("category_id") or "category_rules")
    if source_type == "confirmation_history":
        return f"confirmations:{int(details.get('checked_recent_confirmations') or 0)}"
    if source_type == "execution_results":
        return f"execution_results:{int(details.get('checked_execution_results') or 0)}"
    if source_type == "public_asset_urls":
        return f"assets:{int(details.get('image_url_count') or 0)}"
    if source_type == "finance_records":
        return "finance_review"
    return source_type


def _publish_check_fix_action(key: str, *, blocking: bool) -> dict[str, Any]:
    action_map = {
        "account_health_gate": ("open-connect", "Review account health", "settings.account"),
        "field_completeness": ("focus-publish-intake", "Fill missing publish fields", "product.publish_intake"),
        "category_match": ("focus-publish-intake", "Fix eBay category", "product.publish_intake"),
        "business_policies": ("focus-publish-intake", "Add business policies", "product.publish_intake"),
        "inventory_location": ("focus-publish-intake", "Add inventory location", "product.publish_intake"),
        "package_facts": ("focus-publish-intake", "Add package facts", "product.publish_intake"),
        "asset_reachability": ("focus-publish-intake", "Replace or upload assets", "product.assets"),
        "new_product_duplicate_guard": ("focus-publish-intake", "Use fresh SKU and assets", "product.publish_intake"),
        "item_specifics_quality": ("focus-publish-intake", "Complete item specifics", "product.publish_intake"),
        "ip_vero_and_claims": ("focus-publish-intake", "Remove IP or policy risk", "product.policy_review"),
        "gpsr_regulatory_fields": ("focus-publish-intake", "Add regulatory fields", "product.regulatory"),
        "price_quantity_exposure": ("focus-publish-intake", "Review price and quantity", "product.finance"),
        "profit_and_fee_sanity": ("focus-publish-intake", "Review profit inputs", "product.finance"),
        "inventory_api_lifecycle": ("open-confirm", "Review post-publish lifecycle", "confirmations"),
    }
    action, label, target = action_map.get(str(key or ""), ("focus-publish-intake", "Fix publish intake", "product.publish_intake"))
    if not blocking:
        action, label, target = "open-confirm", "Review in decision center", "confirmations"
    return {
        "action": action,
        "label": label,
        "target": target,
        "requires_human": True,
        "can_trigger_ebay_oauth": False,
        "can_trigger_real_write": False,
        "can_trigger_payment": False,
        "secret_exposed": False,
    }


def _publish_check_confirmation_gate(key: str, *, blocking: bool) -> dict[str, Any]:
    return {
        "action_type": "publish_listing",
        "check_key": key,
        "blocking": bool(blocking),
        "requires_confirmation_center": True,
        "real_write_allowed_without_confirmation": False,
        "decision_center_required": True,
        "secret_exposed": False,
    }


def _publish_health_traffic_light_report(checks: list[dict[str, Any]], *, preflight: dict[str, Any]) -> dict[str, Any]:
    red = [item for item in checks if item.get("blocking")]
    yellow = [
        item
        for item in checks
        if not item.get("blocking") and str(item.get("status") or "") in {"needs_attention", "waiting", "missing"}
    ]
    green = [item for item in checks if not item.get("blocking") and item not in yellow]
    decision = "green_ready_for_confirmation"
    if red:
        decision = "red_blocked"
    elif yellow or preflight.get("status") != "ready_for_platform_adapter":
        decision = "yellow_review_required"
    return {
        "contract_version": "2026-06-18-publish-health-traffic-light",
        "decision": decision,
        "red_count": len(red),
        "yellow_count": len(yellow),
        "green_count": len(green),
        "total_count": len(checks),
        "can_enter_confirmation_center": not bool(red),
        "requires_confirmation_center": True,
        "real_write_allowed_without_confirmation": False,
        "red_checks": [_traffic_light_check_summary(item) for item in red],
        "yellow_checks": [_traffic_light_check_summary(item) for item in yellow],
        "green_checks": [_traffic_light_check_summary(item) for item in green[:6]],
        "secret_exposed": False,
    }


def _traffic_light_check_summary(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "key": item.get("key"),
        "label": item.get("label"),
        "status": item.get("status"),
        "summary": item.get("summary"),
        "blocking": bool(item.get("blocking")),
        "source_records": item.get("source_records") or [],
        "fix_action": item.get("fix_action") or {},
        "confirmation_gate": item.get("confirmation_gate") or {},
    }


def _publish_readiness_evidence_packet(checks: list[dict[str, Any]], *, preflight: dict[str, Any]) -> dict[str, Any]:
    return {
        "contract_version": "2026-06-19-backend-publish-preflight-evidence",
        "check_count": len(checks),
        "blocking_check_count": len([item for item in checks if item.get("blocking")]),
        "checks_have_source_records": all(bool(item.get("source_records")) for item in checks),
        "checks_have_fix_actions": all(bool(item.get("fix_action")) for item in checks),
        "confirmation_center_path": "/confirmations",
        "preflight_status": preflight.get("status"),
        "creates_confirmation_only": True,
        "creates_real_write": False,
        "requires_confirmation_center": True,
        "real_write_allowed_without_confirmation": False,
        "frontend_gets_token": False,
        "runtime_gets_token": False,
        "secret_exposed": False,
    }


def _latest_platform_error(execution_results: list[dict[str, Any]], *, sku: str) -> dict[str, Any] | None:
    sku = str(sku or "").strip()
    for record in execution_results:
        result = record.get("result") if isinstance(record.get("result"), dict) else record
        platform_sku = str((result.get("platform_result") or {}).get("sku") or "") if isinstance(result.get("platform_result"), dict) else ""
        steps = result.get("steps", []) if isinstance(result.get("steps"), list) else []
        if sku and platform_sku and sku != platform_sku:
            continue
        if sku and not platform_sku and not _steps_reference_sku(steps, sku):
            continue
        for step in steps:
            error = step.get("platform_error") if isinstance(step, dict) else None
            if not isinstance(error, dict):
                continue
            if error.get("code") == "seller_listing_limit":
                return {
                    "error_id": error.get("error_id"),
                    "code": error.get("code") or "seller_listing_limit",
                    "message": error.get("message"),
                    "step": step.get("step"),
                }
    return None


def _steps_reference_sku(steps: list[Any], sku: str) -> bool:
    if not sku:
        return False
    for step in steps:
        if not isinstance(step, dict):
            continue
        path = str(step.get("path") or "")
        if sku in path:
            return True
    return False


def _recovery_result(
    status: str,
    *,
    sku: str,
    checks: list[dict[str, Any]],
    safe_to_retry: bool,
    blocked_by: list[Any] | None = None,
) -> dict[str, Any]:
    return {
        "status": status,
        "action_type": "publish_listing",
        "sku": sku,
        "inventory_item_found": False,
        "offer_count": 0,
        "published_offer": {},
        "safe_to_retry_publish": bool(safe_to_retry),
        "recommended_action": "fix_connection_or_payload",
        "checks": checks,
        "blocked_by": [str(item) for item in blocked_by or []],
        "cleanup_plan": _cleanup_plan(sku=sku, published_offer={}, offer_count=0, inventory_found=False),
        "access_token_returned_to_frontend": False,
        "access_token_returned_to_runtime": False,
        "raw_response_stored": False,
        "secret_exposed": False,
    }


def _published_offer(offers: list[Any]) -> dict[str, Any]:
    for item in offers:
        if not isinstance(item, dict):
            continue
        listing = item.get("listing") if isinstance(item.get("listing"), dict) else {}
        listing_id = str(item.get("listingId") or item.get("listing_id") or listing.get("listingId") or "").strip()
        listing_status = str(item.get("listingStatus") or item.get("status") or listing.get("status") or "").strip()
        if listing_id or listing_status.upper() in {"PUBLISHED", "ACTIVE"}:
            return {
                "offer_id": str(item.get("offerId") or item.get("offer_id") or "").strip(),
                "listing_id": listing_id,
                "listing_status": listing_status,
            }
    return {}


def _unpublished_offer(offers: list[Any], *, marketplace_id: str) -> dict[str, Any]:
    target_marketplace = str(marketplace_id or "").strip().upper()
    for item in offers:
        if not isinstance(item, dict):
            continue
        offer_id = str(item.get("offerId") or item.get("offer_id") or "").strip()
        listing = item.get("listing") if isinstance(item.get("listing"), dict) else {}
        listing_id = str(item.get("listingId") or item.get("listing_id") or listing.get("listingId") or "").strip()
        listing_status = str(item.get("listingStatus") or item.get("status") or listing.get("status") or "").strip().upper()
        offer_marketplace = str(item.get("marketplaceId") or item.get("marketplace_id") or "").strip().upper()
        if not offer_id or listing_id or listing_status in {"PUBLISHED", "ACTIVE"}:
            continue
        if target_marketplace and offer_marketplace and offer_marketplace != target_marketplace:
            continue
        return {
            "offer_id": offer_id,
            "listing_status": listing_status or "UNPUBLISHED",
            "marketplace_id": offer_marketplace or target_marketplace,
        }
    return {}


def _cleanup_plan(*, sku: str, published_offer: dict[str, Any], offer_count: int, inventory_found: bool) -> dict[str, Any]:
    operations: list[dict[str, Any]] = []
    listing_id = str((published_offer or {}).get("listing_id") or "").strip()
    offer_id = str((published_offer or {}).get("offer_id") or "").strip()
    if listing_id:
        operations.append({"operation": "end_listing", "listing_id": listing_id, "writes_to_ebay": True})
    if offer_id:
        operations.append({"operation": "delete_offer", "offer_id": offer_id, "writes_to_ebay": True})
    elif offer_count:
        operations.append({"operation": "inspect_and_delete_offers_by_sku", "sku": sku, "writes_to_ebay": True})
    if inventory_found or sku:
        operations.append({"operation": "delete_inventory_item", "sku": sku, "writes_to_ebay": True})
    return {
        "status": "plan_only",
        "confirmation_required": True,
        "reason": "Cleaning a live test listing changes eBay state and must pass the confirmation center.",
        "operations": operations,
        "secret_exposed": False,
    }


def _blocked(status: str, blockers: list[Any], *, preflight: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "status": status,
        "action_type": "publish_listing",
        "message": "eBay publish is blocked before any platform write.",
        "blocked_by": [str(item) for item in blockers],
        "audit": {
            "preflight": preflight or {},
            "real_execution": {
                "published_to_ebay": False,
                "procurement_paid": False,
                "refund_executed": False,
                "ad_budget_changed": False,
                "store_policy_changed": False,
            },
            "access_token_returned_to_frontend": False,
            "access_token_returned_to_runtime": False,
        },
        "secret_exposed": False,
    }


def _draft_blocked(status: str, blockers: list[Any], *, preflight: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "status": status,
        "action_type": "save_ebay_listing_draft",
        "message": "eBay draft save is blocked before any platform write.",
        "blocked_by": [str(item) for item in blockers],
        "audit": {
            "preflight": preflight or {},
            "real_execution": {
                "ebay_draft_saved": False,
                "published_to_ebay": False,
                "procurement_paid": False,
                "refund_executed": False,
                "ad_budget_changed": False,
                "store_policy_changed": False,
            },
            "access_token_returned_to_frontend": False,
            "access_token_returned_to_runtime": False,
        },
        "secret_exposed": False,
    }


def _cleanup_blocked(status: str, blockers: list[Any], *, preflight: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "status": status,
        "action_type": "cleanup_test_listing",
        "message": "eBay test listing cleanup is blocked before any platform write.",
        "blocked_by": [str(item) for item in blockers],
        "audit": {
            "preflight": preflight or {},
            "real_execution": {
                "cleanup_test_listing": False,
                "published_to_ebay": False,
                "procurement_paid": False,
                "refund_executed": False,
                "ad_budget_changed": False,
                "store_policy_changed": False,
            },
            "access_token_returned_to_frontend": False,
            "access_token_returned_to_runtime": False,
        },
        "secret_exposed": False,
    }


def _cleanup_write_result(
    status: str,
    message: str,
    steps: list[dict[str, Any]],
    *,
    preflight: dict[str, Any],
) -> dict[str, Any]:
    return {
        "status": status,
        "action_type": "cleanup_test_listing",
        "message": message,
        "steps": steps,
        "audit": {
            "preflight": preflight,
            "real_execution": {
                "cleanup_test_listing": False,
                "published_to_ebay": False,
                "procurement_paid": False,
                "refund_executed": False,
                "ad_budget_changed": False,
                "store_policy_changed": False,
            },
            "access_token_returned_to_frontend": False,
            "access_token_returned_to_runtime": False,
            "raw_response_stored": False,
        },
        "secret_exposed": False,
    }


def _write_result(
    status: str,
    message: str,
    steps: list[dict[str, Any]],
    *,
    preflight: dict[str, Any],
    platform_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    safe_platform_result = platform_result or {}
    return {
        "status": status,
        "action_type": "publish_listing",
        "message": message,
        "steps": steps,
        "platform_result": safe_platform_result,
        "audit": {
            "preflight": preflight,
            "real_execution": {
                "published_to_ebay": False,
                "procurement_paid": False,
                "refund_executed": False,
                "ad_budget_changed": False,
                "store_policy_changed": False,
            },
            "access_token_returned_to_frontend": False,
            "access_token_returned_to_runtime": False,
            "raw_response_stored": False,
            "platform_result": safe_platform_result,
        },
        "secret_exposed": False,
    }


def _safe_ebay_kyc_checks(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw_checks = payload.get("kycChecks") if isinstance(payload.get("kycChecks"), list) else []
    checks: list[dict[str, Any]] = []
    for raw in raw_checks[:10]:
        if not isinstance(raw, dict):
            continue
        safe = {
            "data_required": str(raw.get("dataRequired") or "").strip()[:80],
            "alert": str(raw.get("alert") or "").strip()[:240],
            "detail": str(raw.get("detailMessage") or "").strip()[:480],
            "due_date": str(raw.get("dueDate") or "").strip()[:80],
            "remedy_available": bool(raw.get("remedyUrl")),
        }
        checks.append({key: value for key, value in safe.items() if value not in ("", None)})
    return checks


def _draft_write_result(
    status: str,
    message: str,
    steps: list[dict[str, Any]],
    *,
    preflight: dict[str, Any],
    platform_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "status": status,
        "action_type": "save_ebay_listing_draft",
        "message": message,
        "steps": steps,
        "platform_result": platform_result or {},
        "audit": {
            "preflight": preflight,
            "real_execution": {
                "ebay_draft_saved": False,
                "published_to_ebay": False,
                "procurement_paid": False,
                "refund_executed": False,
                "ad_budget_changed": False,
                "store_policy_changed": False,
            },
            "access_token_returned_to_frontend": False,
            "access_token_returned_to_runtime": False,
            "raw_response_stored": False,
        },
        "secret_exposed": False,
    }


def _audit(*, request: Any, preflight: dict[str, Any], real_execution: dict[str, bool], platform_result: dict[str, Any]) -> dict[str, Any]:
    return {
        "user_id": getattr(request, "user_id", None),
        "company_id": getattr(request, "company_id", None),
        "store_id": getattr(request, "store_id", None),
        "platform": getattr(request, "platform", "ebay"),
        "confirmation_id": getattr(request, "confirmation_id", None),
        "confirmed_by": getattr(request, "confirmed_by", None),
        "confirmed_at": getattr(request, "confirmed_at", None),
        "idempotency_key_present": bool(getattr(request, "idempotency_key", None) or getattr(request, "payload", {}).get("idempotency_key")),
        "execution_mode": (
            "ebay_inventory_draft_save_adapter"
            if str(getattr(request, "action_type", "") or "") in {"save_ebay_listing_draft", "save_ebay_draft"}
            else "ebay_inventory_publish_adapter"
        ),
        "platform_adapter_called": True,
        "preflight": preflight,
        "real_execution": real_execution,
        "platform_result": platform_result,
    }


def _step_summary(name: str, path: str, result: dict[str, Any]) -> dict[str, Any]:
    summary = {
        "step": name,
        "path": path,
        "http_status": result.get("http_status"),
        "status": result.get("status"),
        "response_size": result.get("response_size"),
        "error_type": result.get("error_type"),
        "raw_response_stored": False,
    }
    platform_error = _safe_platform_error(result.get("json"))
    if platform_error:
        summary["platform_error"] = platform_error
    return summary


def _normalize_missing_offer_inspection(result: dict[str, Any]) -> dict[str, Any]:
    """Treat only eBay's exact new-SKU/no-offer response as an empty offer set."""
    if result.get("http_status") != 404 or result.get("status") not in {"http_error", "not_found"}:
        return result
    payload = result.get("json")
    if not isinstance(payload, dict):
        return result
    errors = payload.get("errors")
    if not isinstance(errors, list) or len(errors) != 1 or not isinstance(errors[0], dict):
        return result
    error = errors[0]
    if (
        str(error.get("errorId") or "") != "25713"
        or error.get("domain") != "API_INVENTORY"
        or error.get("subdomain") != "Selling"
        or error.get("category") != "Request"
    ):
        return result
    normalized = dict(result)
    normalized.update(
        {
            "status": "ok",
            "json": {"offers": []},
            "normalized_outcome": "sku_has_no_offer",
        }
    )
    return normalized


def _safe_platform_error(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    errors = value.get("errors") if isinstance(value.get("errors"), list) else []
    first = next((item for item in errors if isinstance(item, dict)), None)
    if not first:
        return {}
    message = _plain_text(first.get("message") or "")[:700]
    long_message = _plain_text(first.get("longMessage") or "")[:700]
    error = {
        "error_id": first.get("errorId"),
        "code": _platform_error_code(first.get("errorId"), message),
        "domain": first.get("domain"),
        "category": first.get("category"),
        "message": message,
    }
    if long_message and long_message != message:
        error["long_message"] = long_message
    parameters = _safe_platform_parameters(first.get("parameters"))
    if parameters:
        error["parameters"] = parameters
    return error


def _platform_error_code(error_id: Any, message: str) -> str:
    text = str(message or "").lower()
    if "item specific" in text and ("missing" in text or "required" in text or "add" in text):
        return "missing_item_specific"
    if "exceed" in text and "amount" in text and "list" in text:
        return "seller_listing_limit"
    if str(error_id) == "25002" and "limit" in text and ("listing" in text or "amount" in text):
        return "seller_listing_limit"
    if "policy" in text:
        return "business_policy_error"
    if "location" in text or "merchantlocationkey" in text:
        return "inventory_location_error"
    if "category" in text:
        return "category_error"
    return "platform_error"


def _safe_platform_parameters(value: Any) -> list[dict[str, str]]:
    params: list[dict[str, str]] = []
    for item in value if isinstance(value, list) else []:
        if not isinstance(item, dict):
            continue
        name = _plain_text(item.get("name") or item.get("paramName") or "")[:80]
        raw_value = _plain_text(item.get("value") or item.get("paramValue") or "")[:500]
        if name or raw_value:
            params.append({"name": name, "value": raw_value})
        if len(params) >= 5:
            break
    return params


def _safe_headers(headers: dict[str, str]) -> dict[str, str]:
    return {key: value for key, value in headers.items() if key.lower() in {"content-type", "x-ebay-c-request-id", "x-ebay-c-version"}}


def _safe_error_json(raw: bytes) -> dict[str, Any]:
    try:
        data = json.loads(raw.decode("utf-8")) if raw else {}
        if not isinstance(data, dict):
            return {}
        return {
            key: value
            for key, value in data.items()
            if str(key).lower() not in {"access_token", "refresh_token", "authorization"}
        }
    except Exception:
        return {}
