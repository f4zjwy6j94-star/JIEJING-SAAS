#!/usr/bin/env python3
"""Contract checks for the confirmation-gated production deploy channel."""

from __future__ import annotations

import contextlib
import importlib.util
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import warnings
import zipfile


ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT / "tools" / "jiejing_production_deploy.py"
APPLY = ROOT / "deploy" / "jiejing-production-release-apply.sh"
COMPOSE = ROOT / "deploy" / "docker-compose.production-pilot.yml"
PATCH_APPLY = ROOT / "deploy" / "apply-staging-patch.sh"
CI = ROOT / ".github" / "workflows" / "jiejing-ci.yml"
RUNBOOK = ROOT / "docs" / "JIEJING_PRODUCTION_DEPLOY_RUNBOOK_20260823.md"
PRECLOUD_GATE = ROOT / "tools" / "jiejing_precloud_deployment_gate.py"
BASH_REQUIRED_MESSAGE = (
    "bash executable is required for production deploy channel runtime contract fixtures"
)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")

PHASE3_BUNDLE_FILES = {
    "jiejing_saas/runtime_evidence.py",
    "tools/jiejing_runtime_evidence_snapshot.py",
    "tools/test_jiejing_runtime_evidence.py",
    "docs/superpowers/specs/2026-09-08-production-evidence-no-restart-design.md",
    "docs/superpowers/plans/2026-09-08-production-evidence-no-restart-implementation-plan.md",
    "deploy/jiejing-production-evidence-auto-refresh.sh",
    "deploy/systemd/jiejing-production-evidence-refresh.service",
    "deploy/systemd/jiejing-production-evidence-refresh.timer",
    "tools/test_jiejing_production_evidence_auto_refresh_guardrails.py",
    "docs/superpowers/specs/2026-08-26-production-evidence-auto-refresh-design.md",
    "docs/superpowers/plans/2026-08-26-production-evidence-auto-refresh-implementation-plan.md",
}

BASE_BUNDLE_FILES = {
    "index.html",
    "app.html",
    "app.js",
    "styles.css",
    "Dockerfile.saas",
    "deploy/docker-compose.production-pilot.yml",
    "deploy/Caddyfile.production",
    "deploy/nginx.ops.production.conf",
    "ops.html", "ops.js", "ops.css", "assets/jiejing-logo-mark.svg",
    "assets/jiejing-app-icon.svg", "assets/jiejing-ops-panels.js",
    "deploy/jiejing-production-release-apply.sh",
    "jiejing_saas/migrations/002_media_credit_buckets_postgres.sql",
    "jiejing_saas/migrations/003_runtime_schema_reconciliation_postgres.sql",
    "jiejing_saas/migrations/004_platform_model_trial_reservations_postgres.sql",
    "tools/jiejing_secret_scan.py",
}

def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def require_bash_contract(resolver=shutil.which) -> str:
    bash_path = resolver("bash")
    if not bash_path:
        raise RuntimeError(BASH_REQUIRED_MESSAGE)
    return str(bash_path)


