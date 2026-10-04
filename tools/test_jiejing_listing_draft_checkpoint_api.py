#!/usr/bin/env python3
"""Real local HTTP contract for merchant Listing checkpoints; no external services."""
from __future__ import annotations

import copy
import gc
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timedelta
import json
from pathlib import Path
import socket
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]
FIELD_KEYS = ("title", "selling_points", "description", "category", "item_specifics",
              "keywords", "price", "images", "logistics", "risk_notes")


class CheckpointHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="jiejing-checkpoint-")
        cls.root = Path(cls.directory.name)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        cls.base = f"http://127.0.0.1:{port}"
        cls.process = subprocess.Popen(
            [sys.executable, str(ROOT / "tools/jiejing_saas_backend_cli.py"), "serve",
             "--db", str(cls.root / "saas.sqlite"), "--runtime-db", str(cls.root / "runtime.sqlite"),
             "--output-root", str(cls.root), "--host", "127.0.0.1", "--port", str(port)],
            cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            env={"PYTHONUTF8": "1", "JIEJING_DATABASE_ENGINE": "sqlite", "JIEJING_DATABASE_URL": "",
                 # This suite intentionally makes hundreds of isolated local
                 # fixture calls. Rate limiting is tested separately; keep it
                 # enabled without making test order exhaust a shared budget.
                 "JIEJING_EXPENSIVE_API_RATE_LIMIT_MAX_PER_IP": "2000",
                 "JIEJING_EXPENSIVE_API_RATE_LIMIT_MAX_GLOBAL": "4000",
                 "TEMP": str(cls.root), "TMP": str(cls.root), "SYSTEMROOT": "C:\\Windows"},
        )
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            try:
                if cls.request("/health")[0] == 200:
                    break
            except urllib.error.URLError:
                time.sleep(0.1)
        else:
            cls.tearDownClass()
            raise AssertionError("isolated HTTP server did not start")
        status, registered = cls.request("/auth/register", method="POST", body={
            "email": "checkpoint-owner@local.invalid", "password": "local-checkpoint-fixture-pass",
            "company_name": "Checkpoint fixture"})
        assert status == 201, "local fixture registration failed"
        cls.token = registered["token"]

    @classmethod
    def tearDownClass(cls):
        cls.process.terminate()
        cls.process.wait(timeout=10)
        # Independent repository-writer cases use real sqlite connections whose
        # context exits commit but whose driver objects may await collection.
        gc.collect()
        cls.directory.cleanup()

    @classmethod
    def request(cls, path, *, method="GET", body=None, token=None):
        headers = {"Content-Type": "application/json"}
        token = getattr(cls, "token", "") if token is None else token
        if token:
            headers["Authorization"] = f"Bearer {token}"
        request = urllib.request.Request(cls.base + path, method=method, headers=headers,
                                         data=None if body is None else json.dumps(body).encode())
        try:
            response = urllib.request.urlopen(request, timeout=20)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            return response.status, json.loads(response.read().decode())

    def setUp(self):
        status, store = self.request("/stores", method="POST", body={
            "platform": "ebay", "store_name": "Checkpoint " + uuid.uuid4().hex[:8], "marketplace": "EBAY_US"})
        self.assertEqual(status, 201)
        self.store_id = store["store"]["store_id"]
        self.identity = {"key": "listing-project-" + uuid.uuid4().hex,
                         "source_report_id": "", "candidate_id": ""}
        self.path = f"/stores/{self.store_id}/listing-drafts/{self.identity['key']}/checkpoint"
        self.query = "?" + urllib.parse.urlencode({key: self.identity[key] for key in ("source_report_id", "candidate_id")})
        self.fact_body = {"listing_project_identity": self.identity,
                          "merchant_product_fact_packet": {"merchant_confirmed_facts": {
                              "product_name": "Foldable Tablet Stand", "material": "Aluminum", "condition": "NEW"}}}
        status, facts = self.request(f"/stores/{self.store_id}/product-facts", method="POST", body=self.fact_body)
        self.assertEqual(status, 201)
        self.base_report_id = facts["report"]["report_id"]
        self.company_id = facts["task"]["company_id"]
        self.user_id = facts["task"]["user_id"]
        self.body = {"contract_version": "listing_merchant_edit_v1", "listing_project_identity": self.identity,
                     "base_report_id": self.base_report_id, "expected_revision": 0,
                     "mutation_id": str(uuid.uuid4()), "fields": {key: "" for key in FIELD_KEYS},
                     "merchant_edited_fields": ["title", "description"]}
        self.body["fields"]["title"] = "My edited tablet stand"

    def report_fixture(self, suffix, report_type, created_at, *, identity=None, status="saved"):
        # Source-report fixture only: this does not invoke or claim a real model generation.
        report_id = "report_" + self.identity["key"] + "_" + suffix
        with closing(sqlite3.connect(self.root / "saas.sqlite")) as conn, conn:
            conn.row_factory = sqlite3.Row
            original = conn.execute("select * from reports where report_id = ?", (self.base_report_id,)).fetchone()
            payload = json.loads(original["report_json"])
            payload["listing_project_identity"] = self.identity if identity is None else identity
            payload["artifact_type"] = report_type
            conn.execute("""insert into reports
                (report_id,task_id,runtime_run_id,report_type,title,status,created_at,report_json)
                values (?,?,?,?,?,?,?,?)""", (report_id, original["task_id"], "checkpoint_source_fixture",
                report_type, "Checkpoint source fixture", status, created_at, json.dumps(payload)))
        return report_id

    def test_publish_intake_roundtrip_preserves_costs_and_explicit_clears(self):
        before_tasks = self.request("/tasks")[1]
        before_reports = self.request("/reports")[1]
        self.body["publish_intake"] = {
            "values": {"sku": "TEST-8PC", "title": "", "shipping_cost": "4.20", "ad_budget": "0",
                       "exchange_rate": "1", "item_location": "Test location", "image_urls": "https://example.invalid/product.jpg"},
            "basis": {"title": "Source title", "shipping_cost": "", "price": "12.99"},
        }
        status, saved = self.request(self.path, method="POST", body=self.body)
        self.assertEqual(status, 201, "a scoped publish form must save without creating a publication task")
        self.assertEqual(saved["checkpoint"]["publish_intake"], self.body["publish_intake"])
        status, read = self.request(self.path + self.query)
        self.assertEqual(status, 200)
        self.assertEqual(read["checkpoint"]["publish_intake"], self.body["publish_intake"])
        self.assertFalse(saved["model_called"] or saved["usage_consumed"] or saved["real_platform_writes_enabled"])
        self.assertEqual(self.request("/tasks")[1], before_tasks)
        self.assertEqual(self.request("/reports")[1], before_reports)

    def test_publish_intake_survives_legacy_clients_and_exact_retry(self):
        self.body["publish_intake"] = {"values": {"shipping_cost": "4.20", "title": ""}, "basis": {}}
        status, original = self.request(self.path, method="POST", body=self.body)
        self.assertEqual(status, 201)
        legacy = copy.deepcopy(self.body)
        del legacy["publish_intake"]
        legacy.update(expected_revision=1, mutation_id=str(uuid.uuid4()))
        legacy["fields"]["title"] = "A later merchant title"
        status, newer = self.request(self.path, method="POST", body=legacy)
        self.assertEqual(status, 201)
        self.assertEqual(newer["checkpoint"]["publish_intake"], self.body["publish_intake"])
        status, replay = self.request(self.path, method="POST", body=self.body)
        self.assertEqual(status, 200)
        self.assertEqual(replay["checkpoint"], original["checkpoint"])
        self.assertEqual(self.request(self.path + self.query)[1]["checkpoint"], newer["checkpoint"])

    def test_publish_intake_conflict_keeps_both_sides_and_rejects_authority(self):
        self.body["publish_intake"] = {"values": {"shipping_cost": "4.20"}, "basis": {}}
        self.assertEqual(self.request(self.path, method="POST", body=self.body)[0], 201)
        other = copy.deepcopy(self.body)
        other.update(mutation_id=str(uuid.uuid4()))
        other["publish_intake"]["values"]["shipping_cost"] = "8.00"
        status, conflict = self.request(self.path, method="POST", body=other)
        self.assertEqual(status, 409)
        self.assertEqual(conflict["latest_checkpoint"]["publish_intake"], self.body["publish_intake"])
        for bad in (None, {"values": {}, "basis": {}, "ready": True},
                    {"values": {"simulation_only": "false"}, "basis": {}},
                    {"values": {}, "basis": {"company_id": "other-company"}},
                    {"values": {"shipping_cost": 0}, "basis": {}},
                    {"values": {"sku": "x" * 801}, "basis": {}},
                    {"values": {"description_html": "x" * 6001}, "basis": {}},
                    {"values": {"title": "a\u0000b"}, "basis": {}}):
            with self.subTest(invalid_shape=type(bad).__name__):
                invalid = {**other, "expected_revision": 1, "publish_intake": bad}
                self.assertEqual(self.request(self.path, method="POST", body=invalid)[0], 400)
        secret = {**other, "expected_revision": 1,
                  "publish_intake": {"values": {"title": "sk-" + "a" * 32}, "basis": {}}}
        self.assertEqual(self.request(self.path, method="POST", body=secret)[0], 422)
        self.assertEqual(self.request(self.path + self.query)[1]["current_revision"], 1)

    def test_save_then_read_preserves_complete_fields_without_tasks_or_reports(self):
        before_tasks = self.request("/tasks")[1]
        before_reports = self.request("/reports")[1]
        status, saved = self.request(self.path, method="POST", body=self.body)
        self.assertEqual(status, 201, "checkpoint POST must save through the authenticated HTTP interface")
        checkpoint = saved["checkpoint"]
        self.assertTrue(checkpoint["checkpoint_id"].startswith("listing_edit_"))
        self.assertEqual(checkpoint["fields"], self.body["fields"])
        self.assertEqual(checkpoint["revision"], 1)
        self.assertEqual(checkpoint["source"], "merchant_edit")
        self.assertFalse(saved["model_called"] or saved["usage_consumed"] or saved["real_platform_writes_enabled"])
        status, read = self.request(self.path + self.query)
        self.assertEqual(status, 200)
        self.assertEqual(read["checkpoint"], checkpoint)
        self.assertEqual(read["current_base_report_id"], self.base_report_id)
        self.assertFalse(read["base_changed"])
        self.assertEqual(self.request("/tasks")[1], before_tasks)
        self.assertEqual(self.request("/reports")[1], before_reports)

    def test_browser_inputs_save_and_restore_through_real_http(self):
        node = shutil.which("node")
        self.assertIsNotNone(node, "Node is required for the real browser-to-HTTP integration")
        before_tasks = self.request("/tasks")[1]
        before_reports = self.request("/reports")[1]
        base = self.request(self.path + self.query)[1]["current_base_report"]
        result = subprocess.run(
            [node, str(ROOT / "tools/test_jiejing_listing_cloud_checkpoint_http_smoke.js")],
            cwd=ROOT, text=True, encoding="utf-8", capture_output=True, timeout=45,
            input=json.dumps({"api_base": self.base, "session_token": self.token,
                              "profile": self.request("/me")[1], "store_id": self.store_id,
                              "identity": self.identity, "base_report": base}),
        )
        # Never surface child output containing local session material on failure.
        self.assertEqual(result.returncode, 0, "real browser-to-HTTP checkpoint smoke failed")
        evidence = json.loads(result.stdout)
        self.assertEqual(evidence["visible_controls"], 8)
        self.assertEqual(evidence["post_count"], 2)
        self.assertEqual(evidence["restored_publish_fields"], 9)
        self.assertGreaterEqual(evidence["get_count"], 2)
        self.assertEqual(evidence["restored_fields"], 10)
        status, read = self.request(self.path + self.query)
        self.assertEqual(status, 200)
        self.assertEqual(read["checkpoint"]["fields"]["title"], "")
        self.assertEqual(read["checkpoint"]["fields"]["description"], "Merchant FAL description stays exact")
        self.assertEqual(read["current_revision"], 2)
        self.assertEqual(read["checkpoint"]["publish_intake"]["values"]["shipping_cost"], "4.20")
        self.assertEqual(read["checkpoint"]["publish_intake"]["values"]["title"], "")
        self.assertEqual(self.request("/tasks")[1], before_tasks)
        self.assertEqual(self.request("/reports")[1], before_reports)

    def _browser_unchanged_fact_roundtrip(self, *, source_is_image=False, saved_fact_noop=False):
        """Actual DOM -> fact POST -> checkpoint CAS, including a cold reload."""
        node = shutil.which("node")
        self.assertIsNotNone(node, "Node is required for the real wizard-to-HTTP integration")
        packet = {
            "product_name": "Gold wood-handled measuring set", "simulation_only": True,
            "source": "backend_product_vision_extraction",
            "vision_contract_version": "jiejing_ai_ceo_product_vision_intake_v1",
            "buyer_copy_requires_validated_listing_generation": True,
            "merchant_confirmed_facts": {
                "product_name": "Gold wood-handled measuring set", "condition": "NEW",
                "material": "Gold-tone metal and wood", "source_url": "https://supplier.example.test/gold-set",
                "sku": "SIM-GOLD-SET", "package_weight_g": "380", "package_length_cm": "22",
                "package_width_cm": "12", "package_height_cm": "5", "unit_cost": "2.50",
                "selling_price": "12.99", "currency": "USD", "quantity": "10",
                "item_location": "CN / Shenzhen", "handling_time_days": "3",
                "image_urls": "https://media.example.test/approved-gold-set.jpg", "image_rights_confirmed": True,
            },
            "field_evidence": {"material": {"source_type": "merchant_image", "image_indexes": [0],
                                             "confidence": 0.9, "merchant_confirmation_received": True}},
            "source_records": [{"type": "merchant_product_image", "asset_id": "local-historical-upload",
                                "sha256": "ab" * 32, "original_filename": "fixture.jpg", "source_index": 0,
                                "width": 640, "height": 640, "rights_status": "pending_merchant_confirmation",
                                "signed_url_persisted": False}],
            "fact_conflicts": [],
        }
        if source_is_image:
            packet["merchant_confirmed_facts"]["source_url"] = packet["merchant_confirmed_facts"]["image_urls"]
        if saved_fact_noop:
            # A previously saved editor already carries its safe suggestions.
            # The next image-step save therefore reuses the older fact head,
            # while the newer validated Listing remains the checkpoint base.
            packet["derived_listing_suggestions"] = {
                key: value for key, value in packet["merchant_confirmed_facts"].items()
                if key != "image_rights_confirmed"
            }
        action = self.fact_action("Gold-tone metal and wood", self.base_report_id)
        action["merchant_product_fact_packet"] = packet
        status, saved = self.request(f"/stores/{self.store_id}/product-facts", method="POST", body=action)
        self.assertEqual(status, 201)
        self.base_report_id = saved["report"]["report_id"]
        # Minimized production pattern: an older scoped report has the same
        # selected image URL pending; the current saved packet confirms it.
        # Restoring history must not revive the obsolete rights observation.
        historical_id = self.report_fixture("wizard_old_pending", "merchant.product_facts",
                                            (datetime.now().astimezone() - timedelta(minutes=1)).isoformat())
        historical = copy.deepcopy(saved["report"]["report"])
        for record in historical["merchant_product_fact_packet"]["source_records"]:
            if record.get("url") == packet["merchant_confirmed_facts"]["image_urls"]:
                record.update(rights_status="pending_merchant_confirmation", signed_url_persisted=False)
        with closing(sqlite3.connect(self.root / "saas.sqlite")) as conn, conn:
            conn.execute("update reports set report_json = ? where report_id = ?", (json.dumps(historical), historical_id))
        fields = {key: "" for key in FIELD_KEYS}
        fields.update(title="Gold-Tone Measuring Set", selling_points="4 cups\n4 spoons\nWood handles",
                      description="Eight gold-tone pieces with wood handles", category="Measuring Cups and Spoons",
                      item_specifics="Material: Gold-tone metal and wood", price="12.99",
                      images=packet["merchant_confirmed_facts"]["image_urls"], logistics="Shenzhen, China")
        # Seed a historical generation artifact, not a provider call. All later
        # reads, fact saves and checkpoint changes use the real HTTP handlers.
        listing_id = self.report_fixture("wizard_generation", "listing.package", datetime.now().astimezone().isoformat())
        generated = {"contract_version": "listing_ai_draft_generation_v1", "product": packet["product_name"],
                     "listing_project_identity": self.identity,
                     "merchant_product_fact_packet": saved["merchant_product_fact_packet"],
                     "listing_handoff": {"ready_for_listing_draft": True, "source_mode": "project_scoped_live_model",
                         "target_report_type": "listing.package", "listing_fields": {
                             **fields, "selling_points": fields["selling_points"].splitlines(),
                             "description_seed": fields["description"]}}}
        with closing(sqlite3.connect(self.root / "saas.sqlite")) as conn, conn:
            conn.execute("update reports set report_json = ?, runtime_run_id = ? where report_id = ?",
                         (json.dumps(generated), "listing_draft_generation", listing_id))
        body = {**self.body, "base_report_id": listing_id, "fields": fields, "merchant_edited_fields": []}
        self.assertEqual(self.request(self.path, method="POST", body=body)[0], 201)
        result = subprocess.run(
            [node, str(ROOT / "tools/test_jiejing_listing_cloud_checkpoint_http_smoke.js")],
            cwd=ROOT, text=True, encoding="utf-8", capture_output=True, timeout=90,
            input=json.dumps({"scenario": "unchanged-facts-wizard", "api_base": self.base,
                              "session_token": self.token, "profile": self.request("/me")[1],
                              "store_id": self.store_id, "identity": self.identity, "expected_copy": fields,
                              "saved_fact_noop": saved_fact_noop}),
        )
        # The child emits an allowlisted diagnostic, never a raw exception,
        # request header, cookie, session value or browser trace.
        self.assertEqual(result.returncode, 0, "real unchanged-facts wizard failed: " + result.stderr)
        evidence = json.loads(result.stdout)
        self.assertEqual(evidence["scenario"], "unchanged-facts-wizard")
        self.assertTrue(evidence["no_conflict"])
        self.assertTrue(evidence["server_packets_equal"])
        self.assertEqual(evidence["restored_publish_fields"], 35)
        self.assertEqual(evidence["external_requests"], 0)
        self.assertEqual(evidence["page_errors"], 0)
        if saved_fact_noop:
            self.assertTrue(evidence["initial_fact_save_unchanged"])
            self.assertEqual(evidence["initial_checkpoint_base_type"], "listing.package")

    def test_browser_unchanged_facts_keep_cloud_copy_after_wizard_roundtrip(self):
        self._browser_unchanged_fact_roundtrip()

    def test_browser_source_link_and_image_at_same_url_keep_both_authoritative_records(self):
        self._browser_unchanged_fact_roundtrip(source_is_image=True)

    def test_browser_reused_fact_head_keeps_newer_listing_base_and_completes_wizard(self):
        self._browser_unchanged_fact_roundtrip(saved_fact_noop=True)

    def fact_action(self, material, expected, *, mutation=None, identity=None):
        body = copy.deepcopy(self.fact_body)
        body["listing_project_identity"] = identity or self.identity
        body["merchant_product_fact_packet"]["merchant_confirmed_facts"]["material"] = material
        body["save_context"] = {"contract_version": "merchant_product_fact_save_v1",
                                "mutation_id": mutation or str(uuid.uuid4()),
                                "expected_fact_report_id": expected}
        return body

    def test_fact_actions_a_b_a_create_a_new_authoritative_report(self):
        path = f"/stores/{self.store_id}/product-facts"
        before_a = self.base_report_id
        status, b = self.request(path, method="POST", body=self.fact_action("Wood", before_a))
        self.assertEqual(status, 201)
        status, a = self.request(path, method="POST", body=self.fact_action("Aluminum", b["report"]["report_id"]))
        self.assertEqual(status, 201, "an intentional A after B is a new action, not the first A's delivery retry")
        self.assertNotEqual(before_a, a["report"]["report_id"])
        self.assertEqual(a["report"]["report_id"], self.request(self.path + self.query)[1]["current_base_report_id"])
        self.assertTrue(a["is_current"])
        self.assertEqual(a["current_fact_report_id"], a["report"]["report_id"])

    def test_legacy_fact_retry_only_replays_current_and_cannot_overwrite_modern_scope(self):
        path = f"/stores/{self.store_id}/product-facts"
        self.assertEqual(self.request(path, method="POST", body=self.fact_body)[0], 200)
        legacy_b = copy.deepcopy(self.fact_body)
        legacy_b["merchant_product_fact_packet"]["merchant_confirmed_facts"]["material"] = "Wood"
        status, b = self.request(path, method="POST", body=legacy_b)
        self.assertEqual(status, 201)
        before_reports = self.request("/reports")[1]
        status, stale = self.request(path, method="POST", body=self.fact_body)
        self.assertEqual(status, 409)
        self.assertEqual(stale["error_code"], "product_fact_client_upgrade_required")
        self.assertEqual(self.request("/reports")[1], before_reports)
        modern = self.fact_action("Wood", b["report"]["report_id"])
        status, modern_b = self.request(path, method="POST", body=modern)
        self.assertEqual(status, 201)
        self.assertEqual(self.request(path, method="POST", body=legacy_b)[0], 409)
        # A later independent vision-style fact report must not erase the scope's
        # historical modern-client protection.
        vision = self.report_fixture("later_vision", "merchant.product_facts", "2100-01-01T00:00:00+00:00")
        status, rejected = self.request(path, method="POST", body=legacy_b)
        self.assertEqual(status, 409)
        self.assertEqual(rejected["current_fact_report_id"], vision)
        self.assertNotEqual(vision, modern_b["report"]["report_id"])

    def test_old_fact_action_replay_returns_original_receipt_without_advancing_current(self):
        path = f"/stores/{self.store_id}/product-facts"
        action = self.fact_action("Wood", self.base_report_id)
        status, original = self.request(path, method="POST", body=action)
        self.assertEqual(status, 201)
        status, later = self.request(path, method="POST", body=self.fact_action("Steel", original["report"]["report_id"]))
        self.assertEqual(status, 201)
        before_tasks, before_reports = self.request("/tasks")[1], self.request("/reports")[1]
        status, replay = self.request(path, method="POST", body=action)
        self.assertEqual(status, 200)
        self.assertTrue(replay["idempotent_replay"])
        self.assertFalse(replay["is_current"])
        self.assertEqual(replay["task"], original["task"])
        self.assertEqual(replay["report"], original["report"])
        self.assertEqual(replay["current_fact_report_id"], later["report"]["report_id"])
        self.assertEqual(replay["current_fact_report"], later["report"])
        self.assertEqual(self.request(self.path + self.query)[1]["current_base_report_id"], later["report"]["report_id"])
        for field in ("packet", "expected"):
            changed = copy.deepcopy(action)
            if field == "packet":
                changed["merchant_product_fact_packet"]["merchant_confirmed_facts"]["material"] = "Plastic"
            else:
                changed["save_context"]["expected_fact_report_id"] = later["report"]["report_id"]
            status, conflict = self.request(path, method="POST", body=changed)
            self.assertEqual(status, 409)
            self.assertEqual(conflict["error_code"], "product_fact_mutation_conflict")
        self.assertEqual(self.request("/tasks")[1], before_tasks)
        self.assertEqual(self.request("/reports")[1], before_reports)

    def test_fact_action_concurrency_and_duplicate_delivery_are_serialized(self):
        path = f"/stores/{self.store_id}/product-facts"
        actions = [self.fact_action(material, self.base_report_id) for material in ("Wood", "Steel")]
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda body: self.request(path, method="POST", body=body), actions))
        self.assertEqual(sorted(status for status, _ in results), [201, 409])
        winner = next(body for status, body in results if status == 201)
        loser = next(body for status, body in results if status == 409)
        self.assertEqual(loser["error_code"], "product_fact_version_conflict")
        self.assertEqual(loser["current_fact_report"], winner["report"])
        action = self.fact_action("Aluminum", winner["report"]["report_id"])
        with ThreadPoolExecutor(max_workers=3) as pool:
            results = list(pool.map(lambda _: self.request(path, method="POST", body=action), range(3)))
        self.assertEqual(sorted(status for status, _ in results), [200, 200, 201])
        self.assertEqual(len({body["report"]["report_id"] for _, body in results}), 1)
        self.assertEqual(len({body["task"]["task_id"] for _, body in results}), 1)

    def test_invalid_fact_save_context_does_not_create_records(self):
        path = f"/stores/{self.store_id}/product-facts"
        valid = self.fact_action("Wood", self.base_report_id)
        contexts = [None, [], "legacy", {}, {**valid["save_context"], "contract_version": "other"},
                    {**valid["save_context"], "unknown": True}]
        for field, values in (("mutation_id", (None, True, 123, "short", "x" * 161, "bad/id--", "标识123456")),
                              ("expected_fact_report_id", (None, 123, False, [], "x" * 161, "bad/id"))):
            contexts.extend({**valid["save_context"], field: value} for value in values)
        before_tasks, before_reports = self.request("/tasks")[1], self.request("/reports")[1]
        for index, context in enumerate(contexts):
            with self.subTest(context=index):
                status, error = self.request(path, method="POST", body={**valid, "save_context": context})
                self.assertEqual(status, 400)
                self.assertEqual(error["error_code"], "product_fact_invalid_save_context")
        self.assertEqual(self.request("/tasks")[1], before_tasks)
        self.assertEqual(self.request("/reports")[1], before_reports)
        self.assertEqual(self.request(path, method="POST", body=valid)[0], 201)

    def test_fact_action_scopes_and_user_fingerprint_do_not_leak_or_alias(self):
        path = f"/stores/{self.store_id}/product-facts"
        action = self.fact_action("Wood", self.base_report_id)
        _, saved = self.request(path, method="POST", body=action)
        report_ids = {saved["report"]["report_id"]}
        for anchor in ("key", "source_report_id", "candidate_id"):
            scoped = copy.deepcopy(action)
            scoped["listing_project_identity"][anchor] += "other"
            scoped["save_context"]["expected_fact_report_id"] = ""
            status, receipt = self.request(path, method="POST", body=scoped)
            self.assertEqual(status, 201)
            self.assertEqual(receipt["listing_project_identity"], scoped["listing_project_identity"])
            report_ids.add(receipt["report"]["report_id"])
        self.assertEqual(len(report_ids), 4)
        _, store = self.request("/stores", method="POST", body={"platform": "ebay", "store_name": "Fact scope other", "marketplace": "EBAY_US"})
        scoped = copy.deepcopy(action)
        scoped["save_context"]["expected_fact_report_id"] = ""
        status, other_store = self.request(f"/stores/{store['store']['store_id']}/product-facts", method="POST", body=scoped)
        self.assertEqual(status, 201)
        self.assertNotIn(other_store["report"]["report_id"], report_ids)
        password = "local-fact-user-fixture-pass"
        email = "fact-other-" + uuid.uuid4().hex + "@local.invalid"
        status, user = self.request("/auth/register", method="POST", token="", body={
            "email": email, "password": password, "company_name": "Other fact tenant"})
        self.assertEqual(status, 201)
        status, forbidden = self.request(path, method="POST", body=action, token=user["token"])
        self.assertEqual(status, 404)
        self.assertNotIn(saved["report"]["report_id"], json.dumps(forbidden))
        # Synthetic membership at the DB boundary; the subsequent login and
        # request still run real authentication and create_task permission checks.
        with closing(sqlite3.connect(self.root / "saas.sqlite")) as conn, conn:
            conn.execute("insert into team_members(company_id,user_id,role,created_at) values (?,?,'admin',?)",
                         (self.company_id, user["user"]["user_id"], "2026-09-07T00:00:00+00:00"))
            conn.execute("update users set default_company_id = ? where user_id = ?", (self.company_id, user["user"]["user_id"]))
        status, login = self.request("/auth/login", method="POST", token="", body={"email": email, "password": password})
        self.assertEqual(status, 200)
        status, conflict = self.request(path, method="POST", body=action, token=login["token"])
        self.assertEqual(status, 409)
        self.assertEqual(conflict["error_code"], "product_fact_mutation_conflict")

    def test_legacy_fact_digest_binds_all_identity_anchors(self):
        path = f"/stores/{self.store_id}/product-facts"
        for anchor in ("source_report_id", "candidate_id"):
            changed = copy.deepcopy(self.fact_body)
            changed["listing_project_identity"][anchor] = "legacy-other-anchor"
            status, saved = self.request(path, method="POST", body=changed)
            self.assertEqual(status, 201)
            self.assertNotEqual(saved["report"]["report_id"], self.base_report_id)
            self.assertEqual(saved["listing_project_identity"], changed["listing_project_identity"])
            self.assertEqual(self.request(path, method="POST", body=changed)[0], 200)

    def test_new_fact_report_is_ordered_after_same_millisecond_primary_base(self):
        path = f"/stores/{self.store_id}/product-facts"
        previous_time = "2100-01-01T00:00:00.123456+00:00"
        previous = self.report_fixture("future_listing", "listing.package", previous_time)
        self.report_fixture("future_research", "ai_ceo.market_research", "2200-01-01T00:00:00+00:00")
        status, saved = self.request(path, method="POST", body=self.fact_action("Wood", self.base_report_id))
        self.assertEqual(status, 201)
        created = datetime.fromisoformat(saved["report"]["created_at"])
        self.assertGreaterEqual(created - datetime.fromisoformat(previous_time), timedelta(milliseconds=1))
        self.assertEqual(created.year, 2100, "research fallback must not displace a primary fact/Listing base")
        self.assertEqual(self.request(self.path + self.query)[1]["current_base_report_id"], saved["report"]["report_id"])
        with closing(sqlite3.connect(self.root / "saas.sqlite")) as conn:
            self.assertEqual(conn.execute("select created_at from reports where report_id = ?", (previous,)).fetchone()[0], previous_time)
            self.assertEqual(conn.execute("select created_at from reports where report_id = ?", (saved["report"]["report_id"],)).fetchone()[0], saved["report"]["created_at"])
        status, next_saved = self.request(path, method="POST", body=self.fact_action("Steel", saved["report"]["report_id"]))
        self.assertEqual(status, 201)
        self.assertGreaterEqual(datetime.fromisoformat(next_saved["report"]["created_at"]) - created, timedelta(milliseconds=1))

    def test_incomplete_report_identity_is_not_an_empty_anchor_fact_scope(self):
        self.report_fixture("incomplete_fact", "merchant.product_facts", "2200-01-01T00:00:00+00:00",
                            identity={"key": self.identity["key"]})
        status, saved = self.request(f"/stores/{self.store_id}/product-facts", method="POST",
                                     body=self.fact_action("Wood", self.base_report_id))
        self.assertEqual(status, 201, "missing report anchors are not the same identity as explicit empty anchors")
        self.assertLess(datetime.fromisoformat(saved["report"]["created_at"]).year, 2200)

    def test_mixed_offset_primary_base_does_not_hide_a_newer_fact_action(self):
        previous_time = "2100-01-01T08:00:00.123456+08:00"
        old_id = self.report_fixture("offset_listing", "listing.package", previous_time)
        status, saved = self.request(f"/stores/{self.store_id}/product-facts", method="POST",
                                     body=self.fact_action("Wood", self.base_report_id))
        self.assertEqual(status, 201)
        self.assertGreaterEqual(datetime.fromisoformat(saved["report"]["created_at"]) - datetime.fromisoformat(previous_time), timedelta(milliseconds=1))
        self.assertEqual(self.request(self.path + self.query)[1]["current_base_report_id"], saved["report"]["report_id"])
        with closing(sqlite3.connect(self.root / "saas.sqlite")) as conn:
            self.assertEqual(conn.execute("select created_at from reports where report_id=?", (old_id,)).fetchone()[0], previous_time)

    def test_independent_fact_report_writer_updates_authority_without_a_model_call(self):
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        from jiejing_saas.repository import SaaSRepository
        repository = SaaSRepository(self.root / "saas.sqlite", database_engine="sqlite", database_url="")
        future = "2100-01-01T00:00:00.333000+00:00"
        self.report_fixture("vision_previous_listing", "listing.package", future)
        task = repository.create_task(company_id=self.company_id, store_id=self.store_id, user_id=self.user_id,
                                      task_type="product_vision", title="Synthetic report writer", input_data={})
        # Exercise the same independent storage entry as vision, with no client,
        # provider adapter, upload, model or outbound request.
        report = repository.save_merchant_product_fact_report(
            task=task, packet={"source": "backend_product_vision_extraction", "product_name": "Foldable Tablet Stand",
                               "unknown_facts": ["material"]}, listing_project_identity=self.identity)
        self.assertGreaterEqual(datetime.fromisoformat(report["created_at"]) - datetime.fromisoformat(future), timedelta(milliseconds=1))
        status, conflict = self.request(f"/stores/{self.store_id}/product-facts", method="POST",
                                        body=self.fact_action("Wood", self.base_report_id))
        self.assertEqual(status, 409)
        self.assertEqual(conflict["error_code"], "product_fact_version_conflict")
        self.assertEqual(conflict["current_fact_report_id"], report["report_id"])
        self.assertEqual(conflict["current_fact_report"]["created_at"], report["created_at"])

    def test_pre_action_digest_legacy_receipt_replays_only_in_its_exact_scope(self):
        import hashlib
        # Materialize the previous release's deterministic IDs without changing
        # its payload or timestamps; this is migration-free compatibility data.
        with closing(sqlite3.connect(self.root / "saas.sqlite")) as conn, conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("select r.*,t.company_id,t.store_id from reports r join tasks t on t.task_id=r.task_id where r.report_id=?",
                               (self.base_report_id,)).fetchone()
            payload = json.loads(row["report_json"])
            content = json.dumps({"company_id": self.company_id, "store_id": self.store_id,
                "project_key": self.identity["key"], "packet": payload["merchant_product_fact_packet"]},
                sort_keys=True, ensure_ascii=False, separators=(",", ":"))
            digest = hashlib.sha256(content.encode()).hexdigest()[:40]
            old_report, old_task = f"report_product_facts_{digest}", f"task_product_facts_{digest}"
            conn.execute("update tasks set task_id=? where task_id=?", (old_task, row["task_id"]))
            conn.execute("update reports set report_id=?,task_id=? where report_id=?", (old_report, old_task, self.base_report_id))
        path = f"/stores/{self.store_id}/product-facts"
        status, replay = self.request(path, method="POST", body=self.fact_body)
        self.assertEqual(status, 200)
        self.assertEqual(replay["report"]["report_id"], old_report)
        different = copy.deepcopy(self.fact_body)
        different["listing_project_identity"]["candidate_id"] = "another-old-scope"
        status, separate = self.request(path, method="POST", body=different)
        self.assertEqual(status, 201)
        self.assertNotEqual(separate["report"]["report_id"], old_report)
        changed = copy.deepcopy(self.fact_body)
        changed["merchant_product_fact_packet"]["merchant_confirmed_facts"]["material"] = "Wood"
        self.assertEqual(self.request(path, method="POST", body=changed)[0], 201)
        self.assertEqual(self.request(path, method="POST", body=self.fact_body)[0], 409)

    def test_fact_action_audit_failure_rolls_back_task_report_memory_and_mutation(self):
        action = self.fact_action("Wood", self.base_report_id)
        path = f"/stores/{self.store_id}/product-facts"
        before_tasks, before_reports = self.request("/tasks")[1], self.request("/reports")[1]
        with closing(sqlite3.connect(self.root / "saas.sqlite")) as conn, conn:
            before_memory = conn.execute("select count(*) from merchant_memory").fetchone()[0]
            conn.execute("""create trigger fact_save_audit_fault before insert on audit_logs
                when NEW.action_type = 'merchant.product_facts.saved'
                begin select raise(ABORT, 'fixture fact audit unavailable'); end""")
        try:
            status, failure = self.request(path, method="POST", body=action)
            self.assertEqual(status, 503)
            self.assertEqual(failure["error_code"], "product_fact_storage_unavailable")
            self.assertNotIn("fixture fact", json.dumps(failure))
            self.assertEqual(self.request("/tasks")[1], before_tasks)
            self.assertEqual(self.request("/reports")[1], before_reports)
            self.assertEqual(self.request(self.path + self.query)[1]["current_base_report_id"], self.base_report_id)
            with closing(sqlite3.connect(self.root / "saas.sqlite")) as conn:
                self.assertEqual(conn.execute("select count(*) from merchant_memory").fetchone()[0], before_memory)
        finally:
            with closing(sqlite3.connect(self.root / "saas.sqlite")) as conn, conn:
                conn.execute("drop trigger fact_save_audit_fault")
        self.assertEqual(self.request(path, method="POST", body=action)[0], 201)

    def test_revision_cas_and_explicit_clear(self):
        self.assertEqual(self.request(self.path, method="POST", body=self.body)[0], 201)
        updated = copy.deepcopy(self.body)
        updated.update(expected_revision=1, mutation_id=str(uuid.uuid4()))
        updated["fields"]["title"] = ""
        status, saved = self.request(self.path, method="POST", body=updated)
        self.assertEqual(status, 201)
        self.assertEqual(saved["checkpoint"]["revision"], 2)
        self.assertEqual(saved["checkpoint"]["fields"]["title"], "")
        stale = copy.deepcopy(self.body)
        stale["mutation_id"] = str(uuid.uuid4())
        status, conflict = self.request(self.path, method="POST", body=stale)
        self.assertEqual(status, 409)
        self.assertEqual(conflict["error_code"], "listing_draft_revision_conflict")
        self.assertEqual(conflict["latest_checkpoint"], saved["checkpoint"])
        self.assertEqual(self.request(self.path + self.query)[1]["checkpoint"], saved["checkpoint"])

    def test_mutation_retry_returns_exact_original_receipt_after_later_edits(self):
        status, original = self.request(self.path, method="POST", body=self.body)
        self.assertEqual(status, 201)
        second = copy.deepcopy(self.body)
        second.update(expected_revision=1, mutation_id=str(uuid.uuid4()))
        second["fields"]["title"] = "Version B"
        self.assertEqual(self.request(self.path, method="POST", body=second)[0], 201)
        third = copy.deepcopy(self.body)
        third.update(expected_revision=2, mutation_id=str(uuid.uuid4()))
        status, latest = self.request(self.path, method="POST", body=third)
        self.assertEqual(status, 201)
        self.assertEqual(latest["checkpoint"]["revision"], 3)
        self.assertNotEqual(latest["checkpoint"]["checkpoint_id"], original["checkpoint"]["checkpoint_id"])
        status, replay = self.request(self.path, method="POST", body=self.body)
        self.assertEqual(status, 200)
        self.assertTrue(replay["idempotent_replay"])
        self.assertEqual(replay["checkpoint"], original["checkpoint"])
        self.assertEqual(self.request(self.path + self.query)[1]["checkpoint"], latest["checkpoint"])
        changed = copy.deepcopy(self.body)
        changed["fields"]["title"] = "Cannot reuse a mutation for other content"
        status, conflict = self.request(self.path, method="POST", body=changed)
        self.assertEqual(status, 409)
        self.assertEqual(conflict["error_code"], "listing_draft_mutation_conflict")

    def test_new_fact_base_preserves_old_checkpoint_and_replay_but_rejects_new_stale_save(self):
        _, original = self.request(self.path, method="POST", body=self.body)
        changed_facts = copy.deepcopy(self.fact_body)
        changed_facts["merchant_product_fact_packet"]["merchant_confirmed_facts"]["material"] = "Wood"
        status, facts = self.request(f"/stores/{self.store_id}/product-facts", method="POST", body=changed_facts)
        self.assertEqual(status, 201)
        _, read = self.request(self.path + self.query)
        self.assertTrue(read["base_changed"])
        self.assertEqual(read["checkpoint"], original["checkpoint"])
        self.assertEqual(read["current_base_report_id"], facts["report"]["report_id"])
        status, profile = self.request("/me")
        self.assertEqual(status, 200)
        owner_id = profile["identity"]["user_id"]
        self.assertEqual(owner_id, profile["user"]["user_id"])
        self.assertEqual(facts["task"]["user_id"], owner_id)
        self.assertEqual(read["current_base_report"]["user_id"], owner_id)
        # Checkpoint reads include the authenticated task author. Preserve the
        # complete fact-report contract as well; do not discard any DTO fields.
        self.assertEqual(read["current_base_report"], {"user_id": owner_id, **facts["report"]})
        self.assertEqual(self.request(self.path, method="POST", body=self.body)[0], 200)
        stale = copy.deepcopy(self.body)
        stale.update(expected_revision=1, mutation_id=str(uuid.uuid4()))
        status, conflict = self.request(self.path, method="POST", body=stale)
        self.assertEqual(status, 409)
        self.assertEqual(conflict["error_code"], "listing_draft_base_conflict")
        stale["base_report_id"] = facts["report"]["report_id"]
        status, rebased = self.request(self.path, method="POST", body=stale)
        self.assertEqual(status, 201, "a rejected attempt must not consume its mutation")
        self.assertEqual(rebased["checkpoint"]["revision"], 2)

    def test_invalid_or_trust_bearing_input_is_rejected_before_persistence(self):
        bad_values = []
        for key, value in (("model_generated", True), ("ready_for_publish", True),
                           ("merchant_product_fact_packet", {}), ("snapshot", {})):
            bad = copy.deepcopy(self.body)
            bad[key] = value
            bad_values.append(bad)
        for revision in (True, -1, 1.5, "0"):
            bad = copy.deepcopy(self.body)
            bad["expected_revision"] = revision
            bad_values.append(bad)
        for value in (None, 12, [], "x" * 801, "\ud800", "text\u0000value"):
            bad = copy.deepcopy(self.body)
            bad["fields"]["title"] = value
            bad_values.append(bad)
        bad = copy.deepcopy(self.body)
        del bad["fields"]["risk_notes"]
        bad_values.append(bad)
        bad = copy.deepcopy(self.body)
        bad["fields"]["cost_price"] = "10"
        bad_values.append(bad)
        bad = copy.deepcopy(self.body)
        del bad["listing_project_identity"]["candidate_id"]
        bad_values.append(bad)
        bad = copy.deepcopy(self.body)
        bad["listing_project_identity"]["key"] = "another-project"
        bad_values.append(bad)
        for bad in bad_values:
            with self.subTest(case=len(bad_values), keys=list(bad)):
                self.assertEqual(self.request(self.path, method="POST", body=bad)[0], 400)
        secret_shape = "ghp_" + "Z" * 30
        bad = copy.deepcopy(self.body)
        bad["fields"]["description"] = secret_shape
        status, response = self.request(self.path, method="POST", body=bad)
        self.assertEqual(status, 422)
        self.assertNotIn(secret_shape, json.dumps(response))
        self.assertEqual(self.request(self.path)[0], 400, "missing anchors are not blank anchors")
        self.assertEqual(self.request(self.path + self.query + "&candidate_id=other")[0], 400)
        self.assertEqual(self.request(self.path + self.query)[1]["current_revision"], 0)
        self.assertEqual(self.request(self.path, method="POST", body=self.body)[0], 201)

    def test_concurrent_creation_and_duplicate_delivery_use_database_serialization(self):
        bodies = [{**self.body, "mutation_id": str(uuid.uuid4())} for _ in range(5)]
        with ThreadPoolExecutor(max_workers=5) as pool:
            results = list(pool.map(lambda body: self.request(self.path, method="POST", body=body), bodies))
        self.assertEqual(sorted(status for status, _ in results), [201, 409, 409, 409, 409])
        duplicate = {**self.body, "expected_revision": 1, "mutation_id": str(uuid.uuid4())}
        with ThreadPoolExecutor(max_workers=5) as pool:
            results = list(pool.map(lambda _: self.request(self.path, method="POST", body=duplicate), range(5)))
        self.assertEqual(sorted(status for status, _ in results), [200, 200, 200, 200, 201])
        self.assertEqual(len({json.dumps(value["checkpoint"], sort_keys=True) for _, value in results}), 1)
        self.assertEqual(self.request(self.path + self.query)[1]["current_revision"], 2)

    def test_auth_tenant_store_and_each_identity_anchor_are_not_wildcards(self):
        _, saved = self.request(self.path, method="POST", body=self.body)
        self.assertEqual(self.request(self.path + self.query, token="")[0], 401)
        self.assertEqual(self.request(self.path, method="POST", body=self.body, token="")[0], 401)
        status, other = self.request("/auth/register", method="POST", token="", body={
            "email": "other-" + uuid.uuid4().hex + "@local.invalid", "password": "local-checkpoint-other-pass",
            "company_name": "Other checkpoint company"})
        self.assertEqual(status, 201)
        status, response = self.request(self.path + self.query, token=other["token"])
        self.assertEqual(status, 404)
        self.assertNotIn(saved["checkpoint"]["checkpoint_id"], json.dumps(response))
        self.assertEqual(self.request(self.path, method="POST", body=self.body, token=other["token"])[0], 404)
        for key in ("source_report_id", "candidate_id"):
            identity = {**self.identity, key: "different-anchor"}
            query = "?" + urllib.parse.urlencode({k: identity[k] for k in ("source_report_id", "candidate_id")})
            self.assertEqual(self.request(self.path + query)[0], 404)
            wrong = {**self.body, "listing_project_identity": identity, "mutation_id": str(uuid.uuid4())}
            self.assertEqual(self.request(self.path, method="POST", body=wrong)[0], 404)
        status, store = self.request("/stores", method="POST", body={
            "platform": "ebay", "store_name": "Other own store", "marketplace": "EBAY_US"})
        self.assertEqual(status, 201)
        path = self.path.replace(self.store_id, store["store"]["store_id"])
        self.assertEqual(self.request(path + self.query)[0], 404)
        self.assertEqual(self.request(path, method="POST", body=self.body)[0], 404)
        self.assertEqual(self.request(self.path + self.query)[1]["checkpoint"], saved["checkpoint"])

    def test_viewer_can_read_but_cannot_save(self):
        _, saved = self.request(self.path, method="POST", body=self.body)
        company_id = saved["checkpoint"]["company_id"]
        # Role is fixture data at the DB boundary; requests still use real auth/permission handlers.
        with closing(sqlite3.connect(self.root / "saas.sqlite")) as conn, conn:
            conn.execute("update team_members set role = 'viewer' where company_id = ?", (company_id,))
        try:
            self.assertEqual(self.request(self.path + self.query)[0], 200)
            self.assertEqual(self.request(self.path, method="POST", body=self.body)[0], 403)
        finally:
            with closing(sqlite3.connect(self.root / "saas.sqlite")) as conn, conn:
                conn.execute("update team_members set role = 'owner' where company_id = ?", (company_id,))

    def test_audit_storage_failure_rolls_back_revision_head_and_mutation(self):
        _, original = self.request(self.path, method="POST", body=self.body)
        updated = {**self.body, "expected_revision": 1, "mutation_id": str(uuid.uuid4())}
        with closing(sqlite3.connect(self.root / "saas.sqlite")) as conn, conn:
            conn.execute("""create trigger checkpoint_audit_fault before insert on audit_logs
                when NEW.action_type = 'listing.merchant_edit.saved'
                begin select raise(ABORT, 'fixture audit unavailable'); end""")
        try:
            status, failure = self.request(self.path, method="POST", body=updated)
            self.assertEqual(status, 503)
            self.assertNotIn("fixture audit", json.dumps(failure))
            self.assertEqual(self.request(self.path + self.query)[1]["checkpoint"], original["checkpoint"])
        finally:
            with closing(sqlite3.connect(self.root / "saas.sqlite")) as conn, conn:
                conn.execute("drop trigger checkpoint_audit_fault")
        status, retried = self.request(self.path, method="POST", body=updated)
        self.assertEqual(status, 201)
        self.assertEqual(retried["checkpoint"]["revision"], 2)

    def test_http_receipts_preserve_merchant_text_urls_and_identity_verbatim(self):
        self.identity = {"key": self.identity["key"] + "-fal", "source_report_id": "fal-origin",
                         "candidate_id": "fal-candidate"}
        self.fact_body["listing_project_identity"] = self.identity
        _, facts = self.request(f"/stores/{self.store_id}/product-facts", method="POST", body=self.fact_body)
        self.path = f"/stores/{self.store_id}/listing-drafts/{self.identity['key']}/checkpoint"
        self.query = "?" + urllib.parse.urlencode({key: self.identity[key] for key in ("source_report_id", "candidate_id")})
        self.body.update(listing_project_identity=self.identity, base_report_id=facts["report"]["report_id"],
                         mutation_id="save-fal-edit-1234")
        self.body["fields"].update(title="FAL display stand", images="https://fal.media/files/image.jpg")
        status, saved = self.request(self.path, method="POST", body=self.body)
        self.assertEqual(status, 201)
        self.assertEqual(saved["checkpoint"]["fields"], self.body["fields"])
        self.assertEqual(saved["checkpoint"]["mutation_id"], self.body["mutation_id"])
        self.assertEqual(saved["checkpoint"]["listing_project_identity"], self.identity)
        _, read = self.request(self.path + self.query)
        self.assertEqual(read["checkpoint"], saved["checkpoint"])
        self.assertEqual(read["current_base_report"]["report"]["listing_project_identity"], self.identity)
        self.assertEqual(self.request(self.path, method="POST", body=self.body)[1]["checkpoint"], saved["checkpoint"])
        stale = {**self.body, "mutation_id": "other-fal-edit-1234"}
        status, conflict = self.request(self.path, method="POST", body=stale)
        self.assertEqual(status, 409)
        self.assertEqual(conflict["latest_checkpoint"], saved["checkpoint"])

    def test_base_query_filters_before_ordering_and_generation_invalidates_old_checkpoint(self):
        _, saved = self.request(self.path, method="POST", body=self.body)
        self.report_fixture("a", "listing.package", "2100-01-01T00:00:00+00:00")
        latest = self.report_fixture("z", "product.listing", "2100-01-01T00:00:00+00:00")
        self.report_fixture("newer_market", "ai_ceo.market_research", "2101-01-01T00:00:00+00:00")
        self.report_fixture("failed", "listing.package", "2102-01-01T00:00:00+00:00", status="failed")
        self.report_fixture("other_candidate", "listing.package", "2103-01-01T00:00:00+00:00",
                            identity={**self.identity, "candidate_id": "other"})
        self.report_fixture("other_project", "listing.package", "2104-01-01T00:00:00+00:00",
                            identity={**self.identity, "key": "listing-project-other"})
        self.report_fixture("incomplete", "listing.package", "2105-01-01T00:00:00+00:00",
                            identity={"key": self.identity["key"]})
        status, read = self.request(self.path + self.query)
        self.assertEqual(status, 200)
        self.assertEqual(read["current_base_report_id"], latest)
        self.assertTrue(read["base_changed"])
        self.assertEqual(read["checkpoint"], saved["checkpoint"])
        stale = {**self.body, "expected_revision": 1, "mutation_id": str(uuid.uuid4())}
        self.assertEqual(self.request(self.path, method="POST", body=stale)[1]["error_code"], "listing_draft_base_conflict")

    def test_historical_generation_is_exact_scope_and_excludes_unadopted_or_invalid_reports(self):
        def generation(suffix, *, identity=None, valid=True, pending_rewrite=False):
            rid = self.report_fixture(suffix, "listing.package", "2020-01-01T00:00:00+00:00", identity=identity)
            with closing(sqlite3.connect(self.root / "saas.sqlite")) as conn, conn:
                body = json.loads(conn.execute("select report_json from reports where report_id=?", (rid,)).fetchone()[0])
                body.update(contract_version="listing_ai_draft_generation_v1", listing_handoff={
                    "source_mode": "project_scoped_live_model", "ready_for_listing_draft": True,
                    "listing_fields": {}})
                if not valid:
                    body["listing_handoff"] = []
                if pending_rewrite:
                    body["listing_handoff"]["listing_fields"]["buyer_copy_rewrite"] = {
                        "contract_version": "listing_buyer_copy_rewrite_v1", "expected_base_report_id": self.base_report_id,
                        "expected_checkpoint_revision": 0}
                conn.execute("update reports set runtime_run_id=?,report_json=? where report_id=?",
                    ("listing_draft_generation", json.dumps(body), rid))
            return rid

        for key in ("key", "source_report_id", "candidate_id"):
            generation("foreign_" + key, identity={**self.identity, key: "foreign"})
        generation("invalid", valid=False)
        generation("unadopted_rewrite", pending_rewrite=True)
        status, empty = self.request(self.path + self.query)
        self.assertEqual(status, 200)
        self.assertIsNone(empty.get("validated_generation_report"))
        rid = generation("valid")
        before = self.request("/reports")[1]
        status, read = self.request(self.path + self.query)
        self.assertEqual(status, 200)
        self.assertEqual(read["current_base_report_id"], self.base_report_id)
        self.assertEqual(read["validated_generation_report"]["report_id"], rid)
        self.assertEqual(read["validated_generation_report"]["company_id"], self.company_id)
        self.assertEqual(read["validated_generation_report"]["store_id"], self.store_id)
        self.assertEqual(read["validated_generation_report"]["report"]["listing_project_identity"], self.identity)
        self.assertEqual(self.request("/reports")[1], before)
        self.assertFalse(read["model_called"] or read["usage_consumed"] or read["real_platform_writes_enabled"])

    def test_fact_head_remains_independent_of_newer_copy_and_rejects_other_origins(self):
        facts = self.report_fixture("current_facts", "merchant.product_facts", "2090-01-01T00:00:00+00:00")
        copy_report = self.report_fixture("newer_copy", "listing.package", "2091-01-01T00:00:00+00:00")
        for key in ("key", "source_report_id", "candidate_id"):
            self.report_fixture("foreign_facts_" + key, "merchant.product_facts", "2092-01-01T00:00:00+00:00",
                                identity={**self.identity, key: "foreign"})
        self.report_fixture("failed_facts", "merchant.product_facts", "2093-01-01T00:00:00+00:00", status="failed")
        before = self.request("/reports")[1]
        status, read = self.request(self.path + self.query)
        self.assertEqual(status, 200)
        self.assertEqual(read["current_base_report_id"], copy_report)
        self.assertEqual(read["current_product_fact_report"]["report_id"], facts)
        self.assertEqual(read["current_product_fact_report"]["company_id"], self.company_id)
        self.assertEqual(read["current_product_fact_report"]["store_id"], self.store_id)
        self.assertEqual(read["current_product_fact_report"]["report"]["listing_project_identity"], self.identity)
        self.assertEqual(self.request("/reports")[1], before)
        self.assertFalse(read["model_called"] or read["usage_consumed"] or read["real_platform_writes_enabled"])

    def test_market_fallback_requires_each_explicit_anchor(self):
        with closing(sqlite3.connect(self.root / "saas.sqlite")) as conn, conn:
            conn.execute("update reports set status = 'failed' where report_id = ?", (self.base_report_id,))
        self.report_fixture("missing_anchor_market", "ai_ceo.market_research", "2101-01-01T00:00:00+00:00",
                            identity={"key": self.identity["key"]})
        self.assertEqual(self.request(self.path + self.query)[0], 404)
        market = self.report_fixture("complete_market", "ai_ceo.market_research", "2100-01-01T00:00:00+00:00")
        status, read = self.request(self.path + self.query)
        self.assertEqual(status, 200)
        self.assertEqual(read["status"], "empty")
        self.assertEqual(read["current_base_report_id"], market)
        self.body["base_report_id"] = market
        self.assertEqual(self.request(self.path, method="POST", body=self.body)[0], 201)


