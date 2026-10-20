"""Offline path-policy tests for explicitly approved tracked OPS source files."""
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
APPROVED_DEPLOY = ("deploy/Caddyfile.production", "deploy/nginx.ops.production.conf")


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
                if args == ["show", "HEAD:" + SYNC.SCANNER]:
                    return SimpleNamespace(stdout=scanner.read_bytes())
                if args not in (["ls-files", "--error-unmatch", "--", SYNC.SCANNER],
                                ["diff", "--quiet", "HEAD", "--", SYNC.SCANNER]):
                    raise AssertionError("Unexpected scanner guard call")
                return SimpleNamespace(returncode=0)

        with patch.object(SYNC.subprocess, "run", return_value=SimpleNamespace(returncode=1)) as scan:
            with self.assertRaises(SYNC.Stop) as result:
                SYNC.scan(ScannerGit())
        self.assertEqual(result.exception.error["code"], "SECRET_SCAN_FAILED")
        scan.assert_called_once()
        self.assertEqual(scan.call_args.args[0][:2], [SYNC.sys.executable, "-c"])
        self.assertEqual(scan.call_args.args[0][-1], str(scanner))
        self.assertEqual(scan.call_args.kwargs["input"], scanner.read_bytes())


class DeploySourcePathTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="deploy-source-policy-")
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)
        (self.repo / "deploy").mkdir()
        for name in APPROVED_DEPLOY:
            (self.repo / name).write_text("# synthetic configuration source\n", encoding="utf-8")

    def test_only_exact_reviewed_tracked_deploy_sources_are_allowed(self):
        for name in APPROVED_DEPLOY:
            with self.subTest(path=name):
                self.assertRegex(SYNC.safe_path(GitStub(self.repo, APPROVED_DEPLOY), name), r"^[a-f0-9]{64}$")

    def test_untracked_deploy_sources_are_rejected(self):
        for name in APPROVED_DEPLOY:
            with self.subTest(path=name), self.assertRaises(SYNC.Stop) as result:
                SYNC.safe_path(GitStub(self.repo, tracked=()), name)
            self.assertEqual(result.exception.error["code"], "SENSITIVE_OR_NON_SOURCE_PATH")

    def test_case_variants_and_other_configs_are_not_authorized(self):
        for name in (
            "Deploy/Caddyfile.production", "deploy/caddyfile.production",
            "deploy/Caddyfile.Production", "deploy/Caddyfile.staging",
            "DEPLOY/nginx.ops.production.conf", "deploy/NGINX.ops.production.conf",
            "deploy/nginx.ops.production.CONF", "deploy/nginx.production.conf",
            "deploy/other.conf", "deploy/nested/nginx.ops.production.conf",
            "private/nginx.ops.production.conf",
        ):
            with self.subTest(path=name), self.assertRaises(SYNC.Stop) as result:
                SYNC.safe_path(GitStub(self.repo, tracked=(name,)), name)
            self.assertEqual(result.exception.error["code"], "SENSITIVE_OR_NON_SOURCE_PATH")

    def test_deploy_exception_does_not_authorize_deletion(self):
        for name in APPROVED_DEPLOY:
            (self.repo / name).unlink()
            with self.subTest(path=name), self.assertRaises(SYNC.Stop) as result:
                SYNC.safe_path(GitStub(self.repo, APPROVED_DEPLOY), name)
            self.assertEqual(result.exception.error["code"], "PATH_MISSING")

    def test_deploy_sources_keep_utf8_binary_and_size_checks(self):
        for name in APPROVED_DEPLOY:
            for data in (b"binary\x00content", b"\xff\xfe", b"x" * (SYNC.MAX_TEXT_BYTES + 1)):
                (self.repo / name).write_bytes(data)
                with self.subTest(path=name, byte_count=len(data)), self.assertRaises(SYNC.Stop) as result:
                    SYNC.safe_path(GitStub(self.repo, APPROVED_DEPLOY), name)
                self.assertEqual(result.exception.error["code"], "NON_TEXT_OR_OVERSIZE")

    def test_deploy_sources_reject_link_at_file_or_parent(self):
        # Mock only the filesystem boundary; creating links can require Windows privileges.
        for name in APPROVED_DEPLOY:
            for link_path in (self.repo / "deploy", self.repo / name):
                with self.subTest(path=name, link=str(link_path)), patch.object(
                    Path, "is_symlink", autospec=True, side_effect=lambda current: current == link_path
                ), self.assertRaises(SYNC.Stop) as result:
                    SYNC.safe_path(GitStub(self.repo, APPROVED_DEPLOY), name)
                self.assertEqual(result.exception.error["code"], "SYMLINK_PATH_FORBIDDEN")

    def test_deploy_exception_does_not_bypass_explicit_dirty_or_staged_scope(self):
        selected = {SYNC.INDEX, *APPROVED_DEPLOY}
        index = self.repo / SYNC.INDEX
        index.parent.mkdir(parents=True)
        index.write_text("# synthetic progress\n", encoding="utf-8")

        class ScopeGit(GitStub):
            text = staticmethod(SYNC.Git.text)

            def assert_idle(self):
                pass

            def status(self):
                return self.dirty, self.staged

            def run(self, args, step, allowed=(0,)):
                if args == ["diff", "--numstat", "--no-ext-diff", "--no-textconv", "HEAD", "--", SYNC.INDEX]:
                    return SimpleNamespace(stdout=b"1\t0\t" + SYNC.INDEX.encode("utf-8"))
                return super().run(args, step, allowed)

        git = ScopeGit(self.repo, APPROVED_DEPLOY)
        for dirty, staged, expected in (
            (selected | {"app.js"}, set(), "UNLISTED_DIRTY_PATHS"),
            (selected, {APPROVED_DEPLOY[0]}, "EXISTING_STAGED_CHANGES"),
        ):
            git.dirty, git.staged = dirty, staged
            with self.subTest(code=expected), self.assertRaises(SYNC.Stop) as result:
                SYNC.save_scope(git, selected)
            self.assertEqual(result.exception.error["code"], expected)


class ReviewedRepairSourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="repair-source-policy-")
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)
        self.sources = (
            "jiejing_saas/support_token_resolver.py",
            "tools/test_jiejing_support_token_resolver.py",
            "jiejing_saas/support_credential_adapters.py",
            "tools/test_jiejing_support_credential_adapters.py",
        )
        for name in self.sources:
            path = self.repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("# synthetic source\n", encoding="utf-8")

    def test_only_four_exact_support_source_names_can_be_new(self):
        for name in self.sources:
            self.assertRegex(SYNC.safe_path(GitStub(self.repo, ()), name), r"^[a-f0-9]{64}$")
        for name in (
            "jiejing_saas/support_token.py", "tools/test_jiejging_support_token_resolver.py",
            "tools/TEST_jiejing_support_token_resolver.py", "private/support_token_resolver.py",
            "jiejing_saas/support_token_resolver.py.json", "jiejing_saas/support_credential_adapter.py",
            "jiejing_saas/SUPPORT_credential_adapters.py", "private/support_credential_adapters.py",
            "tools/test_jiejging_support_credential_adapters.py", "jiejing_saas/support_credential_adapters.py.json",
        ):
            with self.subTest(path=name), self.assertRaises(SYNC.Stop):
                SYNC.safe_path(GitStub(self.repo, (name,)), name)

    def test_support_names_keep_text_size_links_and_no_deletion_guards(self):
        for name in self.sources:
            path = self.repo / name
            for raw in (b"x\0y", b"\xff", b"x" * (SYNC.MAX_TEXT_BYTES + 1)):
                path.write_bytes(raw)
                with self.subTest(path=name, size=len(raw)), self.assertRaises(SYNC.Stop):
                    SYNC.safe_path(GitStub(self.repo, (name,)), name)
            path.write_text("# synthetic\n", encoding="utf-8")
            with patch.object(Path, "is_symlink", autospec=True, side_effect=lambda current: current == path):
                with self.assertRaises(SYNC.Stop) as result:
                    SYNC.safe_path(GitStub(self.repo, (name,)), name)
                self.assertEqual(result.exception.error["code"], "SYMLINK_PATH_FORBIDDEN")
            path.unlink()
            with self.assertRaises(SYNC.Stop) as result:
                SYNC.safe_path(GitStub(self.repo, (name,)), name)
            self.assertEqual(result.exception.error["code"], "PATH_MISSING")

    def test_app_limit_only_exact_tracked_source_and_three_million_bytes(self):
        app = self.repo / "app.js"
        app.write_bytes(b"/" * 3_000_000)
        self.assertRegex(SYNC.safe_path(GitStub(self.repo, ("app.js",)), "app.js"), r"^[a-f0-9]{64}$")
        for name, tracked in (("app.js", ()), ("App.js", ("App.js",)), ("other.js", ("other.js",))):
            (self.repo / name).write_bytes(b"x" * (SYNC.MAX_TEXT_BYTES + 1))
            with self.subTest(path=name, tracked=tracked), self.assertRaises(SYNC.Stop):
                SYNC.safe_path(GitStub(self.repo, tracked), name)
        for raw in (b"x" * 3_000_001, b"x\0y", b"\xff"):
            app.write_bytes(raw)
            with self.assertRaises(SYNC.Stop):
                SYNC.safe_path(GitStub(self.repo, ("app.js",)), "app.js")
        app.unlink()
        with self.assertRaises(SYNC.Stop):
            SYNC.safe_path(GitStub(self.repo, ("app.js",)), "app.js")

    def test_supplemental_scan_checks_large_app_tail_without_secret_output(self):
        scanner = self.repo / SYNC.SCANNER
        scanner.write_bytes((ROOT / SYNC.SCANNER).read_bytes())
        app = self.repo / "app.js"

        class ScannerGit(GitStub):
            report = {"steps": []}
            def identity(self):
                pass
            def run(self, args, step, allowed=(0,)):
                if args == ["show", "HEAD:" + SYNC.SCANNER]:
                    return SimpleNamespace(stdout=(ROOT / SYNC.SCANNER).read_bytes())
                if args == ["diff", "--quiet", "HEAD", "--", SYNC.SCANNER]:
                    return SimpleNamespace(returncode=0)
                return super().run(args, step, allowed)

        git = ScannerGit(self.repo, (SYNC.SCANNER, "app.js"))
        for secret in (False, True):
            tail = ("gh" + "p_" + "A" * 30) if secret else "console.log('safe');"
            app.write_bytes(("// x\n" * 510_000 + tail).encode("utf-8"))
            with patch.object(SYNC.subprocess, "run", return_value=SimpleNamespace(returncode=0)):
                if secret:
                    with self.assertRaises(SYNC.Stop) as result:
                        SYNC.scan(git)
                    self.assertEqual(result.exception.error["code"], "SECRET_SCAN_FAILED")
                    self.assertNotIn(tail, str(result.exception.error))
                else:
                    SYNC.scan(git)
                    self.assertTrue(any(s["step"] == "reviewed_large_source_secret_scan" for s in git.report["steps"]))

    def test_mutable_scanner_swap_cannot_replace_canonical_rules_or_execute(self):
        scanner = self.repo / SYNC.SCANNER
        canonical = (ROOT / SYNC.SCANNER).read_bytes()
        scanner.write_bytes(canonical)
        marker = self.repo / "unexpected-marker.txt"
        tail = "gh" + "p_" + "A" * 30
        (self.repo / "app.js").write_bytes(("// x\n" * 510_000 + tail).encode())

        class ScannerGit(GitStub):
            report = {"steps": []}
            def identity(self):
                pass
            def run(self, args, step, allowed=(0,)):
                if args == ["show", "HEAD:" + SYNC.SCANNER]:
                    return SimpleNamespace(stdout=canonical)
                if args == ["diff", "--quiet", "HEAD", "--", SYNC.SCANNER]:
                    return SimpleNamespace(returncode=0)
                return super().run(args, step, allowed)

        def swap_after_scan(*args, **kwargs):
            self.assertEqual(kwargs["input"], canonical)
            scanner.write_text("from pathlib import Path\nPath(" + repr(str(marker)) + ").write_text('bad')\nRULES=[]\n", encoding="utf-8")
            return SimpleNamespace(returncode=0)

        with patch.object(SYNC.subprocess, "run", side_effect=swap_after_scan):
            with self.assertRaises(SYNC.Stop) as result:
                SYNC.scan(ScannerGit(self.repo, (SYNC.SCANNER, "app.js")))
        self.assertEqual(result.exception.error["code"], "SECRET_SCAN_FAILED")
        self.assertFalse(marker.exists())
        self.assertNotIn(tail, str(result.exception.error))


