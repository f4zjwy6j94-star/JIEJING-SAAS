"""Offline Message API contract tests; no external requests or real credentials."""
from __future__ import annotations

import json
import io
import hashlib
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from urllib.request import HTTPSHandler, Request, build_opener
from urllib.response import addinfourl

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from jiejing_saas.ebay_message_adapter import EbayMessageAdapter, MessageScope, MESSAGE_SCOPE
from jiejing_saas import ebay_message_adapter as adapter_module


class MessageAdapterTests(unittest.TestCase):
    def setUp(self):
        self.scope = MessageScope("company-a", "store-a", "seller-a")
        self.calls = []

    def token(self, scope):
        return {"ok": True, "access_token": "synthetic-not-a-real-token",
                "binding": scope.as_dict(), "scopes": [MESSAGE_SCOPE]}

    def transport(self, request, timeout):
        self.calls.append(request)
        return 200, {}, json.dumps({"conversations": [{"conversationId": "conv-1"}],
                                   "total": 1}).encode()

    def test_read_is_explicitly_enabled_and_only_uses_official_get(self):
        adapter = EbayMessageAdapter(self.scope, token_provider=self.token, transport=self.transport)
        self.assertEqual(adapter.get_conversations()["status"], "blocked_read_disabled")
        self.assertEqual(len(self.calls), 0)
        adapter = EbayMessageAdapter(self.scope, token_provider=self.token, transport=self.transport,
                                     read_enabled=True)
        result = adapter.get_conversations()
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["conversations"][0]["conversationId"], "conv-1")
        self.assertEqual(self.calls[0].get_method(), "GET")
        self.assertTrue(self.calls[0].full_url.startswith("https://api.ebay.com/commerce/message/v1/conversation?"))
        self.assertIn("conversation_type=FROM_MEMBERS", self.calls[0].full_url)
        self.assertNotIn("synthetic-not-a-real-token", json.dumps(result))

    def test_pagination_is_bounded_and_provider_next_url_is_never_followed(self):
        def pages(request, timeout):
            self.calls.append(request)
            return 200, {}, json.dumps({"conversations": [{"conversationId": str(len(self.calls))}],
                                       "next": "https://evil.invalid/leak"}).encode()
        adapter = EbayMessageAdapter(self.scope, token_provider=self.token, transport=pages, read_enabled=True)
        with self.assertRaises(ValueError):
            adapter.get_conversations(limit=51)
        with self.assertRaises(ValueError):
            adapter.get_conversations(max_pages=4)
        result = adapter.get_conversations(limit=1, max_pages=2)
        self.assertEqual(len(result["conversations"]), 2)
        self.assertTrue(result["truncated"])
        self.assertTrue(all(r.full_url.startswith("https://api.ebay.com/") for r in self.calls))
        self.assertIn("offset=1", self.calls[1].full_url)

    def test_detail_keeps_conversation_binding_and_failure_is_not_empty_inbox(self):
        def detail(request, timeout):
            self.calls.append(request)
            return 200, {}, json.dumps({"messages": [{"messageId": "m1", "messageBody": "Synthetic question"}],
                                       "conversationType": "FROM_MEMBERS"}).encode()
        adapter = EbayMessageAdapter(self.scope, token_provider=self.token, transport=detail, read_enabled=True)
        result = adapter.get_conversation("conv-1")
        self.assertEqual(result["conversation_id"], "conv-1")
        self.assertEqual(result["messages"][0]["messageId"], "m1")
        with self.assertRaises(ValueError):
            adapter.get_conversation("../send_message")
        wrong_token = lambda scope: {**self.token(scope), "binding": {**scope.as_dict(), "owner_id": "other"}}
        bad = EbayMessageAdapter(self.scope, token_provider=wrong_token, transport=detail, read_enabled=True)
        failed = bad.get_conversation("conv-1")
        self.assertEqual(failed["status"], "blocked_token_binding")
        self.assertIsNone(failed["messages"])
        self.assertEqual(len(self.calls), 1)

    def test_send_disabled_by_default_and_receipt_required_not_just_http_success(self):
        adapter = EbayMessageAdapter(self.scope, token_provider=self.token, transport=self.transport)
        self.assertEqual(adapter.send_reply("conv-1", "Draft reply")["status"], "blocked_send_disabled")
        self.assertEqual(len(self.calls), 0)
        adapter = EbayMessageAdapter(self.scope, token_provider=self.token, transport=self.transport, send_enabled=True)
        self.assertEqual(adapter.send_reply("conv-1", "Draft reply", expected_recipient="buyer-a")["status"], "result_unknown")
        self.assertEqual(self.calls[0].get_method(), "POST")
        self.assertEqual(json.loads(self.calls[0].data), {"conversationId": "conv-1", "messageText": "Draft reply"})
        def accepted(request, timeout):
            return 201, {}, json.dumps({"messageId": "sent-1", "createdDate": "2026-10-12T04:00:00Z",
                "messageBody": "Draft reply", "senderUserName": "seller-a", "recipientUserName": "buyer-a"}).encode()
        adapter = EbayMessageAdapter(self.scope, token_provider=self.token, transport=accepted, send_enabled=True)
        self.assertEqual(adapter.send_reply("conv-1", "Draft reply", expected_recipient="buyer-a")["status"], "sent")

    def test_failed_detail_retains_scope_for_safe_error_snapshot(self):
        adapter = EbayMessageAdapter(self.scope, token_provider=self.token,
            transport=lambda request, timeout: (403, {}, b'{"message":"do not expose raw error"}'), read_enabled=True)
        result = adapter.get_conversation("conv-1")
        self.assertEqual(result["scope"], self.scope.as_dict())
        self.assertEqual(result["conversation_id"], "conv-1")
        self.assertEqual(result["status"], "http_error")
        self.assertIsNone(result["messages"])
        self.assertNotIn("do not expose", json.dumps(result))

    def test_send_receipt_must_match_body_sender_and_intended_recipient(self):
        receipt = {"messageId": "sent-verified", "createdDate": "2026-10-13T01:00:00Z",
                   "messageBody": "Draft reply", "senderUserName": "seller-a", "recipientUserName": "buyer-a"}
        def transport(request, timeout):
            self.calls.append(request)
            return 201, {}, json.dumps(receipt).encode()
        adapter = EbayMessageAdapter(self.scope, token_provider=self.token, transport=transport, send_enabled=True)
        result = adapter.send_reply("conv-1", "Draft reply", expected_recipient="buyer-a")
        self.assertEqual(result["status"], "sent")
        for field, value in (("messageBody", "Different reply"), ("senderUserName", "other-seller"),
                             ("recipientUserName", "other-buyer"), ("createdDate", "not-a-date")):
            with self.subTest(field=field):
                original = receipt[field]
                receipt[field] = value
                result = adapter.send_reply("conv-1", "Draft reply", expected_recipient="buyer-a")
                self.assertEqual(result["status"], "result_unknown")
                self.assertFalse(result["message_sent"])
                self.assertNotIn("messageBody", result)
                receipt[field] = original
        self.assertEqual(len(self.calls), 5)

    def test_ambiguous_receipt_and_mutated_prepared_body_never_claim_sent(self):
        def duplicate_receipt(request, timeout):
            self.calls.append(request)
            return 201, {}, (b'{"messageId":"m","createdDate":"2026-10-13T01:00:00Z",'
                b'"senderUserName":"seller-a","recipientUserName":"wrong",'
                b'"recipientUserName":"buyer-a","messageBody":"Reply"}')
        adapter = EbayMessageAdapter(self.scope, token_provider=self.token,
                                     transport=duplicate_receipt, send_enabled=True)
        self.assertEqual(adapter.send_reply("conv-1", "Reply", expected_recipient="buyer-a")["status"], "result_unknown")
        prepared = adapter.prepare_reply("conv-1", "Reply", expected_recipient="buyer-a")
        prepared.request.data = json.dumps({"conversationId": "conv-1", "messageText": "Tampered"}).encode()
        self.assertEqual(adapter.send_prepared_reply(prepared)["status"], "result_unknown")
        self.assertEqual(len(self.calls), 1)

    def test_recipient_binding_required_before_any_external_send(self):
        adapter = EbayMessageAdapter(self.scope, token_provider=self.token,
                                     transport=self.transport, send_enabled=True)
        for recipient in (None, "", "seller-a", "buyer\x00-a", "a" * 513, "bad-\ud800"):
            with self.subTest(recipient=repr(recipient)):
                result = adapter.send_reply("conv-1", "Reply", expected_recipient=recipient)
                self.assertEqual(result["status"], "blocked_recipient_binding")
                self.assertFalse(result["buyer_message_http_attempted"])
        self.assertEqual(self.calls, [])

    def test_only_documented_http_success_codes_are_accepted(self):
        for status in (201, 202, 204, 301, 302, 307, 308):
            with self.subTest(status=status):
                adapter = EbayMessageAdapter(self.scope, token_provider=self.token,
                    transport=lambda request, timeout: (status, {}, b'{"conversations":[]}'), read_enabled=True)
                result = adapter.get_conversations()
                self.assertNotEqual(result["status"], "ok")
                self.assertIsNone(result["conversations"])

    def test_default_transport_never_follows_redirect_or_forwards_authorization(self):
        calls = []
        class SyntheticHTTPS(HTTPSHandler):
            def https_open(self, request):
                calls.append(request)
                response = addinfourl(io.BytesIO(b""),
                    {"Location": "https://other.invalid/token-sink"}, request.full_url, 302)
                response.msg = "Found"
                return response
        def offline_opener(*handlers):
            return build_opener(*handlers, SyntheticHTTPS())
        with patch.object(adapter_module, "build_opener", side_effect=offline_opener):
            adapter = EbayMessageAdapter(self.scope, token_provider=self.token, read_enabled=True)
            result = adapter.get_conversations()
        self.assertNotEqual(result["status"], "ok")
        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0].full_url.startswith("https://api.ebay.com/commerce/message/v1/"))
        self.assertNotIn("Authorization", calls[0].headers)
        self.assertEqual(calls[0].get_header("Authorization"), "Bearer synthetic-not-a-real-token")

    def test_send_body_official_2000_character_boundary(self):
        adapter = EbayMessageAdapter(self.scope, token_provider=self.token, transport=self.transport, send_enabled=True)
        adapter.send_reply("conv-1", "a" * 2000, expected_recipient="buyer-a")
        self.assertEqual(len(self.calls), 1)
        with self.assertRaises(ValueError):
            adapter.send_reply("conv-1", "a" * 2001)
        self.assertEqual(len(self.calls), 1)

    def test_hash_owner_binding_matches_username_not_digest_as_username(self):
        username = "Synthetic-Straße"
        digest = hashlib.sha256(username.casefold().encode("utf-8")).hexdigest()
        scope = MessageScope("company-a", "store-a", digest,
                             owner_binding_kind="sha256_casefold_ebay_username")
        self.assertTrue(scope.matches_owner(username))
        self.assertTrue(scope.matches_owner("SYNTHETIC-STRASSE"))
        self.assertFalse(scope.matches_owner("other-seller"))
        self.assertFalse(scope.matches_owner(digest))
        self.assertFalse(scope.matches_owner(None))
        self.assertTrue(scope.is_incoming_message("buyer-a", username))
        self.assertFalse(scope.is_incoming_message(username, "buyer-a"))
        self.assertFalse(scope.is_incoming_message(username, username.upper()))
        self.assertEqual(scope.as_dict()["owner_binding_kind"], "sha256_casefold_ebay_username")
        self.assertEqual(self.scope.owner_binding_kind, "raw_fixture")
        self.assertTrue(self.scope.matches_owner("SELLER-A"))
        disabled = EbayMessageAdapter(scope, token_provider=lambda scope: self.fail("must not resolve"),
                                      transport=lambda request, timeout: self.fail("must not send"))
        self.assertEqual(disabled.get_conversation("conv-1")["status"], "blocked_read_disabled")
        self.assertEqual(disabled.send_reply("conv-1", "Reply")["status"], "blocked_send_disabled")

    def test_owner_binding_rejects_invalid_hash_modes_and_invalid_provider_username(self):
        digest = hashlib.sha256(b"seller-a").hexdigest()
        for value in (digest.upper(), digest[:-1], "g" * 64, " " + digest, digest + " "):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "invalid_owner_binding"):
                MessageScope("company-a", "store-a", value,
                             owner_binding_kind="sha256_casefold_ebay_username")
        with self.assertRaisesRegex(ValueError, "invalid_owner_binding"):
            MessageScope("company-a", "store-a", "seller-a", owner_binding_kind="unknown")
        for username in ("a" * 513, "seller\x00-a", "seller\n-a"):
            bad_hash = hashlib.sha256(username.casefold().encode()).hexdigest()
            scope = MessageScope("company-a", "store-a", bad_hash,
                                 owner_binding_kind="sha256_casefold_ebay_username")
            self.assertFalse(scope.matches_owner(username))

    def test_token_and_prepared_reply_binding_reject_cross_mode_and_missing_mode(self):
        digest = hashlib.sha256(b"seller-a").hexdigest()
        hashed = MessageScope("company-a", "store-a", digest,
                              owner_binding_kind="sha256_casefold_ebay_username")
        raw = MessageScope("company-a", "store-a", digest)
        self.assertNotEqual(hashed, raw)
        for binding in (raw.as_dict(), {k: v for k, v in hashed.as_dict().items() if k != "owner_binding_kind"}):
            provider = lambda scope: {**self.token(scope), "binding": binding}
            adapter = EbayMessageAdapter(hashed, token_provider=provider, transport=self.transport,
                                         read_enabled=True, send_enabled=True)
            self.assertEqual(adapter.get_conversation("conv-1")["status"], "blocked_token_binding")
            self.assertEqual(adapter.send_reply("conv-1", "Reply", expected_recipient="buyer-a")["status"], "blocked_token_binding")
        raw_adapter = EbayMessageAdapter(raw, token_provider=self.token, transport=self.transport, send_enabled=True)
        prepared = raw_adapter.prepare_reply("conv-1", "Reply", expected_recipient="buyer-a")
        hash_adapter = EbayMessageAdapter(hashed, token_provider=self.token, transport=self.transport, send_enabled=True)
        self.assertEqual(hash_adapter.send_prepared_reply(prepared)["status"], "result_unknown")
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()
