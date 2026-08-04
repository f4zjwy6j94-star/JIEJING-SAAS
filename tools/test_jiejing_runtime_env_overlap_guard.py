#!/usr/bin/env python3
"""Public-contract tests for the Jiejing runtime env overlap guard."""

from __future__ import annotations

import json
import re
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import jiejing_runtime_env_overlap_guard as guard_module
from jiejing_runtime_env_overlap_guard import (
    Declaration,
    GuardAnalysis,
    MIGRATION_APPLY_CONFIRMATION,
    _strip_yaml_scalar,
    analyze_runtime_env_ownership,
    check_runtime_env_ownership,
)


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "jiejing_runtime_env_overlap_guard.py"


class RuntimeEnvOverlapGuardTest(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary_directory.cleanup)
        self.fixture_root = Path(self._temporary_directory.name)
        self.compose_path = self.fixture_root / "docker-compose.yml"
        runtime_env_root = self.fixture_root / "runtime-env"
        runtime_env_root.mkdir()
        self.managed_path = runtime_env_root / "tencent-managed.env"
        self.secret_path = runtime_env_root / "jiejing-saas.staging-oauth.env"
        self.postgres_path = runtime_env_root / "postgres-localqueue.env"

    def _write_legal_fixture(self) -> None:
        self.compose_path.write_text(
            """services:
  jiejing-saas:
    env_file:
      - ./runtime-env/tencent-managed.env
      - ./runtime-env/jiejing-saas.staging-oauth.env
      - ./runtime-env/postgres-localqueue.env
    environment:
      JIEJING_ENABLE_REAL_PLATFORM_WRITES: \"false\"
      JIEJING_EBAY_WRITE_LIVE: \"false\"
      JIEJING_PUBLIC_STAGING_REAL_WRITE_POLICY: \"disabled_public_staging\"
      JIEJING_BILLING_PROVIDER: \"stripe_test_mock\"
  jiejing-worker:
    env_file:
      - ./runtime-env/tencent-managed.env
      - ./runtime-env/jiejing-saas.staging-oauth.env
      - ./runtime-env/postgres-localqueue.env
    environment:
      JIEJING_ENABLE_REAL_PLATFORM_WRITES: \"false\"
      JIEJING_EBAY_WRITE_LIVE: \"false\"
      JIEJING_PUBLIC_STAGING_REAL_WRITE_POLICY: \"disabled_public_staging\"
      JIEJING_BILLING_PROVIDER: \"stripe_test_mock\"
""",
            encoding="utf-8",
        )
        self.managed_path.write_text(
            "JIEJING_BACKUP_POLICY_CONFIGURED=true\n",
            encoding="utf-8",
        )
        self.secret_path.write_text(
            "JIEJING_EBAY_CLIENT_SECRET=LEGAL_SECRET_SENTINEL\n",
            encoding="utf-8",
        )
        self.postgres_path.write_text(
            "JIEJING_DATABASE_URL=postgresql://LEGAL_DATABASE_SENTINEL/db\n",
            encoding="utf-8",
        )

    def _augment_legacy_compose_contract(self) -> None:
        """Keep pre-contract fixtures focused on the behavior they originally target."""
        if not self.compose_path.is_file():
            return
        lines = self.compose_path.read_text(encoding="utf-8").splitlines()
        index = 0
        while index < len(lines):
            service_match = re.match(r"^(\s+)(jiejing-saas|jiejing-worker)\s*:\s*(?:#.*)?$", lines[index])
            if service_match is None:
                index += 1
                continue
            service_indent = len(service_match.group(1))
            end = index + 1
            while end < len(lines):
                candidate = lines[end]
                if candidate.strip() and len(candidate) - len(candidate.lstrip(" ")) <= service_indent:
                    break
                end += 1
            child_indents = [
                len(line) - len(line.lstrip(" "))
                for line in lines[index + 1 : end]
                if line.strip() and len(line) - len(line.lstrip(" ")) > service_indent
            ]
            property_indent = min(child_indents, default=service_indent + 2)
            has_env_file = any(
                len(line) - len(line.lstrip(" ")) == property_indent
                and re.match(r"^\s*env_file\s*:", line)
                for line in lines[index + 1 : end]
            )
            if not has_env_file:
                pad = " " * property_indent
                item_pad = " " * (property_indent + max(2, property_indent - service_indent))
                additions = [
                    f"{pad}env_file:",
                    f"{item_pad}- ./runtime-env/tencent-managed.env",
                    f"{item_pad}- ./runtime-env/jiejing-saas.staging-oauth.env",
                    f"{item_pad}- ./runtime-env/postgres-localqueue.env",
                ]
                lines[index + 1 : index + 1] = additions
                end += len(additions)
            cursor = index + 1
            while cursor < end:
                line = lines[cursor]
                line_indent = len(line) - len(line.lstrip(" "))
                environment_match = re.match(r"^\s*environment\s*:\s*(?:#.*)?$", line)
                if line_indent != property_indent or environment_match is None:
                    cursor += 1
                    continue
                block_end = cursor + 1
                while block_end < end:
                    candidate = lines[block_end]
                    if candidate.strip() and len(candidate) - len(candidate.lstrip(" ")) <= line_indent:
                        break
                    block_end += 1
                has_billing_pin = any("JIEJING_BILLING_PROVIDER" in candidate for candidate in lines[cursor + 1 : block_end])
                if not has_billing_pin:
                    entries = [candidate for candidate in lines[cursor + 1 : block_end] if candidate.strip()]
                    entry_indent = (
                        len(entries[0]) - len(entries[0].lstrip(" "))
                        if entries
                        else property_indent + max(2, property_indent - service_indent)
                    )
                    list_form = bool(entries and entries[0].lstrip().startswith("- "))
                    billing = (
                        f"{' ' * entry_indent}- JIEJING_BILLING_PROVIDER=stripe_test_mock"
                        if list_form
                        else f"{' ' * entry_indent}JIEJING_BILLING_PROVIDER: \"stripe_test_mock\""
                    )
                    lines[cursor + 1 : cursor + 1] = [billing]
                    end += 1
                    block_end += 1
                cursor = block_end
            index = end
        self.compose_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _run_check(self, *, augment_legacy_contract: bool = True) -> subprocess.CompletedProcess[str]:
        if augment_legacy_contract:
            self._augment_legacy_compose_contract()
        return subprocess.run(
            [
                sys.executable,
                str(TOOL),
                "check",
                "--compose",
                str(self.compose_path),
                "--managed-env",
                str(self.managed_path),
                "--secret-env",
                str(self.secret_path),
                "--postgres-env",
                str(self.postgres_path),
                "--json",
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def _run_migrate(
        self,
        *,
        apply: bool = False,
        confirm: str | None = None,
        augment_legacy_contract: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        if augment_legacy_contract:
            self._augment_legacy_compose_contract()
        command = [
            sys.executable,
            str(TOOL),
            "migrate",
            "--compose",
            str(self.compose_path),
            "--managed-env",
            str(self.managed_path),
            "--secret-env",
            str(self.secret_path),
            "--postgres-env",
            str(self.postgres_path),
            "--json",
        ]
        if apply:
            command.append("--apply")
        if confirm is not None:
            command.extend(("--confirm", confirm))
        return subprocess.run(
            command,
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_migrate_defaults_to_dry_run_and_does_not_modify_files(self) -> None:
        self._write_legal_fixture()
        before = {
            path: path.read_bytes()
            for path in (self.compose_path, self.managed_path, self.secret_path, self.postgres_path)
        }

        completed = self._run_migrate()

        self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)
        report = json.loads(completed.stdout)
        self.assertEqual(report["operation"], "migrate")
        self.assertEqual(report["mode"], "dry_run")
        self.assertFalse(report["applied"])
        self.assertFalse(report["secret_exposed"])
        self.assertEqual(
            before,
            {
                path: path.read_bytes()
                for path in (self.compose_path, self.managed_path, self.secret_path, self.postgres_path)
            },
        )

    def test_migrate_plans_equal_known_duplicate_removal_from_wrong_source(self) -> None:
        self._write_legal_fixture()
        sentinel = "EQUAL_DATABASE_SENTINEL_MUST_NOT_LEAK"
        self.managed_path.write_text(
            "JIEJING_BACKUP_POLICY_CONFIGURED=true\n"
            f"JIEJING_DATABASE_URL={sentinel}\n",
            encoding="utf-8",
        )
        self.postgres_path.write_text(f"JIEJING_DATABASE_URL={sentinel}\n", encoding="utf-8")

        completed = self._run_migrate()

        self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)
        self.assertNotIn(sentinel, completed.stdout + completed.stderr)
        report = json.loads(completed.stdout)
        self.assertTrue(report["ok"])
        self.assertEqual(
            report["actions"],
            [
                {
                    "action": "remove_from_wrong_source",
                    "comparison": "equal",
                    "count": 1,
                    "key": "JIEJING_DATABASE_URL",
                    "owner": "postgres-localqueue.env",
                    "source": "tencent-managed.env",
                }
            ],
        )
        self.assertEqual(report["summary"]["changed_source_count"], 1)
        self.assertEqual(
            sorted(key for key in _all_json_keys(report) if _looks_like_value_field(key)),
            [],
        )
        for path in (self.compose_path, self.managed_path, self.secret_path, self.postgres_path):
            self.assertNotIn(str(path), completed.stdout + completed.stderr)

    def test_migrate_rejects_conflicting_values_without_exposing_them(self) -> None:
        self._write_legal_fixture()
        managed_sentinel = "MANAGED_CONFLICT_MUST_NOT_LEAK"
        postgres_sentinel = "POSTGRES_CONFLICT_MUST_NOT_LEAK"
        self.managed_path.write_text(
            "JIEJING_BACKUP_POLICY_CONFIGURED=true\n"
            f"JIEJING_DATABASE_URL={managed_sentinel}\n",
            encoding="utf-8",
        )
        self.postgres_path.write_text(
            f"JIEJING_DATABASE_URL={postgres_sentinel}\n",
            encoding="utf-8",
        )
        before = (self.managed_path.read_bytes(), self.postgres_path.read_bytes())

        completed = self._run_migrate()

        self.assertNotEqual(completed.returncode, 0)
        combined = completed.stdout + completed.stderr
        self.assertNotIn(managed_sentinel, combined)
        self.assertNotIn(postgres_sentinel, combined)
        report = json.loads(completed.stdout)
        self.assertEqual(report["actions"], [])
        self.assertTrue(
            any(
                blocker.get("code") == "migration_value_conflict"
                and blocker.get("key") == "JIEJING_DATABASE_URL"
                and blocker.get("comparison") == "conflict"
                for blocker in report["blockers"]
            )
        )
        self.assertEqual(before, (self.managed_path.read_bytes(), self.postgres_path.read_bytes()))

    def test_migrate_apply_with_preflight_blockers_creates_no_backups_or_mutations(self) -> None:
        self._write_legal_fixture()
        self.managed_path.write_text(
            "JIEJING_BACKUP_POLICY_CONFIGURED=true\n"
            "JIEJING_DATABASE_URL=MANAGED_CONFLICT_SENTINEL\n",
            encoding="utf-8",
        )
        self.postgres_path.write_text(
            "JIEJING_DATABASE_URL=POSTGRES_CONFLICT_SENTINEL\n",
            encoding="utf-8",
        )
        before_payloads = {
            self.managed_path: self.managed_path.read_bytes(),
            self.postgres_path: self.postgres_path.read_bytes(),
        }
        before_names = {path.name for path in self.managed_path.parent.iterdir()}

        completed = self._run_migrate(apply=True, confirm=MIGRATION_APPLY_CONFIRMATION)

        self.assertNotEqual(completed.returncode, 0)
        report = json.loads(completed.stdout)
        self.assertEqual(report["summary"]["backup_count"], 0)
        self.assertEqual(before_names, {path.name for path in self.managed_path.parent.iterdir()})
        self.assertEqual(
            before_payloads,
            {
                self.managed_path: self.managed_path.read_bytes(),
                self.postgres_path: self.postgres_path.read_bytes(),
            },
        )

    def test_migrate_refuses_wrong_source_key_when_authoritative_source_is_missing(self) -> None:
        self._write_legal_fixture()
        sentinel = "ORPHAN_DATABASE_SECRET_MUST_NOT_LEAK"
        self.managed_path.write_text(
            "JIEJING_BACKUP_POLICY_CONFIGURED=true\n"
            f"JIEJING_DATABASE_PASSWORD={sentinel}\n",
            encoding="utf-8",
        )

        completed = self._run_migrate()

        self.assertNotEqual(completed.returncode, 0)
        self.assertNotIn(sentinel, completed.stdout + completed.stderr)
        report = json.loads(completed.stdout)
        self.assertEqual(report["actions"], [])
        self.assertTrue(
            any(
                blocker.get("code") == "authoritative_source_missing"
                and blocker.get("key") == "JIEJING_DATABASE_PASSWORD"
                and blocker.get("owner") == "postgres-localqueue.env"
                for blocker in report["blockers"]
            )
        )

    def test_migrate_apply_requires_exact_confirmation_phrase(self) -> None:
        self._write_legal_fixture()

        completed = self._run_migrate(apply=True)

        self.assertNotEqual(completed.returncode, 0)
        report = json.loads(completed.stdout)
        self.assertEqual(report["mode"], "apply")
        self.assertFalse(report["applied"])
        self.assertTrue(
            any(blocker.get("code") == "apply_confirmation_required" for blocker in report["blockers"])
        )

    def test_migrate_apply_does_not_echo_incorrect_confirmation_text(self) -> None:
        self._write_legal_fixture()
        sentinel = "INCORRECT_CONFIRMATION_MUST_NOT_LEAK"

        completed = self._run_migrate(apply=True, confirm=sentinel)

        self.assertNotEqual(completed.returncode, 0)
        self.assertNotIn(sentinel, completed.stdout + completed.stderr)
        report = json.loads(completed.stdout)
        self.assertTrue(
            any(blocker.get("code") == "apply_confirmation_required" for blocker in report["blockers"])
        )

    def test_simultaneous_second_migration_is_refused_by_exclusive_lock(self) -> None:
        self._write_legal_fixture()
        sentinel = "LOCKED_MIGRATION_SENTINEL_MUST_NOT_LEAK"
        self.managed_path.write_text(
            "JIEJING_BACKUP_POLICY_CONFIGURED=true\n"
            f"JIEJING_DATABASE_URL={sentinel}\n",
            encoding="utf-8",
        )
        self.postgres_path.write_text(f"JIEJING_DATABASE_URL={sentinel}\n", encoding="utf-8")
        before = self.managed_path.read_bytes()
        plan = guard_module._build_migration_plan(
            compose_path=self.compose_path,
            managed_env_path=self.managed_path,
            secret_env_path=self.secret_path,
            postgres_env_path=self.postgres_path,
        )
        lock = guard_module._acquire_migration_lock(plan)
        try:
            report = guard_module.migrate_runtime_env_ownership(
                compose_path=self.compose_path,
                managed_env_path=self.managed_path,
                secret_env_path=self.secret_path,
                postgres_env_path=self.postgres_path,
                apply=True,
                confirm=MIGRATION_APPLY_CONFIRMATION,
            )
            self.assertTrue(lock.path.exists())
        finally:
            guard_module._release_migration_lock(lock)

        serialized = json.dumps(report, ensure_ascii=False)
        self.assertFalse(report["ok"])
        self.assertFalse(report["applied"])
        self.assertNotIn(sentinel, serialized)
        self.assertTrue(
            any(blocker.get("code") == "migration_lock_unavailable" for blocker in report["blockers"])
        )
        self.assertEqual(self.managed_path.read_bytes(), before)
        self.assertFalse(lock.path.exists())

    def test_migrate_apply_backs_up_then_atomically_removes_only_wrong_source_lines(self) -> None:
        self._write_legal_fixture()
        sentinel = "APPLY_EQUAL_DATABASE_SENTINEL_MUST_NOT_LEAK"
        self.managed_path.write_text(
            "JIEJING_BACKUP_POLICY_CONFIGURED=true\n"
            f"JIEJING_DATABASE_URL={sentinel}\n",
            encoding="utf-8",
        )
        self.postgres_path.write_text(f"JIEJING_DATABASE_URL={sentinel}\n", encoding="utf-8")
        self.managed_path.chmod(0o640)
        original = self.managed_path.read_bytes()
        original_mode = stat.S_IMODE(self.managed_path.stat().st_mode)
        before_names = {path.name for path in self.managed_path.parent.iterdir()}

        completed = self._run_migrate(apply=True, confirm=MIGRATION_APPLY_CONFIRMATION)

        self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)
        self.assertNotIn(sentinel, completed.stdout + completed.stderr)
        report = json.loads(completed.stdout)
        self.assertTrue(report["ok"])
        self.assertTrue(report["applied"])
        self.assertEqual(self.managed_path.read_text(encoding="utf-8"), "JIEJING_BACKUP_POLICY_CONFIGURED=true\n")
        self.assertEqual(self.postgres_path.read_text(encoding="utf-8"), f"JIEJING_DATABASE_URL={sentinel}\n")
        new_paths = [
            path
            for path in self.managed_path.parent.iterdir()
            if path.name not in before_names
        ]
        self.assertEqual(len(new_paths), 1)
        self.assertEqual(new_paths[0].read_bytes(), original)
        target_mode = stat.S_IMODE(self.managed_path.stat().st_mode)
        backup_mode = stat.S_IMODE(new_paths[0].stat().st_mode)
        self.assertEqual(target_mode & ~original_mode, 0)
        self.assertEqual(backup_mode & ~original_mode, 0)

    def test_migrate_apply_preserves_bom_mixed_newlines_and_untouched_bytes(self) -> None:
        self._write_legal_fixture()
        sentinel = b"BYTE_PRESERVING_DATABASE_SENTINEL_MUST_NOT_LEAK"
        original = (
            b"\xef\xbb\xbfJIEJING_BACKUP_POLICY_CONFIGURED=true\r\n"
            + b"JIEJING_DATABASE_URL=" + sentinel + b"\n"
            + b"# untouched-comment\r\n"
            + b"JIEJING_COS_REGION=ap-guangzhou"
        )
        expected = (
            b"\xef\xbb\xbfJIEJING_BACKUP_POLICY_CONFIGURED=true\r\n"
            b"# untouched-comment\r\n"
            b"JIEJING_COS_REGION=ap-guangzhou"
        )
        self.managed_path.write_bytes(original)
        self.postgres_path.write_bytes(b"JIEJING_DATABASE_URL=" + sentinel + b"\r\n")
        postgres_before = self.postgres_path.read_bytes()
        before_names = {path.name for path in self.managed_path.parent.iterdir()}

        completed = self._run_migrate(apply=True, confirm=MIGRATION_APPLY_CONFIRMATION)

        self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)
        self.assertNotIn(sentinel.decode("ascii"), completed.stdout + completed.stderr)
        self.assertEqual(self.managed_path.read_bytes(), expected)
        self.assertEqual(self.postgres_path.read_bytes(), postgres_before)
        backups = [
            path
            for path in self.managed_path.parent.iterdir()
            if path.name not in before_names
        ]
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), original)

    def test_migrate_apply_rolls_back_all_changed_targets_when_atomic_replace_fails(self) -> None:
        self._write_legal_fixture()
        database_sentinel = "ROLLBACK_DATABASE_SENTINEL_MUST_NOT_LEAK"
        backup_sentinel = "ROLLBACK_BACKUP_SENTINEL_MUST_NOT_LEAK"
        self.managed_path.write_text(
            f"JIEJING_BACKUP_POLICY_CONFIGURED={backup_sentinel}\n"
            f"JIEJING_DATABASE_URL={database_sentinel}\n",
            encoding="utf-8",
        )
        self.postgres_path.write_text(
            f"JIEJING_DATABASE_URL={database_sentinel}\n"
            f"JIEJING_BACKUP_POLICY_CONFIGURED={backup_sentinel}\n",
            encoding="utf-8",
        )
        before = {
            self.managed_path: self.managed_path.read_bytes(),
            self.postgres_path: self.postgres_path.read_bytes(),
        }
        real_commit = guard_module._commit_candidate
        call_count = 0

        def fail_second_commit(
            snapshot: guard_module.SourceSnapshot,
            candidate_payload: bytes,
            candidate_digest: str,
            mode: int,
        ) -> guard_module.CommitRecord:
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise OSError("PRIVATE_FAILURE_DETAIL_MUST_NOT_LEAK")
            return real_commit(snapshot, candidate_payload, candidate_digest, mode)

        with patch.object(guard_module, "_commit_candidate", fail_second_commit):
            report = guard_module.migrate_runtime_env_ownership(
                compose_path=self.compose_path,
                managed_env_path=self.managed_path,
                secret_env_path=self.secret_path,
                postgres_env_path=self.postgres_path,
                apply=True,
                confirm=MIGRATION_APPLY_CONFIRMATION,
            )

        serialized = json.dumps(report, ensure_ascii=False)
        self.assertFalse(report["ok"])
        self.assertFalse(report["applied"])
        self.assertNotIn(database_sentinel, serialized)
        self.assertNotIn(backup_sentinel, serialized)
        self.assertNotIn("PRIVATE_FAILURE_DETAIL_MUST_NOT_LEAK", serialized)
        self.assertTrue(
            any(blocker.get("code") == "apply_atomic_replace_failed" for blocker in report["blockers"])
        )
        self.assertEqual(
            before,
            {
                self.managed_path: self.managed_path.read_bytes(),
                self.postgres_path: self.postgres_path.read_bytes(),
            },
        )

    def test_migrate_apply_detects_change_before_backup_and_preserves_concurrent_bytes(self) -> None:
        self._write_legal_fixture()
        sentinel = "STALE_BEFORE_BACKUP_MUST_NOT_LEAK"
        concurrent = b"JIEJING_BACKUP_POLICY_CONFIGURED=false\r\n"
        self.managed_path.write_text(
            "JIEJING_BACKUP_POLICY_CONFIGURED=true\n"
            f"JIEJING_DATABASE_URL={sentinel}\n",
            encoding="utf-8",
        )
        self.postgres_path.write_text(f"JIEJING_DATABASE_URL={sentinel}\n", encoding="utf-8")
        before_names = {path.name for path in self.managed_path.parent.iterdir()}
        real_verify = guard_module._verify_source_snapshots
        injected = False

        def inject_before_backup(*args: object, **kwargs: object) -> None:
            nonlocal injected
            if not injected:
                injected = True
                self.managed_path.write_bytes(concurrent)
            real_verify(*args, **kwargs)

        with patch.object(guard_module, "_verify_source_snapshots", inject_before_backup):
            report = guard_module.migrate_runtime_env_ownership(
                compose_path=self.compose_path,
                managed_env_path=self.managed_path,
                secret_env_path=self.secret_path,
                postgres_env_path=self.postgres_path,
                apply=True,
                confirm=MIGRATION_APPLY_CONFIRMATION,
            )

        serialized = json.dumps(report, ensure_ascii=False)
        self.assertFalse(report["ok"])
        self.assertFalse(report["applied"])
        self.assertNotIn(sentinel, serialized)
        self.assertTrue(any(blocker.get("code") == "apply_plan_stale" for blocker in report["blockers"]))
        self.assertEqual(self.managed_path.read_bytes(), concurrent)
        self.assertEqual(before_names, {path.name for path in self.managed_path.parent.iterdir()})

    def test_migrate_apply_preserves_concurrent_second_source_and_rolls_back_first(self) -> None:
        self._write_legal_fixture()
        database_sentinel = "SECOND_REPLACE_DATABASE_MUST_NOT_LEAK"
        backup_sentinel = "SECOND_REPLACE_BACKUP_MUST_NOT_LEAK"
        self.managed_path.write_text(
            f"JIEJING_BACKUP_POLICY_CONFIGURED={backup_sentinel}\n"
            f"JIEJING_DATABASE_URL={database_sentinel}\n",
            encoding="utf-8",
        )
        self.postgres_path.write_text(
            f"JIEJING_DATABASE_URL={database_sentinel}\n"
            f"JIEJING_BACKUP_POLICY_CONFIGURED={backup_sentinel}\n",
            encoding="utf-8",
        )
        postgres_before = self.postgres_path.read_bytes()
        concurrent_managed = b"JIEJING_BACKUP_POLICY_CONFIGURED=concurrent-owner-change\r\n"
        before_names = {path.name for path in self.managed_path.parent.iterdir()}
        real_verify = guard_module._verify_source_snapshots
        call_count = 0

        def inject_before_second_replace(*args: object, **kwargs: object) -> None:
            nonlocal call_count
            call_count += 1
            if call_count == 3:
                self.managed_path.write_bytes(concurrent_managed)
            real_verify(*args, **kwargs)

        with patch.object(guard_module, "_verify_source_snapshots", inject_before_second_replace):
            report = guard_module.migrate_runtime_env_ownership(
                compose_path=self.compose_path,
                managed_env_path=self.managed_path,
                secret_env_path=self.secret_path,
                postgres_env_path=self.postgres_path,
                apply=True,
                confirm=MIGRATION_APPLY_CONFIRMATION,
            )

        serialized = json.dumps(report, ensure_ascii=False)
        self.assertFalse(report["ok"])
        self.assertFalse(report["applied"])
        self.assertNotIn(database_sentinel, serialized)
        self.assertNotIn(backup_sentinel, serialized)
        self.assertTrue(
            any(blocker.get("code") == "apply_source_changed" for blocker in report["blockers"])
        )
        self.assertEqual(self.managed_path.read_bytes(), concurrent_managed)
        self.assertEqual(self.postgres_path.read_bytes(), postgres_before)
        backups = [
            path
            for path in self.managed_path.parent.iterdir()
            if path.name not in before_names
        ]
        self.assertEqual(len(backups), 2)

    def test_commit_helper_detects_change_after_outer_verify_without_replacing(self) -> None:
        self._write_legal_fixture()
        sentinel = "FINAL_COMMIT_COMPARE_MUST_NOT_LEAK"
        concurrent = b"JIEJING_BACKUP_POLICY_CONFIGURED=external-final-window\r\n"
        self.managed_path.write_text(
            "JIEJING_BACKUP_POLICY_CONFIGURED=true\n"
            f"JIEJING_DATABASE_URL={sentinel}\n",
            encoding="utf-8",
        )
        self.postgres_path.write_text(f"JIEJING_DATABASE_URL={sentinel}\n", encoding="utf-8")
        def inject_after_final_compare(snapshot: guard_module.SourceSnapshot) -> None:
            snapshot.path.write_bytes(concurrent)

        with patch.object(
            guard_module,
            "_guarded_commit_before_detach",
            inject_after_final_compare,
        ):
            report = guard_module.migrate_runtime_env_ownership(
                compose_path=self.compose_path,
                managed_env_path=self.managed_path,
                secret_env_path=self.secret_path,
                postgres_env_path=self.postgres_path,
                apply=True,
                confirm=MIGRATION_APPLY_CONFIRMATION,
            )

        serialized = json.dumps(report, ensure_ascii=False)
        self.assertFalse(report["ok"])
        self.assertFalse(report["applied"])
        self.assertNotIn(sentinel, serialized)
        self.assertTrue(any(blocker.get("code") == "apply_source_changed" for blocker in report["blockers"]))
        self.assertEqual(self.managed_path.read_bytes(), concurrent)
        self.assertFalse((self.managed_path.parent / ".jiejing-runtime-env-migration.lock").exists())

    def test_forward_install_no_clobber_preserves_target_created_after_detach(self) -> None:
        self._write_legal_fixture()
        sentinel = "FORWARD_INSTALL_RACE_MUST_NOT_LEAK"
        concurrent = b"JIEJING_BACKUP_POLICY_CONFIGURED=external-after-detach\r\n"
        self.managed_path.write_text(
            "JIEJING_BACKUP_POLICY_CONFIGURED=true\n"
            f"JIEJING_DATABASE_URL={sentinel}\n",
            encoding="utf-8",
        )
        self.postgres_path.write_text(f"JIEJING_DATABASE_URL={sentinel}\n", encoding="utf-8")

        def create_concurrent_target(
            snapshot: guard_module.SourceSnapshot,
            _backup_path: Path,
        ) -> None:
            snapshot.path.write_bytes(concurrent)

        with patch.object(
            guard_module,
            "_guarded_commit_before_install",
            create_concurrent_target,
        ):
            report = guard_module.migrate_runtime_env_ownership(
                compose_path=self.compose_path,
                managed_env_path=self.managed_path,
                secret_env_path=self.secret_path,
                postgres_env_path=self.postgres_path,
                apply=True,
                confirm=MIGRATION_APPLY_CONFIRMATION,
            )

        serialized = json.dumps(report, ensure_ascii=False)
        self.assertFalse(report["ok"])
        self.assertFalse(report["applied"])
        self.assertNotIn(sentinel, serialized)
        self.assertTrue(any(blocker.get("code") == "apply_install_conflict" for blocker in report["blockers"]))
        self.assertTrue(any(blocker.get("code") == "apply_recovery_conflict" for blocker in report["blockers"]))
        self.assertEqual(self.managed_path.read_bytes(), concurrent)

    def test_detached_backup_open_handle_drift_is_restored_without_overwrite(self) -> None:
        self._write_legal_fixture()
        sentinel = "DETACHED_BACKUP_DRIFT_MUST_NOT_LEAK"
        detached_drift = b"JIEJING_BACKUP_POLICY_CONFIGURED=open-handle-drift\r\n"
        self.managed_path.write_text(
            "JIEJING_BACKUP_POLICY_CONFIGURED=true\n"
            f"JIEJING_DATABASE_URL={sentinel}\n",
            encoding="utf-8",
        )
        self.postgres_path.write_text(f"JIEJING_DATABASE_URL={sentinel}\n", encoding="utf-8")

        def mutate_detached_backup(record: guard_module.CommitRecord) -> None:
            record.backup_path.write_bytes(detached_drift)

        with patch.object(
            guard_module,
            "_guarded_commit_after_install",
            mutate_detached_backup,
        ):
            report = guard_module.migrate_runtime_env_ownership(
                compose_path=self.compose_path,
                managed_env_path=self.managed_path,
                secret_env_path=self.secret_path,
                postgres_env_path=self.postgres_path,
                apply=True,
                confirm=MIGRATION_APPLY_CONFIRMATION,
            )

        serialized = json.dumps(report, ensure_ascii=False)
        self.assertFalse(report["ok"])
        self.assertFalse(report["applied"])
        self.assertNotIn(sentinel, serialized)
        self.assertTrue(
            any(blocker.get("code") == "apply_backup_source_changed" for blocker in report["blockers"])
        )
        self.assertEqual(self.managed_path.read_bytes(), detached_drift)

    def test_prepared_candidate_mutation_before_link_never_reaches_live_target(self) -> None:
        self._write_legal_fixture()
        sentinel = "PRELINK_CANDIDATE_MUTATION_MUST_NOT_LEAK"
        unplanned = b"JIEJING_BACKUP_POLICY_CONFIGURED=unplanned-prelink\r\n"
        self.managed_path.write_text(
            "JIEJING_BACKUP_POLICY_CONFIGURED=true\n"
            f"JIEJING_DATABASE_URL={sentinel}\n",
            encoding="utf-8",
        )
        self.postgres_path.write_text(f"JIEJING_DATABASE_URL={sentinel}\n", encoding="utf-8")
        original = self.managed_path.read_bytes()
        real_install = guard_module._install_artifact_no_clobber
        mutated = False

        def mutate_before_link(
            prepared: guard_module.PreparedCandidate,
            target: Path,
        ) -> guard_module.NamespaceMutationOutcome:
            nonlocal mutated
            if prepared.role == "candidate" and not mutated:
                mutated = True
                prepared.path.write_bytes(unplanned)
            return real_install(prepared, target)

        with patch.object(guard_module, "_install_artifact_no_clobber", mutate_before_link):
            report = guard_module.migrate_runtime_env_ownership(
                compose_path=self.compose_path,
                managed_env_path=self.managed_path,
                secret_env_path=self.secret_path,
                postgres_env_path=self.postgres_path,
                apply=True,
                confirm=MIGRATION_APPLY_CONFIRMATION,
            )

        serialized = json.dumps(report, ensure_ascii=False)
        self.assertFalse(report["ok"])
        self.assertFalse(report["applied"])
        self.assertNotIn(sentinel, serialized)
        self.assertNotIn("unplanned-prelink", serialized)
        self.assertTrue(any(blocker.get("code") == "apply_candidate_changed" for blocker in report["blockers"]))
        self.assertEqual(self.managed_path.read_bytes(), original)
        self.assertEqual(report["summary"]["backup_count"], 2)
        self.assertEqual(report["summary"]["artifact_counts"], {"backup": 1, "candidate": 1})

    def test_candidate_mutation_after_link_is_removed_from_live_target(self) -> None:
        self._write_legal_fixture()
        sentinel = "POSTLINK_CANDIDATE_MUTATION_MUST_NOT_LEAK"
        unplanned = b"JIEJING_BACKUP_POLICY_CONFIGURED=unplanned-postlink\r\n"
        self.managed_path.write_text(
            "JIEJING_BACKUP_POLICY_CONFIGURED=true\n"
            f"JIEJING_DATABASE_URL={sentinel}\n",
            encoding="utf-8",
        )
        self.postgres_path.write_text(f"JIEJING_DATABASE_URL={sentinel}\n", encoding="utf-8")
        original = self.managed_path.read_bytes()
        real_link = guard_module.os.link
        mutated = False

        def mutate_after_link(
            source: str | bytes | Path,
            target: str | bytes | Path,
            *args: object,
            **kwargs: object,
        ) -> None:
            nonlocal mutated
            real_link(source, target, *args, **kwargs)
            if not mutated:
                mutated = True
                Path(source).write_bytes(unplanned)

        with patch.object(guard_module.os, "link", mutate_after_link):
            report = guard_module.migrate_runtime_env_ownership(
                compose_path=self.compose_path,
                managed_env_path=self.managed_path,
                secret_env_path=self.secret_path,
                postgres_env_path=self.postgres_path,
                apply=True,
                confirm=MIGRATION_APPLY_CONFIRMATION,
            )

        serialized = json.dumps(report, ensure_ascii=False)
        self.assertFalse(report["ok"])
        self.assertFalse(report["applied"])
        self.assertNotIn(sentinel, serialized)
        self.assertNotIn("unplanned-postlink", serialized)
        self.assertTrue(any(blocker.get("code") == "apply_candidate_changed" for blocker in report["blockers"]))
        self.assertEqual(self.managed_path.read_bytes(), original)
        self.assertEqual(report["summary"]["backup_count"], 3)
        self.assertEqual(
            report["summary"]["artifact_counts"],
            {"backup": 1, "candidate": 1, "candidate_hold": 1},
        )

    def test_forward_detach_fsync_failure_restores_original_live_target(self) -> None:
        self._write_legal_fixture()
        sentinel = "DETACH_FSYNC_FAILURE_MUST_NOT_LEAK"
        self.managed_path.write_text(
            "JIEJING_BACKUP_POLICY_CONFIGURED=true\n"
            f"JIEJING_DATABASE_URL={sentinel}\n",
            encoding="utf-8",
        )
        self.postgres_path.write_text(f"JIEJING_DATABASE_URL={sentinel}\n", encoding="utf-8")
        original = self.managed_path.read_bytes()
        real_fsync_directory = guard_module._fsync_directory
        fsync_count = 0

        def fail_second_directory_fsync(directory: Path) -> None:
            nonlocal fsync_count
            fsync_count += 1
            if fsync_count == 2:
                raise OSError("PRIVATE_FORWARD_DETACH_FSYNC_FAILURE_MUST_NOT_LEAK")
            real_fsync_directory(directory)

        with patch.object(guard_module, "_fsync_directory", fail_second_directory_fsync):
            report = guard_module.migrate_runtime_env_ownership(
                compose_path=self.compose_path,
                managed_env_path=self.managed_path,
                secret_env_path=self.secret_path,
                postgres_env_path=self.postgres_path,
                apply=True,
                confirm=MIGRATION_APPLY_CONFIRMATION,
            )

        self.assertFalse(report["ok"])
        self.assertFalse(report["applied"])
        self.assertEqual(self.managed_path.read_bytes(), original)
        self.assertTrue(any(blocker.get("code") == "apply_durability_failed" for blocker in report["blockers"]))
        self.assertEqual(report["summary"]["backup_count"], 2)
        self.assertEqual(report["summary"]["artifact_counts"], {"backup": 1, "candidate": 1})
        self.assertFalse((self.managed_path.parent / ".jiejing-runtime-env-migration.lock").exists())

    def test_forward_link_fsync_failure_rolls_back_candidate_to_original(self) -> None:
        self._write_legal_fixture()
        sentinel = "LINK_FSYNC_FAILURE_MUST_NOT_LEAK"
        self.managed_path.write_text(
            "JIEJING_BACKUP_POLICY_CONFIGURED=true\n"
            f"JIEJING_DATABASE_URL={sentinel}\n",
            encoding="utf-8",
        )
        self.postgres_path.write_text(f"JIEJING_DATABASE_URL={sentinel}\n", encoding="utf-8")
        original = self.managed_path.read_bytes()
        real_fsync_directory = guard_module._fsync_directory
        fsync_count = 0

        def fail_third_directory_fsync(directory: Path) -> None:
            nonlocal fsync_count
            fsync_count += 1
            if fsync_count == 3:
                raise OSError("PRIVATE_FORWARD_LINK_FSYNC_FAILURE_MUST_NOT_LEAK")
            real_fsync_directory(directory)

        with patch.object(guard_module, "_fsync_directory", fail_third_directory_fsync):
            report = guard_module.migrate_runtime_env_ownership(
                compose_path=self.compose_path,
                managed_env_path=self.managed_path,
                secret_env_path=self.secret_path,
                postgres_env_path=self.postgres_path,
                apply=True,
                confirm=MIGRATION_APPLY_CONFIRMATION,
            )

        self.assertFalse(report["ok"])
        self.assertFalse(report["applied"])
        self.assertEqual(self.managed_path.read_bytes(), original)
        self.assertTrue(any(blocker.get("code") == "apply_durability_failed" for blocker in report["blockers"]))
        self.assertEqual(report["summary"]["backup_count"], 2)
        self.assertEqual(report["summary"]["artifact_counts"], {"backup": 1, "candidate_hold": 1})
        self.assertFalse((self.managed_path.parent / ".jiejing-runtime-env-migration.lock").exists())

    def test_commit_target_match_rejects_mid_read_mutation_with_same_size(self) -> None:
        self._write_legal_fixture()
        original = b"candidate-old-bytes"
        mutated = b"candidate-new-bytes"
        self.managed_path.write_bytes(original)
        target_stat = self.managed_path.stat()
        record = guard_module.CommitRecord(
            source="tencent-managed.env",
            path=self.managed_path,
            candidate_payload=original,
            candidate_digest=guard_module.hashlib.sha256(original).hexdigest(),
            physical_identity=(int(target_stat.st_dev), int(target_stat.st_ino)),
            candidate_metadata=(
                int(target_stat.st_size),
                int(target_stat.st_mtime_ns),
                stat.S_IMODE(target_stat.st_mode),
            ),
            backup_path=self.managed_path.parent / "unused-backup",
            candidate_artifact_path=self.managed_path.parent / "unused-candidate",
            mode=stat.S_IMODE(target_stat.st_mode),
        )
        real_read_bytes = Path.read_bytes
        mutated_once = False

        def mutate_after_first_read(path: Path) -> bytes:
            nonlocal mutated_once
            payload = real_read_bytes(path)
            if path == self.managed_path and not mutated_once:
                mutated_once = True
                path.write_bytes(mutated)
            return payload

        with patch.object(Path, "read_bytes", mutate_after_first_read):
            matches = guard_module._commit_target_matches(record)

        self.assertFalse(matches)
        self.assertEqual(self.managed_path.read_bytes(), mutated)

    def test_rollback_preserves_external_edit_after_first_commit_and_reports_conflict(self) -> None:
        self._write_legal_fixture()
        database_sentinel = "ROLLBACK_CONFLICT_DATABASE_MUST_NOT_LEAK"
        backup_sentinel = "ROLLBACK_CONFLICT_BACKUP_MUST_NOT_LEAK"
        self.managed_path.write_text(
            f"JIEJING_BACKUP_POLICY_CONFIGURED={backup_sentinel}\n"
            f"JIEJING_DATABASE_URL={database_sentinel}\n",
            encoding="utf-8",
        )
        self.postgres_path.write_text(
            f"JIEJING_DATABASE_URL={database_sentinel}\n"
            f"JIEJING_BACKUP_POLICY_CONFIGURED={backup_sentinel}\n",
            encoding="utf-8",
        )
        managed_before = self.managed_path.read_bytes()
        concurrent = b"JIEJING_DATABASE_URL=external-after-first-commit\r\n"
        real_commit = guard_module._commit_candidate
        call_count = 0

        def edit_first_then_fail_second(
            snapshot: guard_module.SourceSnapshot,
            candidate_payload: bytes,
            candidate_digest: str,
            mode: int,
        ) -> guard_module.CommitRecord:
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise OSError("PRIVATE_SECOND_COMMIT_FAILURE_MUST_NOT_LEAK")
            record = real_commit(snapshot, candidate_payload, candidate_digest, mode)
            snapshot.path.write_bytes(concurrent)
            return record

        with patch.object(guard_module, "_commit_candidate", edit_first_then_fail_second):
            report = guard_module.migrate_runtime_env_ownership(
                compose_path=self.compose_path,
                managed_env_path=self.managed_path,
                secret_env_path=self.secret_path,
                postgres_env_path=self.postgres_path,
                apply=True,
                confirm=MIGRATION_APPLY_CONFIRMATION,
            )

        serialized = json.dumps(report, ensure_ascii=False)
        self.assertFalse(report["ok"])
        self.assertFalse(report["applied"])
        self.assertNotIn(database_sentinel, serialized)
        self.assertNotIn(backup_sentinel, serialized)
        self.assertNotIn("PRIVATE_SECOND_COMMIT_FAILURE_MUST_NOT_LEAK", serialized)
        self.assertTrue(any(blocker.get("code") == "apply_atomic_replace_failed" for blocker in report["blockers"]))
        self.assertTrue(
            any(
                blocker.get("code") == "apply_rollback_source_changed"
                and blocker.get("source") == "postgres-localqueue.env"
                for blocker in report["blockers"]
            )
        )
        self.assertEqual(self.postgres_path.read_bytes(), concurrent)
        self.assertEqual(self.managed_path.read_bytes(), managed_before)

    def test_failed_replace_source_is_not_added_to_rollback_set(self) -> None:
        self._write_legal_fixture()
        sentinel = "FAILED_REPLACE_NOT_ROLLED_BACK_MUST_NOT_LEAK"
        self.managed_path.write_text(
            "JIEJING_BACKUP_POLICY_CONFIGURED=true\n"
            f"JIEJING_DATABASE_URL={sentinel}\n",
            encoding="utf-8",
        )
        self.postgres_path.write_text(f"JIEJING_DATABASE_URL={sentinel}\n", encoding="utf-8")
        before = self.managed_path.read_bytes()
        real_install = guard_module._install_artifact_no_clobber
        call_count = 0

        def fail_candidate_install_once(
            artifact: Path,
            target: Path,
        ) -> tuple[tuple[int, int], tuple[int, int, int]]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise OSError("PRIVATE_REPLACE_FAILURE_MUST_NOT_LEAK")
            return real_install(artifact, target)

        with patch.object(guard_module, "_install_artifact_no_clobber", fail_candidate_install_once):
            report = guard_module.migrate_runtime_env_ownership(
                compose_path=self.compose_path,
                managed_env_path=self.managed_path,
                secret_env_path=self.secret_path,
                postgres_env_path=self.postgres_path,
                apply=True,
                confirm=MIGRATION_APPLY_CONFIRMATION,
            )

        serialized = json.dumps(report, ensure_ascii=False)
        self.assertEqual(call_count, 2)
        self.assertFalse(report["ok"])
        self.assertNotIn(sentinel, serialized)
        self.assertNotIn("PRIVATE_REPLACE_FAILURE_MUST_NOT_LEAK", serialized)
        self.assertFalse(any(blocker.get("code", "").startswith("apply_rollback") for blocker in report["blockers"]))
        self.assertEqual(self.managed_path.read_bytes(), before)

    def test_migrate_apply_rolls_back_when_post_write_validation_fails(self) -> None:
        self._write_legal_fixture()
        sentinel = "VALIDATION_ROLLBACK_SENTINEL_MUST_NOT_LEAK"
        self.managed_path.write_text(
            "JIEJING_BACKUP_POLICY_CONFIGURED=true\n"
            f"JIEJING_DATABASE_URL={sentinel}\n",
            encoding="utf-8",
        )
        self.postgres_path.write_text(f"JIEJING_DATABASE_URL={sentinel}\n", encoding="utf-8")
        before = self.managed_path.read_bytes()
        real_build_plan = guard_module._build_migration_plan
        call_count = 0

        def fail_validation(**paths: Path) -> guard_module.MigrationPlan:
            nonlocal call_count
            call_count += 1
            plan = real_build_plan(**paths)
            if call_count == 2:
                return guard_module.MigrationPlan(
                    analysis=plan.analysis,
                    actions=(),
                    blockers=({"code": "synthetic_validation_failure", "source": "migration"},),
                )
            return plan

        with patch.object(guard_module, "_build_migration_plan", fail_validation):
            report = guard_module.migrate_runtime_env_ownership(
                compose_path=self.compose_path,
                managed_env_path=self.managed_path,
                secret_env_path=self.secret_path,
                postgres_env_path=self.postgres_path,
                apply=True,
                confirm=MIGRATION_APPLY_CONFIRMATION,
            )

        serialized = json.dumps(report, ensure_ascii=False)
        self.assertFalse(report["ok"])
        self.assertFalse(report["applied"])
        self.assertNotIn(sentinel, serialized)
        self.assertTrue(
            any(blocker.get("code") == "post_apply_validation_failed" for blocker in report["blockers"])
        )
        self.assertEqual(self.managed_path.read_bytes(), before)

    def test_rollback_restore_no_clobber_preserves_target_created_after_detach(self) -> None:
        self._write_legal_fixture()
        sentinel = "ROLLBACK_RESTORE_RACE_MUST_NOT_LEAK"
        concurrent = b"JIEJING_BACKUP_POLICY_CONFIGURED=external-during-rollback\r\n"
        self.managed_path.write_text(
            "JIEJING_BACKUP_POLICY_CONFIGURED=true\n"
            f"JIEJING_DATABASE_URL={sentinel}\n",
            encoding="utf-8",
        )
        self.postgres_path.write_text(f"JIEJING_DATABASE_URL={sentinel}\n", encoding="utf-8")
        real_build_plan = guard_module._build_migration_plan
        call_count = 0

        def fail_validation(**paths: Path) -> guard_module.MigrationPlan:
            nonlocal call_count
            call_count += 1
            plan = real_build_plan(**paths)
            if call_count == 2:
                return guard_module.MigrationPlan(
                    analysis=plan.analysis,
                    actions=(),
                    blockers=({"code": "synthetic_validation_failure", "source": "migration"},),
                )
            return plan

        def create_concurrent_target_before_restore(
            record: guard_module.CommitRecord,
            _candidate_hold: Path,
            _backup_path: Path,
        ) -> None:
            record.path.write_bytes(concurrent)

        with (
            patch.object(guard_module, "_build_migration_plan", fail_validation),
            patch.object(
                guard_module,
                "_guarded_rollback_before_restore",
                create_concurrent_target_before_restore,
            ),
        ):
            report = guard_module.migrate_runtime_env_ownership(
                compose_path=self.compose_path,
                managed_env_path=self.managed_path,
                secret_env_path=self.secret_path,
                postgres_env_path=self.postgres_path,
                apply=True,
                confirm=MIGRATION_APPLY_CONFIRMATION,
            )

        serialized = json.dumps(report, ensure_ascii=False)
        self.assertFalse(report["ok"])
        self.assertFalse(report["applied"])
        self.assertNotIn(sentinel, serialized)
        self.assertTrue(
            any(blocker.get("code") == "post_apply_validation_failed" for blocker in report["blockers"])
        )
        self.assertTrue(any(blocker.get("code") == "apply_rollback_conflict" for blocker in report["blockers"]))
        self.assertEqual(self.managed_path.read_bytes(), concurrent)

    def test_rollback_detach_fsync_failure_restores_candidate_live_target(self) -> None:
        self._write_legal_fixture()
        sentinel = "ROLLBACK_DETACH_FSYNC_MUST_NOT_LEAK"
        self.managed_path.write_text(
            "JIEJING_BACKUP_POLICY_CONFIGURED=true\n"
            f"JIEJING_DATABASE_URL={sentinel}\n",
            encoding="utf-8",
        )
        self.postgres_path.write_text(f"JIEJING_DATABASE_URL={sentinel}\n", encoding="utf-8")
        expected_candidate = b"JIEJING_BACKUP_POLICY_CONFIGURED=true\r\n"
        real_build_plan = guard_module._build_migration_plan
        real_fsync_directory = guard_module._fsync_directory
        build_count = 0
        fsync_count = 0

        def fail_validation(**paths: Path) -> guard_module.MigrationPlan:
            nonlocal build_count
            build_count += 1
            plan = real_build_plan(**paths)
            if build_count == 2:
                return guard_module.MigrationPlan(
                    analysis=plan.analysis,
                    actions=(),
                    blockers=({"code": "synthetic_validation_failure", "source": "migration"},),
                )
            return plan

        def fail_fourth_directory_fsync(directory: Path) -> None:
            nonlocal fsync_count
            fsync_count += 1
            if fsync_count == 4:
                raise OSError("PRIVATE_ROLLBACK_DETACH_FSYNC_FAILURE_MUST_NOT_LEAK")
            real_fsync_directory(directory)

        with (
            patch.object(guard_module, "_build_migration_plan", fail_validation),
            patch.object(
                guard_module,
                "_fsync_directory",
                fail_fourth_directory_fsync,
            ),
        ):
            report = guard_module.migrate_runtime_env_ownership(
                compose_path=self.compose_path,
                managed_env_path=self.managed_path,
                secret_env_path=self.secret_path,
                postgres_env_path=self.postgres_path,
                apply=True,
                confirm=MIGRATION_APPLY_CONFIRMATION,
            )

        serialized = json.dumps(report, ensure_ascii=False)
        self.assertFalse(report["ok"])
        self.assertFalse(report["applied"])
        self.assertNotIn(sentinel, serialized)
        self.assertEqual(self.managed_path.read_bytes(), expected_candidate)
        self.assertTrue(
            any(blocker.get("code") == "apply_rollback_durability_failed" for blocker in report["blockers"])
        )
        self.assertEqual(report["summary"]["backup_count"], 2)
        self.assertEqual(
            report["summary"]["artifact_counts"],
            {"backup": 1, "candidate_hold": 1},
        )
        self.assertFalse((self.managed_path.parent / ".jiejing-runtime-env-migration.lock").exists())

    def test_rollback_candidate_hold_drift_is_promoted_after_original_restore(self) -> None:
        self._write_legal_fixture()
        sentinel = "ROLLBACK_HOLD_DRIFT_MUST_NOT_LEAK"
        external = b"JIEJING_BACKUP_POLICY_CONFIGURED=external-open-handle\r\n"
        self.managed_path.write_text(
            "JIEJING_BACKUP_POLICY_CONFIGURED=true\n"
            f"JIEJING_DATABASE_URL={sentinel}\n",
            encoding="utf-8",
        )
        self.postgres_path.write_text(f"JIEJING_DATABASE_URL={sentinel}\n", encoding="utf-8")
        real_build_plan = guard_module._build_migration_plan
        build_count = 0

        def fail_validation(**paths: Path) -> guard_module.MigrationPlan:
            nonlocal build_count
            build_count += 1
            plan = real_build_plan(**paths)
            if build_count == 2:
                return guard_module.MigrationPlan(
                    analysis=plan.analysis,
                    actions=(),
                    blockers=({"code": "synthetic_validation_failure", "source": "migration"},),
                )
            return plan

        def mutate_candidate_hold(
            _record: guard_module.CommitRecord,
            candidate_hold: Path,
            _backup_path: Path,
        ) -> None:
            candidate_hold.write_bytes(external)

        with (
            patch.object(guard_module, "_build_migration_plan", fail_validation),
            patch.object(
                guard_module,
                "_guarded_rollback_before_restore",
                mutate_candidate_hold,
            ),
        ):
            report = guard_module.migrate_runtime_env_ownership(
                compose_path=self.compose_path,
                managed_env_path=self.managed_path,
                secret_env_path=self.secret_path,
                postgres_env_path=self.postgres_path,
                apply=True,
                confirm=MIGRATION_APPLY_CONFIRMATION,
            )

        serialized = json.dumps(report, ensure_ascii=False)
        self.assertFalse(report["ok"])
        self.assertFalse(report["applied"])
        self.assertNotIn(sentinel, serialized)
        self.assertNotIn("external-open-handle", serialized)
        self.assertEqual(self.managed_path.read_bytes(), external)
        self.assertTrue(
            any(blocker.get("code") == "apply_rollback_source_changed" for blocker in report["blockers"])
        )
        self.assertEqual(report["summary"]["backup_count"], 3)
        self.assertEqual(
            report["summary"]["artifact_counts"],
            {"backup": 1, "candidate_hold": 1, "rollback_recovery": 1},
        )

    def test_final_live_commit_revalidation_preserves_concurrent_edit(self) -> None:
        self._write_legal_fixture()
        sentinel = "FINAL_LIVE_REVALIDATION_MUST_NOT_LEAK"
        concurrent = b"JIEJING_BACKUP_POLICY_CONFIGURED=external-before-success\r\n"
        self.managed_path.write_text(
            "JIEJING_BACKUP_POLICY_CONFIGURED=true\n"
            f"JIEJING_DATABASE_URL={sentinel}\n",
            encoding="utf-8",
        )
        self.postgres_path.write_text(f"JIEJING_DATABASE_URL={sentinel}\n", encoding="utf-8")
        real_build_plan = guard_module._build_migration_plan
        build_count = 0

        def mutate_after_validation_read(**paths: Path) -> guard_module.MigrationPlan:
            nonlocal build_count
            build_count += 1
            plan = real_build_plan(**paths)
            if build_count == 2:
                self.managed_path.write_bytes(concurrent)
            return plan

        with patch.object(guard_module, "_build_migration_plan", mutate_after_validation_read):
            report = guard_module.migrate_runtime_env_ownership(
                compose_path=self.compose_path,
                managed_env_path=self.managed_path,
                secret_env_path=self.secret_path,
                postgres_env_path=self.postgres_path,
                apply=True,
                confirm=MIGRATION_APPLY_CONFIRMATION,
            )

        serialized = json.dumps(report, ensure_ascii=False)
        self.assertFalse(report["ok"])
        self.assertFalse(report["applied"])
        self.assertNotIn(sentinel, serialized)
        self.assertNotIn("external-before-success", serialized)
        self.assertEqual(self.managed_path.read_bytes(), concurrent)
        self.assertTrue(any(blocker.get("code") == "apply_commit_source_changed" for blocker in report["blockers"]))
        self.assertTrue(
            any(blocker.get("code") == "apply_rollback_source_changed" for blocker in report["blockers"])
        )

    def test_migrate_apply_rejects_symlink_source_without_path_leakage(self) -> None:
        self._write_legal_fixture()
        original_is_symlink = Path.is_symlink

        def simulated_is_symlink(path: Path) -> bool:
            return path == self.managed_path or original_is_symlink(path)

        with patch.object(Path, "is_symlink", simulated_is_symlink):
            report = guard_module.migrate_runtime_env_ownership(
                compose_path=self.compose_path,
                managed_env_path=self.managed_path,
                secret_env_path=self.secret_path,
                postgres_env_path=self.postgres_path,
                apply=True,
                confirm=MIGRATION_APPLY_CONFIRMATION,
            )

        serialized = json.dumps(report, ensure_ascii=False)
        self.assertFalse(report["ok"])
        self.assertFalse(report["applied"])
        self.assertNotIn(str(self.managed_path), serialized)
        self.assertTrue(
            any(
                blocker.get("code") == "source_symlink"
                and blocker.get("source") == "tencent-managed.env"
                for blocker in report["blockers"]
            )
        )

    def test_migrate_keeps_unknown_duplicate_as_fail_closed_blocker(self) -> None:
        self._write_legal_fixture()
        sentinel = "UNKNOWN_DUPLICATE_SENTINEL_MUST_NOT_LEAK"
        self.managed_path.write_text(
            "JIEJING_BACKUP_POLICY_CONFIGURED=true\n"
            f"JIEJING_LEGACY_UNCLASSIFIED={sentinel}\n",
            encoding="utf-8",
        )
        self.postgres_path.write_text(
            "JIEJING_DATABASE_URL=postgresql://LEGAL_DATABASE_SENTINEL/db\n"
            f"JIEJING_LEGACY_UNCLASSIFIED={sentinel}\n",
            encoding="utf-8",
        )

        completed = self._run_migrate()

        self.assertNotEqual(completed.returncode, 0)
        self.assertNotIn(sentinel, completed.stdout + completed.stderr)
        report = json.loads(completed.stdout)
        self.assertEqual(report["actions"], [])
        self.assertTrue(
            any(
                blocker.get("code") == "unknown_duplicate"
                and blocker.get("key") == "JIEJING_LEGACY_UNCLASSIFIED"
                and blocker.get("comparison") == "equal"
                for blocker in report["blockers"]
            )
        )

    def test_migrate_can_remove_multiple_equal_occurrences_from_wrong_source(self) -> None:
        self._write_legal_fixture()
        sentinel = "MULTIPLE_EQUAL_DUPLICATE_MUST_NOT_LEAK"
        self.managed_path.write_text(
            "JIEJING_BACKUP_POLICY_CONFIGURED=true\n"
            f"JIEJING_DATABASE_URL={sentinel}\n"
            f"JIEJING_DATABASE_URL={sentinel}\n",
            encoding="utf-8",
        )
        self.postgres_path.write_text(f"JIEJING_DATABASE_URL={sentinel}\n", encoding="utf-8")

        completed = self._run_migrate()

        self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)
        self.assertNotIn(sentinel, completed.stdout + completed.stderr)
        report = json.loads(completed.stdout)
        self.assertEqual(len(report["actions"]), 1)
        self.assertEqual(report["actions"][0]["count"], 2)
        self.assertEqual(report["actions"][0]["comparison"], "equal")

    def test_migrate_rejects_private_source_path_aliases_without_exposing_path(self) -> None:
        self._write_legal_fixture()

        report = guard_module.migrate_runtime_env_ownership(
            compose_path=self.compose_path,
            managed_env_path=self.managed_path,
            secret_env_path=self.secret_path,
            postgres_env_path=self.managed_path,
        )

        serialized = json.dumps(report, ensure_ascii=False)
        self.assertFalse(report["ok"])
        self.assertNotIn(str(self.managed_path), serialized)
        self.assertTrue(
            any(
                blocker.get("code") == "migration_source_path_alias"
                and set(blocker.get("sources", []))
                == {"postgres-localqueue.env", "tencent-managed.env"}
                for blocker in report["blockers"]
            )
        )

    def test_migrate_rejects_hardlinked_role_files_without_exposing_paths(self) -> None:
        self._write_legal_fixture()
        hardlink_path = self.managed_path.parent / "postgres-hardlink.env"
        try:
            hardlink_path.hardlink_to(self.managed_path)
        except (OSError, NotImplementedError) as error:
            self.skipTest(f"hardlinks unavailable: {type(error).__name__}")

        report = guard_module.migrate_runtime_env_ownership(
            compose_path=self.compose_path,
            managed_env_path=self.managed_path,
            secret_env_path=self.secret_path,
            postgres_env_path=hardlink_path,
        )

        serialized = json.dumps(report, ensure_ascii=False)
        self.assertFalse(report["ok"])
        self.assertNotIn(str(self.managed_path), serialized)
        self.assertNotIn(str(hardlink_path), serialized)
        self.assertTrue(
            any(
                blocker.get("code") == "migration_source_path_alias"
                and set(blocker.get("sources", []))
                == {"postgres-localqueue.env", "tencent-managed.env"}
                for blocker in report["blockers"]
            )
        )

    def test_migrate_rejects_mocked_parent_reparse_or_junction_without_path_leakage(self) -> None:
        self._write_legal_fixture()
        runtime_env_parent = self.managed_path.parent
        real_link_check = guard_module._path_is_link_or_reparse

        def simulated_reparse(path: Path) -> bool:
            return path == runtime_env_parent or real_link_check(path)

        with patch.object(guard_module, "_path_is_link_or_reparse", simulated_reparse):
            report = guard_module.migrate_runtime_env_ownership(
                compose_path=self.compose_path,
                managed_env_path=self.managed_path,
                secret_env_path=self.secret_path,
                postgres_env_path=self.postgres_path,
            )

        serialized = json.dumps(report, ensure_ascii=False)
        self.assertFalse(report["ok"])
        for path in (self.managed_path, self.secret_path, self.postgres_path):
            self.assertNotIn(str(path), serialized)
        blocked_sources = {
            blocker.get("source")
            for blocker in report["blockers"]
            if blocker.get("code") == "source_parent_link"
        }
        self.assertEqual(
            blocked_sources,
            {
                "tencent-managed.env",
                "jiejing-saas.staging-oauth.env",
                "postgres-localqueue.env",
            },
        )

    def test_migrate_defers_wrong_source_compose_declaration_without_action(self) -> None:
        self._write_legal_fixture()
        sentinel = "COMPOSE_MIGRATION_DEFERRED_MUST_NOT_LEAK"
        text = self.compose_path.read_text(encoding="utf-8")
        needle = '      JIEJING_BILLING_PROVIDER: "stripe_test_mock"\n'
        self.compose_path.write_text(
            text.replace(needle, needle + f'      JIEJING_DATABASE_URL: "{sentinel}"\n', 1),
            encoding="utf-8",
        )
        self.postgres_path.write_text(f"JIEJING_DATABASE_URL={sentinel}\n", encoding="utf-8")

        completed = self._run_migrate(augment_legacy_contract=False)

        self.assertNotEqual(completed.returncode, 0)
        self.assertNotIn(sentinel, completed.stdout + completed.stderr)
        report = json.loads(completed.stdout)
        self.assertEqual(report["actions"], [])
        self.assertTrue(
            any(
                blocker.get("code") == "compose_migration_deferred"
                and blocker.get("key") == "JIEJING_DATABASE_URL"
                and blocker.get("source") == "compose:jiejing-saas"
                for blocker in report["blockers"]
            )
        )

    def test_migration_plan_and_snapshot_repr_hide_bytes_digests_bindings_and_paths(self) -> None:
        self._write_legal_fixture()
        sentinel = "MIGRATION_REPR_SENTINEL_MUST_NOT_LEAK"
        self.managed_path.write_text(
            "JIEJING_BACKUP_POLICY_CONFIGURED=true\n"
            f"JIEJING_DATABASE_URL={sentinel}\n",
            encoding="utf-8",
        )
        self.postgres_path.write_text(f"JIEJING_DATABASE_URL={sentinel}\n", encoding="utf-8")

        plan = guard_module._build_migration_plan(
            compose_path=self.compose_path,
            managed_env_path=self.managed_path,
            secret_env_path=self.secret_path,
            postgres_env_path=self.postgres_path,
        )

        rendered = repr(plan) + "\n" + "\n".join(repr(action) for action in plan.actions)
        self.assertNotIn(sentinel, rendered)
        for path in (self.compose_path, self.managed_path, self.secret_path, self.postgres_path):
            self.assertNotIn(str(path), rendered)
        self.assertNotIn("line_digest", rendered)
        self.assertNotIn("payload", rendered)

    def test_check_accepts_legal_three_file_ownership(self) -> None:
        self._write_legal_fixture()

        completed = self._run_check()

        self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)
        report = json.loads(completed.stdout)
        self.assertTrue(report["ok"])
        self.assertEqual(report["summary"]["blocker_count"], 0)
        self.assertFalse(report["secret_exposed"])

    def test_check_blocks_duplicate_key_within_one_file(self) -> None:
        self._write_legal_fixture()
        self.managed_path.write_text(
            "JIEJING_BACKUP_POLICY_CONFIGURED=true\n"
            "JIEJING_BACKUP_POLICY_CONFIGURED=false\n",
            encoding="utf-8",
        )

        completed = self._run_check()

        self.assertNotEqual(completed.returncode, 0)
        report = json.loads(completed.stdout)
        self.assertFalse(report["ok"])
        self.assertTrue(
            any(
                blocker.get("code") == "same_source_duplicate"
                and blocker.get("key") == "JIEJING_BACKUP_POLICY_CONFIGURED"
                for blocker in report["blockers"]
            )
        )

    def test_check_blocks_key_repeated_across_private_sources(self) -> None:
        self._write_legal_fixture()
        self.managed_path.write_text(
            "JIEJING_BACKUP_POLICY_CONFIGURED=true\n"
            "JIEJING_LEGACY_UNCLASSIFIED=MANAGED_SENTINEL\n",
            encoding="utf-8",
        )
        self.secret_path.write_text(
            "JIEJING_EBAY_CLIENT_SECRET=LEGAL_SECRET_SENTINEL\n"
            "JIEJING_LEGACY_UNCLASSIFIED=SECRET_SENTINEL\n",
            encoding="utf-8",
        )

        completed = self._run_check()

        self.assertNotEqual(completed.returncode, 0)
        report = json.loads(completed.stdout)
        self.assertTrue(
            any(
                blocker.get("code") == "cross_source_duplicate"
                and blocker.get("key") == "JIEJING_LEGACY_UNCLASSIFIED"
                for blocker in report["blockers"]
            )
        )
        self.assertFalse(
            any(
                warning.get("code") == "unknown_unique_key"
                and warning.get("key") == "JIEJING_LEGACY_UNCLASSIFIED"
                for warning in report["warnings"]
            )
        )

    def test_duplicate_summary_counts_unique_keys_not_blocker_records(self) -> None:
        self._write_legal_fixture()
        self.managed_path.write_text(
            "JIEJING_BACKUP_POLICY_CONFIGURED=true\n"
            "JIEJING_LEGACY_UNCLASSIFIED=FIRST_SENTINEL\n"
            "JIEJING_LEGACY_UNCLASSIFIED=SECOND_SENTINEL\n",
            encoding="utf-8",
        )
        self.secret_path.write_text(
            "JIEJING_EBAY_CLIENT_SECRET=LEGAL_SECRET_SENTINEL\n"
            "JIEJING_LEGACY_UNCLASSIFIED=THIRD_SENTINEL\n",
            encoding="utf-8",
        )

        completed = self._run_check()

        self.assertNotEqual(completed.returncode, 0)
        report = json.loads(completed.stdout)
        duplicate_blockers = [
            blocker
            for blocker in report["blockers"]
            if blocker.get("key") == "JIEJING_LEGACY_UNCLASSIFIED"
            and blocker.get("code") in {"same_source_duplicate", "cross_source_duplicate"}
        ]
        self.assertEqual(len(duplicate_blockers), 2)
        self.assertEqual(report["summary"]["unauthorized_duplicate_count"], 1)

    def test_report_classifies_conflict_without_exposing_values(self) -> None:
        self._write_legal_fixture()
        sentinels = (
            "MANAGED_VALUE_MUST_NEVER_LEAK",
            "POSTGRES_VALUE_MUST_NEVER_LEAK",
            "EBAY_SECRET_MUST_NEVER_LEAK",
        )
        self.managed_path.write_text(
            "JIEJING_BACKUP_POLICY_CONFIGURED=true\n"
            f"JIEJING_DATABASE_URL={sentinels[0]}\n",
            encoding="utf-8",
        )
        self.secret_path.write_text(
            f"JIEJING_EBAY_CLIENT_SECRET={sentinels[2]}\n",
            encoding="utf-8",
        )
        self.postgres_path.write_text(
            f"JIEJING_DATABASE_URL={sentinels[1]}\n",
            encoding="utf-8",
        )

        completed = self._run_check()

        self.assertNotEqual(completed.returncode, 0)
        combined_output = completed.stdout + completed.stderr
        for sentinel in sentinels:
            self.assertNotIn(sentinel, combined_output)
        report = json.loads(completed.stdout)
        duplicate = next(
            blocker
            for blocker in report["blockers"]
            if blocker.get("code") == "cross_source_duplicate"
            and blocker.get("key") == "JIEJING_DATABASE_URL"
        )
        self.assertEqual(duplicate["comparison"], "conflict")
        report_keys = _all_json_keys(report)
        forbidden_fields = sorted(key for key in report_keys if _looks_like_value_field(key))
        self.assertEqual(forbidden_fields, [])

    def test_inline_compose_environment_cannot_hide_true_write_clamp(self) -> None:
        self._write_legal_fixture()
        self.compose_path.write_text(
            """services:
  jiejing-saas:
    environment: {JIEJING_ENABLE_REAL_PLATFORM_WRITES: \"true\"}
""",
            encoding="utf-8",
        )

        completed = self._run_check()

        self.assertNotEqual(completed.returncode, 0)
        report = json.loads(completed.stdout)
        self.assertTrue(
            any(
                blocker.get("code") == "unsupported_inline_compose_environment"
                for blocker in report["blockers"]
            )
        )

    def test_genuinely_unknown_compose_static_key_is_warning_only(self) -> None:
        self._write_legal_fixture()
        self.compose_path.write_text(
            """services:
  jiejing-saas:
    environment:
      JIEJING_ENABLE_REAL_PLATFORM_WRITES: \"false\"
      JIEJING_EBAY_WRITE_LIVE: \"false\"
      JIEJING_PUBLIC_STAGING_REAL_WRITE_POLICY: \"disabled_public_staging\"
      JIEJING_SELECTED_DOMAIN: \"jiejing.shop\"
  jiejing-worker:
    environment:
      JIEJING_ENABLE_REAL_PLATFORM_WRITES: \"false\"
      JIEJING_EBAY_WRITE_LIVE: \"false\"
      JIEJING_PUBLIC_STAGING_REAL_WRITE_POLICY: \"disabled_public_staging\"
""",
            encoding="utf-8",
        )

        completed = self._run_check()

        self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)
        report = json.loads(completed.stdout)
        self.assertTrue(
            any(
                warning.get("code") == "compose_static_key"
                and warning.get("key") == "JIEJING_SELECTED_DOMAIN"
                for warning in report["warnings"]
            )
        )

    def test_ebay_client_secret_in_compose_is_wrong_source_blocker(self) -> None:
        self._write_legal_fixture()
        self.compose_path.write_text(
            """services:
  jiejing-saas:
    environment:
      JIEJING_ENABLE_REAL_PLATFORM_WRITES: \"false\"
      JIEJING_EBAY_WRITE_LIVE: \"false\"
      JIEJING_PUBLIC_STAGING_REAL_WRITE_POLICY: \"disabled_public_staging\"
      JIEJING_EBAY_CLIENT_SECRET: \"COMPOSE_SECRET_MUST_NOT_LEAK\"
""",
            encoding="utf-8",
        )

        completed = self._run_check()

        self.assertNotEqual(completed.returncode, 0)
        self.assertNotIn("COMPOSE_SECRET_MUST_NOT_LEAK", completed.stdout + completed.stderr)
        report = json.loads(completed.stdout)
        self.assertTrue(
            any(
                blocker.get("code") == "wrong_source"
                and blocker.get("key") == "JIEJING_EBAY_CLIENT_SECRET"
                and blocker.get("owner") == "jiejing-saas.staging-oauth.env"
                for blocker in report["blockers"]
            )
        )

    def test_database_url_in_compose_is_wrong_source_blocker(self) -> None:
        self._write_legal_fixture()
        self.compose_path.write_text(
            """services:
  jiejing-worker:
    environment:
      JIEJING_ENABLE_REAL_PLATFORM_WRITES: \"false\"
      JIEJING_EBAY_WRITE_LIVE: \"false\"
      JIEJING_PUBLIC_STAGING_REAL_WRITE_POLICY: \"disabled_public_staging\"
      JIEJING_DATABASE_URL: \"DATABASE_COMPOSE_VALUE_MUST_NOT_LEAK\"
""",
            encoding="utf-8",
        )

        completed = self._run_check()

        self.assertNotEqual(completed.returncode, 0)
        self.assertNotIn("DATABASE_COMPOSE_VALUE_MUST_NOT_LEAK", completed.stdout + completed.stderr)
        report = json.loads(completed.stdout)
        self.assertTrue(
            any(
                blocker.get("code") == "wrong_source"
                and blocker.get("key") == "JIEJING_DATABASE_URL"
                and blocker.get("owner") == "postgres-localqueue.env"
                for blocker in report["blockers"]
            )
        )

    def test_summary_has_stable_guardrail_counters(self) -> None:
        self._write_legal_fixture()
        self.managed_path.write_text(
            "JIEJING_BACKUP_POLICY_CONFIGURED=true\n"
            "JIEJING_DATABASE_URL=WRONG_SOURCE_SENTINEL\n",
            encoding="utf-8",
        )
        self.compose_path.write_text(
            """services:
  jiejing-saas:
    environment:
      JIEJING_ENABLE_REAL_PLATFORM_WRITES: \"true\"
      JIEJING_EBAY_WRITE_LIVE: \"false\"
      JIEJING_PUBLIC_STAGING_REAL_WRITE_POLICY: \"disabled_public_staging\"
  jiejing-worker:
    environment:
      JIEJING_ENABLE_REAL_PLATFORM_WRITES: \"false\"
      JIEJING_EBAY_WRITE_LIVE: \"false\"
      JIEJING_PUBLIC_STAGING_REAL_WRITE_POLICY: \"disabled_public_staging\"
""",
            encoding="utf-8",
        )

        completed = self._run_check()

        self.assertNotEqual(completed.returncode, 0)
        report = json.loads(completed.stdout)
        self.assertEqual(report["summary"]["unauthorized_duplicate_count"], 1)
        self.assertEqual(report["summary"]["wrong_source_count"], 1)
        self.assertEqual(report["summary"]["illegal_compose_override_count"], 2)

    def test_check_blocks_known_key_in_wrong_private_source(self) -> None:
        self._write_legal_fixture()
        self.managed_path.write_text(
            "JIEJING_BACKUP_POLICY_CONFIGURED=true\n"
            "JIEJING_DATABASE_ENGINE=postgres\n",
            encoding="utf-8",
        )

        completed = self._run_check()

        self.assertNotEqual(completed.returncode, 0)
        report = json.loads(completed.stdout)
        self.assertEqual(report["summary"]["wrong_source_count"], 1)
        self.assertTrue(
            any(
                blocker.get("code") == "wrong_source"
                and blocker.get("key") == "JIEJING_DATABASE_ENGINE"
                and blocker.get("owner") == "postgres-localqueue.env"
                for blocker in report["blockers"]
            )
        )

    def test_false_compose_safety_mapping_passes(self) -> None:
        self._write_legal_fixture()

        completed = self._run_check()

        self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)
        report = json.loads(completed.stdout)
        self.assertEqual(report["summary"]["unsafe_compose_override_count"], 0)
        self.assertEqual(report["summary"]["illegal_compose_override_count"], 0)

    def test_true_compose_safety_mapping_fails(self) -> None:
        self._write_legal_fixture()
        self.compose_path.write_text(
            """services:
  jiejing-saas:
    environment:
      JIEJING_ENABLE_REAL_PLATFORM_WRITES: \"true\"
      JIEJING_EBAY_WRITE_LIVE: \"false\"
      JIEJING_PUBLIC_STAGING_REAL_WRITE_POLICY: \"disabled_public_staging\"
  jiejing-worker:
    environment:
      JIEJING_ENABLE_REAL_PLATFORM_WRITES: \"false\"
      JIEJING_EBAY_WRITE_LIVE: \"false\"
      JIEJING_PUBLIC_STAGING_REAL_WRITE_POLICY: \"disabled_public_staging\"
""",
            encoding="utf-8",
        )

        completed = self._run_check()

        self.assertNotEqual(completed.returncode, 0)
        report = json.loads(completed.stdout)
        self.assertEqual(report["summary"]["unsafe_compose_override_count"], 1)
        self.assertEqual(report["summary"]["illegal_compose_override_count"], 2)
        self.assertTrue(
            any(
                blocker.get("code") == "unsafe_compose_override"
                and blocker.get("key") == "JIEJING_ENABLE_REAL_PLATFORM_WRITES"
                for blocker in report["blockers"]
            )
        )

    def test_missing_private_source_fails_closed(self) -> None:
        self._write_legal_fixture()
        self.managed_path.unlink()

        completed = self._run_check()

        self.assertNotEqual(completed.returncode, 0)
        report = json.loads(completed.stdout)
        self.assertTrue(
            any(
                blocker.get("code") == "source_missing"
                and blocker.get("source") == "tencent-managed.env"
                for blocker in report["blockers"]
            )
        )

    def test_non_utf8_private_source_fails_unreadable_without_leak(self) -> None:
        self._write_legal_fixture()
        self.secret_path.write_bytes(b"\xff\xfeSECRET_BINARY_SENTINEL")

        completed = self._run_check()

        self.assertNotEqual(completed.returncode, 0)
        self.assertNotIn("SECRET_BINARY_SENTINEL", completed.stdout + completed.stderr)
        report = json.loads(completed.stdout)
        self.assertTrue(
            any(
                blocker.get("code") == "source_unreadable"
                and blocker.get("source") == "jiejing-saas.staging-oauth.env"
                for blocker in report["blockers"]
            )
        )

    def test_malformed_env_line_fails_closed(self) -> None:
        self._write_legal_fixture()
        self.postgres_path.write_text("BROKEN ENV LINE\n", encoding="utf-8")

        completed = self._run_check()

        self.assertNotEqual(completed.returncode, 0)
        report = json.loads(completed.stdout)
        self.assertTrue(
            any(
                blocker.get("code") == "invalid_env_syntax"
                and blocker.get("source") == "postgres-localqueue.env"
                for blocker in report["blockers"]
            )
        )

    def test_compose_environment_list_form_is_checked(self) -> None:
        self._write_legal_fixture()
        self.compose_path.write_text(
            """services:
  jiejing-saas:
    environment:
      - JIEJING_ENABLE_REAL_PLATFORM_WRITES=false
      - JIEJING_EBAY_WRITE_LIVE=false
      - JIEJING_PUBLIC_STAGING_REAL_WRITE_POLICY=disabled_public_staging
  jiejing-worker:
    environment:
      JIEJING_ENABLE_REAL_PLATFORM_WRITES: \"false\"
      JIEJING_EBAY_WRITE_LIVE: \"false\"
      JIEJING_PUBLIC_STAGING_REAL_WRITE_POLICY: \"disabled_public_staging\"
""",
            encoding="utf-8",
        )

        completed = self._run_check()

        self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)
        report = json.loads(completed.stdout)
        self.assertEqual(report["summary"]["illegal_compose_override_count"], 0)

    def test_commented_compose_environment_header_is_checked(self) -> None:
        self._write_legal_fixture()
        self.compose_path.write_text(
            """services:
  jiejing-saas:
    environment: # safety clamps stay fail-closed
      JIEJING_ENABLE_REAL_PLATFORM_WRITES: \"false\"
      JIEJING_EBAY_WRITE_LIVE: \"false\"
      JIEJING_PUBLIC_STAGING_REAL_WRITE_POLICY: \"disabled_public_staging\"
  jiejing-worker:
    environment:
      JIEJING_ENABLE_REAL_PLATFORM_WRITES: \"false\"
      JIEJING_EBAY_WRITE_LIVE: \"false\"
      JIEJING_PUBLIC_STAGING_REAL_WRITE_POLICY: \"disabled_public_staging\"
""",
            encoding="utf-8",
        )

        completed = self._run_check()

        self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)
        report = json.loads(completed.stdout)
        self.assertEqual(report["summary"]["illegal_compose_override_count"], 0)

    def test_malformed_compose_environment_entry_fails_closed(self) -> None:
        self._write_legal_fixture()
        self.compose_path.write_text(
            """services:
  jiejing-saas:
    environment:
      - BROKEN_LIST_ENTRY
  jiejing-worker:
    environment:
      JIEJING_ENABLE_REAL_PLATFORM_WRITES: \"false\"
      JIEJING_EBAY_WRITE_LIVE: \"false\"
      JIEJING_PUBLIC_STAGING_REAL_WRITE_POLICY: \"disabled_public_staging\"
""",
            encoding="utf-8",
        )

        completed = self._run_check()

        self.assertNotEqual(completed.returncode, 0)
        report = json.loads(completed.stdout)
        self.assertEqual(report["summary"]["illegal_compose_override_count"], 4)
        self.assertTrue(
            any(
                blocker.get("code") == "invalid_compose_environment_syntax"
                for blocker in report["blockers"]
            )
        )

    def test_compose_without_services_section_fails_closed(self) -> None:
        self._write_legal_fixture()
        self.compose_path.write_text("name: invalid-compose-fixture\n", encoding="utf-8")

        completed = self._run_check()

        self.assertNotEqual(completed.returncode, 0)
        report = json.loads(completed.stdout)
        self.assertTrue(
            any(
                blocker.get("code") == "missing_compose_services_section"
                for blocker in report["blockers"]
            )
        )

    def test_runtime_service_without_environment_is_missing_all_required_clamps(self) -> None:
        self._write_legal_fixture()
        self.compose_path.write_text(
            """services:
  jiejing-saas:
    image: jiejing-saas:test
  jiejing-frontend:
    environment:
      JIEJING_PUBLIC_BASE_URL: \"https://app.jiejing.shop\"
""",
            encoding="utf-8",
        )

        completed = self._run_check()

        self.assertNotEqual(completed.returncode, 0)
        report = json.loads(completed.stdout)
        missing = [
            blocker
            for blocker in report["blockers"]
            if blocker.get("code") == "missing_required_compose_clamp"
            and blocker.get("service") == "jiejing-saas"
        ]
        self.assertEqual(len(missing), 3)
        self.assertFalse(
            any(
                blocker.get("code") == "missing_required_compose_clamp"
                and blocker.get("service") == "jiejing-frontend"
                for blocker in report["blockers"]
            )
        )

    def test_missing_one_clamp_is_scoped_to_the_runtime_service(self) -> None:
        self._write_legal_fixture()
        self.compose_path.write_text(
            """services:
    jiejing-saas:
        environment:
            JIEJING_ENABLE_REAL_PLATFORM_WRITES: \"false\"
            JIEJING_EBAY_WRITE_LIVE: \"false\"
            JIEJING_PUBLIC_STAGING_REAL_WRITE_POLICY: \"disabled_public_staging\"
    jiejing-worker:
        environment:
            JIEJING_ENABLE_REAL_PLATFORM_WRITES: \"false\"
            JIEJING_EBAY_WRITE_LIVE: \"false\"
    jiejing-frontend:
        image: nginx:test
""",
            encoding="utf-8",
        )

        completed = self._run_check()

        self.assertNotEqual(completed.returncode, 0)
        report = json.loads(completed.stdout)
        missing = [
            blocker
            for blocker in report["blockers"]
            if blocker.get("code") == "missing_required_compose_clamp"
        ]
        self.assertEqual(len(missing), 1)
        self.assertEqual(missing[0]["service"], "jiejing-worker")
        self.assertEqual(missing[0]["key"], "JIEJING_PUBLIC_STAGING_REAL_WRITE_POLICY")

    def test_multiple_runtime_services_with_four_space_indent_and_false_clamps_pass(self) -> None:
        self._write_legal_fixture()
        self.compose_path.write_text(
            """services:
    jiejing-saas:
        environment:
            - JIEJING_ENABLE_REAL_PLATFORM_WRITES=false
            - JIEJING_EBAY_WRITE_LIVE=false
            - JIEJING_PUBLIC_STAGING_REAL_WRITE_POLICY=disabled_public_staging
    jiejing-worker:
        environment: # separate runtime contract
            JIEJING_ENABLE_REAL_PLATFORM_WRITES: \"false\"
            JIEJING_EBAY_WRITE_LIVE: \"false\"
            JIEJING_PUBLIC_STAGING_REAL_WRITE_POLICY: \"disabled_public_staging\"
    jiejing-frontend:
        image: nginx:test
""",
            encoding="utf-8",
        )

        completed = self._run_check()

        self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)
        report = json.loads(completed.stdout)
        self.assertEqual(report["summary"]["illegal_compose_override_count"], 0)

    def test_wechat_charge_allowed_true_is_forbidden_in_staging(self) -> None:
        self._write_legal_fixture()
        self.secret_path.write_text(
            "JIEJING_EBAY_CLIENT_SECRET=LEGAL_SECRET_SENTINEL\n"
            "JIEJING_WECHAT_PAY_CHARGE_ALLOWED=true\n",
            encoding="utf-8",
        )

        completed = self._run_check()

        self.assertNotEqual(completed.returncode, 0)
        report = json.loads(completed.stdout)
        self.assertEqual(report["summary"]["illegal_compose_override_count"], 0)
        self.assertTrue(
            any(
                blocker.get("code") == "forbidden_staging_value"
                and blocker.get("key") == "JIEJING_WECHAT_PAY_CHARGE_ALLOWED"
                for blocker in report["blockers"]
            )
        )

    def test_optional_high_risk_toggle_false_passes_in_its_owner(self) -> None:
        self._write_legal_fixture()
        self.secret_path.write_text(
            "JIEJING_EBAY_CLIENT_SECRET=LEGAL_SECRET_SENTINEL\n"
            "JIEJING_WECHAT_PAY_CHARGE_ALLOWED=false\n",
            encoding="utf-8",
        )

        completed = self._run_check()

        self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)
        report = json.loads(completed.stdout)
        self.assertEqual(report["summary"]["forbidden_staging_value_count"], 0)

    def test_documented_public_charging_true_is_forbidden_wherever_declared(self) -> None:
        self._write_legal_fixture()
        self.managed_path.write_text(
            "JIEJING_BACKUP_POLICY_CONFIGURED=true\n"
            "JIEJING_PUBLIC_CHARGING_ALLOWED=true\n",
            encoding="utf-8",
        )

        completed = self._run_check()

        self.assertNotEqual(completed.returncode, 0)
        report = json.loads(completed.stdout)
        self.assertTrue(
            any(
                blocker.get("code") == "forbidden_staging_value"
                and blocker.get("key") == "JIEJING_PUBLIC_CHARGING_ALLOWED"
                for blocker in report["blockers"]
            )
        )

    def test_explicit_payment_refund_purchase_and_media_generation_toggles_block_true(self) -> None:
        for key in (
            "JIEJING_DOMESTIC_PAYMENT_LIVE_CUTOVER_APPROVED",
            "JIEJING_MANUAL_QR_COLLECTION_ENABLED",
            "JIEJING_WECHAT_PAY_REFUND_ALLOWED",
            "JIEJING_MEDIA_CREDIT_PURCHASE_ENABLED",
            "JIEJING_MEDIA_GENERATION_LIVE",
        ):
            with self.subTest(key=key):
                self._write_legal_fixture()
                self.secret_path.write_text(
                    "JIEJING_EBAY_CLIENT_SECRET=LEGAL_SECRET_SENTINEL\n"
                    f"{key}=true\n",
                    encoding="utf-8",
                )

                completed = self._run_check()

                self.assertNotEqual(completed.returncode, 0)
                report = json.loads(completed.stdout)
                self.assertTrue(
                    any(
                        blocker.get("code") == "forbidden_staging_value"
                        and blocker.get("key") == key
                        for blocker in report["blockers"]
                    )
                )

    def test_internal_analysis_exposes_reusable_value_private_key_groups(self) -> None:
        self._write_legal_fixture()

        analysis = analyze_runtime_env_ownership(
            compose_path=self.compose_path,
            managed_env_path=self.managed_path,
            secret_env_path=self.secret_path,
            postgres_env_path=self.postgres_path,
        )

        self.assertIsInstance(analysis, GuardAnalysis)
        database = next(key_analysis for key_analysis in analysis.keys if key_analysis.key == "JIEJING_DATABASE_URL")
        self.assertEqual(database.owner, "postgres-localqueue.env")
        self.assertEqual(database.comparison, "equal")
        self.assertEqual(database.source_roles, ("postgres-localqueue.env",))
        self.assertEqual(len(database.source_groups), 1)

    def test_media_live_capabilities_are_secret_owned_without_false_constraint(self) -> None:
        self._write_legal_fixture()
        self.secret_path.write_text(
            "JIEJING_EBAY_CLIENT_SECRET=LEGAL_SECRET_SENTINEL\n"
            "JIEJING_MEDIA_LIVE_PROVIDER_ENABLED=true\n"
            "JIEJING_MEDIA_LIVE_VIDEO_ENABLED=true\n",
            encoding="utf-8",
        )

        completed = self._run_check()

        self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)
        report = json.loads(completed.stdout)
        for key in ("JIEJING_MEDIA_LIVE_PROVIDER_ENABLED", "JIEJING_MEDIA_LIVE_VIDEO_ENABLED"):
            declaration = next(item for item in report["declarations"] if item.get("key") == key)
            self.assertEqual(declaration["owner"], "jiejing-saas.staging-oauth.env")
            self.assertFalse(
                any(
                    blocker.get("code") == "forbidden_staging_value"
                    and blocker.get("key") == key
                    for blocker in report["blockers"]
                )
            )

    def test_media_live_capabilities_in_compose_are_migration_blockers_only(self) -> None:
        self._write_legal_fixture()
        self.compose_path.write_text(
            """services:
  jiejing-saas:
    environment:
      JIEJING_ENABLE_REAL_PLATFORM_WRITES: \"false\"
      JIEJING_EBAY_WRITE_LIVE: \"false\"
      JIEJING_PUBLIC_STAGING_REAL_WRITE_POLICY: \"disabled_public_staging\"
      JIEJING_MEDIA_LIVE_PROVIDER_ENABLED: \"true\"
      JIEJING_MEDIA_LIVE_VIDEO_ENABLED: \"true\"
  jiejing-worker:
    environment:
      JIEJING_ENABLE_REAL_PLATFORM_WRITES: \"false\"
      JIEJING_EBAY_WRITE_LIVE: \"false\"
      JIEJING_PUBLIC_STAGING_REAL_WRITE_POLICY: \"disabled_public_staging\"
""",
            encoding="utf-8",
        )

        completed = self._run_check()

        self.assertNotEqual(completed.returncode, 0)
        report = json.loads(completed.stdout)
        for key in ("JIEJING_MEDIA_LIVE_PROVIDER_ENABLED", "JIEJING_MEDIA_LIVE_VIDEO_ENABLED"):
            self.assertTrue(
                any(
                    blocker.get("code") == "wrong_source"
                    and blocker.get("key") == key
                    and blocker.get("owner") == "jiejing-saas.staging-oauth.env"
                    for blocker in report["blockers"]
                )
            )
            self.assertFalse(
                any(
                    blocker.get("code") == "forbidden_staging_value"
                    and blocker.get("key") == key
                    for blocker in report["blockers"]
                )
            )
        self.assertEqual(report["summary"]["illegal_compose_override_count"], 2)

    def test_ordinary_ebay_and_media_status_keys_remain_unknown_compose_warnings(self) -> None:
        self._write_legal_fixture()
        self.compose_path.write_text(
            """services:
  jiejing-saas:
    environment:
      JIEJING_ENABLE_REAL_PLATFORM_WRITES: \"false\"
      JIEJING_EBAY_WRITE_LIVE: \"false\"
      JIEJING_PUBLIC_STAGING_REAL_WRITE_POLICY: \"disabled_public_staging\"
      JIEJING_EBAY_LISTING_METADATA_LIVE: \"true\"
      JIEJING_MEDIA_PROVIDER_LATENCY_WARNING_MS: \"12000\"
  jiejing-worker:
    environment:
      JIEJING_ENABLE_REAL_PLATFORM_WRITES: \"false\"
      JIEJING_EBAY_WRITE_LIVE: \"false\"
      JIEJING_PUBLIC_STAGING_REAL_WRITE_POLICY: \"disabled_public_staging\"
""",
            encoding="utf-8",
        )

        completed = self._run_check()

        self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)
        report = json.loads(completed.stdout)
        warning_keys = {
            warning.get("key")
            for warning in report["warnings"]
            if warning.get("code") == "compose_static_key"
        }
        self.assertTrue(
            {"JIEJING_EBAY_LISTING_METADATA_LIVE", "JIEJING_MEDIA_PROVIDER_LATENCY_WARNING_MS"}
            <= warning_keys
        )

    def test_runbook_status_keys_in_compose_are_exact_managed_migration_blockers(self) -> None:
        self._write_legal_fixture()
        self.compose_path.write_text(
            """services:
  jiejing-saas:
    environment:
      JIEJING_ENABLE_REAL_PLATFORM_WRITES: \"false\"
      JIEJING_EBAY_WRITE_LIVE: \"false\"
      JIEJING_PUBLIC_STAGING_REAL_WRITE_POLICY: \"disabled_public_staging\"
      JIEJING_BACKUP_RESTORE_DRILL_RUNBOOK_PUBLISHED: \"true\"
      JIEJING_DATABASE_ENDPOINT_INCIDENT_RUNBOOK_PUBLISHED: \"true\"
  jiejing-worker:
    environment:
      JIEJING_ENABLE_REAL_PLATFORM_WRITES: \"false\"
      JIEJING_EBAY_WRITE_LIVE: \"false\"
      JIEJING_PUBLIC_STAGING_REAL_WRITE_POLICY: \"disabled_public_staging\"
""",
            encoding="utf-8",
        )

        completed = self._run_check()

        self.assertNotEqual(completed.returncode, 0)
        report = json.loads(completed.stdout)
        for key in (
            "JIEJING_BACKUP_RESTORE_DRILL_RUNBOOK_PUBLISHED",
            "JIEJING_DATABASE_ENDPOINT_INCIDENT_RUNBOOK_PUBLISHED",
        ):
            self.assertTrue(
                any(
                    blocker.get("code") == "wrong_source"
                    and blocker.get("key") == key
                    and blocker.get("owner") == "tencent-managed.env"
                    for blocker in report["blockers"]
                )
            )
        self.assertEqual(report["summary"]["illegal_compose_override_count"], 2)

    def test_compose_with_only_frontend_is_missing_both_runtime_services(self) -> None:
        self._write_legal_fixture()
        self.compose_path.write_text(
            """services:
  jiejing-frontend:
    image: nginx:test
""",
            encoding="utf-8",
        )

        completed = self._run_check()

        self.assertNotEqual(completed.returncode, 0)
        report = json.loads(completed.stdout)
        missing = {
            blocker.get("service")
            for blocker in report["blockers"]
            if blocker.get("code") == "missing_required_runtime_service"
        }
        self.assertEqual(missing, {"jiejing-saas", "jiejing-worker"})
        self.assertEqual(report["summary"]["illegal_compose_override_count"], 2)

    def test_repeated_environment_blocks_cannot_split_required_clamps(self) -> None:
        self._write_legal_fixture()
        self.compose_path.write_text(
            """services:
  jiejing-saas:
    environment:
      JIEJING_ENABLE_REAL_PLATFORM_WRITES: \"false\"
      JIEJING_EBAY_WRITE_LIVE: \"false\"
    environment:
      JIEJING_PUBLIC_STAGING_REAL_WRITE_POLICY: \"disabled_public_staging\"
  jiejing-worker:
    environment:
      JIEJING_ENABLE_REAL_PLATFORM_WRITES: \"false\"
      JIEJING_EBAY_WRITE_LIVE: \"false\"
      JIEJING_PUBLIC_STAGING_REAL_WRITE_POLICY: \"disabled_public_staging\"
""",
            encoding="utf-8",
        )

        completed = self._run_check()

        self.assertNotEqual(completed.returncode, 0)
        report = json.loads(completed.stdout)
        self.assertTrue(
            any(
                blocker.get("code") == "duplicate_compose_environment_block"
                and blocker.get("service") == "jiejing-saas"
                for blocker in report["blockers"]
            )
        )
        self.assertTrue(
            any(
                blocker.get("code") == "missing_required_compose_clamp"
                and blocker.get("service") == "jiejing-saas"
                for blocker in report["blockers"]
            )
        )

    def test_repeated_runtime_service_blocks_cannot_split_required_clamps(self) -> None:
        self._write_legal_fixture()
        self.compose_path.write_text(
            """services:
    jiejing-saas:
        environment:
            JIEJING_ENABLE_REAL_PLATFORM_WRITES: \"false\"
            JIEJING_EBAY_WRITE_LIVE: \"false\"
    jiejing-saas:
        environment:
            JIEJING_PUBLIC_STAGING_REAL_WRITE_POLICY: \"disabled_public_staging\"
    jiejing-worker:
        environment:
            JIEJING_ENABLE_REAL_PLATFORM_WRITES: \"false\"
            JIEJING_EBAY_WRITE_LIVE: \"false\"
            JIEJING_PUBLIC_STAGING_REAL_WRITE_POLICY: \"disabled_public_staging\"
""",
            encoding="utf-8",
        )

        completed = self._run_check()

        self.assertNotEqual(completed.returncode, 0)
        report = json.loads(completed.stdout)
        self.assertTrue(
            any(
                blocker.get("code") == "duplicate_compose_service"
                and blocker.get("service") == "jiejing-saas"
                for blocker in report["blockers"]
            )
        )
        self.assertTrue(
            any(
                blocker.get("code") == "missing_required_compose_clamp"
                and blocker.get("service") == "jiejing-saas"
                for blocker in report["blockers"]
            )
        )

    def test_duplicate_top_level_services_sections_fail_closed(self) -> None:
        self._write_legal_fixture()
        complete_runtime = """    environment:
      JIEJING_ENABLE_REAL_PLATFORM_WRITES: \"false\"
      JIEJING_EBAY_WRITE_LIVE: \"false\"
      JIEJING_PUBLIC_STAGING_REAL_WRITE_POLICY: \"disabled_public_staging\"
"""
        self.compose_path.write_text(
            "services:\n  jiejing-saas:\n"
            + complete_runtime
            + "services:\n  jiejing-worker:\n"
            + complete_runtime,
            encoding="utf-8",
        )

        completed = self._run_check()

        self.assertNotEqual(completed.returncode, 0)
        report = json.loads(completed.stdout)
        self.assertTrue(
            any(
                blocker.get("code") == "duplicate_top_level_services"
                for blocker in report["blockers"]
            )
        )
        self.assertEqual(report["summary"]["illegal_compose_override_count"], 1)

    def test_nested_mapping_environment_decoy_is_not_a_runtime_environment(self) -> None:
        self._write_legal_fixture()
        text = self.compose_path.read_text(encoding="utf-8")
        direct_block = """    environment:
      JIEJING_ENABLE_REAL_PLATFORM_WRITES: \"false\"
      JIEJING_EBAY_WRITE_LIVE: \"false\"
      JIEJING_PUBLIC_STAGING_REAL_WRITE_POLICY: \"disabled_public_staging\"
      JIEJING_BILLING_PROVIDER: \"stripe_test_mock\"
"""
        nested_block = """    x-decoy:
      environment:
        JIEJING_ENABLE_REAL_PLATFORM_WRITES: \"false\"
        JIEJING_EBAY_WRITE_LIVE: \"false\"
        JIEJING_PUBLIC_STAGING_REAL_WRITE_POLICY: \"disabled_public_staging\"
        JIEJING_BILLING_PROVIDER: \"stripe_test_mock\"
"""
        self.compose_path.write_text(text.replace(direct_block, nested_block, 1), encoding="utf-8")

        completed = self._run_check(augment_legacy_contract=False)

        self.assertNotEqual(completed.returncode, 0)
        report = json.loads(completed.stdout)
        self.assertTrue(
            any(
                blocker.get("code") == "nested_reserved_compose_key"
                and blocker.get("key") == "environment"
                and blocker.get("service") == "jiejing-saas"
                for blocker in report["blockers"]
            )
        )
        self.assertTrue(
            any(
                blocker.get("code") == "missing_runtime_environment"
                and blocker.get("service") == "jiejing-saas"
                for blocker in report["blockers"]
            )
        )

    def test_block_scalar_environment_decoy_is_not_a_runtime_environment(self) -> None:
        self._write_legal_fixture()
        text = self.compose_path.read_text(encoding="utf-8")
        direct_block = """    environment:
      JIEJING_ENABLE_REAL_PLATFORM_WRITES: \"false\"
      JIEJING_EBAY_WRITE_LIVE: \"false\"
      JIEJING_PUBLIC_STAGING_REAL_WRITE_POLICY: \"disabled_public_staging\"
      JIEJING_BILLING_PROVIDER: \"stripe_test_mock\"
"""
        scalar_decoy = """    command: |
      environment:
        JIEJING_ENABLE_REAL_PLATFORM_WRITES: \"false\"
        JIEJING_EBAY_WRITE_LIVE: \"false\"
        JIEJING_PUBLIC_STAGING_REAL_WRITE_POLICY: \"disabled_public_staging\"
        JIEJING_BILLING_PROVIDER: \"stripe_test_mock\"
"""
        self.compose_path.write_text(text.replace(direct_block, scalar_decoy, 1), encoding="utf-8")

        completed = self._run_check(augment_legacy_contract=False)

        report = json.loads(completed.stdout)
        self.assertNotEqual(completed.returncode, 0)
        self.assertTrue(any(blocker.get("code") == "nested_reserved_compose_key" for blocker in report["blockers"]))
        self.assertTrue(
            any(
                blocker.get("code") == "missing_runtime_environment"
                and blocker.get("service") == "jiejing-saas"
                for blocker in report["blockers"]
            )
        )

    def test_nested_clamp_beneath_empty_mapping_is_malformed_and_does_not_count(self) -> None:
        self._write_legal_fixture()
        text = self.compose_path.read_text(encoding="utf-8")
        direct_block = """    environment:
      JIEJING_ENABLE_REAL_PLATFORM_WRITES: \"false\"
      JIEJING_EBAY_WRITE_LIVE: \"false\"
      JIEJING_PUBLIC_STAGING_REAL_WRITE_POLICY: \"disabled_public_staging\"
      JIEJING_BILLING_PROVIDER: \"stripe_test_mock\"
"""
        ambiguous_block = """    environment:
      JIEJING_NESTED_WRAPPER:
        JIEJING_ENABLE_REAL_PLATFORM_WRITES: \"false\"
      JIEJING_EBAY_WRITE_LIVE: \"false\"
      JIEJING_PUBLIC_STAGING_REAL_WRITE_POLICY: \"disabled_public_staging\"
      JIEJING_BILLING_PROVIDER: \"stripe_test_mock\"
"""
        self.compose_path.write_text(text.replace(direct_block, ambiguous_block, 1), encoding="utf-8")

        completed = self._run_check(augment_legacy_contract=False)

        report = json.loads(completed.stdout)
        self.assertNotEqual(completed.returncode, 0)
        blocker_codes = {blocker.get("code") for blocker in report["blockers"]}
        self.assertIn("non_scalar_compose_environment_value", blocker_codes)
        self.assertIn("ambiguous_compose_environment_entry_indent", blocker_codes)
        self.assertTrue(
            any(
                blocker.get("code") == "missing_required_compose_clamp"
                and blocker.get("key") == "JIEJING_ENABLE_REAL_PLATFORM_WRITES"
                and blocker.get("service") == "jiejing-saas"
                for blocker in report["blockers"]
            )
        )
        self.assertFalse(
            any(
                item.get("key") == "JIEJING_ENABLE_REAL_PLATFORM_WRITES"
                and item.get("source") == "compose:jiejing-saas"
                for item in report["declarations"]
            )
        )

    def test_environment_rejects_collection_block_scalar_and_empty_values(self) -> None:
        for private_syntax in ("", "[]", "{}", "|", ">", "&value false", "*value"):
            with self.subTest(private_syntax=private_syntax):
                self._write_legal_fixture()
                text = self.compose_path.read_text(encoding="utf-8")
                needle = '      JIEJING_BILLING_PROVIDER: "stripe_test_mock"\n'
                replacement = needle + f"      JIEJING_MALFORMED_VALUE: {private_syntax}\n"
                self.compose_path.write_text(text.replace(needle, replacement, 1), encoding="utf-8")

                completed = self._run_check(augment_legacy_contract=False)

                report = json.loads(completed.stdout)
                self.assertNotEqual(completed.returncode, 0)
                self.assertTrue(
                    any(
                        blocker.get("code") == "non_scalar_compose_environment_value"
                        for blocker in report["blockers"]
                    )
                )
                self.assertFalse(
                    any(item.get("key") == "JIEJING_MALFORMED_VALUE" for item in report["declarations"])
                )

    def test_runtime_env_file_contract_rejects_missing_duplicate_reordered_and_unsupported_entries(self) -> None:
        mutations = {
            "missing": (
                "      - ./runtime-env/postgres-localqueue.env\n",
                "",
                "missing_required_compose_env_file_source",
            ),
            "duplicate": (
                "      - ./runtime-env/postgres-localqueue.env\n",
                "      - ./runtime-env/postgres-localqueue.env\n"
                "      - ./runtime-env/postgres-localqueue.env\n",
                "duplicate_compose_env_file_source",
            ),
            "reordered": (
                "      - ./runtime-env/tencent-managed.env\n"
                "      - ./runtime-env/jiejing-saas.staging-oauth.env\n",
                "      - ./runtime-env/jiejing-saas.staging-oauth.env\n"
                "      - ./runtime-env/tencent-managed.env\n",
                "reordered_compose_env_file_sources",
            ),
            "extra": (
                "      - ./runtime-env/postgres-localqueue.env\n",
                "      - ./runtime-env/postgres-localqueue.env\n"
                "      - ./runtime-env/unapproved-extra.env\n",
                "unexpected_compose_env_file_source",
            ),
            "long_syntax": (
                "      - ./runtime-env/tencent-managed.env\n",
                "      - path: ./runtime-env/tencent-managed.env\n",
                "unsupported_compose_env_file_entry",
            ),
            "variable": (
                "      - ./runtime-env/tencent-managed.env\n",
                "      - ${JIEJING_MANAGED_ENV_FILE}\n",
                "unsupported_compose_env_file_entry",
            ),
        }
        for _name, (old, new, expected_code) in mutations.items():
            with self.subTest(case=_name):
                self._write_legal_fixture()
                text = self.compose_path.read_text(encoding="utf-8")
                self.compose_path.write_text(text.replace(old, new, 1), encoding="utf-8")

                completed = self._run_check(augment_legacy_contract=False)

                self.assertNotEqual(completed.returncode, 0)
                report = json.loads(completed.stdout)
                self.assertTrue(
                    any(
                        blocker.get("code") == expected_code
                        and blocker.get("service") in {None, "jiejing-saas"}
                        for blocker in report["blockers"]
                    ),
                    report["blockers"],
                )

    def test_nested_env_file_decoy_is_not_a_runtime_env_file_contract(self) -> None:
        self._write_legal_fixture()
        text = self.compose_path.read_text(encoding="utf-8")
        direct = """    env_file:
      - ./runtime-env/tencent-managed.env
      - ./runtime-env/jiejing-saas.staging-oauth.env
      - ./runtime-env/postgres-localqueue.env
"""
        nested = """    x-decoy:
      env_file:
        - ./runtime-env/tencent-managed.env
        - ./runtime-env/jiejing-saas.staging-oauth.env
        - ./runtime-env/postgres-localqueue.env
"""
        self.compose_path.write_text(text.replace(direct, nested, 1), encoding="utf-8")

        completed = self._run_check(augment_legacy_contract=False)

        report = json.loads(completed.stdout)
        self.assertNotEqual(completed.returncode, 0)
        self.assertTrue(
            any(
                blocker.get("code") == "nested_reserved_compose_key"
                and blocker.get("key") == "env_file"
                for blocker in report["blockers"]
            )
        )
        self.assertTrue(
            any(
                blocker.get("code") == "missing_required_compose_env_file"
                and blocker.get("service") == "jiejing-saas"
                for blocker in report["blockers"]
            )
        )

    def test_env_file_same_basename_in_wrong_directory_fails_path_identity(self) -> None:
        self._write_legal_fixture()
        text = self.compose_path.read_text(encoding="utf-8")
        wrong_reference = "./wrong-directory/tencent-managed.env"
        self.compose_path.write_text(
            text.replace("./runtime-env/tencent-managed.env", wrong_reference, 1),
            encoding="utf-8",
        )

        completed = self._run_check(augment_legacy_contract=False)

        report = json.loads(completed.stdout)
        serialized = json.dumps(report, ensure_ascii=False)
        self.assertNotEqual(completed.returncode, 0)
        self.assertTrue(
            any(
                blocker.get("code") == "unexpected_compose_env_file_source"
                and blocker.get("service") == "jiejing-saas"
                for blocker in report["blockers"]
            )
        )
        self.assertTrue(
            any(
                blocker.get("code") == "missing_required_compose_env_file_source"
                and blocker.get("required_source_role") == "managed"
                for blocker in report["blockers"]
            )
        )
        self.assertNotIn(wrong_reference, serialized)
        self.assertNotIn(str(self.fixture_root), serialized)

    def test_env_file_rejects_interpolation_home_and_uri_references(self) -> None:
        unsafe_references = (
            "$JIEJING_MANAGED_ENV_FILE",
            "${JIEJING_MANAGED_ENV_FILE}",
            "%JIEJING_MANAGED_ENV_FILE%",
            "~/runtime-env/tencent-managed.env",
            "https://example.invalid/tencent-managed.env",
            "file:///runtime-env/tencent-managed.env",
        )
        for unsafe_reference in unsafe_references:
            with self.subTest(unsafe_reference=unsafe_reference):
                self._write_legal_fixture()
                text = self.compose_path.read_text(encoding="utf-8")
                self.compose_path.write_text(
                    text.replace("./runtime-env/tencent-managed.env", unsafe_reference, 1),
                    encoding="utf-8",
                )

                completed = self._run_check(augment_legacy_contract=False)

                report = json.loads(completed.stdout)
                self.assertNotEqual(completed.returncode, 0)
                self.assertTrue(
                    any(
                        blocker.get("code") == "unsupported_compose_env_file_entry"
                        for blocker in report["blockers"]
                    )
                )
                self.assertNotIn(unsafe_reference, json.dumps(report, ensure_ascii=False))

    def test_env_file_accepts_absolute_paths_only_when_they_match_cli_sources(self) -> None:
        self._write_legal_fixture()
        text = self.compose_path.read_text(encoding="utf-8")
        replacements = (
            ("./runtime-env/tencent-managed.env", self.managed_path.as_posix()),
            ("./runtime-env/jiejing-saas.staging-oauth.env", self.secret_path.as_posix()),
            ("./runtime-env/postgres-localqueue.env", self.postgres_path.as_posix()),
        )
        for relative, absolute in replacements:
            text = text.replace(relative, absolute)
        self.compose_path.write_text(text, encoding="utf-8")

        completed = self._run_check(augment_legacy_contract=False)

        self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)

    def test_non_literal_reserved_structural_keys_fail_even_beside_valid_blocks(self) -> None:
        suspicious_lines = (
            '    "environment": {}',
            r'    "\x65nvironment": {}',
            r'    "\u0065nvironment": {}',
            "    'env_file': []",
            r'    "\u0065nv_file": []',
            "    &runtime environment: {}",
            "    ? environment: {}",
            "    <<: *runtime_environment",
        )
        for suspicious_line in suspicious_lines:
            with self.subTest(suspicious_line=suspicious_line):
                self._write_legal_fixture()
                text = self.compose_path.read_text(encoding="utf-8")
                self.compose_path.write_text(
                    text.replace("  jiejing-saas:\n", f"  jiejing-saas:\n{suspicious_line}\n", 1),
                    encoding="utf-8",
                )

                completed = self._run_check(augment_legacy_contract=False)

                report = json.loads(completed.stdout)
                self.assertNotEqual(completed.returncode, 0)
                self.assertTrue(
                    any(
                        blocker.get("code") == "non_literal_compose_structural_key"
                        and blocker.get("service") == "jiejing-saas"
                        for blocker in report["blockers"]
                    ),
                    report["blockers"],
                )

    def test_non_literal_services_and_runtime_service_keys_fail_beside_valid_blocks(self) -> None:
        cases = (
            ("top", '"services": {}'),
            ("top", r'"\x73ervices": {}'),
            ("top", r'"\u0073ervices": {}'),
            ("top", "? services: {}"),
            ("top", "&root services: {}"),
            ("top", "<<: *services"),
            ("services", '  "jiejing-saas": {}'),
            ("services", r'  "\x6aiejing-saas": {}'),
            ("services", "  ? jiejing-worker: {}"),
            ("services", "  &runtime jiejing-saas: {}"),
            ("services", "  <<: *runtime_services"),
        )
        for scope, suspicious_line in cases:
            with self.subTest(scope=scope, suspicious_line=suspicious_line):
                self._write_legal_fixture()
                text = self.compose_path.read_text(encoding="utf-8")
                if scope == "top":
                    text = text + suspicious_line + "\n"
                else:
                    text = text.replace("services:\n", f"services:\n{suspicious_line}\n", 1)
                self.compose_path.write_text(text, encoding="utf-8")

                completed = self._run_check(augment_legacy_contract=False)

                report = json.loads(completed.stdout)
                self.assertNotEqual(completed.returncode, 0)
                self.assertTrue(
                    any(
                        blocker.get("code") == "non_literal_compose_structural_key"
                        for blocker in report["blockers"]
                    ),
                    report["blockers"],
                )

    def test_canonical_two_line_explicit_mappings_block_in_every_guarded_scope(self) -> None:
        sentinel = "EXPLICIT_MAPPING_VALUE_MUST_NOT_LEAK"
        cases = ("top", "services", "runtime", "environment", "env_file")
        for scope in cases:
            with self.subTest(scope=scope):
                self._write_legal_fixture()
                text = self.compose_path.read_text(encoding="utf-8")
                if scope == "top":
                    text += f"? services\n: {sentinel}\n"
                elif scope == "services":
                    text = text.replace(
                        "services:\n",
                        f"services:\n  ? jiejing-saas\n  : {sentinel}\n",
                        1,
                    )
                elif scope == "runtime":
                    text = text.replace(
                        "  jiejing-saas:\n",
                        f"  jiejing-saas:\n    ? environment\n    : {sentinel}\n",
                        1,
                    )
                elif scope == "environment":
                    text = text.replace(
                        "    environment:\n",
                        f"    environment:\n      ? JIEJING_ENABLE_REAL_PLATFORM_WRITES\n      : {sentinel}\n",
                        1,
                    )
                else:
                    text = text.replace(
                        "    env_file:\n",
                        f"    env_file:\n      ? env_source\n      : {sentinel}\n",
                        1,
                    )
                self.compose_path.write_text(text, encoding="utf-8")

                completed = self._run_check(augment_legacy_contract=False)

                self.assertNotEqual(completed.returncode, 0)
                self.assertNotIn(sentinel, completed.stdout + completed.stderr)
                report = json.loads(completed.stdout)
                explicit_blockers = [
                    blocker
                    for blocker in report["blockers"]
                    if blocker.get("code") == "unsupported_explicit_compose_mapping_syntax"
                ]
                self.assertGreaterEqual(len(explicit_blockers), 2, report["blockers"])

    def test_anchor_wrapped_quoted_keys_block_in_every_guarded_scope(self) -> None:
        cases = {
            "top": '&k "services": {}',
            "services": '  &k "jiejing-saas": {}',
            "runtime": '    &k "environment": {}',
            "environment": '      &k "JIEJING_FAKE_KEY": "ANCHOR_VALUE_MUST_NOT_LEAK"',
            "env_file": '      &k "path": "ANCHOR_PATH_MUST_NOT_LEAK"',
        }
        for scope, suspicious_line in cases.items():
            with self.subTest(scope=scope):
                self._write_legal_fixture()
                text = self.compose_path.read_text(encoding="utf-8")
                if scope == "top":
                    text += suspicious_line + "\n"
                elif scope == "services":
                    text = text.replace("services:\n", f"services:\n{suspicious_line}\n", 1)
                elif scope == "runtime":
                    text = text.replace("  jiejing-saas:\n", f"  jiejing-saas:\n{suspicious_line}\n", 1)
                elif scope == "environment":
                    text = text.replace("    environment:\n", f"    environment:\n{suspicious_line}\n", 1)
                else:
                    text = text.replace("    env_file:\n", f"    env_file:\n{suspicious_line}\n", 1)
                self.compose_path.write_text(text, encoding="utf-8")

                completed = self._run_check(augment_legacy_contract=False)

                self.assertNotEqual(completed.returncode, 0)
                self.assertNotIn("ANCHOR_VALUE_MUST_NOT_LEAK", completed.stdout + completed.stderr)
                self.assertNotIn("ANCHOR_PATH_MUST_NOT_LEAK", completed.stdout + completed.stderr)
                report = json.loads(completed.stdout)
                self.assertTrue(
                    any(
                        blocker.get("code") == "non_literal_compose_structural_key"
                        for blocker in report["blockers"]
                    ),
                    report["blockers"],
                )

    def test_runtime_env_file_contract_rejects_inline_and_duplicate_blocks(self) -> None:
        for case in ("inline", "duplicate_block"):
            with self.subTest(case=case):
                self._write_legal_fixture()
                text = self.compose_path.read_text(encoding="utf-8")
                env_file = """    env_file:
      - ./runtime-env/tencent-managed.env
      - ./runtime-env/jiejing-saas.staging-oauth.env
      - ./runtime-env/postgres-localqueue.env
"""
                replacement = (
                    "    env_file: [./runtime-env/tencent-managed.env]\n"
                    if case == "inline"
                    else env_file + env_file
                )
                self.compose_path.write_text(text.replace(env_file, replacement, 1), encoding="utf-8")

                completed = self._run_check(augment_legacy_contract=False)

                report = json.loads(completed.stdout)
                expected = (
                    "unsupported_inline_compose_env_file"
                    if case == "inline"
                    else "duplicate_compose_env_file_block"
                )
                self.assertNotEqual(completed.returncode, 0)
                self.assertTrue(any(blocker.get("code") == expected for blocker in report["blockers"]))

    def test_secret_aliases_are_exact_secret_owned_and_values_never_leak(self) -> None:
        aliases = (
            "STRIPE_SECRET_KEY",
            "STRIPE_WEBHOOK_SECRET",
            "OPENAI_API_KEY",
            "DEEPSEEK_API_KEY",
            "EBAY_ACCESS_TOKEN",
            "EBAY_CLIENT_ID",
            "EBAY_CLIENT_SECRET",
            "EBAY_REFRESH_TOKEN",
            "EBAY_RU_NAME",
            "VAULT_TOKEN",
            "FAL_KEY_ID",
            "FAL_KEY_SECRET",
            "JIEJING_FAL_KEY_ID",
            "JIEJING_FAL_KEY_SECRET",
            "JIEJING_EBAY_ACCOUNT_READ_TOKEN",
            "JIEJING_EBAY_READ_TOKEN",
        )
        self._write_legal_fixture()
        sentinels = [f"PRIVATE_ALIAS_{index}_MUST_NOT_LEAK" for index in range(len(aliases))]
        self.managed_path.write_text(
            "JIEJING_BACKUP_POLICY_CONFIGURED=true\n"
            + "".join(f"{key}={value}\n" for key, value in zip(aliases, sentinels)),
            encoding="utf-8",
        )

        completed = self._run_check(augment_legacy_contract=False)

        self.assertNotEqual(completed.returncode, 0)
        combined = completed.stdout + completed.stderr
        for sentinel in sentinels:
            self.assertNotIn(sentinel, combined)
        report = json.loads(completed.stdout)
        wrong_aliases = {
            blocker.get("key")
            for blocker in report["blockers"]
            if blocker.get("code") == "wrong_source"
            and blocker.get("owner") == "jiejing-saas.staging-oauth.env"
        }
        self.assertTrue(set(aliases) <= wrong_aliases)

    def test_active_managed_provider_aliases_are_exact_managed_owned(self) -> None:
        aliases = (
            "VAULT_ADDR",
            "TENCENTCLOUD_SECRET_ID",
            "TENCENTCLOUD_SECRET_KEY",
            "TENCENTCLOUD_TOKEN",
        )
        self._write_legal_fixture()
        sentinels = [f"MANAGED_ALIAS_{index}_MUST_NOT_LEAK" for index in range(len(aliases))]
        self.secret_path.write_text(
            "JIEJING_EBAY_CLIENT_SECRET=LEGAL_SECRET_SENTINEL\n"
            + "".join(f"{key}={value}\n" for key, value in zip(aliases, sentinels)),
            encoding="utf-8",
        )

        completed = self._run_check(augment_legacy_contract=False)

        self.assertNotEqual(completed.returncode, 0)
        combined = completed.stdout + completed.stderr
        for sentinel in sentinels:
            self.assertNotIn(sentinel, combined)
        report = json.loads(completed.stdout)
        wrong_aliases = {
            blocker.get("key")
            for blocker in report["blockers"]
            if blocker.get("code") == "wrong_source" and blocker.get("owner") == "tencent-managed.env"
        }
        self.assertEqual(wrong_aliases, set(aliases))

    def test_tencentcloud_token_only_passes_in_managed_source_and_never_leaks(self) -> None:
        sentinel = "TENCENTCLOUD_TOKEN_VALUE_MUST_NOT_LEAK"
        for source in ("managed", "secret", "postgres", "compose"):
            with self.subTest(source=source):
                self._write_legal_fixture()
                if source == "managed":
                    self.managed_path.write_text(
                        "JIEJING_BACKUP_POLICY_CONFIGURED=true\n"
                        f"TENCENTCLOUD_TOKEN={sentinel}\n",
                        encoding="utf-8",
                    )
                elif source == "secret":
                    self.secret_path.write_text(
                        "JIEJING_EBAY_CLIENT_SECRET=LEGAL_SECRET_SENTINEL\n"
                        f"TENCENTCLOUD_TOKEN={sentinel}\n",
                        encoding="utf-8",
                    )
                elif source == "postgres":
                    self.postgres_path.write_text(
                        "JIEJING_DATABASE_URL=postgresql://LEGAL_DATABASE_SENTINEL/db\n"
                        f"TENCENTCLOUD_TOKEN={sentinel}\n",
                        encoding="utf-8",
                    )
                else:
                    text = self.compose_path.read_text(encoding="utf-8")
                    needle = '      JIEJING_BILLING_PROVIDER: "stripe_test_mock"\n'
                    self.compose_path.write_text(
                        text.replace(needle, needle + f'      TENCENTCLOUD_TOKEN: "{sentinel}"\n', 1),
                        encoding="utf-8",
                    )

                completed = self._run_check(augment_legacy_contract=False)

                combined = completed.stdout + completed.stderr
                self.assertNotIn(sentinel, combined)
                report = json.loads(completed.stdout)
                if source == "managed":
                    self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)
                else:
                    self.assertNotEqual(completed.returncode, 0)
                    self.assertTrue(
                        any(
                            blocker.get("code") == "wrong_source"
                            and blocker.get("key") == "TENCENTCLOUD_TOKEN"
                            and blocker.get("owner") == "tencent-managed.env"
                            for blocker in report["blockers"]
                        )
                    )

    def test_managed_and_postgres_prefixes_take_precedence_over_secret_suffixes(self) -> None:
        self._write_legal_fixture()
        self.managed_path.write_text(
            "JIEJING_BACKUP_POLICY_CONFIGURED=true\n"
            "JIEJING_TENCENT_SECRET_KEY=MANAGED_SENTINEL\n",
            encoding="utf-8",
        )
        self.postgres_path.write_text(
            "JIEJING_DATABASE_URL=postgresql://DATABASE_SENTINEL/db\n"
            "JIEJING_DATABASE_API_KEY=POSTGRES_SENTINEL\n",
            encoding="utf-8",
        )

        completed = self._run_check(augment_legacy_contract=False)

        self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)
        report = json.loads(completed.stdout)
        owners = {item["key"]: item["owner"] for item in report["declarations"]}
        self.assertEqual(owners["JIEJING_TENCENT_SECRET_KEY"], "tencent-managed.env")
        self.assertEqual(owners["JIEJING_DATABASE_API_KEY"], "postgres-localqueue.env")

    def test_billing_provider_pin_is_required_and_rejects_live_or_manual_modes(self) -> None:
        for value in ("stripe", "manual_qr"):
            with self.subTest(value=value):
                self._write_legal_fixture()
                text = self.compose_path.read_text(encoding="utf-8")
                self.compose_path.write_text(
                    text.replace(
                        '      JIEJING_BILLING_PROVIDER: "stripe_test_mock"\n',
                        f'      JIEJING_BILLING_PROVIDER: "{value}"\n',
                        1,
                    ),
                    encoding="utf-8",
                )

                completed = self._run_check(augment_legacy_contract=False)

                report = json.loads(completed.stdout)
                self.assertNotEqual(completed.returncode, 0)
                self.assertTrue(any(blocker.get("code") == "unsafe_billing_provider" for blocker in report["blockers"]))
                self.assertTrue(
                    any(
                        blocker.get("code") == "forbidden_staging_value"
                        and blocker.get("key") == "JIEJING_BILLING_PROVIDER"
                        for blocker in report["blockers"]
                    )
                )

        self._write_legal_fixture()
        text = self.compose_path.read_text(encoding="utf-8")
        self.compose_path.write_text(
            text.replace('      JIEJING_BILLING_PROVIDER: "stripe_test_mock"\n', "", 1),
            encoding="utf-8",
        )
        completed = self._run_check(augment_legacy_contract=False)
        report = json.loads(completed.stdout)
        self.assertTrue(
            any(
                blocker.get("code") == "missing_required_billing_provider_pin"
                and blocker.get("service") == "jiejing-saas"
                for blocker in report["blockers"]
            )
        )

    def test_readiness_only_domestic_adapter_has_no_staging_value_constraint(self) -> None:
        self._write_legal_fixture()
        self.secret_path.write_text(
            "JIEJING_EBAY_CLIENT_SECRET=LEGAL_SECRET_SENTINEL\n"
            "JIEJING_DOMESTIC_PAYMENT_ADAPTER_ENABLED=true\n",
            encoding="utf-8",
        )

        completed = self._run_check(augment_legacy_contract=False)

        self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)
        report = json.loads(completed.stdout)
        self.assertFalse(
            any(
                blocker.get("code") == "forbidden_staging_value"
                and blocker.get("key") == "JIEJING_DOMESTIC_PAYMENT_ADAPTER_ENABLED"
                for blocker in report["blockers"]
            )
        )

    def test_vault_runtime_evidence_is_managed_owned(self) -> None:
        self._write_legal_fixture()
        self.managed_path.write_text(
            "JIEJING_BACKUP_POLICY_CONFIGURED=true\n"
            "JIEJING_VAULT_ENABLED=true\n"
            "JIEJING_VAULT_LIVE_PROBE_PASSED=true\n",
            encoding="utf-8",
        )

        completed = self._run_check(augment_legacy_contract=False)

        self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)
        report = json.loads(completed.stdout)
        owners = {item["key"]: item["owner"] for item in report["declarations"]}
        self.assertEqual(owners["JIEJING_VAULT_ENABLED"], "tencent-managed.env")
        self.assertEqual(owners["JIEJING_VAULT_LIVE_PROBE_PASSED"], "tencent-managed.env")

    def test_yaml_scalar_comments_preserve_hashes_inside_quotes(self) -> None:
        self.assertEqual(_strip_yaml_scalar('"jie#jing.shop" # trailing comment'), "jie#jing.shop")
        self.assertEqual(_strip_yaml_scalar("'a#b' # trailing comment"), "a#b")
        self.assertEqual(_strip_yaml_scalar('"false" # safety clamp'), "false")

        self._write_legal_fixture()
        text = self.compose_path.read_text(encoding="utf-8")
        text = text.replace('"false"', '"false" # clamp')
        text = text.replace('"disabled_public_staging"', '"disabled_public_staging" # policy')
        text = text.replace('"stripe_test_mock"', '"stripe_test_mock" # no-charge provider')
        self.compose_path.write_text(text, encoding="utf-8")
        completed = self._run_check(augment_legacy_contract=False)
        self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)

    def test_declaration_repr_and_public_report_never_expose_private_values(self) -> None:
        sentinel = "DECLARATION_PRIVATE_VALUE_MUST_NOT_LEAK"
        declaration = Declaration("OPENAI_API_KEY", "secret", 1, sentinel)
        self.assertNotIn(sentinel, repr(declaration))

        self._write_legal_fixture()
        self.secret_path.write_text(f"OPENAI_API_KEY={sentinel}\n", encoding="utf-8")
        completed = self._run_check(augment_legacy_contract=False)
        self.assertNotIn(sentinel, completed.stdout + completed.stderr)

    def test_compose_contract_violation_count_is_truthful_and_legacy_compatible(self) -> None:
        self._write_legal_fixture()
        text = self.compose_path.read_text(encoding="utf-8")
        self.compose_path.write_text(text.replace("    env_file:\n", "    env_file: []\n", 1), encoding="utf-8")

        completed = self._run_check(augment_legacy_contract=False)

        report = json.loads(completed.stdout)
        self.assertGreater(report["summary"]["compose_contract_violation_count"], 0)
        self.assertEqual(
            report["summary"]["compose_contract_violation_count"],
            report["summary"]["illegal_compose_override_count"],
        )

    def test_symlink_compose_and_private_inputs_are_rejected_without_path_leakage(self) -> None:
        self._write_legal_fixture()
        for target_path, expected_source in (
            (self.compose_path, "compose"),
            (self.secret_path, "jiejing-saas.staging-oauth.env"),
        ):
            with self.subTest(source=expected_source):
                original_is_symlink = Path.is_symlink

                def simulated_is_symlink(path: Path) -> bool:
                    return path == target_path or original_is_symlink(path)

                with patch.object(Path, "is_symlink", simulated_is_symlink):
                    report = check_runtime_env_ownership(
                        compose_path=self.compose_path,
                        managed_env_path=self.managed_path,
                        secret_env_path=self.secret_path,
                        postgres_env_path=self.postgres_path,
                    )

                serialized = json.dumps(report, ensure_ascii=False)
                self.assertFalse(report["ok"])
                self.assertTrue(
                    any(
                        blocker.get("code") == "source_symlink"
                        and blocker.get("source") == expected_source
                        for blocker in report["blockers"]
                    )
                )
                self.assertNotIn(str(target_path), serialized)


def _all_json_keys(item: object) -> set[str]:
    if isinstance(item, dict):
        keys = {str(key) for key in item}
        for nested in item.values():
            keys.update(_all_json_keys(nested))
        return keys
    if isinstance(item, list):
        keys: set[str] = set()
        for nested in item:
            keys.update(_all_json_keys(nested))
        return keys
    return set()


def _looks_like_value_field(key: str) -> bool:
    normalized = key.casefold()
    return normalized in {"value", "values"} or normalized.endswith(("_value", "_values"))


if __name__ == "__main__":
    unittest.main()