def read(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(path)
    return path.read_text(encoding="utf-8")


def validate_retired_diagnostic_exclusions(apply: str) -> list[str]:
    """A fresh candidate must not inherit removed one-shot capture code."""
    start = apply.index('rsync -a --delete')
    end = apply.index('"$active_app/" "$candidate_app/"', start)
    previous_release_copy = apply[start:end]
    paths = ('jiejing_saas/private_answer_capture.py', 'tools/test_jiejing_ai_ceo_private_answer_capture.py')
    return [f'retired diagnostic inherited from active release:{path}' for path in paths
            if f"--exclude '{path}'" not in previous_release_copy]


def load_deploy_module():
    spec = importlib.util.spec_from_file_location("jiejing_production_deploy", CLIENT)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load production deploy module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate_required_bundle_files() -> list[str]:
    module = load_deploy_module()
    failures: list[str] = []
    with tempfile.TemporaryDirectory(prefix="jiejing-production-bundle-contract-") as temp_dir:
        temp = Path(temp_dir)
        complete = BASE_BUNDLE_FILES | PHASE3_BUNDLE_FILES
        complete_zip = temp / "complete.zip"
        with zipfile.ZipFile(complete_zip, "w") as archive:
            for name in sorted(complete):
                archive.writestr(name, "placeholder\n")
        try:
            module.validate_zip(complete_zip)
        except ValueError as exc:
            failures.append(f"complete phase3 bundle rejected: {exc}")

        for omitted in sorted(PHASE3_BUNDLE_FILES):
            bundle = temp / (omitted.replace("/", "_") + ".zip")
            with zipfile.ZipFile(bundle, "w") as archive:
                for name in sorted(complete - {omitted}):
                    archive.writestr(name, "placeholder\n")
            try:
                module.validate_zip(bundle)
            except ValueError as exc:
                if omitted not in str(exc):
                    failures.append(f"missing {omitted} produced imprecise error: {exc}")
            else:
                failures.append(f"bundle missing {omitted} was accepted")
    return failures


def validate_atomic_frontend_manifest() -> list[str]:
    module = load_deploy_module()
    failures: list[str] = []
    family = "20260831-atomic-workbench"
    app_js = b"console.log('atomic frontend');\r\n"
    styles_css = b"body { color: #123; }\r\n"
    app_digest = hashlib.sha256(app_js.replace(b"\r\n", b"\n")).hexdigest()[:12]
    styles_digest = hashlib.sha256(styles_css.replace(b"\r\n", b"\n")).hexdigest()[:12]
    app_version = f"{family}-{app_digest}"
    styles_version = f"{family}-{styles_digest}"
    files = {
        "index.html": (
            f'<link rel="prefetch" href="./app.js?v={app_version}" as="script">\n'
            f'<link rel="prefetch" href="./styles.css?v={styles_version}" as="style">\n'
            f'<script data-lazy="./app.js?v={app_version}"></script>\n'
            f'<meta data-lazy-style="./styles.css?v={styles_version}">\n'
        ).encode("utf-8"),
        "app.html": (
            f'<link rel="stylesheet" href="./styles.css?v={styles_version}">\n'
            f'<script src="./app.js?v={app_version}"></script>\n'
        ).encode("utf-8"),
        "app.js": app_js,
        "styles.css": styles_css,
    }
    manifest = {
        "frontend_files_sha256": {
            name: hashlib.sha256(contents).hexdigest() for name, contents in files.items()
        },
        "source_commit": "a" * 40,
        "file_count": len(files),
        "files": list(files),
        "files_sha256": {
            name: hashlib.sha256(contents).hexdigest() for name, contents in files.items()
        },
    }
    with tempfile.TemporaryDirectory(prefix="jiejing-atomic-frontend-contract-") as temp_dir:
        bundle = Path(temp_dir) / "bundle.zip"
        with zipfile.ZipFile(bundle, "w") as archive:
            for name, contents in files.items():
                archive.writestr(name, contents)
        try:
            module.validate_atomic_frontend_release(bundle, manifest)
        except (AttributeError, TypeError, ValueError) as exc:
            failures.append(f"valid atomic frontend manifest rejected:{exc}")
        try:
            module.validate_bundle_manifest(bundle, manifest, set(files), "a" * 40)
        except (AttributeError, TypeError, ValueError) as exc:
            failures.append(f"valid complete bundle manifest rejected:{exc}")
        for label, broken in (
            ("stale source", {**manifest, "source_commit": "b" * 40}),
            (
                "missing file hash",
                {
                    **manifest,
                    "files_sha256": {
                        name: digest
                        for name, digest in manifest["files_sha256"].items()
                        if name != "app.html"
                    },
                },
            ),
            (
                "extra file hash",
                {
                    **manifest,
                    "files_sha256": {
                        **manifest["files_sha256"],
                        "unexpected.txt": "0" * 64,
                    },
                },
            ),
            ("missing manifest file", {**manifest, "files": list(files)[:-1]}),
            ("wrong file count", {**manifest, "file_count": len(files) + 1}),
        ):
            try:
                module.validate_bundle_manifest(bundle, broken, set(files), "a" * 40)
            except (AttributeError, TypeError, ValueError):
                continue
            failures.append(f"unsafe complete bundle manifest accepted:{label}")
        broken_manifests = [
            {},
            {
                "frontend_files_sha256": {
                    name: digest
                    for name, digest in manifest["frontend_files_sha256"].items()
                    if name != "app.html"
                }
            },
            {"frontend_files_sha256": {**manifest["frontend_files_sha256"], "app.js": "0" * 64}},
            {"frontend_files_sha256": {**manifest["frontend_files_sha256"], "extra.html": "0" * 64}},
        ]
        for broken in broken_manifests:
            try:
                module.validate_atomic_frontend_release(bundle, broken)
            except (AttributeError, TypeError, ValueError):
                continue
            failures.append("missing, mismatched, or over-broad frontend manifest was accepted")

        def expect_frontend_rejected(label: str, changed_files: dict[str, bytes]) -> None:
            changed_bundle = Path(temp_dir) / f"{label}.zip"
            with zipfile.ZipFile(changed_bundle, "w") as archive:
                for name, contents in changed_files.items():
                    archive.writestr(name, contents)
            changed_manifest = {
                "frontend_files_sha256": {
                    name: hashlib.sha256(contents).hexdigest()
                    for name, contents in changed_files.items()
                }
            }
            try:
                module.validate_atomic_frontend_release(changed_bundle, changed_manifest)
            except (AttributeError, TypeError, ValueError):
                return
            failures.append(f"unsafe frontend reference accepted:{label}")

        expect_frontend_rejected(
            "mixed-family",
            {
                **files,
                "index.html": files["index.html"].replace(
                    family.encode("utf-8"), b"other-family"
                ),
            },
        )
        expect_frontend_rejected(
            "lazy-string-only",
            {
                **files,
                "index.html": (
                    f'<div data-lazy="./app.js?v={app_version}" '
                    f'data-style="./styles.css?v={styles_version}"></div>\n'
                ).encode("utf-8"),
            },
        )
        expect_frontend_rejected(
            "extra-unversioned",
            {
                **files,
                "app.html": files["app.html"] + b'<script src="./app.js"></script>\n',
            },
        )
        expect_frontend_rejected(
            "absolute-load",
            {
                **files,
                "app.html": files["app.html"]
                + f'<script src="https://cdn.example.test/app.js?v={app_version}"></script>\n'.encode(
                    "utf-8"
                ),
            },
        )

        validation_files = {
            name: files.get(name, b"placeholder\n")
            for name in BASE_BUNDLE_FILES | PHASE3_BUNDLE_FILES
        }
        validation_files.update({name: b"/* public operations fixture */\n" for name in module.ATOMIC_OPS_FILES})
        validation_files["ops.html"] = (
            b'<link rel="stylesheet" href="ops.css?v=fixture">'
            b'<script src="assets/jiejing-ops-panels.js?v=fixture"></script>'
            b'<script src="ops.js?v=fixture"></script>'
        ).replace(b'?v=fixture', b'?v=' + module.ops_asset_version(validation_files).encode())
        full_bundle = Path(temp_dir) / "full-candidate.zip"
        with zipfile.ZipFile(full_bundle, "w") as archive:
            for name, contents in validation_files.items():
                archive.writestr(name, contents)
        full_manifest = {
            "scope": "public_staging_patch_whitelist_v1",
            "real_platform_writes_enabled": False,
            "source_commit": "a" * 40,
            "file_count": len(validation_files),
            "files": list(validation_files),
            "files_sha256": {
                name: hashlib.sha256(contents).hexdigest()
                for name, contents in validation_files.items()
            },
            "frontend_files_sha256": {
                name: hashlib.sha256(validation_files[name]).hexdigest()
                for name in ("index.html", "app.html", "app.js", "styles.css")
            },
            "ops_files_sha256": {
                name: hashlib.sha256(validation_files[name]).hexdigest()
                for name in module.ATOMIC_OPS_FILES
            },
            "zip_sha256": module.sha256(full_bundle),
        }
        full_manifest_path = Path(temp_dir) / "full-candidate.manifest.json"
        full_manifest_path.write_text(json.dumps(full_manifest), encoding="utf-8")
        fixture_source_hashes = {
            name: hashlib.sha256(contents).hexdigest()
            for name, contents in validation_files.items()
        }
        try:
            module.validate_local_release_candidate(
                full_bundle, full_manifest_path, set(validation_files), "a" * 40,
                source_files_sha256=fixture_source_hashes,
            )
        except ValueError as exc:
            if "gate_evidence" not in str(exc):
                failures.append(f"missing gate proof produced imprecise rejection:{exc}")
        else:
            failures.append("new release candidate without source-bound gate proof was accepted")
        try:
            from jiejing_release_gate_evidence import build_gate_evidence
        except ModuleNotFoundError:
            from tools.jiejing_release_gate_evidence import build_gate_evidence
        fixture_checks = [("fixture_pass", ["python", "tools/fixture.py"])]
        fixture_state = {"source_commit": "a" * 40, "source_tree": "b" * 40,
                         "worktree_clean": True, "tracked_flags_safe": True, "tracked_fingerprint_sha256": "c" * 64}
        full_manifest["release_gate_proof"] = {"report_sha256": "d" * 64, "evidence": build_gate_evidence(
            fixture_checks, [{"key": "fixture_pass", "pass": True, "returncode": 0}],
            fixture_state, fixture_state, "2026-09-05T10:00:00Z", "2026-09-05T10:00:01Z", ROOT,
        )}
        full_manifest_path.write_text(json.dumps(full_manifest), encoding="utf-8")
        try:
            _, initial_bundle_sha, initial_manifest_sha = module.validate_local_release_candidate(
                full_bundle,
                full_manifest_path,
                set(validation_files),
                "a" * 40,
                source_files_sha256=fixture_source_hashes,
                source_tree="b" * 40, gate_checks=fixture_checks,
            )
        except (AttributeError, TypeError, ValueError) as exc:
            failures.append(f"valid sealed release candidate rejected:{exc}")
            initial_bundle_sha = module.sha256(full_bundle)
            initial_manifest_sha = module.sha256(full_manifest_path)

        original_proof_bytes = full_manifest_path.read_bytes()
        for label, edit in (
            ("stale source", lambda evidence: evidence.update(source_commit="f" * 40)),
            ("stale catalog", lambda evidence: evidence.update(check_catalog_sha256="0" * 64)),
            ("failed result", lambda evidence: evidence["results"][0].update(returncode=1)),
            ("missing result", lambda evidence: evidence["results"].clear()),
        ):
            candidate_manifest = json.loads(original_proof_bytes)
            edit(candidate_manifest["release_gate_proof"]["evidence"])
            full_manifest_path.write_text(json.dumps(candidate_manifest), encoding="utf-8")
            try:
                module.validate_local_release_candidate(
                    full_bundle, full_manifest_path, set(validation_files), "a" * 40,
                    source_files_sha256=fixture_source_hashes, source_tree="b" * 40, gate_checks=fixture_checks,
                )
            except ValueError as exc:
                if "gate_evidence" not in str(exc):
                    failures.append(f"{label} gate proof produced imprecise rejection:{exc}")
            else:
                failures.append(f"production validator accepted {label} gate proof")
        full_manifest_path.write_bytes(original_proof_bytes)

        original_bundle_bytes = full_bundle.read_bytes()
        full_bundle.write_bytes(original_bundle_bytes + b"tampered-after-initial-validation")
        try:
            module.validate_local_release_candidate(
                full_bundle,
                full_manifest_path,
                set(validation_files),
                "a" * 40,
                expected_bundle_sha256=initial_bundle_sha,
                expected_manifest_sha256=initial_manifest_sha,
                source_files_sha256=fixture_source_hashes,
            )
        except (AttributeError, TypeError, ValueError) as exc:
            if "candidate_bundle_changed" not in str(exc):
                failures.append(f"changed bundle produced imprecise rejection:{exc}")
        else:
            failures.append("bundle changed after initial validation was accepted")
        full_bundle.write_bytes(original_bundle_bytes)

        original_manifest_bytes = full_manifest_path.read_bytes()
        full_manifest_path.write_bytes(original_manifest_bytes + b" \n")
        try:
            module.validate_local_release_candidate(
                full_bundle,
                full_manifest_path,
                set(validation_files),
                "a" * 40,
                expected_bundle_sha256=initial_bundle_sha,
                expected_manifest_sha256=initial_manifest_sha,
                source_files_sha256=fixture_source_hashes,
            )
        except (AttributeError, TypeError, ValueError) as exc:
            if "candidate_manifest_changed" not in str(exc):
                failures.append(f"changed manifest produced imprecise rejection:{exc}")
        else:
            failures.append("manifest changed after initial validation was accepted")
        full_manifest_path.write_bytes(original_manifest_bytes)

        original_git_value = module.git_value
        source_state = {"head": "a" * 40, "dirty": ""}

        def fixture_git_value(*args: str) -> str:
            if args[:2] == ("rev-parse", "HEAD"):
                return source_state["head"]
            if args and args[0] == "status":
                return source_state["dirty"]
            return original_git_value(*args)

        module.git_value = fixture_git_value
        try:
            module.assert_source_state("a" * 40)
            source_state["head"] = "b" * 40
            try:
                module.assert_source_state("a" * 40)
            except ValueError as exc:
                if "source_commit_changed" not in str(exc):
                    failures.append(f"changed HEAD produced imprecise rejection:{exc}")
            else:
                failures.append("HEAD changed before upload was accepted")
        finally:
            module.git_value = original_git_value

        current_source_commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=True,
            timeout=30,
        ).stdout.strip()
        committed_whitelist_bytes = module.git_blob_bytes(
            current_source_commit,
            "deploy/apply-staging-patch.sh",
        )
        original_root = module.ROOT
        original_git_blob_bytes = module.git_blob_bytes
        transient_root = Path(temp_dir) / "transient-worktree-root"
        (transient_root / "deploy").mkdir(parents=True)
        transient_worktree_whitelist = committed_whitelist_bytes.decode("utf-8").replace(
            ")\n",
            '  "worktree-only-forged.txt"\n)\n',
            1,
        )
        (transient_root / "deploy" / "apply-staging-patch.sh").write_text(
            transient_worktree_whitelist,
            encoding="utf-8",
        )
        module.ROOT = transient_root
        module.git_blob_bytes = lambda source, path: committed_whitelist_bytes
        try:
            pinned_deploy_whitelist = module.apply_patch_file_list(current_source_commit)
        finally:
            module.git_blob_bytes = original_git_blob_bytes
            module.ROOT = original_root
        if "worktree-only-forged.txt" in pinned_deploy_whitelist:
            failures.append("deploy whitelist followed a transient worktree expansion")
        forged_targets = {
            "deploy/jiejing-production-release-apply.sh",
            "app.js",
        }
        committed_target_bytes = {
            name: module.git_blob_bytes(current_source_commit, name)
            for name in forged_targets
        }
        forged_contents = {
            **committed_target_bytes,
            "deploy/jiejing-production-release-apply.sh": (
                b"#!/usr/bin/env bash\necho FORGED_APPLY_ENTERED\n"
            ),
        }
        forged_bundle = Path(temp_dir) / "forged-self-consistent.zip"
        with zipfile.ZipFile(forged_bundle, "w") as archive:
            for name, contents in forged_contents.items():
                archive.writestr(name, contents)
        forged_manifest = {
            "source_commit": current_source_commit,
            "file_count": len(forged_contents),
            "files": list(forged_contents),
            "files_sha256": {
                name: hashlib.sha256(contents).hexdigest()
                for name, contents in forged_contents.items()
            },
        }
        try:
            module.validate_bundle_manifest(
                forged_bundle,
                forged_manifest,
                set(forged_contents),
                current_source_commit,
            )
        except (AttributeError, TypeError, ValueError) as exc:
            failures.append(f"self-consistent forged manifest fixture invalid:{exc}")
        try:
            module.validate_bundle_matches_source_commit(
                forged_bundle,
                set(forged_contents),
                current_source_commit,
            )
        except (AttributeError, TypeError, ValueError) as exc:
            expected_error = (
                "bundle_source_commit_mismatch:"
                "deploy/jiejing-production-release-apply.sh"
            )
            if expected_error not in str(exc):
                failures.append(f"forged apply script produced imprecise rejection:{exc}")
        else:
            failures.append("self-consistent forged apply script matched the source commit")

        try:
            require_bash_contract()
        except RuntimeError as exc:
            failures.append(str(exc))
        else:
            with tempfile.TemporaryDirectory(
                prefix="jiejing-remote-integrity-fixture-", dir=ROOT
            ) as remote_temp_dir:
                remote_temp = Path(remote_temp_dir)
                source_zip = remote_temp / "source.zip"
                source_manifest = remote_temp / "source.manifest"
                source_zip.write_bytes(original_bundle_bytes)
                source_manifest.write_bytes(original_manifest_bytes)
                expected_received_zip_sha = module.sha256(source_zip)
                expected_received_manifest_sha = module.sha256(source_manifest)
                token = os.urandom(4).hex()
                remote_base = f"/tmp/jiejing-production-integrity-{token}"
                received_zip_upload = remote_base + ".zip.uploading"
                received_manifest_upload = remote_base + ".manifest.json.uploading"
                received_zip = remote_base + ".zip"
                received_manifest = remote_base + ".manifest.json"
                received_dir = remote_base + ".d"
                prelude = module.build_remote_integrity_prelude(
                    remote_zip_upload=received_zip_upload,
                    remote_zip=received_zip,
                    expected_bundle_sha256=expected_received_zip_sha,
                    remote_manifest_upload=received_manifest_upload,
                    remote_manifest=received_manifest,
                    expected_manifest_sha256=expected_received_manifest_sha,
                    remote_dir=received_dir,
                )
                cleanup_start = prelude.index("cleanup_remote_artifacts() {")
                cleanup_end = prelude.index("\n}", cleanup_start)
                cleanup_function = prelude[cleanup_start:cleanup_end]
                if 'exit "$' in cleanup_function or 'return "$final_rc"' not in cleanup_function:
                    failures.append("remote EXIT cleanup can recurse through exit instead of returning")
                source_zip_relative = source_zip.relative_to(ROOT).as_posix()
                source_manifest_relative = source_manifest.relative_to(ROOT).as_posix()
                copy_inputs = (
                    f"cp '{source_zip_relative}' '{received_zip_upload}'\n"
                    f"cp '{source_manifest_relative}' '{received_manifest_upload}'\n"
                )
                source_zip.write_bytes(original_bundle_bytes + b"tampered-in-transit")
                remote_result = run_bash_login_fixture(
                    copy_inputs + prelude + "\necho APPLY_ENTERED\n",
                    remote_temp,
                    "remote-integrity-login-fixture.sh",
                )
                combined = remote_result.stdout + remote_result.stderr
                if remote_result.returncode != 1 or "APPLY_ENTERED" in combined:
                    failures.append("tampered received bundle did not fail closed with rc=1")
                if "REMOTE_ARTIFACT_SHA256_MISMATCH=" not in combined:
                    failures.append(
                        "tampered received bundle lacked deterministic hash rejection:"
                        + combined[-500:]
                    )
                cleanup_check_script = "\n".join(
                    [
                        "#!/usr/bin/env bash",
                        "set -euo pipefail",
                        *[f"[[ ! -e '{path}' ]]" for path in (
                            received_zip_upload,
                            received_zip,
                            received_manifest_upload,
                            received_manifest,
                            received_dir,
                        )],
                    ]
                )
                cleanup_check = run_bash_fixture(
                    cleanup_check_script,
                    remote_temp,
                    "remote-hash-cleanup-check.sh",
                )
                if cleanup_check.returncode != 0:
                    failures.append("hash mismatch left remote temporary artifacts")

                source_zip.write_bytes(original_bundle_bytes)
                mock_unzip = (
                    "unzip() {\n"
                    "  if [[ \"$1\" == \"-tq\" ]]; then return 0; fi\n"
                    "  if [[ \"$1\" == \"-q\" ]]; then mkdir -p \"$4\"; return 0; fi\n"
                    "  return 2\n"
                    "}\n"
                )
                apply_failure = run_bash_login_fixture(
                    copy_inputs
                    + mock_unzip
                    + prelude
                    + "\necho APPLY_ENTERED\nfalse\n",
                    remote_temp,
                    "remote-apply-failure-login-fixture.sh",
                )
                apply_combined = apply_failure.stdout + apply_failure.stderr
                if apply_failure.returncode != 1 or "APPLY_ENTERED" not in apply_combined:
                    failures.append(
                        "remote apply-failure fixture did not preserve rc=1:"
                        + apply_combined[-500:]
                    )
                if "pop_var_context" in apply_combined:
                    failures.append("remote apply failure triggered bash trap context corruption")
                cleanup_check = run_bash_fixture(
                    cleanup_check_script,
                    remote_temp,
                    "remote-apply-cleanup-check.sh",
                )
                if cleanup_check.returncode != 0:
                    failures.append("apply failure left remote temporary artifacts")

                dry_run_success = run_bash_login_fixture(
                    copy_inputs
                    + mock_unzip
                    + prelude
                    + "\necho REMOTE_DRY_RUN_RUNTIME_PASS\n",
                    remote_temp,
                    "remote-dry-run-success-login-fixture.sh",
                )
                dry_run_combined = dry_run_success.stdout + dry_run_success.stderr
                if (
                    dry_run_success.returncode != 0
                    or "REMOTE_DRY_RUN_RUNTIME_PASS" not in dry_run_combined
                ):
                    failures.append(
                        "remote dry-run success fixture failed rc="
                        + str(dry_run_success.returncode)
                        + " output="
                        + dry_run_combined[-500:]
                    )
                if "pop_var_context" in dry_run_combined:
                    failures.append("remote dry-run success triggered bash trap context corruption")
                cleanup_check = run_bash_fixture(
                    cleanup_check_script,
                    remote_temp,
                    "remote-success-cleanup-check.sh",
                )
                if cleanup_check.returncode != 0:
                    failures.append("successful remote dry-run left temporary artifacts")

                cleanup_failure = run_bash_login_fixture(
                    copy_inputs
                    + mock_unzip
                    + "FAIL_REMOTE_CLEANUP=0\n"
                    + "rm() {\n"
                    + "  if [[ \"$FAIL_REMOTE_CLEANUP\" == \"1\" ]]; then return 23; fi\n"
                    + "  command rm \"$@\"\n"
                    + "}\n"
                    + prelude
                    + "\nFAIL_REMOTE_CLEANUP=1\necho CLEANUP_FAILURE_ARMED\n",
                    remote_temp,
                    "remote-cleanup-failure-login-fixture.sh",
                )
                cleanup_failure_combined = cleanup_failure.stdout + cleanup_failure.stderr
                if (
                    cleanup_failure.returncode != 23
                    or "CLEANUP_FAILURE_ARMED" not in cleanup_failure_combined
                ):
                    failures.append(
                        "cleanup failure after successful remote command did not become rc=23:"
                        + str(cleanup_failure.returncode)
                        + ":"
                        + cleanup_failure_combined[-500:]
                    )
                cleanup_failure_reset = (
                    "#!/usr/bin/env bash\n"
                    "set -euo pipefail\n"
                    + "\n".join(
                        f"rm -rf -- '{path}'"
                        for path in (
                            received_zip_upload,
                            received_zip,
                            received_manifest_upload,
                            received_manifest,
                            received_dir,
                        )
                    )
                    + "\n"
                )
                cleanup_failure_reset_result = run_bash_fixture(
                    cleanup_failure_reset,
                    remote_temp,
                    "remote-cleanup-failure-fixture-reset.sh",
                )
                if cleanup_failure_reset_result.returncode != 0:
                    failures.append("cleanup-failure fixture reset left remote artifacts")

                original_failure_wins = run_bash_login_fixture(
                    copy_inputs
                    + mock_unzip
                    + "FAIL_REMOTE_CLEANUP=0\n"
                    + "rm() {\n"
                    + "  if [[ \"$FAIL_REMOTE_CLEANUP\" == \"1\" ]]; then return 23; fi\n"
                    + "  command rm \"$@\"\n"
                    + "}\n"
                    + prelude
                    + "\nFAIL_REMOTE_CLEANUP=1\necho ORIGINAL_FAILURE_ARMED\nfalse\n",
                    remote_temp,
                    "remote-original-failure-wins-login-fixture.sh",
                )
                original_failure_combined = (
                    original_failure_wins.stdout + original_failure_wins.stderr
                )
                if (
                    original_failure_wins.returncode != 1
                    or "ORIGINAL_FAILURE_ARMED" not in original_failure_combined
                ):
                    failures.append(
                        "cleanup failure overwrote original remote rc=1 with rc="
                        + str(original_failure_wins.returncode)
                        + ":"
                        + original_failure_combined[-500:]
                    )
                if "pop_var_context" in original_failure_combined:
                    failures.append("original failure triggered bash trap context corruption")
                original_failure_reset_result = run_bash_fixture(
                    cleanup_failure_reset,
                    remote_temp,
                    "remote-original-failure-fixture-reset.sh",
                )
                if original_failure_reset_result.returncode != 0:
                    failures.append("original-failure fixture reset left remote artifacts")

        duplicate_bundle = Path(temp_dir) / "duplicate-any-entry.zip"
        duplicate_files = {**validation_files, "notes.txt": b"first\n"}
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            with zipfile.ZipFile(duplicate_bundle, "w") as archive:
                for name, contents in duplicate_files.items():
                    archive.writestr(name, contents)
                archive.writestr("notes.txt", b"second\n")
        try:
            module.validate_zip(duplicate_bundle, allowed_files=set(duplicate_files))
        except (AttributeError, TypeError, ValueError) as exc:
            if "duplicate_entries" not in str(exc):
                failures.append(f"duplicate zip entry produced imprecise rejection:{exc}")
        else:
            failures.append("duplicate non-frontend zip entry was accepted")

        unexpected_bundle = Path(temp_dir) / "unexpected-entry.zip"
        with zipfile.ZipFile(unexpected_bundle, "w") as archive:
            for name, contents in validation_files.items():
                archive.writestr(name, contents)
            archive.writestr("unexpected.txt", b"not reviewed\n")
        try:
            module.validate_zip(unexpected_bundle, allowed_files=set(validation_files))
        except (AttributeError, TypeError, ValueError) as exc:
            if "bundle_whitelist_mismatch" not in str(exc):
                failures.append(f"non-whitelist entry produced imprecise rejection:{exc}")
        else:
            failures.append("non-whitelisted zip entry was accepted")

        unsafe_bundle = Path(temp_dir) / "unsafe-entry.zip"
        unsafe_files = {**validation_files, "../escape.txt": b"escape\n"}
        with zipfile.ZipFile(unsafe_bundle, "w") as archive:
            for name, contents in unsafe_files.items():
                archive.writestr(name, contents)
        try:
            module.validate_zip(unsafe_bundle, allowed_files=set(unsafe_files))
        except (AttributeError, TypeError, ValueError) as exc:
            if "unsafe_path:../escape.txt" not in str(exc):
                failures.append(f"traversal entry produced imprecise rejection:{exc}")
        else:
            failures.append("zip traversal entry was accepted")

        symlink_bundle = Path(temp_dir) / "symlink-entry.zip"
        symlink_files = {**validation_files, "frontend-link": b"app.js"}
        with zipfile.ZipFile(symlink_bundle, "w") as archive:
            for name, contents in validation_files.items():
                archive.writestr(name, contents)
            info = zipfile.ZipInfo("frontend-link")
            info.create_system = 3
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(info, b"app.js")
        try:
            module.validate_zip(symlink_bundle, allowed_files=set(symlink_files))
        except (AttributeError, TypeError, ValueError) as exc:
            if "symlink:frontend-link" not in str(exc):
                failures.append(f"symlink entry produced imprecise rejection:{exc}")
        else:
            failures.append("zip symlink entry was accepted")
    return failures


