#!/usr/bin/env python3
"""Crash-consistency contracts for the pre-provider media queue setup saga."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.repository import SaaSRepository  # noqa: E402


class MediaQueueSetupRecoveryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="jiejing-media-setup-recovery-", ignore_cleanup_errors=True)
        self.repository = SaaSRepository(Path(self.temp.name) / "saas.sqlite", database_engine="sqlite", database_url="")
        fixture = self.repository.create_user_with_company(
            email=f"setup-recovery-{id(self)}@example.test",
            password="local-test-password",
            company_name="Media setup recovery contract",
        )
        self.company_id = fixture["company"]["company_id"]
        self.user_id = fixture["user"]["user_id"]

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _prepared_setup(self) -> tuple[dict, dict, dict, str]:
        store = self.repository.create_store(
            company_id=self.company_id,
            user_id=self.user_id,
            payload={"platform": "ebay", "store_name": "crash recovery", "marketplace": "EBAY_US"},
        )
        self.repository.apply_media_credit_operation(
            company_id=self.company_id,
            user_id=self.user_id,
            operation_type="grant",
            points=320,
            idempotency_key="setup-recovery-grant-v1",
            reference_type="test_fixture",
            reference_id="setup-recovery",
            details={"credit_source": "purchased", "source_reference_id": "setup-recovery"},
        )
        idempotency_key = "setup-recovery-media-job-v1"
        reserved = self.repository.apply_media_credit_operation(
            company_id=self.company_id,
            user_id=self.user_id,
            operation_type="reserve",
            points=320,
            idempotency_key=f"{idempotency_key}:reserve:v1",
            reference_type="media_job",
            reference_id=idempotency_key,
        )
        task = self.repository.create_task(
            company_id=self.company_id,
            store_id=store["store_id"],
            user_id=self.user_id,
            task_type="provider_job",
            title="Crash before queue activation",
            input_data={"provider_job_key": "media.asset_generation"},
        )
        media_job = self.repository.create_media_asset_job(
            company_id=self.company_id,
            store_id=store["store_id"],
            task_id=task["task_id"],
            user_id=self.user_id,
            provider_job_key="media.asset_generation",
            idempotency_key=idempotency_key,
            job_spec={"media_credits": {"reservation": reserved}},
            status="pending",
        )
        queue = self.repository.create_queue_job(
            company_id=self.company_id,
            task_id=task["task_id"],
            max_attempts=1,
            initial_status="preparing",
            publish=False,
            job_data={
                "kind": "provider_job",
                "provider_job_key": "media.asset_generation",
                "media_job_id": media_job["media_job_id"],
                "idempotency_key": idempotency_key,
                "queue_setup_protocol": "media_queue_saga_v1",
                "setup_committed": False,
                "media_credits": {
                    "enforcement_enabled": True,
                    "quote": {"estimated_points": 320, "points_per_image": 80, "image_count": 4},
                    "reservation": reserved,
                },
                "live_provider_called": False,
            },
        )
        media_job = self.repository.update_media_asset_job(
            company_id=self.company_id,
            media_job_id=media_job["media_job_id"],
            status="queued",
            queue_job_id=queue["job_id"],
        )
        return task, media_job, queue, str(reserved["ledger_entry"]["ledger_id"])

    def _make_queue_stale(self, queue_id: str) -> None:
        with self.repository._connect() as conn:  # noqa: SLF001 - isolated contract fixture
            conn.execute(
                "update queue_jobs set updated_at = ? where job_id = ? and company_id = ?",
                ("2020-01-01T00:00:00+00:00", queue_id, self.company_id),
            )

    def _reserve_stale_orphan(
        self,
        *,
        reference_id: str,
        reference_type: str = "media_job",
        points: int = 80,
        details: dict | None = None,
    ) -> dict:
        self.repository.apply_media_credit_operation(
            company_id=self.company_id,
            user_id=self.user_id,
            operation_type="grant",
            points=points,
            idempotency_key=f"{reference_id}:grant:v1",
            reference_type="test_fixture",
            reference_id=reference_id,
            details={"credit_source": "purchased", "source_reference_id": reference_id},
        )
        reserved = self.repository.apply_media_credit_operation(
            company_id=self.company_id,
            user_id=self.user_id,
            operation_type="reserve",
            points=points,
            idempotency_key=f"{reference_id}:reserve:v1",
            reference_type=reference_type,
            reference_id=reference_id,
            details=details or {},
        )
        reservation_id = str(reserved["ledger_entry"]["ledger_id"])
        with self.repository._connect() as conn:  # noqa: SLF001 - isolated contract fixture
            conn.execute(
                "update media_credit_ledger set created_at = ?, updated_at = ? where company_id = ? and ledger_id = ?",
                ("2020-01-01T00:00:00+00:00", "2020-01-01T00:00:00+00:00", self.company_id, reservation_id),
            )
        return reserved

    def test_watchdog_releases_stale_preparing_setup_and_never_makes_it_claimable(self) -> None:
        task, media_job, queue, reservation_id = self._prepared_setup()
        self._make_queue_stale(queue["job_id"])

        before = self.repository.queue_health_summary(company_id=self.company_id, stale_after_seconds=30)
        self.assertEqual("attention_required", before["status"])
        self.assertEqual(1, before["stale_setup_count"])

        result = self.repository.recover_stale_queue_jobs(
            company_id=self.company_id,
            stale_after_seconds=30,
        )

        setup = result["stale_setup_recovery"]
        self.assertEqual("completed", setup["status"])
        self.assertEqual(1, setup["recovered_count"])
        self.assertEqual(0, setup["manual_reconcile_count"])
        self.assertEqual(
            "failed",
            self.repository.get_queue_job(job_id=queue["job_id"], company_id=self.company_id)["status"],
        )
        self.assertIsNone(
            self.repository.claim_next_queue_job(company_id=self.company_id, job_id=queue["job_id"])
        )
        self.assertEqual(
            "failed",
            self.repository.get_task(company_id=self.company_id, task_id=task["task_id"])["status"],
        )
        self.assertEqual(
            "needs_rework",
            self.repository.get_media_asset_job(
                company_id=self.company_id,
                media_job_id=media_job["media_job_id"],
            )["status"],
        )
        terminal = self.repository.get_media_credit_terminal_for_reservation(
            company_id=self.company_id,
            reservation_id=reservation_id,
        )
        self.assertEqual("release", terminal["operation_type"])
        self.assertEqual(0, self.repository.get_media_credit_account(company_id=self.company_id)["reserved_points"])

    def test_compensation_can_resume_after_metadata_write_crash_without_double_release(self) -> None:
        _task, _media_job, queue, reservation_id = self._prepared_setup()
        self._make_queue_stale(queue["job_id"])
        original_update = self.repository.update_media_asset_job
        with patch.object(self.repository, "update_media_asset_job", side_effect=RuntimeError("injected metadata crash")):
            first = self.repository.recover_stale_queue_jobs(
                company_id=self.company_id,
                stale_after_seconds=30,
            )
        self.assertEqual(1, first["stale_setup_recovery"]["manual_reconcile_count"])
        self.assertEqual(
            "compensating",
            self.repository.get_queue_job(job_id=queue["job_id"], company_id=self.company_id)["status"],
        )
        self._make_queue_stale(queue["job_id"])
        with patch.object(self.repository, "update_media_asset_job", wraps=original_update):
            second = self.repository.recover_stale_queue_jobs(
                company_id=self.company_id,
                stale_after_seconds=30,
            )
        self.assertEqual(1, second["stale_setup_recovery"]["recovered_count"])
        terminals = [
            entry
            for entry in self.repository.list_media_credit_ledger(company_id=self.company_id, limit=100)
            if entry.get("reservation_id") == reservation_id
            and entry.get("operation_type") in {"release", "settle"}
        ]
        self.assertEqual(["release"], [entry["operation_type"] for entry in terminals])

    def test_fresh_preparing_setup_is_not_reaped(self) -> None:
        _task, _media_job, queue, reservation_id = self._prepared_setup()
        result = self.repository.recover_stale_queue_jobs(
            company_id=self.company_id,
            stale_after_seconds=30,
        )
        self.assertEqual(0, result["stale_setup_recovery"]["recovered_count"])
        self.assertEqual(
            "preparing",
            self.repository.get_queue_job(job_id=queue["job_id"], company_id=self.company_id)["status"],
        )
        self.assertIsNone(
            self.repository.get_media_credit_terminal_for_reservation(
                company_id=self.company_id,
                reservation_id=reservation_id,
            )
        )

    def test_dispatch_uncertain_is_never_reported_as_healthy(self) -> None:
        store = self.repository.create_store(
            company_id=self.company_id,
            user_id=self.user_id,
            payload={"platform": "ebay", "store_name": "dispatch uncertainty", "marketplace": "EBAY_US"},
        )
        task = self.repository.create_task(
            company_id=self.company_id,
            store_id=store["store_id"],
            user_id=self.user_id,
            task_type="provider_job",
            title="Unknown Redis publish outcome",
            input_data={"provider_job_key": "media.asset_generation"},
        )
        queue = self.repository.create_queue_job(
            company_id=self.company_id,
            task_id=task["task_id"],
            max_attempts=1,
            publish=False,
            job_data={"kind": "provider_job"},
        )
        self.repository.update_queue_job(
            job_id=queue["job_id"],
            company_id=self.company_id,
            status="dispatch_uncertain",
        )
        tenant_health = self.repository.queue_health_summary(company_id=self.company_id)
        global_health = self.repository.global_queue_health_summary()
        self.assertEqual("attention_required", tenant_health["status"])
        self.assertTrue(tenant_health["dispatch_uncertain_requires_manual_reconcile"])
        self.assertEqual("attention_required", global_health["status"])
        self.assertTrue(global_health["dispatch_uncertain_requires_manual_reconcile"])

    def test_watchdog_releases_bare_stale_reserve_and_same_logical_key_gets_new_attempt(self) -> None:
        reference_id = "orphan-media-job-logical-key-v1"
        first = self._reserve_stale_orphan(reference_id=reference_id)
        first_reservation_id = str(first["ledger_entry"]["ledger_id"])

        recovery = self.repository.recover_stale_queue_jobs(
            company_id=self.company_id,
            stale_after_seconds=30,
        )["stale_setup_recovery"]["orphan_reservation_recovery"]

        self.assertEqual("completed", recovery["status"])
        self.assertEqual(1, recovery["recovered_count"])
        self.assertEqual(False, recovery["provider_call_triggered"])
        terminal = self.repository.get_media_credit_terminal_for_reservation(
            company_id=self.company_id,
            reservation_id=first_reservation_id,
        )
        self.assertEqual("release", terminal["operation_type"])
        self.assertEqual(0, self.repository.get_media_credit_account(company_id=self.company_id)["reserved_points"])

        retry_operation_key = self.repository.media_credit_reservation_attempt_idempotency_key(
            company_id=self.company_id,
            reference_type="media_job",
            reference_id=reference_id,
            base_idempotency_key=f"{reference_id}:reserve:v1",
        )
        self.assertNotEqual(f"{reference_id}:reserve:v1", retry_operation_key)
        second = self.repository.apply_media_credit_operation(
            company_id=self.company_id,
            user_id=self.user_id,
            operation_type="reserve",
            points=80,
            idempotency_key=retry_operation_key,
            reference_type="media_job",
            reference_id=reference_id,
        )
        self.assertFalse(second["duplicate_request"])
        self.assertNotEqual(first_reservation_id, second["ledger_entry"]["ledger_id"])
        self.assertEqual(
            retry_operation_key,
            self.repository.media_credit_reservation_attempt_idempotency_key(
                company_id=self.company_id,
                reference_type="media_job",
                reference_id=reference_id,
                base_idempotency_key=f"{reference_id}:reserve:v1",
            ),
        )

    def test_watchdog_never_releases_reservation_linked_to_any_queue_state(self) -> None:
        # Any persisted queue row is non-orphan evidence.  In particular,
        # dispatch_uncertain may already be published to Redis; failed and
        # dead-letter rows also require their own saga/manual reconciliation.
        for queue_status in ("queued", "running", "completed", "dispatch_uncertain", "failed", "dead_letter"):
            with self.subTest(queue_status=queue_status):
                reference_id = f"orphan-protected-{queue_status}-v1"
                reserved = self._reserve_stale_orphan(reference_id=reference_id)
                reservation_id = str(reserved["ledger_entry"]["ledger_id"])
                store = self.repository.create_store(
                    company_id=self.company_id,
                    user_id=self.user_id,
                    payload={
                        "platform": "ebay",
                        "store_name": f"protected {queue_status}",
                        "marketplace": "EBAY_US",
                    },
                )
                task = self.repository.create_task(
                    company_id=self.company_id,
                    store_id=store["store_id"],
                    user_id=self.user_id,
                    task_type="provider_job",
                    title=f"Protected {queue_status}",
                    input_data={"media_asset_idempotency_key": reference_id},
                )
                queue = self.repository.create_queue_job(
                    company_id=self.company_id,
                    task_id=task["task_id"],
                    max_attempts=1,
                    publish=False,
                    job_data={
                        "kind": "provider_job",
                        "idempotency_key": reference_id,
                        "media_credits": {"reservation": reserved},
                    },
                )
                if queue_status == "completed":
                    self.repository.create_media_asset_job(
                        company_id=self.company_id,
                        store_id=store["store_id"],
                        task_id=task["task_id"],
                        user_id=self.user_id,
                        provider_job_key="media.asset_generation",
                        idempotency_key=reference_id,
                        job_spec={"media_credits": {"reservation": reserved}},
                        queue_job_id=queue["job_id"],
                        status="provider_returned",
                    )
                if queue_status != "queued":
                    self.repository.update_queue_job(
                        job_id=queue["job_id"],
                        company_id=self.company_id,
                        status=queue_status,
                    )

                self.repository.recover_stale_queue_jobs(
                    company_id=self.company_id,
                    stale_after_seconds=30,
                )

                self.assertIsNone(
                    self.repository.get_media_credit_terminal_for_reservation(
                        company_id=self.company_id,
                        reservation_id=reservation_id,
                    )
                )

    def test_watchdog_requires_manual_reconcile_for_task_or_media_without_queue(self) -> None:
        task_reference = "partial-setup-task-only-v1"
        media_reference = "partial-setup-media-only-v1"
        task_reservation = self._reserve_stale_orphan(reference_id=task_reference)
        media_reservation = self._reserve_stale_orphan(reference_id=media_reference)
        store = self.repository.create_store(
            company_id=self.company_id,
            user_id=self.user_id,
            payload={"platform": "ebay", "store_name": "partial setup", "marketplace": "EBAY_US"},
        )
        self.repository.create_task(
            company_id=self.company_id,
            store_id=store["store_id"],
            user_id=self.user_id,
            task_type="provider_job",
            title="Task persisted before crash",
            input_data={"media_asset_idempotency_key": task_reference},
        )
        media_task = self.repository.create_task(
            company_id=self.company_id,
            store_id=store["store_id"],
            user_id=self.user_id,
            task_type="provider_job",
            title="Media record persisted before crash",
            input_data={"provider_job_key": "media.asset_generation"},
        )
        self.repository.create_media_asset_job(
            company_id=self.company_id,
            store_id=store["store_id"],
            task_id=media_task["task_id"],
            user_id=self.user_id,
            provider_job_key="media.asset_generation",
            idempotency_key=media_reference,
            job_spec={"media_credits": {"reservation": media_reservation}},
            status="pending",
        )

        recovery = self.repository.recover_stale_queue_jobs(
            company_id=self.company_id,
            stale_after_seconds=30,
        )["stale_setup_recovery"]["orphan_reservation_recovery"]

        self.assertEqual("attention_required", recovery["status"])
        self.assertEqual(0, recovery["recovered_count"])
        self.assertEqual(2, recovery["manual_reconcile_count"])
        self.assertEqual(
            {"stale_media_reservation_partial_setup_requires_reconcile"},
            {item["failure_code"] for item in recovery["manual_reconcile"]},
        )
        for reserved in (task_reservation, media_reservation):
            self.assertIsNone(
                self.repository.get_media_credit_terminal_for_reservation(
                    company_id=self.company_id,
                    reservation_id=str(reserved["ledger_entry"]["ledger_id"]),
                )
            )

    def test_watchdog_releases_stale_media_rework_reserve_and_clears_preparing_slot(self) -> None:
        parent_media_job_id = "media_job_parent_orphan_rework_v1"
        version = 2
        reference_id = "orphan-media-rework-logical-key-v2"
        slot = self.repository.reserve_media_rework(
            company_id=self.company_id,
            parent_media_job_id=parent_media_job_id,
            version=version,
            idempotency_key=reference_id,
        )
        self.assertTrue(slot["acquired"])
        reserved = self._reserve_stale_orphan(
            reference_id=reference_id,
            reference_type="media_rework",
            details={"parent_media_job_id": parent_media_job_id, "version": version},
        )
        reservation_id = str(reserved["ledger_entry"]["ledger_id"])
        with self.repository._connect() as conn:  # noqa: SLF001 - isolated contract fixture
            conn.execute(
                """
                update media_rework_reservations set expires_epoch = 0
                where company_id = ? and parent_media_job_id = ? and version = ?
                """,
                (self.company_id, parent_media_job_id, version),
            )

        first = self.repository.recover_stale_queue_jobs(
            company_id=self.company_id,
            stale_after_seconds=30,
        )["stale_setup_recovery"]["orphan_reservation_recovery"]
        second = self.repository.recover_stale_queue_jobs(
            company_id=self.company_id,
            stale_after_seconds=30,
        )["stale_setup_recovery"]["orphan_reservation_recovery"]

        self.assertEqual(1, first["recovered_count"])
        self.assertEqual(0, second["recovered_count"])
        terminals = [
            entry
            for entry in self.repository.list_media_credit_ledger(company_id=self.company_id, limit=100)
            if entry.get("reservation_id") == reservation_id and entry.get("operation_type") == "release"
        ]
        self.assertEqual(1, len(terminals))
        retry_operation_key = self.repository.media_credit_reservation_attempt_idempotency_key(
            company_id=self.company_id,
            reference_type="media_rework",
            reference_id=reference_id,
            base_idempotency_key=f"{reference_id}:reserve:v1",
        )
        self.assertNotEqual(f"{reference_id}:reserve:v1", retry_operation_key)
        retried_credit = self.repository.apply_media_credit_operation(
            company_id=self.company_id,
            user_id=self.user_id,
            operation_type="reserve",
            points=80,
            idempotency_key=retry_operation_key,
            reference_type="media_rework",
            reference_id=reference_id,
            details={"parent_media_job_id": parent_media_job_id, "version": version},
        )
        self.assertFalse(retried_credit["duplicate_request"])
        self.assertNotEqual(reservation_id, retried_credit["ledger_entry"]["ledger_id"])
        reacquired = self.repository.reserve_media_rework(
            company_id=self.company_id,
            parent_media_job_id=parent_media_job_id,
            version=version,
            idempotency_key=reference_id,
        )
        self.assertTrue(reacquired["acquired"])


if __name__ == "__main__":
    unittest.main()
