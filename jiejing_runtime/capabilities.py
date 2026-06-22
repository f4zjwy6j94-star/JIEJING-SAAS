"""Runtime capability profile for SaaS and operator visibility."""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .agent_team import JiejingAgentTeam
from .agent_quality_gate import OwnedAgentQualityGate
from .creative_capabilities import CreativeCapabilityProfile
from .knowledge import load_default_knowledge_base
from .model_clients import model_client_status_from_env
from .owned_agents import OwnedAgentExecutor
from .public_search import PublicSearchProbeAdapter
from .media_generation import MediaGenerationAdapter
from .ebay_provider_status import EbayProviderStatus
from .execution_preflight import ExecutionPreflightChecker
from .repository import SQLiteRuntimeRepository
from .role_capabilities import RuntimeRoleCapabilityMap
from .tools_registry import ToolRegistry
from .provider_job_contracts import build_provider_job_contract_catalog


@dataclass(slots=True)
class CapabilityItem:
    key: str
    label: str
    status: str
    detail: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


class RuntimeCapabilityProfile:
    """Summarizes what the owned Runtime can safely do right now."""

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path

    def to_dict(self) -> dict[str, Any]:
        knowledge = load_default_knowledge_base().summary()
        knowledge_source_types = knowledge.get("source_types", {})
        role_capability_map = RuntimeRoleCapabilityMap().to_dict()
        owned_agent_team = JiejingAgentTeam().to_dict()
        owned_agent_executor = OwnedAgentExecutor().to_dict()
        owned_agent_quality_gate = OwnedAgentQualityGate().to_dict()
        tools = ToolRegistry().list_tools()
        model_status = model_client_status_from_env()
        tavily_status = PublicSearchProbeAdapter().provider_status("tavily")
        fal_status = MediaGenerationAdapter().provider_status("fal")
        ebay_status = EbayProviderStatus().to_dict()
        creative_profile = CreativeCapabilityProfile().to_dict()
        execution_preflight = ExecutionPreflightChecker().contract()
        provider_job_contracts = build_provider_job_contract_catalog()
        memory_summary = SQLiteRuntimeRepository(self.db_path).get_memory_summary() if self.db_path else {"record_count": 0}
        handoff_dir = Path(
            os.environ.get("JIEJING_HERMES_HANDOFF_DIR")
            or Path(__file__).resolve().parents[1] / "output" / "jiejing-hermes-handoff"
        )
        items = [
            CapabilityItem(
                "task_protocol",
                "JiejingTask protocol",
                "ready",
                "Runtime can create and validate the 11-step eBay product workflow.",
            ),
            CapabilityItem(
                "knowledge_pack",
                "Sanitized Jiejing/Hermes knowledge pack",
                "ready" if knowledge.get("item_count", 0) else "missing",
                f"{knowledge.get('item_count', 0)} sanitized knowledge items are available.",
            ),
            CapabilityItem(
                "long_term_memory",
                "Runtime long-term memory",
                "ready" if memory_summary.get("record_count", 0) else "empty_ready",
                (
                    f"{memory_summary.get('record_count', 0)} sanitized memory records are stored. "
                    "Credentials, buyer private data, and execution authority are excluded."
                ),
            ),
            CapabilityItem(
                "hermes_asset_migration",
                "Current Hermes asset migration",
                "ready"
                if knowledge_source_types.get("hermes_current_shared_note")
                and knowledge_source_types.get("hermes_current_skill")
                and knowledge_source_types.get("hermes_profile_inventory")
                and knowledge_source_types.get("hermes_config_inventory")
                else "partial",
                (
                    f"{knowledge_source_types.get('hermes_current_shared_note', 0)} shared notes, "
                    f"{knowledge_source_types.get('hermes_current_skill', 0)} skills, profile inventory, "
                    "and safe config inventory are migrated without raw secrets."
                ),
            ),
            CapabilityItem(
                "model_client",
                "Configurable model client",
                "configured" if model_status.get("configured") else "fallback",
                "Uses live model only when endpoint, key, and model are configured; otherwise rule-based fallback.",
            ),
            CapabilityItem(
                "merchant_operating_profile",
                "Merchant operating profile",
                "ready",
                "Runtime can carry stage, sourcing, fulfillment, risk, media, customer-service, and confirmation preferences through every task.",
            ),
            CapabilityItem(
                "role_report_contract",
                "Role report contract",
                "ready",
                "Runtime validates required report sections for market, listing, asset, service, finance, confirmation, and CEO handoff outputs.",
            ),
            CapabilityItem(
                "owned_agent_team",
                "Jiejing-owned commerce Agent Team",
                "ready_contract",
                f"{owned_agent_team['role_count']} commerce roles own task permissions, forbidden actions, quality gates, and handoff contracts before any model call.",
            ),
            CapabilityItem(
                "owned_agent_execution",
                "Jiejing-owned role execution",
                "local_ready",
                (
                    f"{owned_agent_executor['agent_count']} role agents can generate commerce-specific reports locally "
                    "for market, sourcing, listing, assets, service, finance, confirmation, and CEO handoff tasks."
                ),
            ),
            CapabilityItem(
                "owned_agent_quality_gate",
                "Owned Agent report quality gate",
                "ready",
                (
                    "Every owned role report can be checked for required sections, source discipline, "
                    "pending facts, forbidden claims, and no-real-execution boundaries before handoff."
                ),
            ),
            CapabilityItem(
                "creative_engine_contract",
                "Design, image, and video capability contract",
                "ready",
                (
                    f"{len(creative_profile.get('capabilities', []))} creative capability contracts are mapped; "
                    "real images/video require configured providers and asset manifests."
                ),
            ),
            CapabilityItem(
                "market_data_packet",
                "Market data packet split layer",
                "ready",
                "Runtime can separate eBay signal, public search, cross-platform reference, sourcing availability, and logistics facts before Hermes writes a report.",
            ),
            CapabilityItem(
                "ebay_read_only_probe",
                "eBay read-only probe adapter shell",
                "credential_ready" if ebay_status.get("credential_present") else "ready",
                (
                    "Runtime can normalize Browse/Taxonomy snapshots and has a guarded live-read shell; "
                    f"credential_present={ebay_status.get('credential_present')}. No eBay writes are implemented."
                ),
            ),
            CapabilityItem(
                "ebay_listing_metadata_read",
                "eBay listing metadata reader",
                "ready",
                "Product Agent can read or normalize Taxonomy item specifics and Account API policy snapshots; publish and policy edits stay blocked.",
            ),
            CapabilityItem(
                "public_search_probe",
                "Public search probe and Tavily provider",
                "configured" if tavily_status.get("configured") else "ready_contract",
                (
                    "Runtime can normalize public search snapshots and can run Tavily public search when explicitly enabled; "
                    f"provider configured={tavily_status.get('configured')}, host={tavily_status.get('endpoint_host') or 'pending'}."
                ),
            ),
            CapabilityItem(
                "cross_platform_reference_probe",
                "Cross-platform reference probe adapter shell",
                "ready",
                "Runtime can normalize public or authorized references from Amazon, 1688, Taobao, Pinduoduo, Shopify, and similar platforms as directional context.",
            ),
            CapabilityItem(
                "sourcing_availability_probe",
                "Sourcing availability probe adapter shell",
                "ready",
                "Runtime can normalize 1688 links, merchant links, supplier quotes, tables, and authorized source snapshots without ordering or paying.",
            ),
            CapabilityItem(
                "logistics_estimate_probe",
                "Logistics estimate probe adapter shell",
                "ready",
                "Runtime can normalize package facts and shipping estimates without buying labels or writing tracking.",
            ),
            CapabilityItem(
                "media_generation_provider",
                "Image/video generation provider boundary",
                "configured" if fal_status.get("configured") else "ready_contract",
                (
                    "Asset Agent can accept real provider manifests or call configured image/video endpoints; "
                    f"FAL configured={fal_status.get('configured')}. No generated asset is claimed without a manifest."
                ),
            ),
            CapabilityItem(
                "provider_job_contracts",
                "Provider job contracts",
                "ready_contract",
                (
                    f"{provider_job_contracts.get('contract_count', 0)} provider job contracts define task-scoped secrets, "
                    "timeouts, retries, output packets, source records, and no-real-execution boundaries."
                ),
            ),
            CapabilityItem(
                "same_topic_shadow_compare",
                "Hermes same-topic comparison scorer",
                "ready_contract",
                "Runtime can compare Jiejing and Hermes outputs by section coverage, source records, blockers, confirmations, and forbidden execution claims.",
            ),
            CapabilityItem(
                "hermes_shadow",
                "Hermes shadow dispatch",
                "ready",
                "Runtime can translate tasks into role-specific Hermes dispatch packets without calling Hermes.",
            ),
            CapabilityItem(
                "hermes_file_handoff",
                "Hermes file handoff",
                "ready",
                f"Sanitized handoff files are written under {handoff_dir}.",
            ),
            CapabilityItem(
                "confirmation_center",
                "Confirmation center boundary",
                "ready",
                "High-risk actions produce confirmation items and are held for ExecutionService.",
            ),
            CapabilityItem(
                "execution_preflight",
                "Execution preflight contract",
                "ready_contract",
                "Confirmed actions are checked for listing facts, policy IDs, supplier facts, media, finance, and action-specific payload before any platform adapter can run.",
            ),
            CapabilityItem(
                "role_capability_map",
                "Hermes-to-Runtime role capability map",
                "ready",
                f"{role_capability_map['summary']['role_count']} internal role capabilities are mapped for migration.",
            ),
            CapabilityItem(
                "real_execution",
                "Real eBay/payment/logistics execution",
                "blocked",
                "No real publish, payment, refund, ad, procurement, or policy write is allowed in this runtime mode.",
            ),
            CapabilityItem(
                "production_backend",
                "Production SaaS backend",
                "partial",
                "Local API and SQLite exist; multi-tenant auth, queue, vault, and cloud database are not production-ready.",
            ),
        ]
        return {
            "runtime": "jiejing-runtime",
            "profile_version": "2026-05-15.1",
            "db_path": str(self.db_path) if self.db_path else None,
            "knowledge": knowledge,
            "long_term_memory": memory_summary,
            "creative": creative_profile,
            "role_capability_map": role_capability_map,
            "owned_agent_team": owned_agent_team,
            "owned_agent_executor": owned_agent_executor,
            "owned_agent_quality_gate": owned_agent_quality_gate,
            "tools": {
                "registered_count": len(tools),
                "enabled_count": len([tool for tool in tools if tool.get("enabled")]),
            },
            "provider_status": {
                "public_search_tavily": tavily_status,
                "media_fal": fal_status,
                "ebay": ebay_status,
            },
            "provider_job_contracts": provider_job_contracts,
            "execution_preflight": execution_preflight,
            "capabilities": [item.to_dict() for item in items],
            "safe_to_demo": True,
            "safe_to_execute_real_platform_actions": False,
        }
