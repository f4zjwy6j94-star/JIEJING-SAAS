#!/usr/bin/env python3
"""Exercise instruction guards with isolated document/workflow fixtures.

The approved brand/continuity decision must pass without making the security
checks optional. No workflow is dispatched and the real documents are not edited.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest
import sys
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def load_guard(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class InstructionContinuityTests(unittest.TestCase):
    def run_guard(self, name: str, changes: dict[str, tuple[str, str]] | None = None) -> int:
        module = load_guard(name)
        paths = {key: getattr(module, key) for key in ("AGENTS", "RUNBOOK")}
        if name.endswith("agents_md_guardrails"):
            paths.update(PREPARE_BUNDLE=module.PREPARE_BUNDLE, PATCH_SCRIPT=module.PATCH_SCRIPT)
        else:
            paths.update(WORKFLOW=module.WORKFLOW,
                         WORK_SYNC=ROOT / "docs/continuity/11.0/WORK_SYNC.md")
        with tempfile.TemporaryDirectory(prefix="jiejing-instruction-guard-") as directory:
            fixtures = {}
            for key, source in paths.items():
                content = source.read_text(encoding="utf-8")
                if changes and key in changes:
                    before, after = changes[key]
                    self.assertIn(before, content, f"fixture marker drift: {key}")
                    content = content.replace(before, after)
                fixture = Path(directory) / key
                fixture.write_text(content, encoding="utf-8")
                fixtures[key] = fixture
            with patch.multiple(module, create=True, **fixtures), contextlib.redirect_stdout(io.StringIO()):
                return module.main()

    def test_approved_cross_border_brand_passes(self):
        self.assertEqual(self.run_guard("test_jiejing_agents_md_guardrails"), 0)

    def test_current_two_endpoint_continuity_passes(self):
        self.assertEqual(self.run_guard("test_jiejing_local_first_cloud_fallback_guardrails"), 0)

    def test_full_gate_keeps_instruction_and_ops_regressions(self):
        # Catalog inspection only: do not recursively launch the gate.
        with patch.object(sys, "path", [str(ROOT), str(ROOT / "tools"), *sys.path]):
            gate = load_guard("jiejing_precloud_deployment_gate")
        checks = dict(gate.CHECKS)
        expected = {
            "instruction_continuity_regressions": "tools/test_jiejing_instruction_continuity_regressions.py",
            "ops_evidence": "tools/test_jiejing_ops_evidence.py",
            "ops_measurement_alignment": "tools/test_jiejing_ops_measurement_alignment.py",
            "ops_panels": "tools/test_jiejing_ops_panels.js",
            "analytics_source": "tools/test_jiejing_analytics_source.js",
            "work_sync_ops_sources": "tools/test_jiejing_work_sync_ops_sources.py",
        }
        self.assertEqual(len(checks), len(gate.CHECKS), "duplicate checks are not coverage")
        for key, script in expected.items():
            with self.subTest(key=key):
                self.assertTrue(key in checks, f"required gate check missing: {key}")
                self.assertIn(script, checks[key])

    def test_brand_and_safety_cannot_be_removed(self):
        markers = (
            "delivered eBay-first.",
            "eBay is the first supported platform, not a permanent exclusive scope.",
            "Future platform expansion must not be presented as currently available functionality.",
            "Do not reframe it as a generic ERP",
            "Do not run or repeat eBay OAuth",
            "Do not run Stripe live payment cutover",
            "Do not read, print, commit, or write secrets",
            "Code review, local test success, production health, paid availability, and real eBay execution are distinct evidence",
        )
        for marker in markers:
            with self.subTest(marker=marker):
                self.assertEqual(self.run_guard("test_jiejing_agents_md_guardrails", {"AGENTS": (marker, "REMOVED")}), 1)

    def test_continuity_does_not_grant_extra_authority(self):
        markers = (
            "docs/continuity/11.0/WORK_SYNC.md",
            "video/jiejing-11-continuity-20261006",
            "The earlier local-first/fallback preference has been superseded",
            "Do not treat Codex Cloud as having local-only files, browser login state, or local secrets.",
            "Source/progress synchronization is not deployment authorization.",
            "It does not prove that the other endpoint has received it.",
            "Preserve dirty work, unexpected branches or divergence",
            "Never push main, force-push, dispatch deployment or upload private material as part of this workflow.",
        )
        for marker in markers:
            with self.subTest(marker=marker):
                self.assertEqual(self.run_guard("test_jiejing_local_first_cloud_fallback_guardrails", {"AGENTS": (marker, "REMOVED")}), 1)

    def test_receive_save_and_media_protection_remain_required(self):
        for marker in ("work_sync.py status --repo .", "work_sync.py receive --repo .", "work_sync.py save --repo .",
                       "不会切换分支、stash、reset、clean", "不上传历史正文、图片/音视频/ZIP"):
            with self.subTest(marker=marker):
                self.assertEqual(self.run_guard("test_jiejing_local_first_cloud_fallback_guardrails", {"WORK_SYNC": (marker, "REMOVED")}), 1)

    def test_self_check_cannot_be_turned_into_scheduled_or_secret_work(self):
        for added in ("schedule:", "pull_request_target:", "contents: write", "deploy_mode:", "STRIPE_SECRET_KEY"):
            with self.subTest(added=added):
                self.assertEqual(self.run_guard("test_jiejing_local_first_cloud_fallback_guardrails", {
                    "WORKFLOW": ("workflow_dispatch:", "workflow_dispatch:\n  " + added),
                }), 1)

    def test_real_platform_writes_cannot_be_enabled(self):
        self.assertEqual(self.run_guard("test_jiejing_local_first_cloud_fallback_guardrails", {
            "WORKFLOW": ('JIEJING_ENABLE_REAL_PLATFORM_WRITES: "0"', 'JIEJING_ENABLE_REAL_PLATFORM_WRITES: "1"'),
        }), 1)

    def test_old_endpoint_priority_cannot_be_restored(self):
        self.assertEqual(self.run_guard("test_jiejing_local_first_cloud_fallback_guardrails", {
            "AGENTS": ("## Local And Cloud Boundaries", "## Local And Cloud Boundaries\n\nLocal Windows Codex is the primary operating mode."),
        }), 1)


if __name__ == "__main__":
    unittest.main()
