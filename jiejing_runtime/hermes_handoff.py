"""Import Hermes handoff outputs back into JiejingTaskResult."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .asset_manifest import AssetManifestValidator
from .ceo_final_report import CeoFinalReportValidator
from .confirmation_package import ConfirmationPackageValidator
from .customer_learning import CustomerLearningValidator
from .finance_review import FinanceReviewValidator
from .listing_package import ListingPackageValidator
from .models import JiejingTask, now_iso
from .policies import ConfirmationCenter


class HermesHandoffResultImporter:
    """Converts a Hermes/team_bus markdown output into Runtime result format."""

    def __init__(self, confirmation_center: ConfirmationCenter | None = None) -> None:
        self.confirmation_center = confirmation_center or ConfirmationCenter()

    def import_markdown(self, packet_json: Path, role_output_md: Path) -> dict[str, Any]:
        packet = json.loads(packet_json.read_text(encoding="utf-8"))
        task = JiejingTask(packet["task"])
        text = role_output_md.read_text(encoding="utf-8", errors="replace")
        now = now_iso()
        sections = self._parse_sections(text)
        confirmation_items = self.confirmation_center.build_for_task(task)
        missing_inputs = self._infer_missing_inputs(text)
        missing_inputs.extend(self._infer_section_gaps(task, sections, text))
        listing_validation = None
        if task.task_type == "listing.package":
            listing_validator = ListingPackageValidator()
            listing_validation = listing_validator.validate_text(text)
            missing_inputs.extend(listing_validator.missing_inputs_from_validation(listing_validation))
        asset_manifest_validation = None
        if task.task_type == "asset.brief":
            asset_validator = AssetManifestValidator()
            asset_manifest_validation = asset_validator.validate_text(text)
            missing_inputs.extend(asset_validator.missing_inputs_from_validation(asset_manifest_validation))
        customer_learning_validation = None
        if task.task_type == "customer.learn_product":
            customer_validator = CustomerLearningValidator()
            customer_learning_validation = customer_validator.validate_text(text)
            missing_inputs.extend(customer_validator.missing_inputs_from_validation(customer_learning_validation))
        finance_review_validation = None
        if task.task_type == "finance.review":
            finance_validator = FinanceReviewValidator()
            finance_review_validation = finance_validator.validate_text(text)
            missing_inputs.extend(finance_validator.missing_inputs_from_validation(finance_review_validation))
        confirmation_package_validation = None
        if task.task_type == "confirmation.package":
            confirmation_validator = ConfirmationPackageValidator()
            confirmation_package_validation = confirmation_validator.validate_text(text)
            missing_inputs.extend(confirmation_validator.missing_inputs_from_validation(confirmation_package_validation))
        ceo_final_report_validation = None
        if task.task_type == "ceo.final_report":
            ceo_validator = CeoFinalReportValidator()
            ceo_final_report_validation = ceo_validator.validate_text(text)
            missing_inputs.extend(ceo_validator.missing_inputs_from_validation(ceo_final_report_validation))
        missing_inputs = self._dedupe_inputs(missing_inputs)
        risk_flags = self._infer_risks(text)
        if not self._has_usable_output(text):
            risk_flags.append(
                {
                    "risk_id": "empty_role_output",
                    "severity": "critical",
                    "message": "Hermes returned an empty or unusable role output.",
                }
            )
        status = self._infer_status(task, text, missing_inputs, confirmation_items)
        return {
            "task_id": task.task_id,
            "task_type": task.task_type,
            "task_version": task.task_version,
            "status": status,
            "executor": "hermes-handoff-importer",
            "executor_version": "0.1.0",
            "started_at": now,
            "finished_at": now,
            "summary": self._summary(text, task),
            "report": {
                "mode": "hermes_handoff_import",
                "target_role": packet.get("target_role"),
                "required_sections": task.output_contract.get("required_sections", []),
                "returned_sections": sorted(sections),
                "section_gaps": [item for item in missing_inputs if item.get("input_id", "").startswith("report_section_")],
                "listing_validation": listing_validation,
                "asset_manifest_validation": asset_manifest_validation,
                "customer_learning_validation": customer_learning_validation,
                "finance_review_validation": finance_review_validation,
                "confirmation_package_validation": confirmation_package_validation,
                "ceo_final_report_validation": ceo_final_report_validation,
                "sections": sections,
                "raw_excerpt": self._excerpt(text, 1400),
            },
            "source_records": [
                {
                    "source_id": f"src_hermes_handoff_{self._safe_id(task.task_type)}",
                    "source_type": "hermes_handoff_output",
                    "title": role_output_md.name,
                    "url": None,
                    "captured_at": now,
                    "confidence": "medium",
                    "used_for": [task.task_type],
                    "note": "Imported from a Hermes/team_bus handoff output. Runtime still validates confirmation boundaries.",
                }
            ],
            "missing_inputs": missing_inputs,
            "risk_flags": risk_flags,
            "confirmation_items": confirmation_items,
            "next_tasks": [],
            "artifacts": [
                {
                    "artifact_type": "hermes_role_markdown",
                    "path": str(role_output_md),
                    "exists": role_output_md.exists(),
                    "synthetic": False,
                }
            ],
            "audit": {
                "adapter": "hermes-handoff-importer",
                "packet_json": str(packet_json),
                "role_output_md": str(role_output_md),
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

    def _parse_sections(self, text: str) -> dict[str, str]:
        sections: dict[str, str] = {}
        current = "body"
        buffer: list[str] = []
        for line in text.splitlines():
            heading = re.match(r"^\s{0,3}#{1,4}\s+(.+?)\s*$", line)
            if heading:
                if buffer:
                    sections[self._safe_key(current)] = "\n".join(buffer).strip()
                current = heading.group(1).strip()
                buffer = []
            else:
                buffer.append(line)
        if buffer:
            sections[self._safe_key(current)] = "\n".join(buffer).strip()
        return {key: value for key, value in sections.items() if value}

    def _infer_missing_inputs(self, text: str) -> list[dict[str, str]]:
        missing = []
        patterns = [
            ("live_market_data", r"(?i)(actual|exact|live|official|verified).{0,60}(eBay|listing|seller|pricing|review|data).{0,60}(needed|need|required|missing|unavailable|pending)"),
            ("supplier_real_facts", r"(?i)(supplier|1688|source).{0,40}(pending|missing|unknown|need|confirm)"),
            ("business_policy_ids", r"(?i)(fulfillment|payment|return).{0,40}(policy|policies).{0,40}(pending|missing|confirm)"),
            ("taxonomy_item_specifics", r"(?i)(taxonomy|category|item specific).{0,40}(pending|missing|confirm|check)"),
            ("logistics_quote", r"(?i)(logistics|shipping|SpeedPAK|Orange Connex).{0,40}(pending|estimate|quote|confirm)"),
            ("source_confidence_upgrade", r"(?i)(AI-inferred|preliminary estimate|not official|general knowledge|without live data)"),
        ]
        for input_id, pattern in patterns:
            if re.search(pattern, text):
                missing.append(
                    {
                        "input_id": input_id,
                        "reason": "Imported Hermes output indicates this fact is pending or needs confirmation.",
                        "severity": "blocking",
                    }
                )
        return missing

    def _infer_section_gaps(self, task: JiejingTask, sections: dict[str, str], text: str) -> list[dict[str, str]]:
        required = task.output_contract.get("required_sections", [])
        if not isinstance(required, list) or not required:
            return []
        if not self._has_usable_output(text):
            return [
                {
                    "input_id": "role_output_empty",
                    "reason": "Hermes output is empty, so required report sections cannot be validated.",
                    "severity": "blocking",
                }
            ]
        normalized_sections = set(sections)
        gaps: list[dict[str, str]] = []
        for section in required:
            section_key = self._safe_key(str(section))
            if self._section_is_present(section_key, normalized_sections, text):
                continue
            gaps.append(
                {
                    "input_id": f"report_section_{section_key}",
                    "reason": f"Required report section was not found in Hermes output: {section_key}.",
                    "severity": "blocking",
                }
            )
        return gaps

    def _section_is_present(self, section_key: str, normalized_sections: set[str], text: str) -> bool:
        if section_key in normalized_sections:
            return True
        aliases = {
            "ebay_price_bands": ["ebay_price_band_hypothesis", "price_bands", "pricing"],
            "pricing_direction": ["pricing_direction", "ebay_price_band_hypothesis", "price_bands", "pricing"],
            "conclusion_next_step": ["conclusion_and_next_step", "conclusion", "next_step"],
        }
        if any(alias in normalized_sections for alias in aliases.get(section_key, [])):
            return True
        if section_key == "competitor_top5":
            return bool(re.search(r"(?i)(top\s*5|top five|5\s+competitor|five competitor)", text))
        return False

    def _dedupe_inputs(self, missing_inputs: list[dict[str, str]]) -> list[dict[str, str]]:
        seen: set[str] = set()
        deduped: list[dict[str, str]] = []
        for item in missing_inputs:
            input_id = str(item.get("input_id", ""))
            if input_id in seen:
                continue
            seen.add(input_id)
            deduped.append(item)
        return deduped

    def _infer_risks(self, text: str) -> list[dict[str, str]]:
        risks = []
        if re.search(r"(?i)(publish|listing).{0,30}(block|lock|not ready|cannot)", text):
            risks.append({"risk_id": "publish_lock", "severity": "critical", "message": "Imported output keeps publish lock active."})
        if re.search(r"(?i)(refund|compensation|negative feedback|dispute)", text):
            risks.append({"risk_id": "customer_service_escalation", "severity": "high", "message": "Sensitive buyer-service topic detected."})
        if re.search(r"(?i)(estimate|inference|not official|unavailable)", text):
            risks.append({"risk_id": "source_confidence", "severity": "medium", "message": "Some data is estimate or inference."})
        return risks

    def _infer_status(
        self,
        task: JiejingTask,
        text: str,
        missing_inputs: list[dict[str, str]],
        confirmation_items: list[dict[str, Any]],
    ) -> str:
        if not self._has_usable_output(text):
            return "failed_tool"
        if re.search(r"(?i)\b(timeout|timed out)\b", text):
            return "failed_timeout"
        if re.search(r"(?i)\b(failed|empty output)\b", text):
            return "failed_tool"
        if missing_inputs:
            return "blocked_missing_input"
        if confirmation_items:
            return "blocked_confirmation_required"
        if re.search(r"(?i)(pending|draft only|not publish-ready|preliminary|AI-inferred|not official|estimate only)", text):
            return "partial_success"
        return "success"

    def _summary(self, text: str, task: JiejingTask) -> str:
        for line in text.splitlines():
            clean = line.strip(" #-\t")
            if len(clean) >= 20:
                return clean[:240]
        return f"Imported Hermes handoff output for {task.task_type}."

    def _excerpt(self, text: str, limit: int) -> str:
        collapsed = re.sub(r"\s+", " ", text).strip()
        if len(collapsed) <= limit:
            return collapsed
        return collapsed[: limit - 3] + "..."

    def _has_usable_output(self, text: str) -> bool:
        return len(re.sub(r"\s+", "", text)) >= 40

    def _safe_key(self, value: str) -> str:
        return re.sub(r"[^a-zA-Z0-9_]+", "_", value.strip().lower()).strip("_") or "section"

    def _safe_id(self, value: str) -> str:
        return re.sub(r"[^a-zA-Z0-9_]+", "_", value)
