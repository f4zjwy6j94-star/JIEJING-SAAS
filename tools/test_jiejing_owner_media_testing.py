#!/usr/bin/env python3
"""Contracts for the private, auditable owner media-testing allowance."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.media_credits import (  # noqa: E402
    OWNER_MEDIA_TESTING_POINTS,
    OWNER_MEDIA_TESTING_SOURCE,
    grant_owner_media_testing_points,
)
from jiejing_saas.api_server import _reserve_ops_media_points  # noqa: E402
from jiejing_saas.repository import SaaSRepository  # noqa: E402


CLI_PATH = ROOT / "tools" / "jiejing_owner_media_testing.py"


class OwnerMediaTestingContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="jiejing-owner-media-testing-", ignore_cleanup_errors=True)
        self.repository = SaaSRepository(Path(self.temp.name) / "saas.sqlite", database_engine="sqlite")
        fixture = self.repository.create_user_with_company(
            email="owner-media-testing@example.test",
            password="local-test-password",
            company_name="Owner media testing contract",
        )
        self.company_id = fixture["company"]["company_id"]
        self.user_id = fixture["user"]["user_id"]
        self.email = fixture["user"]["email"]

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_allowlisted_owner_gets_one_fixed_auditable_testing_allowance(self) -> None:
        safe_env = {
            "JIEJING_OWNER_MEDIA_TESTING_ENABLED": "true",
            "JIEJING_OWNER_MEDIA_TESTING_COMPANY_ALLOWLIST": self.company_id,
        }
        with patch.dict(os.environ, safe_env, clear=False):
            first = grant_owner_media_testing_points(
                self.repository,
                account_email=self.email,
                expected_company_id=self.company_id,
            )
            replay = grant_owner_media_testing_points(
                self.repository,
                account_email=self.email,
                expected_company_id=self.company_id,
            )

        self.assertTrue(first.get("ok"), first)
        self.assertEqual(OWNER_MEDIA_TESTING_POINTS, first.get("points_granted"))
        self.assertEqual(OWNER_MEDIA_TESTING_SOURCE, first.get("credit_source"))
        self.assertFalse(first.get("external_provider_action_triggered"))
        self.assertFalse(first.get("public_charging_allowed"))
        self.assertFalse(first.get("secret_exposed"))
        self.assertTrue(replay.get("duplicate_request"), replay)

        account = self.repository.get_media_credit_account(company_id=self.company_id)
        self.assertEqual(OWNER_MEDIA_TESTING_POINTS, account.get("owner_testing_points"))
        self.assertEqual(0, account.get("purchased_points"))
        grants = [
            item
            for item in self.repository.list_media_credit_ledger(company_id=self.company_id, limit=100)
            if item.get("operation_type") == "grant"
            and item.get("reference_type") == OWNER_MEDIA_TESTING_SOURCE
        ]
        self.assertEqual(1, len(grants))
        audits = [
            item
            for item in self.repository.list_audit_logs(company_id=self.company_id, limit=100)
            if item.get("action_type") == "media_credit.owner_testing.granted"
        ]
        self.assertEqual(1, len(audits))

    def test_owner_allowance_is_reserved_before_the_expired_acceptance_path(self) -> None:
        safe_env = {
            "JIEJING_OWNER_MEDIA_TESTING_ENABLED": "true",
            "JIEJING_OWNER_MEDIA_TESTING_COMPANY_ALLOWLIST": self.company_id,
            "JIEJING_CONTROLLED_MEDIA_ACCEPTANCE_ENABLED": "true",
            "JIEJING_CONTROLLED_MEDIA_ACCEPTANCE_COMPANY_ALLOWLIST": self.company_id,
        }
        with patch.dict(os.environ, safe_env, clear=False):
            grant_owner_media_testing_points(
                self.repository,
                account_email=self.email,
                expected_company_id=self.company_id,
            )
            reserved = _reserve_ops_media_points(
                self.repository,
                company_id=self.company_id,
                user_id=self.user_id,
                media_idempotency_key="owner-media-testing-job-v1",
                media_quote={"estimated_points": 80},
            )

        self.assertIsNotNone(reserved)
        entry = (reserved or {}).get("ledger_entry", {})
        self.assertEqual("reserve", entry.get("operation_type"))
        self.assertEqual(80, entry.get("points"))
        allocations = entry.get("details", {}).get("allocations", [])
        self.assertEqual(1, len(allocations))
        bucket = self.repository.get_media_credit_source(
            company_id=self.company_id,
            source_type=OWNER_MEDIA_TESTING_SOURCE,
        )
        self.assertEqual(80, (bucket or {}).get("reserved_points"))

    def test_private_cli_has_no_points_ttl_or_source_override(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(CLI_PATH), "--help"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=20,
            check=False,
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertIn("--account-email", completed.stdout)
        self.assertIn("--expected-company-id", completed.stdout)
        self.assertNotIn("--points", completed.stdout)
        self.assertNotIn("--ttl", completed.stdout)
        self.assertNotIn("--source", completed.stdout)

    def test_settings_labels_owner_points_without_calling_them_purchased(self) -> None:
        frontend = (ROOT / "app.js").read_text(encoding="utf-8")
        self.assertIn("account.owner_testing_points", frontend)
        self.assertIn("内部测试额度", frontend)

    def test_generic_media_reserve_cannot_consume_private_owner_allowance(self) -> None:
        safe_env = {
            "JIEJING_OWNER_MEDIA_TESTING_ENABLED": "true",
            "JIEJING_OWNER_MEDIA_TESTING_COMPANY_ALLOWLIST": self.company_id,
        }
        with patch.dict(os.environ, safe_env, clear=False):
            grant_owner_media_testing_points(
                self.repository,
                account_email=self.email,
                expected_company_id=self.company_id,
            )
        with self.assertRaisesRegex(ValueError, "insufficient available media points"):
            self.repository.apply_media_credit_operation(
                company_id=self.company_id,
                user_id=self.user_id,
                operation_type="reserve",
                points=20,
                idempotency_key="generic-reserve-must-not-use-owner-testing-v1",
                reference_type="media_job",
                reference_id="generic-owner-testing-job",
            )

    def test_media_rework_uses_the_same_private_owner_reservation_path_as_initial_generation(self) -> None:
        api_source = (ROOT / "jiejing_saas" / "api_server.py").read_text(encoding="utf-8")
        retry_start = api_source.index(
            'if len(parts) == 3 and parts[0] == "media-asset-jobs" and parts[2] == "retry":'
        )
        retry_end = api_source.index(
            'if len(parts) == 3 and parts[0] == "queue-jobs" and parts[2] == "retry":',
            retry_start,
        )
        retry_source = api_source[retry_start:retry_end]
        self.assertIn("ops_reservation = _reserve_ops_media_points(", retry_source)
        self.assertLess(
            retry_source.index("ops_reservation = _reserve_ops_media_points("),
            retry_source.index("self.repository.apply_media_credit_operation("),
            "owner testing points must be considered before the generic purchased/plan bucket path",
        )


if __name__ == "__main__":
    unittest.main()
