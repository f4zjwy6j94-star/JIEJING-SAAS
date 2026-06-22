#!/usr/bin/env python3
"""Build a sanitized Runtime knowledge pack from curated Jiejing/Hermes assets."""

from __future__ import annotations

import sys
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
HERMES_ROOT = ROOT.parent
CODEX_HOME = Path.home() / ".codex"
WSL_HERMES_HOME = Path(r"\\wsl.localhost\Ubuntu\home\hermes\.hermes")
WSL_HERMES_SHARED = WSL_HERMES_HOME / "shared"
WSL_HERMES_SKILLS = WSL_HERMES_HOME / "skills"
WSL_HERMES_PROFILES = WSL_HERMES_HOME / "profiles"
WSL_HERMES_CONFIG = WSL_HERMES_HOME / "config.yaml"
WSL_HERMES_ENV = WSL_HERMES_HOME / ".env"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_runtime.knowledge import (  # noqa: E402
    DEFAULT_KNOWLEDGE_DIR,
    KNOWLEDGE_VERSION,
    KnowledgeItem,
    KnowledgePack,
    compact_content,
    make_item_id,
    now_iso,
    sanitize_text,
    write_knowledge_pack,
)


@dataclass(slots=True)
class SourceSpec:
    base: Path
    path: str
    title: str
    role: str
    task_types: list[str]
    tags: list[str]
    priority: int = 50
    source_type: str = "curated_file"
    source_ref: str | None = None


CURATED_SOURCES = [
    SourceSpec(
        HERMES_ROOT,
        "patch_work/hermes-skills/ceo/jiejing-ceo-orchestration/SKILL.md",
        "CEO orchestration and productized gate flow",
        "ceo",
        ["ceo.intake", "ceo.final_report", "confirmation.package"],
        ["role", "orchestration", "task_split", "confirmation"],
        95,
    ),
    SourceSpec(
        HERMES_ROOT,
        "patch_work/hermes-skills/market-manager/jiejing-ebay-market-report/SKILL.md",
        "Market manager report standard and data packet rule",
        "market-manager",
        ["market.data_packet", "market.report"],
        ["market", "report", "source_health", "ebay"],
        95,
    ),
    SourceSpec(
        HERMES_ROOT,
        "patch_work/hermes-skills/product-manager/jiejing-listing-media-package/SKILL.md",
        "Product manager listing and media package standard",
        "product-manager",
        ["listing.package", "asset.brief", "customer.learn_product"],
        ["listing", "media", "ebay", "publish_lock"],
        95,
    ),
    SourceSpec(
        HERMES_ROOT,
        "patch_work/hermes-skills/customer-service/product-customer-service-brief/SKILL.md",
        "Customer service product learning gate",
        "customer-service",
        ["customer.learn_product"],
        ["customer_service", "automation_boundary", "faq"],
        90,
    ),
    SourceSpec(
        HERMES_ROOT,
        "patch_work/hermes-skills/finance-supply/jiejing-profit-fulfillment-supply-chain/SKILL.md",
        "Finance supply fulfillment and SpeedPAK discipline",
        "finance-supply",
        ["source.match", "finance.review"],
        ["finance", "sourcing", "fulfillment", "speedpak"],
        95,
    ),
    SourceSpec(
        HERMES_ROOT,
        "patch_work/hermes-skills/team-repair/jiejing-demo-compliance-audit/SKILL.md",
        "Team repair compliance and workflow health checklist",
        "team-repair",
        ["owner.review", "ceo.final_report"],
        ["repair", "audit", "demo_boundary", "workflow_health"],
        85,
    ),
    SourceSpec(
        HERMES_ROOT,
        "output/JIEJING_HERMES_CEO_EXECUTION_SOP_20260513.md",
        "CEO execution SOP snapshot",
        "ceo",
        ["ceo.intake", "ceo.final_report"],
        ["sop", "closed_loop"],
        75,
    ),
    SourceSpec(
        HERMES_ROOT,
        "output/JIEJING_CEO_EXECUTION_SOP_20260513.md",
        "Jiejing CEO execution SOP snapshot",
        "ceo",
        ["ceo.intake", "ceo.final_report"],
        ["sop", "closed_loop"],
        75,
    ),
    SourceSpec(
        HERMES_ROOT,
        "output/JIEJING_HERMES_KANBAN_INTEGRATION_20260513.md",
        "Kanban integration as internal task split layer",
        "all",
        ["ceo.intake", "owner.review"],
        ["kanban", "task_split", "internal_only"],
        70,
    ),
    SourceSpec(
        HERMES_ROOT,
        "output/JIEJING_SPEEDPAK_ORANGE_CONNEX_POLICY_RESEARCH_20260514.md",
        "SpeedPAK Orange Connex policy research",
        "finance-supply",
        ["finance.review"],
        ["speedpak", "orange_connex", "logistics"],
        80,
    ),
    SourceSpec(
        HERMES_ROOT,
        "output/cable-clips-pdf-staging-20260513/02_market_manager.md",
        "Sample market manager report structure",
        "market-manager",
        ["market.report"],
        ["sample", "market", "report"],
        65,
    ),
    SourceSpec(
        HERMES_ROOT,
        "output/cable-clips-pdf-staging-20260513/04_product_listing.md",
        "Sample product listing report structure",
        "product-manager",
        ["listing.package"],
        ["sample", "listing", "report"],
        65,
    ),
    SourceSpec(
        HERMES_ROOT,
        "output/cable-clips-pdf-staging-20260513/05_asset_workshop.md",
        "Sample asset workshop task package",
        "product-manager",
        ["asset.brief"],
        ["sample", "media", "asset_workshop"],
        60,
    ),
    SourceSpec(
        HERMES_ROOT,
        "output/cable-clips-pdf-staging-20260513/06_customer_service.md",
        "Sample customer service learning package",
        "customer-service",
        ["customer.learn_product"],
        ["sample", "customer_service"],
        60,
    ),
    SourceSpec(
        HERMES_ROOT,
        "output/cable-clips-pdf-staging-20260513/07_finance_final.md",
        "Sample finance final check",
        "finance-supply",
        ["finance.review"],
        ["sample", "finance"],
        60,
    ),
    SourceSpec(
        CODEX_HOME,
        "skills/jiejing-design-system/SKILL.md",
        "Jiejing SaaS design and public copy guardrails",
        "web-engineer",
        ["owner.review"],
        ["public_copy", "design_system", "demo_boundary"],
        70,
        source_ref="codex-skill:jiejing-design-system",
    ),
]


