#!/usr/bin/env python3
"""Real loopback HTTP rewrite contracts; temporary DBs and a local model boundary only."""
from __future__ import annotations

import copy
from concurrent.futures import ThreadPoolExecutor
import gc
import json
from pathlib import Path
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock
import urllib.error
import urllib.parse
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from tools.test_jiejing_listing_buyer_copy_rewrite import FIELD_KEYS, LocalModelBoundary


def serve_fixture(directory, port):
    """Local provider and explicit persistence faults; normal storage stays real."""
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
    provider_log_lock = threading.Lock()

    def local_model(self, **kwargs):
        control = json.loads((root / "provider-control.json").read_text(encoding="utf-8"))
        with provider_log_lock:
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
        from tools.listing_claim_review_fixture import review_response
        review = review_response(kwargs, usage={"input_tokens": 80, "output_tokens": 50, "total_tokens": 130})
        if review is not None:
            return review
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
    real_checkpoint_read = SaaSRepository.get_listing_draft_checkpoint

    def checkpoint_read_with_explicit_fault(self, **kwargs):
        control = json.loads((root / "provider-control.json").read_text(encoding="utf-8"))
        if control.get("hold_first_source_read"):
            try:
                with (root / "source-entered").open("x", encoding="utf-8"):
                    pass
            except FileExistsError:
                pass
            else:
                deadline = time.monotonic() + 20
                while not (root / "source-release").exists():
                    if time.monotonic() >= deadline:
                        raise TimeoutError("local source fixture release was not received")
                    time.sleep(0.01)
        if control.get("source_read_error"):
            raise sqlite3.OperationalError("local checkpoint storage unavailable")
        return real_checkpoint_read(self, **kwargs)

    SaaSRepository.get_listing_draft_checkpoint = checkpoint_read_with_explicit_fault
    SaaSBackendServer(db_path=root / "saas.sqlite", runtime_db_path=root / "runtime.sqlite",
        output_root=root, host="127.0.0.1", port=int(port)).serve_forever()


