"""Synthetic in-process HTTP server on 127.0.0.1:0; no production or provider I/O."""
from __future__ import annotations

import http.client
import hashlib
import json
import os
import socket
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
import test_jiejing_support_connection_boundary as boundary_fixture
from jiejing_saas.api_server import SaaSBackendHandler, JiejingSafeThreadingHTTPServer
from jiejing_saas.config import SaaSSettings
from jiejing_saas.security import SessionManager
from jiejing_saas.support_application import SupportApplication
from jiejing_saas.support_conversations import SupportConversations
from jiejing_saas.ebay_message_adapter import MessageScope


class SupportHttpTests(unittest.TestCase):
    def setUp(self):
        environment = patch.dict(os.environ, {"JIEJING_SAAS_ENV": "test", "JIEJING_SAFE_ACCESS_LOG_ENABLED": "false"}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)
        connect = socket.socket.connect
        def loopback_only(sock, address):
            if type(address) is not tuple or address[0] != "127.0.0.1":
                raise AssertionError("fixture permits only explicit IPv4 loopback")
            return connect(sock, address)
        network = patch.object(socket.socket, "connect", loopback_only)
        network.start()
        self.addCleanup(network.stop)
        self.fixture = boundary_fixture.SupportConnectionBoundaryTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.repo = self.fixture.repo
        root = Path(self.fixture.temp.name)
        settings = SaaSSettings.from_env(db_path=self.repo.db_path, runtime_db_path=root / "runtime.sqlite",
            output_root=root / "output", host="127.0.0.1", port=0)
        sessions = SessionManager(secret="synthetic-support-http-only", ttl_seconds=600)
        self.token = sessions.create_token(user_id=self.fixture.user, company_id=self.fixture.company,
            email="boundary@example.test")
        self.repo.ensure_user_session(sessions.verify_token(self.token))
        repo = self.repo
        application = SupportApplication(repo)
        class Handler(SaaSBackendHandler):
            repository = repo
            support_application = application
        Handler.settings, Handler.sessions = settings, sessions
        self.handler = Handler
        self.server = JiejingSafeThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)
        self.path = f"/stores/{self.fixture.store}/support"

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def enable_cache(self):
        self.fixture.fixture()
        self.scope = MessageScope(self.fixture.company, self.fixture.store,
            hashlib.sha256(b"synthetic-seller").hexdigest(), "sha256_casefold_ebay_username")
        self.service = SupportConversations(self.repo, self.scope)
        self.service.initialize_local_schema()
        self.service.ingest({"status": "ok", "scope": self.scope.as_dict(), "conversation_id": "conv-1",
            "truncated": False, "messages": [{"messageId": "m1", "messageBody": "Is it blue? 💙",
                "senderUsername": "synthetic-buyer", "recipientUsername": "synthetic-seller",
                "createdDate": "2026-10-12T00:00:00Z"}]})
        self.handler.settings.support_cache_workspace_enabled = True
        self.handler.support_application = SupportApplication(self.repo, enabled=True)

    def request(self, suffix="/capability", *, method="GET", body=None, token=True, headers=None, path=None):
        request_headers = {"Accept": "application/json", **(headers or {})}
        if token:
            request_headers["Authorization"] = "Bearer " + (self.token if token is True else token)
        data = None if body is None else json.dumps(body).encode("utf-8")
        if data is not None:
            request_headers.setdefault("Content-Type", "application/json")
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_address[1], timeout=10)
        try:
            conn.request(method, path or self.path + suffix, body=data, headers=request_headers)
            response = conn.getresponse()
            return response.status, json.loads(response.read().decode("utf-8"))
        finally:
            conn.close()

    def test_real_http_requires_auth_and_defaults_closed(self):
        status, _ = self.request(token=False)
        self.assertEqual(status, 401)
        status, payload = self.request()
        self.assertEqual(status, 200)
        self.assertEqual(payload["support"]["blocked_by"], ["support_application_disabled"])
        self.assertFalse(payload["support"]["send_enabled"])
        self.assertFalse(self.handler.settings.support_cache_workspace_enabled)

    def test_http_cache_to_manual_draft_edit_and_preview_without_confirmation_or_send(self):
        self.enable_cache()
        self.assertEqual(self.request()[1]["support"]["status"], "local_cache_available")
        listing = self.request("/conversations")[1]["support"]
        self.assertEqual(listing["conversations"][0]["conversation_id"], "conv-1")
        detail = self.request("/conversations/conv-1")[1]["support"]
        self.assertEqual(detail["messages"][0]["body"], "Is it blue? 💙")
        status, created = self.request("/drafts", method="POST", body={"conversation_id": "conv-1",
            "source_message_id": "m1", "body": "The supplied photo shows blue. 💙", "fact_refs": ["merchant-photo-1"]})
        self.assertEqual(status, 201)
        draft_id = created["support"]["draft_id"]
        status, changed = self.request(f"/drafts/{draft_id}/edit", method="POST",
            body={"expected_revision": 1, "body": "Please check the supplied photo. 💙"})
        self.assertEqual(status, 200)
        self.assertEqual(changed["support"]["revision"], 2)
        status, preview = self.request(f"/drafts/{draft_id}/confirmation-preview", method="POST", body={})
        self.assertEqual(status, 200)
        self.assertEqual(preview["support"]["message_body"], changed["support"]["body"])
        self.assertFalse(preview["support"]["confirmation_created"])
        self.assertFalse(preview["support"]["approved"])
        self.assertFalse(preview["support"]["send_enabled"])
        self.assertNotIn("confirmation_id", preview["support"])
        for forbidden in (self.scope.owner_id, self.fixture.ref, "synthetic-buyer", "synthetic-seller", "support_binding"):
            self.assertNotIn(forbidden, json.dumps([listing, detail, created, changed, preview]))
        with self.repo._connect() as conn:
            self.assertEqual(conn.execute("select count(*) from confirmations").fetchone()[0], 0)
            self.assertEqual(conn.execute("select count(*) from support_send_intents_v1").fetchone()[0], 0)

    def test_http_discovery_is_explicit_default_closed_and_projects_ids_only(self):
        self.enable_cache()
        status, payload = self.request("/discover", method="POST", body={})
        self.assertEqual(status, 409)
        self.assertEqual(payload["support"]["blocked_by"], ["support_sync_disabled"])
        from tools.test_jiejing_support_application import SupportApplicationTests
        resolver = SupportApplicationTests.resolver(self)
        self.handler.support_application = SupportApplication(self.repo, enabled=True, sync_enabled=True, resolver=resolver)
        response = json.dumps({"conversations": [{"conversationId": "new-conversation",
            "conversationType": "FROM_MEMBERS", "latestMessage": {"senderUsername": "synthetic-private-buyer"}}],
            "next": "https://outside.invalid/not-followed"}).encode()
        with patch("jiejing_saas.ebay_message_adapter.message_http_transport", return_value=(200, {}, response)) as network:
            status, payload = self.request("/discover", method="POST", body={"offset": 25})
        self.assertEqual(status, 200)
        self.assertEqual(payload["support"]["conversation_ids"], ["new-conversation"])
        self.assertEqual(payload["support"]["next_offset"], 50)
        self.assertEqual(network.call_count, 1)
        for forbidden in ("synthetic-private-buyer", "latestMessage", self.scope.owner_id, self.fixture.ref):
            self.assertNotIn(forbidden, json.dumps(payload))

    def test_http_discovery_rejects_query_forged_scope_and_unsafe_origin(self):
        self.enable_cache()
        self.handler.settings.environment = "production"
        self.handler.settings.cors_origin = "https://trusted.example.test"
        with patch("jiejing_saas.ebay_message_adapter.message_http_transport", side_effect=AssertionError("no I/O")):
            self.assertEqual(self.request("/discover?offset=0", method="POST", body={})[0], 400)
            self.assertEqual(self.request("/discover", method="POST", body={"store_id": "other"})[0], 400)
            self.assertEqual(self.request("/discover", method="POST", body={},
                                          headers={"Origin": "https://outside.invalid"})[0], 403)
            self.assertEqual(self.request("/discover", method="POST", body={}, token=False)[0], 401)

    def test_accumulated_history_over_1000_is_readable_in_explicit_pages(self):
        self.enable_cache()
        messages = [{"messageId": f"history-{index:04d}", "messageBody": f"Message {index} 💙",
            "senderUsername": "synthetic-buyer", "recipientUsername": "synthetic-seller",
            "createdDate": "2026-10-12T01:00:00Z"} for index in range(1001)]
        incoming = {"status": "ok", "scope": self.scope.as_dict(), "conversation_id": "history-Fal",
            "truncated": False, "messages": messages[:1000]}
        self.service.ingest(incoming)
        self.service.ingest({**incoming, "messages": messages[1000:]})
        before = self.service.read_snapshot("history-Fal")
        self.assertEqual(len(before["messages"]), 1001)
        status, initial = self.request("/conversations/history-Fal")
        self.assertEqual(status, 200)
        first = initial["support"]
        self.assertEqual(len(first["messages"]), 50)
        self.assertEqual((first["message_offset"], first["message_limit"], first["next_offset"]), (0, 50, 50))
        self.assertTrue(first["has_more"])
        self.assertFalse(first["truncated"], "upstream truncation is not cache pagination")
        seen = []
        offset = 0
        for _ in range(11):
            status, payload = self.request(f"/conversations/history-Fal?limit=100&offset={offset}")
            self.assertEqual(status, 200)
            page = payload["support"]
            self.assertEqual(page["message_offset"], offset)
            self.assertLessEqual(len(page["messages"]), 100)
            seen.extend(item["message_id"] for item in page["messages"])
            self.assertFalse(page["external_request_performed"])
            self.assertFalse(page["send_enabled"])
            if not page["has_more"]:
                self.assertIsNone(page["next_offset"])
                break
            offset = page["next_offset"]
        self.assertEqual(seen, [item["messageId"] for item in messages])
        self.assertEqual(self.service.read_snapshot("history-Fal"), before)
        empty = self.request("/conversations/history-Fal?limit=100&offset=1001")[1]["support"]
        self.assertEqual(empty["messages"], [])
        self.assertFalse(empty["has_more"])
        self.assertIsNone(empty["next_offset"])
        with self.repo._connect() as conn:
            self.assertEqual(conn.execute("select count(*) from confirmations").fetchone()[0], 0)
            self.assertEqual(conn.execute("select count(*) from support_send_intents_v1").fetchone()[0], 0)

    def test_detail_pagination_is_strict_and_does_not_widen_identity_or_scope(self):
        self.enable_cache()
        for query in ("limit=0", "limit=101", "offset=-1", "offset=2147483648", "offset=1.5",
                      "limit=true", "limit=10&limit=20", "offset=1&offset=2", "company_id=other",
                      "send_enabled=true", "limit=10&owner_id=other"):
            with self.subTest(query=query):
                self.assertEqual(self.request("/conversations/conv-1?" + query)[0], 400)
        self.assertEqual(self.request("/conversations/conv-1?limit=1&offset=0", token=False)[0], 401)
        self.assertEqual(self.request("/conversations/conv-1?limit=1&offset=0")[0], 200)
        self.fixture.sql("update team_members set role='viewer' where company_id=? and user_id=?",
            (self.fixture.company, self.fixture.user))
        status, payload = self.request("/conversations/conv-1?limit=1&offset=0")
        self.assertEqual(status, 403)
        self.assertNotIn("messages", json.dumps(payload))

    def test_stale_edit_has_conflict_status_and_keeps_current_body(self):
        self.enable_cache()
        _, created = self.request("/drafts", method="POST", body={"conversation_id": "conv-1",
            "source_message_id": "m1", "body": "Blue"})
        draft_id = created["support"]["draft_id"]
        self.request(f"/drafts/{draft_id}/edit", method="POST", body={"expected_revision": 1, "body": "Current"})
        status, payload = self.request(f"/drafts/{draft_id}/edit", method="POST", body={"expected_revision": 1, "body": "Stale"})
        self.assertEqual(status, 409)
        self.assertEqual(payload["error"], "support state conflict; refresh before retrying")
        self.assertEqual(self.service.get_draft(draft_id)["body"], "Current")

    def test_signed_identity_not_request_body_controls_tenant_and_actor(self):
        self.enable_cache()
        other = self.repo.create_user_with_company(email="other-http@example.test", password="synthetic-password",
            company_name="Other HTTP tenant")
        other_token = self.handler.sessions.create_token(user_id=other["user"]["user_id"],
            company_id=other["company"]["company_id"], email="other-http@example.test")
        self.repo.ensure_user_session(self.handler.sessions.verify_token(other_token))
        status, payload = self.request("/conversations/conv-1", token=other_token)
        self.assertEqual(status, 403)
        self.assertNotIn("messages", json.dumps(payload))
        for key in ("company_id", "actor_id", "user_id", "store_id", "owner_id", "owner_username_hash",
                    "secret_ref", "token", "access_token", "resolver", "send_enabled", "read_enabled", "enabled"):
            with self.subTest(key=key):
                status, result = self.request("/drafts", method="POST", body={"conversation_id": "conv-1",
                    "source_message_id": "m1", "body": "Blue", key: "must-not-echo"})
                self.assertEqual(status, 400)
                self.assertNotIn("must-not-echo", json.dumps(result))
        self.assertEqual(self.service.draft_history("not-created"), [])

    def test_same_company_other_store_cannot_edit_or_preview_first_store_draft(self):
        self.enable_cache()
        _, created = self.request("/drafts", method="POST", body={"conversation_id": "conv-1", "source_message_id": "m1", "body": "Blue"})
        draft_id = created["support"]["draft_id"]
        other_store = self.repo.create_store(company_id=self.fixture.company, user_id=self.fixture.user,
            payload={"platform": "ebay", "store_name": "Second synthetic store"})["store_id"]
        secondary = boundary_fixture.SupportConnectionBoundaryTests()
        secondary.repo, secondary.company, secondary.user, secondary.store = self.repo, self.fixture.company, self.fixture.user, other_store
        # The shared fixture uses a fixed nonce. Preserve uniqueness for the
        # second synthetic callback without changing any production validation.
        self.fixture.sql("update oauth_authorization_requests set state_nonce=? where oauth_request_id=?",
            ("synthetic-state-first-store", self.fixture.request_id))
        secondary.fixture()
        for action, body in (("edit", {"expected_revision": 1, "body": "Wrong store"}), ("confirmation-preview", {})):
            status, payload = self.request(method="POST", body=body,
                path=f"/stores/{other_store}/support/drafts/{draft_id}/{action}")
            self.assertEqual(status, 404)
            self.assertNotIn("Blue", json.dumps(payload))
        self.assertEqual(self.service.get_draft(draft_id)["body"], "Blue")

    def test_role_revocation_applies_to_existing_http_session(self):
        self.enable_cache()
        self.assertEqual(self.request("/conversations")[0], 200)
        self.fixture.sql("update team_members set role='viewer' where company_id=? and user_id=?",
            (self.fixture.company, self.fixture.user))
        self.assertEqual(self.request("/conversations")[0], 403)
        self.assertEqual(self.request("/drafts", method="POST", body={"conversation_id": "conv-1",
            "source_message_id": "m1", "body": "Must not save"})[0], 403)

    def test_mutations_reuse_origin_restrictions_and_require_json(self):
        self.enable_cache()
        self.handler.settings.environment = "production"
        self.handler.settings.cors_origin = "https://trusted.example.test"
        body = {"conversation_id": "conv-1", "source_message_id": "m1", "body": "Blue"}
        self.assertEqual(self.request("/drafts", method="POST", body=body,
            headers={"Origin": "https://untrusted.example.test"})[0], 403)
        self.assertEqual(self.request("/drafts", method="POST", body=body,
            headers={"Origin": "http://trusted.example.test"})[0], 403)
        self.assertEqual(self.request("/drafts", method="POST", body=body,
            headers={"Origin": "https://trusted.example.test", "Content-Type": "text/plain"})[0], 415)
        self.assertEqual(self.request("/drafts", method="POST", body=body,
            headers={"Origin": "https://trusted.example.test"})[0], 201)

    def test_sync_stays_blocked_even_with_cache_flag_and_live_ebay_flags(self):
        self.enable_cache()
        self.handler.settings.ebay_read_only_live_enabled = True
        self.handler.settings.ebay_write_live_enabled = True
        status, payload = self.request("/sync", method="POST", body={"conversation_id": "conv-1"})
        self.assertEqual(status, 409)
        self.assertEqual(payload["support"]["blocked_by"], ["support_sync_disabled"])
        self.assertFalse(payload["support"]["send_enabled"])
        for action in ("approve", "send", "execute"):
            self.assertEqual(self.request(f"/drafts/draft-1/{action}", method="POST", body={})[0], 404)

    def test_query_cannot_enable_features_or_select_other_identity(self):
        for suffix in ("/capability?enabled=true", "/capability?company_id=other", "/capability?token=",
                       "/conversations?limit=1&limit=2", "/conversations?offset=", "/conversations?send_enabled=true"):
            with self.subTest(suffix=suffix):
                self.assertEqual(self.request(suffix)[0], 400)
        self.assertFalse(self.handler.settings.support_cache_workspace_enabled)
        self.assertEqual(self.request()[1]["support"]["blocked_by"], ["support_application_disabled"])
        self.assertEqual(self.request("/sync?enabled=true", method="POST", body={"conversation_id": "conv-1"})[0], 400)

    def test_json_shape_size_and_preview_unknown_fields_are_rejected(self):
        self.enable_cache()
        self.assertEqual(self.request("/drafts", method="POST", body=[])[0], 400)
        with patch("jiejing_saas.api_server.MAX_JSON_BODY_BYTES", 256):
            self.assertEqual(self.request("/drafts", method="POST", body={"body": "x" * 257})[0], 413)
        self.assertEqual(self.request("/drafts/not-created/confirmation-preview", method="POST", body={"approve": True})[0], 400)

    def test_unknown_backend_exception_is_sanitized_over_http(self):
        self.enable_cache()
        with patch.object(self.handler.support_application, "get_conversation",
            side_effect=RuntimeError("do-not-expose-token-or-private-raw-message")):
            status, payload = self.request("/conversations/conv-1")
        self.assertEqual(status, 503)
        self.assertEqual(payload["error"], "support workspace unavailable")
        self.assertNotIn("do-not-expose", json.dumps(payload))

    def test_literal_buyer_and_draft_text_round_trip_matches_confirmation_body_hash(self):
        self.enable_cache()
        incoming = "Is this Fal or fal.ai? 蓝色 💙 media.fal_asset_generation"
        self.service.ingest({"status": "ok", "scope": self.scope.as_dict(), "conversation_id": "conv-Fal",
            "truncated": False, "messages": [{"messageId": "m-Fal", "messageBody": incoming,
                "senderUsername": "synthetic-buyer", "recipientUsername": "synthetic-seller",
                "createdDate": "2026-10-12T01:00:00Z"}]})
        status, detail = self.request("/conversations/conv-Fal")
        self.assertEqual(status, 200)
        self.assertEqual(detail["support"]["conversation_id"], "conv-Fal")
        self.assertEqual(detail["support"]["messages"][0]["message_id"], "m-Fal")
        self.assertEqual(detail["support"]["messages"][0]["body"], incoming)
        body = "Please return the item to Fal; ask about fal.ai first. 💙"
        refs = ["Fal photo", "fal.ai comparison"]
        status, created = self.request("/drafts", method="POST", body={"conversation_id": "conv-Fal",
            "source_message_id": "m-Fal", "body": body, "fact_refs": refs})
        self.assertEqual(status, 201)
        self.assertEqual(created["support"]["body"], body)
        self.assertEqual(created["support"]["fact_refs"], refs)
        draft_id = created["support"]["draft_id"]
        revised = body + "\nConfirm the Fal label before returning."
        status, edited = self.request(f"/drafts/{draft_id}/edit", method="POST",
            body={"expected_revision": 1, "body": revised})
        self.assertEqual(status, 200)
        self.assertEqual(edited["support"]["body"], revised)
        status, preview = self.request(f"/drafts/{draft_id}/confirmation-preview", method="POST", body={})
        self.assertEqual(status, 200)
        self.assertEqual(preview["support"]["message_body"], revised)
        canonical = self.service.prepare_confirmation(draft_id)
        projected_hash = hashlib.sha256(json.dumps(preview["support"]["message_body"],
            ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        self.assertEqual(projected_hash, canonical["support_binding"]["body_hash"])
        self.assertFalse(preview["support"]["confirmation_created"])
        self.assertFalse(preview["support"]["send_enabled"])

    def test_support_projection_drops_unknown_metadata_and_nested_secrets(self):
        self.enable_cache()
        original = self.handler.support_application.get_conversation
        def injected(context, conversation_id, **page):
            result = original(context, conversation_id, **page)
            result.update(provider="private-fal-provider", access_token="synthetic-top-token",
                owner_username_hash="private-owner-hash", extra={"password": "nested-password"})
            result["messages"][0].update(token="synthetic-message-token", provider="private-message-provider",
                extra={"secret_ref": "private-ref"}, reply_to="private-username")
            return result
        with patch.object(self.handler.support_application, "get_conversation", side_effect=injected):
            status, payload = self.request("/conversations/conv-1")
        self.assertEqual(status, 200)
        self.assertEqual(payload["support"]["messages"][0]["body"], "Is it blue? 💙")
        encoded = json.dumps(payload)
        for marker in ("synthetic-top-token", "private-fal-provider", "private-owner-hash", "nested-password",
                       "synthetic-message-token", "private-message-provider", "private-ref", "private-username"):
            self.assertNotIn(marker, encoded)
        self.assertEqual(set(payload["support"]["messages"][0]), {"message_id", "body", "created_at", "direction"})

    def test_secret_like_admitted_text_fails_closed_instead_of_rewriting_preview(self):
        self.enable_cache()
        original = self.handler.support_application.get_conversation
        for secret_text in ("Bearer abcdefghijklmnop", "access_token=synthetic-sensitive-value",
                            "sk-synthetickey0123456789", "api_key=synthetic-provider-key"):
            injected_bodies = []
            def injected(context, conversation_id, **page):
                result = original(context, conversation_id, **page)
                result["messages"][0]["body"] = secret_text
                injected_bodies.append(secret_text)
                return result
            with self.subTest(secret_text=secret_text), patch.object(
                    self.handler.support_application, "get_conversation", side_effect=injected):
                status, payload = self.request("/conversations/conv-1")
            self.assertEqual(status, 503)
            self.assertEqual(injected_bodies, [secret_text], "projection must reject the actual body, not a mock signature error")
            self.assertEqual(payload["error"], "support workspace unavailable")
            self.assertNotIn(secret_text, json.dumps(payload))

    def test_preview_projection_never_admits_metadata_objects_or_send_enablement(self):
        self.enable_cache()
        _, created = self.request("/drafts", method="POST", body={"conversation_id": "conv-1",
            "source_message_id": "m1", "body": "Ask Fal about fal.ai. 💙"})
        draft_id = created["support"]["draft_id"]
        original = self.handler.support_application.preview_confirmation
        def extra_metadata(context, selected):
            result = original(context, selected)
            result.update(provider="private-provider", access_token="private-preview-token",
                support_binding={"owner_id": "private-owner", "secret_ref": "private-ref"})
            return result
        with patch.object(self.handler.support_application, "preview_confirmation", side_effect=extra_metadata):
            status, payload = self.request(f"/drafts/{draft_id}/confirmation-preview", method="POST", body={})
        self.assertEqual(status, 200)
        self.assertEqual(payload["support"]["message_body"], "Ask Fal about fal.ai. 💙")
        self.assertNotIn("private-", json.dumps(payload))
        for field, bad_value in (("message_body", {"token": "private-object-token"}),
                                 ("message_body", "Bearer abcdefghijklmnop"), ("send_enabled", True)):
            def malformed(context, selected):
                result = original(context, selected)
                result[field] = bad_value
                return result
            with self.subTest(field=field, value=bad_value), patch.object(
                    self.handler.support_application, "preview_confirmation", side_effect=malformed):
                status, payload = self.request(f"/drafts/{draft_id}/confirmation-preview", method="POST", body={})
            self.assertEqual(status, 503)
            self.assertNotIn("private-", json.dumps(payload))
            self.assertNotIn("abcdefghijklmnop", json.dumps(payload))

    def test_general_provider_mapping_and_secret_filter_are_not_weakened(self):
        from jiejing_saas.api_server import _merchant_safe_replaceable_media_provider, _redact_secret_like
        projected = _merchant_safe_replaceable_media_provider({"media_provider": "fal", "note": "Fal and fal.ai"})
        self.assertEqual(projected, {"media_provider": "jiejing_media_router", "note": "jiejing_media_router and jiejing_media_router"})
        secret = _redact_secret_like({"access_token": "synthetic-token", "note": "Bearer abcdefghijklmnop"})
        self.assertNotIn("synthetic-token", json.dumps(secret))
        self.assertNotIn("abcdefghijklmnop", json.dumps(secret))

    def test_missing_support_schema_get_does_not_install_support_tables(self):
        self.handler.settings.support_cache_workspace_enabled = True
        self.handler.support_application = SupportApplication(self.repo, enabled=True)
        status, payload = self.request()
        self.assertEqual(status, 200)
        self.assertEqual(payload["support"]["blocked_by"], ["support_schema_not_ready"])
        with self.repo._connect() as conn:
            tables = conn.execute("select name from sqlite_master where type='table' and name like 'support_%'").fetchall()
        self.assertEqual(tables, [])

    def test_configuration_flag_is_independent_and_false_without_explicit_setting(self):
        root = Path(self.fixture.temp.name)
        with patch.dict(os.environ, {"JIEJING_SUPPORT_CACHE_WORKSPACE_ENABLED": "true"}, clear=True):
            settings = SaaSSettings.from_env(db_path=self.repo.db_path, runtime_db_path=root / "runtime.sqlite",
                output_root=root / "output", host="127.0.0.1", port=0)
        self.assertTrue(settings.support_cache_workspace_enabled)
        self.assertTrue(settings.public_dict()["support_cache_workspace_enabled"])
        self.assertFalse(settings.ebay_read_only_live_enabled)
        self.assertFalse(settings.ebay_write_live_enabled)
        self.assertFalse(settings.effective_real_platform_writes_enabled)


if __name__ == "__main__":
    unittest.main()
