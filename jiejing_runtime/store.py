"""File-backed run store for Jiejing Agent Runtime MVP."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import RuntimeAuditEvent, now_iso


class FileRunStore:
    def __init__(self, run_dir: Path) -> None:
        self.run_dir = run_dir
        self.tasks_dir = run_dir / "tasks"
        self.results_dir = run_dir / "results"
        self.audit_path = run_dir / "audit-log.jsonl"

    def prepare(self, clean: bool = True) -> None:
        self.tasks_dir.mkdir(parents=True, exist_ok=True)
        self.results_dir.mkdir(parents=True, exist_ok=True)
        if clean:
            for old_path in list(self.tasks_dir.glob("*.json")) + list(self.results_dir.glob("*.json")):
                old_path.unlink()
            if self.audit_path.exists():
                self.audit_path.unlink()

    def write_task_snapshot(self, order: int, task: dict[str, Any]) -> Path:
        path = self.tasks_dir / f"{order:02d}_{self._safe_name(task.get('task_type', 'task'))}.json"
        path.write_text(json.dumps(task, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def write_result(self, order: int, result: dict[str, Any]) -> Path:
        path = self.results_dir / f"{order:02d}_{self._safe_name(result.get('task_type', 'result'))}.json"
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def append_audit(self, event: RuntimeAuditEvent) -> None:
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        with self.audit_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")

    def write_run_summary(self, summary: dict[str, Any]) -> Path:
        path = self.run_dir / "run.json"
        path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def write_markdown_summary(self, summary: dict[str, Any], results: list[dict[str, Any]]) -> Path:
        lines = [
            f"# Jiejing Runtime Run - {summary['run_id']}",
            "",
            f"- Adapter: `{summary['adapter']}`",
            f"- Task count: `{summary['task_count']}`",
            f"- Run status: `{summary['run_status']}`",
            f"- Confirmation items: `{summary['confirmation_item_count']}`",
            f"- Missing inputs: `{summary['missing_input_count']}`",
            "",
            "## Results",
            "",
        ]
        for index, result in enumerate(results, start=1):
            lines.append(f"{index}. `{result['task_type']}` -> `{result['status']}`")
            lines.append(f"   {result['summary']}")
        path = self.run_dir / "summary.md"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    def build_summary(self, run_id: str, adapter: str, results: list[dict[str, Any]]) -> dict[str, Any]:
        status_counts: dict[str, int] = {}
        confirmation_count = 0
        missing_input_count = 0
        for result in results:
            status = str(result.get("status", "unknown"))
            status_counts[status] = status_counts.get(status, 0) + 1
            confirmation_count += len(result.get("confirmation_items", []))
            missing_input_count += len(result.get("missing_inputs", []))

        statuses = [str(result.get("status", "unknown")) for result in results]
        run_status = "success"
        if any(status.startswith("failed") for status in statuses):
            run_status = "partial_failure"
        elif statuses and all(status == "blocked_permission" for status in statuses):
            run_status = "adapter_plan_only"
        elif any(status.startswith("blocked") for status in statuses):
            run_status = "completed_with_blocks"
        elif any(status == "partial_success" for status in statuses):
            run_status = "completed_with_warnings"

        return {
            "run_id": run_id,
            "adapter": adapter,
            "run_status": run_status,
            "task_count": len(results),
            "status_counts": status_counts,
            "confirmation_item_count": confirmation_count,
            "missing_input_count": missing_input_count,
            "generated_at": now_iso(),
            "real_execution": {
                "published_to_ebay": False,
                "procurement_paid": False,
                "refund_executed": False,
                "ad_budget_changed": False,
                "store_policy_changed": False,
            },
        }

    def _safe_name(self, value: Any) -> str:
        text = str(value).replace(".", "_")
        return "".join(char if char.isalnum() or char in {"_", "-"} else "_" for char in text)
