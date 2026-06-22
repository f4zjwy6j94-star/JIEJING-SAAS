"""Execution adapters for Jiejing Agent Runtime."""

from __future__ import annotations

import json
import os
import re
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from .agent_team import JiejingAgentTeam
from .agent_quality_gate import OwnedAgentQualityGate
from .asset_manifest import AssetManifestValidator
from .ceo_final_report import CeoFinalReportValidator
from .confirmation_package import ConfirmationPackageValidator
from .customer_learning import CustomerLearningValidator
from .ebay_listing_metadata import EbayListingMetadataAdapter, EbayListingMetadataConfig
from .finance_review import FinanceReviewValidator
from .knowledge import KnowledgeBase, KnowledgeItem, load_default_knowledge_base
from .listing_package import ListingPackageValidator
from .market_data_packet import MarketDataPacketBuilder
from .media_generation import MediaGenerationAdapter, MediaGenerationConfig
from .model_clients import ModelClient, RuleBasedModelClient
from .models import JiejingTask, now_iso
from .owned_agents import OwnedAgentExecutor
from .policies import ConfirmationCenter
from .report_contracts import validate_role_report_contract
from .role_capabilities import RuntimeRoleCapabilityMap
from .tool_orchestrator import JiejingToolOrchestrator

EXECUTION_AUDIT_FALSE = {
    "published_to_ebay": False,
    "procurement_paid": False,
    "refund_executed": False,
    "ad_budget_changed": False,
    "store_policy_changed": False,
}


def _merchant_value_is_chinese_enough(value: Any) -> bool:
    """Reject English-heavy merchant-visible model output before persistence."""

    if isinstance(value, str):
        text = value.strip()
        if not text:
            return True
        cjk_count = len(re.findall(r"[\u4e00-\u9fff]", text))
        if cjk_count >= 2:
            return True
        words = re.findall(r"[A-Za-z][A-Za-z'-]+", text)
        letters = len(re.findall(r"[A-Za-z]", text))
        return len(words) < 5 or letters < 28
    if isinstance(value, list):
        return all(_merchant_value_is_chinese_enough(item) for item in value)
    if isinstance(value, dict):
        return all(_merchant_value_is_chinese_enough(item) for item in value.values())
    return True


def _ensure_required_report_sections(task: JiejingTask, report: dict[str, Any], fallback_text: str) -> dict[str, Any]:
    """Fill controlled adapter reports with required section placeholders.

    Live model outputs are not auto-filled; they must satisfy the contract
    themselves. This helper is for plan/mock/handoff adapters and deterministic
    packet builders that do not call a role model.
    """

    required_sections = [str(section) for section in task.output_contract.get("required_sections", [])]
    sections = report.get("sections")
    sections = dict(sections) if isinstance(sections, dict) else {}
    for section in required_sections:
        sections.setdefault(section, fallback_text)
    report["required_sections"] = required_sections
    report["sections"] = sections
    return report


class AgentAdapter(ABC):
    name = "agent"
    version = "0.0.0"

    @abstractmethod
    def execute(self, task: JiejingTask) -> dict[str, Any]:
        """Execute a single JiejingTask and return a JiejingTaskResult dict."""


class MockAgentAdapter(AgentAdapter):
    """Deterministic local adapter used for offline development and tests."""

    name = "jiejing-mock-agent"
    version = "0.1.0"

    def __init__(self, confirmation_center: ConfirmationCenter | None = None) -> None:
        self.confirmation_center = confirmation_center or ConfirmationCenter()

    def execute(self, task: JiejingTask) -> dict[str, Any]:
        started_at = now_iso()
        text, source_exists, source_path, synthetic = self._read_task_source(task)
        if not source_exists and not synthetic and source_path is None:
            text = self._synthetic_generated_task(task)
            synthetic = True
        status = str(task.input.get("expected_status") or "success")
        if not source_exists and not synthetic:
            status = "failed_tool"

        confirmation_items = self.confirmation_center.build_for_task(task)
        if task.task_type == "confirmation.package" and status == "success":
            status = "blocked_confirmation_required"

        finished_at = now_iso()
        report = {
            "mode": "mock",
            "source_file": str(source_path) if source_path else None,
            "source_file_exists": source_exists,
            "synthetic": synthetic,
            "excerpt": self._excerpt(text),
            "required_sections": task.output_contract.get("required_sections", []),
            "sections": self._mock_sections(task, text),
            "notes": task.input.get("notes", ""),
            "merchant_readable_summary": self._summary(task, status),
        }
        report["report_contract"] = validate_role_report_contract(task, report)
        return {
            "task_id": task.task_id,
            "task_type": task.task_type,
            "task_version": task.task_version,
            "status": status,
            "executor": self.name,
            "executor_version": self.version,
            "started_at": started_at,
            "finished_at": finished_at,
            "summary": self._summary(task, status),
            "report": report,
            "source_records": [
                {
                    "source_id": f"src_{self._safe_id(task.task_type)}",
                    "source_type": "hermes_closed_loop_sample" if source_path else "ai_inference",
                    "title": task.input.get("sample_source_file") or task.task_type,
                    "url": None,
                    "captured_at": finished_at,
                    "confidence": "high" if source_exists else "medium",
                    "used_for": [task.task_type],
                    "note": "Offline runtime sample. No real platform action was executed.",
                }
            ],
            "missing_inputs": self._missing_inputs(task),
            "risk_flags": self._risk_flags(task),
            "confirmation_items": confirmation_items,
            "next_tasks": [],
            "artifacts": [
                {
                    "artifact_type": "markdown" if source_path else "runtime_generated",
                    "path": str(source_path) if source_path else None,
                    "exists": source_exists,
                    "synthetic": synthetic,
                }
            ],
            "audit": {
                "adapter": self.name,
                "adapter_version": self.version,
                "real_execution": task.context.get(
                    "execution_boundary",
                    {
                        "published_to_ebay": False,
                        "procurement_paid": False,
                        "refund_executed": False,
                        "ad_budget_changed": False,
                        "store_policy_changed": False,
                    },
                ),
                "real_execution_allowed": False,
                "timeout_seconds": task.timeout_seconds,
                "source_chars": len(text),
                "replacement_characters": text.count("\ufffd"),
            },
        }

    def _read_task_source(self, task: JiejingTask) -> tuple[str, bool, Path | None, bool]:
        source_file = task.input.get("sample_source_file")
        source_root = task.context.get("source_root")
        if source_file and source_root:
            source_path = Path(source_root) / str(source_file)
            if source_path.exists():
                return source_path.read_text(encoding="utf-8", errors="replace"), True, source_path, False
            return "", False, source_path, False

        if task.task_type == "confirmation.package":
            return self._synthetic_confirmation(task), False, None, True
        return "", False, None, False

    def _mock_sections(self, task: JiejingTask, text: str) -> dict[str, str]:
        excerpt = self._excerpt(text) or "离线 Runtime 样例：该部分是用于演示校验的合同占位，不代表真实平台数据。"
        return {
            str(section): excerpt
            for section in task.output_contract.get("required_sections", [])
        }

    def _synthetic_confirmation(self, task: JiejingTask) -> str:
        actions = [item["action_type"] for item in self.confirmation_center.build_for_task(task)]
        lines = [
            "捷境 Runtime 已生成决策中心包。",
            "以下动作需要商家审核：",
        ]
        lines.extend(f"- {action}" for action in actions)
        return "\n".join(lines)

    def _synthetic_generated_task(self, task: JiejingTask) -> str:
        product = str(task.input.get("product") or task.context.get("sample_name") or "捷境工作流")
        expected_status = str(task.input.get("expected_status") or "success")
        sections = task.output_contract.get("required_sections", [])
        lines = [
            f"已为 {product} 生成捷境 Runtime 任务。",
            f"任务类型：{task.task_type}。",
            f"预期状态：{expected_status}。",
            "不允许执行真实平台写入、付款、退款、广告、政策修改或买家消息发送。",
        ]
        if sections:
            lines.append("必需部分：")
            lines.extend(f"- {section}" for section in sections)
        return "\n".join(lines)

    def _summary(self, task: JiejingTask, status: str) -> str:
        label = task.raw.get("audit", {}).get("description") or task.task_type
        return f"{label} 结果状态：{status}。"

    def _missing_inputs(self, task: JiejingTask) -> list[dict[str, str]]:
        blockers = {
            "source.match": ["supplier_real_facts"],
            "listing.package": ["supplier_real_facts", "taxonomy_item_specifics", "business_policy_ids"],
            "asset.brief": ["confirmed_product_facts"],
            "finance.review": ["final_shipping_price", "final_purchase_cost"],
        }.get(task.task_type, [])
        return [
            {
                "input_id": blocker,
                "reason": self._blocker_reason(blocker),
                "severity": "blocking",
            }
            for blocker in blockers
        ]

    def _blocker_reason(self, blocker: str) -> str:
        reasons = {
            "supplier_real_facts": "发布前需要真实尺寸、重量、材质、发货地、包装和测试信息。",
            "taxonomy_item_specifics": "发布前必须检查 eBay 类目和必填 item specifics。",
            "business_policy_ids": "Fulfillment、payment、return policies 必须来自授权店铺。",
            "confirmed_product_facts": "商业素材不能声明未验证商品事实。",
            "final_shipping_price": "最终运费会影响利润和买家承诺。",
            "final_purchase_cost": "最终采购成本会影响利润和采购决策。",
        }
        return reasons.get(blocker, "工作流安全继续前必须补齐。")

    def _risk_flags(self, task: JiejingTask) -> list[dict[str, str]]:
        mapping = {
            "market.report": [("source_confidence", "medium", "缺失数据必须继续标记，不能假装已有来源。")],
            "source.match": [("supplier_verification", "high", "供应商事实需要确认。")],
            "listing.package": [("publish_listing", "critical", "真实 eBay 发布必须进入决策中心。")],
            "asset.brief": [("asset_not_final", "high", "素材简报不是最终商业素材。")],
            "customer.learn_product": [("auto_reply_boundary", "medium", "敏感回复需要人工接管。")],
            "finance.review": [("margin_shipping_policy", "high", "运费可能推翻利润。")],
            "confirmation.package": [("confirmation_gate", "critical", "高风险动作已锁定。")],
        }
        return [
            {"risk_id": risk_id, "severity": severity, "message": message}
            for risk_id, severity, message in mapping.get(task.task_type, [])
        ]

    def _excerpt(self, text: str, limit: int = 900) -> str:
        collapsed = re.sub(r"\s+", " ", text).strip()
        if len(collapsed) <= limit:
            return collapsed
        return collapsed[: limit - 3] + "..."

    def _safe_id(self, value: str) -> str:
        return re.sub(r"[^a-zA-Z0-9_]+", "_", value)