def cleanup_fixture_directory(directory, *, timeout=2.0):
    """Release only this test-owned temporary directory after its server exits."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            directory.cleanup()
            return
        except PermissionError as exc:
            # On Windows the exited server can release SQLite's file handle a
            # few milliseconds after wait(). Never hide persistent locks or
            # any other filesystem failure, and never retry a business call.
            remaining = deadline - time.monotonic()
            if getattr(exc, "winerror", None) != 32 or remaining <= 0:
                raise
            time.sleep(min(0.02, remaining))


class FixtureDirectoryCleanupTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform == "win32", "Windows denies unlink while SQLite owns the file")
    def test_cleanup_waits_for_a_real_sqlite_handle_to_close(self):
        directory = tempfile.TemporaryDirectory(prefix="jiejing-rewrite-cleanup-")
        root = Path(directory.name)
        connection = sqlite3.connect(root / "saas.sqlite", check_same_thread=False)
        release = threading.Timer(0.15, connection.close)
        release.start()
        try:
            cleanup_fixture_directory(directory)
            self.assertFalse(root.exists(), "cleanup must actually remove the allocated fixture")
        finally:
            release.join(timeout=2)
            connection.close()
            directory.cleanup()

    @unittest.skipUnless(sys.platform == "win32", "Windows denies unlink while SQLite owns the file")
    def test_persistent_sqlite_lock_still_fails_within_the_bound(self):
        directory = tempfile.TemporaryDirectory(prefix="jiejing-rewrite-cleanup-")
        root = Path(directory.name)
        connection = sqlite3.connect(root / "saas.sqlite")
        started = time.monotonic()
        try:
            with self.assertRaises(PermissionError) as failure:
                cleanup_fixture_directory(directory, timeout=0.03)
            self.assertEqual(failure.exception.winerror, 32)
            self.assertLess(time.monotonic() - started, 1)
            self.assertTrue(root.exists(), "a locked fixture must not be reported as cleaned")
        finally:
            connection.close()
            directory.cleanup()

    def test_other_permission_errors_are_not_retried_or_hidden(self):
        with tempfile.TemporaryDirectory(prefix="jiejing-rewrite-cleanup-") as root:
            directory = mock.Mock()
            directory.name = root
            failure = PermissionError(13, "local fixture access denied")
            directory.cleanup.side_effect = failure
            with self.assertRaises(PermissionError) as raised:
                cleanup_fixture_directory(directory)
            self.assertIs(raised.exception, failure)
            directory.cleanup.assert_called_once_with()


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
        cleanup_fixture_directory(cls.directory)

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
        quota = payload["model_settings"]["platform_trial_quota"]
        # The countdown naturally changes during a read-only request; compare
        # all entitlement, usage and immutable window fields, not wall time.
        self.assertIs(type(quota.get("seconds_remaining")), int)
        self.assertGreaterEqual(quota["seconds_remaining"], 0)
        return {key: value for key, value in quota.items() if key != "seconds_remaining"}

    def test_http_rejects_unknown_mode_before_model(self):
        status, rejected = self.request(self.path, method="POST", body={**self.body, "generation_mode": "rewrite"})
        self.assertEqual(status, 400)
        self.assertEqual(rejected["failure_code"], "listing_generation_mode_invalid")
        self.assertFalse(rejected["model_called"])
        self.assertFalse(rejected["usage_consumed"])
        self.assertIsNone(rejected["report"])
        self.assertEqual(self.calls(), [])

    def test_real_generated_copy_survives_first_image_rights_save_and_publish_projection(self):
        self.run_generated_media_copy_browser_loop(simulation_only=True)

    def test_media_copy_reuse_preserves_real_source_and_confirmation_guards(self):
        self.run_generated_media_copy_browser_loop(simulation_only=False)

    def test_copy_survives_conflict_metadata_normalization_after_images_and_cold_reload(self):
        self.run_generated_media_copy_browser_loop(simulation_only=False, with_conflicts=True)

    def test_old_product_copy_survives_generation_falling_out_of_recent_reports(self):
        self.run_generated_media_copy_browser_loop(simulation_only=True, old_generation=True)

    def test_old_project_bootstraps_when_all_its_reports_fall_out_of_recent_feed(self):
        self.run_generated_media_copy_browser_loop(simulation_only=True, all_history_old=True)

    def test_latest_fact_conflict_snapshot_does_not_resurrect_historical_reason(self):
        self.run_generated_media_copy_browser_loop(simulation_only=False, with_conflicts=True,
                                                   historical_normalized_reason=True)

    def test_optional_clears_survive_saved_history_image_step_and_cold_reload(self):
        self.run_generated_media_copy_browser_loop(simulation_only=False, with_conflicts=True,
                                                   historical_normalized_reason=True, cleared_optional=True)

    def run_generated_media_copy_browser_loop(self, *, simulation_only, with_conflicts=False, old_generation=False,
                                             historical_normalized_reason=False, cleared_optional=False, all_history_old=False):
        """The full app crosses real fact/checkpoint HTTP after a real generation handler."""
        node = shutil.which("node")
        self.assertIsNotNone(node, "Node is required for the real media-to-publish browser loop")
        identity = {"key": "listing-project-media-" + uuid.uuid4().hex,
                    "source_report_id": "", "candidate_id": ""}
        packet = {"source": "backend_product_vision_extraction", "simulation_only": simulation_only,
            "vision_contract_version": "jiejing_ai_ceo_product_vision_intake_v1",
            "buyer_copy_requires_validated_listing_generation": True,
            "merchant_confirmed_facts": {"product_name": "Foldable Tablet Stand",
                "material": "Aluminum and silicone", "condition": "NEW", "style": "Foldable",
                "source_url": "https://supplier.example.test/tablet-stand"}}
        if with_conflicts:
            packet["fact_conflicts"] = [{"field": "product_dimensions_cm", "values": ["11.5 x 11.5", "20 x 20 x 0.5"],
                "reason": "Supplier dimension tables refer to an unverified size or package.", "requires_merchant_confirmation": True}]
        if historical_normalized_reason:
            # Production history contains an old extraction explanation which
            # the later saved fact snapshot normalized to empty. Restoring the
            # latest complete snapshot must not resurrect that older version.
            packet["fact_conflicts"].append({"field": "currency", "values": ["USD", "CNY"], "reason": ""})
        if cleared_optional:
            packet["unknown_facts"] = ["net_weight_g", "product_origin"]
        fact_path = f"/stores/{self.store_id}/product-facts"
        status, anchor = self.request(fact_path, method="POST", body={
            "listing_project_identity": identity, "merchant_product_fact_packet": packet})
        self.assertEqual(status, 201)
        # The immutable source anchor is distinct from the selected candidate's
        # project; never create two different full identities under one key.
        identity.update(key="listing-project-media-selected-" + uuid.uuid4().hex,
                        source_report_id=anchor["report"]["report_id"], candidate_id="candidate-media")
        status, facts = self.request(fact_path, method="POST", body={
            "listing_project_identity": identity, "merchant_product_fact_packet": packet})
        self.assertEqual(status, 201)
        output = {"title": "Foldable Aluminum Tablet Stand",
            "selling_points": ["Aluminum construction", "Foldable design", "Silicone contact pads"],
            "description": "A foldable aluminum tablet stand with silicone contact pads for desktop use.",
            "category_suggestion": "Tablet Stands", "keywords": ["tablet stand"],
            "item_specifics": {"Type": "Tablet Stand"}}
        (self.root / "provider-control.json").write_text(json.dumps({"output": output}), encoding="utf-8")
        status, generated = self.request(self.path, method="POST", body={
            "operation_id": str(uuid.uuid4()), "listing_project_identity": identity,
            "merchant_product_fact_packet": facts["merchant_product_fact_packet"], "current_draft_fields": {}})
        self.assertEqual(status, 201, "the real generation endpoint must produce the scoped proof")
        self.assertEqual(len(self.calls()), 2)
        report = generated["report"]
        fields = {key: "" for key in FIELD_KEYS}
        fields.update(title=output["title"], selling_points="\n".join(output["selling_points"]),
                      description=output["description"])
        checkpoint_path = f"/stores/{self.store_id}/listing-drafts/{identity['key']}/checkpoint"
        status, _saved = self.request(checkpoint_path, method="POST", body={
            "contract_version": "listing_merchant_edit_v1", "listing_project_identity": identity,
            "base_report_id": report["report_id"], "expected_revision": 0, "mutation_id": str(uuid.uuid4()),
            "fields": fields, "merchant_edited_fields": []})
        self.assertEqual(status, 201)
        # Seed only a pending local media job, through the real repository. It
        # has no provider result or merchant approval; no proof is forged.
        from jiejing_saas.repository import SaaSRepository
        profile = self.request("/me")[1]
        repository = SaaSRepository(self.root / "saas.sqlite", database_engine="sqlite", database_url="")
        if old_generation or all_history_old:
            # Real saved generation, then enough unrelated product history to
            # evict it from the UI's recent-24 feed, followed by an unchanged
            # fact successor and an explicitly adopted text checkpoint.
            for index in range(27):
                repository.save_merchant_product_fact_report(task=facts["task"], packet=facts["merchant_product_fact_packet"],
                    listing_project_identity={**identity, "key": f"unrelated-history-{index}"},
                    _created_at=f"2027-01-01T00:00:{index:02d}+00:00")
            if not all_history_old:
                successor = repository.save_merchant_product_fact_report(task=facts["task"],
                    packet=facts["merchant_product_fact_packet"], listing_project_identity=identity,
                    _created_at="2027-01-02T00:00:00+00:00")
                status, _ = self.request(checkpoint_path, method="POST", body={
                    "contract_version": "listing_merchant_edit_v1", "listing_project_identity": identity,
                    "base_report_id": successor["report_id"], "expected_revision": 1, "mutation_id": str(uuid.uuid4()),
                    "fields": fields, "merchant_edited_fields": []})
                self.assertEqual(status, 201)
            recent = self.request("/reports?limit=24")[1]["reports"]
            gc.collect()
            self.assertNotIn(report["report_id"], [item["report_id"] for item in recent])
            if all_history_old:
                self.assertFalse(any(item["report"].get("listing_project_identity", {}).get("key") == identity["key"]
                                     for item in recent), "the cold page must start without any project report")
            else:
                self.assertIn(successor["report_id"], [item["report_id"] for item in recent])
        if with_conflicts:
            # The original vision report retains provenance metadata, while a
            # later merchant fact save uses the public normalized schema.
            # Both records legitimately exist in the same project history.
            original_packet = copy.deepcopy(facts["merchant_product_fact_packet"])
            original_packet["fact_conflicts"][0].update(image_indexes=[1, 2], requires_merchant_confirmation=True)
            if historical_normalized_reason:
                original_packet["fact_conflicts"][1]["reason"] = "本轮文字资料与图片建议不同，均未确认，请核对真实商品资料。"
            if cleared_optional:
                original_packet["derived_listing_suggestions"].update(net_weight_g="120", product_origin="Jieyang, Guangdong")
            repository.save_merchant_product_fact_report(task=facts["task"], packet=original_packet,
                listing_project_identity=identity, _created_at="2020-01-01T00:00:00+00:00")
        pending_media = repository.create_media_asset_job(
            company_id=profile["identity"]["company_id"], store_id=self.store_id,
            task_id=report["task_id"], user_id=profile["identity"]["user_id"],
            provider_job_key="local-pending-media", idempotency_key=str(uuid.uuid4()),
            job_spec={"inputs": {"product_facts": {"listing_project_key": identity["key"]}}})
        del repository
        gc.collect()  # Release SQLite's completed context handles before Windows cleanup.
        result = subprocess.run([node, str(ROOT / "tools/test_jiejing_listing_cloud_checkpoint_http_smoke.js")],
            cwd=ROOT, text=True, encoding="utf-8", capture_output=True, timeout=90,
            input=json.dumps({"scenario": "new-media-after-generation", "api_base": self.base,
                "session_token": self.token, "profile": profile, "store_id": self.store_id,
                "identity": identity, "expected_copy": fields, "simulation_only": simulation_only,
                "expected_unknown_fields": ["net_weight_g", "product_origin"] if cleared_optional else [],
                "pending_media": pending_media}))
        # Only the child's fixed diagnostic is surfaced, never a local credential or response body.
        self.assertEqual(result.returncode, 0, "real media-to-publish loop failed: " + result.stderr)
        evidence = json.loads(result.stdout)
        self.assertTrue(evidence["copy_preserved"])
        self.assertTrue(evidence["cold_reload_preserved"])
        self.assertFalse(evidence["model_generated_after_checkpoint"])
        self.assertFalse(evidence["base_changed"])
        self.assertEqual(evidence["external_requests"], 0)
        self.assertEqual(evidence["page_errors"], 0)
        self.assertEqual(evidence["source_blockers"], ["simulation_only_product_facts"] if simulation_only else
                         ["media_job_not_approved", "image_rights_not_attested", "image_assets_missing"])
        self.assertTrue(evidence["denials_created_no_business_records"])
        self.assertTrue(evidence["confirmation_entry_exercised"])
        self.assertEqual(len(self.calls()), 2, "image saving must never regenerate buyer copy")

    def test_operation_result_is_readable_and_replay_does_not_call_model_again(self):
        operation_id = str(uuid.uuid4())
        request = {**self.body, "operation_id": operation_id}
        status, generated = self.request(self.path, method="POST", body=request)
        self.assertEqual(status, 201)
        report_id = generated["report"]["report_id"]
        calls = len(self.calls())
        quota = self.quota()
        status_path = f"/stores/{self.store_id}/listing-drafts/{self.identity['key']}/generation-status?" + urllib.parse.urlencode({
            "operation_id": operation_id, "source_report_id": self.identity["source_report_id"],
            "candidate_id": self.identity["candidate_id"],
        })
        status, observed = self.request(status_path)
        self.assertEqual(status, 200)
        self.assertEqual(observed["contract_version"], "listing_generation_operation_v1")
        self.assertEqual(observed["operation_id"], operation_id)
        self.assertEqual(observed["status"], "report_saved")
        self.assertEqual(observed["report"]["report_id"], report_id)
        self.assertIs(observed["can_retry"], False)
        status, replay = self.request(self.path, method="POST", body=request)
        self.assertEqual(status, 200)
        self.assertEqual(replay["status"], "report_saved")
        self.assertEqual(replay["report"]["report_id"], report_id)
        self.assertEqual(len(self.calls()), calls)
        self.assertEqual(self.quota(), quota)

    def test_pending_operation_replay_and_conflict_do_not_reserve_or_generate_again(self):
        operation_id = str(uuid.uuid4())
        request = {**self.body, "operation_id": operation_id}
        (self.root / "provider-control.json").write_text(json.dumps({"hold": True}), encoding="utf-8")
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(self.request, self.path, method="POST", body=request)
            try:
                deadline = time.monotonic() + 10
                while not (self.root / "provider-entered").exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertTrue((self.root / "provider-entered").exists())
                quota = self.quota()
                status, pending = self.request(self.path, method="POST", body=request)
                self.assertEqual(status, 200)
                self.assertEqual(pending["status"], "running")
                self.assertIs(pending["can_retry"], False)
                changed = {**request, "current_draft_fields": {**request["current_draft_fields"], "title": "不同的标题"}}
                status, conflict = self.request(self.path, method="POST", body=changed)
                self.assertEqual(status, 409)
                self.assertEqual(conflict["status"], "conflict")
                self.assertIs(conflict["can_retry"], False)
                changed_marks = {**request, "current_draft_fields": {**request["current_draft_fields"],
                    "merchant_edited_fields": [key for key in self.edited if key != "price"]}}
                self.assertEqual({key: changed_marks["current_draft_fields"][key] for key in FIELD_KEYS}, self.fields)
                self.assertNotEqual(changed_marks["current_draft_fields"]["merchant_edited_fields"], self.edited)
                status, marks_conflict = self.request(self.path, method="POST", body=changed_marks)
                self.assertEqual(status, 409)
                self.assertEqual(marks_conflict["status"], "conflict")
                self.assertEqual(marks_conflict["failure_code"], "listing_generation_operation_conflict")
                self.assertIs(marks_conflict["can_retry"], False)
                self.assertEqual(len(self.calls()), 1)
                self.assertEqual(self.quota(), quota)
            finally:
                (self.root / "provider-release").touch()
            self.assertEqual(first.result(timeout=20)[0], 201)

    def test_not_found_then_resume_claim_prevents_late_original_post_from_executing_again(self):
        import threading

        request = {**self.body, "operation_id": str(uuid.uuid4())}
        status_path = f"/stores/{self.store_id}/listing-drafts/{self.identity['key']}/generation-status?" + urllib.parse.urlencode({
            "operation_id": request["operation_id"], "source_report_id": self.identity["source_report_id"],
            "candidate_id": self.identity["candidate_id"]})
        original_ready, release_original = threading.Event(), threading.Event()
        quota_before = self.quota()
        (self.root / "provider-control.json").write_text(json.dumps({"hold": True}), encoding="utf-8")

        def delayed_original_post():
            # Delay only delivery of the frozen client request, not API claim/storage.
            original_ready.set()
            if not release_original.wait(timeout=10):
                raise TimeoutError("late original request was not released")
            return self.request(self.path, method="POST", body=request)

        with ThreadPoolExecutor(max_workers=2) as pool:
            original = pool.submit(delayed_original_post)
            try:
                self.assertTrue(original_ready.wait(timeout=5))
                status, missing = self.request(status_path)
                self.assertEqual(status, 200)
                self.assertEqual(missing["operation_id"], request["operation_id"])
                self.assertEqual(missing["status"], "not_found")
                self.assertIs(missing["report"], None)
                self.assertIs(missing["can_retry"], False)
                self.assertEqual(self.calls(), [])
                self.assertEqual(self.quota(), quota_before)

                resumed = pool.submit(self.request, self.path, method="POST", body=copy.deepcopy(request))
                deadline = time.monotonic() + 10
                while not (self.root / "provider-entered").exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertTrue((self.root / "provider-entered").exists())
                quota_pending = self.quota()
                release_original.set()
                status, replay = original.result(timeout=10)
                self.assertEqual(status, 200)
                self.assertEqual(replay["status"], "running")
                self.assertEqual(replay["operation_id"], request["operation_id"])
                self.assertEqual(replay["task_id"], missing["task_id"])
                self.assertIs(replay["can_retry"], False)
                self.assertEqual(len(self.calls()), 1)
                self.assertEqual(self.quota(), quota_pending)
            finally:
                release_original.set()
                (self.root / "provider-release").touch()
            status, generated = resumed.result(timeout=20)
            self.assertEqual(status, 201)
            self.assertEqual(generated["report"]["task_id"], missing["task_id"])

        quota_completed = self.quota()
        self.assertEqual(quota_completed["used"], quota_before["used"] + 1)
        status, observed = self.request(status_path)
        self.assertEqual(status, 200)
        self.assertEqual(observed["status"], "report_saved")
        self.assertEqual(observed["task_id"], missing["task_id"])
        self.assertEqual(observed["report"]["report_id"], generated["report"]["report_id"])
        self.assertEqual(len(self.calls()), 2)
        self.assertEqual(self.quota(), quota_completed)

    def test_operation_is_claimed_before_source_precheck_can_race_a_replay(self):
        request = {**self.body, "operation_id": str(uuid.uuid4())}
        (self.root / "provider-control.json").write_text(json.dumps({"hold_first_source_read": True}), encoding="utf-8")
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(self.request, self.path, method="POST", body=request)
            try:
                deadline = time.monotonic() + 10
                while not (self.root / "source-entered").exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertTrue((self.root / "source-entered").exists())
                status, replay = self.request(self.path, method="POST", body=request)
                self.assertEqual(status, 200)
                self.assertEqual(replay["status"], "running")
                self.assertIs(replay["can_retry"], False)
                self.assertEqual(self.calls(), [], "a replay cannot overtake its source-checking owner")
            finally:
                (self.root / "source-release").touch()
            self.assertEqual(first.result(timeout=20)[0], 201)
        self.assertEqual(len(self.calls()), 2)

    def test_claimed_operation_source_failure_settles_without_model_and_never_reexecutes(self):
        request = {**self.body, "operation_id": str(uuid.uuid4())}
        (self.root / "provider-control.json").write_text(json.dumps({"source_read_error": True}), encoding="utf-8")
        status, blocked = self.request(self.path, method="POST", body=request)
        self.assertEqual(status, 503)
        self.assertEqual(blocked["failure_code"], "listing_rewrite_source_unavailable")
        status_path = f"/stores/{self.store_id}/listing-drafts/{self.identity['key']}/generation-status?" + urllib.parse.urlencode({
            "operation_id": request["operation_id"], "source_report_id": self.identity["source_report_id"],
            "candidate_id": self.identity["candidate_id"]})
        status, observed = self.request(status_path)
        self.assertEqual(status, 200)
        self.assertEqual(observed["status"], "failed_before_report")
        self.assertIs(observed["can_retry"], True)
        self.assertIs(observed["model_called"], False)
        self.assertIs(observed["usage_consumed"], False)
        self.assertIs(observed["report_save_attempted"], False)
        (self.root / "provider-control.json").write_text("{}", encoding="utf-8")
        status, replay = self.request(self.path, method="POST", body=request)
        self.assertEqual(status, 200)
        self.assertEqual(replay["status"], "failed_before_report")
        self.assertEqual(self.calls(), [])
        self.assertEqual(self.quota()["used"], 0)
        status, retry = self.request(self.path, method="POST", body={**request, "operation_id": str(uuid.uuid4())})
        self.assertEqual(status, 201)
        self.assertEqual(retry["status"], "completed")
        self.assertEqual(len(self.calls()), 2)

    def test_legacy_failed_result_requires_exact_task_checkpoint_and_presave_ledger(self):
        invalid_output = LocalModelBoundary().output
        invalid_output["title"] = "中文结果不能通过"
        (self.root / "provider-control.json").write_text(json.dumps({"output": invalid_output}), encoding="utf-8")
        status, failed = self.request(self.path, method="POST", body=self.body)
        self.assertEqual(status, 422)
        query = {"legacy_task_id": failed["task_id"], "source_report_id": self.identity["source_report_id"],
                 "candidate_id": self.identity["candidate_id"], "expected_base_report_id": self.body["expected_base_report_id"],
                 "expected_checkpoint_revision": 1}
        path = f"/stores/{self.store_id}/listing-drafts/{self.identity['key']}/generation-status?"
        before_tasks, before_reports, quota = self.request("/tasks")[1], self.request("/reports")[1], self.quota()
        status, result = self.request(path + urllib.parse.urlencode(query))
        self.assertEqual(status, 200)
        self.assertEqual(result["status"], "legacy_failed_before_report")
        self.assertIs(result["can_retry"], True)
        self.assertEqual(result["proof_kind"], "immutable_failed_usage_ledger")
        self.assertNotIn("report_save_attempted", result)
        self.assertNotIn("operation_id", result)
        status, wrong = self.request(path + urllib.parse.urlencode({**query, "expected_checkpoint_revision": 2}))
        self.assertEqual(status, 200)
        self.assertEqual(wrong["status"], "legacy_evidence_incomplete")
        self.assertIs(wrong["can_retry"], False)
        self.assertEqual(len(self.calls()), 2)
        self.assertEqual(self.request("/tasks")[1], before_tasks)
        self.assertEqual(self.request("/reports")[1], before_reports)
        self.assertEqual(self.quota(), quota)

    def test_legacy_saved_report_recovery_preserves_authenticated_author(self):
        status, generated = self.request(self.path, method="POST", body=self.body)
        self.assertEqual(status, 201)
        query = {"legacy_task_id": generated["report"]["task_id"],
                 "source_report_id": self.identity["source_report_id"], "candidate_id": self.identity["candidate_id"],
                 "expected_base_report_id": self.body["expected_base_report_id"], "expected_checkpoint_revision": 1}
        path = f"/stores/{self.store_id}/listing-drafts/{self.identity['key']}/generation-status?"
        before_tasks, before_reports, quota = self.request("/tasks")[1], self.request("/reports")[1], self.quota()
        status, recovered = self.request(path + urllib.parse.urlencode(query))
        self.assertEqual(status, 200)
        self.assertEqual(recovered["status"], "report_saved")
        self.assertEqual(recovered["report"]["report_id"], generated["report"]["report_id"])
        self.assertEqual(recovered["report"].get("user_id"), recovered["user_id"])
        self.assertIs(recovered["can_retry"], False)
        self.assertEqual(self.request("/tasks")[1], before_tasks)
        self.assertEqual(self.request("/reports")[1], before_reports)
        self.assertEqual(self.quota(), quota)
        self.assertEqual(len(self.calls()), 2)

    def test_http_requires_the_saved_source_revision_before_model(self):
        status, rejected = self.request(self.path, method="POST", body={**self.body,
            "expected_checkpoint_revision": 0})
        self.assertEqual(status, 409)
        self.assertEqual(rejected["failure_code"], "listing_rewrite_source_conflict")
        self.assertFalse(rejected["model_called"])
        self.assertFalse(rejected["usage_consumed"])
        self.assertIsNone(rejected["report"])
        self.assertEqual(self.calls(), [])

    def test_source_storage_unavailable_is_a_known_no_model_block_and_retry_recovers(self):
        original_reports = self.request("/reports")[1]
        original_tasks = self.request("/tasks")[1]
        original_quota = self.quota()
        (self.root / "provider-control.json").write_text(json.dumps({"source_read_error": True}), encoding="utf-8")
        status, blocked = self.request(self.path, method="POST", body=self.body)
        self.assertEqual(status, 503)
        self.assertEqual(blocked, {
            "status": "blocked",
            "failure_code": "listing_rewrite_source_unavailable",
            "blocked_by": ["listing_rewrite_source_unavailable"],
            "merchant_message": "原稿或商品资料已变化，或云端保存暂不可用；请核对后再重写。现有文案未被替换。",
            "model_called": False, "usage_consumed": False, "report": None,
            "real_platform_writes_enabled": False, "secret_exposed": False,
        })
        for key in ("model_called", "usage_consumed", "real_platform_writes_enabled", "secret_exposed"):
            self.assertIs(blocked[key], False)
        self.assertEqual(self.calls(), [])
        after_block_quota = self.quota()
        self.assertEqual(after_block_quota["used"], original_quota["used"])
        self.assertEqual(after_block_quota["remaining"], original_quota["remaining"])
        self.assertEqual(self.request("/reports")[1], original_reports)
        self.assertEqual(self.request("/tasks")[1], original_tasks)
        # Remove only the synthetic storage fault; leave original source,
        # checkpoint, quota, auth and request unchanged for the explicit retry.
        (self.root / "provider-control.json").write_text("{}", encoding="utf-8")
        self.assertEqual(self.request(self.checkpoint_path + self.checkpoint_query)[1]["checkpoint"], self.original_checkpoint)
        status, completed = self.request(self.path, method="POST", body=self.body)
        self.assertEqual(status, 201)
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(len(self.calls()), 2)
        self.assertEqual(self.quota()["used"], original_quota["used"] + 1)
        self.assertEqual(len(self.request("/reports")[1]["reports"]), len(original_reports["reports"]) + 1)
        self.assertEqual(self.request(self.checkpoint_path + self.checkpoint_query)[1]["checkpoint"], self.original_checkpoint)

    def test_http_rewrite_persists_original_and_accepts_new_checkpoint(self):
        self.assertEqual(self.quota()["used"], 0)
        status, generated = self.request(self.path, method="POST", body=self.body)
        self.assertEqual(status, 201, generated)
        self.assertEqual(generated["status"], "completed", generated)
        report = generated["report"]
        stored_report = next(item for item in self.request("/reports")[1]["reports"] if item["report_id"] == report["report_id"])
        self.assertEqual(report.get("company_id"), stored_report["company_id"])
        self.assertEqual(report.get("store_id"), stored_report["store_id"])
        checkpoint_base = self.request(self.checkpoint_path + self.checkpoint_query)[1]["current_base_report"]
        self.assertEqual(checkpoint_base["report_id"], report["report_id"])
        self.assertEqual(checkpoint_base["task_id"], report["task_id"])
        generation_task = next(item for item in self.request("/tasks")[1]["tasks"] if item["task_id"] == report["task_id"])
        self.assertEqual(generation_task["user_id"], self.request("/me")[1]["identity"]["user_id"])
        self.assertEqual(checkpoint_base.get("user_id"), generation_task["user_id"], "checkpoint projection retains the actual task author")
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
        self.assertEqual(len(self.calls()), 2)
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
        self.assertEqual(len(self.calls()), 4)

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
        self.assertEqual(status, 422)
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
        self.assertEqual(len(self.calls()), 2, "a storage fault must not trigger another model request")

    def test_other_tenant_cannot_rewrite_or_read_the_original_project(self):
        status, other = self.request("/auth/register", method="POST", token="", body={
            "email": uuid.uuid4().hex + "@local.invalid", "password": "local-other-tenant-pass",
            "company_name": "Other local tenant"})
        self.assertEqual(status, 201)
        status_path = f"/stores/{self.store_id}/listing-drafts/{self.identity['key']}/generation-status?" + urllib.parse.urlencode({
            "operation_id": str(uuid.uuid4()), "source_report_id": self.identity["source_report_id"],
            "candidate_id": self.identity["candidate_id"],
        })
        for path, method, body in ((self.path, "POST", self.body),
            (self.checkpoint_path + self.checkpoint_query, "GET", None), (status_path, "GET", None)):
            with self.subTest(method=method):
                status, rejected = self.request(path, method=method, body=body, token=other["token"])
                self.assertEqual(status, 404)
                self.assertNotIn(self.fields["title"], json.dumps(rejected, ensure_ascii=False))
        self.assertEqual(self.calls(), [])
        self.assertEqual(self.quota()["used"], 0)

    def test_status_not_found_or_malformed_identity_never_authorizes_generation(self):
        operation_id = str(uuid.uuid4())
        query = {"operation_id": operation_id, "source_report_id": self.identity["source_report_id"],
                 "candidate_id": self.identity["candidate_id"]}
        path = f"/stores/{self.store_id}/listing-drafts/{self.identity['key']}/generation-status?"
        status, missing = self.request(path + urllib.parse.urlencode(query))
        self.assertEqual(status, 200)
        self.assertEqual(missing["status"], "not_found")
        self.assertIs(missing["can_retry"], False)
        for invalid in (urllib.parse.urlencode(query) + "&operation_id=another-id",
                        urllib.parse.urlencode({**query, "unexpected": "value"}),
                        urllib.parse.urlencode({key: value for key, value in query.items() if key != "candidate_id"})):
            status, rejected = self.request(path + invalid)
            self.assertEqual(status, 400)
            self.assertNotIn("can_retry", rejected)
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
        self.assertEqual(len(self.calls()), 2)

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
        self.assertEqual(len(self.calls()), 4)

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
        self.assertEqual(len(self.calls()), 2)

    def run_real_browser(self, wire_case=None, lose_generation_response=False, reload_before_check=False,
                         unregistered_first_response=False, legacy_request_signature=False):
        node = shutil.which("node")
        self.assertIsNotNone(node, "the configured Node runtime is required for local browser integration")
        base_report = self.request(self.checkpoint_path + self.checkpoint_query)[1]["current_base_report"]
        result = subprocess.run([node, str(ROOT / "tools/test_jiejing_listing_buyer_copy_rewrite_http_smoke.js")],
            cwd=ROOT, text=True, encoding="utf-8", capture_output=True, timeout=60,
            input=json.dumps({"api_base": self.base, "session_token": self.token,
                "profile": self.request("/me")[1], "store_id": self.store_id, "identity": self.identity,
                "base_report": base_report, "fields": self.fields, "merchant_edited_fields": self.edited,
                "wire_case": wire_case, "lose_generation_response": lose_generation_response,
                "reload_before_check": reload_before_check, "unregistered_first_response": unregistered_first_response,
                "legacy_request_signature": legacy_request_signature}),
            env={"SYSTEMROOT": "C:\\Windows", "PROGRAMFILES": "C:\\Program Files", "TEMP": str(self.root), "TMP": str(self.root),
                 "PATH": str(Path(node).parent)})
        # Never echo child output that could contain the local fixture session.
        safe_failure = next((line for line in result.stderr.splitlines()
            if line.startswith("buyer_copy_rewrite_http_browser_smoke_failed")
            and all(character.isalnum() or character == "_" for character in line)), "no_safe_failure_location")
        self.assertEqual(result.returncode, 0, "real browser -> HTTP rewrite integration failed: " + safe_failure)
        return json.loads(result.stdout)

    def test_real_browser_rewrites_saves_and_reloads_via_http(self):
        evidence = self.run_real_browser()
        self.assertEqual(evidence["generation_posts"], 1)
        self.assertEqual(evidence["checkpoint_posts"], 2, "one explicit original flush and one new-copy adoption")
        self.assertTrue(evidence["refreshed"])
        self.assertEqual(evidence["external_requests"], 0)
        current = self.request(self.checkpoint_path + self.checkpoint_query)[1]
        self.assertEqual(current["current_revision"], 3)
        self.assertNotEqual(current["checkpoint"]["fields"]["title"], self.fields["title"])
        self.assertEqual(current["checkpoint"]["fields"]["price"], self.fields["price"])
        self.assertEqual(len(self.calls()), 2)

    def assert_real_browser_default_generation(self, resume=False):
        copy_fields = {key: value for key, value in LocalModelBoundary().output.items()
                       if key in {"title", "selling_points", "description"}}
        self.fields.update({**copy_fields, "selling_points": "\n".join(copy_fields["selling_points"])})
        status, _ = self.request(self.checkpoint_path, method="POST", body={
            "contract_version": "listing_merchant_edit_v1", "listing_project_identity": self.identity,
            "base_report_id": self.body["expected_base_report_id"], "expected_revision": 1,
            "mutation_id": str(uuid.uuid4()), "fields": self.fields, "merchant_edited_fields": self.edited})
        self.assertEqual(status, 201)
        (self.root / "provider-control.json").write_text(json.dumps({"output": copy_fields}), encoding="utf-8")
        evidence = self.run_real_browser("default", unregistered_first_response=resume)
        self.assertEqual(evidence["status"], 201)
        self.assertEqual(evidence["generation_posts"], 2 if resume else 1)
        self.assertTrue(evidence["ui_metadata_retained_at_send"])
        self.assertEqual(evidence["external_requests"], 0)
        self.assertEqual(len(self.calls()), 2)
        return evidence

    def test_real_browser_default_generation_uses_the_same_wire_fact_contract(self):
        self.assert_real_browser_default_generation()

    def test_real_browser_signed_default_resumes_after_reload_without_changing_wire_or_creating_checkpoint(self):
        evidence = self.assert_real_browser_default_generation(resume=True)
        self.assertTrue(evidence["persisted_signature_reloaded"])
        self.assertEqual(evidence["checkpoint_posts"], 0)
        self.assertEqual(evidence["generation_status_gets"], 3)
        self.assertEqual(self.quota()["used"], 1)

    def assert_browser_wire_rejected(self, kind):
        before_tasks = self.request("/tasks")[1]
        evidence = self.run_real_browser(kind)
        self.assertEqual(evidence["status"], 400)
        self.assertEqual(evidence["generation_posts"], 1)
        self.assertTrue(evidence["ui_metadata_retained_at_send"])
        self.assertEqual(evidence["external_requests"], 0)
        self.assertEqual(self.request("/tasks")[1], before_tasks)
        self.assertEqual(self.request(self.checkpoint_path + self.checkpoint_query)[1]["checkpoint"]["fields"], self.fields)
        self.assertEqual(self.calls(), [])

    def test_real_browser_wire_unknown_packet_key_remains_rejected_before_model(self):
        self.assert_browser_wire_rejected("unknown")

    def test_real_browser_wire_sensitive_fact_remains_rejected_before_model(self):
        self.assert_browser_wire_rejected("sensitive")

    def test_real_browser_lost_rewrite_response_recovers_exact_result_with_original_revision(self):
        evidence = self.run_real_browser(lose_generation_response=True)
        self.assertEqual(evidence["generation_posts"], 1)
        self.assertEqual(evidence["generation_status_gets"], 1)
        self.assertEqual(evidence["checkpoint_posts"], 2)
        self.assertTrue(evidence["refreshed"])
        self.assertEqual(evidence["external_requests"], 0)
        self.assertEqual(len(self.calls()), 2)

    def test_real_browser_lost_rewrite_response_reloads_original_signature_before_result_check(self):
        evidence = self.run_real_browser(lose_generation_response=True, reload_before_check=True)
        self.assertTrue(evidence["persisted_signature_reloaded"])
        self.assertEqual(evidence["generation_posts"], 1)
        self.assertEqual(evidence["generation_status_gets"], 1)
        self.assertEqual(evidence["checkpoint_posts"], 2)
        self.assertTrue(evidence["refreshed"])
        self.assertEqual(evidence["external_requests"], 0)
        self.assertEqual(len(self.calls()), 2)

    def test_real_browser_continues_unregistered_generation_with_original_operation_once(self):
        evidence = self.run_real_browser(unregistered_first_response=True)
        self.assertEqual(evidence["generation_posts"], 2)
        self.assertEqual(evidence["generation_status_gets"], 3)
        self.assertEqual(evidence["checkpoint_posts"], 2, "continue must not flush or rebase the original source")
        self.assertTrue(evidence["refreshed"])
        self.assertEqual(evidence["external_requests"], 0)
        self.assertEqual(len(self.calls()), 2)
        self.assertEqual(self.quota()["used"], 1)

    def test_real_browser_legacy_unregistered_rewrite_uses_original_input_and_exact_checkpoint_proof(self):
        evidence = self.run_real_browser(unregistered_first_response=True, legacy_request_signature=True)
        self.assertEqual(evidence["generation_posts"], 2)
        self.assertEqual(evidence["checkpoint_posts"], 2)
        self.assertTrue(evidence["legacy_request_signature_remains_absent"])
        self.assertEqual(len(self.calls()), 2)
        self.assertEqual(self.quota()["used"], 1)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--serve-fixture":
        serve_fixture(sys.argv[2], sys.argv[3])
    else:
        unittest.main()
