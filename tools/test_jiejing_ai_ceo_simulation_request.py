#!/usr/bin/env python3
"""Public planner boundary for one-way, explicitly requested simulation."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from jiejing_saas.ai_ceo_semantic_plan import SemanticPlanError, plan_ai_ceo_turn
from tools.test_jiejing_ai_ceo_semantic_dispatch import ModelFixture, decision


class SimulationRequestTests(unittest.TestCase):
    def plan(self, request=None, *, message="这组数据仅用于内部模拟。", changes=None, current=None, omit=False):
        payload = decision(read_images=False, **(changes or {}))
        if not omit:
            payload["simulation_request"] = request
        return plan_ai_ceo_turn(model_client=ModelFixture(payload), message=message,
            conversation_history=[], active_listing_context=current or {}, has_source_assets=False)

    def test_explicit_request_is_typed_and_auditable_without_fact_proposals(self):
        request = {"enabled": True, "source_quote": "仅用于内部模拟"}
        plan = self.plan(request)
        self.assertEqual(request, plan["simulation_request"])
        self.assertEqual([], plan["product_fact_proposals"])
        self.assertFalse(plan["real_platform_writes_enabled"])

    def test_omitted_or_null_request_does_not_infer_simulation_from_words(self):
        for message in ("不要设置内部模拟。", "供应商说‘内部模拟’，解释这句话。", "采用上一组。"):
            for omit in (True, False):
                with self.subTest(message=message, omit=omit):
                    self.assertIsNone(self.plan(message=message, omit=omit)["simulation_request"])

    def test_invalid_types_quotes_authority_or_secret_are_rejected(self):
        invalid = [False, True, [], "true", {},
            {"enabled": False, "source_quote": "仅用于内部模拟"},
            {"enabled": 1, "source_quote": "仅用于内部模拟"},
            {"enabled": "true", "source_quote": "仅用于内部模拟"},
            {"enabled": True, "source_quote": ""},
            {"enabled": True, "source_quote": " "},
            {"enabled": True, "source_quote": False},
            {"enabled": True, "source_quote": "没有本条出处"},
            {"enabled": True, "source_quote": "仅用于内部模拟", "image_rights_confirmed": True},
            {"enabled": True, "source_quote": "仅用于内部模拟", "project_id": "forged"},
        ]
        for index, request in enumerate(invalid):
            with self.subTest(case=index), self.assertRaisesRegex(SemanticPlanError, "semantic_plan_invalid_simulation_request"):
                self.plan(request)
        with self.assertRaisesRegex(SemanticPlanError, "semantic_plan_invalid_simulation_request"):
            self.plan({"enabled": True, "source_quote": "字" * 161}, message="字" * 161)
        sensitive = "api_" + "key=fake-simulation-fixture"
        with self.assertRaisesRegex(SemanticPlanError, "semantic_plan_sensitive_simulation_request"):
            self.plan({"enabled": True, "source_quote": sensitive}, message=sensitive)

    def test_request_requires_ready_target_and_artifact(self):
        request = {"enabled": True, "source_quote": "仅用于内部模拟"}
        for changes in ({"status": "clarification_required"}, {"project_action": "none"},
                        {"project_action": "clarify"}, {"save_artifact": False}):
            with self.subTest(changes=changes), self.assertRaisesRegex(SemanticPlanError, "semantic_plan_unrequested_simulation_request"):
                self.plan(request, changes=changes)
        plan = self.plan(request, changes={"project_action": "current"})
        self.assertEqual("clarification_required", plan["status"])
        self.assertIsNone(plan["simulation_request"])
        self.assertFalse(plan["save_artifact"])


if __name__ == "__main__":
    unittest.main()
