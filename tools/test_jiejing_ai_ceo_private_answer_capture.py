"""Opt-in diagnosis must never become merchant-visible or cross-tenant logging."""
from __future__ import annotations

import json
import gc
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class PrivateAnswerCaptureTests(unittest.TestCase):
    def test_real_chat_retains_failed_answer_privately_before_fallback_only(self):
        from jiejing_saas import ai_ceo_chat as chat
        from jiejing_saas.repository import SaaSRepository
        from jiejing_saas.private_answer_capture import create_private_answer_capture

        class Model:
            model = "offline-private-capture"
            def generate_text(self, **kwargs):
                return {"text":"DIAGNOSTIC_ONLY_SENTINEL：目前没有形成比较结果。", "model_mode":"live_http_model_text",
                        "bounded_empty_answer_recovery":True, "reasoning_content":"DO_NOT_STORE_REASONING"}

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            root = Path(folder)
            repo = SaaSRepository(root / "fixture.sqlite")
            account = repo.create_user_with_company(email="capture@example.test", password="unit-test-only-password", company_name="Private capture")
            identity = dict(user_id=account["user"]["user_id"], company_id=account["company"]["company_id"])
            store = repo.create_store(**identity, payload={"platform":"ebay", "marketplace":"EBAY_US"})
            scope = dict(identity, store_id=store["store_id"], project_key="listing-project-capture")
            now = datetime.now(timezone.utc)
            (root / "control.json").write_text(json.dumps(dict(scope, capture_id="capture_chat", enabled=True,
                approved_at=now.isoformat(), expires_at=(now + timedelta(hours=2)).isoformat())), encoding="utf-8")
            capture = create_private_answer_capture(root=root, **scope, attempt_id="task_capture")
            with patch.dict(os.environ, {"JIEJING_AI_CEO_DEFAULT_WEB_CONTEXT_ENABLED":"false", "JIEJING_AI_CEO_REALTIME_SEARCH_ENABLED":"false"}):
                result = chat.run_ai_ceo_chat(repository=repo, **identity, store_id=store["store_id"],
                    message="比较3个候选商品，不创建Listing或发布。", model_client=Model(), on_answer_rejected=capture)
            stored = (root / "capture_chat.answer.json").read_text(encoding="utf-8")
            self.assertIn("DIAGNOSTIC_ONLY_SENTINEL", stored)
            self.assertNotIn("DO_NOT_STORE_REASONING", stored)
            self.assertNotIn("DIAGNOSTIC_ONLY_SENTINEL", json.dumps(result))
            self.assertNotIn("DEBUG-jj-answer", json.dumps(result))
            del repo
            gc.collect()

    def test_missing_expired_other_scope_or_revoked_consent_never_captures(self):
        from jiejing_saas.private_answer_capture import create_private_answer_capture

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            scope = dict(company_id="company_fixture", user_id="user_fixture",
                         store_id="store_fixture", project_key="listing-project-fixture")
            args = dict(root=root, **scope, attempt_id="task_fixture")
            self.assertIsNone(create_private_answer_capture(**args))
            now = datetime.now(timezone.utc)
            consent = dict(scope, capture_id="capture_scope", enabled=True,
                          approved_at=now.isoformat(), expires_at=(now + timedelta(hours=2)).isoformat())
            control = root / "control.json"
            variants = [{key:"other"} for key in scope] + [
                {"enabled":False}, {"expires_at":(now - timedelta(seconds=1)).isoformat()},
                {"expires_at":(now + timedelta(days=2)).isoformat()}, {"capture_id":"../../capture_elsewhere"}]
            for variant in variants:
                control.write_text(json.dumps({**consent, **variant}), encoding="utf-8")
                self.assertIsNone(create_private_answer_capture(**args), variant)
            control.write_text(json.dumps(consent), encoding="utf-8")
            capture = create_private_answer_capture(**args)
            control.unlink()
            capture({"stage":"initial_quality_rejection", "answer":"do not store"})
            self.assertEqual([], list(root.glob("*.answer.json")))

    def test_answer_redaction_drops_reasoning_credentials_and_non_allowlisted_fields(self):
        from jiejing_saas.private_answer_capture import create_private_answer_capture

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            now = datetime.now(timezone.utc)
            scope = dict(company_id="company_fixture", user_id="user_fixture",
                         store_id="store_fixture", project_key="listing-project-fixture")
            (root / "control.json").write_text(json.dumps(dict(scope, capture_id="capture_redaction", enabled=True,
                approved_at=now.isoformat(), expires_at=(now + timedelta(hours=2)).isoformat())), encoding="utf-8")
            secret = "unit-fixture-credential-value"
            capture = create_private_answer_capture(root=root, **scope, attempt_id="task_fixture")
            capture({"stage":"initial_quality_rejection", "answer":
                '<think>PRIVATE_REASONING_SENTINEL</think>候选比较表。\n'
                + json.dumps({"password": secret, "api_key": secret})
                + '\nAuthorization: Bearer ' + secret,
                "reasoning_content":"PRIVATE_REASONING_FIELD", "user_prompt":"PRIVATE_PROMPT",
                "candidate_count":{"secret":secret}, "blocked_by":["missing_concrete_product_candidates", secret]})
            stored = (root / "capture_redaction.answer.json").read_text(encoding="utf-8")
            for forbidden in (secret, "PRIVATE_REASONING_SENTINEL", "PRIVATE_REASONING_FIELD", "PRIVATE_PROMPT"):
                self.assertNotIn(forbidden, stored)
            self.assertIn("候选比较表", stored)

    def test_approved_scope_captures_one_failure_and_disables_itself(self):
        from jiejing_saas.private_answer_capture import create_private_answer_capture

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            now = datetime.now(timezone.utc)
            scope = dict(company_id="company_fixture", user_id="user_fixture",
                         store_id="store_fixture", project_key="listing-project-fixture")
            consent = dict(scope, capture_id="capture_fixture", enabled=True,
                           approved_at=now.isoformat(), expires_at=(now + timedelta(hours=2)).isoformat())
            (root / "control.json").write_text(json.dumps(consent), encoding="utf-8")
            capture = create_private_answer_capture(root=root, **scope, attempt_id="task_fixture")
            self.assertIsNotNone(capture)
            capture({"answer": "比较结果不完整。", "stage": "initial_quality_rejection",
                     "blocked_by": ["missing_concrete_product_candidates"], "candidate_count": 0,
                     "required_candidate_count": 3, "bounded_empty_answer_recovery": True})
            evidence = json.loads((root / "capture_fixture.answer.json").read_text(encoding="utf-8"))
            self.assertEqual("比较结果不完整。", evidence["answer"])
            self.assertEqual("task_fixture", evidence["attempt_id"])
            self.assertTrue(evidence["bounded_empty_answer_recovery"])
            self.assertFalse((root / "control.json").exists(), "Capture must disable itself after one sample")
            self.assertIsNone(create_private_answer_capture(root=root, **scope, attempt_id="task_next"))
            capture({"answer": "Do not overwrite the first sample", "stage": "initial_quality_rejection"})
            self.assertEqual(evidence, json.loads((root / "capture_fixture.answer.json").read_text(encoding="utf-8")))


if __name__ == "__main__":
    unittest.main()
