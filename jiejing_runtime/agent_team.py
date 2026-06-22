"""Owned Jiejing commerce-agent team contracts.

This module is the replacement path for the generic Hermes dependency. It does
not try to copy a general-purpose agent OS. It defines the commerce-specific
roles, permissions, quality gates, and handoff contracts that Jiejing Runtime
owns before any model or external worker is called.
"""

from __future__ import annotations

import copy
import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any

from .knowledge import KnowledgeItem
from .models import JiejingTask


HIGH_RISK_FORBIDDEN_ACTIONS = [
    "Do not publish or revise a real eBay listing.",
    "Do not change real price or inventory.",
    "Do not place, pay, or cancel a procurement order.",
    "Do not refund, partially refund, compensate, or promise compensation.",
    "Do not start, stop, or change advertising budget.",
    "Do not edit fulfillment, payment, return, subscription, or authorization policy.",
    "Do not write tracking, buyer address, or account-sensitive data to a live platform.",
    "Do not send sensitive buyer promises without a human confirmation record.",
]


@dataclass(slots=True)
class AgentToolPermission:
    key: str
    access: str
    purpose: str
    boundary: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(slots=True)
class AgentRoleSpec:
    role: str
    merchant_label: str
    internal_label: str
    task_types: list[str]
    mission: str
    system_prompt: str
    required_outputs: list[str]
    quality_gates: list[str]
    handoff_targets: list[str]
    tool_permissions: list[AgentToolPermission]
    forbidden_actions: list[str]
    maturity_status: str
    knowledge_role: str | None = None
    input_requirements: list[str] = field(default_factory=list)
    stop_conditions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["tool_permissions"] = [item.to_dict() for item in self.tool_permissions]
        return data