CURRENT_HERMES_SHARED_SOURCES = [
    SourceSpec(
        WSL_HERMES_SHARED,
        "PROJECT_STATE.md",
        "Current Hermes project state and business facts",
        "all",
        ["ceo.intake", "owner.review", "ceo.final_report"],
        ["current_state", "business_direction", "hermes_current"],
        100,
        "hermes_current_shared_note",
        "wsl-hermes-shared:PROJECT_STATE.md",
    ),
    SourceSpec(
        WSL_HERMES_SHARED,
        "CURRENT_SOURCE_OF_TRUTH_20260503.md",
        "Hermes current source of truth",
        "all",
        ["ceo.intake", "owner.review", "ceo.final_report"],
        ["source_of_truth", "role_boundary", "project_direction"],
        98,
        "hermes_current_shared_note",
        "wsl-hermes-shared:CURRENT_SOURCE_OF_TRUTH_20260503.md",
    ),
    SourceSpec(
        WSL_HERMES_SHARED,
        "SOFTWARE_PRODUCT_DIRECTION.md",
        "Jiejing software product direction",
        "all",
        ["ceo.intake", "owner.review"],
        ["product_direction", "saas", "positioning"],
        95,
        "hermes_current_shared_note",
        "wsl-hermes-shared:SOFTWARE_PRODUCT_DIRECTION.md",
    ),
    SourceSpec(
        WSL_HERMES_SHARED,
        "AI_ASSISTED_EBAY_OPERATING_SOP.md",
        "AI-assisted eBay operating SOP",
        "all",
        ["market.report", "source.match", "listing.package", "customer.learn_product", "finance.review"],
        ["ebay", "sop", "closed_loop"],
        95,
        "hermes_current_shared_note",
        "wsl-hermes-shared:AI_ASSISTED_EBAY_OPERATING_SOP.md",
    ),
    SourceSpec(
        WSL_HERMES_SHARED,
        "JIEJING_SAAS_CURRENT_WORKFLOW_SYNC_20260511.md",
        "Current SaaS workflow sync",
        "all",
        ["ceo.intake", "owner.review", "confirmation.package"],
        ["saas_flow", "workflow", "alignment"],
        95,
        "hermes_current_shared_note",
        "wsl-hermes-shared:JIEJING_SAAS_CURRENT_WORKFLOW_SYNC_20260511.md",
    ),
    SourceSpec(
        WSL_HERMES_SHARED,
        "JIEJING_SAAS_TASK_SPLIT_DATA_PACKET_RULE_20260512.md",
        "Task split and market data packet rule",
        "market-manager",
        ["market.data_packet", "market.report", "owner.review"],
        ["task_split", "timeout", "market_data_packet"],
        100,
        "hermes_current_shared_note",
        "wsl-hermes-shared:JIEJING_SAAS_TASK_SPLIT_DATA_PACKET_RULE_20260512.md",
    ),
    SourceSpec(
        WSL_HERMES_SHARED,
        "JIEJING_SAAS_HERMES_CLOSED_LOOP_LESSONS_20260514.md",
        "Closed-loop test lessons",
        "all",
        ["ceo.final_report", "owner.review", "confirmation.package"],
        ["closed_loop", "lessons", "productized_gate"],
        100,
        "hermes_current_shared_note",
        "wsl-hermes-shared:JIEJING_SAAS_HERMES_CLOSED_LOOP_LESSONS_20260514.md",
    ),
    SourceSpec(
        WSL_HERMES_SHARED,
        "JIEJING_SPEEDPAK_ORANGE_CONNEX_POLICY_RESEARCH_20260514.md",
        "SpeedPAK and Orange Connex policy research",
        "finance-supply",
        ["finance.review", "source.match"],
        ["logistics", "speedpak", "orange_connex"],
        95,
        "hermes_current_shared_note",
        "wsl-hermes-shared:JIEJING_SPEEDPAK_ORANGE_CONNEX_POLICY_RESEARCH_20260514.md",
    ),
    SourceSpec(
        WSL_HERMES_SHARED,
        "JIEJING_EBAY_PLATFORM_KNOWLEDGE_V01_20260504.md",
        "eBay platform knowledge",
        "all",
        ["market.report", "listing.package", "confirmation.package"],
        ["ebay", "platform_rules", "listing"],
        95,
        "hermes_current_shared_note",
        "wsl-hermes-shared:JIEJING_EBAY_PLATFORM_KNOWLEDGE_V01_20260504.md",
    ),
    SourceSpec(
        WSL_HERMES_SHARED,
        "JIEJING_HERMES_CEO_EXECUTION_SOP_20260513.md",
        "CEO execution SOP from Hermes",
        "ceo",
        ["ceo.intake", "ceo.final_report", "owner.review"],
        ["ceo", "sop", "orchestration"],
        95,
        "hermes_current_shared_note",
        "wsl-hermes-shared:JIEJING_HERMES_CEO_EXECUTION_SOP_20260513.md",
    ),
    SourceSpec(
        WSL_HERMES_SHARED,
        "PRODUCT_MANAGER_MEDIA_CAPABILITY_BOUNDARY.md",
        "Product manager media capability boundary",
        "product-manager",
        ["listing.package", "asset.brief"],
        ["media", "asset_workshop", "boundary"],
        95,
        "hermes_current_shared_note",
        "wsl-hermes-shared:PRODUCT_MANAGER_MEDIA_CAPABILITY_BOUNDARY.md",
    ),
    SourceSpec(
        WSL_HERMES_SHARED,
        "MERCHANT_CONFIGURATION_SPEC.md",
        "Merchant configuration spec",
        "all",
        ["ceo.intake", "source.match", "confirmation.package"],
        ["merchant_profile", "configuration", "permissions"],
        92,
        "hermes_current_shared_note",
        "wsl-hermes-shared:MERCHANT_CONFIGURATION_SPEC.md",
    ),
    SourceSpec(
        WSL_HERMES_SHARED,
        "HUMAN_REVIEW_BOUNDARY.md",
        "Human review boundary",
        "all",
        ["confirmation.package", "listing.package", "finance.review", "customer.learn_product"],
        ["confirmation", "human_review", "safety"],
        100,
        "hermes_current_shared_note",
        "wsl-hermes-shared:HUMAN_REVIEW_BOUNDARY.md",
    ),
    SourceSpec(
        WSL_HERMES_SHARED,
        "TEAM_OPERATING_MODEL.md",
        "Hermes team operating model",
        "all",
        ["ceo.intake", "owner.review"],
        ["role_model", "team", "migration"],
        90,
        "hermes_current_shared_note",
        "wsl-hermes-shared:TEAM_OPERATING_MODEL.md",
    ),
    SourceSpec(
        WSL_HERMES_SHARED,
        "ROLE_ALIGNMENT_MATRIX_20260430.md",
        "Role alignment matrix",
        "all",
        ["ceo.intake", "owner.review"],
        ["role_alignment", "migration"],
        90,
        "hermes_current_shared_note",
        "wsl-hermes-shared:ROLE_ALIGNMENT_MATRIX_20260430.md",
    ),
    SourceSpec(
        WSL_HERMES_SHARED,
        "EXECUTION_CLOSED_LOOP_SYSTEM.md",
        "Execution closed-loop system",
        "all",
        ["ceo.intake", "ceo.final_report", "owner.review"],
        ["closed_loop", "execution", "workflow"],
        92,
        "hermes_current_shared_note",
        "wsl-hermes-shared:EXECUTION_CLOSED_LOOP_SYSTEM.md",
    ),
    SourceSpec(
        WSL_HERMES_SHARED,
        "STAINLESS_CUP_HERMES_VALIDATION_REPORT_20260512.md",
        "Stainless cup Hermes validation report",
        "all",
        ["market.report", "listing.package", "finance.review", "ceo.final_report"],
        ["sample", "validation", "stainless_cup"],
        82,
        "hermes_current_shared_note",
        "wsl-hermes-shared:STAINLESS_CUP_HERMES_VALIDATION_REPORT_20260512.md",
    ),
    SourceSpec(
        WSL_HERMES_SHARED,
        "FINAL_MOCK_CLOSED_LOOP_STAINLESS_CUP_20260513.md",
        "Final mock closed-loop stainless cup sample",
        "all",
        ["ceo.final_report", "owner.review"],
        ["sample", "closed_loop"],
        80,
        "hermes_current_shared_note",
        "wsl-hermes-shared:FINAL_MOCK_CLOSED_LOOP_STAINLESS_CUP_20260513.md",
    ),
]


