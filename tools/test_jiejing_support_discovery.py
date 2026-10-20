"""Discover synthetic incoming conversation IDs from an initially empty cache."""
import json
import unittest
from unittest.mock import patch

from tools.test_jiejing_support_application import SupportApplicationTests as Fixture
from jiejing_saas.support_application import SupportApplication


class SupportDiscoveryTests(unittest.TestCase):
    setUp = Fixture.setUp
    context = Fixture.context
    resolver = Fixture.resolver

    def response(self, entries=None, **extra):
        return (200, {}, json.dumps({"conversations": entries if entries is not None else [
            {"conversationId": "new-conversation", "conversationType": "FROM_MEMBERS",
             "latestMessage": {"messageBody": "must-not-project", "senderUsername": "synthetic-buyer"}}], **extra}).encode())

    def app(self):
        return SupportApplication(self.repo, enabled=True, sync_enabled=True, resolver=self.resolver())

    def test_empty_cache_can_discover_ids_without_ingesting_unverified_list_messages(self):
        app = self.app()
        self.assertEqual(app.list_conversations(self.context())["conversations"], [])
        with patch("jiejing_saas.ebay_message_adapter.message_http_transport", return_value=self.response()) as network:
            result = app.discover(self.context(), {})
        self.assertEqual(result["conversation_ids"], ["new-conversation"])
        self.assertEqual(result["status"], "discovered")
        self.assertFalse(result["has_more"])
        self.assertIsNone(result["next_offset"])
        self.assertTrue(result["buyer_message_http_attempted"])
        self.assertFalse(result["send_enabled"])
        self.assertEqual(network.call_count, 1)
        self.assertEqual(app.list_conversations(self.context())["conversations"], [])
        for forbidden in ("must-not-project", "synthetic-buyer", self.scope.owner_id, self.fixture.ref):
            self.assertNotIn(forbidden, json.dumps(result))

    def test_explicit_pagination_returns_continuation_without_following_provider_url(self):
        with patch("jiejing_saas.ebay_message_adapter.message_http_transport", return_value=self.response(
                next="https://outside.invalid/not-to-follow")) as network:
            result = self.app().discover(self.context(), {"limit": 25, "max_pages": 2, "offset": 50})
        self.assertTrue(result["has_more"])
        self.assertEqual(result["next_offset"], 100)
        urls = [call.args[0].full_url for call in network.call_args_list]
        self.assertIn("offset=50", urls[0])
        self.assertIn("offset=75", urls[1])
        self.assertTrue(all(url.startswith("https://api.ebay.com/commerce/message/v1/conversation?") for url in urls))
        self.assertEqual(result["conversation_ids"], ["new-conversation"])

    def test_disabled_wrong_actor_and_forged_configuration_make_no_external_call(self):
        with patch("jiejing_saas.ebay_message_adapter.message_http_transport", side_effect=AssertionError("no I/O")):
            self.assertEqual(SupportApplication(self.repo).discover(self.context(), {})["blocked_by"],
                             ["support_application_disabled"])
            self.assertEqual(SupportApplication(self.repo, enabled=True).discover(self.context(), {})["blocked_by"],
                             ["support_sync_disabled"])
            with self.assertRaises(PermissionError):
                self.app().discover(self.context(actor_id="foreign-user"), {})
            for bad in ({"access_token": "injected"}, {"company_id": "other"}, {"offset": True},
                        {"limit": 51}, {"max_pages": 4}, {"offset": -1}, {"offset": 10001}):
                with self.subTest(bad=bad), self.assertRaises(ValueError):
                    self.app().discover(self.context(), bad)

    def test_late_response_after_connection_change_or_actor_removal_is_not_returned(self):
        for revoke_actor in (False, True):
            with self.subTest(revoke_actor=revoke_actor):
                def response(*args):
                    if revoke_actor:
                        self.fixture.sql("update users set status='disabled' where user_id=?", (self.fixture.user,))
                    else:
                        self.fixture.sql("update platform_connections set status='revoked' where connection_id=?",
                                         (self.fixture.connection_id,))
                    return self.response()
                with patch("jiejing_saas.ebay_message_adapter.message_http_transport", side_effect=response):
                    if revoke_actor:
                        with self.assertRaises(PermissionError):
                            self.app().discover(self.context(), {})
                    else:
                        self.assertEqual(self.app().discover(self.context(), {})["status"], "blocked")
                self.fixture.sql("update platform_connections set status='read_only_authorized' where connection_id=?",
                                 (self.fixture.connection_id,))
                self.fixture.sql("update users set status='active' where user_id=?", (self.fixture.user,))

    def test_invalid_identifier_or_wrong_conversation_kind_fails_closed(self):
        for entries in ([{"conversationId": "../other"}], [{"conversationId": ""}], [{"conversationId": 123}],
                        [{"conversationId": "new", "conversationType": "FROM_EBAY"}], [{}]):
            with self.subTest(entries=entries), patch("jiejing_saas.ebay_message_adapter.message_http_transport",
                                                    return_value=self.response(entries)):
                result = self.app().discover(self.context(), {})
                self.assertEqual(result["status"], "blocked")
                self.assertNotIn("conversation_ids", result)

    def test_empty_page_with_next_is_not_an_infinite_cursor(self):
        with patch("jiejing_saas.ebay_message_adapter.message_http_transport",
                   return_value=self.response([], next="https://api.ebay.com/next")) as network:
            result = self.app().discover(self.context(), {"max_pages": 3})
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(network.call_count, 1)


if __name__ == "__main__":
    unittest.main()
