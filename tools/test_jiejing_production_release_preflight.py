"""Offline release evidence/preflight contract; never run the deployment script.

Receipt writes use synthetic temporary files only. Preflight tests clear the
environment and forbid database/network/write boundaries; no production env,
customer records, provider calls or backup-evidence refresh are performed.
"""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SPEC = importlib.util.spec_from_file_location(
    "production_release_evidence_test_target", ROOT / "tools/jiejing_production_release_evidence.py"
)
RELEASE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RELEASE)


class ReleaseReceiptTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="release-preflight-fixture-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        # Filesystem ownership is the boundary; portable fixtures are not root-owned.
        self.owner = mock.patch.object(RELEASE, "trusted_owner", return_value=True)
        self.owner.start()
        self.addCleanup(self.owner.stop)

    def test_build_receipt_is_immutable_and_failed_rewrite_preserves_bytes(self):
        target = self.root / "JIEJING_RUNTIME_BUILD.safe.json"
        RELEASE.write_receipt(target, "a" * 40, applied=False)
        original = target.read_bytes()
        self.assertEqual(json.loads(original), {
            "contract_version": "jiejing_runtime_build_v1", "source_commit": "a" * 40,
        })
        with self.assertRaisesRegex(ValueError, "build_identity_already_exists"):
            RELEASE.write_receipt(target, "b" * 40, applied=False)
        self.assertEqual(target.read_bytes(), original)
        self.assertEqual(list(self.root.iterdir()), [target])

    def test_applied_replacement_retains_each_previous_original(self):
        target = self.root / "deployment.safe.json"
        RELEASE.write_receipt(target, "a" * 40, applied=True)
        first = target.read_bytes()
        RELEASE.write_receipt(target, "b" * 40, applied=True)
        second = target.read_bytes()
        RELEASE.write_receipt(target, "c" * 40, applied=True)
        backups = list(self.root.glob("deployment.previous-*.safe.json"))
        self.assertEqual(len(backups), 2)
        self.assertEqual({item.read_bytes() for item in backups}, {first, second})
        result = json.loads(target.read_bytes())
        self.assertEqual(result["source_commit"], "c" * 40)
        self.assertTrue(result["applied"])
        self.assertTrue(result["public_health_verified"])
        self.assertFalse(result["secret_exposed"])
        self.assertEqual(list(self.root.glob(".release-receipt-*")), [])

    def test_invalid_source_identity_is_rejected_without_creating_files(self):
        for invalid in ("", "a" * 39, "a" * 41, "A" * 40, "g" * 40, "a" * 64, "a" * 40 + "\n"):
            with self.subTest(identity_length=len(invalid)), self.assertRaisesRegex(ValueError, "source_identity_invalid"):
                RELEASE.write_receipt(self.root / "deployment.safe.json", invalid, applied=True)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_invalid_output_name_or_relative_path_is_rejected(self):
        for target in (self.root / "other.json", Path("deployment.safe.json")):
            with self.subTest(path_type="absolute" if target.is_absolute() else "relative"), self.assertRaisesRegex(ValueError, "receipt_path_invalid"):
                RELEASE.write_receipt(target, "a" * 40, applied=True)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_untrusted_parent_is_rejected_before_receipt_write(self):
        target = self.root / "deployment.safe.json"
        with mock.patch.object(RELEASE, "trusted_owner", return_value=False), self.assertRaisesRegex(ValueError, "receipt_directory_not_trusted"):
            RELEASE.write_receipt(target, "a" * 40, applied=True)
        self.assertFalse(target.exists())

    def test_symlink_receipt_is_rejected_without_read_or_replacement(self):
        # A synthetic lstat response avoids requiring Windows symlink privileges.
        # The implementation must reject the file type before reading its content.
        target = self.root / "deployment.safe.json"
        original = b'{"synthetic":"unchanged"}\n'
        target.write_bytes(original)
        real_lstat = Path.lstat
        with mock.patch.object(Path, "lstat", autospec=True, side_effect=lambda path: (
            SimpleNamespace(st_mode=stat.S_IFLNK | 0o777) if path == target else real_lstat(path)
        )), mock.patch.object(Path, "read_bytes", side_effect=AssertionError("must not read link target")), \
             mock.patch.object(RELEASE.os, "replace", side_effect=AssertionError("must not replace link")), \
             self.assertRaisesRegex(ValueError, "existing_receipt_not_trusted"):
            RELEASE.write_receipt(target, "a" * 40, applied=True)
        self.assertEqual(target.read_bytes(), original)
        self.assertEqual(list(self.root.iterdir()), [target])


