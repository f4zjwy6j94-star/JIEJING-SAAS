"""Jiejing Agent Runtime MVP orchestration."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .adapters import AgentAdapter, HermesAdapterPlanOnly, HermesFileHandoffAdapter, HermesShadowAdapter, JiejingAgentAdapter, MockAgentAdapter
from .contracts import ResultContractValidator
from .model_clients import DeepSeekModelClient, model_client_from_env
from .models import JiejingTask, RuntimeAuditEvent, RuntimeIssue, validate_task_core
from .policies import SafetyGate
from .store import FileRunStore
from .task_queue import TaskQueue


@dataclass(slots=True)
class RuntimeConfig:
    adapter_name: str = "mock"
    demo_mode: bool = True
    stop_on_failure: bool = False
    clean_output: bool = True


@dataclass(slots=True)
class RuntimeRunSummary:
    run_dir: Path
    run_json: Path
    summary_md: Path
    task_count: int
    run_status: str
    issues: list[RuntimeIssue] = field(default_factory=list)


class JiejingRuntime:
    """Runs a list of standard JiejingTask objects through an adapter."""

    def __init__(
        self,
        config: RuntimeConfig | None = None,
        adapter: AgentAdapter | None = None,
        safety_gate: SafetyGate | None = None,
    ) -> None:
        self.config = config or RuntimeConfig()
        self.adapter = adapter or self._adapter_from_name(self.config.adapter_name)
        self.safety_gate = safety_gate or SafetyGate(demo_mode=self.config.demo_mode)
        self.result_contracts = ResultContractValidator()

    def run_task_files(self, task_files: list[Path], run_dir: Path, run_id: str | None = None) -> RuntimeRunSummary:
        tasks = [json.loads(path.read_text(encoding="utf-8")) for path in task_files]
        return self.run_tasks(tasks, run_dir, run_id=run_id)

    def run_tasks(self, raw_tasks: list[dict[str, Any]], run_dir: Path, run_id: str | None = None) -> RuntimeRunSummary:
        run_id = run_id or self._default_run_id(raw_tasks)
        store = FileRunStore(run_dir)
        store.prepare(clean=self.config.clean_output)
        store.append_audit(
            RuntimeAuditEvent("run_started", None, f"Run {run_id} started.", details={"adapter": self.adapter.name})
        )

        issues: list[RuntimeIssue] = []
        results: list[dict[str, Any]] = []
        queue = TaskQueue.from_raw_tasks(raw_tasks)
        dependency_issues = queue.validate_dependencies()
        issues.extend(dependency_issues)
        if dependency_issues:
            store.append_audit(
                RuntimeAuditEvent(
                    "queue_dependency_check",
                    None,
                    "Task queue dependency check produced issues.",
                    details={"issues": [issue.to_dict() for issue in dependency_issues]},
                )
            )

        while queue.has_next():
            item = queue.next()
            order = item.order
            task = item.task
            store.write_task_snapshot(order, task.raw)
            task_issues = validate_task_core(task)
            task_issues.extend(self.safety_gate.validate_task_policy(task))
            if task_issues:
                issues.extend(task_issues)
                result = self._failed_policy_result(task, task_issues)
                results.append(result)
                store.write_result(order, result)
                queue.complete(item, str(result.get("status", "failed_policy")))
                store.append_audit(
                    RuntimeAuditEvent(
                        "task_failed_policy",
                        task.task_id,
                        "Task failed runtime policy validation.",
                        details={"issues": [issue.to_dict() for issue in task_issues]},
                    )
                )
                if self.config.stop_on_failure:
                    break
                continue

            store.append_audit(RuntimeAuditEvent("task_started", task.task_id, f"Task {task.task_type} started."))
            result = self.adapter.execute(task)
            result_issues = self.safety_gate.validate_result(result)
            result_issues.extend(self.result_contracts.validate(task, result))
            if result_issues:
                issues.extend(result_issues)
                if any(issue.severity == "error" for issue in result_issues):
                    result["status"] = "failed_policy"
                result.setdefault("audit", {})["runtime_policy_issues"] = [issue.to_dict() for issue in result_issues]
            results.append(result)
            store.write_result(order, result)
            queue.complete(item, str(result.get("status", "unknown")))
            store.append_audit(
                RuntimeAuditEvent(
                    "task_finished",
                    task.task_id,
                    f"Task {task.task_type} finished with {result.get('status')}.",
                    details={"confirmation_items": len(result.get("confirmation_items", []))},
                )
            )
            if self.config.stop_on_failure and str(result.get("status", "")).startswith("failed"):
                break

        summary = store.build_summary(run_id, self.adapter.name, results)
        summary["queue"] = queue.snapshot()
        if issues and summary["run_status"] == "success":
            summary["run_status"] = "completed_with_policy_warnings"
        summary["issues"] = [issue.to_dict() for issue in issues]
        run_json = store.write_run_summary(summary)
        summary_md = store.write_markdown_summary(summary, results)
        store.append_audit(RuntimeAuditEvent("run_finished", None, f"Run {run_id} finished.", details=summary))
        return RuntimeRunSummary(
            run_dir=run_dir,
            run_json=run_json,
            summary_md=summary_md,
            task_count=len(results),
            run_status=summary["run_status"],
            issues=issues,
        )

    def _adapter_from_name(self, name: str) -> AgentAdapter:
        if name == "mock":
            return MockAgentAdapter()
        if name == "jiejing-local":
            return JiejingAgentAdapter()
        if name == "jiejing-llm":
            return JiejingAgentAdapter(model_client=model_client_from_env())
        if name == "jiejing-deepseek":
            return JiejingAgentAdapter(model_client=DeepSeekModelClient())
        if name == "hermes-plan":
            return HermesAdapterPlanOnly()
        if name == "hermes-shadow":
            return HermesShadowAdapter()
        if name == "hermes-file":
            return HermesFileHandoffAdapter()
        raise ValueError(f"Unknown adapter: {name}")

    def _default_run_id(self, raw_tasks: list[dict[str, Any]]) -> str:
        if not raw_tasks:
            return "empty-run"
        first = raw_tasks[0]
        return str(first.get("project_id") or first.get("context", {}).get("sample_id") or "jiejing-runtime-run")

    def _failed_policy_result(self, task: JiejingTask, issues: list[RuntimeIssue]) -> dict[str, Any]:
        return {
            "task_id": task.task_id or "invalid_task",
            "task_type": task.task_type or "unknown",
            "task_version": task.task_version or "unknown",
            "status": "failed_policy",
            "executor": "jiejing-runtime",
            "executor_version": "0.1.0",
            "summary": "Task did not pass runtime policy validation.",
            "report": {"issues": [issue.to_dict() for issue in issues]},
            "source_records": [
                {
                    "source_id": "src_runtime_validation",
                    "source_type": "ai_inference",
                    "title": "Runtime validation",
                    "url": None,
                    "captured_at": "",
                    "confidence": "high",
                    "used_for": [task.task_type or "unknown"],
                    "note": "Generated by runtime validation before adapter execution.",
                }
            ],
            "missing_inputs": [],
            "risk_flags": [{"risk_id": issue.code, "severity": issue.severity, "message": issue.message} for issue in issues],
            "confirmation_items": [],
            "next_tasks": [],
            "artifacts": [],
            "audit": {"runtime_policy_issues": [issue.to_dict() for issue in issues], "real_execution_allowed": False},
        }