def validate_remote_stdout_contract() -> list[str]:
    module = load_deploy_module()
    failures: list[str] = []
    source_sha = "a" * 40
    dry_output = "\n".join(
        [
            "JIEJING_PRODUCTION_DEPLOY_DRY_RUN=1",
            f"SOURCE_COMMIT={source_sha}",
            "CANDIDATE_RELEASE_PERSISTED=0",
            "ACTIVE_SWITCHED=0",
            "PRIVATE_ENV_NORMALIZATION_REQUIRED=1",
            "PRIVATE_ENV_NORMALIZATION_PLANNED=1",
            "PRIVATE_ENV_NORMALIZATION_APPLIED=0",
            "EVIDENCE_SNAPSHOT_INITIALIZED=0",
            "OPS_PREVIOUS_RELEASE_SUPPORTED=0",
            "OPS_STORED_CERTIFICATE_PREFLIGHT=1",
            "OPS_LOCAL_TLS_ASSETS_ISOLATION_VERIFIED=0",
        ]
    )
    try:
        parsed = module.parse_remote_stdout_contract(dry_output, "dry_run", source_sha)
    except (AttributeError, TypeError, ValueError) as exc:
        return [f"dry-run stdout contract unavailable:{exc}"]
    expected = {
        "candidate_release_persisted": False,
        "active_switched": False,
        "private_env_normalization_required": True,
        "private_env_normalization_planned": True,
        "private_env_normalization_applied": False,
        "evidence_snapshot_initialized": False,
        "ops_previous_release_supported": False,
        "ops_stored_certificate_preflight": True,
        "ops_local_tls_assets_isolation_verified": False,
    }
    if parsed != expected:
        failures.append(f"dry-run stdout contract parsed incorrectly:{parsed}")
    for broken in (
        dry_output.replace("JIEJING_PRODUCTION_DEPLOY_DRY_RUN=1\n", ""),
        dry_output + "\nJIEJING_PRODUCTION_DEPLOY_DRY_RUN=1",
        dry_output + "\nJIEJING_PRODUCTION_DEPLOY_APPLIED=1",
        dry_output.replace(f"SOURCE_COMMIT={source_sha}", f"SOURCE_COMMIT={'b' * 40}"),
        dry_output.replace("ACTIVE_SWITCHED=0\n", ""),
        dry_output + "\nACTIVE_SWITCHED=1",
        dry_output.replace("PRIVATE_ENV_NORMALIZATION_REQUIRED=1", "PRIVATE_ENV_NORMALIZATION_REQUIRED=secret-value"),
        dry_output.replace("OPS_STORED_CERTIFICATE_PREFLIGHT=1", "OPS_STORED_CERTIFICATE_PREFLIGHT=0"),
        dry_output.replace("OPS_LOCAL_TLS_ASSETS_ISOLATION_VERIFIED=0", "OPS_LOCAL_TLS_ASSETS_ISOLATION_VERIFIED=1"),
    ):
        try:
            module.parse_remote_stdout_contract(broken, "dry_run", source_sha)
        except ValueError:
            continue
        failures.append("unsafe or incomplete dry-run stdout contract was accepted")
    apply_output = (
        dry_output
        .replace("JIEJING_PRODUCTION_DEPLOY_DRY_RUN=1", "JIEJING_PRODUCTION_DEPLOY_APPLIED=1")
        .replace("CANDIDATE_RELEASE_PERSISTED=0", "CANDIDATE_RELEASE_PERSISTED=1")
        .replace("ACTIVE_SWITCHED=0", "ACTIVE_SWITCHED=1")
        .replace("PRIVATE_ENV_NORMALIZATION_APPLIED=0", "PRIVATE_ENV_NORMALIZATION_APPLIED=1")
        .replace("EVIDENCE_SNAPSHOT_INITIALIZED=0", "EVIDENCE_SNAPSHOT_INITIALIZED=1")
        .replace("OPS_LOCAL_TLS_ASSETS_ISOLATION_VERIFIED=0", "OPS_LOCAL_TLS_ASSETS_ISOLATION_VERIFIED=1")
    ) + "\n" + commercial_report_fixture("ready")
    try:
        parsed_apply = module.parse_remote_stdout_contract(apply_output, "apply", source_sha)
    except ValueError as exc:
        failures.append(f"valid apply stdout contract rejected:{exc}")
    else:
        if not (
            parsed_apply["candidate_release_persisted"]
            and parsed_apply["active_switched"]
            and parsed_apply["private_env_normalization_applied"]
            and parsed_apply.get("evidence_snapshot_initialized") is True
            and parsed_apply.get("commercial_readiness", {}).get("status") == "ready"
        ):
            failures.append(f"apply stdout contract parsed incorrectly:{parsed_apply}")
    blocked_output = apply_output.replace(commercial_report_fixture("ready"), commercial_report_fixture("backup_restore"))
    try:
        blocked = module.parse_remote_stdout_contract(blocked_output, "apply", source_sha)
        if blocked.get("commercial_readiness") != {
            "contract_verified": True, "status": "blocked", "reason": "backup_restore",
            "blocker_count": 1, "warning_count": 0, "production_ready": False,
            "beta_ready": False, "can_accept_real_customers": False,
            "public_charging_allowed": True,
        }:
            failures.append("deployed receipt must preserve the commercial backup hold and charging configuration")
    except ValueError as exc:
        failures.append(f"valid blocked deployment receipt rejected:{exc}")
    for broken in (
        apply_output.replace(commercial_report_fixture("ready"), ""),
        blocked_output + "\nCOMMERCIAL_READINESS_STATUS=blocked",
        blocked_output + "\nCOMMERCIAL_UNKNOWN=synthetic",
        blocked_output.replace("COMMERCIAL_BLOCKER_COUNT=1", "COMMERCIAL_BLOCKER_COUNT=true"),
        blocked_output.replace("COMMERCIAL_PRODUCTION_READY=false", "COMMERCIAL_PRODUCTION_READY=true"),
        blocked_output.replace("COMMERCIAL_PUBLIC_CHARGING_ALLOWED=true", "COMMERCIAL_PUBLIC_CHARGING_ALLOWED=false"),
        blocked_output.replace("COMMERCIAL_READINESS_REASON=backup_restore", "COMMERCIAL_READINESS_REASON=unknown"),
    ):
        try:
            module.parse_remote_stdout_contract(broken, "apply", source_sha)
        except ValueError:
            continue
        failures.append("missing, conflicting or unknown commercial receipt was accepted")
    try:
        module.parse_remote_stdout_contract(dry_output + "\n" + commercial_report_fixture("ready"), "dry_run", source_sha)
    except ValueError:
        pass
    else:
        failures.append("dry-run must not claim a commercial readiness observation")
    try:
        module.parse_remote_stdout_contract(
            apply_output.replace("JIEJING_PRODUCTION_DEPLOY_APPLIED=1\n", ""),
            "apply",
            source_sha,
        )
    except ValueError:
        pass
    else:
        failures.append("apply stdout contract without exact apply receipt was accepted")
    try:
        module.parse_remote_stdout_contract(
            apply_output + "\nJIEJING_PRODUCTION_DEPLOY_DRY_RUN=1",
            "apply",
            source_sha,
        )
    except ValueError:
        pass
    else:
        failures.append("apply stdout contract with conflicting dry-run receipt was accepted")
    for broken in (
        apply_output.replace("EVIDENCE_SNAPSHOT_INITIALIZED=1", ""),
        apply_output.replace("EVIDENCE_SNAPSHOT_INITIALIZED=1", "EVIDENCE_SNAPSHOT_INITIALIZED=0"),
        apply_output + "\nEVIDENCE_SNAPSHOT_INITIALIZED=1",
    ):
        try:
            module.parse_remote_stdout_contract(broken, "apply", source_sha)
        except ValueError:
            continue
        failures.append("apply without one successful snapshot initialization was accepted")
    return failures


def validate_private_env_runtime_fixture(apply: str) -> list[str]:
    try:
        require_bash_contract()
    except RuntimeError as exc:
        return [str(exc)]
    try:
        functions = extract_bash_functions(
            apply,
            (
                "resolve_manifest_private_dir",
                "private_env_permissions_ready",
                "assess_private_env_normalization",
            ),
        )
    except ValueError as exc:
        return [f"private env normalization functions unavailable:{exc}"]
    failures: list[str] = []
    with tempfile.TemporaryDirectory(prefix="private-env-fixture-", dir=ROOT) as temp_dir:
        temp = Path(temp_dir)
        relative_temp = temp.relative_to(ROOT).as_posix()
        fixture = f"""#!/usr/bin/env bash
set -euo pipefail
{functions}
TEST_ROOT="$PWD/{relative_temp}"
PRODUCTION_ROOT="$TEST_ROOT/production"
RELEASE_ROOT="$PRODUCTION_ROOT/releases"
previous_release="$RELEASE_ROOT/current"
private_dir="$RELEASE_ROOT/private-owner/private"
COMPOSE_ENV="$private_dir/production-compose.env"
APP_ENV="$private_dir/jiejing-saas.production.env"
mkdir -p "$previous_release" "$private_dir"
printf 'SECRET_SENTINEL_COMPOSE' >"$COMPOSE_ENV"
printf 'SECRET_SENTINEL_APP' >"$APP_ENV"
printf 'PRIVATE_DIR=%s\n' "$private_dir" >"$previous_release/JIEJING_PRODUCTION_RELEASE_MANIFEST.txt"
environment_file="$COMPOSE_ENV"
resolve_manifest_private_dir "$previous_release" "$environment_file"
[[ "$private_dir" == "$RELEASE_ROOT/private-owner/private" ]]

ln -s "$RELEASE_ROOT/private-owner/private" "$RELEASE_ROOT/symlink-private"
printf 'PRIVATE_DIR=%s\n' "$RELEASE_ROOT/symlink-private" >"$previous_release/JIEJING_PRODUCTION_RELEASE_MANIFEST.txt"
set +e
resolve_manifest_private_dir "$previous_release" "$environment_file" >/dev/null 2>&1
symlink_rc=$?
set -e
[[ "$symlink_rc" != "0" ]]

outside="$TEST_ROOT/outside/private"
mkdir -p "$outside"
printf 'PRIVATE_DIR=%s\n' "$outside" >"$previous_release/JIEJING_PRODUCTION_RELEASE_MANIFEST.txt"
set +e
resolve_manifest_private_dir "$previous_release" "$environment_file" >/dev/null 2>&1
outside_rc=$?
set -e
[[ "$outside_rc" != "0" ]]

nested="$RELEASE_ROOT/nested/extra/private"
mkdir -p "$nested"
printf 'SECRET_SENTINEL_COMPOSE' >"$nested/production-compose.env"
printf 'SECRET_SENTINEL_APP' >"$nested/jiejing-saas.production.env"
printf 'PRIVATE_DIR=%s\n' "$nested" >"$previous_release/JIEJING_PRODUCTION_RELEASE_MANIFEST.txt"
set +e
resolve_manifest_private_dir "$previous_release" "$nested/production-compose.env" >/dev/null 2>&1
nested_rc=$?
set -e
[[ "$nested_rc" != "0" ]]

printf 'PRIVATE_DIR=%s\nPRIVATE_DIR=%s\n' "$RELEASE_ROOT/private-owner/private" "$RELEASE_ROOT/private-owner/private" >"$previous_release/JIEJING_PRODUCTION_RELEASE_MANIFEST.txt"
set +e
resolve_manifest_private_dir "$previous_release" "$environment_file" >/dev/null 2>&1
duplicate_rc=$?
set -e
[[ "$duplicate_rc" != "0" ]]

printf 'PRIVATE_DIR=%s\n' "$RELEASE_ROOT/private-owner/private" >"$previous_release/JIEJING_PRODUCTION_RELEASE_MANIFEST.txt"
resolve_manifest_private_dir "$previous_release" "$environment_file"
FAKE_PRIVATE_OWNER=ubuntu:ubuntu
stat() {{
  if [[ "$*" == *"$private_dir"* ]]; then
    case "$*" in
      *production-compose.env*|*jiejing-saas.production.env*) printf '%s\n' "$FAKE_PRIVATE_OWNER 600" ;;
      *) printf '%s\n' "$FAKE_PRIVATE_OWNER 700" ;;
    esac
    return 0
  fi
  command stat "$@"
}}
private_env_normalization_required=0
assess_private_env_normalization >"$TEST_ROOT/assessment.out"
output="$(<"$TEST_ROOT/assessment.out")"
[[ "$private_env_normalization_required" == "1" ]]
[[ "$output" == *"PRIVATE_ENV_NORMALIZATION_REQUIRED=1"* ]]
[[ "$output" == *"PRIVATE_ENV_NORMALIZATION_PLANNED=1"* ]]
[[ "$output" != *"SECRET_SENTINEL"* ]]
FAKE_PRIVATE_OWNER=root:root
private_env_normalization_required=1
assess_private_env_normalization >"$TEST_ROOT/assessment.out"
output="$(<"$TEST_ROOT/assessment.out")"
[[ "$private_env_normalization_required" == "0" ]]
[[ "$output" == *"PRIVATE_ENV_NORMALIZATION_REQUIRED=0"* ]]
[[ "$output" == *"PRIVATE_ENV_NORMALIZATION_PLANNED=0"* ]]
printf '%s\n' PRIVATE_ENV_FIXTURE_PASS
"""
        result = run_bash_fixture(fixture, temp, "private-env-runtime.sh")
        if result.returncode != 0 or "PRIVATE_ENV_FIXTURE_PASS" not in result.stdout:
            failures.append(
                "private env runtime fixture failed rc="
                + str(result.returncode)
                + " stdout="
                + result.stdout[-1000:]
                + " stderr="
                + result.stderr[-1000:]
            )
    return failures


