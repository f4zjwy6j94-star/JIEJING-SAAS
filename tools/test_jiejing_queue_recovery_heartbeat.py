#!/usr/bin/env python3
"""Regression checks for queue heartbeat, stale recovery, and dead letters."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.repository import SaaSRepository  # noqa: E402


OUT = ROOT / "output" / "jiejing-queue-recovery-heartbeat-test"
DB = OUT / "saas.sqlite"


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    if DB.exists():
        DB.unlink()

    repository = SaaSRepository(DB, database_engine="sqlite")
    account = repository.create_user_with_company(
        email="queue-recovery@example.com",
        password="unit-test-password",
        company_name="Queue Recovery Test",
    )
    user = account["user"]
    company = account["company"]
    store = repository.create_store(
        company_id=company["company_id"],
        user_id=user["user_id"],
        payload={"platform": "ebay", "store_name": "Queue Recovery Store", "marketplace": "EBAY_US"},
    )
    task = repository.create_task(
        company_id=company["company_id"],
        store_id=store["store_id"],
        user_id=user["user_id"],
        task_type="market_report",
        title="Queue recovery heartbeat test",
        input_data={"source": "unit_test"},
    )
    job = repository.create_queue_job(
        company_id=company["company_id"],
        task_id=task["task_id"],
        job_data={"kind": "workflow_task", "task_id": task["task_id"], "run_mode": "queued"},
        max_attempts=2,
    )

    claimed = repository.claim_next_queue_job(company_id=company["company_id"])
    if not claimed or claimed["job_id"] != job["job_id"] or claimed["attempts"] != 1:
        return fail(f"queued job should be claimable once: {claimed}")

    heartbeat = repository.heartbeat_queue_job(
        job_id=job["job_id"],
        company_id=company["company_id"],
        worker_id="unit-test-worker",
        lease_seconds=60,
    )
    if heartbeat.get("job", {}).get("worker_heartbeat", {}).get("worker_id") != "unit-test-worker":
        return fail(f"running job should record worker heartbeat: {heartbeat}")

    fresh_health = repository.queue_health_summary(company_id=company["company_id"], stale_after_seconds=30)
    if fresh_health.get("status") != "ready" or fresh_health.get("stale_running_count") != 0:
        return fail(f"fresh heartbeat should keep queue healthy: {fresh_health}")

    _force_stale(repository, job_id=job["job_id"], company_id=company["company_id"])
    first_recovery = repository.recover_stale_queue_jobs(company_id=company["company_id"], stale_after_seconds=30)
    if first_recovery.get("recovered_count") != 1 or first_recovery.get("dead_letter_count") != 0:
        return fail(f"first stale run should requeue job: {first_recovery}")
    requeued = repository.get_queue_job(job_id=job["job_id"], company_id=company["company_id"])
    if not requeued or requeued["status"] != "queued" or requeued["attempts"] != 1:
        return fail(f"stale running job should return to queued before max attempts: {requeued}")

    second_claim = repository.claim_next_queue_job(company_id=company["company_id"])
    if not second_claim or second_claim["attempts"] != 2:
        return fail(f"recovered job should be claimable for second attempt: {second_claim}")
    repository.heartbeat_queue_job(
        job_id=job["job_id"],
        company_id=company["company_id"],
        worker_id="unit-test-worker",
        lease_seconds=60,
    )
    _force_stale(repository, job_id=job["job_id"], company_id=company["company_id"])
    second_recovery = repository.recover_stale_queue_jobs(company_id=company["company_id"], stale_after_seconds=30)
    if second_recovery.get("recovered_count") != 0 or second_recovery.get("dead_letter_count") != 1:
        return fail(f"exhausted stale job should move to dead letter: {second_recovery}")

    dead = repository.get_queue_job(job_id=job["job_id"], company_id=company["company_id"])
    if not dead or dead["status"] != "dead_letter" or not dead.get("job", {}).get("dead_letter"):
        return fail(f"dead-letter state should be visible on the job: {dead}")

    final_health = repository.queue_health_summary(company_id=company["company_id"], stale_after_seconds=30)
    if final_health.get("status") != "attention_required" or final_health.get("counts", {}).get("dead_letter") != 1:
        return fail(f"dead letters should surface in queue health: {final_health}")
    if first_recovery.get("secret_exposed") is not False or final_health.get("secret_exposed") is not False:
        return fail("queue recovery and health responses must keep secret_exposed=false")

    print("PASS queue_recovery_heartbeat")
    return 0


def _force_stale(repository: SaaSRepository, *, job_id: str, company_id: str) -> None:
    stale_at = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    with repository._connect() as conn:  # noqa: SLF001 - targeted white-box regression for watchdog state.
        row = conn.execute(
            "select job_json from queue_jobs where job_id = ? and company_id = ?",
            (job_id, company_id),
        ).fetchone()
        if not row:
            raise AssertionError("queue job not found while forcing stale state")
        job_json = json.loads(row["job_json"])
        job_json["worker_heartbeat"] = {
            "worker_id": "unit-test-worker",
            "heartbeat_at": stale_at,
            "lease_seconds": 60,
        }
        conn.execute(
            "update queue_jobs set updated_at = ?, job_json = ? where job_id = ? and company_id = ?",
            (stale_at, json.dumps(job_json, ensure_ascii=False), job_id, company_id),
        )


if __name__ == "__main__":
    raise SystemExit(main())
