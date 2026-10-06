"""Execution preflight checks for confirmed platform actions.

Confirmation is necessary, but it is not enough. Before any future platform
adapter can publish, revise, refund, advertise, procure, or edit policies, the
request must also prove that the operational facts are complete enough for that
action type.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any, Protocol


class ExecutionRequestLike(Protocol):
    action_type: str
    company_id: str
    store_id: str
    payload: dict[str, Any]
    confirmation_id: str | None
    confirmed_by: str | None
    confirmed_at: str | None
    idempotency_key: str | None


ACTION_ALIASES = {
    "publish_listing": "publish_listing",
    "bulk_publish_listing": "bulk_publish_listing",
    "prepare_listing_draft": "prepare_listing_draft",
    "save_listing_draft": "prepare_listing_draft",
    "listing_draft": "prepare_listing_draft",
    "save_ebay_listing_draft": "save_ebay_listing_draft",
    "save_ebay_draft": "save_ebay_listing_draft",
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
        "publish_evidence",
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
    "prepare_listing_draft": [
        "listing.title",
        "listing.description_html",
        "listing.draft_source",
    ],
    "save_ebay_listing_draft": [
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
        "asset_manifest.assets",
        "publish_evidence",
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
    "prepare_listing_draft",
    "prepare_report",
    "update_task_status",
    "create_asset_task",
}


PUBLISH_EVIDENCE_CONTRACT_VERSION = "2026-08-31-publish-source-rights-evidence-v1"


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
    version = "2026-08-31.1"

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
        if action_type in {"publish_listing", "save_ebay_listing_draft"}:
            issues.extend(validate_publish_input_values(payload))
            evidence_review = validate_publish_evidence(
                payload,
                company_id=str(getattr(request, "company_id", "") or ""),
                store_id=str(getattr(request, "store_id", "") or ""),
                listing_project_key=_listing_project_key(payload),
            )
            issues.extend(evidence_review["issues"])
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
        if action_type not in {"publish_listing", "save_ebay_listing_draft"}:
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
        if action_type == "prepare_listing_draft":
            return f"Listing draft preparation cannot proceed until {field} is present."
        if action_type in {"publish_listing", "save_ebay_listing_draft", "bulk_publish_listing", "revise_listing"}:
            return f"Listing execution cannot proceed until {field} is present."
        if action_type in {"refund", "partial_refund", "sensitive_buyer_commitment"}:
            return f"Customer-impacting execution cannot proceed until {field} is present."
        if action_type in {"procurement_payment", "purchase_order", "address_write"}:
            return f"Procurement or address execution cannot proceed until {field} is present."
        return f"Execution cannot proceed until {field} is present."


def finite_publish_number(value: Any) -> float | None:
    """Never accept booleans or non-finite values as merchant quantities/money."""
    if isinstance(value, bool):
        return None
    try:
        amount = float(str(value).strip())
    except (TypeError, ValueError, OverflowError):
        return None
    return amount if math.isfinite(amount) else None


def publish_procurement_cost_in_sale_currency(finance: dict[str, Any], sale_currency: str) -> float | None:
    """Convert only an explicitly labelled procurement currency, never other fees."""
    raw = finance.get("procurement_cost_money", finance.get("procurement_cost"))
    amount = finite_publish_number(raw.get("value") if isinstance(raw, dict) else raw)
    if amount is None or amount < 0:
        return None
    cost_currency = str(raw.get("currency") or "").strip().upper() if isinstance(raw, dict) else sale_currency
    if not cost_currency:
        return None
    if cost_currency == sale_currency:
        return amount
    rate = finite_publish_number(finance.get("exchange_rate"))
    if (not cost_currency or rate is None or rate <= 0
            or finance.get("exchange_rate_basis") != "sale_currency_per_cost_currency"):
        return None
    converted = finite_publish_number(amount * rate)
    return round(converted, 2) if converted is not None else None


def validate_publish_input_values(payload: dict[str, Any]) -> list[dict[str, str]]:
    """Check sale values independently of presence and merchant approval."""
    listing = payload.get("listing") if isinstance(payload.get("listing"), dict) else {}
    price = listing.get("price") if isinstance(listing.get("price"), dict) else {"value": listing.get("price"), "currency": "USD"}
    supplier = payload.get("supplier_facts") if isinstance(payload.get("supplier_facts"), dict) else {}
    issues: list[dict[str, str]] = []
    amount = finite_publish_number(price.get("value"))
    if amount is None or amount <= 0:
        issues.append(PreflightIssue("listing.price.value", "售价必须是大于 0 的有效数字。").to_dict())
    sale_currency = str(price.get("currency", "USD") or "").strip().upper()
    currency_valid = len(sale_currency) == 3 and sale_currency.isascii() and sale_currency.isalpha()
    if not currency_valid:
        issues.append(PreflightIssue("listing.price.currency", "请确认售价币种，并填写 3 位币种代码（如 USD）；未知币种不能计算利润或发布。").to_dict())
    quantity = finite_publish_number(listing.get("quantity"))
    if quantity is None or quantity < 0 or not quantity.is_integer() or quantity > 9007199254740991:
        issues.append(PreflightIssue("listing.quantity", "库存必须是非负整数，不能截取小数或使用无效数字。").to_dict())
    if amount is not None and quantity is not None and not math.isfinite(amount * quantity):
        issues.append(PreflightIssue("listing.price.exposure", "售价与库存的乘积超出可计算范围，请核对输入。").to_dict())
    if "package_weight_g" in supplier:
        weight = finite_publish_number(supplier.get("package_weight_g"))
        if weight is None or weight <= 0:
            issues.append(PreflightIssue("supplier_facts.package_weight_g", "包装重量必须是大于 0 的有效数字。").to_dict())
    if "package_dimensions_cm" in supplier:
        dimensions = supplier.get("package_dimensions_cm")
        dimensions = dimensions if isinstance(dimensions, dict) else {}
        for axis in ("length", "width", "height"):
            size = finite_publish_number(dimensions.get(axis))
            if size is None or size <= 0:
                axis_label = {"length": "长", "width": "宽", "height": "高"}[axis]
                issues.append(PreflightIssue(f"supplier_facts.package_dimensions_cm.{axis}", f"包装{axis_label}（cm）必须填写大于 0 的有效数字。").to_dict())
    finance = payload.get("finance_review") if isinstance(payload.get("finance_review"), dict) else {}
    cost_values = []
    for key in ("procurement_cost", "shipping_cost", "ebay_fee", "ad_budget", "return_risk_reserve", "net_profit"):
        field = f"{key}_money" if f"{key}_money" in finance else key
        value = finance.get(field)
        number = finite_publish_number(value.get("value") if isinstance(value, dict) else value)
        if field in finance:
            if number is None or number < 0:
                issues.append(PreflightIssue(f"finance_review.{field}", "费用和净利润必须是非负的有效数字；亏损商品不能直接发布。").to_dict())
            if isinstance(value, dict) and str(value.get("currency") or "").strip().upper() != sale_currency:
                converted = publish_procurement_cost_in_sale_currency(finance, sale_currency) if key == "procurement_cost" else None
                if converted is None:
                    issues.append(PreflightIssue(f"finance_review.{field}.currency", "费用不能跨币种直接相减；采购成本换算需明确 1 单位成本币种兑换多少售价币种及有效汇率，其余费用请填写售价币种金额。").to_dict())
                number = converted
        if key != "net_profit":
            cost_values.append(number)
    for key in ("exchange_rate", "gross_margin_percent"):
        if key in finance:
            number = finite_publish_number(finance[key])
            if number is None or (key == "exchange_rate" and number <= 0):
                message = "汇率必须是大于 0 的有效数字。" if key == "exchange_rate" else "毛利率必须是有效数字。"
                issues.append(PreflightIssue(f"finance_review.{key}", message).to_dict())
    declared = finance.get("net_profit_money", finance.get("net_profit"))
    declared_profit = finite_publish_number(declared.get("value") if isinstance(declared, dict) else declared)
    if currency_valid and amount is not None and all(value is not None for value in cost_values):
        calculated_profit = finite_publish_number(round(amount - sum(cost_values), 2))
        if calculated_profit is None:
            issues.append(PreflightIssue("finance_review.calculated_contribution_profit", "费用合计超出可计算范围，请核对输入。").to_dict())
            return issues
        if calculated_profit < 0:
            issues.append(PreflightIssue("finance_review.calculated_contribution_profit", "按售价和完整费用计算为亏损，请调整售价或成本后重新核对。").to_dict())
        if declared_profit is not None and abs(calculated_profit - declared_profit) > 0.011:
            issues.append(PreflightIssue("finance_review.net_profit_money", "填写的净利润与售价减去费用的计算结果不一致，请重新核对。").to_dict())
    return issues


def validate_publish_evidence(
    payload: dict[str, Any],
    *,
    company_id: str | None = None,
    store_id: str | None = None,
    listing_project_key: str | None = None,
) -> dict[str, Any]:
    """Strictly validate one backend-issued source and image-rights packet."""

    payload = payload if isinstance(payload, dict) else {}
    evidence = payload.get("publish_evidence") if isinstance(payload.get("publish_evidence"), dict) else {}
    issues: list[dict[str, str]] = []

    def add(key: str, message: str) -> None:
        if any(item.get("key") == key for item in issues):
            return
        issues.append(PreflightIssue(key, message).to_dict())

    if not evidence:
        add(
            "publish_evidence",
            "Listing execution requires backend-resolved product-source and image-rights evidence.",
        )
        return {
            "status": "blocked",
            "ready": False,
            "contract_version": PUBLISH_EVIDENCE_CONTRACT_VERSION,
            "issues": issues,
            "required_asset_count": 0,
            "covered_asset_count": 0,
        }

    if evidence.get("contract_version") != PUBLISH_EVIDENCE_CONTRACT_VERSION:
        add(
            "publish_evidence.contract_version",
            "Publish evidence uses an unsupported contract version and must be resolved again by the backend.",
        )
    if evidence.get("status") != "ready":
        add("publish_evidence.status", "Publish evidence is not ready for an eBay write.")
    if evidence.get("server_resolved") is not True:
        add(
            "publish_evidence.server_resolved",
            "Listing execution requires publish evidence resolved by the Jiejing backend; browser assertions are not trusted.",
        )

    scope = evidence.get("scope") if isinstance(evidence.get("scope"), dict) else {}
    expected_company_id = str(company_id or "").strip()
    expected_store_id = str(store_id or "").strip()
    expected_project_key = str(listing_project_key or _listing_project_key(payload)).strip()
    if not expected_company_id or str(scope.get("company_id") or "").strip() != expected_company_id:
        add(
            "publish_evidence.scope.company_id",
            "Publish evidence belongs to a different company and cannot authorize this eBay write.",
        )
    if not expected_store_id or str(scope.get("store_id") or "").strip() != expected_store_id:
        add(
            "publish_evidence.scope.store_id",
            "Publish evidence belongs to a different store and cannot authorize this eBay write.",
        )
    if not expected_project_key or str(scope.get("listing_project_key") or "").strip() != expected_project_key:
        add(
            "publish_evidence.scope.listing_project_key",
            "Publish evidence is not bound to the current Listing project.",
        )

    refs = evidence.get("refs") if isinstance(evidence.get("refs"), dict) else {}
    report_id = str(refs.get("product_fact_report_id") or "").strip()
    media_job_id = str(refs.get("media_job_id") or "").strip()
    product_source = evidence.get("product_source") if isinstance(evidence.get("product_source"), dict) else {}
    if not (
        product_source.get("status") == "verified"
        and product_source.get("source_mode") in {"merchant_source_supplied", "merchant_owned_product"}
        and product_source.get("evidence_type") == "merchant_product_fact_report"
        and report_id
        and str(product_source.get("evidence_id") or "").strip() == report_id
    ):
        add(
            "publish_evidence.product_source",
            "A current merchant product-fact report must verify the product source before an eBay write.",
        )

    manifest = payload.get("asset_manifest") if isinstance(payload.get("asset_manifest"), dict) else {}
    manifest_assets = manifest.get("assets") if isinstance(manifest.get("assets"), list) else []
    expected_assets: list[tuple[str, str]] = []
    for raw in manifest_assets:
        item = raw if isinstance(raw, dict) else {}
        asset_id = str(item.get("asset_id") or "").strip()
        url = str(item.get("url") or item.get("url_or_file_path") or "").strip()
        expected_assets.append((asset_id, hashlib.sha256(url.encode("utf-8")).hexdigest() if url else ""))

    rights = evidence.get("image_rights") if isinstance(evidence.get("image_rights"), dict) else {}
    if rights.get("status") != "verified":
        add(
            "publish_evidence.image_rights.status",
            "Image rights must be verified by persisted merchant or approved-media evidence.",
        )
    covered_assets = rights.get("assets") if isinstance(rights.get("assets"), list) else []
    required_count = rights.get("required_asset_count")
    covered_count = rights.get("covered_asset_count")
    expected_count = len(manifest_assets)
    counts_are_ints = (
        isinstance(required_count, int)
        and not isinstance(required_count, bool)
        and isinstance(covered_count, int)
        and not isinstance(covered_count, bool)
    )
    if not (
        expected_count > 0
        and all(url_sha256 for _, url_sha256 in expected_assets)
        and counts_are_ints
        and required_count == expected_count
        and covered_count == expected_count
        and len(covered_assets) == expected_count
        and rights.get("coverage_complete") is True
    ):
        add(
            "publish_evidence.image_rights.coverage",
            "Every image in the eBay asset manifest must have complete server-resolved commercial-rights coverage.",
        )

    actual_assets: list[tuple[str, str]] = []
    asset_evidence_valid = True
    allowed_evidence_types = {"merchant_product_fact_report", "approved_media_asset_job"}
    for raw in covered_assets:
        item = raw if isinstance(raw, dict) else {}
        asset_id = str(item.get("asset_id") or "").strip()
        url_sha256 = str(item.get("url_sha256") or "").strip().lower()
        evidence_type = str(item.get("evidence_type") or "").strip()
        evidence_id = str(item.get("evidence_id") or "").strip()
        actual_assets.append((asset_id, url_sha256))
        expected_evidence_id = report_id if evidence_type == "merchant_product_fact_report" else media_job_id
        if (
            evidence_type not in allowed_evidence_types
            or not expected_evidence_id
            or evidence_id != expected_evidence_id
            or len(url_sha256) != 64
            or any(char not in "0123456789abcdef" for char in url_sha256)
        ):
            asset_evidence_valid = False
    if not asset_evidence_valid or sorted(actual_assets) != sorted(expected_assets):
        add(
            "publish_evidence.image_rights.assets",
            "Image-rights evidence does not match the exact asset IDs and URLs being sent to eBay.",
        )

    if evidence.get("secret_exposed") is not False:
        add(
            "publish_evidence.secret_exposed",
            "Publish evidence must not contain or expose provider credentials.",
        )
    resolved_at = str(evidence.get("resolved_at") or "").strip()
    if not resolved_at:
        add("publish_evidence.resolved_at", "Publish evidence must include its backend resolution time.")
    fingerprint = str(evidence.get("fingerprint") or "").strip().lower()
    fingerprint_payload = {
        key: value for key, value in evidence.items() if key not in {"resolved_at", "fingerprint"}
    }
    expected_fingerprint = hashlib.sha256(
        json.dumps(
            fingerprint_payload,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    if fingerprint != expected_fingerprint:
        add(
            "publish_evidence.fingerprint",
            "Publish evidence changed after backend resolution and must be resolved again.",
        )

    return {
        "status": "ready" if not issues else "blocked",
        "ready": not issues,
        "contract_version": PUBLISH_EVIDENCE_CONTRACT_VERSION,
        "issues": issues,
        "required_asset_count": required_count if isinstance(required_count, int) else 0,
        "covered_asset_count": covered_count if isinstance(covered_count, int) else 0,
    }


def _listing_project_key(payload: dict[str, Any]) -> str:
    identity = payload.get("listing_project_identity") if isinstance(payload.get("listing_project_identity"), dict) else {}
    listing = payload.get("listing") if isinstance(payload.get("listing"), dict) else {}
    return str(
        identity.get("key")
        or payload.get("listing_project_key")
        or listing.get("listing_project_key")
        or ""
    ).strip()