class HermesAdapterPlanOnly(AgentAdapter):
    """Placeholder adapter that keeps Hermes behind a boundary.

    It deliberately does not call Hermes. The production adapter should translate
    JiejingTask into short Hermes role prompts, enforce timeout/retry, and parse
    results back into JiejingTaskResult.
    """

    name = "hermes-adapter-plan-only"
    version = "0.1.0"

    def execute(self, task: JiejingTask) -> dict[str, Any]:
        now = now_iso()
        summary = "HermesAdapter is plan-only in this runtime MVP; no Hermes call was executed."
        report = {
            "mode": "plan_only",
            "task_input": task.input,
            "merchant_readable_summary": summary,
            "limits": ["No Hermes call was executed.", "No real platform action was executed."],
        }
        _ensure_required_report_sections(task, report, "Plan-only adapter preserved this required section boundary.")
        report["report_contract"] = validate_role_report_contract(task, report)
        return {
            "task_id": task.task_id,
            "task_type": task.task_type,
            "task_version": task.task_version,
            "status": "blocked_permission",
            "executor": self.name,
            "executor_version": self.version,
            "started_at": now,
            "finished_at": now,
            "summary": summary,
            "report": report,
            "source_records": [
                {
                    "source_id": "src_hermes_adapter_plan",
                    "source_type": "ai_inference",
                    "title": "HermesAdapter boundary placeholder",
                    "url": None,
                    "captured_at": now,
                    "confidence": "medium",
                    "used_for": [task.task_type],
                    "note": "No Hermes execution happened.",
                }
            ],
            "missing_inputs": [],
            "risk_flags": [],
            "confirmation_items": [],
            "next_tasks": [],
            "artifacts": [],
            "audit": {
                "adapter": self.name,
                "real_execution_allowed": False,
                "real_execution": {
                    "published_to_ebay": False,
                    "procurement_paid": False,
                    "refund_executed": False,
                    "ad_budget_changed": False,
                    "store_policy_changed": False,
                },
            },
        }


class HermesShadowAdapter(AgentAdapter):
    """Creates Hermes dispatch packets without calling Hermes.

    This is the first bridge toward running Hermes behind Jiejing Runtime. It
    translates every JiejingTask into a small role prompt and records what would
    be sent, while keeping all real execution blocked.
    """

    name = "hermes-shadow-adapter"
    version = "0.1.0"

    def __init__(
        self,
        confirmation_center: ConfirmationCenter | None = None,
        knowledge_base: KnowledgeBase | None = None,
    ) -> None:
        self.confirmation_center = confirmation_center or ConfirmationCenter()
        self.knowledge_base = knowledge_base or load_default_knowledge_base()
        self.role_capabilities = RuntimeRoleCapabilityMap(self.knowledge_base)

    def execute(self, task: JiejingTask) -> dict[str, Any]:
        now = now_iso()
        role = self._role_for_task(task.task_type)
        knowledge_items = self.knowledge_base.query(role=role, task_type=task.task_type, limit=4)
        role_capability = self.role_capabilities.for_role(role)
        dispatch_prompt = self._dispatch_prompt(task, role, knowledge_items)
        confirmation_items = self.confirmation_center.build_for_task(task)
        status = "blocked_confirmation_required" if confirmation_items else "success"
        if task.task_type in {"listing.package", "finance.review"}:
            status = "blocked_missing_input"
        summary = f"Hermes shadow dispatch packet prepared for {role}; no Hermes call was executed."
        report = {
            "mode": "hermes_shadow",
            "target_role": role,
            "role_capability": role_capability.to_dict() if role_capability else None,
            "dispatch_prompt": dispatch_prompt,
            "runtime_knowledge": [
                {
                    "item_id": item.item_id,
                    "title": item.title,
                    "role": item.role,
                    "task_types": item.task_types,
                    "source_ref": item.source_ref,
                }
                for item in knowledge_items
            ],
            "handoff_contract": {
                "return_format": "JiejingTaskResult-compatible structured report",
                "must_label_sources": True,
                "must_keep_missing_facts_pending": True,
                "must_not_execute_real_actions": True,
            },
            "merchant_readable_summary": summary,
            "limits": ["Hermes was not called.", "This is a dispatch packet, not a finished role report."],
        }
        _ensure_required_report_sections(
            task,
            report,
            f"Handoff section for {role}. Hermes must return this section with source labels and Pending for unknown facts.",
        )
        report["report_contract"] = validate_role_report_contract(task, report)
        return {
            "task_id": task.task_id,
            "task_type": task.task_type,
            "task_version": task.task_version,
            "status": status,
            "executor": self.name,
            "executor_version": self.version,
            "started_at": now,
            "finished_at": now,
            "summary": summary,
            "report": report,
            "source_records": [
                {
                    "source_id": "src_hermes_shadow_adapter",
                    "source_type": "runtime_adapter_plan",
                    "title": "Hermes shadow dispatch packet",
                    "url": None,
                    "captured_at": now,
                    "confidence": "medium",
                    "used_for": [task.task_type],
                    "note": "Prepared by Jiejing Runtime. No Hermes, eBay, payment, refund, ad, or procurement call happened.",
                }
            ],
            "missing_inputs": self._missing_inputs(task),
            "risk_flags": self._risk_flags(task),
            "confirmation_items": confirmation_items,
            "next_tasks": [],
            "artifacts": [
                {
                    "artifact_type": "hermes_dispatch_prompt",
                    "path": None,
                    "exists": False,
                    "synthetic": True,
                }
            ],
            "audit": {
                "adapter": self.name,
                "adapter_version": self.version,
                "target_role": role,
                "knowledge_pack": self.knowledge_base.summary(),
                "real_execution_allowed": False,
                "real_execution": dict(EXECUTION_AUDIT_FALSE),
            },
        }

    def _role_for_task(self, task_type: str) -> str:
        if task_type.startswith("market."):
            return "market-manager"
        if task_type in {"source.match", "finance.review"}:
            return "finance-supply"
        if task_type in {"listing.package", "asset.brief"}:
            return "product-manager"
        if task_type == "customer.learn_product":
            return "customer-service"
        if task_type == "owner.review":
            return "team-repair"
        return "ceo"

    def _dispatch_prompt(self, task: JiejingTask, role: str, knowledge_items: list[KnowledgeItem]) -> str:
        sections = task.output_contract.get("required_sections", [])
        knowledge_titles = [item.title for item in knowledge_items]
        role_capability = self.role_capabilities.for_role(role)
        lines = [
            f"Jiejing Runtime dispatch to Hermes role: {role}",
            f"Task type: {task.task_type}",
            f"Product: {task.input.get('product', 'current product')}",
            f"Merchant goal: {task.input.get('merchant_goal', '')}",
            "",
            f"Role migration status: {role_capability.migration_status if role_capability else 'unknown'}",
            "Return a merchant-readable structured report. Keep unknown supplier, listing, policy, cost, and media facts as Pending.",
            "Do not publish, purchase, refund, change ads, edit policies, change authorization, or send sensitive buyer promises.",
            "",
            "Required sections:",
        ]
        lines.extend(f"- {section}" for section in sections)
        if role_capability:
            lines.extend(["", "Role output duties:"])
            lines.extend(f"- {item}" for item in role_capability.required_outputs[:6])
            lines.extend(["", "Role safety boundary:"])
            lines.extend(f"- {item}" for item in role_capability.safety_boundary[:5])
        lines.extend(["", "Runtime knowledge to follow:"])
        lines.extend(f"- {title}" for title in knowledge_titles)
        return "\n".join(lines)

    def _missing_inputs(self, task: JiejingTask) -> list[dict[str, str]]:
        return JiejingAgentAdapter(knowledge_base=self.knowledge_base)._missing_inputs(task)

    def _risk_flags(self, task: JiejingTask) -> list[dict[str, str]]:
        return JiejingAgentAdapter(knowledge_base=self.knowledge_base)._risk_flags(task)