class ColdStartPreflightTests(unittest.TestCase):
    def test_synthetic_ready_production_control_passes_without_refresh(self):
        with mock.patch.dict(os.environ, {"JIEJING_WECHAT_PAY_CHARGE_ALLOWED": "true"}, clear=True), \
             mock.patch("jiejing_saas.config.SaaSSettings.from_env", return_value=SimpleNamespace(is_production_like=True)), \
             mock.patch("jiejing_saas.backup_plan.build_backup_plan", return_value={
                 "backup_ready_for_paid_launch": True, "blockers": [],
             }):
            result = RELEASE.backup_cold_start_preflight()
            self.assertTrue(result["passed"])
            self.assertTrue(result["backup_ready"])
            self.assertFalse(result["evidence_refreshed"])
            self.assertFalse(result["business_database_accessed"])

    def test_charge_or_refund_enabled_requires_literal_paid_backup_readiness(self):
        for flag in ("JIEJING_WECHAT_PAY_CHARGE_ALLOWED", "JIEJING_WECHAT_PAY_REFUND_ALLOWED"):
            for not_ready in (False, None, 1, "true"):
                with self.subTest(flag=flag, readiness=not_ready), mock.patch.dict(os.environ, {flag: "true"}, clear=True), \
                     mock.patch("jiejing_saas.config.SaaSSettings.from_env", return_value=SimpleNamespace(is_production_like=True)), \
                     mock.patch("jiejing_saas.backup_plan.build_backup_plan", return_value={
                         "backup_ready_for_paid_launch": not_ready, "blockers": ["restore_drill_overdue"],
                     }) as plan:
                    before = dict(os.environ)
                    result = RELEASE.backup_cold_start_preflight()
                    self.assertFalse(result["passed"])
                    self.assertTrue(result["money_enabled"])
                    self.assertFalse(result["backup_ready"])
                    self.assertEqual(result["blockers"], ["restore_drill_overdue"])
                    self.assertFalse(result["evidence_refreshed"])
                    self.assertFalse(result["business_database_accessed"])
                    self.assertEqual(plan.call_args.args[1].system_counts(), {})
                    self.assertEqual(dict(os.environ), before)

    def test_real_settings_without_evidence_fail_closed_without_io(self):
        # Clear all inherited provider, DB and evidence settings before real evaluation.
        from jiejing_saas.config import SaaSSettings  # noqa: F401
        from jiejing_saas.backup_plan import build_backup_plan  # noqa: F401
        with mock.patch.dict(os.environ, {
            "JIEJING_SAAS_ENV": "production", "JIEJING_WECHAT_PAY_CHARGE_ALLOWED": "true",
        }, clear=True), contextlib.ExitStack() as guards:
            for target in ("sqlite3.connect", "socket.create_connection", "pathlib.Path.open",
                           "pathlib.Path.write_text", "pathlib.Path.write_bytes", "os.replace"):
                guards.enter_context(mock.patch(target, side_effect=AssertionError("preflight IO forbidden")))
            before = dict(os.environ)
            result = RELEASE.backup_cold_start_preflight()
            self.assertFalse(result["passed"])
            self.assertFalse(result["backup_ready"])
            self.assertIn("restore_drill_not_recorded", result["blockers"])
            self.assertFalse(result["business_database_accessed"])
            self.assertFalse(result["evidence_refreshed"])
            self.assertFalse(result["secret_exposed"])
            self.assertEqual(dict(os.environ), before)

    def test_real_expired_restore_date_is_not_refreshed_or_relabelled(self):
        values = {"JIEJING_SAAS_ENV": "production", "JIEJING_WECHAT_PAY_REFUND_ALLOWED": "true",
                  "JIEJING_RESTORE_DRILL_LAST_AT": "2000-01-01T00:00:00+00:00"}
        with mock.patch.dict(os.environ, values, clear=True):
            result = RELEASE.backup_cold_start_preflight()
            self.assertFalse(result["passed"])
            self.assertIn("restore_drill_overdue", result["blockers"])
            self.assertEqual(dict(os.environ), values)
            self.assertFalse(result["evidence_refreshed"])

    def test_preflight_cli_returns_nonzero_when_paid_backup_is_not_ready(self):
        with mock.patch.dict(os.environ, {
            "JIEJING_SAAS_ENV": "production", "JIEJING_WECHAT_PAY_CHARGE_ALLOWED": "true",
        }, clear=True), mock.patch.object(sys, "argv", ["release-evidence", "preflight"]), \
             contextlib.redirect_stdout(io.StringIO()) as output:
            status = RELEASE.main()
        self.assertEqual(status, 2)
        self.assertFalse(json.loads(output.getvalue())["passed"])

    def test_backup_readiness_does_not_replace_production_environment_requirement(self):
        with mock.patch.dict(os.environ, {}, clear=True), \
             mock.patch("jiejing_saas.config.SaaSSettings.from_env", return_value=SimpleNamespace(is_production_like=False)), \
             mock.patch("jiejing_saas.backup_plan.build_backup_plan", return_value={"backup_ready_for_paid_launch": True}):
            self.assertFalse(RELEASE.backup_cold_start_preflight()["passed"])


