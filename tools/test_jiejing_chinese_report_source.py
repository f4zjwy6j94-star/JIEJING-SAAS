#!/usr/bin/env python3
"""Regression for merchant-visible Chinese Market Report and Listing Package sources."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_runtime.adapters import JiejingAgentAdapter  # noqa: E402
from jiejing_runtime.model_clients import ModelClient  # noqa: E402
from jiejing_runtime.models import JiejingTask  # noqa: E402
from jiejing_runtime.workflow_templates import ProductWorkflowRequest, build_product_workflow  # noqa: E402


FORBIDDEN_PHRASES = (
    "Market Manager prepared",
    "Product Manager drafted an eBay-shaped listing package",
    "Pending supplier quote",
    "Real eBay publish requires confirmation",
    "No real eBay publish",
    "source-backed data before real execution",
)


class EnglishHeavyLiveModel(ModelClient):
    name = "english-heavy-live-model"
    version = "unit"

    def generate_report(self, task: JiejingTask) -> dict[str, Any]:
        sections = {
            str(section): "Product Manager drafted an eBay-shaped listing package and real publish remains blocked until validation and confirmation."
            for section in task.output_contract.get("required_sections", [])
        }
        return {
            "model_mode": "live_http_model",
            "model_configured": True,
            "merchant_readable_summary": "Market Manager prepared a structured eBay opportunity report; live data is still required before production decisions.",
            "sections": sections,
        }


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    tasks = _tasks()
    owned_adapter = JiejingAgentAdapter()
    for task in tasks:
        result = owned_adapter.execute(task)
        if _assert_chinese_visible_result(result):
            return _assert_chinese_visible_result(result)

    live_adapter = JiejingAgentAdapter(model_client=EnglishHeavyLiveModel())
    for task in tasks:
        result = live_adapter.execute(task)
        if _assert_chinese_visible_result(result):
            return _assert_chinese_visible_result(result)
        report = result.get("report") if isinstance(result.get("report"), dict) else {}
        model_assist = report.get("model_assist") if isinstance(report.get("model_assist"), dict) else {}
        rejected = model_assist.get("english_heavy_fields_rejected") or []
        if not rejected:
            return fail("English-heavy live model fields should be rejected before report persistence")
        quality = report.get("merchant_language_quality") if isinstance(report.get("merchant_language_quality"), dict) else {}
        if quality.get("checked_before_persist") is not True or quality.get("merchant_visible_language") != "zh-CN":
            return fail(f"report should record Chinese language quality gate: {quality}")

    print("PASS jiejing_chinese_report_source")
    return 0


def _tasks() -> list[JiejingTask]:
    request = ProductWorkflowRequest(
        product="Adhesive Cable Organizer",
        merchant_goal="生成商家可读的中文 Market Report 和 Listing Package。",
        project_id="zh-report-source-unit",
        stage="store_opened",
        platform="ebay",
        user_id="unit-user",
        company_id="unit-company",
        store_id="unit-store",
        marketplace="EBAY_US",
        source_mode="official_api",
        notes="商家可见报告必须中文；缺口写待补资料。",
    )
    selected = []
    for raw in build_product_workflow(request):
        if raw.get("task_type") in {"market.report", "listing.package"}:
            selected.append(JiejingTask(raw))
    return selected


def _assert_chinese_visible_result(result: dict[str, Any]) -> int:
    report = result.get("report") if isinstance(result.get("report"), dict) else {}
    visible = {
        "summary": result.get("summary"),
        "merchant_readable_summary": report.get("merchant_readable_summary"),
        "sections": report.get("sections"),
        "limits": report.get("limits"),
        "risk_flags": result.get("risk_flags"),
        "missing_inputs": result.get("missing_inputs"),
    }
    serialized = json.dumps(visible, ensure_ascii=False)
    if not _contains_cjk(serialized):
        return fail(f"merchant-visible report should contain Chinese text for {result.get('task_type')}")
    for phrase in FORBIDDEN_PHRASES:
        if phrase in serialized:
            return fail(f"merchant-visible report leaked old English phrase `{phrase}` for {result.get('task_type')}")
    summary = str(result.get("summary") or "")
    if not _contains_cjk(summary):
        return fail(f"summary should be Chinese for {result.get('task_type')}: {summary}")
    for item in result.get("risk_flags") or []:
        message = str(item.get("message") or "") if isinstance(item, dict) else str(item)
        if message and not _contains_cjk(message):
            return fail(f"risk flag should be Chinese for {result.get('task_type')}: {message}")
    for item in result.get("missing_inputs") or []:
        reason = str(item.get("reason") or "") if isinstance(item, dict) else str(item)
        if reason and not _contains_cjk(reason):
            return fail(f"missing input reason should be Chinese for {result.get('task_type')}: {reason}")
    return 0


def _contains_cjk(value: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in value)


if __name__ == "__main__":
    raise SystemExit(main())