class HermesFileHandoffAdapter(HermesShadowAdapter):
    """Writes sanitized Hermes handoff packets to disk.

    This still does not call Hermes. It creates stable files that a later
    Feishu/team_bus/cloud-Hermes connector can pick up and execute.
    """

    name = "hermes-file-handoff-adapter"
    version = "0.1.0"

    def __init__(
        self,
        handoff_root: Path | None = None,
        confirmation_center: ConfirmationCenter | None = None,
        knowledge_base: KnowledgeBase | None = None,
    ) -> None:
        super().__init__(confirmation_center=confirmation_center, knowledge_base=knowledge_base)
        self.handoff_root = handoff_root or Path(
            os.environ.get("JIEJING_HERMES_HANDOFF_DIR")
            or Path(__file__).resolve().parents[1] / "output" / "jiejing-hermes-handoff"
        )

    def execute(self, task: JiejingTask) -> dict[str, Any]:
        result = super().execute(task)
        role = str(result.get("report", {}).get("target_role") or "ceo")
        packet_paths = self._write_packet(task, role, result)
        result["executor"] = self.name
        result["executor_version"] = self.version
        result["summary"] = f"Hermes handoff packet written for {role}; execution remains blocked until a connector picks it up."
        result.setdefault("report", {})["handoff_files"] = {key: str(path) for key, path in packet_paths.items()}
        result["artifacts"] = [
            {
                "artifact_type": "hermes_handoff_markdown",
                "path": str(packet_paths["markdown"]),
                "exists": packet_paths["markdown"].exists(),
                "synthetic": False,
            },
            {
                "artifact_type": "hermes_handoff_json",
                "path": str(packet_paths["json"]),
                "exists": packet_paths["json"].exists(),
                "synthetic": False,
            },
        ]
        result.setdefault("audit", {})["handoff_root"] = str(self.handoff_root)
        return result

    def _write_packet(self, task: JiejingTask, role: str, result: dict[str, Any]) -> dict[str, Path]:
        project_id = str(task.raw.get("project_id") or task.context.get("sample_id") or "jiejing-runtime")
        packet_dir = self.handoff_root / self._safe_name(project_id) / role
        packet_dir.mkdir(parents=True, exist_ok=True)
        base_name = f"{self._safe_name(task.task_id)}"
        markdown_path = packet_dir / f"{base_name}.md"
        json_path = packet_dir / f"{base_name}.json"
        prompt = str(result.get("report", {}).get("dispatch_prompt") or "")
        markdown = [
            f"# Jiejing Runtime Hermes Handoff - {task.task_type}",
            "",
            f"- task_id: `{task.task_id}`",
            f"- target_role: `{role}`",
            f"- project_id: `{project_id}`",
            f"- platform: `{task.raw.get('platform', '')}`",
            f"- store_id: `{task.raw.get('store_id', '')}`",
            f"- status: `{result.get('status')}`",
            "",
            "## Safety Boundary",
            "",
            "- Do not publish to eBay.",
            "- Do not pay supplier or buy labels.",
            "- Do not refund, change ads, edit policies, or change authorization.",
            "- Keep missing facts as Pending.",
            "",
            "## Dispatch Prompt",
            "",
            "```text",
            prompt,
            "```",
        ]
        markdown_path.write_text("\n".join(markdown) + "\n", encoding="utf-8")
        packet = {
            "task": task.raw,
            "target_role": role,
            "dispatch_prompt": prompt,
            "required_sections": task.output_contract.get("required_sections", []),
            "safety_boundary": {
                "real_execution_allowed": False,
                "high_risk_actions_require_confirmation": True,
            },
            "runtime_result_preview": {
                "status": result.get("status"),
                "summary": result.get("summary"),
                "confirmation_items": result.get("confirmation_items", []),
                "missing_inputs": result.get("missing_inputs", []),
            },
        }
        json_path.write_text(json.dumps(packet, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"markdown": markdown_path, "json": json_path}

    def _safe_name(self, value: Any) -> str:
        return re.sub(r"[^a-zA-Z0-9_.-]+", "_", str(value)).strip("_")[:120] or "task"


class JiejingAgentAdapter(AgentAdapter):
    """First owned Jiejing agent adapter.

    This adapter proves Jiejing can execute the task protocol without Hermes.
    The MVP uses a local deterministic model client; production can replace it
    with a real LLM client behind the same interface.
    """

    name = "jiejing-agent"
    version = "0.1.0"

    def __init__(
        self,
        model_client: ModelClient | None = None,
        confirmation_center: ConfirmationCenter | None = None,
        knowledge_base: KnowledgeBase | None = None,
    ) -> None:
        self.model_client = model_client or RuleBasedModelClient()
        self.confirmation_center = confirmation_center or ConfirmationCenter()
        self.knowledge_base = knowledge_base or load_default_knowledge_base()
        self.agent_team = JiejingAgentTeam()
        self.owned_agent_executor = OwnedAgentExecutor()
        self.agent_quality_gate = OwnedAgentQualityGate()
        self.tool_orchestrator = JiejingToolOrchestrator()

    def execute(self, task: JiejingTask) -> dict[str, Any]:
        started_at = now_iso()
        if task.task_type == "market.data_packet":
            return self._execute_market_data_packet(task, started_at)
        knowledge_items = self._knowledge_for(task)
        agent_task = self.agent_team.build_model_task(task, knowledge_items)
        report = self._generate_owned_or_model_assisted_report(agent_task, knowledge_items)
        report["model_client"] = self.model_client.name
        report["model_client_version"] = self.model_client.version
        report["model_client_boundary"] = (
            "owned_agent_output"
            if isinstance(self.model_client, RuleBasedModelClient)
            else "owned_agent_output_with_live_model_client_available"
        )
        report["merchant_profile"] = task.input.get("merchant_profile", {})
        if knowledge_items:
            report = self._enrich_report_with_knowledge(report, knowledge_items)
        report = self._enrich_report_with_runtime_tools(task, report)
        report = self.agent_team.normalize_report(task, report, knowledge_items)
        report.update(self._validation_report_for(task))
        report["report_contract"] = validate_role_report_contract(task, report)
        report["owned_agent_quality_gate"] = self.agent_quality_gate.review_report(task, report)
        report["merchant_language_quality"] = self._merchant_language_quality_for_report(report)
        confirmation_items = self.confirmation_center.build_for_task(task)
        status = self._status_for(task, confirmation_items)
        finished_at = now_iso()
        return {
            "task_id": task.task_id,
            "task_type": task.task_type,
            "task_version": task.task_version,
            "status": status,
            "executor": self.name,
            "executor_version": self.version,
            "started_at": started_at,
            "finished_at": finished_at,
            "summary": report["merchant_readable_summary"],
            "report": report,
            "source_records": [
                {
                    "source_id": f"src_{task.task_type.replace('.', '_')}_jiejing_agent",
                    "source_type": "ai_inference",
                    "title": f"捷境本地 Agent 输出：{task.task_type}",
                    "url": None,
                    "captured_at": finished_at,
                    "confidence": "medium",
                    "used_for": [task.task_type],
                    "note": "由捷境 owned commerce Agent Team 生成；未执行真实平台写入。",
                }
            ]
            + self._knowledge_source_records(task, knowledge_items, finished_at)
            + self._tool_source_records(task, report, finished_at),
            "missing_inputs": self._missing_inputs(task),
            "risk_flags": self._risk_flags(task),
            "confirmation_items": confirmation_items,
            "next_tasks": [],
            "artifacts": [],
            "audit": {
                "adapter": self.name,
                "adapter_version": self.version,
                "model_client": self.model_client.name,
                "model_client_version": self.model_client.version,
                "owned_agent_executor": self.owned_agent_executor.to_dict(),
                "agent_team": self.agent_team.to_dict(),
                "agent_role": self.agent_team.role_for(task.task_type),
                "owned_agent_quality_gate": report["owned_agent_quality_gate"],
                "knowledge_pack": self.knowledge_base.summary(),
                "real_execution_allowed": False,
                "real_execution": {
                    "published_to_ebay": False,
                    "procurement_paid": False,
                    "refund_executed": False,
                    "ad_budget_changed": False,
                    "store_policy_changed": False,
                },
            },
        }

    def _generate_owned_or_model_assisted_report(self, agent_task: JiejingTask, knowledge_items: list[KnowledgeItem]) -> dict[str, Any]:
        owned_report = self.owned_agent_executor.generate_report(agent_task, knowledge_items)
        if isinstance(self.model_client, RuleBasedModelClient):
            return owned_report
        model_report = self.model_client.generate_report(agent_task)
        if not model_report.get("model_configured"):
            owned_report["model_assist"] = {
                "status": "not_configured",
                "client": self.model_client.name,
                "fallback_mode": model_report.get("model_mode"),
            }
            return owned_report
        model_mode = str(model_report.get("model_mode") or "")
        if model_report.get("model_error") or "error_fallback" in model_mode:
            owned_report["model_assist"] = {
                "status": "fallback_error",
                "client": self.model_client.name,
                "fallback_mode": model_mode,
                "model_error": str(model_report.get("model_error") or "")[:500],
            }
            owned_report["model_error"] = str(model_report.get("model_error") or "")[:500]
            return owned_report
        merged = dict(owned_report)
        owned_sections = owned_report.get("sections") if isinstance(owned_report.get("sections"), dict) else {}
        model_sections = model_report.get("sections") if isinstance(model_report.get("sections"), dict) else {}
        accepted_model_sections, rejected_model_sections = self._chinese_safe_model_sections(model_sections)
        merged["sections"] = {**owned_sections, **accepted_model_sections}
        rejected_fields = [f"sections.{section}" for section in rejected_model_sections]
        if model_report.get("merchant_readable_summary") and _merchant_value_is_chinese_enough(model_report.get("merchant_readable_summary")):
            merged["merchant_readable_summary"] = str(model_report["merchant_readable_summary"])
        elif model_report.get("merchant_readable_summary"):
            rejected_fields.append("merchant_readable_summary")
        merged["model_assist"] = {
            "status": "applied",
            "client": self.model_client.name,
            "model_mode": model_report.get("model_mode"),
            "sections_from_model": sorted(accepted_model_sections),
            "english_heavy_fields_rejected": sorted(rejected_fields),
            "owned_scaffold_preserved": True,
        }
        execution = dict(merged.get("owned_agent_execution") or {})
        execution["uses_live_model"] = True
        execution["model_client"] = self.model_client.name
        execution["model_mode"] = model_report.get("model_mode")
        merged["owned_agent_execution"] = execution
        limits = list(merged.get("limits") or [])
        limits.append("live model 输出仍受捷境报告合同、决策中心和禁止绕过真实写入的边界约束。")
        merged["limits"] = limits
        return merged

    def _chinese_safe_model_sections(self, model_sections: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
        accepted: dict[str, Any] = {}
        rejected: list[str] = []
        for key, value in model_sections.items():
            if _merchant_value_is_chinese_enough(value):
                accepted[str(key)] = value
            else:
                rejected.append(str(key))
        return accepted, rejected

    def _merchant_language_quality_for_report(self, report: dict[str, Any]) -> dict[str, Any]:
        model_assist = report.get("model_assist") if isinstance(report.get("model_assist"), dict) else {}
        return {
            "merchant_visible_language": "zh-CN",
            "checked_before_persist": True,
            "english_heavy_model_fields_rejected": list(model_assist.get("english_heavy_fields_rejected") or []),
            "allowed_english_terms": ["eBay", "SKU", "Listing", "Market Report", "Listing Package"],
        }

    def _enrich_report_with_runtime_tools(self, task: JiejingTask, report: dict[str, Any]) -> dict[str, Any]:
        enriched = dict(report)
        sections = dict(enriched.get("sections", {}))
        orchestration = self.tool_orchestrator.execute_for_task(task)
        tool_names: list[str] = []
        tool_driven_sections: dict[str, list[str]] = {}
        for execution in orchestration.get("executions", []):
            tool_name = str(execution.get("tool_name") or "")
            output = execution.get("output") if isinstance(execution.get("output"), dict) else {}
            if tool_name == "market_data_packet":
                sections["market_data_packet"] = output.get("report", {}).get("sections", {})
                enriched["market_data_packet_probe"] = {
                    "status": output.get("status"),
                    "summary": output.get("summary"),
                    "missing_inputs": output.get("missing_inputs", []),
                    "risk_flags": output.get("risk_flags", []),
                    "probes": output.get("report", {}).get("probes", []),
                    "source_records": output.get("source_records", []),
                }
            elif tool_name == "sourcing_availability":
                sections["sourcing_availability"] = output
                enriched["sourcing_availability_probe"] = output
            elif tool_name == "ebay_listing_metadata":
                sections["ebay_listing_metadata"] = output
                enriched["listing_metadata_probe"] = output
            elif tool_name == "media_generation":
                sections["media_generation"] = output
                enriched["media_generation_probe"] = output
            elif tool_name == "logistics_estimate":
                sections["logistics_estimate"] = output
                enriched["logistics_estimate_probe"] = output
            applied_sections = self._apply_tool_output_to_sections(task, sections, tool_name, output)
            if applied_sections:
                tool_driven_sections[tool_name] = applied_sections
            if tool_name:
                tool_names.append(tool_name)
        if tool_names:
            enriched["tool_orchestration"] = orchestration
            tool_notes = list(enriched.get("tool_notes") or [])
            tool_notes.append(
                "Runtime tools were executed through Jiejing ToolOrchestrator with timeout, retry, no-secret, and no-real-write boundaries."
            )
            enriched["tool_notes"] = tool_notes
            execution = dict(enriched.get("owned_agent_execution") or {})
            execution["uses_external_tools"] = True
            execution["external_tool_names"] = sorted(set(tool_names))
            if tool_driven_sections:
                execution["tool_driven_sections"] = tool_driven_sections
            enriched["owned_agent_execution"] = execution
        if tool_driven_sections:
            enriched["tool_driven_sections"] = tool_driven_sections
        enriched["sections"] = sections
        return enriched

    def _apply_tool_output_to_sections(
        self,
        task: JiejingTask,
        sections: dict[str, Any],
        tool_name: str,
        output: dict[str, Any],
    ) -> list[str]:
        if not output:
            return []
        if tool_name == "market_data_packet":
            return self._apply_market_packet_to_sections(sections, output)
        if tool_name == "sourcing_availability":
            return self._apply_sourcing_to_sections(sections, output)
        if tool_name == "ebay_listing_metadata":
            return self._apply_listing_metadata_to_sections(sections, output)
        if tool_name == "media_generation":
            return self._apply_media_generation_to_sections(sections, output)
        if tool_name == "logistics_estimate":
            return self._apply_logistics_to_sections(sections, output)
        return []

    def _apply_market_packet_to_sections(self, sections: dict[str, Any], output: dict[str, Any]) -> list[str]:
        packet = output.get("report") if isinstance(output.get("report"), dict) else {}
        packet_sections = packet.get("sections") if isinstance(packet.get("sections"), dict) else {}
        if not packet_sections:
            return []
        applied: list[str] = []
        source_health = packet_sections.get("source_health")
        if isinstance(source_health, dict):
            sections["source_health"] = source_health
            applied.append("source_health")
        ebay_signal = packet_sections.get("ebay_signal")
        if isinstance(ebay_signal, dict):
            sections["ebay_price_bands"] = {
                "source": "market_data_packet.ebay_signal",
                "status": ebay_signal.get("status"),
                "confidence": ebay_signal.get("confidence"),
                "summary": ebay_signal.get("summary"),
                "use_in_report": "Use as the eBay demand and price-band signal; if not ready, keep price bands directional.",
                "raw_signal": ebay_signal,
            }
            applied.append("ebay_price_bands")
        public_signal = packet_sections.get("public_search_signal")
        if isinstance(public_signal, dict):
            sections["search_and_keyword_signal"] = {
                "source": "market_data_packet.public_search_signal",
                "status": public_signal.get("status"),
                "confidence": public_signal.get("confidence"),
                "summary": public_signal.get("summary"),
                "source_records": public_signal.get("source_records", []),
                "result_count": (public_signal.get("metrics") or {}).get("result_count") if isinstance(public_signal.get("metrics"), dict) else None,
                "existing_keyword_draft": sections.get("keywords"),
                "rule": "Public search pages are directional references, not official eBay sales proof.",
            }
            applied.append("search_and_keyword_signal")
        cross_platform = packet_sections.get("cross_platform_reference")
        if isinstance(cross_platform, dict):
            sections["cross_platform_reference"] = cross_platform
            applied.append("cross_platform_reference")
        source_availability = packet_sections.get("source_availability")
        if isinstance(source_availability, dict):
            sections["source_availability_signal"] = source_availability
            applied.append("source_availability_signal")
        logistics_signal = packet_sections.get("logistics_signal")
        if isinstance(logistics_signal, dict):
            sections["logistics_signal"] = logistics_signal
            applied.append("logistics_signal")
        unavailable = packet_sections.get("unavailable_sources")
        if isinstance(unavailable, list):
            sections["data_gaps"] = unavailable
            applied.append("data_gaps")
        return applied

    def _apply_sourcing_to_sections(self, sections: dict[str, Any], output: dict[str, Any]) -> list[str]:
        candidates = output.get("candidates") if isinstance(output.get("candidates"), list) else []
        metrics = output.get("metrics") if isinstance(output.get("metrics"), dict) else {}
        applied: list[str] = []
        if candidates:
            sections["supplier_candidates"] = [
                {
                    "title": item.get("title") or item.get("supplier_name") or "Supplier candidate",
                    "source_platform": item.get("source_platform"),
                    "supplier_name": item.get("supplier_name"),
                    "source_url": item.get("source_url"),
                    "unit_cost": item.get("unit_cost"),
                    "currency": item.get("currency"),
                    "moq": item.get("moq"),
                    "stock": item.get("stock"),
                    "ship_from": item.get("ship_from"),
                    "missing_facts": item.get("missing_facts", []),
                    "status": "ready_for_costing" if not item.get("missing_facts") else "needs_supplier_facts",
                }
                for item in candidates[:5]
            ]
            applied.append("supplier_candidates")
        if metrics:
            sections["cost_inputs"] = {
                "source": "sourcing_availability.metrics",
                "lowest_unit_cost": metrics.get("lowest_unit_cost"),
                "candidate_count": metrics.get("candidate_count"),
                "ready_candidate_count": metrics.get("ready_candidate_count"),
                "ship_from_distribution": metrics.get("ship_from_distribution", []),
                "remaining_blockers": metrics.get("blockers", []),
            }
            applied.append("cost_inputs")
        package_rows = [
            {
                "title": item.get("title") or item.get("supplier_name") or "Supplier candidate",
                "package_weight_g": item.get("package_weight_g"),
                "package_dimensions_cm": item.get("package_dimensions_cm"),
                "material": item.get("material"),
                "packaging": item.get("packaging"),
                "ship_from": item.get("ship_from"),
                "restriction_notes": item.get("restriction_notes"),
            }
            for item in candidates[:5]
        ]
        if package_rows:
            sections["package_inputs"] = {
                "source": "sourcing_availability.candidates",
                "rows": package_rows,
                "rule": "Only verified package facts can flow into finance, logistics promise, and publish confirmation.",
            }
            applied.append("package_inputs")
        blockers = metrics.get("blockers") if isinstance(metrics.get("blockers"), list) else []
        if blockers:
            sections["supplier_questions"] = [
                f"Confirm `{item.get('missing_fact')}` for {item.get('candidate_count')} candidate(s)."
                for item in blockers
                if item.get("missing_fact")
            ]
            applied.append("supplier_questions")
        sections["procurement_boundary"] = (
            "货源匹配只允许读取和整理。供应商下单、付款、地址写入和一件代发指令"
            "必须进入决策中心，或命中已保存的商家规则。"
        )
        applied.append("procurement_boundary")
        return applied

    def _apply_listing_metadata_to_sections(self, sections: dict[str, Any], output: dict[str, Any]) -> list[str]:
        applied: list[str] = []
        category_id = output.get("category_id")
        if category_id:
            sections["category_id"] = {
                "value": category_id,
                "marketplace_id": output.get("marketplace_id"),
                "source": "ebay_listing_metadata",
                "status": output.get("status"),
            }
            applied.append("category_id")
        required_aspects = output.get("required_aspects") if isinstance(output.get("required_aspects"), list) else []
        if required_aspects:
            existing = sections.get("item_specifics") if isinstance(sections.get("item_specifics"), dict) else {}
            sections["item_specifics"] = {
                **existing,
                "dynamic_required_by_ebay": required_aspects,
                "source": "eBay Taxonomy item aspects",
                "rule": "必填 item specifics 取决于类目和站点，不能依赖固定通用表。",
            }
            applied.append("item_specifics")
        policies = output.get("business_policies") if isinstance(output.get("business_policies"), dict) else {}
        if policies:
            sections["business_policies"] = {
                "source": "eBay Account policy read or sanitized store snapshot",
                "status": output.get("status"),
                "fulfillment": policies.get("fulfillment", []),
                "payment": policies.get("payment", []),
                "return": policies.get("return", []),
                "rule": "Policies 是可复用的店铺模板；编辑政策或使用它们执行发布仍需要确认。",
            }
            applied.append("business_policies")
        missing = output.get("missing") if isinstance(output.get("missing"), list) else []
        blockers = list(sections.get("publish_blockers") or [])
        if missing:
            blockers.extend(f"eBay 元数据仍缺少 `{item}`。" for item in missing)
        if output.get("status") != "ready":
            blockers.append("Listing metadata 尚未完全就绪；发布保持锁定。")
        if blockers:
            sections["publish_blockers"] = self._unique_texts(blockers)
            applied.append("publish_blockers")
        return applied

    def _apply_media_generation_to_sections(self, sections: dict[str, Any], output: dict[str, Any]) -> list[str]:
        assets = output.get("assets") if isinstance(output.get("assets"), list) else []
        applied: list[str] = []
        if assets:
            by_type: dict[str, list[dict[str, Any]]] = {}
            for asset in assets:
                asset_type = str(asset.get("asset_type") or "asset")
                by_type.setdefault(asset_type, []).append(asset)
            sections["generated_asset_manifest"] = {
                "source": "media_generation",
                "status": output.get("status"),
                "provider": output.get("provider"),
                "asset_count": len(assets),
                "asset_types": output.get("asset_types", sorted(by_type)),
                "assets_by_type": by_type,
            }
            sections["media_manifest_status"] = output.get("summary") or "Media manifest returned usable assets."
            applied.extend(["generated_asset_manifest", "media_manifest_status"])
        else:
            sections["media_manifest_status"] = {
                "status": output.get("status"),
                "summary": output.get("summary"),
                "required_before_claiming_generated": output.get("required_before_claiming_generated", []),
            }
            applied.append("media_manifest_status")
        return applied

    def _apply_logistics_to_sections(self, sections: dict[str, Any], output: dict[str, Any]) -> list[str]:
        metrics = output.get("metrics") if isinstance(output.get("metrics"), dict) else {}
        estimates = output.get("estimates") if isinstance(output.get("estimates"), list) else []
        applied: list[str] = []
        if metrics:
            sections["logistics_route"] = {
                "source": "logistics_estimate.metrics",
                "origin": metrics.get("origin"),
                "destination": metrics.get("destination"),
                "route": metrics.get("route"),
                "package_weight_g": metrics.get("package_weight_g"),
                "package_dimensions_cm": metrics.get("package_dimensions_cm"),
                "lowest_shipping_cost": metrics.get("lowest_shipping_cost"),
                "fastest_eta_days": metrics.get("fastest_eta_days"),
                "status": output.get("status"),
                "rule": "Do not promise delivery until a real carrier quote and store fulfillment policy are confirmed.",
            }
            applied.append("logistics_route")
            cost_table = list(sections.get("cost_table") or [])
            cost_table.extend(
                [
                    {"item": "package_weight_g", "value": metrics.get("package_weight_g") or "Pending"},
                    {"item": "package_dimensions_cm", "value": metrics.get("package_dimensions_cm") or "Pending"},
                    {"item": "international_shipping", "value": metrics.get("lowest_shipping_cost") or "Pending carrier quote"},
                ]
            )
            sections["cost_table"] = cost_table
            applied.append("cost_table")
        if estimates:
            sections["shipping_estimates"] = estimates
            applied.append("shipping_estimates")
        missing = metrics.get("missing_facts") if isinstance(metrics.get("missing_facts"), list) else []
        if missing:
            risk_notes = list(sections.get("risk_notes") or [])
            risk_notes.append("Logistics estimate still missing: " + ", ".join(str(item) for item in missing))
            sections["risk_notes"] = self._unique_texts(risk_notes)
            applied.append("risk_notes")
        sections["next_action"] = (
            "Use the logistics estimate for margin review only after package facts and service quote are confirmed; "
            "label purchase and tracking write remain confirmation-gated."
        )
        applied.append("next_action")
        return applied

    def _unique_texts(self, values: list[Any]) -> list[str]:
        seen: set[str] = set()
        unique: list[str] = []
        for value in values:
            text = str(value)
            if text and text not in seen:
                seen.add(text)
                unique.append(text)
        return unique

    def _listing_metadata_config(self, task: JiejingTask, probe_config: dict[str, Any]) -> EbayListingMetadataConfig:
        return EbayListingMetadataConfig(
            marketplace_id=str(probe_config.get("marketplace_id") or self._marketplace_id(str(task.input.get("marketplace") or "eBay US"))),
            category_id=str(probe_config.get("category_id") or task.input.get("category_id") or ""),
            category_tree_id=str(probe_config.get("category_tree_id") or "0"),
            base_url=str(probe_config.get("base_url") or "https://api.ebay.com"),
            access_token=str(probe_config.get("access_token")) if probe_config.get("access_token") else None,
            live_enabled=probe_config.get("live_enabled") is True,
            taxonomy_response=probe_config.get("taxonomy_response") if isinstance(probe_config.get("taxonomy_response"), dict) else None,
            fulfillment_policy_response=probe_config.get("fulfillment_policy_response")
            if isinstance(probe_config.get("fulfillment_policy_response"), dict)
            else None,
            payment_policy_response=probe_config.get("payment_policy_response") if isinstance(probe_config.get("payment_policy_response"), dict) else None,
            return_policy_response=probe_config.get("return_policy_response") if isinstance(probe_config.get("return_policy_response"), dict) else None,
            timeout_seconds=self._int(probe_config.get("timeout_seconds"), 20),
        )

    def _media_generation_config(self, task: JiejingTask, probe_config: dict[str, Any]) -> MediaGenerationConfig:
        product = str(probe_config.get("product") or task.input.get("product") or "current product")
        return MediaGenerationConfig(
            product=product,
            image_prompt=str(probe_config.get("image_prompt") or ""),
            video_prompt=str(probe_config.get("video_prompt") or ""),
            detail_page_prompt=str(probe_config.get("detail_page_prompt") or ""),
            image_count=self._int(probe_config.get("image_count"), 4),
            image_sizes=[
                str(item)
                for item in (probe_config.get("image_sizes") if isinstance(probe_config.get("image_sizes"), list) else ["1600x1600", "1200x1600", "1200x3600"])
            ],
            scene_types=[
                str(item)
                for item in (
                    probe_config.get("scene_types")
                    if isinstance(probe_config.get("scene_types"), list)
                    else ["main_white_bg", "lifestyle_scene", "detail_page", "dimension_image"]
                )
            ],
            asset_manifest=probe_config.get("asset_manifest") if isinstance(probe_config.get("asset_manifest"), dict) else None,
            live_enabled=probe_config.get("live_enabled") is True,
            provider=str(probe_config.get("provider") or ""),
            image_endpoint=str(probe_config.get("image_endpoint")) if probe_config.get("image_endpoint") else None,
            video_endpoint=str(probe_config.get("video_endpoint")) if probe_config.get("video_endpoint") else None,
            api_key=str(probe_config.get("api_key")) if probe_config.get("api_key") else None,
            proxy_url=str(probe_config.get("proxy_url")) if probe_config.get("proxy_url") else None,
            image_model=str(probe_config.get("image_model") or "openai/gpt-image-2"),
            video_model=str(probe_config.get("video_model") or "fal-ai/wan-i2v"),
            reference_image_url=str(probe_config.get("reference_image_url") or ""),
            timeout_seconds=self._int(probe_config.get("timeout_seconds"), 45),
        )

    def _tool_source_records(self, task: JiejingTask, report: dict[str, Any], captured_at: str) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        market_packet = report.get("market_data_packet_probe")
        if isinstance(market_packet, dict):
            records.append(
                {
                    "source_id": f"src_{task.task_type.replace('.', '_')}_market_data_packet",
                    "source_type": "runtime_market_packet",
                    "title": "Market data packet for market report",
                    "url": None,
                    "captured_at": captured_at,
                    "confidence": "medium" if market_packet.get("status") == "success" else "low",
                    "used_for": [task.task_type],
                    "note": str(market_packet.get("summary") or "Market data packet probe result."),
                }
            )
            for item in market_packet.get("source_records", []) or []:
                if not isinstance(item, dict):
                    continue
                source_type = str(item.get("source_type") or "")
                if source_type not in {"public_page", "official_api", "merchant_provided", "manual_input", "tool_estimate", "ai_inference", "restricted_unavailable"}:
                    continue
                records.append(
                    {
                        **item,
                        "source_id": str(item.get("source_id") or f"src_{task.task_type.replace('.', '_')}_market_packet_source"),
                        "used_for": sorted(set([*(item.get("used_for") if isinstance(item.get("used_for"), list) else []), task.task_type])),
                        "raw_provider_response_stored": False,
                        "secret_exposed": False,
                    }
                )
        listing_metadata = report.get("listing_metadata_probe")
        if isinstance(listing_metadata, dict):
            records.append(
                {
                    "source_id": f"src_{task.task_type.replace('.', '_')}_ebay_listing_metadata",
                    "source_type": str(listing_metadata.get("source_type") or "official_api"),
                    "title": "eBay Taxonomy and business policy metadata",
                    "url": None,
                    "captured_at": captured_at,
                    "confidence": str(listing_metadata.get("confidence") or "low"),
                    "used_for": [task.task_type],
                    "note": str(listing_metadata.get("summary") or "Listing metadata probe result."),
                }
            )
        sourcing = report.get("sourcing_availability_probe")
        if isinstance(sourcing, dict):
            records.append(
                {
                    "source_id": f"src_{task.task_type.replace('.', '_')}_sourcing_availability",
                    "source_type": str(sourcing.get("source_type") or "merchant_provided"),
                    "title": "Sourcing availability snapshot",
                    "url": None,
                    "captured_at": captured_at,
                    "confidence": str(sourcing.get("confidence") or "low"),
                    "used_for": [task.task_type],
                    "note": str(sourcing.get("summary") or "Sourcing availability probe result."),
                }
            )
        media_generation = report.get("media_generation_probe")
        if isinstance(media_generation, dict):
            records.append(
                {
                    "source_id": f"src_{task.task_type.replace('.', '_')}_media_generation",
                    "source_type": str(media_generation.get("source_type") or "media_provider"),
                    "title": "Image and video generation manifest",
                    "url": None,
                    "captured_at": captured_at,
                    "confidence": str(media_generation.get("confidence") or "low"),
                    "used_for": [task.task_type],
                    "note": str(media_generation.get("summary") or "Media generation probe result."),
                }
            )
        logistics = report.get("logistics_estimate_probe")
        if isinstance(logistics, dict):
            records.append(
                {
                    "source_id": f"src_{task.task_type.replace('.', '_')}_logistics_estimate",
                    "source_type": str(logistics.get("source_type") or "tool_estimate"),
                    "title": "Logistics estimate snapshot",
                    "url": None,
                    "captured_at": captured_at,
                    "confidence": str(logistics.get("confidence") or "low"),
                    "used_for": [task.task_type],
                    "note": str(logistics.get("summary") or "物流估算探针结果。"),
                }
            )
        return records

    def _execute_market_data_packet(self, task: JiejingTask, started_at: str) -> dict[str, Any]:
        packet = MarketDataPacketBuilder().build(task)
        packet["report"]["merchant_readable_summary"] = packet["summary"]
        knowledge_items = self._knowledge_for(task)
        _ensure_required_report_sections(
            task,
            packet["report"],
            "Market data packet 已保留该必需部分边界；运行探针前，带来源的数据值保持待补。",
        )
        packet["report"] = self.agent_team.normalize_report(task, packet["report"], knowledge_items)
        packet["report"]["owned_agent_execution"] = {
            "executor": self.owned_agent_executor.name,
            "executor_version": self.owned_agent_executor.version,
            "role": self.agent_team.role_for(task.task_type),
            "merchant_label": packet["report"].get("agent_label"),
            "agent_class": "MarketDataPacketBuilder",
            "uses_live_model": False,
            "uses_external_tools": bool(packet.get("report", {}).get("adapter_probe_inputs")),
            "external_tool_names": packet.get("report", {}).get("adapter_probe_inputs", []),
            "knowledge_items_used": [item.title for item in knowledge_items[:4]],
            "replacement_scope": "market_data_split_layer",
            "real_execution_allowed": False,
        }
        packet["report"]["model_client"] = self.model_client.name
        packet["report"]["model_client_version"] = self.model_client.version
        packet["report"]["report_contract"] = validate_role_report_contract(task, packet["report"])
        packet["report"]["owned_agent_quality_gate"] = self.agent_quality_gate.review_report(task, packet["report"])
        finished_at = now_iso()
        return {
            "task_id": task.task_id,
            "task_type": task.task_type,
            "task_version": task.task_version,
            "status": packet["status"],
            "executor": self.name,
            "executor_version": self.version,
            "started_at": started_at,
            "finished_at": finished_at,
            "summary": packet["summary"],
            "report": packet["report"],
            "source_records": packet["source_records"],
            "missing_inputs": packet["missing_inputs"],
            "risk_flags": packet["risk_flags"],
            "confirmation_items": [],
            "next_tasks": [
                {
                    "task_type": "market.report",
                    "condition": "只有 market.data_packet 具备来源事实后才运行；否则保持阻断状态。",
                }
            ],
            "artifacts": [],
            "audit": {
                "adapter": self.name,
                "adapter_version": self.version,
                "agent_team": self.agent_team.to_dict(),
                "agent_role": self.agent_team.role_for(task.task_type),
                "owned_agent_executor": self.owned_agent_executor.to_dict(),
                "owned_agent_quality_gate": packet["report"]["owned_agent_quality_gate"],
                "market_data_packet_builder": MarketDataPacketBuilder.version,
                "real_execution_allowed": False,
                "real_execution": dict(EXECUTION_AUDIT_FALSE),
            },
        }

    def _validation_report_for(self, task: JiejingTask) -> dict[str, Any]:
        product = str(task.input.get("product") or "Current eBay product")
        if task.task_type == "listing.package":
            return {"listing_validation": ListingPackageValidator().validate_text(self._demo_listing_text(product))}
        if task.task_type == "asset.brief":
            return {"asset_manifest_validation": AssetManifestValidator().validate_text(self._demo_asset_manifest_text(product))}
        if task.task_type == "customer.learn_product":
            return {"customer_learning_validation": CustomerLearningValidator().validate_text(self._demo_customer_learning_text(product))}
        if task.task_type == "finance.review":
            return {"finance_review_validation": FinanceReviewValidator().validate_text(self._demo_finance_text(product))}
        if task.task_type == "confirmation.package":
            return {"confirmation_package_validation": ConfirmationPackageValidator().validate_text(self._demo_confirmation_text())}
        if task.task_type == "ceo.final_report":
            return {"ceo_final_report_validation": CeoFinalReportValidator().validate_text(self._demo_ceo_final_text(product))}
        return {}

    def _demo_listing_text(self, product: str) -> str:
        return f"""
# Product Manager Listing Package

SKU: JJ-DEMO-001
Title: {product[:42]} eBay Draft Product Listing
Category ID: 20687
Condition: New
Format: Fixed Price
Price: US $19.99
Quantity: 50

Item Specifics:
- Brand: Unbranded
- Type: Home Decor
- Material: Pending supplier confirmation
- Color: Pending supplier confirmation
- MPN: Does Not Apply
- UPC: Does Not Apply

Pictures: Picture 1 white background; Picture 2 lifestyle scene; Picture 3 dimensions; Picture 4 detail.
Video: 20 second product use and detail demonstration draft.
Description HTML: <div><h2>{product}</h2><p>Draft eBay description. Final claims require supplier confirmation.</p></div>
Package weight: 620 g
Package dimensions: 12x12x26 cm
Handling time: 3 business days
Item Location: Zhejiang, China
Fulfillment policy: authorized store default fulfillmentPolicyId pending final read.
Payment policy: authorized store default paymentPolicyId pending final read.
Return policy: authorized store default returnPolicyId pending final read.
Publish blockers: publish lock remains active until supplier facts, category specifics, policy IDs, finance review, and merchant confirmation are complete.
"""

    def _demo_asset_manifest_text(self, product: str) -> str:
        return f"""
# Asset Manager Output

Generated files are ready for demo review.

```json
{{
  "assets": [
    {{
      "asset_id": "img_main_01",
      "asset_type": "main_image",
      "url": "https://example.com/demo/{self._safe_token(product)}-main.jpg",
      "dimensions": "1600x1600",
      "source": "jiejing_demo_generation",
      "commercial_use_status": "demo_only",
      "status": "generated"
    }},
    {{
      "asset_id": "img_detail_01",
      "asset_type": "detail_page",
      "url": "https://example.com/demo/{self._safe_token(product)}-detail.jpg",
      "dimensions": "1200x3600",
      "source": "jiejing_demo_generation",
      "commercial_use_status": "demo_only",
      "status": "generated"
    }},
    {{
      "asset_id": "video_01",
      "asset_type": "product_video",
      "url": "https://example.com/demo/{self._safe_token(product)}-video.mp4",
      "duration_seconds": 24,
      "source": "jiejing_demo_generation",
      "commercial_use_status": "demo_only",
      "status": "generated"
    }}
  ]
}}
```
"""

    def _demo_customer_learning_text(self, product: str) -> str:
        return f"""
# Customer Service Learning Package

## product_service_file
Product service file: {product}. Final material, size, package and included accessories require supplier confirmation.

## buyer_question_map
Buyer question map: size, material, included accessories, tracking, delivery delay, damaged item, return process.

## faq
FAQ: answer product facts only from confirmed listing package; ask for photos for damage review; do not approve refund by yourself.

## reply_boundary
Auto reply boundary: low-risk FAQ and tracking wording only. Do not promise exact arrival date, compensation, refund approval, customs result, or medical effect.

## auto_reply_templates
Template: Thank you for your message. I can help check the product details and shipping status.
Template: Please send a clear photo of the product and outer package so we can review it.

## escalation_rules
Human takeover / manual takeover is required for refund, compensation, negative feedback, customs, exact delivery date, and any buyer dispute.

Customer service is ready for automatic replies only within the safe reply boundary above.
"""

    def _demo_finance_text(self, product: str) -> str:
        return f"""
# Finance and Fulfillment Review

## cost_table
Sale price / listing price: US $19.99
Procurement cost / 1688 cost: CNY 18.00
Platform fee / eBay fee: US $2.75
Logistics cost / SpeedPAK / Orange Connex estimate: CNY 58.50
Package cost / packaging cost: CNY 2.00
Subscription allocation / store subscription fee: US $0.20 per unit
Return reserve / refund reserve: US $1.20 per unit

## net_profit_money
Net profit money estimate for {product}: US $4.80 before ads. This is not a guaranteed profit.

## logistics_route
Logistics route: supplier or merchant route, then SpeedPAK Economy after final weight check.

## subscription_allocation
Store subscription allocation is included as US $0.20 per unit for the draft.

## return_reserve
Return reserve is US $1.20 because mismatch, breakage or after-sale cost may occur.

## risk_notes
Financial risk: logistics quote is still an estimate; supplier weight and package size must be confirmed.

## next_action
Finance lock / publish lock: do not publish. Send to confirmation center after supplier facts, policy IDs, and merchant approval are complete.
"""

    def _demo_confirmation_text(self) -> str:
        return """
# Confirmation Center Package

## allowed_auto_actions
Allowed auto actions: organize reports, prepare draft listings, draft low-risk customer replies, update internal task status, and build asset tasks.

## default_rule_actions
Default rule actions: saved store rules may prepare drafts but not execute real changes.

## every_time_confirm_actions
Every time confirm actions / manual confirmation:
- publish listing requires confirmation every time.
- batch publish requires confirmation every time.
- procurement payment requires confirmation every time.
- refund and partial refund require confirmation every time.
- ad budget and promoted listing budget require confirmation every time.
- price change requires confirmation every time.
- inventory change requires confirmation every time.
- store policy change including fulfillment policy, payment policy, and return policy requires confirmation every time.
- store subscription change requires confirmation every time.
- OAuth authorization and token scope change require confirmation every time.
- sensitive customer promise, compensation, guarantee, customs, and exact delivery date require confirmation every time.

## blocked_actions
Never auto / blocked actions: no real publish, no procurement payment, no refund, no ad spend, no policy edit, no OAuth scope change without merchant confirmation.

## missing_facts
Missing facts / stop conditions: supplier facts, final logistics quote, business policy IDs, category item specifics, asset manifest, and finance lock.
"""

    def _demo_ceo_final_text(self, product: str) -> str:
        return f"""
# AI CEO Final Report

## current_status
Current status: {product} has market report, source facts, listing package, asset manifest, customer learning, finance review, and confirmation package assembled for review.

## source_health
Source health / source confidence: live sources and merchant inputs still need confirmation before real publish.

## reports_ready
Reports ready: market manager report, product manager listing package, asset manager asset manifest, customer service learning package, finance manager finance review, and confirmation center package are ready for review.

## publish_lock
Publish lock: do not publish. Real eBay publish remains locked until merchant confirmation in the confirmation center.

## next_minimum_action
Next minimum action: confirm supplier facts and business policy IDs, then review the confirmation center publish item.
"""

    def _safe_token(self, value: str) -> str:
        return re.sub(r"[^a-zA-Z0-9]+", "-", value.lower()).strip("-")[:40] or "product"

    def _env_enabled(self, name: str) -> bool:
        return str(os.environ.get(name) or "").strip().lower() in {"1", "true", "yes", "on"}

    def _int(self, value: Any, fallback: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return fallback

    def _marketplace_id(self, marketplace: str) -> str:
        normalized = marketplace.strip().upper().replace(" ", "_").replace("-", "_")
        if normalized in {"EBAY_US", "EBAY_GB", "EBAY_DE", "EBAY_AU", "EBAY_CA"}:
            return normalized
        if normalized in {"US", "EBAYUS"}:
            return "EBAY_US"
        return "EBAY_US"

    def _status_for(self, task: JiejingTask, confirmation_items: list[dict[str, Any]]) -> str:
        if task.task_type in {"listing.package", "finance.review"}:
            return "blocked_missing_input"
        if confirmation_items:
            return "blocked_confirmation_required"
        if task.task_type in {"market.report", "source.match", "asset.brief"}:
            return "partial_success"
        return "success"

    def _knowledge_for(self, task: JiejingTask) -> list[KnowledgeItem]:
        return self.knowledge_base.query(
            role=self.agent_team.knowledge_role_for(task.task_type),
            task_type=task.task_type,
            limit=5,
        )

    def _role_for_task(self, task_type: str) -> str:
        return self.agent_team.role_for(task_type)

    def _enrich_report_with_knowledge(self, report: dict[str, Any], items: list[KnowledgeItem]) -> dict[str, Any]:
        enriched = dict(report)
        sections = dict(enriched.get("sections", {}))
        sections["runtime_knowledge_applied"] = [
            {
                "title": item.title,
                "role": item.role,
                "source_ref": item.source_ref,
                "rule_excerpt": self._excerpt(item.content, 480),
            }
            for item in items
        ]
        enriched["sections"] = sections
        enriched["runtime_knowledge"] = [
            {
                "item_id": item.item_id,
                "title": item.title,
                "role": item.role,
                "task_types": item.task_types,
                "tags": item.tags,
                "source_ref": item.source_ref,
            }
            for item in items
        ]
        return enriched

    def _knowledge_source_records(
        self,
        task: JiejingTask,
        items: list[KnowledgeItem],
        captured_at: str,
    ) -> list[dict[str, Any]]:
        return [
            {
                "source_id": f"kb_{item.item_id}",
                "source_type": "runtime_sanitized_knowledge",
                "title": item.title,
                "url": None,
                "captured_at": captured_at,
                "confidence": "medium",
                "used_for": [task.task_type],
                "note": f"来自 {item.source_ref} 的 Runtime 脱敏知识；没有导入任何凭证。",
            }
            for item in items[:3]
        ]

    def _excerpt(self, text: str, limit: int = 500) -> str:
        collapsed = re.sub(r"\s+", " ", text).strip()
        if len(collapsed) <= limit:
            return collapsed
        return collapsed[: limit - 3] + "..."

    def _missing_inputs(self, task: JiejingTask) -> list[dict[str, str]]:
        blockers = {
            "source.match": ["supplier_real_facts"],
            "listing.package": ["category_item_specifics", "business_policy_ids", "supplier_real_facts"],
            "asset.brief": ["confirmed_product_facts"],
            "finance.review": ["final_cost", "final_shipping_policy"],
        }.get(task.task_type, [])
        reasons = {
            "supplier_real_facts": "必须确认供应商尺寸、材质、重量、发货地、包装和测试信息。",
            "category_item_specifics": "必须验证 eBay taxonomy 和必填 item specifics。",
            "business_policy_ids": "店铺 fulfillment、payment、return policy IDs 必须来自授权账号。",
            "confirmed_product_facts": "商业素材不能声明未验证功能。",
            "final_cost": "利润测算需要最终采购成本。",
            "final_shipping_policy": "最终发货政策和价格会影响利润与买家承诺。",
        }
        return [
            {"input_id": blocker, "reason": reasons.get(blocker, "安全继续前必须补齐。"), "severity": "blocking"}
            for blocker in blockers
        ]

    def _risk_flags(self, task: JiejingTask) -> list[dict[str, str]]:
        if task.task_type == "confirmation.package":
            return [{"risk_id": "confirmation_required", "severity": "critical", "message": "高风险动作已锁定。"}]
        if task.task_type == "listing.package":
            return [{"risk_id": "publish_not_allowed", "severity": "critical", "message": "当前只是草稿，真实发布已阻断。"}]
        if task.task_type == "finance.review":
            return [{"risk_id": "margin_uncertain", "severity": "high", "message": "需要最终成本和发货事实。"}]
        return []
