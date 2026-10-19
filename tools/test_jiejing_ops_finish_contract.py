"""Offline regression for evidence labels and unchanged latency-alert policy."""
import sys
import unittest
import importlib.util
import json
import tempfile
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from jiejing_saas.operations_metering import build_reliability_alert_summary, RELIABILITY_ALERT_THRESHOLDS
spec = importlib.util.spec_from_file_location("release_evidence", ROOT / "tools/jiejing_production_release_evidence.py")
release_evidence = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release_evidence)


class OpsFinishContract(unittest.TestCase):
    def test_latency_alert_keeps_threshold_and_separates_sample_denominators(self):
        data = {"model": {"request_count": 100, "sample_count": 90,
                          "streamed_request_count": 26, "p75_duration_ms": 21931,
                          "p75_first_output_ms": 1672, "failure_count": 0, "timeout_count": 0,
                          "latest_sample_at": "2026-10-04T10:40:38+00:00"}}
        item = build_reliability_alert_summary(data)["items"][0]
        self.assertEqual(item["status"], "attention")
        self.assertEqual(item["reason_codes"], ["high_latency"])
        self.assertEqual(item["p75_first_output_ms"], 1672)
        self.assertEqual(item["first_output_sample_count"], 26)
        self.assertEqual(item["sample_count"], 90)
        self.assertEqual(item["latest_sample_at"], "2026-10-04T10:40:38+00:00")
        self.assertEqual(RELIABILITY_ALERT_THRESHOLDS["model"]["attention_p75_ms"], 15000)

    def test_reliability_ui_names_window_not_real_time_and_keeps_alarm(self):
        source = (ROOT / "ops.js").read_text(encoding="utf-8")
        section = source[source.index("function renderReliability()"):source.index("function renderSettings()")]
        self.assertIn("measurementScope(overview.period", section)
        self.assertIn("最近样本", section)
        self.assertIn("不是实时速度测试", section)
        self.assertIn("耗时样本", source)
        self.assertIn("首次出字", source)
        self.assertIn("reliabilityAlertDetails(alerts)", section)
        css = (ROOT / "ops.css").read_text(encoding="utf-8")
        self.assertIn(".ops-reliability-alert-detail .ops-reliability-list { grid-template-columns: 1fr; }", css)
        self.assertIn(".ops-reliability-item dl { grid-template-columns: 1fr; }", css)

    def test_ops_proxy_follows_only_fixed_docker_service(self):
        source = (ROOT / "deploy/nginx.ops.production.conf").read_text(encoding="utf-8")
        self.assertIn("resolver 127.0.0.11 valid=10s ipv6=off;", source)
        self.assertIn("zone jiejing_ops_api 64k;", source)
        self.assertIn("server jiejing-saas:8788 resolve;", source)
        self.assertNotIn("proxy_pass http://jiejing-saas:8788", source)
        self.assertNotIn("proxy_pass $", source)

    def test_build_receipt_is_immutable_and_applied_receipt_preserves_previous(self):
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(release_evidence, "trusted_owner", return_value=True):
            root = Path(folder).resolve()
            build = root / "JIEJING_RUNTIME_BUILD.safe.json"
            release_evidence.write_receipt(build, "a" * 40, applied=False)
            with self.assertRaises(ValueError):
                release_evidence.write_receipt(build, "b" * 40, applied=False)
            receipt = root / "deployment.safe.json"
            release_evidence.write_receipt(receipt, "a" * 40, applied=True)
            release_evidence.write_receipt(receipt, "b" * 40, applied=True)
            self.assertEqual(json.loads(receipt.read_text())["source_commit"], "b" * 40)
            backups = list(root.glob("deployment.previous-*.safe.json"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(json.loads(backups[0].read_text())["source_commit"], "a" * 40)
            with self.assertRaises(ValueError):
                release_evidence.write_receipt(root / "other.json", "a" * 40, applied=True)

    def test_writer_refuses_untrusted_parent_without_creating_receipt(self):
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(release_evidence, "trusted_owner", return_value=False):
            target = Path(folder).resolve() / "deployment.safe.json"
            with self.assertRaises(ValueError):
                release_evidence.write_receipt(target, "a" * 40, applied=True)
            self.assertFalse(target.exists())

    def test_cold_start_preserves_expired_backup_failure_without_database(self):
        with mock.patch.dict("os.environ", {"JIEJING_WECHAT_PAY_CHARGE_ALLOWED": "true"}), \
             mock.patch("jiejing_saas.config.SaaSSettings.from_env", return_value=mock.Mock(is_production_like=True)), \
             mock.patch("jiejing_saas.backup_plan.build_backup_plan", return_value={"backup_ready_for_paid_launch": False, "blockers": ["restore_drill_overdue"]}) as plan:
            result = release_evidence.backup_cold_start_preflight()
            self.assertFalse(result["passed"])
            self.assertFalse(result["business_database_accessed"])
            self.assertFalse(result["evidence_refreshed"])
            self.assertEqual(plan.call_args.args[1].system_counts(), {})
            self.assertEqual(result["blockers"], ["restore_drill_overdue"])

    def test_deploy_preflight_precedes_replacement_and_receipt_follows_postflight(self):
        source = (ROOT / "deploy/jiejing-production-release-apply.sh").read_text()
        self.assertLess(source.index('current_stage="backup_cold_start_preflight"'), source.index('current_stage="start_candidate_api"'))
        self.assertLess(source.index('finalize_evidence_refresh_transaction ||'), source.index('current_stage="record_verified_applied_release"'))
        self.assertLess(source.index('current_stage="record_verified_applied_release"'), source.index('printf \'%s\\n\' "JIEJING_PRODUCTION_DEPLOY_APPLIED=1"'))

    def test_real_settings_and_backup_preflight_fail_closed_with_no_evidence(self):
        with mock.patch.dict("os.environ", {"JIEJING_SAAS_ENV": "production", "JIEJING_WECHAT_PAY_CHARGE_ALLOWED": "true"}, clear=True):
            result = release_evidence.backup_cold_start_preflight()
        self.assertFalse(result["passed"])
        self.assertIn("restore_drill_not_recorded", result["blockers"])
        self.assertFalse(result["business_database_accessed"])


if __name__ == "__main__":
    unittest.main()
