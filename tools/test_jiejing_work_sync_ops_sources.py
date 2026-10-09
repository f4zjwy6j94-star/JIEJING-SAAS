"""Offline path-policy tests for the two explicitly approved OPS source files."""
import importlib.util
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("ops_work_sync", ROOT / "docs/continuity/11.0/work_sync.py")
SYNC = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SYNC)
APPROVED = ("assets/jiejing-first-party-analytics.js", "assets/jiejing-ops-panels.js")


class GitStub:
    def __init__(self, repo, tracked=APPROVED):
        self.repo = repo
        self.tracked = set(tracked)

    def run(self, args, step, allowed=(0,)):
        if args[:3] != ["ls-files", "--error-unmatch", "--"]:
            raise AssertionError("Only a tracked-path lookup is permitted in this test")
        return SimpleNamespace(returncode=0 if args[-1] in self.tracked else 1)


class OpsSourcePathTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ops-source-policy-")
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)
        (self.repo / "assets").mkdir()
        for name in APPROVED:
            (self.repo / name).write_text("// synthetic source fixture\n", encoding="utf-8")

    def test_only_exact_reviewed_tracked_sources_are_allowed(self):
        for name in APPROVED:
            self.assertRegex(SYNC.safe_path(GitStub(self.repo), name), r"^[a-f0-9]{64}$")

    def test_untracked_or_other_assets_still_fail_closed(self):
        for name in APPROVED:
            with self.assertRaises(SYNC.Stop):
                SYNC.safe_path(GitStub(self.repo, tracked=()), name)
        for name in ("assets/other.js", "assets/photo.png", "media/source.js", "assets/jiejing-ops-panels.js.json", "ASSETS/jiejing-ops-panels.js", "assets/../ops.js", "private/ops.js"):
            with self.assertRaises(SYNC.Stop):
                SYNC.safe_path(GitStub(self.repo, tracked=(name,)), name)

    def test_approved_names_do_not_bypass_binary_or_size_limits(self):
        path = self.repo / APPROVED[0]
        for data in (b"binary\x00content", b"\xff\xfe", b"x" * (SYNC.MAX_TEXT_BYTES + 1)):
            path.write_bytes(data)
            with self.assertRaises(SYNC.Stop) as result:
                SYNC.safe_path(GitStub(self.repo), APPROVED[0])
            self.assertEqual(result.exception.error["code"], "NON_TEXT_OR_OVERSIZE")

    def test_exception_does_not_authorize_source_deletion(self):
        (self.repo / APPROVED[0]).unlink()
        with self.assertRaises(SYNC.Stop) as result:
            SYNC.safe_path(GitStub(self.repo), APPROVED[0])
        self.assertEqual(result.exception.error["code"], "PATH_MISSING")

    def test_failed_secret_scan_still_stops(self):
        scanner = self.repo / SYNC.SCANNER
        scanner.parent.mkdir()
        scanner.write_text("# synthetic scanner fixture\n", encoding="utf-8")

        class ScannerGit:
            repo = self.repo
            report = {"steps": []}

            def identity(self):
                pass

            def run(self, args, step, allowed=(0,)):
                if args not in (["ls-files", "--error-unmatch", "--", SYNC.SCANNER],
                                ["diff", "--quiet", "HEAD", "--", SYNC.SCANNER]):
                    raise AssertionError("Unexpected scanner guard call")
                return SimpleNamespace(returncode=0)

        with patch.object(SYNC.subprocess, "run", return_value=SimpleNamespace(returncode=1)) as scan:
            with self.assertRaises(SYNC.Stop) as result:
                SYNC.scan(ScannerGit())
        self.assertEqual(result.exception.error["code"], "SECRET_SCAN_FAILED")
        scan.assert_called_once()
        self.assertEqual(scan.call_args.args[0], [SYNC.sys.executable, str(scanner)])


if __name__ == "__main__":
    unittest.main()
