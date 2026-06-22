"""Execution preflight checks for confirmed platform actions.

Confirmation is necessary, but it is not enough. Before any future platform
adapter can publish, revise, refund, advertise, procure, or edit policies, the
request must also prove that the operational facts are complete enough for that
action type.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class ExecutionRequestLike(Protocol):
    action_type: str
    payload: dict[str, Any]
    confirmation_id: str | None
    confirmed_by: str | None
    confirmed_at: str | None
    idempotency_key: str | None


ACTION_ALIASES = {
    "publish_listing": "publish_listing",
    "bulk_publish_listing": "bulk_publish_listing",
    "revise_listing": "revise_listing",
    "change_price": "change_price",
    "change_inventory": "change_inventory",
    "ad_budget": "ad_budget",
    "open_ad_campaign": "ad_budget",
    "change_ad_budget": "ad_budget",
    "refund": "refund",
    "partial_refund": "partial_refund",
    "procurement_payment": "procurement_payment",
    "purchase_order": "purchase_order",
    "cleanup_test_listing": "cleanup_test_listing",
    "address_write": "address_write",
    "policy_edit": "policy_edit",
    "change_shipping_policy": "policy_edit",
    "change_payment_policy": "policy_edit",
    "change_return_policy": "policy_edit",
    "store_subscription": "store_subscription",
    "ebay_oauth_scope_change": "oauth_scope_change",
    "oauth_scope_change": "oauth_scope_change",
    "sensitive_customer_reply": "sensitive_buyer_commitment",
    "sensitive_buyer_commitment": "sensitive_buyer_commitment",
}

ACTION_REQUIREMENTS = {
    "publish_listing": [
        "account_health.status",
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
        "supplier_facts.material",
        "supplier_facts.item_location",
        "asset_manifest.assets",
        "finance_review.net_profit_money",
        "confirmation_record",
        "idempotency_key",
    ],
    "bulk_publish_listing": [
        "batch.items",
        "batch.publish_count",
        "batch.item_level_preflight",
        "confirmation_record",
        "idempotency_key",
    ],
    "revise_listing": ["listing_id", "change_set", "confirmation_record", "idempotency_key"],
    "change_price": ["listing_id", "new_price", "reason", "finance_review", "confirmation_record", "idempotency_key"],
    "change_inventory": ["listing_id", "new_quantity", "reason", "confirmation_record", "idempotency_key"],
    "ad_budget": ["campaign_or_listing_id", "budget_amount", "budget_period", "reason", "confirmation_record", "idempotency_key"],
    "refund": ["order_id", "refund_amount", "reason", "buyer_case_status", "confirmation_record", "idempotency_key"],
    "partial_refund": ["order_id", "refund_amount", "reason", "buyer_case_status", "confirmation_record", "idempotency_key"],
    "procurement_payment": ["supplier_id_or_link", "purchase_amount", "ship_to_address_mode", "confirmation_record", "idempotency_key"],
    "purchase_order": ["supplier_id_or_link", "order_items", "ship_to_address_mode", "confirmation_record", "idempotency_key"],
    "cleanup_test_listing": ["cleanup_plan.operations", "cleanup_plan.confirmation_required", "confirmation_record", "idempotency_key"],
    "address_write": ["order_id_or_purchase_id", "target_address", "confirmation_record", "idempotency_key"],
    "policy_edit": ["policy_type", "policy_id", "change_set", "confirmation_record", "idempotency_key"],
    "store_subscription": ["subscription_plan", "monthly_cost", "confirmation_record", "idempotency_key"],
    "oauth_scope_change": ["requested_scopes", "authorization_url_or_state", "confirmation_record", "idempotency_key"],
    "sensitive_buyer_commitment": ["order_id", "message_draft", "risk_reason", "confirmation_record", "idempotency_key"],
}

LOW_RISK_ACTIONS = {
    "save_internal_note",
    "save_draft",
    "prepare_report",
    "update_task_status",
    "create_asset_task",
}


@dataclass(slots=True)
class PreflightIssue:
    key: str
    message: str
    severity: str = "blocking"

    def to_dict(self) -> dict[str, str]:
        return {"key": self.key, "message": self.message, "severity": self.severity}


class ExecutionPreflightChecker:
    """Checks whether a confirmed request is complete enough for execution."""

    name = "jiejing-execution-preflight"
    version = "2026-05-15.1"

    def review(self, request: ExecutionRequestLike) -> dict[str, Any]:
        action_type = self._canonical_action(request.action_type)
        payload = request.payload if isinstance(request.payload, dict) else {}
        requirements = list(ACTION_REQUIREMENTS.get(action_type, []))
        missing = [field for field in requirements if not self._present(request, payload, field)]
        unknown_action = action_type not in ACTION_REQUIREMENTS and action_type not in LOW_RISK_ACTIONS
        issues = [PreflightIssue(field, self._message_for_missing(action_type, field)).to_dict() for field in missing]
        if unknown_action:
            issues.append(
                PreflightIssue(
                    "unknown_action_type",
                    f"Action type {request.action_type} has no execution adapter contract.",
                ).to_dict()
            )
        category_issue = self._category_relevance_issue(action_type, payload)
        if category_issue:
            issues.append(category_issue.to_dict())
        account_health_issue = self._account_health_issue(action_type, payload)
        if account_health_issue:
            issues.append(account_health_issue.to_dict())
        if action_type in LOW_RISK_ACTIONS and not issues:
            status = "ready_low_risk"
        elif issues:
            status = "blocked_missing_execution_facts"
        else:
            status = "ready_for_platform_adapter"
        return {
            "preflight": self.name,
            "preflight_version": self.version,
            "action_type": request.action_type,
            "canonical_action_type": action_type,
            "status": status,
            "required_fields": requirements,
            "missing_fields": missing,
            "issues": issues,
            "confirmation_record_present": self._has_confirmation(request),
            "platform_adapter_required": action_type not in LOW_RISK_ACTIONS,
            "real_execution_allowed": False,
            "safe_for_demo_handoff": status in {"ready_low_risk", "ready_for_platform_adapter", "blocked_missing_execution_facts"},
        }

    def contract(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "action_aliases": ACTION_ALIASES,
            "action_requirements": ACTION_REQUIREMENTS,
            "low_risk_actions": sorted(LOW_RISK_ACTIONS),
            "real_execution_allowed": False,
            "confirmation_is_required_but_not_sufficient": True,
        }

    def _canonical_action(self, action_type: str) -> str:
        return ACTION_ALIASES.get(str(action_type or "").strip(), str(action_type or "").strip())

    def _present(self, request: ExecutionRequestLike, payload: dict[str, Any], field_path: str) -> bool:
        if field_path == "confirmation_record":
            return self._has_confirmation(request)
        if field_path == "idempotency_key":
            return bool(getattr(request, "idempotency_key", None) or payload.get("idempotency_key"))
        current: Any = payload
        for part in field_path.split("."):
            if not isinstance(current, dict) or part not in current:
                return False
            current = current[part]
        if current is None:
            return False
        if isinstance(current, str):
            return bool(current.strip())
        if isinstance(current, (list, tuple, set, dict)):
            return bool(current)
        return True

    def _has_confirmation(self, request: ExecutionRequestLike) -> bool:
        return bool(request.confirmation_id and request.confirmed_by and request.confirmed_at)

    def _category_relevance_issue(self, action_type: str, payload: dict[str, Any]) -> PreflightIssue | None:
        if action_type != "publish_listing":
            return None
        listing = payload.get("listing") if isinstance(payload.get("listing"), dict) else {}
        validation = listing.get("category_validation") if isinstance(listing.get("category_validation"), dict) else {}
        if validation.get("product_match") is False:
            return PreflightIssue(
                "listing.category_id",
                "Listing execution cannot proceed until the eBay category is validated as relevant to this product.",
            )
        title = str(listing.get("title") or listing.get("product") or "").strip().lower()
        leaf = str(listing.get("category_leaf") or listing.get("leaf_category") or listing.get("category_name") or "").strip().lower()
        if not title or not leaf:
            return None
        musical_leaf_markers = {"bass", "guitar", "instrument", "musical"}
        musical_title_markers = {"guitar", "bass", "instrument", "music", "musical"}
        incense_title_markers = {"incense", "burner", "aroma", "aromatherapy", "backflow"}
        if (set(leaf.replace("/", " ").split()) & musical_leaf_markers) and not (
            set(title.replace("/", " ").split()) & musical_title_markers
        ):
            return PreflightIssue(
                "listing.category_id",
                f"Listing category `{leaf}` does not match product title `{title}`.",
            )
        if (set(title.replace("/", " ").split()) & incense_title_markers) and (
            set(leaf.replace("/", " ").split()) & musical_leaf_markers
        ):
            return PreflightIssue(
                "listing.category_id",
                f"Listing category `{leaf}` is incompatible with an incense burner product.",
            )
        return None

    def _account_health_issue(self, action_type: str, payload: dict[str, Any]) -> PreflightIssue | None:
        if action_type not in ACTION_REQUIREMENTS:
            return None
        account_health = payload.get("account_health") if isinstance(payload.get("account_health"), dict) else {}
        if not account_health:
            return None
        blocked_markers = {
            "blocked",
            "frozen",
            "hold",
            "held",
            "limited",
            "restricted",
            "restriction",
            "suspended",
            "unverified",
            "unknown",
        }
        status_fields = [
            account_health.get("status"),
            account_health.get("account_status"),
            account_health.get("selling_status"),
            account_health.get("payout_status"),
            account_health.get("payment_status"),
            account_health.get("verification_status"),
        ]
        restrictions = account_health.get("restrictions")
        if isinstance(restrictions, list):
            status_fields.extend(str(item) for item in restrictions)
        elif isinstance(restrictions, str):
            status_fields.append(restrictions)
        normalized = " ".join(str(item or "").strip().lower().replace("_", " ") for item in status_fields)
        if any(marker in normalized for marker in blocked_markers):
            return PreflightIssue(
                "account_health.status",
                "eBay account health is not clear for publishing. Stop real writes and route this store to account-risk diagnosis first.",
            )
        return None

    def _message_for_missing(self, action_type: str, field: str) -> str:
        if field == "confirmation_record":
            return "A recorded merchant confirmation is required before this action can leave the confirmation center."
        if field == "idempotency_key":
            return "An idempotency key is required so queue retries cannot duplicate platform writes."
        if field == "account_health.status":
            return "A current eBay account-health snapshot is required before publishing so restricted, frozen or payout-held accounts cannot receive real writes."
        if action_type in {"publish_listing", "bulk_publish_listing", "revise_listing"}:
            return f"Listing execution cannot proceed until {field} is present."
        if action_type in {"refund", "partial_refund", "sensitive_buyer_commitment"}:
            return f"Customer-impacting execution cannot proceed until {field} is present."
        if action_type in {"procurement_payment", "purchase_order", "address_write"}:
            return f"Procurement or address execution cannot proceed until {field} is present."
        return f"Execution cannot proceed until {field} is present."
