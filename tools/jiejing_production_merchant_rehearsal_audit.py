#!/usr/bin/env python3
"""Read-only, secret-safe audit of one merchant eBay rehearsal chain.

Run inside the production API container. The confirmation ID is used as the
tenant anchor, so the audit never needs an email address, password, session
cookie, OAuth refresh or broad cross-tenant export.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Iterable

from jiejing_saas.merchant_project_status import build_merchant_project_status
from jiejing_saas.repository import SaaSRepository


PRODUCT_MARKERS = ("jj-incense-jc2023041300002-01", "245675556011", "jc2023041300002", "香炉", "incense")
PROJECT_KEYS = {"project_id", "listing_project_key", "project_key"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirmation-id", required=True)
    return parser.parse_args()


def load_json(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(str(value or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def walk(value: Any) -> Iterable[tuple[str, Any]]:
    if isinstance(value, dict):
        for key, child in value.items():
            yield str(key), child
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def first_value(payload: Any, keys: set[str]) -> Any:
    for key, value in walk(payload):
        if key in keys and value not in (None, "", [], {}):
            return value
    return None


def all_text_values(payload: Any, keys: set[str]) -> list[str]:
    values: list[str] = []
    for key, value in walk(payload):
        if key in keys and value not in (None, "", [], {}):
            text = str(value).strip()
            if text and text not in values:
                values.append(text)
    return values


def project_ids(payload: Any) -> list[str]:
    values = all_text_values(payload, PROJECT_KEYS)
    for key, value in walk(payload):
        if key != "listing_project_identity" or not isinstance(value, dict):
            continue
        project_id = str(value.get("key") or "").strip()
        if project_id and project_id not in values:
            values.append(project_id)
    return values


def project_identities(payload: Any) -> list[dict[str, str]]:
    identities: list[dict[str, str]] = []
    for key, value in walk(payload):
        if key != "listing_project_identity" or not isinstance(value, dict):
            continue
        identity = {
            "key": str(value.get("key") or "").strip(),
            "source_report_id": str(value.get("source_report_id") or value.get("source_id") or "").strip(),
            "candidate_id": str(value.get("candidate_id") or "").strip(),
        }
        if identity["key"] and identity not in identities:
            identities.append(identity)
    return identities


def platform_errors(payload: Any) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    for key, value in walk(payload):
        if key != "platform_error" or not isinstance(value, dict):
            continue
        item = {
            "error_id": value.get("error_id"),
            "code": str(value.get("code") or "")[:80],
            "domain": str(value.get("domain") or "")[:80],
            "message": " ".join(str(value.get("message") or "").split())[:240],
        }
        if item not in errors:
            errors.append(item)
    return errors


def marker_clause(columns: list[str]) -> tuple[str, list[str]]:
    predicates: list[str] = []
    params: list[str] = []
    for column in columns:
        for marker in PRODUCT_MARKERS:
            predicates.append(f"lower(cast({column} as text)) like ?")
            params.append(f"%{marker.lower()}%")
    return "(" + " or ".join(predicates) + ")", params


def row_dict(row: Any) -> dict[str, Any]:
    return dict(row) if row is not None else {}


class SnapshotRepository:
    """In-memory repository view so project status derivation stays read-only."""

    def __init__(self, *, tasks, reports, confirmations, executions, media):
        self.tasks = tasks
        self.reports = reports
        self.confirmations = confirmations
        self.executions = executions
        self.media = media

    def list_tasks(self, *, company_id, store_id=None, limit=None):
        del company_id, store_id, limit
        return self.tasks

    def list_reports(self, *, company_id, task_id=None, limit=None):
        del company_id, limit
        return [item for item in self.reports if not task_id or item.get("task_id") == task_id]

    def list_confirmations(self, *, company_id, status=None, limit=None):
        del company_id, limit
        return [item for item in self.confirmations if not status or item.get("status") == status]

    def list_execution_results(self, *, company_id, limit=None):
        del company_id, limit
        return self.executions

    def list_media_asset_jobs(self, *, company_id, store_id=None, status=None, limit=100):
        del company_id, store_id, limit
        return [item for item in self.media if not status or item.get("status") == status]


def main() -> int:
    args = parse_args()
    repository = SaaSRepository(
        Path(os.environ.get("JIEJING_SAAS_DB_PATH") or "/tmp/jiejing-saas.sqlite3"),
        database_engine=os.environ.get("JIEJING_DATABASE_ENGINE"),
        database_url=os.environ.get("JIEJING_DATABASE_URL", ""),
    )

    with repository._connect() as conn:  # Read-only queries only; no initialize or writes.
        confirmation_row = conn.execute(
            "select * from confirmations where confirmation_id = ?",
            (args.confirmation_id,),
        ).fetchone()
        if not confirmation_row:
            print(json.dumps({"ok": False, "reason": "confirmation_not_found", "secret_exposed": False}))
            return 2

        confirmation = row_dict(confirmation_row)
        company_id = str(confirmation.get("company_id") or "")
        store_id = str(confirmation.get("store_id") or "")
        task_id = str(confirmation.get("task_id") or "")
        confirmation_json = load_json(confirmation.get("item_json"))

        task_row = conn.execute(
            "select * from tasks where company_id = ? and task_id = ?",
            (company_id, task_id),
        ).fetchone()
        task = row_dict(task_row)
        user_id = str(task.get("user_id") or confirmation.get("decided_by") or "")

        task_marker_sql, task_marker_params = marker_clause(["input_json", "output_json", "title"])
        related_tasks = conn.execute(
            f"select * from tasks where company_id = ? and (task_id = ? or {task_marker_sql}) order by created_at asc",
            tuple([company_id, task_id, *task_marker_params]),
        ).fetchall()
        related_task_ids = [str(row["task_id"]) for row in related_tasks]
        related_placeholders = ",".join("?" for _ in related_task_ids) or "?"
        related_query_ids = related_task_ids or [task_id]

        report_marker_sql, report_marker_params = marker_clause(["r.report_json", "r.title"])
        reports = conn.execute(
            f"""
            select r.* from reports r
            join tasks t on t.task_id = r.task_id
            where t.company_id = ? and (r.task_id = ? or {report_marker_sql})
            order by r.created_at asc
            """,
            tuple([company_id, task_id, *report_marker_params]),
        ).fetchall()

        executions = conn.execute(
            "select * from execution_results where confirmation_id = ? order by created_at asc",
            (args.confirmation_id,),
        ).fetchall()

        chat_rows = []
        if user_id:
            chat_marker_sql, chat_marker_params = marker_clause(["turn_json"])
            chat_rows = conn.execute(
                f"""
                select * from ai_ceo_chat_turns
                where company_id = ? and user_id = ? and {chat_marker_sql}
                order by created_at asc
                """,
                tuple([company_id, user_id, *chat_marker_params]),
            ).fetchall()

        media_marker_sql, media_marker_params = marker_clause(["media_job_json"])
        media_rows = conn.execute(
            f"""
            select * from media_asset_jobs
            where company_id = ? and (task_id = ? or {media_marker_sql})
            order by created_at asc
            """,
            tuple([company_id, task_id, *media_marker_params]),
        ).fetchall()

        model_usage = conn.execute(
            f"""
            select count(*) as record_count,
                   coalesce(sum(request_count), 0) as request_count,
                   coalesce(sum(total_tokens), 0) as total_tokens,
                   coalesce(sum(cost_minor), 0) as cost_minor,
                   max(created_at) as latest_at
            from model_usage_ledger
            where company_id = ? and task_id in ({related_placeholders})
            """,
            tuple([company_id, *related_query_ids]),
        ).fetchone()
        provider_cost = conn.execute(
            f"""
            select count(*) as record_count,
                   coalesce(sum(media_points), 0) as media_points,
                   coalesce(sum(cost_minor), 0) as cost_minor,
                   max(created_at) as latest_at
            from provider_cost_ledger
            where company_id = ? and task_id in ({related_placeholders})
            """,
            tuple([company_id, *related_query_ids]),
        ).fetchone()

        credit_account_row = conn.execute(
            """
            select balance_points, reserved_points, lifetime_granted_points,
                   lifetime_spent_points, updated_at
            from media_credit_accounts where company_id = ?
            """,
            (company_id,),
        ).fetchone()
        credit_ledger_rows = conn.execute(
            """
            select operation_type, points, status, reference_type, reference_id, created_at
            from media_credit_ledger where company_id = ?
            order by created_at desc limit 30
            """,
            (company_id,),
        ).fetchall()

        connection_rows = conn.execute(
            """
            select connection_id, status, created_at, store_id
            from platform_connections
            where company_id = ? and lower(platform) = 'ebay'
            order by created_at desc
            """,
            (company_id,),
        ).fetchall()

        audit_marker_sql, audit_marker_params = marker_clause(["audit_json", "summary", "target_id"])
        audit_rows = conn.execute(
            f"""
            select action_type, target_type, target_id, created_at
            from audit_logs
            where company_id = ? and (target_id = ? or {audit_marker_sql})
            order by created_at asc limit 200
            """,
            tuple([company_id, args.confirmation_id, *audit_marker_params]),
        ).fetchall()

        snapshot_task_rows = conn.execute(
            "select * from tasks where company_id = ? and store_id = ? order by created_at desc limit 500",
            (company_id, store_id),
        ).fetchall()
        snapshot_report_rows = conn.execute(
            """
            select r.* from reports r join tasks t on t.task_id = r.task_id
            where t.company_id = ? and t.store_id = ? order by r.created_at desc limit 500
            """,
            (company_id, store_id),
        ).fetchall()
        snapshot_confirmation_rows = conn.execute(
            """
            select * from confirmations where company_id = ? and store_id = ?
            order by created_at desc limit 500
            """,
            (company_id, store_id),
        ).fetchall()
        snapshot_execution_rows = conn.execute(
            """
            select e.* from execution_results e
            join confirmations c on c.confirmation_id = e.confirmation_id
            where c.company_id = ? and c.store_id = ? order by e.created_at desc limit 500
            """,
            (company_id, store_id),
        ).fetchall()
        snapshot_media_rows = conn.execute(
            """
            select * from media_asset_jobs where company_id = ? and store_id = ?
            order by created_at desc limit 200
            """,
            (company_id, store_id),
        ).fetchall()

    task_summaries = []
    for row in related_tasks:
        item = row_dict(row)
        payload = {**load_json(item.get("input_json")), **load_json(item.get("output_json"))}
        task_summaries.append(
            {
                "task_id": item.get("task_id"),
                "task_type": item.get("task_type"),
                "status": item.get("status"),
                "created_at": item.get("created_at"),
                "updated_at": item.get("updated_at"),
                "sku": first_value(payload, {"sku"}),
                "offer_id": first_value(payload, {"offer_id"}),
                "project_ids": project_ids(payload),
            }
        )

    report_summaries = []
    for row in reports:
        item = row_dict(row)
        payload = load_json(item.get("report_json"))
        fact_packet = first_value(payload, {"merchant_product_fact_packet"})
        fact_packet = fact_packet if isinstance(fact_packet, dict) else {}
        confirmed_facts = fact_packet.get("merchant_confirmed_facts")
        confirmed_facts = confirmed_facts if isinstance(confirmed_facts, dict) else {}
        source_facts = fact_packet.get("source_confirmed_facts")
        source_facts = source_facts if isinstance(source_facts, dict) else {}
        report_summaries.append(
            {
                "report_id": item.get("report_id"),
                "task_id": item.get("task_id"),
                "report_type": item.get("report_type"),
                "status": item.get("status"),
                "created_at": item.get("created_at"),
                "sku": first_value(payload, {"sku"}),
                "offer_id": first_value(payload, {"offer_id"}),
                "project_ids": project_ids(payload),
                "project_identities": project_identities(payload),
                "unknown_facts": fact_packet.get("unknown_facts") if isinstance(fact_packet.get("unknown_facts"), list) else [],
                "blocked_by": fact_packet.get("blocked_by") if isinstance(fact_packet.get("blocked_by"), list) else [],
                "confirmed_fact_keys": sorted(str(key) for key in confirmed_facts),
                "source_fact_keys": sorted(str(key) for key in source_facts),
            }
        )

    execution_summaries = []
    for row in executions:
        item = row_dict(row)
        payload = load_json(item.get("result_json"))
        execution_summaries.append(
            {
                "execution_id": item.get("execution_id"),
                "action_type": item.get("action_type"),
                "status": item.get("status"),
                "created_at": item.get("created_at"),
                "offer_id": first_value(payload, {"offer_id"}) or first_value(confirmation_json, {"offer_id"}),
                "listing_id": first_value(payload, {"listing_id", "item_id"}),
                "public_listing_created": first_value(payload, {"public_listing_created", "published_to_ebay"}),
                "platform_errors": platform_errors(payload),
                "blockers": all_text_values(payload, {"blocker", "blocked_by", "reason", "error_code"})[:12],
            }
        )

    media_summaries = []
    for row in media_rows:
        item = row_dict(row)
        payload = load_json(item.get("media_job_json"))
        outputs = first_value(payload, {"outputs", "artifacts", "generated_assets"})
        media_summaries.append(
            {
                "media_job_id": item.get("media_job_id"),
                "task_id": item.get("task_id"),
                "status": item.get("status"),
                "created_at": item.get("created_at"),
                "updated_at": item.get("updated_at"),
                "provider": first_value(payload, {"provider"}),
                "sku": first_value(payload, {"sku"}),
                "project_ids": project_ids(payload),
                "project_identities": project_identities(payload),
                "output_count": len(outputs) if isinstance(outputs, list) else None,
                "listing_use_status": first_value(payload, {"listing_use_status", "review_status"}),
                "concept_only": first_value(payload, {"concept_only"}),
            }
        )

    credit_account = row_dict(credit_account_row)
    if credit_account:
        credit_account["available_points"] = int(credit_account.get("balance_points") or 0) - int(
            credit_account.get("reserved_points") or 0
        )

    project_id_values = project_ids(confirmation_json)
    if not project_id_values:
        for item in media_summaries:
            project_id_values.extend(item.get("project_ids") or [])
    current_project_id = next(iter(dict.fromkeys(project_id_values)), "")
    has_account_restriction = any(
        str(error.get("error_id") or "") == "25019"
        for execution in execution_summaries
        for error in execution.get("platform_errors") or []
    )
    snapshot_repository = SnapshotRepository(
        tasks=[repository._task_row_to_dict(row) for row in snapshot_task_rows],
        reports=[repository._report_row_to_dict(row) for row in snapshot_report_rows],
        confirmations=[repository._confirmation_row_to_dict(row) for row in snapshot_confirmation_rows],
        executions=[repository._execution_row_to_dict(row) for row in snapshot_execution_rows],
        media=[repository._media_asset_job_row_to_dict(row) for row in snapshot_media_rows],
    )
    project_status = build_merchant_project_status(
        repository=snapshot_repository,
        company_id=company_id,
        store_id=store_id,
        project_id=current_project_id,
        account_health=(
            {"status": "restricted", "onboarding_stage": "account_review_required"}
            if has_account_restriction
            else {"status": "normal"}
        ),
    )

    result = {
        "ok": True,
        "scope": {
            "company_id": company_id,
            "store_id": store_id,
            "task_id": task_id,
            "related_task_ids": related_task_ids,
        },
        "confirmation": {
            "confirmation_id": args.confirmation_id,
            "action_type": confirmation.get("action_type"),
            "status": confirmation.get("status"),
            "created_at": confirmation.get("created_at"),
            "decided_at": confirmation.get("decided_at"),
            "offer_id": first_value(confirmation_json, {"offer_id"}),
            "sku": first_value(confirmation_json, {"sku"}),
            "project_ids": project_ids(confirmation_json),
        },
        "tasks": task_summaries,
        "reports": report_summaries,
        "executions": execution_summaries,
        "ai_ceo_chat": {
            "matching_turn_count": len(chat_rows),
            "turns": [
                {
                    "assistant_id": row["assistant_id"],
                    "status": row["status"],
                    "route": row["route"],
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                }
                for row in chat_rows
            ],
        },
        "media_jobs": media_summaries,
        "merchant_project_status": project_status,
        "model_usage": row_dict(model_usage),
        "provider_cost": row_dict(provider_cost),
        "media_credit_account": credit_account,
        "recent_media_credit_ledger": [row_dict(row) for row in credit_ledger_rows],
        "ebay_connections": [row_dict(row) for row in connection_rows],
        "audit": {
            "matching_record_count": len(audit_rows),
            "actions": [row_dict(row) for row in audit_rows],
        },
        "merchant_visibility_contract": {
            "chat_history": "GET /ai-ceo/chat-history",
            "tasks": "GET /tasks",
            "reports": "GET /reports",
            "confirmations": "GET /confirmations",
            "executions": "GET /execution-results",
            "media_jobs": "GET /stores/{store_id}/media-asset-jobs",
            "project_status": "GET /stores/{store_id}/merchant-project-status?project_id=...",
        },
        "read_only": True,
        "external_platform_called": False,
        "oauth_performed": False,
        "secret_exposed": False,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
