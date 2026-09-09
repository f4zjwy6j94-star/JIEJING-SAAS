#!/usr/bin/env python3
"""Temporary-database recovery proofs for explicitly selected legacy Listing tasks."""
from __future__ import annotations

import copy
import gc
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
import uuid
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.listing_draft_generation import ListingDraftGenerationError, generate_listing_draft
from jiejing_saas.repository import SaaSRepository


class LocalModel:
    model = "legacy-recovery-local-fixture"

    def __init__(self):
        self.calls = 0
        self.output = {"title": "Foldable Aluminum Tablet Stand",
                       "selling_points": ["Aluminum construction", "Foldable design", "Silicone pads"],
                       "description": "A foldable aluminum tablet stand with silicone contact pads."}

    def generate_text(self, **_kwargs):
        self.calls += 1
        return {"text": json.dumps(self.output), "model": self.model,
                "_usage": {"input_tokens": 80, "output_tokens": 50, "total_tokens": 130}}


class LegacyRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="jiejing-legacy-recovery-")
        self.addCleanup(self.directory.cleanup)
        self.addCleanup(gc.collect)
        env = patch.dict(os.environ, {"PYTHONUTF8": "1", "SYSTEMROOT": "C:\\Windows",
            "TEMP": self.directory.name, "TMP": self.directory.name,
            "JIEJING_DATABASE_ENGINE": "sqlite", "JIEJING_DATABASE_URL": ""}, clear=True)
        env.start()
        self.addCleanup(env.stop)
        self.repository = SaaSRepository(Path(self.directory.name) / "saas.sqlite")
        account = self.repository.create_user_with_company(email="legacy@local.invalid",
            password="local-fixture-password", company_name="Local legacy recovery")
        self.company_id, self.user_id = account["company"]["company_id"], account["user"]["user_id"]
        self.store_id = self.repository.create_store(company_id=self.company_id, user_id=self.user_id,
            payload={"platform": "ebay", "store_name": "Legacy fixture", "marketplace": "EBAY_US"})["store_id"]
        self.identity = {"key": "listing-project-legacy", "source_report_id": "report-legacy-source", "candidate_id": "candidate_1"}
        self.packet = {"contract_version": "merchant_product_fact_packet_v1", "simulation_only": True,
            "merchant_confirmed_facts": {}, "derived_listing_suggestions": {"product_name": "Foldable Tablet Stand",
                "material": "Aluminum and silicone", "condition": "NEW", "style": "Foldable", "quantity": "2"}}
        self.fields = {"title": "旧标题", "selling_points": "旧卖点一\n旧卖点二\n旧卖点三", "description": "旧描述",
            "category": "Existing category", "item_specifics": "Type: Tablet Stand", "keywords": "",
            "price": "USD 39.99", "images": "https://assets.example.invalid/concept.png",
            "logistics": "Not verified", "risk_notes": "Concept only; not eligible for publication."}
        self.edited = ["description", "selling_points", "title"]
        facts = self.repository.save_merchant_product_fact_checkpoint(company_id=self.company_id,
            store_id=self.store_id, user_id=self.user_id, packet=self.packet, listing_project_identity=self.identity)
        self.base_id = facts["report"]["report_id"]
        self.repository.save_listing_draft_checkpoint(company_id=self.company_id, store_id=self.store_id,
            user_id=self.user_id, project_key=self.identity["key"], body={"contract_version": "listing_merchant_edit_v1",
                "listing_project_identity": self.identity, "base_report_id": self.base_id, "expected_revision": 0,
                "mutation_id": str(uuid.uuid4()), "fields": self.fields, "merchant_edited_fields": self.edited})
        self.model = LocalModel()

    def generate(self):
        return generate_listing_draft(repository=self.repository, company_id=self.company_id,
            store_id=self.store_id, user_id=self.user_id, listing_project_identity=self.identity,
            merchant_product_fact_packet=self.packet,
            current_draft_fields={**self.fields, "merchant_edited_fields": self.edited},
            generation_mode="rewrite_buyer_copy", expected_base_report_id=self.base_id, expected_checkpoint_revision=1,
            model_client=self.model, model_resolution={"provider_key": "local_fixture", "model": self.model.model,
                "merchant_pays_provider_directly": True})

    def read(self, task_id, **overrides):
        from jiejing_saas.listing_generation_legacy_recovery import read_legacy_listing_generation_result
        args = {"repository": self.repository, "company_id": self.company_id, "store_id": self.store_id,
                "user_id": self.user_id, "task_id": task_id, "listing_project_identity": self.identity,
                "expected_base_report_id": self.base_id, "expected_checkpoint_revision": 1}
        return read_legacy_listing_generation_result(**{**args, **overrides})

    def quality_failure(self):
        self.model.output["title"] = "中文结果无法通过"
        with self.assertRaises(ListingDraftGenerationError) as caught:
            self.generate()
        return self.repository.get_task(company_id=self.company_id, task_id=caught.exception.task_id)

    def replace_input(self, task_id, value):
        with self.repository._connect() as connection:
            connection.execute("update tasks set input_json = ? where task_id = ?", (json.dumps(value), task_id))

    def test_selected_quality_failure_recovers_without_writes_or_another_model_call(self):
        self.model.output["title"] = "中文结果无法通过"
        with self.assertRaises(ListingDraftGenerationError) as caught:
            self.generate()
        task_id = caught.exception.task_id
        self.assertEqual(self.model.calls, 2)
        task_before = self.repository.get_task(company_id=self.company_id, task_id=task_id)
        reports_before = self.repository.list_reports(company_id=self.company_id)
        checkpoint_before = self.repository.get_listing_draft_checkpoint(company_id=self.company_id,
            store_id=self.store_id, identity=self.identity)
        recovered = self.read(task_id)
        self.assertEqual(recovered["status"], "legacy_failed_before_report")
        self.assertIs(recovered["can_retry"], True)
        self.assertEqual(recovered["proof_kind"], "immutable_failed_usage_ledger")
        self.assertNotIn("report_save_attempted", recovered)
        self.assertNotIn("operation_id", recovered)
        self.assertIsNone(recovered["report"])
        self.assertIs(recovered["model_called"], False)
        self.assertEqual(self.repository.get_task(company_id=self.company_id, task_id=task_id), task_before)
        self.assertEqual(self.repository.list_reports(company_id=self.company_id), reports_before)
        self.assertEqual(self.repository.get_listing_draft_checkpoint(company_id=self.company_id,
            store_id=self.store_id, identity=self.identity), checkpoint_before)
        self.assertEqual(self.model.calls, 2)

    def test_storage_failure_with_completed_usage_cannot_unlock_a_legacy_retry(self):
        with self.repository._connect() as connection:
            connection.execute("""create trigger reject_listing_report before insert on reports
                when new.runtime_run_id = 'listing_draft_generation'
                begin select raise(abort, 'injected json report storage failure'); end""")
        with self.assertRaises(ListingDraftGenerationError) as caught:
            self.generate()
        recovered = self.read(caught.exception.task_id)
        self.assertEqual(recovered["status"], "legacy_evidence_incomplete")
        self.assertIs(recovered["can_retry"], False)
        self.assertIs(caught.exception.report_save_attempted, True)
        self.assertEqual(self.model.calls, 1)

    def test_completed_usage_commit_ack_loss_cannot_be_relabelled_failed(self):
        original = self.repository.record_model_usage
        lost = False

        def lose_first_ack(**kwargs):
            nonlocal lost
            row = original(**kwargs)
            if not lost:
                lost = True
                raise OSError("local database acknowledgement lost")
            return row

        with patch.object(self.repository, "record_model_usage", side_effect=lose_first_ack):
            with self.assertRaises(ListingDraftGenerationError) as caught:
                self.generate()
        recovered = self.read(caught.exception.task_id)
        self.assertEqual(recovered["status"], "legacy_evidence_incomplete")
        self.assertIs(recovered["can_retry"], False)
        self.assertEqual(self.model.calls, 1)

    def test_saved_report_with_lost_ack_is_returned_without_another_generation(self):
        original = self.repository.save_listing_draft_report

        def lose_saved_report_ack(**kwargs):
            original(**kwargs)
            raise OSError("local report acknowledgement lost")

        with patch.object(self.repository, "save_listing_draft_report", side_effect=lose_saved_report_ack):
            with self.assertRaises(ListingDraftGenerationError) as caught:
                self.generate()
        reports = self.repository.list_reports(company_id=self.company_id, task_id=caught.exception.task_id)
        self.assertEqual(len(reports), 1)
        task_before = self.repository.get_task(company_id=self.company_id, task_id=caught.exception.task_id)
        checkpoint_before = self.repository.get_listing_draft_checkpoint(company_id=self.company_id,
            store_id=self.store_id, identity=self.identity)
        recovered = self.read(caught.exception.task_id)
        self.assertEqual(recovered["status"], "report_saved")
        self.assertIs(recovered["can_retry"], False)
        # Scoped recovery includes the task author; generic report listing does not.
        self.assertEqual(task_before["user_id"], self.user_id)
        self.assertEqual(recovered["report"], {**reports[0], "user_id": self.user_id})
        self.assertEqual(self.repository.get_task(company_id=self.company_id, task_id=caught.exception.task_id), task_before)
        self.assertEqual(self.repository.list_reports(company_id=self.company_id, task_id=caught.exception.task_id), reports)
        self.assertEqual(self.repository.get_listing_draft_checkpoint(company_id=self.company_id,
            store_id=self.store_id, identity=self.identity), checkpoint_before)
        self.assertEqual(self.model.calls, 1)

    def test_another_same_project_failed_save_remains_uncertain(self):
        self.model.output["title"] = "中文结果无法通过"
        with self.assertRaises(ListingDraftGenerationError) as caught:
            self.generate()
        first_task = caught.exception.task_id
        self.model.output["title"] = "Foldable Aluminum Tablet Stand"
        with self.repository._connect() as connection:
            connection.execute("""create trigger reject_later_report before insert on reports
                when new.runtime_run_id = 'listing_draft_generation'
                begin select raise(abort, 'injected report save failure'); end""")
        with self.assertRaises(ListingDraftGenerationError):
            self.generate()
        recovered = self.read(first_task)
        self.assertIs(recovered["can_retry"], False)
        self.assertEqual(recovered["status"], "legacy_evidence_incomplete")
        self.assertEqual(self.model.calls, 3)

    def test_invalid_context_is_not_reflected_as_an_arbitrary_response_payload(self):
        invalid = {**self.identity, "api_key": "do-not-reflect-this-input"}
        recovered = self.read("task_missing_fixture", listing_project_identity=invalid)
        self.assertIs(recovered["can_retry"], False)
        self.assertNotIn("do-not-reflect-this-input", json.dumps(recovered))
        self.assertNotIn("api_key", recovered["listing_project_identity"])

    def test_full_owner_and_frozen_identity_are_required(self):
        task = self.quality_failure()
        variants = [{"company_id": "company_other"}, {"store_id": "store_other"}, {"user_id": "user_other"},
            {"expected_base_report_id": "report_other"}, {"expected_checkpoint_revision": 2},
            {"expected_checkpoint_revision": True}, {"expected_checkpoint_revision": "1"},
            *({"listing_project_identity": {**self.identity, key: "other"}} for key in self.identity)]
        for variant in variants:
            with self.subTest(variant=variant):
                result = self.read(task["task_id"], **variant)
                self.assertIs(result["can_retry"], False)
                self.assertIsNone(result["report"])
        self.assertIs(self.read(task["task_id"])["can_retry"], True)
        self.assertEqual(self.model.calls, 2)

    def test_ten_fields_edited_marks_packet_and_legacy_contract_match_the_frozen_checkpoint(self):
        task = self.quality_failure()
        original = task["input"]
        variants = []
        for field in self.fields:
            changed = copy.deepcopy(original)
            changed["current_draft_fields"][field] += " changed"
            variants.append(changed)
        changed = copy.deepcopy(original)
        changed["current_draft_fields"]["merchant_edited_fields"] = []
        variants.append(changed)
        changed = copy.deepcopy(original)
        changed["merchant_product_fact_packet"]["derived_listing_suggestions"]["material"] = "Titanium"
        variants.append(changed)
        variants.extend([{**original, "contract_version": "listing_generation_operation_v1"},
                         {**original, "generation_mode": "preserve_merchant_edits"}])
        for index, value in enumerate(variants):
            with self.subTest(index=index):
                self.replace_input(task["task_id"], value)
                self.assertIs(self.read(task["task_id"])["can_retry"], False)
        self.replace_input(task["task_id"], original)
        self.assertIs(self.read(task["task_id"])["can_retry"], True)

    def test_strict_failure_task_booleans_and_counts_are_not_truthy_strings(self):
        task = self.quality_failure()
        original = task["output"]
        variants = [{"model_called": "true"}, {"usage_consumed": "true"}, {"usage_ledger_recorded": "true"},
                    {"usage_ledger_recorded": False}, {"model_request_count": True}, {"model_request_count": 0},
                    {"model_request_count": 3}, {"real_platform_writes_enabled": "false"},
                    {"secret_exposed": "false"}, {"failure_code": "listing_other_failure"}]
        for variant in variants:
            with self.subTest(variant=variant):
                self.repository.update_task_status(company_id=self.company_id, task_id=task["task_id"],
                    status="failed", output={**original, **variant})
                self.assertIs(self.read(task["task_id"])["can_retry"], False)
        self.repository.update_task_status(company_id=self.company_id, task_id=task["task_id"], status="failed", output=original)
        self.assertIs(self.read(task["task_id"])["can_retry"], True)

    def test_immutable_usage_identity_outcome_and_uniqueness_are_required(self):
        task = self.quality_failure()
        with self.repository._connect() as connection:
            original = dict(connection.execute("select * from model_usage_ledger where task_id = ?", (task["task_id"],)).fetchone())
        usage = json.loads(original["usage_json"])
        variants = [{"request_count": 0}, {"request_count": 2.5}, {"user_id": "user_other"},
            {"idempotency_key_hash": "0" * 64},
            {"usage_json": json.dumps({**usage, "details": {**usage["details"], "outcome": "model_completed"}})},
            {"usage_json": json.dumps({**usage, "details": {**usage["details"], "failure_code": "listing_wrong_failure"}})},
            {"usage_json": json.dumps({**usage, "secret_exposed": "false"})},
            {"usage_json": json.dumps({**usage, "provider_credentials_stored": "false"})},
            {"usage_json": json.dumps({**usage, "details": {**usage["details"], "responses_stored": True}})}]
        for variant in variants:
            with self.subTest(fields=list(variant)):
                assignments = ",".join(f"{key} = ?" for key in variant)
                with self.repository._connect() as connection:
                    connection.execute(f"update model_usage_ledger set {assignments} where usage_id = ?", (*variant.values(), original["usage_id"]))
                self.assertIs(self.read(task["task_id"])["can_retry"], False)
                with self.repository._connect() as connection:
                    connection.execute(f"update model_usage_ledger set {assignments} where usage_id = ?", (*(original[key] for key in variant), original["usage_id"]))
        self.assertIs(self.read(task["task_id"])["can_retry"], True)
        self.repository.record_model_usage(company_id=self.company_id, user_id=self.user_id, task_id=task["task_id"],
            usage_owner="merchant_byok", model_family="local_fixture", model_label=self.model.model,
            request_count=1, input_tokens=1, output_tokens=1, total_tokens=2, cost_minor=0,
            currency="CNY", cost_status="unavailable", idempotency_key=f"different-key-{task['task_id']}",
            details={"outcome": "failed", "failure_code": task["output"]["failure_code"]})
        self.assertIs(self.read(task["task_id"])["can_retry"], False)

    def test_pending_and_completed_without_report_never_count_as_finished(self):
        task = self.quality_failure()
        other = self.repository.create_task(company_id=self.company_id, store_id=self.store_id, user_id=self.user_id,
            task_type="listing_draft_generation", title="Another real local task", input_data=task["input"])
        for status in ("queued", "running", "completed", "failed"):
            with self.subTest(status=status):
                self.repository.update_task_status(company_id=self.company_id, task_id=other["task_id"], status=status, output={})
                self.assertIs(self.read(task["task_id"])["can_retry"], False)

    def test_frozen_history_not_latest_head_is_used_and_newer_edits_survive(self):
        task = self.quality_failure()
        newer_fields = {**self.fields, "title": "Newer unsent merchant title"}
        self.repository.save_listing_draft_checkpoint(company_id=self.company_id, store_id=self.store_id,
            user_id=self.user_id, project_key=self.identity["key"], body={"contract_version": "listing_merchant_edit_v1",
                "listing_project_identity": self.identity, "base_report_id": self.base_id, "expected_revision": 1,
                "mutation_id": str(uuid.uuid4()), "fields": newer_fields, "merchant_edited_fields": self.edited})
        result = self.read(task["task_id"])
        self.assertIs(result["can_retry"], True)
        latest = self.repository.get_listing_draft_checkpoint(company_id=self.company_id, store_id=self.store_id, identity=self.identity)
        self.assertEqual(latest["checkpoint"]["fields"], newer_fields)
        self.assertEqual(latest["current_revision"], 2)
        self.assertEqual(self.model.calls, 2)

    def test_another_completed_task_needs_a_real_scoped_listing_report(self):
        task = self.quality_failure()
        self.model.output["title"] = "Foldable Aluminum Tablet Stand"
        completed = self.generate()
        self.assertIs(self.read(task["task_id"])["can_retry"], True)
        with self.repository._connect() as connection:
            original = dict(connection.execute("select * from reports where report_id = ?", (completed["report"]["report_id"],)).fetchone())
        data = json.loads(original["report_json"])
        wrong_identity = {**data, "listing_project_identity": {**self.identity, "candidate_id": "other"}}
        for variant in ({"report_type": "runtime.result"}, {"status": "pending"}, {"runtime_run_id": "other"},
                        {"report_json": json.dumps(wrong_identity)},
                        {"report_json": json.dumps({**data, "real_platform_writes_enabled": True})}):
            with self.subTest(fields=list(variant)):
                assignments = ",".join(f"{key} = ?" for key in variant)
                with self.repository._connect() as connection:
                    connection.execute(f"update reports set {assignments} where report_id = ?", (*variant.values(), original["report_id"]))
                self.assertIs(self.read(task["task_id"])["can_retry"], False)
                with self.repository._connect() as connection:
                    connection.execute(f"update reports set {assignments} where report_id = ?", (*(original[key] for key in variant), original["report_id"]))


if __name__ == "__main__":
    unittest.main()