def validate_application_rollback_runtime_fixture(apply: str) -> list[str]:
    try:
        require_bash_contract()
    except RuntimeError as exc:
        return [str(exc)]
    try:
        functions = extract_bash_functions(
            apply,
            (
                "build_candidate_images_with_retry",
                "image_ref_id",
                "remove_image_ref_if_present",
                "discard_prior_rollback_hold_backups",
                "prepare_prior_rollback_hold_backups",
                "restore_prior_rollback_image_holds",
                "capture_previous_runtime_images",
                "capture_candidate_runtime_images",
                "verify_runtime_labels_and_health",
                "verify_candidate_runtime_image_coherence",
                "atomic_replace_active_link",
                "verify_previous_runtime_restored",
                "rollback_application_release",
            ),
        )
    except ValueError as exc:
        return [f"application rollback functions unavailable:{exc}"]
    failures: list[str] = []
    with tempfile.TemporaryDirectory(prefix="application-rollback-fixture-", dir=ROOT) as temp_dir:
        temp = Path(temp_dir)
        relative_temp = temp.relative_to(ROOT).as_posix()
        fixture = f"""#!/usr/bin/env bash
set -euo pipefail
{functions}
TEST_ROOT="$PWD/{relative_temp}"
active_app="$TEST_ROOT/old/app"
candidate_app="$TEST_ROOT/new/app"
ACTIVE_LINK="$TEST_ROOT/active"
environment_file="$TEST_ROOT/private/production-compose.env"
mkdir -p "$active_app/deploy" "$candidate_app/deploy" "$(dirname "$environment_file")"
touch "$active_app/deploy/docker-compose.production-pilot.yml"
touch "$candidate_app/deploy/docker-compose.production-pilot.yml" "$environment_file"
ln -s "$active_app" "$ACTIVE_LINK"
old_api="sha256:$(printf 'a%.0s' {{1..64}})"
old_worker="sha256:$(printf 'b%.0s' {{1..64}})"
new_api="sha256:$(printf 'c%.0s' {{1..64}})"
new_worker="sha256:$(printf 'd%.0s' {{1..64}})"
manual_api="sha256:$(printf 'e%.0s' {{1..64}})"
manual_worker="sha256:$(printf 'f%.0s' {{1..64}})"
ROLLBACK_API_HOLD_REF=jiejing-production-rollback-api:previous
ROLLBACK_WORKER_HOLD_REF=jiejing-production-rollback-worker:previous
ROLLBACK_API_HOLD_BACKUP_REF=jiejing-production-rollback-api:capture-backup
ROLLBACK_WORKER_HOLD_BACKUP_REF=jiejing-production-rollback-worker:capture-backup
declare -A IMAGE_EXISTS REF_TO_ID CONTAINER_IMAGE CONTAINER_APP
FAIL_HOLD_REF=""
FAIL_BUILD=0
BUILD_CALLS=0
REQUIRE_HOLD_SOURCE=0

resolve_image() {{
  local source="$1"
  if [[ "${{IMAGE_EXISTS[$source]:-0}}" == "1" ]]; then
    printf '%s\n' "$source"
    return 0
  fi
  local id="${{REF_TO_ID[$source]:-}}"
  [[ -n "$id" && "${{IMAGE_EXISTS[$id]:-0}}" == "1" ]] || return 1
  printf '%s\n' "$id"
}}

garbage_collect_images() {{
  local id ref container referenced
  for id in "${{!IMAGE_EXISTS[@]}}"; do
    referenced=0
    for ref in "${{!REF_TO_ID[@]}}"; do
      [[ "${{REF_TO_ID[$ref]}}" == "$id" ]] && referenced=1
    done
    for container in "${{!CONTAINER_IMAGE[@]}}"; do
      [[ "${{CONTAINER_IMAGE[$container]}}" == "$id" ]] && referenced=1
    done
    [[ "$referenced" == "1" ]] || unset 'IMAGE_EXISTS[$id]'
  done
}}

reset_store() {{
  IMAGE_EXISTS=([$old_api]=1 [$old_worker]=1)
  REF_TO_ID=([deploy-jiejing-saas]="$old_api" [deploy-jiejing-worker]="$old_worker")
  CONTAINER_IMAGE=([deploy-jiejing-saas-1]="$old_api" [deploy-jiejing-worker-1]="$old_worker")
  CONTAINER_APP=([deploy-jiejing-saas-1]="$active_app" [deploy-jiejing-worker-1]="$active_app")
  FAIL_HOLD_REF=""
  FAIL_BUILD=0
  BUILD_CALLS=0
  REQUIRE_HOLD_SOURCE=0
  previous_api_image_id=""
  previous_worker_image_id=""
  previous_api_image_ref=""
  previous_worker_image_ref=""
  candidate_api_image_id=""
  candidate_worker_image_id=""
}}

docker() {{
  if [[ "${{1:-}} ${{2:-}}" == "image inspect" ]]; then
    local id
    id="$(resolve_image "${{3:-}}")" || return 1
    if [[ "${{4:-}}" == "--format" ]]; then printf '%s\n' "$id"; fi
    return 0
  fi
  if [[ "${{1:-}} ${{2:-}}" == "image tag" ]]; then
    local source="${{3:-}}" id destination="${{4:-}}"
    [[ "$destination" != "$FAIL_HOLD_REF" ]] || return 9
    if [[ "$REQUIRE_HOLD_SOURCE" == "1" \
      && ( "$source" == "$old_api" || "$source" == "$old_worker" ) ]]; then
      return 8
    fi
    id="$(resolve_image "$source")" || return 1
    REF_TO_ID[$destination]="$id"
    garbage_collect_images
    return 0
  fi
  if [[ "${{1:-}} ${{2:-}}" == "image rm" ]]; then
    unset 'REF_TO_ID[${{3:-}}]'
    garbage_collect_images
    return 0
  fi
  [[ "${{1:-}}" == inspect ]] || return 2
  local container="${{2:-}}" format="${{4:-}}" image ref app
  image="${{CONTAINER_IMAGE[$container]:-}}"
  app="${{CONTAINER_APP[$container]:-}}"
  [[ -n "$image" && "${{IMAGE_EXISTS[$image]:-0}}" == "1" ]] || return 1
  if [[ "$container" == deploy-jiejing-saas-1 ]]; then ref=deploy-jiejing-saas; else ref=deploy-jiejing-worker; fi
  case "$format" in
    '{{{{.Image}}}}') printf '%s\n' "$image" ;;
    '{{{{.Config.Image}}}}') printf '%s\n' "$ref" ;;
    '{{{{.State.Status}}}}') printf '%s\n' running ;;
    '{{{{if .State.Health}}}}{{{{.State.Health.Status}}}}{{{{else}}}}none{{{{end}}}}') printf '%s\n' healthy ;;
    *config_files*) printf '%s\n' "$app/deploy/docker-compose.production-pilot.yml" ;;
    *working_dir*) printf '%s\n' "$app/deploy" ;;
    *environment_file*) printf '%s\n' "$environment_file" ;;
    *) return 3 ;;
  esac
}}

fake_candidate_compose() {{
  local action="${{1:-}}" service="${{@: -1}}" id
  if [[ "$action" == build ]]; then
    BUILD_CALLS=$((BUILD_CALLS + 1))
    IMAGE_EXISTS[$new_api]=1
    REF_TO_ID[deploy-jiejing-saas]="$new_api"
    if [[ "$FAIL_BUILD" == "1" ]]; then return 7; fi
    IMAGE_EXISTS[$new_worker]=1
    REF_TO_ID[deploy-jiejing-worker]="$new_worker"
    return 0
  fi
  [[ "$action" == up ]] || return 2
  id="$(resolve_image "deploy-${{service}}")" || return 1
  CONTAINER_IMAGE["deploy-${{service}}-1"]="$id"
  CONTAINER_APP["deploy-${{service}}-1"]="$candidate_app"
  garbage_collect_images
}}

fake_previous_compose() {{
  local service="${{@: -1}}"
  local id
  case "$service" in
    jiejing-saas) id="$(resolve_image deploy-jiejing-saas)" ;;
    jiejing-worker) id="$(resolve_image deploy-jiejing-worker)" ;;
    *) return 0 ;;
  esac
  CONTAINER_IMAGE["deploy-${{service}}-1"]="$id"
  CONTAINER_APP["deploy-${{service}}-1"]="$active_app"
  garbage_collect_images
}}
candidate_compose=(fake_candidate_compose)
previous_compose=(fake_previous_compose)
previous_ops_supported=1
wait_container_healthy() {{ return 0; }}
wait_public_json() {{ return 0; }}
stop_candidate_ops_if_owned() {{ return 0; }}
ops_dns_points_to_old_host() {{ return 0; }}
verify_ops_surface() {{ return 0; }}

# Happy path: service-specific candidate images are valid, while fixed holds
# keep both different previous images restorable after live tags/containers move.
reset_store
capture_previous_runtime_images
[[ "${{REF_TO_ID[$ROLLBACK_API_HOLD_REF]:-}}" == "$old_api" ]]
[[ "${{REF_TO_ID[$ROLLBACK_WORKER_HOLD_REF]:-}}" == "$old_worker" ]]
build_candidate_images_with_retry
capture_candidate_runtime_images
[[ "$candidate_api_image_id" == "$new_api" && "$candidate_worker_image_id" == "$new_worker" ]]
[[ "$candidate_api_image_id" != "$candidate_worker_image_id" ]]
fake_candidate_compose up -d --no-deps jiejing-saas
fake_candidate_compose up -d --no-deps jiejing-worker
verify_candidate_runtime_image_coherence >"$TEST_ROOT/coherence.out"
coherence_output="$(<"$TEST_ROOT/coherence.out")"
[[ "$coherence_output" == CANDIDATE_RUNTIME_IMAGE_COHERENCE=verified ]]
REQUIRE_HOLD_SOURCE=1
rollback_application_release
[[ "$(readlink -f -- "$ACTIVE_LINK")" == "$active_app" ]]
[[ "${{CONTAINER_IMAGE[deploy-jiejing-saas-1]}}" == "$old_api" ]]
[[ "${{CONTAINER_IMAGE[deploy-jiejing-worker-1]}}" == "$old_worker" ]]
verify_previous_runtime_restored

# A partially-created hold pair must be undone before any build/container work.
reset_store
FAIL_HOLD_REF="$ROLLBACK_WORKER_HOLD_REF"
set +e
capture_previous_runtime_images
hold_failure_rc=$?
set -e
[[ "$hold_failure_rc" != "0" && "$BUILD_CALLS" == "0" ]]
[[ -z "${{REF_TO_ID[$ROLLBACK_API_HOLD_REF]:-}}" && -z "${{REF_TO_ID[$ROLLBACK_WORKER_HOLD_REF]:-}}" ]]
[[ "${{CONTAINER_IMAGE[deploy-jiejing-saas-1]}}" == "$old_api" ]]
[[ "${{CONTAINER_IMAGE[deploy-jiejing-worker-1]}}" == "$old_worker" ]]

# Updating an existing manual rollback pair must also be all-or-nothing. The
# fake store immediately collects an overwritten, otherwise-unreferenced hold.
reset_store
IMAGE_EXISTS[$manual_api]=1
IMAGE_EXISTS[$manual_worker]=1
REF_TO_ID[$ROLLBACK_API_HOLD_REF]="$manual_api"
REF_TO_ID[$ROLLBACK_WORKER_HOLD_REF]="$manual_worker"
FAIL_HOLD_REF="$ROLLBACK_WORKER_HOLD_REF"
set +e
capture_previous_runtime_images
existing_hold_failure_rc=$?
set -e
[[ "$existing_hold_failure_rc" != "0" ]]
[[ "${{REF_TO_ID[$ROLLBACK_API_HOLD_REF]:-}}" == "$manual_api" ]]
[[ "${{REF_TO_ID[$ROLLBACK_WORKER_HOLD_REF]:-}}" == "$manual_worker" ]]
[[ "${{IMAGE_EXISTS[$manual_api]:-0}}" == "1" && "${{IMAGE_EXISTS[$manual_worker]:-0}}" == "1" ]]

# A partial build failure remains exactly recoverable through the holds.
reset_store
capture_previous_runtime_images
FAIL_BUILD=1
set +e
build_candidate_images_with_retry
partial_build_rc=$?
set -e
[[ "$partial_build_rc" != "0" ]]
rollback_application_release
verify_previous_runtime_restored

# Mutation guard: deleting either hold makes the simulated image store collect
# that old image when candidate containers replace the last live references.
for missing_hold in "$ROLLBACK_API_HOLD_REF" "$ROLLBACK_WORKER_HOLD_REF"; do
  reset_store
  capture_previous_runtime_images
  unset 'REF_TO_ID[$missing_hold]'
  build_candidate_images_with_retry
  capture_candidate_runtime_images
  fake_candidate_compose up -d --no-deps jiejing-saas
  fake_candidate_compose up -d --no-deps jiejing-worker
  before_failed_rollback_api="${{CONTAINER_IMAGE[deploy-jiejing-saas-1]}}"
  before_failed_rollback_worker="${{CONTAINER_IMAGE[deploy-jiejing-worker-1]}}"
  set +e
  rollback_application_release
  missing_hold_rc=$?
  set -e
  [[ "$missing_hold_rc" != "0" ]]
  [[ "${{CONTAINER_IMAGE[deploy-jiejing-saas-1]}}" == "$before_failed_rollback_api" ]]
  [[ "${{CONTAINER_IMAGE[deploy-jiejing-worker-1]}}" == "$before_failed_rollback_worker" ]]
  [[ "${{CONTAINER_APP[deploy-jiejing-saas-1]}}" == "$candidate_app" ]]
  [[ "${{CONTAINER_APP[deploy-jiejing-worker-1]}}" == "$candidate_app" ]]
done

printf '%s\n' APPLICATION_ROLLBACK_FIXTURE_PASS
"""
        result = run_bash_fixture(fixture, temp, "application-rollback-runtime.sh")
        if result.returncode != 0 or "APPLICATION_ROLLBACK_FIXTURE_PASS" not in result.stdout:
            failures.append(
                "application rollback runtime fixture failed rc="
                + str(result.returncode)
                + " stdout="
                + result.stdout[-1000:]
                + " stderr="
                + result.stderr[-1000:]
            )
    return failures


def validate_finalization_lock_runtime_fixture(apply: str) -> list[str]:
    try:
        require_bash_contract()
    except RuntimeError as exc:
        return [str(exc)]
    try:
        function = extract_bash_functions(
            apply, ("finalize_evidence_refresh_transaction",)
        )
    except ValueError as exc:
        return [f"evidence refresh finalization function unavailable:{exc}"]
    failures: list[str] = []
    with tempfile.TemporaryDirectory(prefix="finalization-lock-fixture-", dir=ROOT) as temp_dir:
        temp = Path(temp_dir)
        relative_temp = temp.relative_to(ROOT).as_posix()
        fixture = f"""#!/usr/bin/env bash
set -euo pipefail
{function}
TEST_ROOT="$PWD/{relative_temp}"
CALL_LOG="$TEST_ROOT/calls.log"
deploy_lock_held=1
maintenance_lock_held=0
current_stage=fixture
FAIL_ACQUIRE=0
acquire_maintenance_lock() {{
  [[ "$deploy_lock_held" == "1" && "$maintenance_lock_held" == "0" ]]
  if [[ "$FAIL_ACQUIRE" == "1" ]]; then
    printf '%s\n' ACQUIRE_MAINTENANCE_FAILED >>"$CALL_LOG"
    return 1
  fi
  printf '%s\n' ACQUIRE_MAINTENANCE >>"$CALL_LOG"
  maintenance_lock_held=1
}}
verify_candidate_runtime_image_coherence() {{
  [[ "$deploy_lock_held" == "1" && "$maintenance_lock_held" == "1" ]]
  printf '%s\n' VERIFY_COHERENCE >>"$CALL_LOG"
}}
start_and_verify_evidence_refresh_timer() {{
  [[ "$deploy_lock_held" == "1" && "$maintenance_lock_held" == "1" ]]
  printf '%s\n' VERIFY_TIMER >>"$CALL_LOG"
}}
release_maintenance_lock() {{
  [[ "$deploy_lock_held" == "1" && "$maintenance_lock_held" == "1" ]]
  printf '%s\n' RELEASE_MAINTENANCE >>"$CALL_LOG"
  maintenance_lock_held=0
}}
finalize_evidence_refresh_transaction
[[ "$maintenance_lock_held" == "0" && "$deploy_lock_held" == "1" ]]
printf '%s\n' ACQUIRE_MAINTENANCE VERIFY_COHERENCE VERIFY_TIMER RELEASE_MAINTENANCE >"$TEST_ROOT/expected.log"
cmp -s "$TEST_ROOT/expected.log" "$CALL_LOG"
: >"$CALL_LOG"
FAIL_ACQUIRE=1
set +e
finalize_evidence_refresh_transaction
failure_rc=$?
set -e
[[ "$failure_rc" != "0" && "$maintenance_lock_held" == "0" ]]
printf '%s\n' ACQUIRE_MAINTENANCE_FAILED >"$TEST_ROOT/expected-failure.log"
cmp -s "$TEST_ROOT/expected-failure.log" "$CALL_LOG"
printf '%s\n' FINALIZATION_LOCK_FIXTURE_PASS
"""
        result = run_bash_fixture(fixture, temp, "finalization-lock-runtime.sh")
        if result.returncode != 0 or "FINALIZATION_LOCK_FIXTURE_PASS" not in result.stdout:
            failures.append(
                "evidence refresh finalization lock fixture failed rc="
                + str(result.returncode)
                + " stdout="
                + result.stdout[-1000:]
                + " stderr="
                + result.stderr[-1000:]
            )
    return failures


def extract_bash_functions(source: str, names: tuple[str, ...]) -> str:
    matches = list(re.finditer(r"(?m)^([a-zA-Z_][a-zA-Z0-9_]*)\(\) \{\n", source))
    by_name = {match.group(1): match for match in matches}
    extracted: list[str] = []
    for name in names:
        if name not in by_name:
            raise ValueError(f"missing bash function:{name}")
        match = by_name[name]
        closing = re.search(r"(?m)^}\r?$", source[match.end() :])
        if closing is None:
            raise ValueError(f"unterminated bash function:{name}")
        end = match.end() + closing.end()
        extracted.append(source[match.start() : end].rstrip())
    return "\n\n".join(extracted) + "\n"


def run_bash_fixture(script: str, temp: Path, name: str) -> subprocess.CompletedProcess[str]:
    bash_executable = require_bash_contract()
    harness = temp / name
    harness.write_text(script, encoding="utf-8", newline="\n")
    try:
        harness.chmod(0o755)
    except OSError:
        pass
    relative = harness.relative_to(ROOT).as_posix()
    return subprocess.run(
        [bash_executable, relative],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
        timeout=30,
    )


def run_bash_login_fixture(
    script: str, temp: Path, name: str
) -> subprocess.CompletedProcess[str]:
    payload = temp / f"{name}.payload"
    payload.write_text(script, encoding="utf-8", newline="\n")
    relative_payload = payload.relative_to(ROOT).as_posix()
    return run_bash_fixture(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f"payload=\"$(cat -- '{relative_payload}')\"\n"
        "bash -lc \"$payload\"\n",
        temp,
        name,
    )


def fixture_bash_path_exists(path: str, temp: Path, name: str) -> bool:
    if re.fullmatch(r"/tmp/jiejing-production-dry-run-[A-Za-z0-9]{8}\.d", path) is None:
        return False
    result = run_bash_fixture(
        f"""#!/usr/bin/env bash
set -euo pipefail
candidate='{path}'
[[ -e "$candidate" || -L "$candidate" ]]
""",
        temp,
        name,
    )
    return result.returncode == 0


def cleanup_fixture_bash_path(
    path: str, temp: Path, name: str
) -> subprocess.CompletedProcess[str]:
    if re.fullmatch(r"/tmp/jiejing-production-dry-run-[A-Za-z0-9]{8}\.d", path) is None:
        return subprocess.CompletedProcess(["bash", name], 2, "", "invalid fixture path")
    return run_bash_fixture(
        f"""#!/usr/bin/env bash
set -euo pipefail
candidate='{path}'
case "$candidate" in
  /tmp/jiejing-production-dry-run-????????.d) ;;
  *) exit 2 ;;
esac
resolved="$(readlink -f -- "$candidate" 2>/dev/null || true)"
owner="$(stat -c %u -- "$candidate" 2>/dev/null || true)"
[[ "$resolved" == "$candidate" && -d "$resolved" && ! -L "$resolved" ]]
[[ "$owner" == "$(id -u)" ]]
rm -rf --one-file-system -- "$resolved"
[[ ! -e "$resolved" && ! -L "$resolved" ]]
""",
        temp,
        name,
    )


