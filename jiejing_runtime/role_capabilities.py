"""Role capability map for migrating Hermes skills into Jiejing Runtime.

The SaaS front end should not expose these roles as the merchant's main mental
model. This map exists for the backend, adapters, and owner diagnostics so
Hermes can become a replaceable worker instead of a hard dependency.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .knowledge import KnowledgeBase, load_default_knowledge_base


@dataclass(slots=True)
class RoleCapability:
    role: str
    merchant_label: str
    internal_label: str
    current_hermes_capability: list[str]
    runtime_owned_assets: list[str]
    task_types: list[str]
    required_outputs: list[str]
    safety_boundary: list[str]
    migration_status: str
    next_runtime_steps: list[str]
    public_visibility: str = "internal_only"
    knowledge_items: int = 0
    gaps: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class RuntimeRoleCapabilityMap:
    """Maps Hermes' current role capabilities to Jiejing-owned Runtime assets."""

    version = "2026-05-14.1"

    def __init__(self, knowledge_base: KnowledgeBase | None = None) -> None:
        self.knowledge_base = knowledge_base or load_default_knowledge_base()

    def roles(self) -> list[RoleCapability]:
        roles = self._base_roles()
        knowledge_summary = self.knowledge_base.summary()
        role_counts = knowledge_summary.get("roles", {})
        for role in roles:
            role.knowledge_items = int(role_counts.get(role.role, 0))
        return roles

    def to_dict(self) -> dict[str, Any]:
        roles = self.roles()
        return {
            "version": self.version,
            "purpose": "Migrate Hermes role skills, SOPs, and output contracts into the Jiejing-owned Runtime boundary.",
            "merchant_model": "Merchant faces AI CEO, work records, source records, and confirmation center; internal roles remain backend execution units.",
            "roles": [role.to_dict() for role in roles],
            "summary": {
                "role_count": len(roles),
                "runtime_ready_roles": len([role for role in roles if role.migration_status in {"runtime_contract_ready", "runtime_partial"}]),
                "internal_only_roles": len([role for role in roles if role.public_visibility == "internal_only"]),
                "high_risk_actions_confirmed": True,
            },
        }

    def for_role(self, role_name: str) -> RoleCapability | None:
        for role in self.roles():
            if role.role == role_name:
                return role
        return None

    def _base_roles(self) -> list[RoleCapability]:
        return [
            RoleCapability(
                role="ceo",
                merchant_label="AI CEO",
                internal_label="Goal intake, orchestration, and final judgement",
                current_hermes_capability=[
                    "Receives merchant intent from Feishu/CLI-style entrypoints.",
                    "Splits the commerce chain into market, sourcing, listing, asset, service, finance, and confirmation work.",
                    "Summarizes progress and keeps high-risk execution behind confirmation.",
                ],
                runtime_owned_assets=[
                    "JiejingTask protocol",
                    "ProductWorkflowRequest",
                    "11-step product workflow template",
                    "Confirmation package task",
                    "Runtime summary and audit log",
                ],
                task_types=["ceo.intake", "confirmation.package", "ceo.final_report"],
                required_outputs=["goal boundary", "task split", "blocking gaps", "confirmation summary", "next minimum action"],
                safety_boundary=[
                    "Do not bypass confirmation center.",
                    "Do not present Hermes as public product.",
                    "Do not claim real execution unless ExecutionService confirms it.",
                ],
                migration_status="runtime_contract_ready",
                next_runtime_steps=[
                    "Add live run-state heartbeat for each downstream task.",
                    "Connect Feishu CEO handoff through Runtime instead of free-form task messages.",
                ],
            ),
            RoleCapability(
                role="market-manager",
                merchant_label="Market report",
                internal_label="Market data packet and market judgement",
                current_hermes_capability=[
                    "Writes structured eBay market reports when prompt scope is controlled.",
                    "Can use Jiejing market-report skill and source-health rules.",
                    "Times out when asked to collect too much data and write a full report in one job.",
                ],
                runtime_owned_assets=[
                    "market.data_packet task",
                    "MarketDataPacketBuilder",
                    "Hermes handoff importer section-gap checks",
                    "source confidence and missing live data blockers",
                ],
                task_types=["market.data_packet", "market.report"],
                required_outputs=[
                    "source health",
                    "eBay price bands",
                    "Top 5 competitor breakdown",
                    "buyer pain points",
                    "keywords",
                    "recommendation and next step",
                ],
                safety_boundary=[
                    "AI inference must be labeled.",
                    "No market report is source-backed until eBay/source/logistics probes are ready.",
                    "No transition to publish-ready listing when required market sections are missing.",
                ],
                migration_status="runtime_partial",
                next_runtime_steps=[
                    "Implement eBay read-only probe adapter.",
                    "Implement public search probe adapter.",
                    "Feed compact data packet to Hermes only for judgement writing.",
                ],
                gaps=["live eBay probe", "public search probe", "source-backed Top 5 competitor data"],
            ),
            RoleCapability(
                role="product-manager",
                merchant_label="Listing and media package",
                internal_label="eBay listing package and asset brief",
                current_hermes_capability=[
                    "Generates eBay listing draft structure and media task packages from upstream reports.",
                    "Knows fixed eBay listing skeleton and category-dynamic item specifics boundary.",
                    "Can define image/video requirements but should not claim files exist without manifest.",
                ],
                runtime_owned_assets=[
                    "listing.package task contract",
                    "asset.brief task contract",
                    "publish blocker and business-policy blockers",
                    "media manifest rule",
                ],
                task_types=["listing.package", "asset.brief"],
                required_outputs=[
                    "SKU, title, category, condition, price, quantity",
                    "category item specifics",
                    "description HTML",
                    "pictures and video requirements",
                    "package facts",
                    "fulfillment/payment/return policy status",
                    "publish blockers",
                ],
                safety_boundary=[
                    "Do not invent policy IDs.",
                    "Do not publish or mark publish-ready without supplier facts, taxonomy validation, policies, and merchant confirmation.",
                    "Do not claim generated media files without file manifest.",
                ],
                migration_status="runtime_contract_ready",
                next_runtime_steps=[
                    "Add category-specific item-specific validator shell.",
                    "Add media manifest schema for generated images/video.",
                    "Connect product-manager handoff output into listing.package importer.",
                ],
                gaps=["real eBay taxonomy lookup", "real image/video generation manifest"],
            ),
            RoleCapability(
                role="customer-service",
                merchant_label="Auto customer service",
                internal_label="Product learning, reply templates, and escalation",
                current_hermes_capability=[
                    "Builds product-service learning files from market/listing/asset facts.",
                    "Defines low-risk FAQ and escalation boundaries.",
                    "Keeps sensitive buyer commitments gated.",
                ],
                runtime_owned_assets=[
                    "customer.learn_product task contract",
                    "product learning gate",
                    "auto-reply boundary rule",
                ],
                task_types=["customer.learn_product"],
                required_outputs=["product service file", "buyer question map", "FAQ", "reply boundary", "templates", "escalation rules"],
                safety_boundary=[
                    "No sensitive buyer promise without confirmation.",
                    "No product-specific auto reply before product file is learned.",
                    "Refunds, compensation, disputes, and policy exceptions escalate.",
                ],
                migration_status="runtime_contract_ready",
                next_runtime_steps=[
                    "Add stale product-file detector.",
                    "Add reply-risk classifier before automatic replies.",
                ],
                gaps=["real message ingestion", "reply classifier"],
            ),
            RoleCapability(
                role="finance-supply",
                merchant_label="Cost, sourcing, and fulfillment",
                internal_label="Supplier match, logistics, margin, and finance review",
                current_hermes_capability=[
                    "Organizes 1688/manual supplier facts, SpeedPAK/Orange Connex assumptions, and margin review.",
                    "Can identify missing cost, package, and logistics facts.",
                    "Needs real logistics/source adapters for production-grade numbers.",
                ],
                runtime_owned_assets=[
                    "source.match task contract",
                    "finance.review task contract",
                    "logistics_quote missing input",
                    "procurement confirmation boundary",
                ],
                task_types=["source.match", "finance.review"],
                required_outputs=["supplier candidates", "cost inputs", "package inputs", "logistics route", "net profit money", "return reserve", "risk notes"],
                safety_boundary=[
                    "Do not pay supplier or place procurement order without confirmation.",
                    "Do not claim final margin without final purchase cost and logistics quote.",
                    "Do not choose a route that violates platform/logistics restrictions.",
                ],
                migration_status="runtime_partial",
                next_runtime_steps=[
                    "Add 1688/source read snapshot adapter.",
                    "Add Orange Connex/SpeedPAK quote adapter shell.",
                    "Add finance report importer checks for money numbers.",
                ],
                gaps=["real source read", "real logistics quote", "fee model calibration"],
            ),
            RoleCapability(
                role="team-repair",
                merchant_label="Workflow health",
                internal_label="Compliance, timeout, and process repair",
                current_hermes_capability=[
                    "Audits workflow drift, empty outputs, stale files, and demo/real boundary mistakes.",
                    "Captures lessons from live Hermes tests and SaaS UI gaps.",
                ],
                runtime_owned_assets=[
                    "owner.review task contract",
                    "handoff importer empty-output detection",
                    "runtime regression tests",
                    "progress documents",
                ],
                task_types=["owner.review"],
                required_outputs=["runtime findings", "SaaS findings", "Hermes findings", "next improvements"],
                safety_boundary=[
                    "Do not rewrite product direction without owner intent.",
                    "Do not treat already-fixed problems as new without checking artifacts.",
                ],
                migration_status="runtime_contract_ready",
                next_runtime_steps=[
                    "Add automated health report over latest run directory.",
                    "Add timeout/error aggregation for SaaS operator panel.",
                ],
                gaps=["run health dashboard"],
            ),
            RoleCapability(
                role="web-engineer",
                merchant_label="SaaS product UI",
                internal_label="Frontend, demo flow, and public copy guardrails",
                current_hermes_capability=[
                    "Supports public/SaaS UI implementation and demo boundary checks.",
                    "Keeps merchant-facing language aligned with Jiejing, not Hermes.",
                ],
                runtime_owned_assets=[
                    "capability profile API",
                    "Runtime API bridge",
                    "public copy guardrails in knowledge pack",
                ],
                task_types=["owner.review"],
                required_outputs=["UI consistency findings", "copy boundary findings", "runtime panel readiness"],
                safety_boundary=[
                    "Public pages do not expose Hermes.",
                    "Public pages do not claim real customer cases or real API writes before connection.",
                ],
                migration_status="runtime_partial",
                next_runtime_steps=[
                    "Expose role capability map in SaaS operator diagnostics.",
                    "Map data-packet state to merchant-readable work records.",
                ],
                gaps=["production frontend/backend separation"],
            ),
            RoleCapability(
                role="desktop-engineer",
                merchant_label="Desktop automation boundary",
                internal_label="Desktop tooling, browser, and local operator helpers",
                current_hermes_capability=[
                    "Can support local development helpers, browser/debug scripts, and desktop-side validation.",
                    "Should not become the SaaS production execution path.",
                ],
                runtime_owned_assets=[
                    "local CLI",
                    "local API server",
                    "file handoff artifacts",
                ],
                task_types=["owner.review"],
                required_outputs=["local tool status", "operator helper notes", "non-production boundary"],
                safety_boundary=[
                    "Do not rely on local desktop automation for production SaaS execution.",
                    "Do not store credentials in frontend or public files.",
                ],
                migration_status="planned",
                next_runtime_steps=[
                    "Keep desktop helpers as dev-only tools.",
                    "Move production path to backend queue and cloud workers.",
                ],
                gaps=["cloud replacement for local helpers"],
            ),
            RoleCapability(
                role="mobile-engineer",
                merchant_label="Mobile experience boundary",
                internal_label="Mobile responsive SaaS review and future app path",
                current_hermes_capability=[
                    "Can support mobile UI review and future mobile experience planning.",
                    "Not central to the current eBay automation backend.",
                ],
                runtime_owned_assets=[
                    "mobile-safe confirmation boundary concept",
                    "responsive SaaS UI requirements",
                ],
                task_types=["owner.review"],
                required_outputs=["mobile usability findings", "confirmation usability findings"],
                safety_boundary=[
                    "Mobile must not hide high-risk confirmation context.",
                    "Mobile should prioritize AI CEO, confirmation center, order issues, and work records.",
                ],
                migration_status="planned",
                next_runtime_steps=[
                    "Add mobile confirmation-readiness checklist.",
                    "Keep heavy operator controls on desktop until productized.",
                ],
                gaps=["mobile app/runtime integration"],
            ),
        ]
