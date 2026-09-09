#!/usr/bin/env python3
"""Local temporary-repository contracts for explicitly authorized buyer-copy rewriting."""
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

from jiejing_saas.listing_draft_generation import (
    ListingDraftGenerationError, generate_listing_draft, is_listing_buyer_copy_rewrite_contract,
)
from jiejing_saas.repository import SaaSRepository


FIELD_KEYS = ("title", "selling_points", "description", "category", "item_specifics",
              "keywords", "price", "images", "logistics", "risk_notes")
BUYER_FIELDS = {"title", "selling_points", "description"}


class LocalModelBoundary:
    name = "local-rewrite-fixture"
    version = "1"
    model = "local-fixture-no-network"

    def __init__(self):
        self.calls = []
        self.output = {
            "title": "Foldable Aluminum Tablet Stand",
            "selling_points": ["Aluminum construction", "Foldable design", "Silicone contact pads"],
            "description": "A foldable aluminum tablet stand with silicone contact pads for desktop use.",
            "category_suggestion": "Model-owned category must not replace the editor",
            "keywords": ["waterproof titanium"],
            "item_specifics": {"Type": "Universal iPad Holder", "Brand": "Invented Brand"},
            "quantity": "999", "selling_price": "0.01", "image_rights_confirmed": True,
        }

    def generate_text(self, **kwargs):
        self.calls.append(kwargs)
        return {"text": json.dumps(self.output), "model": self.model,
                "_usage": {"input_tokens": 80, "output_tokens": 50, "total_tokens": 130}}


class BuyerCopyRewriteTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="jiejing-buyer-copy-rewrite-")
        self.addCleanup(self.directory.cleanup)
        self.addCleanup(gc.collect)
        self.clean_environment = patch.dict(os.environ, {"PYTHONUTF8": "1", "SYSTEMROOT": "C:\\Windows",
            "TEMP": self.directory.name, "TMP": self.directory.name,
            "JIEJING_DATABASE_ENGINE": "sqlite", "JIEJING_DATABASE_URL": ""}, clear=True)
        self.clean_environment.start()
        self.addCleanup(self.clean_environment.stop)
        self.db = Path(self.directory.name) / "saas.sqlite"
        self.repository = SaaSRepository(self.db)
        account = self.repository.create_user_with_company(email="rewrite@local.invalid",
            password="local-rewrite-fixture-password", company_name="Local rewrite fixture")
        self.company_id = account["company"]["company_id"]
        self.user_id = account["user"]["user_id"]
        self.store = self.repository.create_store(company_id=self.company_id, user_id=self.user_id,
            payload={"platform": "ebay", "store_name": "Local rewrite fixture", "marketplace": "EBAY_US"})
        self.identity = {"key": "listing-project-rewrite", "source_report_id": "report-source-rewrite",
                         "candidate_id": "candidate_1"}
        self.packet = {"contract_version": "merchant_product_fact_packet_v1", "simulation_only": True,
            "merchant_confirmed_facts": {}, "derived_listing_suggestions": {
                "product_name": "Foldable Tablet Stand", "material": "Aluminum and silicone",
                "condition": "NEW", "style": "Foldable", "quantity": "2"}}
        self.fields = {
            "title": "折叠平板支架旧标题", "selling_points": "旧卖点一\n旧卖点二\n旧卖点三",
            "description": "Old draft. 内部演练，不可发布。", "category": "  保留现有类目  ",
            "item_specifics": "Type: Merchant original\nColor: Gray", "keywords": "",
            "price": "USD 39.99 (merchant draft only)", "images": "https://assets.example.invalid/concept.png",
            "logistics": "  未核对物流\n", "risk_notes": "Concept only; image rights not confirmed."}
        self.edited = ["title", "selling_points", "description", "category", "price", "risk_notes"]
        self.model = LocalModelBoundary()
        saved_facts = self.repository.save_merchant_product_fact_checkpoint(company_id=self.company_id,
            store_id=self.store["store_id"], user_id=self.user_id, packet=self.packet,
            listing_project_identity=self.identity)
        self.base_report_id = saved_facts["report"]["report_id"]
        self.repository.save_listing_draft_checkpoint(company_id=self.company_id, store_id=self.store["store_id"],
            user_id=self.user_id, project_key=self.identity["key"], body={
                "contract_version": "listing_merchant_edit_v1", "listing_project_identity": self.identity,
                "base_report_id": self.base_report_id, "expected_revision": 0, "mutation_id": str(uuid.uuid4()),
                "fields": self.fields, "merchant_edited_fields": self.edited})
        self.original_tasks = self.repository.list_tasks(company_id=self.company_id)
        self.original_reports = self.repository.list_reports(company_id=self.company_id)

    def generate(self, **overrides):
        args = {"repository": self.repository, "company_id": self.company_id,
            "store_id": self.store["store_id"], "user_id": self.user_id,
            "listing_project_identity": self.identity, "merchant_product_fact_packet": self.packet,
            "current_draft_fields": {**self.fields, "merchant_edited_fields": self.edited},
            "expected_base_report_id": self.base_report_id, "expected_checkpoint_revision": 1,
            "model_client": self.model, "model_resolution": {"provider_key": "local_fixture",
                "model": self.model.model, "merchant_pays_provider_directly": True}}
        args.update(overrides)
        return generate_listing_draft(**args)

    def test_explicit_rewrite_replaces_only_three_fields_and_preserves_original_in_report(self):
        before = copy.deepcopy(self.fields)
        default = self.generate()
        self.assertEqual(default["failure_code"], "listing_merchant_copy_marketplace_language")
        self.assertFalse(default["model_called"])
        self.assertEqual(self.model.calls, [])

        result = self.generate(generation_mode="rewrite_buyer_copy")
        self.assertEqual(result["status"], "completed")
        self.assertEqual(len(self.model.calls), 1)
        saved = self.repository.get_report_for_company(company_id=self.company_id,
            report_id=result["report"]["report_id"])
        handoff = saved["report"]["listing_handoff"]["listing_fields"]
        contract = handoff["buyer_copy_rewrite"]
        self.assertEqual(contract["contract_version"], "listing_buyer_copy_rewrite_v1")
        self.assertEqual(contract["previous_fields"], before)
        self.assertEqual(set(contract["fields"]), set(FIELD_KEYS))
        for key in FIELD_KEYS:
            if key in BUYER_FIELDS:
                self.assertNotEqual(contract["fields"][key], before[key])
            else:
                self.assertEqual(contract["fields"][key], before[key], key)
        self.assertEqual(set(contract["previous_merchant_edited_fields"]), set(self.edited))
        self.assertEqual(set(contract["merchant_edited_fields"]), set(self.edited) - BUYER_FIELDS)
        self.assertEqual(saved["report"]["listing_project_identity"], self.identity)
        self.assertEqual(handoff["merchant_product_fact_packet"]["merchant_confirmed_facts"], {})
        self.assertTrue(handoff["simulation_only"])
        self.assertTrue(handoff["image_requirements"]["rights_check_required"])
        self.assertFalse(handoff["real_platform_writes_enabled"])
        self.assertNotIn("折叠平板支架旧标题", self.model.calls[0]["user_prompt"])
        self.assertEqual(self.fields, before)

    def test_unknown_modes_are_rejected_before_model_or_task(self):
        for mode in (None, True, {}, "rewrite", "REWRITE_BUYER_COPY", "rewrite_buyer_copy "):
            with self.subTest(mode=mode):
                result = self.generate(generation_mode=mode)
                self.assertEqual(result["failure_code"], "listing_generation_mode_invalid")
                self.assertFalse(result["model_called"])
                self.assertFalse(result["usage_consumed"])
                self.assertIsNone(result["report"])
        self.assertEqual(self.model.calls, [])
        self.assertEqual(self.repository.list_tasks(company_id=self.company_id), self.original_tasks)

    def test_rewrite_requires_a_complete_bounded_secret_free_string_snapshot(self):
        source = {**self.fields, "merchant_edited_fields": self.edited}
        invalid = [({}, "listing_rewrite_snapshot_invalid"),
            ({**source, "price": 39.99}, "listing_rewrite_snapshot_invalid"),
            ({**source, "secret_ref": "not-permitted"}, "listing_rewrite_snapshot_invalid"),
            ({**source, "title": "x" * 801}, "listing_rewrite_snapshot_invalid"),
            ({**source, "description": "x" * 1401}, "listing_rewrite_snapshot_invalid"),
            ({**source, "selling_points": "x" * 1401}, "listing_rewrite_snapshot_invalid"),
            ({**source, "keywords": "bad\x00value"}, "listing_rewrite_snapshot_invalid"),
            ({**source, "keywords": "bad\ud800value"}, "listing_rewrite_snapshot_invalid"),
            ({**source, "merchant_edited_fields": ["quantity"]}, "listing_rewrite_snapshot_invalid"),
            ({**source, "merchant_edited_fields": [True]}, "listing_rewrite_snapshot_invalid"),
            ({**source, "risk_notes": "ghp_" + "S" * 30}, "listing_rewrite_snapshot_sensitive_text")]
        for index, (fields, code) in enumerate(invalid):
            with self.subTest(case=index):
                result = self.generate(generation_mode="rewrite_buyer_copy", current_draft_fields=fields)
                self.assertEqual(result["failure_code"], code)
                self.assertFalse(result["model_called"])
                self.assertFalse(result["usage_consumed"])
                self.assertIsNone(result["report"])
        self.assertEqual(self.model.calls, [])
        self.assertEqual(self.repository.list_tasks(company_id=self.company_id), self.original_tasks)

    def test_rewrite_output_must_fit_checkpoints_and_failure_keeps_original(self):
        for field, value in (("description", "Foldable design. " * 100),
                             ("selling_points", ["Foldable design. " * 19] * 5)):
            with self.subTest(field=field):
                self.model.output[field] = value
                before = copy.deepcopy(self.fields)
                with self.assertRaises(ListingDraftGenerationError) as failure:
                    self.generate(generation_mode="rewrite_buyer_copy")
                self.assertEqual(failure.exception.failure_code, "listing_model_output_rewrite_copy_too_long")
                self.assertTrue(failure.exception.model_called)
                self.assertTrue(failure.exception.usage_consumed)
                self.assertEqual(self.fields, before)
                self.assertEqual(self.repository.list_reports(company_id=self.company_id), self.original_reports)
                self.model.output = LocalModelBoundary().output
        self.assertEqual(len(self.model.calls), 4, "one bounded correction per failed request")

    def test_storage_redaction_difference_is_rejected_before_model(self):
        self.fields["risk_notes"] = "AIAK" + "A" * 12
        self.repository.save_listing_draft_checkpoint(company_id=self.company_id, store_id=self.store["store_id"],
            user_id=self.user_id, project_key=self.identity["key"], body={
                "contract_version": "listing_merchant_edit_v1", "listing_project_identity": self.identity,
                "base_report_id": self.base_report_id, "expected_revision": 1, "mutation_id": str(uuid.uuid4()),
                "fields": self.fields, "merchant_edited_fields": self.edited})
        result = self.generate(generation_mode="rewrite_buyer_copy", expected_checkpoint_revision=2)
        self.assertEqual(result["failure_code"], "listing_rewrite_snapshot_sensitive_text")
        self.assertFalse(result["model_called"])
        self.assertEqual(self.model.calls, [])
        self.assertEqual(self.repository.list_reports(company_id=self.company_id), self.original_reports)

    def test_rewrite_model_copy_must_survive_storage_without_redaction_or_coercion(self):
        invalid = [("description", "AIAK" + "B" * 12, "listing_model_output_rewrite_copy_sensitive_text"),
            ("title", {"invented": "value"}, "listing_model_output_rewrite_copy_invalid"),
            ("description", "Foldable.\x00", "listing_model_output_rewrite_copy_invalid"),
            ("description", "Foldable.\ud800", "listing_model_output_rewrite_copy_invalid"),
            ("title", "T" * 81, "listing_model_output_rewrite_copy_too_long")]
        for field, value, code in invalid:
            with self.subTest(field=field, code=code):
                self.model.output = LocalModelBoundary().output
                self.model.output[field] = value
                with self.assertRaises(ListingDraftGenerationError) as failure:
                    self.generate(generation_mode="rewrite_buyer_copy")
                self.assertEqual(failure.exception.failure_code, code)
                self.assertTrue(failure.exception.model_called)
                self.assertEqual(self.repository.list_reports(company_id=self.company_id), self.original_reports)
        self.assertEqual(len(self.model.calls), len(invalid) * 2)

    def test_only_the_exact_bounded_rewrite_dto_can_preserve_merchant_text(self):
        result = self.generate(generation_mode="rewrite_buyer_copy")
        contract = result["report"]["report"]["listing_handoff"]["listing_fields"]["buyer_copy_rewrite"]
        self.assertTrue(is_listing_buyer_copy_rewrite_contract(contract))
        for key in ("fields", "previous_fields"):
            malformed = copy.deepcopy(contract)
            malformed[key]["merchant_edited_fields"] = {"api_key": "unapproved-nested-field"}
            self.assertFalse(is_listing_buyer_copy_rewrite_contract(malformed))
        self.assertFalse(is_listing_buyer_copy_rewrite_contract({**contract, "provider": "unapproved"}))
        self.assertFalse(is_listing_buyer_copy_rewrite_contract({**contract, "expected_checkpoint_revision": True}))
        self.assertFalse(is_listing_buyer_copy_rewrite_contract({**contract, "expected_base_report_id": "sk-" + "A" * 14}))


if __name__ == "__main__":
    unittest.main()
