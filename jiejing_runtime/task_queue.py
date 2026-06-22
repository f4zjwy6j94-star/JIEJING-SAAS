"""Task queue primitives for the Jiejing Agent Runtime MVP."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterator

from .models import JiejingTask, RuntimeIssue


@dataclass(slots=True)
class TaskQueueItem:
    order: int
    task: JiejingTask
    status: str = "queued"


class TaskQueue:
    """Small in-memory queue with dependency checks.

    The first production queue will likely be Redis, Postgres, or a managed
    queue. This object keeps the same mental model in the MVP: tasks are queued,
    validated, marked running, and then completed.
    """

    def __init__(self, items: list[TaskQueueItem]) -> None:
        self.items = items
        self._cursor = 0

    @classmethod
    def from_raw_tasks(cls, raw_tasks: list[dict[str, Any]]) -> "TaskQueue":
        return cls([TaskQueueItem(order=index, task=JiejingTask(raw)) for index, raw in enumerate(raw_tasks, start=1)])

    def __iter__(self) -> Iterator[TaskQueueItem]:
        return iter(self.items)

    def validate_dependencies(self) -> list[RuntimeIssue]:
        issues: list[RuntimeIssue] = []
        seen: set[str] = set()
        all_ids = {item.task.task_id for item in self.items if item.task.task_id}

        for item in self.items:
            task_id = item.task.task_id
            if not task_id:
                issues.append(RuntimeIssue("empty_task_id", f"Task at order {item.order} has no task_id."))
                continue
            if task_id in seen:
                issues.append(RuntimeIssue("duplicate_task_id", f"Duplicate task_id: {task_id}"))
            seen.add(task_id)

            parent = item.task.raw.get("parent_task_id")
            if parent and parent not in all_ids:
                issues.append(RuntimeIssue("missing_parent_task", f"{task_id} references missing parent_task_id: {parent}"))
            if parent and parent not in seen:
                issues.append(RuntimeIssue("parent_after_child", f"{task_id} appears before its parent_task_id: {parent}", "warning"))

        return issues

    def has_next(self) -> bool:
        return self._cursor < len(self.items)

    def next(self) -> TaskQueueItem:
        item = self.items[self._cursor]
        self._cursor += 1
        item.status = "running"
        return item

    def complete(self, item: TaskQueueItem, status: str) -> None:
        item.status = status

    def snapshot(self) -> list[dict[str, Any]]:
        return [
            {
                "order": item.order,
                "task_id": item.task.task_id,
                "task_type": item.task.task_type,
                "status": item.status,
                "parent_task_id": item.task.raw.get("parent_task_id"),
            }
            for item in self.items
        ]