def commercial_report_fixture(outcome: str) -> str:
    states = {
        "ready": ("ready", "none", "0", "0", "true", "true", "true", "true"),
        "backup_restore": ("blocked", "backup_restore", "1", "0", "false", "false", "false", "true"),
        "billing_quota": ("blocked", "billing_quota", "0", "1", "false", "true", "false", "false"),
    }
    fields = ("COMMERCIAL_READINESS_STATUS", "COMMERCIAL_READINESS_REASON",
              "COMMERCIAL_BLOCKER_COUNT", "COMMERCIAL_WARNING_COUNT",
              "COMMERCIAL_PRODUCTION_READY", "COMMERCIAL_BETA_READY",
              "COMMERCIAL_CAN_ACCEPT_REAL_CUSTOMERS", "COMMERCIAL_PUBLIC_CHARGING_ALLOWED")
    return "PUBLIC_READINESS_CONTRACT_STATUS=verified\n" + "\n".join(
        f"{key}={value}" for key, value in zip(fields, states[outcome], strict=True)
    )


def evidence_journal_fixture(outcome: str) -> str:
    return "\n".join((
        "LIVE_RELEASE_GUARD_STATUS=ready", "COS_PROBE_STATUS=verified",
        "PROVIDER_ALARM_STATUS=verified", "CLS_PROBE_STATUS=verified",
        "RUNTIME_EVIDENCE_SNAPSHOT_STATUS=verified",
        "API_RUNTIME_STATUS=unchanged", "WORKER_RUNTIME_STATUS=unchanged",
        "API_RUNTIME_STATUS=unchanged", "WORKER_RUNTIME_STATUS=unchanged",
        commercial_report_fixture(outcome),
        "JIEJING_PRODUCTION_EVIDENCE_REFRESH_STATUS=success", "SECRET_EXPOSED=false",
    ))


def run_first_oneshot_fixture(apply: str, journal: str, *, start_rc: int = 0,
                              result: str = "success", status: str = "0",
                              after_id: str = "b" * 32) -> subprocess.CompletedProcess[str]:
    names = ["verify_first_evidence_refresh_oneshot"]
    if "verify_evidence_refresh_journal()" in apply:
        names.insert(0, "verify_evidence_refresh_journal")
    functions = extract_bash_functions(apply, tuple(names))
    script = f'''set -euo pipefail
{functions}
EVIDENCE_REFRESH_SERVICE=fixture.service
STARTED=0
JOURNAL={shlex.quote(journal)}
systemctl() {{
  if [[ "$1" == start ]]; then STARTED=1; return {start_rc}; fi
  case "$*" in
    *InvocationID*) if [[ "$STARTED" == 0 ]]; then printf '%s\\n' {'a' * 32}; else printf '%s\\n' {shlex.quote(after_id)}; fi ;;
    *ExecMainStatus*) printf '%s\\n' {shlex.quote(status)} ;;
    *Result*) printf '%s\\n' {shlex.quote(result)} ;;
    *) return 91 ;;
  esac
}}
journalctl() {{
  [[ "$1" == '_SYSTEMD_INVOCATION_ID={after_id}' ]] || return 92
  printf '%s\\n' "$JOURNAL"
}}
sleep() {{ :; }}
verify_first_evidence_refresh_oneshot
printf '%s\\n' "${{FIRST_ONESHOT_READINESS_REPORT:-}}"
'''
    completed = subprocess.run([require_bash_contract(), "-s"], cwd=ROOT,
                               input=script.encode("utf-8"), capture_output=True,
                               check=False, timeout=30)
    return subprocess.CompletedProcess(
        completed.args, completed.returncode,
        completed.stdout.decode("utf-8", errors="replace"),
        completed.stderr.decode("utf-8", errors="replace"),
    )


def validate_first_oneshot_classification(apply: str) -> list[str]:
    failures = []
    legacy_journal = "JIEJING_PRODUCTION_EVIDENCE_REFRESH_STATUS=success\nSECRET_EXPOSED=false"
    missing = run_first_oneshot_fixture(apply, legacy_journal)
    if missing.returncode == 0:
        return ["first oneshot must reject success without a verified commercial classification"]
    for outcome in ("ready", "backup_restore", "billing_quota"):
        accepted = run_first_oneshot_fixture(apply, evidence_journal_fixture(outcome))
        if accepted.returncode != 0 or accepted.stdout.strip() != commercial_report_fixture(outcome):
            failures.append(f"first oneshot must preserve verified {outcome}: exit_{accepted.returncode}")
    valid = evidence_journal_fixture("backup_restore")
    invalid = [
        ("missing collection", valid.replace("COS_PROBE_STATUS=verified\n", "")),
        ("missing snapshot", valid.replace("RUNTIME_EVIDENCE_SNAPSHOT_STATUS=verified\n", "")),
        ("missing final runtime", valid.replace("API_RUNTIME_STATUS=unchanged\n", "", 1)),
        ("duplicate success", valid + "\nJIEJING_PRODUCTION_EVIDENCE_REFRESH_STATUS=success"),
        ("skipped", valid + "\nJIEJING_PRODUCTION_EVIDENCE_REFRESH_STATUS=skipped"),
        ("refresh failure", valid + "\nJIEJING_PRODUCTION_EVIDENCE_REFRESH_BLOCKER=runtime_identity_changed"),
        ("duplicate classification", valid + "\nCOMMERCIAL_READINESS_STATUS=blocked"),
        ("unknown classification", valid.replace("COMMERCIAL_READINESS_REASON=backup_restore", "COMMERCIAL_READINESS_REASON=unknown")),
        ("false admission", valid.replace("COMMERCIAL_PRODUCTION_READY=false", "COMMERCIAL_PRODUCTION_READY=true")),
        ("wrong count", valid.replace("COMMERCIAL_BLOCKER_COUNT=1", "COMMERCIAL_BLOCKER_COUNT=0")),
        ("missing safety", valid.replace("SECRET_EXPOSED=false", "")),
        ("unsafe marker", valid + "\nSECRET_EXPOSED=true"),
        ("unknown commercial field", valid + "\nCOMMERCIAL_UNKNOWN=synthetic"),
    ]
    for label, journal in invalid:
        rejected = run_first_oneshot_fixture(apply, journal)
        if rejected.returncode == 0 or rejected.stdout.strip():
            failures.append(f"first oneshot must silently reject {label}")
    for label, kwargs in (
        ("service start failed", {"start_rc": 2}),
        ("exit two", {"status": "2", "result": "exit-code"}),
        ("failed result", {"result": "failed"}),
        ("same invocation", {"after_id": "a" * 32}),
        ("invalid invocation", {"after_id": "unknown"}),
    ):
        if run_first_oneshot_fixture(apply, valid, **kwargs).returncode == 0:
            failures.append(f"first oneshot must reject {label}")
    return failures


