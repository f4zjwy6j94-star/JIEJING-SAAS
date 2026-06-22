"""SQLite persistence for Jiejing Agent Runtime.

The runtime still writes file artifacts for inspection, but a SaaS backend needs
queryable state. This repository is the first local persistence layer: runs,
task snapshots, results, confirmation items, and audit events can be saved and
queried without depending on Hermes internals.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .execution import ExecutionRequest, ExecutionService
from .listing_package import ListingPackageValidator
from .long_term_memory import LongTermMemoryRecord, build_memory_record, memory_candidates_from_result, summarize_memory_records


class SQLiteRuntimeRepository:
    VALIDATION_KEYS = [
        "report_contract",
        "listing_validation",
        "asset_manifest_validation",
        "customer_learning_validation",
        "finance_review_validation",
        "confirmation_package_validation",
        "ceo_final_report_validation",
    ]

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path

    def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(
                """
                create table if not exists runs (
                  run_id text primary key,
                  adapter text not null,
                  run_status text not null,
                  task_count integer not null,
                  confirmation_item_count integer not null,
                  missing_input_count integer not null,
                  generated_at text not null,
                  summary_json text not null
                );

                create table if not exists tasks (
                  run_id text not null,
                  order_index integer not null,
                  task_id text not null,
                  task_type text not null,
                  status text not null,
                  parent_task_id text,
                  task_json text not null,
                  primary key (run_id, task_id)
                );

                create table if not exists results (
                  run_id text not null,
                  order_index integer not null,
                  task_id text not null,
                  task_type text not null,
                  status text not null,
                  result_json text not null,
                  primary key (run_id, task_id)
                );

                create table if not exists confirmations (
                  run_id text not null,
                  confirmation_id text not null,
                  task_id text not null,
                  action_type text not null,
                  title text not null,
                  default_action text not null,
                  item_json text not null,
                  primary key (run_id, confirmation_id)
                );

                create table if not exists audit_events (
                  run_id text not null,
                  event_index integer not null,
                  event_type text not null,
                  task_id text,
                  created_at text not null,
                  event_json text not null,
                  primary key (run_id, event_index)
                );

                create table if not exists confirmation_decisions (
                  run_id text not null,
                  confirmation_id text not null,
                  decision text not null,
                  decided_by text not null,
                  decided_at text not null,
                  note text,
                  decision_json text not null,
                  primary key (run_id, confirmation_id)
                );

                create table if not exists execution_results (
                  run_id text not null,
                  execution_id text not null,
                  confirmation_id text not null,
                  task_id text not null,
                  action_type text not null,
                  status text not null,
                  created_at text not null,
                  result_json text not null,
                  primary key (run_id, execution_id)
                );

                create table if not exists long_term_memories (
                  memory_id text primary key,
                  scope_type text not null,
                  scope_id text not null,
                  user_id text,
                  company_id text,
                  store_id text,
                  product text,
                  role text,
                  task_type text,
                  title text not null,
                  content text not null,
                  tags_json text not null,
                  source_run_id text,
                  source_task_id text,
                  confidence text not null,
                  priority integer not null,
                  memory_status text not null,
                  visibility text not null,
                  sensitivity_level text not null,
                  created_at text not null,
                  updated_at text not null
                );
                """
            )

    def save_run_directory(self, run_dir: Path) -> dict[str, Any]:
        self.initialize()
        run_json_path = run_dir / "run.json"
        if not run_json_path.exists():
            raise FileNotFoundError(f"missing run.json: {run_json_path}")
        summary = self._read_json(run_json_path)
        run_id = str(summary["run_id"])
        results_dir = run_dir / "results"
        tasks_dir = run_dir / "tasks"
        audit_path = run_dir / "audit-log.jsonl"

        result_files = sorted(results_dir.glob("*.json")) if results_dir.exists() else []
        task_files = sorted(tasks_dir.glob("*.json")) if tasks_dir.exists() else []
        audit_events = self._read_audit_events(audit_path)

        with self._connect() as conn:
            self._delete_run(conn, run_id)
            conn.execute(
                """
                insert into runs (
                  run_id, adapter, run_status, task_count, confirmation_item_count,
                  missing_input_count, generated_at, summary_json
                ) values (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    summary.get("adapter", ""),
                    summary.get("run_status", ""),
                    int(summary.get("task_count", 0)),
                    int(summary.get("confirmation_item_count", 0)),
                    int(summary.get("missing_input_count", 0)),
                    summary.get("generated_at", ""),
                    json.dumps(summary, ensure_ascii=False),
                ),
            )
            queue_by_task = {item.get("task_id"): item for item in summary.get("queue", []) if isinstance(item, dict)}
            for order, file_path in enumerate(task_files, start=1):
                task = self._read_json(file_path)
                queue_item = queue_by_task.get(task.get("task_id"), {})
                conn.execute(
                    """
                    insert into tasks (
                      run_id, order_index, task_id, task_type, status, parent_task_id, task_json
                    ) values (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        order,
                        task.get("task_id", ""),
                        task.get("task_type", ""),
                        queue_item.get("status", "queued"),
                        task.get("parent_task_id"),
                        json.dumps(task, ensure_ascii=False),
                    ),
                )
            result_payloads = []
            for order, file_path in enumerate(result_files, start=1):
                result = self._read_json(file_path)
                result_payloads.append(result)
                conn.execute(
                    """
                    insert into results (
                      run_id, order_index, task_id, task_type, status, result_json
                    ) values (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        order,
                        result.get("task_id", ""),
                        result.get("task_type", ""),
                        result.get("status", ""),
                        json.dumps(result, ensure_ascii=False),
                    ),
                )
                for item in result.get("confirmation_items", []):
                    if not isinstance(item, dict):
                        continue
                    conn.execute(
                        """
                        insert into confirmations (
                          run_id, confirmation_id, task_id, action_type, title, default_action, item_json
                        ) values (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            run_id,
                            item.get("confirmation_id", ""),
                            result.get("task_id", ""),
                            item.get("action_type", ""),
                            item.get("title", ""),
                            item.get("default_action", ""),
                            json.dumps(item, ensure_ascii=False),
                        ),
                    )
            self._upsert_memory_candidates(conn, run_id, result_payloads)
            for index, event in enumerate(audit_events, start=1):
                conn.execute(
                    """
                    insert into audit_events (
                      run_id, event_index, event_type, task_id, created_at, event_json
                    ) values (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        index,
                        event.get("event_type", ""),
                        event.get("task_id"),
                        event.get("created_at", ""),
                        json.dumps(event, ensure_ascii=False),
                    ),
                )
        return {"run_id": run_id, "results": len(result_files), "tasks": len(task_files), "audit_events": len(audit_events)}

    def list_runs(self) -> list[dict[str, Any]]:
        self.initialize()
        with self._connect() as conn:
            rows = conn.execute(
                """
                select run_id, adapter, run_status, task_count, confirmation_item_count,
                       missing_input_count, generated_at
                from runs
                order by generated_at desc, run_id desc
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        self.initialize()
        with self._connect() as conn:
            row = conn.execute("select summary_json from runs where run_id = ?", (run_id,)).fetchone()
        if row is None:
            return None
        return json.loads(row["summary_json"])

    def get_tasks(self, run_id: str) -> list[dict[str, Any]]:
        return self._get_json_rows("tasks", "task_json", run_id)

    def get_results(self, run_id: str) -> list[dict[str, Any]]:
        return self._get_json_rows("results", "result_json", run_id)

    def get_validation_summary(self, run_id: str) -> dict[str, Any]:
        results = self.get_results(run_id)
        validations = []
        for result in results:
            report = result.get("report", {})
            if not isinstance(report, dict):
                continue
            for key in self.VALIDATION_KEYS:
                validation = report.get(key)
                if not isinstance(validation, dict):
                    continue
                validations.append(
                    {
                        "task_id": result.get("task_id"),
                        "task_type": result.get("task_type"),
                        "result_status": result.get("status"),
                        "validation_key": key,
                        "validator": validation.get("validator"),
                        "validator_version": validation.get("validator_version"),
                        "validation_status": validation.get("status"),
                        "summary": validation.get("summary"),
                    }
                )
        blocked = [
            item
            for item in validations
            if "blocked" in str(item.get("validation_status", "")) or "missing" in str(item.get("validation_status", ""))
        ]
        ready = [
            item
            for item in validations
            if str(item.get("validation_status", "")).startswith("ready")
            or str(item.get("validation_status", "")).endswith("ready")
            or str(item.get("validation_status", "")) == "manifest_ready"
        ]
        return {
            "run_id": run_id,
            "validation_count": len(validations),
            "ready_count": len(ready),
            "blocked_count": len(blocked),
            "validations": validations,
        }

    def apply_listing_facts(
        self,
        run_id: str,
        facts: dict[str, Any],
        updated_by: str = "merchant_demo",
    ) -> dict[str, Any]:
        """Apply merchant-supplied listing facts and revalidate listing package.

        This is still a demo/local API operation. It updates the Runtime record
        so the SaaS mock can prove a blocked listing package can become ready for
        confirmation review after facts are supplied. It never executes eBay.
        """

        self.initialize()
        validator = ListingPackageValidator()
        updated_at = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
        normalized_facts = {str(key): value for key, value in (facts or {}).items()}

        with self._connect() as conn:
            run_row = conn.execute("select summary_json from runs where run_id = ?", (run_id,)).fetchone()
            if run_row is None:
                raise KeyError(f"run not found: {run_id}")

            result_row = conn.execute(
                """
                select order_index, task_id, result_json
                from results
                where run_id = ? and task_type = 'listing.package'
                order by order_index
                limit 1
                """,
                (run_id,),
            ).fetchone()
            if result_row is None:
                raise KeyError("listing.package result not found")

            result = json.loads(result_row["result_json"])
            listing_text = self._listing_text_from_facts(result, normalized_facts)
            validation = validator.validate_text(listing_text)
            missing_inputs = validator.missing_inputs_from_validation(validation)
            next_status = (
                "blocked_confirmation_required"
                if validation.get("status") == "ready_for_confirmation_review"
                else "blocked_missing_input"
            )

            report = dict(result.get("report") or {})
            sections = dict(report.get("sections") or {})
            sections["merchant_supplied_listing_facts"] = normalized_facts
            sections["listing_revalidation"] = {
                "updated_by": updated_by,
                "updated_at": updated_at,
                "validation_status": validation.get("status"),
                "next_status": next_status,
                "real_execution_allowed": False,
            }
            report["sections"] = sections
            report["listing_validation"] = validation
            report["merchant_readable_summary"] = (
                "商家补齐货源资料后，产品刊登资料包已重新校验。"
                "当前只能进入确认中心复核，仍不会真实发布到 eBay。"
            )

            result["status"] = next_status
            result["summary"] = report["merchant_readable_summary"]
            result["missing_inputs"] = missing_inputs
            result["report"] = report
            audit = dict(result.get("audit") or {})
            audit["real_execution_allowed"] = False
            audit["real_execution"] = {
                "published_to_ebay": False,
                "procurement_paid": False,
                "refund_executed": False,
                "ad_budget_changed": False,
                "store_policy_changed": False,
            }
            result["audit"] = audit

            conn.execute(
                """
                update results
                set status = ?, result_json = ?
                where run_id = ? and task_id = ?
                """,
                (
                    next_status,
                    json.dumps(result, ensure_ascii=False),
                    run_id,
                    result.get("task_id", ""),
                ),
            )
            conn.execute(
                """
                update tasks
                set status = ?
                where run_id = ? and task_id = ?
                """,
                (next_status, run_id, result.get("task_id", "")),
            )

            result_rows = conn.execute(
                "select result_json from results where run_id = ? order by order_index",
                (run_id,),
            ).fetchall()
            result_payloads = [json.loads(row["result_json"]) for row in result_rows]
            missing_count = sum(len(item.get("missing_inputs") or []) for item in result_payloads)
            confirmation_count = sum(len(item.get("confirmation_items") or []) for item in result_payloads)
            has_block = any("blocked" in str(item.get("status", "")) for item in result_payloads)
            run_status = "completed_with_blocks" if has_block or missing_count else "completed"
            summary = json.loads(run_row["summary_json"])
            summary["run_status"] = run_status
            summary["missing_input_count"] = missing_count
            summary["confirmation_item_count"] = confirmation_count
            for queue_item in summary.get("queue", []):
                if queue_item.get("task_id") == result.get("task_id"):
                    queue_item["status"] = next_status
            conn.execute(
                """
                update runs
                set run_status = ?, missing_input_count = ?, confirmation_item_count = ?, summary_json = ?
                where run_id = ?
                """,
                (
                    run_status,
                    missing_count,
                    confirmation_count,
                    json.dumps(summary, ensure_ascii=False),
                    run_id,
                ),
            )

            next_event_index = (
                conn.execute(
                    "select coalesce(max(event_index), 0) + 1 as next_index from audit_events where run_id = ?",
                    (run_id,),
                ).fetchone()["next_index"]
            )
            event = {
                "run_id": run_id,
                "event_type": "listing_facts_revalidated",
                "task_id": result.get("task_id"),
                "created_at": updated_at,
                "updated_by": updated_by,
                "validation_status": validation.get("status"),
                "next_status": next_status,
                "real_execution_allowed": False,
            }
            conn.execute(
                """
                insert into audit_events (
                  run_id, event_index, event_type, task_id, created_at, event_json
                ) values (?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    int(next_event_index),
                    event["event_type"],
                    result.get("task_id"),
                    updated_at,
                    json.dumps(event, ensure_ascii=False),
                ),
            )

        return {
            "run_id": run_id,
            "task_id": result.get("task_id"),
            "result_status": next_status,
            "validation": validation,
            "validation_summary": self.get_validation_summary(run_id),
        }

    def get_confirmations(self, run_id: str) -> list[dict[str, Any]]:
        return self._get_json_rows("confirmations", "item_json", run_id)

    def get_audit_events(self, run_id: str) -> list[dict[str, Any]]:
        return self._get_json_rows("audit_events", "event_json", run_id)

    def list_memories(
        self,
        *,
        scope_type: str | None = None,
        role: str | None = None,
        task_type: str | None = None,
        product: str | None = None,
        limit: int = 80,
    ) -> list[dict[str, Any]]:
        self.initialize()
        clauses = ["memory_status != 'archived'"]
        values: list[Any] = []
        if scope_type:
            clauses.append("scope_type = ?")
            values.append(scope_type)
        if role:
            clauses.append("role = ?")
            values.append(role)
        if task_type:
            clauses.append("task_type = ?")
            values.append(task_type)
        if product:
            clauses.append("product like ?")
            values.append(f"%{product}%")
        values.append(max(1, min(200, int(limit))))
        sql = f"""
            select *
            from long_term_memories
            where {' and '.join(clauses)}
            order by priority desc, updated_at desc, memory_id desc
            limit ?
        """
        with self._connect() as conn:
            rows = conn.execute(sql, values).fetchall()
        return [self._memory_row_to_dict(row) for row in rows]

    def get_memory_summary(self) -> dict[str, Any]:
        return summarize_memory_records(self.list_memories(limit=200))

    def create_memory(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.initialize()
        record = build_memory_record(
            scope_type=str(payload.get("scope_type") or "workflow"),
            scope_id=str(payload.get("scope_id") or "manual"),
            title=str(payload.get("title") or ""),
            content=str(payload.get("content") or ""),
            user_id=str(payload.get("user_id") or ""),
            company_id=str(payload.get("company_id") or ""),
            store_id=str(payload.get("store_id") or ""),
            product=str(payload.get("product") or ""),
            role=str(payload.get("role") or ""),
            task_type=str(payload.get("task_type") or ""),
            tags=[str(item) for item in payload.get("tags", [])] if isinstance(payload.get("tags"), list) else [],
            source_run_id=str(payload.get("source_run_id") or ""),
            source_task_id=str(payload.get("source_task_id") or ""),
            confidence=str(payload.get("confidence") or "medium"),
            priority=int(payload.get("priority") or 50),
            memory_status=str(payload.get("memory_status") or "active"),
        )
        if record is None:
            raise ValueError("memory content is empty or unsafe")
        with self._connect() as conn:
            self._upsert_memory_record(conn, record)
        return record.to_dict()

    def record_confirmation_decision(
        self,
        run_id: str,
        confirmation_id: str,
        decision: str,
        decided_by: str,
        decided_at: str,
        note: str | None = None,
    ) -> dict[str, Any]:
        self.initialize()
        if decision not in {"approve", "edit", "reject"}:
            raise ValueError("decision must be one of: approve, edit, reject")
        confirmation = self._get_confirmation(run_id, confirmation_id)
        if confirmation is None:
            raise KeyError(f"confirmation not found: {confirmation_id}")

        record = {
            "run_id": run_id,
            "confirmation_id": confirmation_id,
            "decision": decision,
            "decided_by": decided_by,
            "decided_at": decided_at,
            "note": note,
            "execution_status": "held_for_execution_service",
            "real_execution": {
                "published_to_ebay": False,
                "procurement_paid": False,
                "refund_executed": False,
                "ad_budget_changed": False,
                "store_policy_changed": False,
            },
        }
        with self._connect() as conn:
            event_index = self._next_event_index(conn, run_id)
            conn.execute(
                """
                insert or replace into confirmation_decisions (
                  run_id, confirmation_id, decision, decided_by, decided_at, note, decision_json
                ) values (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    confirmation_id,
                    decision,
                    decided_by,
                    decided_at,
                    note,
                    json.dumps(record, ensure_ascii=False),
                ),
            )
            event = {
                "run_id": run_id,
                "event_type": "confirmation_decision_recorded",
                "confirmation_id": confirmation_id,
                "task_id": confirmation.get("source_task_ids", [None])[0],
                "created_at": decided_at,
                "decision": decision,
                "decided_by": decided_by,
                "execution_status": record["execution_status"],
                "real_execution_allowed": False,
            }
            conn.execute(
                """
                insert into audit_events (
                  run_id, event_index, event_type, task_id, created_at, event_json
                ) values (?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    int(event_index),
                    event["event_type"],
                    event.get("task_id"),
                    decided_at,
                    json.dumps(event, ensure_ascii=False),
                ),
            )
        return record

    def get_confirmation_decisions(self, run_id: str) -> list[dict[str, Any]]:
        self.initialize()
        with self._connect() as conn:
            rows = conn.execute(
                "select decision_json from confirmation_decisions where run_id = ? order by decided_at, confirmation_id",
                (run_id,),
            ).fetchall()
        return [json.loads(row["decision_json"]) for row in rows]

    def execute_confirmation_decision(
        self,
        run_id: str,
        confirmation_id: str,
        requested_by: str = "merchant_demo",
        demo_mode: bool = True,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Send an approved confirmation through the ExecutionService boundary.

        The local Runtime records the execution handoff and audit trail. In demo
        mode it never writes to eBay, payment, logistics, ads, or procurement.
        """

        self.initialize()
        confirmation = self._get_confirmation(run_id, confirmation_id)
        if confirmation is None:
            raise KeyError(f"confirmation not found: {confirmation_id}")
        decision = self._get_confirmation_decision(run_id, confirmation_id)
        if decision is None:
            raise ValueError("confirmation decision is required before execution service")
        if decision.get("decision") != "approve":
            raise ValueError("only approved confirmations can enter execution service")
        action_type = str(confirmation.get("action_type") or "unknown_action")
        if action_type in {"publish_listing", "bulk_publish_listing"} and not self._listing_ready_for_execution(run_id):
            raise ValueError("listing package must be ready for confirmation review before publish execution handoff")

        task_id = str(confirmation.get("source_task_ids", [confirmation.get("task_id", "")])[0] or confirmation.get("task_id", ""))
        task = self._get_task(run_id, task_id) or {}
        request = ExecutionRequest(
            action_type=action_type,
            task_id=task_id,
            user_id=str(task.get("user_id") or "user_demo"),
            company_id=str(task.get("company_id") or "company_demo"),
            store_id=str(task.get("store_id") or "store_demo"),
            platform=str(task.get("platform") or "ebay"),
            payload={
                "confirmation": confirmation,
                "decision": decision,
                **(payload or {}),
            },
            confirmation_id=confirmation_id,
            confirmed_by=str(decision.get("decided_by") or requested_by),
            confirmed_at=str(decision.get("decided_at") or datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")),
        )
        execution = ExecutionService(demo_mode=demo_mode).execute(request).to_dict()
        execution_id = f"exec_{confirmation_id}"
        record = {
            "run_id": run_id,
            "execution_id": execution_id,
            "confirmation_id": confirmation_id,
            "requested_by": requested_by,
            "demo_mode": demo_mode,
            "execution_result": execution,
            "real_execution": execution.get("audit", {}).get("real_execution", {}),
        }
        decision["execution_status"] = execution.get("status")
        decision["execution_result"] = execution
        with self._connect() as conn:
            conn.execute(
                """
                insert or replace into execution_results (
                  run_id, execution_id, confirmation_id, task_id, action_type, status, created_at, result_json
                ) values (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    execution_id,
                    confirmation_id,
                    task_id,
                    request.action_type,
                    execution.get("status"),
                    execution.get("created_at"),
                    json.dumps(record, ensure_ascii=False),
                ),
            )
            conn.execute(
                """
                update confirmation_decisions
                set decision_json = ?
                where run_id = ? and confirmation_id = ?
                """,
                (json.dumps(decision, ensure_ascii=False), run_id, confirmation_id),
            )
            event_index = self._next_event_index(conn, run_id)
            event = {
                "run_id": run_id,
                "event_type": "execution_service_handoff",
                "execution_id": execution_id,
                "confirmation_id": confirmation_id,
                "action_type": request.action_type,
                "task_id": task_id,
                "created_at": execution.get("created_at"),
                "status": execution.get("status"),
                "message": execution.get("message"),
                "real_execution": execution.get("audit", {}).get("real_execution", {}),
            }
            conn.execute(
                """
                insert into audit_events (
                  run_id, event_index, event_type, task_id, created_at, event_json
                ) values (?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    int(event_index),
                    event["event_type"],
                    task_id,
                    execution.get("created_at"),
                    json.dumps(event, ensure_ascii=False),
                ),
            )
        return record

    def get_execution_results(self, run_id: str) -> list[dict[str, Any]]:
        self.initialize()
        with self._connect() as conn:
            rows = conn.execute(
                "select result_json from execution_results where run_id = ? order by created_at, execution_id",
                (run_id,),
            ).fetchall()
        return [json.loads(row["result_json"]) for row in rows]

    def _get_json_rows(self, table: str, column: str, run_id: str) -> list[dict[str, Any]]:
        self.initialize()
        order_col = "order_index" if table in {"tasks", "results"} else "event_index"
        if table == "confirmations":
            order_col = "confirmation_id"
        with self._connect() as conn:
            rows = conn.execute(
                f"select {column} from {table} where run_id = ? order by {order_col}",
                (run_id,),
            ).fetchall()
        return [json.loads(row[column]) for row in rows]

    def _upsert_memory_candidates(self, conn: sqlite3.Connection, run_id: str, results: list[dict[str, Any]]) -> None:
        for result in results:
            for record in memory_candidates_from_result(run_id, result):
                self._upsert_memory_record(conn, record)

    def _upsert_memory_record(self, conn: sqlite3.Connection, record: LongTermMemoryRecord) -> None:
        conn.execute(
            """
            insert into long_term_memories (
              memory_id, scope_type, scope_id, user_id, company_id, store_id,
              product, role, task_type, title, content, tags_json, source_run_id,
              source_task_id, confidence, priority, memory_status, visibility,
              sensitivity_level, created_at, updated_at
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            on conflict(memory_id) do update set
              title = excluded.title,
              content = excluded.content,
              tags_json = excluded.tags_json,
              confidence = excluded.confidence,
              priority = excluded.priority,
              memory_status = excluded.memory_status,
              updated_at = excluded.updated_at
            """,
            (
                record.memory_id,
                record.scope_type,
                record.scope_id,
                record.user_id,
                record.company_id,
                record.store_id,
                record.product,
                record.role,
                record.task_type,
                record.title,
                record.content,
                json.dumps(record.tags, ensure_ascii=False),
                record.source_run_id,
                record.source_task_id,
                record.confidence,
                record.priority,
                record.memory_status,
                record.visibility,
                record.sensitivity_level,
                record.created_at,
                record.updated_at,
            ),
        )

    def _memory_row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        try:
            item["tags"] = json.loads(item.pop("tags_json") or "[]")
        except json.JSONDecodeError:
            item["tags"] = []
        return item

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _delete_run(self, conn: sqlite3.Connection, run_id: str) -> None:
        for table in ["execution_results", "confirmation_decisions", "audit_events", "confirmations", "results", "tasks", "runs"]:
            conn.execute(f"delete from {table} where run_id = ?", (run_id,))

    def _get_confirmation(self, run_id: str, confirmation_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "select item_json from confirmations where run_id = ? and confirmation_id = ?",
                (run_id, confirmation_id),
            ).fetchone()
        if row is None:
            return None
        return json.loads(row["item_json"])

    def _get_confirmation_decision(self, run_id: str, confirmation_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "select decision_json from confirmation_decisions where run_id = ? and confirmation_id = ?",
                (run_id, confirmation_id),
            ).fetchone()
        if row is None:
            return None
        return json.loads(row["decision_json"])

    def _get_task(self, run_id: str, task_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "select task_json from tasks where run_id = ? and task_id = ?",
                (run_id, task_id),
            ).fetchone()
        if row is None:
            return None
        return json.loads(row["task_json"])

    def _listing_ready_for_execution(self, run_id: str) -> bool:
        summary = self.get_validation_summary(run_id)
        for item in summary.get("validations", []):
            if item.get("validation_key") == "listing_validation":
                return item.get("validation_status") == "ready_for_confirmation_review"
        return False

    def _next_event_index(self, conn: sqlite3.Connection, run_id: str) -> int:
        return int(
            conn.execute(
                "select coalesce(max(event_index), 0) + 1 as next_index from audit_events where run_id = ?",
                (run_id,),
            ).fetchone()["next_index"]
        )

    def _listing_text_from_facts(self, result: dict[str, Any], facts: dict[str, Any]) -> str:
        product = str(facts.get("product") or facts.get("title_cn") or "Jiejing eBay Product").strip()
        title = str(
            facts.get("ebay_title")
            or facts.get("title")
            or f"{product[:42]} eBay Draft Listing"
        ).strip()
        if len(title) > 80:
            title = title[:80].rstrip()
        price = str(facts.get("price") or facts.get("purchase_price") or "US $19.99").strip()
        quantity = str(facts.get("quantity") or "50").strip()
        category = str(facts.get("category_id") or facts.get("category_candidate") or "20687").strip()
        weight = str(facts.get("package_weight") or "620 g").strip()
        dimensions = str(facts.get("package_dimensions") or "21 x 18 x 14 cm").strip()
        material = str(facts.get("material") or "confirmed supplier material").strip()
        location = str(facts.get("source_location") or "China").strip()
        included = str(facts.get("included") or "included accessories confirmed by supplier").strip()
        fulfillment = str(facts.get("fulfillment_policy_id") or "fulfillmentPolicyId DEMO-FULFILLMENT-001 authorized store default").strip()
        payment = str(facts.get("payment_policy_id") or "paymentPolicyId DEMO-PAYMENT-001 authorized store default").strip()
        returns = str(facts.get("return_policy_id") or "returnPolicyId DEMO-RETURN-001 authorized store default").strip()
        source_link = str(facts.get("source_link") or "merchant supplied source link").strip()
        quality = str(facts.get("quality_checks") or "packaging, breakage, supplier support and image consistency checked").strip()
        return f"""
# Product Manager Listing Package

SKU: {result.get("task_id", "JJ-DEMO-LISTING")}-READY
Title: {title}
Category ID: {category}
Condition: New
Format: Fixed Price
Price: {price}
Quantity: {quantity}

Item Specifics:
- Brand: Unbranded
- Type: {product}
- Material: {material}
- Color: As shown
- Included accessories: {included}
- MPN: Does Not Apply
- UPC: Does Not Apply

Pictures: Picture 1 white background; Picture 2 lifestyle scene; Picture 3 dimensions; Picture 4 detail; Picture 5 package/included items.
Video: 20 second product use and detail demonstration draft.
Description HTML: <div><h2>{product}</h2><p>Draft eBay description based on merchant supplied source facts. Source: {source_link}. Quality checks: {quality}.</p></div>
Package weight: {weight}
Package dimensions: {dimensions}
Handling time: 3 business days
Item Location: {location}
Fulfillment policy: {fulfillment}
Payment policy: {payment}
Return policy: {returns}
Publish blockers: publish lock remains active. Real eBay publish requires confirmation center approval, backend execution service, OAuth scope check, audit log, and final merchant approval.
"""

    def _read_json(self, path: Path) -> dict[str, Any]:
        return json.loads(path.read_text(encoding="utf-8"))

    def _read_audit_events(self, path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        events = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                events.append(json.loads(line))
        return events