class JiejingAgentTeam:
    """Commerce-specific agent contracts owned by Jiejing Runtime."""

    name = "jiejing-owned-agent-team"
    version = "2026-05-15.2"

    def __init__(self) -> None:
        self._roles = self._build_roles()
        self._task_to_role: dict[str, str] = {}
        for role in self._roles.values():
            for task_type in role.task_types:
                self._task_to_role[task_type] = role.role

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "purpose": "Run the eBay-first Jiejing commerce workflow without binding the SaaS to Hermes internals.",
            "merchant_model": "Merchant faces AI CEO, work records, source records, and confirmation center; roles remain backend execution units.",
            "role_count": len(self._roles),
            "roles": [role.to_dict() for role in self._roles.values()],
            "task_to_role": dict(self._task_to_role),
            "replacement_boundary": {
                "not_a_hermes_clone": True,
                "commerce_vertical_runtime": True,
                "real_execution_requires_execution_service": True,
                "high_risk_actions_require_confirmation": True,
            },
        }

    def role_for(self, task_type: str) -> str:
        return self._task_to_role.get(task_type, "ceo")

    def spec_for_task(self, task_type: str) -> AgentRoleSpec:
        return self._roles[self.role_for(task_type)]

    def knowledge_role_for(self, task_type: str) -> str:
        spec = self.spec_for_task(task_type)
        return spec.knowledge_role or spec.role

    def build_model_task(self, task: JiejingTask, knowledge_items: list[KnowledgeItem]) -> JiejingTask:
        spec = self.spec_for_task(task.task_type)
        raw = copy.deepcopy(task.raw)
        task_input = dict(raw.get("input", {}) if isinstance(raw.get("input"), dict) else {})
        task_context = dict(raw.get("context", {}) if isinstance(raw.get("context"), dict) else {})
        task_input["agent_profile"] = {
            "agent_team": self.name,
            "agent_team_version": self.version,
            "role": spec.role,
            "merchant_label": spec.merchant_label,
            "internal_label": spec.internal_label,
            "maturity_status": spec.maturity_status,
        }
        task_input["agent_instructions"] = {
            "mission": spec.mission,
            "system_prompt": (
                f"{spec.system_prompt}\n"
                "商家可见标题、摘要、风险、缺口、下一步和报告正文必须使用简体中文；"
                "eBay、SKU、Listing、Market Report、Listing Package 等专有词可以保留英文。"
                "没有来源的数据必须写成待补资料，不能用英文模板或旧演示商品补空白。"
            ),
            "language_policy": "merchant_visible_zh_cn_required",
            "required_outputs": spec.required_outputs,
            "quality_gates": spec.quality_gates,
            "forbidden_actions": spec.forbidden_actions,
            "handoff_targets": spec.handoff_targets,
            "input_requirements": spec.input_requirements,
            "stop_conditions": spec.stop_conditions,
        }
        task_input["tool_permissions"] = [permission.to_dict() for permission in spec.tool_permissions]
        task_input["handoff_contract"] = self._handoff_contract(task, spec)
        task_input["knowledge_context"] = [
            {
                "item_id": item.item_id,
                "title": item.title,
                "role": item.role,
                "tags": item.tags,
                "source_ref": item.source_ref,
                "content_excerpt": self._excerpt(item.content, 720),
            }
            for item in knowledge_items[:6]
        ]
        task_context["agent_team"] = {
            "name": self.name,
            "version": self.version,
            "role": spec.role,
            "maturity_status": spec.maturity_status,
        }
        raw["input"] = task_input
        raw["context"] = task_context
        return JiejingTask(raw)

    def normalize_report(
        self,
        task: JiejingTask,
        report: dict[str, Any],
        knowledge_items: list[KnowledgeItem],
    ) -> dict[str, Any]:
        spec = self.spec_for_task(task.task_type)
        normalized = dict(report)
        normalized["agent_team"] = {
            "name": self.name,
            "version": self.version,
            "replacement_path": "Jiejing-owned commerce Agent Runtime",
            "not_hermes_clone": True,
        }
        normalized["agent_role"] = spec.role
        normalized["agent_label"] = spec.merchant_label
        normalized["agent_maturity_status"] = spec.maturity_status
        normalized["agent_profile"] = {
            "role": spec.role,
            "merchant_label": spec.merchant_label,
            "internal_label": spec.internal_label,
            "mission": spec.mission,
        }
        normalized["tool_permissions"] = [permission.to_dict() for permission in spec.tool_permissions]
        normalized["forbidden_actions"] = list(spec.forbidden_actions)
        normalized["quality_gates"] = list(spec.quality_gates)
        normalized["input_requirements"] = list(spec.input_requirements)
        normalized["stop_conditions"] = list(spec.stop_conditions)
        normalized["handoff_contract"] = self._handoff_contract(task, spec)
        normalized["job_spec"] = {
            "role": spec.role,
            "mission": spec.mission,
            "input_requirements": list(spec.input_requirements),
            "required_outputs": list(spec.required_outputs),
            "quality_gates": list(spec.quality_gates),
            "stop_conditions": list(spec.stop_conditions),
            "handoff_targets": list(spec.handoff_targets),
            "forbidden_actions": list(spec.forbidden_actions),
        }
        normalized["knowledge_context_used"] = [
            {
                "item_id": item.item_id,
                "title": item.title,
                "role": item.role,
                "source_ref": item.source_ref,
            }
            for item in knowledge_items[:6]
        ]
        normalized["report_quality"] = self._quality_review(task, normalized, spec)
        normalized["job_spec_compliance"] = self._job_spec_compliance(task, normalized, spec)
        return normalized

    def _handoff_contract(self, task: JiejingTask, spec: AgentRoleSpec) -> dict[str, Any]:
        return {
            "task_type": task.task_type,
            "producer_role": spec.role,
            "handoff_targets": list(spec.handoff_targets),
            "required_sections": list(task.output_contract.get("required_sections", [])),
            "role_required_outputs": list(spec.required_outputs),
            "stop_conditions": list(spec.stop_conditions),
            "must_label_source_type": True,
            "unknown_facts_stay_pending": True,
            "merchant_readable_summary_required": True,
            "high_risk_actions_to_confirmation_center": True,
            "real_execution_allowed": False,
        }

    def _quality_review(self, task: JiejingTask, report: dict[str, Any], spec: AgentRoleSpec) -> dict[str, Any]:
        sections = report.get("sections")
        section_map = sections if isinstance(sections, dict) else {}
        required_sections = [str(item) for item in task.output_contract.get("required_sections", [])]
        missing_sections = [
            section
            for section in required_sections
            if not str(section_map.get(section, "")).strip()
        ]
        forbidden_claims = self._forbidden_claims(report)
        gate_status = "pass" if not missing_sections and not forbidden_claims else "needs_repair"
        return {
            "status": gate_status,
            "role": spec.role,
            "required_sections_checked": required_sections,
            "missing_sections": missing_sections,
            "forbidden_claims_found": forbidden_claims,
            "quality_gates_checked": list(spec.quality_gates),
            "safe_for_real_execution": False,
            "next_runtime_action": "continue_workflow" if gate_status == "pass" else "repair_report_before_handoff",
        }

    def _job_spec_compliance(self, task: JiejingTask, report: dict[str, Any], spec: AgentRoleSpec) -> dict[str, Any]:
        serialized = json.dumps(report, ensure_ascii=False).lower()
        required_runtime_controls = {
            "tool_permissions": bool(report.get("tool_permissions")),
            "forbidden_actions": bool(report.get("forbidden_actions")),
            "quality_gates": bool(report.get("quality_gates")),
            "handoff_contract": isinstance(report.get("handoff_contract"), dict),
            "job_spec": isinstance(report.get("job_spec"), dict),
        }
        missing_controls = [key for key, present in required_runtime_controls.items() if not present]
        output_markers = {
            output: self._mentions_output(serialized, output)
            for output in spec.required_outputs
        }
        missing_output_markers = [output for output, present in output_markers.items() if not present]
        forbidden_claims = self._forbidden_claims(report)
        status = "pass"
        if missing_controls or forbidden_claims:
            status = "needs_repair"
        elif missing_output_markers:
            status = "needs_attention"
        return {
            "status": status,
            "role": spec.role,
            "task_type": task.task_type,
            "runtime_controls_present": required_runtime_controls,
            "missing_runtime_controls": missing_controls,
            "required_outputs_checked": list(spec.required_outputs),
            "missing_output_markers": missing_output_markers,
            "stop_conditions_checked": list(spec.stop_conditions),
            "forbidden_claims_found": forbidden_claims,
            "real_execution_allowed": False,
        }

    def _mentions_output(self, serialized_report: str, output: str) -> bool:
        words = [word for word in re.split(r"[^a-zA-Z0-9]+", output.lower()) if len(word) >= 4]
        if not words:
            return True
        return any(word in serialized_report for word in words)

    def _forbidden_claims(self, report: dict[str, Any]) -> list[str]:
        serialized = json.dumps(report, ensure_ascii=False).lower()
        patterns = {
            "real_execution_allowed_true": r'"real_execution_allowed"\s*:\s*true',
            "published_to_ebay_true": r'"published_to_ebay"\s*:\s*true',
            "procurement_paid_true": r'"procurement_paid"\s*:\s*true',
            "refund_executed_true": r'"refund_executed"\s*:\s*true',
            "ad_budget_changed_true": r'"ad_budget_changed"\s*:\s*true',
            "store_policy_changed_true": r'"store_policy_changed"\s*:\s*true',
            "claim_published": r'\b(published|posted)\s+(the\s+)?(real\s+)?(ebay\s+)?listing\b',
            "claim_paid_supplier": r'\b(paid|placed)\s+(the\s+)?(supplier|procurement|1688)\b',
        }
        return [key for key, pattern in patterns.items() if re.search(pattern, serialized)]

    def _build_roles(self) -> dict[str, AgentRoleSpec]:
        read_only_external = "read_only_or_snapshot_only"
        internal_only = "internal_runtime_only"
        return {
            "ceo": AgentRoleSpec(
                role="ceo",
                merchant_label="AI CEO",
                internal_label="Goal intake, orchestration, and final judgment",
                task_types=["ceo.intake", "ceo.final_report", "owner.review"],
                mission="Receive the merchant goal, split it into commerce tasks, hold the direction, and summarize what is ready or blocked.",
                system_prompt=(
                    "You are Jiejing's AI CEO. Keep the workflow eBay-first, automation-focused, and confirmation-gated. "
                    "Do not promise sales results. Translate merchant intent into small role tasks."
                ),
                required_outputs=["goal boundary", "task split", "blocking gaps", "risk boundary", "next minimum action"],
                quality_gates=[
                    "Task split must be small enough to avoid role timeout.",
                    "High-risk actions must be named as confirmation items.",
                    "Final report must say what can continue and what is blocked.",
                ],
                handoff_targets=["market-manager", "confirmation-center", "merchant"],
                tool_permissions=[
                    AgentToolPermission("runtime_repository", internal_only, "read and write task state", "No customer data outside tenant scope."),
                    AgentToolPermission("confirmation_center", internal_only, "create confirmation package", "No execution without merchant decision."),
                ],
                forbidden_actions=list(HIGH_RISK_FORBIDDEN_ACTIONS),
                maturity_status="owned_contract_ready",
                input_requirements=["merchant goal", "merchant stage", "target platform", "source route if known", "risk preferences"],
                stop_conditions=["goal is outside eBay-first workflow", "request requires real write without confirmation", "task is too large and must be split"],
                knowledge_role="ceo",
            ),
            "market-manager": AgentRoleSpec(
                role="market-manager",
                merchant_label="市场经理",
                internal_label="Market packet and opportunity judgment",
                task_types=["market.data_packet", "market.report"],
                mission="Build source-labeled market judgment before any sourcing, listing, or media work starts.",
                system_prompt=(
                    "You are Jiejing's market manager. Separate official data, public pages, merchant inputs, and AI inference. "
                    "Never turn weak data into a confident publish decision."
                ),
                required_outputs=[
                    "category overview",
                    "buyer profile",
                    "eBay price bands",
                    "competitor pattern",
                    "keyword direction",
                    "risk assessment",
                    "sell/test/stop recommendation",
                ],
                quality_gates=[
                    "Every market number must have a source type or be labeled as inference.",
                    "Recommendation must include a reason and a stop condition.",
                    "Unknown competitor or search data must stay visible.",
                ],
                handoff_targets=["finance-supply", "product-manager", "ceo"],
                tool_permissions=[
                    AgentToolPermission("ebay_browse", read_only_external, "read public eBay market snapshots", "No seller-account writes."),
                    AgentToolPermission("ebay_taxonomy", read_only_external, "check category direction", "No listing publish."),
                    AgentToolPermission("public_search", read_only_external, "collect public web signals", "No anti-bot bypass."),
                    AgentToolPermission("cross_platform_reference", read_only_external, "use Amazon/1688/Taobao references as directional context", "Do not claim internal platform data."),
                ],
                forbidden_actions=list(HIGH_RISK_FORBIDDEN_ACTIONS),
                maturity_status="owned_contract_partial_tools",
                input_requirements=["product or product direction", "marketplace", "source labels", "public/eBay data packet or allowed search tools"],
                stop_conditions=["no product direction", "live data unavailable and report would overclaim", "request asks for publish decision"],
                knowledge_role="market-manager",
            ),
            "finance-supply": AgentRoleSpec(
                role="finance-supply",
                merchant_label="货源与财务经理",
                internal_label="Source matching, logistics, and margin review",
                task_types=["source.match", "finance.review"],
                mission="Turn the market direction into sourcing facts, supplier questions, logistics assumptions, and money review.",
                system_prompt=(
                    "You are Jiejing's sourcing and finance agent. Keep supplier facts, package data, shipping, fees, and margin explicit. "
                    "Never pay or place orders."
                ),
                required_outputs=[
                    "source route",
                    "supplier candidates",
                    "cost inputs",
                    "package inputs",
                    "supplier questions",
                    "logistics route",
                    "net profit money",
                    "publish/procurement blocker",
                ],
                quality_gates=[
                    "Money output must use concrete currency values, not only percentages.",
                    "Supplier dimensions, weight, material, origin, and dropship rule must be marked confirmed or pending.",
                    "Procurement and payment stay blocked until confirmation.",
                ],
                handoff_targets=["product-manager", "confirmation-center", "ceo"],
                tool_permissions=[
                    AgentToolPermission("sourcing_availability", read_only_external, "read authorized 1688/manual supplier snapshots", "No ordering or payment."),
                    AgentToolPermission("logistics_estimate", read_only_external, "estimate shipping route and quote", "No label purchase or tracking write."),
                    AgentToolPermission("finance_calculator", internal_only, "calculate fees, reserves, and net profit", "Use estimates until official data is present."),
                ],
                forbidden_actions=list(HIGH_RISK_FORBIDDEN_ACTIONS),
                maturity_status="owned_contract_partial_tools",
                input_requirements=["source route", "supplier link or quote when available", "package facts", "logistics route", "target price band"],
                stop_conditions=["supplier cost is missing for real margin", "package weight/dimensions are missing for publish", "procurement/payment requested without confirmation"],
                knowledge_role="finance-supply",
            ),
            "product-manager": AgentRoleSpec(
                role="product-manager",
                merchant_label="产品刊登经理",
                internal_label="eBay listing package",
                task_types=["listing.package"],
                mission="Prepare an eBay-shaped listing package that can be validated before publish.",
                system_prompt=(
                    "You are Jiejing's eBay product listing manager. Produce fixed listing fields plus category-dynamic item specifics. "
                    "Never invent policy IDs or call the draft publish-ready when blockers remain."
                ),
                required_outputs=[
                    "SKU",
                    "Title within 80 characters",
                    "Subtitle caveat",
                    "Category ID",
                    "Condition",
                    "Format",
                    "Price",
                    "Quantity",
                    "Item Specifics",
                    "Description HTML",
                    "Picture and video requirements",
                    "Package facts",
                    "Fulfillment/payment/return policy status",
                    "Publish blockers",
                ],
                quality_gates=[
                    "Listing package must match real eBay fixed skeleton.",
                    "Category item specifics must be marked validated or pending taxonomy check.",
                    "Policy IDs must come from authorized account data or stay pending.",
                    "Publish remains locked until supplier, taxonomy, asset, finance, and confirmation gates pass.",
                ],
                handoff_targets=["asset-manager", "customer-service", "finance-supply", "confirmation-center"],
                tool_permissions=[
                    AgentToolPermission("ebay_taxonomy", read_only_external, "query category and aspects", "No publish or revise call."),
                    AgentToolPermission("business_policy_read", read_only_external, "read fulfillment/payment/return policy IDs when authorized", "No policy edit."),
                    AgentToolPermission("listing_validator", internal_only, "check required fields and blockers", "Validation only."),
                ],
                forbidden_actions=list(HIGH_RISK_FORBIDDEN_ACTIONS),
                maturity_status="owned_contract_ready",
                input_requirements=["market report", "source and finance precheck", "category hint", "supplier facts", "store policy status"],
                stop_conditions=["category/taxonomy pending for real publish", "supplier facts missing", "business policy IDs missing", "publish confirmation missing"],
                knowledge_role="product-manager",
            ),
            "asset-manager": AgentRoleSpec(
                role="asset-manager",
                merchant_label="素材工坊经理",
                internal_label="Image, detail page, and video task package",
                task_types=["asset.brief"],
                mission="Convert listing needs into image, detail-page, and video generation instructions with claim safety.",
                system_prompt=(
                    "You are Jiejing's asset workshop manager. Design product images, scene images, details, size charts, and video briefs. "
                    "Do not claim files exist unless a manifest exists."
                ),
                required_outputs=[
                    "image plan",
                    "detail page plan",
                    "video plan",
                    "asset settings",
                    "claim risk",
                    "media manifest status",
                ],
                quality_gates=[
                    "Commercial-use status must be explicit.",
                    "Generated file claims require asset manifest entries.",
                    "Unconfirmed product facts must not appear as hard claims in images or video.",
                ],
                handoff_targets=["product-manager", "customer-service", "confirmation-center"],
                tool_permissions=[
                    AgentToolPermission("image_generation", "requires_configured_provider", "generate product and scene images", "No unverified claims in media."),
                    AgentToolPermission("video_generation", "requires_configured_provider", "generate or brief product video", "No fake testimonial or unsupported claim."),
                    AgentToolPermission("asset_manifest", internal_only, "record generated file metadata", "Manifest required before downstream use."),
                ],
                forbidden_actions=list(HIGH_RISK_FORBIDDEN_ACTIONS),
                maturity_status="owned_contract_waiting_live_media_tools",
                input_requirements=["listing package", "confirmed or pending product facts", "image/video requirements", "media provider or manifest"],
                stop_conditions=["no asset manifest for generated-file claim", "unconfirmed facts would appear as hard claims", "media provider is not configured for live generation"],
                knowledge_role="product-manager",
            ),
            "customer-service": AgentRoleSpec(
                role="customer-service",
                merchant_label="客服专员",
                internal_label="Product learning and reply boundary",
                task_types=["customer.learn_product"],
                mission="Learn the product file before automatic replies and define where human takeover is required.",
                system_prompt=(
                    "You are Jiejing's customer-service agent. Learn confirmed product facts first. "
                    "Auto-reply only inside the safe boundary."
                ),
                required_outputs=[
                    "product service file",
                    "buyer question map",
                    "FAQ",
                    "reply boundary",
                    "auto reply templates",
                    "escalation rules",
                ],
                quality_gates=[
                    "No product-specific auto reply before product file is learned.",
                    "Refund, dispute, compensation, customs, exact delivery date, and sensitive promise escalate.",
                    "Reply templates must not exceed confirmed listing facts.",
                ],
                handoff_targets=["finance-supply", "confirmation-center", "ceo"],
                tool_permissions=[
                    AgentToolPermission("message_draft", internal_only, "draft low-risk buyer replies", "No automatic send in current Runtime."),
                    AgentToolPermission("customer_case_classifier", "planned", "classify reply risk", "Sensitive cases require confirmation."),
                ],
                forbidden_actions=list(HIGH_RISK_FORBIDDEN_ACTIONS),
                maturity_status="owned_contract_ready",
                input_requirements=["listing package", "confirmed product facts", "shipping/return boundary", "buyer concern map"],
                stop_conditions=["product file not learned", "buyer request involves refund/compensation/dispute", "reply would exceed confirmed facts"],
                knowledge_role="customer-service",
            ),
            "confirmation-center": AgentRoleSpec(
                role="confirmation-center",
                merchant_label="决策中心",
                internal_label="Human decision package and execution boundary",
                task_types=["confirmation.package"],
                mission="Collect high-risk actions into a simple merchant decision package before ExecutionService can act.",
                system_prompt=(
                    "You are Jiejing's confirmation center. Separate what can run automatically from what must wait for the merchant. "
                    "Do not execute the action."
                ),
                required_outputs=[
                    "allowed auto actions",
                    "default rule actions",
                    "every-time confirm actions",
                    "blocked actions",
                    "missing facts",
                    "execution service requirements",
                ],
                quality_gates=[
                    "Publish, procurement payment, refund, ads, policy edits, OAuth, and sensitive promises must be every-time confirmation actions.",
                    "No confirmation item may hide missing facts.",
                    "ExecutionService must have a confirmation record before any real write.",
                ],
                handoff_targets=["execution-service", "ceo", "merchant"],
                tool_permissions=[
                    AgentToolPermission("confirmation_queue", internal_only, "create and update confirmation items", "No platform write."),
                    AgentToolPermission("execution_service", "blocked_until_confirmed", "execute after valid human decision", "Not callable by this role directly."),
                ],
                forbidden_actions=list(HIGH_RISK_FORBIDDEN_ACTIONS),
                maturity_status="owned_contract_ready",
                input_requirements=["high-risk action list", "missing facts", "policy/cost/source/media status", "merchant saved rules"],
                stop_conditions=["confirmation item hides missing facts", "execution requested without decision record", "action category is prohibited"],
                knowledge_role="ceo",
            ),
        }

    def _excerpt(self, text: str, limit: int) -> str:
        collapsed = re.sub(r"\s+", " ", text).strip()
        if len(collapsed) <= limit:
            return collapsed
        return collapsed[: limit - 3] + "..."