CURRENT_HERMES_SKILL_SOURCES = [
    SourceSpec(
        WSL_HERMES_SKILLS,
        "jiejing-ceo-orchestration/SKILL.md",
        "Current Hermes skill: Jiejing CEO orchestration",
        "ceo",
        ["ceo.intake", "ceo.final_report", "confirmation.package"],
        ["skill", "ceo", "orchestration"],
        100,
        "hermes_current_skill",
        "wsl-hermes-skill:jiejing-ceo-orchestration",
    ),
    SourceSpec(
        WSL_HERMES_SKILLS,
        "jiejing-ebay-market-report/SKILL.md",
        "Current Hermes skill: eBay market report",
        "market-manager",
        ["market.data_packet", "market.report"],
        ["skill", "market", "ebay"],
        100,
        "hermes_current_skill",
        "wsl-hermes-skill:jiejing-ebay-market-report",
    ),
    SourceSpec(
        WSL_HERMES_SKILLS,
        "jiejing-cross-platform-market-research/SKILL.md",
        "Current Hermes skill: cross-platform market research",
        "market-manager",
        ["market.data_packet", "market.report"],
        ["skill", "market", "cross_platform"],
        96,
        "hermes_current_skill",
        "wsl-hermes-skill:jiejing-cross-platform-market-research",
    ),
    SourceSpec(
        WSL_HERMES_SKILLS,
        "jiejing-saas-product-boundary/SKILL.md",
        "Current Hermes skill: SaaS product boundary",
        "all",
        ["ceo.intake", "owner.review"],
        ["skill", "product_boundary", "saas"],
        98,
        "hermes_current_skill",
        "wsl-hermes-skill:jiejing-saas-product-boundary",
    ),
    SourceSpec(
        WSL_HERMES_SKILLS,
        "jiejing-confirmation-risk-boundary/SKILL.md",
        "Current Hermes skill: confirmation risk boundary",
        "all",
        ["confirmation.package", "listing.package", "finance.review", "customer.learn_product"],
        ["skill", "confirmation", "risk"],
        100,
        "hermes_current_skill",
        "wsl-hermes-skill:jiejing-confirmation-risk-boundary",
    ),
    SourceSpec(
        WSL_HERMES_SKILLS,
        "ebay-production-scope-limits/SKILL.md",
        "Current Hermes skill: eBay production scope limits",
        "all",
        ["listing.package", "confirmation.package", "finance.review"],
        ["skill", "ebay", "scope", "safety"],
        98,
        "hermes_current_skill",
        "wsl-hermes-skill:ebay-production-scope-limits",
    ),
    SourceSpec(
        WSL_HERMES_SKILLS,
        "devops/ebay-cross-border-listing/SKILL.md",
        "Current Hermes skill: eBay cross-border listing",
        "product-manager",
        ["listing.package"],
        ["skill", "ebay", "listing"],
        92,
        "hermes_current_skill",
        "wsl-hermes-skill:devops/ebay-cross-border-listing",
    ),
    SourceSpec(
        WSL_HERMES_SKILLS,
        "devops/edis-speedpak-api/SKILL.md",
        "Current Hermes skill: eDIS SpeedPAK API",
        "finance-supply",
        ["finance.review", "source.match"],
        ["skill", "speedpak", "logistics"],
        92,
        "hermes_current_skill",
        "wsl-hermes-skill:devops/edis-speedpak-api",
    ),
    SourceSpec(
        WSL_HERMES_SKILLS,
        "devops/fal-image-generation-pipeline/SKILL.md",
        "Current Hermes skill: image generation pipeline",
        "product-manager",
        ["asset.brief"],
        ["skill", "image_generation", "media"],
        88,
        "hermes_current_skill",
        "wsl-hermes-skill:devops/fal-image-generation-pipeline",
    ),
    SourceSpec(
        WSL_HERMES_SKILLS,
        "devops/kanban-orchestrator/SKILL.md",
        "Current Hermes skill: Kanban orchestrator",
        "ceo",
        ["ceo.intake", "owner.review"],
        ["skill", "kanban", "task_split"],
        86,
        "hermes_current_skill",
        "wsl-hermes-skill:devops/kanban-orchestrator",
    ),
    SourceSpec(
        WSL_HERMES_SKILLS,
        "devops/hermes-team-bus-dispatch/SKILL.md",
        "Current Hermes skill: team bus dispatch",
        "ceo",
        ["ceo.intake", "owner.review"],
        ["skill", "team_bus", "dispatch"],
        86,
        "hermes_current_skill",
        "wsl-hermes-skill:devops/hermes-team-bus-dispatch",
    ),
    SourceSpec(
        WSL_HERMES_SKILLS,
        "tavily-search/SKILL.md",
        "Current Hermes skill: Tavily/public search",
        "market-manager",
        ["market.data_packet", "market.report"],
        ["skill", "public_search"],
        82,
        "hermes_current_skill",
        "wsl-hermes-skill:tavily-search",
    ),
    SourceSpec(
        WSL_HERMES_SKILLS,
        "agent-browser/SKILL.md",
        "Current Hermes skill: browser research",
        "market-manager",
        ["market.data_packet", "market.report"],
        ["skill", "browser", "research"],
        82,
        "hermes_current_skill",
        "wsl-hermes-skill:agent-browser",
    ),
]


