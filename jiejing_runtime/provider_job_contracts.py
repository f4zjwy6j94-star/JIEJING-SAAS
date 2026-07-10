"""Provider job contracts for Jiejing-owned Runtime.

These contracts are the next production layer after the local Agent reports:
every external capability must become a bounded, retryable provider job before
the SaaS backend can safely use it for real merchants.

The contracts do not call providers and do not expose credentials. They define
how future jobs should be queued, what secret reference is required, what output
must be normalized, and which actions remain confirmation-gated.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


CONTRACT_VERSION = "2026-05-15.1"


@dataclass(slots=True)
class ProviderJobContract:
    key: str
    label: str
    provider_family: str
    used_by_tasks: list[str]
    required_secret_purpose: str | None
    timeout_seconds: int
    max_attempts: int
    queue: str
    output_packet: str
    source_record_type: str
    blocked_actions: list[str] = field(default_factory=list)
    required_inputs: list[str] = field(default_factory=list)
    normalized_outputs: list[str] = field(default_factory=list)
    failure_visible_to_merchant: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "provider_family": self.provider_family,
            "used_by_tasks": list(self.used_by_tasks),
            "required_secret_purpose": self.required_secret_purpose,
            "timeout_seconds": self.timeout_seconds,
            "max_attempts": self.max_attempts,
            "queue": self.queue,
            "output_packet": self.output_packet,
            "source_record_type": self.source_record_type,
            "blocked_actions": list(self.blocked_actions),
            "required_inputs": list(self.required_inputs),
            "normalized_outputs": list(self.normalized_outputs),
            "failure_visible_to_merchant": self.failure_visible_to_merchant,
            "raw_secret_exposed": False,
            "real_execution_allowed": False,
        }


class ProviderJobContractCatalog:
    """Front-end-safe catalog of provider job boundaries."""

    def list_contracts(self) -> list[dict[str, Any]]:
        return [item.to_dict() for item in self._contracts()]

    def to_dict(self) -> dict[str, Any]:
        contracts = self.list_contracts()
        provider_families = sorted({item["provider_family"] for item in contracts})
        task_types = sorted({task for item in contracts for task in item["used_by_tasks"]})
        return {
            "contract_version": CONTRACT_VERSION,
            "contract_count": len(contracts),
            "provider_families": provider_families,
            "task_types": task_types,
            "contracts": contracts,
            "queue_rules": {
                "merchant_sees_status": True,
                "timeouts_become_failed_tool": True,
                "retry_never_repeats_high_risk_action": True,
                "provider_error_written_to_work_record": True,
                "raw_provider_response_not_persisted": True,
            },
            "secret_boundary": {
                "frontend_gets_raw_secret": False,
                "runtime_gets_raw_secret": False,
                "provider_job_gets_task_scoped_secret": True,
                "secret_refs_only_in_public_payloads": True,
            },
            "production_missing": [
                "Cloud queue worker implementation",
                "Vault/KMS runtime secret resolver",
                "provider-specific billing and quota guard",
                "provider response normalizers connected to SaaS database",
                "operator alerting for repeated failure and dead-letter jobs",
            ],
            "secret_exposed": False,
            "real_execution_allowed": False,
        }

    def _contracts(self) -> list[ProviderJobContract]:
        return [
            ProviderJobContract(
                key="public_search.market_research",
                label="Public search market research",
                provider_family="public_search",
                used_by_tasks=["market.data_packet", "market.report"],
                required_secret_purpose="public_search_api_key",
                timeout_seconds=20,
                max_attempts=2,
                queue="provider.read",
                output_packet="market_public_search_signal",
                source_record_type="public_search",
                required_inputs=["query", "marketplace", "category_hint"],
                normalized_outputs=["title", "url", "snippet", "source_type", "confidence", "captured_at"],
            ),
            ProviderJobContract(
                key="ebay.read_only_snapshot",
                label="eBay read-only snapshot",
                provider_family="ebay",
                used_by_tasks=["market.data_packet", "market.report", "listing.package", "finance.review", "customer.learn_product"],
                required_secret_purpose="ebay_refresh_token",
                timeout_seconds=30,
                max_attempts=2,
                queue="provider.read",
                output_packet="ebay_sanitized_data_packet",
                source_record_type="official_api",
                required_inputs=["store_id", "marketplace_id", "resource_keys"],
                normalized_outputs=["store_profile", "policies", "inventory", "orders", "fees", "taxonomy"],
                blocked_actions=["publish_listing", "revise_listing", "refund", "change_price", "change_inventory"],
            ),
            ProviderJobContract(
                key="sourcing.1688_availability",
                label="1688 sourcing availability",
                provider_family="sourcing",
                used_by_tasks=["source.match", "finance.review", "asset.brief"],
                required_secret_purpose="sourcing_api_secret",
                timeout_seconds=25,
                max_attempts=2,
                queue="provider.read",
                output_packet="sourcing_candidate_packet",
                source_record_type="sourcing_snapshot",
                required_inputs=["product_keyword_or_url", "merchant_source_mode", "risk_filters"],
                normalized_outputs=["source_url", "title", "unit_cost", "moq", "stock", "ship_from", "package_weight_g", "material"],
                blocked_actions=["procurement_order", "procurement_payment", "address_write"],
            ),
            ProviderJobContract(
                key="logistics.orange_connex_quote",
                label="Orange Connex / SpeedPAK quote",
                provider_family="logistics",
                used_by_tasks=["finance.review", "confirmation.package"],
                required_secret_purpose="logistics_api_secret",
                timeout_seconds=20,
                max_attempts=2,
                queue="provider.read",
                output_packet="logistics_quote_packet",
                source_record_type="logistics_quote",
                required_inputs=["origin", "destination", "package_weight_g", "package_dimensions_cm", "service_hint"],
                normalized_outputs=["carrier", "service_name", "cost", "currency", "eta_min_days", "eta_max_days", "tracking"],
                blocked_actions=["buy_label", "write_tracking", "promise_exact_delivery_date"],
            ),
            ProviderJobContract(
                key="media.asset_generation",
                label="Jiejing asset generation router",
                provider_family="media",
                used_by_tasks=["asset.brief"],
                required_secret_purpose="media_generation_api_key",
                timeout_seconds=60,
                max_attempts=1,
                queue="provider.media",
                output_packet="asset_manifest",
                source_record_type="media_provider",
                required_inputs=["creative_job_spec", "product_facts", "image_count", "image_sizes", "scene_types"],
                normalized_outputs=[
                    "asset_type",
                    "url_or_file_path",
                    "dimensions_or_duration",
                    "source_provider_or_upload",
                    "prompt_version",
                    "cost_estimate",
                    "commercial_use_status",
                    "fact_review_status",
                    "listing_use_status",
                    "asset_manifest_validation",
                    "asset_review_status",
                    "cost_guard_status",
                    "production_gate_status",
                ],
                blocked_actions=[
                    "claim_unverified_product_fact",
                    "use_brand_or_person_without_rights",
                    "treat_text_brief_as_generated_asset",
                    "publish_asset_before_manifest_review",
                    "call_live_media_provider_before_quota_gate",
                    "hide_media_cost_from_work_record",
                ],
            ),
            ProviderJobContract(
                key="media.fal_asset_generation",
                label="FAL media generation driver legacy alias",
                provider_family="media",
                used_by_tasks=["asset.brief"],
                required_secret_purpose="media_generation_api_key",
                timeout_seconds=60,
                max_attempts=1,
                queue="provider.media",
                output_packet="asset_manifest",
                source_record_type="media_provider",
                required_inputs=["product_facts", "image_count", "image_sizes", "scene_types"],
                normalized_outputs=["asset_type", "url_or_file_path", "dimensions_or_duration", "source_provider_or_upload", "cost_estimate", "review_status"],
                blocked_actions=[
                    "claim_unverified_product_fact",
                    "use_brand_or_person_without_rights",
                    "treat_fal_as_product_identity",
                ],
            ),
            ProviderJobContract(
                key="model.role_report_assist",
                label="Role report model assist",
                provider_family="model",
                used_by_tasks=[
                    "market.report",
                    "listing.package",
                    "asset.brief",
                    "customer.learn_product",
                    "finance.review",
                    "confirmation.package",
                    "ceo.final_report",
                ],
                required_secret_purpose="model_api_key",
                timeout_seconds=45,
                max_attempts=1,
                queue="provider.model",
                output_packet="role_report_sections",
                source_record_type="ai_inference",
                required_inputs=["task_type", "required_sections", "sanitized_context", "merchant_goal"],
                normalized_outputs=["merchant_readable_summary", "sections", "limits", "missing_inputs", "risk_flags"],
                blocked_actions=["real_platform_write", "guaranteed_sales_claim", "hide_pending_fact"],
            ),
        ]


def build_provider_job_contract_catalog() -> dict[str, Any]:
    return ProviderJobContractCatalog().to_dict()