class ProductImageCheckpointHTTPTests(unittest.TestCase):
    # An independent localhost server keeps these added regression requests out
    # of the existing suite's rate-limit window. Production limits stay intact.
    setUpClass = classmethod(CheckpointHTTPTests.setUpClass.__func__)
    tearDownClass = classmethod(CheckpointHTTPTests.tearDownClass.__func__)
    request = classmethod(CheckpointHTTPTests.request.__func__)
    setUp = CheckpointHTTPTests.setUp
    fact_action = CheckpointHTTPTests.fact_action

    def test_product_image_urls_survive_fact_save_and_cold_report_restore(self):
        urls = "https://v3b.fal.media/files/b/fixture/gold-set.jpg https://fal.media/files/detail.jpg"
        action = self.fact_action("Gold-tone metal and wood", self.base_report_id)
        action["merchant_product_fact_packet"]["merchant_confirmed_facts"].update(
            image_urls=urls, image_rights_confirmed=True)
        action["merchant_product_fact_packet"]["simulation_only"] = True
        status, saved = self.request(f"/stores/{self.store_id}/product-facts", method="POST", body=action)
        self.assertEqual(status, 201)
        # Real save receipt and the same cold-start report route used by the browser.
        for response in (saved, self.request(self.path + self.query)[1]):
            report = response.get("current_base_report") or response["report"]
            packet = report["report"]["merchant_product_fact_packet"]
            self.assertEqual(packet["merchant_confirmed_facts"]["image_urls"].split(), urls.split())
            self.assertTrue(packet["merchant_confirmed_facts"]["image_rights_confirmed"])
            self.assertTrue(packet["simulation_only"])
            self.assertIn("simulation_only_product_facts", packet["blocked_by"])
            image_sources = [r["url"] for r in packet["source_records"] if r["type"] == "merchant_product_image"]
            self.assertEqual(image_sources, urls.split())
        _, replayed = self.request(f"/stores/{self.store_id}/product-facts", method="POST", body=action)
        self.assertEqual(replayed["report"], saved["report"])

    def test_multiple_reviewed_image_lines_are_not_silently_dropped(self):
        urls = ["https://v3b.fal.media/files/b/fixture/gold-set.jpg", "https://fal.media/files/detail.jpg"]
        current_id = self.base_report_id
        for separator in ("\n", "\r\n"):
            action = self.fact_action("Gold-tone metal and wood", current_id)
            action["merchant_product_fact_packet"]["merchant_confirmed_facts"].update(
                image_urls=separator.join(urls), image_rights_confirmed=True)
            status, saved = self.request(f"/stores/{self.store_id}/product-facts", method="POST", body=action)
            self.assertEqual(status, 201)
            current_id = saved["report"]["report_id"]
            packet = self.request(self.path + self.query)[1]["current_base_report"]["report"]["merchant_product_fact_packet"]
            self.assertEqual(packet["merchant_confirmed_facts"].get("image_urls", "").split(), urls)
            self.assertNotIn("image_urls", packet["unknown_facts"])


if __name__ == "__main__":
    unittest.main()