MANUAL_ITEMS = [
    {
        "title": "Jiejing closed-loop task sequence",
        "role": "all",
        "task_types": [
            "ceo.intake",
            "market.data_packet",
            "market.report",
            "source.match",
            "listing.package",
            "asset.brief",
            "customer.learn_product",
            "finance.review",
            "confirmation.package",
            "ceo.final_report",
        ],
        "tags": ["closed_loop", "task_split", "saaS_flow"],
        "priority": 100,
        "source_ref": "runtime-distilled:closed-loop",
        "content": (
            "Default Jiejing flow: AI CEO receives the merchant goal, then splits work into market data packet, "
            "market report, supplier/fulfillment facts, product listing package, media task package, customer-service "
            "product learning, finance final check, confirmation package, and CEO final report. Do not send the whole "
            "commerce chain to one role in one giant prompt."
        ),
    },
    {
        "title": "Jiejing-owned Agent job descriptions",
        "role": "all",
        "task_types": [
            "ceo.intake",
            "market.data_packet",
            "market.report",
            "source.match",
            "listing.package",
            "asset.brief",
            "customer.learn_product",
            "finance.review",
            "confirmation.package",
            "ceo.final_report",
            "owner.review",
        ],
        "tags": ["agent_job_spec", "role_boundary", "handoff", "quality_gate", "owned_runtime"],
        "priority": 100,
        "source_ref": "runtime-distilled:owned-agent-job-descriptions",
        "content": (
            "Jiejing-owned Agents must follow clear role specs before using model or provider tools. AI CEO receives goals, "
            "splits work, keeps direction, and summarizes readiness or blockers. Market Manager builds source-labeled "
            "market packets and reports; it may use eBay Browse, Taxonomy, Tavily/public search, and cross-platform public "
            "references, but it cannot decide to publish. Sourcing and Finance turns market direction into supplier facts, "
            "purchase cost, package data, logistics assumptions, and money review; it cannot order, pay, or buy labels. "
            "Product Listing Manager prepares the real eBay listing package: SKU, title, category, condition, price, quantity, "
            "item specifics, description HTML, package facts, and fulfillment/payment/return policy status; it cannot invent "
            "policy IDs or mark a listing publish-ready when blockers remain. Asset Workshop Manager prepares or generates "
            "product images, detail pages, scene images, size charts, and videos; it cannot claim real files exist without an "
            "asset manifest. Customer Service Agent learns the product file before auto replies and escalates refund, dispute, "
            "compensation, customs, exact-delivery-date, and sensitive promise cases. Confirmation Center separates automatic "
            "low-risk work from every-time merchant confirmation and never executes the platform action itself. Every role must "
            "output merchant-readable summary, required sections, source type, missing facts, forbidden actions, quality gates, "
            "and handoff target."
        ),
    },
    {
        "title": "Human confirmation boundary",
        "role": "all",
        "task_types": ["confirmation.package", "listing.package", "finance.review", "customer.learn_product"],
        "tags": ["confirmation", "safety", "execution_boundary"],
        "priority": 100,
        "source_ref": "runtime-distilled:confirmation-boundary",
        "content": (
            "Real eBay publish, batch publish, price or inventory changes, procurement payment, refund, ad budget, "
            "shipping/payment/return policy edits, account authorization changes, and sensitive buyer-service promises "
            "must be held for merchant confirmation. Drafting, analysis, and low-risk internal preparation can proceed."
        ),
    },
    {
        "title": "Public product language boundary",
        "role": "web-engineer",
        "task_types": ["owner.review"],
        "tags": ["public_copy", "hermes_boundary", "saas"],
        "priority": 95,
        "source_ref": "runtime-distilled:public-language",
        "content": (
            "Public Jiejing pages should say Jiejing and AI CEO. Do not expose Hermes, worker, profile, token, internal "
            "script paths, or hidden execution logs. Do not promise guaranteed orders, profit, real customers, or live API "
            "writes unless they are actually connected."
        ),
    },
    {
        "title": "Market report sections",
        "role": "market-manager",
        "task_types": ["market.report"],
        "tags": ["market", "report_template", "source_health"],
        "priority": 100,
        "source_ref": "runtime-distilled:market-report",
        "content": (
            "Market report must include category overview, buyer profile, eBay price bands with numbers, top competitor "
            "breakdown, complaint/pain points, search language, differentiation opportunity, pricing direction, at least "
            "five risk items, report level, source health, and next action. AI inference must be labeled as inference."
        ),
    },
    {
        "title": "eBay listing package sections",
        "role": "product-manager",
        "task_types": ["listing.package"],
        "tags": ["listing", "ebay", "report_template"],
        "priority": 100,
        "source_ref": "runtime-distilled:listing-package",
        "content": (
            "Listing package must separate fixed eBay skeleton from category-dynamic item specifics. Include SKU, title "
            "within 80 characters, subtitle paid notice if used, site, category ID, condition, fixed-price format, price, "
            "quantity, item specifics, pictures 1-12 plan, video plan, HTML description, package weight/dimensions, "
            "handling time, item location, fulfillment/payment/return policy status, publish lock, and missing facts."
        ),
    },
    {
        "title": "Media task package versus actual generated files",
        "role": "product-manager",
        "task_types": ["asset.brief"],
        "tags": ["media", "asset_workshop", "manifest"],
        "priority": 95,
        "source_ref": "runtime-distilled:media-state",
        "content": (
            "Media task package means requirements, prompts, storyboard, dimensions, shot list, and verification checklist. "
            "Actual media files are separate and require a manifest with file paths, type, dimensions, duration, source, "
            "and commercial-use status. Do not claim generated images or video unless files exist."
        ),
    },
    {
        "title": "Customer service product learning gate",
        "role": "customer-service",
        "task_types": ["customer.learn_product"],
        "tags": ["customer_service", "learning_gate", "auto_reply"],
        "priority": 95,
        "source_ref": "runtime-distilled:customer-service",
        "content": (
            "Customer-service must learn the product file before product-specific auto replies. It needs title, verified or "
            "pending specs, package contents, allowed/prohibited claims, shipping and return boundaries, buyer concerns, "
            "FAQ, low-risk reply templates, escalation rules, and stale-file triggers."
        ),
    },
    {
        "title": "Supplier and finance publish gate",
        "role": "finance-supply",
        "task_types": ["source.match", "finance.review"],
        "tags": ["finance", "supplier", "publish_lock"],
        "priority": 95,
        "source_ref": "runtime-distilled:finance-supplier",
        "content": (
            "Before publish confirmation, supplier facts must include source channel, purchase price, MOQ, SKU mapping, "
            "package weight and dimensions, origin city, fulfillment route, inspection/repackaging needs, restricted-item "
            "flags, and logistics quote status. Cost output must use money numbers, not only percentages."
        ),
    },
]


