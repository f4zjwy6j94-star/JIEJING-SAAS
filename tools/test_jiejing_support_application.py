"""Offline application tests; all accounts, messages and network responses synthetic."""
from pathlib import Path
import hashlib
import json
import sqlite3
import time
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
import test_jiejing_support_connection_boundary as boundary_fixture
from jiejing_saas.ebay_message_adapter import MessageScope
from jiejing_saas.support_conversations import SupportConversations
from jiejing_saas.support_token_resolver import SupportTokenResolver
from jiejing_saas.ebay_message_adapter import MESSAGE_SCOPE


class SupportApplicationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = boundary_fixture.SupportConnectionBoundaryTests()
        self.fixture.setUp()
        self.fixture.fixture()
        self.addCleanup(self.fixture.tearDown)
        self.repo = self.fixture.repo
        self.scope = MessageScope(self.fixture.company, self.fixture.store,
            hashlib.sha256(b"synthetic-seller").hexdigest(), "sha256_casefold_ebay_username")
        self.service = SupportConversations(self.repo, self.scope)
        self.service.initialize_local_schema()
        self.incoming = {"status": "ok", "scope": self.scope.as_dict(), "conversation_id": "conv-1",
            "truncated": False, "messages": [{"messageId": "m1", "messageBody": "What colour? 💙",
                "senderUsername": "synthetic-buyer", "recipientUsername": "synthetic-seller",
                "createdDate": "2026-10-12T00:00:00Z", "extra": "must-never-project"}]}

    def context(self, **overrides):
        from jiejing_saas.support_application import SupportActorContext
        return SupportActorContext(**{**dict(actor_id=self.fixture.user, company_id=self.fixture.company,
            store_id=self.fixture.store), **overrides})

    def resolver(self, on_refresh=None):
        def refresh(*, binding, task_scope):
            if on_refresh:
                on_refresh()
            return {"ok": True, "http_status": 200, "source": "backend_vault_secret_ref_refresh",
                "binding": binding, "access_token": "synthetic-access-not-real", "token_type": "Bearer",
                "expires_in": 3600, "refreshed_at": int(time.time()), "secret_exposed": False}
        return SupportTokenResolver(self.repo, refresh=refresh,
            introspect=lambda **kwargs: {"ok": True, "http_status": 200, "active": True,
                "client_id": "synthetic-client", "scopes": [MESSAGE_SCOPE], "secret_exposed": False},
            get_identity=lambda **kwargs: {"status": "identity_mapping_ready",
                "ebay_user_id_hash": hashlib.sha256(b"synthetic-immutable-user").hexdigest(),
                "ebay_username_hash": self.scope.owner_id, "secret_exposed": False},
            expected_client_id="synthetic-client", verification_enabled=True)

    def test_default_disabled_does_not_create_database_or_call_network(self):
        from jiejing_saas.repository import SaaSRepository
        from jiejing_saas.support_application import SupportApplication, SupportActorContext
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "absent.sqlite"
            repo = SaaSRepository(path, database_engine="sqlite", database_url="")
            app = SupportApplication(repo)
            context = SupportActorContext("synthetic-user", "synthetic-company", "synthetic-store")
            with patch("socket.socket", side_effect=AssertionError("no network")):
                result = app.capability(context)
            self.assertEqual(result["status"], "blocked")
            self.assertEqual(result["blocked_by"], ["support_application_disabled"])
            self.assertFalse(result["send_enabled"])
            self.assertFalse(path.exists())

    def test_cached_gets_are_select_only_and_project_no_internal_metadata(self):
        from jiejing_saas.support_application import SupportApplication
        self.service.ingest(self.incoming)
        app = SupportApplication(self.repo, enabled=True)
        statements = []
        connect = sqlite3.connect
        def traced(*args, **kwargs):
            conn = connect(*args, **kwargs)
            conn.set_trace_callback(statements.append)
            return conn
        with patch("sqlite3.connect", side_effect=traced), \
             patch.object(self.repo, "initialize", side_effect=AssertionError("no DDL")), \
             patch("socket.socket", side_effect=AssertionError("no network")):
            capability = app.capability(self.context())
            listing = app.list_conversations(self.context())
            detail = app.get_conversation(self.context(), "conv-1")
        self.assertEqual(capability["status"], "local_cache_available")
        self.assertFalse(capability["credentials_verified"])
        self.assertEqual(listing["conversations"][0]["conversation_id"], "conv-1")
        self.assertEqual(detail["messages"], [{"message_id": "m1", "body": "What colour? 💙",
            "created_at": "2026-10-12T00:00:00.000000Z", "direction": "incoming"}])
        public = json.dumps([capability, listing, detail])
        for forbidden in (self.scope.owner_id, self.fixture.ref, self.fixture.connection_id,
                          "synthetic-seller", "synthetic-buyer", "must-never-project", '"scope"', '"extra"'):
            self.assertNotIn(forbidden, public)
        self.assertTrue(statements)
        for sql in statements:
            self.assertTrue(sql.lstrip().lower().startswith(("select", "pragma", "begin", "rollback")), sql)

    def test_draft_edit_and_confirmation_preview_never_approve_or_send(self):
        from jiejing_saas.support_application import SupportApplication
        self.service.ingest(self.incoming)
        app = SupportApplication(self.repo, enabled=True)
        with patch("socket.socket", side_effect=AssertionError("no network")), \
             patch.object(self.repo, "initialize", side_effect=AssertionError("no implicit migration")):
            draft = app.create_draft(self.context(), {"conversation_id": "conv-1", "source_message_id": "m1",
                "body": "The supplied photo shows blue. 💙", "fact_refs": ["merchant-photo-1"]})
            changed = app.edit_draft(self.context(), draft["draft_id"], {"expected_revision": 1,
                "body": "Please check the blue option in the supplied photo. 💙"})
            preview = app.preview_confirmation(self.context(), draft["draft_id"])
        self.assertEqual(changed["revision"], 2)
        self.assertEqual(preview["message_body"], changed["body"])
        self.assertEqual(preview["status"], "preview_only")
        self.assertFalse(preview["confirmation_created"])
        self.assertFalse(preview["approved"])
        self.assertFalse(preview["facts_verified"])
        self.assertFalse(preview["send_enabled"])
        self.assertNotIn("confirmation_id", preview)
        for key in ("support_binding", "support_binding_hash", "scope", "reply_to", "actor_id"):
            self.assertNotIn(key, preview)
            self.assertNotIn(key, draft)
        self.assertEqual(len(self.service.draft_history(draft["draft_id"])), 2)
        with self.repo._connect() as conn:
            self.assertEqual(conn.execute("select count(*) from confirmations").fetchone()[0], 0)
            self.assertEqual(conn.execute("select count(*) from support_send_intents_v1").fetchone()[0], 0)
        for method in ("execute", "send", "send_reply", "approve", "decide_confirmation"):
            self.assertFalse(hasattr(app, method), method)

    def test_only_explicit_enabled_sync_can_fetch_then_persist_a_scoped_snapshot(self):
        from jiejing_saas.support_application import SupportApplication
        payload = {"conversation_id": "conv-1", "limit": 25, "max_pages": 1}
        response = json.dumps({"conversationType": "FROM_MEMBERS", "messages": self.incoming["messages"]}).encode()
        with patch("jiejing_saas.ebay_message_adapter.message_http_transport", return_value=(200, {}, response)) as network:
            blocked = SupportApplication(self.repo, enabled=True, resolver=self.resolver()).sync(self.context(), payload)
            self.assertEqual(blocked["blocked_by"], ["support_sync_disabled"])
            network.assert_not_called()
            app = SupportApplication(self.repo, enabled=True, sync_enabled=True, resolver=self.resolver())
            result = app.sync(self.context(), payload)
        self.assertEqual(result["sync_status"], "ok")
        self.assertTrue(result["external_request_performed"])
        self.assertFalse(result["send_enabled"])
        self.assertEqual(network.call_count, 1)
        request = network.call_args.args[0]
        self.assertEqual(request.get_method(), "GET")
        self.assertIn("/conversation/conv-1?", request.full_url)
        self.assertEqual(app.get_conversation(self.context(), "conv-1")["messages"], result["messages"])
        public = json.dumps(result)
        for forbidden in ("synthetic-access-not-real", self.fixture.ref, self.scope.owner_id, "must-never-project"):
            self.assertNotIn(forbidden, public)

    def test_configured_sync_uses_server_factory_only_after_actor_and_schema_checks(self):
        from jiejing_saas.support_application import SupportApplication
        from jiejing_saas.config import SaaSSettings
        root = Path(self.fixture.temp.name)
        settings = SaaSSettings.from_env(db_path=self.repo.db_path, runtime_db_path=root / "unused.sqlite",
            output_root=root, host="127.0.0.1", port=0)
        response = json.dumps({"conversationType": "FROM_MEMBERS", "messages": self.incoming["messages"]}).encode()
        with patch("jiejing_saas.support_credential_adapters.build_support_resolver", return_value=self.resolver()) as factory, \
             patch("jiejing_saas.ebay_message_adapter.message_http_transport", return_value=(200, {}, response)) as network:
            app = SupportApplication(self.repo, enabled=True, sync_enabled=True, settings=settings)
            with self.assertRaises(PermissionError):
                app.sync(self.context(actor_id="foreign-user"), {"conversation_id": "conv-1"})
            factory.assert_not_called()
            network.assert_not_called()
            result = app.sync(self.context(), {"conversation_id": "conv-1"})
            self.assertEqual(result["sync_status"], "ok")
            self.assertEqual(factory.call_count, 1)
            self.assertEqual(factory.call_args.kwargs["company_id"], self.fixture.company)
            self.assertEqual(factory.call_args.kwargs["store_id"], self.fixture.store)
            self.assertFalse(result["send_enabled"])

    def test_cross_tenant_store_and_untrusted_context_are_rejected(self):
        from jiejing_saas.support_application import SupportApplication
        other = self.repo.create_user_with_company(email="other@example.test", password="synthetic-password",
            company_name="Other tenant")
        store = self.repo.create_store(company_id=other["company"]["company_id"],
            user_id=other["user"]["user_id"], payload={"platform": "ebay"})
        app = SupportApplication(self.repo, enabled=True)
        with self.assertRaisesRegex(PermissionError, "actor_not_authorized"):
            app.get_conversation(self.context(company_id=other["company"]["company_id"], store_id=store["store_id"]), "conv-1")
        with self.assertRaisesRegex(PermissionError, "store_not_accessible"):
            app.list_conversations(self.context(store_id=store["store_id"]))
        with self.assertRaisesRegex(PermissionError, "actor_context_required"):
            app.capability({"actor_id": self.fixture.user, "company_id": self.fixture.company, "store_id": self.fixture.store})

    def test_only_explicit_support_roles_can_read_or_mutate_cache(self):
        from jiejing_saas.support_application import SupportApplication
        app = SupportApplication(self.repo, enabled=True)
        self.service.ingest(self.incoming)
        for role in ("owner", "admin", "support", "operator", "media", "finance", "viewer"):
            self.fixture.sql("update team_members set role=? where company_id=? and user_id=?",
                (role, self.fixture.company, self.fixture.user))
            with self.subTest(role=role):
                if role in ("owner", "admin", "support"):
                    self.assertEqual(app.get_conversation(self.context(), "conv-1")["sync_status"], "ok")
                else:
                    with self.assertRaisesRegex(PermissionError, "actor_not_authorized"):
                        app.capability(self.context())
                    with self.assertRaisesRegex(PermissionError, "actor_not_authorized"):
                        app.create_draft(self.context(), {"conversation_id": "conv-1", "source_message_id": "m1", "body": "Blue"})

    def test_removed_or_inactive_actor_cannot_edit_or_preview_existing_draft(self):
        from jiejing_saas.support_application import SupportApplication
        app = SupportApplication(self.repo, enabled=True)
        self.service.ingest(self.incoming)
        draft = app.create_draft(self.context(), {"conversation_id": "conv-1", "source_message_id": "m1", "body": "Blue"})
        self.fixture.sql("update users set status='disabled' where user_id=?", (self.fixture.user,))
        with self.assertRaisesRegex(PermissionError, "actor_not_authorized"):
            app.edit_draft(self.context(), draft["draft_id"], {"expected_revision": 1, "body": "Changed"})
        self.fixture.sql("update users set status='active' where user_id=?", (self.fixture.user,))
        self.fixture.sql("delete from team_members where company_id=? and user_id=?", (self.fixture.company, self.fixture.user))
        with self.assertRaisesRegex(PermissionError, "actor_not_authorized"):
            app.preview_confirmation(self.context(), draft["draft_id"])
        self.assertEqual(self.service.get_draft(draft["draft_id"])["revision"], 1)

    def test_browser_identity_credential_and_send_fields_are_not_accepted(self):
        from jiejing_saas.support_application import SupportApplication
        app = SupportApplication(self.repo, enabled=True, sync_enabled=True, resolver=self.resolver())
        self.service.ingest(self.incoming)
        draft = app.create_draft(self.context(), {"conversation_id": "conv-1", "source_message_id": "m1", "body": "Blue"})
        for key in ("actor_id", "company_id", "store_id", "owner_id", "owner_username_hash", "owner_binding_kind",
                    "access_token", "secret_ref", "read_enabled", "send_enabled", "approve", "support_binding", "extra"):
            with self.subTest(key=key), patch("socket.socket", side_effect=AssertionError("no network")):
                with self.assertRaisesRegex(ValueError, "payload_not_allowed"):
                    app.sync(self.context(), {"conversation_id": "conv-1", key: "injected"})
                with self.assertRaisesRegex(ValueError, "payload_not_allowed"):
                    app.create_draft(self.context(), {"conversation_id": "conv-1", "source_message_id": "m1", "body": "Blue", key: "injected"})
                with self.assertRaisesRegex(ValueError, "payload_not_allowed"):
                    app.edit_draft(self.context(), draft["draft_id"], {"expected_revision": 1, "body": "Blue", key: "injected"})

    def test_missing_schema_or_unique_guard_blocks_without_repair(self):
        from jiejing_saas.support_application import SupportApplication
        app = SupportApplication(self.repo, enabled=True)
        self.fixture.sql("drop table support_send_intents_v1")
        self.assertEqual(app.capability(self.context())["blocked_by"], ["support_schema_not_ready"])
        self.assertEqual(app.list_conversations(self.context())["blocked_by"], ["support_schema_not_ready"])
        statement = SupportConversations.schema_statements()[3]
        statement = statement.replace(",\n                unique(company_id, store_id, owner_id, confirmation_id)", "")
        self.fixture.sql(statement)
        self.assertEqual(app.capability(self.context())["blocked_by"], ["support_schema_not_ready"])
        with self.repo._connect() as conn:
            unique = conn.execute("pragma index_list(support_send_intents_v1)").fetchall()
        self.assertEqual(len(unique), 2, "application must not restore the removed constraint")

    def test_failed_sync_clears_current_eligibility_but_keeps_historical_messages(self):
        from jiejing_saas.support_application import SupportApplication
        self.service.ingest(self.incoming)
        app = SupportApplication(self.repo, enabled=True, sync_enabled=True, resolver=self.resolver())
        with patch("jiejing_saas.ebay_message_adapter.message_http_transport", return_value=(503, {}, b"{}")):
            result = app.sync(self.context(), {"conversation_id": "conv-1"})
        self.assertEqual(result["sync_status"], "http_error")
        self.assertEqual(len(result["messages"]), 1)
        self.assertEqual(self.service.read_snapshot("conv-1")["current_message_ids"], [])
        with self.assertRaisesRegex(ValueError, "complete_current_snapshot_required"):
            app.create_draft(self.context(), {"conversation_id": "conv-1", "source_message_id": "m1", "body": "Blue"})

    def test_role_revoked_during_credential_verification_has_zero_message_http_and_no_cache_write(self):
        from jiejing_saas.support_application import SupportApplication
        def revoke():
            self.fixture.sql("update team_members set role='viewer' where company_id=? and user_id=?",
                (self.fixture.company, self.fixture.user))
        app = SupportApplication(self.repo, enabled=True, sync_enabled=True, resolver=self.resolver(revoke))
        with patch("jiejing_saas.ebay_message_adapter.message_http_transport") as network:
            with self.assertRaisesRegex(PermissionError, "actor_not_authorized"):
                app.sync(self.context(), {"conversation_id": "conv-1"})
        network.assert_not_called()
        self.assertEqual(self.service.read_snapshot("conv-1")["messages"], [])

    def test_late_response_after_role_revocation_is_not_persisted_or_returned(self):
        from jiejing_saas.support_application import SupportApplication
        def response(*_):
            self.fixture.sql("delete from team_members where company_id=? and user_id=?", (self.fixture.company, self.fixture.user))
            return 200, {}, json.dumps({"conversationType": "FROM_MEMBERS", "messages": self.incoming["messages"]}).encode()
        app = SupportApplication(self.repo, enabled=True, sync_enabled=True, resolver=self.resolver())
        with patch("jiejing_saas.ebay_message_adapter.message_http_transport", side_effect=response) as network:
            with self.assertRaisesRegex(PermissionError, "actor_not_authorized"):
                app.sync(self.context(), {"conversation_id": "conv-1"})
        self.assertEqual(network.call_count, 1)
        self.assertEqual(self.service.read_snapshot("conv-1")["messages"], [])

    def test_late_response_after_owner_binding_change_cannot_pollute_either_cache(self):
        from jiejing_saas.support_application import SupportApplication
        def response(*_):
            self.fixture.patch_metadata({"ebay_username_hash": hashlib.sha256(b"other-seller").hexdigest()})
            return 200, {}, json.dumps({"conversationType": "FROM_MEMBERS", "messages": self.incoming["messages"]}).encode()
        app = SupportApplication(self.repo, enabled=True, sync_enabled=True, resolver=self.resolver())
        with patch("jiejing_saas.ebay_message_adapter.message_http_transport", side_effect=response):
            result = app.sync(self.context(), {"conversation_id": "conv-1"})
        self.assertEqual(result["blocked_by"], ["support_context_changed"])
        self.assertEqual(self.service.read_snapshot("conv-1")["messages"], [])
        self.assertEqual(app.list_conversations(self.context())["conversations"], [])

    def test_concurrent_edits_preserve_one_current_revision_and_no_lost_update(self):
        from jiejing_saas.support_application import SupportApplication
        self.service.ingest(self.incoming)
        app = SupportApplication(self.repo, enabled=True)
        draft = app.create_draft(self.context(), {"conversation_id": "conv-1", "source_message_id": "m1", "body": "Blue"})
        def edit(body):
            try:
                return app.edit_draft(self.context(), draft["draft_id"], {"expected_revision": 1, "body": body})
            except ValueError as exc:
                return str(exc)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(edit, ["First revision", "Second revision"]))
        self.assertEqual(sum(isinstance(result, dict) for result in results), 1)
        self.assertIn("draft_revision_conflict", results)
        self.assertEqual(len(self.service.draft_history(draft["draft_id"])), 2)

    def test_postgres_defaults_closed_and_connection_failure_does_not_migrate(self):
        from jiejing_saas.support_application import SupportApplication
        app = SupportApplication(self.repo, enabled=True)
        with patch.object(self.repo, "database_engine", "postgres"), \
             patch.object(self.repo, "initialize", side_effect=AssertionError("no migration")), \
             patch.object(self.repo, "_connect", side_effect=RuntimeError("synthetic connection unavailable")) as connect:
            self.assertEqual(SupportApplication(self.repo).capability(self.context())["blocked_by"], ["support_application_disabled"])
            connect.assert_not_called()
            result = app.capability(self.context())
            connect.assert_called_once_with()
        self.assertEqual(result["blocked_by"], ["support_database_unavailable"])
        self.assertFalse(result["schema_write_performed"])

    def test_missing_actor_uniqueness_constraint_blocks_ambiguous_role_lookup(self):
        from jiejing_saas.support_application import SupportApplication
        self.fixture.sql("alter table team_members rename to team_members_original")
        self.fixture.sql("create table team_members(company_id text,user_id text,role text,created_at text)")
        self.fixture.sql("insert into team_members select * from team_members_original")
        result = SupportApplication(self.repo, enabled=True).capability(self.context())
        self.assertEqual(result["blocked_by"], ["support_schema_not_ready"])

    def test_all_default_off_actions_and_enabled_missing_db_remain_non_mutating(self):
        from jiejing_saas.repository import SaaSRepository
        from jiejing_saas.support_application import SupportApplication
        app = SupportApplication(self.repo, enabled="true", sync_enabled=True, resolver=self.resolver())
        actions = [lambda: app.list_conversations(self.context()),
            lambda: app.get_conversation(self.context(), "conv-1"),
            lambda: app.sync(self.context(), {"conversation_id": "conv-1"}),
            lambda: app.create_draft(self.context(), {"conversation_id": "conv-1", "source_message_id": "m1", "body": "Blue"}),
            lambda: app.edit_draft(self.context(), "draft-1", {"expected_revision": 1, "body": "Blue"}),
            lambda: app.preview_confirmation(self.context(), "draft-1")]
        with patch("socket.socket", side_effect=AssertionError("no network")):
            for action in actions:
                self.assertEqual(action()["blocked_by"], ["support_application_disabled"])
        path = Path(self.fixture.temp.name) / "not-created.sqlite"
        empty = SaaSRepository(path, database_engine="sqlite", database_url="")
        self.assertEqual(SupportApplication(empty, enabled=True).capability(self.context())["blocked_by"], ["support_schema_not_ready"])
        self.assertFalse(path.exists())

    def test_invalid_text_pagination_and_revision_are_rejected_before_provider_calls(self):
        from jiejing_saas.support_application import SupportApplication
        app = SupportApplication(self.repo, enabled=True, sync_enabled=True, resolver=self.resolver())
        with patch("socket.socket", side_effect=AssertionError("no network")):
            for values in ({"limit": True}, {"limit": 51}, {"max_pages": 4}, {"conversation_id": "../other"}):
                with self.subTest(values=values), self.assertRaises(ValueError):
                    app.sync(self.context(), {"conversation_id": "conv-1", **values})
            for body in ("bad-\ud800", "x" * 2001, "", None, {"text": "Blue"}):
                with self.subTest(body=repr(body)), self.assertRaisesRegex(ValueError, "text_invalid"):
                    app.create_draft(self.context(), {"conversation_id": "conv-1", "source_message_id": "m1", "body": body})
            for revision in (True, 0, "1"):
                with self.subTest(revision=revision), self.assertRaisesRegex(ValueError, "revision_conflict"):
                    app.edit_draft(self.context(), "draft-1", {"expected_revision": revision, "body": "Blue"})

    def test_revoked_connection_blocks_cached_access_and_preserves_history(self):
        from jiejing_saas.support_application import SupportApplication
        self.service.ingest(self.incoming)
        self.fixture.sql("update platform_connections set status='revoked' where connection_id=?", (self.fixture.connection_id,))
        result = SupportApplication(self.repo, enabled=True).get_conversation(self.context(), "conv-1")
        self.assertEqual(result["blocked_by"], ["support_connection_unavailable"])
        self.assertNotIn("messages", result)
        self.assertEqual(len(self.service.read_snapshot("conv-1")["messages"]), 1)

    def test_unverified_scope_is_not_reported_as_live_access_and_get_does_not_resolve(self):
        from jiejing_saas.support_application import SupportApplication
        self.fixture.patch_metadata({"actual_granted_scope_verified": False, "granted_scope_verification_source": ""})
        resolver = self.resolver(lambda: self.fail("GET must not refresh"))
        app = SupportApplication(self.repo, enabled=True, sync_enabled=True, resolver=resolver)
        capability = app.capability(self.context())
        self.assertEqual(capability["status"], "local_cache_available")
        self.assertFalse(capability["credentials_verified"])
        self.assertTrue(capability["requires_live_owner_check"])
        self.assertEqual(app.list_conversations(self.context())["conversations"], [])

    def _assert_late_sync_cannot_replace_current(self, newer_failure=False):
        from jiejing_saas.support_application import SupportApplication
        app = SupportApplication(self.repo, enabled=True, sync_enabled=True, resolver=self.resolver())
        entered, release = threading.Event(), threading.Event()
        lock, calls = threading.Lock(), []
        newer_messages = [*self.incoming["messages"], {**self.incoming["messages"][0],
            "messageId": "m2", "messageBody": "Actually red please.", "createdDate": "2026-10-12T00:01:00Z"}]
        def response(*_):
            with lock:
                calls.append(1)
                number = len(calls)
            if number == 1:
                entered.set()
                if not release.wait(15):
                    raise TimeoutError("synthetic barrier expired")
                messages = self.incoming["messages"]
            elif newer_failure:
                return 503, {}, b"{}"
            else:
                messages = newer_messages
            return 200, {}, json.dumps({"conversationType": "FROM_MEMBERS", "messages": messages}).encode()
        with patch("jiejing_saas.ebay_message_adapter.message_http_transport", side_effect=response), \
             ThreadPoolExecutor(max_workers=2) as pool:
            old = pool.submit(app.sync, self.context(), {"conversation_id": "conv-1"})
            try:
                self.assertTrue(entered.wait(10))
                newer = pool.submit(app.sync, self.context(), {"conversation_id": "conv-1"}).result(timeout=15)
                expected = self.service.read_snapshot("conv-1")
            finally:
                release.set()
            older = old.result(timeout=15)
        self.assertEqual(older["blocked_by"], ["support_sync_superseded"])
        self.assertNotIn("messages", older)
        self.assertEqual(self.service.read_snapshot("conv-1"), expected)
        self.assertEqual(expected["current_message_ids"], [] if newer_failure else ["m1", "m2"])
        self.assertEqual(newer["sync_status"], "http_error" if newer_failure else "ok")

    def test_late_old_sync_cannot_replace_newer_messages(self):
        self._assert_late_sync_cannot_replace_current()

    def test_late_old_success_cannot_reenable_after_newer_failure(self):
        self._assert_late_sync_cannot_replace_current(newer_failure=True)

    def test_sync_reservation_invalidates_old_reply_and_only_completes_once(self):
        self.service.ingest(self.incoming)
        previous = self.service.read_snapshot("conv-1")
        generation = self.service.begin_sync("conv-1")
        pending = self.service.read_snapshot("conv-1")
        self.assertEqual(pending["messages"], previous["messages"])
        self.assertEqual(pending["last_success_at"], previous["last_success_at"])
        self.assertEqual(pending["current_message_ids"], [])
        self.assertEqual(pending["sync_status"], "syncing")
        self.assertTrue(self.service.sync_attempt_is_current("conv-1", generation))
        self.service.ingest(self.incoming, expected_generation=generation)
        self.assertFalse(self.service.sync_attempt_is_current("conv-1", generation))
        with self.assertRaisesRegex(ValueError, "support_sync_superseded"):
            self.service.ingest(self.incoming, expected_generation=generation)

    def test_direct_ingest_invalidates_pending_async_attempt(self):
        first = self.service.begin_sync("conv-1")
        self.service.ingest({**self.incoming, "status": "http_error", "messages": None})
        with self.assertRaisesRegex(ValueError, "support_sync_superseded"):
            self.service.ingest(self.incoming, expected_generation=first)
        self.assertEqual(self.service.read_snapshot("conv-1")["sync_status"], "http_error")
        self.assertEqual(self.service.read_snapshot("conv-1")["current_message_ids"], [])

    def test_old_sync_schema_is_blocked_and_not_upgraded_by_get(self):
        from jiejing_saas.support_application import SupportApplication
        self.fixture.sql("alter table support_sync_v1 drop column sync_generation")
        result = SupportApplication(self.repo, enabled=True).capability(self.context())
        self.assertEqual(result["blocked_by"], ["support_schema_not_ready"])
        with self.repo._connect() as connection:
            self.assertNotIn("sync_generation", [row["name"] for row in connection.execute("pragma table_info(support_sync_v1)")])

    def test_credential_failure_does_not_falsely_claim_zero_external_io(self):
        from jiejing_saas.support_application import SupportApplication
        def failure():
            raise RuntimeError("synthetic backend failure; do not expose")
        self.service.ingest(self.incoming)
        app = SupportApplication(self.repo, enabled=True, sync_enabled=True, resolver=self.resolver(failure))
        with patch("jiejing_saas.ebay_message_adapter.message_http_transport") as message_http:
            result = app.sync(self.context(), {"conversation_id": "conv-1"})
        message_http.assert_not_called()
        self.assertIsNone(result["external_request_performed"], "credential provider I/O is not observable here")
        self.assertFalse(result["buyer_message_http_attempted"])
        self.assertTrue(result["credential_verification_attempted"])
        self.assertEqual(result["sync_status"], "credential_verification_failed")
        self.assertEqual(self.service.read_snapshot("conv-1")["current_message_ids"], [])
        self.assertNotIn("synthetic backend failure", json.dumps(result))


if __name__ == "__main__":
    unittest.main()
