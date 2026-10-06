#!/usr/bin/env python3
"""Generation operations use real temporary storage and a local model boundary."""
from __future__ import annotations

import copy
from concurrent.futures import ThreadPoolExecutor
import sqlite3
import threading
import unittest
from unittest.mock import patch
import uuid

import test_jiejing_listing_buyer_copy_rewrite as rewrite_fixture
from jiejing_saas.listing_generation_operations import (
    build_listing_generation_operation, claim_listing_generation_operation, read_listing_generation_operation,
)
from jiejing_saas.listing_draft_generation import ListingDraftGenerationError


class ListingGenerationOperationTests(unittest.TestCase):
    setUp = rewrite_fixture.BuyerCopyRewriteTests.setUp
    generate = rewrite_fixture.BuyerCopyRewriteTests.generate

    def operation(self, **changes):
        values = dict(company_id=self.company_id, store_id=self.store["store_id"], user_id=self.user_id,
            operation_id=str(uuid.uuid4()), listing_project_identity=self.identity,
            merchant_product_fact_packet=self.packet,
            current_draft_fields={**self.fields, "merchant_edited_fields": self.edited},
            generation_mode="rewrite_buyer_copy", expected_base_report_id=self.base_report_id,
            expected_checkpoint_revision=1)
        values.update(changes)
        return build_listing_generation_operation(**values)

    def read(self, operation):
        return read_listing_generation_operation(self.repository, company_id=self.company_id,
            store_id=self.store["store_id"], user_id=self.user_id, operation_id=operation["operation_id"],
            listing_project_identity=self.identity)

    def test_same_operation_executes_once_and_readback_returns_its_exact_saved_report(self):
        operation = self.operation()
        claim = claim_listing_generation_operation(self.repository, operation=operation)
        self.assertTrue(claim["claimed"])
        self.assertEqual(self.read(operation)["status"], "running")
        generated = self.generate(generation_mode="rewrite_buyer_copy", operation_task=claim["task"])
        self.assertEqual(generated["status"], "completed")
        readback = self.read(operation)
        self.assertEqual(readback["status"], "report_saved")
        self.assertEqual(readback["report"]["report_id"], generated["report"]["report_id"])
        self.assertEqual(readback["report"]["user_id"], self.user_id)
        self.assertEqual(readback["listing_project_identity"], self.identity)
        task = self.repository.get_task(company_id=self.company_id, task_id=claim["task"]["task_id"])
        self.assertEqual(task["input"]["model_usage_owner"], "merchant_account_byok")
        self.assertEqual(task["input"]["provider_key"], "local_fixture")
        self.assertTrue(task["input"]["model_usage_required"])
        self.assertEqual(task["input"]["fingerprint"], operation["fingerprint"])
        self.assertFalse(readback["can_retry"])
        self.assertFalse(readback["real_platform_writes_enabled"])
        repeated = claim_listing_generation_operation(self.repository, operation=operation)
        self.assertFalse(repeated["claimed"])
        self.assertEqual(repeated["status"], "report_saved")
        replay = self.generate(generation_mode="rewrite_buyer_copy", operation_task=claim["task"])
        self.assertEqual(replay["status"], "report_saved")
        self.assertEqual(len(self.model.calls), 2)

    def test_operation_rejects_unrelated_payload_fields_before_creating_a_task(self):
        cases = [dict(merchant_product_fact_packet={**self.packet, "unrelated_private_note": "not product data"}),
                 dict(current_draft_fields={"title": "Tablet", "unrelated_private_note": "not listing data"},
                      generation_mode="preserve_merchant_edits", expected_base_report_id=None, expected_checkpoint_revision=None)]
        nested = copy.deepcopy(self.packet)
        nested["derived_listing_suggestions"]["unrelated_private_note"] = "not product data"
        cases.append(dict(merchant_product_fact_packet=nested))
        for changes in cases:
            with self.subTest(keys=sorted(changes)):
                with self.assertRaises(ValueError):
                    operation = self.operation(**changes)
                    claim_listing_generation_operation(self.repository, operation=operation)
        self.assertEqual(self.repository.list_tasks(company_id=self.company_id), self.original_tasks)
        self.assertEqual(self.model.calls, [])

    def test_same_operation_id_with_changed_input_conflicts_without_model_or_extra_task(self):
        operation = self.operation()
        claim_listing_generation_operation(self.repository, operation=operation)
        changed = self.operation(operation_id=operation["operation_id"],
            current_draft_fields={**self.fields, "title": "Changed title", "merchant_edited_fields": self.edited})
        before_tasks = self.repository.list_tasks(company_id=self.company_id)
        replay = claim_listing_generation_operation(self.repository, operation=changed)
        self.assertEqual(replay["status"], "conflict")
        self.assertFalse(replay["claimed"])
        self.assertFalse(replay["can_retry"])
        self.assertEqual(self.repository.list_tasks(company_id=self.company_id), before_tasks)
        self.assertEqual(self.model.calls, [])

    def test_parallel_claims_and_service_replays_have_only_one_model_executor(self):
        operation = self.operation()
        with ThreadPoolExecutor(max_workers=2) as pool:
            claims = list(pool.map(lambda _: claim_listing_generation_operation(self.repository, operation=operation), range(2)))
        self.assertEqual(sum(claim["claimed"] for claim in claims), 1)
        owner = next(claim for claim in claims if claim["claimed"])
        entered, release = threading.Event(), threading.Event()
        boundary = self.model.generate_text
        def held(**kwargs):
            entered.set()
            if not release.wait(5):
                raise AssertionError("local fixture model was not released")
            return boundary(**kwargs)
        self.model.generate_text = held
        with ThreadPoolExecutor(max_workers=1) as pool:
            work = pool.submit(self.generate, generation_mode="rewrite_buyer_copy", operation_task=owner["task"])
            try:
                self.assertTrue(entered.wait(5))
                replay = self.generate(generation_mode="rewrite_buyer_copy", operation_task=owner["task"])
                self.assertEqual(replay["status"], "running")
                self.assertFalse(replay["can_retry"])
            finally:
                release.set()
            self.assertEqual(work.result(timeout=5)["status"], "completed")
        self.assertEqual(len(self.model.calls), 2)

    def test_quality_failure_is_readable_as_known_pre_save_failure_and_old_fields_survive(self):
        operation = self.operation()
        claim = claim_listing_generation_operation(self.repository, operation=operation)
        self.model.output["description"] = "Titanium reinforced tablet stand."
        with self.assertRaises(ListingDraftGenerationError):
            self.generate(generation_mode="rewrite_buyer_copy", operation_task=claim["task"])
        view = self.read(operation)
        self.assertEqual(view["status"], "failed_before_report")
        self.assertTrue(view["can_retry"])
        self.assertTrue(view["model_called"])
        self.assertTrue(view["usage_consumed"])
        self.assertFalse(view["report_save_attempted"])
        self.assertIsNone(view["report"])
        self.assertEqual(len(self.model.calls), 2)
        self.assertEqual(self.repository.list_reports(company_id=self.company_id), self.original_reports)
        self.assertEqual(self.repository.get_listing_draft_checkpoint(company_id=self.company_id,
            store_id=self.store["store_id"], identity=self.identity)["checkpoint"]["fields"], self.fields)

    def test_saving_phase_must_persist_before_report_storage_can_start(self):
        operation = self.operation()
        claim = claim_listing_generation_operation(self.repository, operation=operation)
        with sqlite3.connect(self.db) as conn:
            conn.execute("""create trigger fixture_block_saving_phase before update of output_json on tasks
                when json_extract(new.output_json,'$.phase')='saving_report'
                begin select raise(abort,'fixture saving phase unavailable'); end""")
        with self.assertRaises(ListingDraftGenerationError) as error:
            self.generate(generation_mode="rewrite_buyer_copy", operation_task=claim["task"])
        self.assertFalse(error.exception.report_save_attempted)
        self.assertEqual(self.read(operation)["status"], "failed_before_report")
        self.assertEqual(self.repository.list_reports(company_id=self.company_id), self.original_reports)
        self.assertEqual(len(self.model.calls), 2)

    def test_report_storage_failure_stays_unknown_and_does_not_license_retry(self):
        operation = self.operation()
        claim = claim_listing_generation_operation(self.repository, operation=operation)
        with sqlite3.connect(self.db) as conn:
            conn.execute("""create trigger fixture_block_report before insert on reports
                when new.runtime_run_id='listing_draft_generation'
                begin select raise(abort,'fixture report storage unavailable'); end""")
        with self.assertRaises(ListingDraftGenerationError) as error:
            self.generate(generation_mode="rewrite_buyer_copy", operation_task=claim["task"])
        self.assertTrue(error.exception.report_save_attempted)
        view = self.read(operation)
        self.assertEqual(view["status"], "save_unknown")
        self.assertFalse(view["can_retry"])
        self.assertTrue(view["report_save_attempted"])
        self.assertEqual(len(self.model.calls), 2)

    def test_saved_report_overrides_failed_post_save_metadata_without_a_second_generation(self):
        operation = self.operation()
        claim = claim_listing_generation_operation(self.repository, operation=operation)
        with sqlite3.connect(self.db) as conn:
            conn.execute("""create trigger fixture_block_completion before update of output_json on tasks
                when json_extract(new.output_json,'$.phase')='report_saved'
                begin select raise(abort,'fixture metadata unavailable'); end""")
        result = self.generate(generation_mode="rewrite_buyer_copy", operation_task=claim["task"])
        view = self.read(operation)
        self.assertEqual(view["status"], "report_saved")
        self.assertEqual(view["report"]["report_id"], result["report"]["report_id"])
        self.assertFalse(view["can_retry"])
        self.assertEqual(len(self.model.calls), 2)

    def test_recovery_rejects_a_report_whose_original_snapshot_is_not_the_claimed_input(self):
        operation = self.operation()
        claim = claim_listing_generation_operation(self.repository, operation=operation)
        result = self.generate(generation_mode="rewrite_buyer_copy", operation_task=claim["task"])
        with sqlite3.connect(self.db) as conn:
            conn.execute("""update reports set report_json=json_set(report_json,
                '$.listing_handoff.listing_fields.buyer_copy_rewrite.previous_fields.title','Different request title')
                where report_id=?""", (result["report"]["report_id"],))
        view = self.read(operation)
        self.assertEqual(view["status"], "save_unknown")
        self.assertIsNone(view["report"])
        self.assertFalse(view["can_retry"])

    def test_source_read_failure_after_claim_is_known_pre_model_failure(self):
        operation = self.operation()
        claim = claim_listing_generation_operation(self.repository, operation=operation)
        with patch.object(self.repository, "get_listing_draft_checkpoint",
                          side_effect=sqlite3.OperationalError("fixture checkpoint storage unavailable")):
            result = self.generate(generation_mode="rewrite_buyer_copy", operation_task=claim["task"])
            self.assertEqual(result["status"], "blocked")
            self.assertEqual(result["failure_code"], "listing_rewrite_source_unavailable")
            view = self.read(operation)
            self.assertEqual(view["status"], "failed_before_report")
            self.assertTrue(view["can_retry"])
            self.assertFalse(view["model_called"])
            self.assertFalse(view["usage_consumed"])
            self.assertEqual(self.model.calls, [])

    def test_missing_foreign_and_different_project_reads_do_not_reveal_or_restart_the_operation(self):
        operation = self.operation()
        self.assertEqual(self.read(operation)["status"], "not_found")
        claim_listing_generation_operation(self.repository, operation=operation)
        before_tasks = self.repository.list_tasks(company_id=self.company_id)
        for scope in ({"company_id": "company_foreign"}, {"store_id": "store_foreign"}, {"user_id": "user_foreign"}):
            values = dict(company_id=self.company_id, store_id=self.store["store_id"], user_id=self.user_id,
                operation_id=operation["operation_id"], listing_project_identity=self.identity)
            view = read_listing_generation_operation(self.repository, **{**values, **scope})
            self.assertEqual(view["status"], "not_found")
            self.assertIsNone(view["report"])
            self.assertFalse(view["can_retry"])
        for field in self.identity:
            view = read_listing_generation_operation(self.repository, company_id=self.company_id,
                store_id=self.store["store_id"], user_id=self.user_id, operation_id=operation["operation_id"],
                listing_project_identity={**self.identity, field: "other_identity"})
            self.assertEqual(view["status"], "conflict")
            self.assertIsNone(view["report"])
            self.assertFalse(view["can_retry"])
        self.assertEqual(self.repository.list_tasks(company_id=self.company_id), before_tasks)
        self.assertEqual(self.model.calls, [])

    def test_an_old_unfinished_operation_never_becomes_eligible_for_automatic_execution(self):
        operation = self.operation()
        claim = claim_listing_generation_operation(self.repository, operation=operation)
        with sqlite3.connect(self.db) as conn:
            conn.execute("update tasks set created_at=?,updated_at=? where task_id=?",
                ("2000-01-01T00:00:00+00:00", "2000-01-01T00:00:00+00:00", claim["task"]["task_id"]))
        before = self.repository.get_task(company_id=self.company_id, task_id=claim["task"]["task_id"])
        view = self.read(operation)
        self.assertEqual(view["status"], "running")
        self.assertFalse(view["can_retry"])
        self.assertFalse(claim_listing_generation_operation(self.repository, operation=operation)["claimed"])
        self.assertEqual(self.repository.get_task(company_id=self.company_id, task_id=claim["task"]["task_id"]), before)
        self.assertEqual(self.model.calls, [])

    def test_sensitive_operation_ids_and_payloads_are_rejected_without_creating_a_task(self):
        for changes in ({"operation_id": "sk-" + "A" * 24},
                        {"merchant_product_fact_packet": {**self.packet, "api_key": "sk-" + "B" * 24}},
                        {"current_draft_fields": {**self.fields, "risk_notes": "ghp_" + "C" * 30,
                                                  "merchant_edited_fields": self.edited}}):
            with self.assertRaises(ValueError):
                claim_listing_generation_operation(self.repository, operation=self.operation(**changes))
        self.assertEqual(self.repository.list_tasks(company_id=self.company_id), self.original_tasks)
        self.assertEqual(self.model.calls, [])

    def test_default_generation_operation_preserves_its_existing_mode_and_has_no_rewrite_anchors(self):
        self.model.output["keywords"] = ["tablet stand"]
        self.model.output["item_specifics"] = {"Type": "Tablet Stand"}
        operation = self.operation(generation_mode="preserve_merchant_edits", current_draft_fields={},
            expected_base_report_id=None, expected_checkpoint_revision=None)
        claim = claim_listing_generation_operation(self.repository, operation=operation)
        result = self.generate(generation_mode="preserve_merchant_edits", current_draft_fields={},
            expected_base_report_id=None, expected_checkpoint_revision=None, operation_task=claim["task"])
        self.assertEqual(result["status"], "completed")
        view = self.read(operation)
        self.assertEqual(view["status"], "report_saved")
        self.assertEqual(view["generation_mode"], "preserve_merchant_edits")
        self.assertIsNone(view["expected_base_report_id"])
        self.assertIsNone(view["expected_checkpoint_revision"])
        self.assertEqual(len(self.model.calls), 2)


if __name__ == "__main__":
    unittest.main()
