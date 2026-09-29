#!/usr/bin/env python3
"""Isolated release-evidence regressions; never run the full gate or deploy."""

from __future__ import annotations

import contextlib
import ast
import copy
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load_tool(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ReleaseGateEvidenceTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="jiejing-gate-evidence-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.git("init", "-q")
        (self.root / ".gitignore").write_text("output/\n", encoding="utf-8")
        (self.root / "source.txt").write_text("committed source\n", encoding="utf-8")
        self.git("add", ".")
        self.git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.test", "commit", "-qm", "fixture")
        self.gate = load_tool("jiejing_precloud_deployment_gate")
        self.checks = [("fixture_pass", [sys.executable, "-c", "raise SystemExit(0)"])]

    def git(self, *args):
        return subprocess.check_output(["git", *args], cwd=self.root, text=True).strip()

    def run_gate(self, checks=None):
        output = self.root / "output" / "gate"
        with patch.object(self.gate, "ROOT", self.root), patch.object(self.gate, "OUT", output), \
                patch.object(self.gate, "CHECKS", self.checks if checks is None else checks), \
                contextlib.redirect_stdout(io.StringIO()):
            code = self.gate.main()
        return code, json.loads((output / "latest.json").read_text(encoding="utf-8"))

    def test_clean_gate_binds_actual_source_and_complete_check_results(self):
        code, report = self.run_gate()
        self.assertEqual(code, 0)
        evidence = report.get("release_gate_evidence", {})
        self.assertEqual(evidence.get("source_commit"), self.git("rev-parse", "HEAD"))
        self.assertEqual(evidence.get("source_tree"), self.git("rev-parse", "HEAD^{tree}"))
        self.assertIs(evidence.get("release_eligible"), True)
        self.assertEqual(evidence.get("expected_check_keys"), ["fixture_pass"])
        self.assertEqual(evidence.get("results"), [{"key": "fixture_pass", "pass": True, "returncode": 0}])

    def test_listing_rewrite_api_has_a_bounded_browser_integration_budget(self):
        command = [sys.executable, "tools/test_jiejing_listing_buyer_copy_rewrite_api.py"]
        cases = (("listing_buyer_copy_rewrite_api", 300), ("browser_fixture", 300),
                 ("listing_buyer_copy_rewrite_frontend", 600), ("listing_single_progress", 600),
                 ("fixture_pass", 180), ("listing_buyer_copy_rewrite_api_extra", 180),
                 ("listing_buyer_copy_rewrite", 180), ("listing_single_progress_extra", 180))
        for key, expected in cases:
            with self.subTest(key=key), patch.object(self.gate.subprocess, "run",
                    return_value=subprocess.CompletedProcess(command, 0, "PASS", "")) as run:
                result = self.gate._run_check(key, command)
                self.assertEqual(run.call_args.kwargs["timeout"], expected)
                self.assertEqual(run.call_count, 1)
                self.assertIs(result["pass"], True)

    def test_listing_rewrite_api_timeout_still_fails_without_retry(self):
        command = [sys.executable, "tools/test_jiejing_listing_buyer_copy_rewrite_api.py"]
        for key, budget in (("listing_buyer_copy_rewrite_api", 300),
                            ("listing_buyer_copy_rewrite_frontend", 600), ("listing_single_progress", 600)):
            with self.subTest(key=key), patch.object(self.gate.subprocess, "run",
                    side_effect=subprocess.TimeoutExpired(command, budget)) as run:
                result = self.gate._run_check(key, command)
            self.assertEqual(run.call_count, 1)
            self.assertIs(result["pass"], False)
            self.assertEqual(result["returncode"], 124)
            self.assertEqual(result["error"], "timeout")

    def test_dirty_checks_are_diagnostic_only(self):
        (self.root / "source.txt").write_text("not committed\n", encoding="utf-8")
        code, report = self.run_gate()
        self.assertEqual(code, 1)
        self.assertEqual(report["status"], "pass_local_checks")
        self.assertIs(report["ready_for_public_staging_code_handoff"], False)

    def test_hidden_index_flags_cannot_attest_modified_worktree_bytes(self):
        for flag in ("assume-unchanged", "skip-worktree"):
            with self.subTest(flag=flag):
                self.git("update-index", f"--{flag}", "source.txt")
                try:
                    (self.root / "source.txt").write_text("UNCOMMITTED MODIFIED INPUT\n", encoding="utf-8")
                    self.assertEqual(self.git("status", "--porcelain"), "")
                    self.assertEqual(self.git("show", "HEAD:source.txt"), "committed source")
                    code, report = self.run_gate([("modified_input_only", [sys.executable, "-c",
                        "from pathlib import Path; assert 'UNCOMMITTED MODIFIED INPUT' in Path('source.txt').read_text()"] )])
                    self.assertEqual(report["status"], "pass_local_checks")
                    self.assertEqual(code, 1)
                    self.assertIs(report["ready_for_public_staging_code_handoff"], False)
                    self.assertIs(report["release_gate_evidence"]["source_before"]["tracked_flags_safe"], False)
                    self.assertIs(report["release_gate_evidence"]["source_after"]["tracked_flags_safe"], False)
                finally:
                    self.git("update-index", f"--no-{flag}", "source.txt")
                    (self.root / "source.txt").write_text("committed source\n", encoding="utf-8")

    def test_tracking_flags_are_checked_at_end_too(self):
        command = "import subprocess; subprocess.run(['git','update-index','--skip-worktree','source.txt'], check=True)"
        try:
            code, report = self.run_gate([("hide_tracking_after_start", [sys.executable, "-c", command])])
            self.assertEqual(code, 1)
            self.assertIs(report["release_gate_evidence"]["source_before"]["tracked_flags_safe"], True)
            self.assertIs(report["release_gate_evidence"]["source_after"]["tracked_flags_safe"], False)
        finally:
            self.git("update-index", "--no-skip-worktree", "source.txt")

    def test_normal_crlf_checkout_remains_eligible(self):
        (self.root / ".gitattributes").write_text("source.txt text eol=crlf\n", encoding="utf-8")
        self.git("add", ".gitattributes")
        self.git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.test", "commit", "-qm", "CRLF fixture")
        (self.root / "source.txt").write_bytes(b"committed source\r\n")
        self.assertEqual(self.git("status", "--porcelain"), "")
        code, report = self.run_gate()
        self.assertEqual(code, 0)
        self.assertIs(report["ready_for_public_staging_code_handoff"], True)

    def test_bundle_and_deploy_source_guards_reject_hidden_tracking_flags(self):
        bundle = load_tool("jiejing_prepare_public_staging_bundle")
        deploy = load_tool("jiejing_production_deploy")
        commit = self.git("rev-parse", "HEAD")
        for flag in ("assume-unchanged", "skip-worktree"):
            with self.subTest(flag=flag), patch.object(bundle, "ROOT", self.root), patch.object(deploy, "ROOT", self.root):
                self.git("update-index", f"--{flag}", "source.txt")
                try:
                    self.assertEqual(self.git("status", "--porcelain"), "")
                    with self.assertRaisesRegex(RuntimeError, "tracking_flags"):
                        bundle._clean_source_commit()
                    with self.assertRaisesRegex(RuntimeError, "tracking_flags"):
                        bundle._assert_source_unchanged(commit)
                    with self.assertRaisesRegex(ValueError, "tracking_flags"):
                        deploy.assert_source_state(commit)
                finally:
                    self.git("update-index", f"--no-{flag}", "source.txt")

    def test_changes_during_checks_even_if_reverted_are_not_release_evidence(self):
        command = "from pathlib import Path; p=Path('source.txt'); b=p.read_bytes(); p.write_bytes(b+'changed'.encode()); p.write_bytes(b)"
        code, report = self.run_gate([("transient_source_change", [sys.executable, "-c", command])])
        self.assertEqual(code, 1)
        self.assertEqual(self.git("status", "--porcelain"), "")
        self.assertIs(report["ready_for_public_staging_code_handoff"], False)

    def test_empty_duplicate_or_failed_catalog_is_not_passing(self):
        for checks in ([], self.checks * 2, [("failure", [sys.executable, "-c", "raise SystemExit(4)"])]):
            with self.subTest(checks=checks):
                code, report = self.run_gate(checks)
                self.assertEqual(code, 1)
                self.assertIs(report["ready_for_public_staging_code_handoff"], False)

    def test_catalog_is_portable_without_changing_literal_arguments(self):
        helper = load_tool("jiejing_release_gate_evidence")
        windows = [("test", ["C:/Python313/python.exe", "C:/candidate/tools/check.py", "literal\\argument"])]
        linux = [("test", ["/opt/venv/bin/python3.13", "/candidate/tools/check.py", "literal\\argument"])]
        win = helper.canonical_checks(windows, Path("C:/candidate"))
        self.assertEqual(win, helper.canonical_checks(linux, Path("/candidate")))
        self.assertEqual(win[0]["command"][-1], "literal\\argument")

    def test_gate_report_can_be_sealed_but_old_unbound_report_cannot(self):
        helper = load_tool("jiejing_release_gate_evidence")
        _, report = self.run_gate()
        path = self.root / "output" / "gate" / "latest.json"
        proof = helper.load_gate_report(path, self.git("rev-parse", "HEAD"), self.git("rev-parse", "HEAD^{tree}"), self.checks, self.root)
        self.assertEqual(proof["evidence"], report["release_gate_evidence"])
        self.assertEqual(len(proof["report_sha256"]), 64)
        self.assertNotIn("stdout_tail", json.dumps(proof))
        path.write_text(json.dumps({"status": "pass_local_checks", "checks": [{"key": "old_196", "pass": True}],
                                    "ready_for_public_staging_code_handoff": True}), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "gate_evidence"):
            helper.load_gate_report(path, self.git("rev-parse", "HEAD"), self.git("rev-parse", "HEAD^{tree}"), self.checks, self.root)

    def test_next_steps_use_current_authority_not_historical_reachability(self):
        for status in ("verified", "blocked", "not_checked"):
            steps = self.gate._next_external_steps({"status": status})
            text = "\n".join(steps)
            for stale in ("agentuser_ssh", "known_agentuser", "vault_kms", "provision_managed_postgres", "artifact_is_missing_or_stale"):
                self.assertNotIn(stale, text)
            self.assertIn("JIEJING_CURRENT_EXECUTION_STATE", text)
            self.assertIn("manual_github", text)
            self.assertIn("explicitly_approves_new_ebay_account", text)

    def test_evidence_rejects_stale_partial_tampered_and_unsafe_summaries(self):
        helper = load_tool("jiejing_release_gate_evidence")
        self.checks.append(("second_pass", [sys.executable, "-c", "pass"]))
        _, report = self.run_gate()
        original = report["release_gate_evidence"]
        commit, tree = original["source_commit"], original["source_tree"]
        mutations = {
            "stale_commit": lambda e: e.update(source_commit="a" * 40),
            "stale_tree": lambda e: e.update(source_tree="b" * 40),
            "missing_result": lambda e: e["results"].pop(),
            "result_order": lambda e: e["results"].reverse(),
            "duplicate_result": lambda e: e["results"].append(e["results"][0]),
            "failed_returncode": lambda e: e["results"][0].update(returncode=2),
            "boolean_returncode": lambda e: e["results"][0].update(returncode=False),
            "truthy_pass": lambda e: e["results"][0].update({"pass": 1}),
            "dirty_start": lambda e: e["source_before"].update(worktree_clean=False),
            "dirty_finish": lambda e: e["source_after"].update(worktree_clean=False),
            "hidden_tracking_start": lambda e: e["source_before"].update(tracked_flags_safe=False),
            "hidden_tracking_finish": lambda e: e["source_after"].update(tracked_flags_safe=False),
            "changed_files": lambda e: e["source_after"].update(tracked_fingerprint_sha256="f" * 64),
            "claim_failure": lambda e: e.update(release_eligible=False),
            "naive_timestamp": lambda e: e.update(started_at="2026-09-05T00:00:00"),
            "backwards_timestamp": lambda e: e.update(finished_at="2000-01-01T00:00:00Z"),
            "raw_output_in_proof": lambda e: e.update(stdout_tail="not allowed in manifest"),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label):
                evidence = copy.deepcopy(original)
                mutate(evidence)
                with self.assertRaisesRegex(ValueError, "gate_evidence"):
                    helper.validate_gate_evidence(evidence, commit, tree, self.checks, self.root)
        for catalog in (self.checks[:1], list(reversed(self.checks)), self.checks * 2, [],
                        [("fixture_pass", [sys.executable, "-c", "different command"]), self.checks[1]]):
            with self.subTest(catalog=catalog), self.assertRaisesRegex(ValueError, "gate_evidence"):
                helper.validate_gate_evidence(original, commit, tree, catalog, self.root)

    def test_raw_report_must_agree_with_its_sanitized_evidence(self):
        helper = load_tool("jiejing_release_gate_evidence")
        _, original = self.run_gate()
        path = self.root / "output" / "gate" / "latest.json"
        for label, mutate in {
            "failed_result": lambda r: r["checks"][0].update(returncode=4),
            "duplicate_result": lambda r: r["checks"].append(r["checks"][0]),
            "string_pass": lambda r: r["checks"][0].update({"pass": "true"}),
            "failed_status": lambda r: r.update(status="failed_local_checks"),
            "false_handoff": lambda r: r.update(ready_for_public_staging_code_handoff=False),
            "exposure_flag": lambda r: r.update(secret_exposed=True),
        }.items():
            with self.subTest(label=label):
                report = copy.deepcopy(original)
                mutate(report)
                path.write_text(json.dumps(report), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "gate_evidence"):
                    helper.load_gate_report(path, self.git("rev-parse", "HEAD"), self.git("rev-parse", "HEAD^{tree}"), self.checks, self.root)

    def test_same_candidate_in_another_checkout_accepts_receipt(self):
        helper = load_tool("jiejing_release_gate_evidence")
        _, report = self.run_gate()
        clone_temp = tempfile.TemporaryDirectory(prefix="jiejing-gate-second-checkout-")
        self.addCleanup(clone_temp.cleanup)
        clone = Path(clone_temp.name)
        subprocess.run(["git", "clone", "-q", str(self.root), str(clone)], check=True, capture_output=True)
        state = helper.capture_source_state(clone)
        self.assertNotEqual(state["tracked_fingerprint_sha256"], report["release_gate_evidence"]["source_before"]["tracked_fingerprint_sha256"])
        helper.validate_gate_evidence(report["release_gate_evidence"], state["source_commit"], state["source_tree"], self.checks, clone)

    def test_historical_doctor_does_not_claim_current_verification(self):
        doctor = self.root / "output" / "jiejing-deploy-channel-doctor" / "latest.json"
        doctor.parent.mkdir(parents=True)
        doctor.write_text(json.dumps({"deploy_channel_ready": True, "public_staging_reachable": True}), encoding="utf-8")
        with patch.object(self.gate, "ROOT", self.root):
            observed = self.gate._latest_staging_verification()
        self.assertEqual(observed["status"], "historical_verified")
        self.assertIs(observed["current_state_verified"], False)

    def test_actual_gate_cli_fails_closed_but_keeps_dirty_diagnostics(self):
        (self.root / "tools").mkdir()
        (self.root / "tools" / "jiejing_release_gate_evidence.py").write_text(
            (ROOT / "tools" / "jiejing_release_gate_evidence.py").read_text(encoding="utf-8"), encoding="utf-8")
        source = (ROOT / "tools" / "jiejing_precloud_deployment_gate.py").read_text(encoding="utf-8")
        node = next(node for node in ast.parse(source).body if isinstance(node, ast.AnnAssign) and getattr(node.target, "id", "") == "CHECKS")
        lines = source.splitlines(keepends=True)
        lines[node.lineno - 1:node.end_lineno] = ['CHECKS = [("fixture_pass", [sys.executable, "-c", "pass"])]\n']
        script = self.root / "tools" / "jiejing_precloud_deployment_gate.py"
        script.write_text("".join(lines), encoding="utf-8")
        (self.root / ".gitignore").write_text("output/\n__pycache__/\n", encoding="utf-8")
        self.git("add", ".")
        self.git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.test", "commit", "-qm", "fixture gate CLI")
        (self.root / "source.txt").write_text("uncommitted source\n", encoding="utf-8")
        result = subprocess.run([sys.executable, str(script)], cwd=self.root, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 1)
        report = json.loads((self.root / "output" / "jiejing-precloud-deployment-gate" / "latest.json").read_text(encoding="utf-8"))
        self.assertEqual(report["status"], "pass_local_checks")
        self.assertIs(report["ready_for_public_staging_code_handoff"], False)
        self.assertEqual(len(report["checks"]), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
