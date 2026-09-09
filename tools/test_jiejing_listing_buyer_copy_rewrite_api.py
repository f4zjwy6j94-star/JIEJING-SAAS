#!/usr/bin/env python3
"""Real loopback HTTP rewrite contracts; temporary DBs and a local model boundary only."""
from __future__ import annotations

import copy
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import shutil
import socket
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
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from tools.test_jiejing_listing_buyer_copy_rewrite import FIELD_KEYS, LocalModelBoundary


def serve_fixture(directory, port):
    """Local provider plus an explicit report-save fault; normal storage stays real."""
    from jiejing_runtime.model_clients import OpenAICompatibleModelClient
    from jiejing_saas.api_server import SaaSBackendServer
    from jiejing_saas.repository import SaaSRepository
    root = Path(directory)
    real_connect = socket.socket.connect

    def loopback_only(sock, address):
        if not isinstance(address, tuple) or address[0] not in ("127.0.0.1", "::1", "localhost"):
            (root / "external-request-blocked").touch()
            raise RuntimeError("non-loopback network blocked in rewrite fixture")
        return real_connect(sock, address)

    socket.socket.connect = loopback_only

    def local_model(self, **kwargs):
        control = json.loads((root / "provider-control.json").read_text(encoding="utf-8"))
        with (root / "provider-calls.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"prompt": kwargs.get("user_prompt", "")}) + "\n")
        if control.get("hold"):
            (root / "provider-entered").touch()
            deadline = time.monotonic() + 20
            while not (root / "provider-release").exists():
                if time.monotonic() >= deadline:
                    raise TimeoutError("local fixture release was not received")
                time.sleep(0.01)
        if control.get("error"):
            raise TimeoutError("local provider fixture timeout")
        return {"text": json.dumps(control.get("output", LocalModelBoundary().output)),
                "_usage": {"input_tokens": 80, "output_tokens": 50, "total_tokens": 130}}

    OpenAICompatibleModelClient.generate_text = local_model
    real_report_save = SaaSRepository.save_listing_draft_report

    def report_save_with_explicit_fault(self, **kwargs):
        control = json.loads((root / "provider-control.json").read_text(encoding="utf-8"))
        if control.get("report_save_error"):
            # A JSON-labelled storage fault must not masquerade as a safe
            # pre-save model parse failure merely because of its public code.
            raise ValueError("local report storage json failure")
        return real_report_save(self, **kwargs)

    SaaSRepository.save_listing_draft_report = report_save_with_explicit_fault
    SaaSBackendServer(db_path=root / "saas.sqlite", runtime_db_path=root / "runtime.sqlite",
        output_root=root, host="127.0.0.1", port=int(port)).serve_forever()


class BuyerCopyRewriteHTTPTests(unittest.TestCase):
    @classmethod
    def start_fixture(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="jiejing-rewrite-http-")
        cls.root = Path(cls.directory.name)
        (cls.root / "provider-control.json").write_text("{}", encoding="utf-8")
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        cls.base = f"http://127.0.0.1:{port}"
        cls.process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--serve-fixture",
            str(cls.root), str(port)], cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            env={"PYTHONUTF8": "1", "SYSTEMROOT": "C:\\Windows", "TEMP": str(cls.root), "TMP": str(cls.root),
                "JIEJING_DATABASE_ENGINE": "sqlite", "JIEJING_DATABASE_URL": "",
                "JIEJING_AI_CEO_PLATFORM_MODEL_ENABLED": "true",
                "JIEJING_AI_CEO_PLATFORM_MODEL_PROVIDER": "deepseek",
                "JIEJING_AI_CEO_PLATFORM_MODEL_API_KEY": "local-fixture-not-a-credential",
                "JIEJING_PLATFORM_TRIAL_ACTIVATION_REQUIRED": "false"})
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            try:
                if cls.request("/health", token="")[0] == 200:
                    return
            except urllib.error.URLError:
                time.sleep(0.05)
        cls.stop_fixture()
        raise AssertionError("local fixture server did not start")

    @classmethod
    def stop_fixture(cls):
        cls.process.terminate()
        cls.process.wait(timeout=10)
        cls.directory.cleanup()

    @classmethod
    def request(cls, path, *, method="GET", body=None, token=None):
        headers = {"Content-Type": "application/json"}
        token = getattr(cls, "token", "") if token is None else token
        if token:
            headers["Authorization"] = "Bearer " + token
        request = urllib.request.Request(cls.base + path, method=method, headers=headers,
            data=None if body is None else json.dumps(body).encode())
        try:
            response = urllib.request.urlopen(request, timeout=25)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            return response.status, json.loads(response.read().decode())

    def setUp(self):
        # A fresh server per case keeps real registration/usage limits intact;
        # unrelated fixture accounts must not consume the next case's allowance.
        type(self).start_fixture()
        self.addCleanup(type(self).stop_fixture)
        (self.root / "provider-control.json").write_text("{}", encoding="utf-8")
        for name in ("provider-calls.jsonl", "provider-entered", "provider-release"):
            (self.root / name).unlink(missing_ok=True)
        status, account = self.request("/auth/register", method="POST", token="", body={
            "email": uuid.uuid4().hex + "@local.invalid", "password": "local-http-rewrite-pass",
            "company_name": "Local rewrite HTTP fixture"})
        self.assertEqual(status, 201)
        type(self).token = account["token"]
        status, store = self.request("/stores", method="POST", body={"platform": "ebay",
            "store_name": "Local rewrite store", "marketplace": "EBAY_US"})
        self.assertEqual(status, 201)
        self.store_id = store["store"]["store_id"]
        self.identity = {"key": "listing-project-http-" + uuid.uuid4().hex,
                         "source_report_id": "", "candidate_id": ""}
        self.packet = {"simulation_only": True, "merchant_confirmed_facts": {},
            "derived_listing_suggestions": {"product_name": "Foldable Tablet Stand", "material": "Aluminum and silicone",
                "condition": "NEW", "style": "Foldable", "quantity": "2"}}
        status, facts = self.request(f"/stores/{self.store_id}/product-facts", method="POST", body={
            "listing_project_identity": self.identity, "merchant_product_fact_packet": self.packet})
        self.assertEqual(status, 201)
        self.fields = {key: "" for key in FIELD_KEYS}
        self.fields.update(title="旧平板支架", selling_points="旧卖点一\n旧卖点二\n旧卖点三",
            description="Draft. 仅供内部演练。", price="USD 39.99", risk_notes="Concept only.")
        self.edited = ["title", "description", "selling_points", "price", "risk_notes"]
        self.checkpoint_path = f"/stores/{self.store_id}/listing-drafts/{self.identity['key']}/checkpoint"
        self.checkpoint_query = "?" + urllib.parse.urlencode({key: self.identity[key]
            for key in ("source_report_id", "candidate_id")})
        self.checkpoint_body = {"contract_version": "listing_merchant_edit_v1", "listing_project_identity": self.identity,
            "base_report_id": facts["report"]["report_id"], "expected_revision": 0, "mutation_id": str(uuid.uuid4()),
            "fields": self.fields, "merchant_edited_fields": self.edited}
        status, saved = self.request(self.checkpoint_path, method="POST", body=self.checkpoint_body)
        self.assertEqual(status, 201)
        self.original_checkpoint = saved["checkpoint"]
        self.body = {"generation_mode": "rewrite_buyer_copy", "listing_project_identity": self.identity,
            "merchant_product_fact_packet": self.packet, "current_draft_fields": {
                **self.fields, "merchant_edited_fields": self.edited},
            "expected_base_report_id": facts["report"]["report_id"], "expected_checkpoint_revision": 1}
        self.path = f"/stores/{self.store_id}/listing-drafts/generate"

    def tearDown(self):
        self.assertFalse((self.root / "external-request-blocked").exists(), "no external requests are permitted")

    def calls(self):
        path = self.root / "provider-calls.jsonl"
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []

    def quota(self):
        status, payload = self.request(f"/stores/{self.store_id}/model/settings")
        self.assertEqual(status, 200)
        return payload["model_settings"]["platform_trial_quota"]

    def test_http_rejects_unknown_mode_before_model(self):
        status, rejected = self.request(self.path, method="POST", body={**self.body, "generation_mode": "rewrite"})
        self.assertEqual(status, 400)
        self.assertEqual(rejected["failure_code"], "listing_generation_mode_invalid")
        self.assertFalse(rejected["model_called"])
        self.assertFalse(rejected["usage_consumed"])
        self.assertIsNone(rejected["report"])
        self.assertEqual(self.calls(), [])

    def test_http_requires_the_saved_source_revision_before_model(self):
        status, rejected = self.request(self.path, method="POST", body={**self.body,
            "expected_checkpoint_revision": 0})
        self.assertEqual(status, 409)
        self.assertEqual(rejected["failure_code"], "listing_rewrite_source_conflict")
        self.assertFalse(rejected["model_called"])
        self.assertFalse(rejected["usage_consumed"])
        self.assertIsNone(rejected["report"])
        self.assertEqual(self.calls(), [])

    def test_http_rewrite_persists_original_and_accepts_new_checkpoint(self):
        self.assertEqual(self.quota()["used"], 0)
        status, generated = self.request(self.path, method="POST", body=self.body)
        self.assertEqual(status, 201, generated)
        self.assertEqual(generated["status"], "completed", generated)
        report = generated["report"]
        stored_report = next(item for item in self.request("/reports")[1]["reports"] if item["report_id"] == report["report_id"])
        self.assertEqual(report.get("company_id"), stored_report["company_id"])
        self.assertEqual(report.get("store_id"), stored_report["store_id"])
        contract = report["report"]["listing_handoff"]["listing_fields"]["buyer_copy_rewrite"]
        self.assertEqual(contract["previous_fields"], self.fields)
        status, saved = self.request(self.checkpoint_path, method="POST", body={**self.checkpoint_body,
            "base_report_id": report["report_id"], "expected_revision": 1, "mutation_id": str(uuid.uuid4()),
            "fields": contract["fields"], "merchant_edited_fields": contract["merchant_edited_fields"]})
        self.assertEqual(status, 201, saved)
        self.assertEqual(self.request(self.checkpoint_path + self.checkpoint_query)[1]["checkpoint"], saved["checkpoint"])
        self.assertEqual(self.request(self.checkpoint_path, method="POST", body={**self.checkpoint_body,
            "base_report_id": report["report_id"], "expected_revision": 2, "mutation_id": str(uuid.uuid4()),
            "fields": {**contract["fields"], "description": "Merchant changed the new draft."},
            "merchant_edited_fields": [*contract["merchant_edited_fields"], "description"]})[0], 201)
        self.assertEqual(len(self.calls()), 1)
        self.assertEqual(self.quota()["used"], 1)

    def test_a_second_rewrite_uses_the_first_report_and_replays_without_moving_head(self):
        status, first = self.request(self.path, method="POST", body=self.body)
        self.assertEqual(status, 201)
        first_report = first["report"]
        first_contract = first_report["report"]["listing_handoff"]["listing_fields"]["buyer_copy_rewrite"]
        adoption = {**self.checkpoint_body, "base_report_id": first_report["report_id"],
            "expected_revision": 1, "mutation_id": str(uuid.uuid4()), "fields": first_contract["fields"],
            "merchant_edited_fields": first_contract["merchant_edited_fields"]}
        status, saved_first = self.request(self.checkpoint_path, method="POST", body=adoption)
        self.assertEqual(status, 201)
        status, second = self.request(self.path, method="POST", body={**self.body,
            "expected_base_report_id": first_report["report_id"], "expected_checkpoint_revision": 2,
            "current_draft_fields": {**first_contract["fields"],
                "merchant_edited_fields": first_contract["merchant_edited_fields"]}})
        self.assertEqual(status, 201, second)
        second_report = second["report"]
        second_contract = second_report["report"]["listing_handoff"]["listing_fields"]["buyer_copy_rewrite"]
        self.assertEqual(second_contract["expected_base_report_id"], first_report["report_id"])
        status, saved_second = self.request(self.checkpoint_path, method="POST", body={**adoption,
            "base_report_id": second_report["report_id"], "expected_revision": 2, "mutation_id": str(uuid.uuid4()),
            "fields": second_contract["fields"], "merchant_edited_fields": second_contract["merchant_edited_fields"]})
        self.assertEqual(status, 201, saved_second)
        status, replay = self.request(self.checkpoint_path, method="POST", body=adoption)
        self.assertEqual(status, 200)
        self.assertEqual(replay["checkpoint"], saved_first["checkpoint"])
        self.assertTrue(replay["idempotent_replay"])
        self.assertEqual(self.request(self.checkpoint_path + self.checkpoint_query)[1]["checkpoint"], saved_second["checkpoint"])
        self.assertEqual(len(self.calls()), 2)

    def test_http_rejects_source_and_snapshot_mismatches_without_quota_usage(self):
        self.assertEqual(self.quota()["used"], 0)
        original_tasks = self.request("/tasks")[1]
        original_reports = self.request("/reports")[1]
        invalid = [({"expected_base_report_id": "report-absent"}, 409),
            ({"expected_checkpoint_revision": True}, 400),
            ({"expected_checkpoint_revision": 999}, 409),
            ({"expected_base_report_id": None}, 400),
            ({"listing_project_identity": {**self.identity, "candidate_id": "another"}}, 409),
            ({"listing_project_identity": {"key": self.identity["key"]}}, 400),
            ({"current_draft_fields": {**self.body["current_draft_fields"], "price": "changed without save"}}, 409),
            ({"current_draft_fields": {**self.body["current_draft_fields"], "images": []}}, 400),
            ({"current_draft_fields": {**self.body["current_draft_fields"], "api_key": "not allowed"}}, 400),
            ({"current_draft_fields": {**self.body["current_draft_fields"], "risk_notes": "AIAK" + "C" * 12}}, 422)]
        for overrides, expected_status in invalid:
            with self.subTest(fields=list(overrides)):
                status, rejected = self.request(self.path, method="POST", body={**self.body, **overrides})
                self.assertEqual(status, expected_status)
                self.assertFalse(rejected["model_called"])
                self.assertFalse(rejected["usage_consumed"])
                self.assertIsNone(rejected["report"])
        self.assertEqual(self.calls(), [])
        self.assertEqual(self.request("/tasks")[1], original_tasks)
        self.assertEqual(self.request("/reports")[1], original_reports)
        self.assertEqual(self.quota()["used"], 0)

    def test_failed_model_validation_keeps_original_and_accounts_for_one_attempt(self):
        invalid_output = LocalModelBoundary().output
        invalid_output["title"] = "中文结果不能通过"
        (self.root / "provider-control.json").write_text(json.dumps({"output": invalid_output}), encoding="utf-8")
        original_reports = self.request("/reports")[1]
        status, failed = self.request(self.path, method="POST", body=self.body)
        self.assertEqual(status, 502)
        self.assertEqual(failed["failure_code"], "listing_model_output_marketplace_language")
        self.assertTrue(failed["model_called"])
        self.assertTrue(failed["usage_consumed"])
        self.assertIs(failed.get("report_save_attempted"), False)
        self.assertIsNone(failed["report"])
        self.assertEqual(self.request("/reports")[1], original_reports)
        self.assertEqual(self.request(self.checkpoint_path + self.checkpoint_query)[1]["checkpoint"], self.original_checkpoint)
        self.assertEqual(len(self.calls()), 2, "one request and one bounded correction, not an unbounded retry")
        self.assertEqual(self.quota()["used"], 1, "the bounded correction belongs to one accounted generation attempt")

    def test_report_save_failure_is_not_a_known_pre_save_failure(self):
        (self.root / "provider-control.json").write_text(json.dumps({"report_save_error": True}), encoding="utf-8")
        original_reports = self.request("/reports")[1]
        status, failed = self.request(self.path, method="POST", body=self.body)
        self.assertEqual(status, 502)
        self.assertEqual(failed["failure_code"], "listing_model_output_invalid_json")
        self.assertIs(failed.get("report_save_attempted"), True)
        self.assertIn("保存结果尚未确认", failed["merchant_message"])
        self.assertNotIn("没有保存 Listing", failed["merchant_message"])
        self.assertIsNone(failed["report"])
        self.assertEqual(self.request("/reports")[1], original_reports)
        self.assertEqual(self.request(self.checkpoint_path + self.checkpoint_query)[1]["checkpoint"], self.original_checkpoint)
        self.assertEqual(len(self.calls()), 1, "a storage fault must not trigger another model request")

    def test_other_tenant_cannot_rewrite_or_read_the_original_project(self):
        status, other = self.request("/auth/register", method="POST", token="", body={
            "email": uuid.uuid4().hex + "@local.invalid", "password": "local-other-tenant-pass",
            "company_name": "Other local tenant"})
        self.assertEqual(status, 201)
        for path, method, body in ((self.path, "POST", self.body),
            (self.checkpoint_path + self.checkpoint_query, "GET", None)):
            with self.subTest(method=method):
                status, rejected = self.request(path, method=method, body=body, token=other["token"])
                self.assertEqual(status, 404)
                self.assertNotIn(self.fields["title"], json.dumps(rejected, ensure_ascii=False))
        self.assertEqual(self.calls(), [])
        self.assertEqual(self.quota()["used"], 0)

    def test_http_rewrite_cannot_change_saved_facts_or_simulation_and_rights(self):
        for packet in ({**self.packet, "simulation_only": False,
                        "merchant_confirmed_facts": {**self.packet["derived_listing_suggestions"],
                            "image_rights_confirmed": True}},
                       {**self.packet, "derived_listing_suggestions": {
                            **self.packet["derived_listing_suggestions"], "quantity": "999"}}):
            with self.subTest(packet_kind=packet["simulation_only"]):
                status, rejected = self.request(self.path, method="POST", body={**self.body,
                    "merchant_product_fact_packet": packet})
                self.assertEqual(status, 409)
                self.assertEqual(rejected["failure_code"], "listing_rewrite_source_facts_conflict")
                self.assertFalse(rejected["model_called"])
                self.assertFalse(rejected["usage_consumed"])
        self.assertEqual(self.calls(), [])
        self.assertEqual(self.request(self.checkpoint_path + self.checkpoint_query)[1]["checkpoint"], self.original_checkpoint)

    def test_facts_only_change_during_model_cannot_be_hidden_by_new_report(self):
        (self.root / "provider-control.json").write_text(json.dumps({"hold": True}), encoding="utf-8")
        with ThreadPoolExecutor(max_workers=1) as executor:
            pending = executor.submit(self.request, self.path, method="POST", body=self.body)
            try:
                deadline = time.monotonic() + 12
                while not (self.root / "provider-entered").exists():
                    if pending.done() or time.monotonic() >= deadline:
                        self.fail("held model was not entered")
                    time.sleep(0.01)
                changed_packet = copy.deepcopy(self.packet)
                changed_packet["derived_listing_suggestions"]["quantity"] = "9"
                status, new_facts = self.request(f"/stores/{self.store_id}/product-facts", method="POST", body={
                    "listing_project_identity": self.identity, "merchant_product_fact_packet": changed_packet})
                self.assertEqual(status, 201)
                before = self.request(self.checkpoint_path + self.checkpoint_query)[1]
                self.assertEqual(before["current_revision"], 1)
                self.assertEqual(before["current_base_report_id"], new_facts["report"]["report_id"])
            finally:
                (self.root / "provider-release").touch()
            status, generated = pending.result(timeout=15)
        self.assertEqual(status, 201, generated)
        report = generated["report"]
        current = self.request(self.checkpoint_path + self.checkpoint_query)[1]
        self.assertEqual(current["current_base_report_id"], new_facts["report"]["report_id"],
            "a superseded unadopted N must not hide the newer fact base B")
        self.assertIn(report["report_id"], current["superseded_rewrite_report_ids"])
        contract = report["report"]["listing_handoff"]["listing_fields"]["buyer_copy_rewrite"]
        stale_adoption = {**self.checkpoint_body,
            "base_report_id": report["report_id"], "expected_revision": 1, "mutation_id": str(uuid.uuid4()),
            "fields": contract["fields"], "merchant_edited_fields": contract["merchant_edited_fields"]}
        status, rejected = self.request(self.checkpoint_path, method="POST", body=stale_adoption)
        self.assertEqual(status, 409, "new report must not hide a facts-only source change")
        self.assertEqual(rejected["error_code"], "listing_draft_base_conflict")
        self.assertEqual(self.request(self.checkpoint_path + self.checkpoint_query)[1]["checkpoint"], self.original_checkpoint)
        manual = {**self.checkpoint_body, "base_report_id": current["current_base_report_id"], "expected_revision": 1,
                  "mutation_id": str(uuid.uuid4()), "fields": {**self.fields, "title": "Reviewed current facts"}}
        status, saved_manual = self.request(self.checkpoint_path, method="POST", body=manual)
        self.assertEqual(status, 201, "the conflict must not lock ordinary merchant editing")
        status, saved_again = self.request(self.checkpoint_path, method="POST", body={**manual, "expected_revision": 2,
            "mutation_id": str(uuid.uuid4()), "fields": {**manual["fields"], "description": "A further merchant edit."}})
        self.assertEqual(status, 201)
        self.assertEqual(self.request(self.checkpoint_path, method="POST", body=stale_adoption)[0], 409)
        self.assertEqual(self.request(self.checkpoint_path + self.checkpoint_query)[1]["checkpoint"], saved_again["checkpoint"])
        self.assertIn(report["report_id"], [item["report_id"] for item in self.request("/reports")[1]["reports"]])
        self.assertEqual(len(self.calls()), 1)

    def test_http_rewrite_snapshots_keep_provider_words_and_urls_exact(self):
        self.fields.update(risk_notes="FAL concept original text", images="https://fal.media/files/original-product.png")
        status, saved = self.request(self.checkpoint_path, method="POST", body={**self.checkpoint_body,
            "fields": self.fields, "expected_revision": 1, "mutation_id": str(uuid.uuid4())})
        self.assertEqual(status, 201)
        status, generated = self.request(self.path, method="POST", body={**self.body,
            "expected_checkpoint_revision": 2, "current_draft_fields": {**self.fields, "merchant_edited_fields": self.edited}})
        self.assertEqual(status, 201, generated)
        contract = generated["report"]["report"]["listing_handoff"]["listing_fields"]["buyer_copy_rewrite"]
        self.assertEqual(contract["previous_fields"], self.fields)
        self.assertEqual(contract["fields"]["images"], self.fields["images"])
        self.assertEqual(contract["fields"]["risk_notes"], self.fields["risk_notes"])
        read_report = next(item for item in self.request("/reports")[1]["reports"]
                           if item["report_id"] == generated["report"]["report_id"])
        self.assertEqual(read_report["report"]["listing_handoff"]["listing_fields"]["buyer_copy_rewrite"], contract)
        current_base = self.request(self.checkpoint_path + self.checkpoint_query)[1]["current_base_report"]
        self.assertEqual(current_base["report"]["listing_handoff"]["listing_fields"]["buyer_copy_rewrite"], contract)

    def test_two_pending_rewrites_do_not_lock_each_other_or_ordinary_editing(self):
        (self.root / "provider-control.json").write_text(json.dumps({"hold": True}), encoding="utf-8")
        with ThreadPoolExecutor(max_workers=2) as executor:
            pending = [executor.submit(self.request, self.path, method="POST", body=self.body) for _ in range(2)]
            try:
                deadline = time.monotonic() + 12
                while len(self.calls()) < 2:
                    if any(item.done() for item in pending) or time.monotonic() >= deadline:
                        self.fail("both held model requests must enter before either report is created")
                    time.sleep(0.01)
            finally:
                (self.root / "provider-release").touch()
            results = [item.result(timeout=15) for item in pending]
        self.assertTrue(all(status == 201 for status, _ in results))
        reports = {body["report"]["report_id"]: body["report"] for _, body in results}
        self.assertEqual(len(reports), 2)
        current = self.request(self.checkpoint_path + self.checkpoint_query)[1]
        chosen_id = current["current_base_report_id"]
        self.assertIn(chosen_id, reports)
        other_id = next(key for key in reports if key != chosen_id)
        self.assertIn(other_id, current["superseded_rewrite_report_ids"])
        chosen = reports[chosen_id]["report"]["listing_handoff"]["listing_fields"]["buyer_copy_rewrite"]
        adopted = {**self.checkpoint_body, "base_report_id": chosen_id, "expected_revision": 1,
            "mutation_id": str(uuid.uuid4()), "fields": chosen["fields"], "merchant_edited_fields": chosen["merchant_edited_fields"]}
        self.assertEqual(self.request(self.checkpoint_path, method="POST", body=adopted)[0], 201)
        other = reports[other_id]["report"]["listing_handoff"]["listing_fields"]["buyer_copy_rewrite"]
        self.assertEqual(self.request(self.checkpoint_path, method="POST", body={**adopted,
            "base_report_id": other_id, "mutation_id": str(uuid.uuid4()), "fields": other["fields"]})[0], 409)
        status, edited = self.request(self.checkpoint_path, method="POST", body={**adopted,
            "expected_revision": 2, "mutation_id": str(uuid.uuid4()),
            "fields": {**chosen["fields"], "description": "Merchant can keep editing."},
            "merchant_edited_fields": [*chosen["merchant_edited_fields"], "description"]})
        self.assertEqual(status, 201)
        self.assertEqual(self.request(self.checkpoint_path + self.checkpoint_query)[1]["checkpoint"], edited["checkpoint"])
        self.assertEqual(len(self.calls()), 2)

    def test_merchant_edit_during_model_can_continue_after_conflict_without_regeneration(self):
        (self.root / "provider-control.json").write_text(json.dumps({"hold": True}), encoding="utf-8")
        with ThreadPoolExecutor(max_workers=1) as executor:
            pending = executor.submit(self.request, self.path, method="POST", body=self.body)
            try:
                deadline = time.monotonic() + 12
                while not (self.root / "provider-entered").exists():
                    if pending.done() or time.monotonic() >= deadline:
                        self.fail("held model was not entered")
                    time.sleep(0.01)
                update = {**self.checkpoint_body, "expected_revision": 1, "mutation_id": str(uuid.uuid4()),
                    "fields": {**self.fields, "title": "Another window's latest title"}}
                status, concurrent_edit = self.request(self.checkpoint_path, method="POST", body=update)
                self.assertEqual(status, 201)
            finally:
                (self.root / "provider-release").touch()
            status, generated = pending.result(timeout=15)
        self.assertEqual(status, 201)
        current = self.request(self.checkpoint_path + self.checkpoint_query)[1]
        self.assertEqual(current["current_base_report_id"], self.body["expected_base_report_id"])
        self.assertIn(generated["report"]["report_id"], current["superseded_rewrite_report_ids"])
        self.assertEqual(current["checkpoint"], concurrent_edit["checkpoint"])
        self.assertEqual(self.request(self.checkpoint_path, method="POST", body={**update,
            "base_report_id": generated["report"]["report_id"], "mutation_id": str(uuid.uuid4())})[0], 409)
        status, continued = self.request(self.checkpoint_path, method="POST", body={**update,
            "expected_revision": 2, "mutation_id": str(uuid.uuid4()),
            "fields": {**update["fields"], "description": "Reviewed without another AI request."}})
        self.assertEqual(status, 201)
        self.assertEqual(self.request(self.checkpoint_path + self.checkpoint_query)[1]["checkpoint"], continued["checkpoint"])
        self.assertEqual(len(self.calls()), 1)

    def test_real_browser_rewrites_saves_and_reloads_via_http(self):
        node = shutil.which("node")
        self.assertIsNotNone(node, "the configured Node runtime is required for local browser integration")
        base_report = self.request(self.checkpoint_path + self.checkpoint_query)[1]["current_base_report"]
        result = subprocess.run([node, str(ROOT / "tools/test_jiejing_listing_buyer_copy_rewrite_http_smoke.js")],
            cwd=ROOT, text=True, encoding="utf-8", capture_output=True, timeout=60,
            input=json.dumps({"api_base": self.base, "session_token": self.token,
                "profile": self.request("/me")[1], "store_id": self.store_id, "identity": self.identity,
                "base_report": base_report, "fields": self.fields, "merchant_edited_fields": self.edited}),
            env={"SYSTEMROOT": "C:\\Windows", "PROGRAMFILES": "C:\\Program Files", "TEMP": str(self.root), "TMP": str(self.root),
                 "PATH": str(Path(node).parent)})
        # Never echo child output that could contain the local fixture session.
        safe_failure = next((line for line in result.stderr.splitlines()
            if line.startswith("buyer_copy_rewrite_http_browser_smoke_failed")
            and all(character.isalnum() or character == "_" for character in line)), "no_safe_failure_location")
        self.assertEqual(result.returncode, 0, "real browser -> HTTP rewrite integration failed: " + safe_failure)
        evidence = json.loads(result.stdout)
        self.assertEqual(evidence["generation_posts"], 1)
        self.assertEqual(evidence["checkpoint_posts"], 2, "one explicit original flush and one new-copy adoption")
        self.assertTrue(evidence["refreshed"])
        self.assertEqual(evidence["external_requests"], 0)
        current = self.request(self.checkpoint_path + self.checkpoint_query)[1]
        self.assertEqual(current["current_revision"], 3)
        self.assertNotEqual(current["checkpoint"]["fields"]["title"], self.fields["title"])
        self.assertEqual(current["checkpoint"]["fields"]["price"], self.fields["price"])
        self.assertEqual(len(self.calls()), 1)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--serve-fixture":
        serve_fixture(sys.argv[2], sys.argv[3])
    else:
        unittest.main()