def main() -> int:
    items: list[KnowledgeItem] = []
    counters: dict[str, int] = {
        "files_read": 0,
        "files_missing": 0,
        "items_from_files": 0,
        "manual_items": 0,
        "secret_assignments_redacted": 0,
        "secret_header_lines_removed": 0,
        "long_values_redacted": 0,
        "emails_redacted": 0,
        "suspicious_path_lines_removed": 0,
    }
    missing: list[str] = []

    file_sources = CURATED_SOURCES + CURRENT_HERMES_SHARED_SOURCES + CURRENT_HERMES_SKILL_SOURCES

    for spec in file_sources:
        path = spec.base / spec.path
        source_ref = spec.source_ref or spec.path.replace("\\", "/")
        if not path.exists():
            missing.append(source_ref)
            counters["files_missing"] += 1
            continue
        raw = read_text_smart(path)
        sanitized, report = sanitize_text(raw)
        for key, value in report.items():
            counters[key] = counters.get(key, 0) + value
        content = compact_content(sanitized)
        if not content:
            continue
        items.append(
            KnowledgeItem(
                item_id=make_item_id(spec.title, source_ref),
                title=spec.title,
                role=spec.role,
                task_types=spec.task_types,
                tags=spec.tags,
                source_ref=source_ref,
                content=content,
                priority=spec.priority,
                source_type=spec.source_type,
            )
        )
        counters["files_read"] += 1
        counters["items_from_files"] += 1

    for manual in MANUAL_ITEMS:
        source_ref = str(manual["source_ref"])
        items.append(
            KnowledgeItem(
                item_id=make_item_id(str(manual["title"]), source_ref),
                title=str(manual["title"]),
                role=str(manual["role"]),
                task_types=list(manual["task_types"]),
                tags=list(manual["tags"]),
                source_ref=source_ref,
                content=str(manual["content"]),
                priority=int(manual["priority"]),
                source_type="runtime_distilled_rule",
            )
        )
        counters["manual_items"] += 1

    for item in build_runtime_hermes_inventory_items():
        items.append(item)
        counters["manual_items"] += 1

    pack = KnowledgePack(
        version=KNOWLEDGE_VERSION,
        generated_at=now_iso(),
        items=items,
        redaction_report={**counters, "missing_sources": missing},
    )
    pack_path = write_knowledge_pack(pack)
    summary_path = write_summary(pack, pack_path)
    manifest_path = write_migration_manifest(pack, pack_path)
    print(f"OK knowledge pack written: {pack_path}")
    print(f"summary={summary_path}")
    print(f"migration_manifest={manifest_path}")
    print(f"items={len(items)} files_read={counters['files_read']} manual_items={counters['manual_items']}")
    print(f"redactions={sum(counters[key] for key in counters if key.endswith('_redacted') or key.endswith('_removed'))}")
    return 0


