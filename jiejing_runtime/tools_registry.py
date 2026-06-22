"""Tool registry boundary for Jiejing Agent Runtime.

This module records which external capabilities the runtime knows about. The
MVP does not execute these tools. Production adapters can bind real providers
behind the same tool names while keeping permissions and confirmation rules
centralized.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ToolSpec:
    name: str
    category: str
    description: str
    enabled: bool = False
    requires_confirmation: bool = False
    allowed_task_types: list[str] = field(default_factory=list)
    forbidden_actions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "category": self.category,
            "description": self.description,
            "enabled": self.enabled,
            "requires_confirmation": self.requires_confirmation,
            "allowed_task_types": self.allowed_task_types,
            "forbidden_actions": self.forbidden_actions,
        }


class ToolRegistry:
    def __init__(self, tools: list[ToolSpec] | None = None) -> None:
        self._tools = {tool.name: tool for tool in (tools or self.default_tools())}

    def list_tools(self) -> list[dict[str, Any]]:
        return [tool.to_dict() for tool in self._tools.values()]

    def get(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    def enabled_for_task(self, task_type: str) -> list[ToolSpec]:
        return [
            tool
            for tool in self._tools.values()
            if tool.enabled and (not tool.allowed_task_types or task_type in tool.allowed_task_types)
        ]

    @staticmethod
    def default_tools() -> list[ToolSpec]:
        return [
            ToolSpec(
                name="web.public_search",
                category="research",
                description="Search public web pages and label source confidence.",
                enabled=False,
                allowed_task_types=["market.data_packet", "market.report"],
            ),
            ToolSpec(
                name="ebay.read_only",
                category="platform_api",
                description="Read authorized eBay store, listing, order, fee, and policy data.",
                enabled=False,
                allowed_task_types=["market.data_packet", "listing.package", "finance.review"],
            ),
            ToolSpec(
                name="ebay.listing_metadata_read",
                category="platform_api",
                description="Read Taxonomy item specifics and Account API fulfillment/payment/return policies for draft listings.",
                enabled=False,
                allowed_task_types=["listing.package"],
                forbidden_actions=["publish_listing", "edit_business_policy", "change_inventory"],
            ),
            ToolSpec(
                name="ebay.execution",
                category="platform_api",
                description="Execute confirmed eBay writes through ExecutionService only.",
                enabled=False,
                requires_confirmation=True,
                allowed_task_types=["confirmation.package"],
                forbidden_actions=["publish_without_confirmation", "refund_without_confirmation", "policy_edit_without_confirmation"],
            ),
            ToolSpec(
                name="sourcing.1688_read",
                category="sourcing",
                description="Read 1688 product, price, SKU, stock, supplier, and origin data when authorized or supplied.",
                enabled=False,
                allowed_task_types=["market.data_packet", "source.match", "finance.review"],
            ),
            ToolSpec(
                name="logistics.orange_connex_estimate",
                category="logistics",
                description="Estimate SpeedPAK / Orange Connex shipping options and limits.",
                enabled=False,
                allowed_task_types=["market.data_packet", "source.match", "finance.review"],
            ),
            ToolSpec(
                name="market.cross_platform_reference",
                category="research",
                description="Collect public or authorized cross-platform reference signals without treating them as official eBay data.",
                enabled=False,
                allowed_task_types=["market.data_packet", "market.report"],
            ),
            ToolSpec(
                name="asset.image_video_generation",
                category="asset",
                description="Generate product images, detail images, scene images, and video briefs/assets.",
                enabled=False,
                allowed_task_types=["asset.brief"],
            ),
            ToolSpec(
                name="asset.open_design_workflow",
                category="asset",
                description="Create design directions, image styles, detail-page layout, and critique checklists using Jiejing-owned Open Design style rules.",
                enabled=False,
                allowed_task_types=["asset.brief", "listing.package"],
            ),
            ToolSpec(
                name="asset.image_generation_provider",
                category="asset",
                description="Provider-neutral adapter for generating main images, scene images, detail pages, and dimension images.",
                enabled=False,
                allowed_task_types=["asset.brief"],
                forbidden_actions=["claim_generated_files_without_manifest", "invent_unverified_product_claims"],
            ),
            ToolSpec(
                name="asset.video_generation_provider",
                category="asset",
                description="Provider-neutral adapter for producing product demo videos, covers, subtitles, and talking-head variants.",
                enabled=False,
                allowed_task_types=["asset.brief"],
                forbidden_actions=["fake_testimonial", "unsupported_product_demo", "use_person_likeness_without_rights"],
            ),
            ToolSpec(
                name="runtime.long_term_memory",
                category="memory",
                description="Store and retrieve sanitized merchant, store, product, workflow, and role lessons.",
                enabled=False,
                allowed_task_types=[
                    "ceo.intake",
                    "market.report",
                    "source.match",
                    "listing.package",
                    "asset.brief",
                    "customer.learn_product",
                    "finance.review",
                    "confirmation.package",
                    "ceo.final_report",
                ],
                forbidden_actions=["store_credentials", "store_buyer_private_data", "grant_execution_authority"],
            ),
        ]
