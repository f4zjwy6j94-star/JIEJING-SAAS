"""Metadata-only support binding; all identities and credentials refs synthetic."""
from __future__ import annotations

import gc
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from jiejing_saas.repository import SaaSRepository
from jiejing_saas import repository as repository_module

MESSAGE_SCOPE = "https://api.ebay.com/oauth/api_scope/commerce.message"


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


class SupportConnectionBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="jiejing-support-boundary-")
        self.repo = SaaSRepository(Path(self.temp.name) / "synthetic.sqlite", database_engine="sqlite", database_url="")
        account = self.repo.create_user_with_company(email="boundary@example.test", password="synthetic-password",
                                                     company_name="Synthetic boundary")
        self.company, self.user = account["company"]["company_id"], account["user"]["user_id"]
        self.store = self.repo.create_store(company_id=self.company, user_id=self.user, payload={"platform": "ebay"})["store_id"]

    def tearDown(self):
        gc.collect()
        self.temp.cleanup()

    def fixture(self, *, scope=MESSAGE_SCOPE, verified=True):
        scopes = [scope]
        request = self.repo.create_oauth_authorization_request(company_id=self.company, store_id=self.store,
            user_id=self.user, plan={"platform": "ebay", "status": "ready_to_redirect", "state_nonce": "synthetic-state",
                                     "scopes": scopes, "environment": "production"})
        self.request_id = request["oauth_request_id"]
        secret = self.repo.create_secret_reference(company_id=self.company, store_id=self.store, user_id=self.user,
            provider="ebay", purpose="ebay_refresh_token", status="managed_vault_stored",
            metadata={"oauth_request_id": self.request_id, "credential_owner": "jiejing_saas_backend"})
        self.ref = secret["secret_ref"]
        self.metadata = {"oauth_request_id": self.request_id, "credential_source": "jiejing_vault_secret_ref",
            "environment": "production", "account_deletion_identity_mapping_status": "identity_mapping_ready",
            "ebay_user_id_hash": digest("synthetic-immutable-user"), "ebay_username_hash": digest("synthetic-seller"),
            "actual_granted_scope_verified": verified,
            "granted_scope_verification_source": "ebay_token_introspection" if verified else ""}
        connection = self.repo.create_platform_connection(company_id=self.company, store_id=self.store, user_id=self.user,
            payload={"platform": "ebay", "connection_type": "oauth", "status": "read_only_authorized",
                     "scopes": scopes, "secret_ref": self.ref, "metadata": self.metadata})
        self.connection_id = connection["connection_id"]
        self.event = {"status": "callback_exchange_completed", "token_exchange_performed": True,
            "connection": connection, "secret_exposed": False,
            "backend_connection_binding": {"contract_version": "2026-08-10-oauth-callback-connection-binding-v1",
                "oauth_request_id": self.request_id, "connection_id": self.connection_id,
                "connection_id_sha256": digest(self.connection_id), "credential_ref_sha256": digest(self.ref),
                "seller_identity_sha256": digest(self.metadata["ebay_user_id_hash"]),
                "created_by_backend_callback": True, "secret_exposed": False},
            "granted_scope_verification": {"source": "ebay_token_introspection", "active": verified,
                "client_id_matched": verified, "exact_scope_matched": verified, "secret_exposed": False}}
        self.repo.update_oauth_authorization_request(oauth_request_id=self.request_id,
            status="callback_exchange_completed", details=self.event)

    def boundary(self, **kwargs):
        with patch.object(self.repo, "initialize", side_effect=AssertionError("metadata GET must not initialize")):
            return self.repo.get_support_connection_boundary(company_id=kwargs.get("company_id", self.company),
                                                             store_id=kwargs.get("store_id", self.store))

    def test_verified_binding_is_internal_and_does_not_enable_network(self):
        self.fixture()
        result = self.boundary()
        self.assertTrue(result["ready"])
        self.assertTrue(result["connection_bound"])
        self.assertTrue(result["granted_message_scope_verified"])
        self.assertEqual(result["internal"]["secret_ref"], self.ref)
        self.assertEqual(result["internal"]["owner_username_hash"], digest("synthetic-seller"))
        self.assertFalse(result["read_enabled"])
        self.assertFalse(result["send_enabled"])
        self.assertFalse(result["external_request_performed"])
        public = repository_module._public_support_connection_boundary(result)
        for forbidden in (self.ref, self.connection_id, self.request_id, digest("synthetic-seller")):
            self.assertNotIn(forbidden, json.dumps(public))
        self.assertNotIn("internal", public)

    def test_requested_scope_does_not_prove_granted_scope(self):
        self.fixture(verified=False)
        result = self.boundary()
        self.assertTrue(result["connection_bound"])
        self.assertTrue(result["requested_message_scope_present"])
        self.assertFalse(result["ready"])
        self.assertFalse(result["granted_message_scope_verified"])
        self.assertIn("support_message_scope_unverified", result["blocked_by"])
        self.assertEqual(result["internal"]["secret_ref"], self.ref)

    def test_absent_store_connection_and_scope_are_explicit(self):
        missing = self.boundary()
        self.assertIn("support_connection_missing", missing["blocked_by"])
        self.assertNotIn("internal", missing)
        wrong = self.boundary(company_id="other-company")
        self.assertIn("support_store_not_accessible", wrong["blocked_by"])
        self.fixture(scope="https://api.ebay.com/oauth/api_scope/sell.inventory.readonly")
        result = self.boundary()
        self.assertFalse(result["ready"])
        self.assertIn("support_message_scope_missing", result["blocked_by"])

    def test_missing_database_does_not_create_a_file_or_schema(self):
        path = Path(self.temp.name) / "absent.sqlite"
        empty = SaaSRepository(path, database_engine="sqlite", database_url="")
        with patch.object(empty, "initialize", side_effect=AssertionError("must not initialize")):
            result = empty.get_support_connection_boundary(company_id=self.company, store_id=self.store)
        self.assertIn("support_metadata_unavailable", result["blocked_by"])
        self.assertFalse(path.exists())

    def sql(self, statement, params=()):
        conn = self.repo._connect()
        try:
            with conn:
                conn.execute(statement, params)
        finally:
            conn.close()

    def patch_metadata(self, updates):
        self.sql("update platform_connections set metadata_json=? where connection_id=?",
                 (json.dumps({**self.metadata, **updates}), self.connection_id))

    def test_multiple_authorized_connections_never_choose_a_convenient_one(self):
        self.fixture()
        self.repo.create_platform_connection(company_id=self.company, store_id=self.store, user_id=self.user,
            payload={"platform": "ebay", "connection_type": "oauth", "status": "read_only_authorized",
                     "scopes": [MESSAGE_SCOPE], "secret_ref": self.ref, "metadata": self.metadata})
        result = self.boundary()
        self.assertIn("support_connection_ambiguous", result["blocked_by"])
        self.assertFalse(result["connection_bound"])
        self.assertNotIn("internal", result)

    def test_invalid_connection_metadata_fails_without_internal_selectors(self):
        self.fixture()
        cases = [({"environment": "sandbox"}, "support_message_environment_not_production"),
                 ({"environment": ""}, "support_message_environment_not_production"),
                 ({"ebay_username_hash": ""}, "support_owner_identity_binding_missing"),
                 ({"ebay_user_id_hash": "not-a-hash"}, "support_owner_identity_binding_missing"),
                 ({"credential_source": "environment_fallback"}, "support_connection_not_backend_oauth"),
                 ({"token_endpoint": "https://api.sandbox.ebay.com/identity/v1/oauth2/token"}, "support_message_environment_not_production")]
        for metadata, code in cases:
            with self.subTest(code=code, field=list(metadata)[0]):
                self.patch_metadata(metadata)
                result = self.boundary()
                self.assertIn(code, result["blocked_by"])
                self.assertNotIn("internal", result)

    def test_secret_reference_wrong_purpose_provider_status_or_store_fails_closed(self):
        self.fixture()
        cases = [("purpose", "model_api_key", "support_secret_ref_wrong_purpose"),
                 ("provider", "other", "support_secret_ref_wrong_purpose"),
                 ("status", "revoked", "support_secret_ref_not_available"),
                 ("store_id", "other-store", "support_secret_ref_not_bound"),
                 ("company_id", "other-company", "support_secret_ref_not_bound")]
        originals = {"purpose": "ebay_refresh_token", "provider": "ebay", "status": "managed_vault_stored",
                     "store_id": self.store, "company_id": self.company}
        for column, value, code in cases:
            with self.subTest(column=column):
                self.sql(f"update secret_refs set {column}=? where secret_ref=?", (value, self.ref))
                result = self.boundary()
                self.assertIn(code, result["blocked_by"])
                self.assertNotIn("internal", result)
                self.sql(f"update secret_refs set {column}=? where secret_ref=?", (originals[column], self.ref))

    def test_callback_binding_hashes_and_backend_origin_are_required(self):
        self.fixture()
        conn = self.repo._connect()
        try:
            original = json.loads(conn.execute("select request_json from oauth_authorization_requests where oauth_request_id=?",
                                              (self.request_id,)).fetchone()["request_json"])
        finally:
            conn.close()
        for key, value in (("connection_id_sha256", digest("wrong")), ("credential_ref_sha256", digest("wrong")),
                           ("seller_identity_sha256", digest("wrong")), ("created_by_backend_callback", False)):
            with self.subTest(key=key):
                payload = json.loads(json.dumps(original))
                payload["callback_events"][0]["backend_connection_binding"][key] = value
                self.sql("update oauth_authorization_requests set request_json=? where oauth_request_id=?",
                         (json.dumps(payload), self.request_id))
                result = self.boundary()
                self.assertIn("support_callback_binding_invalid", result["blocked_by"])
                self.assertNotIn("internal", result)

    def test_system_callback_audit_is_required_and_must_correlate_in_time(self):
        self.fixture()
        self.sql("update audit_logs set actor_type='user' where target_id=? and action_type='oauth.callback.received'", (self.request_id,))
        result = self.boundary()
        self.assertIn("support_callback_audit_not_trusted", result["blocked_by"])
        self.assertNotIn("internal", result)
        self.sql("update audit_logs set actor_type='system', created_at='2000-01-01T00:00:00Z' where target_id=? and action_type='oauth.callback.received'", (self.request_id,))
        result = self.boundary()
        self.assertIn("support_callback_audit_not_trusted", result["blocked_by"])

    def test_self_asserted_scope_flag_without_matching_callback_proof_is_not_verified(self):
        self.fixture(verified=False)
        self.patch_metadata({"actual_granted_scope_verified": True, "granted_scope_verification_source": "ebay_token_introspection"})
        result = self.boundary()
        self.assertTrue(result["connection_bound"])
        self.assertFalse(result["granted_message_scope_verified"])
        self.assertFalse(result["ready"])
        self.assertIn("support_message_scope_unverified", result["blocked_by"])

    def test_accessor_issues_select_only_and_never_calls_initialization_or_network(self):
        self.fixture()
        conn = self.repo._connect()
        statements = []
        conn.set_trace_callback(statements.append)
        with patch.object(self.repo, "_connect", return_value=conn), \
             patch("socket.socket", side_effect=AssertionError("must not network")):
            result = self.boundary()
        self.assertTrue(result["ready"])
        self.assertTrue(statements)
        self.assertTrue(all(statement.lstrip().lower().startswith("select ") for statement in statements), statements)

    def test_postgres_metadata_path_does_not_initialize_or_run_ddl(self):
        self.fixture()
        candidate = SaaSRepository(self.repo.db_path, database_engine="postgres", database_url="postgresql://synthetic.invalid/db")
        conn = self.repo._connect()
        statements = []
        conn.set_trace_callback(statements.append)
        try:
            with patch.object(candidate, "_connect", return_value=conn), \
                 patch.object(candidate, "initialize", side_effect=AssertionError("no initialize")), \
                 patch.object(candidate, "_initialize_postgres", side_effect=AssertionError("no migrations")), \
                 patch("socket.socket", side_effect=AssertionError("no provider requests")):
                result = candidate.get_support_connection_boundary(company_id=self.company, store_id=self.store)
            self.assertTrue(result["ready"])
            self.assertTrue(all(statement.lstrip().lower().startswith("select ") for statement in statements))
        finally:
            conn.close()

    def test_metadata_context_failure_clears_all_readiness_claims(self):
        self.fixture()
        for stage in ("enter", "select", "exit"):
            with self.subTest(stage=stage):
                raw = self.repo._connect()
                class FailingContext:
                    def __enter__(self):
                        if stage == "enter":
                            raise RuntimeError("synthetic-driver-error-do-not-expose")
                        return self
                    def execute(self, *args, **kwargs):
                        if stage == "select":
                            raise RuntimeError("synthetic-driver-error-do-not-expose")
                        return raw.execute(*args, **kwargs)
                    def __exit__(self, *args):
                        if stage == "exit":
                            raise RuntimeError("synthetic-driver-error-do-not-expose")
                    def close(self):
                        raw.close()
                with patch.object(self.repo, "_connect", return_value=FailingContext()), \
                     patch("socket.socket", side_effect=AssertionError("must not network")):
                    result = self.boundary()
                public = repository_module._public_support_connection_boundary(result)
                for value in (result, public):
                    self.assertFalse(value["ready"])
                    self.assertEqual(value["status"], "blocked")
                    self.assertFalse(value["connection_bound"])
                    self.assertFalse(value["requested_message_scope_present"])
                    self.assertFalse(value["granted_message_scope_verified"])
                    self.assertEqual(value["scope_verification_source"], "")
                    self.assertIsNone(value["scope_verified_at"])
                    self.assertFalse(value["read_enabled"])
                    self.assertFalse(value["send_enabled"])
                    self.assertFalse(value["live_end_to_end_verified"])
                    self.assertIn("support_metadata_unavailable", value["blocked_by"])
                    self.assertNotIn("synthetic-driver-error", json.dumps(value))
                    self.assertNotIn("internal", value)

    def test_owner_selector_never_claims_live_identity_verification(self):
        snapshots = [("missing_connection", self.boundary())]
        self.fixture()
        snapshots.append(("metadata_ready", self.boundary()))
        # The historical callback proof binds seller identity, not this username
        # hash. Treat the latter only as an internal selector pending live check.
        self.patch_metadata({"ebay_username_hash": digest("changed-synthetic-owner")})
        snapshots.append(("changed_owner_selector", self.boundary()))
        for label, result in snapshots:
            with self.subTest(label=label):
                public = repository_module._public_support_connection_boundary(result)
                for value in (result, public):
                    self.assertTrue(value["requires_live_owner_check"])
                    self.assertFalse(value["owner_identity_verified"])
                    self.assertFalse(value["read_enabled"])
                    self.assertFalse(value["send_enabled"])
                    self.assertFalse(value["live_end_to_end_verified"])
                self.assertNotIn("changed-synthetic-owner", json.dumps(public))
                self.assertNotIn(digest("changed-synthetic-owner"), json.dumps(public))


if __name__ == "__main__":
    unittest.main()