def read_text_smart(path: Path) -> str:
    raw = path.read_bytes()
    for encoding in ("utf-8", "utf-8-sig", "gb18030"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def build_runtime_hermes_inventory_items() -> list[KnowledgeItem]:
    items: list[KnowledgeItem] = []
    items.append(build_config_inventory_item())
    items.append(build_provider_inventory_item())
    items.append(build_ebay_provider_inventory_item())
    profile_item = build_profile_skill_inventory_item()
    if profile_item is not None:
        items.append(profile_item)
    return items


def build_config_inventory_item() -> KnowledgeItem:
    exists = WSL_HERMES_CONFIG.exists()
    size = WSL_HERMES_CONFIG.stat().st_size if exists else 0
    content = (
        "Hermes config migration rule for Jiejing Runtime:\n"
        f"- config_path_exists: {exists}\n"
        f"- config_size_bytes: {size}\n"
        "- raw config content is intentionally not imported into Runtime knowledge because it can contain provider, gateway, "
        "token, cookie, model, proxy, or credential settings.\n"
        "- Runtime must use its own environment variables, vault/secret manager, tenant permission checks, and adapter settings.\n"
        "- Migrated configuration value is the boundary: Hermes remains an internal worker; Jiejing Runtime owns task protocol, "
        "role contracts, confirmation center, audit records, and execution-service boundary.\n"
    )
    return KnowledgeItem(
        item_id=make_item_id("Hermes safe config inventory", "wsl-hermes-config:config.yaml"),
        title="Hermes safe config inventory",
        role="all",
        task_types=["ceo.intake", "owner.review", "confirmation.package"],
        tags=["config", "migration", "secret_boundary", "runtime_ownership"],
        source_ref="wsl-hermes-config:config.yaml",
        content=content,
        priority=96,
        source_type="hermes_config_inventory",
    )


def build_provider_inventory_item() -> KnowledgeItem:
    env_keys = {
        "deepseek": env_key_exists("DEEPSEEK_API_KEY"),
        "tavily": env_key_exists("TAVILY_API_KEY"),
        "fal_pair": env_key_exists("FAL_KEY_ID") and env_key_exists("FAL_KEY_SECRET"),
        "fal_single": env_key_exists("FAL_KEY"),
        "gemini": env_key_exists("GEMINI_API_KEY"),
        "openai_voice": env_key_exists("VOICE_TOOLS_OPENAI_KEY"),
    }
    content = (
        "Hermes provider inventory synchronized into Jiejing Runtime as safe Agent knowledge. "
        "This item tells the owned Agents which provider families exist and how they may be used; it never imports raw credentials.\n\n"
        f"- DeepSeek model provider detected: {env_keys['deepseek']}. Use for structured Runtime reports when Jiejing model env is enabled.\n"
        f"- Tavily public search provider detected: {env_keys['tavily']}. Use for market data packet and market report public-web evidence. "
        "It is not official eBay sales data and must be labeled as public search/source reference.\n"
        f"- FAL media provider detected: {env_keys['fal_pair'] or env_keys['fal_single']}. Use for Asset Agent image/video generation only when provider=fal or a media endpoint is explicitly requested. "
        "Default image direction follows Hermes: gpt-image-2 quality-low for controlled e-commerce assets, with cheaper draft/fallback models available. "
        "Video must be a product-demonstration brief/asset, not merely a still image plus narration.\n"
        f"- Gemini media helper detected: {env_keys['gemini']}. If absent, cutout/normalization or product-vision tasks must stay pending or use another configured provider.\n"
        f"- Voice/OpenAI audio helper detected: {env_keys['openai_voice']}. Use only for internal narration/voice tasks when explicitly configured.\n"
        "- Feishu, GitHub, browser, and Codex credentials are internal operator/dev-control tools; they are not merchant-facing Jiejing SaaS capabilities.\n"
        "- Raw provider values stay in environment/vault/Hermes local files. Jiejing Agent reports should mention provider status and source type, never print keys, cookies, or OAuth strings.\n"
    )
    sanitized, _ = sanitize_text(content)
    return KnowledgeItem(
        item_id=make_item_id("Hermes provider inventory for Jiejing Agents", "wsl-hermes-provider-inventory:env-presence"),
        title="Hermes provider inventory for Jiejing Agents",
        role="all",
        task_types=["ceo.intake", "market.data_packet", "market.report", "listing.package", "asset.brief", "owner.review"],
        tags=["provider_inventory", "model", "public_search", "media", "migration", "secret_boundary"],
        source_ref="wsl-hermes-provider-inventory:env-presence",
        content=compact_content(sanitized),
        priority=99,
        source_type="hermes_provider_inventory",
    )


def build_ebay_provider_inventory_item() -> KnowledgeItem:
    market_token_file_exists = (WSL_HERMES_PROFILES / "market-manager" / "credentials" / "ebay_production_user_token.json").exists()
    listing_rules_file_exists = (WSL_HERMES_HOME / "output" / "ebay-account" / "northvalesource_listing_rules_latest.json").exists()
    policy_snapshot_exists = (WSL_HERMES_HOME / "output" / "ebay-account" / "business_policies_latest.json").exists()
    content = (
        "eBay provider inventory synchronized into Jiejing Runtime as safe Agent knowledge. "
        "This is the API capability map the Agents should follow; raw seller OAuth values are not imported.\n\n"
        f"- Seller credential file detected for market role: {market_token_file_exists}. Runtime may only use a backend credential resolver or vault, not a frontend value.\n"
        f"- Store listing rules snapshot detected: {listing_rules_file_exists}. Use sanitized snapshots for draft/policy defaults when live Account policy read is unavailable.\n"
        f"- Business policy snapshot detected: {policy_snapshot_exists}. If present, product-manager may read fulfillment/payment/return policy IDs from sanitized backend data; do not hardcode them.\n"
        "- Browse API: market-manager can use it for eBay public item summaries, sample price bands, seller/listing examples, and category signals.\n"
        "- Taxonomy API: product-manager must use it for category ID, required/recommended item specifics, condition support, and category-dependent fields.\n"
        "- Account API policy read: product-manager should read fulfillment, payment, and return policy templates when the seller authorization allows it. A 403 may mean extra business permission is missing, not that the store is disconnected.\n"
        "- Trading API: Hermes currently uses this surface for listing/order/shipping/price operations where REST sell APIs are limited. Runtime should treat writes through this path as ExecutionService actions, never direct Agent actions.\n"
        "- Finances API: finance-supply can use it for transaction, fee, refund, and profit review when authorized.\n"
        "- Fulfillment/order/logistics APIs: read order and shipping status when authorized; label purchase, tracking writes, address writes, and procurement payment remain confirmation-gated.\n"
        "- All eBay publish, price, inventory, refund, ad, policy, account authorization, and payment-impacting actions must pass confirmation center and audit logs.\n"
    )
    sanitized, _ = sanitize_text(content)
    return KnowledgeItem(
        item_id=make_item_id("eBay provider inventory for Jiejing Agents", "wsl-hermes-provider-inventory:ebay-safe-map"),
        title="eBay provider inventory for Jiejing Agents",
        role="all",
        task_types=["market.data_packet", "market.report", "listing.package", "finance.review", "confirmation.package", "owner.review"],
        tags=["provider_inventory", "ebay", "taxonomy", "business_policy", "finances", "execution_boundary"],
        source_ref="wsl-hermes-provider-inventory:ebay-safe-map",
        content=compact_content(sanitized),
        priority=100,
        source_type="hermes_provider_inventory",
    )


def env_key_exists(name: str) -> bool:
    if not WSL_HERMES_ENV.exists():
        return False
    try:
        for line in WSL_HERMES_ENV.read_text(encoding="utf-8", errors="ignore").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, raw_value = stripped.split("=", 1)
            if key.strip() == name and raw_value.strip().strip('"').strip("'"):
                return True
    except OSError:
        return False
    return False


def build_profile_skill_inventory_item() -> KnowledgeItem | None:
    if not WSL_HERMES_PROFILES.exists():
        return None
    profiles: list[dict[str, Any]] = []
    relevant_keywords = (
        "jiejing",
        "ebay",
        "speedpak",
        "edis",
        "orange",
        "fal-image",
        "image-generation",
        "kanban",
        "team-bus",
        "tavily",
        "browser",
        "market",
        "listing",
        "confirmation",
    )
    for snapshot in sorted(WSL_HERMES_PROFILES.glob("*/.skills_prompt_snapshot.json")):
        try:
            data = json.loads(snapshot.read_text(encoding="utf-8"))
        except Exception:
            continue
        manifest = data.get("manifest", {})
        if not isinstance(manifest, dict):
            continue
        relevant = [
            key
            for key in sorted(manifest)
            if any(keyword in key.lower() for keyword in relevant_keywords)
        ]
        profiles.append(
            {
                "profile": snapshot.parent.name,
                "total_skills_seen": len(manifest),
                "relevant_skills": relevant[:80],
                "relevant_skill_count": len(relevant),
            }
        )
    if not profiles:
        return None
    content = (
        "Hermes profile skill inventory migrated as sanitized Runtime context. "
        "This inventory records which role profiles have Jiejing/eBay/logistics/research/media/dispatch skills available; "
        "it does not import credentials or profile runtime state.\n\n"
        + json.dumps(profiles, ensure_ascii=False, indent=2)
    )
    sanitized, _ = sanitize_text(content)
    return KnowledgeItem(
        item_id=make_item_id("Hermes profile skill inventory", "wsl-hermes-profiles:skills_prompt_snapshots"),
        title="Hermes profile skill inventory",
        role="all",
        task_types=["ceo.intake", "market.report", "listing.package", "asset.brief", "finance.review", "owner.review"],
        tags=["skills", "profiles", "migration", "role_capability"],
        source_ref="wsl-hermes-profiles:skills_prompt_snapshots",
        content=compact_content(sanitized, limit=9000),
        priority=94,
        source_type="hermes_profile_inventory",
    )


def write_summary(pack: KnowledgePack, pack_path: Path) -> Path:
    role_counts: dict[str, int] = {}
    task_counts: dict[str, int] = {}
    for item in pack.items:
        role_counts[item.role] = role_counts.get(item.role, 0) + 1
        for task_type in item.task_types:
            task_counts[task_type] = task_counts.get(task_type, 0) + 1

    lines = [
        "# Jiejing Runtime Knowledge Pack",
        "",
        f"- version: `{pack.version}`",
        f"- generated_at: `{pack.generated_at}`",
        f"- pack_path: `{pack_path}`",
        f"- item_count: `{len(pack.items)}`",
        "",
        "## Roles",
    ]
    for role, count in sorted(role_counts.items()):
        lines.append(f"- `{role}`: {count}")
    lines.extend(["", "## Task Types"])
    for task_type, count in sorted(task_counts.items()):
        lines.append(f"- `{task_type}`: {count}")
    lines.extend(["", "## Included Items"])
    for item in pack.items:
        lines.append(f"- `{item.role}` / `{','.join(item.task_types)}`: {item.title} ({item.source_ref})")
    lines.extend(["", "## Redaction Report"])
    for key, value in pack.redaction_report.items():
        if key == "missing_sources":
            continue
        lines.append(f"- `{key}`: {value}")
    if pack.redaction_report.get("missing_sources"):
        lines.extend(["", "## Missing Sources"])
        for source in pack.redaction_report["missing_sources"]:
            lines.append(f"- `{source}`")
    path = DEFAULT_KNOWLEDGE_DIR / "summary.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def write_migration_manifest(pack: KnowledgePack, pack_path: Path) -> Path:
    role_counts: dict[str, int] = {}
    task_counts: dict[str, int] = {}
    source_type_counts: dict[str, int] = {}
    for item in pack.items:
        role_counts[item.role] = role_counts.get(item.role, 0) + 1
        source_type_counts[item.source_type] = source_type_counts.get(item.source_type, 0) + 1
        for task_type in item.task_types:
            task_counts[task_type] = task_counts.get(task_type, 0) + 1

    manifest = {
        "generated_at": pack.generated_at,
        "knowledge_version": pack.version,
        "knowledge_pack": str(pack_path),
        "migration_scope": {
            "project_direction": True,
            "shared_memory_notes": True,
            "role_sops": True,
            "skills": True,
            "profile_skill_inventory": True,
            "safe_config_inventory": True,
            "raw_credentials_imported": False,
            "raw_cookies_imported": False,
            "raw_tokens_imported": False,
            "raw_hermes_config_imported": False,
        },
        "source_roots": {
            "local_curated_sources": str(HERMES_ROOT),
            "wsl_hermes_shared": str(WSL_HERMES_SHARED),
            "wsl_hermes_skills": str(WSL_HERMES_SKILLS),
            "wsl_hermes_profiles": str(WSL_HERMES_PROFILES),
        },
        "item_count": len(pack.items),
        "role_counts": role_counts,
        "task_type_counts": task_counts,
        "source_type_counts": source_type_counts,
        "redaction_report": pack.redaction_report,
        "runtime_use": {
            "loaded_by": "jiejing_runtime.knowledge.load_default_knowledge_base",
            "used_by": "JiejingAgentAdapter and JiejingAgentTeam model-task context",
            "safety_rule": "Unknown facts remain Pending; high-risk actions remain confirmation-gated.",
        },
    }
    path = DEFAULT_KNOWLEDGE_DIR / "hermes-migration-manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


if __name__ == "__main__":
    raise SystemExit(main())
