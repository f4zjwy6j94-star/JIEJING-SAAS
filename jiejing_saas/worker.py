"""Local worker for queued Jiejing SaaS tasks.

This is still a local MVP worker. It deliberately keeps real platform writes
disabled, but it separates "accept a merchant request" from "run Runtime work",
which is the shape we need before swapping SQLite/local queue for Redis or a
cloud queue.
"""

from __future__ import annotations

import os
from typing import Any

from jiejing_runtime.models import now_iso

from .config import SaaSSettings
from .ebay_data_packet import build_ebay_read_only_data_packet
from .ebay_http_client import EbayReadOnlyHttpClient
from .ebay_read_adapter import EbayReadOnlyAdapter
from .provider_job_runner import ProviderJobRunner
from .repository import SaaSRepository
from .runtime_bridge import RuntimeBridge


class LocalQueueWorker:
    def __init__(self, *, repository: SaaSRepository, runtime_bridge: RuntimeBridge, settings: SaaSSettings | None = None) -> None:
        self.repository = repository
        self.runtime_bridge = runtime_bridge
        self.settings = settings
        self.provider_job_runner = ProviderJobRunner(settings=settings)
        self.process_started_at = now_iso()

    def run_next(self, *, company_id: str | None = None, job_id: str | None = None) -> dict[str, Any]:
        worker_id = self._worker_id()
        self._record_worker_heartbeat(worker_id=worker_id, status="polling", details={"company_id": company_id or "", "job_id": job_id or ""})
        job = self.repository.claim_next_queue_job(company_id=company_id, job_id=job_id)
        if not job:
            self._record_worker_heartbeat(worker_id=worker_id, status="idle", details={"company_id": company_id or "", "job_id": job_id or ""})
            return {
                "status": "idle",
                "message": "No queued SaaS job is waiting for the local worker.",
                "real_platform_writes_enabled": False,
            }
        return self.run_claimed_job(job)

    def run_claimed_job(self, job: dict[str, Any]) -> dict[str, Any]:
        worker_id = self._worker_id()
        self._record_worker_heartbeat(
            worker_id=worker_id,
            status="running",
            current_job_id=job.get("job_id"),
            details={"company_id": job.get("company_id"), "task_id": job.get("task_id")},
        )
        self.repository.heartbeat_queue_job(
            job_id=job["job_id"],
            company_id=job["company_id"],
            worker_id=worker_id,
        )
        task: dict[str, Any] = {
            "task_id": job.get("task_id"),
            "company_id": job.get("company_id"),
        }
        try:
            task = self.repository.get_task(company_id=job["company_id"], task_id=job["task_id"])
            if not task:
                failed_job = self.repository.update_queue_job(
                    job_id=job["job_id"],
                    company_id=job["company_id"],
                    status="failed",
                    details={"error": "Task not found for claimed queue job."},
                )
                return {
                    "status": "failed",
                    "queue_job": failed_job,
                    "error": "Task not found for claimed queue job.",
                    "real_platform_writes_enabled": False,
                }

            body = task.get("input") if isinstance(task.get("input"), dict) else {}
            job_body = job.get("job") if isinstance(job.get("job"), dict) else {}
            if job_body.get("kind") == "ebay_read_only_live_plan":
                return self._run_ebay_read_only_live_plan_job(job=job, task=task, job_body=job_body)
            if job_body.get("kind") == "provider_job":
                return self._run_provider_job(job=job, task=task, job_body=job_body)
            self.repository.update_task_status(
                task_id=task["task_id"],
                company_id=task["company_id"],
                status="running",
                audit_summary="Local worker started SaaS task execution.",
            )
            self.repository.mark_task_steps_running(task_id=task["task_id"], company_id=task["company_id"])
            runtime_result = self.runtime_bridge.run_product_workflow(
                task_id=task["task_id"],
                user_id=task["user_id"],
                company_id=task["company_id"],
                store_id=task["store_id"],
                body=body,
            )
            completed_task = self.repository.complete_task_from_runtime(
                task_id=task["task_id"],
                company_id=task["company_id"],
                runtime_result=runtime_result,
            )
            saved = self.repository.save_runtime_outputs(task=completed_task, runtime_result=runtime_result)
            steps = self.repository.list_task_steps(company_id=task["company_id"], task_id=task["task_id"])
            completed_job = self.repository.update_queue_job(
                job_id=job["job_id"],
                company_id=job["company_id"],
                status="completed",
                details={
                    "runtime_run_id": saved["runtime_run_id"],
                    "reports": saved["reports"],
                    "confirmations": saved["confirmations"],
                    "steps": len(steps),
                },
            )
            return {
                "status": "completed",
                "task": completed_task,
                "queue_job": completed_job,
                "steps": steps,
                "runtime": {
                    "run_id": runtime_result["run_id"],
                    "run": runtime_result["run"],
                    "validation_summary": runtime_result["validation_summary"],
                    "saas_snapshot": runtime_result["saas_snapshot"],
                    "runtime_output_dir": runtime_result["runtime_output_dir"],
                },
                "saved": saved,
                "real_platform_writes_enabled": False,
            }
        except Exception as exc:  # pragma: no cover - defensive worker boundary
            message = str(exc)
            task_id = str(task.get("task_id") or job.get("task_id") or "")
            company_id = str(task.get("company_id") or job.get("company_id") or "")
            self.repository.update_task_status(
                task_id=task_id,
                company_id=company_id,
                status="failed",
                output={"error": message, "failed_by": "local_queue_worker"},
                audit_summary="Local worker failed. SaaS backend surfaced the failure instead of silently hanging.",
            )
            self.repository.mark_task_steps_failed(task_id=task_id, company_id=company_id, error=message)
            failed_job = self.repository.update_queue_job(
                job_id=job["job_id"],
                company_id=job["company_id"],
                status="failed",
                details={"error": message},
            )
            return {
                "status": "failed",
                "task": self.repository.get_task(company_id=company_id, task_id=task_id),
                "queue_job": failed_job,
                "steps": self.repository.list_task_steps(company_id=company_id, task_id=task_id),
                "error": message,
                "real_platform_writes_enabled": False,
            }
        finally:
            self._record_worker_heartbeat(
                worker_id=worker_id,
                status="idle",
                details={"last_job_id": job.get("job_id"), "company_id": job.get("company_id"), "task_id": job.get("task_id")},
            )

    def _worker_id(self) -> str:
        configured = os.environ.get("JIEJING_WORKER_ID")
        if configured:
            return configured
        if self.settings and self.settings.is_production_like:
            return os.environ.get("JIEJING_WORKER_SLOT") or "jiejing-worker:default"
        return f"local_worker:{os.getpid()}"

    def _record_worker_heartbeat(
        self,
        *,
        worker_id: str,
        status: str,
        current_job_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        try:
            self.repository.record_worker_heartbeat(
                worker_id=worker_id,
                status=status,
                queue_provider=self.settings.queue_provider if self.settings else os.environ.get("JIEJING_QUEUE_PROVIDER", "local_worker"),
                current_job_id=current_job_id,
                process_started_at=self.process_started_at,
                process_id=os.getpid(),
                details=details or {},
            )
        except Exception:
            # Worker heartbeat must never mask queue execution or recovery.
            return

    def _run_ebay_read_only_live_plan_job(
        self,
        *,
        job: dict[str, Any],
        task: dict[str, Any],
        job_body: dict[str, Any],
    ) -> dict[str, Any]:
        self.repository.update_task_status(
            task_id=task["task_id"],
            company_id=task["company_id"],
            status="running",
            audit_summary="Local worker started eBay read-only live-plan job.",
        )
        live_read_plan = job_body.get("live_read_plan") if isinstance(job_body.get("live_read_plan"), dict) else {}
        if self.settings and live_read_plan.get("status") == "ready_to_queue_live_read_job":
            store = self.repository.get_store_for_company(company_id=task["company_id"], store_id=task["store_id"]) or {}
            live_result = EbayReadOnlyHttpClient(self.settings).execute_live_read(
                live_read_plan=live_read_plan,
                request_context={
                    **(task.get("input") if isinstance(task.get("input"), dict) else {}),
                    "store_id": task["store_id"],
                    "product": str((task.get("input") or {}).get("product") or store.get("store_name") or "eBay product"),
                },
            )
            packet_record = None
            if live_result.get("live_read_performed"):
                resources_requested = live_read_plan.get("resources_requested") if isinstance(live_read_plan.get("resources_requested"), list) else None
                resource_catalog = EbayReadOnlyAdapter(self.settings)._select_resources(resources_requested)
                probe_plan = {
                    "status": "read_only_live_completed",
                    "platform": "ebay",
                    "company_id": task["company_id"],
                    "store_id": task["store_id"],
                    "store_name": store.get("store_name"),
                    "marketplace": store.get("marketplace") or live_read_plan.get("marketplace") or "EBAY_US",
                    "user_id": task["user_id"],
                    "resources_requested": live_read_plan.get("resources_requested") or [],
                    "resources": resource_catalog,
                    "resource_count": len(resource_catalog),
                    "request_count": live_result.get("request_count", 0),
                    "route_results": live_result.get("route_results") if isinstance(live_result.get("route_results"), list) else [],
                    "blocked_by": [],
                    "live_read_performed": True,
                    "access_token_used": bool(live_result.get("access_token_used")),
                    "access_token_returned_to_frontend": False,
                    "raw_ebay_response_stored": False,
                    "real_platform_writes_enabled": False,
                    "secret_exposed": False,
                }
                packet = build_ebay_read_only_data_packet(
                    company_id=task["company_id"],
                    store=store,
                    user_id=task["user_id"],
                    probe_plan=probe_plan,
                    source_mode="official_api",
                    sample_payload=live_result.get("sample_payload") if isinstance(live_result.get("sample_payload"), dict) else {},
                )
                packet_record = self.repository.create_platform_data_packet(
                    company_id=task["company_id"],
                    store_id=task["store_id"],
                    user_id=task["user_id"],
                    packet=packet,
                )
            output = {
                "status": "completed_official_read" if live_result.get("live_read_performed") else "completed_no_live_read",
                "summary": "eBay read-only job ran through the backend HTTP client. No write API was called and no raw response or token was persisted.",
                "live_read_plan": live_read_plan,
                "live_read_result": live_result,
                "data_packet_id": packet_record.get("packet_id") if packet_record else None,
                "live_read_performed": bool(live_result.get("live_read_performed")),
                "real_platform_writes_enabled": False,
                "secret_exposed": False,
            }
            completed_task = self.repository.update_task_status(
                task_id=task["task_id"],
                company_id=task["company_id"],
                status="completed",
                output=output,
                audit_summary="eBay read-only live job completed through backend HTTP client.",
            )
            completed_job = self.repository.update_queue_job(
                job_id=job["job_id"],
                company_id=job["company_id"],
                status="completed",
                details={
                    "kind": "ebay_read_only_live_plan",
                    "live_read_performed": bool(live_result.get("live_read_performed")),
                    "request_count": live_result.get("request_count", 0),
                    "data_packet_id": packet_record.get("packet_id") if packet_record else None,
                    "secret_exposed": False,
                },
            )
            self.repository.write_audit(
                company_id=task["company_id"],
                store_id=task["store_id"],
                user_id=task["user_id"],
                actor_type="system",
                action_type="ebay.read_only.live.completed",
                target_type="queue_job",
                target_id=job["job_id"],
                summary="eBay read-only live job completed. Tokens and raw responses were not persisted.",
                details={
                    "request_count": live_result.get("request_count", 0),
                    "data_packet_id": packet_record.get("packet_id") if packet_record else None,
                    "access_token_returned_to_frontend": False,
                    "access_token_returned_to_runtime": False,
                    "raw_response_stored": False,
                    "real_platform_writes_enabled": False,
                    "secret_exposed": False,
                },
            )
            return {
                "status": "completed",
                "task": completed_task,
                "queue_job": completed_job,
                "steps": [],
                "runtime": None,
                "saved": {"reports": 0, "confirmations": 0, "data_packets": 1 if packet_record else 0},
                "live_read_plan": live_read_plan,
                "live_read_result": live_result,
                "data_packet": packet_record,
                "real_platform_writes_enabled": False,
            }
        output = {
            "status": "completed_no_live_read",
            "summary": "eBay read-only live-plan job completed as a contract check. No token was read and no eBay HTTP request was performed.",
            "live_read_plan": live_read_plan,
            "live_read_performed": False,
            "real_platform_writes_enabled": False,
            "secret_exposed": False,
        }
        completed_task = self.repository.update_task_status(
            task_id=task["task_id"],
            company_id=task["company_id"],
            status="completed",
            output=output,
            audit_summary="eBay read-only live-plan job completed without live API calls.",
        )
        completed_job = self.repository.update_queue_job(
            job_id=job["job_id"],
            company_id=job["company_id"],
            status="completed",
            details={
                "kind": "ebay_read_only_live_plan",
                "live_read_performed": False,
                "route_request_count": live_read_plan.get("route_request_count"),
            },
        )
        return {
            "status": "completed",
            "task": completed_task,
            "queue_job": completed_job,
            "steps": [],
            "runtime": None,
            "saved": {"reports": 0, "confirmations": 0},
            "live_read_plan": live_read_plan,
            "real_platform_writes_enabled": False,
        }

    def _run_provider_job(
        self,
        *,
        job: dict[str, Any],
        task: dict[str, Any],
        job_body: dict[str, Any],
    ) -> dict[str, Any]:
        self.repository.update_task_status(
            task_id=task["task_id"],
            company_id=task["company_id"],
            status="running",
            audit_summary="Local worker started provider job contract dry-run.",
        )
        provider_output = self.provider_job_runner.run(
            company_id=task["company_id"],
            store_id=task["store_id"],
            user_id=task["user_id"],
            task_id=task["task_id"],
            job_id=job["job_id"],
            job_body=job_body,
        )
        safety = provider_output.get("safety") if isinstance(provider_output.get("safety"), dict) else {}
        live_provider_called = bool(safety.get("live_provider_called"))
        raw_secret_read = bool(safety.get("raw_secret_read"))
        action_type = "provider_job.live_read.completed" if live_provider_called else "provider_job.dry_run.completed"
        audit_summary = (
            "Provider job live read completed through a backend adapter. No raw provider response or secret was persisted."
            if live_provider_called
            else "Provider job contract dry-run completed without live external calls."
        )
        completed_task = self.repository.update_task_status(
            task_id=task["task_id"],
            company_id=task["company_id"],
            status="completed",
            output=provider_output,
            audit_summary=audit_summary,
        )
        completed_job = self.repository.update_queue_job(
            job_id=job["job_id"],
            company_id=job["company_id"],
            status="completed",
            details={
                "kind": "provider_job",
                "provider_job_key": provider_output.get("provider_job_key"),
                "provider_family": provider_output.get("provider_family"),
                "provider_status": provider_output.get("status"),
                "missing_inputs": provider_output.get("missing_inputs", []),
                "live_provider_called": live_provider_called,
                "raw_secret_read": raw_secret_read,
                "secret_exposed": False,
            },
        )
        self.repository.write_audit(
            company_id=task["company_id"],
            store_id=task["store_id"],
            user_id=task["user_id"],
            actor_type="system",
            action_type=action_type,
            target_type="queue_job",
            target_id=job["job_id"],
            summary=audit_summary,
            details={
                "provider_job_key": provider_output.get("provider_job_key"),
                "provider_family": provider_output.get("provider_family"),
                "status": provider_output.get("status"),
                "missing_inputs": provider_output.get("missing_inputs", []),
                "live_provider_called": live_provider_called,
                "raw_secret_read": raw_secret_read,
                "raw_provider_response_stored": False,
                "secret_exposed": False,
            },
        )
        return {
            "status": "completed",
            "task": completed_task,
            "queue_job": completed_job,
            "steps": [],
            "runtime": None,
            "saved": {"reports": 0, "confirmations": 0, "provider_jobs": 1},
            "provider_job": provider_output,
            "real_platform_writes_enabled": False,
        }
