"""Workflow templates that turn SaaS goals into JiejingTask queues."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .merchant_profile import HIGH_RISK_CONFIRMATION_ACTIONS, MerchantOperatingProfile, build_merchant_profile
from .models import now_iso


TASK_VERSION = "2026-05-14"

DEFAULT_CONFIRMATION_ACTIONS = list(HIGH_RISK_CONFIRMATION_ACTIONS)

DEFAULT_SOURCE_TYPES = [
    "official_api",
    "official_page",
    "public_page",
    "merchant_provided",
    "manual_input",
    "screenshot_or_video",
    "tool_estimate",
    "ai_inference",
    "runtime_market_packet",
    "restricted_unavailable",
    "runtime_sanitized_knowledge",
]

EXECUTION_BOUNDARY = {
    "published_to_ebay": False,
    "procurement_paid": False,
    "refund_executed": False,
    "ad_budget_changed": False,
    "store_policy_changed": False,
}


@dataclass(slots=True)
class ProductWorkflowRequest:
    product: str
    merchant_goal: str
    project_id: str = ""
    stage: str = "store_opened"
    platform: str = "ebay"
    user_id: str = "user_demo"
    company_id: str = "company_demo"
    store_id: str = "store_demo_northvalesource"
    marketplace: str = "eBay US"
    source_mode: str = "manual_or_1688"
    notes: str = ""
    market_probe_inputs: dict[str, Any] | None = None
    ebay_read_only_probe: dict[str, Any] | None = None
    public_search_probe: dict[str, Any] | None = None
    cross_platform_reference_probe: dict[str, Any] | None = None
    sourcing_availability_probe: dict[str, Any] | None = None
    logistics_estimate_probe: dict[str, Any] | None = None
    listing_metadata_probe: dict[str, Any] | None = None
    media_generation_probe: dict[str, Any] | None = None
    merchant_profile: dict[str, Any] | MerchantOperatingProfile | None = None


WORKFLOW_STEPS = [
    (
        "ceo.intake",
        None,
        60,
        "AI CEO receives merchant goal and splits the work.",
        ["merchant_goal", "merchant_stage", "risk_boundary", "task_breakdown", "next_tasks"],
        "success",
    ),
    (
        "market.data_packet",
        "ceo.intake",
        120,
        "Organize market source status before judgment.",
        ["source_health", "ebay_signal", "public_search_signal", "cross_platform_reference", "unavailable_sources"],
        "success",
    ),
    (
        "market.report",
        "market.data_packet",
        180,
        "Market manager prepares product/category report.",
        [
            "category_overview",
            "buyer_profile",
            "ebay_price_bands",
            "competitor_top5",
            "buyer_pain_points",
            "keywords",
            "differentiation",
            "pricing_direction",
            "risk_assessment",
            "conclusion_next_step",
        ],
        "partial_success",
    ),
    (
        "source.match",
        "market.report",
        150,
        "Match sourcing route and supplier facts.",
        ["source_route", "supplier_candidates", "cost_inputs", "package_inputs", "supplier_questions", "procurement_boundary"],
        "blocked_confirmation_required",
    ),
    (
        "listing.package",
        "source.match",
        180,
        "Product manager prepares eBay listing package.",
        [
            "sku",
            "title",
            "subtitle_notice",
            "category_id",
            "condition",
            "format",
            "price",
            "quantity",
            "item_specifics",
            "description_html",
            "pictures_required",
            "video_required",
            "package_weight",
            "package_dimensions",
            "business_policies",
            "publish_blockers",
        ],
        "blocked_missing_input",
    ),
    (
        "asset.brief",
        "listing.package",
        150,
        "Create media task package for image, detail page, and video.",
        ["image_plan", "detail_page_plan", "video_plan", "asset_settings", "claim_risk", "media_manifest_status"],
        "partial_success",
    ),
    (
        "customer.learn_product",
        "asset.brief",
        120,
        "Customer-service learns the product file before auto replies.",
        ["product_service_file", "buyer_question_map", "faq", "reply_boundary", "auto_reply_templates", "escalation_rules"],
        "success",
    ),
    (
        "finance.review",
        "customer.learn_product",
        150,
        "Finance and fulfillment final check.",
        ["cost_table", "net_profit_money", "logistics_route", "subscription_allocation", "return_reserve", "risk_notes", "next_action"],
        "blocked_missing_input",
    ),
    (
        "confirmation.package",
        "finance.review",
        120,
        "Collect high-risk actions into confirmation center.",
        ["allowed_auto_actions", "default_rule_actions", "every_time_confirm_actions", "blocked_actions", "missing_facts"],
        "blocked_confirmation_required",
    ),
    (
        "ceo.final_report",
        "confirmation.package",
        90,
        "AI CEO summarizes the closed loop.",
        ["current_status", "source_health", "reports_ready", "publish_lock", "next_minimum_action"],
        "success",
    ),
    (
        "owner.review",
        "ceo.final_report",
        90,
        "Owner review captures Runtime and SaaS improvements.",
        ["runtime_findings", "saas_findings", "hermes_findings", "next_improvements"],
        "success",
    ),
]


def build_product_workflow(request: ProductWorkflowRequest | dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(request, dict):
        request = ProductWorkflowRequest(
            product=str(request.get("product") or "Untitled eBay product"),
            merchant_goal=str(request.get("merchant_goal") or "Run a Jiejing eBay product workflow."),
            project_id=str(request.get("project_id") or ""),
            stage=str(request.get("stage") or "store_opened"),
            platform=str(request.get("platform") or "ebay"),
            user_id=str(request.get("user_id") or "user_demo"),
            company_id=str(request.get("company_id") or "company_demo"),
            store_id=str(request.get("store_id") or "store_demo_northvalesource"),
            marketplace=str(request.get("marketplace") or "eBay US"),
            source_mode=str(request.get("source_mode") or "manual_or_1688"),
            notes=str(request.get("notes") or ""),
            market_probe_inputs=request.get("market_probe_inputs") if isinstance(request.get("market_probe_inputs"), dict) else None,
            ebay_read_only_probe=request.get("ebay_read_only_probe") if isinstance(request.get("ebay_read_only_probe"), dict) else None,
            public_search_probe=request.get("public_search_probe") if isinstance(request.get("public_search_probe"), dict) else None,
            cross_platform_reference_probe=request.get("cross_platform_reference_probe")
            if isinstance(request.get("cross_platform_reference_probe"), dict)
            else None,
            sourcing_availability_probe=request.get("sourcing_availability_probe")
            if isinstance(request.get("sourcing_availability_probe"), dict)
            else None,
            logistics_estimate_probe=request.get("logistics_estimate_probe") if isinstance(request.get("logistics_estimate_probe"), dict) else None,
            listing_metadata_probe=request.get("listing_metadata_probe") if isinstance(request.get("listing_metadata_probe"), dict) else None,
            media_generation_probe=request.get("media_generation_probe") if isinstance(request.get("media_generation_probe"), dict) else None,
            merchant_profile=request.get("merchant_profile") if isinstance(request.get("merchant_profile"), dict) else None,
        )
    project_id = request.project_id or f"{_safe_id(request.product)}-{now_iso()[:10].replace('-', '')}"
    merchant_profile = _profile_for_request(request)
    task_ids: dict[str, str] = {}
    tasks: list[dict[str, Any]] = []
    for index, (task_type, parent_type, timeout, description, sections, expected_status) in enumerate(WORKFLOW_STEPS, start=1):
        task_id = f"{project_id}::{index:02d}::{task_type}"
        task_ids[task_type] = task_id
        parent_task_id = task_ids.get(parent_type) if parent_type else None
        tasks.append(
            {
                "task_id": task_id,
                "task_type": task_type,
                "task_version": TASK_VERSION,
                "user_id": request.user_id,
                "company_id": request.company_id,
                "store_id": request.store_id,
                "platform": request.platform,
                "stage": request.stage,
                "project_id": project_id,
                "parent_task_id": parent_task_id,
                "input": _input_for(task_type, request, expected_status, merchant_profile),
                "context": {
                    "sample_id": project_id,
                    "sample_name": f"{request.product} Jiejing generated workflow",
                    "sample_status": "runtime_generated_product_workflow",
                    "previous_task_id": parent_task_id,
                    "execution_boundary": dict(EXECUTION_BOUNDARY),
                    "merchant_operating_profile": merchant_profile.to_dict(),
                },
                "source_policy": {
                    "must_label_sources": True,
                    "allowed_source_types": DEFAULT_SOURCE_TYPES,
                    "ai_inference_rule": "AI inference must be labeled and cannot be presented as official platform data.",
                    "task_specific_note": _source_note_for(task_type),
                },
                "risk_policy": {
                    "confirmation_required_actions": merchant_profile.confirmation_required_actions,
                    "auto_allowed_actions": merchant_profile.auto_allowed_actions,
                    "blocked_actions": merchant_profile.blocked_actions,
                    "permission_level": merchant_profile.permission_level,
                    "risk_level": merchant_profile.risk_level,
                    "default_action": "hold",
                    "no_real_execution_in_demo": True,
                },
                "output_contract": {
                    "summary_required": True,
                    "merchant_readable": True,
                    "required_sections": sections,
                    "empty_output_allowed": False,
                },
                "timeout_seconds": timeout,
                "retry_policy": {
                    "max_retries": 2,
                    "split_on_timeout": True,
                    "split_strategy": "return partial result, preserve source records, and create smaller follow-up tasks",
                },
                "audit": {
                    "prepared_at": now_iso(),
                    "prepared_by": "jiejing_runtime.workflow_templates",
                    "description": description,
                },
            }
        )
    return tasks


def _profile_for_request(request: ProductWorkflowRequest) -> MerchantOperatingProfile:
    if isinstance(request.merchant_profile, MerchantOperatingProfile):
        return request.merchant_profile
    raw = dict(request.merchant_profile or {})
    raw.setdefault("merchantStage", request.stage)
    raw.setdefault("source_mode", request.source_mode)
    return build_merchant_profile(raw)


def _input_for(task_type: str, request: ProductWorkflowRequest, expected_status: str, merchant_profile: MerchantOperatingProfile) -> dict[str, Any]:
    data: dict[str, Any] = {
        "product": request.product,
        "merchant_goal": request.merchant_goal,
        "expected_status": expected_status,
        "notes": request.notes,
        "marketplace": request.marketplace,
        "source_mode": request.source_mode,
        "merchant_profile": merchant_profile.to_task_input(),
    }
    if task_type == "market.data_packet":
        data["must_collect"] = ["eBay official/read-only signal", "public search signal", "cross-platform reference", "source availability"]
        data["market_probe_inputs"] = request.market_probe_inputs or {}
        data["ebay_read_only_probe"] = request.ebay_read_only_probe or {}
        data["public_search_probe"] = request.public_search_probe or {}
        data["cross_platform_reference_probe"] = request.cross_platform_reference_probe or {}
        data["sourcing_availability_probe"] = request.sourcing_availability_probe or {}
        data["logistics_estimate_probe"] = request.logistics_estimate_probe or {}
    elif task_type == "market.report":
        data["report_level"] = "initial_or_data_enhanced_until_live_sources_confirmed"
        data["market_probe_inputs"] = request.market_probe_inputs or {}
        data["ebay_read_only_probe"] = request.ebay_read_only_probe or {}
        data["public_search_probe"] = request.public_search_probe or {}
        data["cross_platform_reference_probe"] = request.cross_platform_reference_probe or {}
        data["sourcing_availability_probe"] = request.sourcing_availability_probe or {}
        data["logistics_estimate_probe"] = request.logistics_estimate_probe or {}
    elif task_type == "source.match":
        data["supplier_facts_status"] = "pending_or_manual_input"
        data["allowed_source_routes"] = merchant_profile.source_routes
        data["sourcing_availability_probe"] = request.sourcing_availability_probe or {}
    elif task_type == "listing.package":
        data["listing_mode"] = "fixed_price"
        data["must_validate"] = ["category_id", "condition_values", "item_specifics", "business_policy_ids"]
        data["store_policy_mode"] = merchant_profile.store_policy_mode
        data["listing_metadata_probe"] = request.listing_metadata_probe or {}
    elif task_type == "asset.brief":
        data["media_state_rule"] = "task_package_before_actual_files_manifest"
        data["media_mode"] = merchant_profile.media_mode
        data["media_generation_probe"] = request.media_generation_probe or {}
    elif task_type == "customer.learn_product":
        data["automation_boundary"] = "low_risk_auto_reply_only_after_product_file"
        data["customer_service_mode"] = merchant_profile.customer_service_mode
    elif task_type == "finance.review":
        data["cost_rule"] = "money_numbers_required_not_percent_only"
        data["profit_floor"] = merchant_profile.profit_floor
        data["fee_mode"] = merchant_profile.fee_mode
        data["logistics_estimate_probe"] = request.logistics_estimate_probe or {}
    elif task_type == "confirmation.package":
        data["confirm_actions"] = merchant_profile.confirmation_required_actions
        data["auto_allowed_actions"] = merchant_profile.auto_allowed_actions
        data["blocked_actions"] = merchant_profile.blocked_actions
    return data


def _source_note_for(task_type: str) -> str:
    notes = {
        "market.report": "Market report must preserve source health and report level.",
        "source.match": "Supplier facts may use manual input or authorized source API; do not invent publish facts.",
        "listing.package": "eBay category and item specifics must be validated before real publish.",
        "asset.brief": "Do not claim actual generated files unless a manifest exists.",
        "customer.learn_product": "Customer service needs product file before auto replies.",
        "finance.review": "Final logistics quote and costs are required before publish confirmation.",
        "confirmation.package": "High-risk execution actions are held.",
    }
    return notes.get(task_type, "")


def _safe_id(value: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9]+", "-", value.lower()).strip("-")
    return text[:40] or "jiejing-product"
