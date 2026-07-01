"""Jiejing Agent Runtime MVP package.

This package is the first owned execution base for Jiejing. It does not replace
Hermes yet; it defines the task runner, adapter boundary, safety gate, and file
store that future backend code can call.
"""

from .runtime import JiejingRuntime, RuntimeConfig, RuntimeRunSummary
from .adapters import JiejingAgentAdapter
from .agent_team import AgentRoleSpec, AgentToolPermission, JiejingAgentTeam
from .agent_quality_gate import OwnedAgentQualityGate
from .owned_agents import OwnedAgentExecutor
from .execution import ExecutionRequest, ExecutionResult, ExecutionService
from .execution_preflight import ExecutionPreflightChecker
from .model_clients import (
    OpenAICompatibleModelClient,
    OpenAIResponsesModelClient,
    DeepSeekModelClient,
    RuleBasedModelClient,
    model_client_from_env,
    model_client_status_from_env,
)
from .repository import SQLiteRuntimeRepository
from .tools_registry import ToolRegistry, ToolSpec
from .knowledge import KnowledgeBase, KnowledgeItem, KnowledgePack, load_default_knowledge_base
from .long_term_memory import LongTermMemoryRecord, build_memory_record, memory_candidates_from_result
from .creative_capabilities import CreativeCapabilityProfile
from .workflow_templates import ProductWorkflowRequest, build_product_workflow
from .merchant_profile import MerchantOperatingProfile, build_default_merchant_profile, build_merchant_profile, merchant_profile_defaults
from .report_contracts import RoleReportContractValidator, validate_role_report_contract
from .capabilities import RuntimeCapabilityProfile
from .hermes_handoff import HermesHandoffResultImporter
from .market_data_packet import MarketDataPacketBuilder
from .role_capabilities import RoleCapability, RuntimeRoleCapabilityMap
from .ebay_read_only import EbayReadOnlyProbeAdapter, EbayReadOnlyProbeConfig
from .public_search import PublicSearchProbeAdapter, PublicSearchProbeConfig
from .cross_platform_reference import CrossPlatformReferenceAdapter, CrossPlatformReferenceConfig
from .sourcing_availability import SourcingAvailabilityAdapter, SourcingAvailabilityConfig
from .logistics_estimate import LogisticsEstimateAdapter, LogisticsEstimateConfig
from .ebay_listing_metadata import EbayListingMetadataAdapter, EbayListingMetadataConfig
from .ebay_credentials import EbayCredentialResolver
from .ebay_provider_status import EbayProviderStatus
from .media_generation import MediaGenerationAdapter, MediaGenerationConfig
from .media_capability_router import build_media_capability_router
from .tool_orchestrator import JiejingToolOrchestrator
from .shadow_compare import RuntimeComparisonScorer
from .listing_package import ListingPackageValidator
from .asset_manifest import AssetManifestValidator
from .customer_learning import CustomerLearningValidator
from .finance_review import FinanceReviewValidator
from .confirmation_package import ConfirmationPackageValidator
from .ceo_final_report import CeoFinalReportValidator
from .saas_snapshot import build_saas_snapshot
from .progress_scorecard import build_progress_scorecard
from .replacement_readiness import build_replacement_readiness
from .provider_job_contracts import ProviderJobContractCatalog, build_provider_job_contract_catalog
from .agent_provider_plan import build_agent_provider_execution_plan

__all__ = [
    "JiejingRuntime",
    "JiejingAgentAdapter",
    "RuntimeConfig",
    "RuntimeRunSummary",
    "AgentRoleSpec",
    "AgentToolPermission",
    "JiejingAgentTeam",
    "OwnedAgentQualityGate",
    "OwnedAgentExecutor",
    "ExecutionRequest",
    "ExecutionResult",
    "ExecutionService",
    "ExecutionPreflightChecker",
    "OpenAICompatibleModelClient",
    "OpenAIResponsesModelClient",
    "DeepSeekModelClient",
    "RuleBasedModelClient",
    "model_client_from_env",
    "model_client_status_from_env",
    "SQLiteRuntimeRepository",
    "ToolRegistry",
    "ToolSpec",
    "KnowledgeBase",
    "KnowledgeItem",
    "KnowledgePack",
    "load_default_knowledge_base",
    "LongTermMemoryRecord",
    "build_memory_record",
    "memory_candidates_from_result",
    "CreativeCapabilityProfile",
    "ProductWorkflowRequest",
    "build_product_workflow",
    "MerchantOperatingProfile",
    "build_default_merchant_profile",
    "build_merchant_profile",
    "merchant_profile_defaults",
    "RoleReportContractValidator",
    "validate_role_report_contract",
    "RuntimeCapabilityProfile",
    "HermesHandoffResultImporter",
    "MarketDataPacketBuilder",
    "RoleCapability",
    "RuntimeRoleCapabilityMap",
    "EbayReadOnlyProbeAdapter",
    "EbayReadOnlyProbeConfig",
    "PublicSearchProbeAdapter",
    "PublicSearchProbeConfig",
    "CrossPlatformReferenceAdapter",
    "CrossPlatformReferenceConfig",
    "SourcingAvailabilityAdapter",
    "SourcingAvailabilityConfig",
    "LogisticsEstimateAdapter",
    "LogisticsEstimateConfig",
    "EbayListingMetadataAdapter",
    "EbayListingMetadataConfig",
    "EbayCredentialResolver",
    "EbayProviderStatus",
    "MediaGenerationAdapter",
    "MediaGenerationConfig",
    "build_media_capability_router",
    "JiejingToolOrchestrator",
    "RuntimeComparisonScorer",
    "ListingPackageValidator",
    "AssetManifestValidator",
    "CustomerLearningValidator",
    "FinanceReviewValidator",
    "ConfirmationPackageValidator",
    "CeoFinalReportValidator",
    "build_saas_snapshot",
    "build_progress_scorecard",
    "build_replacement_readiness",
    "ProviderJobContractCatalog",
    "build_provider_job_contract_catalog",
    "build_agent_provider_execution_plan",
]
