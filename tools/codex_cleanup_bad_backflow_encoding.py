"""Remove the bad-encoding backflow workflow created by Codex.

This is intentionally scoped to one task_id created by the current operator
mistake. It does not touch stores, eBay connections, model secrets, packets, or
other merchant records.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from jiejing_saas.repository import SaaSRepository


BAD_TASK_ID = "task_b7e49e5c15a8051f"


def main() -> None:
    repo = SaaSRepository(
        Path(os.environ.get("JIEJING_SAAS_DB_PATH", "/data/saas.sqlite")),
        database_engine=os.environ.get("JIEJING_DATABASE_ENGINE", "sqlite"),
        database_url=os.environ.get("JIEJING_DATABASE_URL", ""),
    )
    repo.initialize()
    summary: dict[str, object] = {
        "task_id": BAD_TASK_ID,
        "deleted": {},
        "untouched": {
            "stores": True,
            "platform_connections": True,
            "secret_refs": True,
            "platform_data_packets": True,
        },
    }
    with repo._connect() as conn:  # noqa: SLF001 - controlled staging maintenance script.
        reports = conn.execute("select report_id from reports where task_id = ?", (BAD_TASK_ID,)).fetchall()
        confirmations = conn.execute("select confirmation_id from confirmations where task_id = ?", (BAD_TASK_ID,)).fetchall()
        jobs = conn.execute("select job_id from queue_jobs where task_id = ?", (BAD_TASK_ID,)).fetchall()
        report_ids = [row["report_id"] for row in reports]
        confirmation_ids = [row["confirmation_id"] for row in confirmations]
        job_ids = [row["job_id"] for row in jobs]
        source_ids = report_ids + confirmation_ids

        deleted_memory = 0
        if source_ids:
            placeholders = ",".join("?" for _ in source_ids)
            deleted_memory += conn.execute(
                f"delete from merchant_memory where source_id in ({placeholders})",
                tuple(source_ids),
            ).rowcount
        deleted_memory += conn.execute(
            "delete from merchant_memory where memory_json::text like ?",
            (f"%{BAD_TASK_ID}%",),
        ).rowcount

        deleted_audit = conn.execute(
            "delete from audit_logs where target_id = ? or audit_json::text like ?",
            (BAD_TASK_ID, f"%{BAD_TASK_ID}%"),
        ).rowcount
        for job_id in job_ids:
            deleted_audit += conn.execute(
                "delete from audit_logs where target_id = ? or audit_json::text like ?",
                (job_id, f"%{job_id}%"),
            ).rowcount

        summary["deleted"] = {
            "merchant_memory": deleted_memory,
            "audit_logs": deleted_audit,
            "confirmations": conn.execute("delete from confirmations where task_id = ?", (BAD_TASK_ID,)).rowcount,
            "reports": conn.execute("delete from reports where task_id = ?", (BAD_TASK_ID,)).rowcount,
            "task_steps": conn.execute("delete from task_steps where task_id = ?", (BAD_TASK_ID,)).rowcount,
            "queue_jobs": conn.execute("delete from queue_jobs where task_id = ?", (BAD_TASK_ID,)).rowcount,
            "tasks": conn.execute("delete from tasks where task_id = ?", (BAD_TASK_ID,)).rowcount,
        }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
