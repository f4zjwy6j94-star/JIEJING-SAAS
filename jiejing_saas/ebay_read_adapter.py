"""eBay read-only adapter contract for Jiejing SaaS.

This is a safe adapter shell. It does not call eBay, read Vault secrets, or
return seller data. It defines the read bundles the formal backend will use once
OAuth, Vault/KMS, token refresh, queue, and audit are production-ready.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .config import SaaSSettings
from .ebay_http_client import build_ebay_http_client_contract


@dataclass(frozen=True, slots=True)
class EbayReadResource:
    key: str
    label: str
    api_family: str
    official_scope_hint: list[str]
    purpose: str
    downstream_module: list[str]
    pii_or_financial_sensitivity: str = "low"
    fallback: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "api_family": self.api_family,
            "official_scope_hint": self.official_scope_hint,
            "purpose": self.purpose,
            "downstream_module": self.downstream_module,
            "pii_or_financial_sensitivity": self.pii_or_financial_sensitivity,
            "fallback": self.fallback,
        }


READ_RESOURCES: list[EbayReadResource] = [
    EbayReadResource(
        key="store_profile",
        label="Store profile",
        api_family="sell.account",
        official_scope_hint=["sell.account.readonly"],
        purpose="Read seller account, marketplace, store identity, selling limits, and high-level account status before workflow automation.",
        downstream_module=["connected_accounts", "ai_ceo_home", "ai_report"],
        fallback=["seller_hub_screenshot", "merchant_manual_store_profile"],
    ),
    EbayReadResource(
        key="account_business_policies",
        label="Store business policies",
        api_family="sell.account",
        official_scope_hint=["sell.account.readonly"],
        purpose="Read fulfillment, payment, and return policy IDs before creating listing packages.",
        downstream_module=["connected_accounts", "product_listing", "confirmation_center"],
        fallback=["seller_policy_snapshot_import", "merchant_manual_policy_ids"],
    ),
    EbayReadResource(
        key="inventory_and_offers",
        label="Inventory items and offers",
        api_family="sell.inventory",
        official_scope_hint=["sell.inventory.readonly"],
        purpose="Read existing SKUs, quantities, listing status, offer IDs, and item locations.",
        downstream_module=["product_listing", "market_report", "ai_report"],
        fallback=["seller_hub_listing_export", "csv_import", "manual_sku_sample"],
    ),
    EbayReadResource(
        key="orders_and_fulfillment",
        label="Orders and fulfillment",
        api_family="sell.fulfillment",
        official_scope_hint=["sell.fulfillment.readonly"],
        purpose="Read paid orders, fulfillment status, buyer message context, tracking gaps, and handling-time risk.",
        downstream_module=["customer_service", "logistics", "finance_review", "confirmation_center"],
        pii_or_financial_sensitivity="medium",
        fallback=["seller_hub_order_export", "manual_order_sample"],
    ),
    EbayReadResource(
        key="finances",
        label="Fees, payouts, and transactions",
        api_family="sell.finances",
        official_scope_hint=["sell.finances"],
        purpose="Read payout, fee, order earning, transaction, and billing activity context for margin review.",
        downstream_module=["finance_review", "ai_report"],
        pii_or_financial_sensitivity="high",
        fallback=["seller_hub_payment_export", "manual_fee_sample"],
    ),
    EbayReadResource(
        key="taxonomy_listing_metadata",
        label="Category and item specifics",
        api_family="commerce.taxonomy",
        official_scope_hint=["commerce.identity.readonly_or_app_access"],
        purpose="Suggest category IDs and required/recommended item specifics for each listing draft.",
        downstream_module=["product_listing", "market_report"],
        fallback=["cached_taxonomy_snapshot", "manual_category_id"],
    ),
    EbayReadResource(
        key="marketing_readonly",
        label="Promoted listing and ads signals",
        api_family="sell.marketing",
        official_scope_hint=["sell.marketing.readonly"],
        purpose="Read ad campaign context and performance signals without changing budgets.",
        downstream_module=["market_report", "finance_review", "ai_report"],
        pii_or_financial_sensitivity="medium",
        fallback=["seller_hub_ads_export", "manual_ad_spend_sample"],
    ),
]


class EbayReadOnlyAdapter:
    def __init__(self, settings: SaaSSettings) -> None:
        self.settings = settings

    def resource_catalog(self) -> dict[str, Any]:
        return {
            "version": "2026-05-15-ebay-readonly-catalog",
            "platform": "ebay",
            "resources": [resource.to_dict() for resource in READ_RESOURCES],
            "guardrails": {
                "no_live_calls_in_mvp": True,
                "no_write_scopes": True,
                "no_access_token_to_frontend": True,
                "pii_and_finance_require_task_scope": True,
                "secret_exposed": False,
            },
            "secret_exposed": False,
        }

    def build_read_workflow_plan(
        self,
        *,
        probe_plan: dict[str, Any],
    ) -> dict[str, Any]:
        resources = probe_plan.get("resources") if isinstance(probe_plan.get("resources"), list) else []
        read_steps = [
            {
                "step_order": 1,
                "key": "check_store_scope",
                "label": "Check store and tenant scope",
                "status": "planned",
                "backend_only": True,
            },
            {
                "step_order": 2,
                "key": "resolve_refresh_token",
                "label": "Resolve eBay refresh token from Vault/KMS",
                "status": "blocked" if "ebay_refresh_token_secret_ref" in probe_plan.get("blocked_by", []) else "planned",
                "backend_only": True,
            },
            {
                "step_order": 3,
                "key": "refresh_access_token",
                "label": "Refresh short-lived eBay access token",
                "status": "blocked" if "token_refresh_not_ready" in probe_plan.get("blocked_by", []) else "planned",
                "backend_only": True,
                "returns_token_to_frontend": False,
            },
        ]
        step_order = 4
        for resource in resources:
            if not isinstance(resource, dict):
                continue
            read_steps.append(
                {
                    "step_order": step_order,
                    "key": f"read_{resource.get('key')}",
                    "label": f"Read {resource.get('label')}",
                    "resource_key": resource.get("key"),
                    "api_family": resource.get("api_family"),
                    "status": "blocked_until_live_adapter" if probe_plan.get("blocked_by") else "planned",
                    "scope_hint": resource.get("official_scope_hint") or [],
                    "fallback": resource.get("fallback") or [],
                    "backend_only": True,
                }
            )
            step_order += 1
        read_steps.extend(
            [
                {
                    "step_order": step_order,
                    "key": "sanitize_and_label_sources",
                    "label": "Sanitize PII/secrets and label data sources",
                    "status": "planned",
                    "backend_only": True,
                },
                {
                    "step_order": step_order + 1,
                    "key": "cache_data_packet",
                    "label": "Cache read-only data packet",
                    "status": "planned",
                    "backend_only": True,
                },
                {
                    "step_order": step_order + 2,
                    "key": "handoff_to_runtime",
                    "label": "Hand packet to Runtime reports and draft workflows",
                    "status": "planned",
                    "backend_only": False,
                },
            ]
        )
        return {
            "workflow_version": "2026-05-15-ebay-readonly-workflow",
            "platform": "ebay",
            "status": "blocked_until_live_adapter" if probe_plan.get("blocked_by") else "ready_to_queue_read_job",
            "store_id": probe_plan.get("store_id"),
            "marketplace": probe_plan.get("marketplace"),
            "resources_requested": probe_plan.get("resources_requested") or [],
            "read_steps": read_steps,
            "step_count": len(read_steps),
            "blocked_by": probe_plan.get("blocked_by") or [],
            "safe_for_real_platform_write": False,
            "frontend_gets_access_token": False,
            "runtime_gets_raw_ebay_response": False,
            "runtime_gets_sanitized_packet_only": True,
            "secret_exposed": False,
        }

    def build_probe_plan(
        self,
        *,
        company_id: str,
        store: dict[str, Any],
        user_id: str,
        requested_resources: list[str] | None,
        secret_refs: list[dict[str, Any]],
        connections: list[dict[str, Any]],
        token_refresh_plan: dict[str, Any],
    ) -> dict[str, Any]:
        selected = self._select_resources(requested_resources)
        blockers = []
        if str(store.get("platform") or "").lower() != "ebay":
            blockers.append("store_platform_not_ebay")
        if not _has_ebay_refresh_ref(secret_refs):
            blockers.append("ebay_refresh_token_secret_ref")
        if not _has_readonly_connection(connections):
            blockers.append("ebay_read_only_connection")
        if token_refresh_plan.get("status") != "refresh_ready":
            blockers.append("token_refresh_not_ready")
        http_contract = build_ebay_http_client_contract(self.settings)
        blockers.extend(item for item in http_contract.get("blocked_by", []) if item not in blockers)

        status = "read_only_blocked" if blockers else "read_only_ready"
        return {
            "status": status,
            "platform": "ebay",
            "company_id": company_id,
            "store_id": store.get("store_id"),
            "store_name": store.get("store_name"),
            "marketplace": store.get("marketplace") or "EBAY_US",
            "user_id": user_id,
            "resources_requested": [resource["key"] for resource in selected],
            "resources": selected,
            "resource_count": len(selected),
            "blocked_by": blockers,
            "live_read_performed": False,
            "access_token_used": False,
            "access_token_returned_to_frontend": False,
            "raw_ebay_response_stored": False,
            "real_platform_writes_enabled": False,
            "source_label_when_live": "official_api",
            "degrade_to_when_blocked": [
                "seller_export",
                "policy_snapshot_import",
                "manual_sample",
                "AI_inference_labeled_as_inference",
            ],
            "next_step": "implement_backend_vault_token_resolver_and_read_http_adapter" if blockers else "run_queued_read_probe",
            "notes": [
                "Read-only data must be fetched by the backend adapter, not the browser or Runtime directly.",
                "Order and finance reads can contain sensitive buyer or payout data and must be task-scoped.",
                "Read-only probes can feed reports and drafts, but cannot publish, refund, revise listings, change ads, or edit policies.",
                "Missing API access must be shown as a source gap instead of pretending live data was read.",
            ],
            "secret_exposed": False,
        }

    def _select_resources(self, requested_resources: list[str] | None) -> list[dict[str, Any]]:
        if not requested_resources:
            return [resource.to_dict() for resource in READ_RESOURCES]
        requested = {str(item).strip().lower() for item in requested_resources if str(item).strip()}
        selected = [resource.to_dict() for resource in READ_RESOURCES if resource.key in requested]
        return selected or [resource.to_dict() for resource in READ_RESOURCES]


def _has_ebay_refresh_ref(secret_refs: list[dict[str, Any]]) -> bool:
    return any(
        str(item.get("provider") or "").lower() == "ebay"
        and str(item.get("purpose") or "").lower() == "ebay_refresh_token"
        for item in secret_refs
    )


def _has_readonly_connection(connections: list[dict[str, Any]]) -> bool:
    for item in connections:
        if str(item.get("platform") or "").lower() != "ebay":
            continue
        if str(item.get("connection_type") or "").lower() != "oauth":
            continue
        status = str(item.get("status") or "").lower()
        if status not in {"read_only_authorized", "authorized", "connected"}:
            continue
        scopes = [str(scope).lower() for scope in item.get("scopes", [])]
        if any("readonly" in scope for scope in scopes):
            return True
    return False
