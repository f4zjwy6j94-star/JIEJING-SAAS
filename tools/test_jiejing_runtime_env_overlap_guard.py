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
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import jiejing_runtime_env_overlap_guard as guard_module
from jiejing_runtime_env_overlap_guard import (
    Declaration,
    GuardAnalysis,
    MIGRATION_APPLY_CONFIRMATION,
    RESOLUTION_APPLY_CONFIRMATION,
    RESOLUTION_MANIFEST_SCHEMA_VERSION,
    _strip_yaml_scalar,
    analyze_runtime_env_ownership,
    apply_runtime_env_resolution,
    check_runtime_env_ownership,
    plan_runtime_env_resolution,
)


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "jiejing_runtime_env_overlap_guard.py"


RESOLUTION_APPLY_SAFETY_CONTRACT = """Phase 8 resolution-apply public contract.

The command is independent from resolution-plan and has no apply flag.  Without
the new exact confirmation phrase it is a dry-run; a wrong phrase fails closed,
and both cases leave every input byte unchanged.  Before any mutation it must
rebuild the same zero-blocker plan and bind the candidate Compose, donor
Compose, decision manifest, managed env, secret env, and postgres env to stable
non-aliased, non-link/reparse snapshots and one plan identity.  Any blocker,
drift, path alias, symlink/junction/reparse, or pre/mid-operation TOCTOU produces
zero forward mutation or transaction-wide rollback.

Only managed/secret/postgres private env payloads may change.  Candidate and
donor Compose plus the manifest are read-only forever; retire-equal Compose
donor actions are evidence-only.  The four executable action kinds preserve
opaque internally-bound values while removing wrong-source declarations and,
where needed, moving a unique/equal donor value to its authoritative private
owner.  Existing byte-preserving render, CAS/no-clobber, lock, backup, and
rollback primitives are the only allowed write path.  Concurrent external
changes are retained and fail the whole transaction.  A post-apply guard of the
candidate desired topology must have zero blockers/actions or every committed
private change is rolled back.  After that validator, every backup/commit check,
and immediately before success, every uncommitted readonly snapshot is checked
again; late drift is preserved while all private commits roll back, including
evidence-only retire transactions.

Compose donor scalars may enter a private env file only through an explicit
Compose env_file-compatible reversible encoding contract.  The encoded RHS is
round-tripped with literal single-quote runtime semantics: hash, surrounding
spaces, dollar interpolation markers, double quotes and backslashes remain
literal, and embedded single quotes use the runtime-supported backslash escape.
Only a source that is itself explicitly single-quoted may carry a dollar marker:
plain/double-quoted Compose scalars and unquoted/double-quoted private RHS values
can interpolate in a runtime context and therefore fail closed.  A Compose
environment list item is never reclassified as a literal because quote-like
characters appear only after ``KEY=``; its entire YAML item/container context is
bound.  Resolution planning may report a list-form donor read-only, but apply
accepts Compose donors only from an ``environment`` mapping; every list-form
donor fails closed before backup regardless of content or quote appearance.
Newline, NUL, Unicode Cc/Zl/Zp characters (including NEL, line separator, and
paragraph separator), invalid escape/trailer forms, and any value that cannot
be proven reversible fail closed before a backup or commit; ordinary printable
Unicode remains allowed.  Every fully rendered private candidate is parsed by
the complete env parser before backup/commit, with zero blockers, and each
addition must appear exactly once with a runtime value identical to its bound
value.  Private-to-private moves bind the source's exact RHS instead of
stripping it, and independently verify that the moved RHS retains the same
runtime semantic value.

Existing private payloads are decoded and scanned as complete text before any
``splitlines`` operation.  Only physical LF and CRLF line endings are valid;
lone CR and all other Unicode Cc/Zl/Zp characters fail closed with a value-free
source-role blocker.  LF, CRLF and mixed LF/CRLF files remain valid, and removal
rendering preserves every untouched byte.  This env-file rule does not parse or
rewrite candidate Compose, donor Compose, or manifest structure.

Public output contains only roles, counts, codes, and action summaries: never
private key names, values, paths, digests, or line content; secret_exposed is
always false.
"""


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

    def _run_check(
        self,
        *,
        augment_legacy_contract: bool = True,
        required_runtime_services: tuple[str, ...] = (),
    ) -> subprocess.CompletedProcess[str]:
        if augment_legacy_contract:
            self._augment_legacy_compose_contract()
        command = [
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
        ]
        for service_name in required_runtime_services:
            command.extend(("--required-runtime-service", service_name))
        return subprocess.run(
            command,
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
        required_runtime_services: tuple[str, ...] = (),
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
        for service_name in required_runtime_services:
            command.extend(("--required-runtime-service", service_name))
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

    def _write_resolution_manifest(self, decisions: list[dict[str, object]]) -> Path:
        manifest_path = self.fixture_root / "resolution-manifest.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "schema_version": RESOLUTION_MANIFEST_SCHEMA_VERSION,
                    "decisions": decisions,
                }
            ),
            encoding="utf-8",
        )
        return manifest_path

    def _run_resolution_plan(
        self,
        manifest_path: Path,
        *,
        augment_legacy_contract: bool = True,
        compose_path: Path | None = None,
        compose_runtime_path: Path | None = None,
        donor_compose_path: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        if augment_legacy_contract:
            self._augment_legacy_compose_contract()
        command = [
                sys.executable,
                str(TOOL),
                "resolution-plan",
                "--compose",
                str(compose_path or self.compose_path),
                "--managed-env",
                str(self.managed_path),
                "--secret-env",
                str(self.secret_path),
                "--postgres-env",
                str(self.postgres_path),
                "--decision-manifest",
                str(manifest_path),
                "--json",
            ]
        if compose_runtime_path is not None:
            command.extend(("--compose-runtime-path", str(compose_runtime_path)))
        if donor_compose_path is not None:
            command.extend(("--donor-compose", str(donor_compose_path)))
        return subprocess.run(
            command,
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def _run_resolution_apply(
        self,
        manifest_path: Path,
        *,
        confirm: str | None = None,
        augment_legacy_contract: bool = True,
        compose_path: Path | None = None,
        compose_runtime_path: Path | None = None,
        donor_compose_path: Path | None = None,
        compose_override_paths: tuple[Path, ...] = (),
        required_runtime_services: tuple[str, ...] = (),
    ) -> subprocess.CompletedProcess[str]:
        if augment_legacy_contract:
            self._augment_legacy_compose_contract()
        command = [
            sys.executable,
            str(TOOL),
            "resolution-apply",
            "--compose",
            str(compose_path or self.compose_path),
            "--managed-env",
            str(self.managed_path),
            "--secret-env",
            str(self.secret_path),
            "--postgres-env",
            str(self.postgres_path),
            "--decision-manifest",
            str(manifest_path),
            "--json",
        ]
        if confirm is not None:
            command.extend(("--confirm", confirm))
        if compose_runtime_path is not None:
            command.extend(("--compose-runtime-path", str(compose_runtime_path)))
        if donor_compose_path is not None:
            command.extend(("--donor-compose", str(donor_compose_path)))
        for override_path in compose_override_paths:
            command.extend(("--compose-override", str(override_path)))
        for service_name in required_runtime_services:
            command.extend(("--required-runtime-service", service_name))
        return subprocess.run(
            command,
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_resolution_apply_without_confirmation_is_a_value_free_dry_run(self) -> None:
        self._write_legal_fixture()
        self.managed_path.write_text(
            self.managed_path.read_text(encoding="utf-8")
            + "JIEJING_EBAY_CLIENT_SECRET=LEGAL_SECRET_SENTINEL\n",
            encoding="utf-8",
        )
        manifest_path = self._write_resolution_manifest([])
        before = {
            path: path.read_bytes()
            for path in (
                self.compose_path,
                self.managed_path,
                self.secret_path,
                self.postgres_path,
                manifest_path,
            )
        }

        completed = self._run_resolution_apply(
            manifest_path,
            augment_legacy_contract=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)
        report = json.loads(completed.stdout)
        self.assertTrue(report["ok"], report["blockers"])
        self.assertEqual(report["operation"], "resolution-apply")
        self.assertEqual(report["mode"], "dry_run")
        self.assertFalse(report["applied"])
        self.assertFalse(report["secret_exposed"])
        self.assertEqual(report["summary"]["action_count"], 1)
        self.assertEqual(before, {path: path.read_bytes() for path in before})
        self.assertNotIn("JIEJING_EBAY_CLIENT_SECRET", completed.stdout + completed.stderr)
        self.assertNotIn("LEGAL_SECRET_SENTINEL", completed.stdout + completed.stderr)
        self.assertEqual(
            sorted(key for key in _all_json_keys(report) if _looks_like_value_field(key)),
            [],
        )

    def test_resolution_apply_exact_confirmation_removes_equal_private_duplicate(self) -> None:
        self._write_legal_fixture()
        duplicate = b"JIEJING_EBAY_CLIENT_SECRET=LEGAL_SECRET_SENTINEL\r\n"
        original_managed = self.managed_path.read_bytes()
        self.managed_path.write_bytes(original_managed + duplicate)
        manifest_path = self._write_resolution_manifest([])
        read_only_before = {
            path: path.read_bytes()
            for path in (self.compose_path, self.secret_path, self.postgres_path, manifest_path)
        }

        completed = self._run_resolution_apply(
            manifest_path,
            confirm=RESOLUTION_APPLY_CONFIRMATION,
            augment_legacy_contract=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)
        report = json.loads(completed.stdout)
        self.assertTrue(report["ok"], report["blockers"])
        self.assertEqual(report["mode"], "apply")
        self.assertTrue(report["applied"])
        self.assertFalse(report["secret_exposed"])
        self.assertEqual(self.managed_path.read_bytes(), original_managed)
        self.assertEqual(read_only_before, {path: path.read_bytes() for path in read_only_before})
        self.assertEqual(
            report["actions"],
            [
                {
                    "action": "remove_equal_duplicate",
                    "source_role": "managed",
                    "target_role": "secret",
                    "count": 1,
                }
            ],
        )
        self.assertNotIn("JIEJING_EBAY_CLIENT_SECRET", completed.stdout + completed.stderr)
        self.assertNotIn("LEGAL_SECRET_SENTINEL", completed.stdout + completed.stderr)

    def test_resolution_apply_rejects_inexact_confirmation_without_writes_or_echo(self) -> None:
        self._write_legal_fixture()
        self.managed_path.write_text(
            self.managed_path.read_text(encoding="utf-8")
            + "JIEJING_EBAY_CLIENT_SECRET=LEGAL_SECRET_SENTINEL\n",
            encoding="utf-8",
        )
        manifest_path = self._write_resolution_manifest([])
        before = {
            path: path.read_bytes()
            for path in (
                self.compose_path,
                self.managed_path,
                self.secret_path,
                self.postgres_path,
                manifest_path,
            )
        }
        inexact = RESOLUTION_APPLY_CONFIRMATION + " "

        completed = self._run_resolution_apply(
            manifest_path,
            confirm=inexact,
            augment_legacy_contract=False,
        )

        self.assertEqual(completed.returncode, 1)
        report = json.loads(completed.stdout)
        self.assertFalse(report["ok"])
        self.assertFalse(report["applied"])
        self.assertIn(
            "resolution_apply_confirmation_invalid",
            {blocker["code"] for blocker in report["blockers"]},
        )
        self.assertEqual(before, {path: path.read_bytes() for path in before})
        self.assertNotIn(inexact, completed.stdout + completed.stderr)

    def test_resolution_apply_moves_unique_private_value_to_authoritative_owner(self) -> None:
        self._write_legal_fixture()
        key = "JIEJING_BACKUP_RESTORE_DRILL_RUNBOOK_PUBLISHED"
        sentinel = "UNIQUE_PRIVATE_VALUE_MUST_NOT_LEAK"
        original_managed = self.managed_path.read_bytes()
        original_secret = self.secret_path.read_bytes()
        self.secret_path.write_bytes(original_secret + f"{key}={sentinel}\r\n".encode())
        manifest_path = self._write_resolution_manifest(
            [
                {
                    "key": key,
                    "authoritative_role": "managed",
                    "donor_role": "secret",
                }
            ]
        )
        read_only_before = {
            path: path.read_bytes()
            for path in (self.compose_path, manifest_path)
        }

        completed = self._run_resolution_apply(
            manifest_path,
            confirm=RESOLUTION_APPLY_CONFIRMATION,
            augment_legacy_contract=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)
        report = json.loads(completed.stdout)
        self.assertTrue(report["ok"], report["blockers"])
        self.assertTrue(report["applied"])
        self.assertEqual(self.secret_path.read_bytes(), original_secret)
        self.assertEqual(
            self.managed_path.read_bytes(),
            original_managed + f"{key}={sentinel}\n".encode(),
        )
        self.assertEqual(read_only_before, {path: path.read_bytes() for path in read_only_before})
        validation = check_runtime_env_ownership(
            compose_path=self.compose_path,
            managed_env_path=self.managed_path,
            secret_env_path=self.secret_path,
            postgres_env_path=self.postgres_path,
        )
        self.assertTrue(validation["ok"], validation["blockers"])
        self.assertNotIn(key, completed.stdout + completed.stderr)
        self.assertNotIn(sentinel, completed.stdout + completed.stderr)

    def test_resolution_apply_moves_equal_compose_donors_to_private_owner_only(self) -> None:
        self._write_legal_fixture()
        key = "JIEJING_BACKUP_RESTORE_DRILL_RUNBOOK_PUBLISHED"
        sentinel = "EQUAL_COMPOSE_DONOR_VALUE_MUST_NOT_LEAK"
        donor_compose = self.fixture_root / "donor-compose.yml"
        donor_compose.write_text(
            self.compose_path.read_text(encoding="utf-8").replace(
                '      JIEJING_BILLING_PROVIDER: "stripe_test_mock"\n',
                '      JIEJING_BILLING_PROVIDER: "stripe_test_mock"\n'
                f'      {key}: "{sentinel}"\n',
            ),
            encoding="utf-8",
        )
        manifest_path = self._write_resolution_manifest(
            [
                {
                    "key": key,
                    "authoritative_role": "managed",
                    "donor_role": "compose",
                }
            ]
        )
        original_managed = self.managed_path.read_bytes()
        read_only_before = {
            path: path.read_bytes()
            for path in (self.compose_path, donor_compose, manifest_path)
        }

        completed = self._run_resolution_apply(
            manifest_path,
            confirm=RESOLUTION_APPLY_CONFIRMATION,
            augment_legacy_contract=False,
            donor_compose_path=donor_compose,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)
        report = json.loads(completed.stdout)
        self.assertTrue(report["ok"], report["blockers"])
        self.assertTrue(report["applied"])
        self.assertEqual(
            self.managed_path.read_bytes(),
            original_managed + f"{key}='{sentinel}'\n".encode(),
        )
        self.assertEqual(read_only_before, {path: path.read_bytes() for path in read_only_before})
        validation = check_runtime_env_ownership(
            compose_path=self.compose_path,
            managed_env_path=self.managed_path,
            secret_env_path=self.secret_path,
            postgres_env_path=self.postgres_path,
        )
        self.assertTrue(validation["ok"], validation["blockers"])
        self.assertNotIn(key, completed.stdout + completed.stderr)
        self.assertNotIn(sentinel, completed.stdout + completed.stderr)

    def test_resolution_apply_retire_compose_donor_is_evidence_only_zero_write(self) -> None:
        self._write_legal_fixture()
        key = "JIEJING_MEDIA_LIVE_PROVIDER_ENABLED"
        sentinel = "RETIRE_PRIVATE_VALUE_MUST_NOT_LEAK"
        donor_compose = self.fixture_root / "legacy-donor-compose.yml"
        donor_compose.write_text(
            self.compose_path.read_text(encoding="utf-8").replace(
                '      JIEJING_BILLING_PROVIDER: "stripe_test_mock"\n',
                '      JIEJING_BILLING_PROVIDER: "stripe_test_mock"\n'
                f'      {key}: "{sentinel}"\n',
            ),
            encoding="utf-8",
        )
        self.secret_path.write_text(
            self.secret_path.read_text(encoding="utf-8") + f"{key}={sentinel}\n",
            encoding="utf-8",
        )
        manifest_path = self._write_resolution_manifest(
            [
                {
                    "key": key,
                    "authoritative_role": "secret",
                    "donor_role": "compose",
                    "resolution_action": "retire_equal_compose_donor_keep_authoritative",
                }
            ]
        )
        before = {
            path: path.read_bytes()
            for path in (
                self.compose_path,
                donor_compose,
                self.managed_path,
                self.secret_path,
                self.postgres_path,
                manifest_path,
            )
        }

        completed = self._run_resolution_apply(
            manifest_path,
            confirm=RESOLUTION_APPLY_CONFIRMATION,
            augment_legacy_contract=False,
            donor_compose_path=donor_compose,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)
        report = json.loads(completed.stdout)
        self.assertTrue(report["ok"], report["blockers"])
        self.assertTrue(report["applied"])
        self.assertEqual(report["summary"]["backup_count"], 0)
        self.assertEqual(report["summary"]["artifact_counts"], {})
        self.assertEqual(before, {path: path.read_bytes() for path in before})
        self.assertNotIn(key, completed.stdout + completed.stderr)
        self.assertNotIn(sentinel, completed.stdout + completed.stderr)

    def test_resolution_apply_rejects_list_form_retire_after_readonly_plan(self) -> None:
        """Mapping-only validation applies before evidence-only retire dispatch."""

        self._write_legal_fixture()
        key = "JIEJING_MEDIA_LIVE_PROVIDER_ENABLED"
        sentinel = "RETIRE_LIST_VALUE_MUST_NOT_LEAK"
        donor_text = self.compose_path.read_text(encoding="utf-8")
        for compose_key, value in (
            ("JIEJING_ENABLE_REAL_PLATFORM_WRITES", "false"),
            ("JIEJING_EBAY_WRITE_LIVE", "false"),
            ("JIEJING_PUBLIC_STAGING_REAL_WRITE_POLICY", "disabled_public_staging"),
            ("JIEJING_BILLING_PROVIDER", "stripe_test_mock"),
        ):
            donor_text = donor_text.replace(
                f'      {compose_key}: "{value}"\n',
                f"      - {compose_key}={value}\n",
            )
        donor_text = donor_text.replace(
            "      - JIEJING_BILLING_PROVIDER=stripe_test_mock\n",
            "      - JIEJING_BILLING_PROVIDER=stripe_test_mock\n"
            f"      - {key}={sentinel}\n",
        )
        donor_compose = self.fixture_root / "retire-list-donor.yml"
        donor_compose.write_text(donor_text, encoding="utf-8")
        self.secret_path.write_text(
            self.secret_path.read_text(encoding="utf-8") + f"{key}={sentinel}\n",
            encoding="utf-8",
        )
        manifest_path = self._write_resolution_manifest(
            [
                {
                    "key": key,
                    "authoritative_role": "secret",
                    "donor_role": "compose",
                    "resolution_action": "retire_equal_compose_donor_keep_authoritative",
                }
            ]
        )
        before = {
            path: path.read_bytes()
            for path in (
                self.compose_path,
                donor_compose,
                manifest_path,
                self.managed_path,
                self.secret_path,
                self.postgres_path,
            )
        }

        plan = plan_runtime_env_resolution(
            compose_path=self.compose_path,
            managed_env_path=self.managed_path,
            secret_env_path=self.secret_path,
            postgres_env_path=self.postgres_path,
            decision_manifest_path=manifest_path,
            donor_compose_path=donor_compose,
        )
        report = apply_runtime_env_resolution(
            compose_path=self.compose_path,
            managed_env_path=self.managed_path,
            secret_env_path=self.secret_path,
            postgres_env_path=self.postgres_path,
            decision_manifest_path=manifest_path,
            donor_compose_path=donor_compose,
            confirm=RESOLUTION_APPLY_CONFIRMATION,
        )

        serialized = json.dumps(report, ensure_ascii=False)
        self.assertTrue(plan["ok"], plan["blockers"])
        self.assertEqual(plan["summary"]["action_count"], 1)
        self.assertEqual(
            plan["actions"][0]["action"],
            "retire_equal_compose_donor_keep_authoritative",
        )
        self.assertFalse(report["ok"])
        self.assertFalse(report["applied"])
        self.assertIn(
            "resolution_apply_value_unrepresentable",
            {item["code"] for item in report["blockers"]},
        )
        self.assertEqual(report["summary"]["backup_count"], 0)
        self.assertEqual(before, {path: path.read_bytes() for path in before})
        self.assertNotIn(key, serialized)
        self.assertNotIn(sentinel, serialized)
        self.assertNotIn(str(donor_compose), serialized)
        self.assertFalse(report["secret_exposed"])

    def test_resolution_apply_rebuild_detects_manifest_plan_drift_before_mutation(self) -> None:
        self._write_legal_fixture()
        self.managed_path.write_text(
            self.managed_path.read_text(encoding="utf-8")
            + "JIEJING_EBAY_CLIENT_SECRET=LEGAL_SECRET_SENTINEL\n",
            encoding="utf-8",
        )
        manifest_path = self._write_resolution_manifest([])
        private_before = {
            path: path.read_bytes()
            for path in (self.managed_path, self.secret_path, self.postgres_path)
        }
        original_manifest = manifest_path.read_bytes()
        real_acquire = guard_module._acquire_migration_lock
        drifted = False

        def drift_manifest_then_lock(
            plan: guard_module.MigrationPlan,
        ) -> guard_module.MigrationLock:
            nonlocal drifted
            manifest_path.write_bytes(original_manifest + b" ")
            drifted = True
            return real_acquire(plan)

        with patch.object(guard_module, "_acquire_migration_lock", drift_manifest_then_lock):
            report = apply_runtime_env_resolution(
                compose_path=self.compose_path,
                managed_env_path=self.managed_path,
                secret_env_path=self.secret_path,
                postgres_env_path=self.postgres_path,
                decision_manifest_path=manifest_path,
                confirm=RESOLUTION_APPLY_CONFIRMATION,
            )

        self.assertTrue(drifted)
        self.assertFalse(report["ok"])
        self.assertFalse(report["applied"])
        self.assertIn(
            "resolution_apply_plan_drift",
            {blocker["code"] for blocker in report["blockers"]},
        )
        self.assertEqual(private_before, {path: path.read_bytes() for path in private_before})
        self.assertEqual(manifest_path.read_bytes(), original_manifest + b" ")
        self.assertNotIn(str(manifest_path), json.dumps(report))

    def test_resolution_apply_alias_preflight_is_zero_mutation(self) -> None:
        self._write_legal_fixture()
        before = {
            path: path.read_bytes()
            for path in (
                self.compose_path,
                self.managed_path,
                self.secret_path,
                self.postgres_path,
            )
        }

        report = apply_runtime_env_resolution(
            compose_path=self.compose_path,
            managed_env_path=self.managed_path,
            secret_env_path=self.secret_path,
            postgres_env_path=self.postgres_path,
            decision_manifest_path=self.compose_path,
            confirm=RESOLUTION_APPLY_CONFIRMATION,
        )

        self.assertFalse(report["ok"])
        self.assertFalse(report["applied"])
        self.assertIn(
            "resolution_source_path_alias",
            {blocker["code"] for blocker in report["blockers"]},
        )
        self.assertEqual(before, {path: path.read_bytes() for path in before})
        self.assertEqual(report["summary"]["backup_count"], 0)

    def test_resolution_apply_symlink_and_parent_reparse_preflight_are_zero_mutation(self) -> None:
        self._write_legal_fixture()
        manifest_path = self._write_resolution_manifest([])
        before = {
            path: path.read_bytes()
            for path in (
                self.compose_path,
                self.managed_path,
                self.secret_path,
                self.postgres_path,
                manifest_path,
            )
        }
        original_is_symlink = Path.is_symlink

        def simulated_symlink(path: Path) -> bool:
            return path == self.secret_path or original_is_symlink(path)

        with patch.object(Path, "is_symlink", simulated_symlink):
            symlink_report = apply_runtime_env_resolution(
                compose_path=self.compose_path,
                managed_env_path=self.managed_path,
                secret_env_path=self.secret_path,
                postgres_env_path=self.postgres_path,
                decision_manifest_path=manifest_path,
                confirm=RESOLUTION_APPLY_CONFIRMATION,
            )

        real_link_check = guard_module._path_is_link_or_reparse
        managed_parent = self.managed_path.parent

        def simulated_reparse(path: Path) -> bool:
            return path == managed_parent or real_link_check(path)

        with patch.object(guard_module, "_path_is_link_or_reparse", simulated_reparse):
            reparse_report = apply_runtime_env_resolution(
                compose_path=self.compose_path,
                managed_env_path=self.managed_path,
                secret_env_path=self.secret_path,
                postgres_env_path=self.postgres_path,
                decision_manifest_path=manifest_path,
                confirm=RESOLUTION_APPLY_CONFIRMATION,
            )

        self.assertIn("source_symlink", {item["code"] for item in symlink_report["blockers"]})
        self.assertIn("source_parent_link", {item["code"] for item in reparse_report["blockers"]})
        self.assertFalse(symlink_report["applied"])
        self.assertFalse(reparse_report["applied"])
        self.assertEqual(before, {path: path.read_bytes() for path in before})
        self.assertNotIn(str(self.secret_path), json.dumps(symlink_report))
        self.assertNotIn(str(managed_parent), json.dumps(reparse_report))

    def test_resolution_apply_snapshot_binds_all_six_primary_inputs(self) -> None:
        self._write_legal_fixture()
        key = "JIEJING_BACKUP_RESTORE_DRILL_RUNBOOK_PUBLISHED"
        donor_compose = self.fixture_root / "donor-compose.yml"
        donor_compose.write_text(
            self.compose_path.read_text(encoding="utf-8").replace(
                '      JIEJING_BILLING_PROVIDER: "stripe_test_mock"\n',
                '      JIEJING_BILLING_PROVIDER: "stripe_test_mock"\n'
                f'      {key}: "BOUND_INPUT_SENTINEL"\n',
            ),
            encoding="utf-8",
        )
        manifest_path = self._write_resolution_manifest(
            [{"key": key, "authoritative_role": "managed", "donor_role": "compose"}]
        )
        bound_paths = (
            self.compose_path,
            donor_compose,
            manifest_path,
            self.managed_path,
            self.secret_path,
            self.postgres_path,
        )
        originals = {path: path.read_bytes() for path in bound_paths}
        real_acquire = guard_module._acquire_migration_lock

        for drift_path in bound_paths:
            with self.subTest(role=bound_paths.index(drift_path)):
                for path, payload in originals.items():
                    path.write_bytes(payload)

                def drift_then_lock(
                    plan: guard_module.MigrationPlan,
                    *,
                    selected: Path = drift_path,
                ) -> guard_module.MigrationLock:
                    selected.write_bytes(originals[selected] + b"\n")
                    return real_acquire(plan)

                with patch.object(guard_module, "_acquire_migration_lock", drift_then_lock):
                    report = apply_runtime_env_resolution(
                        compose_path=self.compose_path,
                        managed_env_path=self.managed_path,
                        secret_env_path=self.secret_path,
                        postgres_env_path=self.postgres_path,
                        decision_manifest_path=manifest_path,
                        donor_compose_path=donor_compose,
                        confirm=RESOLUTION_APPLY_CONFIRMATION,
                    )

                self.assertFalse(report["ok"])
                self.assertFalse(report["applied"])
                self.assertIn(
                    "resolution_apply_plan_drift",
                    {blocker["code"] for blocker in report["blockers"]},
                )
                self.assertEqual(drift_path.read_bytes(), originals[drift_path] + b"\n")
                for unchanged_path in set(bound_paths) - {drift_path}:
                    self.assertEqual(unchanged_path.read_bytes(), originals[unchanged_path])
                self.assertEqual(report["summary"]["backup_count"], 0)

    def test_resolution_apply_binds_compose_override_content_before_mutation(self) -> None:
        self._write_legal_fixture()
        self.managed_path.write_text(
            self.managed_path.read_text(encoding="utf-8")
            + "JIEJING_EBAY_CLIENT_SECRET=LEGAL_SECRET_SENTINEL\n",
            encoding="utf-8",
        )
        manifest_path = self._write_resolution_manifest([])
        override_path = self.fixture_root / "docker-compose.cost-saver.yml"
        override_path.write_text(
            "services:\n"
            "  jiejing-saas:\n"
            "    deploy:\n"
            "      resources:\n"
            "        limits:\n"
            "          memory: 768M\n",
            encoding="utf-8",
        )
        private_before = {
            path: path.read_bytes()
            for path in (self.managed_path, self.secret_path, self.postgres_path)
        }
        override_before = override_path.read_bytes()
        real_acquire = guard_module._acquire_migration_lock

        def drift_override_then_lock(
            plan: guard_module.MigrationPlan,
        ) -> guard_module.MigrationLock:
            override_path.write_bytes(override_before.replace(b"768M", b"769M"))
            return real_acquire(plan)

        with patch.object(guard_module, "_acquire_migration_lock", drift_override_then_lock):
            report = apply_runtime_env_resolution(
                compose_path=self.compose_path,
                managed_env_path=self.managed_path,
                secret_env_path=self.secret_path,
                postgres_env_path=self.postgres_path,
                decision_manifest_path=manifest_path,
                compose_override_paths=(override_path,),
                confirm=RESOLUTION_APPLY_CONFIRMATION,
            )

        self.assertFalse(report["ok"])
        self.assertFalse(report["applied"])
        self.assertIn(
            "resolution_apply_plan_drift",
            {blocker["code"] for blocker in report["blockers"]},
        )
        self.assertEqual(private_before, {path: path.read_bytes() for path in private_before})
        self.assertEqual(override_path.read_bytes(), override_before.replace(b"768M", b"769M"))
        self.assertEqual(report["summary"]["backup_count"], 0)

    def test_resolution_apply_mid_transaction_failure_rolls_back_all_private_changes(self) -> None:
        self._write_legal_fixture()
        key = "JIEJING_BACKUP_RESTORE_DRILL_RUNBOOK_PUBLISHED"
        sentinel = "ROLLBACK_UNIQUE_VALUE_MUST_NOT_LEAK"
        self.secret_path.write_text(
            self.secret_path.read_text(encoding="utf-8") + f"{key}={sentinel}\n",
            encoding="utf-8",
        )
        manifest_path = self._write_resolution_manifest(
            [{"key": key, "authoritative_role": "managed", "donor_role": "secret"}]
        )
        before = {
            path: path.read_bytes()
            for path in (
                self.compose_path,
                self.managed_path,
                self.secret_path,
                self.postgres_path,
                manifest_path,
            )
        }
        real_commit = guard_module._commit_candidate
        call_count = 0

        def fail_second_private_commit(
            snapshot: guard_module.SourceSnapshot,
            candidate_payload: bytes,
            candidate_digest: str,
            mode: int,
        ) -> guard_module.CommitRecord:
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise OSError("PRIVATE_TRANSACTION_FAILURE_MUST_NOT_LEAK")
            return real_commit(snapshot, candidate_payload, candidate_digest, mode)

        with patch.object(guard_module, "_commit_candidate", fail_second_private_commit):
            report = apply_runtime_env_resolution(
                compose_path=self.compose_path,
                managed_env_path=self.managed_path,
                secret_env_path=self.secret_path,
                postgres_env_path=self.postgres_path,
                decision_manifest_path=manifest_path,
                confirm=RESOLUTION_APPLY_CONFIRMATION,
            )

        serialized = json.dumps(report, ensure_ascii=False)
        self.assertEqual(call_count, 2)
        self.assertFalse(report["ok"])
        self.assertFalse(report["applied"])
        self.assertIn("apply_atomic_replace_failed", {item["code"] for item in report["blockers"]})
        self.assertEqual(before, {path: path.read_bytes() for path in before})
        self.assertNotIn(key, serialized)
        self.assertNotIn(sentinel, serialized)
        self.assertNotIn("PRIVATE_TRANSACTION_FAILURE_MUST_NOT_LEAK", serialized)

    def test_resolution_apply_preserves_concurrent_external_change_and_fails_whole_transaction(self) -> None:
        self._write_legal_fixture()
        key = "JIEJING_BACKUP_RESTORE_DRILL_RUNBOOK_PUBLISHED"
        sentinel = "CONCURRENT_UNIQUE_VALUE_MUST_NOT_LEAK"
        self.secret_path.write_text(
            self.secret_path.read_text(encoding="utf-8") + f"{key}={sentinel}\n",
            encoding="utf-8",
        )
        manifest_path = self._write_resolution_manifest(
            [{"key": key, "authoritative_role": "managed", "donor_role": "secret"}]
        )
        secret_before = self.secret_path.read_bytes()
        concurrent = b"JIEJING_BACKUP_POLICY_CONFIGURED=external-owner-change\r\n"
        real_commit = guard_module._commit_candidate
        call_count = 0

        def inject_external_change_before_second_failure(
            snapshot: guard_module.SourceSnapshot,
            candidate_payload: bytes,
            candidate_digest: str,
            mode: int,
        ) -> guard_module.CommitRecord:
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                self.managed_path.write_bytes(concurrent)
                raise OSError("CONCURRENT_FAILURE_DETAIL_MUST_NOT_LEAK")
            return real_commit(snapshot, candidate_payload, candidate_digest, mode)

        with patch.object(
            guard_module,
            "_commit_candidate",
            inject_external_change_before_second_failure,
        ):
            report = apply_runtime_env_resolution(
                compose_path=self.compose_path,
                managed_env_path=self.managed_path,
                secret_env_path=self.secret_path,
                postgres_env_path=self.postgres_path,
                decision_manifest_path=manifest_path,
                confirm=RESOLUTION_APPLY_CONFIRMATION,
            )

        serialized = json.dumps(report, ensure_ascii=False)
        self.assertFalse(report["ok"])
        self.assertFalse(report["applied"])
        self.assertEqual(self.managed_path.read_bytes(), concurrent)
        self.assertEqual(self.secret_path.read_bytes(), secret_before)
        self.assertIn("apply_atomic_replace_failed", {item["code"] for item in report["blockers"]})
        self.assertIn("apply_rollback_source_changed", {item["code"] for item in report["blockers"]})
        self.assertNotIn(key, serialized)
        self.assertNotIn(sentinel, serialized)
        self.assertNotIn("CONCURRENT_FAILURE_DETAIL_MUST_NOT_LEAK", serialized)

    def test_resolution_apply_rolls_back_when_post_apply_desired_guard_blocks(self) -> None:
        self._write_legal_fixture()
        key = "JIEJING_BACKUP_RESTORE_DRILL_RUNBOOK_PUBLISHED"
        sentinel = "POST_GUARD_VALUE_MUST_NOT_LEAK"
        self.secret_path.write_text(
            self.secret_path.read_text(encoding="utf-8") + f"{key}={sentinel}\n",
            encoding="utf-8",
        )
        manifest_path = self._write_resolution_manifest(
            [{"key": key, "authoritative_role": "managed", "donor_role": "secret"}]
        )
        before = {
            path: path.read_bytes()
            for path in (self.managed_path, self.secret_path, self.postgres_path)
        }
        real_capture = guard_module._capture_source_snapshots

        def blocked_post_guard(**kwargs: Path) -> tuple[
            dict[str, guard_module.SourceSnapshot],
            list[dict[str, object]],
        ]:
            snapshots, blockers = real_capture(**kwargs)
            return snapshots, [*blockers, {"code": "synthetic_post_guard_blocker"}]

        with patch.object(guard_module, "_capture_source_snapshots", blocked_post_guard):
            report = apply_runtime_env_resolution(
                compose_path=self.compose_path,
                managed_env_path=self.managed_path,
                secret_env_path=self.secret_path,
                postgres_env_path=self.postgres_path,
                decision_manifest_path=manifest_path,
                confirm=RESOLUTION_APPLY_CONFIRMATION,
            )

        serialized = json.dumps(report, ensure_ascii=False)
        self.assertFalse(report["ok"])
        self.assertFalse(report["applied"])
        self.assertIn(
            "post_apply_validation_failed",
            {blocker["code"] for blocker in report["blockers"]},
        )
        self.assertEqual(before, {path: path.read_bytes() for path in before})
        self.assertNotIn(key, serialized)
        self.assertNotIn(sentinel, serialized)

    def test_resolution_apply_final_candidate_drift_rolls_back_private_commit(self) -> None:
        """Post-validator readonly drift must fail the whole private transaction."""

        self._write_legal_fixture()
        sentinel = "FINAL_CANDIDATE_DRIFT_VALUE_MUST_NOT_LEAK"
        self.managed_path.write_text(
            self.managed_path.read_text(encoding="utf-8")
            + f"JIEJING_EBAY_CLIENT_SECRET={sentinel}\n",
            encoding="utf-8",
        )
        self.secret_path.write_text(
            f"JIEJING_EBAY_CLIENT_SECRET={sentinel}\n",
            encoding="utf-8",
        )
        manifest_path = self._write_resolution_manifest([])
        private_before = {
            path: path.read_bytes()
            for path in (self.managed_path, self.secret_path, self.postgres_path)
        }
        candidate_before = self.compose_path.read_bytes()
        external_candidate = candidate_before + b"# external-final-candidate-window\n"
        real_capture = guard_module._capture_source_snapshots
        injected = False

        def drift_after_post_snapshot(**kwargs: Path) -> tuple[
            dict[str, guard_module.SourceSnapshot],
            list[dict[str, object]],
        ]:
            nonlocal injected
            snapshots, blockers = real_capture(**kwargs)
            if not injected:
                injected = True
                self.compose_path.write_bytes(external_candidate)
            return snapshots, blockers

        with patch.object(guard_module, "_capture_source_snapshots", drift_after_post_snapshot):
            report = apply_runtime_env_resolution(
                compose_path=self.compose_path,
                managed_env_path=self.managed_path,
                secret_env_path=self.secret_path,
                postgres_env_path=self.postgres_path,
                decision_manifest_path=manifest_path,
                confirm=RESOLUTION_APPLY_CONFIRMATION,
            )

        serialized = json.dumps(report, ensure_ascii=False)
        self.assertTrue(injected)
        self.assertFalse(report["ok"])
        self.assertFalse(report["applied"])
        self.assertIn("apply_source_changed", {item["code"] for item in report["blockers"]})
        self.assertEqual(private_before, {path: path.read_bytes() for path in private_before})
        self.assertEqual(self.compose_path.read_bytes(), external_candidate)
        self.assertNotIn(sentinel, serialized)
        self.assertNotIn(str(self.compose_path), serialized)
        self.assertFalse(report["secret_exposed"])

    def test_resolution_apply_readonly_drift_after_final_artifact_check_rolls_back(self) -> None:
        """The last readonly verify follows every backup/commit integrity check."""

        self._write_legal_fixture()
        key = "JIEJING_EBAY_CLIENT_SECRET"
        sentinel = "FINAL_ARTIFACT_WINDOW_VALUE_MUST_NOT_LEAK"
        self.managed_path.write_text(
            self.managed_path.read_text(encoding="utf-8") + f"{key}={sentinel}\n",
            encoding="utf-8",
        )
        self.secret_path.write_text(f"{key}={sentinel}\n", encoding="utf-8")
        manifest_path = self._write_resolution_manifest([])
        private_before = {
            path: path.read_bytes()
            for path in (self.managed_path, self.secret_path, self.postgres_path)
        }
        manifest_before = manifest_path.read_bytes()
        external_manifest = manifest_before + b" "
        real_artifact_match = guard_module._artifact_matches_snapshot
        artifact_match_count = 0

        def drift_manifest_after_third_artifact_check(
            path: Path,
            snapshot: guard_module.SourceSnapshot,
        ) -> bool:
            nonlocal artifact_match_count
            matched = real_artifact_match(path, snapshot)
            artifact_match_count += 1
            if artifact_match_count == 3:
                manifest_path.write_bytes(external_manifest)
            return matched

        with patch.object(
            guard_module,
            "_artifact_matches_snapshot",
            drift_manifest_after_third_artifact_check,
        ):
            report = apply_runtime_env_resolution(
                compose_path=self.compose_path,
                managed_env_path=self.managed_path,
                secret_env_path=self.secret_path,
                postgres_env_path=self.postgres_path,
                decision_manifest_path=manifest_path,
                confirm=RESOLUTION_APPLY_CONFIRMATION,
            )

        serialized = json.dumps(report, ensure_ascii=False)
        self.assertGreaterEqual(artifact_match_count, 3)
        self.assertFalse(report["ok"])
        self.assertFalse(report["applied"])
        self.assertIn("apply_source_changed", {item["code"] for item in report["blockers"]})
        self.assertEqual(private_before, {path: path.read_bytes() for path in private_before})
        self.assertEqual(manifest_path.read_bytes(), external_manifest)
        self.assertNotIn(str(manifest_path), serialized)
        self.assertNotIn(key, serialized)
        self.assertNotIn(sentinel, serialized)
        self.assertFalse(report["secret_exposed"])

    def test_resolution_apply_final_readonly_drift_rolls_back_private_commit(self) -> None:
        """Donor, manifest and override remain bound through the final success window."""

        cases = ("donor", "manifest", "override")
        for case in cases:
            with self.subTest(readonly_role=case):
                self._write_legal_fixture()
                donor_compose: Path | None = None
                compose_override_paths: tuple[Path, ...] = ()
                if case == "donor":
                    key = "JIEJING_BACKUP_RESTORE_DRILL_RUNBOOK_PUBLISHED"
                    donor_compose = self.fixture_root / "final-window-donor-compose.yml"
                    donor_compose.write_text(
                        self.compose_path.read_text(encoding="utf-8").replace(
                            '      JIEJING_BILLING_PROVIDER: "stripe_test_mock"\n',
                            '      JIEJING_BILLING_PROVIDER: "stripe_test_mock"\n'
                            f'      {key}: "FINAL_DONOR_VALUE_MUST_NOT_LEAK"\n',
                        ),
                        encoding="utf-8",
                    )
                    manifest_path = self._write_resolution_manifest(
                        [{"key": key, "authoritative_role": "managed", "donor_role": "compose"}]
                    )
                    selected = donor_compose
                    external = donor_compose.read_bytes() + b"# external-final-donor-window\n"
                else:
                    self.managed_path.write_text(
                        self.managed_path.read_text(encoding="utf-8")
                        + "JIEJING_EBAY_CLIENT_SECRET=FINAL_READONLY_VALUE_MUST_NOT_LEAK\n",
                        encoding="utf-8",
                    )
                    self.secret_path.write_text(
                        "JIEJING_EBAY_CLIENT_SECRET=FINAL_READONLY_VALUE_MUST_NOT_LEAK\n",
                        encoding="utf-8",
                    )
                    manifest_path = self._write_resolution_manifest([])
                    if case == "manifest":
                        selected = manifest_path
                        external = manifest_path.read_bytes() + b" "
                    else:
                        override_path = self.fixture_root / "final-window-override.yml"
                        override_path.write_text(
                            "services:\n"
                            "  jiejing-saas:\n"
                            "    deploy:\n"
                            "      resources:\n"
                            "        limits:\n"
                            "          memory: 768M\n",
                            encoding="utf-8",
                        )
                        compose_override_paths = (override_path,)
                        selected = override_path
                        external = override_path.read_bytes().replace(b"768M", b"769M")
                private_before = {
                    path: path.read_bytes()
                    for path in (self.managed_path, self.secret_path, self.postgres_path)
                }
                readonly_paths = tuple(
                    path
                    for path in (
                        self.compose_path,
                        donor_compose,
                        manifest_path,
                        *compose_override_paths,
                    )
                    if path is not None
                )
                readonly_before = {path: path.read_bytes() for path in readonly_paths}

                def drift_in_final_window(_plan: guard_module.MigrationPlan) -> None:
                    selected.write_bytes(external)

                with patch.object(
                    guard_module,
                    "_guarded_apply_after_post_validation",
                    drift_in_final_window,
                ):
                    report = apply_runtime_env_resolution(
                        compose_path=self.compose_path,
                        managed_env_path=self.managed_path,
                        secret_env_path=self.secret_path,
                        postgres_env_path=self.postgres_path,
                        decision_manifest_path=manifest_path,
                        donor_compose_path=donor_compose,
                        compose_override_paths=compose_override_paths,
                        confirm=RESOLUTION_APPLY_CONFIRMATION,
                    )

                serialized = json.dumps(report, ensure_ascii=False)
                self.assertFalse(report["ok"])
                self.assertFalse(report["applied"])
                self.assertIn(
                    "apply_source_changed",
                    {item["code"] for item in report["blockers"]},
                )
                self.assertEqual(private_before, {path: path.read_bytes() for path in private_before})
                self.assertEqual(selected.read_bytes(), external)
                for unchanged in set(readonly_paths) - {selected}:
                    self.assertEqual(unchanged.read_bytes(), readonly_before[unchanged])
                self.assertNotIn(str(selected), serialized)
                self.assertNotIn("MUST_NOT_LEAK", serialized)
                self.assertFalse(report["secret_exposed"])

    def test_resolution_apply_final_readonly_drift_fails_retire_only_without_writes(self) -> None:
        """Evidence-only apply still binds every readonly input through final return."""

        for case in ("candidate", "donor", "manifest", "override"):
            with self.subTest(readonly_role=case):
                self._write_legal_fixture()
                key = "JIEJING_MEDIA_LIVE_PROVIDER_ENABLED"
                sentinel = "FINAL_RETIRE_VALUE_MUST_NOT_LEAK"
                donor_compose = self.fixture_root / "final-retire-donor-compose.yml"
                donor_compose.write_text(
                    self.compose_path.read_text(encoding="utf-8").replace(
                        '      JIEJING_BILLING_PROVIDER: "stripe_test_mock"\n',
                        '      JIEJING_BILLING_PROVIDER: "stripe_test_mock"\n'
                        f'      {key}: "{sentinel}"\n',
                    ),
                    encoding="utf-8",
                )
                self.secret_path.write_text(
                    self.secret_path.read_text(encoding="utf-8") + f"{key}={sentinel}\n",
                    encoding="utf-8",
                )
                manifest_path = self._write_resolution_manifest(
                    [
                        {
                            "key": key,
                            "authoritative_role": "secret",
                            "donor_role": "compose",
                            "resolution_action": (
                                "retire_equal_compose_donor_keep_authoritative"
                            ),
                        }
                    ]
                )
                override_path = self.fixture_root / "final-retire-override.yml"
                override_path.write_text(
                    "services:\n"
                    "  jiejing-saas:\n"
                    "    deploy:\n"
                    "      resources:\n"
                    "        limits:\n"
                    "          memory: 768M\n",
                    encoding="utf-8",
                )
                readonly_by_role = {
                    "candidate": self.compose_path,
                    "donor": donor_compose,
                    "manifest": manifest_path,
                    "override": override_path,
                }
                selected = readonly_by_role[case]
                external = selected.read_bytes() + b"# external-final-retire-window\n"
                all_paths = (
                    self.compose_path,
                    donor_compose,
                    manifest_path,
                    override_path,
                    self.managed_path,
                    self.secret_path,
                    self.postgres_path,
                )
                before = {path: path.read_bytes() for path in all_paths}

                def drift_in_final_window(_plan: guard_module.MigrationPlan) -> None:
                    selected.write_bytes(external)

                with patch.object(
                    guard_module,
                    "_guarded_apply_after_post_validation",
                    drift_in_final_window,
                ):
                    report = apply_runtime_env_resolution(
                        compose_path=self.compose_path,
                        managed_env_path=self.managed_path,
                        secret_env_path=self.secret_path,
                        postgres_env_path=self.postgres_path,
                        decision_manifest_path=manifest_path,
                        donor_compose_path=donor_compose,
                        compose_override_paths=(override_path,),
                        confirm=RESOLUTION_APPLY_CONFIRMATION,
                    )

                serialized = json.dumps(report, ensure_ascii=False)
                self.assertFalse(report["ok"])
                self.assertFalse(report["applied"])
                self.assertIn(
                    "apply_source_changed",
                    {item["code"] for item in report["blockers"]},
                )
                self.assertEqual(selected.read_bytes(), external)
                for unchanged in set(all_paths) - {selected}:
                    self.assertEqual(unchanged.read_bytes(), before[unchanged])
                self.assertEqual(report["summary"]["backup_count"], 0)
                self.assertNotIn(str(selected), serialized)
                self.assertNotIn(key, serialized)
                self.assertNotIn(sentinel, serialized)
                self.assertFalse(report["secret_exposed"])

    def test_resolution_apply_compose_donor_uses_literal_reversible_env_encoding(self) -> None:
        """Safe Compose scalars must survive the independent env_file runtime contract."""

        safe_values = (
            ("hash", "hash#value", "hash#value"),
            ("spaces", "'  leading and trailing  '", "  leading and trailing  "),
            ("single_quote", "single'quote", "single'quote"),
            ("double_quote", 'double"quote', 'double"quote'),
            ("backslash", r"back\slash", r"back\slash"),
            ("dollar", "'${INTERPOLATED_MUST_STAY_LITERAL}'", "${INTERPOLATED_MUST_STAY_LITERAL}"),
            ("empty", '""', ""),
        )

        def reference_decode_literal_env_rhs(rhs: str) -> str:
            self.assertGreaterEqual(len(rhs), 2)
            self.assertEqual(rhs[0], "'")
            self.assertEqual(rhs[-1], "'")
            decoded: list[str] = []
            cursor = 1
            while cursor < len(rhs) - 1:
                character = rhs[cursor]
                if character == "\\" and cursor + 1 < len(rhs) - 1 and rhs[cursor + 1] == "'":
                    decoded.append("'")
                    cursor += 2
                    continue
                self.assertNotEqual(character, "'", "unescaped quote is outside the safe subset")
                decoded.append(character)
                cursor += 1
            return "".join(decoded)

        for label, donor_scalar, expected_value in safe_values:
            with self.subTest(value_kind=label):
                self._write_legal_fixture()
                key = "JIEJING_BACKUP_REVERSIBLE_COMPOSE_DONOR"
                donor_compose = self.fixture_root / f"reversible-{label}-donor.yml"
                donor_compose.write_text(
                    self.compose_path.read_text(encoding="utf-8").replace(
                        '      JIEJING_BILLING_PROVIDER: "stripe_test_mock"\n',
                        '      JIEJING_BILLING_PROVIDER: "stripe_test_mock"\n'
                        f"      {key}: {donor_scalar}\n",
                    ),
                    encoding="utf-8",
                )
                manifest_path = self._write_resolution_manifest(
                    [{"key": key, "authoritative_role": "managed", "donor_role": "compose"}]
                )
                readonly_before = {
                    path: path.read_bytes()
                    for path in (self.compose_path, donor_compose, manifest_path)
                }

                report = apply_runtime_env_resolution(
                    compose_path=self.compose_path,
                    managed_env_path=self.managed_path,
                    secret_env_path=self.secret_path,
                    postgres_env_path=self.postgres_path,
                    decision_manifest_path=manifest_path,
                    donor_compose_path=donor_compose,
                    confirm=RESOLUTION_APPLY_CONFIRMATION,
                )

                serialized = json.dumps(report, ensure_ascii=False)
                self.assertTrue(report["ok"], report["blockers"])
                self.assertTrue(report["applied"])
                target_line = next(
                    line
                    for line in self.managed_path.read_text(encoding="utf-8").splitlines()
                    if line.startswith(f"{key}=")
                )
                encoded_rhs = target_line.split("=", 1)[1]
                self.assertEqual(
                    encoded_rhs,
                    "'" + expected_value.replace("'", "\\'") + "'",
                )
                self.assertEqual(reference_decode_literal_env_rhs(encoded_rhs), expected_value)
                self.assertEqual(
                    readonly_before,
                    {path: path.read_bytes() for path in readonly_before},
                )
                self.assertNotIn(key, serialized)
                if expected_value:
                    self.assertNotIn(expected_value, serialized)
                self.assertFalse(report["secret_exposed"])

    def test_resolution_apply_compose_donor_dollar_requires_single_quoted_source(self) -> None:
        """Plain/double Compose dollar values may interpolate; only single quotes are literal."""

        key = "JIEJING_BACKUP_COMPOSE_DOLLAR_SOURCE"
        marker = "${RUNTIME_INTERPOLATION_MUST_NOT_LEAK}"
        for source_style, donor_scalar, allowed in (
            ("plain", marker, False),
            ("double", f'"{marker}"', False),
            ("single", f"'{marker}'", True),
        ):
            with self.subTest(source_style=source_style):
                self._write_legal_fixture()
                donor_compose = self.fixture_root / f"dollar-{source_style}-donor.yml"
                donor_compose.write_text(
                    self.compose_path.read_text(encoding="utf-8").replace(
                        '      JIEJING_BILLING_PROVIDER: "stripe_test_mock"\n',
                        '      JIEJING_BILLING_PROVIDER: "stripe_test_mock"\n'
                        f"      {key}: {donor_scalar}\n",
                    ),
                    encoding="utf-8",
                )
                manifest_path = self._write_resolution_manifest(
                    [{"key": key, "authoritative_role": "managed", "donor_role": "compose"}]
                )
                before = {
                    path: path.read_bytes()
                    for path in (
                        self.compose_path,
                        donor_compose,
                        manifest_path,
                        self.managed_path,
                        self.secret_path,
                        self.postgres_path,
                    )
                }

                report = apply_runtime_env_resolution(
                    compose_path=self.compose_path,
                    managed_env_path=self.managed_path,
                    secret_env_path=self.secret_path,
                    postgres_env_path=self.postgres_path,
                    decision_manifest_path=manifest_path,
                    donor_compose_path=donor_compose,
                    confirm=RESOLUTION_APPLY_CONFIRMATION,
                )

                serialized = json.dumps(report, ensure_ascii=False)
                if allowed:
                    self.assertTrue(report["ok"], report["blockers"])
                    self.assertTrue(report["applied"])
                    self.assertIn(f"{key}='{marker}'\n".encode(), self.managed_path.read_bytes())
                    for readonly in (self.compose_path, donor_compose, manifest_path):
                        self.assertEqual(readonly.read_bytes(), before[readonly])
                else:
                    self.assertFalse(report["ok"])
                    self.assertFalse(report["applied"])
                    self.assertIn(
                        "resolution_apply_value_unrepresentable",
                        {item["code"] for item in report["blockers"]},
                    )
                    self.assertEqual(before, {path: path.read_bytes() for path in before})
                self.assertNotIn(key, serialized)
                self.assertNotIn(marker, serialized)
                self.assertFalse(report["secret_exposed"])

    def test_resolution_apply_compose_list_rhs_quotes_cannot_spoof_literal_dollar(self) -> None:
        """A list item's YAML container is unquoted even when its RHS resembles a quote."""

        self._write_legal_fixture()
        key = "JIEJING_BACKUP_LIST_STYLE_SPOOF"
        marker = "${LIST_CONTEXT_MUST_NOT_LEAK}"
        donor_text = self.compose_path.read_text(encoding="utf-8")
        for compose_key, value in (
            ("JIEJING_ENABLE_REAL_PLATFORM_WRITES", "false"),
            ("JIEJING_EBAY_WRITE_LIVE", "false"),
            ("JIEJING_PUBLIC_STAGING_REAL_WRITE_POLICY", "disabled_public_staging"),
            ("JIEJING_BILLING_PROVIDER", "stripe_test_mock"),
        ):
            donor_text = donor_text.replace(
                f'      {compose_key}: "{value}"\n',
                f"      - {compose_key}={value}\n",
            )
        donor_text = donor_text.replace(
            "      - JIEJING_BILLING_PROVIDER=stripe_test_mock\n",
            "      - JIEJING_BILLING_PROVIDER=stripe_test_mock\n"
            f"      - {key}='{marker}'\n",
        )
        donor_compose = self.fixture_root / "list-style-spoof-donor.yml"
        donor_compose.write_text(donor_text, encoding="utf-8")
        manifest_path = self._write_resolution_manifest(
            [{"key": key, "authoritative_role": "managed", "donor_role": "compose"}]
        )
        before = {
            path: path.read_bytes()
            for path in (
                self.compose_path,
                donor_compose,
                manifest_path,
                self.managed_path,
                self.secret_path,
                self.postgres_path,
            )
        }

        report = apply_runtime_env_resolution(
            compose_path=self.compose_path,
            managed_env_path=self.managed_path,
            secret_env_path=self.secret_path,
            postgres_env_path=self.postgres_path,
            decision_manifest_path=manifest_path,
            donor_compose_path=donor_compose,
            confirm=RESOLUTION_APPLY_CONFIRMATION,
        )

        serialized = json.dumps(report, ensure_ascii=False)
        self.assertFalse(report["ok"])
        self.assertFalse(report["applied"])
        self.assertIn(
            "resolution_apply_value_unrepresentable",
            {item["code"] for item in report["blockers"]},
        )
        self.assertEqual(report["summary"]["backup_count"], 0)
        self.assertEqual(before, {path: path.read_bytes() for path in before})
        self.assertNotIn(key, serialized)
        self.assertNotIn(marker, serialized)
        self.assertFalse(report["secret_exposed"])

    def test_resolution_apply_rejects_plain_compose_list_donor_after_readonly_plan(self) -> None:
        """Resolution plan can report a plain list donor, but apply is mapping-only."""

        self._write_legal_fixture()
        key = "JIEJING_BACKUP_PLAIN_LIST_DONOR"
        sentinel = "PLAIN_LIST_DONOR_VALUE_MUST_NOT_LEAK"
        donor_text = self.compose_path.read_text(encoding="utf-8")
        for compose_key, value in (
            ("JIEJING_ENABLE_REAL_PLATFORM_WRITES", "false"),
            ("JIEJING_EBAY_WRITE_LIVE", "false"),
            ("JIEJING_PUBLIC_STAGING_REAL_WRITE_POLICY", "disabled_public_staging"),
            ("JIEJING_BILLING_PROVIDER", "stripe_test_mock"),
        ):
            donor_text = donor_text.replace(
                f'      {compose_key}: "{value}"\n',
                f"      - {compose_key}={value}\n",
            )
        donor_text = donor_text.replace(
            "      - JIEJING_BILLING_PROVIDER=stripe_test_mock\n",
            "      - JIEJING_BILLING_PROVIDER=stripe_test_mock\n"
            f"      - {key}={sentinel}\n",
        )
        donor_compose = self.fixture_root / "plain-list-donor.yml"
        donor_compose.write_text(donor_text, encoding="utf-8")
        manifest_path = self._write_resolution_manifest(
            [{"key": key, "authoritative_role": "managed", "donor_role": "compose"}]
        )
        before = {
            path: path.read_bytes()
            for path in (
                self.compose_path,
                donor_compose,
                manifest_path,
                self.managed_path,
                self.secret_path,
                self.postgres_path,
            )
        }

        plan = plan_runtime_env_resolution(
            compose_path=self.compose_path,
            managed_env_path=self.managed_path,
            secret_env_path=self.secret_path,
            postgres_env_path=self.postgres_path,
            decision_manifest_path=manifest_path,
            donor_compose_path=donor_compose,
        )
        report = apply_runtime_env_resolution(
            compose_path=self.compose_path,
            managed_env_path=self.managed_path,
            secret_env_path=self.secret_path,
            postgres_env_path=self.postgres_path,
            decision_manifest_path=manifest_path,
            donor_compose_path=donor_compose,
            confirm=RESOLUTION_APPLY_CONFIRMATION,
        )

        serialized = json.dumps(report, ensure_ascii=False)
        self.assertTrue(plan["ok"], plan["blockers"])
        self.assertEqual(plan["summary"]["action_count"], 1)
        self.assertFalse(report["ok"])
        self.assertFalse(report["applied"])
        self.assertIn(
            "resolution_apply_value_unrepresentable",
            {item["code"] for item in report["blockers"]},
        )
        self.assertEqual(report["summary"]["backup_count"], 0)
        self.assertEqual(before, {path: path.read_bytes() for path in before})
        self.assertNotIn(key, serialized)
        self.assertNotIn(sentinel, serialized)
        self.assertFalse(report["secret_exposed"])

    def test_resolution_apply_future_compose_action_cannot_bypass_mapping_only(self) -> None:
        """Unknown future Compose actions cross the common structure gate before dispatch."""

        self._write_legal_fixture()
        key = "JIEJING_BACKUP_FUTURE_LIST_DONOR"
        sentinel = "FUTURE_LIST_DONOR_VALUE_MUST_NOT_LEAK"
        donor_text = self.compose_path.read_text(encoding="utf-8")
        for compose_key, value in (
            ("JIEJING_ENABLE_REAL_PLATFORM_WRITES", "false"),
            ("JIEJING_EBAY_WRITE_LIVE", "false"),
            ("JIEJING_PUBLIC_STAGING_REAL_WRITE_POLICY", "disabled_public_staging"),
            ("JIEJING_BILLING_PROVIDER", "stripe_test_mock"),
        ):
            donor_text = donor_text.replace(
                f'      {compose_key}: "{value}"\n',
                f"      - {compose_key}={value}\n",
            )
        donor_text = donor_text.replace(
            "      - JIEJING_BILLING_PROVIDER=stripe_test_mock\n",
            "      - JIEJING_BILLING_PROVIDER=stripe_test_mock\n"
            f"      - {key}={sentinel}\n",
        )
        donor_compose = self.fixture_root / "future-list-donor.yml"
        donor_compose.write_text(donor_text, encoding="utf-8")
        manifest_path = self._write_resolution_manifest(
            [{"key": key, "authoritative_role": "managed", "donor_role": "compose"}]
        )
        execution_plan = guard_module._build_runtime_env_resolution(
            compose_path=self.compose_path,
            managed_env_path=self.managed_path,
            secret_env_path=self.secret_path,
            postgres_env_path=self.postgres_path,
            decision_manifest_path=manifest_path,
            donor_compose_path=donor_compose,
        )
        self.assertFalse(execution_plan.blockers)
        future_action = replace(
            execution_plan.actions[0],
            action="future_compose_donor_action",
        )
        future_plan = replace(execution_plan, actions=(future_action,))
        before = {
            path: path.read_bytes()
            for path in (
                self.compose_path,
                donor_compose,
                manifest_path,
                self.managed_path,
                self.secret_path,
                self.postgres_path,
            )
        }

        with patch.object(
            guard_module,
            "_build_runtime_env_resolution",
            return_value=future_plan,
        ):
            report = apply_runtime_env_resolution(
                compose_path=self.compose_path,
                managed_env_path=self.managed_path,
                secret_env_path=self.secret_path,
                postgres_env_path=self.postgres_path,
                decision_manifest_path=manifest_path,
                donor_compose_path=donor_compose,
                confirm=RESOLUTION_APPLY_CONFIRMATION,
            )

        serialized = json.dumps(report, ensure_ascii=False)
        self.assertFalse(report["ok"])
        self.assertFalse(report["applied"])
        self.assertIn(
            "resolution_apply_value_unrepresentable",
            {item["code"] for item in report["blockers"]},
        )
        self.assertEqual(report["summary"]["backup_count"], 0)
        self.assertEqual(before, {path: path.read_bytes() for path in before})
        self.assertNotIn(key, serialized)
        self.assertNotIn(sentinel, serialized)
        self.assertFalse(report["secret_exposed"])

    def test_resolution_apply_revalidates_compose_donor_required_service_exact(self) -> None:
        """Snapshot-bound apply refuses a donor missing one required service declaration."""

        self._write_legal_fixture()
        key = "JIEJING_BACKUP_REQUIRED_SERVICE_EXACT"
        sentinel = "REQUIRED_SERVICE_VALUE_MUST_NOT_LEAK"
        donor_compose = self.fixture_root / "required-service-donor.yml"
        donor_compose.write_text(
            self.compose_path.read_text(encoding="utf-8").replace(
                '      JIEJING_BILLING_PROVIDER: "stripe_test_mock"\n',
                '      JIEJING_BILLING_PROVIDER: "stripe_test_mock"\n'
                f'      {key}: "{sentinel}"\n',
            ),
            encoding="utf-8",
        )
        manifest_path = self._write_resolution_manifest(
            [{"key": key, "authoritative_role": "managed", "donor_role": "compose"}]
        )
        execution_plan = guard_module._build_runtime_env_resolution(
            compose_path=self.compose_path,
            managed_env_path=self.managed_path,
            secret_env_path=self.secret_path,
            postgres_env_path=self.postgres_path,
            decision_manifest_path=manifest_path,
            donor_compose_path=donor_compose,
        )
        self.assertFalse(execution_plan.blockers)
        self.assertIsNotNone(execution_plan.donor_analysis)
        incomplete_donor_analysis = replace(
            execution_plan.donor_analysis,
            declarations=tuple(
                declaration
                for declaration in execution_plan.donor_analysis.declarations
                if not (
                    declaration.key == key
                    and declaration.source == "compose:jiejing-worker"
                )
            ),
        )
        incomplete_plan = replace(
            execution_plan,
            donor_analysis=incomplete_donor_analysis,
        )
        before = {
            path: path.read_bytes()
            for path in (
                self.compose_path,
                donor_compose,
                manifest_path,
                self.managed_path,
                self.secret_path,
                self.postgres_path,
            )
        }

        with patch.object(
            guard_module,
            "_build_runtime_env_resolution",
            return_value=incomplete_plan,
        ):
            report = apply_runtime_env_resolution(
                compose_path=self.compose_path,
                managed_env_path=self.managed_path,
                secret_env_path=self.secret_path,
                postgres_env_path=self.postgres_path,
                decision_manifest_path=manifest_path,
                donor_compose_path=donor_compose,
                confirm=RESOLUTION_APPLY_CONFIRMATION,
            )

        serialized = json.dumps(report, ensure_ascii=False)
        self.assertFalse(report["ok"])
        self.assertFalse(report["applied"])
        self.assertIn(
            "resolution_apply_plan_stale",
            {item["code"] for item in report["blockers"]},
        )
        self.assertEqual(report["summary"]["backup_count"], 0)
        self.assertEqual(before, {path: path.read_bytes() for path in before})
        self.assertNotIn(key, serialized)
        self.assertNotIn(sentinel, serialized)
        self.assertFalse(report["secret_exposed"])

    def test_resolution_apply_compose_list_dollar_variants_all_fail_closed(self) -> None:
        """Comments, escapes and whole-item YAML quotes never make list-form dollars safe."""

        key = "JIEJING_BACKUP_LIST_DOLLAR_VARIANT"
        marker = "${LIST_VARIANT_MUST_NOT_LEAK}"
        for variant, raw_item in (
            ("rhs_double", f'{key}="$LIST_VARIANT_MUST_NOT_LEAK"'),
            ("rhs_comment", f"{key}='{marker}' # reviewed comment"),
            ("rhs_escape", f"{key}='{marker}\\suffix'"),
            ("whole_double", f'"{key}={marker}"'),
            ("whole_single", f"'{key}={marker}'"),
            ("whole_double_escape", f'"{key}=$LIST_VARIANT_MUST_NOT_LEAK\\\\suffix"'),
        ):
            with self.subTest(variant=variant):
                self._write_legal_fixture()
                donor_text = self.compose_path.read_text(encoding="utf-8")
                for compose_key, value in (
                    ("JIEJING_ENABLE_REAL_PLATFORM_WRITES", "false"),
                    ("JIEJING_EBAY_WRITE_LIVE", "false"),
                    ("JIEJING_PUBLIC_STAGING_REAL_WRITE_POLICY", "disabled_public_staging"),
                    ("JIEJING_BILLING_PROVIDER", "stripe_test_mock"),
                ):
                    donor_text = donor_text.replace(
                        f'      {compose_key}: "{value}"\n',
                        f"      - {compose_key}={value}\n",
                    )
                donor_text = donor_text.replace(
                    "      - JIEJING_BILLING_PROVIDER=stripe_test_mock\n",
                    "      - JIEJING_BILLING_PROVIDER=stripe_test_mock\n"
                    f"      - {raw_item}\n",
                )
                donor_compose = self.fixture_root / f"list-{variant}-donor.yml"
                donor_compose.write_text(donor_text, encoding="utf-8")
                manifest_path = self._write_resolution_manifest(
                    [{"key": key, "authoritative_role": "managed", "donor_role": "compose"}]
                )
                before = {
                    path: path.read_bytes()
                    for path in (
                        self.compose_path,
                        donor_compose,
                        manifest_path,
                        self.managed_path,
                        self.secret_path,
                        self.postgres_path,
                    )
                }

                report = apply_runtime_env_resolution(
                    compose_path=self.compose_path,
                    managed_env_path=self.managed_path,
                    secret_env_path=self.secret_path,
                    postgres_env_path=self.postgres_path,
                    decision_manifest_path=manifest_path,
                    donor_compose_path=donor_compose,
                    confirm=RESOLUTION_APPLY_CONFIRMATION,
                )

                serialized = json.dumps(report, ensure_ascii=False)
                self.assertFalse(report["ok"])
                self.assertFalse(report["applied"])
                self.assertIn(
                    "resolution_apply_value_unrepresentable",
                    {item["code"] for item in report["blockers"]},
                )
                self.assertEqual(report["summary"]["backup_count"], 0)
                self.assertEqual(before, {path: path.read_bytes() for path in before})
                self.assertNotIn(key, serialized)
                self.assertNotIn("LIST_VARIANT_MUST_NOT_LEAK", serialized)
                self.assertFalse(report["secret_exposed"])

    def test_resolution_apply_rejects_unsupported_compose_donor_structures_zero_write(self) -> None:
        """Compact/flow/tag/reference/explicit YAML structures cannot authorize apply."""

        key = "JIEJING_BACKUP_UNSUPPORTED_DONOR_STRUCTURE"
        sentinel = "UNSUPPORTED_DONOR_STRUCTURE_MUST_NOT_LEAK"
        for variant, environment_replacement in (
            ("compact_mapping_colon_space", f"environment:\n      - {key}: {sentinel}\n"),
            ("compact_mapping_colon_eol", f"environment:\n      - {key}:\n"),
            ("flow_mapping", f"environment: {{{key}: {sentinel}}}\n"),
            ("flow_sequence", f"environment: [{key}={sentinel}]\n"),
            ("tag", f"environment:\n      {key}: !unsafe {sentinel}\n"),
            ("anchor", f"environment:\n      {key}: &unsafe {sentinel}\n"),
            ("alias", f"environment:\n      {key}: *unsafe\n"),
            ("merge", "environment:\n      <<: *unsafe\n"),
            ("explicit_mapping", f"environment:\n      ? {key}\n      : {sentinel}\n"),
        ):
            with self.subTest(variant=variant):
                self._write_legal_fixture()
                donor_compose = self.fixture_root / f"unsupported-{variant}-donor.yml"
                donor_compose.write_text(
                    self.compose_path.read_text(encoding="utf-8").replace(
                        "environment:\n",
                        environment_replacement,
                    ),
                    encoding="utf-8",
                )
                manifest_path = self._write_resolution_manifest(
                    [{"key": key, "authoritative_role": "managed", "donor_role": "compose"}]
                )
                before = {
                    path: path.read_bytes()
                    for path in (
                        self.compose_path,
                        donor_compose,
                        manifest_path,
                        self.managed_path,
                        self.secret_path,
                        self.postgres_path,
                    )
                }

                report = apply_runtime_env_resolution(
                    compose_path=self.compose_path,
                    managed_env_path=self.managed_path,
                    secret_env_path=self.secret_path,
                    postgres_env_path=self.postgres_path,
                    decision_manifest_path=manifest_path,
                    donor_compose_path=donor_compose,
                    confirm=RESOLUTION_APPLY_CONFIRMATION,
                )

                serialized = json.dumps(report, ensure_ascii=False)
                self.assertFalse(report["ok"])
                self.assertFalse(report["applied"])
                self.assertGreater(report["summary"]["blocker_count"], 0)
                self.assertEqual(report["summary"]["backup_count"], 0)
                self.assertEqual(before, {path: path.read_bytes() for path in before})
                self.assertNotIn(key, serialized)
                self.assertNotIn(sentinel, serialized)
                self.assertNotIn(str(donor_compose), serialized)
                self.assertFalse(report["secret_exposed"])

    def test_resolution_apply_rejects_unrepresentable_compose_donor_values_zero_write(self) -> None:
        """Decoded newline, NUL and control values are outside the reversible subset."""

        for label, donor_scalar in (
            ("newline", '"line\\nbreak"'),
            ("nul", '"nul\\0value"'),
            ("control", '"control\\u0001value"'),
        ):
            with self.subTest(value_kind=label):
                self._write_legal_fixture()
                key = "JIEJING_BACKUP_UNREPRESENTABLE_COMPOSE_DONOR"
                donor_compose = self.fixture_root / f"unrepresentable-{label}-donor.yml"
                donor_compose.write_text(
                    self.compose_path.read_text(encoding="utf-8").replace(
                        '      JIEJING_BILLING_PROVIDER: "stripe_test_mock"\n',
                        '      JIEJING_BILLING_PROVIDER: "stripe_test_mock"\n'
                        f"      {key}: {donor_scalar}\n",
                    ),
                    encoding="utf-8",
                )
                manifest_path = self._write_resolution_manifest(
                    [{"key": key, "authoritative_role": "managed", "donor_role": "compose"}]
                )
                before = {
                    path: path.read_bytes()
                    for path in (
                        self.compose_path,
                        donor_compose,
                        manifest_path,
                        self.managed_path,
                        self.secret_path,
                        self.postgres_path,
                    )
                }

                report = apply_runtime_env_resolution(
                    compose_path=self.compose_path,
                    managed_env_path=self.managed_path,
                    secret_env_path=self.secret_path,
                    postgres_env_path=self.postgres_path,
                    decision_manifest_path=manifest_path,
                    donor_compose_path=donor_compose,
                    confirm=RESOLUTION_APPLY_CONFIRMATION,
                )

                serialized = json.dumps(report, ensure_ascii=False)
                self.assertFalse(report["ok"])
                self.assertFalse(report["applied"])
                self.assertIn(
                    "resolution_apply_value_unrepresentable",
                    {item["code"] for item in report["blockers"]},
                )
                self.assertEqual(before, {path: path.read_bytes() for path in before})
                self.assertNotIn(key, serialized)
                self.assertNotIn(donor_scalar, serialized)
                self.assertFalse(report["secret_exposed"])

    def test_resolution_apply_rejects_compose_unicode_separators_before_private_commit(self) -> None:
        """YAML-escaped Cc/Zl/Zp values must never reach the commit primitive."""

        for label, yaml_escape in (
            ("nel", r"\x85"),
            ("line_separator", r"\u2028"),
            ("paragraph_separator", r"\u2029"),
            ("other_cc", r"\u0080"),
        ):
            with self.subTest(unicode_category=label):
                self._write_legal_fixture()
                key = "JIEJING_BACKUP_UNICODE_SEPARATOR_DONOR"
                marker = "UNICODE_SEPARATOR_VALUE_MUST_NOT_LEAK"
                donor_scalar = f'"{marker}{yaml_escape}suffix"'
                donor_compose = self.fixture_root / f"unicode-{label}-donor.yml"
                donor_compose.write_text(
                    self.compose_path.read_text(encoding="utf-8").replace(
                        '      JIEJING_BILLING_PROVIDER: "stripe_test_mock"\n',
                        '      JIEJING_BILLING_PROVIDER: "stripe_test_mock"\n'
                        f"      {key}: {donor_scalar}\n",
                    ),
                    encoding="utf-8",
                )
                manifest_path = self._write_resolution_manifest(
                    [{"key": key, "authoritative_role": "managed", "donor_role": "compose"}]
                )
                before = {
                    path: path.read_bytes()
                    for path in (
                        self.compose_path,
                        donor_compose,
                        manifest_path,
                        self.managed_path,
                        self.secret_path,
                        self.postgres_path,
                    )
                }
                commit_calls = 0

                def forbidden_commit(*args: object, **kwargs: object) -> object:
                    nonlocal commit_calls
                    commit_calls += 1
                    raise AssertionError("UNICODE_SEPARATOR_MUST_FAIL_BEFORE_COMMIT")

                with patch.object(guard_module, "_commit_candidate", forbidden_commit):
                    report = apply_runtime_env_resolution(
                        compose_path=self.compose_path,
                        managed_env_path=self.managed_path,
                        secret_env_path=self.secret_path,
                        postgres_env_path=self.postgres_path,
                        decision_manifest_path=manifest_path,
                        donor_compose_path=donor_compose,
                        confirm=RESOLUTION_APPLY_CONFIRMATION,
                    )

                serialized = json.dumps(report, ensure_ascii=False)
                self.assertFalse(report["ok"])
                self.assertFalse(report["applied"])
                self.assertIn(
                    "resolution_apply_value_unrepresentable",
                    {item["code"] for item in report["blockers"]},
                )
                self.assertEqual(commit_calls, 0)
                self.assertEqual(report["summary"]["backup_count"], 0)
                self.assertEqual(before, {path: path.read_bytes() for path in before})
                self.assertNotIn(key, serialized)
                self.assertNotIn(marker, serialized)
                self.assertNotIn(str(donor_compose), serialized)
                for forbidden_field in ("key", "value", "path", "digest", "line"):
                    self.assertNotIn(f'"{forbidden_field}"', serialized)
                self.assertFalse(report["secret_exposed"])

    def test_resolution_apply_validates_complete_rendered_private_candidate_before_commit(self) -> None:
        """The full rendered payload and bound addition must agree before backup/commit."""

        self._write_legal_fixture()
        key = "JIEJING_BACKUP_RENDERED_CANDIDATE_PREFLIGHT"
        marker = "RENDERED_CANDIDATE_VALUE_MUST_NOT_LEAK"
        replacement = "ALTERED_RENDERED_VALUE_MUST_NOT_LEAK"
        donor_compose = self.fixture_root / "rendered-candidate-donor.yml"
        donor_compose.write_text(
            self.compose_path.read_text(encoding="utf-8").replace(
                '      JIEJING_BILLING_PROVIDER: "stripe_test_mock"\n',
                '      JIEJING_BILLING_PROVIDER: "stripe_test_mock"\n'
                f'      {key}: "{marker}"\n',
            ),
            encoding="utf-8",
        )
        manifest_path = self._write_resolution_manifest(
            [{"key": key, "authoritative_role": "managed", "donor_role": "compose"}]
        )
        before = {
            path: path.read_bytes()
            for path in (
                self.compose_path,
                donor_compose,
                manifest_path,
                self.managed_path,
                self.secret_path,
                self.postgres_path,
            )
        }
        real_render = guard_module._render_candidate
        commit_calls = 0

        def render_value_mismatch(*args: object, **kwargs: object) -> bytes:
            payload = real_render(*args, **kwargs)
            self.assertIn(marker.encode(), payload)
            return payload.replace(marker.encode(), replacement.encode(), 1)

        def forbidden_commit(*args: object, **kwargs: object) -> object:
            nonlocal commit_calls
            commit_calls += 1
            raise AssertionError("INVALID_RENDERED_CANDIDATE_MUST_NOT_COMMIT")

        with (
            patch.object(guard_module, "_render_candidate", render_value_mismatch),
            patch.object(guard_module, "_commit_candidate", forbidden_commit),
        ):
            report = apply_runtime_env_resolution(
                compose_path=self.compose_path,
                managed_env_path=self.managed_path,
                secret_env_path=self.secret_path,
                postgres_env_path=self.postgres_path,
                decision_manifest_path=manifest_path,
                donor_compose_path=donor_compose,
                confirm=RESOLUTION_APPLY_CONFIRMATION,
            )

        serialized = json.dumps(report, ensure_ascii=False)
        self.assertFalse(report["ok"])
        self.assertFalse(report["applied"])
        self.assertIn(
            "apply_candidate_preflight_failed",
            {item["code"] for item in report["blockers"]},
        )
        self.assertEqual(before, {path: path.read_bytes() for path in before})
        for forbidden in (key, marker, replacement, str(donor_compose)):
            self.assertNotIn(forbidden, serialized)
        for forbidden_field in ("key", "value", "path", "digest", "line"):
            self.assertNotIn(f'"{forbidden_field}"', serialized)
        self.assertFalse(report["secret_exposed"])

    def test_resolution_apply_allows_ordinary_printable_unicode_compose_donor(self) -> None:
        """Printable Unicode remains in the reversible literal env_file subset."""

        self._write_legal_fixture()
        key = "JIEJING_BACKUP_PRINTABLE_UNICODE_DONOR"
        value = "可打印-é-🙂"
        donor_compose = self.fixture_root / "printable-unicode-donor.yml"
        donor_compose.write_text(
            self.compose_path.read_text(encoding="utf-8").replace(
                '      JIEJING_BILLING_PROVIDER: "stripe_test_mock"\n',
                '      JIEJING_BILLING_PROVIDER: "stripe_test_mock"\n'
                f'      {key}: "{value}"\n',
            ),
            encoding="utf-8",
        )
        manifest_path = self._write_resolution_manifest(
            [{"key": key, "authoritative_role": "managed", "donor_role": "compose"}]
        )
        readonly_before = {
            path: path.read_bytes()
            for path in (self.compose_path, donor_compose, manifest_path)
        }

        report = apply_runtime_env_resolution(
            compose_path=self.compose_path,
            managed_env_path=self.managed_path,
            secret_env_path=self.secret_path,
            postgres_env_path=self.postgres_path,
            decision_manifest_path=manifest_path,
            donor_compose_path=donor_compose,
            confirm=RESOLUTION_APPLY_CONFIRMATION,
        )

        serialized = json.dumps(report, ensure_ascii=False)
        self.assertTrue(report["ok"], report["blockers"])
        self.assertTrue(report["applied"])
        self.assertIn(f"{key}='{value}'\n".encode(), self.managed_path.read_bytes())
        self.assertEqual(
            readonly_before,
            {path: path.read_bytes() for path in readonly_before},
        )
        self.assertNotIn(key, serialized)
        self.assertNotIn(value, serialized)
        for forbidden_field in ("key", "value", "path", "digest", "line"):
            self.assertNotIn(f'"{forbidden_field}"', serialized)
        self.assertFalse(report["secret_exposed"])

    def test_resolution_apply_rejects_private_unicode_separators_before_commit(self) -> None:
        """Private donor Cc/Zl/Zp spellings fail before any commit or backup."""

        for label, unsafe_character in (
            ("nel", "\u0085"),
            ("line_separator", "\u2028"),
            ("paragraph_separator", "\u2029"),
            ("other_cc", "\u0080"),
        ):
            with self.subTest(unicode_category=label):
                self._write_legal_fixture()
                key = "JIEJING_BACKUP_PRIVATE_UNICODE_SEPARATOR"
                marker = "PRIVATE_UNICODE_SEPARATOR_MUST_NOT_LEAK"
                self.secret_path.write_text(
                    self.secret_path.read_text(encoding="utf-8")
                    + f"{key}='{marker}{unsafe_character}suffix'\n",
                    encoding="utf-8",
                )
                manifest_path = self._write_resolution_manifest(
                    [{"key": key, "authoritative_role": "managed", "donor_role": "secret"}]
                )
                before = {
                    path: path.read_bytes()
                    for path in (
                        self.compose_path,
                        manifest_path,
                        self.managed_path,
                        self.secret_path,
                        self.postgres_path,
                    )
                }
                commit_calls = 0

                def forbidden_commit(*args: object, **kwargs: object) -> object:
                    nonlocal commit_calls
                    commit_calls += 1
                    raise AssertionError("PRIVATE_UNICODE_SEPARATOR_MUST_FAIL_PREFLIGHT")

                with patch.object(guard_module, "_commit_candidate", forbidden_commit):
                    report = apply_runtime_env_resolution(
                        compose_path=self.compose_path,
                        managed_env_path=self.managed_path,
                        secret_env_path=self.secret_path,
                        postgres_env_path=self.postgres_path,
                        decision_manifest_path=manifest_path,
                        confirm=RESOLUTION_APPLY_CONFIRMATION,
                    )

                serialized = json.dumps(report, ensure_ascii=False)
                self.assertFalse(report["ok"])
                self.assertFalse(report["applied"])
                self.assertEqual(commit_calls, 0)
                self.assertEqual(report["summary"]["backup_count"], 0)
                self.assertEqual(before, {path: path.read_bytes() for path in before})
                self.assertNotIn(key, serialized)
                self.assertNotIn(marker, serialized)
                self.assertNotIn(str(self.secret_path), serialized)
                for forbidden_field in ("key", "value", "path", "digest", "line"):
                    self.assertNotIn(f'"{forbidden_field}"', serialized)
                self.assertFalse(report["secret_exposed"])

    def test_resolution_apply_rejects_existing_private_unicode_boundaries_before_removal(self) -> None:
        """Existing NEL/LS/PS cannot be swallowed before same-file removals."""

        for role, source_path, unsafe_key, duplicate_assignment in (
            (
                "managed",
                self.managed_path,
                "JIEJING_COS_EXISTING_UNICODE_BOUNDARY",
                "JIEJING_EBAY_CLIENT_SECRET=LEGAL_SECRET_SENTINEL",
            ),
            (
                "secret",
                self.secret_path,
                "JIEJING_EBAY_CLIENT_ID",
                "JIEJING_BACKUP_POLICY_CONFIGURED=true",
            ),
            (
                "postgres",
                self.postgres_path,
                "JIEJING_DATABASE_POOL_MODE",
                "JIEJING_BACKUP_POLICY_CONFIGURED=true",
            ),
        ):
            for separator_name, unsafe_character in (
                ("nel", "\u0085"),
                ("line_separator", "\u2028"),
                ("paragraph_separator", "\u2029"),
            ):
                with self.subTest(role=role, separator=separator_name):
                    self._write_legal_fixture()
                    marker = "EXISTING_PRIVATE_BOUNDARY_MUST_NOT_LEAK"
                    source_path.write_bytes(
                        source_path.read_bytes()
                        + f"{duplicate_assignment}\n".encode()
                        + f"{unsafe_key}={marker}{unsafe_character}#hidden-tail\n".encode()
                    )
                    manifest_path = self._write_resolution_manifest([])
                    before = {
                        path: path.read_bytes()
                        for path in (
                            self.compose_path,
                            manifest_path,
                            self.managed_path,
                            self.secret_path,
                            self.postgres_path,
                        )
                    }
                    real_commit = guard_module._commit_candidate
                    commit_calls = 0

                    def count_commit(*args: object, **kwargs: object) -> object:
                        nonlocal commit_calls
                        commit_calls += 1
                        return real_commit(*args, **kwargs)

                    with patch.object(guard_module, "_commit_candidate", count_commit):
                        report = apply_runtime_env_resolution(
                            compose_path=self.compose_path,
                            managed_env_path=self.managed_path,
                            secret_env_path=self.secret_path,
                            postgres_env_path=self.postgres_path,
                            decision_manifest_path=manifest_path,
                            confirm=RESOLUTION_APPLY_CONFIRMATION,
                        )

                    serialized = json.dumps(report, ensure_ascii=False)
                    self.assertEqual(commit_calls, 0)
                    self.assertEqual(report["summary"]["backup_count"], 0)
                    self.assertFalse(report["ok"])
                    self.assertFalse(report["applied"])
                    self.assertIn(
                        "invalid_env_syntax",
                        {item["code"] for item in report["blockers"]},
                    )
                    self.assertEqual(before, {path: path.read_bytes() for path in before})
                    for forbidden in (
                        unsafe_key,
                        duplicate_assignment.split("=", 1)[0],
                        marker,
                        str(source_path),
                    ):
                        self.assertNotIn(forbidden, serialized)
                    for forbidden_field in ("key", "value", "path", "digest", "line"):
                        self.assertNotIn(f'"{forbidden_field}"', serialized)
                    self.assertFalse(report["secret_exposed"])

    def test_resolution_apply_rejects_existing_private_lone_cr_before_removal(self) -> None:
        """A lone CR in any private role fails before an unrelated same-file removal."""

        for role, source_path, unsafe_key, duplicate_assignment in (
            (
                "managed",
                self.managed_path,
                "JIEJING_COS_EXISTING_LONE_CR",
                "JIEJING_EBAY_CLIENT_SECRET=LEGAL_SECRET_SENTINEL",
            ),
            (
                "secret",
                self.secret_path,
                "JIEJING_EBAY_CLIENT_ID",
                "JIEJING_BACKUP_POLICY_CONFIGURED=true",
            ),
            (
                "postgres",
                self.postgres_path,
                "JIEJING_DATABASE_POOL_MODE",
                "JIEJING_BACKUP_POLICY_CONFIGURED=true",
            ),
        ):
            with self.subTest(role=role):
                self._write_legal_fixture()
                marker = "EXISTING_PRIVATE_LONE_CR_MUST_NOT_LEAK"
                source_path.write_bytes(
                    source_path.read_bytes()
                    + f"{duplicate_assignment}\n".encode()
                    + f"{unsafe_key}={marker}\r#hidden-tail\n".encode()
                )
                manifest_path = self._write_resolution_manifest([])
                before = {
                    path: path.read_bytes()
                    for path in (
                        self.compose_path,
                        manifest_path,
                        self.managed_path,
                        self.secret_path,
                        self.postgres_path,
                    )
                }
                commit_calls = 0

                def forbidden_commit(*args: object, **kwargs: object) -> object:
                    nonlocal commit_calls
                    commit_calls += 1
                    raise AssertionError("LONE_CR_MUST_FAIL_BEFORE_COMMIT")

                with patch.object(guard_module, "_commit_candidate", forbidden_commit):
                    report = apply_runtime_env_resolution(
                        compose_path=self.compose_path,
                        managed_env_path=self.managed_path,
                        secret_env_path=self.secret_path,
                        postgres_env_path=self.postgres_path,
                        decision_manifest_path=manifest_path,
                        confirm=RESOLUTION_APPLY_CONFIRMATION,
                    )

                serialized = json.dumps(report, ensure_ascii=False)
                self.assertFalse(report["ok"])
                self.assertFalse(report["applied"])
                self.assertIn(
                    "invalid_env_syntax",
                    {item["code"] for item in report["blockers"]},
                )
                self.assertEqual(commit_calls, 0)
                self.assertEqual(report["summary"]["backup_count"], 0)
                self.assertEqual(before, {path: path.read_bytes() for path in before})
                for forbidden in (unsafe_key, marker, str(source_path)):
                    self.assertNotIn(forbidden, serialized)
                for forbidden_field in ("key", "value", "path", "digest", "line"):
                    self.assertNotIn(f'"{forbidden_field}"', serialized)
                self.assertFalse(report["secret_exposed"])

    def test_resolution_apply_preserves_lf_crlf_and_mixed_private_line_endings(self) -> None:
        """Valid physical LF/CRLF mixtures survive an unrelated removal byte-for-byte."""

        key = "JIEJING_EBAY_CLIENT_SECRET"
        base = b"JIEJING_BACKUP_POLICY_CONFIGURED=true"
        duplicate = b"JIEJING_EBAY_CLIENT_SECRET=LEGAL_SECRET_SENTINEL"
        untouched = b"JIEJING_COS_UNTOUCHED_PRINTABLE=unicode-safe"
        for line_style, original, expected in (
            (
                "lf",
                base + b"\n" + duplicate + b"\n" + untouched + b"\n",
                base + b"\n" + untouched + b"\n",
            ),
            (
                "crlf",
                base + b"\r\n" + duplicate + b"\r\n" + untouched + b"\r\n",
                base + b"\r\n" + untouched + b"\r\n",
            ),
            (
                "mixed",
                base + b"\r\n" + duplicate + b"\n" + untouched + b"\r\n",
                base + b"\r\n" + untouched + b"\r\n",
            ),
        ):
            with self.subTest(line_style=line_style):
                self._write_legal_fixture()
                self.managed_path.write_bytes(original)
                manifest_path = self._write_resolution_manifest([])
                readonly_before = {
                    path: path.read_bytes()
                    for path in (
                        self.compose_path,
                        manifest_path,
                        self.secret_path,
                        self.postgres_path,
                    )
                }

                report = apply_runtime_env_resolution(
                    compose_path=self.compose_path,
                    managed_env_path=self.managed_path,
                    secret_env_path=self.secret_path,
                    postgres_env_path=self.postgres_path,
                    decision_manifest_path=manifest_path,
                    confirm=RESOLUTION_APPLY_CONFIRMATION,
                )

                serialized = json.dumps(report, ensure_ascii=False)
                self.assertTrue(report["ok"], report["blockers"])
                self.assertTrue(report["applied"])
                self.assertEqual(self.managed_path.read_bytes(), expected)
                self.assertEqual(
                    readonly_before,
                    {path: path.read_bytes() for path in readonly_before},
                )
                self.assertNotIn(key, serialized)
                for forbidden_field in ("key", "value", "path", "digest", "line"):
                    self.assertNotIn(f'"{forbidden_field}"', serialized)
                self.assertFalse(report["secret_exposed"])

    def test_resolution_apply_private_donor_dollar_requires_single_quoted_source(self) -> None:
        """Moving a contextual private dollar RHS is safe only when its source is literal."""

        key = "JIEJING_BACKUP_PRIVATE_DOLLAR_SOURCE"
        marker = "${PRIVATE_CONTEXT_MUST_NOT_LEAK}"
        for source_style, raw_rhs, allowed in (
            ("unquoted", marker, False),
            ("double", f'"{marker}"', False),
            ("single", f"'{marker}'", True),
        ):
            with self.subTest(source_style=source_style):
                self._write_legal_fixture()
                self.secret_path.write_text(
                    self.secret_path.read_text(encoding="utf-8") + f"{key}={raw_rhs}\n",
                    encoding="utf-8",
                )
                manifest_path = self._write_resolution_manifest(
                    [{"key": key, "authoritative_role": "managed", "donor_role": "secret"}]
                )
                before = {
                    path: path.read_bytes()
                    for path in (
                        self.compose_path,
                        manifest_path,
                        self.managed_path,
                        self.secret_path,
                        self.postgres_path,
                    )
                }

                report = apply_runtime_env_resolution(
                    compose_path=self.compose_path,
                    managed_env_path=self.managed_path,
                    secret_env_path=self.secret_path,
                    postgres_env_path=self.postgres_path,
                    decision_manifest_path=manifest_path,
                    confirm=RESOLUTION_APPLY_CONFIRMATION,
                )

                serialized = json.dumps(report, ensure_ascii=False)
                if allowed:
                    self.assertTrue(report["ok"], report["blockers"])
                    self.assertTrue(report["applied"])
                    self.assertIn(f"{key}={raw_rhs}\n".encode(), self.managed_path.read_bytes())
                    self.assertNotIn(f"{key}=".encode(), self.secret_path.read_bytes())
                    self.assertEqual(self.compose_path.read_bytes(), before[self.compose_path])
                    self.assertEqual(manifest_path.read_bytes(), before[manifest_path])
                else:
                    self.assertFalse(report["ok"])
                    self.assertFalse(report["applied"])
                    self.assertIn(
                        "resolution_apply_value_unrepresentable",
                        {item["code"] for item in report["blockers"]},
                    )
                    self.assertEqual(before, {path: path.read_bytes() for path in before})
                self.assertNotIn(key, serialized)
                self.assertNotIn(marker, serialized)
                self.assertFalse(report["secret_exposed"])

    def test_resolution_apply_private_donor_preserves_exact_runtime_rhs(self) -> None:
        """A private move binds the exact RHS; whitespace and quoting are not stripped."""

        for label, raw_rhs in (
            ("spaces", "  leading and trailing  "),
            ("literal", r"'# $ double-quote \\ literal'"),
            ("single_quote", r"'single\'quote\tail'"),
            ("double_quote", r'"double\"quote\\tail"'),
            ("empty", ""),
        ):
            with self.subTest(value_kind=label):
                self._write_legal_fixture()
                key = "JIEJING_BACKUP_PRIVATE_DONOR_RHS"
                self.secret_path.write_text(
                    self.secret_path.read_text(encoding="utf-8") + f"{key}={raw_rhs}\n",
                    encoding="utf-8",
                )
                manifest_path = self._write_resolution_manifest(
                    [{"key": key, "authoritative_role": "managed", "donor_role": "secret"}]
                )
                readonly_before = {
                    path: path.read_bytes() for path in (self.compose_path, manifest_path)
                }

                report = apply_runtime_env_resolution(
                    compose_path=self.compose_path,
                    managed_env_path=self.managed_path,
                    secret_env_path=self.secret_path,
                    postgres_env_path=self.postgres_path,
                    decision_manifest_path=manifest_path,
                    confirm=RESOLUTION_APPLY_CONFIRMATION,
                )

                serialized = json.dumps(report, ensure_ascii=False)
                self.assertTrue(report["ok"], report["blockers"])
                self.assertTrue(report["applied"])
                self.assertIn(f"{key}={raw_rhs}\n".encode(), self.managed_path.read_bytes())
                self.assertNotIn(f"{key}=".encode(), self.secret_path.read_bytes())
                self.assertEqual(
                    readonly_before,
                    {path: path.read_bytes() for path in readonly_before},
                )
                self.assertNotIn(key, serialized)
                if raw_rhs:
                    self.assertNotIn(raw_rhs, serialized)
                self.assertFalse(report["secret_exposed"])

    def test_resolution_apply_complete_live_97_action_fixture_reaches_zero_blockers(self) -> None:
        self._write_legal_fixture()
        sentinel = "FULL_LIVE_97_VALUE_MUST_NOT_LEAK"
        keys = [f"JIEJING_BACKUP_SYNTHETIC_LIVE_{index:03d}" for index in range(97)]
        original_managed = self.managed_path.read_bytes()
        original_secret = self.secret_path.read_bytes()
        self.managed_path.write_bytes(
            original_managed
            + b"".join(f"{key}={sentinel}\n".encode() for key in keys)
        )
        self.secret_path.write_bytes(
            original_secret
            + b"".join(f"{key}={sentinel}\r\n".encode() for key in keys)
        )
        donor_compose = self.fixture_root / "current-live-donor-compose.yml"
        donor_compose.write_bytes(self.compose_path.read_bytes())
        manifest_path = self._write_resolution_manifest([])
        managed_before_apply = self.managed_path.read_bytes()
        read_only_before = {
            path: path.read_bytes()
            for path in (self.compose_path, donor_compose, manifest_path)
        }

        completed = self._run_resolution_apply(
            manifest_path,
            confirm=RESOLUTION_APPLY_CONFIRMATION,
            augment_legacy_contract=False,
            donor_compose_path=donor_compose,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)
        report = json.loads(completed.stdout)
        self.assertTrue(report["ok"], report["blockers"])
        self.assertTrue(report["applied"])
        self.assertEqual(report["summary"]["action_count"], 97)
        self.assertEqual(
            report["actions"],
            [
                {
                    "action": "remove_equal_duplicate",
                    "source_role": "secret",
                    "target_role": "managed",
                    "count": 97,
                }
            ],
        )
        self.assertEqual(self.managed_path.read_bytes(), managed_before_apply)
        self.assertEqual(self.secret_path.read_bytes(), original_secret)
        self.assertEqual(read_only_before, {path: path.read_bytes() for path in read_only_before})
        validation = check_runtime_env_ownership(
            compose_path=self.compose_path,
            managed_env_path=self.managed_path,
            secret_env_path=self.secret_path,
            postgres_env_path=self.postgres_path,
        )
        self.assertTrue(validation["ok"], validation["blockers"])
        self.assertEqual(validation["summary"]["blocker_count"], 0)
        self.assertNotIn(keys[0], completed.stdout + completed.stderr)
        self.assertNotIn(keys[-1], completed.stdout + completed.stderr)
        self.assertNotIn(sentinel, completed.stdout + completed.stderr)
        self.assertFalse(report["secret_exposed"])
        self.assertEqual(
            sorted(key for key in _all_json_keys(report) if _looks_like_value_field(key)),
            [],
        )

    def test_resolution_plan_candidate_compose_uses_future_runtime_path(self) -> None:
        self._write_legal_fixture()
        candidate_dir = self.fixture_root / "candidate" / "deploy"
        candidate_dir.mkdir(parents=True)
        candidate_compose = candidate_dir / self.compose_path.name
        candidate_compose.write_text(self.compose_path.read_text(encoding="utf-8"), encoding="utf-8")
        manifest_path = self._write_resolution_manifest([])

        completed = self._run_resolution_plan(
            manifest_path,
            augment_legacy_contract=False,
            compose_path=candidate_compose,
            compose_runtime_path=self.compose_path,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)
        report = json.loads(completed.stdout)
        self.assertTrue(report["ok"], report["blockers"])
        self.assertFalse(report["secret_exposed"])
        self.assertNotIn(str(candidate_compose), completed.stdout + completed.stderr)
        self.assertNotIn(str(self.compose_path), completed.stdout + completed.stderr)

    def test_resolution_plan_can_move_equal_read_only_compose_donors_to_missing_owner(self) -> None:
        self._write_legal_fixture()
        sentinel = "COMPOSE_DONOR_VALUE_MUST_NOT_LEAK"
        donor_compose = self.fixture_root / "donor-compose.yml"
        donor_compose.write_text(
            self.compose_path.read_text(encoding="utf-8").replace(
                '      JIEJING_BILLING_PROVIDER: "stripe_test_mock"\n',
                '      JIEJING_BILLING_PROVIDER: "stripe_test_mock"\n'
                f'      JIEJING_BACKUP_RESTORE_DRILL_RUNBOOK_PUBLISHED: "{sentinel}"\n',
            ),
            encoding="utf-8",
        )
        manifest_path = self._write_resolution_manifest(
            [
                {
                    "key": "JIEJING_BACKUP_RESTORE_DRILL_RUNBOOK_PUBLISHED",
                    "authoritative_role": "managed",
                    "donor_role": "compose",
                }
            ]
        )
        before = {
            path: path.read_bytes()
            for path in (
                self.compose_path,
                donor_compose,
                self.managed_path,
                self.secret_path,
                self.postgres_path,
            )
        }

        completed = self._run_resolution_plan(
            manifest_path,
            augment_legacy_contract=False,
            donor_compose_path=donor_compose,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)
        self.assertNotIn(sentinel, completed.stdout + completed.stderr)
        report = json.loads(completed.stdout)
        self.assertTrue(report["ok"], report["blockers"])
        self.assertEqual(
            report["actions"],
            [
                {
                    "action": "move_equal_donors_to_authoritative",
                    "key": "JIEJING_BACKUP_RESTORE_DRILL_RUNBOOK_PUBLISHED",
                    "source_role": "compose",
                    "target_role": "managed",
                    "count": 2,
                    "comparison": "equal",
                }
            ],
        )
        self.assertEqual(
            before,
            {path: path.read_bytes() for path in before},
        )
        self.assertEqual(
            sorted(key for key in _all_json_keys(report) if _looks_like_value_field(key)),
            [],
        )

    def test_resolution_plan_retires_equal_compose_donor_when_secret_owner_exists(self) -> None:
        self._write_legal_fixture()
        key = "JIEJING_MEDIA_LIVE_PROVIDER_ENABLED"
        sentinel = "RETIRE_EQUAL_PRIVATE_VALUE_MUST_NOT_LEAK"
        donor_compose = self.fixture_root / "legacy-donor-compose.yml"
        donor_compose.write_text(
            self.compose_path.read_text(encoding="utf-8").replace(
                '      JIEJING_BILLING_PROVIDER: "stripe_test_mock"\n',
                '      JIEJING_BILLING_PROVIDER: "stripe_test_mock"\n'
                f'      {key}: "{sentinel}"\n',
            ),
            encoding="utf-8",
        )
        self.secret_path.write_text(
            self.secret_path.read_text(encoding="utf-8") + f"{key}={sentinel}\n",
            encoding="utf-8",
        )
        manifest_path = self._write_resolution_manifest(
            [
                {
                    "key": key,
                    "authoritative_role": "secret",
                    "donor_role": "compose",
                    "resolution_action": "retire_equal_compose_donor_keep_authoritative",
                }
            ]
        )
        before = {
            path: path.read_bytes()
            for path in (
                self.compose_path,
                donor_compose,
                self.managed_path,
                self.secret_path,
                self.postgres_path,
                manifest_path,
            )
        }

        completed = self._run_resolution_plan(
            manifest_path,
            augment_legacy_contract=False,
            donor_compose_path=donor_compose,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)
        self.assertNotIn(sentinel, completed.stdout + completed.stderr)
        report = json.loads(completed.stdout)
        self.assertTrue(report["ok"], report["blockers"])
        self.assertFalse(report["applied"])
        self.assertEqual(report["blockers"], [])
        self.assertEqual(
            report["actions"],
            [
                {
                    "action": "retire_equal_compose_donor_keep_authoritative",
                    "key": key,
                    "source_role": "compose",
                    "target_role": "secret",
                    "count": 2,
                    "comparison": "equal",
                }
            ],
        )
        self.assertEqual(before, {path: path.read_bytes() for path in before})
        self.assertEqual(
            sorted(key for key in _all_json_keys(report) if _looks_like_value_field(key)),
            [],
        )

    def test_resolution_plan_retire_action_fails_closed_when_preconditions_are_not_exact(self) -> None:
        key = "JIEJING_MEDIA_LIVE_VIDEO_ENABLED"
        cases = (
            ("owner_conflict", "resolution_retire_owner_donor_conflict"),
            ("owner_missing", "resolution_retire_authoritative_owner_missing"),
            ("candidate_declares", "resolution_retire_candidate_declaration_present"),
            ("service_topology", "resolution_compose_donor_service_topology_invalid"),
        )
        for case_name, expected_code in cases:
            with self.subTest(case_name=case_name):
                self._write_legal_fixture()
                owner_value = "RETIRE_OWNER_VALUE_MUST_NOT_LEAK"
                donor_value = (
                    "RETIRE_DONOR_CONFLICT_MUST_NOT_LEAK"
                    if case_name == "owner_conflict"
                    else owner_value
                )
                donor_compose = self.fixture_root / f"{case_name}-legacy-donor.yml"
                donor_compose.write_text(
                    self.compose_path.read_text(encoding="utf-8").replace(
                        '      JIEJING_BILLING_PROVIDER: "stripe_test_mock"\n',
                        '      JIEJING_BILLING_PROVIDER: "stripe_test_mock"\n'
                        f'      {key}: "{donor_value}"\n',
                        1 if case_name == "service_topology" else -1,
                    ),
                    encoding="utf-8",
                )
                if case_name != "owner_missing":
                    self.secret_path.write_text(
                        self.secret_path.read_text(encoding="utf-8")
                        + f"{key}={owner_value}\n",
                        encoding="utf-8",
                    )
                if case_name == "candidate_declares":
                    self.compose_path.write_text(
                        self.compose_path.read_text(encoding="utf-8").replace(
                            '      JIEJING_BILLING_PROVIDER: "stripe_test_mock"\n',
                            '      JIEJING_BILLING_PROVIDER: "stripe_test_mock"\n'
                            f'      {key}: "{owner_value}"\n',
                        ),
                        encoding="utf-8",
                    )
                manifest_path = self._write_resolution_manifest(
                    [
                        {
                            "key": key,
                            "authoritative_role": "secret",
                            "donor_role": "compose",
                            "resolution_action": "retire_equal_compose_donor_keep_authoritative",
                        }
                    ]
                )
                before = {
                    path: path.read_bytes()
                    for path in (
                        self.compose_path,
                        donor_compose,
                        self.managed_path,
                        self.secret_path,
                        self.postgres_path,
                        manifest_path,
                    )
                }

                completed = self._run_resolution_plan(
                    manifest_path,
                    augment_legacy_contract=False,
                    donor_compose_path=donor_compose,
                )

                self.assertNotEqual(completed.returncode, 0)
                report = json.loads(completed.stdout)
                self.assertFalse(report["ok"])
                self.assertFalse(report["applied"])
                self.assertEqual(report["actions"], [])
                self.assertIn(expected_code, {blocker["code"] for blocker in report["blockers"]})
                self.assertEqual(before, {path: path.read_bytes() for path in before})
                serialized = completed.stdout + completed.stderr
                self.assertNotIn(owner_value, serialized)
                self.assertNotIn(donor_value, serialized)
                self.assertNotIn(str(donor_compose), serialized)
                self.assertNotIn("digest", serialized.casefold())
                self.assertEqual(
                    sorted(field for field in _all_json_keys(report) if _looks_like_value_field(field)),
                    [],
                )

    def test_resolution_plan_resolves_private_forbidden_value_with_explicit_safe_compose_keep(self) -> None:
        self._write_legal_fixture()
        sentinel = "FORBIDDEN_PRIVATE_VALUE_MUST_NOT_LEAK"
        self.secret_path.write_text(
            self.secret_path.read_text(encoding="utf-8")
            + f"JIEJING_ENABLE_REAL_PLATFORM_WRITES={sentinel}\n",
            encoding="utf-8",
        )
        manifest_path = self._write_resolution_manifest(
            [
                {
                    "key": "JIEJING_ENABLE_REAL_PLATFORM_WRITES",
                    "authoritative_role": "compose",
                }
            ]
        )

        completed = self._run_resolution_plan(
            manifest_path,
            augment_legacy_contract=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)
        self.assertNotIn(sentinel, completed.stdout + completed.stderr)
        report = json.loads(completed.stdout)
        self.assertTrue(report["ok"], report["blockers"])
        self.assertEqual(
            [
                action
                for action in report["actions"]
                if action["key"] == "JIEJING_ENABLE_REAL_PLATFORM_WRITES"
            ],
            [
                {
                    "action": "keep_authoritative_remove_wrong_source",
                    "key": "JIEJING_ENABLE_REAL_PLATFORM_WRITES",
                    "source_role": "secret",
                    "target_role": "compose",
                    "count": 1,
                    "comparison": "conflict",
                }
            ],
        )
        self.assertNotIn(
            "forbidden_staging_value",
            {blocker["code"] for blocker in report["blockers"]},
        )

    def test_resolution_plan_keeps_forbidden_blocker_when_candidate_compose_is_unsafe(self) -> None:
        self._write_legal_fixture()
        self.compose_path.write_text(
            self.compose_path.read_text(encoding="utf-8").replace(
                'JIEJING_ENABLE_REAL_PLATFORM_WRITES: "false"',
                'JIEJING_ENABLE_REAL_PLATFORM_WRITES: "true"',
            ),
            encoding="utf-8",
        )
        self.secret_path.write_text(
            self.secret_path.read_text(encoding="utf-8")
            + "JIEJING_ENABLE_REAL_PLATFORM_WRITES=true\n",
            encoding="utf-8",
        )
        manifest_path = self._write_resolution_manifest(
            [
                {
                    "key": "JIEJING_ENABLE_REAL_PLATFORM_WRITES",
                    "authoritative_role": "compose",
                }
            ]
        )

        completed = self._run_resolution_plan(
            manifest_path,
            augment_legacy_contract=False,
        )

        self.assertNotEqual(completed.returncode, 0)
        report = json.loads(completed.stdout)
        self.assertFalse(report["ok"])
        self.assertIn(
            "forbidden_staging_value",
            {blocker["code"] for blocker in report["blockers"]},
        )
        self.assertFalse(report["secret_exposed"])

    def test_resolution_plan_rejects_conflicting_compose_donor_values(self) -> None:
        self._write_legal_fixture()
        first_sentinel = "DONOR_CONFLICT_ONE_MUST_NOT_LEAK"
        second_sentinel = "DONOR_CONFLICT_TWO_MUST_NOT_LEAK"
        billing_line = '      JIEJING_BILLING_PROVIDER: "stripe_test_mock"\n'
        donor_text = self.compose_path.read_text(encoding="utf-8").replace(
            billing_line,
            billing_line
            + f'      JIEJING_BACKUP_RESTORE_DRILL_RUNBOOK_PUBLISHED: "{first_sentinel}"\n',
            1,
        )
        donor_prefix, donor_suffix = donor_text.rsplit(billing_line, 1)
        donor_text = (
            donor_prefix
            + billing_line
            + f'      JIEJING_BACKUP_RESTORE_DRILL_RUNBOOK_PUBLISHED: "{second_sentinel}"\n'
            + donor_suffix
        )
        donor_compose = self.fixture_root / "conflicting-donor-compose.yml"
        donor_compose.write_text(donor_text, encoding="utf-8")
        manifest_path = self._write_resolution_manifest(
            [
                {
                    "key": "JIEJING_BACKUP_RESTORE_DRILL_RUNBOOK_PUBLISHED",
                    "authoritative_role": "managed",
                    "donor_role": "compose",
                }
            ]
        )

        completed = self._run_resolution_plan(
            manifest_path,
            augment_legacy_contract=False,
            donor_compose_path=donor_compose,
        )

        self.assertNotEqual(completed.returncode, 0)
        self.assertNotIn(first_sentinel, completed.stdout + completed.stderr)
        self.assertNotIn(second_sentinel, completed.stdout + completed.stderr)
        report = json.loads(completed.stdout)
        self.assertIn(
            "resolution_compose_donor_conflict",
            {blocker["code"] for blocker in report["blockers"]},
        )

    def test_resolution_plan_requires_exact_compose_donor_runtime_service_topology(self) -> None:
        self._write_legal_fixture()
        key = "JIEJING_BACKUP_RESTORE_DRILL_RUNBOOK_PUBLISHED"
        manifest_path = self._write_resolution_manifest(
            [{"key": key, "authoritative_role": "managed", "donor_role": "compose"}]
        )

        def runtime_service(name: str, donor_count: int) -> str:
            donor_lines = "".join(
                f'      {key}: "DONOR_SERVICE_TOPOLOGY_MUST_NOT_LEAK"\n'
                for _ in range(donor_count)
            )
            return (
                f"  {name}:\n"
                "    env_file:\n"
                "      - ./runtime-env/tencent-managed.env\n"
                "      - ./runtime-env/jiejing-saas.staging-oauth.env\n"
                "      - ./runtime-env/postgres-localqueue.env\n"
                "    environment:\n"
                '      JIEJING_ENABLE_REAL_PLATFORM_WRITES: "false"\n'
                '      JIEJING_EBAY_WRITE_LIVE: "false"\n'
                '      JIEJING_PUBLIC_STAGING_REAL_WRITE_POLICY: "disabled_public_staging"\n'
                '      JIEJING_BILLING_PROVIDER: "stripe_test_mock"\n'
                + donor_lines
            )

        def sidecar_service(donor_count: int) -> str:
            donor_lines = "".join(
                f'      {key}: "DONOR_SERVICE_TOPOLOGY_MUST_NOT_LEAK"\n'
                for _ in range(donor_count)
            )
            return "  metrics-sidecar:\n    environment:\n" + donor_lines

        cases = {
            "single_saas": runtime_service("jiejing-saas", 1) + runtime_service("jiejing-worker", 0),
            "single_worker": runtime_service("jiejing-saas", 0) + runtime_service("jiejing-worker", 1),
            "sidecar_only": (
                runtime_service("jiejing-saas", 0)
                + runtime_service("jiejing-worker", 0)
                + sidecar_service(1)
            ),
            "extra_sidecar": (
                runtime_service("jiejing-saas", 1)
                + runtime_service("jiejing-worker", 1)
                + sidecar_service(1)
            ),
            "same_service_repeat": (
                runtime_service("jiejing-saas", 2) + runtime_service("jiejing-worker", 1)
            ),
        }
        for case_name, services in cases.items():
            with self.subTest(case_name=case_name):
                donor_compose = self.fixture_root / f"{case_name}-donor-compose.yml"
                donor_compose.write_text("services:\n" + services, encoding="utf-8")

                completed = self._run_resolution_plan(
                    manifest_path,
                    augment_legacy_contract=False,
                    donor_compose_path=donor_compose,
                )

                self.assertNotEqual(completed.returncode, 0)
                self.assertNotIn(
                    "DONOR_SERVICE_TOPOLOGY_MUST_NOT_LEAK",
                    completed.stdout + completed.stderr,
                )
                report = json.loads(completed.stdout)
                self.assertIn(
                    "resolution_compose_donor_service_topology_invalid",
                    {blocker["code"] for blocker in report["blockers"]},
                )
                self.assertFalse(
                    any(
                        action["key"] == key
                        and action["action"] == "move_equal_donors_to_authoritative"
                        for action in report["actions"]
                    )
                )

    def test_resolution_plan_rejects_missing_compose_donor_declaration(self) -> None:
        self._write_legal_fixture()
        donor_compose = self.fixture_root / "missing-key-donor-compose.yml"
        donor_compose.write_text(self.compose_path.read_text(encoding="utf-8"), encoding="utf-8")
        manifest_path = self._write_resolution_manifest(
            [
                {
                    "key": "JIEJING_BACKUP_RESTORE_DRILL_RUNBOOK_PUBLISHED",
                    "authoritative_role": "managed",
                    "donor_role": "compose",
                }
            ]
        )

        completed = self._run_resolution_plan(
            manifest_path,
            augment_legacy_contract=False,
            donor_compose_path=donor_compose,
        )

        self.assertNotEqual(completed.returncode, 0)
        report = json.loads(completed.stdout)
        self.assertIn(
            "resolution_compose_donor_missing",
            {blocker["code"] for blocker in report["blockers"]},
        )
        self.assertFalse(report["secret_exposed"])

    def test_resolution_plan_rejects_compose_donor_when_target_owner_already_exists(self) -> None:
        self._write_legal_fixture()
        key = "JIEJING_BACKUP_RESTORE_DRILL_RUNBOOK_PUBLISHED"
        self.managed_path.write_text(
            self.managed_path.read_text(encoding="utf-8") + f"{key}=TARGET_OWNER_EXISTS\n",
            encoding="utf-8",
        )
        donor_compose = self.fixture_root / "owner-present-donor-compose.yml"
        donor_compose.write_text(
            self.compose_path.read_text(encoding="utf-8").replace(
                '      JIEJING_BILLING_PROVIDER: "stripe_test_mock"\n',
                '      JIEJING_BILLING_PROVIDER: "stripe_test_mock"\n'
                f'      {key}: "DONOR_MUST_NOT_LEAK"\n',
            ),
            encoding="utf-8",
        )
        manifest_path = self._write_resolution_manifest(
            [{"key": key, "authoritative_role": "managed", "donor_role": "compose"}]
        )

        completed = self._run_resolution_plan(
            manifest_path,
            augment_legacy_contract=False,
            donor_compose_path=donor_compose,
        )

        self.assertNotEqual(completed.returncode, 0)
        self.assertNotIn("DONOR_MUST_NOT_LEAK", completed.stdout + completed.stderr)
        self.assertNotIn("TARGET_OWNER_EXISTS", completed.stdout + completed.stderr)
        report = json.loads(completed.stdout)
        self.assertIn(
            "resolution_donor_target_topology_not_empty",
            {blocker["code"] for blocker in report["blockers"]},
        )

    def test_resolution_plan_rejects_invalid_and_structurally_unsafe_donor_paths(self) -> None:
        self._write_legal_fixture()
        manifest_path = self._write_resolution_manifest([])
        missing_donor = self.fixture_root / "missing-donor-compose.yml"
        missing_report = plan_runtime_env_resolution(
            compose_path=self.compose_path,
            managed_env_path=self.managed_path,
            secret_env_path=self.secret_path,
            postgres_env_path=self.postgres_path,
            decision_manifest_path=manifest_path,
            donor_compose_path=missing_donor,
        )
        self.assertFalse(missing_report["ok"])
        self.assertIn("source_missing", {blocker["code"] for blocker in missing_report["blockers"]})
        self.assertNotIn(str(missing_donor), json.dumps(missing_report))

        invalid_donor = self.fixture_root / "invalid-donor-compose.yml"
        invalid_donor.write_text("services: {}\n", encoding="utf-8")
        invalid_report = plan_runtime_env_resolution(
            compose_path=self.compose_path,
            managed_env_path=self.managed_path,
            secret_env_path=self.secret_path,
            postgres_env_path=self.postgres_path,
            decision_manifest_path=manifest_path,
            donor_compose_path=invalid_donor,
        )
        self.assertFalse(invalid_report["ok"])
        self.assertIn(
            "unsupported_inline_compose_services",
            {blocker["code"] for blocker in invalid_report["blockers"]},
        )
        self.assertNotIn(str(invalid_donor), json.dumps(invalid_report))

    def test_resolution_plan_rejects_symlink_donor_without_path_leakage(self) -> None:
        self._write_legal_fixture()
        donor_compose = self.fixture_root / "donor-compose.yml"
        donor_compose.write_text(self.compose_path.read_text(encoding="utf-8"), encoding="utf-8")
        manifest_path = self._write_resolution_manifest([])
        original_is_symlink = Path.is_symlink

        def simulated_is_symlink(path: Path) -> bool:
            return path == donor_compose or original_is_symlink(path)

        with patch.object(Path, "is_symlink", simulated_is_symlink):
            report = plan_runtime_env_resolution(
                compose_path=self.compose_path,
                managed_env_path=self.managed_path,
                secret_env_path=self.secret_path,
                postgres_env_path=self.postgres_path,
                decision_manifest_path=manifest_path,
                donor_compose_path=donor_compose,
            )

        self.assertFalse(report["ok"])
        self.assertIn("source_symlink", {blocker["code"] for blocker in report["blockers"]})
        self.assertNotIn(str(donor_compose), json.dumps(report))
        self.assertFalse(report["secret_exposed"])

    def test_resolution_plan_rejects_parent_reparse_for_donor_and_manifest(self) -> None:
        self._write_legal_fixture()
        donor_parent = self.fixture_root / "donor-parent"
        donor_parent.mkdir()
        donor_compose = donor_parent / "donor-compose.yml"
        donor_compose.write_text(self.compose_path.read_text(encoding="utf-8"), encoding="utf-8")
        manifest_parent = self.fixture_root / "manifest-parent"
        manifest_parent.mkdir()
        manifest_path = manifest_parent / "resolution-manifest.json"
        manifest_path.write_text(
            json.dumps(
                {"schema_version": RESOLUTION_MANIFEST_SCHEMA_VERSION, "decisions": []}
            ),
            encoding="utf-8",
        )
        real_link_check = guard_module._path_is_link_or_reparse

        def simulated_reparse(path: Path) -> bool:
            return path in {donor_parent, manifest_parent} or real_link_check(path)

        with patch.object(guard_module, "_path_is_link_or_reparse", simulated_reparse):
            report = plan_runtime_env_resolution(
                compose_path=self.compose_path,
                managed_env_path=self.managed_path,
                secret_env_path=self.secret_path,
                postgres_env_path=self.postgres_path,
                decision_manifest_path=manifest_path,
                donor_compose_path=donor_compose,
            )

        serialized = json.dumps(report, ensure_ascii=False)
        self.assertFalse(report["ok"])
        self.assertGreaterEqual(
            sum(blocker["code"] == "source_parent_link" for blocker in report["blockers"]),
            2,
        )
        self.assertTrue(
            any(
                blocker.get("code") == "source_parent_link"
                and blocker.get("source_role") == "compose"
                for blocker in report["blockers"]
            )
        )
        self.assertNotIn(str(donor_parent), serialized)
        self.assertNotIn(str(manifest_parent), serialized)
        self.assertFalse(report["secret_exposed"])

    def test_resolution_plan_rejects_donor_parent_directory_swap_after_parent_check(self) -> None:
        self._write_legal_fixture()
        key = "JIEJING_BACKUP_RESTORE_DRILL_RUNBOOK_PUBLISHED"
        sentinel = "DONOR_PARENT_SWAP_MUST_NOT_LEAK"
        billing_line = '      JIEJING_BILLING_PROVIDER: "stripe_test_mock"\n'
        donor_payload = self.compose_path.read_text(encoding="utf-8").replace(
            billing_line,
            billing_line + f'      {key}: "{sentinel}"\n',
            2,
        )
        for relative_path, runtime_path in (
            ("./runtime-env/tencent-managed.env", self.managed_path),
            ("./runtime-env/jiejing-saas.staging-oauth.env", self.secret_path),
            ("./runtime-env/postgres-localqueue.env", self.postgres_path),
        ):
            donor_payload = donor_payload.replace(relative_path, runtime_path.as_posix())
        donor_parent = self.fixture_root / "donor-live"
        donor_parent.mkdir()
        donor_compose = donor_parent / "docker-compose.yml"
        donor_compose.write_text(donor_payload, encoding="utf-8")
        replacement_parent = self.fixture_root / "donor-replacement"
        replacement_parent.mkdir()
        (replacement_parent / donor_compose.name).write_text(donor_payload, encoding="utf-8")
        parked_parent = self.fixture_root / "donor-parked"
        manifest_path = self._write_resolution_manifest(
            [{"key": key, "authoritative_role": "managed", "donor_role": "compose"}]
        )
        real_parent_check = guard_module._source_parent_link_blocker
        swapped = False

        def swap_after_parent_check(path: Path, source: str) -> dict[str, object] | None:
            nonlocal swapped
            blocker = real_parent_check(path, source)
            if source == guard_module.DONOR_COMPOSE_SOURCE and blocker is None and not swapped:
                swapped = True
                donor_parent.rename(parked_parent)
                replacement_parent.rename(donor_parent)
            return blocker

        with patch.object(
            guard_module,
            "_source_parent_link_blocker",
            swap_after_parent_check,
        ):
            report = plan_runtime_env_resolution(
                compose_path=self.compose_path,
                managed_env_path=self.managed_path,
                secret_env_path=self.secret_path,
                postgres_env_path=self.postgres_path,
                decision_manifest_path=manifest_path,
                donor_compose_path=donor_compose,
            )

        serialized = json.dumps(report, ensure_ascii=False)
        self.assertTrue(swapped)
        self.assertFalse(report["ok"])
        self.assertIn(
            "source_parent_changed_during_snapshot",
            {blocker["code"] for blocker in report["blockers"]},
        )
        self.assertNotIn(sentinel, serialized)
        self.assertNotIn(str(donor_parent), serialized)
        self.assertNotIn(str(replacement_parent), serialized)
        self.assertFalse(report["secret_exposed"])

    def test_resolution_plan_rejects_manifest_parent_directory_swap_after_parent_check(self) -> None:
        self._write_legal_fixture()
        manifest_parent = self.fixture_root / "manifest-live"
        manifest_parent.mkdir()
        manifest_path = manifest_parent / "resolution-manifest.json"
        manifest_payload = json.dumps(
            {"schema_version": RESOLUTION_MANIFEST_SCHEMA_VERSION, "decisions": []}
        )
        manifest_path.write_text(manifest_payload, encoding="utf-8")
        replacement_parent = self.fixture_root / "manifest-replacement"
        replacement_parent.mkdir()
        (replacement_parent / manifest_path.name).write_text(manifest_payload, encoding="utf-8")
        parked_parent = self.fixture_root / "manifest-parked"
        real_parent_check = guard_module._source_parent_link_blocker
        swapped = False

        def swap_after_parent_check(path: Path, source: str) -> dict[str, object] | None:
            nonlocal swapped
            blocker = real_parent_check(path, source)
            if source == guard_module.RESOLUTION_MANIFEST_SOURCE and blocker is None and not swapped:
                swapped = True
                manifest_parent.rename(parked_parent)
                replacement_parent.rename(manifest_parent)
            return blocker

        with patch.object(
            guard_module,
            "_source_parent_link_blocker",
            swap_after_parent_check,
        ):
            report = plan_runtime_env_resolution(
                compose_path=self.compose_path,
                managed_env_path=self.managed_path,
                secret_env_path=self.secret_path,
                postgres_env_path=self.postgres_path,
                decision_manifest_path=manifest_path,
            )

        serialized = json.dumps(report, ensure_ascii=False)
        self.assertTrue(swapped)
        self.assertFalse(report["ok"])
        self.assertIn(
            "source_parent_changed_during_snapshot",
            {blocker["code"] for blocker in report["blockers"]},
        )
        self.assertNotIn(str(manifest_parent), serialized)
        self.assertNotIn(str(replacement_parent), serialized)
        self.assertFalse(report["secret_exposed"])

    def test_resolution_plan_rechecks_donor_and_manifest_parent_reparse_after_parent_check(self) -> None:
        self._write_legal_fixture()
        key = "JIEJING_BACKUP_RESTORE_DRILL_RUNBOOK_PUBLISHED"
        sentinel = "PARENT_REPARSE_SWAP_MUST_NOT_LEAK"
        billing_line = '      JIEJING_BILLING_PROVIDER: "stripe_test_mock"\n'
        donor_payload = self.compose_path.read_text(encoding="utf-8").replace(
            billing_line,
            billing_line + f'      {key}: "{sentinel}"\n',
            2,
        )
        for relative_path, runtime_path in (
            ("./runtime-env/tencent-managed.env", self.managed_path),
            ("./runtime-env/jiejing-saas.staging-oauth.env", self.secret_path),
            ("./runtime-env/postgres-localqueue.env", self.postgres_path),
        ):
            donor_payload = donor_payload.replace(relative_path, runtime_path.as_posix())
        donor_parent = self.fixture_root / "donor-reparse-live"
        donor_parent.mkdir()
        donor_compose = donor_parent / "docker-compose.yml"
        donor_compose.write_text(donor_payload, encoding="utf-8")
        manifest_parent = self.fixture_root / "manifest-reparse-live"
        manifest_parent.mkdir()
        manifest_path = manifest_parent / "resolution-manifest.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "schema_version": RESOLUTION_MANIFEST_SCHEMA_VERSION,
                    "decisions": [
                        {"key": key, "authoritative_role": "managed", "donor_role": "compose"}
                    ],
                }
            ),
            encoding="utf-8",
        )
        real_parent_check = guard_module._source_parent_link_blocker
        real_link_check = guard_module._path_is_link_or_reparse
        active_reparse_parents: set[Path] = set()

        def activate_reparse_after_parent_check(
            path: Path,
            source: str,
        ) -> dict[str, object] | None:
            blocker = real_parent_check(path, source)
            if blocker is None and source == guard_module.DONOR_COMPOSE_SOURCE:
                active_reparse_parents.add(donor_parent)
            if blocker is None and source == guard_module.RESOLUTION_MANIFEST_SOURCE:
                active_reparse_parents.add(manifest_parent)
            return blocker

        def simulated_reparse(path: Path) -> bool:
            return path in active_reparse_parents or real_link_check(path)

        with (
            patch.object(
                guard_module,
                "_source_parent_link_blocker",
                activate_reparse_after_parent_check,
            ),
            patch.object(guard_module, "_path_is_link_or_reparse", simulated_reparse),
        ):
            report = plan_runtime_env_resolution(
                compose_path=self.compose_path,
                managed_env_path=self.managed_path,
                secret_env_path=self.secret_path,
                postgres_env_path=self.postgres_path,
                decision_manifest_path=manifest_path,
                donor_compose_path=donor_compose,
            )

        serialized = json.dumps(report, ensure_ascii=False)
        parent_link_blockers = [
            blocker for blocker in report["blockers"] if blocker["code"] == "source_parent_link"
        ]
        self.assertEqual(
            active_reparse_parents,
            {donor_parent, manifest_parent},
        )
        self.assertFalse(report["ok"])
        self.assertGreaterEqual(len(parent_link_blockers), 2)
        self.assertTrue(
            any(blocker.get("source_role") == "compose" for blocker in parent_link_blockers)
        )
        self.assertNotIn(sentinel, serialized)
        self.assertNotIn(str(donor_parent), serialized)
        self.assertNotIn(str(manifest_parent), serialized)
        self.assertFalse(report["secret_exposed"])

    def test_resolution_plan_allows_unrelated_sibling_churn_in_donor_and_manifest_parents(self) -> None:
        self._write_legal_fixture()
        key = "JIEJING_BACKUP_RESTORE_DRILL_RUNBOOK_PUBLISHED"
        sentinel = "SIBLING_CHURN_DONOR_VALUE_MUST_NOT_LEAK"
        billing_line = '      JIEJING_BILLING_PROVIDER: "stripe_test_mock"\n'
        donor_payload = self.compose_path.read_text(encoding="utf-8").replace(
            billing_line,
            billing_line + f'      {key}: "{sentinel}"\n',
            2,
        )
        for relative_path, runtime_path in (
            ("./runtime-env/tencent-managed.env", self.managed_path),
            ("./runtime-env/jiejing-saas.staging-oauth.env", self.secret_path),
            ("./runtime-env/postgres-localqueue.env", self.postgres_path),
        ):
            donor_payload = donor_payload.replace(relative_path, runtime_path.as_posix())
        donor_parent = self.fixture_root / "donor-sibling-live"
        donor_parent.mkdir()
        donor_compose = donor_parent / "docker-compose.yml"
        donor_compose.write_text(donor_payload, encoding="utf-8")
        manifest_parent = self.fixture_root / "manifest-sibling-live"
        manifest_parent.mkdir()
        manifest_path = manifest_parent / "resolution-manifest.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "schema_version": RESOLUTION_MANIFEST_SCHEMA_VERSION,
                    "decisions": [
                        {"key": key, "authoritative_role": "managed", "donor_role": "compose"}
                    ],
                }
            ),
            encoding="utf-8",
        )
        real_parent_check = guard_module._source_parent_link_blocker
        churned_sources: set[str] = set()
        source_parents = {
            guard_module.DONOR_COMPOSE_SOURCE: donor_parent,
            guard_module.RESOLUTION_MANIFEST_SOURCE: manifest_parent,
        }

        def churn_sibling_after_parent_check(
            path: Path,
            source: str,
        ) -> dict[str, object] | None:
            blocker = real_parent_check(path, source)
            parent = source_parents.get(source)
            if blocker is None and parent is not None and source not in churned_sources:
                churned_sources.add(source)
                sibling = parent / "unrelated-sibling.tmp"
                sibling.write_text("unrelated", encoding="utf-8")
                sibling.unlink()
                parent_stat = guard_module.os.stat(parent, follow_symlinks=False)
                guard_module.os.utime(
                    parent,
                    ns=(
                        int(parent_stat.st_atime_ns),
                        int(parent_stat.st_mtime_ns) + 1_000_000_000,
                    ),
                )
            return blocker

        with patch.object(
            guard_module,
            "_source_parent_link_blocker",
            churn_sibling_after_parent_check,
        ):
            report = plan_runtime_env_resolution(
                compose_path=self.compose_path,
                managed_env_path=self.managed_path,
                secret_env_path=self.secret_path,
                postgres_env_path=self.postgres_path,
                decision_manifest_path=manifest_path,
                donor_compose_path=donor_compose,
            )

        serialized = json.dumps(report, ensure_ascii=False)
        self.assertEqual(
            churned_sources,
            {guard_module.DONOR_COMPOSE_SOURCE, guard_module.RESOLUTION_MANIFEST_SOURCE},
        )
        self.assertTrue(report["ok"], report["blockers"])
        self.assertTrue(
            any(
                action["key"] == key
                and action["action"] == "move_equal_donors_to_authoritative"
                for action in report["actions"]
            )
        )
        self.assertNotIn(sentinel, serialized)
        self.assertNotIn(str(donor_parent), serialized)
        self.assertNotIn(str(manifest_parent), serialized)
        self.assertFalse(report["secret_exposed"])

    def test_resolution_plan_rejects_donor_and_manifest_parent_aba_swap(self) -> None:
        self._write_legal_fixture()
        key = "JIEJING_BACKUP_RESTORE_DRILL_RUNBOOK_PUBLISHED"
        sentinel = "PARENT_ABA_DONOR_VALUE_MUST_NOT_LEAK"
        billing_line = '      JIEJING_BILLING_PROVIDER: "stripe_test_mock"\n'
        donor_payload = self.compose_path.read_text(encoding="utf-8").replace(
            billing_line,
            billing_line + f'      {key}: "{sentinel}"\n',
            2,
        )
        for relative_path, runtime_path in (
            ("./runtime-env/tencent-managed.env", self.managed_path),
            ("./runtime-env/jiejing-saas.staging-oauth.env", self.secret_path),
            ("./runtime-env/postgres-localqueue.env", self.postgres_path),
        ):
            donor_payload = donor_payload.replace(relative_path, runtime_path.as_posix())
        donor_parent = self.fixture_root / "donor-aba-live"
        donor_parent.mkdir()
        donor_compose = donor_parent / "docker-compose.yml"
        donor_compose.write_text(donor_payload, encoding="utf-8")
        donor_attack_parent = self.fixture_root / "donor-aba-attack"
        donor_attack_parent.mkdir()
        (donor_attack_parent / donor_compose.name).write_text(donor_payload, encoding="utf-8")
        manifest_parent = self.fixture_root / "manifest-aba-live"
        manifest_parent.mkdir()
        manifest_path = manifest_parent / "resolution-manifest.json"
        manifest_payload = json.dumps(
            {
                "schema_version": RESOLUTION_MANIFEST_SCHEMA_VERSION,
                "decisions": [
                    {"key": key, "authoritative_role": "managed", "donor_role": "compose"}
                ],
            }
        )
        manifest_path.write_text(manifest_payload, encoding="utf-8")
        manifest_attack_parent = self.fixture_root / "manifest-aba-attack"
        manifest_attack_parent.mkdir()
        (manifest_attack_parent / manifest_path.name).write_text(manifest_payload, encoding="utf-8")
        source_states = {
            guard_module.DONOR_COMPOSE_SOURCE: {
                "live": donor_parent,
                "attack": donor_attack_parent,
                "original_parked": self.fixture_root / "donor-aba-original-parked",
                "attack_parked": self.fixture_root / "donor-aba-attack-parked",
            },
            guard_module.RESOLUTION_MANIFEST_SOURCE: {
                "live": manifest_parent,
                "attack": manifest_attack_parent,
                "original_parked": self.fixture_root / "manifest-aba-original-parked",
                "attack_parked": self.fixture_root / "manifest-aba-attack-parked",
            },
        }
        real_parent_check = guard_module._source_parent_link_blocker
        real_parent_capture = guard_module._capture_source_parent_chain
        parent_capture_counts: dict[str, int] = {}
        attacked_sources: set[str] = set()
        restored_sources: set[str] = set()

        def swap_to_attack_after_parent_check(
            path: Path,
            source: str,
        ) -> dict[str, object] | None:
            blocker = real_parent_check(path, source)
            state = source_states.get(source)
            if blocker is None and state is not None and source not in attacked_sources:
                attacked_sources.add(source)
                state["live"].rename(state["original_parked"])
                state["attack"].rename(state["live"])
            return blocker

        def restore_before_parent_recapture(
            path: Path,
            source: str,
        ) -> tuple[
            tuple[guard_module.ParentDirectorySnapshot, ...],
            dict[str, object] | None,
        ]:
            parent_capture_counts[source] = parent_capture_counts.get(source, 0) + 1
            state = source_states.get(source)
            if (
                state is not None
                and parent_capture_counts[source] == 2
                and source in attacked_sources
                and source not in restored_sources
            ):
                restored_sources.add(source)
                state["live"].rename(state["attack_parked"])
                state["original_parked"].rename(state["live"])
            return real_parent_capture(path, source)

        with (
            patch.object(
                guard_module,
                "_source_parent_link_blocker",
                swap_to_attack_after_parent_check,
            ),
            patch.object(
                guard_module,
                "_capture_source_parent_chain",
                restore_before_parent_recapture,
            ),
        ):
            report = plan_runtime_env_resolution(
                compose_path=self.compose_path,
                managed_env_path=self.managed_path,
                secret_env_path=self.secret_path,
                postgres_env_path=self.postgres_path,
                decision_manifest_path=manifest_path,
                donor_compose_path=donor_compose,
            )

        serialized = json.dumps(report, ensure_ascii=False)
        self.assertEqual(
            attacked_sources,
            {guard_module.DONOR_COMPOSE_SOURCE, guard_module.RESOLUTION_MANIFEST_SOURCE},
        )
        self.assertEqual(restored_sources, attacked_sources)
        self.assertFalse(report["ok"])
        changed_blockers = [
            blocker
            for blocker in report["blockers"]
            if blocker["code"] == "source_changed_during_snapshot"
        ]
        self.assertGreaterEqual(len(changed_blockers), 2)
        self.assertTrue(
            any(blocker.get("source_role") == "compose" for blocker in changed_blockers)
        )
        self.assertNotIn(sentinel, serialized)
        for state in source_states.values():
            for path in state.values():
                self.assertNotIn(str(path), serialized)
        self.assertNotIn("digest", serialized.casefold())
        self.assertFalse(report["secret_exposed"])

    def test_resolution_plan_rejects_hardlinked_inputs_without_path_leakage(self) -> None:
        self._write_legal_fixture()
        hardlink_donor = self.fixture_root / "donor-compose-hardlink.yml"
        try:
            hardlink_donor.hardlink_to(self.compose_path)
        except (OSError, NotImplementedError) as error:
            self.skipTest(f"hardlinks unavailable: {type(error).__name__}")
        manifest_path = self._write_resolution_manifest([])

        report = plan_runtime_env_resolution(
            compose_path=self.compose_path,
            managed_env_path=self.managed_path,
            secret_env_path=self.secret_path,
            postgres_env_path=self.postgres_path,
            decision_manifest_path=manifest_path,
            donor_compose_path=hardlink_donor,
        )

        serialized = json.dumps(report, ensure_ascii=False)
        self.assertFalse(report["ok"])
        self.assertIn(
            "resolution_source_path_alias",
            {blocker["code"] for blocker in report["blockers"]},
        )
        self.assertNotIn(str(self.compose_path), serialized)
        self.assertNotIn(str(hardlink_donor), serialized)
        self.assertFalse(report["secret_exposed"])

    def test_resolution_plan_rejects_manifest_mid_snapshot_change(self) -> None:
        self._write_legal_fixture()
        manifest_path = self._write_resolution_manifest([])
        original = manifest_path.read_bytes()
        mutated = original.replace(b"v1", b"x1", 1)
        self.assertEqual(len(original), len(mutated))
        replacement_path = manifest_path.with_suffix(".replacement")
        replacement_path.write_bytes(mutated)
        real_stat = guard_module.os.stat
        mutated_once = False
        manifest_lstat_count = 0

        def mutate_before_post_read_stat(
            path: object,
            *args: object,
            **kwargs: object,
        ) -> object:
            nonlocal manifest_lstat_count, mutated_once
            if (
                Path(path) == manifest_path
                and kwargs.get("follow_symlinks") is False
            ):
                manifest_lstat_count += 1
                if manifest_lstat_count == 3:
                    mutated_once = True
                    guard_module.os.replace(replacement_path, manifest_path)
            return real_stat(path, *args, **kwargs)

        with patch.object(guard_module.os, "stat", mutate_before_post_read_stat):
            report = plan_runtime_env_resolution(
                compose_path=self.compose_path,
                managed_env_path=self.managed_path,
                secret_env_path=self.secret_path,
                postgres_env_path=self.postgres_path,
                decision_manifest_path=manifest_path,
            )

        self.assertTrue(mutated_once)
        self.assertFalse(report["ok"])
        self.assertIn(
            "source_changed_during_snapshot",
            {blocker["code"] for blocker in report["blockers"]},
        )
        self.assertNotIn(str(manifest_path), json.dumps(report))

    def test_resolution_plan_rejects_manifest_swap_between_precheck_and_open(self) -> None:
        self._write_legal_fixture()
        manifest_path = self._write_resolution_manifest([])
        original = manifest_path.read_bytes()
        replacement = original.replace(b"v1", b"x1", 1)
        self.assertEqual(len(original), len(replacement))
        replacement_path = manifest_path.with_suffix(".replacement")
        replacement_path.write_bytes(replacement)
        real_open = guard_module.os.open
        swapped = False

        def swap_before_open(
            path: object,
            flags: int,
            *args: object,
            **kwargs: object,
        ) -> int:
            nonlocal swapped
            if Path(path) == manifest_path and not swapped:
                swapped = True
                guard_module.os.replace(replacement_path, manifest_path)
            return real_open(path, flags, *args, **kwargs)

        with patch.object(guard_module.os, "open", swap_before_open):
            report = plan_runtime_env_resolution(
                compose_path=self.compose_path,
                managed_env_path=self.managed_path,
                secret_env_path=self.secret_path,
                postgres_env_path=self.postgres_path,
                decision_manifest_path=manifest_path,
            )

        self.assertTrue(swapped)
        self.assertFalse(report["ok"])
        self.assertIn(
            "source_changed_during_snapshot",
            {blocker["code"] for blocker in report["blockers"]},
        )
        self.assertNotIn(str(manifest_path), json.dumps(report))

    def test_resolution_plan_uses_bound_manifest_bytes_after_path_swap(self) -> None:
        self._write_legal_fixture()
        manifest_path = self._write_resolution_manifest([])
        replacement = json.dumps(
            {
                "schema_version": RESOLUTION_MANIFEST_SCHEMA_VERSION,
                "decisions": [
                    {
                        "key": "SWAPPED_MANIFEST_SENTINEL",
                        "authoritative_role": "managed",
                    }
                ],
            }
        ).encode("utf-8")
        real_capture = guard_module._capture_source_snapshot
        swapped = False

        def swap_after_capture(
            path: Path,
            source: str,
        ) -> tuple[guard_module.SourceSnapshot | None, dict[str, object] | None]:
            nonlocal swapped
            result = real_capture(path, source)
            if path == manifest_path and not swapped and result[0] is not None:
                swapped = True
                replacement_path = manifest_path.with_suffix(".replacement")
                replacement_path.write_bytes(replacement)
                guard_module.os.replace(replacement_path, manifest_path)
            return result

        with patch.object(guard_module, "_capture_source_snapshot", swap_after_capture):
            report = plan_runtime_env_resolution(
                compose_path=self.compose_path,
                managed_env_path=self.managed_path,
                secret_env_path=self.secret_path,
                postgres_env_path=self.postgres_path,
                decision_manifest_path=manifest_path,
            )

        self.assertTrue(swapped)
        self.assertEqual(manifest_path.read_bytes(), replacement)
        self.assertTrue(report["ok"], report["blockers"])
        self.assertNotIn("SWAPPED_MANIFEST_SENTINEL", json.dumps(report))
        self.assertFalse(report["secret_exposed"])

    def test_checked_in_resolution_manifest_closes_full_synthetic_live_topology_without_mutation(self) -> None:
        self._write_legal_fixture()
        manifest_path = ROOT / "deploy" / "jiejing-staging-runtime-env-resolution-manifest.example.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        decisions = manifest["decisions"]
        compose_donor_keys = {
            decision["key"]
            for decision in decisions
            if decision.get("donor_role") == "compose"
        }
        retire_compose_donor_keys = {
            decision["key"]
            for decision in decisions
            if decision.get("resolution_action")
            == "retire_equal_compose_donor_keep_authoritative"
        }
        move_compose_donor_keys = compose_donor_keys - retire_compose_donor_keys
        private_donor_keys = {
            decision["key"]: decision["donor_role"]
            for decision in decisions
            if decision.get("donor_role") not in {None, "compose"}
        }
        keep_owner_decisions = [decision for decision in decisions if "donor_role" not in decision]

        candidate_text = self.compose_path.read_text(encoding="utf-8").replace(
            '      JIEJING_BILLING_PROVIDER: "stripe_test_mock"\n',
            '      JIEJING_BILLING_PROVIDER: "stripe_test_mock"\n'
            '      JIEJING_CORS_ORIGIN: "https://candidate.example"\n',
        )
        donor_insert = "".join(
            f'      {key}: "true"\n'
            if key.startswith("JIEJING_MEDIA_")
            else f'      {key}: "LIVE_TOPOLOGY_COMPOSE_DONOR"\n'
            for key in sorted(compose_donor_keys)
        )
        donor_text = candidate_text.replace(
            '      JIEJING_BILLING_PROVIDER: "stripe_test_mock"\n',
            '      JIEJING_BILLING_PROVIDER: "stripe_test_mock"\n' + donor_insert,
        )
        self.compose_path.write_text(donor_text, encoding="utf-8")
        candidate_dir = self.fixture_root / "candidate" / "deploy"
        candidate_dir.mkdir(parents=True)
        candidate_compose = candidate_dir / "docker-compose.yml"
        candidate_compose.write_text(candidate_text, encoding="utf-8")

        target_by_role: dict[str, list[str]] = {
            "managed": [],
            "secret": ["JIEJING_EBAY_CLIENT_SECRET=LIVE_TOPOLOGY_SECRET_BASE"],
            "postgres": ["JIEJING_DATABASE_URL=LIVE_TOPOLOGY_POSTGRES_BASE"],
        }
        for decision in keep_owner_decisions:
            key = decision["key"]
            owner_role = decision["authoritative_role"]
            if owner_role == "compose":
                legacy_value = (
                    "true"
                    if key in {
                        "JIEJING_ENABLE_REAL_PLATFORM_WRITES",
                        "JIEJING_EBAY_WRITE_LIVE",
                    }
                    else "LIVE_TOPOLOGY_LEGACY_PRIVATE"
                )
                if key == "JIEJING_BILLING_PROVIDER":
                    legacy_value = "LIVE_TOPOLOGY_LEGACY_PROVIDER"
                target_by_role["secret"].append(f"{key}={legacy_value}")
                continue
            target_by_role[owner_role].append(f"{key}=LIVE_TOPOLOGY_OWNER_{owner_role}")
            wrong_role = "secret" if owner_role != "secret" else "managed"
            target_by_role[wrong_role].append(f"{key}=LIVE_TOPOLOGY_WRONG_{wrong_role}")
        for key, donor_role in private_donor_keys.items():
            target_by_role[donor_role].append(f"{key}=LIVE_TOPOLOGY_PRIVATE_DONOR")
        for key in sorted(retire_compose_donor_keys):
            target_by_role["secret"].append(f"{key}=true")

        self.managed_path.write_text("\n".join(target_by_role["managed"]) + "\n", encoding="utf-8")
        self.secret_path.write_text("\n".join(target_by_role["secret"]) + "\n", encoding="utf-8")
        self.postgres_path.write_text("\n".join(target_by_role["postgres"]) + "\n", encoding="utf-8")
        before = {
            path: path.read_bytes()
            for path in (
                candidate_compose,
                self.compose_path,
                self.managed_path,
                self.secret_path,
                self.postgres_path,
                manifest_path,
            )
        }

        completed = self._run_resolution_plan(
            manifest_path,
            augment_legacy_contract=False,
            compose_path=candidate_compose,
            compose_runtime_path=self.compose_path,
            donor_compose_path=self.compose_path,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)
        self.assertNotIn("LIVE_TOPOLOGY_", completed.stdout + completed.stderr)
        report = json.loads(completed.stdout)
        self.assertTrue(report["ok"], report["blockers"])
        self.assertEqual(report["summary"]["decision_count"], 24)
        self.assertEqual(report["summary"]["action_count"], 24)
        self.assertEqual(report["blockers"], [])
        self.assertEqual(
            {
                action["key"]
                for action in report["actions"]
                if action["action"] == "move_equal_donors_to_authoritative"
            },
            move_compose_donor_keys,
        )
        self.assertTrue(
            all(
                action["source_role"] == "compose"
                and action["count"] == 2
                and action["comparison"] == "equal"
                for action in report["actions"]
                if action["action"] == "move_equal_donors_to_authoritative"
            )
        )
        self.assertEqual(
            {
                action["key"]
                for action in report["actions"]
                if action["action"] == "retire_equal_compose_donor_keep_authoritative"
            },
            retire_compose_donor_keys,
        )
        self.assertTrue(
            all(
                action["source_role"] == "compose"
                and action["target_role"] == "secret"
                and action["count"] == 2
                and action["comparison"] == "equal"
                for action in report["actions"]
                if action["action"] == "retire_equal_compose_donor_keep_authoritative"
            )
        )
        self.assertEqual(before, {path: path.read_bytes() for path in before})
        serialized = json.dumps(report, ensure_ascii=False)
        self.assertNotIn(str(candidate_compose), serialized)
        self.assertNotIn(str(self.compose_path), serialized)
        self.assertEqual(
            sorted(key for key in _all_json_keys(report) if _looks_like_value_field(key)),
            [],
        )

    def _write_resolution_topology_fixture(self) -> tuple[Path, dict[Path, bytes], tuple[str, ...]]:
        self._write_legal_fixture()
        compose_text = self.compose_path.read_text(encoding="utf-8").replace(
            '      JIEJING_BILLING_PROVIDER: "stripe_test_mock"\n',
            '      JIEJING_BILLING_PROVIDER: "stripe_test_mock"\n'
            '      JIEJING_CORS_ORIGIN: "https://owner.example"\n',
        )
        self.compose_path.write_text(compose_text, encoding="utf-8")
        sentinels = (
            "OWNER_BROWSER_MUST_NOT_LEAK",
            "DONOR_BROWSER_MUST_NOT_LEAK",
            "WRONG_CORS_MUST_NOT_LEAK",
            "MOVE_POSTGRES_MUST_NOT_LEAK",
            "EQUAL_EVIDENCE_MUST_NOT_LEAK",
        )
        self.managed_path.write_text(
            "JIEJING_BACKUP_POLICY_CONFIGURED=true\n"
            f"JIEJING_BROWSER_SMOKE_PASSED={sentinels[0]}\n"
            f"JIEJING_COS_BACKUP_LAST_SUCCESS_AT={sentinels[4]}\n",
            encoding="utf-8",
        )
        self.secret_path.write_text(
            "JIEJING_EBAY_CLIENT_SECRET=LEGAL_SECRET_SENTINEL\n"
            f"JIEJING_BROWSER_SMOKE_PASSED={sentinels[1]}\n"
            f"JIEJING_CORS_ORIGIN={sentinels[2]}\n"
            f"JIEJING_POSTGRES_LIVE_PROBE_PASSED={sentinels[3]}\n"
            f"JIEJING_COS_BACKUP_LAST_SUCCESS_AT={sentinels[4]}\n",
            encoding="utf-8",
        )
        manifest_path = self._write_resolution_manifest(
            [
                {"key": "JIEJING_BROWSER_SMOKE_PASSED", "authoritative_role": "managed"},
                {"key": "JIEJING_CORS_ORIGIN", "authoritative_role": "compose"},
                {
                    "key": "JIEJING_POSTGRES_LIVE_PROBE_PASSED",
                    "authoritative_role": "postgres",
                    "donor_role": "secret",
                },
            ]
        )
        before = {
            path: path.read_bytes()
            for path in (self.compose_path, self.managed_path, self.secret_path, self.postgres_path)
        }
        return manifest_path, before, sentinels

    def test_resolution_plan_is_value_free_non_mutating_and_covers_observed_topologies(self) -> None:
        manifest_path, before, sentinels = self._write_resolution_topology_fixture()

        completed = self._run_resolution_plan(manifest_path)

        self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)
        self.assertTrue(all(sentinel not in completed.stdout + completed.stderr for sentinel in sentinels))
        report = json.loads(completed.stdout)
        self.assertTrue(report["ok"], report["blockers"])
        self.assertEqual(report["operation"], "resolution-plan")
        self.assertEqual(report["mode"], "dry_run")
        self.assertFalse(report["applied"])
        self.assertFalse(report["secret_exposed"])
        self.assertEqual(
            {(action["key"], action["action"], action["source_role"], action["target_role"]) for action in report["actions"]},
            {
                ("JIEJING_BROWSER_SMOKE_PASSED", "keep_authoritative_remove_wrong_source", "secret", "managed"),
                ("JIEJING_CORS_ORIGIN", "keep_authoritative_remove_wrong_source", "secret", "compose"),
                ("JIEJING_COS_BACKUP_LAST_SUCCESS_AT", "remove_equal_duplicate", "secret", "managed"),
                ("JIEJING_POSTGRES_LIVE_PROBE_PASSED", "move_unique_to_authoritative", "secret", "postgres"),
            },
        )
        for action in report["actions"]:
            self.assertEqual(
                set(action),
                {"action", "key", "source_role", "target_role", "count", "comparison"},
            )
            self.assertIn(action["comparison"], {"equal", "conflict"})
        self.assertEqual(
            before,
            {
                path: path.read_bytes()
                for path in (self.compose_path, self.managed_path, self.secret_path, self.postgres_path)
            },
        )
        self.assertEqual(
            sorted(key for key in _all_json_keys(report) if _looks_like_value_field(key)),
            [],
        )

    def test_resolution_apply_executes_all_private_action_kinds_without_compose_mutation(self) -> None:
        manifest_path, before, sentinels = self._write_resolution_topology_fixture()
        manifest_before = manifest_path.read_bytes()

        completed = self._run_resolution_apply(
            manifest_path,
            confirm=RESOLUTION_APPLY_CONFIRMATION,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)
        report = json.loads(completed.stdout)
        self.assertTrue(report["ok"], report["blockers"])
        self.assertTrue(report["applied"])
        self.assertEqual(report["summary"]["action_count"], 4)
        self.assertEqual(self.compose_path.read_bytes(), before[self.compose_path])
        self.assertEqual(self.managed_path.read_bytes(), before[self.managed_path])
        self.assertEqual(
            self.secret_path.read_bytes(),
            before[self.secret_path].splitlines(keepends=True)[0],
        )
        self.assertEqual(
            self.postgres_path.read_bytes(),
            before[self.postgres_path]
            + f"JIEJING_POSTGRES_LIVE_PROBE_PASSED={sentinels[3]}\n".encode(),
        )
        self.assertEqual(manifest_path.read_bytes(), manifest_before)
        validation = check_runtime_env_ownership(
            compose_path=self.compose_path,
            managed_env_path=self.managed_path,
            secret_env_path=self.secret_path,
            postgres_env_path=self.postgres_path,
        )
        self.assertTrue(validation["ok"], validation["blockers"])
        self.assertTrue(all(sentinel not in completed.stdout for sentinel in sentinels))
        for key in (
            "JIEJING_BROWSER_SMOKE_PASSED",
            "JIEJING_CORS_ORIGIN",
            "JIEJING_COS_BACKUP_LAST_SUCCESS_AT",
            "JIEJING_POSTGRES_LIVE_PROBE_PASSED",
        ):
            self.assertNotIn(key, completed.stdout)

    def test_resolution_plan_rejects_stale_decision(self) -> None:
        self._write_legal_fixture()
        manifest_path = self._write_resolution_manifest(
            [{"key": "JIEJING_DEFAULT_PLAN_KEY", "authoritative_role": "managed"}]
        )

        report = plan_runtime_env_resolution(
            compose_path=self.compose_path,
            managed_env_path=self.managed_path,
            secret_env_path=self.secret_path,
            postgres_env_path=self.postgres_path,
            decision_manifest_path=manifest_path,
        )

        self.assertFalse(report["ok"])
        self.assertIn("resolution_decision_stale", {item["code"] for item in report["blockers"]})

    def test_resolution_plan_rejects_invalid_and_unknown_decisions(self) -> None:
        self._write_legal_fixture()
        invalid_manifest = self._write_resolution_manifest(
            [{"key": "JIEJING_DEFAULT_PLAN_KEY", "authoritative_role": "runtime"}]
        )
        invalid_report = plan_runtime_env_resolution(
            compose_path=self.compose_path,
            managed_env_path=self.managed_path,
            secret_env_path=self.secret_path,
            postgres_env_path=self.postgres_path,
            decision_manifest_path=invalid_manifest,
        )
        self.assertFalse(invalid_report["ok"])
        self.assertIn(
            "resolution_decision_authoritative_role_invalid",
            {item["code"] for item in invalid_report["blockers"]},
        )

        self.secret_path.write_text(
            self.secret_path.read_text(encoding="utf-8")
            + "UNREGISTERED_LEGACY_FLAG=UNKNOWN_DECISION_SENTINEL\n",
            encoding="utf-8",
        )
        unknown_manifest = self._write_resolution_manifest(
            [{"key": "UNREGISTERED_LEGACY_FLAG", "authoritative_role": "managed"}]
        )
        unknown_report = plan_runtime_env_resolution(
            compose_path=self.compose_path,
            managed_env_path=self.managed_path,
            secret_env_path=self.secret_path,
            postgres_env_path=self.postgres_path,
            decision_manifest_path=unknown_manifest,
        )
        self.assertFalse(unknown_report["ok"])
        self.assertIn(
            "resolution_decision_unknown_key",
            {item["code"] for item in unknown_report["blockers"]},
        )
        self.assertNotIn("UNKNOWN_DECISION_SENTINEL", json.dumps(unknown_report))

    def test_resolution_plan_rejects_invalid_roles_and_actions_without_traceback_or_path(self) -> None:
        self._write_legal_fixture()
        cases = (
            (
                {"key": "JIEJING_DEFAULT_PLAN_KEY", "authoritative_role": ["managed"]},
                "resolution_decision_authoritative_role_invalid",
            ),
            (
                {
                    "key": "JIEJING_DEFAULT_PLAN_KEY",
                    "authoritative_role": "managed",
                    "donor_role": {"role": "secret"},
                },
                "resolution_decision_donor_role_invalid",
            ),
            (
                {
                    "key": "JIEJING_MEDIA_LIVE_PROVIDER_ENABLED",
                    "authoritative_role": "secret",
                    "donor_role": "compose",
                    "resolution_action": ["retire"],
                },
                "resolution_decision_action_invalid",
            ),
            (
                {
                    "key": "JIEJING_MEDIA_LIVE_PROVIDER_ENABLED",
                    "authoritative_role": "secret",
                    "donor_role": "compose",
                    "resolution_action": None,
                },
                "resolution_decision_action_invalid",
            ),
            (
                {
                    "key": "JIEJING_MEDIA_LIVE_PROVIDER_ENABLED",
                    "authoritative_role": "secret",
                    "donor_role": "compose",
                    "resolution_action": "move_equal_donors_to_authoritative",
                },
                "resolution_decision_action_invalid",
            ),
            (
                {
                    "key": "JIEJING_BACKUP_RESTORE_DRILL_RUNBOOK_PUBLISHED",
                    "authoritative_role": "managed",
                    "donor_role": "compose",
                    "resolution_action": "retire_equal_compose_donor_keep_authoritative",
                },
                "resolution_decision_action_roles_invalid",
            ),
            (
                {
                    "key": "JIEJING_EBAY_CLIENT_SECRET",
                    "authoritative_role": "secret",
                    "donor_role": "compose",
                    "resolution_action": "retire_equal_compose_donor_keep_authoritative",
                },
                "resolution_decision_action_key_invalid",
            ),
        )
        for decision, expected_code in cases:
            with self.subTest(expected_code=expected_code):
                manifest_path = self._write_resolution_manifest([decision])

                completed = self._run_resolution_plan(manifest_path)

                self.assertNotEqual(completed.returncode, 0)
                self.assertEqual(completed.stderr, "")
                self.assertNotIn("Traceback", completed.stdout)
                self.assertNotIn(str(manifest_path), completed.stdout)
                report = json.loads(completed.stdout)
                self.assertFalse(report["ok"])
                self.assertIn(expected_code, {item["code"] for item in report["blockers"]})
                self.assertFalse(report["secret_exposed"])

    def test_checked_in_staging_resolution_manifest_is_value_free_and_action_explicit(self) -> None:
        manifest_path = ROOT / "deploy" / "jiejing-staging-runtime-env-resolution-manifest.example.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        self.assertEqual(manifest["schema_version"], RESOLUTION_MANIFEST_SCHEMA_VERSION)
        self.assertEqual(len(manifest["decisions"]), 24)
        self.assertEqual(
            {decision["key"] for decision in manifest["decisions"] if "donor_role" in decision},
            {
                "JIEJING_BACKUP_RESTORE_DRILL_RUNBOOK_PUBLISHED",
                "JIEJING_DATABASE_ENDPOINT_INCIDENT_RUNBOOK_PUBLISHED",
                "JIEJING_MEDIA_LIVE_PROVIDER_ENABLED",
                "JIEJING_MEDIA_LIVE_VIDEO_ENABLED",
                "JIEJING_POSTGRES_LIVE_PROBE_PASSED",
                "JIEJING_VAULT_ENABLED",
                "JIEJING_VAULT_LIVE_PROBE_PASSED",
            },
        )
        for decision in manifest["decisions"]:
            self.assertTrue(
                set(decision).issubset(
                    {"key", "authoritative_role", "donor_role", "resolution_action"}
                )
            )
        self.assertEqual(
            {
                decision["key"]: decision["resolution_action"]
                for decision in manifest["decisions"]
                if "resolution_action" in decision
            },
            {
                "JIEJING_MEDIA_LIVE_PROVIDER_ENABLED": (
                    "retire_equal_compose_donor_keep_authoritative"
                ),
                "JIEJING_MEDIA_LIVE_VIDEO_ENABLED": (
                    "retire_equal_compose_donor_keep_authoritative"
                ),
            },
        )
        self.assertEqual(
            sorted(key for key in _all_json_keys(manifest) if _looks_like_value_field(key)),
            [],
        )

    def test_resolution_plan_requires_donor_when_owner_is_missing(self) -> None:
        self._write_legal_fixture()
        self.secret_path.write_text(
            "JIEJING_EBAY_CLIENT_SECRET=LEGAL_SECRET_SENTINEL\n"
            "JIEJING_POSTGRES_LIVE_PROBE_PASSED=MISSING_OWNER_SENTINEL\n",
            encoding="utf-8",
        )
        manifest_path = self._write_resolution_manifest(
            [{"key": "JIEJING_POSTGRES_LIVE_PROBE_PASSED", "authoritative_role": "postgres"}]
        )

        completed = self._run_resolution_plan(manifest_path)

        self.assertNotEqual(completed.returncode, 0)
        self.assertNotIn("MISSING_OWNER_SENTINEL", completed.stdout + completed.stderr)
        report = json.loads(completed.stdout)
        self.assertIn(
            "resolution_missing_owner_requires_donor",
            {item["code"] for item in report["blockers"]},
        )

    def test_resolution_plan_rejects_ambiguous_donor(self) -> None:
        self._write_legal_fixture()
        self.secret_path.write_text(
            "JIEJING_EBAY_CLIENT_SECRET=LEGAL_SECRET_SENTINEL\n"
            "JIEJING_VAULT_ENABLED=AMBIGUOUS_DONOR_ONE\n"
            "JIEJING_VAULT_ENABLED=AMBIGUOUS_DONOR_TWO\n",
            encoding="utf-8",
        )
        manifest_path = self._write_resolution_manifest(
            [
                {
                    "key": "JIEJING_VAULT_ENABLED",
                    "authoritative_role": "managed",
                    "donor_role": "secret",
                }
            ]
        )

        completed = self._run_resolution_plan(manifest_path)

        self.assertNotEqual(completed.returncode, 0)
        self.assertNotIn("AMBIGUOUS_DONOR", completed.stdout + completed.stderr)
        report = json.loads(completed.stdout)
        self.assertIn("resolution_donor_not_unique", {item["code"] for item in report["blockers"]})

    def test_observed_exact_registry_keys_have_evidence_driven_owners(self) -> None:
        self._write_legal_fixture()
        self.managed_path.write_text(
            self.managed_path.read_text(encoding="utf-8")
            + "\n".join(
                f"{key}=registered"
                for key in (
                    "JIEJING_BROWSER_SMOKE_PASSED",
                    "JIEJING_DEFAULT_PLAN_KEY",
                    "JIEJING_DEPLOY_CHANNEL_READY",
                    "JIEJING_PRODUCTION_DEPLOYMENT_DRY_RUN_PASSED",
                    "JIEJING_PRODUCTION_POST_DEPLOY_HEALTH_SMOKE_PASSED",
                    "JIEJING_PRODUCTION_RELEASE_ARTIFACT_SHA256",
                    "JIEJING_PRODUCTION_ROLLBACK_POINT_ID",
                    "JIEJING_SECRET_SCAN_PASSED",
                    "JIEJING_VAULT_ENABLED",
                    "JIEJING_VAULT_LIVE_PROBE_PASSED",
                )
            )
            + "\n",
            encoding="utf-8",
        )
        self.postgres_path.write_text(
            self.postgres_path.read_text(encoding="utf-8")
            + "JIEJING_POSTGRES_LIVE_PROBE_PASSED=registered\n",
            encoding="utf-8",
        )
        self.compose_path.write_text(
            self.compose_path.read_text(encoding="utf-8").replace(
                '      JIEJING_BILLING_PROVIDER: "stripe_test_mock"\n',
                '      JIEJING_BILLING_PROVIDER: "stripe_test_mock"\n'
                '      JIEJING_BILLING_PLANS_PUBLISHED: "true"\n'
                '      JIEJING_CORS_ORIGIN: "https://registered.example"\n'
                '      JIEJING_QUOTA_ENFORCEMENT_ENABLED: "true"\n',
            ),
            encoding="utf-8",
        )

        report = check_runtime_env_ownership(
            compose_path=self.compose_path,
            managed_env_path=self.managed_path,
            secret_env_path=self.secret_path,
            postgres_env_path=self.postgres_path,
        )

        self.assertTrue(report["ok"], report["blockers"])
        owners = {
            declaration["key"]: declaration["owner"]
            for declaration in report["declarations"]
        }
        self.assertEqual(owners["JIEJING_BILLING_PLANS_PUBLISHED"], "compose")
        self.assertEqual(owners["JIEJING_CORS_ORIGIN"], "compose")
        self.assertEqual(owners["JIEJING_QUOTA_ENFORCEMENT_ENABLED"], "compose")
        self.assertEqual(owners["JIEJING_POSTGRES_LIVE_PROBE_PASSED"], "postgres-localqueue.env")
        for key in (
            "JIEJING_BROWSER_SMOKE_PASSED",
            "JIEJING_DEFAULT_PLAN_KEY",
            "JIEJING_DEPLOY_CHANNEL_READY",
            "JIEJING_PRODUCTION_DEPLOYMENT_DRY_RUN_PASSED",
            "JIEJING_PRODUCTION_POST_DEPLOY_HEALTH_SMOKE_PASSED",
            "JIEJING_PRODUCTION_RELEASE_ARTIFACT_SHA256",
            "JIEJING_PRODUCTION_ROLLBACK_POINT_ID",
            "JIEJING_SECRET_SCAN_PASSED",
            "JIEJING_VAULT_ENABLED",
            "JIEJING_VAULT_LIVE_PROBE_PASSED",
        ):
            self.assertEqual(owners[key], "tencent-managed.env")
        bare_aliases = {
            "BILLING_PLANS_PUBLISHED",
            "BROWSER_SMOKE_PASSED",
            "CORS_ORIGIN",
            "DEFAULT_PLAN_KEY",
            "DEPLOY_CHANNEL_READY",
            "POSTGRES_LIVE_PROBE_PASSED",
            "PRODUCTION_DEPLOYMENT_DRY_RUN_PASSED",
            "PRODUCTION_POST_DEPLOY_HEALTH_SMOKE_PASSED",
            "PRODUCTION_RELEASE_ARTIFACT_SHA256",
            "PRODUCTION_ROLLBACK_POINT_ID",
            "QUOTA_ENFORCEMENT_ENABLED",
            "SECRET_SCAN_PASSED",
            "VAULT_ENABLED",
            "VAULT_LIVE_PROBE_PASSED",
        }
        self.assertTrue(
            bare_aliases.isdisjoint(
                guard_module.MANAGED_EXACT_KEYS
                | guard_module.POSTGRES_EXACT_KEYS
                | set(guard_module.COMPOSE_STATIC_KEYS)
            )
        )

    def test_compose_exact_registry_accepts_runtime_topology_and_rejects_private_sources(self) -> None:
        self._write_legal_fixture()
        keys = ("JIEJING_ALLOW_HERMES_ADAPTERS", "JIEJING_SAAS_ENV")
        compose_text = self.compose_path.read_text(encoding="utf-8").replace(
            '      JIEJING_BILLING_PROVIDER: "stripe_test_mock"\n',
            '      JIEJING_BILLING_PROVIDER: "stripe_test_mock"\n'
            '      JIEJING_ALLOW_HERMES_ADAPTERS: "false"\n'
            '      JIEJING_SAAS_ENV: "staging"\n',
        )
        self.compose_path.write_text(compose_text, encoding="utf-8")

        candidate_report = check_runtime_env_ownership(
            compose_path=self.compose_path,
            managed_env_path=self.managed_path,
            secret_env_path=self.secret_path,
            postgres_env_path=self.postgres_path,
        )

        self.assertTrue(candidate_report["ok"], candidate_report["blockers"])
        for key in keys:
            declarations = [
                declaration
                for declaration in candidate_report["declarations"]
                if declaration["key"] == key
            ]
            self.assertEqual(
                {declaration["source"] for declaration in declarations},
                {"compose:jiejing-saas", "compose:jiejing-worker"},
            )
            self.assertTrue(
                all(declaration["owner"] == "compose" for declaration in declarations)
            )

        self.compose_path.write_text(
            compose_text.replace(
                '      JIEJING_ALLOW_HERMES_ADAPTERS: "false"\n'
                '      JIEJING_SAAS_ENV: "staging"\n',
                "",
            ),
            encoding="utf-8",
        )
        self.secret_path.write_text(
            self.secret_path.read_text(encoding="utf-8")
            + "JIEJING_ALLOW_HERMES_ADAPTERS=PRIVATE_SOURCE_SENTINEL\n"
            + "JIEJING_SAAS_ENV=PRIVATE_SOURCE_SENTINEL\n",
            encoding="utf-8",
        )

        private_report = check_runtime_env_ownership(
            compose_path=self.compose_path,
            managed_env_path=self.managed_path,
            secret_env_path=self.secret_path,
            postgres_env_path=self.postgres_path,
        )

        self.assertFalse(private_report["ok"])
        for key in keys:
            self.assertTrue(
                any(
                    blocker.get("code") == "wrong_source"
                    and blocker.get("key") == key
                    and blocker.get("owner") == "compose"
                    for blocker in private_report["blockers"]
                )
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
        managed_bytes = self.managed_path.read_bytes()
        newline = b"\r\n" if b"\r\n" in managed_bytes else b"\n"
        expected_candidate = b"JIEJING_BACKUP_POLICY_CONFIGURED=true" + newline
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

    def test_check_saas_only_profile_does_not_require_worker(self) -> None:
        self._write_legal_fixture()
        compose = self.compose_path.read_text(encoding="utf-8")
        self.compose_path.write_text(compose.split("  jiejing-worker:\n", 1)[0], encoding="utf-8")

        completed = self._run_check(required_runtime_services=("jiejing-saas",))

        self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)
        report = json.loads(completed.stdout)
        self.assertTrue(report["ok"])
        self.assertEqual(report["blockers"], [])

    def test_required_runtime_service_option_is_repeatable(self) -> None:
        self._write_legal_fixture()

        completed = self._run_check(
            required_runtime_services=("jiejing-saas", "jiejing-worker"),
        )

        self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)
        self.assertTrue(json.loads(completed.stdout)["ok"])

    def test_migrate_saas_only_profile_does_not_require_worker(self) -> None:
        self._write_legal_fixture()
        compose = self.compose_path.read_text(encoding="utf-8")
        self.compose_path.write_text(compose.split("  jiejing-worker:\n", 1)[0], encoding="utf-8")

        completed = self._run_migrate(required_runtime_services=("jiejing-saas",))

        self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)
        report = json.loads(completed.stdout)
        self.assertTrue(report["ok"])
        self.assertEqual(report["mode"], "dry_run")
        self.assertEqual(report["blockers"], [])

    def test_saas_only_profile_still_rejects_worker_structural_duplicates(self) -> None:
        self._write_legal_fixture()
        compose = self.compose_path.read_text(encoding="utf-8")
        self.compose_path.write_text(
            compose.split("  jiejing-worker:\n", 1)[0]
            + """  jiejing-worker:
    environment:
      WORKER_STATIC_ONE: "one"
    environment:
      WORKER_STATIC_TWO: "two"
""",
            encoding="utf-8",
        )

        completed = self._run_check(
            augment_legacy_contract=False,
            required_runtime_services=("jiejing-saas",),
        )

        self.assertNotEqual(completed.returncode, 0)
        report = json.loads(completed.stdout)
        self.assertTrue(
            any(
                blocker.get("code") == "duplicate_compose_environment_block"
                and blocker.get("service") == "jiejing-worker"
                for blocker in report["blockers"]
            )
        )
        self.assertFalse(
            any(
                blocker.get("code") in {
                    "missing_runtime_environment",
                    "missing_required_compose_env_file",
                    "missing_required_compose_clamp",
                    "missing_required_billing_provider_pin",
                }
                and blocker.get("service") == "jiejing-worker"
                for blocker in report["blockers"]
            )
        )

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

    def test_candidate_compose_can_be_checked_at_its_future_runtime_path(self) -> None:
        self._write_legal_fixture()
        candidate_dir = self.fixture_root / "candidate" / "deploy"
        candidate_dir.mkdir(parents=True)
        candidate_compose = candidate_dir / self.compose_path.name
        candidate_compose.write_text(self.compose_path.read_text(encoding="utf-8"), encoding="utf-8")

        report = check_runtime_env_ownership(
            compose_path=candidate_compose,
            compose_runtime_path=self.compose_path,
            managed_env_path=self.managed_path,
            secret_env_path=self.secret_path,
            postgres_env_path=self.postgres_path,
        )

        self.assertTrue(report["ok"], report["blockers"])
        self.assertFalse(report["secret_exposed"])

        completed = subprocess.run(
            [
                sys.executable,
                str(TOOL),
                "check",
                "--compose",
                str(candidate_compose),
                "--compose-runtime-path",
                str(self.compose_path),
                "--managed-env",
                str(self.managed_path),
                "--secret-env",
                str(self.secret_path),
                "--postgres-env",
                str(self.postgres_path),
                "--required-runtime-service",
                "jiejing-saas",
                "--required-runtime-service",
                "jiejing-worker",
                "--json",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)
        self.assertNotIn(str(candidate_compose), completed.stdout + completed.stderr)
        self.assertNotIn(str(self.compose_path), completed.stdout + completed.stderr)

    def test_candidate_templates_can_be_read_without_touching_runtime_env_paths(self) -> None:
        self._write_legal_fixture()
        candidate_dir = self.fixture_root / "candidate-public-inputs"
        candidate_dir.mkdir()
        candidate_managed = candidate_dir / "managed.example"
        candidate_secret = candidate_dir / "secret.example"
        candidate_postgres = candidate_dir / "postgres.example"
        candidate_managed.write_text(self.managed_path.read_text(encoding="utf-8"), encoding="utf-8")
        candidate_secret.write_text(self.secret_path.read_text(encoding="utf-8"), encoding="utf-8")
        candidate_postgres.write_text(self.postgres_path.read_text(encoding="utf-8"), encoding="utf-8")

        report = check_runtime_env_ownership(
            compose_path=self.compose_path,
            managed_env_path=candidate_managed,
            secret_env_path=candidate_secret,
            postgres_env_path=candidate_postgres,
            managed_runtime_path=self.managed_path,
            secret_runtime_path=self.secret_path,
            postgres_runtime_path=self.postgres_path,
        )

        self.assertTrue(report["ok"], report["blockers"])
        self.assertFalse(report["secret_exposed"])

    def test_resource_only_compose_override_is_allowed(self) -> None:
        self._write_legal_fixture()
        override_path = self.fixture_root / "docker-compose.cost-saver.yml"
        override_path.write_text(
            """services:
  jiejing-saas:
    deploy:
      resources:
        limits:
          cpus: "0.75"
          memory: 768M
          pids: 256
        reservations:
          cpus: "0.25"
          memory: 256M
  jiejing-worker:
    deploy:
      resources:
        limits:
          cpus: "0.50"
          memory: 512M
""",
            encoding="utf-8",
        )

        report = check_runtime_env_ownership(
            compose_path=self.compose_path,
            compose_override_paths=(override_path,),
            managed_env_path=self.managed_path,
            secret_env_path=self.secret_path,
            postgres_env_path=self.postgres_path,
        )

        self.assertTrue(report["ok"], report["blockers"])

        second_override = self.fixture_root / "docker-compose.cost-saver-worker.yml"
        second_override.write_text(
            "services:\n  jiejing-worker:\n    deploy:\n      resources:\n        limits:\n          memory: 512M\n",
            encoding="utf-8",
        )
        completed = subprocess.run(
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
                "--compose-override",
                str(override_path),
                "--compose-override",
                str(second_override),
                "--json",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)

    def test_compose_override_cannot_change_runtime_env_or_safety_contract(self) -> None:
        unsafe_cases = {
            "environment": "    environment:\n      JIEJING_ENABLE_REAL_PLATFORM_WRITES: true\n",
            "env_file": "    env_file:\n      - /tmp/untrusted.env\n",
            "safety_key": "    JIEJING_BILLING_PROVIDER: stripe\n",
            "extends": "    extends:\n      service: other\n",
            "anchor": "    deploy: &runtime_settings\n      resources: {}\n",
            "image": "    image: attacker/example:latest\n",
            "build": "    build: /tmp/untrusted\n",
            "command": "    command: python /tmp/untrusted.py\n",
            "entrypoint": "    entrypoint: /tmp/untrusted\n",
            "privileged": "    privileged: true\n",
            "cap_add": "    cap_add:\n      - SYS_ADMIN\n",
            "security_opt": "    security_opt:\n      - seccomp=unconfined\n",
            "volumes": "    volumes:\n      - /:/host\n",
            "devices": "    devices:\n      - /dev:/dev\n",
            "network_mode": "    network_mode: host\n",
            "ports": "    ports:\n      - 9999:9999\n",
            "restart": "    restart: always\n",
            "profiles": "    profiles:\n      - unsafe\n",
            "direct_resource_key": "    mem_limit: 512M\n",
        }
        for case, service_body in unsafe_cases.items():
            with self.subTest(case=case):
                self._write_legal_fixture()
                override_path = self.fixture_root / f"override-{case}.yml"
                override_path.write_text(
                    "services:\n  jiejing-saas:\n" + service_body,
                    encoding="utf-8",
                )

                report = check_runtime_env_ownership(
                    compose_path=self.compose_path,
                    compose_override_paths=(override_path,),
                    managed_env_path=self.managed_path,
                    secret_env_path=self.secret_path,
                    postgres_env_path=self.postgres_path,
                )

                self.assertFalse(report["ok"])
                self.assertTrue(
                    any(
                        blocker.get("code") in {"unsafe_compose_override", "ambiguous_compose_override"}
                        for blocker in report["blockers"]
                    ),
                    report["blockers"],
                )
                self.assertFalse(report["secret_exposed"])

        top_level_include = self.fixture_root / "override-top-level-include.yml"
        top_level_include.write_text(
            "include:\n  - untrusted-runtime.yml\nservices:\n  jiejing-saas:\n    mem_limit: 768M\n",
            encoding="utf-8",
        )
        report = check_runtime_env_ownership(
            compose_path=self.compose_path,
            compose_override_paths=(top_level_include,),
            managed_env_path=self.managed_path,
            secret_env_path=self.secret_path,
            postgres_env_path=self.postgres_path,
        )
        self.assertFalse(report["ok"])
        self.assertTrue(
            any(blocker.get("code") == "ambiguous_compose_override" for blocker in report["blockers"]),
            report["blockers"],
        )

        for top_level_key in ("name", "version", "volumes", "networks", "configs", "secrets"):
            with self.subTest(top_level_key=top_level_key):
                top_level_override = self.fixture_root / f"override-top-level-{top_level_key}.yml"
                top_level_override.write_text(
                    f"services:\n  jiejing-saas:\n    deploy:\n      resources:\n        limits:\n          memory: 512M\n{top_level_key}: {{}}\n",
                    encoding="utf-8",
                )
                report = check_runtime_env_ownership(
                    compose_path=self.compose_path,
                    compose_override_paths=(top_level_override,),
                    managed_env_path=self.managed_path,
                    secret_env_path=self.secret_path,
                    postgres_env_path=self.postgres_path,
                )
                self.assertFalse(report["ok"], top_level_key)

        unknown_service = self.fixture_root / "override-unknown-service.yml"
        unknown_service.write_text(
            "services:\n  attacker-sidecar:\n    image: attacker/example:latest\n",
            encoding="utf-8",
        )
        report = check_runtime_env_ownership(
            compose_path=self.compose_path,
            compose_override_paths=(unknown_service,),
            managed_env_path=self.managed_path,
            secret_env_path=self.secret_path,
            postgres_env_path=self.postgres_path,
        )
        self.assertFalse(report["ok"], report["blockers"])

    def test_compose_override_resource_scalars_are_bounded_and_literal(self) -> None:
        unsafe_values = ("0", "-1", "65", "1e3", "${CPU_LIMIT}", "*cpu", "[1]", "{}", "1:2")
        for value in unsafe_values:
            with self.subTest(value=value):
                self._write_legal_fixture()
                override_path = self.fixture_root / "override-unsafe-scalar.yml"
                override_path.write_text(
                    "services:\n  jiejing-saas:\n    deploy:\n      resources:\n        limits:\n"
                    f"          cpus: {value}\n",
                    encoding="utf-8",
                )
                report = check_runtime_env_ownership(
                    compose_path=self.compose_path,
                    compose_override_paths=(override_path,),
                    managed_env_path=self.managed_path,
                    secret_env_path=self.secret_path,
                    postgres_env_path=self.postgres_path,
                )
                self.assertFalse(report["ok"], value)


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
