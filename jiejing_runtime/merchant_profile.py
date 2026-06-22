"""Merchant operating profiles for Jiejing Runtime.

The profile is the customization layer. Runtime keeps one stable commerce
workflow, while each merchant can change operating preferences inside safe
boundaries: source route, fulfillment mode, risk appetite, media mode, customer
service automation, and confirmation rules.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


PROFILE_VERSION = "2026-05-14"

HIGH_RISK_CONFIRMATION_ACTIONS = [
    "oauth_scope_change",
    "publish_listing",
    "bulk_publish_listing",
    "change_price",
    "change_inventory",
    "ad_budget",
    "refund",
    "partial_refund",
    "procurement_payment",
    "cleanup_test_listing",
    "address_write",
    "policy_edit",
    "store_subscription",
    "sensitive_buyer_commitment",
]

LOW_RISK_AUTO_ACTIONS = [
    "read_only_import",
    "market_research_packet",
    "draft_report",
    "listing_draft",
    "asset_brief",
    "customer_learning_pack",
    "finance_estimate",
    "work_record",
]

STAGE_DEFAULTS: dict[str, dict[str, Any]] = {
    "newbie": {
        "operating_mode": "guided_first_product",
        "source_routes": ["1688_read_only_or_manual", "manual_link_image_table"],
        "fulfillment_mode": "supplier_or_domestic_forwarding",
        "automation_level": "guided_low_auto",
        "customer_service_mode": "draft_until_product_file_ready",
        "store_policy_mode": "guided_defaults_then_confirm",
        "workflow_focus": ["open_store", "connect_read_only", "first_product", "safe_publish_confirmation"],
    },
    "store_opened": {
        "operating_mode": "single_store_process_automation",
        "source_routes": ["1688_read_only_or_manual", "manual_link_image_table", "supplier_table"],
        "fulfillment_mode": "product_by_product",
        "automation_level": "balanced_auto",
        "customer_service_mode": "standard_reply_after_product_learning",
        "store_policy_mode": "reuse_authorized_store_policies",
        "workflow_focus": ["read_store_context", "listing_draft", "asset_package", "confirmation_center"],
    },
    "has_orders": {
        "operating_mode": "order_first_automation",
        "source_routes": ["existing_store_items", "1688_replenishment", "manual_supplier_facts"],
        "fulfillment_mode": "order_and_tracking_first",
        "automation_level": "service_sensitive_auto",
        "customer_service_mode": "auto_standard_reply_sensitive_hold",
        "store_policy_mode": "preserve_existing_policy_templates",
        "workflow_focus": ["orders", "customer_service", "logistics", "profit_review", "listing_improvement"],
    },
    "multi_store": {
        "operating_mode": "multi_store_guarded_bulk",
        "source_routes": ["1688_read_only_or_manual", "supplier_table", "store_by_store_policy"],
        "fulfillment_mode": "store_specific_rules",
        "automation_level": "batch_with_confirmation_gates",
        "customer_service_mode": "shared_inbox_with_store_rules",
        "store_policy_mode": "global_template_with_store_exceptions",
        "workflow_focus": ["store_selection", "bulk_candidate_review", "policy_mapping", "team_permissions"],
    },
}


@dataclass(slots=True)
class MerchantOperatingProfile:
    profile_version: str = PROFILE_VERSION
    merchant_stage: str = "store_opened"
    operating_mode: str = "single_store_process_automation"
    source_routes: list[str] = field(default_factory=lambda: ["1688_read_only_or_manual", "manual_link_image_table"])
    fulfillment_mode: str = "product_by_product"
    risk_level: str = "balanced"
    automation_level: str = "balanced_auto"
    permission_level: str = "low_auto"
    media_mode: str = "mixed"
    customer_service_mode: str = "standard_reply_after_product_learning"
    store_policy_mode: str = "reuse_authorized_store_policies"
    fee_mode: str = "fees_readonly"
    profit_floor: int = 15
    watch_metric: str = "profit"
    tone: str = "warm"
    auto_allowed_actions: list[str] = field(default_factory=lambda: list(LOW_RISK_AUTO_ACTIONS))
    confirmation_required_actions: list[str] = field(default_factory=lambda: list(HIGH_RISK_CONFIRMATION_ACTIONS))
    blocked_actions: list[str] = field(default_factory=list)
    workflow_focus: list[str] = field(default_factory=list)
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile_version": self.profile_version,
            "merchant_stage": self.merchant_stage,
            "operating_mode": self.operating_mode,
            "source_routes": list(self.source_routes),
            "fulfillment_mode": self.fulfillment_mode,
            "risk_level": self.risk_level,
            "automation_level": self.automation_level,
            "permission_level": self.permission_level,
            "media_mode": self.media_mode,
            "customer_service_mode": self.customer_service_mode,
            "store_policy_mode": self.store_policy_mode,
            "fee_mode": self.fee_mode,
            "profit_floor": self.profit_floor,
            "watch_metric": self.watch_metric,
            "tone": self.tone,
            "auto_allowed_actions": list(self.auto_allowed_actions),
            "confirmation_required_actions": list(self.confirmation_required_actions),
            "blocked_actions": list(self.blocked_actions),
            "workflow_focus": list(self.workflow_focus),
            "notes": self.notes,
        }

    def to_task_input(self) -> dict[str, Any]:
        return {
            "merchant_stage": self.merchant_stage,
            "operating_mode": self.operating_mode,
            "source_routes": list(self.source_routes),
            "fulfillment_mode": self.fulfillment_mode,
            "risk_level": self.risk_level,
            "permission_level": self.permission_level,
            "media_mode": self.media_mode,
            "customer_service_mode": self.customer_service_mode,
            "store_policy_mode": self.store_policy_mode,
            "fee_mode": self.fee_mode,
            "profit_floor": self.profit_floor,
            "watch_metric": self.watch_metric,
            "auto_allowed_actions": list(self.auto_allowed_actions),
            "confirmation_required_actions": list(self.confirmation_required_actions),
            "blocked_actions": list(self.blocked_actions),
        }


def build_default_merchant_profile(stage: str = "store_opened", overrides: dict[str, Any] | None = None) -> MerchantOperatingProfile:
    raw: dict[str, Any] = {"merchantStage": stage}
    if overrides:
        raw.update(overrides)
    return build_merchant_profile(raw)


def build_merchant_profile(raw: dict[str, Any] | None = None) -> MerchantOperatingProfile:
    raw = raw if isinstance(raw, dict) else {}
    stage = str(raw.get("merchantStage") or raw.get("merchant_stage") or raw.get("stage") or "store_opened")
    defaults = dict(STAGE_DEFAULTS.get(stage, STAGE_DEFAULTS["store_opened"]))
    profile = MerchantOperatingProfile(
        merchant_stage=stage,
        operating_mode=str(raw.get("operating_mode") or defaults["operating_mode"]),
        source_routes=_source_routes(raw.get("sourceApiMode") or raw.get("source_mode"), defaults["source_routes"]),
        fulfillment_mode=str(raw.get("fulfillmentMode") or raw.get("fulfillment_mode") or defaults["fulfillment_mode"]),
        risk_level=str(raw.get("riskLevel") or raw.get("risk_level") or "balanced"),
        automation_level=str(raw.get("automation_level") or defaults["automation_level"]),
        permission_level=str(raw.get("permissionLevel") or raw.get("permission_level") or "low_auto"),
        media_mode=str(raw.get("mediaMode") or raw.get("media_mode") or "mixed"),
        customer_service_mode=str(raw.get("customer_service_mode") or defaults["customer_service_mode"]),
        store_policy_mode=str(raw.get("returnPolicy") or raw.get("store_policy_mode") or defaults["store_policy_mode"]),
        fee_mode=str(raw.get("feeInsightMode") or raw.get("fee_mode") or "fees_readonly"),
        profit_floor=_int_or_default(raw.get("profitFloor") or raw.get("profit_floor"), 15),
        watch_metric=str(raw.get("watchMetric") or raw.get("watch_metric") or "profit"),
        tone=str(raw.get("tone") or "warm"),
        workflow_focus=list(defaults["workflow_focus"]),
        notes=str(raw.get("notes") or ""),
    )
    _apply_permission_rules(profile)
    _apply_risk_rules(profile)
    return profile


def merchant_profile_defaults() -> dict[str, Any]:
    return {
        "profile_version": PROFILE_VERSION,
        "stages": {stage: build_default_merchant_profile(stage).to_dict() for stage in STAGE_DEFAULTS},
        "high_risk_confirmation_actions": list(HIGH_RISK_CONFIRMATION_ACTIONS),
        "low_risk_auto_actions": list(LOW_RISK_AUTO_ACTIONS),
    }


def _source_routes(value: Any, defaults: list[str]) -> list[str]:
    route = str(value or "")
    if route == "api_1688_readonly":
        return ["1688_read_only_api", "manual_link_image_table"]
    if route == "manual_1688":
        return ["manual_1688_link_image_table", "merchant_upload"]
    if route == "api_1688_order_confirm":
        return ["1688_read_only_api", "1688_purchase_after_confirmation", "manual_link_image_table"]
    if route == "source_multi":
        return ["1688_read_only_api", "supplier_erp", "logistics_api", "spreadsheet_import", "manual_link_image_table"]
    if route:
        return [route]
    return list(defaults)


def _apply_permission_rules(profile: MerchantOperatingProfile) -> None:
    level = profile.permission_level
    auto_allowed = set(profile.auto_allowed_actions)
    confirmation_required = set(profile.confirmation_required_actions)
    blocked = set(profile.blocked_actions)

    if level == "draft":
        profile.automation_level = "draft_only"
        auto_allowed = {"read_only_import", "draft_report", "work_record"}
        confirmation_required.add("buyer_message_send")
    elif level == "service_auto":
        profile.automation_level = "standard_service_auto_sensitive_hold"
        auto_allowed.add("standard_customer_reply_after_product_learning")
        confirmation_required.discard("buyer_message_send")
        confirmation_required.add("sensitive_buyer_commitment")
    elif level == "batch_confirm":
        profile.automation_level = "batch_low_risk_auto_core_confirm"
        auto_allowed.update({"low_risk_batch_queue", "standard_recordkeeping"})
    elif level == "custom":
        profile.automation_level = "custom_rules_required"
        blocked.add("custom_rule_without_owner_approval")
    else:
        confirmation_required.add("buyer_message_send")

    profile.auto_allowed_actions = sorted(auto_allowed)
    profile.confirmation_required_actions = sorted(confirmation_required)
    profile.blocked_actions = sorted(blocked)


def _apply_risk_rules(profile: MerchantOperatingProfile) -> None:
    blocked = set(profile.blocked_actions)
    if profile.risk_level == "conservative":
        blocked.update({"unverified_brand_or_ip", "unverified_battery", "unverified_liquid", "unverified_fragile_packaging"})
    elif profile.risk_level == "aggressive":
        profile.auto_allowed_actions = sorted(set(profile.auto_allowed_actions) | {"prepare_more_candidates"})
        profile.confirmation_required_actions = sorted(set(profile.confirmation_required_actions) | set(HIGH_RISK_CONFIRMATION_ACTIONS))
    profile.blocked_actions = sorted(blocked)


def _int_or_default(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