def validate_bash_runtime_fixture(apply: str) -> list[str]:
    try:
        require_bash_contract()
    except RuntimeError as exc:
        return [str(exc)]
    failures: list[str] = []
    functions = extract_bash_functions(
        apply,
        (
            "refuse",
            "require_flock",
            "acquire_deploy_lock",
            "restore_root_file",
            "restore_evidence_refresh_units",
            "restore_evidence_refresh_timer_activity",
            "verify_no_evidence_refresh_dropins",
            "create_dry_run_candidate",
            "cleanup_dry_run_candidate",
            "dry_run_cleanup_handler",
            "arm_dry_run_cleanup_traps",
        ),
    )
    with tempfile.TemporaryDirectory(
        prefix="phase3-bash-fixture-", dir=ROOT
    ) as temp_dir:
        temp = Path(temp_dir)
        relative_temp = temp.relative_to(ROOT).as_posix()
        helper_probe = run_bash_fixture(
            """#!/usr/bin/env bash
set -euo pipefail
probe="$(mktemp -d --tmpdir=/tmp 'jiejing-production-dry-run-XXXXXXXX.d')"
printf 'HELPER_PROBE=%s\n' "$probe"
""",
            temp,
            "path-helper-probe.sh",
        )
        helper_matches = re.findall(
            r"/tmp/jiejing-production-dry-run-[^/\r\n]{8}\.d",
            helper_probe.stdout,
        )
        helper_candidate = helper_matches[-1] if helper_matches else ""
        if not helper_candidate:
            failures.append("cross-WSL path helper probe did not create a candidate")
        elif not fixture_bash_path_exists(
            helper_candidate, temp, "path-helper-exists.sh"
        ):
            failures.append("cross-WSL path exists helper returned a false negative")
        if helper_candidate:
            helper_cleanup = cleanup_fixture_bash_path(
                helper_candidate, temp, "path-helper-cleanup.sh"
            )
            if helper_cleanup.returncode != 0:
                failures.append(
                    "cross-WSL cleanup helper failed rc="
                    + str(helper_cleanup.returncode)
                    + " stderr="
                    + helper_cleanup.stderr[-500:]
                )
            if fixture_bash_path_exists(
                helper_candidate, temp, "path-helper-absent.sh"
            ):
                failures.append("cross-WSL cleanup helper did not remove its probe")
        fixture = f"""#!/usr/bin/env bash
set -euo pipefail
{functions}
TEST_ROOT="$PWD/{relative_temp}"
CALL_LOG="$TEST_ROOT/systemctl.log"
DEPLOY_LOCK="$TEST_ROOT/deploy.lock"
deploy_lock_held=0
FAKE_FLOCK_RC=0
FAKE_ENABLED_STATE=disabled
FAKE_ACTIVE_STATE=inactive
FAKE_SERVICE_DROPIN_PROPERTY="DropInPaths="
FAKE_TIMER_DROPIN_PROPERTY="DropInPaths="
flock() {{
  if [[ "${{1:-}}" == "-n" ]]; then return "$FAKE_FLOCK_RC"; fi
  return 0
}}
systemctl() {{
  printf 'SYSTEMCTL:%s\n' "$*" >>"$CALL_LOG"
  if [[ "$*" == *"-p DropInPaths"* ]]; then
    case "${{2:-}}" in
      refresh.service) printf '%s\n' "$FAKE_SERVICE_DROPIN_PROPERTY" ;;
      refresh.timer) printf '%s\n' "$FAKE_TIMER_DROPIN_PROPERTY" ;;
      *) return 3 ;;
    esac
    return 0
  fi
  case "${{1:-}}" in
    is-enabled) printf '%s\n' "$FAKE_ENABLED_STATE" ;;
    is-active) printf '%s\n' "$FAKE_ACTIVE_STATE" ;;
  esac
  return 0
}}

set +e
lock_busy_output="$(FAKE_FLOCK_RC=1 acquire_deploy_lock 2>&1)"
lock_busy_rc=$?
lock_error_output="$(FAKE_FLOCK_RC=7 acquire_deploy_lock 2>&1)"
lock_error_rc=$?
set -e
[[ "$lock_busy_rc" == "34" && "$lock_busy_output" == *"REFUSE_PRODUCTION_DEPLOY_LOCK_BUSY=1"* ]]
[[ "$lock_error_rc" == "35" && "$lock_error_output" == *"REFUSE_LOCK_ACQUIRE_FAILED=deploy:7"* ]]

: >"$CALL_LOG"
unit_snapshot_complete=0
unit_mutation_started=0
restore_evidence_refresh_units
[[ ! -s "$CALL_LOG" ]]

first="$TEST_ROOT/first"
mkdir -p "$first/backups"
EVIDENCE_REFRESH_WRAPPER="$first/wrapper"
EVIDENCE_REFRESH_SERVICE_PATH="$first/service"
EVIDENCE_REFRESH_TIMER_PATH="$first/timer"
EVIDENCE_REFRESH_SERVICE="refresh.service"
EVIDENCE_REFRESH_TIMER="refresh.timer"
wrapper_backup="$first/backups/wrapper"
service_backup="$first/backups/service"
timer_backup="$first/backups/timer"
printf new >"$EVIDENCE_REFRESH_WRAPPER"
printf new >"$EVIDENCE_REFRESH_SERVICE_PATH"
printf new >"$EVIDENCE_REFRESH_TIMER_PATH"
old_wrapper_present=0
old_service_present=0
old_timer_present=0
old_timer_enabled=not-found
old_timer_active=inactive
old_timer_should_be_enabled=0
old_timer_should_be_active=0
unit_snapshot_complete=1
unit_mutation_started=1
FAKE_ENABLED_STATE=not-found
FAKE_ACTIVE_STATE=inactive
: >"$CALL_LOG"
restore_evidence_refresh_units
printf '%s\n' RELEASE_MAINTENANCE >>"$CALL_LOG"
restore_evidence_refresh_timer_activity
[[ ! -e "$EVIDENCE_REFRESH_WRAPPER" && ! -e "$EVIDENCE_REFRESH_SERVICE_PATH" && ! -e "$EVIDENCE_REFRESH_TIMER_PATH" ]]
! grep -Fq 'SYSTEMCTL:start refresh.timer' "$CALL_LOG"

upgrade="$TEST_ROOT/upgrade"
mkdir -p "$upgrade/backups"
EVIDENCE_REFRESH_WRAPPER="$upgrade/wrapper"
EVIDENCE_REFRESH_SERVICE_PATH="$upgrade/service"
EVIDENCE_REFRESH_TIMER_PATH="$upgrade/timer"
wrapper_backup="$upgrade/backups/wrapper"
service_backup="$upgrade/backups/service"
timer_backup="$upgrade/backups/timer"
printf old-wrapper >"$wrapper_backup"; chmod 0755 "$wrapper_backup"
printf old-service >"$service_backup"; chmod 0644 "$service_backup"
printf old-timer >"$timer_backup"; chmod 0644 "$timer_backup"
printf new-wrapper >"$EVIDENCE_REFRESH_WRAPPER"
printf new-service >"$EVIDENCE_REFRESH_SERVICE_PATH"
printf new-timer >"$EVIDENCE_REFRESH_TIMER_PATH"
chmod 0600 "$EVIDENCE_REFRESH_WRAPPER"
chmod 0700 "$EVIDENCE_REFRESH_SERVICE_PATH"
chmod 0600 "$EVIDENCE_REFRESH_TIMER_PATH"
case "$PWD" in
  /mnt/[a-zA-Z]/*) ;;
  *)
    [[ "$(stat -c %a "$EVIDENCE_REFRESH_WRAPPER")" != "$(stat -c %a "$wrapper_backup")" ]]
    [[ "$(stat -c %a "$EVIDENCE_REFRESH_SERVICE_PATH")" != "$(stat -c %a "$service_backup")" ]]
    [[ "$(stat -c %a "$EVIDENCE_REFRESH_TIMER_PATH")" != "$(stat -c %a "$timer_backup")" ]]
    ;;
esac
old_wrapper_present=1
old_service_present=1
old_timer_present=1
old_timer_enabled=enabled
old_timer_active=active
old_timer_should_be_enabled=1
old_timer_should_be_active=1
unit_snapshot_complete=1
unit_mutation_started=1
FAKE_ENABLED_STATE=enabled
FAKE_ACTIVE_STATE=active
: >"$CALL_LOG"
restore_evidence_refresh_units
printf '%s\n' RELEASE_MAINTENANCE >>"$CALL_LOG"
restore_evidence_refresh_timer_activity
cmp -s "$wrapper_backup" "$EVIDENCE_REFRESH_WRAPPER"
cmp -s "$service_backup" "$EVIDENCE_REFRESH_SERVICE_PATH"
cmp -s "$timer_backup" "$EVIDENCE_REFRESH_TIMER_PATH"
[[ "$(stat -c %a "$EVIDENCE_REFRESH_WRAPPER")" == "$(stat -c %a "$wrapper_backup")" ]]
[[ "$(stat -c %a "$EVIDENCE_REFRESH_SERVICE_PATH")" == "$(stat -c %a "$service_backup")" ]]
[[ "$(stat -c %a "$EVIDENCE_REFRESH_TIMER_PATH")" == "$(stat -c %a "$timer_backup")" ]]
release_line="$(grep -n '^RELEASE_MAINTENANCE$' "$CALL_LOG" | cut -d: -f1)"
start_line="$(grep -n '^SYSTEMCTL:start refresh.timer$' "$CALL_LOG" | cut -d: -f1)"
[[ -n "$release_line" && -n "$start_line" && "$release_line" -lt "$start_line" ]]
grep -Fqx 'SYSTEMCTL:enable refresh.timer' "$CALL_LOG"

FAKE_SERVICE_DROPIN_PROPERTY=DropInPaths=
FAKE_TIMER_DROPIN_PROPERTY=DropInPaths=
verify_no_evidence_refresh_dropins
FAKE_SERVICE_DROPIN_PROPERTY=""
FAKE_TIMER_DROPIN_PROPERTY=""
set +e
verify_no_evidence_refresh_dropins
dropin_unsupported_rc=$?
set -e
[[ "$dropin_unsupported_rc" != "0" ]]
FAKE_SERVICE_DROPIN_PROPERTY=DropInPaths=
FAKE_TIMER_DROPIN_PROPERTY=DropInPaths=/etc/systemd/system/refresh.timer.d/override.conf
set +e
verify_no_evidence_refresh_dropins
dropin_nonempty_rc=$?
set -e
[[ "$dropin_nonempty_rc" != "0" ]]

dry_run_candidate=""
release_dir=""
create_dry_run_candidate
[[ -d "$dry_run_candidate" ]]
touch "$dry_run_candidate/proof"
cleanup_dry_run_candidate "$dry_run_candidate"
[[ ! -e "$dry_run_candidate" ]]
printf '%s\n' FIXTURE_PASS
"""
        result = run_bash_fixture(fixture, temp, "runtime-fixture.sh")
        if result.returncode != 0 or "FIXTURE_PASS" not in result.stdout:
            failures.append(
                "runtime fixture failed rc="
                + str(result.returncode)
                + " stdout="
                + result.stdout[-1000:]
                + " stderr="
                + result.stderr[-1000:]
            )

        dry_signal_functions = extract_bash_functions(
            apply,
            (
                "create_dry_run_candidate",
                "cleanup_dry_run_candidate",
                "dry_run_cleanup_handler",
                "arm_dry_run_cleanup_traps",
            ),
        )
        for signal_name, expected_rc in (("TERM", 143), ("HUP", 129)):
            dry_signal = f"""#!/usr/bin/env bash
set -euo pipefail
{dry_signal_functions}
dry_run_candidate=""
release_dir=""
dry_run_cleanup_active=0
arm_dry_run_cleanup_traps
create_dry_run_candidate
printf 'CANDIDATE=%s\n' "$dry_run_candidate"
touch "$dry_run_candidate/proof"
kill -{signal_name} $$
printf '%s\n' SHOULD_NOT_REACH
"""
            result = run_bash_fixture(
                dry_signal, temp, f"dry-signal-{signal_name.lower()}.sh"
            )
            candidate_matches = re.findall(
                r"/tmp/jiejing-production-dry-run-[^/\r\n]{8}\.d", result.stdout
            )
            candidate = candidate_matches[-1] if candidate_matches else ""
            if result.returncode != expected_rc:
                failures.append(
                    f"dry-run {signal_name} fixture wrong rc:{result.returncode}"
                )
            if not candidate:
                failures.append(f"dry-run {signal_name} fixture did not expose candidate")
            elif fixture_bash_path_exists(
                candidate, temp, f"dry-{signal_name.lower()}-exists.sh"
            ):
                failures.append(f"dry-run {signal_name} fixture left candidate:{candidate}")
                cleanup_result = cleanup_fixture_bash_path(
                    candidate, temp, f"dry-{signal_name.lower()}-cleanup.sh"
                )
                if cleanup_result.returncode != 0:
                    failures.append(
                        f"dry-run {signal_name} fixture cleanup failed rc:"
                        f"{cleanup_result.returncode}"
                    )
            if "SHOULD_NOT_REACH" in result.stdout + result.stderr:
                failures.append(f"dry-run {signal_name} fixture crossed signal boundary")

        cleanup_call = (
            '    cleanup_dry_run_candidate "$dry_run_candidate" || exit_code=39'
        )
        mutated_dry_functions = dry_signal_functions.replace(
            cleanup_call,
            "    : # MUTATION: intentionally skip candidate cleanup",
            1,
        )
        if mutated_dry_functions == dry_signal_functions:
            failures.append("dry-run cleanup mutation target was not found")
        else:
            mutation_fixture = f"""#!/usr/bin/env bash
set -euo pipefail
{mutated_dry_functions}
dry_run_candidate=""
release_dir=""
dry_run_cleanup_active=0
arm_dry_run_cleanup_traps
create_dry_run_candidate
printf 'CANDIDATE=%s\n' "$dry_run_candidate"
touch "$dry_run_candidate/proof"
kill -TERM $$
"""
            mutation_result = run_bash_fixture(
                mutation_fixture, temp, "dry-signal-cleanup-mutation.sh"
            )
            mutation_matches = re.findall(
                r"/tmp/jiejing-production-dry-run-[^/\r\n]{8}\.d",
                mutation_result.stdout,
            )
            mutation_candidate = mutation_matches[-1] if mutation_matches else ""
            mutation_detected = bool(mutation_candidate) and fixture_bash_path_exists(
                mutation_candidate, temp, "dry-mutation-exists.sh"
            )
            if not mutation_detected:
                failures.append(
                    "dry-run dynamic fixture did not detect a no-op cleanup mutation"
                )
            if mutation_candidate and mutation_detected:
                mutation_cleanup = cleanup_fixture_bash_path(
                    mutation_candidate, temp, "dry-mutation-cleanup.sh"
                )
                if mutation_cleanup.returncode != 0:
                    failures.append(
                        "dry-run mutation leftover cleanup failed rc:"
                        + str(mutation_cleanup.returncode)
                    )
                elif fixture_bash_path_exists(
                    mutation_candidate, temp, "dry-mutation-absent.sh"
                ):
                    failures.append("dry-run mutation cleanup left its fixture candidate")

        interrupt_functions = extract_bash_functions(
            apply,
            (
                "restore_root_file",
                "restore_evidence_refresh_units",
                "restore_evidence_refresh_timer_activity",
                "fail_unit_transaction",
                "unit_transaction_signal_handler",
                "unit_transaction_exit_handler",
                "arm_unit_transaction_traps",
            ),
        )
        interrupt = f"""#!/usr/bin/env bash
set -euo pipefail
{interrupt_functions}
TEST_ROOT="$PWD/{relative_temp}/interrupt"
mkdir -p "$TEST_ROOT/backups"
EVIDENCE_REFRESH_WRAPPER="$TEST_ROOT/wrapper"
EVIDENCE_REFRESH_SERVICE_PATH="$TEST_ROOT/service"
EVIDENCE_REFRESH_TIMER_PATH="$TEST_ROOT/timer"
EVIDENCE_REFRESH_SERVICE=refresh.service
EVIDENCE_REFRESH_TIMER=refresh.timer
wrapper_backup="$TEST_ROOT/backups/wrapper"
service_backup="$TEST_ROOT/backups/service"
timer_backup="$TEST_ROOT/backups/timer"
printf new >"$EVIDENCE_REFRESH_WRAPPER"
printf new >"$EVIDENCE_REFRESH_SERVICE_PATH"
printf new >"$EVIDENCE_REFRESH_TIMER_PATH"
old_wrapper_present=0
old_service_present=0
old_timer_present=0
old_timer_enabled=not-found
old_timer_active=inactive
old_timer_should_be_enabled=0
old_timer_should_be_active=0
unit_snapshot_complete=1
unit_mutation_started=1
unit_transaction_active=0
unit_transaction_failure_in_progress=0
current_stage=fixture_interrupt
second_signal_sent=0
systemctl() {{
  if [[ "$second_signal_sent" == "0" ]]; then
    second_signal_sent=1
    kill -INT $$
  fi
  case "${{1:-}}" in
    is-enabled) printf '%s\n' not-found ;;
    is-active) printf '%s\n' inactive ;;
  esac
  return 0
}}
release_maintenance_lock() {{ printf '%s\n' RELEASE_MAINTENANCE; }}
release_deploy_lock() {{ printf '%s\n' RELEASE_DEPLOY; }}
acquire_maintenance_lock_for_rollback() {{ maintenance_lock_held=1; printf '%s\n' ACQUIRE_ROLLBACK_MAINTENANCE; }}
rollback_application_release() {{ printf '%s\n' APPLICATION_ROLLBACK; return 0; }}
arm_unit_transaction_traps
kill -TERM $$
printf '%s\n' SHOULD_NOT_REACH
"""
        result = run_bash_fixture(interrupt, temp, "interrupt-fixture.sh")
        combined = result.stdout + result.stderr
        if result.returncode != 143:
            failures.append(f"TERM fixture wrong rc:{result.returncode}")
        for marker in (
            "TIMER_INSTALL_ROLLED_BACK=1",
            "APPLICATION_RELEASE_RETAINED=0",
            "JIEJING_PRODUCTION_ROLLBACK_APPLIED=1",
            "APPLICATION_ROLLBACK",
            "RELEASE_MAINTENANCE",
            "RELEASE_DEPLOY",
        ):
            if marker not in combined:
                failures.append(f"TERM fixture missing:{marker}")
        if "SHOULD_NOT_REACH" in combined:
            failures.append("TERM fixture crossed the application rollback/success boundary")
        interrupt_root = temp / "interrupt"
        for name in ("wrapper", "service", "timer"):
            if (interrupt_root / name).exists():
                failures.append(f"TERM fixture left first-install target:{name}")

        unexpected_exit = interrupt.replace(
            f"{relative_temp}/interrupt", f"{relative_temp}/unexpected-exit"
        ).replace("kill -TERM $$", "exit 9")
        result = run_bash_fixture(unexpected_exit, temp, "exit-fixture.sh")
        combined = result.stdout + result.stderr
        if result.returncode != 9:
            failures.append(f"EXIT fixture wrong rc:{result.returncode}")
        for marker in (
            "TIMER_INSTALL_ROLLED_BACK=1",
            "APPLICATION_RELEASE_RETAINED=0",
            "JIEJING_PRODUCTION_ROLLBACK_APPLIED=1",
            "APPLICATION_ROLLBACK",
            "RELEASE_MAINTENANCE",
            "RELEASE_DEPLOY",
        ):
            if marker not in combined:
                failures.append(f"EXIT fixture missing:{marker}")
        exit_root = temp / "unexpected-exit"
        for name in ("wrapper", "service", "timer"):
            if (exit_root / name).exists():
                failures.append(f"EXIT fixture left first-install target:{name}")

        lock_failure = (
            interrupt.replace(
                f"{relative_temp}/interrupt", f"{relative_temp}/lock-failure"
            )
            .replace(
                "arm_unit_transaction_traps\nkill -TERM $$",
                "acquire_maintenance_lock_for_rollback() { echo ACQUIRE_ROLLBACK_MAINTENANCE_FAILED; return 1; }\n"
                "restore_evidence_refresh_units() { echo UNIT_RESTORE_CALLED; return 0; }\n"
                "restore_evidence_refresh_timer_activity() { echo TIMER_ACTIVITY_CALLED; return 0; }\n"
                "rollback_application_release() { echo APPLICATION_ROLLBACK_CALLED; return 0; }\n"
                "arm_unit_transaction_traps\nkill -TERM $$",
            )
        )
        result = run_bash_fixture(lock_failure, temp, "lock-failure-fixture.sh")
        combined = result.stdout + result.stderr
        if result.returncode != 143:
            failures.append(f"rollback lock-failure fixture wrong rc:{result.returncode}")
        for forbidden_marker in (
            "UNIT_RESTORE_CALLED",
            "TIMER_ACTIVITY_CALLED",
            "APPLICATION_ROLLBACK_CALLED",
            "TIMER_INSTALL_ROLLED_BACK=1",
            "JIEJING_PRODUCTION_ROLLBACK_APPLIED=1",
        ):
            if forbidden_marker in combined:
                failures.append(
                    f"rollback proceeded without maintenance lock:{forbidden_marker}"
                )
        if "JIEJING_PRODUCTION_ROLLBACK_INCOMPLETE=1" not in combined:
            failures.append("rollback lock failure was not reported as incomplete")
    return failures


def validate_missing_bash_fails_whole_test() -> list[str]:
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        result = main(
            bash_resolver=lambda _name: None,
            run_prerequisite_self_test=False,
        )
    rendered = output.getvalue()
    if result != 1:
        return ["missing bash did not fail the complete deploy-channel contract test"]
    if f"FAIL {BASH_REQUIRED_MESSAGE}" not in rendered:
        return ["missing bash failure did not expose the required prerequisite clearly"]
    return []


