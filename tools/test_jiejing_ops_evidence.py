"""Offline OPS projection contracts; no network, runtime credentials or business data."""
import sys
from datetime import datetime, timezone
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from jiejing_saas.owner_launch_control import build_ops_console_evidence


class OpsEvidenceTests(unittest.TestCase):
    def project(self, **kwargs):
        values = dict(backup={}, operational={}, edge={}, readiness={}, release_evidence={}, frontend_version="test-v1")
        return build_ops_console_evidence(**(values | kwargs))

    def test_missing_is_unknown_not_success(self):
        packet = self.project()
        self.assertEqual(packet["backup"]["status"], "unknown")
        self.assertEqual(packet["runtime"]["status"], "unknown")
        self.assertIsNone(packet["readiness"]["production_ready"])
        self.assertEqual(packet["release"]["production_deployment_status"], "not_connected")

    def test_actual_nested_proof_and_expired_evidence(self):
        packet = self.project(backup={"backup_ready_for_paid_launch": False, "blockers": ["restore_drill_overdue"], "restore": {"restore_drill_recorded": True, "restore_drill_fresh": False, "last_restore_drill_at": "2026-08-01T00:00:00Z"}}, operational={"status": "ready", "worker_runtime": {"status": "ready", "heartbeat_status": "idle_no_running_jobs"}, "database_live_probe": {"status": "ready", "message": "private data"}}, readiness={"production_ready": False, "items": [{"key": "backup_restore", "severity": "blocker", "status": "blocked_backup_restore_not_ready", "detail": "private data"}]})
        self.assertEqual(packet["backup"]["restore_status"], "attention_required")
        self.assertEqual(packet["backup"]["pitr_status"], "unknown")
        self.assertEqual(packet["runtime"]["status"], "ready")
        self.assertEqual(packet["runtime"]["worker_status"], "ready")
        self.assertEqual(packet["readiness"]["blockers"][0]["key"], "backup_restore")
        self.assertNotIn("private data", str(packet))

    def test_version_bound_history_is_not_live_deployment(self):
        packet = self.project(release_evidence={"frontend_asset_version": "test-v1", "browser_smoke_passed": True, "public_charging_approved": True})
        self.assertTrue(packet["release"]["version_bound_evidence"])
        self.assertEqual(packet["release"]["production_deployment_status"], "not_connected")
        self.assertEqual(self.project(release_evidence={"frontend_asset_version": "old", "browser_smoke_passed": True})["release"]["version_bound_evidence"], False)

    def test_runtime_receipt_requires_matching_build_and_verified_apply(self):
        build = {"contract_version": "jiejing_runtime_build_v1", "source_commit": "a" * 40}
        applied = {"contract_version": "jiejing_applied_release_v1", "source_commit": "a" * 40,
                   "verified_at": datetime.now(timezone.utc).isoformat(),
                   "applied": True, "public_health_verified": True, "secret_exposed": False}
        release = self.project(runtime_build=build, deployment_receipt=applied)["release"]
        self.assertEqual(release["production_deployment_status"], "ready")
        self.assertEqual(release["source_commit"], "a" * 40)
        for change in ({"source_commit": "b" * 40}, {"applied": False}, {"applied": "true"},
                       {"public_health_verified": False}, {"secret_exposed": True},
                       {"verified_at": "2099-01-01T00:00:00Z"}, {"verified_at": "not-a-date"}):
            with self.subTest(change=change):
                rejected = self.project(runtime_build=build, deployment_receipt=applied | change)["release"]
                self.assertNotEqual(rejected["production_deployment_status"], "ready")
                self.assertEqual(rejected["source_commit"], "a" * 40)
        self.assertNotEqual(self.project(deployment_receipt=applied)["release"]["production_deployment_status"], "ready")

    def test_deployment_projection_never_returns_raw_paths_or_extra_fields(self):
        packet = self.project(runtime_build={"contract_version": "jiejing_runtime_build_v1", "source_commit": "unsafe/path"},
                              deployment_receipt={"raw": "private-value", "path": "/private/sensitive"})
        self.assertEqual(packet["release"]["source_commit"], "")
        self.assertNotIn("private-value", str(packet))
        self.assertNotIn("/private", str(packet))


if __name__ == "__main__":
    unittest.main()
