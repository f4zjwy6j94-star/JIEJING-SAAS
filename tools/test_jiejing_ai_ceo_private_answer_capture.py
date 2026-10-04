"""Temporary consent scope and private-output boundary regressions."""
from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from jiejing_saas.private_answer_capture import create_private_answer_capture


class PrivateAnswerCaptureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="jiejing-private-diagnostic-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.scope = dict(company_id="company-test", user_id="user-test", store_id="store-test",
                          project_key="project-test", message="一次指定的测试报告", attempt_id="attempt-test")
        now = datetime.now(timezone.utc)
        self.consent = {**{k: self.scope[k] for k in ("company_id", "user_id", "store_id", "project_key")},
            "capture_id": "capture_test", "enabled": True,
            "message_sha256": hashlib.sha256(self.scope["message"].encode()).hexdigest(),
            "approved_at": now.isoformat(), "expires_at": (now + timedelta(minutes=2)).isoformat()}

    def enable(self):
        target = self.root / "control.json"
        target.write_text(json.dumps(self.consent), encoding="utf-8")
        target.chmod(0o600)

    def event(self, stage="initial"):
        return {"stage": stage, "answer": "当前在售。测试内容。", "accepted": False,
            "blocked_by": ["research_unverified_current_availability"],
            "semantic_plan": {"intent": "research", "query": "test", "secret_key": "not-to-be-saved"},
            "source_records": [{"citation_id": "S1", "url": "https://www.ebay.com/itm/123456789012",
                "title": "Test", "snippet": "US $5.99", "cookie": "not-to-be-saved"}]}

    def test_default_off_and_exact_scope_including_message(self):
        self.assertIsNone(create_private_answer_capture(root=self.root, **self.scope))
        self.enable()
        for field in ("company_id", "user_id", "store_id", "project_key", "message"):
            with self.subTest(field=field):
                self.assertIsNone(create_private_answer_capture(root=self.root, **{**self.scope, field:"different"}))
        self.assertIsNotNone(create_private_answer_capture(root=self.root, **self.scope))
        self.assertEqual(["control.json"], sorted(x.name for x in self.root.iterdir()))

    def test_expired_future_or_overlong_consent_does_not_capture(self):
        now = datetime.now(timezone.utc)
        for start, end in ((-3,-1),(1,2),(-1,180)):
            self.consent.update(approved_at=(now + timedelta(minutes=start)).isoformat(),
                                expires_at=(now + timedelta(minutes=end)).isoformat())
            self.enable()
            self.assertIsNone(create_private_answer_capture(root=self.root, **self.scope))

    def test_only_one_request_can_claim_and_only_two_ordered_attempts_are_saved(self):
        self.enable()
        winner = create_private_answer_capture(root=self.root, **self.scope)
        other = create_private_answer_capture(root=self.root, **{**self.scope,"attempt_id":"other"})
        winner(self.event("repair"))  # No initial result: no claim.
        self.assertTrue((self.root / "control.json").exists())
        winner(self.event())
        other(self.event())
        winner(self.event("repair"))
        winner(self.event("repair"))
        sample = json.loads((self.root / "capture_test.answer.json").read_text(encoding="utf-8"))
        self.assertEqual("attempt-test", sample["attempt_id"])
        self.assertEqual(["initial", "repair"], [x["stage"] for x in sample["attempts"]])
        self.assertNotIn("not-to-be-saved", json.dumps(sample))
        self.assertFalse((self.root / "control.json").exists())
        self.enable()  # Cannot silently reuse consumed consent.
        self.assertIsNone(create_private_answer_capture(root=self.root, **self.scope))

    def test_revocation_before_initial_and_between_attempts_is_effective(self):
        self.enable()
        sink = create_private_answer_capture(root=self.root, **self.scope)
        (self.root / "control.json").unlink()
        sink(self.event())
        self.assertFalse((self.root / "capture_test.answer.json").exists())
        self.enable()
        sink = create_private_answer_capture(root=self.root, **self.scope)
        sink(self.event())
        original = (self.root / "capture_test.answer.json").read_bytes()
        (self.root / "capture_test.consumed.json").rename(self.root / "capture_test.disabled.json")
        sink(self.event("repair"))
        self.assertEqual(original, (self.root / "capture_test.answer.json").read_bytes())

    def test_provider_reasoning_credentials_and_email_are_not_saved(self):
        self.enable()
        sink = create_private_answer_capture(root=self.root, **self.scope)
        event = self.event()
        event["answer"] = ('<think>private-thought</think>\n价格 $5.99。 '
            'password="fixture-private-value" api_key="fixture-private-key" person@example.test。')
        sink(event)
        text = (self.root / "capture_test.answer.json").read_text(encoding="utf-8")
        for private in ("private-thought", "fixture-private-value", "fixture-private-key", "person@example.test"):
            self.assertNotIn(private, text)
        self.assertIn("$5.99", text)

    @unittest.skipUnless(os.name == "posix", "POSIX filesystem modes")
    def test_shared_control_or_directory_is_not_accepted(self):
        self.enable()
        (self.root / "control.json").chmod(0o644)
        self.assertIsNone(create_private_answer_capture(root=self.root, **self.scope))
        (self.root / "control.json").chmod(0o600)
        self.root.chmod(0o755)
        self.assertIsNone(create_private_answer_capture(root=self.root, **self.scope))

    def test_malformed_or_symlink_control_is_rejected_without_logging(self):
        self.enable()
        (self.root / "control.json").write_text('{"enabled":true', encoding="utf-8")
        self.assertIsNone(create_private_answer_capture(root=self.root, **self.scope))
        self.consent["capture_id"] = "../escape"
        self.enable()
        self.assertIsNone(create_private_answer_capture(root=self.root, **self.scope))


if __name__ == "__main__":
    unittest.main()