class FollowupSourceApprovalTests(unittest.TestCase):
    session_test = "tools/test_jiejing_rotating_browser_session_http.py"
    migration_source = "jiejing_saas/migrations/006_support_conversations_postgres.sql"

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="followup-source-policy-")
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)
        for name in (self.session_test, self.migration_source):
            path = self.repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("-- synthetic source\n" if name.endswith(".sql") else "# synthetic source\n", encoding="utf-8")

    def test_owner_approved_session_test_requires_exact_tracked_path(self):
        self.assertRegex(
            SYNC.safe_path(GitStub(self.repo, (self.session_test,)), self.session_test),
            r"^[a-f0-9]{64}$",
        )
        with self.assertRaises(SYNC.Stop) as result:
            SYNC.safe_path(GitStub(self.repo, ()), self.session_test)
        self.assertEqual(result.exception.error["code"], "SENSITIVE_OR_NON_SOURCE_PATH")

    def test_owner_approved_sql_source_may_be_new_but_not_other_sql(self):
        self.assertRegex(
            SYNC.safe_path(GitStub(self.repo, ()), self.migration_source),
            r"^[a-f0-9]{64}$",
        )
        other = "jiejing_saas/migrations/007_support_conversations_postgres.sql"
        (self.repo / other).write_text("-- synthetic source\n", encoding="utf-8")
        with self.assertRaises(SYNC.Stop) as result:
            SYNC.safe_path(GitStub(self.repo, (other,)), other)
        self.assertEqual(result.exception.error["code"], "SENSITIVE_OR_NON_SOURCE_PATH")

    def test_followup_exceptions_do_not_allow_case_directory_or_suffix_variants(self):
        for name in (
            "tools/TEST_jiejing_rotating_browser_session_http.py",
            "Tools/test_jiejing_rotating_browser_session_http.py",
            "tools/test_jiejing_rotating_browser_session_http.py.json",
            "tools/test_other_session_http.py",
            "jiejing_saas/rotating_browser_session.py",
            "private/test_jiejing_rotating_browser_session_http.py",
            "jiejing_saas/migrations/006_support_conversations_postgres.SQL",
            "jiejing_saas/migrations/006_SUPPORT_conversations_postgres.sql",
            "jiejing_saas/Migrations/006_support_conversations_postgres.sql",
            "jiejing_saas/migrations/other.sql",
            "data/006_support_conversations_postgres.sql",
            "jiejing_saas/migrations/nested/006_support_conversations_postgres.sql",
        ):
            with self.subTest(path=name), self.assertRaises(SYNC.Stop) as result:
                SYNC.safe_path(GitStub(self.repo, (name,)), name)
            self.assertEqual(result.exception.error["code"], "SENSITIVE_OR_NON_SOURCE_PATH")

    def test_followup_exceptions_do_not_allow_deletion(self):
        for name in (self.session_test, self.migration_source):
            (self.repo / name).unlink()
            with self.subTest(path=name), self.assertRaises(SYNC.Stop) as result:
                SYNC.safe_path(GitStub(self.repo, (name,)), name)
            self.assertEqual(result.exception.error["code"], "PATH_MISSING")

    def test_followup_exceptions_keep_text_and_original_size_limit(self):
        for name in (self.session_test, self.migration_source):
            for raw in (b"binary\x00value", b"\xff\xfe", b"x" * (SYNC.MAX_TEXT_BYTES + 1)):
                (self.repo / name).write_bytes(raw)
                with self.subTest(path=name, size=len(raw)), self.assertRaises(SYNC.Stop) as result:
                    SYNC.safe_path(GitStub(self.repo, (name,)), name)
                self.assertEqual(result.exception.error["code"], "NON_TEXT_OR_OVERSIZE")

    def test_followup_exceptions_reject_symlink_at_every_path_component(self):
        for name in (self.session_test, self.migration_source):
            candidate = self.repo
            for part in name.split("/"):
                candidate = candidate / part
                with self.subTest(path=name, component=str(candidate)), patch.object(
                    Path, "is_symlink", autospec=True,
                    side_effect=lambda current, target=candidate: current == target,
                ), self.assertRaises(SYNC.Stop) as result:
                    SYNC.safe_path(GitStub(self.repo, (name,)), name)
                self.assertEqual(result.exception.error["code"], "SYMLINK_PATH_FORBIDDEN")

    def test_followup_exceptions_keep_explicit_dirty_and_staged_guards(self):
        selected = {SYNC.INDEX, self.session_test, self.migration_source}

        class ScopeGit(GitStub):
            text = staticmethod(SYNC.Git.text)

            def assert_idle(self):
                pass

            def status(self):
                return self.dirty, self.staged

            def run(self, args, step, allowed=(0,)):
                if args == ["diff", "--numstat", "--no-ext-diff", "--no-textconv", "HEAD", "--", SYNC.INDEX]:
                    return SimpleNamespace(stdout=b"1\t0\t" + SYNC.INDEX.encode("utf-8"))
                return super().run(args, step, allowed)

        git = ScopeGit(self.repo, (self.session_test,))
        for dirty, staged, expected in (
            (selected | {"app.js"}, set(), "UNLISTED_DIRTY_PATHS"),
            (selected, {self.session_test}, "EXISTING_STAGED_CHANGES"),
        ):
            git.dirty, git.staged = dirty, staged
            with self.subTest(code=expected), self.assertRaises(SYNC.Stop) as result:
                SYNC.save_scope(git, selected)
            self.assertEqual(result.exception.error["code"], expected)

    def test_canonical_scanner_checks_both_newly_approved_files(self):
        scanner = self.repo / SYNC.SCANNER
        canonical = (ROOT / SYNC.SCANNER).read_bytes()
        scanner.write_bytes(canonical)

        class ScannerGit(GitStub):
            def __init__(self, repo):
                super().__init__(repo, (SYNC.SCANNER, FollowupSourceApprovalTests.session_test))
                self.report = {"steps": []}

            def identity(self):
                pass

            def run(self, args, step, allowed=(0,)):
                if args == ["show", "HEAD:" + SYNC.SCANNER]:
                    return SimpleNamespace(stdout=canonical)
                if args == ["diff", "--quiet", "HEAD", "--", SYNC.SCANNER]:
                    return SimpleNamespace(returncode=0)
                return super().run(args, step, allowed)

        # Execute the original scanner, not a stubbed successful subprocess.
        SYNC.scan(ScannerGit(self.repo))
        fixture_value = "gh" + "p_" + "A" * 32
        for name in (self.session_test, self.migration_source):
            path = self.repo / name
            original = path.read_bytes()
            path.write_text(fixture_value + "\n", encoding="utf-8")
            try:
                with self.subTest(path=name), self.assertRaises(SYNC.Stop) as result:
                    SYNC.scan(ScannerGit(self.repo))
                self.assertEqual(result.exception.error["code"], "SECRET_SCAN_FAILED")
                self.assertNotIn(fixture_value, str(result.exception.error))
            finally:
                path.write_bytes(original)
        SYNC.scan(ScannerGit(self.repo))


if __name__ == "__main__":
    unittest.main()