class ReleaseScriptOrderTests(unittest.TestCase):
    def test_cold_start_is_fail_fast_no_network_and_before_api_replacement(self):
        source = (ROOT / "deploy/jiejing-production-release-apply.sh").read_text(encoding="utf-8")
        self.assertIn("set -euo pipefail", source)
        start = source.index('current_stage="backup_cold_start_preflight"')
        replace = source.index('current_stage="start_candidate_api"')
        self.assertLess(start, replace)
        preflight = source[start:replace]
        self.assertIn("docker run --rm --network none", preflight)
        self.assertIn('"$candidate_api_image_id" python tools/jiejing_production_release_evidence.py preflight', preflight)
        self.assertIn("dst=/run/jiejing-production-evidence,readonly", preflight)
        self.assertNotIn("||", preflight, "preflight failure cannot be swallowed before replacement")
        self.assertNotIn("--force", preflight)
        self.assertNotIn("jiejing-production-evidence-auto-refresh.sh", preflight)
        self.assertNotRegex(preflight, r"(?:export\s+)?JIEJING_(?:RESTORE_DRILL_LAST_AT|WECHAT_PAY_(?:CHARGE|REFUND)_ALLOWED)=")
        self.assertIn('"${candidate_compose[@]}" up -d --no-deps jiejing-saas', source[replace:])

    def test_applied_receipt_follows_successful_postflight_and_precedes_success_claim(self):
        source = (ROOT / "deploy/jiejing-production-release-apply.sh").read_text(encoding="utf-8")
        applied = source.index('current_stage="record_verified_applied_release"')
        self.assertLess(source.index('current_stage="verify_public_health"'), applied)
        self.assertLess(source.index('current_stage="verify_public_product_readiness"'), applied)
        finalize = source.index("finalize_evidence_refresh_transaction || finalization_rc=$?")
        self.assertLess(finalize, applied)
        self.assertIn('fail_unit_transaction "$finalization_rc"', source[finalize:applied])
        success = source.index('printf \'%s\\n\' "JIEJING_PRODUCTION_DEPLOY_APPLIED=1"')
        self.assertLess(applied, success)
        record = source[applied:success]
        self.assertIn('jiejing_production_release_evidence.py" applied', record)
        self.assertIn('--output /opt/jiejing-production/runtime-evidence/deployment.safe.json', record)
        self.assertIn('fail_unit_transaction "$unit_rc"', record)


if __name__ == "__main__":
    unittest.main()
