#!/usr/bin/env python3
"""Local HTTP regressions for merchant saves of vision-origin product facts.

Only synthetic products are used. No model, eBay, payment, or external network
is available to the child backend; its database is temporary SQLite.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
import subprocess
import sqlite3
import sys
import tempfile
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.test_jiejing_ai_ceo_routing_supplier_http_red import (
    free_port, isolated_backend_env, request_json, wait_for_health,
)
from jiejing_saas.repository import SaaSRepository, normalize_merchant_product_fact_packet
from jiejing_saas.publish_source_rights import build_merchant_fact_save_attestation


class ProductFactAuthHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="jiejing-fact-auth-http-", ignore_cleanup_errors=True)
        root = Path(cls.temp.name)
        cls.db = root / "saas.sqlite"
        hook = root / "hook"
        hook.mkdir()
        (hook / "sitecustomize.py").write_text(
            "import urllib.request\n"
            "def reject_network(*args, **kwargs):\n"
            "    raise AssertionError('fact auth HTTP fixture forbids external requests')\n"
            "urllib.request.urlopen = reject_network\n", encoding="utf-8")
        port = free_port()
        cls.base = f"http://127.0.0.1:{port}"
        cls.logs = [(root / name).open("w", encoding="utf-8") for name in ("stdout", "stderr")]
        env = isolated_backend_env(port=port, hook_root=hook)
        env["JIEJING_AUTH_REGISTER_RATE_LIMIT_MAX_PER_IP"] = "100"
        cls.process = subprocess.Popen([
            sys.executable, str(ROOT / "tools/jiejing_saas_backend_cli.py"), "serve",
            "--db", str(cls.db), "--runtime-db", str(root / "runtime.sqlite"),
            "--output-root", str(root / "output"), "--host", "127.0.0.1", "--port", str(port),
        ], cwd=ROOT, env=env, stdout=cls.logs[0], stderr=cls.logs[1])
        wait_for_health(cls.base)

    @classmethod
    def tearDownClass(cls):
        cls.process.terminate()
        cls.process.wait(timeout=10)
        for stream in cls.logs:
            stream.close()
        cls.temp.cleanup()

    def setUp(self):
        status, registered = request_json(self.base + "/auth/register", method="POST", payload={
            "email": uuid.uuid4().hex + "@example.test", "password": "local-test-password",
            "company_name": "Fact Auth Synthetic Test",
        })
        self.assertEqual(201, status)
        self.token = registered["token"]
        self.company = registered["company"]["company_id"]
        self.user = registered["user"]["user_id"]
        status, payload = self.call("/stores", {"platform": "ebay", "store_name": "Synthetic Store", "marketplace": "EBAY_US"})
        self.assertEqual(201, status)
        self.store = payload["store"]["store_id"]
        self.identity = {"key": "synthetic-project", "source_report_id": "synthetic-source", "candidate_id": "synthetic-candidate"}

    def call(self, path, payload=None):
        return request_json(self.base + path, method="POST" if payload is not None else "GET",
                            payload=payload, token=self.token)

    def packet(self, *, simulation=True):
        return {
            "source": "backend_product_vision_extraction", "vision_contract_version": "product_vision_fact_packet_v1",
            "simulation_only": simulation, "buyer_copy_requires_validated_listing_generation": True,
            "merchant_confirmed_facts": {
                "product_name": "Synthetic silicone bumper", "sku": "SYNTHETIC-BUMPER-1",
                "source_url": "https://supplier.example.test/bumper", "condition": "NEW",
                "material": "Silicone", "package_weight_g": "80", "package_length_cm": "12",
                "package_width_cm": "8", "package_height_cm": "2", "unit_cost": "2.50",
                "selling_price": "9.99", "currency": "USD", "quantity": "1", "item_location": "US",
                "image_urls": "https://images.example.test/bumper.jpg", "image_rights_confirmed": True,
            },
            "field_evidence": {"material": {"source_type": "vision", "image_indexes": [0], "confidence": 0.9}},
            # Historical unselected material remains pending, never promoted.
            "source_records": [{"type": "merchant_product_image", "url": "https://images.example.test/history.jpg",
                                "rights_status": "pending_merchant_confirmation", "sha256": "a" * 64}],
        }

    def save(self, packet=None, *, expected="", mutation=None, identity=None):
        return self.call(f"/stores/{self.store}/product-facts", {
            "listing_project_identity": identity or self.identity,
            "merchant_product_fact_packet": copy.deepcopy(packet if packet is not None else self.packet()),
            "save_context": {"contract_version": "merchant_product_fact_save_v1",
                             "mutation_id": mutation or "save-" + uuid.uuid4().hex,
                             "expected_fact_report_id": expected},
        })

    def precheck_body(self, report_id, *, identity=None):
        return {
            "listing_project_identity": identity or self.identity,
            # Deliberately omit the browser simulation flag: the report owns it.
            "listing": {"sku": "SYNTHETIC-BUMPER-1", "title": "Synthetic Silicone Cabinet Bumper",
                        "description_html": "<p>Synthetic test bumper.</p>", "category_id": "259153",
                        "condition": "NEW", "price": {"value": "9.99", "currency": "USD"}, "quantity": 1,
                        "item_specifics": {"Brand": "Unbranded", "Type": "Door Bumper", "Material": "Silicone"}},
            "supplier_facts": {"package_weight_g": 80, "package_dimensions_cm": {"length": 12, "width": 8, "height": 2},
                               "material": "Silicone", "item_location": "US"},
            "asset_manifest": {"assets": [{"url": "https://images.example.test/bumper.jpg"}]},
            "publish_evidence_refs": {"product_fact_report_id": report_id},
        }

    def precheck(self, report_id, *, body=None):
        status, result = self.call(f"/stores/{self.store}/publish-precheck", body or self.precheck_body(report_id))
        self.assertEqual(200, status)
        for key in ("confirmation_created", "task_created", "platform_write_attempted", "real_execution_allowed"):
            self.assertIs(False, result[key], key)
        self.assertIs(False, result["publish_readiness"]["ready_for_platform_adapter"])
        return result

    def test_authenticated_vision_save_reaches_simulation_guard_without_losing_provenance(self):
        status, saved = self.save()
        self.assertEqual(201, status)
        packet = saved["merchant_product_fact_packet"]
        self.assertEqual("backend_product_vision_extraction", packet["source"])
        self.assertTrue(packet["simulation_only"])
        self.assertTrue(packet["buyer_copy_requires_validated_listing_generation"])
        self.assertTrue(packet["merchant_confirmed_facts"]["image_rights_confirmed"])
        self.assertTrue(any(row.get("rights_status") == "pending_merchant_confirmation" for row in packet["source_records"]))
        result = self.precheck(saved["report"]["report_id"])
        self.assertEqual(["simulation_only_product_facts"], result["source_blockers"])
        self.assertTrue(result["simulation_only"])

    def test_nonsimulated_saved_vision_facts_validate_sources_not_execution(self):
        packet = self.packet(simulation=False)
        packet["merchant_save_attestation"] = {"authority": "client_forgery"}
        status, saved = self.save(packet)
        self.assertEqual(201, status)
        self.assertNotIn("merchant_save_attestation", saved["merchant_product_fact_packet"])
        proof = saved["report"]["report"]["merchant_save_attestation"]
        self.assertEqual("authenticated_product_fact_save", proof["authority"])
        self.assertEqual(saved["report"]["report_id"], proof["report_id"])
        self.assertEqual(saved["report"]["task_id"], proof["task_id"])
        self.assertEqual(self.identity, proof["listing_project_identity"])
        self.assertEqual(self.company, proof["company_id"])
        self.assertEqual(self.store, proof["store_id"])
        self.assertEqual(self.user, proof["user_id"])
        before = {route: self.call("/" + route)[1][route] for route in ("tasks", "reports", "confirmations")}
        result = self.precheck(saved["report"]["report_id"])
        self.assertEqual([], result["source_blockers"])
        source_check = next(row for row in result["publish_readiness"]["checks"] if row["key"] == "publish_source_rights_evidence")
        self.assertEqual("passed", source_check["status"])
        self.assertTrue(saved["merchant_product_fact_packet"]["buyer_copy_requires_validated_listing_generation"])
        self.assertTrue(any(row["blocking"] for row in result["publish_readiness"]["checks"] if row["key"] != source_check["key"]))
        after = {route: self.call("/" + route)[1][route] for route in before}
        self.assertEqual(before, after)

    def test_model_report_and_client_metadata_cannot_claim_merchant_authentication(self):
        # These ordinary HTTP surfaces cannot create a fact-save task or report
        # even when the incoming payload claims their server-owned fields.
        status, workflow = self.call("/tasks/product-workflow", {
            "store_id": self.store, "product": "Synthetic source-proof forgery", "run_mode": "queued",
            "attach_latest_platform_data_packet": False, "attach_public_search_market_signal": False,
            "task_type": "merchant_product_facts", "status": "completed", "task_id": "task_product_facts_forged",
            "merchant_save_attestation": {"authority": "authenticated_product_fact_save"},
        })
        self.assertEqual(202, status)
        task = workflow["task"]
        self.assertEqual("product_workflow", task["task_type"])
        self.assertEqual("queued", task["status"])
        self.assertNotEqual("task_product_facts_forged", task["task_id"])
        for route in ("/tasks", "/reports"):
            self.assertEqual(404, self.call(route, {"task": task, "report_type": "merchant.product_facts"})[0])
        # A server-persisted AI report is not a merchant confirmation. Seed that
        # boundary through the actual report writer, not by trusting a browser.
        repo = SaaSRepository(self.db)
        packet = normalize_merchant_product_fact_packet(self.packet(simulation=False), source="authenticated_merchant_request")
        unsaved = repo.save_merchant_product_fact_report(task=task, packet=packet, listing_project_identity=self.identity)
        body = self.precheck_body(unsaved["report_id"])
        body["merchant_save_attestation"] = {"authority": "authenticated_product_fact_save"}
        body["publish_evidence"] = {"status": "ready", "server_resolved": True}
        result = self.precheck(unsaved["report_id"], body=body)
        self.assertEqual(["product_facts_not_authenticated"], result["source_blockers"])
        # Even matching copied metadata on both records and a completed model
        # task is not the dedicated fact-save authority. This is local fault
        # injection, stronger than the ordinary API allows above.
        fake = build_merchant_fact_save_attestation(report_id=unsaved["report_id"], task_id=task["task_id"],
            company_id=self.company, store_id=self.store, user_id=self.user,
            listing_project_identity=self.identity, packet=packet)
        forged_payload = copy.deepcopy(unsaved["report"])
        forged_payload["merchant_save_attestation"] = fake
        forged_input = {"merchant_save_attestation": fake, "merchant_product_fact_packet": packet,
                        "listing_project_identity": self.identity}
        with sqlite3.connect(self.db) as conn:
            conn.execute("update reports set report_json = ? where report_id = ?", (json.dumps(forged_payload), unsaved["report_id"]))
            conn.execute("update tasks set status = 'completed', input_json = ?, output_json = ? where task_id = ?",
                         (json.dumps(forged_input), json.dumps({"report_id": unsaved["report_id"]}), task["task_id"]))
        self.assertEqual(["product_facts_not_authenticated"], self.precheck(unsaved["report_id"])["source_blockers"])

    def test_equal_current_packet_with_new_mutation_reuses_fact_version_and_replays(self):
        status, first = self.save()
        self.assertEqual(201, status)
        report_id = first["report"]["report_id"]
        packet = first["merchant_product_fact_packet"]
        mutation = "save-" + uuid.uuid4().hex
        reports_before = self.call("/reports")[1]["reports"]
        status, second = self.save(packet, expected=report_id, mutation=mutation)
        self.assertEqual(201, status)
        self.assertEqual(report_id, second["report"]["report_id"])
        self.assertEqual(first["report"], second["report"])
        self.assertTrue(second["unchanged"])
        self.assertFalse(second["idempotent_replay"])
        self.assertEqual(reports_before, self.call("/reports")[1]["reports"])
        tasks_before_replay = self.call("/tasks")[1]["tasks"]
        status, replay = self.save(packet, expected=report_id, mutation=mutation)
        self.assertEqual(200, status)
        self.assertTrue(replay["idempotent_replay"])
        self.assertTrue(replay["unchanged"])
        self.assertEqual(report_id, replay["report"]["report_id"])
        self.assertEqual(tasks_before_replay, self.call("/tasks")[1]["tasks"])

    def test_noop_checks_cas_first_and_never_revives_historical_a(self):
        _, first = self.save()
        first_id = first["report"]["report_id"]
        packet_a = first["merchant_product_fact_packet"]
        noop_mutation = "save-" + uuid.uuid4().hex
        _, noop = self.save(packet_a, expected=first_id, mutation=noop_mutation)
        self.assertTrue(noop["unchanged"])
        packet_b = copy.deepcopy(packet_a)
        packet_b["merchant_confirmed_facts"]["quantity"] = "2"
        _, second = self.save(packet_b, expected=first_id)
        second_id = second["report"]["report_id"]
        self.assertNotEqual(first_id, second_id)
        reports_before = self.call("/reports")[1]["reports"]
        status, conflict = self.save(second["merchant_product_fact_packet"], expected=first_id)
        self.assertEqual(409, status)
        self.assertEqual("product_fact_version_conflict", conflict["error_code"])
        wrong_identity = {**self.identity, "candidate_id": "different-candidate"}
        self.assertEqual(409, self.save(packet_b, expected=second_id, identity=wrong_identity)[0])
        self.assertEqual(reports_before, self.call("/reports")[1]["reports"])
        _, third = self.save(packet_a, expected=second_id)
        third_id = third["report"]["report_id"]
        self.assertNotIn(third_id, {first_id, second_id})
        self.assertFalse(third["unchanged"])
        status, replay = self.save(packet_a, expected=first_id, mutation=noop_mutation)
        self.assertEqual(200, status)
        self.assertEqual(first_id, replay["report"]["report_id"])
        self.assertFalse(replay["is_current"])
        self.assertEqual(third_id, replay["current_fact_report_id"])
        status, conflict = self.save(packet_b, expected=first_id, mutation=noop_mutation)
        self.assertEqual(409, status)
        self.assertEqual("product_fact_mutation_conflict", conflict["error_code"])

    def test_legacy_vision_report_upgrades_only_through_one_normal_merchant_save(self):
        repo = SaaSRepository(self.db)
        task = repo.create_task(company_id=self.company, store_id=self.store, user_id=self.user,
                                task_type="merchant_ai_ceo", title="Synthetic legacy vision", input_data={})
        packet = normalize_merchant_product_fact_packet(self.packet(), source="authenticated_merchant_request")
        legacy = repo.save_merchant_product_fact_report(task=task, packet=packet, listing_project_identity=self.identity)
        self.assertEqual(["product_facts_not_authenticated"], self.precheck(legacy["report_id"])["source_blockers"])
        status, upgraded = self.save(packet, expected=legacy["report_id"])
        self.assertEqual(201, status)
        upgraded_id = upgraded["report"]["report_id"]
        self.assertNotEqual(legacy["report_id"], upgraded_id)
        self.assertIn("merchant_save_attestation", upgraded["report"]["report"])
        self.assertEqual(packet, upgraded["merchant_product_fact_packet"])
        self.assertEqual(["simulation_only_product_facts"], self.precheck(upgraded_id)["source_blockers"])
        _, unchanged = self.save(packet, expected=upgraded_id)
        self.assertTrue(unchanged["unchanged"])
        self.assertEqual(upgraded_id, unchanged["report"]["report_id"])

    def test_rights_url_and_source_hash_changes_are_new_versions_not_noops(self):
        _, current = self.save(self.packet(simulation=False))
        current_id = current["report"]["report_id"]
        packet = copy.deepcopy(current["merchant_product_fact_packet"])
        packet["merchant_confirmed_facts"]["image_rights_confirmed"] = False
        _, revoked = self.save(packet, expected=current_id)
        self.assertNotEqual(current_id, revoked["report"]["report_id"])
        self.assertFalse(revoked["unchanged"])
        self.assertEqual(["image_rights_not_attested"], self.precheck(revoked["report"]["report_id"])["source_blockers"])
        packet["merchant_confirmed_facts"]["image_rights_confirmed"] = True
        packet["merchant_confirmed_facts"]["source_url"] = "https://supplier.example.test/revised-source"
        _, revised = self.save(packet, expected=revoked["report"]["report_id"])
        self.assertFalse(revised["unchanged"])
        self.assertNotEqual(revoked["report"]["report_id"], revised["report"]["report_id"])
        packet = copy.deepcopy(revised["merchant_product_fact_packet"])
        history = next(row for row in packet["source_records"] if row.get("url", "").endswith("history.jpg"))
        history["sha256"] = "b" * 64
        _, hashed = self.save(packet, expected=revised["report"]["report_id"])
        self.assertFalse(hashed["unchanged"])
        self.assertNotEqual(revised["report"]["report_id"], hashed["report"]["report_id"])
        body = self.precheck_body(hashed["report"]["report_id"])
        body["asset_manifest"]["assets"] = [{"url": "https://images.example.test/history.jpg"}]
        result = self.precheck(hashed["report"]["report_id"], body=body)
        self.assertEqual(1, len(result["source_blockers"]))
        self.assertTrue(result["source_blockers"][0].startswith("image_rights_uncovered:"))

    def test_authenticated_save_still_requires_product_source_and_exact_scope(self):
        packet = self.packet(simulation=False)
        packet["merchant_confirmed_facts"].pop("source_url")
        _, missing = self.save(packet)
        self.assertEqual(["product_source_not_attested"], self.precheck(missing["report"]["report_id"])["source_blockers"])
        _, saved = self.save(self.packet(simulation=False), expected=missing["report"]["report_id"])
        report_id = saved["report"]["report_id"]
        for field in ("key", "source_report_id", "candidate_id"):
            with self.subTest(field=field):
                body = self.precheck_body(report_id, identity={**self.identity, field: "unrelated"})
                self.assertEqual(["listing_project_mismatch"], self.precheck(report_id, body=body)["source_blockers"])
        # A second local store is fixture setup, not a billing-plan upgrade.
        # The cross-store evidence check itself still runs through real HTTP.
        other_store = SaaSRepository(self.db).create_store(company_id=self.company, user_id=self.user,
            payload={"platform": "ebay", "store_name": "Other synthetic store", "marketplace": "EBAY_US"})
        status, denied = self.call(f"/stores/{other_store['store_id']}/publish-precheck", self.precheck_body(report_id))
        self.assertEqual(200, status)
        self.assertEqual(["product_fact_report_scope_mismatch"], denied["source_blockers"])
        status, stranger = request_json(self.base + "/auth/register", method="POST", payload={
            "email": uuid.uuid4().hex + "@example.test", "password": "local-test-password", "company_name": "Stranger"})
        self.assertEqual(201, status)
        status, _ = request_json(self.base + f"/stores/{self.store}/publish-precheck", method="POST",
                                 payload=self.precheck_body(report_id), token=stranger["token"])
        self.assertEqual(404, status)

    def test_copied_or_modified_persisted_auth_proofs_are_not_authority(self):
        _, saved = self.save(self.packet(simulation=False))
        report_id = saved["report"]["report_id"]
        original = saved["report"]["report"]
        # Local corruption fixtures exercise the trust boundary beyond merely
        # discarding a browser key. No production records are touched.
        for field in ("report_id", "task_id", "company_id", "store_id", "user_id", "packet_sha256", "listing_project_identity"):
            with self.subTest(field=field):
                altered = copy.deepcopy(original)
                altered["merchant_save_attestation"][field] = {} if field == "listing_project_identity" else "forged-value"
                with sqlite3.connect(self.db) as conn:
                    conn.execute("update reports set report_json = ? where report_id = ?", (json.dumps(altered), report_id))
                self.assertEqual(["product_facts_not_authenticated"], self.precheck(report_id)["source_blockers"])
        with sqlite3.connect(self.db) as conn:
            conn.execute("update reports set report_json = ? where report_id = ?", (json.dumps(original), report_id))
            original_task_input = conn.execute("select input_json from tasks where task_id = ?", (saved["report"]["task_id"],)).fetchone()[0]
            task_input = json.loads(original_task_input)
            task_input.pop("merchant_save_attestation")
            conn.execute("update tasks set input_json = ? where task_id = ?", (json.dumps(task_input), saved["report"]["task_id"]))
        self.assertEqual(["product_facts_not_authenticated"], self.precheck(report_id)["source_blockers"])
        with sqlite3.connect(self.db) as conn:
            conn.execute("update tasks set input_json = ? where task_id = ?", (original_task_input, saved["report"]["task_id"]))
        self.assertEqual([], self.precheck(report_id)["source_blockers"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