def validate_runtime_evidence_bootstrap() -> list[str]:
    """The first candidate must have a verified snapshot before it starts."""
    apply = read(APPLY)
    compose = read(COMPOSE)
    failures: list[str] = []
    if 'current_stage="initialize_runtime_evidence_snapshot"' not in apply:
        return ["candidate startup has no runtime evidence initialization"]
    init = apply.index('current_stage="initialize_runtime_evidence_snapshot"')
    if not apply.index('if [[ "$DRY_RUN" == "1" ]]') < init < apply.index('current_stage="start_candidate_api"'):
        failures.append("snapshot initialization must be after dry-run exit and before API start")
    if compose.count('JIEJING_RUNTIME_EVIDENCE_FILE: "/run/jiejing-production-evidence/current.json"') != 2:
        failures.append("both API and Worker must select the fixed runtime evidence file")
    if compose.count('/opt/jiejing-production/runtime-evidence:/run/jiejing-production-evidence:ro') != 2:
        failures.append("both services must mount the evidence directory read-only")
    block = apply[apply.index("runtime_evidence_result_verified() {"):apply.index("\nverify_runtime_labels_and_health() {")]
    good = {"status": "prepared", "contract_version": "jiejing_runtime_evidence_snapshot_v1", "writes_snapshot": False, "secret_exposed": False}
    fixtures = [
        (json.dumps(good), True),
        ('{"status":"blocked",' + json.dumps(good)[1:], False),
        (json.dumps({**good, "secret_exposed": "false"}), False),
        (json.dumps({**good, "writes_snapshot": 0}), False),
        (json.dumps({**good, "unexpected": True}), False),
        ("{invalid", False),
    ]
    import shlex
    bash = require_bash_contract()
    for payload, expected in fixtures:
        completed = subprocess.run([bash, "-s"], input=(block + "\nprintf '%s' " + shlex.quote(payload) + " | runtime_evidence_result_verified prepared\n").encode(), stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
        if (completed.returncode == 0) != expected:
            failures.append("runtime evidence bootstrap JSON contract accepted invalid or rejected valid result")
    # Execute the real bootstrap. Only the process boundaries are replaced:
    # no Docker daemon, private env, provider, or production path is accessed.
    bootstrap_fixture = r'''
set -euo pipefail
exec 3>&1
candidate_app=/candidate
private_dir=/private-source
candidate_api_image_id=sha256:fixture-api
candidate_worker_image_id=sha256:fixture-worker
python3() {
  if [[ "$1" == /candidate/tools/jiejing_runtime_evidence_snapshot.py ]]; then
    [[ "$*" == '/candidate/tools/jiejing_runtime_evidence_snapshot.py --prepare-directory --output-dir /opt/jiejing-production/runtime-evidence' ]] || return 91
    echo PREPARE >&3
    [[ "$TEST_CASE" != prepare_exit ]] || return 7
    if [[ "$TEST_CASE" == prepare_invalid ]]; then echo '{}'; return 0; fi
    echo '{"status":"prepared","contract_version":"jiejing_runtime_evidence_snapshot_v1","writes_snapshot":false,"secret_exposed":false}'
  else
    command python3 "$@"
  fi
}
docker() {
  case "$*" in
    'run --rm --network none -w /app sha256:fixture-api python tools/jiejing_runtime_evidence_snapshot.py --check-capability')
      echo API_CAPABILITY >&3
      [[ "$TEST_CASE" != api_exit ]] || return 8
      if [[ "$TEST_CASE" == api_invalid ]]; then echo '{}'; return 0; fi
      echo '{"status":"capable","contract_version":"jiejing_runtime_evidence_snapshot_v1","writes_snapshot":false,"secret_exposed":false}'
      ;;
    'run --rm --network none -w /app sha256:fixture-worker python tools/jiejing_runtime_evidence_snapshot.py --check-capability')
      echo WORKER_CAPABILITY >&3
      [[ "$TEST_CASE" != worker_exit ]] || return 9
      if [[ "$TEST_CASE" == worker_invalid ]]; then echo '{}'; return 0; fi
      echo '{"status":"capable","contract_version":"jiejing_runtime_evidence_snapshot_v1","writes_snapshot":false,"secret_exposed":false}'
      ;;
    'run --rm --network none --mount type=bind,src=/private-source,dst=/private,readonly --mount type=bind,src=/opt/jiejing-production/runtime-evidence,dst=/runtime-evidence -w /app sha256:fixture-api python tools/jiejing_runtime_evidence_snapshot.py --env-file /private/jiejing-saas.production.env --output-dir /runtime-evidence')
      echo SNAPSHOT >&3
      [[ "$TEST_CASE" != snapshot_exit ]] || return 10
      case "$TEST_CASE" in
        snapshot_invalid) echo '{}';;
        snapshot_extra) echo '{"status":"verified","contract_version":"jiejing_runtime_evidence_snapshot_v1","secret_exposed":false,"evidence_sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","extra":1}';;
        snapshot_bad_hash) echo '{"status":"verified","contract_version":"jiejing_runtime_evidence_snapshot_v1","secret_exposed":false,"evidence_sha256":"bad"}';;
        snapshot_duplicate) echo '{"status":"blocked","status":"verified","contract_version":"jiejing_runtime_evidence_snapshot_v1","secret_exposed":false,"evidence_sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}';;
        snapshot_nonbool) echo '{"status":"verified","contract_version":"jiejing_runtime_evidence_snapshot_v1","secret_exposed":0,"evidence_sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}';;
        *) echo '{"status":"verified","contract_version":"jiejing_runtime_evidence_snapshot_v1","secret_exposed":false,"evidence_sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}';;
      esac
      ;;
    *) echo UNEXPECTED_DOCKER_ARGUMENTS >&3; return 92;;
  esac
}
initialize_runtime_evidence_snapshot
echo CANDIDATE_MAY_START
'''
    phases = ["PREPARE", "API_CAPABILITY", "WORKER_CAPABILITY", "SNAPSHOT"]
    bootstrap_cases = {
        "success": 4, "prepare_exit": 1, "prepare_invalid": 1,
        "api_exit": 2, "api_invalid": 2,
        "worker_exit": 3, "worker_invalid": 3,
        "snapshot_exit": 4, "snapshot_invalid": 4, "snapshot_extra": 4,
        "snapshot_bad_hash": 4, "snapshot_duplicate": 4, "snapshot_nonbool": 4,
    }
    for case, phase_count in bootstrap_cases.items():
        script = block + "\nTEST_CASE=" + shlex.quote(case) + "\n" + bootstrap_fixture
        completed = subprocess.run([bash, "-s"], input=script.encode(), stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
        output = completed.stdout.decode("utf-8", errors="replace").splitlines()
        expected = phases[:phase_count]
        if case == "success":
            expected += ["EVIDENCE_SNAPSHOT_INITIALIZED=1", "CANDIDATE_MAY_START"]
        if output != expected or (completed.returncode == 0) != (case == "success"):
            failures.append(f"runtime evidence bootstrap ordering/failure boundary failed:{case}")
    return failures


def main(
    bash_resolver=shutil.which,
    *,
    run_prerequisite_self_test: bool = True,
) -> int:
    try:
        require_bash_contract(bash_resolver)
    except RuntimeError as exc:
        return fail(str(exc))
    if run_prerequisite_self_test:
        prerequisite_failures = validate_missing_bash_fails_whole_test()
        if prerequisite_failures:
            return fail("; ".join(prerequisite_failures))
    evidence_failures = validate_runtime_evidence_bootstrap()
    if evidence_failures:
        return fail("; ".join(evidence_failures))
    try:
        client = read(CLIENT)
        apply = read(APPLY)
        retired_failures = validate_retired_diagnostic_exclusions(apply)
        if retired_failures:
            return fail("; ".join(retired_failures))
        compose = read(COMPOSE)
        patch_apply = read(PATCH_APPLY)
        ci = read(CI)
        runbook = read(RUNBOOK)
        precloud_gate = read(PRECLOUD_GATE)
    except FileNotFoundError as exc:
        return fail(f"missing production deploy channel file: {exc}")

    required_client = [
        'DEFAULT_HOST = "43.129.169.223"',
        "DEFAULT_PORT = 22",
        'Path.home() / ".ssh" / "jiejing_production_hk_ed25519"',
        'choices=("dry_run", "apply")',
        'EXPECTED_CONFIRM = "deploy app.jiejing.shop production"',
        "bundle_sha256_mismatch",
        "manifest_scope_invalid",
        "validate_bundle_manifest(bundle, manifest, allowed_files, expected_source_commit)",
        "validate_local_release_candidate(",
        "apply_patch_file_list(source_sha)",
        'git_blob_bytes(source_commit, "deploy/apply-staging-patch.sh")',
        "source_commit_file_hashes(source_sha, allowed_files)",
        "validate_bundle_matches_source_commit(",
        "bundle_source_commit_mismatch:",
        "assert_source_state(source_sha)",
        "build_remote_integrity_prelude(",
        "REMOTE_ARTIFACT_SHA256_MISMATCH",
        "trap cleanup_remote_artifacts EXIT",
        r'rm -f -- \"$REMOTE_ZIP_UPLOAD\" \"$REMOTE_ZIP\"',
        r'rm -f -- \"$REMOTE_MANIFEST_UPLOAD\" \"$REMOTE_MANIFEST\"',
        r'rm -rf -- \"$REMOTE_DIR\"',
        "remote_manifest_upload",
        "validate_atomic_frontend_release(bundle, manifest)",
        "manifest_source_commit_mismatch",
        "manifest_file_hash_scope_invalid",
        "duplicate_entries",
        "frontend_files_sha256",
        "validate_bundle_javascript(bundle)",
        "local_node_unavailable",
        "bundle_javascript_invalid",
        '"jiejing_saas/migrations/002_media_credit_buckets_postgres.sql"',
        '"jiejing_saas/migrations/003_runtime_schema_reconciliation_postgres.sql"',
        '"jiejing_saas/migrations/004_platform_model_trial_reservations_postgres.sql"',
        "StrictHostKeyChecking=yes",
        "IdentitiesOnly=yes",
        "BatchMode=yes",
        "ServerAliveInterval=15",
        "ServerAliveCountMax=12",
        "TCPKeepAlive=yes",
        "JIEJING_PRODUCTION_DEPLOY_CONFIRM",
        "JIEJING_PRODUCTION_DEPLOY_DRY_RUN",
        "jiejing-production-release-apply.sh",
        '"secret_exposed": False',
        "PRODUCTION_REMOTE_APPLY_TIMEOUT_SECONDS",
        "PHASE3_REQUIRED_BUNDLE_FILES",
        *[f'"{name}"' for name in sorted(PHASE3_BUNDLE_FILES)],
    ]
    required_apply = [
        'EXPECTED_CONFIRM="deploy app.jiejing.shop production"',
        'PRODUCTION_ROOT="/opt/jiejing-production"',
        'ACTIVE_LINK="$PRODUCTION_ROOT/app"',
        'RELEASE_ROOT="$PRODUCTION_ROOT/releases"',
        "REFUSE_PRODUCTION_CONFIRMATION_MISMATCH",
        "REFUSE_INVALID_PRODUCTION_DRY_RUN",
        "REFUSE_PATCH_DIR_OUTSIDE_TMP",
        "REFUSE_ACTIVE_RELEASE_OUTSIDE_ROOT",
        "REFUSE_PRIVATE_MANIFEST_CONTRACT=1",
        "com.docker.compose.project.environment_file",
        "JIEJING_PRODUCTION_PRIVATE_DIR",
        "docker compose",
        "--project-name deploy",
        "build jiejing-saas jiejing-worker",
        "up -d --no-deps jiejing-saas",
        "up -d --no-deps jiejing-worker",
        "up -d --no-deps --force-recreate jiejing-frontend",
        "up -d --no-deps --force-recreate jiejing-edge",
        'PUBLIC_URL="https://app.jiejing.shop"',
        'wait_public_json "/health"',
        'wait_public_json "/health/deep"',
        'wait_public_json "/readiness/product-saas"',
        'data.get("status") == "ok"',
        'health.get("status") == "ready"',
        'readiness = data.get("readiness") or {}',
        'readiness.get("environment") == "production"',
        'readiness.get("public_contract_version")',
        'PRODUCTION_PUBLIC_CHECK_FAILED=',
        "JIEJING_PRODUCTION_DEPLOY_DRY_RUN=1",
        "JIEJING_PRODUCTION_DEPLOY_APPLIED=1",
        "JIEJING_PRODUCTION_ROLLBACK_APPLIED=1",
        "JIEJING_PRODUCTION_DEPLOY_FAILED_STAGE=",
        "build_candidate_images_with_retry",
        "JIEJING_PRODUCTION_BUILD_RETRY=",
        "trap rollback_on_error ERR",
        "chmod -R go-w",
        "JIEJING_PRODUCTION_RELEASE_MANIFEST.txt",
        'DEPLOY_LOCK="/run/lock/jiejing-production-deploy.lock"',
        'MAINTENANCE_LOCK="/run/lock/jiejing-production-maintenance.lock"',
        "REFUSE_PRODUCTION_DEPLOY_LOCK_BUSY=1",
        "REFUSE_PRODUCTION_MAINTENANCE_LOCK_BUSY=1",
        "REFUSE_FLOCK_UNAVAILABLE=1",
        "REFUSE_LOCK_OPEN_FAILED=",
        "REFUSE_LOCK_ACQUIRE_FAILED=",
        "validate_evidence_refresh_candidate",
        "bash -n",
        "systemd-analyze verify",
        "TIMER_INSTALL_APPLIED=1",
        "TIMER_FIRST_ONESHOT_VERIFIED=1",
        "TIMER_INSTALL_ROLLED_BACK=1",
        "APPLICATION_RELEASE_RETAINED=0",
        "InvocationID",
        "ExecMainStatus",
        "JIEJING_PRODUCTION_EVIDENCE_REFRESH_STATUS=success",
        "NextElapseUSecRealtime",
        "restore_evidence_refresh_units",
        "restore_evidence_refresh_timer_activity",
        "cmp -s",
        '[[ "$after_invocation" =~ ^[0-9a-f]{32}$ ]]',
        "JIEJING_PRODUCTION_EVIDENCE_REFRESH_STATUS=skipped",
        "JIEJING_PRODUCTION_EVIDENCE_REFRESH_STATUS=blocked",
        "JIEJING_PRODUCTION_EVIDENCE_REFRESH_BLOCKER=",
        "SECRET_EXPOSED=true",
        "SECRET_EXPOSED=false",
        "JIEJING_PRODUCTION_UNIT_TRANSACTION_FAILED_STAGE=",
        "unit_transaction_active=0",
        "unit_transaction_failure_in_progress=0",
        "unit_transaction_signal_handler",
        "unit_transaction_exit_handler",
        "arm_unit_transaction_traps",
        "disarm_unit_transaction_traps",
        "DropInPaths",
        "REFUSE_EVIDENCE_REFRESH_DROPINS=1",
        "create_dry_run_candidate",
        "cleanup_dry_run_candidate",
        "arm_dry_run_cleanup_traps",
        "REFUSE_DRY_RUN_CANDIDATE_UNTRUSTED=1",
        "CANDIDATE_RELEASE_PERSISTED=0",
        "PRIVATE_ENV_NORMALIZATION_REQUIRED=",
        "PRIVATE_ENV_NORMALIZATION_PLANNED=",
        "PRIVATE_ENV_NORMALIZATION_APPLIED=0",
        "normalize_private_env_permissions",
        "capture_previous_runtime_images",
        "capture_candidate_runtime_images",
        "verify_candidate_runtime_image_coherence",
        "atomic_replace_active_link",
        "rollback_application_release",
        "finalize_evidence_refresh_transaction",
        'ROLLBACK_API_HOLD_REF="jiejing-production-rollback-api:previous"',
        'ROLLBACK_WORKER_HOLD_REF="jiejing-production-rollback-worker:previous"',
        "ROLLBACK_IMAGE_HOLDS_VERIFIED=1",
        "CANDIDATE_RUNTIME_IMAGE_COHERENCE=verified",
    ]
    required_compose = [
        "${JIEJING_PRODUCTION_PRIVATE_DIR:-../../private}/jiejing-saas.production.env",
        "${JIEJING_PRODUCTION_PRIVATE_DIR:-../../private}/jiejing-vault-token.d/jiejing-vault-token",
        "${JIEJING_PRODUCTION_PRIVATE_DIR:-../../private}/jiejing-vault-token.d:/run/jiejing-vault-token-output",
    ]
    required_patch_whitelist = [
        '"deploy/jiejing-production-release-apply.sh"',
        '"tools/jiejing_production_deploy.py"',
        '"tools/test_jiejing_production_deploy_channel.py"',
        '"docs/JIEJING_PRODUCTION_DEPLOY_RUNBOOK_20260823.md"',
        *[f'"{name}"' for name in sorted(PHASE3_BUNDLE_FILES)],
        '"jiejing_saas/migrations/002_media_credit_buckets_postgres.sql"',
        '"jiejing_saas/migrations/003_runtime_schema_reconciliation_postgres.sql"',
        '"jiejing_saas/migrations/004_platform_model_trial_reservations_postgres.sql"',
    ]
    required_ci = [
        "python tools/test_jiejing_production_deploy_channel.py",
        "python tools/test_jiejing_production_evidence_auto_refresh_guardrails.py",
    ]
    required_runbook = [
        "正式生产主机",
        "dry_run",
        "deploy app.jiejing.shop production",
        "不复制任何密钥",
        "失败自动回滚",
        "production_ready",
        "can_accept_real_customers",
        "warning_count",
        "真实扣款、退款或 eBay 写入",
        "/run/lock/jiejing-production-deploy.lock",
        "/run/lock/jiejing-production-maintenance.lock",
        "`dry_run` 不获取任何锁",
        "TIMER_INSTALL_ROLLED_BACK=1",
        "APPLICATION_RELEASE_RETAINED=0",
        "InvocationID",
        "NextElapseUSecRealtime",
        "DropInPaths",
        "3600",
        "SIGKILL",
        "jiejing-production-rollback-api:previous",
        "jiejing-production-rollback-worker:previous",
        "禁止 image prune",
    ]

    missing: list[str] = []
    for prefix, text, markers in (
        ("client", client, required_client),
        ("apply", apply, required_apply),
        ("compose", compose, required_compose),
        ("patch", patch_apply, required_patch_whitelist),
        ("ci", ci, required_ci),
        ("runbook", runbook, required_runbook),
        (
            "precloud",
            precloud_gate,
            ["production_evidence_auto_refresh_guardrails"],
        ),
    ):
        missing.extend(f"{prefix}:{marker}" for marker in markers if marker not in text)
    if missing:
        return fail("production deploy channel missing markers: " + ",".join(missing))
    initial_source_check = client.index("assert_source_state(source_sha)")
    pinned_whitelist = client.index("apply_patch_file_list(source_sha)", initial_source_check)
    source_blob_validation = client.index("source_commit_file_hashes(source_sha, allowed_files)")
    initial_validation = client.index(
        "manifest_sha256 = validate_local_release_candidate("
    )
    sealed_validation = client.index("validate_local_release_candidate(", initial_validation + 1)
    final_source_check = client.index("assert_source_state(source_sha)", sealed_validation)
    if "upload(args, bundle, remote_zip)" in client:
        return fail("production upload must use sealed temporary artifacts, not mutable source paths")
    sealed_bundle_upload = client.index("upload(args, sealed_bundle, remote_zip_upload)")
    sealed_manifest_upload = client.index("upload(args, sealed_manifest, remote_manifest_upload)")
    post_upload_source_check = client.index(
        "assert_source_state(source_sha)", sealed_manifest_upload
    )
    remote_prelude = client.index("build_remote_integrity_prelude(", post_upload_source_check)
    remote_apply = client.index('"sudo -n env "', remote_prelude)
    if not (
        initial_source_check
        < pinned_whitelist
        < source_blob_validation
        < initial_validation
        < sealed_validation
        < final_source_check
        < sealed_bundle_upload
        < sealed_manifest_upload
        < post_upload_source_check
        < remote_prelude
        < remote_apply
    ):
        return fail("sealed local and received remote artifacts are not revalidated before apply")

    bundle_failures = validate_required_bundle_files()
    if bundle_failures:
        return fail("; ".join(bundle_failures))
    atomic_frontend_failures = validate_atomic_frontend_manifest()
    if atomic_frontend_failures:
        return fail("; ".join(atomic_frontend_failures))
    stdout_contract_failures = validate_remote_stdout_contract()
    if stdout_contract_failures:
        return fail("; ".join(stdout_contract_failures))
    oneshot_failures = validate_first_oneshot_classification(apply)
    if oneshot_failures:
        return fail("; ".join(oneshot_failures))
    private_env_failures = validate_private_env_runtime_fixture(apply)
    if private_env_failures:
        return fail("; ".join(private_env_failures))

    application_rollback_failures = validate_application_rollback_runtime_fixture(apply)
    if application_rollback_failures:
        return fail("; ".join(application_rollback_failures))

    for hold_pin in (
        'docker image tag "$previous_api_image_id" "$ROLLBACK_API_HOLD_REF" || hold_rc=1',
        'docker image tag "$previous_worker_image_id" "$ROLLBACK_WORKER_HOLD_REF" || hold_rc=1',
    ):
        if apply.count(hold_pin) != 1:
            return fail("rollback image hold pin is not uniquely mutation-testable:" + hold_pin)
        mutated = apply.replace(hold_pin, ": # hold pin mutation", 1)
        if not validate_application_rollback_runtime_fixture(mutated):
            return fail("stateful image store did not detect deleted hold pin:" + hold_pin)

    finalization_lock_failures = validate_finalization_lock_runtime_fixture(apply)
    if finalization_lock_failures:
        return fail("; ".join(finalization_lock_failures))

    deploy_module = load_deploy_module()
    timeout_budget = getattr(deploy_module, "PRODUCTION_REMOTE_APPLY_TIMEOUT_SECONDS", 0)
    if timeout_budget < 2700:
        return fail("production apply timeout does not cover oneshot, health, and build budget")
    timeout_start = client.index("remote_timeout =")
    timeout_end = client.index("completed = run(", timeout_start)
    timeout_section = client[timeout_start:timeout_end]
    if 'if args.mode == "apply"' not in timeout_section or "PRODUCTION_REMOTE_APPLY_TIMEOUT_SECONDS" not in timeout_section:
        return fail("long remote timeout is not scoped to apply mode")
    runtime_failures = validate_bash_runtime_fixture(apply)
    if runtime_failures:
        return fail("; ".join(runtime_failures))

    candidate_select = apply.index('if [[ "$DRY_RUN" == "1" ]]')
    candidate_else = apply.index("\nelse\n", candidate_select)
    candidate_select_end = apply.index("\nfi\n", candidate_else) + len("\nfi\n")
    dry_candidate_branch = apply[candidate_select:candidate_else]
    apply_candidate_branch = apply[candidate_else:candidate_select_end]
    forbidden_dry_candidate = ["acquire_deploy_lock", "acquire_maintenance_lock", "$RELEASE_ROOT", "systemctl", "journalctl"]
    present_dry_candidate = [
        marker for marker in forbidden_dry_candidate if marker in dry_candidate_branch
    ]
    if present_dry_candidate:
        return fail("dry-run candidate branch has production side effect: " + ",".join(present_dry_candidate))
    arm_dry_cleanup = dry_candidate_branch.index("arm_dry_run_cleanup_traps")
    create_dry_candidate = dry_candidate_branch.index(
        "create_dry_run_candidate", arm_dry_cleanup
    )
    if arm_dry_cleanup >= create_dry_candidate:
        return fail("dry-run cleanup traps must be armed before candidate creation")
    live_snapshot_start = apply.index('active_app="$(readlink -f -- "$ACTIVE_LINK"')
    docker_live_read = apply.index("docker inspect deploy-jiejing-saas-1", live_snapshot_start)
    lock_gate_start = apply.rindex(
        'if [[ "$DRY_RUN" == "0" ]]',
        apply.index('validate_evidence_refresh_candidate "$resolved_patch_dir"'),
        live_snapshot_start,
    )
    lock_gate_end = apply.index("\nfi\n", lock_gate_start) + len("\nfi\n")
    lock_gate = apply[lock_gate_start:lock_gate_end]
    if "else" in lock_gate:
        return fail("dry-run lock gate must not contain a locking else branch")
    deploy_lock = apply.index("acquire_deploy_lock", lock_gate_start, lock_gate_end)
    maintenance_lock = apply.index("acquire_maintenance_lock", deploy_lock)
    permanent_release = apply.index('release_dir="$RELEASE_ROOT/', docker_live_read)
    create_permanent_release = apply.index(
        'install -d -m 0750 -o root -g root "$release_dir"', permanent_release
    )
    if not (
        lock_gate_start
        < deploy_lock
        < maintenance_lock
        < lock_gate_end
        < live_snapshot_start
        < docker_live_read
        < permanent_release
        < create_permanent_release
        < candidate_select_end
    ):
        return fail("apply must acquire both locks before creating a permanent release")

    dry_run_exit = apply.index('if [[ "$DRY_RUN" == "1" ]]', candidate_select_end)
    dry_run_end = apply.index("\nfi\n", dry_run_exit) + len("\nfi\n")
    build_stage = apply.index('current_stage="build_candidate_images"')
    if not (candidate_select_end < dry_run_exit < dry_run_end < build_stage):
        return fail("dry-run must exit before container or active-link mutation")
    if "systemctl" in apply[:dry_run_end] or "journalctl" in apply[:dry_run_end]:
        return fail("dry-run preflight invokes systemd instead of remaining read-only")
    private_resolve = apply.index(
        'resolve_manifest_private_dir "$previous_release" "$environment_file"',
        docker_live_read,
    )
    private_assess = apply.index("assess_private_env_normalization", private_resolve)
    dry_run_block = apply[dry_run_exit:dry_run_end]
    if 'PRIVATE_ENV_NORMALIZATION_APPLIED=0' not in apply[private_assess:dry_run_end]:
        return fail("dry-run does not expose private env normalization state")

    normalize_function = apply[
        apply.index("normalize_private_env_permissions()") : apply.index(
            "require_flock()"
        )
    ]
    for marker in (
        "O_NOFOLLOW",
        "os.fstat",
        "os.fchown",
        "os.fchmod",
        "st_nlink != 1",
        "PRIVATE_ENV_NORMALIZATION_ROLLED_BACK=1",
    ):
        if marker not in normalize_function:
            return fail(f"private env normalization is not fd-safe:{marker}")
    normalize_call = apply.index("normalize_private_env_permissions", dry_run_end)
    if not dry_run_end < normalize_call < build_stage:
        return fail("apply must normalize exact private env targets before image build and active switch")

    unit_install = apply.index('current_stage="install_evidence_refresh_units"')
    active_switch = apply.index('current_stage="activate_release"')
    arm_full_rollback = apply.index("arm_unit_transaction_traps", active_switch)
    install_call = apply.index("install_evidence_refresh_units", unit_install)
    release_maintenance = apply.index("release_maintenance_lock", install_call)
    start_oneshot = apply.index("verify_first_evidence_refresh_oneshot", release_maintenance)
    verify_invocation = apply.index("TIMER_FIRST_ONESHOT_VERIFIED=1", start_oneshot)
    finalize_transaction = apply.index("finalize_evidence_refresh_transaction", verify_invocation)
    start_timer = apply.index("TIMER_INSTALL_APPLIED=1", finalize_transaction)
    disable_app_rollback = apply.index("trap - ERR", start_timer)
    release_deploy = apply.index("release_deploy_lock", disable_app_rollback)
    if not (
        active_switch
        < arm_full_rollback
        < unit_install
        < install_call
        < release_maintenance
        < start_oneshot
        < verify_invocation
        < finalize_transaction
        < start_timer
        < disable_app_rollback
        < release_deploy
    ):
        return fail("unit transaction or lock release order is unsafe")

    finalization_function = apply[
        apply.index("finalize_evidence_refresh_transaction()") : apply.index(
            "fail_unit_transaction()"
        )
    ]
    final_acquire = finalization_function.index("acquire_maintenance_lock")
    final_coherence = finalization_function.index(
        "verify_candidate_runtime_image_coherence", final_acquire
    )
    final_timer = finalization_function.index(
        "start_and_verify_evidence_refresh_timer", final_coherence
    )
    final_release = finalization_function.index(
        "release_maintenance_lock", final_timer
    )
    if not final_acquire < final_coherence < final_timer < final_release:
        return fail("final timer/coherence commit is not maintenance-lock protected")

    install_function = apply[
        apply.index("install_evidence_refresh_units()") : apply.index(
            "verify_first_evidence_refresh_oneshot()"
        )
    ]
    install_verify = install_function.index("systemd-analyze verify")
    daemon_reload = install_function.index("systemctl daemon-reload", install_verify)
    enable_timer = install_function.index(
        'systemctl enable "$EVIDENCE_REFRESH_TIMER"', daemon_reload
    )
    if not install_verify < daemon_reload < enable_timer:
        return fail("unit install must verify, reload, then enable without starting timer")
    if 'systemctl start "$EVIDENCE_REFRESH_TIMER"' in install_function:
        return fail("unit install starts timer while maintenance lock is held")

    oneshot_function = apply[
        apply.index("verify_first_evidence_refresh_oneshot()") : apply.index(
            "start_and_verify_evidence_refresh_timer()"
        )
    ]
    oneshot_start = oneshot_function.index('systemctl start "$EVIDENCE_REFRESH_SERVICE"')
    oneshot_invocation = oneshot_function.index("InvocationID", oneshot_start)
    oneshot_result = oneshot_function.index("ExecMainStatus", oneshot_invocation)
    oneshot_journal = oneshot_function.index(
        "JIEJING_PRODUCTION_EVIDENCE_REFRESH_STATUS=success", oneshot_result
    )
    if not oneshot_start < oneshot_invocation < oneshot_result < oneshot_journal:
        return fail("first oneshot is not bound to its verified invocation journal")
    if "grep -Fxc 'SECRET_EXPOSED=false'" not in oneshot_function:
        return fail("first oneshot does not require the value-free safety marker exactly once")

    forbidden_dry_run = ["systemctl", "journalctl", "flock", "evidence-auto-refresh.sh"]
    present_dry_run = [marker for marker in forbidden_dry_run if marker in dry_run_block]
    if present_dry_run:
        return fail("dry-run contains side effect: " + ",".join(present_dry_run))

    rollback_start = apply.index("restore_evidence_refresh_units()")
    rollback_end = apply.index("restore_evidence_refresh_timer_activity()", rollback_start)
    rollback_body = apply[rollback_start:rollback_end]
    for marker in ("old_wrapper_present", "old_service_present", "old_timer_present"):
        if marker not in rollback_body:
            return fail(f"unit rollback does not cover first-install/upgrade state: {marker}")
    no_snapshot_guard = (
        '[[ "$unit_snapshot_complete" != "1" || "$unit_mutation_started" != "1" ]]'
    )
    if no_snapshot_guard not in rollback_body:
        return fail("unit rollback may mutate systemd before a complete snapshot and mutation")
    restore_stop = rollback_body.index('systemctl stop "$EVIDENCE_REFRESH_TIMER"')
    restore_guard = rollback_body.index(no_snapshot_guard)
    if restore_guard > restore_stop:
        return fail("unit rollback guard must precede every systemctl mutation")
    if 'systemctl start "$EVIDENCE_REFRESH_TIMER"' in rollback_body:
        return fail("unit files rollback starts old timer while maintenance lock is held")

    failed_transaction = apply[
        apply.index("fail_unit_transaction()") : apply.index("rollback_on_error()")
    ]
    fail_handler_end = failed_transaction.index("unit_transaction_signal_handler()")
    fail_handler = failed_transaction[:fail_handler_end]
    recursion_guard = fail_handler.index(
        'if [[ "$unit_transaction_failure_in_progress" == "1" ]]'
    )
    recursion_guard_end = fail_handler.index("fi", recursion_guard)
    ignore_secondary_signals = fail_handler.index("trap '' HUP INT TERM")
    set_failure_guard = fail_handler.index("unit_transaction_failure_in_progress=1")
    if not recursion_guard_end < ignore_secondary_signals < set_failure_guard:
        return fail("unit rollback must ignore secondary signals immediately after recursion guard")
    restore_files = failed_transaction.index("restore_evidence_refresh_units")
    rollback_application = failed_transaction.index("rollback_application_release", restore_files)
    release_failed_maintenance = failed_transaction.index(
        "release_maintenance_lock", rollback_application
    )
    restore_activity = failed_transaction.index(
        "restore_evidence_refresh_timer_activity", release_failed_maintenance
    )
    release_failed_deploy = failed_transaction.index("release_deploy_lock", restore_activity)
    if not (
        restore_files
        < rollback_application
        < release_failed_maintenance
        < restore_activity
        < release_failed_deploy
    ):
        return fail("failed unit transaction restores timer activity before releasing maintenance lock")

    dropin_check = apply[
        apply.index("verify_no_evidence_refresh_dropins()") : apply.index(
            "install_evidence_refresh_units()"
        )
    ]
    if "--value" in dropin_check or dropin_check.count('!= "DropInPaths="') != 2:
        return fail("DropInPaths must be present and exactly empty for both fixed units")

    atomic_install = apply[
        apply.index("atomic_install_root_file()") : apply.index("restore_root_file()")
    ]
    if "cmp -s" not in atomic_install:
        return fail("atomic root install does not verify candidate bytes")

    timer_verify = apply[
        apply.index("start_and_verify_evidence_refresh_timer()") : apply.index(
            "fail_unit_transaction()"
        )
    ]
    for invalid in ('""', '"n/a"', '"0"'):
        if invalid not in timer_verify:
            return fail(f"timer NextElapse validation does not reject {invalid}")

    build_call = apply.index("build_candidate_images_with_retry", build_stage)
    mutation_start = apply.index("mutation_started=1", build_stage)
    if mutation_start > build_call:
        return fail("candidate build must retain old-image rollback eligibility")

    capture_stage = apply.index('current_stage="capture_previous_runtime_images"', dry_run_end)
    capture_images = apply.index("capture_previous_runtime_images", capture_stage + 1)
    capture_candidate_stage = apply.index(
        'current_stage="capture_candidate_runtime_images"', build_stage
    )
    capture_candidate_images = apply.index(
        "capture_candidate_runtime_images", capture_candidate_stage + 1
    )
    start_candidate_api = apply.index('current_stage="start_candidate_api"', build_stage)
    start_candidate_worker = apply.index('current_stage="start_candidate_worker"', start_candidate_api)
    verify_images = apply.index("verify_candidate_runtime_image_coherence", start_candidate_worker)
    if not (
        normalize_call
        < capture_images
        < build_call
        < capture_candidate_stage
        < capture_candidate_images
        < start_candidate_api
        < start_candidate_worker
        < verify_images
        < active_switch
    ):
        return fail("runtime image snapshot/coherence ordering is unsafe")
    atomic_link_function = apply[
        apply.index("atomic_replace_active_link()") : apply.index(
            "rollback_application_release()"
        )
    ]
    for marker in ('readlink -f', 'ln -s --', 'mv -Tf --', 'expected_current'):
        if marker not in atomic_link_function:
            return fail(f"active link replacement is not atomic/verified:{marker}")
    if 'ln -sfnT "$candidate_app" "$ACTIVE_LINK"' in apply:
        return fail("candidate activation still uses a non-transactional symlink replacement")
    app_rollback = apply[
        apply.index("rollback_application_release()") : apply.index(
            "rollback_on_error()"
        )
    ]
    for marker in (
        "previous_api_image_id",
        "previous_worker_image_id",
        "docker image tag",
        'docker image tag "$ROLLBACK_API_HOLD_REF" "$previous_api_image_ref"',
        'docker image tag "$ROLLBACK_WORKER_HOLD_REF" "$previous_worker_image_ref"',
        "verify_previous_runtime_restored",
        'atomic_replace_active_link "$active_app" "$candidate_app"',
        'wait_public_json "/health"',
        'wait_public_json "/health/deep"',
        'wait_public_json "/readiness/product-saas"',
    ):
        if marker not in app_rollback:
            return fail(f"application rollback does not restore exact old runtime:{marker}")
    bare_api_restore = (
        'docker image tag "$previous_api_image_id" "$previous_api_image_ref"'
    )
    bare_worker_restore = (
        'docker image tag "$previous_worker_image_id" "$previous_worker_image_ref"'
    )
    if bare_api_restore in app_rollback or bare_worker_restore in app_rollback:
        return fail("application rollback still depends on unpinned bare image IDs")

    forbidden = [
        "StrictHostKeyChecking=no",
        "systemctl enable --now",
        "docker compose down -v",
        "docker volume rm",
        "docker image prune",
        "docker builder prune",
        "docker system prune",
        "DROP DATABASE",
        "JIEJING_EBAY_ACCESS_TOKEN",
        "JIEJING_EBAY_REFRESH_TOKEN",
        "JIEJING_WECHAT_PAY_API_V3_KEY",
        "OPENAI_API_KEY",
        "rm -rf /",
    ]
    combined = client + "\n" + apply
    present = [marker for marker in forbidden if marker in combined]
    if present:
        return fail("production deploy channel contains forbidden marker: " + ",".join(present))

    print("PASS jiejing_production_deploy_channel")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
