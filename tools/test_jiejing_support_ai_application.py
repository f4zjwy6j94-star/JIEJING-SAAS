"""Synthetic AI proposal-to-draft slice on the existing support application."""
from dataclasses import replace
import unittest
from unittest.mock import Mock, patch

from tools import test_jiejing_support_application as fixtures
from tools import test_jiejing_support_ai_decision as decisions
from jiejing_saas.support_application import SupportApplication


class SupportAiApplicationTests(unittest.TestCase):
    context = fixtures.SupportApplicationTests.context

    def setUp(self):
        fixtures.SupportApplicationTests.setUp(self)
        from jiejing_saas.support_ai_decision import SupportKnowledge, SupportFact
        self.service.ingest(self.incoming)
        self.knowledge = SupportKnowledge(scope=self.scope, conversation_id="conv-1",
            product_binding="synthetic-item-1", fact_version="fact-report-1", policy_version="policy-1",
            facts=(SupportFact("color", "Blue", "merchant_confirmed", "fact-report-1"),
                   SupportFact("drawers", "Two drawers", "merchant_confirmed", "fact-report-1")))
        self.script = decisions.SupportAiDecisionTests()
        self.script.setUp()
        self.model = decisions.ScriptedModel(self.script.answer, self.script.review)
        self.loader = Mock(return_value=self.knowledge)
        self.factory = Mock(return_value=self.model)

    def app(self, enabled=True):
        return SupportApplication(self.repo, enabled=True, ai_enabled=enabled,
            ai_knowledge_loader=self.loader, ai_model_factory=self.factory)

    def count_drafts(self):
        with self.repo._connect() as conn:
            return conn.execute("select count(*) from support_drafts_v1").fetchone()[0]

    def test_ai_is_off_by_default_and_request_cannot_supply_model_facts_or_scope(self):
        self.assertEqual(self.app(False).propose_ai_reply(self.context(), {"conversation_id": "conv-1"})["blocked_by"],
                         ["support_ai_disabled"])
        self.loader.assert_not_called()
        self.factory.assert_not_called()
        for key in ("facts", "store_id", "model_client", "approved", "source_message_id", "send_enabled"):
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.app().propose_ai_reply(self.context(), {"conversation_id": "conv-1", key: "injected"})

    def test_bound_ai_reply_persists_reviewed_draft_without_confirmation_or_send(self):
        with patch.object(self.repo, "initialize", side_effect=AssertionError("no implicit DDL")), \
             patch("socket.socket", side_effect=AssertionError("no provider socket")):
            result = self.app().propose_ai_reply(self.context(), {"conversation_id": "conv-1"})
        self.assertEqual(result["status"], "reply_candidate")
        draft = self.service.get_draft(result["draft"]["draft_id"])
        self.assertEqual(draft["body"], "It is blue and has two drawers.")
        self.assertEqual(draft["generation_kind"], "ai_reviewed_draft_not_authorization")
        self.assertEqual(draft["ai_review"]["fact_version"], "fact-report-1")
        self.assertEqual(draft["ai_review"]["binding_hash"], result["binding_hash"])
        self.assertEqual(self.loader.call_count, 2)
        self.assertFalse(result["automatic_send_allowed"])
        self.assertFalse(result["message_sent"])
        with self.repo._connect() as conn:
            self.assertEqual(conn.execute("select count(*) from confirmations").fetchone()[0], 0)
            self.assertEqual(conn.execute("select count(*) from support_send_intents_v1").fetchone()[0], 0)

    def test_missing_or_foreign_product_binding_hands_off_before_model(self):
        for value in (None, replace(self.knowledge, conversation_id="other-conversation"),
                      replace(self.knowledge, product_binding=""), {"facts": "from-browser"}):
            with self.subTest(value=value):
                self.loader.return_value = value
                result = self.app().propose_ai_reply(self.context(), {"conversation_id": "conv-1"})
                self.assertEqual(result["status"], "human_required")
        self.factory.assert_not_called()
        self.assertEqual(self.count_drafts(), 0)

    def test_changed_fact_or_policy_version_during_model_call_discards_candidate(self):
        for key in ("fact_version", "policy_version", "product_binding"):
            with self.subTest(key=key):
                self.model.responses = [self.script.answer, self.script.review]
                self.loader.side_effect = [self.knowledge, replace(self.knowledge, **{key: "new-value"})]
                result = self.app().propose_ai_reply(self.context(), {"conversation_id": "conv-1"})
                self.assertEqual(result["status"], "blocked")
                self.assertIn("support_ai_context_changed", result["blocked_by"])
        self.assertEqual(self.count_drafts(), 0)

    def test_new_message_during_model_call_and_removed_actor_block_persistence(self):
        original = self.model.generate_text
        def add_message(**kwargs):
            result = original(**kwargs)
            self.service.ingest({**self.incoming, "messages": [*self.incoming["messages"],
                {**self.incoming["messages"][0], "messageId": "m2", "createdDate": "2026-10-12T00:01:00Z",
                 "messageBody": "Actually I want to return it."}]})
            return result
        self.model.generate_text = add_message
        result = self.app().propose_ai_reply(self.context(), {"conversation_id": "conv-1"})
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(self.count_drafts(), 0)
        self.fixture.sql("update users set status='disabled' where user_id=?", (self.fixture.user,))
        self.factory.reset_mock()
        with self.assertRaises(PermissionError):
            self.app().propose_ai_reply(self.context(), {"conversation_id": "conv-1"})
        self.factory.assert_not_called()

    def test_human_edit_invalidates_prior_ai_review(self):
        app = self.app()
        result = app.propose_ai_reply(self.context(), {"conversation_id": "conv-1"})
        draft_id = result["draft"]["draft_id"]
        app.edit_draft(self.context(), draft_id, {"expected_revision": 1, "body": "Manually revised reply"})
        changed = self.service.get_draft(draft_id)
        self.assertNotIn("ai_review", changed)
        self.assertEqual(changed["generation_kind"], "editable_draft_not_automatic_reply")
        self.assertIn("ai_review", self.service.draft_history(draft_id)[0])

    def test_semantic_handoff_creates_no_sendable_draft(self):
        self.model.responses = [{**self.script.answer, "disposition": "handoff", "risk_reasons": ["refund"], "sentences": []}]
        result = self.app().propose_ai_reply(self.context(), {"conversation_id": "conv-1"})
        self.assertEqual(result["status"], "human_required")
        self.assertEqual(result["body"], "")
        self.assertEqual(self.count_drafts(), 0)


if __name__ == "__main__":
    unittest.main()
