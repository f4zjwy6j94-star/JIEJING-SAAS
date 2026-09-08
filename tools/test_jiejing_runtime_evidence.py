#!/usr/bin/env python3
"""Real-file runtime evidence regressions; POSIX trust cases require local root."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import hashlib
import os
from pathlib import Path
import sys
import tempfile
import unittest
import subprocess
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.backup_plan import build_backup_plan
from jiejing_saas.config import SaaSSettings
from jiejing_saas.monitoring import build_monitoring_status
from jiejing_saas.repository import SaaSRepository
from jiejing_saas.runtime_evidence import RuntimeEvidenceError, read_runtime_evidence, write_runtime_evidence_snapshot

KEYS = (
    "JIEJING_COS_BACKUP_LAST_SUCCESS_AT",
    "JIEJING_CLS_LIVE_PROBE_LAST_AT",
    "JIEJING_CLS_INGESTION_LIVE_PROBE_PASSED",
    "JIEJING_CLS_INGESTION_LIVE_PROBE_LAST_AT",
    "JIEJING_PROVIDER_LATENCY_ALARM_VERIFIED_AT",
    "JIEJING_PROVIDER_COST_ALARM_VERIFIED_AT",
)
BOOL_KEY = KEYS[2]


def evidence_at(moment: datetime) -> dict:
    return {key: True if key == BOOL_KEY else moment.isoformat() for key in KEYS}


class RuntimeEvidenceLegacyTests(unittest.TestCase):
    def test_permission_cases_cannot_be_a_silent_green_skip(self):
        self.assertEqual(os.name, "posix", "POSIX runtime is required for this contract")
        self.assertEqual(os.geteuid(), 0, "isolated root-owned fixtures are required")

    def test_unconfigured_legacy_mode_reads_only_six_environment_values(self):
        with patch.dict(os.environ, {KEYS[0]: "  legacy-value  ", BOOL_KEY: "yes", "SYNTHETIC_UNRELATED": "not-exported"}, clear=True):
            result = read_runtime_evidence()
        self.assertEqual(set(result), set(KEYS))
        self.assertEqual(result[KEYS[0]], "legacy-value")
        self.assertEqual(result[BOOL_KEY], "yes")
        self.assertEqual(result[KEYS[1]], "")
        self.assertNotIn("not-exported", json.dumps(result))

    def test_explicit_empty_or_relative_path_cannot_enable_environment_fallback(self):
        for path in ("", "relative.json"):
            with self.subTest(path_kind="empty" if not path else "relative"), patch.dict(os.environ, {"JIEJING_RUNTIME_EVIDENCE_FILE": path}, clear=True):
                with self.assertRaises(RuntimeEvidenceError):
                    read_runtime_evidence()


@unittest.skipUnless(os.name == "posix" and os.geteuid() == 0, "requires isolated POSIX root-owned fixtures")
class RuntimeEvidencePosixTests(unittest.TestCase):
    def setUp(self):
        # /tmp is intentionally not trusted: all ancestors must be root-owned
        # and not group/other writable, including on real production paths.
        self.temp = tempfile.TemporaryDirectory(prefix="jiejing-runtime-evidence-", dir="/root")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.base.chmod(0o755)
        self.snap_dir = self.base / "snapshot"
        self.snap_dir.mkdir(mode=0o755)
        self.snapshot = self.snap_dir / "current.json"
        self.now = datetime.now(timezone.utc).replace(microsecond=0)
        self.old = self.now - timedelta(days=10)
        env = {
            "PATH": "/usr/bin:/bin", "JIEJING_SAAS_ENV": "production",
            "JIEJING_RUNTIME_EVIDENCE_FILE": str(self.snapshot),
            "JIEJING_COS_BACKUP_ENABLED": "true", "JIEJING_COS_BUCKET": "synthetic-only",
            "JIEJING_COS_REGION": "ap-guangzhou", "JIEJING_COS_BACKUP_LIVE_PROBE_REQUIRED": "true",
            "JIEJING_CLS_ENABLED": "true", "JIEJING_CLS_REGION": "ap-guangzhou",
            "JIEJING_CLS_LOGSET_ID": "synthetic-logset", "JIEJING_CLS_TOPIC_ID": "synthetic-topic",
            "JIEJING_CLS_ALERT_POLICY_CONFIGURED": "true", "JIEJING_CLS_LIVE_PROBE_REQUIRED": "true",
            **{key: "true" if key == BOOL_KEY else self.old.isoformat() for key in KEYS},
        }
        self.environment = patch.dict(os.environ, env, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.settings = SaaSSettings.from_env(db_path=self.base / "saas.sqlite", runtime_db_path=self.base / "runtime.sqlite", output_root=self.base / "output", host="127.0.0.1", port=0)
        self.repo = SaaSRepository(self.settings.db_path, database_engine="sqlite")
        self.repo.initialize()

    def write_snapshot(self, evidence):
        temporary = self.snap_dir / "next.json"
        temporary.write_text(json.dumps({"version": 1, "evidence": evidence}), encoding="utf-8")
        temporary.chmod(0o644)
        os.replace(temporary, self.snapshot)

    def run_cli(self, *args):
        return subprocess.run([sys.executable, str(ROOT / "tools/jiejing_runtime_evidence_snapshot.py"), *args],
                              env={"PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1",
                                   "JIEJING_RUNTIME_EVIDENCE_FILE": "/missing/synthetic-only.json"},
                              text=True, capture_output=True, timeout=15)

    def write_env_fixture(self, evidence):
        directory = self.base / "private"
        directory.mkdir(mode=0o700, exist_ok=True)
        path = directory / "synthetic.env"
        path.write_text("\n".join(f"{key}={'true' if value is True else 'false' if value is False else value}" for key, value in evidence.items())
                        + "\nSYNTHETIC_UNRELATED=must-not-be-exported\n", encoding="utf-8")
        path.chmod(0o600)
        return path

    def test_capability_is_exact_and_does_not_read_or_write_files(self):
        before = sorted(str(path.relative_to(self.base)) for path in self.base.rglob("*"))
        process = self.run_cli("--check-capability")
        self.assertEqual(process.returncode, 0)
        self.assertEqual(process.stderr, "")
        self.assertEqual(json.loads(process.stdout), {"status": "capable", "contract_version": "jiejing_runtime_evidence_snapshot_v1",
                                                   "secret_exposed": False, "writes_snapshot": False})
        self.assertEqual(sorted(str(path.relative_to(self.base)) for path in self.base.rglob("*")), before)

    def test_capability_rejects_image_missing_writer_even_if_reader_constant_exists(self):
        image_root = self.base / "old-image"
        (image_root / "tools").mkdir(parents=True)
        (image_root / "jiejing_saas").mkdir()
        (image_root / "jiejing_saas/__init__.py").write_text("", encoding="utf-8")
        # A synthetic incomplete image at the import boundary, not a mocked reader.
        (image_root / "jiejing_saas/runtime_evidence.py").write_text(
            'CONTRACT_VERSION = "jiejing_runtime_evidence_snapshot_v1"\ndef read_runtime_evidence():\n    return {}\n', encoding="utf-8")
        entry = image_root / "tools/jiejing_runtime_evidence_snapshot.py"
        entry.write_bytes((ROOT / "tools/jiejing_runtime_evidence_snapshot.py").read_bytes())
        process = subprocess.run([sys.executable, str(entry), "--check-capability"],
                                 env={"PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1"},
                                 text=True, capture_output=True, timeout=15)
        self.assertEqual(process.returncode, 2)
        self.assertEqual(json.loads(process.stdout)["status"], "blocked")
        self.assertEqual(process.stderr, "")

    def test_prepare_directory_creates_only_leaf_and_never_repairs_untrusted_existing_mode(self):
        target = self.base / "prepared"
        process = self.run_cli("--prepare-directory", "--output-dir", str(target))
        self.assertEqual(process.returncode, 0)
        self.assertEqual(json.loads(process.stdout), {"status": "prepared", "contract_version": "jiejing_runtime_evidence_snapshot_v1",
                                                   "secret_exposed": False, "writes_snapshot": False})
        self.assertEqual(target.stat().st_mode & 0o7777, 0o755)
        self.assertEqual((target.stat().st_uid, target.stat().st_gid), (0, 0))
        self.assertEqual(list(target.iterdir()), [])
        target.chmod(0o777)
        rejected = self.run_cli("--prepare-directory", "--output-dir", str(target))
        self.assertNotEqual(rejected.returncode, 0)
        self.assertEqual(target.stat().st_mode & 0o7777, 0o777)
        self.assertNotIn(str(target), rejected.stdout + rejected.stderr)

    def test_writer_exports_exact_allowlist_atomically_and_preserves_private_source(self):
        path = self.write_env_fixture(evidence_at(self.now))
        source = path.read_bytes()
        self.write_snapshot(evidence_at(self.old))
        old_inode = self.snapshot.stat().st_ino
        process = self.run_cli("--env-file", str(path), "--output-dir", str(self.snap_dir))
        self.assertEqual(process.returncode, 0)
        self.assertEqual(process.stderr, "")
        raw = self.snapshot.read_bytes()
        self.assertEqual(json.loads(process.stdout), {"status": "verified", "contract_version": "jiejing_runtime_evidence_snapshot_v1",
                                                   "secret_exposed": False, "evidence_sha256": hashlib.sha256(raw).hexdigest()})
        self.assertEqual(json.loads(raw), {"version": 1, "evidence": evidence_at(self.now)})
        self.assertEqual(path.read_bytes(), source)
        self.assertEqual(self.snapshot.stat().st_mode & 0o7777, 0o644)
        self.assertEqual((self.snapshot.stat().st_uid, self.snapshot.stat().st_gid), (0, 0))
        self.assertNotEqual(self.snapshot.stat().st_ino, old_inode)
        self.assertNotIn("must-not-be-exported", raw.decode() + process.stdout + process.stderr)
        self.assertEqual(read_runtime_evidence()[KEYS[0]], self.now.isoformat())

    def test_same_process_sees_new_snapshot_without_changing_old_environment(self):
        self.write_snapshot(evidence_at(self.old))
        pid, old_environment = os.getpid(), dict(os.environ)
        before_backup = build_backup_plan(self.settings, self.repo)
        before_monitor = build_monitoring_status(self.settings, self.repo, now_utc=self.now)
        self.assertFalse(before_backup["object_storage"]["live_probe_fresh"])
        self.assertFalse(before_monitor["cloud_monitoring"]["live_probe_fresh"])
        self.write_snapshot(evidence_at(self.now))
        backup = build_backup_plan(self.settings, self.repo)
        monitoring = build_monitoring_status(self.settings, self.repo, now_utc=self.now)
        self.assertTrue(backup["object_storage"]["live_probe_fresh"])
        self.assertTrue(monitoring["cloud_monitoring"]["live_probe_fresh"])
        self.assertTrue(monitoring["cloud_monitoring"]["ingestion_live_probe_fresh"])
        self.assertTrue(monitoring["provider_observability"]["alarm_evidence"]["latency"]["fresh"])
        self.assertTrue(monitoring["provider_observability"]["alarm_evidence"]["cost"]["fresh"])
        self.assertEqual(os.getpid(), pid)
        self.assertEqual(dict(os.environ), old_environment)

    def test_inflight_real_http_response_survives_snapshot_publication(self):
        from concurrent.futures import ThreadPoolExecutor
        from http.client import HTTPConnection
        import threading
        from jiejing_saas.api_server import JiejingSafeThreadingHTTPServer, SaaSBackendHandler

        parsed, release = threading.Event(), threading.Event()
        settings = self.settings

        class HeldRequestHandler(SaaSBackendHandler):
            # A test-only barrier after real HTTP parsing, not a replacement
            # handler/response. Production request handling remains unchanged.
            def parse_request(self):
                result = super().parse_request()
                if result and self.path == "/health" and not parsed.is_set():
                    parsed.set()
                    if not release.wait(15):
                        raise AssertionError("synthetic_http_barrier_timeout")
                return result

        HeldRequestHandler.settings = settings
        self.write_snapshot(evidence_at(self.old))
        source = self.write_env_fixture(evidence_at(self.now))
        pid, environment = os.getpid(), dict(os.environ)
        server = JiejingSafeThreadingHTTPServer(("127.0.0.1", 0), HeldRequestHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        executor = ThreadPoolExecutor(max_workers=1)
        thread.start()

        def request():
            connection = HTTPConnection("127.0.0.1", server.server_address[1], timeout=20)
            try:
                connection.request("GET", "/health")
                response = connection.getresponse()
                raw = response.read()
                return response.status, int(response.getheader("content-length")), raw
            finally:
                connection.close()

        try:
            response = executor.submit(request)
            self.assertTrue(parsed.wait(5), "real request never reached the handler barrier")
            self.assertFalse(response.done())
            published = self.run_cli("--env-file", str(source), "--output-dir", str(self.snap_dir))
            self.assertEqual(published.returncode, 0)
            self.assertEqual(json.loads(published.stdout)["status"], "verified")
            self.assertFalse(response.done(), "held request completed before evidence refresh")
            self.assertEqual(os.getpid(), pid)
            self.assertTrue(thread.is_alive())
            self.assertEqual(dict(os.environ), environment)
            release.set()
            status, length, raw = response.result(timeout=5)
            self.assertEqual(status, 200)
            self.assertEqual(len(raw), length)
            self.assertEqual(json.loads(raw)["status"], "ok")
            self.assertEqual(request()[0], 200)
            self.assertTrue(build_backup_plan(self.settings, self.repo)["object_storage"]["live_probe_fresh"])
            monitoring = build_monitoring_status(self.settings, self.repo, now_utc=self.now)
            self.assertTrue(monitoring["cloud_monitoring"]["live_probe_fresh"])
            self.assertTrue(monitoring["cloud_monitoring"]["ingestion_live_probe_fresh"])
            self.assertEqual(os.getpid(), pid)
            self.assertEqual(dict(os.environ), environment)
        finally:
            release.set()
            executor.shutdown(wait=True)
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
        self.assertFalse(thread.is_alive())

    def test_writer_rejects_bad_input_or_destination_without_changing_previous_snapshot(self):
        source = self.write_env_fixture(evidence_at(self.now))
        original = source.read_bytes()
        self.write_snapshot(evidence_at(self.old))
        previous = self.snapshot.read_bytes()
        bad_inputs = [
            original + (KEYS[0] + '=synthetic-duplicate\n').encode(),
            b'\n'.join(line for line in original.splitlines() if not line.startswith(KEYS[0].encode())),
            original.replace(self.now.isoformat().encode(), b'synthetic-invalid-timestamp'),
            original.replace(b'=true', b'=synthetic-invalid-bool'),
        ]
        for raw in bad_inputs:
            with self.subTest(kind="invalid_allowlist"):
                source.write_bytes(raw)
                rejected = self.run_cli("--env-file", str(source), "--output-dir", str(self.snap_dir))
                self.assertEqual(rejected.returncode, 2)
                self.assertEqual(json.loads(rejected.stdout), {"status": "blocked", "contract_version": "jiejing_runtime_evidence_snapshot_v1",
                                                              "reason": "runtime_evidence_operation_failed", "secret_exposed": False})
                self.assertEqual(rejected.stderr, "")
                self.assertEqual(source.read_bytes(), raw)
                self.assertEqual(self.snapshot.read_bytes(), previous)
                self.assertEqual([path.name for path in self.snap_dir.iterdir()], ["current.json"])
        source.write_bytes(original)
        for path, mode in [(source, 0o644), (source.parent, 0o777), (self.snap_dir, 0o777), (self.snapshot, 0o666)]:
            with self.subTest(kind="untrusted_mode", mode=mode):
                old_mode = path.stat().st_mode & 0o7777
                path.chmod(mode)
                try:
                    rejected = self.run_cli("--env-file", str(source), "--output-dir", str(self.snap_dir))
                    self.assertEqual(rejected.returncode, 2)
                    self.assertEqual(self.snapshot.read_bytes(), previous)
                    self.assertNotIn(str(self.base), rejected.stdout + rejected.stderr)
                finally:
                    path.chmod(old_mode)

    def test_filesystem_failure_before_publish_preserves_old_complete_snapshot(self):
        source = self.write_env_fixture(evidence_at(self.now))
        for boundary in ("fsync", "replace"):
            with self.subTest(boundary=boundary):
                self.write_snapshot(evidence_at(self.old))
                previous = self.snapshot.read_bytes()
                with patch("os." + boundary, side_effect=OSError("synthetic-failure")):
                    with self.assertRaises(OSError):
                        write_runtime_evidence_snapshot(source, self.snap_dir)
                self.assertEqual(self.snapshot.read_bytes(), previous)
                self.assertEqual([path.name for path in self.snap_dir.iterdir()], ["current.json"])
                self.assertEqual(read_runtime_evidence()[KEYS[0]], self.old.isoformat())

    def test_directory_fsync_failure_after_replace_never_claims_old_snapshot_rollback(self):
        source = self.write_env_fixture(evidence_at(self.now))
        self.write_snapshot(evidence_at(self.old))
        original_fsync = os.fsync
        calls = []
        def fail_directory_fsync(descriptor):
            calls.append(descriptor)
            if len(calls) == 2:
                raise OSError("synthetic-directory-durability-failure")
            return original_fsync(descriptor)
        with patch("os.fsync", side_effect=fail_directory_fsync):
            with self.assertRaises(OSError):
                write_runtime_evidence_snapshot(source, self.snap_dir)
        self.assertEqual(len(calls), 2)
        # Rename already published a complete valid new file. There was no
        # success return and no claim of power-loss durability or two-file atomicity.
        self.assertEqual(json.loads(self.snapshot.read_bytes()), {"version": 1, "evidence": evidence_at(self.now)})
        self.assertEqual(read_runtime_evidence()[KEYS[0]], self.now.isoformat())
        self.assertEqual([path.name for path in self.snap_dir.iterdir()], ["current.json"])

    def test_monitoring_reads_one_complete_snapshot_for_cls_and_both_alarms(self):
        self.write_snapshot(evidence_at(self.now))
        original_open = os.open
        reads = []
        def open_then_replace(path, flags, *args, **kwargs):
            descriptor = original_open(path, flags, *args, **kwargs)
            if path == "current.json" and not flags & os.O_WRONLY:
                reads.append(descriptor)
                self.write_snapshot(evidence_at(self.old))
            return descriptor
        # Patch only the filesystem boundary: all builders and the reader are real.
        with patch("os.open", side_effect=open_then_replace):
            result = build_monitoring_status(self.settings, self.repo, now_utc=self.now)
        self.assertEqual(len(reads), 1)
        self.assertTrue(result["cloud_monitoring"]["live_probe_fresh"])
        self.assertTrue(result["cloud_monitoring"]["ingestion_live_probe_fresh"])
        self.assertTrue(result["provider_observability"]["alarm_evidence"]["latency"]["fresh"])
        self.assertTrue(result["provider_observability"]["alarm_evidence"]["cost"]["fresh"])
        self.assertEqual(read_runtime_evidence()[KEYS[0]], self.old.isoformat())

    def test_snapshot_does_not_extend_stale_or_future_evidence_freshness(self):
        for moment in (self.old, self.now + timedelta(days=1)):
            with self.subTest(kind="stale" if moment < self.now else "future"):
                self.write_snapshot(evidence_at(moment))
                self.assertEqual(read_runtime_evidence()[KEYS[0]], moment.isoformat())
                backup = build_backup_plan(self.settings, self.repo)
                monitoring = build_monitoring_status(self.settings, self.repo, now_utc=self.now)
                self.assertFalse(backup["object_storage"]["live_probe_fresh"])
                self.assertFalse(monitoring["cloud_monitoring"]["live_probe_fresh"])
                self.assertFalse(monitoring["cloud_monitoring"]["ingestion_live_probe_fresh"])
                self.assertFalse(monitoring["provider_observability"]["alarm_evidence"]["latency"]["fresh"])
                self.assertFalse(monitoring["provider_observability"]["alarm_evidence"]["cost"]["fresh"])

    def test_invalid_protocol_never_uses_valid_environment(self):
        os.environ.update({key: "true" if key == BOOL_KEY else self.now.isoformat() for key in KEYS})
        valid = {"version": 1, "evidence": evidence_at(self.now)}
        invalid = [
            {**valid, "unexpected": True},
            {**valid, "version": True},
            {**valid, "version": 2},
            {"version": 1, "evidence": {**valid["evidence"], "unexpected": "synthetic"}},
            {"version": 1, "evidence": {key: value for key, value in valid["evidence"].items() if key != BOOL_KEY}},
            {"version": 1, "evidence": {**valid["evidence"], BOOL_KEY: "true"}},
            {"version": 1, "evidence": {**valid["evidence"], KEYS[0]: "not-an-iso-time"}},
            {"version": 1, "evidence": {**valid["evidence"], KEYS[0]: self.now.replace(tzinfo=None).isoformat()}},
        ]
        raw_cases = [json.dumps(value) for value in invalid]
        raw_cases += [json.dumps(valid).replace('"version": 1', '"version": 1, "version": 1'),
                      json.dumps(valid) + " " * 16384, '{"version":1,', '[]', '[' * 7900 + ']' * 7900,
                      '{"a":' * 2600 + '0' + '}' * 2600]
        for index, raw in enumerate(raw_cases):
            with self.subTest(case=index):
                self.snapshot.write_text(raw, encoding="utf-8")
                self.snapshot.chmod(0o644)
                with self.assertRaisesRegex(RuntimeEvidenceError, r"^runtime_evidence_[a-z_]+$"):
                    read_runtime_evidence()

    def test_untrusted_permissions_owners_and_symlink_ancestors_are_rejected(self):
        self.write_snapshot(evidence_at(self.now))
        for path, mode in [(self.snapshot, 0o600), (self.snapshot, 0o666), (self.snap_dir, 0o775), (self.base, 0o777)]:
            with self.subTest(kind="mode", mode=mode):
                old_mode = path.stat().st_mode & 0o7777
                path.chmod(mode)
                try:
                    with self.assertRaises(RuntimeEvidenceError):
                        read_runtime_evidence()
                finally:
                    path.chmod(old_mode)
        for path in (self.snapshot, self.snap_dir, self.base):
            with self.subTest(kind="owner", level=path.name):
                os.chown(path, 1000, 1000)
                try:
                    with self.assertRaises(RuntimeEvidenceError):
                        read_runtime_evidence()
                finally:
                    os.chown(path, 0, 0)
        direct_link, parent_link = self.base / "linked.json", self.base / "linked-dir"
        direct_link.symlink_to(self.snapshot)
        parent_link.symlink_to(self.snap_dir, target_is_directory=True)
        for path in (direct_link, parent_link / "current.json"):
            with self.subTest(kind="symlink", level=path.name), patch.dict(os.environ, {"JIEJING_RUNTIME_EVIDENCE_FILE": str(path)}):
                with self.assertRaises(RuntimeEvidenceError):
                    read_runtime_evidence()

    def test_recursive_json_parser_failure_is_a_safe_missing_evidence_result(self):
        self.snapshot.write_text('[' * 2000 + ']' * 2000, encoding="utf-8")
        self.snapshot.chmod(0o644)
        # CPython scanner implementations have different recursion ceilings.
        # Exercise the real standard-library recursive scanner and real file.
        with patch("json.scanner.make_scanner", json.scanner.py_make_scanner):
            with self.assertRaises(RuntimeEvidenceError):
                read_runtime_evidence()
            backup = build_backup_plan(self.settings, self.repo)
            monitoring = build_monitoring_status(self.settings, self.repo, now_utc=self.now)
        self.assertIn("runtime_evidence_unavailable", backup["object_storage"]["blocked_by"])
        self.assertIn("runtime_evidence_unavailable", monitoring["cloud_monitoring"]["blocked_by"])
        self.assertNotIn(str(self.base), json.dumps([backup, monitoring]))

    def test_timestamp_utc_overflow_is_rejected_before_consumers(self):
        for timestamp in ("0001-01-01T00:00:00+01:00", "9999-12-31T23:59:59-01:00"):
            with self.subTest(timestamp_boundary=timestamp[:4]):
                self.write_snapshot({key: True if key == BOOL_KEY else timestamp for key in KEYS})
                with self.assertRaises(RuntimeEvidenceError):
                    read_runtime_evidence()
                backup = build_backup_plan(self.settings, self.repo)
                monitoring = build_monitoring_status(self.settings, self.repo, now_utc=self.now)
                self.assertFalse(backup["object_storage"]["target_ready"])
                self.assertFalse(monitoring["production_monitoring_ready"])
                self.assertIn("runtime_evidence_unavailable", backup["object_storage"]["blocked_by"])
                self.assertIn("runtime_evidence_unavailable", monitoring["cloud_monitoring"]["blocked_by"])

    def test_invalid_snapshot_builders_fail_closed_without_exception_or_path_disclosure(self):
        from jiejing_saas.readiness import build_product_readiness_or_degraded
        os.environ.update({key: "true" if key == BOOL_KEY else self.now.isoformat() for key in KEYS})
        os.environ["JIEJING_CLS_LIVE_PROBE_REQUIRED"] = "false"
        for raw in (None, '{"version":1,'):
            with self.subTest(missing=raw is None):
                if raw is not None:
                    self.snapshot.write_text(raw, encoding="utf-8")
                    self.snapshot.chmod(0o644)
                backup = build_backup_plan(self.settings, self.repo)
                monitoring = build_monitoring_status(self.settings, self.repo, now_utc=self.now)
                readiness = build_product_readiness_or_degraded(self.settings, self.repo)
                self.assertFalse(backup["object_storage"]["target_ready"])
                self.assertFalse(monitoring["cloud_monitoring"]["target_ready"])
                self.assertFalse(monitoring["production_monitoring_ready"])
                self.assertFalse(readiness["production_ready"])
                self.assertIn("runtime_evidence_unavailable", backup["object_storage"]["blocked_by"])
                self.assertIn("runtime_evidence_unavailable", monitoring["cloud_monitoring"]["blocked_by"])
                self.assertNotIn(str(self.base), json.dumps([backup, monitoring]))


def platform_main():
    if os.name == "nt":
        wsl = Path(r"C:\Windows\System32\wsl.exe")
        source = Path(__file__).resolve()
        if not wsl.is_file() or len(source.drive) != 2 or source.drive[1] != ":":
            print("runtime_evidence_tests_require_wsl_root")
            return 2
        linux_source = "/mnt/" + source.drive[0].lower() + source.as_posix()[2:]
        command = [str(wsl), "--user", "root", "--exec", "/usr/bin/env", "-i",
                   "PATH=/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE=1", "/usr/bin/python3", linux_source, *sys.argv[1:]]
        try:
            return subprocess.run(command, env={"SystemRoot": r"C:\Windows", "WINDIR": r"C:\Windows",
                                               "PATH": r"C:\Windows\System32"}, timeout=240).returncode
        except (OSError, subprocess.TimeoutExpired):
            print("runtime_evidence_tests_require_wsl_root")
            return 2
    if os.name != "posix" or os.geteuid() != 0:
        print("runtime_evidence_tests_require_isolated_posix_root")
        return 2
    unittest.main(verbosity=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(platform_main())
