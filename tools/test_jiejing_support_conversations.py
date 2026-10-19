"""Isolated local DB tests. All people, messages, tokens and send receipts synthetic."""
from __future__ import annotations

import json
import gc
import hashlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from jiejing_saas.repository import SaaSRepository
from jiejing_saas.ebay_message_adapter import MessageScope, EbayMessageAdapter, MESSAGE_SCOPE
from jiejing_saas.support_conversations import SupportConversations


def synthetic_receipt(request, message_id):
    """Complete official SendMessageResponse, with synthetic parties only."""
    return 201, {}, json.dumps({"messageId": message_id, "createdDate": "2026-10-12T01:00:00Z",
        "messageBody": json.loads(request.data)["messageText"],
        "senderUserName": "synthetic-seller", "recipientUserName": "synthetic-buyer"}).encode()


class SupportConversationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="jiejing-support-offline-")
        self.repo = SaaSRepository(Path(self.temp.name) / "test.sqlite", database_engine="sqlite", database_url="")
        self.account = self.repo.create_user_with_company(email="support-test@example.test",
                                                        password="synthetic-local-password", company_name="Synthetic")
        self.company = self.account["company"]["company_id"]
        self.user = self.account["user"]["user_id"]
        store = self.repo.create_store(company_id=self.company, user_id=self.user, payload={"platform": "ebay"})
        self.scope = MessageScope(self.company, store["store_id"], "synthetic-seller")
        self.service = SupportConversations(self.repo, self.scope)
        self.service.initialize_local_schema()
        self.incoming = {"status": "ok", "scope": self.scope.as_dict(), "conversation_id": "conv-1",
                         "truncated": False, "messages": [{"messageId": "m1", "messageBody": "What colour?",
                            "senderUsername": "synthetic-buyer", "recipientUsername": "synthetic-seller",
                            "createdDate": "2026-10-12T00:00:00Z"}]}

    def tearDown(self):
        gc.collect()  # Existing repository connection contexts release SQLite handles on GC.
        self.temp.cleanup()

    def test_synced_messages_are_deduplicated_and_error_keeps_last_snapshot(self):
        self.service.ingest(self.incoming)
        self.service.ingest(self.incoming)
        restored = SupportConversations(self.repo, self.scope)
        snapshot = restored.read_snapshot("conv-1")
        self.assertEqual(len(snapshot["messages"]), 1)
        restored.ingest({"status": "http_error", "scope": self.scope.as_dict(), "conversation_id": "conv-1"})
        snapshot = restored.read_snapshot("conv-1")
        self.assertEqual(len(snapshot["messages"]), 1)
        self.assertEqual(snapshot["sync_status"], "http_error")
        other = SupportConversations(self.repo, MessageScope(self.company, self.scope.store_id, "other-seller"))
        self.assertEqual(other.read_snapshot("conv-1")["messages"], [])

    def test_edit_requires_current_revision_and_changes_confirmation_binding(self):
        self.service.ingest(self.incoming)
        draft = self.service.create_draft("conv-1", "m1", body="Please see the blue option.",
                                          actor_id=self.user, fact_refs=["product.fact.colour"])
        old = self.service.prepare_confirmation(draft["draft_id"])
        changed = self.service.edit_draft(draft["draft_id"], expected_revision=1,
                                          body="The supplied photo shows blue.", actor_id=self.user)
        self.assertEqual(changed["revision"], 2)
        self.assertNotEqual(old["support_binding"], self.service.prepare_confirmation(draft["draft_id"])["support_binding"])
        with self.assertRaises(ValueError):
            self.service.edit_draft(draft["draft_id"], expected_revision=1, body="Stale edit", actor_id=self.user)
        self.assertEqual(len(self.service.draft_history(draft["draft_id"])), 2)

    def confirmation_for(self, draft_id):
        item = self.service.prepare_confirmation(draft_id)
        confirmation = self.repo.create_confirmation(company_id=self.company, store_id=self.scope.store_id,
            task_id=None, runtime_run_id="support-offline", item=item,
            action_type="buyer_message_send", title=item["title"])
        return self.repo.decide_confirmation(company_id=self.company,
            confirmation_id=confirmation["confirmation_id"], decision="approve", decided_by=self.user, note="Synthetic approval",
    expected_access_epochs=self.repo.access_session_epochs(user_id=self.user,company_id=self.company),
)

    def adapter(self, transport, *, send_enabled=True):
        return EbayMessageAdapter(self.scope, token_provider=lambda scope: {
            "ok": True, "binding": scope.as_dict(), "scopes": [MESSAGE_SCOPE], "access_token": "synthetic"},
            transport=transport, send_enabled=send_enabled)

    def test_existing_confirmation_exact_content_and_single_persistent_send(self):
        self.service.ingest(self.incoming)
        draft = self.service.create_draft("conv-1", "m1", body="Photo shows blue.", actor_id=self.user, fact_refs=["colour"])
        confirmation = self.confirmation_for(draft["draft_id"])
        calls = []
        def sent(request, timeout):
            calls.append(request)
            return synthetic_receipt(request, "sent-1")
        receipt = self.service.execute(draft["draft_id"], confirmation_id=confirmation["confirmation_id"],
                                       actor_id=self.user, adapter=self.adapter(sent))
        self.assertEqual(receipt["status"], "sent")
        restored = SupportConversations(self.repo, self.scope)
        duplicate = restored.execute(draft["draft_id"], confirmation_id=confirmation["confirmation_id"],
                                      actor_id=self.user, adapter=self.adapter(sent))
        self.assertEqual(duplicate["message_id"], "sent-1")
        self.assertEqual(len(calls), 1)

    def test_timeout_survives_restart_no_retry_and_no_edit_after_attempt(self):
        self.service.ingest(self.incoming)
        draft = self.service.create_draft("conv-1", "m1", body="Please check blue.", actor_id=self.user, fact_refs=["colour"])
        confirmation = self.confirmation_for(draft["draft_id"])
        calls = []
        def timeout(request, seconds):
            calls.append(request)
            raise TimeoutError("synthetic timeout containing no real data")
        receipt = self.service.execute(draft["draft_id"], confirmation_id=confirmation["confirmation_id"],
                                       actor_id=self.user, adapter=self.adapter(timeout))
        self.assertEqual(receipt["status"], "result_unknown")
        restored = SupportConversations(self.repo, self.scope)
        restored.execute(draft["draft_id"], confirmation_id=confirmation["confirmation_id"],
                         actor_id=self.user, adapter=self.adapter(timeout))
        self.assertEqual(len(calls), 1)
        with self.assertRaises(ValueError):
            restored.edit_draft(draft["draft_id"], expected_revision=1, body="Retry body", actor_id=self.user)

    def test_wrong_recipient_receipt_is_persistent_unknown_and_never_retried(self):
        self.service.ingest(self.incoming)
        draft = self.service.create_draft("conv-1", "m1", body="Blue.", actor_id=self.user, fact_refs=["colour"])
        confirmation = self.confirmation_for(draft["draft_id"])
        calls = []
        def mismatched(request, seconds):
            calls.append(request)
            status, headers, data = synthetic_receipt(request, "other-recipient")
            receipt = json.loads(data)
            receipt["recipientUserName"] = "different-buyer"
            return status, headers, json.dumps(receipt).encode()
        for service in (self.service, SupportConversations(self.repo, self.scope)):
            receipt = service.execute(draft["draft_id"], confirmation_id=confirmation["confirmation_id"],
                actor_id=self.user, adapter=self.adapter(mismatched))
            self.assertEqual(receipt["status"], "result_unknown")
            self.assertFalse(receipt["message_sent"])
            self.assertFalse(receipt["automatic_retry_allowed"])
        self.assertEqual(len(calls), 1)

    def test_source_changes_after_approval_require_new_draft_not_stale_reply(self):
        self.service.ingest(self.incoming)
        draft = self.service.create_draft("conv-1", "m1", body="Blue.", actor_id=self.user, fact_refs=["colour"])
        confirmation = self.confirmation_for(draft["draft_id"])
        newer = {**self.incoming, "messages": [{**self.incoming["messages"][0], "messageId": "m2",
                  "messageBody": "Actually cancel that question.", "createdDate": "2026-10-12T01:00:00Z"}]}
        self.service.ingest(newer)
        calls = []
        with self.assertRaises(ValueError):
            self.service.execute(draft["draft_id"], confirmation_id=confirmation["confirmation_id"],
                actor_id=self.user, adapter=self.adapter(lambda request, timeout: calls.append(request)))
        self.assertEqual(calls, [])

    def test_stale_confirm_and_cross_scope_never_send(self):
        self.service.ingest(self.incoming)
        draft = self.service.create_draft("conv-1", "m1", body="Blue.", actor_id=self.user, fact_refs=["colour"])
        confirmation = self.confirmation_for(draft["draft_id"])
        self.service.edit_draft(draft["draft_id"], expected_revision=1, body="New reply.", actor_id=self.user)
        calls = []
        adapter = self.adapter(lambda request, timeout: calls.append(request))
        with self.assertRaisesRegex(ValueError, "confirmation_binding_stale"):
            self.service.execute(draft["draft_id"], confirmation_id=confirmation["confirmation_id"], actor_id=self.user, adapter=adapter)
        wrong_scope = SupportConversations(self.repo, MessageScope("wrong-company", self.scope.store_id, self.scope.owner_id))
        with self.assertRaises(PermissionError):
            wrong_scope.read_snapshot("conv-1")
        with self.assertRaises(PermissionError):
            self.service.ingest({**self.incoming, "scope": {**self.scope.as_dict(), "owner_id": "other"}})
        self.assertEqual(calls, [])

    def test_production_schema_is_never_auto_created(self):
        class ProductionRepository:
            database_engine = "postgres"
            def initialize(self):
                raise AssertionError("must not initialize a production DB")
        service = SupportConversations(ProductionRepository(), self.scope)
        with self.assertRaisesRegex(RuntimeError, "reviewed_production_migration"):
            service.initialize_local_schema()

    def test_new_draft_cannot_bypass_unknown_send_for_same_source(self):
        self.service.ingest(self.incoming)
        draft = self.service.create_draft("conv-1", "m1", body="Blue.", actor_id=self.user, fact_refs=["colour"])
        confirmation = self.confirmation_for(draft["draft_id"])
        self.service.execute(draft["draft_id"], confirmation_id=confirmation["confirmation_id"], actor_id=self.user,
                             adapter=self.adapter(lambda request, timeout: (503, {}, b"{}")))
        with self.assertRaisesRegex(ValueError, "source_message_already_claimed"):
            self.service.create_draft("conv-1", "m1", body="Duplicate reply", actor_id=self.user, fact_refs=["colour"])

    def test_concurrent_execute_results_in_one_http_send(self):
        self.service.ingest(self.incoming)
        draft = self.service.create_draft("conv-1", "m1", body="Blue.", actor_id=self.user, fact_refs=["colour"])
        confirmation = self.confirmation_for(draft["draft_id"])
        calls = []
        def sent(request, timeout):
            calls.append(request)
            return synthetic_receipt(request, "one-only")
        def execute(_):
            return self.service.execute(draft["draft_id"], confirmation_id=confirmation["confirmation_id"],
                                         actor_id=self.user, adapter=self.adapter(sent))
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(execute, [1, 2]))
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.service.get_send_intent(draft["draft_id"])["status"], "sent")

    def test_cached_conversations_are_paged_without_external_refresh(self):
        self.service.ingest(self.incoming)
        self.service.ingest({**self.incoming, "conversation_id": "conv-2"})
        result = self.service.list_conversations(limit=1, offset=0)
        self.assertEqual(len(result["conversations"]), 1)
        self.assertTrue(result["has_more"])
        self.assertFalse(result["external_request_performed"])
        with self.assertRaises(ValueError):
            self.service.list_conversations(limit=501)

    def test_fractional_new_message_invalidates_approved_draft(self):
        self.service.ingest(self.incoming)
        draft = self.service.create_draft("conv-1", "m1", body="Blue.", actor_id=self.user, fact_refs=["colour"])
        confirmation = self.confirmation_for(draft["draft_id"])
        self.service.ingest({**self.incoming, "messages": [self.incoming["messages"][0], {**self.incoming["messages"][0],
            "messageId": "m2", "createdDate": "2026-10-12T00:00:00.100Z"}]})
        self.assertEqual([m["messageId"] for m in self.service.read_snapshot("conv-1")["messages"]], ["m1", "m2"])
        calls = []
        with self.assertRaisesRegex(ValueError, "source_message_changed"):
            self.service.execute(draft["draft_id"], confirmation_id=confirmation["confirmation_id"],
                actor_id=self.user, adapter=self.adapter(lambda request, timeout: calls.append(request)))
        self.assertEqual(calls, [])

    def test_timezones_are_normalized_and_ordered_by_instant(self):
        self.service.ingest({**self.incoming, "messages": [
            {**self.incoming["messages"][0], "messageId": "early", "createdDate": "2026-10-12T08:00:00+08:00"},
            {**self.incoming["messages"][0], "messageId": "later", "createdDate": "2026-10-12T00:00:01Z"}]})
        snapshot = self.service.read_snapshot("conv-1")
        self.assertEqual([m["messageId"] for m in snapshot["messages"]], ["early", "later"])
        self.assertEqual(snapshot["messages"][0]["createdDate"], "2026-10-12T00:00:00.000000Z")

    def test_invalid_or_missing_timestamp_blocks_send_and_preserves_cache(self):
        self.service.ingest(self.incoming)
        draft = self.service.create_draft("conv-1", "m1", body="Blue.", actor_id=self.user, fact_refs=["colour"])
        confirmation = self.confirmation_for(draft["draft_id"])
        for timestamp in ("", None, "invalid", "2026-10-12T00:00:01", "2026-02-30T00:00:00Z"):
            with self.subTest(timestamp=timestamp):
                snapshot = self.service.ingest({**self.incoming, "messages": [{**self.incoming["messages"][0],
                    "messageId": "invalid-new", "createdDate": timestamp}]})
                self.assertEqual(snapshot["sync_status"], "invalid_message_timestamp")
                self.assertEqual(len(snapshot["messages"]), 1)
                calls = []
                with self.assertRaises(ValueError):
                    self.service.execute(draft["draft_id"], confirmation_id=confirmation["confirmation_id"],
                        actor_id=self.user, adapter=self.adapter(lambda request, timeout: calls.append(request)))
                self.assertEqual(calls, [])
        self.assertIsNone(self.service.get_send_intent(draft["draft_id"]))

    def test_draft_official_2000_character_boundary_before_any_claim(self):
        self.service.ingest(self.incoming)
        draft = self.service.create_draft("conv-1", "m1", body="a" * 2000, actor_id=self.user, fact_refs=[])
        with self.assertRaises(ValueError):
            self.service.create_draft("conv-1", "m1", body="a" * 2001, actor_id=self.user, fact_refs=[])
        with self.assertRaises(ValueError):
            self.service.edit_draft(draft["draft_id"], expected_revision=1, body="a" * 2001, actor_id=self.user)
        self.assertIsNone(self.service.get_send_intent(draft["draft_id"]))

    def test_confirmed_no_outbound_token_failure_does_not_claim_source(self):
        self.service.ingest(self.incoming)
        draft = self.service.create_draft("conv-1", "m1", body="Blue.", actor_id=self.user, fact_refs=[])
        confirmation = self.confirmation_for(draft["draft_id"])
        calls = []
        def sent(request, timeout):
            calls.append(request)
            return synthetic_receipt(request, "single")
        blocked = EbayMessageAdapter(self.scope, token_provider=lambda scope: {"ok": False},
                                     transport=sent, send_enabled=True)
        result = self.service.execute(draft["draft_id"], confirmation_id=confirmation["confirmation_id"],
                                      actor_id=self.user, adapter=blocked)
        self.assertEqual(result["status"], "blocked_token_resolution")
        self.assertIsNone(self.service.get_send_intent(draft["draft_id"]))
        self.assertEqual(calls, [])
        result = self.service.execute(draft["draft_id"], confirmation_id=confirmation["confirmation_id"],
                                      actor_id=self.user, adapter=self.adapter(sent))
        self.assertEqual(result["status"], "sent")
        self.assertEqual(len(calls), 1)

    def test_complete_empty_refresh_preserves_history_but_invalidates_send(self):
        self.service.ingest(self.incoming)
        draft = self.service.create_draft("conv-1", "m1", body="Blue.", actor_id=self.user, fact_refs=[])
        confirmation = self.confirmation_for(draft["draft_id"])
        snapshot = self.service.ingest({**self.incoming, "messages": []})
        self.assertEqual(len(snapshot["messages"]), 1)
        calls = []
        with self.assertRaisesRegex(ValueError, "source_message_not_in_current_snapshot"):
            self.service.execute(draft["draft_id"], confirmation_id=confirmation["confirmation_id"],
                actor_id=self.user, adapter=self.adapter(lambda request, timeout: calls.append(request)))
        with self.assertRaises(ValueError):
            self.service.create_draft("conv-1", "m1", body="Obsolete", actor_id=self.user, fact_refs=[])
        self.assertEqual(calls, [])
        self.assertIsNone(self.service.get_send_intent(draft["draft_id"]))

    def test_arbitrary_fact_reference_is_never_claimed_as_verified(self):
        self.service.ingest(self.incoming)
        draft = self.service.create_draft("conv-1", "m1", body="Blue.", actor_id=self.user,
                                          fact_refs=["nonexistent-fact"])
        item = self.service.prepare_confirmation(draft["draft_id"])
        self.assertFalse(item["facts_verified"])
        self.assertIn("fact_references_unverified", item["risk_flags"])

    def test_equal_instants_do_not_invent_message_order(self):
        self.service.ingest(self.incoming)
        draft = self.service.create_draft("conv-1", "m1", body="Blue.", actor_id=self.user, fact_refs=[])
        confirmation = self.confirmation_for(draft["draft_id"])
        self.service.ingest({**self.incoming, "messages": [self.incoming["messages"][0],
            {**self.incoming["messages"][0], "messageId": "m2", "createdDate": "2026-10-12T08:00:00+08:00"}]})
        with self.assertRaisesRegex(ValueError, "source_message_order_ambiguous"):
            self.service.execute(draft["draft_id"], confirmation_id=confirmation["confirmation_id"], actor_id=self.user,
                adapter=self.adapter(lambda request, timeout: self.fail("must not send")))

    def test_invalid_message_record_refresh_persists_blocked_snapshot(self):
        before = self.service.ingest(self.incoming)
        draft = self.service.create_draft("conv-1", "m1", body="Blue.", actor_id=self.user, fact_refs=[])
        confirmation = self.confirmation_for(draft["draft_id"])
        newer = {**self.incoming["messages"][0], "messageId": "m2", "createdDate": "2026-10-12T00:00:01Z"}
        malformed_records = [
            {key: value for key, value in newer.items() if key != "messageBody"},
            {**newer, "messageBody": None}, {**newer, "messageBody": {"text": "new question"}},
            {**newer, "messageId": None}, {**newer, "messageId": ["m2"]}, None,
        ]
        for malformed in malformed_records:
            with self.subTest(malformed=malformed):
                snapshot = self.service.ingest({**self.incoming, "messages": [self.incoming["messages"][0], malformed]})
                self.assertEqual(snapshot["sync_status"], "invalid_message_record")
                self.assertEqual(snapshot["messages"], before["messages"])
                self.assertEqual(snapshot["last_success_at"], before["last_success_at"])
                self.assertEqual(snapshot["current_message_ids"], [])
                self.assertEqual(snapshot["current_message_hashes"], {})
                with self.assertRaisesRegex(ValueError, "complete_current_snapshot_required"):
                    self.service.execute(draft["draft_id"], confirmation_id=confirmation["confirmation_id"],
                        actor_id=self.user, adapter=self.adapter(lambda request, timeout: self.fail("must not send")))
                self.assertIsNone(self.service.get_send_intent(draft["draft_id"]))

    def test_invalid_message_list_or_owner_refresh_cannot_reuse_old_confirmation(self):
        before = self.service.ingest(self.incoming)
        draft = self.service.create_draft("conv-1", "m1", body="Blue.", actor_id=self.user, fact_refs=[])
        confirmation = self.confirmation_for(draft["draft_id"])
        newer = {**self.incoming["messages"][0], "messageId": "m2", "createdDate": "2026-10-12T00:00:01Z"}
        for messages, expected_status in (
            (None, "messages_required"), ({"messageId": "m2"}, "messages_required"),
            ([{**newer, "recipientUsername": "another-seller"}], "message_owner_mismatch"),
            ([{**newer, "senderUsername": []}], "invalid_message_record"),
            ([{**newer, "senderUsername": self.scope.owner_id, "recipientUsername": None}], "invalid_message_record"),
            ([{**newer, "createdDate": "invalid-date"}], "invalid_message_timestamp"),
        ):
            with self.subTest(messages=messages):
                snapshot = self.service.ingest({**self.incoming, "messages": messages})
                self.assertEqual(snapshot["sync_status"], expected_status)
                self.assertEqual(snapshot["messages"], before["messages"])
                self.assertEqual(snapshot["last_success_at"], before["last_success_at"])
                self.assertEqual(snapshot["current_message_ids"], [])
                self.assertEqual(snapshot["current_message_hashes"], {})
                restored = SupportConversations(self.repo, self.scope)
                with self.assertRaisesRegex(ValueError, "complete_current_snapshot_required"):
                    restored.execute(draft["draft_id"], confirmation_id=confirmation["confirmation_id"],
                        actor_id=self.user, adapter=self.adapter(lambda request, timeout: self.fail("must not send")))
                self.assertIsNone(restored.get_send_intent(draft["draft_id"]))

    def test_valid_refresh_restores_eligibility_without_losing_history_or_duplicate_send(self):
        before = self.service.ingest(self.incoming)
        draft = self.service.create_draft("conv-1", "m1", body="Blue.", actor_id=self.user, fact_refs=[])
        confirmation = self.confirmation_for(draft["draft_id"])
        self.service.ingest({**self.incoming, "messages": [{"messageId": "malformed"}]})
        restored = SupportConversations(self.repo, self.scope)
        with self.assertRaisesRegex(ValueError, "complete_current_snapshot_required"):
            restored.create_draft("conv-1", "m1", body="Must not bypass", actor_id=self.user, fact_refs=[])
        snapshot = restored.ingest(self.incoming)
        self.assertEqual(snapshot["sync_status"], "ok")
        self.assertEqual(snapshot["messages"], before["messages"])
        self.assertEqual(snapshot["current_message_ids"], ["m1"])
        calls = []
        def sent(request, timeout):
            calls.append(request)
            return synthetic_receipt(request, "restored-one")
        for _ in range(2):
            receipt = restored.execute(draft["draft_id"], confirmation_id=confirmation["confirmation_id"],
                                       actor_id=self.user, adapter=self.adapter(sent))
            self.assertEqual(receipt["status"], "sent")
        self.assertEqual(len(calls), 1)

    def test_cross_scope_failure_cannot_invalidate_a_different_bound_snapshot(self):
        before = self.service.ingest(self.incoming)
        for key in ("company_id", "store_id", "owner_id"):
            with self.subTest(key=key):
                with self.assertRaisesRegex(PermissionError, "message_scope_mismatch"):
                    self.service.ingest({**self.incoming, "messages": None,
                        "scope": {**self.scope.as_dict(), key: "another-scope"}})
                self.assertEqual(self.service.read_snapshot("conv-1"), before)
        for conversation_id in (None, ""):
            with self.assertRaisesRegex(ValueError, "conversation_id_required"):
                self.service.ingest({**self.incoming, "conversation_id": conversation_id, "messages": None})
            self.assertEqual(self.service.read_snapshot("conv-1"), before)

    def test_concurrent_failed_refreshes_remain_blocked_without_partial_messages(self):
        before = self.service.ingest(self.incoming)
        draft = self.service.create_draft("conv-1", "m1", body="Blue.", actor_id=self.user, fact_refs=[])
        confirmation = self.confirmation_for(draft["draft_id"])
        valid_prefix = {**self.incoming["messages"][0], "messageId": "m2", "createdDate": "2026-10-12T00:00:01Z"}
        invalid = [None, {**valid_prefix, "messageId": "m3", "recipientUsername": "another-seller"}]
        def refresh(message):
            return self.service.ingest({**self.incoming, "messages": [valid_prefix, message]})
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(refresh, invalid))
        for snapshot in results + [self.service.read_snapshot("conv-1")]:
            self.assertIn(snapshot["sync_status"], ("invalid_message_record", "message_owner_mismatch"))
            self.assertEqual(snapshot["messages"], before["messages"])
            self.assertEqual(snapshot["current_message_ids"], [])
            self.assertEqual(snapshot["current_message_hashes"], {})
        with self.assertRaisesRegex(ValueError, "complete_current_snapshot_required"):
            self.service.execute(draft["draft_id"], confirmation_id=confirmation["confirmation_id"],
                actor_id=self.user, adapter=self.adapter(lambda request, timeout: self.fail("must not send")))
        self.assertIsNone(self.service.get_send_intent(draft["draft_id"]))

    def test_hash_bound_owner_accepts_casefold_incoming_and_sends_once_after_confirmation(self):
        digest = hashlib.sha256(b"synthetic-seller").hexdigest()
        self.scope = MessageScope(self.company, self.scope.store_id, digest,
                                  owner_binding_kind="sha256_casefold_ebay_username")
        self.service = SupportConversations(self.repo, self.scope)
        incoming = {**self.incoming, "scope": self.scope.as_dict(), "messages": [
            {**self.incoming["messages"][0], "recipientUsername": "SYNTHETIC-Seller"},
            {**self.incoming["messages"][0], "messageId": "own-1", "messageBody": "Our earlier reply",
             "senderUsername": "Synthetic-Seller", "recipientUsername": "synthetic-buyer",
             "createdDate": "2026-10-12T00:00:01Z"}]}
        snapshot = self.service.ingest(incoming)
        self.assertEqual(snapshot["sync_status"], "ok")
        self.assertEqual(len(snapshot["messages"]), 2)
        with self.assertRaisesRegex(ValueError, "incoming_source_message_required"):
            self.service.create_draft("conv-1", "own-1", body="Not an incoming message",
                                      actor_id=self.user, fact_refs=[])
        draft = self.service.create_draft("conv-1", "m1", body="Photo shows blue.",
                                          actor_id=self.user, fact_refs=[])
        confirmation = self.confirmation_for(draft["draft_id"])
        self.assertEqual(confirmation["item"]["support_binding"]["owner_binding_kind"],
                         "sha256_casefold_ebay_username")
        calls = []
        def sent(request, timeout):
            calls.append(request)
            return synthetic_receipt(request, "hash-sent-1")
        for service in (self.service, SupportConversations(self.repo, self.scope)):
            receipt = service.execute(draft["draft_id"], confirmation_id=confirmation["confirmation_id"],
                                       actor_id=self.user, adapter=self.adapter(sent))
            self.assertEqual(receipt["message_id"], "hash-sent-1")
        self.assertEqual(len(calls), 1)

    def test_raw_digest_fixture_and_hash_owner_have_disjoint_persistent_scopes(self):
        digest = hashlib.sha256(b"synthetic-seller").hexdigest()
        hashed_scope = MessageScope(self.company, self.scope.store_id, digest,
                                    owner_binding_kind="sha256_casefold_ebay_username")
        raw_scope = MessageScope(self.company, self.scope.store_id, digest)
        hashed = SupportConversations(self.repo, hashed_scope)
        raw = SupportConversations(self.repo, raw_scope)
        payload = {**self.incoming, "scope": hashed_scope.as_dict()}
        hashed.ingest(payload)
        hashed_draft = hashed.create_draft("conv-1", "m1", body="Hash-mode reply", actor_id=self.user, fact_refs=[])
        self.assertEqual(raw.read_snapshot("conv-1")["messages"], [])
        self.assertEqual(raw.list_conversations()["conversations"], [])
        with self.assertRaises(KeyError):
            raw.get_draft(hashed_draft["draft_id"])
        with self.assertRaisesRegex(PermissionError, "message_scope_mismatch"):
            raw.ingest(payload)
        raw_payload = {**payload, "scope": raw_scope.as_dict(), "messages": [
            {**self.incoming["messages"][0], "recipientUsername": digest, "messageBody": "Other fixture"}]}
        raw.ingest(raw_payload)
        raw_draft = raw.create_draft("conv-1", "m1", body="Raw-mode reply", actor_id=self.user, fact_refs=[])
        self.assertEqual(hashed.read_snapshot("conv-1")["messages"][0]["messageBody"], "What colour?")
        self.assertEqual(raw.read_snapshot("conv-1")["messages"][0]["messageBody"], "Other fixture")
        self.assertNotEqual(raw.prepare_confirmation(raw_draft["draft_id"])["support_binding_hash"],
                            hashed.prepare_confirmation(hashed_draft["draft_id"])["support_binding_hash"])
        wrong_adapter = EbayMessageAdapter(raw_scope, token_provider=lambda scope: self.fail("must not resolve"),
                                           transport=lambda request, timeout: self.fail("must not send"), send_enabled=True)
        with self.assertRaisesRegex(PermissionError, "adapter_scope_mismatch"):
            hashed.execute(hashed_draft["draft_id"], confirmation_id="not-reached", actor_id=self.user,
                           adapter=wrong_adapter)

    def test_hash_owner_bad_batch_still_invalidates_previous_confirmation(self):
        digest = hashlib.sha256(b"synthetic-seller").hexdigest()
        self.scope = MessageScope(self.company, self.scope.store_id, digest,
                                  owner_binding_kind="sha256_casefold_ebay_username")
        self.service = SupportConversations(self.repo, self.scope)
        incoming = {**self.incoming, "scope": self.scope.as_dict()}
        before = self.service.ingest(incoming)
        draft = self.service.create_draft("conv-1", "m1", body="Blue.", actor_id=self.user, fact_refs=[])
        confirmation = self.confirmation_for(draft["draft_id"])
        newer = {**incoming["messages"][0], "messageId": "m2", "createdDate": "2026-10-12T00:00:00.100Z"}
        for messages, expected in (
            ([incoming["messages"][0], {k: v for k, v in newer.items() if k != "messageBody"}], "invalid_message_record"),
            ([{**newer, "recipientUsername": "other-seller"}], "message_owner_mismatch"),
            ([{**newer, "recipientUsername": digest}], "message_owner_mismatch"),
            (None, "messages_required"),
        ):
            with self.subTest(expected=expected, messages=messages):
                self.service.ingest(incoming)
                snapshot = self.service.ingest({**incoming, "messages": messages})
                self.assertEqual(snapshot["sync_status"], expected)
                self.assertEqual(snapshot["messages"], before["messages"])
                self.assertEqual(snapshot["current_message_ids"], [])
                self.assertEqual(snapshot["current_message_hashes"], {})
                with self.assertRaisesRegex(ValueError, "complete_current_snapshot_required"):
                    self.service.execute(draft["draft_id"], confirmation_id=confirmation["confirmation_id"],
                        actor_id=self.user, adapter=self.adapter(lambda request, timeout: self.fail("must not send")))
                self.assertIsNone(self.service.get_send_intent(draft["draft_id"]))

    def test_hash_scope_changed_incoming_casefold_still_invalidates_stale_reply(self):
        digest = hashlib.sha256(b"synthetic-seller").hexdigest()
        self.scope = MessageScope(self.company, self.scope.store_id, digest,
                                  owner_binding_kind="sha256_casefold_ebay_username")
        self.service = SupportConversations(self.repo, self.scope)
        incoming = {**self.incoming, "scope": self.scope.as_dict()}
        self.service.ingest(incoming)
        draft = self.service.create_draft("conv-1", "m1", body="Blue.", actor_id=self.user, fact_refs=[])
        confirmation = self.confirmation_for(draft["draft_id"])
        self.service.ingest({**incoming, "messages": [incoming["messages"][0],
            {**incoming["messages"][0], "messageId": "m2", "recipientUsername": "SYNTHETIC-SELLER",
             "createdDate": "2026-10-12T00:00:00.100Z"}]})
        with self.assertRaisesRegex(ValueError, "source_message_changed_since_draft"):
            self.service.execute(draft["draft_id"], confirmation_id=confirmation["confirmation_id"],
                actor_id=self.user, adapter=self.adapter(lambda request, timeout: self.fail("must not send")))
        self.assertIsNone(self.service.get_send_intent(draft["draft_id"]))

    def test_hash_scope_rejects_other_owner_and_mode_without_mutating_snapshot(self):
        digest = hashlib.sha256(b"synthetic-seller").hexdigest()
        self.scope = MessageScope(self.company, self.scope.store_id, digest,
                                  owner_binding_kind="sha256_casefold_ebay_username")
        self.service = SupportConversations(self.repo, self.scope)
        incoming = {**self.incoming, "scope": self.scope.as_dict()}
        before = self.service.ingest(incoming)
        for change in ({"owner_binding_kind": "raw_fixture"}, {"owner_id": hashlib.sha256(b"other").hexdigest()},
                       {"company_id": "another-company"}, {"store_id": "another-store"}):
            with self.subTest(change=change), self.assertRaisesRegex(PermissionError, "message_scope_mismatch"):
                self.service.ingest({**incoming, "scope": {**self.scope.as_dict(), **change}, "messages": None})
            self.assertEqual(self.service.read_snapshot("conv-1"), before)
        other = SupportConversations(self.repo, MessageScope(self.company, self.scope.store_id,
            hashlib.sha256(b"other").hexdigest(), owner_binding_kind="sha256_casefold_ebay_username"))
        self.assertEqual(other.read_snapshot("conv-1")["messages"], [])

    def test_executor_revoked_during_token_preparation_cannot_claim_or_send(self):
        employee = self.repo.create_user_with_company(email="executor-race@example.test",
            password="synthetic-local-password", company_name="Synthetic employee")
        executor = employee["user"]["user_id"]
        for mutation in ("downgrade", "remove"):
            with self.subTest(mutation=mutation):
                with self.service._connection() as conn:
                    conn.execute("insert into team_members(company_id,user_id,role,created_at) values(?,?,?,?) "
                        "on conflict(company_id,user_id) do update set role=excluded.role",
                        (self.company, executor, "operator", "2026-10-12T00:00:00Z"))
                conversation = "executor-race-" + mutation
                self.service.ingest({**self.incoming, "conversation_id": conversation})
                draft = self.service.create_draft(conversation, "m1", body="Approved reply",
                    actor_id=self.user, fact_refs=[])
                confirmation = self.confirmation_for(draft["draft_id"])
                calls = []
                def token_provider(scope):
                    with self.service._connection() as conn:
                        if mutation == "downgrade":
                            conn.execute("update team_members set role='viewer' where company_id=? and user_id=?",
                                (self.company, executor))
                        else:
                            conn.execute("delete from team_members where company_id=? and user_id=?",
                                (self.company, executor))
                    return {"ok": True, "binding": scope.as_dict(), "scopes": [MESSAGE_SCOPE], "access_token": "synthetic"}
                def transport(request, timeout):
                    calls.append(request)
                    return 201, {}, b'{"messageId":"must-not-send","createdDate":"2026-10-12T01:00:00Z"}'
                adapter = EbayMessageAdapter(self.scope, token_provider=token_provider, transport=transport, send_enabled=True)
                with self.assertRaisesRegex(PermissionError, "support_executor_not_authorized"):
                    self.service.execute(draft["draft_id"], confirmation_id=confirmation["confirmation_id"],
                        actor_id=executor, adapter=adapter)
                self.assertEqual(calls, [])
                self.assertIsNone(self.service.get_send_intent(draft["draft_id"]))
                self.assertEqual(self.repo.get_team_member(company_id=self.company, user_id=self.user)["role"], "owner")

    def test_disabled_actor_cannot_create_or_edit_reply_drafts(self):
        self.service.ingest(self.incoming)
        draft = self.service.create_draft("conv-1", "m1", body="Blue.", actor_id=self.user, fact_refs=[])
        self.repo.set_user_access_status(user_id=self.user, status="disabled")
        with self.assertRaisesRegex(PermissionError, "support_missing_permission"):
            self.service.create_draft("conv-1", "m1", body="Disabled reply", actor_id=self.user, fact_refs=[])
        with self.assertRaisesRegex(PermissionError, "support_missing_permission"):
            self.service.edit_draft(draft["draft_id"], expected_revision=1, body="Disabled edit", actor_id=self.user)
        self.assertEqual(len(self.service.draft_history(draft["draft_id"])), 1)

    def test_account_disabled_during_token_preparation_cannot_claim_or_send(self):
        employee = self.repo.create_user_with_company(email="disabled-send-race@example.test",
            password="synthetic-local-password", company_name="Synthetic employee")
        executor = employee["user"]["user_id"]
        with self.service._connection() as conn:
            conn.execute("insert into team_members(company_id,user_id,role,created_at) values(?,?,?,?)",
                (self.company, executor, "operator", "2026-10-12T00:00:00Z"))
        for target, error in ((executor, "support_executor_not_authorized"),
                              (self.user, "confirmation_approver_not_authorized")):
            with self.subTest(target_role="executor" if target == executor else "approver"):
                self.repo.set_user_access_status(user_id=executor, status="active")
                self.repo.set_user_access_status(user_id=self.user, status="active")
                conversation = "disabled-claim-" + target
                self.service.ingest({**self.incoming, "conversation_id": conversation})
                draft = self.service.create_draft(conversation, "m1", body="Approved reply",
                    actor_id=self.user, fact_refs=[])
                confirmation = self.confirmation_for(draft["draft_id"])
                calls = []
                def token_provider(scope):
                    self.repo.set_user_access_status(user_id=target, status="disabled")
                    return {"ok": True, "binding": scope.as_dict(), "scopes": [MESSAGE_SCOPE], "access_token": "synthetic"}
                adapter = EbayMessageAdapter(self.scope, token_provider=token_provider,
                    transport=lambda request, timeout: calls.append(request), send_enabled=True)
                with self.assertRaisesRegex(PermissionError, error):
                    self.service.execute(draft["draft_id"], confirmation_id=confirmation["confirmation_id"],
                        actor_id=executor, adapter=adapter)
                self.assertEqual(calls, [])
                self.assertIsNone(self.service.get_send_intent(draft["draft_id"]))

    def test_malformed_utf8_refresh_invalidates_hash_owner_snapshot_before_encoding(self):
        self.scope = MessageScope(self.company, self.scope.store_id, hashlib.sha256(b"synthetic-seller").hexdigest(),
                                  owner_binding_kind="sha256_casefold_ebay_username")
        self.service = SupportConversations(self.repo, self.scope)
        incoming = {**self.incoming, "scope": self.scope.as_dict()}
        before = self.service.ingest(incoming)
        draft = self.service.create_draft("conv-1", "m1", body="Approved reply", actor_id=self.user, fact_refs=[])
        confirmation = self.confirmation_for(draft["draft_id"])
        for field in ("senderUsername", "recipientUsername", "messageId", "messageBody", "createdDate"):
            with self.subTest(field=field):
                before = self.service.ingest(incoming)
                broken = {**incoming["messages"][0], "messageId": "bad-utf8", "createdDate": "2026-10-12T00:00:01Z",
                          field: "unpaired-\ud800"}
                snapshot = self.service.ingest({**incoming, "messages": [incoming["messages"][0], broken]})
                self.assertIn(snapshot["sync_status"], ("invalid_message_record", "invalid_message_timestamp"))
                self.assertEqual(snapshot["messages"], before["messages"])
                self.assertEqual(snapshot["last_success_at"], before["last_success_at"])
                self.assertEqual(snapshot["current_message_ids"], [])
                self.assertEqual(snapshot["current_message_hashes"], {})
                calls = []
                with self.assertRaisesRegex(ValueError, "complete_current_snapshot_required"):
                    self.service.execute(draft["draft_id"], confirmation_id=confirmation["confirmation_id"],
                        actor_id=self.user, adapter=self.adapter(lambda request, timeout: calls.append(request)))
                self.assertEqual(calls, [])
                self.assertIsNone(self.service.get_send_intent(draft["draft_id"]))

    def test_valid_emoji_refresh_recovers_after_malformed_utf8_without_content_loss(self):
        self.scope = MessageScope(self.company, self.scope.store_id, hashlib.sha256(b"synthetic-seller").hexdigest(),
                                  owner_binding_kind="sha256_casefold_ebay_username")
        self.service = SupportConversations(self.repo, self.scope)
        message = {**self.incoming["messages"][0], "messageBody": "请问是蓝色吗？ 💙"}
        incoming = {**self.incoming, "scope": self.scope.as_dict(), "messages": [message]}
        before = self.service.ingest(incoming)
        invalid = self.service.ingest({**incoming, "messages": [{**message, "messageBody": "bad-\udfff"}]})
        self.assertEqual(invalid["sync_status"], "invalid_message_record")
        recovered = self.service.ingest(incoming)
        self.assertEqual(recovered["sync_status"], "ok")
        self.assertEqual(recovered["messages"], before["messages"])
        body = "照片中是蓝色 💙\nPlease check the supplied photo."
        draft = self.service.create_draft("conv-1", "m1", body=body, actor_id=self.user, fact_refs=[])
        confirmation = self.confirmation_for(draft["draft_id"])
        payloads = []
        def transport(request, timeout):
            payloads.append(json.loads(request.data.decode("utf-8")))
            return synthetic_receipt(request, "emoji-sent")
        result = self.service.execute(draft["draft_id"], confirmation_id=confirmation["confirmation_id"],
            actor_id=self.user, adapter=self.adapter(transport))
        self.assertEqual(result["status"], "sent")
        self.assertEqual(payloads, [{"conversationId": "conv-1", "messageText": body}])
        self.assertEqual(confirmation["item"]["message_body"], payloads[0]["messageText"])

    def test_invalid_utf8_routing_is_rejected_and_status_is_safe_failure(self):
        before = self.service.ingest(self.incoming)
        with self.assertRaisesRegex(ValueError, "conversation_id_required"):
            self.service.ingest({**self.incoming, "conversation_id": "bad-\ud800"})
        self.assertEqual(self.service.read_snapshot("conv-1"), before)
        failed = self.service.ingest({**self.incoming, "status": "bad-\ud800"})
        self.assertEqual(failed["sync_status"], "invalid_response")
        self.assertEqual(failed["messages"], before["messages"])
        self.assertEqual(failed["current_message_ids"], [])
        self.assertEqual(failed["current_message_hashes"], {})

    def test_approver_revoked_during_token_preparation_with_valid_executor_is_blocked(self):
        employee = self.repo.create_user_with_company(email="valid-executor@example.test",
            password="synthetic-local-password", company_name="Synthetic employee")
        executor = employee["user"]["user_id"]
        with self.service._connection() as conn:
            conn.execute("insert into team_members(company_id,user_id,role,created_at) values(?,?,?,?)",
                (self.company, executor, "operator", "2026-10-12T00:00:00Z"))
        self.service.ingest(self.incoming)
        draft = self.service.create_draft("conv-1", "m1", body="Approved reply", actor_id=self.user, fact_refs=[])
        confirmation = self.confirmation_for(draft["draft_id"])
        calls = []
        def token_provider(scope):
            with self.service._connection() as conn:
                conn.execute("update team_members set role='viewer' where company_id=? and user_id=?",
                    (self.company, self.user))
            return {"ok": True, "binding": scope.as_dict(), "scopes": [MESSAGE_SCOPE], "access_token": "synthetic"}
        adapter = EbayMessageAdapter(self.scope, token_provider=token_provider,
            transport=lambda request, timeout: calls.append(request), send_enabled=True)
        with self.assertRaisesRegex(PermissionError, "confirmation_approver_not_authorized"):
            self.service.execute(draft["draft_id"], confirmation_id=confirmation["confirmation_id"],
                actor_id=executor, adapter=adapter)
        self.assertEqual(calls, [])
        self.assertIsNone(self.service.get_send_intent(draft["draft_id"]))


if __name__ == "__main__":
    unittest.main()
