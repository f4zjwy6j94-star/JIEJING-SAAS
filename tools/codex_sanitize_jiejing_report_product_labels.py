#!/usr/bin/env python
"""Sanitize test artifacts that used the account/store label as a product name.

This is a one-off maintenance script for the controlled staging database. It
does not delete records or touch auth/token/secret tables. It only updates
model-value task/report/memory/audit text that incorrectly treated the merchant
account label as a product label.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from jiejing_runtime.models import now_iso
from jiejing_saas import SaaSRepository


WRONG_LABEL = "zongshuding4"
SAFE_LABEL = "Official eBay packet without selected SKU"


def sanitize_text(value: str) -> str:
    text = value
    phrase_patterns = [
        r"JJ-ZONGSHUDING4-EBAY-OFFICIAL-P-TEST",
        r"zongshuding4\s+eBay\s+official\s+packet",
        r"zongshuding4\s+eBay\s+Official\s+Packet",
        r"zongshuding4\s+eBay官方数据包",
        r"zongshuding4\s+eBay\s+官方数据包",
    ]
    for pattern in phrase_patterns:
        text = re.sub(pattern, SAFE_LABEL, text, flags=re.IGNORECASE)
    # Do not rewrite email addresses, URLs, ids, or other account identifiers.
    text = text.replace("PENDING-SKU-FROM-OFFICIAL-PACKET", SAFE_LABEL)
    return re.sub(r"(?<![A-Za-z0-9_@.-])zongshuding4(?![A-Za-z0-9_@.-])", SAFE_LABEL, text, flags=re.IGNORECASE)


def sanitize_json(value: Any) -> Any:
    if isinstance(value, str):
        return sanitize_text(value)
    if isinstance(value, list):
        return [sanitize_json(item) for item in value]
    if isinstance(value, dict):
        return {key: sanitize_json(item) for key, item in value.items()}
    return value


def load_json_field(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if value is None:
        return {}
    try:
        return json.loads(str(value))
    except json.JSONDecodeError:
        return {}


def dump_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def changed(before: Any, after: Any) -> bool:
    return json.dumps(before, ensure_ascii=False, sort_keys=True) != json.dumps(after, ensure_ascii=False, sort_keys=True)


def main() -> None:
    repo = SaaSRepository(Path(os.environ.get("JIEJING_SAAS_DB_PATH", "/data/saas.sqlite")))
    repo.initialize()
    counts = {
        "tasks": 0,
        "reports": 0,
        "merchant_memory": 0,
        "audit_logs": 0,
    }
    touched_task_ids: set[str] = set()
    touched_report_ids: set[str] = set()
    like = f"%{WRONG_LABEL}%"

    with repo._connect() as conn:  # Controlled staging maintenance; no secrets are selected.
        task_rows = conn.execute(
            """
            select task_id, title, input_json, output_json
            from tasks
            where task_type = ?
              and (lower(title) like ? or lower(cast(input_json as text)) like ? or lower(cast(output_json as text)) like ?)
            """,
            ("model_value_rehearsal", like, like, like),
        ).fetchall()
        for row in task_rows:
            task_id = str(row["task_id"])
            new_title = sanitize_text(str(row["title"]))
            input_json = load_json_field(row["input_json"])
            output_json = load_json_field(row["output_json"])
            new_input = sanitize_json(input_json)
            new_output = sanitize_json(output_json)
            if new_title != row["title"] or changed(input_json, new_input) or changed(output_json, new_output):
                conn.execute(
                    "update tasks set title = ?, input_json = ?, output_json = ?, updated_at = ? where task_id = ?",
                    (new_title, dump_json(new_input), dump_json(new_output), now_iso(), task_id),
                )
                touched_task_ids.add(task_id)
                counts["tasks"] += 1

        report_rows = conn.execute(
            """
            select report_id, task_id, report_type, title, report_json
            from reports
            where lower(title) like ? or lower(cast(report_json as text)) like ?
            """,
            (like, like),
        ).fetchall()
        for row in report_rows:
            report_id = str(row["report_id"])
            report_type = str(row["report_type"])
            report_json = load_json_field(row["report_json"])
            new_json = sanitize_json(report_json)
            if report_type == "market.report":
                new_title = "Market Report is blocked until a concrete SKU/product packet is selected."
            elif report_type == "listing.package":
                new_title = "Listing Package is blocked until concrete product facts and supplier materials are added."
            else:
                new_title = sanitize_text(str(row["title"]))
            if new_title != row["title"] or changed(report_json, new_json):
                conn.execute(
                    "update reports set title = ?, report_json = ? where report_id = ?",
                    (new_title, dump_json(new_json), report_id),
                )
                touched_report_ids.add(report_id)
                touched_task_ids.add(str(row["task_id"]))
                counts["reports"] += 1

        memory_rows = conn.execute(
            """
            select memory_id, source_id, title, summary, memory_json
            from merchant_memory
            where source_type = ?
              and (lower(title) like ? or lower(summary) like ? or lower(cast(memory_json as text)) like ?)
            """,
            ("report", like, like, like),
        ).fetchall()
        for row in memory_rows:
            memory_json = load_json_field(row["memory_json"])
            new_memory = sanitize_json(memory_json)
            new_title = sanitize_text(str(row["title"]))
            new_summary = sanitize_text(str(row["summary"]))
            if new_title != row["title"] or new_summary != row["summary"] or changed(memory_json, new_memory):
                conn.execute(
                    """
                    update merchant_memory
                    set title = ?, summary = ?, memory_json = ?, updated_at = ?
                    where memory_id = ?
                    """,
                    (new_title, new_summary, dump_json(new_memory), now_iso(), str(row["memory_id"])),
                )
                touched_report_ids.add(str(row["source_id"]))
                counts["merchant_memory"] += 1

        if touched_task_ids:
            audit_rows = conn.execute(
                """
                select audit_id, target_id, audit_json
                from audit_logs
                where target_type = ? and lower(cast(audit_json as text)) like ?
                """,
                ("task", like),
            ).fetchall()
            for row in audit_rows:
                if str(row["target_id"]) not in touched_task_ids:
                    continue
                audit_json = load_json_field(row["audit_json"])
                new_audit = sanitize_json(audit_json)
                if changed(audit_json, new_audit):
                    conn.execute(
                        "update audit_logs set audit_json = ? where audit_id = ?",
                        (dump_json(new_audit), str(row["audit_id"])),
                    )
                    counts["audit_logs"] += 1

    print(
        json.dumps(
            {
                "sanitized": counts,
                "touched_task_ids": sorted(touched_task_ids),
                "touched_report_ids": sorted(touched_report_ids),
                "secret_tables_touched": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
